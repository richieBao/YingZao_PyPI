# -*- coding: utf-8 -*-
"""
PointDirectionalHitOnSurfaceLike
点沿给定方向在“平面/曲面/网格/Brep 等几何对象”上的
“优先求交点 / 退化用投影点(最近点)” 求解器

------------------------------------------------------------
输入（GhPython 建议设置）:
    Pt : rg.Point3d (Item)
        输入点
        Access: Item
        TypeHints: Point3d

    Geo : object (Item)
        目标几何：优先支持 Plane / Surface / Brep / Mesh / Extrusion
        也可输入其它可转成 Brep/Mesh 的几何
        Access: Item
        TypeHints: (No hints) 或 Geometry

    Direction : rg.Vector3d (Item)
        方向向量（不要求单位化；为零向量会报错）
        Access: Item
        TypeHints: Vector3d

    Tol : float (Item)
        容差（用于求交与判断），默认 1e-6
        Access: Item
        TypeHints: float

    RayLength : float (Item)
        用于模拟“射线”的线段长度，默认 1e6
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    HitPt : rg.Point3d (Item)
        新交点（优先：射线与几何交点；退化：点到几何最近点投影）
        Access: Item
        TypeHints: Point3d

    HitSeg : rg.Line (Item)
        Pt -> HitPt 的线段
        Access: Item
        TypeHints: Line

    Log : str (Item)
        日志（说明使用了哪种策略、失败原因等）
        Access: Item
        TypeHints: str
------------------------------------------------------------

核心策略：
1) 优先：从 Pt 沿 Direction 作“射线(很长的线段)”与目标几何求交；
   - 若存在交点，且交点位于射线正向（t >= 0），取沿方向最近的那个。
2) 退而求其次：若无交点（或都在反向），则取 Pt 到目标几何的最近点（ClosestPoint）作为“投影点”。

注：
- 对 Plane：用 Line-Plane 求交；退化为垂足投影。
- 对 Mesh：用 Intersection.LineMesh；退化用 Mesh.ClosestPoint。
- 对 Brep/Surface/Extrusion：尽量转为 Brep 后用 Intersection.LineBrep；
  退化用 Brep.ClosestPoint。
"""

import Rhino
import Rhino.Geometry as rg


class PointDirectionalHitOnSurfaceLike(object):
    def __init__(self, pt, geo, direction, tol=1e-6, ray_length=1e6):
        self.pt = pt
        self.geo_in = geo
        self.direction = direction
        self.tol = tol if (tol is not None and tol > 0) else 1e-6
        self.ray_length = ray_length if (ray_length is not None and ray_length > 0) else 1e6

        self.HitPt = None
        self.HitSeg = None
        self.Log = ""

        self._solve()

    # -------------------------
    # basic validate
    # -------------------------
    @staticmethod
    def _is_valid_point(pt):
        return isinstance(pt, rg.Point3d) and pt.IsValid

    @staticmethod
    def _is_valid_vec(v):
        return isinstance(v, rg.Vector3d) and v.IsValid and (v.Length > 0)

    # -------------------------
    # conversions
    # -------------------------
    @staticmethod
    def _try_get_plane(obj):
        """若 obj 本身是 Plane 或可转换为 Plane，则返回 (True, plane)"""
        if obj is None:
            return False, None
        if isinstance(obj, rg.Plane):
            return True, obj
        if isinstance(obj, rg.PlaneSurface):
            # PlaneSurface 可取其 Plane
            return True, obj.Plane
        return False, None

    @staticmethod
    def _try_get_mesh(obj):
        if obj is None:
            return None
        if isinstance(obj, rg.Mesh):
            return obj
        # 尝试把 Brep/Surface 转 mesh（轻量化尝试）
        try:
            brep = rg.Brep.TryConvertBrep(obj)
            if brep:
                meshes = rg.Mesh.CreateFromBrep(brep, rg.MeshingParameters.Default)
                if meshes and len(meshes) > 0:
                    m = rg.Mesh()
                    for mm in meshes:
                        m.Append(mm)
                    m.Normals.ComputeNormals()
                    m.Compact()
                    return m
        except:
            pass
        return None

    @staticmethod
    def _try_get_brep(obj):
        if obj is None:
            return None
        if isinstance(obj, rg.Brep):
            return obj
        if isinstance(obj, rg.Extrusion):
            try:
                return obj.ToBrep()
            except:
                return None
        if isinstance(obj, rg.Surface):
            try:
                return obj.ToBrep()
            except:
                return None
        if isinstance(obj, rg.Curve):
            # 曲线不在本组件目标范围内；这里直接 None
            return None
        # 最通用的 TryConvert
        try:
            return rg.Brep.TryConvertBrep(obj)
        except:
            return None

    # -------------------------
    # ray line builder
    # -------------------------
    def _build_forward_ray_line(self):
        """用很长 Line 模拟射线：Pt -> Pt + dir_unit * ray_length"""
        d = rg.Vector3d(self.direction)
        d.Unitize()
        a = self.pt
        b = self.pt + d * float(self.ray_length)
        return rg.Line(a, b), d  # (line, dir_unit)

    # -------------------------
    # forward filtering
    # -------------------------
    def _pick_nearest_forward(self, cand_pts, dir_unit):
        """
        只保留位于 Pt 沿 dir_unit 正向（含容差）的点，并取最近
        返回 Point3d or None
        """
        good = []
        for p in cand_pts:
            if p is None:
                continue
            v = p - self.pt
            t = rg.Vector3d.Multiply(v, dir_unit)  # 点积=沿方向标量
            if t >= -self.tol:
                good.append((t, p))
        if not good:
            return None
        good.sort(key=lambda x: x[0])
        return good[0][1]

    # -------------------------
    # intersection methods
    # -------------------------
    def _intersect_line_plane(self, line, plane):
        ok, t = rg.Intersect.Intersection.LinePlane(line, plane, self.tol)
        if not ok:
            return None
        # RhinoCommon: t 是 line 的参数（0..1 对应线段），但也可能超出
        # 我们允许超出，但后面会用 forward 过滤
        return line.PointAt(t)

    def _intersect_line_mesh(self, line, mesh):
        # 返回参数 t 列表（沿 Line.Direction 的距离参数），以及点
        try:
            t_list = rg.Intersect.Intersection.LineMesh(line, mesh)
            if not t_list:
                return []
            pts = []
            for t in t_list:
                pts.append(line.PointAt(t))
            return pts
        except:
            return []

    def _intersect_line_brep(self, line, brep):
        try:
            # Intersection.LineBrep 返回 CurveIntersections
            x = rg.Intersect.Intersection.LineBrep(line, brep, self.tol)
            if not x:
                return []
            pts = []
            for evt in x:
                if evt and evt.IsPoint:
                    pts.append(evt.PointA)
            return pts
        except:
            return []

    # -------------------------
    # fallback closest point
    # -------------------------
    def _closest_point_on_plane(self, plane):
        # 垂足投影（正交投影）
        return plane.ClosestPoint(self.pt)

    def _closest_point_on_mesh(self, mesh):
        # MeshPoint
        try:
            mp = mesh.ClosestMeshPoint(self.pt, 0.0)
            if mp is None:
                return None
            return mesh.PointAt(mp)
        except:
            return None

    def _closest_point_on_brep(self, brep):
        try:
            ok, cp, ci, s, t = brep.ClosestPoint(self.pt, self.tol)
            if ok:
                return cp
            # 再试一次不带 tol
            ok2, cp2, ci2, s2, t2 = brep.ClosestPoint(self.pt)
            if ok2:
                return cp2
        except:
            pass
        return None

    # -------------------------
    # main solve
    # -------------------------
    def _solve(self):
        if not self._is_valid_point(self.pt):
            self.Log = "ERROR: Pt is invalid or None."
            return
        if self.geo_in is None:
            self.Log = "ERROR: Geo is None."
            return
        if not self._is_valid_vec(self.direction):
            self.Log = "ERROR: Direction is invalid / zero-length."
            return

        ray_line, dir_unit = self._build_forward_ray_line()

        # 1) Plane path (fast & exact)
        is_plane, pln = self._try_get_plane(self.geo_in)
        if is_plane and pln is not None:
            hit = self._intersect_line_plane(ray_line, pln)
            if hit is not None:
                # forward check
                pick = self._pick_nearest_forward([hit], dir_unit)
                if pick is not None:
                    self.HitPt = pick
                    self.HitSeg = rg.Line(self.pt, self.HitPt)
                    self.Log = "OK: Hit by Line-Plane intersection (forward)."
                    return
            # fallback
            proj = self._closest_point_on_plane(pln)
            if proj is not None and proj.IsValid:
                self.HitPt = proj
                self.HitSeg = rg.Line(self.pt, self.HitPt)
                self.Log = "FALLBACK: No valid forward Line-Plane hit; used Plane.ClosestPoint."
                return
            self.Log = "ERROR: Plane fallback failed."
            return

        # 2) Mesh path
        mesh = self._try_get_mesh(self.geo_in)
        if mesh is not None and mesh.IsValid:
            pts = self._intersect_line_mesh(ray_line, mesh)
            pick = self._pick_nearest_forward(pts, dir_unit)
            if pick is not None:
                self.HitPt = pick
                self.HitSeg = rg.Line(self.pt, self.HitPt)
                self.Log = "OK: Hit by Line-Mesh intersection (forward). Hits=%d" % len(pts)
                return
            # fallback
            proj = self._closest_point_on_mesh(mesh)
            if proj is not None and proj.IsValid:
                self.HitPt = proj
                self.HitSeg = rg.Line(self.pt, self.HitPt)
                self.Log = "FALLBACK: No valid forward Line-Mesh hit; used Mesh closest point."
                return
            self.Log = "ERROR: Mesh fallback failed."
            return

        # 3) Brep / Surface / Extrusion path
        brep = self._try_get_brep(self.geo_in)
        if brep is not None and brep.IsValid:
            pts = self._intersect_line_brep(ray_line, brep)
            pick = self._pick_nearest_forward(pts, dir_unit)
            if pick is not None:
                self.HitPt = pick
                self.HitSeg = rg.Line(self.pt, self.HitPt)
                self.Log = "OK: Hit by Line-Brep intersection (forward). Hits=%d" % len(pts)
                return
            # fallback
            proj = self._closest_point_on_brep(brep)
            if proj is not None and proj.IsValid:
                self.HitPt = proj
                self.HitSeg = rg.Line(self.pt, self.HitPt)
                self.Log = "FALLBACK: No valid forward Line-Brep hit; used Brep closest point."
                return
            self.Log = "ERROR: Brep fallback failed."
            return

        # 4) last resort: try any geometry closest point via Point3d.ClosestPoint on common types
        self.Log = "ERROR: Unsupported Geo type (cannot convert to Plane/Mesh/Brep)."

if __name__ == '__main__':
    # =====================================================
    # GH Python 组件入口
    # =====================================================

    try:
        _tol = Tol
    except:
        _tol = 1e-6

    try:
        _ray_len = RayLength
    except:
        _ray_len = 1e6

    Solver = PointDirectionalHitOnSurfaceLike(Pt, Geo, Direction, _tol, _ray_len)

    HitPt = Solver.HitPt
    HitSeg = Solver.HitSeg
    Log = Solver.Log
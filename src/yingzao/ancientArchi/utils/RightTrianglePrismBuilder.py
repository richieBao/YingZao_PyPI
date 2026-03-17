"""
GhPython Component: RightTriangle_Prism (Class-based)
----------------------------------------------------
【类/方法结构】便于后续在别的组件里复用调用。

Inputs (GH 中建议这样配置):
    theta      : float        Access:item  (单位: 度)  角度 θ
    h          : float        Access:item  高度 h
    base_point : rg.Point3d   Access:item  默认=World Origin  (O 点)
    ref_plane  : object       Access:item  默认="WorldXZ" 或直接传 rg.Plane
    offset     : float        Access:item  默认=5.0  两侧偏移距离(沿 ref_plane 法向 ±offset)

Outputs:
    dist          : float              A-O 距离
    SectionCurve  : rg.PolylineCurve   原始三角截面曲线 (A-O-B-A)
    SectionPts    : list[Point3d]      [A,O,B,A]
    BrepSolid     : rg.Brep            最终封闭体 (可能为 None)
    BrepParts     : list[rg.Brep]      [side_brep, cap1_brep, cap2_brep]
    OPlanes       : list[rg.Plane]     过 O 点的三个互相垂直参考平面 [P0, Px, Py]
    Log           : str
"""

import math
import Rhino.Geometry as rg
import scriptcontext as sc




class RightTrianglePrismBuilder(object):
    """
    生成直角三角形截面 + 双侧偏移成体的构造器。

    关键点：
    - 参考平面轴向严格按 GH 的 XY/XZ/YZ 定义，不依赖 rg.Plane.WorldXZ 等不存在的字段。
    - 端面 cap 使用 CreateFromCornerPoints（比 CreatePlanarBreps 更稳）。
    - 输出三个过 O 点、互相垂直参考平面：P0(输入参考面), Px(含X轴), Py(含Y轴)。
    """

    def __init__(self, theta_deg, h, base_point=None, ref_plane=None, offset=5.0, tol=None, default_plane_tag="WorldXZ"):
        self.theta_deg = theta_deg
        self.h = h
        self.base_point = base_point if base_point is not None else rg.Point3d(0, 0, 0)
        self.ref_plane_input = ref_plane
        self.offset = float(offset) if offset is not None else 5.0
        self.default_plane_tag = default_plane_tag

        doc_tol = sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6
        self.tol = float(tol) if tol is not None else doc_tol

        # outputs / state
        self.dist = None
        self.section_pts = None
        self.section_curve = None
        self.o_planes = []
        self.brep_parts = []
        self.brep_solid = None
        self.log = ""

        # internal
        self._plO = None
        self._A3 = None
        self._O3 = None
        self._B3 = None

    # --------------------------
    # static helpers
    # --------------------------
    @staticmethod
    def _safe_float(x, default=None):
        try:
            if x is None:
                return default
            return float(x)
        except:
            return default

    @staticmethod
    def _make_gh_plane(tag, origin):
        """
        按 GH 的参考平面轴向定义构造 Plane：
        XY: X=(1,0,0) Y=(0,1,0) Z=(0,0,1)
        XZ: X=(1,0,0) Y=(0,0,1) Z=(0,-1,0)
        YZ: X=(0,1,0) Y=(0,0,1) Z=(1,0,0)
        """
        tag = (tag or "WorldXZ").strip().lower()

        if tag in ("worldxy", "xy"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 1, 0)
            return rg.Plane(origin, x, y)

        if tag in ("worldxz", "xz"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)
            return rg.Plane(origin, x, y)

        if tag in ("worldyz", "yz"):
            x = rg.Vector3d(0, 1, 0)
            y = rg.Vector3d(0, 0, 1)
            return rg.Plane(origin, x, y)

        # fallback -> XZ
        x = rg.Vector3d(1, 0, 0)
        y = rg.Vector3d(0, 0, 1)
        return rg.Plane(origin, x, y)

    @classmethod
    def _coerce_plane(cls, x, base_point, default_tag="WorldXZ"):
        """支持 rg.Plane / 'WorldXY|WorldXZ|WorldYZ' / 'XY|XZ|YZ' / None"""
        if isinstance(x, rg.Plane):
            pl = rg.Plane(x)
            pl.Origin = base_point
            return pl
        if x is None:
            return cls._make_gh_plane(default_tag, base_point)
        if isinstance(x, (str, bytes)):
            return cls._make_gh_plane(str(x), base_point)
        return cls._make_gh_plane(default_tag, base_point)

    @staticmethod
    def _make_o_planes(p0):
        """
        给定过 O 点的参考平面 p0，构造另外两个也过 O 点的互相垂直平面：
          - Px: 垂直于 p0，且包含 p0.XAxis 方向（通过 O）
          - Py: 垂直于 p0，且包含 p0.YAxis 方向（通过 O）
        返回 [p0, px, py]
        """
        o = p0.Origin
        x = rg.Vector3d(p0.XAxis)
        y = rg.Vector3d(p0.YAxis)
        z = rg.Vector3d(p0.ZAxis)

        x.Unitize()
        y.Unitize()
        z.Unitize()

        px = rg.Plane(o, x, z)
        py = rg.Plane(o, y, z)
        return [p0, px, py]

    # --------------------------
    # build steps
    # --------------------------
    def validate_and_compute_dist(self):
        th = self._safe_float(self.theta_deg, None)
        hh = self._safe_float(self.h, None)
        if th is None or hh is None:
            self.log = "theta 或 h 为空，无法计算。"
            return False

        theta_rad = math.radians(th)
        t = math.tan(theta_rad)
        eps = 1e-12
        if abs(t) < eps:
            self.dist = float("inf")
            self.log = "theta 接近 0° 或 180°，tan(theta)≈0，dist→∞。"
            return False

        self.dist = hh / t
        return True

    def build_reference_planes(self):
        self._plO = self._coerce_plane(self.ref_plane_input, self.base_point, self.default_plane_tag)
        self.o_planes = self._make_o_planes(self._plO)
        return True

    def build_section(self):
        """
        在参考平面坐标中构造直角三角形：
            O = (0,0)
            A = (-dist, 0)
            B = (-dist, h)
        """
        if self._plO is None:
            self.log = "Reference plane not built."
            return False
        if self.dist is None or (isinstance(self.dist, float) and (math.isinf(self.dist) or math.isnan(self.dist))):
            self.log = "dist 无效，无法构造截面。"
            return False

        # local points
        O2 = rg.Point3d(0.0, 0.0, 0.0)
        A2 = rg.Point3d(-self.dist, 0.0, 0.0)
        B2 = rg.Point3d(-self.dist, float(self.h), 0.0)

        # to world
        self._O3 = self._plO.PointAt(O2.X, O2.Y)
        self._A3 = self._plO.PointAt(A2.X, A2.Y)
        self._B3 = self._plO.PointAt(B2.X, B2.Y)

        self.section_pts = [self._A3, self._O3, self._B3, self._A3]
        pline = rg.Polyline(self.section_pts)
        self.section_curve = rg.PolylineCurve(pline)
        self.section_curve.MakeClosed(self.tol)
        return True

    def build_solid(self):
        """
        1) 截面沿法向 ±offset 平移两份
        2) Loft 生成侧面
        3) 端面用 CreateFromCornerPoints 做两片三角面
        4) Join / CapPlanarHoles
        """
        if self.section_curve is None or self._plO is None:
            self.log = "Section not built."
            return False

        # normal
        n = rg.Vector3d(self._plO.ZAxis)
        if not n.Unitize():
            self.log = "参考平面法向无法单位化。"
            return False

        vpos = n * self.offset
        vneg = n * (-self.offset)

        x1 = rg.Transform.Translation(vpos)
        x2 = rg.Transform.Translation(vneg)

        # curves
        c1 = self.section_curve.DuplicateCurve()
        c2 = self.section_curve.DuplicateCurve()
        c1.Transform(x1)
        c2.Transform(x2)
        c1.MakeClosed(self.tol)
        c2.MakeClosed(self.tol)

        # loft side
        lofts = rg.Brep.CreateFromLoft([c1, c2], rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)
        side_brep = lofts[0] if lofts and len(lofts) > 0 else None
        if side_brep is None:
            self.log = "Loft 失败：无法生成侧面 Brep。"
            return False

        # cap by corner points (robust)
        A0, O0, B0 = self._A3, self._O3, self._B3

        A1, O1, B1 = rg.Point3d(A0), rg.Point3d(O0), rg.Point3d(B0)
        A2p, O2p, B2p = rg.Point3d(A0), rg.Point3d(O0), rg.Point3d(B0)
        A1.Transform(x1); O1.Transform(x1); B1.Transform(x1)
        A2p.Transform(x2); O2p.Transform(x2); B2p.Transform(x2)

        cap1_brep = rg.Brep.CreateFromCornerPoints(A1, O1, B1, self.tol)
        cap2_brep = rg.Brep.CreateFromCornerPoints(A2p, B2p, O2p, self.tol)  # 反序让外法向更一致
        if cap1_brep is None or cap2_brep is None:
            self.log = "Cap 失败：CreateFromCornerPoints 返回 None（检查 tol / 点是否重合）。"
            return False

        parts = [side_brep, cap1_brep, cap2_brep]
        self.brep_parts = parts

        joined = rg.Brep.JoinBreps(parts, self.tol)
        if not joined or len(joined) == 0:
            # fallback
            tmp = side_brep.DuplicateBrep() if side_brep else None
            tmp = tmp.CapPlanarHoles(self.tol) if tmp else None
            if tmp and tmp.IsSolid:
                self.brep_solid = tmp
                self.log = "OK (CapPlanarHoles fallback)"
                return True
            self.log = "JoinBreps 失败且 fallback 失败。"
            return False

        self.brep_solid = joined[0]
        if not self.brep_solid.IsSolid:
            capped = self.brep_solid.CapPlanarHoles(self.tol)
            if capped and capped.IsSolid:
                self.brep_solid = capped
                self.log = "OK (joined + capped)"
                return True
            self.log = "生成了 Brep，但未成为 Solid（可能存在缝隙/容差问题）。"
            return True

        self.log = "OK"
        return True

    def run(self):
        """
        一键执行；永远不抛异常，失败原因写入 self.log。
        """
        try:
            ok = self.validate_and_compute_dist()
            if not ok:
                return self._pack()

            self.build_reference_planes()

            ok = self.build_section()
            if not ok:
                return self._pack()

            self.build_solid()
            return self._pack()

        except Exception as e:
            self.log = "Error: {}".format(e)
            return self._pack()

    def _pack(self):
        """统一输出"""
        return {
            "dist": self.dist,
            "SectionCurve": self.section_curve,
            "SectionPts": self.section_pts,
            "BrepSolid": self.brep_solid,
            "BrepParts": self.brep_parts,
            "OPlanes": self.o_planes,
            "Log": self.log
        }

if __name__ == "__main__":
    # =========================================================
    # GhPython 组件主调用区（输入输出绑定）
    # =========================================================
    # 默认值处理
    if base_point is None:
        base_point = rg.Point3d(0, 0, 0)

    builder = RightTrianglePrismBuilder(
        theta_deg=theta,
        h=h,
        base_point=base_point,
        ref_plane=ref_plane,   # 支持 Plane 或 "WorldXY"/"WorldXZ"/"WorldYZ"
        offset=offset,
        tol=(sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6),
        default_plane_tag="WorldXZ"
    )

    _out = builder.run()

    dist = _out["dist"]
    SectionCurve = _out["SectionCurve"]
    SectionPts = _out["SectionPts"]
    BrepSolid = _out["BrepSolid"]
    BrepParts = _out["BrepParts"]
    OPlanes = _out["OPlanes"]
    Log = _out["Log"]

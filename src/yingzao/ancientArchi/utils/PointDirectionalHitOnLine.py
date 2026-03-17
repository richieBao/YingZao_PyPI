# -*- coding: utf-8 -*-
"""
PointDirectionalHitOnLine
点沿给定方向在直线上的“优先求交点 / 退化用投影点”求解器

------------------------------------------------------------
输入（GhPython 建议设置）:
    Pt : rg.Point3d (Item)
        输入点
        Access: Item
        TypeHints: Point3d

    LineCrv : rg.Curve (Item)
        输入直线（建议为 LineCurve / Line / 可转 Curve 的直线几何）
        Access: Item
        TypeHints: Curve

    Direction : rg.Vector3d (Item)
        方向向量（不要求单位化；为零向量会报错）
        Access: Item
        TypeHints: Vector3d

    Tol : float (Item)
        容差（用于求交与判断），默认 1e-6
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    HitPt : rg.Point3d (Item)
        新交点（优先：射线与直线交点；退化：点到直线投影点）
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
1) 优先：从 Pt 沿 Direction 作“射线(很长的线段)”与输入直线求交；
   - 若交点存在，且交点位于射线的正向（t >= 0），取该交点。
2) 退而求其次：若无交点（或交点在反向），则取 Pt 到输入直线的最近点投影。

注意：
- 输入必须是“直线”性质的 Curve（允许 LineCurve / 可 IsLinear 的 Curve）
- 若 LineCrv 不是直线，会尝试按 Curve 最近点投影（仍能工作，但“沿方向求交”的意义会弱化）
"""

import Rhino
import Rhino.Geometry as rg


class PointDirectionalHitOnLine(object):
    def __init__(self, pt, line_crv, direction, tol=1e-6):
        self.pt = pt
        self.line_crv_in = line_crv
        self.direction = direction
        self.tol = tol if (tol is not None and tol > 0) else 1e-6

        self.HitPt = None
        self.HitSeg = None
        self.Log = ""

        self._solve()

    # -------------------------
    # helpers
    # -------------------------
    @staticmethod
    def _as_curve(obj):
        """尽量把输入转成 Curve；失败则返回 None"""
        if obj is None:
            return None
        if isinstance(obj, rg.Curve):
            return obj
        if isinstance(obj, rg.Line):
            return rg.LineCurve(obj)
        if isinstance(obj, rg.LineCurve):
            return obj
        # 其它类型尝试转换
        try:
            c = rg.Curve.TryConvert(obj)
            return c
        except:
            return None

    @staticmethod
    def _is_valid_point(pt):
        return isinstance(pt, rg.Point3d) and pt.IsValid

    @staticmethod
    def _is_valid_vec(v):
        return isinstance(v, rg.Vector3d) and v.IsValid and (v.Length > 0)

    def _build_forward_ray_segment(self, length=1e6):
        """用很长线段模拟射线：Pt -> Pt + dir_unit * length"""
        d = rg.Vector3d(self.direction)
        d.Unitize()
        a = self.pt
        b = self.pt + d * float(length)
        return rg.LineCurve(a, b), d  # 返回“射线线段curve”与单位方向

    def _try_intersect_line_like(self, crvA, crvB):
        """
        求交：Curve-Curve
        返回：交点列表 [Point3d]
        """
        if crvA is None or crvB is None:
            return []
        x = Rhino.Geometry.Intersect.Intersection.CurveCurve(crvA, crvB, self.tol, self.tol)
        if not x:
            return []
        pts = []
        for evt in x:
            if evt and evt.IsPoint:
                pts.append(evt.PointA)
        return pts

    def _filter_forward_points(self, pts, dir_unit):
        """
        只保留位于 Pt 沿 dir_unit 正向（含容差）的点，并按“沿方向的参数距离”排序，取最近。
        """
        good = []
        for p in pts:
            v = p - self.pt
            t = rg.Vector3d.Multiply(v, dir_unit)  # 点积=沿方向标量
            if t >= -self.tol:
                good.append((t, p))
        good.sort(key=lambda x: x[0])
        return [p for _, p in good]

    def _project_closest_point(self, target_crv):
        """
        最近点投影：Pt 到 target_crv 的 ClosestPoint
        返回投影点 or None
        """
        if target_crv is None:
            return None
        ok, t = target_crv.ClosestPoint(self.pt, self.tol)
        if not ok:
            # 有些情况下不用 tol 也能得到
            ok2, t2 = target_crv.ClosestPoint(self.pt)
            if not ok2:
                return None
            t = t2
        return target_crv.PointAt(t)

    # -------------------------
    # main solve
    # -------------------------
    def _solve(self):
        # --- validate ---
        if not self._is_valid_point(self.pt):
            self.Log = "ERROR: Pt is invalid or None."
            return

        crv = self._as_curve(self.line_crv_in)
        if crv is None or (not crv.IsValid):
            self.Log = "ERROR: LineCrv is invalid or cannot be converted to Curve."
            return

        if not self._is_valid_vec(self.direction):
            self.Log = "ERROR: Direction is invalid / zero-length."
            return

        # --- strategy 1: ray intersection ---
        ray_crv, dir_unit = self._build_forward_ray_segment(length=1e6)

        pts_int = self._try_intersect_line_like(ray_crv, crv)
        pts_fwd = self._filter_forward_points(pts_int, dir_unit)

        if pts_fwd:
            self.HitPt = pts_fwd[0]
            self.HitSeg = rg.Line(self.pt, self.HitPt)
            self.Log = "OK: Hit by ray-line intersection (forward). Intersections=%d" % len(pts_int)
            return

        # --- fallback: projection (closest point) ---
        proj = self._project_closest_point(crv)
        if proj is not None and proj.IsValid:
            self.HitPt = proj
            self.HitSeg = rg.Line(self.pt, self.HitPt)
            self.Log = "FALLBACK: No valid forward intersection; used closest-point projection."
            return

        self.Log = "ERROR: Failed both intersection and projection. Check inputs/tolerance."

if __name__ == '__main__':
    # =====================================================
    # GH Python 组件入口
    # =====================================================

    # 兼容 GhPython 未提供 Tol 输入时的默认值
    try:
        _tol = Tol
    except:
        _tol = 1e-6

    Solver = PointDirectionalHitOnLine(Pt, LineCrv, Direction, _tol)

    HitPt = Solver.HitPt
    HitSeg = Solver.HitSeg
    Log = Solver.Log
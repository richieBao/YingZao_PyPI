# -*- coding: utf-8 -*-
"""
GhPython Component: AxisLines_Intersections_Solver
--------------------------------------------------
用 GH Python 实现附图的“轴线 + 平行线 + 交点 + 距离计算”。

========================
GH 输入端参数建议（Inputs）
========================
O           : Point3d   (Access=item, TypeHint=Point3d)   # 可不接；默认 World Origin
RefPlane    : Plane     (Access=item, TypeHint=Plane)     # 可不接；默认 GH 的 XY Plane
d           : float     (Access=item, TypeHint=float)     # OA/OB长度(=A、B距O沿RefPlane.Y方向)；默认 5.0
L12_len     : float     (Access=item, TypeHint=float)     # L1/L2长度；默认 96.84
L36_len     : float     (Access=item, TypeHint=float)     # L3~L6长度；默认 100.0
alpha_deg   : float     (Access=item, TypeHint=float)     # AO 与 AC/AD 夹角（左右相等）；默认 45.0
axis_len    : float     (Access=item, TypeHint=float)     # 仅用于显示轴线 AO/AC/AD 的长度；默认 140.0

=========================
GH 输出端参数建议（Outputs）
=========================
Axis_AO     : Line      (Access=item, TypeHint=Line)
Axis_AC     : Line      (Access=item, TypeHint=Line)
Axis_AD     : Line      (Access=item, TypeHint=Line)

L1          : Line      (Access=item, TypeHint=Line)
L2          : Line      (Access=item, TypeHint=Line)
L3          : Line      (Access=item, TypeHint=Line)
L4          : Line      (Access=item, TypeHint=Line)
L5          : Line      (Access=item, TypeHint=Line)
L6          : Line      (Access=item, TypeHint=Line)

O_out       : Point3d   (Access=item, TypeHint=Point3d)
A           : Point3d   (Access=item, TypeHint=Point3d)
B           : Point3d   (Access=item, TypeHint=Point3d)

J           : Point3d   (Access=item, TypeHint=Point3d)   # L2 ∩ L3
K           : Point3d   (Access=item, TypeHint=Point3d)   # L2 ∩ L6
Jp          : Point3d   (Access=item, TypeHint=Point3d)   # L1 ∩ L5
Kp          : Point3d   (Access=item, TypeHint=Point3d)   # L1 ∩ L6

Dist_BJ     : float     (Access=item, TypeHint=float)     # |B-J|
Dist_JK     : float     (Access=item, TypeHint=float)     # |J-K|

Log         : list[str] (Access=list, TypeHint=str)

---------------------------------
几何约定（与题述 / 附图一致）
---------------------------------
1) AO：过 O，沿 RefPlane.XAxis。
2) OA / OB：过 O，沿 RefPlane.YAxis 的正负方向各取长度 d，得到 A(+) 与 B(-)。
3) L1/L2：平行 AO，分别过 A、B，长度 L12_len。
4) AC/AD：过 O，分别在 RefPlane 内以 ±alpha_deg 旋转 AO 得到方向。
5) L3/L4：平行 AC，分别位于 AC 两侧（±d），长度 L36_len。
6) L5/L6：平行 AD，分别位于 AD 两侧（±d），长度 L36_len。
7) 交点：
   J  = L2 ∩ L3
   K  = L2 ∩ L6
   J' = L1 ∩ L5
   K' = L1 ∩ L4
"""

import math
import Rhino
from Rhino.Geometry import Point3d, Vector3d, Plane, Line, LineCurve, Transform, Curve
from Rhino.Geometry.Intersect import Intersection


class AxisLinesIntersectionsSolver(object):
    def __init__(self):
        self.Log = []

    # -------------------------
    # helpers
    # -------------------------
    def _default_plane(self):
        # GH 的 XY Plane
        return Plane.WorldXY

    def _ensure_point(self, p):
        if p is None:
            return Point3d.Origin
        if isinstance(p, Point3d):
            return p
        try:
            return Point3d(p)
        except Exception:
            return Point3d.Origin

    def _ensure_plane(self, pl):
        if pl is None:
            return self._default_plane()
        if isinstance(pl, Plane):
            return pl
        # 兼容 gh 输入可能是构造对象
        try:
            return Plane(pl)
        except Exception:
            return self._default_plane()

    def _rotate_in_plane(self, vec, plane, angle_rad):
        """
        在给定 plane 的法向量 around plane.ZAxis 旋转 vec。
        """
        xform = Transform.Rotation(angle_rad, plane.ZAxis, Point3d.Origin)
        v = Vector3d(vec)
        v.Transform(xform)
        return v

    def _make_centered_line(self, center_pt, dir_vec, length):
        """
        以 center_pt 为中点，沿 dir_vec 方向生成指定长度的 Line
        """
        v = Vector3d(dir_vec)
        if v.IsZero:
            v = Vector3d(1, 0, 0)
        v.Unitize()
        half = 0.5 * float(length)
        a = center_pt - v * half
        b = center_pt + v * half
        return Line(a, b)

    def _offset_parallel_in_plane(self, base_line, plane, offset):
        """
        将 base_line 在 plane 内做平移偏移（沿 plane 的法向与线方向叉乘得到的侧向）。
        返回偏移后的 Line（保持长度与方向）。
        """
        dvec = base_line.Direction
        if dvec.IsZero:
            dvec = plane.XAxis
        dvec.Unitize()

        # 在平面内的“侧向” = plane.ZAxis × line_dir（保证仍在平面内）
        side = Vector3d.CrossProduct(plane.ZAxis, dvec)
        if side.IsZero:
            side = plane.YAxis
        side.Unitize()

        move = side * float(offset)
        return Line(base_line.From + move, base_line.To + move)

    def _line_line_intersection_point(self, l1, l2):
        """
        计算两条无限延长直线的交点（用 RhinoCommon Intersection.LineLine）。
        若平行或无交点，返回 None。
        """
        a = l1.From
        b = l1.To
        c = l2.From
        d = l2.To
        # IronPython 下 Intersection.LineLine(...) 存在多重重载；
        # 传入 tol 容易被解析到包含 Boolean 参数的重载，从而触发：
        # TypeError: 'float' value cannot be converted to System.Boolean ...
        # 因此这里使用最稳定的重载：LineLine(Line, Line, out double, out double)
        rc, ta, tb = Intersection.LineLine(Line(a, b), Line(c, d))
        if not rc:
            return None
        # ta 是 l1 参数（0..1 对应线段），但我们按“无限延长线”理解，依旧可取点
        pt = a + (b - a) * ta
        return pt

    # -------------------------
    # main solve
    # -------------------------
    def solve(self,
              O=None,
              RefPlane=None,
              d=5.0,
              L12_len=96.84,
              L36_len=100.0,
              alpha_deg=45.0,
              axis_len=140.0):

        # sanitize inputs
        O = self._ensure_point(O)
        RefPlane = self._ensure_plane(RefPlane)
        d = float(d) if d is not None else 5.0
        L12_len = float(L12_len) if L12_len is not None else 96.84
        L36_len = float(L36_len) if L36_len is not None else 100.0
        alpha_deg = float(alpha_deg) if alpha_deg is not None else 45.0
        axis_len = float(axis_len) if axis_len is not None else 140.0

        # axes directions in the given plane
        xdir = Vector3d(RefPlane.XAxis)
        ydir = Vector3d(RefPlane.YAxis)
        zdir = Vector3d(RefPlane.ZAxis)
        if xdir.IsZero: xdir = Vector3d(1, 0, 0)
        if ydir.IsZero: ydir = Vector3d(0, 1, 0)
        if zdir.IsZero: zdir = Vector3d(0, 0, 1)
        xdir.Unitize()
        ydir.Unitize()
        zdir.Unitize()

        # Step 1: AO axis + A/B + L1/L2
        # A,B along plane.YAxis around O with distance d
        A = O + ydir * d
        B = O - ydir * d

        Axis_AO = self._make_centered_line(O, xdir, axis_len)

        # L1/L2: parallel AO (i.e., parallel xdir), centered at A/B
        L1 = self._make_centered_line(A, xdir, L12_len)
        L2 = self._make_centered_line(B, xdir, L12_len)

        # Step 2: AC/AD axes (rotate AO dir in plane)
        ang = math.radians(alpha_deg)
        ac_dir = self._rotate_in_plane(xdir, RefPlane, +ang)
        ad_dir = self._rotate_in_plane(xdir, RefPlane, -ang)

        Axis_AC = self._make_centered_line(O, ac_dir, axis_len)
        Axis_AD = self._make_centered_line(O, ad_dir, axis_len)

        # Build base lines along AC/AD through O with length L36_len, then offset ±d on each side
        AC_base = self._make_centered_line(O, ac_dir, L36_len)
        AD_base = self._make_centered_line(O, ad_dir, L36_len)

        # L3/L4 are parallel to AC, on both sides of AC
        L3 = self._offset_parallel_in_plane(AC_base, RefPlane, +d)
        L4 = self._offset_parallel_in_plane(AC_base, RefPlane, -d)

        # L5/L6 are parallel to AD, on both sides of AD
        # NOTE (per latest diagram): L6 is the +d side; L5 is the -d side.
        L6 = self._offset_parallel_in_plane(AD_base, RefPlane, +d)
        L5 = self._offset_parallel_in_plane(AD_base, RefPlane, -d)

        # Step 3: intersections
        J = self._line_line_intersection_point(L2, L3)
        K = self._line_line_intersection_point(L2, L6)
        Jp = self._line_line_intersection_point(L1, L5)
        # NOTE (per latest diagram): K' should be the intersection of L1 and L4.
        Kp = self._line_line_intersection_point(L1, L4)

        # distances
        Dist_BJ = None
        Dist_JK = None

        if J is not None:
            Dist_BJ = B.DistanceTo(J)
        if (J is not None) and (K is not None):
            Dist_JK = J.DistanceTo(K)

        # logging
        self.Log = []
        self.Log.append("OK: Geometry built with RefPlane axes:")
        self.Log.append("  XAxis={0}, YAxis={1}, ZAxis={2}".format(tuple(xdir), tuple(ydir), tuple(zdir)))
        self.Log.append("  d={0}, L12_len={1}, L36_len={2}, alpha_deg={3}".format(d, L12_len, L36_len, alpha_deg))
        self.Log.append("Intersections:")
        self.Log.append("  J (L2∩L3)  = {0}".format(J if J is not None else "None"))
        self.Log.append("  K (L2∩L6)  = {0}".format(K if K is not None else "None"))
        self.Log.append("  J' (L1∩L5) = {0}".format(Jp if Jp is not None else "None"))
        self.Log.append("  K' (L1∩L4) = {0}".format(Kp if Kp is not None else "None"))
        self.Log.append("Distances:")
        self.Log.append("  |B-J| = {0}".format(Dist_BJ if Dist_BJ is not None else "None"))
        self.Log.append("  |J-K| = {0}".format(Dist_JK if Dist_JK is not None else "None"))

        # pack outputs (match GH output names)
        return {
            "Axis_AO": Axis_AO,
            "Axis_AC": Axis_AC,
            "Axis_AD": Axis_AD,
            "L1": L1, "L2": L2, "L3": L3, "L4": L4, "L5": L5, "L6": L6,
            "O_out": O, "A": A, "B": B,
            "J": J, "K": K, "Jp": Jp, "Kp": Kp,
            "Dist_BJ": Dist_BJ,
            "Dist_JK": Dist_JK,
            "Log": self.Log
        }

if __name__ == "__main__":
    # =========================
    # GH Python 调用区（直接用）
    # =========================
    _solver = AxisLinesIntersectionsSolver()
    _out = _solver.solve(O, RefPlane, d, L12_len, L36_len, alpha_deg, axis_len)

    Axis_AO = _out["Axis_AO"]
    Axis_AC = _out["Axis_AC"]
    Axis_AD = _out["Axis_AD"]

    L1 = _out["L1"]
    L2 = _out["L2"]
    L3 = _out["L3"]
    L4 = _out["L4"]
    L5 = _out["L5"]
    L6 = _out["L6"]

    O_out = _out["O_out"]
    A = _out["A"]
    B = _out["B"]

    J = _out["J"]
    K = _out["K"]
    Jp = _out["Jp"]
    Kp = _out["Kp"]

    Dist_BJ = _out["Dist_BJ"]
    Dist_JK = _out["Dist_JK"]

    Log = _out["Log"]

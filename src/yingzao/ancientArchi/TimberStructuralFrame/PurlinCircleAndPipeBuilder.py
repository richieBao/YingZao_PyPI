# -*- coding: utf-8 -*-
"""
PurlinCircleAndPipeBuilder
槫（圆截面 + 封口圆柱体）生成器 —— “旧点+新点”为直径，圆必过两点（并强制在参考平面内）

核心约束（按你的澄清）：
- OldPt 与 NewPt 必须是圆上的一对对径点（直径两端）
- 圆心为 OldPt—NewPt 的中点
- 圆半径为 槫直径/2
- 圆所在平面内的 X 轴 = (NewPt - OldPt) 方向（确保两点严格落在圆上）
- 圆平面法向 = Direction（会 Normalize）

新增约束（本次新增）：
- 增加输入端 RefPlane
- 圆**必须在 RefPlane 平面内**绘制（即：圆平面 = RefPlane 平行且过圆心）
- 为了“控制方位”，圆平面的 X/Y 轴继承 RefPlane 的 X/Y 轴（保证方位一致）
- 同时仍保证 p0/p1 在圆上：将直径方向强制投影到 RefPlane 内，作为圆平面 X 轴；
  若投影退化（几乎垂直 RefPlane），则回退用 RefPlane.XAxis。

拉伸逻辑（保持）：
- ExtrudePosDist 与 ExtrudeNegDist 拉伸时，均以“原始圆截面（中截面）”为基准进行拉伸
- 两次 cap=False 拉伸，Join 后统一 CapPlanarHoles，仅封两端

------------------------------------------------------------
输入（GhPython 建议设置）:
    Pts : rg.Point3d (List)
        多个点列表（每个点作为直径一端点 OldPt）
        Access: List
        TypeHints: Point3d

    PurlinDiameter : float (Item)
        槫直径（OldPt 沿 Direction 移动该距离得到 NewPt；圆半径=直径/2）
        Access: Item
        TypeHints: float

    Direction : rg.Vector3d (Item)
        指定“生成直径新点”的方向向量（会 Normalize；若为零向量则回落 WorldZ）
        Access: Item
        TypeHints: Vector3d

    RefPlane : rg.Plane (Item)
        参考平面：圆截面必须在该平面内绘制（用于控制方位）
        若未输入/无效：回退为“以圆心+Direction”为法向的平面（旧逻辑）
        Access: Item
        TypeHints: Plane

    ExtrudePosDist : float (Item)
        沿圆截面法向（RefPlane.ZAxis）正向拉伸距离（可为0）
        Access: Item
        TypeHints: float

    ExtrudeNegDist : float (Item)
        沿圆截面法向（RefPlane.ZAxis）反向拉伸距离（可为0）
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    Circles : list[rg.Circle]
        每个槫的圆截面（圆必过 OldPt 与 NewPt，且圆平面在 RefPlane 内）
        Access: List
        TypeHints: Circle

    Cylinders : list[rg.Brep]
        每个槫的封口圆柱体（Brep，含两端封口）
        Access: List
        TypeHints: Brep

    NewPts : list[rg.Point3d]
        OldPt 沿 Direction 移动 PurlinDiameter 后的新点（直径另一端）
        Access: List
        TypeHints: Point3d

（调试/对接用，可按需删掉）:
    CenterPts : list[rg.Point3d]
    DiamLines : list[rg.Line]
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg


class PurlinCircleAndPipeBuilder(object):
    def __init__(self, pts, diameter, direction, ref_plane, extrude_pos, extrude_neg, tol=1e-9):
        self.tol = tol
        self.pts = self._as_point_list(pts)

        self.diameter = self._to_float(diameter, default=0.0)
        self.extrude_pos = self._to_float(extrude_pos, default=0.0)
        self.extrude_neg = self._to_float(extrude_neg, default=0.0)

        self.dir = self._prepare_dir(direction)
        self.ref_plane = self._prepare_plane(ref_plane)

        # outputs
        self.new_pts = []
        self.center_pts = []
        self.diam_lines = []
        self.circles = []
        self.cylinders = []

    # ---------- public ----------
    def build(self):
        # 空输入时不报错（避免 GH 组件变红）
        if not self.pts or self.diameter <= self.tol:
            return self.circles, self.cylinders, self.new_pts, self.center_pts, self.diam_lines

        r = 0.5 * self.diameter

        for old_pt in self.pts:
            p0 = rg.Point3d(old_pt)
            p1 = p0 + (self.dir * self.diameter)  # NewPt：直径另一端

            diam_line = rg.Line(p0, p1)
            center = diam_line.PointAt(0.5)

            # 以 RefPlane 为基准构造“圆截面平面”（必须在 RefPlane 内）
            circle_plane, axis_dir = self._make_circle_plane_in_refplane(center, p0, p1)

            circle = rg.Circle(circle_plane, r)

            # 拉伸轴向：圆截面平面的法向（在 RefPlane 约束下就是 RefPlane.ZAxis）
            cyl = self._make_capped_cylinder_two_sided_from_mid(circle, axis_dir, self.extrude_pos, self.extrude_neg)

            self.new_pts.append(p1)
            self.center_pts.append(center)
            self.diam_lines.append(diam_line)
            self.circles.append(circle)
            if cyl is not None:
                self.cylinders.append(cyl)

        return self.circles, self.cylinders, self.new_pts, self.center_pts, self.diam_lines

    # ---------- helpers ----------
    def _as_point_list(self, pts):
        if pts is None:
            return []
        if isinstance(pts, (list, tuple)):
            return [p for p in pts if isinstance(p, rg.Point3d)]
        if isinstance(pts, rg.Point3d):
            return [pts]
        return []

    def _to_float(self, v, default=0.0):
        try:
            if v is None:
                return float(default)
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return float(v[0])
            return float(v)
        except:
            return float(default)

    def _prepare_dir(self, direction):
        d = direction if isinstance(direction, rg.Vector3d) else rg.Vector3d(0, 0, 1)
        if d.IsTiny(self.tol) or d.Length <= self.tol:
            d = rg.Vector3d(0, 0, 1)
        d.Unitize()
        return d

    def _prepare_plane(self, pl):
        # GhPython 中 Plane 输入为空时可能为 None 或 Unset
        if isinstance(pl, rg.Plane):
            return pl
        # 回退：WorldXY
        return rg.Plane.WorldXY

    def _make_circle_plane_in_refplane(self, center, p0, p1):
        """
        返回:
            circle_plane : rg.Plane   （与 RefPlane 共面/平行，且过 center）
            axis_dir     : rg.Vector3d（圆截面法向，用于拉伸；即 circle_plane.ZAxis）
        逻辑：
        - 法向固定为 RefPlane.ZAxis（确保圆在 RefPlane 平面内）
        - 圆平面 X 轴：取直径方向 (p1-p0) 投影到 RefPlane 内
          若投影退化，则用 RefPlane.XAxis
        - Y 轴用 Z×X 得到，保持右手系
        """
        ref = rg.Plane(self.ref_plane)
        n = rg.Vector3d(ref.ZAxis)
        if n.IsTiny(self.tol) or n.Length <= self.tol:
            n = rg.Vector3d(0, 0, 1)
        n.Unitize()

        # 直径方向
        d = rg.Vector3d(p1 - p0)
        if d.IsTiny(self.tol) or d.Length <= self.tol:
            d = rg.Vector3d(ref.XAxis)

        # 投影到 RefPlane 内： d_proj = d - (d·n) n
        dot = rg.Vector3d.Multiply(d, n)
        d_proj = d - (n * dot)

        if d_proj.IsTiny(self.tol) or d_proj.Length <= self.tol:
            x_axis = rg.Vector3d(ref.XAxis)
            if x_axis.IsTiny(self.tol):
                x_axis = rg.Vector3d(1, 0, 0)
        else:
            x_axis = d_proj

        x_axis.Unitize()

        y_axis = rg.Vector3d.CrossProduct(n, x_axis)
        if y_axis.IsTiny(self.tol) or y_axis.Length <= self.tol:
            y_axis = rg.Vector3d(ref.YAxis)
            if y_axis.IsTiny(self.tol):
                # 最终兜底
                y_axis = rg.Vector3d(0, 1, 0)
        y_axis.Unitize()

        circle_plane = rg.Plane(center, x_axis, y_axis)
        # 关键：保证平面法向与 RefPlane 法向同向
        # （Plane(center, x, y) 的 ZAxis 理论上就是 x×y，这里 y = n×x => x×y 与 n 同向）
        axis_dir = rg.Vector3d(circle_plane.ZAxis)
        axis_dir.Unitize()

        return circle_plane, axis_dir

    def _make_capped_cylinder_two_sided_from_mid(self, circle, axis_dir, pos_dist, neg_dist):
        """
        pos / neg 两次拉伸都“从同一个原始圆截面”开始，不平移截面。
        axis_dir 为圆截面法向（在 RefPlane 约束下等价于 RefPlane.ZAxis）。
        """
        pos_d = max(0.0, float(pos_dist))
        neg_d = max(0.0, float(neg_dist))

        if (pos_d + neg_d) <= self.tol:
            return None

        mid_crv = circle.ToNurbsCurve()
        breps = []

        # 正向：+axis_dir（用正长度）
        if pos_d > self.tol:
            ext_pos = rg.Extrusion.Create(mid_crv, pos_d, False)  # cap=False
            if ext_pos is not None:
                breps.append(ext_pos.ToBrep())

        # 反向：-axis_dir（用负长度）
        if neg_d > self.tol:
            ext_neg = rg.Extrusion.Create(mid_crv, -neg_d, False)  # cap=False
            if ext_neg is not None:
                breps.append(ext_neg.ToBrep())

        if not breps:
            return None

        # 一侧：Cap 端口
        if len(breps) == 1:
            b = breps[0]
            capped = b.CapPlanarHoles(self.tol)
            if capped is not None:
                capped.MergeCoplanarFaces(self.tol)
                return capped
            b.MergeCoplanarFaces(self.tol)
            return b

        # 两侧：Join + Cap（只封两端端口，不封中截面）
        joined_list = rg.Brep.JoinBreps(breps, self.tol)
        if not joined_list or len(joined_list) == 0:
            # Join 失败：尽力返回体量最大的 cap 后 brep
            cand = []
            for b in breps:
                cb = b.CapPlanarHoles(self.tol)
                cand.append(cb if cb is not None else b)

            def _vol(brep):
                mp = rg.VolumeMassProperties.Compute(brep)
                return mp.Volume if mp else 0.0

            best = max(cand, key=_vol)
            best.MergeCoplanarFaces(self.tol)
            return best

        def _vol(brep):
            mp = rg.VolumeMassProperties.Compute(brep)
            return mp.Volume if mp else 0.0

        best_joined = max(joined_list, key=_vol)

        capped = best_joined.CapPlanarHoles(self.tol)
        if capped is not None:
            capped.MergeCoplanarFaces(self.tol)
            return capped

        best_joined.MergeCoplanarFaces(self.tol)
        return best_joined

if __name__ == '__main__':
    # ---------------- GH 运行区（直接绑定输出） ----------------
    # 期望 GH 输入名：Pts, PurlinDiameter, Direction, RefPlane, ExtrudePosDist, ExtrudeNegDist
    builder = PurlinCircleAndPipeBuilder(Pts, PurlinDiameter, Direction, RefPlane, ExtrudePosDist, ExtrudeNegDist)
    Circles, Cylinders, NewPts, CenterPts, DiamLines = builder.build()

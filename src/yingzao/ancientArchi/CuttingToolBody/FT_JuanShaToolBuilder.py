# -*- coding: utf-8 -*-
"""FT_JuanShaTool_Class_v10_2

卷殺特征刀具 (增加 SectionEdges 输出端)
--------------------------------------------------
截面 = 竖直等分 V0..V_N、水平等分 U0..U_N
卷殺折线 = (V_N,U_1)-(V_{N-1},U_2)-...-(V_1,U_N)
Brep 中自动识别高向面(Y方向接近)与长向面(X方向接近)的交线作为角边
HeightFacePlane / LengthFacePlane 原点 = 角边中点
SectionPlane 原点 = PositionPoint

新增输出:
    SectionEdges : [height_edge, length_edge] 两条截面边线 (Line)
"""

import Rhino.Geometry as rg
import Rhino.Geometry.Intersect as rgx
from Rhino.Geometry import Point3d, Line, Vector3d


class JuanShaToolBuilder(object):
    def __init__(self,
                 height_fen=None,
                 length_fen=None,
                 thickness_fen=None,
                 div_count=None,
                 section_plane=None,
                 position_point=None,
                 tol=1e-6):

        self.log = []
        self.tol = tol

        self.height_fen = 9.0 if height_fen is None else float(height_fen)
        self.length_fen = 16.0 if length_fen is None else float(length_fen)
        self.thickness_fen = 10.0 if thickness_fen is None else float(thickness_fen)
        self.div_count = 4 if div_count is None else max(2, int(div_count))

        # ---- 默认 XZ 平面 ----
        if section_plane is None:
            o = Point3d(0, 0, 0)
            x = Vector3d(1, 0, 0)   # 长
            y = Vector3d(0, 0, 1)   # 高
            base_plane = rg.Plane(o, x, y)
            self._log("未提供 SectionPlane → 使用世界 XZ 平面")
        else:
            base_plane = rg.Plane(section_plane)
            self._log("使用输入 SectionPlane")

        # ---- 平面原点 = PositionPoint ----
        if position_point is not None:
            base_plane.Origin = position_point
            self._log("SectionPlane 原点 = PositionPoint")
        else:
            self._log("PositionPoint 未提供，使用原平面")

        self.plane = base_plane
        self.origin = base_plane.Origin
        self.x_dir = base_plane.XAxis; self.x_dir.Unitize()
        self.y_dir = base_plane.YAxis; self.y_dir.Unitize()
        self.z_dir = base_plane.ZAxis; self.z_dir.Unitize()

        self._log(
            "参数: Height=%.3f, Length=%.3f, Thick=%.3f, Div=%d" %
            (self.height_fen, self.length_fen, self.thickness_fen, self.div_count)
        )

    def _log(self, msg):
        self.log.append(str(msg))

    @staticmethod
    def _line_line_pt(line_a, line_b):
        rc, ta, tb = rgx.Intersection.LineLine(line_a, line_b)
        if not rc:
            return None
        pa = line_a.PointAt(ta)
        pb = line_b.PointAt(tb)
        return Point3d((pa.X+pb.X)/2, (pa.Y+pb.Y)/2, (pa.Z+pb.Z)/2)

    # ---------- 构造截面 ----------
    def _build_section_curve(self):

        o = self.origin
        N = self.div_count

        # 高向点 V0..V_N
        V = []
        for i in range(N + 1):
            V.append(o + self.y_dir * (self.height_fen * float(i)/N))

        # 长向点 U0..U_N
        U = []
        for i in range(N + 1):
            U.append(o + self.x_dir * (self.length_fen * float(i)/N))

        # Li：连接 V[N+1-i] → U[i]
        lines = []
        for i in range(1, N + 1):
            lines.append(Line(V[N+1-i], U[i]))

        # 相邻线段交点
        inter_pts = []
        for i in range(len(lines)-1):
            p = self._line_line_pt(lines[i], lines[i+1])
            if p: inter_pts.append(p)

        if len(inter_pts) == 0:
            self._log("交点不足 → 退化为三角形截面")
            pts = [o, V[N], U[N], o]
        else:
            # O → V_N → P1..P(k) → U_N → O
            pts = [o, V[N]] + inter_pts + [U[N], o]

        curve = rg.Polyline(pts).ToNurbsCurve()
        curve.MakeClosed(self.tol)
        return curve

    # ---------- 从 Brep 自动识别角边 ----------
    def _find_corner_edge(self, brep):

        best_h_face, best_l_face = None, None
        best_dot_x, best_dot_y = -1, -1

        for f in brep.Faces:
            d0 = f.Domain(0); d1 = f.Domain(1)
            u = (d0.T0 + d0.T1) * 0.5
            v = (d1.T0 + d1.T1) * 0.5
            n = f.NormalAt(u, v)
            if not n.Unitize():   # 防止零向量
                continue

            dx = abs(rg.Vector3d.Multiply(n, self.x_dir))
            dy = abs(rg.Vector3d.Multiply(n, self.y_dir))

            if dx > best_dot_x:
                best_dot_x = dx; best_h_face = f
            if dy > best_dot_y:
                best_dot_y = dy; best_l_face = f

        if best_h_face is None or best_l_face is None:
            return None, None

        brep_h = best_h_face.DuplicateFace(True)
        brep_l = best_l_face.DuplicateFace(True)

        rc, crvs, _ = rgx.Intersection.BrepBrep(brep_h, brep_l, self.tol)
        if not rc or not crvs:
            return None, None

        c = crvs[0]
        hl_line = Line(c.PointAtStart, c.PointAtEnd)
        mid = c.PointAtNormalizedLength(0.5)
        return hl_line, mid

    # ---------- 主构造 ----------
    def build(self):

        # A. 构造截面
        sec = self._build_section_curve()

        # B. 截面中的高/长边（作为输出 SectionEdges）
        height_edge = Line(self.origin,
                           self.origin + self.y_dir * self.height_fen)
        length_edge = Line(self.origin,
                           self.origin + self.x_dir * self.length_fen)
        section_edges = [height_edge, length_edge]

        # C. 尝试挤出
        extr = rg.Extrusion.Create(sec, self.thickness_fen, True)
        tool_brep = extr.ToBrep() if extr else None

        if tool_brep is None:
            surf = rg.Surface.CreateExtrusion(sec, self.z_dir * self.thickness_fen)
            if surf:
                tool_brep = surf.ToBrep().CapPlanarHoles(self.tol)

        if tool_brep is None:
            self._log("挤出失败 → 无 Brep")
            return None, section_edges, None, None, None, self.log

        # D. 识别角边
        hl, mid = self._find_corner_edge(tool_brep)
        if hl is None:
            bottom = self.origin
            top = bottom + self.z_dir * self.thickness_fen
            hl = Line(bottom, top)
            mid = hl.PointAt(0.5)

        # E. 两个参考平面（原点=角边中点）
        height_plane = rg.Plane(mid, self.y_dir, self.z_dir)
        length_plane = rg.Plane(mid, self.x_dir, self.z_dir)

        return tool_brep, section_edges, hl, height_plane, length_plane, self.log

if __name__=='__main__':
    # ================= GH 输入 / 输出 =================

    builder = JuanShaToolBuilder(
        height_fen=HeightFen,
        length_fen=LengthFen,
        thickness_fen=ThicknessFen,
        div_count=DivCount,
        section_plane=SectionPlane,
        position_point=PositionPoint
    )

    ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, Log = builder.build()

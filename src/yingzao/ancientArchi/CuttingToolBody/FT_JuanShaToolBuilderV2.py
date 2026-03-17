# -*- coding: utf-8 -*-
"""
FT_JuanShaToolBuilderV2
--------------------------------------------------
需求实现汇总：

1) OutputLower : bool
   True  -> 输出下体块 ToolBrep（保持原卷殺切分逻辑 A-B-C-A）
   False -> 输出上体块 ToolBrep（由同一卷殺折线派生上半截面 C-B-D-C）

2) 上体块(OutputLower=False)时：
   HeightFacePlane / LengthFacePlane 与下体块一致，但沿参考平面 YAxis 上移 HeightFen
   （即上边缘线的中点对应位置）

3) UpperExtendLen : float（默认 0）
   仅当 OutputLower=False 且 UpperExtendLen>0 时：
   生成 UpperExtendBrep —— 使用端部竖直截面（x=LengthFen 处的竖直面，图中蓝绿色截面）
   沿 +x_dir 拉伸 UpperExtendLen，形成可延伸长方体块。

输出：
    ToolBrep
    SectionEdges
    HL_Intersection
    HeightFacePlane
    LengthFacePlane
    UpperExtendBrep
    Log
"""

import Rhino.Geometry as rg
import Rhino.Geometry.Intersect as rgx
from Rhino.Geometry import Point3d, Line, Vector3d


class JuanShaToolBuilderV2(object):

    def __init__(self,
                 height_fen=None,
                 length_fen=None,
                 thickness_fen=None,
                 div_count=None,
                 section_plane=None,
                 position_point=None,
                 output_lower=True,
                 upper_extend_len=0.0,
                 tol=1e-6):

        self.log = []
        self.tol = tol

        self.height_fen = 9.0 if height_fen is None else float(height_fen)
        self.length_fen = 16.0 if length_fen is None else float(length_fen)
        self.thickness_fen = 10.0 if thickness_fen is None else float(thickness_fen)
        self.div_count = 4 if div_count is None else max(2, int(div_count))

        self.output_lower = bool(output_lower)
        self.upper_extend_len = 0.0 if upper_extend_len is None else float(upper_extend_len)

        # ---- 默认 XZ 平面（与你项目常用一致：X=length，Y=height，Z=normal/厚度方向）----
        if section_plane is None:
            o = Point3d(0, 0, 0)
            x = Vector3d(1, 0, 0)   # LengthFen
            y = Vector3d(0, 0, 1)   # HeightFen
            base_plane = rg.Plane(o, x, y)
            self._log("未提供 SectionPlane → 使用世界 XZ 平面")
        else:
            base_plane = rg.Plane(section_plane)
            self._log("使用输入 SectionPlane")

        if position_point is not None:
            base_plane.Origin = position_point
            self._log("SectionPlane 原点 = PositionPoint")
        else:
            self._log("PositionPoint 未提供，使用输入平面原点")

        self.plane = base_plane
        self.origin = base_plane.Origin

        self.x_dir = base_plane.XAxis; self.x_dir.Unitize()  # LengthFen 方向
        self.y_dir = base_plane.YAxis; self.y_dir.Unitize()  # HeightFen 方向
        self.z_dir = base_plane.ZAxis; self.z_dir.Unitize()  # 厚度方向

        self._log(
            "参数: Height=%.3f, Length=%.3f, Thick=%.3f, Div=%d, OutputLower=%s, UpperExtendLen=%.3f" %
            (self.height_fen, self.length_fen, self.thickness_fen, self.div_count,
             str(self.output_lower), self.upper_extend_len)
        )

    # ==================================================
    # utils
    # ==================================================
    def _log(self, msg):
        self.log.append(str(msg))

    @staticmethod
    def _line_line_pt(line_a, line_b):
        rc, ta, tb = rgx.Intersection.LineLine(line_a, line_b)
        if not rc:
            return None
        pa = line_a.PointAt(ta)
        pb = line_b.PointAt(tb)
        return Point3d((pa.X + pb.X) / 2.0, (pa.Y + pb.Y) / 2.0, (pa.Z + pb.Z) / 2.0)

    # ==================================================
    # 下半截面点序列（保持原卷殺切分逻辑）
    # ==================================================
    def _build_section_pts__lower(self):

        o = self.origin
        N = self.div_count

        # 高向点 V0..V_N
        V = []
        for i in range(N + 1):
            V.append(o + self.y_dir * (self.height_fen * float(i) / N))

        # 长向点 U0..U_N
        U = []
        for i in range(N + 1):
            U.append(o + self.x_dir * (self.length_fen * float(i) / N))

        # Li：连接 V[N+1-i] → U[i]
        lines = []
        for i in range(1, N + 1):
            lines.append(Line(V[N + 1 - i], U[i]))

        # 相邻线段交点
        inter_pts = []
        for i in range(len(lines) - 1):
            p = self._line_line_pt(lines[i], lines[i + 1])
            if p:
                inter_pts.append(p)

        if len(inter_pts) == 0:
            self._log("交点不足 → 退化为三角形截面")
            pts = [o, V[N], U[N], o]
        else:
            # A(=O) → C(=V_N) → P1..Pk → B(=U_N) → A
            pts = [o, V[N]] + inter_pts + [U[N], o]

        return pts

    # ==================================================
    # 下半截面（原逻辑）
    # ==================================================
    def _build_section_curve(self):
        pts = self._build_section_pts__lower()
        crv = rg.Polyline(pts).ToNurbsCurve()
        crv.MakeClosed(self.tol)
        return crv

    # ==================================================
    # 上半截面（派生）：C-B-D-C
    # ==================================================
    def _build_section_curve__upper(self):

        pts_lower = self._build_section_pts__lower()

        A = pts_lower[0]
        C = pts_lower[1]
        B = pts_lower[-2]
        D = A + self.x_dir * self.length_fen + self.y_dir * self.height_fen  # 右上角

        if len(pts_lower) == 4:
            # 退化三角形：A-C-B-A -> 上半：C-B-D-C
            pts_upper = [C, B, D, C]
        else:
            mid_pts = pts_lower[2:-2]  # C->...->B 的卷殺折线中间点
            pts_upper = [C] + mid_pts + [B, D, C]

        crv = rg.Polyline(pts_upper).ToNurbsCurve()
        crv.MakeClosed(self.tol)
        return crv

    # ==================================================
    # 统一截面曲线法向，避免挤出翻面（GH/IronPython 兼容 TryGetPlane）
    # ==================================================
    def _ensure_curve_normal(self, crv):
        if crv is None:
            return None

        ok, pl = False, None
        try:
            res = crv.TryGetPlane()
            if isinstance(res, tuple) and len(res) >= 2:
                ok, pl = res[0], res[1]
            else:
                ok = bool(res)
        except:
            ok = False

        if ok and pl is not None:
            n = pl.ZAxis
            n.Unitize()
            dz = Vector3d.Multiply(n, self.z_dir)
            if dz < 0:
                crv.Reverse()
                self._log("截面曲线法向反向 → Reverse() 以统一挤出方向")
        else:
            self._log("警告：TryGetPlane 失败，未做法向统一")

        return crv

    # ==================================================
    # 上体块延伸：端部竖直截面（图中蓝绿色截面）+ 沿 +x_dir 拉伸
    # ==================================================
    def _build_upper_extend_brep(self, end_vertical_plane):
        """
        end_vertical_plane:
            端部竖直面，位于 x = LengthFen 处，法向 ~ x_dir
            该平面以 (y_dir, z_dir) 为轴：XAxis=y_dir, YAxis=z_dir, ZAxis=x_dir

        截面矩形：
            以 end_vertical_plane.Origin 为“上边缘中点”
            向 -y_dir 下走 HeightFen
            厚度沿 z_dir 为 ±Thickness/2（围绕中线）
        拉伸：
            沿 +x_dir 拉伸 UpperExtendLen
        """

        L = 0.0 if self.upper_extend_len is None else float(self.upper_extend_len)
        if L <= 0:
            return None

        o = end_vertical_plane.Origin
        y = end_vertical_plane.XAxis  # = y_dir
        z = end_vertical_plane.YAxis  # = z_dir
        y.Unitize()
        z.Unitize()

        half_t = self.thickness_fen * 0.5
        z0 = z * half_t

        # 以上边缘为基准（o 在上边缘中点线上）
        p_top_negz = o - z0
        p_top_posz = o + z0
        p_bot_posz = o - y * self.height_fen + z0
        p_bot_negz = o - y * self.height_fen - z0

        rect = rg.Polyline([p_top_negz, p_top_posz, p_bot_posz, p_bot_negz, p_top_negz]).ToNurbsCurve()
        rect.MakeClosed(self.tol)

        # 沿 +x_dir 拉伸 L
        extr = rg.Extrusion.Create(rect, L, True)
        brep = extr.ToBrep() if extr else None

        if brep is None:
            surf = rg.Surface.CreateExtrusion(rect, self.x_dir * L)
            if surf:
                brep = surf.ToBrep().CapPlanarHoles(self.tol)

        return brep

    # ==================================================
    # build
    # ==================================================
    def build(self):

        # A. 截面曲线（下/上）
        if self.output_lower:
            sec = self._build_section_curve()
        else:
            sec = self._build_section_curve__upper()

        # B. 统一法向（避免镜像/翻面）
        sec = self._ensure_curve_normal(sec)

        # C. SectionEdges 输出（在截面平面内的两条基准边）
        height_edge = Line(self.origin, self.origin + self.y_dir * self.height_fen)
        length_edge = Line(self.origin, self.origin + self.x_dir * self.length_fen)
        section_edges = [height_edge, length_edge]

        # D. ToolBrep 挤出（厚度方向 z_dir，长度 thickness_fen）
        extr = rg.Extrusion.Create(sec, self.thickness_fen, True)
        tool_brep = extr.ToBrep() if extr else None
        if tool_brep is None:
            surf = rg.Surface.CreateExtrusion(sec, self.z_dir * self.thickness_fen)
            if surf:
                tool_brep = surf.ToBrep().CapPlanarHoles(self.tol)

        if tool_brep is None:
            self._log("挤出失败 → 无 ToolBrep")
            return None, section_edges, None, None, None, None, self.log

        # E. 参考平面输出规则：
        #    下体块：mid = origin + z*thick/2
        #    上体块：mid 在此基础上 + y*HeightFen（上边缘线中点）
        base_mid = self.origin + self.z_dir * (self.thickness_fen * 0.5)
        if self.output_lower:
            mid_for_planes = base_mid
        else:
            mid_for_planes = base_mid + self.y_dir * self.height_fen
            self._log("上体块参考平面：mid 沿 Y 上移 HeightFen")

        # HL_Intersection：竖向角边线（保持与 mid 规则一致）
        hl_from = self.origin
        hl_to = self.origin + self.z_dir * self.thickness_fen
        if not self.output_lower:
            hl_from = hl_from + self.y_dir * self.height_fen
            hl_to = hl_to + self.y_dir * self.height_fen
        hl = Line(hl_from, hl_to)

        height_plane = rg.Plane(mid_for_planes, self.y_dir, self.z_dir)
        length_plane = rg.Plane(mid_for_planes, self.x_dir, self.z_dir)

        # F. 上体块延伸长方体（正确：端部竖直截面 x=LengthFen）
        upper_extend_brep = None
        if (not self.output_lower) and (self.upper_extend_len > 0):

            # 端部竖直面：位于 mid_for_planes + x_dir*LengthFen
            # 用 (y_dir, z_dir) 构造平面，确保 plane.ZAxis = y×z = x_dir
            end_plane_origin = mid_for_planes + self.x_dir * self.length_fen
            end_vertical_plane = rg.Plane(end_plane_origin, self.y_dir, self.z_dir)

            upper_extend_brep = self._build_upper_extend_brep(end_vertical_plane)

        return tool_brep, section_edges, hl, height_plane, length_plane, upper_extend_brep, self.log


if __name__ == '__main__':
    # ================= GH 输入 / 输出 =================
    #
    # Inputs (GH 建议配置):
    #   HeightFen      : float
    #   LengthFen      : float
    #   ThicknessFen   : float
    #   DivCount       : int
    #   SectionPlane   : Plane
    #   PositionPoint  : Point3d
    #   OutputLower    : bool
    #   UpperExtendLen : float   (可选，不接则默认 0)
    #
    # Outputs:
    #   ToolBrep
    #   SectionEdges
    #   HL_Intersection
    #   HeightFacePlane
    #   LengthFacePlane
    #   UpperExtendBrep
    #   Log

    try:
        _upper_extend_len_in = UpperExtendLen
    except:
        _upper_extend_len_in = 0.0

    builder = JuanShaToolBuilderV2(
        height_fen=HeightFen,
        length_fen=LengthFen,
        thickness_fen=ThicknessFen,
        div_count=DivCount,
        section_plane=SectionPlane,
        position_point=PositionPoint,
        output_lower=OutputLower,
        upper_extend_len=_upper_extend_len_in
    )

    ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, UpperExtendBrep, Log = builder.build()

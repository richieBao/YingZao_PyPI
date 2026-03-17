# -*- coding: utf-8 -*-
"""
FT_RuFang_KaKouTool (v1.3) - 修复版 + YZ 参考平面

GhPython 组件：乳栿 / 柱头方卡扣特征刀具截面 + 实体

关键修复（v1.3）：
- 先通过 CreatePlanarBreps 从截面曲线生成面
- 再沿拉伸向量拉伸两个面，生成完整闭合实体
- 避免 CapPlanarHoles 对开放边界的识别困难
"""

import Rhino
import Rhino.Geometry as rg

try:
    TOL = Rhino.RhinoDoc.ActiveDoc.ModelAbsoluteTolerance
except:
    TOL = 0.001


class RuFangKaKouBuilder(object):
    """乳栿 / 柱头方卡扣特征刀具构造器"""

    def __init__(self,
                 base_point,
                 ref_plane,
                 width_fen,
                 height_fen,
                 edge_offset_fen,
                 top_inset_fen,
                 extrude_fen):
        self.base_point = base_point
        self.ref_plane = ref_plane
        self.width_fen = float(width_fen)
        self.height_fen = float(height_fen)
        self.edge_offset_fen = float(edge_offset_fen)
        self.top_inset_fen = float(top_inset_fen)
        self.extrude_fen = float(extrude_fen)
        self.log = []

        self._ensure_plane()
        self._normalize_axes()

    # --------------------------------------------------------------
    # 基本平面与坐标处理
    # --------------------------------------------------------------
    def _ensure_plane(self):
        """若未提供 RefPlane，则用 BasePoint 构造一个 XZ 平面。"""
        if self.ref_plane is None:
            self.ref_plane = rg.Plane(self.base_point,
                                      rg.Vector3d.XAxis,
                                      rg.Vector3d.ZAxis)
            self.log.append("✓ RefPlane 已自动创建（XZ 平面）。")
        else:
            plane = rg.Plane(self.ref_plane)
            plane.Origin = self.base_point
            self.ref_plane = plane
            self.log.append("✓ RefPlane 已同步到 BasePoint。")

    def _normalize_axes(self):
        """单位化 X / Y / Z 轴。"""
        self.x_dir = self.ref_plane.XAxis
        self.y_dir = self.ref_plane.YAxis
        self.z_dir = self.ref_plane.ZAxis
        self.x_dir.Unitize()
        self.y_dir.Unitize()
        self.z_dir.Unitize()

    # --------------------------------------------------------------
    # 点位计算
    # --------------------------------------------------------------
    def _build_key_points(self):
        """计算 A,B,C,D,E,F,G,H,I,J 等关键点。"""

        C = self.base_point
        W = self.width_fen
        H = self.height_fen
        e = self.edge_offset_fen
        t = self.top_inset_fen

        D = C + self.x_dir * W
        A = C + self.y_dir * H
        B = A + self.x_dir * W

        I = A - self.y_dir * t
        J = B - self.y_dir * t

        E = I + self.x_dir * e
        F = J - self.x_dir * e
        G = C + self.x_dir * e
        H_pt = D - self.x_dir * e

        self.points = {
            "A": A, "B": B, "C": C, "D": D,
            "E": E, "F": F, "G": G, "H": H_pt,
            "I": I, "J": J
        }

        self.log.append("✓ 关键点计算完成。")

    # --------------------------------------------------------------
    # 截面曲线
    # --------------------------------------------------------------
    def _build_sections(self):
        """构造外层 / 内层截面 PolylineCurve。"""

        A = self.points["A"]
        B = self.points["B"]
        C = self.points["C"]
        D = self.points["D"]
        E = self.points["E"]
        F = self.points["F"]
        G = self.points["G"]
        H = self.points["H"]

        outer_pts = [A, B, D, H, F, E, G, C, A]
        inner_pts = [E, F, H, G, E]

        outer_pl = rg.Polyline(outer_pts)
        inner_pl = rg.Polyline(inner_pts)

        self.outer_section = outer_pl.ToPolylineCurve()
        self.inner_section = inner_pl.ToPolylineCurve()

        self.log.append("✓ 外层/内层截面多段线已生成。")

    # ==============================================================
    # 核心修复：先封面，再拉伸
    # ==============================================================
    # ==============================================================
    # 改版：用 Extrusion.Create 直接生成实体，不再手工拼面
    # ==============================================================
    def _extrude_closed_curve_to_brep(self, curve, vector, curve_name="curve"):
        """
        使用 Rhino.Geometry.Extrusion.Create 生成挤出实体：
        - 按 ref_plane 的法向挤出 height = self.extrude_fen
        - cap=True 自动加顶 / 底盖
        - 再转为 Brep 并合并共面面片
        """

        if curve is None:
            self.log.append("✗ {} 为 None，跳过。".format(curve_name))
            return None

        if not curve.IsClosed:
            self.log.append("✗ {} 未闭合（两端点距离={:.4f}），跳过。".format(
                curve_name,
                curve.PointAtStart.DistanceTo(curve.PointAtEnd)
            ))
            return None

        # 1. 选用 ref_plane 作为挤出基准平面
        #    Extrusion.Create 会先把 curve 投影到这个平面，再沿平面法向挤出
        plane = rg.Plane(self.ref_plane)

        height = float(self.extrude_fen)
        if abs(height) < 1e-6:
            self.log.append("✗ {} 挤出高度过小，跳过。".format(curve_name))
            return None

        # 2. 创建挤出体（cap=True 自动加盖）
        try:
            extr = rg.Extrusion.Create(curve, plane, height, True)
        except Exception as e:
            self.log.append("✗ Extrusion.Create 异常（{}）：{}".format(curve_name, e))
            return None

        if extr is None:
            self.log.append("✗ Extrusion.Create 返回 None（{}）。".format(curve_name))
            return None

        # 3. 转为 Brep
        brep = extr.ToBrep(True)
        if brep is None:
            brep = extr.ToBrep()
        if brep is None:
            self.log.append("✗ Extrusion.ToBrep 失败（{}）。".format(curve_name))
            return None

        # 4. 合并共面面片，清理几何
        try:
            brep.MergeCoplanarFaces(TOL, True)
        except Exception as e:
            self.log.append("⚠ MergeCoplanarFaces 异常（{}）：{}".format(curve_name, e))

        if brep.IsSolid:
            self.log.append("✓ {} 挤出实体生成成功（Closed Brep）。".format(curve_name))
        else:
            self.log.append("⚠ {} 仍为 Open Brep（IsSolid=False）。".format(curve_name))

        return brep

    # ==============================================================
    # 实体拉伸（调用改进的方法）
    # ==============================================================
    def _build_tools(self):
        """沿 RefPlane.ZAxis 拉伸截面，生成两个刀具实体。"""

        vec = rg.Vector3d(self.z_dir)
        vec.Unitize()
        vec *= self.extrude_fen

        self.log.append("\n--- 开始构建 OuterTool ---")
        outer_brep = self._extrude_closed_curve_to_brep(
            self.outer_section, vec, "OuterSection"
        )

        self.log.append("\n--- 开始构建 InnerTool ---")
        inner_brep = self._extrude_closed_curve_to_brep(
            self.inner_section, vec, "InnerSection"
        )

        self.outer_tool = outer_brep
        self.inner_tool = inner_brep

    # --------------------------------------------------------------
    # 边与中点
    # --------------------------------------------------------------
    def _build_edges(self):
        """构造主要边线与中点。"""

        P = self.points

        edges = [
            ("AB", P["A"], P["B"]),
            ("BD", P["B"], P["D"]),
            ("DC", P["D"], P["C"]),
            ("CA", P["C"], P["A"]),
            ("CG", P["C"], P["G"]),
            ("DH", P["D"], P["H"]),
            ("IE", P["I"], P["E"]),
            ("JF", P["J"], P["F"]),
            ("EF", P["E"], P["F"]),
            ("FG", P["F"], P["G"]),
            ("GH", P["G"], P["H"]),
            ("HE", P["H"], P["E"]),
        ]

        self.edge_names = []
        self.edge_midpoints = []
        self.edge_curves = []

        for name, p0, p1 in edges:
            self.edge_names.append(name)
            mid = rg.Point3d(
                0.5 * (p0.X + p1.X),
                0.5 * (p0.Y + p1.Y),
                0.5 * (p0.Z + p1.Z)
            )
            self.edge_midpoints.append(mid)
            self.edge_curves.append(rg.LineCurve(p0, p1))

        self.log.append("✓ 边线与中点列表已生成（{}条）。".format(len(self.edge_names)))

    # --------------------------------------------------------------
    # 参考平面（增加 YZPlane）
    # --------------------------------------------------------------
    def _build_ref_planes(self):
        """构造输出所需的几个参考平面。"""

        # 0. 过 BasePoint 的原始参考平面（XZ）
        ref_plane_out = rg.Plane(self.ref_plane)

        # 1. 过 A-B-C-D 几何中心的平面（XY）
        A = self.points["A"]
        B = self.points["B"]
        C = self.points["C"]
        D = self.points["D"]
        center = rg.Point3d(
            0.25 * (A.X + B.X + C.X + D.X),
            0.25 * (A.Y + B.Y + C.Y + D.Y),
            0.25 * (A.Z + B.Z + C.Z + D.Z)
        )
        rect_center_plane = rg.Plane(center,
                                     self.ref_plane.XAxis,
                                     self.ref_plane.YAxis)

        # 2. 过 A-B 中点的“宽 × 拉伸”平面（XZ）
        mid_ab = rg.Point3d(
            0.5 * (A.X + B.X),
            0.5 * (A.Y + B.Y),
            0.5 * (A.Z + B.Z)
        )
        ab_mid_plane = rg.Plane(mid_ab,
                                self.ref_plane.XAxis,
                                self.ref_plane.ZAxis)

        # 3. 过 C-D 中点的“宽 × 拉伸”平面（XZ）
        mid_cd = rg.Point3d(
            0.5 * (C.X + D.X),
            0.5 * (C.Y + D.Y),
            0.5 * (C.Z + D.Z)
        )
        cd_mid_plane = rg.Plane(mid_cd,
                                self.ref_plane.XAxis,
                                self.ref_plane.ZAxis)

        # 4. 侧面参考平面：沿拉伸方向偏移一半
        extrude_vec = rg.Vector3d(self.z_dir)
        extrude_vec.Unitize()
        side_center = center + extrude_vec * (self.extrude_fen * 0.5)
        side_center_plane = rg.Plane(side_center,
                                     self.ref_plane.XAxis,
                                     self.z_dir)

        # 5. 新增：YZ 参考平面（过 BasePoint, X=Y 轴, Y=Z 轴）
        yz_plane = rg.Plane(self.base_point,
                            self.ref_plane.YAxis,
                            self.ref_plane.ZAxis)

        self.ref_planes = [ref_plane_out,
                           rect_center_plane,
                           ab_mid_plane,
                           cd_mid_plane,
                           side_center_plane,
                           yz_plane]

        self.log.append("✓ 参考平面已生成（6 个，含 YZPlane）。")

    # ==============================================================
    # 统一构建接口
    # ==============================================================
    def build(self):
        self._build_key_points()
        self._build_sections()
        self._build_tools()
        self._build_edges()
        self._build_ref_planes()

        key_points = [self.points[n] for n in ["A", "B", "C", "D",
                                               "E", "F", "G", "H",
                                               "I", "J"]]
        key_point_names = ["A", "B", "C", "D",
                           "E", "F", "G", "H",
                           "I", "J"]

        return {
            "OuterTool": self.outer_tool,
            "InnerTool": self.inner_tool,
            "OuterSection": self.outer_section,
            "InnerSection": self.inner_section,
            "RefPlanes": self.ref_planes,
            "EdgeMidPoints": self.edge_midpoints,
            "EdgeNames": self.edge_names,
            "KeyPoints": key_points,
            "KeyPointNames": key_point_names,
            "EdgeCurves": self.edge_curves,
            "Log": self.log,
            "RefPlaneNames": [
                "RefPlaneOut",
                "RectCenterPlane",
                "AB_MidPlane",
                "CD_MidPlane",
                "SideCenterPlane",
                "YZPlane",
            ],
        }

if __name__ == "__main__":
    # ==============================================================
    # GhPython 入口
    # ==============================================================

    if BasePoint is None:
        BasePoint = rg.Point3d(0, 0, 0)

    if 'RefPlane' not in globals():
        RefPlane = None

    if WidthFen is None or WidthFen == 0:
        WidthFen = 10.0

    if HeightFen is None or HeightFen == 0:
        HeightFen = 15.0

    if EdgeOffsetFen is None or EdgeOffsetFen == 0:
        EdgeOffsetFen = 1.0

    if TopInsetFen is None or TopInsetFen == 0:
        TopInsetFen = 5.0

    if ExtrudeFen is None or ExtrudeFen == 0:
        ExtrudeFen = 10.0

    builder = RuFangKaKouBuilder(
        base_point=BasePoint,
        ref_plane=RefPlane,
        width_fen=WidthFen,
        height_fen=HeightFen,
        edge_offset_fen=EdgeOffsetFen,
        top_inset_fen=TopInsetFen,
        extrude_fen=ExtrudeFen
    )

    result = builder.build()

    OuterTool = result["OuterTool"]
    InnerTool = result["InnerTool"]
    OuterSection = result["OuterSection"]
    InnerSection = result["InnerSection"]
    RefPlanes = result["RefPlanes"]
    EdgeMidPoints = result["EdgeMidPoints"]
    EdgeNames = result["EdgeNames"]
    KeyPoints = result["KeyPoints"]
    KeyPointNames = result["KeyPointNames"]
    EdgeCurves = result["EdgeCurves"]
    Log = result["Log"]
    RefPlaneNames = result["RefPlaneNames"]

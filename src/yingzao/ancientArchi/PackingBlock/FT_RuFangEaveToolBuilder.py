# -*- coding: utf-8 -*-
"""
GhPython 组件：橑檐方 (RuFang Eave Tool)

几何约定（参见手绘图 D-E-F-A / C-B）：
- 参考平面 RefPlane：
    * RefPlane.XAxis：D-A / C-B 方向（宽方向）
    * RefPlane.YAxis：B-A / C-D 方向（高方向）
    * RefPlane.ZAxis：平面法向（垂直截面，用作拉伸方向）

- 基准点：输入参数点（C 点左下角）

- 矩形 A-B-C-D-A：
    * A-B = C-D = HeightFen     （沿 RefPlane.YAxis）
    * D-A = C-B = WidthFen      （沿 RefPlane.XAxis）

- 斜边定位：
    * D-E = WidthFen / 2         （沿 -RefPlane.XAxis）
    * 最终截面：A-B-C-E-A（斜边 E-A）

- 截面拉伸：
    * 沿 RefPlane.ZAxis 拉伸 ExtrudeFen，生成封闭 Brep

============================================================
建议在 GhPython 组件中设置的输入参数（用于 setup_io）:

    InputPoint : rg.Point3d
        基准点（C 点位置，矩形左下角）。

    RefPlane : rg.Plane (可选)
        截面参考平面。若为 None，则自动生成一个以 InputPoint
        为原点的 XZ 平面（XAxis=World X, YAxis=World Z）。

    WidthFen : float
        D-A / C-B 长度（分°），默认 10.0。

    HeightFen : float
        A-B / C-D 长度（分°），默认 30.0。

    ExtrudeFen : float
        截面沿 RefPlane.ZAxis 拉伸长度（分°），默认 100.0。

============================================================
建议在 GhPython 组件中设置的输出参数（用于 setup_io）:

    EveTool : rg.Brep
        橑檐方封闭 Brep 对象（截面 A-B-C-E-A 沿 Z 轴拉伸）。

    Section : rg.PolylineCurve
        截面多段线 A-B-C-E-A。

    SectionVertices : list[rg.Point3d]
        截面顶点列表 [A, B, C, E]。

    SectionVertexNames : list[str]
        对应顶点名 ["A", "B", "C", "E"]。

    RectEdgeMidPoints : list[rg.Point3d]
        矩形 A-B-C-D 四条边的中点列表 [AB_mid, BC_mid, CD_mid, DA_mid]。

    RectEdgeNames : list[str]
        对应边名 ["AB", "BC", "CD", "DA"]。

    RefPlaneList : list[rg.Plane]
        基于参考平面的三个方向的参考平面列表（过 F 点）：
        [0] RefPlane_X    : 过 F 点，法向 = RefPlane.XAxis
        [1] RefPlane_Y    : 过 F 点，法向 = RefPlane.YAxis
        [2] RefPlane_Z    : 过 F 点，法向 = RefPlane.ZAxis

    RefPlaneNames : list[str]
        对应平面名 ["RefPlane_X", "RefPlane_Y", "RefPlane_Z"]。

    Log : list[str]
        调试信息与计算过程记录。
"""

import Rhino
import Rhino.Geometry as rg

# --------------------------------------------------------------------
# 全局公差
# --------------------------------------------------------------------
try:
    TOL = Rhino.RhinoDoc.ActiveDoc.ModelAbsoluteTolerance
except:
    TOL = 0.001


class RuFangEaveToolBuilder(object):
    """橑檐方特征刀具构造器"""

    def __init__(self,
                 input_point,
                 ref_plane,
                 width_fen,
                 height_fen,
                 extrude_fen):
        self.input_point = input_point
        self.ref_plane = ref_plane
        self.width_fen = float(width_fen)
        self.height_fen = float(height_fen)
        self.extrude_fen = float(extrude_fen)
        self.log = []

        self._ensure_plane()
        self._normalize_axes()

    # --------------------------------------------------------------
    # 基本平面与坐标处理
    # --------------------------------------------------------------
    def _ensure_plane(self):
        """若未提供 RefPlane，则用 InputPoint 构造一个 XZ 平面。"""
        if self.ref_plane is None:
            # XAxis = World X, YAxis = World Z
            self.ref_plane = rg.Plane(self.input_point,
                                      rg.Vector3d.XAxis,
                                      rg.Vector3d.ZAxis)
            self.log.append("✓ RefPlane 为 None，已自动创建 XZ 平面。")
        else:
            # 把输入平面原点移到 InputPoint
            plane = rg.Plane(self.ref_plane)
            plane.Origin = self.input_point
            self.ref_plane = plane
            self.log.append("✓ RefPlane 已同步到 InputPoint。")

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
        """计算 A, B, C, D, E 等关键点。"""

        C = self.input_point  # 基准点（左下角）
        W = self.width_fen    # C-B 长度（X 轴方向）
        H = self.height_fen   # C-D 长度（Y 轴方向）

        # 矩形四角
        # C 在原点（左下）
        B = C + self.x_dir * W      # 右下，沿 X 轴
        D = C + self.y_dir * H      # 左上，沿 Y 轴
        A = D + self.x_dir * W      # 右上

        # 点 E：在 D-C 直线上（左边边线），D-E = W/2（D-A 的一半）
        # E 从 D 沿 -Y 方向移动 W/2
        E = D - self.y_dir * (W * 0.5)

        self.points = {
            "A": A,
            "B": B,
            "C": C,
            "D": D,
            "E": E
        }

        self.log.append("✓ 关键点计算完成。")
        self.log.append("  C(原点) → B(沿 X 轴 {}°)".format(W))
        self.log.append("  C(原点) → D(沿 Y 轴 {}°)".format(H))
        self.log.append("  E 在 D-C 直线上，D-E = {}°".format(W * 0.5))

    # --------------------------------------------------------------
    # 截面曲线
    # --------------------------------------------------------------
    def _build_section(self):
        """构造截面 PolylineCurve A-B-C-E-A。"""

        A = self.points["A"]
        B = self.points["B"]
        C = self.points["C"]
        E = self.points["E"]

        # 截面顶点顺序：A → B → C → E → A
        section_pts = [A, B, C, E, A]
        section_pl = rg.Polyline(section_pts)
        self.section = section_pl.ToPolylineCurve()

        self.log.append("✓ 截面多段线已生成（A-B-C-E-A）。")

    # ==============================================================
    # 核心方法：曲线 → 封闭 Brep（先平面，再拉伸）
    # ==============================================================
    def _extrude_closed_curve_to_brep(self, curve, vector, curve_name="curve"):
        """
        从闭合截面曲线生成封闭 Brep：
        1. CreatePlanarBreps 生成底面
        2. Surface.CreateExtrusion 生成侧面
        3. 创建顶面
        4. 合并并闭合
        """
        if curve is None:
            self.log.append("✗ {} 为 None，跳过。".format(curve_name))
            return None

        if vector.IsZero:
            self.log.append("✗ {} 拉伸向量为 0，跳过。".format(curve_name))
            return None

        # --------------------------------------------------
        # 1. 验证曲线闭合
        # --------------------------------------------------
        if not curve.IsClosed:
            self.log.append("✗ {} 未闭合，跳过。".format(curve_name))
            return None

        # --------------------------------------------------
        # 2. 创建底面（平面 Brep）
        # --------------------------------------------------
        planar_breps = rg.Brep.CreatePlanarBreps([curve], TOL)
        if not planar_breps or len(planar_breps) == 0:
            self.log.append("✗ CreatePlanarBreps 失败（{}）。".format(curve_name))
            return None

        base_brep = planar_breps[0]
        if base_brep is None or base_brep.Faces.Count == 0:
            self.log.append("✗ CreatePlanarBreps 生成空 Brep（{}）。".format(curve_name))
            return None

        self.log.append("  → 底面生成成功。")

        # --------------------------------------------------
        # 3. 拉伸侧面
        # --------------------------------------------------
        side_surf = rg.Surface.CreateExtrusion(curve, vector)
        if not side_surf:
            self.log.append("✗ Surface.CreateExtrusion 失败（{}）。".format(curve_name))
            return None

        side_brep = rg.Brep.CreateFromSurface(side_surf)
        if not side_brep:
            self.log.append("✗ Brep.CreateFromSurface 失败（{}）。".format(curve_name))
            return None

        self.log.append("  → 侧面生成成功。")

        # --------------------------------------------------
        # 4. 合并：底面 + 侧面 + 顶面
        # --------------------------------------------------
        final_brep = side_brep

        # 添加底面
        try:
            final_brep.Append(base_brep)
            self.log.append("  → 底面已添加。")
        except Exception as e:
            self.log.append("  ⚠ 底面添加异常: {}".format(e))

        # 创建顶面
        try:
            top_curve = curve.DuplicateCurve()
            top_curve.Translate(vector)

            top_planar_breps = rg.Brep.CreatePlanarBreps([top_curve], TOL)
            if top_planar_breps and len(top_planar_breps) > 0:
                top_brep = top_planar_breps[0]
                if top_brep.Faces.Count > 0:
                    top_brep.Faces[0].Reverse(1, True)
                final_brep.Append(top_brep)
                self.log.append("  → 顶面已添加。")
            else:
                self.log.append("  ⚠ 顶面创建失败。")
        except Exception as e:
            self.log.append("  ⚠ 顶面添加异常: {}".format(e))

        # --------------------------------------------------
        # 5. 闭合处理
        # --------------------------------------------------
        capped = final_brep.CapPlanarHoles(TOL)
        if capped is not None:
            final_brep = capped
            self.log.append("  → CapPlanarHoles 成功闭合。")

        if not final_brep.IsSolid:
            try:
                solid_brep = rg.Brep.CreateSolid(final_brep, TOL)
                if solid_brep is not None:
                    final_brep = solid_brep
                    self.log.append("  → CreateSolid 成功转为实体。")
            except Exception as e:
                self.log.append("  ⚠ CreateSolid 异常: {}".format(e))

        # --------------------------------------------------
        # 6. 合并共面面片
        # --------------------------------------------------
        try:
            final_brep.MergeCoplanarFaces(TOL, True)
            self.log.append("  → 共面面片已合并。")
        except Exception as e:
            self.log.append("  ⚠ MergeCoplanarFaces 异常: {}".format(e))

        # --------------------------------------------------
        # 7. 最终检查
        # --------------------------------------------------
        if final_brep.IsSolid:
            self.log.append("✓ {} 生成成功（IsSolid=True）。".format(curve_name))
        else:
            self.log.append("⚠ {} 未完全闭合（IsSolid=False）。".format(curve_name))

        return final_brep

    # ==============================================================
    # 实体拉伸
    # ==============================================================
    def _build_tool(self):
        """沿 RefPlane.ZAxis 拉伸截面，生成刀具实体。"""

        vec = rg.Vector3d(self.z_dir)
        vec.Unitize()
        vec *= self.extrude_fen

        self.log.append("\n--- 开始构建 EveTool ---")
        eve_brep = self._extrude_closed_curve_to_brep(
            self.section, vec, "Section"
        )

        self.eve_tool = eve_brep

    # --------------------------------------------------------------
    # 矩形边中点
    # --------------------------------------------------------------
    def _build_rect_edge_midpoints(self):
        """计算矩形 A-B-C-D 四条边的中点。"""

        A = self.points["A"]
        B = self.points["B"]
        C = self.points["C"]
        D = self.points["D"]

        edges = [
            ("AB", A, B),
            ("BC", B, C),
            ("CD", C, D),
            ("DA", D, A),
        ]

        self.rect_edge_names = []
        self.rect_edge_midpoints = []

        for name, p0, p1 in edges:
            self.rect_edge_names.append(name)
            mid = rg.Point3d(
                0.5 * (p0.X + p1.X),
                0.5 * (p0.Y + p1.Y),
                0.5 * (p0.Z + p1.Z)
            )
            self.rect_edge_midpoints.append(mid)

        self.log.append("✓ 矩形边中点已计算（4 条边）。")

    # --------------------------------------------------------------
    # 参考平面（过 F 点，三个方向）
    # --------------------------------------------------------------
    def _build_ref_planes(self):
        """构造过 F 点（截面中心）基于参考平面三个方向的平面。"""

        # 计算 F 点（截面 A-B-C-E 的几何中心）
        A = self.points["A"]
        B = self.points["B"]
        C = self.points["C"]
        E = self.points["E"]

        f_point = rg.Point3d(
            0.25 * (A.X + B.X + C.X + E.X),
            0.25 * (A.Y + B.Y + C.Y + E.Y),
            0.25 * (A.Z + B.Z + C.Z + E.Z)
        )

        # 三个参考平面（法向分别沿 X、Y、Z 方向）
        # [0] RefPlane_X：法向 = RefPlane.XAxis，包含 Y 和 Z 方向
        ref_plane_x = rg.Plane(f_point, self.y_dir, self.z_dir)

        # [1] RefPlane_Y：法向 = RefPlane.YAxis，包含 X 和 Z 方向
        ref_plane_y = rg.Plane(f_point, self.x_dir, self.z_dir)

        # [2] RefPlane_Z：法向 = RefPlane.ZAxis，包含 X 和 Y 方向
        ref_plane_z = rg.Plane(f_point, self.x_dir, self.y_dir)

        self.ref_planes = [ref_plane_x, ref_plane_y, ref_plane_z]
        self.f_point = f_point

        self.log.append("✓ 参考平面已生成（过 F 点，3 个方向）。")

    # ==============================================================
    # 统一构建接口
    # ==============================================================
    def build(self):
        """主构建方法。"""
        self._build_key_points()
        self._build_section()
        self._build_tool()
        self._build_rect_edge_midpoints()
        self._build_ref_planes()

        section_vertices = [
            self.points["A"],
            self.points["B"],
            self.points["C"],
            self.points["E"]
        ]
        section_vertex_names = ["A", "B", "C", "E"]

        return {
            "EveTool": self.eve_tool,
            "Section": self.section,
            "SectionVertices": section_vertices,
            "SectionVertexNames": section_vertex_names,
            "RectEdgeMidPoints": self.rect_edge_midpoints,
            "RectEdgeNames": self.rect_edge_names,
            "RefPlaneList": self.ref_planes,
            "RefPlaneNames": ["RefPlane_X", "RefPlane_Y", "RefPlane_Z"],
            "Log": self.log,
        }

if __name__=="__main__":
    # ==============================================================
    # GhPython 入口
    # ==============================================================

    # ---- 输入默认值 ----
    if InputPoint is None:
        InputPoint = rg.Point3d(0, 0, 0)

    if 'RefPlane' not in globals():
        RefPlane = None

    if WidthFen is None or WidthFen == 0:
        WidthFen = 10.0

    if HeightFen is None or HeightFen == 0:
        HeightFen = 30.0

    if ExtrudeFen is None or ExtrudeFen == 0:
        ExtrudeFen = 100.0

    # ---- 构建对象 ----
    builder = RuFangEaveToolBuilder(
        input_point=InputPoint,
        ref_plane=RefPlane,
        width_fen=WidthFen,
        height_fen=HeightFen,
        extrude_fen=ExtrudeFen
    )

    result = builder.build()

    # ---- 输出到 GhPython 组件 ----
    EveTool             = result["EveTool"]
    Section             = result["Section"]
    SectionVertices     = result["SectionVertices"]
    SectionVertexNames  = result["SectionVertexNames"]
    RectEdgeMidPoints   = result["RectEdgeMidPoints"]
    RectEdgeNames       = result["RectEdgeNames"]
    RefPlaneList        = result["RefPlaneList"]
    RefPlaneNames       = result["RefPlaneNames"]
    Log                 = result["Log"]
# -*- coding: utf-8 -*-
"""
EntasisColumn_AssemblySolver
梭柱（EntasisColumn）· 单一 GhPython 组件（把多个 ghpy/gh 组件串联为一个）

本组件按你给定的“分°/尺 → cm → 构建刀具 → 圆柱木料 → 布尔切割”流程整合：
- step 1：单位换算
  - SongStyleUnitConverter：柱径/AB/BC（分°）→ cm（受 Grade 与 ChiToCm 影响）
  - ChiToMetric_Chi2Metric：柱高（尺）→ cm（受 ChiToCm 影响）
- step 2：构建卷杀刀具（SuoZhuJuanShaToolBuilder）
- step 3：构建圆柱木料（严格“封面”的 Solid）并以刀具切割
  - 使用：FT_CutTimbersByTools_GH_SolidDifference（替代 FT_CutTimberByTools_V2）

注意（你强调的 GH 默认平面轴向关系）：
- XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
- XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
- YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)

----------------------------------------------------------------------
输入（GhPython 建议设置）:
    PlacePlane : rg.Plane (Item)
        放置参考平面（默认 GH 的 XY Plane，原点(0,0,0)）
        Access: Item
        TypeHints: Plane

    Grade : str (Item)
        等材（默认“第六等”）
        Access: Item
        TypeHints: str

    ColumnDiameterFen : float (Item)
        柱径（单位：分°，营造法式模数单位）
        Access: Item
        TypeHints: float

    ColumnHeightChi : float (Item)
        柱高（单位：尺）
        Access: Item
        TypeHints: float

    ChiToCm : float (Item)
        1 尺 = ? cm（默认 31.2）
        Access: Item
        TypeHints: float

    JuanShaLen_AB_Fen : float (Item)
        卷杀分段一长度 AB（单位：分°，默认 5）
        Access: Item
        TypeHints: float

    JuanShaLen_BC_Fen : float (Item)
        卷杀分段二长度 BC（单位：分°，默认 4）
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    AbsStructRep : object (Item)
        结果体（= FT_CutTimbersByTools_GH_SolidDifference 的 CutTimbers）
        Access: Item
        TypeHints: (No hints)

    Log : str (Item)
        日志
        Access: Item
        TypeHints: str

    OutputsDict : dict (Item)   （可选）
        Solver 成员变量字典（便于调试/扩展）
        Access: Item
        TypeHints: (No hints)
----------------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg
import Grasshopper as gh
import Grasshopper.Kernel as ghk
import Grasshopper.Kernel.Parameters as ghp


from yingzao.ancientArchi import (
    SongStyleUnitConverter,
    ChiToMetric_Chi2Metric,
    SuoZhuJuanShaToolBuilder,
    FT_CutTimbersByTools_GH_SolidDifference,
    coerce_float,
    coerce_str,
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.02.21"

'''
ghenv.Component.Name = "梭柱•宋（EntasisColumn）"
ghenv.Component.NickName = "EntasisColumn_AssemblySolver"
ghenv.Component.Description = "梭柱（EntasisColumn）组件整合：单位换算 + 卷杀刀具 + 实体差集切割"
ghenv.Component.Message = "1.0"
ghenv.Component.Category = "YingZaoLab"
ghenv.Component.SubCategory = "柱作"
ghenv.Component.AdditionalHelpFromDocStrings = "1"
'''

# =========================================================
# IO 端口配置（便于自动生成输入输出端）
# =========================================================
def setup_io(comp):
    """
    EntasisColumn_AssemblySolver

    ----------------------------------------------------------------------
    输入（GhPython 建议设置）:
        PlacePlane : rg.Plane (Item)
            放置参考平面（默认 GH 的 XY Plane，原点(0,0,0)）
            Access: Item
            TypeHints: Plane

        Grade : str (Item)
            等材（默认“第六等”）
            Access: Item
            TypeHints: str

        ColumnDiameterFen : float (Item)
            柱径（单位：分°，营造法式模数单位）
            Access: Item
            TypeHints: float

        ColumnHeightChi : float (Item)
            柱高（单位：尺）
            Access: Item
            TypeHints: float

        ChiToCm : float (Item)
            1 尺 = ? cm（默认 31.2）
            Access: Item
            TypeHints: float

        JuanShaLen_AB_Fen : float (Item)
            卷杀分段一长度 AB（单位：分°，默认 5）
            Access: Item
            TypeHints: float

        JuanShaLen_BC_Fen : float (Item)
            卷杀分段二长度 BC（单位：分°，默认 4）
            Access: Item
            TypeHints: float

    输出（GhPython 建议设置）:
        AbsStructRep : object (Item)
            结果体（= FT_CutTimbersByTools_GH_SolidDifference 的 CutTimbers）
            Access: Item
            TypeHints: (No hints)

        Log : str (Item)
            日志
            Access: Item
            TypeHints: str

        OutputsDict : dict (Item)
            Solver 成员变量字典（便于调试/扩展）
            Access: Item
            TypeHints: (No hints)
    ----------------------------------------------------------------------
    """
    pass


# =========================================================
# 兼容式读取（支持别名），避免你这次日志中“柱径/柱高=0”的问题
# =========================================================
def _gh_get(name, default=None, aliases=None):
    if aliases is None:
        aliases = []
    try:
        return globals()[name]
    except Exception:
        pass
    for a in aliases:
        try:
            return globals()[a]
        except Exception:
            continue
    return default


# =========================================================
# 主 Solver
# =========================================================
class EntasisColumn_AssemblySolver(object):
    def __init__(
        self,
        place_plane,
        grade,
        column_diameter_fen,
        column_height_chi,
        chi_to_cm,
        juansha_len_ab_fen,
        juansha_len_bc_fen,
        tolerance=1e-7,
        keep_inside=False,
        debug=None
    ):
        self.PlacePlane = place_plane
        self.Grade = grade
        self.ColumnDiameterFen = column_diameter_fen
        self.ColumnHeightChi = column_height_chi
        self.ChiToCm = chi_to_cm
        self.JuanShaLen_AB_Fen = juansha_len_ab_fen
        self.JuanShaLen_BC_Fen = juansha_len_bc_fen
        self.Tolerance = tolerance
        self.KeepInside = keep_inside
        self.Debug = debug

        # outputs / internals
        self.LogLines = []
        self.Log = ""
        self.AbsStructRep = None

        # step 1
        self.ColumnDia_CM = 0.0
        self.ColumnRadius_CM = 0.0
        self.JuanShaLen_AB_CM = 0.0
        self.JuanShaLen_BC_CM = 0.0
        self.ColumnHeight_CM = 0.0

        # step 2
        self.ToolBasePlane = None
        self.JuanShaToolBrep = None
        self.SectionProfileCrv = None
        self.SectionOutlineCrv = None
        self.SectionFace = None
        self.KeyPts = None
        self.GuideCrvs = None
        self.ToolDebugLog = ""

        # step 3
        self.TimberCircleCrv = None
        self.TimberBrep = None
        self.CutTimbers = None
        self.FailTimbers = None
        self.CutLog = ""

        self._run()

    def _log(self, s):
        try:
            self.LogLines.append(str(s))
        except Exception:
            pass

    def _safe_plane(self, pl):
        if isinstance(pl, rg.Plane):
            return pl
        return rg.Plane.WorldXY

    def _make_capped_cylinder_from_plane(self, base_plane, radius_cm, height_cm):
        """
        关键修复：
        - 你的环境中 rg.Brep.CreateFromExtrusion 不存在
        - 改用 rg.Extrusion.Create(curve, height, cap=True).ToBrep()
        """
        base_plane = self._safe_plane(base_plane)
        r = float(radius_cm)
        h = float(height_cm)

        circle = rg.Circle(base_plane, r)
        crv = circle.ToNurbsCurve()

        ext = rg.Extrusion.Create(crv, h, True)  # True => cap
        if ext is None:
            raise Exception("Extrusion.Create failed. (curve may be invalid or not closed)")
        brep = ext.ToBrep()

        return crv, brep

    def _step1_unit_convert(self):
        grade_in = coerce_str(self.Grade, default="第六等")
        chi_to_cm_in = coerce_float(self.ChiToCm, default=31.2)

        col_d_fen = coerce_float(self.ColumnDiameterFen, default=0.0)
        ab_fen = coerce_float(self.JuanShaLen_AB_Fen, default=5.0)
        bc_fen = coerce_float(self.JuanShaLen_BC_Fen, default=4.0)

        conv = SongStyleUnitConverter(chi_to_cm=chi_to_cm_in)

        # 分° -> 尺值 -> cm
        col_d_chi = conv.fen_to_chi(grade_in, col_d_fen)
        ab_chi = conv.fen_to_chi(grade_in, ab_fen)
        bc_chi = conv.fen_to_chi(grade_in, bc_fen)

        self.ColumnDia_CM = float(conv.chi_to_cm_value(col_d_chi))
        self.ColumnRadius_CM = self.ColumnDia_CM * 0.5
        self.JuanShaLen_AB_CM = float(conv.chi_to_cm_value(ab_chi))
        self.JuanShaLen_BC_CM = float(conv.chi_to_cm_value(bc_chi))

        # 柱高：尺 -> cm
        try:
            _h_converter = ChiToMetric_Chi2Metric(self.ColumnHeightChi, chi_to_cm_in)
            _, h_cm, _ = _h_converter.convert()
            self.ColumnHeight_CM = float(h_cm)
        except Exception:
            self.ColumnHeight_CM = 0.0

        self._log("[step1] Grade=%s, ChiToCm=%.6f" % (grade_in, chi_to_cm_in))
        self._log("[step1] ColumnDia: %.6f cm (R=%.6f cm)" % (self.ColumnDia_CM, self.ColumnRadius_CM))
        self._log("[step1] AB: %.6f cm, BC: %.6f cm" % (self.JuanShaLen_AB_CM, self.JuanShaLen_BC_CM))
        self._log("[step1] ColumnHeight: %.6f cm" % (self.ColumnHeight_CM))

        # 给一个强提示：如果为 0，基本就是输入没读到或输入为 0
        if self.ColumnDia_CM <= 0.0:
            self._log("[step1][WARN] ColumnDia_CM is 0. Check GH input name: ColumnDiameterFen (or alias ColumnDia_Fen).")
        if self.ColumnHeight_CM <= 0.0:
            self._log("[step1][WARN] ColumnHeight_CM is 0. Check GH input name: ColumnHeightChi (or alias ColumnHeight_Chi).")

    def _step2_build_tool(self):
        # BasePlane：PlacePlane 沿自身 Z 轴移动到 “柱高 cm” 处（只变原点，不变轴）
        pl = self._safe_plane(self.PlacePlane)
        dz = rg.Vector3d(pl.ZAxis)
        dz.Unitize()
        dz *= self.ColumnHeight_CM

        tool_plane = rg.Plane(pl)
        tool_plane.Origin = tool_plane.Origin + dz
        self.ToolBasePlane = tool_plane

        # 你给定的对应关系
        suo_zhu_radius = self.ColumnRadius_CM
        juansha_ab = self.JuanShaLen_AB_CM
        juansha_bc = self.JuanShaLen_BC_CM
        juansha_drop_ci = self.JuanShaLen_BC_CM
        suo_zhu_height_ah = self.ColumnHeight_CM / 3.0

        builder = SuoZhuJuanShaToolBuilder(
            base_plane=tool_plane,
            suo_zhu_radius=suo_zhu_radius,
            juansha_len_ab=juansha_ab,
            juansha_len_bc=juansha_bc,
            suo_zhu_height_ah=suo_zhu_height_ah,
            juansha_drop_ci=juansha_drop_ci,
            tolerance=self.Tolerance
        )

        self.JuanShaToolBrep = builder.JuanShaToolBrep
        self.SectionProfileCrv = builder.SectionProfileCrv
        self.SectionOutlineCrv = builder.SectionOutlineCrv
        self.SectionFace = builder.SectionFace
        self.KeyPts = builder.KeyPts
        self.GuideCrvs = builder.GuideCrvs
        self.ToolDebugLog = builder.DebugLog

        self._log("[step2] ToolBasePlane moved to column top (Origin shifted along PlacePlane.ZAxis).")
        self._log("[step2] Tool params: R=%.6f, AB=%.6f, BC=%.6f, CI=%.6f, AH=%.6f"
                  % (suo_zhu_radius, juansha_ab, juansha_bc, juansha_drop_ci, suo_zhu_height_ah))

    def _step3_build_timber_and_cut(self):
        # Timbers：以 PlacePlane 原点为圆心，半径=柱径/2，向 PlacePlane.ZAxis 拉伸柱高 cm 的“封口实体圆柱”
        self.TimberCircleCrv, self.TimberBrep = self._make_capped_cylinder_from_plane(
            self.PlacePlane, self.ColumnRadius_CM, self.ColumnHeight_CM
        )

        tools = self.JuanShaToolBrep
        timbers = self.TimberBrep

        # 改为：FT_CutTimbersByTools_GH_SolidDifference
        cutter = FT_CutTimbersByTools_GH_SolidDifference(
            debug=bool(self.Debug) if self.Debug is not None else False
        )
        self.CutTimbers, self.FailTimbers, self.CutLog = cutter.cut(
            timbers=timbers,
            tools=tools,
            keep_inside=bool(self.KeepInside),
            debug=self.Debug
        )

        # AbsStructRep 必须为 CutTimbers
        self.AbsStructRep = self.CutTimbers

        self._log("[step3] Timber built via Extrusion.Create(curve, height, cap=True).ToBrep().")
        self._log("[step3] CutTimbers type: %s" % (type(self.CutTimbers).__name__,))

    def _run(self):
        try:
            self._step1_unit_convert()
            self._step2_build_tool()
            self._step3_build_timber_and_cut()
        except Exception as e:
            self._log("[ERROR] %s" % str(e))

        # 汇总日志
        try:
            self.Log = "\n".join(self.LogLines)
        except Exception:
            self.Log = ""


# =========================================================
# GH Python 组件式入口
# =========================================================
if __name__ == "__main__":

    # ---- 输入读取 + 默认值（并做别名兼容）----
    PlacePlane = _gh_get("PlacePlane", rg.Plane.WorldXY)

    Grade = _gh_get("Grade", "第六等")

    # ✅柱径：兼容 ColumnDiameterFen / ColumnDia_Fen
    ColumnDiameterFen = _gh_get("ColumnDiameterFen", None, aliases=["ColumnDia_Fen"])
    if ColumnDiameterFen is None:
        ColumnDiameterFen = 0.0

    # ✅柱高：兼容 ColumnHeightChi / ColumnHeight_Chi
    ColumnHeightChi = _gh_get("ColumnHeightChi", None, aliases=["ColumnHeight_Chi"])
    if ColumnHeightChi is None:
        ColumnHeightChi = 0.0

    ChiToCm = _gh_get("ChiToCm", 31.2)
    JuanShaLen_AB_Fen = _gh_get("JuanShaLen_AB_Fen", 5.0)
    JuanShaLen_BC_Fen = _gh_get("JuanShaLen_BC_Fen", 4.0)

    # 可选输入（若你未来加端口，可直接用）
    KeepInside = _gh_get("KeepInside", False)
    Tolerance = _gh_get("Tolerance", 1e-7)
    Debug = _gh_get("Debug", None)

    Solver = EntasisColumn_AssemblySolver(
        place_plane=PlacePlane,
        grade=Grade,
        column_diameter_fen=ColumnDiameterFen,
        column_height_chi=ColumnHeightChi,
        chi_to_cm=ChiToCm,
        juansha_len_ab_fen=JuanShaLen_AB_Fen,
        juansha_len_bc_fen=JuanShaLen_BC_Fen,
        tolerance=Tolerance,
        keep_inside=KeepInside,
        debug=Debug
    )

    # =====================================================
    # GH Python 组件 · 输出绑定区
    # 说明：
    # - 当前只强制暴露 AbsStructRep / Log（按你阶段要求）
    # - 其它内部变量全部已保存在 Solver 成员中；下面逐一绑定同名输出端，便于后续增减
    # =====================================================

    # ---- 必要输出 ----
    AbsStructRep = Solver.AbsStructRep
    Log = Solver.Log

    # ----（可选）调试总字典：不占用大量端口也能看到所有内部结果 ----
    OutputsDict = Solver.__dict__

    # ---- step 1 internals ----
    PlacePlane = Solver.PlacePlane
    Grade = Solver.Grade
    ColumnDiameterFen = Solver.ColumnDiameterFen
    ColumnHeightChi = Solver.ColumnHeightChi
    ChiToCm = Solver.ChiToCm
    JuanShaLen_AB_Fen = Solver.JuanShaLen_AB_Fen
    JuanShaLen_BC_Fen = Solver.JuanShaLen_BC_Fen

    ColumnDia_CM = Solver.ColumnDia_CM
    ColumnRadius_CM = Solver.ColumnRadius_CM
    JuanShaLen_AB_CM = Solver.JuanShaLen_AB_CM
    JuanShaLen_BC_CM = Solver.JuanShaLen_BC_CM
    ColumnHeight_CM = Solver.ColumnHeight_CM

    # ---- step 2 internals ----
    ToolBasePlane = Solver.ToolBasePlane
    JuanShaToolBrep = Solver.JuanShaToolBrep
    SectionProfileCrv = Solver.SectionProfileCrv
    SectionOutlineCrv = Solver.SectionOutlineCrv
    SectionFace = Solver.SectionFace
    KeyPts = Solver.KeyPts
    GuideCrvs = Solver.GuideCrvs
    ToolDebugLog = Solver.ToolDebugLog

    # ---- step 3 internals ----
    TimberCircleCrv = Solver.TimberCircleCrv
    TimberBrep = Solver.TimberBrep
    CutTimbers = Solver.CutTimbers
    FailTimbers = Solver.FailTimbers
    CutLog = Solver.CutLog

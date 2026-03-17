# -*- coding: utf-8 -*-
"""
VaseASolver —— 寳瓶-A（Vase-A）一体化求解器 (Step 1 + Step 2)

步骤说明：
    Step 1: DBJsonReader 读取 CommonComponents 表中 Vase-A 的 params_json（ExportAll=True）
    Step 2: VaseGenerator 生成宝瓶 Brep（可选倾斜裁切）

输入（GhPython）：
    DBPath     : str         - SQLite 数据库路径
    base_point : Point3d     - 定位点（优先于 DB，若 None 则 DB，再无则原点）
    Refresh    : bool        - 刷新接口（可触发重算；逻辑上不需要 sticky）

输出（GhPython · 固定三输出）：
    CutTimbers : Brep / list[Brep] - 最终几何（宝瓶）
    FailTimbers: list              - 失败几何（默认空）
    Log        : str               - 日志

开发模式输出（developer-friendly）：
    本文件在“GH Python 输出绑定区”会把 solver 的成员变量逐项赋值到同名变量。
    你只要在 GH 组件上新增同名输出端，即可随时把任何内部变量挂出来调试。
"""

import traceback
import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    DBJsonReader,
    parse_all_to_dict,
    all_get,
    make_reference_plane,
    to_scalar,
)

from yingzao.ancientArchi import VaseGenerator


# ======================================================================
# 工具：安全取“组件输入端变量”（因为当前 ghpy 组件只声明 3 个输入端）
# ======================================================================
def _has_input(name):
    try:
        return name in globals()
    except:
        return False


def _get_input(name, default=None):
    if _has_input(name):
        v = globals().get(name, default)
        return v
    return default


def _is_empty_list(x):
    return isinstance(x, (list, tuple)) and len(x) == 0


# ======================================================================
# Solver 主类
# ======================================================================
class VaseA_Solver_4PU(object):
    def __init__(self, DBPath, base_point=None, Refresh=False, ghenv=None):
        self.DBPath = DBPath
        self.base_point_in = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # ---- Step1 outputs
        self.Value = None
        self.All = None
        self.AllDict = None
        self.DBLog = ""

        # ---- Step2 outputs（VaseGenerator）
        self.vase_base_point = None
        self.vase_ref_plane = None

        self.Vase__section_diameters = None
        self.Vase__section_heights = None
        self.Vase__bulge_distances = None
        self.Vase__close_caps = None
        self.Vase__cut_plane_height = None
        self.Vase__cut_plane_tilt_deg = None
        self.Vase__cut_enabled = None

        self.base_ref_plane = None

        self.circles = None
        self.rails = None
        self.cut_plane = None  # 按你原组件要求：不输出裁切面（置 None）
        self._cut_plane_internal = None
        self.vase = None
        self.info = None

        # ---- Debug outputs (from VaseGenerator internal attrs)
        self.BXPlane_Curves = None
        self.BXPlane_Points = None
        self.BoundarySurfaces_Surfaces = None
        self.BoundarySurfaces_CutterBrep = None
        self.SplitBrep_Fragments = None
        self.SplitBrep_Areas = None
        self.SplitBrep_SortedIndex = None
        self.SplitBrep_KeptBrep = None
        self.CappedBrep = None
        self.Cap_Count = None
        self.Cap_IsSolid = None

        # ---- Final outputs
        self.CutTimbers = None
        self.FailTimbers = []
        self.Log = ""

    # --------------------------------------------------------------
    # Step 1: DBJsonReader
    # --------------------------------------------------------------
    def step1_read_db(self):
        # DBJsonReader 参数（固定按你要求）
        Table = "CommonComponents"
        KeyField = "type_code"
        KeyValue = "Vase-A"
        Field = "params_json"
        JsonPath = None
        ExportAll = True

        reader = DBJsonReader(
            db_path=self.DBPath,
            table=Table,
            key_field=KeyField,
            key_value=KeyValue,
            field=Field,
            json_path=JsonPath,
            export_all=ExportAll,
            ghenv=self.ghenv
        )
        self.Value, self.All, self.DBLog = reader.run()

        # All → Dict（后续只允许从这里取值，不再二次读库）
        self.AllDict = parse_all_to_dict(self.All)

    # --------------------------------------------------------------
    # Step 2: VaseGenerator（寳瓶-A）
    # --------------------------------------------------------------
    def step2_build_vase(self):
        # 2.1 base_point：组件输入端 > DB > 默认原点
        db_bp = all_get(self.AllDict, "Vase", "base_point", None)
        bp = self.base_point_in if self.base_point_in is not None else db_bp
        if bp is None:
            bp = rg.Point3d(0, 0, 0)
        self.vase_base_point = bp

        # 2.2 ref_plane：默认 WorldXY；如 DB 写了 WorldXY/WorldXZ/WorldYZ，则转换
        # 注意：你要求的三大参考平面轴向关系，make_reference_plane 会按项目约定实现
        db_rp = all_get(self.AllDict, "Vase", "ref_plane", None)
        rp = db_rp if db_rp is not None else rg.Plane.WorldXY
        # 若 rp 为字符串/标记，则转换；若已是 Plane，则原样
        try:
            if isinstance(rp, str):
                rp = make_reference_plane(rp)
        except:
            rp = rg.Plane.WorldXY
        if rp is None:
            rp = rg.Plane.WorldXY
        self.vase_ref_plane = rp

        # 2.3 读取 DB 参数（命名规则：Vase__xxx）
        # 组件输入端只有 3 个，不在 GH 端开这些输入；因此这里只做 DB > 默认
        self.Vase__section_diameters = all_get(self.AllDict, "Vase", "section_diameters", None)
        self.Vase__section_heights = all_get(self.AllDict, "Vase", "section_heights", None)
        self.Vase__bulge_distances = all_get(self.AllDict, "Vase", "bulge_distances", None)

        self.Vase__close_caps = all_get(self.AllDict, "Vase", "close_caps", True)

        self.Vase__cut_plane_height = all_get(self.AllDict, "Vase", "cut_plane_height", 40.0)
        self.Vase__cut_plane_tilt_deg = all_get(self.AllDict, "Vase", "cut_plane_tilt_deg", 16.0)
        self.Vase__cut_enabled = all_get(self.AllDict, "Vase", "cut_enabled", True)

        # 2.4 兼容：可能被写成 [40.0] 这种单元素 list
        self.Vase__cut_plane_height = to_scalar(self.Vase__cut_plane_height, 40.0)
        self.Vase__cut_plane_tilt_deg = to_scalar(self.Vase__cut_plane_tilt_deg, 16.0)
        self.Vase__close_caps = bool(to_scalar(self.Vase__close_caps, True))
        self.Vase__cut_enabled = bool(to_scalar(self.Vase__cut_enabled, True))

        # 2.5 空列表处理：按你原 Vase 组件逻辑，空/None → None
        if self.Vase__section_diameters is None or _is_empty_list(self.Vase__section_diameters):
            self.Vase__section_diameters = None
        if self.Vase__section_heights is None or _is_empty_list(self.Vase__section_heights):
            self.Vase__section_heights = None
        if self.Vase__bulge_distances is None or _is_empty_list(self.Vase__bulge_distances):
            self.Vase__bulge_distances = None

        # 2.6 生成宝瓶
        vase_gen = VaseGenerator(
            self.vase_base_point,
            self.vase_ref_plane,
            self.Vase__section_diameters,
            self.Vase__section_heights,
            self.Vase__bulge_distances,
            cut_plane_height=self.Vase__cut_plane_height,
            cut_plane_tilt_deg=self.Vase__cut_plane_tilt_deg,
            cut_enabled=self.Vase__cut_enabled
        )

        self.circles, self.rails, self._cut_plane_internal, self.vase = vase_gen.generate(
            close_ends=self.Vase__close_caps
        )

        # ⚠️ 按你原组件要求：不显示裁切面
        self.cut_plane = None

        # 信息
        try:
            self.info = vase_gen.get_info()
        except:
            self.info = None

        # Debug outputs（若 VaseGenerator 内部有这些属性就取出来）
        self.BXPlane_Curves = getattr(vase_gen, "BXPlane_Curves", [])
        self.BXPlane_Points = getattr(vase_gen, "BXPlane_Points", [])
        self.BoundarySurfaces_Surfaces = getattr(vase_gen, "BoundarySurfaces_Surfaces", [])
        self.BoundarySurfaces_CutterBrep = getattr(vase_gen, "BoundarySurfaces_CutterBrep", None)
        self.SplitBrep_Fragments = getattr(vase_gen, "SplitBrep_Fragments", [])
        self.SplitBrep_Areas = getattr(vase_gen, "SplitBrep_Areas", [])
        self.SplitBrep_SortedIndex = getattr(vase_gen, "SplitBrep_SortedIndex", [])
        self.SplitBrep_KeptBrep = getattr(vase_gen, "SplitBrep_KeptBrep", None)
        self.CappedBrep = getattr(vase_gen, "CappedBrep", None)
        self.Cap_Count = getattr(vase_gen, "Cap_Count", 0)
        self.Cap_IsSolid = getattr(vase_gen, "Cap_IsSolid", False)
        self.base_ref_plane = getattr(vase_gen, "ref_plane", None)



        # 最终输出
        self.CutTimbers = self.vase
        self.FailTimbers = []

    # --------------------------------------------------------------
    # Run
    # --------------------------------------------------------------
    def run(self):
        logs = []
        try:
            logs.append("Step1: read db ...")
            self.step1_read_db()
            logs.append("Step1: ok")

            logs.append("Step2: build vase ...")
            self.step2_build_vase()
            logs.append("Step2: ok")

        except Exception as e:
            self.FailTimbers = self.FailTimbers or []
            self.CutTimbers = None
            logs.append("ERROR: {}".format(str(e)))
            logs.append(traceback.format_exc())

        # 汇总日志
        if self.DBLog:
            logs.append("---- DBJsonReader Log ----")
            logs.append(str(self.DBLog))

        self.Log = "\n".join([l for l in logs if l is not None])
        return self.CutTimbers, self.FailTimbers, self.Log


# ======================================================================
# GhPython 组件主调用区（仅 3 输入端：DBPath/base_point/Refresh）
# ======================================================================
if __name__ == "__main__":
    # 读取输入（只允许这三个）
    _DBPath = _get_input("DBPath", None)
    _base_point = _get_input("base_point", None)
    _Refresh = _get_input("Refresh", False)

    solver = VaseA_Solver_4PU(_DBPath, _base_point, _Refresh, ghenv=ghenv)
    CutTimbers, FailTimbers, Log = solver.run()

    # ==================================================================
    # GH Python 组件输出绑定区（developer-friendly）
    # 说明：
    #   - 下面把 solver 的成员变量逐一赋给“同名变量”
    #   - 你在 GH 里新增同名输出端即可直接输出这些调试数据
    #   - 当前 GH 组件固定三输出：CutTimbers / FailTimbers / Log
    # ==================================================================

    # --- Step1 outputs
    Value   = solver.Value
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = solver.DBLog

    # --- Step2 outputs (Vase)
    vase_base_point = solver.vase_base_point
    vase_ref_plane  = solver.vase_ref_plane

    Vase__section_diameters = solver.Vase__section_diameters
    Vase__section_heights   = solver.Vase__section_heights
    Vase__bulge_distances   = solver.Vase__bulge_distances
    Vase__close_caps        = solver.Vase__close_caps
    Vase__cut_plane_height  = solver.Vase__cut_plane_height
    Vase__cut_plane_tilt_deg= solver.Vase__cut_plane_tilt_deg
    Vase__cut_enabled       = solver.Vase__cut_enabled

    base_ref_plane = solver.base_ref_plane

    circles = solver.circles
    rails   = solver.rails
    cut_plane = solver.cut_plane
    _cut_plane_internal = solver._cut_plane_internal
    vase = solver.vase
    info = solver.info

    # --- Debug pipeline outputs
    BXPlane_Curves = solver.BXPlane_Curves
    BXPlane_Points = solver.BXPlane_Points
    BoundarySurfaces_Surfaces = solver.BoundarySurfaces_Surfaces
    BoundarySurfaces_CutterBrep = solver.BoundarySurfaces_CutterBrep
    SplitBrep_Fragments = solver.SplitBrep_Fragments
    SplitBrep_Areas = solver.SplitBrep_Areas
    SplitBrep_SortedIndex = solver.SplitBrep_SortedIndex
    SplitBrep_KeptBrep = solver.SplitBrep_KeptBrep
    CappedBrep = solver.CappedBrep
    Cap_Count = solver.Cap_Count
    Cap_IsSolid = solver.Cap_IsSolid


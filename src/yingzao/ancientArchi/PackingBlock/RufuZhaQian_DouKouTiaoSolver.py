# -*- coding: utf-8 -*-
"""
RufuZhaQian_DouKouTiaoSolver.py

乳栿劄牽_枓口跳 —— 一体化求解器（逐步转换）

步骤说明（当前实现到 Step 9）：
    Step 1: DBJsonReader 读取 CommonComponents 表中 type_code = RufuZhaQian_DouKouTiao 的 params_json
            - ExportAll=True → All（[(name,value), ...]）并转 AllDict（便于后续按键取值）
            - ⚠ 注意：后续步骤若再次读取 DB，应使用 All_2 / AllDict_2 等命名，避免覆盖 All_1 / AllDict_1
    Step 2: FT_timber_block_uniform —— 构造原始木料（主木坯）
            - base_point 优先取 GhPython 输入端 base_point，否则取 DB 中的 base_point（若有），否则原点
            - reference_plane 默认使用 GH 的 XZ Plane（按你给定的 GH 轴向定义）

    Step 3: 两侧切削（FT_BlockCutter::1 + PlaneFromLists::1/2 + GeoAligner::1）
            - FT_BlockCutter::1：按 DB 参数构造“切削块”木坯（base_point=原点，XZ Plane）
            - PlaneFromLists::1：从 Step2 的 EdgeMidPoints / Corner0Planes 取目标平面（支持广播对齐）
            - PlaneFromLists::2：从 Step3/BC1 的 EdgeMidPoints / Corner0Planes 取源平面（Tree/列表/标量皆可）
            - GeoAligner::1：将 BC1 TimberBrep 从 SourcePlane 对齐到 TargetPlane，产物追加到 CutTimbers
    Step 4: 櫨枓和令栱切削（FT_BlockCutter::2 + PlaneFromLists::3/4 + GeoAligner::2）
            - FT_BlockCutter::2：按 DB 参数构造“櫨枓/令栱切削块”木坯（base_point=原点，XZ Plane）
            - PlaneFromLists::3：从 Step2 的 EdgeMidPoints / Corner0Planes 取目标平面（列表/标量皆可）
            - PlaneFromLists::4：从 Step4/BC2 的 EdgeMidPoints / Corner0Planes 取源平面（列表/标量皆可）
            - GeoAligner::2：将 BC2 TimberBrep 从 SourcePlane 对齐到 TargetPlane，产物追加到 CutTimbers



    Step 5: 端头切削（FT_BlockCutter::3 + PlaneFromLists::5/6 + GeoAligner::3）
            - FT_BlockCutter::3：按 DB 参数构造“端头切削块”木坯（base_point=原点，XZ Plane）
            - PlaneFromLists::5：从 Step2 的 PointList / Corner0Planes 取目标平面（支持广播对齐）
            - PlaneFromLists::6：从 Step5/BC3 的 PointList / Corner0Planes 取源平面（支持广播对齐）
            - GeoAligner::3：将 BC3 TimberBrep 从 SourcePlane 对齐到 TargetPlane（Geo 单值、Plane 多值广播），产物追加到 CutTimbers

    Step 6: 端头中间切削（FT_BlockCutter::4 + PlaneFromLists::7/8 + GeoAligner::3）
            - FT_BlockCutter::4：按 DB 参数构造“端头中间切削块”木坯（base_point=原点，XZ Plane）
            - PlaneFromLists::7：从 Step2 的 EdgeMidPoints / Corner0Planes 取目标平面
            - PlaneFromLists::8：从 Step6/BC4 的 EdgeMidPoints / Corner0Planes 取源平面
            - GeoAligner::3：将 BC4 TimberBrep 从 SourcePlane 对齐到 TargetPlane，产物追加到 CutTimbers


Step 7: 乳栿劄牽切削（RuFangKaKouBuilder + PlaneFromLists::9 + GeoAligner::4）
        - RuFangKaKouBuilder：生成 OuterTool/InnerTool 等切削几何
        - PlaneFromLists::9：从 Step2 的 EdgeMidPoints / Corner0Planes 取目标平面
        - GeoAligner::4：将 OuterTool 对位到目标平面，产物追加到 CutTimbers

Step 8: 令栱切削（FT_BlockCutter::5 + PlaneFromLists::10/11 + GeoAligner::5）
        - FT_BlockCutter::5：按 DB 参数构造“令栱切削块”木坯（base_point=原点，XZ Plane）
        - PlaneFromLists::10：从 Step2 的 PointList / Corner0Planes 取目标平面（支持广播对齐）
        - PlaneFromLists::11：从 Step8/BC5 的 PointList / Corner0Planes 取源平面（支持广播对齐）
        - GeoAligner::5：将 BC5 TimberBrep 从 SourcePlane 对齐到 TargetPlane（MoveX/MoveZ 广播），产物追加到 CutTimbers

输入（GhPython）：
    DBPath     : str         - SQLite 数据库路径（Song-styleArchi.db）
    base_point : Point3d     - 木料定位点（输入优先 > DB > 默认）
    Refresh    : bool        - True 强制重读数据库并重算（GH 本身会自动重算，这里保留接口）

输出（GhPython）：
    CutTimbers  : object/list   - 最终几何（当前 Step2 先输出 [TimberBrep] 作为 CutTimbers）
    FailTimbers : list          - 失败几何列表（当前为空）
    Log         : list[str]     - 日志

并在文末“GH PYTHON 组件输出绑定区”中，暴露当前已实现步骤的全部 Solver 成员变量，便于后续增减输出端。
"""

import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    FT_GeoAligner,
    RuFangKaKouBuilder,
    JuanShaToolBuilder,
    FT_CutTimberByTools,
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2025.12.31"


# ======================================================================
# 通用工具函数
# ======================================================================
def _is_seq(x):
    return isinstance(x, (list, tuple))


def _deep_flatten(x):
    """
    递归拍平 list/tuple（并尽量兼容 GH 输出中常见的 .NET List 嵌套）。
    用于避免输出端出现：
        System.Collections.Generic.List`1[System.Object] ...
    """
    if x is None:
        return []
    # Rhino/GH 常见几何与基础类型：不当作可迭代容器展开
    if isinstance(x, (str, rg.GeometryBase, rg.Plane, rg.Point3d, rg.Vector3d, rg.Line, rg.Transform)):
        return [x]

    # .NET IEnumerable / GH DataTree 分支在 python 里也常可迭代
    try:
        # 先判断是否像序列一样可迭代
        iter(x)
    except Exception:
        return [x]

    # 对 list/tuple 或可迭代对象递归展开
    out = []
    try:
        for it in x:
            if _is_seq(it):
                out.extend(_deep_flatten(it))
            else:
                # 对 .NET List / IEnumerable 再试一次递归
                try:
                    if not isinstance(it, (str, rg.GeometryBase, rg.Plane, rg.Point3d, rg.Vector3d, rg.Line,
                                           rg.Transform)) and hasattr(it, "__iter__"):
                        out.extend(_deep_flatten(list(it)))
                    else:
                        out.append(it)
                except Exception:
                    out.append(it)
        return out
    except Exception:
        return [x]


def _to_point3d(pt, default=None):
    """把输入尽量归一为 rg.Point3d。"""
    if default is None:
        default = rg.Point3d(0.0, 0.0, 0.0)

    if pt is None:
        return default
    if isinstance(pt, rg.Point3d):
        return pt
    if isinstance(pt, rg.Point):
        return pt.Location
    # 允许 (x,y,z)
    if isinstance(pt, (list, tuple)) and len(pt) >= 3:
        try:
            return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
        except Exception:
            return default
    return default


def _gh_xz_plane(origin=None):
    """
    GH 的 XZ Plane（按你给定的轴向定义）：
        X = (1,0,0)
        Y = (0,0,1)
        Z = (0,-1,0)  （由 X × Y 得到）
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, xaxis, yaxis)


def _get_from_alldict(AllDict, key, default=None):
    if not AllDict:
        return default
    return AllDict.get(key, default)


def _is_gh_datatree(x):
    """宽松判断是否为 Grasshopper DataTree。"""
    if x is None:
        return False
    # GH DataTree 常见特征：BranchCount / Branch / Path
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


def _tree_to_single_values(x):
    """把 DataTree 每个分支的第一个值取出来，返回 python list。"""
    if not _is_gh_datatree(x):
        return None
    vals = []
    try:
        bc = int(x.BranchCount)
        for i in range(bc):
            br = x.Branch(i)
            if br is None or len(br) == 0:
                vals.append(None)
            else:
                vals.append(br[0])
    except Exception:
        return None
    return vals


def _as_list_or_none(x):
    """把标量/序列/DataTree 归一成 list；None 返回 None。"""
    if x is None:
        return None
    if _is_gh_datatree(x):
        return _tree_to_single_values(x)
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _first_or_self(x):
    if isinstance(x, (list, tuple)) and len(x) > 0:
        return x[0]
    return x


def _as_number(x, default=0.0):
    """把可能为 list/tuple/DataTree 的值转成 float。"""
    try:
        x = _as_list_or_none(x)
        if isinstance(x, list):
            x = x[0] if len(x) > 0 else None
    except Exception:
        pass
    x = _first_or_self(x)
    if x is None:
        return float(default)
    try:
        return float(x)
    except Exception:
        return float(default)


def _as_bool(x, default=False):
    """把可能为 list/tuple/DataTree 的值转成 bool。"""
    try:
        x = _as_list_or_none(x)
        if isinstance(x, list):
            x = x[0] if len(x) > 0 else None
    except Exception:
        pass
    x = _first_or_self(x)
    if x is None:
        return bool(default)
    return bool(x)


def _broadcast_pair(a_list, b_list):
    """广播对齐：任一长度为 1 时，扩展到另一长度；否则按最大长度循环取值。"""
    if a_list is None:
        a_list = [None]
    if b_list is None:
        b_list = [None]
    la, lb = len(a_list), len(b_list)
    n = max(la, lb)
    if la == 0:
        a_list = [None]
        la = 1
    if lb == 0:
        b_list = [None]
        lb = 1
    out_a, out_b = [], []
    for i in range(n):
        out_a.append(a_list[i % la] if la > 1 else a_list[0])
        out_b.append(b_list[i % lb] if lb > 1 else b_list[0])
    return out_a, out_b


def _broadcast_get(val, i, n):
    """val 可以是标量 / list / DataTree，按长度 n 广播后取第 i 个。"""
    lst = _as_list_or_none(val)
    if lst is None:
        lst = [val]
    if len(lst) == 0:
        return None
    if len(lst) == 1:
        return lst[0]
    return lst[i % len(lst)]


def _broadcast_len(*vals):
    """从若干可能为标量/序列/DataTree 的输入里，推断需要循环的次数 n（至少为 1）。"""
    n = 1
    for v in vals:
        lst = _as_list_or_none(v)
        if isinstance(lst, list) and len(lst) > n:
            n = len(lst)
    return n


# ======================================================================
# Solver 主类
# ======================================================================
class RufuZhaQian_DouKouTiaoSolver(object):
    """
    数据库驱动 + 多 ghpy 串联 → 单 ghpy Solver
    """

    def __init__(self, DBPath, base_point, Refresh, ghenv, FT_timber_block_uniform_length_fen=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # 可选输入端覆盖（GH 输入端若存在且有值，则优先于 DB）
        self.FT_timber_block_uniform_length_fen_override = FT_timber_block_uniform_length_fen

        # ============ 全局日志 ============
        self.Log = []

        # ============ 最终对外输出（按要求） ============
        self.CutTimbers = None
        self.FailTimbers = []

        # ============ Step 1 ============
        self.Value_1 = None
        self.All_1 = None  # [(name, value), ...]
        self.AllDict_1 = None  # {name: value, ...}

        # ============ Step 2：主木坯（FT_timber_block_uniform 对齐命名） ============
        self.TimberBrep = None
        self.FaceList = []
        self.PointList = []
        self.EdgeList = []
        self.CenterPoint = None
        self.CenterAxisLines = []
        self.EdgeMidPoints = []
        self.FacePlaneList = []
        self.Corner0Planes = []
        self.LocalAxesPlane = None
        self.AxisX = None
        self.AxisY = None
        self.AxisZ = None
        self.FaceDirTags = []
        self.EdgeDirTags = []
        self.Corner0EdgeDirs = []

        # ============ Step 3：两侧切削（FT_BlockCutter::1 + PlaneFromLists::1/2 + GeoAligner::1） ============
        # --- FT_BlockCutter::1（其内部仍是 build_timber_block_uniform） ---
        self.BC1_TimberBrep = None
        self.BC1_FaceList = []
        self.BC1_PointList = []
        self.BC1_EdgeList = []
        self.BC1_CenterPoint = None
        self.BC1_CenterAxisLines = []
        self.BC1_EdgeMidPoints = []
        self.BC1_FacePlaneList = []
        self.BC1_Corner0Planes = []
        self.BC1_LocalAxesPlane = None
        self.BC1_AxisX = None
        self.BC1_AxisY = None
        self.BC1_AxisZ = None
        self.BC1_FaceDirTags = []
        self.BC1_EdgeDirTags = []
        self.BC1_Corner0EdgeDirs = []

        # --- PlaneFromLists::1（目标平面） ---
        self.PFL1_BasePlane = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlane = None
        self.PFL1_Log = []

        # --- PlaneFromLists::2（源平面，Tree 模式） ---
        self.PFL2_BasePlane = None
        self.PFL2_OriginPoint = None
        self.PFL2_ResultPlane = None
        self.PFL2_Log = []

        # --- GeoAligner::1 ---
        self.GA1_SourceOut = []
        self.GA1_TargetOut = []
        self.GA1_MovedGeo = []
        # ============ Step 4：櫨枓和令栱切削（FT_BlockCutter::2 + PlaneFromLists::3/4 + GeoAligner::2） ============
        # --- FT_BlockCutter::2（其内部仍是 build_timber_block_uniform） ---
        self.BC2_TimberBrep = None
        self.BC2_FaceList = []
        self.BC2_PointList = []
        self.BC2_EdgeList = []
        self.BC2_CenterPoint = None
        self.BC2_CenterAxisLines = []
        self.BC2_EdgeMidPoints = []
        self.BC2_FacePlaneList = []
        self.BC2_Corner0Planes = []
        self.BC2_LocalAxesPlane = None
        self.BC2_AxisX = None
        self.BC2_AxisY = None
        self.BC2_AxisZ = None
        self.BC2_FaceDirTags = []
        self.BC2_EdgeDirTags = []
        self.BC2_Corner0EdgeDirs = []

        # --- PlaneFromLists::3（目标平面） ---
        self.PFL3_BasePlane = None
        self.PFL3_OriginPoint = None
        self.PFL3_ResultPlane = None
        self.PFL3_Log = []

        # --- PlaneFromLists::4（源平面） ---
        self.PFL4_BasePlane = None
        self.PFL4_OriginPoint = None
        self.PFL4_ResultPlane = None
        self.PFL4_Log = []

        # --- GeoAligner::2 ---
        self.GA2_SourceOut = []
        self.GA2_TargetOut = []
        self.GA2_MovedGeo = []

        # ============ Step 5：端头切削（FT_BlockCutter::3 + PlaneFromLists::5/6 + GeoAligner::3） ============
        # --- FT_BlockCutter::3 ---
        self.BC3_TimberBrep = None
        self.BC3_FaceList = []
        self.BC3_PointList = []
        self.BC3_EdgeList = []
        self.BC3_CenterPoint = None
        self.BC3_CenterAxisLines = []
        self.BC3_EdgeMidPoints = []
        self.BC3_FacePlaneList = []
        self.BC3_Corner0Planes = []
        self.BC3_LocalAxesPlane = None
        self.BC3_AxisX = None
        self.BC3_AxisY = None
        self.BC3_AxisZ = None
        self.BC3_FaceDirTags = []
        self.BC3_EdgeDirTags = []
        self.BC3_Corner0EdgeDirs = []

        # --- PlaneFromLists::5（目标平面，来自 Step2 PointList） ---
        self.PFL5_BasePlane = None
        self.PFL5_OriginPoint = None
        self.PFL5_ResultPlane = None
        self.PFL5_Log = []

        # --- PlaneFromLists::6（源平面，来自 BC3 PointList） ---
        self.PFL6_BasePlane = None
        self.PFL6_OriginPoint = None
        self.PFL6_ResultPlane = None
        self.PFL6_Log = []

        # --- GeoAligner::3 ---
        self.GA3_SourceOut = []
        self.GA3_TargetOut = []
        self.GA3_MovedGeo = []

        # ============ Step 6：端头中间切削（FT_BlockCutter::4 + PlaneFromLists::7/8 + GeoAligner::3） ============
        # --- FT_BlockCutter::4 ---
        self.BC4_TimberBrep = None
        self.BC4_FaceList = []
        self.BC4_PointList = []
        self.BC4_EdgeList = []
        self.BC4_CenterPoint = None
        self.BC4_CenterAxisLines = []
        self.BC4_EdgeMidPoints = []
        self.BC4_FacePlaneList = []
        self.BC4_Corner0Planes = []
        self.BC4_LocalAxesPlane = None
        self.BC4_AxisX = None
        self.BC4_AxisY = None
        self.BC4_AxisZ = None
        self.BC4_FaceDirTags = []
        self.BC4_EdgeDirTags = []
        self.BC4_Corner0EdgeDirs = []

        # --- PlaneFromLists::7（目标平面，来自 Step2 EdgeMidPoints） ---
        self.PFL7_BasePlane = None
        self.PFL7_OriginPoint = None
        self.PFL7_ResultPlane = None
        self.PFL7_Log = []

        # --- PlaneFromLists::8（源平面，来自 BC4 EdgeMidPoints） ---
        self.PFL8_BasePlane = None
        self.PFL8_OriginPoint = None
        self.PFL8_ResultPlane = None
        self.PFL8_Log = []

        # --- GeoAligner::(Step6) ---
        # 注意：Step5 已使用 GA3_*；此处避免覆盖，内部采用 GA4_* 保存
        self.GA4_SourceOut = []
        self.GA4_TargetOut = []
        self.GA4_MovedGeo = []

        # ============ Step 7：乳栿劄牽切削（RuFangKaKouBuilder + PlaneFromLists::9 + GeoAligner::4） ============
        self.RFKK_OuterTool = None
        self.RFKK_InnerTool = None
        self.RFKK_OuterSection = None
        self.RFKK_InnerSection = None
        self.RFKK_RefPlanes = []
        self.RFKK_EdgeMidPoints = []
        self.RFKK_EdgeNames = []
        self.RFKK_KeyPoints = []
        self.RFKK_KeyPointNames = []
        self.RFKK_EdgeCurves = []
        self.RFKK_Log = []
        self.RFKK_RefPlaneNames = []

        # --- PlaneFromLists::9（目标平面，来自 Step2 EdgeMidPoints / Corner0Planes） ---
        self.PFL9_BasePlane = None
        self.PFL9_OriginPoint = None
        self.PFL9_ResultPlane = None
        self.PFL9_Log = []

        # --- GeoAligner::4（对位 OuterTool） ---
        self.GA5_SourceOut = []
        self.GA5_TargetOut = []
        self.GA5_MovedGeo = []

        # ============ Step 8：令栱切削（FT_BlockCutter::5 + PlaneFromLists::10/11 + GeoAligner::5） ============
        # --- FT_BlockCutter::5 ---
        self.BC5_TimberBrep = None
        self.BC5_FaceList = []
        self.BC5_PointList = []
        self.BC5_EdgeList = []
        self.BC5_CenterPoint = None
        self.BC5_CenterAxisLines = []
        self.BC5_EdgeMidPoints = []
        self.BC5_FacePlaneList = []
        self.BC5_Corner0Planes = []
        self.BC5_LocalAxesPlane = None
        self.BC5_AxisX = None
        self.BC5_AxisY = None
        self.BC5_AxisZ = None
        self.BC5_FaceDirTags = []
        self.BC5_EdgeDirTags = []
        self.BC5_Corner0EdgeDirs = []

        # --- PlaneFromLists::10（目标平面，来自 Step2 PointList / Corner0Planes） ---
        self.PFL10_BasePlane = None
        self.PFL10_OriginPoint = None
        self.PFL10_ResultPlane = None
        self.PFL10_Log = []

        # --- PlaneFromLists::11（源平面，来自 BC5 PointList / Corner0Planes） ---
        self.PFL11_BasePlane = None
        self.PFL11_OriginPoint = None
        self.PFL11_ResultPlane = None
        self.PFL11_Log = []

        # --- GeoAligner::5 ---
        # 注意：Step7 已使用 GA5_*；此处避免覆盖，内部采用 GA6_* 保存
        self.GA6_SourceOut = []
        self.GA6_TargetOut = []
        self.GA6_MovedGeo = []
        # ============ Step 9：卷殺和刀具合并裁切（JuanShaToolBuilder + PlaneFromLists::12 + GeoAligner::6 + FT_CutTimberByTools） ============
        # --- JuanShaToolBuilder ---
        self.JS_ToolBrep = None
        self.JS_SectionEdges = []
        self.JS_HL_Intersection = None
        self.JS_HeightFacePlane = None
        self.JS_LengthFacePlane = None
        self.JS_Log = []

        # --- PlaneFromLists::12（目标平面，来自 Step2 EdgeMidPoints / Corner0Planes） ---
        self.PFL12_BasePlane = None
        self.PFL12_OriginPoint = None
        self.PFL12_ResultPlane = None
        self.PFL12_Log = []

        # --- GeoAligner::6（对位 JuanShaTool） ---
        # 注意：Step8 已使用 GA6_*；此处避免覆盖，内部采用 GA7_* 保存
        self.GA7_SourceOut = []
        self.GA7_TargetOut = []
        self.GA7_MovedGeo = []

        # --- Step9 最终裁切结果（FT_CutTimberByTools） ---
        self.FinalCutTimbers = None
        self.FinalFailTimbers = []
        self.FinalCutLog = []

        # 预留：后续步骤逐步补齐（避免你后面加输出端时改结构）
        self._reserved_steps = ["step3", "step4", "step5", "step6", "step7", "step8", "step9"]

    # ------------------------------------------------------------------
    # Step 3：两侧切削（按你给定的组件串）
    # ------------------------------------------------------------------
    def step3_side_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 3.1 FT_BlockCutter::1
        # ---------------------------
        bc_len = _get_from_alldict(AllDict, "FT_BlockCutter_1__length_fen", None)
        bc_wid = _get_from_alldict(AllDict, "FT_BlockCutter_1__width_fen", None)
        bc_hei = _get_from_alldict(AllDict, "FT_BlockCutter_1__height_fen", None)
        if bc_len is None:
            bc_len = 32.0
        if bc_wid is None:
            bc_wid = 32.0
        if bc_hei is None:
            bc_hei = 20.0

        bc_bp = rg.Point3d(0.0, 0.0, 0.0)  # base_point 默认为原点
        bc_plane = _gh_xz_plane(origin=bc_bp)  # reference_plane 为 GH 的 XZ Plane

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(bc_len),
                float(bc_wid),
                float(bc_hei),
                bc_bp,
                bc_plane,
            )

            self.BC1_TimberBrep = timber_brep
            self.BC1_FaceList = faces or []
            self.BC1_PointList = points or []
            self.BC1_EdgeList = edges or []
            self.BC1_CenterPoint = center_pt
            self.BC1_CenterAxisLines = center_axes or []
            self.BC1_EdgeMidPoints = edge_midpts or []
            self.BC1_FacePlaneList = face_planes or []
            self.BC1_Corner0Planes = corner0_planes or []
            self.BC1_LocalAxesPlane = local_axes_plane
            self.BC1_AxisX = axis_x
            self.BC1_AxisY = axis_y
            self.BC1_AxisZ = axis_z
            self.BC1_FaceDirTags = face_tags or []
            self.BC1_EdgeDirTags = edge_tags or []
            self.BC1_Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step3/BC1] " + str(l))

        except Exception as e:
            self.BC1_TimberBrep = None
            self.BC1_FaceList = []
            self.BC1_PointList = []
            self.BC1_EdgeList = []
            self.BC1_CenterPoint = None
            self.BC1_CenterAxisLines = []
            self.BC1_EdgeMidPoints = []
            self.BC1_FacePlaneList = []
            self.BC1_Corner0Planes = []
            self.BC1_LocalAxesPlane = None
            self.BC1_AxisX = None
            self.BC1_AxisY = None
            self.BC1_AxisZ = None
            self.BC1_FaceDirTags = []
            self.BC1_EdgeDirTags = []
            self.BC1_Corner0EdgeDirs = []
            self.Log.append("[Step3/BC1] 构建 FT_BlockCutter::1 失败: {}".format(e))
            return

        # ---------------------------
        # 3.2 PlaneFromLists::1（目标平面）
        #   OriginPoints = Step2 EdgeMidPoints
        #   BasePlanes   = Step2 Corner0Planes
        #   IndexOrigin  = PlaneFromLists_1__IndexOrigin
        #   IndexPlane   = PlaneFromLists_1__IndexPlane
        #   广播对齐
        # ---------------------------
        try:
            idx_o_1 = _get_from_alldict(AllDict, "PlaneFromLists_1__IndexOrigin", None)
            idx_p_1 = _get_from_alldict(AllDict, "PlaneFromLists_1__IndexPlane", None)
            wrap_1 = _get_from_alldict(AllDict, "PlaneFromLists_1__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_1)
            idx_p_list = _as_list_or_none(idx_p_1)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl1 = FTPlaneFromLists(wrap=bool(wrap_1))
            # 逐个求值，输出保持 list（便于你后面加输出端）
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl1.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL1_BasePlane = bp_out
            self.PFL1_OriginPoint = op_out
            self.PFL1_ResultPlane = rp_out
            self.PFL1_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step3/PFL1] " + str(l))

        except Exception as e:
            self.PFL1_BasePlane = None
            self.PFL1_OriginPoint = None
            self.PFL1_ResultPlane = None
            self.PFL1_Log = ["错误: {}".format(e)]
            self.Log.append("[Step3/PFL1] PlaneFromLists::1 失败: {}".format(e))
            return

        # ---------------------------
        # 3.3 PlaneFromLists::2（源平面，Tree 模式）
        #   OriginPoints = BC1 EdgeMidPoints
        #   BasePlanes   = BC1 Corner0Planes
        #   IndexOrigin  = PlaneFromLists_2__IndexOrigin（Tree：每分支一个值）
        #   IndexPlane   = PlaneFromLists_2__IndexPlane（Tree：每分支一个值）
        # ---------------------------
        try:
            idx_o_2 = _get_from_alldict(AllDict, "PlaneFromLists_2__IndexOrigin", None)
            idx_p_2 = _get_from_alldict(AllDict, "PlaneFromLists_2__IndexPlane", None)
            wrap_2 = _get_from_alldict(AllDict, "PlaneFromLists_2__Wrap", True)

            # Tree → 每分支单值 list；若不是 Tree，也按 list/标量处理
            idx_o2_list = _as_list_or_none(idx_o_2)
            idx_p2_list = _as_list_or_none(idx_p_2)
            idx_o2_list, idx_p2_list = _broadcast_pair(idx_o2_list, idx_p2_list)

            pfl2 = FTPlaneFromLists(wrap=bool(wrap_2))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o2_list, idx_p2_list):
                bp, op, rp, lg = pfl2.build_plane(
                    self.BC1_EdgeMidPoints,
                    self.BC1_Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL2_BasePlane = bp_out
            self.PFL2_OriginPoint = op_out
            self.PFL2_ResultPlane = rp_out
            self.PFL2_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step3/PFL2] " + str(l))

        except Exception as e:
            self.PFL2_BasePlane = None
            self.PFL2_OriginPoint = None
            self.PFL2_ResultPlane = None
            self.PFL2_Log = ["错误: {}".format(e)]
            self.Log.append("[Step3/PFL2] PlaneFromLists::2 失败: {}".format(e))
            return

        # ---------------------------
        # 3.4 GeoAligner::1
        #   Geo         = BC1 TimberBrep
        #   SourcePlane = PFL2 ResultPlane
        #   TargetPlane = PFL1 ResultPlane
        # ---------------------------
        try:
            rot_deg = _get_from_alldict(AllDict, "GeoAligner_1__RotateDeg", 0.0)
            # 你给的说明里 FlipY = GeoAligner_1__TargetPlane（按原话读取）
            flip_y = _get_from_alldict(AllDict, "GeoAligner_1__TargetPlane", False)
            flip_x = _get_from_alldict(AllDict, "GeoAligner_1__FlipX", False)
            flip_z = _get_from_alldict(AllDict, "GeoAligner_1__FlipZ", False)
            mv_x = _get_from_alldict(AllDict, "GeoAligner_1__MoveX", 0.0)
            mv_y = _get_from_alldict(AllDict, "GeoAligner_1__MoveY", 0.0)
            mv_z = _get_from_alldict(AllDict, "GeoAligner_1__MoveZ", 0.0)

            # SourcePlane / TargetPlane：应保留为 list（两侧各一组），逐对执行对齐
            sp_list = self.PFL2_ResultPlane if isinstance(self.PFL2_ResultPlane, list) else (
                [self.PFL2_ResultPlane] if self.PFL2_ResultPlane is not None else [])
            tp_list = self.PFL1_ResultPlane if isinstance(self.PFL1_ResultPlane, list) else (
                [self.PFL1_ResultPlane] if self.PFL1_ResultPlane is not None else [])

            # 广播对齐 SourcePlane/TargetPlane
            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)

            self.GA1_SourceOut = []
            self.GA1_TargetOut = []
            self.GA1_MovedGeo = []

            for i in range(n):
                sp = sp_list[i] if sp_list else None
                tp = tp_list[i] if tp_list else None

                # 数值/布尔参数也允许是 list / DataTree（与 planes 同步广播）
                rdeg = _as_number(_broadcast_get(rot_deg, i, n), 0.0)
                fx = _as_bool(_broadcast_get(flip_x, i, n), False)
                fy = _as_bool(_broadcast_get(flip_y, i, n), False)
                fz = _as_bool(_broadcast_get(flip_z, i, n), False)
                mx = _as_number(_broadcast_get(mv_x, i, n), 0.0)
                my = _as_number(_broadcast_get(mv_y, i, n), 0.0)
                mz = _as_number(_broadcast_get(mv_z, i, n), 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.BC1_TimberBrep,
                    sp,
                    tp,
                    rotate_deg=rdeg,
                    flip_x=fx,
                    flip_y=fy,
                    flip_z=fz,
                    move_x=mx,
                    move_y=my,
                    move_z=mz,
                )

                self.GA1_SourceOut.append(so)
                self.GA1_TargetOut.append(to)
                self.GA1_MovedGeo.append(mg)

            # Step3 的产物：追加到 CutTimbers（不破坏 Step2 的占位输出）
            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA1_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA1_SourceOut = []
            self.GA1_TargetOut = []
            self.GA1_MovedGeo = []
            self.Log.append("[Step3/GA1] GeoAligner::1 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 4：櫨枓和令栱切削（按你给定的组件串）
    # ------------------------------------------------------------------
    def step4_ludou_linggong_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 4.1 FT_BlockCutter::2
        # ---------------------------
        bc_len = _get_from_alldict(AllDict, "FT_BlockCutter_2__length_fen", None)
        bc_wid = _get_from_alldict(AllDict, "FT_BlockCutter_2__width_fen", None)
        bc_hei = _get_from_alldict(AllDict, "FT_BlockCutter_2__height_fen", None)
        if bc_len is None:
            bc_len = 32.0
        if bc_wid is None:
            bc_wid = 32.0
        if bc_hei is None:
            bc_hei = 20.0

        bc_bp = rg.Point3d(0.0, 0.0, 0.0)  # base_point 默认为原点
        bc_plane = _gh_xz_plane(origin=bc_bp)  # reference_plane 默认为 GH 的 XZ Plane

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(bc_len),
                float(bc_wid),
                float(bc_hei),
                bc_bp,
                bc_plane,
            )

            self.BC2_TimberBrep = timber_brep
            self.BC2_FaceList = faces or []
            self.BC2_PointList = points or []
            self.BC2_EdgeList = edges or []
            self.BC2_CenterPoint = center_pt
            self.BC2_CenterAxisLines = center_axes or []
            self.BC2_EdgeMidPoints = edge_midpts or []
            self.BC2_FacePlaneList = face_planes or []
            self.BC2_Corner0Planes = corner0_planes or []
            self.BC2_LocalAxesPlane = local_axes_plane
            self.BC2_AxisX = axis_x
            self.BC2_AxisY = axis_y
            self.BC2_AxisZ = axis_z
            self.BC2_FaceDirTags = face_tags or []
            self.BC2_EdgeDirTags = edge_tags or []
            self.BC2_Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step4/BC2] " + str(l))

        except Exception as e:
            self.BC2_TimberBrep = None
            self.BC2_FaceList = []
            self.BC2_PointList = []
            self.BC2_EdgeList = []
            self.BC2_CenterPoint = None
            self.BC2_CenterAxisLines = []
            self.BC2_EdgeMidPoints = []
            self.BC2_FacePlaneList = []
            self.BC2_Corner0Planes = []
            self.BC2_LocalAxesPlane = None
            self.BC2_AxisX = None
            self.BC2_AxisY = None
            self.BC2_AxisZ = None
            self.BC2_FaceDirTags = []
            self.BC2_EdgeDirTags = []
            self.BC2_Corner0EdgeDirs = []
            self.Log.append("[Step4/BC2] 构建 FT_BlockCutter::2 失败: {}".format(e))
            return

        # ---------------------------
        # 4.2 PlaneFromLists::3（目标平面）
        #   OriginPoints = Step2 EdgeMidPoints
        #   BasePlanes   = Step2 Corner0Planes
        # ---------------------------
        try:
            idx_o_3 = _get_from_alldict(AllDict, "PlaneFromLists_3__IndexOrigin", None)
            idx_p_3 = _get_from_alldict(AllDict, "PlaneFromLists_3__IndexPlane", None)
            wrap_3 = _get_from_alldict(AllDict, "PlaneFromLists_3__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_3)
            idx_p_list = _as_list_or_none(idx_p_3)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl3 = FTPlaneFromLists(wrap=bool(wrap_3))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl3.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL3_BasePlane = bp_out
            self.PFL3_OriginPoint = op_out
            self.PFL3_ResultPlane = rp_out
            self.PFL3_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step4/PFL3] " + str(l))

        except Exception as e:
            self.PFL3_BasePlane = None
            self.PFL3_OriginPoint = None
            self.PFL3_ResultPlane = None
            self.PFL3_Log = ["错误: {}".format(e)]
            self.Log.append("[Step4/PFL3] PlaneFromLists::3 失败: {}".format(e))
            return

        # ---------------------------
        # 4.3 PlaneFromLists::4（源平面）
        #   OriginPoints = BC2 EdgeMidPoints
        #   BasePlanes   = BC2 Corner0Planes
        # ---------------------------
        try:
            idx_o_4 = _get_from_alldict(AllDict, "PlaneFromLists_4__IndexOrigin", None)
            idx_p_4 = _get_from_alldict(AllDict, "PlaneFromLists_4__IndexPlane", None)
            wrap_4 = _get_from_alldict(AllDict, "PlaneFromLists_4__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_4)
            idx_p_list = _as_list_or_none(idx_p_4)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl4 = FTPlaneFromLists(wrap=bool(wrap_4))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl4.build_plane(
                    self.BC2_EdgeMidPoints,
                    self.BC2_Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL4_BasePlane = bp_out
            self.PFL4_OriginPoint = op_out
            self.PFL4_ResultPlane = rp_out
            self.PFL4_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step4/PFL4] " + str(l))

        except Exception as e:
            self.PFL4_BasePlane = None
            self.PFL4_OriginPoint = None
            self.PFL4_ResultPlane = None
            self.PFL4_Log = ["错误: {}".format(e)]
            self.Log.append("[Step4/PFL4] PlaneFromLists::4 失败: {}".format(e))
            return

        # ---------------------------
        # 4.4 GeoAligner::2
        #   Geo         = BC2 TimberBrep
        #   SourcePlane = PFL4 ResultPlane
        #   TargetPlane = PFL3 ResultPlane
        #   ⚠ 你的说明：MoveZ 为 GeoAligner_2__MoveX（按原话映射）
        # ---------------------------
        try:
            rot_deg = _get_from_alldict(AllDict, "GeoAligner_2__RotateDeg", 0.0)
            flip_x = _get_from_alldict(AllDict, "GeoAligner_2__FlipX", False)
            flip_y = _get_from_alldict(AllDict, "GeoAligner_2__FlipY", False)
            flip_z = _get_from_alldict(AllDict, "GeoAligner_2__FlipZ", False)

            # -------------------------------------------------
            # 根源修复：
            # 你在 Step4 的定义是「MoveZ = GeoAligner_2__MoveX」。
            # 因此 GeoAligner::2 的 MoveX 本身并没有独立数据源，
            # 不应把 GeoAligner_2__MoveX 同时当作 move_x 传入。
            # 否则就会出现你遇到的“MoveX 为空却带入 -30”等问题。
            #
            # 规则：
            # - 只读取 GeoAligner_2__MoveY 作为 move_y（若有）
            # - 读取 GeoAligner_2__MoveX 作为 move_z（若有）
            # - move_x 永远不从 DB 取值：无值则不传 / 默认由 align 内部处理
            # -------------------------------------------------
            mv_y = _get_from_alldict(AllDict, "GeoAligner_2__MoveY", None)
            mv_z_mapped_from_x = _get_from_alldict(AllDict, "GeoAligner_2__MoveX", None)

            sp_list = self.PFL4_ResultPlane if isinstance(self.PFL4_ResultPlane, list) else (
                [self.PFL4_ResultPlane] if self.PFL4_ResultPlane is not None else [])
            tp_list = self.PFL3_ResultPlane if isinstance(self.PFL3_ResultPlane, list) else (
                [self.PFL3_ResultPlane] if self.PFL3_ResultPlane is not None else [])

            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)

            self.GA2_SourceOut = []
            self.GA2_TargetOut = []
            self.GA2_MovedGeo = []

            for i in range(n):
                sp = sp_list[i] if sp_list else None
                tp = tp_list[i] if tp_list else None

                rdeg = _as_number(_broadcast_get(rot_deg, i, n), 0.0)
                fx = _as_bool(_broadcast_get(flip_x, i, n), False)
                fy = _as_bool(_broadcast_get(flip_y, i, n), False)
                fz = _as_bool(_broadcast_get(flip_z, i, n), False)
                # move_x：没有数据源 → 不传入（保持 None 语义）
                my_raw = _broadcast_get(mv_y, i, n)
                mz_raw = _broadcast_get(mv_z_mapped_from_x, i, n)

                # 只有在 DB 确实给了值时才传入；无值则完全不传，让 align 使用默认
                kwargs = {
                    "rotate_deg": rdeg,
                    "flip_x": fx,
                    "flip_y": fy,
                    "flip_z": fz,
                }
                if my_raw is not None:
                    kwargs["move_y"] = _as_number(my_raw, 0.0)
                if mz_raw is not None:
                    kwargs["move_z"] = _as_number(mz_raw, 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.BC2_TimberBrep,
                    sp,
                    tp,
                    **kwargs
                )

                self.GA2_SourceOut.append(so)
                self.GA2_TargetOut.append(to)
                self.GA2_MovedGeo.append(mg)

            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA2_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA2_SourceOut = []
            self.GA2_TargetOut = []
            self.GA2_MovedGeo = []
            self.Log.append("[Step4/GA2] GeoAligner::2 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Step 5：端头切削（按你给定的组件串）
    # ------------------------------------------------------------------
    def step5_end_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 5.1 FT_BlockCutter::3
        # ---------------------------
        bc_len = _get_from_alldict(AllDict, "FT_BlockCutter_3__length_fen", None)
        bc_wid = _get_from_alldict(AllDict, "FT_BlockCutter_3__width_fen", None)
        bc_hei = _get_from_alldict(AllDict, "FT_BlockCutter_3__height_fen", None)
        if bc_len is None:
            bc_len = 32.0
        if bc_wid is None:
            bc_wid = 32.0
        if bc_hei is None:
            bc_hei = 20.0

        bc_bp = rg.Point3d(0.0, 0.0, 0.0)
        bc_plane = _gh_xz_plane(origin=bc_bp)

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(bc_len),
                float(bc_wid),
                float(bc_hei),
                bc_bp,
                bc_plane,
            )

            self.BC3_TimberBrep = timber_brep
            self.BC3_FaceList = faces or []
            self.BC3_PointList = points or []
            self.BC3_EdgeList = edges or []
            self.BC3_CenterPoint = center_pt
            self.BC3_CenterAxisLines = center_axes or []
            self.BC3_EdgeMidPoints = edge_midpts or []
            self.BC3_FacePlaneList = face_planes or []
            self.BC3_Corner0Planes = corner0_planes or []
            self.BC3_LocalAxesPlane = local_axes_plane
            self.BC3_AxisX = axis_x
            self.BC3_AxisY = axis_y
            self.BC3_AxisZ = axis_z
            self.BC3_FaceDirTags = face_tags or []
            self.BC3_EdgeDirTags = edge_tags or []
            self.BC3_Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step5/BC3] " + str(l))

        except Exception as e:
            self.BC3_TimberBrep = None
            self.BC3_FaceList = []
            self.BC3_PointList = []
            self.BC3_EdgeList = []
            self.BC3_CenterPoint = None
            self.BC3_CenterAxisLines = []
            self.BC3_EdgeMidPoints = []
            self.BC3_FacePlaneList = []
            self.BC3_Corner0Planes = []
            self.BC3_LocalAxesPlane = None
            self.BC3_AxisX = None
            self.BC3_AxisY = None
            self.BC3_AxisZ = None
            self.BC3_FaceDirTags = []
            self.BC3_EdgeDirTags = []
            self.BC3_Corner0EdgeDirs = []
            self.Log.append("[Step5/BC3] 构建 FT_BlockCutter::3 失败: {}".format(e))
            return

        # ---------------------------
        # 5.2 PlaneFromLists::5（目标平面）
        #   OriginPoints = Step2 PointList
        #   BasePlanes   = Step2 Corner0Planes
        #   支持广播对齐
        # ---------------------------
        try:
            idx_o_5 = _get_from_alldict(AllDict, "PlaneFromLists_5__IndexOrigin", None)
            idx_p_5 = _get_from_alldict(AllDict, "PlaneFromLists_5__IndexPlane", None)
            wrap_5 = _get_from_alldict(AllDict, "PlaneFromLists_5__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_5)
            idx_p_list = _as_list_or_none(idx_p_5)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl5 = FTPlaneFromLists(wrap=bool(wrap_5))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl5.build_plane(
                    self.PointList,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL5_BasePlane = bp_out
            self.PFL5_OriginPoint = op_out
            self.PFL5_ResultPlane = rp_out
            self.PFL5_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step5/PFL5] " + str(l))

        except Exception as e:
            self.PFL5_BasePlane = None
            self.PFL5_OriginPoint = None
            self.PFL5_ResultPlane = None
            self.PFL5_Log = ["错误: {}".format(e)]
            self.Log.append("[Step5/PFL5] PlaneFromLists::5 失败: {}".format(e))
            return

        # ---------------------------
        # 5.3 PlaneFromLists::6（源平面）
        #   OriginPoints = BC3 PointList（按你的描述“PointList”，这里按 FT_BlockCutter::3 的 PointList 处理）
        #   BasePlanes   = BC3 Corner0Planes
        #   支持广播对齐
        # ---------------------------
        try:
            idx_o_6 = _get_from_alldict(AllDict, "PlaneFromLists_6__IndexOrigin", None)
            idx_p_6 = _get_from_alldict(AllDict, "PlaneFromLists_6__IndexPlane", None)
            wrap_6 = _get_from_alldict(AllDict, "PlaneFromLists_6__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_6)
            idx_p_list = _as_list_or_none(idx_p_6)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl6 = FTPlaneFromLists(wrap=bool(wrap_6))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl6.build_plane(
                    self.BC3_PointList,
                    self.BC3_Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL6_BasePlane = bp_out
            self.PFL6_OriginPoint = op_out
            self.PFL6_ResultPlane = rp_out
            self.PFL6_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step5/PFL6] " + str(l))

        except Exception as e:
            self.PFL6_BasePlane = None
            self.PFL6_OriginPoint = None
            self.PFL6_ResultPlane = None
            self.PFL6_Log = ["错误: {}".format(e)]
            self.Log.append("[Step5/PFL6] PlaneFromLists::6 失败: {}".format(e))
            return

        # ---------------------------
        # 5.4 GeoAligner::3
        #   Geo         = BC3 TimberBrep（单值）
        #   SourcePlane = PFL6 ResultPlane（多值）
        #   TargetPlane = PFL5 ResultPlane（多值）
        #   注意：Geo 单值，而 SP/TP 多值，需要广播机制
        # ---------------------------
        try:
            rot_deg = _get_from_alldict(AllDict, "GeoAligner_3__RotateDeg", 0.0)
            flip_x = _get_from_alldict(AllDict, "GeoAligner_3__FlipX", False)
            flip_y = _get_from_alldict(AllDict, "GeoAligner_3__FlipY", False)
            flip_z = _get_from_alldict(AllDict, "GeoAligner_3__FlipZ", False)
            mv_x = _get_from_alldict(AllDict, "GeoAligner_3__MoveX", None)
            mv_y = _get_from_alldict(AllDict, "GeoAligner_3__MoveY", None)
            mv_z = _get_from_alldict(AllDict, "GeoAligner_3__MoveZ", None)

            sp_list = self.PFL6_ResultPlane if isinstance(self.PFL6_ResultPlane, list) else (
                [self.PFL6_ResultPlane] if self.PFL6_ResultPlane is not None else [])
            tp_list = self.PFL5_ResultPlane if isinstance(self.PFL5_ResultPlane, list) else (
                [self.PFL5_ResultPlane] if self.PFL5_ResultPlane is not None else [])

            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)
            n = max(n, _broadcast_len(rot_deg, flip_x, flip_y, flip_z, mv_x, mv_y, mv_z))

            self.GA3_SourceOut = []
            self.GA3_TargetOut = []
            self.GA3_MovedGeo = []

            for i in range(n):
                sp = sp_list[i % len(sp_list)] if sp_list else None
                tp = tp_list[i % len(tp_list)] if tp_list else None

                rdeg = _as_number(_broadcast_get(rot_deg, i, n), 0.0)
                fx = _as_bool(_broadcast_get(flip_x, i, n), False)
                fy = _as_bool(_broadcast_get(flip_y, i, n), False)
                fz = _as_bool(_broadcast_get(flip_z, i, n), False)

                mx_raw = _broadcast_get(mv_x, i, n)
                my_raw = _broadcast_get(mv_y, i, n)
                mz_raw = _broadcast_get(mv_z, i, n)

                kwargs = {
                    "rotate_deg": rdeg,
                    "flip_x": fx,
                    "flip_y": fy,
                    "flip_z": fz,
                }
                # 无值则不传：保持“无值则默认”的根源策略
                if mx_raw is not None:
                    kwargs["move_x"] = _as_number(mx_raw, 0.0)
                if my_raw is not None:
                    kwargs["move_y"] = _as_number(my_raw, 0.0)
                if mz_raw is not None:
                    kwargs["move_z"] = _as_number(mz_raw, 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.BC3_TimberBrep,
                    sp,
                    tp,
                    **kwargs
                )

                self.GA3_SourceOut.append(so)
                self.GA3_TargetOut.append(to)
                self.GA3_MovedGeo.append(mg)

            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA3_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA3_SourceOut = []
            self.GA3_TargetOut = []
            self.GA3_MovedGeo = []
            self.Log.append("[Step5/GA3] GeoAligner::3 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 6：端头中间切削（按你给定的组件串）
    #   FT_BlockCutter::4 + PlaneFromLists::7/8 + GeoAligner::3
    # ------------------------------------------------------------------
    def step6_end_middle_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 6.1 FT_BlockCutter::4
        # ---------------------------
        bc_len = _get_from_alldict(AllDict, "FT_BlockCutter_4__length_fen", None)
        bc_wid = _get_from_alldict(AllDict, "FT_BlockCutter_4__width_fen", None)
        bc_hei = _get_from_alldict(AllDict, "FT_BlockCutter_4__height_fen", None)
        if bc_len is None:
            bc_len = 32.0
        if bc_wid is None:
            bc_wid = 32.0
        if bc_hei is None:
            bc_hei = 20.0

        bc_bp = rg.Point3d(0.0, 0.0, 0.0)
        bc_plane = _gh_xz_plane(origin=bc_bp)

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(bc_len),
                float(bc_wid),
                float(bc_hei),
                bc_bp,
                bc_plane,
            )

            self.BC4_TimberBrep = timber_brep
            self.BC4_FaceList = faces or []
            self.BC4_PointList = points or []
            self.BC4_EdgeList = edges or []
            self.BC4_CenterPoint = center_pt
            self.BC4_CenterAxisLines = center_axes or []
            self.BC4_EdgeMidPoints = edge_midpts or []
            self.BC4_FacePlaneList = face_planes or []
            self.BC4_Corner0Planes = corner0_planes or []
            self.BC4_LocalAxesPlane = local_axes_plane
            self.BC4_AxisX = axis_x
            self.BC4_AxisY = axis_y
            self.BC4_AxisZ = axis_z
            self.BC4_FaceDirTags = face_tags or []
            self.BC4_EdgeDirTags = edge_tags or []
            self.BC4_Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step6/BC4] " + str(l))

        except Exception as e:
            self.BC4_TimberBrep = None
            self.BC4_FaceList = []
            self.BC4_PointList = []
            self.BC4_EdgeList = []
            self.BC4_CenterPoint = None
            self.BC4_CenterAxisLines = []
            self.BC4_EdgeMidPoints = []
            self.BC4_FacePlaneList = []
            self.BC4_Corner0Planes = []
            self.BC4_LocalAxesPlane = None
            self.BC4_AxisX = None
            self.BC4_AxisY = None
            self.BC4_AxisZ = None
            self.BC4_FaceDirTags = []
            self.BC4_EdgeDirTags = []
            self.BC4_Corner0EdgeDirs = []
            self.Log.append("[Step6/BC4] 构建 FT_BlockCutter::4 失败: {}".format(e))
            return

        # ---------------------------
        # 6.2 PlaneFromLists::7（目标平面）
        #   OriginPoints = Step2 EdgeMidPoints
        #   BasePlanes   = Step2 Corner0Planes
        # ---------------------------
        try:
            idx_o_7 = _get_from_alldict(AllDict, "PlaneFromLists_7__IndexOrigin", None)
            idx_p_7 = _get_from_alldict(AllDict, "PlaneFromLists_7__IndexPlane", None)
            wrap_7 = _get_from_alldict(AllDict, "PlaneFromLists_7__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_7)
            idx_p_list = _as_list_or_none(idx_p_7)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl7 = FTPlaneFromLists(wrap=bool(wrap_7))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl7.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL7_BasePlane = bp_out
            self.PFL7_OriginPoint = op_out
            self.PFL7_ResultPlane = rp_out
            self.PFL7_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step6/PFL7] " + str(l))

        except Exception as e:
            self.PFL7_BasePlane = None
            self.PFL7_OriginPoint = None
            self.PFL7_ResultPlane = None
            self.PFL7_Log = ["错误: {}".format(e)]
            self.Log.append("[Step6/PFL7] PlaneFromLists::7 失败: {}".format(e))
            return

        # ---------------------------
        # 6.3 PlaneFromLists::8（源平面）
        #   OriginPoints = BC4 EdgeMidPoints
        #   BasePlanes   = BC4 Corner0Planes
        # ---------------------------
        try:
            idx_o_8 = _get_from_alldict(AllDict, "PlaneFromLists_8__IndexOrigin", None)
            idx_p_8 = _get_from_alldict(AllDict, "PlaneFromLists_8__IndexPlane", None)
            wrap_8 = _get_from_alldict(AllDict, "PlaneFromLists_8__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_8)
            idx_p_list = _as_list_or_none(idx_p_8)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl8 = FTPlaneFromLists(wrap=bool(wrap_8))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp, op, rp, lg = pfl8.build_plane(
                    self.BC4_EdgeMidPoints,
                    self.BC4_Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp)
                op_out.append(op)
                rp_out.append(rp)
                lg_out.extend(lg or [])

            self.PFL8_BasePlane = bp_out
            self.PFL8_OriginPoint = op_out
            self.PFL8_ResultPlane = rp_out
            self.PFL8_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step6/PFL8] " + str(l))

        except Exception as e:
            self.PFL8_BasePlane = None
            self.PFL8_OriginPoint = None
            self.PFL8_ResultPlane = None
            self.PFL8_Log = ["错误: {}".format(e)]
            self.Log.append("[Step6/PFL8] PlaneFromLists::8 失败: {}".format(e))
            return

        # ---------------------------
        # 6.4 GeoAligner::3（Step6）
        #   Geo         = BC4 TimberBrep（单值）
        #   SourcePlane = PFL8 ResultPlane（可能多值）
        #   TargetPlane = PFL7 ResultPlane（可能多值）
        #   Geo 单值，而 SP/TP 多值，需要广播机制
        # ---------------------------
        try:
            # Step6 的 GeoAligner::3（FT_BlockCutter::4）参数：只允许读取本步骤自己的变量
            # 说明：
            # - 数据库里 Step5 端头切削已占用 GeoAligner_3__*（GA3），Step6 不能回退读取它，否则会串扰（你看到的 mv_y=33 就是这种串扰）
            # - 兼容两种 ExportAll 叶子键命名：
            #     1) GeoAligner_4__MoveY 这类“扁平键”
            #     2) GeoAligner::3(FT_BlockCutter::4)__MoveY 这类“组名__叶子名”
            def _ga6_get(param, default=None):
                cand_keys = [
                    "GeoAligner::3(FT_BlockCutter::4)__{}".format(param),
                    "GeoAligner_3__{}".format(param),
                ]
                for kk in cand_keys:
                    if kk in AllDict:
                        vv = AllDict.get(kk, None)
                        if vv is not None:
                            return vv
                return default

            rot_deg = _ga6_get("RotateDeg", 0.0)
            flip_x = _ga6_get("FlipX", False)
            flip_y = _ga6_get("FlipY", False)
            flip_z = _ga6_get("FlipZ", False)
            mv_x = _ga6_get("MoveX", None)
            mv_y = _ga6_get("MoveY", None)
            mv_z = _ga6_get("MoveZ", None)
            print(mv_x, mv_y, mv_z)

            sp_list = self.PFL8_ResultPlane if isinstance(self.PFL8_ResultPlane, list) else (
                [self.PFL8_ResultPlane] if self.PFL8_ResultPlane is not None else [])
            tp_list = self.PFL7_ResultPlane if isinstance(self.PFL7_ResultPlane, list) else (
                [self.PFL7_ResultPlane] if self.PFL7_ResultPlane is not None else [])

            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)
            n = max(n, _broadcast_len(rot_deg, flip_x, flip_y, flip_z, mv_x, mv_y, mv_z))

            self.GA4_SourceOut = []
            self.GA4_TargetOut = []
            self.GA4_MovedGeo = []

            for i in range(n):
                sp = sp_list[i % len(sp_list)] if sp_list else None
                tp = tp_list[i % len(tp_list)] if tp_list else None

                rdeg = _as_number(_broadcast_get(rot_deg, i, n), 0.0)
                fx = _as_bool(_broadcast_get(flip_x, i, n), False)
                fy = _as_bool(_broadcast_get(flip_y, i, n), False)
                fz = _as_bool(_broadcast_get(flip_z, i, n), False)

                mx_raw = _broadcast_get(mv_x, i, n)
                my_raw = _broadcast_get(mv_y, i, n)
                mz_raw = _broadcast_get(mv_z, i, n)

                kwargs = {
                    "rotate_deg": rdeg,
                    "flip_x": fx,
                    "flip_y": fy,
                    "flip_z": fz,
                }
                # 无值则不传：保持“无值则默认”的根源策略
                if mx_raw is not None:
                    kwargs["move_x"] = _as_number(mx_raw, 0.0)
                if my_raw is not None:
                    kwargs["move_y"] = _as_number(my_raw, 0.0)
                if mz_raw is not None:
                    kwargs["move_z"] = _as_number(mz_raw, 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.BC4_TimberBrep,
                    sp,
                    tp,
                    **kwargs
                )

                self.GA4_SourceOut.append(so)
                self.GA4_TargetOut.append(to)
                self.GA4_MovedGeo.append(mg)

            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA4_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA4_SourceOut = []
            self.GA4_TargetOut = []
            self.GA4_MovedGeo = []
            self.Log.append("[Step6/GA3] GeoAligner::3 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 7：乳栿劄牽切削（RuFangKaKouBuilder + PlaneFromLists::9 + GeoAligner::4）
    # ------------------------------------------------------------------
    def step7_rufang_kakou_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 7.1 RuFangKaKouBuilder
        # ---------------------------
        try:
            bp = rg.Point3d(0.0, 0.0, 0.0)

            w = _get_from_alldict(AllDict, "RuFangKaKouBuilder__WidthFen", None)
            h = _get_from_alldict(AllDict, "RuFangKaKouBuilder__HeightFen", None)
            eo = _get_from_alldict(AllDict, "RuFangKaKouBuilder__EdgeOffsetFen", None)
            ti = _get_from_alldict(AllDict, "RuFangKaKouBuilder__TopInsetFen", None)
            ex = _get_from_alldict(AllDict, "RuFangKaKouBuilder__ExtrudeFen", None)

            # 按你给的 ghpy 逻辑：None 或 0 用默认
            if w is None or w == 0:
                w = 10.0
            if h is None or h == 0:
                h = 15.0
            if eo is None or eo == 0:
                eo = 1.0
            if ti is None or ti == 0:
                ti = 5.0
            if ex is None or ex == 0:
                ex = 10.0

            # RefPlane：此步骤你未指定来源，先按 None 交给 Builder 内部处理
            ref_plane = None

            builder = RuFangKaKouBuilder(
                base_point=bp,
                ref_plane=ref_plane,
                width_fen=float(w),
                height_fen=float(h),
                edge_offset_fen=float(eo),
                top_inset_fen=float(ti),
                extrude_fen=float(ex),
            )
            result = builder.build() or {}

            self.RFKK_OuterTool = result.get("OuterTool", None)
            self.RFKK_InnerTool = result.get("InnerTool", None)
            self.RFKK_OuterSection = result.get("OuterSection", None)
            self.RFKK_InnerSection = result.get("InnerSection", None)
            self.RFKK_RefPlanes = result.get("RefPlanes", []) or []
            self.RFKK_EdgeMidPoints = result.get("EdgeMidPoints", []) or []
            self.RFKK_EdgeNames = result.get("EdgeNames", []) or []
            self.RFKK_KeyPoints = result.get("KeyPoints", []) or []
            self.RFKK_KeyPointNames = result.get("KeyPointNames", []) or []
            self.RFKK_EdgeCurves = result.get("EdgeCurves", []) or []
            self.RFKK_Log = result.get("Log", []) or []
            self.RFKK_RefPlaneNames = result.get("RefPlaneNames", []) or []

            for l in (self.RFKK_Log or []):
                self.Log.append("[Step7/RuFangKaKou] " + str(l))

        except Exception as e:
            self.RFKK_OuterTool = None
            self.RFKK_InnerTool = None
            self.RFKK_OuterSection = None
            self.RFKK_InnerSection = None
            self.RFKK_RefPlanes = []
            self.RFKK_EdgeMidPoints = []
            self.RFKK_EdgeNames = []
            self.RFKK_KeyPoints = []
            self.RFKK_KeyPointNames = []
            self.RFKK_EdgeCurves = []
            self.RFKK_Log = ["错误: {}".format(e)]
            self.RFKK_RefPlaneNames = []
            self.Log.append("[Step7/RuFangKaKou] RuFangKaKouBuilder 失败: {}".format(e))
            return

        # ---------------------------
        # 7.2 PlaneFromLists::9（目标平面）
        #   OriginPoints = Step2 EdgeMidPoints
        #   BasePlanes   = Step2 Corner0Planes
        # ---------------------------
        try:
            idx_o_9 = _get_from_alldict(AllDict, "PlaneFromLists_9__IndexOrigin", None)
            idx_p_9 = _get_from_alldict(AllDict, "PlaneFromLists_9__IndexPlane", None)
            wrap_9 = _get_from_alldict(AllDict, "PlaneFromLists_9__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_9)
            idx_p_list = _as_list_or_none(idx_p_9)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl9 = FTPlaneFromLists(wrap=bool(wrap_9))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp9, op9, rp9, lg9 = pfl9.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp9)
                op_out.append(op9)
                rp_out.append(rp9)
                lg_out.extend(lg9 or [])

            self.PFL9_BasePlane = bp_out
            self.PFL9_OriginPoint = op_out
            self.PFL9_ResultPlane = rp_out
            self.PFL9_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step7/PFL9] " + str(l))

        except Exception as e:
            self.PFL9_BasePlane = None
            self.PFL9_OriginPoint = None
            self.PFL9_ResultPlane = None
            self.PFL9_Log = ["错误: {}".format(e)]
            self.Log.append("[Step7/PFL9] PlaneFromLists::9 失败: {}".format(e))
            return

        # ---------------------------
        # 7.3 GeoAligner::4
        #   Geo         = RuFangKaKouBuilder OuterTool（单值）
        #   SourcePlane = RuFangKaKouBuilder RefPlanes（按索引 GeoAligner_4__SourcePlane 取）
        #   TargetPlane = PlaneFromLists::9 ResultPlane（可能多值）
        #   FlipX       = GeoAligner_4__FlipX
        #   MoveY       = GeoAligner_4__MoveY
        # ---------------------------
        try:
            # 读取本步骤自己的 GA4 参数（不做回退）
            def _ga7_get(param, default=None):
                cand_keys = [
                    "GeoAligner::4__{}".format(param),
                    "GeoAligner_4__{}".format(param),
                ]
                for kk in cand_keys:
                    if kk in AllDict:
                        vv = AllDict.get(kk, None)
                        if vv is not None:
                            return vv
                return default

            sp_idx = _ga7_get("SourcePlane", None)
            flip_x = _ga7_get("FlipX", False)
            mv_y = _ga7_get("MoveY", None)

            # SourcePlane：支持直接给 Plane，或给索引（int / list[int] / DataTree）
            sp_list = []
            if isinstance(sp_idx, rg.Plane):
                sp_list = [sp_idx]
            else:
                idx_list = _as_list_or_none(sp_idx)
                if idx_list is None:
                    idx_list = [sp_idx]
                for ii in (idx_list or []):
                    if ii is None:
                        sp_list.append(None)
                        continue
                    try:
                        k = int(ii)
                        if self.RFKK_RefPlanes:
                            k = k % len(self.RFKK_RefPlanes)
                            sp_list.append(self.RFKK_RefPlanes[k])
                        else:
                            sp_list.append(None)
                    except Exception:
                        sp_list.append(None)

            tp_list = self.PFL9_ResultPlane if isinstance(self.PFL9_ResultPlane, list) else (
                [self.PFL9_ResultPlane] if self.PFL9_ResultPlane is not None else [])
            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)
            n = max(n, _broadcast_len(flip_x, mv_y))

            self.GA5_SourceOut = []
            self.GA5_TargetOut = []
            self.GA5_MovedGeo = []

            for i in range(n):
                sp = sp_list[i % len(sp_list)] if sp_list else None
                tp = tp_list[i % len(tp_list)] if tp_list else None

                fx = _as_bool(_broadcast_get(flip_x, i, n), False)
                my_raw = _broadcast_get(mv_y, i, n)

                kwargs = {
                    "rotate_deg": 0.0,
                    "flip_x": fx,
                    "flip_y": False,
                    "flip_z": False,
                }
                if my_raw is not None:
                    kwargs["move_y"] = _as_number(my_raw, 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.RFKK_OuterTool,
                    sp,
                    tp,
                    **kwargs
                )
                self.GA5_SourceOut.append(so)
                self.GA5_TargetOut.append(to)
                self.GA5_MovedGeo.append(mg)

            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA5_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA5_SourceOut = []
            self.GA5_TargetOut = []
            self.GA5_MovedGeo = []
            self.Log.append("[Step7/GA4] GeoAligner::4 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 8：令栱切削（FT_BlockCutter::5 + PlaneFromLists::10/11 + GeoAligner::5）
    # ------------------------------------------------------------------
    def step8_linggong_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 8.1 FT_BlockCutter::5
        # ---------------------------
        bc_len = _get_from_alldict(AllDict, "FT_BlockCutter_5__length_fen", None)
        bc_wid = _get_from_alldict(AllDict, "FT_BlockCutter_5__width_fen", None)
        bc_hei = _get_from_alldict(AllDict, "FT_BlockCutter_5__height_fen", None)

        if bc_len is None:
            bc_len = 32.0
        if bc_wid is None:
            bc_wid = 32.0
        if bc_hei is None:
            bc_hei = 20.0

        bc_bp = rg.Point3d(0.0, 0.0, 0.0)  # base_point 默认为原点
        bc_plane = _gh_xz_plane(origin=bc_bp)  # reference_plane 默认为 GH 的 XZ Plane

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(bc_len),
                float(bc_wid),
                float(bc_hei),
                bc_bp,
                bc_plane,
            )

            self.BC5_TimberBrep = timber_brep
            self.BC5_FaceList = faces or []
            self.BC5_PointList = points or []
            self.BC5_EdgeList = edges or []
            self.BC5_CenterPoint = center_pt
            self.BC5_CenterAxisLines = center_axes or []
            self.BC5_EdgeMidPoints = edge_midpts or []
            self.BC5_FacePlaneList = face_planes or []
            self.BC5_Corner0Planes = corner0_planes or []
            self.BC5_LocalAxesPlane = local_axes_plane
            self.BC5_AxisX = axis_x
            self.BC5_AxisY = axis_y
            self.BC5_AxisZ = axis_z
            self.BC5_FaceDirTags = face_tags or []
            self.BC5_EdgeDirTags = edge_tags or []
            self.BC5_Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step8/BC5] " + str(l))

        except Exception as e:
            self.BC5_TimberBrep = None
            self.BC5_FaceList = []
            self.BC5_PointList = []
            self.BC5_EdgeList = []
            self.BC5_CenterPoint = None
            self.BC5_CenterAxisLines = []
            self.BC5_EdgeMidPoints = []
            self.BC5_FacePlaneList = []
            self.BC5_Corner0Planes = []
            self.BC5_LocalAxesPlane = None
            self.BC5_AxisX = None
            self.BC5_AxisY = None
            self.BC5_AxisZ = None
            self.BC5_FaceDirTags = []
            self.BC5_EdgeDirTags = []
            self.BC5_Corner0EdgeDirs = []
            self.Log.append("[Step8/BC5] FT_BlockCutter::5 失败: {}".format(e))
            return

        # ---------------------------
        # 8.2 PlaneFromLists::10（目标平面）
        #   OriginPoints = Step2 PointList
        #   BasePlanes   = Step2 Corner0Planes
        # ---------------------------
        try:
            idx_o_10 = _get_from_alldict(AllDict, "PlaneFromLists_10__IndexOrigin", None)
            idx_p_10 = _get_from_alldict(AllDict, "PlaneFromLists_10__IndexPlane", None)
            wrap_10 = _get_from_alldict(AllDict, "PlaneFromLists_10__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_10)
            idx_p_list = _as_list_or_none(idx_p_10)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl10 = FTPlaneFromLists(wrap=bool(wrap_10))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp10, op10, rp10, lg10 = pfl10.build_plane(
                    self.PointList,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp10)
                op_out.append(op10)
                rp_out.append(rp10)
                lg_out.extend(lg10 or [])

            self.PFL10_BasePlane = bp_out
            self.PFL10_OriginPoint = op_out
            self.PFL10_ResultPlane = rp_out
            self.PFL10_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step8/PFL10] " + str(l))

        except Exception as e:
            self.PFL10_BasePlane = None
            self.PFL10_OriginPoint = None
            self.PFL10_ResultPlane = None
            self.PFL10_Log = ["错误: {}".format(e)]
            self.Log.append("[Step8/PFL10] PlaneFromLists::10 失败: {}".format(e))
            return

        # ---------------------------
        # 8.3 PlaneFromLists::11（源平面）
        #   OriginPoints = BC5 PointList
        #   BasePlanes   = BC5 Corner0Planes
        # ---------------------------
        try:
            idx_o_11 = _get_from_alldict(AllDict, "PlaneFromLists_11__IndexOrigin", None)
            idx_p_11 = _get_from_alldict(AllDict, "PlaneFromLists_11__IndexPlane", None)
            wrap_11 = _get_from_alldict(AllDict, "PlaneFromLists_11__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_11)
            idx_p_list = _as_list_or_none(idx_p_11)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl11 = FTPlaneFromLists(wrap=bool(wrap_11))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp11, op11, rp11, lg11 = pfl11.build_plane(
                    self.BC5_PointList,
                    self.BC5_Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp11)
                op_out.append(op11)
                rp_out.append(rp11)
                lg_out.extend(lg11 or [])

            self.PFL11_BasePlane = bp_out
            self.PFL11_OriginPoint = op_out
            self.PFL11_ResultPlane = rp_out
            self.PFL11_Log = lg_out
            for l in (lg_out or []):
                self.Log.append("[Step8/PFL11] " + str(l))

        except Exception as e:
            self.PFL11_BasePlane = None
            self.PFL11_OriginPoint = None
            self.PFL11_ResultPlane = None
            self.PFL11_Log = ["错误: {}".format(e)]
            self.Log.append("[Step8/PFL11] PlaneFromLists::11 失败: {}".format(e))
            return

        # ---------------------------
        # 8.4 GeoAligner::5
        #   Geo         = BC5 TimberBrep
        #   SourcePlane = PFL11 ResultPlane
        #   TargetPlane = PFL10 ResultPlane
        #   MoveX       = GeoAligner_5__MoveX
        #   MoveZ       = GeoAligner_5__MoveZ
        # ---------------------------
        try:
            mv_x = _get_from_alldict(AllDict, "GeoAligner_5__MoveX", None)
            mv_z = _get_from_alldict(AllDict, "GeoAligner_5__MoveZ", None)

            sp_list = self.PFL11_ResultPlane if isinstance(self.PFL11_ResultPlane, list) else (
                [self.PFL11_ResultPlane] if self.PFL11_ResultPlane is not None else [])
            tp_list = self.PFL10_ResultPlane if isinstance(self.PFL10_ResultPlane, list) else (
                [self.PFL10_ResultPlane] if self.PFL10_ResultPlane is not None else [])

            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)
            n = max(n, _broadcast_len(mv_x, mv_z))

            self.GA6_SourceOut = []
            self.GA6_TargetOut = []
            self.GA6_MovedGeo = []

            for i in range(n):
                sp = sp_list[i % len(sp_list)] if sp_list else None
                tp = tp_list[i % len(tp_list)] if tp_list else None

                mx_raw = _broadcast_get(mv_x, i, n)
                mz_raw = _broadcast_get(mv_z, i, n)

                kwargs = {
                    "rotate_deg": 0.0,
                    "flip_x": False,
                    "flip_y": False,
                    "flip_z": False,
                }
                if mx_raw is not None:
                    kwargs["move_x"] = _as_number(mx_raw, 0.0)
                if mz_raw is not None:
                    kwargs["move_z"] = _as_number(mz_raw, 0.0)

                so, to, mg = FT_GeoAligner.align(
                    self.BC5_TimberBrep,
                    sp,
                    tp,
                    **kwargs
                )
                self.GA6_SourceOut.append(so)
                self.GA6_TargetOut.append(to)
                self.GA6_MovedGeo.append(mg)

            if self.CutTimbers is None:
                self.CutTimbers = []
            moved = [g for g in self.GA6_MovedGeo if g is not None]
            if moved:
                self.CutTimbers = _deep_flatten(self.CutTimbers) + moved

        except Exception as e:
            self.GA6_SourceOut = []
            self.GA6_TargetOut = []
            self.GA6_MovedGeo = []
            self.Log.append("[Step8/GA5] GeoAligner::5 失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 9：卷殺和刀具合并裁切
    #   JuanShaToolBuilder + PlaneFromLists::12 + GeoAligner::6 + FT_CutTimberByTools
    # ------------------------------------------------------------------
    def step9_juansha_and_final_cut(self):
        AllDict = self.AllDict_1 or {}

        # ---------------------------
        # 9.1 JuanShaToolBuilder
        # ---------------------------
        try:
            h = _get_from_alldict(AllDict, "JuanShaToolBuilder__HeightFen", None)
            l = _get_from_alldict(AllDict, "JuanShaToolBuilder__LengthFen", None)
            dc = _get_from_alldict(AllDict, "JuanShaToolBuilder__DivCount", None)
            th = _get_from_alldict(AllDict, "JuanShaToolBuilder__ThicknessFen", None)

            # SectionPlane：若 DB 未提供，则默认 GH XZ Plane（原点随 PositionPoint）
            sp = _get_from_alldict(AllDict, "JuanShaToolBuilder__SectionPlane", None)

            pp = _get_from_alldict(AllDict, "JuanShaToolBuilder__PositionPoint", None)
            pp = _to_point3d(pp, default=rg.Point3d(0.0, 0.0, 0.0))

            if sp is None:
                sp = _gh_xz_plane(origin=pp)

            builder = JuanShaToolBuilder(
                height_fen=h,
                length_fen=l,
                thickness_fen=th,
                div_count=dc,
                section_plane=sp,
                position_point=pp
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, Log = builder.build()

            self.JS_ToolBrep = ToolBrep
            self.JS_SectionEdges = SectionEdges or []
            self.JS_HL_Intersection = HL_Intersection
            self.JS_HeightFacePlane = HeightFacePlane
            self.JS_LengthFacePlane = LengthFacePlane
            self.JS_Log = Log or []

            for li in (self.JS_Log or []):
                self.Log.append("[Step9/JuanShaToolBuilder] " + str(li))

        except Exception as e:
            self.JS_ToolBrep = None
            self.JS_SectionEdges = []
            self.JS_HL_Intersection = None
            self.JS_HeightFacePlane = None
            self.JS_LengthFacePlane = None
            self.JS_Log = ["错误: {}".format(e)]
            self.Log.append("[Step9/JuanShaToolBuilder] 失败: {}".format(e))
            # 没有刀具则无法继续最终裁切
            return

        # ---------------------------
        # 9.2 PlaneFromLists::12（目标平面）
        #   OriginPoints = Step2 EdgeMidPoints
        #   BasePlanes   = Step2 Corner0Planes
        # ---------------------------
        try:
            idx_o_12 = _get_from_alldict(AllDict, "PlaneFromLists_12__IndexOrigin", None)
            idx_p_12 = _get_from_alldict(AllDict, "PlaneFromLists_12__IndexPlane", None)
            wrap_12 = _get_from_alldict(AllDict, "PlaneFromLists_12__Wrap", True)

            idx_o_list = _as_list_or_none(idx_o_12)
            idx_p_list = _as_list_or_none(idx_p_12)
            idx_o_list, idx_p_list = _broadcast_pair(idx_o_list, idx_p_list)

            pfl12 = FTPlaneFromLists(wrap=bool(wrap_12))
            bp_out, op_out, rp_out, lg_out = [], [], [], []
            for io, ip in zip(idx_o_list, idx_p_list):
                bp12, op12, rp12, lg12 = pfl12.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip,
                )
                bp_out.append(bp12)
                op_out.append(op12)
                rp_out.append(rp12)
                lg_out.extend(lg12 or [])

            self.PFL12_BasePlane = bp_out
            self.PFL12_OriginPoint = op_out
            self.PFL12_ResultPlane = rp_out
            self.PFL12_Log = lg_out
            for li in (lg_out or []):
                self.Log.append("[Step9/PFL12] " + str(li))

        except Exception as e:
            self.PFL12_BasePlane = None
            self.PFL12_OriginPoint = None
            self.PFL12_ResultPlane = None
            self.PFL12_Log = ["错误: {}".format(e)]
            self.Log.append("[Step9/PFL12] PlaneFromLists::12 失败: {}".format(e))
            return

        # ---------------------------
        # 9.3 GeoAligner::6（对位 JuanSha Tool）
        #   Geo         = JuanShaToolBuilder ToolBrep
        #   SourcePlane = JuanShaToolBuilder HeightFacePlane（按 GeoAligner_6__SourcePlane 索引取）
        #   TargetPlane = PlaneFromLists::12 ResultPlane
        #   RotateDeg   = GeoAligner_6__RotateDeg
        #   FlipZ       = GeoAligner_6__FlipZ
        # ---------------------------
        try:
            sp_idx = _get_from_alldict(AllDict, "GeoAligner_6__SourcePlane", 0)
            rot_deg = _get_from_alldict(AllDict, "GeoAligner_6__RotateDeg", 0.0)
            flip_z = _get_from_alldict(AllDict, "GeoAligner_6__FlipZ", False)

            # HeightFacePlane 可能是单个 Plane，也可能是 list
            hfp_list = self.JS_HeightFacePlane
            if isinstance(hfp_list, rg.Plane):
                hfp_list = [hfp_list]
            elif hfp_list is None:
                hfp_list = [None]
            elif not isinstance(hfp_list, list):
                hfp_list = [hfp_list]

            idx_list = _as_list_or_none(sp_idx)
            if idx_list is None:
                idx_list = [sp_idx]

            # 目标平面：可能多值
            tp_list = self.PFL12_ResultPlane if isinstance(self.PFL12_ResultPlane, list) else (
                [self.PFL12_ResultPlane] if self.PFL12_ResultPlane is not None else [])
            # source plane 先按 idx_list 生成
            sp_list = []
            for ii in idx_list:
                try:
                    k = int(ii) if ii is not None else 0
                except Exception:
                    k = 0
                if hfp_list:
                    k = k % len(hfp_list)
                    sp_list.append(hfp_list[k])
                else:
                    sp_list.append(None)

            sp_list, tp_list = _broadcast_pair(sp_list, tp_list)
            n = max(len(sp_list), len(tp_list), 1)
            n = max(n, _broadcast_len(rot_deg, flip_z))

            self.GA7_SourceOut = []
            self.GA7_TargetOut = []
            self.GA7_MovedGeo = []

            for i in range(n):
                sp = sp_list[i % len(sp_list)] if sp_list else None
                tp = tp_list[i % len(tp_list)] if tp_list else None

                rdeg = _as_number(_broadcast_get(rot_deg, i, n), 0.0)
                fz = _as_bool(_broadcast_get(flip_z, i, n), False)

                so, to, mg = FT_GeoAligner.align(
                    self.JS_ToolBrep,
                    sp,
                    tp,
                    rotate_deg=rdeg,
                    flip_x=False,
                    flip_y=False,
                    flip_z=fz,
                    move_x=0.0,
                    move_y=0.0,
                    move_z=0.0,
                )
                self.GA7_SourceOut.append(so)
                self.GA7_TargetOut.append(to)
                self.GA7_MovedGeo.append(mg)

        except Exception as e:
            self.GA7_SourceOut = []
            self.GA7_TargetOut = []
            self.GA7_MovedGeo = []
            self.Log.append("[Step9/GA6] GeoAligner::6 失败: {}".format(e))
            return

        # ---------------------------
        # 9.4 FT_CutTimberByTools（最终裁切）
        #   Timbers = Step2 TimberBrep
        #   Tools   = [GA1, GA2, GA3(step5), GA4(step6), GA5(step7), GA6(step8), GA7(step9)] 的 MovedGeo 列表合并
        # ---------------------------
        try:
            tools = []
            for grp in [self.GA1_MovedGeo, self.GA2_MovedGeo, self.GA3_MovedGeo, self.GA4_MovedGeo, self.GA5_MovedGeo,
                        self.GA6_MovedGeo, self.GA7_MovedGeo]:
                tools.extend(_deep_flatten(grp))
            tools = [t for t in tools if t is not None]

            cutter = FT_CutTimberByTools(self.TimberBrep, tools)
            CutTimbers, FailTimbers, Log = cutter.run()

            self.FinalCutTimbers = CutTimbers
            self.FinalFailTimbers = FailTimbers or []
            self.FinalCutLog = Log or []

            for li in (self.FinalCutLog or []):
                self.Log.append("[Step9/CutTimber] " + str(li))

            # 最终对外输出：以最终裁切结果覆盖 CutTimbers/FailTimbers
            self.CutTimbers = CutTimbers
            self.FailTimbers = FailTimbers or []

        except Exception as e:
            self.FinalCutTimbers = None
            self.FinalFailTimbers = []
            self.FinalCutLog = ["错误: {}".format(e)]
            self.Log.append("[Step9/CutTimber] FT_CutTimberByTools 失败: {}".format(e))

    def step1_read_db(self):
        table = "CommonComponents"
        key_field = "type_code"
        key_value = "RufuZhaQian_DouKouTiao"
        field = "params_json"
        json_path = None
        export_all = True

        if not self.DBPath:
            self.Log.append("[Step1] DBPath 为空，无法读取数据库。")
            self.All_1 = []
            self.AllDict_1 = {}
            return

        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table=table,
                key_field=key_field,
                key_value=key_value,
                field=field,
                json_path=json_path,
                export_all=export_all,
                ghenv=self.ghenv
            )
            value, all_list, log_lines = reader.run()

            self.Value_1 = value
            self.All_1 = all_list if all_list is not None else []
            self.AllDict_1 = dict(self.All_1) if self.All_1 else {}

            for l in (log_lines or []):
                self.Log.append("[Step1] " + str(l))

            if not self.All_1:
                self.Log.append("[Step1] All_1 为空：未读到 params_json 或 key 不存在。")

        except Exception as e:
            self.Value_1 = None
            self.All_1 = []
            self.AllDict_1 = {}
            self.Log.append("[Step1] 读取数据库失败: {}".format(e))

    # ------------------------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ------------------------------------------------------------------
    def step2_timber_block(self):
        AllDict = self.AllDict_1 or {}

        # 从 DB 取三维参数（若 DB 没有就用默认）
        length_fen = _get_from_alldict(AllDict, "FT_timber_block_uniform__length_fen", None)
        width_fen = _get_from_alldict(AllDict, "FT_timber_block_uniform__width_fen", None)
        height_fen = _get_from_alldict(AllDict, "FT_timber_block_uniform__height_fen", None)

        if length_fen is None:
            length_fen = 32.0
        if width_fen is None:
            width_fen = 32.0
        if height_fen is None:
            height_fen = 20.0

        # 可选输入端覆盖：FT_timber_block_uniform_length_fen（输入端优先 > DB > 默认）
        try:
            _ov = self.FT_timber_block_uniform_length_fen_override
        except Exception:
            _ov = None
        if _ov is not None:
            # 支持标量 / list / DataTree（取第一个并广播语义）
            length_fen = _as_number(_ov, default=length_fen)
            self.Log.append("[Step2] 使用输入端覆盖 length_fen = {}".format(length_fen))

        # base_point：输入端优先；否则尝试 DB 的 FT_timber_block_uniform__base_point；否则原点
        bp_in = self.base_point
        bp_db = _get_from_alldict(AllDict, "FT_timber_block_uniform__base_point", None)
        bp = _to_point3d(bp_in, default=_to_point3d(bp_db, default=rg.Point3d(0.0, 0.0, 0.0)))

        # reference_plane：按要求默认 GH XZ Plane（以 bp 为原点）
        reference_plane = _gh_xz_plane(origin=bp)

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                float(length_fen),
                float(width_fen),
                float(height_fen),
                bp,
                reference_plane,
            )

            self.TimberBrep = timber_brep
            self.FaceList = faces or []
            self.PointList = points or []
            self.EdgeList = edges or []
            self.CenterPoint = center_pt
            self.CenterAxisLines = center_axes or []
            self.EdgeMidPoints = edge_midpts or []
            self.FacePlaneList = face_planes or []
            self.Corner0Planes = corner0_planes or []
            self.LocalAxesPlane = local_axes_plane
            self.AxisX = axis_x
            self.AxisY = axis_y
            self.AxisZ = axis_z
            self.FaceDirTags = face_tags or []
            self.EdgeDirTags = edge_tags or []
            self.Corner0EdgeDirs = corner0_dirs or []

            for l in (log_lines or []):
                self.Log.append("[Step2] " + str(l))

            # 按“最终输出”约定：当前先用 TimberBrep 占位 CutTimbers
            self.CutTimbers = [self.TimberBrep] if self.TimberBrep is not None else []
            self.FailTimbers = []

        except Exception as e:
            self.TimberBrep = None
            self.FaceList = []
            self.PointList = []
            self.EdgeList = []
            self.CenterPoint = None
            self.CenterAxisLines = []
            self.EdgeMidPoints = []
            self.FacePlaneList = []
            self.Corner0Planes = []
            self.LocalAxesPlane = None
            self.AxisX = None
            self.AxisY = None
            self.AxisZ = None
            self.FaceDirTags = []
            self.EdgeDirTags = []
            self.Corner0EdgeDirs = []

            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[Step2] 构建木坯失败: {}".format(e))

    # ------------------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------------------
    def run(self):
        # Step 1
        self.step1_read_db()
        if not self.All_1:
            self.Log.append("run: All_1 为空，终止后续步骤。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        # Step 2
        self.step2_timber_block()

        # Step 3
        self.step3_side_cut()

        # Step 4
        self.step4_ludou_linggong_cut()

        # Step 5
        self.step5_end_cut()

        # Step 6
        self.step6_end_middle_cut()

        # Step 7
        self.step7_rufang_kakou_cut()

        # Step 8
        self.step8_linggong_cut()

        # Step 9
        self.step9_juansha_and_final_cut()

        return self


# ======================================================================
# GH PYTHON 组件输出绑定区
#   - 这里保持“逐一赋值”的显式写法，便于你后续增减输出端
#   - 同时对关键输出做递归拍平，避免 GH 显示 System.Collections.Generic.List`1[System.Object]
# ======================================================================
if __name__ == "__main__":

    # ---------------------------
    # 输入默认值兜底（输入端优先 > DB > 默认）
    # ---------------------------
    try:
        _db = DBPath
    except Exception:
        _db = None

    try:
        _bp = base_point
    except Exception:
        _bp = None

    try:
        _rf = Refresh
    except Exception:
        _rf = False

    # 可选输入端：用户可自行在 GH 增加 FT_timber_block_uniform_length_fen 输入端
    # - 若未增加该输入端：此处会捕获异常并保持 None
    # - 若增加但未传值：也视为 None
    try:
        _tlen = FT_timber_block_uniform_length_fen
    except Exception:
        _tlen = None

    solver = RufuZhaQian_DouKouTiaoSolver(_db, _bp, _rf, ghenv, FT_timber_block_uniform_length_fen=_tlen).run()

    # ---------------------------
    # 对外三大输出（按要求）
    # ---------------------------
    CutTimbers = _deep_flatten(solver.CutTimbers)
    FailTimbers = _deep_flatten(solver.FailTimbers)
    Log = _deep_flatten(solver.Log)

    # =============================================================
    # 逐步暴露（到当前 Step2 为止）全部 Solver 成员变量
    # 你在 GH 里新增输出端时，只要在这里继续补一行同名赋值即可
    # =============================================================

    # -------- Step 1 --------
    Value_1 = solver.Value_1
    All_1 = solver.All_1
    AllDict_1 = solver.AllDict_1

    # -------- Step 2：主木坯 --------
    TimberBrep = solver.TimberBrep
    FaceList = solver.FaceList
    PointList = solver.PointList
    EdgeList = solver.EdgeList
    CenterPoint = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    EdgeMidPoints = solver.EdgeMidPoints
    FacePlaneList = solver.FacePlaneList
    Corner0Planes = solver.Corner0Planes
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = solver.FaceDirTags
    EdgeDirTags = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs

    # -------- Step 3：两侧切削 --------
    BC1_TimberBrep = solver.BC1_TimberBrep
    BC1_FaceList = solver.BC1_FaceList
    BC1_PointList = solver.BC1_PointList
    BC1_EdgeList = solver.BC1_EdgeList
    BC1_CenterPoint = solver.BC1_CenterPoint
    BC1_CenterAxisLines = solver.BC1_CenterAxisLines
    BC1_EdgeMidPoints = solver.BC1_EdgeMidPoints
    BC1_FacePlaneList = solver.BC1_FacePlaneList
    BC1_Corner0Planes = solver.BC1_Corner0Planes
    BC1_LocalAxesPlane = solver.BC1_LocalAxesPlane
    BC1_AxisX = solver.BC1_AxisX
    BC1_AxisY = solver.BC1_AxisY
    BC1_AxisZ = solver.BC1_AxisZ
    BC1_FaceDirTags = solver.BC1_FaceDirTags
    BC1_EdgeDirTags = solver.BC1_EdgeDirTags
    BC1_Corner0EdgeDirs = solver.BC1_Corner0EdgeDirs

    PFL1_BasePlane = solver.PFL1_BasePlane
    PFL1_OriginPoint = solver.PFL1_OriginPoint
    PFL1_ResultPlane = solver.PFL1_ResultPlane
    PFL1_Log = solver.PFL1_Log

    PFL2_BasePlane = solver.PFL2_BasePlane
    PFL2_OriginPoint = solver.PFL2_OriginPoint
    PFL2_ResultPlane = solver.PFL2_ResultPlane
    PFL2_Log = solver.PFL2_Log

    GA1_SourceOut = solver.GA1_SourceOut
    GA1_TargetOut = solver.GA1_TargetOut
    GA1_MovedGeo = solver.GA1_MovedGeo

    # -------- Step 4：櫨枓和令栱切削 --------
    BC2_TimberBrep = solver.BC2_TimberBrep
    BC2_FaceList = solver.BC2_FaceList
    BC2_PointList = solver.BC2_PointList
    BC2_EdgeList = solver.BC2_EdgeList
    BC2_CenterPoint = solver.BC2_CenterPoint
    BC2_CenterAxisLines = solver.BC2_CenterAxisLines
    BC2_EdgeMidPoints = solver.BC2_EdgeMidPoints
    BC2_FacePlaneList = solver.BC2_FacePlaneList
    BC2_Corner0Planes = solver.BC2_Corner0Planes
    BC2_LocalAxesPlane = solver.BC2_LocalAxesPlane
    BC2_AxisX = solver.BC2_AxisX
    BC2_AxisY = solver.BC2_AxisY
    BC2_AxisZ = solver.BC2_AxisZ
    BC2_FaceDirTags = solver.BC2_FaceDirTags
    BC2_EdgeDirTags = solver.BC2_EdgeDirTags
    BC2_Corner0EdgeDirs = solver.BC2_Corner0EdgeDirs

    PFL3_BasePlane = solver.PFL3_BasePlane
    PFL3_OriginPoint = solver.PFL3_OriginPoint
    PFL3_ResultPlane = solver.PFL3_ResultPlane
    PFL3_Log = solver.PFL3_Log

    PFL4_BasePlane = solver.PFL4_BasePlane
    PFL4_OriginPoint = solver.PFL4_OriginPoint
    PFL4_ResultPlane = solver.PFL4_ResultPlane
    PFL4_Log = solver.PFL4_Log

    GA2_SourceOut = solver.GA2_SourceOut
    GA2_TargetOut = solver.GA2_TargetOut
    GA2_MovedGeo = solver.GA2_MovedGeo

    # -------- Step 5：端头切削 --------
    BC3_TimberBrep = solver.BC3_TimberBrep
    BC3_FaceList = solver.BC3_FaceList
    BC3_PointList = solver.BC3_PointList
    BC3_EdgeList = solver.BC3_EdgeList
    BC3_CenterPoint = solver.BC3_CenterPoint
    BC3_CenterAxisLines = solver.BC3_CenterAxisLines
    BC3_EdgeMidPoints = solver.BC3_EdgeMidPoints
    BC3_FacePlaneList = solver.BC3_FacePlaneList
    BC3_Corner0Planes = solver.BC3_Corner0Planes
    BC3_LocalAxesPlane = solver.BC3_LocalAxesPlane
    BC3_AxisX = solver.BC3_AxisX
    BC3_AxisY = solver.BC3_AxisY
    BC3_AxisZ = solver.BC3_AxisZ
    BC3_FaceDirTags = solver.BC3_FaceDirTags
    BC3_EdgeDirTags = solver.BC3_EdgeDirTags
    BC3_Corner0EdgeDirs = solver.BC3_Corner0EdgeDirs

    PFL5_BasePlane = solver.PFL5_BasePlane
    PFL5_OriginPoint = solver.PFL5_OriginPoint
    PFL5_ResultPlane = solver.PFL5_ResultPlane
    PFL5_Log = solver.PFL5_Log

    PFL6_BasePlane = solver.PFL6_BasePlane
    PFL6_OriginPoint = solver.PFL6_OriginPoint
    PFL6_ResultPlane = solver.PFL6_ResultPlane
    PFL6_Log = solver.PFL6_Log

    GA3_SourceOut = solver.GA3_SourceOut
    GA3_TargetOut = solver.GA3_TargetOut
    GA3_MovedGeo = solver.GA3_MovedGeo

    # -------- Step 6：端头中间切削 --------
    BC4_TimberBrep = solver.BC4_TimberBrep
    BC4_FaceList = solver.BC4_FaceList
    BC4_PointList = solver.BC4_PointList
    BC4_EdgeList = solver.BC4_EdgeList
    BC4_CenterPoint = solver.BC4_CenterPoint
    BC4_CenterAxisLines = solver.BC4_CenterAxisLines
    BC4_EdgeMidPoints = solver.BC4_EdgeMidPoints
    BC4_FacePlaneList = solver.BC4_FacePlaneList
    BC4_Corner0Planes = solver.BC4_Corner0Planes
    BC4_LocalAxesPlane = solver.BC4_LocalAxesPlane
    BC4_AxisX = solver.BC4_AxisX
    BC4_AxisY = solver.BC4_AxisY
    BC4_AxisZ = solver.BC4_AxisZ
    BC4_FaceDirTags = solver.BC4_FaceDirTags
    BC4_EdgeDirTags = solver.BC4_EdgeDirTags
    BC4_Corner0EdgeDirs = solver.BC4_Corner0EdgeDirs

    PFL7_BasePlane = solver.PFL7_BasePlane
    PFL7_OriginPoint = solver.PFL7_OriginPoint
    PFL7_ResultPlane = solver.PFL7_ResultPlane
    PFL7_Log = solver.PFL7_Log

    PFL8_BasePlane = solver.PFL8_BasePlane
    PFL8_OriginPoint = solver.PFL8_OriginPoint
    PFL8_ResultPlane = solver.PFL8_ResultPlane
    PFL8_Log = solver.PFL8_Log

    GA4_SourceOut = solver.GA4_SourceOut
    GA4_TargetOut = solver.GA4_TargetOut
    GA4_MovedGeo = solver.GA4_MovedGeo

    # -------- Step 7：乳栿劄牽切削 --------
    RFKK_OuterTool = solver.RFKK_OuterTool
    RFKK_InnerTool = solver.RFKK_InnerTool
    RFKK_OuterSection = solver.RFKK_OuterSection
    RFKK_InnerSection = solver.RFKK_InnerSection
    RFKK_RefPlanes = solver.RFKK_RefPlanes
    RFKK_EdgeMidPoints = solver.RFKK_EdgeMidPoints
    RFKK_EdgeNames = solver.RFKK_EdgeNames
    RFKK_KeyPoints = solver.RFKK_KeyPoints
    RFKK_KeyPointNames = solver.RFKK_KeyPointNames
    RFKK_EdgeCurves = solver.RFKK_EdgeCurves
    RFKK_Log = solver.RFKK_Log
    RFKK_RefPlaneNames = solver.RFKK_RefPlaneNames

    PFL9_BasePlane = solver.PFL9_BasePlane
    PFL9_OriginPoint = solver.PFL9_OriginPoint
    PFL9_ResultPlane = solver.PFL9_ResultPlane
    PFL9_Log = solver.PFL9_Log

    GA5_SourceOut = solver.GA5_SourceOut
    GA5_TargetOut = solver.GA5_TargetOut
    GA5_MovedGeo = solver.GA5_MovedGeo

    # -------- Step 8：令栱切削 --------
    BC5_TimberBrep = solver.BC5_TimberBrep
    BC5_FaceList = solver.BC5_FaceList
    BC5_PointList = solver.BC5_PointList
    BC5_EdgeList = solver.BC5_EdgeList
    BC5_CenterPoint = solver.BC5_CenterPoint
    BC5_CenterAxisLines = solver.BC5_CenterAxisLines
    BC5_EdgeMidPoints = solver.BC5_EdgeMidPoints
    BC5_FacePlaneList = solver.BC5_FacePlaneList
    BC5_Corner0Planes = solver.BC5_Corner0Planes
    BC5_LocalAxesPlane = solver.BC5_LocalAxesPlane
    BC5_AxisX = solver.BC5_AxisX
    BC5_AxisY = solver.BC5_AxisY
    BC5_AxisZ = solver.BC5_AxisZ
    BC5_FaceDirTags = solver.BC5_FaceDirTags
    BC5_EdgeDirTags = solver.BC5_EdgeDirTags
    BC5_Corner0EdgeDirs = solver.BC5_Corner0EdgeDirs

    PFL10_BasePlane = solver.PFL10_BasePlane
    PFL10_OriginPoint = solver.PFL10_OriginPoint
    PFL10_ResultPlane = solver.PFL10_ResultPlane
    PFL10_Log = solver.PFL10_Log

    PFL11_BasePlane = solver.PFL11_BasePlane
    PFL11_OriginPoint = solver.PFL11_OriginPoint
    PFL11_ResultPlane = solver.PFL11_ResultPlane
    PFL11_Log = solver.PFL11_Log

    GA6_SourceOut = solver.GA6_SourceOut
    GA6_TargetOut = solver.GA6_TargetOut
    GA6_MovedGeo = solver.GA6_MovedGeo

    # -------- Step 9：卷殺和最终裁切 --------
    JS_ToolBrep = solver.JS_ToolBrep
    JS_SectionEdges = solver.JS_SectionEdges
    JS_HL_Intersection = solver.JS_HL_Intersection
    JS_HeightFacePlane = solver.JS_HeightFacePlane
    JS_LengthFacePlane = solver.JS_LengthFacePlane
    JS_Log = solver.JS_Log

    PFL12_BasePlane = solver.PFL12_BasePlane
    PFL12_OriginPoint = solver.PFL12_OriginPoint
    PFL12_ResultPlane = solver.PFL12_ResultPlane
    PFL12_Log = solver.PFL12_Log

    GA7_SourceOut = solver.GA7_SourceOut
    GA7_TargetOut = solver.GA7_TargetOut
    GA7_MovedGeo = solver.GA7_MovedGeo

    FinalCutTimbers = solver.FinalCutTimbers
    FinalFailTimbers = solver.FinalFailTimbers
    FinalCutLog = solver.FinalCutLog



# -*- coding: utf-8 -*-
"""
SiPU_INOUT_1ChaoJuantou_ComponentAssemblySolver.py

【当前实现进度】
- Step 1：读取数据库（DBJsonReader）
- Step 2：叠级1-櫨枓（LuDou / LUDouSolver） + 对位（VSG1_GA_Ludou / GeoAligner_xfm）
- Step 3：叠级2-泥道栱 + 華栱（NiDaoGong/HuaGong） + 对位（VSG2_GA_* / GeoAligner_xfm）
- Step 4：叠级3-交互枓 + 散枓（JiaoHuDou/SanDou） + PlaneFromLists + 对位（VSG3_GA_* / GeoAligner_xfm）
- Step 5：叠级4-壁内慢栱 / 耍头 / 令栱 + 对位（VSG4_GA_* / GeoAligner_xfm，令栱为 Tree）
- Step 6：叠级5-散枓、交互枓部分：PlaneFromLists::5-1/5-2 + 对位（VSG5_GA_SanDou-* / VSG5_GA_JiaoHuDou-LingGong，含 Tree 广播）
- Step 7-1：叠级6-襯方頭（ChenFangTou）+ 对位（VSG6_GA_ChenFangTou）
- Step 7-2：叠级6-橑檐方（LaoYanFang-6）+ PlaneFromLists::6-1 + 对位（VSG6_GA_LaoYanFang）
- Step 7-3：叠级6-平基方 / 柱头方（Timber-6）+ 对位（VSG6_GA_PingJiFang / VSG6_GA_ZhuTouFang）
- 输出：ComponentAssembly（包含 Step2~Step7-3 的对位结果） + Log
- 其余中间变量全部保留为 Solver 成员变量，便于后续逐步把更多部件串进来

输入（当前仅三项，后续按步骤再加）：
    DBPath     : str   SQLite 数据库路径
    PlacePlane : Plane 放置参考平面（默认 GH XY Plane，原点(100,100,0)）
    Refresh    : bool  刷新按钮，True 时清空输出并清 sticky 缓存

数据库读取约定（与要求一致）：
- Table    = "PuZuo"
- KeyField = "type_code"
- KeyValue = "SiPU_INOUT_1ChaoJuantou"
- Field    = "params_json"
- ExportAll= True

注意：
- 参数优先级：组件输入端 > 数据库 > 默认值（当前步骤仅 PlacePlane/Refresh 属于输入端）
- 处理输出端嵌套 List`1[Object]：对最终 ComponentAssembly 做递归拍平
"""

from __future__ import print_function, division

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    LUDouSolver,
    GeoAligner_xfm,
    NiDaoGong_4PU_INOUT_1ChaoJuantou_Solver,
    ChaAngWithHuaGong4PUSolver,
    JiaoHuDouSolver,
    JIAOHU_DOU_doukoutiaoSolver,
    QiAngDouSolver,
    SanDouSolver,
    FTPlaneFromLists,
    BiNeiManGongSolver,
    ShuaTou_4PU_INOUT_1ChaoJuantouSolver,
    LingGong_4PU_INOUT_1ChaoJuantouChongGSolver,
    ChenFangTouSolver,
    RuFangEaveToolBuilder,
    build_timber_block_uniform,
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.11-sipu-chaang-infillpu"


# =========================================================
# 通用工具函数（参考 ChongGongComponentAssemblySolver.py 的风格）
# =========================================================

def _default_place_plane():
    """默认放置平面：GH 的 XY Plane，原点为 (100,100,0)。"""
    pl = rg.Plane.WorldXY
    pl.Origin = rg.Point3d(100.0, 100.0, 0.0)
    return pl


def _ensure_list(x):
    """把 None/单值/tuple/list 统一成 list（不做深度拍平）。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    return [x]


def _broadcast_pair(a_list, b_list):
    """
    将两个 list 广播到同一长度（仿 GH 一对多/多对多广播）。
    规则：
    - 若两者长度相同：直接返回
    - 若其中一个长度为 1：复制到另一个长度
    - 若其中一个为空：用另一个的长度（空则返回 0）
    - 其他不匹配：截断到 min(lenA,lenB)（尽量不炸组件）
    返回：(a_out, b_out, n)
    """
    a = _ensure_list(a_list)
    b = _ensure_list(b_list)
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return [], [], 0
    if la == 0:
        return [0] * lb, b, lb
    if lb == 0:
        return a, [0] * la, la
    if la == lb:
        return a, b, la
    if la == 1 and lb > 1:
        return a * lb, b, lb
    if lb == 1 and la > 1:
        return a, b * la, la
    n = min(la, lb)
    return a[:n], b[:n], n


def _broadcast_to(seq, n, fill=None):
    """把 seq（任意：None/标量/list/tuple）广播到长度 n（仿 GH）。"""
    s = _ensure_list(seq)
    if n <= 0:
        return []
    if len(s) == 0:
        return [fill] * n
    if len(s) == n:
        return s
    if len(s) == 1 and n > 1:
        return s * n
    # 不匹配且非 1：截断/补齐（补齐用最后一个）
    if len(s) > n:
        return s[:n]
    return s + [s[-1]] * (n - len(s))


# --- scalar coercion helpers (GH Item-like) ---
def _first_or_self(x):
    """GH Item 输入若为 list/tuple，则取第一个；否则返回自身。None 保持 None。"""
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return x[0] if len(x) > 0 else None
    return x


def _as_float(x, default=None):
    """安全转 float：None -> default；list/tuple -> 取第一个；失败 -> default。"""
    v = _first_or_self(x)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _as_int(x, default=None):
    """安全转 int：None -> default；list/tuple -> 取第一个；失败 -> default。"""
    v = _first_or_self(x)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return default


def _as_bool(x, default=None):
    """安全转 bool：None -> default；list/tuple -> 取第一个；支持字符串 true/false/1/0。"""
    v = _first_or_self(x)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, (str, bytes)):
        s = v.decode("utf-8", "ignore") if isinstance(v, bytes) else v
        s = s.strip().lower()
        if s in ("true", "t", "yes", "y", "1", "on"):
            return True
        if s in ("false", "f", "no", "n", "0", "off"):
            return False
    # fallback：Python 的 truthy 规则
    try:
        return bool(v)
    except Exception:
        return default


def _unwrap_first(x):
    """把 GH Tree/嵌套 list/tuple 逐层取第一个元素，直到遇到非 list/tuple 或空。"""
    while isinstance(x, (list, tuple)):
        if len(x) == 0:
            return None
        x = x[0]
    return x


def _as_tree_branches(x):
    """把输入规范为 GH Tree 的 branches 结构: [[item],[item],...]."""
    if x is None:
        return [[None]]
    if isinstance(x, (list, tuple)):
        # tree-like
        if len(x) > 0 and all(isinstance(b, (list, tuple)) for b in x):
            out = []
            for b in x:
                out.append([_unwrap_first(b)])
            return out if len(out) > 0 else [[None]]
        # list-like
        return [[_unwrap_first(v)] for v in x] if len(x) > 0 else [[None]]
    return [[x]]


def _broadcast_tree(x, n_branches):
    """GH 风格：若只有 1 个分支，则广播到 n_branches；否则按分支对应截取/补齐。"""
    b = _as_tree_branches(x)
    if len(b) == 0:
        b = [[None]]
    if len(b) == 1 and n_branches > 1:
        return [b[0] for _ in range(n_branches)]
    if len(b) >= n_branches:
        return b[:n_branches]
    last = b[-1]
    return b + [last for _ in range(n_branches - len(b))]


def _broadcast_tree_item(x, n_branches, default=None):
    """将输入 x 归一化为 GH Tree(分支数=n_branches)，且每个分支只有 1 个值。
    规则（贴近 GH 的“分支对应 + 单值广播”语义）：
      - x 为 None -> 全部分支为 default
      - x 为标量 -> 广播到所有分支
      - x 为 list/tuple:
          * 若形如 [[a],[b]] -> 取每分支第一个元素
          * 若形如 [[a,b]] 且 n_branches=2 -> 视为单分支多值，按索引拆成 {0}=a,{1}=b
          * 若形如 [a,b] -> 视为多值，按索引拆成分支
          * 若仅 1 个值 -> 广播
    返回格式：[[v0],[v1],...]
    """
    # None
    if x is None:
        return [[default] for _ in range(n_branches)]

    # 识别“分支”结构
    branches = None
    items = None
    if isinstance(x, (list, tuple)):
        if len(x) > 0 and all(isinstance(e, (list, tuple)) for e in x):
            branches = list(x)
        else:
            items = list(x)
    else:
        items = [x]

    vals = []

    if branches is not None:
        # 多分支
        if len(branches) == 0:
            vals = [default] * n_branches
        elif len(branches) == n_branches:
            for br in branches:
                if br is None or len(br) == 0:
                    vals.append(default)
                else:
                    vals.append(br[0])
        elif len(branches) == 1:
            br = branches[0] if branches[0] is not None else []
            # 单分支多值：可拆分
            if isinstance(br, (list, tuple)) and len(br) >= n_branches:
                vals = [br[i] for i in range(n_branches)]
            else:
                v = br[0] if isinstance(br, (list, tuple)) and len(br) > 0 else default
                vals = [v] * n_branches
        else:
            # 分支数不匹配：按序取，缺的用最后一个分支广播
            for i in range(n_branches):
                br = branches[i] if i < len(branches) else branches[-1]
                if br is None or len(br) == 0:
                    vals.append(default)
                else:
                    vals.append(br[0])
    else:
        # 非分支：按 items 处理
        if items is None:
            items = [x]
        if len(items) == 0:
            vals = [default] * n_branches
        elif len(items) >= n_branches:
            vals = items[:n_branches]
        elif len(items) == 1:
            vals = [items[0]] * n_branches
        else:
            vals = list(items) + [items[-1] for _ in range(n_branches - len(items))]

    return [[v] for v in vals]


def _flatten_items(x, out_list):
    """递归拍平 list/tuple（用于避免 GH 输出 List`1[Object] 嵌套）。"""
    if x is None:
        return
    if isinstance(x, (list, tuple)):
        for it in x:
            _flatten_items(it, out_list)
    else:
        out_list.append(x)


def _pick_nth_from_tree(tree_like, n=0):
    """从 GH Tree-like（list of branches / list）中取第 n 个元素（按拍平顺序）。"""
    if tree_like is None:
        return None
    flat = []
    try:
        _flatten_items(tree_like, flat)
    except Exception:
        flat = _ensure_list(tree_like)
    if n < 0:
        return None
    if len(flat) == 0:
        return None
    if n >= len(flat):
        return flat[-1]
    return flat[n]


def _as_int(val, default=0):
    """尽量将输入转换为 int。"""
    try:
        if val is None:
            return int(default)
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, int):
            return int(val)
        if isinstance(val, float):
            return int(round(val))
        if isinstance(val, str):
            s = val.strip()
            if s == '':
                return int(default)
            return int(float(s))
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_int(val[0], default)
    except:
        pass
    return int(default)


def _as_float_or_list(x, default=0.0):
    """标量 -> float；list/tuple -> list[float]"""
    if x is None:
        return default
    if isinstance(x, (list, tuple)):
        if len(x) == 0:
            return []
        out = []
        for v in x:
            try:
                out.append(float(v))
            except:
                out.append(float(default))
        return out
    try:
        return float(x)
    except:
        return float(default)


def _as_01(x, default=0):
    """将 flip 值统一到 0/1"""
    try:
        if isinstance(x, (list, tuple)):
            x = x[0] if len(x) else default
        if isinstance(x, bool):
            return 1 if x else 0
        if isinstance(x, (int, float)):
            return 1 if float(x) != 0.0 else 0
        if isinstance(x, str):
            s = x.strip().lower()
            if s in ("1", "true", "t", "yes", "y", "on"):
                return 1
            if s in ("0", "false", "f", "no", "n", "off", ""):
                return 0
    except:
        pass
    return int(default)


def _as_01_or_list(x, default=0):
    """标量 -> 0/1；list/tuple -> list[0/1]"""
    if x is None:
        return default
    if isinstance(x, (list, tuple)):
        if len(x) == 0:
            return []
        return [_as_01(v, default) for v in x]
    return _as_01(x, default)


def _pick_by_index(seq, idx, default=None):
    """从 list/tuple 中按 idx 取元素；越界返回 default。"""
    if seq is None:
        return default
    if not isinstance(seq, (list, tuple)):
        return seq
    if len(seq) == 0:
        return default
    i = int(idx)
    if i < 0 or i >= len(seq):
        return default
    return seq[i]


def _transform_planes(planes, xform):
    """将 Plane 列表应用 Transform（None 安全）。"""
    if planes is None:
        return []
    # GH 行为：Transform 输入可能是单个 Transform，也可能是 list/tree。
    # 本函数用于“把一组 Plane 作为 Geometry 输入 Transform”，通常期望使用同一个 Transform。
    # 若传入 list/tuple，则取第一个（与 GH 常见的 item->list 广播行为一致）。
    if isinstance(xform, (list, tuple)):
        xform = xform[0] if len(xform) > 0 else None
    if xform is None:
        return list(planes) if isinstance(planes, (list, tuple)) else [planes]
    out = []
    if isinstance(planes, (list, tuple)):
        for pl in planes:
            try:
                if isinstance(pl, rg.Plane):
                    p2 = rg.Plane(pl)
                    p2.Transform(xform)
                    out.append(p2)
                else:
                    out.append(pl)
            except:
                out.append(pl)
    else:
        out.append(planes)
    return out


def _transform_points(pts, xform):
    """将 Point3d 列表应用 Transform（None 安全）。"""
    if pts is None:
        return []
    if isinstance(xform, (list, tuple)):
        xform = xform[0] if len(xform) > 0 else None
    if xform is None:
        return list(pts) if isinstance(pts, (list, tuple)) else [pts]
    out = []
    if isinstance(pts, (list, tuple)):
        for p in pts:
            try:
                if isinstance(p, rg.Point3d):
                    p2 = rg.Point3d(p)
                    p2.Transform(xform)
                    out.append(p2)
                else:
                    out.append(p)
            except:
                out.append(p)
    else:
        out.append(pts)
    return out


def _as_int_list(x):
    """把 int/float/str 或 list/tuple 转为 list[int]；None -> []"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [_as_int(v, 0) for v in x]
    return [_as_int(x, 0)]


# =========================================================
# Solver 主类（逐步实现）
# =========================================================

class SiPU_ChaAng_InfillPUComponentAssemblySolver(object):

    def __init__(self, DBPath, PlacePlane=None, Refresh=False, ghenv=None, EnableChenBu=True):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = bool(Refresh)
        self.ghenv = ghenv

        # =========================================================
        # Step 9：襯補计算开关
        #   - True : 计算并把结果追加到 ComponentAssembly
        #   - False: 不计算、不追加（输出保持 None）
        # =========================================================
        try:
            self.EnableChenBu = bool(EnableChenBu)
        except Exception:
            self.EnableChenBu = True

        # ---- Step 1 outputs ----
        self.Value = None
        self.All = None
        self.All_dict = None
        self.DBLog = None

        # ---- Step 2: LuDou solver outputs (全部保留) ----
        self.LUDou_solver = None

        self.LUDou_Value = None
        self.LUDou_All = None
        self.LUDou_All_dict = None

        self.LUDou_TimberBrep = None
        self.LUDou_FaceList = None
        self.LUDou_PointList = None
        self.LUDou_EdgeList = None
        self.LUDou_CenterPoint = None
        self.LUDou_CenterAxisLines = None
        self.LUDou_EdgeMidPoints = None
        self.LUDou_FacePlaneList = None
        self.LUDou_Corner0Planes = None
        self.LUDou_LocalAxesPlane = None
        self.LUDou_AxisX = None
        self.LUDou_AxisY = None
        self.LUDou_AxisZ = None
        self.LUDou_FaceDirTags = None
        self.LUDou_EdgeDirTags = None
        self.LUDou_Corner0EdgeDirs = None

        self.LUDou_BasePlane1 = None
        self.LUDou_OriginPoint1 = None
        self.LUDou_ResultPlane1 = None

        self.LUDou_BasePlane2 = None
        self.LUDou_OriginPoint2 = None
        self.LUDou_ResultPlane2 = None

        self.LUDou_BasePlane3 = None
        self.LUDou_OriginPoint3 = None
        self.LUDou_ResultPlane3 = None

        self.LUDou_ToolBrep = None
        self.LUDou_BasePoint = None
        self.LUDou_BaseLine = None
        self.LUDou_SecPlane = None
        self.LUDou_FacePlane = None

        self.LUDou_AlignedTool = None
        self.LUDou_XForm = None
        self.LUDou_SourcePlane = None
        self.LUDou_TargetPlane = None
        self.LUDou_SourcePoint = None
        self.LUDou_TargetPoint = None
        self.LUDou_DebugInfo = None

        self.LUDou_BlockTimbers = None

        self.LUDou_AlignedTool2 = None
        self.LUDou_XForm2 = None
        self.LUDou_SourcePlane2 = None
        self.LUDou_TargetPlane2 = None
        self.LUDou_SourcePoint2 = None
        self.LUDou_TargetPoint2 = None
        self.LUDou_DebugInfo2 = None

        self.LUDou_CutTimbers = None
        self.LUDou_FailTimbers = None
        self.LUDou_Log = None

        # ---- Step 2b: VSG1_GA_Ludou outputs ----
        self.VSG1_SourceOut = None
        self.VSG1_TargetOut = None
        self.VSG1_XFormRaw = None  # Rhino.Geometry.Transform（供后续步骤复用）
        self.VSG1_TransformOut = None
        self.VSG1_MovedGeo = None

        # ---- Step 3: NiDaoGong / HuaGong solvers outputs（必要字段 + developer-friendly 保留） ----
        self.NiDaoGong_solver = None
        self.NiDaoGong_CutTimbers = None
        self.NiDaoGong_FailTimbers = None
        self.NiDaoGong_FacePlaneList = None
        self.NiDaoGong_Log = None

        self.VSG2_NiDaoGong_SourceOut = None
        self.VSG2_NiDaoGong_TargetOut = None
        self.VSG2_NiDaoGong_XFormRaw = None
        self.VSG2_NiDaoGong_TransformOut = None
        self.VSG2_NiDaoGong_MovedGeo = None

        self.HuaGong_solver = None
        self.HuaGong_CutTimbers = None
        self.HuaGong_FailTimbers = None
        self.HuaGong_FacePlaneList = None
        self.HuaGong_Log = None

        self.VSG2_HuaGong_SourceOut = None
        self.VSG2_HuaGong_TargetOut = None
        self.VSG2_HuaGong_XFormRaw = None
        self.VSG2_HuaGong_TransformOut = None
        self.VSG2_HuaGong_MovedGeo = None

        # ---- Step 4: JiaoHuDou / SanDou + PlaneFromLists + VSG3 outputs ----
        self.JiaoHuDou_solver = None
        self.JiaoHuDou_CutTimbers = None
        self.JiaoHuDou_FailTimbers = None
        self.JiaoHuDou_FacePlaneList = None
        self.JiaoHuDou_Log = None

        # PlaneFromLists::3-1（基于 HuaGong 的变换后 EdgeMidPoints/Corner0Planes）
        self.PFL3_1_OriginPoints = None
        self.PFL3_1_BasePlanes = None
        self.PFL3_1_BasePlane = None
        self.PFL3_1_OriginPoint = None
        self.PFL3_1_ResultPlane = None
        self.PFL3_1_Log = None

        # VSG3_GA_JiaoHuDou
        self.VSG3_JiaoHuDou_SourceOut = None
        self.VSG3_JiaoHuDou_TargetOut = None
        self.VSG3_JiaoHuDou_XFormRaw = None
        self.VSG3_JiaoHuDou_TransformOut = None
        self.VSG3_JiaoHuDou_MovedGeo = None

        self.SanDou_solver = None
        self.SanDou_CutTimbers = None
        self.SanDou_FailTimbers = None
        self.SanDou_FacePlaneList = None
        self.SanDou_Log = None

        # PlaneFromLists::3-2（基于 NiDaoGong 的变换后 EdgeMidPoints/Corner0Planes）
        self.PFL3_2_OriginPoints = None
        self.PFL3_2_BasePlanes = None
        self.PFL3_2_BasePlane = None
        self.PFL3_2_OriginPoint = None
        self.PFL3_2_ResultPlane = None
        self.PFL3_2_Log = None

        # VSG3_GA_SanDou
        self.VSG3_SanDou_SourceOut = None
        self.VSG3_SanDou_TargetOut = None
        self.VSG3_SanDou_XFormRaw = None
        self.VSG3_SanDou_TransformOut = None
        self.VSG3_SanDou_MovedGeo = None

        # ---- Step 5: BiNeiManGong / ShuaTou / LingGong + VSG4 outputs ----
        self.BiNeiManGong_solver = None
        self.BiNeiManGong_CutTimbers = None
        self.BiNeiManGong_FailTimbers = None
        self.BiNeiManGong_FacePlaneList = None
        self.BiNeiManGong_CutTimbersPlusAnZhi = None
        self.BiNeiManGong_Log = None

        self.VSG4_BiNeiManGong_SourceOut = None
        self.VSG4_BiNeiManGong_TargetOut = None
        self.VSG4_BiNeiManGong_XFormRaw = None
        self.VSG4_BiNeiManGong_TransformOut = None
        self.VSG4_BiNeiManGong_MovedGeo = None
        self.VSG4_BiNeiManGong_TargetPlanePicked = None

        self.ShuaTou_solver = None
        self.ShuaTou_CutTimbers = None
        self.ShuaTou_FailTimbers = None
        self.ShuaTou_FacePlaneList = None
        self.ShuaTou_Log = None

        self.VSG4_ShuaTou_SourceOut = None
        self.VSG4_ShuaTou_TargetOut = None
        self.VSG4_ShuaTou_XFormRaw = None
        self.VSG4_ShuaTou_TransformOut = None
        self.VSG4_ShuaTou_MovedGeo = None

        self.LingGong_solver = None
        self.LingGong_CutTimbers = None
        self.LingGong_FailTimbers = None
        self.LingGong_FacePlaneList = None
        self.LingGong_Log = None

        # VSG4_GA_LingGong（注意：TransformOut 可能为 tree，因此这里保留 tree 结构）
        self.VSG4_LingGong_SourceOut = None
        self.VSG4_LingGong_TargetOut = None
        self.VSG4_LingGong_XFormRaw = None
        self.VSG4_LingGong_TransformOut = None
        self.VSG4_LingGong_MovedGeo = None
        self.VSG4_LingGong_TargetPlaneTree = None

        # ---- Step 5 extra (for Step6 PlaneFromLists Transform inputs) ----
        self.BiNeiManGong_EdgeMidPoints = None
        self.BiNeiManGong_Corner0Planes = None
        self.LingGong_EdgeMidPoints = None
        self.LingGong_Corner0Planes = None

        # ---- Step 6: 叠级5 - 散枓/交互枓（新增） ----
        # PlaneFromLists::5-1（基于 LingGong EdgeMidPoints/Corner0Planes，经 VSG4_LingGong Transform tree）
        self.PFL5_1_OriginPointsTree = None
        self.PFL5_1_BasePlanesTree = None
        self.PFL5_1_BasePlane = None
        self.PFL5_1_OriginPoint = None
        self.PFL5_1_ResultPlane = None
        self.PFL5_1_Log = None

        # VSG5_GA_SanDou-LingGong
        self.VSG5_SanDou_LingGong_SourceOut = None
        self.VSG5_SanDou_LingGong_TargetOut = None
        self.VSG5_SanDou_LingGong_XFormRaw = None
        self.VSG5_SanDou_LingGong_TransformOut = None
        self.VSG5_SanDou_LingGong_MovedGeo = None

        # PlaneFromLists::5-2（基于 BiNeiManGong EdgeMidPoints/Corner0Planes，经 VSG4_BiNeiManGong Transform）
        self.PFL5_2_OriginPoints = None
        self.PFL5_2_BasePlanes = None
        self.PFL5_2_BasePlane = None
        self.PFL5_2_OriginPoint = None
        self.PFL5_2_ResultPlane = None
        self.PFL5_2_Log = None

        # VSG5_GA_SanDou-BiNeiManGong
        self.VSG5_SanDou_BiNeiManGong_SourceOut = None
        self.VSG5_SanDou_BiNeiManGong_TargetOut = None
        self.VSG5_SanDou_BiNeiManGong_XFormRaw = None
        self.VSG5_SanDou_BiNeiManGong_TransformOut = None
        self.VSG5_SanDou_BiNeiManGong_MovedGeo = None

        # Jiaohudou-DouKouTiao solver + VSG5_GA_JiaoHuDou-LingGong（Tree）
        self.JiaoHuDou_DouKouTiao_solver = None
        self.JiaoHuDou_DouKouTiao_CutTimbers = None
        self.JiaoHuDou_DouKouTiao_FailTimbers = None
        self.JiaoHuDou_DouKouTiao_FacePlaneList = None
        self.JiaoHuDou_DouKouTiao_Log = None

        self.VSG5_JiaoHuDou_LingGong_SourceOut = None
        self.VSG5_JiaoHuDou_LingGong_TargetOut = None
        self.VSG5_JiaoHuDou_LingGong_XFormRaw = None
        self.VSG5_JiaoHuDou_LingGong_TransformOut = None
        self.VSG5_JiaoHuDou_LingGong_MovedGeo = None
        self.VSG5_JiaoHuDou_LingGong_TargetPlaneTree = None

        # ---- Step7-1: ChenFangTou + VSG6 ----
        self.ChenFangTou_solver = None
        self.ChenFangTou_CutTimbers = None
        self.ChenFangTou_FailTimbers = None
        self.ChenFangTou_FacePlaneList = None
        self.ChenFangTou_Log = None

        self.VSG6_SourceOut = None
        self.VSG6_TargetOut = None
        self.VSG6_XFormRaw = None
        self.VSG6_TransformOut = None
        self.VSG6_MovedGeo = None

        # ------------------------------------------------------------
        # Step 7-2: 橑檐方（LaoYanFang-6）+ PlaneFromLists::6-1 + VSG6_GA_LaoYanFang
        # ------------------------------------------------------------
        self.LaoYanFang6_EveTool = None
        self.LaoYanFang6_Section = None
        self.LaoYanFang6_SectionVertices = None
        self.LaoYanFang6_SectionVertexNames = None
        self.LaoYanFang6_RectEdgeMidPoints = None
        self.LaoYanFang6_RectEdgeNames = None
        self.LaoYanFang6_RefPlaneList = None
        self.LaoYanFang6_RefPlaneNames = None
        self.LaoYanFang6_Log = None

        self.PFL6_1_BasePlane = None
        self.PFL6_1_OriginPoint = None
        self.PFL6_1_ResultPlane = None
        self.PFL6_1_Log = None

        self.VSG6_LaoYanFang_SourceOut = None
        self.VSG6_LaoYanFang_TargetOut = None
        self.VSG6_LaoYanFang_XFormRaw = None
        self.VSG6_LaoYanFang_TransformOut = None
        self.VSG6_LaoYanFang_MovedGeo = None

        # ------------------------------------------------------------
        # Step 7-3: Timber-6（木料）+ VSG6_GA_PingJiFang / VSG6_GA_ZhuTouFang
        # ------------------------------------------------------------
        self.Timber6_TimberBrep = None
        self.Timber6_FaceList = None
        self.Timber6_PointList = None
        self.Timber6_EdgeList = None
        self.Timber6_CenterPoint = None
        self.Timber6_CenterAxisLines = None
        self.Timber6_EdgeMidPoints = None
        self.Timber6_FacePlaneList = None
        self.Timber6_Corner0Planes = None
        self.Timber6_LocalAxesPlane = None
        self.Timber6_AxisX = None
        self.Timber6_AxisY = None
        self.Timber6_AxisZ = None
        self.Timber6_FaceDirTags = None
        self.Timber6_EdgeDirTags = None
        self.Timber6_Corner0EdgeDirs = None
        self.Timber6_Log = None
        self.VSG6_PingJiFang_SourceOut = None
        self.VSG6_PingJiFang_TargetOut = None
        self.VSG6_PingJiFang_XFormRaw = None
        self.VSG6_PingJiFang_TransformOut = None
        self.VSG6_PingJiFang_MovedGeo = None
        self.VSG6_ZhuTouFang_SourceOut = None
        self.VSG6_ZhuTouFang_TargetOut = None
        self.VSG6_ZhuTouFang_XFormRaw = None
        self.VSG6_ZhuTouFang_TransformOut = None
        self.VSG6_ZhuTouFang_MovedGeo = None

        # ---- Step 8: Timber-7 / Cube / NiuJiFang（全部保留，便于调试） ----
        self.Timber7_TimberBrep = None
        self.Timber7_FaceList = None
        self.Timber7_PointList = None
        self.Timber7_EdgeList = None
        self.Timber7_CenterPoint = None
        self.Timber7_CenterAxisLines = None
        self.Timber7_EdgeMidPoints = None
        self.Timber7_FacePlaneList = None
        self.Timber7_Corner0Planes = None
        self.Timber7_LocalAxesPlane = None
        self.Timber7_AxisX = None
        self.Timber7_AxisY = None
        self.Timber7_AxisZ = None
        self.Timber7_FaceDirTags = None
        self.Timber7_EdgeDirTags = None
        self.Timber7_Corner0EdgeDirs = None
        self.Timber7_Log = None

        self.VSG7_Cube1_SourceOut = None
        self.VSG7_Cube1_TargetOut = None
        self.VSG7_Cube1_XFormRaw = None
        self.VSG7_Cube1_TransformOut = None
        self.VSG7_Cube1_MovedGeo = None

        self.PFL7_1_OriginPoints = None
        self.PFL7_1_BasePlanes = None
        self.PFL7_1_BasePlane = None
        self.PFL7_1_OriginPoint = None
        self.PFL7_1_ResultPlane = None
        self.PFL7_1_Log = None

        self.VSG7_Cube2_SourceOut = None
        self.VSG7_Cube2_TargetOut = None
        self.VSG7_Cube2_XFormRaw = None
        self.VSG7_Cube2_TransformOut = None
        self.VSG7_Cube2_MovedGeo = None

        self.LaoYanFang7_EveTool = None
        self.LaoYanFang7_Section = None
        self.LaoYanFang7_SectionVertices = None
        self.LaoYanFang7_SectionVertexNames = None
        self.LaoYanFang7_RectEdgeMidPoints = None
        self.LaoYanFang7_RectEdgeNames = None
        self.LaoYanFang7_RefPlaneList = None
        self.LaoYanFang7_RefPlaneNames = None
        self.LaoYanFang7_Log = None

        self.PFL7_2_BasePlane = None
        self.PFL7_2_OriginPoint = None
        self.PFL7_2_ResultPlane = None
        self.PFL7_2_Log = None

        self.VSG7_NiuJiFang_SourceOut = None
        self.VSG7_NiuJiFang_TargetOut = None
        self.VSG7_NiuJiFang_XFormRaw = None
        self.VSG7_NiuJiFang_TransformOut = None
        self.VSG7_NiuJiFang_MovedGeo = None
        self.ComponentAssembly = None
        self.Log = []

    # -------------------------
    # Step 0: Refresh 清理
    # -------------------------
    def _handle_refresh(self):
        if not self.Refresh:
            return

        comp = self.ghenv.Component if self.ghenv is not None else None
        if comp is not None:
            for p in comp.Params.Output:
                try:
                    p.VolatileData.Clear()
                except:
                    pass

            key = "SiPU_INOUT_1ChaoJuantou_CA_CACHE_{}".format(comp.InstanceGuid)
            if key in sc.sticky:
                del sc.sticky[key]

        self.Log.append(u"[Refresh] Cleared outputs & sticky cache.")

    # -------------------------
    # Step 1: 读库
    # -------------------------
    def step1_read_db(self):
        self.Log.append(u"[Step1] Read DBJsonReader (PuZuo / type_code=SiPU_ChaAng_InfillPU).")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="PuZuo",
            key_field="type_code",
            key_value="SiPU_ChaAng_InfillPU",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value, self.All, self.DBLog = reader.run()

        # All -> dict（注意：All 是 (key, val) 的 list）
        d = {}
        try:
            if self.All is not None:
                for kv in self.All:
                    if not isinstance(kv, (list, tuple)) or len(kv) < 2:
                        continue
                    d[kv[0]] = kv[1]
        except:
            pass

        self.All_dict = d
        self.Log.append(u"[Step1] All count = {}".format(len(d)))

        if self.DBLog:
            try:
                self.Log.extend(_ensure_list(self.DBLog))
            except:
                pass

    # -------------------------
    # Step 2: 櫨枓 + 对位
    # -------------------------
    def step2_ludou_and_align(self):
        self.Log.append(u"[Step2] Build LuDou via LUDouSolver, then align to PlacePlane.")

        # 2.1 LuDou（base_point 当前未作为组件输入端：按你的 step2 说明，默认原点）
        base_point = rg.Point3d(0, 0, 0)

        self.LUDou_solver = LUDouSolver(self.DBPath, base_point, self.ghenv).run()

        s = self.LUDou_solver
        # DB 相关
        self.LUDou_Value = getattr(s, "Value", None)
        self.LUDou_All = getattr(s, "All", None)
        self.LUDou_All_dict = getattr(s, "All_dict", None)

        # 主木坯
        self.LUDou_TimberBrep = getattr(s, "TimberBrep", None)
        self.LUDou_FaceList = getattr(s, "FaceList", None)
        self.LUDou_PointList = getattr(s, "PointList", None)
        self.LUDou_EdgeList = getattr(s, "EdgeList", None)
        self.LUDou_CenterPoint = getattr(s, "CenterPoint", None)
        self.LUDou_CenterAxisLines = getattr(s, "CenterAxisLines", None)
        self.LUDou_EdgeMidPoints = getattr(s, "EdgeMidPoints", None)
        self.LUDou_FacePlaneList = getattr(s, "FacePlaneList", None)
        self.LUDou_Corner0Planes = getattr(s, "Corner0Planes", None)
        self.LUDou_LocalAxesPlane = getattr(s, "LocalAxesPlane", None)
        self.LUDou_AxisX = getattr(s, "AxisX", None)
        self.LUDou_AxisY = getattr(s, "AxisY", None)
        self.LUDou_AxisZ = getattr(s, "AxisZ", None)
        self.LUDou_FaceDirTags = getattr(s, "FaceDirTags", None)
        self.LUDou_EdgeDirTags = getattr(s, "EdgeDirTags", None)
        self.LUDou_Corner0EdgeDirs = getattr(s, "Corner0EdgeDirs", None)

        # PlaneFromLists
        self.LUDou_BasePlane1 = getattr(s, "BasePlane1", None)
        self.LUDou_OriginPoint1 = getattr(s, "OriginPoint1", None)
        self.LUDou_ResultPlane1 = getattr(s, "ResultPlane1", None)

        self.LUDou_BasePlane2 = getattr(s, "BasePlane2", None)
        self.LUDou_OriginPoint2 = getattr(s, "OriginPoint2", None)
        self.LUDou_ResultPlane2 = getattr(s, "ResultPlane2", None)

        self.LUDou_BasePlane3 = getattr(s, "BasePlane3", None)
        self.LUDou_OriginPoint3 = getattr(s, "OriginPoint3", None)
        self.LUDou_ResultPlane3 = getattr(s, "ResultPlane3", None)

        # FT_QiAo
        self.LUDou_ToolBrep = getattr(s, "ToolBrep", None)
        self.LUDou_BasePoint = getattr(s, "BasePoint", None)
        self.LUDou_BaseLine = getattr(s, "BaseLine", None)
        self.LUDou_SecPlane = getattr(s, "SecPlane", None)
        self.LUDou_FacePlane = getattr(s, "FacePlane", None)

        # AlignToolToTimber::1
        self.LUDou_AlignedTool = getattr(s, "AlignedTool", None)
        self.LUDou_XForm = getattr(s, "XForm", None)
        self.LUDou_SourcePlane = getattr(s, "SourcePlane", None)
        self.LUDou_TargetPlane = getattr(s, "TargetPlane", None)
        self.LUDou_SourcePoint = getattr(s, "SourcePoint", None)
        self.LUDou_TargetPoint = getattr(s, "TargetPoint", None)
        self.LUDou_DebugInfo = getattr(s, "DebugInfo", None)

        # BlockCutter / AlignToolToTimber::2
        self.LUDou_BlockTimbers = getattr(s, "BlockTimbers", None)

        self.LUDou_AlignedTool2 = getattr(s, "AlignedTool2", None)
        self.LUDou_XForm2 = getattr(s, "XForm2", None)
        self.LUDou_SourcePlane2 = getattr(s, "SourcePlane2", None)
        self.LUDou_TargetPlane2 = getattr(s, "TargetPlane2", None)
        self.LUDou_SourcePoint2 = getattr(s, "SourcePoint2", None)
        self.LUDou_TargetPoint2 = getattr(s, "TargetPoint2", None)
        self.LUDou_DebugInfo2 = getattr(s, "DebugInfo2", None)

        # 切割结果
        self.LUDou_CutTimbers = getattr(s, "CutTimbers", None)
        self.LUDou_FailTimbers = getattr(s, "FailTimbers", None)
        self.LUDou_Log = getattr(s, "Log", None)

        # 2.2 VSG1_GA_Ludou（从 Step1 的 All_dict 取参数）
        # SourcePlane = LuDou.FacePlaneList[ idx ]，idx 来自 VSG1_GA_Ludou__SourcePlane
        idx = _as_int(self.All_dict.get("VSG1_GA_Ludou__SourcePlane", 0), 0)
        src_plane = _pick_by_index(self.LUDou_FacePlaneList, idx, None)

        # 参数：按“组件输入端 > 数据库 > 默认”
        # 当前 VSG1 的输入端只有 PlacePlane；其余从数据库取，不存在则给默认
        rotate_deg = _as_float_or_list(self.All_dict.get("VSG1_GA_Ludou__RotateDeg", 0.0), 0.0)
        flip_x = _as_01_or_list(self.All_dict.get("VSG1_GA_Ludou__FlipX", 0), 0)
        flip_y = _as_01_or_list(self.All_dict.get("VSG1_GA_Ludou__FlipY", 0), 0)
        flip_z = _as_01_or_list(self.All_dict.get("VSG1_GA_Ludou__FlipZ", 0), 0)
        move_x = _as_float_or_list(self.All_dict.get("VSG1_GA_Ludou__MoveX", 0.0), 0.0)
        move_y = _as_float_or_list(self.All_dict.get("VSG1_GA_Ludou__MoveY", 0.0), 0.0)
        move_z = _as_float_or_list(self.All_dict.get("VSG1_GA_Ludou__MoveZ", 0.0), 0.0)

        geo = self.LUDou_CutTimbers

        self.VSG1_SourceOut, self.VSG1_TargetOut, xform, self.VSG1_MovedGeo = GeoAligner_xfm.align(
            geo,
            src_plane,
            self.PlacePlane,
            rotate_deg=rotate_deg,
            flip_x=flip_x,
            flip_y=flip_y,
            flip_z=flip_z,
            move_x=move_x,
            move_y=move_y,
            move_z=move_z,
        )

        self.VSG1_XFormRaw = xform
        self.VSG1_TransformOut = ght.GH_Transform(xform) if xform is not None else None
        self.Log.append(u"[Step2] VSG1 aligned done. SourcePlaneIndex={}".format(idx))

    # -------------------------
    # Step 3: 泥道栱 + 華栱 + 对位（目标平面来源：LuDou FacePlaneList 经 VSG1 变换）
    # -------------------------
    def step3_nidaogong_huagong_and_align(self):
        self.Log.append(u"[Step3] Build NiDaoGong/HuaGong, then align to transformed LuDou planes.")

        base_point = rg.Point3d(0, 0, 0)

        # ---- 3.1 NiDaoGong ----
        try:
            self.NiDaoGong_solver = NiDaoGong_4PU_INOUT_1ChaoJuantou_Solver(self.DBPath, base_point, self.Refresh,
                                                                            self.ghenv).run()
        except Exception as e:
            self.NiDaoGong_solver = None
            self.Log.append(u"[Step3] NiDaoGong solver failed: {}".format(e))

        if self.NiDaoGong_solver is not None:
            s = self.NiDaoGong_solver
            self.NiDaoGong_CutTimbers = getattr(s, "CutTimbers", None)
            self.NiDaoGong_FailTimbers = getattr(s, "FailTimbers", None)
            self.NiDaoGong_FacePlaneList = getattr(s, "FacePlaneList", None)
            self.NiDaoGong_Log = getattr(s, "Log", None)

        # ---- 3.2 VSG2_GA_NiDaoGong ----
        # SourcePlane: NiDaoGong.FacePlaneList[idx]
        sp_idx = _as_int(self.All_dict.get("VSG2_GA_NiDaoGong__SourcePlane", 0), 0)
        src_plane = _pick_by_index(self.NiDaoGong_FacePlaneList, sp_idx, None)

        # TargetPlane: transform(LuDou.FacePlaneList, VSG1_XFormRaw)[idx]
        tp_idx = _as_int(self.All_dict.get("VSG2_GA_NiDaoGong__TargetPlane", 0), 0)
        ludou_planes_xf = _transform_planes(self.LUDou_FacePlaneList, self.VSG1_XFormRaw)
        tgt_plane = _pick_by_index(ludou_planes_xf, tp_idx, None)

        rotate_deg = _as_float_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__RotateDeg", 0.0), 0.0)
        flip_x = _as_01_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__FlipX", 0), 0)
        flip_y = _as_01_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__FlipY", 0), 0)
        flip_z = _as_01_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__FlipZ", 0), 0)
        move_x = _as_float_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__MoveX", 0.0), 0.0)
        move_y = _as_float_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__MoveY", 0.0), 0.0)
        move_z = _as_float_or_list(self.All_dict.get("VSG2_GA_NiDaoGong__MoveZ", 0.0), 0.0)

        try:
            self.VSG2_NiDaoGong_SourceOut, self.VSG2_NiDaoGong_TargetOut, xform2, self.VSG2_NiDaoGong_MovedGeo = GeoAligner_xfm.align(
                self.NiDaoGong_CutTimbers,
                src_plane,
                tgt_plane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )
            self.VSG2_NiDaoGong_XFormRaw = xform2
            self.VSG2_NiDaoGong_TransformOut = ght.GH_Transform(xform2) if xform2 is not None else None
            self.Log.append(u"[Step3] VSG2_NiDaoGong aligned. SP_idx={} TP_idx={}".format(sp_idx, tp_idx))
        except Exception as e:
            self.Log.append(u"[Step3] VSG2_NiDaoGong align failed: {}".format(e))

        # ---- 3.3 HuaGong（替换为 ChaAngWithHuaGong4PU） ----
        # 说明：按你的要求，用 ChaAngWithHuaGong4PU 替换原 HuaGong 组件；
        #      但本 Solver 对外仍保持 HuaGong_* 命名与输出端语义不变。
        try:
            self.HuaGong_solver = ChaAngWithHuaGong4PUSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
            self.HuaGong_solver = self.HuaGong_solver.run()
        except Exception as e:
            self.HuaGong_solver = None
            self.Log.append(u"[Step3] ChaAngWithHuaGong4PU solver failed: {}".format(e))

        if self.HuaGong_solver is not None:
            s = self.HuaGong_solver
            # 主输出（仍按 HuaGong_* 命名）
            self.HuaGong_CutTimbers = getattr(s, "CutTimbers", None)
            self.HuaGong_FailTimbers = getattr(s, "FailTimbers", None)
            self.HuaGong_Log = getattr(s, "Log", None)

            # FacePlaneList：优先取 HuaGong_FacePlaneList（ChaAngWithHuaGong4PU 暴露的端口）
            self.HuaGong_FacePlaneList = getattr(s, "HuaGong_FacePlaneList", None)
            if self.HuaGong_FacePlaneList is None:
                self.HuaGong_FacePlaneList = getattr(s, "FacePlaneList", None)

            # Step4 PlaneFromLists::3-1 仍需要 EdgeMidPoints / Corner0Planes（若缺失则退回 None）
            # Step4 PlaneFromLists::3-1 仍需要 EdgeMidPoints / Corner0Planes
            # 注意：此处运行的是 Python 版 solver，不经过 GH 组件“输出绑定区”，
            # 因此不能只依赖顶层 solver 暴露的端口名；需要从子 solver（solver_huagong）兜底取值。
            _hg_sub = getattr(s, "solver_huagong", None)

            self.HuaGong_EdgeMidPoints = (
                    getattr(s, "HuaGong_EdgeMidPoints", None)
                    or getattr(s, "EdgeMidPoints", None)
                    or (getattr(_hg_sub, "EdgeMidPoints", None) if _hg_sub is not None else None)
            )
            self.HuaGong_Corner0Planes = (
                    getattr(s, "HuaGong_Corner0Planes", None)
                    or getattr(s, "Corner0Planes", None)
                    or (getattr(_hg_sub, "Corner0Planes", None) if _hg_sub is not None else None)
            )
        # ---- 3.4 VSG2_GA_HuaGong ----
        sp_idx = _as_int(self.All_dict.get("VSG2_GA_HuaGong__SourcePlane", 0), 0)
        src_plane = _pick_by_index(self.HuaGong_FacePlaneList, sp_idx, None)

        tp_idx = _as_int(self.All_dict.get("VSG2_GA_HuaGong__TargetPlane", 0), 0)
        tgt_plane = _pick_by_index(ludou_planes_xf, tp_idx, None)

        rotate_deg = _as_float_or_list(self.All_dict.get("VSG2_GA_HuaGong__RotateDeg", 0.0), 0.0)
        flip_x = _as_01_or_list(self.All_dict.get("VSG2_GA_HuaGong__FlipX", 0), 0)
        flip_y = _as_01_or_list(self.All_dict.get("VSG2_GA_HuaGong__FlipY", 0), 0)
        flip_z = _as_01_or_list(self.All_dict.get("VSG2_GA_HuaGong__FlipZ", 0), 0)
        move_x = _as_float_or_list(self.All_dict.get("VSG2_GA_HuaGong__MoveX", 0.0), 0.0)
        move_y = _as_float_or_list(self.All_dict.get("VSG2_GA_HuaGong__MoveY", 0.0), 0.0)
        move_z = _as_float_or_list(self.All_dict.get("VSG2_GA_HuaGong__MoveZ", 0.0), 0.0)

        try:
            self.VSG2_HuaGong_SourceOut, self.VSG2_HuaGong_TargetOut, xform3, self.VSG2_HuaGong_MovedGeo = GeoAligner_xfm.align(
                self.HuaGong_CutTimbers,
                src_plane,
                tgt_plane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )
            self.VSG2_HuaGong_XFormRaw = xform3
            self.VSG2_HuaGong_TransformOut = ght.GH_Transform(xform3) if xform3 is not None else None
            self.Log.append(u"[Step3] VSG2_HuaGong aligned. SP_idx={} TP_idx={}".format(sp_idx, tp_idx))
        except Exception as e:
            self.Log.append(u"[Step3] VSG2_HuaGong align failed: {}".format(e))

    # -------------------------
    # Step 4: 交互枓 + 散枓 + PlaneFromLists + 对位（目标平面来自 NiDaoGong/HuaGong 对位后的几何参考）
    # -------------------------
    def step4_jiaohudou_sandou_and_align(self):
        self.Log.append(
            u"[Step4] Build JiaoHuDou/SanDou, compute target planes (PlaneFromLists::3-1/3-2), then align (VSG3).")

        base_point = rg.Point3d(0, 0, 0)

        # ---- 4.1 JiaoHuDou ----
        try:
            self.JiaoHuDou_solver = JiaoHuDouSolver(self.DBPath, base_point, self.Refresh)
            self.JiaoHuDou_solver.run()
        except Exception as e:
            self.JiaoHuDou_solver = None
            self.Log.append(u"[Step4] JiaoHuDou solver failed: {}".format(e))

        if self.JiaoHuDou_solver is not None:
            s = self.JiaoHuDou_solver
            self.JiaoHuDou_CutTimbers = getattr(s, "CutTimbers", None)
            self.JiaoHuDou_FailTimbers = getattr(s, "FailTimbers", None)
            self.JiaoHuDou_FacePlaneList = getattr(s, "FacePlaneList", None)
            self.JiaoHuDou_Log = getattr(s, "Log", None)

        # ---- 4.1b QiAngDou（新增） ----
        try:
            self.QiAngDou_solver = QiAngDouSolver(self.DBPath, base_point, self.Refresh)
            self.QiAngDou_solver.run()
        except Exception as e:
            self.QiAngDou_solver = None
            self.Log.append(u"[Step4] QiAngDou solver failed: {}".format(e))

        if self.QiAngDou_solver is not None:
            s = self.QiAngDou_solver
            self.QiAngDou_CutTimbers = getattr(s, "CutTimbers", None)
            self.QiAngDou_FailTimbers = getattr(s, "FailTimbers", None)
            self.QiAngDou_FacePlaneList = getattr(s, "FacePlaneList", None)
            self.QiAngDou_Log = getattr(s, "Log", None)

        # ---- 4.2 PlaneFromLists::3-1（来自 HuaGong 的 EdgeMidPoints/Corner0Planes，经 VSG2_HuaGong 变换） ----
        try:
            # 关键：PlaneFromLists::3-1 的 OriginPoints/BasePlanes 必须来自「已对位后的 HuaGong」
            # - OriginPoints : HuaGong_EdgeMidPoints 经过 VSG2_HuaGong 的 Transform
            # - BasePlanes   : HuaGong_Corner0Planes 经过 VSG2_HuaGong 的 Transform
            # 注意：替换 HuaGong -> ChaAngWithHuaGong4PU 后，这两个输出仍旧作为输入，不可断开。
            hg_edge_mid = getattr(self, "HuaGong_EdgeMidPoints", None)
            hg_corner0 = getattr(self, "HuaGong_Corner0Planes", None)

            # 若上游未生成（None），则给出空列表以避免 build_plane 直接报错；日志中会提示。
            self.PFL3_1_OriginPoints = _transform_points(hg_edge_mid, self.VSG2_HuaGong_XFormRaw)
            self.PFL3_1_BasePlanes = _transform_planes(hg_corner0, self.VSG2_HuaGong_XFormRaw)

            if (self.PFL3_1_OriginPoints is None) or (len(self.PFL3_1_OriginPoints) == 0):
                self.Log.append(u"[Step4][WARN] PFL3-1 OriginPoints is empty (HuaGong_EdgeMidPoints missing).")
            if (self.PFL3_1_BasePlanes is None) or (len(self.PFL3_1_BasePlanes) == 0):
                self.Log.append(u"[Step4][WARN] PFL3-1 BasePlanes is empty (HuaGong_Corner0Planes missing).")

            idx_o = self.All_dict.get("PlaneFromLists_3_1__IndexOrigin", 0)
            idx_p = self.All_dict.get("PlaneFromLists_3_1__IndexPlane", 0)

            # GH 广播：IndexOrigin / IndexPlane 可能为标量或列表，需对齐到同一长度
            idx_o_list, idx_p_list, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=True)
            base_planes_out, origin_pts_out, result_planes_out = [], [], []
            logs = []
            for i in range(n):
                bp_i, op_i, rp_i, lg_i = builder.build_plane(
                    self.PFL3_1_OriginPoints,
                    self.PFL3_1_BasePlanes,
                    idx_o_list[i],
                    idx_p_list[i]
                )
                base_planes_out.append(bp_i)
                origin_pts_out.append(op_i)
                result_planes_out.append(rp_i)
                if lg_i:
                    _flatten_items(lg_i, logs)

            # n==1 -> 标量；n>1 -> 列表（GH 会自动识别为 list / tree-like）
            self.PFL3_1_BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PFL3_1_OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PFL3_1_ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PFL3_1_Log = logs

            self.Log.append(u"[Step4] PlaneFromLists::3-1 built.")
        except Exception as e:
            self.Log.append(u"[Step4] PlaneFromLists::3-1 failed: {}".format(e))

        # ---- 4.3 VSG3_GA_JiaoHuDou ----
        # 按你的要求：Geo / SourcePlane / TargetPlane / RotateDeg / MoveY 为 Tree（2 个分支，每分支 1 个值）；
        # 其它输入端为 Item。
        try:
            # --- TargetPlane: PlaneFromLists::3-1 的 ResultPlane（Tree：2 分支；若单值则广播） ---
            tgt_tree_in = _broadcast_tree_item(getattr(self, 'PFL3_1_ResultPlane', None), 2, default=None)

            # --- Geo: QiAngDou.CutTimbers + JiaoHuDou.CutTimbers（Tree：2 分支，每分支 1 个对象；若为单值则广播） ---
            # 注意：CutTimbers 在 GhPython 中常见为 list（可能 len=1），这里按“每分支一个对象”要求取第一个几何（len==1）。
            qad_geo0 = _unwrap_first(getattr(self, 'QiAngDou_CutTimbers', None))
            jhd_geo0 = _unwrap_first(getattr(self, 'JiaoHuDou_CutTimbers', None))

            # 固定顺序：{0}=QiAngDou，{1}=JiaoHuDou，并保证 Geo/SourcePlane 位置对应
            geo_tree_in = [[qad_geo0], [jhd_geo0]]

            # --- SourcePlane: 来自两组件 FacePlaneList（Tree：2 分支，每分支 1 个值） ---
            # SourcePlane 索引：允许为单值或两值；单值则广播到两分支
            sp_idx_list = _broadcast_to(_as_int_list(self.All_dict.get("VSG3_GA_JiaoHuDou__SourcePlane", 0)), 2, fill=0)
            src_qad = _pick_by_index(getattr(self, 'QiAngDou_FacePlaneList', None), sp_idx_list[0], None)
            src_jhd = _pick_by_index(getattr(self, 'JiaoHuDou_FacePlaneList', None), sp_idx_list[1], None)
            src_tree_in = [[src_qad], [src_jhd]]

            # --- RotateDeg: Tree（2 分支；若单值则广播） ---
            rot_in = self.All_dict.get("VSG3_GA_JiaoHuDou__RotateDeg", 0.0)
            rot_tree_in = _broadcast_tree_item(_as_float_or_list(rot_in, 0.0), 2, default=0.0)

            # --- MoveY: Tree（2 分支；若单值则广播） ---
            movey_in = self.All_dict.get("VSG3_GA_JiaoHuDou__MoveY", 0.0)
            my_tree_in = _broadcast_tree_item(_as_float_or_list(movey_in, 0.0), 2, default=0.0)

            # --- 其它输入端（Item）：FlipX/FlipY/FlipZ/MoveX/MoveZ
            # 若输入端没有值传入（None），则保持为 None（不强行转型），以便下游按默认处理。
            fx_raw = self.All_dict.get("VSG3_GA_JiaoHuDou__FlipX", None)
            fy_raw = self.All_dict.get("VSG3_GA_JiaoHuDou__FlipY", None)
            fz_raw = self.All_dict.get("VSG3_GA_JiaoHuDou__FlipZ", None)
            mx_raw = self.All_dict.get("VSG3_GA_JiaoHuDou__MoveX", None)
            mz_raw = self.All_dict.get("VSG3_GA_JiaoHuDou__MoveZ", None)

            fx = (_as_bool(fx_raw, False) if fx_raw is not None else None)
            fy = (_as_bool(fy_raw, False) if fy_raw is not None else None)
            fz = (_as_bool(fz_raw, False) if fz_raw is not None else None)
            mx = (_as_float(mx_raw, 0.0) if mx_raw is not None else None)
            mz = (_as_float(mz_raw, 0.0) if mz_raw is not None else None)

            so_tree, to_tree, x_tree, mg_tree = [], [], [], []
            for bi in range(2):
                g = geo_tree_in[bi][0] if (geo_tree_in and bi < len(geo_tree_in) and geo_tree_in[bi]) else None
                sp = src_tree_in[bi][0] if (src_tree_in and bi < len(src_tree_in) and src_tree_in[bi]) else None
                tp = tgt_tree_in[bi][0] if (tgt_tree_in and bi < len(tgt_tree_in) and tgt_tree_in[bi]) else None
                rd = rot_tree_in[bi][0] if (rot_tree_in and bi < len(rot_tree_in) and rot_tree_in[bi]) else 0.0
                my = my_tree_in[bi][0] if (my_tree_in and bi < len(my_tree_in) and my_tree_in[bi]) else 0.0

                # GH 语义：任一关键输入为空则该分支输出 None（而不是抛异常）
                if g is None or sp is None or tp is None:
                    so_tree.append([None])
                    to_tree.append([None])
                    x_tree.append([None])
                    mg_tree.append([None])
                    continue

                so, to, xform, mg = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rd,
                    flip_x=fx,
                    flip_y=fy,
                    flip_z=fz,
                    move_x=mx,
                    move_y=my,
                    move_z=mz,
                )
                so_tree.append([so])
                to_tree.append([to])
                x_tree.append([xform])
                mg_tree.append([mg])

            # 输出保持 Tree（嵌套 list）
            self.VSG3_JiaoHuDou_SourceOut = so_tree
            self.VSG3_JiaoHuDou_TargetOut = to_tree
            self.VSG3_JiaoHuDou_XFormRaw = x_tree
            self.VSG3_JiaoHuDou_TransformOut = [[ght.GH_Transform(x[0]) if x and x[0] is not None else None] for x in
                                                x_tree]
            self.VSG3_JiaoHuDou_MovedGeo = mg_tree

            self.Log.append(u"[Step4] VSG3_JiaoHuDou aligned (Tree). SP_idx_list={} branches=2".format(sp_idx_list))
        except Exception as e:
            self.Log.append(u"[Step4] VSG3_JiaoHuDou align failed: {}".format(e))

        # ---- 4.4 SanDou ----
        try:
            self.SanDou_solver = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh,
                                              ghenv=self.ghenv)
            self.SanDou_solver.run()
        except Exception as e:
            self.SanDou_solver = None
            self.Log.append(u"[Step4] SanDou solver failed: {}".format(e))

        if self.SanDou_solver is not None:
            s = self.SanDou_solver
            self.SanDou_CutTimbers = getattr(s, "CutTimbers", None)
            self.SanDou_FailTimbers = getattr(s, "FailTimbers", None)
            self.SanDou_FacePlaneList = getattr(s, "FacePlaneList", None)
            self.SanDou_Log = getattr(s, "Log", None)

        # ---- 4.5 PlaneFromLists::3-2（来自 NiDaoGong 的 EdgeMidPoints/Corner0Planes，经 VSG2_NiDaoGong 变换） ----
        try:
            nd_edge_mid = getattr(self.NiDaoGong_solver, "EdgeMidPoints",
                                  None) if self.NiDaoGong_solver is not None else None
            nd_corner0 = getattr(self.NiDaoGong_solver, "Corner0Planes",
                                 None) if self.NiDaoGong_solver is not None else None

            self.PFL3_2_OriginPoints = _transform_points(nd_edge_mid, self.VSG2_NiDaoGong_XFormRaw)
            self.PFL3_2_BasePlanes = _transform_planes(nd_corner0, self.VSG2_NiDaoGong_XFormRaw)

            idx_o = self.All_dict.get("PlaneFromLists_3_2__IndexOrigin", 0)
            idx_p = self.All_dict.get("PlaneFromLists_3_2__IndexPlane", 0)

            # GH 广播：IndexOrigin / IndexPlane 可能为标量或列表，需对齐到同一长度
            idx_o_list, idx_p_list, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=True)
            base_planes_out, origin_pts_out, result_planes_out = [], [], []
            logs = []
            for i in range(n):
                bp_i, op_i, rp_i, lg_i = builder.build_plane(
                    self.PFL3_2_OriginPoints,
                    self.PFL3_2_BasePlanes,
                    idx_o_list[i],
                    idx_p_list[i]
                )
                base_planes_out.append(bp_i)
                origin_pts_out.append(op_i)
                result_planes_out.append(rp_i)
                if lg_i:
                    _flatten_items(lg_i, logs)

            self.PFL3_2_BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PFL3_2_OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PFL3_2_ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PFL3_2_Log = logs

            self.Log.append(u"[Step4] PlaneFromLists::3-2 built.")
        except Exception as e:
            self.Log.append(u"[Step4] PlaneFromLists::3-2 failed: {}".format(e))

        # ---- 4.6 VSG3_GA_SanDou ----
        try:
            sp_idx = _as_int(self.All_dict.get("VSG3_GA_SanDou__SourcePlane", 0), 0)
            src_plane0 = _pick_by_index(self.SanDou_FacePlaneList, sp_idx, None)

            tgt_plane_in = self.PFL3_2_ResultPlane

            rotate_in = self.All_dict.get("VSG3_GA_SanDou__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG3_GA_SanDou__FlipX", 0)
            flipy_in = self.All_dict.get("VSG3_GA_SanDou__FlipY", 0)
            flipz_in = self.All_dict.get("VSG3_GA_SanDou__FlipZ", 0)
            movex_in = self.All_dict.get("VSG3_GA_SanDou__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG3_GA_SanDou__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG3_GA_SanDou__MoveZ", 0.0)

            geo_in = self.SanDou_CutTimbers

            geo_list = _ensure_list(geo_in)
            tgt_list = _ensure_list(tgt_plane_in)

            n = max(len(geo_list) if len(geo_list) > 0 else 1,
                    len(tgt_list) if len(tgt_list) > 0 else 1)

            geo_list = _broadcast_to(geo_list if len(geo_list) > 0 else [geo_in], n, fill=None)
            tgt_list = _broadcast_to(tgt_list if len(tgt_list) > 0 else [tgt_plane_in], n, fill=None)

            rot_list = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
            fx_list = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
            fy_list = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
            fz_list = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
            mx_list = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
            my_list = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
            mz_list = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)

            src_list = _broadcast_to([src_plane0], n, fill=None)

            so_list, to_list, x_list, mg_list = [], [], [], []
            for i in range(n):
                so, to, xform, mg = GeoAligner_xfm.align(
                    geo_list[i],
                    src_list[i],
                    tgt_list[i],
                    rotate_deg=rot_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                so_list.append(so)
                to_list.append(to)
                x_list.append(xform)
                mg_list.append(mg)

            self.VSG3_SanDou_SourceOut = so_list[0] if n == 1 else so_list
            self.VSG3_SanDou_TargetOut = to_list[0] if n == 1 else to_list
            self.VSG3_SanDou_XFormRaw = x_list[0] if n == 1 else x_list
            self.VSG3_SanDou_TransformOut = (ght.GH_Transform(x_list[0]) if (n == 1 and x_list[0] is not None)
                                             else [ght.GH_Transform(x) if x is not None else None for x in x_list])
            self.VSG3_SanDou_MovedGeo = mg_list[0] if n == 1 else mg_list

            self.Log.append(u"[Step4] VSG3_SanDou aligned (loop). SP_idx={} n={}".format(sp_idx, n))
        except Exception as e:
            self.Log.append(u"[Step4] VSG3_SanDou align failed: {}".format(e))

    # -------------------------
    # Step 5: 叠级4 - 壁内慢栱 / 耍頭 / 令栱 + 对位（VSG4）
    # -------------------------
    def step5_bineimangong_shuatou_linggong_and_align(self):
        self.Log.append(u"[Step5] Build BiNeiManGong/ShuaTou/LingGong, then align (VSG4).")

        base_point = rg.Point3d(0, 0, 0)

        # ---- 5.1 BiNeiManGong ----
        try:
            self.BiNeiManGong_solver = BiNeiManGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
            self.BiNeiManGong_solver = self.BiNeiManGong_solver.run()

            self.BiNeiManGong_CutTimbers = getattr(self.BiNeiManGong_solver, 'CutTimbers', None)
            self.BiNeiManGong_FailTimbers = getattr(self.BiNeiManGong_solver, 'FailTimbers', None)
            self.BiNeiManGong_FacePlaneList = getattr(self.BiNeiManGong_solver, 'FacePlaneList', None)
            self.BiNeiManGong_EdgeMidPoints = getattr(self.BiNeiManGong_solver, 'EdgeMidPoints', None)
            self.BiNeiManGong_Corner0Planes = getattr(self.BiNeiManGong_solver, 'Corner0Planes', None)
            self.BiNeiManGong_CutTimbersPlusAnZhi = getattr(self.BiNeiManGong_solver, 'CutTimbersPlusAnZhi', None)
            self.BiNeiManGong_Log = getattr(self.BiNeiManGong_solver, 'Log', None)
        except Exception as e:
            self.BiNeiManGong_solver = None
            self.Log.append(u"[Step5] BiNeiManGong solver failed: {}".format(e))

        # ---- 5.2 VSG4_GA_BiNeiManGong ----
        # TargetPlane：HuaGong FacePlaneList 经 VSG2_HuaGong TransformOut 变换后的索引
        try:
            sp_idx = _as_int(self.All_dict.get('VSG4_GA_BiNeiManGong__SourcePlane', 0), 0)
            src_plane0 = _pick_by_index(self.BiNeiManGong_FacePlaneList, sp_idx, None)

            tp_idx = _as_int(self.All_dict.get('VSG4_GA_BiNeiManGong__TargetPlane', 0), 0)
            # 先把 HuaGong FacePlaneList 变换到与 VSG2_HuaGong 同位
            hg_planes = _ensure_list(self.HuaGong_FacePlaneList)
            x2 = self.VSG2_HuaGong_XFormRaw
            if isinstance(x2, (list, tuple)):
                x2 = x2[0] if len(x2) > 0 else None
            hg_planes_x = _transform_planes(hg_planes, x2) if (hg_planes and x2 is not None) else hg_planes
            tgt_plane0 = _pick_by_index(hg_planes_x, tp_idx, None)
            self.VSG4_BiNeiManGong_TargetPlanePicked = tgt_plane0

            rotate_in = self.All_dict.get('VSG4_GA_BiNeiManGong__RotateDeg', 0.0)
            flipx_in = self.All_dict.get('VSG4_GA_BiNeiManGong__FlipX', 0)
            flipy_in = self.All_dict.get('VSG4_GA_BiNeiManGong__FlipY', 0)
            flipz_in = self.All_dict.get('VSG4_GA_BiNeiManGong__FlipZ', 0)
            movex_in = self.All_dict.get('VSG4_GA_BiNeiManGong__MoveX', 0.0)
            movey_in = self.All_dict.get('VSG4_GA_BiNeiManGong__MoveY', 0.0)
            movez_in = self.All_dict.get('VSG4_GA_BiNeiManGong__MoveZ', 0.0)

            geo_in = self.BiNeiManGong_CutTimbersPlusAnZhi
            geo_list = _ensure_list(geo_in)
            tgt_list = _ensure_list(tgt_plane0)
            n = max(len(geo_list) if len(geo_list) > 0 else 1,
                    len(tgt_list) if len(tgt_list) > 0 else 1)
            geo_list = _broadcast_to(geo_list if len(geo_list) > 0 else [geo_in], n, fill=None)
            tgt_list = _broadcast_to(tgt_list if len(tgt_list) > 0 else [tgt_plane0], n, fill=None)

            rot_list = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
            fx_list = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
            fy_list = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
            fz_list = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
            mx_list = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
            my_list = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
            mz_list = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)
            src_list = _broadcast_to([src_plane0], n, fill=None)

            so_list, to_list, x_list, mg_list = [], [], [], []
            for i in range(n):
                so, to, xform, mg = GeoAligner_xfm.align(
                    geo_list[i],
                    src_list[i],
                    tgt_list[i],
                    rotate_deg=rot_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                so_list.append(so)
                to_list.append(to)
                x_list.append(xform)
                mg_list.append(mg)

            self.VSG4_BiNeiManGong_SourceOut = so_list[0] if n == 1 else so_list
            self.VSG4_BiNeiManGong_TargetOut = to_list[0] if n == 1 else to_list
            self.VSG4_BiNeiManGong_XFormRaw = x_list[0] if n == 1 else x_list
            self.VSG4_BiNeiManGong_TransformOut = (ght.GH_Transform(x_list[0]) if (n == 1 and x_list[0] is not None)
                                                   else [ght.GH_Transform(x) if x is not None else None for x in
                                                         x_list])
            self.VSG4_BiNeiManGong_MovedGeo = mg_list[0] if n == 1 else mg_list

            self.Log.append(u"[Step5] VSG4_BiNeiManGong aligned. SP_idx={} TP_idx={} n={}".format(sp_idx, tp_idx, n))
        except Exception as e:
            self.Log.append(u"[Step5] VSG4_BiNeiManGong align failed: {}".format(e))

        # ---- 5.3 ShuaTou ----
        try:
            self.ShuaTou_solver = ShuaTou_4PU_INOUT_1ChaoJuantouSolver(self.DBPath, base_point, self.Refresh,
                                                                       self.ghenv)
            self.ShuaTou_solver = self.ShuaTou_solver.run()

            self.ShuaTou_CutTimbers = getattr(self.ShuaTou_solver, 'CutTimbers', None)
            self.ShuaTou_FailTimbers = getattr(self.ShuaTou_solver, 'FailTimbers', None)
            self.ShuaTou_FacePlaneList = getattr(self.ShuaTou_solver, 'FacePlaneList', None)
            self.ShuaTou_Log = getattr(self.ShuaTou_solver, 'Log', None)
        except Exception as e:
            self.ShuaTou_solver = None
            self.Log.append(u"[Step5] ShuaTou solver failed: {}".format(e))

        # ---- 5.4 VSG4_GA_ShuaTou ----
        # TargetPlane：同 VSG4_BiNeiManGong 目标平面（Picked）
        try:
            sp_idx = _as_int(self.All_dict.get('VSG4_GA_ShuaTou__SourcePlane', 0), 0)
            src_plane0 = _pick_by_index(self.ShuaTou_FacePlaneList, sp_idx, None)
            tgt_plane_in = self.VSG4_BiNeiManGong_TargetPlanePicked

            rotate_in = self.All_dict.get('VSG4_GA_ShuaTou__RotateDeg', 0.0)
            flipx_in = self.All_dict.get('VSG4_GA_ShuaTou__FlipX', 0)
            flipy_in = self.All_dict.get('VSG4_GA_ShuaTou__FlipY', 0)
            flipz_in = self.All_dict.get('VSG4_GA_ShuaTou__FlipZ', 0)
            movex_in = self.All_dict.get('VSG4_GA_ShuaTou__MoveX', 0.0)
            movey_in = self.All_dict.get('VSG4_GA_ShuaTou__MoveY', 0.0)
            movez_in = self.All_dict.get('VSG4_GA_ShuaTou__MoveZ', 0.0)

            geo_in = self.ShuaTou_CutTimbers
            geo_list = _ensure_list(geo_in)
            tgt_list = _ensure_list(tgt_plane_in)
            n = max(len(geo_list) if len(geo_list) > 0 else 1,
                    len(tgt_list) if len(tgt_list) > 0 else 1)
            geo_list = _broadcast_to(geo_list if len(geo_list) > 0 else [geo_in], n, fill=None)
            tgt_list = _broadcast_to(tgt_list if len(tgt_list) > 0 else [tgt_plane_in], n, fill=None)

            rot_list = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
            fx_list = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
            fy_list = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
            fz_list = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
            mx_list = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
            my_list = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
            mz_list = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)
            src_list = _broadcast_to([src_plane0], n, fill=None)

            so_list, to_list, x_list, mg_list = [], [], [], []
            for i in range(n):
                so, to, xform, mg = GeoAligner_xfm.align(
                    geo_list[i],
                    src_list[i],
                    tgt_list[i],
                    rotate_deg=rot_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                so_list.append(so)
                to_list.append(to)
                x_list.append(xform)
                mg_list.append(mg)

            self.VSG4_ShuaTou_SourceOut = so_list[0] if n == 1 else so_list
            self.VSG4_ShuaTou_TargetOut = to_list[0] if n == 1 else to_list
            self.VSG4_ShuaTou_XFormRaw = x_list[0] if n == 1 else x_list
            self.VSG4_ShuaTou_TransformOut = (ght.GH_Transform(x_list[0]) if (n == 1 and x_list[0] is not None)
                                              else [ght.GH_Transform(x) if x is not None else None for x in x_list])
            self.VSG4_ShuaTou_MovedGeo = mg_list[0] if n == 1 else mg_list

            self.Log.append(u"[Step5] VSG4_ShuaTou aligned. SP_idx={} n={}".format(sp_idx, n))
        except Exception as e:
            self.Log.append(u"[Step5] VSG4_ShuaTou align failed: {}".format(e))

        # ---- 5.5 LingGong ----
        try:
            self.LingGong_solver = LingGong_4PU_INOUT_1ChaoJuantouChongGSolver(self.DBPath, base_point, self.Refresh,
                                                                               self.ghenv)
            self.LingGong_solver = self.LingGong_solver.run()
            self.LingGong_CutTimbers = getattr(self.LingGong_solver, 'CutTimbers', None)
            self.LingGong_FailTimbers = getattr(self.LingGong_solver, 'FailTimbers', None)
            self.LingGong_FacePlaneList = getattr(self.LingGong_solver, 'FacePlaneList', None)
            self.LingGong_EdgeMidPoints = getattr(self.LingGong_solver, 'EdgeMidPoints', None)
            self.LingGong_Corner0Planes = getattr(self.LingGong_solver, 'Corner0Planes', None)
            self.LingGong_Log = getattr(self.LingGong_solver, 'Log', None)
        except Exception as e:
            self.LingGong_solver = None
            self.Log.append(u"[Step5] LingGong solver failed: {}".format(e))

        # ---- 5.6 VSG4_GA_LingGong ----
        # TargetPlane：JiaoHuDou FacePlaneList 经过 VSG3_JiaoHuDou TransformOut（可能为 tree）变换后的索引
        try:
            sp_idx = _as_int(self.All_dict.get('VSG4_GA_LingGong__SourcePlane', 0), 0)
            src_plane0 = _pick_by_index(self.LingGong_FacePlaneList, sp_idx, None)

            tp_idx_in = self.All_dict.get('VSG4_GA_LingGong__TargetPlane', 0)
            tp_idx_list = _as_int_list(tp_idx_in)

            rotate_in = self.All_dict.get('VSG4_GA_LingGong__RotateDeg', 0.0)
            flipx_in = self.All_dict.get('VSG4_GA_LingGong__FlipX', 0)
            flipy_in = self.All_dict.get('VSG4_GA_LingGong__FlipY', 0)
            flipz_in = self.All_dict.get('VSG4_GA_LingGong__FlipZ', 0)
            movex_in = self.All_dict.get('VSG4_GA_LingGong__MoveX', 0.0)
            movey_in = self.All_dict.get('VSG4_GA_LingGong__MoveY', 0.0)
            movez_in = self.All_dict.get('VSG4_GA_LingGong__MoveZ', 0.0)

            geo_in = self.LingGong_CutTimbers
            geo_list = _ensure_list(geo_in)

            # TransformOut（来自 VSG3_GA_JiaoHuDou）现在应为 Tree（2 个分支，每分支 1 个 xform）
            x3 = self.VSG3_JiaoHuDou_XFormRaw

            # 归一化为 2 分支 Tree：[[xform0],[xform1]]
            if x3 is None:
                x3_tree = [[None], [None]]
            elif isinstance(x3, (list, tuple)):
                # 已是 tree-like
                if len(x3) == 2 and all(isinstance(br, (list, tuple)) for br in x3):
                    x3_tree = [list(br) for br in x3]
                # 可能是 [x0, x1]
                elif len(x3) == 2 and not any(isinstance(br, (list, tuple)) for br in x3):
                    x3_tree = [[x3[0]], [x3[1]]]
                else:
                    # 其它情况：作为单值广播到两分支
                    x0 = x3[0] if len(x3) > 0 else None
                    x3_tree = [[x0], [x0]]
            else:
                x3_tree = [[x3], [x3]]

            # 组件 Transform 的 Geometry 输入：
            #   - 分支0：JiaoHuDou.FacePlaneList[tp_idx]
            #   - 分支1：QiAngDou.FacePlaneList[tp_idx]
            # 两个分支分别用对应的 xform 做几何变换后取索引。
            tp_idx_list = _broadcast_to(tp_idx_list, 2, fill=0)
            face_plane_lists = [
                _ensure_list(self.JiaoHuDou_FacePlaneList),
                _ensure_list(getattr(self, 'QiAngDou_FacePlaneList', None))
            ]

            target_plane_tree = []
            for bi in range(2):
                planes_src = face_plane_lists[bi]
                xf_list = x3_tree[bi] if isinstance(x3_tree[bi], (list, tuple)) else [x3_tree[bi]]
                bi_out = []
                for xf in xf_list:
                    planes_x = _transform_planes(planes_src, xf) if (planes_src and xf is not None) else list(
                        planes_src)
                    bi_out.append(_pick_by_index(planes_x, tp_idx_list[bi], None))
                target_plane_tree.append(bi_out)

            self.VSG4_LingGong_TargetPlaneTree = target_plane_tree

            # 逐分支、逐项做 GeoAligner（GH 广播：geo_list 与 branch target 列表）
            src_list0 = [src_plane0]
            so_tree, to_tree, x_tree, mg_tree = [], [], [], []
            for br in target_plane_tree:
                tgt_list = _ensure_list(br)
                n = max(len(geo_list) if len(geo_list) > 0 else 1,
                        len(tgt_list) if len(tgt_list) > 0 else 1)

                geo_b = _broadcast_to(geo_list if len(geo_list) > 0 else [geo_in], n, fill=None)
                tgt_b = _broadcast_to(tgt_list if len(tgt_list) > 0 else [br], n, fill=None)
                src_b = _broadcast_to(src_list0, n, fill=None)

                rot_b = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
                fx_b = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
                fy_b = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
                fz_b = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
                mx_b = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
                my_b = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
                mz_b = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)

                so_list, to_list, x_list, mg_list = [], [], [], []
                for i in range(n):
                    so, to, xform, mg = GeoAligner_xfm.align(
                        geo_b[i],
                        src_b[i],
                        tgt_b[i],
                        rotate_deg=rot_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    so_list.append(so)
                    to_list.append(to)
                    x_list.append(xform)
                    mg_list.append(mg)

                so_tree.append(so_list)
                to_tree.append(to_list)
                x_tree.append(x_list)
                mg_tree.append(mg_list)

            self.VSG4_LingGong_SourceOut = so_tree
            self.VSG4_LingGong_TargetOut = to_tree
            self.VSG4_LingGong_XFormRaw = x_tree
            self.VSG4_LingGong_TransformOut = [[ght.GH_Transform(x) if x is not None else None for x in br] for br in
                                               x_tree]
            self.VSG4_LingGong_MovedGeo = mg_tree

            self.Log.append(
                u"[Step5] VSG4_LingGong aligned (tree). SP_idx={} branches={}".format(sp_idx, len(target_plane_tree)))
        except Exception as e:
            self.Log.append(u"[Step5] VSG4_LingGong align failed: {}".format(e))

    # -------------------------
    # Step 6: 叠级5 - 散枓（对位到令栱/壁内慢栱） + 交互枓[枓口跳]（对位到令栱）
    #   - PlaneFromLists::5-1：LingGong EdgeMidPoints/Corner0Planes 经 VSG4_LingGong Transform tree -> 索引提取 ResultPlane
    #   - VSG5_GA_SanDou-LingGong：SanDou CutTimbers 对位到 PFL5-1 ResultPlane（tree 广播）
    #   - PlaneFromLists::5-2：BiNeiManGong EdgeMidPoints/Corner0Planes 经 VSG4_BiNeiManGong Transform -> 索引提取 ResultPlane
    #   - VSG5_GA_SanDou-BiNeiManGong：SanDou CutTimbers 对位到 PFL5-2 ResultPlane（list 广播）
    #   - Jiaohudou-DouKouTiao + VSG5_GA_JiaoHuDou-LingGong：Geo/TargetPlane/RotateDeg 为 Tree，按 GH Tree 对齐逐项循环
    # -------------------------
    def step6_sandou_jiaohudou_stage5_and_align(self):
        self.Log.append(
            u"[Step6] Build target planes (PFL5-1/5-2), align SanDou to LingGong/BiNeiManGong, build Jiaohudou-DouKouTiao and align to LingGong (tree).")

        # =========================================================
        # 6.1 PlaneFromLists::5-1（LingGong -> Transform tree）
        # =========================================================
        try:
            # Transform tree from VSG4_LingGong (xform raw tree)
            x_tree = self.VSG4_LingGong_XFormRaw
            if x_tree is None:
                x_tree = [[None]]
            elif not isinstance(x_tree, (list, tuple)):
                x_tree = [[x_tree]]
            else:
                # ensure 2-level tree
                if len(x_tree) > 0 and not any(isinstance(it, (list, tuple)) for it in x_tree):
                    x_tree = [list(x_tree)]
                else:
                    x_tree = [list(br) if isinstance(br, (list, tuple)) else [br] for br in x_tree]

            pts0 = _ensure_list(self.LingGong_EdgeMidPoints)
            pls0 = _ensure_list(self.LingGong_Corner0Planes)

            idx_o = self.All_dict.get("PlaneFromLists_5_1__IndexOrigin", 0)
            idx_p = self.All_dict.get("PlaneFromLists_5_1__IndexPlane", 0)
            idx_o_list, idx_p_list, n_idx = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=True)

            origin_tree, plane_tree = [], []
            baseplane_out_tree, originpt_out_tree, resultplane_out_tree = [], [], []
            logs = []

            for br in x_tree:
                br_origin, br_plane = [], []
                br_bp_out, br_op_out, br_rp_out = [], [], []
                for xf in br:
                    pts_x = _transform_points(pts0, xf) if (pts0 and xf is not None) else list(pts0)
                    pls_x = _transform_planes(pls0, xf) if (pls0 and xf is not None) else list(pls0)
                    br_origin.append(pts_x)
                    br_plane.append(pls_x)

                    # 对每个 transform 实例，按 idx 广播生成 ResultPlane（可能为 list）
                    bps_tmp, ops_tmp, rps_tmp = [], [], []
                    for i in range(n_idx):
                        bp_i, op_i, rp_i, lg_i = builder.build_plane(
                            pts_x,
                            pls_x,
                            idx_o_list[i],
                            idx_p_list[i]
                        )
                        bps_tmp.append(bp_i)
                        ops_tmp.append(op_i)
                        rps_tmp.append(rp_i)
                        if lg_i:
                            _flatten_items(lg_i, logs)

                    br_bp_out.append(bps_tmp[0] if n_idx == 1 else bps_tmp)
                    br_op_out.append(ops_tmp[0] if n_idx == 1 else ops_tmp)
                    br_rp_out.append(rps_tmp[0] if n_idx == 1 else rps_tmp)

                origin_tree.append(br_origin)
                plane_tree.append(br_plane)
                baseplane_out_tree.append(br_bp_out)
                originpt_out_tree.append(br_op_out)
                resultplane_out_tree.append(br_rp_out)

            self.PFL5_1_OriginPointsTree = origin_tree
            self.PFL5_1_BasePlanesTree = plane_tree
            self.PFL5_1_BasePlane = baseplane_out_tree
            self.PFL5_1_OriginPoint = originpt_out_tree
            self.PFL5_1_ResultPlane = resultplane_out_tree
            self.PFL5_1_Log = logs

            self.Log.append(u"[Step6] PlaneFromLists::5-1 built (tree). branches={}".format(len(resultplane_out_tree)))
        except Exception as e:
            self.Log.append(u"[Step6] PlaneFromLists::5-1 failed: {}".format(e))

        # =========================================================
        # 6.2 VSG5_GA_SanDou-LingGong（TargetPlane = PFL5-1 ResultPlane tree）
        # =========================================================
        try:
            geo_in = self.SanDou_CutTimbers
            geo_list0 = _ensure_list(geo_in)

            # SourcePlane: SanDou FacePlaneList by index (supports scalar/list)
            sp_idx_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__SourcePlane", 0)
            sp_idx_list = _as_int_list(sp_idx_in)
            if len(sp_idx_list) == 0:
                sp_idx_list = [0]

            rotate_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__FlipX", 0)
            flipy_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__FlipY", 0)
            flipz_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__FlipZ", 0)
            movex_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG5_GA_SanDou_LingGong__MoveZ", 0.0)

            # TargetPlane tree (same structure as PFL5_1_ResultPlane)
            tgt_tree = self.PFL5_1_ResultPlane
            if tgt_tree is None:
                tgt_tree = [[None]]
            # normalize to 2-level tree: branches -> items
            if not isinstance(tgt_tree, (list, tuple)):
                tgt_tree = [[tgt_tree]]
            else:
                tgt_tree = [list(br) if isinstance(br, (list, tuple)) else [br] for br in tgt_tree]

            so_tree, to_tree, x_tree, mg_tree = [], [], [], []
            for br in tgt_tree:
                # br item may be scalar or list (if n_idx>1). flatten one level to align list.
                tgt_list_flat = []
                _flatten_items(br, tgt_list_flat)
                tgt_list = _ensure_list(tgt_list_flat)

                n = max(len(geo_list0) if len(geo_list0) > 0 else 1,
                        len(tgt_list) if len(tgt_list) > 0 else 1,
                        len(sp_idx_list) if len(sp_idx_list) > 0 else 1)

                geo_b = _broadcast_to(geo_list0 if len(geo_list0) > 0 else [geo_in], n, fill=None)
                tgt_b = _broadcast_to(tgt_list if len(tgt_list) > 0 else [None], n, fill=None)
                sp_bi = _broadcast_to(sp_idx_list, n, fill=sp_idx_list[-1] if len(sp_idx_list) else 0)
                src_b = [_pick_by_index(self.SanDou_FacePlaneList, sp_bi[i], None) for i in range(n)]

                rot_b = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
                fx_b = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
                fy_b = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
                fz_b = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
                mx_b = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
                my_b = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
                mz_b = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)

                so_list, to_list, x_list, mg_list = [], [], [], []
                for i in range(n):
                    so, to, xf, mg = GeoAligner_xfm.align(
                        geo_b[i],
                        src_b[i],
                        tgt_b[i],
                        rotate_deg=rot_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    so_list.append(so);
                    to_list.append(to);
                    x_list.append(xf);
                    mg_list.append(mg)

                so_tree.append(so_list)
                to_tree.append(to_list)
                x_tree.append(x_list)
                mg_tree.append(mg_list)

            self.VSG5_SanDou_LingGong_SourceOut = so_tree
            self.VSG5_SanDou_LingGong_TargetOut = to_tree
            self.VSG5_SanDou_LingGong_XFormRaw = x_tree
            self.VSG5_SanDou_LingGong_TransformOut = [[ght.GH_Transform(x) if x is not None else None for x in br] for
                                                      br in x_tree]
            self.VSG5_SanDou_LingGong_MovedGeo = mg_tree

            self.Log.append(u"[Step6] VSG5_SanDou-LingGong aligned (tree). branches={}".format(len(so_tree)))
        except Exception as e:
            self.Log.append(u"[Step6] VSG5_SanDou-LingGong align failed: {}".format(e))

        # =========================================================
        # 6.3 PlaneFromLists::5-2（BiNeiManGong -> Transform）
        # =========================================================
        try:
            x4 = self.VSG4_BiNeiManGong_XFormRaw
            if isinstance(x4, (list, tuple)):
                x4 = x4[0] if len(x4) else None

            pts0 = _ensure_list(self.BiNeiManGong_EdgeMidPoints)
            pls0 = _ensure_list(self.BiNeiManGong_Corner0Planes)

            self.PFL5_2_OriginPoints = _transform_points(pts0, x4) if (pts0 and x4 is not None) else list(pts0)
            self.PFL5_2_BasePlanes = _transform_planes(pls0, x4) if (pls0 and x4 is not None) else list(pls0)

            idx_o = self.All_dict.get("PlaneFromLists_5_2__IndexOrigin", 0)
            idx_p = self.All_dict.get("PlaneFromLists_5_2__IndexPlane", 0)
            idx_o_list, idx_p_list, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=True)
            base_planes_out, origin_pts_out, result_planes_out = [], [], []
            logs = []
            for i in range(n):
                bp_i, op_i, rp_i, lg_i = builder.build_plane(
                    self.PFL5_2_OriginPoints,
                    self.PFL5_2_BasePlanes,
                    idx_o_list[i],
                    idx_p_list[i]
                )
                base_planes_out.append(bp_i)
                origin_pts_out.append(op_i)
                result_planes_out.append(rp_i)
                if lg_i:
                    _flatten_items(lg_i, logs)

            self.PFL5_2_BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PFL5_2_OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PFL5_2_ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PFL5_2_Log = logs

            self.Log.append(u"[Step6] PlaneFromLists::5-2 built.")
        except Exception as e:
            self.Log.append(u"[Step6] PlaneFromLists::5-2 failed: {}".format(e))

        # =========================================================
        # 6.4 VSG5_GA_SanDou-BiNeiManGong（TargetPlane = PFL5-2 ResultPlane）
        # =========================================================
        try:
            geo_in = self.SanDou_CutTimbers
            geo_list = _ensure_list(geo_in)

            sp_idx_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__SourcePlane", 0)
            sp_idx = _as_int(sp_idx_in, 0)
            src_plane0 = _pick_by_index(self.SanDou_FacePlaneList, sp_idx, None)

            tgt_plane_in = self.PFL5_2_ResultPlane

            rotate_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__FlipX", 0)
            flipy_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__FlipY", 0)
            flipz_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__FlipZ", 0)
            movex_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG5_GA_SanDou_BiNeiManGong__MoveZ", 0.0)

            tgt_list = _ensure_list(tgt_plane_in)
            n = max(len(geo_list) if len(geo_list) > 0 else 1,
                    len(tgt_list) if len(tgt_list) > 0 else 1)

            geo_b = _broadcast_to(geo_list if len(geo_list) > 0 else [geo_in], n, fill=None)
            tgt_b = _broadcast_to(tgt_list if len(tgt_list) > 0 else [tgt_plane_in], n, fill=None)
            src_b = _broadcast_to([src_plane0], n, fill=None)

            rot_b = _broadcast_to(_as_float_or_list(rotate_in, 0.0), n, fill=0.0)
            fx_b = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
            fy_b = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
            fz_b = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
            mx_b = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
            my_b = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
            mz_b = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)

            so_list, to_list, x_list, mg_list = [], [], [], []
            for i in range(n):
                so, to, xf, mg = GeoAligner_xfm.align(
                    geo_b[i],
                    src_b[i],
                    tgt_b[i],
                    rotate_deg=rot_b[i],
                    flip_x=fx_b[i],
                    flip_y=fy_b[i],
                    flip_z=fz_b[i],
                    move_x=mx_b[i],
                    move_y=my_b[i],
                    move_z=mz_b[i],
                )
                so_list.append(so);
                to_list.append(to);
                x_list.append(xf);
                mg_list.append(mg)

            self.VSG5_SanDou_BiNeiManGong_SourceOut = so_list[0] if n == 1 else so_list
            self.VSG5_SanDou_BiNeiManGong_TargetOut = to_list[0] if n == 1 else to_list
            self.VSG5_SanDou_BiNeiManGong_XFormRaw = x_list[0] if n == 1 else x_list
            self.VSG5_SanDou_BiNeiManGong_TransformOut = (
                ght.GH_Transform(x_list[0]) if (n == 1 and x_list[0] is not None)
                else [ght.GH_Transform(x) if x is not None else None for x in x_list])
            self.VSG5_SanDou_BiNeiManGong_MovedGeo = mg_list[0] if n == 1 else mg_list

            self.Log.append(u"[Step6] VSG5_SanDou-BiNeiManGong aligned. SP_idx={} n={}".format(sp_idx, n))
        except Exception as e:
            self.Log.append(u"[Step6] VSG5_SanDou-BiNeiManGong align failed: {}".format(e))

        # =========================================================
        # 6.5 Jiaohudou-DouKouTiao solver
        # =========================================================
        try:
            base_point = rg.Point3d(0, 0, 0)
            self.JiaoHuDou_DouKouTiao_solver = JIAOHU_DOU_doukoutiaoSolver(self.DBPath, base_point, self.Refresh)
            self.JiaoHuDou_DouKouTiao_solver.run()

            s = self.JiaoHuDou_DouKouTiao_solver
            self.JiaoHuDou_DouKouTiao_CutTimbers = getattr(s, "CutTimbers", None)
            self.JiaoHuDou_DouKouTiao_FailTimbers = getattr(s, "FailTimbers", None)
            self.JiaoHuDou_DouKouTiao_FacePlaneList = getattr(s, "FacePlaneList", None)
            self.JiaoHuDou_DouKouTiao_Log = getattr(s, "Log", None)

            self.Log.append(u"[Step6] Jiaohudou-DouKouTiao solver ok.")
        except Exception as e:
            self.JiaoHuDou_DouKouTiao_solver = None
            self.Log.append(u"[Step6] Jiaohudou-DouKouTiao solver failed: {}".format(e))

        # =========================================================
        # 6.6 VSG5_GA_JiaoHuDou-LingGong（TargetPlane + RotateDeg 为 Tree）
        # =========================================================
        try:
            geo_in = self.JiaoHuDou_DouKouTiao_CutTimbers
            geo_list0 = _ensure_list(geo_in)

            # SourcePlane index (supports scalar/list)
            sp_idx_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__SourcePlane", 0)
            sp_idx_list = _as_int_list(sp_idx_in)
            if len(sp_idx_list) == 0:
                sp_idx_list = [0]

            # TargetPlane index (can be scalar/list/tree)
            tp_idx_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__TargetPlane", 0)

            # RotateDeg can be scalar/list/tree
            rot_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__RotateDeg", 0.0)

            # other params
            flipx_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__FlipX", 0)
            flipy_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__FlipY", 0)
            flipz_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__FlipZ", 0)
            movex_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG5_GA_JiaoHuDou_LingGong__MoveZ", 0.0)

            # Transform tree from VSG4_LingGong (reuse normalize)
            x_tree = self.VSG4_LingGong_XFormRaw
            if x_tree is None:
                x_tree = [[None]]
            elif not isinstance(x_tree, (list, tuple)):
                x_tree = [[x_tree]]
            else:
                if len(x_tree) > 0 and not any(isinstance(it, (list, tuple)) for it in x_tree):
                    x_tree = [list(x_tree)]
                else:
                    x_tree = [list(br) if isinstance(br, (list, tuple)) else [br] for br in x_tree]

            # normalize target index tree
            def _to_tree(v):
                if isinstance(v, (list, tuple)):
                    if len(v) > 0 and any(isinstance(it, (list, tuple)) for it in v):
                        return [list(br) if isinstance(br, (list, tuple)) else [br] for br in v]
                    return [list(v)]
                return [[v]]

            tp_tree = _to_tree(tp_idx_in)
            rot_tree = _to_tree(rot_in)

            # Build TargetPlane tree: for each branch/item, transform LingGong FacePlaneList then pick by tp index
            lg_planes0 = _ensure_list(self.LingGong_FacePlaneList)
            target_plane_tree = []
            for bi, br in enumerate(x_tree):
                br_tp_idx = tp_tree[bi] if bi < len(tp_tree) else tp_tree[-1]
                br_out = []
                for ii, xf in enumerate(br):
                    idx_here = br_tp_idx[ii] if ii < len(br_tp_idx) else br_tp_idx[-1]
                    idx_here = _as_int(idx_here, 0)
                    planes_x = _transform_planes(lg_planes0, xf) if (lg_planes0 and xf is not None) else list(
                        lg_planes0)
                    br_out.append(_pick_by_index(planes_x, idx_here, None))
                target_plane_tree.append(br_out)

            self.VSG5_JiaoHuDou_LingGong_TargetPlaneTree = target_plane_tree

            so_tree, to_tree, xout_tree, mg_tree = [], [], [], []
            for bi, br_tgt in enumerate(target_plane_tree):
                br_rot = rot_tree[bi] if bi < len(rot_tree) else rot_tree[-1]

                tgt_list = _ensure_list(br_tgt)
                rot_list = _ensure_list(br_rot)

                n = max(len(geo_list0) if len(geo_list0) > 0 else 1,
                        len(tgt_list) if len(tgt_list) > 0 else 1,
                        len(rot_list) if len(rot_list) > 0 else 1,
                        len(sp_idx_list) if len(sp_idx_list) > 0 else 1)

                geo_b = _broadcast_to(geo_list0 if len(geo_list0) > 0 else [geo_in], n, fill=None)
                tgt_b = _broadcast_to(tgt_list if len(tgt_list) > 0 else [None], n, fill=None)

                sp_bi = _broadcast_to(sp_idx_list, n, fill=sp_idx_list[-1] if len(sp_idx_list) else 0)
                src_b = [_pick_by_index(self.JiaoHuDou_DouKouTiao_FacePlaneList, sp_bi[i], None) for i in range(n)]

                rot_b = _broadcast_to(_as_float_or_list(rot_list, 0.0), n, fill=0.0)
                fx_b = _broadcast_to(_as_01_or_list(flipx_in, 0), n, fill=0)
                fy_b = _broadcast_to(_as_01_or_list(flipy_in, 0), n, fill=0)
                fz_b = _broadcast_to(_as_01_or_list(flipz_in, 0), n, fill=0)
                mx_b = _broadcast_to(_as_float_or_list(movex_in, 0.0), n, fill=0.0)
                my_b = _broadcast_to(_as_float_or_list(movey_in, 0.0), n, fill=0.0)
                mz_b = _broadcast_to(_as_float_or_list(movez_in, 0.0), n, fill=0.0)

                so_list, to_list, x_list, mg_list = [], [], [], []
                for i in range(n):
                    so, to, xf, mg = GeoAligner_xfm.align(
                        geo_b[i],
                        src_b[i],
                        tgt_b[i],
                        rotate_deg=rot_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    so_list.append(so);
                    to_list.append(to);
                    x_list.append(xf);
                    mg_list.append(mg)

                so_tree.append(so_list)
                to_tree.append(to_list)
                xout_tree.append(x_list)
                mg_tree.append(mg_list)

            self.VSG5_JiaoHuDou_LingGong_SourceOut = so_tree
            self.VSG5_JiaoHuDou_LingGong_TargetOut = to_tree
            self.VSG5_JiaoHuDou_LingGong_XFormRaw = xout_tree
            self.VSG5_JiaoHuDou_LingGong_TransformOut = [[ght.GH_Transform(x) if x is not None else None for x in br]
                                                         for br in xout_tree]
            self.VSG5_JiaoHuDou_LingGong_MovedGeo = mg_tree

            self.Log.append(u"[Step6] VSG5_JiaoHuDou-LingGong aligned (tree). branches={}".format(len(so_tree)))
        except Exception as e:
            self.Log.append(u"[Step6] VSG5_JiaoHuDou-LingGong align failed: {}".format(e))

    # -------------------------
    # Step Final: 组合输出
    # -------------------------

    def step7_chenfangtou_and_align(self):
        self.Log.append(u"[Step7-1] Build ChenFangTou, then align to ShuaTou (VSG6).")

        base_point = rg.Point3d(0, 0, 0)

        # =========================================================
        # 7.1 ChenFangTou（襯方頭）
        # =========================================================
        try:
            self.ChenFangTou_solver = ChenFangTouSolver(
                DBPath=self.DBPath,
                base_point=base_point,
                Refresh=self.Refresh,
                ghenv=self.ghenv
            ).run()

            self.ChenFangTou_CutTimbers = getattr(self.ChenFangTou_solver, 'CutTimbers', None)
            self.ChenFangTou_FailTimbers = getattr(self.ChenFangTou_solver, 'FailTimbers', None)
            self.ChenFangTou_FacePlaneList = getattr(self.ChenFangTou_solver, 'FacePlaneList', None)
            self.ChenFangTou_Log = getattr(self.ChenFangTou_solver, 'Log', None)

        except Exception as e:
            self.ChenFangTou_solver = None
            self.ChenFangTou_CutTimbers = None
            self.ChenFangTou_FailTimbers = None
            self.ChenFangTou_FacePlaneList = None
            self.ChenFangTou_Log = [u"[ChenFangTou] ERROR: %s" % str(e)]
            self.Log.extend(_ensure_list(self.ChenFangTou_Log))

        # =========================================================
        # 7.2 VSG6_GA_ChenFangTou（按参考平面对位到 ShuaTou）
        #     - SourcePlane：ChenFangTou FacePlaneList idx
        #     - TargetPlane：ShuaTou FacePlaneList idx，再经 VSG4_ShuaTou Transform 变换
        # =========================================================
        try:
            sp_idx = _as_int(self.All_dict.get('VSG6_GA_ChenFangTou__SourcePlane', 0), 0)
            src_plane0 = _pick_by_index(self.ChenFangTou_FacePlaneList, sp_idx, None)

            tp_idx = _as_int(self.All_dict.get('VSG6_GA_ChenFangTou__TargetPlane', 0), 0)
            st_planes = _ensure_list(self.ShuaTou_FacePlaneList)

            x4 = self.VSG4_ShuaTou_XFormRaw
            if isinstance(x4, (list, tuple)):
                x4 = x4[0] if len(x4) > 0 else None
            st_planes_x = _transform_planes(st_planes, x4) if (st_planes and x4 is not None) else st_planes
            tgt_plane0 = _pick_by_index(st_planes_x, tp_idx, None)

            rotate_deg = _as_float_or_list(self.All_dict.get('VSG6_GA_ChenFangTou__RotateDeg', 0.0), 0.0)
            flip_z = _as_01_or_list(self.All_dict.get('VSG6_GA_ChenFangTou__FlipZ', 0), 0)

            geo = self.ChenFangTou_CutTimbers

            self.VSG6_SourceOut, self.VSG6_TargetOut, xform, self.VSG6_MovedGeo = GeoAligner_xfm.align(
                geo,
                src_plane0,
                tgt_plane0,
                rotate_deg=rotate_deg,
                flip_x=0,
                flip_y=0,
                flip_z=flip_z,
                move_x=0.0,
                move_y=0.0,
                move_z=0.0,
            )

            self.VSG6_XFormRaw = xform
            self.VSG6_TransformOut = ght.GH_Transform(xform) if xform is not None else None

        except Exception as e:
            self.VSG6_SourceOut = None
            self.VSG6_TargetOut = None
            self.VSG6_XFormRaw = None
            self.VSG6_TransformOut = None
            self.VSG6_MovedGeo = None
            self.Log.append(u"[VSG6_GA_ChenFangTou] ERROR: %s" % str(e))

    def build_component_assembly(self):
        # 组合：按步骤逐步 append
        parts = []
        if self.VSG1_MovedGeo is not None:
            parts.append(self.VSG1_MovedGeo)
        if self.VSG2_NiDaoGong_MovedGeo is not None:
            parts.append(self.VSG2_NiDaoGong_MovedGeo)
        if self.VSG2_HuaGong_MovedGeo is not None:
            parts.append(self.VSG2_HuaGong_MovedGeo)
        if self.VSG3_JiaoHuDou_MovedGeo is not None:
            parts.append(self.VSG3_JiaoHuDou_MovedGeo)
        if self.VSG3_SanDou_MovedGeo is not None:
            parts.append(self.VSG3_SanDou_MovedGeo)

        # Step5 parts
        if self.VSG4_BiNeiManGong_MovedGeo is not None:
            parts.append(self.VSG4_BiNeiManGong_MovedGeo)
        if self.VSG4_ShuaTou_MovedGeo is not None:
            parts.append(self.VSG4_ShuaTou_MovedGeo)
        if self.VSG4_LingGong_MovedGeo is not None:
            parts.append(self.VSG4_LingGong_MovedGeo)

        # Step6 parts
        if self.VSG5_SanDou_LingGong_MovedGeo is not None:
            parts.append(self.VSG5_SanDou_LingGong_MovedGeo)
        if self.VSG5_SanDou_BiNeiManGong_MovedGeo is not None:
            parts.append(self.VSG5_SanDou_BiNeiManGong_MovedGeo)
        if self.VSG5_JiaoHuDou_LingGong_MovedGeo is not None:
            parts.append(self.VSG5_JiaoHuDou_LingGong_MovedGeo)
        # Step7/8：襯補部分（受 Step9 开关控制）
        if getattr(self, 'VSG6_MovedGeo', None) is not None:
            parts.append(self.VSG6_MovedGeo)

        # ---- 襯補：可关闭 ----
        if getattr(self, 'EnableChenBu', True):
            # Step7-2 / Step7-3
            if getattr(self, 'VSG6_LaoYanFang_MovedGeo', None) is not None:
                parts.append(self.VSG6_LaoYanFang_MovedGeo)
            if getattr(self, 'VSG6_PingJiFang_MovedGeo', None) is not None:
                parts.append(self.VSG6_PingJiFang_MovedGeo)
            if getattr(self, 'VSG6_ZhuTouFang_MovedGeo', None) is not None:
                parts.append(self.VSG6_ZhuTouFang_MovedGeo)

            # Step8
            if getattr(self, 'VSG7_Cube1_MovedGeo', None) is not None:
                parts.append(self.VSG7_Cube1_MovedGeo)
            if getattr(self, 'VSG7_Cube2_MovedGeo', None) is not None:
                parts.append(self.VSG7_Cube2_MovedGeo)
            if getattr(self, 'VSG7_NiuJiFang_MovedGeo', None) is not None:
                parts.append(self.VSG7_NiuJiFang_MovedGeo)

        flat = []
        _flatten_items(parts, flat)
        self.ComponentAssembly = flat

    def step7_2_laoyanfang_and_align(self):
        # Step 9：襯補计算开关
        if not getattr(self, 'EnableChenBu', True):
            self.Log.append(
                u"[Step7-2] EnableChenBu=False → skip LaoYanFang-6 / PlaneFromLists::6-1 / VSG6_GA_LaoYanFang")
            self.VSG6_LaoYanFang_MovedGeo = None
            return
        self.Log.append(u"[Step7-2] Build LaoYanFang-6, PlaneFromLists::6-1, then align (VSG6_GA_LaoYanFang).")

        # =========================================================
        # 7-2) LaoYanFang-6（橑檐方刀具）
        # =========================================================
        try:
            input_point = rg.Point3d(0, 0, 0)

            w_in = self.All_dict.get("LaoYanFang_6__WidthFen", None)
            h_in = self.All_dict.get("LaoYanFang_6__HeightFen", None)
            e_in = self.All_dict.get("LaoYanFang_6__ExtrudeFen", None)

            # 允许 w/h/e 为标量或 list（取第一个）
            w0 = _ensure_list(w_in)[0] if len(_ensure_list(w_in)) > 0 else None
            h0 = _ensure_list(h_in)[0] if len(_ensure_list(h_in)) > 0 else None
            e0 = _ensure_list(e_in)[0] if len(_ensure_list(e_in)) > 0 else None

            width_fen = float(_as_float_or_list(w0, 10.0))
            height_fen = float(_as_float_or_list(h0, 30.0))
            extrude_fen = float(_as_float_or_list(e0, 100.0))

            # RefPlane（本步骤一般未接线 → None）
            ref_plane = None

            builder = RuFangEaveToolBuilder(
                input_point=input_point,
                ref_plane=ref_plane,
                width_fen=width_fen,
                height_fen=height_fen,
                extrude_fen=extrude_fen
            )

            result = builder.build() or {}

            self.LaoYanFang6_EveTool = result.get("EveTool", None)
            self.LaoYanFang6_Section = result.get("Section", None)
            self.LaoYanFang6_SectionVertices = result.get("SectionVertices", None)
            self.LaoYanFang6_SectionVertexNames = result.get("SectionVertexNames", None)
            self.LaoYanFang6_RectEdgeMidPoints = result.get("RectEdgeMidPoints", None)
            self.LaoYanFang6_RectEdgeNames = result.get("RectEdgeNames", None)
            self.LaoYanFang6_RefPlaneList = result.get("RefPlaneList", None)
            self.LaoYanFang6_RefPlaneNames = result.get("RefPlaneNames", None)

            self.LaoYanFang6_Log = []
            rlog = result.get("Log", [])
            if isinstance(rlog, (list, tuple)):
                self.LaoYanFang6_Log.extend([str(x) for x in rlog])
            elif rlog is not None:
                self.LaoYanFang6_Log.append(str(rlog))

        except Exception as e:
            self.Log.append(u"[ERR][Step7-2] LaoYanFang-6 build failed: {}".format(e))
            self.LaoYanFang6_EveTool = None
            self.LaoYanFang6_RectEdgeMidPoints = None
            self.LaoYanFang6_RefPlaneList = None
            self.LaoYanFang6_Log = [str(e)]

        # =========================================================
        # 7-2) PlaneFromLists::6-1
        # =========================================================
        try:
            origin_points = self.LaoYanFang6_RectEdgeMidPoints
            base_planes = self.LaoYanFang6_RefPlaneList

            idx_origin_in = self.All_dict.get("PlaneFromLists_6_1__IndexOrigin", 0)
            idx_plane_in = self.All_dict.get("PlaneFromLists_6_1__IndexPlane", 0)
            wrap_in = self.All_dict.get("PlaneFromLists_6_1__Wrap", True)

            idx_origin_list = _ensure_list(idx_origin_in)
            idx_plane_list = _ensure_list(idx_plane_in)
            idx_origin_list, idx_plane_list, n = _broadcast_pair(idx_origin_list, idx_plane_list)

            pfl_builder = FTPlaneFromLists(wrap=bool(wrap_in))

            bp_last, op_last, rp_last = None, None, None
            pfl_logs = []

            for io, ip in zip(idx_origin_list, idx_plane_list):
                bp, op, rp, lg = pfl_builder.build_plane(origin_points, base_planes, io, ip)
                bp_last, op_last, rp_last = bp, op, rp
                if lg is not None:
                    if isinstance(lg, (list, tuple)):
                        pfl_logs.extend([str(x) for x in lg])
                    else:
                        pfl_logs.append(str(lg))

            self.PFL6_1_BasePlane = bp_last
            self.PFL6_1_OriginPoint = op_last
            self.PFL6_1_ResultPlane = rp_last
            self.PFL6_1_Log = pfl_logs

        except Exception as e:
            self.Log.append(u"[ERR][Step7-2] PlaneFromLists::6-1 failed: {}".format(e))
            self.PFL6_1_ResultPlane = None
            self.PFL6_1_Log = [str(e)]

        # =========================================================
        # 7-2) VSG6_GA_LaoYanFang 对位（GeoAligner_xfm）
        # =========================================================
        try:
            geo_in = self.LaoYanFang6_EveTool
            source_plane_in = self.PFL6_1_ResultPlane

            # TargetPlane：取 VSG5_GA_JiaoHuDou-LingGong 输入 TargetPlane Tree 的第 2 个对象（index=1）
            tp_tree = getattr(self, "VSG5_JiaoHuDou_LingGong_TargetPlaneTree", None)
            target_plane_in = _pick_nth_from_tree(tp_tree, 0)

            flipx_in = self.All_dict.get("VSG6_GA_LaoYanFang__FlipX", 0)
            movey_in = self.All_dict.get("VSG6_GA_LaoYanFang__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG6_GA_LaoYanFang__MoveZ", 0.0)

            # 其它默认（即便 DB 没有也不影响）
            rot_in = self.All_dict.get("VSG6_GA_LaoYanFang__RotateDeg", 0.0)
            flipy_in = self.All_dict.get("VSG6_GA_LaoYanFang__FlipY", 0)
            flipz_in = self.All_dict.get("VSG6_GA_LaoYanFang__FlipZ", 0)
            movex_in = self.All_dict.get("VSG6_GA_LaoYanFang__MoveX", 0.0)

            # 广播对齐（以 RotateDeg 为主）
            geo_list = _ensure_list(geo_in)
            sp_list = _ensure_list(source_plane_in)
            tp_list = _ensure_list(target_plane_in)

            rot_list = _ensure_list(rot_in)
            fx_list = _ensure_list(flipx_in)
            fy_list = _ensure_list(flipy_in)
            fz_list = _ensure_list(flipz_in)
            mx_list = _ensure_list(movex_in)
            my_list = _ensure_list(movey_in)
            mz_list = _ensure_list(movez_in)

            geo_list, rot_list, n = _broadcast_pair(geo_list, rot_list)
            sp_list = _broadcast_to(sp_list, n, fill=None)
            tp_list = _broadcast_to(tp_list, n, fill=None)

            fx_list = _broadcast_to(fx_list, n, fill=0)
            fy_list = _broadcast_to(fy_list, n, fill=0)
            fz_list = _broadcast_to(fz_list, n, fill=0)
            mx_list = _broadcast_to(mx_list, n, fill=0.0)
            my_list = _broadcast_to(my_list, n, fill=0.0)
            mz_list = _broadcast_to(mz_list, n, fill=0.0)

            moved_out = []
            so_last, to_last, x_last = None, None, None

            for i in range(n):
                so, to, xform, moved = GeoAligner_xfm.align(
                    geo_list[i],
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=float(_as_float_or_list(rot_list[i], 0.0)),
                    flip_x=bool(_as_01_or_list(fx_list[i], 0)),
                    flip_y=bool(_as_01_or_list(fy_list[i], 0)),
                    flip_z=bool(_as_01_or_list(fz_list[i], 0)),
                    move_x=float(_as_float_or_list(mx_list[i], 0.0)),
                    move_y=float(_as_float_or_list(my_list[i], 0.0)),
                    move_z=float(_as_float_or_list(mz_list[i], 0.0)),
                )
                so_last, to_last, x_last = so, to, xform
                moved_out.append(moved)

            self.VSG6_LaoYanFang_SourceOut = so_last
            self.VSG6_LaoYanFang_TargetOut = to_last
            self.VSG6_LaoYanFang_XFormRaw = x_last
            self.VSG6_LaoYanFang_TransformOut = ght.GH_Transform(x_last) if x_last is not None else None
            self.VSG6_LaoYanFang_MovedGeo = moved_out if n != 1 else moved_out[0]

        except Exception as e:
            self.Log.append(u"[ERR][Step7-2] VSG6_GA_LaoYanFang align failed: {}".format(e))
            self.VSG6_LaoYanFang_MovedGeo = None

    def step7_3_timber6_and_align_pingjifang_zhutoufang(self):
        # Step 9：襯補计算开关
        if not getattr(self, 'EnableChenBu', True):
            self.Log.append(u"[Step7-3] EnableChenBu=False → skip Timber-6 / VSG6_GA_PingJiFang / VSG6_GA_ZhuTouFang")
            self.VSG6_PingJiFang_MovedGeo = None
            self.VSG6_ZhuTouFang_MovedGeo = None
            return
        self.Log.append(u"[Step7-3] Build Timber-6, then align PingJiFang / ZhuTouFang (GeoAligner_xfm).")

        # =========================================================
        # 7-3) Timber-6（木料）
        # =========================================================
        try:
            length_in = self.All_dict.get("Timber_6__length_fen", None)
            width_in = self.All_dict.get("Timber_6__width_fen", None)
            height_in = self.All_dict.get("Timber_6__height_fen", None)

            # 允许输入为标量或 list（取第一个）
            l0 = _ensure_list(length_in)[0] if len(_ensure_list(length_in)) > 0 else None
            w0 = _ensure_list(width_in)[0] if len(_ensure_list(width_in)) > 0 else None
            h0 = _ensure_list(height_in)[0] if len(_ensure_list(height_in)) > 0 else None

            length_fen = float(_as_float_or_list(l0, 32.0))
            width_fen = float(_as_float_or_list(w0, 32.0))
            height_fen = float(_as_float_or_list(h0, 20.0))

            base_point = rg.Point3d(0, 0, 0)

            # Timber-6 的 reference_plane 采用 GH 参考平面语义（XY / XZ / YZ）
            # 允许传入：
            #   - "XY Plane" / "XZ Plane" / "YZ Plane"
            #   - "WorldXY" / "WorldXZ" / "WorldYZ"
            #   - 或直接传入 rg.Plane / GH_Plane
            ref_in = self.All_dict.get("Timber_6__reference_plane", "WorldXZ")
            if ref_in is None or (isinstance(ref_in, str) and ref_in.strip() == ""):
                ref_in = "WorldXZ"

            # --- 1) 直接 Plane / GH_Plane ---
            reference_plane = None
            if isinstance(ref_in, rg.Plane):
                reference_plane = ref_in
            elif hasattr(ref_in, "Plane") and isinstance(getattr(ref_in, "Plane", None), rg.Plane):
                reference_plane = ref_in.Plane

            # --- 2) 字符串模式：按 GH 的 XY/XZ/YZ 方向向量约定构造 ---
            if reference_plane is None:
                s = str(ref_in).strip()
                s_up = s.replace(" ", "").upper()  # "XYPLANE" / "WORLDXZ" ...
                # 约定：
                #   XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
                #   XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
                #   YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
                if s_up in ("XY", "XYPLANE", "WORLDXY"):
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 1.0, 0.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                elif s_up in ("XZ", "XZPLANE", "WORLDXZ"):
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                elif s_up in ("YZ", "YZPLANE", "WORLDYZ"):
                    xaxis = rg.Vector3d(0.0, 1.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                else:
                    # 回退：保持既有习惯，默认 WorldXZ
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                    self.Log.append(
                        u"[WARN][Step7-3] Timber_6__reference_plane unsupported: {} → fallback WorldXZ".format(s))
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
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
            )

            self.Timber6_TimberBrep = timber_brep
            self.Timber6_FaceList = faces
            self.Timber6_PointList = points
            self.Timber6_EdgeList = edges
            self.Timber6_CenterPoint = center_pt
            self.Timber6_CenterAxisLines = center_axes
            self.Timber6_EdgeMidPoints = edge_midpts
            self.Timber6_FacePlaneList = face_planes
            self.Timber6_Corner0Planes = corner0_planes
            self.Timber6_LocalAxesPlane = local_axes_plane
            self.Timber6_AxisX = axis_x
            self.Timber6_AxisY = axis_y
            self.Timber6_AxisZ = axis_z
            self.Timber6_FaceDirTags = face_tags
            self.Timber6_EdgeDirTags = edge_tags
            self.Timber6_Corner0EdgeDirs = corner0_dirs
            self.Timber6_Log = log_lines

        except Exception as e:
            self.Log.append(u"[ERR][Step7-3] Timber-6 build failed: {}".format(e))
            self.Timber6_TimberBrep = None
            self.Timber6_FacePlaneList = []
            self.Timber6_Log = [u"错误: {}".format(e)]

        # =========================================================
        # 7-3) VSG6_GA_PingJiFang（Timber-6 -> VSG5_JiaoHuDou-LingGong TargetPlane[0]）
        # =========================================================
        try:
            geo_in = self.Timber6_TimberBrep

            # SourcePlane：Timber-6 FacePlaneList 索引
            sp_idx_in = self.All_dict.get("VSG6_GA_PingJiFang__SourcePlane", 0)
            sp_idx = _as_int(sp_idx_in, 0)
            source_plane_in = _pick_by_index(self.Timber6_FacePlaneList, sp_idx, None)

            # TargetPlane：取 VSG5_GA_JiaoHuDou-LingGong 输入 TargetPlane Tree 的第 1 个对象（index=0）
            tp_tree = getattr(self, "VSG5_JiaoHuDou_LingGong_TargetPlaneTree", None)
            target_plane_in = _pick_nth_from_tree(tp_tree, 1)

            rot_in = self.All_dict.get("VSG6_GA_PingJiFang__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG6_GA_PingJiFang__FlipX", 0)
            movez_in = self.All_dict.get("VSG6_GA_PingJiFang__MoveZ", 0.0)

            rotate_deg = _as_float_or_list(rot_in, 0.0)
            flip_x = _as_01(flipx_in, 0)
            move_z = _as_float_or_list(movez_in, 0.0)

            # GH 风格广播：以 rotate 为主（若其为 list）
            rot_list = _ensure_list(rotate_deg)
            n = len(rot_list) if len(rot_list) > 0 else 1

            geo_list = _broadcast_to(geo_in, n, fill=geo_in)
            sp_list = _broadcast_to(source_plane_in, n, fill=source_plane_in)
            tp_list = _broadcast_to(target_plane_in, n, fill=target_plane_in)
            flipx_list = _broadcast_to(flip_x, n, fill=flip_x)
            movez_list = _broadcast_to(move_z, n, fill=move_z)

            so_last, to_last, xf_last, mv_last = None, None, None, None

            rot_iter = rot_list if len(rot_list) > 0 else [0.0] * n

            for g, sp, tp, rd, fx, mz in zip(geo_list, sp_list, tp_list, rot_iter, flipx_list, movez_list):
                so, to, xf, mv = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rd,
                    flip_x=fx,
                    flip_y=0,
                    flip_z=0,
                    move_x=0.0,
                    move_y=0.0,
                    move_z=mz,
                )
                so_last, to_last, xf_last, mv_last = so, to, xf, mv

            self.VSG6_PingJiFang_SourceOut = so_last
            self.VSG6_PingJiFang_TargetOut = to_last
            self.VSG6_PingJiFang_XFormRaw = xf_last
            self.VSG6_PingJiFang_TransformOut = ght.GH_Transform(xf_last) if xf_last is not None else None
            self.VSG6_PingJiFang_MovedGeo = mv_last

        except Exception as e:
            self.Log.append(u"[ERR][Step7-3] VSG6_GA_PingJiFang failed: {}".format(e))
            self.VSG6_PingJiFang_MovedGeo = None

        # =========================================================
        # 7-3) VSG6_GA_ZhuTouFang（Timber-6 -> ShuaTou FacePlaneList(经 VSG4_ShuaTou Transform)）
        # =========================================================
        try:
            geo_in = self.Timber6_TimberBrep

            sp_idx_in = self.All_dict.get("VSG6_GA_ZhuTouFang__SourcePlane", 0)
            sp_idx = _as_int(sp_idx_in, 0)
            source_plane_in = _pick_by_index(self.Timber6_FacePlaneList, sp_idx, None)

            tp_idx_in = self.All_dict.get("VSG6_GA_ZhuTouFang__TargetPlane", 0)
            tp_idx = _as_int(tp_idx_in, 0)

            shuatou_planes = getattr(self, "ShuaTou_FacePlaneList", None)
            x4 = getattr(self, "VSG4_ShuaTou_XFormRaw", None)
            shuatou_planes_x = _transform_planes(shuatou_planes, x4)
            target_plane_in = _pick_by_index(shuatou_planes_x, tp_idx, None)

            flipx_in = self.All_dict.get("VSG6_GA_ZhuTouFang__FlipX", 0)
            flip_x = _as_01(flipx_in, 0)

            so, to, xf, mv = GeoAligner_xfm.align(
                geo_in,
                source_plane_in,
                target_plane_in,
                rotate_deg=0.0,
                flip_x=flip_x,
                flip_y=0,
                flip_z=0,
                move_x=0.0,
                move_y=0.0,
                move_z=0.0,
            )

            self.VSG6_ZhuTouFang_SourceOut = so
            self.VSG6_ZhuTouFang_TargetOut = to
            self.VSG6_ZhuTouFang_XFormRaw = xf
            self.VSG6_ZhuTouFang_TransformOut = ght.GH_Transform(xf) if xf is not None else None
            self.VSG6_ZhuTouFang_MovedGeo = mv

        except Exception as e:
            self.Log.append(u"[ERR][Step7-3] VSG6_GA_ZhuTouFang failed: {}".format(e))
            self.VSG6_ZhuTouFang_MovedGeo = None

    def step8_cube_and_niujifang(self):
        """Step 8: 立方块与牛脊方（襯補，可由 EnableChenBu 控制）"""
        if not getattr(self, 'EnableChenBu', True):
            self.Log.append(
                u"[Step8] EnableChenBu=False → skip Timber-7 / VSG7_GA_Cube-1 / PlaneFromLists::7-1 / VSG7_GA_Cube-2 / LaoYanFang-7 / PlaneFromLists::7-2 / VSG7_GA_NiuJiFang")
            self.VSG7_Cube1_MovedGeo = None
            self.VSG7_Cube2_MovedGeo = None
            self.VSG7_NiuJiFang_MovedGeo = None
            return
        return self._step8_cube_and_niujifang_impl()

    def _step8_cube_and_niujifang_impl(self):
        self.Log.append(
            u"[Step8] Build Timber-7 (Cube), align Cube-1/Cube-2, then build LaoYanFang-7 and align NiuJiFang.")

        # =========================================================
        # 8-1) Timber-7（木料）
        # =========================================================
        try:
            length_in = self.All_dict.get("Timber_7__length_fen", None)
            width_in = self.All_dict.get("Timber_7__width_fen", None)
            height_in = self.All_dict.get("Timber_7__height_fen", None)

            l0 = _ensure_list(length_in)[0] if len(_ensure_list(length_in)) > 0 else None
            w0 = _ensure_list(width_in)[0] if len(_ensure_list(width_in)) > 0 else None
            h0 = _ensure_list(height_in)[0] if len(_ensure_list(height_in)) > 0 else None

            length_fen = float(_as_float_or_list(l0, 32.0))
            width_fen = float(_as_float_or_list(w0, 32.0))
            height_fen = float(_as_float_or_list(h0, 20.0))

            base_point = rg.Point3d(0.0, 0.0, 0.0)

            # reference_plane：沿用 Step7-3 的 GH 参考平面语义（XY/XZ/YZ）
            ref_in = self.All_dict.get("Timber_7__reference_plane", "WorldXZ")
            if ref_in is None or (isinstance(ref_in, str) and ref_in.strip() == ""):
                ref_in = "WorldXZ"

            reference_plane = None
            if isinstance(ref_in, rg.Plane):
                reference_plane = ref_in
            elif hasattr(ref_in, "Plane") and isinstance(getattr(ref_in, "Plane", None), rg.Plane):
                reference_plane = ref_in.Plane

            if reference_plane is None:
                s = str(ref_in).strip()
                s_up = s.replace(" ", "").upper()
                if s_up in ("XY", "XYPLANE", "WORLDXY"):
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 1.0, 0.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                elif s_up in ("XZ", "XZPLANE", "WORLDXZ"):
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                elif s_up in ("YZ", "YZPLANE", "WORLDYZ"):
                    xaxis = rg.Vector3d(0.0, 1.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                else:
                    xaxis = rg.Vector3d(1.0, 0.0, 0.0)
                    yaxis = rg.Vector3d(0.0, 0.0, 1.0)
                    reference_plane = rg.Plane(base_point, xaxis, yaxis)
                    self.Log.append(
                        u"[WARN][Step8] Timber_7__reference_plane unsupported: {} → fallback WorldXZ".format(s))

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
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
            )

            self.Timber7_TimberBrep = timber_brep
            self.Timber7_FaceList = faces
            self.Timber7_PointList = points
            self.Timber7_EdgeList = edges
            self.Timber7_CenterPoint = center_pt
            self.Timber7_CenterAxisLines = center_axes
            self.Timber7_EdgeMidPoints = edge_midpts
            self.Timber7_FacePlaneList = face_planes
            self.Timber7_Corner0Planes = corner0_planes
            self.Timber7_LocalAxesPlane = local_axes_plane
            self.Timber7_AxisX = axis_x
            self.Timber7_AxisY = axis_y
            self.Timber7_AxisZ = axis_z
            self.Timber7_FaceDirTags = face_tags
            self.Timber7_EdgeDirTags = edge_tags
            self.Timber7_Corner0EdgeDirs = corner0_dirs
            self.Timber7_Log = log_lines

        except Exception as e:
            self.Log.append(u"[ERR][Step8] Timber-7 build failed: {}".format(e))
            self.Timber7_TimberBrep = None
            self.Timber7_FacePlaneList = []
            self.Timber7_Log = [u"错误: {}".format(e)]

        # =========================================================
        # 8-2) VSG7_GA_Cube-1（Timber-7 -> BiNeiManGong FacePlaneList（经 VSG4_BiNeiManGong Transform））
        # =========================================================
        try:
            geo_in = self.Timber7_TimberBrep

            sp_idx = _as_int(self.All_dict.get("VSG7_GA_Cube_1__SourcePlane", 0), 0)
            source_plane_in = _pick_by_index(self.Timber7_FacePlaneList, sp_idx, None)

            tp_idx = _as_int(self.All_dict.get("VSG7_GA_Cube_1__TargetPlane", 0), 0)
            binei_planes = getattr(self, "BiNeiManGong_FacePlaneList", None)
            x4 = getattr(self, "VSG4_BiNeiManGong_XFormRaw", None)
            binei_planes_x = _transform_planes(binei_planes, x4)
            target_plane_in = _pick_by_index(binei_planes_x, tp_idx, None)

            # inputs
            rot_in = self.All_dict.get("VSG7_GA_Cube_1__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG7_GA_Cube_1__FlipX", 0)
            flipy_in = self.All_dict.get("VSG7_GA_Cube_1__FlipY", 0)
            flipz_in = self.All_dict.get("VSG7_GA_Cube_1__FlipZ", 0)
            movex_in = self.All_dict.get("VSG7_GA_Cube_1__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG7_GA_Cube_1__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG7_GA_Cube_1__MoveZ", 0.0)

            rot_list = _ensure_list(rot_in)
            fx_list = _ensure_list(flipx_in)
            fy_list = _ensure_list(flipy_in)
            fz_list = _ensure_list(flipz_in)
            mx_list = _ensure_list(movex_in)
            my_list = _ensure_list(movey_in)
            mz_list = _ensure_list(movez_in)

            # 关键：TargetPlane 可能来自变换后的列表；Geo/Plane/TargetPlane 也可能是 list，需参与广播
            geo_raw_list = _ensure_list(geo_in)
            sp_raw_list = _ensure_list(source_plane_in)
            tp_raw_list = _ensure_list(target_plane_in)

            # 广播长度：以 RotateDeg 为主，若其为空则取其它输入的最大长度
            n = len(rot_list)
            n = max(n, len(geo_raw_list), len(sp_raw_list), len(tp_raw_list), len(fx_list), len(fy_list), len(fz_list),
                    len(mx_list), len(my_list), len(mz_list))
            if n <= 0:
                n = 1

            geo_list = _broadcast_to(geo_raw_list, n, fill=geo_in)
            sp_list = _broadcast_to(sp_raw_list, n, fill=source_plane_in)
            tp_list = _broadcast_to(tp_raw_list, n, fill=target_plane_in)

            rot_list = _broadcast_to(rot_list, n, fill=0.0)
            fx_list = _broadcast_to(fx_list, n, fill=0)
            fy_list = _broadcast_to(fy_list, n, fill=0)
            fz_list = _broadcast_to(fz_list, n, fill=0)
            mx_list = _broadcast_to(mx_list, n, fill=0.0)
            my_list = _broadcast_to(my_list, n, fill=0.0)
            mz_list = _broadcast_to(mz_list, n, fill=0.0)

            moved_out = []
            so_last, to_last, x_last = None, None, None

            for i in range(n):
                so, to, xform, moved = GeoAligner_xfm.align(
                    geo_list[i],
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=float(_as_float_or_list(rot_list[i], 0.0)),
                    flip_x=bool(_as_01_or_list(fx_list[i], 0)),
                    flip_y=bool(_as_01_or_list(fy_list[i], 0)),
                    flip_z=bool(_as_01_or_list(fz_list[i], 0)),
                    move_x=float(_as_float_or_list(mx_list[i], 0.0)),
                    move_y=float(_as_float_or_list(my_list[i], 0.0)),
                    move_z=float(_as_float_or_list(mz_list[i], 0.0)),
                )
                so_last, to_last, x_last = so, to, xform
                moved_out.append(moved)

            self.VSG7_Cube1_SourceOut = so_last
            self.VSG7_Cube1_TargetOut = to_last
            self.VSG7_Cube1_XFormRaw = x_last
            self.VSG7_Cube1_TransformOut = ght.GH_Transform(x_last) if x_last is not None else None
            self.VSG7_Cube1_MovedGeo = moved_out if n != 1 else moved_out[0]

        except Exception as e:
            self.Log.append(u"[ERR][Step8] VSG7_GA_Cube-1 failed: {}".format(e))
            self.VSG7_Cube1_MovedGeo = None

        # =========================================================
        # 8-3) PlaneFromLists::7-1（取 BiNeiManGong 角点平面 / 边中点，经 VSG4_BiNeiManGong Transform）
        # =========================================================
        try:
            x4 = getattr(self, "VSG4_BiNeiManGong_XFormRaw", None)
            origin_points = _transform_points(getattr(self, "BiNeiManGong_EdgeMidPoints", None), x4)
            base_planes = _transform_planes(getattr(self, "BiNeiManGong_Corner0Planes", None), x4)

            self.PFL7_1_OriginPoints = origin_points
            self.PFL7_1_BasePlanes = base_planes

            idx_origin_in = self.All_dict.get("PlaneFromLists_7_1__IndexOrigin", 0)
            idx_plane_in = self.All_dict.get("PlaneFromLists_7_1__IndexPlane", 0)
            wrap_in = self.All_dict.get("PlaneFromLists_7_1__Wrap", True)

            idx_origin_list = _ensure_list(idx_origin_in)
            idx_plane_list = _ensure_list(idx_plane_in)
            idx_origin_list, idx_plane_list, n = _broadcast_pair(idx_origin_list, idx_plane_list)

            pfl_builder = FTPlaneFromLists(wrap=bool(wrap_in))

            bp_list, op_list, rp_list = [], [], []
            pfl_logs = []

            for io, ip in zip(idx_origin_list, idx_plane_list):
                bp, op, rp, lg = pfl_builder.build_plane(origin_points, base_planes, io, ip)
                bp_list.append(bp)
                op_list.append(op)
                rp_list.append(rp)
                if lg is not None:
                    if isinstance(lg, (list, tuple)):
                        pfl_logs.extend([str(x) for x in lg])
                    else:
                        pfl_logs.append(str(lg))

            # GH 风格：若只有 1 个结果则输出 item，否则输出 list
            self.PFL7_1_BasePlane = bp_list[0] if len(bp_list) == 1 else bp_list
            self.PFL7_1_OriginPoint = op_list[0] if len(op_list) == 1 else op_list
            self.PFL7_1_ResultPlane = rp_list[0] if len(rp_list) == 1 else rp_list
            self.PFL7_1_Log = pfl_logs

        except Exception as e:
            self.Log.append(u"[ERR][Step8] PlaneFromLists::7-1 failed: {}".format(e))
            self.PFL7_1_ResultPlane = None
            self.PFL7_1_Log = [str(e)]

        # =========================================================
        # 8-4) VSG7_GA_Cube-2（Timber-7 -> PlaneFromLists::7-1 ResultPlane）
        # =========================================================
        try:
            geo_in = self.Timber7_TimberBrep

            sp_idx = _as_int(self.All_dict.get("VSG7_GA_Cube_2__SourcePlane", 0), 0)
            source_plane_in = _pick_by_index(self.Timber7_FacePlaneList, sp_idx, None)
            target_plane_in = self.PFL7_1_ResultPlane

            rot_in = self.All_dict.get("VSG7_GA_Cube_2__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG7_GA_Cube_2__FlipX", 0)
            flipy_in = self.All_dict.get("VSG7_GA_Cube_2__FlipY", 0)
            flipz_in = self.All_dict.get("VSG7_GA_Cube_2__FlipZ", 0)
            movex_in = self.All_dict.get("VSG7_GA_Cube_2__MoveX", 0.0)
            movey_in = self.All_dict.get("VSG7_GA_Cube_2__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG7_GA_Cube_2__MoveZ", 0.0)

            rot_list = _ensure_list(rot_in)
            fx_list = _ensure_list(flipx_in)
            fy_list = _ensure_list(flipy_in)
            fz_list = _ensure_list(flipz_in)
            mx_list = _ensure_list(movex_in)
            my_list = _ensure_list(movey_in)
            mz_list = _ensure_list(movez_in)

            # 关键：VSG7_GA_* 以 Geo 为操作对象；其余输入端按 GH 广播规则对齐
            geo_raw_list = _ensure_list(geo_in)
            sp_raw_list = _ensure_list(source_plane_in)
            tp_raw_list = _ensure_list(target_plane_in)

            n = 1
            n = max(
                n,
                len(geo_raw_list),
                len(sp_raw_list),
                len(tp_raw_list),
                len(rot_list),
                len(fx_list),
                len(fy_list),
                len(fz_list),
                len(mx_list),
                len(my_list),
                len(mz_list),
            )
            if n <= 0:
                n = 1

            geo_list = _broadcast_to(geo_raw_list, n, fill=geo_in)
            sp_list = _broadcast_to(sp_raw_list, n, fill=source_plane_in)
            tp_list = _broadcast_to(tp_raw_list, n, fill=target_plane_in)

            rot_list = _broadcast_to(rot_list, n, fill=0.0)
            fx_list = _broadcast_to(fx_list, n, fill=0)
            fy_list = _broadcast_to(fy_list, n, fill=0)
            fz_list = _broadcast_to(fz_list, n, fill=0)
            mx_list = _broadcast_to(mx_list, n, fill=0.0)
            my_list = _broadcast_to(my_list, n, fill=0.0)
            mz_list = _broadcast_to(mz_list, n, fill=0.0)

            moved_out = []
            so_list, to_list, x_list = [], [], []

            for i in range(n):
                so, to, xform, moved = GeoAligner_xfm.align(
                    geo_list[i],
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=float(_as_float_or_list(rot_list[i], 0.0)),
                    flip_x=bool(_as_01_or_list(fx_list[i], 0)),
                    flip_y=bool(_as_01_or_list(fy_list[i], 0)),
                    flip_z=bool(_as_01_or_list(fz_list[i], 0)),
                    move_x=float(_as_float_or_list(mx_list[i], 0.0)),
                    move_y=float(_as_float_or_list(my_list[i], 0.0)),
                    move_z=float(_as_float_or_list(mz_list[i], 0.0)),
                )
                so_list.append(so)
                to_list.append(to)
                x_list.append(xform)
                moved_out.append(moved)

            # GH 风格：若 n==1 输出 item，否则输出 list
            self.VSG7_Cube2_SourceOut = so_list[0] if n == 1 else so_list
            self.VSG7_Cube2_TargetOut = to_list[0] if n == 1 else to_list
            self.VSG7_Cube2_XFormRaw = x_list[0] if n == 1 else x_list
            self.VSG7_Cube2_TransformOut = (
                ght.GH_Transform(x_list[0]) if (n == 1 and x_list[0] is not None) else
                [ght.GH_Transform(x) if x is not None else None for x in x_list]
            )
            self.VSG7_Cube2_MovedGeo = moved_out[0] if n == 1 else moved_out

        except Exception as e:
            self.Log.append(u"[ERR][Step8] VSG7_GA_Cube-2 failed: {}".format(e))
            self.VSG7_Cube2_MovedGeo = None

        # =========================================================
        # 8-5) LaoYanFang-7（牛脊方刀具本体：RuFangEaveToolBuilder）
        # =========================================================
        try:
            input_point = rg.Point3d(0.0, 0.0, 0.0)

            width_in = self.All_dict.get("LaoYanFang_7__WidthFen", None)
            height_in = self.All_dict.get("LaoYanFang_7__HeightFen", None)
            extrude_in = self.All_dict.get("LaoYanFang_7__ExtrudeFen", None)

            w0 = _ensure_list(width_in)[0] if len(_ensure_list(width_in)) > 0 else None
            h0 = _ensure_list(height_in)[0] if len(_ensure_list(height_in)) > 0 else None
            e0 = _ensure_list(extrude_in)[0] if len(_ensure_list(extrude_in)) > 0 else None

            width_fen = float(_as_float_or_list(w0, 10.0))
            height_fen = float(_as_float_or_list(h0, 30.0))
            extrude_fen = float(_as_float_or_list(e0, 100.0))

            # 可选 RefPlane（与 ghpy 一致：允许 None）
            ref_plane_in = self.All_dict.get("LaoYanFang_7__RefPlane", None)
            ref_plane = None
            if isinstance(ref_plane_in, rg.Plane):
                ref_plane = ref_plane_in
            elif hasattr(ref_plane_in, "Plane") and isinstance(getattr(ref_plane_in, "Plane", None), rg.Plane):
                ref_plane = ref_plane_in.Plane

            builder = RuFangEaveToolBuilder(
                input_point=input_point,
                ref_plane=ref_plane,
                width_fen=width_fen,
                height_fen=height_fen,
                extrude_fen=extrude_fen
            )

            result = builder.build() or {}

            self.LaoYanFang7_EveTool = result.get("EveTool", None)
            self.LaoYanFang7_Section = result.get("Section", None)
            self.LaoYanFang7_SectionVertices = result.get("SectionVertices", None)
            self.LaoYanFang7_SectionVertexNames = result.get("SectionVertexNames", None)
            self.LaoYanFang7_RectEdgeMidPoints = result.get("RectEdgeMidPoints", None)
            self.LaoYanFang7_RectEdgeNames = result.get("RectEdgeNames", None)
            self.LaoYanFang7_RefPlaneList = result.get("RefPlaneList", None)
            self.LaoYanFang7_RefPlaneNames = result.get("RefPlaneNames", None)

            rlog = result.get("Log", [])
            if isinstance(rlog, (list, tuple)):
                self.LaoYanFang7_Log = [str(x) for x in rlog]
            elif rlog is not None:
                self.LaoYanFang7_Log = [str(rlog)]
            else:
                self.LaoYanFang7_Log = []

        except Exception as e:
            self.Log.append(u"[ERR][Step8] LaoYanFang-7 build failed: {}".format(e))
            self.LaoYanFang7_EveTool = None
            self.LaoYanFang7_RectEdgeMidPoints = None
            self.LaoYanFang7_RefPlaneList = None
            self.LaoYanFang7_Log = [str(e)]

        # =========================================================
        # 8-6) PlaneFromLists::7-2（LaoYanFang-7 RectEdgeMidPoints / RefPlaneList）
        # =========================================================
        try:
            origin_points = self.LaoYanFang7_RectEdgeMidPoints
            base_planes = self.LaoYanFang7_RefPlaneList

            idx_origin_in = self.All_dict.get("PlaneFromLists_7_2__IndexOrigin", 0)
            idx_plane_in = self.All_dict.get("PlaneFromLists_7_2__IndexPlane", 0)
            wrap_in = self.All_dict.get("PlaneFromLists_7_2__Wrap", True)

            idx_origin_list = _ensure_list(idx_origin_in)
            idx_plane_list = _ensure_list(idx_plane_in)
            idx_origin_list, idx_plane_list, n = _broadcast_pair(idx_origin_list, idx_plane_list)

            pfl_builder = FTPlaneFromLists(wrap=bool(wrap_in))

            bp_last, op_last, rp_last = None, None, None
            pfl_logs = []

            for io, ip in zip(idx_origin_list, idx_plane_list):
                bp, op, rp, lg = pfl_builder.build_plane(origin_points, base_planes, io, ip)
                bp_last, op_last, rp_last = bp, op, rp
                if lg is not None:
                    if isinstance(lg, (list, tuple)):
                        pfl_logs.extend([str(x) for x in lg])
                    else:
                        pfl_logs.append(str(lg))

            self.PFL7_2_BasePlane = bp_last
            self.PFL7_2_OriginPoint = op_last
            self.PFL7_2_ResultPlane = rp_last
            self.PFL7_2_Log = pfl_logs

        except Exception as e:
            self.Log.append(u"[ERR][Step8] PlaneFromLists::7-2 failed: {}".format(e))
            self.PFL7_2_ResultPlane = None
            self.PFL7_2_Log = [str(e)]

        # =========================================================
        # 8-7) VSG7_GA_NiuJiFang（LaoYanFang-7 -> Timber-7 FacePlaneList[Cube-1 SourcePlane]（经 VSG7_Cube-1 Transform））
        # =========================================================
        try:
            geo_in = self.LaoYanFang7_EveTool
            source_plane_in = self.PFL7_2_ResultPlane

            # Timber-7 FacePlaneList: index 与 VSG7_GA_Cube_1__SourcePlane 一致
            sp_idx = _as_int(self.All_dict.get("VSG7_GA_Cube_1__SourcePlane", 0), 0)
            timber7_plane = _pick_by_index(self.Timber7_FacePlaneList, sp_idx, None)
            x1 = getattr(self, "VSG7_Cube1_XFormRaw", None)
            target_plane_in = _transform_planes([timber7_plane], x1)[0] if timber7_plane is not None else None

            movey_in = self.All_dict.get("VSG7_GA_NiuJiFang__MoveY", 0.0)
            movez_in = self.All_dict.get("VSG7_GA_NiuJiFang__MoveZ", 0.0)

            rot_in = self.All_dict.get("VSG7_GA_NiuJiFang__RotateDeg", 0.0)
            flipx_in = self.All_dict.get("VSG7_GA_NiuJiFang__FlipX", 0)
            flipy_in = self.All_dict.get("VSG7_GA_NiuJiFang__FlipY", 0)
            flipz_in = self.All_dict.get("VSG7_GA_NiuJiFang__FlipZ", 0)
            movex_in = self.All_dict.get("VSG7_GA_NiuJiFang__MoveX", 0.0)

            geo_list = _ensure_list(geo_in)
            sp_list = _ensure_list(source_plane_in)
            tp_list = _ensure_list(target_plane_in)

            rot_list = _ensure_list(rot_in)
            fx_list = _ensure_list(flipx_in)
            fy_list = _ensure_list(flipy_in)
            fz_list = _ensure_list(flipz_in)
            mx_list = _ensure_list(movex_in)
            my_list = _ensure_list(movey_in)
            mz_list = _ensure_list(movez_in)

            n = len(rot_list)
            n = max(n, len(fx_list), len(fy_list), len(fz_list), len(mx_list), len(my_list), len(mz_list),
                    len(geo_list), len(sp_list), len(tp_list))
            if n <= 0:
                n = 1

            geo_list = _broadcast_to(geo_list, n, fill=geo_in)
            sp_list = _broadcast_to(sp_list, n, fill=source_plane_in)
            tp_list = _broadcast_to(tp_list, n, fill=target_plane_in)
            rot_list = _broadcast_to(rot_list, n, fill=0.0)
            fx_list = _broadcast_to(fx_list, n, fill=0)
            fy_list = _broadcast_to(fy_list, n, fill=0)
            fz_list = _broadcast_to(fz_list, n, fill=0)
            mx_list = _broadcast_to(mx_list, n, fill=0.0)
            my_list = _broadcast_to(my_list, n, fill=0.0)
            mz_list = _broadcast_to(mz_list, n, fill=0.0)

            moved_out = []
            so_last, to_last, x_last = None, None, None

            for i in range(n):
                so, to, xform, moved = GeoAligner_xfm.align(
                    geo_list[i],
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=float(_as_float_or_list(rot_list[i], 0.0)),
                    flip_x=bool(_as_01_or_list(fx_list[i], 0)),
                    flip_y=bool(_as_01_or_list(fy_list[i], 0)),
                    flip_z=bool(_as_01_or_list(fz_list[i], 0)),
                    move_x=float(_as_float_or_list(mx_list[i], 0.0)),
                    move_y=float(_as_float_or_list(my_list[i], 0.0)),
                    move_z=float(_as_float_or_list(mz_list[i], 0.0)),
                )
                so_last, to_last, x_last = so, to, xform
                moved_out.append(moved)

            self.VSG7_NiuJiFang_SourceOut = so_last
            self.VSG7_NiuJiFang_TargetOut = to_last
            self.VSG7_NiuJiFang_XFormRaw = x_last
            self.VSG7_NiuJiFang_TransformOut = ght.GH_Transform(x_last) if x_last is not None else None
            self.VSG7_NiuJiFang_MovedGeo = moved_out if n != 1 else moved_out[0]

        except Exception as e:
            self.Log.append(u"[ERR][Step8] VSG7_GA_NiuJiFang failed: {}".format(e))
            self.VSG7_NiuJiFang_MovedGeo = None

    def run(self):
        # PlacePlane 默认值处理（输入端优先）
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self._handle_refresh()
        self.step1_read_db()
        self.step2_ludou_and_align()
        self.step3_nidaogong_huagong_and_align()
        self.step4_jiaohudou_sandou_and_align()
        self.step5_bineimangong_shuatou_linggong_and_align()
        self.step6_sandou_jiaohudou_stage5_and_align()
        self.step7_chenfangtou_and_align()

        # Step 9：襯補计算开关（默认 True）
        if getattr(self, 'EnableChenBu', True):
            self.step7_2_laoyanfang_and_align()
            self.step7_3_timber6_and_align_pingjifang_zhutoufang()
            self.step8_cube_and_niujifang()
        else:
            self.Log.append(u"[Step9] EnableChenBu=False → skip all ChenBu alignment steps (VSG6/VSG7)")

        self.build_component_assembly()

        # 汇总 Log：把各子 solver 的日志也并进来（如果有）
        try:
            for attr in [
                'LUDou_Log', 'NiDaoGong_Log', 'HuaGong_Log', 'JiaoHuDou_Log', 'SanDou_Log',
                'PFL3_1_Log', 'PFL3_2_Log', 'BiNeiManGong_Log', 'ShuaTou_Log', 'LingGong_Log',
                'PFL5_1_Log', 'PFL5_2_Log', 'JiaoHuDou_DouKouTiao_Log'
            ]:
                lg = getattr(self, attr, None)
                if lg:
                    self.Log.extend(_ensure_list(lg))
        except Exception:
            pass

        return self

    def _run_impl(self):
        # PlacePlane 默认值处理（输入端优先）
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self._handle_refresh()
        self.step1_read_db()
        self.step2_ludou_and_align()
        self.step3_nidaogong_huagong_and_align()
        self.step4_jiaohudou_sandou_and_align()
        self.step5_bineimangong_shuatou_linggong_and_align()
        self.step6_sandou_jiaohudou_stage5_and_align()
        self.step7_chenfangtou_and_align()
        self.step7_2_laoyanfang_and_align()
        self.step7_3_timber6_and_align_pingjifang_zhutoufang()
        self.step8_cube_and_niujifang()
        self.build_component_assembly()

        # 汇总 Log：把 LuDou solver 内部日志也并进来（如果有）
        try:
            if self.LUDou_Log:
                self.Log.extend(_ensure_list(self.LUDou_Log))
            if self.NiDaoGong_Log:
                self.Log.extend(_ensure_list(self.NiDaoGong_Log))
            if self.HuaGong_Log:
                self.Log.extend(_ensure_list(self.HuaGong_Log))
            if self.JiaoHuDou_Log:
                self.Log.extend(_ensure_list(self.JiaoHuDou_Log))
            if self.SanDou_Log:
                self.Log.extend(_ensure_list(self.SanDou_Log))
            if self.PFL3_1_Log:
                self.Log.extend(_ensure_list(self.PFL3_1_Log))
            if self.PFL3_2_Log:
                self.Log.extend(_ensure_list(self.PFL3_2_Log))
            if self.BiNeiManGong_Log:
                self.Log.extend(_ensure_list(self.BiNeiManGong_Log))
            if self.ShuaTou_Log:
                self.Log.extend(_ensure_list(self.ShuaTou_Log))
            if self.LingGong_Log:
                self.Log.extend(_ensure_list(self.LingGong_Log))
            if self.PFL5_1_Log:
                self.Log.extend(_ensure_list(self.PFL5_1_Log))
            if self.PFL5_2_Log:
                self.Log.extend(_ensure_list(self.PFL5_2_Log))
            if self.JiaoHuDou_DouKouTiao_Log:
                self.Log.extend(_ensure_list(self.JiaoHuDou_DouKouTiao_Log))
        except:
            pass

        return self


# =========================================================
# GH Python 组件入口 + 输出绑定区
#   - 输出端至少包含：ComponentAssembly, Log
#   - 其余输出端：按需在 GH 中添加同名输出端即可看到内部数据
# =========================================================

if __name__ == "__main__":

    # ---- 输入默认值（优先级：输入端 > 数据库 > 默认；此处仅处理输入端自身缺省）----
    if "Refresh" not in globals() or Refresh is None:
        Refresh = False

    # PlacePlane：如果输入端没接，则默认 XY Plane (100,100,0)
    if "PlacePlane" not in globals():
        PlacePlane = None
    if PlacePlane is None:
        PlacePlane = _default_place_plane()

    # Step 9：襯補计算开关（输入端 Bool；默认 True）
    if "EnableChenBu" not in globals() or EnableChenBu is None:
        EnableChenBu = True

    solver = SiPU_ChaAng_InfillPUComponentAssemblySolver(
        DBPath,
        PlacePlane,
        Refresh,
        ghenv,
        EnableChenBu=EnableChenBu
    ).run()

    # ======= 最终输出（你要求的两个端口）=======
    ComponentAssembly = solver.ComponentAssembly
    Log = solver.Log

    # ======= Step1：DB 输出（保留，便于后续调试/扩展）=======
    Value = solver.Value
    All = solver.All
    All_dict = solver.All_dict
    DBLog = solver.DBLog

    # ======= Step2：LuDou 全部中间输出（保留）=======
    LUDou_Value = solver.LUDou_Value
    LUDou_All = solver.LUDou_All
    LUDou_All_dict = solver.LUDou_All_dict

    LUDou_TimberBrep = solver.LUDou_TimberBrep
    LUDou_FaceList = solver.LUDou_FaceList
    LUDou_PointList = solver.LUDou_PointList
    LUDou_EdgeList = solver.LUDou_EdgeList
    LUDou_CenterPoint = solver.LUDou_CenterPoint
    LUDou_CenterAxisLines = solver.LUDou_CenterAxisLines
    LUDou_EdgeMidPoints = solver.LUDou_EdgeMidPoints
    LUDou_FacePlaneList = solver.LUDou_FacePlaneList
    LUDou_Corner0Planes = solver.LUDou_Corner0Planes
    LUDou_LocalAxesPlane = solver.LUDou_LocalAxesPlane
    LUDou_AxisX = solver.LUDou_AxisX
    LUDou_AxisY = solver.LUDou_AxisY
    LUDou_AxisZ = solver.LUDou_AxisZ
    LUDou_FaceDirTags = solver.LUDou_FaceDirTags
    LUDou_EdgeDirTags = solver.LUDou_EdgeDirTags
    LUDou_Corner0EdgeDirs = solver.LUDou_Corner0EdgeDirs

    LUDou_BasePlane1 = solver.LUDou_BasePlane1
    LUDou_OriginPoint1 = solver.LUDou_OriginPoint1
    LUDou_ResultPlane1 = solver.LUDou_ResultPlane1

    LUDou_BasePlane2 = solver.LUDou_BasePlane2
    LUDou_OriginPoint2 = solver.LUDou_OriginPoint2
    LUDou_ResultPlane2 = solver.LUDou_ResultPlane2

    LUDou_BasePlane3 = solver.LUDou_BasePlane3
    LUDou_OriginPoint3 = solver.LUDou_OriginPoint3
    LUDou_ResultPlane3 = solver.LUDou_ResultPlane3

    LUDou_ToolBrep = solver.LUDou_ToolBrep
    LUDou_BasePoint = solver.LUDou_BasePoint
    LUDou_BaseLine = solver.LUDou_BaseLine
    LUDou_SecPlane = solver.LUDou_SecPlane
    LUDou_FacePlane = solver.LUDou_FacePlane

    LUDou_AlignedTool = solver.LUDou_AlignedTool
    LUDou_XForm = solver.LUDou_XForm
    LUDou_SourcePlane = solver.LUDou_SourcePlane
    LUDou_TargetPlane = solver.LUDou_TargetPlane
    LUDou_SourcePoint = solver.LUDou_SourcePoint
    LUDou_TargetPoint = solver.LUDou_TargetPoint
    LUDou_DebugInfo = solver.LUDou_DebugInfo

    LUDou_BlockTimbers = solver.LUDou_BlockTimbers

    LUDou_AlignedTool2 = solver.LUDou_AlignedTool2
    LUDou_XForm2 = solver.LUDou_XForm2
    LUDou_SourcePlane2 = solver.LUDou_SourcePlane2
    LUDou_TargetPlane2 = solver.LUDou_TargetPlane2
    LUDou_SourcePoint2 = solver.LUDou_SourcePoint2
    LUDou_TargetPoint2 = solver.LUDou_TargetPoint2
    LUDou_DebugInfo2 = solver.LUDou_DebugInfo2

    LUDou_CutTimbers = solver.LUDou_CutTimbers
    LUDou_FailTimbers = solver.LUDou_FailTimbers
    LUDou_Log = solver.LUDou_Log

    # ======= Step2b：VSG1 对位输出（保留）=======
    VSG1_SourceOut = solver.VSG1_SourceOut
    VSG1_TargetOut = solver.VSG1_TargetOut
    VSG1_TransformOut = solver.VSG1_TransformOut
    VSG1_MovedGeo = solver.VSG1_MovedGeo

    # ======= Step3：NiDaoGong / HuaGong + VSG2 对位输出（保留）=======
    NiDaoGong_CutTimbers = solver.NiDaoGong_CutTimbers
    NiDaoGong_FailTimbers = solver.NiDaoGong_FailTimbers
    NiDaoGong_FacePlaneList = solver.NiDaoGong_FacePlaneList
    NiDaoGong_Log = solver.NiDaoGong_Log

    VSG2_NiDaoGong_SourceOut = solver.VSG2_NiDaoGong_SourceOut
    VSG2_NiDaoGong_TargetOut = solver.VSG2_NiDaoGong_TargetOut
    VSG2_NiDaoGong_TransformOut = solver.VSG2_NiDaoGong_TransformOut
    VSG2_NiDaoGong_MovedGeo = solver.VSG2_NiDaoGong_MovedGeo

    HuaGong_CutTimbers = solver.HuaGong_CutTimbers
    HuaGong_FailTimbers = solver.HuaGong_FailTimbers
    HuaGong_FacePlaneList = solver.HuaGong_FacePlaneList
    HuaGong_Log = solver.HuaGong_Log

    VSG2_HuaGong_SourceOut = solver.VSG2_HuaGong_SourceOut
    VSG2_HuaGong_TargetOut = solver.VSG2_HuaGong_TargetOut
    VSG2_HuaGong_TransformOut = solver.VSG2_HuaGong_TransformOut
    VSG2_HuaGong_MovedGeo = solver.VSG2_HuaGong_MovedGeo

    # ======= Step4：JiaoHuDou / SanDou + PlaneFromLists + VSG3 对位输出（保留）=======
    JiaoHuDou_CutTimbers = solver.JiaoHuDou_CutTimbers
    JiaoHuDou_FailTimbers = solver.JiaoHuDou_FailTimbers
    JiaoHuDou_FacePlaneList = solver.JiaoHuDou_FacePlaneList
    JiaoHuDou_Log = solver.JiaoHuDou_Log

    PFL3_1_OriginPoints = solver.PFL3_1_OriginPoints
    PFL3_1_BasePlanes = solver.PFL3_1_BasePlanes
    PFL3_1_BasePlane = solver.PFL3_1_BasePlane
    PFL3_1_OriginPoint = solver.PFL3_1_OriginPoint
    PFL3_1_ResultPlane = solver.PFL3_1_ResultPlane
    PFL3_1_Log = solver.PFL3_1_Log

    VSG3_JiaoHuDou_SourceOut = solver.VSG3_JiaoHuDou_SourceOut
    VSG3_JiaoHuDou_TargetOut = solver.VSG3_JiaoHuDou_TargetOut
    VSG3_JiaoHuDou_TransformOut = solver.VSG3_JiaoHuDou_TransformOut
    VSG3_JiaoHuDou_MovedGeo = solver.VSG3_JiaoHuDou_MovedGeo

    SanDou_CutTimbers = solver.SanDou_CutTimbers
    SanDou_FailTimbers = solver.SanDou_FailTimbers
    SanDou_FacePlaneList = solver.SanDou_FacePlaneList
    SanDou_Log = solver.SanDou_Log

    PFL3_2_OriginPoints = solver.PFL3_2_OriginPoints
    PFL3_2_BasePlanes = solver.PFL3_2_BasePlanes
    PFL3_2_BasePlane = solver.PFL3_2_BasePlane
    PFL3_2_OriginPoint = solver.PFL3_2_OriginPoint
    PFL3_2_ResultPlane = solver.PFL3_2_ResultPlane
    PFL3_2_Log = solver.PFL3_2_Log

    VSG3_SanDou_SourceOut = solver.VSG3_SanDou_SourceOut
    VSG3_SanDou_TargetOut = solver.VSG3_SanDou_TargetOut
    VSG3_SanDou_TransformOut = solver.VSG3_SanDou_TransformOut
    VSG3_SanDou_MovedGeo = solver.VSG3_SanDou_MovedGeo

    # ======= Step5：BiNeiManGong / ShuaTou / LingGong + VSG4 对位输出（保留）=======
    BiNeiManGong_CutTimbers = solver.BiNeiManGong_CutTimbers
    BiNeiManGong_FailTimbers = solver.BiNeiManGong_FailTimbers
    BiNeiManGong_FacePlaneList = solver.BiNeiManGong_FacePlaneList
    BiNeiManGong_CutTimbersPlusAnZhi = solver.BiNeiManGong_CutTimbersPlusAnZhi
    BiNeiManGong_Log = solver.BiNeiManGong_Log

    VSG4_BiNeiManGong_SourceOut = solver.VSG4_BiNeiManGong_SourceOut
    VSG4_BiNeiManGong_TargetOut = solver.VSG4_BiNeiManGong_TargetOut
    VSG4_BiNeiManGong_TransformOut = solver.VSG4_BiNeiManGong_TransformOut
    VSG4_BiNeiManGong_MovedGeo = solver.VSG4_BiNeiManGong_MovedGeo

    ShuaTou_CutTimbers = solver.ShuaTou_CutTimbers
    ShuaTou_FailTimbers = solver.ShuaTou_FailTimbers
    ShuaTou_FacePlaneList = solver.ShuaTou_FacePlaneList
    ShuaTou_Log = solver.ShuaTou_Log

    VSG4_ShuaTou_SourceOut = solver.VSG4_ShuaTou_SourceOut
    VSG4_ShuaTou_TargetOut = solver.VSG4_ShuaTou_TargetOut
    VSG4_ShuaTou_TransformOut = solver.VSG4_ShuaTou_TransformOut
    VSG4_ShuaTou_MovedGeo = solver.VSG4_ShuaTou_MovedGeo

    LingGong_CutTimbers = solver.LingGong_CutTimbers
    LingGong_FailTimbers = solver.LingGong_FailTimbers
    LingGong_FacePlaneList = solver.LingGong_FacePlaneList
    LingGong_Log = solver.LingGong_Log

    VSG4_LingGong_SourceOut = solver.VSG4_LingGong_SourceOut
    VSG4_LingGong_TargetOut = solver.VSG4_LingGong_TargetOut
    VSG4_LingGong_TransformOut = solver.VSG4_LingGong_TransformOut
    VSG4_LingGong_MovedGeo = solver.VSG4_LingGong_MovedGeo

    # ======= Step6：SanDou / Jiaohudou-DouKouTiao + PlaneFromLists::5-* + VSG5 对位输出（保留）=======
    PFL5_1_OriginPointsTree = solver.PFL5_1_OriginPointsTree
    PFL5_1_BasePlanesTree = solver.PFL5_1_BasePlanesTree
    PFL5_1_BasePlane = solver.PFL5_1_BasePlane
    PFL5_1_OriginPoint = solver.PFL5_1_OriginPoint
    PFL5_1_ResultPlane = solver.PFL5_1_ResultPlane
    PFL5_1_Log = solver.PFL5_1_Log

    VSG5_SanDou_LingGong_SourceOut = solver.VSG5_SanDou_LingGong_SourceOut
    VSG5_SanDou_LingGong_TargetOut = solver.VSG5_SanDou_LingGong_TargetOut
    VSG5_SanDou_LingGong_TransformOut = solver.VSG5_SanDou_LingGong_TransformOut
    VSG5_SanDou_LingGong_MovedGeo = solver.VSG5_SanDou_LingGong_MovedGeo

    PFL5_2_OriginPoints = solver.PFL5_2_OriginPoints
    PFL5_2_BasePlanes = solver.PFL5_2_BasePlanes
    PFL5_2_BasePlane = solver.PFL5_2_BasePlane
    PFL5_2_OriginPoint = solver.PFL5_2_OriginPoint
    PFL5_2_ResultPlane = solver.PFL5_2_ResultPlane
    PFL5_2_Log = solver.PFL5_2_Log

    VSG5_SanDou_BiNeiManGong_SourceOut = solver.VSG5_SanDou_BiNeiManGong_SourceOut
    VSG5_SanDou_BiNeiManGong_TargetOut = solver.VSG5_SanDou_BiNeiManGong_TargetOut
    VSG5_SanDou_BiNeiManGong_TransformOut = solver.VSG5_SanDou_BiNeiManGong_TransformOut
    VSG5_SanDou_BiNeiManGong_MovedGeo = solver.VSG5_SanDou_BiNeiManGong_MovedGeo

    JiaoHuDou_DouKouTiao_CutTimbers = solver.JiaoHuDou_DouKouTiao_CutTimbers
    JiaoHuDou_DouKouTiao_FailTimbers = solver.JiaoHuDou_DouKouTiao_FailTimbers
    JiaoHuDou_DouKouTiao_FacePlaneList = solver.JiaoHuDou_DouKouTiao_FacePlaneList
    JiaoHuDou_DouKouTiao_Log = solver.JiaoHuDou_DouKouTiao_Log

    VSG5_JiaoHuDou_LingGong_SourceOut = solver.VSG5_JiaoHuDou_LingGong_SourceOut
    VSG5_JiaoHuDou_LingGong_TargetOut = solver.VSG5_JiaoHuDou_LingGong_TargetOut
    VSG5_JiaoHuDou_LingGong_TransformOut = solver.VSG5_JiaoHuDou_LingGong_TransformOut
    VSG5_JiaoHuDou_LingGong_MovedGeo = solver.VSG5_JiaoHuDou_LingGong_MovedGeo

    # =========================================================
    # Step7-1：襯方頭（ChenFangTou）+ 对位（VSG6）
    # =========================================================
    ChenFangTou_solver = solver.ChenFangTou_solver
    ChenFangTou_CutTimbers = solver.ChenFangTou_CutTimbers
    ChenFangTou_FailTimbers = solver.ChenFangTou_FailTimbers
    ChenFangTou_FacePlaneList = solver.ChenFangTou_FacePlaneList
    ChenFangTou_Log = solver.ChenFangTou_Log

    VSG6_SourceOut = solver.VSG6_SourceOut
    VSG6_TargetOut = solver.VSG6_TargetOut
    VSG6_XFormRaw = solver.VSG6_XFormRaw
    VSG6_TransformOut = solver.VSG6_TransformOut
    VSG6_MovedGeo = solver.VSG6_MovedGeo

    # ======= Step7-2：LaoYanFang-6 / PlaneFromLists::6-1 / VSG6_GA_LaoYanFang（开发模式输出）=======
    LaoYanFang6_EveTool = solver.LaoYanFang6_EveTool
    LaoYanFang6_Section = solver.LaoYanFang6_Section
    LaoYanFang6_SectionVertices = solver.LaoYanFang6_SectionVertices
    LaoYanFang6_SectionVertexNames = solver.LaoYanFang6_SectionVertexNames
    LaoYanFang6_RectEdgeMidPoints = solver.LaoYanFang6_RectEdgeMidPoints
    LaoYanFang6_RectEdgeNames = solver.LaoYanFang6_RectEdgeNames
    LaoYanFang6_RefPlaneList = solver.LaoYanFang6_RefPlaneList
    LaoYanFang6_RefPlaneNames = solver.LaoYanFang6_RefPlaneNames
    LaoYanFang6_Log = solver.LaoYanFang6_Log

    PFL6_1_BasePlane = solver.PFL6_1_BasePlane
    PFL6_1_OriginPoint = solver.PFL6_1_OriginPoint
    PFL6_1_ResultPlane = solver.PFL6_1_ResultPlane
    PFL6_1_Log = solver.PFL6_1_Log

    VSG6_LaoYanFang_SourceOut = solver.VSG6_LaoYanFang_SourceOut
    VSG6_LaoYanFang_TargetOut = solver.VSG6_LaoYanFang_TargetOut
    VSG6_LaoYanFang_XFormRaw = solver.VSG6_LaoYanFang_XFormRaw
    VSG6_LaoYanFang_TransformOut = solver.VSG6_LaoYanFang_TransformOut
    VSG6_LaoYanFang_MovedGeo = solver.VSG6_LaoYanFang_MovedGeo

    # ======= Step7-3：Timber-6 / VSG6_GA_PingJiFang / VSG6_GA_ZhuTouFang（开发模式输出）=======
    Timber6_TimberBrep = solver.Timber6_TimberBrep
    Timber6_FacePlaneList = solver.Timber6_FacePlaneList
    Timber6_Log = solver.Timber6_Log

    VSG6_PingJiFang_SourceOut = solver.VSG6_PingJiFang_SourceOut
    VSG6_PingJiFang_TargetOut = solver.VSG6_PingJiFang_TargetOut
    VSG6_PingJiFang_XFormRaw = solver.VSG6_PingJiFang_XFormRaw
    VSG6_PingJiFang_TransformOut = solver.VSG6_PingJiFang_TransformOut
    VSG6_PingJiFang_MovedGeo = solver.VSG6_PingJiFang_MovedGeo

    VSG6_ZhuTouFang_SourceOut = solver.VSG6_ZhuTouFang_SourceOut
    VSG6_ZhuTouFang_TargetOut = solver.VSG6_ZhuTouFang_TargetOut
    VSG6_ZhuTouFang_XFormRaw = solver.VSG6_ZhuTouFang_XFormRaw
    VSG6_ZhuTouFang_TransformOut = solver.VSG6_ZhuTouFang_TransformOut
    VSG6_ZhuTouFang_MovedGeo = solver.VSG6_ZhuTouFang_MovedGeo

    # ======= Step8：Timber-7 / Cube-1 / PlaneFromLists::7-1 / Cube-2 / LaoYanFang-7 / PlaneFromLists::7-2 / NiuJiFang（开发模式输出）=======
    Timber7_TimberBrep = solver.Timber7_TimberBrep
    Timber7_FacePlaneList = solver.Timber7_FacePlaneList
    Timber7_EdgeMidPoints = solver.Timber7_EdgeMidPoints
    Timber7_Corner0Planes = solver.Timber7_Corner0Planes
    Timber7_Log = solver.Timber7_Log

    VSG7_Cube1_SourceOut = solver.VSG7_Cube1_SourceOut
    VSG7_Cube1_TargetOut = solver.VSG7_Cube1_TargetOut
    VSG7_Cube1_XFormRaw = solver.VSG7_Cube1_XFormRaw
    VSG7_Cube1_TransformOut = solver.VSG7_Cube1_TransformOut
    VSG7_Cube1_MovedGeo = solver.VSG7_Cube1_MovedGeo

    PFL7_1_OriginPoints = solver.PFL7_1_OriginPoints
    PFL7_1_BasePlanes = solver.PFL7_1_BasePlanes
    PFL7_1_BasePlane = solver.PFL7_1_BasePlane
    PFL7_1_OriginPoint = solver.PFL7_1_OriginPoint
    PFL7_1_ResultPlane = solver.PFL7_1_ResultPlane
    PFL7_1_Log = solver.PFL7_1_Log

    VSG7_Cube2_SourceOut = solver.VSG7_Cube2_SourceOut
    VSG7_Cube2_TargetOut = solver.VSG7_Cube2_TargetOut
    VSG7_Cube2_XFormRaw = solver.VSG7_Cube2_XFormRaw
    VSG7_Cube2_TransformOut = solver.VSG7_Cube2_TransformOut
    VSG7_Cube2_MovedGeo = solver.VSG7_Cube2_MovedGeo

    LaoYanFang7_EveTool = solver.LaoYanFang7_EveTool
    LaoYanFang7_RectEdgeMidPoints = solver.LaoYanFang7_RectEdgeMidPoints
    LaoYanFang7_RefPlaneList = solver.LaoYanFang7_RefPlaneList
    LaoYanFang7_Log = solver.LaoYanFang7_Log

    PFL7_2_BasePlane = solver.PFL7_2_BasePlane
    PFL7_2_OriginPoint = solver.PFL7_2_OriginPoint
    PFL7_2_ResultPlane = solver.PFL7_2_ResultPlane
    PFL7_2_Log = solver.PFL7_2_Log

    VSG7_NiuJiFang_SourceOut = solver.VSG7_NiuJiFang_SourceOut
    VSG7_NiuJiFang_TargetOut = solver.VSG7_NiuJiFang_TargetOut
    VSG7_NiuJiFang_XFormRaw = solver.VSG7_NiuJiFang_XFormRaw
    VSG7_NiuJiFang_TransformOut = solver.VSG7_NiuJiFang_TransformOut
    VSG7_NiuJiFang_MovedGeo = solver.VSG7_NiuJiFang_MovedGeo

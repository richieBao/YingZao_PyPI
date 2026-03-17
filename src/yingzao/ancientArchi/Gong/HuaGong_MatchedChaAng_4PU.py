# -*- coding: utf-8 -*-
"""
HuaGong_MatchedChaAng_4PU · Step 1（DBJsonReader）+ Step 2（Timber_block_uniform）+ Step 3（卷殺 Juansha）

目标：
- 将“華栱_四鋪作裏外並一抄卷頭（HuaGong_4PU_INOUT_1ChaoJuantou）”的多组件流程，
  逐步合并为单一 GhPython 组件（数据库驱动 + developer-friendly 输出）。

已完成步骤：
1) Step 1：读取数据库
   - Table     = DG_Dou
   - KeyField  = type_code
   - KeyValue  = HuaGong_4PU_INOUT_1ChaoJuantou
   - Field     = params_json
   - ExportAll = True
   输出：
   - Value, All, AllDict, DBLog

2) Step 2：原始木料构建（Timber_block_uniform）
   输入端：
   - length_fen  = Timber_block_uniform__length_fen（来自 AllDict；无则默认）
   - width_fen   = Timber_block_uniform__width_fen（来自 AllDict；无则默认）
   - height_fen  = Timber_block_uniform__height_fen（来自 AllDict；无则默认）
   - base_point  = 组件输入端 base_point（None → 原点）
   - reference_plane = 默认 GH 的 XZ Plane
     XZ Plane 轴向（按你给出的 GH 定义）：
       X = (1,0,0)
       Y = (0,0,1)
       Z = (0,-1,0)

说明：
- 参数优先级：组件输入端（若存在同名输入变量） > 数据库 AllDict > 默认
  当前组件“强制要求仅 3 个输入端（DBPath/base_point/Refresh）”，
  但为了后续可扩展，这里实现了“可选同名输入端覆盖”的逻辑：若你未来在 GH 中加了
  Timber_block_uniform__length_fen 等输入端并接线，将自动优先生效。
"""

__author__  = "richiebao [coding-x.tech]"
__version__ = "2026.01.04-huagong-step1-8-v1"

import Rhino.Geometry as rg
import ghpythonlib.components as ghc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    JuanShaToolBuilder,
    FTPlaneFromLists,
    GeoAligner_xfm,
)
import Grasshopper.Kernel.Types as ght


# ==============================================================
# GH 组件信息
# ==============================================================


# ==============================================================
# 通用工具函数（参考 LingGongSolver 结构，但按本组件需求裁剪）
# ==============================================================

def all_to_dict(all_list):
    """
    All = [
        ('Timber_block_uniform__length_fen', 72),
        ('Timber_block_uniform__width_fen',  10),
        ...
    ] -> dict
    """
    d = {}
    if not all_list:
        return d
    for item in all_list:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        k, v = item
        d[k] = v
    return d


def make_ref_plane(mode_str):
    """
    按 GH 参考平面定义构造：
    - XY : X=(1,0,0), Y=(0,1,0) -> Z=(0,0,1)
    - XZ : X=(1,0,0), Y=(0,0,1) -> Z=(0,-1,0)  (默认)
    - YZ : X=(0,1,0), Y=(0,0,1) -> Z=(1,0,0)
    """
    origin = rg.Point3d(0.0, 0.0, 0.0)
    if mode_str is None:
        mode_str = "XZ"
    m = str(mode_str).upper()

    if m in ("WORLDXY", "XY", "XY_PLANE"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WORLDYZ", "YZ", "YZ_PLANE"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def normalize_point3d(p):
    """把 base_point 统一成 rg.Point3d；None/异常 -> 原点。"""
    if p is None:
        return rg.Point3d(0.0, 0.0, 0.0)
    if isinstance(p, rg.Point):
        return p.Location
    if isinstance(p, rg.Point3d):
        return p
    # 尝试 (x,y,z) 或带 X/Y/Z 属性
    try:
        return rg.Point3d(p.X, p.Y, p.Z)
    except:
        try:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        except:
            return rg.Point3d(0.0, 0.0, 0.0)


def unwrap_gh_value(obj):
    """
    尝试将 Grasshopper Goo / Wrapper 解包为 RhinoCommon 几何。
    - 支持常见 GH_Goo: GH_Brep/GH_Curve/GH_Surface/GH_Mesh/GH_Point/GH_Vector/...（通常有 .Value）
    - 支持 GH_ObjectWrapper（通常有 .Value 或 .ScriptVariable()）
    - 若无法解包，则原样返回
    """
    if obj is None:
        return None

    # GH Goo 通常有 ScriptVariable()，优先使用
    try:
        if hasattr(obj, "ScriptVariable"):
            v = obj.ScriptVariable()
            if v is not None:
                return v
    except:
        pass

    # GH Goo 常见的 .Value
    try:
        if hasattr(obj, "Value"):
            v = obj.Value
            if v is not None:
                return v
    except:
        pass

    return obj


def flatten_tree(x):
    """
    递归拍平 list/tuple 以及 .NET IEnumerable（如 System.Collections.Generic.List[object]），
    且对每个叶子做 Goo->Geometry 解包，避免出现：
    - System.Collections.Generic.List`1[System.Object]
    - Data conversion failed from Goo to Geometry
    """
    if x is None:
        return []

    # Python list / tuple
    if isinstance(x, (list, tuple)):
        out = []
        for i in x:
            out.extend(flatten_tree(i))
        return out

    # .NET IEnumerable（排除字符串）
    try:
        from System.Collections import IEnumerable
        if isinstance(x, IEnumerable) and not isinstance(x, (str, bytes)):
            out = []
            for i in x:
                out.extend(flatten_tree(i))
            return out
    except Exception:
        pass

    # 叶子：先解包 Goo
    u = unwrap_gh_value(x)

    # 解包后如果是 list/tuple，继续展开
    if isinstance(u, (list, tuple)):
        return flatten_tree(u)

    # 解包后如果是 .NET IEnumerable，继续展开
    try:
        from System.Collections import IEnumerable
        if isinstance(u, IEnumerable) and not isinstance(u, (str, bytes)):
            out = []
            for i in u:
                out.extend(flatten_tree(i))
            return out
    except Exception:
        pass

    return [u]
def get_input_if_exists(name, fallback=None):
    """
    参数优先级：组件输入端（若存在同名变量且“有有效值”） > fallback

    注意：
    - GhPython 中如果你添加了某个输入端但未接线/为空，变量可能是 None、空字符串、空列表等；
      这些都应视为“无值”，应回退到 fallback（通常是 DB 或默认）。
    - 0 / False 是合法值，不能当作“无值”丢弃。
    """
    try:
        if name in globals():
            v = globals()[name]

            # None 直接视为无值
            if v is None:
                return fallback

            # 空字符串视为无值（常见于 Panel 空内容）
            if isinstance(v, str) and v.strip() == "":
                return fallback

            # 空 list/tuple 视为无值（常见于未赋值的列表输入）
            if isinstance(v, (list, tuple)) and len(v) == 0:
                return fallback

            # 其它情况：视为有效值（包括 0 / False）
            return v
    except:
        pass
    return fallback


def ensure_list(x):
    """把标量/None 转成 list；list/tuple 原样返回（不拍平）。"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def broadcast_last(lst, n):
    """将 lst 广播到长度 n（GH longest-list 规则：不足则重复最后一个）。"""
    if n <= 0:
        return []
    if not lst:
        return [None] * n
    if len(lst) >= n:
        return lst[:n]
    return lst + [lst[-1]] * (n - len(lst))


def gh_match(*lists):
    """按 GH 数据匹配（Longest List + Repeat Last）对齐多个 list，返回对齐后的 lists 与 n。"""
    lens = [len(l) for l in lists]
    n = max(lens) if lens else 0
    return [broadcast_last(l, n) for l in lists], n


def safe_index(seq, idx, wrap=True):
    """安全索引：支持 wrap；越界返回 None。"""
    if not seq:
        return None
    try:
        i = int(idx)
    except:
        return None
    if wrap:
        return seq[i % len(seq)]
    if i < 0 or i >= len(seq):
        return None
    return seq[i]



def to_branches(tree_like):
    """
    将 GH DataTree / 嵌套 list/tuple / 标量 转成“分支列表”：
      - 若是 DataTree（有 BranchCount / Branch(i)），提取每个分支为 list；
      - 若是 list/tuple：
          * 若其中任一元素仍是 list/tuple，则视为已是多分支结构，逐项作为分支；
          * 否则视为单分支，返回 [list(x)]；
      - 否则视为单分支，返回 [[x]]。
    """
    if tree_like is None:
        return []
    try:
        if hasattr(tree_like, "BranchCount") and hasattr(tree_like, "Branch"):
            branches = []
            for i in range(tree_like.BranchCount):
                b = tree_like.Branch(i)
                branches.append(list(b) if b is not None else [])
            return branches
    except:
        pass

    if isinstance(tree_like, (list, tuple)):
        if len(tree_like) == 0:
            return []
        if any(isinstance(it, (list, tuple)) for it in tree_like):
            return [list(b) if isinstance(b, (list, tuple)) else [b] for b in tree_like]
        return [list(tree_like)]
    return [[tree_like]]


def broadcast_branches(branches, n_branches):
    """将分支列表广播到 n_branches（不足重复最后一个分支）。"""
    if n_branches <= 0:
        return []
    if not branches:
        return [[] for _ in range(n_branches)]
    if len(branches) >= n_branches:
        return branches[:n_branches]
    return branches + [branches[-1]] * (n_branches - len(branches))






# ==============================================================
# 主 Solver 类 —— HuaGong_MatchedChaAng_4PU
# ==============================================================

class HuaGong_MatchedChaAng_4PU(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        # 输入缓存
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1：数据库读取成员
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step 2：木坯几何输出成员（与 Timber_block_uniform 组件命名对齐）
        self.TimberBrep      = None
        self.FaceList        = []
        self.PointList       = []
        self.EdgeList        = []
        self.CenterPoint     = None
        self.CenterAxisLines = []
        self.EdgeMidPoints   = []
        self.FacePlaneList   = []
        self.Corner0Planes   = []
        self.LocalAxesPlane  = None
        self.AxisX           = None
        self.AxisY           = None
        self.AxisZ           = None
        self.FaceDirTags     = []
        self.EdgeDirTags     = []
        self.Corner0EdgeDirs = []
        self.TimberLog       = []

        # Step 3：卷殺（Juansha）+ PlaneFromLists::1 + AlignToolToTimber::1
        # --- Juansha outputs ---
        self.Juansha_ToolBrep        = None
        self.Juansha_SectionEdges    = []
        self.Juansha_HL_Intersection = None
        self.Juansha_HeightFacePlane = None
        self.Juansha_LengthFacePlane = None
        self.Juansha_Log             = []

        # --- PlaneFromLists::1 outputs (可能为列表) ---
        self.PlaneFromLists_1_BasePlane   = []
        self.PlaneFromLists_1_OriginPoint = []
        self.PlaneFromLists_1_ResultPlane = []
        self.PlaneFromLists_1_Log         = []

        # --- AlignToolToTimber::1 outputs (可能为列表) ---
        self.AlignToolToTimber_1_SourceOut    = []
        self.AlignToolToTimber_1_TargetOut    = []
        self.AlignToolToTimber_1_TransformOut = []
        self.AlignToolToTimber_1_MovedGeo     = []
        self.AlignToolToTimber_1_Log          = []


        # Step 4：櫨枓和泥道栱切削准备（BlockCutter::1 + AlignToolToTimber::2）
        # --- BlockCutter::1 outputs ---
        self.BlockCutter_1_TimberBrep      = None
        self.BlockCutter_1_FaceList        = []
        self.BlockCutter_1_PointList       = []
        self.BlockCutter_1_EdgeList        = []
        self.BlockCutter_1_CenterPoint     = None
        self.BlockCutter_1_CenterAxisLines = []
        self.BlockCutter_1_EdgeMidPoints   = []
        self.BlockCutter_1_FacePlaneList   = []
        self.BlockCutter_1_Corner0Planes   = []
        self.BlockCutter_1_LocalAxesPlane  = None
        self.BlockCutter_1_AxisX           = None
        self.BlockCutter_1_AxisY           = None
        self.BlockCutter_1_AxisZ           = None
        self.BlockCutter_1_FaceDirTags     = []
        self.BlockCutter_1_EdgeDirTags     = []
        self.BlockCutter_1_Corner0EdgeDirs = []
        self.BlockCutter_1_Log             = []

        # --- AlignToolToTimber::2 outputs（树结构保持） ---
        self.AlignToolToTimber_2_SourceOut_tree    = []
        self.AlignToolToTimber_2_TargetOut_tree    = []
        self.AlignToolToTimber_2_TransformOut_tree = []
        self.AlignToolToTimber_2_MovedGeo_tree     = []
        self.AlignToolToTimber_2_Log               = []


        # Step 5：单泥道栱切削准备（BlockCutter::2 + AlignToolToTimber::3）
        # --- BlockCutter::2 outputs ---
        self.BlockCutter_2_TimberBrep      = None
        self.BlockCutter_2_FaceList        = []
        self.BlockCutter_2_PointList       = []
        self.BlockCutter_2_EdgeList        = []
        self.BlockCutter_2_CenterPoint     = None
        self.BlockCutter_2_CenterAxisLines = []
        self.BlockCutter_2_EdgeMidPoints   = []
        self.BlockCutter_2_FacePlaneList   = []
        self.BlockCutter_2_Corner0Planes   = []
        self.BlockCutter_2_LocalAxesPlane  = None
        self.BlockCutter_2_AxisX           = None
        self.BlockCutter_2_AxisY           = None
        self.BlockCutter_2_AxisZ           = None
        self.BlockCutter_2_FaceDirTags     = []
        self.BlockCutter_2_EdgeDirTags     = []
        self.BlockCutter_2_Corner0EdgeDirs = []
        self.BlockCutter_2_Log             = []

        # --- AlignToolToTimber::3 outputs ---
        self.AlignToolToTimber_3_SourceOut_tree    = []
        self.AlignToolToTimber_3_TargetOut_tree    = []
        self.AlignToolToTimber_3_TransformOut_tree = []
        self.AlignToolToTimber_3_MovedGeo_tree     = []
        self.AlignToolToTimber_3_Log               = []

        # Step 6：窄口部分切削准备（BlockCutter::3 + AlignToolToTimber::4）
        # --- BlockCutter::3 outputs ---
        self.BlockCutter_3_TimberBrep      = None
        self.BlockCutter_3_FaceList        = []
        self.BlockCutter_3_PointList       = []
        self.BlockCutter_3_EdgeList        = []
        self.BlockCutter_3_CenterPoint     = None
        self.BlockCutter_3_CenterAxisLines = []
        self.BlockCutter_3_EdgeMidPoints   = []
        self.BlockCutter_3_FacePlaneList   = []
        self.BlockCutter_3_Corner0Planes   = []
        self.BlockCutter_3_LocalAxesPlane  = None
        self.BlockCutter_3_AxisX           = None
        self.BlockCutter_3_AxisY           = None
        self.BlockCutter_3_AxisZ           = None
        self.BlockCutter_3_FaceDirTags     = []
        self.BlockCutter_3_EdgeDirTags     = []
        self.BlockCutter_3_Corner0EdgeDirs = []
        self.BlockCutter_3_Log             = []

        # --- AlignToolToTimber::4 outputs ---
        self.AlignToolToTimber_4_SourceOut_tree    = []
        self.AlignToolToTimber_4_TargetOut_tree    = []
        self.AlignToolToTimber_4_TransformOut_tree = []
        self.AlignToolToTimber_4_MovedGeo_tree     = []
        self.AlignToolToTimber_4_Log               = []

        # Step 7：欹䫜切削准备（QiAOTool + PlaneFromLists::2/3 + AlignToolToTimber::5）
        # --- QiAOTool outputs（尽量与 build_timber_block_uniform 命名对齐，同时保留 CutTimbers） ---
        self.QiAOTool_CutTimbers      = []
        self.QiAOTool_FailTimbers     = []
        self.QiAOTool_TimberBrep      = None
        self.QiAOTool_FaceList        = []
        self.QiAOTool_PointList       = []
        self.QiAOTool_EdgeList        = []
        self.QiAOTool_CenterPoint     = None
        self.QiAOTool_CenterAxisLines = []
        self.QiAOTool_EdgeMidPoints   = []
        self.QiAOTool_FacePlaneList   = []
        self.QiAOTool_Corner0Planes   = []
        self.QiAOTool_LocalAxesPlane  = None
        self.QiAOTool_AxisX           = None
        self.QiAOTool_AxisY           = None
        self.QiAOTool_AxisZ           = None
        self.QiAOTool_FaceDirTags     = []
        self.QiAOTool_EdgeDirTags     = []
        self.QiAOTool_Corner0EdgeDirs = []
        self.QiAOTool_Log             = []

        # --- PlaneFromLists::2 outputs（Timber_block_uniform -> ResultPlane） ---
        self.PlaneFromLists_2_BasePlane   = []
        self.PlaneFromLists_2_OriginPoint = []
        self.PlaneFromLists_2_ResultPlane = []
        self.PlaneFromLists_2_Log         = []

        # --- PlaneFromLists::3 outputs（QiAOTool -> ResultPlane） ---
        self.PlaneFromLists_3_BasePlane   = []
        self.PlaneFromLists_3_OriginPoint = []
        self.PlaneFromLists_3_ResultPlane = []
        self.PlaneFromLists_3_Log         = []

        # --- AlignToolToTimber::5 outputs ---
        self.AlignToolToTimber_5_SourceOut    = []
        self.AlignToolToTimber_5_TargetOut    = []
        self.AlignToolToTimber_5_TransformOut = []
        self.AlignToolToTimber_5_MovedGeo     = []
        self.AlignToolToTimber_5_Log          = []


        # Step 8：栱眼切削准备（GongYan + PlaneFromLists::4 + AlignToolToTimber::6）
        # --- GongYan outputs ---
        self.GongYan_SectionCurve   = None
        self.GongYan_SectionFace    = None
        self.GongYan_LeftCurve      = None
        self.GongYan_RightCurve     = None
        self.GongYan_SymmetryAxis   = None
        self.GongYan_AllPoints      = None
        self.GongYan_ToolBrep       = None
        self.GongYan_SectionPlanes  = []
        self.GongYan_Log            = []

        # --- PlaneFromLists::4 outputs ---
        self.PlaneFromLists_4_BasePlane   = []
        self.PlaneFromLists_4_OriginPoint = []
        self.PlaneFromLists_4_ResultPlane = []
        self.PlaneFromLists_4_Log         = []

        # --- AlignToolToTimber::6 outputs（按“Geo 整体”对位；RotateDeg 可为列表） ---
        self.AlignToolToTimber_6_SourceOut_tree    = []
        self.AlignToolToTimber_6_TargetOut_tree    = []
        self.AlignToolToTimber_6_TransformOut_tree = []
        self.AlignToolToTimber_6_MovedGeo_tree     = []
        self.AlignToolToTimber_6_Log               = []
        # 最终输出（后续步骤加入切削后会覆盖）
        self.CutTimbers  = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：从 AllDict 取值（若是单元素 list/tuple 自动解包）
    # ------------------------------------------------------
    def all_get(self, key, default=None):
        """从 AllDict 取值（兼容命名差异：__ vs _）。

        说明：你当前 DBJsonReader 展开的键有时是
            BlockCutter_2_length_fen
        而 GH 端/约定可能是
            BlockCutter_2__length_fen
        为避免漏读，这里自动尝试 key 的若干等价形式。
        """
        if not self.AllDict:
            return default

        # 1) 原 key
        if key in self.AllDict:
            v = self.AllDict[key]
        else:
            # 2) 兼容：把双下划线改成单下划线
            alt = key.replace('__', '_') if '__' in key else None
            if alt and alt in self.AllDict:
                v = self.AllDict[alt]
            else:
                return default

        # 自动解包单元素 list/tuple
        if isinstance(v, (list, tuple)):
            if len(v) == 0:
                return default
            if len(v) == 1:
                return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="HuaGong_4ChaAng",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成：DG_Dou / type_code=HuaGong_4PU_INOUT_1ChaoJuantou")
            for l in (self.DBLog or []):
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建（Timber_block_uniform）
    # ------------------------------------------------------
    def step2_timber(self):
        """
        参数优先级（实现）：
        - 若 GH 输入端存在同名变量（例如 Timber_block_uniform__length_fen），则优先；
        - 否则取 AllDict；
        - 否则取默认值。
        """

        # --- 2.1 尺寸参数：输入端覆盖 > DB > 默认 ---
        length_raw = get_input_if_exists(
            "Timber_block_uniform__length_fen",
            self.all_get("Timber_block_uniform__length_fen", 32.0)
        )
        width_raw = get_input_if_exists(
            "Timber_block_uniform__width_fen",
            self.all_get("Timber_block_uniform__width_fen", 32.0)
        )
        height_raw = get_input_if_exists(
            "Timber_block_uniform__height_fen",
            self.all_get("Timber_block_uniform__height_fen", 20.0)
        )

        try:
            length_fen = float(length_raw)
            width_fen  = float(width_raw)
            height_fen = float(height_raw)
        except Exception as e:
            self.Log.append("[TIMBER] 尺寸转 float 出错: {}，回退默认值".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        # --- 2.2 base_point：组件输入端（None -> 原点） ---
        bp = normalize_point3d(self.base_point)

        # --- 2.3 reference_plane：默认 GH XZ Plane（按要求固定） ---
        # 你明确要求此步默认 XZ Plane，这里不从 DB 取（后续若需要可再开放）
        reference_plane = make_ref_plane("XZ")

        self.Log.append("[TIMBER] length/width/height = {}, {}, {}".format(length_fen, width_fen, height_fen))
        self.Log.append("[TIMBER] base_point = ({:.3f},{:.3f},{:.3f})".format(bp.X, bp.Y, bp.Z))
        self.Log.append("[TIMBER] reference_plane = GH XZ Plane (X=(1,0,0), Y=(0,0,1), Z=(0,-1,0))")

        # --- 2.4 调用库函数构建木坯 ---
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
                length_fen,
                width_fen,
                height_fen,
                bp,
                reference_plane,
            )

            self.TimberBrep      = timber_brep
            self.FaceList        = faces or []
            self.PointList       = points or []
            self.EdgeList        = edges or []
            self.CenterPoint     = center_pt
            self.CenterAxisLines = center_axes or []
            self.EdgeMidPoints   = edge_midpts or []
            self.FacePlaneList   = face_planes or []
            self.Corner0Planes   = corner0_planes or []
            self.LocalAxesPlane  = local_axes_plane
            self.AxisX           = axis_x
            self.AxisY           = axis_y
            self.AxisZ           = axis_z
            self.FaceDirTags     = face_tags or []
            self.EdgeDirTags     = edge_tags or []
            self.Corner0EdgeDirs = corner0_dirs or []
            self.TimberLog       = log_lines or []

            self.Log.append("[TIMBER] build_timber_block_uniform 完成")
            for l in self.TimberLog:
                self.Log.append("[TIMBER] " + str(l))

            # 当前仅 Step1-2：暂以木坯作为 CutTimbers 的占位输出
            self.CutTimbers  = [self.TimberBrep] if self.TimberBrep is not None else []
            self.FailTimbers = []

        except Exception as e:
            self.TimberBrep      = None
            self.FaceList        = []
            self.PointList       = []
            self.EdgeList        = []
            self.CenterPoint     = None
            self.CenterAxisLines = []
            self.EdgeMidPoints   = []
            self.FacePlaneList   = []
            self.Corner0Planes   = []
            self.LocalAxesPlane  = None
            self.AxisX           = None
            self.AxisY           = None
            self.AxisZ           = None
            self.FaceDirTags     = []
            self.EdgeDirTags     = []
            self.Corner0EdgeDirs = []
            self.TimberLog       = ["错误: {}".format(e)]

            self.CutTimbers  = []
            self.FailTimbers = []

            self.Log.append("[ERROR] step2_timber 出错: {}".format(e))

        return self
    # ------------------------------------------------------
    # Step 3：卷殺（Juansha）+ PlaneFromLists::1 + AlignToolToTimber::1
    # ------------------------------------------------------
    def step3_juansha(self):
        # ---------- 3.1 Juansha（JuanShaToolBuilder） ----------
        try:
            # 参数优先级：输入端覆盖 > DB > 默认
            h_raw = get_input_if_exists("Juansha__HeightFen", self.all_get("Juansha__HeightFen", None))
            l_raw = get_input_if_exists("Juansha__LengthFen", self.all_get("Juansha__LengthFen", None))
            d_raw = get_input_if_exists("Juansha__DivCount", self.all_get("Juansha__DivCount", None))
            t_raw = get_input_if_exists("Juansha__ThicknessFen", self.all_get("Juansha__ThicknessFen", None))

            # 默认值（仅在 DB 也没有时兜底）
            HeightFen = 4.0 if h_raw is None else float(h_raw)
            LengthFen = 28.0 if l_raw is None else float(l_raw)
            DivCount = 10 if d_raw is None else int(d_raw)
            ThicknessFen = 2.0 if t_raw is None else float(t_raw)

            # SectionPlane：你未在 step3 映射中指定来源，这里按“可选输入端覆盖 > DB > 默认 GH XY”
            sp_mode = get_input_if_exists("Juansha__SectionPlane", self.all_get("Juansha__SectionPlane", None))
            SectionPlane = sp_mode if isinstance(sp_mode, rg.Plane) else make_ref_plane("XY")

            # PositionPoint：默认原点；允许可选输入端覆盖
            pp_raw = get_input_if_exists("Juansha__PositionPoint", None)
            PositionPoint = normalize_point3d(pp_raw)

            builder = JuanShaToolBuilder(
                height_fen=HeightFen,
                length_fen=LengthFen,
                thickness_fen=ThicknessFen,
                div_count=DivCount,
                section_plane=SectionPlane,
                position_point=PositionPoint
            )

            (
                self.Juansha_ToolBrep,
                self.Juansha_SectionEdges,
                self.Juansha_HL_Intersection,
                self.Juansha_HeightFacePlane,
                self.Juansha_LengthFacePlane,
                jlog
            ) = builder.build()

            self.Juansha_Log = jlog or []
            self.Log.append("[JUANSHA] ToolBuilder 完成")
            for l in self.Juansha_Log:
                self.Log.append("[JUANSHA] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step3_juansha::Juansha 出错: {}".format(e))
            self.Juansha_ToolBrep = None
            self.Juansha_LengthFacePlane = None
            return self

        # ---------- 3.2 PlaneFromLists::1（FTPlaneFromLists） ----------
        try:
            OriginPoints = self.EdgeMidPoints or []
            BasePlanes = self.Corner0Planes or []

            idx_o_raw = get_input_if_exists(
                "PlaneFromLists_1__IndexOrigin",
                self.all_get("PlaneFromLists_1__IndexOrigin", 0)
            )
            idx_p_raw = get_input_if_exists(
                "PlaneFromLists_1__IndexPlane",
                self.all_get("PlaneFromLists_1__IndexPlane", 0)
            )

            Wrap = get_input_if_exists("PlaneFromLists_1__Wrap", self.all_get("PlaneFromLists_1__Wrap", True))
            Wrap = True if Wrap is None else bool(Wrap)

            idx_o_list = ensure_list(idx_o_raw)
            idx_p_list = ensure_list(idx_p_raw)

            (idx_o_list, idx_p_list), n = gh_match(idx_o_list, idx_p_list)
            if n == 0:
                n = 1
                idx_o_list = [0]
                idx_p_list = [0]

            builder = FTPlaneFromLists(wrap=Wrap)

            bp_list = []
            op_list = []
            rp_list = []
            plog = []

            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o_list[i],
                    idx_p_list[i]
                )
                bp_list.append(BasePlane)
                op_list.append(OriginPoint)
                rp_list.append(ResultPlane)
                if Log:
                    plog.extend(Log if isinstance(Log, (list, tuple)) else [Log])

            self.PlaneFromLists_1_BasePlane = bp_list
            self.PlaneFromLists_1_OriginPoint = op_list
            self.PlaneFromLists_1_ResultPlane = rp_list
            self.PlaneFromLists_1_Log = plog

            self.Log.append("[PFL1] PlaneFromLists::1 完成，输出 {} 组 ResultPlane".format(len(rp_list)))

        except Exception as e:
            self.Log.append("[ERROR] step3_juansha::PlaneFromLists::1 出错: {}".format(e))
            self.PlaneFromLists_1_ResultPlane = []
            return self

        # ---------- 3.3 AlignToolToTimber::1（GeoAligner_xfm） ----------
        try:
            Geo = self.Juansha_ToolBrep
            SourcePlane = self.Juansha_LengthFacePlane
            TargetPlane = self.PlaneFromLists_1_ResultPlane

            # 广播参数：必须保持顺序一一对应：
            #   PlaneFromLists::1 的 ResultPlane[i]  <->  RotateDeg[i]
            # 因此以 TargetPlane（ResultPlane 列表）的顺序作为主轴进行对齐。
            geo_list = ensure_list(Geo)
            src_list = ensure_list(SourcePlane)
            tgt_list = ensure_list(TargetPlane)

            RotateDeg = get_input_if_exists(
                "AlignToolToTimber_1__RotateDeg",
                self.all_get("AlignToolToTimber_1__RotateDeg", 0)
            )
            FlipY = get_input_if_exists(
                "AlignToolToTimber_1__FlipY",
                self.all_get("AlignToolToTimber_1__FlipY", False)
            )
            FlipX = get_input_if_exists("AlignToolToTimber_1__FlipX", self.all_get("AlignToolToTimber_1__FlipX", False))
            FlipZ = get_input_if_exists("AlignToolToTimber_1__FlipZ", self.all_get("AlignToolToTimber_1__FlipZ", False))
            MoveX = get_input_if_exists("AlignToolToTimber_1__MoveX", self.all_get("AlignToolToTimber_1__MoveX", 0))
            MoveY = get_input_if_exists("AlignToolToTimber_1__MoveY", self.all_get("AlignToolToTimber_1__MoveY", 0))
            MoveZ = get_input_if_exists("AlignToolToTimber_1__MoveZ", self.all_get("AlignToolToTimber_1__MoveZ", 0))

            rot_list = ensure_list(RotateDeg)
            fx_list  = ensure_list(FlipX)
            fy_list  = ensure_list(FlipY)
            fz_list  = ensure_list(FlipZ)
            mx_list  = ensure_list(MoveX)
            my_list  = ensure_list(MoveY)
            mz_list  = ensure_list(MoveZ)

            # 以 tgt_list 为主轴，按 GH longest-list 规则对齐其它参数（Repeat Last）
            n = max(len(tgt_list), len(rot_list), len(geo_list), len(src_list), len(fx_list), len(fy_list), len(fz_list), len(mx_list), len(my_list), len(mz_list))
            if n == 0:
                n = 1

            tgt_list = broadcast_last(tgt_list, n)
            rot_list = broadcast_last(rot_list, n)
            geo_list = broadcast_last(geo_list, n)
            src_list = broadcast_last(src_list, n)
            fx_list  = broadcast_last(fx_list, n)
            fy_list  = broadcast_last(fy_list, n)
            fz_list  = broadcast_last(fz_list, n)
            mx_list  = broadcast_last(mx_list, n)
            my_list  = broadcast_last(my_list, n)
            mz_list  = broadcast_last(mz_list, n)

            src_out = []
            tgt_out = []
            xfm_out = []
            mv_out  = []

            for i in range(n):
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
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

                src_out.append(SourceOut)
                tgt_out.append(TargetOut)
                xfm_out.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                mv_out.append(MovedGeo)

            self.AlignToolToTimber_1_SourceOut   = src_out
            self.AlignToolToTimber_1_TargetOut   = tgt_out
            self.AlignToolToTimber_1_TransformOut = xfm_out
            self.AlignToolToTimber_1_MovedGeo    = mv_out

            self.Log.append("[ALIGN1] AlignToolToTimber::1 完成，对齐 {} 组（ResultPlane[i] <-> RotateDeg[i]）".format(n))

        except Exception as e:
            self.Log.append("[ERROR] step3_juansha::AlignToolToTimber::1 出错: {}".format(e))
            self.AlignToolToTimber_1_MovedGeo = []

        return self

    # ------------------------------------------------------
    # Step 4：櫨枓和泥道栱切削准备（BlockCutter::1 + AlignToolToTimber::2）
    # ------------------------------------------------------
    def step4_blockcutter_and_align2(self):
        """
        Step 4：櫨枓和泥道栱切削（当前步仅完成刀块构建 + 对位 AlignToolToTimber::2）
        - BlockCutter::1 的 length/width/height 允许为列表（通常为两个值），一组 (L,W,H) 对应一个长方体刀块。
          例如：
            length=[16,10], width=[10,10], height=[4,5]
          => 两个刀块尺寸分别为 (16,10,4) 与 (10,10,5)
        - AlignToolToTimber::2：
          Geo 与 SourcePlane 均为 2 分支（与刀块一一对应），TargetPlane 为单值索引广播对齐。
        """

        # =====================================================
        # 4.1 BlockCutter::1 —— 支持尺寸列表（生成多块刀块 / 多分支）
        # =====================================================
        try:
            l_raw = get_input_if_exists("BlockCutter_1__length_fen", self.all_get("BlockCutter_1__length_fen", 32.0))
            w_raw = get_input_if_exists("BlockCutter_1__width_fen",  self.all_get("BlockCutter_1__width_fen",  32.0))
            h_raw = get_input_if_exists("BlockCutter_1__height_fen", self.all_get("BlockCutter_1__height_fen", 20.0))

            l_list = l_raw if isinstance(l_raw, (list, tuple)) else [l_raw]
            w_list = w_raw if isinstance(w_raw, (list, tuple)) else [w_raw]
            h_list = h_raw if isinstance(h_raw, (list, tuple)) else [h_raw]

            # GH longest-list：以三者最大长度为准，不足重复最后一个
            ( _aligned_lists, n_blocks ) = gh_match(l_list, w_list, h_list)
            l_list, w_list, h_list = _aligned_lists

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            # BlockCutter::1 参考平面：按要求默认为 GH 的 XZ Plane
            # XZ Plane 轴向（按 GH 定义）：
            #   X = (1,0,0)
            #   Y = (0,0,1)
            #   Z = (0,-1,0)
            reference_plane = make_ref_plane("XZ")

            self.Log.append("[STEP4] BlockCutter::1 生成刀块数 = {}".format(n_blocks))

            # 以“分支”的形式保存（每个分支通常一个 brep）
            self.BlockCutter_1_TimberBrep_Branches = []
            self.BlockCutter_1_FacePlaneList_Branches = []
            self.BlockCutter_1_Log_Branches = []

            # 同时保留扁平列表（便于调试/兼容）
            self.BlockCutter_1_TimberBrep = []
            self.BlockCutter_1_FacePlaneList = []
            self.BlockCutter_1_Log = []

            # legacy（兼容旧输出绑定区）：默认取第 0 块刀块的特征；若无则保持空
            self.BlockCutter_1_FaceList        = []
            self.BlockCutter_1_PointList       = []
            self.BlockCutter_1_EdgeList        = []
            self.BlockCutter_1_CenterPoint     = None
            self.BlockCutter_1_CenterAxisLines = []
            self.BlockCutter_1_EdgeMidPoints   = []
            self.BlockCutter_1_Corner0Planes   = []
            self.BlockCutter_1_LocalAxesPlane  = None
            self.BlockCutter_1_AxisX           = None
            self.BlockCutter_1_AxisY           = None
            self.BlockCutter_1_AxisZ           = None
            self.BlockCutter_1_FaceDirTags     = []
            self.BlockCutter_1_EdgeDirTags     = []
            self.BlockCutter_1_Corner0EdgeDirs = []

            for i in range(n_blocks):
                # 尺寸转 float（单个失败回退默认）
                try:
                    length_fen = 32.0 if l_list[i] is None else float(l_list[i])
                    width_fen  = 32.0 if w_list[i] is None else float(w_list[i])
                    height_fen = 20.0 if h_list[i] is None else float(h_list[i])
                except:
                    length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

                self.Log.append("[STEP4] BlockCutter::1[{}] L/W/H = {}, {}, {}".format(i, length_fen, width_fen, height_fen))

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
                        length_fen,
                        width_fen,
                        height_fen,
                        base_point,
                        reference_plane,
                    )

                    # legacy：第 0 块刀块输出到旧变量，方便 GH 输出绑定区不报错
                    if i == 0:
                        self.BlockCutter_1_FaceList        = faces or []
                        self.BlockCutter_1_PointList       = points or []
                        self.BlockCutter_1_EdgeList        = edges or []
                        self.BlockCutter_1_CenterPoint     = center_pt
                        self.BlockCutter_1_CenterAxisLines = center_axes or []
                        self.BlockCutter_1_EdgeMidPoints   = edge_midpts or []
                        self.BlockCutter_1_Corner0Planes   = corner0_planes or []
                        self.BlockCutter_1_LocalAxesPlane  = local_axes_plane
                        self.BlockCutter_1_AxisX           = axis_x
                        self.BlockCutter_1_AxisY           = axis_y
                        self.BlockCutter_1_AxisZ           = axis_z
                        self.BlockCutter_1_FaceDirTags     = face_tags or []
                        self.BlockCutter_1_EdgeDirTags     = edge_tags or []
                        self.BlockCutter_1_Corner0EdgeDirs = corner0_dirs or []

                    # branch
                    self.BlockCutter_1_TimberBrep_Branches.append([timber_brep])
                    self.BlockCutter_1_FacePlaneList_Branches.append(face_planes or [])
                    self.BlockCutter_1_Log_Branches.append(log_lines or [])

                    # flat
                    self.BlockCutter_1_TimberBrep.append(timber_brep)
                    self.BlockCutter_1_FacePlaneList.append(face_planes or [])
                    self.BlockCutter_1_Log.extend(log_lines or [])

                except Exception as e:
                    self.Log.append("[ERROR] BlockCutter::1[{}] 构建失败: {}".format(i, e))
                    self.BlockCutter_1_TimberBrep_Branches.append([None])
                    self.BlockCutter_1_FacePlaneList_Branches.append([])
                    self.BlockCutter_1_Log_Branches.append(["错误: {}".format(e)])

                    self.BlockCutter_1_TimberBrep.append(None)
                    self.BlockCutter_1_FacePlaneList.append([])
                    self.BlockCutter_1_Log.append("错误: {}".format(e))

        except Exception as e:
            self.Log.append("[ERROR] step4 BlockCutter::1 初始化失败: {}".format(e))
            self.BlockCutter_1_TimberBrep_Branches = []
            self.BlockCutter_1_FacePlaneList_Branches = []
            self.BlockCutter_1_Log_Branches = []
            self.BlockCutter_1_TimberBrep = []
            self.BlockCutter_1_FacePlaneList = []
            self.BlockCutter_1_Log = []

        # =====================================================
        # 4.2 AlignToolToTimber::2 —— Tree(两分支) 一一对应 + TargetPlane 单值广播
        # =====================================================
        try:
            # --- Geo branches（与 BlockCutter 对齐） ---
            geo_branches = self.BlockCutter_1_TimberBrep_Branches if hasattr(self, "BlockCutter_1_TimberBrep_Branches") else []
            src_faceplanes_branches = self.BlockCutter_1_FacePlaneList_Branches if hasattr(self, "BlockCutter_1_FacePlaneList_Branches") else []

            # 若没有 branches，但 flat 有数据，转成 branches
            if not geo_branches and getattr(self, "BlockCutter_1_TimberBrep", None):
                geo_branches = [[g] for g in (self.BlockCutter_1_TimberBrep or [])]
            if not src_faceplanes_branches and getattr(self, "BlockCutter_1_FacePlaneList", None):
                src_faceplanes_branches = (self.BlockCutter_1_FacePlaneList or [])

            n_branches = len(geo_branches)

            # --- SourcePlane / TargetPlane index ---
            src_idx_raw = get_input_if_exists("AlignToolToTimber_2__SourcePlane", self.all_get("AlignToolToTimber_2__SourcePlane", 0))
            tgt_idx_raw = get_input_if_exists("AlignToolToTimber_2__TargetPlane", self.all_get("AlignToolToTimber_2__TargetPlane", 0))

            src_idx_list = src_idx_raw if isinstance(src_idx_raw, (list, tuple)) else [src_idx_raw]
            tgt_idx_list = tgt_idx_raw if isinstance(tgt_idx_raw, (list, tuple)) else [tgt_idx_raw]

            # 目标索引一般是单值：广播到分支数
            src_idx_list = broadcast_last(src_idx_list, n_branches)
            tgt_idx_list = broadcast_last(tgt_idx_list, n_branches)

            # Timber_block_uniform 的 face plane list（作为对齐目标）
            tgt_faceplanes = self.FacePlaneList or []

            self.AlignToolToTimber_2_SourcePlane = []
            self.AlignToolToTimber_2_TargetPlane = []
            self.AlignToolToTimber_2_SourceOut = []
            self.AlignToolToTimber_2_TargetOut = []
            self.AlignToolToTimber_2_Transform = []
            self.AlignToolToTimber_2_MovedGeo = []
            self.AlignToolToTimber_2_Log = []

            # Rotate/Flip/Move（本步描述未给出——保持与 ghpy 组件一致：可选输入端覆盖 > DB > 默认）
            rotate_raw = get_input_if_exists("AlignToolToTimber_2__RotateDeg", self.all_get("AlignToolToTimber_2__RotateDeg", 0))
            flipx_raw  = get_input_if_exists("AlignToolToTimber_2__FlipX",    self.all_get("AlignToolToTimber_2__FlipX",    False))
            flipy_raw  = get_input_if_exists("AlignToolToTimber_2__FlipY",    self.all_get("AlignToolToTimber_2__FlipY",    False))
            flipz_raw  = get_input_if_exists("AlignToolToTimber_2__FlipZ",    self.all_get("AlignToolToTimber_2__FlipZ",    False))
            movex_raw  = get_input_if_exists("AlignToolToTimber_2__MoveX",    self.all_get("AlignToolToTimber_2__MoveX",    0))
            movey_raw  = get_input_if_exists("AlignToolToTimber_2__MoveY",    self.all_get("AlignToolToTimber_2__MoveY",    0))
            movez_raw  = get_input_if_exists("AlignToolToTimber_2__MoveZ",    self.all_get("AlignToolToTimber_2__MoveZ",    0))

            rotate_list = rotate_raw if isinstance(rotate_raw, (list, tuple)) else [rotate_raw]
            flipx_list  = flipx_raw  if isinstance(flipx_raw,  (list, tuple)) else [flipx_raw]
            flipy_list  = flipy_raw  if isinstance(flipy_raw,  (list, tuple)) else [flipy_raw]
            flipz_list  = flipz_raw  if isinstance(flipz_raw,  (list, tuple)) else [flipz_raw]
            movex_list  = movex_raw  if isinstance(movex_raw,  (list, tuple)) else [movex_raw]
            movey_list  = movey_raw  if isinstance(movey_raw,  (list, tuple)) else [movey_raw]
            movez_list  = movez_raw  if isinstance(movez_raw,  (list, tuple)) else [movez_raw]

            rotate_list = broadcast_last(rotate_list, n_branches)
            flipx_list  = broadcast_last(flipx_list,  n_branches)
            flipy_list  = broadcast_last(flipy_list,  n_branches)
            flipz_list  = broadcast_last(flipz_list,  n_branches)
            movex_list  = broadcast_last(movex_list,  n_branches)
            movey_list  = broadcast_last(movey_list,  n_branches)
            movez_list  = broadcast_last(movez_list,  n_branches)

            for bi in range(n_branches):
                geo = geo_branches[bi][0] if geo_branches[bi] else None
                src_planes = src_faceplanes_branches[bi] if bi < len(src_faceplanes_branches) else []
                src_idx = src_idx_list[bi]
                tgt_idx = tgt_idx_list[bi]

                # 取 SourcePlane（来自 BlockCutter::1 的 FacePlaneList 分支）
                src_plane = None
                try:
                    if src_planes and src_idx is not None:
                        ii = int(src_idx)
                        if 0 <= ii < len(src_planes):
                            src_plane = src_planes[ii]
                except:
                    src_plane = None

                # 取 TargetPlane（来自 Timber_block_uniform 的 FacePlaneList，单值索引广播）
                tgt_plane = None
                try:
                    if tgt_faceplanes and tgt_idx is not None:
                        jj = int(tgt_idx)
                        if 0 <= jj < len(tgt_faceplanes):
                            tgt_plane = tgt_faceplanes[jj]
                except:
                    tgt_plane = None

                self.AlignToolToTimber_2_SourcePlane.append(src_plane)
                self.AlignToolToTimber_2_TargetPlane.append(tgt_plane)

                if geo is None or src_plane is None or tgt_plane is None:
                    self.AlignToolToTimber_2_SourceOut.append(None)
                    self.AlignToolToTimber_2_TargetOut.append(None)
                    self.AlignToolToTimber_2_Transform.append(None)
                    self.AlignToolToTimber_2_MovedGeo.append(None)
                    self.AlignToolToTimber_2_Log.append("[STEP4] Align2[{}] 缺少 Geo/Plane，跳过".format(bi))
                    continue

                try:
                    SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                        geo,
                        src_plane,
                        tgt_plane,
                        rotate_deg=rotate_list[bi],
                        flip_x=flipx_list[bi],
                        flip_y=flipy_list[bi],
                        flip_z=flipz_list[bi],
                        move_x=movex_list[bi],
                        move_y=movey_list[bi],
                        move_z=movez_list[bi],
                    )
                    self.AlignToolToTimber_2_SourceOut.append(SourceOut)
                    self.AlignToolToTimber_2_TargetOut.append(TargetOut)
                    self.AlignToolToTimber_2_Transform.append(TransformOut)
                    self.AlignToolToTimber_2_MovedGeo.append(MovedGeo)
                    self.AlignToolToTimber_2_Log.append("[STEP4] Align2[{}] OK".format(bi))
                except Exception as e:
                    self.AlignToolToTimber_2_SourceOut.append(None)
                    self.AlignToolToTimber_2_TargetOut.append(None)
                    self.AlignToolToTimber_2_Transform.append(None)
                    self.AlignToolToTimber_2_MovedGeo.append(None)
                    self.AlignToolToTimber_2_Log.append("[ERROR] Align2[{}] 失败: {}".format(bi, e))

            # --- 输出 Tree（两分支）保持：每个分支对应一个刀块对齐结果 ---
            # 注意：当前每个分支默认只取 geo_branches[bi][0] 一个几何
            # 将每个分支内的嵌套 list/tuple 递归拍平，避免输出为 System.Collections.Generic.List`1[System.Object]
            self.AlignToolToTimber_2_SourceOut_tree    = [flatten_tree(x) for x in (self.AlignToolToTimber_2_SourceOut or [])]
            self.AlignToolToTimber_2_TargetOut_tree    = [flatten_tree(x) for x in (self.AlignToolToTimber_2_TargetOut or [])]
            self.AlignToolToTimber_2_TransformOut_tree = [flatten_tree(x) for x in (self.AlignToolToTimber_2_Transform or [])]
            # 将所有分支递归拍平为单层几何列表（避免嵌套 list 导致下游 Goo->Geometry 转换失败）
            self.AlignToolToTimber_2_MovedGeo_tree     = flatten_tree(self.AlignToolToTimber_2_MovedGeo)
            self.Log.extend(self.AlignToolToTimber_2_Log)

        except Exception as e:
            self.Log.append("[ERROR] step4 AlignToolToTimber::2 初始化失败: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5：单泥道栱切削准备（BlockCutter::2 + AlignToolToTimber::3）
    # ------------------------------------------------------
    def step5_blockcutter2_and_align3(self):
        """
        Step 5：单泥道栱切削（当前步仅完成刀块构建 + 对位 AlignToolToTimber::3）
        - BlockCutter::2：默认参考平面为 GH 的 XZ Plane（按 GH 定义）
        - AlignToolToTimber::3：输入参数需要广播对齐；本步额外使用 MoveY（可为列表）
        """
        # =====================================================
        # 5.1 BlockCutter::2 —— 生成刀块（通常单块；也兼容列表尺寸）
        # =====================================================
        try:
            l_raw = get_input_if_exists("BlockCutter_2__length_fen", self.all_get("BlockCutter_2__length_fen", 32.0))
            w_raw = get_input_if_exists("BlockCutter_2__width_fen",  self.all_get("BlockCutter_2__width_fen",  32.0))
            h_raw = get_input_if_exists("BlockCutter_2__height_fen", self.all_get("BlockCutter_2__height_fen", 20.0))

            l_list = l_raw if isinstance(l_raw, (list, tuple)) else [l_raw]
            w_list = w_raw if isinstance(w_raw, (list, tuple)) else [w_raw]
            h_list = h_raw if isinstance(h_raw, (list, tuple)) else [h_raw]

            (_aligned, n_blocks) = gh_match(l_list, w_list, h_list)
            l_list, w_list, h_list = _aligned
            if n_blocks <= 0:
                n_blocks = 1
                l_list, w_list, h_list = [32.0], [32.0], [20.0]

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = make_ref_plane("XZ")

            # 先清空
            self.BlockCutter_2_TimberBrep = []
            self.BlockCutter_2_FacePlaneList = []
            self.BlockCutter_2_Log = []

            # legacy（默认取第0块）
            self.BlockCutter_2_FaceList        = []
            self.BlockCutter_2_PointList       = []
            self.BlockCutter_2_EdgeList        = []
            self.BlockCutter_2_CenterPoint     = None
            self.BlockCutter_2_CenterAxisLines = []
            self.BlockCutter_2_EdgeMidPoints   = []
            self.BlockCutter_2_Corner0Planes   = []
            self.BlockCutter_2_LocalAxesPlane  = None
            self.BlockCutter_2_AxisX           = None
            self.BlockCutter_2_AxisY           = None
            self.BlockCutter_2_AxisZ           = None
            self.BlockCutter_2_FaceDirTags     = []
            self.BlockCutter_2_EdgeDirTags     = []
            self.BlockCutter_2_Corner0EdgeDirs = []

            self.Log.append("[STEP5] BlockCutter::2 生成刀块数 = {}".format(n_blocks))

            for i in range(n_blocks):
                try:
                    length_fen = 32.0 if l_list[i] is None else float(l_list[i])
                    width_fen  = 32.0 if w_list[i] is None else float(w_list[i])
                    height_fen = 20.0 if h_list[i] is None else float(h_list[i])
                except:
                    length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

                self.Log.append("[STEP5] BlockCutter::2[{}] L/W/H = {}, {}, {}".format(i, length_fen, width_fen, height_fen))

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

                if i == 0:
                    self.BlockCutter_2_FaceList        = faces or []
                    self.BlockCutter_2_PointList       = points or []
                    self.BlockCutter_2_EdgeList        = edges or []
                    self.BlockCutter_2_CenterPoint     = center_pt
                    self.BlockCutter_2_CenterAxisLines = center_axes or []
                    self.BlockCutter_2_EdgeMidPoints   = edge_midpts or []
                    self.BlockCutter_2_Corner0Planes   = corner0_planes or []
                    self.BlockCutter_2_LocalAxesPlane  = local_axes_plane
                    self.BlockCutter_2_AxisX           = axis_x
                    self.BlockCutter_2_AxisY           = axis_y
                    self.BlockCutter_2_AxisZ           = axis_z
                    self.BlockCutter_2_FaceDirTags     = face_tags or []
                    self.BlockCutter_2_EdgeDirTags     = edge_tags or []
                    self.BlockCutter_2_Corner0EdgeDirs = corner0_dirs or []

                self.BlockCutter_2_TimberBrep.append(timber_brep)
                self.BlockCutter_2_FacePlaneList.append(face_planes or [])
                self.BlockCutter_2_Log.extend(log_lines or [])

        except Exception as e:
            self.Log.append("[ERROR] step5 BlockCutter::2 失败: {}".format(e))
            self.BlockCutter_2_TimberBrep = []
            self.BlockCutter_2_FacePlaneList = []
            self.BlockCutter_2_Log = []
            return self

        # =====================================================
        # 5.2 AlignToolToTimber::3 —— 广播对齐（含 MoveY）
        # =====================================================
        try:
            geo_list = self.BlockCutter_2_TimberBrep or []
            src_faceplanes_list = self.BlockCutter_2_FacePlaneList or []
            tgt_faceplanes = self.FacePlaneList or []

            src_idx_raw = get_input_if_exists("AlignToolToTimber_3__SourcePlane", self.all_get("AlignToolToTimber_3__SourcePlane", 0))
            tgt_idx_raw = get_input_if_exists("AlignToolToTimber_3__TargetPlane", self.all_get("AlignToolToTimber_3__TargetPlane", 0))
            moveY_raw   = get_input_if_exists("AlignToolToTimber_3__MoveY",       self.all_get("AlignToolToTimber_3__MoveY", 0))

            # 其他 align 参数（可选）
            rotate_raw = get_input_if_exists("AlignToolToTimber_3__RotateDeg", self.all_get("AlignToolToTimber_3__RotateDeg", 0))
            flipx_raw  = get_input_if_exists("AlignToolToTimber_3__FlipX",    self.all_get("AlignToolToTimber_3__FlipX", False))
            flipy_raw  = get_input_if_exists("AlignToolToTimber_3__FlipY",    self.all_get("AlignToolToTimber_3__FlipY", False))
            flipz_raw  = get_input_if_exists("AlignToolToTimber_3__FlipZ",    self.all_get("AlignToolToTimber_3__FlipZ", False))
            movex_raw  = get_input_if_exists("AlignToolToTimber_3__MoveX",    self.all_get("AlignToolToTimber_3__MoveX", 0))
            movez_raw  = get_input_if_exists("AlignToolToTimber_3__MoveZ",    self.all_get("AlignToolToTimber_3__MoveZ", 0))

            src_idx_list = ensure_list(src_idx_raw)
            tgt_idx_list = ensure_list(tgt_idx_raw)
            moveY_list   = ensure_list(moveY_raw)

            rotate_list = ensure_list(rotate_raw)
            flipx_list  = ensure_list(flipx_raw)
            flipy_list  = ensure_list(flipy_raw)
            flipz_list  = ensure_list(flipz_raw)
            movex_list  = ensure_list(movex_raw)
            movez_list  = ensure_list(movez_raw)

            # 对齐长度：以 geo_list 为主（通常 1；若 BlockCutter_2 是多块则多）
            n = max(len(geo_list), len(src_idx_list), len(tgt_idx_list), len(moveY_list),
                    len(rotate_list), len(flipx_list), len(flipy_list), len(flipz_list), len(movex_list), len(movez_list))
            if n <= 0:
                n = 1

            geo_list     = broadcast_last(geo_list, n)
            src_idx_list = broadcast_last(src_idx_list, n)
            tgt_idx_list = broadcast_last(tgt_idx_list, n)
            moveY_list   = broadcast_last(moveY_list, n)
            # 关键修复：当 MoveY 是多值而 BlockCutter_2 仅生成 1 组 FacePlaneList 时，
            # 必须将 src_faceplanes_list 广播到 n，确保 i>=1 时仍能取到有效 SourcePlane
            src_faceplanes_list = broadcast_last(src_faceplanes_list, n)

            rotate_list = broadcast_last(rotate_list, n)
            flipx_list  = broadcast_last(flipx_list,  n)
            flipy_list  = broadcast_last(flipy_list,  n)
            flipz_list  = broadcast_last(flipz_list,  n)
            movex_list  = broadcast_last(movex_list,  n)
            movez_list  = broadcast_last(movez_list,  n)

            src_out, tgt_out, xfm_out, mv_out = [], [], [], []

            for i in range(n):
                geo = geo_list[i]
                src_planes = src_faceplanes_list[i] if i < len(src_faceplanes_list) else []
                src_plane = safe_index(src_planes, src_idx_list[i], wrap=True)
                tgt_plane = safe_index(tgt_faceplanes, tgt_idx_list[i], wrap=True)

                if geo is None or src_plane is None or tgt_plane is None:
                    src_out.append(None); tgt_out.append(None); xfm_out.append(None); mv_out.append(None)
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rotate_list[i],
                    flip_x=flipx_list[i],
                    flip_y=flipy_list[i],
                    flip_z=flipz_list[i],
                    move_x=movex_list[i],
                    move_y=moveY_list[i],     # 关键：使用 AlignToolToTimber_3__MoveY
                    move_z=movez_list[i],
                )
                src_out.append(SourceOut)
                tgt_out.append(TargetOut)
                xfm_out.append(TransformOut)
                mv_out.append(MovedGeo)

            # Tree 输出：对齐后的结果统一递归拍平为几何列表（避免 Goo->Geometry 转换失败）
            self.AlignToolToTimber_3_SourceOut_tree    = [flatten_tree(x) for x in src_out]
            self.AlignToolToTimber_3_TargetOut_tree    = [flatten_tree(x) for x in tgt_out]
            self.AlignToolToTimber_3_TransformOut_tree = [flatten_tree(x) for x in xfm_out]
            self.AlignToolToTimber_3_MovedGeo_tree     = flatten_tree(mv_out)

            self.AlignToolToTimber_3_Log = ["[STEP5] AlignToolToTimber::3 完成，对齐 {} 组".format(n)]
            self.Log.extend(self.AlignToolToTimber_3_Log)

        except Exception as e:
            self.Log.append("[ERROR] step5 AlignToolToTimber::3 失败: {}".format(e))

        return self

# ------------------------------------------------------
# Step 6：窄口部分（BlockCutter::3 + AlignToolToTimber::4）
# ------------------------------------------------------

    def step6_blockcutter3_and_align4(self):
        """
        Step 6：窄口部分切削准备（当前步仅完成刀块构建 + 对位 AlignToolToTimber::4）
        - BlockCutter::3：默认参考平面为 GH 的 XZ Plane（按 GH 定义），base_point 默认为原点
        - AlignToolToTimber::4：MoveY 通常为两个值，其他输入参数为单值，需要广播对齐
          关键：当 n 由 MoveY 拉长时，必须将 src_faceplanes_list 广播到 n，避免 i>=1 时 src_plane=None 导致跳过
        """
        # =====================================================
        # 6.1 BlockCutter::3 —— 生成刀块（通常单块；也兼容列表尺寸）
        # =====================================================
        try:
            l_raw = get_input_if_exists("BlockCutter_3__length_fen", self.all_get("BlockCutter_3__length_fen", 32.0))
            w_raw = get_input_if_exists("BlockCutter_3__width_fen",  self.all_get("BlockCutter_3__width_fen",  32.0))
            h_raw = get_input_if_exists("BlockCutter_3__height_fen", self.all_get("BlockCutter_3__height_fen", 20.0))

            l_list = l_raw if isinstance(l_raw, (list, tuple)) else [l_raw]
            w_list = w_raw if isinstance(w_raw, (list, tuple)) else [w_raw]
            h_list = h_raw if isinstance(h_raw, (list, tuple)) else [h_raw]

            (_aligned, n_blocks) = gh_match(l_list, w_list, h_list)
            l_list, w_list, h_list = _aligned
            if n_blocks <= 0:
                n_blocks = 1
                l_list, w_list, h_list = [32.0], [32.0], [20.0]

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = make_ref_plane("XZ")

            # 清空
            self.BlockCutter_3_TimberBrep = []
            self.BlockCutter_3_FacePlaneList = []
            self.BlockCutter_3_Log = []

            # legacy（默认取第0块）
            self.BlockCutter_3_FaceList        = []
            self.BlockCutter_3_PointList       = []
            self.BlockCutter_3_EdgeList        = []
            self.BlockCutter_3_CenterPoint     = None
            self.BlockCutter_3_CenterAxisLines = []
            self.BlockCutter_3_EdgeMidPoints   = []
            self.BlockCutter_3_Corner0Planes   = []
            self.BlockCutter_3_LocalAxesPlane  = None
            self.BlockCutter_3_AxisX           = None
            self.BlockCutter_3_AxisY           = None
            self.BlockCutter_3_AxisZ           = None
            self.BlockCutter_3_FaceDirTags     = []
            self.BlockCutter_3_EdgeDirTags     = []
            self.BlockCutter_3_Corner0EdgeDirs = []

            self.Log.append("[STEP6] BlockCutter::3 生成刀块数 = {}".format(n_blocks))

            for i in range(n_blocks):
                try:
                    length_fen = 32.0 if l_list[i] is None else float(l_list[i])
                    width_fen  = 32.0 if w_list[i] is None else float(w_list[i])
                    height_fen = 20.0 if h_list[i] is None else float(h_list[i])
                except:
                    length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

                self.Log.append("[STEP6] BlockCutter::3[{}] L/W/H = {}, {}, {}".format(i, length_fen, width_fen, height_fen))

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

                if i == 0:
                    self.BlockCutter_3_FaceList        = faces or []
                    self.BlockCutter_3_PointList       = points or []
                    self.BlockCutter_3_EdgeList        = edges or []
                    self.BlockCutter_3_CenterPoint     = center_pt
                    self.BlockCutter_3_CenterAxisLines = center_axes or []
                    self.BlockCutter_3_EdgeMidPoints   = edge_midpts or []
                    self.BlockCutter_3_Corner0Planes   = corner0_planes or []
                    self.BlockCutter_3_LocalAxesPlane  = local_axes_plane
                    self.BlockCutter_3_AxisX           = axis_x
                    self.BlockCutter_3_AxisY           = axis_y
                    self.BlockCutter_3_AxisZ           = axis_z
                    self.BlockCutter_3_FaceDirTags     = face_tags or []
                    self.BlockCutter_3_EdgeDirTags     = edge_tags or []
                    self.BlockCutter_3_Corner0EdgeDirs = corner0_dirs or []

                self.BlockCutter_3_TimberBrep.append(timber_brep)
                self.BlockCutter_3_FacePlaneList.append(face_planes or [])
                self.BlockCutter_3_Log.extend(log_lines or [])

        except Exception as e:
            self.Log.append("[ERROR] step6 BlockCutter::3 失败: {}".format(e))
            self.BlockCutter_3_TimberBrep = []
            self.BlockCutter_3_FacePlaneList = []
            self.BlockCutter_3_Log = []
            return self

        # =====================================================
        # 6.2 AlignToolToTimber::4 —— 广播对齐（含 MoveY）
        # =====================================================
        try:
            geo_list = self.BlockCutter_3_TimberBrep or []
            src_faceplanes_list = self.BlockCutter_3_FacePlaneList or []
            tgt_faceplanes = self.FacePlaneList or []

            src_idx_raw = get_input_if_exists("AlignToolToTimber_4__SourcePlane", self.all_get("AlignToolToTimber_4__SourcePlane", 0))
            tgt_idx_raw = get_input_if_exists("AlignToolToTimber_4__TargetPlane", self.all_get("AlignToolToTimber_4__TargetPlane", 0))
            moveY_raw   = get_input_if_exists("AlignToolToTimber_4__MoveY",       self.all_get("AlignToolToTimber_4__MoveY", 0))

            # 其他 align 参数（可选）
            rotate_raw = get_input_if_exists("AlignToolToTimber_4__RotateDeg", self.all_get("AlignToolToTimber_4__RotateDeg", 0))
            flipx_raw  = get_input_if_exists("AlignToolToTimber_4__FlipX",    self.all_get("AlignToolToTimber_4__FlipX", False))
            flipy_raw  = get_input_if_exists("AlignToolToTimber_4__FlipY",    self.all_get("AlignToolToTimber_4__FlipY", False))
            flipz_raw  = get_input_if_exists("AlignToolToTimber_4__FlipZ",    self.all_get("AlignToolToTimber_4__FlipZ", False))
            movex_raw  = get_input_if_exists("AlignToolToTimber_4__MoveX",    self.all_get("AlignToolToTimber_4__MoveX", 0))
            movez_raw  = get_input_if_exists("AlignToolToTimber_4__MoveZ",    self.all_get("AlignToolToTimber_4__MoveZ", 0))

            src_idx_list = ensure_list(src_idx_raw)
            tgt_idx_list = ensure_list(tgt_idx_raw)
            moveY_list   = ensure_list(moveY_raw)

            rotate_list = ensure_list(rotate_raw)
            flipx_list  = ensure_list(flipx_raw)
            flipy_list  = ensure_list(flipy_raw)
            flipz_list  = ensure_list(flipz_raw)
            movex_list  = ensure_list(movex_raw)
            movez_list  = ensure_list(movez_raw)

            # n 由 MoveY 等拉长（GH longest-list）
            n = max(len(geo_list), len(src_idx_list), len(tgt_idx_list), len(moveY_list),
                    len(rotate_list), len(flipx_list), len(flipy_list), len(flipz_list), len(movex_list), len(movez_list))
            if n <= 0:
                n = 1

            geo_list     = broadcast_last(geo_list, n)
            src_idx_list = broadcast_last(src_idx_list, n)
            tgt_idx_list = broadcast_last(tgt_idx_list, n)
            moveY_list   = broadcast_last(moveY_list, n)

            # 关键：广播 SourceFacePlaneList，避免 i>=1 时 src_plane=None
            src_faceplanes_list = broadcast_last(src_faceplanes_list, n)

            rotate_list = broadcast_last(rotate_list, n)
            flipx_list  = broadcast_last(flipx_list,  n)
            flipy_list  = broadcast_last(flipy_list,  n)
            flipz_list  = broadcast_last(flipz_list,  n)
            movex_list  = broadcast_last(movex_list,  n)
            movez_list  = broadcast_last(movez_list,  n)

            src_out, tgt_out, xfm_out, mv_out = [], [], [], []

            for i in range(n):
                geo = geo_list[i]
                src_planes = src_faceplanes_list[i] if i < len(src_faceplanes_list) else []
                src_plane = safe_index(src_planes, src_idx_list[i], wrap=True)
                tgt_plane = safe_index(tgt_faceplanes, tgt_idx_list[i], wrap=True)

                if geo is None or src_plane is None or tgt_plane is None:
                    src_out.append(None); tgt_out.append(None); xfm_out.append(None); mv_out.append(None)
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rotate_list[i],
                    flip_x=flipx_list[i],
                    flip_y=flipy_list[i],
                    flip_z=flipz_list[i],
                    move_x=movex_list[i],
                    move_y=moveY_list[i],
                    move_z=movez_list[i],
                )
                src_out.append(SourceOut)
                tgt_out.append(TargetOut)
                xfm_out.append(TransformOut)
                mv_out.append(MovedGeo)

            self.AlignToolToTimber_4_SourceOut_tree    = [flatten_tree(x) for x in src_out]
            self.AlignToolToTimber_4_TargetOut_tree    = [flatten_tree(x) for x in tgt_out]
            self.AlignToolToTimber_4_TransformOut_tree = [flatten_tree(x) for x in xfm_out]
            self.AlignToolToTimber_4_MovedGeo_tree     = flatten_tree(mv_out)

            self.AlignToolToTimber_4_Log = ["[STEP6] AlignToolToTimber::4 完成，对齐 {} 组".format(n)]
            self.Log.extend(self.AlignToolToTimber_4_Log)

        except Exception as e:
            self.Log.append("[ERROR] step6 AlignToolToTimber::4 失败: {}".format(e))

        return self


        # ------------------------------------------------------
        # Step 7：欹䫜切削准备（QiAOTool + PlaneFromLists::2/3 + AlignToolToTimber::5）
        # ------------------------------------------------------


    def step7_qiao_and_align5(self):
        """
        Step 7：欹䫜切削部分（QiAOTool + PlaneFromLists::2/3 + AlignToolToTimber::5）

        修正说明（参考附件 QiAoToolSolver.py）：
        - 不再尝试不存在/不匹配签名的 Builder 名称，改为直接调用：
            build_timber_block_uniform + build_qiao_tool + FTPlaneFromLists + FTAligner + SolidDifference
        - 关键：参考平面严格使用 GH XZ Plane 轴系（X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)）
        - 参数来自：输入端覆盖 > AllDict > 默认值
        - 生成：
            QiAOTool_TimberBrep / QiAOTool_FacePlaneList / QiAOTool_Corner0Planes / QiAOTool_EdgeMidPoints
            QiAOTool_ToolBrep / QiAOTool_AlignedTool / QiAOTool_CutTimbers
        """
        # =====================================================
        # Step7.1 QiAOTool（按 QiAoToolSolver 的参数与流程）
        # =====================================================
        try:
            from yingzao.ancientArchi import (
                build_timber_block_uniform,
                build_qiao_tool,
                FTPlaneFromLists,
                FTAligner,
                FT_CutTimberByTools,
            )
        except Exception as e:
            self.Log.append("[STEP7][ERROR] 无法导入 QiAOTool 依赖: {}".format(e))
            return self

        # --- 读取参数（输入端覆盖 > DB > 默认） ---
        l_raw = get_input_if_exists("QiAOTool__length_fen", self.all_get("QiAOTool__length_fen", 41.0))
        w_raw = get_input_if_exists("QiAOTool__width_fen",  self.all_get("QiAOTool__width_fen",  16.0))
        h_raw = get_input_if_exists("QiAOTool__height_fen", self.all_get("QiAOTool__height_fen", 10.0))

        qi_h_raw   = get_input_if_exists("QiAOTool__qi_height",     self.all_get("QiAOTool__qi_height", 4.0))
        sha_w_raw  = get_input_if_exists("QiAOTool__sha_width",     self.all_get("QiAOTool__sha_width", 2.0))
        qi_off_raw = get_input_if_exists("QiAOTool__qi_offset_fen", self.all_get("QiAOTool__qi_offset_fen", 0.5))

        # 可选（数据库里不一定有，但参考 QiAoToolSolver 需要）
        extrude_len_raw = get_input_if_exists("QiAOTool__extrude_length", self.all_get("QiAOTool__extrude_length", 28.0))
        extrude_pos_raw = get_input_if_exists("QiAOTool__extrude_positive", self.all_get("QiAOTool__extrude_positive", False))

        # base_point（默认原点；允许输入端/DB 覆盖）
        bp_raw = get_input_if_exists("QiAOTool__base_point", self.all_get("QiAOTool__base_point", None))
        bp = normalize_point3d(bp_raw)

        # 数值转换
        def _to_float(x, default):
            try:
                if x is None:
                    return float(default)
                return float(x)
            except Exception:
                return float(default)

        length_fen  = _to_float(l_raw, 41.0)
        width_fen   = _to_float(w_raw,  16.0)
        height_fen  = _to_float(h_raw,  10.0)

        qi_height   = _to_float(qi_h_raw, 4.0)
        sha_width   = _to_float(sha_w_raw, 2.0)
        qi_offset   = _to_float(qi_off_raw, 0.5)

        extrude_len = _to_float(extrude_len_raw, 28.0)

        def _to_bool(x, default=False):
            if x is None:
                return bool(default)
            if isinstance(x, bool):
                return x
            # numbers
            if isinstance(x, (int, float)):
                return bool(int(x))
            # strings
            try:
                s = str(x).strip().lower()
                if s in ("true", "t", "yes", "y", "1", "on"):
                    return True
                if s in ("false", "f", "no", "n", "0", "off", ""):
                    return False
            except Exception:
                pass
            return bool(default)

        extrude_pos = _to_bool(extrude_pos_raw, False)

        # 参考平面：严格 GH XZ Plane（原点为 bp）
        qi_ref_plane = make_ref_plane("XZ")
        qi_ref_plane.Origin = bp
        timber_ref_plane = make_ref_plane("XZ")
        timber_ref_plane.Origin = bp

        # --- 7.1.1 工具木坯（供 PlaneFromLists::3 用） ---
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
                length_fen, width_fen, height_fen, bp, timber_ref_plane
            )

            self.QiAOTool_TimberBrep      = timber_brep
            self.QiAOTool_FaceList        = faces or []
            self.QiAOTool_PointList       = points or []
            self.QiAOTool_EdgeList        = edges or []
            self.QiAOTool_CenterPoint     = center_pt
            self.QiAOTool_CenterAxisLines = center_axes or []
            self.QiAOTool_EdgeMidPoints   = edge_midpts or []
            self.QiAOTool_FacePlaneList   = face_planes or []
            self.QiAOTool_Corner0Planes   = corner0_planes or []
            self.QiAOTool_LocalAxesPlane  = local_axes_plane
            self.QiAOTool_AxisX           = axis_x
            self.QiAOTool_AxisY           = axis_y
            self.QiAOTool_AxisZ           = axis_z
            self.QiAOTool_FaceDirTags     = face_tags or []
            self.QiAOTool_EdgeDirTags     = edge_tags or []
            self.QiAOTool_Corner0EdgeDirs = corner0_dirs or []
            self.QiAOTool_Log = log_lines or []
            self.Log.append("[STEP7] QiAOTool timber OK: L/W/H={}/{}/{}".format(length_fen, width_fen, height_fen))
        except Exception as e:
            self.QiAOTool_TimberBrep = None
            self.QiAOTool_EdgeMidPoints = []
            self.QiAOTool_Corner0Planes = []
            self.QiAOTool_FacePlaneList = []
            self.QiAOTool_Log = ["[ERROR] build_timber_block_uniform: {}".format(e)]
            self.Log.append("[STEP7][ERROR] QiAOTool timber 失败: {}".format(e))
            return self

        # --- 7.1.2 生成欹䫜刀具（build_qiao_tool） ---
        try:
            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset,
                extrude_len,
                bp,
                qi_ref_plane,
                extrude_pos
            )
            self.QiAOTool_ToolBrep = ToolBrep
            self.QiAOTool_QiAo_FacePlane = FacePlane
            self.Log.append("[STEP7] QiAOTool tool OK (qi_height={}, sha_width={}, qi_offset={}, extrude_len={}, extrude_positive={})".format(
                qi_height, sha_width, qi_offset, extrude_len, extrude_pos
            ))
        except Exception as e:
            self.QiAOTool_ToolBrep = None
            self.QiAOTool_QiAo_FacePlane = None
            self.Log.append("[STEP7][ERROR] build_qiao_tool 失败: {}".format(e))
            return self

        # --- 7.1.3 对位（参考 QiAoToolSolver 固定索引与 BlockRotDeg=90） ---
        try:
            pfl = FTPlaneFromLists(wrap=True)
            _, _, block_face_plane, _ = pfl.build_plane(
                self.QiAOTool_EdgeMidPoints, self.QiAOTool_Corner0Planes, 8, 1
            )

            aligned_list = []
            if self.QiAOTool_ToolBrep is not None and self.QiAOTool_QiAo_FacePlane is not None and block_face_plane is not None:
                aligned, xf, *_ = FTAligner.align(
                    self.QiAOTool_ToolBrep,
                    self.QiAOTool_QiAo_FacePlane,
                    None,
                    block_face_plane,
                    None,
                    None, None, None,
                    None, None, None,
                    None, None, None,
                    None,             # ToolRotDeg = None
                    float(90.0)       # BlockRotDeg = 90
                )
                aligned_list = [aligned]
            self.QiAOTool_AlignedTool = aligned_list
            self.Log.append("[STEP7] QiAOTool align OK (BlockRotDeg=90, PFL IndexOrigin=8 IndexPlane=1)")
        except Exception as e:
            self.QiAOTool_AlignedTool = []
            self.Log.append("[STEP7][ERROR] QiAOTool align 失败: {}".format(e))
            return self

        # --- 7.1.4 切削：优先 GH SolidDifference（ghpythonlib），否则 fallback ---
        self.QiAOTool_CutTimbers = []
        self.QiAOTool_FailTimbers = []
        try:
            if self.QiAOTool_TimberBrep is None:
                self.Log.append("[STEP7][WARN] QiAOTool TimberBrep None，跳过切削")
            else:
                if ghc is not None:
                    res = ghc.SolidDifference(self.QiAOTool_TimberBrep, self.QiAOTool_AlignedTool)
                    res0 = res[0] if (isinstance(res, tuple) and len(res) > 0) else res
                    parts = flatten_tree(res0)
                    parts = [p for p in parts if p is not None]
                    self.QiAOTool_CutTimbers = parts
                    self.Log.append("[STEP7] QiAOTool cut OK (GH SolidDifference), parts={}".format(len(parts)))
                else:
                    cutter = FT_CutTimberByTools(self.QiAOTool_TimberBrep, self.QiAOTool_AlignedTool)
                    cut, fail, log_lines = cutter.run()
                    self.QiAOTool_CutTimbers = flatten_tree(cut)
                    self.QiAOTool_FailTimbers = flatten_tree(fail)
                    self.Log.append("[STEP7] QiAOTool cut OK (fallback), parts={}".format(len(self.QiAOTool_CutTimbers)))
        except Exception as e:
            self.QiAOTool_CutTimbers = []
            self.QiAOTool_FailTimbers = []
            self.Log.append("[STEP7][ERROR] QiAOTool cut 失败: {}".format(e))

        # =====================================================
        # 以下保持原实现：PlaneFromLists::2 / PlaneFromLists::3 / AlignToolToTimber::5
        # =====================================================


        # =====================================================
        # 7.2 PlaneFromLists::2（基于 Timber_block_uniform）
        # =====================================================
        try:
            OriginPoints = self.EdgeMidPoints or []
            BasePlanes   = self.Corner0Planes or []

            idx_o_raw = get_input_if_exists("PlaneFromLists_2__IndexOrigin", self.all_get("PlaneFromLists_2__IndexOrigin", 0))
            idx_p_raw = get_input_if_exists("PlaneFromLists_2__IndexPlane",  self.all_get("PlaneFromLists_2__IndexPlane", 0))

            Wrap = get_input_if_exists("PlaneFromLists_2__Wrap", self.all_get("PlaneFromLists_2__Wrap", True))
            Wrap = True if Wrap is None else bool(Wrap)

            idx_o_list = ensure_list(idx_o_raw)
            idx_p_list = ensure_list(idx_p_raw)
            (idx_o_list, idx_p_list), n = gh_match(idx_o_list, idx_p_list)
            if n == 0:
                n = 1
                idx_o_list = [0]
                idx_p_list = [0]

            builder = FTPlaneFromLists(wrap=Wrap)

            bp_list, op_list, rp_list, plog = [], [], [], []
            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints, BasePlanes, idx_o_list[i], idx_p_list[i]
                )
                bp_list.append(BasePlane)
                op_list.append(OriginPoint)
                rp_list.append(ResultPlane)
                if Log:
                    plog.extend(Log if isinstance(Log, (list, tuple)) else [Log])

            self.PlaneFromLists_2_BasePlane   = bp_list
            self.PlaneFromLists_2_OriginPoint = op_list
            self.PlaneFromLists_2_ResultPlane = rp_list
            self.PlaneFromLists_2_Log         = plog
            self.Log.append("[PFL2] PlaneFromLists::2 完成，输出 {} 组 ResultPlane".format(len(rp_list)))

        except Exception as e:
            self.Log.append("[ERROR] step7 PlaneFromLists::2 失败: {}".format(e))
            self.PlaneFromLists_2_ResultPlane = []

        # =====================================================
        # 7.3 PlaneFromLists::3（基于 QiAOTool）
        # =====================================================
        try:
            OriginPoints = self.QiAOTool_EdgeMidPoints or []
            BasePlanes   = self.QiAOTool_Corner0Planes or []

            idx_o_raw = get_input_if_exists("PlaneFromLists_3__IndexOrigin", self.all_get("PlaneFromLists_3__IndexOrigin", 0))
            idx_p_raw = get_input_if_exists("PlaneFromLists_3__IndexPlane",  self.all_get("PlaneFromLists_3__IndexPlane", 0))

            Wrap = get_input_if_exists("PlaneFromLists_3__Wrap", self.all_get("PlaneFromLists_3__Wrap", True))
            Wrap = True if Wrap is None else bool(Wrap)

            idx_o_list = ensure_list(idx_o_raw)
            idx_p_list = ensure_list(idx_p_raw)
            (idx_o_list, idx_p_list), n = gh_match(idx_o_list, idx_p_list)
            if n == 0:
                n = 1
                idx_o_list = [0]
                idx_p_list = [0]

            builder = FTPlaneFromLists(wrap=Wrap)

            bp_list, op_list, rp_list, plog = [], [], [], []
            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints, BasePlanes, idx_o_list[i], idx_p_list[i]
                )
                bp_list.append(BasePlane)
                op_list.append(OriginPoint)
                rp_list.append(ResultPlane)
                if Log:
                    plog.extend(Log if isinstance(Log, (list, tuple)) else [Log])

            self.PlaneFromLists_3_BasePlane   = bp_list
            self.PlaneFromLists_3_OriginPoint = op_list
            self.PlaneFromLists_3_ResultPlane = rp_list
            self.PlaneFromLists_3_Log         = plog
            self.Log.append("[PFL3] PlaneFromLists::3 完成，输出 {} 组 ResultPlane".format(len(rp_list)))

        except Exception as e:
            self.Log.append("[ERROR] step7 PlaneFromLists::3 失败: {}".format(e))
            self.PlaneFromLists_3_ResultPlane = []

        # =====================================================
        # 7.4 AlignToolToTimber::5（Geo = QiAOTool.CutTimbers）
        # =====================================================
        try:
            geo_list = ensure_list(self.QiAOTool_CutTimbers)
            src_list = ensure_list(self.PlaneFromLists_3_ResultPlane)
            tgt_list = ensure_list(self.PlaneFromLists_2_ResultPlane)

            RotateDeg = get_input_if_exists("AlignToolToTimber_5__RotateDeg", self.all_get("AlignToolToTimber_5__RotateDeg", 0))
            rot_list = ensure_list(RotateDeg)

            # 对齐主轴：按 SourcePlane 列表顺序（PlaneFromLists::3）为主，保证 i 顺序一致
            n = max(len(src_list), len(tgt_list), len(rot_list), len(geo_list))
            if n == 0:
                n = 1

            src_list = broadcast_last(src_list, n)
            tgt_list = broadcast_last(tgt_list, n)
            rot_list = broadcast_last(rot_list, n)
            geo_list = broadcast_last(geo_list, n)

            src_out, tgt_out, xfm_out, mv_out = [], [], [], []
            for i in range(n):
                geo = geo_list[i]
                src_plane = src_list[i]
                tgt_plane = tgt_list[i]

                if geo is None or src_plane is None or tgt_plane is None:
                    src_out.append(None); tgt_out.append(None); xfm_out.append(None); mv_out.append(None)
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rot_list[i],
                    flip_x=False,
                    flip_y=False,
                    flip_z=False,
                    move_x=0,
                    move_y=0,
                    move_z=0,
                )

                src_out.append(SourceOut)
                tgt_out.append(TargetOut)
                xfm_out.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                mv_out.append(MovedGeo)

            self.AlignToolToTimber_5_SourceOut    = src_out
            self.AlignToolToTimber_5_TargetOut    = tgt_out
            self.AlignToolToTimber_5_TransformOut = xfm_out
            self.AlignToolToTimber_5_MovedGeo     = mv_out
            self.AlignToolToTimber_5_Log          = ["[STEP7] AlignToolToTimber::5 完成，对齐 {} 组".format(n)]
            self.Log.extend(self.AlignToolToTimber_5_Log)

        except Exception as e:
            self.Log.append("[ERROR] step7 AlignToolToTimber::5 失败: {}".format(e))

        return self



    def step8_gongyan_and_align6(self):
        """
        Step 8：栱眼切削准备（GongYan + PlaneFromLists::4 + AlignToolToTimber::6）

        要点：
        - GongYan：仅读取 EM_fen（GongYan__EM_fen）；BasePoint 默认原点；其余参数用默认值/None
        - PlaneFromLists::4：OriginPoints = Timber_block_uniform.PointList；BasePlanes = Corner0Planes；
          IndexOrigin/IndexPlane 支持列表，按 GH 长列表规则广播对齐
        - AlignToolToTimber::6：
          Geo = GongYan.ToolBrep（可能为“2 个 Brep 的列表”，需视为整体一起变换）
          SourcePlane = GongYan.SectionPlanes[SourcePlaneIndex]
          TargetPlane = PlaneFromLists::4.ResultPlane（通常为 2 个）
          RotateDeg 为列表（2 个），其它为单值，广播对齐，依次对“整体 Geo”执行对位
        """
        # =====================================================
        # 8.1 GongYan
        # =====================================================
        try:
            from yingzao.ancientArchi import FT_GongYan_CaiQi_ToolBuilder
        except Exception as e:
            self.GongYan_Log = ["[STEP8][ERROR] 无法导入 FT_GongYan_CaiQi_ToolBuilder: {}".format(e)]
            self.Log.extend(self.GongYan_Log)
            return self

        try:
            bp_raw = get_input_if_exists("GongYan__BasePoint", self.all_get("GongYan__BasePoint", None))
            bp = normalize_point3d(bp_raw)

            em_raw = get_input_if_exists("GongYan__EM_fen", self.all_get("GongYan__EM_fen", None))
            try:
                EM_fen = float(em_raw) if em_raw is not None else None
            except Exception:
                EM_fen = None

            # SectionPlane：用 GH XZ Plane 作为默认（与本构件一致），原点设为 bp
            sec_plane = get_input_if_exists("GongYan__SectionPlane", None)
            if sec_plane is None:
                sec_plane = make_ref_plane("XZ")
                sec_plane.Origin = bp

            builder = FT_GongYan_CaiQi_ToolBuilder(
                base_point=bp,
                section_plane=sec_plane,
                EM_fen=EM_fen,
                EC_fen=None,
                AI_fen=None,
                AG_fen=None,
                JR_fen=None,
                HK_fen=None,
                Thickness=None,
                OffsetDist=None
            )

            (SectionCurve, SectionFace, LeftCurve, RightCurve,
             SymmetryAxis, AllPoints, ToolBrep, SectionPlanes, Log) = builder.build()

            self.GongYan_SectionCurve  = SectionCurve
            self.GongYan_SectionFace   = SectionFace
            self.GongYan_LeftCurve     = LeftCurve
            self.GongYan_RightCurve    = RightCurve
            self.GongYan_SymmetryAxis  = SymmetryAxis
            self.GongYan_AllPoints     = AllPoints
            self.GongYan_ToolBrep      = ToolBrep
            self.GongYan_SectionPlanes = SectionPlanes if SectionPlanes is not None else []
            self.GongYan_Log           = Log if isinstance(Log, (list, tuple)) else ([Log] if Log else [])
            self.Log.append("[STEP8] GongYan build OK (EM_fen={})".format(EM_fen))

        except Exception as e:
            import traceback
            self.GongYan_ToolBrep = None
            self.GongYan_SectionPlanes = []
            self.GongYan_Log = ["[STEP8][ERROR] GongYan 执行异常: {}\n{}".format(str(e), traceback.format_exc())]
            self.Log.extend(self.GongYan_Log)
            return self

        # =====================================================
        # 8.2 PlaneFromLists::4（基于 Timber_block_uniform）
        # =====================================================
        try:
            OriginPoints = self.PointList or []
            BasePlanes   = self.Corner0Planes or []

            idx_o_raw = get_input_if_exists("PlaneFromLists_4__IndexOrigin", self.all_get("PlaneFromLists_4__IndexOrigin", 0))
            idx_p_raw = get_input_if_exists("PlaneFromLists_4__IndexPlane",  self.all_get("PlaneFromLists_4__IndexPlane", 0))

            Wrap = get_input_if_exists("PlaneFromLists_4__Wrap", self.all_get("PlaneFromLists_4__Wrap", True))
            Wrap = True if Wrap is None else bool(Wrap)

            idx_o_list = ensure_list(idx_o_raw)
            idx_p_list = ensure_list(idx_p_raw)
            (idx_o_list, idx_p_list), n = gh_match(idx_o_list, idx_p_list)
            if n == 0:
                n = 1
                idx_o_list = [0]
                idx_p_list = [0]

            builder = FTPlaneFromLists(wrap=Wrap)

            bp_list, op_list, rp_list, plog = [], [], [], []
            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints, BasePlanes, idx_o_list[i], idx_p_list[i]
                )
                bp_list.append(BasePlane)
                op_list.append(OriginPoint)
                rp_list.append(ResultPlane)
                if Log:
                    plog.extend(Log if isinstance(Log, (list, tuple)) else [Log])

            self.PlaneFromLists_4_BasePlane   = bp_list
            self.PlaneFromLists_4_OriginPoint = op_list
            self.PlaneFromLists_4_ResultPlane = rp_list
            self.PlaneFromLists_4_Log         = plog
            self.Log.append("[PFL4] PlaneFromLists::4 完成，输出 {} 组 ResultPlane".format(len(rp_list)))

        except Exception as e:
            self.PlaneFromLists_4_ResultPlane = []
            self.PlaneFromLists_4_Log = ["[STEP8][ERROR] PlaneFromLists::4 失败: {}".format(e)]
            self.Log.extend(self.PlaneFromLists_4_Log)
            return self

        # =====================================================
        # 8.3 AlignToolToTimber::6（Geo 作为整体 + 广播）
        # =====================================================
        try:
            geo_group = self.GongYan_ToolBrep
            # 视为整体：不对 geo_group 做 ensure_list 广播，只在循环中重复引用
            src_planes = self.GongYan_SectionPlanes or []

            src_idx_raw = get_input_if_exists("AlignToolToTimber_6__SourcePlane", self.all_get("AlignToolToTimber_6__SourcePlane", 0))
            tgt_planes_list = self.PlaneFromLists_4_ResultPlane or []

            rot_raw   = get_input_if_exists("AlignToolToTimber_6__RotateDeg", self.all_get("AlignToolToTimber_6__RotateDeg", 0))
            flipx_raw = get_input_if_exists("AlignToolToTimber_6__FlipX",     self.all_get("AlignToolToTimber_6__FlipX", False))
            movex_raw = get_input_if_exists("AlignToolToTimber_6__MoveX",     self.all_get("AlignToolToTimber_6__MoveX", 0))
            movez_raw = get_input_if_exists("AlignToolToTimber_6__MoveZ",     self.all_get("AlignToolToTimber_6__MoveZ", 0))

            rot_list   = ensure_list(rot_raw)
            flipx_list = ensure_list(flipx_raw)
            movex_list = ensure_list(movex_raw)
            movez_list = ensure_list(movez_raw)

            # 目标平面也作为列表参与广播
            tgt_list = ensure_list(tgt_planes_list)

            n = max(len(rot_list), len(tgt_list), len(flipx_list), len(movex_list), len(movez_list))
            if n <= 0:
                n = 1

            rot_list   = broadcast_last(rot_list, n)
            tgt_list   = broadcast_last(tgt_list, n)
            flipx_list = broadcast_last(flipx_list, n)
            movex_list = broadcast_last(movex_list, n)
            movez_list = broadcast_last(movez_list, n)

            src_plane = safe_index(src_planes, src_idx_raw, wrap=True)

            src_out, tgt_out, xfm_out, mv_out = [], [], [], []

            for i in range(n):
                tgt_plane = tgt_list[i]

                if geo_group is None or src_plane is None or tgt_plane is None:
                    src_out.append(None); tgt_out.append(None); xfm_out.append(None); mv_out.append(None)
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_group,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rot_list[i],
                    flip_x=flipx_list[i],
                    flip_y=False,
                    flip_z=False,
                    move_x=movex_list[i],
                    move_y=0,
                    move_z=movez_list[i],
                )

                src_out.append(SourceOut)
                tgt_out.append(TargetOut)
                xfm_out.append(TransformOut)
                # MovedGeo 可能是 list（整体两件），这里保留分支结构：每次循环一个分支
                mv_out.append(MovedGeo)

            self.AlignToolToTimber_6_SourceOut_tree    = [flatten_tree(x) for x in src_out]
            self.AlignToolToTimber_6_TargetOut_tree    = [flatten_tree(x) for x in tgt_out]
            self.AlignToolToTimber_6_TransformOut_tree = [flatten_tree(x) for x in xfm_out]
            self.AlignToolToTimber_6_MovedGeo_tree     = [flatten_tree(x) for x in mv_out]

            self.AlignToolToTimber_6_Log = ["[STEP8] AlignToolToTimber::6 完成，对齐 {} 组（Geo整体）".format(n)]
            self.Log.extend(self.AlignToolToTimber_6_Log)

        except Exception as e:
            self.AlignToolToTimber_6_MovedGeo_tree = []
            self.AlignToolToTimber_6_Log = ["[STEP8][ERROR] AlignToolToTimber::6 失败: {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_6_Log)

        return self
    def step9_cut_timbers(self):
        """
        Step 9：CutTimbersByTools_V3
        - Timbers: Timber_block_uniform 的 TimberBrep
        - Tools: AlignToolToTimber::1~6 的 MovedGeo 汇总（会递归拍平，过滤 None）
        """
        try:
            from yingzao.ancientArchi import FT_CutTimbersByTools_GH_SolidDifference

            timbers = self.TimberBrep

            # 汇总刀具：对齐后的 MovedGeo / MovedGeo_tree
            tools_sources = [
                getattr(self, 'AlignToolToTimber_1_MovedGeo', None),
                getattr(self, 'AlignToolToTimber_2_MovedGeo_tree', None),
                getattr(self, 'AlignToolToTimber_3_MovedGeo_tree', None),
                getattr(self, 'AlignToolToTimber_4_MovedGeo_tree', None),
                getattr(self, 'AlignToolToTimber_5_MovedGeo', None),
                getattr(self, 'AlignToolToTimber_6_MovedGeo_tree', None),
            ]

            tools_flat = []
            for src in tools_sources:
                if src is None:
                    continue
                tools_flat.extend(flatten_tree(src))

            # 过滤空值
            tools_flat = [g for g in tools_flat if g is not None]

            # 便于调试：保留工具列表
            self.CutTools = tools_flat

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=False)
            CutTimbers, FailTimbers, CutLog = cutter.cut(
                timbers=timbers,
                tools=tools_flat,
                keep_inside=False,
                debug=None
            )

            self.CutTimbers = flatten_tree(CutTimbers)
            self.FailTimbers = flatten_tree(FailTimbers)

            self.Log.append("[STEP9] CutTimbersByTools_V3 完成")
            if CutLog:
                self.Log.extend(flatten_tree(CutLog))

        except Exception as e:
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[ERROR] step9 CutTimbersByTools_V3 失败: {}".format(e))

        return self


    def run(self):
        # Step 1：数据库
        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：木坯
        self.step2_timber()

        if self.TimberBrep is None:
            self.Log.append("[RUN] TimberBrep 为空，Step3 跳过。")
            return self

        # Step 3：卷殺 + 对位
        self.step3_juansha()

        # Step 4：BlockCutter::1 + AlignToolToTimber::2
        self.step4_blockcutter_and_align2()

        # Step 5：
        self.step5_blockcutter2_and_align3()

        # Step 6：
        self.step6_blockcutter3_and_align4()

        # Step 7：
        self.step7_qiao_and_align5()

        # Step 8：栱眼
        self.step8_gongyan_and_align6()


        # Step 9：CutTimbersByTools_V3
        self.step9_cut_timbers()

        self.Log.append("[RUN] Step1-9 完成")
        return self
# ==============================================================
# GhPython 组件输出绑定区（developer-friendly）
# ==============================================================

if __name__ == "__main__":

    solver = HuaGong_MatchedChaAng_4PU(DBPath, base_point, Refresh, ghenv).run()

    # --- 最终主输出（当前 Step1-5：以 TimberBrep 占位 CutTimbers；Juansha 工具已生成并对位） ---
    CutTimbers  = flatten_tree(solver.CutTimbers)
    FailTimbers = flatten_tree(solver.FailTimbers)
    Log         = flatten_tree(solver.Log)

    # --- Step1: DB 输出 ---
    Value   = solver.Value
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = flatten_tree(solver.DBLog)

    # --- Step2: Timber_block_uniform 输出 ---
    TimberBrep      = solver.TimberBrep
    FaceList        = flatten_tree(solver.FaceList)
    PointList       = flatten_tree(solver.PointList)
    EdgeList        = flatten_tree(solver.EdgeList)
    CenterPoint     = solver.CenterPoint
    CenterAxisLines = flatten_tree(solver.CenterAxisLines)
    EdgeMidPoints   = flatten_tree(solver.EdgeMidPoints)
    FacePlaneList   = flatten_tree(solver.FacePlaneList)
    Corner0Planes   = flatten_tree(solver.Corner0Planes)
    LocalAxesPlane  = solver.LocalAxesPlane
    AxisX           = solver.AxisX
    AxisY           = solver.AxisY
    AxisZ           = solver.AxisZ
    FaceDirTags     = flatten_tree(solver.FaceDirTags)
    EdgeDirTags     = flatten_tree(solver.EdgeDirTags)
    Corner0EdgeDirs = flatten_tree(solver.Corner0EdgeDirs)
    TimberLog       = flatten_tree(solver.TimberLog)

    # --- Step3: Juansha / PlaneFromLists::1 / AlignToolToTimber::1 输出 ---
    Juansha_ToolBrep        = solver.Juansha_ToolBrep
    Juansha_SectionEdges    = flatten_tree(solver.Juansha_SectionEdges)
    Juansha_HL_Intersection = solver.Juansha_HL_Intersection
    Juansha_HeightFacePlane = solver.Juansha_HeightFacePlane
    Juansha_LengthFacePlane = solver.Juansha_LengthFacePlane
    Juansha_Log             = flatten_tree(solver.Juansha_Log)

    PlaneFromLists_1_BasePlane   = flatten_tree(solver.PlaneFromLists_1_BasePlane)
    PlaneFromLists_1_OriginPoint = flatten_tree(solver.PlaneFromLists_1_OriginPoint)
    PlaneFromLists_1_ResultPlane = flatten_tree(solver.PlaneFromLists_1_ResultPlane)
    PlaneFromLists_1_Log         = flatten_tree(solver.PlaneFromLists_1_Log)

    AlignToolToTimber_1_SourceOut    = flatten_tree(solver.AlignToolToTimber_1_SourceOut)
    AlignToolToTimber_1_TargetOut    = flatten_tree(solver.AlignToolToTimber_1_TargetOut)
    AlignToolToTimber_1_TransformOut = flatten_tree(solver.AlignToolToTimber_1_TransformOut)
    AlignToolToTimber_1_MovedGeo     = flatten_tree(solver.AlignToolToTimber_1_MovedGeo)
    AlignToolToTimber_1_Log          = flatten_tree(solver.AlignToolToTimber_1_Log)


    # --- Step4: BlockCutter::1 / AlignToolToTimber::2 输出 ---
    BlockCutter_1_TimberBrep      = solver.BlockCutter_1_TimberBrep
    BlockCutter_1_TimberBrep_Branches = flatten_tree(getattr(solver, 'BlockCutter_1_TimberBrep_Branches', []))
    BlockCutter_1_FaceList        = flatten_tree(solver.BlockCutter_1_FaceList)
    BlockCutter_1_PointList       = flatten_tree(solver.BlockCutter_1_PointList)
    BlockCutter_1_EdgeList        = flatten_tree(solver.BlockCutter_1_EdgeList)
    BlockCutter_1_CenterPoint     = solver.BlockCutter_1_CenterPoint
    BlockCutter_1_CenterAxisLines = flatten_tree(solver.BlockCutter_1_CenterAxisLines)
    BlockCutter_1_EdgeMidPoints   = flatten_tree(solver.BlockCutter_1_EdgeMidPoints)
    BlockCutter_1_FacePlaneList   = flatten_tree(solver.BlockCutter_1_FacePlaneList)
    BlockCutter_1_FacePlaneList_Branches = flatten_tree(getattr(solver, 'BlockCutter_1_FacePlaneList_Branches', []))
    BlockCutter_1_Corner0Planes   = flatten_tree(solver.BlockCutter_1_Corner0Planes)
    BlockCutter_1_LocalAxesPlane  = solver.BlockCutter_1_LocalAxesPlane
    BlockCutter_1_AxisX           = solver.BlockCutter_1_AxisX
    BlockCutter_1_AxisY           = solver.BlockCutter_1_AxisY
    BlockCutter_1_AxisZ           = solver.BlockCutter_1_AxisZ
    BlockCutter_1_FaceDirTags     = flatten_tree(solver.BlockCutter_1_FaceDirTags)
    BlockCutter_1_EdgeDirTags     = flatten_tree(solver.BlockCutter_1_EdgeDirTags)
    BlockCutter_1_Corner0EdgeDirs = flatten_tree(solver.BlockCutter_1_Corner0EdgeDirs)
    BlockCutter_1_Log             = flatten_tree(solver.BlockCutter_1_Log)

    # Tree 输出保持嵌套列表结构（GH 会自动识别为 Tree）
    AlignToolToTimber_2_SourceOut_tree    = solver.AlignToolToTimber_2_SourceOut_tree
    AlignToolToTimber_2_TargetOut_tree    = solver.AlignToolToTimber_2_TargetOut_tree
    AlignToolToTimber_2_TransformOut_tree = solver.AlignToolToTimber_2_TransformOut_tree
    AlignToolToTimber_2_MovedGeo_tree     = solver.AlignToolToTimber_2_MovedGeo_tree
    AlignToolToTimber_2_Log               = flatten_tree(solver.AlignToolToTimber_2_Log)

    # --- Step5: BlockCutter::2 / AlignToolToTimber::3 输出 ---
    BlockCutter_2_TimberBrep      = flatten_tree(getattr(solver, 'BlockCutter_2_TimberBrep', []))
    BlockCutter_2_FaceList        = flatten_tree(getattr(solver, 'BlockCutter_2_FaceList', []))
    BlockCutter_2_PointList       = flatten_tree(getattr(solver, 'BlockCutter_2_PointList', []))
    BlockCutter_2_EdgeList        = flatten_tree(getattr(solver, 'BlockCutter_2_EdgeList', []))
    BlockCutter_2_CenterPoint     = getattr(solver, 'BlockCutter_2_CenterPoint', None)
    BlockCutter_2_CenterAxisLines = flatten_tree(getattr(solver, 'BlockCutter_2_CenterAxisLines', []))
    BlockCutter_2_EdgeMidPoints   = flatten_tree(getattr(solver, 'BlockCutter_2_EdgeMidPoints', []))
    BlockCutter_2_FacePlaneList   = flatten_tree(getattr(solver, 'BlockCutter_2_FacePlaneList', []))
    BlockCutter_2_Corner0Planes   = flatten_tree(getattr(solver, 'BlockCutter_2_Corner0Planes', []))
    BlockCutter_2_LocalAxesPlane  = getattr(solver, 'BlockCutter_2_LocalAxesPlane', None)
    BlockCutter_2_AxisX           = getattr(solver, 'BlockCutter_2_AxisX', None)
    BlockCutter_2_AxisY           = getattr(solver, 'BlockCutter_2_AxisY', None)
    BlockCutter_2_AxisZ           = getattr(solver, 'BlockCutter_2_AxisZ', None)
    BlockCutter_2_FaceDirTags     = flatten_tree(getattr(solver, 'BlockCutter_2_FaceDirTags', []))
    BlockCutter_2_EdgeDirTags     = flatten_tree(getattr(solver, 'BlockCutter_2_EdgeDirTags', []))
    BlockCutter_2_Corner0EdgeDirs = flatten_tree(getattr(solver, 'BlockCutter_2_Corner0EdgeDirs', []))
    BlockCutter_2_Log             = flatten_tree(getattr(solver, 'BlockCutter_2_Log', []))

    AlignToolToTimber_3_SourceOut_tree    = getattr(solver, 'AlignToolToTimber_3_SourceOut_tree', [])
    AlignToolToTimber_3_TargetOut_tree    = getattr(solver, 'AlignToolToTimber_3_TargetOut_tree', [])
    AlignToolToTimber_3_TransformOut_tree = getattr(solver, 'AlignToolToTimber_3_TransformOut_tree', [])
    AlignToolToTimber_3_MovedGeo_tree     = getattr(solver, 'AlignToolToTimber_3_MovedGeo_tree', [])
    AlignToolToTimber_3_Log               = flatten_tree(getattr(solver, 'AlignToolToTimber_3_Log', []))


    # --- Step6: BlockCutter::3 / AlignToolToTimber::4 输出 ---
    BlockCutter_3_TimberBrep      = flatten_tree(getattr(solver, 'BlockCutter_3_TimberBrep', []))
    BlockCutter_3_FaceList        = flatten_tree(getattr(solver, 'BlockCutter_3_FaceList', []))
    BlockCutter_3_PointList       = flatten_tree(getattr(solver, 'BlockCutter_3_PointList', []))
    BlockCutter_3_EdgeList        = flatten_tree(getattr(solver, 'BlockCutter_3_EdgeList', []))
    BlockCutter_3_CenterPoint     = getattr(solver, 'BlockCutter_3_CenterPoint', None)
    BlockCutter_3_CenterAxisLines = flatten_tree(getattr(solver, 'BlockCutter_3_CenterAxisLines', []))
    BlockCutter_3_EdgeMidPoints   = flatten_tree(getattr(solver, 'BlockCutter_3_EdgeMidPoints', []))
    BlockCutter_3_FacePlaneList   = flatten_tree(getattr(solver, 'BlockCutter_3_FacePlaneList', []))
    BlockCutter_3_Corner0Planes   = flatten_tree(getattr(solver, 'BlockCutter_3_Corner0Planes', []))
    BlockCutter_3_LocalAxesPlane  = getattr(solver, 'BlockCutter_3_LocalAxesPlane', None)
    BlockCutter_3_AxisX           = getattr(solver, 'BlockCutter_3_AxisX', None)
    BlockCutter_3_AxisY           = getattr(solver, 'BlockCutter_3_AxisY', None)
    BlockCutter_3_AxisZ           = getattr(solver, 'BlockCutter_3_AxisZ', None)
    BlockCutter_3_FaceDirTags     = flatten_tree(getattr(solver, 'BlockCutter_3_FaceDirTags', []))
    BlockCutter_3_EdgeDirTags     = flatten_tree(getattr(solver, 'BlockCutter_3_EdgeDirTags', []))
    BlockCutter_3_Corner0EdgeDirs = flatten_tree(getattr(solver, 'BlockCutter_3_Corner0EdgeDirs', []))
    BlockCutter_3_Log             = flatten_tree(getattr(solver, 'BlockCutter_3_Log', []))

    AlignToolToTimber_4_SourceOut_tree    = getattr(solver, 'AlignToolToTimber_4_SourceOut_tree', [])
    AlignToolToTimber_4_TargetOut_tree    = getattr(solver, 'AlignToolToTimber_4_TargetOut_tree', [])
    AlignToolToTimber_4_TransformOut_tree = getattr(solver, 'AlignToolToTimber_4_TransformOut_tree', [])
    AlignToolToTimber_4_MovedGeo_tree     = getattr(solver, 'AlignToolToTimber_4_MovedGeo_tree', [])
    AlignToolToTimber_4_Log               = flatten_tree(getattr(solver, 'AlignToolToTimber_4_Log', []))

    # --- Step7: QiAOTool / PlaneFromLists::2-3 / AlignToolToTimber::5 输出 ---
    QiAOTool_CutTimbers      = flatten_tree(getattr(solver, 'QiAOTool_CutTimbers', []))
    QiAOTool_FailTimbers     = flatten_tree(getattr(solver, 'QiAOTool_FailTimbers', []))
    QiAOTool_TimberBrep      = getattr(solver, 'QiAOTool_TimberBrep', None)
    QiAOTool_EdgeMidPoints   = flatten_tree(getattr(solver, 'QiAOTool_EdgeMidPoints', []))
    QiAOTool_Corner0Planes   = flatten_tree(getattr(solver, 'QiAOTool_Corner0Planes', []))
    QiAOTool_FacePlaneList   = flatten_tree(getattr(solver, 'QiAOTool_FacePlaneList', []))
    QiAOTool_Log             = flatten_tree(getattr(solver, 'QiAOTool_Log', []))

    PlaneFromLists_2_BasePlane   = flatten_tree(getattr(solver, 'PlaneFromLists_2_BasePlane', []))
    PlaneFromLists_2_OriginPoint = flatten_tree(getattr(solver, 'PlaneFromLists_2_OriginPoint', []))
    PlaneFromLists_2_ResultPlane = flatten_tree(getattr(solver, 'PlaneFromLists_2_ResultPlane', []))
    PlaneFromLists_2_Log         = flatten_tree(getattr(solver, 'PlaneFromLists_2_Log', []))

    PlaneFromLists_3_BasePlane   = flatten_tree(getattr(solver, 'PlaneFromLists_3_BasePlane', []))
    PlaneFromLists_3_OriginPoint = flatten_tree(getattr(solver, 'PlaneFromLists_3_OriginPoint', []))
    PlaneFromLists_3_ResultPlane = flatten_tree(getattr(solver, 'PlaneFromLists_3_ResultPlane', []))
    PlaneFromLists_3_Log         = flatten_tree(getattr(solver, 'PlaneFromLists_3_Log', []))

    AlignToolToTimber_5_SourceOut    = flatten_tree(getattr(solver, 'AlignToolToTimber_5_SourceOut', []))
    AlignToolToTimber_5_TargetOut    = flatten_tree(getattr(solver, 'AlignToolToTimber_5_TargetOut', []))
    AlignToolToTimber_5_TransformOut = flatten_tree(getattr(solver, 'AlignToolToTimber_5_TransformOut', []))
    AlignToolToTimber_5_MovedGeo     = flatten_tree(getattr(solver, 'AlignToolToTimber_5_MovedGeo', []))
    AlignToolToTimber_5_Log          = flatten_tree(getattr(solver, 'AlignToolToTimber_5_Log', []))

    # --- Step8: GongYan / PlaneFromLists::4 / AlignToolToTimber::6 输出 ---
    GongYan_SectionCurve  = getattr(solver, 'GongYan_SectionCurve', None)
    GongYan_SectionFace   = getattr(solver, 'GongYan_SectionFace', None)
    GongYan_LeftCurve     = getattr(solver, 'GongYan_LeftCurve', None)
    GongYan_RightCurve    = getattr(solver, 'GongYan_RightCurve', None)
    GongYan_SymmetryAxis  = getattr(solver, 'GongYan_SymmetryAxis', None)
    GongYan_AllPoints     = getattr(solver, 'GongYan_AllPoints', None)
    GongYan_ToolBrep      = getattr(solver, 'GongYan_ToolBrep', None)
    GongYan_SectionPlanes = flatten_tree(getattr(solver, 'GongYan_SectionPlanes', []))
    GongYan_Log           = flatten_tree(getattr(solver, 'GongYan_Log', []))

    PlaneFromLists_4_BasePlane   = flatten_tree(getattr(solver, 'PlaneFromLists_4_BasePlane', []))
    PlaneFromLists_4_OriginPoint = flatten_tree(getattr(solver, 'PlaneFromLists_4_OriginPoint', []))
    PlaneFromLists_4_ResultPlane = flatten_tree(getattr(solver, 'PlaneFromLists_4_ResultPlane', []))
    PlaneFromLists_4_Log         = flatten_tree(getattr(solver, 'PlaneFromLists_4_Log', []))

    AlignToolToTimber_6_SourceOut_tree    = getattr(solver, 'AlignToolToTimber_6_SourceOut_tree', [])
    AlignToolToTimber_6_TargetOut_tree    = getattr(solver, 'AlignToolToTimber_6_TargetOut_tree', [])
    AlignToolToTimber_6_TransformOut_tree = getattr(solver, 'AlignToolToTimber_6_TransformOut_tree', [])
    AlignToolToTimber_6_MovedGeo_tree_raw = getattr(solver, 'AlignToolToTimber_6_MovedGeo_tree', [])
    # 展平：避免输出 System.Collections.Generic.List`1[System.Object] 嵌套
    AlignToolToTimber_6_MovedGeo_tree     = flatten_tree(AlignToolToTimber_6_MovedGeo_tree_raw)
    AlignToolToTimber_6_Log               = flatten_tree(getattr(solver, 'AlignToolToTimber_6_Log', []))




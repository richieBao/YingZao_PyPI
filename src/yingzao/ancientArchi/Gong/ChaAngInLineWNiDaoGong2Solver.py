# -*- coding: utf-8 -*-
"""
ChaAngInLineWNiDaoGong2Solver · Step 1 + Step 2

将用于构建「插昂與泥道栱相列二（ChaAngInLineWNiDaoGong2）」的 GH 连线流程（部分步骤）
合并为一个单独 GhPython 组件脚本。

✅ 当前实现到 Step 2：
Step 1：DBJsonReader（DG_Dou / KeyField=type_code / KeyValue=HuaGong_4PU_INOUT_1ChaoJuantou / Field=ChaAngInLineWNiDaoGong / ExportAll=True）
Step 2：Timber_block_uniform（build_timber_block_uniform）

输入（GH 建议配置 / 名称大小写按你习惯可改，但需与代码一致）
--------------------------------------------------------------
DBPath      : str        Access:item
base_point  : Point3d    Access:item   (木料定位点；None → 原点)
Refresh     : bool       Access:item   (刷新/重读数据库)

输出（面向使用者）
--------------------------------------------------------------
CutTimbers  : list[Geometry]   # 当前阶段：输出主木坯 TimberBrep（若成功）
FailTimbers : list[Geometry]
Log         : list[str]

开发模式输出（developer-friendly，可按需在 GH 里增减输出端）
--------------------------------------------------------------
Value, All, AllDict, DBLog
TimberBrep, FaceList, PointList, EdgeList, CenterPoint, CenterAxisLines,
EdgeMidPoints, FacePlaneList, Corner0Planes, LocalAxesPlane,
AxisX, AxisY, AxisZ, FaceDirTags, EdgeDirTags, Corner0EdgeDirs

注意
--------------------------------------------------------------
1) 参数优先级：组件输入端 > 数据库(All/AllDict) > 默认值。
   - 当前 Step2 的 length/width/height 默认从数据库取；若缺失则回退默认。
   - base_point 始终优先取组件输入端。
2) 参考平面为 GH 约定：
   - XY : X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
   - XZ : X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
   - YZ : X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
   本组件 Step2 默认使用 GH 的 XZ Plane，并把其原点移动到 base_point。
3) 若输出端出现：System.Collections.Generic.List`1[System.Object]
   会对 CutTimbers / FailTimbers / 关键列表输出做递归拍平与 .NET 列表转换。

"""

import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    JuanShaToolBuilder,
    QiAoToolSolver,
    FT_GongYanSection_DouKouTiaoBuilder,
    HuaTouZi,
    GeoAligner_xfm,
    SplitSectionAnalyzer,
    SplitByPlaneAnalyzer,
    RightTrianglePrismBuilder,
    FT_CutTimbersByTools_GH_SolidDifference,
)

import Grasshopper.Kernel.Types as ght
import scriptcontext as sc

try:
    import Grasshopper as gh
    from Grasshopper import DataTree
    from Grasshopper.Kernel.Data import GH_Path
except Exception:
    gh = None
    DataTree = None
    GH_Path = None


# ==============================================================
# 通用工具函数
# ==============================================================

def _is_dotnet_list(x):
    """粗略判断 .NET List/Array 等可枚举对象（避免把字符串当可枚举）。"""
    if x is None:
        return False
    if isinstance(x, (str, bytes)):
        return False
    # RhinoCommon Geometry 多数也可枚举，需排除
    if isinstance(x, rg.GeometryBase):
        return False
    # Python list/tuple
    if isinstance(x, (list, tuple)):
        return True
    # .NET IEnumerable
    try:
        import System
        if isinstance(x, System.Collections.IEnumerable):
            return True
    except Exception:
        pass
    return False


def to_py_list(x):
    """把 .NET IEnumerable 以及 list/tuple 统一转为 Python list；非序列则返回 [x]。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    if _is_dotnet_list(x):
        try:
            return [i for i in x]
        except Exception:
            pass
    return [x]


def flatten_any(x):
    """
    Recursively flatten list/tuple/.NET IEnumerable/DataTree,
    but DO NOT flatten Rhino/GH geometry or goo objects.
    Python 3 version (Rhino 8 / GH Python).
    """
    if x is None:
        return []

    # --- never flatten strings ---
    if isinstance(x, str):
        return [x]

    # --- protect Rhino geometry ---
    try:
        import Rhino.Geometry as rg
        if isinstance(x, (
                rg.GeometryBase,
                rg.Brep, rg.Curve, rg.Surface, rg.Extrusion,
                rg.Mesh, rg.Point3d, rg.Vector3d, rg.Plane,
                rg.Transform, rg.Line, rg.Polyline
        )):
            return [x]
    except:
        pass

    # --- protect GH Transform / Goo ---
    try:
        import Grasshopper.Kernel.Types as ght
        if isinstance(x, ght.GH_Transform):
            return [x]
    except:
        pass

    # --- DataTree ---
    try:
        if hasattr(x, "Branches") and hasattr(x, "BranchCount"):
            out = []
            for i in range(x.BranchCount):
                out.extend(flatten_any(x.Branches[i]))
            return out
    except:
        pass

    # --- python list / tuple ---
    if isinstance(x, (list, tuple)):
        out = []
        for it in x:
            out.extend(flatten_any(it))
        return out

    # --- .NET IEnumerable (but not dict) ---
    try:
        from System.Collections import IEnumerable
        if isinstance(x, dict):
            return [x]
        if isinstance(x, IEnumerable):
            out = []
            for it in x:
                out.extend(flatten_any(it))
            return out
    except:
        pass

    # --- fallback: scalar ---
    return [x]


def _is_gh_datatree(x):
    """Detect GH DataTree (GhPython)."""
    if x is None:
        return False
    return hasattr(x, "Branches") and hasattr(x, "BranchCount")


def _tree_to_branch_items(tree):
    """Return list of (path, items:list) for a GH DataTree."""
    if not _is_gh_datatree(tree):
        return []
    out = []
    try:
        for i in range(tree.BranchCount):
            path = tree.Paths[i] if hasattr(tree, "Paths") else None
            items = [it for it in tree.Branches[i]]
            out.append((path, items))
    except Exception:
        # fallback: try Branches only
        try:
            for i in range(tree.BranchCount):
                out.append((None, [it for it in tree.Branches[i]]))
        except Exception:
            return []
    return out


def _make_tree_from_branches(branch_results):
    """Create a GH DataTree[object] from list of (path, items)."""
    if DataTree is None or GH_Path is None:
        return None
    try:
        dt = DataTree[object]()
        for bi, (path, items) in enumerate(branch_results):
            if path is None:
                path = GH_Path(bi)
            for it in to_py_list(items):
                dt.Add(it, path)
        return dt
    except Exception:
        return None


def _as_bool(v, default=False):
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "y", "t"):
            return True
        if s in ("false", "0", "no", "n", "f"):
            return False
    except Exception:
        pass
    return default


def _as_float(v, default=0.0):
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_seq(x):
    """用于广播：None -> [None]，其他按 to_py_list 规则。"""
    if x is None:
        return [None]
    seq = to_py_list(x)
    return seq if len(seq) > 0 else [None]


def _broadcast_len(*seqs, wrap=True):
    """根据多个序列确定广播后的长度。"""
    lens = [len(_safe_seq(s)) for s in seqs]
    if not lens:
        return 0
    if max(lens) == 1:
        return 1
    if wrap:
        return max(lens)
    return min([l for l in lens if l > 0]) if lens else 0


def _pick(seq, i, wrap=True):
    """按 GH 风格广播取第 i 项。"""
    s = _safe_seq(seq)
    if len(s) == 1:
        return s[0]
    if wrap:
        return s[i % len(s)]
    # wrap=False：由调用方保证 i < len(s)
    return s[i]


def all_to_dict(all_list):
    """All=[('k',v),...] → dict"""
    d = {}
    if all_list is None:
        return d
    for item in to_py_list(all_list):
        if isinstance(item, tuple) and len(item) == 2:
            k, v = item
            d[str(k)] = v
    return d


def make_gh_plane(mode_str, origin_pt=None):
    """将字符串/Plane 输入转换为 GH 约定的参考平面，并允许指定 origin。

    你给出的 GH 参考平面轴向约定：
      - XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
      - XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
      - YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)

    Rhino 的 Plane 构造只需提供 XAxis/YAxis，ZAxis 将由叉乘得到；
    因此这里严格按 GH 的 X/Y 方向构造。
    """

    if origin_pt is None:
        origin_pt = rg.Point3d(0.0, 0.0, 0.0)

    # 1) 直接传入 Rhino Plane / GH_Plane
    try:
        if isinstance(mode_str, rg.Plane):
            pl = rg.Plane(mode_str)
            pl.Origin = origin_pt
            return pl
    except Exception:
        pass

    try:
        if isinstance(mode_str, ght.GH_Plane):
            pl = rg.Plane(mode_str.Value)
            pl.Origin = origin_pt
            return pl
    except Exception:
        pass

    # 2) 字符串模式（允许 "WorldXZ" / "XZ Plane" / "XZ" 等）
    if mode_str is None:
        mode_str = "WorldXZ"
    m = str(mode_str).upper().replace(" ", "").replace("_", "")

    # XY
    if m in ("WORLDXY", "XY", "XYPLANE", "PLANEXY"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin_pt, x, y)

    # YZ
    if m in ("WORLDYZ", "YZ", "YZPLANE", "PLANEYZ"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin_pt, x, y)

    # XZ（默认）
    # X=(1,0,0), Y=(0,0,1) => Z=(0,-1,0)
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin_pt, x, y)


def normalize_point3d(p):
    """把 base_point 统一成 rg.Point3d（None/rg.Point/tuple/带XYZ属性对象）。"""
    if p is None:
        return rg.Point3d(0.0, 0.0, 0.0)
    if isinstance(p, rg.Point3d):
        return p
    if isinstance(p, rg.Point):
        return p.Location
    if isinstance(p, (list, tuple)) and len(p) >= 3:
        try:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        except Exception:
            return rg.Point3d(0.0, 0.0, 0.0)
    try:
        return rg.Point3d(float(p.X), float(p.Y), float(p.Z))
    except Exception:
        return rg.Point3d(0.0, 0.0, 0.0)


def unwrap_gh_transform(x):
    """Unwrap GH_Transform / rg.Transform / None to rg.Transform or None."""
    if x is None:
        return None
    try:
        if isinstance(x, rg.Transform):
            return x
    except Exception:
        pass
    try:
        if isinstance(x, ght.GH_Transform):
            return x.Value
    except Exception:
        pass
    # some goo may expose Value
    try:
        if hasattr(x, "Value"):
            v = x.Value
            if isinstance(v, rg.Transform):
                return v
    except Exception:
        pass
    return None


# ==============================================================
# 主 Solver
# ==============================================================

class ChaAngInLineWNiDaoGong2Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step 2 Timber_block_uniform 输出（与 build_timber_block_uniform 的命名对齐）
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
        # Step 3 卷杀刀具定位与对齐（PlaneFromLists::1 + JuanSha + GeoAligner::1）
        self.PlaneFromLists_1__BasePlane = []
        self.PlaneFromLists_1__OriginPoint = []
        self.PlaneFromLists_1__ResultPlane = []
        self.PlaneFromLists_1__Log = []

        self.JuanSha__ToolBrep = []
        self.JuanSha__HL_Intersection = []
        self.JuanSha__SectionEdges = []
        self.JuanSha__HeightFacePlane = []
        self.JuanSha__LengthFacePlane = []
        self.JuanSha__Log = []

        self.GeoAligner_1__SourceOut = []
        self.GeoAligner_1__TargetOut = []
        self.GeoAligner_1__MovedGeo = []
        self.GeoAligner_1__TransformOut = []

        # Step 4 BlockCutter::1 + ListItem + GeoAligner::2（刀具木料块对齐到主木坯平面）
        self.BlockCutter_1__TimberBrep = None
        self.BlockCutter_1__FaceList = []
        self.BlockCutter_1__PointList = []
        self.BlockCutter_1__EdgeList = []
        self.BlockCutter_1__CenterPoint = None
        self.BlockCutter_1__CenterAxisLines = []
        self.BlockCutter_1__EdgeMidPoints = []
        self.BlockCutter_1__FacePlaneList = []
        self.BlockCutter_1__Corner0Planes = []
        self.BlockCutter_1__LocalAxesPlane = None
        self.BlockCutter_1__AxisX = None
        self.BlockCutter_1__AxisY = None
        self.BlockCutter_1__AxisZ = None
        self.BlockCutter_1__FaceDirTags = []
        self.BlockCutter_1__EdgeDirTags = []
        self.BlockCutter_1__Corner0EdgeDirs = []
        self.BlockCutter_1__Log = []

        self.GeoAligner_2__SourcePlanePicked = []
        self.GeoAligner_2__SourcePlanePicked_Log = []
        self.GeoAligner_2__TargetPlanePicked = []
        self.GeoAligner_2__TargetPlanePicked_Log = []

        self.GeoAligner_2__SourceOut = []
        self.GeoAligner_2__TargetOut = []
        self.GeoAligner_2__MovedGeo = []
        self.GeoAligner_2__TransformOut = []

        # Step 5 QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::3（齐凹刀具对齐）
        self.QiAOTool__CutTimbers = []
        self.QiAOTool__FailTimbers = []
        self.QiAOTool__Log = []
        self.QiAOTool__EdgeMidPoints = []
        self.QiAOTool__Corner0Planes = []

        # QiAOTool 开发输出（如 solver 提供则保存）
        self.QiAOTool__TimberBrep = None
        self.QiAOTool__ToolBrep = None
        self.QiAOTool__AlignedTool = None
        self.QiAOTool__PFL1_ResultPlane = []
        self.QiAOTool__QiAo_FacePlane = None

        # PlaneFromLists::2（主木坯 -> TargetPlane）
        self.PlaneFromLists_2__BasePlane = []
        self.PlaneFromLists_2__OriginPoint = []
        self.PlaneFromLists_2__ResultPlane = []
        self.PlaneFromLists_2__Log = []

        # PlaneFromLists::3（QiAOTool -> SourcePlane）
        self.PlaneFromLists_3__BasePlane = []
        self.PlaneFromLists_3__OriginPoint = []
        self.PlaneFromLists_3__ResultPlane = []
        self.PlaneFromLists_3__Log = []

        # GeoAligner::3
        self.GeoAligner_3__SourceOut = []
        self.GeoAligner_3__TargetOut = []
        self.GeoAligner_3__MovedGeo = []
        self.GeoAligner_3__TransformOut = []

        # Step 6 GongYan + ListItem×2 + GeoAligner::4（栱眼刀具对齐）
        self.GongYan__GongYanSectionCrv = None
        self.GongYan__AnZhiSectionCrv = None
        self.GongYan__SectionCurves = []
        self.GongYan__DebugPts = []
        self.GongYan__SectionSolidBrep = None
        self.GongYan__SectionSolidBrep_Offset = None
        self.GongYan__SectionSolidBreps = []
        self.GongYan__RefPlane = None
        self.GongYan__Log = []

        # Step 6 List Item（从平面列表取 Source/Target）
        self.GeoAligner_4__SourcePlanePicked = []
        self.GeoAligner_4__SourcePlanePicked_Log = []
        self.GeoAligner_4__TargetPlanePicked = []
        self.GeoAligner_4__TargetPlanePicked_Log = []

        # Step 6 GeoAligner::4 输出
        self.GeoAligner_4__SourceOut = []
        self.GeoAligner_4__TargetOut = []
        self.GeoAligner_4__MovedGeo = []
        self.GeoAligner_4__TransformOut = []
        # Step 7 BlockCutter::2 + ListItem×2 + GeoAligner::5（刀具木料块对齐）
        self.BlockCutter_2__TimberBrep = None
        self.BlockCutter_2__FaceList = []
        self.BlockCutter_2__PointList = []
        self.BlockCutter_2__EdgeList = []
        self.BlockCutter_2__CenterPoint = None
        self.BlockCutter_2__CenterAxisLines = []
        self.BlockCutter_2__EdgeMidPoints = []
        self.BlockCutter_2__FacePlaneList = []
        self.BlockCutter_2__Corner0Planes = []
        self.BlockCutter_2__LocalAxesPlane = None
        self.BlockCutter_2__AxisX = None
        self.BlockCutter_2__AxisY = None
        self.BlockCutter_2__AxisZ = None
        self.BlockCutter_2__FaceDirTags = []
        self.BlockCutter_2__EdgeDirTags = []
        self.BlockCutter_2__Corner0EdgeDirs = []
        self.BlockCutter_2__Log = []

        self.GeoAligner_5__SourcePlanePicked = []
        self.GeoAligner_5__SourcePlanePicked_Log = []
        self.GeoAligner_5__TargetPlanePicked = []
        self.GeoAligner_5__TargetPlanePicked_Log = []

        self.GeoAligner_5__SourceOut = []
        self.GeoAligner_5__TargetOut = []
        self.GeoAligner_5__MovedGeo = []
        self.GeoAligner_5__TransformOut = []

        # 最终输出（当前阶段）
        self.CutTimbers = []
        self.FailTimbers = []

    # ---------------------------------------------------------
    # Small coercion helpers (instance wrappers)
    # NOTE: earlier steps used the module-level helpers; Step7
    # was written calling self._as_float, so we provide it here.
    # ---------------------------------------------------------
    def _as_float(self, v, default=0.0):
        """Coerce GH inputs (including GH_Number / strings / None) to float."""
        return _as_float(v, default)

    # ---------- AllDict 取值 ----------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        return self.AllDict[key]

        # ------------------------------------------------------
        # Step 1：读取数据库（All + AllDict）
        # Step 8 ChaAng + ListItem×2 + GeoAligner::6 + CutTimbersByTools_V3::1（插昂刀具对齐并切主木坯）
        self.ChaAng__CutTimbers = []
        self.ChaAng__FailTimbers = []
        self.ChaAng__Log = []
        self.ChaAng__RefPlanes = []
        self.ChaAng__SolidFace_AE = None

        self.GeoAligner_6__SourcePlanePicked = []
        self.GeoAligner_6__SourcePlanePicked_Log = []
        self.GeoAligner_6__TargetPlanePicked = []
        self.GeoAligner_6__TargetPlanePicked_Log = []

        self.GeoAligner_6__SourceOut = None
        self.GeoAligner_6__TargetOut = None
        self.GeoAligner_6__MovedGeo = None
        self.GeoAligner_6__TransformOut = None

        self.CutTimbersByTools_V3_1__CutTimbers = []
        self.CutTimbersByTools_V3_1__CutTimbers_All = []  # 原始切割结果（未筛选最大体积）
        self.CutTimbersByTools_V3_1__FailTimbers = []
        self.CutTimbersByTools_V3_1__Log = []

        # Step 9（绿色分组）：
        # PlaneFromLists::4 + CutTimbersByTools_V3::2 + SplitSectionAnalyzer +
        # RightTrianglePrismBuilder + GeoAligner::7 + CutTimbersByTools_V3::3
        self.CutTimbersByTools_V3_2__CutTimbers = []
        self.CutTimbersByTools_V3_2__FailTimbers = []
        self.CutTimbersByTools_V3_2__Log = []

        self.PlaneFromLists_4__BasePlane = []
        self.PlaneFromLists_4__OriginPoint = []
        self.PlaneFromLists_4__ResultPlane = []
        self.PlaneFromLists_4__Log = []
        # PlaneFromLists::5 + BrepPlane[EX]（用于 SplitSectionAnalyzer 的 Cutter 输入）
        self.PlaneFromLists_5__BasePlane = []
        self.PlaneFromLists_5__OriginPoint = []
        self.PlaneFromLists_5__ResultPlane = []
        self.PlaneFromLists_5__Log = []

        self.BrepPlaneEX__SplitBreps = []
        self.BrepPlaneEX__Areas = []
        self.BrepPlaneEX__MaxAreaBrep = None
        self.BrepPlaneEX__MaxArea = None
        self.BrepPlaneEX__SectionCurves = []
        self.BrepPlaneEX__SectionPoints = []
        self.BrepPlaneEX__Log = []

        self.SplitSectionAnalyzer__SortedVolumes = []
        self.SplitSectionAnalyzer__MaxClosedBrep = None
        self.SplitSectionAnalyzer__SectionFaces = []
        self.SplitSectionAnalyzer__SectionBrep = None
        self.SplitSectionAnalyzer__StableEdgeCurves = []
        self.SplitSectionAnalyzer__StableLineSegments = []
        self.SplitSectionAnalyzer__StableMidPoints = []
        self.SplitSectionAnalyzer__MaxMidPoint = None
        self.SplitSectionAnalyzer__CutterAnglesHV = [None, None]
        self.SplitSectionAnalyzer__PlaneCutterCurves = []
        self.SplitSectionAnalyzer__PlaneCutterMidPoint = None
        self.SplitSectionAnalyzer__Log = []

        self.RightTrianglePrismBuilder__dist = None
        self.RightTrianglePrismBuilder__SectionCurve = None
        self.RightTrianglePrismBuilder__SectionPts = []
        self.RightTrianglePrismBuilder__BrepParts = []
        self.RightTrianglePrismBuilder__OPlanes = []
        self.RightTrianglePrismBuilder__BrepSolid = None
        self.RightTrianglePrismBuilder__Log = []

        self.GeoAligner_7__SourceOut = None
        self.GeoAligner_7__TargetOut = None
        # 供后续 GeoAligner::8 复用（必须与 GeoAligner::7 的 TargetPlane 同一引用来源）
        self.GeoAligner_7__TargetPlane = None
        self.GeoAligner_7__MovedGeo = None
        self.GeoAligner_7__TransformOut = None

        self.CutTimbersByTools_V3_3__CutTimbers = []
        self.CutTimbersByTools_V3_3__FailTimbers = []
        self.CutTimbersByTools_V3_3__Log = []

        # Step X（花头子刀具生成 + 对齐 + 裁切）：
        # HuaTouZi + GeoAligner::8 + CutTimbersByTools_V3::4
        self.HuaTouZi__SolidBrep = None
        self.HuaTouZi__SectionCrv = None
        self.HuaTouZi__SectionCrv_Pos = None
        self.HuaTouZi__SectionCrv_Neg = None
        self.HuaTouZi__LoftBrep = None
        self.HuaTouZi__CapPosBrep = None
        self.HuaTouZi__CapNegBrep = None
        self.HuaTouZi__Log = []
        self.HuaTouZi__Pts_B = None
        self.HuaTouZi__PlaneAtB_X = None

        self.GeoAligner_8__SourceOut = None
        self.GeoAligner_8__TargetOut = None
        self.GeoAligner_8__MovedGeo = None
        self.GeoAligner_8__TransformOut = None

        self.CutTimbersByTools_V3_4__CutTimbers = []
        self.CutTimbersByTools_V3_4__FailTimbers = []
        self.CutTimbersByTools_V3_4__Log = []

    # ------------------------------------------------------

    def _list_item_pick(self, lst, index, wrap=True, label="ListItem", **kwargs):
        """GH 风格 List Item：支持 index 为标量/列表/DataTree，wrap 取模或越界返回 None。
        返回 (picked_list, log_lines)。picked_list 总是 Python list（可能含 None）。
        """
        logs = []

        # 兼容旧参数名 tag
        if 'tag' in kwargs and kwargs.get('tag') is not None:
            label = kwargs.get('tag')

        try:
            lst_py = to_py_list(lst)
            lst_py = flatten_any(lst_py)
        except Exception:
            lst_py = []

        try:
            idx_py = to_py_list(index)
            idx_py = flatten_any(idx_py)
        except Exception:
            idx_py = []

        # 允许 index 为空：直接返回 [None]
        if not idx_py:
            logs.append("[{0}] Empty index; pick None".format(label))
            return [None], logs

        n = len(lst_py)
        if n == 0:
            logs.append("[{0}] Empty list; pick None".format(label))
            return [None for _ in idx_py], logs

        picked = []
        for raw_i in idx_py:
            try:
                ii = int(raw_i)
            except Exception:
                ii = 0

            if wrap:
                jj = ii % n
                picked.append(lst_py[jj])
                logs.append("[{0}] idx={1} -> {2} (wrap, n={3})".format(label, ii, jj, n))
            else:
                if 0 <= ii < n:
                    picked.append(lst_py[ii])
                    logs.append("[{0}] idx={1} OK (n={2})".format(label, ii, n))
                else:
                    picked.append(None)
                    logs.append("[{0}] idx={1} out of range (n={2}); pick None".format(label, ii, n))

        return picked, logs

    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="ChaAngInLineWNiDaoGong2",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv,
            )

            self.Value, self.All, self.DBLog = reader.run()
            self.AllDict = all_to_dict(self.All)

            self.Log.append("[DB] 读取完成：All={} / AllDict={}".format(
                len(to_py_list(self.All)),
                len(self.AllDict)
            ))

            for l in to_py_list(self.DBLog):
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db: {}".format(e))
            self.Value, self.All, self.AllDict, self.DBLog = None, None, {}, [str(e)]

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建 Timber_block_uniform
    # ------------------------------------------------------
    def step2_timber_block_uniform(self):
        # fen 尺寸：目前仅数据库/默认
        def _as_float(v, default):
            try:
                return float(v)
            except Exception:
                return float(default)

        length_fen = _as_float(self.all_get("Timber_block_uniform__length_fen", 32.0), 32.0)
        width_fen = _as_float(self.all_get("Timber_block_uniform__width_fen", 32.0), 32.0)
        height_fen = _as_float(self.all_get("Timber_block_uniform__height_fen", 20.0), 20.0)

        # base_point：输入优先
        bp = normalize_point3d(self.base_point)

        # reference_plane：默认 GH XZ Plane，并把原点移动到 base_point
        # 若数据库未来增加 Timber_block_uniform__reference_plane，可直接替换这里逻辑：
        ref_mode = self.all_get("Timber_block_uniform__reference_plane", "WorldXZ")
        ref_plane = make_gh_plane(ref_mode, origin_pt=bp)

        self.Log.append("[TIMBER] length/width/height = ({},{},{}) fen".format(length_fen, width_fen, height_fen))
        self.Log.append("[TIMBER] base_point = ({:.3f},{:.3f},{:.3f})".format(bp.X, bp.Y, bp.Z))
        self.Log.append("[TIMBER] reference_plane = {} (origin moved to base_point)".format(ref_mode))

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
                ref_plane,
            )

            self.TimberBrep = timber_brep
            self.FaceList = faces
            self.PointList = points
            self.EdgeList = edges
            self.CenterPoint = center_pt
            self.CenterAxisLines = center_axes
            self.EdgeMidPoints = edge_midpts
            self.FacePlaneList = face_planes
            self.Corner0Planes = corner0_planes
            self.LocalAxesPlane = local_axes_plane
            self.AxisX = axis_x
            self.AxisY = axis_y
            self.AxisZ = axis_z
            self.FaceDirTags = face_tags
            self.EdgeDirTags = edge_tags
            self.Corner0EdgeDirs = corner0_dirs

            self.Log.append("[TIMBER] build_timber_block_uniform OK")
            for l in to_py_list(log_lines):
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step2_timber_block_uniform: {}".format(e))

        # 当前阶段：把主木坯作为 CutTimbers 输出
        if self.TimberBrep is not None:
            self.CutTimbers = [self.TimberBrep]
        else:
            self.CutTimbers = []
        self.FailTimbers = []

        return self

    # ------------------------------------------------------
    # Run
    # ------------------------------------------------------
    # ------------------------------------------------------
    # Step 3：卷杀刀具定位与对齐（PlaneFromLists::1 + JuanSha + GeoAligner::1）
    # ------------------------------------------------------
    def step3_juan_sha_and_align(self):
        """
        Step 3:
            3.1 PlaneFromLists::1（FTPlaneFromLists.build_plane）
            3.2 JuanSha（JuanShaToolBuilder.build）
            3.3 GeoAligner::1（GeoAligner_xfm.align）
        """
        try:
            # ---------------------------
            # 3.1 PlaneFromLists::1
            # ---------------------------
            idx_origin = self.all_get("PlaneFromLists_1__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_1__IndexPlane", None)
            wrap = _as_bool(self.all_get("PlaneFromLists_1__Wrap", True), True)

            builder = FTPlaneFromLists(wrap=wrap)
            bp, op, rp, plog = builder.build_plane(
                self.EdgeMidPoints,
                self.Corner0Planes,
                idx_origin,
                idx_plane
            )

            self.PlaneFromLists_1__BasePlane = flatten_any(bp)
            self.PlaneFromLists_1__OriginPoint = flatten_any(op)
            self.PlaneFromLists_1__ResultPlane = flatten_any(rp)
            self.PlaneFromLists_1__Log = to_py_list(plog)

            self.Log.append("[STEP3] PlaneFromLists::1 OK (wrap={})".format(wrap))

        except Exception as e:
            self.Log.append("[ERROR] Step3.1 PlaneFromLists::1: {}".format(e))
            self.PlaneFromLists_1__BasePlane = []
            self.PlaneFromLists_1__OriginPoint = []
            self.PlaneFromLists_1__ResultPlane = []
            self.PlaneFromLists_1__Log = ["错误: {}".format(e)]

        # ---------------------------
        # 3.2 JuanSha（按 SectionPlane 广播）
        # ---------------------------
        try:
            h_fen = self.all_get("JuanSha__HeightFen", None)
            l_fen = self.all_get("JuanSha__LengthFen", None)
            div_c = self.all_get("JuanSha__DivCount", None)
            t_fen = self.all_get("JuanSha__ThicknessFen", None)

            # PositionPoint：输入端 base_point 优先
            pos_pt = normalize_point3d(self.base_point)

            section_planes = self.PlaneFromLists_1__ResultPlane
            section_planes = _safe_seq(section_planes)

            tool_list = []
            sec_edges_list = []
            hl_list = []
            hface_list = []
            lface_list = []
            jlog_all = []

            for i, sp in enumerate(section_planes):
                try:
                    js_builder = JuanShaToolBuilder(
                        height_fen=h_fen,
                        length_fen=l_fen,
                        thickness_fen=t_fen,
                        div_count=div_c,
                        section_plane=sp,
                        position_point=pos_pt
                    )
                    ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, jlog = js_builder.build()

                    tool_list.append(ToolBrep)
                    sec_edges_list.append(SectionEdges)
                    hl_list.append(HL_Intersection)
                    hface_list.append(HeightFacePlane)
                    lface_list.append(LengthFacePlane)
                    if jlog is not None:
                        jlog_all.extend(to_py_list(jlog))
                except Exception as e_one:
                    self.Log.append("[ERROR] Step3.2 JuanSha item[{}]: {}".format(i, e_one))
                    tool_list.append(None)
                    sec_edges_list.append(None)
                    hl_list.append(None)
                    hface_list.append(None)
                    lface_list.append(None)

            self.JuanSha__ToolBrep = flatten_any(tool_list)
            self.JuanSha__SectionEdges = flatten_any(sec_edges_list)
            self.JuanSha__HL_Intersection = flatten_any(hl_list)
            self.JuanSha__HeightFacePlane = flatten_any(hface_list)
            self.JuanSha__LengthFacePlane = flatten_any(lface_list)
            self.JuanSha__Log = jlog_all

            self.Log.append("[STEP3] JuanSha OK (count={})".format(len(_safe_seq(section_planes))))

        except Exception as e:
            self.Log.append("[ERROR] Step3.2 JuanSha: {}".format(e))
            self.JuanSha__ToolBrep = []
            self.JuanSha__SectionEdges = []
            self.JuanSha__HL_Intersection = []
            self.JuanSha__HeightFacePlane = []
            self.JuanSha__LengthFacePlane = []
            self.JuanSha__Log = ["错误: {}".format(e)]

        # ---------------------------
        # 3.3 GeoAligner::1（按 GH 广播）
        # ---------------------------
        try:
            geo = self.JuanSha__ToolBrep
            source_plane = self.JuanSha__HeightFacePlane
            target_plane = self.PlaneFromLists_1__ResultPlane

            rotate_deg = self.all_get("GeoAligner_1__RotateDeg", 0)
            flip_x = _as_bool(self.all_get("GeoAligner_1__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_1__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_1__FlipZ", False), False)
            move_x = self.all_get("GeoAligner_1__MoveX", 0)
            move_y = self.all_get("GeoAligner_1__MoveY", 0)
            move_z = self.all_get("GeoAligner_1__MoveZ", 0)

            # 广播长度
            wrap = True  # GeoAligner 本身未提供 Wrap 参数，此处按 GH 常见 wrap 逻辑处理
            n = _broadcast_len(geo, source_plane, target_plane, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y,
                               move_z, wrap=wrap)

            src_outs = []
            tgt_outs = []
            xforms = []
            moved = []

            for i in range(n):
                g = _pick(geo, i, wrap=wrap)
                sp = _pick(source_plane, i, wrap=wrap)
                tp = _pick(target_plane, i, wrap=wrap)

                rd = _pick(rotate_deg, i, wrap=wrap)
                fx = _pick(flip_x, i, wrap=wrap)
                fy = _pick(flip_y, i, wrap=wrap)
                fz = _pick(flip_z, i, wrap=wrap)

                mx = _pick(move_x, i, wrap=wrap)
                my = _pick(move_y, i, wrap=wrap)
                mz = _pick(move_z, i, wrap=wrap)

                try:
                    so, to, xf, mg = GeoAligner_xfm.align(
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
                    src_outs.append(so)
                    tgt_outs.append(to)
                    xforms.append(ght.GH_Transform(xf) if xf is not None else None)
                    moved.append(mg)
                except Exception as e_one:
                    self.Log.append("[ERROR] Step3.3 GeoAligner item[{}]: {}".format(i, e_one))
                    src_outs.append(None)
                    tgt_outs.append(None)
                    xforms.append(None)
                    moved.append(None)

            self.GeoAligner_1__SourceOut = flatten_any(src_outs)
            self.GeoAligner_1__TargetOut = flatten_any(tgt_outs)
            self.GeoAligner_1__TransformOut = flatten_any(xforms)
            self.GeoAligner_1__MovedGeo = flatten_any(moved)

            self.Log.append("[STEP3] GeoAligner::1 OK (count={})".format(n))

        except Exception as e:
            self.Log.append("[ERROR] Step3.3 GeoAligner::1: {}".format(e))
            self.GeoAligner_1__SourceOut = []
            self.GeoAligner_1__TargetOut = []
            self.GeoAligner_1__TransformOut = []
            self.GeoAligner_1__MovedGeo = []

        # 关键输出拍平（避免 System.Collections...）
        self.PlaneFromLists_1__ResultPlane = flatten_any(self.PlaneFromLists_1__ResultPlane)
        self.JuanSha__ToolBrep = flatten_any(self.JuanSha__ToolBrep)
        self.GeoAligner_1__MovedGeo = flatten_any(self.GeoAligner_1__MovedGeo)

    # ------------------------------------------------------
    # Step 4：BlockCutter::1 + List Item + GeoAligner::2
    # ------------------------------------------------------
    def step4_blockcutter_and_geoaligner2(self):
        """
        Step 4:
            4.1 BlockCutter::1（build_timber_block_uniform 生成刀具木料块）
            4.2 List Item（从两个 FacePlaneList 取 SourcePlane / TargetPlane）
            4.3 GeoAligner::2（对齐刀具木坯到主木坯目标平面）
        """

        # ---------------------------
        # 4.1 BlockCutter::1
        # ---------------------------
        try:
            def _as_float_seq(v, default):
                """Parse scalar/list (or JSON-like string list) into list[float]."""
                if v is None:
                    return [float(default)]
                # already a list/tuple
                if isinstance(v, (list, tuple)):
                    out = []
                    for x in v:
                        try:
                            out.append(float(x))
                        except Exception:
                            out.append(float(default))
                    return out if out else [float(default)]
                # string: maybe "[1,2,3]" or "10"
                if isinstance(v, str):
                    s = v.strip()
                    if s.startswith('[') and s.endswith(']'):
                        try:
                            import json
                            arr = json.loads(s)
                            if isinstance(arr, list):
                                return [float(x) for x in arr]
                        except Exception:
                            pass
                    try:
                        return [float(s)]
                    except Exception:
                        return [float(default)]
                # scalar
                try:
                    return [float(v)]
                except Exception:
                    return [float(default)]

            length_seq = _as_float_seq(self.all_get("BlockCutter_1__length_fen", 32.0), 32.0)
            width_seq = _as_float_seq(self.all_get("BlockCutter_1__width_fen", 32.0), 32.0)
            height_seq = _as_float_seq(self.all_get("BlockCutter_1__height_fen", 20.0), 20.0)

            # base_point：输入端优先（若 None → 原点）
            bp = normalize_point3d(self.base_point)

            # reference_plane：默认 WorldXZ（按 GH 约定，并把原点移动到 base_point）
            ref_mode = self.all_get("BlockCutter_1__reference_plane", "WorldXZ")
            ref_plane = make_gh_plane(ref_mode, origin_pt=bp)

            # 多值尺寸 → GH 风格广播对齐（wrap=True）
            n = _broadcast_len(length_seq, width_seq, height_seq, wrap=True)
            self.Log.append("[BLOCKCUTTER1] broadcast count = {}".format(n))
            self.Log.append("[BLOCKCUTTER1] base_point = ({:.3f},{:.3f},{:.3f})".format(bp.X, bp.Y, bp.Z))
            self.Log.append("[BLOCKCUTTER1] reference_plane = {} (origin moved to base_point)".format(ref_mode))

            timber_breps = []
            faces_all = []
            points_all = []
            edges_all = []
            center_pts = []
            center_axes_all = []
            edge_midpts_all = []
            face_planes_all = []
            corner0_planes_all = []
            local_axes_planes = []
            axis_x_all = []
            axis_y_all = []
            axis_z_all = []
            face_tags_all = []
            edge_tags_all = []
            corner0_dirs_all = []
            log_lines_all = []

            for i in range(n):
                lf = _pick(length_seq, i, wrap=True)
                wf = _pick(width_seq, i, wrap=True)
                hf = _pick(height_seq, i, wrap=True)

                self.Log.append("[BLOCKCUTTER1] item[{}] (L,W,H)=({},{},{}) fen".format(i, lf, wf, hf))

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
                    lf,
                    wf,
                    hf,
                    bp,
                    ref_plane,
                )

                timber_breps.append(timber_brep)
                faces_all.append(faces)
                points_all.append(points)
                edges_all.append(edges)
                center_pts.append(center_pt)
                center_axes_all.append(center_axes)
                edge_midpts_all.append(edge_midpts)
                face_planes_all.append(face_planes)
                corner0_planes_all.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_all.append(axis_x)
                axis_y_all.append(axis_y)
                axis_z_all.append(axis_z)
                face_tags_all.append(face_tags)
                edge_tags_all.append(edge_tags)
                corner0_dirs_all.append(corner0_dirs)
                log_lines_all.append(to_py_list(log_lines))

            # 输出：TimberBrep 为 list（可能多个）
            self.BlockCutter_1__TimberBrep = flatten_any(timber_breps)
            self.BlockCutter_1__FaceList = faces_all
            self.BlockCutter_1__PointList = points_all
            self.BlockCutter_1__EdgeList = edges_all
            self.BlockCutter_1__CenterPoint = center_pts
            self.BlockCutter_1__CenterAxisLines = center_axes_all
            self.BlockCutter_1__EdgeMidPoints = edge_midpts_all
            self.BlockCutter_1__FacePlaneList = face_planes_all
            self.BlockCutter_1__Corner0Planes = corner0_planes_all
            self.BlockCutter_1__LocalAxesPlane = local_axes_planes
            self.BlockCutter_1__AxisX = axis_x_all
            self.BlockCutter_1__AxisY = axis_y_all
            self.BlockCutter_1__AxisZ = axis_z_all
            self.BlockCutter_1__FaceDirTags = face_tags_all
            self.BlockCutter_1__EdgeDirTags = edge_tags_all
            self.BlockCutter_1__Corner0EdgeDirs = corner0_dirs_all
            self.BlockCutter_1__Log = log_lines_all

            self.Log.append("[BLOCKCUTTER1] build_timber_block_uniform OK (count={})".format(n))

        except Exception as e:
            self.Log.append("[ERROR] Step4.1 BlockCutter::1: {}".format(e))
            self.BlockCutter_1__TimberBrep = []
            self.BlockCutter_1__FaceList = []
            self.BlockCutter_1__PointList = []
            self.BlockCutter_1__EdgeList = []
            self.BlockCutter_1__CenterPoint = None
            self.BlockCutter_1__CenterAxisLines = []
            self.BlockCutter_1__EdgeMidPoints = []
            self.BlockCutter_1__FacePlaneList = []
            self.BlockCutter_1__Corner0Planes = []
            self.BlockCutter_1__LocalAxesPlane = None
            self.BlockCutter_1__AxisX = None
            self.BlockCutter_1__AxisY = None
            self.BlockCutter_1__AxisZ = None
            self.BlockCutter_1__FaceDirTags = []
            self.BlockCutter_1__EdgeDirTags = []
            self.BlockCutter_1__Corner0EdgeDirs = []
            self.BlockCutter_1__Log = ["错误: {}".format(e)]

        # 关键列表拍平（避免 System.Collections...）
        # 关键列表拍平：仅在 FacePlaneList 为一维 list[Plane] 时拍平（避免破坏多木料块的 list[list[Plane]] 结构）
        try:
            if isinstance(self.BlockCutter_1__FacePlaneList, list) and self.BlockCutter_1__FacePlaneList and isinstance(
                    self.BlockCutter_1__FacePlaneList[0], rg.Plane):
                self.BlockCutter_1__FacePlaneList = flatten_any(self.BlockCutter_1__FacePlaneList)
        except Exception:
            pass

        # ---------------------------
        # 4.2 List Item（SourcePlane / TargetPlane）
        # ---------------------------
        def _list_item_pick(src_list, idx_in, wrap=True, tag="LISTITEM"):
            planes = flatten_any(src_list)
            idxs = flatten_any(idx_in)
            if idxs is None or len(idxs) == 0:
                idxs = [0]

            # 广播规则（按你的约定：Index 单值 → 取 1 项；Index 多值 → 逐项取）
            n = len(idxs) if len(idxs) > 1 else 1

            picked = []
            logs = []

            if planes is None or len(planes) == 0:
                for i in range(n):
                    picked.append(None)
                    logs.append("[{}] Empty list; pick None".format(tag))
                return picked, logs

            for i in range(n):
                ii = idxs[i] if len(idxs) > 1 else idxs[0]
                try:
                    ii_int = int(ii)
                except Exception:
                    ii_int = 0
                    logs.append("[{}] Invalid index '{}', fallback 0".format(tag, ii))

                # 允许负索引
                if ii_int < 0:
                    ii_int = len(planes) + ii_int

                if wrap:
                    jj = ii_int % len(planes)
                    picked.append(planes[jj])
                    if ii_int != jj:
                        logs.append("[{}] Wrap index {} -> {}".format(tag, ii_int, jj))
                else:
                    if 0 <= ii_int < len(planes):
                        picked.append(planes[ii_int])
                    else:
                        picked.append(None)
                        logs.append(
                            "[{}] Index out of range: {} (len={}), output None".format(tag, ii_int, len(planes)))

            return picked, logs

        try:
            src_idx = self.all_get("GeoAligner_2__SourcePlane", None)
            src_wrap = _as_bool(self.all_get("GeoAligner_2__SourceWrap", True), True)

            # BlockCutter_1__FacePlaneList 可能为：
            #   - 单个木料块: list[Plane]
            #   - 多个木料块: list[list[Plane]]
            faceplane_lists = self.BlockCutter_1__FacePlaneList
            idxs = flatten_any(to_py_list(src_idx)) if src_idx is not None else [0]
            n = _broadcast_len(faceplane_lists, idxs, wrap=True)

            picked_src = []
            log_src = []
            for i in range(n):
                planes_i = _pick(faceplane_lists, i, wrap=True)
                planes_flat = flatten_any(planes_i)
                if not planes_flat:
                    picked_src.append(None)
                    log_src.append("[LISTITEM(Source)] Empty FacePlaneList at item[{}]".format(i))
                    continue
                raw_ii = _pick(idxs, i, wrap=True)
                try:
                    ii_int = int(raw_ii) if raw_ii is not None else 0
                except Exception:
                    ii_int = 0
                    log_src.append("[LISTITEM(Source)] Invalid index '{}', fallback 0".format(raw_ii))

                if ii_int < 0:
                    ii_int = len(planes_flat) + ii_int

                if src_wrap:
                    jj = ii_int % len(planes_flat)
                    picked_src.append(planes_flat[jj])
                    if ii_int != jj:
                        log_src.append("[LISTITEM(Source)] Wrap index {} -> {}".format(ii_int, jj))
                else:
                    if 0 <= ii_int < len(planes_flat):
                        picked_src.append(planes_flat[ii_int])
                    else:
                        picked_src.append(None)
                        log_src.append("[LISTITEM(Source)] Index out of range: {} (len={}), output None".format(ii_int,
                                                                                                                len(planes_flat)))

            self.GeoAligner_2__SourcePlanePicked = flatten_any(picked_src)
            self.GeoAligner_2__SourcePlanePicked_Log = to_py_list(log_src)

            self.Log.append(
                "[STEP4] ListItem(Source) OK (wrap={}, count={})".format(src_wrap, len(to_py_list(picked_src))))
            for l in to_py_list(log_src):
                self.Log.append("[STEP4] " + str(l))


        except Exception as e:
            self.Log.append("[ERROR] Step4.2 ListItem(Source): {}".format(e))
            self.GeoAligner_2__SourcePlanePicked = []
            self.GeoAligner_2__SourcePlanePicked_Log = ["错误: {}".format(e)]

        try:
            tgt_idx = self.all_get("GeoAligner_2__TargetPlane", None)
            tgt_wrap = _as_bool(self.all_get("GeoAligner_2__TargetWrap", True), True)

            picked_tgt, log_tgt = _list_item_pick(
                self.FacePlaneList,  # Step2 主木坯 FacePlaneList
                tgt_idx,
                wrap=tgt_wrap,
                tag="LISTITEM(Target)"
            )

            self.GeoAligner_2__TargetPlanePicked = flatten_any(picked_tgt)
            self.GeoAligner_2__TargetPlanePicked_Log = to_py_list(log_tgt)

            self.Log.append(
                "[STEP4] ListItem(Target) OK (wrap={}, count={})".format(tgt_wrap, len(to_py_list(picked_tgt))))
            for l in to_py_list(log_tgt):
                self.Log.append("[STEP4] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] Step4.2 ListItem(Target): {}".format(e))
            self.GeoAligner_2__TargetPlanePicked = []
            self.GeoAligner_2__TargetPlanePicked_Log = ["错误: {}".format(e)]

        # ---------------------------
        # 4.3 GeoAligner::2（按 GH 广播）
        # ---------------------------
        try:
            geo = self.BlockCutter_1__TimberBrep
            source_plane = self.GeoAligner_2__SourcePlanePicked
            target_plane = self.GeoAligner_2__TargetPlanePicked

            rotate_deg = self.all_get("GeoAligner_2__RotateDeg", 0)
            flip_x = _as_bool(self.all_get("GeoAligner_2__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_2__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_2__FlipZ", False), False)
            move_x = self.all_get("GeoAligner_2__MoveX", 0)
            move_y = self.all_get("GeoAligner_2__MoveY", 0)
            move_z = self.all_get("GeoAligner_2__MoveZ", 0)

            # 广播长度（与 Step3 保持一致：wrap=True）
            wrap = True
            n = _broadcast_len(geo, source_plane, target_plane, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y,
                               move_z, wrap=wrap)

            src_outs = []
            tgt_outs = []
            xforms = []
            moved = []

            for i in range(n):
                g = _pick(geo, i, wrap=wrap)
                sp = _pick(source_plane, i, wrap=wrap)
                tp = _pick(target_plane, i, wrap=wrap)

                rd = _pick(rotate_deg, i, wrap=wrap)
                fx = _pick(flip_x, i, wrap=wrap)
                fy = _pick(flip_y, i, wrap=wrap)
                fz = _pick(flip_z, i, wrap=wrap)

                mx = _pick(move_x, i, wrap=wrap)
                my = _pick(move_y, i, wrap=wrap)
                mz = _pick(move_z, i, wrap=wrap)

                try:
                    so, to, xf, mg = GeoAligner_xfm.align(
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
                    src_outs.append(so)
                    tgt_outs.append(to)
                    xforms.append(ght.GH_Transform(xf) if xf is not None else None)
                    moved.append(mg)
                except Exception as e_one:
                    self.Log.append("[ERROR] Step4.3 GeoAligner::2 item[{}]: {}".format(i, e_one))
                    src_outs.append(None)
                    tgt_outs.append(None)
                    xforms.append(None)
                    moved.append(None)

            self.GeoAligner_2__SourceOut = flatten_any(src_outs)
            self.GeoAligner_2__TargetOut = flatten_any(tgt_outs)
            self.GeoAligner_2__TransformOut = flatten_any(xforms)
            self.GeoAligner_2__MovedGeo = flatten_any(moved)

            self.Log.append("[GA2] GeoAligner::2 OK (count={})".format(n))

        except Exception as e:
            self.Log.append("[ERROR] Step4.3 GeoAligner::2: {}".format(e))
            self.GeoAligner_2__SourceOut = []
            self.GeoAligner_2__TargetOut = []
            self.GeoAligner_2__TransformOut = []
            self.GeoAligner_2__MovedGeo = []

        # 关键输出拍平（避免 System.Collections...）
        self.GeoAligner_2__SourcePlanePicked = flatten_any(self.GeoAligner_2__SourcePlanePicked)
        self.GeoAligner_2__TargetPlanePicked = flatten_any(self.GeoAligner_2__TargetPlanePicked)
        self.GeoAligner_2__MovedGeo = flatten_any(self.GeoAligner_2__MovedGeo)
        self.GeoAligner_2__TransformOut = flatten_any(self.GeoAligner_2__TransformOut)

        return self

    # ------------------------------------------------------
    # Step 5：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::3
    # ------------------------------------------------------
    def step5_qiaotool_pfl2_pfl3_geoaligner3(self):
        """
        Step 5（对应附图绿色组）:
            5.1 QiAOTool（QiAoToolSolver 生成齐凹刀具几何）
            5.2 PlaneFromLists::2（主木坯 -> TargetPlane）
            5.3 PlaneFromLists::3（QiAOTool -> SourcePlane）
            5.4 GeoAligner::3（对齐 QiAOTool 几何到主木坯平面）
        """

        # ---------------------------
        # 5.1 QiAOTool
        # ---------------------------
        try:
            bp = normalize_point3d(self.base_point)

            params = {
                "length_fen": _as_float(self.all_get("QiAOTool__length_fen", 41.0), 41.0),
                "width_fen": _as_float(self.all_get("QiAOTool__width_fen", 16.0), 16.0),
                "height_fen": _as_float(self.all_get("QiAOTool__height_fen", 10.0), 10.0),
                "base_point": bp,

                # planes（按 QiAOTool 组件逻辑：mode + origin）
                "timber_ref_plane": make_gh_plane(
                    self.all_get("QiAOTool__timber_ref_plane_mode", self.all_get("QiAOTool__timber_ref_plane", "XZ")),
                    origin_pt=bp
                ),
                "qi_ref_plane": make_gh_plane(
                    self.all_get("QiAOTool__qi_ref_plane_mode", self.all_get("QiAOTool__qi_ref_plane", "XZ")),
                    origin_pt=bp
                ),

                # qiao params
                "qi_height": _as_float(self.all_get("QiAOTool__qi_height", 4.0), 4.0),
                "sha_width": _as_float(self.all_get("QiAOTool__sha_width", 2.0), 2.0),
                "qi_offset_fen": _as_float(self.all_get("QiAOTool__qi_offset_fen", 0.5), 0.5),
                "extrude_length": _as_float(self.all_get("QiAOTool__extrude_length", 28.0), 28.0),
                "extrude_positive": _as_bool(self.all_get("QiAOTool__extrude_positive", False), False),
            }

            solver = QiAoToolSolver(ghenv=self.ghenv)
            solver.run(params)

            # 核心输出
            self.QiAOTool__CutTimbers = flatten_any(solver.CutTimbers)
            self.QiAOTool__FailTimbers = flatten_any(getattr(solver, "FailTimbers", []))
            self.QiAOTool__Log = to_py_list(getattr(solver, "Log", []))

            # 本步骤取面所需
            self.QiAOTool__EdgeMidPoints = flatten_any(getattr(solver, "EdgeMidPoints", []))
            self.QiAOTool__Corner0Planes = flatten_any(getattr(solver, "Corner0Planes", []))

            # 开发输出（若存在）
            self.QiAOTool__TimberBrep = getattr(solver, "TimberBrep", None)
            self.QiAOTool__ToolBrep = getattr(solver, "ToolBrep", None)
            self.QiAOTool__AlignedTool = getattr(solver, "AlignedTool", None)
            self.QiAOTool__PFL1_ResultPlane = flatten_any(getattr(solver, "PFL1_ResultPlane", []))
            self.QiAOTool__QiAo_FacePlane = getattr(solver, "QiAo_FacePlane", None)

            self.Log.append("[QIAOTOOL] OK (CutTimbers={})".format(len(to_py_list(self.QiAOTool__CutTimbers))))
            for l in self.QiAOTool__Log:
                self.Log.append("[QIAOTOOL] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] Step5.1 QiAOTool: {}".format(e))
            self.QiAOTool__CutTimbers = []
            self.QiAOTool__FailTimbers = []
            self.QiAOTool__Log = ["错误: {}".format(e)]
            self.QiAOTool__EdgeMidPoints = []
            self.QiAOTool__Corner0Planes = []
            self.QiAOTool__TimberBrep = None
            self.QiAOTool__ToolBrep = None
            self.QiAOTool__AlignedTool = None
            self.QiAOTool__PFL1_ResultPlane = []
            self.QiAOTool__QiAo_FacePlane = None

        # ---------------------------
        # 5.2 / 5.3 PlaneFromLists 广播封装
        # ---------------------------
        def _pfl_broadcast_build(tag, origin_points, base_planes, idx_origin, idx_plane, wrap=True):
            op_list = flatten_any(origin_points)
            bp_list = flatten_any(base_planes)

            idx_o = flatten_any(idx_origin)
            idx_p = flatten_any(idx_plane)

            if idx_o is None or len(idx_o) == 0:
                idx_o = [0]
            if idx_p is None or len(idx_p) == 0:
                idx_p = [0]

            n = _broadcast_len(idx_o, idx_p, wrap=wrap)

            builder = FTPlaneFromLists(wrap=wrap)

            base_out = []
            orig_out = []
            res_out = []
            logs = []

            if (op_list is None or len(op_list) == 0) or (bp_list is None or len(bp_list) == 0):
                for i in range(n):
                    base_out.append(None)
                    orig_out.append(None)
                    res_out.append(None)
                    logs.append("[{}] Empty OriginPoints/BasePlanes".format(tag))
                return base_out, orig_out, res_out, logs

            for i in range(n):
                io = _pick(idx_o, i, wrap=wrap)
                ip = _pick(idx_p, i, wrap=wrap)
                try:
                    io = int(io)
                except Exception:
                    logs.append("[{}] Invalid IndexOrigin '{}', fallback 0".format(tag, io))
                    io = 0
                try:
                    ip = int(ip)
                except Exception:
                    logs.append("[{}] Invalid IndexPlane '{}', fallback 0".format(tag, ip))
                    ip = 0

                try:
                    bpo, opo, rpo, plog = builder.build_plane(op_list, bp_list, io, ip)
                    base_out.append(bpo)
                    orig_out.append(opo)
                    res_out.append(rpo)
                    if plog is not None:
                        logs.extend(to_py_list(plog))
                except Exception as e_one:
                    logs.append("[{}] build_plane item[{}] error: {}".format(tag, i, e_one))
                    base_out.append(None)
                    orig_out.append(None)
                    res_out.append(None)

            return base_out, orig_out, res_out, logs

        # ---------------------------
        # 5.2 PlaneFromLists::2（主木坯 -> TargetPlane）
        # ---------------------------
        try:
            idx_origin = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
            idx_plane = self.all_get("PlaneFromLists_2__IndexPlane", 0)
            wrap = _as_bool(self.all_get("PlaneFromLists_2__Wrap", True), True)

            bp_out, op_out, rp_out, plog = _pfl_broadcast_build(
                "PFL2",
                self.EdgeMidPoints,
                self.Corner0Planes,
                idx_origin,
                idx_plane,
                wrap=wrap
            )

            self.PlaneFromLists_2__BasePlane = flatten_any(bp_out)
            self.PlaneFromLists_2__OriginPoint = flatten_any(op_out)
            self.PlaneFromLists_2__ResultPlane = flatten_any(rp_out)
            self.PlaneFromLists_2__Log = to_py_list(plog)

            self.Log.append(
                "[PFL2] OK (wrap={}, count={})".format(wrap, len(_safe_seq(self.PlaneFromLists_2__ResultPlane))))
            for l in self.PlaneFromLists_2__Log:
                self.Log.append("[PFL2] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] Step5.2 PlaneFromLists::2: {}".format(e))
            self.PlaneFromLists_2__BasePlane = []
            self.PlaneFromLists_2__OriginPoint = []
            self.PlaneFromLists_2__ResultPlane = []
            self.PlaneFromLists_2__Log = ["错误: {}".format(e)]

        # ---------------------------
        # 5.3 PlaneFromLists::3（QiAOTool -> SourcePlane）
        # ---------------------------
        try:
            idx_origin = self.all_get("PlaneFromLists_3__IndexOrigin", 0)
            idx_plane = self.all_get("PlaneFromLists_3__IndexPlane", 0)
            wrap = _as_bool(self.all_get("PlaneFromLists_3__Wrap", True), True)

            bp_out, op_out, rp_out, plog = _pfl_broadcast_build(
                "PFL3",
                self.QiAOTool__EdgeMidPoints,
                self.QiAOTool__Corner0Planes,
                idx_origin,
                idx_plane,
                wrap=wrap
            )

            self.PlaneFromLists_3__BasePlane = flatten_any(bp_out)
            self.PlaneFromLists_3__OriginPoint = flatten_any(op_out)
            self.PlaneFromLists_3__ResultPlane = flatten_any(rp_out)
            self.PlaneFromLists_3__Log = to_py_list(plog)

            self.Log.append(
                "[PFL3] OK (wrap={}, count={})".format(wrap, len(_safe_seq(self.PlaneFromLists_3__ResultPlane))))
            for l in self.PlaneFromLists_3__Log:
                self.Log.append("[PFL3] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] Step5.3 PlaneFromLists::3: {}".format(e))
            self.PlaneFromLists_3__BasePlane = []
            self.PlaneFromLists_3__OriginPoint = []
            self.PlaneFromLists_3__ResultPlane = []
            self.PlaneFromLists_3__Log = ["错误: {}".format(e)]

        # ---------------------------
        # 5.4 GeoAligner::3（按 GH 广播）
        # ---------------------------
        try:
            geo = self.QiAOTool__CutTimbers
            source_plane = self.PlaneFromLists_3__ResultPlane
            target_plane = self.PlaneFromLists_2__ResultPlane

            rotate_deg = self.all_get("GeoAligner_3__RotateDeg", 0)
            flip_x = _as_bool(self.all_get("GeoAligner_3__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_3__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_3__FlipZ", False), False)
            move_x = self.all_get("GeoAligner_3__MoveX", 0)
            move_y = self.all_get("GeoAligner_3__MoveY", 0)
            move_z = self.all_get("GeoAligner_3__MoveZ", 0)

            wrap = _as_bool(self.all_get("GeoAligner_3__Wrap", True), True)
            n = _broadcast_len(geo, source_plane, target_plane, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y,
                               move_z, wrap=wrap)

            src_outs = []
            tgt_outs = []
            xforms = []
            moved = []

            for i in range(n):
                g = _pick(geo, i, wrap=wrap)
                sp = _pick(source_plane, i, wrap=wrap)
                tp = _pick(target_plane, i, wrap=wrap)

                rd = _pick(rotate_deg, i, wrap=wrap)
                fx = _pick(flip_x, i, wrap=wrap)
                fy = _pick(flip_y, i, wrap=wrap)
                fz = _pick(flip_z, i, wrap=wrap)

                mx = _pick(move_x, i, wrap=wrap)
                my = _pick(move_y, i, wrap=wrap)
                mz = _pick(move_z, i, wrap=wrap)

                try:
                    so, to, xf, mg = GeoAligner_xfm.align(
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
                    src_outs.append(so)
                    tgt_outs.append(to)
                    xforms.append(ght.GH_Transform(xf) if xf is not None else None)
                    moved.append(mg)
                except Exception as e_one:
                    self.Log.append("[ERROR] Step5.4 GeoAligner::3 item[{}]: {}".format(i, e_one))
                    src_outs.append(None)
                    tgt_outs.append(None)
                    xforms.append(None)
                    moved.append(None)

            self.GeoAligner_3__SourceOut = flatten_any(src_outs)
            self.GeoAligner_3__TargetOut = flatten_any(tgt_outs)
            self.GeoAligner_3__TransformOut = flatten_any(xforms)
            self.GeoAligner_3__MovedGeo = flatten_any(moved)

            self.Log.append("[GA3] OK (wrap={}, count={})".format(wrap, n))

        except Exception as e:
            self.Log.append("[ERROR] Step5.4 GeoAligner::3: {}".format(e))
            self.GeoAligner_3__SourceOut = []
            self.GeoAligner_3__TargetOut = []
            self.GeoAligner_3__TransformOut = []
            self.GeoAligner_3__MovedGeo = []

        # 关键输出拍平（避免 System.Collections...）
        self.QiAOTool__CutTimbers = flatten_any(self.QiAOTool__CutTimbers)
        self.QiAOTool__EdgeMidPoints = flatten_any(self.QiAOTool__EdgeMidPoints)
        self.QiAOTool__Corner0Planes = flatten_any(self.QiAOTool__Corner0Planes)
        self.PlaneFromLists_2__ResultPlane = flatten_any(self.PlaneFromLists_2__ResultPlane)
        self.PlaneFromLists_3__ResultPlane = flatten_any(self.PlaneFromLists_3__ResultPlane)
        self.GeoAligner_3__MovedGeo = flatten_any(self.GeoAligner_3__MovedGeo)
        self.GeoAligner_3__TransformOut = flatten_any(self.GeoAligner_3__TransformOut)

        return self

    # ==============================================================
    # Step 6：GongYan + ListItem×2 + GeoAligner::4
    # ==============================================================
    def step6_gongyan_and_geoaligner4(self):
        """
        Step6（附图绿色组）:
            GongYan -> ListItem(Source from GongYan.RefPlane) + ListItem(Target from Timber.FacePlaneList) -> GeoAligner::4

        关键修复：
        - GongYan_LengthFen 与 Offset 可能为 GH Tree / list（Tree_Cleaned），需按 GH 广播循环计算；
          聚合输出 SectionSolidBreps（附图期望 2 个值）。
        """
        import Rhino.Geometry as rg

        # -------------------------
        # 6.1 GongYan
        # -------------------------
        try:
            from yingzao.ancientArchi import FT_GongYanSection_DouKouTiaoBuilder

            def _as_float_scalar(v, default):
                try:
                    if v is None:
                        return float(default)
                    # GH_Goo
                    if hasattr(v, "Value"):
                        v = v.Value
                    return float(v)
                except Exception:
                    try:
                        return float(str(v))
                    except Exception:
                        return float(default)

            def _unwrap_gh_value(x):
                try:
                    return x.Value
                except Exception:
                    return x

            def _as_list_values(x):
                """标量 / list / .NET List / DataTree -> 一维 list"""
                if x is None:
                    return []
                xx = _unwrap_gh_value(x)
                # DataTree / IGH_Structure
                try:
                    if hasattr(xx, "Paths") and hasattr(xx, "Branch"):
                        vals = []
                        for p in xx.Paths:
                            br = xx.Branch(p)
                            if br is None:
                                continue
                            for it in br:
                                vals.append(_unwrap_gh_value(it))
                        return vals
                except Exception:
                    pass

                xx = flatten_any(xx)
                if xx is None:
                    return []
                if isinstance(xx, (list, tuple)):
                    return [_unwrap_gh_value(v) for v in xx]
                return [xx]

            def _as_float_list(x, default_scalar):
                vals = _as_list_values(x)
                out = []
                for v in vals:
                    try:
                        out.append(float(_unwrap_gh_value(v)))
                    except Exception:
                        try:
                            out.append(float(str(v)))
                        except Exception:
                            pass
                if len(out) == 0:
                    out = [float(default_scalar)]
                return out

            # SectionPlane：数据库可为 "WorldXZ" / "XZ" / Plane；缺省用 WorldXZ
            sp_raw = self.all_get("GongYan__SectionPlane", None)
            try:
                section_plane = make_gh_plane(sp_raw if sp_raw is not None else "WorldXZ", rg.Point3d(0, 0, 0))
            except Exception:
                # make_gh_plane 签名差异兜底
                section_plane = make_gh_plane(sp_raw if sp_raw is not None else "WorldXZ", rg.Point3d(0, 0, 0))

            # GongYan BasePoint：按你的反馈，默认原点（不同于主木坯 base_point）
            bp_raw = self.all_get("GongYan__BasePoint", None)
            base_pt = normalize_point3d(bp_raw) if bp_raw is not None else rg.Point3d(0, 0, 0)

            gy_radius = _as_float_scalar(self.all_get("GongYan__GongYan_RadiusFen", None), 1.0)

            # Tree/list 兼容：LengthFen 与 Offset 可能多值（Tree_Cleaned）
            gy_length_list = _as_float_list(self.all_get("GongYan__GongYan_LengthFen", None), 1.0)
            offset_list = _as_float_list(self.all_get("GongYan__Offset", None), 0.0)

            az_qh = _as_float_scalar(self.all_get("GongYan__AnZhi_QiHeightFen", None), 1.0)
            az_sw = _as_float_scalar(self.all_get("GongYan__AnZhi_ShaWidthFen", None), 1.0)
            az_of = _as_float_scalar(self.all_get("GongYan__AnZhi_OffsetFen", None), 0.0)
            gap = _as_float_scalar(self.all_get("GongYan__GapFen", None), 0.0)
            ping_h = _as_float_scalar(self.all_get("GongYan__PingHeight", None), 0.0)
            thickness = _as_float_scalar(self.all_get("GongYan__Thickness", None), 1.0)

            run_count = max(len(gy_length_list), len(offset_list), 1)

            def _pick(lst, i):
                if not lst:
                    return None
                return lst[i % len(lst)]

            # 聚合输出（统一为 list，最后 flatten_any）
            agg_log = []
            agg_debug_pts = []
            agg_section_curves = []
            agg_gongyan_crv = []
            agg_anzhi_crv = []
            agg_section_solid = []
            agg_section_solid_offset = []
            agg_section_solids = []
            agg_ref_plane = []

            last_profile_plane = None
            last_section_face = None

            def _extend(col, val):
                if val is None:
                    return
                vv = flatten_any(val)
                if isinstance(vv, (list, tuple)):
                    col.extend(list(vv))
                else:
                    col.append(vv)

            for i in range(run_count):
                gy_length = float(_pick(gy_length_list, i))
                offset = float(_pick(offset_list, i))

                builder = FT_GongYanSection_DouKouTiaoBuilder(
                    SectionPlane=section_plane,
                    BasePoint=base_pt,
                    GongYan_RadiusFen=gy_radius,
                    GongYan_LengthFen=gy_length,
                    AnZhi_QiHeightFen=az_qh,
                    AnZhi_ShaWidthFen=az_sw,
                    AnZhi_OffsetFen=az_of,
                    GapFen=gap,
                    PingHeight=ping_h,
                    Thickness=thickness,
                    Offset=offset,
                    tol=1e-6
                ).run()

                agg_log += to_py_list(getattr(builder, "log", None))
                _extend(agg_debug_pts, getattr(builder, "debug_pts", None))
                _extend(agg_section_curves, getattr(builder, "section_curves", None))
                _extend(agg_gongyan_crv, getattr(builder, "gongyan_lower", None))
                _extend(agg_anzhi_crv, getattr(builder, "section_boundary", None))
                _extend(agg_section_solid, getattr(builder, "section_solid", None))
                _extend(agg_section_solid_offset, getattr(builder, "section_solid_offset", None))
                try:
                    _extend(agg_section_solids, builder.section_solids[-1])
                except Exception:
                    _extend(agg_section_solids, getattr(builder, "section_solids", None))
                _extend(agg_ref_plane, getattr(builder, "ref_planes", None))

                last_profile_plane = getattr(builder, "profile_plane", None)
                last_section_face = getattr(builder, "section_face", None)

            # ---- members ----
            self.GongYan__Log = agg_log
            self.GongYan__DebugPts = flatten_any(agg_debug_pts)
            self.GongYan__SectionCurves = flatten_any(agg_section_curves)
            self.GongYan__GongYanSectionCrv = flatten_any(agg_gongyan_crv)
            self.GongYan__AnZhiSectionCrv = flatten_any(agg_anzhi_crv)
            self.GongYan__SectionSolidBrep = flatten_any(agg_section_solid)
            self.GongYan__SectionSolidBrep_Offset = flatten_any(agg_section_solid_offset)

            # 关键输出：应可产生 2 个 Brep（Tree/list 广播后）
            self.GongYan__SectionSolidBreps = flatten_any(agg_section_solids)

            # GeoAligner::4 的 SourcePlane 来自此输出（List Item）
            self.GongYan__RefPlane = flatten_any(agg_ref_plane)

            # 可选调试中间量
            self.GongYan__ProfilePlane = last_profile_plane
            self.GongYan__SectionFaceBrep = last_section_face

            self.Log += [
                "[GONGYAN] OK (runs={}, solids={})".format(run_count, len(to_py_list(self.GongYan__SectionSolidBreps)))]
            if self.GongYan__Log:
                self.Log += ["[GONGYAN] " + s for s in to_py_list(self.GongYan__Log)]

        except Exception as e:
            self.Log.append("[ERROR] Step6.1 GongYan: {}".format(e))
            self.GongYan__Log = ["ERROR: {}".format(e)]
            self.GongYan__SectionSolidBreps = []
            self.GongYan__RefPlane = []

        # -------------------------
        # 6.2 List Item x2
        #   - SourcePlane: from GongYan.RefPlane
        #   - TargetPlane: from Timber.FacePlaneList
        # -------------------------
        try:
            src_idx = self.all_get("GeoAligner_4__SourcePlane", 0)
            src_wrap = bool(self.all_get("GeoAligner_4__SourceWrap", True))
            self.GeoAligner_4__SourcePlanePicked, self.GeoAligner_4__SourcePlanePicked_Log = self._list_item_pick(
                self.GongYan__RefPlane,
                src_idx,
                wrap=src_wrap,
                tag="LI_SRC"
            )
            self.GeoAligner_4__SourcePlanePicked = flatten_any(self.GeoAligner_4__SourcePlanePicked)
            self.Log.append("[LI_SRC] OK (wrap={}, count={})".format(src_wrap, len(to_py_list(
                self.GeoAligner_4__SourcePlanePicked))))
        except Exception as e:
            self.Log.append("[ERROR] Step6.2 ListItem(Source): {}".format(e))
            self.GeoAligner_4__SourcePlanePicked = None
            self.GeoAligner_4__SourcePlanePicked_Log = ["ERROR: {}".format(e)]

        try:
            tgt_idx = self.all_get("GeoAligner_4__TargetPlane", 0)
            tgt_wrap = bool(self.all_get("GeoAligner_4__TargetWrap", True))
            self.GeoAligner_4__TargetPlanePicked, self.GeoAligner_4__TargetPlanePicked_Log = self._list_item_pick(
                self.FacePlaneList,
                tgt_idx,
                wrap=tgt_wrap,
                tag="LI_TGT"
            )
            self.GeoAligner_4__TargetPlanePicked = flatten_any(self.GeoAligner_4__TargetPlanePicked)
            self.Log.append("[LI_TGT] OK (wrap={}, count={})".format(tgt_wrap, len(to_py_list(
                self.GeoAligner_4__TargetPlanePicked))))
        except Exception as e:
            self.Log.append("[ERROR] Step6.2 ListItem(Target): {}".format(e))
            self.GeoAligner_4__TargetPlanePicked = None
            self.GeoAligner_4__TargetPlanePicked_Log = ["ERROR: {}".format(e)]

        # -------------------------
        # 6.3 GeoAligner::4
        # -------------------------
        try:
            from yingzao.ancientArchi import GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght

            ga_wrap = bool(self.all_get("GeoAligner_4__Wrap", True))

            rotate = _as_float_scalar(self.all_get("GeoAligner_4__RotateDeg", None), 0.0)
            flip_x = bool(self.all_get("GeoAligner_4__FlipX", False))
            flip_y = bool(self.all_get("GeoAligner_4__FlipY", False))
            flip_z = bool(self.all_get("GeoAligner_4__FlipZ", False))
            move_x = _as_float_scalar(self.all_get("GeoAligner_4__MoveX", None), 0.0)
            move_y = _as_float_scalar(self.all_get("GeoAligner_4__MoveY", None), 0.0)
            move_z = _as_float_scalar(self.all_get("GeoAligner_4__MoveZ", None), 0.0)

            geo_list = to_py_list(self.GongYan__SectionSolidBreps)
            src_list = to_py_list(self.GeoAligner_4__SourcePlanePicked)
            tgt_list = to_py_list(self.GeoAligner_4__TargetPlanePicked)

            # GH 广播：Geo/Source/Target 任一可单可多
            n = max(len(geo_list), len(src_list), len(tgt_list), 1)

            def _pick_b(lst, i):
                if not lst:
                    return None
                return lst[i % len(lst)] if ga_wrap else (lst[i] if i < len(lst) else None)

            out_src, out_tgt, out_xfm, out_geo = [], [], [], []
            for i in range(n):
                g = _pick_b(geo_list, i)
                sp = _pick_b(src_list, i)
                tp = _pick_b(tgt_list, i)

                if g is None or sp is None or tp is None:
                    out_src.append(sp)
                    out_tgt.append(tp)
                    out_xfm.append(None)
                    out_geo.append(None)
                    continue

                s_o, t_o, xfm, moved = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rotate,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=move_y,
                    move_z=move_z
                )
                out_src.append(s_o)
                out_tgt.append(t_o)
                out_xfm.append(ght.GH_Transform(xfm) if xfm is not None else None)
                out_geo.append(moved)

            self.GeoAligner_4__SourceOut = flatten_any(out_src)
            self.GeoAligner_4__TargetOut = flatten_any(out_tgt)
            self.GeoAligner_4__TransformOut = flatten_any(out_xfm)
            self.GeoAligner_4__MovedGeo = flatten_any(out_geo)

            self.Log.append(
                "[GA4] OK (wrap={}, count={})".format(ga_wrap, len(to_py_list(self.GeoAligner_4__MovedGeo))))

        except Exception as e:
            self.Log.append("[ERROR] Step6.3 GeoAligner::4: {}".format(e))
            self.GeoAligner_4__SourceOut = None
            self.GeoAligner_4__TargetOut = None
            self.GeoAligner_4__TransformOut = None
            self.GeoAligner_4__MovedGeo = None

    def step7_blockcutter2_and_geoaligner5(self):
        """Step7：BlockCutter::2 + ListItem×2 + GeoAligner::5（刀具木料块对齐到主木坯平面）
        严格遵守：不重读库；参数优先级由 self.all_get 决定；GH 广播（Wrap/截断）。
        """
        try:
            from yingzao.ancientArchi import build_timber_block_uniform, GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght
        except Exception as e:
            self.Log.append("[ERROR] [STEP7] import: {}".format(e))
            return

        # ---------------------------------------------------------
        # 7.1 BlockCutter::2（实际上是 timber_block_uniform）
        # ---------------------------------------------------------
        try:
            L = self._as_float(self.all_get("BlockCutter_2__length_fen", 10.0), 10.0)
            W = self._as_float(self.all_get("BlockCutter_2__width_fen", 10.0), 10.0)
            H = self._as_float(self.all_get("BlockCutter_2__height_fen", 10.0), 10.0)

            bp = self.base_point if self.base_point is not None else rg.Point3d(0.0, 0.0, 0.0)
            refp_in = self.all_get("BlockCutter_2__reference_plane", "WorldXZ")
            refp = make_gh_plane(refp_in, bp)  # 统一把 origin 移到 base_point

            self.Log.append("[BLOCKCUTTER2] length/width/height = ({:.3f},{:.3f},{:.3f})".format(L, W, H))

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
                L, W, H,
                bp,
                refp,
            )

            self.BlockCutter_2__TimberBrep = timber_brep
            self.BlockCutter_2__FaceList = flatten_any(faces)
            self.BlockCutter_2__PointList = flatten_any(points)
            self.BlockCutter_2__EdgeList = flatten_any(edges)
            self.BlockCutter_2__CenterPoint = center_pt
            self.BlockCutter_2__CenterAxisLines = flatten_any(center_axes)
            self.BlockCutter_2__EdgeMidPoints = flatten_any(edge_midpts)
            self.BlockCutter_2__FacePlaneList = flatten_any(face_planes)
            self.BlockCutter_2__Corner0Planes = flatten_any(corner0_planes)
            self.BlockCutter_2__LocalAxesPlane = local_axes_plane
            self.BlockCutter_2__AxisX = axis_x
            self.BlockCutter_2__AxisY = axis_y
            self.BlockCutter_2__AxisZ = axis_z
            self.BlockCutter_2__FaceDirTags = flatten_any(face_tags)
            self.BlockCutter_2__EdgeDirTags = flatten_any(edge_tags)
            self.BlockCutter_2__Corner0EdgeDirs = flatten_any(corner0_dirs)
            self.BlockCutter_2__Log = flatten_any(log_lines)

            self.Log.extend(["[BLOCKCUTTER2] OK"] + self.BlockCutter_2__Log)

        except Exception as e:
            self.Log.append("[BLOCKCUTTER2] ERROR: {}".format(e))
            # 清空输出，避免后续崩溃
            self.BlockCutter_2__TimberBrep = None
            self.BlockCutter_2__FaceList = []
            self.BlockCutter_2__PointList = []
            self.BlockCutter_2__EdgeList = []
            self.BlockCutter_2__CenterPoint = None
            self.BlockCutter_2__CenterAxisLines = []
            self.BlockCutter_2__EdgeMidPoints = []
            self.BlockCutter_2__FacePlaneList = []
            self.BlockCutter_2__Corner0Planes = []
            self.BlockCutter_2__LocalAxesPlane = None
            self.BlockCutter_2__AxisX = None
            self.BlockCutter_2__AxisY = None
            self.BlockCutter_2__AxisZ = None
            self.BlockCutter_2__FaceDirTags = []
            self.BlockCutter_2__EdgeDirTags = []
            self.BlockCutter_2__Corner0EdgeDirs = []
            self.BlockCutter_2__Log = []
            return

        # ---------------------------------------------------------
        # 7.2 List Item ×2（取 SourcePlane / TargetPlane）
        # ---------------------------------------------------------
        # ListItem A：SourcePlane（来自 BlockCutter::2 FacePlaneList）
        try:
            src_idx = self.all_get("GeoAligner_5__SourcePlane", 0)
            src_wrap = _as_bool(self.all_get("GeoAligner_5__SourceWrap", True), True)

            picked_src, picked_src_log = self._list_item_pick(
                self.BlockCutter_2__FacePlaneList,
                src_idx,
                wrap=src_wrap,
                label="LI5_SRC",
            )
            self.GeoAligner_5__SourcePlanePicked = flatten_any(picked_src)
            self.GeoAligner_5__SourcePlanePicked_Log = flatten_any(picked_src_log)

            self.Log.extend(self.GeoAligner_5__SourcePlanePicked_Log)

        except Exception as e:
            self.GeoAligner_5__SourcePlanePicked = []
            self.GeoAligner_5__SourcePlanePicked_Log = ["[LI5_SRC] ERROR: {}".format(e)]
            self.Log.extend(self.GeoAligner_5__SourcePlanePicked_Log)

        # ListItem B：TargetPlane（来自 主木坯 FacePlaneList）
        try:
            tgt_idx = self.all_get("GeoAligner_5__TargetPlane", 0)
            tgt_wrap = _as_bool(self.all_get("GeoAligner_5__TargetWrap", True), True)

            picked_tgt, picked_tgt_log = self._list_item_pick(
                self.FacePlaneList,
                tgt_idx,
                wrap=tgt_wrap,
                label="LI5_TGT",
            )
            self.GeoAligner_5__TargetPlanePicked = flatten_any(picked_tgt)
            self.GeoAligner_5__TargetPlanePicked_Log = flatten_any(picked_tgt_log)

            self.Log.extend(self.GeoAligner_5__TargetPlanePicked_Log)

        except Exception as e:
            self.GeoAligner_5__TargetPlanePicked = []
            self.GeoAligner_5__TargetPlanePicked_Log = ["[LI5_TGT] ERROR: {}".format(e)]
            self.Log.extend(self.GeoAligner_5__TargetPlanePicked_Log)

        # ---------------------------------------------------------
        # 7.3 GeoAligner::5（GH 广播：Geo / SourcePlane / TargetPlane）
        # ---------------------------------------------------------
        try:
            rotate_deg = self._as_float(self.all_get("GeoAligner_5__RotateDeg", 0.0), 0.0)
            flip_x = _as_bool(self.all_get("GeoAligner_5__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_5__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_5__FlipZ", False), False)
            move_x = self._as_float(self.all_get("GeoAligner_5__MoveX", 0.0), 0.0)
            move_y = self._as_float(self.all_get("GeoAligner_5__MoveY", 0.0), 0.0)
            move_z = self._as_float(self.all_get("GeoAligner_5__MoveZ", 0.0), 0.0)
            ga_wrap = _as_bool(self.all_get("GeoAligner_5__Wrap", True), True)

            geos = flatten_any(to_py_list(self.BlockCutter_2__TimberBrep))
            if not geos:
                geos = [self.BlockCutter_2__TimberBrep]

            srcs = flatten_any(to_py_list(self.GeoAligner_5__SourcePlanePicked))
            tgts = flatten_any(to_py_list(self.GeoAligner_5__TargetPlanePicked))

            n = _broadcast_len(geos, srcs, tgts, wrap=ga_wrap)

            src_out_all, tgt_out_all, moved_all, xfm_all = [], [], [], []
            for i in range(n):
                g = _pick(geos, i, wrap=ga_wrap)
                sp = _pick(srcs, i, wrap=ga_wrap)
                tp = _pick(tgts, i, wrap=ga_wrap)

                if g is None or sp is None or tp is None:
                    self.Log.append("[GA5] item[{}] skip (geo/src/tgt is None)".format(i))
                    src_out_all.append(None)
                    tgt_out_all.append(None)
                    moved_all.append(None)
                    xfm_all.append(None)
                    continue

                try:
                    s_out, t_out, xform, moved = GeoAligner_xfm.align(
                        g,
                        sp,
                        tp,
                        rotate_deg=rotate_deg,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                        move_x=move_x,
                        move_y=move_y,
                        move_z=move_z,
                    )
                    src_out_all.append(s_out)
                    tgt_out_all.append(t_out)
                    moved_all.append(moved)
                    xfm_all.append(xform)

                except Exception as e_one:
                    self.Log.append("[GA5] item[{}] ERROR: {}".format(i, e_one))
                    src_out_all.append(None)
                    tgt_out_all.append(None)
                    moved_all.append(None)
                    xfm_all.append(None)

            self.GeoAligner_5__SourceOut = flatten_any(src_out_all)
            self.GeoAligner_5__TargetOut = flatten_any(tgt_out_all)
            self.GeoAligner_5__MovedGeo = flatten_any(moved_all)

            # TransformOut -> GH_Transform（逐项包装）
            xfm_wrapped = []
            for t in flatten_any(xfm_all):
                try:
                    xfm_wrapped.append(ght.GH_Transform(t) if t is not None else None)
                except Exception:
                    xfm_wrapped.append(None)
            self.GeoAligner_5__TransformOut = flatten_any(xfm_wrapped)

            self.Log.append("[GA5] OK (wrap={}, count={})".format(ga_wrap, n))

        except Exception as e:
            self.Log.append("[GA5] ERROR: {}".format(e))
            self.GeoAligner_5__SourceOut = []
            self.GeoAligner_5__TargetOut = []
            self.GeoAligner_5__MovedGeo = []
            self.GeoAligner_5__TransformOut = []

    def step8_chaang_geoaligner6_cutv3_1(self):
        """Step8：ChaAng + ListItem×2 + GeoAligner::6 + CutTimbersByTools_V3::1
        仅增量实现本步骤；不重读本 Solver 的库（ChaAng 子 Solver 会自行读库）；GH 广播（Wrap/截断）。
        """
        try:
            from yingzao.ancientArchi import ChaAng4PUSolver, GeoAligner_xfm, FT_CutTimbersByTools_GH_SolidDifference
            import Grasshopper.Kernel.Types as ght
        except Exception as e:
            self.Log.append("[ERROR] [STEP8] import: {}".format(e))
            return

        # ---------------------------------------------------------
        # 8.1 ChaAng（子 Solver：会自行读库；这里仅调用并保留输出）
        # ---------------------------------------------------------
        try:
            bp = self.base_point if self.base_point is not None else rg.Point3d(0.0, 0.0, 0.0)
            self.Log.append("[CHAANG] run ChaAng4PUSolver ...")
            _ca = ChaAng4PUSolver(self.DBPath, bp, self.Refresh)
            _ca.run()

            self.ChaAng__CutTimbers = flatten_any(getattr(_ca, "CutTimbers", None))
            self.ChaAng__FailTimbers = flatten_any(getattr(_ca, "FailTimbers", None))
            self.ChaAng__Log = flatten_any(getattr(_ca, "Log", []))
            self.ChaAng__RefPlanes = flatten_any(getattr(_ca, "RefPlanes", []))
            self.ChaAng__SolidFace_AE = getattr(_ca, "SolidFace_AE", None)

            # 日志
            if self.ChaAng__Log:
                self.Log.extend(["[CHAANG] " + str(x) for x in self.ChaAng__Log])
            else:
                self.Log.append("[CHAANG] OK (no log lines)")

        except Exception as e:
            self.Log.append("[CHAANG] ERROR: {}".format(e))
            self.ChaAng__CutTimbers = []
            self.ChaAng__FailTimbers = []
            self.ChaAng__Log = ["ERROR: {}".format(e)]
            self.ChaAng__RefPlanes = []
            self.ChaAng__SolidFace_AE = None
            # ChaAng 失败则后续不继续
            return

        # ---------------------------------------------------------
        # 8.2 List Item ×2（取 SourcePlane / TargetPlane）
        # ---------------------------------------------------------
        # ListItem A：SourcePlane（来自 ChaAng RefPlanes）
        try:
            src_idx = self.all_get("GeoAligner_6__SourcePlane", 0)
            src_wrap = _as_bool(self.all_get("GeoAligner_6__SourceWrap", True), True)

            picked_src, picked_src_log = self._list_item_pick(
                self.ChaAng__RefPlanes,
                src_idx,
                wrap=src_wrap,
                label="LI6_SRC",
            )
            self.GeoAligner_6__SourcePlanePicked = flatten_any(picked_src)
            self.GeoAligner_6__SourcePlanePicked_Log = flatten_any(picked_src_log)
            self.Log.extend(self.GeoAligner_6__SourcePlanePicked_Log)
        except Exception as e:
            self.GeoAligner_6__SourcePlanePicked = []
            self.GeoAligner_6__SourcePlanePicked_Log = ["[LI6_SRC] ERROR: {}".format(e)]
            self.Log.extend(self.GeoAligner_6__SourcePlanePicked_Log)

        # ListItem B：TargetPlane（来自 主木坯 FacePlaneList）
        try:
            tgt_idx = self.all_get("GeoAligner_6__TargetPlane", 0)
            tgt_wrap = _as_bool(self.all_get("GeoAligner_6__TargetWrap", True), True)

            picked_tgt, picked_tgt_log = self._list_item_pick(
                self.FacePlaneList,
                tgt_idx,
                wrap=tgt_wrap,
                label="LI6_TGT",
            )
            self.GeoAligner_6__TargetPlanePicked = flatten_any(picked_tgt)
            self.GeoAligner_6__TargetPlanePicked_Log = flatten_any(picked_tgt_log)
            self.Log.extend(self.GeoAligner_6__TargetPlanePicked_Log)
        except Exception as e:
            self.GeoAligner_6__TargetPlanePicked = []
            self.GeoAligner_6__TargetPlanePicked_Log = ["[LI6_TGT] ERROR: {}".format(e)]
            self.Log.extend(self.GeoAligner_6__TargetPlanePicked_Log)

        # ---------------------------------------------------------
        # 8.3 GeoAligner::6（GH 广播：Geo / SourcePlane / TargetPlane）
        # ---------------------------------------------------------
        try:
            rotate_deg = self._as_float(self.all_get("GeoAligner_6__RotateDeg", 0.0), 0.0)
            flip_x = _as_bool(self.all_get("GeoAligner_6__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_6__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_6__FlipZ", False), False)
            move_x = self._as_float(self.all_get("GeoAligner_6__MoveX", 0.0), 0.0)
            move_y = self._as_float(self.all_get("GeoAligner_6__MoveY", 0.0), 0.0)
            move_z = self._as_float(self.all_get("GeoAligner_6__MoveZ", 0.0), 0.0)
            ga_wrap = _as_bool(self.all_get("GeoAligner_6__Wrap", True), True)

            geos = flatten_any(to_py_list(self.ChaAng__CutTimbers))
            if not geos:
                geos = [self.ChaAng__CutTimbers]

            srcs = flatten_any(to_py_list(self.GeoAligner_6__SourcePlanePicked))
            tgts = flatten_any(to_py_list(self.GeoAligner_6__TargetPlanePicked))

            n = _broadcast_len(geos, srcs, tgts, wrap=ga_wrap)

            src_out_all, tgt_out_all, moved_all, xfm_all = [], [], [], []
            for i in range(n):
                g = _pick(geos, i, wrap=ga_wrap)
                sp = _pick(srcs, i, wrap=ga_wrap)
                tp = _pick(tgts, i, wrap=ga_wrap)

                if g is None or sp is None or tp is None:
                    self.Log.append("[GA6] item[{}] skip (geo/src/tgt is None)".format(i))
                    src_out_all.append(None)
                    tgt_out_all.append(None)
                    moved_all.append(None)
                    xfm_all.append(None)
                    continue

                try:
                    s_out, t_out, xform, moved = GeoAligner_xfm.align(
                        g,
                        sp,
                        tp,
                        rotate_deg=rotate_deg,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                        move_x=move_x,
                        move_y=move_y,
                        move_z=move_z,
                    )
                    src_out_all.append(s_out)
                    tgt_out_all.append(t_out)
                    moved_all.append(moved)
                    xfm_all.append(xform)
                except Exception as ee:
                    self.Log.append("[GA6] item[{}] ERROR: {}".format(i, ee))
                    src_out_all.append(None)
                    tgt_out_all.append(None)
                    moved_all.append(None)
                    xfm_all.append(None)

            # TransformOut 包装为 GH_Transform
            xfm_wrapped = []
            for x in flatten_any(xfm_all):
                try:
                    xfm_wrapped.append(ght.GH_Transform(x) if x is not None else None)
                except Exception:
                    xfm_wrapped.append(x)

            self.GeoAligner_6__SourceOut = flatten_any(src_out_all)
            self.GeoAligner_6__TargetOut = flatten_any(tgt_out_all)
            self.GeoAligner_6__MovedGeo = flatten_any(moved_all)
            self.GeoAligner_6__TransformOut = flatten_any(xfm_wrapped)

            self.Log.append("[GA6] OK (wrap={}, count={})".format(ga_wrap, n))

        except Exception as e:
            self.Log.append("[GA6] ERROR: {}".format(e))
            self.GeoAligner_6__SourceOut = []
            self.GeoAligner_6__TargetOut = []
            self.GeoAligner_6__MovedGeo = []
            self.GeoAligner_6__TransformOut = []

        # ---------------------------------------------------------
        # 8.4 CutTimbersByTools_V3::1（对齐后的 ChaAng 作为刀具切主木坯）
        # ---------------------------------------------------------
        try:
            wrap_cut = _as_bool(self.all_get("CutTimbersByTools_V3_1__Wrap", True), True)
            keep_inside = _as_bool(self.all_get("CutTimbersByTools_V3_1__KeepInside", False), False)
            debug_cut = _as_bool(self.all_get("CutTimbersByTools_V3_1__Debug", False), False)

            timbers_in = self.GeoAligner_6__MovedGeo

            # Tools 可能来自多个对象/多个列表/Tree；必须作为「一个扁平列表」传入 cutter.cut(...)
            tools_in = flatten_any([
                self.GeoAligner_2__MovedGeo,
                self.GeoAligner_5__MovedGeo,
            ])
            # 过滤 None，确保 tools_in 为一维 list
            tools_in = [t for t in tools_in if t is not None]

            timbers_list = flatten_any(to_py_list(timbers_in))
            if not timbers_list:
                timbers_list = [timbers_in]
            # 同样过滤 None（避免无效输入）
            timbers_list = [t for t in timbers_list if t is not None]

            if not tools_in:
                # 无刀具：直接返回原 timber
                self.CutTimbersByTools_V3_1__CutTimbers = flatten_any(timbers_list)
                self.CutTimbersByTools_V3_1__FailTimbers = []
                self.CutTimbersByTools_V3_1__Log = ["[CUTV3_1] tools empty -> pass through"]
                self.Log.extend(self.CutTimbersByTools_V3_1__Log)
                return

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=debug_cut)

            cut_all, fail_all, log_all = [], [], []
            # 规则：多个 timbers -> 每个 timber 都用同一组 tools 切（符合 GH 常见 1×N）

            try:
                c, f, lg = cutter.cut(
                    timbers=timbers_list,
                    tools=tools_in,
                    keep_inside=keep_inside,
                    debug=debug_cut
                )
                # cut_all.extend(flatten_any(c))
                cut_all.extend(flatten_any(c))
                fail_all.extend(flatten_any(f))
                log_all.extend(flatten_any(lg))
            except Exception as ee:
                log_all.append("[CUTV3_1] timber[{}] ERROR: {}".format(i, ee))

            self.CutTimbersByTools_V3_1__CutTimbers = flatten_any(cut_all)
            self.CutTimbersByTools_V3_1__FailTimbers = flatten_any(fail_all)
            self.CutTimbersByTools_V3_1__Log = ["[CUTV3_1] wrap={}, keep_inside={}".format(wrap_cut,
                                                                                           keep_inside)] + flatten_any(
                log_all)

            self.Log.extend(self.CutTimbersByTools_V3_1__Log)
            # 8.4.1 选取体积最大的 CutTimbers（CutTimbersByTools_V3::1 可能产生多个对象）
            try:
                import ghpythonlib.components as ghc
                cand = [b for b in flatten_any(self.CutTimbersByTools_V3_1__CutTimbers) if b is not None]
                self.CutTimbersByTools_V3_1__CutTimbers_All = cand
                if cand:
                    best_brep = None
                    best_vol = None
                    for b in cand:
                        try:
                            v, _c = ghc.Volume(b)
                            v = float(v) if v is not None else None
                        except Exception:
                            v = None
                        if v is None:
                            continue
                        if (best_vol is None) or (v > best_vol):
                            best_vol = v
                            best_brep = b
                    if best_brep is not None:
                        self.CutTimbersByTools_V3_1__CutTimbers = [best_brep]
                        self.Log.append("[CUTV3_1] pick max volume = {}".format(best_vol))
                    else:
                        self.Log.append("[CUTV3_1] volume compute failed; keep all")
            except Exception as ee:
                self.Log.append("[CUTV3_1] max volume select error: {}".format(ee))
                self.CutTimbersByTools_V3_1__CutTimbers_All = flatten_any(self.CutTimbersByTools_V3_1__CutTimbers)

        except Exception as e:
            self.Log.append("[CUTV3_1] ERROR: {}".format(e))
            self.CutTimbersByTools_V3_1__CutTimbers = []
            self.CutTimbersByTools_V3_1__FailTimbers = []
            self.CutTimbersByTools_V3_1__Log = ["ERROR: {}".format(e)]

    # ------------------------------------------------------
    # Step 9：绿色分组（PlaneFromLists::4 + CutV3::2 + SplitSectionAnalyzer +
    #        RightTrianglePrismBuilder + GeoAligner::7 + CutV3::3）
    # ------------------------------------------------------
    def step9_green_group(self):
        """仅实现绿色分组对应步骤；不再读库，只使用 AllDict + 输入端 + 默认值。"""

        step_log = []

        # --------------------------------------------------
        # 9.1 CutTimbersByTools_V3::2（第一次切割）
        # --------------------------------------------------
        try:
            keep_inside_2 = _as_bool(self.all_get("CutTimbersByTools_V3_2__KeepInside", True), True)
            debug_2 = _as_bool(self.all_get("CutTimbersByTools_V3_2__Debug", False), False)

            tools_merge = []
            for _t in [
                self.GeoAligner_1__MovedGeo,
                self.GeoAligner_2__MovedGeo,
                self.GeoAligner_3__MovedGeo,
                self.GeoAligner_4__MovedGeo,
                self.GeoAligner_5__MovedGeo,
            ]:
                tools_merge.extend([x for x in flatten_any(_t) if x is not None])

            timbers_in = self.TimberBrep
            if timbers_in is None:
                self.CutTimbersByTools_V3_2__CutTimbers = []
                self.CutTimbersByTools_V3_2__FailTimbers = []
                self.CutTimbersByTools_V3_2__Log = ["[CUTV3_2] TimberBrep is None; skip"]
            elif not tools_merge:
                self.CutTimbersByTools_V3_2__CutTimbers = [timbers_in]
                self.CutTimbersByTools_V3_2__FailTimbers = []
                self.CutTimbersByTools_V3_2__Log = ["[CUTV3_2] tools empty -> pass through"]
            else:
                cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=debug_2)
                c, f, lg = cutter.cut(
                    timbers=timbers_in,
                    tools=tools_merge,
                    keep_inside=keep_inside_2,
                    debug=debug_2
                )
                self.CutTimbersByTools_V3_2__CutTimbers = flatten_any(c)
                self.CutTimbersByTools_V3_2__FailTimbers = flatten_any(f)
                self.CutTimbersByTools_V3_2__Log = [
                                                       "[CUTV3_2] keep_inside={} | tools={}".format(keep_inside_2,
                                                                                                    len(tools_merge))
                                                   ] + flatten_any(lg)

            step_log.extend(self.CutTimbersByTools_V3_2__Log)
        except Exception as e:
            self.CutTimbersByTools_V3_2__CutTimbers = []
            self.CutTimbersByTools_V3_2__FailTimbers = []
            self.CutTimbersByTools_V3_2__Log = ["[CUTV3_2] ERROR: {}".format(e)]
            step_log.extend(self.CutTimbersByTools_V3_2__Log)

        # --------------------------------------------------
        # 9.2 PlaneFromLists::4（剖切 PlaneRef）
        # --------------------------------------------------
        try:
            idx_origin = self.all_get("PlaneFromLists_4__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_4__IndexPlane", None)
            wrap = _as_bool(self.all_get("PlaneFromLists_4__Wrap", True), True)

            origin_pts = to_py_list(self.EdgeMidPoints)
            base_pls = to_py_list(self.Corner0Planes)
            idx_o = flatten_any(to_py_list(idx_origin)) if idx_origin is not None else [0]
            idx_p = flatten_any(to_py_list(idx_plane)) if idx_plane is not None else [0]

            n = _broadcast_len(idx_o, idx_p, wrap=True)
            picked_bp, picked_op, result_pl, plog = [], [], [], []

            if not origin_pts or not base_pls:
                plog.append("[PFL4] origin_pts or base_pls empty")
            for i in range(n):
                io = _pick(idx_o, i, wrap=True)
                ip = _pick(idx_p, i, wrap=True)
                try:
                    io_i = int(io) if io is not None else 0
                except Exception:
                    io_i = 0
                try:
                    ip_i = int(ip) if ip is not None else 0
                except Exception:
                    ip_i = 0

                if not origin_pts or not base_pls:
                    picked_bp.append(None)
                    picked_op.append(None)
                    result_pl.append(None)
                    continue

                if wrap:
                    op = origin_pts[io_i % len(origin_pts)]
                    bp = base_pls[ip_i % len(base_pls)]
                else:
                    op = origin_pts[io_i] if 0 <= io_i < len(origin_pts) else None
                    bp = base_pls[ip_i] if 0 <= ip_i < len(base_pls) else None

                picked_bp.append(bp)
                picked_op.append(op)
                if bp is None or op is None:
                    result_pl.append(None)
                else:
                    try:
                        pl = rg.Plane(bp)
                        pl.Origin = op
                        result_pl.append(pl)
                    except Exception:
                        result_pl.append(None)

            self.PlaneFromLists_4__BasePlane = flatten_any(picked_bp)
            self.PlaneFromLists_4__OriginPoint = flatten_any(picked_op)
            self.PlaneFromLists_4__ResultPlane = flatten_any(result_pl)
            self.PlaneFromLists_4__Log = ["[PFL4] wrap={} n={}".format(wrap, n)] + flatten_any(plog)

            step_log.extend(self.PlaneFromLists_4__Log)
        except Exception as e:
            self.PlaneFromLists_4__BasePlane = []
            self.PlaneFromLists_4__OriginPoint = []
            self.PlaneFromLists_4__ResultPlane = []
            self.PlaneFromLists_4__Log = ["[PFL4] ERROR: {}".format(e)]
            step_log.extend(self.PlaneFromLists_4__Log)

        # --------------------------------------------------
        # 9.3 SplitSectionAnalyzer（剖切分析）
        # --------------------------------------------------
        try:
            # Brep input: CutTimbersByTools_V3::2 -> CutTimbers (keep list when multiple)
            breps = [b for b in flatten_any(self.CutTimbersByTools_V3_2__CutTimbers) if b is not None]
            if not breps:
                brep_in = None
            elif len(breps) == 1:
                brep_in = breps[0]
            else:
                brep_in = breps

            # Cutter: Transform(ChaAng.SolidFace_AE, GeoAligner6.TransformOut)
            cutter_geo = self.ChaAng__SolidFace_AE
            xfm = None
            try:
                xfm_list = flatten_any(self.GeoAligner_6__TransformOut)
                xfm = unwrap_gh_transform(xfm_list[0]) if xfm_list else None
            except Exception:
                xfm = None

            cutter_xf = None
            if cutter_geo is not None and xfm is not None:
                try:
                    # BrepFace special case
                    if hasattr(cutter_geo, "DuplicateFace"):
                        cutter_xf = cutter_geo.DuplicateFace(True)
                    elif hasattr(cutter_geo, "Duplicate"):
                        cutter_xf = cutter_geo.Duplicate()
                    else:
                        cutter_xf = cutter_geo
                    try:
                        cutter_xf.Transform(xfm)
                    except Exception:
                        # try transform on a copy brep
                        pass
                except Exception:
                    cutter_xf = cutter_geo
            else:
                cutter_xf = cutter_geo

            # --- Cutter 输入调整（PlaneFromLists::5 + BrepPlane[EX]） ---
            # 目的：为 SplitSectionAnalyzer 提供更稳定的 Cutter（BrepPlane[EX] 的 MaxAreaBrep）
            cutter_for_ssa = cutter_xf
            try:
                # 9.2.1 PlaneFromLists::5
                idx_origin5 = self.all_get("PlaneFromLists_5__IndexOrigin", None)
                idx_plane5 = self.all_get("PlaneFromLists_5__IndexPlane", None)
                wrap5 = _as_bool(self.all_get("PlaneFromLists_5__Wrap", True), True)

                origin_pts5 = to_py_list(self.CenterPoint)
                base_pls5 = to_py_list(self.Corner0Planes)
                idx_o5 = flatten_any(to_py_list(idx_origin5)) if idx_origin5 is not None else [0]
                idx_p5 = flatten_any(to_py_list(idx_plane5)) if idx_plane5 is not None else [0]

                n5 = _broadcast_len(origin_pts5, base_pls5, idx_o5, idx_p5, wrap=True)
                bp5_list, op5_list, rp5_list, plog5 = [], [], [], []
                if not origin_pts5 or not base_pls5:
                    plog5.append("[PFL5] origin_pts5 or base_pls5 empty")
                for ii in range(n5):
                    io = _pick(idx_o5, ii, wrap=True)
                    ip = _pick(idx_p5, ii, wrap=True)
                    try:
                        io_i = int(io) if io is not None else 0
                    except Exception:
                        io_i = 0
                    try:
                        ip_i = int(ip) if ip is not None else 0
                    except Exception:
                        ip_i = 0

                    if not origin_pts5 or not base_pls5:
                        bp5_list.append(None)
                        op5_list.append(None)
                        rp5_list.append(None)
                        continue

                    if wrap5:
                        op = origin_pts5[io_i % len(origin_pts5)]
                        bp = base_pls5[ip_i % len(base_pls5)]
                    else:
                        op = origin_pts5[io_i] if 0 <= io_i < len(origin_pts5) else None
                        bp = base_pls5[ip_i] if 0 <= ip_i < len(base_pls5) else None

                    bp5_list.append(bp)
                    op5_list.append(op)
                    if bp is None or op is None:
                        rp5_list.append(None)
                    else:
                        try:
                            pl = rg.Plane(bp)
                            pl.Origin = op
                            rp5_list.append(pl)
                        except Exception:
                            rp5_list.append(None)

                self.PlaneFromLists_5__BasePlane = flatten_any(bp5_list)
                self.PlaneFromLists_5__OriginPoint = flatten_any(op5_list)
                self.PlaneFromLists_5__ResultPlane = flatten_any(rp5_list)
                self.PlaneFromLists_5__Log = ["[PFL5] wrap={} n={}".format(wrap5, n5)] + flatten_any(plog5)

                # 9.2.2 BrepPlane[EX]（SplitByPlaneAnalyzer）
                _tol = self.all_get("BrepPlaneEX__Tol", None)
                tol_use = float(_tol) if _tol is not None else (sc.doc.ModelAbsoluteTolerance if sc.doc else 0.01)

                max_brep = None
                max_area = None
                split_breps_all = []
                areas_all = []
                section_crvs_all = []
                section_pts_all = []
                log_brepplane = []

                for pl in flatten_any(self.PlaneFromLists_5__ResultPlane):
                    if pl is None or cutter_xf is None:
                        continue
                    try:
                        ana = SplitByPlaneAnalyzer(cutter_xf, pl, tol=tol_use, cutter_scale=2.0).run()
                        split_breps_all.extend(flatten_any(getattr(ana, 'split_breps', [])))
                        areas_all.extend(flatten_any(getattr(ana, 'areas', [])))
                        section_crvs_all.extend(flatten_any(getattr(ana, 'section_curves', [])))
                        section_pts_all.extend(flatten_any(getattr(ana, 'section_points', [])))
                        log_brepplane.extend(flatten_any(getattr(ana, 'log', [])))
                        a = getattr(ana, 'max_area', None)
                        b = getattr(ana, 'max_area_brep', None)
                        try:
                            a_val = float(a) if a is not None else None
                        except Exception:
                            a_val = None
                        if b is not None and a_val is not None:
                            if (max_area is None) or (a_val > max_area):
                                max_area = a_val
                                max_brep = b
                    except Exception as _ee:
                        log_brepplane.append('[BrepPlaneEX] ERROR: {}'.format(_ee))

                self.BrepPlaneEX__SplitBreps = flatten_any(split_breps_all)
                self.BrepPlaneEX__Areas = flatten_any(areas_all)
                self.BrepPlaneEX__MaxAreaBrep = max_brep
                self.BrepPlaneEX__MaxArea = max_area
                self.BrepPlaneEX__SectionCurves = flatten_any(section_crvs_all)
                self.BrepPlaneEX__SectionPoints = flatten_any(section_pts_all)
                self.BrepPlaneEX__Log = ['[BrepPlaneEX] tol={}'.format(tol_use)] + flatten_any(log_brepplane)

                if max_brep is not None:
                    cutter_for_ssa = max_brep
            except Exception as _ee:
                self.PlaneFromLists_5__Log = ['[PFL5] ERROR: {}'.format(_ee)]
                self.BrepPlaneEX__Log = ['[BrepPlaneEX] ERROR: {}'.format(_ee)]

            tol_default = (sc.doc.ModelAbsoluteTolerance if sc.doc else 0.01)
            cap_tol = None
            split_tol = None

            try:
                cap_tol = float(cap_tol)
            except Exception:
                cap_tol = float(tol_default)
            try:
                split_tol = float(split_tol)
            except Exception:
                split_tol = float(tol_default)

            plane_ref = self.PlaneFromLists_4__ResultPlane
            # NOTE: sticky cache fully removed per requirement; always recompute.
            # Other optional inputs are intentionally left as None (unwired in GH).
            _poly_div_n = 64
            _poly_min_seg = 0.0
            _planar_factor = 50.0

            self.cutter_xf = cutter_xf
            print(plane_ref)

            an = SplitSectionAnalyzer(
                brep=brep_in,
                cutter=cutter_for_ssa,
                cap_tol=None,
                split_tol=None,
                polyline_div_n=_poly_div_n,
                polyline_min_seg=_poly_min_seg,
                planar_tol_factor=_planar_factor,
                plane_ref=plane_ref[0],
            ).run()
            # 输出映射（尽量按组件脚本字段名）
            self.SplitSectionAnalyzer__SortedVolumes = getattr(an, "sorted_volumes", [])
            self.SplitSectionAnalyzer__MaxClosedBrep = getattr(an, "max_closed_brep", None)
            self.SplitSectionAnalyzer__SectionFaces = getattr(an, "section_faces", [])
            self.SplitSectionAnalyzer__SectionBrep = getattr(an, "section_brep", None)
            self.SplitSectionAnalyzer__StableEdgeCurves = getattr(an, "stable_edge_curves", [])
            self.SplitSectionAnalyzer__StableLineSegments = getattr(an, "stable_line_segments", [])
            self.SplitSectionAnalyzer__StableMidPoints = getattr(an, "segment_midpoints", [])
            self.SplitSectionAnalyzer__MaxMidPoint = getattr(an, "maxx_midpoint", None)
            self.SplitSectionAnalyzer__CutterAnglesHV = getattr(an, "cutter_angles_hv", [None, None])
            self.SplitSectionAnalyzer__PlaneCutterCurves = getattr(an, "plane_cutter_curves", [])
            self.SplitSectionAnalyzer__PlaneCutterMidPoint = getattr(an, "plane_cutter_midpoint", None)
            self.SplitSectionAnalyzer__Log = flatten_any(getattr(an, "log", []))

            print(self.SplitSectionAnalyzer__PlaneCutterMidPoint)

            step_log.extend(["[SSA] cap_tol={} split_tol={}".format(cap_tol, split_tol)])
            step_log.extend(self.SplitSectionAnalyzer__Log)
        except Exception as e:
            self.SplitSectionAnalyzer__SortedVolumes = []
            self.SplitSectionAnalyzer__MaxClosedBrep = None
            self.SplitSectionAnalyzer__SectionFaces = []
            self.SplitSectionAnalyzer__SectionBrep = None
            self.SplitSectionAnalyzer__StableEdgeCurves = []
            self.SplitSectionAnalyzer__StableLineSegments = []
            self.SplitSectionAnalyzer__StableMidPoints = []
            self.SplitSectionAnalyzer__MaxMidPoint = None
            self.SplitSectionAnalyzer__CutterAnglesHV = [None, None]
            self.SplitSectionAnalyzer__PlaneCutterCurves = []
            self.SplitSectionAnalyzer__PlaneCutterMidPoint = None
            self.SplitSectionAnalyzer__Log = ["[SSA] ERROR: {}".format(e)]
            step_log.extend(self.SplitSectionAnalyzer__Log)

        # --------------------------------------------------
        # 9.4 RightTrianglePrismBuilder（直角三棱柱刀具）
        # --------------------------------------------------
        # 按要求修改：
        #   - base_point：默认原点
        #   - ref_plane：使用组件默认值（交由 builder.default_plane_tag 处理）
        #   - offset：使用默认值
        #   - theta：来自 SplitSectionAnalyzer__CutterAnglesHV，索引=RightTrianglePrismBuilder__theta
        #   - h：RightTrianglePrismBuilder__h
        # --------------------------------------------------
        try:
            # base_point / ref_plane / offset：全部使用默认
            base_pt = rg.Point3d(0, 0, 0)
            ref_plane = None
            offset = None

            # h
            h_in = self.all_get("RightTrianglePrismBuilder__h", 1.0)
            try:
                h = float(h_in)
            except Exception:
                h = 1.0

            # theta = CutterAnglesHV[theta_idx]
            theta_idx_in = self.all_get("RightTrianglePrismBuilder__theta", 0)
            try:
                theta_idx = int(theta_idx_in)
            except Exception:
                theta_idx = 0

            cutter_angles = flatten_any(getattr(self, "SplitSectionAnalyzer__CutterAnglesHV", []) or [])
            if cutter_angles and 0 <= theta_idx < len(cutter_angles):
                try:
                    theta = float(cutter_angles[theta_idx])
                except Exception:
                    theta = float(cutter_angles[0])
                    theta_idx = 0
            elif cutter_angles:
                # idx 越界，回退到 0
                try:
                    theta = float(cutter_angles[0])
                except Exception:
                    theta = 0.0
                theta_idx = 0
            else:
                # 无可用角度，回退为 0
                theta = 0.0
                theta_idx = 0

            builder = RightTrianglePrismBuilder(
                theta_deg=theta,
                h=h,
                base_point=base_pt,
                ref_plane=ref_plane,  # 默认值：由 default_plane_tag 兜底
                offset=offset,
                tol=(sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6),
                default_plane_tag="WorldXZ",
            )
            out = builder.run() or {}

            # 保存全部关键输出（developer-friendly）
            self.RightTrianglePrismBuilder__dist = out.get("dist", None)
            self.RightTrianglePrismBuilder__SectionCurve = out.get("SectionCurve", None)
            self.RightTrianglePrismBuilder__SectionPts = flatten_any(out.get("SectionPts", []))
            self.RightTrianglePrismBuilder__BrepSolid = out.get("BrepSolid", None)
            self.RightTrianglePrismBuilder__BrepParts = flatten_any(out.get("BrepParts", []))
            self.RightTrianglePrismBuilder__OPlanes = flatten_any(out.get("OPlanes", []))
            self.RightTrianglePrismBuilder__Log = flatten_any(out.get("Log", []))

            step_log.append("[RTPB] theta_idx={} theta={} h={} offset={} (base_point=Origin, ref_plane=default)".format(
                theta_idx, theta, h, offset
            ))
            step_log.extend(self.RightTrianglePrismBuilder__Log)
        except Exception as e:
            self.RightTrianglePrismBuilder__dist = None
            self.RightTrianglePrismBuilder__SectionCurve = None
            self.RightTrianglePrismBuilder__SectionPts = []
            self.RightTrianglePrismBuilder__BrepSolid = None
            self.RightTrianglePrismBuilder__BrepParts = []
            self.RightTrianglePrismBuilder__OPlanes = []
            self.RightTrianglePrismBuilder__Log = ["[RTPB] ERROR: {}".format(e)]
            step_log.extend(self.RightTrianglePrismBuilder__Log)

        # --------------------------------------------------
        # 9.5 GeoAligner::7（三棱柱刀具对齐到目标平面）（三棱柱刀具对齐到目标平面）
        # --------------------------------------------------
        try:
            geo = self.RightTrianglePrismBuilder__BrepSolid

            # SourcePlane：OPlanes[ListItem]
            sp_idx = self.all_get("GeoAligner_7__SourcePlane", 0)
            sp_wrap = _as_bool(self.all_get("GeoAligner_7__SourceWrap", True), True)
            picked_sp, picked_sp_log = self._list_item_pick(
                self.RightTrianglePrismBuilder__OPlanes,
                sp_idx,
                wrap=sp_wrap,
                label="LI7_SRC",
            )
            src_plane = picked_sp[0] if picked_sp else None
            step_log.extend(flatten_any(picked_sp_log))

            # TargetPlane：PlaneOrigin(Base=Transformed(SourcePlane of GA6), Origin=PlaneCutterMidPoint)
            target_plane = None
            try:
                src_pls = flatten_any(self.GeoAligner_6__SourcePlanePicked)
                src_pl = src_pls[0] if src_pls else None
                if src_pl is not None:
                    target_plane = rg.Plane(src_pl)
                    xfm_list = flatten_any(self.GeoAligner_6__TransformOut)
                    xfm = unwrap_gh_transform(xfm_list[0]) if xfm_list else None
                    if xfm is not None:
                        target_plane.Transform(xfm)
                    if self.SplitSectionAnalyzer__PlaneCutterMidPoint is not None:
                        target_plane.Origin = self.SplitSectionAnalyzer__PlaneCutterMidPoint
            except Exception:
                target_plane = None

            # 保存 TargetPlane 引用，供后续 GeoAligner::8 复用（必须与 GeoAligner::7 TargetPlane 完全一致）
            self.GeoAligner_7__TargetPlane = target_plane

            rotate_deg = self._as_float(self.all_get("GeoAligner_7__RotateDeg", 0.0), 0.0)
            flip_x = _as_bool(self.all_get("GeoAligner_7__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_7__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_7__FlipZ", False), False)
            move_x = self._as_float(self.all_get("GeoAligner_7__MoveX", 0.0), 0.0)
            move_y = self._as_float(self.all_get("GeoAligner_7__MoveY", 0.0), 0.0)
            move_z = self._as_float(self.all_get("GeoAligner_7__MoveZ", 0.0), 0.0)

            if geo is None or src_plane is None or target_plane is None:
                self.GeoAligner_7__SourceOut = None
                self.GeoAligner_7__TargetOut = None
                self.GeoAligner_7__MovedGeo = None
                self.GeoAligner_7__TransformOut = None
                step_log.append("[GA7] geo/src/tgt is None; skip")
            else:
                s_out, t_out, xform, moved = GeoAligner_xfm.align(
                    geo,
                    src_plane,
                    target_plane,
                    rotate_deg=rotate_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=move_y,
                    move_z=move_z,
                )
                self.GeoAligner_7__SourceOut = s_out
                self.GeoAligner_7__TargetOut = t_out
                self.GeoAligner_7__MovedGeo = moved
                try:
                    self.GeoAligner_7__TransformOut = ght.GH_Transform(xform) if xform is not None else None
                except Exception:
                    self.GeoAligner_7__TransformOut = xform
                step_log.append("[GA7] OK")
        except Exception as e:
            self.GeoAligner_7__SourceOut = None
            self.GeoAligner_7__TargetOut = None
            self.GeoAligner_7__MovedGeo = None
            self.GeoAligner_7__TransformOut = None
            step_log.append("[GA7] ERROR: {}".format(e))

        # --------------------------------------------------
        # 9.6 CutTimbersByTools_V3::3（第二次切割）
        # --------------------------------------------------
        try:
            keep_inside_3 = _as_bool(self.all_get("CutTimbersByTools_V3_3__KeepInside", True), True)
            debug_3 = _as_bool(self.all_get("CutTimbersByTools_V3_3__Debug", False), False)

            timber_in = self.SplitSectionAnalyzer__MaxClosedBrep
            tool_geo = self.GeoAligner_7__MovedGeo
            tools = [tool_geo] if tool_geo is not None else []

            if timber_in is None:
                self.CutTimbersByTools_V3_3__CutTimbers = []
                self.CutTimbersByTools_V3_3__FailTimbers = []
                self.CutTimbersByTools_V3_3__Log = ["[CUTV3_3] MaxClosedBrep is None; skip"]
            elif not tools:
                self.CutTimbersByTools_V3_3__CutTimbers = [timber_in]
                self.CutTimbersByTools_V3_3__FailTimbers = []
                self.CutTimbersByTools_V3_3__Log = ["[CUTV3_3] tool empty -> pass through"]
            else:
                cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=debug_3)
                c, f, lg = cutter.cut(
                    timbers=timber_in,
                    tools=tools,
                    keep_inside=keep_inside_3,
                    debug=debug_3
                )
                self.CutTimbersByTools_V3_3__CutTimbers = flatten_any(c)
                self.CutTimbersByTools_V3_3__FailTimbers = flatten_any(f)
                self.CutTimbersByTools_V3_3__Log = [
                                                       "[CUTV3_3] keep_inside={}".format(keep_inside_3)
                                                   ] + flatten_any(lg)

            step_log.extend(self.CutTimbersByTools_V3_3__Log)
        except Exception as e:
            self.CutTimbersByTools_V3_3__CutTimbers = []
            self.CutTimbersByTools_V3_3__FailTimbers = []
            self.CutTimbersByTools_V3_3__Log = ["[CUTV3_3] ERROR: {}".format(e)]
            step_log.extend(self.CutTimbersByTools_V3_3__Log)

        # --------------------------------------------------
        # Step 9 对外输出（至少 CutTimbers / FailTimbers / Log）
        # --------------------------------------------------
        self.CutTimbers = flatten_any(self.CutTimbersByTools_V3_3__CutTimbers)
        self.FailTimbers = flatten_any(self.CutTimbersByTools_V3_3__FailTimbers)

        # 合并 Step9 日志
        self.Log.extend([str(x) for x in flatten_any(step_log)])

        return self

    def stepX_huatouzi_geoaligner8_cutv3_4(self):
        """Step X：花头子刀具生成 + 对齐 + 裁切

        HuaTouZi + GeoAligner::8 + CutTimbersByTools_V3::4

        关键约束：
        - 禁止读库：仅使用 AllDict + 组件输入端 + 默认值
        - GeoAligner::8 TargetPlane 必须与 GeoAligner::7 TargetPlane 同一引用来源
        - GeoAligner::8 MoveX = -RightTrianglePrismBuilder__dist
        - CutTimbersByTools_V3::4 Timbers = CutTimbersByTools_V3::3 CutTimbers
        """

        step_log = []

        # --------------------------------------------------
        # X-1 HuaTouZi（生成花头子刀具）
        # --------------------------------------------------
        try:
            base_pt = rg.Point3d.Origin
            ref_plane_mode = self.all_get("HuaTouZi__ref_plane_mode", None)
            if ref_plane_mode is None:
                ref_plane_mode = self.all_get("HuaTouZi__RefPlaneMode", None)
            if ref_plane_mode is None:
                ref_plane_mode = "XZ Plane"

            tol_in = self.all_get("HuaTouZi__Tol", None)
            tol = _as_float(tol_in, sc.doc.ModelAbsoluteTolerance if sc.doc else 0.01)
            if tol <= 0:
                tol = sc.doc.ModelAbsoluteTolerance if sc.doc else 0.01

            AB_in = self.all_get("HuaTouZi__AB", None)
            BC_in = self.all_get("HuaTouZi__BC", None)
            DE_in = self.all_get("HuaTouZi__DE", None)
            HF_in = self.all_get("HuaTouZi__HF", None)
            IG_in = self.all_get("HuaTouZi__IG", None)
            OFF_in = self.all_get("HuaTouZi__Offset", None)

            def _vals_as_items(v, default_scalar):
                if v is None:
                    return [float(default_scalar)]
                # Tree / list / scalar
                if _is_gh_datatree(v):
                    return v
                vv = flatten_any(to_py_list(v))
                if not vv:
                    return [float(default_scalar)]
                return vv

            AB = _vals_as_items(AB_in, 10.0)
            BC = _vals_as_items(BC_in, 4.0)
            DE = _vals_as_items(DE_in, 0.5)
            HF = _vals_as_items(HF_in, None)  # HF 可能未使用
            IG = _vals_as_items(IG_in, 1.5)
            OFF = _vals_as_items(OFF_in, 5.0)

            any_tree = any(_is_gh_datatree(x) for x in [AB, BC, DE, HF, IG, OFF])

            def _build_one(ab, bc, de, hf, ig, off):
                # 防御：None -> 默认
                ab = _as_float(ab, 10.0)
                bc = _as_float(bc, 4.0)
                de = _as_float(de, 0.5)
                ig = _as_float(ig, 1.5)
                off = _as_float(off, 5.0)
                hf = _as_float(hf, 0.0) if hf is not None else None

                ht = HuaTouZi(base_point=base_pt, ref_plane_mode=ref_plane_mode, tol=tol)
                # 兼容 HF 参数（不同版本可能无该参数）
                try:
                    if hf is None:
                        ht.set_params(AB=ab, BC=bc, DE=de, IG=ig, Offset=off, Tol=tol)
                    else:
                        ht.set_params(AB=ab, BC=bc, DE=de, HF=hf, IG=ig, Offset=off, Tol=tol)
                except Exception:
                    ht.set_params(AB=ab, BC=bc, DE=de, IG=ig, Offset=off, Tol=tol)

                if _as_bool(self.Refresh, False):
                    try:
                        ht.log.append("Refresh=True: recompute triggered by button.")
                    except Exception:
                        pass

                ht.build(reset=True)
                return {
                    "SolidBrep": ht.solid_brep,
                    "SectionCrv": ht.section_crv,
                    "SectionCrv_Pos": ht.section_crv_pos,
                    "SectionCrv_Neg": ht.section_crv_neg,
                    "LoftBrep": ht.loft_brep,
                    "CapPosBrep": ht.cap_pos_brep,
                    "CapNegBrep": ht.cap_neg_brep,
                    "Log": flatten_any(getattr(ht, "log", [])),
                    "Pts_B": getattr(ht, "B", None),
                    "PlaneAtB_X": getattr(ht, "plane_at_b_x", None),
                }

            # outputs collector (tree-aware)
            out_keys = [
                "SolidBrep",
                "SectionCrv",
                "SectionCrv_Pos",
                "SectionCrv_Neg",
                "LoftBrep",
                "CapPosBrep",
                "CapNegBrep",
                "Log",
                "Pts_B",
                "PlaneAtB_X",
            ]

            branch_maps = {k: [] for k in out_keys}

            if any_tree:
                # branch-wise
                trees = {"AB": AB, "BC": BC, "DE": DE, "HF": HF, "IG": IG, "OFF": OFF}
                branch_lists = {}
                max_branches = 0
                for name, tv in trees.items():
                    if _is_gh_datatree(tv):
                        bl = _tree_to_branch_items(tv)
                        branch_lists[name] = bl
                        max_branches = max(max_branches, len(bl))
                    else:
                        branch_lists[name] = None

                for bi in range(max_branches if max_branches > 0 else 1):
                    path = None
                    # pick path from first available tree
                    for name, bl in branch_lists.items():
                        if bl and bi < len(bl):
                            path = bl[bi][0]
                            break
                    if path is None:
                        path = GH_Path(bi) if GH_Path is not None else None

                    def _branch_items(name, fallback_items):
                        bl = branch_lists.get(name)
                        if bl is None:
                            return flatten_any(to_py_list(fallback_items))
                        if not bl:
                            return []
                        if bi < len(bl):
                            return flatten_any(to_py_list(bl[bi][1]))
                        return flatten_any(to_py_list(bl[-1][1]))

                    ab_items = _branch_items("AB", AB)
                    bc_items = _branch_items("BC", BC)
                    de_items = _branch_items("DE", DE)
                    hf_items = _branch_items("HF", HF)
                    ig_items = _branch_items("IG", IG)
                    off_items = _branch_items("OFF", OFF)

                    n = _broadcast_len(ab_items, bc_items, de_items, hf_items, ig_items, off_items, wrap=True)
                    if n <= 0:
                        n = 1

                    for ii in range(n):
                        res = _build_one(
                            _pick(ab_items, ii, wrap=True),
                            _pick(bc_items, ii, wrap=True),
                            _pick(de_items, ii, wrap=True),
                            _pick(hf_items, ii, wrap=True) if hf_items else None,
                            _pick(ig_items, ii, wrap=True),
                            _pick(off_items, ii, wrap=True),
                        )
                        for k in out_keys:
                            branch_maps[k].append((path, [res.get(k, None)]))

                # convert to DataTree where possible
                def _mk_tree(k):
                    dt = DataTree[object]() if DataTree is not None else None
                    if dt is None:
                        return [it for _, items in branch_maps[k] for it in to_py_list(items)]
                    for path, items in branch_maps[k]:
                        if path is None:
                            path = GH_Path(0)
                        for it in to_py_list(items):
                            dt.Add(it, path)
                    return dt

                self.HuaTouZi__SolidBrep = _mk_tree("SolidBrep")
                self.HuaTouZi__SectionCrv = _mk_tree("SectionCrv")
                self.HuaTouZi__SectionCrv_Pos = _mk_tree("SectionCrv_Pos")
                self.HuaTouZi__SectionCrv_Neg = _mk_tree("SectionCrv_Neg")
                self.HuaTouZi__LoftBrep = _mk_tree("LoftBrep")
                self.HuaTouZi__CapPosBrep = _mk_tree("CapPosBrep")
                self.HuaTouZi__CapNegBrep = _mk_tree("CapNegBrep")
                self.HuaTouZi__Pts_B = _mk_tree("Pts_B")
                self.HuaTouZi__PlaneAtB_X = _mk_tree("PlaneAtB_X")
                # log: flatten all
                self.HuaTouZi__Log = [str(x) for x in flatten_any(_mk_tree("Log"))]
            else:
                # list/scalar broadcast
                ab_items = flatten_any(to_py_list(AB))
                bc_items = flatten_any(to_py_list(BC))
                de_items = flatten_any(to_py_list(DE))
                hf_items = flatten_any(to_py_list(HF))
                ig_items = flatten_any(to_py_list(IG))
                off_items = flatten_any(to_py_list(OFF))
                n = _broadcast_len(ab_items, bc_items, de_items, hf_items, ig_items, off_items, wrap=True)
                if n <= 0:
                    n = 1
                solids, sec, secp, secn, lofts, capP, capN, logs, ptsb, plbx = ([] for _ in range(10))
                for i in range(n):
                    res = _build_one(
                        _pick(ab_items, i, wrap=True),
                        _pick(bc_items, i, wrap=True),
                        _pick(de_items, i, wrap=True),
                        _pick(hf_items, i, wrap=True) if hf_items else None,
                        _pick(ig_items, i, wrap=True),
                        _pick(off_items, i, wrap=True),
                    )
                    solids.append(res.get("SolidBrep"))
                    sec.append(res.get("SectionCrv"))
                    secp.append(res.get("SectionCrv_Pos"))
                    secn.append(res.get("SectionCrv_Neg"))
                    lofts.append(res.get("LoftBrep"))
                    capP.append(res.get("CapPosBrep"))
                    capN.append(res.get("CapNegBrep"))
                    logs.extend(flatten_any(res.get("Log", [])))
                    ptsb.append(res.get("Pts_B"))
                    plbx.append(res.get("PlaneAtB_X"))

                # 若只有一个元素则保留单值语义（更贴近 GH）
                self.HuaTouZi__SolidBrep = solids[0] if len(solids) == 1 else solids
                self.HuaTouZi__SectionCrv = sec[0] if len(sec) == 1 else sec
                self.HuaTouZi__SectionCrv_Pos = secp[0] if len(secp) == 1 else secp
                self.HuaTouZi__SectionCrv_Neg = secn[0] if len(secn) == 1 else secn
                self.HuaTouZi__LoftBrep = lofts[0] if len(lofts) == 1 else lofts
                self.HuaTouZi__CapPosBrep = capP[0] if len(capP) == 1 else capP
                self.HuaTouZi__CapNegBrep = capN[0] if len(capN) == 1 else capN
                self.HuaTouZi__Pts_B = ptsb[0] if len(ptsb) == 1 else ptsb
                self.HuaTouZi__PlaneAtB_X = plbx[0] if len(plbx) == 1 else plbx
                self.HuaTouZi__Log = [str(x) for x in flatten_any(logs)]

            step_log.append("[HuaTouZi] OK")
            step_log.extend(self.HuaTouZi__Log)
        except Exception as e:
            self.HuaTouZi__SolidBrep = None
            self.HuaTouZi__SectionCrv = None
            self.HuaTouZi__SectionCrv_Pos = None
            self.HuaTouZi__SectionCrv_Neg = None
            self.HuaTouZi__LoftBrep = None
            self.HuaTouZi__CapPosBrep = None
            self.HuaTouZi__CapNegBrep = None
            self.HuaTouZi__Pts_B = None
            self.HuaTouZi__PlaneAtB_X = None
            self.HuaTouZi__Log = ["[HuaTouZi] ERROR: {}".format(e)]
            step_log.extend(self.HuaTouZi__Log)

        # --------------------------------------------------
        # X-2 GeoAligner::8（对齐花头子刀具）
        # --------------------------------------------------
        try:
            geo_in = self.HuaTouZi__SolidBrep
            src_in = self.HuaTouZi__PlaneAtB_X
            # TargetPlane 必须与 GeoAligner::7 的 TargetPlane 完全一致（同一引用来源）
            tgt_plane = self.GeoAligner_7__TargetPlane

            rotate_deg = _as_float(self.all_get("GeoAligner_8__RotateDeg", 0.0), 0.0)
            flip_x = _as_bool(self.all_get("GeoAligner_8__FlipX", False), False)
            flip_y = _as_bool(self.all_get("GeoAligner_8__FlipY", False), False)
            flip_z = _as_bool(self.all_get("GeoAligner_8__FlipZ", False), False)

            dist = self.RightTrianglePrismBuilder__dist
            if dist is None:
                dist = self.all_get("RightTrianglePrismBuilder__dist", 0.0)
            move_x = -_as_float(dist, 0.0)
            move_y = _as_float(self.all_get("GeoAligner_8__MoveY", 0.0), 0.0)
            move_z = _as_float(self.all_get("GeoAligner_8__MoveZ", 0.0), 0.0)

            # tree-aware align
            def _align_one(g, sp):
                if g is None or sp is None or tgt_plane is None:
                    return None, None, None, None

                s_out, t_out, xform, moved = GeoAligner_xfm.align(
                    g,
                    sp,
                    tgt_plane,
                    rotate_deg=rotate_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=move_y,
                    move_z=move_z,
                )
                xform = ght.GH_Transform(xform) if xform is not None else None
                return s_out, t_out, xform, moved

            if _is_gh_datatree(geo_in) or _is_gh_datatree(src_in):
                # branch-wise align
                geo_br = _tree_to_branch_items(geo_in) if _is_gh_datatree(geo_in) else None
                src_br = _tree_to_branch_items(src_in) if _is_gh_datatree(src_in) else None
                max_br = max(len(geo_br) if geo_br else 0, len(src_br) if src_br else 0)
                if max_br <= 0:
                    max_br = 1

                def _mk_dt():
                    return DataTree[object]() if DataTree is not None else None

                dt_s, dt_t, dt_x, dt_m = _mk_dt(), _mk_dt(), _mk_dt(), _mk_dt()
                list_s, list_t, list_x, list_m = [], [], [], []

                for bi in range(max_br):
                    path = None
                    if geo_br and bi < len(geo_br):
                        path = geo_br[bi][0]
                    elif src_br and bi < len(src_br):
                        path = src_br[bi][0]
                    if path is None and GH_Path is not None:
                        path = GH_Path(bi)

                    geo_items = flatten_any(to_py_list(geo_br[bi][1])) if geo_br and bi < len(geo_br) else flatten_any(
                        to_py_list(geo_in))
                    src_items = flatten_any(to_py_list(src_br[bi][1])) if src_br and bi < len(src_br) else flatten_any(
                        to_py_list(src_in))

                    n = _broadcast_len(geo_items, src_items, wrap=True)
                    if n <= 0:
                        n = 1
                    for ii in range(n):
                        s_out, t_out, x_out, m_out = _align_one(
                            _pick(geo_items, ii, wrap=True),
                            _pick(src_items, ii, wrap=True),
                        )
                        if dt_s is not None:
                            dt_s.Add(s_out, path)
                            dt_t.Add(t_out, path)
                            dt_x.Add(x_out, path)
                            dt_m.Add(m_out, path)
                        else:
                            list_s.append(s_out)
                            list_t.append(t_out)
                            list_x.append(x_out)
                            list_m.append(m_out)

                self.GeoAligner_8__SourceOut = dt_s if dt_s is not None else list_s
                self.GeoAligner_8__TargetOut = dt_t if dt_t is not None else list_t
                self.GeoAligner_8__TransformOut = dt_x if dt_x is not None else list_x
                self.GeoAligner_8__MovedGeo = dt_m if dt_m is not None else list_m
            else:
                geo_list = flatten_any(to_py_list(geo_in))
                src_list = flatten_any(to_py_list(src_in))
                n = _broadcast_len(geo_list, src_list, wrap=True)
                if n <= 0:
                    n = 1
                s_all, t_all, x_all, m_all = [], [], [], []
                for i in range(n):
                    s_out, t_out, x_out, m_out = _align_one(
                        _pick(geo_list, i, wrap=True),
                        _pick(src_list, i, wrap=True),
                    )
                    s_all.append(s_out)
                    t_all.append(t_out)
                    x_all.append(x_out)
                    m_all.append(m_out)

                self.GeoAligner_8__SourceOut = s_all[0] if len(s_all) == 1 else s_all
                self.GeoAligner_8__TargetOut = t_all[0] if len(t_all) == 1 else t_all
                self.GeoAligner_8__TransformOut = x_all[0] if len(x_all) == 1 else x_all
                self.GeoAligner_8__MovedGeo = m_all[0] if len(m_all) == 1 else m_all

            step_log.append("[GA8] OK | MoveX={}".format(move_x))
        except Exception as e:
            self.GeoAligner_8__SourceOut = None
            self.GeoAligner_8__TargetOut = None
            self.GeoAligner_8__MovedGeo = None
            self.GeoAligner_8__TransformOut = None
            step_log.append("[GA8] ERROR: {}".format(e))

        # --------------------------------------------------
        # X-3 CutTimbersByTools_V3::4（用花头子刀具裁切木料）
        # --------------------------------------------------
        try:
            # Timbers：CutTimbersByTools_V3::3 的 CutTimbers
            timbers_in = [x for x in flatten_any(self.CutTimbersByTools_V3_3__CutTimbers) if x is not None]

            # Tools：GeoAligner::8 MovedGeo
            tools_in = [x for x in flatten_any(self.GeoAligner_8__MovedGeo) if x is not None]

            # KeepInside：优先取 Negative 组件 Result（若库里有），否则退回 CutTimbersByTools_V3_4__KeepInside
            keep_inside = self.all_get("Negative__Result", None)
            if keep_inside is None:
                keep_inside = self.all_get("CutTimbersByTools_V3_4__KeepInside", None)
            keep_inside = _as_bool(keep_inside, False)

            debug_4 = _as_bool(self.all_get("CutTimbersByTools_V3_4__Debug", False), False)

            if not timbers_in:
                self.CutTimbersByTools_V3_4__CutTimbers = []
                self.CutTimbersByTools_V3_4__FailTimbers = []
                self.CutTimbersByTools_V3_4__Log = ["[CUTV3_4] timbers empty; skip"]
            elif not tools_in:
                self.CutTimbersByTools_V3_4__CutTimbers = timbers_in
                self.CutTimbersByTools_V3_4__FailTimbers = []
                self.CutTimbersByTools_V3_4__Log = ["[CUTV3_4] tools empty -> pass through"]
            else:
                cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=debug_4)
                cut_all, fail_all, log_all = [], [], []
                for tb in timbers_in:
                    c, f, lg = cutter.cut(
                        timbers=tb,
                        tools=tools_in,
                        keep_inside=keep_inside,
                        debug=debug_4,
                    )
                    cut_all.extend(flatten_any(c))
                    fail_all.extend(flatten_any(f))
                    log_all.extend(flatten_any(lg))
                self.CutTimbersByTools_V3_4__CutTimbers = flatten_any(cut_all)
                self.CutTimbersByTools_V3_4__FailTimbers = flatten_any(fail_all)
                self.CutTimbersByTools_V3_4__Log = [
                                                       "[CUTV3_4] keep_inside={} | tools={} | timbers={}".format(
                                                           keep_inside, len(tools_in), len(timbers_in)
                                                       )
                                                   ] + flatten_any(log_all)

            # 对外输出更新到 Step X 结果
            self.CutTimbers = flatten_any(self.CutTimbersByTools_V3_4__CutTimbers)
            self.FailTimbers = flatten_any(self.CutTimbersByTools_V3_4__FailTimbers)

            step_log.extend(self.CutTimbersByTools_V3_4__Log)
        except Exception as e:
            self.CutTimbersByTools_V3_4__CutTimbers = []
            self.CutTimbersByTools_V3_4__FailTimbers = []
            self.CutTimbersByTools_V3_4__Log = ["[CUTV3_4] ERROR: {}".format(e)]
            step_log.extend(self.CutTimbersByTools_V3_4__Log)

        # 合并日志
        self.Log.extend([str(x) for x in flatten_any(step_log)])
        return self

    def run(self):
        self.step1_read_db()
        self.step2_timber_block_uniform()
        self.step3_juan_sha_and_align()
        self.step4_blockcutter_and_geoaligner2()
        self.step5_qiaotool_pfl2_pfl3_geoaligner3()
        self.step6_gongyan_and_geoaligner4()

        self.step7_blockcutter2_and_geoaligner5()
        self.step8_chaang_geoaligner6_cutv3_1()
        self.step9_green_group()
        self.stepX_huatouzi_geoaligner8_cutv3_4()
        # 拍平，避免 GH 显示 System.Collections.Generic.List`1[System.Object]
        self.CutTimbers = flatten_any(self.CutTimbers)
        self.FailTimbers = flatten_any(self.FailTimbers)

        # 关键列表也做一次 to_py_list + flatten，便于后续广播
        self.FaceList = flatten_any(self.FaceList)
        self.PointList = flatten_any(self.PointList)
        self.EdgeList = flatten_any(self.EdgeList)
        self.CenterAxisLines = flatten_any(self.CenterAxisLines)
        self.EdgeMidPoints = flatten_any(self.EdgeMidPoints)
        self.FacePlaneList = flatten_any(self.FacePlaneList)
        self.Corner0Planes = flatten_any(self.Corner0Planes)

        # Step4 关键列表再拍平一次（避免 .NET List）
        # Step4 FacePlaneList：若为多木料块(list[list[Plane]])则保持结构；仅在一维时拍平
        try:
            if isinstance(self.BlockCutter_1__FacePlaneList, list) and self.BlockCutter_1__FacePlaneList and isinstance(
                    self.BlockCutter_1__FacePlaneList[0], rg.Plane):
                self.BlockCutter_1__FacePlaneList = flatten_any(self.BlockCutter_1__FacePlaneList)
        except Exception:
            pass
        self.GeoAligner_2__SourcePlanePicked = flatten_any(self.GeoAligner_2__SourcePlanePicked)
        self.GeoAligner_2__TargetPlanePicked = flatten_any(self.GeoAligner_2__TargetPlanePicked)
        self.GeoAligner_2__MovedGeo = flatten_any(self.GeoAligner_2__MovedGeo)
        self.GeoAligner_2__TransformOut = flatten_any(self.GeoAligner_2__TransformOut)

        return self


if __name__ == "__main__":
    # ==============================================================
    # GhPython 组件入口
    # ==============================================================

    # 说明：
    # - 下面假定 GH 组件已声明输入：DBPath, base_point, Refresh
    # - 并已声明输出：CutTimbers, FailTimbers, Log 以及（可选）开发模式输出

    _solver = ChaAngInLineWNiDaoGong2Solver(DBPath, base_point, Refresh, ghenv)
    _solver.run()

    # 面向使用者的输出
    CutTimbers = _solver.CutTimbers
    FailTimbers = _solver.FailTimbers
    Log = _solver.Log

    # --------------------------------------------------------------
    # GH Python 组件 · 输出绑定区（developer-friendly）
    #   ✅ 逐一把 Solver 成员变量赋给同名输出端
    #   只要你在 GH 里增加同名输出端，就能直接看到内部状态
    # --------------------------------------------------------------

    # Step 1
    Value = _solver.Value
    All = _solver.All
    AllDict = _solver.AllDict
    DBLog = _solver.DBLog

    # Step 2
    TimberBrep = _solver.TimberBrep
    FaceList = _solver.FaceList
    PointList = _solver.PointList
    EdgeList = _solver.EdgeList
    CenterPoint = _solver.CenterPoint
    CenterAxisLines = _solver.CenterAxisLines
    EdgeMidPoints = _solver.EdgeMidPoints
    FacePlaneList = _solver.FacePlaneList
    Corner0Planes = _solver.Corner0Planes
    LocalAxesPlane = _solver.LocalAxesPlane
    AxisX = _solver.AxisX
    AxisY = _solver.AxisY
    AxisZ = _solver.AxisZ
    FaceDirTags = _solver.FaceDirTags
    EdgeDirTags = _solver.EdgeDirTags
    Corner0EdgeDirs = _solver.Corner0EdgeDirs

    # Step 3
    PlaneFromLists_1__BasePlane = _solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint = _solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__ResultPlane = _solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log = _solver.PlaneFromLists_1__Log

    JuanSha__ToolBrep = _solver.JuanSha__ToolBrep
    JuanSha__HL_Intersection = _solver.JuanSha__HL_Intersection
    JuanSha__SectionEdges = _solver.JuanSha__SectionEdges
    JuanSha__HeightFacePlane = _solver.JuanSha__HeightFacePlane
    JuanSha__LengthFacePlane = _solver.JuanSha__LengthFacePlane
    JuanSha__Log = _solver.JuanSha__Log

    GeoAligner_1__SourceOut = _solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut = _solver.GeoAligner_1__TargetOut
    GeoAligner_1__MovedGeo = _solver.GeoAligner_1__MovedGeo
    GeoAligner_1__TransformOut = _solver.GeoAligner_1__TransformOut

    # Step 4
    BlockCutter_1__TimberBrep = _solver.BlockCutter_1__TimberBrep
    BlockCutter_1__FaceList = _solver.BlockCutter_1__FaceList
    BlockCutter_1__PointList = _solver.BlockCutter_1__PointList
    BlockCutter_1__EdgeList = _solver.BlockCutter_1__EdgeList
    BlockCutter_1__CenterPoint = _solver.BlockCutter_1__CenterPoint
    BlockCutter_1__CenterAxisLines = _solver.BlockCutter_1__CenterAxisLines
    BlockCutter_1__EdgeMidPoints = _solver.BlockCutter_1__EdgeMidPoints
    BlockCutter_1__FacePlaneList = _solver.BlockCutter_1__FacePlaneList
    BlockCutter_1__Corner0Planes = _solver.BlockCutter_1__Corner0Planes
    BlockCutter_1__LocalAxesPlane = _solver.BlockCutter_1__LocalAxesPlane
    BlockCutter_1__AxisX = _solver.BlockCutter_1__AxisX
    BlockCutter_1__AxisY = _solver.BlockCutter_1__AxisY
    BlockCutter_1__AxisZ = _solver.BlockCutter_1__AxisZ
    BlockCutter_1__FaceDirTags = _solver.BlockCutter_1__FaceDirTags
    BlockCutter_1__EdgeDirTags = _solver.BlockCutter_1__EdgeDirTags
    BlockCutter_1__Corner0EdgeDirs = _solver.BlockCutter_1__Corner0EdgeDirs
    BlockCutter_1__Log = _solver.BlockCutter_1__Log

    GeoAligner_2__SourcePlanePicked = _solver.GeoAligner_2__SourcePlanePicked
    GeoAligner_2__SourcePlanePicked_Log = _solver.GeoAligner_2__SourcePlanePicked_Log
    GeoAligner_2__TargetPlanePicked = _solver.GeoAligner_2__TargetPlanePicked
    GeoAligner_2__TargetPlanePicked_Log = _solver.GeoAligner_2__TargetPlanePicked_Log

    GeoAligner_2__SourceOut = _solver.GeoAligner_2__SourceOut
    GeoAligner_2__TargetOut = _solver.GeoAligner_2__TargetOut
    GeoAligner_2__MovedGeo = _solver.GeoAligner_2__MovedGeo
    GeoAligner_2__TransformOut = _solver.GeoAligner_2__TransformOut

    # Step 5
    QiAOTool__CutTimbers = _solver.QiAOTool__CutTimbers
    QiAOTool__FailTimbers = _solver.QiAOTool__FailTimbers
    QiAOTool__Log = _solver.QiAOTool__Log
    QiAOTool__EdgeMidPoints = _solver.QiAOTool__EdgeMidPoints
    QiAOTool__Corner0Planes = _solver.QiAOTool__Corner0Planes
    QiAOTool__TimberBrep = _solver.QiAOTool__TimberBrep
    QiAOTool__ToolBrep = _solver.QiAOTool__ToolBrep
    QiAOTool__AlignedTool = _solver.QiAOTool__AlignedTool
    QiAOTool__PFL1_ResultPlane = _solver.QiAOTool__PFL1_ResultPlane
    QiAOTool__QiAo_FacePlane = _solver.QiAOTool__QiAo_FacePlane

    PlaneFromLists_2__BasePlane = _solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = _solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane = _solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = _solver.PlaneFromLists_2__Log

    PlaneFromLists_3__BasePlane = _solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__OriginPoint = _solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__ResultPlane = _solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__Log = _solver.PlaneFromLists_3__Log

    GeoAligner_3__SourceOut = _solver.GeoAligner_3__SourceOut
    GeoAligner_3__TargetOut = _solver.GeoAligner_3__TargetOut
    GeoAligner_3__MovedGeo = _solver.GeoAligner_3__MovedGeo
    GeoAligner_3__TransformOut = _solver.GeoAligner_3__TransformOut

    # Step 6: GongYan + ListItem×2 + GeoAligner::4
    GongYan__GongYanSectionCrv = _solver.GongYan__GongYanSectionCrv
    GongYan__AnZhiSectionCrv = _solver.GongYan__AnZhiSectionCrv
    GongYan__SectionCurves = _solver.GongYan__SectionCurves
    GongYan__DebugPts = _solver.GongYan__DebugPts
    GongYan__SectionSolidBrep = _solver.GongYan__SectionSolidBrep
    GongYan__SectionSolidBrep_Offset = _solver.GongYan__SectionSolidBrep_Offset
    GongYan__SectionSolidBreps = _solver.GongYan__SectionSolidBreps
    GongYan__RefPlane = _solver.GongYan__RefPlane
    GongYan__Log = _solver.GongYan__Log

    GeoAligner_4__SourcePlanePicked = _solver.GeoAligner_4__SourcePlanePicked
    GeoAligner_4__SourcePlanePicked_Log = _solver.GeoAligner_4__SourcePlanePicked_Log
    GeoAligner_4__TargetPlanePicked = _solver.GeoAligner_4__TargetPlanePicked
    GeoAligner_4__TargetPlanePicked_Log = _solver.GeoAligner_4__TargetPlanePicked_Log

    GeoAligner_4__SourceOut = _solver.GeoAligner_4__SourceOut
    GeoAligner_4__TargetOut = _solver.GeoAligner_4__TargetOut
    GeoAligner_4__MovedGeo = _solver.GeoAligner_4__MovedGeo
    GeoAligner_4__TransformOut = _solver.GeoAligner_4__TransformOut

    # ------------------ Step7（BlockCutter::2 + GeoAligner::5）developer-friendly outputs ------------------
    BlockCutter_2__TimberBrep = _solver.BlockCutter_2__TimberBrep
    BlockCutter_2__FaceList = _solver.BlockCutter_2__FaceList
    BlockCutter_2__PointList = _solver.BlockCutter_2__PointList
    BlockCutter_2__EdgeList = _solver.BlockCutter_2__EdgeList
    BlockCutter_2__CenterPoint = _solver.BlockCutter_2__CenterPoint
    BlockCutter_2__CenterAxisLines = _solver.BlockCutter_2__CenterAxisLines
    BlockCutter_2__EdgeMidPoints = _solver.BlockCutter_2__EdgeMidPoints
    BlockCutter_2__FacePlaneList = _solver.BlockCutter_2__FacePlaneList
    BlockCutter_2__Corner0Planes = _solver.BlockCutter_2__Corner0Planes
    BlockCutter_2__LocalAxesPlane = _solver.BlockCutter_2__LocalAxesPlane
    BlockCutter_2__AxisX = _solver.BlockCutter_2__AxisX
    BlockCutter_2__AxisY = _solver.BlockCutter_2__AxisY
    BlockCutter_2__AxisZ = _solver.BlockCutter_2__AxisZ
    BlockCutter_2__FaceDirTags = _solver.BlockCutter_2__FaceDirTags
    BlockCutter_2__EdgeDirTags = _solver.BlockCutter_2__EdgeDirTags
    BlockCutter_2__Corner0EdgeDirs = _solver.BlockCutter_2__Corner0EdgeDirs
    BlockCutter_2__Log = _solver.BlockCutter_2__Log

    GeoAligner_5__SourcePlanePicked = _solver.GeoAligner_5__SourcePlanePicked
    GeoAligner_5__SourcePlanePicked_Log = _solver.GeoAligner_5__SourcePlanePicked_Log
    GeoAligner_5__TargetPlanePicked = _solver.GeoAligner_5__TargetPlanePicked
    GeoAligner_5__TargetPlanePicked_Log = _solver.GeoAligner_5__TargetPlanePicked_Log

    GeoAligner_5__SourceOut = _solver.GeoAligner_5__SourceOut
    GeoAligner_5__TargetOut = _solver.GeoAligner_5__TargetOut
    GeoAligner_5__MovedGeo = _solver.GeoAligner_5__MovedGeo
    GeoAligner_5__TransformOut = _solver.GeoAligner_5__TransformOut
    # -----------------------------
    # Step8 developer-friendly outputs
    # -----------------------------
    ChaAng__CutTimbers = _solver.ChaAng__CutTimbers
    ChaAng__FailTimbers = _solver.ChaAng__FailTimbers
    ChaAng__Log = _solver.ChaAng__Log
    ChaAng__RefPlanes = _solver.ChaAng__RefPlanes
    ChaAng__SolidFace_AE = _solver.ChaAng__SolidFace_AE

    GeoAligner_6__SourcePlanePicked = _solver.GeoAligner_6__SourcePlanePicked
    GeoAligner_6__SourcePlanePicked_Log = _solver.GeoAligner_6__SourcePlanePicked_Log
    GeoAligner_6__TargetPlanePicked = _solver.GeoAligner_6__TargetPlanePicked
    GeoAligner_6__TargetPlanePicked_Log = _solver.GeoAligner_6__TargetPlanePicked_Log

    GeoAligner_6__SourceOut = _solver.GeoAligner_6__SourceOut
    GeoAligner_6__TargetOut = _solver.GeoAligner_6__TargetOut
    GeoAligner_6__MovedGeo = _solver.GeoAligner_6__MovedGeo
    GeoAligner_6__TransformOut = _solver.GeoAligner_6__TransformOut

    CutTimbersByTools_V3_1__CutTimbers = _solver.CutTimbersByTools_V3_1__CutTimbers
    CutTimbersByTools_V3_1__FailTimbers = _solver.CutTimbersByTools_V3_1__FailTimbers
    CutTimbersByTools_V3_1__Log = _solver.CutTimbersByTools_V3_1__Log

    # -----------------------------
    # Step9 developer-friendly outputs
    # -----------------------------
    CutTimbersByTools_V3_2__CutTimbers = _solver.CutTimbersByTools_V3_2__CutTimbers
    CutTimbersByTools_V3_2__FailTimbers = _solver.CutTimbersByTools_V3_2__FailTimbers
    CutTimbersByTools_V3_2__Log = _solver.CutTimbersByTools_V3_2__Log

    PlaneFromLists_4__BasePlane = _solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4__OriginPoint = _solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4__ResultPlane = _solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4__Log = _solver.PlaneFromLists_4__Log

    SplitSectionAnalyzer__SortedVolumes = _solver.SplitSectionAnalyzer__SortedVolumes
    SplitSectionAnalyzer__MaxClosedBrep = _solver.SplitSectionAnalyzer__MaxClosedBrep
    SplitSectionAnalyzer__SectionFaces = _solver.SplitSectionAnalyzer__SectionFaces
    SplitSectionAnalyzer__SectionBrep = _solver.SplitSectionAnalyzer__SectionBrep
    SplitSectionAnalyzer__StableEdgeCurves = _solver.SplitSectionAnalyzer__StableEdgeCurves
    SplitSectionAnalyzer__StableLineSegments = _solver.SplitSectionAnalyzer__StableLineSegments
    SplitSectionAnalyzer__StableMidPoints = _solver.SplitSectionAnalyzer__StableMidPoints
    SplitSectionAnalyzer__MaxMidPoint = _solver.SplitSectionAnalyzer__MaxMidPoint
    SplitSectionAnalyzer__CutterAnglesHV = _solver.SplitSectionAnalyzer__CutterAnglesHV
    SplitSectionAnalyzer__PlaneCutterCurves = _solver.SplitSectionAnalyzer__PlaneCutterCurves
    SplitSectionAnalyzer__PlaneCutterMidPoint = _solver.SplitSectionAnalyzer__PlaneCutterMidPoint
    SplitSectionAnalyzer__Log = _solver.SplitSectionAnalyzer__Log

    RightTrianglePrismBuilder__dist = _solver.RightTrianglePrismBuilder__dist
    RightTrianglePrismBuilder__SectionCurve = _solver.RightTrianglePrismBuilder__SectionCurve
    RightTrianglePrismBuilder__SectionPts = _solver.RightTrianglePrismBuilder__SectionPts
    RightTrianglePrismBuilder__BrepParts = _solver.RightTrianglePrismBuilder__BrepParts
    RightTrianglePrismBuilder__OPlanes = _solver.RightTrianglePrismBuilder__OPlanes
    RightTrianglePrismBuilder__BrepSolid = _solver.RightTrianglePrismBuilder__BrepSolid
    RightTrianglePrismBuilder__Log = _solver.RightTrianglePrismBuilder__Log

    GeoAligner_7__SourceOut = _solver.GeoAligner_7__SourceOut
    GeoAligner_7__TargetOut = _solver.GeoAligner_7__TargetOut
    GeoAligner_7__TargetPlane = _solver.GeoAligner_7__TargetPlane
    GeoAligner_7__MovedGeo = _solver.GeoAligner_7__MovedGeo
    GeoAligner_7__TransformOut = _solver.GeoAligner_7__TransformOut

    CutTimbersByTools_V3_3__CutTimbers = _solver.CutTimbersByTools_V3_3__CutTimbers
    CutTimbersByTools_V3_3__FailTimbers = _solver.CutTimbersByTools_V3_3__FailTimbers
    CutTimbersByTools_V3_3__Log = _solver.CutTimbersByTools_V3_3__Log

    # -----------------------------
    # Step X developer-friendly outputs
    # -----------------------------
    HuaTouZi__SolidBrep = _solver.HuaTouZi__SolidBrep
    HuaTouZi__SectionCrv = _solver.HuaTouZi__SectionCrv
    HuaTouZi__SectionCrv_Pos = _solver.HuaTouZi__SectionCrv_Pos
    HuaTouZi__SectionCrv_Neg = _solver.HuaTouZi__SectionCrv_Neg
    HuaTouZi__LoftBrep = _solver.HuaTouZi__LoftBrep
    HuaTouZi__CapPosBrep = _solver.HuaTouZi__CapPosBrep
    HuaTouZi__CapNegBrep = _solver.HuaTouZi__CapNegBrep
    HuaTouZi__Log = _solver.HuaTouZi__Log
    HuaTouZi__Pts_B = _solver.HuaTouZi__Pts_B
    HuaTouZi__PlaneAtB_X = _solver.HuaTouZi__PlaneAtB_X

    GeoAligner_8__SourceOut = _solver.GeoAligner_8__SourceOut
    GeoAligner_8__TargetOut = _solver.GeoAligner_8__TargetOut
    GeoAligner_8__MovedGeo = _solver.GeoAligner_8__MovedGeo
    GeoAligner_8__TransformOut = _solver.GeoAligner_8__TransformOut

    CutTimbersByTools_V3_4__CutTimbers = _solver.CutTimbersByTools_V3_4__CutTimbers
    CutTimbersByTools_V3_4__FailTimbers = _solver.CutTimbersByTools_V3_4__FailTimbers
    CutTimbersByTools_V3_4__Log = _solver.CutTimbersByTools_V3_4__Log

    cutter_xf = _solver.cutter_xf
    CutTimbers.extend(CutTimbersByTools_V3_1__CutTimbers)

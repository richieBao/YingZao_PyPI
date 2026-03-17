# -*- coding: utf-8 -*-
"""
JiaoAngInLineWJiaoHuaGongSolver (角昂與角華栱相列)
- 单一 GhPython 组件：数据库驱动（DG_Dou 表 / All 导出）
- 当前仅实现：
    Step 1：DBJsonReader 读取 All，并转换为 AllDict
    Step 2：Timber_block_uniform 原始木料构建（build_timber_block_uniform）
- 其余步骤后续按“逐步转换”继续增量加入（本文件已预留结构与变量区）
"""

from __future__ import print_function

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import DBJsonReader
from yingzao.ancientArchi import build_timber_block_uniform
from yingzao.ancientArchi import JuanShaToolBuilder
from yingzao.ancientArchi import FTPlaneFromLists
from yingzao.ancientArchi import GeoAligner_xfm

# Step 12 dependency (HuaTouZi tool)
try:
    from yingzao.ancientArchi import HuaTouZi  # noqa
except Exception:
    HuaTouZi = None

# Step 11 依赖（剖切分析 + 三角棱柱刀具）
try:
    from yingzao.ancientArchi import SplitSectionAnalyzer  # noqa
except Exception:
    SplitSectionAnalyzer = None

try:
    from yingzao.ancientArchi import RightTrianglePrismBuilder  # noqa
except Exception:
    RightTrianglePrismBuilder = None

# Step 9 依赖（角昂/角华栱相列-四铺作 黑盒 + 切割器）
try:
    from yingzao.ancientArchi import ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver  # noqa
except Exception:
    ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver = None

try:
    from yingzao.ancientArchi import FT_CutTimbersByTools_GH_SolidDifference  # noqa
except Exception:
    FT_CutTimbersByTools_GH_SolidDifference = None

# Step 8 依赖（栱眼/工眼：材栔刀具）
try:
    from yingzao.ancientArchi import FT_GongYan_CaiQi_ToolBuilder  # noqa
except Exception:
    FT_GongYan_CaiQi_ToolBuilder = None

# Step 7 可选依赖（起翘刀具）
try:
    from yingzao.ancientArchi import QiAoToolSolver  # noqa
except Exception:
    QiAoToolSolver = None

try:
    from yingzao.ancientArchi import InputHelper, GHPlaneFactory  # noqa
except Exception:
    InputHelper = None
    GHPlaneFactory = None

# Step 6 可选依赖（库中若存在则优先使用；否则使用本文件内置兜底实现）
try:
    from yingzao.ancientArchi import AxisLinesIntersectionsSolver  # noqa
except Exception:
    AxisLinesIntersectionsSolver = None

try:
    from yingzao.ancientArchi import SectionExtrude_SymmetricTrapezoid  # noqa
except Exception:
    SectionExtrude_SymmetricTrapezoid = None

try:
    import Grasshopper.Kernel.Types as ght
except Exception:
    ght = None

try:
    from Grasshopper import DataTree
    from Grasshopper.Kernel.Data import GH_Path
except Exception:
    DataTree = None
    GH_Path = None

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.17"



# ==============================================================
# 通用工具函数（与参考 Solver 风格一致）
# ==============================================================

def to_py_list(x):
    """尽量把 GH 的数据（单值/列表/tuple/可迭代）转成 Python list。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    try:
        # GH / .NET IEnumerable
        return list(x)
    except Exception:
        return [x]


def _list_item(lst, idx, wrap=True):
    """GH List Item 的轻量等价实现（模块级兜底）。

    该文件里多个 Step 会调用 `_list_item`，但并非每个 Step 段落都定义了
    局部 `_list_item`，从而可能触发：`undefined name '_list_item'`。
    这里提供模块级实现，确保任意位置调用都可用。
    """
    l = to_py_list(lst)
    if len(l) == 0:
        return None
    try:
        ii = int(idx)
    except Exception:
        ii = 0
    if wrap:
        ii = ii % len(l)
    if ii < 0 or ii >= len(l):
        return None
    return l[ii]


def flatten_any(x):
    """
    递归拍平 list/tuple/NET List，避免出现：
    System.Collections.Generic.List`1[System.Object] 嵌套套娃
    """
    out = []
    if x is None:
        return out
    # string/Point3d/Brep 等不当作可迭代展开
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]
    try:
        # rhino Brep/Curve 等也不展开
        if isinstance(x, (rg.GeometryBase,)):
            return [x]
    except Exception:
        pass

    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out

    # .NET List / GH_Goo IEnumerable
    try:
        if hasattr(x, "__iter__"):
            for it in x:
                out.extend(flatten_any(it))
            # 若迭代为空，则视为单值
            if len(out) == 0:
                return [x]
            return out
    except Exception:
        pass

    return [x]


def gh_tree_to_list(x, flatten_branches=True):
    """将 Grasshopper.DataTree 转为 Python list。

    说明：
    - 许多 ghpythonlib.components/自定义 align 输出为 DataTree（调试打印常见为 tree {n}）。
    - 但后续 RhinoCommon/自写 cutter 往往只接受 Brep 或 Python list[ Brep ]。
    - 这里按 GH Merge 行为：把各 branch 的元素合并为一个列表（默认扁平一层）。
    """
    if x is None:
        return []
    # DataTree 典型特征：有 Branches/Paths 属性
    if hasattr(x, 'Branches'):
        out = []
        try:
            for br in x.Branches:
                if br is None:
                    continue
                if flatten_branches:
                    out.extend(flatten_any(br))
                else:
                    out.append(list(br))
            return out
        except Exception:
            # 兜底：退回到 to_py_list
            return to_py_list(x)
    return to_py_list(x)


def all_to_dict(all_list):
    """把 All: [(k,v), ...] 转成 dict。"""
    d = {}
    for kv in to_py_list(all_list):
        try:
            k, v = kv
            d[str(k)] = v
        except Exception:
            pass
    return d


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


def make_gh_plane(plane_name, origin_pt):
    """
    参考 GH 默认平面轴向定义（按你的要求）：
    XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  (默认)
    YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    origin_pt = normalize_point3d(origin_pt)
    m = str(plane_name or "").strip().upper().replace(" ", "")

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
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin_pt, x, y)


def _first_not_none(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _is_atomic_value(x):
    """判断是否应视为单值而非可广播列表。"""
    if x is None:
        return True
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return True
    try:
        if isinstance(x, (rg.GeometryBase,)):
            return True
    except Exception:
        pass
    return False


def _as_broadcast_list(x):
    """把输入规范化为可广播的 list（单值 -> [x]；列表/可迭代 -> list(x)）。"""
    if x is None:
        return []
    if _is_atomic_value(x):
        return [x]
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    try:
        return list(x)
    except Exception:
        return [x]


def _broadcast_to_len(lst, n):
    """GH 风格广播：短列表循环重复到 n；空列表 -> [None]*n。"""
    if n <= 0:
        return []
    if lst is None:
        return [None] * n
    if len(lst) == 0:
        return [None] * n
    if len(lst) == n:
        return lst
    if len(lst) == 1:
        return [lst[0]] * n
    return [lst[i % len(lst)] for i in range(n)]


# ==============================================================
# 主 Solver（逐步实现）
# ==============================================================

class JiaoAngInLineWJiaoHuaGongSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1：数据库读取
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step 2：Timber_block_uniform 输出（与 build_timber_block_uniform 命名对齐）
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
        self.TimberLog = []

        # Step 3：Juansha + PlaneFromLists::1 + AlignToolToTimber::1
        self.Juansha__ToolBrep = None
        self.Juansha__SectionEdges = []
        self.Juansha__Intersection = None
        self.Juansha__HeightFacePlane = None
        self.Juansha__LengthFacePlane = None
        self.Juansha__Log = []

        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        self.AlignToolToTimber_1__SourceOut = None
        self.AlignToolToTimber_1__TargetOut = None
        self.AlignToolToTimber_1__MovedGeo = None
        self.AlignToolToTimber_1__TransformOut = None
        self.AlignToolToTimber_1__Log = []

        # Step 4：BlockCutter::1 + ListItemx2 + AlignToolToTimber::2
        self.BlockCutter_1__TimberBrep = None
        self.BlockCutter_1__FacePlaneList = []
        self.BlockCutter_1__EdgeMidPoints = []
        self.BlockCutter_1__Corner0Planes = []
        self.BlockCutter_1__LocalAxesPlane = None
        self.BlockCutter_1__PointList = []
        self.BlockCutter_1__EdgeList = []
        self.BlockCutter_1__FaceList = []
        self.BlockCutter_1__Log = []

        self.ListItem_SourcePlane__Item = None
        self.ListItem_TargetPlane__Item = None

        self.AlignToolToTimber_2__SourceOut = None
        self.AlignToolToTimber_2__TargetOut = None
        self.AlignToolToTimber_2__MovedGeo = None
        self.AlignToolToTimber_2__TransformOut = None
        self.AlignToolToTimber_2__Log = []

        # Step 5：BlockCutter::2 + ListItemx2 + GeoAligner::3
        self.BlockCutter_2__TimberBrep = None
        self.BlockCutter_2__FacePlaneList = []
        self.BlockCutter_2__EdgeMidPoints = []
        self.BlockCutter_2__Corner0Planes = []
        self.BlockCutter_2__LocalAxesPlane = None
        self.BlockCutter_2__PointList = []
        self.BlockCutter_2__EdgeList = []
        self.BlockCutter_2__FaceList = []
        self.BlockCutter_2__Log = []

        self.GeoAligner_3__SourcePlane_Item = None
        self.GeoAligner_3__TargetPlane_Item = None

        self.GeoAligner_3__SourceOut = None
        self.GeoAligner_3__TargetOut = None
        self.GeoAligner_3__MovedGeo = None
        self.GeoAligner_3__TransformOut = None
        self.GeoAligner_3__Log = []

        # Step 6：AxisLinesIntersectionsSolver + SectionExtrude_SymmetricTrapezoid + AlignToolToTimber::4
        # --- AxisLinesIntersectionsSolver outputs ---
        self.AxisLinesIntersectionsSolver__Axis_AO = None
        self.AxisLinesIntersectionsSolver__Axis_AC = None
        self.AxisLinesIntersectionsSolver__Axis_AD = None
        self.AxisLinesIntersectionsSolver__L1 = None
        self.AxisLinesIntersectionsSolver__L2 = None
        self.AxisLinesIntersectionsSolver__L3 = None
        self.AxisLinesIntersectionsSolver__L4 = None
        self.AxisLinesIntersectionsSolver__L5 = None
        self.AxisLinesIntersectionsSolver__L6 = None
        self.AxisLinesIntersectionsSolver__O_out = None
        self.AxisLinesIntersectionsSolver__A = None
        self.AxisLinesIntersectionsSolver__B = None
        self.AxisLinesIntersectionsSolver__J = None
        self.AxisLinesIntersectionsSolver__K = None
        self.AxisLinesIntersectionsSolver__Jp = None
        self.AxisLinesIntersectionsSolver__Kp = None
        self.AxisLinesIntersectionsSolver__Dist_BJ = None
        self.AxisLinesIntersectionsSolver__Dist_JK = None
        self.AxisLinesIntersectionsSolver__Log = []

        # --- SectionExtrude_SymmetricTrapezoid outputs ---
        self.SectionExtrude_SymmetricTrapezoid__A = None
        self.SectionExtrude_SymmetricTrapezoid__B = None
        self.SectionExtrude_SymmetricTrapezoid__C = None
        self.SectionExtrude_SymmetricTrapezoid__D = None
        self.SectionExtrude_SymmetricTrapezoid__O = None
        self.SectionExtrude_SymmetricTrapezoid__E = None
        self.SectionExtrude_SymmetricTrapezoid__Oprime = None
        self.SectionExtrude_SymmetricTrapezoid__AB = None
        self.SectionExtrude_SymmetricTrapezoid__CD = None
        self.SectionExtrude_SymmetricTrapezoid__AC = None
        self.SectionExtrude_SymmetricTrapezoid__BD = None
        self.SectionExtrude_SymmetricTrapezoid__Axis_AC = None
        self.SectionExtrude_SymmetricTrapezoid__section_polyline = None
        self.SectionExtrude_SymmetricTrapezoid__section_curve = None
        self.SectionExtrude_SymmetricTrapezoid__solid_list = []
        self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime = None
        self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_X = None
        self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_Y = None
        self.SectionExtrude_SymmetricTrapezoid__log = []

        # --- AlignToolToTimber::4 outputs ---
        self.AlignToolToTimber_4__TargetPlane_Item = None
        self.AlignToolToTimber_4__SourceOut = None
        self.AlignToolToTimber_4__TargetOut = None
        self.AlignToolToTimber_4__MovedGeo = None
        self.AlignToolToTimber_4__TransformOut = None
        self.AlignToolToTimber_4__Log = []

        # Step 7：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + AlignToolToTimber::5
        self.QiAOTool__CutTimbers = None
        self.QiAOTool__FailTimbers = None
        self.QiAOTool__EdgeMidPoints = []
        self.QiAOTool__Corner0Planes = []
        self.QiAOTool__Log = []

        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        self.AlignToolToTimber_5__SourceOut = None
        self.AlignToolToTimber_5__TargetOut = None
        self.AlignToolToTimber_5__MovedGeo = None
        self.AlignToolToTimber_5__TransformOut = None
        self.AlignToolToTimber_5__Log = []

        # Step 8：GongYan + PlaneFromLists::4 + ListItem + AlignToolToTimber::6
        self.GongYan__ToolBrep = None
        self.GongYan__SectionCurve = None
        self.GongYan__SectionFace = None
        self.GongYan__LeftCurve = None
        self.GongYan__RightCurve = None
        self.GongYan__SymmetryAxis = None
        self.GongYan__AllPoints = None
        self.GongYan__SectionPlanes = None
        self.GongYan__Log = []

        self.PlaneFromLists_4__BasePlane = None
        self.PlaneFromLists_4__OriginPoint = None
        self.PlaneFromLists_4__ResultPlane = None
        self.PlaneFromLists_4__Log = []

        self.AlignToolToTimber_6__SourcePlane_Item = None
        self.AlignToolToTimber_6__SourceOut = None
        self.AlignToolToTimber_6__TargetOut = None
        self.AlignToolToTimber_6__MovedGeo = None
        self.AlignToolToTimber_6__TransformOut = None
        self.AlignToolToTimber_6__Log = []

        # Step 9：ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver + ListItem×2 + AlignToolToTimber::7 + CutTimbersByTools::1
        self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__CutTimbers = None
        self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__FailTimbers = None
        self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log = []
        self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__RefPlanes = None
        self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__SolidFace_AE = None

        self.AlignToolToTimber_7__SourcePlane_Item = None
        self.AlignToolToTimber_7__TargetPlane_Item = None

        self.AlignToolToTimber_7__SourceOut = None
        self.AlignToolToTimber_7__TargetOut = None
        self.AlignToolToTimber_7__MovedGeo = None
        self.AlignToolToTimber_7__TransformOut = None
        self.AlignToolToTimber_7__Log = []

        self.CutTimbersByTools_1__CutTimbers = None
        self.CutTimbersByTools_1__FailTimbers = None
        self.CutTimbersByTools_1__Log = []

        # Step 10：CutTimbersByTools::2（主木坯 + 多刀具合并切割）
        self.CutTimbersByTools_2__CutTimbers = None
        self.CutTimbersByTools_2__FailTimbers = None
        self.CutTimbersByTools_2__Log = []

        # Step 11：SplitSectionAnalyzer + RightTrianglePrismBuilder + AlignToolToTimber::8 + CutTimbersByTools::3
        # --- Step 11A：Transform（SolidFace_AE x AlignToolToTimber::7.TransformOut） ---
        self.Step11_Transform__GeometryIn = None
        self.Step11_Transform__TransformIn = None
        self.Step11_Transform__GeometryOut = None

        # --- Step 11B：SplitSectionAnalyzer ---
        self.SplitSectionAnalyzer__SortedClosedBreps = None
        self.SplitSectionAnalyzer__SortedVolumes = None
        self.SplitSectionAnalyzer__MaxClosedBrep = None
        self.SplitSectionAnalyzer__SectionCurves = None
        self.SplitSectionAnalyzer__SectionFaces = None
        self.SplitSectionAnalyzer__StableEdgeCurves = None
        self.SplitSectionAnalyzer__StableLineSegments = None
        self.SplitSectionAnalyzer__SegmentMidPoints = None
        self.SplitSectionAnalyzer__LowestMidPoint = None
        self.SplitSectionAnalyzer__HighestMidPoint = None
        self.SplitSectionAnalyzer__MinXMidPoint = None
        self.SplitSectionAnalyzer__MaxXMidPoint = None
        self.SplitSectionAnalyzer__MinYMidPoint = None
        self.SplitSectionAnalyzer__MaxYMidPoint = None
        self.SplitSectionAnalyzer__MinZMidPoint = None
        self.SplitSectionAnalyzer__MaxZMidPoint = None
        self.SplitSectionAnalyzer__CutterAnglesHV = None
        self.SplitSectionAnalyzer__PlaneCutterCurves = None
        self.SplitSectionAnalyzer__PlaneCutterMidPoint = None
        self.SplitSectionAnalyzer__PlaneRef_Item = None
        self.SplitSectionAnalyzer__Log = []

        # --- Step 11C：RightTrianglePrismBuilder ---
        self.RightTrianglePrismBuilder__dist = None
        self.RightTrianglePrismBuilder__SectionCurve = None
        self.RightTrianglePrismBuilder__SectionPts = None
        self.RightTrianglePrismBuilder__BrepSolid = None
        self.RightTrianglePrismBuilder__BrepParts = None
        self.RightTrianglePrismBuilder__OPlanes = None
        self.RightTrianglePrismBuilder__Log = []

        # --- Step 11D：ListItem（SourcePlane from OPlanes） ---
        self.AlignToolToTimber_8__SourcePlane_Item = None

        # --- Step 11E：AlignToolToTimber::8 ---
        self.AlignToolToTimber_8__TargetPlane = None
        self.AlignToolToTimber_8__SourceOut = None
        self.AlignToolToTimber_8__TargetOut = None
        self.AlignToolToTimber_8__MovedGeo = None
        self.AlignToolToTimber_8__TransformOut = None
        self.AlignToolToTimber_8__Log = []

        # --- Step 11F：CutTimbersByTools::3 ---
        self.CutTimbersByTools_3__CutTimbers = None
        self.CutTimbersByTools_3__FailTimbers = None
        self.CutTimbersByTools_3__Log = []

        # Step 12: HuaTouZi + AlignToolToTimber::9 + CutTimbersByTools::4
        self.HuaTouZi__SolidBrep = None
        self.HuaTouZi__SectionCrv = None
        self.HuaTouZi__SectionCrv_Pos = None
        self.HuaTouZi__SectionCrv_Neg = None
        self.HuaTouZi__LoftBrep = None
        self.HuaTouZi__CapPosBrep = None
        self.HuaTouZi__CapNegBrep = None
        self.HuaTouZi__Log = []
        self.HuaTouZi__Pts_B = None
        self.HuaTouZi__PlaneAB_X = None

        self.AlignToolToTimber_9__SourceOut = None
        self.AlignToolToTimber_9__TargetOut = None
        self.AlignToolToTimber_9__MovedGeo = None
        self.AlignToolToTimber_9__TransformOut = None
        self.AlignToolToTimber_9__Log = []

        self.CutTimbersByTools_4__CutTimbers = None
        self.CutTimbersByTools_4__FailTimbers = None
        self.CutTimbersByTools_4__Log = []

        # Final outputs（先占位：后续步骤会更新）
        self.CutTimbers = []
        self.FailTimbers = []

    # --------------------------
    # AllDict 取值（优先级：输入端 > DB(AllDict) > 默认）
    # --------------------------
    def all_get(self, key, default=None):
        try:
            if key in self.AllDict:
                v = self.AllDict.get(key, None)
                if v is None:
                    return default
                return v
        except Exception:
            pass
        return default

    def input_get(self, name, default=None):
        """GH 输入端取值（未接线通常为 None）。"""
        try:
            if name in globals():
                v = globals().get(name, None)
                if v is None:
                    return default
                return v
        except Exception:
            pass
        return default

    def get_param(self, input_name, db_key, default=None):
        """参数优先级：GH 输入端 > AllDict(数据库) > default。"""
        v_in = self.input_get(input_name, None)
        if v_in is not None:
            return v_in
        return self.all_get(db_key, default)

    # --------------------------
    # Step 1：读库（DG_Dou / type_code=JiaoAngInLineWJiaoHuaGong / params_json / ExportAll=True）
    # --------------------------
    def step1_read_db(self):
        cache_key = "YingZaoLab::JiaoAngInLineWJiaoHuaGong::AllCache::{}".format(self.DBPath)

        use_cache = True
        try:
            use_cache = (not bool(self.Refresh))
        except Exception:
            use_cache = True

        if use_cache and cache_key in sc.sticky:
            try:
                cached = sc.sticky.get(cache_key, None)
                if cached:
                    self.Value = cached.get("Value", None)
                    self.All = cached.get("All", None)
                    self.AllDict = cached.get("AllDict", {}) or {}
                    self.DBLog = cached.get("DBLog", []) or []
                    self.Log.append("[Step1] use sticky cache: {}".format(cache_key))
                    return
            except Exception:
                pass

        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="JiaoAngInLineWJiaoHuaGong",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            v, all_list, log_lines = reader.run()
            self.Value = v
            self.All = all_list
            self.DBLog = to_py_list(log_lines)
            self.AllDict = all_to_dict(all_list)

            sc.sticky[cache_key] = {
                "Value": self.Value,
                "All": self.All,
                "AllDict": self.AllDict,
                "DBLog": self.DBLog
            }
            self.Log.append("[Step1] DB read ok. All count={}".format(len(to_py_list(self.All))))

        except Exception as e:
            self.Value = None
            self.All = []
            self.AllDict = {}
            self.DBLog = ["[Step1][ERROR] {}".format(e)]
            self.Log.extend(self.DBLog)

    # --------------------------
    # Step 2：Timber_block_uniform
    # --------------------------
    def step2_build_timber(self):
        # 取参数（DB键名对齐 All 规则）
        length_fen = self.all_get("Timber_block_uniform__length_fen", 32.0)
        width_fen = self.all_get("Timber_block_uniform__width_fen", 32.0)
        height_fen = self.all_get("Timber_block_uniform__height_fen", 20.0)

        # base_point：输入端优先；否则 DB；否则原点
        db_bp = self.all_get("Timber_block_uniform__base_point", None)
        bp = _first_not_none(self.base_point, db_bp, rg.Point3d(0.0, 0.0, 0.0))
        bp = normalize_point3d(bp)

        # reference_plane：默认 GH XZ Plane；若 DB 指定则用 DB
        rp_name = self.all_get("Timber_block_uniform__reference_plane", "WorldXZ")
        ref_plane = make_gh_plane(rp_name, bp)

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
                ref_plane,
            )

            self.TimberBrep = timber_brep
            self.FaceList = flatten_any(faces)
            self.PointList = flatten_any(points)
            self.EdgeList = flatten_any(edges)
            self.CenterPoint = center_pt
            self.CenterAxisLines = flatten_any(center_axes)
            self.EdgeMidPoints = flatten_any(edge_midpts)
            self.FacePlaneList = flatten_any(face_planes)
            self.Corner0Planes = flatten_any(corner0_planes)
            self.LocalAxesPlane = local_axes_plane
            self.AxisX = axis_x
            self.AxisY = axis_y
            self.AxisZ = axis_z
            self.FaceDirTags = flatten_any(face_tags)
            self.EdgeDirTags = flatten_any(edge_tags)
            self.Corner0EdgeDirs = flatten_any(corner0_dirs)
            self.TimberLog = to_py_list(log_lines)

            self.Log.append("[Step2] Timber_block_uniform ok.")

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
            self.TimberLog = ["[Step2][ERROR] {}".format(e)]
            self.Log.extend(self.TimberLog)

    # --------------------------
    # Step 3：Juansha + PlaneFromLists::1 + AlignToolToTimber::1
    # --------------------------
    def step3_juansha_plane_align(self):
        # ========== Step A：Juansha ==========
        try:
            h_fen = self.get_param("Juansha__HeightFen", "Juansha__HeightFen", 9)
            l_fen = self.get_param("Juansha__LengthFen", "Juansha__LengthFen", 16)
            div_c = self.get_param("Juansha__DivCount", "Juansha__DivCount", 4)
            t_fen = self.get_param("Juansha__ThicknessFen", "Juansha__ThicknessFen", 10)

            # 与旧 Solver 一致：PositionPoint=原点；SectionPlane=None（或输入端提供）
            pos_pt = self.get_param("Juansha__PositionPoint", "Juansha__PositionPoint", rg.Point3d(0.0, 0.0, 0.0))
            pos_pt = normalize_point3d(pos_pt)
            sec_pl = self.get_param("Juansha__SectionPlane", "Juansha__SectionPlane", None)

            builder = JuanShaToolBuilder(
                height_fen=h_fen,
                length_fen=l_fen,
                thickness_fen=t_fen,
                div_count=div_c,
                section_plane=sec_pl,
                position_point=pos_pt
            )
            tool_brep, section_edges, hl_intersection, height_face_plane, length_face_plane, log_lines = builder.build()

            self.Juansha__ToolBrep = tool_brep
            self.Juansha__SectionEdges = flatten_any(section_edges)
            self.Juansha__Intersection = hl_intersection
            self.Juansha__HeightFacePlane = height_face_plane
            self.Juansha__LengthFacePlane = length_face_plane
            self.Juansha__Log = to_py_list(log_lines)
            self.Log.append("[Step3A] Juansha ok.")

        except Exception as e:
            self.Juansha__ToolBrep = None
            self.Juansha__SectionEdges = []
            self.Juansha__Intersection = None
            self.Juansha__HeightFacePlane = None
            self.Juansha__LengthFacePlane = None
            self.Juansha__Log = ["[Step3A][ERROR] {}".format(e)]
            self.Log.extend(self.Juansha__Log)

        # ========== Step B：PlaneFromLists::1 ==========
        try:
            idx_origin_in = self.get_param("PlaneFromLists_1__IndexOrigin", "PlaneFromLists_1__IndexOrigin", 9)
            idx_plane_in = self.get_param("PlaneFromLists_1__IndexPlane", "PlaneFromLists_1__IndexPlane", 1)
            wrap_in = self.get_param("PlaneFromLists_1__Wrap", "PlaneFromLists_1__Wrap", True)

            origin_pts = flatten_any(self.EdgeMidPoints)
            base_planes = flatten_any(self.Corner0Planes)

            idx_origin_l = _as_broadcast_list(idx_origin_in)
            idx_plane_l = _as_broadcast_list(idx_plane_in)
            max_len = max(len(idx_origin_l), len(idx_plane_l), 1)
            idx_origin_l = _broadcast_to_len(idx_origin_l, max_len)
            idx_plane_l = _broadcast_to_len(idx_plane_l, max_len)

            builder = FTPlaneFromLists(wrap=bool(wrap_in))
            base_out_list = []
            org_out_list = []
            res_out_list = []
            log_all = []

            for io, ip in zip(idx_origin_l, idx_plane_l):
                bp, op, rp, lg = builder.build_plane(origin_pts, base_planes, io, ip)
                base_out_list.append(bp)
                org_out_list.append(op)
                res_out_list.append(rp)
                log_all.extend(to_py_list(lg))

            # GH 习惯：若最终仅一个值，则输出单值；否则输出列表
            self.PlaneFromLists_1__BasePlane = base_out_list[0] if len(base_out_list) == 1 else base_out_list
            self.PlaneFromLists_1__OriginPoint = org_out_list[0] if len(org_out_list) == 1 else org_out_list
            self.PlaneFromLists_1__ResultPlane = res_out_list[0] if len(res_out_list) == 1 else res_out_list
            self.PlaneFromLists_1__Log = log_all
            self.Log.append("[Step3B] PlaneFromLists::1 ok.")

        except Exception as e:
            self.PlaneFromLists_1__BasePlane = None
            self.PlaneFromLists_1__OriginPoint = None
            self.PlaneFromLists_1__ResultPlane = None
            self.PlaneFromLists_1__Log = ["[Step3B][ERROR] {}".format(e)]
            self.Log.extend(self.PlaneFromLists_1__Log)

        # ========== Step C：AlignToolToTimber::1 ==========
        try:
            target_pl = self.PlaneFromLists_1__ResultPlane
            target_list = _as_broadcast_list(target_pl)
            max_len = max(len(target_list), 1)

            rot_in = self.get_param("AlignToolToTimber_1__RotateDeg", "AlignToolToTimber_1__RotateDeg", 90)
            flipy_in = self.get_param("AlignToolToTimber_1__FlipY", "AlignToolToTimber_1__FlipY", False)

            rot_list = _broadcast_to_len(_as_broadcast_list(rot_in), max_len)
            flipy_list = _broadcast_to_len(_as_broadcast_list(flipy_in), max_len)

            moved_list = []
            xfm_list = []
            src_out_list = []
            tgt_out_list = []
            log_all = []

            for i in range(max_len):
                _tgt = target_list[i] if len(target_list) > 0 else None
                _rot = rot_list[i]
                _fy = flipy_list[i]
                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    self.Juansha__ToolBrep,
                    self.Juansha__LengthFacePlane,
                    _tgt,
                    rotate_deg=_rot,
                    flip_x=False,
                    flip_y=_fy,
                    flip_z=False,
                    move_x=0.0,
                    move_y=0.0,
                    move_z=0.0,
                )
                src_out_list.append(src_out)
                tgt_out_list.append(tgt_out)
                xfm_list.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                moved_list.append(moved_geo)
                # GeoAligner_xfm.align 当前无 Log 输出；保持接口统一

            self.AlignToolToTimber_1__SourceOut = src_out_list[0] if len(src_out_list) == 1 else src_out_list
            self.AlignToolToTimber_1__TargetOut = tgt_out_list[0] if len(tgt_out_list) == 1 else tgt_out_list
            self.AlignToolToTimber_1__TransformOut = xfm_list[0] if len(xfm_list) == 1 else xfm_list
            self.AlignToolToTimber_1__MovedGeo = moved_list[0] if len(moved_list) == 1 else moved_list
            self.AlignToolToTimber_1__Log = log_all
            self.Log.append("[Step3C] AlignToolToTimber::1 ok.")

        except Exception as e:
            self.AlignToolToTimber_1__SourceOut = None
            self.AlignToolToTimber_1__TargetOut = None
            self.AlignToolToTimber_1__MovedGeo = None
            self.AlignToolToTimber_1__TransformOut = None
            self.AlignToolToTimber_1__Log = ["[Step3C][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_1__Log)

    # --------------------------
    # Step 4：BlockCutter::1 + ListItemx2 + AlignToolToTimber::2
    # --------------------------
    def step4_blockcutter_aligntool(self):
        """Generate tool timber block(s) and align each branch to the main timber face."""

        # ========== Step 4A：BlockCutter::1（支持 length/width/height 广播生成多个分支） ==========
        try:
            len_in = self.get_param("BlockCutter_1__length_fen", "BlockCutter_1__length_fen", 32.0)
            wid_in = self.get_param("BlockCutter_1__width_fen", "BlockCutter_1__width_fen", 32.0)
            hei_in = self.get_param("BlockCutter_1__height_fen", "BlockCutter_1__height_fen", 20.0)

            len_l = _as_broadcast_list(len_in)
            wid_l = _as_broadcast_list(wid_in)
            hei_l = _as_broadcast_list(hei_in)
            n = max(len(len_l), len(wid_l), len(hei_l), 1)
            len_l = _broadcast_to_len(len_l, n)
            wid_l = _broadcast_to_len(wid_l, n)
            hei_l = _broadcast_to_len(hei_l, n)

            bp = normalize_point3d(_first_not_none(self.base_point, rg.Point3d(0.0, 0.0, 0.0)))
            rp_name = self.get_param("BlockCutter_1__reference_plane", "BlockCutter_1__reference_plane", "WorldXZ")
            ref_plane = make_gh_plane(rp_name, bp)

            tool_breps = []
            face_planes_all = []
            edge_midpts_all = []
            corner0_planes_all = []
            local_axes_all = []
            faces_all = []
            points_all = []
            edges_all = []
            log_all = []

            for i in range(n):
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
                    float(len_l[i]),
                    float(wid_l[i]),
                    float(hei_l[i]),
                    bp,
                    ref_plane,
                )

                tool_breps.append(timber_brep)
                faces_all.append(flatten_any(faces))
                points_all.append(flatten_any(points))
                edges_all.append(flatten_any(edges))
                edge_midpts_all.append(flatten_any(edge_midpts))
                face_planes_all.append(flatten_any(face_planes))
                corner0_planes_all.append(flatten_any(corner0_planes))
                local_axes_all.append(local_axes_plane)
                log_all.extend(to_py_list(log_lines))

            # TimberBrep 强制为 Tree（每分支一个 Brep）；无 GH 时退化为 list
            if DataTree is not None and GH_Path is not None:
                geo_tree = DataTree[object]()
                for i, b in enumerate(tool_breps):
                    geo_tree.Add(b, GH_Path(i))
                self.BlockCutter_1__TimberBrep = geo_tree
            else:
                self.BlockCutter_1__TimberBrep = tool_breps

            self.BlockCutter_1__FacePlaneList = face_planes_all[0] if n == 1 else face_planes_all
            self.BlockCutter_1__EdgeMidPoints = edge_midpts_all[0] if n == 1 else edge_midpts_all
            self.BlockCutter_1__Corner0Planes = corner0_planes_all[0] if n == 1 else corner0_planes_all
            self.BlockCutter_1__LocalAxesPlane = local_axes_all[0] if n == 1 else local_axes_all
            self.BlockCutter_1__FaceList = faces_all[0] if n == 1 else faces_all
            self.BlockCutter_1__PointList = points_all[0] if n == 1 else points_all
            self.BlockCutter_1__EdgeList = edges_all[0] if n == 1 else edges_all
            self.BlockCutter_1__Log = log_all

            self.Log.append("[Step4A] BlockCutter::1 ok.")

        except Exception as e:
            self.BlockCutter_1__TimberBrep = None
            self.BlockCutter_1__FacePlaneList = []
            self.BlockCutter_1__EdgeMidPoints = []
            self.BlockCutter_1__Corner0Planes = []
            self.BlockCutter_1__LocalAxesPlane = None
            self.BlockCutter_1__PointList = []
            self.BlockCutter_1__EdgeList = []
            self.BlockCutter_1__FaceList = []
            self.BlockCutter_1__Log = ["[Step4A][ERROR] {}".format(e)]
            self.Log.extend(self.BlockCutter_1__Log)
            return

        # ========== Step 4B：List Item x2（SourcePlane / TargetPlane） ==========
        def _list_item(lst, idx, wrap=True):
            l = to_py_list(lst)
            if len(l) == 0:
                return None
            try:
                ii = int(idx)
            except Exception:
                ii = 0
            if wrap:
                ii = ii % len(l)
            if ii < 0 or ii >= len(l):
                return None
            return l[ii]

        try:
            src_idx = self.get_param("AlignToolToTimber_2__SourcePlane", "AlignToolToTimber_2__SourcePlane", 0)
            tgt_idx = self.get_param("AlignToolToTimber_2__TargetPlane", "AlignToolToTimber_2__TargetPlane", 0)
            wrap_src = self.get_param("ListItem_SourcePlane__Wrap", "ListItem_SourcePlane__Wrap", True)
            wrap_tgt = self.get_param("ListItem_TargetPlane__Wrap", "ListItem_TargetPlane__Wrap", True)

            src_planes_all = self.BlockCutter_1__FacePlaneList

            # 如果多块输出为 list-of-lists，则按块广播索引后逐块取 plane
            if isinstance(src_planes_all, list) and len(src_planes_all) > 0 and isinstance(src_planes_all[0], list):
                src_idx_l = _broadcast_to_len(_as_broadcast_list(src_idx), len(src_planes_all))
                src_sel = []
                for planes_i, ii in zip(src_planes_all, src_idx_l):
                    src_sel.append(_list_item(planes_i, ii, bool(wrap_src)))
                self.ListItem_SourcePlane__Item = src_sel[0] if len(src_sel) == 1 else src_sel
            else:
                self.ListItem_SourcePlane__Item = _list_item(src_planes_all, src_idx, bool(wrap_src))

            self.ListItem_TargetPlane__Item = _list_item(self.FacePlaneList, tgt_idx, bool(wrap_tgt))

            self.Log.append("[Step4B] ListItem x2 ok.")

        except Exception as e:
            self.ListItem_SourcePlane__Item = None
            self.ListItem_TargetPlane__Item = None
            self.Log.append("[Step4B][ERROR] {}".format(e))

        # ========== Step 4C：AlignToolToTimber::2（Tree 分支循环，对齐并保留路径） ==========
        try:
            geo_in = self.BlockCutter_1__TimberBrep

            paths = []
            geos = []
            if DataTree is not None and hasattr(geo_in, "Paths") and hasattr(geo_in, "Branch"):
                for p in geo_in.Paths:
                    br = geo_in.Branch(p)
                    g0 = br[0] if (br and len(br) > 0) else None
                    paths.append(p)
                    geos.append(g0)
            else:
                geos = to_py_list(geo_in)
                paths = [i for i in range(len(geos))]

            n_branch = max(len(geos), 1)

            src_item_l = _broadcast_to_len(_as_broadcast_list(self.ListItem_SourcePlane__Item), n_branch)
            tgt_item_l = _broadcast_to_len(_as_broadcast_list(self.ListItem_TargetPlane__Item), n_branch)

            rot_in = self.get_param("AlignToolToTimber_2__RotateDeg", "AlignToolToTimber_2__RotateDeg", None)
            fx_in = self.get_param("AlignToolToTimber_2__FlipX", "AlignToolToTimber_2__FlipX", False)
            fy_in = self.get_param("AlignToolToTimber_2__FlipY", "AlignToolToTimber_2__FlipY", False)
            fz_in = self.get_param("AlignToolToTimber_2__FlipZ", "AlignToolToTimber_2__FlipZ", False)
            mx_in = self.get_param("AlignToolToTimber_2__MoveX", "AlignToolToTimber_2__MoveX", 0.0)
            my_in = self.get_param("AlignToolToTimber_2__MoveY", "AlignToolToTimber_2__MoveY", 0.0)
            mz_in = self.get_param("AlignToolToTimber_2__MoveZ", "AlignToolToTimber_2__MoveZ", 0.0)

            rot_l = _broadcast_to_len(_as_broadcast_list(rot_in), n_branch)
            fx_l = _broadcast_to_len(_as_broadcast_list(fx_in), n_branch)
            fy_l = _broadcast_to_len(_as_broadcast_list(fy_in), n_branch)
            fz_l = _broadcast_to_len(_as_broadcast_list(fz_in), n_branch)
            mx_l = _broadcast_to_len(_as_broadcast_list(mx_in), n_branch)
            my_l = _broadcast_to_len(_as_broadcast_list(my_in), n_branch)
            mz_l = _broadcast_to_len(_as_broadcast_list(mz_in), n_branch)

            if DataTree is not None and GH_Path is not None:
                moved_tree = DataTree[object]()
                xfm_tree = DataTree[object]()
                src_out_tree = DataTree[object]()
                tgt_out_tree = DataTree[object]()
            else:
                moved_tree, xfm_tree, src_out_tree, tgt_out_tree = [], [], [], []

            log_all = []

            for i in range(n_branch):
                g = geos[i]
                sp = src_item_l[i]
                tp = tgt_item_l[i]

                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rot_l[i],
                    flip_x=bool(fx_l[i]),
                    flip_y=bool(fy_l[i]),
                    flip_z=bool(fz_l[i]),
                    move_x=float(mx_l[i]) if mx_l[i] is not None else 0.0,
                    move_y=float(my_l[i]) if my_l[i] is not None else 0.0,
                    move_z=float(mz_l[i]) if mz_l[i] is not None else 0.0,
                )

                # NOTE: GeoAligner_xfm.align 可能返回 list/tuple 甚至多层嵌套（如 [Brep] / [[Brep]]）。
                # 这里将 list/tuple 递归拍平；若仅 1 个元素，则取该元素，保证每分支尽量为单个 Brep。
                _moved_flat = flatten_any(moved_geo)
                if len(_moved_flat) == 1:
                    moved_geo = _moved_flat[0]
                elif len(_moved_flat) > 1:
                    moved_geo = _moved_flat

                if DataTree is not None and GH_Path is not None:
                    pth = paths[i] if not isinstance(paths[i], int) else GH_Path(paths[i])
                    moved_tree.Add(moved_geo, pth)
                    xfm_tree.Add(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out, pth)
                    src_out_tree.Add(src_out, pth)
                    tgt_out_tree.Add(tgt_out, pth)
                else:
                    moved_tree.append(moved_geo)
                    xfm_tree.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                    src_out_tree.append(src_out)
                    tgt_out_tree.append(tgt_out)

                log_all.append("[path {}] align ok".format(paths[i]))

            # --- final_output_normalize: 若非 DataTree 环境，可能输出为 [Brep] / [[Brep]]，这里统一递归拍平并尽量拆单值 ---
            def _norm_out(_x):
                if isinstance(_x, (list, tuple)):
                    _flat = flatten_any(_x)
                    return _flat[0] if len(_flat) == 1 else _flat
                return _x

            if not (DataTree is not None and GH_Path is not None and hasattr(moved_tree, 'Paths')):
                moved_tree = _norm_out(moved_tree)
                xfm_tree = _norm_out(xfm_tree)
                src_out_tree = _norm_out(src_out_tree)
                tgt_out_tree = _norm_out(tgt_out_tree)

            # NOTE: tools 端口需要“能参与裁切”的 Brep 或 list[Brep]。
            # 在 GH 环境下 moved_tree 往往是 DataTree（打印为 tree {n}），这里按 Merge 规则扁平一层。
            _moved_list = gh_tree_to_list(moved_tree, flatten_branches=True)
            _moved_out = _moved_list[0] if len(_moved_list) == 1 else _moved_list
            self.AlignToolToTimber_2__MovedGeo = _moved_out
            self.AlignToolToTimber_2__TransformOut = xfm_tree
            self.AlignToolToTimber_2__SourceOut = src_out_tree
            self.AlignToolToTimber_2__TargetOut = tgt_out_tree
            self.AlignToolToTimber_2__Log = log_all

            self.Log.append("[Step4C] AlignToolToTimber::2 ok.")

        except Exception as e:
            self.AlignToolToTimber_2__SourceOut = None
            self.AlignToolToTimber_2__TargetOut = None
            self.AlignToolToTimber_2__MovedGeo = None
            self.AlignToolToTimber_2__TransformOut = None
            self.AlignToolToTimber_2__Log = ["[Step4C][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_2__Log)

    # --------------------------
    # Step 5：BlockCutter::2 + ListItemx2 + GeoAligner::3
    # --------------------------
    def step5_blockcutter2_geoaligner3(self):
        """Generate 2nd tool timber block(s) and align to target plane(s) using GeoAligner_xfm."""

        # ========== Step 5A：BlockCutter::2（支持 length/width/height 广播生成多个块） ==========
        try:
            len_in = self.get_param("BlockCutter_2__length_fen", "BlockCutter_2__length_fen", 32.0)
            wid_in = self.get_param("BlockCutter_2__width_fen", "BlockCutter_2__width_fen", 32.0)
            hei_in = self.get_param("BlockCutter_2__height_fen", "BlockCutter_2__height_fen", 20.0)

            len_l = _as_broadcast_list(len_in)
            wid_l = _as_broadcast_list(wid_in)
            hei_l = _as_broadcast_list(hei_in)
            n = max(len(len_l), len(wid_l), len(hei_l), 1)
            len_l = _broadcast_to_len(len_l, n)
            wid_l = _broadcast_to_len(wid_l, n)
            hei_l = _broadcast_to_len(hei_l, n)

            bp = normalize_point3d(_first_not_none(self.base_point, rg.Point3d(0.0, 0.0, 0.0)))
            rp_name = self.get_param("BlockCutter_2__reference_plane", "BlockCutter_2__reference_plane", "WorldXZ")
            ref_plane = make_gh_plane(rp_name, bp)

            tool_breps = []
            face_planes_all = []
            edge_midpts_all = []
            corner0_planes_all = []
            local_axes_all = []
            faces_all = []
            points_all = []
            edges_all = []
            log_all = []

            for i in range(n):
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
                    float(len_l[i]),
                    float(wid_l[i]),
                    float(hei_l[i]),
                    bp,
                    ref_plane,
                )

                tool_breps.append(timber_brep)
                faces_all.append(flatten_any(faces))
                points_all.append(flatten_any(points))
                edges_all.append(flatten_any(edges))
                edge_midpts_all.append(flatten_any(edge_midpts))
                face_planes_all.append(flatten_any(face_planes))
                corner0_planes_all.append(flatten_any(corner0_planes))
                local_axes_all.append(local_axes_plane)
                log_all.extend(to_py_list(log_lines))

            # 这里按提示：GeoAligner::3 输入为 list（无需 Tree）；若你后续需要 Tree，可在下游再包装
            self.BlockCutter_2__TimberBrep = tool_breps[0] if n == 1 else tool_breps
            self.BlockCutter_2__FacePlaneList = face_planes_all[0] if n == 1 else face_planes_all
            self.BlockCutter_2__EdgeMidPoints = edge_midpts_all[0] if n == 1 else edge_midpts_all
            self.BlockCutter_2__Corner0Planes = corner0_planes_all[0] if n == 1 else corner0_planes_all
            self.BlockCutter_2__LocalAxesPlane = local_axes_all[0] if n == 1 else local_axes_all
            self.BlockCutter_2__FaceList = faces_all[0] if n == 1 else faces_all
            self.BlockCutter_2__PointList = points_all[0] if n == 1 else points_all
            self.BlockCutter_2__EdgeList = edges_all[0] if n == 1 else edges_all
            self.BlockCutter_2__Log = log_all

            self.Log.append("[Step5A] BlockCutter::2 ok.")

        except Exception as e:
            self.BlockCutter_2__TimberBrep = None
            self.BlockCutter_2__FacePlaneList = []
            self.BlockCutter_2__EdgeMidPoints = []
            self.BlockCutter_2__Corner0Planes = []
            self.BlockCutter_2__LocalAxesPlane = None
            self.BlockCutter_2__PointList = []
            self.BlockCutter_2__EdgeList = []
            self.BlockCutter_2__FaceList = []
            self.BlockCutter_2__Log = ["[Step5A][ERROR] {}".format(e)]
            self.Log.extend(self.BlockCutter_2__Log)
            return

        # ========== Step 5B：List Item x2（SourcePlane / TargetPlane） ==========
        def _list_item(lst, idx, wrap=True):
            l = to_py_list(lst)
            if len(l) == 0:
                return None
            try:
                ii = int(idx)
            except Exception:
                ii = 0
            if wrap:
                ii = ii % len(l)
            if ii < 0 or ii >= len(l):
                return None
            return l[ii]

        try:
            src_idx = self.get_param("GeoAligner_3__SourcePlane", "GeoAligner_3__SourcePlane", 0)
            tgt_idx = self.get_param("GeoAligner_3__TargetPlane", "GeoAligner_3__TargetPlane", 0)
            wrap_src = self.get_param("GeoAligner_3__SourceWrap", "GeoAligner_3__SourceWrap", True)
            wrap_tgt = self.get_param("GeoAligner_3__TargetWrap", "GeoAligner_3__TargetWrap", True)

            src_planes_all = self.BlockCutter_2__FacePlaneList

            # 允许多块：list-of-lists
            if isinstance(src_planes_all, list) and len(src_planes_all) > 0 and isinstance(src_planes_all[0], list):
                src_idx_l = _broadcast_to_len(_as_broadcast_list(src_idx), len(src_planes_all))
                src_sel = []
                for planes_i, ii in zip(src_planes_all, src_idx_l):
                    src_sel.append(_list_item(planes_i, ii, bool(wrap_src)))
                self.GeoAligner_3__SourcePlane_Item = src_sel[0] if len(src_sel) == 1 else src_sel
            else:
                self.GeoAligner_3__SourcePlane_Item = _list_item(src_planes_all, src_idx, bool(wrap_src))

            self.GeoAligner_3__TargetPlane_Item = _list_item(self.FacePlaneList, tgt_idx, bool(wrap_tgt))

            self.Log.append("[Step5B] ListItem x2 ok.")

        except Exception as e:
            self.GeoAligner_3__SourcePlane_Item = None
            self.GeoAligner_3__TargetPlane_Item = None
            self.Log.append("[Step5B][ERROR] {}".format(e))

        # ========== Step 5C：GeoAligner::3（广播对齐计算） ==========
        try:
            geos = _as_broadcast_list(self.BlockCutter_2__TimberBrep)
            # 注意：如果 BlockCutter_2__TimberBrep 是单个 Brep，上面会变成 [Brep]

            src_l = _as_broadcast_list(self.GeoAligner_3__SourcePlane_Item)
            tgt_l = _as_broadcast_list(self.GeoAligner_3__TargetPlane_Item)

            rot_in = self.get_param("GeoAligner_3__RotateDeg", "GeoAligner_3__RotateDeg", None)
            fx_in = self.get_param("GeoAligner_3__FlipX", "GeoAligner_3__FlipX", False)
            fy_in = self.get_param("GeoAligner_3__FlipY", "GeoAligner_3__FlipY", False)
            fz_in = self.get_param("GeoAligner_3__FlipZ", "GeoAligner_3__FlipZ", False)
            mx_in = self.get_param("GeoAligner_3__MoveX", "GeoAligner_3__MoveX", 0.0)
            my_in = self.get_param("GeoAligner_3__MoveY", "GeoAligner_3__MoveY", 0.0)
            mz_in = self.get_param("GeoAligner_3__MoveZ", "GeoAligner_3__MoveZ", 0.0)

            rot_l = _as_broadcast_list(rot_in)
            fx_l = _as_broadcast_list(fx_in)
            fy_l = _as_broadcast_list(fy_in)
            fz_l = _as_broadcast_list(fz_in)
            mx_l = _as_broadcast_list(mx_in)
            my_l = _as_broadcast_list(my_in)
            mz_l = _as_broadcast_list(mz_in)

            # GH 广播：以最长列表长度为基准；若全是单值，则以 geo 数量为基准
            n = max(len(geos), len(src_l), len(tgt_l), len(rot_l), len(fx_l), len(fy_l), len(fz_l), len(mx_l),
                    len(my_l), len(mz_l), 1)

            geos = _broadcast_to_len(geos, n)
            src_l = _broadcast_to_len(src_l, n)
            tgt_l = _broadcast_to_len(tgt_l, n)
            rot_l = _broadcast_to_len(rot_l, n)
            fx_l = _broadcast_to_len(fx_l, n)
            fy_l = _broadcast_to_len(fy_l, n)
            fz_l = _broadcast_to_len(fz_l, n)
            mx_l = _broadcast_to_len(mx_l, n)
            my_l = _broadcast_to_len(my_l, n)
            mz_l = _broadcast_to_len(mz_l, n)

            moved_list = []
            xfm_list = []
            src_out_list = []
            tgt_out_list = []
            log_all = []

            for i in range(n):
                g = geos[i]
                sp = src_l[i]
                tp = tgt_l[i]

                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rot_l[i],
                    flip_x=bool(fx_l[i]),
                    flip_y=bool(fy_l[i]),
                    flip_z=bool(fz_l[i]),
                    move_x=float(mx_l[i]) if mx_l[i] is not None else 0.0,
                    move_y=float(my_l[i]) if my_l[i] is not None else 0.0,
                    move_z=float(mz_l[i]) if mz_l[i] is not None else 0.0,
                )

                # moved_geo 递归拍平并尽量拆单值
                _moved_flat = flatten_any(moved_geo)
                if len(_moved_flat) == 1:
                    moved_geo = _moved_flat[0]
                elif len(_moved_flat) > 1:
                    moved_geo = _moved_flat

                moved_list.append(moved_geo)
                xfm_list.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                src_out_list.append(src_out)
                tgt_out_list.append(tgt_out)
                log_all.append("[i {}] geoalign ok".format(i))

            # GH 习惯：若仅一个值则拆单
            self.GeoAligner_3__MovedGeo = moved_list[0] if len(moved_list) == 1 else moved_list
            self.GeoAligner_3__TransformOut = xfm_list[0] if len(xfm_list) == 1 else xfm_list
            self.GeoAligner_3__SourceOut = src_out_list[0] if len(src_out_list) == 1 else src_out_list
            self.GeoAligner_3__TargetOut = tgt_out_list[0] if len(tgt_out_list) == 1 else tgt_out_list
            self.GeoAligner_3__Log = log_all

            self.Log.append("[Step5C] GeoAligner::3 ok.")

        except Exception as e:
            self.GeoAligner_3__SourceOut = None
            self.GeoAligner_3__TargetOut = None
            self.GeoAligner_3__MovedGeo = None
            self.GeoAligner_3__TransformOut = None
            self.GeoAligner_3__Log = ["[Step5C][ERROR] {}".format(e)]
            self.Log.extend(self.GeoAligner_3__Log)

    # --------------------------
    # Step 6：AxisLinesIntersectionsSolver + SectionExtrude_SymmetricTrapezoid + AlignToolToTimber::4
    # --------------------------
    def step6_axis_section_align(self):
        """Axis intersection -> symmetric trapezoid section extrude -> align to main timber."""

        # -------------------------------------------------
        # Step 6A：AxisLinesIntersectionsSolver（优先用库；否则用内置实现）
        # -------------------------------------------------
        try:
            # Params (GH input > AllDict > default)
            O_in = self.get_param("AxisLinesIntersectionsSolver__O", "AxisLinesIntersectionsSolver__O",
                                  rg.Point3d(0.0, 0.0, 0.0))
            RefPlane_in = self.get_param("AxisLinesIntersectionsSolver__RefPlane",
                                         "AxisLinesIntersectionsSolver__RefPlane", None)
            d_in = self.get_param("AxisLinesIntersectionsSolver__d", "AxisLinesIntersectionsSolver__d", 5.0)
            L12_len_in = self.get_param("AxisLinesIntersectionsSolver__L12_len",
                                        "AxisLinesIntersectionsSolver__L12_len", 96.84)
            L36_len_in = self.get_param("AxisLinesIntersectionsSolver__L36_len",
                                        "AxisLinesIntersectionsSolver__L36_len", 100.0)
            alpha_deg_in = self.get_param("AxisLinesIntersectionsSolver__alpha_deg",
                                          "AxisLinesIntersectionsSolver__alpha_deg", 45.0)
            axis_len_in = self.get_param("AxisLinesIntersectionsSolver__axis_len",
                                         "AxisLinesIntersectionsSolver__axis_len", 100.0)

            O = normalize_point3d(O_in)

            ref_plane = RefPlane_in if isinstance(RefPlane_in, rg.Plane) else make_gh_plane("WorldXY", O)
            axis_done = False

            # ---- If library solver exists, try to call it first ----
            if AxisLinesIntersectionsSolver is not None:
                try:
                    _solver = AxisLinesIntersectionsSolver()

                    _out = _solver.solve(
                        O=O,
                        RefPlane=ref_plane,
                        d=float(d_in),
                        L12_len=float(L12_len_in),
                        L36_len=float(L36_len_in),
                        alpha_deg=float(alpha_deg_in),
                        axis_len=float(axis_len_in),
                    )

                    self.AxisLinesIntersectionsSolver__Axis_AO = _out["Axis_AO"]
                    self.AxisLinesIntersectionsSolver__Axis_AC = _out["Axis_AC"]
                    self.AxisLinesIntersectionsSolver__Axis_AD = _out["Axis_AD"]

                    self.AxisLinesIntersectionsSolver__L1 = _out["L1"]
                    self.AxisLinesIntersectionsSolver__L2 = _out["L2"]
                    self.AxisLinesIntersectionsSolver__L3 = _out["L3"]
                    self.AxisLinesIntersectionsSolver__L4 = _out["L4"]
                    self.AxisLinesIntersectionsSolver__L5 = _out["L5"]
                    self.AxisLinesIntersectionsSolver__L6 = _out["L6"]

                    self.AxisLinesIntersectionsSolver__O_out = _out["O_out"]
                    self.AxisLinesIntersectionsSolver__A = _out["A"]
                    self.AxisLinesIntersectionsSolver__B = _out["B"]

                    self.AxisLinesIntersectionsSolver__J = _out["J"]
                    self.AxisLinesIntersectionsSolver__K = _out["K"]
                    self.AxisLinesIntersectionsSolver__Jp = _out["Jp"]
                    self.AxisLinesIntersectionsSolver__Kp = _out["Kp"]

                    self.AxisLinesIntersectionsSolver__Dist_BJ = _out["Dist_BJ"]
                    self.AxisLinesIntersectionsSolver__Dist_JK = _out["Dist_JK"]

                    self.AxisLinesIntersectionsSolver__Log = to_py_list(_out["Log"])

                    # 若关键结果为空，则走内置兜底
                    if self.AxisLinesIntersectionsSolver__Dist_JK is None:
                        raise Exception(
                            "AxisLinesIntersectionsSolver library output missing Dist_JK; fallback to builtin")

                    self.Log.append("[Step6A] AxisLinesIntersectionsSolver (library) ok.")
                    axis_done = True

                except Exception as _ee:
                    # 回退到内置实现
                    self.AxisLinesIntersectionsSolver__Log = [
                        "[Step6A][WARN] lib AxisLinesIntersectionsSolver failed: {}".format(_ee)]

            # ---- Builtin implementation ----
            if not axis_done:
                import math
                try:
                    import System
                except Exception:
                    System = None

                tol = 0.001

                def _unit(v):
                    vv = rg.Vector3d(v)
                    if vv.IsZero:
                        return vv
                    vv.Unitize()
                    return vv

                def _line_centered(pt, dirv, length):
                    dv = _unit(dirv)
                    a = pt - dv * (float(length) * 0.5)
                    b = pt + dv * (float(length) * 0.5)
                    return rg.Line(a, b)

                def _rot_dir(dirv, ang_deg, axis):
                    dv = rg.Vector3d(dirv)
                    xform = rg.Transform.Rotation(math.radians(float(ang_deg)), axis, rg.Point3d.Origin)
                    dv.Transform(xform)
                    return _unit(dv)

                def _line_line_pt(l1, l2):
                    """Robust line-line intersection for coplanar infinite lines."""
                    try:
                        if System is not None:
                            ta = System.Double(0.0)
                            tb = System.Double(0.0)
                            ok = rg.Intersect.Intersection.LineLine(l1, l2, ta, tb, tol, False)
                            if ok:
                                return l1.PointAt(float(ta))
                            return None
                    except Exception:
                        pass
                    # fallback: closest points
                    try:
                        ok, a, b = rg.Line.ClosestPoints(l1, l2)
                        if ok:
                            return a
                    except Exception:
                        pass
                    return None

                x = _unit(ref_plane.XAxis)
                y = _unit(ref_plane.YAxis)
                z = _unit(ref_plane.ZAxis)

                # A/B：O 沿 ref_plane.YAxis 正负偏移 d
                d = float(d_in)
                A = O + y * d
                B = O - y * d

                # Axis lines
                Axis_AO = rg.Line(O, O + x * float(axis_len_in))
                dir_ac = _rot_dir(x, float(alpha_deg_in), z)
                dir_ad = _rot_dir(x, -float(alpha_deg_in), z)
                Axis_AC = rg.Line(O, O + dir_ac * float(axis_len_in))
                Axis_AD = rg.Line(O, O + dir_ad * float(axis_len_in))

                # L1/L2：过 A/B，平行 AO
                L1 = _line_centered(A, x, float(L12_len_in))
                L2 = _line_centered(B, x, float(L12_len_in))

                # L3/L4：平行 AC，距 O 偏移 ±d
                perp_ac = _unit(rg.Vector3d.CrossProduct(z, dir_ac))
                L3 = _line_centered(O + perp_ac * d, dir_ac, float(L36_len_in))
                L4 = _line_centered(O - perp_ac * d, dir_ac, float(L36_len_in))

                # L5/L6：平行 AD，距 O 偏移 ±d
                perp_ad = _unit(rg.Vector3d.CrossProduct(z, dir_ad))
                L5 = _line_centered(O + perp_ad * d, dir_ad, float(L36_len_in))
                L6 = _line_centered(O - perp_ad * d, dir_ad, float(L36_len_in))

                # Intersections
                J = _line_line_pt(L2, L3)
                K = _line_line_pt(L2, L6)
                Jp = _line_line_pt(L1, L5)
                Kp = _line_line_pt(L1, L6)

                dist_bj = B.DistanceTo(J) if (B is not None and J is not None) else None
                dist_jk = J.DistanceTo(K) if (J is not None and K is not None) else None

                self.AxisLinesIntersectionsSolver__Axis_AO = Axis_AO
                self.AxisLinesIntersectionsSolver__Axis_AC = Axis_AC
                self.AxisLinesIntersectionsSolver__Axis_AD = Axis_AD
                self.AxisLinesIntersectionsSolver__L1 = L1
                self.AxisLinesIntersectionsSolver__L2 = L2
                self.AxisLinesIntersectionsSolver__L3 = L3
                self.AxisLinesIntersectionsSolver__L4 = L4
                self.AxisLinesIntersectionsSolver__L5 = L5
                self.AxisLinesIntersectionsSolver__L6 = L6
                self.AxisLinesIntersectionsSolver__O_out = O
                self.AxisLinesIntersectionsSolver__A = A
                self.AxisLinesIntersectionsSolver__B = B
                self.AxisLinesIntersectionsSolver__J = J
                self.AxisLinesIntersectionsSolver__K = K
                self.AxisLinesIntersectionsSolver__Jp = Jp
                self.AxisLinesIntersectionsSolver__Kp = Kp
                self.AxisLinesIntersectionsSolver__Dist_BJ = dist_bj
                self.AxisLinesIntersectionsSolver__Dist_JK = dist_jk
                self.AxisLinesIntersectionsSolver__Log = [
                    "[builtin] d={}, L12_len={}, L36_len={}, alpha_deg={}, axis_len={}".format(d_in, L12_len_in,
                                                                                               L36_len_in, alpha_deg_in,
                                                                                               axis_len_in),
                    "J={}, K={}, Jp={}, Kp={}".format(J, K, Jp, Kp),
                    "Dist_BJ={}, Dist_JK={}".format(dist_bj, dist_jk),
                ]

                self.Log.append("[Step6A] AxisLinesIntersectionsSolver (builtin) ok.")

        except Exception as e:
            self.AxisLinesIntersectionsSolver__Log = ["[Step6A][ERROR] {}".format(e)]
            self.Log.extend(self.AxisLinesIntersectionsSolver__Log)
            return

        # -------------------------------------------------
        # Step 6B：SectionExtrude_SymmetricTrapezoid（优先用库；否则内置兜底）
        # -------------------------------------------------
        try:
            # Params
            base_point_in = self.get_param("SectionExtrude_SymmetricTrapezoid__base_point",
                                           "SectionExtrude_SymmetricTrapezoid__base_point", rg.Point3d(0.0, 0.0, 0.0))
            ref_plane_in = self.get_param("SectionExtrude_SymmetricTrapezoid__ref_plane",
                                          "SectionExtrude_SymmetricTrapezoid__ref_plane", None)
            oe_len_in = self.get_param("SectionExtrude_SymmetricTrapezoid__oe_len",
                                       "SectionExtrude_SymmetricTrapezoid__oe_len", 1.0)
            angle_deg_in = self.get_param("SectionExtrude_SymmetricTrapezoid__angle_deg",
                                          "SectionExtrude_SymmetricTrapezoid__angle_deg", 45.0)
            extrude_h_in = self.get_param("SectionExtrude_SymmetricTrapezoid__extrude_h",
                                          "SectionExtrude_SymmetricTrapezoid__extrude_h", 11.0)
            oo_prime_in = self.get_param("SectionExtrude_SymmetricTrapezoid__oo_prime",
                                         "SectionExtrude_SymmetricTrapezoid__oo_prime", 5.0)

            bp = normalize_point3d(base_point_in)
            ref_plane = ref_plane_in if isinstance(ref_plane_in, rg.Plane) else make_gh_plane("WorldXY", bp)

            # ab_len 来自 AxisLinesIntersectionsSolver__Dist_JK（按要求：不重算，直接用）
            ab_len_in = self.AxisLinesIntersectionsSolver__Dist_JK
            if ab_len_in is None:
                # 允许输入端覆盖
                ab_len_in = self.get_param("SectionExtrude_SymmetricTrapezoid__ab_len",
                                           "SectionExtrude_SymmetricTrapezoid__ab_len", 24.142136)
            ab_len_val = float(ab_len_in)

            # ---- If library exists ----
            if SectionExtrude_SymmetricTrapezoid is not None:
                try:
                    # 固定接口：构造 + build()
                    _sec = SectionExtrude_SymmetricTrapezoid(
                        base_point=bp,
                        ref_plane=ref_plane,
                        ab_len=ab_len_val,
                        oe_len=float(oe_len_in),
                        angle_deg=float(angle_deg_in),
                        extrude_h=float(extrude_h_in),
                        oo_prime=float(oo_prime_in),
                    ).build()

                    # Points
                    self.SectionExtrude_SymmetricTrapezoid__A = _sec.A
                    self.SectionExtrude_SymmetricTrapezoid__B = _sec.B
                    self.SectionExtrude_SymmetricTrapezoid__C = _sec.C
                    self.SectionExtrude_SymmetricTrapezoid__D = _sec.D
                    self.SectionExtrude_SymmetricTrapezoid__O = _sec.O
                    self.SectionExtrude_SymmetricTrapezoid__E = _sec.E
                    self.SectionExtrude_SymmetricTrapezoid__Oprime = _sec.Oprime

                    # Lines
                    self.SectionExtrude_SymmetricTrapezoid__AB = _sec.AB
                    self.SectionExtrude_SymmetricTrapezoid__CD = _sec.CD
                    self.SectionExtrude_SymmetricTrapezoid__AC = _sec.AC
                    self.SectionExtrude_SymmetricTrapezoid__BD = _sec.BD
                    self.SectionExtrude_SymmetricTrapezoid__Axis_AC = _sec.Axis_AC

                    # Section
                    self.SectionExtrude_SymmetricTrapezoid__section_polyline = _sec.section_polyline
                    self.SectionExtrude_SymmetricTrapezoid__section_curve = _sec.section_curve
                    self.SectionExtrude_SymmetricTrapezoid__section_brep = _sec.section_brep

                    # Solids
                    self.SectionExtrude_SymmetricTrapezoid__solid_brep = _sec.solid_brep
                    self.SectionExtrude_SymmetricTrapezoid__solid_brep_mirror = _sec.solid_brep_mirror
                    self.SectionExtrude_SymmetricTrapezoid__solid_list = flatten_any(_sec.solid_list)

                    # Planes
                    self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime = _sec.Plane_Oprime
                    self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_X = _sec.Plane_Oprime_X
                    self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_Y = _sec.Plane_Oprime_Y
                    self.SectionExtrude_SymmetricTrapezoid__MirrorPlane_ACZ = _sec.MirrorPlane_ACZ

                    # Log
                    self.SectionExtrude_SymmetricTrapezoid__log = to_py_list(_sec.log)

                    if not self.SectionExtrude_SymmetricTrapezoid__solid_list:
                        raise Exception(
                            "SectionExtrude_SymmetricTrapezoid library output missing solid_list; fallback to builtin")

                    self.Log.append("[Step6B] SectionExtrude_SymmetricTrapezoid (library) ok.")

                except Exception as _ee:
                    self.SectionExtrude_SymmetricTrapezoid__log = [
                        "[Step6B][WARN] lib SectionExtrude_SymmetricTrapezoid failed: {}".format(_ee)]
                    # fallback to builtin below

            # ---- Builtin implementation ----
            import math

            x = rg.Vector3d(ref_plane.XAxis);
            x.Unitize()
            y = rg.Vector3d(ref_plane.YAxis);
            y.Unitize()
            z = rg.Vector3d(ref_plane.ZAxis);
            z.Unitize()

            O = bp
            E = O + y * float(oe_len_in)
            # Oprime：沿 ref_plane.YAxis 偏移
            Oprime = O + y * float(oo_prime_in)

            # Trapezoid: top AB centered at O (y=0), bottom CD at y=-oe_len
            half_top = ab_len_val * 0.5
            A = O - x * half_top
            B = O + x * half_top

            ang = max(0.1, float(angle_deg_in))
            shift = float(oe_len_in) / math.tan(math.radians(ang)) if math.tan(math.radians(ang)) != 0 else 0.0
            bottom_len = max(0.01, ab_len_val - 2.0 * shift)
            half_bot = bottom_len * 0.5
            C = (O - y * float(oe_len_in)) + x * half_bot
            D = (O - y * float(oe_len_in)) - x * half_bot

            pl = rg.Polyline([A, B, C, D, A])
            section_poly = pl
            section_crv = rg.PolylineCurve(pl)

            # Extrude
            solid_list = self.SectionExtrude_SymmetricTrapezoid__solid_list

            Plane_Oprime = rg.Plane(Oprime, x, y)
            Plane_Oprime_X = rg.Plane(Oprime, x, z)
            Plane_Oprime_Y = rg.Plane(Oprime, y, z)

            # save
            self.SectionExtrude_SymmetricTrapezoid__A = A
            self.SectionExtrude_SymmetricTrapezoid__B = B
            self.SectionExtrude_SymmetricTrapezoid__C = C
            self.SectionExtrude_SymmetricTrapezoid__D = D
            self.SectionExtrude_SymmetricTrapezoid__O = O
            self.SectionExtrude_SymmetricTrapezoid__E = E
            self.SectionExtrude_SymmetricTrapezoid__Oprime = Oprime
            self.SectionExtrude_SymmetricTrapezoid__AB = rg.Line(A, B)
            self.SectionExtrude_SymmetricTrapezoid__CD = rg.Line(D, C)
            self.SectionExtrude_SymmetricTrapezoid__AC = rg.Line(A, C)
            self.SectionExtrude_SymmetricTrapezoid__BD = rg.Line(B, D)
            self.SectionExtrude_SymmetricTrapezoid__Axis_AC = rg.Line(O, O + x * 10.0)
            self.SectionExtrude_SymmetricTrapezoid__section_polyline = section_poly
            self.SectionExtrude_SymmetricTrapezoid__section_curve = section_crv
            self.SectionExtrude_SymmetricTrapezoid__solid_list = flatten_any(solid_list)
            self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime = Plane_Oprime
            self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_X = Plane_Oprime_X
            self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_Y = Plane_Oprime_Y
            self.SectionExtrude_SymmetricTrapezoid__log = self.SectionExtrude_SymmetricTrapezoid__log + [
                "[builtin] ab_len={}, oe_len={}, angle_deg={}, extrude_h={}, oo_prime={}".format(ab_len_val, oe_len_in,
                                                                                                 angle_deg_in,
                                                                                                 extrude_h_in,
                                                                                                 oo_prime_in),
                "solid_count={}".format(len(self.SectionExtrude_SymmetricTrapezoid__solid_list)),
            ]

            self.Log.append("[Step6B] SectionExtrude_SymmetricTrapezoid (builtin) ok.")

        except Exception as e:
            self.SectionExtrude_SymmetricTrapezoid__log = ["[Step6B][ERROR] {}".format(e)]
            self.Log.extend(self.SectionExtrude_SymmetricTrapezoid__log)
            return

        # -------------------------------------------------
        # Step 6C：ListItem（TargetPlane）
        # -------------------------------------------------
        try:
            tgt_idx = self.get_param("AlignToolToTimber_4__TargetPlane", "AlignToolToTimber_4__TargetPlane", 0)
            wrap_tgt = self.get_param("AlignToolToTimber_4__TargetWrap", "AlignToolToTimber_4__TargetWrap", True)
            planes = to_py_list(self.FacePlaneList)
            if len(planes) == 0:
                self.AlignToolToTimber_4__TargetPlane_Item = None
            else:
                try:
                    ii = int(tgt_idx)
                except Exception:
                    ii = 0
                if wrap_tgt:
                    ii = ii % len(planes)
                self.AlignToolToTimber_4__TargetPlane_Item = planes[ii] if (0 <= ii < len(planes)) else None

            self.Log.append("[Step6C] ListItem(TargetPlane) ok.")
        except Exception as e:
            self.AlignToolToTimber_4__TargetPlane_Item = None
            self.Log.append("[Step6C][ERROR] {}".format(e))

        # -------------------------------------------------
        # Step 6D：AlignToolToTimber::4（对齐实体到主木坯）
        # -------------------------------------------------
        try:
            geos = flatten_any(self.SectionExtrude_SymmetricTrapezoid__solid_list)
            src_plane = self.SectionExtrude_SymmetricTrapezoid__Plane_Oprime
            tgt_plane = self.AlignToolToTimber_4__TargetPlane_Item

            rot_in = self.get_param("AlignToolToTimber_4__RotateDeg", "AlignToolToTimber_4__RotateDeg", None)
            fx_in = self.get_param("AlignToolToTimber_4__FlipX", "AlignToolToTimber_4__FlipX", False)
            fy_in = self.get_param("AlignToolToTimber_4__FlipY", "AlignToolToTimber_4__FlipY", False)
            fz_in = self.get_param("AlignToolToTimber_4__FlipZ", "AlignToolToTimber_4__FlipZ", False)
            mx_in = self.get_param("AlignToolToTimber_4__MoveX", "AlignToolToTimber_4__MoveX", 0.0)
            my_in = self.get_param("AlignToolToTimber_4__MoveY", "AlignToolToTimber_4__MoveY", 0.0)
            mz_in = self.get_param("AlignToolToTimber_4__MoveZ", "AlignToolToTimber_4__MoveZ", 0.0)

            n = max(len(geos), 1)
            rot_l = _broadcast_to_len(_as_broadcast_list(rot_in), n)
            fx_l = _broadcast_to_len(_as_broadcast_list(fx_in), n)
            fy_l = _broadcast_to_len(_as_broadcast_list(fy_in), n)
            fz_l = _broadcast_to_len(_as_broadcast_list(fz_in), n)
            mx_l = _broadcast_to_len(_as_broadcast_list(mx_in), n)
            my_l = _broadcast_to_len(_as_broadcast_list(my_in), n)
            mz_l = _broadcast_to_len(_as_broadcast_list(mz_in), n)

            moved_list = []
            xfm_list = []
            src_out_list = []
            tgt_out_list = []
            log_all = []

            for i in range(n):
                g = geos[i] if len(geos) > 0 else None
                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    g,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rot_l[i],
                    flip_x=bool(fx_l[i]),
                    flip_y=bool(fy_l[i]),
                    flip_z=bool(fz_l[i]),
                    move_x=float(mx_l[i]) if mx_l[i] is not None else 0.0,
                    move_y=float(my_l[i]) if my_l[i] is not None else 0.0,
                    move_z=float(mz_l[i]) if mz_l[i] is not None else 0.0,
                )

                _flat = flatten_any(moved_geo)
                moved_geo = _flat[0] if len(_flat) == 1 else (_flat if len(_flat) > 1 else moved_geo)

                moved_list.append(moved_geo)
                xfm_list.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                src_out_list.append(src_out)
                tgt_out_list.append(tgt_out)
                log_all.append("[i {}] AlignToolToTimber::4 ok".format(i))

            self.AlignToolToTimber_4__SourceOut = src_out_list[0] if len(src_out_list) == 1 else src_out_list
            self.AlignToolToTimber_4__TargetOut = tgt_out_list[0] if len(tgt_out_list) == 1 else tgt_out_list
            self.AlignToolToTimber_4__TransformOut = xfm_list[0] if len(xfm_list) == 1 else xfm_list
            self.AlignToolToTimber_4__MovedGeo = moved_list[0] if len(moved_list) == 1 else moved_list
            self.AlignToolToTimber_4__Log = log_all

            self.Log.append("[Step6D] AlignToolToTimber::4 ok.")

        except Exception as e:
            self.AlignToolToTimber_4__SourceOut = None
            self.AlignToolToTimber_4__TargetOut = None
            self.AlignToolToTimber_4__MovedGeo = None
            self.AlignToolToTimber_4__TransformOut = None
            self.AlignToolToTimber_4__Log = ["[Step6D][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_4__Log)

    # --------------------------
    # Step 7：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + AlignToolToTimber::5
    # --------------------------
    def step7_qiao_tool_plane_align(self):
        """Generate QiAo tool -> extract planes -> align tool to main timber (GH style broadcast)."""

        # ========== Step 7A：QiAOTool =============
        try:
            if QiAoToolSolver is None:
                raise Exception("QiAoToolSolver not found in yingzao.ancientArchi")

            def _to_float(x, default):
                try:
                    if x is None:
                        return float(default)
                    return float(x)
                except Exception:
                    return float(default)

            def _to_bool(x, default=False):
                if x is None:
                    return bool(default)
                try:
                    if InputHelper is not None:
                        return bool(InputHelper.to_bool(x, default=default))
                    return bool(x)
                except Exception:
                    return bool(default)

            # 参数优先级：GH 输入端 > AllDict > 默认
            length_fen = self.get_param("QiAOTool__length_fen", "QiAOTool__length_fen", 41.0)
            width_fen = self.get_param("QiAOTool__width_fen", "QiAOTool__width_fen", 16.0)
            height_fen = self.get_param("QiAOTool__height_fen", "QiAOTool__height_fen", 10.0)

            bp_in = self.get_param("QiAOTool__base_point", "QiAOTool__base_point", rg.Point3d(0.0, 0.0, 0.0))
            bp = normalize_point3d(bp_in)

            timber_ref_mode = self.get_param(
                "QiAOTool__timber_ref_plane_mode",
                "QiAOTool__timber_ref_plane_mode",
                "XZ",
            )
            qi_ref_mode = self.get_param(
                "QiAOTool__qi_ref_plane_mode",
                "QiAOTool__qi_ref_plane_mode",
                "XZ",
            )

            qi_height = self.get_param("QiAOTool__qi_height", "QiAOTool__qi_height", 4.0)
            sha_width = self.get_param("QiAOTool__sha_width", "QiAOTool__sha_width", 2.0)
            qi_offset_fen = self.get_param("QiAOTool__qi_offset_fen", "QiAOTool__qi_offset_fen", 0.5)
            extrude_length = self.get_param("QiAOTool__extrude_length", "QiAOTool__extrude_length", 28.0)
            extrude_positive = self.get_param("QiAOTool__extrude_positive", "QiAOTool__extrude_positive", False)

            def _make_plane(mode, origin):
                # 优先用库中的 GHPlaneFactory；否则回退到本文件的 make_gh_plane
                if GHPlaneFactory is not None:
                    try:
                        return GHPlaneFactory.make(mode if mode is not None else "XZ", origin=origin)
                    except Exception:
                        pass
                m = str(mode or "XZ")
                if m.strip().upper() in ("XZ", "WORLDXZ"):
                    return make_gh_plane("WorldXZ", origin)
                if m.strip().upper() in ("XY", "WORLDXY"):
                    return make_gh_plane("WorldXY", origin)
                if m.strip().upper() in ("YZ", "WORLDYZ"):
                    return make_gh_plane("WorldYZ", origin)
                return make_gh_plane(m, origin)

            params = {
                "length_fen": _to_float(length_fen, 41.0),
                "width_fen": _to_float(width_fen, 16.0),
                "height_fen": _to_float(height_fen, 10.0),
                "base_point": bp,
                "timber_ref_plane": _make_plane(timber_ref_mode, bp),
                "qi_height": _to_float(qi_height, 4.0),
                "sha_width": _to_float(sha_width, 2.0),
                "qi_offset_fen": _to_float(qi_offset_fen, 0.5),
                "extrude_length": _to_float(extrude_length, 28.0),
                "extrude_positive": _to_bool(extrude_positive, default=False),
                "qi_ref_plane": _make_plane(qi_ref_mode, bp),
            }

            # Refresh（仅用于 sticky 缓存重建 solver 对象）
            rf_in = self.get_param("QiAOTool__Refresh", "QiAOTool__Refresh", False)
            rf = _to_bool(rf_in, default=False)

            sticky_key = "QiAoToolSolver::{ver}".format(ver=__version__)
            solver = None
            if (not rf) and (sticky_key in sc.sticky):
                solver = sc.sticky.get(sticky_key, None)
            if solver is None:
                solver = QiAoToolSolver(ghenv=self.ghenv)
                sc.sticky[sticky_key] = solver

            solver.run(params)

            self.QiAOTool__CutTimbers = solver.CutTimbers
            self.QiAOTool__FailTimbers = solver.FailTimbers
            # 仅保留本步骤会用到的输出：EdgeMidPoints / Corner0Planes
            self.QiAOTool__EdgeMidPoints = flatten_any(getattr(solver, "EdgeMidPoints", None))
            self.QiAOTool__Corner0Planes = flatten_any(getattr(solver, "Corner0Planes", None))
            self.QiAOTool__Log = to_py_list(getattr(solver, "Log", []))

            self.Log.append("[Step7A] QiAOTool ok.")

        except Exception as e:
            self.QiAOTool__CutTimbers = None
            self.QiAOTool__FailTimbers = None
            self.QiAOTool__EdgeMidPoints = []
            self.QiAOTool__Corner0Planes = []
            self.QiAOTool__Log = ["[Step7A][ERROR] {}".format(e)]
            self.Log.extend(self.QiAOTool__Log)
            # 若刀具未生成，后续步骤无意义，直接 return
            return

        # ========== Step 7B：PlaneFromLists::2（主木坯 -> TargetPlane） =============
        try:
            idx_origin_in = self.get_param("PlaneFromLists_2__IndexOrigin", "PlaneFromLists_2__IndexOrigin", 0)
            idx_plane_in = self.get_param("PlaneFromLists_2__IndexPlane", "PlaneFromLists_2__IndexPlane", 0)
            wrap_in = self.get_param("PlaneFromLists_2__Wrap", "PlaneFromLists_2__Wrap", True)

            origin_pts = flatten_any(self.EdgeMidPoints)
            base_planes = flatten_any(self.Corner0Planes)

            idx_origin_l = _as_broadcast_list(idx_origin_in)
            idx_plane_l = _as_broadcast_list(idx_plane_in)
            max_len = max(len(idx_origin_l), len(idx_plane_l), 1)
            idx_origin_l = _broadcast_to_len(idx_origin_l, max_len)
            idx_plane_l = _broadcast_to_len(idx_plane_l, max_len)

            builder = FTPlaneFromLists(wrap=bool(wrap_in))
            base_out_list, org_out_list, res_out_list, log_all = [], [], [], []
            for io, ip in zip(idx_origin_l, idx_plane_l):
                bp, op, rp, lg = builder.build_plane(origin_pts, base_planes, io, ip)
                base_out_list.append(bp)
                org_out_list.append(op)
                res_out_list.append(rp)
                log_all.extend(to_py_list(lg))

            self.PlaneFromLists_2__BasePlane = base_out_list[0] if len(base_out_list) == 1 else base_out_list
            self.PlaneFromLists_2__OriginPoint = org_out_list[0] if len(org_out_list) == 1 else org_out_list
            self.PlaneFromLists_2__ResultPlane = res_out_list[0] if len(res_out_list) == 1 else res_out_list
            self.PlaneFromLists_2__Log = log_all
            self.Log.append("[Step7B] PlaneFromLists::2 ok.")

        except Exception as e:
            self.PlaneFromLists_2__BasePlane = None
            self.PlaneFromLists_2__OriginPoint = None
            self.PlaneFromLists_2__ResultPlane = None
            self.PlaneFromLists_2__Log = ["[Step7B][ERROR] {}".format(e)]
            self.Log.extend(self.PlaneFromLists_2__Log)

        # ========== Step 7C：PlaneFromLists::3（QiAOTool -> SourcePlane） =============
        try:
            idx_origin_in = self.get_param("PlaneFromLists_3__IndexOrigin", "PlaneFromLists_3__IndexOrigin", 0)
            idx_plane_in = self.get_param("PlaneFromLists_3__IndexPlane", "PlaneFromLists_3__IndexPlane", 0)
            wrap_in = self.get_param("PlaneFromLists_3__Wrap", "PlaneFromLists_3__Wrap", True)

            origin_pts = flatten_any(self.QiAOTool__EdgeMidPoints)
            base_planes = flatten_any(self.QiAOTool__Corner0Planes)

            idx_origin_l = _as_broadcast_list(idx_origin_in)
            idx_plane_l = _as_broadcast_list(idx_plane_in)
            max_len = max(len(idx_origin_l), len(idx_plane_l), 1)
            idx_origin_l = _broadcast_to_len(idx_origin_l, max_len)
            idx_plane_l = _broadcast_to_len(idx_plane_l, max_len)

            builder = FTPlaneFromLists(wrap=bool(wrap_in))
            base_out_list, org_out_list, res_out_list, log_all = [], [], [], []
            for io, ip in zip(idx_origin_l, idx_plane_l):
                bp, op, rp, lg = builder.build_plane(origin_pts, base_planes, io, ip)
                base_out_list.append(bp)
                org_out_list.append(op)
                res_out_list.append(rp)
                log_all.extend(to_py_list(lg))

            self.PlaneFromLists_3__BasePlane = base_out_list[0] if len(base_out_list) == 1 else base_out_list
            self.PlaneFromLists_3__OriginPoint = org_out_list[0] if len(org_out_list) == 1 else org_out_list
            self.PlaneFromLists_3__ResultPlane = res_out_list[0] if len(res_out_list) == 1 else res_out_list
            self.PlaneFromLists_3__Log = log_all
            self.Log.append("[Step7C] PlaneFromLists::3 ok.")

        except Exception as e:
            self.PlaneFromLists_3__BasePlane = None
            self.PlaneFromLists_3__OriginPoint = None
            self.PlaneFromLists_3__ResultPlane = None
            self.PlaneFromLists_3__Log = ["[Step7C][ERROR] {}".format(e)]
            self.Log.extend(self.PlaneFromLists_3__Log)

        # ========== Step 7D：AlignToolToTimber::5（广播对齐） =============
        try:
            geo_in = self.QiAOTool__CutTimbers
            src_in = self.PlaneFromLists_3__ResultPlane
            tgt_in = self.PlaneFromLists_2__ResultPlane

            # Geo 既可能是 Tree，也可能是 list/单值
            paths, geos = [], []
            if DataTree is not None and hasattr(geo_in, "Paths") and hasattr(geo_in, "Branch"):
                for p in geo_in.Paths:
                    br = geo_in.Branch(p)
                    for g in br:
                        paths.append(p)
                        geos.append(g)
            else:
                geos = flatten_any(geo_in)
                paths = [i for i in range(len(geos))]

            n_geo = max(len(geos), 1)

            src_l = _broadcast_to_len(_as_broadcast_list(src_in), n_geo)
            tgt_l = _broadcast_to_len(_as_broadcast_list(tgt_in), n_geo)

            rot_in = self.get_param("AlignToolToTimber_5__RotateDeg", "AlignToolToTimber_5__RotateDeg", 0)
            fx_in = self.get_param("AlignToolToTimber_5__FlipX", "AlignToolToTimber_5__FlipX", False)
            fy_in = self.get_param("AlignToolToTimber_5__FlipY", "AlignToolToTimber_5__FlipY", False)
            fz_in = self.get_param("AlignToolToTimber_5__FlipZ", "AlignToolToTimber_5__FlipZ", False)
            mx_in = self.get_param("AlignToolToTimber_5__MoveX", "AlignToolToTimber_5__MoveX", 0.0)
            my_in = self.get_param("AlignToolToTimber_5__MoveY", "AlignToolToTimber_5__MoveY", 0.0)
            mz_in = self.get_param("AlignToolToTimber_5__MoveZ", "AlignToolToTimber_5__MoveZ", 0.0)

            rot_l = _broadcast_to_len(_as_broadcast_list(rot_in), n_geo)
            fx_l = _broadcast_to_len(_as_broadcast_list(fx_in), n_geo)
            fy_l = _broadcast_to_len(_as_broadcast_list(fy_in), n_geo)
            fz_l = _broadcast_to_len(_as_broadcast_list(fz_in), n_geo)
            mx_l = _broadcast_to_len(_as_broadcast_list(mx_in), n_geo)
            my_l = _broadcast_to_len(_as_broadcast_list(my_in), n_geo)
            mz_l = _broadcast_to_len(_as_broadcast_list(mz_in), n_geo)

            if DataTree is not None and GH_Path is not None:
                moved_tree = DataTree[object]()
                xfm_tree = DataTree[object]()
                src_out_tree = DataTree[object]()
                tgt_out_tree = DataTree[object]()
            else:
                moved_tree, xfm_tree, src_out_tree, tgt_out_tree = [], [], [], []

            log_all = []

            for i in range(n_geo):
                g = geos[i]
                sp = src_l[i]
                tp = tgt_l[i]

                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rot_l[i],
                    flip_x=bool(fx_l[i]),
                    flip_y=bool(fy_l[i]),
                    flip_z=bool(fz_l[i]),
                    move_x=float(mx_l[i]) if mx_l[i] is not None else 0.0,
                    move_y=float(my_l[i]) if my_l[i] is not None else 0.0,
                    move_z=float(mz_l[i]) if mz_l[i] is not None else 0.0,
                )

                _moved_flat = flatten_any(moved_geo)
                if len(_moved_flat) == 1:
                    moved_geo = _moved_flat[0]
                elif len(_moved_flat) > 1:
                    moved_geo = _moved_flat

                if DataTree is not None and GH_Path is not None:
                    pth = paths[i] if not isinstance(paths[i], int) else GH_Path(paths[i])
                    moved_tree.Add(moved_geo, pth)
                    xfm_tree.Add(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out, pth)
                    src_out_tree.Add(src_out, pth)
                    tgt_out_tree.Add(tgt_out, pth)
                else:
                    moved_tree.append(moved_geo)
                    xfm_tree.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                    src_out_tree.append(src_out)
                    tgt_out_tree.append(tgt_out)

                log_all.append("[i {}] align ok".format(i))

            def _norm_out(_x):
                if isinstance(_x, (list, tuple)):
                    _flat = flatten_any(_x)
                    return _flat[0] if len(_flat) == 1 else _flat
                return _x

            if not (DataTree is not None and GH_Path is not None and hasattr(moved_tree, 'Paths')):
                moved_tree = _norm_out(moved_tree)
                xfm_tree = _norm_out(xfm_tree)
                src_out_tree = _norm_out(src_out_tree)
                tgt_out_tree = _norm_out(tgt_out_tree)

            # NOTE: tools 端口需要“能参与裁切”的 Brep 或 list[Brep]。
            # 在 GH 环境下 moved_tree 往往是 DataTree（打印为 tree {n}），这里按 Merge 规则扁平一层。
            _moved_list = gh_tree_to_list(moved_tree, flatten_branches=True)
            _moved_out = _moved_list[0] if len(_moved_list) == 1 else _moved_list
            self.AlignToolToTimber_5__MovedGeo = _moved_out
            self.AlignToolToTimber_5__TransformOut = xfm_tree
            self.AlignToolToTimber_5__SourceOut = src_out_tree
            self.AlignToolToTimber_5__TargetOut = tgt_out_tree
            self.AlignToolToTimber_5__Log = log_all
            self.Log.append("[Step7D] AlignToolToTimber::5 ok.")

        except Exception as e:
            self.AlignToolToTimber_5__SourceOut = None
            self.AlignToolToTimber_5__TargetOut = None
            self.AlignToolToTimber_5__MovedGeo = None
            self.AlignToolToTimber_5__TransformOut = None
            self.AlignToolToTimber_5__Log = ["[Step7D][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_5__Log)

    # --------------------------
    # Step 8：GongYan + PlaneFromLists::4 + ListItem + AlignToolToTimber::6
    # --------------------------
    def step8_gongyan_plane_align(self):
        """Generate GongYan tool -> extract target plane from main timber -> pick source plane -> align."""

        # ========== Step 8A：GongYan（栱眼/工眼工具生成） ==========
        try:
            if FT_GongYan_CaiQi_ToolBuilder is None:
                raise Exception("FT_GongYan_CaiQi_ToolBuilder not available in yingzao.ancientArchi")

            bp = self.get_param("GongYan__BasePoint", "GongYan__BasePoint", rg.Point3d(0.0, 0.0, 0.0))
            bp = normalize_point3d(bp)

            sec_pl = self.get_param("GongYan__SectionPlane", "GongYan__SectionPlane", None)
            if sec_pl is not None and not isinstance(sec_pl, rg.Plane):
                # 若输入端给的是字符串/其它对象，则尝试转为 GH 平面；失败则置 None
                try:
                    sec_pl = make_gh_plane(str(sec_pl), bp)
                except Exception:
                    sec_pl = None

            EM_fen = self.get_param("GongYan__EM_fen", "GongYan__EM_fen", None)
            EC_fen = self.get_param("GongYan__EC_fen", "GongYan__EC_fen", None)
            AI_fen = self.get_param("GongYan__AI_fen", "GongYan__AI_fen", None)
            AG_fen = self.get_param("GongYan__AG_fen", "GongYan__AG_fen", None)
            JR_fen = self.get_param("GongYan__JR_fen", "GongYan__JR_fen", None)
            HK_fen = self.get_param("GongYan__HK_fen", "GongYan__HK_fen", None)
            Thickness = self.get_param("GongYan__Thickness", "GongYan__Thickness", None)
            OffsetDist = self.get_param("GongYan__OffsetDist", "GongYan__OffsetDist", None)

            builder = FT_GongYan_CaiQi_ToolBuilder(
                base_point=bp,
                section_plane=sec_pl,
                EM_fen=EM_fen,
                EC_fen=EC_fen,
                AI_fen=AI_fen,
                AG_fen=AG_fen,
                JR_fen=JR_fen,
                HK_fen=HK_fen,
                Thickness=Thickness,
                OffsetDist=OffsetDist,
            )

            (SectionCurve, SectionFace, LeftCurve, RightCurve, SymmetryAxis,
             AllPoints, ToolBrep, SectionPlanes, Log) = builder.build()

            self.GongYan__ToolBrep = ToolBrep
            self.GongYan__SectionCurve = SectionCurve
            self.GongYan__SectionFace = SectionFace
            self.GongYan__LeftCurve = LeftCurve
            self.GongYan__RightCurve = RightCurve
            self.GongYan__SymmetryAxis = SymmetryAxis
            self.GongYan__AllPoints = AllPoints
            self.GongYan__SectionPlanes = SectionPlanes
            self.GongYan__Log = to_py_list(Log)
            self.Log.append("[Step8A] GongYan ok.")

        except Exception as e:
            import traceback
            self.GongYan__ToolBrep = None
            self.GongYan__SectionCurve = None
            self.GongYan__SectionFace = None
            self.GongYan__LeftCurve = None
            self.GongYan__RightCurve = None
            self.GongYan__SymmetryAxis = None
            self.GongYan__AllPoints = None
            self.GongYan__SectionPlanes = None
            self.GongYan__Log = ["[Step8A][ERROR] {}\n{}".format(e, traceback.format_exc())]
            self.Log.extend(self.GongYan__Log)

        # ========== Step 8B：PlaneFromLists::4（从主木坯抽取 TargetPlane） ==========
        try:
            idx_origin_in = self.get_param("PlaneFromLists_4__IndexOrigin", "PlaneFromLists_4__IndexOrigin", 0)
            idx_plane_in = self.get_param("PlaneFromLists_4__IndexPlane", "PlaneFromLists_4__IndexPlane", 0)
            wrap_in = self.get_param("PlaneFromLists_4__Wrap", "PlaneFromLists_4__Wrap", True)

            origin_pts = flatten_any(self.PointList)
            base_planes = flatten_any(self.Corner0Planes)

            idx_origin_l = _as_broadcast_list(idx_origin_in)
            idx_plane_l = _as_broadcast_list(idx_plane_in)
            max_len = max(len(idx_origin_l), len(idx_plane_l), 1)
            idx_origin_l = _broadcast_to_len(idx_origin_l, max_len)
            idx_plane_l = _broadcast_to_len(idx_plane_l, max_len)

            builder = FTPlaneFromLists(wrap=bool(wrap_in))
            base_out_list = []
            org_out_list = []
            res_out_list = []
            log_all = []

            for io, ip in zip(idx_origin_l, idx_plane_l):
                bp, op, rp, lg = builder.build_plane(origin_pts, base_planes, io, ip)
                base_out_list.append(bp)
                org_out_list.append(op)
                res_out_list.append(rp)
                log_all.extend(to_py_list(lg))

            self.PlaneFromLists_4__BasePlane = base_out_list[0] if len(base_out_list) == 1 else base_out_list
            self.PlaneFromLists_4__OriginPoint = org_out_list[0] if len(org_out_list) == 1 else org_out_list
            self.PlaneFromLists_4__ResultPlane = res_out_list[0] if len(res_out_list) == 1 else res_out_list
            self.PlaneFromLists_4__Log = log_all
            self.Log.append("[Step8B] PlaneFromLists::4 ok.")

        except Exception as e:
            self.PlaneFromLists_4__BasePlane = None
            self.PlaneFromLists_4__OriginPoint = None
            self.PlaneFromLists_4__ResultPlane = None
            self.PlaneFromLists_4__Log = ["[Step8B][ERROR] {}".format(e)]
            self.Log.extend(self.PlaneFromLists_4__Log)

        # ========== Step 8C：List Item（从 GongYan.SectionPlanes 取 SourcePlane） ==========
        def _list_item(lst, idx, wrap=True):
            l = to_py_list(lst)
            if len(l) == 0:
                return None
            try:
                ii = int(idx)
            except Exception:
                ii = 0
            if wrap:
                ii = ii % len(l)
            if ii < 0 or ii >= len(l):
                return None
            return l[ii]

        try:
            idx_in = self.get_param("AlignToolToTimber_6__SourcePlane", "AlignToolToTimber_6__SourcePlane", 0)
            wrap_in = self.get_param("AlignToolToTimber_6__SourcePlane_Wrap", "AlignToolToTimber_6__SourcePlane_Wrap",
                                     True)
            src_list = self.GongYan__SectionPlanes

            idx_l = _as_broadcast_list(idx_in)
            # 若 idx 是列表，按 GH 广播逐项取值；否则返回单值
            if not _is_atomic_value(idx_in) and len(idx_l) > 1:
                out = []
                for ii in idx_l:
                    out.append(_list_item(src_list, ii, bool(wrap_in)))
                self.AlignToolToTimber_6__SourcePlane_Item = out[0] if len(out) == 1 else out
            else:
                self.AlignToolToTimber_6__SourcePlane_Item = _list_item(src_list, idx_in, bool(wrap_in))

            self.Log.append("[Step8C] ListItem (GongYan.SectionPlanes) ok.")

        except Exception as e:
            self.AlignToolToTimber_6__SourcePlane_Item = None
            self.Log.append("[Step8C][ERROR] {}".format(e))

        # ========== Step 8D：AlignToolToTimber::6（广播对齐） ==========
        try:
            geo_in = self.GongYan__ToolBrep

            src_l = _as_broadcast_list(self.AlignToolToTimber_6__SourcePlane_Item)
            tgt_l = _as_broadcast_list(self.PlaneFromLists_4__ResultPlane)

            rot_in = self.get_param("AlignToolToTimber_6__RotateDeg", "AlignToolToTimber_6__RotateDeg", 0)
            fx_in = self.get_param("AlignToolToTimber_6__FlipX", "AlignToolToTimber_6__FlipX", False)
            fy_in = self.get_param("AlignToolToTimber_6__FlipY", "AlignToolToTimber_6__FlipY", False)
            fz_in = self.get_param("AlignToolToTimber_6__FlipZ", "AlignToolToTimber_6__FlipZ", False)
            mx_in = self.get_param("AlignToolToTimber_6__MoveX", "AlignToolToTimber_6__MoveX", 0.0)
            my_in = self.get_param("AlignToolToTimber_6__MoveY", "AlignToolToTimber_6__MoveY", 0.0)
            mz_in = self.get_param("AlignToolToTimber_6__MoveZ", "AlignToolToTimber_6__MoveZ", 0.0)

            rot_l = _as_broadcast_list(rot_in)
            fx_l = _as_broadcast_list(fx_in)
            fy_l = _as_broadcast_list(fy_in)
            fz_l = _as_broadcast_list(fz_in)
            mx_l = _as_broadcast_list(mx_in)
            my_l = _as_broadcast_list(my_in)
            mz_l = _as_broadcast_list(mz_in)

            n = max(len(src_l), len(tgt_l), len(rot_l), len(fx_l), len(fy_l), len(fz_l), len(mx_l), len(my_l),
                    len(mz_l), 1)
            src_l = _broadcast_to_len(src_l, n)
            tgt_l = _broadcast_to_len(tgt_l, n)
            rot_l = _broadcast_to_len(rot_l, n)
            fx_l = _broadcast_to_len(fx_l, n)
            fy_l = _broadcast_to_len(fy_l, n)
            fz_l = _broadcast_to_len(fz_l, n)
            mx_l = _broadcast_to_len(mx_l, n)
            my_l = _broadcast_to_len(my_l, n)
            mz_l = _broadcast_to_len(mz_l, n)

            moved_list = []
            xfm_list = []
            src_out_list = []
            tgt_out_list = []
            log_all = []

            for i in range(n):
                src_out, tgt_out, xfm_out, moved_geo = GeoAligner_xfm.align(
                    geo_in,
                    src_l[i],
                    tgt_l[i],
                    rotate_deg=rot_l[i],
                    flip_x=bool(fx_l[i]),
                    flip_y=bool(fy_l[i]),
                    flip_z=bool(fz_l[i]),
                    move_x=float(mx_l[i]) if mx_l[i] is not None else 0.0,
                    move_y=float(my_l[i]) if my_l[i] is not None else 0.0,
                    move_z=float(mz_l[i]) if mz_l[i] is not None else 0.0,
                )

                _moved_flat = flatten_any(moved_geo)
                if len(_moved_flat) == 1:
                    moved_geo = _moved_flat[0]
                elif len(_moved_flat) > 1:
                    moved_geo = _moved_flat

                moved_list.append(moved_geo)
                xfm_list.append(ght.GH_Transform(xfm_out) if (ght and xfm_out is not None) else xfm_out)
                src_out_list.append(src_out)
                tgt_out_list.append(tgt_out)
                log_all.append("[i {}] align ok".format(i))

            self.AlignToolToTimber_6__MovedGeo = moved_list[0] if len(moved_list) == 1 else moved_list
            self.AlignToolToTimber_6__TransformOut = xfm_list[0] if len(xfm_list) == 1 else xfm_list
            self.AlignToolToTimber_6__SourceOut = src_out_list[0] if len(src_out_list) == 1 else src_out_list
            self.AlignToolToTimber_6__TargetOut = tgt_out_list[0] if len(tgt_out_list) == 1 else tgt_out_list
            self.AlignToolToTimber_6__Log = log_all
            self.Log.append("[Step8D] AlignToolToTimber::6 ok.")

        except Exception as e:
            self.AlignToolToTimber_6__SourceOut = None
            self.AlignToolToTimber_6__TargetOut = None
            self.AlignToolToTimber_6__MovedGeo = None
            self.AlignToolToTimber_6__TransformOut = None
            self.AlignToolToTimber_6__Log = ["[Step8D][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_6__Log)

    # --------------------------
    # Step 9：ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver + ListItem×2 + AlignToolToTimber::7 + CutTimbersByTools::1
    # --------------------------
    def step9_chaang4pu_align_and_cut(self):
        """Blackbox generate ChaAng4PU tool geo -> extract planes -> align -> cut."""

        # ========== Step 9A：ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver（黑盒） ==========
        try:
            if ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver is None:
                raise Exception("ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver not available in yingzao.ancientArchi")

            bp = normalize_point3d(self.get_param("ChaAng4PU__base_point", "ChaAng4PU__base_point", self.base_point))
            rf = self.get_param("ChaAng4PU__Refresh", "ChaAng4PU__Refresh", self.Refresh)

            s = ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver(self.DBPath, bp, rf)
            # 兼容不同命名：run/solve
            if hasattr(s, "run"):
                s.run()
            elif hasattr(s, "solve"):
                s.solve()
            else:
                raise Exception("ChaAng4PU solver has no run/solve method")

            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__CutTimbers = getattr(s, "CutTimbers", None)
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__FailTimbers = getattr(s, "FailTimbers", None)
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log = to_py_list(getattr(s, "Log", None))
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__RefPlanes = getattr(s, "RefPlanes", None)
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__SolidFace_AE = getattr(s, "SolidFace_AE", None)
            self.Log.append("[Step9A] ChaAng4PU blackbox ok.")

        except Exception as e:
            import traceback
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__CutTimbers = None
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__FailTimbers = None
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__RefPlanes = None
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__SolidFace_AE = None
            self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log = [
                "[Step9A][ERROR] {}\n{}".format(e, traceback.format_exc())]
            self.Log.extend(self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log)

        # ========== Step 9B：List Item ×2（SourcePlane / TargetPlane） ==========
        def _list_item(lst, idx, wrap=True):
            l = to_py_list(lst)
            if len(l) == 0:
                return None
            try:
                ii = int(idx)
            except Exception:
                ii = 0
            if wrap:
                ii = ii % len(l)
            if ii < 0 or ii >= len(l):
                return None
            return l[ii]

        # SourcePlane from RefPlanes
        try:
            idx_in = self.get_param("AlignToolToTimber_7__SourcePlane", "AlignToolToTimber_7__SourcePlane", 0)
            wrap_in = self.get_param("AlignToolToTimber_7__SourcePlane_Wrap", "AlignToolToTimber_7__SourcePlane_Wrap",
                                     True)
            src_list = self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__RefPlanes

            idx_l = _as_broadcast_list(idx_in)
            if (not _is_atomic_value(idx_in)) and len(idx_l) > 1:
                out = []
                for ii in idx_l:
                    out.append(_list_item(src_list, ii, bool(wrap_in)))
                self.AlignToolToTimber_7__SourcePlane_Item = out[0] if len(out) == 1 else out
            else:
                self.AlignToolToTimber_7__SourcePlane_Item = _list_item(src_list, idx_in, bool(wrap_in))

            self.Log.append("[Step9B] ListItem SourcePlane ok.")

        except Exception as e:
            self.AlignToolToTimber_7__SourcePlane_Item = None
            self.Log.append("[Step9B][ERROR] SourcePlane: {}".format(e))

        # TargetPlane from main timber FacePlaneList
        try:
            idx_in = self.get_param("AlignToolToTimber_7__TargetPlane", "AlignToolToTimber_7__TargetPlane", 0)
            wrap_in = self.get_param("AlignToolToTimber_7__TargetPlane_Wrap", "AlignToolToTimber_7__TargetPlane_Wrap",
                                     True)
            tgt_list = self.FacePlaneList

            idx_l = _as_broadcast_list(idx_in)
            if (not _is_atomic_value(idx_in)) and len(idx_l) > 1:
                out = []
                for ii in idx_l:
                    out.append(_list_item(tgt_list, ii, bool(wrap_in)))
                self.AlignToolToTimber_7__TargetPlane_Item = out[0] if len(out) == 1 else out
            else:
                self.AlignToolToTimber_7__TargetPlane_Item = _list_item(tgt_list, idx_in, bool(wrap_in))

            self.Log.append("[Step9B] ListItem TargetPlane ok.")

        except Exception as e:
            self.AlignToolToTimber_7__TargetPlane_Item = None
            self.Log.append("[Step9B][ERROR] TargetPlane: {}".format(e))

        # ========== Step 9C：AlignToolToTimber::7（广播对齐，接口同 GeoAligner_xfm） ==========
        try:
            geo_in = self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__CutTimbers
            geo_list = _as_broadcast_list(geo_in)

            src_l = _as_broadcast_list(self.AlignToolToTimber_7__SourcePlane_Item)
            tgt_l = _as_broadcast_list(self.AlignToolToTimber_7__TargetPlane_Item)

            rot_in = self.get_param("AlignToolToTimber_7__RotateDeg", "AlignToolToTimber_7__RotateDeg", 0)
            fx_in = self.get_param("AlignToolToTimber_7__FlipX", "AlignToolToTimber_7__FlipX", False)
            fy_in = self.get_param("AlignToolToTimber_7__FlipY", "AlignToolToTimber_7__FlipY", False)
            fz_in = self.get_param("AlignToolToTimber_7__FlipZ", "AlignToolToTimber_7__FlipZ", False)
            mx_in = self.get_param("AlignToolToTimber_7__MoveX", "AlignToolToTimber_7__MoveX", 0.0)
            my_in = self.get_param("AlignToolToTimber_7__MoveY", "AlignToolToTimber_7__MoveY", 0.0)
            mz_in = self.get_param("AlignToolToTimber_7__MoveZ", "AlignToolToTimber_7__MoveZ", 0.0)

            rot_l = _as_broadcast_list(rot_in)
            fx_l = _as_broadcast_list(fx_in)
            fy_l = _as_broadcast_list(fy_in)
            fz_l = _as_broadcast_list(fz_in)
            mx_l = _as_broadcast_list(mx_in)
            my_l = _as_broadcast_list(my_in)
            mz_l = _as_broadcast_list(mz_in)

            n = max(len(geo_list), len(src_l), len(tgt_l), len(rot_l), len(fx_l), len(fy_l), len(fz_l), len(mx_l),
                    len(my_l), len(mz_l), 1)
            geo_list = _broadcast_to_len(geo_list, n)
            src_l = _broadcast_to_len(src_l, n)
            tgt_l = _broadcast_to_len(tgt_l, n)
            rot_l = _broadcast_to_len(rot_l, n)
            fx_l = _broadcast_to_len(fx_l, n)
            fy_l = _broadcast_to_len(fy_l, n)
            fz_l = _broadcast_to_len(fz_l, n)
            mx_l = _broadcast_to_len(mx_l, n)
            my_l = _broadcast_to_len(my_l, n)
            mz_l = _broadcast_to_len(mz_l, n)

            moved_list = []
            xfm_list = []
            src_out_list = []
            tgt_out_list = []
            log_all = []

            for g, sp, tp, rd, fx, fy, fz, mx, my, mz in zip(geo_list, src_l, tgt_l, rot_l, fx_l, fy_l, fz_l, mx_l,
                                                             my_l, mz_l):
                if g is None or sp is None or tp is None:
                    moved_list.append(None)
                    xfm_list.append(None)
                    src_out_list.append(sp)
                    tgt_out_list.append(tp)
                    log_all.append("[Step9C][WARN] align skipped (missing geo/plane)")
                    continue

                so, to_, xfm, mg = GeoAligner_xfm.align(
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

                moved_list.append(mg)
                xfm_list.append(xfm)
                src_out_list.append(so)
                tgt_out_list.append(to_)
                log_all.append("[Step9C] ok")

            self.AlignToolToTimber_7__MovedGeo = moved_list[0] if len(moved_list) == 1 else moved_list
            self.AlignToolToTimber_7__TransformOut = xfm_list[0] if len(xfm_list) == 1 else xfm_list
            self.AlignToolToTimber_7__SourceOut = src_out_list[0] if len(src_out_list) == 1 else src_out_list
            self.AlignToolToTimber_7__TargetOut = tgt_out_list[0] if len(tgt_out_list) == 1 else tgt_out_list
            self.AlignToolToTimber_7__Log = log_all
            self.Log.append("[Step9C] AlignToolToTimber::7 ok.")

        except Exception as e:
            self.AlignToolToTimber_7__SourceOut = None
            self.AlignToolToTimber_7__TargetOut = None
            self.AlignToolToTimber_7__MovedGeo = None
            self.AlignToolToTimber_7__TransformOut = None
            self.AlignToolToTimber_7__Log = ["[Step9C][ERROR] {}".format(e)]
            self.Log.extend(self.AlignToolToTimber_7__Log)

        # ========== Step 9D：CutTimbersByTools::1（切割） ==========
        try:
            if FT_CutTimbersByTools_GH_SolidDifference is None:
                raise Exception("FT_CutTimbersByTools_GH_SolidDifference not available in yingzao.ancientArchi")

            # 说明：按用户提供的 GH 连线约定：
            # - Timbers <- AlignToolToTimber::7.MovedGeo
            # - Tools   <- AlignToolToTimber::4__MovedGeo
            timbers_in = self.AlignToolToTimber_7__MovedGeo
            tools_in = self.AlignToolToTimber_4__MovedGeo

            keep_inside = self.get_param("CutTimbersByTools_1__KeepInside", "CutTimbersByTools_1__KeepInside", False)
            dbg_in = self.get_param("CutTimbersByTools_1__Debug", "CutTimbersByTools_1__Debug", None)

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(dbg_in) if dbg_in is not None else False)
            c, f, lg = cutter.cut(
                timbers=timbers_in,
                tools=tools_in,
                keep_inside=bool(keep_inside),
                debug=dbg_in
            )

            self.CutTimbersByTools_1__CutTimbers = c
            self.CutTimbersByTools_1__FailTimbers = f
            self.CutTimbersByTools_1__Log = to_py_list(lg)
            self.Log.append("[Step9D] CutTimbersByTools::1 ok.")

        except Exception as e:
            self.CutTimbersByTools_1__CutTimbers = None
            self.CutTimbersByTools_1__FailTimbers = None
            self.CutTimbersByTools_1__Log = ["[Step9D][ERROR] {}".format(e)]
            self.Log.extend(self.CutTimbersByTools_1__Log)

    # ----------------------------------------------------------
    # Step 10：CutTimbersByTools::2
    #   Timbers = Timber_block_uniform.TimberBrep
    #   Tools   = Merge([AlignToolToTimber::1.MovedGeo, AlignToolToTimber::2.MovedGeo, GeoAligner::3.MovedGeo,
    #                   AlignToolToTimber::4.MovedGeo, AlignToolToTimber::5.MovedGeo, AlignToolToTimber::6.MovedGeo])
    # ----------------------------------------------------------
    def step10_cut_timbers_by_tools2(self):
        if FT_CutTimbersByTools_GH_SolidDifference is None:
            self.Log.append('[Step10] FT_CutTimbersByTools_GH_SolidDifference import failed; skip.')
            return

        # GH 参数优先级：输入端 > AllDict > 默认
        keep_inside = self.get_param('CutTimbersByTools_2__KeepInside', 'CutTimbersByTools_2__KeepInside', False)
        debug_cut = self.get_param('CutTimbersByTools_2__Debug', 'CutTimbersByTools_2__Debug', None)

        timbers_in = self.TimberBrep

        # Tools：严格按 GH Merge 行为，把多个 MovedGeo 合并为一个 tools 列表（并扁平一层）
        tool_sources = [
            getattr(self, 'AlignToolToTimber_1__MovedGeo', None),
            getattr(self, 'AlignToolToTimber_2__MovedGeo', None),
            getattr(self, 'GeoAligner_3__MovedGeo', None),
            getattr(self, 'AlignToolToTimber_4__MovedGeo', None),
            getattr(self, 'AlignToolToTimber_5__MovedGeo', None),
            getattr(self, 'AlignToolToTimber_6__MovedGeo', None),
        ]
        tools_in = []
        for t in tool_sources:
            if t is None:
                continue
            try:
                tools_in.extend(flatten_any(t))
            except Exception:
                # 兜底：保持原值
                tools_in.append(t)

        # 若没有任何刀具，直接返回
        if not tools_in:
            self.Log.append('[Step10] Tools list is empty; skip cut.')
            self.CutTimbersByTools_2__CutTimbers = None
            self.CutTimbersByTools_2__FailTimbers = None
            self.CutTimbersByTools_2__Log = ['[Step10] empty tools']
            return

        try:
            cutter = FT_CutTimbersByTools_GH_SolidDifference(
                debug=bool(debug_cut) if debug_cut is not None else False
            )
            c, f, lg = cutter.cut(
                timbers=timbers_in,
                tools=tools_in,
                keep_inside=bool(keep_inside),
                debug=debug_cut
            )
            self.CutTimbersByTools_2__CutTimbers = c
            self.CutTimbersByTools_2__FailTimbers = f
            self.CutTimbersByTools_2__Log = to_py_list(lg)
            self.Log.append('[Step10] CutTimbersByTools::2 ok; tools_count={}'.format(len(tools_in)))
        except Exception as e:
            self.CutTimbersByTools_2__CutTimbers = None
            self.CutTimbersByTools_2__FailTimbers = None
            self.CutTimbersByTools_2__Log = ['[Step10] Exception: {}'.format(e)]
            self.Log.append('[Step10] CutTimbersByTools::2 failed: {}'.format(e))

    # ----------------------------------------------------------
    # Step 11：SplitSectionAnalyzer + RightTrianglePrismBuilder + AlignToolToTimber::8 + CutTimbersByTools::3
    #   A) Transform: SolidFace_AE by AlignToolToTimber::7.TransformOut
    #   B) SplitSectionAnalyzer: Brep <- CutTimbersByTools::2.CutTimbers
    #   C) RightTrianglePrismBuilder: build a right-triangle prism tool
    #   D) ListItem: SourcePlane from OPlanes
    #   E) AlignToolToTimber::8: align tool to target plane
    #   F) CutTimbersByTools::3: cut MaxClosedBrep by aligned tool
    # ----------------------------------------------------------
    def step11_split_prism_align_cut(self):
        # ========== Step 11A：Transform（把 SolidFace_AE 变换到木坯局部坐标） ==========
        try:
            self.Step11_Transform__GeometryIn = self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__SolidFace_AE
            self.Step11_Transform__TransformIn = self.AlignToolToTimber_7__TransformOut

            geo_in = self.Step11_Transform__GeometryIn
            xfm_in = self.Step11_Transform__TransformIn

            def _one_transform(geo_obj, xfm_obj):
                if geo_obj is None or xfm_obj is None:
                    return None
                # 兼容：xfm 可能被包在 GH_Transform 里
                try:
                    if hasattr(xfm_obj, 'Value'):
                        xfm_obj = xfm_obj.Value
                except Exception:
                    pass
                try:
                    # BrepFace / Surface / Curve 等：优先 Duplicate 再 Transform
                    if hasattr(geo_obj, 'Duplicate'):
                        dup = geo_obj.Duplicate()
                        try:
                            dup.Transform(xfm_obj)
                            return dup
                        except Exception:
                            pass
                    if hasattr(geo_obj, 'DuplicateBrep'):
                        dup = geo_obj.DuplicateBrep()
                        dup.Transform(xfm_obj)
                        return dup
                    if hasattr(geo_obj, 'DuplicateCurve'):
                        dup = geo_obj.DuplicateCurve()
                        dup.Transform(xfm_obj)
                        return dup
                except Exception:
                    pass
                # 兜底：若是 BrepFace，尝试 ToBrep
                try:
                    if hasattr(geo_obj, 'ToBrep'):
                        b = geo_obj.ToBrep()
                        if b is not None:
                            b.Transform(xfm_obj)
                            return b
                except Exception:
                    pass
                return None

            g_list = _as_broadcast_list(geo_in)
            x_list = _as_broadcast_list(xfm_in)
            n = max(len(g_list), len(x_list), 1)
            g_list = _broadcast_to_len(g_list, n)
            x_list = _broadcast_to_len(x_list, n)

            out_list = []
            for g, x in zip(g_list, x_list):
                out_list.append(_one_transform(g, x))

            self.Step11_Transform__GeometryOut = out_list[0] if len(out_list) == 1 else out_list
            self.Log.append('[Step11A] Transform ok.')
        except Exception as e:
            self.Step11_Transform__GeometryOut = None
            self.Log.append('[Step11A][ERROR] Transform: {}'.format(e))

        # ========== Step 11B：SplitSectionAnalyzer（剖切分析） ==========
        try:
            if SplitSectionAnalyzer is None:
                raise Exception('SplitSectionAnalyzer not available in yingzao.ancientArchi')

            # Brep <- CutTimbersByTools::2.CutTimbers（按图要求）
            brep_in = self.CutTimbersByTools_2__CutTimbers
            cutter_in = self.Step11_Transform__GeometryOut

            # PlaneRef：从 Timber_block_uniform.FacePlaneList 取 List Item
            idx_plane = self.get_param('SplitSectionAnalyzer__PlaneRef', 'SplitSectionAnalyzer__PlaneRef', 0)
            wrap_plane = self.get_param('SplitSectionAnalyzer__PlaneRef_Wrap', 'SplitSectionAnalyzer__PlaneRef_Wrap',
                                        True)
            pl_list = self.FacePlaneList
            self.SplitSectionAnalyzer__PlaneRef_Item = _list_item(pl_list, idx_plane, bool(wrap_plane))

            _refresh = bool(self.get_param('SplitSectionAnalyzer__Refresh', 'SplitSectionAnalyzer__Refresh', False))
            cap_tol = self.get_param('SplitSectionAnalyzer__CapTol', 'SplitSectionAnalyzer__CapTol', None)
            split_tol = self.get_param('SplitSectionAnalyzer__SplitTol', 'SplitSectionAnalyzer__SplitTol', None)
            poly_div_n = self.get_param('SplitSectionAnalyzer__PolylineDivN', 'SplitSectionAnalyzer__PolylineDivN', 64)
            poly_min_seg = self.get_param('SplitSectionAnalyzer__PolylineMinSeg',
                                          'SplitSectionAnalyzer__PolylineMinSeg', 0.0)
            planar_factor = self.get_param('SplitSectionAnalyzer__PlanarTolFactor',
                                           'SplitSectionAnalyzer__PlanarTolFactor', 50.0)

            # NOTE: 已移除 Step 11B 的 sticky 缓存逻辑（sc.sticky）。
            # 这里每次都会重新运行 SplitSectionAnalyzer（Refresh 参数保留但不再影响缓存命中）。
            print(brep_in)

            an = SplitSectionAnalyzer(
                brep=brep_in[0],
                cutter=cutter_in,
                cap_tol=cap_tol,
                split_tol=split_tol,
                polyline_div_n=poly_div_n,
                polyline_min_seg=poly_min_seg,
                planar_tol_factor=planar_factor,
                plane_ref=self.SplitSectionAnalyzer__PlaneRef_Item
            ).run()

            # 输出严格按组件端口保存
            self.SplitSectionAnalyzer__SortedClosedBreps = getattr(an, 'sorted_closed_breps', None)
            self.SplitSectionAnalyzer__SortedVolumes = getattr(an, 'sorted_volumes', None)
            self.SplitSectionAnalyzer__MaxClosedBrep = getattr(an, 'max_closed_brep', None)
            print(self.SplitSectionAnalyzer__MaxClosedBrep)

            self.SplitSectionAnalyzer__SectionCurves = getattr(an, 'section_curves', None)
            self.SplitSectionAnalyzer__SectionFaces = getattr(an, 'section_faces', None)
            self.SplitSectionAnalyzer__StableEdgeCurves = getattr(an, 'stable_edge_curves', None)
            self.SplitSectionAnalyzer__StableLineSegments = getattr(an, 'stable_line_segments', None)

            self.SplitSectionAnalyzer__SegmentMidPoints = getattr(an, 'segment_midpoints', None)
            self.SplitSectionAnalyzer__LowestMidPoint = getattr(an, 'lowest_midpoint', None)
            self.SplitSectionAnalyzer__HighestMidPoint = getattr(an, 'highest_midpoint', None)

            self.SplitSectionAnalyzer__MinXMidPoint = getattr(an, 'minx_midpoint', None)
            self.SplitSectionAnalyzer__MaxXMidPoint = getattr(an, 'maxx_midpoint', None)
            self.SplitSectionAnalyzer__MinYMidPoint = getattr(an, 'miny_midpoint', None)
            self.SplitSectionAnalyzer__MaxYMidPoint = getattr(an, 'maxy_midpoint', None)
            self.SplitSectionAnalyzer__MinZMidPoint = getattr(an, 'minz_midpoint', None)
            self.SplitSectionAnalyzer__MaxZMidPoint = getattr(an, 'maxz_midpoint', None)

            self.SplitSectionAnalyzer__CutterAnglesHV = getattr(an, 'cutter_angles_hv', None)
            self.SplitSectionAnalyzer__PlaneCutterCurves = getattr(an, 'plane_cutter_curves', None)
            self.SplitSectionAnalyzer__PlaneCutterMidPoint = getattr(an, 'plane_cutter_midpoint', None)
            self.SplitSectionAnalyzer__Log = to_py_list(getattr(an, 'log', []))

            self.Log.append('[Step11B] SplitSectionAnalyzer ok.')

        except Exception as e:
            self.SplitSectionAnalyzer__Log = ['[Step11B][ERROR] {}'.format(e)]
            self.Log.extend(self.SplitSectionAnalyzer__Log)

        # ========== Step 11C：RightTrianglePrismBuilder（三角棱柱刀具生成） ==========
        try:
            if RightTrianglePrismBuilder is None:
                raise Exception('RightTrianglePrismBuilder not available in yingzao.ancientArchi')

            offset_in = self.get_param('RightTrianglePrismBuilder__offset', 'RightTrianglePrismBuilder__offset', 0.0)
            h_in = self.get_param('RightTrianglePrismBuilder__h', 'RightTrianglePrismBuilder__h', 1.0)

            # theta：来自 SplitSectionAnalyzer.CutterAnglesHV，再按索引取值
            theta_idx = self.get_param('RightTrianglePrismBuilder__theta', 'RightTrianglePrismBuilder__theta', 0)
            angles_hv = self.SplitSectionAnalyzer__CutterAnglesHV
            if angles_hv is None:
                theta_val = None
            else:
                # angles_hv 期望是 [H, V] 或 tuple
                ang_list = to_py_list(angles_hv)
                theta_val = _list_item(ang_list, theta_idx, True)

            base_pt = rg.Point3d(0, 0, 0)
            ref_plane = None

            builder = RightTrianglePrismBuilder(
                theta_deg=theta_val,
                h=h_in,
                base_point=base_pt,
                ref_plane=ref_plane,
                offset=offset_in,
                tol=(sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6),
                default_plane_tag='WorldXZ'
            )
            out = builder.run()

            self.RightTrianglePrismBuilder__dist = out.get('dist', None)
            self.RightTrianglePrismBuilder__SectionCurve = out.get('SectionCurve', None)
            self.RightTrianglePrismBuilder__SectionPts = out.get('SectionPts', None)
            self.RightTrianglePrismBuilder__BrepSolid = out.get('BrepSolid', None)
            self.RightTrianglePrismBuilder__BrepParts = out.get('BrepParts', None)
            self.RightTrianglePrismBuilder__OPlanes = out.get('OPlanes', None)
            self.RightTrianglePrismBuilder__Log = to_py_list(out.get('Log', []))

            self.Log.append('[Step11C] RightTrianglePrismBuilder ok.')

        except Exception as e:
            self.RightTrianglePrismBuilder__Log = ['[Step11C][ERROR] {}'.format(e)]
            self.Log.extend(self.RightTrianglePrismBuilder__Log)

        # ========== Step 11D：List Item（从 OPlanes 抽取 SourcePlane） ==========
        # 说明（按你的反馈修正）：
        # - AlignToolToTimber::8 的 SourcePlane 应来自 RightTrianglePrismBuilder 的 OPlanes
        # - 其索引值应取自参数/输入：AlignToolToTimber_8__SourcePlane（而不是 *_SourcePlane_Index）
        # - 为兼容旧字段，若 AlignToolToTimber_8__SourcePlane 不存在/不可转为索引，则回退 *_SourcePlane_Index
        try:
            wrap_sp = self.get_param('AlignToolToTimber_8__SourcePlane_Wrap', 'AlignToolToTimber_8__SourcePlane_Wrap',
                                     True)
            planes = to_py_list(self.RightTrianglePrismBuilder__OPlanes)

            # 新优先：AlignToolToTimber_8__SourcePlane
            src_sel = self.get_param('AlignToolToTimber_8__SourcePlane', 'AlignToolToTimber_8__SourcePlane', None)

            idx_sp = None
            # 1) 若本身就是可转 int/float 的索引
            try:
                if src_sel is not None and not isinstance(src_sel, (rg.Plane,)):
                    idx_sp = int(src_sel)
            except Exception:
                idx_sp = None

            # 2) 若给的是 Plane（或 GH_Plane goo），尝试在 OPlanes 中匹配到索引
            if idx_sp is None and src_sel is not None:
                sp_plane = None
                try:
                    if isinstance(src_sel, rg.Plane):
                        sp_plane = src_sel
                    elif hasattr(src_sel, 'Value') and isinstance(src_sel.Value, rg.Plane):
                        sp_plane = src_sel.Value
                except Exception:
                    sp_plane = None

                if sp_plane is not None and planes:
                    # 用“原点接近 + 法向近似平行”做一个稳健的匹配
                    tol = (sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6)
                    best_i = None
                    best_d = None
                    try:
                        n0 = sp_plane.Normal
                    except Exception:
                        n0 = None
                    for i, pl in enumerate(planes):
                        try:
                            if hasattr(pl, 'Value') and isinstance(pl.Value, rg.Plane):
                                pl = pl.Value
                            if not isinstance(pl, rg.Plane):
                                continue
                            d = sp_plane.Origin.DistanceTo(pl.Origin)
                            if best_d is None or d < best_d:
                                # 可选法向相似约束（若拿得到）
                                ok = True
                                if n0 is not None:
                                    try:
                                        ok = abs(rg.Vector3d.Multiply(n0, pl.Normal)) > 0.999
                                    except Exception:
                                        ok = True
                                if ok:
                                    best_d = d
                                    best_i = i
                        except Exception:
                            continue
                    if best_i is not None and (best_d is None or best_d <= (tol * 10.0)):
                        idx_sp = best_i

            # 3) 仍未得出 idx，则回退旧字段
            if idx_sp is None:
                idx_sp = self.get_param('AlignToolToTimber_8__SourcePlane_Index',
                                        'AlignToolToTimber_8__SourcePlane_Index', 0)

            self.AlignToolToTimber_8__SourcePlane_Item = _list_item(planes, idx_sp, bool(wrap_sp))
            self.Log.append('[Step11D] ListItem SourcePlane ok. idx={}'.format(idx_sp))
        except Exception as e:
            self.AlignToolToTimber_8__SourcePlane_Item = None
            self.Log.append('[Step11D][ERROR] SourcePlane ListItem: {}'.format(e))

        # ========== Step 11E：AlignToolToTimber::8（对齐刀具到目标平面） ==========
        try:
            geo_in = self.RightTrianglePrismBuilder__BrepSolid
            sp_in = self.AlignToolToTimber_8__SourcePlane_Item

            # TargetPlane 计算：
            # - 取 AlignToolToTimber::7.SourcePlane（作为 Transform 的 Geometry）
            # - Transform = AlignToolToTimber::7.TransformOut
            # - Plane Origin：Origin = SplitSectionAnalyzer.PlaneCutterMidPoint
            base_plane_in = self.AlignToolToTimber_7__SourcePlane_Item
            xfm_in = self.AlignToolToTimber_7__TransformOut
            origin_pt = self.SplitSectionAnalyzer__PlaneCutterMidPoint

            # 统一 xfm
            try:
                if hasattr(xfm_in, 'Value'):
                    xfm_in = xfm_in.Value
            except Exception:
                pass

            tgt_plane = None
            if base_plane_in is not None and xfm_in is not None:
                # base_plane_in 可能是 list，按 GH 语义取第一个（此处应为单一 plane）
                bp0 = _as_broadcast_list(base_plane_in)[0]
                if isinstance(bp0, rg.Plane):
                    tgt_plane = rg.Plane(bp0)
                    try:
                        tgt_plane.Transform(xfm_in)
                    except Exception:
                        pass
                else:
                    # 兜底：若是 GH_Plane goo
                    try:
                        if hasattr(bp0, 'Value') and isinstance(bp0.Value, rg.Plane):
                            tgt_plane = rg.Plane(bp0.Value)
                            tgt_plane.Transform(xfm_in)
                    except Exception:
                        tgt_plane = None

            if tgt_plane is not None and origin_pt is not None:
                try:
                    tgt_plane.Origin = normalize_point3d(origin_pt)
                except Exception:
                    pass

            self.AlignToolToTimber_8__TargetPlane = tgt_plane

            rot_in = self.get_param('AlignToolToTimber_8__RotateDeg', 'AlignToolToTimber_8__RotateDeg', 0)
            fx_in = self.get_param('AlignToolToTimber_8__FlipX', 'AlignToolToTimber_8__FlipX', False)
            fy_in = self.get_param('AlignToolToTimber_8__FlipY', 'AlignToolToTimber_8__FlipY', False)
            fz_in = self.get_param('AlignToolToTimber_8__FlipZ', 'AlignToolToTimber_8__FlipZ', False)
            mx_in = self.get_param('AlignToolToTimber_8__MoveX', 'AlignToolToTimber_8__MoveX', 0.0)
            my_in = self.get_param('AlignToolToTimber_8__MoveY', 'AlignToolToTimber_8__MoveY', 0.0)
            mz_in = self.get_param('AlignToolToTimber_8__MoveZ', 'AlignToolToTimber_8__MoveZ', 0.0)

            so, to_, xfm, mg = GeoAligner_xfm.align(
                geo_in,
                sp_in,
                tgt_plane,
                rotate_deg=rot_in,
                flip_x=fx_in,
                flip_y=fy_in,
                flip_z=fz_in,
                move_x=mx_in,
                move_y=my_in,
                move_z=mz_in,
            )

            self.AlignToolToTimber_8__SourceOut = so
            self.AlignToolToTimber_8__TargetOut = to_
            self.AlignToolToTimber_8__TransformOut = xfm
            self.AlignToolToTimber_8__MovedGeo = mg
            self.AlignToolToTimber_8__Log = ['[Step11E] ok']
            self.Log.append('[Step11E] AlignToolToTimber::8 ok.')

        except Exception as e:
            self.AlignToolToTimber_8__SourceOut = None
            self.AlignToolToTimber_8__TargetOut = None
            self.AlignToolToTimber_8__TransformOut = None
            self.AlignToolToTimber_8__MovedGeo = None
            self.AlignToolToTimber_8__Log = ['[Step11E][ERROR] {}'.format(e)]
            self.Log.extend(self.AlignToolToTimber_8__Log)

        # ========== Step 11F：CutTimbersByTools::3（刀具切割） ==========
        try:
            if FT_CutTimbersByTools_GH_SolidDifference is None:
                raise Exception('FT_CutTimbersByTools_GH_SolidDifference not available in yingzao.ancientArchi')

            timbers_in = self.SplitSectionAnalyzer__MaxClosedBrep
            tools_in = self.AlignToolToTimber_8__MovedGeo

            keep_inside = self.get_param('CutTimbersByTools_3__KeepInside', 'CutTimbersByTools_3__KeepInside', False)
            dbg_in = self.get_param('CutTimbersByTools_3__Debug', 'CutTimbersByTools_3__Debug', None)

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(dbg_in) if dbg_in is not None else False)
            c, f, lg = cutter.cut(
                timbers=timbers_in,
                tools=tools_in,
                keep_inside=bool(keep_inside),
                debug=dbg_in
            )
            self.CutTimbersByTools_3__CutTimbers = c
            self.CutTimbersByTools_3__FailTimbers = f
            self.CutTimbersByTools_3__Log = to_py_list(lg)
            self.Log.append('[Step11F] CutTimbersByTools::3 ok.')
        except Exception as e:
            self.CutTimbersByTools_3__CutTimbers = None
            self.CutTimbersByTools_3__FailTimbers = None
            self.CutTimbersByTools_3__Log = ['[Step11F][ERROR] {}'.format(e)]
            self.Log.extend(self.CutTimbersByTools_3__Log)

    # --------------------------
    # Step 12: HuaTouZi -> AlignToolToTimber::9 -> CutTimbersByTools::4
    # --------------------------
    def step12_huatouzi_align_cut(self):
        # ========== Step 12A: HuaTouZi (build tool geometry) ==========
        try:
            if HuaTouZi is None:
                raise Exception('HuaTouZi not available in yingzao.ancientArchi')

            bp = self.get_param('HuaTouZi__base_point', 'HuaTouZi__base_point', None)
            bp = _first_not_none(bp, self.base_point, rg.Point3d.Origin)
            bp = normalize_point3d(bp)

            ref_plane_mode_in = self.get_param('ref_plane_mode', 'HuaTouZi__ref_plane_mode', 'XZ Plane')

            AB_in = self.get_param('HuaTouZi__AB', 'HuaTouZi__AB', 10.0)
            BC_in = self.get_param('HuaTouZi__BC', 'HuaTouZi__BC', 4.0)
            DE_in = self.get_param('HuaTouZi__DE', 'HuaTouZi__DE', 0.5)
            IG_in = self.get_param('HuaTouZi__IG', 'HuaTouZi__IG', 1.5)
            Offset_in = self.get_param('HuaTouZi__Offset', 'HuaTouZi__Offset', 5.0)
            Tol_in = self.get_param('HuaTouZi__Tol', 'HuaTouZi__Tol', sc.doc.ModelAbsoluteTolerance)

            # GH-style broadcast: allow AB/BC/DE/IG/Offset to be scalar or list
            AB_l = _as_broadcast_list(AB_in)
            BC_l = _as_broadcast_list(BC_in)
            DE_l = _as_broadcast_list(DE_in)
            IG_l = _as_broadcast_list(IG_in)
            Off_l = _as_broadcast_list(Offset_in)
            rp_l = _as_broadcast_list(ref_plane_mode_in)

            n = max(len(AB_l), len(BC_l), len(DE_l), len(IG_l), len(Off_l), len(rp_l), 1)
            AB_l = _broadcast_to_len(AB_l, n)
            BC_l = _broadcast_to_len(BC_l, n)
            DE_l = _broadcast_to_len(DE_l, n)
            IG_l = _broadcast_to_len(IG_l, n)
            Off_l = _broadcast_to_len(Off_l, n)
            rp_l = _broadcast_to_len(rp_l, n)

            solids = []
            sec_crvs = []
            sec_pos = []
            sec_neg = []
            lofts = []
            caps_p = []
            caps_n = []
            logs = []
            pts_b = []
            pl_abx = []

            for i in range(n):
                ht = HuaTouZi(base_point=bp, ref_plane_mode=rp_l[i], tol=float(Tol_in))
                ht.set_params(
                    AB=float(AB_l[i]),
                    BC=float(BC_l[i]),
                    DE=float(DE_l[i]),
                    IG=float(IG_l[i]),
                    Offset=float(Off_l[i]),
                    Tol=float(Tol_in),
                )
                ht.build(reset=True)

                solids.append(ht.solid_brep)
                sec_crvs.append(ht.section_crv)
                sec_pos.append(ht.section_crv_pos)
                sec_neg.append(ht.section_crv_neg)
                lofts.append(ht.loft_brep)
                caps_p.append(ht.cap_pos_brep)
                caps_n.append(ht.cap_neg_brep)
                logs.append(to_py_list(ht.log))
                pts_b.append(ht.B)
                pl_abx.append(ht.plane_at_b_x)

            # Preserve list structure; also keep a flat view where helpful
            self.HuaTouZi__SolidBrep = solids if n > 1 else solids[0]
            self.HuaTouZi__SectionCrv = sec_crvs if n > 1 else sec_crvs[0]
            self.HuaTouZi__SectionCrv_Pos = sec_pos if n > 1 else sec_pos[0]
            self.HuaTouZi__SectionCrv_Neg = sec_neg if n > 1 else sec_neg[0]
            self.HuaTouZi__LoftBrep = lofts if n > 1 else lofts[0]
            self.HuaTouZi__CapPosBrep = caps_p if n > 1 else caps_p[0]
            self.HuaTouZi__CapNegBrep = caps_n if n > 1 else caps_n[0]
            self.HuaTouZi__Log = logs
            self.HuaTouZi__Pts_B = pts_b if n > 1 else pts_b[0]
            self.HuaTouZi__PlaneAB_X = pl_abx if n > 1 else pl_abx[0]

            self.Log.append('[Step12A] HuaTouZi ok. count={}'.format(n))
        except Exception as e:
            self.HuaTouZi__SolidBrep = None
            self.HuaTouZi__SectionCrv = None
            self.HuaTouZi__SectionCrv_Pos = None
            self.HuaTouZi__SectionCrv_Neg = None
            self.HuaTouZi__LoftBrep = None
            self.HuaTouZi__CapPosBrep = None
            self.HuaTouZi__CapNegBrep = None
            self.HuaTouZi__Log = ['[Step12A][ERROR] {}'.format(e)]
            self.HuaTouZi__Pts_B = None
            self.HuaTouZi__PlaneAB_X = None
            self.Log.extend(to_py_list(self.HuaTouZi__Log))
            return

        # ========== Step 12B: AlignToolToTimber::9 (align tool to target plane) ==========
        try:
            geo_in = self.HuaTouZi__SolidBrep
            sp_in = self.HuaTouZi__PlaneAB_X

            # TargetPlane MUST be identical to the input TargetPlane used by AlignToolToTimber::8
            tp_in = self.AlignToolToTimber_8__TargetPlane

            rot_in = self.get_param('AlignToolToTimber_9__RotateDeg', 'AlignToolToTimber_9__RotateDeg', 0)
            fx_in = self.get_param('AlignToolToTimber_9__FlipX', 'AlignToolToTimber_9__FlipX', False)
            fy_in = self.get_param('AlignToolToTimber_9__FlipY', 'AlignToolToTimber_9__FlipY', False)
            fz_in = self.get_param('AlignToolToTimber_9__FlipZ', 'AlignToolToTimber_9__FlipZ', False)

            # MoveX = - RightTrianglePrismBuilder__dist
            dist = self.RightTrianglePrismBuilder__dist
            try:
                dist_f = float(dist) if dist is not None else 0.0
            except Exception:
                dist_f = 0.0
            mx_in = -dist_f

            my_in = self.get_param('AlignToolToTimber_9__MoveY', 'AlignToolToTimber_9__MoveY', 0.0)
            mz_in = self.get_param('AlignToolToTimber_9__MoveZ', 'AlignToolToTimber_9__MoveZ', 0.0)

            geo_l = _as_broadcast_list(geo_in)
            sp_l = _as_broadcast_list(sp_in)
            tp_l = _as_broadcast_list(tp_in)

            n = max(len(geo_l), len(sp_l), len(tp_l), 1)
            geo_l = _broadcast_to_len(geo_l, n)
            sp_l = _broadcast_to_len(sp_l, n)
            tp_l = _broadcast_to_len(tp_l, n)

            so_list = []
            to_list = []
            xfm_list = []
            mg_list = []

            for i in range(n):
                so, to_, xfm, mg = GeoAligner_xfm.align(
                    geo_l[i],
                    sp_l[i],
                    tp_l[i],
                    rotate_deg=rot_in,
                    flip_x=fx_in,
                    flip_y=fy_in,
                    flip_z=fz_in,
                    move_x=mx_in,
                    move_y=my_in,
                    move_z=mz_in,
                )
                so_list.append(so)
                to_list.append(to_)
                xfm_list.append(xfm)
                mg_list.append(mg)

            self.AlignToolToTimber_9__SourceOut = so_list if n > 1 else so_list[0]
            self.AlignToolToTimber_9__TargetOut = to_list if n > 1 else to_list[0]
            self.AlignToolToTimber_9__TransformOut = xfm_list if n > 1 else xfm_list[0]
            self.AlignToolToTimber_9__MovedGeo = mg_list if n > 1 else mg_list[0]
            self.AlignToolToTimber_9__Log = ['[Step12B] ok']
            self.Log.append('[Step12B] AlignToolToTimber::9 ok. count={}'.format(n))

        except Exception as e:
            self.AlignToolToTimber_9__SourceOut = None
            self.AlignToolToTimber_9__TargetOut = None
            self.AlignToolToTimber_9__TransformOut = None
            self.AlignToolToTimber_9__MovedGeo = None
            self.AlignToolToTimber_9__Log = ['[Step12B][ERROR] {}'.format(e)]
            self.Log.extend(to_py_list(self.AlignToolToTimber_9__Log))
            return

        # ========== Step 12C: CutTimbersByTools::4 (cut timbers using aligned HuaTouZi tool) ==========
        try:
            if FT_CutTimbersByTools_GH_SolidDifference is None:
                raise Exception('FT_CutTimbersByTools_GH_SolidDifference not available in yingzao.ancientArchi')

            timbers_in = self.CutTimbersByTools_3__CutTimbers
            tools_in = self.AlignToolToTimber_9__MovedGeo

            # Ensure python lists (also convert DataTree)
            timbers_list = gh_tree_to_list(timbers_in)
            if len(timbers_list) == 0 and timbers_in is not None:
                timbers_list = to_py_list(timbers_in)
            timbers_list = flatten_any(timbers_list)

            tools_list = gh_tree_to_list(tools_in)
            if len(tools_list) == 0 and tools_in is not None:
                tools_list = to_py_list(tools_in)
            tools_list = flatten_any(tools_list)

            keep_inside = self.get_param('CutTimbersByTools_4__KeepInside', 'CutTimbersByTools_4__KeepInside', False)
            dbg_in = self.get_param('CutTimbersByTools_4__Debug', 'CutTimbersByTools_4__Debug', None)

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(dbg_in) if dbg_in is not None else False)
            c, f, lg = cutter.cut(
                timbers=timbers_list,
                tools=tools_list,
                keep_inside=bool(keep_inside),
                debug=dbg_in
            )

            self.CutTimbersByTools_4__CutTimbers = c
            self.CutTimbersByTools_4__FailTimbers = f
            self.CutTimbersByTools_4__Log = to_py_list(lg)
            self.Log.append('[Step12C] CutTimbersByTools::4 ok.')

        except Exception as e:
            self.CutTimbersByTools_4__CutTimbers = None
            self.CutTimbersByTools_4__FailTimbers = None
            self.CutTimbersByTools_4__Log = ['[Step12C][ERROR] {}'.format(e)]
            self.Log.extend(to_py_list(self.CutTimbersByTools_4__Log))

    # --------------------------
    # 主入口
    # --------------------------
    def solve(self):
        self.step1_read_db()
        self.step2_build_timber()

        # Step 3（增量）：卷杀刀具生成 + 定位平面提取 + 对齐
        self.step3_juansha_plane_align()

        # Step 4（增量）：BlockCutter 刀具木料块 + 取面平面 + Tree 对齐
        self.step4_blockcutter_aligntool()

        # Step 5（增量）：BlockCutter::2 + ListItem + GeoAligner::3
        self.step5_blockcutter2_geoaligner3()

        # Step 6（增量）：AxisLinesIntersectionsSolver + SectionExtrude_SymmetricTrapezoid + AlignToolToTimber::4
        self.step6_axis_section_align()

        # Step 7（增量）：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + AlignToolToTimber::5
        self.step7_qiao_tool_plane_align()

        # Step 8（增量）：GongYan + PlaneFromLists::4 + ListItem + AlignToolToTimber::6
        self.step8_gongyan_plane_align()

        # Step 9（增量）：ChaAng4PU 黑盒 -> ListItem×2 -> AlignToolToTimber::7 -> CutTimbersByTools::1
        self.step9_chaang4pu_align_and_cut()

        # Step 10（增量）：CutTimbersByTools::2（主木坯 + 多刀具合并切割）
        self.step10_cut_timbers_by_tools2()

        # Step 11（增量）：SplitSectionAnalyzer -> RightTrianglePrismBuilder -> AlignToolToTimber::8 -> CutTimbersByTools::3
        # 注意：本步骤仅产出 developer-friendly 中间结果，不改变默认最终输出策略
        self.step11_split_prism_align_cut()

        # Step 12 (incremental): HuaTouZi -> AlignToolToTimber::9 -> CutTimbersByTools::4
        self.step12_huatouzi_align_cut()

        # 默认输出：优先 Step12，其次 Step10，其次 Step9；否则回落为主木坯，其次 Step9；否则回落为主木坯
        if self.CutTimbersByTools_4__CutTimbers is not None:
            self.CutTimbers = flatten_any(self.CutTimbersByTools_4__CutTimbers)
            self.FailTimbers = flatten_any(self.CutTimbersByTools_4__FailTimbers)
        elif self.CutTimbersByTools_2__CutTimbers is not None:
            self.CutTimbers = flatten_any(self.CutTimbersByTools_2__CutTimbers)
            self.FailTimbers = flatten_any(self.CutTimbersByTools_2__FailTimbers)
        elif self.CutTimbersByTools_1__CutTimbers is not None:
            self.CutTimbers = flatten_any(self.CutTimbersByTools_1__CutTimbers)
            self.FailTimbers = flatten_any(self.CutTimbersByTools_1__FailTimbers)
        else:
            self.CutTimbers = flatten_any(self.TimberBrep)
            self.FailTimbers = []

        # 汇总日志
        self.Log.extend(self.DBLog)
        self.Log.extend(self.TimberLog)
        self.Log.extend(self.Juansha__Log)
        self.Log.extend(self.PlaneFromLists_1__Log)
        self.Log.extend(self.AlignToolToTimber_1__Log)
        self.Log.extend(self.BlockCutter_1__Log)
        # ListItem 本身无独立 Log（出错已写入 self.Log），这里保持结构一致
        self.Log.extend(self.AlignToolToTimber_2__Log)
        self.Log.extend(self.BlockCutter_2__Log)
        self.Log.extend(self.GeoAligner_3__Log)
        self.Log.extend(self.AxisLinesIntersectionsSolver__Log)
        self.Log.extend(self.SectionExtrude_SymmetricTrapezoid__log)
        self.Log.extend(self.AlignToolToTimber_4__Log)

        # Step 7
        self.Log.extend(self.QiAOTool__Log)
        self.Log.extend(self.PlaneFromLists_2__Log)
        self.Log.extend(self.PlaneFromLists_3__Log)
        self.Log.extend(self.AlignToolToTimber_5__Log)

        # Step 8
        self.Log.extend(self.GongYan__Log)
        self.Log.extend(self.PlaneFromLists_4__Log)
        self.Log.extend(self.AlignToolToTimber_6__Log)

        # Step 9
        self.Log.extend(to_py_list(self.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log))
        self.Log.extend(self.AlignToolToTimber_7__Log)
        self.Log.extend(to_py_list(self.CutTimbersByTools_1__Log))

        # Step 10
        self.Log.extend(to_py_list(self.CutTimbersByTools_2__Log))

        # Step 11
        self.Log.extend(to_py_list(self.SplitSectionAnalyzer__Log))
        self.Log.extend(to_py_list(self.RightTrianglePrismBuilder__Log))
        self.Log.extend(to_py_list(self.AlignToolToTimber_8__Log))
        self.Log.extend(to_py_list(self.CutTimbersByTools_3__Log))

        # Step 12
        self.Log.extend(to_py_list(self.HuaTouZi__Log))
        self.Log.extend(to_py_list(self.AlignToolToTimber_9__Log))
        self.Log.extend(to_py_list(self.CutTimbersByTools_4__Log))

if __name__=="__main__":
    # ==============================================================
    # GhPython 组件入口
    #   假定已在组件中声明以下输入：
    #       DBPath, base_point, Refresh
    #   并声明输出（最少）：
    #       CutTimbers, FailTimbers, Log
    #   以及（开发模式）你可以按需增加同名输出端口来接收下述变量
    # ==============================================================

    solver = JiaoAngInLineWJiaoHuaGongSolver(DBPath, base_point, Refresh, ghenv=ghenv)
    solver.solve()

    # --------------------------
    # 必要输出（用户要求）
    # --------------------------
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --------------------------
    # GH Python 组件 · 输出绑定区（developer-friendly）
    # 说明：
    # - 只要你在 GH 里新增一个输出端口并命名为下列任意同名变量，
    #   即可直接看到内部中间结果（便于逐步转换时调试）。
    # - 若未来出现重名变量，将按“组件名_端口名”规则继续前缀化处理。
    # --------------------------
    # Step 1
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # Step 2
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
    TimberLog = solver.TimberLog

    # Step 3
    Juansha_ToolBrep = solver.Juansha__ToolBrep
    Juansha_SectionEdges = solver.Juansha__SectionEdges
    Juansha_Intersection = solver.Juansha__Intersection
    Juansha_HeightFacePlane = solver.Juansha__HeightFacePlane
    Juansha_LengthFacePlane = solver.Juansha__LengthFacePlane
    Juansha_Log = solver.Juansha__Log

    PlaneFromLists_1_BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1_OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1_ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1_Log = solver.PlaneFromLists_1__Log

    AlignToolToTimber_1_SourceOut = solver.AlignToolToTimber_1__SourceOut
    AlignToolToTimber_1_TargetOut = solver.AlignToolToTimber_1__TargetOut
    AlignToolToTimber_1_MovedGeo = solver.AlignToolToTimber_1__MovedGeo
    AlignToolToTimber_1_TransformOut = solver.AlignToolToTimber_1__TransformOut
    AlignToolToTimber_1_Log = solver.AlignToolToTimber_1__Log

    # Step 4
    BlockCutter_1_TimberBrep = solver.BlockCutter_1__TimberBrep
    BlockCutter_1_FacePlaneList = solver.BlockCutter_1__FacePlaneList
    BlockCutter_1_EdgeMidPoints = solver.BlockCutter_1__EdgeMidPoints
    BlockCutter_1_Corner0Planes = solver.BlockCutter_1__Corner0Planes
    BlockCutter_1_LocalAxesPlane = solver.BlockCutter_1__LocalAxesPlane
    BlockCutter_1_PointList = solver.BlockCutter_1__PointList
    BlockCutter_1_EdgeList = solver.BlockCutter_1__EdgeList
    BlockCutter_1_FaceList = solver.BlockCutter_1__FaceList
    BlockCutter_1_Log = solver.BlockCutter_1__Log

    ListItem_SourcePlane_Item = solver.ListItem_SourcePlane__Item
    ListItem_TargetPlane_Item = solver.ListItem_TargetPlane__Item

    AlignToolToTimber_2_SourceOut = solver.AlignToolToTimber_2__SourceOut
    AlignToolToTimber_2_TargetOut = solver.AlignToolToTimber_2__TargetOut
    AlignToolToTimber_2_MovedGeo = solver.AlignToolToTimber_2__MovedGeo
    AlignToolToTimber_2_TransformOut = solver.AlignToolToTimber_2__TransformOut
    AlignToolToTimber_2_Log = solver.AlignToolToTimber_2__Log

    # Step 5
    BlockCutter_2_TimberBrep = solver.BlockCutter_2__TimberBrep
    BlockCutter_2_FacePlaneList = solver.BlockCutter_2__FacePlaneList
    BlockCutter_2_EdgeMidPoints = solver.BlockCutter_2__EdgeMidPoints
    BlockCutter_2_Corner0Planes = solver.BlockCutter_2__Corner0Planes
    BlockCutter_2_LocalAxesPlane = solver.BlockCutter_2__LocalAxesPlane
    BlockCutter_2_PointList = solver.BlockCutter_2__PointList
    BlockCutter_2_EdgeList = solver.BlockCutter_2__EdgeList
    BlockCutter_2_FaceList = solver.BlockCutter_2__FaceList
    BlockCutter_2_Log = solver.BlockCutter_2__Log

    GeoAligner_3_SourcePlane_Item = solver.GeoAligner_3__SourcePlane_Item
    GeoAligner_3_TargetPlane_Item = solver.GeoAligner_3__TargetPlane_Item
    GeoAligner_3_SourceOut = solver.GeoAligner_3__SourceOut
    GeoAligner_3_TargetOut = solver.GeoAligner_3__TargetOut
    GeoAligner_3_MovedGeo = solver.GeoAligner_3__MovedGeo
    GeoAligner_3_TransformOut = solver.GeoAligner_3__TransformOut
    GeoAligner_3_Log = solver.GeoAligner_3__Log

    # Step 6
    AxisLinesIntersectionsSolver_Axis_AO = solver.AxisLinesIntersectionsSolver__Axis_AO
    AxisLinesIntersectionsSolver_Axis_AC = solver.AxisLinesIntersectionsSolver__Axis_AC
    AxisLinesIntersectionsSolver_Axis_AD = solver.AxisLinesIntersectionsSolver__Axis_AD
    AxisLinesIntersectionsSolver_L1 = solver.AxisLinesIntersectionsSolver__L1
    AxisLinesIntersectionsSolver_L2 = solver.AxisLinesIntersectionsSolver__L2
    AxisLinesIntersectionsSolver_L3 = solver.AxisLinesIntersectionsSolver__L3
    AxisLinesIntersectionsSolver_L4 = solver.AxisLinesIntersectionsSolver__L4
    AxisLinesIntersectionsSolver_L5 = solver.AxisLinesIntersectionsSolver__L5
    AxisLinesIntersectionsSolver_L6 = solver.AxisLinesIntersectionsSolver__L6
    AxisLinesIntersectionsSolver_O = solver.AxisLinesIntersectionsSolver__O_out
    AxisLinesIntersectionsSolver_A = solver.AxisLinesIntersectionsSolver__A
    AxisLinesIntersectionsSolver_B = solver.AxisLinesIntersectionsSolver__B
    AxisLinesIntersectionsSolver_J = solver.AxisLinesIntersectionsSolver__J
    AxisLinesIntersectionsSolver_K = solver.AxisLinesIntersectionsSolver__K
    AxisLinesIntersectionsSolver_Jp = solver.AxisLinesIntersectionsSolver__Jp
    AxisLinesIntersectionsSolver_Kp = solver.AxisLinesIntersectionsSolver__Kp
    AxisLinesIntersectionsSolver_Dist_BJ = solver.AxisLinesIntersectionsSolver__Dist_BJ
    AxisLinesIntersectionsSolver_Dist_JK = solver.AxisLinesIntersectionsSolver__Dist_JK
    AxisLinesIntersectionsSolver_Log = solver.AxisLinesIntersectionsSolver__Log

    SectionExtrude_SymmetricTrapezoid_A = solver.SectionExtrude_SymmetricTrapezoid__A
    SectionExtrude_SymmetricTrapezoid_B = solver.SectionExtrude_SymmetricTrapezoid__B
    SectionExtrude_SymmetricTrapezoid_C = solver.SectionExtrude_SymmetricTrapezoid__C
    SectionExtrude_SymmetricTrapezoid_D = solver.SectionExtrude_SymmetricTrapezoid__D
    SectionExtrude_SymmetricTrapezoid_O = solver.SectionExtrude_SymmetricTrapezoid__O
    SectionExtrude_SymmetricTrapezoid_E = solver.SectionExtrude_SymmetricTrapezoid__E
    SectionExtrude_SymmetricTrapezoid_Oprime = solver.SectionExtrude_SymmetricTrapezoid__Oprime
    SectionExtrude_SymmetricTrapezoid_AB = solver.SectionExtrude_SymmetricTrapezoid__AB
    SectionExtrude_SymmetricTrapezoid_CD = solver.SectionExtrude_SymmetricTrapezoid__CD
    SectionExtrude_SymmetricTrapezoid_AC = solver.SectionExtrude_SymmetricTrapezoid__AC
    SectionExtrude_SymmetricTrapezoid_BD = solver.SectionExtrude_SymmetricTrapezoid__BD
    SectionExtrude_SymmetricTrapezoid_section_polyline = solver.SectionExtrude_SymmetricTrapezoid__section_polyline
    SectionExtrude_SymmetricTrapezoid_section_curve = solver.SectionExtrude_SymmetricTrapezoid__section_curve
    SectionExtrude_SymmetricTrapezoid_solid_list = solver.SectionExtrude_SymmetricTrapezoid__solid_list
    SectionExtrude_SymmetricTrapezoid_Plane_Oprime = solver.SectionExtrude_SymmetricTrapezoid__Plane_Oprime
    SectionExtrude_SymmetricTrapezoid_Plane_Oprime_X = solver.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_X
    SectionExtrude_SymmetricTrapezoid_Plane_Oprime_Y = solver.SectionExtrude_SymmetricTrapezoid__Plane_Oprime_Y
    SectionExtrude_SymmetricTrapezoid_Log = solver.SectionExtrude_SymmetricTrapezoid__log

    AlignToolToTimber_4_TargetPlane_Item = solver.AlignToolToTimber_4__TargetPlane_Item
    AlignToolToTimber_4_SourceOut = solver.AlignToolToTimber_4__SourceOut
    AlignToolToTimber_4_TargetOut = solver.AlignToolToTimber_4__TargetOut
    AlignToolToTimber_4_MovedGeo = solver.AlignToolToTimber_4__MovedGeo
    AlignToolToTimber_4_TransformOut = solver.AlignToolToTimber_4__TransformOut
    AlignToolToTimber_4_Log = solver.AlignToolToTimber_4__Log

    # Step 7
    QiAOTool_CutTimbers = solver.QiAOTool__CutTimbers
    QiAOTool_FailTimbers = solver.QiAOTool__FailTimbers
    QiAOTool_EdgeMidPoints = solver.QiAOTool__EdgeMidPoints
    QiAOTool_Corner0Planes = solver.QiAOTool__Corner0Planes
    QiAOTool_Log = solver.QiAOTool__Log

    PlaneFromLists_2_BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2_OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2_ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2_Log = solver.PlaneFromLists_2__Log

    PlaneFromLists_3_BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3_OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3_ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3_Log = solver.PlaneFromLists_3__Log

    AlignToolToTimber_5_SourceOut = solver.AlignToolToTimber_5__SourceOut
    AlignToolToTimber_5_TargetOut = solver.AlignToolToTimber_5__TargetOut
    AlignToolToTimber_5_MovedGeo = solver.AlignToolToTimber_5__MovedGeo
    AlignToolToTimber_5_TransformOut = solver.AlignToolToTimber_5__TransformOut
    AlignToolToTimber_5_Log = solver.AlignToolToTimber_5__Log

    # Step 8
    GongYan_ToolBrep = solver.GongYan__ToolBrep
    GongYan_SectionCurve = solver.GongYan__SectionCurve
    GongYan_SectionFace = solver.GongYan__SectionFace
    GongYan_LeftCurve = solver.GongYan__LeftCurve
    GongYan_RightCurve = solver.GongYan__RightCurve
    GongYan_SymmetryAxis = solver.GongYan__SymmetryAxis
    GongYan_AllPoints = solver.GongYan__AllPoints
    GongYan_SectionPlanes = solver.GongYan__SectionPlanes
    GongYan_Log = solver.GongYan__Log

    PlaneFromLists_4_BasePlane = solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4_OriginPoint = solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4_ResultPlane = solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4_Log = solver.PlaneFromLists_4__Log

    AlignToolToTimber_6_SourcePlane_Item = solver.AlignToolToTimber_6__SourcePlane_Item
    AlignToolToTimber_6_SourceOut = solver.AlignToolToTimber_6__SourceOut
    AlignToolToTimber_6_TargetOut = solver.AlignToolToTimber_6__TargetOut
    AlignToolToTimber_6_MovedGeo = solver.AlignToolToTimber_6__MovedGeo
    AlignToolToTimber_6_TransformOut = solver.AlignToolToTimber_6__TransformOut
    AlignToolToTimber_6_Log = solver.AlignToolToTimber_6__Log

    # Step 9
    ChaAng4PU_CutTimbers = solver.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__CutTimbers
    ChaAng4PU_FailTimbers = solver.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__FailTimbers
    ChaAng4PU_Log = solver.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__Log
    ChaAng4PU_RefPlanes = solver.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__RefPlanes
    ChaAng4PU_SolidFace_AE = solver.ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver__SolidFace_AE

    AlignToolToTimber_7_SourcePlane_Item = solver.AlignToolToTimber_7__SourcePlane_Item
    AlignToolToTimber_7_TargetPlane_Item = solver.AlignToolToTimber_7__TargetPlane_Item
    AlignToolToTimber_7_SourceOut = solver.AlignToolToTimber_7__SourceOut
    AlignToolToTimber_7_TargetOut = solver.AlignToolToTimber_7__TargetOut
    AlignToolToTimber_7_MovedGeo = solver.AlignToolToTimber_7__MovedGeo
    AlignToolToTimber_7_TransformOut = solver.AlignToolToTimber_7__TransformOut
    AlignToolToTimber_7_Log = solver.AlignToolToTimber_7__Log

    CutTimbersByTools_1_CutTimbers = solver.CutTimbersByTools_1__CutTimbers
    CutTimbersByTools_1_FailTimbers = solver.CutTimbersByTools_1__FailTimbers
    CutTimbersByTools_1_Log = solver.CutTimbersByTools_1__Log

    # Step 10
    CutTimbersByTools_2_CutTimbers = solver.CutTimbersByTools_2__CutTimbers
    CutTimbersByTools_2_FailTimbers = solver.CutTimbersByTools_2__FailTimbers
    CutTimbersByTools_2_Log = solver.CutTimbersByTools_2__Log

    # Step 11
    Step11_Transform_GeometryIn = solver.Step11_Transform__GeometryIn
    Step11_Transform_TransformIn = solver.Step11_Transform__TransformIn
    Step11_Transform_GeometryOut = solver.Step11_Transform__GeometryOut

    SplitSectionAnalyzer_PlaneRef_Item = solver.SplitSectionAnalyzer__PlaneRef_Item
    SplitSectionAnalyzer_SortedClosedBreps = solver.SplitSectionAnalyzer__SortedClosedBreps
    SplitSectionAnalyzer_SortedVolumes = solver.SplitSectionAnalyzer__SortedVolumes
    SplitSectionAnalyzer_MaxClosedBrep = solver.SplitSectionAnalyzer__MaxClosedBrep
    SplitSectionAnalyzer_SectionCurves = solver.SplitSectionAnalyzer__SectionCurves
    SplitSectionAnalyzer_SectionFaces = solver.SplitSectionAnalyzer__SectionFaces
    SplitSectionAnalyzer_StableEdgeCurves = solver.SplitSectionAnalyzer__StableEdgeCurves
    SplitSectionAnalyzer_StableLineSegments = solver.SplitSectionAnalyzer__StableLineSegments
    SplitSectionAnalyzer_SegmentMidPoints = solver.SplitSectionAnalyzer__SegmentMidPoints
    SplitSectionAnalyzer_LowestMidPoint = solver.SplitSectionAnalyzer__LowestMidPoint
    SplitSectionAnalyzer_HighestMidPoint = solver.SplitSectionAnalyzer__HighestMidPoint
    SplitSectionAnalyzer_MinXMidPoint = solver.SplitSectionAnalyzer__MinXMidPoint
    SplitSectionAnalyzer_MaxXMidPoint = solver.SplitSectionAnalyzer__MaxXMidPoint
    SplitSectionAnalyzer_MinYMidPoint = solver.SplitSectionAnalyzer__MinYMidPoint
    SplitSectionAnalyzer_MaxYMidPoint = solver.SplitSectionAnalyzer__MaxYMidPoint
    SplitSectionAnalyzer_MinZMidPoint = solver.SplitSectionAnalyzer__MinZMidPoint
    SplitSectionAnalyzer_MaxZMidPoint = solver.SplitSectionAnalyzer__MaxZMidPoint
    SplitSectionAnalyzer_CutterAnglesHV = solver.SplitSectionAnalyzer__CutterAnglesHV
    SplitSectionAnalyzer_PlaneCutterCurves = solver.SplitSectionAnalyzer__PlaneCutterCurves
    SplitSectionAnalyzer_PlaneCutterMidPoint = solver.SplitSectionAnalyzer__PlaneCutterMidPoint
    SplitSectionAnalyzer_Log = solver.SplitSectionAnalyzer__Log

    RightTrianglePrismBuilder_dist = solver.RightTrianglePrismBuilder__dist
    RightTrianglePrismBuilder_SectionCurve = solver.RightTrianglePrismBuilder__SectionCurve
    RightTrianglePrismBuilder_SectionPts = solver.RightTrianglePrismBuilder__SectionPts
    RightTrianglePrismBuilder_BrepSolid = solver.RightTrianglePrismBuilder__BrepSolid
    RightTrianglePrismBuilder_BrepParts = solver.RightTrianglePrismBuilder__BrepParts
    RightTrianglePrismBuilder_OPlanes = solver.RightTrianglePrismBuilder__OPlanes
    RightTrianglePrismBuilder_Log = solver.RightTrianglePrismBuilder__Log

    AlignToolToTimber_8_SourcePlane_Item = solver.AlignToolToTimber_8__SourcePlane_Item
    AlignToolToTimber_8_TargetPlane = solver.AlignToolToTimber_8__TargetPlane
    AlignToolToTimber_8_SourceOut = solver.AlignToolToTimber_8__SourceOut
    AlignToolToTimber_8_TargetOut = solver.AlignToolToTimber_8__TargetOut
    AlignToolToTimber_8_MovedGeo = solver.AlignToolToTimber_8__MovedGeo
    AlignToolToTimber_8_TransformOut = solver.AlignToolToTimber_8__TransformOut
    AlignToolToTimber_8_Log = solver.AlignToolToTimber_8__Log

    CutTimbersByTools_3_CutTimbers = solver.CutTimbersByTools_3__CutTimbers
    CutTimbersByTools_3_FailTimbers = solver.CutTimbersByTools_3__FailTimbers
    CutTimbersByTools_3_Log = solver.CutTimbersByTools_3__Log

    # Step 12
    HuaTouZi_SolidBrep = solver.HuaTouZi__SolidBrep
    HuaTouZi_SectionCrv = solver.HuaTouZi__SectionCrv
    HuaTouZi_SectionCrv_Pos = solver.HuaTouZi__SectionCrv_Pos
    HuaTouZi_SectionCrv_Neg = solver.HuaTouZi__SectionCrv_Neg
    HuaTouZi_LoftBrep = solver.HuaTouZi__LoftBrep
    HuaTouZi_CapPosBrep = solver.HuaTouZi__CapPosBrep
    HuaTouZi_CapNegBrep = solver.HuaTouZi__CapNegBrep
    HuaTouZi_Log = solver.HuaTouZi__Log
    HuaTouZi_Pts_B = solver.HuaTouZi__Pts_B
    HuaTouZi_PlaneAB_X = solver.HuaTouZi__PlaneAB_X

    AlignToolToTimber_9_SourceOut = solver.AlignToolToTimber_9__SourceOut
    AlignToolToTimber_9_TargetOut = solver.AlignToolToTimber_9__TargetOut
    AlignToolToTimber_9_MovedGeo = solver.AlignToolToTimber_9__MovedGeo
    AlignToolToTimber_9_TransformOut = solver.AlignToolToTimber_9__TransformOut
    AlignToolToTimber_9_Log = solver.AlignToolToTimber_9__Log

    CutTimbersByTools_4_CutTimbers = solver.CutTimbersByTools_4__CutTimbers
    CutTimbersByTools_4_FailTimbers = solver.CutTimbersByTools_4__FailTimbers
    CutTimbersByTools_4_Log = solver.CutTimbersByTools_4__Log

    CutTimbers = [CutTimbersByTools_1_CutTimbers[0], CutTimbersByTools_4_CutTimbers[0]]

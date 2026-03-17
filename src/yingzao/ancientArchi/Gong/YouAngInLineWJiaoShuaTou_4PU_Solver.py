# -*- coding: utf-8 -*-
"""
YouAngInLineWJiaoShuaTou_4PU_Solver.ghpy
=============================================================
将用于构建「由昂與角耍頭相列（YouAngInLineWJiaoShuaTou_4PU）」的一组 ghpy 自定义组件
逐步转换为一个单一 GhPython 组件（Solver 模式）。

⚠️ 本文件目前实现到：
    Step1 = DBJsonReader（读取 DG_Dou.params_json → Value/All/AllDict）
    Step2 = TimberBlock_SkewAxis_M（BuildTimberBlockUniform_SkewAxis_M）

后续 Step 将按你继续提供的“组件名 + 组件代码 + GH 连线规则”继续增量添加，
并保持：不动已完成部分，只增量扩展。

输入端（GH Inputs，建议按此命名）：
-------------------------------------------------------------
DBPath      : str       # SQLite 数据库路径
base_point  : Point3d   # 木料定位点（无则用世界原点）
Refresh     : bool/int  # 刷新（触发重读数据库等）

输出端（GH Outputs，最少需要）：
-------------------------------------------------------------
CutTimbers  : list[object]   # 最终木料（后续步骤切割完成后输出）
FailTimbers : list[object]   # 失败木料
Log         : list[str]      # 全局日志

开发模式输出（developer-friendly）：
-------------------------------------------------------------
你可以在 GH 输出端自己添加任意同名端口，本脚本会在“输出绑定区”把 solver 成员变量
按同名变量赋值出来；若你添加了同名输出端，就能直接看到内部中间结果。

作者: richiebao [coding-x.tech]
版本: 2026.01.21
"""

from __future__ import division

import Rhino.Geometry as rg

# yingzao.ancientArchi 自定义库（按要求：直接调用，不重复造轮子）
from yingzao.ancientArchi import DBJsonReader
from yingzao.ancientArchi import BuildTimberBlockUniform_SkewAxis_M
from yingzao.ancientArchi import build_timber_block_uniform
from yingzao.ancientArchi import FTPlaneFromLists
from yingzao.ancientArchi import GeoAligner_xfm
from yingzao.ancientArchi import QiAoToolSolver, InputHelper, GHPlaneFactory
from yingzao.ancientArchi import AxisLinesIntersectionsSolver
from yingzao.ancientArchi import SectionExtrude_SymmetricTrapezoid

from yingzao.ancientArchi import FT_CutTimbersByTools_GH_SolidDifference
from yingzao.ancientArchi import SplitSectionAnalyzer as SplitSectionAnalyzer_Runner

import scriptcontext as sc
import math

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.21"


# ==============================================================
# 通用工具函数（参考 LingGongSolver 风格，适度裁剪）
# ==============================================================

def to_py_list(x):
    """尽量把 GH / .NET List / IEnumerable 转成 Python list；None -> []。"""
    if x is None:
        return []
    # GH DataTree（Rhino 的 GH_Structure 形态）通常有 BranchCount/Branch
    if hasattr(x, "BranchCount") and hasattr(x, "Branch"):
        out = []
        try:
            for i in range(int(x.BranchCount)):
                br = x.Branch(i)
                out.append(list(br) if br is not None else [])
        except Exception:
            pass
        return out
    # .NET List
    try:
        return list(x)
    except Exception:
        return [x]


def flatten_any(x):
    """
    递归拍平 list/tuple/NET List；保留 None。
    解决你提到的：
    System.Collections.Generic.List`1[System.Object] ...
    """
    out = []
    if x is None:
        return out
    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out
    # .NET List 或 IEnumerable
    if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
        try:
            for it in x:
                out.extend(flatten_any(it))
            return out
        except Exception:
            pass
    out.append(x)
    return out


def _as_tree_branches(x):
    """把 GH Tree / 嵌套列表 / 单值 统一为 list[branch:list]。"""
    if x is None:
        return []
    if hasattr(x, "BranchCount") and hasattr(x, "Branch"):
        out = []
        try:
            for i in range(int(x.BranchCount)):
                br = x.Branch(i)
                out.append(list(br) if br is not None else [])
            return out
        except Exception:
            pass
    if isinstance(x, (list, tuple)):
        if len(x) > 0 and isinstance(x[0], (list, tuple)):
            return [list(b) for b in x]
        return [list(x)]
    if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
        try:
            lst = list(x)
            if len(lst) > 0 and isinstance(lst[0], (list, tuple)):
                return [list(b) for b in lst]
            return [lst]
        except Exception:
            pass
    return [[x]]


def _safe_index(seq, idx, wrap=True):
    """安全索引：wrap=True 时循环取；否则越界返回 None。"""
    if seq is None:
        return None
    try:
        s = list(seq)
    except Exception:
        return None
    if len(s) == 0:
        return None
    try:
        i = int(idx)
    except Exception:
        i = 0
    if wrap:
        return s[i % len(s)]
    if 0 <= i < len(s):
        return s[i]
    return None


def first_or_default(v, default=None):
    """若 v 为 list/tuple，则取第一个；否则直接返回；None → default。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        return v[0] if len(v) else default
    return v


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其它标量 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


def _broadcast_param(val, n, name="param"):
    """
    GH 风格广播/截断到长度 n（参考 LingGongSolver）：
    - list/tuple:
        * len==0 -> [None]*n
        * 0<len<n -> 用“最后一个值”补齐
        * len>=n -> 截断前 n
    - scalar: [val]*n
    """
    if isinstance(val, (list, tuple)):
        seq = list(val)
        l = len(seq)
        if l == 0:
            return [None] * n
        if l >= n:
            return seq[:n]
        last = seq[-1]
        return seq + [last] * (n - l)
    else:
        return [val] * n


def make_ref_plane(mode_str, origin=None):
    """
    GH 参考平面（按你给出的轴向约定）：
    XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
    YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    if mode_str is None:
        mode_str = "WorldXZ"
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
    # Plane 构造自动得到 Z = X × Y = (0,-1,0)
    return rg.Plane(origin, x, y)


def _coerce_plane(obj, default=None):
    """尽量把输入转为 Rhino.Geometry.Plane；失败返回 default。"""
    if obj is None:
        return default
    # RhinoCommon Plane
    try:
        if isinstance(obj, rg.Plane):
            return obj
    except Exception:
        pass
    # Grasshopper GH_Plane / 包装类型通常有 Value
    try:
        v = getattr(obj, 'Value', None)
        if isinstance(v, rg.Plane):
            return v
    except Exception:
        pass
    # 其它可能持有 Plane 属性
    try:
        p = getattr(obj, 'Plane', None)
        if isinstance(p, rg.Plane):
            return p
    except Exception:
        pass
    # 尝试从可迭代中取第一个
    if isinstance(obj, (list, tuple)) and len(obj) > 0:
        return _coerce_plane(obj[0], default)
    return default


def _coerce_point3d(p, default=None):
    """GH Point / Point3d / None -> Point3d"""
    if p is None:
        return default
    if isinstance(p, rg.Point3d):
        return p
    if isinstance(p, rg.Point):
        return p.Location
    # 兼容 (x,y,z)
    try:
        if hasattr(p, "__len__") and len(p) >= 3:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
    except Exception:
        pass
    return default


def _get_from_alldict(AllDict, comp_key, port_name, default=None):
    """
    从 AllDict 读取键： f"{comp_key}__{port_name}"
    例如：TimberBlock_SkewAxis_M__length_fen
    """
    if not AllDict:
        return default
    k = "{}__{}".format(comp_key, port_name)
    if k in AllDict:
        return AllDict.get(k, default)
    return default


def _get_from_alldict_multi(AllDict, comp_key, port_names, default=None):
    """兼容不同字段命名：依次尝试多个 port_name，返回首个命中的值。"""
    if not AllDict:
        return default
    for pn in port_names:
        k = "{}__{}".format(comp_key, pn)
        if k in AllDict:
            return AllDict.get(k, default)
    return default


def _pick_param(input_val, db_val, default=None):
    """输入端优先；否则数据库；否则默认。"""
    if input_val is not None:
        return input_val
    if db_val is not None:
        return db_val
    return default


# ==============================================================
# Step3 组件：ShuaTou（耍頭刀具）——移除 sticky，作为纯函数 Builder
# ==============================================================
def _default_point(p):
    return p if (p is not None) else rg.Point3d(0, 0, 0)


def _default_plane(pl):
    if pl is not None:
        return pl
    origin = rg.Point3d(0, 0, 0)
    xaxis = rg.Vector3d(1, 0, 0)
    yaxis = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, xaxis, yaxis)


def _default_float(x, v):
    try:
        return float(x)
    except Exception:
        return v


class ShuaTouBuilder(object):
    """按你给的 ShuaTou 组件代码封装（v1.8）。"""

    @staticmethod
    def build(base_point, ref_plane,
              width_fen, height_fen,
              AH_fen, DF_fen, FE_fen, EC_fen,
              DG_fen, offset_fen):

        # -------- 默认值（保留组件原逻辑；若 DB 提供值则覆盖） --------
        base_point = _default_point(base_point)
        ref_plane = _default_plane(ref_plane)
        width_fen = _default_float(width_fen, 16)
        height_fen = _default_float(height_fen, 15)
        AH_fen = _default_float(AH_fen, 5)
        DF_fen = _default_float(DF_fen, 6)
        FE_fen = _default_float(FE_fen, 5)
        EC_fen = _default_float(EC_fen, 5)
        DG_fen = _default_float(DG_fen, 2)
        offset_fen = _default_float(offset_fen, 5)

        tol = sc.doc.ModelAbsoluteTolerance

        log = []
        dbg_pts = []
        dbg_lines = []

        log.append("=== FT_ShuaTouTool v1.8 START ===")
        log.append("RefPlane: Origin={0}, X={1}, Y={2}, Z={3}".format(
            ref_plane.Origin, ref_plane.XAxis, ref_plane.YAxis, ref_plane.ZAxis
        ))

        # 0. RefPlanes
        base_ref_plane = rg.Plane(base_point, ref_plane.XAxis, ref_plane.YAxis)
        xy_like_plane = rg.Plane(base_ref_plane)
        rot = rg.Transform.Rotation(math.radians(90.0), base_ref_plane.XAxis, base_point)
        xy_like_plane.Transform(rot)
        RefPlanes = [base_ref_plane, xy_like_plane]

        # 1. base rect
        A, B, C, D = ShuaTouBuilder._build_base_rect(base_point, ref_plane, width_fen, height_fen)
        dbg_pts.extend([A, B, C, D])

        # 2. key points
        H, F, E, G, J, K, I, L, aux_lines = ShuaTouBuilder._build_key_points(
            A, B, C, D,
            AH_fen, DF_fen, FE_fen, DG_fen,
            ref_plane, log
        )
        dbg_pts.extend([H, F, E, G, J, K, I, L])
        dbg_lines.extend(aux_lines)

        # 3. center section
        CenterSectionCrv = rg.Polyline([H, I, K, E]).ToNurbsCurve()
        center_face_poly = rg.Polyline([H, I, K, E, D, A, H]).ToNurbsCurve()
        cf = rg.Brep.CreatePlanarBreps(center_face_poly)
        CenterSectionFace = cf[0] if cf else None

        # 4. side section
        SideSectionCrv = rg.Polyline([H, L, C]).ToNurbsCurve()
        side_face_poly = rg.Polyline([H, L, C, D, A, H]).ToNurbsCurve()
        sf = rg.Brep.CreatePlanarBreps(side_face_poly)
        SideSectionFace = sf[0] if sf else None

        # 5. offset
        n_vec = ref_plane.ZAxis * offset_fen

        H_neg = H + (-n_vec)
        L_neg = L + (-n_vec)
        C_neg = C + (-n_vec)
        A_neg = A + (-n_vec)
        D_neg = D + (-n_vec)

        H_pos = H + n_vec
        L_pos = L + n_vec
        C_pos = C + n_vec
        A_pos = A + n_vec
        D_pos = D + n_vec

        OffsetSideFaces = []
        if SideSectionFace:
            T_neg = rg.Transform.Translation(-n_vec)
            T_pos = rg.Transform.Translation(n_vec)
            face_neg = SideSectionFace.DuplicateBrep()
            face_neg.Transform(T_neg)
            face_pos = SideSectionFace.DuplicateBrep()
            face_pos.Transform(T_pos)
            OffsetSideFaces = [face_neg, face_pos]

        OffsetSideCrvs = []
        if SideSectionCrv:
            T_neg_c = rg.Transform.Translation(-n_vec)
            T_pos_c = rg.Transform.Translation(n_vec)
            crv_neg = SideSectionCrv.DuplicateCurve()
            crv_neg.Transform(T_neg_c)
            crv_pos = SideSectionCrv.DuplicateCurve()
            crv_pos.Transform(T_pos_c)
            OffsetSideCrvs = [crv_neg, crv_pos]

        # 6. loft
        SideLoftFace = None
        if len(OffsetSideCrvs) == 2:
            IKELine = rg.Polyline([I, K, E]).ToNurbsCurve()
            loft = rg.Brep.CreateFromLoft(
                [OffsetSideCrvs[0], IKELine, OffsetSideCrvs[1]],
                rg.Point3d.Unset,
                rg.Point3d.Unset,
                rg.LoftType.Straight,
                False
            )
            if loft:
                SideLoftFace = loft[0]
                log.append("SideLoftFace created (Straight Loft).")
            else:
                log.append("Loft failed - SideLoftFace is None.")
        else:
            log.append("OffsetSideCrvs != 2, cannot loft SideLoftFace.")

        # 7. TriFace
        TriFace = rg.Brep.CreateFromCornerPoints(H_neg, I, H_pos, tol)
        if TriFace:
            log.append("TriFace created (H_neg, I, H_pos).")
        else:
            log.append("TriFace creation failed (points may be collinear).")

        # 8. H'AD'Loft
        HADLoftFace = None
        had_crv_neg = rg.Polyline([H_neg, A_neg, D_neg]).ToNurbsCurve()
        had_crv_pos = rg.Polyline([H_pos, A_pos, D_pos]).ToNurbsCurve()
        had_loft = rg.Brep.CreateFromLoft(
            [had_crv_neg, had_crv_pos],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Straight,
            False
        )
        if had_loft:
            HADLoftFace = had_loft[0]
            log.append("H'AD'Loft created (Straight Loft).")
        else:
            log.append("H'AD'Loft creation failed.")

        # 9. BottomFace
        BottomFace = None
        bottom_tris = []
        t1 = rg.Brep.CreateFromCornerPoints(D_neg, C_neg, E, tol)
        if t1:
            bottom_tris.append(t1)
        t2 = rg.Brep.CreateFromCornerPoints(E, C_pos, D_pos, tol)
        if t2:
            bottom_tris.append(t2)
        t3 = rg.Brep.CreateFromCornerPoints(D_neg, E, D_pos, tol)
        if t3:
            bottom_tris.append(t3)

        if bottom_tris:
            joined_bottom = rg.Brep.JoinBreps(bottom_tris, tol)
            if joined_bottom and len(joined_bottom) > 0:
                BottomFace = joined_bottom[0]
                log.append("BottomFace created from {0} triangles.".format(len(bottom_tris)))
            else:
                log.append("JoinBreps failed for BottomFace.")
        else:
            log.append("No triangles created for BottomFace.")

        # 10. join
        ToolBrep = None
        join_list = []
        if SideLoftFace:
            join_list.append(SideLoftFace)
        if TriFace:
            join_list.append(TriFace)
        if HADLoftFace:
            join_list.append(HADLoftFace)
        if BottomFace:
            join_list.append(BottomFace)
        if OffsetSideFaces:
            join_list.extend([f for f in OffsetSideFaces if f is not None])

        if join_list:
            joined = rg.Brep.JoinBreps(join_list, tol)
            if joined and len(joined) > 0:
                ToolBrep = joined[0]
                log.append("ToolBrep joined from {0} breps.".format(len(join_list)))
                if not ToolBrep.IsSolid:
                    if ToolBrep.CapPlanarHoles(tol):
                        log.append("ToolBrep CapPlanarHoles succeeded, solid={0}".format(ToolBrep.IsSolid))
                    else:
                        log.append("CapPlanarHoles did not fully close ToolBrep.")
        else:
            log.append("No breps to join for ToolBrep.")

        log.append("=== FT_ShuaTouTool v1.8 END ===")

        return (CenterSectionCrv,
                SideSectionCrv,
                CenterSectionFace,
                SideSectionFace,
                OffsetSideFaces,
                OffsetSideCrvs,
                SideLoftFace,
                ToolBrep,
                dbg_pts,
                dbg_lines,
                RefPlanes,
                log)

    @staticmethod
    def _build_base_rect(base_point, plane, width, height):
        X = plane.XAxis
        Y = plane.YAxis
        D = base_point
        C = D + X * width
        A = D + Y * height
        B = A + X * width
        return A, B, C, D

    @staticmethod
    def _build_key_points(A, B, C, D, AH, DF, FE, DG, plane, log):
        X = plane.XAxis
        Y = plane.YAxis

        H = A + X * AH
        F = D + X * DF
        E = F + X * FE
        G = D + Y * DG

        BC = rg.Line(B, C)
        GJ = rg.Line(G, G + X * 500)

        rc, t1, t2 = rg.Intersect.Intersection.LineLine(GJ, BC)
        J = GJ.PointAt(t1) if rc else C

        AF = rg.Line(A, F)
        rc2, t3, t4 = rg.Intersect.Intersection.LineLine(AF, GJ)
        K = AF.PointAt(t3) if rc2 else F

        I = ShuaTouBuilder._perpendicular_foot(H, A, F)

        HL = rg.Line(H, H + (F - A) * 200)
        rc3, t5, t6 = rg.Intersect.Intersection.LineLine(HL, GJ)
        L = HL.PointAt(t5) if rc3 else H

        aux = [AF.ToNurbsCurve(), GJ.ToNurbsCurve(), HL.ToNurbsCurve(), BC.ToNurbsCurve()]
        return H, F, E, G, J, K, I, L, aux

    @staticmethod
    def _perpendicular_foot(P, A, B):
        line = rg.Line(A, B)
        t = line.ClosestParameter(P)
        return line.PointAt(t)


# ==============================================================
# 主 Solver 类 —— YouAngInLineWJiaoShuaTou_4PU
# ==============================================================

class YouAngInLineWJiaoShuaTou_4PU_Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        # 输入缓存
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # 全局日志
        self.Log = []

        # Step 1：数据库读取相关成员
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # Step 2：木坯几何输出成员（与组件命名保持一致）
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
        self.Log_TimberBlock = []

        # Step2 兼容别名（按你后续 Step4 提示词要求）
        self.TimberBlock_SkewAxis_M__EdgeMidPoints = None
        self.TimberBlock_SkewAxis_M__Corner0Planes = None

        # Step 3：ShuaTou + PlaneFromLists::1 + GeoAligner::1
        self.ShuaTou__CenterSectionCrv = None
        self.ShuaTou__SideSectionCrv = None
        self.ShuaTou__CenterSectionFace = None
        self.ShuaTou__SideSectionFace = None
        self.ShuaTou__OffsetSideFaces = []
        self.ShuaTou__OffsetSideCrvs = []
        self.ShuaTou__SideLoftFace = None
        self.ShuaTou__ToolBrep = None
        self.ShuaTou__DebugPoints = []
        self.ShuaTou__DebugLines = []
        self.ShuaTou__RefPlanes = []
        self.ShuaTou__Log = []

        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        self.GeoAligner_1__SourceOut = None
        self.GeoAligner_1__TargetOut = None
        self.GeoAligner_1__TransformOut = None
        self.GeoAligner_1__MovedGeo = None

        # Step 4：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::2
        self.QiAOTool__CutTimbers = None
        self.QiAOTool__FailTimbers = None
        self.QiAOTool__Log = []
        self.QiAOTool__EdgeMidPoints = None
        self.QiAOTool__Corner0Planes = None

        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        self.GeoAligner_2__SourceOut = None
        self.GeoAligner_2__TargetOut = None
        self.GeoAligner_2__TransformOut = None
        self.GeoAligner_2__MovedGeo = None

        # Step 2（补充别名）：供后续 Tree Item 使用
        self.TimberBlock_SkewAxis_M__Skew_Planes = None

        # Step 2（补充别名）：供 Step11 使用
        self.TimberBlock_SkewAxis_M__Obj = None
        self.TimberBlock_SkewAxis_M__Skew_Point_C = None

        # Step11：YouAng 子总成 + AlignToolToTimber::9
        self.YouAng__CutTimbers = None
        self.YouAng__FailTimbers = None
        self.YouAng__Log = None
        self.YouAng__Ang_PtsValues = None
        self.YouAng__Ang_PlanesAValues = None
        self.YouAng__Ang_PlanesBValues = None
        self.YouAng__Ang_OBLoftBrep = None

        self.AlignToolToTimber_9__TargetOriginPoint = None
        self.AlignToolToTimber_9__TargetBasePlane = None
        self.AlignToolToTimber_9__TargetPlane = None
        self.AlignToolToTimber_9__SourcePlane_Selected = None

        self.AlignToolToTimber_9__SourceOut = None
        self.AlignToolToTimber_9__TargetOut = None
        self.AlignToolToTimber_9__TransformOut = None
        self.AlignToolToTimber_9__MovedGeo = None

        # Step 5：blockcutter::1 + ListItem + TreeItem + GeoAligner::3
        self.blockcutter_1__TimberBrep = None
        self.blockcutter_1__FacePlaneList = None
        self.blockcutter_1__EdgeMidPoints = None
        self.blockcutter_1__Corner0Planes = None
        self.blockcutter_1__Log = []

        self.ListItem_GA3__SourcePlane = None
        self.TreeItem_GA3__TargetPlane = None

        self.GeoAligner_3__SourceOut = None
        self.GeoAligner_3__TargetOut = None
        self.GeoAligner_3__TransformOut = None
        self.GeoAligner_3__MovedGeo = None

        # Step 6：blockcutter::2 + ListItem + TreeItem + GeoAligner::4
        self.blockcutter_2__TimberBrep = None
        self.blockcutter_2__FacePlaneList = None
        self.blockcutter_2__EdgeMidPoints = None
        self.blockcutter_2__Corner0Planes = None
        self.blockcutter_2__Log = []

        # Step?：blockcutter::3（用于输出绑定的安全初始化）
        self.blockcutter_3__TimberBrep = None
        self.blockcutter_3__FacePlaneList = []
        self.blockcutter_3__EdgeMidPoints = []
        self.blockcutter_3__Corner0Planes = []
        self.blockcutter_3__Log = []

        self.ListItem_GA4__SourcePlane = None
        self.TreeItem_GA4__TargetPlane = None

        self.GeoAligner_4__SourceOut = None
        self.GeoAligner_4__TargetOut = None
        self.GeoAligner_4__TransformOut = None
        self.GeoAligner_4__MovedGeoTree = None  # 保留 Tree/分支结构（developer 观察用）
        self.GeoAligner_4__MovedGeo = None  # 常用：完全展平，便于后续作为 Tools
        # ---------------------------------------------------------
        # Step7 (GeoAligner::5) developer-friendly init (avoid AttributeError)
        # ---------------------------------------------------------
        self.GeoAligner_5__SourcePlane_ListItem = None
        self.GeoAligner_5__TargetPlane_TreeItem = None
        self.GeoAligner_5__MovedGeoTree = None
        self.GeoAligner_5__MovedGeo = None
        self.GeoAligner_5__SourceOut = None
        self.GeoAligner_5__TargetOut = None
        self.GeoAligner_5__TransformOut = None
        self.Step7__Log = []

        # Step 8：AxisLinesIntersectionsSolver + SectionExtrude_SymmetricTrapezoid::1 + AlignToolToTimber::6
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

        self.SectionExtrude_SymmetricTrapezoid_1__A = None
        self.SectionExtrude_SymmetricTrapezoid_1__B = None
        self.SectionExtrude_SymmetricTrapezoid_1__C = None
        self.SectionExtrude_SymmetricTrapezoid_1__D = None
        self.SectionExtrude_SymmetricTrapezoid_1__O = None
        self.SectionExtrude_SymmetricTrapezoid_1__E = None
        self.SectionExtrude_SymmetricTrapezoid_1__Oprime = None

        self.SectionExtrude_SymmetricTrapezoid_1__AB = None
        self.SectionExtrude_SymmetricTrapezoid_1__CD = None
        self.SectionExtrude_SymmetricTrapezoid_1__AC = None
        self.SectionExtrude_SymmetricTrapezoid_1__BD = None
        self.SectionExtrude_SymmetricTrapezoid_1__Axis_AC = None

        self.SectionExtrude_SymmetricTrapezoid_1__section_polyline = None
        self.SectionExtrude_SymmetricTrapezoid_1__section_curve = None
        self.SectionExtrude_SymmetricTrapezoid_1__section_brep = None

        self.SectionExtrude_SymmetricTrapezoid_1__solid_brep = None
        self.SectionExtrude_SymmetricTrapezoid_1__solid_brep_mirror = None
        self.SectionExtrude_SymmetricTrapezoid_1__solid_list = None

        self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime = None
        self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime_X = None
        self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime_Y = None
        self.SectionExtrude_SymmetricTrapezoid_1__MirrorPlane_ACZ = None
        self.SectionExtrude_SymmetricTrapezoid_1__log = []

        self.AlignToolToTimber_6__SourceOut = None
        self.AlignToolToTimber_6__TargetOut = None
        self.AlignToolToTimber_6__TransformOut = None
        self.AlignToolToTimber_6__MovedGeo = None

        # Step 9：SectionExtrude_SymmetricTrapezoid::2 + AlignToolToTimber::7
        self.SectionExtrude_SymmetricTrapezoid_2__A = None
        self.SectionExtrude_SymmetricTrapezoid_2__B = None
        self.SectionExtrude_SymmetricTrapezoid_2__C = None
        self.SectionExtrude_SymmetricTrapezoid_2__D = None
        self.SectionExtrude_SymmetricTrapezoid_2__O = None
        self.SectionExtrude_SymmetricTrapezoid_2__E = None
        self.SectionExtrude_SymmetricTrapezoid_2__Oprime = None

        self.SectionExtrude_SymmetricTrapezoid_2__AB = None
        self.SectionExtrude_SymmetricTrapezoid_2__CD = None
        self.SectionExtrude_SymmetricTrapezoid_2__AC = None
        self.SectionExtrude_SymmetricTrapezoid_2__BD = None
        self.SectionExtrude_SymmetricTrapezoid_2__Axis_AC = None

        self.SectionExtrude_SymmetricTrapezoid_2__section_polyline = None
        self.SectionExtrude_SymmetricTrapezoid_2__section_curve = None
        self.SectionExtrude_SymmetricTrapezoid_2__section_brep = None

        self.SectionExtrude_SymmetricTrapezoid_2__solid_brep = None
        self.SectionExtrude_SymmetricTrapezoid_2__solid_brep_mirror = None
        self.SectionExtrude_SymmetricTrapezoid_2__solid_list = None

        self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime = None
        self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime_X = None
        self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime_Y = None
        self.SectionExtrude_SymmetricTrapezoid_2__MirrorPlane_ACZ = None
        self.SectionExtrude_SymmetricTrapezoid_2__log = []

        self.AlignToolToTimber_7__SourceOut = None
        self.AlignToolToTimber_7__TargetOut = None
        self.AlignToolToTimber_7__TransformOut = None
        self.AlignToolToTimber_7__MovedGeo = None

        # Step 10：SectionExtrude_SymmetricTrapezoid::3 + AlignToolToTimber::8
        self.SectionExtrude_SymmetricTrapezoid_3__A = None
        self.SectionExtrude_SymmetricTrapezoid_3__B = None
        self.SectionExtrude_SymmetricTrapezoid_3__C = None
        self.SectionExtrude_SymmetricTrapezoid_3__D = None
        self.SectionExtrude_SymmetricTrapezoid_3__O = None
        self.SectionExtrude_SymmetricTrapezoid_3__E = None
        self.SectionExtrude_SymmetricTrapezoid_3__Oprime = None

        self.SectionExtrude_SymmetricTrapezoid_3__AB = None
        self.SectionExtrude_SymmetricTrapezoid_3__CD = None
        self.SectionExtrude_SymmetricTrapezoid_3__AC = None
        self.SectionExtrude_SymmetricTrapezoid_3__BD = None
        self.SectionExtrude_SymmetricTrapezoid_3__Axis_AC = None

        self.SectionExtrude_SymmetricTrapezoid_3__section_polyline = None
        self.SectionExtrude_SymmetricTrapezoid_3__section_curve = None
        self.SectionExtrude_SymmetricTrapezoid_3__section_brep = None

        self.SectionExtrude_SymmetricTrapezoid_3__solid_brep = None
        self.SectionExtrude_SymmetricTrapezoid_3__solid_brep_mirror = None
        self.SectionExtrude_SymmetricTrapezoid_3__solid_list = None

        self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime = None
        self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime_X = None
        self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime_Y = None
        self.SectionExtrude_SymmetricTrapezoid_3__MirrorPlane_ACZ = None
        self.SectionExtrude_SymmetricTrapezoid_3__log = []

        self.AlignToolToTimber_8__SourceOut = None
        self.AlignToolToTimber_8__TargetOut = None
        self.AlignToolToTimber_8__TransformOut = None
        self.AlignToolToTimber_8__MovedGeo = None

        # Step 12：CutTimbersByTools::1 + Transform + SplitSectionAnalyzer
        self.Step12__ToolsFlat = []
        self.Step12__CutterGeo = None

        self.CutTimbersByTools_1__CutTimbers = None
        self.CutTimbersByTools_1__FailTimbers = None
        self.CutTimbersByTools_1__Log = []

        # GH Transform（对齐后的 cutter）
        self.Transform_1__Geometry = None

        # ------------------------------------------------------
        # Step 13：blockcutter::4 + AlignToolToTimber::10
        # ------------------------------------------------------
        self.blockcutter_4__TimberBrep = None
        self.blockcutter_4__FaceList = []
        self.blockcutter_4__PointList = []
        self.blockcutter_4__EdgeList = []
        self.blockcutter_4__CenterPoint = None
        self.blockcutter_4__CenterAxisLines = []
        self.blockcutter_4__EdgeMidPoints = []
        self.blockcutter_4__FacePlaneList = []
        self.blockcutter_4__Corner0Planes = []
        self.blockcutter_4__LocalAxesPlane = None
        self.blockcutter_4__AxisX = None
        self.blockcutter_4__AxisY = None
        self.blockcutter_4__AxisZ = None
        self.blockcutter_4__FaceDirTags = []
        self.blockcutter_4__EdgeDirTags = []
        self.blockcutter_4__Corner0EdgeDirs = []
        self.blockcutter_4__Log = []

        # Tree_Cleaner（对 SourcePlaneTree 做规范化后的结果）
        self.Step13__ATTT10_SourcePlaneTreeCleaned = None

        self.AlignToolToTimber_10__SourcePlane_Selected = None
        self.AlignToolToTimber_10__SourceOut = None
        self.AlignToolToTimber_10__TargetOut = None
        self.AlignToolToTimber_10__TransformOut = None
        self.AlignToolToTimber_10__MovedGeo = None

        # ------------------------------------------------------
        # Step 14：CutTimbersByTools::2
        # ------------------------------------------------------
        self.CutTimbersByTools_2__CutTimbers = None
        self.CutTimbersByTools_2__FailTimbers = None
        self.CutTimbersByTools_2__Log = []

        # ------------------------------------------------------
        # Step 15：blockcutter::5 + AlignToolToTimber::11
        # ------------------------------------------------------
        self.blockcutter_5__TimberBrep = None
        self.blockcutter_5__FaceList = []
        self.blockcutter_5__PointList = []
        self.blockcutter_5__EdgeList = []
        self.blockcutter_5__CenterPoint = None
        self.blockcutter_5__CenterAxisLines = []
        self.blockcutter_5__EdgeMidPoints = []
        self.blockcutter_5__FacePlaneList = []
        self.blockcutter_5__Corner0Planes = []
        self.blockcutter_5__LocalAxesPlane = None
        self.blockcutter_5__AxisX = None
        self.blockcutter_5__AxisY = None
        self.blockcutter_5__AxisZ = None
        self.blockcutter_5__FaceDirTags = []
        self.blockcutter_5__EdgeDirTags = []
        self.blockcutter_5__Corner0EdgeDirs = []
        self.blockcutter_5__Log = []

        # Tree_Cleaner（对 SourcePlaneTree 做规范化后的结果）
        self.Step15__ATTT11_SourcePlaneTreeCleaned = None

        self.AlignToolToTimber_11__SourcePlane_Selected = None
        self.AlignToolToTimber_11__SourceOut = None
        self.AlignToolToTimber_11__TargetOut = None
        self.AlignToolToTimber_11__TransformOut = None
        self.AlignToolToTimber_11__MovedGeo = None

        # MoveX 计算链中间量（便于调试）
        self.AlignToolToTimber_11__MoveX_divistion = None
        self.AlignToolToTimber_11__MoveX_subtraction = None
        self.AlignToolToTimber_11__MoveX_tmp_div = None
        self.AlignToolToTimber_11__MoveX_final = None
        # SplitSectionAnalyzer outputs
        self.SplitSectionAnalyzer__SortedVolumes = None
        self.SplitSectionAnalyzer__MaxClosedBrep = None
        self.SplitSectionAnalyzer__SectionFaces = None
        self.SplitSectionAnalyzer__SectionBrep = None
        self.SplitSectionAnalyzer__StableEdgeCurves = None
        self.SplitSectionAnalyzer__StableLineSegments = None
        self.SplitSectionAnalyzer__MaxXMidPoint = None
        self.SplitSectionAnalyzer__CutterAnglesHV = None
        self.SplitSectionAnalyzer__PlaneCutterCurves = None
        self.SplitSectionAnalyzer__PlaneCutterMidPoint = None
        self.SplitSectionAnalyzer__Log = []

        # 最终主输出（后续步骤会填充）
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        DBJsonReader:
            Table=DG_Dou
            KeyField=type_code
            KeyValue=YouAngInLineWJiaoShuaTou_4PU
            Field=params_json
            ExportAll=True
        """
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="YouAngInLineWJiaoShuaTou_4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            Value, All, Log = reader.run()

            self.Value = Value
            self.All = All
            self.DBLog = to_py_list(Log)

            # All -> dict
            d = {}
            if All:
                try:
                    for k, v in All:
                        d[str(k)] = v
                except Exception:
                    # 兼容 All 是 dict 或其它结构
                    try:
                        if isinstance(All, dict):
                            d = dict(All)
                    except Exception:
                        pass
            self.AllDict = d

            self.Log.append("[DB] 读取完成: All={} 项".format(len(d) if d else 0))
            for l in self.DBLog:
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Value = None
            self.All = None
            self.AllDict = {}
            self.DBLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step1 DBJsonReader 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建（TimberBlock_SkewAxis_M）
    # ------------------------------------------------------
    def step2_timber(self):
        """
        TimberBlock_SkewAxis_M 组件输入端：
            length_fen = TimberBlock_SkewAxis_M__length_fen
            width_fen  = TimberBlock_SkewAxis_M__width_fen
            height_fen = TimberBlock_SkewAxis_M__height_fen
            base_point = GH 输入 base_point（无则原点）
            reference_plane = 默认 GH XZ Plane（过 base_point）
            Skew_len   = TimberBlock_SkewAxis_M__Skew_len（如 DB 中存在）
        """
        try:
            # --- 参数：输入端优先（目前只给了 base_point；其余均从 DB/默认） ---
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            length_fen = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "TimberBlock_SkewAxis_M", "length_fen", None),
                32.0
            )
            width_fen = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "TimberBlock_SkewAxis_M", "width_fen", None),
                32.0
            )
            height_fen = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "TimberBlock_SkewAxis_M", "height_fen", None),
                20.0
            )
            Skew_len = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "TimberBlock_SkewAxis_M", "Skew_len", None),
                20.0
            )

            # reference_plane：默认 GH XZ（过 bp）
            ref_plane = make_ref_plane("WorldXZ", bp)

            # 兼容：Skew_len 可能是 list / tree；但 BuildTimberBlockUniform_SkewAxis_M 内部已能处理
            obj = BuildTimberBlockUniform_SkewAxis_M(
                length_fen,
                width_fen,
                height_fen,
                bp,
                ref_plane,
                Skew_len
            )

            # 保存 TimberBlock 对象本体（供后续 Step11 取 Skew_Point_C 等隐藏字段）
            self.TimberBlock_SkewAxis_M__Obj = obj
            # 尝试提取 Skew_Point_C（若存在）
            try:
                self.TimberBlock_SkewAxis_M__Skew_Point_C = getattr(obj, "Skew_Point_C", None) or getattr(obj,
                                                                                                          "Skew_Point_CValues",
                                                                                                          None) or getattr(
                    obj, "SkewPointC", None)
            except Exception:
                self.TimberBlock_SkewAxis_M__Skew_Point_C = None

            # TimberBrep：确保输出 1 个 Closed Brep（参考你给的组件代码逻辑）
            _tb = getattr(obj, "TimberBrep", None)
            try:
                if _tb is not None and (hasattr(_tb, "BranchCount") and hasattr(_tb, "Branch")):
                    if int(_tb.BranchCount) > 0:
                        br0 = _tb.Branch(0)
                        if br0 is not None and int(br0.Count) > 0:
                            _tb = br0[0]
                elif isinstance(_tb, (list, tuple)):
                    for _it in _tb:
                        if _it is not None:
                            _tb = _it
                            break
            except Exception:
                pass

            self.TimberBrep = _tb
            self.FaceList = getattr(obj, "FaceList", []) or []
            self.PointList = getattr(obj, "PointList", []) or []
            self.EdgeList = getattr(obj, "EdgeList", []) or []
            self.CenterPoint = getattr(obj, "CenterPoint", None)
            self.CenterAxisLines = getattr(obj, "CenterAxisLines", []) or []
            self.EdgeMidPoints = getattr(obj, "EdgeMidPoints", []) or []
            self.FacePlaneList = getattr(obj, "FacePlaneList", []) or []
            self.Corner0Planes = getattr(obj, "Corner0Planes", []) or []
            # Step2 别名（供后续 Step4 按提示词取值）
            self.TimberBlock_SkewAxis_M__EdgeMidPoints = self.EdgeMidPoints
            self.TimberBlock_SkewAxis_M__Corner0Planes = self.Corner0Planes
            self.TimberBlock_SkewAxis_M__Skew_Planes = getattr(obj, "Skew_Planes", None) or getattr(obj, "SkewPlanes",
                                                                                                    None) or getattr(
                obj, "SkewPlanesValues", None)
            self.LocalAxesPlane = getattr(obj, "LocalAxesPlane", None)
            self.AxisX = getattr(obj, "AxisX", None)
            self.AxisY = getattr(obj, "AxisY", None)
            self.AxisZ = getattr(obj, "AxisZ", None)
            self.FaceDirTags = getattr(obj, "FaceDirTags", []) or []
            self.EdgeDirTags = getattr(obj, "EdgeDirTags", []) or []
            self.Corner0EdgeDirs = getattr(obj, "Corner0EdgeDirs", []) or []
            self.Log_TimberBlock = to_py_list(getattr(obj, "Log", []) or [])

            self.Log.append("[TIMBER] TimberBlock_SkewAxis_M 完成: TimberBrep={}".format(
                "OK" if self.TimberBrep is not None else "None"
            ))
            for l in self.Log_TimberBlock:
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            self.TimberBrep = None
            self.Log_TimberBlock = ["主逻辑错误: {}".format(e)]
            self.Log.append("[ERROR] Step2 TimberBlock 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3：ShuaTou + PlaneFromLists::1 + GeoAligner::1
    # ------------------------------------------------------
    def step3_shuatou_plane_geoaligner(self):
        """仅实现 Step3（不重复读库、不修改已完成步骤）。"""
        try:
            # 1) ShuaTou
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))
            ref_plane = make_ref_plane("WorldXZ", bp)

            width_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["WidthFen", "ShuaTou_WidthFen"], None)
            height_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["HeightFen", "ShuaTou_HeightFen"], None)
            AH_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["AH_Fen", "ShuaTou_AH_Fen"], None)
            DF_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["DF_Fen", "ShuaTou_DF_Fen"], None)
            FE_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["FE_Fen", "ShuaTou_FE_Fen"], None)
            EC_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["EC_Fen", "ShuaTou_EC_Fen"], None)
            DG_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["DG_Fen", "ShuaTou_DG_Fen"], None)
            offset_fen = _get_from_alldict_multi(self.AllDict, "ShuaTou", ["OffsetFen", "ShuaTou_OffsetFen"], None)

            (CenterSectionCrv,
             SideSectionCrv,
             CenterSectionFace,
             SideSectionFace,
             OffsetSideFaces,
             OffsetSideCrvs,
             SideLoftFace,
             ToolBrep,
             DebugPoints,
             DebugLines,
             RefPlanes,
             LogS) = ShuaTouBuilder.build(
                bp, ref_plane,
                width_fen, height_fen,
                AH_fen, DF_fen, FE_fen, EC_fen,
                DG_fen, offset_fen
            )

            self.ShuaTou__CenterSectionCrv = CenterSectionCrv
            self.ShuaTou__SideSectionCrv = SideSectionCrv
            self.ShuaTou__CenterSectionFace = CenterSectionFace
            self.ShuaTou__SideSectionFace = SideSectionFace
            self.ShuaTou__OffsetSideFaces = OffsetSideFaces
            self.ShuaTou__OffsetSideCrvs = OffsetSideCrvs
            self.ShuaTou__SideLoftFace = SideLoftFace
            self.ShuaTou__ToolBrep = ToolBrep
            self.ShuaTou__DebugPoints = DebugPoints
            self.ShuaTou__DebugLines = DebugLines
            self.ShuaTou__RefPlanes = RefPlanes
            self.ShuaTou__Log = to_py_list(LogS)

            self.Log.append("[STEP3] ShuaTou 完成: ToolBrep={}".format("OK" if ToolBrep else "None"))

            # 2) PlaneFromLists::1
            origin_branches = _as_tree_branches(self.EdgeMidPoints)
            baseplanes_branches = _as_tree_branches(self.Corner0Planes)
            if len(baseplanes_branches) == 0:
                baseplanes_flat = []
            elif len(baseplanes_branches) == 1:
                baseplanes_flat = list(baseplanes_branches[0])
            else:
                baseplanes_flat = flatten_any(baseplanes_branches)

            idx_origin = _get_from_alldict(self.AllDict, "PlaneFromLists_1", "IndexOrigin", 0)
            idx_plane = _get_from_alldict(self.AllDict, "PlaneFromLists_1", "IndexPlane", 0)
            wrap = bool(_get_from_alldict(self.AllDict, "PlaneFromLists_1", "Wrap", False))

            bcount = len(origin_branches)
            idx_origin_seq = _broadcast_param(idx_origin, bcount, "IndexOrigin")
            idx_plane_seq = _broadcast_param(idx_plane, bcount, "IndexPlane")

            builder = FTPlaneFromLists(wrap=wrap)

            picked_baseplanes = []
            picked_origins = []
            result_planes = []
            pfl_log = []

            for bi in range(bcount):
                br = origin_branches[bi]
                op = _safe_index(br, idx_origin_seq[bi], wrap=wrap)
                bp0 = _safe_index(baseplanes_flat, idx_plane_seq[bi], wrap=wrap)

                if op is None or bp0 is None:
                    picked_baseplanes.append(bp0)
                    picked_origins.append(op)
                    result_planes.append(None)
                    pfl_log.append("Branch {}: Origin/BasePlane None".format(bi))
                    continue

                try:
                    _bp, _op, _pl, _lg = builder.build_plane([op], baseplanes_flat, 0, int(idx_plane_seq[bi]))
                    _bp = first_or_default(_bp, bp0)
                    _op = first_or_default(_op, op)
                    _pl = first_or_default(_pl, None)
                    if _pl is None:
                        _pl = rg.Plane(_bp)
                        _pl.Origin = _op
                    picked_baseplanes.append(_bp)
                    picked_origins.append(_op)
                    result_planes.append(_pl)
                    for _l in to_py_list(_lg):
                        pfl_log.append("B{}: {}".format(bi, _l))
                except Exception as ee:
                    _pl = rg.Plane(bp0)
                    _pl.Origin = op
                    picked_baseplanes.append(bp0)
                    picked_origins.append(op)
                    result_planes.append(_pl)
                    pfl_log.append("B{}: fallback plane ({})".format(bi, ee))

            self.PlaneFromLists_1__BasePlane = picked_baseplanes
            self.PlaneFromLists_1__OriginPoint = picked_origins
            self.PlaneFromLists_1__ResultPlane = [[pl] for pl in result_planes]
            self.PlaneFromLists_1__Log = pfl_log

            self.Log.append("[STEP3] PlaneFromLists::1 完成: branches={}".format(bcount))

            # 3) GeoAligner::1
            geo = self.ShuaTou__ToolBrep
            target_tree = _as_tree_branches(self.PlaneFromLists_1__ResultPlane)
            if len(target_tree) == 0:
                target_tree = [[None]]
            branch_n = len(target_tree)

            src_idx = _get_from_alldict(self.AllDict, "GeoAligner_1", "SourcePlane", 0)
            src_idx_seq = _broadcast_param(src_idx, branch_n, "SourcePlane")

            ref_planes = to_py_list(self.ShuaTou__RefPlanes)

            rotate_deg = _get_from_alldict(self.AllDict, "GeoAligner_1", "RotateDeg", 0.0)
            flip_x = _get_from_alldict(self.AllDict, "GeoAligner_1", "FlipX", False)
            flip_y = _get_from_alldict(self.AllDict, "GeoAligner_1", "FlipY", False)
            flip_z = _get_from_alldict(self.AllDict, "GeoAligner_1", "FlipZ", False)
            move_x = _get_from_alldict(self.AllDict, "GeoAligner_1", "MoveX", 0.0)
            move_y = _get_from_alldict(self.AllDict, "GeoAligner_1", "MoveY", 0.0)
            move_z = _get_from_alldict(self.AllDict, "GeoAligner_1", "MoveZ", 0.0)

            rotate_seq = _broadcast_param(rotate_deg, branch_n, "RotateDeg")
            flipx_seq = _broadcast_param(flip_x, branch_n, "FlipX")
            flipy_seq = _broadcast_param(flip_y, branch_n, "FlipY")
            flipz_seq = _broadcast_param(flip_z, branch_n, "FlipZ")
            movex_seq = _broadcast_param(move_x, branch_n, "MoveX")
            movey_seq = _broadcast_param(move_y, branch_n, "MoveY")
            movez_seq = _broadcast_param(move_z, branch_n, "MoveZ")

            moved_tree = []
            src_outs = []
            tgt_outs = []
            xforms = []

            for bi in range(branch_n):
                tgt_plane = first_or_default(target_tree[bi], None)
                src_plane = _safe_index(ref_planes, src_idx_seq[bi], wrap=True)

                if geo is None or src_plane is None or tgt_plane is None:
                    moved_tree.append([None])
                    src_outs.append(src_plane)
                    tgt_outs.append(tgt_plane)
                    xforms.append(None)
                    continue

                s_out, t_out, xform, moved = GeoAligner_xfm.align(
                    geo,
                    src_plane,
                    tgt_plane,
                    rotate_deg=rotate_seq[bi],
                    flip_x=bool(flipx_seq[bi]),
                    flip_y=bool(flipy_seq[bi]),
                    flip_z=bool(flipz_seq[bi]),
                    move_x=movex_seq[bi],
                    move_y=movey_seq[bi],
                    move_z=movez_seq[bi],
                )
                moved_tree.append([moved])
                src_outs.append(s_out)
                tgt_outs.append(t_out)
                xforms.append(xform)

            try:
                import Grasshopper.Kernel.Types as ght
                xforms_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xforms]
            except Exception:
                xforms_wrapped = xforms

            self.GeoAligner_1__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_1__SourceOut = src_outs
            self.GeoAligner_1__TargetOut = tgt_outs
            self.GeoAligner_1__TransformOut = xforms_wrapped

            self.Log.append("[STEP3] GeoAligner::1 完成: branches={}".format(branch_n))

        except Exception as e:
            self.Log.append("[ERROR] Step3 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::2
    # ------------------------------------------------------
    def step4_qiao_tool_and_align(self):
        """仅实现 Step4（不重复读库、不修改已完成步骤）。"""
        try:
            # -------------------------
            # 1) QiAOTool（移除 sticky：每次直接 new solver）
            # -------------------------
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            def _to_float(x, default):
                try:
                    if x is None:
                        return float(default)
                    # list/tuple 取首值
                    if isinstance(x, (list, tuple)) and len(x):
                        return float(x[0])
                    return float(x)
                except Exception:
                    return float(default)

            # 参数：输入端（无）> AllDict > 默认
            length_fen = _get_from_alldict(self.AllDict, "QiAOTool", "length_fen", None)
            width_fen = _get_from_alldict(self.AllDict, "QiAOTool", "width_fen", None)
            height_fen = _get_from_alldict(self.AllDict, "QiAOTool", "height_fen", None)

            timber_ref_plane_mode = _get_from_alldict(self.AllDict, "QiAOTool", "timber_ref_plane_mode", None)

            qi_height = _get_from_alldict(self.AllDict, "QiAOTool", "qi_height", None)
            sha_width = _get_from_alldict(self.AllDict, "QiAOTool", "sha_width", None)
            qi_offset_fen = _get_from_alldict(self.AllDict, "QiAOTool", "qi_offset_fen", None)
            extrude_length = _get_from_alldict(self.AllDict, "QiAOTool", "extrude_length", None)
            extrude_positive = _get_from_alldict(self.AllDict, "QiAOTool", "extrude_positive", None)
            qi_ref_plane_mode = _get_from_alldict(self.AllDict, "QiAOTool", "qi_ref_plane_mode", None)

            rf = InputHelper.to_bool(self.Refresh, default=False)

            params = {
                "length_fen": _to_float(length_fen, 41.0),
                "width_fen": _to_float(width_fen, 16.0),
                "height_fen": _to_float(height_fen, 10.0),
                "base_point": bp,
                "timber_ref_plane": GHPlaneFactory.make(
                    timber_ref_plane_mode if timber_ref_plane_mode is not None else "XZ",
                    origin=bp
                ),
                "qi_height": _to_float(qi_height, 4.0),
                "sha_width": _to_float(sha_width, 2.0),
                "qi_offset_fen": _to_float(qi_offset_fen, 0.5),
                "extrude_length": _to_float(extrude_length, 28.0),
                "extrude_positive": InputHelper.to_bool(
                    extrude_positive if extrude_positive is not None else False,
                    default=False
                ),
                "qi_ref_plane": GHPlaneFactory.make(
                    qi_ref_plane_mode if qi_ref_plane_mode is not None else "XZ",
                    origin=bp
                ),
            }

            # 移除 sticky：每次直接新建 solver
            qsolver = QiAoToolSolver(ghenv=self.ghenv)
            qsolver.run(params)

            self.QiAOTool__CutTimbers = getattr(qsolver, "CutTimbers", None)
            self.QiAOTool__FailTimbers = getattr(qsolver, "FailTimbers", None)
            self.QiAOTool__Log = to_py_list(getattr(qsolver, "Log", []) or [])
            self.QiAOTool__EdgeMidPoints = getattr(qsolver, "EdgeMidPoints", None)
            self.QiAOTool__Corner0Planes = getattr(qsolver, "Corner0Planes", None)

            self.Log.append("[STEP4] QiAOTool 完成: CutTimbers={}".format(
                "OK" if self.QiAOTool__CutTimbers is not None else "None"
            ))

            # -------------------------
            # 2) PlaneFromLists::3 / ::2（按组件方式：FTPlaneFromLists.build_plane）
            # -------------------------
            from yingzao.ancientArchi import FTPlaneFromLists

            # ---- PlaneFromLists::3 ----
            idx_origin_3 = _get_from_alldict(self.AllDict, "PlaneFromLists_3", "IndexOrigin", 0)
            idx_plane_3 = _get_from_alldict(self.AllDict, "PlaneFromLists_3", "IndexPlane", 0)
            wrap_3 = bool(_get_from_alldict(self.AllDict, "PlaneFromLists_3", "Wrap", True))

            builder3 = FTPlaneFromLists(wrap=wrap_3)
            bp3, op3, pl3, lg3 = builder3.build_plane(
                self.QiAOTool__EdgeMidPoints,
                self.QiAOTool__Corner0Planes,
                idx_origin_3,
                idx_plane_3
            )

            self.PlaneFromLists_3__BasePlane = bp3
            self.PlaneFromLists_3__OriginPoint = op3
            self.PlaneFromLists_3__ResultPlane = pl3
            self.PlaneFromLists_3__Log = lg3

            self.Log.append("[STEP4] PlaneFromLists::3 完成: branches={}".format(len(_as_tree_branches(pl3))))

            # ---- PlaneFromLists::2 ----
            idx_origin_2 = _get_from_alldict(self.AllDict, "PlaneFromLists_2", "IndexOrigin", 0)
            idx_plane_2 = _get_from_alldict(self.AllDict, "PlaneFromLists_2", "IndexPlane", 0)
            wrap_2 = bool(_get_from_alldict(self.AllDict, "PlaneFromLists_2", "Wrap", True))

            op2_src = self.TimberBlock_SkewAxis_M__EdgeMidPoints if getattr(self,
                                                                            "TimberBlock_SkewAxis_M__EdgeMidPoints",
                                                                            None) is not None else getattr(self,
                                                                                                           "EdgeMidPoints",
                                                                                                           None)
            bp2_src = self.TimberBlock_SkewAxis_M__Corner0Planes if getattr(self,
                                                                            "TimberBlock_SkewAxis_M__Corner0Planes",
                                                                            None) is not None else getattr(self,
                                                                                                           "Corner0Planes",
                                                                                                           None)

            builder2 = FTPlaneFromLists(wrap=wrap_2)
            bp2, op2, pl2, lg2 = builder2.build_plane(
                op2_src,
                bp2_src,
                idx_origin_2,
                idx_plane_2
            )

            self.PlaneFromLists_2__BasePlane = bp2
            self.PlaneFromLists_2__OriginPoint = op2
            self.PlaneFromLists_2__ResultPlane = pl2
            self.PlaneFromLists_2__Log = lg2

            self.Log.append("[STEP4] PlaneFromLists::2 完成: branches={}".format(len(_as_tree_branches(pl2))))
            # -------------------------
            # 4) GeoAligner::2（严格按组件原代码：直接调用 GeoAligner_xfm.align）
            # -------------------------
            import Grasshopper.Kernel.Types as ght

            Geo = self.QiAOTool__CutTimbers
            SourcePlane = self.PlaneFromLists_3__ResultPlane
            TargetPlane = self.PlaneFromLists_2__ResultPlane

            RotateDeg = _get_from_alldict(self.AllDict, "GeoAligner_2", "RotateDeg", 0.0)
            FlipX = _get_from_alldict(self.AllDict, "GeoAligner_2", "FlipX", False)
            FlipY = _get_from_alldict(self.AllDict, "GeoAligner_2", "FlipY", False)
            FlipZ = _get_from_alldict(self.AllDict, "GeoAligner_2", "FlipZ", False)
            MoveX = _get_from_alldict(self.AllDict, "GeoAligner_2", "MoveX", 0.0)
            MoveY = _get_from_alldict(self.AllDict, "GeoAligner_2", "MoveY", 0.0)
            MoveZ = _get_from_alldict(self.AllDict, "GeoAligner_2", "MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.GeoAligner_2__SourceOut = SourceOut
            self.GeoAligner_2__TargetOut = TargetOut
            self.GeoAligner_2__TransformOut = TransformOut
            self.GeoAligner_2__MovedGeo = MovedGeo

            self.Log.append("[STEP4] GeoAligner::2 完成")

        except Exception as e:
            self.Log.append("[ERROR] Step4 出错: {}".format(e))

        return self

        # ------------------------------------------------------

    # Step 5：blockcutter::1 + ListItem + TreeItem + GeoAligner::3
    # ------------------------------------------------------
    def step5_blockcutter1_and_geoaligner3(self):
        """仅实现 Step5（不重复读库、不修改已完成步骤）。"""
        try:
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            # -------------------------
            # 1) blockcutter::1（build_timber_block_uniform）
            # -------------------------
            length_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_1", "length_fen", None), 32.0)
            width_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_1", "width_fen", None), 32.0)
            height_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_1", "height_fen", None), 20.0)

            # GH 默认参考平面：这里按你既有约定，默认 WorldXZ（过 base_point）
            ref_plane = make_ref_plane("WorldXZ", bp)

            # 多值“索引位置对齐建模”规则：三者广播到同一长度
            len_seq = to_py_list(length_fen) if isinstance(length_fen, (list, tuple)) or hasattr(length_fen,
                                                                                                 "BranchCount") else [
                length_fen]
            wid_seq = to_py_list(width_fen) if isinstance(width_fen, (list, tuple)) or hasattr(width_fen,
                                                                                               "BranchCount") else [
                width_fen]
            hei_seq = to_py_list(height_fen) if isinstance(height_fen, (list, tuple)) or hasattr(height_fen,
                                                                                                 "BranchCount") else [
                height_fen]
            n = max(len(len_seq), len(wid_seq), len(hei_seq), 1)
            len_seq = _broadcast_param(len_seq, n, "length_fen")
            wid_seq = _broadcast_param(wid_seq, n, "width_fen")
            hei_seq = _broadcast_param(hei_seq, n, "height_fen")

            timber_list = []
            faceplanes_list = []
            edgemid_list = []
            corner0_list = []
            log_lines = []

            for i in range(n):
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
                        _log,
                    ) = build_timber_block_uniform(
                        len_seq[i],
                        wid_seq[i],
                        hei_seq[i],
                        bp,
                        ref_plane,
                    )
                    timber_list.append(timber_brep)
                    faceplanes_list.append(face_planes)
                    edgemid_list.append(edge_midpts)
                    corner0_list.append(corner0_planes)
                    if _log:
                        log_lines.extend(["[blockcutter::1 #{:02d}] {}".format(i, s) for s in to_py_list(_log)])
                except Exception as ee:
                    timber_list.append(None)
                    faceplanes_list.append([])
                    edgemid_list.append([])
                    corner0_list.append([])
                    log_lines.append("[blockcutter::1 #{:02d} ERROR] {}".format(i, ee))

            # 单值时与 GH 行为一致：尽量降维
            self.blockcutter_1__TimberBrep = timber_list[0] if n == 1 else timber_list
            self.blockcutter_1__FacePlaneList = faceplanes_list[0] if n == 1 else faceplanes_list
            self.blockcutter_1__EdgeMidPoints = edgemid_list[0] if n == 1 else edgemid_list
            self.blockcutter_1__Corner0Planes = corner0_list[0] if n == 1 else corner0_list
            self.blockcutter_1__Log = log_lines

            # -------------------------
            # 2) List Item：从 FacePlaneList 取 SourcePlane（按分件/分支）
            # -------------------------
            src_idx = _get_from_alldict(self.AllDict, "GeoAligner_3", "SourcePlane", 0)
            wrap_src = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "SourcePlane_Wrap", None),
                                   True)

            def _list_item_per_branch(face_plane_tree, idx_val, wrap=True):
                # face_plane_tree: list[list[Plane]] 或 list[Plane]
                if face_plane_tree is None:
                    return []
                if isinstance(face_plane_tree, (list, tuple)) and len(face_plane_tree) > 0 and isinstance(
                        face_plane_tree[0], (list, tuple)):
                    branches = [list(b) for b in face_plane_tree]
                else:
                    branches = [to_py_list(face_plane_tree)]

                idx_seq = _broadcast_param(idx_val if isinstance(idx_val, (list, tuple)) else [idx_val], len(branches),
                                           "ListItemIndex")
                out = []
                for bi, br in enumerate(branches):
                    if br is None:
                        out.append(None)
                        continue
                    br = list(br)
                    if len(br) == 0:
                        out.append(None)
                        continue
                    try:
                        ii = int(idx_seq[bi]) if idx_seq[bi] is not None else 0
                    except Exception:
                        ii = 0
                    if wrap:
                        ii = ii % len(br)
                    if ii < 0 or ii >= len(br):
                        out.append(None)
                    else:
                        out.append(br[ii])
                return out

            self.ListItem_GA3__SourcePlane = _list_item_per_branch(self.blockcutter_1__FacePlaneList, src_idx,
                                                                   wrap=bool(wrap_src))

            # -------------------------
            # 3) Tree Item：从 TimberBlock_SkewAxis_M__Skew_Planes 按 Path+Index 取 TargetPlane
            # -------------------------
            skew_tree = getattr(self, "TimberBlock_SkewAxis_M__Skew_Planes", None)
            if skew_tree is None:
                # 兼容旧命名
                skew_tree = getattr(self, "Skew_Planes", None)

            tgt_path = _get_from_alldict(self.AllDict, "GeoAligner_3", "TargetPlane_path", None)
            tgt_index = _get_from_alldict(self.AllDict, "GeoAligner_3", "TargetPlane_index", 0)
            wrap_tgt = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "TargetPlane_Wrap", None),
                                   True)

            def _parse_path(p):
                # 允许 "{0;0}" / "0;0" / [0,0] / GH_Path
                if p is None:
                    return None
                try:
                    # GH_Path 直接返回
                    if p.__class__.__name__ == "GH_Path":
                        return p
                except Exception:
                    pass
                if isinstance(p, (list, tuple)):
                    try:
                        return [int(x) for x in p]
                    except Exception:
                        return list(p)
                s = str(p).strip()
                s = s.strip("{}")
                if ";" in s:
                    parts = [pp for pp in s.split(";") if pp != ""]
                    try:
                        return [int(pp) for pp in parts]
                    except Exception:
                        return parts
                try:
                    return [int(s)]
                except Exception:
                    return [s]

            def _tree_item(tree, paths, indices, wrap=True):
                if tree is None:
                    return []
                # 广播 paths/indices
                if not isinstance(paths, (list, tuple)):
                    paths = [paths]
                if not isinstance(indices, (list, tuple)):
                    indices = [indices]
                n2 = max(len(paths), len(indices), 1)
                paths_b = _broadcast_param(list(paths), n2, "TreeItemPath")
                idx_b = _broadcast_param(list(indices), n2, "TreeItemIndex")

                out = []
                for k in range(n2):
                    p = _parse_path(paths_b[k])
                    idx = idx_b[k]
                    try:
                        idx = int(idx) if idx is not None else 0
                    except Exception:
                        idx = 0

                    # 尝试 GH_Structure 精确取分支
                    branch = None
                    try:
                        if hasattr(tree, "Branch") and hasattr(tree, "PathCount"):
                            # 尝试构造 GH_Path
                            try:
                                from Grasshopper.Kernel.Data import GH_Path
                                if isinstance(p, list):
                                    ghp = GH_Path(*[int(x) for x in p])
                                else:
                                    ghp = p
                                branch = tree.Branch(ghp)
                            except Exception:
                                # fallback: 按字符串匹配路径
                                try:
                                    target_str = str(p)
                                    for ii in range(int(tree.PathCount)):
                                        if str(tree.Path(ii)) == target_str:
                                            branch = tree.Branch(ii)
                                            break
                                except Exception:
                                    branch = None
                    except Exception:
                        branch = None

                    if branch is None:
                        # fallback：当作嵌套列表（path 取不到就用第一个分支）
                        branches = _as_tree_branches(tree)
                        if not branches:
                            out.append(None)
                            continue
                        bi = 0
                        if isinstance(p, list) and len(p) > 0:
                            try:
                                bi = int(p[-1])
                            except Exception:
                                bi = 0
                        bi = max(0, min(bi, len(branches) - 1))
                        branch = branches[bi]

                    br = list(branch) if branch is not None else []
                    if len(br) == 0:
                        out.append(None)
                        continue
                    if wrap:
                        idx = idx % len(br)
                    if idx < 0 or idx >= len(br):
                        out.append(None)
                    else:
                        out.append(br[idx])
                return out

            self.TreeItem_GA3__TargetPlane = _tree_item(skew_tree, tgt_path, tgt_index, wrap=bool(wrap_tgt))

            # -------------------------
            # 4) GeoAligner::3
            # -------------------------
            geo_in = self.blockcutter_1__TimberBrep
            rotate_deg = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "RotateDeg", None), 0.0)
            flip_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "FlipX", None), False)
            flip_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "FlipY", None), False)
            flip_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "FlipZ", None), False)
            move_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "MoveX", None), 0.0)
            move_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "MoveY", None), 0.0)
            move_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_3", "MoveZ", None), 0.0)

            geo_branches = _as_tree_branches(geo_in)
            if not geo_branches:
                geo_branches = [[]]

            # Source/Target：这里按“列表即单分支”的约定对齐到 Geo 第一分支长度
            src_list = to_py_list(self.ListItem_GA3__SourcePlane)
            tgt_list = to_py_list(self.TreeItem_GA3__TargetPlane)

            moved_tree = []
            src_outs = []
            tgt_outs = []
            xforms = []

            # RotateDeg GH 广播对齐：若 Geo 为 Tree 多分支，且 RotateDeg 提供与分支数一致的列表，则按分支取值，再在分支内广播到项目数
            rotate_deg_list = rotate_deg if isinstance(rotate_deg, list) else to_py_list(rotate_deg)
            n_branches = len(geo_branches) if isinstance(geo_branches, list) else 1
            for b, br in enumerate(geo_branches):
                br = list(br)
                bn = max(
                    len(br),
                    len(to_py_list(src_list)),
                    len(to_py_list(tgt_list)),
                    len(to_py_list(rotate_deg)),
                    len(to_py_list(flip_x)),
                    len(to_py_list(flip_y)),
                    len(to_py_list(flip_z)),
                    len(to_py_list(move_x)),
                    len(to_py_list(move_y)),
                    len(to_py_list(move_z)),
                )
                if bn == 0:
                    moved_tree.append([])
                    continue

                # GH 广播对齐：以输入端“最大长度”为准（Geo 也需要被广播/循环对齐）
                geo_seq = _broadcast_param(br, bn, "Geo")
                src_seq = _broadcast_param(src_list, bn, "SourcePlane")
                tgt_seq = _broadcast_param(tgt_list, bn, "TargetPlane")

                # RotateDeg：若 Geo 为 Tree 多分支且 RotateDeg 与分支数一致，则先按分支取值；否则按最大长度广播
                _rot_branch = rotate_deg
                if isinstance(rotate_deg_list, list) and n_branches > 1 and len(rotate_deg_list) == n_branches:
                    _rot_branch = rotate_deg_list[b]
                rot_seq = _broadcast_param(_rot_branch, bn, "RotateDeg")

                flipx_seq = _broadcast_param(flip_x, bn, "FlipX")
                flipy_seq = _broadcast_param(flip_y, bn, "FlipY")
                flipz_seq = _broadcast_param(flip_z, bn, "FlipZ")
                movex_seq = _broadcast_param(move_x, bn, "MoveX")
                movey_seq = _broadcast_param(move_y, bn, "MoveY")
                movez_seq = _broadcast_param(move_z, bn, "MoveZ")

                out_branch = []
                for i in range(bn):
                    geo = geo_seq[i]
                    sp = src_seq[i]
                    tp = tgt_seq[i]
                    if geo is None or sp is None or tp is None:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        continue
                    try:
                        s_out, t_out, xform, moved = GeoAligner_xfm.align(
                            geo,
                            sp,
                            tp,
                            rotate_deg=rot_seq[i],
                            flip_x=bool(flipx_seq[i]),
                            flip_y=bool(flipy_seq[i]),
                            flip_z=bool(flipz_seq[i]),
                            move_x=movex_seq[i],
                            move_y=movey_seq[i],
                            move_z=movez_seq[i],
                        )
                        out_branch.append(moved)
                        src_outs.append(s_out)
                        tgt_outs.append(t_out)
                        xforms.append(xform)
                    except Exception as ee:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        self.blockcutter_1__Log.append("[GeoAligner::3 ERROR] branch={}, i={}, {}".format(b, i, ee))
                moved_tree.append(out_branch)

            # TransformOut 包装为 GH_Transform（保持与既有 GeoAligner 写法一致）
            try:
                import Grasshopper.Kernel.Types as ght
                xforms_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xforms]
            except Exception:
                xforms_wrapped = xforms

            self.GeoAligner_3__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_3__SourceOut = src_outs
            self.GeoAligner_3__TargetOut = tgt_outs
            self.GeoAligner_3__TransformOut = xforms_wrapped

            self.Log.append(
                "[Step5] blockcutter::1 + GeoAligner::3 完成: geo_branches={}, geo_items={}, src_len={}, tgt_len={}".format(
                    len(geo_branches),
                    sum([len(b) for b in geo_branches]),
                    len(src_list),
                    len(tgt_list)
                ))

        except Exception as e:
            self.Log.append("[ERROR] Step5 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 6：blockcutter::2 + ListItem + TreeItem + GeoAligner::4
    # ------------------------------------------------------
    def step6_blockcutter2_and_geoaligner4(self):
        """仅实现 Step6（不重复读库、不修改已完成步骤）。可完全复刻 Step5 的写法/风格。"""
        try:
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            # -------------------------
            # 1) blockcutter::2（build_timber_block_uniform）
            # -------------------------
            length_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_2", "length_fen", None), 32.0)
            width_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_2", "width_fen", None), 32.0)
            height_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_2", "height_fen", None), 20.0)

            # reference_plane：默认 GH XZ（过 base_point），除非 DB 覆盖
            ref_plane = make_ref_plane("WorldXZ", bp)
            _rp_db = _get_from_alldict_multi(self.AllDict, "blockcutter_2", ["reference_plane", "RefPlane", "refPlane"],
                                             None)
            if _rp_db is not None:
                try:
                    ref_plane = _rp_db
                except Exception:
                    pass

            # 多参数对齐：以输入端最大长度为准进行广播对齐
            len_seq = to_py_list(length_fen) if isinstance(length_fen, (list, tuple)) or hasattr(length_fen,
                                                                                                 "BranchCount") else [
                length_fen]
            wid_seq = to_py_list(width_fen) if isinstance(width_fen, (list, tuple)) or hasattr(width_fen,
                                                                                               "BranchCount") else [
                width_fen]
            hei_seq = to_py_list(height_fen) if isinstance(height_fen, (list, tuple)) or hasattr(height_fen,
                                                                                                 "BranchCount") else [
                height_fen]
            n = max(len(len_seq), len(wid_seq), len(hei_seq), 1)
            len_seq = _broadcast_param(len_seq, n, "length_fen")
            wid_seq = _broadcast_param(wid_seq, n, "width_fen")
            hei_seq = _broadcast_param(hei_seq, n, "height_fen")

            timber_list = []
            faceplanes_list = []
            edgemid_list = []
            corner0_list = []
            log_lines = []

            for i in range(n):
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
                        _log,
                    ) = build_timber_block_uniform(
                        len_seq[i],
                        wid_seq[i],
                        hei_seq[i],
                        bp,
                        # ref_plane,
                    )
                    timber_list.append(timber_brep)
                    faceplanes_list.append(face_planes)
                    edgemid_list.append(edge_midpts)
                    corner0_list.append(corner0_planes)
                    if _log:
                        log_lines.extend(["[blockcutter::2 #{:02d}] {}".format(i, s) for s in to_py_list(_log)])
                except Exception as ee:
                    timber_list.append(None)
                    faceplanes_list.append([])
                    edgemid_list.append([])
                    corner0_list.append([])
                    log_lines.append("[blockcutter::2 #{:02d} ERROR] {}".format(i, ee))

            self.blockcutter_2__TimberBrep = timber_list[0] if n == 1 else timber_list
            self.blockcutter_2__FacePlaneList = faceplanes_list[0] if n == 1 else faceplanes_list
            self.blockcutter_2__EdgeMidPoints = edgemid_list[0] if n == 1 else edgemid_list
            self.blockcutter_2__Corner0Planes = corner0_list[0] if n == 1 else corner0_list
            self.blockcutter_2__Log = log_lines

            # -------------------------
            # 2) List Item：从 FacePlaneList 取 SourcePlane
            # -------------------------
            src_idx = _get_from_alldict(self.AllDict, "GeoAligner_4", "SourcePlane", 0)
            wrap_src = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "SourcePlane_Wrap", None),
                                   True)

            def _list_item_per_branch(face_plane_tree, idx_val, wrap=True):
                if face_plane_tree is None:
                    return []
                if isinstance(face_plane_tree, (list, tuple)) and len(face_plane_tree) > 0 and isinstance(
                        face_plane_tree[0], (list, tuple)):
                    branches = [list(b) for b in face_plane_tree]
                else:
                    branches = [to_py_list(face_plane_tree)]

                idx_seq = _broadcast_param(idx_val if isinstance(idx_val, (list, tuple)) else [idx_val], len(branches),
                                           "ListItemIndex")
                out = []
                for bi, br in enumerate(branches):
                    if br is None:
                        out.append(None)
                        continue
                    br = list(br)
                    if len(br) == 0:
                        out.append(None)
                        continue
                    try:
                        ii = int(idx_seq[bi]) if idx_seq[bi] is not None else 0
                    except Exception:
                        ii = 0
                    if wrap:
                        ii = ii % len(br)
                    if ii < 0 or ii >= len(br):
                        out.append(None)
                    else:
                        out.append(br[ii])
                return out

            self.ListItem_GA4__SourcePlane = _list_item_per_branch(self.blockcutter_2__FacePlaneList, src_idx,
                                                                   wrap=bool(wrap_src))

            # -------------------------
            # 3) Tree Item：从 TimberBlock_SkewAxis_M 的 Skew_Planes 取 TargetPlane
            # -------------------------
            skew_tree = getattr(self, "TimberBlock_SkewAxis_M__Skew_Planes", None)
            if skew_tree is None:
                skew_tree = getattr(self, "Skew_Planes", None)

            tgt_path = _get_from_alldict(self.AllDict, "GeoAligner_4", "TargetPlane_path", None)
            tgt_index = _get_from_alldict(self.AllDict, "GeoAligner_4", "TargetPlane_index", 0)
            wrap_tgt = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "TargetPlane_Wrap", None),
                                   True)

            def _parse_path(p):
                if p is None:
                    return None
                try:
                    if p.__class__.__name__ == "GH_Path":
                        return p
                except Exception:
                    pass
                if isinstance(p, (list, tuple)):
                    try:
                        return [int(x) for x in p]
                    except Exception:
                        return list(p)
                s = str(p).strip().strip("{}")
                if ";" in s:
                    parts = [pp for pp in s.split(";") if pp != ""]
                    try:
                        return [int(pp) for pp in parts]
                    except Exception:
                        return parts
                try:
                    return [int(s)]
                except Exception:
                    return [s]

            def _tree_item(tree, paths, indices, wrap=True):
                if tree is None:
                    return []
                if not isinstance(paths, (list, tuple)):
                    paths = [paths]
                if not isinstance(indices, (list, tuple)):
                    indices = [indices]
                n2 = max(len(paths), len(indices), 1)
                paths_b = _broadcast_param(list(paths), n2, "TreeItemPath")
                idx_b = _broadcast_param(list(indices), n2, "TreeItemIndex")

                out = []
                for k in range(n2):
                    p = _parse_path(paths_b[k])
                    idx = idx_b[k]
                    try:
                        idx = int(idx) if idx is not None else 0
                    except Exception:
                        idx = 0

                    branch = None
                    try:
                        if hasattr(tree, "Branch") and hasattr(tree, "PathCount"):
                            try:
                                from Grasshopper.Kernel.Data import GH_Path
                                if isinstance(p, list):
                                    ghp = GH_Path(*[int(x) for x in p])
                                else:
                                    ghp = p
                                branch = tree.Branch(ghp)
                            except Exception:
                                try:
                                    target_str = str(p)
                                    for ii in range(int(tree.PathCount)):
                                        if str(tree.Path(ii)) == target_str:
                                            branch = tree.Branch(ii)
                                            break
                                except Exception:
                                    branch = None
                    except Exception:
                        branch = None

                    if branch is None:
                        branches = _as_tree_branches(tree)
                        if not branches:
                            out.append(None)
                            continue
                        bi = 0
                        if isinstance(p, list) and len(p) > 0:
                            try:
                                bi = int(p[-1])
                            except Exception:
                                bi = 0
                        bi = max(0, min(bi, len(branches) - 1))
                        branch = branches[bi]

                    br = list(branch) if branch is not None else []
                    if len(br) == 0:
                        out.append(None)
                        continue
                    if wrap:
                        idx = idx % len(br)
                    if idx < 0 or idx >= len(br):
                        out.append(None)
                    else:
                        out.append(br[idx])
                return out

            self.TreeItem_GA4__TargetPlane = _tree_item(skew_tree, tgt_path, tgt_index, wrap=bool(wrap_tgt))

            # -------------------------
            # 4) GeoAligner::4（按 GH 广播 + Tree 分支循环）
            # -------------------------
            geo_in = self.blockcutter_2__TimberBrep
            rotate_deg = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "RotateDeg", None), 0.0)
            flip_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "FlipX", None), False)
            flip_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "FlipY", None), False)
            flip_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "FlipZ", None), False)
            move_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "MoveX", None), 0.0)
            move_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "MoveY", None), 0.0)
            move_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_4", "MoveZ", None), 0.0)

            geo_branches = _as_tree_branches(geo_in)
            if not geo_branches:
                geo_branches = [[]]

            src_list = to_py_list(self.ListItem_GA4__SourcePlane)
            tgt_list = to_py_list(self.TreeItem_GA4__TargetPlane)

            moved_tree = []
            src_outs = []
            tgt_outs = []
            xforms = []

            rotate_deg_list = rotate_deg if isinstance(rotate_deg, list) else to_py_list(rotate_deg)
            n_branches = len(geo_branches) if isinstance(geo_branches, list) else 1

            # Step6 日志：结构与广播
            self.blockcutter_2__Log.append(
                "[Step6] Geo branches={} | Geo items={} | SourcePlanes={} | TargetPlanes={}".format(
                    len(geo_branches),
                    sum([len(b) for b in geo_branches]),
                    len(src_list),
                    len(tgt_list),
                ))

            for b, br in enumerate(geo_branches):
                br = list(br)
                bn = max(
                    len(br),
                    len(to_py_list(src_list)),
                    len(to_py_list(tgt_list)),
                    len(to_py_list(rotate_deg)),
                    len(to_py_list(flip_x)),
                    len(to_py_list(flip_y)),
                    len(to_py_list(flip_z)),
                    len(to_py_list(move_x)),
                    len(to_py_list(move_y)),
                    len(to_py_list(move_z)),
                )
                if bn == 0:
                    moved_tree.append([])
                    continue

                geo_seq = _broadcast_param(br, bn, "Geo")
                src_seq = _broadcast_param(src_list, bn, "SourcePlane")
                tgt_seq = _broadcast_param(tgt_list, bn, "TargetPlane")

                _rot_branch = rotate_deg
                if isinstance(rotate_deg_list, list) and n_branches > 1 and len(rotate_deg_list) == n_branches:
                    _rot_branch = rotate_deg_list[b]
                rot_seq = _broadcast_param(_rot_branch, bn, "RotateDeg")

                flipx_seq = _broadcast_param(flip_x, bn, "FlipX")
                flipy_seq = _broadcast_param(flip_y, bn, "FlipY")
                flipz_seq = _broadcast_param(flip_z, bn, "FlipZ")
                movex_seq = _broadcast_param(move_x, bn, "MoveX")
                movey_seq = _broadcast_param(move_y, bn, "MoveY")
                movez_seq = _broadcast_param(move_z, bn, "MoveZ")

                self.blockcutter_2__Log.append("[Step6] branch={} broadcast_len={}".format(b, bn))

                out_branch = []
                for i in range(bn):
                    geo = geo_seq[i]
                    sp = src_seq[i]
                    tp = tgt_seq[i]
                    if geo is None or sp is None or tp is None:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        continue
                    try:
                        s_out, t_out, xform, moved = GeoAligner_xfm.align(
                            geo,
                            sp,
                            tp,
                            rotate_deg=rot_seq[i],
                            flip_x=bool(flipx_seq[i]),
                            flip_y=bool(flipy_seq[i]),
                            flip_z=bool(flipz_seq[i]),
                            move_x=movex_seq[i],
                            move_y=movey_seq[i],
                            move_z=movez_seq[i],
                        )
                        out_branch.append(moved)
                        src_outs.append(s_out)
                        tgt_outs.append(t_out)
                        xforms.append(xform)
                    except Exception as ee:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        self.blockcutter_2__Log.append("[GeoAligner::4 ERROR] branch={}, i={}, {}".format(b, i, ee))
                moved_tree.append(out_branch)

            try:
                import Grasshopper.Kernel.Types as ght
                xforms_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xforms]
            except Exception:
                xforms_wrapped = xforms

            self.GeoAligner_4__MovedGeoTree = moved_tree
            self.GeoAligner_4__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_4__SourceOut = src_outs
            self.GeoAligner_4__TargetOut = tgt_outs
            self.GeoAligner_4__TransformOut = xforms_wrapped

            self.Log.append(
                "[Step6] blockcutter::2 + GeoAligner::4 完成: geo_branches={}, geo_items={}, src_len={}, tgt_len={}, moved(flat)={}".format(
                    len(geo_branches),
                    sum([len(b) for b in geo_branches]),
                    len(src_list),
                    len(tgt_list),
                    len(self.GeoAligner_4__MovedGeo) if isinstance(self.GeoAligner_4__MovedGeo, list) else 1,
                ))

        except Exception as e:
            self.Log.append("[ERROR] Step6 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 7：blockcutter::3 + List Item + Tree Item + GeoAligner::5
    # ------------------------------------------------------
    def step7_blockcutter3_geoaligner5(self):
        """仅实现 Step7（不重复读库、不修改已完成步骤）。"""
        try:
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            # -------------------------
            # 1) blockcutter::3（build_timber_block_uniform）
            # -------------------------
            length_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_3", "length_fen", None), 32.0)
            width_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_3", "width_fen", None), 32.0)
            height_fen = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_3", "height_fen", None), 20.0)

            # ⚠️ reference_plane：保持 blockcutter::3 组件默认行为（不从 AllDict 覆盖）
            # build_timber_block_uniform 若有默认 reference_plane，这里不显式传入以保持一致。

            len_seq = to_py_list(length_fen) if isinstance(length_fen, (list, tuple)) or hasattr(length_fen,
                                                                                                 "BranchCount") else [
                length_fen]
            wid_seq = to_py_list(width_fen) if isinstance(width_fen, (list, tuple)) or hasattr(width_fen,
                                                                                               "BranchCount") else [
                width_fen]
            hei_seq = to_py_list(height_fen) if isinstance(height_fen, (list, tuple)) or hasattr(height_fen,
                                                                                                 "BranchCount") else [
                height_fen]
            n = max(len(len_seq), len(wid_seq), len(hei_seq), 1)
            len_seq = _broadcast_param(len_seq, n, "length_fen")
            wid_seq = _broadcast_param(wid_seq, n, "width_fen")
            hei_seq = _broadcast_param(hei_seq, n, "height_fen")

            timber_list = []
            faces_list = []
            points_list = []
            edges_list = []
            centerpt_list = []
            centeraxes_list = []
            edgemid_list = []
            faceplanes_list = []
            corner0_list = []
            local_axes_list = []
            axisx_list = []
            axisy_list = []
            axisz_list = []
            facetag_list = []
            edgetag_list = []
            corner0dir_list = []
            log_lines = []

            for i in range(n):
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
                        _log,
                    ) = build_timber_block_uniform(
                        len_seq[i],
                        wid_seq[i],
                        hei_seq[i],
                        bp,
                        # reference_plane 省略：保持默认行为
                    )
                    timber_list.append(timber_brep)
                    faces_list.append(faces)
                    points_list.append(points)
                    edges_list.append(edges)
                    centerpt_list.append(center_pt)
                    centeraxes_list.append(center_axes)
                    edgemid_list.append(edge_midpts)
                    faceplanes_list.append(face_planes)
                    corner0_list.append(corner0_planes)
                    local_axes_list.append(local_axes_plane)
                    axisx_list.append(axis_x)
                    axisy_list.append(axis_y)
                    axisz_list.append(axis_z)
                    facetag_list.append(face_tags)
                    edgetag_list.append(edge_tags)
                    corner0dir_list.append(corner0_dirs)
                    if _log:
                        log_lines.extend(["[blockcutter::3 #{:02d}] {}".format(i, s) for s in to_py_list(_log)])
                except Exception as ee:
                    timber_list.append(None)
                    faces_list.append([])
                    points_list.append([])
                    edges_list.append([])
                    centerpt_list.append(None)
                    centeraxes_list.append([])
                    edgemid_list.append([])
                    faceplanes_list.append([])
                    corner0_list.append([])
                    local_axes_list.append(None)
                    axisx_list.append(None)
                    axisy_list.append(None)
                    axisz_list.append(None)
                    facetag_list.append([])
                    edgetag_list.append([])
                    corner0dir_list.append([])
                    log_lines.append("[blockcutter::3 #{:02d} ERROR] {}".format(i, ee))

            # 保存所有原输出（developer-friendly）
            self.blockcutter_3__TimberBrep = timber_list[0] if n == 1 else timber_list
            self.blockcutter_3__FaceList = faces_list[0] if n == 1 else faces_list
            self.blockcutter_3__PointList = points_list[0] if n == 1 else points_list
            self.blockcutter_3__EdgeList = edges_list[0] if n == 1 else edges_list
            self.blockcutter_3__CenterPoint = centerpt_list[0] if n == 1 else centerpt_list
            self.blockcutter_3__CenterAxisLines = centeraxes_list[0] if n == 1 else centeraxes_list
            self.blockcutter_3__EdgeMidPoints = edgemid_list[0] if n == 1 else edgemid_list
            self.blockcutter_3__FacePlaneList = faceplanes_list[0] if n == 1 else faceplanes_list
            self.blockcutter_3__Corner0Planes = corner0_list[0] if n == 1 else corner0_list
            self.blockcutter_3__LocalAxesPlane = local_axes_list[0] if n == 1 else local_axes_list
            self.blockcutter_3__AxisX = axisx_list[0] if n == 1 else axisx_list
            self.blockcutter_3__AxisY = axisy_list[0] if n == 1 else axisy_list
            self.blockcutter_3__AxisZ = axisz_list[0] if n == 1 else axisz_list
            self.blockcutter_3__FaceDirTags = facetag_list[0] if n == 1 else facetag_list
            self.blockcutter_3__EdgeDirTags = edgetag_list[0] if n == 1 else edgetag_list
            self.blockcutter_3__Corner0EdgeDirs = corner0dir_list[0] if n == 1 else corner0dir_list
            self.blockcutter_3__Log = log_lines

            # -------------------------
            # 2) List Item：从 FacePlaneList 取 SourcePlane
            # -------------------------
            src_idx = _get_from_alldict(self.AllDict, "GeoAligner_5", "SourcePlane", 0)
            wrap_src = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "SourcePlane_Wrap", None),
                                   True)

            def _list_item_per_branch(face_plane_tree, idx_val, wrap=True):
                if face_plane_tree is None:
                    return []
                if isinstance(face_plane_tree, (list, tuple)) and len(face_plane_tree) > 0 and isinstance(
                        face_plane_tree[0], (list, tuple)):
                    branches = [list(b) for b in face_plane_tree]
                else:
                    branches = [to_py_list(face_plane_tree)]

                idx_seq = _broadcast_param(idx_val if isinstance(idx_val, (list, tuple)) else [idx_val], len(branches),
                                           "ListItemIndex")
                out = []
                for bi, br in enumerate(branches):
                    if br is None:
                        out.append(None)
                        continue
                    br = list(br)
                    if len(br) == 0:
                        out.append(None)
                        continue
                    try:
                        ii = int(idx_seq[bi]) if idx_seq[bi] is not None else 0
                    except Exception:
                        ii = 0
                    if wrap:
                        ii = ii % len(br)
                    if ii < 0 or ii >= len(br):
                        out.append(None)
                    else:
                        out.append(br[ii])
                return out

            self.GeoAligner_5__SourcePlane_ListItem = _list_item_per_branch(self.blockcutter_3__FacePlaneList, src_idx,
                                                                            wrap=bool(wrap_src))

            # -------------------------
            # 3) Tree Item：从 TimberBlock_SkewAxis_M 的 Skew_Planes 取 TargetPlane
            # -------------------------
            skew_tree = getattr(self, "TimberBlock_SkewAxis_M__Skew_Planes", None)
            if skew_tree is None:
                skew_tree = getattr(self, "Skew_Planes", None)

            tgt_path = _get_from_alldict(self.AllDict, "GeoAligner_5", "TargetPlane_path", None)
            tgt_index = _get_from_alldict(self.AllDict, "GeoAligner_5", "TargetPlane_index", 0)
            wrap_tgt = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "TargetPlane_Wrap", None),
                                   True)

            def _parse_path(p):
                if p is None:
                    return None
                try:
                    if p.__class__.__name__ == "GH_Path":
                        return p
                except Exception:
                    pass
                if isinstance(p, (list, tuple)):
                    try:
                        return [int(x) for x in p]
                    except Exception:
                        return list(p)
                s = str(p).strip().strip("{}")
                if ";" in s:
                    parts = [pp for pp in s.split(";") if pp != ""]
                    try:
                        return [int(pp) for pp in parts]
                    except Exception:
                        return parts
                try:
                    return [int(s)]
                except Exception:
                    return [s]

            def _tree_item(tree, paths, indices, wrap=True):
                if tree is None:
                    return []
                if not isinstance(paths, (list, tuple)):
                    paths = [paths]
                if not isinstance(indices, (list, tuple)):
                    indices = [indices]
                n2 = max(len(paths), len(indices), 1)
                paths_b = _broadcast_param(list(paths), n2, "TreeItemPath")
                idx_b = _broadcast_param(list(indices), n2, "TreeItemIndex")

                out = []
                for k in range(n2):
                    p = _parse_path(paths_b[k])
                    idx = idx_b[k]
                    try:
                        idx = int(idx) if idx is not None else 0
                    except Exception:
                        idx = 0

                    branch = None
                    try:
                        if hasattr(tree, "Branch") and hasattr(tree, "PathCount"):
                            try:
                                from Grasshopper.Kernel.Data import GH_Path
                                if isinstance(p, list):
                                    ghp = GH_Path(*[int(x) for x in p])
                                else:
                                    ghp = p
                                branch = tree.Branch(ghp)
                            except Exception:
                                try:
                                    target_str = str(p)
                                    for ii in range(int(tree.PathCount)):
                                        if str(tree.Path(ii)) == target_str:
                                            branch = tree.Branch(ii)
                                            break
                                except Exception:
                                    branch = None
                    except Exception:
                        branch = None

                    if branch is None:
                        branches = _as_tree_branches(tree)
                        if not branches:
                            out.append(None)
                            continue
                        bi = 0
                        if isinstance(p, list) and len(p) > 0:
                            try:
                                bi = int(p[-1])
                            except Exception:
                                bi = 0
                        bi = max(0, min(bi, len(branches) - 1))
                        branch = branches[bi]

                    br = list(branch) if branch is not None else []
                    if len(br) == 0:
                        out.append(None)
                        continue
                    if wrap:
                        idx = idx % len(br)
                    if idx < 0 or idx >= len(br):
                        out.append(None)
                    else:
                        out.append(br[idx])
                return out

            self.GeoAligner_5__TargetPlane_TreeItem = _tree_item(skew_tree, tgt_path, tgt_index, wrap=bool(wrap_tgt))

            # -------------------------
            # 4) GeoAligner::5（按 GH 广播 + Tree 分支循环）
            # -------------------------
            geo_in = self.blockcutter_3__TimberBrep
            rotate_deg = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "RotateDeg", None), 0.0)
            flip_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "FlipX", None), False)
            flip_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "FlipY", None), False)
            flip_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "FlipZ", None), False)
            move_x = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "MoveX", None), 0.0)
            move_y = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "MoveY", None), 0.0)
            move_z = _pick_param(None, _get_from_alldict(self.AllDict, "GeoAligner_5", "MoveZ", None), 0.0)

            geo_branches = _as_tree_branches(geo_in)
            if not geo_branches:
                geo_branches = [[]]

            src_list = to_py_list(self.GeoAligner_5__SourcePlane_ListItem)
            tgt_list = to_py_list(self.GeoAligner_5__TargetPlane_TreeItem)

            moved_tree = []
            src_outs = []
            tgt_outs = []
            xforms = []

            rotate_deg_list = rotate_deg if isinstance(rotate_deg, list) else to_py_list(rotate_deg)
            n_branches = len(geo_branches) if isinstance(geo_branches, list) else 1

            # Step7 日志：结构与广播
            self.blockcutter_3__Log.append(
                "[Step7] Geo branches={} | Geo items={} | SourcePlanes={} | TargetPlanes={}".format(
                    len(geo_branches),
                    sum([len(b) for b in geo_branches]),
                    len(src_list),
                    len(tgt_list),
                ))

            for b, br in enumerate(geo_branches):
                br = list(br)
                bn = max(
                    len(br),
                    len(to_py_list(src_list)),
                    len(to_py_list(tgt_list)),
                    len(to_py_list(rotate_deg)),
                    len(to_py_list(flip_x)),
                    len(to_py_list(flip_y)),
                    len(to_py_list(flip_z)),
                    len(to_py_list(move_x)),
                    len(to_py_list(move_y)),
                    len(to_py_list(move_z)),
                )
                if bn == 0:
                    moved_tree.append([])
                    continue

                geo_seq = _broadcast_param(br, bn, "Geo")
                src_seq = _broadcast_param(src_list, bn, "SourcePlane")
                tgt_seq = _broadcast_param(tgt_list, bn, "TargetPlane")

                _rot_branch = rotate_deg
                if isinstance(rotate_deg_list, list) and n_branches > 1 and len(rotate_deg_list) == n_branches:
                    _rot_branch = rotate_deg_list[b]
                rot_seq = _broadcast_param(_rot_branch, bn, "RotateDeg")

                flipx_seq = _broadcast_param(flip_x, bn, "FlipX")
                flipy_seq = _broadcast_param(flip_y, bn, "FlipY")
                flipz_seq = _broadcast_param(flip_z, bn, "FlipZ")
                movex_seq = _broadcast_param(move_x, bn, "MoveX")
                movey_seq = _broadcast_param(move_y, bn, "MoveY")
                movez_seq = _broadcast_param(move_z, bn, "MoveZ")

                self.blockcutter_3__Log.append("[Step7] branch={} broadcast_len={}".format(b, bn))

                out_branch = []
                for i in range(bn):
                    geo = geo_seq[i]
                    sp = src_seq[i]
                    tp = tgt_seq[i]
                    if geo is None or sp is None or tp is None:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        continue
                    try:
                        s_out, t_out, xform, moved = GeoAligner_xfm.align(
                            geo,
                            sp,
                            tp,
                            rotate_deg=rot_seq[i],
                            flip_x=bool(flipx_seq[i]),
                            flip_y=bool(flipy_seq[i]),
                            flip_z=bool(flipz_seq[i]),
                            move_x=movex_seq[i],
                            move_y=movey_seq[i],
                            move_z=movez_seq[i],
                        )
                        out_branch.append(moved)
                        src_outs.append(s_out)
                        tgt_outs.append(t_out)
                        xforms.append(xform)
                    except Exception as ee:
                        out_branch.append(None)
                        src_outs.append(sp)
                        tgt_outs.append(tp)
                        xforms.append(None)
                        self.blockcutter_3__Log.append("[GeoAligner::5 ERROR] branch={}, i={}, {}".format(b, i, ee))
                moved_tree.append(out_branch)

            try:
                import Grasshopper.Kernel.Types as ght
                xforms_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xforms]
            except Exception:
                xforms_wrapped = xforms

            self.GeoAligner_5__MovedGeoTree = moved_tree
            # Step7 输出端要求：必要时展平（后续未明确要 Tree，默认展平）
            self.GeoAligner_5__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_5__SourceOut = src_outs
            self.GeoAligner_5__TargetOut = tgt_outs
            self.GeoAligner_5__TransformOut = xforms_wrapped

            # Step7 汇总日志
            self.Step7__Log = []
            self.Step7__Log.extend(self.blockcutter_3__Log if isinstance(self.blockcutter_3__Log, list) else [
                str(self.blockcutter_3__Log)])
            self.Step7__Log.append(
                "[Step7] blockcutter::3 + GeoAligner::5 完成: geo_branches={}, geo_items={}, src_len={}, tgt_len={}, moved(flat)={}".format(
                    len(geo_branches),
                    sum([len(b) for b in geo_branches]),
                    len(src_list),
                    len(tgt_list),
                    len(self.GeoAligner_5__MovedGeo) if isinstance(self.GeoAligner_5__MovedGeo, list) else 1,
                ))

            self.Log.append("[Step7] blockcutter::3 + GeoAligner::5 完成。")

        except Exception as e:
            self.Log.append("[ERROR] Step7 出错: {}".format(e))
            try:
                self.Step7__Log = ["[ERROR] Step7 出错: {}".format(e)]
            except Exception:
                pass

        return self

    # ------------------------------------------------------
    # Step 8：AxisLinesIntersectionsSolver + SectionExtrude_SymmetricTrapezoid::1 + AlignToolToTimber::6
    # ------------------------------------------------------
    def step8_axis_section_align(self):
        """Step8（按提示词）：
        1) AxisLinesIntersectionsSolver（轴线与交点）
        2) SectionExtrude_SymmetricTrapezoid::1（对称梯形截面 + 拉伸成 solid_list）
        3) AlignToolToTimber::6（一次性对位 solid_list 到 GeoAligner::3 的 TargetPlane）
        """
        try:
            # -----------------------------
            # Step8-1 AxisLinesIntersectionsSolver
            # -----------------------------
            O = rg.Point3d(0.0, 0.0, 0.0)
            RefPlane = make_ref_plane("WorldXY", O)

            d = _pick_param(None, self.AllDict.get("AxisLinesIntersectionsSolver__d", None), 1.0)
            L12_len = _pick_param(None, self.AllDict.get("AxisLinesIntersectionsSolver__L12_len", None), 1.0)
            L36_len = _pick_param(None, self.AllDict.get("AxisLinesIntersectionsSolver__L36_len", None), 1.0)
            alpha_deg = _pick_param(None, self.AllDict.get("AxisLinesIntersectionsSolver__alpha_deg", None), 0.0)
            axis_len = _pick_param(None, self.AllDict.get("AxisLinesIntersectionsSolver__axis_len", None), 10.0)

            _solver = AxisLinesIntersectionsSolver()
            _out = _solver.solve(O, RefPlane, d, L12_len, L36_len, alpha_deg, axis_len)

            self.AxisLinesIntersectionsSolver__Axis_AO = _out.get("Axis_AO", None)
            self.AxisLinesIntersectionsSolver__Axis_AC = _out.get("Axis_AC", None)
            self.AxisLinesIntersectionsSolver__Axis_AD = _out.get("Axis_AD", None)

            self.AxisLinesIntersectionsSolver__L1 = _out.get("L1", None)
            self.AxisLinesIntersectionsSolver__L2 = _out.get("L2", None)
            self.AxisLinesIntersectionsSolver__L3 = _out.get("L3", None)
            self.AxisLinesIntersectionsSolver__L4 = _out.get("L4", None)
            self.AxisLinesIntersectionsSolver__L5 = _out.get("L5", None)
            self.AxisLinesIntersectionsSolver__L6 = _out.get("L6", None)

            self.AxisLinesIntersectionsSolver__O_out = _out.get("O_out", None)
            self.AxisLinesIntersectionsSolver__A = _out.get("A", None)
            self.AxisLinesIntersectionsSolver__B = _out.get("B", None)

            self.AxisLinesIntersectionsSolver__J = _out.get("J", None)
            self.AxisLinesIntersectionsSolver__K = _out.get("K", None)
            self.AxisLinesIntersectionsSolver__Jp = _out.get("Jp", None)
            self.AxisLinesIntersectionsSolver__Kp = _out.get("Kp", None)

            self.AxisLinesIntersectionsSolver__Dist_BJ = _out.get("Dist_BJ", None)
            self.AxisLinesIntersectionsSolver__Dist_JK = _out.get("Dist_JK", None)

            self.AxisLinesIntersectionsSolver__Log = to_py_list(_out.get("Log", []))

            self.Log.append("[Step8-1] AxisLinesIntersectionsSolver 完成。")
            for l in self.AxisLinesIntersectionsSolver__Log:
                self.Log.append("[Step8-1] " + str(l))

            # -----------------------------
            # Step8-2 SectionExtrude_SymmetricTrapezoid::1
            # -----------------------------
            base_point = rg.Point3d(0.0, 0.0, 0.0)
            ref_plane = make_ref_plane("WorldXY", base_point)

            ab_len = self.AxisLinesIntersectionsSolver__Dist_JK
            oe_len = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_1__oe_len", None), 5.0)
            angle_deg = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_1__angle_deg", None), 0.0)
            extrude_h = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_1__extrude_h", None),
                                    10.0)
            oo_prime = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_1__oo_prime", None), 1.0)

            sec = SectionExtrude_SymmetricTrapezoid(
                base_point=base_point,
                ref_plane=ref_plane,
                ab_len=ab_len,
                oe_len=oe_len,
                angle_deg=angle_deg,
                extrude_h=extrude_h,
                oo_prime=oo_prime
            ).build()

            # Points
            self.SectionExtrude_SymmetricTrapezoid_1__A = getattr(sec, "A", None)
            self.SectionExtrude_SymmetricTrapezoid_1__B = getattr(sec, "B", None)
            self.SectionExtrude_SymmetricTrapezoid_1__C = getattr(sec, "C", None)
            self.SectionExtrude_SymmetricTrapezoid_1__D = getattr(sec, "D", None)
            self.SectionExtrude_SymmetricTrapezoid_1__O = getattr(sec, "O", None)
            self.SectionExtrude_SymmetricTrapezoid_1__E = getattr(sec, "E", None)
            self.SectionExtrude_SymmetricTrapezoid_1__Oprime = getattr(sec, "Oprime", None)

            # Lines / Axis
            self.SectionExtrude_SymmetricTrapezoid_1__AB = getattr(sec, "AB", None)
            self.SectionExtrude_SymmetricTrapezoid_1__CD = getattr(sec, "CD", None)
            self.SectionExtrude_SymmetricTrapezoid_1__AC = getattr(sec, "AC", None)
            self.SectionExtrude_SymmetricTrapezoid_1__BD = getattr(sec, "BD", None)
            self.SectionExtrude_SymmetricTrapezoid_1__Axis_AC = getattr(sec, "Axis_AC", None)

            # Section
            self.SectionExtrude_SymmetricTrapezoid_1__section_polyline = getattr(sec, "section_polyline", None)
            self.SectionExtrude_SymmetricTrapezoid_1__section_curve = getattr(sec, "section_curve", None)
            self.SectionExtrude_SymmetricTrapezoid_1__section_brep = getattr(sec, "section_brep", None)

            # Solids
            self.SectionExtrude_SymmetricTrapezoid_1__solid_brep = getattr(sec, "solid_brep", None)
            self.SectionExtrude_SymmetricTrapezoid_1__solid_brep_mirror = getattr(sec, "solid_brep_mirror", None)
            self.SectionExtrude_SymmetricTrapezoid_1__solid_list = getattr(sec, "solid_list", None)

            # Planes
            self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime = getattr(sec, "Plane_Oprime", None)
            self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime_X = getattr(sec, "Plane_Oprime_X", None)
            self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime_Y = getattr(sec, "Plane_Oprime_Y", None)
            self.SectionExtrude_SymmetricTrapezoid_1__MirrorPlane_ACZ = getattr(sec, "MirrorPlane_ACZ", None)

            self.SectionExtrude_SymmetricTrapezoid_1__log = to_py_list(getattr(sec, "log", []))

            self.Log.append("[Step8-2] SectionExtrude_SymmetricTrapezoid::1 完成。")
            for l in self.SectionExtrude_SymmetricTrapezoid_1__log:
                self.Log.append("[Step8-2] " + str(l))

            # -----------------------------
            # Step8-3 AlignToolToTimber::6（Geo 作为整体，一次 align）
            # -----------------------------
            # Geo：来自 solid_list（N=2），允许从嵌套展平，但最终一次性 align
            geo_raw = self.SectionExtrude_SymmetricTrapezoid_1__solid_list
            geo_list = flatten_any(geo_raw)
            if geo_list is None:
                geo_list = []
            # 确保是 list（规则 B：不做循环广播）
            if not isinstance(geo_list, list):
                geo_list = [geo_list]

            SourcePlane = self.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime

            # TargetPlane：必须与 GeoAligner::3.TargetPlane 一致（沿用既有变量，不重算）
            TargetPlane = getattr(self, "TreeItem_GA3__TargetPlane", None)

            RotateDeg = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__RotateDeg", None), 0.0)
            FlipX = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__FlipX", None), False)
            FlipY = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__FlipY", None), False)
            FlipZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__FlipZ", None), False)
            MoveX = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__MoveX", None), 0.0)
            MoveY = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__MoveY", None), 0.0)
            MoveZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_6__MoveZ", None), 0.0)

            # Align（优先按原数据结构直接传入；若因 Tree 结构导致异常，再降级取首个平面）
            try:
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    TargetPlane,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
            except Exception as ee:
                # 尝试降级：TargetPlane 取首个可用 Plane
                tp_try = TargetPlane
                try:
                    brs = _as_tree_branches(TargetPlane)
                    tp_try = None
                    for br in brs:
                        for it in br:
                            if isinstance(it, rg.Plane):
                                tp_try = it
                                break
                        if tp_try is not None:
                            break
                except Exception:
                    tp_try = TargetPlane

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    tp_try,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
                self.Log.append("[Step8-3][WARN] TargetPlane Tree 兼容降级: {}".format(ee))

            # TransformOut -> GH_Transform（若可用）
            try:
                import Grasshopper.Kernel.Types as ght
                TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            except Exception:
                pass

            self.AlignToolToTimber_6__SourceOut = SourceOut
            self.AlignToolToTimber_6__TargetOut = TargetOut
            self.AlignToolToTimber_6__TransformOut = TransformOut
            self.AlignToolToTimber_6__MovedGeo = MovedGeo

            self.Log.append("[Step8-3] AlignToolToTimber::6 完成。 GeoCount={}".format(len(geo_list)))

            self.Log.append("[Step8] Step8 完成。")

        except Exception as e:
            self.Log.append("[ERROR] Step8 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 9：SectionExtrude_SymmetricTrapezoid::2 + AlignToolToTimber::7
    # ------------------------------------------------------
    def step9_trapezoid2_align7(self):
        """Step9（按提示词）：
        1) SectionExtrude_SymmetricTrapezoid::2（ab_len = AxisLinesIntersectionsSolver.Dist_JK）
        2) AlignToolToTimber::7（TargetPlane = GeoAligner::4.TargetPlane；Geo 作为整体一次 align）
        """
        try:
            # -----------------------------
            # Step9-1 SectionExtrude_SymmetricTrapezoid::2
            # -----------------------------
            base_point = rg.Point3d(0.0, 0.0, 0.0)
            ref_plane = make_ref_plane("WorldXY", base_point)

            # 约束 C：ab_len = AxisLinesIntersectionsSolver.Dist_JK
            ab_len = getattr(self, "AxisLinesIntersectionsSolver__Dist_JK", None)

            oe_len = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_2__oe_len", None), 5.0)
            angle_deg = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_2__angle_deg", None), 0.0)
            extrude_h = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_2__extrude_h", None),
                                    10.0)
            oo_prime = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_2__oo_prime", None), 1.0)

            sec = SectionExtrude_SymmetricTrapezoid(
                base_point=base_point,
                ref_plane=ref_plane,
                ab_len=ab_len,
                oe_len=oe_len,
                angle_deg=angle_deg,
                extrude_h=extrude_h,
                oo_prime=oo_prime
            ).build()

            # Points
            self.SectionExtrude_SymmetricTrapezoid_2__A = getattr(sec, "A", None)
            self.SectionExtrude_SymmetricTrapezoid_2__B = getattr(sec, "B", None)
            self.SectionExtrude_SymmetricTrapezoid_2__C = getattr(sec, "C", None)
            self.SectionExtrude_SymmetricTrapezoid_2__D = getattr(sec, "D", None)
            self.SectionExtrude_SymmetricTrapezoid_2__O = getattr(sec, "O", None)
            self.SectionExtrude_SymmetricTrapezoid_2__E = getattr(sec, "E", None)
            self.SectionExtrude_SymmetricTrapezoid_2__Oprime = getattr(sec, "Oprime", None)

            # Lines / Axis
            self.SectionExtrude_SymmetricTrapezoid_2__AB = getattr(sec, "AB", None)
            self.SectionExtrude_SymmetricTrapezoid_2__CD = getattr(sec, "CD", None)
            self.SectionExtrude_SymmetricTrapezoid_2__AC = getattr(sec, "AC", None)
            self.SectionExtrude_SymmetricTrapezoid_2__BD = getattr(sec, "BD", None)
            self.SectionExtrude_SymmetricTrapezoid_2__Axis_AC = getattr(sec, "Axis_AC", None)

            # Section
            self.SectionExtrude_SymmetricTrapezoid_2__section_polyline = getattr(sec, "section_polyline", None)
            self.SectionExtrude_SymmetricTrapezoid_2__section_curve = getattr(sec, "section_curve", None)
            self.SectionExtrude_SymmetricTrapezoid_2__section_brep = getattr(sec, "section_brep", None)

            # Solids
            self.SectionExtrude_SymmetricTrapezoid_2__solid_brep = getattr(sec, "solid_brep", None)
            self.SectionExtrude_SymmetricTrapezoid_2__solid_brep_mirror = getattr(sec, "solid_brep_mirror", None)
            self.SectionExtrude_SymmetricTrapezoid_2__solid_list = getattr(sec, "solid_list", None)

            # Planes
            self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime = getattr(sec, "Plane_Oprime", None)
            self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime_X = getattr(sec, "Plane_Oprime_X", None)
            self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime_Y = getattr(sec, "Plane_Oprime_Y", None)
            self.SectionExtrude_SymmetricTrapezoid_2__MirrorPlane_ACZ = getattr(sec, "MirrorPlane_ACZ", None)

            self.SectionExtrude_SymmetricTrapezoid_2__log = to_py_list(getattr(sec, "log", []))

            self.Log.append("[Step9-1] SectionExtrude_SymmetricTrapezoid::2 完成。")
            for l in self.SectionExtrude_SymmetricTrapezoid_2__log:
                self.Log.append("[Step9-1] " + str(l))

            # -----------------------------
            # Step9-2 AlignToolToTimber::7
            # -----------------------------
            # 约束 B：Geo 虽是 2 个对象，但作为整体一次性传入 align（不拆、不循环广播）
            geo_raw = self.SectionExtrude_SymmetricTrapezoid_2__solid_list
            geo_list = flatten_any(geo_raw)
            if geo_list is None:
                geo_list = []
            if not isinstance(geo_list, list):
                geo_list = [geo_list]

            SourcePlane = self.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime

            # 约束 A：TargetPlane 必须与 GeoAligner::4 的 TargetPlane 一致（沿用既有变量）
            TargetPlane = getattr(self, "TreeItem_GA4__TargetPlane", None)

            RotateDeg = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__RotateDeg", None), 0.0)
            FlipX = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__FlipX", None), False)
            FlipY = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__FlipY", None), False)
            FlipZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__FlipZ", None), False)
            MoveX = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__MoveX", None), 0.0)
            MoveY = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__MoveY", None), 0.0)
            MoveZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_7__MoveZ", None), 0.0)

            try:
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    TargetPlane,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
            except Exception as ee:
                # 尝试降级：TargetPlane 取首个可用 Plane（与 Step8-3 一致的容错策略）
                tp_try = TargetPlane
                try:
                    brs = _as_tree_branches(TargetPlane)
                    tp_try = None
                    for br in brs:
                        for it in br:
                            if isinstance(it, rg.Plane):
                                tp_try = it
                                break
                        if tp_try is not None:
                            break
                except Exception:
                    tp_try = TargetPlane

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    tp_try,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
                self.Log.append("[Step9-2][WARN] TargetPlane Tree 兼容降级: {}".format(ee))

            # TransformOut -> GH_Transform（若可用）
            try:
                import Grasshopper.Kernel.Types as ght
                TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            except Exception:
                pass

            self.AlignToolToTimber_7__SourceOut = SourceOut
            self.AlignToolToTimber_7__TargetOut = TargetOut
            self.AlignToolToTimber_7__TransformOut = TransformOut
            self.AlignToolToTimber_7__MovedGeo = MovedGeo

            self.Log.append("[Step9-2] AlignToolToTimber::7 完成。 GeoCount={}".format(len(geo_list)))
            self.Log.append("[Step9] Step9 完成。")

        except Exception as e:
            self.Log.append("[ERROR] Step9 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 10：SectionExtrude_SymmetricTrapezoid::3 + AlignToolToTimber::8
    # ------------------------------------------------------
    def step10_trapezoid3_align8(self):
        """Step10（按提示词）：
        1) SectionExtrude_SymmetricTrapezoid::3（ab_len = AxisLinesIntersectionsSolver.Dist_JK）
        2) AlignToolToTimber::8（TargetPlane = GeoAligner::5.TargetPlane；Geo 作为整体一次 align）
        约束：
            A) TargetPlane 必须沿用 GeoAligner::5.TargetPlane（本步骤不重算）
            B) Geo = solid_list（长度应为2）整体传入 align，不拆分、不广播循环
            C) ab_len 来自 AxisLinesIntersectionsSolver.Dist_JK
        """
        try:
            # -----------------------------
            # Step10-1 SectionExtrude_SymmetricTrapezoid::3
            # -----------------------------
            base_point = rg.Point3d(0.0, 0.0, 0.0)
            ref_plane = make_ref_plane("WorldXY", base_point)

            # 约束 C：ab_len = AxisLinesIntersectionsSolver.Dist_JK
            ab_len = getattr(self, "AxisLinesIntersectionsSolver__Dist_JK", None)

            oe_len = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_3__oe_len", None), 5.0)
            angle_deg = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_3__angle_deg", None), 0.0)
            extrude_h = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_3__extrude_h", None),
                                    10.0)
            oo_prime = _pick_param(None, self.AllDict.get("SectionExtrude_SymmetricTrapezoid_3__oo_prime", None), 1.0)

            sec = SectionExtrude_SymmetricTrapezoid(
                base_point=base_point,
                ref_plane=ref_plane,
                ab_len=ab_len,
                oe_len=oe_len,
                angle_deg=angle_deg,
                extrude_h=extrude_h,
                oo_prime=oo_prime
            ).build()

            # Points
            self.SectionExtrude_SymmetricTrapezoid_3__A = getattr(sec, "A", None)
            self.SectionExtrude_SymmetricTrapezoid_3__B = getattr(sec, "B", None)
            self.SectionExtrude_SymmetricTrapezoid_3__C = getattr(sec, "C", None)
            self.SectionExtrude_SymmetricTrapezoid_3__D = getattr(sec, "D", None)
            self.SectionExtrude_SymmetricTrapezoid_3__O = getattr(sec, "O", None)
            self.SectionExtrude_SymmetricTrapezoid_3__E = getattr(sec, "E", None)
            self.SectionExtrude_SymmetricTrapezoid_3__Oprime = getattr(sec, "Oprime", None)

            # Lines / Axis
            self.SectionExtrude_SymmetricTrapezoid_3__AB = getattr(sec, "AB", None)
            self.SectionExtrude_SymmetricTrapezoid_3__CD = getattr(sec, "CD", None)
            self.SectionExtrude_SymmetricTrapezoid_3__AC = getattr(sec, "AC", None)
            self.SectionExtrude_SymmetricTrapezoid_3__BD = getattr(sec, "BD", None)
            self.SectionExtrude_SymmetricTrapezoid_3__Axis_AC = getattr(sec, "Axis_AC", None)

            # Section
            self.SectionExtrude_SymmetricTrapezoid_3__section_polyline = getattr(sec, "section_polyline", None)
            self.SectionExtrude_SymmetricTrapezoid_3__section_curve = getattr(sec, "section_curve", None)
            self.SectionExtrude_SymmetricTrapezoid_3__section_brep = getattr(sec, "section_brep", None)

            # Solids
            self.SectionExtrude_SymmetricTrapezoid_3__solid_brep = getattr(sec, "solid_brep", None)
            self.SectionExtrude_SymmetricTrapezoid_3__solid_brep_mirror = getattr(sec, "solid_brep_mirror", None)
            self.SectionExtrude_SymmetricTrapezoid_3__solid_list = getattr(sec, "solid_list", None)

            # Planes
            self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime = getattr(sec, "Plane_Oprime", None)
            self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime_X = getattr(sec, "Plane_Oprime_X", None)
            self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime_Y = getattr(sec, "Plane_Oprime_Y", None)
            self.SectionExtrude_SymmetricTrapezoid_3__MirrorPlane_ACZ = getattr(sec, "MirrorPlane_ACZ", None)

            self.SectionExtrude_SymmetricTrapezoid_3__log = to_py_list(getattr(sec, "log", []))

            self.Log.append("[Step10-1] SectionExtrude_SymmetricTrapezoid::3 完成。")
            for l in self.SectionExtrude_SymmetricTrapezoid_3__log:
                self.Log.append("[Step10-1] " + str(l))

            # -----------------------------
            # Step10-2 AlignToolToTimber::8
            # -----------------------------
            # Geo：来自 solid_list（期望 2 个 Brep）；允许展平到 1D list，但必须整体一次性 align
            geo_raw = self.SectionExtrude_SymmetricTrapezoid_3__solid_list
            geo_list = flatten_any(geo_raw)
            if geo_list is None:
                geo_list = []
            if not isinstance(geo_list, list):
                geo_list = [geo_list]

            SourcePlane = self.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime

            # 约束 A：TargetPlane 必须与 GeoAligner::5.TargetPlane 一致（沿用既有变量，不重算）
            TargetPlane = getattr(self, "GeoAligner_5__TargetPlane_TreeItem", None)

            RotateDeg = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__RotateDeg", None), 0.0)
            FlipX = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__FlipX", None), False)
            FlipY = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__FlipY", None), False)
            FlipZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__FlipZ", None), False)
            MoveX = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__MoveX", None), 0.0)
            MoveY = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__MoveY", None), 0.0)
            MoveZ = _pick_param(None, self.AllDict.get("AlignToolToTimber_8__MoveZ", None), 0.0)

            try:
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    TargetPlane,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
            except Exception as ee:
                # 降级：TargetPlane 取首个可用 Plane（保持 Step8/9 的容错策略）
                tp_try = TargetPlane
                try:
                    brs = _as_tree_branches(TargetPlane)
                    tp_try = None
                    for br in brs:
                        for it in br:
                            if isinstance(it, rg.Plane):
                                tp_try = it
                                break
                        if tp_try is not None:
                            break
                except Exception:
                    tp_try = TargetPlane

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_list,
                    SourcePlane,
                    tp_try,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )
                self.Log.append("[Step10-2][WARN] TargetPlane Tree 兼容降级: {}".format(ee))

            # TransformOut -> GH_Transform（若可用）
            try:
                import Grasshopper.Kernel.Types as ght
                TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            except Exception:
                pass

            self.AlignToolToTimber_8__SourceOut = SourceOut
            self.AlignToolToTimber_8__TargetOut = TargetOut
            self.AlignToolToTimber_8__TransformOut = TransformOut
            self.AlignToolToTimber_8__MovedGeo = MovedGeo

            self.Log.append("[Step10-2] AlignToolToTimber::8 完成。 GeoCount={}".format(len(geo_list)))
            self.Log.append("[Step10] Step10 完成。")

        except Exception as e:
            self.Log.append("[ERROR] Step10 出错: {}".format(e))

        return self

    # ------------------------------------------------------

    # ------------------------------------------------------
    def step11_youang_align9(self):
        """Step11 = YouAng（子总成） + AlignToolToTimber::9（对位到 TimberBlock_SkewAxis_M 目标平面）"""
        logs = []

        # -------------------------
        # 1) YouAng 子组件（允许其内部读库；需避免与本 Solver 的 All/AllDict 命名冲突）
        # -------------------------
        try:
            from yingzao.ancientArchi import YouAngSolver
            YouAng_DBPath = self.DBPath
            YouAng_base_point = _coerce_point3d(rg.Point3d(0, 0, 0), rg.Point3d(0, 0, 0))
            YouAng_Refresh = self.Refresh

            youang_solver = YouAngSolver(YouAng_DBPath, YouAng_base_point, YouAng_Refresh, self.ghenv)
            youang_solver = youang_solver.run()

            # --- YouAng 主输出 ---
            self.YouAng__CutTimbers = getattr(youang_solver, "CutTimbers", None)
            self.YouAng__FailTimbers = getattr(youang_solver, "FailTimbers", None)
            self.YouAng__Log = getattr(youang_solver, "Log", None)

            # --- YouAng 开发输出（本步骤至少保留这些） ---
            self.YouAng__Ang_PtsValues = getattr(youang_solver, "Ang_PtsValues", None)
            self.YouAng__Ang_PlanesAValues = getattr(youang_solver, "Ang_PlanesAValues", None)
            self.YouAng__Ang_PlanesBValues = getattr(youang_solver, "Ang_PlanesBValues", None)
            self.YouAng__Ang_OBLoftBrep = getattr(youang_solver, "OBLoftBrep", None) or getattr(youang_solver,
                                                                                                "Ang_OBLoftBrep", None)

            if self.YouAng__Log:
                logs.append("[Step11-YouAng] " + str(self.YouAng__Log))
        except Exception as e:
            logs.append("[Step11-YouAng][ERROR] {}".format(e))
            # 保持 None 输出，继续后续（TargetPlane/Align 也会自然失败并记录）
            self.YouAng__CutTimbers = None
            self.YouAng__FailTimbers = None
            self.YouAng__Log = None
            self.YouAng__Ang_PtsValues = None
            self.YouAng__Ang_PlanesAValues = None
            self.YouAng__Ang_PlanesBValues = None
            self.YouAng__Ang_OBLoftBrep = None

        # -------------------------
        # 2) TargetPlane 串联：List Item（Origin） + Tree Item（BasePlane） + Plane Origin
        # -------------------------
        try:
            # =====================================================
            # 2.1 List Item（取 Origin 点）
            #   List  : TimberBlock_SkewAxis_M.Skew_Point_C
            #   Index : AllDict['AlignToolToTimber_9__TargetPlane_Origin']
            #   Wrap  : 默认 True；若库中提供 AlignToolToTimber_9__TargetPlane_base_wrap 则用之
            # 输出：TargetOriginPoint（用于 Plane Origin 的 Origin）
            # =====================================================
            origin_list = getattr(self, "TimberBlock_SkewAxis_M__Skew_Point_C", None)
            if origin_list is None:
                tb_obj = getattr(self, "TimberBlock_SkewAxis_M__Obj", None)
                origin_list = getattr(tb_obj, "Skew_Point_C", None) if tb_obj is not None else None

            origin_idx = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "TargetPlane_Origin", 0)
            wrap_tp = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "TargetPlane_base_wrap", None),
                True
            )

            def _is_int_path_seq(v):
                return isinstance(v, (list, tuple)) and len(v) > 0 and all(
                    isinstance(x, int) if 'long' in globals() else isinstance(x, int) for x in v)

            def _list_item_tree(list_in, index_in, wrap=True):
                """GH List Item 语义（支持 Tree/嵌套 list/普通 list）：对每个分支取 index 项。"""
                branches = _as_tree_branches(list_in)
                if not branches:
                    return None

                # index 广播到分支数
                if isinstance(index_in, (list, tuple)):
                    idx_seq = list(index_in)
                else:
                    idx_seq = [index_in]
                idx_seq = _broadcast_param(idx_seq, len(branches), "AlignToolToTimber_9__TargetPlane_Origin")

                out = []
                for bi, br in enumerate(branches):
                    br = list(br) if br is not None else []
                    out.append(_safe_index(br, idx_seq[bi], wrap=wrap) if br else None)

                return out[0] if len(out) == 1 else out

            target_origin_raw = _list_item_tree(origin_list, origin_idx, wrap=bool(wrap_tp))

            # 强制转 Point3d（保持 GH 输出稳定）
            if isinstance(target_origin_raw, list):
                self.AlignToolToTimber_9__TargetOriginPoint = [_coerce_point3d(p, None) for p in target_origin_raw]
            else:
                self.AlignToolToTimber_9__TargetOriginPoint = _coerce_point3d(target_origin_raw, None)

            # =====================================================
            # 2.2 Tree Item（取 Base Plane）
            #   Tree  : TimberBlock_SkewAxis_M.Skew_Planes（Tree）
            #   Path  : AllDict['AlignToolToTimber_9__TargetPlane_base_path']
            #   Index : AllDict['AlignToolToTimber_9__TargetPlane_base_index']
            #   Wrap  : 同上 wrap_tp
            # 输出：TargetBasePlane
            # =====================================================
            tree_planes = getattr(self, "TimberBlock_SkewAxis_M__Skew_Planes", None)
            if tree_planes is None:
                tb_obj = getattr(self, "TimberBlock_SkewAxis_M__Obj", None)
                tree_planes = getattr(tb_obj, "Skew_Planes", None) if tb_obj is not None else None
            if tree_planes is None:
                tree_planes = getattr(self, "Skew_Planes", None)

            tp_path = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "TargetPlane_base_path", None)
            tp_index = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "TargetPlane_base_index", 0)

            def _parse_gh_path(path_in):
                """解析 GH_Path / '{0;1}' / '0;1' / [0,1] / 0 → tuple[int]."""
                if path_in is None:
                    return None

                # GH_Path：尝试从 Indexes 取
                try:
                    if path_in.__class__.__name__ == "GH_Path":
                        # GH_Path.ToString() -> "{0;1}"
                        s0 = str(path_in).strip()
                        path_in = s0
                except Exception:
                    pass

                # list/tuple of ints
                if isinstance(path_in, (list, tuple)):
                    try:
                        return tuple(int(x) for x in path_in)
                    except Exception:
                        return None

                # int
                if isinstance(path_in, int):
                    return (int(path_in),)

                # str
                try:
                    s = str(path_in).strip()
                except Exception:
                    return None
                if not s:
                    return None
                if s.startswith("{") and s.endswith("}"):
                    s = s[1:-1]
                s = s.replace(",", ";").replace(" ", ";")
                parts = [p for p in s.split(";") if p != ""]
                if not parts:
                    return None
                try:
                    return tuple(int(p) for p in parts)
                except Exception:
                    return None

            def _tree_item(tree, path_in, index_in, wrap=True):
                """GH Tree Item：按 Path + Index 从 DataTree 中取元素（支持 wrap）。"""
                if tree is None:
                    return None

                # 嵌套列表：当作 Branches；path_in 的最后一位作为分支索引（与项目既有降级策略一致）
                if isinstance(tree, (list, tuple)) and tree and isinstance(tree[0], (list, tuple)):
                    branches = [list(b) for b in tree]
                    bi = 0
                    p = _parse_gh_path(path_in)
                    if p and len(p) >= 1:
                        try:
                            bi = int(p[-1])
                        except Exception:
                            bi = 0
                    br = branches[bi % len(branches)] if branches else []
                    return _safe_index(br, index_in, wrap=wrap) if br else None

                # DataTree：遍历分支匹配 Path
                if hasattr(tree, "BranchCount") and hasattr(tree, "Branch"):
                    p = _parse_gh_path(path_in)
                    try:
                        ii = int(index_in) if index_in is not None else 0
                    except Exception:
                        ii = 0

                    # 无 path：默认 0 分支
                    if p is None:
                        try:
                            br0 = tree.Branch(0)
                            br0 = list(br0) if br0 is not None else []
                            return _safe_index(br0, ii, wrap=wrap) if br0 else None
                        except Exception:
                            return None

                    try:
                        bc = int(tree.BranchCount)
                    except Exception:
                        bc = 0

                    for bi in range(bc):
                        try:
                            ghp = tree.Path(bi) if hasattr(tree, "Path") else None
                            pp = _parse_gh_path(ghp) if ghp is not None else None
                            if pp == p:
                                br = tree.Branch(bi)
                                br = list(br) if br is not None else []
                                return _safe_index(br, ii, wrap=wrap) if br else None
                        except Exception:
                            continue
                    return None

                # 一维 list：当作单支
                if isinstance(tree, (list, tuple)):
                    return _safe_index(tree, index_in, wrap=wrap)

                return None

            # 允许 path/index 为“列表”（多对请求）：广播对齐
            def _ensure_path_list(p):
                # [0,1] 视为单个 path；[[0,1],[0,2]] 视为多个 path
                if p is None:
                    return [None]
                if isinstance(p, (list, tuple)) and len(p) > 0 and all(isinstance(x, int) for x in p):
                    return [p]
                if isinstance(p, (list, tuple)):
                    return list(p)
                return [p]

            def _ensure_index_list(i):
                if isinstance(i, (list, tuple)):
                    return list(i)
                return [i]

            path_list = _ensure_path_list(tp_path)
            idx_list = _ensure_index_list(tp_index)
            n2 = max(len(path_list), len(idx_list), 1)
            path_list = _broadcast_param(path_list, n2, "AlignToolToTimber_9__TargetPlane_base_path")
            idx_list = _broadcast_param(idx_list, n2, "AlignToolToTimber_9__TargetPlane_base_index")

            base_planes_raw = []
            for k in range(n2):
                base_planes_raw.append(_tree_item(tree_planes, path_list[k], idx_list[k], wrap=bool(wrap_tp)))

            if n2 == 1:
                self.AlignToolToTimber_9__TargetBasePlane = _coerce_plane(base_planes_raw[0], None)
            else:
                self.AlignToolToTimber_9__TargetBasePlane = [_coerce_plane(p, None) for p in base_planes_raw]

            # =====================================================
            # 2.3 Plane Origin（重定位平面）
            #   Base   : TargetBasePlane
            #   Origin : TargetOriginPoint
            # 输出：TargetPlane（作为 AlignToolToTimber::9 的 TargetPlane）
            # =====================================================
            def _plane_origin(base_plane, origin_pt):
                if base_plane is None or origin_pt is None:
                    return None
                pl = rg.Plane(base_plane)
                try:
                    pl.Origin = origin_pt
                    return pl
                except Exception:
                    return rg.Plane(origin_pt, pl.XAxis, pl.YAxis)

            base_val = self.AlignToolToTimber_9__TargetBasePlane
            org_val = self.AlignToolToTimber_9__TargetOriginPoint

            # 广播对齐：两端若任一为 list，则按最大长度对齐
            if isinstance(base_val, list) or isinstance(org_val, list):
                base_seq = base_val if isinstance(base_val, list) else [base_val]
                org_seq = org_val if isinstance(org_val, list) else [org_val]
                bn = max(len(base_seq), len(org_seq), 1)
                base_seq = _broadcast_param(base_seq, bn, "TargetBasePlane")
                org_seq = _broadcast_param(org_seq, bn, "TargetOriginPoint")
                self.AlignToolToTimber_9__TargetPlane = [_plane_origin(base_seq[i], org_seq[i]) for i in range(bn)]
            else:
                self.AlignToolToTimber_9__TargetPlane = _plane_origin(base_val, org_val)

        except Exception as e:
            logs.append("[Step11-TargetPlane][ERROR] {}".format(e))
            self.AlignToolToTimber_9__TargetOriginPoint = None
            self.AlignToolToTimber_9__TargetBasePlane = None
            self.AlignToolToTimber_9__TargetPlane = None  # -------------------------
        # 3) AlignToolToTimber::9（GeoAligner_xfm.align）
        # -------------------------
        try:
            from yingzao.ancientArchi import GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght

            geo = flatten_any(self.YouAng__CutTimbers)
            # SourcePlane：从 YouAng 的 Ang_PlanesAValues 取索引
            sp_list = getattr(self, "YouAng__Ang_PlanesAValues", None)

            sp_idx = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "SourcePlane", 0)
            sp_wrap = _pick_param(None,
                                  _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "SourcePlane_Wrap", None),
                                  True)

            TargetPlane_Origin_Index = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "SourcePlane", 0)
            self.AlignToolToTimber_9__SourcePlane_Selected = sp_list[TargetPlane_Origin_Index]

            RotateDeg = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "RotateDeg", 0.0)
            FlipX = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "FlipX", False)
            FlipY = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "FlipY", False)
            FlipZ = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "FlipZ", False)
            MoveX = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "MoveX", 0.0)
            MoveY = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "MoveY", 0.0)
            MoveZ = _get_from_alldict(self.AllDict, "AlignToolToTimber_9", "MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                self.AlignToolToTimber_9__SourcePlane_Selected,
                self.AlignToolToTimber_9__TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            self.AlignToolToTimber_9__SourceOut = SourceOut
            self.AlignToolToTimber_9__TargetOut = TargetOut
            self.AlignToolToTimber_9__MovedGeo = MovedGeo
            self.AlignToolToTimber_9__TransformOut = ght.GH_Transform(
                TransformOut) if TransformOut is not None else None
        except Exception as e:
            logs.append("[Step11-AlignToolToTimber::9][ERROR] {}".format(e))
            self.AlignToolToTimber_9__SourceOut = None
            self.AlignToolToTimber_9__TargetOut = None
            self.AlignToolToTimber_9__TransformOut = None
            self.AlignToolToTimber_9__MovedGeo = None

        # -------------------------
        # 4) 汇总日志
        # -------------------------
        if logs:
            self.Log.extend(logs)

    # ------------------------------------------------------
    # Step 12：CutTimbersByTools::1 + Transform + SplitSectionAnalyzer
    # ------------------------------------------------------
    def step12_cut_transform_split_analyze(self):
        """仅实现 Step12（不重复读库、不修改已完成步骤）。"""
        logs = []
        try:
            # -------------------------
            # 0) 组装 Tools（GeoAligner::1~5 + AlignToolToTimber::6~8，共 8 组）
            # -------------------------
            tools_nested_unique_12 = [
                self.GeoAligner_1__MovedGeo,
                self.GeoAligner_2__MovedGeo,
                self.GeoAligner_3__MovedGeo,
                self.GeoAligner_4__MovedGeo,
                self.GeoAligner_5__MovedGeo,
                self.AlignToolToTimber_6__MovedGeo,
                self.AlignToolToTimber_7__MovedGeo,
                self.AlignToolToTimber_8__MovedGeo,
            ]
            tools_flat_unique_12 = flatten_any(tools_nested_unique_12)
            # 过滤 None
            tools_flat_unique_12 = [g for g in tools_flat_unique_12 if g is not None]
            self.Step12__ToolsFlat = tools_flat_unique_12

            # -------------------------
            # 1) CutTimbersByTools::1
            # -------------------------
            keep_inside_12 = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "CutTimbersByTools_1", "KeepInside", None),
                False
            )

            cutter_12 = FT_CutTimbersByTools_GH_SolidDifference(debug=False)
            cuttimbers_12, failtimbers_12, log_12 = cutter_12.cut(
                timbers=self.TimberBrep,
                tools=tools_flat_unique_12,
                keep_inside=bool(keep_inside_12),
                debug=False
            )

            self.CutTimbersByTools_1__CutTimbers = cuttimbers_12
            self.CutTimbersByTools_1__FailTimbers = failtimbers_12
            self.CutTimbersByTools_1__Log = to_py_list(log_12)

            # -------------------------
            # 2) GH Transform：对位 cutter（YouAng.Ang_OBLoftBrep）
            # -------------------------
            cutter_geo_src_12 = self.YouAng__Ang_OBLoftBrep
            xform_in_12 = self.AlignToolToTimber_9__TransformOut

            # AlignToolToTimber_9__TransformOut 可能是 GH_Transform，也可能是 Rhino Transform
            xform_12 = None
            try:
                # GH_Transform.Value -> Rhino.Geometry.Transform
                if xform_in_12 is not None and hasattr(xform_in_12, "Value"):
                    xform_12 = xform_in_12.Value
                else:
                    xform_12 = xform_in_12
            except Exception:
                xform_12 = xform_in_12

            def _dup_and_xform(geo, xf):
                if geo is None:
                    return None
                if xf is None:
                    return geo
                try:
                    # Brep
                    if isinstance(geo, rg.Brep):
                        g2 = geo.DuplicateBrep()
                        g2.Transform(xf)
                        return g2
                    # Surface / GeometryBase
                    if hasattr(geo, "Duplicate"):
                        g2 = geo.Duplicate()
                        try:
                            g2.Transform(xf)
                        except Exception:
                            pass
                        return g2
                    # fallback
                    g2 = geo
                    try:
                        g2.Transform(xf)
                    except Exception:
                        pass
                    return g2
                except Exception:
                    try:
                        g2 = geo.Duplicate()
                        g2.Transform(xf)
                        return g2
                    except Exception:
                        return geo

            cutter_geo_xf_12 = _dup_and_xform(cutter_geo_src_12, xform_12)
            self.Transform_1__Geometry = cutter_geo_xf_12
            self.Step12__CutterGeo = cutter_geo_xf_12

            # -------------------------
            # 3) SplitSectionAnalyzer（移除 sticky；保持默认参数）
            # -------------------------
            refresh_12 = False
            try:
                refresh_12 = bool(self.Refresh)
            except Exception:
                refresh_12 = False

            analyzer_12 = SplitSectionAnalyzer_Runner(
                brep=cuttimbers_12[0],
                cutter=cutter_geo_xf_12,
                cap_tol=None,
                split_tol=None,
                polyline_div_n=64,
                polyline_min_seg=0.0,
                planar_tol_factor=50.0,
                # plane_ref=None
            ).run()

            # 组件脚本里还有 step_plane_x_cutter，这里保持同样行为
            try:
                analyzer_12.step_plane_x_cutter()
            except Exception:
                pass

            self.SplitSectionAnalyzer__SortedVolumes = getattr(analyzer_12, "sorted_volumes", None)
            self.SplitSectionAnalyzer__MaxClosedBrep = getattr(analyzer_12, "max_closed_brep", None)
            self.SplitSectionAnalyzer__SectionFaces = getattr(analyzer_12, "section_faces", None)
            # 注意：SplitSectionAnalyzer 脚本里的 SectionBrep = _an.section_curves/?? 这里按属性名 section_brep 优先
            self.SplitSectionAnalyzer__SectionBrep = getattr(analyzer_12, "section_brep", None)
            if self.SplitSectionAnalyzer__SectionBrep is None:
                self.SplitSectionAnalyzer__SectionBrep = getattr(analyzer_12, "section_curves", None)

            self.SplitSectionAnalyzer__StableEdgeCurves = getattr(analyzer_12, "stable_edge_curves", None)
            self.SplitSectionAnalyzer__StableLineSegments = getattr(analyzer_12, "stable_line_segments", None)
            self.SplitSectionAnalyzer__MaxXMidPoint = getattr(analyzer_12, "maxx_midpoint", None)
            self.SplitSectionAnalyzer__CutterAnglesHV = getattr(analyzer_12, "cutter_angles_hv", None)
            self.SplitSectionAnalyzer__PlaneCutterCurves = getattr(analyzer_12, "plane_cutter_curves", None)
            self.SplitSectionAnalyzer__PlaneCutterMidPoint = getattr(analyzer_12, "plane_cutter_midpoint", None)
            self.SplitSectionAnalyzer__Log = to_py_list(getattr(analyzer_12, "log", []))

            # -------------------------
            # 4) 更新主输出（CutTimbers/FailTimbers/Log）
            # -------------------------
            self.CutTimbers = to_py_list(cuttimbers_12)
            self.FailTimbers = to_py_list(failtimbers_12)

        except Exception as e:
            logs.append("[Step12][ERROR] {}".format(e))

        if logs:
            self.Log.extend(logs)
        return self
        return self

    # 主控入口
    # ------------------------------------------------------
    # ------------------------------------------------------
    # Step 13：blockcutter::4 + AlignToolToTimber::10
    # ------------------------------------------------------
    def step13_blockcutter4_align10(self):
        """Step13 = blockcutter::4 + AlignToolToTimber::10（仅增量实现本步骤）。"""
        logs = []
        try:
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            # -------------------------
            # 1) blockcutter::4（build_timber_block_uniform）
            # -------------------------
            # length_fen 来自 AxisLinesIntersectionsSolver.Dist_JK
            length_fen_13 = getattr(self, "AxisLinesIntersectionsSolver__Dist_JK", None)
            if length_fen_13 is None:
                length_fen_13 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_4", "length_fen", None),
                                            32.0)

            width_fen_13 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_4", "width_fen", None), 32.0)
            height_fen_13 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_4", "height_fen", None),
                                        20.0)

            # GH 风格：若 length/width/height 为多值列表，则按索引对齐并行生成多个 timber
            len_seq = to_py_list(length_fen_13) if isinstance(length_fen_13, (list, tuple)) else [length_fen_13]
            wid_seq = to_py_list(width_fen_13) if isinstance(width_fen_13, (list, tuple)) else [width_fen_13]
            hei_seq = to_py_list(height_fen_13) if isinstance(height_fen_13, (list, tuple)) else [height_fen_13]

            n = max(len(len_seq), len(wid_seq), len(hei_seq), 1)
            len_seq = _broadcast_param(len_seq, n, "blockcutter_4__length_fen")
            wid_seq = _broadcast_param(wid_seq, n, "blockcutter_4__width_fen")
            hei_seq = _broadcast_param(hei_seq, n, "blockcutter_4__height_fen")

            timber_list = []
            faces_list = []
            points_list = []
            edges_list = []
            centerpt_list = []
            centeraxes_list = []
            edgemid_list = []
            faceplanes_list = []
            corner0_list = []
            local_axes_list = []
            axisx_list = []
            axisy_list = []
            axisz_list = []
            facetag_list = []
            edgetag_list = []
            corner0dir_list = []
            log_lines = []

            for i in range(n):
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
                        _log,
                    ) = build_timber_block_uniform(
                        len_seq[i],
                        wid_seq[i],
                        hei_seq[i],
                        bp,
                        # reference_plane：保持 blockcutter::4 组件默认行为（图中未指定则不显式传入）
                    )
                except TypeError:
                    # 兼容库函数可能仍需要 reference_plane 参数的情况：回退传入 None
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
                        _log,
                    ) = build_timber_block_uniform(
                        len_seq[i],
                        wid_seq[i],
                        hei_seq[i],
                        bp,
                        None,
                    )

                timber_list.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                centerpt_list.append(center_pt)
                centeraxes_list.append(center_axes)
                edgemid_list.append(edge_midpts)
                faceplanes_list.append(face_planes)
                corner0_list.append(corner0_planes)
                local_axes_list.append(local_axes_plane)
                axisx_list.append(axis_x)
                axisy_list.append(axis_y)
                axisz_list.append(axis_z)
                facetag_list.append(face_tags)
                edgetag_list.append(edge_tags)
                corner0dir_list.append(corner0_dirs)
                if _log is not None:
                    try:
                        log_lines.extend(list(_log))
                    except Exception:
                        log_lines.append(str(_log))

            self.blockcutter_4__TimberBrep = timber_list[0] if n == 1 else timber_list
            self.blockcutter_4__FaceList = faces_list[0] if n == 1 else faces_list
            self.blockcutter_4__PointList = points_list[0] if n == 1 else points_list
            self.blockcutter_4__EdgeList = edges_list[0] if n == 1 else edges_list
            self.blockcutter_4__CenterPoint = centerpt_list[0] if n == 1 else centerpt_list
            self.blockcutter_4__CenterAxisLines = centeraxes_list[0] if n == 1 else centeraxes_list
            self.blockcutter_4__EdgeMidPoints = edgemid_list[0] if n == 1 else edgemid_list
            self.blockcutter_4__FacePlaneList = faceplanes_list[0] if n == 1 else faceplanes_list
            self.blockcutter_4__Corner0Planes = corner0_list[0] if n == 1 else corner0_list
            self.blockcutter_4__LocalAxesPlane = local_axes_list[0] if n == 1 else local_axes_list
            self.blockcutter_4__AxisX = axisx_list[0] if n == 1 else axisx_list
            self.blockcutter_4__AxisY = axisy_list[0] if n == 1 else axisy_list
            self.blockcutter_4__AxisZ = axisz_list[0] if n == 1 else axisz_list
            self.blockcutter_4__FaceDirTags = facetag_list[0] if n == 1 else facetag_list
            self.blockcutter_4__EdgeDirTags = edgetag_list[0] if n == 1 else edgetag_list
            self.blockcutter_4__Corner0EdgeDirs = corner0dir_list[0] if n == 1 else corner0dir_list
            self.blockcutter_4__Log = log_lines

            # -------------------------
            # 2) Tree_Cleaner：对 SourcePlaneTree 做规范化（不改分支结构）
            #    这里以 blockcutter_4__FacePlaneList 作为上游 plane tree
            # -------------------------
            src_plane_tree_raw = self.blockcutter_4__FacePlaneList

            def _tree_cleaner_keep_structure(tree_in):
                branches = _as_tree_branches(tree_in)
                if not branches:
                    return None
                out = []
                for br in branches:
                    if br is None:
                        out.append([])
                        continue
                    cleaned = []
                    for it in br:
                        if isinstance(it, rg.Plane):
                            cleaned.append(it)
                    out.append(cleaned)
                return out

            tree_cleaned_13 = _tree_cleaner_keep_structure(src_plane_tree_raw)
            self.Step13__ATTT10_SourcePlaneTreeCleaned = tree_cleaned_13

            # -------------------------
            # 3) AlignToolToTimber::10（GeoAligner_xfm.align）
            # -------------------------
            try:
                import Grasshopper.Kernel.Types as ght

                geo_13 = self.blockcutter_4__TimberBrep
                # SourcePlane：从 FacePlaneList 取索引
                sp_idx_13 = _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "SourcePlane", 0)
                sp_wrap_13 = _pick_param(None,
                                         _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "SourcePlane_Wrap",
                                                           None), True)

                # 允许 faceplanes_list 为 [planes] 或 [[planes],[planes]...]
                def _select_plane(face_planes, idx_val, wrap=True):
                    if face_planes is None:
                        return None
                    # face_planes 可能是 branch
                    if isinstance(face_planes, (list, tuple)):
                        return _safe_index(list(face_planes), idx_val, wrap=wrap)
                    return face_planes

                # 逐 timber 选择 SourcePlane
                if isinstance(faceplanes_list if n > 1 else self.blockcutter_4__FacePlaneList, (list, tuple)) and n > 1:
                    sp_selected = []
                    for i in range(n):
                        fp = faceplanes_list[i] if i < len(faceplanes_list) else None
                        try:
                            ii = int(sp_idx_13) if not isinstance(sp_idx_13, (list, tuple)) else int(
                                sp_idx_13[i] if i < len(sp_idx_13) else sp_idx_13[0])
                        except Exception:
                            ii = 0
                        sp_selected.append(_select_plane(fp, ii, wrap=sp_wrap_13))
                else:
                    try:
                        ii = int(sp_idx_13) if not isinstance(sp_idx_13, (list, tuple)) else int(sp_idx_13[0])
                    except Exception:
                        ii = 0
                    sp_selected = _select_plane(self.blockcutter_4__FacePlaneList, ii, wrap=sp_wrap_13)

                self.AlignToolToTimber_10__SourcePlane_Selected = sp_selected

                # TargetPlane：必须与 AlignToolToTimber::9 的 TargetPlane 完全一致
                target_plane_13 = getattr(self, "AlignToolToTimber_9__TargetPlane", None)

                RotateDeg = _pick_param(None,
                                        _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "RotateDeg", None), 0.0)
                FlipX = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "FlipX", None), False)
                FlipY = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "FlipY", None), False)
                FlipZ = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "FlipZ", None), False)
                MoveX = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "MoveX", None), 0.0)
                MoveY = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "MoveY", None), 0.0)
                MoveZ = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_10", "MoveZ", None), 0.0)

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_13,
                    sp_selected,
                    target_plane_13,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )

                self.AlignToolToTimber_10__SourceOut = SourceOut
                self.AlignToolToTimber_10__TargetOut = TargetOut
                self.AlignToolToTimber_10__MovedGeo = MovedGeo
                self.AlignToolToTimber_10__TransformOut = ght.GH_Transform(
                    TransformOut) if TransformOut is not None else None

            except Exception as e:
                logs.append("[Step13-AlignToolToTimber::10][ERROR] {}".format(e))
                self.AlignToolToTimber_10__SourceOut = None
                self.AlignToolToTimber_10__TargetOut = None
                self.AlignToolToTimber_10__TransformOut = None
                self.AlignToolToTimber_10__MovedGeo = None

        except Exception as e:
            logs.append("[Step13][ERROR] {}".format(e))

        if logs:
            self.Log.extend(logs)

        return self

    # ------------------------------------------------------
    # Step 14：CutTimbersByTools::2
    # ------------------------------------------------------
    def step14_cut_timbers_by_tools_2(self):
        """Step14 = CutTimbersByTools::2（仅增量实现本步骤）。"""
        logs = []
        try:
            # -------------------------
            # 0) Timbers / Tools 输入整理
            # -------------------------
            step14_timbers_in = getattr(self, "AlignToolToTimber_9__MovedGeo", None)

            step14_tools_raw_1 = getattr(self, "GeoAligner_5__MovedGeo", None)
            step14_tools_raw_2 = getattr(self, "AlignToolToTimber_8__MovedGeo", None)
            step14_tools_raw_3 = getattr(self, "AlignToolToTimber_10__MovedGeo", None)

            # 三路工具：先 to_py_list，再 flatten_any 彻底展平
            step14_tools_nested = [
                to_py_list(step14_tools_raw_1),
                to_py_list(step14_tools_raw_2),
                to_py_list(step14_tools_raw_3),
            ]
            step14_tools_flat = flatten_any(step14_tools_nested)
            step14_tools_flat = [g for g in step14_tools_flat if g is not None]

            # -------------------------
            # 1) KeepInside
            # -------------------------
            step14_keep_inside = _pick_param(
                None,
                _get_from_alldict(self.AllDict, "CutTimbersByTools_2", "KeepInside", None),
                False
            )

            # -------------------------
            # 2) 执行切割（遵守 Tree 分支循环，不制造笛卡尔积）
            # -------------------------
            cutter_14 = FT_CutTimbersByTools_GH_SolidDifference(debug=False)

            # Timbers 可能为 Tree / 嵌套 list / 单值
            timbers_branches_14 = _as_tree_branches(step14_timbers_in)

            cut_all_14 = []
            fail_all_14 = []
            log_all_14 = []

            # 若 timbers_branches_14 为空，则直接按 None 走原逻辑（与组件一致）
            if not timbers_branches_14:
                ct, ft, lg = cutter_14.cut(
                    timbers=step14_timbers_in,
                    tools=step14_tools_flat,
                    keep_inside=bool(step14_keep_inside),
                    debug=False
                )
                cut_all_14 = to_py_list(ct)
                fail_all_14 = to_py_list(ft)
                log_all_14 = to_py_list(lg)
            else:
                for bi, btimbers in enumerate(timbers_branches_14):
                    try:
                        ct, ft, lg = cutter_14.cut(
                            timbers=btimbers,
                            tools=step14_tools_flat,
                            keep_inside=bool(step14_keep_inside),
                            debug=False
                        )
                        cut_all_14.extend(to_py_list(ct))
                        fail_all_14.extend(to_py_list(ft))
                        log_all_14.extend(to_py_list(lg))
                    except Exception as e:
                        log_all_14.append("[Step14][Branch {}][ERROR] {}".format(bi, e))

            # -------------------------
            # 3) 写入成员变量（developer-friendly）
            # -------------------------
            self.CutTimbersByTools_2__CutTimbers = cut_all_14
            self.CutTimbersByTools_2__FailTimbers = fail_all_14
            self.CutTimbersByTools_2__Log = log_all_14

            # Step14 作为最终切割：更新主输出
            self.CutTimbers = cut_all_14
            self.FailTimbers = fail_all_14

        except Exception as e:
            logs.append("[Step14][ERROR] {}".format(e))
            self.CutTimbersByTools_2__CutTimbers = None
            self.CutTimbersByTools_2__FailTimbers = None
            self.CutTimbersByTools_2__Log = []

        if logs:
            self.Log.extend(logs)

        return self

    def step15_blockcutter5_align11(self):
        """Step15 = blockcutter::5 + AlignToolToTimber::11（仅增量实现本步骤）。"""
        logs = []
        try:
            bp = _coerce_point3d(self.base_point, rg.Point3d(0, 0, 0))

            # -------------------------
            # 1) blockcutter::5（build_timber_block_uniform）
            # -------------------------
            length_fen_15 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_5", "length_fen", None),
                                        32.0)
            width_fen_15 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_5", "width_fen", None), 32.0)
            height_fen_15 = _pick_param(None, _get_from_alldict(self.AllDict, "blockcutter_5", "height_fen", None),
                                        20.0)

            len_seq = to_py_list(length_fen_15) if isinstance(length_fen_15, (list, tuple)) else [length_fen_15]
            wid_seq = to_py_list(width_fen_15) if isinstance(width_fen_15, (list, tuple)) else [width_fen_15]
            hei_seq = to_py_list(height_fen_15) if isinstance(height_fen_15, (list, tuple)) else [height_fen_15]

            n = max(len(len_seq), len(wid_seq), len(hei_seq), 1)
            len_seq = _broadcast_param(len_seq, n, "blockcutter_5__length_fen")
            wid_seq = _broadcast_param(wid_seq, n, "blockcutter_5__width_fen")
            hei_seq = _broadcast_param(hei_seq, n, "blockcutter_5__height_fen")

            timber_list = []
            faces_list = []
            points_list = []
            edges_list = []
            centerpt_list = []
            centeraxes_list = []
            edgemid_list = []
            faceplanes_list = []
            corner0_list = []
            local_axes_list = []
            axisx_list = []
            axisy_list = []
            axisz_list = []
            facetag_list = []
            edgetag_list = []
            corner0dirs_list = []
            log_lines = []

            for i in range(n):
                try:
                    from yingzao.ancientArchi import build_timber_block_uniform

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
                            _log,
                        ) = build_timber_block_uniform(
                            len_seq[i],
                            wid_seq[i],
                            hei_seq[i],
                            bp,
                            # reference_plane：省略以保持默认行为
                        )
                    except TypeError:
                        # 兼容库函数需要 reference_plane 参数的情况：回退传入 None
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
                            _log,
                        ) = build_timber_block_uniform(
                            len_seq[i],
                            wid_seq[i],
                            hei_seq[i],
                            bp,
                            None
                        )

                    timber_list.append(timber_brep)
                    faces_list.append(faces)
                    points_list.append(points)
                    edges_list.append(edges)
                    centerpt_list.append(center_pt)
                    centeraxes_list.append(center_axes)
                    edgemid_list.append(edge_midpts)
                    faceplanes_list.append(face_planes)
                    corner0_list.append(corner0_planes)
                    local_axes_list.append(local_axes_plane)
                    axisx_list.append(axis_x)
                    axisy_list.append(axis_y)
                    axisz_list.append(axis_z)
                    facetag_list.append(face_tags)
                    edgetag_list.append(edge_tags)
                    corner0dirs_list.append(corner0_dirs)
                    if _log:
                        log_lines.extend(["[blockcutter::5 #{:02d}] {}".format(i, s) for s in to_py_list(_log)])
                except Exception as ee:
                    timber_list.append(None)
                    faces_list.append([])
                    points_list.append([])
                    edges_list.append([])
                    centerpt_list.append(None)
                    centeraxes_list.append([])
                    edgemid_list.append([])
                    faceplanes_list.append([])
                    corner0_list.append([])
                    local_axes_list.append(None)
                    axisx_list.append(None)
                    axisy_list.append(None)
                    axisz_list.append(None)
                    facetag_list.append([])
                    edgetag_list.append([])
                    corner0dirs_list.append([])
                    log_lines.append("[blockcutter::5 #{:02d} ERROR] {}".format(i, ee))

            # 单值时与 GH 行为一致：尽量降维
            self.blockcutter_5__TimberBrep = timber_list[0] if n == 1 else timber_list
            self.blockcutter_5__FaceList = faces_list[0] if n == 1 else faces_list
            self.blockcutter_5__PointList = points_list[0] if n == 1 else points_list
            self.blockcutter_5__EdgeList = edges_list[0] if n == 1 else edges_list
            self.blockcutter_5__CenterPoint = centerpt_list[0] if n == 1 else centerpt_list
            self.blockcutter_5__CenterAxisLines = centeraxes_list[0] if n == 1 else centeraxes_list
            self.blockcutter_5__EdgeMidPoints = edgemid_list[0] if n == 1 else edgemid_list
            self.blockcutter_5__FacePlaneList = faceplanes_list[0] if n == 1 else faceplanes_list
            self.blockcutter_5__Corner0Planes = corner0_list[0] if n == 1 else corner0_list
            self.blockcutter_5__LocalAxesPlane = local_axes_list[0] if n == 1 else local_axes_list
            self.blockcutter_5__AxisX = axisx_list[0] if n == 1 else axisx_list
            self.blockcutter_5__AxisY = axisy_list[0] if n == 1 else axisy_list
            self.blockcutter_5__AxisZ = axisz_list[0] if n == 1 else axisz_list
            self.blockcutter_5__FaceDirTags = facetag_list[0] if n == 1 else facetag_list
            self.blockcutter_5__EdgeDirTags = edgetag_list[0] if n == 1 else edgetag_list
            self.blockcutter_5__Corner0EdgeDirs = corner0dirs_list[0] if n == 1 else corner0dirs_list
            self.blockcutter_5__Log = log_lines

            # -------------------------
            # 2) List Item：从 FacePlaneList 取 SourcePlane
            # -------------------------
            sp_idx_raw = _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "SourcePlane", 0)
            sp_wrap = _pick_param(
                None,
                _get_from_alldict_multi(self.AllDict, "AlignToolToTimber_11", ["SourcePlane_wrap", "SourcePlane_Wrap"],
                                        None),
                True
            )

            # Tree_Cleaner：保持结构但清理 None/空值（与 Step13 一致的策略）
            def _tree_cleaner_keep_structure(x):
                if x is None:
                    return None
                if isinstance(x, (list, tuple)):
                    out = []
                    for it in x:
                        if isinstance(it, (list, tuple)):
                            # 分支内递归
                            sub = _tree_cleaner_keep_structure(it)
                            out.append(sub)
                        else:
                            out.append(it)
                    return out
                return x

            sp_idx_cleaned = _tree_cleaner_keep_structure(sp_idx_raw)
            self.Step15__ATTT11_SourcePlaneTreeCleaned = sp_idx_cleaned

            # 逐 timber 选择 SourcePlane（FacePlaneList 可能为 list 或 list[list]）
            def _select_plane(face_planes, idx_val, wrap=True):
                if face_planes is None:
                    return None
                if isinstance(face_planes, (list, tuple)):
                    return _safe_index(list(face_planes), idx_val, wrap=wrap)
                return face_planes

            fp_all = self.blockcutter_5__FacePlaneList
            if n > 1 and isinstance(fp_all, (list, tuple)) and len(fp_all) == n and len(fp_all) > 0 and isinstance(
                    fp_all[0], (list, tuple)):
                # index 广播到 timber 数
                if isinstance(sp_idx_cleaned, (list, tuple)):
                    idx_seq = list(sp_idx_cleaned)
                else:
                    idx_seq = [sp_idx_cleaned]
                idx_seq = _broadcast_param(idx_seq, n, "AlignToolToTimber_11__SourcePlane")

                sp_selected = []
                for i in range(n):
                    sp_selected.append(_select_plane(fp_all[i], idx_seq[i], wrap=sp_wrap))
            else:
                # 单 timber：直接取一个 plane
                if isinstance(sp_idx_cleaned, (list, tuple)):
                    try:
                        ii = int(sp_idx_cleaned[0])
                    except Exception:
                        ii = 0
                else:
                    try:
                        ii = int(sp_idx_cleaned)
                    except Exception:
                        ii = 0
                sp_selected = _select_plane(fp_all, ii, wrap=sp_wrap)

            self.AlignToolToTimber_11__SourcePlane_Selected = sp_selected

            # -------------------------
            # 3) MoveX 计算链（Dist_JK / divistion -> subtraction - tmp_div）
            # -------------------------
            dist_jk = getattr(self, "AxisLinesIntersectionsSolver__Dist_JK", None)
            divistion = _pick_param(None,
                                    _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "MoveX_divistion", None),
                                    1.0)
            subtraction = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "MoveX_subtraction",
                                                              None), 0.0)

            self.AlignToolToTimber_11__MoveX_divistion = divistion
            self.AlignToolToTimber_11__MoveX_subtraction = subtraction

            dist_seq = to_py_list(dist_jk) if isinstance(dist_jk, (list, tuple)) else [dist_jk]
            div_seq = to_py_list(divistion) if isinstance(divistion, (list, tuple)) else [divistion]
            sub_seq = to_py_list(subtraction) if isinstance(subtraction, (list, tuple)) else [subtraction]

            m = max(len(dist_seq), len(div_seq), len(sub_seq), 1)
            dist_seq = _broadcast_param(dist_seq, m, "AxisLinesIntersectionsSolver__Dist_JK")
            div_seq = _broadcast_param(div_seq, m, "AlignToolToTimber_11__MoveX_divistion")
            sub_seq = _broadcast_param(sub_seq, m, "AlignToolToTimber_11__MoveX_subtraction")

            tmp_div_seq = []
            movex_seq = []
            for i in range(m):
                d = dist_seq[i]
                dv = div_seq[i]
                sb = sub_seq[i]
                try:
                    dvv = float(dv) if dv is not None else 1.0
                    if abs(dvv) < 1e-9:
                        dvv = 1e-9
                    dd = float(d) if d is not None else 0.0
                    t = dd / dvv
                except Exception:
                    t = 0.0
                try:
                    mv = (float(sb) if sb is not None else 0.0) - t
                except Exception:
                    mv = 0.0
                tmp_div_seq.append(t)
                movex_seq.append(mv)

            self.AlignToolToTimber_11__MoveX_tmp_div = tmp_div_seq[0] if m == 1 else tmp_div_seq
            self.AlignToolToTimber_11__MoveX_final = movex_seq[0] if m == 1 else movex_seq

            # -------------------------
            # 4) AlignToolToTimber::11（GeoAligner_xfm.align）
            # -------------------------
            try:
                import Grasshopper.Kernel.Types as ght
                from yingzao.ancientArchi import GeoAligner_xfm

                geo_15 = self.blockcutter_5__TimberBrep
                target_plane_15 = getattr(self, "AlignToolToTimber_9__TargetPlane", None)

                RotateDeg = _pick_param(None,
                                        _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "RotateDeg", None), 0.0)
                FlipX = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "FlipX", None), False)
                FlipY = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "FlipY", None), False)
                FlipZ = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "FlipZ", None), False)
                MoveY = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "MoveY", None), 0.0)
                MoveZ = _pick_param(None, _get_from_alldict(self.AllDict, "AlignToolToTimber_11", "MoveZ", None), 0.0)

                # MoveX 使用计算链结果
                MoveX = self.AlignToolToTimber_11__MoveX_final

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_15,
                    sp_selected,
                    target_plane_15,
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )

                self.AlignToolToTimber_11__SourceOut = SourceOut
                self.AlignToolToTimber_11__TargetOut = TargetOut
                self.AlignToolToTimber_11__MovedGeo = MovedGeo
                self.AlignToolToTimber_11__TransformOut = ght.GH_Transform(
                    TransformOut) if TransformOut is not None else None

            except Exception as ee:
                logs.append("[Step15][AlignToolToTimber::11 ERROR] {}".format(ee))
                self.AlignToolToTimber_11__SourceOut = None
                self.AlignToolToTimber_11__TargetOut = None
                self.AlignToolToTimber_11__MovedGeo = None
                self.AlignToolToTimber_11__TransformOut = None

        except Exception as e:
            logs.append("[Step15][ERROR] {}".format(e))

        if logs:
            self.Log.extend(logs)

    def run(self):
        # Step 1：数据库
        self.step1_read_db()

        # 若 All 为空，可以提前返回（保持 LingGongSolver 的策略）
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：木坯
        self.step2_timber()

        # Step 3：ShuaTou + PlaneFromLists::1 + GeoAligner::1
        self.step3_shuatou_plane_geoaligner()

        # Step 4：QiAOTool + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::2
        self.step4_qiao_tool_and_align()

        # Step 5：blockcutter::1 + TreeItem + ListItem + GeoAligner::3
        self.step5_blockcutter1_and_geoaligner3()

        # Step 6：blockcutter::2 + TreeItem + ListItem + GeoAligner::4
        self.step6_blockcutter2_and_geoaligner4()

        # Step 7：blockcutter::3 + ListItem + TreeItem + GeoAligner::5
        self.step7_blockcutter3_geoaligner5()

        # Step 8：AxisLinesIntersectionsSolver + SectionExtrude + AlignToolToTimber::6
        self.step8_axis_section_align()

        # Step 9：SectionExtrude_SymmetricTrapezoid::2 + AlignToolToTimber::7
        self.step9_trapezoid2_align7()

        # Step 10：SectionExtrude_SymmetricTrapezoid::3 + AlignToolToTimber::8
        self.step10_trapezoid3_align8()

        # Step 11：YouAng + AlignToolToTimber::9
        self.step11_youang_align9()

        # Step 12：CutTimbersByTools::1 + Transform + SplitSectionAnalyzer
        self.step12_cut_transform_split_analyze()

        # Step 13：blockcutter::4 + AlignToolToTimber::10
        self.step13_blockcutter4_align10()

        # Step 14：CutTimbersByTools::2
        self.step14_cut_timbers_by_tools_2()

        # Step 15：blockcutter::5 + AlignToolToTimber::11
        self.step15_blockcutter5_align11()

        # 后续步骤待增量实现：AlignTool / GeoAligner / CutTimbersByTools ...
        return self


# ==============================================================
# GH Python 组件输出绑定区（developer-friendly）
# ==============================================================

if __name__ == "__main__":

    solver = YouAngInLineWJiaoShuaTou_4PU_Solver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出（当前仅 Step1-2；CutTimbers/FailTimbers 为空） ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- 开发模式输出：建议你在 GH 输出端自行添加同名端口 ---
    # 1) 常用显式输出（方便你直接拖线查看）
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

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
    Log_TimberBlock = solver.Log_TimberBlock

    TimberBlock_SkewAxis_M__Skew_Planes = solver.TimberBlock_SkewAxis_M__Skew_Planes
    TimberBlock_SkewAxis_M__Skew_Point_C = solver.TimberBlock_SkewAxis_M__Skew_Point_C

    # Step3 outputs
    ShuaTou__CenterSectionCrv = solver.ShuaTou__CenterSectionCrv
    ShuaTou__SideSectionCrv = solver.ShuaTou__SideSectionCrv
    ShuaTou__CenterSectionFace = solver.ShuaTou__CenterSectionFace
    ShuaTou__SideSectionFace = solver.ShuaTou__SideSectionFace
    ShuaTou__OffsetSideFaces = solver.ShuaTou__OffsetSideFaces
    ShuaTou__OffsetSideCrvs = solver.ShuaTou__OffsetSideCrvs
    ShuaTou__SideLoftFace = solver.ShuaTou__SideLoftFace
    ShuaTou__ToolBrep = solver.ShuaTou__ToolBrep
    ShuaTou__DebugPoints = solver.ShuaTou__DebugPoints
    ShuaTou__DebugLines = solver.ShuaTou__DebugLines
    ShuaTou__RefPlanes = solver.ShuaTou__RefPlanes
    ShuaTou__Log = solver.ShuaTou__Log

    PlaneFromLists_1__BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log = solver.PlaneFromLists_1__Log

    GeoAligner_1__MovedGeo = solver.GeoAligner_1__MovedGeo
    GeoAligner_1__SourceOut = solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut = solver.GeoAligner_1__TargetOut
    GeoAligner_1__TransformOut = solver.GeoAligner_1__TransformOut

    # 2) 动态暴露：把 solver 当前所有成员变量写到脚本命名空间中
    #    你只要在 GH 输出端新增同名端口，就能直接读到该变量（避免反复改代码）。
    for _k, _v in solver.__dict__.items():
        try:
            globals()[_k] = _v
        except Exception:
            pass

    # Step4 outputs
    QiAOTool__CutTimbers = solver.QiAOTool__CutTimbers
    QiAOTool__FailTimbers = solver.QiAOTool__FailTimbers
    QiAOTool__Log = solver.QiAOTool__Log
    QiAOTool__EdgeMidPoints = solver.QiAOTool__EdgeMidPoints
    QiAOTool__Corner0Planes = solver.QiAOTool__Corner0Planes

    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    PlaneFromLists_3__BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__Log = solver.PlaneFromLists_3__Log

    GeoAligner_2__MovedGeo = solver.GeoAligner_2__MovedGeo
    GeoAligner_2__SourceOut = solver.GeoAligner_2__SourceOut
    GeoAligner_2__TargetOut = solver.GeoAligner_2__TargetOut
    GeoAligner_2__TransformOut = solver.GeoAligner_2__TransformOut

    # Step5 outputs
    blockcutter_1__TimberBrep = solver.blockcutter_1__TimberBrep
    blockcutter_1__FacePlaneList = solver.blockcutter_1__FacePlaneList
    blockcutter_1__EdgeMidPoints = solver.blockcutter_1__EdgeMidPoints
    blockcutter_1__Corner0Planes = solver.blockcutter_1__Corner0Planes
    blockcutter_1__Log = solver.blockcutter_1__Log

    ListItem_GA3__SourcePlane = solver.ListItem_GA3__SourcePlane
    TreeItem_GA3__TargetPlane = solver.TreeItem_GA3__TargetPlane

    GeoAligner_3__MovedGeo = solver.GeoAligner_3__MovedGeo
    GeoAligner_3__SourceOut = solver.GeoAligner_3__SourceOut
    GeoAligner_3__TargetOut = solver.GeoAligner_3__TargetOut
    GeoAligner_3__TransformOut = solver.GeoAligner_3__TransformOut

    # Step6 outputs
    blockcutter_2__TimberBrep = solver.blockcutter_2__TimberBrep
    blockcutter_2__FacePlaneList = solver.blockcutter_2__FacePlaneList
    blockcutter_2__EdgeMidPoints = solver.blockcutter_2__EdgeMidPoints
    blockcutter_2__Corner0Planes = solver.blockcutter_2__Corner0Planes
    blockcutter_2__Log = solver.blockcutter_2__Log

    ListItem_GA4__SourcePlane = solver.ListItem_GA4__SourcePlane
    TreeItem_GA4__TargetPlane = solver.TreeItem_GA4__TargetPlane

    GeoAligner_4__MovedGeoTree = solver.GeoAligner_4__MovedGeoTree
    GeoAligner_4__MovedGeo = solver.GeoAligner_4__MovedGeo
    GeoAligner_4__SourceOut = solver.GeoAligner_4__SourceOut
    GeoAligner_4__TargetOut = solver.GeoAligner_4__TargetOut
    GeoAligner_4__TransformOut = solver.GeoAligner_4__TransformOut

    # Step7 outputs
    blockcutter_3__TimberBrep = solver.blockcutter_3__TimberBrep
    blockcutter_3__FacePlaneList = solver.blockcutter_3__FacePlaneList
    blockcutter_3__EdgeMidPoints = solver.blockcutter_3__EdgeMidPoints
    blockcutter_3__Corner0Planes = solver.blockcutter_3__Corner0Planes
    blockcutter_3__Log = solver.blockcutter_3__Log

    ListItem_GA5__SourcePlane = solver.GeoAligner_5__SourcePlane_ListItem
    TreeItem_GA5__TargetPlane = solver.GeoAligner_5__TargetPlane_TreeItem

    GeoAligner_5__MovedGeoTree = solver.GeoAligner_5__MovedGeoTree
    GeoAligner_5__MovedGeo = solver.GeoAligner_5__MovedGeo
    GeoAligner_5__SourceOut = solver.GeoAligner_5__SourceOut
    GeoAligner_5__TargetOut = solver.GeoAligner_5__TargetOut
    GeoAligner_5__TransformOut = solver.GeoAligner_5__TransformOut

    Step7__Log = solver.Step7__Log

    # Step8 outputs
    AxisLinesIntersectionsSolver__Axis_AO = solver.AxisLinesIntersectionsSolver__Axis_AO
    AxisLinesIntersectionsSolver__Axis_AC = solver.AxisLinesIntersectionsSolver__Axis_AC
    AxisLinesIntersectionsSolver__Axis_AD = solver.AxisLinesIntersectionsSolver__Axis_AD
    AxisLinesIntersectionsSolver__O_out = solver.AxisLinesIntersectionsSolver__O_out
    AxisLinesIntersectionsSolver__A = solver.AxisLinesIntersectionsSolver__A
    AxisLinesIntersectionsSolver__B = solver.AxisLinesIntersectionsSolver__B
    AxisLinesIntersectionsSolver__J = solver.AxisLinesIntersectionsSolver__J
    AxisLinesIntersectionsSolver__K = solver.AxisLinesIntersectionsSolver__K
    AxisLinesIntersectionsSolver__Dist_BJ = solver.AxisLinesIntersectionsSolver__Dist_BJ
    AxisLinesIntersectionsSolver__Dist_JK = solver.AxisLinesIntersectionsSolver__Dist_JK
    AxisLinesIntersectionsSolver__Log = solver.AxisLinesIntersectionsSolver__Log

    SectionExtrude_SymmetricTrapezoid_1__solid_list = solver.SectionExtrude_SymmetricTrapezoid_1__solid_list
    SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime = solver.SectionExtrude_SymmetricTrapezoid_1__Plane_Oprime
    SectionExtrude_SymmetricTrapezoid_1__log = solver.SectionExtrude_SymmetricTrapezoid_1__log

    AlignToolToTimber_6__MovedGeo = solver.AlignToolToTimber_6__MovedGeo
    AlignToolToTimber_6__TransformOut = solver.AlignToolToTimber_6__TransformOut

    # Step9 outputs
    SectionExtrude_SymmetricTrapezoid_2__solid_list = solver.SectionExtrude_SymmetricTrapezoid_2__solid_list
    SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime = solver.SectionExtrude_SymmetricTrapezoid_2__Plane_Oprime
    SectionExtrude_SymmetricTrapezoid_2__log = solver.SectionExtrude_SymmetricTrapezoid_2__log

    AlignToolToTimber_7__MovedGeo = solver.AlignToolToTimber_7__MovedGeo
    AlignToolToTimber_7__TransformOut = solver.AlignToolToTimber_7__TransformOut

    # Step10 outputs
    SectionExtrude_SymmetricTrapezoid_3__solid_list = solver.SectionExtrude_SymmetricTrapezoid_3__solid_list
    SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime = solver.SectionExtrude_SymmetricTrapezoid_3__Plane_Oprime
    SectionExtrude_SymmetricTrapezoid_3__log = solver.SectionExtrude_SymmetricTrapezoid_3__log

    AlignToolToTimber_8__MovedGeo = solver.AlignToolToTimber_8__MovedGeo
    AlignToolToTimber_8__TransformOut = solver.AlignToolToTimber_8__TransformOut

    # Step11 outputs
    YouAng__CutTimbers = solver.YouAng__CutTimbers
    YouAng__FailTimbers = solver.YouAng__FailTimbers
    YouAng__Log = solver.YouAng__Log
    YouAng__Ang_PtsValues = solver.YouAng__Ang_PtsValues
    YouAng__Ang_PlanesAValues = solver.YouAng__Ang_PlanesAValues
    YouAng__Ang_PlanesBValues = solver.YouAng__Ang_PlanesBValues
    YouAng__Ang_OBLoftBrep = solver.YouAng__Ang_OBLoftBrep

    AlignToolToTimber_9__MovedGeo = solver.AlignToolToTimber_9__MovedGeo
    AlignToolToTimber_9__TransformOut = solver.AlignToolToTimber_9__TransformOut

    # Step12 outputs
    Step12__ToolsFlat = solver.Step12__ToolsFlat
    Step12__CutterGeo = solver.Step12__CutterGeo

    CutTimbersByTools_1__CutTimbers = solver.CutTimbersByTools_1__CutTimbers
    CutTimbersByTools_1__FailTimbers = solver.CutTimbersByTools_1__FailTimbers
    CutTimbersByTools_1__Log = solver.CutTimbersByTools_1__Log

    Transform_1__Geometry = solver.Transform_1__Geometry

    SplitSectionAnalyzer__SortedVolumes = solver.SplitSectionAnalyzer__SortedVolumes
    SplitSectionAnalyzer__MaxClosedBrep = solver.SplitSectionAnalyzer__MaxClosedBrep
    SplitSectionAnalyzer__SectionFaces = solver.SplitSectionAnalyzer__SectionFaces
    SplitSectionAnalyzer__SectionBrep = solver.SplitSectionAnalyzer__SectionBrep
    SplitSectionAnalyzer__StableEdgeCurves = solver.SplitSectionAnalyzer__StableEdgeCurves
    SplitSectionAnalyzer__StableLineSegments = solver.SplitSectionAnalyzer__StableLineSegments
    SplitSectionAnalyzer__MaxXMidPoint = solver.SplitSectionAnalyzer__MaxXMidPoint
    SplitSectionAnalyzer__CutterAnglesHV = solver.SplitSectionAnalyzer__CutterAnglesHV
    SplitSectionAnalyzer__PlaneCutterCurves = solver.SplitSectionAnalyzer__PlaneCutterCurves
    SplitSectionAnalyzer__PlaneCutterMidPoint = solver.SplitSectionAnalyzer__PlaneCutterMidPoint
    SplitSectionAnalyzer__Log = solver.SplitSectionAnalyzer__Log

    # Step13 outputs
    blockcutter_4__TimberBrep = solver.blockcutter_4__TimberBrep
    blockcutter_4__FaceList = solver.blockcutter_4__FaceList
    blockcutter_4__PointList = solver.blockcutter_4__PointList
    blockcutter_4__EdgeList = solver.blockcutter_4__EdgeList
    blockcutter_4__CenterPoint = solver.blockcutter_4__CenterPoint
    blockcutter_4__CenterAxisLines = solver.blockcutter_4__CenterAxisLines
    blockcutter_4__EdgeMidPoints = solver.blockcutter_4__EdgeMidPoints
    blockcutter_4__FacePlaneList = solver.blockcutter_4__FacePlaneList
    blockcutter_4__Corner0Planes = solver.blockcutter_4__Corner0Planes
    blockcutter_4__LocalAxesPlane = solver.blockcutter_4__LocalAxesPlane
    blockcutter_4__AxisX = solver.blockcutter_4__AxisX
    blockcutter_4__AxisY = solver.blockcutter_4__AxisY
    blockcutter_4__AxisZ = solver.blockcutter_4__AxisZ
    blockcutter_4__FaceDirTags = solver.blockcutter_4__FaceDirTags
    blockcutter_4__EdgeDirTags = solver.blockcutter_4__EdgeDirTags
    blockcutter_4__Corner0EdgeDirs = solver.blockcutter_4__Corner0EdgeDirs
    blockcutter_4__Log = solver.blockcutter_4__Log

    Step13__ATTT10_SourcePlaneTreeCleaned = solver.Step13__ATTT10_SourcePlaneTreeCleaned
    AlignToolToTimber_10__SourcePlane_Selected = solver.AlignToolToTimber_10__SourcePlane_Selected
    AlignToolToTimber_10__SourceOut = solver.AlignToolToTimber_10__SourceOut
    AlignToolToTimber_10__TargetOut = solver.AlignToolToTimber_10__TargetOut
    AlignToolToTimber_10__MovedGeo = solver.AlignToolToTimber_10__MovedGeo
    AlignToolToTimber_10__TransformOut = solver.AlignToolToTimber_10__TransformOut

    # Step14 outputs
    CutTimbersByTools_2__CutTimbers = solver.CutTimbersByTools_2__CutTimbers
    CutTimbersByTools_2__FailTimbers = solver.CutTimbersByTools_2__FailTimbers
    CutTimbersByTools_2__Log = solver.CutTimbersByTools_2__Log

    # Step15 outputs
    blockcutter_5__TimberBrep = solver.blockcutter_5__TimberBrep
    blockcutter_5__FaceList = solver.blockcutter_5__FaceList
    blockcutter_5__PointList = solver.blockcutter_5__PointList
    blockcutter_5__EdgeList = solver.blockcutter_5__EdgeList
    blockcutter_5__CenterPoint = solver.blockcutter_5__CenterPoint
    blockcutter_5__CenterAxisLines = solver.blockcutter_5__CenterAxisLines
    blockcutter_5__EdgeMidPoints = solver.blockcutter_5__EdgeMidPoints
    blockcutter_5__FacePlaneList = solver.blockcutter_5__FacePlaneList
    blockcutter_5__Corner0Planes = solver.blockcutter_5__Corner0Planes
    blockcutter_5__LocalAxesPlane = solver.blockcutter_5__LocalAxesPlane
    blockcutter_5__AxisX = solver.blockcutter_5__AxisX
    blockcutter_5__AxisY = solver.blockcutter_5__AxisY
    blockcutter_5__AxisZ = solver.blockcutter_5__AxisZ
    blockcutter_5__FaceDirTags = solver.blockcutter_5__FaceDirTags
    blockcutter_5__EdgeDirTags = solver.blockcutter_5__EdgeDirTags
    blockcutter_5__Corner0EdgeDirs = solver.blockcutter_5__Corner0EdgeDirs
    blockcutter_5__Log = solver.blockcutter_5__Log

    Step15__ATTT11_SourcePlaneTreeCleaned = solver.Step15__ATTT11_SourcePlaneTreeCleaned
    AlignToolToTimber_11__SourcePlane_Selected = solver.AlignToolToTimber_11__SourcePlane_Selected

    AlignToolToTimber_11__MoveX_divistion = solver.AlignToolToTimber_11__MoveX_divistion
    AlignToolToTimber_11__MoveX_subtraction = solver.AlignToolToTimber_11__MoveX_subtraction
    AlignToolToTimber_11__MoveX_tmp_div = solver.AlignToolToTimber_11__MoveX_tmp_div
    AlignToolToTimber_11__MoveX_final = solver.AlignToolToTimber_11__MoveX_final

    AlignToolToTimber_11__SourceOut = solver.AlignToolToTimber_11__SourceOut
    AlignToolToTimber_11__TargetOut = solver.AlignToolToTimber_11__TargetOut
    AlignToolToTimber_11__MovedGeo = solver.AlignToolToTimber_11__MovedGeo
    AlignToolToTimber_11__TransformOut = solver.AlignToolToTimber_11__TransformOut

    # --- 安全获取 AlignToolToTimber_11__MovedGeo 的第一个 ---
    moved_geo_11 = None

    if AlignToolToTimber_11__MovedGeo is not None:
        if isinstance(AlignToolToTimber_11__MovedGeo, (list, tuple)):
            if len(AlignToolToTimber_11__MovedGeo) > 0:
                moved_geo_11 = AlignToolToTimber_11__MovedGeo[0]
        else:
            # GH 广播下可能直接是单个 Brep
            moved_geo_11 = AlignToolToTimber_11__MovedGeo

    # --- 安全加入 CutTimbers ---
    if SplitSectionAnalyzer__MaxClosedBrep is not None:
        CutTimbers.append(SplitSectionAnalyzer__MaxClosedBrep)

    if moved_geo_11 is not None:
        CutTimbers.append(moved_geo_11)


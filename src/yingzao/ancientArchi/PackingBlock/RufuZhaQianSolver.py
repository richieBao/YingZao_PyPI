# -*- coding: utf-8 -*-
"""
RufuZhaQianSolver · Step 1 + Step 2 + Step 3 + Step 4（数据库 + 原始木料 + 端头粗削 + 欹䫜刀）

功能概述：
1) Step 1：读取数据库（DBJsonReader）
   - Table    = CommonComponents
   - KeyField = type_code
   - KeyValue = RufuZhaQian
   - Field    = params_json
   - ExportAll= True
   输出：
   - Value / All / AllDict / DBLog
   说明：
   - 当前模块直接使用 All 和 AllDict（不加 0）

2) Step 2：原始木料构建（FT_timber_block_uniform）
   - length_fen  = AllDict["FT_timber_block_uniform__length_fen"] (default 32)
   - width_fen   = AllDict["FT_timber_block_uniform__width_fen"]  (default 32)
   - height_fen  = AllDict["FT_timber_block_uniform__height_fen"] (default 20)
   - base_point  = 组件输入端 base_point（若无 → 原点 (0,0,0)）
   - reference_plane：
       默认 GH XZ Plane（X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)）
       也可由 AllDict["FT_timber_block_uniform__reference_plane"] 指定：WorldXY / WorldXZ / WorldYZ

3) Step 3：端头粗削（FT_BlockCutter::1 + PF1 + PF2 + Align1）
   3.1 FT_BlockCutter::1（用 build_timber_block_uniform 构建“刀具木块”）
       - length_fen = FT_BlockCutter_1__length_fen
       - width_fen  = FT_BlockCutter_1__width_fen
       - height_fen = FT_BlockCutter_1__height_fen
       - base_point = 默认原点
       - reference_plane = 默认 GH XZ Plane（也可由 FT_BlockCutter_1__reference_plane 指定）
       ✅ 支持 length/width/height 为 list：逐项构建多个木块（修复“float(list) -> 默认值”的问题）
   3.2 PlaneFromLists::1（PF1）
       - OriginPoints = Step2 的 EdgeMidPoints
       - BasePlanes   = Step2 的 Corner0Planes
       - IndexOrigin  = PlaneFromLists_1__IndexOrigin（可列表）
       - IndexPlane   = PlaneFromLists_1__IndexPlane（可列表）
       - Wrap         = PlaneFromLists_1__Wrap（默认 True；若 DB 无此键则 True）
       输出：
       - PF1_ResultPlane 为 list[Plane]
   3.3 PlaneFromLists::2（PF2）
       - OriginPoints = BlockCutter1_EdgeMidPoints（可能为 tree/嵌套列表）
       - BasePlanes   = BlockCutter1_Corner0Planes（可能为 tree/嵌套列表）
       - IndexOrigin  = PlaneFromLists_2__IndexOrigin（列表）
       - IndexPlane   = PlaneFromLists_2__IndexPlane（列表）
       - Wrap         = PlaneFromLists_2__Wrap（默认 True）
       规则：
       - 若 OriginPoints/BasePlanes 为 tree(嵌套列表)，则 IndexOrigin/IndexPlane 的列表值
         依次作用到每个分支：第 i 个分支用 idx_list[i]（不足则用最后一个补齐）
       输出：
       - PF2_ResultPlane 为 list[Plane]
   3.4 FT_AlignToolToTimber::1（Align1）
       - ToolGeo        = BlockCutter1_TimberBrep
       - ToolBasePlane  = PF2_ResultPlane
       - BlockFacePlane = PF1_ResultPlane
       - BlockRotDeg    = FT_AlignToolToTimber_1__BlockRotDeg
       - FlipY          = FT_AlignToolToTimber_1__FlipY
       注意：
       - 输入端值为列表时，一一对应；长度不一致时，按 GH 广播规则补齐（最后值补齐）。
       - 其它参数（FlipX/FlipZ/ToolRotDeg/MoveU/MoveV/DepthOffset 等）使用默认标量并广播。

4) Step 4：乳栿劄牽_欹䫜刀（RufuZhaQian_QiAoSolver + PF3 + PF4 + GeoAligner1）
   4.1 子 Solver：RufuZhaQian_QiAoSolver（数据库驱动，内部类）
       - DB: CommonComponents / type_code=RufuZhaQian_QiAoTool / params_json / ExportAll=True
       - DBPath = 组件输入端 DBPath
       - base_point = 默认原点
       - length_fen = AllDict["RufuZhaQian_QiAoSolver__length_fen"]（若无则子 Solver 默认/DB/库默认）
       输出：
       - QiAo_CutTimbers / QiAo_FailTimbers / QiAo_Log + 其内部 TimberBrep/EdgeMidPoints/Corner0Planes 等
   4.2 PlaneFromLists::3（PF3：主木坯）
       - OriginPoints = Step2 的 EdgeMidPoints
       - BasePlanes   = Step2 的 Corner0Planes
       - IndexOrigin  = PlaneFromLists_3__IndexOrigin（可列表）
       - IndexPlane   = PlaneFromLists_3__IndexPlane（可列表）
   4.3 PlaneFromLists::4（PF4：QiAo 子 Solver 木坯）
       - OriginPoints = QiAo 的 EdgeMidPoints
       - BasePlanes   = QiAo 的 Corner0Planes
       - IndexOrigin  = PlaneFromLists_4__IndexOrigin（可列表）
       - IndexPlane   = PlaneFromLists_4__IndexPlane（可列表）
   4.4 GeoAligner::1（对齐 QiAo 的 CutTimbers）
       - Geo        = QiAo_CutTimbers
       - SourcePlane= PF4_ResultPlane
       - TargetPlane= PF3_ResultPlane
       - FlipX      = GeoAligner_1__FlipX
       - MoveY      = GeoAligner_1__MoveY
       - 其他 RotateDeg/FlipY/FlipZ/MoveX/MoveZ 默认 0 / False / False / 0 / 0
       ✅ 主 Solver 内部逐项广播后逐个调用 FT_GeoAligner.align，输出 GeoAligner1_MovedGeo

输出端：
- CutTimbers（当前阶段：Step4 的 GeoAligner1_MovedGeo；若 Step4 失败则回落主木坯 TimberBrep）
- FailTimbers
- Log
并保留开发模式输出绑定区（Value/All/AllDict/DBLog/TimberBrep/.../Step3*/Step4*）
"""

import Rhino.Geometry as rg
import scriptcontext as sc

from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    FTAligner,
    build_qiao_tool,
    FT_CutTimberByTools,
    FT_GeoAligner,
)

# ==============================================================
# Step 5 子组件：FT_ShuaTouBuilder（耍头刀具）—— 内嵌实现
#   说明：为保证主 Solver 可独立运行，这里直接内嵌 FT_ShuaTouTool(v1.8) 的核心逻辑。
#   输入来源：主 Solver 的 AllDict（FT_ShuaTouBuilder__*）与默认值。
# ==============================================================

import math


def _st_default_point(p):
    return p if (p is not None) else rg.Point3d(0, 0, 0)


def _st_default_plane(pl):
    if pl is not None:
        return pl
    origin = rg.Point3d(0, 0, 0)
    xaxis = rg.Vector3d(1, 0, 0)
    yaxis = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, xaxis, yaxis)


def _st_default_float(x, v):
    try:
        return float(x)
    except:
        return v


class FT_ShuaTouBuilder_Internal(object):
    """FT_ShuaTouTool (v1.8) 内嵌版"""

    @staticmethod
    def build(base_point, ref_plane,
              width_fen, height_fen,
              AH_fen, DF_fen, FE_fen, EC_fen,
              DG_fen, offset_fen):

        # -------- 默认值 --------
        base_point = _st_default_point(base_point)
        ref_plane = _st_default_plane(ref_plane)
        width_fen = _st_default_float(width_fen, 16)
        height_fen = _st_default_float(height_fen, 15)
        AH_fen = _st_default_float(AH_fen, 5)
        DF_fen = _st_default_float(DF_fen, 6)
        FE_fen = _st_default_float(FE_fen, 5)
        EC_fen = _st_default_float(EC_fen, 5)
        DG_fen = _st_default_float(DG_fen, 2)
        offset_fen = _st_default_float(offset_fen, 5)

        tol = sc.doc.ModelAbsoluteTolerance

        log = []
        dbg_pts = []
        dbg_lines = []

        log.append("=== FT_ShuaTouTool v1.8 START ===")
        log.append("RefPlane: Origin={0}, X={1}, Y={2}, Z={3}".format(
            ref_plane.Origin, ref_plane.XAxis, ref_plane.YAxis, ref_plane.ZAxis))

        # ------------------------------------------------------
        # 0. 主要参考平面 RefPlanes
        # ------------------------------------------------------
        base_ref_plane = rg.Plane(base_point, ref_plane.XAxis, ref_plane.YAxis)

        xy_like_plane = rg.Plane(base_ref_plane)
        rot = rg.Transform.Rotation(math.radians(90.0), base_ref_plane.XAxis, base_point)
        xy_like_plane.Transform(rot)

        RefPlanes = [base_ref_plane, xy_like_plane]

        # ------------------------------------------------------
        # 1. 基础矩形 A B C D（D = BasePoint）
        # ------------------------------------------------------
        A, B, C, D = FT_ShuaTouBuilder_Internal._build_base_rect(
            base_point, ref_plane, width_fen, height_fen)
        dbg_pts.extend([A, B, C, D])

        # ------------------------------------------------------
        # 2. 构建关键点
        # ------------------------------------------------------
        H, F, E, G, J, K, I, L, aux_lines = \
            FT_ShuaTouBuilder_Internal._build_key_points(
                A, B, C, D,
                AH_fen, DF_fen, FE_fen, DG_fen,
                ref_plane, log)

        dbg_pts.extend([H, F, E, G, J, K, I, L])
        dbg_lines.extend(aux_lines)

        # ------------------------------------------------------
        # 3. 中心截面线 / 面
        # ------------------------------------------------------
        CenterSectionCrv = rg.Polyline([H, I, K, E]).ToNurbsCurve()

        center_face_poly = rg.Polyline([H, I, K, E, D, A, H]).ToNurbsCurve()
        cf = rg.Brep.CreatePlanarBreps(center_face_poly)
        CenterSectionFace = cf[0] if cf else None

        # ------------------------------------------------------
        # 4. 侧截面线 / 面
        # ------------------------------------------------------
        SideSectionCrv = rg.Polyline([H, L, C]).ToNurbsCurve()

        side_face_poly = rg.Polyline([H, L, C, D, A, H]).ToNurbsCurve()
        sf = rg.Brep.CreatePlanarBreps(side_face_poly)
        SideSectionFace = sf[0] if sf else None

        # ------------------------------------------------------
        # 5. 两侧偏移：关键点 & 截面线 / 面
        # ------------------------------------------------------
        normal = ref_plane.ZAxis
        n_vec = normal * offset_fen

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

        # ------------------------------------------------------
        # 6. SideLoftFace：直线放样
        # ------------------------------------------------------
        SideLoftFace = None
        if len(OffsetSideCrvs) == 2:
            IKELine = rg.Polyline([I, K, E]).ToNurbsCurve()

            loft_curves = [OffsetSideCrvs[0], IKELine, OffsetSideCrvs[1]]

            loft = rg.Brep.CreateFromLoft(
                loft_curves,
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

        # ------------------------------------------------------
        # 7. TriFace：三角面 H'_neg – I – H'_pos
        # ------------------------------------------------------
        TriFace = None
        tri_brep = rg.Brep.CreateFromCornerPoints(H_neg, I, H_pos, tol)
        if tri_brep:
            TriFace = tri_brep
            log.append("TriFace created (H_neg, I, H_pos).")
        else:
            log.append("TriFace creation failed (points may be collinear).")

        # ------------------------------------------------------
        # 8. H'AD'Loft：两侧偏移后的 H'-A'-D' 直线放样
        # ------------------------------------------------------
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

        # ------------------------------------------------------
        # 9. BottomFace：D'_neg, C'_neg, E, C'_pos, D'_pos 外围封闭
        # ------------------------------------------------------
        BottomFace = None
        bottom_tris = []

        t1 = rg.Brep.CreateFromCornerPoints(D_neg, C_neg, E, tol)
        if t1: bottom_tris.append(t1)
        t2 = rg.Brep.CreateFromCornerPoints(E, C_pos, D_pos, tol)
        if t2: bottom_tris.append(t2)
        t3 = rg.Brep.CreateFromCornerPoints(D_neg, E, D_pos, tol)
        if t3: bottom_tris.append(t3)

        if bottom_tris:
            joined_bottom = rg.Brep.JoinBreps(bottom_tris, tol)
            if joined_bottom and len(joined_bottom) > 0:
                BottomFace = joined_bottom[0]
                log.append("BottomFace created from {0} triangles.".format(len(bottom_tris)))
            else:
                log.append("JoinBreps failed for BottomFace.")
        else:
            log.append("No triangles created for BottomFace.")

        # ------------------------------------------------------
        # 10. Join 所有面 → ToolBrep
        # ------------------------------------------------------
        ToolBrep = None
        join_list = []

        if SideLoftFace:   join_list.append(SideLoftFace)
        if TriFace:        join_list.append(TriFace)
        if HADLoftFace:    join_list.append(HADLoftFace)
        if BottomFace:     join_list.append(BottomFace)
        if OffsetSideFaces:
            join_list.extend([f for f in OffsetSideFaces if f is not None])

        if join_list:
            joined = rg.Brep.JoinBreps(join_list, tol)
            if joined and len(joined) > 0:
                ToolBrep = joined[0]
                log.append("ToolBrep joined from {0} breps.".format(len(join_list)))

                if not ToolBrep.IsSolid:
                    if ToolBrep.CapPlanarHoles(tol):
                        log.append("ToolBrep CapPlanarHoles succeeded, solid = {0}".format(ToolBrep.IsSolid))
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
                RefPlanes,
                dbg_pts,
                dbg_lines,
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
    def _build_key_points(A, B, C, D,
                          AH, DF, FE, DG,
                          plane, log):
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

        I = FT_ShuaTouBuilder_Internal._perpendicular_foot(H, A, F)

        HL = rg.Line(H, H + (F - A) * 200)
        rc3, t5, t6 = rg.Intersect.Intersection.LineLine(HL, GJ)
        L = HL.PointAt(t5) if rc3 else H

        aux = [
            AF.ToNurbsCurve(),
            GJ.ToNurbsCurve(),
            HL.ToNurbsCurve(),
            BC.ToNurbsCurve()
        ]
        return H, F, E, G, J, K, I, L, aux

    @staticmethod
    def _perpendicular_foot(P, A, B):
        line = rg.Line(A, B)
        t = line.ClosestParameter(P)
        return line.PointAt(t)


__author__ = "richiebao [coding-x.tech]"
__version__ = "2025.12.28-step4-qiao-geoalign"


# ==============================================================
# 通用工具函数
# ==============================================================

def to_list(x):
    """若为列表/元组则直接返回，否则包装成长度为1的列表。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def all_to_dict(all_list):
    """
    All = [('A__x', 1), ('B__y', [2,3])]
    -> {'A__x': 1, 'B__y': [2,3]}
    """
    d = {}
    if all_list is None:
        return d
    try:
        for item in all_list:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            k = item[0]
            v = item[1]
            d[k] = v
    except:
        pass
    return d


def _flatten(items):
    """
    递归拍平：把 list/tuple/.NET IEnumerable (嵌套) 展开，避免输出端出现
    System.Collections.Generic.List`1[System.Object] 套娃。
    """
    if items is None:
        return []
    # RhinoCommon / GeometryBase / string 等不展开
    if isinstance(items, (str, rg.GeometryBase, rg.Plane, rg.Point3d, rg.Transform)):
        return [items]
    # list/tuple 递归
    if isinstance(items, (list, tuple)):
        out = []
        for it in items:
            out.extend(_flatten(it))
        return out
    # 其它对象：尽量当标量
    return [items]


def make_ref_plane(mode, origin=None):
    """
    注意：这里严格按你给定的 GH 参考平面轴向关系构造：
    XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  (由 X×Y 得 Z)
    YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)   (由 X×Y 得 Z)
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)

    m = str(mode) if mode is not None else "WorldXZ"
    m = m.strip()

    if m in ("WorldXY", "XY", "GH_XY"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WorldYZ", "YZ", "GH_YZ"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def coerce_point3d(pt):
    """把 GH 输入的点/Point3d/None 统一为 Point3d。None -> 原点。"""
    if pt is None:
        return rg.Point3d(0.0, 0.0, 0.0)
    if isinstance(pt, rg.Point3d):
        return pt
    if isinstance(pt, rg.Point):
        return pt.Location
    # 容错：可能是 GH 的 PointProxy / tuple/list
    try:
        if hasattr(pt, "X") and hasattr(pt, "Y") and hasattr(pt, "Z"):
            return rg.Point3d(float(pt.X), float(pt.Y), float(pt.Z))
    except:
        pass
    try:
        if isinstance(pt, (list, tuple)) and len(pt) >= 3:
            return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
    except:
        pass
    return rg.Point3d(0.0, 0.0, 0.0)


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其它标量 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


# =========================================================
# GH Tree 工具（用于 Step6 GeoAligner3 分支对应）
# =========================================================
def _is_ghtree(x):
    return hasattr(x, "Paths") and hasattr(x, "Branch") and hasattr(x, "BranchCount")


def _tree_paths(x):
    try:
        return list(x.Paths)
    except:
        return []


def _tree_branch(x, path):
    try:
        b = x.Branch(path)
        return list(b) if b is not None else []
    except:
        return []


def _wrap_index_tree(i, n, wrap=True):
    if n <= 0:
        return None
    try:
        ii = int(i)
    except:
        return None
    if wrap:
        return ii % n
    if ii < 0 or ii >= n:
        return None
    return ii


def _plane_from_lists_tree_tree(origin_points_tree, base_planes_tree, index_origin_tree, index_plane_tree, wrap=True):
    """
    Tree×Tree 版本 PlaneFromLists（用于 PlaneFromLists::9 这种“索引也是 Tree”的情况）：

    - origin_points_tree / base_planes_tree / index_origin_tree / index_plane_tree 均为 GH DataTree
    - 同一路径 path 的分支一一对应：
        idxO = IndexOrigin{path}[0]
        idxP = IndexPlane{path}[0]
        pt   = OriginPoints{path}[idxO]
        pl   = BasePlanes{path}[idxP]
      每个 path 输出 1 个 BasePlane/OriginPoint/ResultPlane（保持 Tree 结构）

    返回：BasePlaneTree, OriginPointTree, ResultPlaneTree, Log(list[str])
    """
    out_bp = _ensure_datatree()
    out_op = _ensure_datatree()
    out_rp = _ensure_datatree()
    log = []

    paths = _tree_paths(origin_points_tree)

    for pth in paths:
        pts = _tree_branch(origin_points_tree, pth)
        pls = _tree_branch(base_planes_tree, pth)

        io_branch = _tree_branch(index_origin_tree, pth)
        ip_branch = _tree_branch(index_plane_tree, pth)

        io = io_branch[0] if len(io_branch) > 0 else None
        ip = ip_branch[0] if len(ip_branch) > 0 else None

        iopt = _wrap_index_tree(io, len(pts), wrap)
        ippl = _wrap_index_tree(ip, len(pls), wrap)

        if iopt is None or ippl is None or len(pts) == 0 or len(pls) == 0:
            out_bp.Add(None, pth)
            out_op.Add(None, pth)
            out_rp.Add(None, pth)
            log.append(
                "[PFL][{}] invalid branch/index: pts={}, pls={}, io={}, ip={}".format(pth, len(pts), len(pls), io, ip))
            continue

        pt = pts[iopt]
        pl = pls[ippl]

        if isinstance(pt, rg.Point):
            pt = pt.Location

        try:
            rp = rg.Plane(pl)
            rp.Origin = pt

            out_bp.Add(pl, pth)
            out_op.Add(pt, pth)
            out_rp.Add(rp, pth)
            log.append("[PFL][{}] ok idxO={} idxP={}".format(pth, iopt, ippl))
        except Exception as e:
            out_bp.Add(None, pth)
            out_op.Add(None, pth)
            out_rp.Add(None, pth)
            log.append("[PFL][{}] ERROR: {}".format(pth, e))

    return out_bp, out_op, out_rp, log


def _ensure_datatree():
    return DataTree[object]()


def _broadcast_to_len(lst, n):
    if lst is None:
        return [None] * n
    if len(lst) == 0:
        return [None] * n
    if len(lst) == n:
        return lst
    if len(lst) == 1:
        return lst * n
    out = []
    for i in range(n):
        out.append(lst[i % len(lst)])
    return out


def _align_tree_by_branch(GeoTree, SrcTree, TgtTree, MoveZTree,
                          RotateDeg=0.0, FlipX=False, FlipY=False, FlipZ=False, MoveX=0.0, MoveY=0.0):
    """按 GH Tree 分支(path)一一对应对位，输出保持同结构 Tree。"""
    out_source = _ensure_datatree()
    out_target = _ensure_datatree()
    out_geo = _ensure_datatree()
    log_lines = []

    paths = _tree_paths(GeoTree)
    for p in paths:
        geos = _tree_branch(GeoTree, p)
        srcs = _tree_branch(SrcTree, p)
        tgts = _tree_branch(TgtTree, p)
        mzs = _tree_branch(MoveZTree, p)

        n = len(geos)
        if n == 0:
            log_lines.append("[GeoAligner3][{}] empty Geo branch".format(p))
            continue

        srcs = _broadcast_to_len(srcs, n)
        tgts = _broadcast_to_len(tgts, n)
        mzs = _broadcast_to_len(mzs, n)

        for i in range(n):
            try:
                _mz = mzs[i]
                try:
                    _mzv = float(_mz) if _mz is not None else 0.0
                except:
                    _mzv = 0.0

                so, to_, mg = FT_GeoAligner.align(
                    geos[i],
                    srcs[i],
                    tgts[i],
                    rotate_deg=RotateDeg,
                    flip_x=FlipX,
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=_mzv,
                )
                out_source.Add(so, p)
                out_target.Add(to_, p)
                out_geo.Add(mg, p)
            except Exception as e:
                log_lines.append("[GeoAligner3][{}][{}] ERROR: {}".format(p, i, e))
                out_source.Add(None, p)
                out_target.Add(None, p)
                out_geo.Add(None, p)

        log_lines.append("[GeoAligner3][{}] done n={}".format(p, n))

    return out_source, out_target, out_geo, log_lines


def _broadcast_param(val, n, name="param"):
    """
    广播/截断参数到长度 n：

    - 若 val 为列表/元组：
        * len == 0 : 返回 [None] * n
        * 0 < len < n : 用“最后一个值”补齐到 n
        * len >= n : 只取前 n 个
    - 若 val 为标量：
        * 返回 [val] * n
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


def _is_tree(obj):
    """
    粗略判断 tree(嵌套列表)：
    - obj 是 list/tuple
    - 且其元素中至少有一个还是 list/tuple
    """
    if not isinstance(obj, (list, tuple)):
        return False
    for it in obj:
        if isinstance(it, (list, tuple)):
            return True
    return False


def _as_branches(obj):
    """
    把输入转为“分支列表”：
    - 若 obj 是 tree(嵌套列表) → 返回 [branch0, branch1, ...]
    - 若 obj 是普通 list → 当作单分支 [obj]
    - 其它 → 单分支 [[obj]]
    """
    if obj is None:
        return []
    if _is_tree(obj):
        return list(obj)
    if isinstance(obj, (list, tuple)):
        return [list(obj)]
    return [[obj]]


def _safe_int(x, default=0):
    try:
        return int(x)
    except:
        return int(default)


def _safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return float(default)


def _safe_bool01(x, default=0):
    """
    兼容 GH 的 bool / 0/1 / list 中的 0/1 等
    返回 0/1
    """
    if x is None:
        return 1 if default else 0
    if isinstance(x, bool):
        return 1 if x else 0
    try:
        return 1 if int(x) != 0 else 0
    except:
        s = str(x).strip().lower()
        if s in ("true", "t", "yes", "y", "1"):
            return 1
        if s in ("false", "f", "no", "n", "0"):
            return 0
    return 1 if default else 0


def _is_nested_list(obj):
    try:
        return isinstance(obj, (list, tuple)) and len(obj) > 0 and isinstance(obj[0], (list, tuple))
    except:
        return False


def _wrap_index(i, n, wrap=True):
    if n <= 0:
        return 0
    if wrap:
        return i % n
    if i < 0:
        return 0
    if i >= n:
        return n - 1
    return i


def _parse_index_list(v):
    """IndexOrigin / IndexPlane 允许 int 或 list[int]，也兼容 '1,2,3' 字符串。"""
    if v is None:
        return 0
    try:
        # python3: 仅使用 int
        if isinstance(v, int):
            return int(v)
    except:
        if isinstance(v, int):
            return int(v)

    if isinstance(v, float):
        return int(v)
    if isinstance(v, (list, tuple)):
        out = []
        for it in v:
            try:
                out.append(int(it))
            except:
                pass
        return out
    if isinstance(v, str):
        s = v.strip()
        if "," in s:
            out = []
            for part in s.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    out.append(int(float(part)))
                except:
                    pass
            return out
        try:
            return int(float(s))
        except:
            return 0
    return 0


def _plane_from_lists_local(origin_points, base_planes, index_origin, index_plane, wrap=True, per_branch=False):
    """
    本地版 PlaneFromLists，用于修复 FTPlaneFromLists 对 list index 的 int() 报错。
    - per_branch=True：origin_points/base_planes 为 list[list[...]]，index_origin/index_plane 为 list，与分支一一对应
    - per_branch=False：origin_points/base_planes 为扁平 list，index_* 可为 int 或 list[int]
    返回：BasePlane, OriginPoint, ResultPlane, Log（可能为 list 或单值）
    """
    log = []
    idx_o = _parse_index_list(index_origin)
    idx_p = _parse_index_list(index_plane)

    if per_branch and _is_nested_list(origin_points) and _is_nested_list(base_planes):
        n_branch = min(len(origin_points), len(base_planes))
        idx_o_list = idx_o if isinstance(idx_o, list) else [idx_o] * n_branch
        idx_p_list = idx_p if isinstance(idx_p, list) else [idx_p] * n_branch
        idx_o_list = _broadcast_param(idx_o_list, n_branch, "IndexOrigin")
        idx_p_list = _broadcast_param(idx_p_list, n_branch, "IndexPlane")

        base_out, org_out, res_out = [], [], []
        for bi in range(n_branch):
            ops = origin_points[bi] if bi < len(origin_points) else []
            bps = base_planes[bi] if bi < len(base_planes) else []
            if not ops or not bps:
                base_out.append(None);
                org_out.append(None);
                res_out.append(None)
                log.append("[branch {}] empty inputs".format(bi))
                continue
            io = _wrap_index(int(idx_o_list[bi]), len(ops), wrap=wrap)
            ip = _wrap_index(int(idx_p_list[bi]), len(bps), wrap=wrap)
            op = ops[io]
            bp = bps[ip]
            try:
                rp = rg.Plane(bp)
                rp.Origin = op
            except:
                rp = None
            base_out.append(bp);
            org_out.append(op);
            res_out.append(rp)
            log.append("[branch {}] ok OriginIdx={}, PlaneIdx={}".format(bi, io, ip))
        return base_out, org_out, res_out, log

    ops = origin_points if isinstance(origin_points, (list, tuple)) else to_list(origin_points)
    bps = base_planes if isinstance(base_planes, (list, tuple)) else to_list(base_planes)
    if not ops or not bps:
        return None, None, None, ["empty inputs"]

    if isinstance(idx_o, list) or isinstance(idx_p, list):
        idx_o_list = idx_o if isinstance(idx_o, list) else [idx_o]
        idx_p_list = idx_p if isinstance(idx_p, list) else [idx_p]
        n = max(len(idx_o_list), len(idx_p_list))
        idx_o_list = _broadcast_param(idx_o_list, n, "IndexOrigin")
        idx_p_list = _broadcast_param(idx_p_list, n, "IndexPlane")

        base_out, org_out, res_out = [], [], []
        for i in range(n):
            io = _wrap_index(int(idx_o_list[i]), len(ops), wrap=wrap)
            ip = _wrap_index(int(idx_p_list[i]), len(bps), wrap=wrap)
            op = ops[io]
            bp = bps[ip]
            try:
                rp = rg.Plane(bp);
                rp.Origin = op
            except:
                rp = None
            base_out.append(bp);
            org_out.append(op);
            res_out.append(rp)
            log.append("[{}] ok OriginIdx={}, PlaneIdx={}".format(i, io, ip))
        return base_out, org_out, res_out, log

    io = _wrap_index(int(idx_o), len(ops), wrap=wrap)
    ip = _wrap_index(int(idx_p), len(bps), wrap=wrap)
    op = ops[io]
    bp = bps[ip]
    try:
        rp = rg.Plane(bp);
        rp.Origin = op
    except:
        rp = None
    log.append("ok OriginIdx={}, PlaneIdx={}".format(io, ip))
    return bp, op, rp, log


# ==============================================================
# Step 4 子 Solver —— RufuZhaQian_QiAoSolver（内部类）
#   （改为“可被主 Solver 调用”的形式，不使用其 __main__ 输出绑定区）
# ==============================================================

class RufuZhaQian_QiAoSolver_Internal(object):
    """
    乳栿劄牽_欹䫜刀（QiAo）·宋 · 内部子 Solver（数据库驱动）
    逻辑来自你提供的 RufuZhaQian_QiAoSover.py（Step1~Step6）
    """

    def __init__(self, DBPath, base_point_in, Refresh, ghenv, length_override=None,
                 FT_timber_block_uniform_length_fen=None, RufuZhaQian_QiAoSolver_length_fen=None):
        self.DBPath = DBPath
        self.base_point_in = base_point_in
        self.Refresh = Refresh
        self.ghenv = ghenv

        # -------- 可选 GH 输入端覆盖（输入端 > DB > 默认）--------
        # 若 GhPython 组件未新增这些输入端，则参数为 None，不影响原有 DB 读取逻辑。
        self.timber_length_fen_override = FT_timber_block_uniform_length_fen
        self.qiao_length_fen_override = RufuZhaQian_QiAoSolver_length_fen

        self.length_override = length_override  # 外部覆盖 length_fen（仅 length）

        self.Log = []

        # ---- Step1 ----
        self.Step1_Value = None
        self.Step1_All = []
        self.Step1_AllDict = {}
        self.Step1_DBLog = []

        # ---- Step2: timber ----
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
        self.Step2_Log = []

        # ---- Step3: QiAo tool ----
        self.ToolBrep = None
        self.QiAo_BasePoint = None
        self.QiAo_BaseLine = None
        self.QiAo_SecPlane = None
        self.QiAo_FacePlane = None
        self.Step3_Log = []

        # ---- Step4: PlaneFromLists::1 ----
        self.PFL1_BasePlane = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlane = None
        self.Step4_Log = []

        # ---- Step5: AlignToolToTimber::1 ----
        self.AlignedTool = []
        self.XForm = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo = []
        self.Step5_Log = []

        # ---- Step6: CutTimberByTools ----
        self.CutTimbers = None
        self.FailTimbers = []
        self.Step6_Log = []

    def _all_to_dict(self, all_list):
        d = {}
        if not all_list:
            return d
        try:
            for k, v in all_list:
                d[k] = v
        except:
            for item in all_list:
                if isinstance(item, tuple) and len(item) == 2:
                    d[item[0]] = item[1]
        return d

    def _flatten_list(self, x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            out = []
            for i in x:
                out.extend(self._flatten_list(i))
            return out
        return [x]

    def _getA(self, A, key, default=None):
        if not A:
            return default
        return A.get(key, default)

    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="CommonComponents",
                key_field="type_code",
                key_value="RufuZhaQian_QiAoTool",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            v, all_list, db_log = reader.run()
            self.Step1_Value = v
            self.Step1_All = all_list if all_list else []
            self.Step1_DBLog = db_log if isinstance(db_log, list) else [str(db_log)]
            self.Step1_AllDict = self._all_to_dict(self.Step1_All)

            self.Log.append("[QiAo-DB] AllDict={} 项".format(len(self.Step1_AllDict)))
            for l in self.Step1_DBLog:
                self.Log.append("[QiAo-DB] " + str(l))

        except Exception as e:
            self.Log.append("[QiAo-ERROR] step1_read_db 出错: {}".format(e))
        return self

    def step2_timber_block(self):
        A = self.Step1_AllDict

        base_point = coerce_point3d(self.base_point_in)

        # 尺寸：允许外部覆盖 length_fen（只覆盖 length）
        length_fen = self._getA(A, "FT_timber_block_uniform__length_fen", 32.0)
        width_fen = self._getA(A, "FT_timber_block_uniform__width_fen", 32.0)
        height_fen = self._getA(A, "FT_timber_block_uniform__height_fen", 20.0)

        # 外部覆盖（只对 length）
        if self.length_override is not None:
            length_fen = self.length_override

        try:
            length_fen = float(length_fen)
        except:
            length_fen = 32.0
        try:
            width_fen = float(width_fen)
        except:
            width_fen = 32.0
        try:
            height_fen = float(height_fen)
        except:
            height_fen = 20.0

        ref_mode = self._getA(A, "FT_timber_block_uniform__reference_plane", "WorldXZ")
        reference_plane = make_ref_plane(ref_mode, origin=rg.Point3d(0.0, 0.0, 0.0))

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
            self.Step2_Log = log_lines if isinstance(log_lines, list) else [str(log_lines)]

            self.Log.append("[QiAo-TIMBER] OK: L/W/H={}/{}/{}".format(length_fen, width_fen, height_fen))

        except Exception as e:
            self.Step2_Log = ["[QiAo-TIMBER][ERROR] {}".format(e)]
            self.Log.append("[QiAo-ERROR] step2_timber_block 出错: {}".format(e))

        return self

    def step3_build_qiao_tool(self):
        A = self.Step1_AllDict

        # 默认值
        qi_height = self._getA(A, "FT_QiAo__qi_height", 8.0)
        sha_width = self._getA(A, "FT_QiAo__sha_width", 4.0)
        qi_offset_fen = self._getA(A, "FT_QiAo__qi_offset_fen", 1.0)
        extrude_length = self._getA(A, "FT_QiAo__extrude_length", 46.0)
        extrude_positive = self._getA(A, "FT_QiAo__extrude_positive", True)

        qi_height = _safe_float(qi_height, 8.0)
        sha_width = _safe_float(sha_width, 4.0)
        qi_offset_fen = _safe_float(qi_offset_fen, 1.0)
        extrude_length = _safe_float(extrude_length, 46.0)
        extrude_positive = bool(extrude_positive)

        base_point = coerce_point3d(self.base_point_in)

        rp = self._getA(A, "FT_QiAo__reference_plane", None)
        if rp is None:
            reference_plane = None
        elif isinstance(rp, rg.Plane):
            reference_plane = rg.Plane(rp)
        else:
            reference_plane = make_ref_plane(rp, origin=base_point)

        try:
            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset_fen,
                extrude_length,
                base_point,
                reference_plane,
                extrude_positive
            )

            self.ToolBrep = ToolBrep
            self.QiAo_BasePoint = BasePoint
            self.QiAo_BaseLine = BaseLine
            self.QiAo_SecPlane = SecPlane
            self.QiAo_FacePlane = FacePlane
            self.Step3_Log = ["[QiAo] OK"]

        except Exception as e:
            self.ToolBrep = None
            self.QiAo_BasePoint = None
            self.QiAo_BaseLine = None
            self.QiAo_SecPlane = None
            self.QiAo_FacePlane = None
            self.Step3_Log = ["[QiAo][ERROR] {}".format(e)]
            self.Log.append("[QiAo-ERROR] step3_build_qiao_tool 出错: {}".format(e))

        return self

    def step4_plane_from_lists_1(self):
        A = self.Step1_AllDict

        OriginPoints = self.EdgeMidPoints
        BasePlanes = self.Corner0Planes

        idx_origin = self._getA(A, "PlaneFromLists_1__IndexOrigin", 0)
        idx_plane = self._getA(A, "PlaneFromLists_1__IndexPlane", 0)

        IndexOrigin = _safe_int(idx_origin, 0)
        IndexPlane = _safe_int(idx_plane, 0)

        Wrap = True

        try:
            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                int(IndexOrigin),
                int(IndexPlane)
            )
            self.PFL1_BasePlane = BasePlane
            self.PFL1_OriginPoint = OriginPoint
            self.PFL1_ResultPlane = ResultPlane
            self.Step4_Log = self._flatten_list(Log)

            self.Log.append("[QiAo-PFL1] OK: IndexOrigin={} IndexPlane={}".format(IndexOrigin, IndexPlane))

        except Exception as e:
            self.PFL1_BasePlane = None
            self.PFL1_OriginPoint = None
            self.PFL1_ResultPlane = None
            self.Step4_Log = ["[QiAo-PFL1][ERROR] {}".format(e)]
            self.Log.append("[QiAo-ERROR] step4_plane_from_lists_1 出错: {}".format(e))

        return self

    def step5_align_tool_to_timber_1(self):
        A = self.Step1_AllDict

        ToolGeo = self.ToolBrep
        ToolBasePlane = self.QiAo_FacePlane
        BlockFacePlane = self.PFL1_ResultPlane

        BlockRotDeg = self._getA(A, "FT_AlignToolToTimber_1__ToolRotDeg", 0.0)
        BlockRotDeg = _safe_float(BlockRotDeg, 0.0)

        # 其余默认
        ToolRotDeg = None
        ToolContactPoint = None
        BlockTargetPoint = None
        Mode = None
        ToolDir = None
        TargetDir = None
        DepthOffset = None
        MoveU = None
        MoveV = None
        FlipX = None
        FlipY = None
        FlipZ = None

        AlignedTool = []
        XForm = []
        SourcePlane = []
        TargetPlane = []
        SourcePoint = []
        TargetPoint = []
        DebugInfo = []

        tools_list_base = to_list(ToolGeo) if ToolGeo is not None else []
        if len(tools_list_base) == 0 or all(t is None for t in tools_list_base):
            DebugInfo = ["ToolGeo 输入为空，未进行对位。"]
        else:
            tool_count = len(tools_list_base)
            if tool_count == 1:
                lengths = [1,
                           _param_length(ToolBasePlane),
                           _param_length(ToolRotDeg),
                           _param_length(ToolContactPoint),
                           _param_length(BlockFacePlane),
                           _param_length(BlockRotDeg),
                           _param_length(FlipX),
                           _param_length(FlipY),
                           _param_length(FlipZ),
                           _param_length(BlockTargetPoint),
                           _param_length(Mode),
                           _param_length(ToolDir),
                           _param_length(TargetDir),
                           _param_length(DepthOffset),
                           _param_length(MoveU),
                           _param_length(MoveV)]
                lengths = [l for l in lengths if l > 0]
                N = max(lengths) if lengths else 1
            else:
                N = tool_count

            tools_list = _broadcast_param(tools_list_base, N, "ToolGeo")
            tool_planes = _broadcast_param(ToolBasePlane, N, "ToolBasePlane")
            tool_rots = _broadcast_param(ToolRotDeg, N, "ToolRotDeg")
            tool_pts = _broadcast_param(ToolContactPoint, N, "ToolContactPoint")
            block_planes = _broadcast_param(BlockFacePlane, N, "BlockFacePlane")
            block_rots = _broadcast_param(BlockRotDeg, N, "BlockRotDeg")
            flip_xs = _broadcast_param(FlipX, N, "FlipX")
            flip_ys = _broadcast_param(FlipY, N, "FlipY")
            flip_zs = _broadcast_param(FlipZ, N, "FlipZ")
            block_pts = _broadcast_param(BlockTargetPoint, N, "BlockTargetPoint")
            modes = _broadcast_param(Mode, N, "Mode")
            tool_dirs = _broadcast_param(ToolDir, N, "ToolDir")
            target_dirs = _broadcast_param(TargetDir, N, "TargetDir")
            depth_offsets = _broadcast_param(DepthOffset, N, "DepthOffset")
            move_us = _broadcast_param(MoveU, N, "MoveU")
            move_vs = _broadcast_param(MoveV, N, "MoveV")

            for i in range(N):
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tools_list[i],
                    tool_planes[i],
                    tool_pts[i],
                    block_planes[i],
                    block_pts[i],
                    modes[i],
                    tool_dirs[i],
                    target_dirs[i],
                    depth_offsets[i],
                    move_us[i],
                    move_vs[i],
                    flip_xs[i],
                    flip_ys[i],
                    flip_zs[i],
                    tool_rots[i],
                    block_rots[i]
                )

                AlignedTool.append(aligned)
                XForm.append(xf)
                SourcePlane.append(src_pl)
                TargetPlane.append(tgt_pl)
                SourcePoint.append(src_pt)
                TargetPoint.append(tgt_pt)
                DebugInfo.append(dbg)

        self.AlignedTool = AlignedTool
        self.XForm = XForm
        self.SourcePlane = SourcePlane
        self.TargetPlane = TargetPlane
        self.SourcePoint = SourcePoint
        self.TargetPoint = TargetPoint
        self.DebugInfo = DebugInfo
        self.Step5_Log = self._flatten_list(DebugInfo)

        return self

    def step6_cut_timber_by_tools(self):
        Timbers = self.TimberBrep
        Tools = self.AlignedTool

        try:
            cutter = FT_CutTimberByTools(Timbers, Tools)
            CutTimbers, FailTimbers, Log = cutter.run()

            self.CutTimbers = CutTimbers
            self.FailTimbers = FailTimbers if FailTimbers is not None else []
            self.Step6_Log = self._flatten_list(Log)

        except Exception as e:
            self.CutTimbers = None
            self.FailTimbers = []
            self.Step6_Log = ["[QiAo-CUT][ERROR] {}".format(e)]
            self.Log.append("[QiAo-ERROR] step6_cut_timber_by_tools 出错: {}".format(e))

        return self

    def run(self):
        self.step1_read_db()
        self.step2_timber_block()
        self.step3_build_qiao_tool()
        self.step4_plane_from_lists_1()
        self.step5_align_tool_to_timber_1()
        self.step6_cut_timber_by_tools()

        self.Log = self._flatten_list(
            self.Log + self.Step2_Log + self.Step3_Log + self.Step4_Log + self.Step5_Log + self.Step6_Log)
        return self


# ==============================================================
# 主 Solver 类 —— 乳栿劄牽 RufuZhaQianSolver
# ==============================================================

class RufuZhaQianSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv,
                 FT_timber_block_uniform_length_fen=None,
                 RufuZhaQian_QiAoSolver_length_fen=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = bool(Refresh) if Refresh is not None else False
        self.ghenv = ghenv

        # 若 GhPython 组件未新增这些输入端，则参数为 None，不影响原有 DB 读取逻辑。
        self.timber_length_fen_override = FT_timber_block_uniform_length_fen
        self.qiao_length_fen_override = RufuZhaQian_QiAoSolver_length_fen

        # -------- Step 1：数据库读取（直接 All / AllDict）--------
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # -------- Step 2：木坯输出（与 FT_timber_block_uniform 命名保持一致）--------
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

        # -------- Step 3：端头粗削 --------
        # 3.1 FT_BlockCutter::1 输出（“刀具木块”）
        self.BlockCutter1_TimberBrep = None
        self.BlockCutter1_FaceList = []
        self.BlockCutter1_PointList = []
        self.BlockCutter1_EdgeList = []
        self.BlockCutter1_CenterPoint = None
        self.BlockCutter1_CenterAxisLines = []
        self.BlockCutter1_EdgeMidPoints = []
        self.BlockCutter1_FacePlaneList = []
        self.BlockCutter1_Corner0Planes = []
        self.BlockCutter1_LocalAxesPlane = None
        self.BlockCutter1_AxisX = None
        self.BlockCutter1_AxisY = None
        self.BlockCutter1_AxisZ = None
        self.BlockCutter1_FaceDirTags = []
        self.BlockCutter1_EdgeDirTags = []
        self.BlockCutter1_Corner0EdgeDirs = []
        self.BlockCutter1_Log = []

        # 3.2 PlaneFromLists::1 输出（主木坯取面）
        self.PF1_BasePlane = []
        self.PF1_OriginPoint = []
        self.PF1_ResultPlane = []
        self.PF1_Log = []

        # 3.3 PlaneFromLists::2 输出（刀具木块取面）
        self.PF2_BasePlane = []
        self.PF2_OriginPoint = []
        self.PF2_ResultPlane = []
        self.PF2_Log = []

        # 3.4 FT_AlignToolToTimber::1 输出
        self.Align1_AlignedTool = []
        self.Align1_XForm = []
        self.Align1_SourcePlane = []
        self.Align1_TargetPlane = []
        self.Align1_SourcePoint = []
        self.Align1_TargetPoint = []
        self.Align1_DebugInfo = []

        # -------- Step 4：欹䫜刀 + 对齐 --------
        self.QiAoSolver = None
        self.QiAo_CutTimbers = None
        self.QiAo_FailTimbers = []
        self.QiAo_Log = []
        self.QiAo_TimberBrep = None
        self.QiAo_EdgeMidPoints = []
        self.QiAo_Corner0Planes = []

        self.PF3_BasePlane = []
        self.PF3_OriginPoint = []
        self.PF3_ResultPlane = []
        self.PF3_Log = []

        self.PF4_BasePlane = []
        self.PF4_OriginPoint = []
        self.PF4_ResultPlane = []
        self.PF4_Log = []

        self.GeoAligner1_SourceOut = []
        self.GeoAligner1_TargetOut = []
        self.GeoAligner1_MovedGeo = []
        self.GeoAligner1_Log = []

        # -------- Step 5：耍头（FT_ShuaTouBuilder + PF5 + GeoAligner2）--------
        self.ShuaTou_CenterSectionCrv = None
        self.ShuaTou_SideSectionCrv = None
        self.ShuaTou_CenterSectionFace = None
        self.ShuaTou_SideSectionFace = None
        self.ShuaTou_OffsetSideFaces = []
        self.ShuaTou_OffsetSideCrvs = []
        self.ShuaTou_SideLoftFace = None
        self.ShuaTou_ToolBrep = None
        self.ShuaTou_RefPlanes = []
        self.ShuaTou_DebugPoints = []
        self.ShuaTou_DebugLines = []
        self.ShuaTou_Log = []

        self.PF5_BasePlane = []
        self.PF5_OriginPoint = []
        self.PF5_ResultPlane = []
        self.PF5_Log = []

        self.GeoAligner2_SourceOut = []
        self.GeoAligner2_TargetOut = []
        self.GeoAligner2_MovedGeo = []
        self.GeoAligner2_Log = []

        # ---- Step6: 櫨枓切削（FT_BlockCutter::2 + PF6 + PF7 + GeoAligner3）----
        self.BlockCutter2_TimberBrep = []
        self.BlockCutter2_FaceList = []
        self.BlockCutter2_PointList = []
        self.BlockCutter2_EdgeList = []
        self.BlockCutter2_CenterPoint = []
        self.BlockCutter2_CenterAxisLines = []
        self.BlockCutter2_EdgeMidPoints = []
        self.BlockCutter2_FacePlaneList = []
        self.BlockCutter2_Corner0Planes = []
        self.BlockCutter2_LocalAxesPlane = []
        self.BlockCutter2_AxisX = []
        self.BlockCutter2_AxisY = []
        self.BlockCutter2_AxisZ = []
        self.BlockCutter2_FaceDirTags = []
        self.BlockCutter2_EdgeDirTags = []
        self.BlockCutter2_Corner0EdgeDirs = []
        self.BlockCutter2_Log = []

        self.PF6_BasePlane = []
        self.PF6_OriginPoint = []
        self.PF6_ResultPlane = []
        self.PF6_Log = []

        self.PF7_BasePlane = []
        self.PF7_OriginPoint = []
        self.PF7_ResultPlane = []
        self.PF7_Log = []

        self.GeoAligner3_SourceOut = []
        self.GeoAligner3_TargetOut = []
        self.GeoAligner3_MovedGeo = []

        # -------- Step 7：泥道栱切削 + 最终切木（BlockCutter3 + PF8/PF9 + GeoAligner4 + CutTimberByTools）--------
        self.BlockCutter3_TimberBrep = []
        self.BlockCutter3_FaceList = []
        self.BlockCutter3_PointList = []
        self.BlockCutter3_EdgeList = []
        self.BlockCutter3_CenterPoint = []
        self.BlockCutter3_CenterAxisLines = []
        self.BlockCutter3_EdgeMidPoints = []
        self.BlockCutter3_FacePlaneList = []
        self.BlockCutter3_Corner0Planes = []
        self.BlockCutter3_LocalAxesPlane = []
        self.BlockCutter3_AxisX = []
        self.BlockCutter3_AxisY = []
        self.BlockCutter3_AxisZ = []
        self.BlockCutter3_FaceDirTags = []
        self.BlockCutter3_EdgeDirTags = []
        self.BlockCutter3_Corner0EdgeDirs = []
        self.BlockCutter3_Log = []

        self.PF8_BasePlane = []
        self.PF8_OriginPoint = []
        self.PF8_ResultPlane = []
        self.PF8_Log = []

        self.PF9_BasePlane = []
        self.PF9_OriginPoint = []
        self.PF9_ResultPlane = []
        self.PF9_Log = []

        self.GeoAligner4_SourceOut = []
        self.GeoAligner4_TargetOut = []
        self.GeoAligner4_MovedGeo = []
        self.GeoAligner4_Log = []

        self.Final_CutTimbers = []
        self.Final_FailTimbers = []
        self.Final_Log = []
        self.GeoAligner3_Log = []

        # 最终输出
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：从 AllDict 中取值
    # ------------------------------------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict[key]
        # 若是长度为 1 的 list/tuple，则解包
        if isinstance(v, (list, tuple)):
            if len(v) == 0:
                return default
            if len(v) == 1:
                return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        读取：CommonComponents / type_code = RufuZhaQian / params_json
        """
        try:
            cache_key = "RZQ_DB_CACHE::{}::{}".format(self.DBPath, "RufuZhaQian")

            # Refresh=False 时可复用缓存（避免频繁读库）
            if (not self.Refresh) and (cache_key in sc.sticky):
                pack = sc.sticky.get(cache_key, None)
                if pack:
                    self.Value, self.All, self.DBLog = pack
                    self.AllDict = all_to_dict(self.All)
                    self.Log.append("[DB] 使用 sticky 缓存（Refresh=False）")
                    self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))
                    return self

            reader = DBJsonReader(
                db_path=self.DBPath,
                table="CommonComponents",
                key_field="type_code",
                key_value="RufuZhaQian",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成：type_code=RufuZhaQian")
            for l in (self.DBLog or []):
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

            # 写入缓存
            sc.sticky[cache_key] = (self.Value, self.All, self.DBLog)

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ------------------------------------------------------
    def step2_timber(self):
        """
        - base_point 来自组件输入端 base_point
        - 若无输入，则默认原点
        - reference_plane 默认 GH XZ Plane（也可从 DB 读字符串决定）
        """
        base_point = coerce_point3d(self.base_point)

        length_raw = self.all_get("FT_timber_block_uniform__length_fen", 32.0)
        width_raw = self.all_get("FT_timber_block_uniform__width_fen", 32.0)
        height_raw = self.all_get("FT_timber_block_uniform__height_fen", 20.0)

        try:
            length_fen = float(length_raw)
            width_fen = float(width_raw)
            height_fen = float(height_raw)
        except Exception as e:
            self.Log.append("[TIMBER] fen 尺寸转换 float 出错: {}，使用默认 32/32/20".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        # 输入端覆盖：FT_timber_block_uniform length_fen（优先级：输入端 > DB）
        if getattr(self, "timber_length_fen_override", None) is not None:
            try:
                length_fen = float(self.timber_length_fen_override)
                self.Log.append("[TIMBER] length_fen 覆盖：输入端 = {}".format(length_fen))
            except Exception as e:
                self.Log.append("[TIMBER] length_fen 输入端覆盖转换失败: {}，忽略覆盖".format(e))

        ref_mode = self.all_get("FT_timber_block_uniform__reference_plane", "WorldXZ")
        reference_plane = make_ref_plane(ref_mode, origin=rg.Point3d(0.0, 0.0, 0.0))

        print(length_fen)

        self.Log.append("[TIMBER] reference_plane 模式 = {}".format(ref_mode))
        self.Log.append(
            "[TIMBER] base_point = ({:.3f}, {:.3f}, {:.3f})".format(base_point.X, base_point.Y, base_point.Z))

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
            self.TimberLog = log_lines or []

            self.Log.append("[TIMBER] build_timber_block_uniform 完成")
            for l in self.TimberLog:
                self.Log.append("[TIMBER] " + str(l))

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
            self.TimberLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step2_timber 出错: {}".format(e))

        # 先占位（后续会被 Step4 覆盖）
        if self.TimberBrep is not None:
            self.CutTimbers = [self.TimberBrep]
            self.FailTimbers = []
        else:
            self.CutTimbers = []
            self.FailTimbers = []

        return self

    # ------------------------------------------------------
    # Step 3：端头粗削
    # ------------------------------------------------------
    def step3_end_rough_cut(self):

        # ========== 3.1 FT_BlockCutter::1 ==========
        # 允许 length/width/height 为标量或列表；列表则生成多个刀具木块
        bc_len_raw = self.all_get("FT_BlockCutter_1__length_fen", 32.0)
        bc_wid_raw = self.all_get("FT_BlockCutter_1__width_fen", 32.0)
        bc_hei_raw = self.all_get("FT_BlockCutter_1__height_fen", 20.0)

        # 广播到 N
        len_list = to_list(bc_len_raw)
        wid_list = to_list(bc_wid_raw)
        hei_list = to_list(bc_hei_raw)

        N = max(len(len_list), len(wid_list), len(hei_list), 1)
        len_list = _broadcast_param(len_list, N, "BC1_length_fen")
        wid_list = _broadcast_param(wid_list, N, "BC1_width_fen")
        hei_list = _broadcast_param(hei_list, N, "BC1_height_fen")

        # 默认 base_point = 原点；reference_plane = GH XZ（可由 DB 指定）
        bc_base_point = rg.Point3d(0.0, 0.0, 0.0)
        bc_ref_mode = self.all_get("FT_BlockCutter_1__reference_plane", "WorldXZ")
        bc_reference_plane = make_ref_plane(bc_ref_mode, origin=rg.Point3d(0.0, 0.0, 0.0))

        # 这里改为“多刀具列表输出”
        self.BlockCutter1_TimberBrep = []
        self.BlockCutter1_FaceList = []
        self.BlockCutter1_PointList = []
        self.BlockCutter1_EdgeList = []
        self.BlockCutter1_CenterPoint = []
        self.BlockCutter1_CenterAxisLines = []
        self.BlockCutter1_EdgeMidPoints = []
        self.BlockCutter1_FacePlaneList = []
        self.BlockCutter1_Corner0Planes = []
        self.BlockCutter1_LocalAxesPlane = []
        self.BlockCutter1_AxisX = []
        self.BlockCutter1_AxisY = []
        self.BlockCutter1_AxisZ = []
        self.BlockCutter1_FaceDirTags = []
        self.BlockCutter1_EdgeDirTags = []
        self.BlockCutter1_Corner0EdgeDirs = []
        self.BlockCutter1_Log = []

        self.Log.append("[BLOCKCUTTER1] raw length/width/height = {} {} {}".format(bc_len_raw, bc_wid_raw, bc_hei_raw))
        self.Log.append("[BLOCKCUTTER1] broadcast N = {}".format(N))

        for i in range(N):
            # 每个值转 float（单值）
            bc_length_fen = _safe_float(len_list[i], 0.0)
            bc_width_fen = _safe_float(wid_list[i], 0.0)
            bc_height_fen = _safe_float(hei_list[i], 0.0)

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
                    bc_length_fen,
                    bc_width_fen,
                    bc_height_fen,
                    bc_base_point,
                    bc_reference_plane,
                )

                self.BlockCutter1_TimberBrep.append(timber_brep)
                self.BlockCutter1_FaceList.append(faces)
                self.BlockCutter1_PointList.append(points)
                self.BlockCutter1_EdgeList.append(edges)
                self.BlockCutter1_CenterPoint.append(center_pt)
                self.BlockCutter1_CenterAxisLines.append(center_axes)
                self.BlockCutter1_EdgeMidPoints.append(edge_midpts)
                self.BlockCutter1_FacePlaneList.append(face_planes)
                self.BlockCutter1_Corner0Planes.append(corner0_planes)
                self.BlockCutter1_LocalAxesPlane.append(local_axes_plane)
                self.BlockCutter1_AxisX.append(axis_x)
                self.BlockCutter1_AxisY.append(axis_y)
                self.BlockCutter1_AxisZ.append(axis_z)
                self.BlockCutter1_FaceDirTags.append(face_tags)
                self.BlockCutter1_EdgeDirTags.append(edge_tags)
                self.BlockCutter1_Corner0EdgeDirs.append(corner0_dirs)

                self.BlockCutter1_Log.append(log_lines or [])
                self.Log.append("[BLOCKCUTTER1][{}] done L/W/H = {} / {} / {}".format(i, bc_length_fen, bc_width_fen,
                                                                                      bc_height_fen))

            except Exception as e:
                # 失败也要占位，避免后续索引错位
                self.BlockCutter1_TimberBrep.append(None)
                self.BlockCutter1_FaceList.append([])
                self.BlockCutter1_PointList.append([])
                self.BlockCutter1_EdgeList.append([])
                self.BlockCutter1_CenterPoint.append(None)
                self.BlockCutter1_CenterAxisLines.append([])
                self.BlockCutter1_EdgeMidPoints.append([])
                self.BlockCutter1_FacePlaneList.append([])
                self.BlockCutter1_Corner0Planes.append([])
                self.BlockCutter1_LocalAxesPlane.append(None)
                self.BlockCutter1_AxisX.append(None)
                self.BlockCutter1_AxisY.append(None)
                self.BlockCutter1_AxisZ.append(None)
                self.BlockCutter1_FaceDirTags.append([])
                self.BlockCutter1_EdgeDirTags.append([])
                self.BlockCutter1_Corner0EdgeDirs.append([])
                self.BlockCutter1_Log.append(["错误: {}".format(e)])
                self.Log.append("[ERROR] FT_BlockCutter::1 [{}] 出错: {}".format(i, e))

        # 如果全是 None，直接返回（后面 PF2/Align 都没意义）
        if all(t is None for t in self.BlockCutter1_TimberBrep):
            self.Log.append("[BLOCKCUTTER1] 全部刀具构建失败，跳过 PF2/Align1")
            return self

        # ========== 3.2 PlaneFromLists::1（PF1：主木坯）==========
        self.PF1_BasePlane = []
        self.PF1_OriginPoint = []
        self.PF1_ResultPlane = []
        self.PF1_Log = []

        if not self.EdgeMidPoints or not self.Corner0Planes:
            self.PF1_Log = ["EdgeMidPoints 或 Corner0Planes 为空"]
            self.Log.append("[PF1] EdgeMidPoints 或 Corner0Planes 为空，跳过 PF1")
        else:
            idx_origin_raw = self.all_get("PlaneFromLists_1__IndexOrigin", 0)
            idx_plane_raw = self.all_get("PlaneFromLists_1__IndexPlane", 0)
            wrap_raw = self.all_get("PlaneFromLists_1__Wrap", True)

            idx_origin_list = to_list(idx_origin_raw)
            idx_plane_list = to_list(idx_plane_raw)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _bcast_idx(seq, n):
                if seq is None:
                    return [0] * n
                seq = list(seq)
                if len(seq) == 0:
                    return [0] * n
                if len(seq) >= n:
                    return seq[:n]
                last = seq[-1]
                return seq + [last] * (n - len(seq))

            try:
                idx_origin_list = [int(x) for x in _bcast_idx(idx_origin_list, n)]
                idx_plane_list = [int(x) for x in _bcast_idx(idx_plane_list, n)]
            except Exception as e:
                self.Log.append("[PF1] IndexOrigin/IndexPlane 转 int 失败: {}，退回 [0]".format(e))
                idx_origin_list = [0]
                idx_plane_list = [0]
                n = 1

            Wrap = bool(wrap_raw)
            pf = FTPlaneFromLists(wrap=Wrap)

            try:
                for i in range(n):
                    bp, op, rp, lg = pf.build_plane(
                        self.EdgeMidPoints,
                        self.Corner0Planes,
                        idx_origin_list[i],
                        idx_plane_list[i]
                    )
                    self.PF1_BasePlane.append(bp)
                    self.PF1_OriginPoint.append(op)
                    self.PF1_ResultPlane.append(rp)
                    for l in (lg or []):
                        self.PF1_Log.append("[{}] {}".format(i, str(l)))

                self.Log.append("[PF1] PlaneFromLists::1 完成，数量={}".format(len(self.PF1_ResultPlane)))

            except Exception as e:
                self.PF1_BasePlane = []
                self.PF1_OriginPoint = []
                self.PF1_ResultPlane = []
                self.PF1_Log = ["错误: {}".format(e)]
                self.Log.append("[ERROR] PlaneFromLists::1 出错: {}".format(e))

        # ========== 3.3 PlaneFromLists::2（PF2：刀具木块）==========
        self.PF2_BasePlane = []
        self.PF2_OriginPoint = []
        self.PF2_ResultPlane = []
        self.PF2_Log = []

        # 现在 BlockCutter1_EdgeMidPoints/Corner0Planes 是“多刀具的嵌套列表”
        op_in = self.BlockCutter1_EdgeMidPoints
        bp_in = self.BlockCutter1_Corner0Planes

        idx_origin_raw = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
        idx_plane_raw = self.all_get("PlaneFromLists_2__IndexPlane", 0)
        wrap_raw = self.all_get("PlaneFromLists_2__Wrap", True)

        idx_origin_list = to_list(idx_origin_raw)
        idx_plane_list = to_list(idx_plane_raw)

        Wrap = bool(wrap_raw)
        pf2 = FTPlaneFromLists(wrap=Wrap)

        # 将 “多刀具” 当作多个分支：每个刀具一支
        op_branches = _as_branches(op_in)
        bp_branches = _as_branches(bp_in)

        if len(op_branches) == 0 or len(bp_branches) == 0:
            self.PF2_Log = ["分支为空，无法构建 PF2"]
            self.Log.append("[PF2] 分支为空，跳过 PF2")
        else:
            branch_count = max(len(op_branches), len(bp_branches))
            if len(op_branches) == 1 and branch_count > 1:
                op_branches = op_branches * branch_count
            if len(bp_branches) == 1 and branch_count > 1:
                bp_branches = bp_branches * branch_count

            idx_origin_b = _broadcast_param(idx_origin_list, branch_count, "PF2_IndexOrigin")
            idx_plane_b = _broadcast_param(idx_plane_list, branch_count, "PF2_IndexPlane")

            for bi in range(branch_count):
                branch_ops = op_branches[bi]
                branch_bps = bp_branches[bi]

                # 跳过构建失败的刀具（None / 空分支）
                if branch_ops is None or branch_bps is None or len(branch_ops) == 0 or len(branch_bps) == 0:
                    self.PF2_BasePlane.append(None)
                    self.PF2_OriginPoint.append(None)
                    self.PF2_ResultPlane.append(None)
                    self.PF2_Log.append("[branch {}] 输入分支为空（该刀具可能构建失败）".format(bi))
                    continue

                io = _safe_int(idx_origin_b[bi], 0)
                ip = _safe_int(idx_plane_b[bi], 0)

                try:
                    bp_out, op_out, rp_out, lg = pf2.build_plane(
                        branch_ops,
                        branch_bps,
                        io,
                        ip
                    )
                    self.PF2_BasePlane.append(bp_out)
                    self.PF2_OriginPoint.append(op_out)
                    self.PF2_ResultPlane.append(rp_out)
                    for l in (lg or []):
                        self.PF2_Log.append("[branch {}] {}".format(bi, str(l)))
                except Exception as e:
                    self.PF2_BasePlane.append(None)
                    self.PF2_OriginPoint.append(None)
                    self.PF2_ResultPlane.append(None)
                    self.PF2_Log.append("[branch {}] 错误: {}".format(bi, e))

            self.Log.append("[PF2] PlaneFromLists::2 完成，数量={}".format(len(self.PF2_ResultPlane)))

        # ========== 3.4 FT_AlignToolToTimber::1（Align1）==========
        self.Align1_AlignedTool = []
        self.Align1_XForm = []
        self.Align1_SourcePlane = []
        self.Align1_TargetPlane = []
        self.Align1_SourcePoint = []
        self.Align1_TargetPoint = []
        self.Align1_DebugInfo = []

        # ToolGeo 现在是列表（多刀具）
        tool_geo_list = self.BlockCutter1_TimberBrep
        tool_base_planes = self.PF2_ResultPlane
        block_face_planes = self.PF1_ResultPlane

        # 过滤无效
        if not block_face_planes:
            self.Align1_DebugInfo = ["BlockFacePlane(PF1_ResultPlane) 为空，无法对位"]
            self.Log.append("[ALIGN1] BlockFacePlane 为空，跳过 Align1")
            return self

        # 以 Tool 数量为主（多刀具场景），FacePlane 广播
        N = max(len(tool_geo_list), len(tool_base_planes), 1)
        tool_geo_list = _broadcast_param(tool_geo_list, N, "ToolGeo")
        tool_base_list = _broadcast_param(tool_base_planes, N, "ToolBasePlane")
        block_face_list = _broadcast_param(block_face_planes, N, "BlockFacePlane")

        # DB 参数：BlockRotDeg / FlipY
        block_rot_raw = self.all_get("FT_AlignToolToTimber_1__BlockRotDeg", 0.0)
        flip_y_raw = self.all_get("FT_AlignToolToTimber_1__FlipY", 0)
        block_rot_list = _broadcast_param(block_rot_raw, N, "BlockRotDeg")
        flip_y_list = _broadcast_param(flip_y_raw, N, "FlipY")

        # 其他默认
        tool_rot_deg_list = _broadcast_param(0.0, N, "ToolRotDeg")
        tool_contact_point_list = _broadcast_param(None, N, "ToolContactPoint")
        block_target_point_list = _broadcast_param(None, N, "BlockTargetPoint")
        mode_list = _broadcast_param(0, N, "Mode")
        tool_dir_list = _broadcast_param(None, N, "ToolDir")
        target_dir_list = _broadcast_param(None, N, "TargetDir")
        depth_offset_list = _broadcast_param(0.0, N, "DepthOffset")
        move_u_list = _broadcast_param(0.0, N, "MoveU")
        move_v_list = _broadcast_param(0.0, N, "MoveV")
        flip_x_list = _broadcast_param(0, N, "FlipX")
        flip_z_list = _broadcast_param(0, N, "FlipZ")

        for i in range(N):
            # 跳过无效刀具/平面
            if tool_geo_list[i] is None or tool_base_list[i] is None or block_face_list[i] is None:
                self.Align1_AlignedTool.append(None)
                self.Align1_XForm.append(None)
                self.Align1_SourcePlane.append(None)
                self.Align1_TargetPlane.append(None)
                self.Align1_SourcePoint.append(None)
                self.Align1_TargetPoint.append(None)
                self.Align1_DebugInfo.append("[{}] 输入为空，跳过".format(i))
                continue

            try:
                br = _safe_float(block_rot_list[i], 0.0)
                fy = _safe_bool01(flip_y_list[i], 0)

                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tool_geo_list[i],
                    tool_base_list[i],
                    tool_contact_point_list[i],
                    block_face_list[i],
                    block_target_point_list[i],
                    mode_list[i],
                    tool_dir_list[i],
                    target_dir_list[i],
                    depth_offset_list[i],
                    move_u_list[i],
                    move_v_list[i],
                    flip_x_list[i],
                    fy,
                    flip_z_list[i],
                    tool_rot_deg_list[i],
                    br
                )

                self.Align1_AlignedTool.append(aligned)
                self.Align1_XForm.append(xf)
                self.Align1_SourcePlane.append(src_pl)
                self.Align1_TargetPlane.append(tgt_pl)
                self.Align1_SourcePoint.append(src_pt)
                self.Align1_TargetPoint.append(tgt_pt)
                self.Align1_DebugInfo.append(dbg)

                if aligned is None:
                    self.Log.append("[ALIGN1][{}] 对位失败: {}".format(i, dbg))
                else:
                    self.Log.append("[ALIGN1][{}] 对位完成 BlockRotDeg={} FlipY={}".format(i, br, fy))

            except Exception as e:
                msg = "[ERROR][ALIGN1][{}] FTAligner.align 出错: {}".format(i, e)
                self.Align1_AlignedTool.append(None)
                self.Align1_XForm.append(None)
                self.Align1_SourcePlane.append(None)
                self.Align1_TargetPlane.append(None)
                self.Align1_SourcePoint.append(None)
                self.Align1_TargetPoint.append(None)
                self.Align1_DebugInfo.append(msg)
                self.Log.append(msg)

        return self

    # ------------------------------------------------------
    # Step 4：QiAo 子流程 + PF3/PF4 + GeoAligner1
    # ------------------------------------------------------
    def step4_qiao_geoalign(self):

        # ---------- 4.1 QiAo 子 Solver ----------
        # base_point 默认原点（你要求）
        qiao_base_point = rg.Point3d(0.0, 0.0, 0.0)

        # length_fen 覆盖：来自主 AllDict

        # 输入端覆盖：RufuZhaQian_QiAoSolver length_fen（优先级：输入端 > DB）
        qiao_len = getattr(self, "qiao_length_fen_override", None)
        if qiao_len is None:
            qiao_len = self.all_get("RufuZhaQian_QiAoSolver__length_fen", None)
        if isinstance(qiao_len, (list, tuple)) and len(qiao_len) > 0:
            qiao_len = qiao_len[0]
        if qiao_len is not None:
            qiao_len = _safe_float(qiao_len, None)

        try:
            qsolver = RufuZhaQian_QiAoSolver_Internal(
                self.DBPath,
                qiao_base_point,
                self.Refresh,
                self.ghenv,
                length_override=qiao_len,
                FT_timber_block_uniform_length_fen=self.timber_length_fen_override,
                RufuZhaQian_QiAoSolver_length_fen=self.qiao_length_fen_override
            )
            qsolver = qsolver.run()

            self.QiAoSolver = qsolver
            self.QiAo_CutTimbers = qsolver.CutTimbers
            self.QiAo_FailTimbers = qsolver.FailTimbers if qsolver.FailTimbers is not None else []
            self.QiAo_Log = qsolver.Log if qsolver.Log is not None else []
            self.QiAo_TimberBrep = qsolver.TimberBrep
            self.QiAo_EdgeMidPoints = qsolver.EdgeMidPoints
            self.QiAo_Corner0Planes = qsolver.Corner0Planes

            self.Log.append("[STEP4] QiAoSolver 运行完成")

        except Exception as e:
            self.QiAoSolver = None
            self.QiAo_CutTimbers = None
            self.QiAo_FailTimbers = []
            self.QiAo_Log = ["[QiAoSolver][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step4_qiao_geoalign: QiAoSolver 出错: {}".format(e))
            return self

        # ---------- 4.2 PF3（主木坯） ----------
        self.PF3_BasePlane = []
        self.PF3_OriginPoint = []
        self.PF3_ResultPlane = []
        self.PF3_Log = []

        if not self.EdgeMidPoints or not self.Corner0Planes:
            self.PF3_Log = ["EdgeMidPoints 或 Corner0Planes 为空"]
            self.Log.append("[PF3] 主木坯 EdgeMidPoints/Corner0Planes 为空，跳过 PF3")
        else:
            idx_origin_raw = self.all_get("PlaneFromLists_3__IndexOrigin", 0)
            idx_plane_raw = self.all_get("PlaneFromLists_3__IndexPlane", 0)

            idx_origin_list = to_list(idx_origin_raw)
            idx_plane_list = to_list(idx_plane_raw)
            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            idx_origin_list = _broadcast_param(idx_origin_list, n, "PF3_IndexOrigin")
            idx_plane_list = _broadcast_param(idx_plane_list, n, "PF3_IndexPlane")

            pf3 = FTPlaneFromLists(wrap=True)

            for i in range(n):
                io = _safe_int(idx_origin_list[i], 0)
                ip = _safe_int(idx_plane_list[i], 0)
                try:
                    bp, op, rp, lg = pf3.build_plane(self.EdgeMidPoints, self.Corner0Planes, io, ip)
                    self.PF3_BasePlane.append(bp)
                    self.PF3_OriginPoint.append(op)
                    self.PF3_ResultPlane.append(rp)
                    for l in (lg or []):
                        self.PF3_Log.append("[{}] {}".format(i, str(l)))
                except Exception as e:
                    self.PF3_BasePlane.append(None)
                    self.PF3_OriginPoint.append(None)
                    self.PF3_ResultPlane.append(None)
                    self.PF3_Log.append("[{}] 错误: {}".format(i, e))

            self.Log.append("[PF3] 完成，数量={}".format(len(self.PF3_ResultPlane)))

        # ---------- 4.3 PF4（QiAo 子木坯） ----------
        self.PF4_BasePlane = []
        self.PF4_OriginPoint = []
        self.PF4_ResultPlane = []
        self.PF4_Log = []

        q_op = self.QiAo_EdgeMidPoints
        q_bp = self.QiAo_Corner0Planes

        if not q_op or not q_bp:
            self.PF4_Log = ["QiAo EdgeMidPoints 或 Corner0Planes 为空"]
            self.Log.append("[PF4] QiAo EdgeMidPoints/Corner0Planes 为空，跳过 PF4")
        else:
            idx_origin_raw = self.all_get("PlaneFromLists_4__IndexOrigin", 0)
            idx_plane_raw = self.all_get("PlaneFromLists_4__IndexPlane", 0)

            idx_origin_list = to_list(idx_origin_raw)
            idx_plane_list = to_list(idx_plane_raw)
            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            idx_origin_list = _broadcast_param(idx_origin_list, n, "PF4_IndexOrigin")
            idx_plane_list = _broadcast_param(idx_plane_list, n, "PF4_IndexPlane")

            pf4 = FTPlaneFromLists(wrap=True)

            for i in range(n):
                io = _safe_int(idx_origin_list[i], 0)
                ip = _safe_int(idx_plane_list[i], 0)
                try:
                    bp, op, rp, lg = pf4.build_plane(q_op, q_bp, io, ip)
                    self.PF4_BasePlane.append(bp)
                    self.PF4_OriginPoint.append(op)
                    self.PF4_ResultPlane.append(rp)
                    for l in (lg or []):
                        self.PF4_Log.append("[{}] {}".format(i, str(l)))
                except Exception as e:
                    self.PF4_BasePlane.append(None)
                    self.PF4_OriginPoint.append(None)
                    self.PF4_ResultPlane.append(None)
                    self.PF4_Log.append("[{}] 错误: {}".format(i, e))

            self.Log.append("[PF4] 完成，数量={}".format(len(self.PF4_ResultPlane)))

        # ---------- 4.4 GeoAligner::1 ----------
        self.GeoAligner1_SourceOut = []
        self.GeoAligner1_TargetOut = []
        self.GeoAligner1_MovedGeo = []
        self.GeoAligner1_Log = []

        Geo = self.QiAo_CutTimbers
        SourcePlane = self.PF4_ResultPlane
        TargetPlane = self.PF3_ResultPlane

        if Geo is None:
            self.GeoAligner1_Log.append("Geo(QiAo_CutTimbers) 为空，跳过 GeoAligner1")
            self.Log.append("[GeoAligner1] Geo 为空")
            return self
        if not SourcePlane or not TargetPlane:
            self.GeoAligner1_Log.append("SourcePlane 或 TargetPlane 为空，跳过 GeoAligner1")
            self.Log.append("[GeoAligner1] SourcePlane/TargetPlane 为空")
            return self

        # DB 参数
        flip_x_raw = self.all_get("GeoAligner_1__FlipX", 0)
        move_y_raw = self.all_get("GeoAligner_1__MoveY", 0.0)

        # 其它默认
        rotate_deg_raw = self.all_get("GeoAligner_1__RotateDeg", 0.0)
        flip_y_raw = self.all_get("GeoAligner_1__FlipY", 0)
        flip_z_raw = self.all_get("GeoAligner_1__FlipZ", 0)
        move_x_raw = self.all_get("GeoAligner_1__MoveX", 0.0)
        move_z_raw = self.all_get("GeoAligner_1__MoveZ", 0.0)

        geo_list = Geo if isinstance(Geo, (list, tuple)) else [Geo]
        sp_list = SourcePlane if isinstance(SourcePlane, (list, tuple)) else [SourcePlane]
        tp_list = TargetPlane if isinstance(TargetPlane, (list, tuple)) else [TargetPlane]

        N = max(len(geo_list), len(sp_list), len(tp_list), 1)
        geo_list = _broadcast_param(geo_list, N, "GeoAligner1_Geo")
        sp_list = _broadcast_param(sp_list, N, "GeoAligner1_SourcePlane")
        tp_list = _broadcast_param(tp_list, N, "GeoAligner1_TargetPlane")

        flip_x_list = _broadcast_param(flip_x_raw, N, "GeoAligner1_FlipX")
        move_y_list = _broadcast_param(move_y_raw, N, "GeoAligner1_MoveY")

        rotate_list = _broadcast_param(rotate_deg_raw, N, "GeoAligner1_RotateDeg")
        flip_y_list = _broadcast_param(flip_y_raw, N, "GeoAligner1_FlipY")
        flip_z_list = _broadcast_param(flip_z_raw, N, "GeoAligner1_FlipZ")
        move_x_list = _broadcast_param(move_x_raw, N, "GeoAligner1_MoveX")
        move_z_list = _broadcast_param(move_z_raw, N, "GeoAligner1_MoveZ")

        for i in range(N):
            g = geo_list[i]
            sp = sp_list[i]
            tp = tp_list[i]
            if g is None or sp is None or tp is None:
                self.GeoAligner1_SourceOut.append(None)
                self.GeoAligner1_TargetOut.append(None)
                self.GeoAligner1_MovedGeo.append(None)
                self.GeoAligner1_Log.append("[{}] 输入为空，跳过".format(i))
                continue

            rd = _safe_float(rotate_list[i], 0.0)
            fx = _safe_bool01(flip_x_list[i], 0)
            fy = _safe_bool01(flip_y_list[i], 0)
            fz = _safe_bool01(flip_z_list[i], 0)
            mx = _safe_float(move_x_list[i], 0.0)
            my = _safe_float(move_y_list[i], 0.0)
            mz = _safe_float(move_z_list[i], 0.0)

            try:
                so, to_, mg = FT_GeoAligner.align(
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
                self.GeoAligner1_SourceOut.append(so)
                self.GeoAligner1_TargetOut.append(to_)
                self.GeoAligner1_MovedGeo.append(mg)
                self.GeoAligner1_Log.append("[{}] OK".format(i))
            except Exception as e:
                self.GeoAligner1_SourceOut.append(None)
                self.GeoAligner1_TargetOut.append(None)
                self.GeoAligner1_MovedGeo.append(None)
                self.GeoAligner1_Log.append("[{}] ERROR: {}".format(i, e))

        self.Log.append("[STEP4] GeoAligner1 完成，数量={}".format(len(self.GeoAligner1_MovedGeo)))
        return self

    # ------------------------------------------------------
    # Step 5：耍头（FT_ShuaTouBuilder + PF5 + GeoAligner2）
    # ------------------------------------------------------
    def step5_shuatou_geoalign(self):

        # ========== 5.1 FT_ShuaTouBuilder ==========
        # BasePoint 默认为原点
        st_base_point = rg.Point3d(0.0, 0.0, 0.0)

        # RefPlane 未指定时，FT_ShuaTouTool 内部默认 GH XZ Plane（X=(1,0,0), Y=(0,0,1)）
        st_ref_plane = None

        st_width = self.all_get("FT_ShuaTouBuilder__WidthFen", 16.0)
        st_height = self.all_get("FT_ShuaTouBuilder__HeightFen", 15.0)
        st_offset = self.all_get("FT_ShuaTouBuilder__OffsetFen", 5.0)

        # 其余截面分°参数：若库中没有则按工具默认
        st_AH = self.all_get("FT_ShuaTouBuilder__AH_Fen", 5.0)
        st_DF = self.all_get("FT_ShuaTouBuilder__DF_Fen", 6.0)
        st_FE = self.all_get("FT_ShuaTouBuilder__FE_Fen", 5.0)
        st_EC = self.all_get("FT_ShuaTouBuilder__EC_Fen", 5.0)
        st_DG = self.all_get("FT_ShuaTouBuilder__DG_Fen", 2.0)

        try:
            (
                self.ShuaTou_CenterSectionCrv,
                self.ShuaTou_SideSectionCrv,
                self.ShuaTou_CenterSectionFace,
                self.ShuaTou_SideSectionFace,
                self.ShuaTou_OffsetSideFaces,
                self.ShuaTou_OffsetSideCrvs,
                self.ShuaTou_SideLoftFace,
                self.ShuaTou_ToolBrep,
                self.ShuaTou_RefPlanes,
                self.ShuaTou_DebugPoints,
                self.ShuaTou_DebugLines,
                self.ShuaTou_Log,
            ) = FT_ShuaTouBuilder_Internal.build(
                st_base_point,
                st_ref_plane,
                st_width,
                st_height,
                st_AH,
                st_DF,
                st_FE,
                st_EC,
                st_DG,
                st_offset
            )

            self.Log.append("[STEP5] FT_ShuaTouBuilder 完成")
            for l in (self.ShuaTou_Log or []):
                self.Log.append("[STEP5][ShuaTou] " + str(l))

        except Exception as e:
            self.ShuaTou_ToolBrep = None
            self.ShuaTou_RefPlanes = []
            self.ShuaTou_Log = ["[STEP5][ShuaTou][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step5_shuatou_geoalign: FT_ShuaTouBuilder 出错: {}".format(e))
            return self

        # ========== 5.2 PlaneFromLists::5（PF5：主木坯）==========
        self.PF5_BasePlane = []
        self.PF5_OriginPoint = []
        self.PF5_ResultPlane = []
        self.PF5_Log = []

        OriginPoints = self.EdgeMidPoints
        BasePlanes = self.Corner0Planes  # 按既有 Step2 输出

        if not OriginPoints or not BasePlanes:
            self.PF5_Log = ["EdgeMidPoints 或 Corner0Planes 为空"]
            self.Log.append("[PF5] EdgeMidPoints/Corner0Planes 为空，跳过 PF5")
            return self

        idx_origin_raw = self.all_get("PlaneFromLists_5__IndexOrigin", 0)
        idx_plane_raw = self.all_get("PlaneFromLists_5__IndexPlane", 0)
        wrap_raw = self.all_get("PlaneFromLists_5__Wrap", True)

        idx_origin_list = to_list(idx_origin_raw)
        idx_plane_list = to_list(idx_plane_raw)
        n = max(len(idx_origin_list), len(idx_plane_list), 1)
        idx_origin_list = _broadcast_param(idx_origin_list, n, "PF5_IndexOrigin")
        idx_plane_list = _broadcast_param(idx_plane_list, n, "PF5_IndexPlane")

        Wrap = bool(wrap_raw)
        pf5 = FTPlaneFromLists(wrap=Wrap)

        for i in range(n):
            io = _safe_int(idx_origin_list[i], 0)
            ip = _safe_int(idx_plane_list[i], 0)
            try:
                bp, op, rp, lg = pf5.build_plane(OriginPoints, BasePlanes, io, ip)
                self.PF5_BasePlane.append(bp)
                self.PF5_OriginPoint.append(op)
                self.PF5_ResultPlane.append(rp)
                for l in (lg or []):
                    self.PF5_Log.append("[{}] {}".format(i, str(l)))
            except Exception as e:
                self.PF5_BasePlane.append(None)
                self.PF5_OriginPoint.append(None)
                self.PF5_ResultPlane.append(None)
                self.PF5_Log.append("[{}] 错误: {}".format(i, e))

        self.Log.append("[PF5] 完成，数量={}".format(len(self.PF5_ResultPlane)))

        # ========== 5.3 GeoAligner::2（对齐耍头 ToolBrep）==========
        self.GeoAligner2_SourceOut = []
        self.GeoAligner2_TargetOut = []
        self.GeoAligner2_MovedGeo = []
        self.GeoAligner2_Log = []

        # ---- Step6: 櫨枓切削（FT_BlockCutter::2 + PF6 + PF7 + GeoAligner3）----
        self.BlockCutter2_TimberBrep = []
        self.BlockCutter2_FaceList = []
        self.BlockCutter2_PointList = []
        self.BlockCutter2_EdgeList = []
        self.BlockCutter2_CenterPoint = []
        self.BlockCutter2_CenterAxisLines = []
        self.BlockCutter2_EdgeMidPoints = []
        self.BlockCutter2_FacePlaneList = []
        self.BlockCutter2_Corner0Planes = []
        self.BlockCutter2_LocalAxesPlane = []
        self.BlockCutter2_AxisX = []
        self.BlockCutter2_AxisY = []
        self.BlockCutter2_AxisZ = []
        self.BlockCutter2_FaceDirTags = []
        self.BlockCutter2_EdgeDirTags = []
        self.BlockCutter2_Corner0EdgeDirs = []
        self.BlockCutter2_Log = []

        self.PF6_BasePlane = []
        self.PF6_OriginPoint = []
        self.PF6_ResultPlane = []
        self.PF6_Log = []

        self.PF7_BasePlane = []
        self.PF7_OriginPoint = []
        self.PF7_ResultPlane = []
        self.PF7_Log = []

        self.GeoAligner3_SourceOut = []
        self.GeoAligner3_TargetOut = []
        self.GeoAligner3_MovedGeo = []
        self.GeoAligner3_Log = []

        Geo = self.ShuaTou_ToolBrep
        if Geo is None:
            self.GeoAligner2_Log.append("Geo(ShuaTou_ToolBrep) 为空，跳过 GeoAligner2")
            self.Log.append("[GeoAligner2] Geo 为空")
            return self

        # SourcePlane：从 ShuaTou_RefPlanes 按索引取
        sp_idx = self.all_get("GeoAligner_2__SourcePlane", 0)
        sp_idx = _safe_int(sp_idx, 0)

        SourcePlane = None
        try:
            if isinstance(self.ShuaTou_RefPlanes, (list, tuple)) and len(self.ShuaTou_RefPlanes) > 0:
                sp_idx = sp_idx % len(self.ShuaTou_RefPlanes)
                SourcePlane = self.ShuaTou_RefPlanes[sp_idx]
        except:
            SourcePlane = None

        TargetPlane = None
        if self.PF5_ResultPlane:
            TargetPlane = self.PF5_ResultPlane[0]

        if SourcePlane is None or TargetPlane is None:
            self.GeoAligner2_Log.append("SourcePlane 或 TargetPlane 为空，跳过 GeoAligner2")
            self.Log.append("[GeoAligner2] SourcePlane/TargetPlane 为空")
            return self

        rotate_deg_raw = self.all_get("GeoAligner_2__RotateDeg", 0.0)
        flip_x_raw = self.all_get("GeoAligner_2__FlipX", 0)

        # 其余默认
        flip_y_raw = self.all_get("GeoAligner_2__FlipY", 0)
        flip_z_raw = self.all_get("GeoAligner_2__FlipZ", 0)
        move_x_raw = self.all_get("GeoAligner_2__MoveX", 0.0)
        move_y_raw = self.all_get("GeoAligner_2__MoveY", 0.0)
        move_z_raw = self.all_get("GeoAligner_2__MoveZ", 0.0)

        rd = _safe_float(rotate_deg_raw, 0.0)
        fx = _safe_bool01(flip_x_raw, 0)
        fy = _safe_bool01(flip_y_raw, 0)
        fz = _safe_bool01(flip_z_raw, 0)
        mx = _safe_float(move_x_raw, 0.0)
        my = _safe_float(move_y_raw, 0.0)
        mz = _safe_float(move_z_raw, 0.0)

        try:
            so, to_, mg = FT_GeoAligner.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rd,
                flip_x=fx,
                flip_y=fy,
                flip_z=fz,
                move_x=mx,
                move_y=my,
                move_z=mz,
            )
            self.GeoAligner2_SourceOut = [so]
            self.GeoAligner2_TargetOut = [to_]
            self.GeoAligner2_MovedGeo = [mg]
            self.GeoAligner2_Log = ["[0] OK"]

            self.Log.append("[STEP5] GeoAligner2 完成：SourcePlaneIdx={} RotateDeg={} FlipX={}".format(sp_idx, rd, fx))

        except Exception as e:
            self.GeoAligner2_SourceOut = [None]
            self.GeoAligner2_TargetOut = [None]
            self.GeoAligner2_MovedGeo = [None]
            self.GeoAligner2_Log = ["[0] ERROR: {}".format(e)]
            self.Log.append("[ERROR] step5_shuatou_geoalign: GeoAligner2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------
    # ==========================================================
    # Step 6：櫨枓切削（FT_BlockCutter::2 + PlaneFromLists::6/7 + GeoAligner::3）
    # ==========================================================
    def step6_ludou_blockcutter_geoalign(self):

        # ========== 6.1 FT_BlockCutter::2 ==========
        bc_len_raw = self.all_get("FT_BlockCutter_2__length_fen", 32.0)
        bc_wid_raw = self.all_get("FT_BlockCutter_2__width_fen", 32.0)
        bc_hei_raw = self.all_get("FT_BlockCutter_2__height_fen", 20.0)

        len_list = to_list(bc_len_raw)
        wid_list = to_list(bc_wid_raw)
        hei_list = to_list(bc_hei_raw)

        N = max(len(len_list), len(wid_list), len(hei_list), 1)
        len_list = _broadcast_param(len_list, N, "BC2_length_fen")
        wid_list = _broadcast_param(wid_list, N, "BC2_width_fen")
        hei_list = _broadcast_param(hei_list, N, "BC2_height_fen")

        bc_base_point = rg.Point3d(0.0, 0.0, 0.0)
        bc_ref_mode = self.all_get("FT_BlockCutter_2__reference_plane", "WorldXZ")
        bc_reference_plane = make_ref_plane(bc_ref_mode, origin=rg.Point3d(0.0, 0.0, 0.0))

        # 清空输出容器（保持 list 输出）
        self.BlockCutter2_TimberBrep = []
        self.BlockCutter2_FaceList = []
        self.BlockCutter2_PointList = []
        self.BlockCutter2_EdgeList = []
        self.BlockCutter2_CenterPoint = []
        self.BlockCutter2_CenterAxisLines = []
        self.BlockCutter2_EdgeMidPoints = []
        self.BlockCutter2_FacePlaneList = []
        self.BlockCutter2_Corner0Planes = []
        self.BlockCutter2_LocalAxesPlane = []
        self.BlockCutter2_AxisX = []
        self.BlockCutter2_AxisY = []
        self.BlockCutter2_AxisZ = []
        self.BlockCutter2_FaceDirTags = []
        self.BlockCutter2_EdgeDirTags = []
        self.BlockCutter2_Corner0EdgeDirs = []
        self.BlockCutter2_Log = []

        self.Log.append(
            "[STEP6][BLOCKCUTTER2] raw length/width/height = {} {} {}".format(bc_len_raw, bc_wid_raw, bc_hei_raw))
        self.Log.append("[STEP6][BLOCKCUTTER2] broadcast N = {}".format(N))
        self.Log.append("[STEP6][BLOCKCUTTER2] reference_plane = {}".format(bc_ref_mode))

        for i in range(N):
            bc_length_fen = _safe_float(len_list[i], 0.0)
            bc_width_fen = _safe_float(wid_list[i], 0.0)
            bc_height_fen = _safe_float(hei_list[i], 0.0)

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
                    bc_length_fen,
                    bc_width_fen,
                    bc_height_fen,
                    bc_base_point,
                    bc_reference_plane,
                )

                self.BlockCutter2_TimberBrep.append(timber_brep)
                self.BlockCutter2_FaceList.append(faces)
                self.BlockCutter2_PointList.append(points)
                self.BlockCutter2_EdgeList.append(edges)
                self.BlockCutter2_CenterPoint.append(center_pt)
                self.BlockCutter2_CenterAxisLines.append(center_axes)
                self.BlockCutter2_EdgeMidPoints.append(edge_midpts)
                self.BlockCutter2_FacePlaneList.append(face_planes)
                self.BlockCutter2_Corner0Planes.append(corner0_planes)
                self.BlockCutter2_LocalAxesPlane.append(local_axes_plane)
                self.BlockCutter2_AxisX.append(axis_x)
                self.BlockCutter2_AxisY.append(axis_y)
                self.BlockCutter2_AxisZ.append(axis_z)
                self.BlockCutter2_FaceDirTags.append(face_tags)
                self.BlockCutter2_EdgeDirTags.append(edge_tags)
                self.BlockCutter2_Corner0EdgeDirs.append(corner0_dirs)

                for l in (log_lines or []):
                    self.BlockCutter2_Log.append("[{}] {}".format(i, l))

            except Exception as e:
                self.BlockCutter2_TimberBrep.append(None)
                self.BlockCutter2_FaceList.append([])
                self.BlockCutter2_PointList.append([])
                self.BlockCutter2_EdgeList.append([])
                self.BlockCutter2_CenterPoint.append(None)
                self.BlockCutter2_CenterAxisLines.append([])
                self.BlockCutter2_EdgeMidPoints.append([])
                self.BlockCutter2_FacePlaneList.append([])
                self.BlockCutter2_Corner0Planes.append([])
                self.BlockCutter2_LocalAxesPlane.append(None)
                self.BlockCutter2_AxisX.append(None)
                self.BlockCutter2_AxisY.append(None)
                self.BlockCutter2_AxisZ.append(None)
                self.BlockCutter2_FaceDirTags.append([])
                self.BlockCutter2_EdgeDirTags.append([])
                self.BlockCutter2_Corner0EdgeDirs.append([])
                self.BlockCutter2_Log.append("[{}] 错误: {}".format(i, e))

        # ========== 6.2 PlaneFromLists::6 ==========
        self.PF6_BasePlane = None
        self.PF6_OriginPoint = None
        self.PF6_ResultPlane = None
        self.PF6_Log = []

        pf6_idx_origin = self.all_get("PlaneFromLists_6__IndexOrigin", 0)
        pf6_idx_plane = self.all_get("PlaneFromLists_6__IndexPlane", 0)
        pf_wrap = self.all_get("PlaneFromLists__Wrap", True)

        try:
            # 当 IndexOrigin / IndexPlane 为 list 时，FTPlaneFromLists 内部会对 list 做 int() 导致报错；
            # 这里用本地 _plane_from_lists_local 兼容 list 与“分支逐一取值”的语义（对应 PlaneFromLists::6 说明）
            if isinstance(pf6_idx_origin, (list, tuple)) or isinstance(pf6_idx_plane, (list, tuple)) or _is_nested_list(
                    self.BlockCutter2_EdgeMidPoints) or _is_nested_list(self.BlockCutter2_Corner0Planes):
                (
                    self.PF6_BasePlane,
                    self.PF6_OriginPoint,
                    self.PF6_ResultPlane,
                    log6
                ) = _plane_from_lists_local(
                    self.BlockCutter2_EdgeMidPoints,
                    self.BlockCutter2_Corner0Planes,
                    pf6_idx_origin,
                    pf6_idx_plane,
                    wrap=bool(pf_wrap),
                    per_branch=True
                )
            else:
                builder6 = FTPlaneFromLists(wrap=bool(pf_wrap))
                (
                    self.PF6_BasePlane,
                    self.PF6_OriginPoint,
                    self.PF6_ResultPlane,
                    log6
                ) = builder6.build_plane(
                    self.BlockCutter2_EdgeMidPoints,
                    self.BlockCutter2_Corner0Planes,
                    pf6_idx_origin,
                    pf6_idx_plane
                )
            self.PF6_Log = list(log6) if log6 is not None else []
            self.Log.append("[STEP6][PF6] 完成")

        except Exception as e:
            self.PF6_BasePlane = None
            self.PF6_OriginPoint = None
            self.PF6_ResultPlane = None
            self.PF6_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP6][PF6] 错误: {}".format(e))

        # ========== 6.3 PlaneFromLists::7 ==========
        self.PF7_BasePlane = None
        self.PF7_OriginPoint = None
        self.PF7_ResultPlane = None
        self.PF7_Log = []

        pf7_idx_origin = self.all_get("PlaneFromLists_7__IndexOrigin", 0)
        pf7_idx_plane = self.all_get("PlaneFromLists_7__IndexPlane", 0)

        try:
            # PlaneFromLists::7：IndexOrigin / IndexPlane 允许为 list（多取值）
            if isinstance(pf7_idx_origin, (list, tuple)) or isinstance(pf7_idx_plane, (list, tuple)):
                (
                    self.PF7_BasePlane,
                    self.PF7_OriginPoint,
                    self.PF7_ResultPlane,
                    log7
                ) = _plane_from_lists_local(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    pf7_idx_origin,
                    pf7_idx_plane,
                    wrap=bool(pf_wrap),
                    per_branch=False
                )
            else:
                builder7 = FTPlaneFromLists(wrap=bool(pf_wrap))
                (
                    self.PF7_BasePlane,
                    self.PF7_OriginPoint,
                    self.PF7_ResultPlane,
                    log7
                ) = builder7.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    pf7_idx_origin,
                    pf7_idx_plane
                )
            self.PF7_Log = list(log7) if log7 is not None else []
            self.Log.append("[STEP6][PF7] 完成")

        except Exception as e:
            self.PF7_BasePlane = None
            self.PF7_OriginPoint = None
            self.PF7_ResultPlane = None
            self.PF7_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP6][PF7] 错误: {}".format(e))

        # ========== 6.4 GeoAligner::3 ==========
        self.GeoAligner3_SourceOut = None
        self.GeoAligner3_TargetOut = None
        self.GeoAligner3_MovedGeo = None
        self.GeoAligner3_Log = []

        Geo = self.BlockCutter2_TimberBrep
        if Geo is None:
            self.GeoAligner3_Log.append("Geo(BlockCutter2_TimberBrep) 为空，跳过 GeoAligner3")
            self.Log.append("[STEP6][GeoAligner3] Geo 为空")
            return self

        SourcePlane = self.PF6_ResultPlane
        TargetPlane = self.PF7_ResultPlane

        # MoveZ 必须支持：GeoAligner_3__MoveZ（允许 Tree / list / 单值）
        move_z = self.all_get("GeoAligner_3__MoveZ", 0.0)
        move_x = self.all_get("GeoAligner_3__MoveX", 0.0)
        move_y = self.all_get("GeoAligner_3__MoveY", 0.0)

        rotate_deg = self.all_get("GeoAligner_3__RotateDeg", 0.0)
        flip_x = self.all_get("GeoAligner_3__FlipX", False)
        flip_y = self.all_get("GeoAligner_3__FlipY", False)
        flip_z = self.all_get("GeoAligner_3__FlipZ", False)

        try:
            # -------- Tree 分支对应模式（你当前需求）--------
            if _is_ghtree(Geo) and _is_ghtree(SourcePlane) and _is_ghtree(TargetPlane) and _is_ghtree(move_z):
                so_t, to_t, mg_t, lg = _align_tree_by_branch(
                    Geo, SourcePlane, TargetPlane, move_z,
                    RotateDeg=rotate_deg, FlipX=flip_x, FlipY=flip_y, FlipZ=flip_z,
                    MoveX=move_x, MoveY=move_y
                )
                self.GeoAligner3_SourceOut = so_t
                self.GeoAligner3_TargetOut = to_t
                self.GeoAligner3_MovedGeo = mg_t
                self.GeoAligner3_Log = lg
                self.Log.append("[STEP6][GeoAligner3] Tree 分支对位完成")

            # -------- 嵌套 list 分支模式（兼容：list[list[...]]）--------
            elif _is_nested_list(Geo) and _is_nested_list(SourcePlane) and _is_nested_list(
                    TargetPlane) and _is_nested_list(move_z):
                src_out_all, tgt_out_all, moved_all = [], [], []
                lg = []
                n_branch = min(len(Geo), len(SourcePlane), len(TargetPlane), len(move_z))
                for bi in range(n_branch):
                    geos = Geo[bi] or []
                    srcs = SourcePlane[bi] or []
                    tgts = TargetPlane[bi] or []
                    mzs = move_z[bi] or []
                    n = len(geos)
                    if n == 0:
                        src_out_all.append([]);
                        tgt_out_all.append([]);
                        moved_all.append([])
                        lg.append("[branch {}] empty Geo".format(bi))
                        continue
                    srcs = _broadcast_to_len(list(srcs), n)
                    tgts = _broadcast_to_len(list(tgts), n)
                    mzs = _broadcast_to_len(list(mzs), n)
                    so_b, to_b, mg_b = [], [], []
                    for i in range(n):
                        try:
                            mzv = float(mzs[i]) if mzs[i] is not None else 0.0
                        except:
                            mzv = 0.0
                        so, to_, mg = FT_GeoAligner.align(
                            geos[i], srcs[i], tgts[i],
                            rotate_deg=rotate_deg,
                            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
                            move_x=move_x, move_y=move_y, move_z=mzv
                        )
                        so_b.append(so);
                        to_b.append(to_);
                        mg_b.append(mg)
                    src_out_all.append(so_b);
                    tgt_out_all.append(to_b);
                    moved_all.append(mg_b)
                    lg.append("[branch {}] done n={}".format(bi, n))
                self.GeoAligner3_SourceOut = src_out_all
                self.GeoAligner3_TargetOut = tgt_out_all
                self.GeoAligner3_MovedGeo = moved_all
                self.GeoAligner3_Log = lg
                self.Log.append("[STEP6][GeoAligner3] nested-list 分支对位完成")

            # -------- 普通 list / 单值广播模式--------
            else:
                if isinstance(Geo, (list, tuple)) or isinstance(SourcePlane, (list, tuple)) or isinstance(TargetPlane,
                                                                                                          (list,
                                                                                                           tuple)) or isinstance(
                        move_z, (list, tuple)):
                    geos = list(Geo) if isinstance(Geo, (list, tuple)) else [Geo]
                    n = len(geos)
                    srcs = SourcePlane if isinstance(SourcePlane, (list, tuple)) else [SourcePlane]
                    tgts = TargetPlane if isinstance(TargetPlane, (list, tuple)) else [TargetPlane]
                    mzs = move_z if isinstance(move_z, (list, tuple)) else [move_z]

                    srcs = _broadcast_param(list(srcs), n, "SourcePlane")
                    tgts = _broadcast_param(list(tgts), n, "TargetPlane")
                    mzs = _broadcast_to_len(list(mzs), n)

                    src_out, tgt_out, moved = [], [], []
                    for i in range(n):
                        try:
                            mzv = float(mzs[i]) if mzs[i] is not None else 0.0
                        except:
                            mzv = 0.0
                        so, to_, mg = FT_GeoAligner.align(
                            geos[i], srcs[i], tgts[i],
                            rotate_deg=rotate_deg,
                            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
                            move_x=move_x, move_y=move_y, move_z=mzv
                        )
                        src_out.append(so);
                        tgt_out.append(to_);
                        moved.append(mg)
                    self.GeoAligner3_SourceOut = src_out
                    self.GeoAligner3_TargetOut = tgt_out
                    self.GeoAligner3_MovedGeo = moved
                else:
                    self.GeoAligner3_SourceOut, self.GeoAligner3_TargetOut, self.GeoAligner3_MovedGeo = FT_GeoAligner.align(
                        Geo, SourcePlane, TargetPlane,
                        rotate_deg=rotate_deg,
                        flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
                        move_x=move_x, move_y=move_y, move_z=float(move_z) if move_z is not None else 0.0
                    )

                self.Log.append("[STEP6][GeoAligner3] 完成")

        except Exception as e:
            self.GeoAligner3_SourceOut = None
            self.GeoAligner3_TargetOut = None
            self.GeoAligner3_MovedGeo = None
            self.GeoAligner3_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP6][GeoAligner3] 错误: {}".format(e))

        return self

        SourcePlane = self.PF6_ResultPlane
        TargetPlane = self.PF7_ResultPlane

        # MoveZ 必须支持：GeoAligner_3__MoveZ
        move_z = self.all_get("GeoAligner_3__MoveZ", 0.0)
        move_x = self.all_get("GeoAligner_3__MoveX", 0.0)
        move_y = self.all_get("GeoAligner_3__MoveY", 0.0)

        rotate_deg = self.all_get("GeoAligner_3__RotateDeg", 0.0)
        flip_x = self.all_get("GeoAligner_3__FlipX", False)
        flip_y = self.all_get("GeoAligner_3__FlipY", False)
        flip_z = self.all_get("GeoAligner_3__FlipZ", False)

        try:
            # 兼容：Geo 可能是 list（BlockCutter2 有多把刀），SourcePlane/TargetPlane 也可能为 list
            if isinstance(Geo, (list, tuple)) or isinstance(SourcePlane, (list, tuple)) or isinstance(TargetPlane,
                                                                                                      (list, tuple)):
                geos = list(Geo) if isinstance(Geo, (list, tuple)) else [Geo]
                n = len(geos)
                srcs = SourcePlane if isinstance(SourcePlane, (list, tuple)) else [SourcePlane]
                tgts = TargetPlane if isinstance(TargetPlane, (list, tuple)) else [TargetPlane]
                srcs = _broadcast_param(list(srcs), n, "SourcePlane")
                tgts = _broadcast_param(list(tgts), n, "TargetPlane")

                src_out, tgt_out, moved = [], [], []
                for i in range(n):
                    so, to_, mg = FT_GeoAligner.align(
                        geos[i],
                        srcs[i],
                        tgts[i],
                        rotate_deg=rotate_deg,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                        move_x=move_x,
                        move_y=move_y,
                        move_z=move_z,
                    )
                    src_out.append(so);
                    tgt_out.append(to_);
                    moved.append(mg)
                self.GeoAligner3_SourceOut = src_out
                self.GeoAligner3_TargetOut = tgt_out
                self.GeoAligner3_MovedGeo = moved
            else:
                (
                    self.GeoAligner3_SourceOut,
                    self.GeoAligner3_TargetOut,
                    self.GeoAligner3_MovedGeo
                ) = FT_GeoAligner.align(
                    Geo,
                    SourcePlane,
                    TargetPlane,
                    rotate_deg=rotate_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=move_y,
                    move_z=move_z,
                )
            self.Log.append("[STEP6][GeoAligner3] 完成")

        except Exception as e:
            self.GeoAligner3_SourceOut = None
            self.GeoAligner3_TargetOut = None
            self.GeoAligner3_MovedGeo = None
            self.GeoAligner3_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP6][GeoAligner3] 错误: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 7：泥道栱切削（BlockCutter3 + PF8/PF9 + GeoAligner4）并执行最终切木（FT_CutTimberByTools）
    # ------------------------------------------------------
    def step7_nidaogong_cut_and_final(self):

        # ========== 7.1 FT_BlockCutter::3 ==========
        bc_len_raw = self.all_get("FT_BlockCutter_3__length_fen", 32.0)
        bc_wid_raw = self.all_get("FT_BlockCutter_3__width_fen", 32.0)
        bc_hei_raw = self.all_get("FT_BlockCutter_3__height_fen", 20.0)

        # 统一为列表
        len_list = bc_len_raw if isinstance(bc_len_raw, (list, tuple)) else [bc_len_raw]
        wid_list = bc_wid_raw if isinstance(bc_wid_raw, (list, tuple)) else [bc_wid_raw]
        hei_list = bc_hei_raw if isinstance(bc_hei_raw, (list, tuple)) else [bc_hei_raw]

        N = max(len(len_list), len(wid_list), len(hei_list))
        if N <= 0:
            self.Log.append("[STEP7][BLOCKCUTTER3] N=0，跳过")
            return self

        len_list = _broadcast_to_len(len_list, N)
        wid_list = _broadcast_to_len(wid_list, N)
        hei_list = _broadcast_to_len(hei_list, N)

        # reference_plane 默认 WorldXZ（GH 的 XZ Plane）
        ref_plane = make_ref_plane("WorldXZ", origin=rg.Point3d(0.0, 0.0, 0.0))
        bc_ref_mode = "WorldXZ"
        self.Log.append(
            "[STEP7][BLOCKCUTTER3] raw length/width/height = {} {} {}".format(bc_len_raw, bc_wid_raw, bc_hei_raw))
        self.Log.append("[STEP7][BLOCKCUTTER3] broadcast N = {}".format(N))
        self.Log.append("[STEP7][BLOCKCUTTER3] reference_plane = {}".format(bc_ref_mode))

        tb_list = []
        face_list = []
        pt_list = []
        edge_list = []
        cpt_list = []
        cax_list = []
        emid_list = []
        fpl_list = []
        c0p_list = []
        lap_list = []
        axx_list = []
        axy_list = []
        axz_list = []
        ftag_list = []
        etag_list = []
        c0d_list = []
        blog_list = []

        for i in range(N):
            try:
                bc_length_fen = _safe_float(len_list[i], 0.0)
                bc_width_fen = _safe_float(wid_list[i], 0.0)
                bc_height_fen = _safe_float(hei_list[i], 0.0)

                base_point = rg.Point3d(0.0, 0.0, 0.0)

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
                    bc_length_fen,
                    bc_width_fen,
                    bc_height_fen,
                    base_point,
                    ref_plane,
                )

                print(ref_plane)

                tb_list.append(timber_brep)
                face_list.append(faces)
                pt_list.append(points)
                edge_list.append(edges)
                cpt_list.append(center_pt)
                cax_list.append(center_axes)
                emid_list.append(edge_midpts)
                fpl_list.append(face_planes)
                c0p_list.append(corner0_planes)
                lap_list.append(local_axes_plane)
                axx_list.append(axis_x)
                axy_list.append(axis_y)
                axz_list.append(axis_z)
                ftag_list.append(face_tags)
                etag_list.append(edge_tags)
                c0d_list.append(corner0_dirs)
                blog_list.append(log_lines)

                self.Log.append(
                    "[STEP7][BLOCKCUTTER3][{}] done L/W/H = {} / {} / {}".format(i, bc_length_fen, bc_width_fen,
                                                                                 bc_height_fen))

            except Exception as e:
                tb_list.append(None)
                face_list.append([])
                pt_list.append([])
                edge_list.append([])
                cpt_list.append(None)
                cax_list.append([])
                emid_list.append([])
                fpl_list.append([])
                c0p_list.append([])
                lap_list.append(None)
                axx_list.append(None)
                axy_list.append(None)
                axz_list.append(None)
                ftag_list.append([])
                etag_list.append([])
                c0d_list.append([])
                blog_list.append(["错误: {}".format(e)])
                self.Log.append("[STEP7][BLOCKCUTTER3][{}] 错误: {}".format(i, e))

        self.BlockCutter3_TimberBrep = tb_list
        self.BlockCutter3_FaceList = face_list
        self.BlockCutter3_PointList = pt_list
        self.BlockCutter3_EdgeList = edge_list
        self.BlockCutter3_CenterPoint = cpt_list
        self.BlockCutter3_CenterAxisLines = cax_list
        self.BlockCutter3_EdgeMidPoints = emid_list
        self.BlockCutter3_FacePlaneList = fpl_list
        self.BlockCutter3_Corner0Planes = c0p_list
        self.BlockCutter3_LocalAxesPlane = lap_list
        self.BlockCutter3_AxisX = axx_list
        self.BlockCutter3_AxisY = axy_list
        self.BlockCutter3_AxisZ = axz_list
        self.BlockCutter3_FaceDirTags = ftag_list
        self.BlockCutter3_EdgeDirTags = etag_list
        self.BlockCutter3_Corner0EdgeDirs = c0d_list
        self.BlockCutter3_Log = blog_list

        # ========== 7.2 PlaneFromLists::8（主木坯平面）==========
        self.PF8_BasePlane = None
        self.PF8_OriginPoint = None
        self.PF8_ResultPlane = None
        self.PF8_Log = []

        pf8_idx_origin = self.all_get("PlaneFromLists_8__IndexOrigin", 0)
        pf8_idx_plane = self.all_get("PlaneFromLists_8__IndexPlane", 0)

        try:
            boo = True
            (
                self.PF8_BasePlane,
                self.PF8_OriginPoint,
                self.PF8_ResultPlane,
                log8
            ) = _plane_from_lists_local(
                self.PointList,
                self.Corner0Planes,
                pf8_idx_origin,
                pf8_idx_plane,
                wrap=boo,
                per_branch=False
            )
            self.PF8_Log = log8
            self.Log.append("[STEP7][PF8] 完成")

        except Exception as e:
            self.PF8_BasePlane = None
            self.PF8_OriginPoint = None
            self.PF8_ResultPlane = None
            self.PF8_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP7][PF8] 错误: {}".format(e))

        # ========== 7.3 PlaneFromLists::9（泥道栱刀具平面：Tree×Tree 分支对应优先）==========
        self.PF9_BasePlane = None
        self.PF9_OriginPoint = None
        self.PF9_ResultPlane = None
        self.PF9_Log = []

        pf9_idx_origin = self.all_get("PlaneFromLists_9__IndexOrigin", 0)
        pf9_idx_plane = self.all_get("PlaneFromLists_9__IndexPlane", 0)

        try:
            boo = True

            # 若 IndexOrigin/IndexPlane 与 OriginPoints/BasePlanes 均为 Tree：
            # 按“同一路径(path)分支一一对应”，每分支取一个索引值并生成 1 个 ResultPlane
            if _is_ghtree(self.BlockCutter3_PointList) and _is_ghtree(self.BlockCutter3_Corner0Planes) and _is_ghtree(
                    pf9_idx_origin) and _is_ghtree(pf9_idx_plane):
                self.PF9_BasePlane, self.PF9_OriginPoint, self.PF9_ResultPlane, log9 = _plane_from_lists_tree_tree(
                    self.BlockCutter3_PointList,
                    self.BlockCutter3_Corner0Planes,
                    pf9_idx_origin,
                    pf9_idx_plane,
                    wrap=boo
                )
            else:
                # 兼容：列表/嵌套列表（per_branch=True：每个“分支/刀具”各取一个索引）
                (
                    self.PF9_BasePlane,
                    self.PF9_OriginPoint,
                    self.PF9_ResultPlane,
                    log9
                ) = _plane_from_lists_local(
                    self.BlockCutter3_PointList,
                    self.BlockCutter3_Corner0Planes,
                    pf9_idx_origin,
                    pf9_idx_plane,
                    wrap=boo,
                    per_branch=True
                )

            self.PF9_Log = log9
            self.Log.append("[STEP7][PF9] 完成")

        except Exception as e:
            self.PF9_BasePlane = None
            self.PF9_OriginPoint = None
            self.PF9_ResultPlane = None
            self.PF9_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP7][PF9] 错误: {}".format(e))

        # ========== 7.4 GeoAligner::4（Tree 分支对应对齐）==========
        Geo = self.BlockCutter3_TimberBrep
        if Geo is None:
            self.Log.append("[STEP7][GeoAligner4] Geo 为空")
            return self

        SourcePlane = self.PF9_ResultPlane
        TargetPlane = self.PF8_ResultPlane

        move_z = self.all_get("GeoAligner_4__MoveZ", 0.0)
        move_x = self.all_get("GeoAligner_4__MoveX", 0.0)
        move_y = self.all_get("GeoAligner_4__MoveY", 0.0)

        rotate_deg = self.all_get("GeoAligner_4__RotateDeg", 0.0)
        flip_x = self.all_get("GeoAligner_4__FlipX", False)
        flip_y = self.all_get("GeoAligner_4__FlipY", False)
        flip_z = self.all_get("GeoAligner_4__FlipZ", False)

        try:
            # -------- Tree 分支对应模式：Geo / SourcePlane / TargetPlane / MoveZ 同为 Tree --------
            if _is_ghtree(Geo) and _is_ghtree(SourcePlane) and _is_ghtree(TargetPlane) and _is_ghtree(move_z):

                dt_src_out = _ensure_datatree()
                dt_tgt_out = _ensure_datatree()
                dt_geo_out = _ensure_datatree()

                log_lines = ["[GeoAligner4] Tree branch-wise start"]

                paths = _tree_paths(Geo)
                for pth in paths:
                    geos = _tree_branch(Geo, pth)
                    srcs = _tree_branch(SourcePlane, pth)
                    tgts = _tree_branch(TargetPlane, pth)
                    mzs = _tree_branch(move_z, pth)

                    n = len(geos)
                    if n == 0:
                        log_lines.append("[GeoAligner4][{}] empty Geo branch".format(pth))
                        continue

                    srcs = _broadcast_to_len(srcs, n)
                    tgts = _broadcast_to_len(tgts, n)
                    mzs = _broadcast_to_len(mzs, n)

                    for i in range(n):
                        try:
                            _mz = mzs[i]
                            try:
                                _mz = float(_mz)
                            except:
                                _mz = 0.0

                            s_out, t_out, moved = FT_GeoAligner.align(
                                geos[i],
                                srcs[i],
                                tgts[i],
                                rotate_deg=_safe_float(rotate_deg, 0.0),
                                flip_x=bool(flip_x),
                                flip_y=bool(flip_y),
                                flip_z=bool(flip_z),
                                move_x=_safe_float(move_x, 0.0),
                                move_y=_safe_float(move_y, 0.0),
                                move_z=_mz,
                            )

                            dt_src_out.Add(s_out, pth)
                            dt_tgt_out.Add(t_out, pth)
                            dt_geo_out.Add(moved, pth)

                            log_lines.append(
                                "[GeoAligner4][{}][{}] 对位完成 BlockRotDeg={} FlipY={}".format(pth, i, rotate_deg,
                                                                                                int(bool(flip_y))))

                        except Exception as e:
                            dt_src_out.Add(None, pth)
                            dt_tgt_out.Add(None, pth)
                            dt_geo_out.Add(None, pth)
                            log_lines.append("[GeoAligner4][{}][{}] 错误: {}".format(pth, i, e))

                self.GeoAligner4_SourceOut = dt_src_out
                self.GeoAligner4_TargetOut = dt_tgt_out
                self.GeoAligner4_MovedGeo = dt_geo_out
                self.GeoAligner4_Log = log_lines

            else:
                # -------- 非 Tree：退化为列表广播 --------
                geos = Geo if isinstance(Geo, (list, tuple)) else [Geo]
                srcs = SourcePlane if isinstance(SourcePlane, (list, tuple)) else [SourcePlane]
                tgts = TargetPlane if isinstance(TargetPlane, (list, tuple)) else [TargetPlane]

                # MoveZ 可为列表或单值
                mzs = move_z if isinstance(move_z, (list, tuple)) else [move_z]

                n = max(len(geos), len(srcs), len(tgts), len(mzs))
                geos = _broadcast_to_len(geos, n)
                srcs = _broadcast_to_len(srcs, n)
                tgts = _broadcast_to_len(tgts, n)
                mzs = _broadcast_to_len(mzs, n)

                out_s = []
                out_t = []
                out_g = []
                log_lines = ["[GeoAligner4] list broadcast start (N={})".format(n)]

                for i in range(n):
                    try:
                        _mz = mzs[i]
                        try:
                            _mz = float(_mz)
                        except:
                            _mz = 0.0

                        s_out, t_out, moved = FT_GeoAligner.align(
                            geos[i],
                            srcs[i],
                            tgts[i],
                            rotate_deg=_safe_float(rotate_deg, 0.0),
                            flip_x=bool(flip_x),
                            flip_y=bool(flip_y),
                            flip_z=bool(flip_z),
                            move_x=_safe_float(move_x, 0.0),
                            move_y=_safe_float(move_y, 0.0),
                            move_z=_mz,
                        )
                        out_s.append(s_out)
                        out_t.append(t_out)
                        out_g.append(moved)
                        log_lines.append("[GeoAligner4][{}] 对位完成".format(i))
                    except Exception as e:
                        out_s.append(None)
                        out_t.append(None)
                        out_g.append(None)
                        log_lines.append("[GeoAligner4][{}] 错误: {}".format(i, e))

                self.GeoAligner4_SourceOut = out_s
                self.GeoAligner4_TargetOut = out_t
                self.GeoAligner4_MovedGeo = out_g
                self.GeoAligner4_Log = log_lines

            self.Log.append("[STEP7][GeoAligner4] 完成")

        except Exception as e:
            self.GeoAligner4_SourceOut = []
            self.GeoAligner4_TargetOut = []
            self.GeoAligner4_MovedGeo = []
            self.GeoAligner4_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP7][GeoAligner4] 错误: {}".format(e))

        # ========== 7.5 FT_CutTimberByTools（最终输出）==========
        # Timbers：主木坯 TimberBrep
        Timbers = self.TimberBrep

        def _collect_all(x):
            if x is None:
                return []
            if _is_ghtree(x):
                out = []
                for pth in _tree_paths(x):
                    out.extend([g for g in _tree_branch(x, pth) if g is not None])
                return out
            if isinstance(x, (list, tuple)):
                out = []
                for it in x:
                    out.extend(_collect_all(it))
                return out
            return [x]

        tools = []
        # FT_AlignToolToTimber::1 输出在本 Solver 中的命名为 Align1_AlignedTool（兼容旧名 AlignedTool）
        _align_tools = []
        if hasattr(self, 'AlignedTool') and self.AlignedTool:
            _align_tools = self.AlignedTool
        elif hasattr(self, 'Align1_AlignedTool') and self.Align1_AlignedTool:
            _align_tools = self.Align1_AlignedTool
        tools.extend(_collect_all(_align_tools))
        tools.extend(_collect_all(self.GeoAligner1_MovedGeo))
        tools.extend(_collect_all(self.GeoAligner2_MovedGeo))
        tools.extend(_collect_all(self.GeoAligner3_MovedGeo))
        tools.extend(_collect_all(self.GeoAligner4_MovedGeo))

        tools = [t for t in tools if t is not None]

        if Timbers is None:
            self.Final_CutTimbers = []
            self.Final_FailTimbers = []
            self.Final_Log = ["Timbers 为空，跳过 FT_CutTimberByTools"]
            self.Log.append("[STEP7][CutTimberByTools] Timbers 为空")
            return self

        if len(tools) == 0:
            self.Final_CutTimbers = [Timbers]
            self.Final_FailTimbers = []
            self.Final_Log = ["Tools 为空，返回原 Timbers"]
            self.Log.append("[STEP7][CutTimberByTools] Tools 为空")
            return self

        try:
            cutter = FT_CutTimberByTools(Timbers, tools)
            cut, fail, logc = cutter.run()

            self.Final_CutTimbers = cut
            self.Final_FailTimbers = fail
            self.Final_Log = logc

            self.Log.append("[STEP7][CutTimberByTools] 完成")

        except Exception as e:
            self.Final_CutTimbers = []
            self.Final_FailTimbers = []
            self.Final_Log = ["错误: {}".format(e)]
            self.Log.append("[STEP7][CutTimberByTools] 错误: {}".format(e))

        return self

    def run(self):

        # Step 1：数据库
        self.step1_read_db()

        # 若 All 为空：跳过后续
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        # Step 2：木坯
        self.step2_timber()

        # Step 3：端头粗削（构建 BlockCutter + 取平面 + 对位）
        self.step3_end_rough_cut()

        # Step 4：欹䫜刀（QiAo 子流程 + 对齐）
        self.step4_qiao_geoalign()

        # Step 5：耍头（FT_ShuaTouBuilder + PF5 + GeoAligner2）
        self.step5_shuatou_geoalign()

        # Step 6：櫨枓切削（FT_BlockCutter2 + PF6/PF7 + GeoAligner3）
        self.step6_ludou_blockcutter_geoalign()

        # Step 7：泥道栱切削 + 最终切木
        self.step7_nidaogong_cut_and_final()

        # ---- 最终 CutTimbers 输出策略 ----
        # 优先 Step6 的 GeoAligner3_MovedGeo；其次 Step4 的 GeoAligner1_MovedGeo；若均失败则回落主木坯
        final_cut = [g for g in (self.Final_CutTimbers or []) if g is not None]
        moved6 = [g for g in (self.GeoAligner3_MovedGeo or []) if g is not None]
        moved4 = [g for g in (self.GeoAligner1_MovedGeo or []) if g is not None]

        if len(final_cut) > 0:
            self.CutTimbers = final_cut
            self.FailTimbers = self.Final_FailTimbers or []
        elif len(moved6) > 0:
            self.CutTimbers = moved6
        elif len(moved4) > 0:
            self.CutTimbers = moved4
        elif self.TimberBrep is not None:
            self.CutTimbers = [self.TimberBrep]
        else:
            self.CutTimbers = []

        # FailTimbers：优先继承 QiAo 子 Solver 的 FailTimbers（若有）
        self.FailTimbers = self.QiAo_FailTimbers if self.QiAo_FailTimbers is not None else []

        return self


# ==============================================================
# GH Python 组件 · 输出绑定区
# ==============================================================

if __name__ == "__main__":

    # ---------- 输入优先级：组件输入端 > 数据库 > 默认 ----------
    try:
        _db = DBPath
    except:
        _db = None

    try:
        _bp = base_point
    except:
        _bp = None

    try:
        _rf = Refresh
    except:
        _rf = False

    # --- 可选输入端覆盖（不新增输入端时不会报错）---
    try:
        _tl = FT_timber_block_uniform_length_fen
    except:
        _tl = None

    try:
        _ql = RufuZhaQian_QiAoSolver_length_fen
    except:
        _ql = None

    solver = RufuZhaQianSolver(_db, _bp, _rf, ghenv, FT_timber_block_uniform_length_fen=_tl,
                               RufuZhaQian_QiAoSolver_length_fen=_ql)
    solver = solver.run()

    print(solver.GeoAligner1_MovedGeo)

    # --- 最终主输出 ---
    CutTimbers = _flatten(solver.CutTimbers)
    FailTimbers = _flatten(solver.FailTimbers)
    Log = _flatten(solver.Log)

    # --- 开发模式输出：Step1 ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = _flatten(solver.DBLog)

    # --- 开发模式输出：Step2（木坯）---
    TimberBrep = solver.TimberBrep
    FaceList = _flatten(solver.FaceList)
    PointList = _flatten(solver.PointList)
    EdgeList = _flatten(solver.EdgeList)
    CenterPoint = solver.CenterPoint
    CenterAxisLines = _flatten(solver.CenterAxisLines)
    EdgeMidPoints = _flatten(solver.EdgeMidPoints)
    FacePlaneList = _flatten(solver.FacePlaneList)
    Corner0Planes = _flatten(solver.Corner0Planes)
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = _flatten(solver.FaceDirTags)
    EdgeDirTags = _flatten(solver.EdgeDirTags)
    Corner0EdgeDirs = _flatten(solver.Corner0EdgeDirs)
    TimberLog = _flatten(solver.TimberLog)

    # --- 开发模式输出：Step3（端头粗削）---
    BlockCutter1_TimberBrep = solver.BlockCutter1_TimberBrep
    BlockCutter1_FaceList = _flatten(solver.BlockCutter1_FaceList)
    BlockCutter1_PointList = _flatten(solver.BlockCutter1_PointList)
    BlockCutter1_EdgeList = _flatten(solver.BlockCutter1_EdgeList)
    BlockCutter1_CenterPoint = solver.BlockCutter1_CenterPoint
    BlockCutter1_CenterAxisLines = _flatten(solver.BlockCutter1_CenterAxisLines)
    BlockCutter1_EdgeMidPoints = solver.BlockCutter1_EdgeMidPoints  # 注意：可能是 tree，先不 flatten
    BlockCutter1_FacePlaneList = solver.BlockCutter1_FacePlaneList  # 同上
    BlockCutter1_Corner0Planes = solver.BlockCutter1_Corner0Planes  # 同上
    BlockCutter1_LocalAxesPlane = solver.BlockCutter1_LocalAxesPlane
    BlockCutter1_AxisX = solver.BlockCutter1_AxisX
    BlockCutter1_AxisY = solver.BlockCutter1_AxisY
    BlockCutter1_AxisZ = solver.BlockCutter1_AxisZ
    BlockCutter1_FaceDirTags = _flatten(solver.BlockCutter1_FaceDirTags)
    BlockCutter1_EdgeDirTags = _flatten(solver.BlockCutter1_EdgeDirTags)
    BlockCutter1_Corner0EdgeDirs = _flatten(solver.BlockCutter1_Corner0EdgeDirs)
    BlockCutter1_Log = _flatten(solver.BlockCutter1_Log)

    PF1_BasePlane = _flatten(solver.PF1_BasePlane)
    PF1_OriginPoint = _flatten(solver.PF1_OriginPoint)
    PF1_ResultPlane = _flatten(solver.PF1_ResultPlane)
    PF1_Log = _flatten(solver.PF1_Log)

    PF2_BasePlane = _flatten(solver.PF2_BasePlane)
    PF2_OriginPoint = _flatten(solver.PF2_OriginPoint)
    PF2_ResultPlane = _flatten(solver.PF2_ResultPlane)
    PF2_Log = _flatten(solver.PF2_Log)

    Align1_AlignedTool = _flatten(solver.Align1_AlignedTool)
    Align1_XForm = _flatten(solver.Align1_XForm)
    Align1_SourcePlane = _flatten(solver.Align1_SourcePlane)
    Align1_TargetPlane = _flatten(solver.Align1_TargetPlane)
    Align1_SourcePoint = _flatten(solver.Align1_SourcePoint)
    Align1_TargetPoint = _flatten(solver.Align1_TargetPoint)
    Align1_DebugInfo = _flatten(solver.Align1_DebugInfo)

    # --- 开发模式输出：Step4（QiAo + PF3/PF4 + GeoAligner1）---
    QiAo_CutTimbers = solver.QiAo_CutTimbers
    QiAo_FailTimbers = _flatten(solver.QiAo_FailTimbers)
    QiAo_Log = _flatten(solver.QiAo_Log)
    QiAo_TimberBrep = solver.QiAo_TimberBrep
    QiAo_EdgeMidPoints = _flatten(solver.QiAo_EdgeMidPoints)
    QiAo_Corner0Planes = _flatten(solver.QiAo_Corner0Planes)

    PF3_BasePlane = _flatten(solver.PF3_BasePlane)
    PF3_OriginPoint = _flatten(solver.PF3_OriginPoint)
    PF3_ResultPlane = _flatten(solver.PF3_ResultPlane)
    PF3_Log = _flatten(solver.PF3_Log)

    PF4_BasePlane = _flatten(solver.PF4_BasePlane)
    PF4_OriginPoint = _flatten(solver.PF4_OriginPoint)
    PF4_ResultPlane = _flatten(solver.PF4_ResultPlane)
    PF4_Log = _flatten(solver.PF4_Log)

    GeoAligner1_SourceOut = _flatten(solver.GeoAligner1_SourceOut)
    GeoAligner1_TargetOut = _flatten(solver.GeoAligner1_TargetOut)
    GeoAligner1_MovedGeo = _flatten(solver.GeoAligner1_MovedGeo)
    GeoAligner1_Log = _flatten(solver.GeoAligner1_Log)

    # --- 开发模式输出：Step5（耍头 + PF5 + GeoAligner2）---
    ShuaTou_CenterSectionCrv = solver.ShuaTou_CenterSectionCrv
    ShuaTou_SideSectionCrv = solver.ShuaTou_SideSectionCrv
    ShuaTou_CenterSectionFace = solver.ShuaTou_CenterSectionFace
    ShuaTou_SideSectionFace = solver.ShuaTou_SideSectionFace
    ShuaTou_OffsetSideFaces = _flatten(solver.ShuaTou_OffsetSideFaces)
    ShuaTou_OffsetSideCrvs = _flatten(solver.ShuaTou_OffsetSideCrvs)
    ShuaTou_SideLoftFace = solver.ShuaTou_SideLoftFace
    ShuaTou_ToolBrep = solver.ShuaTou_ToolBrep
    ShuaTou_RefPlanes = _flatten(solver.ShuaTou_RefPlanes)
    ShuaTou_DebugPoints = _flatten(solver.ShuaTou_DebugPoints)
    ShuaTou_DebugLines = _flatten(solver.ShuaTou_DebugLines)
    ShuaTou_Log = _flatten(solver.ShuaTou_Log)

    PF5_BasePlane = _flatten(solver.PF5_BasePlane)
    PF5_OriginPoint = _flatten(solver.PF5_OriginPoint)
    PF5_ResultPlane = _flatten(solver.PF5_ResultPlane)
    PF5_Log = _flatten(solver.PF5_Log)

    GeoAligner2_SourceOut = _flatten(solver.GeoAligner2_SourceOut)
    GeoAligner2_TargetOut = _flatten(solver.GeoAligner2_TargetOut)
    GeoAligner2_MovedGeo = _flatten(solver.GeoAligner2_MovedGeo)
    GeoAligner2_Log = _flatten(solver.GeoAligner2_Log)

    # --- 开发模式输出：Step6（櫨枓切削：BlockCutter2 + PF6/PF7 + GeoAligner3）---
    BlockCutter2_TimberBrep = _flatten(solver.BlockCutter2_TimberBrep)
    BlockCutter2_FaceList = _flatten(solver.BlockCutter2_FaceList)
    BlockCutter2_PointList = _flatten(solver.BlockCutter2_PointList)
    BlockCutter2_EdgeList = _flatten(solver.BlockCutter2_EdgeList)
    BlockCutter2_CenterPoint = _flatten(solver.BlockCutter2_CenterPoint)
    BlockCutter2_CenterAxisLines = _flatten(solver.BlockCutter2_CenterAxisLines)
    BlockCutter2_EdgeMidPoints = _flatten(solver.BlockCutter2_EdgeMidPoints)
    BlockCutter2_FacePlaneList = _flatten(solver.BlockCutter2_FacePlaneList)
    BlockCutter2_Corner0Planes = _flatten(solver.BlockCutter2_Corner0Planes)
    BlockCutter2_LocalAxesPlane = _flatten(solver.BlockCutter2_LocalAxesPlane)
    BlockCutter2_AxisX = _flatten(solver.BlockCutter2_AxisX)
    BlockCutter2_AxisY = _flatten(solver.BlockCutter2_AxisY)
    BlockCutter2_AxisZ = _flatten(solver.BlockCutter2_AxisZ)
    BlockCutter2_FaceDirTags = _flatten(solver.BlockCutter2_FaceDirTags)
    BlockCutter2_EdgeDirTags = _flatten(solver.BlockCutter2_EdgeDirTags)
    BlockCutter2_Corner0EdgeDirs = _flatten(solver.BlockCutter2_Corner0EdgeDirs)
    BlockCutter2_Log = _flatten(solver.BlockCutter2_Log)

    PF6_BasePlane = _flatten(solver.PF6_BasePlane)
    PF6_OriginPoint = _flatten(solver.PF6_OriginPoint)
    PF6_ResultPlane = _flatten(solver.PF6_ResultPlane)
    PF6_Log = _flatten(solver.PF6_Log)

    PF7_BasePlane = _flatten(solver.PF7_BasePlane)
    PF7_OriginPoint = _flatten(solver.PF7_OriginPoint)
    PF7_ResultPlane = _flatten(solver.PF7_ResultPlane)
    PF7_Log = _flatten(solver.PF7_Log)

    GeoAligner3_SourceOut = solver.GeoAligner3_SourceOut if _is_ghtree(
        getattr(solver, 'GeoAligner3_SourceOut', None)) else _flatten(solver.GeoAligner3_SourceOut)
    GeoAligner3_TargetOut = solver.GeoAligner3_TargetOut if _is_ghtree(
        getattr(solver, 'GeoAligner3_TargetOut', None)) else _flatten(solver.GeoAligner3_TargetOut)
    GeoAligner3_MovedGeo = solver.GeoAligner3_MovedGeo if _is_ghtree(
        getattr(solver, 'GeoAligner3_MovedGeo', None)) else _flatten(solver.GeoAligner3_MovedGeo)
    GeoAligner3_Log = _flatten(solver.GeoAligner3_Log)

    # ===========================
    # Step 7 outputs
    # ===========================
    BlockCutter3_TimberBrep = _flatten(solver.BlockCutter3_TimberBrep)
    BlockCutter3_FaceList = _flatten(solver.BlockCutter3_FaceList)
    BlockCutter3_PointList = _flatten(solver.BlockCutter3_PointList)
    BlockCutter3_EdgeList = _flatten(solver.BlockCutter3_EdgeList)
    BlockCutter3_CenterPoint = _flatten(solver.BlockCutter3_CenterPoint)
    BlockCutter3_CenterAxisLines = _flatten(solver.BlockCutter3_CenterAxisLines)
    BlockCutter3_EdgeMidPoints = _flatten(solver.BlockCutter3_EdgeMidPoints)
    BlockCutter3_FacePlaneList = _flatten(solver.BlockCutter3_FacePlaneList)
    BlockCutter3_Corner0Planes = _flatten(solver.BlockCutter3_Corner0Planes)
    BlockCutter3_LocalAxesPlane = _flatten(solver.BlockCutter3_LocalAxesPlane)
    BlockCutter3_AxisX = _flatten(solver.BlockCutter3_AxisX)
    BlockCutter3_AxisY = _flatten(solver.BlockCutter3_AxisY)
    BlockCutter3_AxisZ = _flatten(solver.BlockCutter3_AxisZ)
    BlockCutter3_FaceDirTags = _flatten(solver.BlockCutter3_FaceDirTags)
    BlockCutter3_EdgeDirTags = _flatten(solver.BlockCutter3_EdgeDirTags)
    BlockCutter3_Corner0EdgeDirs = _flatten(solver.BlockCutter3_Corner0EdgeDirs)
    BlockCutter3_Log = _flatten(solver.BlockCutter3_Log)

    PF8_BasePlane = _flatten(solver.PF8_BasePlane)
    PF8_OriginPoint = _flatten(solver.PF8_OriginPoint)
    PF8_ResultPlane = _flatten(solver.PF8_ResultPlane)
    PF8_Log = _flatten(solver.PF8_Log)

    PF9_BasePlane = _flatten(solver.PF9_BasePlane)
    PF9_OriginPoint = _flatten(solver.PF9_OriginPoint)
    PF9_ResultPlane = _flatten(solver.PF9_ResultPlane)
    PF9_Log = _flatten(solver.PF9_Log)

    GeoAligner4_SourceOut = solver.GeoAligner4_SourceOut if _is_ghtree(
        getattr(solver, 'GeoAligner4_SourceOut', None)) else _flatten(solver.GeoAligner4_SourceOut)
    GeoAligner4_TargetOut = solver.GeoAligner4_TargetOut if _is_ghtree(
        getattr(solver, 'GeoAligner4_TargetOut', None)) else _flatten(solver.GeoAligner4_TargetOut)
    GeoAligner4_MovedGeo = solver.GeoAligner4_MovedGeo if _is_ghtree(
        getattr(solver, 'GeoAligner4_MovedGeo', None)) else _flatten(solver.GeoAligner4_MovedGeo)
    GeoAligner4_Log = _flatten(solver.GeoAligner4_Log)

    Final_CutTimbers = _flatten(solver.Final_CutTimbers)
    Final_FailTimbers = _flatten(solver.Final_FailTimbers)
    Final_Log = _flatten(solver.Final_Log)


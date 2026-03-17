# -*- coding: utf-8 -*-
"""ShuaTouInLineWManGong2_4PU_Solver

逐步转换版（当前实现：Step1 数据库读取 + Step2 多偏轴木料）。
主输出：CutTimbers / FailTimbers / Log。
开发模式输出：保留并可暴露全部中间成员变量。

注意：本文件结构参考 LingGongSolver.py。
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import math

try:
    import System
    from System.Collections import IEnumerable
except Exception:
    System = None
    IEnumerable = None

from yingzao.ancientArchi import (
    DBJsonReader,
    BuildTimberBlockUniform_SkewAxis_M,
    build_timber_block_uniform,
    FTPlaneFromLists,
    GeoAligner_xfm,
    FT_GongYan_CaiQi_ToolBuilder,
    JuanShaToolBuilder,
    QiAoToolSolver,
    InputHelper,
    GHPlaneFactory,
    FT_CutTimbersByTools_GH_SolidDifference,
)


try:
    import Grasshopper.Kernel.Types as ght
except Exception:
    ght = None


# ==============================================================
# 通用工具函数
# ==============================================================

def to_list(x):
    """若为 list/tuple 则直接返回，否则包装成长度为 1 的列表。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def all_to_dict(all_list):
    """All(list[tuple]) -> dict。"""
    d = {}
    if all_list is None:
        return d
    for item in all_list:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        k, v = item
        d[k] = v
    return d


def gh_plane_XZ(origin):
    """Grasshopper 的 XZ Plane：X=(1,0,0), Y=(0,0,1), Z 自动为 (0,-1,0)。"""
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def first_or_default(v, default=None):
    """若 v 为 list/tuple，则取第一个；否则直接返回；None → default。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        if len(v) == 0:
            return default
        return v[0]
    return v


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其它标量 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


def _broadcast_param(val, n, name="param"):
    """GH 风格广播：list/tuple 截断/末值补齐；标量复制到 n。"""
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


def flatten_any(x):
    """递归拍平 list/tuple/.NET IEnumerable（避免 GH 输出 System.Collections.Generic.List`1[System.Object] 套娃）。

    规则：
    - string / Point3d / Vector3d / Plane / Transform / GeometryBase 不展开
    - list/tuple/.NET IEnumerable（非字符串）递归展开
    """
    out = []
    if x is None:
        return out

    # 不展开的原子类型
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]

    try:
        if isinstance(x, (rg.GeometryBase,)):
            return [x]
    except Exception:
        pass

    # list/tuple
    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out

    # .NET IEnumerable（排除 string）
    if IEnumerable is not None:
        try:
            if isinstance(x, IEnumerable) and not isinstance(x, (str,)):
                for it in x:
                    out.extend(flatten_any(it))
                return out
        except Exception:
            pass

    return [x]


def _is_gh_tree(x):
    """粗略判断 GH DataTree：具备 BranchCount / Branch 方法即可。"""
    if x is None:
        return False
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


def _tree_to_branches(tree):
    """GH DataTree -> list[list]（每个分支转为 python list）。"""
    branches = []
    if not _is_gh_tree(tree):
        return branches
    try:
        bc = int(tree.BranchCount)
    except Exception:
        bc = 0
    for i in range(bc):
        try:
            br = tree.Branch(i)
            if br is None:
                branches.append([])
            else:
                # GH 分支通常是 IList
                branches.append([br[j] for j in range(int(br.Count))])
        except Exception:
            branches.append([])
    return branches


def _wrap_index(i, n, wrap=True):
    if n <= 0:
        return None
    try:
        ii = int(i)
    except Exception:
        return None
    if wrap:
        return ii % n
    if 0 <= ii < n:
        return ii
    return None


def _list_item(lst, idx, wrap=True):
    """GH List Item：按索引取值（可 wrap）。"""
    if lst is None:
        return None
    seq = list(lst) if isinstance(lst, (list, tuple)) else [lst]
    n = len(seq)
    ii = _wrap_index(idx, n, wrap=wrap)
    if ii is None:
        return None
    return seq[ii]


def _as_branch_list(x):
    """把输入转成 branches：Tree -> branches；其它 -> [to_list(x)]。"""
    if _is_gh_tree(x):
        return _tree_to_branches(x)
    return [to_list(x)]


def _graft_any(x):
    """最小化 Graft Tree 适配。

    目标：确保“每个 item 落在独立分支”。

    - 若 x 为 GH Tree：逐 item 变为独立分支（丢弃原分支结构，仅保证 graft 语义）。
    - 若 x 为 list/tuple：每个元素单独分支。
    - 其它标量：单分支单元素。

    返回：list[list] 形式的 branches。
    """
    if x is None:
        return []
    if _is_gh_tree(x):
        flat_items = []
        for br in _tree_to_branches(x):
            for it in br:
                flat_items.append(it)
        return [[it] for it in flat_items]
    if isinstance(x, (list, tuple)):
        return [[it] for it in list(x)]
    return [[x]]


def _gh_path_equal(a, b):
    """尽量稳健地比较 GH_Path。"""
    if a is b:
        return True
    if a is None or b is None:
        return False
    try:
        # GH_Path 常见有 Indices
        ai = getattr(a, "Indices", None)
        bi = getattr(b, "Indices", None)
        if ai is not None and bi is not None:
            return list(ai) == list(bi)
    except Exception:
        pass
    try:
        return str(a) == str(b)
    except Exception:
        return False


def _tree_item(tree, path, index, wrap=False):
    """GH Tree Item：先按 Path 定位分支，再按 Index 取元素。"""
    if tree is None:
        return None
    if not _is_gh_tree(tree):
        # 退化：把它当成单分支 list
        seq = to_list(tree)
        ii = _wrap_index(index, len(seq), wrap=wrap)
        return seq[ii] if ii is not None else None

    # 1) 找 branch id
    branch_i = 0
    try:
        if path is None:
            branch_i = 0
        elif isinstance(path, int):
            branch_i = int(path)
        else:
            # 尝试按 Paths 匹配
            if hasattr(tree, "Paths"):
                paths = list(getattr(tree, "Paths"))
                for i, p in enumerate(paths):
                    if _gh_path_equal(p, path):
                        branch_i = i
                        break
            else:
                # 退而求其次：遍历 tree.Path(i)
                bc = int(getattr(tree, "BranchCount", 0))
                for i in range(bc):
                    p = tree.Path(i)
                    if _gh_path_equal(p, path):
                        branch_i = i
                        break
    except Exception:
        branch_i = 0

    # 2) 取 branch
    try:
        br = tree.Branch(branch_i)
        seq = [br[j] for j in range(int(br.Count))] if br is not None else []
    except Exception:
        seq = []

    ii = _wrap_index(index, len(seq), wrap=wrap)
    return seq[ii] if ii is not None else None


def _max_len(*seqs):
    m = 0
    for s in seqs:
        try:
            m = max(m, len(s))
        except Exception:
            pass
    return m


# ==============================================================
# Step3 子组件：ShuaTou（耍头刀具）—— 内嵌 Builder（与 GH 组件一致）
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

    @staticmethod
    def build(base_point, ref_plane,
              width_fen, height_fen,
              AH_fen, DF_fen, FE_fen, EC_fen,
              DG_fen, offset_fen):

        # -------- 默认值 --------
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
        A, B, C, D = ShuaTouBuilder._build_base_rect(base_point, ref_plane, width_fen, height_fen)
        dbg_pts.extend([A, B, C, D])

        # ------------------------------------------------------
        # 2. 构建关键点
        # ------------------------------------------------------
        H, F, E, G, J, K, I, L, aux_lines = ShuaTouBuilder._build_key_points(
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

        # ------------------------------------------------------
        # 10. Join 所有面 → ToolBrep
        # ------------------------------------------------------
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

        I = ShuaTouBuilder._perpendicular_foot(H, A, F)

        HL = rg.Line(H, H + (F - A) * 200)
        rc3, t5, t6 = rg.Intersect.Intersection.LineLine(HL, GJ)
        L = HL.PointAt(t5) if rc3 else H

        aux = [
            AF.ToNurbsCurve(),
            GJ.ToNurbsCurve(),
            HL.ToNurbsCurve(),
            BC.ToNurbsCurve(),
        ]
        return H, F, E, G, J, K, I, L, aux

    @staticmethod
    def _perpendicular_foot(P, A, B):
        line = rg.Line(A, B)
        t = line.ClosestParameter(P)
        return line.PointAt(t)


# ==============================================================
# 主 Solver 类 —— 耍头与慢栱相列一 ShuaTouInLineWManGong1_4PU
# ==============================================================

class ShuaTouInLineWManGong2_4PU_Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        # 输入缓存
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # 额外输入端缓存（若 GH 组件有这些输入端，则在 __main__ 里注入到这里）
        self._in_BlockCutter_1__length_fen = None
        self._in_BlockCutter_1__width_fen = None
        self._in_BlockCutter_1__height_fen = None
        self._in_BlockCutter_1__reference_plane = None

        self._in_GeoAligner_3__SourcePlane = None
        self._in_GeoAligner_3__TargetPlane_path = None
        self._in_GeoAligner_3__TargetPlane_index = None
        self._in_GeoAligner_3__RotateDeg = None
        self._in_GeoAligner_3__FlipX = None
        self._in_GeoAligner_3__FlipY = None
        self._in_GeoAligner_3__FlipZ = None
        self._in_GeoAligner_3__MoveX = None
        self._in_GeoAligner_3__MoveY = None
        self._in_GeoAligner_3__MoveZ = None

        # Step 6（BlockCutter::2 + GeoAligner::4）额外输入端缓存
        self._in_BlockCutter_2__length_fen = None
        self._in_BlockCutter_2__width_fen = None
        self._in_BlockCutter_2__height_fen = None
        self._in_BlockCutter_2__reference_plane = None
        self._in_GeoAligner_4__SourcePlane = None
        self._in_GeoAligner_4__RotateDeg = None
        self._in_GeoAligner_4__FlipX = None
        self._in_GeoAligner_4__FlipY = None
        self._in_GeoAligner_4__FlipZ = None
        self._in_GeoAligner_4__MoveX = None
        self._in_GeoAligner_4__MoveY = None
        self._in_GeoAligner_4__MoveZ = None

        # Step 7（BlockCutter::3 + GeoAligner::5）额外输入端缓存
        self._in_BlockCutter_3__length_fen = None
        self._in_BlockCutter_3__width_fen = None
        self._in_BlockCutter_3__height_fen = None
        self._in_BlockCutter_3__reference_plane = None

        self._in_GeoAligner_5__SourcePlane = None
        self._in_GeoAligner_5__TargetPlane_path = None
        self._in_GeoAligner_5__TargetPlane_index = None
        self._in_GeoAligner_5__RotateDeg = None
        self._in_GeoAligner_5__FlipX = None
        self._in_GeoAligner_5__FlipY = None
        self._in_GeoAligner_5__FlipZ = None
        self._in_GeoAligner_5__MoveX = None
        self._in_GeoAligner_5__MoveY = None
        self._in_GeoAligner_5__MoveZ = None

        # Step 8（BlockCutter::4 + GeoAligner::6）额外输入端缓存
        self._in_BlockCutter_4__length_fen = None
        self._in_BlockCutter_4__width_fen = None
        self._in_BlockCutter_4__height_fen = None
        self._in_BlockCutter_4__reference_plane = None

        self._in_GeoAligner_6__SourcePlane = None
        self._in_GeoAligner_6__TargetPlane_base_path = None
        self._in_GeoAligner_6__TargetPlane_base_index = None
        self._in_GeoAligner_6__TargetPlane_origin = None
        self._in_GeoAligner_6__RotateDeg = None
        self._in_GeoAligner_6__FlipX = None
        self._in_GeoAligner_6__FlipY = None
        self._in_GeoAligner_6__FlipZ = None
        self._in_GeoAligner_6__MoveX = None
        self._in_GeoAligner_6__MoveY = None
        self._in_GeoAligner_6__MoveZ = None

        # Step 9（GongYan + PlaneFromLists::4 + GeoAligner::7）额外输入端缓存
        self._in_GongYan__BasePoint = None
        self._in_GongYan__SectionPlane = None
        self._in_GongYan__EM_fen = None
        self._in_GongYan__EC_fen = None
        self._in_GongYan__AI_fen = None
        self._in_GongYan__AG_fen = None
        self._in_GongYan__JR_fen = None
        self._in_GongYan__HK_fen = None
        self._in_GongYan__Thickness = None
        self._in_GongYan__OffsetDist = None

        self._in_PlaneFromLists_4__IndexOrigin = None
        self._in_PlaneFromLists_4__IndexPlane = None
        self._in_PlaneFromLists_4__Wrap = None

        self._in_GeoAligner_7__SourcePlane = None
        self._in_GeoAligner_7__RotateDeg = None
        self._in_GeoAligner_7__FlipX = None
        self._in_GeoAligner_7__FlipY = None
        self._in_GeoAligner_7__FlipZ = None
        self._in_GeoAligner_7__MoveX = None
        self._in_GeoAligner_7__MoveY = None
        self._in_GeoAligner_7__MoveZ = None

        # Step 10（QiAOTool::2 + PlaneFromLists::5 + PlaneFromLists::6 + GeoAligner::8）额外输入端缓存
        self._in_QiAOTool_2__length_fen = None
        self._in_QiAOTool_2__width_fen = None
        self._in_QiAOTool_2__height_fen = None
        self._in_QiAOTool_2__base_point = None
        self._in_QiAOTool_2__timber_ref_plane_mode = None
        self._in_QiAOTool_2__qi_height = None
        self._in_QiAOTool_2__sha_width = None
        self._in_QiAOTool_2__qi_offset_fen = None
        self._in_QiAOTool_2__extrude_length = None
        self._in_QiAOTool_2__extrude_positive = None
        self._in_QiAOTool_2__qi_ref_plane_mode = None

        self._in_PlaneFromLists_6__IndexOrigin = None
        self._in_PlaneFromLists_6__IndexPlane = None
        self._in_PlaneFromLists_6__Wrap = None

        self._in_PlaneFromLists_5__IndexOrigin = None
        self._in_PlaneFromLists_5__IndexPlane = None
        self._in_PlaneFromLists_5__Wrap = None

        self._in_GeoAligner_8__RotateDeg = None
        self._in_GeoAligner_8__FlipX = None
        self._in_GeoAligner_8__FlipY = None
        self._in_GeoAligner_8__FlipZ = None
        self._in_GeoAligner_8__MoveX = None
        self._in_GeoAligner_8__MoveY = None
        self._in_GeoAligner_8__MoveZ = None

        # Step 11（PlaneFromLists::7 + Juansha + GeoAligner::9）额外输入端缓存
        self._in_PlaneFromLists_7__IndexOrigin = None
        self._in_PlaneFromLists_7__IndexPlane = None
        self._in_PlaneFromLists_7__Wrap = None

        self._in_Juansha__HeightFen = None
        self._in_Juansha__LengthFen = None
        self._in_Juansha__DivCount = None
        self._in_Juansha__ThicknessFen = None
        self._in_Juansha__SectionPlane = None
        self._in_Juansha__PositionPoint = None

        self._in_GeoAligner_9__RotateDeg = None
        self._in_GeoAligner_9__FlipX = None
        self._in_GeoAligner_9__FlipY = None
        self._in_GeoAligner_9__FlipZ = None
        self._in_GeoAligner_9__MoveX = None
        self._in_GeoAligner_9__MoveY = None
        self._in_GeoAligner_9__MoveZ = None

        # Step 12（BlockCutter::5 + GeoAligner::10）额外输入端缓存
        self._in_BlockCutter_5__length_fen = None
        self._in_BlockCutter_5__width_fen = None
        self._in_BlockCutter_5__height_fen = None
        self._in_BlockCutter_5__reference_plane = None

        self._in_GeoAligner_10__SourcePlane = None
        self._in_GeoAligner_10__RotateDeg = None
        self._in_GeoAligner_10__FlipX = None
        self._in_GeoAligner_10__FlipY = None
        self._in_GeoAligner_10__FlipZ = None
        self._in_GeoAligner_10__MoveX = None
        self._in_GeoAligner_10__MoveY = None
        self._in_GeoAligner_10__MoveZ = None

        # Step 1：数据库读取相关成员
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step 2：木坯几何输出成员（与 BuildTimberBlockUniform_SkewAxis_M 输出保持一致）
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

        # Step2：Skew 扩展输出
        self.Skew_A = None
        self.Skew_Point_B = None
        self.Skew_Point_C = None
        self.Skew_Planes = None
        self.Skew_ExtraPoints_GF_EH = None

        # --------------------------------------------------
        # Step 3：ShuaTou + PlaneFromLists::1 + GeoAligner::1
        # --------------------------------------------------
        # ShuaTou
        self.ShuaTou__CenterSectionCrv = None
        self.ShuaTou__SideSectionCrv = None
        self.ShuaTou__CenterSectionFace = None
        self.ShuaTou__SideSectionFace = None
        self.ShuaTou__OffsetSideFaces = None
        self.ShuaTou__OffsetSideCrvs = None
        self.ShuaTou__SideLoftFace = None
        self.ShuaTou__ToolBrep = None
        self.ShuaTou__RefPlanes = None
        self.ShuaTou__DebugPoints = None
        self.ShuaTou__DebugLines = None
        self.ShuaTou__Log = []

        # PlaneFromLists::1
        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        # List Item (ShuaTou.RefPlanes)
        self.ListItem_ShuaTouRefPlanes__Item = None
        self.ListItem_ShuaTouRefPlanes__Log = []

        # GeoAligner::1
        self.GeoAligner_1__SourceOut = None
        self.GeoAligner_1__TargetOut = None
        self.GeoAligner_1__MovedGeo = None
        self.GeoAligner_1__TransformOut = None
        self.GeoAligner_1__Log = []

        # --------------------------------------------------
        # Step 4：QiAOTool::1 + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::2
        # --------------------------------------------------
        # QiAOTool::1
        self.QiAOTool_1__CutTimbers = None
        self.QiAOTool_1__FailTimbers = None
        self.QiAOTool_1__Log = []
        self.QiAOTool_1__EdgeMidPoints = None
        self.QiAOTool_1__Corner0Planes = None

        self.QiAOTool_1__TimberBrep = None
        self.QiAOTool_1__ToolBrep = None
        self.QiAOTool_1__AlignedTool = None
        self.QiAOTool_1__RefPlanes = None
        self.QiAOTool_1__PFL1_ResultPlane = None
        self.QiAOTool_1__QiAo_FacePlane = None

        # PlaneFromLists::2（主木坯 -> TargetPlane）
        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        # PlaneFromLists::3（QiAOTool -> SourcePlane）
        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        # GeoAligner::2
        self.GeoAligner_2__SourceOut = None
        self.GeoAligner_2__TargetOut = None
        self.GeoAligner_2__MovedGeo = None
        self.GeoAligner_2__TransformOut = None
        self.GeoAligner_2__Log = []

        # --------------------------------------------------
        # Step 5：BlockCutter::1 + GeoAligner::3
        # --------------------------------------------------
        # BlockCutter::1
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

        # Graft Tree
        self.Step5__GraftedGeo = None

        # List Item（FacePlaneList -> SourcePlane）
        self.GeoAligner_3__SourcePlane_Item = None

        # Tree Item（Skew_Planes -> TargetPlane）
        self.GeoAligner_3__TargetPlane_Item = None

        # GeoAligner::3
        self.GeoAligner_3__SourceOut = None
        self.GeoAligner_3__TargetOut = None
        self.GeoAligner_3__MovedGeo = None
        self.GeoAligner_3__TransformOut = None
        self.GeoAligner_3__Log = []

        # --------------------------------------------------
        # Step 6：BlockCutter::2 + GeoAligner::4
        # --------------------------------------------------
        # BlockCutter::2
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

        # List Item（FacePlaneList -> SourcePlane）
        self.GeoAligner_4__SourcePlane_Item = None

        # GeoAligner::4
        self.GeoAligner_4__SourceOut = None
        self.GeoAligner_4__TargetOut = None
        self.GeoAligner_4__MovedGeo = None
        self.GeoAligner_4__TransformOut = None
        self.GeoAligner_4__Log = []

        # --------------------------------------------------
        # Step 7：BlockCutter::3 + GeoAligner::5
        # --------------------------------------------------
        # BlockCutter::3
        self.BlockCutter_3__TimberBrep = None
        self.BlockCutter_3__FaceList = []
        self.BlockCutter_3__PointList = []
        self.BlockCutter_3__EdgeList = []
        self.BlockCutter_3__CenterPoint = None
        self.BlockCutter_3__CenterAxisLines = []
        self.BlockCutter_3__EdgeMidPoints = []
        self.BlockCutter_3__FacePlaneList = []
        self.BlockCutter_3__Corner0Planes = []
        self.BlockCutter_3__LocalAxesPlane = None
        self.BlockCutter_3__AxisX = None
        self.BlockCutter_3__AxisY = None
        self.BlockCutter_3__AxisZ = None
        self.BlockCutter_3__FaceDirTags = []
        self.BlockCutter_3__EdgeDirTags = []
        self.BlockCutter_3__Corner0EdgeDirs = []
        self.BlockCutter_3__Log = []

        # Step7：可选 Graft（确保 GeoAligner 对齐结果分支数与 Geo 数量一致）
        self.Step7__GraftedGeo = None

        # List Item（FacePlaneList -> SourcePlane）
        self.GeoAligner_5__SourcePlane_Item = None

        # Tree Item（Skew_Planes -> TargetPlane）
        self.GeoAligner_5__TargetPlane_Item = None

        # GeoAligner::5
        self.GeoAligner_5__SourceOut = None
        self.GeoAligner_5__TargetOut = None
        self.GeoAligner_5__MovedGeo = None
        self.GeoAligner_5__TransformOut = None
        self.GeoAligner_5__Log = []

        # --------------------------------------------------
        # Step 8：BlockCutter::4 + GeoAligner::6
        # --------------------------------------------------
        # BlockCutter::4
        self.BlockCutter_4__TimberBrep = None
        self.BlockCutter_4__FaceList = []
        self.BlockCutter_4__PointList = []
        self.BlockCutter_4__EdgeList = []
        self.BlockCutter_4__CenterPoint = None
        self.BlockCutter_4__CenterAxisLines = []
        self.BlockCutter_4__EdgeMidPoints = []
        self.BlockCutter_4__FacePlaneList = []
        self.BlockCutter_4__Corner0Planes = []
        self.BlockCutter_4__LocalAxesPlane = None
        self.BlockCutter_4__AxisX = None
        self.BlockCutter_4__AxisY = None
        self.BlockCutter_4__AxisZ = None
        self.BlockCutter_4__FaceDirTags = []
        self.BlockCutter_4__EdgeDirTags = []
        self.BlockCutter_4__Corner0EdgeDirs = []
        self.BlockCutter_4__Log = []

        # List Item（FacePlaneList -> SourcePlane）
        self.GeoAligner_6__SourcePlane_Item = None

        # Tree Item + List Item + Plane Origin（Skew_Planes + Skew_Point_C -> TargetPlane）
        self.GeoAligner_6__TargetPlane_BasePlane_Item = None
        self.GeoAligner_6__TargetPlane_OriginPoint_Item = None
        self.GeoAligner_6__TargetPlane_Item = None

        # GeoAligner::6
        self.GeoAligner_6__SourceOut = None
        self.GeoAligner_6__TargetOut = None
        self.GeoAligner_6__MovedGeo = None
        self.GeoAligner_6__TransformOut = None
        self.GeoAligner_6__Log = []


        # --------------------------------------------------
        # Step 9：GongYan + PlaneFromLists::4 + GeoAligner::7
        # --------------------------------------------------
        # GongYan
        self.GongYan__ToolBrep = None
        self.GongYan__SectionCurve = None
        self.GongYan__SectionFace = None
        self.GongYan__LeftCurve = None
        self.GongYan__RightCurve = None
        self.GongYan__SymmetryAxis = None
        self.GongYan__AllPoints = None
        self.GongYan__SectionPlanes = None
        self.GongYan__Log = []

        # PlaneFromLists::4
        self.PlaneFromLists_4__BasePlane = None
        self.PlaneFromLists_4__OriginPoint = None
        self.PlaneFromLists_4__ResultPlane = None
        self.PlaneFromLists_4__Log = []

        # List Item（GongYan.SectionPlanes -> GeoAligner::7.SourcePlane）
        self.GeoAligner_7__SourcePlane_Item = None

        # GeoAligner::7
        self.GeoAligner_7__SourceOut = None
        self.GeoAligner_7__TargetOut = None
        self.GeoAligner_7__MovedGeo = None
        self.GeoAligner_7__TransformOut = None
        self.GeoAligner_7__Log = []

        # --------------------------------------------------
        # Step 10：QiAOTool::2 + PlaneFromLists::5 + PlaneFromLists::6 + GeoAligner::8
        # --------------------------------------------------
        # QiAOTool::2
        self.QiAOTool_2__CutTimbers = None
        self.QiAOTool_2__FailTimbers = None
        self.QiAOTool_2__Log = []
        self.QiAOTool_2__EdgeMidPoints = None
        self.QiAOTool_2__Corner0Planes = None

        # 其它调试输出（若 solver 提供）
        self.QiAOTool_2__TimberBrep = None
        self.QiAOTool_2__ToolBrep = None
        self.QiAOTool_2__AlignedTool = None
        self.QiAOTool_2__RefPlanes = None
        self.QiAOTool_2__PFL1_ResultPlane = None
        self.QiAOTool_2__QiAo_FacePlane = None

        # PlaneFromLists::6（QiAOTool::2 -> SourcePlane）
        self.PlaneFromLists_6__BasePlane = None
        self.PlaneFromLists_6__OriginPoint = None
        self.PlaneFromLists_6__ResultPlane = None
        self.PlaneFromLists_6__Log = []

        # PlaneFromLists::5（BuildTimberBlockUniform_SkewAxis_M -> TargetPlane）
        self.PlaneFromLists_5__BasePlane = None
        self.PlaneFromLists_5__OriginPoint = None
        self.PlaneFromLists_5__ResultPlane = None
        self.PlaneFromLists_5__Log = []

        # GeoAligner::8
        self.GeoAligner_8__SourceOut = None
        self.GeoAligner_8__TargetOut = None
        self.GeoAligner_8__MovedGeo = None
        self.GeoAligner_8__TransformOut = None
        self.GeoAligner_8__Log = []

        # --------------------------------------------------
        # Step 11：PlaneFromLists::7 + Juansha + GeoAligner::9
        # --------------------------------------------------
        # PlaneFromLists::7
        self.PlaneFromLists_7__BasePlane = None
        self.PlaneFromLists_7__OriginPoint = None
        self.PlaneFromLists_7__ResultPlane = None
        self.PlaneFromLists_7__Log = []

        # Juansha
        self.Juansha__ToolBrep = None
        self.Juansha__HL_Intersection = None
        self.Juansha__SectionEdges = None
        self.Juansha__HeightFacePlane = None
        self.Juansha__LengthFacePlane = None
        self.Juansha__Log = []

        # GeoAligner::9
        self.GeoAligner_9__SourceOut = None
        self.GeoAligner_9__TargetOut = None
        self.GeoAligner_9__MovedGeo = None
        self.GeoAligner_9__TransformOut = None
        self.GeoAligner_9__Log = []

        # --------------------------------------------------
        # Step 12：BlockCutter::5 + GeoAligner::10
        # --------------------------------------------------
        # BlockCutter::5
        self.BlockCutter_5__TimberBrep = None
        self.BlockCutter_5__FaceList = []
        self.BlockCutter_5__PointList = []
        self.BlockCutter_5__EdgeList = []
        self.BlockCutter_5__CenterPoint = None
        self.BlockCutter_5__CenterAxisLines = []
        self.BlockCutter_5__EdgeMidPoints = []
        self.BlockCutter_5__FacePlaneList = []
        self.BlockCutter_5__Corner0Planes = []
        self.BlockCutter_5__LocalAxesPlane = None
        self.BlockCutter_5__AxisX = None
        self.BlockCutter_5__AxisY = None
        self.BlockCutter_5__AxisZ = None
        self.BlockCutter_5__FaceDirTags = []
        self.BlockCutter_5__EdgeDirTags = []
        self.BlockCutter_5__Corner0EdgeDirs = []
        self.BlockCutter_5__Log = []

        # List Item（FacePlaneList -> SourcePlane）
        self.GeoAligner_10__SourcePlane_Item = None

        # GeoAligner::10
        self.GeoAligner_10__SourceOut = None
        self.GeoAligner_10__TargetOut = None
        self.GeoAligner_10__MovedGeo = None
        self.GeoAligner_10__TransformOut = None
        self.GeoAligner_10__Log = []

        # --------------------------------------------------
        # Step 13：CutTimbersByTools（Timbers=SkewAxis TimberBrep, Tools=GeoAligner::1~10 MovedGeo 列表）
        # --------------------------------------------------
        self.CutTimbersByTools__Timbers = None
        self.CutTimbersByTools__Tools = None
        self.CutTimbersByTools__CutTimbers = None
        self.CutTimbersByTools__FailTimbers = None
        self.CutTimbersByTools__Log = []

        # 最终主输出（占位）
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 便捷取值（输入 > DB > default）
    # ------------------------------------------------------
    def all_get(self, key, default=None, prefer_input=None):
        """参数优先级：prefer_input(组件输入端传入的具体值) > AllDict > default"""
        if prefer_input is not None:
            return prefer_input
        if self.AllDict and key in self.AllDict:
            return self.AllDict.get(key, default)
        return default

    # ------------------------------------------------------
    # Step 1：数据库读取（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="ShuaTouInLineWManGong2_4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv,
            )
            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成")
            for l in (self.DBLog or []):
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 7：BlockCutter::3 + GeoAligner::5
    # ------------------------------------------------------
    def step7_blockcutter_3_geoaligner_5(self,
                                        BlockCutter_3__length_fen=None,
                                        BlockCutter_3__width_fen=None,
                                        BlockCutter_3__height_fen=None,
                                        base_point=None,
                                        reference_plane=None,
                                        GeoAligner_5__SourcePlane=None,
                                        GeoAligner_5__TargetPlane_path=None,
                                        GeoAligner_5__TargetPlane_index=None,
                                        GeoAligner_5__RotateDeg=None,
                                        GeoAligner_5__FlipX=None,
                                        GeoAligner_5__FlipY=None,
                                        GeoAligner_5__FlipZ=None,
                                        GeoAligner_5__MoveX=None,
                                        GeoAligner_5__MoveY=None,
                                        GeoAligner_5__MoveZ=None):
        """严格按图连线实现 Step7。

        组件链：
          BlockCutter::3 -> List Item(FacePlaneList -> SourcePlane)
                        -> Tree Item(Skew_Planes -> TargetPlane)
                        -> GeoAligner::5

        关键约束：
        - 禁止重复读库；参数优先级：输入端 > AllDict > 默认。
        - BlockCutter 三维尺寸支持多值：按索引位置对齐（GH 广播：短列表末值补齐）。
        - Tree Item：Path/Index 支持 list/tree，按 GH 广播逐项取值。
        - GeoAligner::5 的 MovedGeo 输出在绑定时必须彻底 flatten。
        """

        # ========== Step 7A：BlockCutter::3 ==========
        try:
            # base_point：输入端 > 默认原点
            bp_in = base_point
            if bp_in is None:
                bp_in = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp_in, rg.Point):
                bp_in = bp_in.Location

            # reference_plane：输入端 > DB > 默认 GH XZ Plane
            rp_in = self.all_get(
                "BlockCutter_3__reference_plane",
                None,
                prefer_input=reference_plane,
            )
            if rp_in is None:
                rp_in = gh_plane_XZ(bp_in)

            # length/width/height：输入端 > DB > 默认
            length_fen_in = self.all_get(
                "BlockCutter_3__length_fen",
                32.0,
                prefer_input=BlockCutter_3__length_fen,
            )
            width_fen_in = self.all_get(
                "BlockCutter_3__width_fen",
                32.0,
                prefer_input=BlockCutter_3__width_fen,
            )
            height_fen_in = self.all_get(
                "BlockCutter_3__height_fen",
                20.0,
                prefer_input=BlockCutter_3__height_fen,
            )

            def _to_float_safe(x, d):
                try:
                    return float(x) if x is not None else float(d)
                except Exception:
                    return float(d)

            def _as_scalar_list(v, default_scalar):
                """把输入转换为一维标量列表（支持 tree/嵌套 list）。"""
                if v is None:
                    return [float(default_scalar)]
                if _is_gh_tree(v) or isinstance(v, (list, tuple)):
                    flat = flatten_any(v)
                    if len(flat) == 0:
                        return [float(default_scalar)]
                    return [_to_float_safe(it, default_scalar) for it in flat]
                return [_to_float_safe(v, default_scalar)]

            L = _as_scalar_list(length_fen_in, 32.0)
            W = _as_scalar_list(width_fen_in, 32.0)
            H = _as_scalar_list(height_fen_in, 20.0)
            n = max(len(L), len(W), len(H), 1)

            Lb = _broadcast_param(L, n, name="length_fen")
            Wb = _broadcast_param(W, n, name="width_fen")
            Hb = _broadcast_param(H, n, name="height_fen")

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            log_lines_all = []

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
                    _to_float_safe(Lb[i], 32.0),
                    _to_float_safe(Wb[i], 32.0),
                    _to_float_safe(Hb[i], 20.0),
                    bp_in,
                    rp_in,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                log_lines_all.append(log_lines)

            self.BlockCutter_3__TimberBrep = timber_breps[0] if n == 1 else timber_breps
            self.BlockCutter_3__FaceList = faces_list[0] if n == 1 else faces_list
            self.BlockCutter_3__PointList = points_list[0] if n == 1 else points_list
            self.BlockCutter_3__EdgeList = edges_list[0] if n == 1 else edges_list
            self.BlockCutter_3__CenterPoint = center_pts[0] if n == 1 else center_pts
            self.BlockCutter_3__CenterAxisLines = center_axes_list[0] if n == 1 else center_axes_list
            self.BlockCutter_3__EdgeMidPoints = edge_midpts_list[0] if n == 1 else edge_midpts_list
            self.BlockCutter_3__FacePlaneList = face_planes_list[0] if n == 1 else face_planes_list
            self.BlockCutter_3__Corner0Planes = corner0_planes_list[0] if n == 1 else corner0_planes_list
            self.BlockCutter_3__LocalAxesPlane = local_axes_planes[0] if n == 1 else local_axes_planes
            self.BlockCutter_3__AxisX = axis_x_list[0] if n == 1 else axis_x_list
            self.BlockCutter_3__AxisY = axis_y_list[0] if n == 1 else axis_y_list
            self.BlockCutter_3__AxisZ = axis_z_list[0] if n == 1 else axis_z_list
            self.BlockCutter_3__FaceDirTags = face_tags_list[0] if n == 1 else face_tags_list
            self.BlockCutter_3__EdgeDirTags = edge_tags_list[0] if n == 1 else edge_tags_list
            self.BlockCutter_3__Corner0EdgeDirs = corner0_dirs_list[0] if n == 1 else corner0_dirs_list
            self.BlockCutter_3__Log = log_lines_all[0] if n == 1 else log_lines_all

            self.Log.append("[STEP7][BlockCutter::3] OK")
        except Exception as e:
            self.BlockCutter_3__TimberBrep = None
            self.BlockCutter_3__FacePlaneList = []
            self.BlockCutter_3__Corner0Planes = []
            self.BlockCutter_3__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step7 BlockCutter::3 出错: {}".format(e))

        # ========== Step 7B：Graft Tree（可选：保证每个 Geo 单独分支）==========
        try:
            self.Step7__GraftedGeo = _graft_any(self.BlockCutter_3__TimberBrep)
        except Exception:
            self.Step7__GraftedGeo = _graft_any(None)

        # ========== Step 7C：List Item（FacePlaneList -> SourcePlane）==========
        try:
            idx_in = self.all_get(
                "GeoAligner_5__SourcePlane",
                0,
                prefer_input=GeoAligner_5__SourcePlane,
            )
            wrap = False
            face_plane_list = getattr(self, "BlockCutter_3__FacePlaneList", None)

            # 多 timber：face_plane_list 为 list[face_planes]
            if isinstance(face_plane_list, list) and len(face_plane_list) > 0 and isinstance(face_plane_list[0], (list, tuple)):
                n_geo = len(face_plane_list)
                idx_flat = flatten_any(idx_in) if (_is_gh_tree(idx_in) or isinstance(idx_in, (list, tuple))) else [idx_in]
                if len(idx_flat) == 0:
                    idx_flat = [0]
                idx_b = _broadcast_param(idx_flat, n_geo, name="GeoAligner_5__SourcePlane")
                src_planes = []
                for gi in range(n_geo):
                    src_planes.append(_list_item(face_plane_list[gi], idx_b[gi], wrap=wrap))
                self.GeoAligner_5__SourcePlane_Item = src_planes[0] if n_geo == 1 else src_planes
            else:
                # 单 timber：idx 可为 tree/list
                idx_branches = _as_branch_list(idx_in)
                src_out = []
                for br in idx_branches:
                    if br is None or (isinstance(br, list) and len(br) == 0):
                        br = [0]
                    b_items = []
                    for i in to_list(br):
                        b_items.append(_list_item(face_plane_list, i, wrap=wrap))
                    src_out.append(b_items)

                if len(src_out) == 1:
                    src_out = src_out[0]
                    if isinstance(src_out, list) and len(src_out) == 1:
                        src_out = src_out[0]

                self.GeoAligner_5__SourcePlane_Item = src_out

            self.Log.append("[STEP7][List Item SourcePlane] OK")
        except Exception as e:
            self.GeoAligner_5__SourcePlane_Item = None
            self.Log.append("[ERROR] Step7 List Item(SourcePlane) 出错: {}".format(e))

        # ========== Step 7D：Tree Item（Skew_Planes -> TargetPlane）==========
        try:
            tree_in = getattr(self, "Skew_Planes", None)
            path_in = self.all_get(
                "GeoAligner_5__TargetPlane_path",
                0,
                prefer_input=GeoAligner_5__TargetPlane_path,
            )
            index_in = self.all_get(
                "GeoAligner_5__TargetPlane_index",
                0,
                prefer_input=GeoAligner_5__TargetPlane_index,
            )
            wrap = False

            path_branches = _as_branch_list(path_in)
            index_branches = _as_branch_list(index_in)

            bcount = max(len(path_branches), len(index_branches))
            if bcount <= 0:
                bcount = 1

            out_tp = []
            for bi in range(bcount):
                pbr = path_branches[bi] if bi < len(path_branches) else path_branches[-1]
                ibr = index_branches[bi] if bi < len(index_branches) else index_branches[-1]

                p_list = to_list(pbr)
                i_list = to_list(ibr)
                n = _max_len(p_list, i_list)
                if n <= 0:
                    n = 1
                p_b = _broadcast_param(p_list, n)
                i_b = _broadcast_param(i_list, n)

                b_items = []
                for k in range(n):
                    b_items.append(_tree_item(tree_in, p_b[k], i_b[k], wrap=wrap))
                out_tp.append(b_items)

            if len(out_tp) == 1:
                out_tp = out_tp[0]
                if isinstance(out_tp, list) and len(out_tp) == 1:
                    out_tp = out_tp[0]

            self.GeoAligner_5__TargetPlane_Item = out_tp
            self.Log.append("[STEP7][Tree Item TargetPlane] OK")
        except Exception as e:
            self.GeoAligner_5__TargetPlane_Item = None
            self.Log.append("[ERROR] Step7 Tree Item(TargetPlane) 出错: {}".format(e))

        # ========== Step 7E：GeoAligner::5 ==========
        try:
            geo_in = self.Step7__GraftedGeo
            source_plane = self.GeoAligner_5__SourcePlane_Item
            target_plane = self.GeoAligner_5__TargetPlane_Item

            rotate_deg = self.all_get("GeoAligner_5__RotateDeg", 0.0, prefer_input=GeoAligner_5__RotateDeg)
            flip_x = self.all_get("GeoAligner_5__FlipX", False, prefer_input=GeoAligner_5__FlipX)
            flip_y = self.all_get("GeoAligner_5__FlipY", False, prefer_input=GeoAligner_5__FlipY)
            flip_z = self.all_get("GeoAligner_5__FlipZ", False, prefer_input=GeoAligner_5__FlipZ)
            move_x = self.all_get("GeoAligner_5__MoveX", 0.0, prefer_input=GeoAligner_5__MoveX)
            move_y = self.all_get("GeoAligner_5__MoveY", 0.0, prefer_input=GeoAligner_5__MoveY)
            move_z = self.all_get("GeoAligner_5__MoveZ", 0.0, prefer_input=GeoAligner_5__MoveZ)

            geo_branches = geo_in if isinstance(geo_in, list) else [to_list(geo_in)]

            def _normalize_plane_branches(p, branch_count, name="plane"):
                if branch_count <= 0:
                    branch_count = 1
                if _is_gh_tree(p):
                    brs = _tree_to_branches(p)
                    if len(brs) == 0:
                        return [[None] for _ in range(branch_count)]
                    if len(brs) >= branch_count:
                        return brs[:branch_count]
                    return brs + [brs[-1]] * (branch_count - len(brs))
                if isinstance(p, (list, tuple)):
                    seq = list(p)
                    if len(seq) == 0:
                        return [[None] for _ in range(branch_count)]
                    if isinstance(seq[0], (list, tuple)):
                        brs = [list(b) for b in seq]
                        if len(brs) >= branch_count:
                            return brs[:branch_count]
                        return brs + [brs[-1]] * (branch_count - len(brs))
                    if name.lower().startswith("source") and len(seq) == branch_count:
                        return [[seq[i]] for i in range(branch_count)]
                    out = []
                    for bi in range(branch_count):
                        ii = bi if bi < len(seq) else (len(seq) - 1)
                        out.append([seq[ii]])
                    return out
                return [[p] for _ in range(branch_count)]

            branch_count = len(geo_branches)
            sp_branches = _normalize_plane_branches(source_plane, branch_count, name="SourcePlane")
            tp_branches = _normalize_plane_branches(target_plane, branch_count, name="TargetPlane")

            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            self.GeoAligner_5__SourceOut = out_source
            self.GeoAligner_5__TargetOut = out_target
            self.GeoAligner_5__TransformOut = out_xf
            self.GeoAligner_5__MovedGeo = out_moved
            self.GeoAligner_5__Log = out_lg
            self.Log.append("[STEP7][GeoAligner::5] OK")
        except Exception as e:
            self.GeoAligner_5__SourceOut = None
            self.GeoAligner_5__TargetOut = None
            self.GeoAligner_5__MovedGeo = None
            self.GeoAligner_5__TransformOut = None
            self.GeoAligner_5__Log = ["[ERROR] GeoAligner::5: {}".format(e)]
            self.Log.append("[ERROR] Step7 GeoAligner::5 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 8：BlockCutter::4 + GeoAligner::6
    # ------------------------------------------------------
    def step8_blockcutter_4_geoaligner_6(self,
                                        BlockCutter_4__length_fen=None,
                                        BlockCutter_4__width_fen=None,
                                        BlockCutter_4__height_fen=None,
                                        base_point=None,
                                        reference_plane=None,
                                        GeoAligner_6__SourcePlane=None,
                                        GeoAligner_6__TargetPlane_base_path=None,
                                        GeoAligner_6__TargetPlane_base_index=None,
                                        GeoAligner_6__TargetPlane_origin=None,
                                        GeoAligner_6__RotateDeg=None,
                                        GeoAligner_6__FlipX=None,
                                        GeoAligner_6__FlipY=None,
                                        GeoAligner_6__FlipZ=None,
                                        GeoAligner_6__MoveX=None,
                                        GeoAligner_6__MoveY=None,
                                        GeoAligner_6__MoveZ=None):
        """严格按图连线实现 Step8。

        组件链：
          BlockCutter::4 -> List Item(FacePlaneList -> SourcePlane)
                        -> Tree Item(Skew_Planes -> BasePlane)
                        -> List Item(Skew_Point_C -> OriginPoint)
                        -> Plane Origin(Base, Origin) -> TargetPlane
                        -> GeoAligner::6

        关键约束：
        - 禁止重复读库；参数优先级：输入端 > AllDict > 默认。
        - BlockCutter 三维尺寸支持多值：按索引位置对齐（GH 广播：短列表末值补齐）。
        - Tree Item：Path/Index 支持 list/tree，按 GH 广播逐项取值。
        - 目标平面构造：Base/Origin 任一为多值时按 GH 广播逐项构造。
        - GeoAligner_6__MovedGeo 输出在绑定时必须彻底 flatten_any。
        """

        # ========== Step 8A：BlockCutter::4 ==========
        try:
            # base_point：输入端 > 默认原点
            bp_in = base_point
            if bp_in is None:
                bp_in = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp_in, rg.Point):
                bp_in = bp_in.Location

            # reference_plane：输入端 > DB > 默认 GH XZ Plane
            rp_in = self.all_get(
                "BlockCutter_4__reference_plane",
                None,
                prefer_input=reference_plane,
            )
            if rp_in is None:
                rp_in = gh_plane_XZ(bp_in)

            # length/width/height：输入端 > DB > 默认
            length_fen_in = self.all_get(
                "BlockCutter_4__length_fen",
                32.0,
                prefer_input=BlockCutter_4__length_fen,
            )
            width_fen_in = self.all_get(
                "BlockCutter_4__width_fen",
                32.0,
                prefer_input=BlockCutter_4__width_fen,
            )
            height_fen_in = self.all_get(
                "BlockCutter_4__height_fen",
                20.0,
                prefer_input=BlockCutter_4__height_fen,
            )

            def _to_float_safe(x, d):
                try:
                    return float(x) if x is not None else float(d)
                except Exception:
                    return float(d)

            def _as_scalar_list(v, default_scalar):
                if v is None:
                    return [float(default_scalar)]
                if _is_gh_tree(v) or isinstance(v, (list, tuple)):
                    flat = flatten_any(v)
                    if len(flat) == 0:
                        return [float(default_scalar)]
                    return [_to_float_safe(it, default_scalar) for it in flat]
                return [_to_float_safe(v, default_scalar)]

            L = _as_scalar_list(length_fen_in, 32.0)
            W = _as_scalar_list(width_fen_in, 32.0)
            H = _as_scalar_list(height_fen_in, 20.0)
            n = max(len(L), len(W), len(H), 1)

            Lb = _broadcast_param(L, n, name="length_fen")
            Wb = _broadcast_param(W, n, name="width_fen")
            Hb = _broadcast_param(H, n, name="height_fen")

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            log_lines_all = []

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
                    _to_float_safe(Lb[i], 32.0),
                    _to_float_safe(Wb[i], 32.0),
                    _to_float_safe(Hb[i], 20.0),
                    bp_in,
                    rp_in,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                log_lines_all.append(log_lines)

            self.BlockCutter_4__TimberBrep = timber_breps[0] if n == 1 else timber_breps
            self.BlockCutter_4__FaceList = faces_list[0] if n == 1 else faces_list
            self.BlockCutter_4__PointList = points_list[0] if n == 1 else points_list
            self.BlockCutter_4__EdgeList = edges_list[0] if n == 1 else edges_list
            self.BlockCutter_4__CenterPoint = center_pts[0] if n == 1 else center_pts
            self.BlockCutter_4__CenterAxisLines = center_axes_list[0] if n == 1 else center_axes_list
            self.BlockCutter_4__EdgeMidPoints = edge_midpts_list[0] if n == 1 else edge_midpts_list
            self.BlockCutter_4__FacePlaneList = face_planes_list[0] if n == 1 else face_planes_list
            self.BlockCutter_4__Corner0Planes = corner0_planes_list[0] if n == 1 else corner0_planes_list
            self.BlockCutter_4__LocalAxesPlane = local_axes_planes[0] if n == 1 else local_axes_planes
            self.BlockCutter_4__AxisX = axis_x_list[0] if n == 1 else axis_x_list
            self.BlockCutter_4__AxisY = axis_y_list[0] if n == 1 else axis_y_list
            self.BlockCutter_4__AxisZ = axis_z_list[0] if n == 1 else axis_z_list
            self.BlockCutter_4__FaceDirTags = face_tags_list[0] if n == 1 else face_tags_list
            self.BlockCutter_4__EdgeDirTags = edge_tags_list[0] if n == 1 else edge_tags_list
            self.BlockCutter_4__Corner0EdgeDirs = corner0_dirs_list[0] if n == 1 else corner0_dirs_list
            self.BlockCutter_4__Log = log_lines_all[0] if n == 1 else log_lines_all

            self.Log.append("[STEP8][BlockCutter::4] OK")
        except Exception as e:
            self.BlockCutter_4__TimberBrep = None
            self.BlockCutter_4__FacePlaneList = []
            self.BlockCutter_4__Corner0Planes = []
            self.BlockCutter_4__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step8 BlockCutter::4 出错: {}".format(e))

        # ========== Step 8B：List Item（FacePlaneList -> SourcePlane）==========
        try:
            idx_in = self.all_get(
                "GeoAligner_6__SourcePlane",
                0,
                prefer_input=GeoAligner_6__SourcePlane,
            )
            wrap = False
            face_plane_list = getattr(self, "BlockCutter_4__FacePlaneList", None)

            # 多 timber：FacePlaneList 为 list[face_planes]
            if isinstance(face_plane_list, list) and len(face_plane_list) > 0 and isinstance(face_plane_list[0], (list, tuple)):
                n_geo = len(face_plane_list)
                idx_flat = flatten_any(idx_in) if (_is_gh_tree(idx_in) or isinstance(idx_in, (list, tuple))) else [idx_in]
                if len(idx_flat) == 0:
                    idx_flat = [0]
                idx_b = _broadcast_param(idx_flat, n_geo, name="GeoAligner_6__SourcePlane")
                src_planes = []
                for gi in range(n_geo):
                    src_planes.append(_list_item(face_plane_list[gi], idx_b[gi], wrap=wrap))
                self.GeoAligner_6__SourcePlane_Item = src_planes[0] if n_geo == 1 else src_planes
            else:
                idx_branches = _as_branch_list(idx_in)
                src_out = []
                for br in idx_branches:
                    if br is None or (isinstance(br, list) and len(br) == 0):
                        br = [0]
                    b_items = []
                    for i in to_list(br):
                        b_items.append(_list_item(face_plane_list, i, wrap=wrap))
                    src_out.append(b_items)
                if len(src_out) == 1:
                    src_out = src_out[0]
                    if isinstance(src_out, list) and len(src_out) == 1:
                        src_out = src_out[0]
                self.GeoAligner_6__SourcePlane_Item = src_out

            self.Log.append("[STEP8][List Item SourcePlane] OK")
        except Exception as e:
            self.GeoAligner_6__SourcePlane_Item = None
            self.Log.append("[ERROR] Step8 List Item(SourcePlane) 出错: {}".format(e))

        # ========== Step 8C：Tree Item（Skew_Planes -> BasePlane）==========
        try:
            tree_in = getattr(self, "Skew_Planes", None)
            path_in = self.all_get(
                "GeoAligner_6__TargetPlane_base_path",
                0,
                prefer_input=GeoAligner_6__TargetPlane_base_path,
            )
            index_in = self.all_get(
                "GeoAligner_6__TargetPlane_base_index",
                0,
                prefer_input=GeoAligner_6__TargetPlane_base_index,
            )
            wrap = False

            path_branches = _as_branch_list(path_in)
            index_branches = _as_branch_list(index_in)

            bcount = max(len(path_branches), len(index_branches))
            if bcount <= 0:
                bcount = 1

            out_bp = []
            for bi in range(bcount):
                pbr = path_branches[bi] if bi < len(path_branches) else path_branches[-1]
                ibr = index_branches[bi] if bi < len(index_branches) else index_branches[-1]

                p_list = to_list(pbr)
                i_list = to_list(ibr)
                n = _max_len(p_list, i_list)
                if n <= 0:
                    n = 1
                p_b = _broadcast_param(p_list, n)
                i_b = _broadcast_param(i_list, n)

                b_items = []
                for k in range(n):
                    b_items.append(_tree_item(tree_in, p_b[k], i_b[k], wrap=wrap))
                out_bp.append(b_items)

            if len(out_bp) == 1:
                out_bp = out_bp[0]
                if isinstance(out_bp, list) and len(out_bp) == 1:
                    out_bp = out_bp[0]

            self.GeoAligner_6__TargetPlane_BasePlane_Item = out_bp
            self.Log.append("[STEP8][Tree Item BasePlane] OK")
        except Exception as e:
            self.GeoAligner_6__TargetPlane_BasePlane_Item = None
            self.Log.append("[ERROR] Step8 Tree Item(BasePlane) 出错: {}".format(e))

        # ========== Step 8D：List Item（Skew_Point_C -> OriginPoint）==========
        try:
            pt_list_in = getattr(self, "Skew_Point_C", None)
            idx_in = self.all_get(
                "GeoAligner_6__TargetPlane_origin",
                0,
                prefer_input=GeoAligner_6__TargetPlane_origin,
            )
            wrap = False

            idx_branches = _as_branch_list(idx_in)
            out_op = []
            for br in idx_branches:
                if br is None or (isinstance(br, list) and len(br) == 0):
                    br = [0]
                b_items = []
                for i in to_list(br):
                    b_items.append(_list_item(pt_list_in, i, wrap=wrap))
                out_op.append(b_items)

            if len(out_op) == 1:
                out_op = out_op[0]
                if isinstance(out_op, list) and len(out_op) == 1:
                    out_op = out_op[0]

            self.GeoAligner_6__TargetPlane_OriginPoint_Item = out_op
            self.Log.append("[STEP8][List Item OriginPoint] OK")
        except Exception as e:
            self.GeoAligner_6__TargetPlane_OriginPoint_Item = None
            self.Log.append("[ERROR] Step8 List Item(OriginPoint) 出错: {}".format(e))

        # ========== Step 8E：Plane Origin（Base + Origin -> TargetPlane）==========
        try:
            base_pl = self.GeoAligner_6__TargetPlane_BasePlane_Item
            origin_pt = self.GeoAligner_6__TargetPlane_OriginPoint_Item

            def _to_point3d(p):
                if p is None:
                    return None
                if isinstance(p, rg.Point3d):
                    return p
                if isinstance(p, rg.Point):
                    return p.Location
                return p

            def _plane_origin(base, origin):
                if base is None or origin is None:
                    return None
                try:
                    op = _to_point3d(origin)
                    return rg.Plane(op, base.XAxis, base.YAxis)
                except Exception:
                    return None

            # 广播对齐：base/origin 任一为 list/tree 时按 GH 广播逐项
            b_list = flatten_any(base_pl) if (_is_gh_tree(base_pl) or isinstance(base_pl, (list, tuple))) else [base_pl]
            o_list = flatten_any(origin_pt) if (_is_gh_tree(origin_pt) or isinstance(origin_pt, (list, tuple))) else [origin_pt]
            if len(b_list) == 0:
                b_list = [None]
            if len(o_list) == 0:
                o_list = [None]
            n = max(len(b_list), len(o_list), 1)
            b_b = _broadcast_param(b_list, n, name="BasePlane")
            o_b = _broadcast_param(o_list, n, name="OriginPoint")
            pls = []
            for i in range(n):
                pls.append(_plane_origin(b_b[i], o_b[i]))
            self.GeoAligner_6__TargetPlane_Item = pls[0] if n == 1 else pls

            self.Log.append("[STEP8][Plane Origin TargetPlane] OK")
        except Exception as e:
            self.GeoAligner_6__TargetPlane_Item = None
            self.Log.append("[ERROR] Step8 Plane Origin(TargetPlane) 出错: {}".format(e))

        # ========== Step 8F：GeoAligner::6 ==========
        try:
            geo_in = getattr(self, "BlockCutter_4__TimberBrep", None)
            source_plane = self.GeoAligner_6__SourcePlane_Item
            target_plane = self.GeoAligner_6__TargetPlane_Item

            rotate_deg = self.all_get("GeoAligner_6__RotateDeg", 0.0, prefer_input=GeoAligner_6__RotateDeg)
            flip_x = self.all_get("GeoAligner_6__FlipX", False, prefer_input=GeoAligner_6__FlipX)
            flip_y = self.all_get("GeoAligner_6__FlipY", False, prefer_input=GeoAligner_6__FlipY)
            flip_z = self.all_get("GeoAligner_6__FlipZ", False, prefer_input=GeoAligner_6__FlipZ)
            move_x = self.all_get("GeoAligner_6__MoveX", 0.0, prefer_input=GeoAligner_6__MoveX)
            move_y = self.all_get("GeoAligner_6__MoveY", 0.0, prefer_input=GeoAligner_6__MoveY)
            move_z = self.all_get("GeoAligner_6__MoveZ", 0.0, prefer_input=GeoAligner_6__MoveZ)

            def _normalize_geo_branches(g):
                if g is None:
                    return [[None]]
                # GH Tree：直接转 branches
                if _is_gh_tree(g):
                    brs = _tree_to_branches(g)
                    return brs if brs else [[None]]
                # list/tuple：若是 list[list] 直接视为 branches；否则每个 item 单独成分支
                if isinstance(g, (list, tuple)):
                    seq = list(g)
                    if len(seq) == 0:
                        return [[None]]
                    if isinstance(seq[0], (list, tuple)):
                        return [list(b) for b in seq]
                    return [[it] for it in seq]
                return [[g]]

            geo_branches = _normalize_geo_branches(geo_in)

            def _normalize_plane_branches(p, branch_count, name="plane"):
                if branch_count <= 0:
                    branch_count = 1

                if _is_gh_tree(p):
                    brs = _tree_to_branches(p)
                    if len(brs) == 0:
                        return [[None] for _ in range(branch_count)]
                    if len(brs) >= branch_count:
                        return brs[:branch_count]
                    return brs + [brs[-1]] * (branch_count - len(brs))

                if isinstance(p, (list, tuple)):
                    seq = list(p)
                    if len(seq) == 0:
                        return [[None] for _ in range(branch_count)]
                    if isinstance(seq[0], (list, tuple)):
                        brs = [list(b) for b in seq]
                        if len(brs) >= branch_count:
                            return brs[:branch_count]
                        return brs + [brs[-1]] * (branch_count - len(brs))

                    if name.lower().startswith("source") and len(seq) == branch_count:
                        return [[seq[i]] for i in range(branch_count)]

                    out = []
                    for bi in range(branch_count):
                        ii = bi if bi < len(seq) else (len(seq) - 1)
                        out.append([seq[ii]])
                    return out

                return [[p] for _ in range(branch_count)]

            branch_count = len(geo_branches)
            sp_branches = _normalize_plane_branches(source_plane, branch_count, name="SourcePlane")
            tp_branches = _normalize_plane_branches(target_plane, branch_count, name="TargetPlane")

            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                moved_items = []
                source_items = []
                target_items = []
                xf_items = []

                for i in range(n):
                    so, to, xf, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    source_items.append(so)
                    target_items.append(to)
                    xf_items.append(xf)
                    moved_items.append(mg)

                out_source.append(source_items)
                out_target.append(target_items)
                out_xf.append(xf_items)
                out_moved.append(moved_items)

            self.GeoAligner_6__SourceOut = out_source
            self.GeoAligner_6__TargetOut = out_target
            self.GeoAligner_6__TransformOut = out_xf
            self.GeoAligner_6__MovedGeo = out_moved
            self.Log.append("[STEP8][GeoAligner::6] OK")
        except Exception as e:
            self.GeoAligner_6__SourceOut = None
            self.GeoAligner_6__TargetOut = None
            self.GeoAligner_6__TransformOut = None
            self.GeoAligner_6__MovedGeo = None
            self.GeoAligner_6__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step8 GeoAligner::6 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 9：GongYan + PlaneFromLists::4 + GeoAligner::7
    # ------------------------------------------------------
    def step9_gongyan_plane_geoaligner_7(
        self,
        GongYan__BasePoint=None,
        GongYan__SectionPlane=None,
        GongYan__EM_fen=None,
        GongYan__EC_fen=None,
        GongYan__AI_fen=None,
        GongYan__AG_fen=None,
        GongYan__JR_fen=None,
        GongYan__HK_fen=None,
        GongYan__Thickness=None,
        GongYan__OffsetDist=None,
        PlaneFromLists_4__IndexOrigin=None,
        PlaneFromLists_4__IndexPlane=None,
        PlaneFromLists_4__Wrap=None,
        GeoAligner_7__SourcePlane=None,
        GeoAligner_7__RotateDeg=None,
        GeoAligner_7__FlipX=None,
        GeoAligner_7__FlipY=None,
        GeoAligner_7__FlipZ=None,
        GeoAligner_7__MoveX=None,
        GeoAligner_7__MoveY=None,
        GeoAligner_7__MoveZ=None,
    ):
        """严格按图连线实现 Step9。

        组件链：
          GongYan -> PlaneFromLists::4 + ListItem(SectionPlanes) -> GeoAligner::7

        特殊规则：GeoAligner::7 的 Geo 输入端（ToolBrep 多个值）必须视为“整体对象”只对齐一次：
          GeoAligner_xfm.align(geo=<list_of_geo>, ...)
        """

        # ========== Step 9A：GongYan ==========
        try:
            bp = self.all_get('GongYan__BasePoint', None, prefer_input=GongYan__BasePoint)
            if bp is None:
                bp = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp, rg.Point):
                bp = bp.Location

            sp = self.all_get('GongYan__SectionPlane', None, prefer_input=GongYan__SectionPlane)

            EM_fen = self.all_get('GongYan__EM_fen', None, prefer_input=GongYan__EM_fen)
            EC_fen = self.all_get('GongYan__EC_fen', None, prefer_input=GongYan__EC_fen)
            AI_fen = self.all_get('GongYan__AI_fen', None, prefer_input=GongYan__AI_fen)
            AG_fen = self.all_get('GongYan__AG_fen', None, prefer_input=GongYan__AG_fen)
            JR_fen = self.all_get('GongYan__JR_fen', None, prefer_input=GongYan__JR_fen)
            HK_fen = self.all_get('GongYan__HK_fen', None, prefer_input=GongYan__HK_fen)
            Thickness = self.all_get('GongYan__Thickness', None, prefer_input=GongYan__Thickness)
            OffsetDist = self.all_get('GongYan__OffsetDist', None, prefer_input=GongYan__OffsetDist)

            builder = FT_GongYan_CaiQi_ToolBuilder(
                base_point=bp,
                section_plane=sp,
                EM_fen=EM_fen,
                EC_fen=EC_fen,
                AI_fen=AI_fen,
                AG_fen=AG_fen,
                JR_fen=JR_fen,
                HK_fen=HK_fen,
                Thickness=Thickness,
                OffsetDist=OffsetDist,
            )

            (self.GongYan__SectionCurve,
             self.GongYan__SectionFace,
             self.GongYan__LeftCurve,
             self.GongYan__RightCurve,
             self.GongYan__SymmetryAxis,
             self.GongYan__AllPoints,
             self.GongYan__ToolBrep,
             self.GongYan__SectionPlanes,
             self.GongYan__Log) = builder.build()

            self.Log.append('[STEP9][GongYan] OK')
        except Exception as e:
            import traceback
            self.GongYan__SectionCurve = None
            self.GongYan__SectionFace = None
            self.GongYan__LeftCurve = None
            self.GongYan__RightCurve = None
            self.GongYan__SymmetryAxis = None
            self.GongYan__AllPoints = None
            self.GongYan__ToolBrep = None
            self.GongYan__SectionPlanes = None
            self.GongYan__Log = '执行异常: {}\n{}'.format(str(e), traceback.format_exc())
            self.Log.append('[ERROR] Step9 GongYan 出错: {}'.format(e))

        # ========== Step 9B：PlaneFromLists::4 ==========
        try:
            origin_points = getattr(self, 'EdgeMidPoints', None)
            base_planes = getattr(self, 'Corner0Planes', None)

            idx_origin = self.all_get('PlaneFromLists_4__IndexOrigin', None, prefer_input=PlaneFromLists_4__IndexOrigin)
            idx_plane = self.all_get('PlaneFromLists_4__IndexPlane', None, prefer_input=PlaneFromLists_4__IndexPlane)
            wrap = self.all_get('PlaneFromLists_4__Wrap', True, prefer_input=PlaneFromLists_4__Wrap)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))
            if bcount <= 0:
                bcount = 1

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_4__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_4__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_4__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_4__Log = out_log

            self.Log.append('[STEP9][PlaneFromLists::4] OK')
        except Exception as e:
            self.PlaneFromLists_4__BasePlane = None
            self.PlaneFromLists_4__OriginPoint = None
            self.PlaneFromLists_4__ResultPlane = None
            self.PlaneFromLists_4__Log = ['[ERROR] PlaneFromLists::4: {}'.format(e)]
            self.Log.append('[ERROR] Step9 PlaneFromLists::4 出错: {}'.format(e))

        # ========== Step 9C：List Item（GongYan.SectionPlanes -> SourcePlane）==========
        try:
            planes_in = getattr(self, 'GongYan__SectionPlanes', None)
            idx_in = self.all_get('GeoAligner_7__SourcePlane', 0, prefer_input=GeoAligner_7__SourcePlane)
            wrap_li = False

            idx_branches = _as_branch_list(idx_in)
            src_out = []
            for br in idx_branches:
                if br is None or (isinstance(br, list) and len(br) == 0):
                    br = [0]
                b_items = []
                for i in to_list(br):
                    b_items.append(_list_item(planes_in, i, wrap=wrap_li))
                src_out.append(b_items)

            if len(src_out) == 1:
                src_out = src_out[0]
                if isinstance(src_out, list) and len(src_out) == 1:
                    src_out = src_out[0]

            self.GeoAligner_7__SourcePlane_Item = src_out
            self.Log.append('[STEP9][List Item SourcePlane] OK')
        except Exception as e:
            self.GeoAligner_7__SourcePlane_Item = None
            self.Log.append('[ERROR] Step9 List Item(SourcePlane) 出错: {}'.format(e))

        # ========== Step 9D：GeoAligner::7（整体对齐多个 Geo）==========
        try:
            geo_raw = getattr(self, 'GongYan__ToolBrep', None)
            geo_list = flatten_any(geo_raw)
            if geo_list is None:
                geo_list = []

            source_plane = self.GeoAligner_7__SourcePlane_Item
            target_plane = self.PlaneFromLists_4__ResultPlane

            rotate_deg = self.all_get('GeoAligner_7__RotateDeg', 0.0, prefer_input=GeoAligner_7__RotateDeg)
            flip_x = self.all_get('GeoAligner_7__FlipX', False, prefer_input=GeoAligner_7__FlipX)
            flip_y = self.all_get('GeoAligner_7__FlipY', False, prefer_input=GeoAligner_7__FlipY)
            flip_z = self.all_get('GeoAligner_7__FlipZ', False, prefer_input=GeoAligner_7__FlipZ)
            move_x = self.all_get('GeoAligner_7__MoveX', 0.0, prefer_input=GeoAligner_7__MoveX)
            move_y = self.all_get('GeoAligner_7__MoveY', 0.0, prefer_input=GeoAligner_7__MoveY)
            move_z = self.all_get('GeoAligner_7__MoveZ', 0.0, prefer_input=GeoAligner_7__MoveZ)

            # 参数可能为 tree/list：按分支广播，每组参数调用一次 align，但 geo 始终为整体 geo_list
            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
                1
            )

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_tf = []
                b_mg = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        geo_list,
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append('i={} OK'.format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            self.GeoAligner_7__SourceOut = out_source
            self.GeoAligner_7__TargetOut = out_target
            self.GeoAligner_7__TransformOut = out_xf
            # 输出端必须完全展平（尤其 MovedGeo）
            self.GeoAligner_7__MovedGeo = flatten_any(out_moved)
            self.GeoAligner_7__Log = out_lg

            self.Log.append('[STEP9][GeoAligner::7] OK')
        except Exception as e:
            self.GeoAligner_7__SourceOut = None
            self.GeoAligner_7__TargetOut = None
            self.GeoAligner_7__TransformOut = None
            self.GeoAligner_7__MovedGeo = None
            self.GeoAligner_7__Log = ['[ERROR] GeoAligner::7: {}'.format(e)]
            self.Log.append('[ERROR] Step9 GeoAligner::7 出错: {}'.format(e))

        return self


    # ------------------------------------------------------
    # Step 10：QiAOTool::2 + PlaneFromLists::5 + PlaneFromLists::6 + GeoAligner::8
    # ------------------------------------------------------
    def step10_qiao_tool2_plane_geoaligner_8(
        self,
        QiAOTool_2__length_fen=None,
        QiAOTool_2__width_fen=None,
        QiAOTool_2__height_fen=None,
        QiAOTool_2__base_point=None,
        QiAOTool_2__timber_ref_plane_mode=None,
        QiAOTool_2__qi_height=None,
        QiAOTool_2__sha_width=None,
        QiAOTool_2__qi_offset_fen=None,
        QiAOTool_2__extrude_length=None,
        QiAOTool_2__extrude_positive=None,
        QiAOTool_2__qi_ref_plane_mode=None,
        PlaneFromLists_6__IndexOrigin=None,
        PlaneFromLists_6__IndexPlane=None,
        PlaneFromLists_6__Wrap=None,
        PlaneFromLists_5__IndexOrigin=None,
        PlaneFromLists_5__IndexPlane=None,
        PlaneFromLists_5__Wrap=None,
        GeoAligner_8__RotateDeg=None,
        GeoAligner_8__FlipX=None,
        GeoAligner_8__FlipY=None,
        GeoAligner_8__FlipZ=None,
        GeoAligner_8__MoveX=None,
        GeoAligner_8__MoveY=None,
        GeoAligner_8__MoveZ=None,
    ):
        """严格按图连线实现 Step10。

        组件链：
          QiAOTool::2 -> PlaneFromLists::6 (SourcePlane, from QiAOTool)
                        -> PlaneFromLists::5 (TargetPlane, from BuildTimberBlockUniform_SkewAxis_M)
                        -> GeoAligner::8 (align tool geo)

        关键约束：
        - 禁止重复读库；参数优先级：输入端 > AllDict > 默认。
        - PlaneFromLists：IndexOrigin / IndexPlane 支持 list/tree，长度不一致按 GH 广播。
        - GeoAligner：Geo/SourcePlane/TargetPlane 若为 Tree：按分支循环；TargetPlane 允许单值广播。
        - GeoAligner_8__MovedGeo 输出必须完全 flatten。
        - 移除 sticky（本 Solver 内直接 new solver，不使用 sc.sticky）。
        """

        # ========== Step 10A：QiAOTool::2 ==========
        try:
            bp_in = QiAOTool_2__base_point
            if bp_in is None:
                bp_in = self.base_point
            if bp_in is None:
                bp_in = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp_in, rg.Point):
                bp_in = bp_in.Location

            def _to_float(x, default):
                try:
                    if x is None:
                        return float(default)
                    return float(x)
                except Exception:
                    return float(default)

            # 输入端 > AllDict > 默认
            _length_fen = self.all_get('QiAOTool_2__length_fen', None, prefer_input=QiAOTool_2__length_fen)
            _width_fen = self.all_get('QiAOTool_2__width_fen', None, prefer_input=QiAOTool_2__width_fen)
            _height_fen = self.all_get('QiAOTool_2__height_fen', None, prefer_input=QiAOTool_2__height_fen)

            _timber_ref_plane_mode = self.all_get('QiAOTool_2__timber_ref_plane_mode', None, prefer_input=QiAOTool_2__timber_ref_plane_mode)
            _qi_height = self.all_get('QiAOTool_2__qi_height', None, prefer_input=QiAOTool_2__qi_height)
            _sha_width = self.all_get('QiAOTool_2__sha_width', None, prefer_input=QiAOTool_2__sha_width)
            _qi_offset_fen = self.all_get('QiAOTool_2__qi_offset_fen', None, prefer_input=QiAOTool_2__qi_offset_fen)
            _extrude_length = self.all_get('QiAOTool_2__extrude_length', None, prefer_input=QiAOTool_2__extrude_length)
            _extrude_positive = self.all_get('QiAOTool_2__extrude_positive', None, prefer_input=QiAOTool_2__extrude_positive)
            _qi_ref_plane_mode = self.all_get('QiAOTool_2__qi_ref_plane_mode', None, prefer_input=QiAOTool_2__qi_ref_plane_mode)

            params = {
                # timber
                'length_fen': _to_float(_length_fen, 41.0),
                'width_fen': _to_float(_width_fen, 16.0),
                'height_fen': _to_float(_height_fen, 10.0),
                'base_point': bp_in,
                'timber_ref_plane': GHPlaneFactory.make(
                    _timber_ref_plane_mode if _timber_ref_plane_mode is not None else 'XZ',
                    origin=bp_in,
                ),
                # qiao
                'qi_height': _to_float(_qi_height, 4.0),
                'sha_width': _to_float(_sha_width, 2.0),
                'qi_offset_fen': _to_float(_qi_offset_fen, 0.5),
                'extrude_length': _to_float(_extrude_length, 28.0),
                'extrude_positive': InputHelper.to_bool(
                    _extrude_positive if _extrude_positive is not None else False,
                    default=False,
                ),
                'qi_ref_plane': GHPlaneFactory.make(
                    _qi_ref_plane_mode if _qi_ref_plane_mode is not None else 'XZ',
                    origin=bp_in,
                ),
            }

            solver = QiAoToolSolver(ghenv=self.ghenv)
            solver.run(params)

            self.QiAOTool_2__CutTimbers = getattr(solver, 'CutTimbers', None)
            self.QiAOTool_2__FailTimbers = getattr(solver, 'FailTimbers', None)
            self.QiAOTool_2__Log = getattr(solver, 'Log', [])
            self.QiAOTool_2__EdgeMidPoints = getattr(solver, 'EdgeMidPoints', None)
            self.QiAOTool_2__Corner0Planes = getattr(solver, 'Corner0Planes', None)

            # 其它调试输出（若存在）
            self.QiAOTool_2__TimberBrep = getattr(solver, 'TimberBrep', None)
            self.QiAOTool_2__ToolBrep = getattr(solver, 'ToolBrep', None)
            self.QiAOTool_2__AlignedTool = getattr(solver, 'AlignedTool', None)
            self.QiAOTool_2__RefPlanes = getattr(solver, 'RefPlanes', None)
            self.QiAOTool_2__PFL1_ResultPlane = getattr(solver, 'PFL1_ResultPlane', None)
            self.QiAOTool_2__QiAo_FacePlane = getattr(solver, 'QiAo_FacePlane', None)

            self.Log.append('[STEP10][QiAOTool::2] OK')
        except Exception as e:
            self.QiAOTool_2__CutTimbers = None
            self.QiAOTool_2__FailTimbers = None
            self.QiAOTool_2__EdgeMidPoints = None
            self.QiAOTool_2__Corner0Planes = None
            self.QiAOTool_2__Log = ['[ERROR] QiAOTool::2: {}'.format(e)]
            self.Log.append('[ERROR] Step10 QiAOTool::2 出错: {}'.format(e))

        # ========== Step 10B：PlaneFromLists::6（QiAOTool::2 -> SourcePlane）==========
        try:
            origin_points = getattr(self, 'QiAOTool_2__EdgeMidPoints', None)
            base_planes = getattr(self, 'QiAOTool_2__Corner0Planes', None)

            idx_origin = self.all_get('PlaneFromLists_6__IndexOrigin', None, prefer_input=PlaneFromLists_6__IndexOrigin)
            idx_plane = self.all_get('PlaneFromLists_6__IndexPlane', None, prefer_input=PlaneFromLists_6__IndexPlane)
            wrap = self.all_get('PlaneFromLists_6__Wrap', True, prefer_input=PlaneFromLists_6__Wrap)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))
            if bcount <= 0:
                bcount = 1

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_6__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_6__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_6__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_6__Log = out_log

            self.Log.append('[STEP10][PlaneFromLists::6] OK')
        except Exception as e:
            self.PlaneFromLists_6__BasePlane = None
            self.PlaneFromLists_6__OriginPoint = None
            self.PlaneFromLists_6__ResultPlane = None
            self.PlaneFromLists_6__Log = ['[ERROR] PlaneFromLists::6: {}'.format(e)]
            self.Log.append('[ERROR] Step10 PlaneFromLists::6 出错: {}'.format(e))

        # ========== Step 10C：PlaneFromLists::5（主木坯 -> TargetPlane）==========
        try:
            origin_points = getattr(self, 'EdgeMidPoints', None)
            base_planes = getattr(self, 'Corner0Planes', None)

            idx_origin = self.all_get('PlaneFromLists_5__IndexOrigin', None, prefer_input=PlaneFromLists_5__IndexOrigin)
            idx_plane = self.all_get('PlaneFromLists_5__IndexPlane', None, prefer_input=PlaneFromLists_5__IndexPlane)
            wrap = self.all_get('PlaneFromLists_5__Wrap', True, prefer_input=PlaneFromLists_5__Wrap)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))
            if bcount <= 0:
                bcount = 1

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_5__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_5__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_5__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_5__Log = out_log

            self.Log.append('[STEP10][PlaneFromLists::5] OK')
        except Exception as e:
            self.PlaneFromLists_5__BasePlane = None
            self.PlaneFromLists_5__OriginPoint = None
            self.PlaneFromLists_5__ResultPlane = None
            self.PlaneFromLists_5__Log = ['[ERROR] PlaneFromLists::5: {}'.format(e)]
            self.Log.append('[ERROR] Step10 PlaneFromLists::5 出错: {}'.format(e))

        # ========== Step 10D：GeoAligner::8 ==========
        try:
            geo_in = self.QiAOTool_2__CutTimbers
            source_plane = self.PlaneFromLists_6__ResultPlane
            target_plane = self.PlaneFromLists_5__ResultPlane

            rotate_deg = self.all_get('GeoAligner_8__RotateDeg', 0.0, prefer_input=GeoAligner_8__RotateDeg)
            flip_x = self.all_get('GeoAligner_8__FlipX', False, prefer_input=GeoAligner_8__FlipX)
            flip_y = self.all_get('GeoAligner_8__FlipY', False, prefer_input=GeoAligner_8__FlipY)
            flip_z = self.all_get('GeoAligner_8__FlipZ', False, prefer_input=GeoAligner_8__FlipZ)
            move_x = self.all_get('GeoAligner_8__MoveX', 0.0, prefer_input=GeoAligner_8__MoveX)
            move_y = self.all_get('GeoAligner_8__MoveY', 0.0, prefer_input=GeoAligner_8__MoveY)
            move_z = self.all_get('GeoAligner_8__MoveZ', 0.0, prefer_input=GeoAligner_8__MoveZ)

            geo_is_tree = _is_gh_tree(geo_in)
            geo_branches = _tree_to_branches(geo_in) if geo_is_tree else [to_list(geo_in)]

            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
                1,
            )

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append('i={} OK'.format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            def _shrink_like_geo(v):
                if geo_is_tree:
                    return v
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list):
                        if isinstance(geo_in, (list, tuple)):
                            return vv
                        if len(vv) == 1:
                            return vv[0]
                        return vv
                    return vv
                return v

            self.GeoAligner_8__SourceOut = _shrink_like_geo(out_source)
            self.GeoAligner_8__TargetOut = _shrink_like_geo(out_target)
            self.GeoAligner_8__TransformOut = _shrink_like_geo(out_xf)
            self.GeoAligner_8__MovedGeo = flatten_any(_shrink_like_geo(out_moved))
            self.GeoAligner_8__Log = out_lg

            self.Log.append('[STEP10][GeoAligner::8] OK')
        except Exception as e:
            self.GeoAligner_8__SourceOut = None
            self.GeoAligner_8__TargetOut = None
            self.GeoAligner_8__TransformOut = None
            self.GeoAligner_8__MovedGeo = None
            self.GeoAligner_8__Log = ['[ERROR] GeoAligner::8: {}'.format(e)]
            self.Log.append('[ERROR] Step10 GeoAligner::8 出错: {}'.format(e))

        return self


    # ------------------------------------------------------
    # Step 11：PlaneFromLists::7 + Juansha + GeoAligner::9
    # ------------------------------------------------------
    def step11_plane_juansha_geoaligner_9(
        self,
        PlaneFromLists_7__IndexOrigin=None,
        PlaneFromLists_7__IndexPlane=None,
        PlaneFromLists_7__Wrap=None,
        Juansha__HeightFen=None,
        Juansha__LengthFen=None,
        Juansha__DivCount=None,
        Juansha__ThicknessFen=None,
        Juansha__SectionPlane=None,
        Juansha__PositionPoint=None,
        GeoAligner_9__RotateDeg=None,
        GeoAligner_9__FlipX=None,
        GeoAligner_9__FlipY=None,
        GeoAligner_9__FlipZ=None,
        GeoAligner_9__MoveX=None,
        GeoAligner_9__MoveY=None,
        GeoAligner_9__MoveZ=None,
    ):
        """严格按图连线实现 Step11。

        组件链：
          PlaneFromLists::7（主木坯 EdgeMidPoints + Corner0Planes -> TargetPlane）
          -> Juansha（卷杀刀具）
          -> GeoAligner::9（对齐刀具：Geo=ToolBrep, SourcePlane=LengthFacePlane, TargetPlane=ResultPlane）

        关键约束：
        - 参数优先级：输入端 > AllDict > 默认。
        - PlaneFromLists：IndexOrigin / IndexPlane 支持 list/tree，长度不一致按 GH 广播。
        - GeoAligner：Geo/SourcePlane/TargetPlane 若为 Tree：按分支循环；TargetPlane 允许单值广播。
        - GeoAligner_9__MovedGeo 输出必须完全 flatten。
        - 不使用 sticky。
        """

        # ========== Step 11-1：PlaneFromLists::7（提供 TargetPlane）==========
        try:
            origin_points = getattr(self, 'BuildTimberBlockUniform_SkewAxis_M__EdgeMidPoints', None)
            base_planes = getattr(self, 'BuildTimberBlockUniform_SkewAxis_M__Corner0Planes', None)
            if origin_points is None:
                origin_points = getattr(self, 'EdgeMidPoints', None)
            if base_planes is None:
                base_planes = getattr(self, 'Corner0Planes', None)

            idx_origin = self.all_get('PlaneFromLists_7__IndexOrigin', None, prefer_input=PlaneFromLists_7__IndexOrigin)
            idx_plane = self.all_get('PlaneFromLists_7__IndexPlane', None, prefer_input=PlaneFromLists_7__IndexPlane)
            wrap = self.all_get('PlaneFromLists_7__Wrap', True, prefer_input=PlaneFromLists_7__Wrap)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))
            if bcount <= 0:
                bcount = 1

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_7__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_7__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_7__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_7__Log = out_log
            self.Log.append('[STEP11][PlaneFromLists::7] OK')
        except Exception as e:
            self.PlaneFromLists_7__BasePlane = None
            self.PlaneFromLists_7__OriginPoint = None
            self.PlaneFromLists_7__ResultPlane = None
            self.PlaneFromLists_7__Log = ['[ERROR] PlaneFromLists::7: {}'.format(e)]
            self.Log.append('[ERROR] Step11 PlaneFromLists::7 出错: {}'.format(e))

        # ========== Step 11-2：Juansha（卷杀刀具）==========
        try:
            # 输入端 > AllDict > 默认
            height_fen = self.all_get('Juansha__HeightFen', None, prefer_input=Juansha__HeightFen)
            length_fen = self.all_get('Juansha__LengthFen', None, prefer_input=Juansha__LengthFen)
            div_count = self.all_get('Juansha__DivCount', None, prefer_input=Juansha__DivCount)
            thickness_fen = self.all_get('Juansha__ThicknessFen', None, prefer_input=Juansha__ThicknessFen)
            section_plane = self.all_get('Juansha__SectionPlane', None, prefer_input=Juansha__SectionPlane)
            position_point = self.all_get('Juansha__PositionPoint', None, prefer_input=Juansha__PositionPoint)

            # 默认值（以常见组件默认推定；若 DB 中存在则覆盖）
            if height_fen is None:
                height_fen = 3.0
            if length_fen is None:
                length_fen = 10.0
            if thickness_fen is None:
                thickness_fen = 1.0
            if div_count is None:
                div_count = 10
            if section_plane is None:
                section_plane = gh_plane_XZ(rg.Point3d(0.0, 0.0, 0.0))
            if position_point is None:
                position_point = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(position_point, rg.Point):
                position_point = position_point.Location

            builder = JuanShaToolBuilder(
                height_fen=height_fen,
                length_fen=length_fen,
                thickness_fen=thickness_fen,
                div_count=div_count,
                section_plane=section_plane,
                position_point=position_point,
            )
            tool_brep, section_edges, hl_intersection, hfp, lfp, lg = builder.build()

            self.Juansha__ToolBrep = tool_brep
            self.Juansha__SectionEdges = section_edges
            self.Juansha__HL_Intersection = hl_intersection
            self.Juansha__HeightFacePlane = hfp
            self.Juansha__LengthFacePlane = lfp
            self.Juansha__Log = lg

            self.Log.append('[STEP11][Juansha] OK')
        except Exception as e:
            self.Juansha__ToolBrep = None
            self.Juansha__SectionEdges = None
            self.Juansha__HL_Intersection = None
            self.Juansha__HeightFacePlane = None
            self.Juansha__LengthFacePlane = None
            self.Juansha__Log = ['[ERROR] Juansha: {}'.format(e)]
            self.Log.append('[ERROR] Step11 Juansha 出错: {}'.format(e))

        # ========== Step 11-3：GeoAligner::9（对齐卷杀刀具）==========
        try:
            geo_in = getattr(self, 'Juansha__ToolBrep', None)
            source_plane = getattr(self, 'Juansha__LengthFacePlane', None)
            target_plane = getattr(self, 'PlaneFromLists_7__ResultPlane', None)

            rotate_deg = self.all_get('GeoAligner_9__RotateDeg', 0.0, prefer_input=GeoAligner_9__RotateDeg)
            flip_x = self.all_get('GeoAligner_9__FlipX', False, prefer_input=GeoAligner_9__FlipX)
            flip_y = self.all_get('GeoAligner_9__FlipY', False, prefer_input=GeoAligner_9__FlipY)
            flip_z = self.all_get('GeoAligner_9__FlipZ', False, prefer_input=GeoAligner_9__FlipZ)
            move_x = self.all_get('GeoAligner_9__MoveX', 0.0, prefer_input=GeoAligner_9__MoveX)
            move_y = self.all_get('GeoAligner_9__MoveY', 0.0, prefer_input=GeoAligner_9__MoveY)
            move_z = self.all_get('GeoAligner_9__MoveZ', 0.0, prefer_input=GeoAligner_9__MoveZ)

            geo_is_tree = _is_gh_tree(geo_in)
            geo_branches = _tree_to_branches(geo_in) if geo_is_tree else [to_list(geo_in)]

            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
                1,
            )

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append('i={} OK'.format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            def _shrink_like_geo(v):
                if geo_is_tree:
                    return v
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list):
                        if isinstance(geo_in, (list, tuple)):
                            return vv
                        if len(vv) == 1:
                            return vv[0]
                        return vv
                    return vv
                return v

            self.GeoAligner_9__SourceOut = _shrink_like_geo(out_source)
            self.GeoAligner_9__TargetOut = _shrink_like_geo(out_target)
            self.GeoAligner_9__TransformOut = _shrink_like_geo(out_xf)
            self.GeoAligner_9__MovedGeo = flatten_any(_shrink_like_geo(out_moved))
            self.GeoAligner_9__Log = out_lg

            self.Log.append('[STEP11][GeoAligner::9] OK')
        except Exception as e:
            self.GeoAligner_9__SourceOut = None
            self.GeoAligner_9__TargetOut = None
            self.GeoAligner_9__TransformOut = None
            self.GeoAligner_9__MovedGeo = None
            self.GeoAligner_9__Log = ['[ERROR] GeoAligner::9: {}'.format(e)]
            self.Log.append('[ERROR] Step11 GeoAligner::9 出错: {}'.format(e))

        return self


    # ------------------------------------------------------
    # Step 12：BlockCutter::5 + GeoAligner::10
    # ------------------------------------------------------
    def step12_blockcutter_5_geoaligner_10(
        self,
        BlockCutter_5__length_fen=None,
        BlockCutter_5__width_fen=None,
        BlockCutter_5__height_fen=None,
        base_point=None,
        reference_plane=None,
        GeoAligner_10__SourcePlane=None,
        GeoAligner_10__RotateDeg=None,
        GeoAligner_10__FlipX=None,
        GeoAligner_10__FlipY=None,
        GeoAligner_10__FlipZ=None,
        GeoAligner_10__MoveX=None,
        GeoAligner_10__MoveY=None,
        GeoAligner_10__MoveZ=None,
    ):
        """严格按图连线实现 Step12。

        组件链：
          BlockCutter::5（多值尺寸 -> 多个 TimberBrep）
          -> List Item（FacePlaneList + Index(tree/list), Wrap=True -> SourcePlane）
          -> GeoAligner::10（Geo=TimberBrep, SourcePlane=Item, TargetPlane=复用 GeoAligner::6 的 TargetPlane）

        关键约束：
        - 参数优先级：输入端 > AllDict > 默认。
        - BlockCutter 尺寸支持多值：按索引位置对齐；长度不一致按 GH 广播对齐（短列表循环/补齐）。
        - GeoAligner::10 的 TargetPlane 必须与 GeoAligner::6 的 TargetPlane 同一来源（直接复用 self.GeoAligner_6__TargetPlane_Item）。
        - Geo/SourcePlane 支持 Tree/list：按 GH 数据树分支循环；TargetPlane 若为单值则对所有分支广播。
        - GeoAligner_10__MovedGeo 输出必须完全 flatten。
        - 不使用 sticky。
        """

        # ========== Step 12A：BlockCutter::5 ==========
        try:
            # base_point：输入端 > 默认原点
            bp_in = base_point
            if bp_in is None:
                bp_in = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp_in, rg.Point):
                bp_in = bp_in.Location

            # reference_plane：输入端 > DB > 默认 GH XZ Plane
            rp_in = self.all_get(
                "BlockCutter_5__reference_plane",
                None,
                prefer_input=reference_plane,
            )
            if rp_in is None:
                rp_in = gh_plane_XZ(bp_in)

            # length/width/height：输入端 > DB > 默认
            length_fen_in = self.all_get(
                "BlockCutter_5__length_fen",
                32.0,
                prefer_input=BlockCutter_5__length_fen,
            )
            width_fen_in = self.all_get(
                "BlockCutter_5__width_fen",
                32.0,
                prefer_input=BlockCutter_5__width_fen,
            )
            height_fen_in = self.all_get(
                "BlockCutter_5__height_fen",
                20.0,
                prefer_input=BlockCutter_5__height_fen,
            )

            def _to_float_safe(x, d):
                try:
                    return float(x) if x is not None else float(d)
                except Exception:
                    return float(d)

            def _as_scalar_list(v, default_scalar):
                """把输入转换为一维标量列表（支持 tree/嵌套 list）。"""
                if v is None:
                    return [float(default_scalar)]
                if _is_gh_tree(v) or isinstance(v, (list, tuple)):
                    flat = flatten_any(v)
                    if len(flat) == 0:
                        return [float(default_scalar)]
                    return [_to_float_safe(it, default_scalar) for it in flat]
                return [_to_float_safe(v, default_scalar)]

            L = _as_scalar_list(length_fen_in, 32.0)
            W = _as_scalar_list(width_fen_in, 32.0)
            H = _as_scalar_list(height_fen_in, 20.0)
            n = max(len(L), len(W), len(H), 1)

            Lb = _broadcast_param(L, n, name="BlockCutter_5__length_fen")
            Wb = _broadcast_param(W, n, name="BlockCutter_5__width_fen")
            Hb = _broadcast_param(H, n, name="BlockCutter_5__height_fen")

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            log_lines_all = []

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
                    _to_float_safe(Lb[i], 32.0),
                    _to_float_safe(Wb[i], 32.0),
                    _to_float_safe(Hb[i], 20.0),
                    bp_in,
                    rp_in,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                log_lines_all.append(log_lines)

            self.BlockCutter_5__TimberBrep = timber_breps[0] if n == 1 else timber_breps
            self.BlockCutter_5__FaceList = faces_list[0] if n == 1 else faces_list
            self.BlockCutter_5__PointList = points_list[0] if n == 1 else points_list
            self.BlockCutter_5__EdgeList = edges_list[0] if n == 1 else edges_list
            self.BlockCutter_5__CenterPoint = center_pts[0] if n == 1 else center_pts
            self.BlockCutter_5__CenterAxisLines = center_axes_list[0] if n == 1 else center_axes_list
            self.BlockCutter_5__EdgeMidPoints = edge_midpts_list[0] if n == 1 else edge_midpts_list
            self.BlockCutter_5__FacePlaneList = face_planes_list[0] if n == 1 else face_planes_list
            self.BlockCutter_5__Corner0Planes = corner0_planes_list[0] if n == 1 else corner0_planes_list
            self.BlockCutter_5__LocalAxesPlane = local_axes_planes[0] if n == 1 else local_axes_planes
            self.BlockCutter_5__AxisX = axis_x_list[0] if n == 1 else axis_x_list
            self.BlockCutter_5__AxisY = axis_y_list[0] if n == 1 else axis_y_list
            self.BlockCutter_5__AxisZ = axis_z_list[0] if n == 1 else axis_z_list
            self.BlockCutter_5__FaceDirTags = face_tags_list[0] if n == 1 else face_tags_list
            self.BlockCutter_5__EdgeDirTags = edge_tags_list[0] if n == 1 else edge_tags_list
            self.BlockCutter_5__Corner0EdgeDirs = corner0_dirs_list[0] if n == 1 else corner0_dirs_list
            self.BlockCutter_5__Log = log_lines_all[0] if n == 1 else log_lines_all

            self.Log.append("[STEP12][BlockCutter::5] OK")
        except Exception as e:
            self.BlockCutter_5__TimberBrep = None
            self.BlockCutter_5__FaceList = []
            self.BlockCutter_5__PointList = []
            self.BlockCutter_5__EdgeList = []
            self.BlockCutter_5__CenterPoint = None
            self.BlockCutter_5__CenterAxisLines = []
            self.BlockCutter_5__EdgeMidPoints = []
            self.BlockCutter_5__FacePlaneList = []
            self.BlockCutter_5__Corner0Planes = []
            self.BlockCutter_5__LocalAxesPlane = None
            self.BlockCutter_5__AxisX = None
            self.BlockCutter_5__AxisY = None
            self.BlockCutter_5__AxisZ = None
            self.BlockCutter_5__FaceDirTags = []
            self.BlockCutter_5__EdgeDirTags = []
            self.BlockCutter_5__Corner0EdgeDirs = []
            self.BlockCutter_5__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step12 BlockCutter::5 出错: {}".format(e))

        # ========== Step 12B：List Item（FacePlaneList -> SourcePlane）==========
        try:
            idx_in = self.all_get(
                "GeoAligner_10__SourcePlane",
                0,
                prefer_input=GeoAligner_10__SourcePlane,
            )
            wrap = True
            face_plane_list = getattr(self, "BlockCutter_5__FacePlaneList", None)

            # 多 timber：FacePlaneList 为 list[face_planes]
            if isinstance(face_plane_list, list) and len(face_plane_list) > 0 and isinstance(face_plane_list[0], (list, tuple)):
                n_geo = len(face_plane_list)
                idx_flat = flatten_any(idx_in) if (_is_gh_tree(idx_in) or isinstance(idx_in, (list, tuple))) else [idx_in]
                if len(idx_flat) == 0:
                    idx_flat = [0]
                idx_b = _broadcast_param(idx_flat, n_geo, name="GeoAligner_10__SourcePlane")
                src_planes = []
                for gi in range(n_geo):
                    src_planes.append(_list_item(face_plane_list[gi], idx_b[gi], wrap=wrap))
                self.GeoAligner_10__SourcePlane_Item = src_planes[0] if n_geo == 1 else src_planes
            else:
                idx_branches = _as_branch_list(idx_in)
                src_out = []
                for br in idx_branches:
                    if br is None or (isinstance(br, list) and len(br) == 0):
                        br = [0]
                    b_items = []
                    for i in to_list(br):
                        b_items.append(_list_item(face_plane_list, i, wrap=wrap))
                    src_out.append(b_items)
                if len(src_out) == 1:
                    src_out = src_out[0]
                    if isinstance(src_out, list) and len(src_out) == 1:
                        src_out = src_out[0]
                self.GeoAligner_10__SourcePlane_Item = src_out

            self.Log.append("[STEP12][List Item SourcePlane] OK")
        except Exception as e:
            self.GeoAligner_10__SourcePlane_Item = None
            self.Log.append("[ERROR] Step12 List Item(SourcePlane) 出错: {}".format(e))

        # ========== Step 12C：GeoAligner::10（对齐）==========
        try:
            geo_in = getattr(self, "BlockCutter_5__TimberBrep", None)
            source_plane = getattr(self, "GeoAligner_10__SourcePlane_Item", None)

            # ✅ TargetPlane：必须复用 Step8 / GeoAligner::6 的 TargetPlane 来源
            target_plane = getattr(self, "GeoAligner_6__TargetPlane_Item", None)
            if target_plane is None:
                # 极端容错：若旧版本未生成 _TargetPlane_Item，则尝试取 _TargetOut
                target_plane = getattr(self, "GeoAligner_6__TargetOut", None)

            rotate_deg = self.all_get("GeoAligner_10__RotateDeg", 0.0, prefer_input=GeoAligner_10__RotateDeg)
            flip_x = self.all_get("GeoAligner_10__FlipX", False, prefer_input=GeoAligner_10__FlipX)
            flip_y = self.all_get("GeoAligner_10__FlipY", False, prefer_input=GeoAligner_10__FlipY)
            flip_z = self.all_get("GeoAligner_10__FlipZ", False, prefer_input=GeoAligner_10__FlipZ)
            move_x = self.all_get("GeoAligner_10__MoveX", 0.0, prefer_input=GeoAligner_10__MoveX)
            move_y = self.all_get("GeoAligner_10__MoveY", 0.0, prefer_input=GeoAligner_10__MoveY)
            move_z = self.all_get("GeoAligner_10__MoveZ", 0.0, prefer_input=GeoAligner_10__MoveZ)

            geo_is_tree = _is_gh_tree(geo_in)
            geo_branches = _tree_to_branches(geo_in) if geo_is_tree else [to_list(geo_in)]

            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
                1,
            )

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            def _shrink_like_geo(v):
                if geo_is_tree:
                    return v
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list):
                        if isinstance(geo_in, (list, tuple)):
                            return vv
                        if len(vv) == 1:
                            return vv[0]
                        return vv
                    return vv
                return v

            self.GeoAligner_10__SourceOut = _shrink_like_geo(out_source)
            self.GeoAligner_10__TargetOut = _shrink_like_geo(out_target)
            self.GeoAligner_10__TransformOut = _shrink_like_geo(out_xf)
            self.GeoAligner_10__MovedGeo = flatten_any(_shrink_like_geo(out_moved))
            self.GeoAligner_10__Log = out_lg

            self.Log.append("[STEP12][GeoAligner::10] OK")
        except Exception as e:
            self.GeoAligner_10__SourceOut = None
            self.GeoAligner_10__TargetOut = None
            self.GeoAligner_10__TransformOut = None
            self.GeoAligner_10__MovedGeo = None
            self.GeoAligner_10__Log = ["[ERROR] GeoAligner::10: {}".format(e)]
            self.Log.append("[ERROR] Step12 GeoAligner::10 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step 2：原始木料构建（BuildTimberBlockUniform_SkewAxis_M）
    # ------------------------------------------------------
    def step13_cut_timbers_by_tools(self, timbers=None, tools=None, tol=None):
        """Step 13：CutTimbersByTools（严格对齐 GH 组件实现）

        对齐目标代码逻辑：
        _dbg_in = None
        _ki_in = KeepInside if "KeepInside" in globals() else False
        cutter = FT_CutTimbersByTools_GH_SolidDifference(...)
        CutTimbers, FailTimbers, Log = cutter.cut(timbers=Timbers, tools=Tools, keep_inside=_ki_in, debug=_dbg_in)
        """
        try:
            # ---- 1) 输入准备（保持你现有 solver 传参方式）----
            if timbers is None:
                timbers = getattr(self, 'TimberBrep', None)
            if tools is None:
                tools = []
                for i in range(1, 11):
                    tools.append(getattr(self, 'GeoAligner_{}__MovedGeo'.format(i), None))

            # 仍然保留一份原始输入到 developer-friendly 输出
            self.CutTimbersByTools__Timbers = timbers
            self.CutTimbersByTools__Tools = tools

            # ---- 2) 严格对齐 GH 组件变量/流程 ----
            _dbg_in = None
            _ki_in = False

            cutter = FT_CutTimbersByTools_GH_SolidDifference(
                debug=bool(_dbg_in) if _dbg_in is not None else False
            )

            CutTimbers, FailTimbers, Log = cutter.cut(
                timbers=timbers,
                tools=tools,
                keep_inside=_ki_in,
                debug=_dbg_in
            )

            # ---- 3) 输出绑定（与全文件命名风格一致）----
            self.CutTimbersByTools__CutTimbers = CutTimbers
            self.CutTimbersByTools__FailTimbers = FailTimbers
            self.CutTimbersByTools__Log = Log

            self.Log.append("[Step13] CutTimbersByTools OK (KeepInside={})".format(_ki_in))

        except Exception as e:
            self.CutTimbersByTools__CutTimbers = None
            self.CutTimbersByTools__FailTimbers = [{'error': str(e)}]
            self.CutTimbersByTools__Log = ['[Step13][EXCEPTION] {}'.format(e)]
            self.Log.append("[ERROR] Step13 CutTimbersByTools 出错: {}".format(e))

        return self


    def step2_timber(self):
        """参数优先级：组件输入端 > 数据库 > 默认值。"""

        # --- 1) base_point：组件输入端; None → 原点 ---
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location
        elif isinstance(bp, rg.Point3d):
            pass
        else:
            # 尝试从 (x,y,z)
            try:
                bp = rg.Point3d(float(bp[0]), float(bp[1]), float(bp[2]))
            except Exception:
                bp = rg.Point3d(0.0, 0.0, 0.0)
                self.Log.append("[TIMBER] base_point 类型不识别，已回退原点")

        # --- 2) 参考平面：默认 GH XZ Plane ---
        reference_plane = gh_plane_XZ(bp)

        # --- 3) 尺寸：来自 DB 或默认 ---
        length_raw = self.all_get("BuildTimberBlockUniform_SkewAxis_M__length_fen", 32.0)
        width_raw = self.all_get("BuildTimberBlockUniform_SkewAxis_M__width_fen", 32.0)
        height_raw = self.all_get("BuildTimberBlockUniform_SkewAxis_M__height_fen", 20.0)
        skew_raw = self.all_get("BuildTimberBlockUniform_SkewAxis_M__Skew_len", 20.0)

        try:
            length_fen = float(length_raw) if length_raw is not None else 32.0
            width_fen = float(width_raw) if width_raw is not None else 32.0
            height_fen = float(height_raw) if height_raw is not None else 20.0
        except Exception as e:
            self.Log.append("[TIMBER] length/width/height 转换失败，使用默认值: {}".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        # Skew_len 允许多值（按组件实现：TimberBrep 仍应输出单个 closed brep）
        skew_len = skew_raw
        if skew_len is None:
            skew_len = 20.0

        try:
            _obj = BuildTimberBlockUniform_SkewAxis_M(
                length_fen,
                width_fen,
                height_fen,
                bp,
                reference_plane,
                skew_len,
            )

            # TimberBrep：直接采用组件输出（不做兼容展开）
            _tb = getattr(_obj, "TimberBrep", None)
            self.TimberBrep = _tb
            self.FaceList = getattr(_obj, "FaceList", [])
            self.PointList = getattr(_obj, "PointList", [])
            self.EdgeList = getattr(_obj, "EdgeList", [])
            self.CenterPoint = getattr(_obj, "CenterPoint", None)
            self.CenterAxisLines = getattr(_obj, "CenterAxisLines", [])
            self.EdgeMidPoints = getattr(_obj, "EdgeMidPoints", [])
            self.FacePlaneList = getattr(_obj, "FacePlaneList", [])
            self.Corner0Planes = getattr(_obj, "Corner0Planes", [])

            # 与其它 Solver 命名保持一致的别名（供后续 PlaneFromLists::7 等步骤直接引用）
            self.BuildTimberBlockUniform_SkewAxis_M__EdgeMidPoints = self.EdgeMidPoints
            self.BuildTimberBlockUniform_SkewAxis_M__Corner0Planes = self.Corner0Planes
            self.LocalAxesPlane = getattr(_obj, "LocalAxesPlane", None)
            self.AxisX = getattr(_obj, "AxisX", None)
            self.AxisY = getattr(_obj, "AxisY", None)
            self.AxisZ = getattr(_obj, "AxisZ", None)
            self.FaceDirTags = getattr(_obj, "FaceDirTags", [])
            self.EdgeDirTags = getattr(_obj, "EdgeDirTags", [])
            self.Corner0EdgeDirs = getattr(_obj, "Corner0EdgeDirs", [])
            self.TimberLog = getattr(_obj, "Log", [])

            # Skew 扩展
            self.Skew_A = getattr(_obj, "Skew_A", None)
            self.Skew_Point_B = getattr(_obj, "Skew_Point_B", None)
            self.Skew_Point_C = getattr(_obj, "Skew_Point_C", None)
            self.Skew_Planes = getattr(_obj, "Skew_Planes", None)
            self.Skew_ExtraPoints_GF_EH = getattr(_obj, "Skew_ExtraPoints_GF_EH", None)

            self.Log.append("[TIMBER] BuildTimberBlockUniform_SkewAxis_M 完成")
            for l in (self.TimberLog or []):
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            self.TimberBrep = None
            self.TimberLog = ["主逻辑错误: {}".format(e)]
            self.Log.append("[ERROR] step2_timber 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3：耍头刀具生成 + 抽取目标平面 + 对齐（ShuaTou + PlaneFromLists::1 + GeoAligner::1）
    # ------------------------------------------------------
    def step3_shua_tou_align(self):
        """严格按 GH 数据流实现 Step3。

        组件链：
          ShuaTou -> PlaneFromLists::1 -> ListItem(RefPlanes) -> GeoAligner::1
        """

        # ========== Step 3A：ShuaTou ==========
        try:
            bp = self.base_point
            if bp is None:
                bp = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp, rg.Point):
                bp = bp.Location

            ref_plane = self.all_get("ShuaTou__RefPlane", None)
            if ref_plane is None:
                # 与 ShuaTou 组件默认一致（GH XZ）
                ref_plane = gh_plane_XZ(bp)

            width_fen = self.all_get("ShuaTou__WidthFen", None)
            height_fen = self.all_get("ShuaTou__HeightFen", None)
            AH_fen = self.all_get("ShuaTou__AH_Fen", None)
            DF_fen = self.all_get("ShuaTou__DF_Fen", None)
            FE_fen = self.all_get("ShuaTou__FE_Fen", None)
            EC_fen = self.all_get("ShuaTou__EC_Fen", None)
            DG_fen = self.all_get("ShuaTou__DG_Fen", None)
            offset_fen = self.all_get("ShuaTou__OffsetFen", None)

            (self.ShuaTou__CenterSectionCrv,
             self.ShuaTou__SideSectionCrv,
             self.ShuaTou__CenterSectionFace,
             self.ShuaTou__SideSectionFace,
             self.ShuaTou__OffsetSideFaces,
             self.ShuaTou__OffsetSideCrvs,
             self.ShuaTou__SideLoftFace,
             self.ShuaTou__ToolBrep,
             self.ShuaTou__RefPlanes,
             self.ShuaTou__DebugPoints,
             self.ShuaTou__DebugLines,
             self.ShuaTou__Log) = ShuaTouBuilder.build(
                bp,
                ref_plane,
                width_fen,
                height_fen,
                AH_fen,
                DF_fen,
                FE_fen,
                EC_fen,
                DG_fen,
                offset_fen,
            )

            self.Log.append("[STEP3][ShuaTou] OK")
        except Exception as e:
            self.ShuaTou__ToolBrep = None
            self.ShuaTou__RefPlanes = None
            self.ShuaTou__Log = ["[ERROR] ShuaTou: {}".format(e)]
            self.Log.append("[ERROR] Step3 ShuaTou 出错: {}".format(e))

        # ========== Step 3B：PlaneFromLists::1 ==========
        try:
            origin_points = getattr(self, "EdgeMidPoints", None)
            base_planes = getattr(self, "Corner0Planes", None)

            idx_origin = self.all_get("PlaneFromLists_1__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_1__IndexPlane", None)
            wrap = self.all_get("PlaneFromLists_1__Wrap", True)

            # Tree / list 广播：逐分支计算，每分支内按 GH 风格广播对齐
            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    # GH：无索引时仍调用一次（但结果可能 None）
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            # 约定：若只有 1 个分支，退化为 list；若 list 里只有 1 项，退化为单值
            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_1__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_1__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_1__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_1__Log = out_log

            self.Log.append("[STEP3][PlaneFromLists::1] OK")
        except Exception as e:
            self.PlaneFromLists_1__BasePlane = None
            self.PlaneFromLists_1__OriginPoint = None
            self.PlaneFromLists_1__ResultPlane = None
            self.PlaneFromLists_1__Log = ["[ERROR] PlaneFromLists::1: {}".format(e)]
            self.Log.append("[ERROR] Step3 PlaneFromLists::1 出错: {}".format(e))

        # ========== Step 3C：List Item（ShuaTou.RefPlanes -> SourcePlane） ==========
        try:
            ref_planes = self.ShuaTou__RefPlanes
            idx_sp = self.all_get("GeoAligner_1__SourcePlane", 0)
            wrap_li = self.all_get("ListItem_ShuaTouRefPlanes__Wrap", True)

            idx_sp_branches = _as_branch_list(idx_sp)
            out_items = []
            out_lg = []

            for bi, br in enumerate(idx_sp_branches):
                br_items = []
                br_lg = []
                if not isinstance(br, list):
                    br = to_list(br)
                if len(br) == 0:
                    br = [0]
                for ii in br:
                    it = _list_item(ref_planes, ii, wrap=bool(wrap_li))
                    br_items.append(it)
                    br_lg.append("idx={} -> {}".format(ii, "OK" if it is not None else "None"))
                out_items.append(br_items)
                out_lg.append(br_lg)

            # shrink
            if len(out_items) == 1:
                out_items = out_items[0]
                if isinstance(out_items, list) and len(out_items) == 1:
                    out_items = out_items[0]
            self.ListItem_ShuaTouRefPlanes__Item = out_items
            self.ListItem_ShuaTouRefPlanes__Log = out_lg

            self.Log.append("[STEP3][ListItem] OK")
        except Exception as e:
            self.ListItem_ShuaTouRefPlanes__Item = None
            self.ListItem_ShuaTouRefPlanes__Log = ["[ERROR] ListItem: {}".format(e)]
            self.Log.append("[ERROR] Step3 ListItem 出错: {}".format(e))

        # ========== Step 3D：GeoAligner::1 ==========
        try:
            geo = self.ShuaTou__ToolBrep
            source_plane = self.ListItem_ShuaTouRefPlanes__Item
            target_plane = self.PlaneFromLists_1__ResultPlane

            rotate_deg = self.all_get("GeoAligner_1__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_1__FlipX", False)
            flip_y = self.all_get("GeoAligner_1__FlipY", False)
            flip_z = self.all_get("GeoAligner_1__FlipZ", False)
            move_x = self.all_get("GeoAligner_1__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_1__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_1__MoveZ", 0.0)

            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                # 分支内广播
                n = _max_len(sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_g = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        geo,
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_g.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_g)
                out_lg.append(b_log)

            # shrink
            def _shrink2(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.GeoAligner_1__SourceOut = _shrink2(out_source)
            self.GeoAligner_1__TargetOut = _shrink2(out_target)
            self.GeoAligner_1__MovedGeo = _shrink2(out_moved)
            self.GeoAligner_1__TransformOut = _shrink2(out_xf)
            self.GeoAligner_1__Log = out_lg

            self.Log.append("[STEP3][GeoAligner::1] OK")
        except Exception as e:
            self.GeoAligner_1__SourceOut = None
            self.GeoAligner_1__TargetOut = None
            self.GeoAligner_1__MovedGeo = None
            self.GeoAligner_1__TransformOut = None
            self.GeoAligner_1__Log = ["[ERROR] GeoAligner::1: {}".format(e)]
            self.Log.append("[ERROR] Step3 GeoAligner::1 出错: {}".format(e))

        return self

        return self

    # ------------------------------------------------------
    # Step 4：起翘刀具生成 + 抽取 Source/TargetPlane + 对齐
    # （QiAOTool::1 + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::2）
    # ------------------------------------------------------
    def step4_qiao_tool_align(self):
        """严格按 GH 数据流实现 Step4。

        组件链：
          QiAOTool::1 -> PlaneFromLists::2 (TargetPlane, from main timber)
                        -> PlaneFromLists::3 (SourcePlane, from QiAOTool)
                        -> GeoAligner::2 (align tool geo)

        注意：
        - 不再读库；所有参数走 self.all_get。
        - PlaneFromLists 与 GeoAligner 需要按 GH 广播与 Tree 分支循环。
        """

        # ========== Step 4A：QiAOTool::1 ==========
        try:
            bp = self.base_point
            if bp is None:
                bp = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp, rg.Point):
                bp = bp.Location

            # 输入参数：优先 GH 输入端（本组件通常无这些输入端）> AllDict > 默认
            _length_fen = self.all_get("QiAOTool_1__length_fen", None)
            _width_fen = self.all_get("QiAOTool_1__width_fen", None)
            _height_fen = self.all_get("QiAOTool_1__height_fen", None)
            _qi_height = self.all_get("QiAOTool_1__qi_height", None)
            _sha_width = self.all_get("QiAOTool_1__sha_width", None)
            _qi_offset_fen = self.all_get("QiAOTool_1__qi_offset_fen", None)
            _extrude_length = self.all_get("QiAOTool_1__extrude_length", None)
            _extrude_positive = self.all_get("QiAOTool_1__extrude_positive", None)
            _timber_ref_plane_mode = self.all_get("QiAOTool_1__timber_ref_plane_mode", None)
            _qi_ref_plane_mode = self.all_get("QiAOTool_1__qi_ref_plane_mode", None)

            def _to_float(x, default):
                try:
                    if x is None:
                        return float(default)
                    return float(x)
                except Exception:
                    return float(default)

            params = {
                # timber
                "length_fen": _to_float(_length_fen, 41.0),
                "width_fen": _to_float(_width_fen, 16.0),
                "height_fen": _to_float(_height_fen, 10.0),
                "base_point": bp,
                "timber_ref_plane": GHPlaneFactory.make(
                    _timber_ref_plane_mode if _timber_ref_plane_mode is not None else "XZ",
                    origin=bp,
                ),
                # qiao
                "qi_height": _to_float(_qi_height, 4.0),
                "sha_width": _to_float(_sha_width, 2.0),
                "qi_offset_fen": _to_float(_qi_offset_fen, 0.5),
                "extrude_length": _to_float(_extrude_length, 28.0),
                "extrude_positive": InputHelper.to_bool(
                    _extrude_positive if _extrude_positive is not None else False,
                    default=False,
                ),
                "qi_ref_plane": GHPlaneFactory.make(
                    _qi_ref_plane_mode if _qi_ref_plane_mode is not None else "XZ",
                    origin=bp,
                ),
            }

            solver = QiAoToolSolver(ghenv=self.ghenv)
            solver.run(params)

            # 组件核心输出
            self.QiAOTool_1__CutTimbers = getattr(solver, "CutTimbers", None)
            self.QiAOTool_1__FailTimbers = getattr(solver, "FailTimbers", None)
            self.QiAOTool_1__Log = getattr(solver, "Log", [])
            self.QiAOTool_1__EdgeMidPoints = getattr(solver, "EdgeMidPoints", None)
            self.QiAOTool_1__Corner0Planes = getattr(solver, "Corner0Planes", None)

            # 其它调试输出（若存在）
            self.QiAOTool_1__TimberBrep = getattr(solver, "TimberBrep", None)
            self.QiAOTool_1__ToolBrep = getattr(solver, "ToolBrep", None)
            self.QiAOTool_1__AlignedTool = getattr(solver, "AlignedTool", None)
            self.QiAOTool_1__RefPlanes = getattr(solver, "RefPlanes", None)
            self.QiAOTool_1__PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
            self.QiAOTool_1__QiAo_FacePlane = getattr(solver, "QiAo_FacePlane", None)

            self.Log.append("[STEP4][QiAOTool::1] OK")
        except Exception as e:
            self.QiAOTool_1__CutTimbers = None
            self.QiAOTool_1__FailTimbers = None
            self.QiAOTool_1__EdgeMidPoints = None
            self.QiAOTool_1__Corner0Planes = None
            self.QiAOTool_1__Log = ["[ERROR] QiAOTool::1: {}".format(e)]
            self.Log.append("[ERROR] Step4 QiAOTool::1 出错: {}".format(e))

        # ========== Step 4B：PlaneFromLists::2（主木坯 -> TargetPlane） ==========
        try:
            origin_points = getattr(self, "EdgeMidPoints", None)
            base_planes = getattr(self, "Corner0Planes", None)

            idx_origin = self.all_get("PlaneFromLists_2__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_2__IndexPlane", None)
            wrap = self.all_get("PlaneFromLists_2__Wrap", True)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_2__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_2__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_2__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_2__Log = out_log

            self.Log.append("[STEP4][PlaneFromLists::2] OK")
        except Exception as e:
            self.PlaneFromLists_2__BasePlane = None
            self.PlaneFromLists_2__OriginPoint = None
            self.PlaneFromLists_2__ResultPlane = None
            self.PlaneFromLists_2__Log = ["[ERROR] PlaneFromLists::2: {}".format(e)]
            self.Log.append("[ERROR] Step4 PlaneFromLists::2 出错: {}".format(e))

        # ========== Step 4C：PlaneFromLists::3（QiAOTool -> SourcePlane） ==========
        try:
            origin_points = getattr(self, "QiAOTool_1__EdgeMidPoints", None)
            base_planes = getattr(self, "QiAOTool_1__Corner0Planes", None)

            idx_origin = self.all_get("PlaneFromLists_3__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_3__IndexPlane", None)
            wrap = self.all_get("PlaneFromLists_3__Wrap", True)

            idx_origin_branches = _as_branch_list(idx_origin)
            idx_plane_branches = _as_branch_list(idx_plane)
            bcount = max(len(idx_origin_branches), len(idx_plane_branches))

            builder = FTPlaneFromLists(wrap=bool(wrap))

            out_base_plane = []
            out_origin_point = []
            out_result_plane = []
            out_log = []

            for bi in range(bcount):
                o_list = idx_origin_branches[bi] if bi < len(idx_origin_branches) else idx_origin_branches[-1]
                p_list = idx_plane_branches[bi] if bi < len(idx_plane_branches) else idx_plane_branches[-1]

                n = _max_len(o_list, p_list)
                if n <= 0:
                    n = 1
                o_b = _broadcast_param(o_list, n)
                p_b = _broadcast_param(p_list, n)

                b_base = []
                b_origin = []
                b_plane = []
                b_lg = []

                for i in range(n):
                    bp_out, op_out, rp_out, lg = builder.build_plane(
                        origin_points,
                        base_planes,
                        o_b[i],
                        p_b[i],
                    )
                    b_base.append(bp_out)
                    b_origin.append(op_out)
                    b_plane.append(rp_out)
                    b_lg.append(lg)

                out_base_plane.append(b_base)
                out_origin_point.append(b_origin)
                out_result_plane.append(b_plane)
                out_log.append(b_lg)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.PlaneFromLists_3__BasePlane = _shrink(out_base_plane)
            self.PlaneFromLists_3__OriginPoint = _shrink(out_origin_point)
            self.PlaneFromLists_3__ResultPlane = _shrink(out_result_plane)
            self.PlaneFromLists_3__Log = out_log

            self.Log.append("[STEP4][PlaneFromLists::3] OK")
        except Exception as e:
            self.PlaneFromLists_3__BasePlane = None
            self.PlaneFromLists_3__OriginPoint = None
            self.PlaneFromLists_3__ResultPlane = None
            self.PlaneFromLists_3__Log = ["[ERROR] PlaneFromLists::3: {}".format(e)]
            self.Log.append("[ERROR] Step4 PlaneFromLists::3 出错: {}".format(e))

        # ========== Step 4D：GeoAligner::2 ==========
        try:
            geo_in = self.QiAOTool_1__CutTimbers
            source_plane = self.PlaneFromLists_3__ResultPlane
            target_plane = self.PlaneFromLists_2__ResultPlane

            rotate_deg = self.all_get("GeoAligner_2__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_2__FlipX", False)
            flip_y = self.all_get("GeoAligner_2__FlipY", False)
            flip_z = self.all_get("GeoAligner_2__FlipZ", False)
            move_x = self.all_get("GeoAligner_2__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_2__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_2__MoveZ", 0.0)

            # Geo：Tree / list / item
            geo_is_tree = _is_gh_tree(geo_in)
            geo_branches = _tree_to_branches(geo_in) if geo_is_tree else [to_list(geo_in)]

            sp_branches = _as_branch_list(source_plane)
            tp_branches = _as_branch_list(target_plane)
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            def _shrink_like_geo(v):
                # 对于 geo 非 tree 的情况：把单分支退化；若仍单项再退化
                if geo_is_tree:
                    return v
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    # vv 是分支 list
                    if isinstance(vv, list):
                        if isinstance(geo_in, (list, tuple)):
                            return vv
                        if len(vv) == 1:
                            return vv[0]
                        return vv
                    return vv
                return v

            self.GeoAligner_2__SourceOut = _shrink_like_geo(out_source)
            self.GeoAligner_2__TargetOut = _shrink_like_geo(out_target)
            self.GeoAligner_2__MovedGeo = flatten_any(_shrink_like_geo(out_moved))
            self.GeoAligner_2__TransformOut = _shrink_like_geo(out_xf)
            self.GeoAligner_2__Log = out_lg

            self.Log.append("[STEP4][GeoAligner::2] OK")
        except Exception as e:
            self.GeoAligner_2__SourceOut = None
            self.GeoAligner_2__TargetOut = None
            self.GeoAligner_2__MovedGeo = None
            self.GeoAligner_2__TransformOut = None
            self.GeoAligner_2__Log = ["[ERROR] GeoAligner::2: {}".format(e)]
            self.Log.append("[ERROR] Step4 GeoAligner::2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5：BlockCutter::1 + GeoAligner::3
    # ------------------------------------------------------
    def step5_blockcutter_1_geoaligner_3(self,
                                        BlockCutter_1__length_fen=None,
                                        BlockCutter_1__width_fen=None,
                                        BlockCutter_1__height_fen=None,
                                        reference_plane=None,
                                        GeoAligner_3__SourcePlane=None,
                                        GeoAligner_3__TargetPlane_path=None,
                                        GeoAligner_3__TargetPlane_index=None,
                                        GeoAligner_3__RotateDeg=None,
                                        GeoAligner_3__FlipX=None,
                                        GeoAligner_3__FlipY=None,
                                        GeoAligner_3__FlipZ=None,
                                        GeoAligner_3__MoveX=None,
                                        GeoAligner_3__MoveY=None,
                                        GeoAligner_3__MoveZ=None):
        """严格按图连线实现 Step5。

        组件链：
          BlockCutter::1 -> Graft Tree (TimberBrep)
                        -> List Item (FacePlaneList -> SourcePlane)
                        -> Tree Item (Skew_Planes -> TargetPlane)
                        -> GeoAligner::3

        注意：
        - 不再读库；参数一律走 all_get（输入端 > AllDict > 默认）。
        - 本步骤用于生成“刀具木料块”并对齐到 Skew_Planes 的指定 TargetPlane。
        - 输出端若出现嵌套：在输出绑定区统一 flatten_any。
        """

        # ========== Step 5A：BlockCutter::1 ==========
        try:
            # base_point：按组件默认世界原点（与 GH 脚本一致）
            base_point = rg.Point3d(0.0, 0.0, 0.0)

            # reference_plane：输入端 > DB > 默认 GH XZ Plane
            rp_in = self.all_get(
                "BlockCutter_1__reference_plane",
                None,
                prefer_input=reference_plane,
            )
            if rp_in is None:
                rp_in = gh_plane_XZ(base_point)

            # length/width/height：输入端 > DB > 默认
            # ⚠️ 支持多值列表：按索引位置对齐（GH 风格广播：短的用末值补齐）
            length_fen_in = self.all_get(
                "BlockCutter_1__length_fen",
                32.0,
                prefer_input=BlockCutter_1__length_fen,
            )
            width_fen_in = self.all_get(
                "BlockCutter_1__width_fen",
                32.0,
                prefer_input=BlockCutter_1__width_fen,
            )
            height_fen_in = self.all_get(
                "BlockCutter_1__height_fen",
                20.0,
                prefer_input=BlockCutter_1__height_fen,
            )

            def _to_float_safe(x, d):
                try:
                    return float(x) if x is not None else float(d)
                except Exception:
                    return float(d)

            def _as_scalar_list(v, default_scalar):
                """把输入转换为一维标量列表。

                - GH Tree / 嵌套 list → flatten_any 后再取标量
                - 标量 → [标量]
                - None/空 → [default_scalar]
                """
                if v is None:
                    return [float(default_scalar)]
                # Tree / list / tuple：优先拍平
                if _is_gh_tree(v) or isinstance(v, (list, tuple)):
                    flat = flatten_any(v)
                    if len(flat) == 0:
                        return [float(default_scalar)]
                    return [_to_float_safe(it, default_scalar) for it in flat]
                return [_to_float_safe(v, default_scalar)]

            L = _as_scalar_list(length_fen_in, 32.0)
            W = _as_scalar_list(width_fen_in, 32.0)
            H = _as_scalar_list(height_fen_in, 20.0)
            n = max(len(L), len(W), len(H), 1)

            Lb = _broadcast_param(L, n, name="length_fen")
            Wb = _broadcast_param(W, n, name="width_fen")
            Hb = _broadcast_param(H, n, name="height_fen")

            # 多块输出：按输入列表对齐生成多个 timber
            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            log_lines_all = []

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
                    _to_float_safe(Lb[i], 32.0),
                    _to_float_safe(Wb[i], 32.0),
                    _to_float_safe(Hb[i], 20.0),
                    base_point,
                    rp_in,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                log_lines_all.append(log_lines)

            # 与 GH 组件输出命名保持一致，并全部保存到 self.BlockCutter_1__XXX
            # 若仅生成 1 个对象，则按 GH 习惯输出为单值；否则为列表（后续 Graft 再变为树分支）
            self.BlockCutter_1__TimberBrep = timber_breps[0] if n == 1 else timber_breps
            self.BlockCutter_1__FaceList = faces_list[0] if n == 1 else faces_list
            self.BlockCutter_1__PointList = points_list[0] if n == 1 else points_list
            self.BlockCutter_1__EdgeList = edges_list[0] if n == 1 else edges_list
            self.BlockCutter_1__CenterPoint = center_pts[0] if n == 1 else center_pts
            self.BlockCutter_1__CenterAxisLines = center_axes_list[0] if n == 1 else center_axes_list
            self.BlockCutter_1__EdgeMidPoints = edge_midpts_list[0] if n == 1 else edge_midpts_list
            self.BlockCutter_1__FacePlaneList = face_planes_list[0] if n == 1 else face_planes_list
            self.BlockCutter_1__Corner0Planes = corner0_planes_list[0] if n == 1 else corner0_planes_list
            self.BlockCutter_1__LocalAxesPlane = local_axes_planes[0] if n == 1 else local_axes_planes
            self.BlockCutter_1__AxisX = axis_x_list[0] if n == 1 else axis_x_list
            self.BlockCutter_1__AxisY = axis_y_list[0] if n == 1 else axis_y_list
            self.BlockCutter_1__AxisZ = axis_z_list[0] if n == 1 else axis_z_list
            self.BlockCutter_1__FaceDirTags = face_tags_list[0] if n == 1 else face_tags_list
            self.BlockCutter_1__EdgeDirTags = edge_tags_list[0] if n == 1 else edge_tags_list
            self.BlockCutter_1__Corner0EdgeDirs = corner0_dirs_list[0] if n == 1 else corner0_dirs_list
            self.BlockCutter_1__Log = log_lines_all[0] if n == 1 else log_lines_all

            self.Log.append("[STEP5][BlockCutter::1] OK")
        except Exception as e:
            self.BlockCutter_1__TimberBrep = None
            self.BlockCutter_1__FacePlaneList = []
            self.BlockCutter_1__Corner0Planes = []
            self.BlockCutter_1__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step5 BlockCutter::1 出错: {}".format(e))

        # ========== Step 5B：Graft Tree（对 TimberBrep 做树分支）==========
        try:
            self.Step5__GraftedGeo = _graft_any(self.BlockCutter_1__TimberBrep)
            self.Log.append("[STEP5][Graft Tree] OK")
        except Exception as e:
            self.Step5__GraftedGeo = []
            self.Log.append("[ERROR] Step5 Graft Tree 出错: {}".format(e))

        # ========== Step 5C：List Item（FacePlaneList -> SourcePlane）==========
        try:
            idx_in = self.all_get(
                "GeoAligner_3__SourcePlane",
                0,
                prefer_input=GeoAligner_3__SourcePlane,
            )
            wrap = False
            face_plane_list = getattr(self, "BlockCutter_1__FacePlaneList", None)

            # 若 BlockCutter 生成多个 timber：FacePlaneList 将是 list[face_planes]
            # 此时 List Item 应对每个 timber 的 face_planes 分别取 index（按广播对齐）。
            if isinstance(face_plane_list, list) and len(face_plane_list) > 0 and isinstance(face_plane_list[0], (list, tuple)):
                n_geo = len(face_plane_list)
                idx_seq = idx_in
                # idx_in 若为 tree/list：拍平为一维列表，按 GH 广播末值补齐
                idx_flat = flatten_any(idx_seq) if (_is_gh_tree(idx_seq) or isinstance(idx_seq, (list, tuple))) else [idx_seq]
                if len(idx_flat) == 0:
                    idx_flat = [0]
                idx_b = _broadcast_param(idx_flat, n_geo, name="GeoAligner_3__SourcePlane")
                src_planes = []
                for gi in range(n_geo):
                    src_planes.append(_list_item(face_plane_list[gi], idx_b[gi], wrap=wrap))
                self.GeoAligner_3__SourcePlane_Item = src_planes[0] if n_geo == 1 else src_planes
            else:
                # 单 timber：维持原行为（支持 idx 为 tree/list）
                idx_branches = _as_branch_list(idx_in)

                src_out = []
                for br in idx_branches:
                    # GH：Index 可能为 list（逐项取）
                    if br is None or (isinstance(br, list) and len(br) == 0):
                        br = [0]
                    b_items = []
                    for i in to_list(br):
                        b_items.append(_list_item(face_plane_list, i, wrap=wrap))
                    src_out.append(b_items)

                # shrink：若只有 1 分支 → list；若 list 内只有 1 项 → item
                if len(src_out) == 1:
                    src_out = src_out[0]
                    if isinstance(src_out, list) and len(src_out) == 1:
                        src_out = src_out[0]

                self.GeoAligner_3__SourcePlane_Item = src_out
            self.Log.append("[STEP5][List Item SourcePlane] OK")
        except Exception as e:
            self.GeoAligner_3__SourcePlane_Item = None
            self.Log.append("[ERROR] Step5 List Item(SourcePlane) 出错: {}".format(e))

        # ========== Step 5D：Tree Item（Skew_Planes -> TargetPlane）==========
        try:
            tree_in = getattr(self, "Skew_Planes", None)
            path_in = self.all_get(
                "GeoAligner_3__TargetPlane_path",
                0,
                prefer_input=GeoAligner_3__TargetPlane_path,
            )
            index_in = self.all_get(
                "GeoAligner_3__TargetPlane_index",
                0,
                prefer_input=GeoAligner_3__TargetPlane_index,
            )
            wrap = False

            path_branches = _as_branch_list(path_in)
            index_branches = _as_branch_list(index_in)

            bcount = max(len(path_branches), len(index_branches))
            if bcount <= 0:
                bcount = 1

            out_tp = []
            for bi in range(bcount):
                pbr = path_branches[bi] if bi < len(path_branches) else path_branches[-1]
                ibr = index_branches[bi] if bi < len(index_branches) else index_branches[-1]

                # 每分支内再做 list 广播（若 pbr/ibr 是 list）
                p_list = to_list(pbr)
                i_list = to_list(ibr)
                n = _max_len(p_list, i_list)
                if n <= 0:
                    n = 1
                p_b = _broadcast_param(p_list, n)
                i_b = _broadcast_param(i_list, n)

                b_items = []
                for k in range(n):
                    b_items.append(_tree_item(tree_in, p_b[k], i_b[k], wrap=wrap))
                out_tp.append(b_items)

            if len(out_tp) == 1:
                out_tp = out_tp[0]
                if isinstance(out_tp, list) and len(out_tp) == 1:
                    out_tp = out_tp[0]

            self.GeoAligner_3__TargetPlane_Item = out_tp
            self.Log.append("[STEP5][Tree Item TargetPlane] OK")
        except Exception as e:
            self.GeoAligner_3__TargetPlane_Item = None
            self.Log.append("[ERROR] Step5 Tree Item(TargetPlane) 出错: {}".format(e))

        # ========== Step 5E：GeoAligner::3 ==========
        try:
            geo_in = self.Step5__GraftedGeo
            source_plane = self.GeoAligner_3__SourcePlane_Item
            target_plane = self.GeoAligner_3__TargetPlane_Item

            rotate_deg = self.all_get("GeoAligner_3__RotateDeg", 0.0, prefer_input=GeoAligner_3__RotateDeg)
            flip_x = self.all_get("GeoAligner_3__FlipX", False, prefer_input=GeoAligner_3__FlipX)
            flip_y = self.all_get("GeoAligner_3__FlipY", False, prefer_input=GeoAligner_3__FlipY)
            flip_z = self.all_get("GeoAligner_3__FlipZ", False, prefer_input=GeoAligner_3__FlipZ)
            move_x = self.all_get("GeoAligner_3__MoveX", 0.0, prefer_input=GeoAligner_3__MoveX)
            move_y = self.all_get("GeoAligner_3__MoveY", 0.0, prefer_input=GeoAligner_3__MoveY)
            move_z = self.all_get("GeoAligner_3__MoveZ", 0.0, prefer_input=GeoAligner_3__MoveZ)

            # GH 语义：Geo 与 SourcePlane 按分支一一对应；TargetPlane 只有一个值时
            # 需要按“列表索引”对齐到各分支（即：第 i 个分支使用 TargetPlane 列表的第 i 项，
            # 若不足则用末值补齐）。最终 MovedGeo 的对象数应等于 Geo 的分支数。
            geo_branches = geo_in if isinstance(geo_in, list) else [to_list(geo_in)]

            def _normalize_plane_branches(p, branch_count, name="plane"):
                """把 plane 输入规范化为 list[list]（branches），以匹配 geo_branches。"""
                if branch_count <= 0:
                    branch_count = 1

                # GH Tree：直接转 branches
                if _is_gh_tree(p):
                    brs = _tree_to_branches(p)
                    # 若树分支数与 geo 不一致，按 GH 广播：不足补末分支
                    if len(brs) == 0:
                        return [[None] for _ in range(branch_count)]
                    if len(brs) >= branch_count:
                        return brs[:branch_count]
                    return brs + [brs[-1]] * (branch_count - len(brs))

                # python list：区分“按分支列表”与“单分支列表”
                if isinstance(p, (list, tuple)):
                    seq = list(p)
                    if len(seq) == 0:
                        return [[None] for _ in range(branch_count)]

                    # 若是 list[list]，直接视为 branches
                    if isinstance(seq[0], (list, tuple)):
                        brs = [list(b) for b in seq]
                        if len(brs) >= branch_count:
                            return brs[:branch_count]
                        return brs + [brs[-1]] * (branch_count - len(brs))

                    # 纯一维 list：
                    # - SourcePlane：若长度==branch_count，视为“每分支一个平面”
                    # - TargetPlane：若长度!=branch_count，也作为“平面池”，按分支索引取
                    if name.lower().startswith("source") and len(seq) == branch_count:
                        return [[seq[i]] for i in range(branch_count)]

                    # 作为 pool：按分支索引取，不足补末值
                    out = []
                    for bi in range(branch_count):
                        ii = bi if bi < len(seq) else (len(seq) - 1)
                        out.append([seq[ii]])
                    return out

                # 标量 plane：广播到所有分支
                return [[p] for _ in range(branch_count)]

            branch_count = len(geo_branches)
            sp_branches = _normalize_plane_branches(source_plane, branch_count, name="SourcePlane")
            tp_branches = _normalize_plane_branches(target_plane, branch_count, name="TargetPlane")
            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches), len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[bi] if bi < len(tp_branches) else tp_branches[-1]
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            def _shrink(v):
                if not isinstance(v, list):
                    return v
                if len(v) == 1:
                    vv = v[0]
                    if isinstance(vv, list) and len(vv) == 1:
                        return vv[0]
                    return vv
                return v

            self.GeoAligner_3__SourceOut = _shrink(out_source)
            self.GeoAligner_3__TargetOut = _shrink(out_target)
            self.GeoAligner_3__MovedGeo = flatten_any(_shrink(out_moved))
            self.GeoAligner_3__TransformOut = _shrink(out_xf)
            self.GeoAligner_3__Log = out_lg

            self.Log.append("[STEP5][GeoAligner::3] OK")
        except Exception as e:
            self.GeoAligner_3__SourceOut = None
            self.GeoAligner_3__TargetOut = None
            self.GeoAligner_3__MovedGeo = None
            self.GeoAligner_3__TransformOut = None
            self.GeoAligner_3__Log = ["[ERROR] GeoAligner::3: {}".format(e)]
            self.Log.append("[ERROR] Step5 GeoAligner::3 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 6：BlockCutter::2 + GeoAligner::4
    # ------------------------------------------------------
    def step6_blockcutter_2_geoaligner_4(self,
                                        BlockCutter_2__length_fen=None,
                                        BlockCutter_2__width_fen=None,
                                        BlockCutter_2__height_fen=None,
                                        base_point=None,
                                        reference_plane=None,
                                        GeoAligner_4__SourcePlane=None,
                                        GeoAligner_4__RotateDeg=None,
                                        GeoAligner_4__FlipX=None,
                                        GeoAligner_4__FlipY=None,
                                        GeoAligner_4__FlipZ=None,
                                        GeoAligner_4__MoveX=None,
                                        GeoAligner_4__MoveY=None,
                                        GeoAligner_4__MoveZ=None):
        """严格按图连线实现 Step6。

        组件链：
          BlockCutter::2 -> List Item(FacePlaneList -> SourcePlane)
                        -> GeoAligner::4

        关键要求：
        - length/width/height 允许多值：按索引位置对齐（GH 广播）生成多个 TimberBrep。
        - List Item 的 Index 允许 Tree：按 GH Tree 分支方式取值（使用本文件既有 Tree 辅助函数）。
        - GeoAligner::4：操作对象为 Geo；Geo/SourcePlane 为 Tree/List 时按分支一一对应；
          TargetPlane 取“GeoAligner::3 的 TargetPlane 输入端参数值”（本实现取 Step5 已得到的
          self.GeoAligner_3__TargetPlane_Item 的第一个 Plane 作为单值广播）。
        - MoveY 有 2 值：需要对 Geo/SourcePlane 广播对齐。
        - self.GeoAligner_4__MovedGeo 必须完全展平。
        - 移除 sticky（本步骤不使用 sticky）。
        """

        # ========== Step 6A：BlockCutter::2 ==========
        try:
            # base_point：输入端 > solver.base_point > 原点
            bp_in = base_point if base_point is not None else self.base_point
            if bp_in is None:
                bp_in = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(bp_in, rg.Point):
                bp_in = bp_in.Location
            elif isinstance(bp_in, rg.Point3d):
                pass
            else:
                try:
                    bp_in = rg.Point3d(float(bp_in[0]), float(bp_in[1]), float(bp_in[2]))
                except Exception:
                    bp_in = rg.Point3d(0.0, 0.0, 0.0)

            # reference_plane：输入端 > DB > 默认 GH XZ Plane
            rp_in = self.all_get(
                "BlockCutter_2__reference_plane",
                None,
                prefer_input=reference_plane,
            )
            if rp_in is None:
                rp_in = gh_plane_XZ(bp_in)

            # length/width/height：输入端 > DB > 默认
            length_fen_in = self.all_get(
                "BlockCutter_2__length_fen",
                32.0,
                prefer_input=BlockCutter_2__length_fen,
            )
            width_fen_in = self.all_get(
                "BlockCutter_2__width_fen",
                32.0,
                prefer_input=BlockCutter_2__width_fen,
            )
            height_fen_in = self.all_get(
                "BlockCutter_2__height_fen",
                20.0,
                prefer_input=BlockCutter_2__height_fen,
            )

            def _to_float_safe(x, d):
                try:
                    return float(x) if x is not None else float(d)
                except Exception:
                    return float(d)

            def _as_scalar_list(v, default_scalar):
                if v is None:
                    return [float(default_scalar)]
                if _is_gh_tree(v) or isinstance(v, (list, tuple)):
                    flat = flatten_any(v)
                    if len(flat) == 0:
                        return [float(default_scalar)]
                    return [_to_float_safe(it, default_scalar) for it in flat]
                return [_to_float_safe(v, default_scalar)]

            L = _as_scalar_list(length_fen_in, 32.0)
            W = _as_scalar_list(width_fen_in, 32.0)
            H = _as_scalar_list(height_fen_in, 20.0)
            n = max(len(L), len(W), len(H), 1)

            Lb = _broadcast_param(L, n, name="length_fen")
            Wb = _broadcast_param(W, n, name="width_fen")
            Hb = _broadcast_param(H, n, name="height_fen")

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            log_lines_all = []

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
                    _to_float_safe(Lb[i], 32.0),
                    _to_float_safe(Wb[i], 32.0),
                    _to_float_safe(Hb[i], 20.0),
                    bp_in,
                    rp_in,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                log_lines_all.append(log_lines)

            self.BlockCutter_2__TimberBrep = timber_breps[0] if n == 1 else timber_breps
            self.BlockCutter_2__FaceList = faces_list[0] if n == 1 else faces_list
            self.BlockCutter_2__PointList = points_list[0] if n == 1 else points_list
            self.BlockCutter_2__EdgeList = edges_list[0] if n == 1 else edges_list
            self.BlockCutter_2__CenterPoint = center_pts[0] if n == 1 else center_pts
            self.BlockCutter_2__CenterAxisLines = center_axes_list[0] if n == 1 else center_axes_list
            self.BlockCutter_2__EdgeMidPoints = edge_midpts_list[0] if n == 1 else edge_midpts_list
            self.BlockCutter_2__FacePlaneList = face_planes_list[0] if n == 1 else face_planes_list
            self.BlockCutter_2__Corner0Planes = corner0_planes_list[0] if n == 1 else corner0_planes_list
            self.BlockCutter_2__LocalAxesPlane = local_axes_planes[0] if n == 1 else local_axes_planes
            self.BlockCutter_2__AxisX = axis_x_list[0] if n == 1 else axis_x_list
            self.BlockCutter_2__AxisY = axis_y_list[0] if n == 1 else axis_y_list
            self.BlockCutter_2__AxisZ = axis_z_list[0] if n == 1 else axis_z_list
            self.BlockCutter_2__FaceDirTags = face_tags_list[0] if n == 1 else face_tags_list
            self.BlockCutter_2__EdgeDirTags = edge_tags_list[0] if n == 1 else edge_tags_list
            self.BlockCutter_2__Corner0EdgeDirs = corner0_dirs_list[0] if n == 1 else corner0_dirs_list
            self.BlockCutter_2__Log = log_lines_all[0] if n == 1 else log_lines_all

            self.Log.append("[STEP6][BlockCutter::2] OK")
        except Exception as e:
            self.BlockCutter_2__TimberBrep = None
            self.BlockCutter_2__FacePlaneList = []
            self.BlockCutter_2__Corner0Planes = []
            self.BlockCutter_2__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step6 BlockCutter::2 出错: {}".format(e))

        # ========== Step 6B：List Item（FacePlaneList -> SourcePlane）==========
        try:
            idx_in = self.all_get(
                "GeoAligner_4__SourcePlane",
                0,
                prefer_input=GeoAligner_4__SourcePlane,
            )
            wrap = False
            face_plane_list = getattr(self, "BlockCutter_2__FacePlaneList", None)

            # 多 timber：FacePlaneList 是 list[list[plane]]，按 timber 数广播 idx 后逐一取
            if isinstance(face_plane_list, list) and len(face_plane_list) > 0 and isinstance(face_plane_list[0], (list, tuple)):
                n_geo = len(face_plane_list)
                idx_flat = flatten_any(idx_in) if (_is_gh_tree(idx_in) or isinstance(idx_in, (list, tuple))) else [idx_in]
                if len(idx_flat) == 0:
                    idx_flat = [0]
                idx_b = _broadcast_param(idx_flat, n_geo, name="GeoAligner_4__SourcePlane")
                src_planes = []
                for gi in range(n_geo):
                    src_planes.append(_list_item(face_plane_list[gi], idx_b[gi], wrap=wrap))
                self.GeoAligner_4__SourcePlane_Item = src_planes[0] if n_geo == 1 else src_planes
            else:
                # 单 timber：支持 idx 为 Tree / list（按分支取）
                idx_branches = _as_branch_list(idx_in)
                src_out = []
                for br in idx_branches:
                    if br is None or (isinstance(br, list) and len(br) == 0):
                        br = [0]
                    b_items = []
                    for i in to_list(br):
                        b_items.append(_list_item(face_plane_list, i, wrap=wrap))
                    src_out.append(b_items)

                if len(src_out) == 1:
                    src_out = src_out[0]
                    if isinstance(src_out, list) and len(src_out) == 1:
                        src_out = src_out[0]
                self.GeoAligner_4__SourcePlane_Item = src_out

            self.Log.append("[STEP6][List Item SourcePlane] OK")
        except Exception as e:
            self.GeoAligner_4__SourcePlane_Item = None
            self.Log.append("[ERROR] Step6 List Item(SourcePlane) 出错: {}".format(e))

        # ========== Step 6C：GeoAligner::4 ==========
        try:
            geo_in = self.BlockCutter_2__TimberBrep
            source_plane = self.GeoAligner_4__SourcePlane_Item

            # TargetPlane：取 GeoAligner::3 的 TargetPlane 输入端参数值
            # 在当前工程中，Step5 已得到 self.GeoAligner_3__TargetPlane_Item（可能为 Tree/List）。
            # 本步骤要求 TargetPlane 为单值 Plane：取拍平后的第一个 Plane，并对所有分支广播。
            tp_candidates = flatten_any(getattr(self, "GeoAligner_3__TargetPlane_Item", None))
            target_plane = tp_candidates[0] if (tp_candidates is not None and len(tp_candidates) > 0) else None
            if target_plane is None:
                target_plane = gh_plane_XZ(rg.Point3d(0.0, 0.0, 0.0))

            rotate_deg = self.all_get("GeoAligner_4__RotateDeg", 0.0, prefer_input=GeoAligner_4__RotateDeg)
            flip_x = self.all_get("GeoAligner_4__FlipX", False, prefer_input=GeoAligner_4__FlipX)
            flip_y = self.all_get("GeoAligner_4__FlipY", False, prefer_input=GeoAligner_4__FlipY)
            flip_z = self.all_get("GeoAligner_4__FlipZ", False, prefer_input=GeoAligner_4__FlipZ)
            move_x = self.all_get("GeoAligner_4__MoveX", 0.0, prefer_input=GeoAligner_4__MoveX)
            move_y = self.all_get("GeoAligner_4__MoveY", 0.0, prefer_input=GeoAligner_4__MoveY)
            move_z = self.all_get("GeoAligner_4__MoveZ", 0.0, prefer_input=GeoAligner_4__MoveZ)

            # Tree/List 对齐：Geo 与 SourcePlane 按分支一一对应；TargetPlane 单值广播；MoveY 按 GH 广播。
            geo_branches = _as_branch_list(geo_in)
            sp_branches = _as_branch_list(source_plane)

            # TargetPlane 单值：做成一个分支一项，便于后续广播
            tp_branches = [[target_plane]]

            rot_branches = _as_branch_list(rotate_deg)
            fx_branches = _as_branch_list(flip_x)
            fy_branches = _as_branch_list(flip_y)
            fz_branches = _as_branch_list(flip_z)
            mx_branches = _as_branch_list(move_x)
            my_branches = _as_branch_list(move_y)
            mz_branches = _as_branch_list(move_z)

            bcount = max(
                len(geo_branches), len(sp_branches),
                len(tp_branches), len(rot_branches),
                len(fx_branches), len(fy_branches), len(fz_branches),
                len(mx_branches), len(my_branches), len(mz_branches),
            )
            if bcount <= 0:
                bcount = 1

            out_source = []
            out_target = []
            out_moved = []
            out_xf = []
            out_lg = []

            for bi in range(bcount):
                gbr = geo_branches[bi] if bi < len(geo_branches) else geo_branches[-1]
                sp = sp_branches[bi] if bi < len(sp_branches) else sp_branches[-1]
                tp = tp_branches[0]  # 单值广播
                rt = rot_branches[bi] if bi < len(rot_branches) else rot_branches[-1]
                fx = fx_branches[bi] if bi < len(fx_branches) else fx_branches[-1]
                fy = fy_branches[bi] if bi < len(fy_branches) else fy_branches[-1]
                fz = fz_branches[bi] if bi < len(fz_branches) else fz_branches[-1]
                mx = mx_branches[bi] if bi < len(mx_branches) else mx_branches[-1]
                my = my_branches[bi] if bi < len(my_branches) else my_branches[-1]
                mz = mz_branches[bi] if bi < len(mz_branches) else mz_branches[-1]

                n = _max_len(gbr, sp, tp, rt, fx, fy, fz, mx, my, mz)
                if n <= 0:
                    n = 1

                g_b = _broadcast_param(gbr, n)
                sp_b = _broadcast_param(sp, n)
                tp_b = _broadcast_param(tp, n)
                rt_b = _broadcast_param(rt, n)
                fx_b = _broadcast_param(fx, n)
                fy_b = _broadcast_param(fy, n)
                fz_b = _broadcast_param(fz, n)
                mx_b = _broadcast_param(mx, n)
                my_b = _broadcast_param(my, n)
                mz_b = _broadcast_param(mz, n)

                b_s = []
                b_t = []
                b_mg = []
                b_tf = []
                b_log = []

                for i in range(n):
                    so, to_, tfm, mg = GeoAligner_xfm.align(
                        g_b[i],
                        sp_b[i],
                        tp_b[i],
                        rotate_deg=rt_b[i],
                        flip_x=fx_b[i],
                        flip_y=fy_b[i],
                        flip_z=fz_b[i],
                        move_x=mx_b[i],
                        move_y=my_b[i],
                        move_z=mz_b[i],
                    )
                    b_s.append(so)
                    b_t.append(to_)
                    b_tf.append(tfm)
                    b_mg.append(mg)
                    b_log.append("i={} OK".format(i))

                out_source.append(b_s)
                out_target.append(b_t)
                out_xf.append(b_tf)
                out_moved.append(b_mg)
                out_lg.append(b_log)

            # Step6 的输出：MovedGeo 必须彻底展平
            self.GeoAligner_4__SourceOut = out_source
            self.GeoAligner_4__TargetOut = out_target
            self.GeoAligner_4__TransformOut = out_xf
            self.GeoAligner_4__MovedGeo = flatten_any(out_moved)
            self.GeoAligner_4__Log = out_lg

            self.Log.append("[STEP6][GeoAligner::4] OK")
        except Exception as e:
            self.GeoAligner_4__SourceOut = None
            self.GeoAligner_4__TargetOut = None
            self.GeoAligner_4__MovedGeo = None
            self.GeoAligner_4__TransformOut = None
            self.GeoAligner_4__Log = ["[ERROR] GeoAligner::4: {}".format(e)]
            self.Log.append("[ERROR] Step6 GeoAligner::4 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------
    def run(self):
        # Step 1：数据库
        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        # Step 2：木坯
        self.step2_timber()

        # Step 3：耍头工具生成 + 对齐
        self.step3_shua_tou_align()

        # Step 4：起翘工具生成 + 对齐
        self.step4_qiao_tool_align()

        # Step 5：BlockCutter::1 + GeoAligner::3
        self.step5_blockcutter_1_geoaligner_3(
            BlockCutter_1__length_fen=self._in_BlockCutter_1__length_fen,
            BlockCutter_1__width_fen=self._in_BlockCutter_1__width_fen,
            BlockCutter_1__height_fen=self._in_BlockCutter_1__height_fen,
            reference_plane=self._in_BlockCutter_1__reference_plane,
            GeoAligner_3__SourcePlane=self._in_GeoAligner_3__SourcePlane,
            GeoAligner_3__TargetPlane_path=self._in_GeoAligner_3__TargetPlane_path,
            GeoAligner_3__TargetPlane_index=self._in_GeoAligner_3__TargetPlane_index,
            GeoAligner_3__RotateDeg=self._in_GeoAligner_3__RotateDeg,
            GeoAligner_3__FlipX=self._in_GeoAligner_3__FlipX,
            GeoAligner_3__FlipY=self._in_GeoAligner_3__FlipY,
            GeoAligner_3__FlipZ=self._in_GeoAligner_3__FlipZ,
            GeoAligner_3__MoveX=self._in_GeoAligner_3__MoveX,
            GeoAligner_3__MoveY=self._in_GeoAligner_3__MoveY,
            GeoAligner_3__MoveZ=self._in_GeoAligner_3__MoveZ,
        )

        # Step 6：BlockCutter::2 + GeoAligner::4
        self.step6_blockcutter_2_geoaligner_4(
            BlockCutter_2__length_fen=self._in_BlockCutter_2__length_fen,
            BlockCutter_2__width_fen=self._in_BlockCutter_2__width_fen,
            BlockCutter_2__height_fen=self._in_BlockCutter_2__height_fen,
            base_point=self.base_point,
            reference_plane=self._in_BlockCutter_2__reference_plane,
            GeoAligner_4__SourcePlane=self._in_GeoAligner_4__SourcePlane,
            GeoAligner_4__RotateDeg=self._in_GeoAligner_4__RotateDeg,
            GeoAligner_4__FlipX=self._in_GeoAligner_4__FlipX,
            GeoAligner_4__FlipY=self._in_GeoAligner_4__FlipY,
            GeoAligner_4__FlipZ=self._in_GeoAligner_4__FlipZ,
            GeoAligner_4__MoveX=self._in_GeoAligner_4__MoveX,
            GeoAligner_4__MoveY=self._in_GeoAligner_4__MoveY,
            GeoAligner_4__MoveZ=self._in_GeoAligner_4__MoveZ,
        )

        # Step 7：BlockCutter::3 + GeoAligner::5
        self.step7_blockcutter_3_geoaligner_5(
            BlockCutter_3__length_fen=self._in_BlockCutter_3__length_fen,
            BlockCutter_3__width_fen=self._in_BlockCutter_3__width_fen,
            BlockCutter_3__height_fen=self._in_BlockCutter_3__height_fen,
            base_point=self.base_point,
            reference_plane=self._in_BlockCutter_3__reference_plane,
            GeoAligner_5__SourcePlane=self._in_GeoAligner_5__SourcePlane,
            GeoAligner_5__TargetPlane_path=self._in_GeoAligner_5__TargetPlane_path,
            GeoAligner_5__TargetPlane_index=self._in_GeoAligner_5__TargetPlane_index,
            GeoAligner_5__RotateDeg=self._in_GeoAligner_5__RotateDeg,
            GeoAligner_5__FlipX=self._in_GeoAligner_5__FlipX,
            GeoAligner_5__FlipY=self._in_GeoAligner_5__FlipY,
            GeoAligner_5__FlipZ=self._in_GeoAligner_5__FlipZ,
            GeoAligner_5__MoveX=self._in_GeoAligner_5__MoveX,
            GeoAligner_5__MoveY=self._in_GeoAligner_5__MoveY,
            GeoAligner_5__MoveZ=self._in_GeoAligner_5__MoveZ,
        )

        # Step 8：BlockCutter::4 + GeoAligner::6
        self.step8_blockcutter_4_geoaligner_6(
            BlockCutter_4__length_fen=getattr(self, '_in_BlockCutter_4__length_fen', None),
            BlockCutter_4__width_fen=getattr(self, '_in_BlockCutter_4__width_fen', None),
            BlockCutter_4__height_fen=getattr(self, '_in_BlockCutter_4__height_fen', None),
            base_point=self.base_point,
            reference_plane=getattr(self, '_in_BlockCutter_4__reference_plane', None),
            GeoAligner_6__SourcePlane=getattr(self, '_in_GeoAligner_6__SourcePlane', None),
            GeoAligner_6__TargetPlane_base_path=getattr(self, '_in_GeoAligner_6__TargetPlane_base_path', None),
            GeoAligner_6__TargetPlane_base_index=getattr(self, '_in_GeoAligner_6__TargetPlane_base_index', None),
            GeoAligner_6__TargetPlane_origin=getattr(self, '_in_GeoAligner_6__TargetPlane_origin', None),
            GeoAligner_6__RotateDeg=getattr(self, '_in_GeoAligner_6__RotateDeg', None),
            GeoAligner_6__FlipX=getattr(self, '_in_GeoAligner_6__FlipX', None),
            GeoAligner_6__FlipY=getattr(self, '_in_GeoAligner_6__FlipY', None),
            GeoAligner_6__FlipZ=getattr(self, '_in_GeoAligner_6__FlipZ', None),
            GeoAligner_6__MoveX=getattr(self, '_in_GeoAligner_6__MoveX', None),
            GeoAligner_6__MoveY=getattr(self, '_in_GeoAligner_6__MoveY', None),
            GeoAligner_6__MoveZ=getattr(self, '_in_GeoAligner_6__MoveZ', None),
        )

        # Step 9：GongYan + PlaneFromLists::4 + GeoAligner::7
        self.step9_gongyan_plane_geoaligner_7(
            GongYan__BasePoint=getattr(self, '_in_GongYan__BasePoint', None),
            GongYan__SectionPlane=getattr(self, '_in_GongYan__SectionPlane', None),
            GongYan__EM_fen=getattr(self, '_in_GongYan__EM_fen', None),
            GongYan__EC_fen=getattr(self, '_in_GongYan__EC_fen', None),
            GongYan__AI_fen=getattr(self, '_in_GongYan__AI_fen', None),
            GongYan__AG_fen=getattr(self, '_in_GongYan__AG_fen', None),
            GongYan__JR_fen=getattr(self, '_in_GongYan__JR_fen', None),
            GongYan__HK_fen=getattr(self, '_in_GongYan__HK_fen', None),
            GongYan__Thickness=getattr(self, '_in_GongYan__Thickness', None),
            GongYan__OffsetDist=getattr(self, '_in_GongYan__OffsetDist', None),
            PlaneFromLists_4__IndexOrigin=getattr(self, '_in_PlaneFromLists_4__IndexOrigin', None),
            PlaneFromLists_4__IndexPlane=getattr(self, '_in_PlaneFromLists_4__IndexPlane', None),
            PlaneFromLists_4__Wrap=getattr(self, '_in_PlaneFromLists_4__Wrap', None),
            GeoAligner_7__SourcePlane=getattr(self, '_in_GeoAligner_7__SourcePlane', None),
            GeoAligner_7__RotateDeg=getattr(self, '_in_GeoAligner_7__RotateDeg', None),
            GeoAligner_7__FlipX=getattr(self, '_in_GeoAligner_7__FlipX', None),
            GeoAligner_7__FlipY=getattr(self, '_in_GeoAligner_7__FlipY', None),
            GeoAligner_7__FlipZ=getattr(self, '_in_GeoAligner_7__FlipZ', None),
            GeoAligner_7__MoveX=getattr(self, '_in_GeoAligner_7__MoveX', None),
            GeoAligner_7__MoveY=getattr(self, '_in_GeoAligner_7__MoveY', None),
            GeoAligner_7__MoveZ=getattr(self, '_in_GeoAligner_7__MoveZ', None),
        )

        # Step 10：QiAOTool::2 + PlaneFromLists::5 + PlaneFromLists::6 + GeoAligner::8
        self.step10_qiao_tool2_plane_geoaligner_8(
            QiAOTool_2__length_fen=getattr(self, '_in_QiAOTool_2__length_fen', None),
            QiAOTool_2__width_fen=getattr(self, '_in_QiAOTool_2__width_fen', None),
            QiAOTool_2__height_fen=getattr(self, '_in_QiAOTool_2__height_fen', None),
            QiAOTool_2__base_point=getattr(self, '_in_QiAOTool_2__base_point', None),
            QiAOTool_2__timber_ref_plane_mode=getattr(self, '_in_QiAOTool_2__timber_ref_plane_mode', None),
            QiAOTool_2__qi_height=getattr(self, '_in_QiAOTool_2__qi_height', None),
            QiAOTool_2__sha_width=getattr(self, '_in_QiAOTool_2__sha_width', None),
            QiAOTool_2__qi_offset_fen=getattr(self, '_in_QiAOTool_2__qi_offset_fen', None),
            QiAOTool_2__extrude_length=getattr(self, '_in_QiAOTool_2__extrude_length', None),
            QiAOTool_2__extrude_positive=getattr(self, '_in_QiAOTool_2__extrude_positive', None),
            QiAOTool_2__qi_ref_plane_mode=getattr(self, '_in_QiAOTool_2__qi_ref_plane_mode', None),
            PlaneFromLists_6__IndexOrigin=getattr(self, '_in_PlaneFromLists_6__IndexOrigin', None),
            PlaneFromLists_6__IndexPlane=getattr(self, '_in_PlaneFromLists_6__IndexPlane', None),
            PlaneFromLists_6__Wrap=getattr(self, '_in_PlaneFromLists_6__Wrap', None),
            PlaneFromLists_5__IndexOrigin=getattr(self, '_in_PlaneFromLists_5__IndexOrigin', None),
            PlaneFromLists_5__IndexPlane=getattr(self, '_in_PlaneFromLists_5__IndexPlane', None),
            PlaneFromLists_5__Wrap=getattr(self, '_in_PlaneFromLists_5__Wrap', None),
            GeoAligner_8__RotateDeg=getattr(self, '_in_GeoAligner_8__RotateDeg', None),
            GeoAligner_8__FlipX=getattr(self, '_in_GeoAligner_8__FlipX', None),
            GeoAligner_8__FlipY=getattr(self, '_in_GeoAligner_8__FlipY', None),
            GeoAligner_8__FlipZ=getattr(self, '_in_GeoAligner_8__FlipZ', None),
            GeoAligner_8__MoveX=getattr(self, '_in_GeoAligner_8__MoveX', None),
            GeoAligner_8__MoveY=getattr(self, '_in_GeoAligner_8__MoveY', None),
            GeoAligner_8__MoveZ=getattr(self, '_in_GeoAligner_8__MoveZ', None),
        )

        # Step 11：PlaneFromLists::7 + Juansha + GeoAligner::9
        self.step11_plane_juansha_geoaligner_9(
            PlaneFromLists_7__IndexOrigin=getattr(self, '_in_PlaneFromLists_7__IndexOrigin', None),
            PlaneFromLists_7__IndexPlane=getattr(self, '_in_PlaneFromLists_7__IndexPlane', None),
            PlaneFromLists_7__Wrap=getattr(self, '_in_PlaneFromLists_7__Wrap', None),
            Juansha__HeightFen=getattr(self, '_in_Juansha__HeightFen', None),
            Juansha__LengthFen=getattr(self, '_in_Juansha__LengthFen', None),
            Juansha__DivCount=getattr(self, '_in_Juansha__DivCount', None),
            Juansha__ThicknessFen=getattr(self, '_in_Juansha__ThicknessFen', None),
            Juansha__SectionPlane=getattr(self, '_in_Juansha__SectionPlane', None),
            Juansha__PositionPoint=getattr(self, '_in_Juansha__PositionPoint', None),
            GeoAligner_9__RotateDeg=getattr(self, '_in_GeoAligner_9__RotateDeg', None),
            GeoAligner_9__FlipX=getattr(self, '_in_GeoAligner_9__FlipX', None),
            GeoAligner_9__FlipY=getattr(self, '_in_GeoAligner_9__FlipY', None),
            GeoAligner_9__FlipZ=getattr(self, '_in_GeoAligner_9__FlipZ', None),
            GeoAligner_9__MoveX=getattr(self, '_in_GeoAligner_9__MoveX', None),
            GeoAligner_9__MoveY=getattr(self, '_in_GeoAligner_9__MoveY', None),
            GeoAligner_9__MoveZ=getattr(self, '_in_GeoAligner_9__MoveZ', None),
        )

        # Step 12：BlockCutter::5 + GeoAligner::10（不影响当前 CutTimbers 回退逻辑，仅提供额外输出）
        self.step12_blockcutter_5_geoaligner_10(
            BlockCutter_5__length_fen=getattr(self, '_in_BlockCutter_5__length_fen', None),
            BlockCutter_5__width_fen=getattr(self, '_in_BlockCutter_5__width_fen', None),
            BlockCutter_5__height_fen=getattr(self, '_in_BlockCutter_5__height_fen', None),
            base_point=self.base_point,
            reference_plane=getattr(self, '_in_BlockCutter_5__reference_plane', None),
            GeoAligner_10__SourcePlane=getattr(self, '_in_GeoAligner_10__SourcePlane', None),
            GeoAligner_10__RotateDeg=getattr(self, '_in_GeoAligner_10__RotateDeg', None),
            GeoAligner_10__FlipX=getattr(self, '_in_GeoAligner_10__FlipX', None),
            GeoAligner_10__FlipY=getattr(self, '_in_GeoAligner_10__FlipY', None),
            GeoAligner_10__FlipZ=getattr(self, '_in_GeoAligner_10__FlipZ', None),
            GeoAligner_10__MoveX=getattr(self, '_in_GeoAligner_10__MoveX', None),
            GeoAligner_10__MoveY=getattr(self, '_in_GeoAligner_10__MoveY', None),
            GeoAligner_10__MoveZ=getattr(self, '_in_GeoAligner_10__MoveZ', None),
        )

        # Step 13：CutTimbersByTools（最终切割输出）
        self.step13_cut_timbers_by_tools(
            timbers=getattr(self, 'TimberBrep', None),
            tools=flatten_any([
                getattr(self, 'GeoAligner_1__MovedGeo', None),
                getattr(self, 'GeoAligner_2__MovedGeo', None),
                getattr(self, 'GeoAligner_3__MovedGeo', None),
                getattr(self, 'GeoAligner_4__MovedGeo', None),
                getattr(self, 'GeoAligner_5__MovedGeo', None),
                getattr(self, 'GeoAligner_6__MovedGeo', None),
                getattr(self, 'GeoAligner_7__MovedGeo', None),
                getattr(self, 'GeoAligner_8__MovedGeo', None),
                getattr(self, 'GeoAligner_9__MovedGeo', None),
                getattr(self, 'GeoAligner_10__MovedGeo', None),
            ])
        )

        # 按要求：CutTimbers 输出端直接等于 CutTimbersByTools 的 CutTimbers
        self.CutTimbers = flatten_any(getattr(self, 'CutTimbersByTools__CutTimbers', None))
        self.FailTimbers = getattr(self, 'CutTimbersByTools__FailTimbers', [])

        self.Log.append('[RUN] 已实现到 Step13：CutTimbersByTools。')

        return self


if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    # ==============================================================

    # 组件入口：仅 3 个输入端
    # DBPath, base_point, Refresh

    solver = ShuaTouInLineWManGong2_4PU_Solver(DBPath, base_point, Refresh, ghenv)

    # --- 可选输入端注入（若 GH 组件定义了这些输入端变量）---
    for _name in [
        "BlockCutter_1__length_fen",
        "BlockCutter_1__width_fen",
        "BlockCutter_1__height_fen",
        "BlockCutter_1__reference_plane",
        "GeoAligner_3__SourcePlane",
        "GeoAligner_3__TargetPlane_path",
        "GeoAligner_3__TargetPlane_index",
        "GeoAligner_3__RotateDeg",
        "GeoAligner_3__FlipX",
        "GeoAligner_3__FlipY",
        "GeoAligner_3__FlipZ",
        "GeoAligner_3__MoveX",
        "GeoAligner_3__MoveY",
        "GeoAligner_3__MoveZ",

        # Step6: BlockCutter::2 + GeoAligner::4
        "BlockCutter_2__length_fen",
        "BlockCutter_2__width_fen",
        "BlockCutter_2__height_fen",
        "BlockCutter_2__reference_plane",
        "GeoAligner_4__SourcePlane",
        "GeoAligner_4__RotateDeg",
        "GeoAligner_4__FlipX",
        "GeoAligner_4__FlipY",
        "GeoAligner_4__FlipZ",
        "GeoAligner_4__MoveX",
        "GeoAligner_4__MoveY",
        "GeoAligner_4__MoveZ",

        # Step7: BlockCutter::3 + GeoAligner::5
        "BlockCutter_3__length_fen",
        "BlockCutter_3__width_fen",
        "BlockCutter_3__height_fen",
        "BlockCutter_3__reference_plane",
        "GeoAligner_5__SourcePlane",
        "GeoAligner_5__TargetPlane_path",
        "GeoAligner_5__TargetPlane_index",
        "GeoAligner_5__RotateDeg",
        "GeoAligner_5__FlipX",
        "GeoAligner_5__FlipY",
        "GeoAligner_5__FlipZ",
        "GeoAligner_5__MoveX",
        "GeoAligner_5__MoveY",
        "GeoAligner_5__MoveZ",

        # Step8: BlockCutter::4 + GeoAligner::6
        "BlockCutter_4__length_fen",
        "BlockCutter_4__width_fen",
        "BlockCutter_4__height_fen",
        "BlockCutter_4__reference_plane",
        "GeoAligner_6__SourcePlane",
        "GeoAligner_6__TargetPlane_base_path",
        "GeoAligner_6__TargetPlane_base_index",
        "GeoAligner_6__TargetPlane_origin",
        "GeoAligner_6__RotateDeg",
        "GeoAligner_6__FlipX",
        "GeoAligner_6__FlipY",
        "GeoAligner_6__FlipZ",
        "GeoAligner_6__MoveX",
        "GeoAligner_6__MoveY",
        "GeoAligner_6__MoveZ",

        # Step9: GongYan + PlaneFromLists::4 + GeoAligner::7
        "GongYan__BasePoint",
        "GongYan__SectionPlane",
        "GongYan__EM_fen",
        "GongYan__EC_fen",
        "GongYan__AI_fen",
        "GongYan__AG_fen",
        "GongYan__JR_fen",
        "GongYan__HK_fen",
        "GongYan__Thickness",
        "GongYan__OffsetDist",
        "PlaneFromLists_4__IndexOrigin",
        "PlaneFromLists_4__IndexPlane",
        "PlaneFromLists_4__Wrap",
        "GeoAligner_7__SourcePlane",
        "GeoAligner_7__RotateDeg",
        "GeoAligner_7__FlipX",
        "GeoAligner_7__FlipY",
        "GeoAligner_7__FlipZ",
        "GeoAligner_7__MoveX",
        "GeoAligner_7__MoveY",
        "GeoAligner_7__MoveZ",

        # Step10: QiAOTool::2 + PlaneFromLists::5 + PlaneFromLists::6 + GeoAligner::8
        "QiAOTool_2__length_fen",
        "QiAOTool_2__width_fen",
        "QiAOTool_2__height_fen",
        "QiAOTool_2__base_point",
        "QiAOTool_2__timber_ref_plane_mode",
        "QiAOTool_2__qi_height",
        "QiAOTool_2__sha_width",
        "QiAOTool_2__qi_offset_fen",
        "QiAOTool_2__extrude_length",
        "QiAOTool_2__extrude_positive",
        "QiAOTool_2__qi_ref_plane_mode",

        "PlaneFromLists_6__IndexOrigin",
        "PlaneFromLists_6__IndexPlane",
        "PlaneFromLists_6__Wrap",

        "PlaneFromLists_5__IndexOrigin",
        "PlaneFromLists_5__IndexPlane",
        "PlaneFromLists_5__Wrap",

        "GeoAligner_8__RotateDeg",
        "GeoAligner_8__FlipX",
        "GeoAligner_8__FlipY",
        "GeoAligner_8__FlipZ",
        "GeoAligner_8__MoveX",
        "GeoAligner_8__MoveY",
        "GeoAligner_8__MoveZ",

        # Step11: PlaneFromLists::7 + Juansha + GeoAligner::9
        "PlaneFromLists_7__IndexOrigin",
        "PlaneFromLists_7__IndexPlane",
        "PlaneFromLists_7__Wrap",

        "Juansha__HeightFen",
        "Juansha__LengthFen",
        "Juansha__DivCount",
        "Juansha__ThicknessFen",
        "Juansha__SectionPlane",
        "Juansha__PositionPoint",

        "GeoAligner_9__RotateDeg",
        "GeoAligner_9__FlipX",
        "GeoAligner_9__FlipY",
        "GeoAligner_9__FlipZ",
        "GeoAligner_9__MoveX",
        "GeoAligner_9__MoveY",
        "GeoAligner_9__MoveZ",

        # Step12: BlockCutter::5 + GeoAligner::10
        "BlockCutter_5__length_fen",
        "BlockCutter_5__width_fen",
        "BlockCutter_5__height_fen",
        "BlockCutter_5__reference_plane",
        "GeoAligner_10__SourcePlane",
        "GeoAligner_10__RotateDeg",
        "GeoAligner_10__FlipX",
        "GeoAligner_10__FlipY",
        "GeoAligner_10__FlipZ",
        "GeoAligner_10__MoveX",
        "GeoAligner_10__MoveY",
        "GeoAligner_10__MoveZ",
    ]:
        try:
            if _name in globals():
                setattr(solver, "_in_" + _name, globals().get(_name))
        except Exception:
            pass

    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = flatten_any(solver.CutTimbers)
    FailTimbers = flatten_any(solver.FailTimbers)
    Log = solver.Log

    # --- 开发模式输出：DB ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- Step2: Timber（BuildTimberBlockUniform_SkewAxis_M）---
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

    # --- Step2: Skew 扩展输出（避免与未来组件重名：统一 Skew_ 前缀）---
    Skew_A = solver.Skew_A
    Skew_Point_B = solver.Skew_Point_B
    Skew_Point_C = solver.Skew_Point_C
    Skew_Planes = solver.Skew_Planes
    Skew_ExtraPoints_GF_EH = solver.Skew_ExtraPoints_GF_EH

    # --- Step3: ShuaTou ---
    ShuaTou__ToolBrep = solver.ShuaTou__ToolBrep
    ShuaTou__RefPlanes = solver.ShuaTou__RefPlanes
    ShuaTou__CenterSectionCrv = solver.ShuaTou__CenterSectionCrv
    ShuaTou__SideSectionCrv = solver.ShuaTou__SideSectionCrv
    ShuaTou__CenterSectionFace = solver.ShuaTou__CenterSectionFace
    ShuaTou__SideSectionFace = solver.ShuaTou__SideSectionFace
    ShuaTou__OffsetSideFaces = solver.ShuaTou__OffsetSideFaces
    ShuaTou__OffsetSideCrvs = solver.ShuaTou__OffsetSideCrvs
    ShuaTou__SideLoftFace = solver.ShuaTou__SideLoftFace
    ShuaTou__DebugPoints = solver.ShuaTou__DebugPoints
    ShuaTou__DebugLines = solver.ShuaTou__DebugLines
    ShuaTou__Log = solver.ShuaTou__Log

    # --- Step3: PlaneFromLists::1 ---
    PlaneFromLists_1__ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__Log = solver.PlaneFromLists_1__Log

    # --- Step3: List Item ---
    ListItem_ShuaTouRefPlanes__Item = solver.ListItem_ShuaTouRefPlanes__Item
    ListItem_ShuaTouRefPlanes__Log = solver.ListItem_ShuaTouRefPlanes__Log

    # --- Step3: GeoAligner::1 ---
    GeoAligner_1__MovedGeo = solver.GeoAligner_1__MovedGeo
    GeoAligner_1__SourceOut = solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut = solver.GeoAligner_1__TargetOut
    _tf = solver.GeoAligner_1__TransformOut
    GeoAligner_1__TransformOut = ght.GH_Transform(_tf) if (ght is not None and _tf is not None and isinstance(_tf, rg.Transform)) else _tf
    GeoAligner_1__Log = solver.GeoAligner_1__Log

    # --- Step4: QiAOTool::1 ---
    QiAOTool_1__CutTimbers = solver.QiAOTool_1__CutTimbers
    QiAOTool_1__FailTimbers = solver.QiAOTool_1__FailTimbers
    QiAOTool_1__Log = solver.QiAOTool_1__Log
    QiAOTool_1__EdgeMidPoints = solver.QiAOTool_1__EdgeMidPoints
    QiAOTool_1__Corner0Planes = solver.QiAOTool_1__Corner0Planes
    QiAOTool_1__TimberBrep = solver.QiAOTool_1__TimberBrep
    QiAOTool_1__ToolBrep = solver.QiAOTool_1__ToolBrep
    QiAOTool_1__AlignedTool = solver.QiAOTool_1__AlignedTool
    QiAOTool_1__RefPlanes = solver.QiAOTool_1__RefPlanes
    QiAOTool_1__PFL1_ResultPlane = solver.QiAOTool_1__PFL1_ResultPlane
    QiAOTool_1__QiAo_FacePlane = solver.QiAOTool_1__QiAo_FacePlane

    # --- Step4: PlaneFromLists::2 ---
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    # --- Step4: PlaneFromLists::3 ---
    PlaneFromLists_3__ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__Log = solver.PlaneFromLists_3__Log

    # --- Step4: GeoAligner::2 ---
    GeoAligner_2__MovedGeo = solver.GeoAligner_2__MovedGeo
    GeoAligner_2__SourceOut = solver.GeoAligner_2__SourceOut
    GeoAligner_2__TargetOut = solver.GeoAligner_2__TargetOut
    _tf2 = solver.GeoAligner_2__TransformOut
    GeoAligner_2__TransformOut = ght.GH_Transform(_tf2) if (ght is not None and _tf2 is not None and isinstance(_tf2, rg.Transform)) else _tf2
    GeoAligner_2__Log = solver.GeoAligner_2__Log

    # --- Step5: BlockCutter::1 ---
    BlockCutter_1__TimberBrep = solver.BlockCutter_1__TimberBrep
    BlockCutter_1__FaceList = solver.BlockCutter_1__FaceList
    BlockCutter_1__PointList = solver.BlockCutter_1__PointList
    BlockCutter_1__EdgeList = solver.BlockCutter_1__EdgeList
    BlockCutter_1__CenterPoint = solver.BlockCutter_1__CenterPoint
    BlockCutter_1__CenterAxisLines = solver.BlockCutter_1__CenterAxisLines
    BlockCutter_1__EdgeMidPoints = solver.BlockCutter_1__EdgeMidPoints
    BlockCutter_1__FacePlaneList = solver.BlockCutter_1__FacePlaneList
    BlockCutter_1__Corner0Planes = solver.BlockCutter_1__Corner0Planes
    BlockCutter_1__LocalAxesPlane = solver.BlockCutter_1__LocalAxesPlane
    BlockCutter_1__AxisX = solver.BlockCutter_1__AxisX
    BlockCutter_1__AxisY = solver.BlockCutter_1__AxisY
    BlockCutter_1__AxisZ = solver.BlockCutter_1__AxisZ
    BlockCutter_1__FaceDirTags = solver.BlockCutter_1__FaceDirTags
    BlockCutter_1__EdgeDirTags = solver.BlockCutter_1__EdgeDirTags
    BlockCutter_1__Corner0EdgeDirs = solver.BlockCutter_1__Corner0EdgeDirs
    BlockCutter_1__Log = solver.BlockCutter_1__Log

    # --- Step5: Graft Tree ---
    Step5__GraftedGeo = solver.Step5__GraftedGeo

    # --- Step5: List Item / Tree Item ---
    GeoAligner_3__SourcePlane_Item = solver.GeoAligner_3__SourcePlane_Item
    GeoAligner_3__TargetPlane_Item = solver.GeoAligner_3__TargetPlane_Item

    # --- Step5: GeoAligner::3 ---
    GeoAligner_3__MovedGeo = flatten_any(solver.GeoAligner_3__MovedGeo)
    GeoAligner_3__SourceOut = solver.GeoAligner_3__SourceOut
    GeoAligner_3__TargetOut = solver.GeoAligner_3__TargetOut
    _tf3 = solver.GeoAligner_3__TransformOut
    GeoAligner_3__TransformOut = ght.GH_Transform(_tf3) if (ght is not None and _tf3 is not None and isinstance(_tf3, rg.Transform)) else _tf3
    GeoAligner_3__Log = solver.GeoAligner_3__Log

    # --- Step6: BlockCutter::2 ---
    BlockCutter_2__TimberBrep = solver.BlockCutter_2__TimberBrep
    BlockCutter_2__FaceList = solver.BlockCutter_2__FaceList
    BlockCutter_2__PointList = solver.BlockCutter_2__PointList
    BlockCutter_2__EdgeList = solver.BlockCutter_2__EdgeList
    BlockCutter_2__CenterPoint = solver.BlockCutter_2__CenterPoint
    BlockCutter_2__CenterAxisLines = solver.BlockCutter_2__CenterAxisLines
    BlockCutter_2__EdgeMidPoints = solver.BlockCutter_2__EdgeMidPoints
    BlockCutter_2__FacePlaneList = solver.BlockCutter_2__FacePlaneList
    BlockCutter_2__Corner0Planes = solver.BlockCutter_2__Corner0Planes
    BlockCutter_2__LocalAxesPlane = solver.BlockCutter_2__LocalAxesPlane
    BlockCutter_2__AxisX = solver.BlockCutter_2__AxisX
    BlockCutter_2__AxisY = solver.BlockCutter_2__AxisY
    BlockCutter_2__AxisZ = solver.BlockCutter_2__AxisZ
    BlockCutter_2__FaceDirTags = solver.BlockCutter_2__FaceDirTags
    BlockCutter_2__EdgeDirTags = solver.BlockCutter_2__EdgeDirTags
    BlockCutter_2__Corner0EdgeDirs = solver.BlockCutter_2__Corner0EdgeDirs
    BlockCutter_2__Log = solver.BlockCutter_2__Log

    # --- Step6: List Item ---
    GeoAligner_4__SourcePlane_Item = solver.GeoAligner_4__SourcePlane_Item

    # --- Step6: GeoAligner::4 ---
    GeoAligner_4__MovedGeo = flatten_any(solver.GeoAligner_4__MovedGeo)
    GeoAligner_4__SourceOut = solver.GeoAligner_4__SourceOut
    GeoAligner_4__TargetOut = solver.GeoAligner_4__TargetOut
    _tf4 = solver.GeoAligner_4__TransformOut
    GeoAligner_4__TransformOut = ght.GH_Transform(_tf4) if (ght is not None and _tf4 is not None and isinstance(_tf4, rg.Transform)) else _tf4
    GeoAligner_4__Log = solver.GeoAligner_4__Log

    # --- Step7: BlockCutter::3 ---
    BlockCutter_3__TimberBrep = solver.BlockCutter_3__TimberBrep
    BlockCutter_3__FaceList = solver.BlockCutter_3__FaceList
    BlockCutter_3__PointList = solver.BlockCutter_3__PointList
    BlockCutter_3__EdgeList = solver.BlockCutter_3__EdgeList
    BlockCutter_3__CenterPoint = solver.BlockCutter_3__CenterPoint
    BlockCutter_3__CenterAxisLines = solver.BlockCutter_3__CenterAxisLines
    BlockCutter_3__EdgeMidPoints = solver.BlockCutter_3__EdgeMidPoints
    BlockCutter_3__FacePlaneList = solver.BlockCutter_3__FacePlaneList
    BlockCutter_3__Corner0Planes = solver.BlockCutter_3__Corner0Planes
    BlockCutter_3__LocalAxesPlane = solver.BlockCutter_3__LocalAxesPlane
    BlockCutter_3__AxisX = solver.BlockCutter_3__AxisX
    BlockCutter_3__AxisY = solver.BlockCutter_3__AxisY
    BlockCutter_3__AxisZ = solver.BlockCutter_3__AxisZ
    BlockCutter_3__FaceDirTags = solver.BlockCutter_3__FaceDirTags
    BlockCutter_3__EdgeDirTags = solver.BlockCutter_3__EdgeDirTags
    BlockCutter_3__Corner0EdgeDirs = solver.BlockCutter_3__Corner0EdgeDirs
    BlockCutter_3__Log = solver.BlockCutter_3__Log

    Step7__GraftedGeo = solver.Step7__GraftedGeo

    # --- Step7: List Item / Tree Item ---
    GeoAligner_5__SourcePlane_Item = solver.GeoAligner_5__SourcePlane_Item
    GeoAligner_5__TargetPlane_Item = solver.GeoAligner_5__TargetPlane_Item

    # --- Step7: GeoAligner::5 ---
    GeoAligner_5__MovedGeo = flatten_any(solver.GeoAligner_5__MovedGeo)
    GeoAligner_5__SourceOut = solver.GeoAligner_5__SourceOut
    GeoAligner_5__TargetOut = solver.GeoAligner_5__TargetOut
    GeoAligner_5__TransformOut = solver.GeoAligner_5__TransformOut
    GeoAligner_5__Log = solver.GeoAligner_5__Log

    # --- Step8: BlockCutter::4 ---
    BlockCutter_4__TimberBrep = solver.BlockCutter_4__TimberBrep
    BlockCutter_4__FaceList = solver.BlockCutter_4__FaceList
    BlockCutter_4__PointList = solver.BlockCutter_4__PointList
    BlockCutter_4__EdgeList = solver.BlockCutter_4__EdgeList
    BlockCutter_4__CenterPoint = solver.BlockCutter_4__CenterPoint
    BlockCutter_4__CenterAxisLines = solver.BlockCutter_4__CenterAxisLines
    BlockCutter_4__EdgeMidPoints = solver.BlockCutter_4__EdgeMidPoints
    BlockCutter_4__FacePlaneList = solver.BlockCutter_4__FacePlaneList
    BlockCutter_4__Corner0Planes = solver.BlockCutter_4__Corner0Planes
    BlockCutter_4__LocalAxesPlane = solver.BlockCutter_4__LocalAxesPlane
    BlockCutter_4__AxisX = solver.BlockCutter_4__AxisX
    BlockCutter_4__AxisY = solver.BlockCutter_4__AxisY
    BlockCutter_4__AxisZ = solver.BlockCutter_4__AxisZ
    BlockCutter_4__FaceDirTags = solver.BlockCutter_4__FaceDirTags
    BlockCutter_4__EdgeDirTags = solver.BlockCutter_4__EdgeDirTags
    BlockCutter_4__Corner0EdgeDirs = solver.BlockCutter_4__Corner0EdgeDirs
    BlockCutter_4__Log = solver.BlockCutter_4__Log

    # --- Step8: List Item / Tree Item / Plane Origin ---
    GeoAligner_6__SourcePlane_Item = solver.GeoAligner_6__SourcePlane_Item
    GeoAligner_6__TargetPlane_BasePlane_Item = solver.GeoAligner_6__TargetPlane_BasePlane_Item
    GeoAligner_6__TargetPlane_OriginPoint_Item = solver.GeoAligner_6__TargetPlane_OriginPoint_Item
    GeoAligner_6__TargetPlane_Item = solver.GeoAligner_6__TargetPlane_Item

    # --- Step8: GeoAligner::6 ---
    GeoAligner_6__MovedGeo = flatten_any(solver.GeoAligner_6__MovedGeo)
    GeoAligner_6__SourceOut = solver.GeoAligner_6__SourceOut
    GeoAligner_6__TargetOut = solver.GeoAligner_6__TargetOut
    _tf6 = solver.GeoAligner_6__TransformOut
    GeoAligner_6__TransformOut = ght.GH_Transform(_tf6) if (ght is not None and _tf6 is not None and isinstance(_tf6, rg.Transform)) else _tf6
    GeoAligner_6__Log = solver.GeoAligner_6__Log

    # --- Step9: GongYan ---
    GongYan__ToolBrep = solver.GongYan__ToolBrep
    GongYan__SectionCurve = solver.GongYan__SectionCurve
    GongYan__SectionFace = solver.GongYan__SectionFace
    GongYan__LeftCurve = solver.GongYan__LeftCurve
    GongYan__RightCurve = solver.GongYan__RightCurve
    GongYan__SymmetryAxis = solver.GongYan__SymmetryAxis
    GongYan__AllPoints = solver.GongYan__AllPoints
    GongYan__SectionPlanes = solver.GongYan__SectionPlanes
    GongYan__Log = solver.GongYan__Log

    # --- Step9: PlaneFromLists::4 ---
    PlaneFromLists_4__BasePlane = solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4__OriginPoint = solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4__ResultPlane = solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4__Log = solver.PlaneFromLists_4__Log

    # --- Step9: List Item ---
    GeoAligner_7__SourcePlane_Item = solver.GeoAligner_7__SourcePlane_Item

    # --- Step9: GeoAligner::7 ---
    GeoAligner_7__MovedGeo = flatten_any(solver.GeoAligner_7__MovedGeo)
    GeoAligner_7__SourceOut = solver.GeoAligner_7__SourceOut
    GeoAligner_7__TargetOut = solver.GeoAligner_7__TargetOut
    GeoAligner_7__TransformOut = solver.GeoAligner_7__TransformOut
    GeoAligner_7__Log = solver.GeoAligner_7__Log

    # --- Step10: QiAOTool::2 ---
    QiAOTool_2__CutTimbers = solver.QiAOTool_2__CutTimbers
    QiAOTool_2__FailTimbers = solver.QiAOTool_2__FailTimbers
    QiAOTool_2__Log = solver.QiAOTool_2__Log
    QiAOTool_2__EdgeMidPoints = solver.QiAOTool_2__EdgeMidPoints
    QiAOTool_2__Corner0Planes = solver.QiAOTool_2__Corner0Planes
    QiAOTool_2__TimberBrep = solver.QiAOTool_2__TimberBrep
    QiAOTool_2__ToolBrep = solver.QiAOTool_2__ToolBrep
    QiAOTool_2__AlignedTool = solver.QiAOTool_2__AlignedTool
    QiAOTool_2__RefPlanes = solver.QiAOTool_2__RefPlanes
    QiAOTool_2__PFL1_ResultPlane = solver.QiAOTool_2__PFL1_ResultPlane
    QiAOTool_2__QiAo_FacePlane = solver.QiAOTool_2__QiAo_FacePlane

    # --- Step10: PlaneFromLists::6 ---
    PlaneFromLists_6__BasePlane = solver.PlaneFromLists_6__BasePlane
    PlaneFromLists_6__OriginPoint = solver.PlaneFromLists_6__OriginPoint
    PlaneFromLists_6__ResultPlane = solver.PlaneFromLists_6__ResultPlane
    PlaneFromLists_6__Log = solver.PlaneFromLists_6__Log

    # --- Step10: PlaneFromLists::5 ---
    PlaneFromLists_5__BasePlane = solver.PlaneFromLists_5__BasePlane
    PlaneFromLists_5__OriginPoint = solver.PlaneFromLists_5__OriginPoint
    PlaneFromLists_5__ResultPlane = solver.PlaneFromLists_5__ResultPlane
    PlaneFromLists_5__Log = solver.PlaneFromLists_5__Log

    # --- Step10: GeoAligner::8 ---
    GeoAligner_8__MovedGeo = flatten_any(solver.GeoAligner_8__MovedGeo)
    GeoAligner_8__SourceOut = solver.GeoAligner_8__SourceOut
    GeoAligner_8__TargetOut = solver.GeoAligner_8__TargetOut
    _tf8 = solver.GeoAligner_8__TransformOut
    GeoAligner_8__TransformOut = ght.GH_Transform(_tf8) if (ght is not None and _tf8 is not None and isinstance(_tf8, rg.Transform)) else _tf8
    GeoAligner_8__Log = solver.GeoAligner_8__Log

    # --- Step11: PlaneFromLists::7 ---
    PlaneFromLists_7__BasePlane = solver.PlaneFromLists_7__BasePlane
    PlaneFromLists_7__OriginPoint = solver.PlaneFromLists_7__OriginPoint
    PlaneFromLists_7__ResultPlane = solver.PlaneFromLists_7__ResultPlane
    PlaneFromLists_7__Log = solver.PlaneFromLists_7__Log

    # --- Step11: Juansha ---
    Juansha__ToolBrep = solver.Juansha__ToolBrep
    Juansha__HL_Intersection = solver.Juansha__HL_Intersection
    Juansha__SectionEdges = solver.Juansha__SectionEdges
    Juansha__HeightFacePlane = solver.Juansha__HeightFacePlane
    Juansha__LengthFacePlane = solver.Juansha__LengthFacePlane
    Juansha__Log = solver.Juansha__Log

    # --- Step11: GeoAligner::9 ---
    GeoAligner_9__MovedGeo = flatten_any(solver.GeoAligner_9__MovedGeo)
    GeoAligner_9__SourceOut = solver.GeoAligner_9__SourceOut
    GeoAligner_9__TargetOut = solver.GeoAligner_9__TargetOut
    _tf9 = solver.GeoAligner_9__TransformOut
    GeoAligner_9__TransformOut = ght.GH_Transform(_tf9) if (ght is not None and _tf9 is not None and isinstance(_tf9, rg.Transform)) else _tf9
    GeoAligner_9__Log = solver.GeoAligner_9__Log

    # --- Step12: BlockCutter::5 ---
    BlockCutter_5__TimberBrep = solver.BlockCutter_5__TimberBrep
    BlockCutter_5__FaceList = solver.BlockCutter_5__FaceList
    BlockCutter_5__PointList = solver.BlockCutter_5__PointList
    BlockCutter_5__EdgeList = solver.BlockCutter_5__EdgeList
    BlockCutter_5__CenterPoint = solver.BlockCutter_5__CenterPoint
    BlockCutter_5__CenterAxisLines = solver.BlockCutter_5__CenterAxisLines
    BlockCutter_5__EdgeMidPoints = solver.BlockCutter_5__EdgeMidPoints
    BlockCutter_5__FacePlaneList = solver.BlockCutter_5__FacePlaneList
    BlockCutter_5__Corner0Planes = solver.BlockCutter_5__Corner0Planes
    BlockCutter_5__LocalAxesPlane = solver.BlockCutter_5__LocalAxesPlane
    BlockCutter_5__AxisX = solver.BlockCutter_5__AxisX
    BlockCutter_5__AxisY = solver.BlockCutter_5__AxisY
    BlockCutter_5__AxisZ = solver.BlockCutter_5__AxisZ
    BlockCutter_5__FaceDirTags = solver.BlockCutter_5__FaceDirTags
    BlockCutter_5__EdgeDirTags = solver.BlockCutter_5__EdgeDirTags
    BlockCutter_5__Corner0EdgeDirs = solver.BlockCutter_5__Corner0EdgeDirs
    BlockCutter_5__Log = solver.BlockCutter_5__Log

    # --- Step12: List Item（FacePlaneList -> SourcePlane）---
    GeoAligner_10__SourcePlane_Item = solver.GeoAligner_10__SourcePlane_Item

    # --- Step12: GeoAligner::10 ---
    GeoAligner_10__MovedGeo = flatten_any(solver.GeoAligner_10__MovedGeo)
    GeoAligner_10__SourceOut = solver.GeoAligner_10__SourceOut
    GeoAligner_10__TargetOut = solver.GeoAligner_10__TargetOut
    _tf10 = solver.GeoAligner_10__TransformOut
    GeoAligner_10__TransformOut = ght.GH_Transform(_tf10) if (ght is not None and _tf10 is not None and isinstance(_tf10, rg.Transform)) else _tf10
    GeoAligner_10__Log = solver.GeoAligner_10__Log



# -*- coding: utf-8 -*-
"""
LingGongInLineWXiaoGongTou_4PU_Solver · Step 1 + Step 2（增量 #1）

Step 1) 读取数据库 DG_Dou / type_code = LingGongInLineWXiaoGongTou_4PU / params_json
        - 输出：Value, All, AllDict, DBLog

Step 2) SkewTimber（偏轴木料）
        - BuildTimberBlockUniform_SkewAxis
        - length_fen  = SkewTimber__length_fen
        - width_fen   = SkewTimber__width_fen
        - height_fen  = SkewTimber__height_fen
        - Skew_len    = SkewTimber__Skew_len（若库内键名不同，按 All 实际键名再对齐修正）
        - base_point  = 组件输入 base_point（None -> 原点）
        - reference_plane = GH XZ Plane（X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)）

输出：
    CutTimbers / FailTimbers / Log
    + developer-friendly：暴露到当前步骤为止所有关键成员变量（便于后续继续挂端口）
"""

import Rhino.Geometry as rg
import scriptcontext as sc

import Grasshopper as gh
import Grasshopper.Kernel.Types as ght
from Grasshopper.Kernel.Data import GH_Path

from yingzao.ancientArchi import (
    DBJsonReader,
    BuildTimberBlockUniform_SkewAxis,
    build_timber_block_uniform,
    GeoAligner_xfm,
    FTPlaneFromLists,
    FT_GongYanSection_Cai_B,
    JuanShaToolBuilder,
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.18"


# ==============================================================
# 通用工具函数（与 LingGongSolver.py 风格一致，但做了更稳健的类型处理）
# ==============================================================

def to_list(x):
    """若为 list/tuple 则直接转 list，否则包装成长度为 1 的 list。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]

def all_to_dict(all_list):
    """
    All = [('A__x', 1), ('B__y', [1,2,3]), ...]  -> dict
    """
    d = {}
    if not all_list:
        return d
    for item in all_list:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                d[str(item[0])] = item[1]
        except Exception:
            pass
    return d

def is_net_list(obj):
    """粗略判断 .NET IList（例如 System.Collections.Generic.List[object]）。"""
    try:
        # IronPython 下常见：有 Count 且可索引
        return hasattr(obj, "Count") and hasattr(obj, "__getitem__")
    except Exception:
        return False

def flatten_any(x):
    """
    递归拍平 list/tuple/NET List，避免输出出现：
    System.Collections.Generic.List`1[System.Object] 套娃

    规则：
    - None -> []
    - string / Point3d / Vector3d / Plane / Transform / Rhino.GeometryBase -> 作为原子，不展开
    - list/tuple/NET List -> 递归展开
    """
    out = []
    if x is None:
        return out

    # 原子类型：不展开
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]
    try:
        if isinstance(x, rg.GeometryBase):
            return [x]
    except Exception:
        pass

    # Python list/tuple
    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out

    # .NET List
    if is_net_list(x):
        try:
            for i in range(int(x.Count)):
                out.extend(flatten_any(x[i]))
            return out
        except Exception:
            # 如果遍历失败，退化为原子
            return [x]

    # 其它：当作原子
    return [x]


# -------------------------------
# GH DataTree 处理（稳健识别 / 分支迭代 / 输出构造）
# -------------------------------

def is_tree(x):
    """尽量稳健判断是否为 Grasshopper DataTree。"""
    if x is None:
        return False
    # 常见：Grasshopper.DataTree[object]
    tname = type(x).__name__
    if "DataTree" in tname or "GH_Structure" in tname:
        return True
    # 兜底：具有 BranchCount/Path/Branch 方法
    return hasattr(x, "BranchCount") and hasattr(x, "Path") and hasattr(x, "Branch")


def tree_branch_count(t):
    try:
        return int(t.BranchCount)
    except Exception:
        return 0


def tree_get_branch(t, bi, default_branch=None):
    """取 DataTree 第 bi 个分支，返回 Python list。"""
    if not is_tree(t):
        return default_branch if default_branch is not None else []
    bc = tree_branch_count(t)
    if bc <= 0:
        return default_branch if default_branch is not None else []
    # GH 广播：若 bi 超界，则回退到最后一个分支（或第 0 分支）
    if bi < 0:
        bi = 0
    if bi >= bc:
        bi = bc - 1
    try:
        br = t.Branch(bi)
        # br 通常是 System.Collections.Generic.List[object]
        return [br[i] for i in range(int(br.Count))]
    except Exception:
        try:
            # 某些情况下 Branch(i) 直接可迭代
            return list(t.Branch(bi))
        except Exception:
            return default_branch if default_branch is not None else []


def tree_get_path(t, bi):
    try:
        return t.Path(bi)
    except Exception:
        return GH_Path(bi)


def tree_new_object():
    try:
        return gh.DataTree[object]()
    except Exception:
        # 兜底：某些环境泛型不可用
        return gh.DataTree[object]()


def tree_add_range(dt, path, items):
    if dt is None:
        return
    if items is None:
        return
    # items 允许是单值
    if not isinstance(items, (list, tuple)) and not is_net_list(items):
        dt.Add(items, path)
        return
    try:
        for it in items:
            dt.Add(it, path)
    except Exception:
        try:
            # .NET List
            for i in range(int(items.Count)):
                dt.Add(items[i], path)
        except Exception:
            dt.Add(items, path)


def _as_seq(x):
    """将输入变成序列（用于 GH 广播）。Tree 在此处不处理（由分支循环处理）。"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    if is_net_list(x):
        try:
            return [x[i] for i in range(int(x.Count))]
        except Exception:
            return [x]
    return [x]


def gh_broadcast_get(seq, i):
    """GH 风格广播取值：len==0 -> None；len==1 -> 广播；其它 -> i % len。"""
    if seq is None:
        return None
    if len(seq) == 0:
        return None
    if len(seq) == 1:
        return seq[0]
    return seq[i % len(seq)]


def list_item_gh(list_in, index_in, wrap=False):
    """GH List Item：支持 index 为 scalar / list / tree。输出结构跟随 index。"""
    lst = _as_seq(list_in)
    if index_in is None:
        return None

    def _pick(idx):
        try:
            ii = int(idx)
        except Exception:
            return None
        if not lst:
            return None
        n = len(lst)
        if wrap:
            ii = ii % n
            return lst[ii]
        if ii < 0 or ii >= n:
            return None
        return lst[ii]

    # Tree
    if is_tree(index_in):
        dt = tree_new_object()
        bc = tree_branch_count(index_in)
        for bi in range(bc):
            path = tree_get_path(index_in, bi)
            br = tree_get_branch(index_in, bi, default_branch=[])
            out_items = []
            for idx in br:
                out_items.append(_pick(idx))
            tree_add_range(dt, path, out_items)
        return dt

    # list
    if isinstance(index_in, (list, tuple)) or is_net_list(index_in):
        idxs = _as_seq(index_in)
        return [_pick(i) for i in idxs]

    # scalar
    return _pick(index_in)


def planefromlists_broadcast(origin_points_in, base_planes_in,
                             index_origin_in, index_plane_in,
                             wrap=True):
    """对 FTPlaneFromLists.build_plane 做 GH 风格广播与 Tree 分支循环封装。

    - IndexOrigin 对应 OriginPoints 的索引；IndexPlane 对应 BasePlanes 的索引
    - IndexOrigin / IndexPlane 长度不一致时，按 GH 广播（短的循环到长的）
    - 任一输入为 Tree：按分支循环，输出保持同树结构
    """

    any_tree = any(is_tree(v) for v in [origin_points_in, base_planes_in, index_origin_in, index_plane_in])

    def _one(op, bp, io, ip):
        try:
            builder = FTPlaneFromLists(wrap=wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(op, bp, io, ip)
            return BasePlane, OriginPoint, ResultPlane, Log, None
        except Exception as e:
            return None, None, None, ["错误: {}".format(e)], str(e)

    # 非 Tree：按索引列表广播
    if not any_tree:
        ops = _as_seq(origin_points_in)
        bps = _as_seq(base_planes_in)
        ios = _as_seq(index_origin_in)
        ips = _as_seq(index_plane_in)

        n = max(len(ios), len(ips), 1)
        out_bp, out_op, out_rp, logs, errs = [], [], [], [], []
        for i in range(n):
            bp, op, rp, lg, err = _one(
                ops,
                bps,
                gh_broadcast_get(ios, i),
                gh_broadcast_get(ips, i),
            )
            out_bp.append(bp)
            out_op.append(op)
            out_rp.append(rp)
            logs.extend(lg or [])
            if err:
                errs.append(err)

        if n == 1:
            return out_bp[0], out_op[0], out_rp[0], logs, errs
        return out_bp, out_op, out_rp, logs, errs

    # Tree：分支循环（以最大分支数为主，缺失分支按最后分支广播）
    branch_counts = [tree_branch_count(v) for v in [origin_points_in, base_planes_in, index_origin_in, index_plane_in] if is_tree(v)]
    bc_max = max(branch_counts) if branch_counts else 1

    dt_bp = tree_new_object()
    dt_op = tree_new_object()
    dt_rp = tree_new_object()
    logs, errs = [], []

    for bi in range(bc_max):
        path = GH_Path(bi)

        ops = tree_get_branch(origin_points_in, bi, default_branch=_as_seq(origin_points_in)) if is_tree(origin_points_in) else _as_seq(origin_points_in)
        bps = tree_get_branch(base_planes_in, bi, default_branch=_as_seq(base_planes_in)) if is_tree(base_planes_in) else _as_seq(base_planes_in)
        ios = tree_get_branch(index_origin_in, bi, default_branch=_as_seq(index_origin_in)) if is_tree(index_origin_in) else _as_seq(index_origin_in)
        ips = tree_get_branch(index_plane_in, bi, default_branch=_as_seq(index_plane_in)) if is_tree(index_plane_in) else _as_seq(index_plane_in)

        n = max(len(ios), len(ips), 1)

        out_bp, out_op, out_rp = [], [], []
        for i in range(n):
            bp, op, rp, lg, err = _one(
                ops,
                bps,
                gh_broadcast_get(ios, i),
                gh_broadcast_get(ips, i),
            )
            out_bp.append(bp)
            out_op.append(op)
            out_rp.append(rp)
            logs.extend(lg or [])
            if err:
                errs.append("branch {} item {}: {}".format(bi, i, err))

        tree_add_range(dt_bp, path, out_bp)
        tree_add_range(dt_op, path, out_op)
        tree_add_range(dt_rp, path, out_rp)

    return dt_bp, dt_op, dt_rp, logs, errs


def geoaligner_broadcast(geo_in, sp_in, tp_in,
                         rotate_deg_in=0.0,
                         flip_x_in=False, flip_y_in=False, flip_z_in=False,
                         move_x_in=0.0, move_y_in=0.0, move_z_in=0.0):
    """对 GeoAligner_xfm.align 做 GH 风格广播与 Tree 分支循环封装。"""

    any_tree = any(is_tree(v) for v in [geo_in, sp_in, tp_in, rotate_deg_in,
                                        flip_x_in, flip_y_in, flip_z_in,
                                        move_x_in, move_y_in, move_z_in])

    def _align_one(geo, sp, tp, rdeg, fx, fy, fz, mx, my, mz):
        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                geo,
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
            xf = ght.GH_Transform(xf) if xf is not None else None
            return so, to, xf, mg, None
        except Exception as e:
            return None, None, None, None, str(e)

    if not any_tree:
        geos = _as_seq(geo_in)
        sps = _as_seq(sp_in)
        tps = _as_seq(tp_in)
        rds = _as_seq(rotate_deg_in)
        fxs = _as_seq(flip_x_in)
        fys = _as_seq(flip_y_in)
        fzs = _as_seq(flip_z_in)
        mxs = _as_seq(move_x_in)
        mys = _as_seq(move_y_in)
        mzs = _as_seq(move_z_in)

        n = max(len(geos), len(sps), len(tps), len(rds), len(fxs), len(fys), len(fzs), len(mxs), len(mys), len(mzs), 1)
        src_out, tar_out, xfs, mgs, errs = [], [], [], [], []
        for i in range(n):
            so, to, xf, mg, err = _align_one(
                gh_broadcast_get(geos, i),
                gh_broadcast_get(sps, i),
                gh_broadcast_get(tps, i),
                gh_broadcast_get(rds, i),
                gh_broadcast_get(fxs, i),
                gh_broadcast_get(fys, i),
                gh_broadcast_get(fzs, i),
                gh_broadcast_get(mxs, i),
                gh_broadcast_get(mys, i),
                gh_broadcast_get(mzs, i),
            )
            src_out.append(so)
            tar_out.append(to)
            xfs.append(xf)
            mgs.append(mg)
            if err:
                errs.append(err)

        # 若 n==1，尽量输出单值（更接近 GH 行为）
        if n == 1:
            return src_out[0], tar_out[0], xfs[0], mgs[0], errs
        return src_out, tar_out, xfs, mgs, errs

    # Tree 分支循环：以“最大分支数”为主；缺失的分支按最后分支广播
    branch_counts = [tree_branch_count(v) for v in [geo_in, sp_in, tp_in, rotate_deg_in,
                                                   flip_x_in, flip_y_in, flip_z_in,
                                                   move_x_in, move_y_in, move_z_in] if is_tree(v)]
    bc_max = max(branch_counts) if branch_counts else 1

    dt_src = tree_new_object()
    dt_tar = tree_new_object()
    dt_xf = tree_new_object()
    dt_mg = tree_new_object()
    errs = []

    for bi in range(bc_max):
        path = GH_Path(bi)

        geos = tree_get_branch(geo_in, bi, default_branch=_as_seq(geo_in)) if is_tree(geo_in) else _as_seq(geo_in)
        sps = tree_get_branch(sp_in, bi, default_branch=_as_seq(sp_in)) if is_tree(sp_in) else _as_seq(sp_in)
        tps = tree_get_branch(tp_in, bi, default_branch=_as_seq(tp_in)) if is_tree(tp_in) else _as_seq(tp_in)
        rds = tree_get_branch(rotate_deg_in, bi, default_branch=_as_seq(rotate_deg_in)) if is_tree(rotate_deg_in) else _as_seq(rotate_deg_in)
        fxs = tree_get_branch(flip_x_in, bi, default_branch=_as_seq(flip_x_in)) if is_tree(flip_x_in) else _as_seq(flip_x_in)
        fys = tree_get_branch(flip_y_in, bi, default_branch=_as_seq(flip_y_in)) if is_tree(flip_y_in) else _as_seq(flip_y_in)
        fzs = tree_get_branch(flip_z_in, bi, default_branch=_as_seq(flip_z_in)) if is_tree(flip_z_in) else _as_seq(flip_z_in)
        mxs = tree_get_branch(move_x_in, bi, default_branch=_as_seq(move_x_in)) if is_tree(move_x_in) else _as_seq(move_x_in)
        mys = tree_get_branch(move_y_in, bi, default_branch=_as_seq(move_y_in)) if is_tree(move_y_in) else _as_seq(move_y_in)
        mzs = tree_get_branch(move_z_in, bi, default_branch=_as_seq(move_z_in)) if is_tree(move_z_in) else _as_seq(move_z_in)

        n = max(len(geos), len(sps), len(tps), len(rds), len(fxs), len(fys), len(fzs), len(mxs), len(mys), len(mzs), 1)

        out_so, out_to, out_xf, out_mg = [], [], [], []
        for i in range(n):
            so, to, xf, mg, err = _align_one(
                gh_broadcast_get(geos, i),
                gh_broadcast_get(sps, i),
                gh_broadcast_get(tps, i),
                gh_broadcast_get(rds, i),
                gh_broadcast_get(fxs, i),
                gh_broadcast_get(fys, i),
                gh_broadcast_get(fzs, i),
                gh_broadcast_get(mxs, i),
                gh_broadcast_get(mys, i),
                gh_broadcast_get(mzs, i),
            )
            out_so.append(so)
            out_to.append(to)
            out_xf.append(xf)
            out_mg.append(mg)
            if err:
                errs.append("branch {} item {}: {}".format(bi, i, err))

        tree_add_range(dt_src, path, out_so)
        tree_add_range(dt_tar, path, out_to)
        tree_add_range(dt_xf, path, out_xf)
        tree_add_range(dt_mg, path, out_mg)

    return dt_src, dt_tar, dt_xf, dt_mg, errs


def geoaligner_broadcast_geo_sp_locked(geo_in, sp_in, tp_in,
                                       rotate_deg_in=0.0,
                                       flip_x_in=False, flip_y_in=False, flip_z_in=False,
                                       move_x_in=0.0, move_y_in=0.0, move_z_in=0.0):
    """GeoAligner 广播（特化版）：

    ✅ 仅用于 GeoAligner::4 的特殊需求：
    - Geo 与 SourcePlane **一一对应**（两者的长度/分支决定循环次数）
    - 其它参数（TargetPlane/Rotate/Flip/Move...）只做广播对齐，但**不增加**循环次数。

    说明：
    - 非 Tree：n = max(len(Geo), len(SourcePlane), 1)
    - Tree：按分支循环；每个分支内 n = max(len(GeoBranch), len(SrcBranch), 1)
    - TargetPlane 以及其它参数：在同一 n 内用 gh_broadcast_get 取值
    """

    def _unwrap_single(x):
        """把 GeoAligner_xfm 的返回值里常见的 .NET List[object] / list 单元素拆包。

        目标：输出端不要出现 `System.Collections.Generic.List\`1[System.Object]` 套娃。
        - None -> None
        - 单元素 list / .NET List -> 直接返回该元素
        - 多元素 list / .NET List -> 返回 Python list（不再是 .NET List）
        - 其它 -> 原样返回
        """
        if x is None:
            return None
        if is_net_list(x):
            try:
                c = int(x.Count)
                if c == 0:
                    return None
                if c == 1:
                    return x[0]
                return [x[i] for i in range(c)]
            except Exception:
                return x
        if isinstance(x, (list, tuple)):
            if len(x) == 0:
                return None
            if len(x) == 1:
                return x[0]
            return list(x)
        return x

    def _align_one(geo, sp, tp, rdeg, fx, fy, fz, mx, my, mz):
        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                geo,
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
            xf = ght.GH_Transform(xf) if xf is not None else None
            # 关键：避免 mg 作为 .NET List 被直接塞进输出（会看到 System.Collections.Generic.List...）
            mg = _unwrap_single(mg)
            return so, to, xf, mg, None
        except Exception as e:
            return None, None, None, None, str(e)

    any_tree = any(is_tree(v) for v in [geo_in, sp_in, tp_in, rotate_deg_in,
                                        flip_x_in, flip_y_in, flip_z_in,
                                        move_x_in, move_y_in, move_z_in])

    # -------------------------------
    # 非 Tree：n 只由 (Geo, SourcePlane) 决定
    # -------------------------------
    if not any_tree:
        geos = _as_seq(geo_in)
        sps = _as_seq(sp_in)
        # 其它参数只广播，不参与决定 n
        tps = _as_seq(tp_in)
        rds = _as_seq(rotate_deg_in)
        fxs = _as_seq(flip_x_in)
        fys = _as_seq(flip_y_in)
        fzs = _as_seq(flip_z_in)
        mxs = _as_seq(move_x_in)
        mys = _as_seq(move_y_in)
        mzs = _as_seq(move_z_in)

        n = max(len(geos), len(sps), 1)
        src_out, tar_out, xfs, mgs, errs = [], [], [], [], []
        for i in range(int(n)):
            so, to, xf, mg, err = _align_one(
                gh_broadcast_get(geos, i),
                gh_broadcast_get(sps, i),
                gh_broadcast_get(tps, i),
                gh_broadcast_get(rds, i),
                gh_broadcast_get(fxs, i),
                gh_broadcast_get(fys, i),
                gh_broadcast_get(fzs, i),
                gh_broadcast_get(mxs, i),
                gh_broadcast_get(mys, i),
                gh_broadcast_get(mzs, i),
            )
            src_out.append(so)
            tar_out.append(to)
            xfs.append(xf)
            mgs.append(mg)
            if err:
                errs.append(err)

        if int(n) == 1:
            return src_out[0], tar_out[0], xfs[0], mgs[0], errs
        return src_out, tar_out, xfs, mgs, errs

    # -------------------------------
    # Tree：以 Geo / SourcePlane 的最大分支数为主（两者一一对应）
    # -------------------------------
    bc_geo = tree_branch_count(geo_in) if is_tree(geo_in) else 0
    bc_sp  = tree_branch_count(sp_in)  if is_tree(sp_in)  else 0
    bc_max = max(bc_geo, bc_sp, 1)

    dt_src = tree_new_object()
    dt_tar = tree_new_object()
    dt_xf  = tree_new_object()
    dt_mg  = tree_new_object()
    errs = []

    # 其它输入的分支数（用于广播缺失分支）
    def _branch_seq(v, bi):
        if is_tree(v):
            bc = tree_branch_count(v)
            if bc <= 0:
                return []
            if bi >= bc:
                bi = bc - 1
            return tree_get_branch(v, bi, default_branch=[])
        return _as_seq(v)

    for bi in range(int(bc_max)):
        # path：优先沿用 Geo 的 path，其次 SourcePlane
        if is_tree(geo_in) and bc_geo > 0:
            path = tree_get_path(geo_in, bi if bi < bc_geo else (bc_geo - 1))
        elif is_tree(sp_in) and bc_sp > 0:
            path = tree_get_path(sp_in, bi if bi < bc_sp else (bc_sp - 1))
        else:
            path = GH_Path(bi)

        geos = _branch_seq(geo_in, bi)
        sps  = _branch_seq(sp_in, bi)

        # n：只由 (GeoBranch, SrcBranch) 决定
        n = max(len(geos), len(sps), 1)

        tps = _branch_seq(tp_in, bi)
        rds = _branch_seq(rotate_deg_in, bi)
        fxs = _branch_seq(flip_x_in, bi)
        fys = _branch_seq(flip_y_in, bi)
        fzs = _branch_seq(flip_z_in, bi)
        mxs = _branch_seq(move_x_in, bi)
        mys = _branch_seq(move_y_in, bi)
        mzs = _branch_seq(move_z_in, bi)

        out_so, out_to, out_xf, out_mg = [], [], [], []
        for i in range(int(n)):
            so, to, xf, mg, err = _align_one(
                gh_broadcast_get(geos, i),
                gh_broadcast_get(sps, i),
                gh_broadcast_get(tps, i),
                gh_broadcast_get(rds, i),
                gh_broadcast_get(fxs, i),
                gh_broadcast_get(fys, i),
                gh_broadcast_get(fzs, i),
                gh_broadcast_get(mxs, i),
                gh_broadcast_get(mys, i),
                gh_broadcast_get(mzs, i),
            )
            out_so.append(so)
            out_to.append(to)
            out_xf.append(xf)
            out_mg.append(mg)
            if err:
                errs.append("branch {} item {}: {}".format(bi, i, err))

        tree_add_range(dt_src, path, out_so)
        tree_add_range(dt_tar, path, out_to)
        tree_add_range(dt_xf,  path, out_xf)
        tree_add_range(dt_mg,  path, out_mg)

    return dt_src, dt_tar, dt_xf, dt_mg, errs


def gh_plane_XY(origin):
    x = rg.Vector3d(1, 0, 0)
    y = rg.Vector3d(0, 1, 0)
    return rg.Plane(origin, x, y)

def gh_plane_XZ(origin):
    """
    Grasshopper 的 XZ Plane（按你的约定轴向）
    X = (1,0,0)
    Y = (0,0,1)
    Z = X × Y = (0,-1,0)
    """
    x = rg.Vector3d(1, 0, 0)
    y = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, x, y)

def gh_plane_YZ(origin):
    x = rg.Vector3d(0, 1, 0)
    y = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, x, y)

def first_or_default(v, default=None):
    """若 v 为 list/tuple，则取第一个；否则直接返回；None -> default。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        return v[0] if len(v) else default
    return v


# ==============================================================
# 主 Solver 类 —— LingGongInLineWXiaoGongTou_4PU_Solver
# ==============================================================

class LingGongInLineWXiaoGongTou_4PU_Solver(object):

    def __init__(self,
                 DBPath,
                 base_point,
                 reference_plane,
                 Refresh,
                 ghenv,
                 TimberBlock_1__length_fen=None,
                 TimberBlock_1__width_fen=None,
                 TimberBlock_1__height_fen=None,
                 GeoAligner_1__SourcePlane=None,
                 GeoAligner_1__TargetPlane=None,
                 GeoAligner_1__RotateDeg=None,
                 GeoAligner_1__FlipX=None,
                 GeoAligner_1__FlipY=None,
                 GeoAligner_1__FlipZ=None,
                 GeoAligner_1__MoveX=None,
                 GeoAligner_1__MoveY=None,
                 GeoAligner_1__MoveZ=None,
                 PlaneFromLists_1__IndexOrigin=None,
                 PlaneFromLists_1__IndexPlane=None,
                 PlaneFromLists_1__Wrap=None,
                 Juansha_1__HeightFen=None,
                 Juansha_1__LengthFen=None,
                 Juansha_1__DivCount=None,
                 Juansha_1__ThicknessFen=None,
                 Juansha_1__SectionPlane=None,
                 Juansha_1__PositionPoint=None,
                 GeoAligner_2__RotateDeg=None,
                 GeoAligner_2__FlipX=None,
                 GeoAligner_2__FlipY=None,
                 GeoAligner_2__FlipZ=None,
                 GeoAligner_2__MoveX=None,
                 GeoAligner_2__MoveY=None,
                 GeoAligner_2__MoveZ=None,
                 PlaneFromLists_2__IndexOrigin=None,
                 PlaneFromLists_2__IndexPlane=None,
                 PlaneFromLists_2__Wrap=None,
                 Juansha_2__HeightFen=None,
                 Juansha_2__LengthFen=None,
                 Juansha_2__DivCount=None,
                 Juansha_2__ThicknessFen=None,
                 Juansha_2__SectionPlane=None,
                 Juansha_2__PositionPoint=None,
                 GeoAligner_3__RotateDeg=None,
                 GeoAligner_3__FlipX=None,
                 GeoAligner_3__FlipY=None,
                 GeoAligner_3__FlipZ=None,
                 GeoAligner_3__MoveX=None,
                 GeoAligner_3__MoveY=None,
                 GeoAligner_3__MoveZ=None,

                 # -------- Step6 输入端（增量）--------
                 PlaneFromLists_3__IndexOrigin=None,
                 PlaneFromLists_3__IndexPlane=None,
                 PlaneFromLists_3__Wrap=None,

                 GongYanB__SectionPlane=None,
                 GongYanB__A=None,
                 GongYanB__RadiusFen=None,
                 GongYanB__LengthFen=None,
                 GongYanB__OffsetFen=None,
                 GongYanB__ExtrudeFen=None,

                 GeoAligner_4__Geo=None,

                 PlaneFromLists_4__IndexOrigin=None,
                 PlaneFromLists_4__IndexPlane=None,
                 PlaneFromLists_4__Wrap=None,

                 GeoAligner_4__RotateDeg=None,
                 GeoAligner_4__FlipX=None,
                 GeoAligner_4__FlipY=None,
                 GeoAligner_4__FlipZ=None,
                 GeoAligner_4__MoveX=None,
                 GeoAligner_4__MoveY=None,
                 GeoAligner_4__MoveZ=None,

                 # -------- Step7 输入端（增量）--------
                 TimberBlock_2__length_fen=None,
                 TimberBlock_2__width_fen=None,
                 TimberBlock_2__height_fen=None,
                 GeoAligner_5__SourcePlane=None,
                 GeoAligner_5__TargetPlane=None,
                 GeoAligner_5__RotateDeg=None,
                 GeoAligner_5__MoveZ=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.reference_plane = reference_plane
        self.Refresh = Refresh
        self.ghenv = ghenv

        # -------- Step3 输入端缓存（参数优先级：输入端 > DB > 默认）--------
        self.TimberBlock_1__length_fen_in = TimberBlock_1__length_fen
        self.TimberBlock_1__width_fen_in = TimberBlock_1__width_fen
        self.TimberBlock_1__height_fen_in = TimberBlock_1__height_fen

        self.GeoAligner_1__SourcePlane_in = GeoAligner_1__SourcePlane
        self.GeoAligner_1__TargetPlane_in = GeoAligner_1__TargetPlane
        self.GeoAligner_1__RotateDeg_in = GeoAligner_1__RotateDeg
        self.GeoAligner_1__FlipX_in = GeoAligner_1__FlipX
        self.GeoAligner_1__FlipY_in = GeoAligner_1__FlipY
        self.GeoAligner_1__FlipZ_in = GeoAligner_1__FlipZ
        self.GeoAligner_1__MoveX_in = GeoAligner_1__MoveX
        self.GeoAligner_1__MoveY_in = GeoAligner_1__MoveY
        self.GeoAligner_1__MoveZ_in = GeoAligner_1__MoveZ

        # -------- Step4 输入端缓存 --------
        self.PlaneFromLists_1__IndexOrigin_in = PlaneFromLists_1__IndexOrigin
        self.PlaneFromLists_1__IndexPlane_in = PlaneFromLists_1__IndexPlane
        self.PlaneFromLists_1__Wrap_in = PlaneFromLists_1__Wrap

        self.Juansha_1__HeightFen_in = Juansha_1__HeightFen
        self.Juansha_1__LengthFen_in = Juansha_1__LengthFen
        self.Juansha_1__DivCount_in = Juansha_1__DivCount
        self.Juansha_1__ThicknessFen_in = Juansha_1__ThicknessFen
        self.Juansha_1__SectionPlane_in = Juansha_1__SectionPlane
        self.Juansha_1__PositionPoint_in = Juansha_1__PositionPoint

        self.GeoAligner_2__RotateDeg_in = GeoAligner_2__RotateDeg
        self.GeoAligner_2__FlipX_in = GeoAligner_2__FlipX
        self.GeoAligner_2__FlipY_in = GeoAligner_2__FlipY
        self.GeoAligner_2__FlipZ_in = GeoAligner_2__FlipZ
        self.GeoAligner_2__MoveX_in = GeoAligner_2__MoveX
        self.GeoAligner_2__MoveY_in = GeoAligner_2__MoveY
        self.GeoAligner_2__MoveZ_in = GeoAligner_2__MoveZ

        # -------- Step5 输入端缓存 --------
        self.PlaneFromLists_2__IndexOrigin_in = PlaneFromLists_2__IndexOrigin
        self.PlaneFromLists_2__IndexPlane_in = PlaneFromLists_2__IndexPlane
        self.PlaneFromLists_2__Wrap_in = PlaneFromLists_2__Wrap

        self.Juansha_2__HeightFen_in = Juansha_2__HeightFen
        self.Juansha_2__LengthFen_in = Juansha_2__LengthFen
        self.Juansha_2__DivCount_in = Juansha_2__DivCount
        self.Juansha_2__ThicknessFen_in = Juansha_2__ThicknessFen
        self.Juansha_2__SectionPlane_in = Juansha_2__SectionPlane
        self.Juansha_2__PositionPoint_in = Juansha_2__PositionPoint

        self.GeoAligner_3__RotateDeg_in = GeoAligner_3__RotateDeg
        self.GeoAligner_3__FlipX_in = GeoAligner_3__FlipX
        self.GeoAligner_3__FlipY_in = GeoAligner_3__FlipY
        self.GeoAligner_3__FlipZ_in = GeoAligner_3__FlipZ
        self.GeoAligner_3__MoveX_in = GeoAligner_3__MoveX
        self.GeoAligner_3__MoveY_in = GeoAligner_3__MoveY
        self.GeoAligner_3__MoveZ_in = GeoAligner_3__MoveZ

        # -------- Step6 输入端缓存 --------
        self.PlaneFromLists_3__IndexOrigin_in = PlaneFromLists_3__IndexOrigin
        self.PlaneFromLists_3__IndexPlane_in = PlaneFromLists_3__IndexPlane
        self.PlaneFromLists_3__Wrap_in = PlaneFromLists_3__Wrap

        self.GongYanB__SectionPlane_in = GongYanB__SectionPlane
        self.GongYanB__A_in = GongYanB__A
        self.GongYanB__RadiusFen_in = GongYanB__RadiusFen
        self.GongYanB__LengthFen_in = GongYanB__LengthFen
        self.GongYanB__OffsetFen_in = GongYanB__OffsetFen
        self.GongYanB__ExtrudeFen_in = GongYanB__ExtrudeFen

        self.GeoAligner_4__Geo_in = GeoAligner_4__Geo

        self.PlaneFromLists_4__IndexOrigin_in = PlaneFromLists_4__IndexOrigin
        self.PlaneFromLists_4__IndexPlane_in = PlaneFromLists_4__IndexPlane
        self.PlaneFromLists_4__Wrap_in = PlaneFromLists_4__Wrap

        self.GeoAligner_4__RotateDeg_in = GeoAligner_4__RotateDeg
        self.GeoAligner_4__FlipX_in = GeoAligner_4__FlipX
        self.GeoAligner_4__FlipY_in = GeoAligner_4__FlipY
        self.GeoAligner_4__FlipZ_in = GeoAligner_4__FlipZ
        self.GeoAligner_4__MoveX_in = GeoAligner_4__MoveX
        self.GeoAligner_4__MoveY_in = GeoAligner_4__MoveY
        self.GeoAligner_4__MoveZ_in = GeoAligner_4__MoveZ

        # -------- Step7 输入端缓存 --------
        self.TimberBlock_2__length_fen_in = TimberBlock_2__length_fen
        self.TimberBlock_2__width_fen_in = TimberBlock_2__width_fen
        self.TimberBlock_2__height_fen_in = TimberBlock_2__height_fen

        self.GeoAligner_5__SourcePlane_in = GeoAligner_5__SourcePlane
        self.GeoAligner_5__TargetPlane_in = GeoAligner_5__TargetPlane
        self.GeoAligner_5__RotateDeg_in = GeoAligner_5__RotateDeg
        self.GeoAligner_5__MoveZ_in = GeoAligner_5__MoveZ

        # -------- Step 1：数据库读取相关成员 --------
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # -------- Step 2：SkewTimber 输出成员（加前缀避免重名）--------
        self.SkewTimber_TimberBrep = None
        self.SkewTimber_FaceList = []
        self.SkewTimber_PointList = []
        self.SkewTimber_EdgeList = []
        self.SkewTimber_CenterPoint = None
        self.SkewTimber_CenterAxisLines = []
        self.SkewTimber_EdgeMidPoints = []
        self.SkewTimber_FacePlaneList = []
        self.SkewTimber_Corner0Planes = []
        self.SkewTimber_LocalAxesPlane = None
        self.SkewTimber_AxisX = None
        self.SkewTimber_AxisY = None
        self.SkewTimber_AxisZ = None
        self.SkewTimber_FaceDirTags = []
        self.SkewTimber_EdgeDirTags = []
        self.SkewTimber_Corner0EdgeDirs = []
        self.SkewTimber_Log = []

        # Skew 专属输出
        self.Skew_A = None
        self.Skew_Point_B = None
        self.Skew_Point_C = None
        self.Skew_Planes = []
        self.Skew_ExtraPoints_GF_EH = []

        # -------- Step 3：TimberBlock::1 输出成员 --------
        self.TimberBlock_1__TimberBrep = None
        self.TimberBlock_1__FaceList = []
        self.TimberBlock_1__PointList = []
        self.TimberBlock_1__EdgeList = []
        self.TimberBlock_1__CenterPoint = None
        self.TimberBlock_1__CenterAxisLines = []
        self.TimberBlock_1__EdgeMidPoints = []
        self.TimberBlock_1__FacePlaneList = []
        self.TimberBlock_1__Corner0Planes = []
        self.TimberBlock_1__LocalAxesPlane = None
        self.TimberBlock_1__AxisX = None
        self.TimberBlock_1__AxisY = None
        self.TimberBlock_1__AxisZ = None
        self.TimberBlock_1__FaceDirTags = []
        self.TimberBlock_1__EdgeDirTags = []
        self.TimberBlock_1__Corner0EdgeDirs = []
        self.TimberBlock_1__Log = []

        # -------- Step 3：List Item 输出 --------
        self.GeoAligner_1__SourcePlane_Item = None
        self.GeoAligner_1__TargetPlane_Item = None

        # -------- Step 3：GeoAligner::1 输出 --------
        self.GeoAligner_1__SourceOut = None
        self.GeoAligner_1__TargetOut = None
        self.GeoAligner_1__MovedGeo = None
        self.GeoAligner_1__TransformOut = None
        self.Step3_Log = []

        # -------- Step 4：PlaneFromLists::1 输出成员 --------
        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        # -------- Step 4：Juansha::1 输出成员 --------
        self.Juansha_1__ToolBrep = None
        self.Juansha_1__HL_Intersection = None
        self.Juansha_1__SectionEdges = None
        self.Juansha_1__HeightFacePlane = None
        self.Juansha_1__LengthFacePlane = None
        self.Juansha_1__Log = []

        # -------- Step 4：GeoAligner::2 输出成员 --------
        self.GeoAligner_2__SourceOut = None
        self.GeoAligner_2__TargetOut = None
        self.GeoAligner_2__MovedGeo = None
        self.GeoAligner_2__TransformOut = None
        self.Step4_Log = []

        # -------- Step 5：PlaneFromLists::2 输出成员 --------
        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        # -------- Step 5：Juansha::2 输出成员 --------
        self.Juansha_2__ToolBrep = None
        self.Juansha_2__HL_Intersection = None
        self.Juansha_2__SectionEdges = None
        self.Juansha_2__HeightFacePlane = None
        self.Juansha_2__LengthFacePlane = None
        self.Juansha_2__Log = []

        # -------- Step 5：GeoAligner::3 输出成员 --------
        self.GeoAligner_3__SourceOut = None
        self.GeoAligner_3__TargetOut = None
        self.GeoAligner_3__MovedGeo = None
        self.GeoAligner_3__TransformOut = None
        self.Step5_Log = []

        # -------- Step 6：PlaneFromLists::3 输出成员 --------
        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        # -------- Step 6：GongYanB 输出成员 --------
        self.GongYanB__ToolBrep = None
        self.GongYanB__SectionFace = None
        self.GongYanB__Points = None
        self.GongYanB__InnerPoints = None
        self.GongYanB__TopPlaneA = None
        self.GongYanB__TopPlaneB = None
        self.GongYanB__BridgePoints = None
        self.GongYanB__BridgeMidPoints = None
        self.GongYanB__BridgePlane = None
        self.GongYanB__Log = []

        # -------- Step 6：List Item（Tree Index）输出 --------
        self.GeoAligner_4__Geo_Item = None

        # -------- Step 6：PlaneFromLists::4 输出成员 --------
        self.PlaneFromLists_4__BasePlane = None
        self.PlaneFromLists_4__OriginPoint = None
        self.PlaneFromLists_4__ResultPlane = None
        self.PlaneFromLists_4__Log = []

        # -------- Step 6：GeoAligner::4 输出成员 --------
        self.GeoAligner_4__SourceOut = None
        self.GeoAligner_4__TargetOut = None
        self.GeoAligner_4__MovedGeo = None
        self.GeoAligner_4__TransformOut = None
        self.Step6_Log = []

        # -------- Step 7：TimberBlock::2 输出成员 --------
        self.TimberBlock_2__TimberBrep = None
        self.TimberBlock_2__FaceList = []
        self.TimberBlock_2__PointList = []
        self.TimberBlock_2__EdgeList = []
        self.TimberBlock_2__CenterPoint = None
        self.TimberBlock_2__CenterAxisLines = []
        self.TimberBlock_2__EdgeMidPoints = []
        self.TimberBlock_2__FacePlaneList = []
        self.TimberBlock_2__Corner0Planes = []
        self.TimberBlock_2__LocalAxesPlane = None
        self.TimberBlock_2__AxisX = None
        self.TimberBlock_2__AxisY = None
        self.TimberBlock_2__AxisZ = None
        self.TimberBlock_2__FaceDirTags = []
        self.TimberBlock_2__EdgeDirTags = []
        self.TimberBlock_2__Corner0EdgeDirs = []
        self.TimberBlock_2__Log = []

        # -------- Step 7：List Item 输出成员 --------
        self.GeoAligner_5__SourcePlane_Item = None
        self.GeoAligner_5__TargetPlane_Item = None
        self.GeoAligner_5__TargetPlane_Reset = None

        # -------- Step 7：GeoAligner::5 输出成员 --------
        self.GeoAligner_5__SourceOut = None
        self.GeoAligner_5__TargetOut = None
        self.GeoAligner_5__MovedGeo = None
        self.GeoAligner_5__TransformOut = None
        self.Step7_Log = []

        # -------- 最终输出（本增量先占位，后续步骤会写入）--------
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：从 AllDict 取值（与 LingGongSolver.py 一致的语义）
    # ------------------------------------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict[key]
        # 若是长度为 1 的列表/元组，则解包
        if isinstance(v, (list, tuple)) and len(v) == 1:
            return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库
    # ------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="LingGongInLineWXiaoGongTou_4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
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
    # Step 2：SkewTimber（BuildTimberBlockUniform_SkewAxis）
    # ------------------------------------------------------
    def step2_skew_timber(self):

        # 参数优先级：组件输入 > 数据库 > 默认
        # 说明：本步骤只有 base_point 来自组件输入；其它 fen 参数来自数据库/默认

        # --- base_point ---
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0, 0, 0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location

        # --- reference_plane 默认 GH XZ ---
        ref_plane = gh_plane_XZ(bp)

        # --- fen 参数（从 AllDict）---
        length_raw = self.all_get("SkewTimber__length_fen", 32.0)
        width_raw  = self.all_get("SkewTimber__width_fen",  32.0)
        height_raw = self.all_get("SkewTimber__height_fen", 20.0)

        # Skew_len：按你 Step2 组件代码里变量名为 Skew_len；数据库键名这里先约定 SkewTimber__Skew_len
        # 如果你库里实际是 SkewTimber__Skew_len 或 SkewTimber__Skew_len_fen/Skew_len 等，后续我会按 All 实际键名对齐
        skew_len_raw = self.all_get("SkewTimber__Skew_len", 20.0)

        try:
            length_fen = float(first_or_default(length_raw, 32.0))
            width_fen  = float(first_or_default(width_raw,  32.0))
            height_fen = float(first_or_default(height_raw, 20.0))
            skew_len   = float(first_or_default(skew_len_raw, 20.0))
        except Exception as e:
            self.Log.append("[SkewTimber] fen 参数转换失败: {}，使用默认值".format(e))
            length_fen, width_fen, height_fen, skew_len = 32.0, 32.0, 20.0, 20.0

        try:
            _obj = BuildTimberBlockUniform_SkewAxis(
                length_fen,
                width_fen,
                height_fen,
                bp,
                ref_plane,
                skew_len,
            )

            # 主输出（带 SkewTimber_ 前缀，避免后续与其它 Timber/BlockCutter 重名）
            self.SkewTimber_TimberBrep = _obj.TimberBrep
            self.SkewTimber_FaceList = _obj.FaceList
            self.SkewTimber_PointList = _obj.PointList
            self.SkewTimber_EdgeList = _obj.EdgeList
            self.SkewTimber_CenterPoint = _obj.CenterPoint
            self.SkewTimber_CenterAxisLines = _obj.CenterAxisLines
            self.SkewTimber_EdgeMidPoints = _obj.EdgeMidPoints
            self.SkewTimber_FacePlaneList = _obj.FacePlaneList
            self.SkewTimber_Corner0Planes = _obj.Corner0Planes
            self.SkewTimber_LocalAxesPlane = _obj.LocalAxesPlane
            self.SkewTimber_AxisX = _obj.AxisX
            self.SkewTimber_AxisY = _obj.AxisY
            self.SkewTimber_AxisZ = _obj.AxisZ
            self.SkewTimber_FaceDirTags = _obj.FaceDirTags
            self.SkewTimber_EdgeDirTags = _obj.EdgeDirTags
            self.SkewTimber_Corner0EdgeDirs = _obj.Corner0EdgeDirs
            self.SkewTimber_Log = _obj.Log

            # Skew 专属
            self.Skew_A = getattr(_obj, "Skew_A", None)
            self.Skew_Point_B = getattr(_obj, "Skew_Point_B", None)
            self.Skew_Point_C = getattr(_obj, "Skew_Point_C", None)
            self.Skew_Planes = getattr(_obj, "Skew_Planes", [])
            self.Skew_ExtraPoints_GF_EH = getattr(_obj, "Skew_ExtraPoints_GF_EH", [])

            self.Log.append("[SkewTimber] BuildTimberBlockUniform_SkewAxis 完成")
            for l in (self.SkewTimber_Log or []):
                self.Log.append("[SkewTimber] " + str(l))

        except Exception as e:
            self.SkewTimber_TimberBrep = None
            self.SkewTimber_Log = ["主逻辑错误: {}".format(e)]
            self.Log.append("[ERROR] step2_skew_timber 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3：TimberBlock::1 + List Item ×2 + GeoAligner::1
    # ------------------------------------------------------
    def step3_timberblock_geoaligner(self):

        self.Step3_Log = []

        # -----------------
        # TimberBlock::1 输入参数（输入端 > DB > 默认）
        # -----------------
        # base_point：组件输入 base_point；None -> 原点
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0, 0, 0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location

        # reference_plane：组件输入 reference_plane；None -> GH XZ Plane
        ref_plane = self.reference_plane
        if ref_plane is None:
            ref_plane = gh_plane_XZ(bp)

        # fen 参数：输入端 > AllDict > 默认
        length_raw = self.TimberBlock_1__length_fen_in
        if length_raw is None:
            length_raw = self.all_get("TimberBlock_1__length_fen", 32.0)
        width_raw = self.TimberBlock_1__width_fen_in
        if width_raw is None:
            width_raw = self.all_get("TimberBlock_1__width_fen", 32.0)
        height_raw = self.TimberBlock_1__height_fen_in
        if height_raw is None:
            height_raw = self.all_get("TimberBlock_1__height_fen", 20.0)

        try:
            length_fen = float(first_or_default(length_raw, 32.0))
            width_fen = float(first_or_default(width_raw, 32.0))
            height_fen = float(first_or_default(height_raw, 20.0))
        except Exception as e:
            self.Step3_Log.append("[TimberBlock::1] fen 参数转换失败: {}，使用默认值".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        # -----------------
        # TimberBlock::1 主逻辑
        # -----------------
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

            self.TimberBlock_1__TimberBrep = timber_brep
            self.TimberBlock_1__FaceList = faces
            self.TimberBlock_1__PointList = points
            self.TimberBlock_1__EdgeList = edges
            self.TimberBlock_1__CenterPoint = center_pt
            self.TimberBlock_1__CenterAxisLines = center_axes
            self.TimberBlock_1__EdgeMidPoints = edge_midpts
            self.TimberBlock_1__FacePlaneList = face_planes
            self.TimberBlock_1__Corner0Planes = corner0_planes
            self.TimberBlock_1__LocalAxesPlane = local_axes_plane
            self.TimberBlock_1__AxisX = axis_x
            self.TimberBlock_1__AxisY = axis_y
            self.TimberBlock_1__AxisZ = axis_z
            self.TimberBlock_1__FaceDirTags = face_tags
            self.TimberBlock_1__EdgeDirTags = edge_tags
            self.TimberBlock_1__Corner0EdgeDirs = corner0_dirs
            self.TimberBlock_1__Log = log_lines

            self.Step3_Log.append("[TimberBlock::1] 完成")
        except Exception as e:
            self.TimberBlock_1__TimberBrep = None
            self.TimberBlock_1__FacePlaneList = []
            self.TimberBlock_1__Log = ["错误: {}".format(e)]
            self.Step3_Log.append("[ERROR] TimberBlock::1 出错: {}".format(e))
            return self

        # -----------------
        # List Item ×2
        # -----------------
        try:
            # 2.1 SourcePlane from TimberBlock FacePlaneList
            idx_sp = self.GeoAligner_1__SourcePlane_in
            if idx_sp is None:
                idx_sp = self.all_get("GeoAligner_1__SourcePlane", 0)
            self.GeoAligner_1__SourcePlane_Item = list_item_gh(self.TimberBlock_1__FacePlaneList, idx_sp, wrap=False)

            # 2.2 TargetPlane from Skew_Planes (upstream)
            idx_tp = self.GeoAligner_1__TargetPlane_in
            if idx_tp is None:
                idx_tp = self.all_get("GeoAligner_1__TargetPlane", 0)
            self.GeoAligner_1__TargetPlane_Item = list_item_gh(self.Skew_Planes, idx_tp, wrap=False)

            self.Step3_Log.append("[List Item] Source/Target Plane 提取完成")
        except Exception as e:
            self.GeoAligner_1__SourcePlane_Item = None
            self.GeoAligner_1__TargetPlane_Item = None
            self.Step3_Log.append("[ERROR] List Item 出错: {}".format(e))
            return self

        # -----------------
        # GeoAligner::1 输入参数（输入端 > DB > 默认）
        # -----------------
        def _get_in_or_db(name, default):
            v_in = getattr(self, name + "_in", None)
            if v_in is not None:
                return v_in
            return self.all_get(name, default)

        rotate_deg = _get_in_or_db("GeoAligner_1__RotateDeg", 0.0)
        flip_x = _get_in_or_db("GeoAligner_1__FlipX", False)
        flip_y = _get_in_or_db("GeoAligner_1__FlipY", False)
        flip_z = _get_in_or_db("GeoAligner_1__FlipZ", False)
        move_x = _get_in_or_db("GeoAligner_1__MoveX", 0.0)
        move_y = _get_in_or_db("GeoAligner_1__MoveY", 0.0)
        move_z = _get_in_or_db("GeoAligner_1__MoveZ", 0.0)

        # -----------------
        # GeoAligner::1 广播/Tree
        # -----------------
        try:
            so, to, xf, mg, errs = geoaligner_broadcast(
                self.TimberBlock_1__TimberBrep,
                self.GeoAligner_1__SourcePlane_Item,
                self.GeoAligner_1__TargetPlane_Item,
                rotate_deg_in=rotate_deg,
                flip_x_in=flip_x,
                flip_y_in=flip_y,
                flip_z_in=flip_z,
                move_x_in=move_x,
                move_y_in=move_y,
                move_z_in=move_z,
            )

            self.GeoAligner_1__SourceOut = so
            self.GeoAligner_1__TargetOut = to
            self.GeoAligner_1__TransformOut = xf
            self.GeoAligner_1__MovedGeo = mg

            if errs:
                for e in errs:
                    self.Step3_Log.append("[GeoAligner::1] " + str(e))
            else:
                self.Step3_Log.append("[GeoAligner::1] 完成")

        except Exception as e:
            self.GeoAligner_1__SourceOut = None
            self.GeoAligner_1__TargetOut = None
            self.GeoAligner_1__TransformOut = None
            self.GeoAligner_1__MovedGeo = None
            self.Step3_Log.append("[ERROR] GeoAligner::1 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4：PlaneFromLists::1 + Juansha::1 + GeoAligner::2
    # ------------------------------------------------------
    def step4_planefromlists_juansha_geoaligner(self):

        self.Step4_Log = []

        # ==================================================
        # Step4A：PlaneFromLists::1（从 SkewTimber 提取 ResultPlane）
        # OriginPoints = SkewTimber_EdgeMidPoints
        # BasePlanes   = SkewTimber_Corner0Planes
        # ==================================================
        try:
            origin_points = self.SkewTimber_EdgeMidPoints
            base_planes = self.SkewTimber_Corner0Planes

            idx_origin = self.PlaneFromLists_1__IndexOrigin_in
            if idx_origin is None:
                idx_origin = self.all_get("PlaneFromLists_1__IndexOrigin", 0)

            idx_plane = self.PlaneFromLists_1__IndexPlane_in
            if idx_plane is None:
                idx_plane = self.all_get("PlaneFromLists_1__IndexPlane", 0)

            wrap = self.PlaneFromLists_1__Wrap_in
            if wrap is None:
                wrap = self.all_get("PlaneFromLists_1__Wrap", True)
            try:
                wrap = bool(first_or_default(wrap, True))
            except Exception:
                wrap = True

            bp, op, rp, lg, errs = planefromlists_broadcast(
                origin_points,
                base_planes,
                idx_origin,
                idx_plane,
                wrap=wrap,
            )

            self.PlaneFromLists_1__BasePlane = bp
            self.PlaneFromLists_1__OriginPoint = op
            self.PlaneFromLists_1__ResultPlane = rp
            self.PlaneFromLists_1__Log = lg or []

            self.Step4_Log.append("[PlaneFromLists::1] 完成")
            if errs:
                for e in errs:
                    self.Step4_Log.append("[PlaneFromLists::1] " + str(e))

        except Exception as e:
            self.PlaneFromLists_1__BasePlane = None
            self.PlaneFromLists_1__OriginPoint = None
            self.PlaneFromLists_1__ResultPlane = None
            self.PlaneFromLists_1__Log = ["错误: {}".format(e)]
            self.Step4_Log.append("[ERROR] PlaneFromLists::1 出错: {}".format(e))
            return self

        # ==================================================
        # Step4B：Juansha::1（卷杀刀具）
        # ==================================================
        try:
            # PositionPoint：组件输入点；若无 -> 原点
            pp = self.Juansha_1__PositionPoint_in
            if pp is None:
                pp = self.all_get("Juansha_1__PositionPoint", None)
            if pp is None:
                pp = rg.Point3d(0, 0, 0)
            elif isinstance(pp, rg.Point):
                pp = pp.Location

            # SectionPlane：未接线则默认 GH XZ（以 PositionPoint 为原点）
            sp = self.Juansha_1__SectionPlane_in
            if sp is None:
                sp = self.all_get("Juansha_1__SectionPlane", None)
            if sp is None:
                sp = gh_plane_XZ(pp)

            # 参数（输入端 > DB > 默认）
            h_raw = self.Juansha_1__HeightFen_in
            if h_raw is None:
                h_raw = self.all_get("Juansha_1__HeightFen", 10.0)

            l_raw = self.Juansha_1__LengthFen_in
            if l_raw is None:
                l_raw = self.all_get("Juansha_1__LengthFen", 80.0)

            d_raw = self.Juansha_1__DivCount_in
            if d_raw is None:
                d_raw = self.all_get("Juansha_1__DivCount", 8)

            t_raw = self.Juansha_1__ThicknessFen_in
            if t_raw is None:
                t_raw = self.all_get("Juansha_1__ThicknessFen", 6.0)

            try:
                HeightFen = float(first_or_default(h_raw, 10.0))
                LengthFen = float(first_or_default(l_raw, 80.0))
                DivCount = int(first_or_default(d_raw, 8))
                ThicknessFen = float(first_or_default(t_raw, 6.0))
            except Exception as e:
                self.Step4_Log.append("[Juansha::1] 参数转换失败: {}，使用默认值".format(e))
                HeightFen, LengthFen, DivCount, ThicknessFen = 10.0, 80.0, 8, 6.0

            builder = JuanShaToolBuilder(
                height_fen=HeightFen,
                length_fen=LengthFen,
                thickness_fen=ThicknessFen,
                div_count=DivCount,
                section_plane=sp,
                position_point=pp,
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, Log = builder.build()

            self.Juansha_1__ToolBrep = ToolBrep
            self.Juansha_1__SectionEdges = SectionEdges
            self.Juansha_1__HL_Intersection = HL_Intersection
            self.Juansha_1__HeightFacePlane = HeightFacePlane
            self.Juansha_1__LengthFacePlane = LengthFacePlane
            self.Juansha_1__Log = Log or []

            self.Step4_Log.append("[Juansha::1] 完成")

        except Exception as e:
            self.Juansha_1__ToolBrep = None
            self.Juansha_1__Log = ["错误: {}".format(e)]
            self.Step4_Log.append("[ERROR] Juansha::1 出错: {}".format(e))
            return self

        # ==================================================
        # Step4C：GeoAligner::2（对齐卷杀刀具）
        # Geo         = Juansha ToolBrep
        # SourcePlane  = Juansha LengthFacePlane
        # TargetPlane  = PlaneFromLists ResultPlane
        # ==================================================
        try:
            def _get_in_or_db(name, default):
                v_in = getattr(self, name + "_in", None)
                if v_in is not None:
                    return v_in
                return self.all_get(name, default)

            rotate_deg = _get_in_or_db("GeoAligner_2__RotateDeg", 0.0)
            flip_x = _get_in_or_db("GeoAligner_2__FlipX", False)
            flip_y = _get_in_or_db("GeoAligner_2__FlipY", False)
            flip_z = _get_in_or_db("GeoAligner_2__FlipZ", False)
            move_x = _get_in_or_db("GeoAligner_2__MoveX", 0.0)
            move_y = _get_in_or_db("GeoAligner_2__MoveY", 0.0)
            move_z = _get_in_or_db("GeoAligner_2__MoveZ", 0.0)

            so, to, xf, mg, errs = geoaligner_broadcast(
                self.Juansha_1__ToolBrep,
                self.Juansha_1__LengthFacePlane,
                self.PlaneFromLists_1__ResultPlane,
                rotate_deg_in=rotate_deg,
                flip_x_in=flip_x,
                flip_y_in=flip_y,
                flip_z_in=flip_z,
                move_x_in=move_x,
                move_y_in=move_y,
                move_z_in=move_z,
            )

            self.GeoAligner_2__SourceOut = so
            self.GeoAligner_2__TargetOut = to
            self.GeoAligner_2__TransformOut = xf
            self.GeoAligner_2__MovedGeo = mg

            if errs:
                for e in errs:
                    self.Step4_Log.append("[GeoAligner::2] " + str(e))
            else:
                self.Step4_Log.append("[GeoAligner::2] 完成")

        except Exception as e:
            self.GeoAligner_2__SourceOut = None
            self.GeoAligner_2__TargetOut = None
            self.GeoAligner_2__TransformOut = None
            self.GeoAligner_2__MovedGeo = None
            self.Step4_Log.append("[ERROR] GeoAligner::2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5：PlaneFromLists::2 + Juansha::2 + GeoAligner::3
    # ------------------------------------------------------
    def step5_planefromlists2_juansha2_geoaligner3(self):

        self.Step5_Log = []

        # ==================================================
        # Step5A：PlaneFromLists::2（从 SkewTimber 提取 ResultPlane）
        # OriginPoints = SkewTimber_EdgeMidPoints
        # BasePlanes   = SkewTimber_Corner0Planes
        # ==================================================
        try:
            origin_points = self.SkewTimber_EdgeMidPoints
            base_planes = self.SkewTimber_Corner0Planes

            idx_origin = self.PlaneFromLists_2__IndexOrigin_in
            if idx_origin is None:
                idx_origin = self.all_get("PlaneFromLists_2__IndexOrigin", 0)

            idx_plane = self.PlaneFromLists_2__IndexPlane_in
            if idx_plane is None:
                idx_plane = self.all_get("PlaneFromLists_2__IndexPlane", 0)

            wrap = self.PlaneFromLists_2__Wrap_in
            if wrap is None:
                wrap = self.all_get("PlaneFromLists_2__Wrap", True)
            try:
                wrap = bool(first_or_default(wrap, True))
            except Exception:
                wrap = True

            bp, op, rp, lg, errs = planefromlists_broadcast(
                origin_points,
                base_planes,
                idx_origin,
                idx_plane,
                wrap=wrap,
            )

            self.PlaneFromLists_2__BasePlane = bp
            self.PlaneFromLists_2__OriginPoint = op
            self.PlaneFromLists_2__ResultPlane = rp
            self.PlaneFromLists_2__Log = lg or []

            self.Step5_Log.append("[PlaneFromLists::2] 完成")
            if errs:
                for e in errs:
                    self.Step5_Log.append("[PlaneFromLists::2] " + str(e))

        except Exception as e:
            self.PlaneFromLists_2__BasePlane = None
            self.PlaneFromLists_2__OriginPoint = None
            self.PlaneFromLists_2__ResultPlane = None
            self.PlaneFromLists_2__Log = ["错误: {}".format(e)]
            self.Step5_Log.append("[ERROR] PlaneFromLists::2 出错: {}".format(e))
            return self

        # ==================================================
        # Step5B：Juansha::2（卷杀刀具）
        # ==================================================
        try:
            # PositionPoint：图中连接 Point 参数；若无 -> 原点
            pp = self.Juansha_2__PositionPoint_in
            if pp is None:
                pp = self.all_get("Juansha_2__PositionPoint", None)
            if pp is None:
                pp = rg.Point3d(0, 0, 0)
            elif isinstance(pp, rg.Point):
                pp = pp.Location

            # SectionPlane：未接线则默认 GH XZ（以 PositionPoint 为原点）
            sp = self.Juansha_2__SectionPlane_in
            if sp is None:
                sp = self.all_get("Juansha_2__SectionPlane", None)
            if sp is None:
                sp = gh_plane_XZ(pp)

            # 参数（输入端 > DB > 默认）
            h_raw = self.Juansha_2__HeightFen_in
            if h_raw is None:
                h_raw = self.all_get("Juansha_2__HeightFen", 10.0)

            l_raw = self.Juansha_2__LengthFen_in
            if l_raw is None:
                l_raw = self.all_get("Juansha_2__LengthFen", 80.0)

            d_raw = self.Juansha_2__DivCount_in
            if d_raw is None:
                d_raw = self.all_get("Juansha_2__DivCount", 8)

            t_raw = self.Juansha_2__ThicknessFen_in
            if t_raw is None:
                t_raw = self.all_get("Juansha_2__ThicknessFen", 6.0)

            try:
                HeightFen = float(first_or_default(h_raw, 10.0))
                LengthFen = float(first_or_default(l_raw, 80.0))
                DivCount = int(first_or_default(d_raw, 8))
                ThicknessFen = float(first_or_default(t_raw, 6.0))
            except Exception as e:
                self.Step5_Log.append("[Juansha::2] 参数转换失败: {}，使用默认值".format(e))
                HeightFen, LengthFen, DivCount, ThicknessFen = 10.0, 80.0, 8, 6.0

            builder = JuanShaToolBuilder(
                height_fen=HeightFen,
                length_fen=LengthFen,
                thickness_fen=ThicknessFen,
                div_count=DivCount,
                section_plane=sp,
                position_point=pp,
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, Log = builder.build()

            self.Juansha_2__ToolBrep = ToolBrep
            self.Juansha_2__SectionEdges = SectionEdges
            self.Juansha_2__HL_Intersection = HL_Intersection
            self.Juansha_2__HeightFacePlane = HeightFacePlane
            self.Juansha_2__LengthFacePlane = LengthFacePlane
            self.Juansha_2__Log = Log or []

            self.Step5_Log.append("[Juansha::2] 完成")

        except Exception as e:
            self.Juansha_2__ToolBrep = None
            self.Juansha_2__Log = ["错误: {}".format(e)]
            self.Step5_Log.append("[ERROR] Juansha::2 出错: {}".format(e))
            return self

        # ==================================================
        # Step5C：GeoAligner::3（对齐卷杀刀具）
        # Geo         = Juansha ToolBrep
        # SourcePlane  = Juansha LengthFacePlane
        # TargetPlane  = PlaneFromLists ResultPlane
        # ==================================================
        try:
            def _get_in_or_db(name, default):
                v_in = getattr(self, name + "_in", None)
                if v_in is not None:
                    return v_in
                return self.all_get(name, default)

            rotate_deg = _get_in_or_db("GeoAligner_3__RotateDeg", 0.0)
            flip_x = _get_in_or_db("GeoAligner_3__FlipX", False)
            flip_y = _get_in_or_db("GeoAligner_3__FlipY", False)
            flip_z = _get_in_or_db("GeoAligner_3__FlipZ", False)
            move_x = _get_in_or_db("GeoAligner_3__MoveX", 0.0)
            move_y = _get_in_or_db("GeoAligner_3__MoveY", 0.0)
            move_z = _get_in_or_db("GeoAligner_3__MoveZ", 0.0)

            so, to, xf, mg, errs = geoaligner_broadcast(
                self.Juansha_2__ToolBrep,
                self.Juansha_2__LengthFacePlane,
                self.PlaneFromLists_2__ResultPlane,
                rotate_deg_in=rotate_deg,
                flip_x_in=flip_x,
                flip_y_in=flip_y,
                flip_z_in=flip_z,
                move_x_in=move_x,
                move_y_in=move_y,
                move_z_in=move_z,
            )

            self.GeoAligner_3__SourceOut = so
            self.GeoAligner_3__TargetOut = to
            self.GeoAligner_3__TransformOut = xf
            self.GeoAligner_3__MovedGeo = mg

            if errs:
                for e in errs:
                    self.Step5_Log.append("[GeoAligner::3] " + str(e))
            else:
                self.Step5_Log.append("[GeoAligner::3] 完成")

        except Exception as e:
            self.GeoAligner_3__SourceOut = None
            self.GeoAligner_3__TargetOut = None
            self.GeoAligner_3__TransformOut = None
            self.GeoAligner_3__MovedGeo = None
            self.Step5_Log.append("[ERROR] GeoAligner::3 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 6：PlaneFromLists::3 + GongYanB + List Item(Tree Index) + PlaneFromLists::4 + GeoAligner::4
    # ------------------------------------------------------
    def step6_planefromlists3_gongyanb_listitem_planefromlists4_geoaligner4(self):

        self.Step6_Log = []

        # 统一参数获取：输入端 > DB > default
        def _in_or_db(attr_in_name, db_key, default=None):
            v_in = getattr(self, attr_in_name, None)
            if v_in is not None:
                return v_in
            if db_key is None:
                return default
            return self.all_get(db_key, default)

        # ==================================================
        # Step6A：PlaneFromLists::3（从 SkewTimber 提取 SourcePlane 候选）
        # OriginPoints = SkewTimber_EdgeMidPoints
        # BasePlanes   = SkewTimber_Corner0Planes
        # ==================================================
        try:
            origin_points = self.SkewTimber_EdgeMidPoints
            base_planes = self.SkewTimber_Corner0Planes

            idx_origin = _in_or_db('PlaneFromLists_3__IndexOrigin_in', 'PlaneFromLists_3__IndexOrigin', 0)
            idx_plane = _in_or_db('PlaneFromLists_3__IndexPlane_in', 'PlaneFromLists_3__IndexPlane', 0)
            wrap = _in_or_db('PlaneFromLists_3__Wrap_in', 'PlaneFromLists_3__Wrap', True)
            try:
                wrap = bool(first_or_default(wrap, True))
            except Exception:
                wrap = True

            bp, op, rp, lg, errs = planefromlists_broadcast(
                origin_points,
                base_planes,
                idx_origin,
                idx_plane,
                wrap=wrap,
            )

            self.PlaneFromLists_3__BasePlane = bp
            self.PlaneFromLists_3__OriginPoint = op
            self.PlaneFromLists_3__ResultPlane = rp
            self.PlaneFromLists_3__Log = lg or []

            self.Step6_Log.append('[PlaneFromLists::3] 完成')
            if errs:
                for e in errs:
                    self.Step6_Log.append('[PlaneFromLists::3] ' + str(e))

        except Exception as e:
            self.PlaneFromLists_3__BasePlane = None
            self.PlaneFromLists_3__OriginPoint = None
            self.PlaneFromLists_3__ResultPlane = None
            self.PlaneFromLists_3__Log = ['错误: {}'.format(e)]
            self.Step6_Log.append('[ERROR] PlaneFromLists::3 出错: {}'.format(e))
            return self

        # ==================================================
        # Step6B：GongYanB（生成栱眼刀具）
        # ==================================================
        try:
            # SectionPlane：未接线则默认 GH XZ plane
            sp = _in_or_db('GongYanB__SectionPlane_in', 'GongYanB__SectionPlane', None)
            if sp is None:
                sp = gh_plane_XZ(rg.Point3d(0, 0, 0))

            # A：图中接了 Point，若无则 World Origin
            A_pt = _in_or_db('GongYanB__A_in', 'GongYanB__A', None)
            if A_pt is None:
                A_pt = rg.Point3d(0, 0, 0)
            elif isinstance(A_pt, rg.Point):
                A_pt = A_pt.Location

            # Tree_Cleaned 参数：允许 Tree/list/scalar
            RadiusFen = _in_or_db('GongYanB__RadiusFen_in', 'GongYanB__RadiusFen', 1.0)
            LengthFen = _in_or_db('GongYanB__LengthFen_in', 'GongYanB__LengthFen', 10.0)
            OffsetFen = _in_or_db('GongYanB__OffsetFen_in', 'GongYanB__OffsetFen', 0.0)
            ExtrudeFen = _in_or_db('GongYanB__ExtrudeFen_in', 'GongYanB__ExtrudeFen', None)
            if ExtrudeFen is None:
                ExtrudeFen = 1.0

            # --- GongYanB：按输入参数最大长度，进行 GH 风格广播对齐逐项计算 ---
            # 参考：GongYanB 组件代码（builder = FT_GongYanSection_Cai_B(...); 结构化解包 builder.build()）

            # 统一为序列（用于 GH 广播），然后按最大长度循环对齐
            SectionPlane_in = sp
            A_in = A_pt
            RadiusFen_in = RadiusFen
            LengthFen_in = LengthFen
            OffsetFen_in = OffsetFen
            ExtrudeFen_in = ExtrudeFen

            sp_seq = _as_seq(SectionPlane_in)
            A_seq = _as_seq(A_in)
            r_seq = _as_seq(RadiusFen_in)
            l_seq = _as_seq(LengthFen_in)
            off_seq = _as_seq(OffsetFen_in)
            ex_seq = _as_seq(ExtrudeFen_in)

            # 取最大长度（至少为 1）
            n = max(1, *(len(s) for s in [sp_seq, A_seq, r_seq, l_seq, off_seq, ex_seq] if s is not None))

            SectionFace_list = []
            OffsetFace_list = []
            Points_list = []
            OffsetPoints_list = []
            ToolBrep_list = []
            BridgePoints_list = []
            BridgeMidPoints_list = []
            BridgePlane_list = []
            Log_list = []
            TopPlaneA_list = []
            TopPlaneB_list = []

            for i in range(int(n)):
                SectionPlane = gh_broadcast_get(sp_seq, i)
                A = gh_broadcast_get(A_seq, i)
                RadiusFen_i = gh_broadcast_get(r_seq, i)
                LengthFen_i = gh_broadcast_get(l_seq, i)
                OffsetFen_i = gh_broadcast_get(off_seq, i)
                ExtrudeFen_i = gh_broadcast_get(ex_seq, i)

                builder = FT_GongYanSection_Cai_B(
                    section_plane=SectionPlane,
                    A_input=A,
                    radius_fen=RadiusFen_i,
                    length_fen=LengthFen_i,
                    offset_fen=OffsetFen_i,
                    extrude_fen=ExtrudeFen_i,
                    doc=sc.doc
                )

                (
                    SectionFace,
                    OffsetFace,
                    Points,
                    OffsetPoints,
                    ToolBrep,
                    BridgePoints,
                    BridgeMidPoints,
                    BridgePlane,
                    Log
                ) = builder.build()

                SectionFace_list.append(SectionFace)
                OffsetFace_list.append(OffsetFace)
                Points_list.append(Points)
                OffsetPoints_list.append(OffsetPoints)
                ToolBrep_list.append(ToolBrep)
                BridgePoints_list.append(BridgePoints)
                BridgeMidPoints_list.append(BridgeMidPoints)
                BridgePlane_list.append(BridgePlane)
                Log_list.append(Log)

                TopPlaneA_list.append(getattr(builder, 'TopPlaneA', None))
                TopPlaneB_list.append(getattr(builder, 'TopPlaneB', None))

            # 输出：n==1 仍输出 item；n>1 输出 list（符合“按最大长度循环对齐”语义）
            if int(n) == 1:
                self.GongYanB__SectionFace = SectionFace_list[0]
                self.GongYanB__OffsetFace = OffsetFace_list[0]
                self.GongYanB__Points = Points_list[0]
                self.GongYanB__OffsetPoints = OffsetPoints_list[0]
                self.GongYanB__ToolBrep = ToolBrep_list[0]
                self.GongYanB__BridgePoints = BridgePoints_list[0]
                self.GongYanB__BridgeMidPoints = BridgeMidPoints_list[0]
                self.GongYanB__BridgePlane = BridgePlane_list[0]
                self.GongYanB__Log = Log_list[0]
                self.GongYanB__TopPlaneA = TopPlaneA_list[0]
                self.GongYanB__TopPlaneB = TopPlaneB_list[0]
            else:
                self.GongYanB__SectionFace = SectionFace_list
                self.GongYanB__OffsetFace = OffsetFace_list
                self.GongYanB__Points = Points_list
                self.GongYanB__OffsetPoints = OffsetPoints_list
                self.GongYanB__ToolBrep = ToolBrep_list
                self.GongYanB__BridgePoints = BridgePoints_list
                self.GongYanB__BridgeMidPoints = BridgeMidPoints_list
                self.GongYanB__BridgePlane = BridgePlane_list
                self.GongYanB__Log = Log_list
                self.GongYanB__TopPlaneA = TopPlaneA_list
                self.GongYanB__TopPlaneB = TopPlaneB_list

            self.Step6_Log.append('[GongYanB] 完成（按最大长度广播对齐）')


        except Exception as e:
            self.GongYanB__ToolBrep = None
            self.GongYanB__Log = ['错误: {}'.format(e)]
            self.Step6_Log.append('[ERROR] GongYanB 出错: {}'.format(e))
            return self

        # ==================================================
        # Step6C：List Item（Index 为 Tree，从 ToolBrep 中按分支索引选 Geo）
        # ==================================================
        try:
            idx_tree = _in_or_db('GeoAligner_4__Geo_in', 'GeoAligner_4__Geo', None)

            def _listitem_tree_index(list_in, index_in_tree, wrap=False):
                """仅本步骤用：Index 为 Tree 的 GH List Item。

                - Index 为 Tree：输出为 Tree，保持同分支结构。
                - Index 为 Tree：输出为 Tree，保持同分支结构。
                - List 端若为 Tree：按分支匹配；分支缺失时按最后分支广播。
                - List 端若为「Python 嵌套 list（list of list）」：视作“分支列表”，按分支匹配。
                - List 端若为普通 list（非嵌套）：按分支复制（每个分支都用同一个 list 取值）。

                ✅ 项目特化需求：
                当 list_in = [[a,b],[c,d]] 且 index_in_tree = [0,1]（非 Tree，但为索引列表）时，
                期望输出为 [a, d]（即每个“子列表/分支”用对应索引取一个）。
                """

                def _is_list_of_lists(x):
                    if not isinstance(x, (list, tuple)):
                        return False
                    if len(x) == 0:
                        return False
                    # 至少包含一个子序列
                    for it in x:
                        if isinstance(it, (list, tuple)) or is_net_list(it):
                            return True
                    return False

                def _seq_from_maybe_net(x):
                    if x is None:
                        return []
                    if isinstance(x, (list, tuple)):
                        return list(x)
                    if is_net_list(x):
                        try:
                            return [x[i] for i in range(int(x.Count))]
                        except Exception:
                            return []
                    return [x]

                # -------- Case A：Index 不是 Tree（但可能是索引列表） --------
                if not is_tree(index_in_tree):
                    # A1) list_in 是嵌套 list：按“分支”逐一取值（用户要求的关键行为）
                    if _is_list_of_lists(list_in) and isinstance(index_in_tree, (list, tuple)):
                        branches = _seq_from_maybe_net(list_in)
                        idxs = _seq_from_maybe_net(index_in_tree)
                        out = []
                        bcnt = len(branches)
                        icnt = len(idxs)
                        if bcnt == 0:
                            return out
                        if icnt == 0:
                            # 没有 index，就退化为 None 列表
                            return [None for _ in range(bcnt)]

                        for bi in range(bcnt):
                            br = _seq_from_maybe_net(branches[bi])
                            n = len(br)
                            # GH 广播：索引列表长度不足时循环
                            raw_idx = idxs[bi % icnt]
                            try:
                                ii = int(raw_idx)
                            except Exception:
                                out.append(None)
                                continue
                            if n <= 0:
                                out.append(None)
                                continue
                            if wrap:
                                out.append(br[ii % n])
                            else:
                                out.append(br[ii] if (0 <= ii < n) else None)
                        return out

                    # A2) 其它情况：沿用既有 GH list item（对普通 list / 单 index）
                    return list_item_gh(list_in, index_in_tree, wrap=wrap)

                dt = tree_new_object()
                bc = tree_branch_count(index_in_tree)

                # 预取 list 分支
                list_is_tree = is_tree(list_in)
                list_is_branch_list = (not list_is_tree) and _is_list_of_lists(list_in)
                list_branch_count = tree_branch_count(list_in) if list_is_tree else (len(list_in) if list_is_branch_list else 0)
                list_seq = _as_seq(list_in) if (not list_is_tree and not list_is_branch_list) else None

                for bi in range(bc):
                    path = tree_get_path(index_in_tree, bi)
                    idxs = tree_get_branch(index_in_tree, bi, default_branch=[])

                    # 本分支可用的 list
                    if list_is_tree:
                        # GH 广播：bi 超界则取最后分支
                        li_bi = bi
                        if list_branch_count > 0:
                            if li_bi >= list_branch_count:
                                li_bi = list_branch_count - 1
                        lst = tree_get_branch(list_in, li_bi, default_branch=[])
                    elif list_is_branch_list:
                        li_bi = bi
                        if list_branch_count > 0 and li_bi >= list_branch_count:
                            li_bi = list_branch_count - 1
                        try:
                            lst = _seq_from_maybe_net(list_in[li_bi])
                        except Exception:
                            lst = []
                    else:
                        lst = list_seq

                    # pick
                    out_items = []
                    n = len(lst) if lst is not None else 0
                    for idx in idxs:
                        try:
                            ii = int(idx)
                        except Exception:
                            out_items.append(None)
                            continue
                        if n <= 0:
                            out_items.append(None)
                            continue
                        if wrap:
                            out_items.append(lst[ii % n])
                        else:
                            out_items.append(lst[ii] if (0 <= ii < n) else None)

                    tree_add_range(dt, path, out_items)

                return dt

            self.GeoAligner_4__Geo_Item = _listitem_tree_index(self.GongYanB__ToolBrep, idx_tree, wrap=False)
            self.Step6_Log.append('[List Item(Tree Index)] 完成')

        except Exception as e:
            self.GeoAligner_4__Geo_Item = None
            self.Step6_Log.append('[ERROR] List Item(Tree Index) 出错: {}'.format(e))
            return self

        # ==================================================
        # Step6D：PlaneFromLists::4（从 GongYanB 桥接点/桥接平面提取 TargetPlane 候选）
        # OriginPoints = GongYanB__BridgeMidPoints
        # BasePlanes   = GongYanB__BridgePlane
        # ==================================================
        try:
            origin_points = self.GongYanB__BridgeMidPoints
            base_planes = self.GongYanB__BridgePlane

            idx_origin = _in_or_db('PlaneFromLists_4__IndexOrigin_in', 'PlaneFromLists_4__IndexOrigin', 0)
            idx_plane = _in_or_db('PlaneFromLists_4__IndexPlane_in', 'PlaneFromLists_4__IndexPlane', 0)
            wrap = _in_or_db('PlaneFromLists_4__Wrap_in', 'PlaneFromLists_4__Wrap', True)
            try:
                wrap = bool(first_or_default(wrap, True))
            except Exception:
                wrap = True

            # PlaneFromLists::4 特殊广播规则：
            # - OriginPoints 为 Tree（或嵌套列表），BasePlanes 为普通列表
            # - IndexOrigin / IndexPlane 为单值
            # 计算时：
            #   IndexOrigin 从 OriginPoints 每个分支各取一次 -> 得到与分支数相同的 OriginPoint/ResultPlane
            #   IndexPlane 从 BasePlanes 只取一个值 -> 对所有分支广播
            # 输出：ResultPlane 为一个 list（长度=分支数），以便后续与其它 list 广播对齐。
            def _is_nested_list_branches(v):
                if v is None:
                    return False
                if is_tree(v):
                    return False
                if not isinstance(v, (list, tuple)) and not is_net_list(v):
                    return False
                try:
                    seq = _as_seq(v)
                    for it in seq:
                        if isinstance(it, (list, tuple)) or is_net_list(it):
                            return True
                    return False
                except Exception:
                    return False

            def _iter_origin_branches(op_in):
                # DataTree
                if is_tree(op_in):
                    bc = tree_branch_count(op_in)
                    for bi in range(bc):
                        yield tree_get_branch(op_in, bi, default_branch=[])
                    return
                # Nested list (list of sublists)
                if _is_nested_list_branches(op_in):
                    for br in _as_seq(op_in):
                        yield _as_seq(br)
                    return
                # Fallback: treat as single branch
                yield _as_seq(op_in)

            # 判断是否触发该特殊规则
            _idx_origin_is_scalar = not (is_tree(idx_origin) or isinstance(idx_origin, (list, tuple)) or is_net_list(idx_origin))
            _idx_plane_is_scalar = not (is_tree(idx_plane) or isinstance(idx_plane, (list, tuple)) or is_net_list(idx_plane))
            _origin_is_branches = is_tree(origin_points) or _is_nested_list_branches(origin_points)
            _base_is_list = (isinstance(base_planes, (list, tuple)) or is_net_list(base_planes)) and (not is_tree(base_planes))

            if _origin_is_branches and _base_is_list and _idx_origin_is_scalar and _idx_plane_is_scalar:
                bps = _as_seq(base_planes)
                bp_list, op_list, rp_list = [], [], []
                lg_all, errs = [], []
                for bi, op_branch in enumerate(_iter_origin_branches(origin_points)):
                    try:
                        builder = FTPlaneFromLists(wrap=wrap)
                        _bp, _op, _rp, _lg = builder.build_plane(op_branch, bps, idx_origin, idx_plane)
                        bp_list.append(_bp)
                        op_list.append(_op)
                        rp_list.append(_rp)
                        lg_all.extend(_lg or [])
                    except Exception as e:
                        bp_list.append(None)
                        op_list.append(None)
                        rp_list.append(None)
                        msg = 'branch {}: {}'.format(bi, e)
                        lg_all.append('错误: ' + msg)
                        errs.append(msg)
                bp, op, rp, lg = bp_list, op_list, rp_list, lg_all
            else:
                # 默认：通用 planefromlists_broadcast（Tree -> Tree）
                bp, op, rp, lg, errs = planefromlists_broadcast(
                    origin_points,
                    base_planes,
                    idx_origin,
                    idx_plane,
                    wrap=wrap,
                )

            self.PlaneFromLists_4__BasePlane = bp
            self.PlaneFromLists_4__OriginPoint = op
            self.PlaneFromLists_4__ResultPlane = rp
            self.PlaneFromLists_4__Log = lg or []

            self.Step6_Log.append('[PlaneFromLists::4] 完成')
            if errs:
                for e in errs:
                    self.Step6_Log.append('[PlaneFromLists::4] ' + str(e))

        except Exception as e:
            self.PlaneFromLists_4__BasePlane = None
            self.PlaneFromLists_4__OriginPoint = None
            self.PlaneFromLists_4__ResultPlane = None
            self.PlaneFromLists_4__Log = ['错误: {}'.format(e)]
            self.Step6_Log.append('[ERROR] PlaneFromLists::4 出错: {}'.format(e))
            return self

        # ==================================================
        # Step6E：GeoAligner::4（对齐刀具 Geo）
        # 注意：按你给的“严格连线”段落
        #   SourcePlane = PlaneFromLists::4 ResultPlane
        #   TargetPlane = PlaneFromLists::3 ResultPlane
        # ==================================================
        try:
            rotate_deg = _in_or_db('GeoAligner_4__RotateDeg_in', 'GeoAligner_4__RotateDeg', 0.0)
            flip_x = _in_or_db('GeoAligner_4__FlipX_in', 'GeoAligner_4__FlipX', False)
            flip_y = _in_or_db('GeoAligner_4__FlipY_in', 'GeoAligner_4__FlipY', False)
            flip_z = _in_or_db('GeoAligner_4__FlipZ_in', 'GeoAligner_4__FlipZ', False)
            move_x = _in_or_db('GeoAligner_4__MoveX_in', 'GeoAligner_4__MoveX', 0.0)
            move_y = _in_or_db('GeoAligner_4__MoveY_in', 'GeoAligner_4__MoveY', 0.0)
            move_z = _in_or_db('GeoAligner_4__MoveZ_in', 'GeoAligner_4__MoveZ', 0.0)

            # GeoAligner::4 特化：Geo 与 SourcePlane 一一对应；其它参数广播但不增加循环次数
            so, to, xf, mg, errs = geoaligner_broadcast_geo_sp_locked(
                self.GeoAligner_4__Geo_Item,
                self.PlaneFromLists_4__ResultPlane,
                self.PlaneFromLists_3__ResultPlane,
                rotate_deg_in=rotate_deg,
                flip_x_in=flip_x,
                flip_y_in=flip_y,
                flip_z_in=flip_z,
                move_x_in=move_x,
                move_y_in=move_y,
                move_z_in=move_z,
            )

            self.GeoAligner_4__SourceOut = so
            self.GeoAligner_4__TargetOut = to
            self.GeoAligner_4__TransformOut = xf
            self.GeoAligner_4__MovedGeo = mg

            if errs:
                for e in errs:
                    self.Step6_Log.append('[GeoAligner::4] ' + str(e))
            else:
                self.Step6_Log.append('[GeoAligner::4] 完成')

        except Exception as e:
            self.GeoAligner_4__SourceOut = None
            self.GeoAligner_4__TargetOut = None
            self.GeoAligner_4__TransformOut = None
            self.GeoAligner_4__MovedGeo = None
            self.Step6_Log.append('[ERROR] GeoAligner::4 出错: {}'.format(e))

        # ==================================================
        # Step6F：失败时尽量记录关键输入状态（用户强调）
        # ==================================================
        try:
            def _brief(x):
                try:
                    tn = type(x).__name__
                except Exception:
                    tn = str(type(x))
                return {
                    'type': tn,
                    'is_tree': bool(is_tree(x)),
                    'branch_count': tree_branch_count(x) if is_tree(x) else 0,
                    'len': len(_as_seq(x)) if (not is_tree(x)) else None,
                }

            self.Step6_Log.append('[DBG] Geo      : {}'.format(_brief(self.GeoAligner_4__Geo_Item)))
            self.Step6_Log.append('[DBG] SrcPlane : {}'.format(_brief(self.PlaneFromLists_4__ResultPlane)))
            self.Step6_Log.append('[DBG] TarPlane : {}'.format(_brief(self.PlaneFromLists_3__ResultPlane)))
            self.Step6_Log.append('[DBG] RotateDeg: {}'.format(_brief(_in_or_db('GeoAligner_4__RotateDeg_in', 'GeoAligner_4__RotateDeg', 0.0))))
            self.Step6_Log.append('[DBG] MoveX    : {}'.format(_brief(_in_or_db('GeoAligner_4__MoveX_in', 'GeoAligner_4__MoveX', 0.0))))
        except Exception:
            pass

        return self

    # ------------------------------------------------------
    # Step 7：TimberBlock::2 + List Item ×2 + Plane Origin + GeoAligner::5
    # ------------------------------------------------------
    def step7_timberblock2_geoaligner5(self):

        self.Step7_Log = []

        # -----------------
        # TimberBlock::2 输入参数（输入端 > DB > 默认）
        # -----------------
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0, 0, 0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location

        ref_plane = self.reference_plane
        if ref_plane is None:
            ref_plane = gh_plane_XZ(bp)

        length_raw = self.TimberBlock_2__length_fen_in
        if length_raw is None:
            length_raw = self.all_get('TimberBlock_2__length_fen', 32.0)
        width_raw = self.TimberBlock_2__width_fen_in
        if width_raw is None:
            width_raw = self.all_get('TimberBlock_2__width_fen', 32.0)
        height_raw = self.TimberBlock_2__height_fen_in
        if height_raw is None:
            height_raw = self.all_get('TimberBlock_2__height_fen', 20.0)

        def _build_one(lf, wf, hf):
            return build_timber_block_uniform(
                float(lf),
                float(wf),
                float(hf),
                bp,
                ref_plane,
            )

        # -----------------
        # TimberBlock::2 广播 / Tree
        # -----------------
        try:
            any_tree = any(is_tree(v) for v in [length_raw, width_raw, height_raw])

            # 输出容器（与输入结构对齐：非 Tree -> list；Tree -> DataTree）
            if any_tree:
                dt_geo = tree_new_object()
                dt_face_planes = tree_new_object()
                dt_faces = tree_new_object()
                dt_points = tree_new_object()
                dt_edges = tree_new_object()
                dt_center_pt = tree_new_object()
                dt_center_axes = tree_new_object()
                dt_edge_midpts = tree_new_object()
                dt_corner0 = tree_new_object()
                dt_local_axes = tree_new_object()
                dt_axis_x = tree_new_object()
                dt_axis_y = tree_new_object()
                dt_axis_z = tree_new_object()
                dt_face_tags = tree_new_object()
                dt_edge_tags = tree_new_object()
                dt_corner_dirs = tree_new_object()
                dt_logs = tree_new_object()

                # 以“分支数最多的 Tree 输入”为驱动
                tree_inputs = [v for v in [length_raw, width_raw, height_raw] if is_tree(v)]
                driver = tree_inputs[0] if tree_inputs else None
                bc = tree_branch_count(driver) if driver is not None else 0

                for bi in range(bc):
                    path = tree_get_path(driver, bi)
                    l_br = tree_get_branch(length_raw, bi, default_branch=[length_raw]) if is_tree(length_raw) else _as_seq(length_raw)
                    w_br = tree_get_branch(width_raw, bi, default_branch=[width_raw]) if is_tree(width_raw) else _as_seq(width_raw)
                    h_br = tree_get_branch(height_raw, bi, default_branch=[height_raw]) if is_tree(height_raw) else _as_seq(height_raw)

                    l_seq = _as_seq(l_br)
                    w_seq = _as_seq(w_br)
                    h_seq = _as_seq(h_br)
                    n = max(len(l_seq), len(w_seq), len(h_seq), 1)

                    out_geo = []
                    out_face_planes = []
                    out_faces = []
                    out_points = []
                    out_edges = []
                    out_center_pt = []
                    out_center_axes = []
                    out_edge_midpts = []
                    out_corner0 = []
                    out_local_axes = []
                    out_axis_x = []
                    out_axis_y = []
                    out_axis_z = []
                    out_face_tags = []
                    out_edge_tags = []
                    out_corner_dirs = []
                    out_logs = []

                    for i in range(n):
                        lf = gh_broadcast_get(l_seq, i)
                        wf = gh_broadcast_get(w_seq, i)
                        hf = gh_broadcast_get(h_seq, i)
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
                        ) = _build_one(lf, wf, hf)

                        out_geo.append(timber_brep)
                        out_faces.append(faces)
                        out_points.append(points)
                        out_edges.append(edges)
                        out_center_pt.append(center_pt)
                        out_center_axes.append(center_axes)
                        out_edge_midpts.append(edge_midpts)
                        out_face_planes.append(face_planes)
                        out_corner0.append(corner0_planes)
                        out_local_axes.append(local_axes_plane)
                        out_axis_x.append(axis_x)
                        out_axis_y.append(axis_y)
                        out_axis_z.append(axis_z)
                        out_face_tags.append(face_tags)
                        out_edge_tags.append(edge_tags)
                        out_corner_dirs.append(corner0_dirs)
                        out_logs.append(log_lines)

                    tree_add_range(dt_geo, path, out_geo)
                    tree_add_range(dt_faces, path, out_faces)
                    tree_add_range(dt_points, path, out_points)
                    tree_add_range(dt_edges, path, out_edges)
                    tree_add_range(dt_center_pt, path, out_center_pt)
                    tree_add_range(dt_center_axes, path, out_center_axes)
                    tree_add_range(dt_edge_midpts, path, out_edge_midpts)
                    tree_add_range(dt_face_planes, path, out_face_planes)
                    tree_add_range(dt_corner0, path, out_corner0)
                    tree_add_range(dt_local_axes, path, out_local_axes)
                    tree_add_range(dt_axis_x, path, out_axis_x)
                    tree_add_range(dt_axis_y, path, out_axis_y)
                    tree_add_range(dt_axis_z, path, out_axis_z)
                    tree_add_range(dt_face_tags, path, out_face_tags)
                    tree_add_range(dt_edge_tags, path, out_edge_tags)
                    tree_add_range(dt_corner_dirs, path, out_corner_dirs)
                    tree_add_range(dt_logs, path, out_logs)

                self.TimberBlock_2__TimberBrep = dt_geo
                self.TimberBlock_2__FaceList = dt_faces
                self.TimberBlock_2__PointList = dt_points
                self.TimberBlock_2__EdgeList = dt_edges
                self.TimberBlock_2__CenterPoint = dt_center_pt
                self.TimberBlock_2__CenterAxisLines = dt_center_axes
                self.TimberBlock_2__EdgeMidPoints = dt_edge_midpts
                self.TimberBlock_2__FacePlaneList = dt_face_planes
                self.TimberBlock_2__Corner0Planes = dt_corner0
                self.TimberBlock_2__LocalAxesPlane = dt_local_axes
                self.TimberBlock_2__AxisX = dt_axis_x
                self.TimberBlock_2__AxisY = dt_axis_y
                self.TimberBlock_2__AxisZ = dt_axis_z
                self.TimberBlock_2__FaceDirTags = dt_face_tags
                self.TimberBlock_2__EdgeDirTags = dt_edge_tags
                self.TimberBlock_2__Corner0EdgeDirs = dt_corner_dirs
                self.TimberBlock_2__Log = dt_logs

            else:
                l_seq = _as_seq(length_raw)
                w_seq = _as_seq(width_raw)
                h_seq = _as_seq(height_raw)
                n = max(len(l_seq), len(w_seq), len(h_seq), 1)

                out_geo = []
                out_faces = []
                out_points = []
                out_edges = []
                out_center_pt = []
                out_center_axes = []
                out_edge_midpts = []
                out_face_planes = []
                out_corner0 = []
                out_local_axes = []
                out_axis_x = []
                out_axis_y = []
                out_axis_z = []
                out_face_tags = []
                out_edge_tags = []
                out_corner_dirs = []
                out_logs = []

                for i in range(n):
                    lf = gh_broadcast_get(l_seq, i)
                    wf = gh_broadcast_get(w_seq, i)
                    hf = gh_broadcast_get(h_seq, i)
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
                    ) = _build_one(lf, wf, hf)

                    out_geo.append(timber_brep)
                    out_faces.append(faces)
                    out_points.append(points)
                    out_edges.append(edges)
                    out_center_pt.append(center_pt)
                    out_center_axes.append(center_axes)
                    out_edge_midpts.append(edge_midpts)
                    out_face_planes.append(face_planes)
                    out_corner0.append(corner0_planes)
                    out_local_axes.append(local_axes_plane)
                    out_axis_x.append(axis_x)
                    out_axis_y.append(axis_y)
                    out_axis_z.append(axis_z)
                    out_face_tags.append(face_tags)
                    out_edge_tags.append(edge_tags)
                    out_corner_dirs.append(corner0_dirs)
                    out_logs.append(log_lines)

                # 输出与 Step3 一致：若 n==1，直接输出 item；否则输出 list
                if n == 1:
                    self.TimberBlock_2__TimberBrep = out_geo[0]
                    self.TimberBlock_2__FaceList = out_faces[0]
                    self.TimberBlock_2__PointList = out_points[0]
                    self.TimberBlock_2__EdgeList = out_edges[0]
                    self.TimberBlock_2__CenterPoint = out_center_pt[0]
                    self.TimberBlock_2__CenterAxisLines = out_center_axes[0]
                    self.TimberBlock_2__EdgeMidPoints = out_edge_midpts[0]
                    self.TimberBlock_2__FacePlaneList = out_face_planes[0]
                    self.TimberBlock_2__Corner0Planes = out_corner0[0]
                    self.TimberBlock_2__LocalAxesPlane = out_local_axes[0]
                    self.TimberBlock_2__AxisX = out_axis_x[0]
                    self.TimberBlock_2__AxisY = out_axis_y[0]
                    self.TimberBlock_2__AxisZ = out_axis_z[0]
                    self.TimberBlock_2__FaceDirTags = out_face_tags[0]
                    self.TimberBlock_2__EdgeDirTags = out_edge_tags[0]
                    self.TimberBlock_2__Corner0EdgeDirs = out_corner_dirs[0]
                    self.TimberBlock_2__Log = out_logs[0]
                else:
                    self.TimberBlock_2__TimberBrep = out_geo
                    self.TimberBlock_2__FaceList = out_faces
                    self.TimberBlock_2__PointList = out_points
                    self.TimberBlock_2__EdgeList = out_edges
                    self.TimberBlock_2__CenterPoint = out_center_pt
                    self.TimberBlock_2__CenterAxisLines = out_center_axes
                    self.TimberBlock_2__EdgeMidPoints = out_edge_midpts
                    self.TimberBlock_2__FacePlaneList = out_face_planes
                    self.TimberBlock_2__Corner0Planes = out_corner0
                    self.TimberBlock_2__LocalAxesPlane = out_local_axes
                    self.TimberBlock_2__AxisX = out_axis_x
                    self.TimberBlock_2__AxisY = out_axis_y
                    self.TimberBlock_2__AxisZ = out_axis_z
                    self.TimberBlock_2__FaceDirTags = out_face_tags
                    self.TimberBlock_2__EdgeDirTags = out_edge_tags
                    self.TimberBlock_2__Corner0EdgeDirs = out_corner_dirs
                    self.TimberBlock_2__Log = out_logs

            self.Step7_Log.append('[TimberBlock::2] 完成')

        except Exception as e:
            self.TimberBlock_2__TimberBrep = None
            self.TimberBlock_2__FacePlaneList = []
            self.TimberBlock_2__Log = ['错误: {}'.format(e)]
            self.Step7_Log.append('[ERROR] TimberBlock::2 出错: {}'.format(e))
            return self

        # -----------------
        # List Item（SourcePlane）：从 TimberBlock::2.FacePlaneList 抽取
        # -----------------
        try:
            idx_sp = self.GeoAligner_5__SourcePlane_in
            if idx_sp is None:
                idx_sp = self.all_get('GeoAligner_5__SourcePlane', 0)

            def _pick_from_faceplanelist(fpl, idx):
                # fpl 可能是：list(Plane)、list(list(Plane))、Tree(每项为 list(Plane))
                if fpl is None:
                    return None
                if is_tree(fpl):
                    dt = tree_new_object()
                    bc = tree_branch_count(fpl)
                    for bi in range(bc):
                        path = tree_get_path(fpl, bi)
                        br = tree_get_branch(fpl, bi, default_branch=[])
                        out_items = []
                        for item in br:
                            if isinstance(item, (list, tuple)) or is_net_list(item):
                                out_items.append(list_item_gh(item, idx, wrap=True))
                            else:
                                # 若直接是 Plane list（极端情况），退化为 list_item_gh
                                out_items.append(list_item_gh(br, idx, wrap=True))
                                break
                        tree_add_range(dt, path, out_items)
                    return dt

                if isinstance(fpl, (list, tuple)) or is_net_list(fpl):
                    seq = _as_seq(fpl)
                    # 若是 list(list(Plane))：逐项取
                    if len(seq) > 0 and (isinstance(seq[0], (list, tuple)) or is_net_list(seq[0])):
                        return [list_item_gh(sub, idx, wrap=True) for sub in seq]
                    # list(Plane)
                    return list_item_gh(seq, idx, wrap=True)

                return None

            self.GeoAligner_5__SourcePlane_Item = _pick_from_faceplanelist(self.TimberBlock_2__FacePlaneList, idx_sp)
        except Exception as e:
            self.GeoAligner_5__SourcePlane_Item = None
            self.Step7_Log.append('[ERROR] List Item SourcePlane 出错: {}'.format(e))
            return self

        # -----------------
        # List Item（TargetPlane）：从 Skew_Planes 抽取 + Plane Origin
        # -----------------
        try:
            idx_tp = self.GeoAligner_5__TargetPlane_in
            if idx_tp is None:
                idx_tp = self.all_get('GeoAligner_5__TargetPlane', 0)
            self.GeoAligner_5__TargetPlane_Item = list_item_gh(self.Skew_Planes, idx_tp, wrap=True)

            origin_pt = self.Skew_Point_C
            if origin_pt is None:
                origin_pt = rg.Point3d(0, 0, 0)
            elif isinstance(origin_pt, rg.Point):
                origin_pt = origin_pt.Location

            def _reset_plane_origin(pl, o):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Origin = o
                    return p2
                except Exception:
                    return pl

            # 目标平面需要与 Geo 结构对齐（Geo 是 list/tree）
            geo_in = self.TimberBlock_2__TimberBrep
            if is_tree(geo_in):
                dt = tree_new_object()
                bc = tree_branch_count(geo_in)
                for bi in range(bc):
                    path = tree_get_path(geo_in, bi)
                    br = tree_get_branch(geo_in, bi, default_branch=[])
                    tree_add_range(dt, path, [_reset_plane_origin(self.GeoAligner_5__TargetPlane_Item, origin_pt) for _ in br])
                self.GeoAligner_5__TargetPlane_Reset = dt
            else:
                n = len(_as_seq(geo_in))
                if n <= 1:
                    self.GeoAligner_5__TargetPlane_Reset = _reset_plane_origin(self.GeoAligner_5__TargetPlane_Item, origin_pt)
                else:
                    self.GeoAligner_5__TargetPlane_Reset = [_reset_plane_origin(self.GeoAligner_5__TargetPlane_Item, origin_pt) for _ in range(n)]

        except Exception as e:
            self.GeoAligner_5__TargetPlane_Item = None
            self.GeoAligner_5__TargetPlane_Reset = None
            self.Step7_Log.append('[ERROR] TargetPlane/PlaneOrigin 出错: {}'.format(e))
            return self

        # -----------------
        # GeoAligner::5（仅 RotateDeg/MoveZ 接线，其它默认）
        # -----------------
        try:
            rotate_deg = self.GeoAligner_5__RotateDeg_in
            if rotate_deg is None:
                rotate_deg = self.all_get('GeoAligner_5__RotateDeg', 0.0)
            move_z = self.GeoAligner_5__MoveZ_in
            if move_z is None:
                move_z = self.all_get('GeoAligner_5__MoveZ', 0.0)

            so, to, xf, mg, errs = geoaligner_broadcast(
                self.TimberBlock_2__TimberBrep,
                self.GeoAligner_5__SourcePlane_Item,
                self.GeoAligner_5__TargetPlane_Reset,
                rotate_deg_in=rotate_deg,
                flip_x_in=False,
                flip_y_in=False,
                flip_z_in=False,
                move_x_in=0.0,
                move_y_in=0.0,
                move_z_in=move_z,
            )

            self.GeoAligner_5__SourceOut = so
            self.GeoAligner_5__TargetOut = to
            self.GeoAligner_5__TransformOut = xf
            self.GeoAligner_5__MovedGeo = mg

            if errs:
                for e in errs:
                    self.Step7_Log.append('[GeoAligner::5] ' + str(e))
            else:
                self.Step7_Log.append('[GeoAligner::5] 完成')

        except Exception as e:
            self.GeoAligner_5__SourceOut = None
            self.GeoAligner_5__TargetOut = None
            self.GeoAligner_5__TransformOut = None
            self.GeoAligner_5__MovedGeo = None
            self.Step7_Log.append('[ERROR] GeoAligner::5 出错: {}'.format(e))

        return self

    # ------------------------------------------------------
    # Step 8: CutTimbersByTools (SkewTimber.TimberBrep - tools from GeoAligner 1..5)
    # ------------------------------------------------------
    def step8_cuttimbersbytools(self):

        self.Step8_Log = []

        # Timbers
        timbers_in = getattr(self, 'SkewTimber_TimberBrep', None)

        # Tools: GeoAligner 1..5 MovedGeo
        tool_sources = [
            getattr(self, 'GeoAligner_1__MovedGeo', None),
            getattr(self, 'GeoAligner_2__MovedGeo', None),
            getattr(self, 'GeoAligner_3__MovedGeo', None),
            getattr(self, 'GeoAligner_4__MovedGeo', None),
            getattr(self, 'GeoAligner_5__MovedGeo', None),
        ]

        def _collect_from_tree(t):
            # Flatten all branches of a DataTree into a python list
            out = []
            try:
                bc = tree_branch_count(t)
                for bi in range(bc):
                    br = tree_get_branch(t, bi, default_branch=[])
                    out.extend(flatten_any(br))
            except Exception:
                pass
            return out

        # Merge tools as GH Merge: flatten one level, keep geometry atoms
        tools = []
        for src in tool_sources:
            if src is None:
                continue
            if is_tree(src):
                tools.extend(_collect_from_tree(src))
            else:
                tools.extend(flatten_any(src))

        # Remove None
        tools = [t for t in tools if t is not None]

        # Boolean difference helper
        def _volume(b):
            try:
                mp = rg.VolumeMassProperties.Compute(b)
                return float(mp.Volume) if mp else 0.0
            except Exception:
                return 0.0

        def _pick_main(breps):
            if not breps:
                return None
            try:
                return max(breps, key=_volume)
            except Exception:
                return breps[0]

        def _bool_diff_one(timber, tool, tol):
            try:
                # RhinoCommon expects lists
                res = rg.Brep.CreateBooleanDifference([timber], [tool], tol)
                if res and len(res) > 0:
                    return _pick_main(list(res))
                return None
            except Exception:
                try:
                    res = rg.Brep.CreateBooleanDifference(timber, tool, tol)
                    if res and len(res) > 0:
                        return _pick_main(list(res))
                except Exception:
                    pass
                return None

        # Tolerance
        try:
            tol = float(getattr(sc.doc, 'ModelAbsoluteTolerance', 0.01)) if sc.doc else 0.01
        except Exception:
            tol = 0.01

        # Cut timbers
        cut_out = []
        fail_out = []

        def _cut_sequence(timber):
            cur = timber
            for tool in tools:
                if cur is None:
                    break
                if tool is None:
                    continue
                nxt = _bool_diff_one(cur, tool, tol)
                if nxt is None:
                    # if boolean fails, keep current and record
                    self.Step8_Log.append('[WARN] BooleanDifference failed for one tool; keep current timber')
                    continue
                cur = nxt
            return cur

        if is_tree(timbers_in):
            dt_cut = tree_new_object()
            dt_fail = tree_new_object()
            bc = tree_branch_count(timbers_in)
            for bi in range(bc):
                path = tree_get_path(timbers_in, bi)
                br = tree_get_branch(timbers_in, bi, default_branch=[])
                br_cut = []
                br_fail = []
                for t in flatten_any(br):
                    if t is None:
                        continue
                    ct = _cut_sequence(t)
                    if ct is None:
                        br_fail.append(t)
                    else:
                        br_cut.append(ct)
                tree_add_range(dt_cut, path, br_cut)
                tree_add_range(dt_fail, path, br_fail)
            self.CutTimbers = dt_cut
            self.FailTimbers = dt_fail
        else:
            for t in flatten_any(timbers_in):
                if t is None:
                    continue
                ct = _cut_sequence(t)
                if ct is None:
                    fail_out.append(t)
                else:
                    cut_out.append(ct)
            # If original input is a single Brep, output single Brep; else list
            if isinstance(timbers_in, rg.Brep):
                self.CutTimbers = cut_out[0] if cut_out else None
                self.FailTimbers = fail_out
            else:
                self.CutTimbers = cut_out
                self.FailTimbers = fail_out

        self.Step8_Log.append('[CutTimbersByTools] tools=%d' % (len(tools),))
        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------
    def run(self):

        # Step 1：数据库
        self.step1_read_db()

        # 若 All 为空，可以提前返回
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：SkewTimber
        self.step2_skew_timber()

        # Step 3：TimberBlock::1 + GeoAligner::1
        self.step3_timberblock_geoaligner()

        # Step 4：PlaneFromLists::1 + Juansha::1 + GeoAligner::2
        self.step4_planefromlists_juansha_geoaligner()

        # Step 5：PlaneFromLists::2 + Juansha::2 + GeoAligner::3
        self.step5_planefromlists2_juansha2_geoaligner3()

        # Step 6：PlaneFromLists::3 + GongYanB + List Item(Tree Index) + PlaneFromLists::4 + GeoAligner::4
        self.step6_planefromlists3_gongyanb_listitem_planefromlists4_geoaligner4()

        # Step 7：TimberBlock::2 + GeoAligner::5
        self.step7_timberblock2_geoaligner5()

        # Step 8：CutTimbersByTools
        self.step8_cuttimbersbytools()

        return self


# ==============================================================
# GH Python 组件输出绑定区（developer-friendly）
# ==============================================================

if __name__ == "__main__":

    # ---- 安全取 GH 输入（避免未连线时报 NameError）----
    _g = globals()
    reference_plane_in = _g.get('reference_plane', None)

    TimberBlock_1__length_fen_in = _g.get('TimberBlock_1__length_fen', None)
    TimberBlock_1__width_fen_in  = _g.get('TimberBlock_1__width_fen', None)
    TimberBlock_1__height_fen_in = _g.get('TimberBlock_1__height_fen', None)

    GeoAligner_1__SourcePlane_in = _g.get('GeoAligner_1__SourcePlane', None)
    GeoAligner_1__TargetPlane_in = _g.get('GeoAligner_1__TargetPlane', None)
    GeoAligner_1__RotateDeg_in   = _g.get('GeoAligner_1__RotateDeg', None)
    GeoAligner_1__FlipX_in       = _g.get('GeoAligner_1__FlipX', None)
    GeoAligner_1__FlipY_in       = _g.get('GeoAligner_1__FlipY', None)
    GeoAligner_1__FlipZ_in       = _g.get('GeoAligner_1__FlipZ', None)
    GeoAligner_1__MoveX_in       = _g.get('GeoAligner_1__MoveX', None)
    GeoAligner_1__MoveY_in       = _g.get('GeoAligner_1__MoveY', None)
    GeoAligner_1__MoveZ_in       = _g.get('GeoAligner_1__MoveZ', None)

    # ---- Step4 输入 ----
    PlaneFromLists_1__IndexOrigin_in = _g.get('PlaneFromLists_1__IndexOrigin', None)
    PlaneFromLists_1__IndexPlane_in  = _g.get('PlaneFromLists_1__IndexPlane', None)
    PlaneFromLists_1__Wrap_in        = _g.get('PlaneFromLists_1__Wrap', None)

    Juansha_1__HeightFen_in     = _g.get('Juansha_1__HeightFen', None)
    Juansha_1__LengthFen_in     = _g.get('Juansha_1__LengthFen', None)
    Juansha_1__DivCount_in      = _g.get('Juansha_1__DivCount', None)
    Juansha_1__ThicknessFen_in  = _g.get('Juansha_1__ThicknessFen', None)
    Juansha_1__SectionPlane_in  = _g.get('Juansha_1__SectionPlane', None)
    Juansha_1__PositionPoint_in = _g.get('Juansha_1__PositionPoint', None)

    GeoAligner_2__RotateDeg_in = _g.get('GeoAligner_2__RotateDeg', None)
    GeoAligner_2__FlipX_in     = _g.get('GeoAligner_2__FlipX', None)
    GeoAligner_2__FlipY_in     = _g.get('GeoAligner_2__FlipY', None)
    GeoAligner_2__FlipZ_in     = _g.get('GeoAligner_2__FlipZ', None)
    GeoAligner_2__MoveX_in     = _g.get('GeoAligner_2__MoveX', None)
    GeoAligner_2__MoveY_in     = _g.get('GeoAligner_2__MoveY', None)
    GeoAligner_2__MoveZ_in     = _g.get('GeoAligner_2__MoveZ', None)

    # ---- Step5 输入 ----
    PlaneFromLists_2__IndexOrigin_in = _g.get('PlaneFromLists_2__IndexOrigin', None)
    PlaneFromLists_2__IndexPlane_in  = _g.get('PlaneFromLists_2__IndexPlane', None)
    PlaneFromLists_2__Wrap_in        = _g.get('PlaneFromLists_2__Wrap', None)

    Juansha_2__HeightFen_in     = _g.get('Juansha_2__HeightFen', None)
    Juansha_2__LengthFen_in     = _g.get('Juansha_2__LengthFen', None)
    Juansha_2__DivCount_in      = _g.get('Juansha_2__DivCount', None)
    Juansha_2__ThicknessFen_in  = _g.get('Juansha_2__ThicknessFen', None)
    Juansha_2__SectionPlane_in  = _g.get('Juansha_2__SectionPlane', None)
    Juansha_2__PositionPoint_in = _g.get('Juansha_2__PositionPoint', None)

    GeoAligner_3__RotateDeg_in = _g.get('GeoAligner_3__RotateDeg', None)
    GeoAligner_3__FlipX_in     = _g.get('GeoAligner_3__FlipX', None)
    GeoAligner_3__FlipY_in     = _g.get('GeoAligner_3__FlipY', None)
    GeoAligner_3__FlipZ_in     = _g.get('GeoAligner_3__FlipZ', None)
    GeoAligner_3__MoveX_in     = _g.get('GeoAligner_3__MoveX', None)
    GeoAligner_3__MoveY_in     = _g.get('GeoAligner_3__MoveY', None)
    GeoAligner_3__MoveZ_in     = _g.get('GeoAligner_3__MoveZ', None)

    # ---- Step6 输入 ----
    PlaneFromLists_3__IndexOrigin_in = _g.get('PlaneFromLists_3__IndexOrigin', None)
    PlaneFromLists_3__IndexPlane_in  = _g.get('PlaneFromLists_3__IndexPlane', None)
    PlaneFromLists_3__Wrap_in        = _g.get('PlaneFromLists_3__Wrap', None)

    GongYanB__SectionPlane_in = _g.get('GongYanB__SectionPlane', None)
    GongYanB__A_in            = _g.get('GongYanB__A', None)
    GongYanB__RadiusFen_in    = _g.get('GongYanB__RadiusFen', None)
    GongYanB__LengthFen_in    = _g.get('GongYanB__LengthFen', None)
    GongYanB__OffsetFen_in    = _g.get('GongYanB__OffsetFen', None)
    GongYanB__ExtrudeFen_in   = _g.get('GongYanB__ExtrudeFen', None)

    GeoAligner_4__Geo_in      = _g.get('GeoAligner_4__Geo', None)

    PlaneFromLists_4__IndexOrigin_in = _g.get('PlaneFromLists_4__IndexOrigin', None)
    PlaneFromLists_4__IndexPlane_in  = _g.get('PlaneFromLists_4__IndexPlane', None)
    PlaneFromLists_4__Wrap_in        = _g.get('PlaneFromLists_4__Wrap', None)

    GeoAligner_4__RotateDeg_in = _g.get('GeoAligner_4__RotateDeg', None)
    GeoAligner_4__FlipX_in     = _g.get('GeoAligner_4__FlipX', None)
    GeoAligner_4__FlipY_in     = _g.get('GeoAligner_4__FlipY', None)
    GeoAligner_4__FlipZ_in     = _g.get('GeoAligner_4__FlipZ', None)
    GeoAligner_4__MoveX_in     = _g.get('GeoAligner_4__MoveX', None)
    GeoAligner_4__MoveY_in     = _g.get('GeoAligner_4__MoveY', None)
    GeoAligner_4__MoveZ_in     = _g.get('GeoAligner_4__MoveZ', None)

    # ---- Step7 输入 ----
    TimberBlock_2__length_fen_in = _g.get('TimberBlock_2__length_fen', None)
    TimberBlock_2__width_fen_in  = _g.get('TimberBlock_2__width_fen', None)
    TimberBlock_2__height_fen_in = _g.get('TimberBlock_2__height_fen', None)

    GeoAligner_5__SourcePlane_in = _g.get('GeoAligner_5__SourcePlane', None)
    GeoAligner_5__TargetPlane_in = _g.get('GeoAligner_5__TargetPlane', None)
    GeoAligner_5__RotateDeg_in   = _g.get('GeoAligner_5__RotateDeg', None)
    GeoAligner_5__MoveZ_in       = _g.get('GeoAligner_5__MoveZ', None)

    solver = LingGongInLineWXiaoGongTou_4PU_Solver(
        DBPath,
        base_point,
        reference_plane_in,
        Refresh,
        ghenv,
        TimberBlock_1__length_fen=TimberBlock_1__length_fen_in,
        TimberBlock_1__width_fen=TimberBlock_1__width_fen_in,
        TimberBlock_1__height_fen=TimberBlock_1__height_fen_in,
        GeoAligner_1__SourcePlane=GeoAligner_1__SourcePlane_in,
        GeoAligner_1__TargetPlane=GeoAligner_1__TargetPlane_in,
        GeoAligner_1__RotateDeg=GeoAligner_1__RotateDeg_in,
        GeoAligner_1__FlipX=GeoAligner_1__FlipX_in,
        GeoAligner_1__FlipY=GeoAligner_1__FlipY_in,
        GeoAligner_1__FlipZ=GeoAligner_1__FlipZ_in,
        GeoAligner_1__MoveX=GeoAligner_1__MoveX_in,
        GeoAligner_1__MoveY=GeoAligner_1__MoveY_in,
        GeoAligner_1__MoveZ=GeoAligner_1__MoveZ_in,
        PlaneFromLists_1__IndexOrigin=PlaneFromLists_1__IndexOrigin_in,
        PlaneFromLists_1__IndexPlane=PlaneFromLists_1__IndexPlane_in,
        PlaneFromLists_1__Wrap=PlaneFromLists_1__Wrap_in,
        Juansha_1__HeightFen=Juansha_1__HeightFen_in,
        Juansha_1__LengthFen=Juansha_1__LengthFen_in,
        Juansha_1__DivCount=Juansha_1__DivCount_in,
        Juansha_1__ThicknessFen=Juansha_1__ThicknessFen_in,
        Juansha_1__SectionPlane=Juansha_1__SectionPlane_in,
        Juansha_1__PositionPoint=Juansha_1__PositionPoint_in,
        GeoAligner_2__RotateDeg=GeoAligner_2__RotateDeg_in,
        GeoAligner_2__FlipX=GeoAligner_2__FlipX_in,
        GeoAligner_2__FlipY=GeoAligner_2__FlipY_in,
        GeoAligner_2__FlipZ=GeoAligner_2__FlipZ_in,
        GeoAligner_2__MoveX=GeoAligner_2__MoveX_in,
        GeoAligner_2__MoveY=GeoAligner_2__MoveY_in,
        GeoAligner_2__MoveZ=GeoAligner_2__MoveZ_in,

        PlaneFromLists_2__IndexOrigin=PlaneFromLists_2__IndexOrigin_in,
        PlaneFromLists_2__IndexPlane=PlaneFromLists_2__IndexPlane_in,
        PlaneFromLists_2__Wrap=PlaneFromLists_2__Wrap_in,
        Juansha_2__HeightFen=Juansha_2__HeightFen_in,
        Juansha_2__LengthFen=Juansha_2__LengthFen_in,
        Juansha_2__DivCount=Juansha_2__DivCount_in,
        Juansha_2__ThicknessFen=Juansha_2__ThicknessFen_in,
        Juansha_2__SectionPlane=Juansha_2__SectionPlane_in,
        Juansha_2__PositionPoint=Juansha_2__PositionPoint_in,
        GeoAligner_3__RotateDeg=GeoAligner_3__RotateDeg_in,
        GeoAligner_3__FlipX=GeoAligner_3__FlipX_in,
        GeoAligner_3__FlipY=GeoAligner_3__FlipY_in,
        GeoAligner_3__FlipZ=GeoAligner_3__FlipZ_in,
        GeoAligner_3__MoveX=GeoAligner_3__MoveX_in,
        GeoAligner_3__MoveY=GeoAligner_3__MoveY_in,
        GeoAligner_3__MoveZ=GeoAligner_3__MoveZ_in,

        # ---- Step6 输入 ----
        PlaneFromLists_3__IndexOrigin=PlaneFromLists_3__IndexOrigin_in,
        PlaneFromLists_3__IndexPlane=PlaneFromLists_3__IndexPlane_in,
        PlaneFromLists_3__Wrap=PlaneFromLists_3__Wrap_in,

        GongYanB__SectionPlane=GongYanB__SectionPlane_in,
        GongYanB__A=GongYanB__A_in,
        GongYanB__RadiusFen=GongYanB__RadiusFen_in,
        GongYanB__LengthFen=GongYanB__LengthFen_in,
        GongYanB__OffsetFen=GongYanB__OffsetFen_in,
        GongYanB__ExtrudeFen=GongYanB__ExtrudeFen_in,

        GeoAligner_4__Geo=GeoAligner_4__Geo_in,

        PlaneFromLists_4__IndexOrigin=PlaneFromLists_4__IndexOrigin_in,
        PlaneFromLists_4__IndexPlane=PlaneFromLists_4__IndexPlane_in,
        PlaneFromLists_4__Wrap=PlaneFromLists_4__Wrap_in,

        GeoAligner_4__RotateDeg=GeoAligner_4__RotateDeg_in,
        GeoAligner_4__FlipX=GeoAligner_4__FlipX_in,
        GeoAligner_4__FlipY=GeoAligner_4__FlipY_in,
        GeoAligner_4__FlipZ=GeoAligner_4__FlipZ_in,
        GeoAligner_4__MoveX=GeoAligner_4__MoveX_in,
        GeoAligner_4__MoveY=GeoAligner_4__MoveY_in,
        GeoAligner_4__MoveZ=GeoAligner_4__MoveZ_in,

        # ---- Step7 输入 ----
        TimberBlock_2__length_fen=TimberBlock_2__length_fen_in,
        TimberBlock_2__width_fen=TimberBlock_2__width_fen_in,
        TimberBlock_2__height_fen=TimberBlock_2__height_fen_in,
        GeoAligner_5__SourcePlane=GeoAligner_5__SourcePlane_in,
        GeoAligner_5__TargetPlane=GeoAligner_5__TargetPlane_in,
        GeoAligner_5__RotateDeg=GeoAligner_5__RotateDeg_in,
        GeoAligner_5__MoveZ=GeoAligner_5__MoveZ_in,
    )
    solver = solver.run()

    # --- 最终主输出（后续步骤完成后会输出真实 Cut/Fail） ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- Step1：DB ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- Step2：SkewTimber（偏轴木料）---
    SkewTimber_TimberBrep = solver.SkewTimber_TimberBrep
    SkewTimber_FaceList = solver.SkewTimber_FaceList
    SkewTimber_PointList = solver.SkewTimber_PointList
    SkewTimber_EdgeList = solver.SkewTimber_EdgeList
    SkewTimber_CenterPoint = solver.SkewTimber_CenterPoint
    SkewTimber_CenterAxisLines = solver.SkewTimber_CenterAxisLines
    SkewTimber_EdgeMidPoints = solver.SkewTimber_EdgeMidPoints
    SkewTimber_FacePlaneList = solver.SkewTimber_FacePlaneList
    SkewTimber_Corner0Planes = solver.SkewTimber_Corner0Planes
    SkewTimber_LocalAxesPlane = solver.SkewTimber_LocalAxesPlane
    SkewTimber_AxisX = solver.SkewTimber_AxisX
    SkewTimber_AxisY = solver.SkewTimber_AxisY
    SkewTimber_AxisZ = solver.SkewTimber_AxisZ
    SkewTimber_FaceDirTags = solver.SkewTimber_FaceDirTags
    SkewTimber_EdgeDirTags = solver.SkewTimber_EdgeDirTags
    SkewTimber_Corner0EdgeDirs = solver.SkewTimber_Corner0EdgeDirs
    SkewTimber_Log = solver.SkewTimber_Log

    # --- Step2：Skew 专属输出 ---
    Skew_A = solver.Skew_A
    Skew_Point_B = solver.Skew_Point_B
    Skew_Point_C = solver.Skew_Point_C
    Skew_Planes = solver.Skew_Planes
    Skew_ExtraPoints_GF_EH = solver.Skew_ExtraPoints_GF_EH

    # --- Step3：TimberBlock::1 ---
    TimberBlock_1__TimberBrep = solver.TimberBlock_1__TimberBrep
    TimberBlock_1__FaceList = solver.TimberBlock_1__FaceList
    TimberBlock_1__PointList = solver.TimberBlock_1__PointList
    TimberBlock_1__EdgeList = solver.TimberBlock_1__EdgeList
    TimberBlock_1__CenterPoint = solver.TimberBlock_1__CenterPoint
    TimberBlock_1__CenterAxisLines = solver.TimberBlock_1__CenterAxisLines
    TimberBlock_1__EdgeMidPoints = solver.TimberBlock_1__EdgeMidPoints
    TimberBlock_1__FacePlaneList = solver.TimberBlock_1__FacePlaneList
    TimberBlock_1__Corner0Planes = solver.TimberBlock_1__Corner0Planes
    TimberBlock_1__LocalAxesPlane = solver.TimberBlock_1__LocalAxesPlane
    TimberBlock_1__AxisX = solver.TimberBlock_1__AxisX
    TimberBlock_1__AxisY = solver.TimberBlock_1__AxisY
    TimberBlock_1__AxisZ = solver.TimberBlock_1__AxisZ
    TimberBlock_1__FaceDirTags = solver.TimberBlock_1__FaceDirTags
    TimberBlock_1__EdgeDirTags = solver.TimberBlock_1__EdgeDirTags
    TimberBlock_1__Corner0EdgeDirs = solver.TimberBlock_1__Corner0EdgeDirs
    TimberBlock_1__Log = solver.TimberBlock_1__Log

    # --- Step3：List Item ---
    GeoAligner_1__SourcePlane_Item = solver.GeoAligner_1__SourcePlane_Item
    GeoAligner_1__TargetPlane_Item = solver.GeoAligner_1__TargetPlane_Item

    # --- Step3：GeoAligner::1 ---
    GeoAligner_1__SourceOut = solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut = solver.GeoAligner_1__TargetOut
    GeoAligner_1__MovedGeo = solver.GeoAligner_1__MovedGeo
    GeoAligner_1__TransformOut = solver.GeoAligner_1__TransformOut
    Step3_Log = solver.Step3_Log

    # --- Step4：PlaneFromLists::1 ---
    PlaneFromLists_1__BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log = solver.PlaneFromLists_1__Log

    # --- Step4：Juansha::1 ---
    Juansha_1__ToolBrep = solver.Juansha_1__ToolBrep
    Juansha_1__HL_Intersection = solver.Juansha_1__HL_Intersection
    Juansha_1__SectionEdges = solver.Juansha_1__SectionEdges
    Juansha_1__HeightFacePlane = solver.Juansha_1__HeightFacePlane
    Juansha_1__LengthFacePlane = solver.Juansha_1__LengthFacePlane
    Juansha_1__Log = solver.Juansha_1__Log

    # --- Step4：GeoAligner::2 ---
    GeoAligner_2__SourceOut = solver.GeoAligner_2__SourceOut
    GeoAligner_2__TargetOut = solver.GeoAligner_2__TargetOut
    GeoAligner_2__MovedGeo = solver.GeoAligner_2__MovedGeo
    GeoAligner_2__TransformOut = solver.GeoAligner_2__TransformOut
    Step4_Log = solver.Step4_Log

    # --- Step5：PlaneFromLists::2 ---
    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    # --- Step5：Juansha::2 ---
    Juansha_2__ToolBrep = solver.Juansha_2__ToolBrep
    Juansha_2__HL_Intersection = solver.Juansha_2__HL_Intersection
    Juansha_2__SectionEdges = solver.Juansha_2__SectionEdges
    Juansha_2__HeightFacePlane = solver.Juansha_2__HeightFacePlane
    Juansha_2__LengthFacePlane = solver.Juansha_2__LengthFacePlane
    Juansha_2__Log = solver.Juansha_2__Log

    # --- Step5：GeoAligner::3 ---
    GeoAligner_3__SourceOut = solver.GeoAligner_3__SourceOut
    GeoAligner_3__TargetOut = solver.GeoAligner_3__TargetOut
    GeoAligner_3__MovedGeo = solver.GeoAligner_3__MovedGeo
    GeoAligner_3__TransformOut = solver.GeoAligner_3__TransformOut
    Step5_Log = solver.Step5_Log

    # --- Step6：PlaneFromLists::3 ---
    PlaneFromLists_3__BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__Log = solver.PlaneFromLists_3__Log

    # --- Step6：GongYanB ---
    GongYanB__ToolBrep = solver.GongYanB__ToolBrep
    GongYanB__SectionFace = solver.GongYanB__SectionFace
    GongYanB__Points = solver.GongYanB__Points
    GongYanB__InnerPoints = solver.GongYanB__InnerPoints
    GongYanB__TopPlaneA = solver.GongYanB__TopPlaneA
    GongYanB__TopPlaneB = solver.GongYanB__TopPlaneB
    GongYanB__BridgePoints = solver.GongYanB__BridgePoints
    GongYanB__BridgeMidPoints = solver.GongYanB__BridgeMidPoints
    GongYanB__BridgePlane = solver.GongYanB__BridgePlane
    GongYanB__Log = solver.GongYanB__Log

    # --- Step6：List Item（Tree Index） ---
    GeoAligner_4__Geo_Item = solver.GeoAligner_4__Geo_Item

    # --- Step6：PlaneFromLists::4 ---
    PlaneFromLists_4__BasePlane = solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4__OriginPoint = solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4__ResultPlane = solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4__Log = solver.PlaneFromLists_4__Log

    # --- Step6：GeoAligner::4 ---
    GeoAligner_4__SourceOut = solver.GeoAligner_4__SourceOut
    GeoAligner_4__TargetOut = solver.GeoAligner_4__TargetOut
    GeoAligner_4__MovedGeo = solver.GeoAligner_4__MovedGeo
    GeoAligner_4__TransformOut = solver.GeoAligner_4__TransformOut
    Step6_Log = solver.Step6_Log

    # --- Step7：TimberBlock::2 ---
    TimberBlock_2__TimberBrep = solver.TimberBlock_2__TimberBrep
    TimberBlock_2__FaceList = solver.TimberBlock_2__FaceList
    TimberBlock_2__PointList = solver.TimberBlock_2__PointList
    TimberBlock_2__EdgeList = solver.TimberBlock_2__EdgeList
    TimberBlock_2__CenterPoint = solver.TimberBlock_2__CenterPoint
    TimberBlock_2__CenterAxisLines = solver.TimberBlock_2__CenterAxisLines
    TimberBlock_2__EdgeMidPoints = solver.TimberBlock_2__EdgeMidPoints
    TimberBlock_2__FacePlaneList = solver.TimberBlock_2__FacePlaneList
    TimberBlock_2__Corner0Planes = solver.TimberBlock_2__Corner0Planes
    TimberBlock_2__LocalAxesPlane = solver.TimberBlock_2__LocalAxesPlane
    TimberBlock_2__AxisX = solver.TimberBlock_2__AxisX
    TimberBlock_2__AxisY = solver.TimberBlock_2__AxisY
    TimberBlock_2__AxisZ = solver.TimberBlock_2__AxisZ
    TimberBlock_2__FaceDirTags = solver.TimberBlock_2__FaceDirTags
    TimberBlock_2__EdgeDirTags = solver.TimberBlock_2__EdgeDirTags
    TimberBlock_2__Corner0EdgeDirs = solver.TimberBlock_2__Corner0EdgeDirs
    TimberBlock_2__Log = solver.TimberBlock_2__Log

    # --- Step7：List Item / Plane Origin ---
    GeoAligner_5__SourcePlane_Item = solver.GeoAligner_5__SourcePlane_Item
    GeoAligner_5__TargetPlane_Item = solver.GeoAligner_5__TargetPlane_Item
    GeoAligner_5__TargetPlane_Reset = solver.GeoAligner_5__TargetPlane_Reset

    # --- Step7：GeoAligner::5 ---
    GeoAligner_5__SourceOut = solver.GeoAligner_5__SourceOut
    GeoAligner_5__TargetOut = solver.GeoAligner_5__TargetOut
    GeoAligner_5__MovedGeo = solver.GeoAligner_5__MovedGeo
    GeoAligner_5__TransformOut = solver.GeoAligner_5__TransformOut
    Step7_Log = solver.Step7_Log


# -*- coding: utf-8 -*-
"""
GuaZiGongInLineWLingGong1_4PU_Solver · Step 1 + Step 2

目标：将用于构建「瓜子栱與令栱相列一（GuaZiGongInLineWLingGong1_4PU）」的一组 GH 自定义组件，
逐步合并为单一 ghpy 组件（数据库驱动）。

本文件仅实现：
  Step 1：读取数据库（DBJsonReader）
  Step 2：原始木料构建（BuildTimberBlockUniform_SkewAxis_M）

约定：
  - 组件输入端仅包含：DBPath, base_point, Refresh
  - 其它参数均从 All / AllDict 读取，若无则使用默认值。
  - 为便于后续逐步扩展：保留“开发模式输出（developer-friendly）”的输出绑定区，
    将 Solver 成员变量逐一暴露到 ghpy 输出端（若未来出现重名，按组件名前缀区分）。
  - 输出列表若出现嵌套或 .NET List 嵌套，将递归拍平（flatten_any）。

参考：LingGongSolver.py（已完成模块）
"""

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    BuildTimberBlockUniform_SkewAxis_M,
    build_timber_block_uniform,
    FTPlaneFromLists,
    JuanShaToolBuilder,
    GeoAligner_xfm,
    FT_GongYanSectionABFEA,
    FT_GongYanSection_Cai_B,
    FT_CutTimbersByTools_GH_SolidDifference,
)

import Grasshopper.Kernel.Types as ght


# ==============================================================
# 通用工具函数（与既有 Solver 风格保持一致）
# ==============================================================

def all_to_dict(all_list):
    """All(list[tuple]) → dict。"""
    d = {}
    if not all_list:
        return d
    for it in all_list:
        if isinstance(it, tuple) and len(it) == 2:
            d[it[0]] = it[1]
    return d


def _is_dotnet_list(x):
    """粗略判断 .NET List/Collection：有 Count 且可索引。"""
    if x is None:
        return False
    # GH 常见：System.Collections.Generic.List`1[System.Object]
    if hasattr(x, "Count") and hasattr(x, "__getitem__"):
        try:
            _ = int(x.Count)
            return True
        except Exception:
            return False
    return False


def flatten_any(x):
    """递归展开 list/tuple 及 .NET List（要求10）。"""
    out = []

    def _walk(v):
        if v is None:
            return
        if _is_dotnet_list(v):
            try:
                for i in range(int(v.Count)):
                    _walk(v[i])
            except Exception:
                out.append(v)
            return
        if isinstance(v, (list, tuple)):
            for a in v:
                _walk(a)
            return
        out.append(v)

    _walk(x)
    return out


def to_py_list(x):
    """将 GH DataTree / .NET list / list 统一转为 Python list。

    - 若为 DataTree-like：返回 list[branch_list]
    - 若为 .NET list：返回 list
    - 其它：返回 [x]

    说明：这里仅做轻量转换，供本 Solver 的“Tree 分支循环 / 广播对齐”使用。
    """
    if x is None:
        return []

    # DataTree-like
    if hasattr(x, "BranchCount") and hasattr(x, "Branch"):
        out = []
        try:
            bc = int(x.BranchCount)
            for bi in range(bc):
                br = x.Branch(bi)
                if br is None:
                    out.append([])
                    continue
                if hasattr(br, "Count"):
                    out.append([br[j] for j in range(int(br.Count))])
                else:
                    out.append(list(br))
            return out
        except Exception:
            return []

    if _is_dotnet_list(x):
        try:
            return [x[i] for i in range(int(x.Count))]
        except Exception:
            return []

    if isinstance(x, (list, tuple)):
        return list(x)

    return [x]


def _get_comp_param(all_dict, comp_name, field, input_val=None, default=None):
    """按优先级取值：输入端 > AllDict(comp__field) > AllDict[comp][field] > default。"""
    if input_val is not None:
        return input_val

    # 1) 双下划线扁平键（兼容两种命名：
    #    - "PlaneFromLists::1__IndexOrigin"（理想）
    #    - "PlaneFromLists_1__IndexOrigin"（常见：把 '::' 替换为 '_'）
    if all_dict:
        k1 = "{}__{}".format(comp_name, field)
        if k1 in all_dict:
            return all_dict.get(k1)

        comp_flat = str(comp_name).replace("::", "_")
        k2 = "{}__{}".format(comp_flat, field)
        if k2 in all_dict:
            return all_dict.get(k2)

    # 2) 组件 dict 形式
    d = all_dict.get(comp_name) if all_dict else None
    if isinstance(d, dict) and field in d:
        return d.get(field)

    # 3) 组件 dict 形式（同样兼容 comp_name 扁平化键）
    if all_dict:
        d2 = all_dict.get(str(comp_name).replace("::", "_"))
        if isinstance(d2, dict) and field in d2:
            return d2.get(field)

    return default


def _as_list(x):
    """标量→[标量]，list/tuple/.NET list→list，None→[]。"""
    if x is None:
        return []
    if _is_dotnet_list(x):
        try:
            return [x[i] for i in range(int(x.Count))]
        except Exception:
            return [x]
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _broadcast_pair(a_list, b_list):
    """GH 风格广播：短列表循环补齐到长列表长度。"""
    a = _as_list(a_list)
    b = _as_list(b_list)
    if not a and not b:
        return [], []
    if not a:
        a = [None]
    if not b:
        b = [None]
    n = max(len(a), len(b))
    aa = [a[i % len(a)] for i in range(n)]
    bb = [b[i % len(b)] for i in range(n)]
    return aa, bb


def _broadcast_multi(*seqs):
    """GH 风格广播：将多个序列广播到最大长度，短序列循环补齐。"""
    lists = [_as_list(s) for s in seqs]
    # 若全部为空
    if all((not l) for l in lists):
        return [[] for _ in lists]
    # 空序列按 [None]
    lists = [l if l else [None] for l in lists]
    n = max(len(l) for l in lists)
    out = []
    for l in lists:
        out.append([l[i % len(l)] for i in range(n)])
    return out


def _get_any_key(all_dict, keys, default=None):
    """从 AllDict 里按多个 key 依次尝试取值。"""
    if not all_dict:
        return default
    for k in keys:
        if k in all_dict:
            return all_dict.get(k)
    return default


def _safe_index(seq, idx, wrap=True):
    """安全索引：支持 wrap；idx 非法则返回 None。"""
    if seq is None:
        return None
    s = _as_list(seq)
    if not s:
        return None
    try:
        i = int(idx)
    except Exception:
        return None
    if wrap:
        i = i % len(s)
    if i < 0 or i >= len(s):
        return None
    return s[i]


def _is_py_tree_like(x):
    """判断是否为“Tree-like”的 Python 嵌套结构。

    说明：本 Solver 中部分上游步骤会把 GH DataTree 转换为 Python 的嵌套
    list（例如：[[p...],[p...]]）。这种情况下如果仍按“非 Tree”处理，会把
    “分支列表”误当作点对象传入 FTPlaneFromLists，导致 ResultPlane 为空。

    规则：
      - x 是 list/tuple 或 .NET list
      - 且其一层元素中存在 list/tuple 或 .NET list（即至少一层嵌套）
    """
    if x is None:
        return False
    if _is_dotnet_list(x):
        try:
            n = int(x.Count)
            if n <= 0:
                return False
            for i in range(n):
                it = x[i]
                if isinstance(it, (list, tuple)) or _is_dotnet_list(it):
                    return True
            return False
        except Exception:
            return False
    if isinstance(x, (list, tuple)):
        for it in x:
            if isinstance(it, (list, tuple)) or _is_dotnet_list(it):
                return True
        return False
    return False


def _plane_from_lists(OriginPoints, BasePlanes, IndexOrigin, IndexPlane, Wrap=True):
    """PlaneFromLists 核心逻辑（带 Tree/广播）。

    返回：BasePlane_out, OriginPoint_out, ResultPlane_out, Log_out
    其中 *_out 可能为：
      - list（非 Tree）
      - list[list]（Tree：按分支）

    ⚠️ 本工程按用户说明的“分支对位”规则：
      - IndexOrigin：作为索引，从 OriginPoints 的【每个分支】中分别取 1 个值；
      - IndexPlane ：作为索引，从 BasePlanes（整体）中取 1 个值；
      - 用取到的 BasePlane（同一个）分别对位到各分支取到的 OriginPoint 上；
      - 输出保持与 OriginPoints 相同分支数（每分支 1 个对象）。

    备注：如果 OriginPoints 不是 Tree，则回退到常规 GH 广播（IndexOrigin/IndexPlane 成对广播）。
    """
    builder = FTPlaneFromLists(wrap=bool(Wrap))

    # ------------------------------------------------------------
    # ① 优先严格复刻原 GhPython 组件写法：直接交给 FTPlaneFromLists
    #    其内部已兼容 GH DataTree / Goo / Wrap 等常见输入形态。
    #    若返回有效 ResultPlane，则直接使用该结果；否则再回退到
    #    本工程的“分支对位”规则（见下方）。
    # ------------------------------------------------------------
    try:
        _bp0, _op0, _rp0, _log0 = builder.build_plane(
            OriginPoints,
            BasePlanes,
            IndexOrigin,
            IndexPlane
        )
        if _rp0 is not None:
            return _bp0, _op0, _rp0, _log0
    except Exception:
        # 继续走后备逻辑（不在此处抛错）
        pass

    # 识别 Tree：既支持 GH DataTree，也支持“Tree 已被转为嵌套 list”的情况
    is_op_tree = (
        (hasattr(OriginPoints, "BranchCount") and hasattr(OriginPoints, "Branch"))
        or _is_py_tree_like(OriginPoints)
    )
    is_bp_tree = (
        (hasattr(BasePlanes, "BranchCount") and hasattr(BasePlanes, "Branch"))
        or _is_py_tree_like(BasePlanes)
    )

    # --------------------
    # Tree 模式：以 OriginPoints 分支为主
    # --------------------
    if is_op_tree:
        op_branches = to_py_list(OriginPoints)  # list[branch]
        bc = len(op_branches)

        # BasePlanes：按“整体列表”使用（即使输入是 Tree，也拍平成一个 list）
        if is_bp_tree:
            bp_branches = to_py_list(BasePlanes)
            baseplanes_flat = flatten_any(bp_branches)
        else:
            baseplanes_flat = _as_list(BasePlanes)

        # IndexOrigin / IndexPlane：按“分支级广播”
        idx_o_seq = _as_list(IndexOrigin)
        idx_p_seq = _as_list(IndexPlane)
        if not idx_o_seq:
            idx_o_seq = [0]
        if not idx_p_seq:
            idx_p_seq = [0]

        base_out_tree = []
        origin_out_tree = []
        result_out_tree = []
        log_tree = []

        for bi in range(bc):
            ops = op_branches[bi] if op_branches else []
            io = idx_o_seq[bi % len(idx_o_seq)]
            ip = idx_p_seq[bi % len(idx_p_seq)]

            try:
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    ops,
                    baseplanes_flat,
                    io,
                    ip
                )
            except Exception as e:
                BasePlane, OriginPoint, ResultPlane, Log = None, None, None, "PlaneFromLists error: {}".format(e)

            # 每分支 1 个值（保持 Tree 分支数）
            base_out_tree.append([BasePlane])
            origin_out_tree.append([OriginPoint])
            result_out_tree.append([ResultPlane])
            log_tree.append([Log])

        return base_out_tree, origin_out_tree, result_out_tree, log_tree

    # --------------------
    # 非 Tree：按列表广播（旧逻辑）
    # --------------------

    # 非 Tree：按列表广播
    io_b, ip_b = _broadcast_pair(IndexOrigin, IndexPlane)
    base_out = []
    origin_out = []
    result_out = []
    log_out = []

    for i, j in zip(io_b, ip_b):
        try:
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(OriginPoints, BasePlanes, i, j)
            base_out.append(BasePlane)
            origin_out.append(OriginPoint)
            result_out.append(ResultPlane)
            log_out.append(Log)
        except Exception as e:
            base_out.append(None)
            origin_out.append(None)
            result_out.append(None)
            log_out.append("PlaneFromLists error: {}".format(e))

    return base_out, origin_out, result_out, log_out


def _geo_aligner(Geo, SourcePlane, TargetPlane,
                rotate_deg=0.0, flip_x=False, flip_y=False, flip_z=False,
                move_x=0.0, move_y=0.0, move_z=0.0):
    """GeoAligner 核心逻辑（Tree/广播）。

    返回：SourceOut, TargetOut, TransformOut, MovedGeo
    其中输出可能为 list 或 list[list]（Tree）。
    """
    geo_tree = to_py_list(Geo) if (hasattr(Geo, "BranchCount") and hasattr(Geo, "Branch")) else None
    src_tree = to_py_list(SourcePlane) if (hasattr(SourcePlane, "BranchCount") and hasattr(SourcePlane, "Branch")) else None
    tgt_tree = to_py_list(TargetPlane) if (hasattr(TargetPlane, "BranchCount") and hasattr(TargetPlane, "Branch")) else None

    # 若任一为 Tree：按分支对齐
    if geo_tree is not None or src_tree is not None or tgt_tree is not None:
        geo_tree = geo_tree if geo_tree is not None else [to_py_list(Geo)]
        src_tree = src_tree if src_tree is not None else [to_py_list(SourcePlane)]

        # TargetPlane 常见：单值 / list / tree
        if tgt_tree is None:
            tgt_list = _as_list(TargetPlane)
            tgt_tree = [tgt_list] if tgt_list else [[TargetPlane]]

        bc = max(len(geo_tree), len(src_tree), len(tgt_tree), 1)

        src_out_tree = []
        tgt_out_tree = []
        xfm_out_tree = []
        moved_tree = []

        for bi in range(bc):
            g_branch = geo_tree[bi % len(geo_tree)] if geo_tree else []
            s_branch = src_tree[bi % len(src_tree)] if src_tree else []

            # TargetPlane：如果不是 tree，按列表索引映射分支（并支持广播）
            t_branch = tgt_tree[bi % len(tgt_tree)] if tgt_tree else []

            g_list = _as_list(g_branch)
            s_list = _as_list(s_branch)
            t_list = _as_list(t_branch)

            n = max(len(g_list), len(s_list), len(t_list), 1)

            src_b = []
            tgt_b = []
            xfm_b = []
            mv_b = []

            for i in range(n):
                gg = g_list[i % len(g_list)] if g_list else None
                ss = s_list[i % len(s_list)] if s_list else None
                tt = t_list[i % len(t_list)] if t_list else None

                try:
                    SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                        gg,
                        ss,
                        tt,
                        rotate_deg=rotate_deg,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                        move_x=move_x,
                        move_y=move_y,
                        move_z=move_z,
                    )
                except Exception:
                    SourceOut, TargetOut, TransformOut, MovedGeo = None, None, None, None

                src_b.append(SourceOut)
                tgt_b.append(TargetOut)
                xfm_b.append(TransformOut)
                mv_b.append(MovedGeo)

            src_out_tree.append(src_b)
            tgt_out_tree.append(tgt_b)
            xfm_out_tree.append(xfm_b)
            moved_tree.append(mv_b)

        return src_out_tree, tgt_out_tree, xfm_out_tree, moved_tree

    # 非 Tree：列表广播
    g_list = _as_list(Geo)
    s_list = _as_list(SourcePlane)
    t_list = _as_list(TargetPlane)
    n = max(len(g_list), len(s_list), len(t_list), 1)

    src_out = []
    tgt_out = []
    xfm_out = []
    moved = []

    for i in range(n):
        gg = g_list[i % len(g_list)] if g_list else None
        ss = s_list[i % len(s_list)] if s_list else None
        tt = t_list[i % len(t_list)] if t_list else None
        try:
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                gg,
                ss,
                tt,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )
        except Exception:
            SourceOut, TargetOut, TransformOut, MovedGeo = None, None, None, None

        src_out.append(SourceOut)
        tgt_out.append(TargetOut)
        xfm_out.append(TransformOut)
        moved.append(MovedGeo)

    return src_out, tgt_out, xfm_out, moved


def first_non_null(x):
    """若为 list/tree/.NET list，则取首个非空元素；否则原样返回。"""
    if x is None:
        return None

    # DataTree-like
    if hasattr(x, "BranchCount") and hasattr(x, "Branch"):
        try:
            bc = int(x.BranchCount)
            for bi in range(bc):
                br = x.Branch(bi)
                if br is None:
                    continue
                if hasattr(br, "Count"):
                    for j in range(int(br.Count)):
                        if br[j] is not None:
                            return br[j]
        except Exception:
            pass
        return None

    if _is_dotnet_list(x):
        try:
            for i in range(int(x.Count)):
                if x[i] is not None:
                    return x[i]
        except Exception:
            return x
        return None

    if isinstance(x, (list, tuple)):
        for it in x:
            if it is not None:
                return it
        return None

    return x


def make_ref_plane(mode_str, origin=None):
    """GH 参考平面（要求5）：XY / XZ / YZ；origin 默认为世界原点。"""
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

    # 默认 XZ：X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def _coerce_point3d(pt):
    """兼容 GH Point / Point3d / None。"""
    if pt is None:
        return rg.Point3d(0.0, 0.0, 0.0)
    if isinstance(pt, rg.Point3d):
        return pt
    if isinstance(pt, rg.Point):
        return pt.Location
    # 可能是 (x,y,z)
    if isinstance(pt, (list, tuple)) and len(pt) >= 3:
        try:
            return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
        except Exception:
            pass
    return rg.Point3d(0.0, 0.0, 0.0)


def _parse_gh_path(path_in):
    """将 GH Path 输入解析为 tuple[int].

    支持：
      - Grasshopper.Kernel.Data.GH_Path（具有 Indices 或 ToString）
      - "{0;1}" / "0;1" / "0,1" 等字符串
      - list/tuple[int]
      - 单个 int
    """
    if path_in is None:
        return None

    # GH_Path（尽量不依赖具体类型）
    if hasattr(path_in, "Indices"):
        try:
            inds = list(path_in.Indices)
            return tuple(int(i) for i in inds)
        except Exception:
            pass
    if hasattr(path_in, "ToString"):
        try:
            s = str(path_in.ToString())
            path_in = s
        except Exception:
            pass

    # list/tuple
    if isinstance(path_in, (list, tuple)):
        try:
            return tuple(int(i) for i in path_in)
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

    # "{0;1}" → "0;1"
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]

    # 允许用 ; , 空格 分隔
    s = s.replace(",", ";").replace(" ", ";")
    parts = [p for p in s.split(";") if p != ""]
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except Exception:
        return None


def _tree_item(tree, path_in, index_in, default=None):
    """GH Tree Item：按 Path + Index 从 DataTree 中取一个元素。

    - tree：GH DataTree 或嵌套列表
    - path_in：GH_Path / str / list[int]
    - index_in：int
    """
    if tree is None:
        return default

    # 嵌套列表：当作 Branches
    if isinstance(tree, (list, tuple)) and tree and isinstance(tree[0], (list, tuple)):
        branches = [list(b) for b in tree]
        # 嵌套列表无 Path 信息：path_in 作为 branch 索引使用
        bi = 0
        try:
            if path_in is not None:
                # 如果给的是 (n,) / int / str，可转成单数
                p = _parse_gh_path(path_in)
                if p and len(p) >= 1:
                    bi = int(p[-1])
        except Exception:
            bi = 0
        br = branches[bi % len(branches)] if branches else []
        return _safe_index(br, index_in, wrap=False) if br else default

    # DataTree
    if hasattr(tree, "BranchCount") and hasattr(tree, "Branch"):
        p = _parse_gh_path(path_in)
        # 如果没有 path，则默认取第 0 支
        if p is None:
            try:
                br = tree.Branch(0)
                return br[int(index_in)] if br is not None else default
            except Exception:
                return default

        # 遍历分支找匹配 Path
        try:
            bc = int(tree.BranchCount)
        except Exception:
            bc = 0
        for bi in range(bc):
            try:
                if hasattr(tree, "Path"):
                    ghp = tree.Path(bi)
                elif hasattr(tree, "Paths"):
                    ghp = tree.Paths[bi]
                else:
                    ghp = None
                pp = _parse_gh_path(ghp) if ghp is not None else None
                if pp == p:
                    br = tree.Branch(bi)
                    try:
                        return br[int(index_in)]
                    except Exception:
                        return default
            except Exception:
                continue
        return default

    # 一维 list：当作单支
    if isinstance(tree, (list, tuple)):
        return _safe_index(tree, index_in, wrap=False)

    return default


def _plane_origin(base_plane, origin_pt):
    """GH Plane Origin：保留 BasePlane 轴向，仅替换 Origin。"""
    if base_plane is None:
        return None
    try:
        pl = rg.Plane(base_plane)
    except Exception:
        return None
    try:
        pl.Origin = _coerce_point3d(origin_pt)
    except Exception:
        # 某些情况下 Origin 可能不可写，退化为构造新 Plane
        try:
            o = _coerce_point3d(origin_pt)
            pl = rg.Plane(o, pl.XAxis, pl.YAxis)
        except Exception:
            return None
    return pl


def _get_input_or_db(all_dict, key, input_val=None, default=None):
    """输入端优先，其次 DB，其次默认（要求8）。"""
    if input_val is not None:
        return input_val
    if all_dict and key in all_dict:
        return all_dict.get(key)
    return default


# ==============================================================
# 主 Solver 类 —— 瓜子栱與令栱相列一
# ==============================================================


class GuaZiGongInLineWLingGong1_4PU_Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # 全局日志
        self.Log = []

        # Step 1：数据库输出
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # Step 2：BuildTimberBlockUniform_SkewAxis_M 输出
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
        self.Log_BuildTimber = []

        # Skew extra outputs（按用户要求：仅这些可随 Skew_len 多值输出而新增）
        self.Skew_A = None
        self.Skew_Point_B = None
        self.Skew_Point_C = None
        self.Skew_Planes = None
        self.Skew_ExtraPoints_GF_EH = None

        # Step 3：PlaneFromLists::1 + Juansha::1 + GeoAligner::1 输出
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        self.Juansha_1__ToolBrep = None
        self.Juansha_1__HL_Intersection = None
        self.Juansha_1__SectionEdges = None
        self.Juansha_1__HeightFacePlane = None
        self.Juansha_1__LengthFacePlane = None
        self.Juansha_1__Log = []

        self.GeoAligner_1__SourceOut = None
        self.GeoAligner_1__TargetOut = None
        self.GeoAligner_1__MovedGeo = None
        self.GeoAligner_1__TransformOut = None

        # Step 4：PlaneFromLists::2 + Juansha::2 + GeoAligner::2 输出
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        self.Juansha_2__ToolBrep = None
        self.Juansha_2__HL_Intersection = None
        self.Juansha_2__SectionEdges = None
        self.Juansha_2__HeightFacePlane = None
        self.Juansha_2__LengthFacePlane = None
        self.Juansha_2__Log = []

        self.GeoAligner_2__SourceOut = None
        self.GeoAligner_2__TargetOut = None
        self.GeoAligner_2__MovedGeo = None
        self.GeoAligner_2__TransformOut = None

        # Step4 合并日志（不影响既有日志结构）
        self.Step4__Log = []

        # Step 5：BlockCutter::1 + GeoAligner::3 输出
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

        self.GeoAligner_3__SourceOut = None
        self.GeoAligner_3__TargetOut = None
        self.GeoAligner_3__MovedGeo = None
        self.GeoAligner_3__TransformOut = None
        self.GeoAligner_3__Log = []

        self.Step5__Log = []

        # Step 6：BlockCutter::2 + GeoAligner::4 输出
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

        # Step6 TargetPlane 构造子图
        self.GeoAligner_4__TargetPlane_BasePlane = None
        self.GeoAligner_4__TargetPlane_OriginPoint = None
        self.GeoAligner_4__TargetPlane = None

        # Step6 GeoAligner::4
        self.GeoAligner_4__SourceOut = None
        self.GeoAligner_4__TargetOut = None
        self.GeoAligner_4__MovedGeo = None
        self.GeoAligner_4__TransformOut = None
        self.GeoAligner_4__Log = []
        self.Step6__Log = []

        # Step 7：GongYan::1 + PlaneFromLists::3 + GeoAligner::5 输出
        self.GongYan_1__SectionFace = None
        self.GongYan_1__Points = None
        self.GongYan_1__InnerSection = None
        self.GongYan_1__InnerSectionMoved = None
        self.GongYan_1__InnerPoints = None
        self.GongYan_1__LoftFace = None
        self.GongYan_1__TopFace = None
        self.GongYan_1__ToolBrep = None
        self.GongYan_1__TopPlaneA = None
        self.GongYan_1__TopPlaneB = None
        self.GongYan_1__Log = []

        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        self.GeoAligner_5__SourceOut = None
        self.GeoAligner_5__TargetOut = None
        self.GeoAligner_5__MovedGeo = None
        self.GeoAligner_5__TransformOut = None
        self.GeoAligner_5__Log = []

        self.Step7__Log = []

        # Step 8：GongYan::2 + PlaneFromLists::4 + PlaneFromLists::5 + GeoAligner::6 输出
        self.GongYan_2__SectionFace = None
        self.GongYan_2__OffsetFace = None
        self.GongYan_2__Points = None
        self.GongYan_2__OffsetPoints = None
        # 注意：按 Step8 需求，GongYan_2__ToolBrep 应为 GongYan::2 的 ToolBrep 经 List Item 取值后的结果。
        # 为保留原始输出（developer-friendly），额外保留 Raw / ListItem 两个中间变量。
        self.GongYan_2__ToolBrep_Raw = None
        self.GongYan_2__ToolBrep_ListItem = None
        self.GongYan_2__ToolBrep = None
        self.GongYan_2__BridgePoints = None
        self.GongYan_2__BridgeMidPoints = None
        self.GongYan_2__BridgePlane = None
        self.GongYan_2__Log = []

        self.PlaneFromLists_4__OriginPoint = None
        self.PlaneFromLists_4__BasePlane = None
        self.PlaneFromLists_4__ResultPlane = None
        self.PlaneFromLists_4__Log = []

        self.PlaneFromLists_5__OriginPoint = None
        self.PlaneFromLists_5__BasePlane = None
        self.PlaneFromLists_5__ResultPlane = None
        self.PlaneFromLists_5__Log = []

        # GeoAligner::6
        self.GeoAligner_6__SourceOut = None
        self.GeoAligner_6__TargetOut = None
        self.GeoAligner_6__MovedGeo = None
        self.GeoAligner_6__MovedGeo_Tree = None
        self.GeoAligner_6__TransformOut = None
        self.GeoAligner_6__Log = []

        self.Step8__Log = []

        # Step 9：CutTimbersByTools 输出（developer-friendly 保留）
        self.CutTimbersByTools_1__CutTimbers = None
        self.CutTimbersByTools_1__FailTimbers = None
        self.CutTimbersByTools_1__Log = []
        self.Step9__Log = []

        # 最终输出（后续步骤实现后再赋值）
        self.CutTimbers = None
        self.FailTimbers = []

    # ----------------------------------------------------------
    # Step 9：CutTimbersByTools（最终切割输出）
    # ----------------------------------------------------------
    def step9_cut_timbers_by_tools(self, timbers, tools, keep_inside=None):
        step_log = []

        # tools 必须完全展平（要求：多层嵌套也要展平）
        tools_flat = flatten_any(tools)

        # KeepInside：输入端 > AllDict > 默认值
        if keep_inside is None:
            keep_inside = _get_comp_param(
                self.AllDict,
                'CutTimbersByTools',
                'KeepInside',
                default=_get_comp_param(self.AllDict, 'CutTimbersByTools::1', 'KeepInside', default=True)
            )
        try:
            keep_inside = bool(keep_inside)
        except Exception:
            keep_inside = True

        try:
            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=False)
            cut_timbers, fail_timbers, log = cutter.cut(
                timbers=timbers,
                tools=tools_flat,
                keep_inside=keep_inside,
                debug=None
            )

            self.CutTimbersByTools_1__CutTimbers = cut_timbers
            self.CutTimbersByTools_1__FailTimbers = fail_timbers
            self.CutTimbersByTools_1__Log = log

            # 绑定最终输出
            self.CutTimbers = cut_timbers
            self.FailTimbers = fail_timbers

            step_log.append('[Step9] CutTimbersByTools OK')
        except Exception as e:
            self.CutTimbersByTools_1__CutTimbers = None
            self.CutTimbersByTools_1__FailTimbers = []
            self.CutTimbersByTools_1__Log = ['CutTimbersByTools error: {}'.format(e)]
            self.CutTimbers = None
            self.FailTimbers = []
            step_log.append('[Step9] CutTimbersByTools FAILED: {}'.format(e))

        self.Step9__Log = flatten_any([self.CutTimbersByTools_1__Log, step_log])
        self.Log = flatten_any([self.Log, self.Step9__Log])
        return self

    # ----------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ----------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="GuaZiGongInLineWLingGong1_4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv,
            )
            self.Value, self.All, self.DBLog = reader.run()
            self.AllDict = all_to_dict(self.All)
            self.Log.append("[Step1] DBJsonReader OK")
        except Exception as e:
            self.Value, self.All, self.DBLog = None, None, ["DBJsonReader error: {}".format(e)]
            self.AllDict = {}
            self.Log.append("[Step1] DBJsonReader FAILED: {}".format(e))
        return self

    # ----------------------------------------------------------
    # Step 2：原始木料构建（BuildTimberBlockUniform_SkewAxis_M）
    # ----------------------------------------------------------
    def step2_build_timber(self):
        # 输入端 base_point 优先；None → 原点
        bp = _coerce_point3d(self.base_point)

        # 读取 DB 参数（注意命名规则：组件名__端口名）
        length_fen = _get_input_or_db(self.AllDict, "BuildTimberBlockUniform_SkewAxis_M__length_fen", None, 32.0)
        width_fen = _get_input_or_db(self.AllDict, "BuildTimberBlockUniform_SkewAxis_M__width_fen", None, 32.0)
        height_fen = _get_input_or_db(self.AllDict, "BuildTimberBlockUniform_SkewAxis_M__height_fen", None, 20.0)
        skew_len = _get_input_or_db(self.AllDict, "BuildTimberBlockUniform_SkewAxis_M__Skew_len", None, 20.0)

        ref_mode = self.AllDict.get("BuildTimberBlockUniform_SkewAxis_M__reference_plane", "WorldXZ")
        reference_plane = make_ref_plane(ref_mode, origin=bp)

        try:
            _obj = BuildTimberBlockUniform_SkewAxis_M(
                length_fen,
                width_fen,
                height_fen,
                bp,
                reference_plane,
                skew_len,
            )

            # TimberBrep：无论 skew_len 是否多值，主 TimberBrep 仅输出 1 个（与既有约定一致）
            self.TimberBrep = first_non_null(_obj.TimberBrep)

            # 常规输出
            self.FaceList = _obj.FaceList
            self.PointList = _obj.PointList
            self.EdgeList = _obj.EdgeList
            self.CenterPoint = _obj.CenterPoint
            self.CenterAxisLines = _obj.CenterAxisLines
            self.EdgeMidPoints = _obj.EdgeMidPoints
            self.FacePlaneList = _obj.FacePlaneList
            self.Corner0Planes = _obj.Corner0Planes
            self.LocalAxesPlane = _obj.LocalAxesPlane
            self.AxisX = _obj.AxisX
            self.AxisY = _obj.AxisY
            self.AxisZ = _obj.AxisZ
            self.FaceDirTags = _obj.FaceDirTags
            self.EdgeDirTags = _obj.EdgeDirTags
            self.Corner0EdgeDirs = _obj.Corner0EdgeDirs

            # Skew extra outputs
            self.Skew_A = getattr(_obj, "Skew_A", None)
            self.Skew_Point_B = getattr(_obj, "Skew_Point_B", None)
            self.Skew_Point_C = getattr(_obj, "Skew_Point_C", None)
            self.Skew_Planes = getattr(_obj, "Skew_Planes", None)
            self.Skew_ExtraPoints_GF_EH = getattr(_obj, "Skew_ExtraPoints_GF_EH", None)

            self.Log_BuildTimber = getattr(_obj, "Log", [])

            self.Log.append("[Step2] BuildTimberBlockUniform_SkewAxis_M OK")
        except Exception as e:
            self.TimberBrep = None
            self.Log_BuildTimber = ["BuildTimber error: {}".format(e)]
            self.Log.append("[Step2] BuildTimberBlockUniform_SkewAxis_M FAILED: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 3：PlaneFromLists::1 + Juansha::1 + GeoAligner::1
    # ----------------------------------------------------------
    def step3_plane_juansha_geoaligner_1(self):
        try:
            # ============ 1) PlaneFromLists::1 ============
            origin_points = getattr(self, 'EdgeMidPoints', None)
            base_planes = getattr(self, 'Corner0Planes', None)

            idx_origin = _get_comp_param(self.AllDict, 'PlaneFromLists::1', 'IndexOrigin', default=0)
            idx_plane = _get_comp_param(self.AllDict, 'PlaneFromLists::1', 'IndexPlane', default=0)
            wrap = _get_comp_param(self.AllDict, 'PlaneFromLists::1', 'Wrap', default=True)

            bp_out, op_out, rp_out, pfl_log = _plane_from_lists(
                origin_points,
                base_planes,
                idx_origin,
                idx_plane,
                Wrap=wrap,
            )

            self.PlaneFromLists_1__BasePlane = bp_out
            self.PlaneFromLists_1__OriginPoint = op_out
            self.PlaneFromLists_1__ResultPlane = rp_out
            self.PlaneFromLists_1__Log = flatten_any(pfl_log)

            # ============ 2) Juansha::1 ============
            # PositionPoint：优先 Solver 输入端 base_point，其次 DB PositionPoint，再默认原点
            pos_pt = self.base_point if self.base_point is not None else _get_comp_param(
                self.AllDict, 'Juansha::1', 'PositionPoint', default=(0.0, 0.0, 0.0)
            )
            pos_pt = _coerce_point3d(pos_pt)

            height_fen = _get_comp_param(self.AllDict, 'Juansha::1', 'HeightFen', default=9)
            length_fen = _get_comp_param(self.AllDict, 'Juansha::1', 'LengthFen', default=16)
            div_count = _get_comp_param(self.AllDict, 'Juansha::1', 'DivCount', default=4)
            thickness_fen = _get_comp_param(self.AllDict, 'Juansha::1', 'ThicknessFen', default=10)
            section_plane = _get_comp_param(self.AllDict, 'Juansha::1', 'SectionPlane', default=make_ref_plane('WorldXZ', origin=pos_pt))

            builder = JuanShaToolBuilder(
                height_fen=height_fen,
                length_fen=length_fen,
                thickness_fen=thickness_fen,
                div_count=div_count,
                section_plane=section_plane,
                position_point=pos_pt,
            )
            tool_brep, section_edges, hl_intersection, height_face_plane, length_face_plane, js_log = builder.build()

            self.Juansha_1__ToolBrep = tool_brep
            self.Juansha_1__SectionEdges = section_edges
            self.Juansha_1__HL_Intersection = hl_intersection
            self.Juansha_1__HeightFacePlane = height_face_plane
            self.Juansha_1__LengthFacePlane = length_face_plane
            self.Juansha_1__Log = flatten_any(js_log)

            # ============ 3) GeoAligner::1 ============
            geo = tool_brep
            source_plane = length_face_plane
            target_plane = rp_out

            rotate_deg = _get_comp_param(self.AllDict, 'GeoAligner::1', 'RotateDeg', default=0.0)
            flip_x = _get_comp_param(self.AllDict, 'GeoAligner::1', 'FlipX', default=False)
            flip_y = _get_comp_param(self.AllDict, 'GeoAligner::1', 'FlipY', default=False)
            flip_z = _get_comp_param(self.AllDict, 'GeoAligner::1', 'FlipZ', default=False)
            move_x = _get_comp_param(self.AllDict, 'GeoAligner::1', 'MoveX', default=0.0)
            move_y = _get_comp_param(self.AllDict, 'GeoAligner::1', 'MoveY', default=0.0)
            move_z = _get_comp_param(self.AllDict, 'GeoAligner::1', 'MoveZ', default=0.0)

            src_out, tgt_out, xfm_out, moved_geo = _geo_aligner(
                geo,
                source_plane,
                target_plane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            self.GeoAligner_1__SourceOut = src_out
            self.GeoAligner_1__TargetOut = tgt_out
            self.GeoAligner_1__TransformOut = xfm_out
            self.GeoAligner_1__MovedGeo = flatten_any(moved_geo)

            # 日志
            self.Log.append("[Step3] PlaneFromLists::1 + Juansha::1 + GeoAligner::1 OK")
            self.Log.append("[Step3] PlaneFromLists idx_origin={} idx_plane={} wrap={}".format(idx_origin, idx_plane, wrap))
        except Exception as e:
            self.Log.append("[Step3] FAILED: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 4：PlaneFromLists::2 + Juansha::2 + GeoAligner::2
    # ----------------------------------------------------------
    def step4_plane_from_lists_2__juansha_2__geo_aligner_2(self):
        """复刻 GH 绿色组 Step4：
        PlaneFromLists::2（从 EdgeMidPoints / FacePlaneList 取 ResultPlane）
        → Juansha::2（生成卷杀刀具）
        → GeoAligner::2（SourcePlane→TargetPlane 对齐刀具）

        约定：
          - 禁止再次读库；参数优先级：输入端（若有）> AllDict > 默认值
          - Tree：按分支循环；list：GH 广播对齐
          - 本步骤对外/存 self 的关键输出统一 flatten_any
        """
        step_log = []
        try:
            # ============ 1) PlaneFromLists::2 ============
            origin_points = getattr(self, 'EdgeMidPoints', None)
            base_planes = getattr(self, 'Corner0Planes', None)

            idx_origin = _get_comp_param(self.AllDict, 'PlaneFromLists::2', 'IndexOrigin', default=0)
            idx_plane = _get_comp_param(self.AllDict, 'PlaneFromLists::2', 'IndexPlane', default=0)
            # 组件原始代码默认 Wrap=True
            wrap = _get_comp_param(self.AllDict, 'PlaneFromLists::2', 'Wrap', default=True)

            print(idx_origin, idx_plane)

            bp_out, op_out, rp_out, pfl_log = _plane_from_lists(
                origin_points,
                base_planes,
                idx_origin,
                idx_plane,
                Wrap=wrap,
            )

            self.PlaneFromLists_2__BasePlane = bp_out
            self.PlaneFromLists_2__OriginPoint = op_out
            self.PlaneFromLists_2__ResultPlane = flatten_any(rp_out)
            self.PlaneFromLists_2__Log = flatten_any(pfl_log)

            step_log.append("PlaneFromLists::2 idx_origin={} idx_plane={} wrap={}".format(idx_origin, idx_plane, wrap))

            # ============ 2) Juansha::2 ============
            pos_pt = self.base_point if self.base_point is not None else _get_comp_param(
                self.AllDict, 'Juansha::2', 'PositionPoint', default=(0.0, 0.0, 0.0)
            )
            pos_pt = _coerce_point3d(pos_pt)

            height_fen = _get_comp_param(self.AllDict, 'Juansha::2', 'HeightFen', default=9)
            length_fen = _get_comp_param(self.AllDict, 'Juansha::2', 'LengthFen', default=16)
            div_count = _get_comp_param(self.AllDict, 'Juansha::2', 'DivCount', default=4)
            thickness_fen = _get_comp_param(self.AllDict, 'Juansha::2', 'ThicknessFen', default=10)
            section_plane = _get_comp_param(self.AllDict, 'Juansha::2', 'SectionPlane', default=make_ref_plane('WorldXZ', origin=pos_pt))

            builder = JuanShaToolBuilder(
                height_fen=height_fen,
                length_fen=length_fen,
                thickness_fen=thickness_fen,
                div_count=div_count,
                section_plane=section_plane,
                position_point=pos_pt,
            )
            tool_brep, section_edges, hl_intersection, height_face_plane, length_face_plane, js_log = builder.build()

            self.Juansha_2__ToolBrep = tool_brep
            self.Juansha_2__SectionEdges = section_edges
            self.Juansha_2__HL_Intersection = hl_intersection
            self.Juansha_2__HeightFacePlane = height_face_plane
            self.Juansha_2__LengthFacePlane = length_face_plane
            self.Juansha_2__Log = flatten_any(js_log)

            # ============ 3) GeoAligner::2 ============
            geo = tool_brep
            source_plane = length_face_plane
            target_plane = self.PlaneFromLists_2__ResultPlane

            rotate_deg = _get_comp_param(self.AllDict, 'GeoAligner::2', 'RotateDeg', default=0.0)
            flip_x = _get_comp_param(self.AllDict, 'GeoAligner::2', 'FlipX', default=False)
            flip_y = _get_comp_param(self.AllDict, 'GeoAligner::2', 'FlipY', default=False)
            flip_z = _get_comp_param(self.AllDict, 'GeoAligner::2', 'FlipZ', default=False)
            move_x = _get_comp_param(self.AllDict, 'GeoAligner::2', 'MoveX', default=0.0)
            move_y = _get_comp_param(self.AllDict, 'GeoAligner::2', 'MoveY', default=0.0)
            move_z = _get_comp_param(self.AllDict, 'GeoAligner::2', 'MoveZ', default=0.0)

            src_out, tgt_out, xfm_out, moved_geo = _geo_aligner(
                geo,
                source_plane,
                target_plane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            self.GeoAligner_2__SourceOut = src_out
            self.GeoAligner_2__TargetOut = tgt_out
            self.GeoAligner_2__TransformOut = xfm_out
            self.GeoAligner_2__MovedGeo = flatten_any(moved_geo)

            step_log.extend([
                "GeoAligner::2 rotate_deg={} flip=({}, {}, {}) move=({}, {}, {})".format(
                    rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z
                ),
            ])

            self.Step4__Log = flatten_any([
                self.PlaneFromLists_2__Log,
                self.Juansha_2__Log,
                step_log,
            ])

            self.Log.append("[Step4] PlaneFromLists::2 + Juansha::2 + GeoAligner::2 OK")
        except Exception as e:
            self.Step4__Log = flatten_any([step_log, "[Step4] FAILED: {}".format(e)])
            self.Log.append("[Step4] FAILED: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 5：BlockCutter::1 + GeoAligner::3
    # ----------------------------------------------------------
    def step5_blockcutter_1__geo_aligner_3(self):
        """复刻 GH 绿色组 Step5：

        1) BlockCutter::1
           - length_fen / width_fen / height_fen 可能为单值或列表
           - 三者按索引对齐；长度不一致则 GH 风格广播
           - 输出全部保留到 self（便于后续增减输出端）

        2) GeoAligner::3
           - Geo / SourcePlane / TargetPlane / MoveZ 均为 Tree：按分支对应循环
           - branch 内部再做 list 广播对齐逐项 align
           - 对外使用的 MovedGeo 必须 flatten_any
        """
        step_log = []
        try:
            # ============ 1) BlockCutter::1 ============
            bp = _coerce_point3d(self.base_point) if self.base_point is not None else rg.Point3d(0.0, 0.0, 0.0)

            # DB 键兼容：blockcutter_1__xxx / BlockCutter::1__xxx / BlockCutter_1__xxx
            length_fen = _get_any_key(self.AllDict, [
                "blockcutter_1__length_fen",
                "BlockCutter::1__length_fen",
                "BlockCutter_1__length_fen",
            ], default=32.0)
            width_fen = _get_any_key(self.AllDict, [
                "blockcutter_1__width_fen",
                "BlockCutter::1__width_fen",
                "BlockCutter_1__width_fen",
            ], default=32.0)
            height_fen = _get_any_key(self.AllDict, [
                "blockcutter_1__height_fen",
                "BlockCutter::1__height_fen",
                "BlockCutter_1__height_fen",
            ], default=20.0)
            ref_mode = _get_any_key(self.AllDict, [
                "blockcutter_1__reference_plane",
                "BlockCutter::1__reference_plane",
                "BlockCutter_1__reference_plane",
            ], default="WorldXZ")
            reference_plane = make_ref_plane(ref_mode, origin=bp)

            # 三端口广播对齐：调用次数 = max(len(length), len(width), len(height))
            ll, ww, hh = _broadcast_multi(length_fen, width_fen, height_fen)

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
            axis_x_list, axis_y_list, axis_z_list = [], [], []
            face_tags_list, edge_tags_list, corner0_dirs_list = [], [], []
            log_all = []

            for i in range(max(len(ll), len(ww), len(hh), 1)):
                lfi = ll[i] if ll else 32.0
                wfi = ww[i] if ww else 32.0
                hfi = hh[i] if hh else 20.0

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
                        lfi,
                        wfi,
                        hfi,
                        bp,
                        reference_plane,
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
                    log_all.append(log_lines)
                except Exception as e:
                    timber_breps.append(None)
                    faces_list.append([])
                    points_list.append([])
                    edges_list.append([])
                    center_pts.append(None)
                    center_axes_list.append([])
                    edge_midpts_list.append([])
                    face_planes_list.append([])
                    corner0_planes_list.append([])
                    local_axes_planes.append(None)
                    axis_x_list.append(None)
                    axis_y_list.append(None)
                    axis_z_list.append(None)
                    face_tags_list.append([])
                    edge_tags_list.append([])
                    corner0_dirs_list.append([])
                    log_all.append(["BlockCutter::1 error: {}".format(e)])

            # 存到 self（全部保留）
            self.BlockCutter_1__TimberBrep = timber_breps
            self.BlockCutter_1__FaceList = faces_list
            self.BlockCutter_1__PointList = points_list
            self.BlockCutter_1__EdgeList = edges_list
            self.BlockCutter_1__CenterPoint = center_pts
            self.BlockCutter_1__CenterAxisLines = center_axes_list
            self.BlockCutter_1__EdgeMidPoints = edge_midpts_list
            self.BlockCutter_1__FacePlaneList = face_planes_list
            self.BlockCutter_1__Corner0Planes = corner0_planes_list
            self.BlockCutter_1__LocalAxesPlane = local_axes_planes
            self.BlockCutter_1__AxisX = axis_x_list
            self.BlockCutter_1__AxisY = axis_y_list
            self.BlockCutter_1__AxisZ = axis_z_list
            self.BlockCutter_1__FaceDirTags = face_tags_list
            self.BlockCutter_1__EdgeDirTags = edge_tags_list
            self.BlockCutter_1__Corner0EdgeDirs = corner0_dirs_list
            self.BlockCutter_1__Log = flatten_any(log_all)

            step_log.append("BlockCutter::1 count={} (broadcasted from length/width/height)".format(len(timber_breps)))

            # ============ 2) GeoAligner::3 ============
            # Geo：按 GH ParamViewer 常见样式，每个 timber 作为一个 branch
            geo_tree = [[g] for g in _as_list(timber_breps)]

            # -------------------------------------------------
            # SourcePlane：BlockCutter::1 的 FacePlaneList 取 ListItem(index)
            #   - FacePlaneList: list[branch]（每个 timber 一支）
            #   - index: 允许为 标量 / list / Tree（每支一个 index）
            #   - 需“分别从各个分支中提取对应这一个索引值的对象”
            # -------------------------------------------------
            src_idx_in = _get_any_key(self.AllDict, [
                "GeoAligner_3__SourcePlane",
                "GeoAligner::3__SourcePlane",
                "GeoAligner::3__SourcePlaneIndex",
                "GeoAligner_3__SourcePlaneIndex",
            ], default=0)

            src_idx_tree = to_py_list(src_idx_in) if (hasattr(src_idx_in, "BranchCount") and hasattr(src_idx_in, "Branch")) else None
            if src_idx_tree is None and isinstance(src_idx_in, (list, tuple)) and src_idx_in and isinstance(src_idx_in[0], (list, tuple)):
                # 嵌套列表当作 Tree
                src_idx_tree = [list(b) for b in src_idx_in]

            src_tree = []
            fp_tree = [list(fp) if isinstance(fp, (list, tuple)) else _as_list(fp) for fp in _as_list(face_planes_list)]
            for bi in range(max(len(geo_tree), len(fp_tree), 1)):
                fp_branch = fp_tree[bi % len(fp_tree)] if fp_tree else []

                idx_branch = None
                if src_idx_tree is not None:
                    idx_branch = src_idx_tree[bi % len(src_idx_tree)] if src_idx_tree else None
                else:
                    idx_branch = src_idx_in

                # ListItem 语义：每支取“一个 index”
                idx_val = _safe_index(idx_branch, 0, wrap=True) if isinstance(idx_branch, (list, tuple)) or _is_dotnet_list(idx_branch) else idx_branch
                plane_i = _safe_index(fp_branch, idx_val, wrap=True)
                src_tree.append([plane_i])

            # -------------------------------------------------
            # TargetPlane：BuildTimberBlockUniform_SkewAxis_M 的 Skew_Planes 取 ListItem(index)
            #   - Skew_Planes: Tree 或 嵌套列表（每支一组 planes）
            #   - index: 允许为 标量 / list / Tree（每支一个 index）
            #   - 必须“分别从各个分支中提取对应这一个索引值的对象”
            # -------------------------------------------------
            tgt_idx_in = _get_any_key(self.AllDict, [
                "GeoAligner_3__TargetPlane",
                "GeoAligner::3__TargetPlane",
            ], default=0)

            tgt_idx_tree = to_py_list(tgt_idx_in) if (hasattr(tgt_idx_in, "BranchCount") and hasattr(tgt_idx_in, "Branch")) else None
            if tgt_idx_tree is None and isinstance(tgt_idx_in, (list, tuple)) and tgt_idx_in and isinstance(tgt_idx_in[0], (list, tuple)):
                tgt_idx_tree = [list(b) for b in tgt_idx_in]

            skew_tree = None
            if hasattr(self.Skew_Planes, "BranchCount") and hasattr(self.Skew_Planes, "Branch"):
                skew_tree = to_py_list(self.Skew_Planes)
            elif isinstance(self.Skew_Planes, (list, tuple)) and self.Skew_Planes and isinstance(self.Skew_Planes[0], (list, tuple)):
                skew_tree = [list(b) for b in self.Skew_Planes]
            else:
                # 标量或一维 list：当作单支
                skew_tree = [_as_list(self.Skew_Planes)]

            tgt_tree = []
            for bi in range(max(len(geo_tree), len(skew_tree), 1)):
                planes_branch = skew_tree[bi % len(skew_tree)] if skew_tree else []

                idx_branch = None
                if tgt_idx_tree is not None:
                    idx_branch = tgt_idx_tree[bi % len(tgt_idx_tree)] if tgt_idx_tree else None
                else:
                    idx_branch = tgt_idx_in

                idx_val = _safe_index(idx_branch, 0, wrap=True) if isinstance(idx_branch, (list, tuple)) or _is_dotnet_list(idx_branch) else idx_branch
                tgt_plane_val = _safe_index(planes_branch, idx_val, wrap=True)
                tgt_tree.append([tgt_plane_val])
            # MoveZ：Tree（或嵌套列表）
            # 语义：与 Geo/SourcePlane/TargetPlane 分支对应，每支一个值
            movez_in = _get_any_key(self.AllDict, [
                "GeoAligner_3__MoveZ",
                "GeoAligner::3__MoveZ",
            ], default=0.0)

            movez_tree = None
            if hasattr(movez_in, "BranchCount") and hasattr(movez_in, "Branch"):
                # 真 DataTree
                movez_tree = to_py_list(movez_in)
            elif isinstance(movez_in, (list, tuple)) and movez_in and isinstance(movez_in[0], (list, tuple)):
                # 嵌套列表：当作 Tree
                movez_tree = [list(b) for b in movez_in]
            elif isinstance(movez_in, (list, tuple)):
                # 一维列表：解释为“每支一个值”
                movez_tree = [[v] for v in list(movez_in)] if movez_in else [[0.0]]
            else:
                # 标量：所有分支同值
                movez_tree = [[movez_in]]

            # 其它输入：默认（若 DB 有则覆盖）
            rotate_deg = _get_any_key(self.AllDict, ["GeoAligner_3__RotateDeg", "GeoAligner::3__RotateDeg"], default=0.0)
            flip_x = _get_any_key(self.AllDict, ["GeoAligner_3__FlipX", "GeoAligner::3__FlipX"], default=False)
            flip_y = _get_any_key(self.AllDict, ["GeoAligner_3__FlipY", "GeoAligner::3__FlipY"], default=False)
            flip_z = _get_any_key(self.AllDict, ["GeoAligner_3__FlipZ", "GeoAligner::3__FlipZ"], default=False)
            move_x = _get_any_key(self.AllDict, ["GeoAligner_3__MoveX", "GeoAligner::3__MoveX"], default=0.0)
            move_y = _get_any_key(self.AllDict, ["GeoAligner_3__MoveY", "GeoAligner::3__MoveY"], default=0.0)

            # 按分支对应循环
            bc = max(len(geo_tree), len(src_tree), len(tgt_tree), len(movez_tree), 1)
            src_out_tree, tgt_out_tree, xfm_out_tree, moved_tree = [], [], [], []
            ga_logs = []

            # 重要：本工程此处的输入语义是“每个分支一个对象”，因此必须严格
            # 按分支 1:1 对位（不做分支内广播扩增），否则会出现 2 分支 → 4 对象的问题。
            for bi in range(bc):
                g_branch = geo_tree[bi % len(geo_tree)] if geo_tree else []
                s_branch = src_tree[bi % len(src_tree)] if src_tree else []
                t_branch = tgt_tree[bi % len(tgt_tree)] if tgt_tree else []
                mz_branch = movez_tree[bi % len(movez_tree)] if movez_tree else [0.0]

                g_list = _as_list(g_branch)
                s_list = _as_list(s_branch)
                t_list = _as_list(t_branch)
                mz_list = _as_list(mz_branch)

                # 每支只取一个（若分支里有多项，按 GH ListItem 语义取第 0 项）
                gg = _safe_index(g_list, 0, wrap=True)
                ss = _safe_index(s_list, 0, wrap=True)
                tt = _safe_index(t_list, 0, wrap=True)
                mz = _safe_index(mz_list, 0, wrap=True) if mz_list else 0.0

                try:
                    SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                        gg,
                        ss,
                        tt,
                        rotate_deg=rotate_deg,
                        flip_x=flip_x,
                        flip_y=flip_y,
                        flip_z=flip_z,
                        move_x=move_x,
                        move_y=move_y,
                        move_z=mz,
                    )
                    src_out_tree.append([SourceOut])
                    tgt_out_tree.append([TargetOut])
                    xfm_out_tree.append([TransformOut])
                    moved_tree.append([MovedGeo])
                except Exception as e:
                    src_out_tree.append([None])
                    tgt_out_tree.append([None])
                    xfm_out_tree.append([None])
                    moved_tree.append([None])
                    ga_logs.append("GeoAligner::3 error (branch {}): {}".format(bi, e))

            self.GeoAligner_3__SourceOut = src_out_tree
            self.GeoAligner_3__TargetOut = tgt_out_tree
            self.GeoAligner_3__TransformOut = xfm_out_tree
            self.GeoAligner_3__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_3__Log = flatten_any(ga_logs)

            step_log.append(
                "GeoAligner::3 src_idx={} tgt_idx={} rotate_deg={} flip=({}, {}, {}) move_xy=({}, {}) MoveZ=Tree".format(
                    src_idx_in, tgt_idx_in, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y
                )
            )

            self.Step5__Log = flatten_any([
                self.BlockCutter_1__Log,
                self.GeoAligner_3__Log,
                step_log,
            ])
            self.Log.append("[Step5] BlockCutter::1 + GeoAligner::3 OK")
        except Exception as e:
            self.Step5__Log = flatten_any([step_log, "[Step5] FAILED: {}".format(e)])
            self.Log.append("[Step5] FAILED: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 6：BlockCutter::2 + GeoAligner::4（含 TargetPlane 构造子图）
    # ----------------------------------------------------------
    def step6_blockcutter_2__geo_aligner_4(self):
        """复刻 GH 绿色组 Step6：

        1) BlockCutter::2
           - length_fen / width_fen / height_fen 可能为单值或列表
           - 三者按索引对齐；长度不一致则 GH 风格广播

        2) GeoAligner::4
           - Geo = BlockCutter_2.TimberBrep
           - SourcePlane = ListItem(BlockCutter_2.FacePlaneList, index=GeoAligner_4__SourcePlane)
           - TargetPlane = PlaneOrigin(
                 Base = TreeItem(Skew_Planes, path=GeoAligner_4__TargetPlane_base_path, index=GeoAligner_4__TargetPlane_base_index),
                 Origin = ListItem(Skew_Point_C, index=GeoAligner_4__TargetPlane_Origin)
             )
           - 其余输入端（FlipY/FlipZ/MoveX/MoveY/MoveZ）支持 AllDict，否则默认

        3) 输出
           - GeoAligner_4__MovedGeo / TransformOut 必须 flatten_any
        """
        step_log = []
        try:
            # ============ 1) BlockCutter::2 ============
            bp = _coerce_point3d(self.base_point) if self.base_point is not None else rg.Point3d(0.0, 0.0, 0.0)

            length_fen = _get_any_key(self.AllDict, [
                "blockcutter_2__length_fen",
                "BlockCutter::2__length_fen",
                "BlockCutter_2__length_fen",
            ], default=32.0)
            width_fen = _get_any_key(self.AllDict, [
                "blockcutter_2__width_fen",
                "BlockCutter::2__width_fen",
                "BlockCutter_2__width_fen",
            ], default=32.0)
            height_fen = _get_any_key(self.AllDict, [
                "blockcutter_2__height_fen",
                "BlockCutter::2__height_fen",
                "BlockCutter_2__height_fen",
            ], default=20.0)
            ref_mode = _get_any_key(self.AllDict, [
                "blockcutter_2__reference_plane",
                "BlockCutter::2__reference_plane",
                "BlockCutter_2__reference_plane",
            ], default="WorldXZ")
            reference_plane = make_ref_plane(ref_mode, origin=bp)

            ll, ww, hh = _broadcast_multi(length_fen, width_fen, height_fen)

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
            axis_x_list, axis_y_list, axis_z_list = [], [], []
            face_tags_list, edge_tags_list, corner0_dirs_list = [], [], []
            log_all = []

            n_call = max(len(ll), len(ww), len(hh), 1)
            for i in range(n_call):
                lfi = ll[i] if ll else 32.0
                wfi = ww[i] if ww else 32.0
                hfi = hh[i] if hh else 20.0
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
                        lfi,
                        wfi,
                        hfi,
                        bp,
                        reference_plane,
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
                    log_all.append(log_lines)
                except Exception as e:
                    timber_breps.append(None)
                    faces_list.append([])
                    points_list.append([])
                    edges_list.append([])
                    center_pts.append(None)
                    center_axes_list.append([])
                    edge_midpts_list.append([])
                    face_planes_list.append([])
                    corner0_planes_list.append([])
                    local_axes_planes.append(None)
                    axis_x_list.append(None)
                    axis_y_list.append(None)
                    axis_z_list.append(None)
                    face_tags_list.append([])
                    edge_tags_list.append([])
                    corner0_dirs_list.append([])
                    log_all.append(["BlockCutter::2 error: {}".format(e)])

            # 存到 self（全部保留）
            self.BlockCutter_2__TimberBrep = timber_breps
            self.BlockCutter_2__FaceList = faces_list
            self.BlockCutter_2__PointList = points_list
            self.BlockCutter_2__EdgeList = edges_list
            self.BlockCutter_2__CenterPoint = center_pts
            self.BlockCutter_2__CenterAxisLines = center_axes_list
            self.BlockCutter_2__EdgeMidPoints = edge_midpts_list
            self.BlockCutter_2__FacePlaneList = face_planes_list
            self.BlockCutter_2__Corner0Planes = corner0_planes_list
            self.BlockCutter_2__LocalAxesPlane = local_axes_planes
            self.BlockCutter_2__AxisX = axis_x_list
            self.BlockCutter_2__AxisY = axis_y_list
            self.BlockCutter_2__AxisZ = axis_z_list
            self.BlockCutter_2__FaceDirTags = face_tags_list
            self.BlockCutter_2__EdgeDirTags = edge_tags_list
            self.BlockCutter_2__Corner0EdgeDirs = corner0_dirs_list
            self.BlockCutter_2__Log = flatten_any(log_all)

            step_log.append("BlockCutter::2 count={} (broadcasted from length/width/height)".format(len(timber_breps)))

            # ============ 2) TargetPlane 构造子图 ============
            # 2.1 Tree Item：从 Skew_Planes 取 BasePlane
            base_path = _get_any_key(self.AllDict, [
                "GeoAligner_4__TargetPlane_base_path",
                "GeoAligner::4__TargetPlane_base_path",
            ], default=None)
            base_index = _get_any_key(self.AllDict, [
                "GeoAligner_4__TargetPlane_base_index",
                "GeoAligner::4__TargetPlane_base_index",
            ], default=0)

            base_path_list = _as_list(base_path) if base_path is not None else [None]
            base_index_list = _as_list(base_index) if base_index is not None else [0]
            base_path_b, base_index_b = _broadcast_pair(base_path_list, base_index_list)

            base_planes = []
            for p, idx in zip(base_path_b, base_index_b):
                base_planes.append(_tree_item(self.Skew_Planes, p, idx, default=None))
            self.GeoAligner_4__TargetPlane_BasePlane = base_planes

            # 2.2 List Item：从 Skew_Point_C 取 Origin 点
            origin_idx = _get_any_key(self.AllDict, [
                "GeoAligner_4__TargetPlane_Origin",
                "GeoAligner::4__TargetPlane_Origin",
            ], default=0)
            origin_idx_list = _as_list(origin_idx) if origin_idx is not None else [0]

            skew_ptc_list = _as_list(self.Skew_Point_C)
            origin_pts = []
            for oi in origin_idx_list:
                origin_pts.append(_safe_index(skew_ptc_list, oi, wrap=True))
            self.GeoAligner_4__TargetPlane_OriginPoint = origin_pts

            # 2.3 Plane Origin：BasePlane + OriginPoint
            bp_b, op_b = _broadcast_pair(base_planes, origin_pts)
            target_planes = [_plane_origin(bp_i, op_i) for bp_i, op_i in zip(bp_b, op_b)]
            self.GeoAligner_4__TargetPlane = target_planes

            step_log.append("TargetPlane: TreeItem(path={}, index={}) + PlaneOrigin(origin_idx={})".format(base_path, base_index, origin_idx))

            # ============ 3) GeoAligner::4 ============
            geo = timber_breps

            # SourcePlane = ListItem(FacePlaneList, idx)
            src_idx = _get_any_key(self.AllDict, [
                "GeoAligner_4__SourcePlane",
                "GeoAligner::4__SourcePlane",
            ], default=0)
            src_idx_list = _as_list(src_idx) if src_idx is not None else [0]

            src_planes = []
            # face_planes_list: list[list[plane]]（每个 timber 一支）
            for bi, fp_branch in enumerate(_as_list(face_planes_list)):
                fp_b = fp_branch if isinstance(fp_branch, (list, tuple)) else _as_list(fp_branch)
                ii = src_idx_list[bi % len(src_idx_list)] if src_idx_list else 0
                src_planes.append(_safe_index(fp_b, ii, wrap=True))

            # 其它输入：默认 + 支持 AllDict
            rotate_deg = _get_any_key(self.AllDict, ["GeoAligner_4__RotateDeg", "GeoAligner::4__RotateDeg"], default=0.0)
            flip_x = _get_any_key(self.AllDict, ["GeoAligner_4__FlipX", "GeoAligner::4__FlipX"], default=False)
            flip_y = _get_any_key(self.AllDict, ["GeoAligner_4__FlipY", "GeoAligner::4__FlipY"], default=False)
            flip_z = _get_any_key(self.AllDict, ["GeoAligner_4__FlipZ", "GeoAligner::4__FlipZ"], default=False)
            move_x = _get_any_key(self.AllDict, ["GeoAligner_4__MoveX", "GeoAligner::4__MoveX"], default=0.0)
            move_y = _get_any_key(self.AllDict, ["GeoAligner_4__MoveY", "GeoAligner::4__MoveY"], default=0.0)
            move_z = _get_any_key(self.AllDict, ["GeoAligner_4__MoveZ", "GeoAligner::4__MoveZ"], default=0.0)

            src_out, tgt_out, xfm_out, moved_geo = _geo_aligner(
                geo,
                src_planes,
                target_planes,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            self.GeoAligner_4__SourceOut = src_out
            self.GeoAligner_4__TargetOut = tgt_out
            self.GeoAligner_4__TransformOut = xfm_out
            self.GeoAligner_4__MovedGeo = flatten_any(moved_geo)

            self.GeoAligner_4__Log = flatten_any([
                "GeoAligner::4 rotate_deg={} flip=({}, {}, {}) move=({}, {}, {}) src_idx={}".format(
                    rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z, src_idx
                )
            ])

            self.Step6__Log = flatten_any([
                self.BlockCutter_2__Log,
                self.GeoAligner_4__Log,
                step_log,
            ])

            self.Log.append("[Step6] BlockCutter::2 + GeoAligner::4 OK")
        except Exception as e:
            self.Step6__Log = flatten_any([step_log, "[Step6] FAILED: {}".format(e)])
            self.GeoAligner_4__Log = flatten_any(["[Step6] FAILED: {}".format(e)])
            self.Log.append("[Step6] FAILED: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Solver 入口
    # ----------------------------------------------------------


    # ----------------------------------------------------------
    # Step 7：GongYan::1 + PlaneFromLists::3 + GeoAligner::5
    # ----------------------------------------------------------
    def step7_gongyan_1__plane_from_lists_3__geo_aligner_5(self):
        """按 GH 连线复刻：

        1) GongYan::1：生成栱眼刀具 ToolBrep + TopPlaneA/TopPlaneB
        2) PlaneFromLists::3：从 Step2(BuildTimberBlockUniform_SkewAxis_M) 的
           EdgeMidPoints / Corner0Planes 提取 ResultPlane
        3) GeoAligner::5：对齐 ToolBrep（SourcePlane=TopPlaneB → TargetPlane=ResultPlane），并施加 MoveX

        说明：
          - 参数优先级：输入端（本 Solver 无额外输入）> AllDict > 默认值
          - Tree/list 广播：尽量遵循 GH 风格（短列表循环补齐；Tree 按分支循环）
          - 关键输出（ResultPlane / MovedGeo）会 flatten_any()
        """
        try:
            all_dict = self.AllDict if isinstance(self.AllDict, dict) else {}

            # ---------- GongYan::1 inputs ----------
            # SectionPlane：XZ Plane（WorldXZ）
            section_plane = make_ref_plane('WorldXZ', origin=rg.Point3d(0.0, 0.0, 0.0))

            # A：默认原点
            A_input = rg.Point3d(0.0, 0.0, 0.0)

            radius_fen = _get_comp_param(all_dict, 'GongYan::1', 'RadiusFen', None, None)
            length_fen = _get_comp_param(all_dict, 'GongYan::1', 'LengthFen', None, None)
            inner_radius_fen = _get_comp_param(all_dict, 'GongYan::1', 'InnerRadiusFen', None, None)
            move_fen = _get_comp_param(all_dict, 'GongYan::1', 'MoveFen', None, None)

            # 默认值（尽量不凭空猜测：若 DB 没有则用 0）
            if radius_fen is None:
                radius_fen = 0
            if length_fen is None:
                length_fen = 0
            if inner_radius_fen is None:
                inner_radius_fen = 0
            if move_fen is None:
                move_fen = 0

            # Tree 检测
            rf_tree = to_py_list(radius_fen) if (hasattr(radius_fen, 'BranchCount') and hasattr(radius_fen, 'Branch')) else None
            lf_tree = to_py_list(length_fen) if (hasattr(length_fen, 'BranchCount') and hasattr(length_fen, 'Branch')) else None
            ir_tree = to_py_list(inner_radius_fen) if (hasattr(inner_radius_fen, 'BranchCount') and hasattr(inner_radius_fen, 'Branch')) else None
            mv_tree = to_py_list(move_fen) if (hasattr(move_fen, 'BranchCount') and hasattr(move_fen, 'Branch')) else None

            def _gongyan_build_one(rf, lf, ir, mv):
                builder = FT_GongYanSectionABFEA(
                    section_plane=section_plane,
                    A_input=A_input,
                    radius_fen=rf,
                    length_fen=lf,
                    inner_radius_fen=ir,
                    move_fen=mv,
                    doc=sc.doc
                )
                return builder.build()

            # 输出容器
            section_face_out = []
            points_out = []
            inner_section_out = []
            inner_section_moved_out = []
            inner_points_out = []
            loft_face_out = []
            top_face_out = []
            tool_brep_out = []
            top_plane_a_out = []
            top_plane_b_out = []
            log_out = []

            if rf_tree is not None or lf_tree is not None or ir_tree is not None or mv_tree is not None:
                # 按分支循环
                rf_tree = rf_tree if rf_tree is not None else [to_py_list(radius_fen)]
                lf_tree = lf_tree if lf_tree is not None else [to_py_list(length_fen)]
                ir_tree = ir_tree if ir_tree is not None else [to_py_list(inner_radius_fen)]
                mv_tree = mv_tree if mv_tree is not None else [to_py_list(move_fen)]

                bc = max(len(rf_tree), len(lf_tree), len(ir_tree), len(mv_tree), 1)

                for bi in range(bc):
                    rfb = _as_list(rf_tree[bi % len(rf_tree)] if rf_tree else [])
                    lfb = _as_list(lf_tree[bi % len(lf_tree)] if lf_tree else [])
                    irb = _as_list(ir_tree[bi % len(ir_tree)] if ir_tree else [])
                    mvb = _as_list(mv_tree[bi % len(mv_tree)] if mv_tree else [])

                    rfb, lfb, irb, mvb = _broadcast_multi(rfb, lfb, irb, mvb)

                    sf_b = []
                    pt_b = []
                    ins_b = []
                    insm_b = []
                    inp_b = []
                    lf_b = []
                    tf_b = []
                    tb_b = []
                    tpa_b = []
                    tpb_b = []
                    lg_b = []

                    for rf, lf, ir, mv in zip(rfb, lfb, irb, mvb):
                        try:
                            (SectionFace,
                             Points,
                             InnerSection,
                             InnerSectionMoved,
                             InnerPoints,
                             LoftFace,
                             TopFace,
                             ToolBrep,
                             TopPlaneA,
                             TopPlaneB,
                             Log) = _gongyan_build_one(rf, lf, ir, mv)
                        except Exception as e:
                            SectionFace=Points=InnerSection=InnerSectionMoved=InnerPoints=LoftFace=TopFace=ToolBrep=TopPlaneA=TopPlaneB=None
                            Log = 'GongYan error: {}'.format(e)

                        sf_b.append(SectionFace)
                        pt_b.append(Points)
                        ins_b.append(InnerSection)
                        insm_b.append(InnerSectionMoved)
                        inp_b.append(InnerPoints)
                        lf_b.append(LoftFace)
                        tf_b.append(TopFace)
                        tb_b.append(ToolBrep)
                        tpa_b.append(TopPlaneA)
                        tpb_b.append(TopPlaneB)
                        lg_b.append(Log)

                    section_face_out.append(sf_b)
                    points_out.append(pt_b)
                    inner_section_out.append(ins_b)
                    inner_section_moved_out.append(insm_b)
                    inner_points_out.append(inp_b)
                    loft_face_out.append(lf_b)
                    top_face_out.append(tf_b)
                    tool_brep_out.append(tb_b)
                    top_plane_a_out.append(tpa_b)
                    top_plane_b_out.append(tpb_b)
                    log_out.append(lg_b)

            else:
                # 非 Tree：列表广播
                rf_list, lf_list, ir_list, mv_list = _broadcast_multi(radius_fen, length_fen, inner_radius_fen, move_fen)
                for rf, lf, ir, mv in zip(rf_list, lf_list, ir_list, mv_list):
                    try:
                        (SectionFace,
                         Points,
                         InnerSection,
                         InnerSectionMoved,
                         InnerPoints,
                         LoftFace,
                         TopFace,
                         ToolBrep,
                         TopPlaneA,
                         TopPlaneB,
                         Log) = _gongyan_build_one(rf, lf, ir, mv)
                    except Exception as e:
                        SectionFace=Points=InnerSection=InnerSectionMoved=InnerPoints=LoftFace=TopFace=ToolBrep=TopPlaneA=TopPlaneB=None
                        Log = 'GongYan error: {}'.format(e)

                    section_face_out.append(SectionFace)
                    points_out.append(Points)
                    inner_section_out.append(InnerSection)
                    inner_section_moved_out.append(InnerSectionMoved)
                    inner_points_out.append(InnerPoints)
                    loft_face_out.append(LoftFace)
                    top_face_out.append(TopFace)
                    tool_brep_out.append(ToolBrep)
                    top_plane_a_out.append(TopPlaneA)
                    top_plane_b_out.append(TopPlaneB)
                    log_out.append(Log)

            # 存 self（保留全部输出）
            self.GongYan_1__SectionFace = section_face_out
            self.GongYan_1__Points = points_out
            self.GongYan_1__InnerSection = inner_section_out
            self.GongYan_1__InnerSectionMoved = inner_section_moved_out
            self.GongYan_1__InnerPoints = inner_points_out
            self.GongYan_1__LoftFace = loft_face_out
            self.GongYan_1__TopFace = top_face_out
            self.GongYan_1__ToolBrep = tool_brep_out
            self.GongYan_1__TopPlaneA = top_plane_a_out
            self.GongYan_1__TopPlaneB = top_plane_b_out
            self.GongYan_1__Log = log_out

            # ---------- PlaneFromLists::3 ----------
            op = getattr(self, 'EdgeMidPoints', None)
            bp = getattr(self, 'Corner0Planes', None)

            idx_origin = _get_comp_param(all_dict, 'PlaneFromLists::3', 'IndexOrigin', None, 0)
            idx_plane = _get_comp_param(all_dict, 'PlaneFromLists::3', 'IndexPlane', None, 0)
            wrap = _get_comp_param(all_dict, 'PlaneFromLists::3', 'Wrap', None, True)

            BasePlane3, OriginPoint3, ResultPlane3, Log3 = _plane_from_lists(op, bp, idx_origin, idx_plane, Wrap=wrap)

            self.PlaneFromLists_3__BasePlane = BasePlane3
            self.PlaneFromLists_3__OriginPoint = OriginPoint3
            # 关键：下游用 ResultPlane 必须 flatten
            self.PlaneFromLists_3__ResultPlane = flatten_any(ResultPlane3)
            self.PlaneFromLists_3__Log = Log3

            # ---------- GeoAligner::5 ----------
            geo_in = self.GongYan_1__ToolBrep
            src_in = self.GongYan_1__TopPlaneB
            tgt_in = self.PlaneFromLists_3__ResultPlane

            rotate_deg = _get_comp_param(all_dict, 'GeoAligner::5', 'RotateDeg', None, 0.0)
            flip_x = _get_comp_param(all_dict, 'GeoAligner::5', 'FlipX', None, False)
            flip_y = _get_comp_param(all_dict, 'GeoAligner::5', 'FlipY', None, False)
            flip_z = _get_comp_param(all_dict, 'GeoAligner::5', 'FlipZ', None, False)
            move_x = _get_comp_param(all_dict, 'GeoAligner::5', 'MoveX', None, 0.0)
            move_y = _get_comp_param(all_dict, 'GeoAligner::5', 'MoveY', None, 0.0)
            move_z = _get_comp_param(all_dict, 'GeoAligner::5', 'MoveZ', None, 0.0)

            # MoveX 可能为 Tree/list：需要广播
            geo_tree = to_py_list(geo_in) if (hasattr(geo_in, 'BranchCount') and hasattr(geo_in, 'Branch')) else None
            src_tree = to_py_list(src_in) if (hasattr(src_in, 'BranchCount') and hasattr(src_in, 'Branch')) else None
            tgt_tree = to_py_list(tgt_in) if (hasattr(tgt_in, 'BranchCount') and hasattr(tgt_in, 'Branch')) else None
            mx_tree = to_py_list(move_x) if (hasattr(move_x, 'BranchCount') and hasattr(move_x, 'Branch')) else None

            if geo_tree is not None or src_tree is not None or tgt_tree is not None or mx_tree is not None:
                geo_tree = geo_tree if geo_tree is not None else [to_py_list(geo_in)]
                src_tree = src_tree if src_tree is not None else [to_py_list(src_in)]

                if tgt_tree is None:
                    t_list = _as_list(tgt_in)
                    tgt_tree = [t_list] if t_list else [[tgt_in]]

                if mx_tree is None:
                    mx_list = _as_list(move_x)
                    mx_tree = [mx_list] if mx_list else [[move_x]]

                bc = max(len(geo_tree), len(src_tree), len(tgt_tree), len(mx_tree), 1)

                src_out_tree = []
                tgt_out_tree = []
                xfm_out_tree = []
                moved_tree = []
                log_tree = []

                for bi in range(bc):
                    g_branch = geo_tree[bi % len(geo_tree)] if geo_tree else []
                    s_branch = src_tree[bi % len(src_tree)] if src_tree else []
                    t_branch = tgt_tree[bi % len(tgt_tree)] if tgt_tree else []
                    mx_branch = mx_tree[bi % len(mx_tree)] if mx_tree else []

                    g_list = _as_list(g_branch)
                    s_list = _as_list(s_branch)
                    t_list = _as_list(t_branch)
                    mx_list = _as_list(mx_branch)

                    g_list, s_list, t_list, mx_list = _broadcast_multi(g_list, s_list, t_list, mx_list)

                    src_b = []
                    tgt_b = []
                    xfm_b = []
                    mv_b = []
                    lg_b = []

                    for gg, ss, tt, mxv in zip(g_list, s_list, t_list, mx_list):
                        try:
                            so, to, xfm, mg = GeoAligner_xfm.align(
                                gg, ss, tt,
                                rotate_deg=rotate_deg,
                                flip_x=bool(flip_x),
                                flip_y=bool(flip_y),
                                flip_z=bool(flip_z),
                                move_x=mxv,
                                move_y=move_y,
                                move_z=move_z,
                            )
                            lg = None
                        except Exception as e:
                            so=to=xfm=mg=None
                            lg = 'GeoAligner5 error: {}'.format(e)

                        src_b.append(so)
                        tgt_b.append(to)
                        xfm_b.append(xfm)
                        mv_b.append(mg)
                        lg_b.append(lg)

                    src_out_tree.append(src_b)
                    tgt_out_tree.append(tgt_b)
                    xfm_out_tree.append(xfm_b)
                    moved_tree.append(mv_b)
                    log_tree.append(lg_b)

                self.GeoAligner_5__SourceOut = src_out_tree
                self.GeoAligner_5__TargetOut = tgt_out_tree
                self.GeoAligner_5__TransformOut = xfm_out_tree
                self.GeoAligner_5__MovedGeo = flatten_any(moved_tree)
                self.GeoAligner_5__Log = log_tree

            else:
                g_list = _as_list(geo_in)
                s_list = _as_list(src_in)
                t_list = _as_list(tgt_in)
                mx_list = _as_list(move_x)
                n = max(len(g_list), len(s_list), len(t_list), len(mx_list), 1)

                src_out = []
                tgt_out = []
                xfm_out = []
                moved = []
                lg_out = []

                for i in range(n):
                    gg = g_list[i % len(g_list)] if g_list else None
                    ss = s_list[i % len(s_list)] if s_list else None
                    tt = t_list[i % len(t_list)] if t_list else None
                    mxv = mx_list[i % len(mx_list)] if mx_list else 0.0

                    try:
                        so, to, xfm, mg = GeoAligner_xfm.align(
                            gg, ss, tt,
                            rotate_deg=rotate_deg,
                            flip_x=bool(flip_x),
                            flip_y=bool(flip_y),
                            flip_z=bool(flip_z),
                            move_x=mxv,
                            move_y=move_y,
                            move_z=move_z,
                        )
                        lg = None
                    except Exception as e:
                        so=to=xfm=mg=None
                        lg = 'GeoAligner5 error: {}'.format(e)

                    src_out.append(so)
                    tgt_out.append(to)
                    xfm_out.append(xfm)
                    moved.append(mg)
                    lg_out.append(lg)

                self.GeoAligner_5__SourceOut = src_out
                self.GeoAligner_5__TargetOut = tgt_out
                self.GeoAligner_5__TransformOut = xfm_out
                self.GeoAligner_5__MovedGeo = flatten_any(moved)
                self.GeoAligner_5__Log = lg_out

            # Step7 合并日志
            self.Step7__Log = flatten_any([
                self.GongYan_1__Log,
                self.PlaneFromLists_3__Log,
                self.GeoAligner_5__Log,
            ])

        except Exception as e:
            self.Step7__Log = flatten_any(self.Step7__Log)
            self.Step7__Log.append('Step7 fatal error: {}'.format(e))
            self.Log.append('Step7 fatal error: {}'.format(e))

        return self

    # ----------------------------------------------------------
    # Step 8：GongYan::2 + PlaneFromLists::4 + PlaneFromLists::5 + GeoAligner::6
    # ----------------------------------------------------------
    def step8_gongyan_2__pfl_4__pfl_5__geo_aligner_6(self):
        """按 GH 连线复刻：

        1) GongYan::2：生成栱眼刀具几何 ToolBrep + BridgePoints/BridgePlane 等
        2) PlaneFromLists::4：从 Step2(BuildTimberBlockUniform_SkewAxis_M) 的 EdgeMidPoints / Corner0Planes 提取 ResultPlane
        3) PlaneFromLists::5：从 GongYan::2 的 BridgePoints / BridgePlane 提取 ResultPlane
        4) GeoAligner::6：对齐对象为 Geo(Tree 每分支 1 个)，SourcePlane(Tree 每分支 1 个)，
           TargetPlane 单值 & MoveX 单值需要按分支重复使用，逐分支执行，MovedGeo 数量需与 Geo 分支数一致。

        说明：
          - 参数优先级：组件输入端（本 Solver 无额外输入）> AllDict > 默认值
          - PlaneFromLists 广播：IndexOrigin/IndexPlane 长度不一致按 GH 广播；Tree 时按分支循环
          - GeoAligner::6：严格按 Geo 分支数逐分支对齐；最终 self.GeoAligner_6__MovedGeo 必须 flatten_any()
        """
        step_log = []
        try:
            all_dict = self.AllDict if isinstance(self.AllDict, dict) else {}

            # ---------- GongYan::2 inputs ----------
            # SectionPlane：默认 WorldXZ，可被 DB 覆盖
            sec_mode = _get_comp_param(all_dict, 'GongYan::2', 'SectionPlane', None, 'WorldXZ')
            section_plane = make_ref_plane(sec_mode, origin=rg.Point3d(0.0, 0.0, 0.0))

            # A：优先 Solver 输入端 base_point
            A_input = _coerce_point3d(getattr(self, 'base_point', None))

            radius_fen = _get_comp_param(all_dict, 'GongYan::2', 'RadiusFen', None, 0)
            length_fen = _get_comp_param(all_dict, 'GongYan::2', 'LengthFen', None, 0)
            offset_fen = _get_comp_param(all_dict, 'GongYan::2', 'OffsetFen', None, 0)
            extrude_fen = _get_comp_param(all_dict, 'GongYan::2', 'ExtrudeFen', None, 0)

            # Tree 检测
            rf_tree = to_py_list(radius_fen) if (hasattr(radius_fen, 'BranchCount') and hasattr(radius_fen, 'Branch')) else None
            lf_tree = to_py_list(length_fen) if (hasattr(length_fen, 'BranchCount') and hasattr(length_fen, 'Branch')) else None
            of_tree = to_py_list(offset_fen) if (hasattr(offset_fen, 'BranchCount') and hasattr(offset_fen, 'Branch')) else None
            ef_tree = to_py_list(extrude_fen) if (hasattr(extrude_fen, 'BranchCount') and hasattr(extrude_fen, 'Branch')) else None

            def _gongyan2_build_one(rf, lf, ofv, efv):
                builder = FT_GongYanSection_Cai_B(
                    section_plane=section_plane,
                    A_input=A_input,
                    radius_fen=rf,
                    length_fen=lf,
                    offset_fen=ofv,
                    extrude_fen=efv,
                    doc=sc.doc
                )
                return builder.build()

            # 输出容器（可能为 list 或 list[list] Tree）
            sec_face_out = []
            off_face_out = []
            pts_out = []
            off_pts_out = []
            tool_out = []
            bridge_pts_out = []
            bridge_mid_out = []
            bridge_plane_out = []
            log_out = []

            if rf_tree is not None or lf_tree is not None or of_tree is not None or ef_tree is not None:
                rf_tree = rf_tree if rf_tree is not None else [to_py_list(radius_fen)]
                lf_tree = lf_tree if lf_tree is not None else [to_py_list(length_fen)]
                of_tree = of_tree if of_tree is not None else [to_py_list(offset_fen)]
                ef_tree = ef_tree if ef_tree is not None else [to_py_list(extrude_fen)]

                bc = max(len(rf_tree), len(lf_tree), len(of_tree), len(ef_tree), 1)

                for bi in range(bc):
                    rfb = _as_list(rf_tree[bi % len(rf_tree)] if rf_tree else [])
                    lfb = _as_list(lf_tree[bi % len(lf_tree)] if lf_tree else [])
                    ofb = _as_list(of_tree[bi % len(of_tree)] if of_tree else [])
                    efb = _as_list(ef_tree[bi % len(ef_tree)] if ef_tree else [])
                    rfb, lfb, ofb, efb = _broadcast_multi(rfb, lfb, ofb, efb)

                    sf_b = []
                    ofa_b = []
                    pt_b = []
                    ofpt_b = []
                    tb_b = []
                    bpt_b = []
                    bpm_b = []
                    bpl_b = []
                    lg_b = []

                    for rf, lf, ofv, efv in zip(rfb, lfb, ofb, efb):
                        try:
                            (SectionFace,
                             OffsetFace,
                             Points,
                             OffsetPoints,
                             ToolBrep,
                             BridgePoints,
                             BridgeMidPoints,
                             BridgePlane,
                             Log) = _gongyan2_build_one(rf, lf, ofv, efv)
                        except Exception as e:
                            SectionFace=OffsetFace=Points=OffsetPoints=ToolBrep=BridgePoints=BridgeMidPoints=BridgePlane=None
                            Log = 'GongYan::2 error: {}'.format(e)

                        sf_b.append(SectionFace)
                        ofa_b.append(OffsetFace)
                        pt_b.append(Points)
                        ofpt_b.append(OffsetPoints)
                        tb_b.append(ToolBrep)
                        bpt_b.append(BridgePoints)
                        bpm_b.append(BridgeMidPoints)
                        bpl_b.append(BridgePlane)
                        lg_b.append(Log)

                    sec_face_out.append(sf_b)
                    off_face_out.append(ofa_b)
                    pts_out.append(pt_b)
                    off_pts_out.append(ofpt_b)
                    tool_out.append(tb_b)
                    bridge_pts_out.append(bpt_b)
                    bridge_mid_out.append(bpm_b)
                    bridge_plane_out.append(bpl_b)
                    log_out.append(lg_b)

            else:
                rf_list, lf_list, of_list, ef_list = _broadcast_multi(radius_fen, length_fen, offset_fen, extrude_fen)
                for rf, lf, ofv, efv in zip(rf_list, lf_list, of_list, ef_list):
                    try:
                        (SectionFace,
                         OffsetFace,
                         Points,
                         OffsetPoints,
                         ToolBrep,
                         BridgePoints,
                         BridgeMidPoints,
                         BridgePlane,
                         Log) = _gongyan2_build_one(rf, lf, ofv, efv)
                    except Exception as e:
                        SectionFace=OffsetFace=Points=OffsetPoints=ToolBrep=BridgePoints=BridgeMidPoints=BridgePlane=None
                        Log = 'GongYan::2 error: {}'.format(e)

                    sec_face_out.append(SectionFace)
                    off_face_out.append(OffsetFace)
                    pts_out.append(Points)
                    off_pts_out.append(OffsetPoints)
                    tool_out.append(ToolBrep)
                    bridge_pts_out.append(BridgePoints)
                    bridge_mid_out.append(BridgeMidPoints)
                    bridge_plane_out.append(BridgePlane)
                    log_out.append(Log)

            self.GongYan_2__SectionFace = sec_face_out
            self.GongYan_2__OffsetFace = off_face_out
            self.GongYan_2__Points = pts_out
            self.GongYan_2__OffsetPoints = off_pts_out
            # 先保留原始 ToolBrep（通常为 Tree：每分支 2 个值）
            self.GongYan_2__ToolBrep_Raw = tool_out
            self.GongYan_2__BridgePoints = bridge_pts_out
            self.GongYan_2__BridgeMidPoints = bridge_mid_out
            self.GongYan_2__BridgePlane = bridge_plane_out
            self.GongYan_2__Log = log_out

            # ---------- PlaneFromLists::4 (BuildTimberBlockUniform_SkewAxis_M) ----------
            op4 = getattr(self, 'EdgeMidPoints', None)
            bp4 = getattr(self, 'Corner0Planes', None)
            idx_origin4 = _get_comp_param(all_dict, 'PlaneFromLists::4', 'IndexOrigin', None, 0)
            idx_plane4 = _get_comp_param(all_dict, 'PlaneFromLists::4', 'IndexPlane', None, 0)
            wrap4 = _get_comp_param(all_dict, 'PlaneFromLists::4', 'Wrap', None, True)

            BasePlane4, OriginPoint4, ResultPlane4, Log4 = _plane_from_lists(op4, bp4, idx_origin4, idx_plane4, Wrap=wrap4)
            self.PlaneFromLists_4__BasePlane = BasePlane4
            self.PlaneFromLists_4__OriginPoint = OriginPoint4
            self.PlaneFromLists_4__ResultPlane = flatten_any(ResultPlane4)
            self.PlaneFromLists_4__Log = Log4

            # ---------- PlaneFromLists::5 (GongYan::2 BridgePoints/BridgePlane) ----------
            op5 = self.GongYan_2__BridgeMidPoints
            bp5 = self.GongYan_2__BridgePlane
            idx_origin5 = _get_comp_param(all_dict, 'PlaneFromLists::5', 'IndexOrigin', None, 0)
            idx_plane5 = _get_comp_param(all_dict, 'PlaneFromLists::5', 'IndexPlane', None, 0)
            wrap5 = _get_comp_param(all_dict, 'PlaneFromLists::5', 'Wrap', None, True)



            BasePlane5, OriginPoint5, ResultPlane5, Log5 = _plane_from_lists(op5, bp5, idx_origin5, idx_plane5, Wrap=wrap5)
            self.PlaneFromLists_5__BasePlane = BasePlane5
            self.PlaneFromLists_5__OriginPoint = OriginPoint5
            # 这里 ResultPlane5 应保持 Tree 结构供 GeoAligner::6 分支对齐
            self.PlaneFromLists_5__ResultPlane = ResultPlane5
            self.PlaneFromLists_5__Log = Log5

            print(ResultPlane5)

            # ---------- GeoAligner::6 ----------
            # List Item 子图：ToolBrep(Tree 每分支 2 个) + Index(list 2 个) -> Geo(Tree 每分支 1 个)
            tool_tree = to_py_list(self.GongYan_2__ToolBrep_Raw)

            geo_indices = _get_comp_param(all_dict, 'GeoAligner::6', 'Geo', None, None)
            if geo_indices is None:
                # 兼容扁平键写法：GeoAligner_6__Geo
                geo_indices = _get_any_key(all_dict, ['GeoAligner_6__Geo', 'GeoAligner::6__Geo'], default=[0])
            geo_indices = _as_list(geo_indices)
            if not geo_indices:
                geo_indices = [0]

            # 以索引数作为期望分支数（通常 2）
            bc_geo = max(len(geo_indices), len(tool_tree), 1)
            geo_tree = []
            for bi in range(bc_geo):
                branch = tool_tree[bi % len(tool_tree)] if tool_tree else []
                idx = geo_indices[bi % len(geo_indices)]
                geo_item = _safe_index(branch, idx, wrap=True)
                geo_tree.append([geo_item])

            # 按用户要求：将 GongYan_2__ToolBrep 改为 List Item 取值后的结果（Tree：每分支 1 个值）
            self.GongYan_2__ToolBrep_ListItem = geo_tree
            self.GongYan_2__ToolBrep = geo_tree

            # SourcePlane：PlaneFromLists::5.ResultPlane（Tree 每分支 1 个，若分支内多值取首个非空）
            src_tree = to_py_list(self.PlaneFromLists_5__ResultPlane)

            # TargetPlane：PlaneFromLists::4.ResultPlane（单值，重复用于所有分支）
            tgt_single = first_non_null(self.PlaneFromLists_4__ResultPlane)

            # MoveX：单值（重复用于所有分支）
            move_x = _get_comp_param(all_dict, 'GeoAligner::6', 'MoveX', None, 0.0)
            rotate_deg = _get_comp_param(all_dict, 'GeoAligner::6', 'RotateDeg', None, 0.0)
            flip_x = _get_comp_param(all_dict, 'GeoAligner::6', 'FlipX', None, False)
            flip_y = _get_comp_param(all_dict, 'GeoAligner::6', 'FlipY', None, False)
            flip_z = _get_comp_param(all_dict, 'GeoAligner::6', 'FlipZ', None, False)
            move_y = _get_comp_param(all_dict, 'GeoAligner::6', 'MoveY', None, 0.0)
            move_z = _get_comp_param(all_dict, 'GeoAligner::6', 'MoveZ', None, 0.0)

            bc = max(len(geo_tree), len(src_tree), 1)

            src_out_tree = []
            tgt_out_tree = []
            xfm_out_tree = []
            moved_tree = []
            log_tree = []

            for bi in range(bc):
                g_branch = geo_tree[bi % len(geo_tree)] if geo_tree else [None]
                s_branch = src_tree[bi % len(src_tree)] if src_tree else [None]

                gg = first_non_null(g_branch)
                ss = first_non_null(s_branch)
                tt = tgt_single
                try:
                    so, to, xfm, mg = GeoAligner_xfm.align(
                        gg, ss, tt,
                        rotate_deg=rotate_deg,
                        flip_x=bool(flip_x),
                        flip_y=bool(flip_y),
                        flip_z=bool(flip_z),
                        move_x=move_x,
                        move_y=move_y,
                        move_z=move_z,
                    )
                    lg = None
                except Exception as e:
                    so=to=xfm=mg=None
                    lg = 'GeoAligner::6 error: {}'.format(e)

                src_out_tree.append([so])
                tgt_out_tree.append([to])
                xfm_out_tree.append([xfm])
                moved_tree.append([mg])
                log_tree.append([lg])

            self.GeoAligner_6__SourceOut = src_out_tree
            self.GeoAligner_6__TargetOut = tgt_out_tree
            self.GeoAligner_6__TransformOut = xfm_out_tree
            self.GeoAligner_6__MovedGeo_Tree = moved_tree
            self.GeoAligner_6__MovedGeo = flatten_any(moved_tree)
            self.GeoAligner_6__Log = log_tree

            self.Step8__Log = flatten_any([
                self.GongYan_2__Log,
                self.PlaneFromLists_4__Log,
                self.PlaneFromLists_5__Log,
                self.GeoAligner_6__Log,
                step_log,
            ])

        except Exception as e:
            self.Step8__Log = flatten_any([step_log, 'Step8 fatal error: {}'.format(e)])
            self.GeoAligner_6__Log = flatten_any(['Step8 fatal error: {}'.format(e)])
            self.Log.append('Step8 fatal error: {}'.format(e))

        return self

    def run(self):
        self.step1_read_db()
        self.step2_build_timber()

        # Step 3
        self.step3_plane_juansha_geoaligner_1()

        # Step 4
        self.step4_plane_from_lists_2__juansha_2__geo_aligner_2()

        # Step 5
        self.step5_blockcutter_1__geo_aligner_3()

        # Step 6
        self.step6_blockcutter_2__geo_aligner_4()

        # Step 7
        self.step7_gongyan_1__plane_from_lists_3__geo_aligner_5()

        # Step 8
        self.step8_gongyan_2__pfl_4__pfl_5__geo_aligner_6()

        # Step 9：CutTimbersByTools（最终切割输出）
        self.step9_cut_timbers_by_tools(
            timbers=getattr(self, 'TimberBrep', None),
            tools=flatten_any([
                getattr(self, 'GeoAligner_1__MovedGeo', None),
                getattr(self, 'GeoAligner_2__MovedGeo', None),
                getattr(self, 'GeoAligner_3__MovedGeo', None),
                getattr(self, 'GeoAligner_4__MovedGeo', None),
                getattr(self, 'GeoAligner_5__MovedGeo', None),
                getattr(self, 'GeoAligner_6__MovedGeo', None),
            ]),
            keep_inside=None,
        )

        # 清理嵌套（开发模式输出中常见）
        self.FailTimbers = flatten_any(self.FailTimbers)
        self.Log = flatten_any(self.Log)
        self.DBLog = flatten_any(self.DBLog)
        self.Log_BuildTimber = flatten_any(self.Log_BuildTimber)

        # Step3 logs flatten
        self.PlaneFromLists_1__Log = flatten_any(self.PlaneFromLists_1__Log)
        self.Juansha_1__Log = flatten_any(self.Juansha_1__Log)

        # Step4 logs flatten
        self.PlaneFromLists_2__Log = flatten_any(self.PlaneFromLists_2__Log)
        self.Juansha_2__Log = flatten_any(self.Juansha_2__Log)
        self.Step4__Log = flatten_any(self.Step4__Log)

        # Step5 logs flatten
        self.BlockCutter_1__Log = flatten_any(self.BlockCutter_1__Log)
        self.GeoAligner_3__Log = flatten_any(self.GeoAligner_3__Log)
        self.Step5__Log = flatten_any(self.Step5__Log)

        # Step6 logs flatten
        self.BlockCutter_2__Log = flatten_any(self.BlockCutter_2__Log)
        self.GeoAligner_4__Log = flatten_any(self.GeoAligner_4__Log)
        self.Step6__Log = flatten_any(self.Step6__Log)

        # Step7 logs flatten
        self.GongYan_1__Log = flatten_any(self.GongYan_1__Log)
        self.PlaneFromLists_3__Log = flatten_any(self.PlaneFromLists_3__Log)
        self.GeoAligner_5__Log = flatten_any(self.GeoAligner_5__Log)
        self.Step7__Log = flatten_any(self.Step7__Log)

        # Step8 logs flatten
        self.GongYan_2__Log = flatten_any(self.GongYan_2__Log)
        self.PlaneFromLists_4__Log = flatten_any(self.PlaneFromLists_4__Log)
        self.PlaneFromLists_5__Log = flatten_any(self.PlaneFromLists_5__Log)
        self.GeoAligner_6__Log = flatten_any(self.GeoAligner_6__Log)
        self.Step8__Log = flatten_any(self.Step8__Log)

        return self


if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    #   说明：请在 GH Python 组件中声明对应输出端（可按需增减）。
    # ==============================================================

    solver = GuaZiGongInLineWLingGong1_4PU_Solver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- Step9: CutTimbersByTools 输出（developer-friendly） ---
    CutTimbersByTools_1__CutTimbers = solver.CutTimbersByTools_1__CutTimbers
    CutTimbersByTools_1__FailTimbers = solver.CutTimbersByTools_1__FailTimbers
    CutTimbersByTools_1__Log = solver.CutTimbersByTools_1__Log
    Step9__Log = solver.Step9__Log

    # --- 开发模式输出：DB ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- Step2: BuildTimberBlockUniform_SkewAxis_M 输出 ---
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
    Log_BuildTimber = solver.Log_BuildTimber

    # --- Skew extra outputs ---
    Skew_A = solver.Skew_A
    Skew_Point_B = solver.Skew_Point_B
    Skew_Point_C = solver.Skew_Point_C
    Skew_Planes = solver.Skew_Planes
    Skew_ExtraPoints_GF_EH = solver.Skew_ExtraPoints_GF_EH

    # --- Step3: PlaneFromLists::1 输出 ---
    PlaneFromLists_1__OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log = solver.PlaneFromLists_1__Log

    # --- Step3: Juansha::1 输出 ---
    Juansha_1__ToolBrep = solver.Juansha_1__ToolBrep
    Juansha_1__HL_Intersection = solver.Juansha_1__HL_Intersection
    Juansha_1__SectionEdges = solver.Juansha_1__SectionEdges
    Juansha_1__HeightFacePlane = solver.Juansha_1__HeightFacePlane
    Juansha_1__LengthFacePlane = solver.Juansha_1__LengthFacePlane
    Juansha_1__Log = solver.Juansha_1__Log

    # --- Step3: GeoAligner::1 输出 ---
    GeoAligner_1__SourceOut = solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut = solver.GeoAligner_1__TargetOut
    GeoAligner_1__MovedGeo = solver.GeoAligner_1__MovedGeo
    # TransformOut: 若为单个 Transform 可包装为 GH_Transform；Tree/list 维持原结构
    _xfm = solver.GeoAligner_1__TransformOut
    if isinstance(_xfm, rg.Transform):
        GeoAligner_1__TransformOut = ght.GH_Transform(_xfm)
    else:
        GeoAligner_1__TransformOut = _xfm


    # --- Step4: PlaneFromLists::2 输出 ---
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    # --- Step4: Juansha::2 输出 ---
    Juansha_2__ToolBrep = solver.Juansha_2__ToolBrep
    Juansha_2__HL_Intersection = solver.Juansha_2__HL_Intersection
    Juansha_2__SectionEdges = solver.Juansha_2__SectionEdges
    Juansha_2__HeightFacePlane = solver.Juansha_2__HeightFacePlane
    Juansha_2__LengthFacePlane = solver.Juansha_2__LengthFacePlane
    Juansha_2__Log = solver.Juansha_2__Log

    # --- Step4: GeoAligner::2 输出 ---
    GeoAligner_2__SourceOut = solver.GeoAligner_2__SourceOut
    GeoAligner_2__TargetOut = solver.GeoAligner_2__TargetOut
    GeoAligner_2__MovedGeo = solver.GeoAligner_2__MovedGeo
    _xfm2 = solver.GeoAligner_2__TransformOut
    if isinstance(_xfm2, rg.Transform):
        GeoAligner_2__TransformOut = ght.GH_Transform(_xfm2)
    else:
        GeoAligner_2__TransformOut = _xfm2

    Step4__Log = solver.Step4__Log

    # --- Step5: BlockCutter::1 输出 ---
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

    # --- Step5: GeoAligner::3 输出 ---
    GeoAligner_3__SourceOut = solver.GeoAligner_3__SourceOut
    GeoAligner_3__TargetOut = solver.GeoAligner_3__TargetOut
    GeoAligner_3__MovedGeo = solver.GeoAligner_3__MovedGeo
    _xfm3 = solver.GeoAligner_3__TransformOut
    if isinstance(_xfm3, rg.Transform):
        GeoAligner_3__TransformOut = ght.GH_Transform(_xfm3)
    else:
        GeoAligner_3__TransformOut = _xfm3
    GeoAligner_3__Log = solver.GeoAligner_3__Log

    Step5__Log = solver.Step5__Log

    # --- Step6: BlockCutter::2 输出 ---
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

    # --- Step6: TargetPlane 构造子图输出 ---
    GeoAligner_4__TargetPlane_BasePlane = solver.GeoAligner_4__TargetPlane_BasePlane
    GeoAligner_4__TargetPlane_OriginPoint = solver.GeoAligner_4__TargetPlane_OriginPoint
    GeoAligner_4__TargetPlane = solver.GeoAligner_4__TargetPlane

    # --- Step6: GeoAligner::4 输出 ---
    GeoAligner_4__SourceOut = solver.GeoAligner_4__SourceOut
    GeoAligner_4__TargetOut = solver.GeoAligner_4__TargetOut
    GeoAligner_4__MovedGeo = solver.GeoAligner_4__MovedGeo
    _xfm4 = solver.GeoAligner_4__TransformOut
    if isinstance(_xfm4, rg.Transform):
        GeoAligner_4__TransformOut = ght.GH_Transform(_xfm4)
    else:
        GeoAligner_4__TransformOut = _xfm4
    GeoAligner_4__Log = solver.GeoAligner_4__Log

    Step6__Log = solver.Step6__Log

    # --- Step7: GongYan::1 + PlaneFromLists::3 + GeoAligner::5 输出 ---
    GongYan_1__ToolBrep = solver.GongYan_1__ToolBrep
    GongYan_1__TopPlaneA = solver.GongYan_1__TopPlaneA
    GongYan_1__TopPlaneB = solver.GongYan_1__TopPlaneB
    GongYan_1__Log = solver.GongYan_1__Log

    PlaneFromLists_3__OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__Log = solver.PlaneFromLists_3__Log

    GeoAligner_5__SourceOut = solver.GeoAligner_5__SourceOut
    GeoAligner_5__TargetOut = solver.GeoAligner_5__TargetOut
    _xfm5 = solver.GeoAligner_5__TransformOut
    # Transform 可能为单值 / list / tree：尽量包装为 GH_Transform
    def _wrap_xfm(v):
        if isinstance(v, rg.Transform):
            return ght.GH_Transform(v)
        if isinstance(v, (list, tuple)):
            return [ _wrap_xfm(x) for x in v ]
        return v
    GeoAligner_5__TransformOut = _wrap_xfm(_xfm5)
    GeoAligner_5__MovedGeo = solver.GeoAligner_5__MovedGeo
    GeoAligner_5__Log = solver.GeoAligner_5__Log

    Step7__Log = solver.Step7__Log

    # --- Step8: GongYan::2 + PlaneFromLists::4 + PlaneFromLists::5 + GeoAligner::6 输出 ---
    GongYan_2__SectionFace = solver.GongYan_2__SectionFace
    GongYan_2__OffsetFace = solver.GongYan_2__OffsetFace
    GongYan_2__Points = solver.GongYan_2__Points
    GongYan_2__OffsetPoints = solver.GongYan_2__OffsetPoints
    GongYan_2__ToolBrep = solver.GongYan_2__ToolBrep
    GongYan_2__BridgePoints = solver.GongYan_2__BridgePoints
    GongYan_2__BridgeMidPoints = solver.GongYan_2__BridgeMidPoints
    GongYan_2__BridgePlane = solver.GongYan_2__BridgePlane
    GongYan_2__Log = solver.GongYan_2__Log

    PlaneFromLists_4__OriginPoint = solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4__BasePlane = solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4__ResultPlane = solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4__Log = solver.PlaneFromLists_4__Log

    PlaneFromLists_5__OriginPoint = solver.PlaneFromLists_5__OriginPoint
    PlaneFromLists_5__BasePlane = solver.PlaneFromLists_5__BasePlane
    PlaneFromLists_5__ResultPlane = solver.PlaneFromLists_5__ResultPlane[0]
    PlaneFromLists_5__Log = solver.PlaneFromLists_5__Log

    GeoAligner_6__SourceOut = solver.GeoAligner_6__SourceOut
    GeoAligner_6__TargetOut = solver.GeoAligner_6__TargetOut
    _xfm6 = solver.GeoAligner_6__TransformOut
    GeoAligner_6__TransformOut = _wrap_xfm(_xfm6)
    GeoAligner_6__MovedGeo_Tree = solver.GeoAligner_6__MovedGeo_Tree
    GeoAligner_6__MovedGeo = solver.GeoAligner_6__MovedGeo
    GeoAligner_6__Log = solver.GeoAligner_6__Log

    Step8__Log = solver.Step8__Log


# -*- coding: utf-8 -*-
"""
archi_component_templates.py
------------------------------------------------------------
面向“铺作/斗栱”类 GhPython ComponentAssemblySolver 的通用模板函数集。

设计目标
- **规格驱动**：Solver 的每个 step 只做“取值映射 + 调模板函数”。
- **自动验证**：模板函数提供输入规整、广播、拍平、越界保护、类型解包等。
- **可复用扩展**：后续新模块只需要新增“取值映射”，必要时再扩展本文件的模板函数。

适用场景（来自当前工程的 5 个模块抽取）
- DBJsonReader 读取 PuZuo.params_json -> All / AllDict
- GH 风格广播（标量/列表/Tree-like）
- PlaneFromLists（FTPlaneFromLists.build_plane）广播
- GeoAligner_xfm.align 广播
- Transform（Plane/Point3d）安全变换 + GH_Transform 解包
- 输出端一维化（避免 List`1[Object] 嵌套）
"""

from __future__ import division

# Rhino / Grasshopper：在 Rhino 8 CPython 环境可直接 import；若在纯 Python 环境导入也尽量不炸
try:
    import Rhino.Geometry as rg
except Exception:  # pragma: no cover
    rg = None

try:
    import Grasshopper.Kernel.Types as ght
except Exception:  # pragma: no cover
    ght = None


# =========================================================
# 基础：默认平面 / 列表规整 / 递归拍平
# =========================================================

def default_place_plane(origin=(100.0, 100.0, 0.0)):
    """默认放置平面：GH 的 XY Plane，原点为 (100,100,0)。"""
    if rg is None:
        return None
    pl = rg.Plane.WorldXY
    try:
        pl.Origin = rg.Point3d(float(origin[0]), float(origin[1]), float(origin[2]))
    except Exception:
        pl.Origin = rg.Point3d(100.0, 100.0, 0.0)
    return pl


def world_xz_plane(origin=None):
    """
    构造 GH 语义的 XZ Plane（你工程里约定）：
    XAxis=(1,0,0), YAxis=(0,0,1), ZAxis=(0,-1,0)
    """
    if rg is None:
        return None
    o = origin if (origin is not None and isinstance(origin, rg.Point3d)) else rg.Point3d(0.0, 0.0, 0.0)
    return rg.Plane(o, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))


def is_iterable_nonstring(x):
    """判定是否是可迭代但非字符串（尽量兼容 GH 的 .NET List）。"""
    if x is None:
        return False
    if isinstance(x, (str, bytes)):
        return False
    try:
        iter(x)
        return True
    except Exception:
        return False


def ensure_list(x):
    """把 None/单值/tuple/list/GH .NET List 统一成 python list（不做深度拍平）。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    # GH 常见：System.Collections.Generic.List[object] 进来表现成可迭代
    if is_iterable_nonstring(x):
        try:
            return list(x)
        except Exception:
            pass
    return [x]


def flatten_items(x, out_list):
    """
    递归拍平 list/tuple/GH .NET List（用于输出端避免嵌套 List`1[Object]）。
    注意：Rhino.Geometry.GeometryBase 可能也可迭代（极少），此处做保护。
    """
    if x is None:
        return
    if isinstance(x, (list, tuple)):
        for it in x:
            flatten_items(it, out_list)
        return
    if is_iterable_nonstring(x):
        # 防止把 Brep/Curve 等误当可迭代：GeometryBase 特判
        try:
            if rg is not None and isinstance(x, rg.GeometryBase):
                out_list.append(x)
                return
        except Exception:
            pass
        try:
            for it in list(x):
                flatten_items(it, out_list)
            return
        except Exception:
            pass
    out_list.append(x)


def append_flat(out_list, *objs):
    """把多个对象拍平后追加到 out_list（out_list 保持一维 items）。"""
    for o in objs:
        flatten_items(o, out_list)


# =========================================================
# 类型转换：int/float/bool/0-1
# =========================================================

def as_int(val, default=0):
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
            if s == "":
                return int(default)
            return int(float(s))
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return as_int(val[0], default)
    except Exception:
        pass
    return int(default)


def as_float(val, default=0.0):
    try:
        if val is None:
            return float(default)
        if isinstance(val, bool):
            return float(int(val))
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return float(default)
            return float(s)
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return as_float(val[0], default)
    except Exception:
        pass
    return float(default)


def as_bool(x, default=False):
    if x is None:
        return bool(default)
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(int(x) != 0)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("1", "true", "t", "yes", "y", "on"):
            return True
        if s in ("0", "false", "f", "no", "n", "off", ""):
            return False
    return bool(default)


def as_01(x, default=0):
    """将 flip 值统一到 0/1（兼容 bool/int/float/str/list）。"""
    try:
        if isinstance(x, (list, tuple)):
            x = x[0] if len(x) else default
        if x is None:
            return int(default)
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
    except Exception:
        pass
    return int(default)


def as_int_list(x):
    """把 int/float/str 或 list/tuple 转为 list[int]；None -> []"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [as_int(v, 0) for v in x]
    return [as_int(x, 0)]


def as_float_list(x, default=0.0):
    """把 float/str 或 list/tuple 转为 list[float]；None -> []"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [as_float(v, default) for v in x]
    return [as_float(x, default)]


def as_01_list(x, default=0):
    """把 flip 值转为 list[0/1]；None -> []"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [as_01(v, default) for v in x]
    return [as_01(x, default)]


# =========================================================
# 取值：按索引/Tree-like
# =========================================================

def pick_by_index(seq, idx, default=None, clamp=True):
    """从 list/tuple/GH list 中按 idx 取元素；越界返回 default（clamp=True 则夹取）。"""
    arr = ensure_list(seq)
    if not arr:
        return default
    i = as_int(idx, 0)
    if clamp:
        if i < 0:
            i = 0
        if i >= len(arr):
            i = len(arr) - 1
        return arr[i]
    if i < 0 or i >= len(arr):
        return default
    return arr[i]

def pick_by_index_safe(seq, idx, default=None):
    """安全取元素：先按 clamp=False 取（越界返回 default），若结果为 default 且序列非空，则回退到 clamp=True。
    目的：在索引偶发越界（例如 DB 参数与几何面列表长度不一致）时，尽量不中断后续组装。
    """
    arr = ensure_list(seq)
    if not arr:
        return default
    v = pick_by_index(arr, idx, default=default, clamp=False)
    if v is default:
        v = pick_by_index(arr, idx, default=default, clamp=True)
    return v



def pick_nth_from_tree(tree_like, n=0):
    """从 Tree-like（嵌套 list/tuple/分支）按拍平顺序取第 n 个元素。"""
    if tree_like is None:
        return None
    flat = []
    flatten_items(tree_like, flat)
    if not flat:
        return None
    if n < 0:
        return None
    if n >= len(flat):
        return flat[-1]
    return flat[n]




def normalize_index(idx, n, default=None, clamp=True, wrap=False, allow_negative=True):
    """把 idx 规范化为 [0, n-1] 的整数索引。

    - wrap=True：按 n 取模（GH 某些组件常见语义）
    - allow_negative=True：允许 -1 表示最后一个
    - clamp=True：越界时夹取到 0 或 n-1；否则返回 default
    """
    try:
        n = int(n)
    except Exception:
        return default
    if n <= 0:
        return default

    i = as_int(idx, 0)

    if wrap:
        return i % n

    if allow_negative and i < 0:
        i = n + i

    if clamp:
        if i < 0:
            i = 0
        if i >= n:
            i = n - 1
        return i

    if 0 <= i < n:
        return i
    return default


def is_gh_tree(x):
    """粗略判断是否为 Grasshopper DataTree（避免硬依赖 Grasshopper 命名空间）。"""
    if x is None:
        return False
    # DataTree 常见属性：BranchCount / Branch(i)
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


def pick_from_items(items, idx, default=None, clamp=False, wrap=False, allow_negative=True, flatten_tree=True):
    """从 items（list/tuple/.NET List/DataTree/嵌套）按 idx 取元素。

    - idx 为 int：返回单值
    - idx 为 list/tuple：返回同长度 list
    - flatten_tree=True：当 items 为 DataTree 或嵌套结构时先拍平再取值
    - clamp/wrap/allow_negative 见 normalize_index
    """
    if items is None:
        return default if not isinstance(idx, (list, tuple)) else []

    arr = None
    if flatten_tree and (is_gh_tree(items) or isinstance(items, (list, tuple)) or is_iterable_nonstring(items)):
        flat = []
        flatten_items(items, flat)
        arr = flat
    else:
        arr = ensure_list(items)

    if not arr:
        return default if not isinstance(idx, (list, tuple)) else []

    def _pick_one(i):
        ii = normalize_index(i, len(arr), default=None, clamp=clamp, wrap=wrap, allow_negative=allow_negative)
        if ii is None:
            return default
        try:
            return arr[ii]
        except Exception:
            return default

    if isinstance(idx, (list, tuple)):
        return [_pick_one(i) for i in idx]
    return _pick_one(idx)
# =========================================================
# 广播：两种形式
# =========================================================

def broadcast_lists(*seqs):
    """
    简化版 GH 广播（统一返回“被广播后的各列表”与 n）：
    - 先 ensure_list
    - n_max = max(len)
    - len==1 重复到 n
    - 若存在多个 len>1 且不等：取 min(len>1)（保守，避免越界）
    """
    L = [ensure_list(s) for s in seqs]
    lens = [len(x) for x in L]
    if not lens or max(lens) == 0:
        return [[] for _ in L], 0

    n_max = max(lens)
    multi = [l for l in lens if l > 1]
    n = min(multi) if (multi and len(set(multi)) > 1) else n_max

    out = []
    for arr in L:
        if len(arr) == 0:
            out.append([None] * n)
        elif len(arr) == 1 and n > 1:
            out.append(arr * n)
        else:
            out.append(arr[:n])
    return out, n


def broadcast_rows(*args):
    """
    GH 类似广播，返回 rows(list[tuple])：
    - 标量当作长度=1
    - list/tuple 当作长度=len
    - N 取最大长度
    - 标量/len==1 重复
    - 其他 list 使用 i % len(list)（wrap）
    """
    lens = []
    for a in args:
        if isinstance(a, (list, tuple)):
            lens.append(len(a))
        else:
            lens.append(1)
    N = max(lens) if lens else 1

    rows = []
    for i in range(N):
        row = []
        for a in args:
            if isinstance(a, (list, tuple)):
                if len(a) == 0:
                    row.append(None)
                elif len(a) == 1:
                    row.append(a[0])
                else:
                    row.append(a[i % len(a)])
            else:
                row.append(a)
        rows.append(tuple(row))
    return rows



def broadcast_rows_clamp_last(*args):
    """与旧版 Solver 一致的广播：N 取最大长度，短列表用最后一个值延展（clamp-last），标量当作长度=1。"""
    lens = []
    seqs = []
    for a in args:
        if isinstance(a, (list, tuple)):
            seqs.append(list(a))
            lens.append(len(a))
        else:
            seqs.append([a])
            lens.append(1)
    N = max(lens) if lens else 1

    rows = []
    for i in range(N):
        row = []
        for seq in seqs:
            if len(seq) == 0:
                row.append(None)
            elif len(seq) == 1:
                row.append(seq[0])
            else:
                row.append(seq[i] if i < len(seq) else seq[-1])
        rows.append(tuple(row))
    return rows


def broadcast_lists_clamp_last(*seqs):
    """返回被广播后的各 list 与 n（clamp-last 规则）。"""
    rows = broadcast_rows_clamp_last(*seqs)
    if not rows:
        return [[] for _ in seqs], 0
    cols = list(zip(*rows))
    return [list(c) for c in cols], len(rows)


def broadcast_pair(a_list, b_list):
    """
    将两个 list 广播到同一长度（仿 GH 一对多/多对多广播）。
    规则与 SiPU 模块中一致。
    返回：(a_out, b_out, n)
    """
    a = ensure_list(a_list)
    b = ensure_list(b_list)
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


def broadcast_to(seq, n, fill=None):
    """把 seq（None/标量/list/tuple）广播到长度 n。"""
    s = ensure_list(seq)
    if n <= 0:
        return []
    if len(s) == 0:
        return [fill] * n
    if len(s) == n:
        return s
    if len(s) == 1 and n > 1:
        return s * n
    if len(s) > n:
        return s[:n]
    return s + [s[-1]] * (n - len(s))


# =========================================================
# Transform：解包 + Plane/Point 安全变换
# =========================================================

def unwrap_transform(xf):
    """将 GH_Transform / Rhino Transform / None 统一解包为 rg.Transform 或 None。"""
    if rg is None:
        return None
    if xf is None:
        return None

    # GH_Transform
    try:
        if ght is not None and isinstance(xf, ght.GH_Transform):
            return xf.Value
    except Exception:
        pass

    if isinstance(xf, rg.Transform):
        return xf

    # 可能有 .Value
    try:
        if hasattr(xf, "Value") and isinstance(xf.Value, rg.Transform):
            return xf.Value
    except Exception:
        pass

    # list/tuple：取第一个（常见 GH item->list 广播）
    if isinstance(xf, (list, tuple)):
        return unwrap_transform(xf[0] if len(xf) else None)

    try:
        return rg.Transform(xf)
    except Exception:
        return None


def xform_plane_axes(pl, xform):
    """
    对 Plane 应用 Transform（对 Origin/XAxis/YAxis 分别变换）。
    相比 Plane.Transform 更可控，避免某些轴向变换异常。
    """
    if rg is None:
        return pl
    xf = unwrap_transform(xform)
    if pl is None or xf is None:
        return pl
    try:
        o = rg.Point3d(pl.Origin)
        x = rg.Vector3d(pl.XAxis)
        y = rg.Vector3d(pl.YAxis)
        o.Transform(xf)
        x.Transform(xf)
        y.Transform(xf)
        return rg.Plane(o, x, y)
    except Exception:
        return pl


def transform_plane(pl, xform):
    """Plane.Transform 的安全封装（会 clone）。"""
    if rg is None:
        return pl
    xf = unwrap_transform(xform)
    if pl is None or xf is None:
        return pl
    try:
        p2 = rg.Plane(pl)
        p2.Transform(xf)
        return p2
    except Exception:
        # 兜底用轴向变换
        return xform_plane_axes(pl, xf)


def transform_planes(planes, xform):
    """Plane 列表应用 Transform（None 安全；xform 可为 list/tree，默认取第一个有效）。"""
    pls = ensure_list(planes)
    xf = unwrap_transform(xform)
    if xf is None:
        return pls
    return [transform_plane(p, xf) for p in pls]


def transform_points(points, xform):
    """Point3d 列表应用 Transform（None 安全）。"""
    if rg is None:
        return ensure_list(points)
    pts = ensure_list(points)
    xf = unwrap_transform(xform)
    if xf is None:
        return pts
    out = []
    for p in pts:
        try:
            if isinstance(p, rg.Point3d):
                p2 = rg.Point3d(p)
                p2.Transform(xf)
                out.append(p2)
            else:
                out.append(p)
        except Exception:
            out.append(p)
    return out


def first_valid_xform(xforms):
    """从 xforms(list/tree/单值) 中取第一个可解包的 Transform。"""
    xf = unwrap_transform(xforms)
    if xf is not None:
        return xf
    cand = ensure_list(xforms)
    for c in cand:
        xf2 = unwrap_transform(c)
        if xf2 is not None:
            return xf2
    return None


# =========================================================
# 组件模板：DB / PlaneFromLists / GeoAligner
# =========================================================

def all_to_dict(all_list):
    """All(list[(k,v)]) -> dict"""
    d = {}
    if not all_list:
        return d
    for kv in all_list:
        if isinstance(kv, (list, tuple)) and len(kv) == 2:
            d[str(kv[0])] = kv[1]
    return d


def read_puzuo_params(db_path, type_code, ghenv=None, table="PuZuo", field="params_json"):
    """
    统一 DBJsonReader 读取（PuZuo.params_json）：
    返回：(Value, All, AllDict, DBLog)
    """
    from yingzao.ancientArchi import DBJsonReader  # 延迟导入，避免纯 python 环境炸
    reader = DBJsonReader(
        db_path=db_path,
        table=table,
        key_field="type_code",
        key_value=type_code,
        field=field,
        json_path=None,
        export_all=True,
        ghenv=ghenv
    )
    value, all_list, dblog = reader.run()
    return value, all_list, all_to_dict(all_list), dblog


def ft_plane_from_lists_broadcast(origin_points, base_planes, index_origin, index_plane, wrap=True, tag=None):
    """
    FTPlaneFromLists.build_plane 广播封装。
    返回：(BasePlane_list, OriginPoint_list, ResultPlane_list, Log_list)
    """
    from yingzao.ancientArchi import FTPlaneFromLists  # 延迟导入
    builder = FTPlaneFromLists(wrap=wrap)

    idxO = ensure_list(index_origin)
    idxP = ensure_list(index_plane)
    (idxO_b, idxP_b), n = broadcast_lists(idxO, idxP)

    base_out, org_out, res_out, log_out = [], [], [], []
    for i in range(n):
        try:
            bp, op, rp, lg = builder.build_plane(origin_points, base_planes, idxO_b[i], idxP_b[i])
        except Exception as e:
            bp, op, rp, lg = None, None, None, "PFL Error: {}".format(e)
        base_out.append(bp)
        org_out.append(op)
        res_out.append(rp)
        if tag:
            log_out.append("[{}][{}] {}".format(tag, i, lg))
        else:
            log_out.append(lg)
    return base_out, org_out, res_out, log_out



def ft_plane_from_lists_broadcast_clamp_last(origin_points, base_planes, index_origin, index_plane, wrap=True, tag=None):
    """与旧版 Solver 一致的 FTPlaneFromLists.build_plane 广播封装（clamp-last）。

    - index_origin / index_plane 允许为 int 或 list
    - N 取最大长度，短列表用最后一个值延展
    返回：(BasePlane_list, OriginPoint_list, ResultPlane_list, Log_list)
    """
    from yingzao.ancientArchi import FTPlaneFromLists  # 延迟导入
    builder = FTPlaneFromLists(wrap=wrap)

    idxO = ensure_list(index_origin)
    idxP = ensure_list(index_plane)
    (idxO_b, idxP_b), n = broadcast_lists_clamp_last(idxO, idxP)

    base_out, org_out, res_out, log_out = [], [], [], []
    for i in range(n):
        try:
            bp, op, rp, lg = builder.build_plane(origin_points, base_planes, idxO_b[i], idxP_b[i])
        except Exception as e:
            bp, op, rp, lg = None, None, None, "PFL Error: {}".format(e)
        base_out.append(bp)
        org_out.append(op)
        res_out.append(rp)
        if tag:
            log_out.append("[{}][{}] {}".format(tag, i, lg))
        else:
            log_out.append(lg)
    return base_out, org_out, res_out, log_out


def geoalign_broadcast(geo, source_plane, target_plane,
                      rotate_deg=0.0, flip_x=0, flip_y=0, flip_z=0,
                      move_x=0.0, move_y=0.0, move_z=0.0):
    """
    GeoAligner_xfm.align 广播封装：
    - geo/source_plane/target_plane 三者按 broadcast_lists 对齐
    - rotate/flip/move 作为标量（如需列表，请在调用前自行 broadcast）
    返回：(SourceOut_list, TargetOut_list, TransformOut_list, MovedGeo_list)
    """
    from yingzao.ancientArchi import GeoAligner_xfm  # 延迟导入

    geo_l = ensure_list(geo)
    sp_l = ensure_list(source_plane)
    tp_l = ensure_list(target_plane)

    (geo_b, sp_b, tp_b), n = broadcast_lists(geo_l, sp_l, tp_l)

    so_list, to_list, xf_list, mg_list = [], [], [], []
    for i in range(n):
        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                geo_b[i],
                sp_b[i],
                tp_b[i],
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )
        except Exception:
            so, to, xf, mg = None, None, None, None
        so_list.append(so)
        to_list.append(to)
        xf_list.append(xf)
        mg_list.append(mg)
    return so_list, to_list, xf_list, mg_list

def geoalign_broadcast_full(geo, source_plane, target_plane,
                           rotate_deg=0.0, flip_x=0, flip_y=0, flip_z=0,
                           move_x=0.0, move_y=0.0, move_z=0.0):
    """完整广播版 GeoAligner_xfm.align（与旧版 BaTou / ChongGong 风格一致）：

    - Geo / SourcePlane / TargetPlane / RotateDeg / FlipX/Y/Z / MoveX/Y/Z 全部参与广播
    - N 取最大长度，短列表用最后一个值延展（clamp-last）
    返回：(SourceOut_list, TargetOut_list, TransformOut_list, MovedGeo_list)
    """
    from yingzao.ancientArchi import GeoAligner_xfm  # 延迟导入

    rows = broadcast_rows_clamp_last(
        geo, source_plane, target_plane,
        rotate_deg, flip_x, flip_y, flip_z,
        move_x, move_y, move_z
    )

    so_list, to_list, xf_list, mg_list = [], [], [], []
    for (g, sp, tp, rd, fx, fy, fz, mx, my, mz) in rows:
        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                g, sp, tp,
                rotate_deg=rd,
                flip_x=fx,
                flip_y=fy,
                flip_z=fz,
                move_x=mx,
                move_y=my,
                move_z=mz,
            )
        except Exception:
            so, to, xf, mg = None, None, None, None
        so_list.append(so)
        to_list.append(to)
        xf_list.append(xf)
        mg_list.append(mg)
    return so_list, to_list, xf_list, mg_list



def wrap_gh_transform(xf):
    """把 Rhino Transform 包成 GH_Transform（若可用）。"""
    if xf is None:
        return None
    if ght is None:
        return xf
    try:
        return ght.GH_Transform(xf)
    except Exception:
        return xf


# =========================================================
# 参考平面解析（数据库字符串/Plane）
# =========================================================

def resolve_reference_plane(ref, base_point=None):
    """
    把数据库/工程里常见 reference_plane 转成 rg.Plane：
    - 允许传入 rg.Plane
    - 允许传入 'WorldXY' / 'WorldYZ' / 'WorldXZ' / 'XZ'
    - base_point 可用于设置 Origin（不传则保留默认）
    """
    if rg is None:
        return None

    if isinstance(ref, rg.Plane):
        pl = rg.Plane(ref)
        if isinstance(base_point, rg.Point3d):
            pl.Origin = base_point
        return pl

    s = str(ref).strip() if ref is not None else "WorldXY"
    if s == "WorldXY":
        pl = rg.Plane.WorldXY
    elif s == "WorldYZ":
        pl = rg.Plane.WorldYZ
    elif s in ("WorldXZ", "XZ", "WorldZX"):
        pl = world_xz_plane()
    else:
        pl = rg.Plane.WorldXY

    if isinstance(base_point, rg.Point3d):
        pl.Origin = base_point
    return pl



# =========================================================
# 兼容层：保持 DanGong / ChongGong 旧版模板函数名不丢失
# ---------------------------------------------------------
# 说明：
# - 早期按模块抽取时，部分 Solver 代码依赖以下函数名：
#   broadcast_n / broadcast_wrap_rows / xform_plane / xform_planes
#   as_float_or_list / as_01_or_list
#   ft_plane_from_lists_broadcast_wrap / geoalign_broadcast_wrap
# - 为避免“名称覆盖 / 丢失”造成 ImportError，这里提供稳定别名与薄封装。
# - 这些别名**不改变**既有实现，只是把旧名映射到当前通用实现。
# =========================================================

# --- 广播：DanGong 语义（保守：多列表长度不一致时取最小公共长度） ---
try:
    broadcast_n  # type: ignore
except NameError:
    def broadcast_n(*seqs):  # type: ignore
        return broadcast_lists(*seqs)

# --- 广播：ChongGong 语义（wrap：按最长长度，列表用 i % len(list) 循环） ---
try:
    broadcast_wrap_rows  # type: ignore
except NameError:
    def broadcast_wrap_rows(*args):  # type: ignore
        return broadcast_rows(*args)

# --- 类型：标量/列表保持原语义（ChongGong 需要） ---
try:
    as_float_or_list  # type: ignore
except NameError:
    def as_float_or_list(val, default=0.0):  # type: ignore
        if val is None:
            return float(default)
        if isinstance(val, (list, tuple)):
            return [as_float(v, default) for v in val]
        return as_float(val, default)

try:
    as_01_or_list  # type: ignore
except NameError:
    def as_01_or_list(val, default=0):  # type: ignore
        if val is None:
            return int(default)
        if isinstance(val, (list, tuple)):
            return [as_01(v, default) for v in val]
        return as_01(val, default)

# --- Plane / Transform ---
try:
    xform_plane  # type: ignore
except NameError:
    # 旧名：对 Plane 应用 Transform（轴向变换版本）
    def xform_plane(pl, xform):  # type: ignore
        return xform_plane_axes(pl, xform)

try:
    xform_planes  # type: ignore
except NameError:
    def xform_planes(planes, xform):  # type: ignore
        # 兼容旧版：xform 可能是 GH_Transform / Transform / None
        return transform_planes(planes, xform)

# --- PlaneFromLists：wrap 广播版本（ChongGong 需要） ---
try:
    ft_plane_from_lists_broadcast_wrap  # type: ignore
except NameError:
    def ft_plane_from_lists_broadcast_wrap(origin_points, base_planes, index_origin, index_plane, wrap=True):  # type: ignore
        from yingzao.ancientArchi import FTPlaneFromLists  # 延迟导入
        builder = FTPlaneFromLists(wrap=wrap)
        rows = broadcast_wrap_rows(
            index_origin if isinstance(index_origin, (list, tuple)) else [index_origin],
            index_plane if isinstance(index_plane, (list, tuple)) else [index_plane],
        )
        base_out, org_out, res_out, log_out = [], [], [], []
        for (i_o, i_p) in rows:
            try:
                bp, op, rp, lg = builder.build_plane(origin_points, base_planes, i_o, i_p)
            except Exception as e:
                bp, op, rp, lg = None, None, None, ["PFL Error: {}".format(e)]
            base_out.append(bp)
            org_out.append(op)
            res_out.append(rp)
            log_out.append(lg)
        return base_out, org_out, res_out, log_out

# --- GeoAligner：wrap 广播版本（ChongGong 需要） ---
try:
    geoalign_broadcast_wrap  # type: ignore
except NameError:
    def geoalign_broadcast_wrap(  # type: ignore
        Geo, SourcePlane, TargetPlane,
        rotate_deg=0.0, flip_x=0, flip_y=0, flip_z=0,
        move_x=0.0, move_y=0.0, move_z=0.0,
    ):
        from yingzao.ancientArchi import GeoAligner_xfm  # 延迟导入
        rows = broadcast_wrap_rows(
            Geo, SourcePlane, TargetPlane,
            rotate_deg, flip_x, flip_y, flip_z,
            move_x, move_y, move_z,
        )
        so_list, to_list, xf_list, mg_list = [], [], [], []
        for (g, sp, tp, rd, fx, fy, fz, mx, my, mz) in rows:
            try:
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rd,
                    flip_x=fx,
                    flip_y=fy,
                    flip_z=fz,
                    move_x=mx,
                    move_y=my,
                    move_z=mz,
                )
            except Exception:
                so, to, xf, mg = None, None, None, None
            so_list.append(so)
            to_list.append(to)
            xf_list.append(xf)
            mg_list.append(mg)
        return so_list, to_list, xf_list, mg_list






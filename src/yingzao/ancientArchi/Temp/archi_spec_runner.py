# -*- coding: utf-8 -*-
"""
archi_spec_runner.py
------------------------------------------------------------
一个极简但可扩展的 “Spec 驱动 Runner”，用于把 ComponentAssemblySolver 的步骤
从“手写串联逻辑”转为 “取值映射 + 调模板函数”。

核心约定
- "$KEY"     : 从 AllDict（数据库展开后的参数字典）取值
- "@Obj.Attr": 从 Context 取对象/字典的属性/键（Obj 可以是 solver 子对象或节点输出字典）
- 内嵌 op    : inputs 里允许出现 {"op": "...", ...} 形式的小表达式（list_item/transform_planes/resolve_plane）

本 Runner 只做两件事：
1) 解析引用（$ / @ / 内嵌 op），把 inputs 变成实际值
2) 调用 archi_component_templates.py 中的模板函数/工具，并把 outputs 写回 Context 与 solver 成员
"""

from __future__ import division

import traceback

import Rhino.Geometry as rg  # type: ignore

from yingzao.ancientArchi.Temp.archi_component_templates import (  # type: ignore
    default_place_plane,
    read_puzuo_params,
    ensure_list,
    append_flat,
    flatten_items,
    transform_planes,
    ft_plane_from_lists_broadcast,
    geoalign_broadcast,
    geoalign_broadcast_wrap,
    wrap_gh_transform,
    resolve_reference_plane,
    as_float,
    as_01,
    as_01_or_list,
    as_float_or_list,

)

# ------------------------------------------------------------
# 小工具：引用解析
# ------------------------------------------------------------

def _is_str_like(x):
    return isinstance(x, (str, bytes))


def _is_hint_str(x):
    """只把 '$...' 或 '@...' 视为 runner 的引用提示字符串。"""
    if not _is_str_like(x):
        return False
    try:
        s = x.strip()
    except Exception:
        return False
    return s.startswith("$") or s.startswith("@")


def _get_from_obj(obj, attr):
    if obj is None:
        return None
    # dict
    if isinstance(obj, dict):
        return obj.get(attr, None)
    # attribute
    return getattr(obj, attr, None)


def resolve_ref(token, ctx, alldict):
    """解析 "$KEY" / "@Obj.Attr" / 普通值。"""
    if not _is_hint_str(token):
        return token

    s = token.strip()
    if s.startswith("$"):
        k = s[1:]
        return alldict.get(k, None)

    if s.startswith("@"):
        path = s[1:]
        if "." in path:
            obj_name, attr = path.split(".", 1)
        else:
            obj_name, attr = path, None

        obj = ctx.get(obj_name, None)
        if attr is None or attr == "":
            return obj

        # 允许连续点路径：@A.B.C
        cur = obj
        for part in attr.split("."):
            cur = _get_from_obj(cur, part)
        return cur

    return token


def _to_index(idx, default=0):
    """把 idx(None/数值/字符串/列表) 规整成 int。"""
    if isinstance(idx, (list, tuple)):
        idx = idx[0] if len(idx) else default
    try:
        return int(round(float(idx)))
    except Exception:
        return int(default)


def _list_item(lst, idx, wrap=True, default=None):
    """GH List Item 语义：wrap=True 时循环索引；wrap=False 时越界返回 default。"""
    arr = ensure_list(lst)
    if not arr:
        return default

    i = _to_index(idx, 0)

    if wrap:
        # Python 的 % 对负数也可用：-1 % n -> n-1
        return arr[i % len(arr)]

    if i < 0 or i >= len(arr):
        return default
    return arr[i]


def resolve_expr(expr, ctx, alldict):
    """
    解析表达式：
    - 标量/列表/字典递归
    - {"op": "list_item", ...}
    - {"op": "transform_planes", ...}
    - {"op": "resolve_plane", ...}
    """
    # 1) 引用字符串
    if _is_hint_str(expr):
        return resolve_ref(expr, ctx, alldict)

    # 2) 内嵌 op
    if isinstance(expr, dict) and "op" in expr:
        op = expr.get("op")

        if op == "list_item":
            lst = resolve_expr(expr.get("list"), ctx, alldict)
            idx = resolve_expr(expr.get("index"), ctx, alldict)
            wrap = bool(expr.get("wrap", True))
            return _list_item(lst, idx, wrap=wrap, default=None)

        if op == "transform_planes":
            planes = resolve_expr(expr.get("planes"), ctx, alldict)
            xform  = resolve_expr(expr.get("xform"), ctx, alldict)
            return transform_planes(planes, xform)

        if op == "resolve_plane":
            ref = resolve_expr(expr.get("ref"), ctx, alldict)
            bp  = resolve_expr(expr.get("base_point"), ctx, alldict)
            if isinstance(bp, (list, tuple)) and len(bp) >= 3:
                try:
                    bp = rg.Point3d(float(bp[0]), float(bp[1]), float(bp[2]))
                except Exception:
                    bp = None
            return resolve_reference_plane(ref, bp)

        # 未实现的内嵌 op
        return None

    # 3) 容器递归
    if isinstance(expr, (list, tuple)):
        return [resolve_expr(i, ctx, alldict) for i in expr]

    if isinstance(expr, dict):
        return {k: resolve_expr(v, ctx, alldict) for k, v in expr.items()}

    return expr



# ------------------------------------------------------------
# 参数安全默认：当 Spec/DB 中给出 None 时，必须回落到 GH 默认
# 否则会把 None 传入 GeoAligner_xfm 导致整行对位失败（ACT 版不会）
# ------------------------------------------------------------

def _dflt(val, default):
    return default if val is None else val

def _as_float_safe(val, default=0.0):
    try:
        return as_float(_dflt(val, default), default)
    except Exception:
        return float(default)

def _as_01_safe(val, default=0):
    try:
        return as_01(_dflt(val, default), default)
    except Exception:
        return int(default)

def _as_float_or_list_safe(val, default=0.0):
    try:
        return as_float_or_list(val, default)
    except Exception:
        # 最保守：None -> default；list 逐项 float；其他 -> float
        if val is None:
            return float(default)
        if isinstance(val, (list, tuple)):
            out=[]
            for v in val:
                out.append(_as_float_safe(v, default))
            return out
        return _as_float_safe(val, default)

def _as_01_or_list_safe(val, default=0):
    try:
        return as_01_or_list(val, default)
    except Exception:
        if val is None:
            return int(default)
        if isinstance(val, (list, tuple)):
            out=[]
            for v in val:
                out.append(_as_01_safe(v, default))
            return out
        return _as_01_safe(val, default)
# ------------------------------------------------------------
# Runner
# ------------------------------------------------------------

class ArchiSpecRunner(object):
    def __init__(self, solver, alldict, log_lines=None):
        self.solver = solver
        self.alldict = alldict or {}
        self.ctx = {}
        self.log = log_lines if log_lines is not None else []

    # --- 日志
    def _log(self, s):
        try:
            self.log.append(str(s))
        except Exception:
            pass

    # --- 写回
    def _bind_output(self, out_spec, value):
        """
        out_spec:
          "@Obj.Attr" -> 写到 ctx["Obj"].Attr 或 ctx["Obj"][Attr]，
                        并同步到 solver 成员（若 Obj=OUT）
        """
        if not isinstance(out_spec, str) or not out_spec.startswith("@"):
            return

        path = out_spec[1:]
        if "." in path:
            obj_name, attr = path.split(".", 1)
        else:
            obj_name, attr = path, None

        if obj_name not in self.ctx:
            # OUT / DB 之类用 dict 容器
            self.ctx[obj_name] = {}

        obj = self.ctx[obj_name]
        if attr is None:
            self.ctx[obj_name] = value
        else:
            if isinstance(obj, dict):
                obj[attr] = value
            else:
                setattr(obj, attr, value)

        # 同步到 solver（仅 OUT）
        try:
            if obj_name == "OUT" and attr:
                setattr(self.solver, attr, value)
        except Exception:
            pass

    # --- validate（MVP）
    def _validate(self, rules):
        if not rules:
            return True
        ok = True
        for r in rules:
            if isinstance(r, str) and r.startswith("geo_not_none:"):
                ref = r.split(":", 1)[1]
                v = resolve_ref(ref, self.ctx, self.alldict)
                if v is None:
                    ok = False
                    self._log("[VALIDATE] FAIL geo_not_none: {}".format(ref))
        return ok

    # --- solver 实例化：尽可能兼容不同签名
    def _instantiate_solver(self, cls, DBPath, base_point, Refresh):
        ghenv = getattr(self.solver, "ghenv", None)

        # 1) 最接近 ACT 的签名： (DBPath, base_point, Refresh, ghenv)
        try:
            return cls(DBPath, base_point, Refresh, ghenv)
        except Exception:
            pass

        # 2) 常见： (DBPath, base_point, Refresh)
        try:
            return cls(DBPath, base_point, Refresh)
        except Exception:
            pass

        # 3) 关键字： (DBPath=..., base_point=..., Refresh=..., ghenv=...)
        try:
            return cls(DBPath=DBPath, base_point=base_point, Refresh=Refresh, ghenv=ghenv)
        except Exception:
            pass

        # 4) 关键字：无 ghenv
        try:
            return cls(DBPath=DBPath, base_point=base_point, Refresh=Refresh)
        except Exception:
            pass

        # 5) 更“Python 风格”的参数名：db_path / refresh
        try:
            return cls(db_path=DBPath, base_point=base_point, refresh=Refresh, ghenv=ghenv)
        except Exception:
            pass
        try:
            return cls(db_path=DBPath, base_point=base_point, refresh=Refresh)
        except Exception:
            pass

        # 最后：直接无参（极少）
        return cls()

    # --- 执行一个 node
    def run_node(self, node):
        nid = node.get("id", "?")
        op  = node.get("op")
        self._log("[NODE] {} :: {}".format(nid, op))

        try:
            inputs = node.get("inputs", {}) or {}
            inputs_v = resolve_expr(inputs, self.ctx, self.alldict)

            # ========== op 分发 ==========
            if op == "read_puzuo_params":
                db_path = inputs_v.get("db_path")
                type_code = inputs_v.get("type_code")
                table = inputs_v.get("table", "PuZuo")
                field = inputs_v.get("field", "params_json")
                val, all_list, all_dict, db_log = read_puzuo_params(
                    db_path=db_path,
                    type_code=type_code,
                    ghenv=getattr(self.solver, "ghenv", None),
                    table=table,
                    field=field
                )
                outs = {"Value": val, "All": all_list, "AllDict": all_dict, "DBLog": db_log}
                if isinstance(all_dict, dict):
                    self.alldict.update(all_dict)
                result = outs

            elif op == "plane_from_lists":
                base_out, org_out, res_out, lg = ft_plane_from_lists_broadcast(
                    origin_points=inputs_v.get("origin_points"),
                    base_planes=inputs_v.get("base_planes"),
                    index_origin=inputs_v.get("index_origin"),
                    index_plane=inputs_v.get("index_plane"),
                    wrap=bool(inputs_v.get("wrap", True)),
                    tag=inputs_v.get("tag", nid)
                )
                result = {"BasePlane": base_out, "OriginPoint": org_out, "ResultPlane": res_out, "Log": lg}

            elif op == "align":
                # geoalign_broadcast 返回顺序：
                # (SourceOut_list, TargetOut_list, TransformOut_list, MovedGeo_list)
                so_list, to_list, xf_list, mg_list = geoalign_broadcast(
                    geo=inputs_v.get("geo"),
                    source_plane=inputs_v.get("source_plane"),
                    target_plane=inputs_v.get("target_plane"),
                    rotate_deg=_as_float_safe(inputs_v.get("rotate_deg"), 0.0),
                    flip_x=_as_01_safe(inputs_v.get("flip_x"), 0),
                    flip_y=_as_01_safe(inputs_v.get("flip_y"), 0),
                    flip_z=_as_01_safe(inputs_v.get("flip_z"), 0),
                    move_x=_as_float_safe(inputs_v.get("move_x"), 0.0),
                    move_y=_as_float_safe(inputs_v.get("move_y"), 0.0),
                    move_z=_as_float_safe(inputs_v.get("move_z"), 0.0)
                )
                # 统一把 Transform 包装成 GH_Transform（如果环境支持）
                xf_list = [wrap_gh_transform(xf) for xf in ensure_list(xf_list)]
                result = {
                    "MovedGeo": mg_list,
                    "SourceOut": so_list,
                    "TargetOut": to_list,
                    "TransformOut": xf_list
                }

            elif op == "align_wrap":
                # 允许 rotate/flip/move 也为 list（wrap 广播）
                so_list, to_list, xf_list, mg_list = geoalign_broadcast_wrap(
                    Geo=inputs_v.get("geo"),
                    SourcePlane=inputs_v.get("source_plane"),
                    TargetPlane=inputs_v.get("target_plane"),
                    rotate_deg=_as_float_or_list_safe(inputs_v.get("rotate_deg"), 0.0),
                    flip_x=_as_01_or_list_safe(inputs_v.get("flip_x"), 0),
                    flip_y=_as_01_or_list_safe(inputs_v.get("flip_y"), 0),
                    flip_z=_as_01_or_list_safe(inputs_v.get("flip_z"), 0),
                    move_x=_as_float_or_list_safe(inputs_v.get("move_x"), 0.0),
                    move_y=_as_float_or_list_safe(inputs_v.get("move_y"), 0.0),
                    move_z=_as_float_or_list_safe(inputs_v.get("move_z"), 0.0),
                )
                xf_list = [wrap_gh_transform(xf) for xf in ensure_list(xf_list)]
                result = {
                    "MovedGeo": mg_list,
                    "SourceOut": so_list,
                    "TargetOut": to_list,
                    "TransformOut": xf_list
                }

            elif op == "call_solver":
                from yingzao import ancientArchi  # type: ignore

                solver_name = inputs_v.get("solver")
                DBPath = inputs_v.get("db_path")
                bp = inputs_v.get("base_point")
                if isinstance(bp, (list, tuple)) and len(bp) >= 3:
                    bp = rg.Point3d(float(bp[0]), float(bp[1]), float(bp[2]))
                Refresh = inputs_v.get("refresh", getattr(self.solver, "Refresh", False))

                cls = getattr(ancientArchi, solver_name)
                inst = self._instantiate_solver(cls, DBPath, bp, Refresh)

                # run() 可能返回 self，也可能返回其它；以返回值优先
                ret = None
                try:
                    ret = inst.run()
                except Exception:
                    # 少数 solver 用 __call__/其它入口，这里不强行猜，直接抛出给上层捕获
                    raise

                if ret is not None and hasattr(ret, "__dict__"):
                    inst = ret

                result = {"_solver": inst}

            elif op == "build_timber_block_uniform":
                # 直接调用 yingzao.ancientArchi.build_timber_block_uniform（与 ACT 一致）
                from yingzao.ancientArchi import build_timber_block_uniform  # type: ignore

                bp = inputs_v.get("base_point")
                if isinstance(bp, (list, tuple)) and len(bp) >= 3:
                    bp = rg.Point3d(float(bp[0]), float(bp[1]), float(bp[2]))
                ref_pl = inputs_v.get("reference_plane")

                length_fen = as_float(inputs_v.get("length_fen"), 0.0)
                width_fen  = as_float(inputs_v.get("width_fen"), 0.0)
                height_fen = as_float(inputs_v.get("height_fen"), 0.0)

                (
                    timber_brep,
                    face_list,
                    point_list,
                    edge_list,
                    center_pt,
                    center_axis_lines,
                    edge_mid_points,
                    face_plane_list,
                    corner0_planes,
                    local_axes_plane,
                    axis_x, axis_y, axis_z,
                    face_tags, edge_tags, corner0_dirs,
                    log_lines,
                ) = build_timber_block_uniform(length_fen, width_fen, height_fen, bp, ref_pl)

                result = {
                    "TimberBrep": timber_brep,
                    "FacePlaneList": face_plane_list,
                    "EdgeMidPoints": edge_mid_points,
                    "Corner0Planes": corner0_planes,
                    "LogLines": log_lines,
                }

            elif op == "assemble":
                prefer = inputs_v.get("prefer", []) or []
                fallback = inputs_v.get("fallback", []) or []
                do_flatten = bool(inputs_v.get("flatten", True))

                out = []
                for x in prefer:
                    append_flat(out, x)

                if len(out) == 0:
                    for x in fallback:
                        append_flat(out, x)

                if do_flatten:
                    flat = []
                    flatten_items(out, flat)
                    out = flat

                result = {"ComponentAssembly": out}

            else:
                self._log("[NODE] {} unknown op: {}".format(nid, op))
                result = {}

            # ========== outputs 绑定 ==========
            outs_spec = node.get("outputs", {}) or {}
            if outs_spec:
                for k, ref in outs_spec.items():
                    self._bind_output(ref, result.get(k))

            # ctx 中也放一份 node 结果 dict，便于 @Node.Key 引用
            self.ctx[nid] = result

            # validate
            self._validate(node.get("validate"))

            return result

        except Exception as e:
            self._log("[NODE][ERROR] {} :: {}".format(nid, e))
            self._log(traceback.format_exc())
            return {}

    def run_step(self, step_spec):
        step_id = step_spec.get("step", "?")
        self._log("=== RUN STEP {} ===".format(step_id))
        for node in (step_spec.get("nodes") or []):
            self.run_node(node)
        return True

    def run(self, spec):
        for step in (spec.get("steps") or []):
            self.run_step(step)
        return self.ctx


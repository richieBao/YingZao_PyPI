# -*- coding: utf-8 -*-
"""
common_utils
---------------------------------------------------------
交互枓 / 角櫨枓等 Solver 共用的一组通用工具函数，包括：

- 列表广播与长度计算：
    _to_list
    _param_length
    _broadcast_param
    _scalar_from_list

- DBJsonReader 输出 All 结构的处理：
    parse_all_to_dict
    all_get
    to_scalar

- 参考平面构造：
    make_reference_plane

说明：
- 函数名保持原始形式，方便从旧代码中直接替换为模块调用。
- 若不希望下划线前缀，也可以在此模块中额外定义别名。
"""

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

# ======================================================================
# 通用工具函数：列表/广播相关
# ======================================================================
def _to_list(x):
    """若为 list/tuple 则转为 list，否则包装成 [x]。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其他 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


def _broadcast_param(val, n, name="param"):
    """
    广播/截断参数到长度 n（参考 FT_AlignToolToTimber 中的策略）：

    - 若 val 为 list/tuple：
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


def _scalar_from_list(val, default=None):
    """
    将可能为 list/tuple 的值收敛为标量：
    - list/tuple → 第一个元素
    - 其他类型：原样返回，None → default

    仅用于“本来就是标量语义”的参数：
    如 qi_height / sha_width / qi_offset_fen / extrude_length 等；
    不用于 FlipY / BlockRotDeg / IndexOrigin / IndexPlane 等
    需要广播或多次运算的参数。
    """
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) > 0 else default
    return val


# ======================================================================
# DBJsonReader 相关：All → 嵌套字典
# ======================================================================
def parse_all_to_dict(all_list):
    """
    输入：
        all_list = [
            ("FT_AlignToolToTimber_1__FlipY", [...]),
            ("FT_AlignToolToTimber_1__BlockRotDeg", 90),
            ("FT_timber_block_uniform__length_fen", 36),
            ...
        ]

    输出为嵌套 dict：
        {
            "FT_AlignToolToTimber_1": {
                "FlipY": [...],
                "BlockRotDeg": 90
            },
            "FT_timber_block_uniform": {
                "length_fen": 36,
                "width_fen":  36,
                "height_fen": 20,
                "reference_plane": "WorldXZ"
            },
            "PlaneFromLists_1": {
                "IndexOrigin": [...],
                "IndexPlane":  [...],
                "wrap": true
            },
            ...
        }
    """
    result = {}

    if not all_list:
        return result

    for key, value in all_list:
        if "__" not in key:
            comp = key
            param = None
        else:
            comp, param = key.split("__", 1)

        if comp not in result:
            result[comp] = {}

        if param is None:
            result[comp] = value
        else:
            result[comp][param] = value

    return result


def all_get(AllDict, comp_name, param_name, default=None):
    """
    从 AllDict 中获取参数值（组件名 + 参数名）：

        AllDict["FT_timber_block_uniform"]["length_fen"] = 36

    访问方式：
        all_get(AllDict, "FT_timber_block_uniform", "length_fen", 32.0)
    """
    if AllDict is None:
        return default

    comp = AllDict.get(comp_name, None)
    if comp is None or not isinstance(comp, dict):
        return default

    return comp.get(param_name, default)


def to_scalar(val, default=None):
    """
    有些参数在 JSON 中可能写成 [36] 这样的单元素列表。
    为了简化使用，这里把：
        - list/tuple → 取第一个元素（若为空则用 default）
        - 其它标量 → 原样返回
        - None      → default
    """
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        if len(val) == 0:
            return default
        return val[0]
    return val


# ======================================================================
# 工具函数：根据字符串构造参考平面
# ======================================================================
def make_reference_plane(tag=None):
    """
    根据数据库中的字符串构造 GH 参考平面：
        - XY Plane：X = (1,0,0)，Y = (0,1,0)，Z = (0,0,1)
        - XZ Plane：X = (1,0,0)，Y = (0,0,1)，Z = (0,-1,0)
        - YZ Plane：X = (0,1,0)，Y = (0,0,1)，Z = (1,0,0)

    若 tag 为 None 或无法识别，默认使用 XZ Plane。
    """
    origin = rg.Point3d(0.0, 0.0, 0.0)
    if tag is None:
        mode = "XZ"
    else:
        s = str(tag).upper()
        if "XY" in s:
            mode = "XY"
        elif "YZ" in s:
            mode = "YZ"
        else:
            mode = "XZ"

    if mode == "XY":
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
    elif mode == "YZ":
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
    else:  # XZ
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)

    return rg.Plane(origin, x, y)

def normalize_bool_param(val):
    """
    把各种形式的 FlipX/FlipY/FlipZ 输入统一成 list[int] (0/1)。
    “将 Grasshopper 输入的各种数据（标量 / list / DataTree / GH_Goo / 字符串）统一规范化成 list[int]（0/1）” 的函数。
    """
    if val is None:
        return []

    if not isinstance(val, (list, tuple)):
        seq = [val]
    else:
        seq = list(val)

    flat = []
    for v in seq:
        if isinstance(v, (list, tuple)):
            flat.extend(v)
        else:
            flat.append(v)

    result = []
    for v in flat:
        if isinstance(v, ght.IGH_Goo):
            try:
                v = v.ScriptVariable()
            except:
                pass

        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("1", "true", "t", "yes", "y"):
                result.append(1)
                continue
            if s in ("0", "false", "f", "no", "n", ""):
                result.append(0)
                continue
            result.append(1)
            continue

        try:
            iv = int(v)
            result.append(1 if iv != 0 else 0)
        except:
            result.append(1 if v else 0)

    return result
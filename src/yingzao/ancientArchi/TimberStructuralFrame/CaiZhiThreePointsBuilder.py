# -*- coding: utf-8 -*-
"""
CaiZhi_3Pts_ByDirectionAndSpan
从“材栔点列表”中按索引取点，并沿给定方向向量正/反向偏移生成 2 个新点，
再额外取一个点，最终输出 3 个点（用于“三点确定唯一矩形”）。

本版新增输出：
- DirUnit      : rg.Vector3d    （Direction 的单位向量）
- SpanVectors  : list[rg.Vector3d]
    两个方向的 Span 缩放向量，顺序与 OffsetPts 一致：
    OffsetPts = [P_minus, P_plus]
    SpanVectors = [V_minus, V_plus]  # 其中 V_minus = -DirUnit * Span, V_plus = +DirUnit * Span

------------------------------------------------------------
输入（GhPython 建议设置）:
    Direction : rg.Vector3d (Item)
        偏移方向向量（无需单位化；内部会 Normalize）
        若为零向量/无效，将回退为 X 轴方向 (1,0,0)

    CaiZhiPts : rg.Point3d (List)
        材栔点列表（可混入 GH_Point / Point3d；内部尽量转 Point3d）
        若为空，则输出空列表（组件不报错、不变红）

    IndexA : int (Item)
        主索引：从 CaiZhiPts 中提取“基准点” P0
        支持负数；越界会自动 clamp 到 [0, n-1]

    Span : float / list[float] (Item / List)
        支撑点跨距（偏移距离）
        - 若 Span 为单值：正/反向偏移距离相同
            P_plus  = P0 + DirUnit * Span
            P_minus = P0 - DirUnit * Span
        - 若 Span 为列表且长度>=2：分别控制两侧偏移距离
            Span[0] -> +Direction 的偏移距离（P_plus）
            Span[1] -> -Direction 的偏移距离（P_minus）
        若 Span 无效则按 0 处理

    IndexB : int (Item)
        额外索引：从 CaiZhiPts 中提取“额外点” P_extra
        规则同 IndexA

输出:
    PointList : list[rg.Point3d]
        三点列表，顺序为: [P_extra, P_minus, P_plus]

    BasePoint : rg.Point3d
        P0（IndexA 提取的基准点）

    OffsetPts : list[rg.Point3d]
        [P_minus, P_plus]

    ExtraPoint : rg.Point3d
        P_extra（IndexB 提取的额外点）

    DirUnit : rg.Vector3d
        Direction 的单位向量（兜底后）

    SpanVectors : list[rg.Vector3d]
        与 OffsetPts 同序: [V_minus, V_plus]
        V_minus = -DirUnit * Span
        V_plus  = +DirUnit * Span
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg


# -------------------------
# 工具函数
# -------------------------
def _first_item(x):
    """GH 可能把 Item 也包成单元素 list，这里统一取第一个。"""
    if x is None:
        return None
    try:
        if hasattr(x, "__iter__") and not isinstance(x, (str, rg.Point3d, rg.Vector3d)):
            x = list(x)
            if len(x) > 0:
                return x[0]
            return None
    except:
        pass
    return x


def _to_float(x, default=0.0):
    x = _first_item(x)
    if x is None:
        return default
    try:
        return float(x)
    except:
        return default


def _to_float_list(x):
    """尽量把 x 转成 list[float]；常见情况：Item / List / tuple / GH_Structure。"""
    if x is None:
        return []
    # RhinoCommon 数值不会走这里；str 也当作单值
    if isinstance(x, (int, float)):
        return [float(x)]
    if isinstance(x, (str,)):
        try:
            return [float(x)]
        except:
            return []
    try:
        if hasattr(x, "__iter__"):
            vals = []
            for it in list(x):
                try:
                    vals.append(float(it))
                except:
                    # 跳过无效项
                    continue
            return vals
    except:
        pass
    # 兜底：按单值尝试
    try:
        return [float(x)]
    except:
        return []


def _parse_span(span, default=0.0):
    """Span 规则:
    - 若 Span 为单值：正/反向偏移距离相同
    - 若 Span 为列表且长度>=2：Span[0] 用于 +Direction，Span[1] 用于 -Direction
    返回: (span_plus, span_minus)
    """
    vals = _to_float_list(span)
    if len(vals) >= 2:
        return vals[0], vals[1]
    if len(vals) == 1:
        return vals[0], vals[0]
    return default, default



def _to_int(x, default=0):
    x = _first_item(x)
    if x is None:
        return default
    try:
        return int(x)
    except:
        try:
            return int(float(x))
        except:
            return default


def _to_point3d(p):
    """尽量把各种点类型转为 rg.Point3d；失败返回 None。"""
    if p is None:
        return None
    if isinstance(p, rg.Point3d):
        return p
    try:
        if hasattr(p, "X") and hasattr(p, "Y") and hasattr(p, "Z"):
            return rg.Point3d(float(p.X), float(p.Y), float(p.Z))
    except:
        pass
    return None


def _to_point_list(pts):
    """把输入点列表尽量转成 list[rg.Point3d]，过滤无效项。"""
    if pts is None:
        return []
    try:
        if isinstance(pts, rg.Point3d):
            return [pts]
        if hasattr(pts, "__iter__") and not isinstance(pts, (str,)):
            out = []
            for it in list(pts):
                p = _to_point3d(it)
                if p is not None:
                    out.append(p)
            return out
    except:
        pass
    p = _to_point3d(pts)
    return [p] if p is not None else []


def _safe_index(i, n):
    """把 i clamp 到 [0, n-1]；n<=0 时返回 None。"""
    if n <= 0:
        return None
    if i < 0:
        i = n + i
    if i < 0:
        i = 0
    if i > n - 1:
        i = n - 1
    return i


def _safe_direction(v):
    """确保方向向量可用，返回单位向量（rg.Vector3d）。"""
    v = _first_item(v)
    if v is None:
        return rg.Vector3d(1, 0, 0)

    if isinstance(v, rg.Vector3d):
        vec = rg.Vector3d(v)
    else:
        try:
            if hasattr(v, "X") and hasattr(v, "Y") and hasattr(v, "Z"):
                vec = rg.Vector3d(float(v.X), float(v.Y), float(v.Z))
            else:
                vec = rg.Vector3d(1, 0, 0)
        except:
            vec = rg.Vector3d(1, 0, 0)

    if vec.IsZero:
        return rg.Vector3d(1, 0, 0)

    vec.Unitize()
    return vec


# -------------------------
# 核心类
# -------------------------
class CaiZhiThreePointsBuilder(object):
    """
    P0 = CaiZhiPts[IndexA]
    P_minus = P0 + (-DirUnit) * Span
    P_plus  = P0 + (+DirUnit) * Span
    P_extra = CaiZhiPts[IndexB]

    OffsetPts   = [P_minus, P_plus]
    SpanVectors = [V_minus, V_plus]  # 与 OffsetPts 同序
    PointList   = [P_extra, P_minus, P_plus]
    """

    def __init__(self, caizhi_pts, index_a=0, index_b=0, direction=None, span=0.0):
        self.caizhi_pts = _to_point_list(caizhi_pts)
        self.index_a = _to_int(index_a, 0)
        self.index_b = _to_int(index_b, 0)
        self.dir_unit = _safe_direction(direction)
        self.span_raw = span

        self.base_point = None
        self.extra_point = None
        self.offset_pts = []
        self.span_vectors = []
        self.point_list = []

    def build(self):
        """
        返回:
            point_list   : list[rg.Point3d]  = [P_extra, P_minus, P_plus]
            base_point   : rg.Point3d or None
            offset_pts   : list[rg.Point3d]  = [P_minus, P_plus]
            extra_point  : rg.Point3d or None
            dir_unit     : rg.Vector3d
            span_vectors : list[rg.Vector3d] = [V_minus, V_plus]  # 与 offset_pts 同序
        """
        n = len(self.caizhi_pts)
        if n == 0:
            self.point_list = []
            self.base_point = None
            self.offset_pts = []
            self.extra_point = None
            self.span_vectors = []
            return (self.point_list, self.base_point, self.offset_pts,
                    self.extra_point, self.dir_unit, self.span_vectors)

        ia = _safe_index(self.index_a, n)
        ib = _safe_index(self.index_b, n)

        self.base_point = self.caizhi_pts[ia]
        self.extra_point = self.caizhi_pts[ib]

        # Span 解析：
        # - 单值：正/反向相同
        # - 列表(>=2)：Span[0] -> +Direction，Span[1] -> -Direction
        span_plus, span_minus = _parse_span(self.span_raw, default=0.0)

        # V_plus / V_minus（顺序要与 OffsetPts 一致：先 minus 再 plus）
        v_plus = rg.Vector3d(self.dir_unit)
        v_plus *= span_plus

        v_minus = rg.Vector3d(self.dir_unit)
        v_minus *= -span_minus

        # P_plus / P_minus
        p_plus = rg.Point3d(self.base_point)
        p_plus += v_plus

        p_minus = rg.Point3d(self.base_point)
        p_minus += v_minus

        self.offset_pts = [p_minus, p_plus]
        self.span_vectors = [v_minus, v_plus]  # 与 offset_pts 同序
        self.point_list = [self.extra_point, p_minus, p_plus]

        return (self.point_list, self.base_point, self.offset_pts,
                self.extra_point, self.dir_unit, self.span_vectors)

if __name__ == "__main__":
    # -------------------------
    # GhPython 入口（把下面变量名与 GH 端口名对应）
    # -------------------------
    # 期望 GH 输入变量名：
    #   Direction, CaiZhiPts, IndexA, Span, IndexB

    builder = CaiZhiThreePointsBuilder(
        caizhi_pts=CaiZhiPts,
        index_a=IndexA,
        index_b=IndexB,
        direction=Direction,
        span=Span
    )

    PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder.build()

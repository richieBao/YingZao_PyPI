# -*- coding: utf-8 -*-
"""
SpanOffset_3Pts_FromTwoPoints
给定一个基准点 BasePoint（原 IndexA 对应点）、一个额外点 ExtraPoint（原 IndexB 对应点），
以及方向向量 Direction 和跨距 Span，
沿 Direction 的正/反向分别偏移 BasePoint 生成两个点，最终输出 3 个点（用于“三点确定唯一矩形”）。

------------------------------------------------------------
输入（GhPython 建议设置）:
    Direction : rg.Vector3d (Item)
        偏移方向向量（无需单位化；内部会 Normalize）
        若为零向量/无效，将回退为 X 轴方向 (1,0,0)
        Access: Item
        TypeHints: Vector3d

    BasePoint : rg.Point3d (Item)
        基准点（替代原 CaiZhiPts[IndexA]）
        Access: Item
        TypeHints: Point3d

    Span : float / list[float] (Item / List)
        支撑点跨距（偏移距离）
        - 若 Span 为单值：正/反向偏移距离相同
            P_plus  = BasePoint + DirUnit * Span
            P_minus = BasePoint - DirUnit * Span
        - 若 Span 为列表且长度>=2：分别控制两侧偏移距离
            Span[0] -> +Direction 的偏移距离（P_plus）
            Span[1] -> -Direction 的偏移距离（P_minus）
        若 Span 无效则按 0 处理
        Access: Item (或 List)
        TypeHints: float

    ExtraPoint : rg.Point3d (Item)
        额外点（替代原 CaiZhiPts[IndexB]）
        Access: Item
        TypeHints: Point3d

输出（GhPython 组件输出端）:
    PointList : list[rg.Point3d] (List)
        三点列表，顺序为: [ExtraPoint, P_minus, P_plus]
        Access: List
        TypeHints: Point3d

    BasePoint_Out : rg.Point3d (Item)
        输出基准点（兜底转换后的 BasePoint）
        Access: Item
        TypeHints: Point3d

    OffsetPts : list[rg.Point3d] (List)
        [P_minus, P_plus]
        Access: List
        TypeHints: Point3d

    ExtraPoint_Out : rg.Point3d (Item)
        输出额外点（兜底转换后的 ExtraPoint）
        Access: Item
        TypeHints: Point3d

    DirUnit : rg.Vector3d (Item)
        Direction 的单位向量（兜底后）
        Access: Item
        TypeHints: Vector3d

    SpanVectors : list[rg.Vector3d] (List)
        与 OffsetPts 同序: [V_minus, V_plus]
        V_minus = -DirUnit * Span_minus
        V_plus  = +DirUnit * Span_plus
        Access: List
        TypeHints: Vector3d
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg


# -------------------------
# 工具函数（沿用原脚手架风格，适配 GH 的 Item/List 混入）
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


def _to_float_list(x):
    """尽量把 x 转成 list[float]；常见情况：Item / List / tuple / GH_Structure。"""
    if x is None:
        return []
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
                    continue
            return vals
    except:
        pass
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


def _to_point3d(p):
    """尽量把各种点类型转为 rg.Point3d；失败返回 None。"""
    p = _first_item(p)
    if p is None:
        return None
    if isinstance(p, rg.Point3d):
        return rg.Point3d(p)
    try:
        if hasattr(p, "X") and hasattr(p, "Y") and hasattr(p, "Z"):
            return rg.Point3d(float(p.X), float(p.Y), float(p.Z))
    except:
        pass
    return None


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
# 核心类（新命名）
# -------------------------
class SpanOffsetThreePointsFromTwoPoints(object):
    """
    BasePoint -> 沿 Direction 正/反向偏移 Span，得到 P_plus / P_minus
    ExtraPoint -> 作为输出三点列表的第一个点

    OffsetPts   = [P_minus, P_plus]
    SpanVectors = [V_minus, V_plus]  # 与 OffsetPts 同序
    PointList   = [ExtraPoint, P_minus, P_plus]
    """

    def __init__(self, base_point=None, extra_point=None, direction=None, span=0.0):
        self.base_point_in = base_point
        self.extra_point_in = extra_point
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
            point_list      : list[rg.Point3d]  = [ExtraPoint, P_minus, P_plus]
            base_point_out  : rg.Point3d or None
            offset_pts      : list[rg.Point3d]  = [P_minus, P_plus]
            extra_point_out : rg.Point3d or None
            dir_unit        : rg.Vector3d
            span_vectors    : list[rg.Vector3d] = [V_minus, V_plus]  # 与 offset_pts 同序
        """
        bp = _to_point3d(self.base_point_in)
        ep = _to_point3d(self.extra_point_in)

        # 兜底：任何关键点缺失，都不让组件变红，输出空/None
        if bp is None or ep is None:
            self.point_list = []
            self.base_point = bp
            self.extra_point = ep
            self.offset_pts = []
            self.span_vectors = []
            return (self.point_list, self.base_point, self.offset_pts,
                    self.extra_point, self.dir_unit, self.span_vectors)

        self.base_point = bp
        self.extra_point = ep

        # Span 解析：Span[0] -> +Direction，Span[1] -> -Direction
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
        self.span_vectors = [v_minus, v_plus]
        self.point_list = [self.extra_point, p_minus, p_plus]

        return (self.point_list, self.base_point, self.offset_pts,
                self.extra_point, self.dir_unit, self.span_vectors)


if __name__ == "__main__":
    # -------------------------
    # GhPython 入口（把下面变量名与 GH 端口名对应）
    # -------------------------
    # 期望 GH 输入变量名：
    #   Direction, BasePoint, Span, ExtraPoint
    #
    builder = SpanOffsetThreePointsFromTwoPoints(
        base_point=BasePoint,
        extra_point=ExtraPoint,
        direction=Direction,
        span=Span
    )

    PointList, BasePoint_Out, OffsetPts, ExtraPoint_Out, DirUnit, SpanVectors = builder.build()

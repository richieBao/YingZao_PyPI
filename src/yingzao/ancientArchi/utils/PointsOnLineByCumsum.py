# -*- coding: utf-8 -*-
"""
ListValues -> Line -> Points Extractor
把“列表的累计和”映射到一根线段上，提取对应点（从起点沿方向累计距离取点）。

------------------------------------------------------------
输入（GhPython 建议设置）:
    Values : float (List)
        多个数值（可混入 int/float/str；会尽量转为 float；无效项会跳过或当 0）
        例: [5,3,1,0]

    BasePoint : rg.Point3d (Item)
        线段起点（定位点）

    Direction : rg.Vector3d (Item)
        线段方向（不要求单位化；内部会 Normalize）

输出:
    BaseLine     : rg.Line
        由 BasePoint + Direction * sum(Values) 生成的线段

    SumValue     : float
        Values 的总和，用作线段长度

    ReversedList : list[float]
        Values 反向后的列表（例: [0,1,3,5]）

    CumList      : list[float]
        反向列表的累计和（例: [0,1,4,9]）

    PointList    : list[rg.Point3d]
        在 BaseLine 上按 CumList 距离取出的点（超出线段长度会被 Clamp 到端点）
------------------------------------------------------------

用法：
    builder = PointsOnLineByCumsum(Values, BasePoint, Direction)
    BaseLine, SumValue, ReversedList, CumList, PointList = builder.build()
"""

import Rhino
import Rhino.Geometry as rg


class PointsOnLineByCumsum(object):
    def __init__(self, values, base_point, direction, clamp=True):
        """
        Args:
            values: list-like
            base_point: rg.Point3d
            direction: rg.Vector3d
            clamp: bool  超出线段长度时是否钳制到端点
        """
        self.values_in = values
        self.base_point = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d.Unset
        self.direction_in = direction if isinstance(direction, rg.Vector3d) else rg.Vector3d.Unset
        self.clamp = clamp

        self.values = []
        self.sum_value = 0.0
        self.rev_list = []
        self.cum_list = []
        self.base_line = rg.Line.Unset
        self.points = []

    # ----------------- public -----------------
    def build(self):
        self._prepare_values()
        self._build_line()
        self._compute_reverse_and_cumsum()
        self._extract_points()
        return self.base_line, self.sum_value, self.rev_list, self.cum_list, self.points

    # ----------------- internal -----------------
    def _first_item(self, x):
        """GH 可能传 list/tuple；取第一个"""
        if isinstance(x, (list, tuple)):
            return x[0] if len(x) > 0 else None
        return x

    def _to_float(self, x, default=0.0):
        """尽量把输入转为 float；失败则给 default"""
        try:
            if x is None:
                return default
            # GH 可能传 Guid / goo：先取 first
            x = self._first_item(x)
            if isinstance(x, bool):
                return float(int(x))
            return float(x)
        except:
            return default

    def _prepare_values(self):
        """把 Values 规整成 list[float]"""
        v = self.values_in
        if v is None:
            self.values = []
        elif isinstance(v, (list, tuple)):
            self.values = [self._to_float(i, 0.0) for i in v]
        else:
            # 允许单值进来
            self.values = [self._to_float(v, 0.0)]

        self.sum_value = sum(self.values) if self.values else 0.0

    def _build_line(self):
        """用 BasePoint + Direction * sum 构建线段"""
        if self.base_point == rg.Point3d.Unset:
            self.base_line = rg.Line.Unset
            return

        d = self.direction_in
        if d == rg.Vector3d.Unset or d.IsTiny():
            # 方向无效时，给一个零长度线段，避免组件报错
            self.base_line = rg.Line(self.base_point, self.base_point)
            return

        d2 = rg.Vector3d(d)
        d2.Unitize()
        end_pt = self.base_point + d2 * self.sum_value
        self.base_line = rg.Line(self.base_point, end_pt)

    def _compute_reverse_and_cumsum(self):
        """反向 + 累计和"""
        self.rev_list = list(reversed(self.values)) if self.values else []
        cum = 0.0
        self.cum_list = []
        for x in self.rev_list:
            cum += x
            self.cum_list.append(cum)

        # 你的示例希望第一个就是 0 的话（当 rev_list 首项为 0 时自然满足）
        # 如果你希望强制在最前插入 0，可用：
        # self.cum_list = [0.0] + self.cum_list

    def _extract_points(self):
        """按 cum_list 距离从线段起点取点"""
        self.points = []
        if not self.base_line.IsValid:
            return

        total_len = self.base_line.Length
        if total_len <= 0:
            # 零长度线段：所有点都是起点
            self.points = [self.base_line.From] * (len(self.cum_list) if self.cum_list else 0)
            return

        for dist in self.cum_list:
            dd = float(dist)
            if self.clamp:
                if dd < 0.0:
                    dd = 0.0
                if dd > total_len:
                    dd = total_len
            # Line.PointAt(t) 需要 0..1 参数
            t = dd / total_len
            pt = self.base_line.PointAt(t)
            self.points.append(pt)

if __name__ == "__main__":
    # ----------------- GH component execution -----------------
    # 约定你的输入端名称：Values, BasePoint, Direction
    # 输出端名称：BaseLine, SumValue, ReversedList, CumList, PointList

    builder = PointsOnLineByCumsum(Values, BasePoint, Direction, clamp=True)
    BaseLine, SumValue, ReversedList, CumList, PointList = builder.build()

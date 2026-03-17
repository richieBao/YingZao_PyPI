# -*- coding: utf-8 -*-
"""FT_YinCornerToolPlane

根据给出的对角线和刀具宽度，计算两端
“对象满刀宽后再廕 Yin 分°” 的刀具面参考平面。

几何逻辑：

- 假定角部两边互相垂直，对角线为 45°；
- 根据 ShapeMode 选择不同对象：
    0: 方形
        通过图纸反算可知：
        满刀宽时沿对角线推进量 d_full = ToolWidth / 2
        offset = d_full + Yin = ToolWidth / 2 + Yin
    1: 圆形（修正后的逻辑）
        1) 以对角线为正方形对角线，边长 S 满足 L = S*sqrt(2)；
        2) 圆直径 D = S，半径 R = D/2 = L/(2*sqrt(2))；
        3) 角点到圆心沿对角线距离 = L/2；
        4) 刀具宽 W 垂直对角线，中心在距圆心 s0 处：
               s0^2 + (W/2)^2 = R^2
               s0 = sqrt(R^2 - (W/2)^2)
        5) 从角点到刀具面的推进量：
               offset = L/2 - s0 + Yin

- 在 offset 处构造法线 ∥ 对角线的平面，即刀具面的参考平面。
  两端各做一次。

输入（在 GhPython 组件中设置）:
    Diag        : 对角线（Line / LineCurve / 线性 Curve）
    ToolWidth   : 刀具宽度（分°），默认 10.0
    Yin         : 廕值（分°），默认 0.5
    ShapeMode   : 对象模式 (int)
                  0 = 方形
                  1 = 圆形

输出:
    ToolPlanes  : list[rg.Plane]，长度 2（起点侧 + 终点侧）
    Log         : list[str] 调试信息
"""

import Rhino.Geometry as rg
import math


class YinCornerToolPlaneCalculator(object):
    """廕特征刀具参考平面计算器（支持方形 / 圆形两种模式）。"""

    def __init__(self, diag, tool_width=10.0, yin=0.5, shape_mode=0):
        self.diag_raw = diag
        self.tool_width = float(tool_width) if tool_width is not None else 10.0
        self.yin = float(yin) if yin is not None else 0.5
        self.shape_mode = int(shape_mode) if shape_mode is not None else 0
        self.log = []
        self.line = None   # LineCurve
        self.length = 0.0  # 对角线长度

    # ---------- 工具函数 ----------

    def _coerce_linecurve(self):
        """尝试把输入对角线统一转换为 LineCurve。"""
        obj = self.diag_raw
        if obj is None:
            return None

        if isinstance(obj, rg.LineCurve):
            return obj

        if isinstance(obj, rg.Line):
            return rg.LineCurve(obj)

        if isinstance(obj, rg.PolylineCurve):
            if obj.PointCount >= 2:
                p0 = obj.Point(0)
                p1 = obj.Point(obj.PointCount - 1)
                return rg.LineCurve(p0, p1)
            return None

        if isinstance(obj, rg.Curve):
            if obj.IsLinear():
                return rg.LineCurve(obj.PointAtStart, obj.PointAtEnd)
            return None

        return None

    def _point_and_tangent_at_length(self, s):
        """按弧长 s（从起点量起）在对角线上取点和切向量。"""
        lc = self.line
        if lc is None:
            return None, None

        L = self.length
        if L <= 0.0:
            return None, None

        # clamp
        if s < 0.0:
            s = 0.0
        if s > L:
            s = L

        ok, t = lc.LengthParameter(s)
        if not ok:
            t = s / L

        pt = lc.PointAt(t)
        tan = lc.TangentAt(t)
        if not tan.IsZero:
            tan.Unitize()
        return pt, tan

    # ---------- offset 计算 ----------

    def _compute_offset_square(self):
        """
        方形模式：

        根据图纸尺寸关系（方36，对角线中段39.9，两端各廕0.5），
        可反推“满刀宽”时沿对角线推进量为 ToolWidth / 2。

        因此：
            d_full = ToolWidth / 2
            offset = d_full + Yin
        """
        base = self.tool_width * 0.5
        offset = base + self.yin

        self.log.append(
            "[方形] 几何：d_full = ToolWidth / 2 = {:.3f}".format(base)
        )
        self.log.append(
            "[方形] offset = d_full + Yin = {:.3f} + {:.3f} = {:.3f}".format(
                base, self.yin, offset
            )
        )
        return offset

    def _compute_offset_circle(self):
        """
        圆形模式（修正版）：

        1) 对角线 L -> 构造正方形边长 S，满足 L = S*sqrt(2)
        2) 圆直径 D = S，半径 R = D/2 = L/(2*sqrt(2))
        3) 角点到圆心距离 = L/2
        4) 刀具宽 W 垂直对角线，中心在距圆心 s0 处：
               s0^2 + (W/2)^2 = R^2
               s0 = sqrt(R^2 - (W/2)^2)
        5) 从角点到刀具面的总推进量：
               offset = L/2 - s0 + Yin
        """
        L = self.length
        W = self.tool_width

        R = L / (2.0 * math.sqrt(2.0))
        self.log.append("[圆] 对角线 L = {:.3f}".format(L))
        self.log.append("[圆] 半径 R = L / (2*sqrt(2)) = {:.3f}".format(R))

        half_w = W * 0.5
        if half_w >= R:
            self.log.append(
                "[圆][警告] ToolWidth/2 >= R，调整半宽为略小于 R。"
            )
            half_w = R * 0.999

        val = R * R - half_w * half_w
        if val < 0.0:
            self.log.append(
                "[圆][警告] R^2 - (W/2)^2 < 0，强制设为 0。"
            )
            val = 0.0

        s0 = math.sqrt(val)          # 刀具中心平面距圆心的距离（沿对角线）
        d_full = (L * 0.5) - s0      # 角点 -> 满刀宽平面推进量
        offset = d_full + self.yin   # 再廕 Yin

        self.log.append(
            "[圆] s0 = sqrt(R^2 - (W/2)^2) = {:.3f}".format(s0)
        )
        self.log.append(
            "[圆] d_full = L/2 - s0 = {:.3f} - {:.3f} = {:.3f}".format(
                L * 0.5, s0, d_full
            )
        )
        self.log.append(
            "[圆] offset = d_full + Yin = {:.3f} + {:.3f} = {:.3f}".format(
                d_full, self.yin, offset
            )
        )

        return offset

    def _compute_offset(self):
        """
        根据 ShapeMode 计算每端沿对角线推进的距离 offset，
        并保证 2*offset <= L。
        """
        mode = 0 if self.shape_mode is None else int(self.shape_mode)
        if mode not in (0, 1):
            self.log.append("ShapeMode 非 0/1，自动采用 0(方形)。")
            mode = 0
        self.shape_mode = mode

        if mode == 0:
            self.log.append("当前模式: 0 = 方形对象。")
            offset = self._compute_offset_square()
        else:
            self.log.append("当前模式: 1 = 圆对象。")
            offset = self._compute_offset_circle()

        if self.length > 0.0 and offset * 2.0 > self.length:
            self.log.append(
                "警告：2 * offset ({:.3f}) > L ({:.3f})，自动限制 offset = L / 2。".format(
                    2.0 * offset, self.length
                )
            )
            offset = self.length * 0.5

        return offset

    # ---------- 主计算 ----------

    def run(self):
        """执行计算，返回 (tool_planes, log)。"""
        self.line = self._coerce_linecurve()
        if self.line is None:
            self.log.append("错误：Diag 无法转换为直线（LineCurve）。")
            return [], self.log

        self.length = self.line.GetLength()
        self.log.append("对角线长度 L = {:.3f}".format(self.length))
        self.log.append("刀具宽度 ToolWidth = {:.3f}".format(self.tool_width))
        self.log.append("廕值 Yin = {:.3f}".format(self.yin))

        if self.length <= 0.0:
            self.log.append("错误：对角线长度为 0。")
            return [], self.log

        offset = self._compute_offset()

        planes = []

        # 起点侧
        pt0, tan0 = self._point_and_tangent_at_length(offset)
        if pt0 is None or tan0 is None or tan0.IsZero:
            self.log.append("错误：起点侧位置计算失败。")
        else:
            plane0 = rg.Plane(pt0, tan0)  # 法线 ∥ 对角线
            planes.append(plane0)
            self.log.append("起点侧刀具面参考平面已生成。")

        # 终点侧
        pt1, tan1 = self._point_and_tangent_at_length(self.length - offset)
        if pt1 is None or tan1 is None or tan1.IsZero:
            self.log.append("错误：终点侧位置计算失败。")
        else:
            plane1 = rg.Plane(pt1, tan1)
            planes.append(plane1)
            self.log.append("终点侧刀具面参考平面已生成。")

        return planes, self.log

if __name__ == "__main__":
    # ==========================================================
    # 组件入口：调用类并输出结果
    # ==========================================================

    if ToolWidth is None:
        ToolWidth = 10.0
    if Yin is None:
        Yin = 0.5
    if 'ShapeMode' not in globals() or ShapeMode is None:
        ShapeMode = 0   # 默认方形模式

    calc = YinCornerToolPlaneCalculator(Diag, ToolWidth, Yin, ShapeMode)
    ToolPlanes, Log = calc.run()

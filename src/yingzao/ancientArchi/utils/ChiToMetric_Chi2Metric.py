# -*- coding: utf-8 -*-
"""
ChiToMetric_Chi2Metric
把“尺(Chi)”按配置 ChiToCm（默认 31.2 cm/尺）换算为：m / cm / mm

------------------------------------------------------------
输入（GhPython 建议设置）:
    Chi : float (Item)
        尺数（可为 float / int / str；也允许 list/树，取第一个可用值）
        Access: Item
        TypeHints: float

    ChiToCm : float (Item)
        1 尺 = ? cm（默认 31.2）
        可为 float / int / str；也允许 list/树，取第一个可用值
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    M : float (Item)
        米
        Access: Item
        TypeHints: float

    CM : float (Item)
        厘米
        Access: Item
        TypeHints: float

    MM : float (Item)
        毫米
        Access: Item
        TypeHints: float
------------------------------------------------------------

用法（在 GhPython 中）:
    converter = ChiToMetric_Chi2Metric(Chi, ChiToCm)
    M, CM, MM = converter.convert()

注意：
- 若输入为空或无法解析，将输出 0.0，并尽量避免组件变红。
"""

from __future__ import division

class ChiToMetric_Chi2Metric(object):
    def __init__(self, chi, chi_to_cm=31.2, tol=1e-12):
        self.tol = tol
        self.chi = self._to_float_first(chi, default=0.0)
        self.chi_to_cm = self._to_float_first(chi_to_cm, default=31.2)

        # 防御：配置为 0 或负数时回退默认
        if abs(self.chi_to_cm) <= self.tol or self.chi_to_cm < 0:
            self.chi_to_cm = 31.2

    # ---------- 公共方法 ----------
    def convert(self):
        """
        返回:
            m  : float
            cm : float
            mm : float
        """
        cm = self.chi * self.chi_to_cm
        mm = cm * 10.0
        m = cm / 100.0
        return m, cm, mm

    # ---------- 内部工具 ----------
    def _to_float_first(self, x, default=0.0):
        """
        允许 x 为:
        - 数值 / 字符串
        - list/tuple/set
        - Grasshopper DataTree / 其它可迭代对象（尽量取第一个元素）
        """
        if x is None:
            return float(default)

        # 尝试把 GH 的 DataTree / 迭代对象“取第一个”
        try:
            # 常见：list/tuple
            if isinstance(x, (list, tuple)):
                if len(x) == 0:
                    return float(default)
                return self._to_float_first(x[0], default=default)

            # 其它可迭代（但排除字符串）
            if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
                try:
                    it = iter(x)
                    first = next(it, None)
                    if first is None:
                        return float(default)
                    return self._to_float_first(first, default=default)
                except Exception:
                    pass
        except Exception:
            pass

        # 解析数值/字符串
        try:
            if isinstance(x, bool):
                return float(int(x))
            if isinstance(x, (int, float)):
                return float(x)

            s = str(x).strip()
            if s == "":
                return float(default)

            # 允许 "31.2cm" 这种，尽量抽取数字
            # 只保留 0-9 . - + e E
            cleaned = []
            for ch in s:
                if ch.isdigit() or ch in ".-+eE":
                    cleaned.append(ch)
            s2 = "".join(cleaned).strip()
            if s2 in ("", "+", "-", ".", "+.", "-."):
                return float(default)
            return float(s2)
        except Exception:
            return float(default)

if __name__ == "__main__":
    # -------------------------
    # 输出绑定区（GhPython 组件底部）
    # -------------------------
    try:
        _converter = ChiToMetric_Chi2Metric(Chi, ChiToCm)
        M, CM, MM = _converter.convert()
    except Exception:
        M, CM, MM = 0.0, 0.0, 0.0

# -*- coding: utf-8 -*-
"""
RightTriangleSolver.py

功能:
    直角三角形边长计算工具。
    输入端为一个斜边和两个直角边。
    当三边中任意给定两个边长时，自动计算第三个未知边长。

适用场景:
    1. GhPython 组件中直接调用；
    2. 作为后续更大几何/构件脚本中的基础计算模块；
    3. 便于封装复用、单元测试、自动生成 GH 输入输出端参数。

------------------------------------------------------------
输入（GhPython 建议设置）:
    Hypotenuse : float
        Access = Item
        TypeHint = float
        斜边长度。
        若为未知边，可输入 0，或不赋有效值。

    LegA : float
        Access = Item
        TypeHint = float
        直角边 A 的长度。
        若为未知边，可输入 0，或不赋有效值。

    LegB : float
        Access = Item
        TypeHint = float
        直角边 B 的长度。
        若为未知边，可输入 0，或不赋有效值。

输出:
    OutHypotenuse : float
        计算后的斜边长度；若计算失败则为 None。

    OutLegA : float
        计算后的直角边 A 长度；若计算失败则为 None。

    OutLegB : float
        计算后的直角边 B 长度；若计算失败则为 None。

    UnknownName : str
        被求解的未知边名称。
        取值可能为:
            "Hypotenuse"
            "LegA"
            "LegB"
            ""
        若输入非法，则可能为空字符串。

    KnownCount : int
        已知边数量。
        合法求解时应为 2。

    Formula : str
        本次计算所使用的公式说明。

    IsValid : bool
        是否成功完成计算。

    Status : str
        运行状态与错误信息说明。
------------------------------------------------------------

勾股定理:
    c^2 = a^2 + b^2

其中:
    c = Hypotenuse
    a = LegA
    b = LegB
"""

import math


class RightTriangleResult(object):
    """
    直角三角形求解结果对象。
    用于统一返回求解结果，便于后续调用。
    """

    def __init__(self):
        self.hypotenuse = None
        self.leg_a = None
        self.leg_b = None
        self.unknown_name = ""
        self.known_count = 0
        self.formula = ""
        self.is_valid = False
        self.status = ""

    def to_dict(self):
        """
        转为字典，便于调试或后续序列化。
        """
        return {
            "hypotenuse": self.hypotenuse,
            "leg_a": self.leg_a,
            "leg_b": self.leg_b,
            "unknown_name": self.unknown_name,
            "known_count": self.known_count,
            "formula": self.formula,
            "is_valid": self.is_valid,
            "status": self.status
        }


class RightTriangleSolver(object):
    """
    直角三角形边长求解器。

    使用方式:
        result = RightTriangleSolver.solve(Hypotenuse, LegA, LegB)

    返回:
        RightTriangleResult
    """

    @staticmethod
    def is_missing(value):
        """
        判断某输入是否视为“未知边”。

        规则:
            - None 视为未知
            - 无法转换为 float 视为未知
            - 数值 0 视为未知

        参数:
            value : any

        返回:
            bool
        """
        if value is None:
            return True
        try:
            return float(value) == 0.0
        except:
            return True

    @staticmethod
    def to_positive_float(value, name):
        """
        将输入转换为正数 float。

        参数:
            value : any
            name  : str
                参数名称，用于报错提示。

        返回:
            float

        异常:
            ValueError
        """
        try:
            val = float(value)
        except:
            raise ValueError("{} 不是有效数字。".format(name))

        if val <= 0:
            raise ValueError("{} 必须大于 0。".format(name))

        return val

    @classmethod
    def count_known(cls, hypotenuse, leg_a, leg_b):
        """
        统计已知边数量。

        返回:
            int
        """
        flags = [
            cls.is_missing(hypotenuse),
            cls.is_missing(leg_a),
            cls.is_missing(leg_b)
        ]
        return 3 - sum(flags)

    @classmethod
    def solve(cls, hypotenuse, leg_a, leg_b):
        """
        求解直角三角形未知边。

        参数:
            hypotenuse : float or None
                斜边长度。未知时可传 0 或 None。

            leg_a : float or None
                直角边 A。未知时可传 0 或 None。

            leg_b : float or None
                直角边 B。未知时可传 0 或 None。

        返回:
            RightTriangleResult
        """
        result = RightTriangleResult()
        status_msgs = []

        h_missing = cls.is_missing(hypotenuse)
        a_missing = cls.is_missing(leg_a)
        b_missing = cls.is_missing(leg_b)

        result.known_count = cls.count_known(hypotenuse, leg_a, leg_b)

        try:
            if result.known_count != 2:
                raise ValueError("必须且只能输入两个边长；未知边请设为 0 或 None。")

            # 情况 1：已知两条直角边，求斜边
            if h_missing and (not a_missing) and (not b_missing):
                a = cls.to_positive_float(leg_a, "LegA")
                b = cls.to_positive_float(leg_b, "LegB")
                c = math.sqrt(a * a + b * b)

                result.hypotenuse = c
                result.leg_a = a
                result.leg_b = b
                result.unknown_name = "Hypotenuse"
                result.formula = "Hypotenuse = sqrt(LegA^2 + LegB^2)"
                result.is_valid = True

                status_msgs.append("[OK] 已知两条直角边，成功计算斜边。")

            # 情况 2：已知斜边和 LegB，求 LegA
            elif a_missing and (not h_missing) and (not b_missing):
                c = cls.to_positive_float(hypotenuse, "Hypotenuse")
                b = cls.to_positive_float(leg_b, "LegB")

                if c <= b:
                    raise ValueError("斜边必须大于任一直角边。当前 Hypotenuse <= LegB。")

                a2 = c * c - b * b
                if a2 <= 0:
                    raise ValueError("Hypotenuse^2 - LegB^2 <= 0，无法求实数直角边 LegA。")

                a = math.sqrt(a2)

                result.hypotenuse = c
                result.leg_a = a
                result.leg_b = b
                result.unknown_name = "LegA"
                result.formula = "LegA = sqrt(Hypotenuse^2 - LegB^2)"
                result.is_valid = True

                status_msgs.append("[OK] 已知斜边和 LegB，成功计算 LegA。")

            # 情况 3：已知斜边和 LegA，求 LegB
            elif b_missing and (not h_missing) and (not a_missing):
                c = cls.to_positive_float(hypotenuse, "Hypotenuse")
                a = cls.to_positive_float(leg_a, "LegA")

                if c <= a:
                    raise ValueError("斜边必须大于任一直角边。当前 Hypotenuse <= LegA。")

                b2 = c * c - a * a
                if b2 <= 0:
                    raise ValueError("Hypotenuse^2 - LegA^2 <= 0，无法求实数直角边 LegB。")

                b = math.sqrt(b2)

                result.hypotenuse = c
                result.leg_a = a
                result.leg_b = b
                result.unknown_name = "LegB"
                result.formula = "LegB = sqrt(Hypotenuse^2 - LegA^2)"
                result.is_valid = True

                status_msgs.append("[OK] 已知斜边和 LegA，成功计算 LegB。")

            else:
                raise ValueError("输入组合无效。请保证三边中恰有一个未知边。")

            status_msgs.append("[OK] 计算完成。")

        except Exception as e:
            result.hypotenuse = None if h_missing else hypotenuse
            result.leg_a = None if a_missing else leg_a
            result.leg_b = None if b_missing else leg_b
            result.is_valid = False
            result.formula = result.formula if result.formula else ""
            status_msgs.append("[ERR] " + str(e))

        result.status = "\n".join(status_msgs)
        return result

if __name__ == "__main__":
    # ============================================================
    # GhPython 组件调用区
    # ============================================================
    # 说明:
    #     在 GhPython 中，假设输入端名称为:
    #         Hypotenuse, LegA, LegB
    #     则可直接使用下述代码求解，并映射到输出端。
    # ============================================================

    _result = RightTriangleSolver.solve(Hypotenuse, LegA, LegB)

    OutHypotenuse = _result.hypotenuse
    OutLegA = _result.leg_a
    OutLegB = _result.leg_b
    UnknownName = _result.unknown_name
    KnownCount = _result.known_count
    Formula = _result.formula
    IsValid = _result.is_valid
    Status = _result.status
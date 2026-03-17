# -*- coding: utf-8 -*-
"""
SongStyleUnitConverter_Value2FenChi
把“任意单位的长度值”换算为：
1) 宋尺制：Chi
2) 材分制：FenDegree（材分“分度”，以 1材高=15分）

------------------------------------------------------------
输入（GhPython 建议设置）:
    Grade : str (Item)
        默认 "第四等"
        支持: "第四等" / "Fourth_grade" / "第4等"（大小写不敏感）
        注意：按你的要求，不把纯数字 "4" 当作等材输入（会回落默认第四等）

    Value : float (Item)
        需要换算的数值（可为 str / list，也会自动转成 float）

    ValueUnit : str (Item)
        Value 的单位，支持（不区分大小写）：
            "丈","z","zhang",
            "尺","c","chi",
            "寸","cun",
            "分","f","fen",      # 这里是“尺制分”(1寸=10分)，仅用于输入单位解析
            "厘","l","li",
            "米","m",
            "分米","dm",
            "厘米","cm",
            "毫米","mm"
        默认 "cm"（强制：未接线时一定为 cm，忽略 Persistent Data）

    ChiToCm : float (Item)
        默认 31.2
        1 宋尺 = ChiToCm cm

------------------------------------------------------------
输出:
    FenDegree : float
        材分制“分度”（1材高=15分）——这是你要的“转化为分度(Fen)”

    ChiValue : float
        该 Value 换算后的“尺”数值

    GradeInfo : str
        等材说明（英文/中文/材广材高）

------------------------------------------------------------
说明（避免混淆）：
- ValueUnit 里的 “分(fen)” 是尺制单位链：1寸=10分（输入单位解析用）
- FenDegree 输出的是“材分制”的分：1材高=15分（营造法式材分）
------------------------------------------------------------
"""

import re

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.02.14"


def _first_item(x):
    if isinstance(x, (list, tuple)):
        return x[0] if len(x) > 0 else None
    return x

def coerce_float(x, default=0.0):
    x = _first_item(x)
    if x is None:
        return float(default)
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    try:
        s = str(x).strip()
        if s == "":
            return float(default)
        return float(s)
    except:
        return float(default)

def coerce_str(x, default=""):
    x = _first_item(x)
    if x is None:
        return default
    s = str(x).strip()
    return s if s != "" else default


class SongStyleUnitConverter_m2FenDegree(object):
    CAI_FEN_PER_CAI_HEIGHT = 15.0  # 1材高=15分（材分）

    def __init__(self, chi_to_cm=31.2):
        self.chi_to_cm = float(chi_to_cm) if chi_to_cm else 31.2

        self.grades = {
            1: {"grade": "First_grade",   "grade_cn": "第一等",  "w_cun": 6.0, "h_cun": 9.0},
            2: {"grade": "Second_grade",  "grade_cn": "第二等",  "w_cun": 5.5, "h_cun": 8.25},
            3: {"grade": "Third_grade",   "grade_cn": "第三等",  "w_cun": 5.0, "h_cun": 7.5},
            4: {"grade": "Fourth_grade",  "grade_cn": "第四等",  "w_cun": 4.8, "h_cun": 7.2},
            5: {"grade": "Fifth_grade",   "grade_cn": "第五等",  "w_cun": 4.4, "h_cun": 6.6},
            6: {"grade": "Sixth_grade",   "grade_cn": "第六等",  "w_cun": 4.0, "h_cun": 6.0},
            7: {"grade": "Seventh_grade", "grade_cn": "第七等",  "w_cun": 3.5, "h_cun": 5.25},
            8: {"grade": "Unranked_A",    "grade_cn": "未入等A", "w_cun": 3.3, "h_cun": 5.0},
            9: {"grade": "Eighth_grade",  "grade_cn": "第八等",  "w_cun": 3.0, "h_cun": 4.5},
            10:{"grade": "Unranked_B",    "grade_cn": "未入等B", "w_cun": 1.2, "h_cun": 1.8},
        }

        self.unit_map = {
            "丈":"zhang","z":"zhang","zhang":"zhang",
            "尺":"chi","c":"chi","chi":"chi",
            "寸":"cun","cun":"cun",
            "分":"fen","f":"fen","fen":"fen",
            "厘":"li","l":"li","li":"li",
            "米":"m","m":"m",
            "分米":"dm","dm":"dm",
            "厘米":"cm","cm":"cm",
            "毫米":"mm","mm":"mm",
        }

        self._grade_index = {}
        for k, v in self.grades.items():
            self._grade_index[str(v["grade"]).strip().lower()] = k
            self._grade_index[str(v["grade_cn"]).strip()] = k

    def parse_grade_key(self, g, default_key=4):
        g = _first_item(g)
        if g is None:
            return default_key
        s = str(g).strip()
        if s == "":
            return default_key

        m = re.match(r"^第\s*(\d+)\s*等$", s)
        if m:
            key = int(m.group(1))
            return key if key in self.grades else default_key

        s_lower = s.lower()
        if s_lower in self._grade_index:
            return self._grade_index[s_lower]
        if s in self._grade_index:
            return self._grade_index[s]

        # 允许 Fourth_grade 这种
        if s_lower in self._grade_index:
            return self._grade_index[s_lower]

        return default_key

    def get_grade(self, g):
        key = self.parse_grade_key(g, default_key=4)
        return self.grades.get(key, self.grades[4])

    def grade_info(self, g):
        rec = self.get_grade(g)
        return "{} / {} | 材广={}寸 材高={}寸".format(
            rec["grade"], rec["grade_cn"], rec["w_cun"], rec["h_cun"]
        )

    def normalize_unit(self, u, default="cm"):
        # ⭐ 默认 cm（这里仅是函数默认，执行区还会强制未接线=cm）
        s = str(_first_item(u)).strip().lower() if u is not None else ""
        if s == "":
            s = default
        return self.unit_map.get(s, "cm")

    def value_to_chi(self, value, unit):
        x = float(value)
        u = self.normalize_unit(unit, default="cm")

        # 尺制链
        if u == "zhang": return x * 10.0
        if u == "chi":   return x
        if u == "cun":   return x * 0.1
        if u == "fen":   return x * 0.01
        if u == "li":    return x * 0.001

        # 米制 → cm → chi
        if u == "m":
            cm = x * 100.0
            return cm / self.chi_to_cm
        if u == "dm":
            cm = x * 10.0
            return cm / self.chi_to_cm
        if u == "cm":
            return x / self.chi_to_cm
        if u == "mm":
            cm = x * 0.1
            return cm / self.chi_to_cm

        # fallback 当 cm
        return x / self.chi_to_cm

    def chi_to_cai_fen(self, grade, chi_value):
        rec = self.get_grade(grade)
        chi = float(chi_value)
        cun = chi * 10.0
        h_cun = float(rec["h_cun"])
        if h_cun == 0:
            return 0.0
        return cun * self.CAI_FEN_PER_CAI_HEIGHT / h_cun

    def value_to_cai_fen(self, grade, value, unit):
        chi = self.value_to_chi(value, unit)
        fen_degree = self.chi_to_cai_fen(grade, chi)
        return fen_degree, chi

if __name__ == "__main__":
    # =========================
    # GhPython 执行区（强制：ValueUnit 未接线时默认 "cm"）
    # =========================
    def _is_connected(input_name):
        """
        判断 GH 输入端是否接线：
        - 若未接线，GH 可能仍有 Persistent Data；这里用 SourceCount 进行强制默认控制
        """
        try:
            for p in ghenv.Component.Params.Input:
                if p.Name == input_name:
                    return p.SourceCount > 0
        except:
            pass
        return False


    Grade_in   = coerce_str(Grade, default="第四等")
    Value_in   = coerce_float(Value, default=0.0)

    # ⭐ 关键：未接线 -> 强制 cm（忽略 Persistent Data）
    if _is_connected("ValueUnit"):
        ValueUnit_in = coerce_str(ValueUnit, default="cm")
    else:
        ValueUnit_in = "cm"

    ChiToCm_in = coerce_float(ChiToCm, default=31.2)

    conv = SongStyleUnitConverter_m2FenDegree(chi_to_cm=ChiToCm_in)

    FenDegree, ChiValue = conv.value_to_cai_fen(Grade_in, Value_in, ValueUnit_in)
    GradeInfo = conv.grade_info(Grade_in)

# -*- coding: utf-8 -*-

"""
修复点：
- Fen/Grade/ChiToCm 可能以 str 或 list[str] 进入 GhPython
- 增加强制转型函数，避免 TypeError: can't multiply sequence by non-int of type 'float'
- Grade 输入端为 str：支持 First_grade / 第一等 / 第4等（含阿拉伯数字字符串），默认第四等
- Grade 不再支持整数（int/float 进入时一律回落到默认第四等）

输入（GhPython 建议设置）:
    Grade   : str   (Item)  默认 "第四等"（也支持 "Fourth_grade" / "第4等"）
    Fen     : float (Item)  # 但就算用户给字符串/列表也能兜底
    OutUnit : str   (Item)  默认 "mm"
    ChiToCm : float (Item)  默认 31.2

输出:
    ChiValue    : float
    CmValue     : float
    CustomValue : float
    GradeInfo   : str
"""

import re

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.02.14"


def _first_item(x):
    """如果是 GH 传入的 list/tuple，取第一个；否则原样返回"""
    if isinstance(x, (list, tuple)):
        return x[0] if len(x) > 0 else None
    return x

def coerce_float(x, default=0.0):
    x = _first_item(x)
    if x is None:
        return float(default)
    # 已经是数字
    if isinstance(x, (int, float)):
        return float(x)
    # 字符串
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


class SongStyleUnitConverter(object):

    CAI_FEN_PER_CAI_HEIGHT = 15.0

    def __init__(self, chi_to_cm=31.2):
        self.chi_to_cm = float(chi_to_cm) if chi_to_cm else 31.2

        # 等材：材广/材高（寸）
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

        # 反向索引：支持英文/中文直接查等次
        self._grade_index = {}
        for k, v in self.grades.items():
            self._grade_index[str(v["grade"]).strip().lower()] = k
            self._grade_index[str(v["grade_cn"]).strip()] = k  # 中文保留原样

    def parse_grade_key(self, g, default_key=4):
        """
        Grade 输入：仅支持字符串（或 list/tuple[str]）
        支持：
          - "First_grade" / "fourth_grade"（大小写不敏感）
          - "第一等" / "第四等"
          - "第4等"（阿拉伯数字）
        不支持：
          - int/float（直接回落默认第四等）
          - 纯数字字符串 "4"（按要求：不再支持整数语义）
        """
        g = _first_item(g)

        # 不再支持 int/float：直接回落默认
        if isinstance(g, (int, float)) and not isinstance(g, bool):
            return default_key

        if g is None:
            return default_key

        s = str(g).strip()
        if s == "":
            return default_key

        # "第4等"
        m = re.match(r"^第\s*(\d+)\s*等$", s)
        if m:
            key = int(m.group(1))
            return key if key in self.grades else default_key

        # 英文/中文索引匹配（英文忽略大小写）
        s_lower = s.lower()
        if s_lower in self._grade_index:
            return self._grade_index[s_lower]
        if s in self._grade_index:
            return self._grade_index[s]

        return default_key

    def get_grade(self, g):
        key = self.parse_grade_key(g, default_key=4)
        return self.grades.get(key, self.grades[4])

    def grade_info(self, g):
        rec = self.get_grade(g)
        return "{} / {} | 材广={}寸 材高={}寸".format(
            rec["grade"], rec["grade_cn"], rec["w_cun"], rec["h_cun"]
        )

    def fen_to_chi(self, grade, fen):
        """fen 必须是 float；这里再兜一次底，避免外部没转型"""
        rec = self.get_grade(grade)  # grade 允许传 str
        fen = float(fen)
        one_fen_cun = rec["h_cun"] / self.CAI_FEN_PER_CAI_HEIGHT
        cun_value = fen * one_fen_cun
        return cun_value * 0.1  # 寸 -> 尺

    def chi_to_cm_value(self, chi):
        return float(chi) * self.chi_to_cm

    def chi_to_unit(self, chi, unit):
        u = self.unit_map.get(str(unit).strip().lower(), "mm")
        chi = float(chi)

        if u == "zhang": return chi / 10.0
        if u == "chi":   return chi
        if u == "cun":   return chi * 10.0
        if u == "fen":   return chi * 100.0
        if u == "li":    return chi * 1000.0

        cm = self.chi_to_cm_value(chi)
        if u == "m":  return cm / 100.0
        if u == "dm": return cm / 10.0
        if u == "cm": return cm
        if u == "mm": return cm * 10.0
        return cm * 10.0

if __name__ == "__main__":
    # =========================
    # GhPython 执行区（关键：先转型）
    # =========================
    # Grade 默认值为 "第四等"，且统一当作字符串处理
    Grade_in   = coerce_str(Grade, default="第四等")
    Fen_in     = coerce_float(Fen, default=0.0)
    OutUnit_in = coerce_str(OutUnit, default="mm")
    ChiToCm_in = coerce_float(ChiToCm, default=31.2)

    conv = SongStyleUnitConverter(chi_to_cm=ChiToCm_in)

    ChiValue    = conv.fen_to_chi(Grade_in, Fen_in)
    CmValue     = conv.chi_to_cm_value(ChiValue)
    CustomValue = conv.chi_to_unit(ChiValue, OutUnit_in)
    GradeInfo   = conv.grade_info(Grade_in)

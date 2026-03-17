# -*- coding: utf-8 -*-
"""
AbsStructRep_SiPU_Corner_ComponentAssemblySolver.py

【逐步转换】Step 1：读取数据库（DBJsonReader）
- Table     = AbsStructRep
- KeyField  = type_code
- KeyValue  = ASR_SiPU_Corner
- Field     = params_json
- ExportAll = True

输入（当前仅 3 个）:
    DBPath     : str / None
    PlacePlane : Plane / None   （默认 GH WorldXY，且原点=(100,100,0)）
    Refresh    : bool           （用于刷新/重读数据库；当前 step1 仅记录）

输出（对外）:
    AbsStructRep : object   （当前 step1 尚未生成构件，先为 None；后续 step 完成后输出组合体）
    Log          : str

内部（先保留，便于后续增减输出端）:
    Value, All, AllDict, DBLog
    PointsOnLineByCumsum__BaseLine,
    PointsOnLineByCumsum__SumValue,
    PointsOnLineByCumsum__ReversedList,
    PointsOnLineByCumsum__CumList,
    PointsOnLineByCumsum__PointList
    CaiZhiThreePointsBuilder__PointList,
    CaiZhiThreePointsBuilder__BasePoint,
    CaiZhiThreePointsBuilder__OffsetPts,
    CaiZhiThreePointsBuilder__ExtraPoint,
    CaiZhiThreePointsBuilder__DirUnit,
    CaiZhiThreePointsBuilder__SpanVectors,
    UniqueRectangleFrom3Pts__Face,
    UniqueRectangleFrom3Pts__AB,
    CaiZhiSupportLinkLines__OffsetPts,
    CaiZhiSupportLinkLines__LinkLines
    CaiZhiThreePointsBuilder1__PointList,
    CaiZhiThreePointsBuilder1__BasePoint,
    CaiZhiThreePointsBuilder1__OffsetPts,
    CaiZhiThreePointsBuilder1__ExtraPoint,
    CaiZhiThreePointsBuilder1__DirUnit,
    CaiZhiThreePointsBuilder1__SpanVectors,
    UniqueRectangleFrom3Pts1__Face,
    UniqueRectangleFrom3Pts1__AB,
    CaiZhiSupportLinkLines1__OffsetPts,
    CaiZhiSupportLinkLines1__LinkLines
    PlaneXYBisectorVectors__Bisector_U,
    PlaneXYBisectorVectors__Bisector_U_Neg,
    PlaneXYBisectorVectors__XAxis_U,
    PlaneXYBisectorVectors__YAxis_U,
    PlaneXYBisectorVectors__ZAxis_U,
    CaiZhiThreePointsBuilder2__PointList,
    CaiZhiThreePointsBuilder2__BasePoint,
    CaiZhiThreePointsBuilder2__OffsetPts,
    CaiZhiThreePointsBuilder2__ExtraPoint,
    CaiZhiThreePointsBuilder2__DirUnit,
    CaiZhiThreePointsBuilder2__SpanVectors,
    UniqueRectangleFrom3Pts2__Face,
    UniqueRectangleFrom3Pts2__AB,
    CaiZhiSupportLinkLines2__OffsetPts,
    CaiZhiSupportLinkLines2__LinkLines
    CaiZhiThreePointsBuilder3__PointList,
    CaiZhiThreePointsBuilder3__BasePoint,
    CaiZhiThreePointsBuilder3__OffsetPts,
    CaiZhiThreePointsBuilder3__ExtraPoint,
    CaiZhiThreePointsBuilder3__DirUnit,
    CaiZhiThreePointsBuilder3__SpanVectors,
    UniqueRectangleFrom3Pts3__Face,
    UniqueRectangleFrom3Pts3__AB,
    CaiZhiSupportLinkLines3__OffsetPts,
    CaiZhiSupportLinkLines3__LinkLines,
    CaiZhiSupportLinkLines3__OffsetLine
    CaiZhiThreePointsBuilder4__PointList,
    CaiZhiThreePointsBuilder4__BasePoint,
    CaiZhiThreePointsBuilder4__OffsetPts,
    CaiZhiThreePointsBuilder4__ExtraPoint,
    CaiZhiThreePointsBuilder4__DirUnit,
    CaiZhiThreePointsBuilder4__SpanVectors,
    UniqueRectangleFrom3Pts4__Face,
    UniqueRectangleFrom3Pts4__AB,
    CaiZhiSupportLinkLines4__OffsetPts,
    CaiZhiSupportLinkLines4__LinkLines,
    CaiZhiSupportLinkLines4__OffsetLine
    CaiZhiThreePointsBuilder5__PointList,
    CaiZhiThreePointsBuilder5__BasePoint,
    CaiZhiThreePointsBuilder5__OffsetPts,
    CaiZhiThreePointsBuilder5__ExtraPoint,
    CaiZhiThreePointsBuilder5__DirUnit,
    CaiZhiThreePointsBuilder5__SpanVectors,
    UniqueRectangleFrom3Pts5__Face,
    UniqueRectangleFrom3Pts5__AB,
    CaiZhiSupportLinkLines5__OffsetPts,
    CaiZhiSupportLinkLines5__LinkLines,
    CaiZhiSupportLinkLines5__OffsetLine
    CaiZhiThreePointsBuilder6__PointList,
    CaiZhiThreePointsBuilder6__BasePoint,
    CaiZhiThreePointsBuilder6__OffsetPts,
    CaiZhiThreePointsBuilder6__ExtraPoint,
    CaiZhiThreePointsBuilder6__DirUnit,
    CaiZhiThreePointsBuilder6__SpanVectors,
    UniqueRectangleFrom3Pts6__Face,
    UniqueRectangleFrom3Pts6__AB,
    CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts,
    CaiZhiSupportLinkLines_ByBasePoint0__LinkLines,
    CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine
    CaiZhiThreePointsBuilder7__PointList,
    CaiZhiThreePointsBuilder7__BasePoint,
    CaiZhiThreePointsBuilder7__OffsetPts,
    CaiZhiThreePointsBuilder7__ExtraPoint,
    CaiZhiThreePointsBuilder7__DirUnit,
    CaiZhiThreePointsBuilder7__SpanVectors,
    UniqueRectangleFrom3Pts7__Face,
    UniqueRectangleFrom3Pts7__AB,
    CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts,
    CaiZhiSupportLinkLines_ByBasePoint1__LinkLines,
    CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine
    CaiZhiThreePointsBuilder8__PointList,
    CaiZhiThreePointsBuilder8__BasePoint,
    CaiZhiThreePointsBuilder8__OffsetPts,
    CaiZhiThreePointsBuilder8__ExtraPoint,
    CaiZhiThreePointsBuilder8__DirUnit,
    CaiZhiThreePointsBuilder8__SpanVectors,
    UniqueRectangleFrom3Pts8__Face,
    UniqueRectangleFrom3Pts8__AB,
    CaiZhiSupportLinkLines_ByBasePoint2__OffsetPts,
    CaiZhiSupportLinkLines_ByBasePoint2__LinkLines,
    CaiZhiSupportLinkLines_ByBasePoint2__OffsetLine
    CaiZhiThreePointsBuilder9__PointList,
    CaiZhiThreePointsBuilder9__BasePoint,
    CaiZhiThreePointsBuilder9__OffsetPts,
    CaiZhiThreePointsBuilder9__ExtraPoint,
    CaiZhiThreePointsBuilder9__DirUnit,
    CaiZhiThreePointsBuilder9__SpanVectors,
    UniqueRectangleFrom3Pts9__Face,
    UniqueRectangleFrom3Pts9__AB,
    CaiZhiSupportLinkLines_ByBasePoint3__OffsetPts,
    CaiZhiSupportLinkLines_ByBasePoint3__LinkLines,
    CaiZhiSupportLinkLines_ByBasePoint3__OffsetLine
"""

from __future__ import print_function, division

import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    DBJsonReader,
    PointsOnLineByCumsum,
    CaiZhiThreePointsBuilder,
    UniqueRectangleFrom3Pts,
    CaiZhiSupportLinkLines,
    CaiZhiSupportLinkLines_ByBasePoint,
    PlaneXYBisectorVectors,
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.02.17+step12_add_LingGongWXiaoGongTou2_support"


# =========================================================
# 通用工具函数
# =========================================================

def _default_place_plane():
    """默认放置平面：GH 的 XY Plane，原点为 (100,100,0)"""
    pl = rg.Plane.WorldXY
    pl.Origin = rg.Point3d(100.0, 100.0, 0.0)
    return pl


def _ensure_list(x):
    """把 None/单值/tuple/list 统一成 list（不做深度拍平）。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    return [x]


def _first_item(x, default=None):
    """取 GH 常见输入（Item/List/Tree）中的第一个标量值。"""
    if x is None:
        return default
    if isinstance(x, (list, tuple)):
        if len(x) == 0:
            return default
        return _first_item(x[0], default)
    return x


def _parse_span_plus_minus(span_raw, default=0.0):
    """解析 Span：支持标量或 [plus, minus] 列表（顺序：+Direction, -Direction）。
    返回: (span_plus, span_minus)
    """
    if span_raw is None:
        try:
            d = float(default)
        except:
            d = 0.0
        return d, d

    # GH 常见：可能是 list/tuple/嵌套
    if isinstance(span_raw, (list, tuple)):
        if len(span_raw) == 0:
            return _parse_span_plus_minus(None, default)
        if len(span_raw) == 1:
            v = _first_item(span_raw[0], default)
            try:
                f = float(v)
            except:
                f = 0.0
            return f, f
        # 约定：[plus, minus]
        v_plus = _first_item(span_raw[0], default)
        v_minus = _first_item(span_raw[1], v_plus)
        try:
            span_plus = float(v_plus)
        except:
            span_plus = 0.0
        try:
            span_minus = float(v_minus)
        except:
            span_minus = 0.0
        return span_plus, span_minus

    v = _first_item(span_raw, default)
    try:
        f = float(v)
    except:
        f = 0.0
    return f, f


def _flatten_items(x, out_list):
    """递归拍平 list/tuple（用于输出端避免嵌套 List`1[Object] 的表现）。"""
    if x is None:
        return
    if isinstance(x, (list, tuple)):
        for it in x:
            _flatten_items(it, out_list)
    else:
        out_list.append(x)


def _as_bool(x, default=False):
    if x is None:
        return bool(default)
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(int(x) != 0)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("1", "true", "t", "yes", "y", "on"):
            return True
        if s in ("0", "false", "f", "no", "n", "off", ""):
            return False
    return bool(default)


# =========================================================
# Solver 主类
# =========================================================

class AbsStructRep_SiPU_Corner_ComponentAssemblySolver(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = _as_bool(Refresh, False)
        self.ghenv = ghenv

        self.LogLines = []
        self.AbsStructRep = None
        self.Log = ""

        # Step1 数据（必须保留）
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = None

        # Step2 数据（PointsOnLineByCumsum：材栔模式）
        self.PointsOnLineByCumsum__BaseLine = None
        self.PointsOnLineByCumsum__SumValue = None
        self.PointsOnLineByCumsum__ReversedList = None
        self.PointsOnLineByCumsum__CumList = None
        self.PointsOnLineByCumsum__PointList = None

        # Step3 数据（插昂與泥道栱相列一 支撑点）
        self.CaiZhiThreePointsBuilder__PointList = None
        self.CaiZhiThreePointsBuilder__BasePoint = None
        self.CaiZhiThreePointsBuilder__OffsetPts = None
        self.CaiZhiThreePointsBuilder__ExtraPoint = None
        self.CaiZhiThreePointsBuilder__DirUnit = None
        self.CaiZhiThreePointsBuilder__SpanVectors = None

        self.UniqueRectangleFrom3Pts__Face = None
        self.UniqueRectangleFrom3Pts__AB = None

        self.CaiZhiSupportLinkLines__OffsetPts = None
        self.CaiZhiSupportLinkLines__LinkLines = None

        # Step4 数据（插昂與泥道栱相列二 支撑点）
        self.CaiZhiThreePointsBuilder1__PointList = None
        self.CaiZhiThreePointsBuilder1__BasePoint = None
        self.CaiZhiThreePointsBuilder1__OffsetPts = None
        self.CaiZhiThreePointsBuilder1__ExtraPoint = None
        self.CaiZhiThreePointsBuilder1__DirUnit = None
        self.CaiZhiThreePointsBuilder1__SpanVectors = None

        self.UniqueRectangleFrom3Pts1__Face = None
        self.UniqueRectangleFrom3Pts1__AB = None

        self.CaiZhiSupportLinkLines1__OffsetPts = None
        self.CaiZhiSupportLinkLines1__LinkLines = None
        # Step5 数据（角昂與角華栱相列 支撑点）
        self.PlaneXYBisectorVectors__Bisector_U = None
        self.PlaneXYBisectorVectors__Bisector_U_Neg = None
        self.PlaneXYBisectorVectors__XAxis_U = None
        self.PlaneXYBisectorVectors__YAxis_U = None
        self.PlaneXYBisectorVectors__ZAxis_U = None

        self.CaiZhiThreePointsBuilder2__PointList = None
        self.CaiZhiThreePointsBuilder2__BasePoint = None
        self.CaiZhiThreePointsBuilder2__OffsetPts = None
        self.CaiZhiThreePointsBuilder2__ExtraPoint = None
        self.CaiZhiThreePointsBuilder2__DirUnit = None
        self.CaiZhiThreePointsBuilder2__SpanVectors = None

        self.UniqueRectangleFrom3Pts2__Face = None
        self.UniqueRectangleFrom3Pts2__AB = None

        self.CaiZhiSupportLinkLines2__OffsetPts = None
        self.CaiZhiSupportLinkLines2__LinkLines = None

        # Step6 数据（耍頭與慢栱相列一 支撑点）
        self.CaiZhiThreePointsBuilder3__PointList = None
        self.CaiZhiThreePointsBuilder3__BasePoint = None
        self.CaiZhiThreePointsBuilder3__OffsetPts = None
        self.CaiZhiThreePointsBuilder3__ExtraPoint = None
        self.CaiZhiThreePointsBuilder3__DirUnit = None
        self.CaiZhiThreePointsBuilder3__SpanVectors = None

        self.UniqueRectangleFrom3Pts3__Face = None
        self.UniqueRectangleFrom3Pts3__AB = None

        self.CaiZhiSupportLinkLines3__OffsetPts = None
        self.CaiZhiSupportLinkLines3__LinkLines = None
        self.CaiZhiSupportLinkLines3__OffsetLine = None

        # Step7 数据（耍頭與慢栱相列二 支撑点）
        self.CaiZhiThreePointsBuilder4__PointList = None
        self.CaiZhiThreePointsBuilder4__BasePoint = None
        self.CaiZhiThreePointsBuilder4__OffsetPts = None
        self.CaiZhiThreePointsBuilder4__ExtraPoint = None
        self.CaiZhiThreePointsBuilder4__DirUnit = None
        self.CaiZhiThreePointsBuilder4__SpanVectors = None

        self.UniqueRectangleFrom3Pts4__Face = None
        self.UniqueRectangleFrom3Pts4__AB = None

        self.CaiZhiSupportLinkLines4__OffsetPts = None
        self.CaiZhiSupportLinkLines4__LinkLines = None
        self.CaiZhiSupportLinkLines4__OffsetLine = None

        # Step8 数据（由昂與角耍頭相列 支撑点）
        self.CaiZhiThreePointsBuilder5__PointList = None
        self.CaiZhiThreePointsBuilder5__BasePoint = None
        self.CaiZhiThreePointsBuilder5__OffsetPts = None
        self.CaiZhiThreePointsBuilder5__ExtraPoint = None
        self.CaiZhiThreePointsBuilder5__DirUnit = None
        self.CaiZhiThreePointsBuilder5__SpanVectors = None

        self.UniqueRectangleFrom3Pts5__Face = None
        self.UniqueRectangleFrom3Pts5__AB = None

        self.CaiZhiSupportLinkLines5__OffsetPts = None
        self.CaiZhiSupportLinkLines5__LinkLines = None
        self.CaiZhiSupportLinkLines5__OffsetLine = None

        # Step9 数据（瓜子栱與令栱相列二 支撑点）
        self.CaiZhiThreePointsBuilder6__PointList = None
        self.CaiZhiThreePointsBuilder6__BasePoint = None
        self.CaiZhiThreePointsBuilder6__OffsetPts = None
        self.CaiZhiThreePointsBuilder6__ExtraPoint = None
        self.CaiZhiThreePointsBuilder6__DirUnit = None
        self.CaiZhiThreePointsBuilder6__SpanVectors = None

        self.UniqueRectangleFrom3Pts6__Face = None
        self.UniqueRectangleFrom3Pts6__AB = None

        self.CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts = None
        self.CaiZhiSupportLinkLines_ByBasePoint0__LinkLines = None
        self.CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine = None

        # Step10 数据（瓜子栱與令栱相列一 支撑点）
        self.CaiZhiThreePointsBuilder7__PointList = None
        self.CaiZhiThreePointsBuilder7__BasePoint = None
        self.CaiZhiThreePointsBuilder7__OffsetPts = None
        self.CaiZhiThreePointsBuilder7__ExtraPoint = None
        self.CaiZhiThreePointsBuilder7__DirUnit = None
        self.CaiZhiThreePointsBuilder7__SpanVectors = None

        self.UniqueRectangleFrom3Pts7__Face = None
        self.UniqueRectangleFrom3Pts7__AB = None

        self.CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts = None
        self.CaiZhiSupportLinkLines_ByBasePoint1__LinkLines = None
        self.CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine = None

    # -------------------------------
    # Step 1：读取数据库
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 AbsStructRep / ASR_SiPU_Corner params_json -> All / AllDict …")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="AbsStructRep",
            key_field="type_code",
            key_value="ASR_SiPU_Corner",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value, self.All, self.DBLog = reader.run()

        d = {}
        try:
            for k, v in _ensure_list(self.All):
                d[str(k)] = v
        except:
            pass
        self.AllDict = d

        self.LogLines.append("Step 1 完成：All items={} AllDict keys={}".format(
            len(_ensure_list(self.All)), len(self.AllDict.keys())
        ))

    # -------------------------------
    # Step 2：材栔模式（PointsOnLineByCumsum）
    # -------------------------------
    def step2_cai_zhi_pattern_points(self):
        """
        Values     : 来自数据库字段 puZuoVerticalCaiZhiPattern
        BasePoint  : PlacePlane.Origin
        Direction  : PlacePlane.ZAxis
        """
        self.LogLines.append("Step 2：材栔模式 PointsOnLineByCumsum（puZuoVerticalCaiZhiPattern）…")

        # 输入端值优先：组件输入端（当前无独立输入端）-> 数据库 -> 默认
        values_raw = None
        try:
            values_raw = self.AllDict.get("puZuoVerticalCaiZhiPattern", None)
        except:
            values_raw = None
        if values_raw is None:
            values_raw = []

        base_pt = self.PlacePlane.Origin
        dir_vec = self.PlacePlane.ZAxis

        builder = PointsOnLineByCumsum(values_raw, base_pt, dir_vec, clamp=True)
        bl, sv, rl, cl, pl = builder.build()

        # 输出变量（按“构件组件名为前缀”避免重名）
        self.PointsOnLineByCumsum__BaseLine = bl
        self.PointsOnLineByCumsum__SumValue = sv
        self.PointsOnLineByCumsum__ReversedList = rl
        self.PointsOnLineByCumsum__CumList = cl

        # PointList 可能出现嵌套/多层嵌套：强制完全展平
        flat_pts = []
        _flatten_items(pl, flat_pts)
        self.PointsOnLineByCumsum__PointList = flat_pts

        self.LogLines.append("Step 2 完成：Points={} SumValue={}".format(len(flat_pts), sv))

    # -------------------------------
    # Step 3：插昂與泥道栱相列一 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::0、UniqueRectangleFrom3Pts::0、CaiZhiSupportLinkLines::0
    # -------------------------------
    def step3_chaang_nidaogong_support_pts(self):
        self.LogLines.append(
            "Step 3：插昂與泥道栱相列一 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- CaiZhiThreePointsBuilder::0 ----------
        Direction = self.PlacePlane.XAxis  # 参考平面 X 轴
        CaiZhiPts = self.PointsOnLineByCumsum__PointList  # 材栔点列表
        IndexA = 2
        IndexB = 1

        # Span 来自数据库：ChaAngInLineWNiDaoGong1__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("ChaAngInLineWNiDaoGong1__axis2support", None)
        except:
            Span_raw = None

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # 组件原型只接受单个 Span；当 span_plus != span_minus 时，按 [+Direction, -Direction] 分别构造两侧点
        if abs(span_plus - span_minus) < 1e-12:
            builder = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_plus
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder.build()
        else:
            # +Direction
            builder_p = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_plus
            )
            PLp, BasePoint, OffsetPts_p, ExtraPoint, DirUnit, SpanVectors_p = builder_p.build()

            # -Direction
            builder_m = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_minus
            )
            PLm, BasePoint_m, OffsetPts_m, ExtraPoint_m, DirUnit_m, SpanVectors_m = builder_m.build()

            # 取 P_plus / P_minus（保持输出次序：[P_minus, P_plus]）
            P_plus = None
            P_minus = None
            try:
                if OffsetPts_p and len(OffsetPts_p) >= 2:
                    P_plus = OffsetPts_p[1]
                elif OffsetPts_p:
                    P_plus = OffsetPts_p[-1]
            except:
                P_plus = None
            try:
                if OffsetPts_m and len(OffsetPts_m) >= 1:
                    P_minus = OffsetPts_m[0]
            except:
                P_minus = None

            OffsetPts = [P_minus, P_plus]
            # SpanVectors 与 OffsetPts 同序：[V_minus, V_plus]
            try:
                if DirUnit is None:
                    DirUnit = DirUnit_m
            except:
                pass
            SpanVectors = []
            try:
                v_minus = rg.Vector3d(DirUnit);
                v_minus.Unitize();
                v_minus *= (-span_minus)
                v_plus = rg.Vector3d(DirUnit);
                v_plus.Unitize();
                v_plus *= (span_plus)
                SpanVectors = [v_minus, v_plus]
            except:
                SpanVectors = []
            PointList = [ExtraPoint, P_minus, P_plus]

        # 输出成员变量（按组件名）
        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder__PointList = pl_flat
        self.CaiZhiThreePointsBuilder__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::0 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts__Face = Face
        self.UniqueRectangleFrom3Pts__AB = AB

        # ---------- CaiZhiSupportLinkLines::0 ----------
        Direction2 = self.CaiZhiThreePointsBuilder__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 3
        SupportPts = self.CaiZhiThreePointsBuilder__OffsetPts

        solver = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines__LinkLines = ll_flat

        self.LogLines.append(
            "Step 3 完成：3Pts={} LinkLines={} Span=[+{},-{}]".format(len(pl_flat), len(ll_flat), span_plus, span_minus))

    # -------------------------------
    # Step 4：插昂與泥道栱相列二 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::1、UniqueRectangleFrom3Pts::1、CaiZhiSupportLinkLines::1
    # -------------------------------
    def step4_chaang_nidaogong_support_pts_2(self):
        self.LogLines.append(
            "Step 4：插昂與泥道栱相列二 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- CaiZhiThreePointsBuilder::1 ----------
        Direction = self.PlacePlane.YAxis  # 参考平面 Y 轴
        CaiZhiPts = self.PointsOnLineByCumsum__PointList  # 材栔点列表
        IndexA = 2
        IndexB = 1

        # Span 来自数据库：ChaAngInLineWNiDaoGong2__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("ChaAngInLineWNiDaoGong2__axis2support", None)
        except:
            Span_raw = None

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # 组件原型只接受单个 Span；当 span_plus != span_minus 时，按 [+Direction, -Direction] 分别构造两侧点
        if abs(span_plus - span_minus) < 1e-12:
            builder = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_plus
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder.build()
        else:
            # +Direction
            builder_p = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_plus
            )
            PLp, BasePoint, OffsetPts_p, ExtraPoint, DirUnit, SpanVectors_p = builder_p.build()

            # -Direction
            builder_m = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=2,
                index_b=1,
                direction=Direction,
                span=span_minus
            )
            PLm, BasePoint_m, OffsetPts_m, ExtraPoint_m, DirUnit_m, SpanVectors_m = builder_m.build()

            # 取 P_plus / P_minus（保持输出次序：[P_minus, P_plus]）
            P_plus = None
            P_minus = None
            try:
                if OffsetPts_p and len(OffsetPts_p) >= 2:
                    P_plus = OffsetPts_p[1]
                elif OffsetPts_p:
                    P_plus = OffsetPts_p[-1]
            except:
                P_plus = None
            try:
                if OffsetPts_m and len(OffsetPts_m) >= 1:
                    P_minus = OffsetPts_m[0]
            except:
                P_minus = None

            OffsetPts = [P_minus, P_plus]
            # SpanVectors 与 OffsetPts 同序：[V_minus, V_plus]
            try:
                if DirUnit is None:
                    DirUnit = DirUnit_m
            except:
                pass
            SpanVectors = []
            try:
                v_minus = rg.Vector3d(DirUnit);
                v_minus.Unitize();
                v_minus *= (-span_minus)
                v_plus = rg.Vector3d(DirUnit);
                v_plus.Unitize();
                v_plus *= (span_plus)
                SpanVectors = [v_minus, v_plus]
            except:
                SpanVectors = []
            PointList = [ExtraPoint, P_minus, P_plus]

        # 输出成员变量（按组件名 + 显式序号 1，避免与 Step3 冲突）
        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder1__PointList = pl_flat
        self.CaiZhiThreePointsBuilder1__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder1__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder1__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder1__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder1__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::1 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder1__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts1__Face = Face
        self.UniqueRectangleFrom3Pts1__AB = AB

        # ---------- CaiZhiSupportLinkLines::1 ----------
        Direction2 = self.CaiZhiThreePointsBuilder1__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 3
        SupportPts = self.CaiZhiThreePointsBuilder1__OffsetPts

        solver = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines1__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines1__LinkLines = ll_flat

        self.LogLines.append(
            "Step 4 完成：3Pts={} LinkLines={} Span=[+{},-{}]".format(len(pl_flat), len(ll_flat), span_plus, span_minus))

    # -------------------------------
    # Step 5：角昂與角華栱相列 支撑点
    #   核心组件：PlaneXYBisectorVectors、CaiZhiThreePointsBuilder::2、UniqueRectangleFrom3Pts::2、CaiZhiSupportLinkLines::2
    # -------------------------------
    def step5_jiaoang_jiaohuagong_support_pts(self):
        self.LogLines.append(
            "Step 5：角昂與角華栱相列 支撑点（PlaneXYBisectorVectors / CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- PlaneXYBisectorVectors ----------
        RefPlane = self.PlacePlane
        CustomXAxis = None
        CustomYAxis = None
        try:
            builder = PlaneXYBisectorVectors(RefPlane, CustomXAxis, CustomYAxis)
            Bisector_U, Bisector_U_Neg, XAxis_U, YAxis_U, ZAxis_U = builder.build()
        except Exception:
            # 避免 GH 组件变红：回退到 WorldXY 的稳定输出
            p = rg.Plane.WorldXY
            XAxis_U = rg.Vector3d(p.XAxis);
            XAxis_U.Unitize()
            YAxis_U = rg.Vector3d(p.YAxis);
            YAxis_U.Unitize()
            ZAxis_U = rg.Vector3d(p.ZAxis);
            ZAxis_U.Unitize()
            Bisector_U = rg.Vector3d(XAxis_U + YAxis_U)
            if not Bisector_U.IsTiny(1e-12):
                Bisector_U.Unitize()
            else:
                Bisector_U = rg.Vector3d(1, 0, 0)
            Bisector_U_Neg = rg.Vector3d(-Bisector_U.X, -Bisector_U.Y, -Bisector_U.Z)

        self.PlaneXYBisectorVectors__Bisector_U = Bisector_U
        self.PlaneXYBisectorVectors__Bisector_U_Neg = Bisector_U_Neg
        self.PlaneXYBisectorVectors__XAxis_U = XAxis_U
        self.PlaneXYBisectorVectors__YAxis_U = YAxis_U
        self.PlaneXYBisectorVectors__ZAxis_U = ZAxis_U

        # ---------- CaiZhiThreePointsBuilder::2 ----------
        Direction = self.PlaneXYBisectorVectors__Bisector_U
        CaiZhiPts = self.PointsOnLineByCumsum__PointList
        IndexA = 2
        IndexB = 1

        # Span 来自数据库：JiaoAngInLineWJiaoHuaGong__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("JiaoAngInLineWJiaoHuaGong__axis2support", None)
        except:
            Span_raw = None

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        if abs(span_plus - span_minus) < 1e-12:
            builder2 = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder2.build()
        else:
            # +Direction
            builder2_p = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PLp, BasePoint, OffsetPts_p, ExtraPoint, DirUnit, SpanVectors_p = builder2_p.build()

            # -Direction
            builder2_m = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_minus
            )
            PLm, BasePoint_m, OffsetPts_m, ExtraPoint_m, DirUnit_m, SpanVectors_m = builder2_m.build()

            P_plus = None
            P_minus = None
            try:
                if OffsetPts_p and len(OffsetPts_p) >= 2:
                    P_plus = OffsetPts_p[1]
                elif OffsetPts_p:
                    P_plus = OffsetPts_p[-1]
            except:
                P_plus = None
            try:
                if OffsetPts_m and len(OffsetPts_m) >= 1:
                    P_minus = OffsetPts_m[0]
            except:
                P_minus = None

            OffsetPts = [P_minus, P_plus]
            SpanVectors = []
            try:
                v_minus = rg.Vector3d(DirUnit);
                v_minus.Unitize();
                v_minus *= (-span_minus)
                v_plus = rg.Vector3d(DirUnit);
                v_plus.Unitize();
                v_plus *= (span_plus)
                SpanVectors = [v_minus, v_plus]
            except:
                SpanVectors = []
            PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder2__PointList = pl_flat
        self.CaiZhiThreePointsBuilder2__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder2__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder2__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder2__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder2__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::2 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder2__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None
        self.UniqueRectangleFrom3Pts2__Face = Face
        self.UniqueRectangleFrom3Pts2__AB = AB

        # ---------- CaiZhiSupportLinkLines::2 ----------
        Direction2 = self.CaiZhiThreePointsBuilder2__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 3
        SupportPts = self.CaiZhiThreePointsBuilder2__OffsetPts

        solver2 = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver2.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines2__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines2__LinkLines = ll_flat

        self.LogLines.append(
            "Step 5 完成：3Pts={} LinkLines={} Span=[+{},-{}]".format(len(pl_flat), len(ll_flat), span_plus, span_minus))

    # -------------------------------
    # Step 6：耍頭與慢栱相列一 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::3、UniqueRectangleFrom3Pts::3、CaiZhiSupportLinkLines::3
    # -------------------------------
    def step6_shuatou_mangong1_support_pts(self):
        self.LogLines.append(
            "Step 6：耍頭與慢栱相列一 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- CaiZhiThreePointsBuilder::3 ----------
        Direction = self.PlacePlane.XAxis
        CaiZhiPts = self.PointsOnLineByCumsum__PointList
        IndexA = 4
        IndexB = 3

        # Span 来自数据库：ShuaTouInLineWManGong1__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("ShuaTouInLineWManGong1__axis2support", None)
        except:
            Span_raw = None

        # ⚠️ 本 step 的 Span 可能是 List：
        #   - 若为标量：沿 +Direction 与 -Direction 使用同一距离（与原组件一致）
        #   - 若为长度>=2 的列表：分别用于 [+Direction, -Direction] 两个偏移距离
        Span_item = _first_item(Span_raw, 0.0) if not isinstance(Span_raw, (list, tuple)) else Span_raw

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # ---------- 使用原组件逻辑生成点 ----------
        # 原 CaiZhiThreePointsBuilder 只能接受单个 Span。
        # 为保持“严格按原组件代码实现”，当 Span 为列表时：
        #   - 调用两次 builder：一次用 span_minus 得到 P_minus（其 P_plus 忽略）
        #   - 一次用 span_plus  得到 P_plus  （其 P_minus 忽略）
        # 然后将两次结果合并为最终 OffsetPts / SpanVectors / PointList。
        builder_minus = CaiZhiThreePointsBuilder(
            caizhi_pts=CaiZhiPts,
            index_a=IndexA,
            index_b=IndexB,
            direction=Direction,
            span=span_minus
        )
        PLm, BasePoint, OffsetPts_m, ExtraPoint, DirUnit, SpanVectors_m = builder_minus.build()

        builder_plus = CaiZhiThreePointsBuilder(
            caizhi_pts=CaiZhiPts,
            index_a=IndexA,
            index_b=IndexB,
            direction=Direction,
            span=span_plus
        )
        PLp, BasePoint_p, OffsetPts_p, ExtraPoint_p, DirUnit_p, SpanVectors_p = builder_plus.build()

        # 合并（以 minus 的 Base/Extra/DirUnit 为准；两次应一致）
        P_minus = None
        P_plus = None
        try:
            if OffsetPts_m and len(OffsetPts_m) >= 1:
                P_minus = OffsetPts_m[0]
        except:
            P_minus = None
        try:
            if OffsetPts_p and len(OffsetPts_p) >= 2:
                P_plus = OffsetPts_p[1]
            elif OffsetPts_p and len(OffsetPts_p) >= 1:
                # 兜底：某些实现可能只返回 1 个点
                P_plus = OffsetPts_p[-1]
        except:
            P_plus = None

        OffsetPts = [P_minus, P_plus]
        SpanVectors = []
        try:
            # 与组件约定一致：V_minus=-DirUnit*span_minus, V_plus=+DirUnit*span_plus
            if DirUnit is None:
                DirUnit = DirUnit_p
            v_minus = rg.Vector3d(DirUnit);
            v_minus.Unitize()
            v_minus *= (-span_minus)
            v_plus = rg.Vector3d(DirUnit);
            v_plus.Unitize()
            v_plus *= (span_plus)
            SpanVectors = [v_minus, v_plus]
        except:
            SpanVectors = []

        PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder3__PointList = pl_flat
        self.CaiZhiThreePointsBuilder3__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder3__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder3__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder3__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder3__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::3 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder3__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts3__Face = Face
        self.UniqueRectangleFrom3Pts3__AB = AB

        # ---------- CaiZhiSupportLinkLines::3 ----------
        Direction2 = self.CaiZhiThreePointsBuilder3__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 5
        SupportPts = self.CaiZhiThreePointsBuilder3__OffsetPts

        solver = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines3__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines3__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines3__OffsetLine = line_seg

        self.LogLines.append(
            "Step 6 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                   span_plus, span_minus,
                                                                                   line_seg is not None))

    # -------------------------------
    # Step 7：耍頭與慢栱相列二 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::4、UniqueRectangleFrom3Pts::4、CaiZhiSupportLinkLines::4
    # -------------------------------
    def step7_shuatou_mangong2_support_pts(self):
        self.LogLines.append(
            "Step 7：耍頭與慢栱相列二 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- CaiZhiThreePointsBuilder::4 ----------
        Direction = self.PlacePlane.YAxis
        CaiZhiPts = self.PointsOnLineByCumsum__PointList
        IndexA = 4
        IndexB = 3

        # Span 来自数据库：ShuaTouInLineWManGong2__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("ShuaTouInLineWManGong2__axis2support", None)
        except:
            Span_raw = None

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        if abs(span_plus - span_minus) < 1e-12:
            builder4 = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder4.build()
        else:
            # +Direction
            builder4_p = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PLp, BasePoint, OffsetPts_p, ExtraPoint, DirUnit, SpanVectors_p = builder4_p.build()

            # -Direction
            builder4_m = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_minus
            )
            PLm, BasePoint_m, OffsetPts_m, ExtraPoint_m, DirUnit_m, SpanVectors_m = builder4_m.build()

            P_plus = None
            P_minus = None
            try:
                if OffsetPts_p and len(OffsetPts_p) >= 2:
                    P_plus = OffsetPts_p[1]
                elif OffsetPts_p:
                    P_plus = OffsetPts_p[-1]
            except:
                P_plus = None
            try:
                if OffsetPts_m and len(OffsetPts_m) >= 1:
                    P_minus = OffsetPts_m[0]
            except:
                P_minus = None

            OffsetPts = [P_minus, P_plus]
            SpanVectors = []
            try:
                if DirUnit is None:
                    DirUnit = DirUnit_m
            except:
                pass
            try:
                v_minus = rg.Vector3d(DirUnit);
                v_minus.Unitize();
                v_minus *= (-span_minus)
                v_plus = rg.Vector3d(DirUnit);
                v_plus.Unitize();
                v_plus *= (span_plus)
                SpanVectors = [v_minus, v_plus]
            except:
                SpanVectors = []
            PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder4__PointList = pl_flat
        self.CaiZhiThreePointsBuilder4__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder4__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder4__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder4__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder4__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::4 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder4__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts4__Face = Face
        self.UniqueRectangleFrom3Pts4__AB = AB

        # ---------- CaiZhiSupportLinkLines::4 ----------
        Direction2 = self.CaiZhiThreePointsBuilder4__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 5
        SupportPts = self.CaiZhiThreePointsBuilder4__OffsetPts

        solver4 = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver4.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines4__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines4__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines4__OffsetLine = line_seg

        self.LogLines.append(
            "Step 7 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                   span_plus, span_minus,
                                                                                   line_seg is not None))

    # -------------------------------
    # Step 8：由昂與角耍頭相列 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::5、UniqueRectangleFrom3Pts::5、CaiZhiSupportLinkLines::5
    # -------------------------------
    def step8_youang_jiaoshuatou_support_pts(self):
        self.LogLines.append(
            "Step 8：由昂與角耍頭相列 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines）…")

        # ---------- CaiZhiThreePointsBuilder::5 ----------
        Direction = self.PlaneXYBisectorVectors__Bisector_U
        CaiZhiPts = self.PointsOnLineByCumsum__PointList
        IndexA = 4
        IndexB = 3

        # Span 来自数据库：YouAngInLineWJiaoShuaTou__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("YouAngInLineWJiaoShuaTou__axis2support", None)
        except:
            Span_raw = None

        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        if abs(span_plus - span_minus) < 1e-12:
            builder5 = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder5.build()
        else:
            # +Direction
            builder5_p = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_plus
            )
            PLp, BasePoint, OffsetPts_p, ExtraPoint, DirUnit, SpanVectors_p = builder5_p.build()

            # -Direction
            builder5_m = CaiZhiThreePointsBuilder(
                caizhi_pts=CaiZhiPts,
                index_a=IndexA,
                index_b=IndexB,
                direction=Direction,
                span=span_minus
            )
            PLm, BasePoint_m, OffsetPts_m, ExtraPoint_m, DirUnit_m, SpanVectors_m = builder5_m.build()

            P_plus = None
            P_minus = None
            try:
                if OffsetPts_p and len(OffsetPts_p) >= 2:
                    P_plus = OffsetPts_p[1]
                elif OffsetPts_p:
                    P_plus = OffsetPts_p[-1]
            except:
                P_plus = None
            try:
                if OffsetPts_m and len(OffsetPts_m) >= 1:
                    P_minus = OffsetPts_m[0]
            except:
                P_minus = None

            OffsetPts = [P_minus, P_plus]
            SpanVectors = []
            try:
                if DirUnit is None:
                    DirUnit = DirUnit_m
            except:
                pass
            try:
                v_minus = rg.Vector3d(DirUnit);
                v_minus.Unitize();
                v_minus *= (-span_minus)
                v_plus = rg.Vector3d(DirUnit);
                v_plus.Unitize();
                v_plus *= (span_plus)
                SpanVectors = [v_minus, v_plus]
            except:
                SpanVectors = []
            PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder5__PointList = pl_flat
        self.CaiZhiThreePointsBuilder5__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder5__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder5__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder5__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder5__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::5 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder5__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts5__Face = Face
        self.UniqueRectangleFrom3Pts5__AB = AB

        # ---------- CaiZhiSupportLinkLines::5 ----------
        Direction2 = self.CaiZhiThreePointsBuilder5__SpanVectors
        CaiZhiPts2 = self.PointsOnLineByCumsum__PointList
        Index = 5
        SupportPts = self.CaiZhiThreePointsBuilder5__OffsetPts

        solver5 = CaiZhiSupportLinkLines(Direction2, CaiZhiPts2, Index, SupportPts)
        OffsetPts2, LinkLines = solver5.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines5__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines5__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines5__OffsetLine = line_seg

        self.LogLines.append(
            "Step 8 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                   span_plus, span_minus,
                                                                                   line_seg is not None))

    # -------------------------------
    # Step 9：瓜子栱與令栱相列二 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::6、UniqueRectangleFrom3Pts::6、CaiZhiSupportLinkLines_ByBasePoint::0
    # -------------------------------
    def step9_guazigong_linggong2_support_pts(self):
        self.LogLines.append(
            "Step 9：瓜子栱與令栱相列二 支撑点（3Pts / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines_ByBasePoint）…")

        # ---------- CaiZhiThreePointsBuilder::6（按描述：BasePoint/ExtraPoint 外部给定）----------
        Direction = self.PlacePlane.YAxis

        # BasePoint：来自 Step6 的 OffsetPts[0]
        BasePoint = None
        try:
            bp_src = self.CaiZhiThreePointsBuilder3__OffsetPts
            if bp_src and len(bp_src) >= 1:
                BasePoint = bp_src[0]
        except:
            BasePoint = None

        # Span：来自数据库 GuaZiGongInLineWLingGong2__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("GuaZiGongInLineWLingGong2__axis2support", None)
        except:
            Span_raw = None
        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # ExtraPoint：PointsOnLine PointList[3] 沿 Step6 SpanVectors[0] 方向移动复制
        ExtraPoint = None
        try:
            p_src = self.PointsOnLineByCumsum__PointList
            p3 = p_src[3] if (p_src and len(p_src) > 3) else None
            v_src = self.CaiZhiThreePointsBuilder3__SpanVectors
            v0 = v_src[0] if (v_src and len(v_src) > 0) else None
            if p3 is not None and v0 is not None:
                ExtraPoint = rg.Point3d(p3)
                ExtraPoint = rg.Point3d(ExtraPoint.X + v0.X, ExtraPoint.Y + v0.Y, ExtraPoint.Z + v0.Z)
        except:
            ExtraPoint = None

        # DirUnit
        DirUnit = rg.Vector3d(Direction)
        if DirUnit.IsTiny(1e-12):
            DirUnit = rg.Vector3d(0, 1, 0)
        try:
            DirUnit.Unitize()
        except:
            pass

        # OffsetPts：按约定 [P_minus, P_plus]，且 span 输入顺序为 [+Direction, -Direction]
        P_plus = None
        P_minus = None
        try:
            if BasePoint is not None:
                # -Direction 偏移 span_minus
                P_minus = rg.Point3d(BasePoint)
                P_minus = rg.Point3d(P_minus.X - DirUnit.X * span_minus,
                                     P_minus.Y - DirUnit.Y * span_minus,
                                     P_minus.Z - DirUnit.Z * span_minus)
                # +Direction 偏移 span_plus
                P_plus = rg.Point3d(BasePoint)
                P_plus = rg.Point3d(P_plus.X + DirUnit.X * span_plus,
                                    P_plus.Y + DirUnit.Y * span_plus,
                                    P_plus.Z + DirUnit.Z * span_plus)
        except:
            P_minus, P_plus = None, None

        OffsetPts = [P_minus, P_plus]
        SpanVectors = []
        try:
            v_minus = rg.Vector3d(DirUnit);
            v_minus *= (-span_minus)
            v_plus = rg.Vector3d(DirUnit);
            v_plus *= (span_plus)
            SpanVectors = [v_minus, v_plus]
        except:
            SpanVectors = []

        PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder6__PointList = pl_flat
        self.CaiZhiThreePointsBuilder6__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder6__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder6__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder6__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder6__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::6 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder6__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts6__Face = Face
        self.UniqueRectangleFrom3Pts6__AB = AB

        # ---------- CaiZhiSupportLinkLines_ByBasePoint::0 ----------
        Direction2 = self.CaiZhiThreePointsBuilder6__SpanVectors
        BasePt = None
        try:
            bp2_src = self.CaiZhiSupportLinkLines3__OffsetPts
            if bp2_src and len(bp2_src) >= 1:
                BasePt = bp2_src[0]
        except:
            BasePt = None
        SupportPts = self.CaiZhiThreePointsBuilder6__OffsetPts

        solver_bp0 = CaiZhiSupportLinkLines_ByBasePoint(Direction2, BasePt, SupportPts)
        OffsetPts2, LinkLines = solver_bp0.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint0__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine = line_seg

        self.LogLines.append(
            "Step 9 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                   span_plus, span_minus,
                                                                                   line_seg is not None))

    # -------------------------------
    # Step 10：瓜子栱與令栱相列一 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::7、UniqueRectangleFrom3Pts::7、CaiZhiSupportLinkLines_ByBasePoint::1
    # -------------------------------
    def step10_guazigong_linggong1_support_pts(self):
        self.LogLines.append(
            "Step 10：瓜子栱與令栱相列一 支撑点（3Pts / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines_ByBasePoint）…")

        # Direction：参考平面 X 轴
        Direction = self.PlacePlane.XAxis

        # BasePoint：来自 Step7 的 OffsetPts[0]
        BasePoint = None
        try:
            bp_src = self.CaiZhiThreePointsBuilder4__OffsetPts
            if bp_src and len(bp_src) >= 1:
                BasePoint = bp_src[0]
        except:
            BasePoint = None

        # Span：来自数据库 GuaZiGongInLineWLingGong1__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("GuaZiGongInLineWLingGong1__axis2support", None)
        except:
            Span_raw = None
        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # ExtraPoint：PointsOnLine PointList[3] 沿 Step7 SpanVectors[0] 方向移动复制
        ExtraPoint = None
        try:
            p_src = self.PointsOnLineByCumsum__PointList
            p3 = p_src[3] if (p_src and len(p_src) > 3) else None
            v_src = self.CaiZhiThreePointsBuilder4__SpanVectors
            v0 = v_src[0] if (v_src and len(v_src) > 0) else None
            if p3 is not None and v0 is not None:
                ExtraPoint = rg.Point3d(p3)
                ExtraPoint = rg.Point3d(ExtraPoint.X + v0.X, ExtraPoint.Y + v0.Y, ExtraPoint.Z + v0.Z)
        except:
            ExtraPoint = None

        # DirUnit
        DirUnit = rg.Vector3d(Direction)
        if DirUnit.IsTiny(1e-12):
            DirUnit = rg.Vector3d(1, 0, 0)
        try:
            DirUnit.Unitize()
        except:
            pass

        # OffsetPts：保持与 Step9 相同约定 [P_minus, P_plus]，且 Span 顺序为 [+Direction, -Direction]
        P_plus = None
        P_minus = None
        try:
            if BasePoint is not None:
                # -Direction 偏移 span_minus
                P_minus = rg.Point3d(BasePoint)
                P_minus = rg.Point3d(P_minus.X - DirUnit.X * span_minus,
                                     P_minus.Y - DirUnit.Y * span_minus,
                                     P_minus.Z - DirUnit.Z * span_minus)
                # +Direction 偏移 span_plus
                P_plus = rg.Point3d(BasePoint)
                P_plus = rg.Point3d(P_plus.X + DirUnit.X * span_plus,
                                    P_plus.Y + DirUnit.Y * span_plus,
                                    P_plus.Z + DirUnit.Z * span_plus)
        except:
            P_minus, P_plus = None, None

        OffsetPts = [P_minus, P_plus]
        SpanVectors = []
        try:
            v_minus = rg.Vector3d(DirUnit);
            v_minus *= (-span_minus)
            v_plus = rg.Vector3d(DirUnit);
            v_plus *= (span_plus)
            SpanVectors = [v_minus, v_plus]
        except:
            SpanVectors = []

        PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder7__PointList = pl_flat
        self.CaiZhiThreePointsBuilder7__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder7__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder7__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder7__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder7__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::7 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder7__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts7__Face = Face
        self.UniqueRectangleFrom3Pts7__AB = AB

        # ---------- CaiZhiSupportLinkLines_ByBasePoint::1 ----------
        Direction2 = self.CaiZhiThreePointsBuilder7__SpanVectors

        BasePt = None
        try:
            bp2_src = self.CaiZhiSupportLinkLines4__OffsetPts
            if bp2_src and len(bp2_src) >= 1:
                BasePt = bp2_src[0]
        except:
            BasePt = None

        SupportPts = self.CaiZhiThreePointsBuilder7__OffsetPts

        solver_bp1 = CaiZhiSupportLinkLines_ByBasePoint(Direction2, BasePt, SupportPts)
        OffsetPts2, LinkLines = solver_bp1.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint1__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine = line_seg

        self.LogLines.append(
            "Step 10 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                    span_plus, span_minus,
                                                                                    line_seg is not None))

    # -------------------------------
    # Step 11：令栱與小栱頭相列一 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::8、UniqueRectangleFrom3Pts::8、CaiZhiSupportLinkLines_ByBasePoint::2
    # -------------------------------
    def step11_linggong_xiaogongtou1_support_pts(self):
        self.LogLines.append(
            "Step 11：令栱與小栱頭相列一 支撑点（3Pts / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines_ByBasePoint）…")

        # Direction：参考平面 X 轴
        Direction = self.PlacePlane.XAxis

        # BasePoint：来自 CaiZhiThreePointsBuilder::5 的 OffsetPts[1]
        BasePoint = None
        try:
            bp_src = self.CaiZhiThreePointsBuilder5__OffsetPts
            if bp_src and len(bp_src) > 1:
                BasePoint = bp_src[1]
        except:
            BasePoint = None

        # Span：来自数据库 LingGongInLineWXiaoGongTou1__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("LingGongInLineWXiaoGongTou1__axis2support", None)
        except:
            Span_raw = None
        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # ExtraPoint：PointsOnLine PointList[3] 沿 CaiZhiThreePointsBuilder::5 的 SpanVectors[1] 方向移动复制
        ExtraPoint = None
        try:
            p_src = self.PointsOnLineByCumsum__PointList
            p3 = p_src[3] if (p_src and len(p_src) > 3) else None
            v_src = self.CaiZhiThreePointsBuilder5__SpanVectors
            v1 = v_src[1] if (v_src and len(v_src) > 1) else None
            if p3 is not None and v1 is not None:
                ExtraPoint = rg.Point3d(p3)
                ExtraPoint = rg.Point3d(ExtraPoint.X + v1.X, ExtraPoint.Y + v1.Y, ExtraPoint.Z + v1.Z)
        except:
            ExtraPoint = None

        # DirUnit
        DirUnit = rg.Vector3d(Direction)
        if DirUnit.IsTiny(1e-12):
            DirUnit = rg.Vector3d(1, 0, 0)
        try:
            DirUnit.Unitize()
        except:
            pass

        # OffsetPts：保持与 Step9/10 相同约定 [P_minus, P_plus]，且 Span 顺序为 [+Direction, -Direction]
        P_plus = None
        P_minus = None
        try:
            if BasePoint is not None:
                # -Direction 偏移 span_minus
                P_minus = rg.Point3d(BasePoint)
                P_minus = rg.Point3d(P_minus.X - DirUnit.X * span_minus,
                                     P_minus.Y - DirUnit.Y * span_minus,
                                     P_minus.Z - DirUnit.Z * span_minus)
                # +Direction 偏移 span_plus
                P_plus = rg.Point3d(BasePoint)
                P_plus = rg.Point3d(P_plus.X + DirUnit.X * span_plus,
                                    P_plus.Y + DirUnit.Y * span_plus,
                                    P_plus.Z + DirUnit.Z * span_plus)
        except:
            P_minus, P_plus = None, None

        OffsetPts = [P_minus, P_plus]
        SpanVectors = []
        try:
            v_minus = rg.Vector3d(DirUnit);
            v_minus *= (-span_minus)
            v_plus = rg.Vector3d(DirUnit);
            v_plus *= (span_plus)
            SpanVectors = [v_minus, v_plus]
        except:
            SpanVectors = []

        PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder8__PointList = pl_flat
        self.CaiZhiThreePointsBuilder8__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder8__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder8__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder8__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder8__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::8 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder8__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts8__Face = Face
        self.UniqueRectangleFrom3Pts8__AB = AB

        # ---------- CaiZhiSupportLinkLines_ByBasePoint::2 ----------
        Direction2 = self.CaiZhiThreePointsBuilder8__SpanVectors

        BasePt = None
        try:
            bp2_src = self.CaiZhiSupportLinkLines5__OffsetPts
            if bp2_src and len(bp2_src) > 1:
                BasePt = bp2_src[1]
        except:
            BasePt = None

        SupportPts = self.CaiZhiThreePointsBuilder8__OffsetPts

        solver_bp2 = CaiZhiSupportLinkLines_ByBasePoint(Direction2, BasePt, SupportPts)
        OffsetPts2, LinkLines = solver_bp2.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint2__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint2__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines_ByBasePoint2__OffsetLine = line_seg

        self.LogLines.append(
            "Step 11 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                    span_plus, span_minus,
                                                                                    line_seg is not None))

    # -------------------------------
    # Step 12：令栱與小栱頭相列二 支撑点
    #   核心组件：CaiZhiThreePointsBuilder::9、UniqueRectangleFrom3Pts::9、CaiZhiSupportLinkLines_ByBasePoint::3
    # -------------------------------
    def step12_linggong_xiaogongtou2_support_pts(self):
        self.LogLines.append(
            "Step 12：令栱與小栱頭相列二 支撑点（3Pts / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines_ByBasePoint）…")

        # Direction：参考平面 Y 轴
        Direction = self.PlacePlane.YAxis

        # BasePoint：来自 CaiZhiThreePointsBuilder::5 的 OffsetPts[1]
        BasePoint = None
        try:
            bp_src = self.CaiZhiThreePointsBuilder5__OffsetPts
            if bp_src and len(bp_src) > 1:
                BasePoint = bp_src[1]
        except:
            BasePoint = None

        # Span：来自数据库 LingGongInLineWXiaoGongTou2__axis2support
        Span_raw = None
        try:
            Span_raw = self.AllDict.get("LingGongInLineWXiaoGongTou2__axis2support", None)
        except:
            Span_raw = None
        span_plus, span_minus = _parse_span_plus_minus(Span_raw, 0.0)

        # ExtraPoint：PointsOnLine PointList[3] 沿 CaiZhiThreePointsBuilder::5 的 SpanVectors[1] 方向移动复制
        ExtraPoint = None
        try:
            p_src = self.PointsOnLineByCumsum__PointList
            p3 = p_src[3] if (p_src and len(p_src) > 3) else None
            v_src = self.CaiZhiThreePointsBuilder5__SpanVectors
            v1 = v_src[1] if (v_src and len(v_src) > 1) else None
            if p3 is not None and v1 is not None:
                ExtraPoint = rg.Point3d(p3)
                ExtraPoint = rg.Point3d(ExtraPoint.X + v1.X, ExtraPoint.Y + v1.Y, ExtraPoint.Z + v1.Z)
        except:
            ExtraPoint = None

        # DirUnit
        DirUnit = rg.Vector3d(Direction)
        if DirUnit.IsTiny(1e-12):
            DirUnit = rg.Vector3d(0, 1, 0)
        try:
            DirUnit.Unitize()
        except:
            pass

        # OffsetPts：保持与 Step9/10/11 相同约定 [P_minus, P_plus]，且 Span 顺序为 [+Direction, -Direction]
        P_plus = None
        P_minus = None
        try:
            if BasePoint is not None:
                # -Direction 偏移 span_minus
                P_minus = rg.Point3d(BasePoint)
                P_minus = rg.Point3d(P_minus.X - DirUnit.X * span_minus,
                                     P_minus.Y - DirUnit.Y * span_minus,
                                     P_minus.Z - DirUnit.Z * span_minus)
                # +Direction 偏移 span_plus
                P_plus = rg.Point3d(BasePoint)
                P_plus = rg.Point3d(P_plus.X + DirUnit.X * span_plus,
                                    P_plus.Y + DirUnit.Y * span_plus,
                                    P_plus.Z + DirUnit.Z * span_plus)
        except:
            P_minus, P_plus = None, None

        OffsetPts = [P_minus, P_plus]
        SpanVectors = []
        try:
            v_minus = rg.Vector3d(DirUnit);
            v_minus *= (-span_minus)
            v_plus = rg.Vector3d(DirUnit);
            v_plus *= (span_plus)
            SpanVectors = [v_minus, v_plus]
        except:
            SpanVectors = []

        PointList = [ExtraPoint, P_minus, P_plus]

        pl_flat = []
        _flatten_items(PointList, pl_flat)
        self.CaiZhiThreePointsBuilder9__PointList = pl_flat
        self.CaiZhiThreePointsBuilder9__BasePoint = BasePoint

        off_flat = []
        _flatten_items(OffsetPts, off_flat)
        self.CaiZhiThreePointsBuilder9__OffsetPts = off_flat
        self.CaiZhiThreePointsBuilder9__ExtraPoint = ExtraPoint
        self.CaiZhiThreePointsBuilder9__DirUnit = DirUnit

        sv_flat = []
        _flatten_items(SpanVectors, sv_flat)
        self.CaiZhiThreePointsBuilder9__SpanVectors = sv_flat

        # ---------- UniqueRectangleFrom3Pts::9 ----------
        Face = None
        AB = None
        Pts = self.CaiZhiThreePointsBuilder9__PointList
        if Pts:
            try:
                ur = UniqueRectangleFrom3Pts(Pts)
                Face, AB = ur.build()
            except:
                Face, AB = None, None

        self.UniqueRectangleFrom3Pts9__Face = Face
        self.UniqueRectangleFrom3Pts9__AB = AB

        # ---------- CaiZhiSupportLinkLines_ByBasePoint::3 ----------
        Direction2 = self.CaiZhiThreePointsBuilder9__SpanVectors

        BasePt = None
        try:
            bp2_src = self.CaiZhiSupportLinkLines5__OffsetPts
            if bp2_src and len(bp2_src) > 1:
                BasePt = bp2_src[1]
        except:
            BasePt = None

        SupportPts = self.CaiZhiThreePointsBuilder9__OffsetPts

        solver_bp3 = CaiZhiSupportLinkLines_ByBasePoint(Direction2, BasePt, SupportPts)
        OffsetPts2, LinkLines = solver_bp3.solve()

        off2_flat = []
        _flatten_items(OffsetPts2, off2_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint3__OffsetPts = off2_flat

        ll_flat = []
        _flatten_items(LinkLines, ll_flat)
        self.CaiZhiSupportLinkLines_ByBasePoint3__LinkLines = ll_flat

        # ---------- 将 OffsetPts 连为直线端 ----------
        line_seg = None
        try:
            if off2_flat and len(off2_flat) >= 2:
                line_seg = rg.Line(off2_flat[0], off2_flat[-1])
        except:
            line_seg = None
        self.CaiZhiSupportLinkLines_ByBasePoint3__OffsetLine = line_seg

        self.LogLines.append(
            "Step 12 完成：3Pts={} LinkLines={} Span=[+{},-{}] OffsetLine={}".format(len(pl_flat), len(ll_flat),
                                                                                    span_plus, span_minus,
                                                                                    line_seg is not None))

    # -------------------------------
    # run
    # -------------------------------
    def run(self):
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        # 当前做到 step12
        self.step1_read_db()
        self.step2_cai_zhi_pattern_points()
        self.step3_chaang_nidaogong_support_pts()
        self.step4_chaang_nidaogong_support_pts_2()
        self.step5_jiaoang_jiaohuagong_support_pts()
        self.step6_shuatou_mangong1_support_pts()
        self.step7_shuatou_mangong2_support_pts()
        self.step8_youang_jiaoshuatou_support_pts()
        self.step9_guazigong_linggong2_support_pts()
        self.step10_guazigong_linggong1_support_pts()
        self.step11_linggong_xiaogongtou1_support_pts()
        self.step12_linggong_xiaogongtou2_support_pts()

        # 先占位：后续 step 完成后再组装 AbsStructRep
        self.AbsStructRep = None

        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GhPython 组件输出绑定区
# =========================================================

if __name__ == "__main__":

    # --- 输入端兜底（避免未连接变红）---
    try:
        _db = DBPath
    except:
        _db = None

    try:
        _pp = PlacePlane
    except:
        _pp = None

    try:
        _rf = Refresh
    except:
        _rf = False

    solver = AbsStructRep_SiPU_Corner_ComponentAssemblySolver(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        ghenv=ghenv
    )
    solver.run()

    # --------- 对外主输出（当前 step1 先占位）---------
    AbsStructRep = getattr(solver, "AbsStructRep", None)
    Log = getattr(solver, "Log", None)

    # --------- Step 1 输出（内部保留/可暴露）---------
    Value = getattr(solver, "Value", None)
    All = getattr(solver, "All", None)
    AllDict = getattr(solver, "AllDict", None)
    DBLog = getattr(solver, "DBLog", None)

    # --------- Step 2 输出（内部保留/可暴露）---------
    PointsOnLineByCumsum__BaseLine = getattr(solver, "PointsOnLineByCumsum__BaseLine", None)
    PointsOnLineByCumsum__SumValue = getattr(solver, "PointsOnLineByCumsum__SumValue", None)
    PointsOnLineByCumsum__ReversedList = getattr(solver, "PointsOnLineByCumsum__ReversedList", None)
    PointsOnLineByCumsum__CumList = getattr(solver, "PointsOnLineByCumsum__CumList", None)
    PointsOnLineByCumsum__PointList = getattr(solver, "PointsOnLineByCumsum__PointList", None)

    # --------- Step 3 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder__PointList = getattr(solver, "CaiZhiThreePointsBuilder__PointList", None)
    CaiZhiThreePointsBuilder__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder__BasePoint", None)
    CaiZhiThreePointsBuilder__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder__OffsetPts", None)
    CaiZhiThreePointsBuilder__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder__ExtraPoint", None)
    CaiZhiThreePointsBuilder__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder__DirUnit", None)
    CaiZhiThreePointsBuilder__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder__SpanVectors", None)

    UniqueRectangleFrom3Pts__Face = getattr(solver, "UniqueRectangleFrom3Pts__Face", None)
    UniqueRectangleFrom3Pts__AB = getattr(solver, "UniqueRectangleFrom3Pts__AB", None)

    CaiZhiSupportLinkLines__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines__OffsetPts", None)
    CaiZhiSupportLinkLines__LinkLines = getattr(solver, "CaiZhiSupportLinkLines__LinkLines", None)

    # --------- Step 4 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder1__PointList = getattr(solver, "CaiZhiThreePointsBuilder1__PointList", None)
    CaiZhiThreePointsBuilder1__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder1__BasePoint", None)
    CaiZhiThreePointsBuilder1__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder1__OffsetPts", None)
    CaiZhiThreePointsBuilder1__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder1__ExtraPoint", None)
    CaiZhiThreePointsBuilder1__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder1__DirUnit", None)
    CaiZhiThreePointsBuilder1__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder1__SpanVectors", None)

    UniqueRectangleFrom3Pts1__Face = getattr(solver, "UniqueRectangleFrom3Pts1__Face", None)
    UniqueRectangleFrom3Pts1__AB = getattr(solver, "UniqueRectangleFrom3Pts1__AB", None)

    CaiZhiSupportLinkLines1__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines1__OffsetPts", None)
    CaiZhiSupportLinkLines1__LinkLines = getattr(solver, "CaiZhiSupportLinkLines1__LinkLines", None)

    # --------- Step 5 输出（内部保留/可暴露）---------
    PlaneXYBisectorVectors__Bisector_U = getattr(solver, "PlaneXYBisectorVectors__Bisector_U", None)
    PlaneXYBisectorVectors__Bisector_U_Neg = getattr(solver, "PlaneXYBisectorVectors__Bisector_U_Neg", None)
    PlaneXYBisectorVectors__XAxis_U = getattr(solver, "PlaneXYBisectorVectors__XAxis_U", None)
    PlaneXYBisectorVectors__YAxis_U = getattr(solver, "PlaneXYBisectorVectors__YAxis_U", None)
    PlaneXYBisectorVectors__ZAxis_U = getattr(solver, "PlaneXYBisectorVectors__ZAxis_U", None)

    CaiZhiThreePointsBuilder2__PointList = getattr(solver, "CaiZhiThreePointsBuilder2__PointList", None)
    CaiZhiThreePointsBuilder2__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder2__BasePoint", None)
    CaiZhiThreePointsBuilder2__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder2__OffsetPts", None)
    CaiZhiThreePointsBuilder2__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder2__ExtraPoint", None)
    CaiZhiThreePointsBuilder2__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder2__DirUnit", None)
    CaiZhiThreePointsBuilder2__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder2__SpanVectors", None)

    UniqueRectangleFrom3Pts2__Face = getattr(solver, "UniqueRectangleFrom3Pts2__Face", None)
    UniqueRectangleFrom3Pts2__AB = getattr(solver, "UniqueRectangleFrom3Pts2__AB", None)

    CaiZhiSupportLinkLines2__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines2__OffsetPts", None)
    CaiZhiSupportLinkLines2__LinkLines = getattr(solver, "CaiZhiSupportLinkLines2__LinkLines", None)

    # --------- Step 6 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder3__PointList = getattr(solver, "CaiZhiThreePointsBuilder3__PointList", None)
    CaiZhiThreePointsBuilder3__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder3__BasePoint", None)
    CaiZhiThreePointsBuilder3__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder3__OffsetPts", None)
    CaiZhiThreePointsBuilder3__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder3__ExtraPoint", None)
    CaiZhiThreePointsBuilder3__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder3__DirUnit", None)
    CaiZhiThreePointsBuilder3__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder3__SpanVectors", None)

    UniqueRectangleFrom3Pts3__Face = getattr(solver, "UniqueRectangleFrom3Pts3__Face", None)
    UniqueRectangleFrom3Pts3__AB = getattr(solver, "UniqueRectangleFrom3Pts3__AB", None)

    CaiZhiSupportLinkLines3__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines3__OffsetPts", None)
    CaiZhiSupportLinkLines3__LinkLines = getattr(solver, "CaiZhiSupportLinkLines3__LinkLines", None)
    CaiZhiSupportLinkLines3__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines3__OffsetLine", None)

    # --------- Step 7 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder4__PointList = getattr(solver, "CaiZhiThreePointsBuilder4__PointList", None)
    CaiZhiThreePointsBuilder4__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder4__BasePoint", None)
    CaiZhiThreePointsBuilder4__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder4__OffsetPts", None)
    CaiZhiThreePointsBuilder4__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder4__ExtraPoint", None)
    CaiZhiThreePointsBuilder4__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder4__DirUnit", None)
    CaiZhiThreePointsBuilder4__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder4__SpanVectors", None)

    UniqueRectangleFrom3Pts4__Face = getattr(solver, "UniqueRectangleFrom3Pts4__Face", None)
    UniqueRectangleFrom3Pts4__AB = getattr(solver, "UniqueRectangleFrom3Pts4__AB", None)

    CaiZhiSupportLinkLines4__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines4__OffsetPts", None)
    CaiZhiSupportLinkLines4__LinkLines = getattr(solver, "CaiZhiSupportLinkLines4__LinkLines", None)
    CaiZhiSupportLinkLines4__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines4__OffsetLine", None)

    # --------- Step 8 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder5__PointList = getattr(solver, "CaiZhiThreePointsBuilder5__PointList", None)
    CaiZhiThreePointsBuilder5__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder5__BasePoint", None)
    CaiZhiThreePointsBuilder5__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder5__OffsetPts", None)
    CaiZhiThreePointsBuilder5__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder5__ExtraPoint", None)
    CaiZhiThreePointsBuilder5__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder5__DirUnit", None)
    CaiZhiThreePointsBuilder5__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder5__SpanVectors", None)

    UniqueRectangleFrom3Pts5__Face = getattr(solver, "UniqueRectangleFrom3Pts5__Face", None)
    UniqueRectangleFrom3Pts5__AB = getattr(solver, "UniqueRectangleFrom3Pts5__AB", None)

    CaiZhiSupportLinkLines5__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines5__OffsetPts", None)
    CaiZhiSupportLinkLines5__LinkLines = getattr(solver, "CaiZhiSupportLinkLines5__LinkLines", None)
    CaiZhiSupportLinkLines5__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines5__OffsetLine", None)

    # --------- Step 9 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder6__PointList = getattr(solver, "CaiZhiThreePointsBuilder6__PointList", None)
    CaiZhiThreePointsBuilder6__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder6__BasePoint", None)
    CaiZhiThreePointsBuilder6__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder6__OffsetPts", None)
    CaiZhiThreePointsBuilder6__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder6__ExtraPoint", None)
    CaiZhiThreePointsBuilder6__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder6__DirUnit", None)
    CaiZhiThreePointsBuilder6__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder6__SpanVectors", None)

    UniqueRectangleFrom3Pts6__Face = getattr(solver, "UniqueRectangleFrom3Pts6__Face", None)
    UniqueRectangleFrom3Pts6__AB = getattr(solver, "UniqueRectangleFrom3Pts6__AB", None)

    CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint0__LinkLines = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint0__LinkLines",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine",
                                                              None)

    # --------- Step 10 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder7__PointList = getattr(solver, "CaiZhiThreePointsBuilder7__PointList", None)
    CaiZhiThreePointsBuilder7__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder7__BasePoint", None)
    CaiZhiThreePointsBuilder7__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder7__OffsetPts", None)
    CaiZhiThreePointsBuilder7__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder7__ExtraPoint", None)
    CaiZhiThreePointsBuilder7__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder7__DirUnit", None)
    CaiZhiThreePointsBuilder7__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder7__SpanVectors", None)

    UniqueRectangleFrom3Pts7__Face = getattr(solver, "UniqueRectangleFrom3Pts7__Face", None)
    UniqueRectangleFrom3Pts7__AB = getattr(solver, "UniqueRectangleFrom3Pts7__AB", None)

    CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint1__LinkLines = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint1__LinkLines",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine",
                                                              None)

    # --------- Step 11 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder8__PointList = getattr(solver, "CaiZhiThreePointsBuilder8__PointList", None)
    CaiZhiThreePointsBuilder8__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder8__BasePoint", None)
    CaiZhiThreePointsBuilder8__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder8__OffsetPts", None)
    CaiZhiThreePointsBuilder8__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder8__ExtraPoint", None)
    CaiZhiThreePointsBuilder8__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder8__DirUnit", None)
    CaiZhiThreePointsBuilder8__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder8__SpanVectors", None)

    UniqueRectangleFrom3Pts8__Face = getattr(solver, "UniqueRectangleFrom3Pts8__Face", None)
    UniqueRectangleFrom3Pts8__AB = getattr(solver, "UniqueRectangleFrom3Pts8__AB", None)

    CaiZhiSupportLinkLines_ByBasePoint2__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint2__OffsetPts",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint2__LinkLines = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint2__LinkLines",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint2__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint2__OffsetLine",
                                                              None)

    # --------- Step 12 输出（内部保留/可暴露）---------
    CaiZhiThreePointsBuilder9__PointList = getattr(solver, "CaiZhiThreePointsBuilder9__PointList", None)
    CaiZhiThreePointsBuilder9__BasePoint = getattr(solver, "CaiZhiThreePointsBuilder9__BasePoint", None)
    CaiZhiThreePointsBuilder9__OffsetPts = getattr(solver, "CaiZhiThreePointsBuilder9__OffsetPts", None)
    CaiZhiThreePointsBuilder9__ExtraPoint = getattr(solver, "CaiZhiThreePointsBuilder9__ExtraPoint", None)
    CaiZhiThreePointsBuilder9__DirUnit = getattr(solver, "CaiZhiThreePointsBuilder9__DirUnit", None)
    CaiZhiThreePointsBuilder9__SpanVectors = getattr(solver, "CaiZhiThreePointsBuilder9__SpanVectors", None)

    UniqueRectangleFrom3Pts9__Face = getattr(solver, "UniqueRectangleFrom3Pts9__Face", None)
    UniqueRectangleFrom3Pts9__AB = getattr(solver, "UniqueRectangleFrom3Pts9__AB", None)

    CaiZhiSupportLinkLines_ByBasePoint3__OffsetPts = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint3__OffsetPts",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint3__LinkLines = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint3__LinkLines",
                                                             None)
    CaiZhiSupportLinkLines_ByBasePoint3__OffsetLine = getattr(solver, "CaiZhiSupportLinkLines_ByBasePoint3__OffsetLine",
                                                              None)

    # --------- 也保留 PlacePlane 便于核对放置逻辑---------
    PlacePlane_Out = getattr(solver, "PlacePlane", None)

    # ======================================================
    # 输出别名（建议在 GH 输出端使用更有语义的命名）
    #   规则：以“构件语义/子构件 type_code”作为前缀，避免 CaiZhiSupportLinkLines3 这类无意义名
    # ======================================================

    # ---- Step2：材栔模式（PointsOnLineByCumsum）----
    PointsOnLine_BaseLine = PointsOnLineByCumsum__BaseLine
    PointsOnLine_SumValue = PointsOnLineByCumsum__SumValue
    PointsOnLine_CumList = PointsOnLineByCumsum__CumList
    PointsOnLine_PointList = PointsOnLineByCumsum__PointList

    # ---- Step3：ChaAngInLineWNiDaoGong1（插昂與泥道栱相列一）----
    ChaAngInLineWNiDaoGong1_3Pts = CaiZhiThreePointsBuilder__PointList
    ChaAngInLineWNiDaoGong1_OffsetPts = CaiZhiSupportLinkLines__OffsetPts
    ChaAngInLineWNiDaoGong1_LinkLines = CaiZhiSupportLinkLines__LinkLines
    ChaAngInLineWNiDaoGong1_Face = UniqueRectangleFrom3Pts__Face
    ChaAngInLineWNiDaoGong1_AB = UniqueRectangleFrom3Pts__AB

    # ---- Step4：ChaAngInLineWNiDaoGong2（插昂與泥道栱相列二）----
    ChaAngInLineWNiDaoGong2_3Pts = CaiZhiThreePointsBuilder1__PointList
    ChaAngInLineWNiDaoGong2_OffsetPts = CaiZhiSupportLinkLines1__OffsetPts
    ChaAngInLineWNiDaoGong2_LinkLines = CaiZhiSupportLinkLines1__LinkLines
    ChaAngInLineWNiDaoGong2_Face = UniqueRectangleFrom3Pts1__Face
    ChaAngInLineWNiDaoGong2_AB = UniqueRectangleFrom3Pts1__AB

    # ---- Step5：JiaoAngInLineWJiaoHuaGong（角昂與角華栱相列）----
    JiaoAngInLineWJiaoHuaGong_BisectorU = PlaneXYBisectorVectors__Bisector_U
    JiaoAngInLineWJiaoHuaGong_3Pts = CaiZhiThreePointsBuilder2__PointList
    JiaoAngInLineWJiaoHuaGong_OffsetPts = CaiZhiSupportLinkLines2__OffsetPts
    JiaoAngInLineWJiaoHuaGong_LinkLines = CaiZhiSupportLinkLines2__LinkLines
    JiaoAngInLineWJiaoHuaGong_Face = UniqueRectangleFrom3Pts2__Face
    JiaoAngInLineWJiaoHuaGong_AB = UniqueRectangleFrom3Pts2__AB

    # ---- Step6：ShuaTouInLineWManGong1（耍頭與慢栱相列一）----
    ShuaTouInLineWManGong1_3Pts = CaiZhiThreePointsBuilder3__PointList
    ShuaTouInLineWManGong1_OffsetPts = CaiZhiSupportLinkLines3__OffsetPts
    ShuaTouInLineWManGong1_LinkLines = CaiZhiSupportLinkLines3__LinkLines
    ShuaTouInLineWManGong1_OffsetLine = CaiZhiSupportLinkLines3__OffsetLine
    ShuaTouInLineWManGong1_Face = UniqueRectangleFrom3Pts3__Face
    ShuaTouInLineWManGong1_AB = UniqueRectangleFrom3Pts3__AB

    # ---- Step7：ShuaTouInLineWManGong2（耍頭與慢栱相列二）----
    ShuaTouInLineWManGong2_3Pts = CaiZhiThreePointsBuilder4__PointList
    ShuaTouInLineWManGong2_OffsetPts = CaiZhiSupportLinkLines4__OffsetPts
    ShuaTouInLineWManGong2_LinkLines = CaiZhiSupportLinkLines4__LinkLines
    ShuaTouInLineWManGong2_OffsetLine = CaiZhiSupportLinkLines4__OffsetLine
    ShuaTouInLineWManGong2_Face = UniqueRectangleFrom3Pts4__Face
    ShuaTouInLineWManGong2_AB = UniqueRectangleFrom3Pts4__AB

    # ---- Step8：YouAngInLineWJiaoShuaTou（由昂與角耍頭相列）----
    YouAngInLineWJiaoShuaTou_3Pts = CaiZhiThreePointsBuilder5__PointList
    YouAngInLineWJiaoShuaTou_OffsetPts = CaiZhiSupportLinkLines5__OffsetPts
    YouAngInLineWJiaoShuaTou_LinkLines = CaiZhiSupportLinkLines5__LinkLines
    YouAngInLineWJiaoShuaTou_OffsetLine = CaiZhiSupportLinkLines5__OffsetLine
    YouAngInLineWJiaoShuaTou_Face = UniqueRectangleFrom3Pts5__Face
    YouAngInLineWJiaoShuaTou_AB = UniqueRectangleFrom3Pts5__AB

    # ---- Step9：GuaZiGongInLineWLingGong2（瓜子栱與令栱相列二）----
    GuaZiGongInLineWLingGong2_3Pts = CaiZhiThreePointsBuilder6__PointList
    GuaZiGongInLineWLingGong2_OffsetPts = CaiZhiSupportLinkLines_ByBasePoint0__OffsetPts
    GuaZiGongInLineWLingGong2_LinkLines = CaiZhiSupportLinkLines_ByBasePoint0__LinkLines
    GuaZiGongInLineWLingGong2_OffsetLine = CaiZhiSupportLinkLines_ByBasePoint0__OffsetLine
    GuaZiGongInLineWLingGong2_Face = UniqueRectangleFrom3Pts6__Face
    GuaZiGongInLineWLingGong2_AB = UniqueRectangleFrom3Pts6__AB

    # ---- Step10：GuaZiGongInLineWLingGong1（瓜子栱與令栱相列一）----
    GuaZiGongInLineWLingGong1_3Pts = CaiZhiThreePointsBuilder7__PointList
    GuaZiGongInLineWLingGong1_OffsetPts = CaiZhiSupportLinkLines_ByBasePoint1__OffsetPts
    GuaZiGongInLineWLingGong1_LinkLines = CaiZhiSupportLinkLines_ByBasePoint1__LinkLines
    GuaZiGongInLineWLingGong1_OffsetLine = CaiZhiSupportLinkLines_ByBasePoint1__OffsetLine
    GuaZiGongInLineWLingGong1_Face = UniqueRectangleFrom3Pts7__Face
    GuaZiGongInLineWLingGong1_AB = UniqueRectangleFrom3Pts7__AB

    # ---- Step11：LingGongInLineWXiaoGongTou1（令栱與小栱頭相列一）----
    LingGongInLineWXiaoGongTou1_3Pts = CaiZhiThreePointsBuilder8__PointList
    LingGongInLineWXiaoGongTou1_OffsetPts = CaiZhiSupportLinkLines_ByBasePoint2__OffsetPts
    LingGongInLineWXiaoGongTou1_LinkLines = CaiZhiSupportLinkLines_ByBasePoint2__LinkLines
    LingGongInLineWXiaoGongTou1_OffsetLine = CaiZhiSupportLinkLines_ByBasePoint2__OffsetLine
    LingGongInLineWXiaoGongTou1_Face = UniqueRectangleFrom3Pts8__Face
    LingGongInLineWXiaoGongTou1_AB = UniqueRectangleFrom3Pts8__AB

    # ---- Step12：LingGongInLineWXiaoGongTou2（令栱與小栱頭相列二）----
    LingGongInLineWXiaoGongTou2_3Pts = CaiZhiThreePointsBuilder9__PointList
    LingGongInLineWXiaoGongTou2_OffsetPts = CaiZhiSupportLinkLines_ByBasePoint3__OffsetPts
    LingGongInLineWXiaoGongTou2_LinkLines = CaiZhiSupportLinkLines_ByBasePoint3__LinkLines
    LingGongInLineWXiaoGongTou2_OffsetLine = CaiZhiSupportLinkLines_ByBasePoint3__OffsetLine
    LingGongInLineWXiaoGongTou2_Face = UniqueRectangleFrom3Pts9__Face
    LingGongInLineWXiaoGongTou2_AB = UniqueRectangleFrom3Pts9__AB



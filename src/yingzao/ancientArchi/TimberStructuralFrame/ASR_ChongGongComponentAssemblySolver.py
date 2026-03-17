# -*- coding: utf-8 -*-
"""
ASR_ChongGongComponentAssemblySolver_step1_4.py

将用于构建 抽象结构_重栱（ASR_ChongGong） 的一组程序组件（包含多个 ghpy 自定义组件 / GH 组件）
逐步转换为一个单独 GhPython 组件。

------------------------------------------------------------
本文件当前实现：
    - Step 1：读取数据库（DBJsonReader）
    - Step 2：材栔模式（PointsOnLineByCumsum）
    - Step 3：瓜子栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts + CaiZhiSupportLinkLines_ByBasePoint + 连接线）
    - Step 4：慢栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts + CaiZhiSupportLinkLines_ByBasePoint + 连接线）（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts + CaiZhiSupportLinkLines_ByBasePoint + 连接线）

后续步骤会在此 Solver 主类中继续累加实现。

------------------------------------------------------------
输入（GhPython 建议设置）:
    DBPath : str (Item)
        SQLite 数据库路径
        Access: Item
        TypeHints: str

    PlacePlane : rg.Plane (Item)
        放置参考平面（默认为 GH WorldXY，且 Origin=(100,100,0)）
        Access: Item
        TypeHints: Plane

    Refresh : bool (Item)
        True 时强制重读数据库、重算
        Access: Item
        TypeHints: bool


    ScaleFactor : float (Item)
        比例缩放因子（默认 1.0）。
        按比例缩放“尺寸参数值”（在生成几何之前缩放），从而所有几何与输出同步缩放。
        Access: Item
        TypeHints: float

输出（当前阶段仅暴露 2 个）:
    AbsStructRep : object
        当前已完成步骤的组合体（本步为：线段 + 点列；后续会替换/扩充为最终构件组合体）

    Log : str
        日志信息

------------------------------------------------------------
命名规则说明：
    数据库 params_json 以 ExportAll=True 读取为 All（list of (key,value)），并转为 AllDict。
    key 的命名规则遵循：
        <ComponentName>__<InputName>
    例如：
        ('FT_AlignToolToTimber_1__BlockRotDeg', 90)
        ('FT_AlignToolToTimber_1__FlipY', [1, 0, 0, 1])
    本 Solver 后续所有参数均优先从组件输入端取，其次 AllDict，最后默认值。

------------------------------------------------------------
注意：
    - 本文件直接调用 yingzao.ancientArchi 中的工具/类，不在此重复定义。
    - 移除 sticky 依赖（本文件不做 sticky 兼容）。
    - 输出端如出现 System.Collections.Generic.List`1[System.Object] 的嵌套表现，
      需要递归拍平；已提供通用 _flatten_items。
"""

from __future__ import print_function, division

import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    DBJsonReader,
    PointsOnLineByCumsum,
    CaiZhiThreePointsBuilder,
    UniqueRectangleFrom3Pts,
    CaiZhiSupportLinkLines_ByBasePoint,
)


# =========================================================
# 通用工具函数（参考 ChongGongComponentAssemblySolver.py 的通用部分）
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


def _as_float_list(values, default=0.0):
    """把 Values 输入（可能为 list/tuple/单值/混入 str）尽量转为 list[float]。"""
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        out = []
        for v in values:
            try:
                out.append(float(v))
            except:
                out.append(float(default))
        return out
    try:
        return [float(values)]
    except:
        return [float(default)]


def _scale_numeric_like(x, scale_factor):
    """将数值/字符串数值/嵌套 list/tuple 中的数值整体乘以 scale_factor。
    用于在构建几何之前缩放“尺寸参数”（参考 ASR_DanGongComponentAssemblySolver 的策略）：
    - 不在最后对几何做 Transform.Scale
    - 而是在“读取到的尺寸参数”层面先缩放，再生成几何
    """
    if x is None:
        return None
    try:
        sf = float(scale_factor) if scale_factor is not None else 1.0
    except:
        sf = 1.0
    if abs(sf - 1.0) < 1e-12:
        return x

    if isinstance(x, (list, tuple)):
        t = [_scale_numeric_like(it, sf) for it in x]
        return t if isinstance(x, list) else tuple(t)

    try:
        v = float(x)
        return v * sf
    except:
        return x



def _safe_plane(plane):
    """确保 PlacePlane 为 rg.Plane；None 则返回默认平面。"""
    if plane is None:
        return _default_place_plane()
    try:
        return rg.Plane(plane)
    except:
        return _default_place_plane()


# =========================================================
# Solver 主类
# =========================================================

class ASR_ChongGongComponentAssemblySolver(object):
    """ASR_ChongGong 单组件装配 Solver（当前仅实现 Step1-2）。"""

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, ScaleFactor=1.0, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = _safe_plane(PlacePlane)
        self.Refresh = _as_bool(Refresh, False)

        # ScaleFactor（缩放“尺寸参数值”，在生成几何之前缩放）
        try:
            self.ScaleFactor = float(ScaleFactor) if ScaleFactor is not None else 1.0
        except:
            self.ScaleFactor = 1.0
        self.ghenv = ghenv

        # 统一日志
        self.LogLines = []
        self.Log = ""

        # 最终（阶段性）组合体
        self.ComponentAssembly = []
        self.AbsStructRep = None

        # Step 1 输出（必须保留：Value/All/AllDict/DBLog）
        self.S1_Value = None
        self.S1_All = None
        self.S1_AllDict = {}
        self.S1_DBLog = None

        # Step 2 输出（以组件名为前缀避免重名）
        self.S2_POC_BaseLine = None
        self.S2_POC_SumValue = None
        self.S2_POC_ReversedList = None
        self.S2_POC_CumList = None
        self.S2_POC_PointList = None

        # Step 3：瓜子栱支撑点（以构件名/组件名为前缀避免重名）
        # --- CaiZhiThreePointsBuilder::0 ---
        self.S3_GuaZiGong_CaiZhi3Pts_PointList = None
        self.S3_GuaZiGong_CaiZhi3Pts_BasePoint = None
        self.S3_GuaZiGong_CaiZhi3Pts_OffsetPts = None
        self.S3_GuaZiGong_CaiZhi3Pts_ExtraPoint = None
        self.S3_GuaZiGong_CaiZhi3Pts_DirUnit = None
        self.S3_GuaZiGong_CaiZhi3Pts_SpanVectors = None

        # --- UniqueRectangleFrom3Pts::0 ---
        self.S3_GuaZiGong_RectFace = None
        self.S3_GuaZiGong_RectAB = None

        # --- CaiZhiSupportLinkLines_ByBasePoint::0 ---
        self.S3_GuaZiGong_SupportLink_OffsetPts = None
        self.S3_GuaZiGong_SupportLink_Lines = None
        # Step 3（本步内完成）：连位直线段（由 SupportLink OffsetPts 拍平后生成）
        self.S3_GuaZiGong_OffsetPts_LinkLine = None

        # Step 4：慢栱支撑点（以构件名/组件名为前缀避免重名）
        # --- CaiZhiThreePointsBuilder::1 ---
        self.S4_ManGong_CaiZhi3Pts_PointList = None
        self.S4_ManGong_CaiZhi3Pts_BasePoint = None
        self.S4_ManGong_CaiZhi3Pts_OffsetPts = None
        self.S4_ManGong_CaiZhi3Pts_ExtraPoint = None
        self.S4_ManGong_CaiZhi3Pts_DirUnit = None
        self.S4_ManGong_CaiZhi3Pts_SpanVectors = None

        # --- UniqueRectangleFrom3Pts::1 ---
        self.S4_ManGong_RectFace = None
        self.S4_ManGong_RectAB = None

        # --- CaiZhiSupportLinkLines_ByBasePoint::1 ---
        self.S4_ManGong_SupportLink_OffsetPts = None
        self.S4_ManGong_SupportLink_Lines = None

        # Step 4：连位直线段（由 SupportLink OffsetPts 拍平后生成）
        self.S4_ManGong_OffsetPts_LinkLine = None


    # -------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 params_json -> All / AllDict …")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="AbsStructRep",
            key_field="type_code",
            key_value="ASR_ChongGong",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.S1_Value, self.S1_All, self.S1_DBLog = reader.run()

        d = {}
        try:
            for k, v in _ensure_list(self.S1_All):
                d[str(k)] = v
        except:
            pass
        self.S1_AllDict = d

        self.LogLines.append(
            "Step 1 完成：All items={} | AllDict keys={}".format(
                len(_ensure_list(self.S1_All)),
                len(self.S1_AllDict.keys())
            )
        )

    # -------------------------------
    # Step 2：材栔模式（PointsOnLineByCumsum）
    # -------------------------------
    def step2_points_on_line_by_cumsum(self):
        self.LogLines.append("Step 2：材栔模式 PointsOnLineByCumsum …")

        # Values：来自数据库 AllDict（puZuoVerticalCaiZhiPattern）
        vals_raw = self.S1_AllDict.get("puZuoVerticalCaiZhiPattern", None)
        vals_raw = _scale_numeric_like(vals_raw, getattr(self, 'ScaleFactor', 1.0))
        vals = _as_float_list(vals_raw, default=0.0)

        base_pt = self.PlacePlane.Origin
        direction = self.PlacePlane.ZAxis

        builder = PointsOnLineByCumsum(vals, base_pt, direction, clamp=True)
        bl, sv, rlist, clist, pts = builder.build()

        self.S2_POC_BaseLine = bl
        self.S2_POC_SumValue = sv
        self.S2_POC_ReversedList = rlist
        self.S2_POC_CumList = clist
        self.S2_POC_PointList = pts

        # 当前阶段组合体：先把线与点放入 ComponentAssembly
        self.ComponentAssembly = []
        self.ComponentAssembly.append(self.S2_POC_BaseLine)
        self.ComponentAssembly.append(self.S2_POC_PointList)

        self.LogLines.append(
            "Step 2 完成：Values={} SumValue={} Points={}".format(
                len(vals),
                self.S2_POC_SumValue,
                len(_ensure_list(self.S2_POC_PointList))
            )
        )


    # -------------------------------
    # Step 3：瓜子栱 支撑点（CaiZhiThreePointsBuilder::0 + UniqueRectangleFrom3Pts::0 + CaiZhiSupportLinkLines_ByBasePoint::0）
    # -------------------------------
    def step3_guazigong_support_points(self):
        self.LogLines.append("Step 3：瓜子栱支撑点（3点矩形 + 支撑连线）…")

        # --- 1) CaiZhiThreePointsBuilder::0 ---
        # Direction = 输入参考平面 X 轴
        s3_cz3_direction = self.PlacePlane.XAxis

        # CaiZhiPts = Step2 的 PointList
        s3_cz3_pts = _ensure_list(self.S2_POC_PointList)

        # IndexA=2, IndexB=1
        s3_cz3_index_a = 2
        s3_cz3_index_b = 1

        # Span = DB 参数：GuaZiGong__axis2support
        s3_cz3_span = self.S1_AllDict.get("GuaZiGong__axis2support", None)
        try:
            s3_cz3_span = float(s3_cz3_span)
        except:
            s3_cz3_span = 0.0

        # ScaleFactor：缩放该距离参数
        try:
            s3_cz3_span = float(s3_cz3_span) * float(getattr(self, 'ScaleFactor', 1.0))
        except:
            pass

        cz3_builder = CaiZhiThreePointsBuilder(
            caizhi_pts=s3_cz3_pts,
            index_a=s3_cz3_index_a,
            index_b=s3_cz3_index_b,
            direction=s3_cz3_direction,
            span=s3_cz3_span
        )
        (
            self.S3_GuaZiGong_CaiZhi3Pts_PointList,
            self.S3_GuaZiGong_CaiZhi3Pts_BasePoint,
            self.S3_GuaZiGong_CaiZhi3Pts_OffsetPts,
            self.S3_GuaZiGong_CaiZhi3Pts_ExtraPoint,
            self.S3_GuaZiGong_CaiZhi3Pts_DirUnit,
            self.S3_GuaZiGong_CaiZhi3Pts_SpanVectors
        ) = cz3_builder.build()

        # --- 2) UniqueRectangleFrom3Pts::0 ---
        self.S3_GuaZiGong_RectFace = None
        self.S3_GuaZiGong_RectAB = None
        if self.S3_GuaZiGong_CaiZhi3Pts_PointList:
            try:
                rect_builder = UniqueRectangleFrom3Pts(self.S3_GuaZiGong_CaiZhi3Pts_PointList)
                self.S3_GuaZiGong_RectFace, self.S3_GuaZiGong_RectAB = rect_builder.build()
            except:
                self.S3_GuaZiGong_RectFace = None
                self.S3_GuaZiGong_RectAB = None

        # --- 3) CaiZhiSupportLinkLines_ByBasePoint::0 ---
        # Direction = SpanVectors（与 OffsetPts 同序，长度通常=2）
        s3_link_direction = _ensure_list(self.S3_GuaZiGong_CaiZhi3Pts_SpanVectors)

        # BasePt = PointsOnLineByCumsum PointList[3]
        base_candidates = _ensure_list(self.S2_POC_PointList)
        if len(base_candidates) == 0:
            s3_link_basept = None
        else:
            idx = 3
            if idx < 0:
                idx = 0
            if idx >= len(base_candidates):
                idx = len(base_candidates) - 1
            s3_link_basept = base_candidates[idx]

        # SupportPts = CaiZhiThreePointsBuilder OffsetPts（[P_minus, P_plus]）
        s3_link_supportpts = _ensure_list(self.S3_GuaZiGong_CaiZhi3Pts_OffsetPts)

        if s3_link_basept is not None and len(s3_link_direction) > 0 and len(s3_link_supportpts) > 0:
            try:
                link_solver = CaiZhiSupportLinkLines_ByBasePoint(
                    s3_link_direction,
                    s3_link_basept,
                    s3_link_supportpts
                )
                self.S3_GuaZiGong_SupportLink_OffsetPts, self.S3_GuaZiGong_SupportLink_Lines = link_solver.solve()
            except:
                self.S3_GuaZiGong_SupportLink_OffsetPts = None
                self.S3_GuaZiGong_SupportLink_Lines = None
        else:
            self.S3_GuaZiGong_SupportLink_OffsetPts = None
            self.S3_GuaZiGong_SupportLink_Lines = None

        # --- 4) 将 CaiZhiSupportLinkLines_ByBasePoint::0 的 OffsetPts（拍平）连为直线段 ---
        flat_pts = []
        _flatten_items(self.S3_GuaZiGong_SupportLink_OffsetPts, flat_pts)

        self.S3_GuaZiGong_OffsetPts_LinkLine = []
        if len(flat_pts) >= 2:
            for i in range(len(flat_pts) - 1):
                try:
                    self.S3_GuaZiGong_OffsetPts_LinkLine.append(rg.Line(flat_pts[i], flat_pts[i + 1]))
                except:
                    pass
        elif len(flat_pts) == 1:
            self.S3_GuaZiGong_OffsetPts_LinkLine = []

        # 把本步新增几何加入组合体（保持先前结果不丢失）
        if self.S3_GuaZiGong_RectFace is not None:
            self.ComponentAssembly.append(self.S3_GuaZiGong_RectFace)
        if self.S3_GuaZiGong_SupportLink_Lines is not None:
            self.ComponentAssembly.append(self.S3_GuaZiGong_SupportLink_Lines)
        if self.S3_GuaZiGong_OffsetPts_LinkLine:
            self.ComponentAssembly.append(self.S3_GuaZiGong_OffsetPts_LinkLine)

        self.LogLines.append(
            "Step 3 完成：Span={} | CZ3Pts={} | RectFace={} | SupportLinkPts={} | SupportLinkLines={} | LinkLine={}".format(
                s3_cz3_span,
                len(_ensure_list(self.S3_GuaZiGong_CaiZhi3Pts_PointList)),
                "OK" if self.S3_GuaZiGong_RectFace else "None",
                len(_ensure_list(flat_pts)),
                len(_ensure_list(self.S3_GuaZiGong_SupportLink_Lines)),
                len(_ensure_list(self.S3_GuaZiGong_OffsetPts_LinkLine))
            )
        )

    # -------------------------------
    # Step 4：慢栱 支撑点（CaiZhiThreePointsBuilder::1 + UniqueRectangleFrom3Pts::1 + CaiZhiSupportLinkLines_ByBasePoint::1）
    # -------------------------------
    def step4_mangong_support_points(self):
        self.LogLines.append("Step 4：慢栱支撑点（3点矩形 + 支撑连线）…")

        # --- 1) CaiZhiThreePointsBuilder::1 ---
        # Direction = 输入参考平面 X 轴
        s4_cz3_direction = self.PlacePlane.XAxis

        # CaiZhiPts = Step2 的 PointList
        s4_cz3_pts = _ensure_list(self.S2_POC_PointList)

        # IndexA=4, IndexB=3
        s4_cz3_index_a = 4
        s4_cz3_index_b = 3

        # Span = DB 参数：ManGong__axis2support
        s4_cz3_span = self.S1_AllDict.get("ManGong__axis2support", None)
        try:
            s4_cz3_span = float(s4_cz3_span)
        except:
            s4_cz3_span = 0.0

        # ScaleFactor：缩放该距离参数
        try:
            s4_cz3_span = float(s4_cz3_span) * float(getattr(self, 'ScaleFactor', 1.0))
        except:
            pass

        cz3_builder = CaiZhiThreePointsBuilder(
            caizhi_pts=s4_cz3_pts,
            index_a=s4_cz3_index_a,
            index_b=s4_cz3_index_b,
            direction=s4_cz3_direction,
            span=s4_cz3_span
        )
        (
            self.S4_ManGong_CaiZhi3Pts_PointList,
            self.S4_ManGong_CaiZhi3Pts_BasePoint,
            self.S4_ManGong_CaiZhi3Pts_OffsetPts,
            self.S4_ManGong_CaiZhi3Pts_ExtraPoint,
            self.S4_ManGong_CaiZhi3Pts_DirUnit,
            self.S4_ManGong_CaiZhi3Pts_SpanVectors
        ) = cz3_builder.build()

        # --- 2) UniqueRectangleFrom3Pts::1 ---
        self.S4_ManGong_RectFace = None
        self.S4_ManGong_RectAB = None
        if self.S4_ManGong_CaiZhi3Pts_PointList:
            try:
                rect_builder = UniqueRectangleFrom3Pts(self.S4_ManGong_CaiZhi3Pts_PointList)
                self.S4_ManGong_RectFace, self.S4_ManGong_RectAB = rect_builder.build()
            except:
                self.S4_ManGong_RectFace = None
                self.S4_ManGong_RectAB = None

        # --- 3) CaiZhiSupportLinkLines_ByBasePoint::1 ---
        # Direction = SpanVectors（与 OffsetPts 同序，长度通常=2）
        s4_link_direction = _ensure_list(self.S4_ManGong_CaiZhi3Pts_SpanVectors)

        # BasePt = PointsOnLineByCumsum PointList[5]
        base_candidates = _ensure_list(self.S2_POC_PointList)
        if len(base_candidates) == 0:
            s4_link_basept = None
        else:
            idx = 5
            if idx < 0:
                idx = 0
            if idx >= len(base_candidates):
                idx = len(base_candidates) - 1
            s4_link_basept = base_candidates[idx]

        # SupportPts = CaiZhiThreePointsBuilder OffsetPts（[P_minus, P_plus]）
        s4_link_supportpts = _ensure_list(self.S4_ManGong_CaiZhi3Pts_OffsetPts)

        if s4_link_basept is not None and len(s4_link_direction) > 0 and len(s4_link_supportpts) > 0:
            try:
                link_solver = CaiZhiSupportLinkLines_ByBasePoint(
                    s4_link_direction,
                    s4_link_basept,
                    s4_link_supportpts
                )
                self.S4_ManGong_SupportLink_OffsetPts, self.S4_ManGong_SupportLink_Lines = link_solver.solve()
            except:
                self.S4_ManGong_SupportLink_OffsetPts = None
                self.S4_ManGong_SupportLink_Lines = None
        else:
            self.S4_ManGong_SupportLink_OffsetPts = None
            self.S4_ManGong_SupportLink_Lines = None

        # --- 4) 将 CaiZhiSupportLinkLines_ByBasePoint::1 的 OffsetPts（拍平）连为直线段 ---
        flat_pts = []
        _flatten_items(self.S4_ManGong_SupportLink_OffsetPts, flat_pts)

        self.S4_ManGong_OffsetPts_LinkLine = []
        if len(flat_pts) >= 2:
            for i in range(len(flat_pts) - 1):
                try:
                    self.S4_ManGong_OffsetPts_LinkLine.append(rg.Line(flat_pts[i], flat_pts[i + 1]))
                except:
                    pass
        elif len(flat_pts) == 1:
            self.S4_ManGong_OffsetPts_LinkLine = []

        # 把本步新增几何加入组合体（保持先前结果不丢失）
        if self.S4_ManGong_RectFace is not None:
            self.ComponentAssembly.append(self.S4_ManGong_RectFace)
        if self.S4_ManGong_SupportLink_Lines is not None:
            self.ComponentAssembly.append(self.S4_ManGong_SupportLink_Lines)
        if self.S4_ManGong_OffsetPts_LinkLine:
            self.ComponentAssembly.append(self.S4_ManGong_OffsetPts_LinkLine)

        self.LogLines.append(
            "Step 4 完成：Span={} | CZ3Pts={} | RectFace={} | SupportLinkPts={} | SupportLinkLines={} | LinkLine={}".format(
                s4_cz3_span,
                len(_ensure_list(self.S4_ManGong_CaiZhi3Pts_PointList)),
                "OK" if self.S4_ManGong_RectFace else "None",
                len(_ensure_list(flat_pts)),
                len(_ensure_list(self.S4_ManGong_SupportLink_Lines)),
                len(_ensure_list(self.S4_ManGong_OffsetPts_LinkLine))
            )
        )


    # -------------------------------
    # Run
    # -------------------------------
    def run(self):
        # 1) PlacePlane 兜底
        self.PlacePlane = _safe_plane(self.PlacePlane)

        # 2) Step 1
        self.step1_read_db()

        # 3) Step 2
        self.step2_points_on_line_by_cumsum()

        # 4) Step 3
        self.step3_guazigong_support_points()

        # 5) Step 4
        self.step4_mangong_support_points()

        # 6) AbsStructRep 输出（递归拍平，避免 List`1[Object]）
        flat = []
        _flatten_items(self.ComponentAssembly, flat)
        self.AbsStructRep = flat

        # 5) Log
        try:
            if self.S1_DBLog:
                self.LogLines.append("DBLog: {}".format(self.S1_DBLog))
        except:
            pass
        self.Log = "\n".join([str(x) for x in _ensure_list(self.LogLines)])

        return self


# =========================================================
# GH Python 组件 · 输出绑定区
#   约定：输出端口名称与 Solver 成员变量同名时，自动绑定。
#   当前阶段：只需要 AbsStructRep, Log
#   但若你在 GH 输出端增加端口（例如 S1_All、S2_POC_PointList 等），也会自动填充。
# =========================================================

def _bind_outputs(ghenv, solver):
    """按 GH 输出端口名称，自动把 solver 同名成员变量赋给输出变量。"""
    try:
        out_params = list(ghenv.Component.Params.Output)
    except:
        out_params = []

    for p in out_params:
        try:
            name = p.Name
            if hasattr(solver, name):
                globals()[name] = getattr(solver, name)
        except:
            pass


# -------------------------
# 输入端兜底：ScaleFactor
# -------------------------
try:
    ScaleFactor
except NameError:
    ScaleFactor = 1.0

if __name__ == "__main__":
    Solver = ASR_ChongGongComponentAssemblySolver(
        DBPath=DBPath,
        PlacePlane=PlacePlane,
        Refresh=Refresh,
        ScaleFactor=ScaleFactor,
        ghenv=ghenv
    ).run()

    # =====================================================
    # GH Python 组件 · 输出绑定区
    # 说明：
    # - 当前只暴露 AbsStructRep / Log 两个输出端（按你的阶段要求）
    # - 其它内部变量全部已保存在 Solver 成员中，后续需要时在这里逐一绑定同名输出端
    #   或者：直接在 GH 输出端新增同名端口，保持下方“自动绑定”即可。
    # =====================================================

    # ---- 当前阶段（必须）----
    AbsStructRep = Solver.AbsStructRep
    Log = Solver.Log

    # ---- step 1 outputs (optional expose) ----
    # 说明：以下变量只有在 GH 组件里新增同名输出端时才会真正显示。
    DB_Value = Solver.S1_Value
    DB_All = Solver.S1_All
    DB_AllDict = Solver.S1_AllDict
    DB_Log = Solver.S1_DBLog

    # ---- step 2 outputs (PointsOnLineByCumsum_1) ----
    # 为后续保持命名规则一致，这里用 “PointsOnLineByCumsum__<PortName>” 的形式导出。
    PointsOnLineByCumsum__Values = Solver.S1_AllDict.get("puZuoVerticalCaiZhiPattern", None)
    PointsOnLineByCumsum__BasePoint = Solver.PlacePlane.Origin
    PointsOnLineByCumsum__Direction = Solver.PlacePlane.ZAxis
    PointsOnLineByCumsum__BaseLine = Solver.S2_POC_BaseLine
    PointsOnLineByCumsum__SumValue = Solver.S2_POC_SumValue
    PointsOnLineByCumsum__ReversedList = Solver.S2_POC_ReversedList
    PointsOnLineByCumsum__CumList = Solver.S2_POC_CumList

    # ---- step 3 outputs (GuaZiGong Support) ----
    # CaiZhiThreePointsBuilder::0
    GuaZiGong_CaiZhiThreePointsBuilder__Direction = Solver.PlacePlane.XAxis
    GuaZiGong_CaiZhiThreePointsBuilder__CaiZhiPts = Solver.S2_POC_PointList
    GuaZiGong_CaiZhiThreePointsBuilder__IndexA = 2
    GuaZiGong_CaiZhiThreePointsBuilder__Span = Solver.S1_AllDict.get("GuaZiGong__axis2support", None)
    GuaZiGong_CaiZhiThreePointsBuilder__IndexB = 1
    GuaZiGong_CaiZhiThreePointsBuilder__PointList = Solver.S3_GuaZiGong_CaiZhi3Pts_PointList
    GuaZiGong_CaiZhiThreePointsBuilder__BasePoint = Solver.S3_GuaZiGong_CaiZhi3Pts_BasePoint
    GuaZiGong_CaiZhiThreePointsBuilder__OffsetPts = Solver.S3_GuaZiGong_CaiZhi3Pts_OffsetPts
    GuaZiGong_CaiZhiThreePointsBuilder__ExtraPoint = Solver.S3_GuaZiGong_CaiZhi3Pts_ExtraPoint
    GuaZiGong_CaiZhiThreePointsBuilder__DirUnit = Solver.S3_GuaZiGong_CaiZhi3Pts_DirUnit
    GuaZiGong_CaiZhiThreePointsBuilder__SpanVectors = Solver.S3_GuaZiGong_CaiZhi3Pts_SpanVectors

    # UniqueRectangleFrom3Pts::0
    GuaZiGong_UniqueRectangleFrom3Pts__Pts = Solver.S3_GuaZiGong_CaiZhi3Pts_PointList
    GuaZiGong_UniqueRectangleFrom3Pts__Face = Solver.S3_GuaZiGong_RectFace
    GuaZiGong_UniqueRectangleFrom3Pts__AB = Solver.S3_GuaZiGong_RectAB

    # CaiZhiSupportLinkLines_ByBasePoint::0
    GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__Direction = Solver.S3_GuaZiGong_CaiZhi3Pts_SpanVectors
    # BasePt = PointsOnLineByCumsum PointList[3]
    _tmp_poc_pts = _ensure_list(Solver.S2_POC_PointList)
    if _tmp_poc_pts:
        _idx = 3
        if _idx >= len(_tmp_poc_pts):
            _idx = len(_tmp_poc_pts) - 1
        GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__BasePt = _tmp_poc_pts[_idx]
    else:
        GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__BasePt = None
    GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__SupportPts = Solver.S3_GuaZiGong_CaiZhi3Pts_OffsetPts
    GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = Solver.S3_GuaZiGong_SupportLink_OffsetPts
    GuaZiGong_CaiZhiSupportLinkLines_ByBasePoint__LinkLines = Solver.S3_GuaZiGong_SupportLink_Lines

    # Step4: Flatten OffsetPts -> connect
    GuaZiGong_SupportOffsetPts_LinkLine = Solver.S3_GuaZiGong_OffsetPts_LinkLine

    PointsOnLineByCumsum__PointList = Solver.S2_POC_PointList



    # ---- step 4 outputs (ManGong Support) ----
    # CaiZhiThreePointsBuilder::1
    ManGong_CaiZhiThreePointsBuilder__Direction = Solver.PlacePlane.XAxis
    ManGong_CaiZhiThreePointsBuilder__CaiZhiPts = Solver.S2_POC_PointList
    ManGong_CaiZhiThreePointsBuilder__IndexA = 4
    ManGong_CaiZhiThreePointsBuilder__Span = Solver.S1_AllDict.get("ManGong__axis2support", None)
    ManGong_CaiZhiThreePointsBuilder__IndexB = 3
    ManGong_CaiZhiThreePointsBuilder__PointList = Solver.S4_ManGong_CaiZhi3Pts_PointList
    ManGong_CaiZhiThreePointsBuilder__BasePoint = Solver.S4_ManGong_CaiZhi3Pts_BasePoint
    ManGong_CaiZhiThreePointsBuilder__OffsetPts = Solver.S4_ManGong_CaiZhi3Pts_OffsetPts
    ManGong_CaiZhiThreePointsBuilder__ExtraPoint = Solver.S4_ManGong_CaiZhi3Pts_ExtraPoint
    ManGong_CaiZhiThreePointsBuilder__DirUnit = Solver.S4_ManGong_CaiZhi3Pts_DirUnit
    ManGong_CaiZhiThreePointsBuilder__SpanVectors = Solver.S4_ManGong_CaiZhi3Pts_SpanVectors

    # UniqueRectangleFrom3Pts::1
    ManGong_UniqueRectangleFrom3Pts__Pts = Solver.S4_ManGong_CaiZhi3Pts_PointList
    ManGong_UniqueRectangleFrom3Pts__Face = Solver.S4_ManGong_RectFace
    ManGong_UniqueRectangleFrom3Pts__AB = Solver.S4_ManGong_RectAB

    # CaiZhiSupportLinkLines_ByBasePoint::1
    ManGong_CaiZhiSupportLinkLines_ByBasePoint__Direction = Solver.S4_ManGong_CaiZhi3Pts_SpanVectors
    # BasePt = PointsOnLineByCumsum PointList[5]
    _tmp_poc_pts2 = _ensure_list(Solver.S2_POC_PointList)
    if _tmp_poc_pts2:
        _idx2 = 5
        if _idx2 >= len(_tmp_poc_pts2):
            _idx2 = len(_tmp_poc_pts2) - 1
        ManGong_CaiZhiSupportLinkLines_ByBasePoint__BasePt = _tmp_poc_pts2[_idx2]
    else:
        ManGong_CaiZhiSupportLinkLines_ByBasePoint__BasePt = None
    ManGong_CaiZhiSupportLinkLines_ByBasePoint__SupportPts = Solver.S4_ManGong_CaiZhi3Pts_OffsetPts
    ManGong_CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = Solver.S4_ManGong_SupportLink_OffsetPts
    ManGong_CaiZhiSupportLinkLines_ByBasePoint__LinkLines = Solver.S4_ManGong_SupportLink_Lines

    # Step4: Flatten OffsetPts -> connect
    ManGong_SupportOffsetPts_LinkLine = Solver.S4_ManGong_OffsetPts_LinkLine

    # ---- 自动绑定（推荐保留）：若 GH 输出端新增端口名=Solver 成员名，会自动赋值 ----
    _bind_outputs(ghenv, Solver)

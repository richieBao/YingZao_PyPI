# -*- coding: utf-8 -*-
"""
ASR_BaTouJiaoXiangZaoComponentAssemblySolver.py

将用于构建 抽象结构_把頭絞項造（ASR_BaTouJiaoXiangZao） 的多个 GH/GhPython 组件
逐步“串联”为单一 GhPython 组件脚本（数据库驱动）。

当前进度（已完成）：
- Step 1：读取数据库（DBJsonReader）
- Step 2：材栔模式点列（PointsOnLineByCumsum）
- Step 3：泥道栱 支撑点（CaiZhiThreePointsBuilder::0 / UniqueRectangleFrom3Pts::0 / CaiZhiSupportLinkLines_ByBasePoint::0）
- Step 4：乳栿参考（CaiZhiThreePointsBuilder::1 / UniqueRectangleFrom3Pts::1）

输入（GhPython 建议设置）:
    DBPath : str (Item)
        SQLite 数据库文件路径
        Access: Item
        TypeHint: str

    PlacePlane : rg.Plane (Item)
        放置参考平面
        Access: Item
        TypeHint: Plane
        Default: WorldXY with Origin=(100,100,0)

    Refresh : bool (Item)
        刷新开关：True 时强制重读数据库并重算（便于调试）
        Access: Item
        TypeHint: bool
        Default: False

    ScaleFactor : float (Item)
        比例缩放因子（默认 1.0）。
        按比例缩放“尺寸参数值”（在生成几何之前缩放），从而所有几何与输出同步缩放。
        Access: Item
        TypeHint: float
        Default: 1.0

输出（GhPython 建议设置）:
    AbsStructRep : object
        最终组合体（后续逐步接入；当前阶段为空/占位）
    Log : str
        日志信息（多行文本）

注意：
- 各步骤内部变量均保留为 Solver 成员，便于后续逐步暴露输出端。
- 数据库读取采用 “All” 列表（(key,value)）并转为字典 AllDict，后续只从 All/AllDict 提取，不再重复读库。
- 如输出端出现多层嵌套列表导致 GH 显示为 System.Collections.Generic.List`1[System.Object]，
  请在输出绑定区使用 _flatten_items 递归拍平后再输出（本文件已提供工具函数，后续步骤按需使用）。
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
# 通用工具函数（参考 ChongGongComponentAssemblySolver.py）
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


def _safe_bool(x, default=False):
    try:
        if x is None:
            return bool(default)
        return bool(x)
    except:
        return bool(default)


def _safe_str(x, default=None):
    try:
        if x is None:
            return default
        return str(x)
    except:
        return default


def _safe_float(x, default=0.0):
    try:
        if x is None:
            return float(default)
        if isinstance(x, (list, tuple)) and len(x) > 0:
            return float(x[0])
        return float(x)
    except:
        return float(default)



def _scale_numeric_like(x, scale_factor):
    """
    将数值/字符串数值/嵌套 list/tuple 中的数值整体乘以 scale_factor。
    用于在构建几何之前缩放“尺寸参数”。

    说明：该策略参考 ASR_DanGongComponentAssemblySolver：
    - 不在最后对几何做 Transform.Scale
    - 而是在“读取到的尺寸参数”层面先缩放，再生成几何
    """
    if x is None:
        return None
    if scale_factor is None:
        return x
    try:
        sf = float(scale_factor)
    except:
        return x
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

def _clamp_index(i, n):
    """clamp index into [0, n-1]; support negative index style."""
    try:
        if n <= 0:
            return 0
        ii = int(i)
        if ii < 0:
            ii = n + ii
        if ii < 0:
            return 0
        if ii > n - 1:
            return n - 1
        return ii
    except:
        return 0


def _get_point_at(pts, idx):
    """safe get point from list; idx will be clamped"""
    if not pts:
        return None
    ii = _clamp_index(idx, len(pts))
    try:
        p = pts[ii]
        # try convert GH_Point to Point3d if needed
        if hasattr(p, "Location"):
            return rg.Point3d(p.Location)
        if isinstance(p, rg.Point3d):
            return p
        # last resort
        return rg.Point3d(p)
    except:
        return None


def _build_polyline_curve(pts):
    """build PolylineCurve if possible"""
    if not pts or len(pts) < 2:
        return None
    try:
        pl = rg.Polyline(pts)
        if pl.IsValid and pl.Count >= 2:
            return rg.PolylineCurve(pl)
    except:
        return None
    return None


def _build_line_segments(pts):
    """build list[rg.Line] segments connecting consecutive points"""
    segs = []
    if not pts or len(pts) < 2:
        return segs
    for i in range(len(pts) - 1):
        try:
            segs.append(rg.Line(pts[i], pts[i + 1]))
        except:
            pass
    return segs


# =========================================================
# Solver 主类
# =========================================================

class ASR_BaTouJiaoXiangZaoComponentAssemblySolver(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, ScaleFactor=1.0, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = _safe_bool(Refresh, False)

        # ScaleFactor：缩放“尺寸参数值”（在生成几何之前缩放）
        try:
            self.ScaleFactor = float(ScaleFactor) if ScaleFactor is not None else 1.0
        except:
            self.ScaleFactor = 1.0
        self.ghenv = ghenv

        # ---------- Logging ----------
        self.LogLines = []
        self.Log = ""

        # ---------- Final result placeholders ----------
        self.AbsStructRep = None  # 最终组合体（后续步骤会逐步填充）
        self.ComponentAssembly = []  # 若你习惯用列表聚合各几何，可后续沿用

        # ---------- Step 1 outputs ----------
        self.Value = None
        self.All = None
        self.AllDict = None
        self.DBLog = None

        # ---------- Step 2 outputs ----------
        self.PointsOnLineByCumsum__Values = None
        self.PointsOnLineByCumsum__BasePoint = None
        self.PointsOnLineByCumsum__Direction = None
        self.PointsOnLineByCumsum__BaseLine = None
        self.PointsOnLineByCumsum__SumValue = None
        self.PointsOnLineByCumsum__ReversedList = None
        self.PointsOnLineByCumsum__CumList = None
        self.PointsOnLineByCumsum__PointList = None

        # ---------- Step 3 outputs (NiDaoGong Support) ----------
        # CaiZhiThreePointsBuilder::0
        self.NiDaoGong__CaiZhiThreePointsBuilder__Direction = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__CaiZhiPts = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__IndexA = 2
        self.NiDaoGong__CaiZhiThreePointsBuilder__Span = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__IndexB = 1
        self.NiDaoGong__CaiZhiThreePointsBuilder__PointList = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__BasePoint = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__OffsetPts = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__ExtraPoint = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__DirUnit = None
        self.NiDaoGong__CaiZhiThreePointsBuilder__SpanVectors = None

        # UniqueRectangleFrom3Pts::0
        self.NiDaoGong__UniqueRectangleFrom3Pts__Face = None
        self.NiDaoGong__UniqueRectangleFrom3Pts__AB = None

        # CaiZhiSupportLinkLines_ByBasePoint::0
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__Direction = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__BasePt = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None

        # Step 3 extra：将 OffsetPts（展平）连为直线段
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Flat = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Polyline = None
        self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_LineSegments = None

        # ---------- Step 4 outputs (RuFuRef) ----------
        # CaiZhiThreePointsBuilder::1
        self.RuFuRef__CaiZhiThreePointsBuilder__Direction = None
        self.RuFuRef__CaiZhiThreePointsBuilder__CaiZhiPts = None
        self.RuFuRef__CaiZhiThreePointsBuilder__IndexA = 2
        self.RuFuRef__CaiZhiThreePointsBuilder__Span = None
        self.RuFuRef__CaiZhiThreePointsBuilder__IndexB = 1
        self.RuFuRef__CaiZhiThreePointsBuilder__PointList = None
        self.RuFuRef__CaiZhiThreePointsBuilder__BasePoint = None
        self.RuFuRef__CaiZhiThreePointsBuilder__OffsetPts = None
        self.RuFuRef__CaiZhiThreePointsBuilder__ExtraPoint = None
        self.RuFuRef__CaiZhiThreePointsBuilder__DirUnit = None
        self.RuFuRef__CaiZhiThreePointsBuilder__SpanVectors = None

        # UniqueRectangleFrom3Pts::1
        self.RuFuRef__UniqueRectangleFrom3Pts__Face = None
        self.RuFuRef__UniqueRectangleFrom3Pts__AB = None

    # -----------------------------
    # logging helpers
    # -----------------------------
    def _log(self, msg):
        try:
            self.LogLines.append(str(msg))
        except:
            self.LogLines.append(repr(msg))

    def _finalize_log(self):
        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])

    # -----------------------------
    # main pipeline
    # -----------------------------
    def run(self):
        # PlacePlane default
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        # Step 1
        self._step_1_read_db()

        # Step 2
        self._step_2_points_on_line_by_cumsum()

        # Step 3
        self._step_3_nidaogong_support_pts()

        # Step 4
        self._step_4_rufu_ref()

        # Final (当前阶段占位)
        self.AbsStructRep = getattr(self, "ComponentAssembly", None)

        self._finalize_log()
        return self.AbsStructRep, self.Log

    # =====================================================
    # Step 1：读取数据库（DBJsonReader）
    # =====================================================
    def _step_1_read_db(self):
        """
        DBJsonReader 组件逻辑（保持原组件代码思路）：
            Table     = AbsStructRep
            KeyField  = type_code
            KeyValue  = ASR_BaTouJiaoXiangZao
            Field     = params_json
            ExportAll = True
        输出:
            Value, All, DBLog
            以及 AllDict（由 All 转换而来）
        """
        try:
            table = "AbsStructRep"
            key_field = "type_code"
            key_value = "ASR_BaTouJiaoXiangZao"
            field = "params_json"
            json_path = None
            export_all = True

            reader = DBJsonReader(
                db_path=self.DBPath,
                table=table,
                key_field=key_field,
                key_value=key_value,
                field=field,
                json_path=json_path,
                export_all=export_all,
                ghenv=self.ghenv
            )
            Value, All, Log = reader.run()

            self.Value = Value
            self.All = All
            self.DBLog = Log

            # All -> Dict（后续统一从 AllDict 取值）
            d = {}
            if All is not None:
                try:
                    for kv in All:
                        if not kv or len(kv) < 2:
                            continue
                        k = kv[0]
                        v = kv[1]
                        d[k] = v
                except Exception as e:
                    self._log("Step1: All->Dict failed: {}".format(e))
            self.AllDict = d

            self._log("Step1 OK: DBJsonReader -> All items = {}".format(len(d)))

        except Exception as e:
            self._log("Step1 ERROR: {}".format(e))
            self.Value = None
            self.All = None
            self.AllDict = {}
            self.DBLog = None

    # =====================================================
    # Step 2：材栔模式（PointsOnLineByCumsum）
    # =====================================================
    def _step_2_points_on_line_by_cumsum(self):
        """
        PointsOnLineByCumsum 组件逻辑（保持原组件代码思路）：
            Values    = AllDict['puZuoVerticalCaiZhiPattern']
            BasePoint = PlacePlane.Origin
            Direction = PlacePlane.ZAxis
        输出:
            BaseLine, SumValue, ReversedList, CumList, PointList
        """
        try:
            if self.AllDict is None:
                self.AllDict = {}

            values = self.AllDict.get("puZuoVerticalCaiZhiPattern", None)
            values = _scale_numeric_like(values, getattr(self, "ScaleFactor", 1.0))

            # 记录 step2 inputs
            self.PointsOnLineByCumsum__Values = values
            self.PointsOnLineByCumsum__BasePoint = self.PlacePlane.Origin
            self.PointsOnLineByCumsum__Direction = self.PlacePlane.ZAxis

            builder = PointsOnLineByCumsum(
                values,
                self.PlacePlane.Origin,
                self.PlacePlane.ZAxis,
                clamp=True
            )
            BaseLine, SumValue, ReversedList, CumList, PointList = builder.build()

            self.PointsOnLineByCumsum__BaseLine = BaseLine
            self.PointsOnLineByCumsum__SumValue = SumValue
            self.PointsOnLineByCumsum__ReversedList = ReversedList
            self.PointsOnLineByCumsum__CumList = CumList
            self.PointsOnLineByCumsum__PointList = PointList

            self._log("Step2 OK: PointsOnLineByCumsum -> PointList = {}".format(
                len(PointList) if PointList is not None else 0
            ))

        except Exception as e:
            self._log("Step2 ERROR: {}".format(e))
            self.PointsOnLineByCumsum__BaseLine = None
            self.PointsOnLineByCumsum__SumValue = None
            self.PointsOnLineByCumsum__ReversedList = None
            self.PointsOnLineByCumsum__CumList = None
            self.PointsOnLineByCumsum__PointList = None

    # =====================================================
    # Step 3：泥道栱 支撑点（按 GH 连线描述串联）
    # =====================================================
    def _step_3_nidaogong_support_pts(self):
        """
        包含的核心组件：
        1) CaiZhiThreePointsBuilder::0
            Direction = PlacePlane.XAxis
            CaiZhiPts  = PointsOnLineByCumsum__PointList
            IndexA     = 2
            Span       = AllDict['NiDaoGong__axis2support']
            IndexB     = 1

        2) UniqueRectangleFrom3Pts::0
            Pts = CaiZhiThreePointsBuilder::0.PointList

        3) CaiZhiSupportLinkLines_ByBasePoint::0
            Direction  = CaiZhiThreePointsBuilder::0.SpanVectors
            BasePt     = PointsOnLineByCumsum__PointList[3]
            SupportPts = CaiZhiThreePointsBuilder::0.OffsetPts

        4) 将 CaiZhiSupportLinkLines_ByBasePoint::0.OffsetPts（展平）连为直线段
        """
        try:
            if self.AllDict is None:
                self.AllDict = {}
            cai_zhi_pts = self.PointsOnLineByCumsum__PointList

            # ---------- CaiZhiThreePointsBuilder::0 ----------
            self.NiDaoGong__CaiZhiThreePointsBuilder__Direction = self.PlacePlane.XAxis
            self.NiDaoGong__CaiZhiThreePointsBuilder__CaiZhiPts = cai_zhi_pts
            self.NiDaoGong__CaiZhiThreePointsBuilder__IndexA = 2
            self.NiDaoGong__CaiZhiThreePointsBuilder__IndexB = 1

            span = self.AllDict.get("NiDaoGong__axis2support", None)
            span = _scale_numeric_like(span, getattr(self, "ScaleFactor", 1.0))
            self.NiDaoGong__CaiZhiThreePointsBuilder__Span = span

            builder = CaiZhiThreePointsBuilder(
                caizhi_pts=cai_zhi_pts,
                index_a=2,
                index_b=1,
                direction=self.PlacePlane.XAxis,
                span=span
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder.build()

            self.NiDaoGong__CaiZhiThreePointsBuilder__PointList = PointList
            self.NiDaoGong__CaiZhiThreePointsBuilder__BasePoint = BasePoint
            self.NiDaoGong__CaiZhiThreePointsBuilder__OffsetPts = OffsetPts
            self.NiDaoGong__CaiZhiThreePointsBuilder__ExtraPoint = ExtraPoint
            self.NiDaoGong__CaiZhiThreePointsBuilder__DirUnit = DirUnit
            self.NiDaoGong__CaiZhiThreePointsBuilder__SpanVectors = SpanVectors

            # ---------- UniqueRectangleFrom3Pts::0 ----------
            face = None
            ab = None
            if PointList:
                try:
                    rect_builder = UniqueRectangleFrom3Pts(PointList)
                    face, ab = rect_builder.build()
                except:
                    face, ab = None, None
            self.NiDaoGong__UniqueRectangleFrom3Pts__Face = face
            self.NiDaoGong__UniqueRectangleFrom3Pts__AB = ab

            # ---------- CaiZhiSupportLinkLines_ByBasePoint::0 ----------
            base_pt = _get_point_at(cai_zhi_pts, 3)
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__Direction = SpanVectors
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__BasePt = base_pt
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts = OffsetPts

            solver = CaiZhiSupportLinkLines_ByBasePoint(SpanVectors, base_pt, OffsetPts)
            OffsetPts2, LinkLines = solver.solve()

            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = OffsetPts2
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = LinkLines

            # ---------- step3 extra: flatten OffsetPts and connect ----------
            flat_pts = []
            _flatten_items(OffsetPts2, flat_pts)
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Flat = flat_pts

            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Polyline = _build_polyline_curve(flat_pts)
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_LineSegments = _build_line_segments(flat_pts)

            self._log("Step3 OK: NiDaoGong support built. OffsetPts(flat) = {}".format(len(flat_pts)))

        except Exception as e:
            self._log("Step3 ERROR: {}".format(e))
            # keep previous steps untouched; only null step3 outputs
            self.NiDaoGong__CaiZhiThreePointsBuilder__PointList = None
            self.NiDaoGong__CaiZhiThreePointsBuilder__BasePoint = None
            self.NiDaoGong__CaiZhiThreePointsBuilder__OffsetPts = None
            self.NiDaoGong__CaiZhiThreePointsBuilder__ExtraPoint = None
            self.NiDaoGong__CaiZhiThreePointsBuilder__DirUnit = None
            self.NiDaoGong__CaiZhiThreePointsBuilder__SpanVectors = None
            self.NiDaoGong__UniqueRectangleFrom3Pts__Face = None
            self.NiDaoGong__UniqueRectangleFrom3Pts__AB = None
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Flat = None
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Polyline = None
            self.NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_LineSegments = None

    # =====================================================
    # Step 4：乳栿参考（按 GH 连线描述串联）
    # =====================================================
    def _step_4_rufu_ref(self):
        """
        包含的核心组件：
        1) CaiZhiThreePointsBuilder::1
            Direction = PlacePlane.YAxis
            CaiZhiPts  = PointsOnLineByCumsum__PointList
            IndexA     = 2
            Span       = AllDict['RufuRef__axis2support']
            IndexB     = 1

        2) UniqueRectangleFrom3Pts::1
            Pts = CaiZhiThreePointsBuilder::1.PointList
        """
        try:
            if self.AllDict is None:
                self.AllDict = {}
            cai_zhi_pts = self.PointsOnLineByCumsum__PointList

            # ---------- CaiZhiThreePointsBuilder::1 ----------
            self.RuFuRef__CaiZhiThreePointsBuilder__Direction = self.PlacePlane.YAxis
            self.RuFuRef__CaiZhiThreePointsBuilder__CaiZhiPts = cai_zhi_pts
            self.RuFuRef__CaiZhiThreePointsBuilder__IndexA = 2
            self.RuFuRef__CaiZhiThreePointsBuilder__IndexB = 1

            span = self.AllDict.get("RufuRef__axis2support", None)
            span = _scale_numeric_like(span, getattr(self, "ScaleFactor", 1.0))
            self.RuFuRef__CaiZhiThreePointsBuilder__Span = span

            builder = CaiZhiThreePointsBuilder(
                caizhi_pts=cai_zhi_pts,
                index_a=2,
                index_b=1,
                direction=self.PlacePlane.YAxis,
                span=span
            )
            PointList, BasePoint, OffsetPts, ExtraPoint, DirUnit, SpanVectors = builder.build()

            self.RuFuRef__CaiZhiThreePointsBuilder__PointList = PointList
            self.RuFuRef__CaiZhiThreePointsBuilder__BasePoint = BasePoint
            self.RuFuRef__CaiZhiThreePointsBuilder__OffsetPts = OffsetPts
            self.RuFuRef__CaiZhiThreePointsBuilder__ExtraPoint = ExtraPoint
            self.RuFuRef__CaiZhiThreePointsBuilder__DirUnit = DirUnit
            self.RuFuRef__CaiZhiThreePointsBuilder__SpanVectors = SpanVectors

            # ---------- UniqueRectangleFrom3Pts::1 ----------
            face = None
            ab = None
            if PointList:
                try:
                    rect_builder = UniqueRectangleFrom3Pts(PointList)
                    face, ab = rect_builder.build()
                except:
                    face, ab = None, None
            self.RuFuRef__UniqueRectangleFrom3Pts__Face = face
            self.RuFuRef__UniqueRectangleFrom3Pts__AB = ab

            self._log("Step4 OK: RuFuRef built. PointList = {}".format(
                len(PointList) if PointList is not None else 0
            ))

        except Exception as e:
            self._log("Step4 ERROR: {}".format(e))
            self.RuFuRef__CaiZhiThreePointsBuilder__PointList = None
            self.RuFuRef__CaiZhiThreePointsBuilder__BasePoint = None
            self.RuFuRef__CaiZhiThreePointsBuilder__OffsetPts = None
            self.RuFuRef__CaiZhiThreePointsBuilder__ExtraPoint = None
            self.RuFuRef__CaiZhiThreePointsBuilder__DirUnit = None
            self.RuFuRef__CaiZhiThreePointsBuilder__SpanVectors = None
            self.RuFuRef__UniqueRectangleFrom3Pts__Face = None
            self.RuFuRef__UniqueRectangleFrom3Pts__AB = None


# =========================================================
# GH Python 组件 · 输出绑定区
#   - 当前只暴露 AbsStructRep / Log 两个输出端（按阶段要求）
#   - 其它内部变量全部已保存在 Solver 成员中，后续需要时在这里逐一绑定同名输出端
# =========================================================

if __name__ == "__main__":

    # --------- inputs (safe fetch) ---------
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

    try:
        _sf = ScaleFactor
    except:
        _sf = 1.0

    solver = ASR_BaTouJiaoXiangZaoComponentAssemblySolver(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        ScaleFactor=_sf,
        ghenv=ghenv
    )
    solver.run()

    # --------- final outputs ---------
    AbsStructRep = getattr(solver, "AbsStructRep", None)
    Log = getattr(solver, "Log", None)

    # --------- inputs echo (optional expose) ---------
    ScaleFactor = getattr(solver, "ScaleFactor", None)

    # =====================================================
    # （内部输出端绑定区：按需逐步暴露）
    # =====================================================

    # --------- Step 1 outputs ---------
    Value = getattr(solver, "Value", None)
    All = getattr(solver, "All", None)
    AllDict = getattr(solver, "AllDict", None)
    DBLog = getattr(solver, "DBLog", None)

    # --------- Step 2 outputs ---------
    PointsOnLineByCumsum__Values = getattr(solver, "PointsOnLineByCumsum__Values", None)
    PointsOnLineByCumsum__BasePoint = getattr(solver, "PointsOnLineByCumsum__BasePoint", None)
    PointsOnLineByCumsum__Direction = getattr(solver, "PointsOnLineByCumsum__Direction", None)
    PointsOnLineByCumsum__BaseLine = getattr(solver, "PointsOnLineByCumsum__BaseLine", None)
    PointsOnLineByCumsum__SumValue = getattr(solver, "PointsOnLineByCumsum__SumValue", None)
    PointsOnLineByCumsum__ReversedList = getattr(solver, "PointsOnLineByCumsum__ReversedList", None)
    PointsOnLineByCumsum__CumList = getattr(solver, "PointsOnLineByCumsum__CumList", None)
    PointsOnLineByCumsum__PointList = getattr(solver, "PointsOnLineByCumsum__PointList", None)

    # --------- Step 3 outputs (optional expose) ---------
    NiDaoGong__CaiZhiThreePointsBuilder__PointList = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__PointList", None)
    NiDaoGong__CaiZhiThreePointsBuilder__BasePoint = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__BasePoint", None)
    NiDaoGong__CaiZhiThreePointsBuilder__OffsetPts = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__OffsetPts", None)
    NiDaoGong__CaiZhiThreePointsBuilder__ExtraPoint = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__ExtraPoint", None)
    NiDaoGong__CaiZhiThreePointsBuilder__DirUnit = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__DirUnit", None)
    NiDaoGong__CaiZhiThreePointsBuilder__SpanVectors = getattr(solver, "NiDaoGong__CaiZhiThreePointsBuilder__SpanVectors", None)

    NiDaoGong__UniqueRectangleFrom3Pts__Face = getattr(solver, "NiDaoGong__UniqueRectangleFrom3Pts__Face", None)
    NiDaoGong__UniqueRectangleFrom3Pts__AB = getattr(solver, "NiDaoGong__UniqueRectangleFrom3Pts__AB", None)

    NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = getattr(solver, "NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts", None)
    NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = getattr(solver, "NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines", None)
    NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Flat = getattr(solver, "NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Flat", None)
    NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Polyline = getattr(solver, "NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_Polyline", None)
    NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_LineSegments = getattr(solver, "NiDaoGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts_LineSegments", None)

    # --------- Step 4 outputs (optional expose) ---------
    RuFuRef__CaiZhiThreePointsBuilder__PointList = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__PointList", None)
    RuFuRef__CaiZhiThreePointsBuilder__BasePoint = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__BasePoint", None)
    RuFuRef__CaiZhiThreePointsBuilder__OffsetPts = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__OffsetPts", None)
    RuFuRef__CaiZhiThreePointsBuilder__ExtraPoint = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__ExtraPoint", None)
    RuFuRef__CaiZhiThreePointsBuilder__DirUnit = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__DirUnit", None)
    RuFuRef__CaiZhiThreePointsBuilder__SpanVectors = getattr(solver, "RuFuRef__CaiZhiThreePointsBuilder__SpanVectors", None)

    RuFuRef__UniqueRectangleFrom3Pts__Face = getattr(solver, "RuFuRef__UniqueRectangleFrom3Pts__Face", None)
    RuFuRef__UniqueRectangleFrom3Pts__AB = getattr(solver, "RuFuRef__UniqueRectangleFrom3Pts__AB", None)


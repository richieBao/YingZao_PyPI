# -*- coding: utf-8 -*-
"""
ASR_DouKouTiaoComponentAssemblySolver_step1_2.py

将用于构建 抽象结构_枓口跳（ASR_DouKouTiao） 的一组程序组件（包含多个 ghpy 自定义组件 / GH 组件）
逐步转换为一个单独 GhPython 组件。

------------------------------------------------------------
本文件当前实现：
    - Step 1：读取数据库（DBJsonReader）
    - Step 2：材栔模式（PointsOnLineByCumsum）

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
    - 参考平面为 GH 的 Plane 约定：
        XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
        XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
        YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
      本文件不硬编码上述向量，而是直接使用 Rhino 的 Plane.XAxis/YAxis/ZAxis，
      以保证与 GH 传入 Plane 一致。
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
# 通用工具函数（参考 ASR_ChongGongComponentAssemblySolver.py 的通用部分）
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
    用于在构建几何之前缩放“尺寸参数”。

    说明：
    - 不在最后对几何做 Transform.Scale（避免点/线/面缩放中心歧义）
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

class ASR_DouKouTiaoComponentAssemblySolver(object):
    """ASR_DouKouTiao 单组件装配 Solver（当前实现 Step1-2）。"""

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, ScaleFactor=1.0, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = _safe_plane(PlacePlane)
        self.Refresh = _as_bool(Refresh, False)
        # ScaleFactor：缩放“尺寸参数”（在生成几何之前缩放）
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
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = None

        # Step 2 输出（以组件名为前缀避免重名）
        self.POC_BaseLine = None
        self.POC_SumValue = None
        self.POC_ReversedList = None
        self.POC_CumList = None
        self.POC_PointList = None

        # Step 3：令栱 支撑点（以步骤/构件名为前缀，避免后续重名）
        self.LingGong__CaiZhiThreePointsBuilder__PointList = None
        self.LingGong__CaiZhiThreePointsBuilder__BasePoint = None
        self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = None
        self.LingGong__CaiZhiThreePointsBuilder__ExtraPoint = None
        self.LingGong__CaiZhiThreePointsBuilder__DirUnit = None
        self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = None

        self.LingGong__UniqueRectangleFrom3Pts__Face = None
        self.LingGong__UniqueRectangleFrom3Pts__AB = None

        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None

        # Step 4：将 OffsetPts 连为直线段
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = None

        # =====================================================
        # Step 4（用户当前要求）：乳栿 支撑点
        #   - CaiZhiThreePointsBuilder::1
        #   - UniqueRectangleFrom3Pts::1
        #   - CaiZhiSupportLinkLines_ByBasePoint::1
        #   - OffsetPts(flat) 连线
        # =====================================================
        self.RuFu__CaiZhiThreePointsBuilder__PointList = None
        self.RuFu__CaiZhiThreePointsBuilder__BasePoint = None
        self.RuFu__CaiZhiThreePointsBuilder__OffsetPts = None
        self.RuFu__CaiZhiThreePointsBuilder__ExtraPoint = None
        self.RuFu__CaiZhiThreePointsBuilder__DirUnit = None
        self.RuFu__CaiZhiThreePointsBuilder__SpanVectors = None

        self.RuFu__UniqueRectangleFrom3Pts__Face = None
        self.RuFu__UniqueRectangleFrom3Pts__AB = None

        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None
        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = None

    # -------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 params_json -> All / AllDict …")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="AbsStructRep",
            key_field="type_code",
            key_value="ASR_DouKouTiao",
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
        # 注意：此阶段未新增输入端，因此 Values 仅从 AllDict 取；若不存在则回落为空列表。
        vals_raw = self.S1_AllDict.get("puZuoVerticalCaiZhiPattern", None)
        vals = _as_float_list(vals_raw, default=0.0)
        vals = [v * self.ScaleFactor for v in vals] if vals else []

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
    # Step 3：令栱 支撑点
    #   - CaiZhiThreePointsBuilder::0
    #   - UniqueRectangleFrom3Pts::0
    #   - CaiZhiSupportLinkLines_ByBasePoint::0
    # -------------------------------
    def step3_linggong_support_points(self):
        self.LogLines.append("Step 3：令栱 支撑点（CaiZhiThreePointsBuilder / UniqueRectangleFrom3Pts / CaiZhiSupportLinkLines_ByBasePoint）…")

        # --- 3.1 CaiZhiThreePointsBuilder::0 ---
        direction = self.PlacePlane.XAxis
        caizhi_pts = _ensure_list(self.S2_POC_PointList)

        try:
            span_raw = self.S1_AllDict.get("LingGong__axis2support", None)
            span_raw = _scale_numeric_like(span_raw, self.ScaleFactor)
            span = float(span_raw) if span_raw is not None else 0.0
        except:
            span = 0.0

        builder_3pts = CaiZhiThreePointsBuilder(
            caizhi_pts=caizhi_pts,
            index_a=2,
            index_b=1,
            direction=direction,
            span=span
        )

        (pt_list, base_pt, offset_pts, extra_pt, dir_unit, span_vecs) = builder_3pts.build()

        self.LingGong__CaiZhiThreePointsBuilder__PointList = pt_list
        self.LingGong__CaiZhiThreePointsBuilder__BasePoint = base_pt
        self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = offset_pts
        self.LingGong__CaiZhiThreePointsBuilder__ExtraPoint = extra_pt
        self.LingGong__CaiZhiThreePointsBuilder__DirUnit = dir_unit
        self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = span_vecs

        # --- 3.2 UniqueRectangleFrom3Pts::0 ---
        face = None
        ab = None
        if pt_list:
            try:
                rect_builder = UniqueRectangleFrom3Pts(pt_list)
                face, ab = rect_builder.build()
            except:
                face, ab = None, None

        self.LingGong__UniqueRectangleFrom3Pts__Face = face
        self.LingGong__UniqueRectangleFrom3Pts__AB = ab

        # --- 3.3 CaiZhiSupportLinkLines_ByBasePoint::0 ---
        base_pt2 = None
        try:
            if len(caizhi_pts) > 3:
                base_pt2 = caizhi_pts[3]
            elif caizhi_pts:
                base_pt2 = caizhi_pts[-1]
        except:
            base_pt2 = None

        solver_link = CaiZhiSupportLinkLines_ByBasePoint(span_vecs, base_pt2, offset_pts)
        offset_pts2, link_lines = solver_link.solve()

        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = offset_pts2
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = link_lines

        self.LogLines.append(
            "Step 3 完成：Span={} 3Pts={} RectFace={} LinkLines={}".format(
                span,
                len(_ensure_list(pt_list)),
                "OK" if face is not None else "None",
                len(_ensure_list(link_lines))
            )
        )

    # -------------------------------
    # Step 4：将 CaiZhiSupportLinkLines_ByBasePoint::0 的 OffsetPts 展平并连为直线段
    # -------------------------------
    def step4_linggong_offsetpts_line(self):
        self.LogLines.append("Step 4：连线（OffsetPts 展平 -> 直线段）…")

        flat_pts = []
        _flatten_items(self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts, flat_pts)
        pts = []
        for p in flat_pts:
            try:
                pts.append(rg.Point3d(p))
            except:
                pass

        line_obj = None
        if len(pts) >= 2:
            if len(pts) == 2:
                try:
                    line_obj = rg.Line(pts[0], pts[1])
                except:
                    line_obj = None
            else:
                try:
                    pl = rg.Polyline(pts)
                    line_obj = rg.PolylineCurve(pl)
                except:
                    line_obj = None

        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = line_obj
        self.LogLines.append("Step 4 完成：OffsetPts(flat)={} LineObj={}".format(len(pts), type(line_obj).__name__ if line_obj is not None else "None"))

    # -------------------------------
    # Step 4（乳栿）：支撑点 + 连线
    #   1) CaiZhiThreePointsBuilder::1
    #   2) UniqueRectangleFrom3Pts::1
    #   3) CaiZhiSupportLinkLines_ByBasePoint::1
    #   4) OffsetPts(flat) 连为直线段
    # -------------------------------
    def step4_rufu_support_points(self):
        self.LogLines.append("Step 4（乳栿）：支撑点（CaiZhiThreePointsBuilder::1 / UniqueRectangleFrom3Pts::1 / CaiZhiSupportLinkLines_ByBasePoint::1）…")

        # --- 4.1 CaiZhiThreePointsBuilder::1 ---
        direction = self.PlacePlane.YAxis
        caizhi_pts = _ensure_list(self.S2_POC_PointList)

        try:
            span_raw = self.S1_AllDict.get("RufuRef__axis2support", None)
            span_raw = _scale_numeric_like(span_raw, self.ScaleFactor)
            span = float(span_raw) if span_raw is not None else 0.0
        except:
            span = 0.0

        builder_3pts = CaiZhiThreePointsBuilder(
            caizhi_pts=caizhi_pts,
            index_a=2,
            index_b=1,
            direction=direction,
            span=span
        )

        (pt_list, base_pt, offset_pts, extra_pt, dir_unit, span_vecs) = builder_3pts.build()

        self.RuFu__CaiZhiThreePointsBuilder__PointList = pt_list
        self.RuFu__CaiZhiThreePointsBuilder__BasePoint = base_pt
        self.RuFu__CaiZhiThreePointsBuilder__OffsetPts = offset_pts
        self.RuFu__CaiZhiThreePointsBuilder__ExtraPoint = extra_pt
        self.RuFu__CaiZhiThreePointsBuilder__DirUnit = dir_unit
        self.RuFu__CaiZhiThreePointsBuilder__SpanVectors = span_vecs

        # --- 4.2 UniqueRectangleFrom3Pts::1 ---
        face = None
        ab = None
        if pt_list:
            try:
                rect_builder = UniqueRectangleFrom3Pts(pt_list)
                face, ab = rect_builder.build()
            except:
                face, ab = None, None

        self.RuFu__UniqueRectangleFrom3Pts__Face = face
        self.RuFu__UniqueRectangleFrom3Pts__AB = ab

        # --- 4.3 CaiZhiSupportLinkLines_ByBasePoint::1 ---
        base_pt2 = None
        try:
            if len(caizhi_pts) > 3:
                base_pt2 = caizhi_pts[3]
            elif caizhi_pts:
                base_pt2 = caizhi_pts[-1]
        except:
            base_pt2 = None

        solver_link = CaiZhiSupportLinkLines_ByBasePoint(span_vecs, base_pt2, offset_pts)
        offset_pts2, link_lines = solver_link.solve()

        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = offset_pts2
        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = link_lines

        # --- 4.4 OffsetPts(flat) 连为直线段 ---
        flat_pts = []
        _flatten_items(offset_pts2, flat_pts)
        pts = []
        for p in flat_pts:
            try:
                pts.append(rg.Point3d(p))
            except:
                pass

        line_obj = None
        if len(pts) >= 2:
            if len(pts) == 2:
                try:
                    line_obj = rg.Line(pts[0], pts[1])
                except:
                    line_obj = None
            else:
                try:
                    pl = rg.Polyline(pts)
                    line_obj = rg.PolylineCurve(pl)
                except:
                    line_obj = None

        self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = line_obj

        self.LogLines.append(
            "Step 4（乳栿）完成：Span={} 3Pts={} RectFace={} LinkLines={} OffsetPts(flat)={} LineObj={}".format(
                span,
                len(_ensure_list(pt_list)),
                "OK" if face is not None else "None",
                len(_ensure_list(link_lines)),
                len(pts),
                type(line_obj).__name__ if line_obj is not None else "None"
            )
        )

    # -------------------------------
    # 总执行入口
    # -------------------------------
    def run(self):
        self.LogLines = []
        self.Log = ""

        if not self.DBPath:
            self.LogLines.append("WARN: DBPath 为空，Step1 将无法读取数据库。")
        try:
            self.step1_read_db()
        except Exception as e:
            self.LogLines.append("ERROR in Step 1: {}".format(e))

        try:
            self.step2_points_on_line_by_cumsum()
        except Exception as e:
            self.LogLines.append("ERROR in Step 2: {}".format(e))

        try:
            self.step3_linggong_support_points()
        except Exception as e:
            self.LogLines.append("ERROR in Step 3: {}".format(e))

        try:
            self.step4_linggong_offsetpts_line()
        except Exception as e:
            self.LogLines.append("ERROR in Step 4: {}".format(e))

        try:
            self.step4_rufu_support_points()
        except Exception as e:
            self.LogLines.append("ERROR in Step 4（乳栿）: {}".format(e))

        # 阶段性输出：AbsStructRep = ComponentAssembly
        # Step 3-4 追加到组合体（尽量保持已有部分不改动）
        try:
            if self.LingGong__UniqueRectangleFrom3Pts__Face is not None:
                self.ComponentAssembly.append(self.LingGong__UniqueRectangleFrom3Pts__Face)
            if self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines is not None:
                self.ComponentAssembly.append(self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines)
            if self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine is not None:
                self.ComponentAssembly.append(self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine)

            # ---- Step 4（乳栿）追加 ----
            if self.RuFu__UniqueRectangleFrom3Pts__Face is not None:
                self.ComponentAssembly.append(self.RuFu__UniqueRectangleFrom3Pts__Face)
            if self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines is not None:
                self.ComponentAssembly.append(self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines)
            if self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine is not None:
                self.ComponentAssembly.append(self.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine)
        except:
            pass

        self.AbsStructRep = self.ComponentAssembly

        self.Log = "\n".join([str(x) for x in _ensure_list(self.LogLines)])
        return self.AbsStructRep, self.Log


# =====================================================
# GH Python 组件 · 输出绑定区
# 说明：
# - 当前只“要求暴露” AbsStructRep / Log 两个输出端
# - 但仍按同名规则，把 Solver 成员逐一绑定为同名变量：
#   你后续在 GH 里新增输出端时，只要名字与下述变量一致即可直接取到值。
# =====================================================

if __name__ == "__main__":
    try:
        Solver = ASR_DouKouTiaoComponentAssemblySolver(DBPath, PlacePlane, Refresh, ScaleFactor, ghenv)
        AbsStructRep, Log = Solver.run()

        # ---- Step 1 outputs ----
        Value = Solver.S1_Value
        All = Solver.S1_All
        AllDict = Solver.S1_AllDict
        DBLog = Solver.S1_DBLog

        # ---- Step 2 outputs ----
        POC_BaseLine = Solver.S2_POC_BaseLine
        POC_SumValue = Solver.S2_POC_SumValue
        POC_ReversedList = Solver.S2_POC_ReversedList
        POC_CumList = Solver.S2_POC_CumList
        POC_PointList = Solver.S2_POC_PointList

        # ---- Step 3 outputs (LingGong) ----
        LingGong__CaiZhiThreePointsBuilder__PointList = Solver.LingGong__CaiZhiThreePointsBuilder__PointList
        LingGong__CaiZhiThreePointsBuilder__BasePoint = Solver.LingGong__CaiZhiThreePointsBuilder__BasePoint
        LingGong__CaiZhiThreePointsBuilder__OffsetPts = Solver.LingGong__CaiZhiThreePointsBuilder__OffsetPts
        LingGong__CaiZhiThreePointsBuilder__ExtraPoint = Solver.LingGong__CaiZhiThreePointsBuilder__ExtraPoint
        LingGong__CaiZhiThreePointsBuilder__DirUnit = Solver.LingGong__CaiZhiThreePointsBuilder__DirUnit
        LingGong__CaiZhiThreePointsBuilder__SpanVectors = Solver.LingGong__CaiZhiThreePointsBuilder__SpanVectors

        LingGong__UniqueRectangleFrom3Pts__Face = Solver.LingGong__UniqueRectangleFrom3Pts__Face
        LingGong__UniqueRectangleFrom3Pts__AB = Solver.LingGong__UniqueRectangleFrom3Pts__AB

        LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = Solver.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts
        LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = Solver.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines

        # ---- Step 4 outputs ----
        LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = Solver.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine

        # ---- Step 4（乳栿）outputs ----
        RuFu__CaiZhiThreePointsBuilder__PointList = Solver.RuFu__CaiZhiThreePointsBuilder__PointList
        RuFu__CaiZhiThreePointsBuilder__BasePoint = Solver.RuFu__CaiZhiThreePointsBuilder__BasePoint
        RuFu__CaiZhiThreePointsBuilder__OffsetPts = Solver.RuFu__CaiZhiThreePointsBuilder__OffsetPts
        RuFu__CaiZhiThreePointsBuilder__ExtraPoint = Solver.RuFu__CaiZhiThreePointsBuilder__ExtraPoint
        RuFu__CaiZhiThreePointsBuilder__DirUnit = Solver.RuFu__CaiZhiThreePointsBuilder__DirUnit
        RuFu__CaiZhiThreePointsBuilder__SpanVectors = Solver.RuFu__CaiZhiThreePointsBuilder__SpanVectors

        RuFu__UniqueRectangleFrom3Pts__Face = Solver.RuFu__UniqueRectangleFrom3Pts__Face
        RuFu__UniqueRectangleFrom3Pts__AB = Solver.RuFu__UniqueRectangleFrom3Pts__AB

        RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = Solver.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts
        RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = Solver.RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines
        RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = Solver.RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine

    except Exception as _e:
        # 避免组件变红：尽量输出空值与错误信息
        AbsStructRep = None
        Log = "FATAL: {}".format(_e)

        Value = None
        All = None
        AllDict = {}
        DBLog = None

        POC_BaseLine = None
        POC_SumValue = None
        POC_ReversedList = None
        POC_CumList = None
        POC_PointList = None

        LingGong__CaiZhiThreePointsBuilder__PointList = None
        LingGong__CaiZhiThreePointsBuilder__BasePoint = None
        LingGong__CaiZhiThreePointsBuilder__OffsetPts = None
        LingGong__CaiZhiThreePointsBuilder__ExtraPoint = None
        LingGong__CaiZhiThreePointsBuilder__DirUnit = None
        LingGong__CaiZhiThreePointsBuilder__SpanVectors = None

        LingGong__UniqueRectangleFrom3Pts__Face = None
        LingGong__UniqueRectangleFrom3Pts__AB = None

        LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None

        LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = None

        RuFu__CaiZhiThreePointsBuilder__PointList = None
        RuFu__CaiZhiThreePointsBuilder__BasePoint = None
        RuFu__CaiZhiThreePointsBuilder__OffsetPts = None
        RuFu__CaiZhiThreePointsBuilder__ExtraPoint = None
        RuFu__CaiZhiThreePointsBuilder__DirUnit = None
        RuFu__CaiZhiThreePointsBuilder__SpanVectors = None

        RuFu__UniqueRectangleFrom3Pts__Face = None
        RuFu__UniqueRectangleFrom3Pts__AB = None

        RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        RuFu__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None
        RuFu__CaiZhiSupportLinkLines_ByBasePoint__OffsetPtsLine = None


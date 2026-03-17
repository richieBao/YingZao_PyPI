# -*- coding: utf-8 -*-
"""
ASR_DanGongComponentAssemblySolver
抽象结构_单栱（ASR_DanGong）组件总装求解器（数据库驱动 | 逐步实现）

目标：
- 将用于构建 ASR_DanGong 的一组 GH / GhPython 组件，逐步“内聚”为单一 GhPython 组件
- 输入端最小化：DBPath / PlacePlane / Refresh
- 其它参数从数据库 AbsStructRep.params_json（ExportAll= True -> All）或默认值获取
- 在 ghpy 内保留各子步骤输出（Solver 成员变量），便于日后增减输出端

本文件当前实现进度：
- step 1：读取数据库（等价 DBJsonReader 组件）
  Table    = "AbsStructRep"
  KeyField = "type_code"
  KeyValue = "ASR_DanGong"
  Field    = "params_json"
  ExportAll= True

输入（GhPython 建议设置）:
    DBPath : str (Item)
        SQLite 数据库文件路径
        Access: Item
        TypeHints: str

    PlacePlane : rg.Plane (Item)
        放置参考平面
        默认：GH WorldXY，但原点强制为 (100,100,0)
        Access: Item
        TypeHints: Plane

    Refresh : bool (Item)
        刷新开关：True 时强制重读数据库（并刷新缓存）
        Access: Item
        TypeHints: bool

    ScaleFactor : float (Item)
        比例缩放因子（默认 1.0）。
        按比例缩放“尺寸参数值”（在生成几何之前缩放），从而所有几何与输出同步缩放。
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    AbsStructRep : object (Item)
        最终组合体（当前 step 1 尚不生成几何，先为 None）
        Access: Item

    Log : str (Item)
        日志信息
        Access: Item
"""

import Rhino
import Rhino.Geometry as rg
from yingzao.ancientArchi import DBJsonReader
from yingzao.ancientArchi import PointsOnLineByCumsum

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.02.19"

'''
ghenv.Component.Name = "ASR_DanGongComponentAssemblySolver"
ghenv.Component.NickName = "ASR_DanGong_Solver"
ghenv.Component.Description = "DB-driven assembly solver for ASR_DanGong (step-by-step)"
ghenv.Component.Message = "step 3"
ghenv.Component.Category = "YingZaoLab"
ghenv.Component.SubCategory = "AbsStructRep"
'''

# =========================================================
# 通用工具函数（后续步骤会持续复用/补充）
# =========================================================

def _is_none_like(x):
    """GH 中常见的“空输入”判定：None / 空列表 / 空树等。"""
    if x is None:
        return True
    try:
        # GH 可能传入空的 System.Collections.IEnumerable
        if hasattr(x, "__len__") and len(x) == 0:
            return True
    except:
        pass
    return False


def _default_place_plane(user_plane):
    """
    PlacePlane 默认规则（按你的要求）：
    - 若输入端 PlacePlane 无值：默认 GH WorldXY，且原点为 (100,100,0)
    - 若输入端 PlacePlane 有值：严格使用该平面（不强改原点/轴向）
    """
    if _is_none_like(user_plane):
        pl = rg.Plane.WorldXY
        pl.Origin = rg.Point3d(100, 100, 0)
        return pl
    # 有输入则拷贝一份，避免改到外部引用
    return rg.Plane(user_plane)


def _safe_to_dict(all_kv_pairs):
    """
    将 DBJsonReader.ExportAll=True 得到的 All（形如 [(key,val),...] 或 tuple 列表）
    转成 dict，便于后续按 All 命名规则直接提取：
      FT_AlignToolToTimber_1__BlockRotDeg -> dict["FT_AlignToolToTimber_1__BlockRotDeg"]
    若 key 重复：后者覆盖前者（与常见 dict 行为一致）
    """
    d = {}
    if _is_none_like(all_kv_pairs):
        return d
    try:
        for item in all_kv_pairs:
            if item is None:
                continue
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                k = item[0]
                v = item[1]
                d[k] = v
    except:
        # 保底：不抛红
        pass
    return d


def _deep_flatten(obj):
    """
    递归拍平 list/tuple/可迭代容器（排除 str/bytes 与 Rhino 常见几何类型）。
    用于避免 GH 输出出现 System.Collections.Generic.List`1[System.Object] 的嵌套壳。
    """
    if obj is None:
        return []
    # 不展开字符串
    if isinstance(obj, (str, bytes)):
        return [obj]
    # Rhino 常见类型：不展开
    rhino_types = (rg.Point3d, rg.Vector3d, rg.Plane, rg.Line, rg.Curve, rg.Brep)
    try:
        if isinstance(obj, rhino_types):
            return [obj]
    except:
        pass
    # 展开 list/tuple/其他可迭代
    try:
        if isinstance(obj, (list, tuple)):
            res = []
            for it in obj:
                res.extend(_deep_flatten(it))
            return res
        # .NET IEnumerable / 其他 iterable
        if hasattr(obj, "__iter__"):
            res = []
            for it in obj:
                res.extend(_deep_flatten(it))
            return res
    except:
        pass
    return [obj]


def _scale_numeric_like(x, scale_factor):
    """将数值/字符串数值/嵌套 list/tuple 中的数值整体乘以 scale_factor。
    用于在构建几何之前缩放“尺寸参数”。

    说明：该策略与 AbsStructRep_SiPU_Corner_ComponentAssemblySolver 的实现方式一致：
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


# =========================================================
# Solver 主类（逐步实现）
# =========================================================

class ASR_DanGongComponentAssemblySolver(object):
    def __init__(self, db_path, place_plane=None, refresh=False, scale_factor=1.0, ghenv=None):
        self.ghenv = ghenv

        # ---- Inputs ----
        self.DBPath = db_path
        self.PlacePlane_In = place_plane
        self.Refresh = bool(refresh)

        # ScaleFactor（缩放“尺寸参数”）：
        # - 该值仅用于缩放“从数据库/输入端读到的距离/尺寸参数”
        # - 不直接对输出几何做 Transform.Scale（避免点/线/面缩放中心歧义）
        try:
            self.ScaleFactor = float(scale_factor) if scale_factor is not None else 1.0
        except:
            self.ScaleFactor = 1.0

        # ---- Resolved/Prepared ----
        self.PlacePlane = _default_place_plane(self.PlacePlane_In)

        # ---- step 1 outputs (kept as members) ----
        self.DB_Value = None
        self.DB_All = None
        self.DB_AllDict = None
        self.DB_Log = ""

        # ---- step 2 outputs (PointsOnLineByCumsum_1) ----
        self.PointsOnLineByCumsum__Values = None
        self.PointsOnLineByCumsum__BasePoint = None
        self.PointsOnLineByCumsum__Direction = None
        self.PointsOnLineByCumsum__BaseLine = None
        self.PointsOnLineByCumsum__SumValue = None
        self.PointsOnLineByCumsum__ReversedList = None
        self.PointsOnLineByCumsum__CumList = None
        self.PointsOnLineByCumsum__PointList = None

        # ---- step 3 outputs (LingGong support points) ----
        self.LingGong__Direction = None
        self.LingGong__CaiZhiPts = None
        self.LingGong__IndexA = 2
        self.LingGong__IndexB = 1
        self.LingGong__Span = None

        # CaiZhiThreePointsBuilder outputs
        self.LingGong__CaiZhiThreePointsBuilder__PointList = None
        self.LingGong__CaiZhiThreePointsBuilder__BasePoint = None
        self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = None
        self.LingGong__CaiZhiThreePointsBuilder__ExtraPoint = None
        self.LingGong__CaiZhiThreePointsBuilder__DirUnit = None
        self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = None

        # UniqueRectangleFrom3Pts outputs
        self.LingGong__UniqueRectangleFrom3Pts__Face = None
        self.LingGong__UniqueRectangleFrom3Pts__AB = None

        # CaiZhiSupportLinkLines_ByBasePoint outputs
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__BasePt = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__Direction = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = None

        # step 4: connect OffsetPts into a line segment
        self.LingGong__OffsetPtsLine = None
        # ---- final outputs placeholders ----
        self.AbsStructRep = None
        self.Log = ""

    # -------------------------
    # 通用取参：输入端优先（若有新增输入端），再 DB_AllDict，再默认值
    # -------------------------
    def _get_param(self, key, default=None, alt_keys=None):
        """
        从 self.DB_AllDict 取参数值。
        - key: 主键
        - alt_keys: 备用键列表（会依次尝试）
        """
        if self.DB_AllDict is None:
            return default
        if key in self.DB_AllDict:
            return self.DB_AllDict.get(key, default)
        if alt_keys:
            for k in alt_keys:
                if k in self.DB_AllDict:
                    return self.DB_AllDict.get(k, default)
        return default

    def _to_float_list(self, values):
        """
        Values 输入（可能为 int/float/str/list/tuple/嵌套）尽量转为 list[float]
        无法转换的项跳过；None 视为空列表
        """
        if values is None:
            return []
        flat = _deep_flatten(values)
        out_list = []
        for v in flat:
            if v is None:
                continue
            if isinstance(v, bool):
                out_list.append(1.0 if v else 0.0)
                continue
            if isinstance(v, (int, float)):
                out_list.append(float(v))
                continue
            try:
                s = str(v).strip()
                if s == "":
                    continue
                out_list.append(float(s))
            except:
                # 跳过无效项
                continue
        return out_list

    # -------------------------
    # step 1：读取数据库（DBJsonReader）
    # -------------------------
    def step_1_read_db(self):
        # 固定读取配置（按你的 step 1 说明）
        table = "AbsStructRep"
        key_field = "type_code"
        key_value = "ASR_DanGong"
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

        value, all_pairs, log = reader.run()

        self.DB_Value = value
        self.DB_All = all_pairs
        self.DB_AllDict = _safe_to_dict(all_pairs)
        self.DB_Log = log if log is not None else ""

        return self

    # -------------------------
    # step 2：材栔模式（PointsOnLineByCumsum 组件）
    # 组件名：PointsOnLineByCumsum_1
    # Inputs:
    #   Values    = DB['puZuoVerticalCaiZhiPattern']
    #   BasePoint = PlacePlane.Origin
    #   Direction = PlacePlane.ZAxis
    # Outputs（全部以组件名前缀保存到 Solver 成员变量）:
    #   BaseLine, SumValue, ReversedList, CumList, PointList
    # -------------------------
    def step_2_cai_zhi_pattern_points_on_line_by_cumsum(self):
        # Values：优先按业务字段名取，其次按 All 命名规则（组件名__端口名）取
        raw_values = self._get_param(
            "puZuoVerticalCaiZhiPattern",
            default=None,
            alt_keys=["PointsOnLineByCumsum__Values", "PointsOnLineByCumsum__Values"]
        )

        # ScaleFactor：缩放累计距离序列（影响点位与后续构件位置）
        raw_values = _scale_numeric_like(raw_values, getattr(self, 'ScaleFactor', 1.0))
        values = self._to_float_list(raw_values)

        base_pt = self.PlacePlane.Origin
        dir_vec = self.PlacePlane.ZAxis

        # 保存输入侧（带组件名前缀）
        self.PointsOnLineByCumsum__Values = values
        self.PointsOnLineByCumsum__BasePoint = base_pt
        self.PointsOnLineByCumsum__Direction = dir_vec

        # 严格按原组件代码调用 yingzao.ancientArchi.PointsOnLineByCumsum
        builder = PointsOnLineByCumsum(values, base_pt, dir_vec, clamp=True)
        base_line, sum_value, rev_list, cum_list, pt_list = builder.build()

        # 输出拍平（避免嵌套壳）
        self.PointsOnLineByCumsum__BaseLine = base_line
        self.PointsOnLineByCumsum__SumValue = float(sum_value) if sum_value is not None else 0.0
        self.PointsOnLineByCumsum__ReversedList = _deep_flatten(rev_list)
        self.PointsOnLineByCumsum__CumList = _deep_flatten(cum_list)
        self.PointsOnLineByCumsum__PointList = _deep_flatten(pt_list)

        return self

    # -------------------------
    # 总入口：run
    # -------------------------

    # -------------------------
    # step 3：令栱 支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts + CaiZhiSupportLinkLines_ByBasePoint）
    # -------------------------
    def step_3_ling_gong_support_points(self):
        '''
        按你的 step 3 说明实现：

        1) CaiZhiThreePointsBuilder
           - Direction = PlacePlane.XAxis
           - CaiZhiPts = PointsOnLineByCumsum__PointList
           - IndexA = 2
           - Span = DB 参数 "LingGong__axis2support"
           - IndexB = 1

        2) UniqueRectangleFrom3Pts
           - Pts = CaiZhiThreePointsBuilder.PointList

        3) CaiZhiSupportLinkLines_ByBasePoint
           - Direction  = CaiZhiThreePointsBuilder.SpanVectors
           - BasePt     = PointsOnLineByCumsum__PointList[3]
           - SupportPts = CaiZhiThreePointsBuilder.OffsetPts

        4) 将 CaiZhiSupportLinkLines_ByBasePoint.OffsetPts 连为直线段（Line）。
        '''

        # -------------------------
        # 0) 输入准备与兜底
        # -------------------------
        try:
            from yingzao.ancientArchi import CaiZhiThreePointsBuilder, UniqueRectangleFrom3Pts, \
                CaiZhiSupportLinkLines_ByBasePoint
        except Exception as e:
            self.DB_Log += "\n[step 3] import yingzao.ancientArchi failed: %s" % str(e)
            return self

        # Direction: PlacePlane.XAxis
        self.LingGong__Direction = self.PlacePlane.XAxis

        # CaiZhiPts: step 2 point list
        pts = self.PointsOnLineByCumsum__PointList
        self.LingGong__CaiZhiPts = pts

        # Span: from DB
        span_raw = self._get_param("LingGong__axis2support", default=0.0)

        # ScaleFactor：缩放该距离参数（支持标量或 [plus, minus] 列表）
        span_raw = _scale_numeric_like(span_raw, getattr(self, 'ScaleFactor', 1.0))
        self.LingGong__Span = span_raw

        # 若点列不足，直接输出空（不报错、不变红）
        if _is_none_like(pts):
            self.LingGong__CaiZhiThreePointsBuilder__PointList = []
            self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = []
            self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = []
            self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = []
            self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = []
            self.LingGong__OffsetPtsLine = None
            return self

        pts_flat = _deep_flatten(pts)

        # -------------------------
        # 1) CaiZhiThreePointsBuilder
        # -------------------------
        try:
            builder = CaiZhiThreePointsBuilder(
                caizhi_pts=pts_flat,
                index_a=int(self.LingGong__IndexA),
                index_b=int(self.LingGong__IndexB),
                direction=self.LingGong__Direction,
                span=self.LingGong__Span
            )
            (pl, bp, offpts, exp, diru, spanvecs) = builder.build()

            self.LingGong__CaiZhiThreePointsBuilder__PointList = _deep_flatten(pl)
            self.LingGong__CaiZhiThreePointsBuilder__BasePoint = bp
            self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = _deep_flatten(offpts)
            self.LingGong__CaiZhiThreePointsBuilder__ExtraPoint = exp
            self.LingGong__CaiZhiThreePointsBuilder__DirUnit = diru
            self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = _deep_flatten(spanvecs)
        except Exception as e:
            self.DB_Log += "\n[step 3] CaiZhiThreePointsBuilder failed: %s" % str(e)
            self.LingGong__CaiZhiThreePointsBuilder__PointList = []
            self.LingGong__CaiZhiThreePointsBuilder__OffsetPts = []
            self.LingGong__CaiZhiThreePointsBuilder__SpanVectors = []
            return self

        # -------------------------
        # 2) UniqueRectangleFrom3Pts
        # -------------------------
        try:
            rect_pts = self.LingGong__CaiZhiThreePointsBuilder__PointList
            if rect_pts and len(rect_pts) >= 3:
                rect_builder = UniqueRectangleFrom3Pts(rect_pts)
                face, ab = rect_builder.build()
                self.LingGong__UniqueRectangleFrom3Pts__Face = face
                self.LingGong__UniqueRectangleFrom3Pts__AB = ab
            else:
                self.LingGong__UniqueRectangleFrom3Pts__Face = None
                self.LingGong__UniqueRectangleFrom3Pts__AB = None
        except Exception as e:
            self.DB_Log += "\n[step 3] UniqueRectangleFrom3Pts failed: %s" % str(e)
            self.LingGong__UniqueRectangleFrom3Pts__Face = None
            self.LingGong__UniqueRectangleFrom3Pts__AB = None

        # -------------------------
        # 3) CaiZhiSupportLinkLines_ByBasePoint
        # -------------------------
        # BasePt = pointlist[3]
        base_pt = None
        try:
            if len(pts_flat) > 3:
                base_pt = pts_flat[3]
        except:
            base_pt = None
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__BasePt = base_pt
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__Direction = self.LingGong__CaiZhiThreePointsBuilder__SpanVectors
        self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts = self.LingGong__CaiZhiThreePointsBuilder__OffsetPts

        try:
            if (not _is_none_like(base_pt)
                    and self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__Direction
                    and self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts):

                # 兼容 yingzao.ancientArchi 内部类的不同签名/方法名：
                # - 你给的 GH 组件包装：CaiZhiSupportLinkLines_ByBasePoint(Direction, BasePt, SupportPts) -> solve()
                # - 也可能存在 build() / solve() / run() 等
                D = self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__Direction
                S = self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__SupportPts

                link_builder = None

                # 1) 先按你给的“组件包装调用方式”尝试（最优先）
                try:
                    link_builder = CaiZhiSupportLinkLines_ByBasePoint(D, base_pt, S)
                except:
                    link_builder = None

                # 2) 若失败，再尝试常见的命名参数形式
                if link_builder is None:
                    try:
                        link_builder = CaiZhiSupportLinkLines_ByBasePoint(Direction=D, BasePt=base_pt, SupportPts=S)
                    except:
                        link_builder = None

                if link_builder is None:
                    try:
                        link_builder = CaiZhiSupportLinkLines_ByBasePoint(direction_vecs=D, base_pt=base_pt,
                                                                          support_pts=S)
                    except:
                        link_builder = None

                if link_builder is None:
                    raise Exception("Cannot construct CaiZhiSupportLinkLines_ByBasePoint with available signatures.")

                # 3) 调用：优先 solve()，其次 build()，再其次 run()
                if hasattr(link_builder, "solve"):
                    offset_pts2, link_lines = link_builder.solve()
                elif hasattr(link_builder, "build"):
                    offset_pts2, link_lines = link_builder.build()
                elif hasattr(link_builder, "run"):
                    offset_pts2, link_lines = link_builder.run()
                else:
                    raise Exception("CaiZhiSupportLinkLines_ByBasePoint has no solve/build/run method.")

                # 注意：OffsetPts/LinkLines 可能是嵌套列表或 Tree 分支数据，必须完全展平
                self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = _deep_flatten(offset_pts2)
                self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = _deep_flatten(link_lines)
            else:
                self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = []
                self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = []
        except Exception as e:
            self.DB_Log += "\n[step 3] CaiZhiSupportLinkLines_ByBasePoint failed: %s" % str(e)
            self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts = []
            self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines = []

        # -------------------------
        # 4) OffsetPts 连线
        # -------------------------
        try:
            # 注意：用户要求把 LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts 中的点
            # 连接成“一个直线段”。OffsetPts 可能来自嵌套 list / Tree 多分支，必须完全展平。
            ops = _deep_flatten(self.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts)

            # 尽量把点转换为 Point3d（过滤无效项）
            ops_pts = []
            for p in ops:
                if p is None:
                    continue
                if isinstance(p, rg.Point3d):
                    ops_pts.append(p)
                    continue
                # GH_Point / 其他点壳
                try:
                    if hasattr(p, "Location"):
                        ops_pts.append(rg.Point3d(p.Location))
                        continue
                except:
                    pass
                try:
                    ops_pts.append(rg.Point3d(p))
                except:
                    pass

            # 连接策略：
            # - 若仅 2 个点：直接连线
            # - 若 >2 个点：取“展平后的首点与末点”连为一个直线段（仍满足“一个直线段”输出）
            if ops_pts and len(ops_pts) >= 2:
                self.LingGong__OffsetPtsLine = rg.Line(ops_pts[0], ops_pts[-1])
            else:
                self.LingGong__OffsetPtsLine = None
        except:
            self.LingGong__OffsetPtsLine = None

        return self

    def run(self):
        # step 1
        self.step_1_read_db()

        # step 2
        self.step_2_cai_zhi_pattern_points_on_line_by_cumsum()

        # step 3
        self.step_3_ling_gong_support_points()

        # 当前阶段：仍不输出最终 AbsStructRep（逐步实现）
        self.AbsStructRep = None

        # 汇总日志
        self.Log = "[ASR_DanGongSolver] step 3 done.\n"
        if self.DB_Log:
            self.Log += str(self.DB_Log)

        return self

if __name__ == '__main__':
    # =========================================================
    # GH Python 组件入口
    # =========================================================

    # 容错：没有 DBPath 时不让组件变红（输出 None + Log）
    if _is_none_like(DBPath):
        Solver = None
        AbsStructRep = None
        Log = "[ASR_DanGongSolver] DBPath is empty. Please provide DBPath."

        # step 1 outputs
        DB_Value = None
        DB_All = None
        DB_AllDict = None
        DB_Log = None

        # step 2 outputs
        PointsOnLineByCumsum__Values = None
        PointsOnLineByCumsum__BasePoint = None
        PointsOnLineByCumsum__Direction = None
        PointsOnLineByCumsum__BaseLine = None
        PointsOnLineByCumsum__SumValue = None
        PointsOnLineByCumsum__ReversedList = None
        PointsOnLineByCumsum__CumList = None
        PointsOnLineByCumsum__PointList = None

        # step 3 outputs (LingGong support points)
        # ---- 简化后的输出名（推荐用于 GH 输出端）----
        LingGong__PointList = None
        LingGong__BasePoint = None
        LingGong__OffsetPts = None
        LingGong__ExtraPoint = None
        LingGong__DirUnit = None
        LingGong__SpanVectors = None

        LingGong__RectFace = None
        LingGong__RectAB = None

        LingGong__Support_OffsetPts = None
        LingGong__Support_LinkLines = None
        LingGong__OffsetPtsLine = None

        # ---- 兼容旧输出名（如你暂时未改 GH 输出端）----
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

    else:
        Solver = ASR_DanGongComponentAssemblySolver(
            db_path=DBPath,
            place_plane=PlacePlane,
            refresh=Refresh,
            scale_factor=ScaleFactor,
            ghenv=ghenv
        ).run()

        # =====================================================
        # GH Python 组件 · 输出绑定区
        # 说明：
        # - 当前只暴露 AbsStructRep / Log 两个输出端（按你的阶段要求）
        # - 其它内部变量全部已保存在 Solver 成员中，后续需要时在这里逐一绑定同名输出端
        # =====================================================

        AbsStructRep = Solver.AbsStructRep
        Log = Solver.Log

        # ---- step 1 outputs (optional expose) ----
        DB_Value = Solver.DB_Value
        DB_All = Solver.DB_All
        DB_AllDict = Solver.DB_AllDict
        DB_Log = Solver.DB_Log

        # ---- step 2 outputs (PointsOnLineByCumsum_1) ----
        PointsOnLineByCumsum__Values = Solver.PointsOnLineByCumsum__Values
        PointsOnLineByCumsum__BasePoint = Solver.PointsOnLineByCumsum__BasePoint
        PointsOnLineByCumsum__Direction = Solver.PointsOnLineByCumsum__Direction
        PointsOnLineByCumsum__BaseLine = Solver.PointsOnLineByCumsum__BaseLine
        PointsOnLineByCumsum__SumValue = Solver.PointsOnLineByCumsum__SumValue
        PointsOnLineByCumsum__ReversedList = Solver.PointsOnLineByCumsum__ReversedList
        PointsOnLineByCumsum__CumList = Solver.PointsOnLineByCumsum__CumList
        PointsOnLineByCumsum__PointList = Solver.PointsOnLineByCumsum__PointList

        # step 3 outputs (LingGong support points)
        # ---- 简化后的输出名（推荐用于 GH 输出端）----
        LingGong__PointList = Solver.LingGong__CaiZhiThreePointsBuilder__PointList
        LingGong__BasePoint = Solver.LingGong__CaiZhiThreePointsBuilder__BasePoint
        LingGong__OffsetPts = Solver.LingGong__CaiZhiThreePointsBuilder__OffsetPts
        LingGong__ExtraPoint = Solver.LingGong__CaiZhiThreePointsBuilder__ExtraPoint
        LingGong__DirUnit = Solver.LingGong__CaiZhiThreePointsBuilder__DirUnit
        LingGong__SpanVectors = Solver.LingGong__CaiZhiThreePointsBuilder__SpanVectors

        LingGong__RectFace = Solver.LingGong__UniqueRectangleFrom3Pts__Face
        LingGong__RectAB = Solver.LingGong__UniqueRectangleFrom3Pts__AB

        LingGong__Support_OffsetPts = Solver.LingGong__CaiZhiSupportLinkLines_ByBasePoint__OffsetPts
        LingGong__Support_LinkLines = Solver.LingGong__CaiZhiSupportLinkLines_ByBasePoint__LinkLines
        LingGong__OffsetPtsLine = Solver.LingGong__OffsetPtsLine

        # ---- 兼容旧输出名（如你暂时未改 GH 输出端）----
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

        # ---- 下面这些是“保留的输出位”（日后增减输出端时解除注释并在 GH 中新增同名输出端）----
        # PlacePlane = Solver.PlacePlane
        # DB_Value = Solver.DB_Value
        DB_All = Solver.DB_All
        # DB_AllDict = Solver.DB_AllDict
        DB_Log = Solver.DB_Log

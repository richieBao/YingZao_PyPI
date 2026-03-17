# -*- coding: utf-8 -*-
"""
ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssembly
------------------------------------------------------------
目标：
- 将“抽象结构_四鋪作裏外並一抄卷頭（ASR_SiPU_INOUT_1ChaoJuantou）”
  的多组件逐步合并为单一 GhPython 组件。

当前实现：
    Step 1：读取数据库
    Step 2：材栔模式（PointsOnLineByCumsum）
    Step 3：华栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    Step 4：泥道栱撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    Step 5：耍头撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    Step 6：壁内慢栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    Step 7：令栱支撑点（OffsetCopyBiDirection + UniqueRectangleFrom3Pts）
    Step 8：连线部分（多组 SpanVectors / OffsetPts / MoveVecList 生成直线）

------------------------------------------------------------
输入：
    DBPath      : str    (Item)
    PlacePlane  : Plane  (Item)
    Refresh     : bool   (Item)
    ScaleFactor : float  (Item)   # 比例因子，默认 1.0；如有输入则所有输出按比例缩放

输出：
    AbsStructRep : list[Geometry]   # 最终组合体
    Log          : str              # 日志信息

内部输出（当前 Step1）：
    Value
    All
    AllDict
    DBLog

内部输出（Step2）：
    PointsOnLine_BaseLine
    PointsOnLine_SumValue
    PointsOnLine_ReversedList
    PointsOnLine_CumList
    PointsOnLine_PointList

内部输出（Step3）：
    HuaGong_PointList
    HuaGong_BasePoint
    HuaGong_OffsetPts
    HuaGong_ExtraPoint
    HuaGong_DirUnit
    HuaGong_SpanVectors

    HuaGong_Face
    HuaGong_AB

内部输出（Step4）：
    NiDaoGong_PointList
    NiDaoGong_BasePoint
    NiDaoGong_OffsetPts
    NiDaoGong_ExtraPoint
    NiDaoGong_DirUnit
    NiDaoGong_SpanVectors

    NiDaoGong_Face
    NiDaoGong_AB

内部输出（Step5）：
    ShuaTou_PointList
    ShuaTou_BasePoint
    ShuaTou_OffsetPts
    ShuaTou_ExtraPoint
    ShuaTou_DirUnit
    ShuaTou_SpanVectors

    ShuaTou_Face
    ShuaTou_AB

内部输出（Step6）：
    BiNeiManGong_PointList
    BiNeiManGong_BasePoint
    BiNeiManGong_OffsetPts
    BiNeiManGong_ExtraPoint
    BiNeiManGong_DirUnit
    BiNeiManGong_SpanVectors

    BiNeiManGong_Face
    BiNeiManGong_AB

内部输出（Step7）：
    LingGong_OffsetTree
    LingGong_MoveVecList
    LingGong_OffsetLog

    LingGong_PointListTree
    LingGong_FaceList
    LingGong_ABList

    LingGong_SpanMovePts
    LingGong_SpanLines

内部输出（Step8）：
    NiDaoGong_LinkLines

    ShuaTou_MovePts
    ShuaTou_SelfLines
    ShuaTou_LinkLines

    BiNeiManGong_MovePts
    BiNeiManGong_SelfLines
    BiNeiManGong_LinkLines

    LingGong_MovePtsTree
    LingGong_MoveLines
    LingGong_ConnectLines
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg

import Grasshopper
from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path

from yingzao.ancientArchi import DBJsonReader
from yingzao.ancientArchi import PointsOnLineByCumsum
from yingzao.ancientArchi import CaiZhiThreePointsBuilder
from yingzao.ancientArchi import UniqueRectangleFrom3Pts
from yingzao.ancientArchi import OffsetCopyBiDirection

__author__  = "richiebao [coding-x.tech]"
__version__ = "2026.02.15"

'''
ghenv.Component.Name = "ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssembly"
ghenv.Component.NickName = "ASR_SiPU_INOUT_1ChaoJuantou"
ghenv.Component.Description = "ComponentAssembly Solver (DB-Driven) - Stepwise Build"
ghenv.Component.Message = "Step8"
ghenv.Component.Category = "YingZaoLab"
ghenv.Component.SubCategory = "抽象结构"
'''

# =========================================================
# 通用工具函数
# =========================================================

def _ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    try:
        return list(x)
    except:
        return [x]


def _is_rhino_atomic(x):
    """
    判断 x 是否应被视为“几何原子项”，不可被 __iter__ 递归展开。
    关键：rg.Point3d/Vector3d/Plane/Line 等在 RhinoCommon 中可能表现为可迭代，
    若递归会被拆成数值（X/Y/Z），这是错误的。
    """
    if x is None:
        return False

    # Rhino.Geometry 的常见“值类型”/“轻量结构体”
    if isinstance(x, (rg.Point3d, rg.Vector3d, rg.Plane, rg.Line, rg.Interval, rg.BoundingBox)):
        return True

    # Rhino.Geometry 的引用类型基类（Brep/Curve/Surface/Mesh/...）
    try:
        if isinstance(x, rg.GeometryBase):
            return True
    except:
        pass

    return False


def _try_unwrap_gh_types(x):
    """
    尝试解包 Grasshopper Kernel Types（GH_Point/GH_Vector/GH_Plane/...）。
    若不可用或无 Value，原样返回。
    """
    if x is None:
        return None

    try:
        # 常见 GH 包装类型都有 Value 属性
        if hasattr(x, "Value"):
            return x.Value
    except:
        pass

    return x


def _flatten_items(x, out_list):
    """
    仅展平“容器”（list/tuple/可迭代集合），不拆 Rhino 几何类型本体。
    这样 pts 展平后仍是 Point3d 列表，而不是 [x,y,z,x,y,z,...] 数值列表。
    """
    if x is None:
        return

    # 字符串视为原子
    if isinstance(x, (str, bytes)):
        out_list.append(x)
        return

    # 先尝试解包 GH 类型
    x_unwrapped = _try_unwrap_gh_types(x)

    # Rhino 几何/值类型：直接加入（不可递归）
    if _is_rhino_atomic(x_unwrapped):
        out_list.append(x_unwrapped)
        return

    # 容器：递归
    if isinstance(x_unwrapped, (list, tuple)):
        for i in x_unwrapped:
            _flatten_items(i, out_list)
        return

    # 其他可迭代：仅在“非 Rhino 原子”情况下递归
    try:
        if hasattr(x_unwrapped, "__iter__"):
            for i in x_unwrapped:
                _flatten_items(i, out_list)
            return
    except:
        pass

    # 默认原子
    out_list.append(x_unwrapped)




def _datatree_branch_to_list(tree, branch_index):
    """从 DataTree 取一个分支为 list。"""
    if tree is None:
        return []
    try:
        br = tree.Branch(branch_index)
        return list(br) if br is not None else []
    except:
        return []



def _get_indexed_point(pt_list, index, default=None):
    """从点列表按 index 取点（clamp）；失败返回 default。"""
    pts = _ensure_list(pt_list)
    if not pts:
        return default
    try:
        i = int(index)
    except:
        i = 0
    if i < 0:
        i = 0
    if i > len(pts) - 1:
        i = len(pts) - 1
    try:
        return pts[i]
    except:
        return default

def _default_place_plane():
    pl = rg.Plane.WorldXY
    pl.Origin = rg.Point3d(100, 100, 0)
    return pl


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


def _try_parse_json_dict(x):
    """尽量把输入转成 dict；失败则返回 None。"""
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        try:
            import json
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except:
            return None
    return None


def _safe_float_list(values):
    """把 values 尽量变成 list[float]，无效项跳过（不做兼容）。"""
    vals = _ensure_list(values)
    out = []
    for v in vals:
        if v is None:
            continue
        try:
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str):
                s = v.strip()
                if s == "":
                    continue
                out.append(float(s))
            else:
                out.append(float(v))
        except:
            continue
    return out


def _safe_float(x, default=0.0):
    """把 x 尽量转成 float，失败返回 default。"""
    if x is None:
        return float(default)
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            s = x.strip()
            if s == "":
                return float(default)
            return float(s)
        return float(x)
    except:
        return float(default)


# =========================================================
# Solver 主类
# =========================================================


# =========================================================
# 输出缩放工具（统一按比例缩放所有几何输出）
# =========================================================

def _try_float(x, default=1.0):
    try:
        if x is None:
            return default
        return float(x)
    except:
        return default


def _scale_any(obj, xform):
    """对常见 Rhino 输出对象进行缩放（尽量不修改原对象）。"""
    if obj is None:
        return None

    # DataTree
    try:
        if isinstance(obj, DataTree):
            dt = DataTree[object]()
            for p in obj.Paths:
                branch = obj.Branch(p)
                for item in branch:
                    dt.Add(_scale_any(item, xform), p)
            return dt
    except:
        pass

    # list / tuple
    if isinstance(obj, list):
        return [_scale_any(o, xform) for o in obj]
    if isinstance(obj, tuple):
        return tuple(_scale_any(o, xform) for o in obj)

    # Rhino GeometryBase
    try:
        if isinstance(obj, rg.GeometryBase):
            dup = obj.Duplicate()
            if dup is not None:
                dup.Transform(xform)
                return dup
            # 兜底：原对象变换（尽量避免，但若 Duplicate 不可用则只能如此）
            obj.Transform(xform)
            return obj
    except:
        pass

    # Rhino 常见值类型：Point3d / Vector3d / Line / Plane 等（都有 Transform）
    try:
        # Point3d/Vector3d/Line 等为值类型，直接复制一份再 Transform
        dup = obj
        dup.Transform(xform)
        return dup
    except:
        return obj


def _scale_all_outputs_in_globals(scale_factor, center_pt):
    sf = _try_float(scale_factor, 1.0)
    if abs(sf - 1.0) <= 1e-9:
        return

    try:
        xform = rg.Transform.Scale(center_pt, sf)
    except:
        return

    # 仅对模块全局变量做一次“类型过滤后缩放”
    _skip = set([
        "Rhino", "rg", "Grasshopper", "DataTree", "GH_Path",
        "DBJsonReader", "PointsOnLineByCumsum", "CaiZhiThreePointsBuilder",
        "UniqueRectangleFrom3Pts", "OffsetCopyBiDirection",
        "ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssemblySolver",
        "ghenv"
    ])

    g = globals()
    for k, v in list(g.items()):
        if k in _skip:
            continue
        if k.startswith("__"):
            continue
        # 不动私有临时变量（_db/_pp/_rf/_sf 等）
        if k.startswith("_"):
            continue
        g[k] = _scale_any(v, xform)
class ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssemblySolver(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, ScaleFactor=1.0, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = bool(Refresh)
        # 比例因子：用于“尺寸参数”缩放（推荐做法：先缩放尺寸再构建几何）
        try:
            self.ScaleFactor = float(ScaleFactor) if ScaleFactor is not None else 1.0
        except:
            self.ScaleFactor = 1.0
        self.ghenv = ghenv

        self.LogLines = []
        self.AbsStructRep = []   # ← 修改：最终组合体变量名
        self.Log = ""

        # Step1 数据
        self.Value1 = None
        self.All1 = None
        self.AllDict1 = {}
        self.DBLog1 = None

        # Step2 数据（材栔模式 / PointsOnLineByCumsum）
        self.ChaoJuantou_PointsOnLine_BaseLine = None
        self.ChaoJuantou_PointsOnLine_SumValue = None
        self.ChaoJuantou_PointsOnLine_ReversedList = None
        self.ChaoJuantou_PointsOnLine_CumList = None
        self.ChaoJuantou_PointsOnLine_PointList = None

        # Step3 数据（华栱支撑点 / CaiZhiThreePointsBuilder）
        self.ChaoJuantou_CaiZhi3Pts_PointList = None
        self.ChaoJuantou_CaiZhi3Pts_BasePoint = None
        self.ChaoJuantou_CaiZhi3Pts_OffsetPts = None
        self.ChaoJuantou_CaiZhi3Pts_ExtraPoint = None
        self.ChaoJuantou_CaiZhi3Pts_DirUnit = None
        self.ChaoJuantou_CaiZhi3Pts_SpanVectors = None

        # Step3 数据（UniqueRectangleFrom3Pts）
        self.ChaoJuantou_UniRect_Face = None
        self.ChaoJuantou_UniRect_AB = None

        # Step4 数据（泥道栱撑点 / CaiZhiThreePointsBuilder）
        self.ChaoJuantou_NiDao_CaiZhi3Pts_PointList = None
        self.ChaoJuantou_NiDao_CaiZhi3Pts_BasePoint = None
        self.ChaoJuantou_NiDao_CaiZhi3Pts_OffsetPts = None
        self.ChaoJuantou_NiDao_CaiZhi3Pts_ExtraPoint = None
        self.ChaoJuantou_NiDao_CaiZhi3Pts_DirUnit = None
        self.ChaoJuantou_NiDao_CaiZhi3Pts_SpanVectors = None

        # Step4 数据（UniqueRectangleFrom3Pts）
        self.ChaoJuantou_NiDao_UniRect_Face = None
        self.ChaoJuantou_NiDao_UniRect_AB = None

        # Step5 数据（耍头撑点 / CaiZhiThreePointsBuilder）
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_PointList = None
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_BasePoint = None
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_OffsetPts = None
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_ExtraPoint = None
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_DirUnit = None
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_SpanVectors = None

        # Step5 数据（UniqueRectangleFrom3Pts）
        self.ChaoJuantou_ShuaTou_UniRect_Face = None
        self.ChaoJuantou_ShuaTou_UniRect_AB = None

        # Step6 数据（壁内慢栱撑点 / CaiZhiThreePointsBuilder）
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_PointList = None
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_BasePoint = None
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_OffsetPts = None
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_ExtraPoint = None
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_DirUnit = None
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_SpanVectors = None

        # Step6 数据（UniqueRectangleFrom3Pts）
        self.ChaoJuantou_BiNeiManGong_UniRect_Face = None
        self.ChaoJuantou_BiNeiManGong_UniRect_AB = None

        # Step7 数据（令栱支撑点 / OffsetCopyBiDirection）
        self.LingGong_OffsetTree = None
        self.LingGong_MoveVecList = None
        self.LingGong_OffsetLog = None

        # Step7 数据（令栱支撑点 / UniqueRectangleFrom3Pts::4）
        self.LingGong_PointListTree = None   # 每分支3点的 Tree
        self.LingGong_FaceList = None        # 两个矩形面（list）
        self.LingGong_ABList = None          # 两个 AB 线（list）

        # Step7 数据（延 HuaGong_SpanVectors 移动得到的2点 + 2条线）
        self.LingGong_SpanMovePts = None     # [pt0, pt1]
        self.LingGong_SpanLines = None       # [line0, line1]

        # Step8 数据（连线部分）
        self.NiDaoGong_LinkLines = None

        self.ShuaTou_MovePts = None
        self.ShuaTou_SelfLines = None
        self.ShuaTou_LinkLines = None

        self.BiNeiManGong_MovePts = None
        self.BiNeiManGong_SelfLines = None
        self.BiNeiManGong_LinkLines = None

        self.LingGong_MovePtsTree = None
        self.LingGong_MoveLines = None
        self.LingGong_ConnectLines = None

        # 解析后的 params（供多 step 复用）
        self.ParamsDict = None

    # -------------------------------------------------
    # Step 1：读取数据库
    # -------------------------------------------------
    def step1_read_db(self):

        self.LogLines.append("Step 1：读取数据库 AbsStructRep.params_json …")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="AbsStructRep",
            key_field="type_code",
            key_value="ASR_SiPU_INOUT_1ChaoJuantou",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value1, self.All1, self.DBLog1 = reader.run()

        d = {}
        try:
            for k, v in _ensure_list(self.All1):
                d[str(k)] = v
        except Exception as e:
            self.LogLines.append("All1 -> AllDict1 转换异常：{}".format(e))

        self.AllDict1 = d

        # 尝试把 Value1 解析为 dict，供后续 step 直接使用
        params = _try_parse_json_dict(self.Value1)
        if params is None and isinstance(self.Value1, (list, tuple)):
            try:
                params = {str(k): v for k, v in self.Value1}
            except:
                params = None
        self.ParamsDict = params

        self.LogLines.append(
            "Step 1 完成：All1 items={} | AllDict1 keys={}".format(
                len(_ensure_list(self.All1)),
                len(self.AllDict1.keys())
            )
        )

    # -------------------------------------------------
    # Step 2：材栔模式（PointsOnLineByCumsum）
    # -------------------------------------------------
    def step2_cai_zhi_points_on_line_by_cumsum(self):

        self.LogLines.append("Step 2：材栔模式 PointsOnLineByCumsum …")

        # ---- Values：来自数据库字段 puZuoVerticalCaiZhiPattern ----
        params = self.ParamsDict

        raw_values = None
        if isinstance(params, dict) and ("puZuoVerticalCaiZhiPattern" in params):
            raw_values = params.get("puZuoVerticalCaiZhiPattern", None)
        elif isinstance(self.AllDict1, dict) and ("puZuoVerticalCaiZhiPattern" in self.AllDict1):
            raw_values = self.AllDict1.get("puZuoVerticalCaiZhiPattern", None)

        values = _safe_float_list(raw_values)
        # 按比例因子缩放“累加距离值”（会影响点位与后续所有构件位置）
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                values = [v * self.ScaleFactor for v in values]
            except:
                pass

        # ---- BasePoint：PlacePlane 原点 ----
        try:
            base_pt = rg.Point3d(self.PlacePlane.Origin)
        except:
            base_pt = rg.Point3d(0, 0, 0)

        # ---- Direction：PlacePlane Z 轴 ----
        try:
            direction = rg.Vector3d(self.PlacePlane.ZAxis)
        except:
            direction = rg.Vector3d(0, 0, 1)

        builder = PointsOnLineByCumsum(values, base_pt, direction, clamp=True)
        bl, s, rev, cum, pts = builder.build()

        # ---- 展平：保证输出端不带嵌套（但不拆 Point3d）----
        _rev = []
        _cum = []
        _pts = []
        _flatten_items(rev, _rev)
        _flatten_items(cum, _cum)
        _flatten_items(pts, _pts)

        self.ChaoJuantou_PointsOnLine_BaseLine = bl
        self.ChaoJuantou_PointsOnLine_SumValue = s
        self.ChaoJuantou_PointsOnLine_ReversedList = _rev
        self.ChaoJuantou_PointsOnLine_CumList = _cum
        self.ChaoJuantou_PointsOnLine_PointList = _pts

        self.LogLines.append(
            "Step 2 完成：Values={} | SumValue={} | Points={}".format(
                len(values),
                s,
                len(_pts)
            )
        )

    # -------------------------------------------------
    # Step 3：华栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    # -------------------------------------------------
    def step3_hua_gong_support_points(self):

        self.LogLines.append("Step 3：华栱支撑点 CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts …")

        # 1) CaiZhiThreePointsBuilder::0
        # Direction = PlacePlane.YAxis
        try:
            cz_direction = rg.Vector3d(self.PlacePlane.YAxis)
        except:
            cz_direction = rg.Vector3d(0, 1, 0)

        # CaiZhiPts = Step2 PointList
        cz_pts = self.ChaoJuantou_PointsOnLine_PointList
        cz_pts_list = _ensure_list(cz_pts)

        # IndexA = 2, IndexB = 1（按你给定）
        cz_index_a = 2
        cz_index_b = 1

        # Span = HuaGong__axis2support（来自数据库参数）
        params = self.ParamsDict
        raw_span = None
        if isinstance(params, dict) and ("HuaGong__axis2support" in params):
            raw_span = params.get("HuaGong__axis2support", None)
        elif isinstance(self.AllDict1, dict) and ("HuaGong__axis2support" in self.AllDict1):
            raw_span = self.AllDict1.get("HuaGong__axis2support", None)
        cz_span = _safe_float(raw_span, default=0.0)
        # 按比例因子缩放该距离参数
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                cz_span = cz_span * self.ScaleFactor
            except:
                pass

        builder = CaiZhiThreePointsBuilder(
            caizhi_pts=cz_pts_list,
            index_a=cz_index_a,
            index_b=cz_index_b,
            direction=cz_direction,
            span=cz_span
        )

        try:
            pl, bp, offpts, ep, diru, spanvecs = builder.build()
        except Exception as e:
            pl, bp, offpts, ep, diru, spanvecs = None, None, None, None, None, None
            self.LogLines.append("Step 3 CaiZhiThreePointsBuilder.build 异常：{}".format(e))

        # 展平输出（不拆 Point3d / Vector3d）
        _pl = []
        _offpts = []
        _spanvecs = []
        _flatten_items(pl, _pl)
        _flatten_items(offpts, _offpts)
        _flatten_items(spanvecs, _spanvecs)

        self.ChaoJuantou_CaiZhi3Pts_PointList = _pl
        self.ChaoJuantou_CaiZhi3Pts_BasePoint = bp
        self.ChaoJuantou_CaiZhi3Pts_OffsetPts = _offpts
        self.ChaoJuantou_CaiZhi3Pts_ExtraPoint = ep
        self.ChaoJuantou_CaiZhi3Pts_DirUnit = diru
        self.ChaoJuantou_CaiZhi3Pts_SpanVectors = _spanvecs

        # 2) UniqueRectangleFrom3Pts::0
        Face = None
        AB = None

        # 严格按组件原代码实现：外层再加保险
        if _pl:
            try:
                builder2 = UniqueRectangleFrom3Pts(_pl)
                Face, AB = builder2.build()
            except Exception as e:
                Face = None
                AB = None
                self.LogLines.append("Step 3 UniqueRectangleFrom3Pts.build 异常：{}".format(e))

        self.ChaoJuantou_UniRect_Face = Face
        self.ChaoJuantou_UniRect_AB = AB

        self.LogLines.append(
            "Step 3 完成：CaiZhi3Pts={} | OffsetPts={} | SpanVectors={} | RectFace={}".format(
                len(_pl),
                len(_offpts),
                len(_spanvecs),
                "OK" if Face is not None else "None"
            )
        )

    # -------------------------------------------------
    # Step 4：泥道栱撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    # -------------------------------------------------
    def step4_ni_dao_gong_support_points(self):

        self.LogLines.append("Step 4：泥道栱撑点 CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts …")

        # 1) CaiZhiThreePointsBuilder::1
        # Direction = PlacePlane.XAxis
        try:
            nd_direction = rg.Vector3d(self.PlacePlane.XAxis)
        except:
            nd_direction = rg.Vector3d(1, 0, 0)

        # CaiZhiPts = Step2 PointList
        nd_pts = self.ChaoJuantou_PointsOnLine_PointList
        nd_pts_list = _ensure_list(nd_pts)

        # IndexA = 2, IndexB = 1（按你给定）
        nd_index_a = 2
        nd_index_b = 1

        # Span = NiDaoGong__axis2support（来自数据库参数）
        params = self.ParamsDict
        raw_span = None
        if isinstance(params, dict) and ("NiDaoGong__axis2support" in params):
            raw_span = params.get("NiDaoGong__axis2support", None)
        elif isinstance(self.AllDict1, dict) and ("NiDaoGong__axis2support" in self.AllDict1):
            raw_span = self.AllDict1.get("NiDaoGong__axis2support", None)
        nd_span = _safe_float(raw_span, default=0.0)
        # 按比例因子缩放该距离参数
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                nd_span = nd_span * self.ScaleFactor
            except:
                pass

        builder = CaiZhiThreePointsBuilder(
            caizhi_pts=nd_pts_list,
            index_a=nd_index_a,
            index_b=nd_index_b,
            direction=nd_direction,
            span=nd_span
        )

        try:
            pl, bp, offpts, ep, diru, spanvecs = builder.build()
        except Exception as e:
            pl, bp, offpts, ep, diru, spanvecs = None, None, None, None, None, None
            self.LogLines.append("Step 4 CaiZhiThreePointsBuilder.build 异常：{}".format(e))

        # 展平输出（不拆 Point3d / Vector3d）
        _pl = []
        _offpts = []
        _spanvecs = []
        _flatten_items(pl, _pl)
        _flatten_items(offpts, _offpts)
        _flatten_items(spanvecs, _spanvecs)

        self.ChaoJuantou_NiDao_CaiZhi3Pts_PointList = _pl
        self.ChaoJuantou_NiDao_CaiZhi3Pts_BasePoint = bp
        self.ChaoJuantou_NiDao_CaiZhi3Pts_OffsetPts = _offpts
        self.ChaoJuantou_NiDao_CaiZhi3Pts_ExtraPoint = ep
        self.ChaoJuantou_NiDao_CaiZhi3Pts_DirUnit = diru
        self.ChaoJuantou_NiDao_CaiZhi3Pts_SpanVectors = _spanvecs

        # 2) UniqueRectangleFrom3Pts::1
        Face = None
        AB = None

        # 严格按组件原代码实现：外层再加保险
        if _pl:
            try:
                builder2 = UniqueRectangleFrom3Pts(_pl)
                Face, AB = builder2.build()
            except Exception as e:
                Face = None
                AB = None
                self.LogLines.append("Step 4 UniqueRectangleFrom3Pts.build 异常：{}".format(e))

        self.ChaoJuantou_NiDao_UniRect_Face = Face
        self.ChaoJuantou_NiDao_UniRect_AB = AB

        self.LogLines.append(
            "Step 4 完成：NiDao3Pts={} | OffsetPts={} | SpanVectors={} | RectFace={}".format(
                len(_pl),
                len(_offpts),
                len(_spanvecs),
                "OK" if Face is not None else "None"
            )
        )

    # -------------------------------------------------
    # Step 5：耍头撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    # -------------------------------------------------
    def step5_shua_tou_support_points(self):

        self.LogLines.append("Step 5：耍头撑点 CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts …")

        # 1) CaiZhiThreePointsBuilder::2
        # Direction = PlacePlane.YAxis
        try:
            st_direction = rg.Vector3d(self.PlacePlane.YAxis)
        except:
            st_direction = rg.Vector3d(0, 1, 0)

        # CaiZhiPts = Step2 PointList
        st_pts = self.ChaoJuantou_PointsOnLine_PointList
        st_pts_list = _ensure_list(st_pts)

        # IndexA = 4, IndexB = 3（按你给定）
        st_index_a = 4
        st_index_b = 3

        # Span = ShuaTou__axis2support（来自数据库参数）
        params = self.ParamsDict
        raw_span = None
        if isinstance(params, dict) and ("ShuaTou__axis2support" in params):
            raw_span = params.get("ShuaTou__axis2support", None)
        elif isinstance(self.AllDict1, dict) and ("ShuaTou__axis2support" in self.AllDict1):
            raw_span = self.AllDict1.get("ShuaTou__axis2support", None)
        st_span = _safe_float(raw_span, default=0.0)
        # 按比例因子缩放该距离参数
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                st_span = st_span * self.ScaleFactor
            except:
                pass

        builder = CaiZhiThreePointsBuilder(
            caizhi_pts=st_pts_list,
            index_a=st_index_a,
            index_b=st_index_b,
            direction=st_direction,
            span=st_span
        )

        try:
            pl, bp, offpts, ep, diru, spanvecs = builder.build()
        except Exception as e:
            pl, bp, offpts, ep, diru, spanvecs = None, None, None, None, None, None
            self.LogLines.append("Step 5 CaiZhiThreePointsBuilder.build 异常：{}".format(e))

        # 展平输出（不拆 Point3d / Vector3d）
        _pl = []
        _offpts = []
        _spanvecs = []
        _flatten_items(pl, _pl)
        _flatten_items(offpts, _offpts)
        _flatten_items(spanvecs, _spanvecs)

        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_PointList = _pl
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_BasePoint = bp
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_OffsetPts = _offpts
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_ExtraPoint = ep
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_DirUnit = diru
        self.ChaoJuantou_ShuaTou_CaiZhi3Pts_SpanVectors = _spanvecs

        # 2) UniqueRectangleFrom3Pts::2
        Face = None
        AB = None

        # 严格按组件原代码实现：外层再加保险
        if _pl:
            try:
                builder2 = UniqueRectangleFrom3Pts(_pl)
                Face, AB = builder2.build()
            except Exception as e:
                Face = None
                AB = None
                self.LogLines.append("Step 5 UniqueRectangleFrom3Pts.build 异常：{}".format(e))

        self.ChaoJuantou_ShuaTou_UniRect_Face = Face
        self.ChaoJuantou_ShuaTou_UniRect_AB = AB

        self.LogLines.append(
            "Step 5 完成：ShuaTou3Pts={} | OffsetPts={} | SpanVectors={} | RectFace={}".format(
                len(_pl),
                len(_offpts),
                len(_spanvecs),
                "OK" if Face is not None else "None"
            )
        )

    # -------------------------------------------------
    # Step 6：壁内慢栱支撑点（CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts）
    # -------------------------------------------------
    def step6_bi_nei_man_gong_support_points(self):

        self.LogLines.append("Step 6：壁内慢栱支撑点 CaiZhiThreePointsBuilder + UniqueRectangleFrom3Pts …")

        # 1) CaiZhiThreePointsBuilder::3
        # Direction = PlacePlane.XAxis
        try:
            bnmg_direction = rg.Vector3d(self.PlacePlane.XAxis)
        except:
            bnmg_direction = rg.Vector3d(1, 0, 0)

        # CaiZhiPts = Step2 PointList
        bnmg_pts = self.ChaoJuantou_PointsOnLine_PointList
        bnmg_pts_list = _ensure_list(bnmg_pts)

        # IndexA = 4, IndexB = 3（按你给定）
        bnmg_index_a = 4
        bnmg_index_b = 3

        # Span = BiNeiManGong__axis2support（来自数据库参数）
        params = self.ParamsDict
        raw_span = None
        if isinstance(params, dict) and ("BiNeiManGong__axis2support" in params):
            raw_span = params.get("BiNeiManGong__axis2support", None)
        elif isinstance(self.AllDict1, dict) and ("BiNeiManGong__axis2support" in self.AllDict1):
            raw_span = self.AllDict1.get("BiNeiManGong__axis2support", None)
        bnmg_span = _safe_float(raw_span, default=0.0)
        # 按比例因子缩放该距离参数
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                bnmg_span = bnmg_span * self.ScaleFactor
            except:
                pass

        builder = CaiZhiThreePointsBuilder(
            caizhi_pts=bnmg_pts_list,
            index_a=bnmg_index_a,
            index_b=bnmg_index_b,
            direction=bnmg_direction,
            span=bnmg_span
        )

        try:
            pl, bp, offpts, ep, diru, spanvecs = builder.build()
        except Exception as e:
            pl, bp, offpts, ep, diru, spanvecs = None, None, None, None, None, None
            self.LogLines.append("Step 6 CaiZhiThreePointsBuilder.build 异常：{}".format(e))

        # 展平输出（不拆 Point3d / Vector3d）
        _pl = []
        _offpts = []
        _spanvecs = []
        _flatten_items(pl, _pl)
        _flatten_items(offpts, _offpts)
        _flatten_items(spanvecs, _spanvecs)

        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_PointList = _pl
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_BasePoint = bp
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_OffsetPts = _offpts
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_ExtraPoint = ep
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_DirUnit = diru
        self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_SpanVectors = _spanvecs

        # 2) UniqueRectangleFrom3Pts::3
        Face = None
        AB = None

        # 严格按组件原代码实现：外层再加保险
        if _pl:
            try:
                builder2 = UniqueRectangleFrom3Pts(_pl)
                Face, AB = builder2.build()
            except Exception as e:
                Face = None
                AB = None
                self.LogLines.append("Step 6 UniqueRectangleFrom3Pts.build 异常：{}".format(e))

        self.ChaoJuantou_BiNeiManGong_UniRect_Face = Face
        self.ChaoJuantou_BiNeiManGong_UniRect_AB = AB

        self.LogLines.append(
            "Step 6 完成：BiNeiManGong3Pts={} | OffsetPts={} | SpanVectors={} | RectFace={}".format(
                len(_pl),
                len(_offpts),
                len(_spanvecs),
                "OK" if Face is not None else "None"
            )
        )


    # -------------------------------------------------
    # Step 7：令栱支撑点（OffsetCopyBiDirection + UniqueRectangleFrom3Pts::4）
    # -------------------------------------------------
    def step7_ling_gong_support_points(self):

        self.LogLines.append("Step 7：令栱支撑点 OffsetCopyBiDirection + UniqueRectangleFrom3Pts …")

        params = self.ParamsDict

        # 1) OffsetCopyBiDirection
        # Geometry = ShuaTou_OffsetPts；Direction = PlacePlane.XAxis；Distance = LingGong__axis2support
        geom_in = self.ChaoJuantou_ShuaTou_CaiZhi3Pts_OffsetPts
        geom_in_list = _ensure_list(geom_in)

        try:
            og_direction = rg.Vector3d(self.PlacePlane.XAxis)
        except:
            og_direction = rg.Vector3d(1, 0, 0)

        raw_dist = None
        if isinstance(params, dict) and ("LingGong__axis2support" in params):
            raw_dist = params.get("LingGong__axis2support", None)
        elif isinstance(self.AllDict1, dict) and ("LingGong__axis2support" in self.AllDict1):
            raw_dist = self.AllDict1.get("LingGong__axis2support", None)
        og_dist = _safe_float(raw_dist, default=0.0)
        # 按比例因子缩放该距离参数
        if getattr(self, 'ScaleFactor', 1.0) != 1.0:
            try:
                og_dist = og_dist * self.ScaleFactor
            except:
                pass

        try:
            og_builder = OffsetCopyBiDirection(og_direction, og_dist)
            offset_tree, move_vec_list, offset_log = og_builder.build_tree(geom_in_list)
        except Exception as e:
            offset_tree, move_vec_list, offset_log = DataTree[object](), [], "OffsetCopyBiDirection 异常：{}".format(e)
            self.LogLines.append("Step 7 OffsetCopyBiDirection 异常：{}".format(e))

        self.LingGong_OffsetTree = offset_tree
        self.LingGong_MoveVecList = move_vec_list
        self.LingGong_OffsetLog = offset_log

        # 2) 取 PointsOnLineByCumsum PointList 索引 3 的点，沿 HuaGong_SpanVectors 方向移动得 2 点
        base_pt = None
        try:
            pts_line = _ensure_list(self.ChaoJuantou_PointsOnLine_PointList)
            if len(pts_line) > 0:
                idx = 3
                if idx < 0:
                    idx = 0
                if idx > len(pts_line) - 1:
                    idx = len(pts_line) - 1
                base_pt = pts_line[idx]
        except:
            base_pt = None

        span_vecs = _ensure_list(self.ChaoJuantou_CaiZhi3Pts_SpanVectors)  # HuaGong SpanVectors
        moved_pts = []
        if base_pt is not None and len(span_vecs) >= 2:
            try:
                moved_pts = [rg.Point3d(base_pt + span_vecs[0]), rg.Point3d(base_pt + span_vecs[1])]
            except:
                moved_pts = []
        self.LingGong_SpanMovePts = moved_pts

        # 2b) 将 moved_pts 合并到 offset_tree 的两个分支下，使每分支 3 点 -> UniqueRectangleFrom3Pts::4
        point_tree = DataTree[object]()
        face_list = []
        ab_list = []

        # 复制 offset_tree 到 point_tree
        try:
            for i in range(offset_tree.BranchCount):
                path = offset_tree.Paths[i]
                br = list(offset_tree.Branch(i))
                for it in br:
                    point_tree.Add(it, path)
        except:
            pass

        # 添加 moved_pts 到对应分支末尾（按次序）
        try:
            for i, mp in enumerate(moved_pts):
                if mp is None:
                    continue
                point_tree.Add(mp, GH_Path(i))
        except:
            pass

        self.LingGong_PointListTree = point_tree

        # 对每个分支计算矩形
        try:
            for i in range(point_tree.BranchCount):
                br_pts = list(point_tree.Branch(i))
                _br = []
                _flatten_items(br_pts, _br)
                Face = None
                AB = None
                if _br:
                    try:
                        rect_builder = UniqueRectangleFrom3Pts(_br)
                        Face, AB = rect_builder.build()
                    except:
                        Face = None
                        AB = None
                face_list.append(Face)
                ab_list.append(AB)
        except:
            pass

        self.LingGong_FaceList = face_list
        self.LingGong_ABList = ab_list

        # 3) moved_pts 分别与 HuaGong_OffsetPts 对应，构建 2 条线
        span_lines = []
        try:
            hg_off = _ensure_list(self.ChaoJuantou_CaiZhi3Pts_OffsetPts)  # HuaGong OffsetPts
            for i in range(min(len(hg_off), len(moved_pts))):
                if hg_off[i] is None or moved_pts[i] is None:
                    continue
                span_lines.append(rg.Line(hg_off[i], moved_pts[i]))
        except:
            span_lines = []

        _lines = []
        _flatten_items(span_lines, _lines)
        self.LingGong_SpanLines = _lines

        self.LogLines.append(
            "Step 7 完成：OffsetTreeBranches={} | SpanMovePts={} | RectFaces={}".format(
                getattr(offset_tree, "BranchCount", 0),
                len(moved_pts),
                len(face_list)
            )
        )


    # -------------------------------------------------
    # Step 8：连线部分
    # -------------------------------------------------
    def step8_link_lines(self):

        self.LogLines.append("Step 8：连线部分 …")

        # -----------------------------
        # 1) PointList[3] 沿 NiDaoGong_SpanVectors 移动 -> 与 NiDaoGong_OffsetPts 对应连线（2条）
        # -----------------------------
        p3 = _get_indexed_point(self.ChaoJuantou_PointsOnLine_PointList, 3, default=None)
        nd_span_vecs = _ensure_list(self.ChaoJuantou_NiDao_CaiZhi3Pts_SpanVectors)
        nd_offpts = _ensure_list(self.ChaoJuantou_NiDao_CaiZhi3Pts_OffsetPts)

        nd_lines = []
        nd_moved = []
        if p3 is not None and len(nd_span_vecs) >= 2:
            try:
                nd_moved = [rg.Point3d(p3 + nd_span_vecs[0]), rg.Point3d(p3 + nd_span_vecs[1])]
            except:
                nd_moved = []
        try:
            for i in range(min(len(nd_moved), len(nd_offpts))):
                if nd_moved[i] is None or nd_offpts[i] is None:
                    continue
                nd_lines.append(rg.Line(nd_offpts[i], nd_moved[i]))
        except:
            nd_lines = []

        _nd_lines = []
        _flatten_items(nd_lines, _nd_lines)
        self.NiDaoGong_LinkLines = _nd_lines

        # -----------------------------
        # 2) PointList[5] 沿 ShuaTou_SpanVectors 移动 -> moved 两点先连线1条，再与 ShuaTou_OffsetPts 对应连线2条
        # -----------------------------
        p5 = _get_indexed_point(self.ChaoJuantou_PointsOnLine_PointList, 5, default=None)
        st_span_vecs = _ensure_list(self.ChaoJuantou_ShuaTou_CaiZhi3Pts_SpanVectors)
        st_offpts = _ensure_list(self.ChaoJuantou_ShuaTou_CaiZhi3Pts_OffsetPts)

        st_moved = []
        st_self_lines = []
        st_connect_lines = []
        if p5 is not None and len(st_span_vecs) >= 2:
            try:
                st_moved = [rg.Point3d(p5 + st_span_vecs[0]), rg.Point3d(p5 + st_span_vecs[1])]
            except:
                st_moved = []
        if len(st_moved) >= 2:
            try:
                st_self_lines.append(rg.Line(st_moved[0], st_moved[1]))
            except:
                pass
        try:
            for i in range(min(len(st_moved), len(st_offpts))):
                if st_moved[i] is None or st_offpts[i] is None:
                    continue
                st_connect_lines.append(rg.Line(st_offpts[i], st_moved[i]))
        except:
            pass

        self.ShuaTou_MovePts = st_moved
        _st_self = []
        _flatten_items(st_self_lines, _st_self)
        self.ShuaTou_SelfLines = _st_self
        _st_conn = []
        _flatten_items(st_connect_lines, _st_conn)
        self.ShuaTou_LinkLines = _st_conn

        # -----------------------------
        # 3) PointList[5] 沿 BiNeiManGong_SpanVectors 移动 -> moved 两点先连线1条，再与 BiNeiManGong_OffsetPts 对应连线2条
        # -----------------------------
        bn_span_vecs = _ensure_list(self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_SpanVectors)
        bn_offpts = _ensure_list(self.ChaoJuantou_BiNeiManGong_CaiZhi3Pts_OffsetPts)

        bn_moved = []
        bn_self_lines = []
        bn_connect_lines = []
        if p5 is not None and len(bn_span_vecs) >= 2:
            try:
                bn_moved = [rg.Point3d(p5 + bn_span_vecs[0]), rg.Point3d(p5 + bn_span_vecs[1])]
            except:
                bn_moved = []
        if len(bn_moved) >= 2:
            try:
                bn_self_lines.append(rg.Line(bn_moved[0], bn_moved[1]))
            except:
                pass
        try:
            for i in range(min(len(bn_moved), len(bn_offpts))):
                if bn_moved[i] is None or bn_offpts[i] is None:
                    continue
                bn_connect_lines.append(rg.Line(bn_offpts[i], bn_moved[i]))
        except:
            pass

        self.BiNeiManGong_MovePts = bn_moved
        _bn_self = []
        _flatten_items(bn_self_lines, _bn_self)
        self.BiNeiManGong_SelfLines = _bn_self
        _bn_conn = []
        _flatten_items(bn_connect_lines, _bn_conn)
        self.BiNeiManGong_LinkLines = _bn_conn

        # -----------------------------
        # 4) PointList[5] 沿 ShuaTou_SpanVectors 移动后，再分别沿 LingGong_MoveVecList 移动
        #    - 每个 base moved 点 -> moved_set（沿 MoveVecList 的所有方向）
        #    - moved_set 作为一个 Tree 分支；分支内连线 1 条（共2条）
        #    - 与 LingGong_OffsetTree 对应两两连线（共4条）
        # -----------------------------
        mv_vecs = _ensure_list(self.LingGong_MoveVecList)
        offset_tree = self.LingGong_OffsetTree

        move_pts_tree = DataTree[object]()
        move_lines = []
        connect_lines = []

        for bi, base_pt in enumerate(_ensure_list(st_moved)):
            path = GH_Path(bi)
            moved_set = []
            for v in mv_vecs:
                if base_pt is None or v is None:
                    continue
                try:
                    moved_set.append(rg.Point3d(base_pt + v))
                except:
                    continue

            for mp in moved_set:
                move_pts_tree.Add(mp, path)

            if len(moved_set) >= 2:
                try:
                    move_lines.append(rg.Line(moved_set[0], moved_set[1]))
                except:
                    pass

            try:
                off_branch = _datatree_branch_to_list(offset_tree, bi)
                if len(off_branch) >= 2 and len(moved_set) >= 2:
                    connect_lines.append(rg.Line(off_branch[0], moved_set[0]))
                    connect_lines.append(rg.Line(off_branch[1], moved_set[1]))
            except:
                pass

        self.LingGong_MovePtsTree = move_pts_tree

        _ml = []
        _flatten_items(move_lines, _ml)
        self.LingGong_MoveLines = _ml

        _cl = []
        _flatten_items(connect_lines, _cl)
        self.LingGong_ConnectLines = _cl

        self.LogLines.append(
            "Step 8 完成：NiDaoLines={} | ShuaTouLines={} | BiNeiManGongLines={} | LingMoveLines={} | LingConnectLines={}".format(
                len(_nd_lines),
                len(_st_conn),
                len(_bn_conn),
                len(_ml),
                len(_cl)
            )
        )

    # -------------------------------------------------
    # run
    # -------------------------------------------------
    def run(self):

        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self.step1_read_db()

        self.step2_cai_zhi_points_on_line_by_cumsum()

        self.step3_hua_gong_support_points()

        self.step4_ni_dao_gong_support_points()

        self.step5_shua_tou_support_points()

        self.step6_bi_nei_man_gong_support_points()

        self.step7_ling_gong_support_points()

        self.step8_link_lines()

        # 当前仅 Step1~8，不生成几何
        self.AbsStructRep = []

        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GH Python 组件 · 输出绑定区
# =========================================================

if __name__ == "__main__":

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

    try:
        _sf = float(_sf)
    except:
        _sf = 1.0

    solver = ASR_SiPU_INOUT_1ChaoJuantou_ComponentAssemblySolver(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        ScaleFactor=_sf,
        ghenv=ghenv
    )
    solver.run()


    # -------- 最终组合体 --------
    AbsStructRep = getattr(solver, "AbsStructRep", None)
    Log = getattr(solver, "Log", None)

    # -------- Step1 内部数据 --------
    Value = getattr(solver, "Value1", None)
    All = getattr(solver, "All1", None)
    AllDict = getattr(solver, "AllDict1", None)
    DBLog = getattr(solver, "DBLog1", None)

    # -------- Step2 内部数据（材栔模式） --------
    PointsOnLine_BaseLine = getattr(solver, "ChaoJuantou_PointsOnLine_BaseLine", None)
    PointsOnLine_SumValue = getattr(solver, "ChaoJuantou_PointsOnLine_SumValue", None)
    PointsOnLine_ReversedList = getattr(solver, "ChaoJuantou_PointsOnLine_ReversedList", None)
    PointsOnLine_CumList = getattr(solver, "ChaoJuantou_PointsOnLine_CumList", None)
    PointsOnLine_PointList = getattr(solver, "ChaoJuantou_PointsOnLine_PointList", None)

    # -------- Step3 内部数据（华栱支撑点）--------
    HuaGong_PointList = getattr(solver, "ChaoJuantou_CaiZhi3Pts_PointList", None)
    HuaGong_BasePoint = getattr(solver, "ChaoJuantou_CaiZhi3Pts_BasePoint", None)
    HuaGong_OffsetPts = getattr(solver, "ChaoJuantou_CaiZhi3Pts_OffsetPts", None)
    HuaGong_ExtraPoint = getattr(solver, "ChaoJuantou_CaiZhi3Pts_ExtraPoint", None)
    HuaGong_DirUnit = getattr(solver, "ChaoJuantou_CaiZhi3Pts_DirUnit", None)
    HuaGong_SpanVectors = getattr(solver, "ChaoJuantou_CaiZhi3Pts_SpanVectors", None)
    HuaGong_Face = getattr(solver, "ChaoJuantou_UniRect_Face", None)
    HuaGong_AB = getattr(solver, "ChaoJuantou_UniRect_AB", None)

    # -------- Step4 内部数据（泥道栱撑点）--------
    NiDaoGong_PointList = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_PointList", None)
    NiDaoGong_BasePoint = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_BasePoint", None)
    NiDaoGong_OffsetPts = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_OffsetPts", None)
    NiDaoGong_ExtraPoint = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_ExtraPoint", None)
    NiDaoGong_DirUnit = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_DirUnit", None)
    NiDaoGong_SpanVectors = getattr(solver, "ChaoJuantou_NiDao_CaiZhi3Pts_SpanVectors", None)
    NiDaoGong_Face = getattr(solver, "ChaoJuantou_NiDao_UniRect_Face", None)
    NiDaoGong_AB = getattr(solver, "ChaoJuantou_NiDao_UniRect_AB", None)

    # -------- Step5 内部数据（耍头撑点）--------
    ShuaTou_PointList = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_PointList", None)
    ShuaTou_BasePoint = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_BasePoint", None)
    ShuaTou_OffsetPts = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_OffsetPts", None)
    ShuaTou_ExtraPoint = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_ExtraPoint", None)
    ShuaTou_DirUnit = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_DirUnit", None)
    ShuaTou_SpanVectors = getattr(solver, "ChaoJuantou_ShuaTou_CaiZhi3Pts_SpanVectors", None)
    ShuaTou_Face = getattr(solver, "ChaoJuantou_ShuaTou_UniRect_Face", None)
    ShuaTou_AB = getattr(solver, "ChaoJuantou_ShuaTou_UniRect_AB", None)

    # -------- Step6 内部数据（壁内慢栱撑点）--------
    BiNeiManGong_PointList = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_PointList", None)
    BiNeiManGong_BasePoint = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_BasePoint", None)
    BiNeiManGong_OffsetPts = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_OffsetPts", None)
    BiNeiManGong_ExtraPoint = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_ExtraPoint", None)
    BiNeiManGong_DirUnit = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_DirUnit", None)
    BiNeiManGong_SpanVectors = getattr(solver, "ChaoJuantou_BiNeiManGong_CaiZhi3Pts_SpanVectors", None)
    BiNeiManGong_Face = getattr(solver, "ChaoJuantou_BiNeiManGong_UniRect_Face", None)
    BiNeiManGong_AB = getattr(solver, "ChaoJuantou_BiNeiManGong_UniRect_AB", None)

    # -------- Step7 内部数据（令栱支撑点）--------
    LingGong_OffsetTree = getattr(solver, "LingGong_OffsetTree", None)
    LingGong_MoveVecList = getattr(solver, "LingGong_MoveVecList", None)
    LingGong_OffsetLog = getattr(solver, "LingGong_OffsetLog", None)

    LingGong_PointListTree = getattr(solver, "LingGong_PointListTree", None)
    LingGong_FaceList = getattr(solver, "LingGong_FaceList", None)
    LingGong_ABList = getattr(solver, "LingGong_ABList", None)

    LingGong_SpanMovePts = getattr(solver, "LingGong_SpanMovePts", None)
    LingGong_SpanLines = getattr(solver, "LingGong_SpanLines", None)

    # -------- Step8 内部数据（连线部分）--------
    NiDaoGong_LinkLines = getattr(solver, "NiDaoGong_LinkLines", None)

    ShuaTou_MovePts = getattr(solver, "ShuaTou_MovePts", None)
    ShuaTou_SelfLines = getattr(solver, "ShuaTou_SelfLines", None)
    ShuaTou_LinkLines = getattr(solver, "ShuaTou_LinkLines", None)

    BiNeiManGong_MovePts = getattr(solver, "BiNeiManGong_MovePts", None)
    BiNeiManGong_SelfLines = getattr(solver, "BiNeiManGong_SelfLines", None)
    BiNeiManGong_LinkLines = getattr(solver, "BiNeiManGong_LinkLines", None)

    LingGong_MovePtsTree = getattr(solver, "LingGong_MovePtsTree", None)
    LingGong_MoveLines = getattr(solver, "LingGong_MoveLines", None)
    LingGong_ConnectLines = getattr(solver, "LingGong_ConnectLines", None)
    # =========================================================
    # 注意：ScaleFactor 采用“先缩放尺寸参数再构建几何”的策略。
    # 因此此处不再对最终输出几何做 Transform.Scale（避免点位错乱/二次变换）。
    # =========================================================



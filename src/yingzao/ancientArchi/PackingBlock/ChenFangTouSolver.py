# -*- coding: utf-8 -*-
"""
襯方頭 ChenFangTouSolver · 当前步骤（Step 1：DBJsonReader + Step 2：FT_timber_block_uniform + Step 3：卡口 RuFangKaKouBuilder + GeoAligner::1 + Step 4：BlockCutter + PlaneFromLists::1/2 + GeoAligner::2 + FT_CutTimberByTools_V2）
-----------------------------------------------------------
将 DBJsonReader（ExportAll=True）与原始木料构建（FT_timber_block_uniform）整合进单一 GhPython 组件，并增加：

Step 3：卡口（RuFangKaKouBuilder）+ 对位（GeoAligner::1）
Step 4：BlockCutter（FT_BlockCutter）+ PlaneFromLists::1/2 + GeoAligner::2 + FT_CutTimberByTools_V2（切割）

输入（GH 输入端）：
    DBPath     : str        - SQLite 数据库路径
    base_point : Point3d    - 木料定位点（用于 Step 2 放置木坯；None → 原点）
    Refresh    : bool       - 刷新开关（True 强制重读数据库并清缓存）

输出（GH 输出端）：
    CutTimbers  : list[Breps]
    FailTimbers : list[Breps]
    Log         : list[str]
"""

import scriptcontext as sc
import Rhino.Geometry as rg
from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    RuFangKaKouBuilder,
    FT_GeoAligner,
    FTPlaneFromLists,
    FT_CutTimberByTools_V2
)


# ======================================================================
# 通用：缓存键（按组件实例）
# ======================================================================
def _cache_key(ghenv, suffix):
    try:
        guid = str(ghenv.Component.InstanceGuid)
    except:
        guid = "unknown"
    return "ChenFangTouSolver::{0}::{1}".format(guid, suffix)


# ======================================================================
# 通用：GH 参考平面（XY / XZ / YZ）
# 说明（按你的规范）：
#   XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
#   XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  (Z = X × Y)
#   YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)   (Z = X × Y)
# ======================================================================
def make_gh_ref_plane(mode="WorldXZ", origin=None):
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)

    m = str(mode) if mode is not None else "WorldXZ"
    m = m.strip().lower()

    if m in ("worldxy", "xy", "xyplane", "world_xy"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("worldyz", "yz", "yzplane", "world_yz"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


# ======================================================================
# 通用：广播工具（GeoAligner / BlockCutter 等多值参数统一用）
# ======================================================================
def _to_list(x):
    """若为 list/tuple 则转为 list，否则包装成 [x]。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]

def _param_length(val):
    """返回参数长度：list/tuple → len；None → 0；其他 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1

def _broadcast_param(val, n, name="param"):
    """
    广播/截断参数到长度 n：
    - val 为 list/tuple：
        * len == 0 : [None]*n
        * 0 < len < n : 末值补齐
        * len >= n : 截断前 n
    - val 为标量： [val]*n
    """
    if n <= 0:
        return []

    if isinstance(val, (list, tuple)):
        arr = list(val)
        if len(arr) == 0:
            return [None] * n
        if len(arr) < n:
            arr = arr + [arr[-1]] * (n - len(arr))
        return arr[:n]

    return [val] * n


# ======================================================================
# Solver 主类（Step 1 + Step 2 + Step 3 + Step 4）
# ======================================================================
class ChenFangTouSolver(object):

    def __init__(self, DBPath=None, base_point=None, Refresh=False, ghenv=None):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = bool(Refresh)
        self.ghenv = ghenv

        # --- Step 1 outputs ---
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # --- Step 2 outputs（与 FT_timber_block_uniform 保持一致命名）---
        self.TimberBrep      = None
        self.FaceList        = []
        self.PointList       = []
        self.EdgeList        = []
        self.CenterPoint     = None
        self.CenterAxisLines = []
        self.EdgeMidPoints   = []
        self.FacePlaneList   = []
        self.Corner0Planes   = []
        self.LocalAxesPlane  = None
        self.AxisX           = None
        self.AxisY           = None
        self.AxisZ           = None
        self.FaceDirTags     = []
        self.EdgeDirTags     = []
        self.Corner0EdgeDirs = []
        self.TimberLog       = []

        # --- Step 3 outputs（卡口 + 对位）---
        self.KaKou_OuterTool      = None
        self.KaKou_InnerTool      = None
        self.KaKou_OuterSection   = None
        self.KaKou_InnerSection   = None
        self.KaKou_RefPlanes      = []
        self.KaKou_EdgeMidPoints  = []
        self.KaKou_EdgeNames      = []
        self.KaKou_KeyPoints      = []
        self.KaKou_KeyPointNames  = []
        self.KaKou_EdgeCurves     = []
        self.KaKou_RefPlaneNames  = []
        self.KaKou_Log            = []

        self.GeoAligner1_SourceOut = None
        self.GeoAligner1_TargetOut = None
        self.GeoAligner1_MovedGeo  = None

        # --- Step 4 outputs（BlockCutter + PlaneFromLists + GeoAligner::2 + Cut）---
        self.BlockCutter_TimberBrep      = None
        self.BlockCutter_FaceList        = []
        self.BlockCutter_PointList       = []
        self.BlockCutter_EdgeList        = []
        self.BlockCutter_CenterPoint     = None
        self.BlockCutter_CenterAxisLines = []
        self.BlockCutter_EdgeMidPoints   = []
        self.BlockCutter_FacePlaneList   = []
        self.BlockCutter_Corner0Planes   = []
        self.BlockCutter_LocalAxesPlane  = None
        self.BlockCutter_AxisX           = None
        self.BlockCutter_AxisY           = None
        self.BlockCutter_AxisZ           = None
        self.BlockCutter_FaceDirTags     = []
        self.BlockCutter_EdgeDirTags     = []
        self.BlockCutter_Corner0EdgeDirs = []
        self.BlockCutter_Log             = []

        # PlaneFromLists::1（主木坯）
        self.PFL1_BasePlane   = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlane = None
        self.PFL1_Log         = []

        # PlaneFromLists::2（BlockCutter）
        self.PFL2_BasePlane   = None
        self.PFL2_OriginPoint = None
        self.PFL2_ResultPlane = None
        self.PFL2_Log         = []

        # GeoAligner::2
        self.GeoAligner2_SourceOut = None
        self.GeoAligner2_TargetOut = None
        self.GeoAligner2_MovedGeo  = None

        # Cut
        self.Cut_Log = []

        # --- Final outputs ---
        self.CutTimbers = []
        self.FailTimbers = []

        # --- Log ---
        self.Log = []

    # ------------------------------------------------------------
    # 小工具：从 AllDict 中取值（兼容长度为1的list）
    # ------------------------------------------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict.get(key, default)
        if isinstance(v, (list, tuple)):
            if len(v) == 0:
                return default
            if len(v) == 1:
                return v[0]
        return v

    def _as_int(self, v, default=0):
        try:
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return self._as_int(v[0], default)
            return int(v)
        except:
            return default

    def _as_float(self, v, default=0.0):
        try:
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return self._as_float(v[0], default)
            return float(v)
        except:
            return default

    def _as_bool01(self, v, default=0):
        try:
            if v is None:
                return int(default)
            if isinstance(v, (list, tuple)):
                if len(v) == 0:
                    return int(default)
                return self._as_bool01(v[0], default)
            if isinstance(v, bool):
                return 1 if v else 0
            return 1 if int(v) != 0 else 0
        except:
            return int(default)

    def _safe_index(self, seq, idx, name="seq"):
        if seq is None:
            self.Log.append("[IDX][WARN] {} 为 None".format(name))
            return None
        try:
            n = len(seq)
        except:
            self.Log.append("[IDX][WARN] {} 不可 len()".format(name))
            return None
        if n == 0:
            self.Log.append("[IDX][WARN] {} 为空列表".format(name))
            return None
        if idx < 0 or idx >= n:
            self.Log.append("[IDX][WARN] {} 索引越界：idx={} / len={}".format(name, idx, n))
            return None
        return seq[idx]

    # ------------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------------
    def step1_read_db(self):
        self.Log.append("[DB] Step 1: DBJsonReader 读取开始")

        if self.DBPath is None or str(self.DBPath).strip() == "":
            self.Log.append("[DB][ERROR] DBPath 为空，无法读取数据库。")
            self.Value, self.All, self.AllDict = None, None, {}
            return

        ck_value = _cache_key(self.ghenv, "Value")
        ck_all   = _cache_key(self.ghenv, "All")
        ck_dict  = _cache_key(self.ghenv, "AllDict")
        ck_log   = _cache_key(self.ghenv, "DBLog")

        if self.Refresh:
            self.Log.append("[DB] Refresh=True：清空缓存并强制重读")
            for k in (ck_value, ck_all, ck_dict, ck_log):
                if k in sc.sticky:
                    del sc.sticky[k]

        if (not self.Refresh) and (ck_all in sc.sticky) and (ck_dict in sc.sticky):
            self.Value   = sc.sticky.get(ck_value, None)
            self.All     = sc.sticky.get(ck_all, None)
            self.AllDict = sc.sticky.get(ck_dict, {}) or {}
            cached_db_log = sc.sticky.get(ck_log, []) or []
            self.DBLog = list(cached_db_log)

            self.Log.append("[DB] 命中缓存：All={}项 / AllDict={}项".format(
                0 if self.All is None else len(self.All),
                len(self.AllDict)
            ))
            for l in cached_db_log:
                self.Log.append("[DB] " + str(l))
            return

        Table     = "DG_Dou"
        KeyField  = "type_code"
        KeyValue  = "ChenFangTou"   # ⚠️ 襯方頭 type_code（若你库里实际不同，请改这里）
        Field     = "params_json"
        JsonPath  = None
        ExportAll = True

        try:
            reader = DBJsonReader(
                db_path    = self.DBPath,
                table      = Table,
                key_field  = KeyField,
                key_value  = KeyValue,
                field      = Field,
                json_path  = JsonPath,
                export_all = ExportAll,
                ghenv      = self.ghenv
            )
            Value, All, DBLog = reader.run()
            self.Value = Value
            self.All = All
            self.DBLog = list(DBLog or [])
            for l in (DBLog or []):
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Log.append("[DB][ERROR] DBJsonReader 运行失败: {}".format(e))
            self.Value, self.All, self.AllDict = None, None, {}
            self.DBLog = []
            return

        if self.All is None or len(self.All) == 0:
            self.Log.append("[DB][WARN] ExportAll=True 但 All 为空：未找到记录或 params_json 无有效字段")
            self.AllDict = {}
        else:
            self.Log.append("[DB] ExportAll=True：读取 {} 项参数".format(len(self.All)))
            d = {}
            dup = 0
            for item in self.All:
                try:
                    k, v = item
                except:
                    self.Log.append("[DB][WARN] 非法 All 条目（无法解包为 (k,v) ）: {}".format(item))
                    continue
                if k in d:
                    dup += 1
                    self.Log.append("[DB][WARN] 参数重复键: {}".format(k))
                d[k] = v
            self.AllDict = d
            self.Log.append("[DB] AllDict 构建完成，共 {} 项（重复键 {} 个）".format(len(self.AllDict), dup))

        sc.sticky[ck_value] = self.Value
        sc.sticky[ck_all]   = self.All
        sc.sticky[ck_dict]  = self.AllDict
        sc.sticky[ck_log]   = [l for l in (self.DBLog or [])]

    # ------------------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ------------------------------------------------------------
    def step2_timber(self):
        self.Log.append("[TIMBER] Step 2: FT_timber_block_uniform 开始")

        length_raw = self.all_get("FT_timber_block_uniform__length_fen", 32.0)
        width_raw  = self.all_get("FT_timber_block_uniform__width_fen",  32.0)
        height_raw = self.all_get("FT_timber_block_uniform__height_fen", 20.0)

        length_fen = self._as_float(length_raw, 32.0)
        width_fen  = self._as_float(width_raw,  32.0)
        height_fen = self._as_float(height_raw, 20.0)

        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location
        elif isinstance(bp, rg.Point3d):
            pass
        else:
            try:
                bp = rg.Point3d(bp.X, bp.Y, bp.Z)
            except:
                bp = rg.Point3d(0.0, 0.0, 0.0)
                self.Log.append("[TIMBER][WARN] base_point 类型无法识别，退回原点。")

        reference_plane = make_gh_ref_plane("WorldXZ", origin=rg.Point3d(0.0, 0.0, 0.0))

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                length_fen,
                width_fen,
                height_fen,
                bp,
                reference_plane,
            )

            self.TimberBrep      = timber_brep
            self.FaceList        = faces or []
            self.PointList       = points or []
            self.EdgeList        = edges or []
            self.CenterPoint     = center_pt
            self.CenterAxisLines = center_axes or []
            self.EdgeMidPoints   = edge_midpts or []
            self.FacePlaneList   = face_planes or []
            self.Corner0Planes   = corner0_planes or []
            self.LocalAxesPlane  = local_axes_plane
            self.AxisX           = axis_x
            self.AxisY           = axis_y
            self.AxisZ           = axis_z
            self.FaceDirTags     = face_tags or []
            self.EdgeDirTags     = edge_tags or []
            self.Corner0EdgeDirs = corner0_dirs or []
            self.TimberLog       = log_lines or []

            self.Log.append("[TIMBER] FT_timber_block_uniform 构建完成")
            for l in (log_lines or []):
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            self.TimberBrep      = None
            self.FaceList        = []
            self.PointList       = []
            self.EdgeList        = []
            self.CenterPoint     = None
            self.CenterAxisLines = []
            self.EdgeMidPoints   = []
            self.FacePlaneList   = []
            self.Corner0Planes   = []
            self.LocalAxesPlane  = None
            self.AxisX           = None
            self.AxisY           = None
            self.AxisZ           = None
            self.FaceDirTags     = []
            self.EdgeDirTags     = []
            self.Corner0EdgeDirs = []
            self.TimberLog       = ["错误: {}".format(e)]
            self.Log.append("[TIMBER][ERROR] build_timber_block_uniform 出错: {}".format(e))

    # ------------------------------------------------------------
    # Step 3.1：卡口 RuFangKaKouBuilder
    # ------------------------------------------------------------
    def step3_kakou_builder(self):
        self.Log.append("[KAKOU] Step 3.1: RuFangKaKouBuilder 开始")

        BasePoint = rg.Point3d(0, 0, 0)
        RefPlane = None

        WidthFen      = self.all_get("RuFangKaKouBuilder__WidthFen", 10.0)
        HeightFen     = self.all_get("RuFangKaKouBuilder__HeightFen", 15.0)
        EdgeOffsetFen = self.all_get("RuFangKaKouBuilder__EdgeOffsetFen", 1.0)
        TopInsetFen   = self.all_get("RuFangKaKouBuilder__TopInsetFen", 5.0)
        ExtrudeFen    = self.all_get("RuFangKaKouBuilder__ExtrudeFen", 10.0)

        if WidthFen is None or WidthFen == 0: WidthFen = 10.0
        if HeightFen is None or HeightFen == 0: HeightFen = 15.0
        if EdgeOffsetFen is None or EdgeOffsetFen == 0: EdgeOffsetFen = 1.0
        if TopInsetFen is None or TopInsetFen == 0: TopInsetFen = 5.0
        if ExtrudeFen is None or ExtrudeFen == 0: ExtrudeFen = 10.0

        try:
            builder = RuFangKaKouBuilder(
                base_point=BasePoint,
                ref_plane=RefPlane,
                width_fen=WidthFen,
                height_fen=HeightFen,
                edge_offset_fen=EdgeOffsetFen,
                top_inset_fen=TopInsetFen,
                extrude_fen=ExtrudeFen
            )

            result = builder.build()

            self.KaKou_OuterTool      = result.get("OuterTool", None)
            self.KaKou_InnerTool      = result.get("InnerTool", None)
            self.KaKou_OuterSection   = result.get("OuterSection", None)
            self.KaKou_InnerSection   = result.get("InnerSection", None)
            self.KaKou_RefPlanes      = result.get("RefPlanes", []) or []
            self.KaKou_EdgeMidPoints  = result.get("EdgeMidPoints", []) or []
            self.KaKou_EdgeNames      = result.get("EdgeNames", []) or []
            self.KaKou_KeyPoints      = result.get("KeyPoints", []) or []
            self.KaKou_KeyPointNames  = result.get("KeyPointNames", []) or []
            self.KaKou_EdgeCurves     = result.get("EdgeCurves", []) or []
            self.KaKou_RefPlaneNames  = result.get("RefPlaneNames", []) or []
            self.KaKou_Log            = result.get("Log", []) or []

            self.Log.append("[KAKOU] RuFangKaKouBuilder 构建完成")
            for l in (self.KaKou_Log or []):
                self.Log.append("[KAKOU] " + str(l))

        except Exception as e:
            self.KaKou_OuterTool      = None
            self.KaKou_InnerTool      = None
            self.KaKou_OuterSection   = None
            self.KaKou_InnerSection   = None
            self.KaKou_RefPlanes      = []
            self.KaKou_EdgeMidPoints  = []
            self.KaKou_EdgeNames      = []
            self.KaKou_KeyPoints      = []
            self.KaKou_KeyPointNames  = []
            self.KaKou_EdgeCurves     = []
            self.KaKou_RefPlaneNames  = []
            self.KaKou_Log            = ["错误: {}".format(e)]
            self.Log.append("[KAKOU][ERROR] RuFangKaKouBuilder 出错: {}".format(e))

    # ------------------------------------------------------------
    # Step 3.2：GeoAligner::1（OuterTool 对位到木坯面）
    # ------------------------------------------------------------
    def step3_geoaligner_1(self):
        self.Log.append("[ALIGN] Step 3.2: GeoAligner::1 开始")

        Geo = self.KaKou_OuterTool
        if Geo is None:
            self.Log.append("[ALIGN][WARN] Geo 为空（KaKou_OuterTool=None），跳过 GeoAligner::1")
            self.GeoAligner1_SourceOut = None
            self.GeoAligner1_TargetOut = None
            self.GeoAligner1_MovedGeo  = None
            return

        src_idx = self._as_int(self.all_get("GeoAligner_1__SourcePlane", 0), 0)
        tgt_idx = self._as_int(self.all_get("GeoAligner_1__TargetPlane", 0), 0)

        SourcePlane = self._safe_index(self.KaKou_RefPlanes, src_idx, name="KaKou_RefPlanes")
        TargetPlane = self._safe_index(self.FacePlaneList, tgt_idx, name="FacePlaneList")

        if SourcePlane is None or TargetPlane is None:
            self.Log.append("[ALIGN][WARN] SourcePlane 或 TargetPlane 为空，跳过 GeoAligner::1")
            self.GeoAligner1_SourceOut = SourcePlane
            self.GeoAligner1_TargetOut = TargetPlane
            self.GeoAligner1_MovedGeo  = None
            return

        RotateDeg = self._as_float(self.all_get("GeoAligner_1__RotateDeg", 0.0), 0.0)
        FlipX     = self._as_bool01(self.all_get("GeoAligner_1__FlipX", 0), 0)
        MoveY     = self._as_float(self.all_get("GeoAligner_1__MoveY", 0.0), 0.0)

        FlipY = 0
        FlipZ = 0
        MoveX = 0.0
        MoveZ = 0.0

        try:
            SourceOut, TargetOut, MovedGeo = FT_GeoAligner.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            self.GeoAligner1_SourceOut = SourceOut
            self.GeoAligner1_TargetOut = TargetOut
            self.GeoAligner1_MovedGeo  = MovedGeo

            self.Log.append("[ALIGN] GeoAligner::1 完成：RotateDeg={}, FlipX={}, MoveY={}".format(RotateDeg, FlipX, MoveY))

        except Exception as e:
            self.GeoAligner1_SourceOut = SourcePlane
            self.GeoAligner1_TargetOut = TargetPlane
            self.GeoAligner1_MovedGeo  = None
            self.Log.append("[ALIGN][ERROR] FT_GeoAligner.align 出错: {}".format(e))

    # ------------------------------------------------------------
    # Step 4.1：FT_BlockCutter（用 build_timber_block_uniform 构建“刀块”）
    # ------------------------------------------------------------
    def step4_block_cutter(self):
        self.Log.append("[BC] Step 4.1: FT_BlockCutter 开始")

        length_raw = self.all_get("FT_BlockCutter__length_fen", 32.0)
        width_raw  = self.all_get("FT_BlockCutter__width_fen",  32.0)
        height_raw = self.all_get("FT_BlockCutter__height_fen", 20.0)

        length_fen = self._as_float(length_raw, 32.0)
        width_fen  = self._as_float(width_raw,  32.0)
        height_fen = self._as_float(height_raw, 20.0)

        base_point = rg.Point3d(0.0, 0.0, 0.0)
        reference_plane = make_gh_ref_plane("WorldXZ", origin=rg.Point3d(0.0, 0.0, 0.0))

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
            )

            self.BlockCutter_TimberBrep      = timber_brep
            self.BlockCutter_FaceList        = faces or []
            self.BlockCutter_PointList       = points or []
            self.BlockCutter_EdgeList        = edges or []
            self.BlockCutter_CenterPoint     = center_pt
            self.BlockCutter_CenterAxisLines = center_axes or []
            self.BlockCutter_EdgeMidPoints   = edge_midpts or []
            self.BlockCutter_FacePlaneList   = face_planes or []
            self.BlockCutter_Corner0Planes   = corner0_planes or []
            self.BlockCutter_LocalAxesPlane  = local_axes_plane
            self.BlockCutter_AxisX           = axis_x
            self.BlockCutter_AxisY           = axis_y
            self.BlockCutter_AxisZ           = axis_z
            self.BlockCutter_FaceDirTags     = face_tags or []
            self.BlockCutter_EdgeDirTags     = edge_tags or []
            self.BlockCutter_Corner0EdgeDirs = corner0_dirs or []
            self.BlockCutter_Log             = log_lines or []

            self.Log.append("[BC] FT_BlockCutter 构建完成")
            for l in (log_lines or []):
                self.Log.append("[BC] " + str(l))

        except Exception as e:
            self.BlockCutter_TimberBrep      = None
            self.BlockCutter_FaceList        = []
            self.BlockCutter_PointList       = []
            self.BlockCutter_EdgeList        = []
            self.BlockCutter_CenterPoint     = None
            self.BlockCutter_CenterAxisLines = []
            self.BlockCutter_EdgeMidPoints   = []
            self.BlockCutter_FacePlaneList   = []
            self.BlockCutter_Corner0Planes   = []
            self.BlockCutter_LocalAxesPlane  = None
            self.BlockCutter_AxisX           = None
            self.BlockCutter_AxisY           = None
            self.BlockCutter_AxisZ           = None
            self.BlockCutter_FaceDirTags     = []
            self.BlockCutter_EdgeDirTags     = []
            self.BlockCutter_Corner0EdgeDirs = []
            self.BlockCutter_Log             = ["错误: {}".format(e)]
            self.Log.append("[BC][ERROR] FT_BlockCutter 出错: {}".format(e))

    # ------------------------------------------------------------
    # Step 4.2：PlaneFromLists::1（主木坯：PointList + Corner0Planes）
    # ------------------------------------------------------------
    def step4_planefromlists_1(self):
        self.Log.append("[PFL] Step 4.2: PlaneFromLists::1 开始")

        OriginPoints = self.PointList
        BasePlanes   = self.Corner0Planes
        IndexOrigin_raw = self.all_get("PlaneFromLists_1__IndexOrigin", 0)
        IndexPlane_raw  = self.all_get("PlaneFromLists_1__IndexPlane", 0)
        Wrap         = self.all_get("PlaneFromLists_1__Wrap", True)
        Wrap = bool(Wrap) if Wrap is not None else True

        # ------------------------------------------------------------
        # GH 广播：IndexOrigin/IndexPlane 可为单值或列表
        # （此处 OriginPoints/BasePlanes 通常是单组列表，不做“列表的列表”分组）
        # ------------------------------------------------------------
        n = max(
            _param_length(IndexOrigin_raw),
            _param_length(IndexPlane_raw),
            1
        )

        IndexOrigins = _broadcast_param(_to_list(IndexOrigin_raw), n, "PlaneFromLists_1__IndexOrigin")
        IndexPlanes  = _broadcast_param(_to_list(IndexPlane_raw),  n, "PlaneFromLists_1__IndexPlane")

        IndexOrigins = [self._as_int(v, 0) for v in IndexOrigins]
        IndexPlanes  = [self._as_int(v, 0) for v in IndexPlanes]

        self.Log.append("[PFL1] 广播长度 n = {}".format(n))
        self.Log.append("[PFL1] IndexOrigins = {}".format(IndexOrigins))
        self.Log.append("[PFL1] IndexPlanes  = {}".format(IndexPlanes))

        try:
            builder = FTPlaneFromLists(wrap=Wrap)

            base_out_list   = []
            origin_out_list = []
            plane_out_list  = []
            log_all = []

            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, LogLines = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    IndexOrigins[i],
                    IndexPlanes[i]
                )

                base_out_list.append(BasePlane)
                origin_out_list.append(OriginPoint)
                plane_out_list.append(ResultPlane)

                for l in (LogLines or []):
                    log_all.append(l)
                    self.Log.append("[PFL1] #{} ".format(i) + str(l))

            # 关键：保持列表输出（让后续 GeoAligner / Cut 可以广播）
            self.PFL1_BasePlane   = base_out_list
            self.PFL1_OriginPoint = origin_out_list
            self.PFL1_ResultPlane = plane_out_list
            self.PFL1_Log         = log_all

        except Exception as e:
            self.PFL1_BasePlane   = None
            self.PFL1_OriginPoint = None
            self.PFL1_ResultPlane = None
            self.PFL1_Log         = ["错误: {}".format(e)]
            self.Log.append("[PFL1][ERROR] build_plane 出错: {}".format(e))


    # ------------------------------------------------------------
    # Step 4.3：PlaneFromLists::2（BlockCutter：PointList + FacePlaneList）
    # ------------------------------------------------------------
    def step4_planefromlists_2(self):
        self.Log.append("[PFL] Step 4.3: PlaneFromLists::2 开始")

        OriginPoints = self.BlockCutter_PointList
        BasePlanes   = self.BlockCutter_FacePlaneList
        IndexOrigin_raw = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
        IndexPlane_raw  = self.all_get("PlaneFromLists_2__IndexPlane", 0)
        Wrap         = self.all_get("PlaneFromLists_2__Wrap", True)
        Wrap = bool(Wrap) if Wrap is not None else True

        # ------------------------------------------------------------
        # GH 广播：支持 IndexOrigin/IndexPlane 为单值或列表
        # 同时兼容 OriginPoints/BasePlanes 为“列表”或“列表的列表”
        # ------------------------------------------------------------
        def _is_list_of_lists(x):
            return isinstance(x, (list, tuple)) and len(x) > 0 and isinstance(x[0], (list, tuple))

        origin_outer_n = len(OriginPoints) if _is_list_of_lists(OriginPoints) else 1
        base_outer_n   = len(BasePlanes)   if _is_list_of_lists(BasePlanes)   else 1

        n = max(
            _param_length(IndexOrigin_raw),
            _param_length(IndexPlane_raw),
            origin_outer_n,
            base_outer_n,
            1
        )

        IndexOrigins = _broadcast_param(_to_list(IndexOrigin_raw), n, "PlaneFromLists_2__IndexOrigin")
        IndexPlanes  = _broadcast_param(_to_list(IndexPlane_raw),  n, "PlaneFromLists_2__IndexPlane")

        # 逐项转 int
        IndexOrigins = [self._as_int(v, 0) for v in IndexOrigins]
        IndexPlanes  = [self._as_int(v, 0) for v in IndexPlanes]

        self.Log.append("[PFL2] 广播长度 n = {}".format(n))
        self.Log.append("[PFL2] IndexOrigins = {}".format(IndexOrigins))
        self.Log.append("[PFL2] IndexPlanes  = {}".format(IndexPlanes))

        try:
            builder = FTPlaneFromLists(wrap=Wrap)

            base_out_list   = []
            origin_out_list = []
            plane_out_list  = []
            log_all = []

            for i in range(n):
                OP_i = OriginPoints[i] if _is_list_of_lists(OriginPoints) else OriginPoints
                BP_i = BasePlanes[i]   if _is_list_of_lists(BasePlanes)   else BasePlanes

                BasePlane, OriginPoint, ResultPlane, LogLines = builder.build_plane(
                    OP_i,
                    BP_i,
                    IndexOrigins[i],
                    IndexPlanes[i]
                )

                base_out_list.append(BasePlane)
                origin_out_list.append(OriginPoint)
                plane_out_list.append(ResultPlane)

                for l in (LogLines or []):
                    log_all.append(l)
                    self.Log.append("[PFL2] #{} ".format(i) + str(l))

            # 输出保持“列表”（让后续 GeoAligner::2 可以继续广播）
            self.PFL2_BasePlane   = base_out_list
            self.PFL2_OriginPoint = origin_out_list
            self.PFL2_ResultPlane = plane_out_list
            self.PFL2_Log         = log_all

        except Exception as e:
            self.PFL2_BasePlane   = None
            self.PFL2_OriginPoint = None
            self.PFL2_ResultPlane = None
            self.PFL2_Log         = ["错误: {}".format(e)]
            self.Log.append("[PFL2][ERROR] build_plane 出错: {}".format(e))

    # ------------------------------------------------------------
    # Step 4.4：GeoAligner::2（对位 BlockCutter 到主木坯）
    #   Geo         = BlockCutter_TimberBrep
    #   SourcePlane = PFL2_ResultPlane
    #   TargetPlane = PFL1_ResultPlane
    #   RotateDeg   = GeoAligner_2__RotateDeg
    #   FlipX       = GeoAligner_2__FlipX
    # ------------------------------------------------------------
    def step4_geoaligner_2(self):
        self.Log.append("[ALIGN] Step 4.4: GeoAligner::2 开始")

        Geo0_raw       = self.BlockCutter_TimberBrep
        SourcePlane_raw = self.PFL2_ResultPlane
        TargetPlane_raw = self.PFL1_ResultPlane
        print(TargetPlane_raw)

        if Geo0_raw is None:
            self.Log.append("[ALIGN2][WARN] BlockCutter_TimberBrep=None，跳过 GeoAligner::2")
            self.GeoAligner2_SourceOut = SourcePlane_raw
            self.GeoAligner2_TargetOut = TargetPlane_raw
            self.GeoAligner2_MovedGeo  = None
            return

        if SourcePlane_raw is None or TargetPlane_raw is None:
            self.Log.append("[ALIGN2][WARN] SourcePlane 或 TargetPlane 为空，跳过 GeoAligner::2")
            self.GeoAligner2_SourceOut = SourcePlane_raw
            self.GeoAligner2_TargetOut = TargetPlane_raw
            self.GeoAligner2_MovedGeo  = None
            return

        # ------------------------------------------------------------
        # 1) 从 DB 取多值参数（RotateDeg/FlipX）
        # ------------------------------------------------------------
        rot_raw   = self.AllDict.get("GeoAligner_2__RotateDeg", self.all_get("GeoAligner_2__RotateDeg", 0.0))
        flipx_raw = self.AllDict.get("GeoAligner_2__FlipX",     self.all_get("GeoAligner_2__FlipX", 0))

        # ------------------------------------------------------------
        # 2) 计算广播长度 n：把 Geo / SourcePlane / TargetPlane 也纳入
        # ------------------------------------------------------------
        n = max(
            _param_length(Geo0_raw),
            _param_length(SourcePlane_raw),
            _param_length(TargetPlane_raw),
            _param_length(rot_raw),
            _param_length(flipx_raw),
            1
        )

        # ------------------------------------------------------------
        # 3) 广播所有输入到长度 n（GH 风格：短的用最后一个补齐）
        # ------------------------------------------------------------
        Geos        = _broadcast_param(_to_list(Geo0_raw),        n, "Geo")
        SourcePlanes = _broadcast_param(_to_list(SourcePlane_raw), n, "SourcePlane")
        TargetPlanes = _broadcast_param(_to_list(TargetPlane_raw), n, "TargetPlane")

        RotateDegs = _broadcast_param(_to_list(rot_raw),   n, "RotateDeg")
        FlipXs_raw = _broadcast_param(_to_list(flipx_raw), n, "FlipX")

        # 逐项强制类型
        RotateDegs = [self._as_float(v, 0.0) for v in RotateDegs]
        FlipXs     = [self._as_bool01(v, 0) for v in FlipXs_raw]

        # 其他参数先保持固定（未来如也需要多值，同样可按上面广播）
        FlipY = 0
        FlipZ = 0
        MoveX = 0.0
        MoveY = 0.0
        MoveZ = 0.0

        self.Log.append("[ALIGN2] 广播长度 n = {}".format(n))
        self.Log.append("[ALIGN2] RotateDegs = {}".format(RotateDegs))
        self.Log.append("[ALIGN2] FlipXs     = {}".format(FlipXs))

        # ------------------------------------------------------------
        # 4) 循环对位：逐项对位（Geo/Source/Target/Rotate/Flip 全广播）
        # ------------------------------------------------------------
        moved_list   = []
        src_out_list = []
        tgt_out_list = []

        for i in range(n):
            try:
                SourceOut, TargetOut, MovedGeo = FT_GeoAligner.align(
                    Geos[i],
                    SourcePlanes[i],
                    TargetPlanes[i],
                    rotate_deg=RotateDegs[i],
                    flip_x=FlipXs[i],
                    flip_y=FlipY,
                    flip_z=FlipZ,
                    move_x=MoveX,
                    move_y=MoveY,
                    move_z=MoveZ,
                )

                src_out_list.append(SourceOut)
                tgt_out_list.append(TargetOut)

                # 兼容 MovedGeo 可能是单值或 list
                if isinstance(MovedGeo, (list, tuple)):
                    moved_list.extend(list(MovedGeo))
                else:
                    moved_list.append(MovedGeo)

                self.Log.append("[ALIGN2] #{} OK: RotateDeg={}, FlipX={}".format(i, RotateDegs[i], FlipXs[i]))

            except Exception as e:
                self.Log.append("[ALIGN2][ERROR] #{} 失败: {}".format(i, e))
                moved_list.append(None)

        # 输出：MovedGeo 保持列表，Cut 时会作为 tools 的一部分继续传下去
        self.GeoAligner2_SourceOut = src_out_list[-1] if len(src_out_list) else SourcePlanes[-1]
        self.GeoAligner2_TargetOut = tgt_out_list[-1] if len(tgt_out_list) else TargetPlanes[-1]
        self.GeoAligner2_MovedGeo  = moved_list


    # ------------------------------------------------------------
    # Step 4.5：FT_CutTimberByTools_V2（切主木坯）
    #   Timbers = TimberBrep
    #   Tools   = [GeoAligner1_MovedGeo, GeoAligner2_MovedGeo]
    # ------------------------------------------------------------
    def step4_cut(self):
        self.Log.append("[CUT] Step 4.5: FT_CutTimberByTools_V2 开始")

        Timbers = self.TimberBrep
        if Timbers is None:
            self.Log.append("[CUT][WARN] TimberBrep=None，跳过切割")
            self.CutTimbers = []
            self.FailTimbers = []
            return

        tools = []
        if self.GeoAligner1_MovedGeo is not None:
            tools.append(self.GeoAligner1_MovedGeo)
        else:
            self.Log.append("[CUT][WARN] GeoAligner1_MovedGeo=None（卡口刀具缺失）")

        if self.GeoAligner2_MovedGeo is not None:
            tools.append(self.GeoAligner2_MovedGeo)
        else:
            self.Log.append("[CUT][WARN] GeoAligner2_MovedGeo=None（BlockCutter 刀具缺失）")

        if len(tools) == 0:
            self.Log.append("[CUT][WARN] Tools 为空，跳过切割")
            self.CutTimbers = []
            self.FailTimbers = []
            return

        KeepInside = self.all_get("FT_CutTimberByTools_V2__KeepInside", False)
        try:
            _keep_inside_flag = bool(KeepInside)
        except:
            _keep_inside_flag = False

        try:
            cutter = FT_CutTimberByTools_V2(
                Timbers,
                tools,
                keep_inside=_keep_inside_flag
            )

            CutTimbers, FailTimbers, LogLines = cutter.run()

            self.CutTimbers  = CutTimbers or []
            self.FailTimbers = FailTimbers or []
            self.Cut_Log     = LogLines or []

            for l in (LogLines or []):
                self.Log.append("[CUT] " + str(l))

            self.Log.append("[CUT] 完成：CutTimbers={} / FailTimbers={}".format(len(self.CutTimbers), len(self.FailTimbers)))

        except Exception as e:
            self.CutTimbers = []
            self.FailTimbers = []
            self.Cut_Log = ["错误: {}".format(e)]
            self.Log.append("[CUT][ERROR] FT_CutTimberByTools_V2 出错: {}".format(e))

    # ------------------------------------------------------------
    # 主控入口（Step 1 + Step 2 + Step 3 + Step 4）
    # ------------------------------------------------------------
    def run(self):
        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空：跳过 Step 2/3/4，输出占位。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        self.step2_timber()
        if self.TimberBrep is None:
            self.Log.append("[RUN] TimberBrep 为空：跳过 Step 3/4。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        # Step 3：卡口 + 对位1
        self.step3_kakou_builder()
        self.step3_geoaligner_1()

        # Step 4：BlockCutter + PlaneFromLists + 对位2 + Cut
        self.step4_block_cutter()
        self.step4_planefromlists_1()
        self.step4_planefromlists_2()
        self.step4_geoaligner_2()
        self.step4_cut()

        self.Log.append("[RUN] 当前实现 Step 1 + Step 2 + Step 3 + Step 4")
        return self

if __name__=="__main__":
    # ======================================================================
    # GH Python 组件入口
    # ======================================================================
    solver = ChenFangTouSolver(
        DBPath=DBPath,
        base_point=base_point,
        Refresh=Refresh,
        ghenv=ghenv
    ).run()


    # ======================================================================
    # GH Python · 输出绑定区（当前步骤）
    # ======================================================================

    # --- 主输出 ---
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log

    # --- Step 1：数据库读取（开发模式输出）---
    Value   = solver.Value
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = solver.DBLog

    # --- Step 2：FT_timber_block_uniform（开发模式输出）---
    TimberBrep      = solver.TimberBrep
    FaceList        = solver.FaceList
    PointList       = solver.PointList
    EdgeList        = solver.EdgeList
    CenterPoint     = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    EdgeMidPoints   = solver.EdgeMidPoints
    FacePlaneList   = solver.FacePlaneList
    Corner0Planes   = solver.Corner0Planes
    LocalAxesPlane  = solver.LocalAxesPlane
    AxisX           = solver.AxisX
    AxisY           = solver.AxisY
    AxisZ           = solver.AxisZ
    FaceDirTags     = solver.FaceDirTags
    EdgeDirTags     = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs
    TimberLog       = solver.TimberLog

    # --- Step 3：卡口（RuFangKaKouBuilder）开发模式输出 ---
    KaKou_OuterTool      = solver.KaKou_OuterTool
    KaKou_InnerTool      = solver.KaKou_InnerTool
    KaKou_OuterSection   = solver.KaKou_OuterSection
    KaKou_InnerSection   = solver.KaKou_InnerSection
    KaKou_RefPlanes      = solver.KaKou_RefPlanes
    KaKou_EdgeMidPoints  = solver.KaKou_EdgeMidPoints
    KaKou_EdgeNames      = solver.KaKou_EdgeNames
    KaKou_KeyPoints      = solver.KaKou_KeyPoints
    KaKou_KeyPointNames  = solver.KaKou_KeyPointNames
    KaKou_EdgeCurves     = solver.KaKou_EdgeCurves
    KaKou_RefPlaneNames  = solver.KaKou_RefPlaneNames
    KaKou_Log            = solver.KaKou_Log

    GeoAligner1_SourceOut = solver.GeoAligner1_SourceOut
    GeoAligner1_TargetOut = solver.GeoAligner1_TargetOut
    GeoAligner1_MovedGeo  = solver.GeoAligner1_MovedGeo

    # --- Step 4：BlockCutter（开发模式输出）---
    BlockCutter_TimberBrep      = solver.BlockCutter_TimberBrep
    BlockCutter_FaceList        = solver.BlockCutter_FaceList
    BlockCutter_PointList       = solver.BlockCutter_PointList
    BlockCutter_EdgeList        = solver.BlockCutter_EdgeList
    BlockCutter_CenterPoint     = solver.BlockCutter_CenterPoint
    BlockCutter_CenterAxisLines = solver.BlockCutter_CenterAxisLines
    BlockCutter_EdgeMidPoints   = solver.BlockCutter_EdgeMidPoints
    BlockCutter_FacePlaneList   = solver.BlockCutter_FacePlaneList
    BlockCutter_Corner0Planes   = solver.BlockCutter_Corner0Planes
    BlockCutter_LocalAxesPlane  = solver.BlockCutter_LocalAxesPlane
    BlockCutter_AxisX           = solver.BlockCutter_AxisX
    BlockCutter_AxisY           = solver.BlockCutter_AxisY
    BlockCutter_AxisZ           = solver.BlockCutter_AxisZ
    BlockCutter_FaceDirTags     = solver.BlockCutter_FaceDirTags
    BlockCutter_EdgeDirTags     = solver.BlockCutter_EdgeDirTags
    BlockCutter_Corner0EdgeDirs = solver.BlockCutter_Corner0EdgeDirs
    BlockCutter_Log             = solver.BlockCutter_Log

    PFL1_BasePlane   = solver.PFL1_BasePlane
    PFL1_OriginPoint = solver.PFL1_OriginPoint
    PFL1_ResultPlane = solver.PFL1_ResultPlane
    PFL1_Log         = solver.PFL1_Log

    PFL2_BasePlane   = solver.PFL2_BasePlane
    PFL2_OriginPoint = solver.PFL2_OriginPoint
    PFL2_ResultPlane = solver.PFL2_ResultPlane
    PFL2_Log         = solver.PFL2_Log

    GeoAligner2_SourceOut = solver.GeoAligner2_SourceOut
    GeoAligner2_TargetOut = solver.GeoAligner2_TargetOut
    GeoAligner2_MovedGeo  = solver.GeoAligner2_MovedGeo

    Cut_Log = solver.Cut_Log


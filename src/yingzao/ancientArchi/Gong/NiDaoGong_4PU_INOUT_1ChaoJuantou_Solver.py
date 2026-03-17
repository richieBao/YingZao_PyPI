# -*- coding: utf-8 -*-
"""
NiDaoGongSolver · Step 1 + Step 2（泥道栱：四鋪作裏外並一抄卷頭 —— 数据库驱动）
------------------------------------------------------------
本文件为“逐步转换”的第 1 阶段：
1) Step 1：读取数据库 DG_Dou / params_json，导出 All，并转换为 AllDict
2) Step 2：构建原始木料块 FT_timber_block_uniform（build_timber_block_uniform）

输入（GhPython 组件输入端）：
    DBPath     : str        - SQLite 数据库路径（Song-styleArchi.db）
    base_point : rg.Point3d - 木料定位点（None → 原点）
    Refresh    : bool       - 刷新开关（True 时强制重读数据库；本阶段仅作为触发重算使用）

输出（建议至少先建这三个，后续可随时增加）：
    CutTimbers   : object/list   - 本阶段占位输出（= TimberBrep）
    FailTimbers  : list          - 本阶段为空
    Log          : list[str]     - 全局日志（递归拍平）

并暴露开发输出：
    Value, All, AllDict, DBLog,
    TimberBrep, FaceList, PointList, EdgeList, CenterPoint, CenterAxisLines,
    EdgeMidPoints, FacePlaneList, Corner0Planes, LocalAxesPlane,
    AxisX, AxisY, AxisZ, FaceDirTags, EdgeDirTags, Corner0EdgeDirs
"""

import Rhino.Geometry as rg

# --- GH Components wrapper (Solid Difference etc.) ---
try:
    import ghpythonlib.components as ghc
except Exception:
    ghc = None
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    JuanShaToolBuilder,
    FTPlaneFromLists,
    FTAligner,
    FT_GongYanSection_Cai_B,
    FT_GeoAligner,
    FT_AnZhiToolBuilder,
)


# ==============================================================
# 通用工具函数
# ==============================================================

def to_list(x):
    """若为列表/元组则直接返回 list，否则包装成长度为 1 的 list。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def all_to_dict(all_list):
    """
    All = [('k', v), ...] → dict
    """
    d = {}
    if not all_list:
        return d
    for item in all_list:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        k, v = item
        d[k] = v
    return d


def make_ref_plane(mode_str):
    """
    根据字符串构造参考平面：
    - XY : X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    - XZ : X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  ← 默认
    - YZ : X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    if mode_str is None:
        mode_str = "WorldXZ"

    m = str(mode_str).upper()
    origin = rg.Point3d(0.0, 0.0, 0.0)

    if m in ("WORLDXY", "XY", "XY_PLANE"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WORLDYZ", "YZ", "YZ_PLANE"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ（Plane 自动得到 Z = X × Y = (0,-1,0)）
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def flatten_any(x):
    """
    递归拍平 list/tuple，避免 GH 输出出现嵌套 System.Collections.Generic.List`1[System.Object]
    注意：Rhino 几何对象不应被当作 iterable 展开，因此这里只对 (list/tuple) 做拍平。
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        out = []
        for it in x:
            if isinstance(it, (list, tuple)):
                out.extend(flatten_any(it))
            else:
                out.append(it)
        return out
    return [x]


def pick_plane(planes, index, wrap=True):
    """从 planes (Plane 或 list[Plane]) 按索引取 Plane。index 可为标量或 list/tuple（取第一个）。"""
    import Rhino.Geometry as rg

    if planes is None:
        return None

    # 允许传入单个 Plane
    if isinstance(planes, rg.Plane):
        planes_list = [planes]
    elif isinstance(planes, (list, tuple)):
        planes_list = list(planes)
    else:
        # 尝试从 GH Goo 取 Value
        if hasattr(planes, "Value") and isinstance(planes.Value, rg.Plane):
            planes_list = [planes.Value]
        else:
            return None

    if not planes_list:
        return None

    # index 允许为 list/tuple：取第一个
    if isinstance(index, (list, tuple)):
        if len(index) == 0:
            return None
        index = index[0]

    try:
        i = int(index)
    except Exception:
        return None

    n = len(planes_list)
    if wrap and n > 0:
        i = i % n

    if i < 0 or i >= n:
        return None

    pl = planes_list[i]
    if isinstance(pl, rg.Plane):
        return pl
    # GH Goo
    if hasattr(pl, "Value") and isinstance(pl.Value, rg.Plane):
        return pl.Value
    return None


def get_input_value(name, default=None):
    """
    从 GH 组件输入端（globals）取值：若输入端不存在则返回 default。
    这样你后续“可选增加 override 输入端”时，不会改代码也能生效。
    """
    try:
        if name in globals():
            v = globals()[name]
            if v is not None:
                return v
    except:
        pass
    return default


def coerce_point3d(p, default_pt=None):
    if default_pt is None:
        default_pt = rg.Point3d(0.0, 0.0, 0.0)
    if p is None:
        return default_pt
    if isinstance(p, rg.Point3d):
        return p
    if isinstance(p, rg.Point):
        return p.Location
    # 尝试 (x,y,z)
    if isinstance(p, (list, tuple)) and len(p) >= 3:
        try:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        except:
            return default_pt
    # 尝试对象属性
    try:
        return rg.Point3d(float(p.X), float(p.Y), float(p.Z))
    except:
        return default_pt


def coerce_brep(x):
    """尽可能把 GH Goo / Proxy / 其它对象转换为 Rhino.Geometry.Brep。
    目的：保证传入 yingzao.ancientArchi 的几何是 RhinoCommon Brep，避免 bbox / boolean 的版本差异。
    """
    if x is None:
        return None
    if isinstance(x, rg.Brep):
        return x

    # GH_Brep 等 Goo 通常有 .Value
    try:
        v = getattr(x, "Value", None)
        if isinstance(v, rg.Brep):
            return v
    except:
        pass

    # RhinoCommon 提供的通用转换
    try:
        b = rg.Brep.TryConvertBrep(x)
        if isinstance(b, rg.Brep):
            return b
    except:
        pass

    return None


# ==============================================================
# 主 Solver 类 —— NiDaoGongSolver
# ==============================================================

class NiDaoGong_4PU_INOUT_1ChaoJuantou_Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step1：DB 输出
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step2：木坯输出（与 FT_timber_block_uniform 命名一致）
        self.TimberBrep = None
        self.FaceList = []
        self.PointList = []
        self.EdgeList = []
        self.CenterPoint = None
        self.CenterAxisLines = []
        self.EdgeMidPoints = []
        self.FacePlaneList = []
        self.Corner0Planes = []
        self.LocalAxesPlane = None
        self.AxisX = None
        self.AxisY = None
        self.AxisZ = None
        self.FaceDirTags = []
        self.EdgeDirTags = []
        self.Corner0EdgeDirs = []

        # Step3：卷杀（JuanShaToolBuilder / PlaneFromLists::1 / FT_AlignToolToTimber::1）
        self.JuanSha_ToolBrep = None
        self.JuanSha_SectionEdges = []
        self.JuanSha_HL_Intersection = None
        self.JuanSha_HeightFacePlane = None
        self.JuanSha_LengthFacePlane = None
        self.JuanSha_Log = []

        self.PFL1_BasePlane = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlane = None
        self.PFL1_Log = []

        self.FT_AlignToolToTimber_1__AlignedTool = []
        self.FT_AlignToolToTimber_1__XForm = []
        self.FT_AlignToolToTimber_1__SourcePlane = []
        self.FT_AlignToolToTimber_1__TargetPlane = []
        self.FT_AlignToolToTimber_1__SourcePoint = []
        self.FT_AlignToolToTimber_1__TargetPoint = []
        self.FT_AlignToolToTimber_1__DebugInfo = []

        # Step4：卡扣（FT_BlockCutter / FT_AlignToolToTimber::2）
        self.FT_BlockCutter_TimberBrep = None
        self.FT_BlockCutter_FaceList = []
        self.FT_BlockCutter_PointList = []
        self.FT_BlockCutter_EdgeList = []
        self.FT_BlockCutter_CenterPoint = None
        self.FT_BlockCutter_CenterAxisLines = []
        self.FT_BlockCutter_EdgeMidPoints = []
        self.FT_BlockCutter_FacePlaneList = []
        self.FT_BlockCutter_Corner0Planes = []
        self.FT_BlockCutter_LocalAxesPlane = None
        self.FT_BlockCutter_AxisX = None
        self.FT_BlockCutter_AxisY = None
        self.FT_BlockCutter_AxisZ = None
        self.FT_BlockCutter_FaceDirTags = []
        self.FT_BlockCutter_EdgeDirTags = []
        self.FT_BlockCutter_Corner0EdgeDirs = []
        self.FT_BlockCutter_Log = []

        # Step4: Align2 选取的平面（便于调试）
        self.Picked_ToolBasePlanes_2 = None
        self.Picked_BlockFacePlanes_2 = None

        self.FT_AlignToolToTimber_2__AlignedTool = []
        self.FT_AlignToolToTimber_2__XForm = []
        self.FT_AlignToolToTimber_2__SourcePlane = []
        self.FT_AlignToolToTimber_2__TargetPlane = []
        self.FT_AlignToolToTimber_2__SourcePoint = []
        self.FT_AlignToolToTimber_2__TargetPoint = []
        self.FT_AlignToolToTimber_2__DebugInfo = []

        # Step5：栱眼（GongYan-B / FT_AlignToolToTimber::3 / FT_CutTimberByTools）
        self.GongYanB_SectionFace = None
        self.GongYanB_OffsetFace = None
        self.GongYanB_Points = []
        self.GongYanB_OffsetPoints = []
        self.GongYanB_ToolBrep = None
        self.GongYanB_BridgePoints = []
        self.GongYanB_BridgeMidPoints = []
        self.GongYanB_BridgePlane = None
        self.GongYanB_Log = []

        self.FT_AlignToolToTimber_3__SourceOut = None
        self.FT_AlignToolToTimber_3__TargetOut = None
        self.FT_AlignToolToTimber_3__MovedGeo = None
        self.FT_AlignToolToTimber_3__Log = []

        self.CutByTools_Log = []
        # 最终输出占位（本阶段先把 TimberBrep 作为 CutTimbers）

        self.CutTimbers = None
        self.FailTimbers = []

        # Step6：闇栔增件输出初始化
        self.AnZhi_ToolBrep = None
        self.AnZhi_BasePoint = None
        self.AnZhi_BaseLine = None
        self.AnZhi_SecPlane = None
        self.AnZhi_FacePlane = None
        self.AnZhi_CubeBrep = None
        self.AnZhi_PinBreps = []
        self.AnZhi_AnZhiToolBrep = None
        self.AnZhi_CubeEdgeCenters = []
        self.AnZhi_CubeFacePlanes = []
        self.AnZhi_CubeVertices = []
        self.AnZhi_Log = []

        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        self.FT_AlignToolToTimber_4__SourceOut = None
        self.FT_AlignToolToTimber_4__TargetOut = None
        self.FT_AlignToolToTimber_4__MovedGeo = []
        self.FT_AlignToolToTimber_4__Log = []

    # -------------------------
    # 从 AllDict 取值
    # -------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict[key]
        # 若是长度为 1 的 list/tuple，解包
        if isinstance(v, (list, tuple)) and len(v) == 1:
            return v[0]
        return v

    # ==========================================================
    # Step 1：读取数据库（DBJsonReader）
    # ==========================================================
    def step1_read_db(self):
        """
        按你的 step1 设定：
        Table      = DG_Dou
        KeyField   = type_code
        KeyValue   = NiDaoGong_4PU_INOUT_1ChaoJuantou   （若读不到则 fallback 尝试 ...ChongG）
        Field      = params_json
        ExportAll  = True
        """
        try:
            # 优先用你步骤描述里的 key_value
            key_value_primary = "NiDaoGong_4PU_INOUT_1ChaoJuantou"
            key_value_fallback = "NiDaoGong_4PU_INOUT_1ChaoJuantouChongG"

            def _read_once(kv):
                reader = DBJsonReader(
                    db_path=self.DBPath,
                    table="DG_Dou",
                    key_field="type_code",
                    key_value=kv,
                    field="params_json",
                    json_path=None,
                    export_all=True,
                    ghenv=self.ghenv
                )
                return reader.run()

            self.Value, self.All, self.DBLog = _read_once(key_value_primary)

            # 如果没读到，再尝试 fallback（与你前面插入数据库的 type_code 一致）
            if not self.All:
                self.Log.append("[DB] primary KeyValue 未读到数据，尝试 fallback: {}".format(key_value_fallback))
                self.Value, self.All, self.DBLog = _read_once(key_value_fallback)

            self.Log.append("[DB] 数据库读取完成")
            for l in (self.DBLog or []):
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))
            self.Value = None
            self.All = None
            self.AllDict = {}
            self.DBLog = ["错误: {}".format(e)]

        return self

    # ==========================================================
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ==========================================================
    def step2_timber(self):
        """
        组件输入端只有 base_point，但仍按“输入优先级”写成可扩展：
        - length_fen / width_fen / height_fen：若你未来在 GH 里新增 override 输入端（同名变量），则优先取输入端；
          否则取 DB：FT_timber_block_uniform__length_fen 等；再否则默认值。
        - base_point：优先取组件输入端 base_point；None → 原点
        - reference_plane：默认 GH XZ Plane（你本 step 明确要求），也允许 DB 中若写了 reference_plane 则可切换
        """
        # ---- fen 尺寸（输入端可选 override）----
        length_fen_in = get_input_value("FT_timber_block_uniform__length_fen", None)
        width_fen_in = get_input_value("FT_timber_block_uniform__width_fen", None)
        height_fen_in = get_input_value("FT_timber_block_uniform__height_fen", None)

        length_raw = length_fen_in if length_fen_in is not None else self.all_get("FT_timber_block_uniform__length_fen",
                                                                                  32.0)
        width_raw = width_fen_in if width_fen_in is not None else self.all_get("FT_timber_block_uniform__width_fen",
                                                                               32.0)
        height_raw = height_fen_in if height_fen_in is not None else self.all_get("FT_timber_block_uniform__height_fen",
                                                                                  20.0)

        try:
            length_fen = float(length_raw)
            width_fen = float(width_raw)
            height_fen = float(height_raw)
        except Exception as e:
            self.Log.append("[TIMBER] fen 尺寸转换失败: {}，退回默认".format(e))
            length_fen = 32.0
            width_fen = 32.0
            height_fen = 20.0

        # ---- base_point：组件输入端优先 ----
        bp = coerce_point3d(self.base_point, rg.Point3d(0.0, 0.0, 0.0))

        # ---- reference_plane：默认 GH XZ Plane ----
        # 你要求 step2 使用 GH XZ Plane；这里仍允许 DB 写了 reference_plane 时覆盖（便于将来扩展）
        ref_mode = self.all_get("FT_timber_block_uniform__reference_plane", "WorldXZ")
        reference_plane = make_ref_plane(ref_mode)

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

            self.TimberBrep = timber_brep
            self.FaceList = faces
            self.PointList = points
            self.EdgeList = edges
            self.CenterPoint = center_pt
            self.CenterAxisLines = center_axes
            self.EdgeMidPoints = edge_midpts
            self.FacePlaneList = face_planes
            self.Corner0Planes = corner0_planes
            self.LocalAxesPlane = local_axes_plane
            self.AxisX = axis_x
            self.AxisY = axis_y
            self.AxisZ = axis_z
            self.FaceDirTags = face_tags
            self.EdgeDirTags = edge_tags
            self.Corner0EdgeDirs = corner0_dirs

            self.Log.append("[TIMBER] build_timber_block_uniform 完成")
            for l in (log_lines or []):
                self.Log.append("[TIMBER] " + str(l))

            # 本阶段最终输出占位
            self.CutTimbers = self.TimberBrep
            self.FailTimbers = []

        except Exception as e:
            self.TimberBrep = None
            self.FaceList = []
            self.PointList = []
            self.EdgeList = []
            self.CenterPoint = None
            self.CenterAxisLines = []
            self.EdgeMidPoints = []
            self.FacePlaneList = []
            self.Corner0Planes = []
            self.LocalAxesPlane = None
            self.AxisX = None
            self.AxisY = None
            self.AxisZ = None
            self.FaceDirTags = []
            self.EdgeDirTags = []
            self.Corner0EdgeDirs = []

            self.CutTimbers = None
            self.FailTimbers = []

            self.Log.append("[ERROR] step2_timber 出错: {}".format(e))

        return self

    # ==========================================================
    # 主控入口（仅 Step1 + Step2）
    # ==========================================================

    # ==========================================================
    # Step 3：卷杀（JuanShaToolBuilder + PlaneFromLists::1 + FT_AlignToolToTimber::1）
    # ==========================================================
    def step3_juansha(self):
        """
        3.1 JuanShaToolBuilder
            HeightFen     = JuanShaToolBuilder__HeightFen
            LengthFen     = JuanShaToolBuilder__LengthFen
            DivCount      = JuanShaToolBuilder__DivCount
            ThicknessFen  = JuanShaToolBuilder__ThicknessFen
            PositionPoint = 原点（可选输入端覆盖）
            SectionPlane  = 默认 GH XZ Plane（可选输入端覆盖）

        3.2 PlaneFromLists::1（FTPlaneFromLists）
            OriginPoints = Step2.EdgeMidPoints
            BasePlanes   = Step2.Corner0Planes
            IndexOrigin  = PlaneFromLists_1__IndexOrigin
            IndexPlane   = PlaneFromLists_1__IndexPlane
            Wrap         = 默认 True（可选输入端覆盖 / DB 覆盖）

        3.3 FT_AlignToolToTimber::1（FTAligner.align 广播对位）
            ToolGeo       = JuanSha.ToolBrep
            ToolBasePlane = JuanSha.HeightFacePlane
            BlockFacePlane= PFL1.ResultPlane
            BlockRotDeg   = FT_AlignToolToTimber_1__BlockRotDeg
            FlipY         = FT_AlignToolToTimber_1__FlipY
        """
        # -------------------------
        # 3.1 JuanShaToolBuilder
        # -------------------------
        try:
            # 输入优先级：组件输入端 > DB > 默认
            HeightFen_in = get_input_value("JuanShaToolBuilder__HeightFen", None)
            LengthFen_in = get_input_value("JuanShaToolBuilder__LengthFen", None)
            DivCount_in = get_input_value("JuanShaToolBuilder__DivCount", None)
            ThicknessFen_in = get_input_value("JuanShaToolBuilder__ThicknessFen", None)

            HeightFen = HeightFen_in if HeightFen_in is not None else self.all_get("JuanShaToolBuilder__HeightFen",
                                                                                   None)
            LengthFen = LengthFen_in if LengthFen_in is not None else self.all_get("JuanShaToolBuilder__LengthFen",
                                                                                   None)
            DivCount = DivCount_in if DivCount_in is not None else self.all_get("JuanShaToolBuilder__DivCount", None)
            ThicknessFen = ThicknessFen_in if ThicknessFen_in is not None else self.all_get(
                "JuanShaToolBuilder__ThicknessFen", None)

            # 默认值（与 GH 面板常用一致：若 DB 也没有则给合理默认）
            if HeightFen is None: HeightFen = 9.0
            if LengthFen is None: LengthFen = 16.0
            if DivCount is None: DivCount = 4
            if ThicknessFen is None: ThicknessFen = 10.0

            # SectionPlane：允许未来加输入端 SectionPlane 覆盖；否则默认 XZ
            SectionPlane_in = get_input_value("JuanShaToolBuilder__SectionPlane", None)
            SectionPlane = SectionPlane_in if SectionPlane_in is not None else make_ref_plane("WorldXZ")

            # PositionPoint：默认原点；允许未来加输入端覆盖
            PositionPoint_in = get_input_value("JuanShaToolBuilder__PositionPoint", None)
            PositionPoint = coerce_point3d(PositionPoint_in, rg.Point3d(0.0, 0.0, 0.0))

            builder = JuanShaToolBuilder(
                height_fen=HeightFen,
                length_fen=LengthFen,
                thickness_fen=ThicknessFen,
                div_count=DivCount,
                section_plane=SectionPlane,
                position_point=PositionPoint
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, LogLines = builder.build()

            self.JuanSha_ToolBrep = ToolBrep
            self.JuanSha_SectionEdges = SectionEdges
            self.JuanSha_HL_Intersection = HL_Intersection
            self.JuanSha_HeightFacePlane = HeightFacePlane
            self.JuanSha_LengthFacePlane = LengthFacePlane
            self.JuanSha_Log = LogLines if LogLines is not None else []

            self.Log.append("[STEP3] JuanShaToolBuilder 完成")
            for l in flatten_any(self.JuanSha_Log):
                self.Log.append("[STEP3][JuanSha] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step3 JuanShaToolBuilder 出错: {}".format(e))
            self.JuanSha_ToolBrep = None
            self.JuanSha_SectionEdges = []
            self.JuanSha_HL_Intersection = None
            self.JuanSha_HeightFacePlane = None
            self.JuanSha_LengthFacePlane = None
            self.JuanSha_Log = ["错误: {}".format(e)]

        # -------------------------
        # 3.2 PlaneFromLists::1
        # -------------------------
        try:
            OriginPoints = self.EdgeMidPoints
            BasePlanes = self.Corner0Planes

            IndexOrigin_in = get_input_value("PlaneFromLists_1__IndexOrigin", None)
            IndexPlane_in = get_input_value("PlaneFromLists_1__IndexPlane", None)

            IndexOrigin = IndexOrigin_in if IndexOrigin_in is not None else self.all_get(
                "PlaneFromLists_1__IndexOrigin", None)
            IndexPlane = IndexPlane_in if IndexPlane_in is not None else self.all_get("PlaneFromLists_1__IndexPlane",
                                                                                      None)

            Wrap_in = get_input_value("PlaneFromLists_1__Wrap", None)
            Wrap = Wrap_in if Wrap_in is not None else self.all_get("PlaneFromLists_1__Wrap", True)
            if Wrap is None:
                Wrap = True

            pfl = FTPlaneFromLists(wrap=Wrap)
            # --- 支持 IndexOrigin / IndexPlane 为标量或列表，并按 GH 广播规则对齐 ---
            idx_o = IndexOrigin
            idx_p = IndexPlane

            # 统一转为列表（标量 -> [标量]；None -> [None]）
            idx_o_list = to_list(idx_o) if isinstance(idx_o, (list, tuple)) else [idx_o]
            idx_p_list = to_list(idx_p) if isinstance(idx_p, (list, tuple)) else [idx_p]

            # 若为空列表，视为 [None]
            if len(idx_o_list) == 0:
                idx_o_list = [None]
            if len(idx_p_list) == 0:
                idx_p_list = [None]

            # 广播到同一长度 N（用最后一个值补齐）
            N = max(len(idx_o_list), len(idx_p_list))
            if len(idx_o_list) < N:
                idx_o_list = idx_o_list + [idx_o_list[-1]] * (N - len(idx_o_list))
            if len(idx_p_list) < N:
                idx_p_list = idx_p_list + [idx_p_list[-1]] * (N - len(idx_p_list))

            BasePlane_list = []
            OriginPoint_list = []
            ResultPlane_list = []
            LogLines = []

            for i in range(N):
                # FTPlaneFromLists 内部对 index 会做 int()，因此此处确保传入的是单个值而不是 list
                BasePlane_i, OriginPoint_i, ResultPlane_i, Log_i = pfl.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o_list[i],
                    idx_p_list[i]
                )
                BasePlane_list.append(BasePlane_i)
                OriginPoint_list.append(OriginPoint_i)
                ResultPlane_list.append(ResultPlane_i)
                if Log_i:
                    LogLines.extend(Log_i)

            # 若只生成 1 个，则保持与原组件一致输出为标量；多个则输出列表
            BasePlane = BasePlane_list[0] if N == 1 else BasePlane_list
            OriginPoint = OriginPoint_list[0] if N == 1 else OriginPoint_list
            ResultPlane = ResultPlane_list[0] if N == 1 else ResultPlane_list

            self.PFL1_BasePlane = BasePlane
            self.PFL1_OriginPoint = OriginPoint
            self.PFL1_ResultPlane = ResultPlane
            self.PFL1_Log = LogLines if LogLines is not None else []

            self.Log.append("[STEP3] PlaneFromLists::1 完成")
            for l in flatten_any(self.PFL1_Log):
                self.Log.append("[STEP3][PFL1] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step3 PlaneFromLists::1 出错: {}".format(e))
            self.PFL1_BasePlane = None
            self.PFL1_OriginPoint = None
            self.PFL1_ResultPlane = None
            self.PFL1_Log = ["错误: {}".format(e)]

        # -------------------------
        # 3.3 FT_AlignToolToTimber::1（广播对位）
        # -------------------------
        try:
            ToolGeo = self.JuanSha_ToolBrep
            ToolBasePlane = self.JuanSha_HeightFacePlane
            BlockFacePlane = self.PFL1_ResultPlane

            BlockRotDeg_in = get_input_value("FT_AlignToolToTimber_1__BlockRotDeg", None)
            FlipY_in = get_input_value("FT_AlignToolToTimber_1__FlipY", None)

            BlockRotDeg = BlockRotDeg_in if BlockRotDeg_in is not None else self.all_get(
                "FT_AlignToolToTimber_1__BlockRotDeg", 0)
            FlipY = FlipY_in if FlipY_in is not None else self.all_get("FT_AlignToolToTimber_1__FlipY", None)

            # 复用对齐组件里的广播逻辑（轻量内嵌，避免污染全局命名）
            def _to_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            def _param_length(val):
                if isinstance(val, (list, tuple)):
                    return len(val)
                if val is None:
                    return 0
                return 1

            def _broadcast_param(val, n):
                if isinstance(val, (list, tuple)):
                    seq = list(val)
                    l = len(seq)
                    if l == 0:
                        return [None] * n
                    if l >= n:
                        return seq[:n]
                    last = seq[-1]
                    return seq + [last] * (n - l)
                else:
                    return [val] * n

            # 结果容器
            AlignedTool = []
            XForm = []
            SourcePlane = []
            TargetPlane = []
            SourcePoint = []
            TargetPoint = []
            DebugInfo = []

            tools_raw = ToolGeo
            if tools_raw is None:
                tools_raw = []
            tools_list_base = _to_list(tools_raw)

            if len(tools_list_base) == 0 or all(t is None for t in tools_list_base):
                DebugInfo = ["ToolGeo 输入为空，未进行对位。"]
            else:
                tool_count = len(tools_list_base)

                # 决定 N
                if tool_count == 1:
                    lengths = [1]
                    lengths.append(_param_length(ToolBasePlane))
                    lengths.append(_param_length(BlockFacePlane))
                    lengths.append(_param_length(BlockRotDeg))
                    lengths.append(_param_length(FlipY))
                    lengths = [l for l in lengths if l > 0]
                    N = max(lengths) if lengths else 1
                else:
                    N = tool_count

                # 广播到 N
                tools_list = _broadcast_param(tools_list_base, N)
                tool_planes = _broadcast_param(ToolBasePlane, N)
                block_planes = _broadcast_param(BlockFacePlane, N)
                block_rots = _broadcast_param(BlockRotDeg, N)
                flip_ys = _broadcast_param(FlipY, N)

                # 本步骤其余对齐参数未连接，按 None/默认传入
                tool_rots = _broadcast_param(None, N)
                tool_pts = _broadcast_param(None, N)
                block_pts = _broadcast_param(None, N)
                modes = _broadcast_param(None, N)
                tool_dirs = _broadcast_param(None, N)
                tgt_dirs = _broadcast_param(None, N)
                depth_off = _broadcast_param(None, N)
                move_u = _broadcast_param(None, N)
                move_v = _broadcast_param(None, N)
                flip_xs = _broadcast_param(None, N)
                flip_zs = _broadcast_param(None, N)

                for i in range(N):
                    aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                        tools_list[i],
                        tool_planes[i],
                        tool_pts[i],
                        block_planes[i],
                        block_pts[i],
                        modes[i],
                        tool_dirs[i],
                        tgt_dirs[i],
                        depth_off[i],
                        move_u[i],
                        move_v[i],
                        flip_xs[i],
                        flip_ys[i],
                        flip_zs[i],
                        tool_rots[i],
                        block_rots[i]
                    )

                    AlignedTool.append(aligned)
                    XForm.append(xf)
                    SourcePlane.append(src_pl)
                    TargetPlane.append(tgt_pl)
                    SourcePoint.append(src_pt)
                    TargetPoint.append(tgt_pt)

                    if aligned is None:
                        DebugInfo.append("对位失败: {0}".format(dbg))
                    else:
                        DebugInfo.append(dbg)

            self.FT_AlignToolToTimber_1__AlignedTool = AlignedTool
            self.FT_AlignToolToTimber_1__XForm = XForm
            self.FT_AlignToolToTimber_1__SourcePlane = SourcePlane
            self.FT_AlignToolToTimber_1__TargetPlane = TargetPlane
            self.FT_AlignToolToTimber_1__SourcePoint = SourcePoint
            self.FT_AlignToolToTimber_1__TargetPoint = TargetPoint
            self.FT_AlignToolToTimber_1__DebugInfo = DebugInfo

            self.Log.append("[STEP3] FT_AlignToolToTimber::1 完成")
            for l in flatten_any(DebugInfo):
                self.Log.append("[STEP3][Align1] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step3 FT_AlignToolToTimber::1 出错: {}".format(e))
            self.FT_AlignToolToTimber_1__AlignedTool = []
            self.FT_AlignToolToTimber_1__XForm = []
            self.FT_AlignToolToTimber_1__SourcePlane = []
            self.FT_AlignToolToTimber_1__TargetPlane = []
            self.FT_AlignToolToTimber_1__SourcePoint = []
            self.FT_AlignToolToTimber_1__TargetPoint = []
            self.FT_AlignToolToTimber_1__DebugInfo = ["错误: {}".format(e)]

        return self

    # ==========================================================
    # Step 4：卡扣（FT_BlockCutter + FT_AlignToolToTimber::2）
    # ==========================================================
    def step4_kakou(self):
        """
        4.1 FT_BlockCutter（用 build_timber_block_uniform 构造刀具体 TimberBrep）
            length_fen = FT_BlockCutter__length_fen
            width_fen  = FT_BlockCutter__width_fen
            height_fen = FT_BlockCutter__height_fen
            base_point = 原点（允许未来输入端覆盖：FT_BlockCutter__base_point）
            reference_plane = 默认 GH XZ Plane（允许未来 DB/输入端覆盖：FT_BlockCutter__reference_plane）

        4.2 FT_AlignToolToTimber::2
            ToolGeo      = FT_BlockCutter_TimberBrep
            ToolBasePlane= FT_BlockCutter_FacePlaneList[ ToolBasePlaneIndex ]
            BlockFacePlane= Step2.FacePlaneList[ BlockFacePlaneIndex ]
            ToolBasePlaneIndex = FT_AlignToolToTimber_2__ToolBasePlane
            BlockFacePlaneIndex= FT_AlignToolToTimber_2__BlockFacePlane

            注意：索引可为标量或列表，按 GH 广播规则对齐，输出 Plane 或 Plane 列表；
                  对位调用 FTAligner.align（其它对齐参数本步未连接则按 None）。
        """
        # -------------------------
        # 4.1 FT_BlockCutter
        # -------------------------
        try:
            l_in = get_input_value("FT_BlockCutter__length_fen", None)
            w_in = get_input_value("FT_BlockCutter__width_fen", None)
            h_in = get_input_value("FT_BlockCutter__height_fen", None)

            l_raw = l_in if l_in is not None else self.all_get("FT_BlockCutter__length_fen", 32.0)
            w_raw = w_in if w_in is not None else self.all_get("FT_BlockCutter__width_fen", 32.0)
            h_raw = h_in if h_in is not None else self.all_get("FT_BlockCutter__height_fen", 20.0)

            try:
                length_fen = float(l_raw) if l_raw is not None else 32.0
                width_fen = float(w_raw) if w_raw is not None else 32.0
                height_fen = float(h_raw) if h_raw is not None else 20.0
            except Exception as e:
                self.Log.append("[STEP4][Cutter] fen 尺寸转换失败: {}，退回默认".format(e))
                length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

            bp_in = get_input_value("FT_BlockCutter__base_point", None)
            bp = coerce_point3d(bp_in, rg.Point3d(0.0, 0.0, 0.0))

            ref_mode_in = get_input_value("FT_BlockCutter__reference_plane", None)
            ref_mode = ref_mode_in if ref_mode_in is not None else self.all_get("FT_BlockCutter__reference_plane",
                                                                                "WorldXZ")
            reference_plane = make_ref_plane(ref_mode)

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

            self.FT_BlockCutter_TimberBrep = timber_brep
            self.FT_BlockCutter_FaceList = faces
            self.FT_BlockCutter_PointList = points
            self.FT_BlockCutter_EdgeList = edges
            self.FT_BlockCutter_CenterPoint = center_pt
            self.FT_BlockCutter_CenterAxisLines = center_axes
            self.FT_BlockCutter_EdgeMidPoints = edge_midpts
            self.FT_BlockCutter_FacePlaneList = face_planes
            self.FT_BlockCutter_Corner0Planes = corner0_planes
            self.FT_BlockCutter_LocalAxesPlane = local_axes_plane
            self.FT_BlockCutter_AxisX = axis_x
            self.FT_BlockCutter_AxisY = axis_y
            self.FT_BlockCutter_AxisZ = axis_z
            self.FT_BlockCutter_FaceDirTags = face_tags
            self.FT_BlockCutter_EdgeDirTags = edge_tags
            self.FT_BlockCutter_Corner0EdgeDirs = corner0_dirs
            self.FT_BlockCutter_Log = log_lines if log_lines is not None else []

            self.Log.append("[STEP4] FT_BlockCutter 完成")
            for l in flatten_any(self.FT_BlockCutter_Log):
                self.Log.append("[STEP4][Cutter] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step4 FT_BlockCutter 出错: {}".format(e))
            self.FT_BlockCutter_TimberBrep = None
            self.FT_BlockCutter_FacePlaneList = []
            self.FT_BlockCutter_Log = ["错误: {}".format(e)]

        # -------------------------
        # 4.2 FT_AlignToolToTimber::2（按索引挑选 Plane，再广播对位）
        # -------------------------
        try:
            ToolGeo = self.FT_BlockCutter_TimberBrep
            tool_face_planes = self.FT_BlockCutter_FacePlaneList
            block_face_planes = self.FacePlaneList  # 来自 Step2

            tool_idx_in = get_input_value("FT_AlignToolToTimber_2__ToolBasePlane", None)
            block_idx_in = get_input_value("FT_AlignToolToTimber_2__BlockFacePlane", None)

            tool_idx = tool_idx_in if tool_idx_in is not None else self.all_get("FT_AlignToolToTimber_2__ToolBasePlane",
                                                                                None)
            block_idx = block_idx_in if block_idx_in is not None else self.all_get(
                "FT_AlignToolToTimber_2__BlockFacePlane", None)

            # --- 将索引统一为列表，并按 GH 广播对齐 ---
            tool_idx_list = to_list(tool_idx) if isinstance(tool_idx, (list, tuple)) else [tool_idx]
            block_idx_list = to_list(block_idx) if isinstance(block_idx, (list, tuple)) else [block_idx]

            if len(tool_idx_list) == 0:
                tool_idx_list = [None]
            if len(block_idx_list) == 0:
                block_idx_list = [None]

            N = max(len(tool_idx_list), len(block_idx_list))
            if len(tool_idx_list) < N:
                tool_idx_list = tool_idx_list + [tool_idx_list[-1]] * (N - len(tool_idx_list))
            if len(block_idx_list) < N:
                block_idx_list = block_idx_list + [block_idx_list[-1]] * (N - len(block_idx_list))

            # --- 安全取 plane（支持 wrap）---
            def _pick_plane(planes, idx, wrap=True):
                if planes is None:
                    return None
                if not isinstance(planes, (list, tuple)):
                    planes = [planes]
                if len(planes) == 0:
                    return None
                if idx is None:
                    return None
                try:
                    ii = int(idx)
                except:
                    return None
                if wrap:
                    ii = ii % len(planes)
                if ii < 0 or ii >= len(planes):
                    return None
                return planes[ii]

            wrap2_in = get_input_value("FT_AlignToolToTimber_2__Wrap", None)
            wrap2 = wrap2_in if wrap2_in is not None else self.all_get("FT_AlignToolToTimber_2__Wrap", True)
            if wrap2 is None:
                wrap2 = True

            ToolBasePlane_list = []
            BlockFacePlane_list = []
            for i in range(N):
                ToolBasePlane_list.append(_pick_plane(tool_face_planes, tool_idx_list[i], wrap2))
                BlockFacePlane_list.append(_pick_plane(block_face_planes, block_idx_list[i], wrap2))

            # 若 N==1 保持标量，否则列表
            ToolBasePlane = ToolBasePlane_list[0] if N == 1 else ToolBasePlane_list
            BlockFacePlane = BlockFacePlane_list[0] if N == 1 else BlockFacePlane_list

            self.Picked_ToolBasePlanes_2 = ToolBasePlane
            self.Picked_BlockFacePlanes_2 = BlockFacePlane

            # ---- 对位广播（复用轻量 align 逻辑，未连接参数按 None）----
            def _to_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            def _param_length(val):
                if isinstance(val, (list, tuple)):
                    return len(val)
                if val is None:
                    return 0
                return 1

            def _broadcast_param(val, n):
                if isinstance(val, (list, tuple)):
                    seq = list(val)
                    l = len(seq)
                    if l == 0:
                        return [None] * n
                    if l >= n:
                        return seq[:n]
                    last = seq[-1]
                    return seq + [last] * (n - l)
                else:
                    return [val] * n

            AlignedTool = []
            XForm = []
            SourcePlane = []
            TargetPlane = []
            SourcePoint = []
            TargetPoint = []
            DebugInfo = []

            tools_raw = ToolGeo
            if tools_raw is None:
                tools_raw = []
            tools_list_base = _to_list(tools_raw)

            if len(tools_list_base) == 0 or all(t is None for t in tools_list_base):
                DebugInfo = ["ToolGeo 输入为空，未进行对位。"]
            else:
                tool_count = len(tools_list_base)

                if tool_count == 1:
                    lengths = [1]
                    lengths.append(_param_length(ToolBasePlane))
                    lengths.append(_param_length(BlockFacePlane))
                    lengths = [l for l in lengths if l > 0]
                    N2 = max(lengths) if lengths else 1
                else:
                    N2 = tool_count

                tools_list = _broadcast_param(tools_list_base, N2)
                tool_planes = _broadcast_param(ToolBasePlane, N2)
                block_planes = _broadcast_param(BlockFacePlane, N2)

                # 其余对齐参数（本步未连接）→ None
                tool_rots = _broadcast_param(None, N2)
                tool_pts = _broadcast_param(None, N2)
                block_pts = _broadcast_param(None, N2)
                modes = _broadcast_param(None, N2)
                tool_dirs = _broadcast_param(None, N2)
                tgt_dirs = _broadcast_param(None, N2)
                depth_off = _broadcast_param(None, N2)
                move_u = _broadcast_param(None, N2)
                move_v = _broadcast_param(None, N2)
                flip_xs = _broadcast_param(None, N2)
                flip_ys = _broadcast_param(None, N2)
                flip_zs = _broadcast_param(None, N2)
                tool_rots2 = _broadcast_param(None, N2)
                block_rots = _broadcast_param(None, N2)

                for i in range(N2):
                    aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                        tools_list[i],
                        tool_planes[i],
                        tool_pts[i],
                        block_planes[i],
                        block_pts[i],
                        modes[i],
                        tool_dirs[i],
                        tgt_dirs[i],
                        depth_off[i],
                        move_u[i],
                        move_v[i],
                        flip_xs[i],
                        flip_ys[i],
                        flip_zs[i],
                        tool_rots2[i],
                        block_rots[i]
                    )

                    AlignedTool.append(aligned)
                    XForm.append(xf)
                    SourcePlane.append(src_pl)
                    TargetPlane.append(tgt_pl)
                    SourcePoint.append(src_pt)
                    TargetPoint.append(tgt_pt)

                    if aligned is None:
                        DebugInfo.append("对位失败: {0}".format(dbg))
                    else:
                        DebugInfo.append(dbg)

            self.FT_AlignToolToTimber_2__AlignedTool = AlignedTool
            self.FT_AlignToolToTimber_2__XForm = XForm
            self.FT_AlignToolToTimber_2__SourcePlane = SourcePlane
            self.FT_AlignToolToTimber_2__TargetPlane = TargetPlane
            self.FT_AlignToolToTimber_2__SourcePoint = SourcePoint
            self.FT_AlignToolToTimber_2__TargetPoint = TargetPoint
            self.FT_AlignToolToTimber_2__DebugInfo = DebugInfo

            self.Log.append("[STEP4] FT_AlignToolToTimber::2 完成")
            for l in flatten_any(DebugInfo):
                self.Log.append("[STEP4][Align2] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step4 FT_AlignToolToTimber::2 出错: {}".format(e))
            self.FT_AlignToolToTimber_2__AlignedTool = []
            self.FT_AlignToolToTimber_2__XForm = []
            self.FT_AlignToolToTimber_2__SourcePlane = []
            self.FT_AlignToolToTimber_2__TargetPlane = []
            self.FT_AlignToolToTimber_2__SourcePoint = []
            self.FT_AlignToolToTimber_2__TargetPoint = []
            self.FT_AlignToolToTimber_2__DebugInfo = ["错误: {}".format(e)]

        return self

    # ==========================================================
    # Step 5：栱眼（GongYan-B + FT_AlignToolToTimber::3 + FT_CutTimberByTools）
    # ==========================================================
    def step5_gongyan_and_cut(self):
        """
        5.1 GongYan-B（FT_GongYanSection_Cai_B）
            A         : 默认原点（允许输入端 GongYan_B__A 覆盖）
            RadiusFen  : GongYan_B__RadiusFen
            LengthFen  : GongYan_B__LengthFen
            OffsetFen  : GongYan_B__OffsetFen
            ExtrudeFen : GongYan_B__ExtrudeFen（若 DB/输入端无则给默认 10.0）
            SectionPlane: 默认 GH XZ Plane（允许输入端 GongYan_B__SectionPlane 覆盖）

        5.2 FT_AlignToolToTimber::3（FT_GeoAligner.align）
            Geo        : GongYan-B.ToolBrep
            SourcePlane: GongYan-B.BridgePlane
            TargetPlane: Step2.FacePlaneList[FT_AlignToolToTimber_3__TargetPlane]
            RotateDeg  : FT_AlignToolToTimber_3__RotateDeg
            FlipX      : FT_AlignToolToTimber_3__FlipX
            MoveX      : FT_AlignToolToTimber_3__MoveX
            其余 FlipY/FlipZ/MoveY/MoveZ 如 DB/输入端存在亦可读取，否则默认 False/0

        5.3 FT_CutTimberByTools
            Timbers : Step2.TimberBrep
            Tools   : [Align1.AlignedTool, Align2.AlignedTool, Align3.MovedGeo] 合并列表
        """

        # -------------------------
        # 5.1 GongYan-B
        # -------------------------
        try:
            # 输入优先级：组件输入端 > DB > 默认
            A_in = get_input_value("GongYan_B__A", None)
            A_pt = coerce_point3d(A_in, rg.Point3d(0.0, 0.0, 0.0))

            r_in = get_input_value("GongYan_B__RadiusFen", None)
            l_in = get_input_value("GongYan_B__LengthFen", None)
            o_in = get_input_value("GongYan_B__OffsetFen", None)
            e_in = get_input_value("GongYan_B__ExtrudeFen", None)

            RadiusFen = r_in if r_in is not None else self.all_get("GongYan_B__RadiusFen", None)
            LengthFen = l_in if l_in is not None else self.all_get("GongYan_B__LengthFen", None)
            OffsetFen = o_in if o_in is not None else self.all_get("GongYan_B__OffsetFen", None)
            ExtrudeFen = e_in if e_in is not None else self.all_get("GongYan_B__ExtrudeFen", None)

            if RadiusFen is None: RadiusFen = 15.0
            if LengthFen is None: LengthFen = 10.0
            if OffsetFen is None: OffsetFen = 0.0
            if ExtrudeFen is None: ExtrudeFen = 1.0

            sp_in = get_input_value("GongYan_B__SectionPlane", None)
            SectionPlane = sp_in if sp_in is not None else make_ref_plane("WorldXZ")

            builder = FT_GongYanSection_Cai_B(
                section_plane=SectionPlane,
                A_input=A_pt,
                radius_fen=RadiusFen,
                length_fen=LengthFen,
                offset_fen=OffsetFen,
                extrude_fen=ExtrudeFen,
                doc=sc.doc
            )

            (SectionFace,
             OffsetFace,
             Points,
             OffsetPoints,
             ToolBrep,
             BridgePoints,
             BridgeMidPoints,
             BridgePlane,
             LogLines) = builder.build()

            self.GongYanB_SectionFace = SectionFace
            self.GongYanB_OffsetFace = OffsetFace
            self.GongYanB_Points = Points if Points is not None else []
            self.GongYanB_OffsetPoints = OffsetPoints if OffsetPoints is not None else []
            self.GongYanB_ToolBrep = ToolBrep
            self.GongYanB_BridgePoints = BridgePoints if BridgePoints is not None else []
            self.GongYanB_BridgeMidPoints = BridgeMidPoints if BridgeMidPoints is not None else []
            self.GongYanB_BridgePlane = BridgePlane
            self.GongYanB_Log = LogLines if LogLines is not None else []

            self.Log.append("[STEP5] GongYan-B 完成")
            for l in flatten_any(self.GongYanB_Log):
                self.Log.append("[STEP5][GongYanB] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step5 GongYan-B 出错: {}".format(e))
            self.GongYanB_ToolBrep = None
            self.GongYanB_BridgePlane = None
            self.GongYanB_Log = ["错误: {}".format(e)]

        # -------------------------
        # 5.2 FT_AlignToolToTimber::3（用 FT_GeoAligner.align）
        # -------------------------
        try:
            Geo = self.GongYanB_ToolBrep
            SourcePlane = self.GongYanB_BridgePlane

            # 取 TargetPlane 索引（可标量或列表）
            tgt_idx_in = get_input_value("FT_AlignToolToTimber_3__TargetPlane", None)
            tgt_idx = tgt_idx_in if tgt_idx_in is not None else self.all_get("FT_AlignToolToTimber_3__TargetPlane",
                                                                             None)

            # 读取变换参数（可标量或列表）
            rot_in = get_input_value("FT_AlignToolToTimber_3__RotateDeg", None)
            fx_in = get_input_value("FT_AlignToolToTimber_3__FlipX", None)
            mx_in = get_input_value("FT_AlignToolToTimber_3__MoveX", None)

            RotateDeg = rot_in if rot_in is not None else self.all_get("FT_AlignToolToTimber_3__RotateDeg", 0)
            FlipX = fx_in if fx_in is not None else self.all_get("FT_AlignToolToTimber_3__FlipX", False)
            MoveX = mx_in if mx_in is not None else self.all_get("FT_AlignToolToTimber_3__MoveX", 0)

            # 可选参数（DB 里若有就取）
            fy_in = get_input_value("FT_AlignToolToTimber_3__FlipY", None)
            fz_in = get_input_value("FT_AlignToolToTimber_3__FlipZ", None)
            my_in = get_input_value("FT_AlignToolToTimber_3__MoveY", None)
            mz_in = get_input_value("FT_AlignToolToTimber_3__MoveZ", None)

            FlipY = fy_in if fy_in is not None else self.all_get("FT_AlignToolToTimber_3__FlipY", False)
            FlipZ = fz_in if fz_in is not None else self.all_get("FT_AlignToolToTimber_3__FlipZ", False)
            MoveY = my_in if my_in is not None else self.all_get("FT_AlignToolToTimber_3__MoveY", 0)
            MoveZ = mz_in if mz_in is not None else self.all_get("FT_AlignToolToTimber_3__MoveZ", 0)

            # pick plane helper
            def _pick_plane(planes, idx, wrap=True):
                if planes is None:
                    return None
                if not isinstance(planes, (list, tuple)):
                    planes = [planes]
                if len(planes) == 0:
                    return None
                if idx is None:
                    return None
                try:
                    ii = int(idx)
                except:
                    return None
                if wrap:
                    ii = ii % len(planes)
                if ii < 0 or ii >= len(planes):
                    return None
                return planes[ii]

            wrap3_in = get_input_value("FT_AlignToolToTimber_3__Wrap", None)
            wrap3 = wrap3_in if wrap3_in is not None else self.all_get("FT_AlignToolToTimber_3__Wrap", True)
            if wrap3 is None:
                wrap3 = True
            # ---- 特殊规则：Geo(栱眼刀具)可能包含 2 个对象，需“视为一个整体”处理 ----
            #  - FlipX / RotateDeg / TargetPlane 为单值：对该整体统一应用
            #  - MoveX 允许为列表：对该整体“复制并移动”多次（每次移动后包含 2 个对象）
            geo_group = to_list(Geo) if isinstance(Geo, (list, tuple)) else [Geo]
            geo_group = [g for g in geo_group if g is not None]

            if len(geo_group) == 0:
                raise ValueError("Geo 为空，无法对位。")

            # TargetPlane：从 FacePlaneList 按索引取 Plane（允许 Wrap）
            TargetPlane = pick_plane(self.FacePlaneList, tgt_idx, wrap=wrap3)

            # 统一参数（若误传列表则取第一个，并记录提示）
            def _first_or_default(v, default=None, name="param"):
                if isinstance(v, (list, tuple)):
                    if len(v) == 0:
                        return default
                    if len(v) > 1:
                        self.Log.append(
                            "[STEP5][Align3][WARN] {} 为列表，按“整体”规则仅取第一个值：{}".format(name, v[0]))
                    return v[0]
                return v if v is not None else default

            rot_val = _first_or_default(RotateDeg, 0, "RotateDeg")
            fx_val = _first_or_default(FlipX, False, "FlipX")
            fy_val = _first_or_default(FlipY, False, "FlipY")
            fz_val = _first_or_default(FlipZ, False, "FlipZ")
            my_val = _first_or_default(MoveY, 0, "MoveY")
            mz_val = _first_or_default(MoveZ, 0, "MoveZ")

            # MoveX：允许为列表 → 多次复制移动
            mx_list = to_list(MoveX) if isinstance(MoveX, (list, tuple)) else [MoveX]
            mx_list = [0 if (m is None) else m for m in mx_list]
            if len(mx_list) == 0:
                mx_list = [0]

            src_list = []
            tgt_list = []
            moved_flat = []
            moved_groups = []
            log_lines = []

            # 复制几何（避免同一对象被多次 Transform 后“叠在一起”）
            def _dup_geo(obj):
                try:
                    if hasattr(obj, 'DuplicateBrep'):
                        return obj.DuplicateBrep()
                    if hasattr(obj, 'Duplicate'):
                        return obj.Duplicate()
                    if hasattr(obj, 'DuplicateShallow'):
                        return obj.DuplicateShallow()
                except Exception:
                    pass
                return obj

            for i, mx in enumerate(mx_list):
                moved_this = []
                src0 = None
                tgt0 = None

                for j, g in enumerate(geo_group):
                    s_out, t_out, m_geo = FT_GeoAligner.align(
                        _dup_geo(g),
                        SourcePlane,
                        TargetPlane,
                        rotate_deg=rot_val,
                        flip_x=fx_val,
                        flip_y=fy_val,
                        flip_z=fz_val,
                        move_x=mx,
                        move_y=my_val,
                        move_z=mz_val,
                    )
                    if src0 is None:
                        src0 = s_out
                    if tgt0 is None:
                        tgt0 = t_out

                    moved_this.append(m_geo)

                src_list.append(src0)
                tgt_list.append(tgt0)
                moved_groups.append(moved_this)
                moved_flat.extend(moved_this)
                log_lines.append("mx[{}]={}: ok ({} geos)".format(i, mx, len(moved_this)))

            # 输出：若仅 1 次移动且 Geo 仅 1 个对象 → 标量；否则输出扁平列表（避免 nested list）
            if len(mx_list) == 1 and len(geo_group) == 1:
                self.FT_AlignToolToTimber_3__SourceOut = src_list[0]
                self.FT_AlignToolToTimber_3__TargetOut = tgt_list[0]
                self.FT_AlignToolToTimber_3__MovedGeo = moved_flat[0] if len(moved_flat) else None
            else:
                # SourceOut/TargetOut：按 move 次数输出列表；MovedGeo：扁平列表（用于后续切削 Tools）
                self.FT_AlignToolToTimber_3__SourceOut = src_list
                self.FT_AlignToolToTimber_3__TargetOut = tgt_list
                self.FT_AlignToolToTimber_3__MovedGeo = moved_flat

            self.FT_AlignToolToTimber_3__Log = log_lines

            self.Log.append("[STEP5] FT_AlignToolToTimber::3 完成")
            for l in flatten_any(log_lines):
                self.Log.append("[STEP5][Align3] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step5 FT_AlignToolToTimber::3 出错: {}".format(e))
            self.FT_AlignToolToTimber_3__SourceOut = None
            self.FT_AlignToolToTimber_3__TargetOut = None
            self.FT_AlignToolToTimber_3__MovedGeo = None
            self.FT_AlignToolToTimber_3__Log = ["错误: {}".format(e)]

        # -------------------------
        # 5.3 FT_CutTimberByTools
        # -------------------------
        try:
            Timbers_raw = self.TimberBrep
            Timbers = coerce_brep(Timbers_raw)
            if Timbers is None:
                self.Log.append("[STEP5][Cut][ERROR] Timbers 无法转换为 Rhino.Geometry.Brep，切削跳过。")
                self.CutTimbers = Timbers_raw
                self.FailTimbers = []
                self.CutByTools_Log = ["Timbers 无法转换为 Brep，切削跳过。"]
                self.Log.append("[STEP5] FT_CutTimberByTools 完成")
                for l in flatten_any(self.CutByTools_Log):
                    self.Log.append("[STEP5][Cut] " + str(l))
                return

            tools = []
            tools.extend(flatten_any(self.FT_AlignToolToTimber_1__AlignedTool))
            tools.extend(flatten_any(self.FT_AlignToolToTimber_2__AlignedTool))
            tools.extend(flatten_any(self.FT_AlignToolToTimber_3__MovedGeo))

            tools = [t for t in tools if t is not None]

            # 强制将 Tools 转为 RhinoCommon Brep（避免 GH Goo / Proxy 导致 bbox 方法缺失）
            tools_brep = []
            for _t in tools:
                _b = coerce_brep(_t)
                if _b is not None:
                    tools_brep.append(_b)
                else:
                    self.Log.append("[STEP5][Cut][WARN] 工具无法转换为 Brep，将忽略。 type={}".format(type(_t)))

            tools = tools_brep

            _keep_inside_flag = False
            cutter = None  # 已弃用 FT_CutTimberByTools_V2：改用 RhinoCommon 布尔（等同 GH Solid Difference）

            # 若 tools 为空：不切削，直接返回原木料
            if len(tools) == 0:
                self.Log.append("[STEP5][Cut] Tools 为空：跳过切削，CutTimbers=Timbers")
                CutTimbers, FailTimbers, LogLines = Timbers, [], ["Tools 为空：跳过切削"]
            else:
                # 直接使用 RhinoCommon 的 BooleanDifference（等同 GH 的 Solid Difference）
                # 优先使用 GH 的 Solid Difference（通过 ghpythonlib.components 调用）
                CutTimbers, FailTimbers, LogLines = (None, None, [])
                try:
                    gh_cut, gh_fail, gh_log = self._cut_timbers_by_gh_solid_difference(Timbers, tools)
                    if gh_cut is not None:
                        CutTimbers = gh_cut
                        FailTimbers = gh_fail or []
                        LogLines = (gh_log or []) + ["[STEP5][Cut] 使用 GH SolidDifference 完成。"]
                    else:
                        # ghpythonlib 不可用或跳过：回退 RhinoCommon
                        CutTimbers, FailTimbers, LogLines = self._cut_timbers_by_tools_fallback(Timbers, tools)
                        LogLines = (LogLines or []) + ["[STEP5][Cut] 回退 RhinoCommon BooleanDifference 完成。"]
                except Exception as ee_gh:
                    # GH 方式异常：回退 RhinoCommon
                    try:
                        CutTimbers, FailTimbers, LogLines = self._cut_timbers_by_tools_fallback(Timbers, tools)
                        LogLines = (LogLines or []) + ["[STEP5][Cut] GH 方式异常，回退 RhinoCommon：{}".format(ee_gh)]
                    except Exception as ee:
                        # 兜底：保留原木料
                        CutTimbers, FailTimbers, LogLines = Timbers, [Timbers], ["CutFallback 异常：{}".format(ee)]
                        self.Log.append("[STEP5][Cut][ERROR] CutFallback 异常：{}，已保留原 Timbers".format(ee))
            self.CutTimbers = CutTimbers
            self.FailTimbers = FailTimbers if FailTimbers is not None else []
            self.CutByTools_Log = LogLines if LogLines is not None else []

            self.Log.append("[STEP5] FT_CutTimberByTools 完成")
            for l in flatten_any(self.CutByTools_Log):
                self.Log.append("[STEP5][Cut] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step5 FT_CutTimberByTools 出错: {}".format(e))
            # CutTimbers 保持已有
            self.CutByTools_Log = ["错误: {}".format(e)]

        return self

    # ------------------------------------------------------------------
    # Local fallback cutter (for Rhino versions without BoundingBox.Intersects)
    # ------------------------------------------------------------------

    def _cut_timbers_by_gh_solid_difference(self, Timbers, Tools):
        """
        使用 ghpythonlib.components 调用 Grasshopper 的 Solid Difference 组件进行切削。

        目的：
        - 复用 GH 内置布尔实现与容错策略，避免部分 RhinoCommon 版本/环境差异导致布尔失败。
        - 当 RhinoCommon 的 CreateBooleanDifference 不稳定时，可优先走 GH 方式。

        参数：
        - Timbers: rg.Brep 或 rg.Brep 列表（本 Solver 通常为单个）
        - Tools  : 刀具列表（可嵌套 list/tuple，会递归拍平，剔除 None）

        返回：
        - CutTimbers : list[rg.Brep]
        - FailTimbers: list[rg.Brep]
        - Log        : list[str]
        """
        log = []
        fail = []

        if ghc is None:
            log.append("[GHSolidDiff][SKIP] ghpythonlib.components 不可用，跳过 GH Solid Difference。")
            return None, None, log

        # 统一 timber 列表
        timber_list = Timbers if isinstance(Timbers, (list, tuple)) else [Timbers]
        timber_list = [t for t in timber_list if t is not None]
        if len(timber_list) == 0:
            log.append("[GHSolidDiff][ERROR] Timbers 为空。")
            return [], [], log

        # tools 扁平化
        tool_list = flatten_any(Tools)
        tool_list = [t for t in tool_list if t is not None]
        if len(tool_list) == 0:
            log.append("[GHSolidDiff][WARN] Tools 为空：不切削。")
            return timber_list, [], log

        out_all = []

        for ti, tb in enumerate(timber_list):
            try:
                res = ghc.SolidDifference(tb, tool_list)
                # 兼容：若返回元组，取第一个
                if isinstance(res, tuple) and len(res) > 0:
                    res0 = res[0]
                else:
                    res0 = res

                res_list = flatten_any(res0)
                res_list = [r for r in res_list if r is not None]

                if len(res_list) == 0:
                    log.append("[GHSolidDiff][WARN] timber#{} 差集结果为空（可能无交/布尔失败）。".format(ti))
                    fail.append(tb)
                else:
                    out_all.extend(res_list)
                    log.append("[GHSolidDiff] timber#{} -> result count={}".format(ti, len(res_list)))
            except Exception as e:
                log.append("[GHSolidDiff][ERROR] timber#{} 运行异常: {}".format(ti, e))
                fail.append(tb)

        return out_all, fail, log

    def _cut_timbers_by_tools_fallback(self, Timbers, Tools):
        """
        兼容性兜底切削：
        - 不依赖 BoundingBox.Intersects（部分 RhinoCommon 版本缺失）
        - 逐刀具对每个 timber 做 BooleanDifference
        - Tools 支持嵌套 list/tuple：会递归拍平，并尽量转为封闭 Brep
        """
        log = []
        fail = []

        tol = sc.doc.ModelAbsoluteTolerance if sc.doc else 0.001

        def _to_brep(g):
            if g is None:
                return None
            if isinstance(g, rg.Brep):
                return g
            # Extrusion / Surface / Mesh 等尝试转 Brep
            try:
                b = rg.Brep.TryConvertBrep(g)
                if b:
                    return b
            except:
                pass
            return None

        def _bbox_intersects(a, b):
            if a is None or b is None:
                return False
            bb1 = a.GetBoundingBox(True)
            bb2 = b.GetBoundingBox(True)
            # 手动 AABB 相交判断
            if bb1.Max.X < bb2.Min.X or bb2.Max.X < bb1.Min.X: return False
            if bb1.Max.Y < bb2.Min.Y or bb2.Max.Y < bb1.Min.Y: return False
            if bb1.Max.Z < bb2.Min.Z or bb2.Max.Z < bb1.Min.Z: return False
            return True

        # --- normalize timbers/tools ---
        timber_list = flatten_any(Timbers)
        tool_list_raw = flatten_any(Tools)

        tool_breps = []
        for t in tool_list_raw:
            tb = _to_brep(t)
            if tb is None:
                continue
            # 尝试封闭（避免开口 Brep 导致布尔失败）
            if not tb.IsSolid:
                try:
                    tb = tb.DuplicateBrep()
                    tb = tb.CapPlanarHoles(tol) or tb
                except:
                    pass
            tool_breps.append(tb)

        log.append("[CutFallback] 输入木料数量: {}".format(len(timber_list)))
        log.append("[CutFallback] 输入刀具数量: {}".format(len(tool_breps)))
        if len(tool_breps) == 0:
            log.append("[CutFallback][WARN] Tools 为空：直接返回 Timbers")
            return timber_list, fail, log

        result_timbers = []
        for ti, timber in enumerate(timber_list):
            tb = _to_brep(timber)
            if tb is None:
                fail.append(timber)
                log.append("[CutFallback][WARN] Timber #{} 不是 Brep，已记入 FailTimbers".format(ti))
                continue

            current_parts = [tb]
            for k, tool in enumerate(tool_breps):
                next_parts = []
                for part in current_parts:
                    if not _bbox_intersects(part, tool):
                        next_parts.append(part)
                        continue
                    try:
                        diffs = rg.Brep.CreateBooleanDifference(part, tool, tol)
                        if diffs and len(diffs) > 0:
                            next_parts.extend(list(diffs))
                        else:
                            # 布尔失败：保留原 part，并记录
                            next_parts.append(part)
                            log.append(
                                "[CutFallback][WARN] Timber#{}/Tool#{} BooleanDifference 失败：保留原件".format(ti, k))
                    except Exception as ee:
                        next_parts.append(part)
                        log.append("[CutFallback][WARN] Timber#{}/Tool#{} 异常：{}（保留原件）".format(ti, k, ee))
                current_parts = next_parts

            result_timbers.extend(current_parts)

        return result_timbers, fail, log

    # ----------------------------------------------------------
    # Step 6：闇栔增件（AnZhi + PlaneFromLists::2 + AlignToolToTimber::4）
    #   - 将 FT_AlignToolToTimber::4 的 MovedGeo 追加到 CutTimbers 列表（不做切削）
    # ----------------------------------------------------------
    def step6_anzhi_addon(self):
        try:
            self.Log.append("[STEP6] AnZhi + PlaneFromLists::2 + FT_AlignToolToTimber::4 开始")

            # ===== 6.1 AnZhi（闇栔刀具体）=====
            # 输入优先级：组件输入端（本 Solver 未暴露）> 数据库 > 默认
            qi_height = self.all_get("AnZhi__qi_height", 8.0)
            sha_width = self.all_get("AnZhi__sha_width", 4.0)
            extrude_length = self.all_get("AnZhi__extrude_length", 4.0)
            extra_height = self.all_get("AnZhi__extra_height", 2.0)
            cube_length = self.all_get("AnZhi__cube_length", None)
            pin_height = self.all_get("AnZhi__pin_height", 4.0)
            pin_width = self.all_get("AnZhi__pin_width", 2.5)
            pin_length = self.all_get("AnZhi__pin_length", 4.0)
            pin_offset = self.all_get("AnZhi__pin_offset", 6.0)
            offset_fen = self.all_get("AnZhi__offset_fen", 1.0)

            # cube_length 默认逻辑（与组件一致）
            if cube_length is None:
                cube_length = 31.0 - 4.0 - 10.0

            if self.base_point is None:
                bp = rg.Point3d(0.0, 0.0, 0.0)
            elif isinstance(self.base_point, rg.Point):
                bp = self.base_point.Location
            else:
                bp = self.base_point

            # 闇栔构建参考平面：默认 WorldXZ（GH XZ Plane）
            ref_plane = make_ref_plane("WorldXZ")

            print("+++")
            print(cube_length)

            anzhi_log = []
            builder = FT_AnZhiToolBuilder(bp, ref_plane)
            (
                tool_brep,
                cube_brep,
                pin_breps,
                an_zhi_brep,
                corner_pt,
                base_line,
                sec_plane,
                face_plane,
                cube_edge_centers,
                cube_face_planes,
                cube_vertices
            ) = builder.build_an_zhi(
                qi_height, sha_width, extrude_length, cube_length,
                extra_height, offset_fen,
                pin_height, pin_width, pin_length, pin_offset,
                anzhi_log
            )

            self.AnZhi_ToolBrep = tool_brep
            self.AnZhi_BasePoint = corner_pt
            self.AnZhi_BaseLine = base_line
            self.AnZhi_SecPlane = sec_plane
            self.AnZhi_FacePlane = face_plane
            self.AnZhi_CubeBrep = cube_brep
            self.AnZhi_PinBreps = pin_breps
            self.AnZhi_AnZhiToolBrep = an_zhi_brep
            self.AnZhi_CubeEdgeCenters = cube_edge_centers
            self.AnZhi_CubeFacePlanes = cube_face_planes
            self.AnZhi_CubeVertices = cube_vertices
            self.AnZhi_Log = anzhi_log
            self.Log.append("[STEP6] AnZhi 完成")

            print(self.AnZhi_ToolBrep)

            # ===== 6.2 PlaneFromLists::2（从 CubeEdgeCenters / CubeFacePlanes 取对位平面）=====
            idx_origin = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
            idx_plane = self.all_get("PlaneFromLists_2__IndexPlane", 0)
            wrap = bool(self.all_get("PlaneFromLists_2__Wrap", True))

            pfl2 = FTPlaneFromLists(wrap=wrap)
            PFL2_BasePlane, PFL2_OriginPoint, PFL2_ResultPlane, PFL2_Log = pfl2.build_plane(
                cube_edge_centers,
                cube_face_planes,
                idx_origin,
                idx_plane
            )

            self.PlaneFromLists_2__BasePlane = PFL2_BasePlane
            self.PlaneFromLists_2__OriginPoint = PFL2_OriginPoint
            self.PlaneFromLists_2__ResultPlane = PFL2_ResultPlane
            self.PlaneFromLists_2__Log = PFL2_Log
            self.Log.append("[STEP6] PlaneFromLists::2 完成")

            # ===== 6.3 FT_AlignToolToTimber::4（GeoAligner）=====
            # TargetPlane：与 Align3 相同的 TargetPlane 输入（从 FT_timber_block_uniform.FacePlaneList 按索引取）
            target_idx = self.all_get("FT_AlignToolToTimber_3__TargetPlane", 0)
            tgt_plane = pick_plane(self.FacePlaneList, target_idx, wrap=True)

            rot_deg = self.all_get("FT_AlignToolToTimber_4__RotateDeg", 0.0)
            flip_x = self.all_get("FT_AlignToolToTimber_4__FlipX", False)
            flip_y = self.all_get("FT_AlignToolToTimber_4__FlipY", False)
            flip_z = self.all_get("FT_AlignToolToTimber_4__FlipZ", False)
            move_x = self.all_get("FT_AlignToolToTimber_4__MoveX", 0.0)
            move_y = self.all_get("FT_AlignToolToTimber_4__MoveY", 0.0)
            move_z = self.all_get("FT_AlignToolToTimber_4__MoveZ", 0.0)

            # RotateDeg 允许列表：Geo/Plane/MoveY 为单值时，按 RotateDeg 广播
            rot_list = to_list(rot_deg) if isinstance(rot_deg, (list, tuple)) else [rot_deg]

            # 兼容：MoveY 若给了列表，仍支持，但优先以 RotateDeg 长度为主做广播
            if isinstance(move_y, (list, tuple)):
                my_list_raw = list(move_y)
                if len(my_list_raw) == 0:
                    my_list = [0.0] * len(rot_list)
                elif len(my_list_raw) == 1:
                    my_list = my_list_raw * len(rot_list)
                elif len(my_list_raw) < len(rot_list):
                    my_list = my_list_raw + [my_list_raw[-1]] * (len(rot_list) - len(my_list_raw))
                else:
                    my_list = my_list_raw[:len(rot_list)]
            else:
                my_list = [move_y] * len(rot_list)

            moved_geos = []
            src_outs = []
            tgt_outs = []

            for i, rd in enumerate(rot_list):
                # 关键：每次对位前复制几何，避免同一 Brep 被原地 Transform 导致结果重合
                geo_i = an_zhi_brep.DuplicateBrep() if hasattr(an_zhi_brep, "DuplicateBrep") else an_zhi_brep
                so, to_, mg = FT_GeoAligner.align(
                    geo_i,
                    PFL2_ResultPlane,
                    tgt_plane,
                    rotate_deg=rd,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=my_list[i],
                    move_z=move_z,
                )
                src_outs.append(so)
                tgt_outs.append(to_)
                moved_geos.append(mg)

            self.FT_AlignToolToTimber_4__SourceOut = src_outs if len(src_outs) != 1 else src_outs[0]
            self.FT_AlignToolToTimber_4__TargetOut = tgt_outs if len(tgt_outs) != 1 else tgt_outs[0]
            self.FT_AlignToolToTimber_4__MovedGeo = moved_geos
            self.FT_AlignToolToTimber_4__Log = ["[Align4] count={}".format(len(moved_geos))]

            self.Log.append("[STEP6] FT_AlignToolToTimber::4 完成")

            # ===== 6.4 追加到 CutTimbers（不裁切）=====
            if self.CutTimbers is None:
                self.CutTimbers = []
            if not isinstance(self.CutTimbers, (list, tuple)):
                self.CutTimbers = [self.CutTimbers]

            self.CutTimbers = list(self.CutTimbers) + flatten_any(moved_geos)

            self.Log.append("[STEP6] 已将 Align4.MovedGeo 追加到 CutTimbers")
            return

        except Exception as e:
            self.Log.append("[ERROR] step6 闇栔增件出错: {}".format(e))
            import traceback
            self.Log.append(traceback.format_exc())
            return

    def run(self):
        # Step 1：数据库
        self.step1_read_db()
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：原始木料
        self.step2_timber()

        # Step 3：卷杀（JuanSha + PlaneFromLists::1 + AlignToolToTimber::1）
        self.step3_juansha()

        # Step 4：卡扣（FT_BlockCutter + FT_AlignToolToTimber::2）
        self.step4_kakou()

        # Step 5：栱眼（GongYan-B + AlignToolToTimber::3）+ 合并切削
        self.step5_gongyan_and_cut()

        # Step 6：闇栔增件（AnZhi + PlaneFromLists::2 + AlignToolToTimber::4）
        self.step6_anzhi_addon()

        return self


# ==============================================================
# GhPython 组件输出绑定区
# ==============================================================

if __name__ == "__main__":

    solver = NiDaoGong_4PU_INOUT_1ChaoJuantou_Solver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出（本阶段 CutTimbers 先占位为 TimberBrep）---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # 递归拍平（避免 GH 输出嵌套 List`1[System.Object]）
    if isinstance(CutTimbers, (list, tuple)):
        CutTimbers = flatten_any(CutTimbers)
    FailTimbers = flatten_any(FailTimbers)
    Log = [str(x) for x in flatten_any(Log)]

    # --- 开发模式输出：DB ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- Step2: Timber 输出（与 FT_timber_block_uniform 命名一致）---
    TimberBrep = solver.TimberBrep
    FaceList = solver.FaceList
    PointList = solver.PointList
    EdgeList = solver.EdgeList
    CenterPoint = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    EdgeMidPoints = solver.EdgeMidPoints
    FacePlaneList = solver.FacePlaneList
    Corner0Planes = solver.Corner0Planes
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = solver.FaceDirTags
    EdgeDirTags = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs

    # --- Step3: 卷杀输出 ---
    JuanSha_ToolBrep = solver.JuanSha_ToolBrep
    JuanSha_SectionEdges = solver.JuanSha_SectionEdges
    JuanSha_HL_Intersection = solver.JuanSha_HL_Intersection
    JuanSha_HeightFacePlane = solver.JuanSha_HeightFacePlane
    JuanSha_LengthFacePlane = solver.JuanSha_LengthFacePlane
    JuanSha_Log = solver.JuanSha_Log

    PFL1_BasePlane = solver.PFL1_BasePlane
    PFL1_OriginPoint = solver.PFL1_OriginPoint
    PFL1_ResultPlane = solver.PFL1_ResultPlane
    PFL1_Log = solver.PFL1_Log

    FT_AlignToolToTimber_1__AlignedTool = flatten_any(solver.FT_AlignToolToTimber_1__AlignedTool)
    FT_AlignToolToTimber_1__XForm = solver.FT_AlignToolToTimber_1__XForm
    FT_AlignToolToTimber_1__SourcePlane = solver.FT_AlignToolToTimber_1__SourcePlane
    FT_AlignToolToTimber_1__TargetPlane = solver.FT_AlignToolToTimber_1__TargetPlane
    FT_AlignToolToTimber_1__SourcePoint = solver.FT_AlignToolToTimber_1__SourcePoint
    FT_AlignToolToTimber_1__TargetPoint = solver.FT_AlignToolToTimber_1__TargetPoint
    FT_AlignToolToTimber_1__DebugInfo = solver.FT_AlignToolToTimber_1__DebugInfo

    # --- Step4: 卡扣输出 ---
    FT_BlockCutter_TimberBrep = solver.FT_BlockCutter_TimberBrep
    FT_BlockCutter_FaceList = solver.FT_BlockCutter_FaceList
    FT_BlockCutter_PointList = solver.FT_BlockCutter_PointList
    FT_BlockCutter_EdgeList = solver.FT_BlockCutter_EdgeList
    FT_BlockCutter_CenterPoint = solver.FT_BlockCutter_CenterPoint
    FT_BlockCutter_CenterAxisLines = solver.FT_BlockCutter_CenterAxisLines
    FT_BlockCutter_EdgeMidPoints = solver.FT_BlockCutter_EdgeMidPoints
    FT_BlockCutter_FacePlaneList = solver.FT_BlockCutter_FacePlaneList
    FT_BlockCutter_Corner0Planes = solver.FT_BlockCutter_Corner0Planes
    FT_BlockCutter_LocalAxesPlane = solver.FT_BlockCutter_LocalAxesPlane
    FT_BlockCutter_AxisX = solver.FT_BlockCutter_AxisX
    FT_BlockCutter_AxisY = solver.FT_BlockCutter_AxisY
    FT_BlockCutter_AxisZ = solver.FT_BlockCutter_AxisZ
    FT_BlockCutter_FaceDirTags = solver.FT_BlockCutter_FaceDirTags
    FT_BlockCutter_EdgeDirTags = solver.FT_BlockCutter_EdgeDirTags
    FT_BlockCutter_Corner0EdgeDirs = solver.FT_BlockCutter_Corner0EdgeDirs
    FT_BlockCutter_Log = solver.FT_BlockCutter_Log

    Picked_ToolBasePlanes_2 = solver.Picked_ToolBasePlanes_2
    Picked_BlockFacePlanes_2 = solver.Picked_BlockFacePlanes_2

    FT_AlignToolToTimber_2__AlignedTool = flatten_any(solver.FT_AlignToolToTimber_2__AlignedTool)
    FT_AlignToolToTimber_2__XForm = solver.FT_AlignToolToTimber_2__XForm
    FT_AlignToolToTimber_2__SourcePlane = solver.FT_AlignToolToTimber_2__SourcePlane
    FT_AlignToolToTimber_2__TargetPlane = solver.FT_AlignToolToTimber_2__TargetPlane
    FT_AlignToolToTimber_2__SourcePoint = solver.FT_AlignToolToTimber_2__SourcePoint
    FT_AlignToolToTimber_2__TargetPoint = solver.FT_AlignToolToTimber_2__TargetPoint
    FT_AlignToolToTimber_2__DebugInfo = solver.FT_AlignToolToTimber_2__DebugInfo

    # --- Step5: 栱眼输出 ---
    GongYanB_SectionFace = solver.GongYanB_SectionFace
    GongYanB_OffsetFace = solver.GongYanB_OffsetFace
    GongYanB_Points = solver.GongYanB_Points
    GongYanB_OffsetPoints = solver.GongYanB_OffsetPoints
    GongYanB_ToolBrep = solver.GongYanB_ToolBrep
    GongYanB_BridgePoints = solver.GongYanB_BridgePoints
    GongYanB_BridgeMidPoints = solver.GongYanB_BridgeMidPoints
    GongYanB_BridgePlane = solver.GongYanB_BridgePlane
    GongYanB_Log = solver.GongYanB_Log

    FT_AlignToolToTimber_3__SourceOut = solver.FT_AlignToolToTimber_3__SourceOut
    FT_AlignToolToTimber_3__TargetOut = solver.FT_AlignToolToTimber_3__TargetOut
    FT_AlignToolToTimber_3__MovedGeo = (
        flatten_any(solver.FT_AlignToolToTimber_3__MovedGeo) if isinstance(solver.FT_AlignToolToTimber_3__MovedGeo,
                                                                           (list,
                                                                            tuple)) else solver.FT_AlignToolToTimber_3__MovedGeo)
    FT_AlignToolToTimber_3__Log = solver.FT_AlignToolToTimber_3__Log

    CutByTools_Log = solver.CutByTools_Log

    # --- Step6: 闇栔增件输出 ---
    AnZhi_ToolBrep = solver.AnZhi_ToolBrep
    AnZhi_BasePoint = solver.AnZhi_BasePoint
    AnZhi_BaseLine = solver.AnZhi_BaseLine
    AnZhi_SecPlane = solver.AnZhi_SecPlane
    AnZhi_FacePlane = solver.AnZhi_FacePlane
    AnZhi_CubeBrep = solver.AnZhi_CubeBrep
    AnZhi_PinBreps = solver.AnZhi_PinBreps
    AnZhi_AnZhiToolBrep = solver.AnZhi_AnZhiToolBrep
    AnZhi_CubeEdgeCenters = solver.AnZhi_CubeEdgeCenters
    AnZhi_CubeFacePlanes = solver.AnZhi_CubeFacePlanes
    AnZhi_CubeVertices = solver.AnZhi_CubeVertices
    AnZhi_Log = solver.AnZhi_Log

    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    FT_AlignToolToTimber_4__SourceOut = solver.FT_AlignToolToTimber_4__SourceOut
    FT_AlignToolToTimber_4__TargetOut = solver.FT_AlignToolToTimber_4__TargetOut
    FT_AlignToolToTimber_4__MovedGeo = (
        flatten_any(solver.FT_AlignToolToTimber_4__MovedGeo) if isinstance(solver.FT_AlignToolToTimber_4__MovedGeo,
                                                                           (list,
                                                                            tuple)) else solver.FT_AlignToolToTimber_4__MovedGeo)
    FT_AlignToolToTimber_4__Log = solver.FT_AlignToolToTimber_4__Log


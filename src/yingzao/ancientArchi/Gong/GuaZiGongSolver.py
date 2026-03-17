# -*- coding: utf-8 -*-
"""
LingGongSolver · Step 1 + Step 2 + Step 3（卷殺，多索引 PF1，多位置对位）
               + Step 4（BlockCutter）
               + Step 5（栱眼：FT_GongYanSection_Cai + PF2 + Align3 + CutTimberByTools）

功能概述：
1) 读取数据库 DG_Dou / type_code = Linggong / params_json
2) 调用 build_timber_block_uniform 构建原始木料块
   - length_fen  = FT_timber_block_uniform__length_fen
   - width_fen   = FT_timber_block_uniform__width_fen
   - height_fen  = FT_timber_block_uniform__height_fen
   - base_point  = 组件输入端 base_point（若 None → 原点）
   - reference_plane：
       * 默认 XZ 平面：X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
       * 可通过 DB 中 FT_timber_block_uniform__reference_plane 决定
3) 卷殺部分（Step 3）：
   3.1 JuanShaToolBuilder 构建卷杀刀具
       - HeightFen      = JuanShaToolBuilder__HeightFen
       - LengthFen      = JuanShaToolBuilder__LengthFen
       - ThicknessFen   = JuanShaToolBuilder__ThicknessFen
       - DivCount       = JuanShaToolBuilder__DivCount
       - SectionPlane   = GH XZ Plane（原点）
       - PositionPoint  = 世界原点
   3.2 PlaneFromLists::1
       - OriginPoints = EdgeMidPoints
       - BasePlanes   = Corner0Planes
       - IndexOrigin  = PlaneFromLists_1__IndexOrigin（可为列表）
       - IndexPlane   = PlaneFromLists_1__IndexPlane（可为列表）
       - Wrap         = PlaneFromLists_1__wrap（默认 True）
       - 支持多对索引：输出多个 ResultPlane / BasePlane / OriginPoint（列表）
   3.3 FT_AlignToolToTimber::1（多位置对位）
       - ToolGeo        = JuanShaToolBuilder.ToolBrep（广播）
       - ToolBasePlane  = JuanShaToolBuilder.HeightFacePlane（广播）
       - BlockFacePlane = PF1_ResultPlane 中的所有平面
       - BlockRotDeg    = FT_AlignToolToTimber_1__BlockRotDeg（标量 → 广播；列表 → 一一对应）
       - FlipY          = FT_AlignToolToTimber_1__FlipY（同上）
       其余参数当前统一使用标量默认值并广播
4) BlockCutter 部分（Step 4）：
   4.1 FT_BlockCutter
       - length_fen      = FT_BlockCutter__length_fen
       - width_fen       = FT_BlockCutter__width_fen
       - height_fen      = FT_BlockCutter__height_fen
       - base_point      = FT_BlockCutter__base_point（若无 → 原点）
       - reference_plane = FT_BlockCutter__reference_plane（若无 → WorldXZ）
   4.2 FT_AlignToolToTimber::2
       - ToolGeo        = FT_BlockCutter.TimberBrep
       - ToolBasePlane  = FT_BlockCutter.FacePlaneList[ FT_AlignToolToTimber_2__ToolBasePlane ]
       - BlockFacePlane = 主木坯 FacePlaneList[ FT_AlignToolToTimber_2__BlockFacePlane ]
       - FlipX / FlipY / FlipZ = FT_AlignToolToTimber_2__FlipX / FlipY / FlipZ
       其余参数使用默认值 0 / None
5) 栱眼部分（Step 5）：
   5.1 FT_GongYanSection_Cai（FT_GongYanSectionABFEA）
       - SectionPlane     = FT_GongYanSection_Cai__SectionPlane（WorldXY/XZ/YZ → 平面）
       - A                = 原点 (0,0,0)
       - RadiusFen        = FT_GongYanSection_Cai__RadiusFen
       - LengthFen        = FT_GongYanSection_Cai__LengthFen
       - InnerRadiusFen   = FT_GongYanSection_Cai__InnerRadiusFen
       - MoveFen          = FT_GongYanSection_Cai__MoveFen
   5.2 PlaneFromLists::2（PF2）
       - OriginPoints = EdgeMidPoints
       - BasePlanes   = Corner0Planes
       - IndexOrigin  = PlaneFromLists_2__IndexOrigin（可列表）
       - IndexPlane   = PlaneFromLists_2__IndexPlane（可列表）
       - Wrap         = PlaneFromLists_2__wrap
   5.3 FT_AlignToolToTimber::3（多位置对位）
       - ToolGeo        = FT_GongYanSection_Cai.ToolBrep
       - ToolBasePlane  = [TopPlaneB, TopPlaneA] （作为列表参与广播）
       - BlockFacePlane = PF2_ResultPlane
       - BlockRotDeg    = FT_AlignToolToTimber_3__BlockRotDeg
       - FlipZ          = FT_AlignToolToTimber_3__FlipZ
       - MoveU          = FT_AlignToolToTimber_3__MoveU
   5.4 FT_CutTimberByTools
       - Timbers = 主木坯 TimberBrep
       - Tools   = [Align1_AlignedTool, Align2_AlignedTool, Align3_AlignedTool] 展平成一维刀具列表
       - 输出 CutTimbers, FailTimbers 为最终构件几何

输入：
    DBPath     : str       - SQLite 数据库路径
    base_point : Point3d   - 木料定位点
    Refresh    : bool      - 手动刷新（预留，本步未用特殊逻辑）

输出：
    CutTimbers      : list[Breps]
    FailTimbers     : list[Breps]
    Log             : list[str]   —— 全局日志

    # 开发模式输出（方便调试内部状态）
    Value           : 任意
    All             : list[tuple]
    AllDict         : dict
    DBLog           : list[str]

    TimberBrep      : Brep
    FaceList        : list[Breps]
    PointList       : list[Point3d]
    EdgeList        : list[Curves]
    CenterPoint     : Point3d
    CenterAxisLines : list[Curves]
    EdgeMidPoints   : list[Point3d]
    FacePlaneList   : list[Plane]
    Corner0Planes   : list[Plane]
    LocalAxesPlane  : Plane
    AxisX           : Vector3d
    AxisY           : Vector3d
    AxisZ           : Vector3d
    FaceDirTags     : list
    EdgeDirTags     : list
    Corner0EdgeDirs : list

    # Step3: JuanShaToolBuilder 输出
    JuanShaToolBrep         : Brep
    JuanShaSectionEdges     : list
    JuanShaHL_Intersection  : list
    JuanShaHeightFacePlane  : Plane
    JuanShaLengthFacePlane  : Plane
    JuanShaLog              : list[str]

    # Step3: PlaneFromLists::1 输出（多值）
    PF1_BasePlane           : list[Plane]
    PF1_OriginPoint         : list[rg.Point3d]
    PF1_ResultPlane         : list[Plane]
    PF1_Log                 : list[str]

    # Step3: FT_AlignToolToTimber::1 输出（多位置）
    Align1_AlignedTool      : list[Breps]
    Align1_XForm            : list[rg.Transform]
    Align1_SourcePlane      : list[Plane]
    Align1_TargetPlane      : list[Plane]
    Align1_SourcePoint      : list[rg.Point3d]
    Align1_TargetPoint      : list[rg.Point3d]
    Align1_DebugInfo        : list[str]

    # Step4: FT_BlockCutter 输出
    BlockCutter_TimberBrep      : Brep
    BlockCutter_FaceList        : list[Breps]
    BlockCutter_PointList       : list[Point3d]
    BlockCutter_EdgeList        : list[Curves]
    BlockCutter_CenterPoint     : Point3d
    BlockCutter_CenterAxisLines : list[Curves]
    BlockCutter_EdgeMidPoints   : list[Point3d]
    BlockCutter_FacePlaneList   : list[Plane]
    BlockCutter_Corner0Planes   : list[Plane]
    BlockCutter_LocalAxesPlane  : Plane
    BlockCutter_AxisX           : Vector3d
    BlockCutter_AxisY           : Vector3d
    BlockCutter_AxisZ           : Vector3d
    BlockCutter_FaceDirTags     : list
    BlockCutter_EdgeDirTags     : list
    BlockCutter_Corner0EdgeDirs : list
    BlockCutter_Log             : list[str]

    # Step4: FT_AlignToolToTimber::2 输出
    Align2_AlignedTool      : Brep
    Align2_XForm            : rg.Transform
    Align2_SourcePlane      : rg.Plane
    Align2_TargetPlane      : rg.Plane
    Align2_SourcePoint      : rg.Point3d
    Align2_TargetPoint      : rg.Point3d
    Align2_DebugInfo        : list[str]

    # Step5: FT_GongYanSection_Cai 输出
    GongSectionFace         : Brep
    GongPoints              : list
    GongInnerSection        : object
    GongInnerSectionMoved   : object
    GongInnerPoints         : list
    GongLoftFace            : Brep
    GongTopFace             : Brep
    GongToolBrep            : Brep
    GongTopPlaneA           : Plane
    GongTopPlaneB           : Plane
    GongLog                 : list[str]

    # Step5: PlaneFromLists::2 输出
    PF2_BasePlane           : list[Plane]
    PF2_OriginPoint         : list[rg.Point3d]
    PF2_ResultPlane         : list[Plane]
    PF2_Log                 : list[str]

    # Step5: FT_AlignToolToTimber::3 输出
    Align3_AlignedTool      : list[Breps]
    Align3_XForm            : list[rg.Transform]
    Align3_SourcePlane      : list[Plane]
    Align3_TargetPlane      : list[Plane]
    Align3_SourcePoint      : list[rg.Point3d]
    Align3_TargetPoint      : list[rg.Point3d]
    Align3_DebugInfo        : list[str]

    # Step5: FT_CutTimberByTools 日志
    CutByToolsLog           : list[str]
"""

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    JuanShaToolBuilder,
    FTPlaneFromLists,
    FTAligner,
    FT_GongYanSectionABFEA,
    FT_CutTimberByTools,
)


# ==============================================================
# 通用工具函数
# ==============================================================

def to_list(x):
    """若为列表则直接返回，否则包装成长度为1的列表。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def all_to_dict(all_list):
    """
    All = [
        ('FT_timber_block_uniform__length_fen', 72),
        ('FT_timber_block_uniform__width_fen',  10),
        ...
    ]
    → {'FT_timber_block_uniform__length_fen': 72, ...}
    """
    d = {}
    if all_list is None:
        return d
    for item in all_list:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        key, value = item
        d[key] = value
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

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    # 由 Plane 构造自动得到 Z = X × Y = (0,-1,0)
    return rg.Plane(origin, x, y)


def first_or_default(v, default=None):
    """若 v 为 list/tuple，则取第一个；否则直接返回；None → default。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        if len(v) == 0:
            return default
        return v[0]
    return v


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其它标量 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


def _broadcast_param(val, n, name="param"):
    """
    广播/截断参数到长度 n：

    - 若 val 为列表/元组：
        * len == 0 : 返回 [None] * n
        * 0 < len < n : 用“最后一个值”补齐到 n
        * len >= n : 只取前 n 个
    - 若 val 为标量：
        * 返回 [val] * n
    """
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


# ==============================================================
# 主 Solver 类 —— 令栱 LingGongSolver
# ==============================================================

class GuaZiGongSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        # 输入缓存
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1：数据库读取相关成员
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志
        self.Log = []

        # Step 2：木坯几何输出成员（与组件命名保持一致）
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

        # Step 3：卷殺相关成员
        # 3.1 JuanShaToolBuilder
        self.JuanShaToolBrep = None
        self.JuanShaSectionEdges = []
        self.JuanShaHL_Intersection = []
        self.JuanShaHeightFacePlane = None
        self.JuanShaLengthFacePlane = None
        self.JuanShaLog = []

        # 3.2 PlaneFromLists::1（支持多对索引 → 多个平面）
        self.PF1_BasePlane = []      # list[Plane]
        self.PF1_OriginPoint = []    # list[Point3d]
        self.PF1_ResultPlane = []    # list[Plane]
        self.PF1_Log = []            # list[str]

        # 3.3 FT_AlignToolToTimber::1（多位置对位）
        self.Align1_AlignedTool = []   # list[Breps]
        self.Align1_XForm = []         # list[Transform]
        self.Align1_SourcePlane = []   # list[Plane]
        self.Align1_TargetPlane = []   # list[Plane]
        self.Align1_SourcePoint = []   # list[Point3d]
        self.Align1_TargetPoint = []   # list[Point3d]
        self.Align1_DebugInfo = []     # list[str]

        # Step 4：BlockCutter + Align2
        # 4.1 FT_BlockCutter 几何
        self.BlockCutter_TimberBrep = None
        self.BlockCutter_FaceList = []
        self.BlockCutter_PointList = []
        self.BlockCutter_EdgeList = []
        self.BlockCutter_CenterPoint = None
        self.BlockCutter_CenterAxisLines = []
        self.BlockCutter_EdgeMidPoints = []
        self.BlockCutter_FacePlaneList = []
        self.BlockCutter_Corner0Planes = []
        self.BlockCutter_LocalAxesPlane = None
        self.BlockCutter_AxisX = None
        self.BlockCutter_AxisY = None
        self.BlockCutter_AxisZ = None
        self.BlockCutter_FaceDirTags = []
        self.BlockCutter_EdgeDirTags = []
        self.BlockCutter_Corner0EdgeDirs = []
        self.BlockCutter_Log = []

        # 4.2 FT_AlignToolToTimber::2
        self.Align2_AlignedTool = None
        self.Align2_XForm = None
        self.Align2_SourcePlane = None
        self.Align2_TargetPlane = None
        self.Align2_SourcePoint = None
        self.Align2_TargetPoint = None
        self.Align2_DebugInfo = []

        # Step 5：栱眼 + PF2 + Align3 + Cut
        # 5.1 FT_GongYanSection_Cai
        self.GongSectionFace       = None
        self.GongPoints            = []
        self.GongInnerSection      = None
        self.GongInnerSectionMoved = None
        self.GongInnerPoints       = []
        self.GongLoftFace          = None
        self.GongTopFace           = None
        self.GongToolBrep          = None
        self.GongTopPlaneA         = None
        self.GongTopPlaneB         = None
        self.GongLog               = []

        # 5.2 PlaneFromLists::2
        self.PF2_BasePlane   = []
        self.PF2_OriginPoint = []
        self.PF2_ResultPlane = []
        self.PF2_Log         = []

        # 5.3 FT_AlignToolToTimber::3
        self.Align3_AlignedTool = []
        self.Align3_XForm       = []
        self.Align3_SourcePlane = []
        self.Align3_TargetPlane = []
        self.Align3_SourcePoint = []
        self.Align3_TargetPoint = []
        self.Align3_DebugInfo   = []

        # 5.4 FT_CutTimberByTools
        self.CutByToolsLog = []

        # 最终 Cut 结果
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：从 AllDict 中取值
    # ------------------------------------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict[key]
        # 若是长度为 1 的列表/元组，则解包
        if isinstance(v, (list, tuple)):
            if len(v) == 0:
                return default
            if len(v) == 1:
                return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        读取 DG_Dou / type_code = Linggong / params_json
        并构造 AllDict
        """
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="GuaZiGong",   # 令栱在表中的 type_code
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成")
            for l in self.DBLog:
                self.Log.append("[DB] " + l)

            # All → dict，供后续所有步骤按键名取值
            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ------------------------------------------------------
    def step2_timber(self):
        """
        调用 build_timber_block_uniform 构建主木坯。
        参数优先级：组件输入 > 数据库 > 默认值
        目前 length/width/height 只来自数据库/默认值，
        base_point 来自组件输入端。
        """
        # --- 1) fen 尺寸：来自 AllDict 或默认 ---
        length_raw = self.all_get("FT_timber_block_uniform__length_fen", 32.0)
        width_raw = self.all_get("FT_timber_block_uniform__width_fen", 32.0)
        height_raw = self.all_get("FT_timber_block_uniform__height_fen", 20.0)

        try:
            length_fen = float(length_raw)
            width_fen = float(width_raw)
            height_fen = float(height_raw)
        except Exception as e:
            self.Log.append("[TIMBER] fen 尺寸转换 float 出错: {}, 使用默认值".format(e))
            length_fen = 32.0
            width_fen = 32.0
            height_fen = 20.0

        # --- 2) 参考平面：DB 或默认 XZ ---
        ref_mode = self.all_get("FT_timber_block_uniform__reference_plane", "WorldXZ")
        reference_plane = make_ref_plane(ref_mode)
        self.Log.append("[TIMBER] reference_plane 模式 = {}".format(ref_mode))

        # --- 3) base_point：组件输入端; None → 原点 ---
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location
        elif isinstance(bp, rg.Point3d):
            pass
        else:
            # 尝试从 (x,y,z) 或其他结构转换
            try:
                bp = rg.Point3d(bp.X, bp.Y, bp.Z)
            except:
                bp = rg.Point3d(0.0, 0.0, 0.0)
                self.Log.append("[TIMBER] base_point 类型无法识别，已退回原点。")

        # --- 4) 调用库函数构建木坯 ---
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

            # 写入成员
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
            for l in log_lines:
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            # 出错时清空几何，写入日志
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

            self.Log.append("[ERROR] step2_timber 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3：卷殺部分
    #   3.1 JuanShaToolBuilder
    #   3.2 PlaneFromLists::1（多索引）
    #   3.3 FT_AlignToolToTimber::1（多位置对位）
    # ------------------------------------------------------
    def step3_juansha(self):

        # ========== 3.1 JuanShaToolBuilder ==========

        # 从 DB 取参数（若 DB 没写就给个保底默认）
        h_raw = self.all_get("JuanShaToolBuilder__HeightFen", 8.0)
        l_raw = self.all_get("JuanShaToolBuilder__LengthFen", 20.0)
        t_raw = self.all_get("JuanShaToolBuilder__ThicknessFen", 2.0)
        d_raw = self.all_get("JuanShaToolBuilder__DivCount", 8)

        try:
            height_fen = float(h_raw)
            length_fen = float(l_raw)
            thickness_fen = float(t_raw)
            div_count = int(d_raw)
        except Exception as e:
            self.Log.append("[JUANSHA] 参数转换失败，使用默认值: {}".format(e))
            height_fen = 8.0
            length_fen = 20.0
            thickness_fen = 2.0
            div_count = 8

        # SectionPlane 为 GH XZ Plane，PositionPoint 为原点
        juansha_section_plane = make_ref_plane("WorldXZ")
        juansha_position_point = rg.Point3d(0.0, 0.0, 0.0)

        try:
            builder = JuanShaToolBuilder(
                height_fen=height_fen,
                length_fen=length_fen,
                thickness_fen=thickness_fen,
                div_count=div_count,
                section_plane=juansha_section_plane,
                position_point=juansha_position_point
            )

            (
                tool_brep,
                section_edges,
                hl_intersection,
                height_face_plane,
                length_face_plane,
                log_lines
            ) = builder.build()

            self.JuanShaToolBrep = tool_brep
            self.JuanShaSectionEdges = section_edges
            self.JuanShaHL_Intersection = hl_intersection
            self.JuanShaHeightFacePlane = height_face_plane
            self.JuanShaLengthFacePlane = length_face_plane
            self.JuanShaLog = log_lines

            self.Log.append("[JUANSHA] JuanShaToolBuilder.build 完成")
            for l in log_lines:
                self.Log.append("[JUANSHA] " + str(l))

        except Exception as e:
            self.JuanShaToolBrep = None
            self.JuanShaSectionEdges = []
            self.JuanShaHL_Intersection = []
            self.JuanShaHeightFacePlane = None
            self.JuanShaLengthFacePlane = None
            self.JuanShaLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] JuanShaToolBuilder.build 出错: {}".format(e))
            # 没有刀具就没法继续对位，直接返回
            return self

        # ========== 3.2 PlaneFromLists::1（支持多个索引） ==========

        if not self.EdgeMidPoints or not self.Corner0Planes:
            self.Log.append("[PF1] EdgeMidPoints 或 Corner0Planes 为空，跳过 PlaneFromLists::1")
            return self

        idx_origin_raw = self.all_get("PlaneFromLists_1__IndexOrigin", 0)
        idx_plane_raw  = self.all_get("PlaneFromLists_1__IndexPlane", 0)
        wrap_raw       = self.all_get("PlaneFromLists_1__wrap", True)

        # 确保是列表，方便多次调用
        idx_origin_list = to_list(idx_origin_raw)
        idx_plane_list  = to_list(idx_plane_raw)

        # 简单广播：长度不一致时，用最后一个值补齐
        n_orig = len(idx_origin_list)
        n_pl   = len(idx_plane_list)
        n      = max(n_orig, n_pl, 1)

        def _broadcast_idx(seq, n):
            if len(seq) == 0:
                return [0] * n
            if len(seq) >= n:
                return list(seq)[:n]
            last = seq[-1]
            return list(seq) + [last] * (n - len(seq))

        try:
            idx_origin_list = [int(i) for i in _broadcast_idx(idx_origin_list, n)]
            idx_plane_list  = [int(i) for i in _broadcast_idx(idx_plane_list,  n)]
        except Exception as e:
            self.Log.append("[PF1] IndexOrigin/IndexPlane 转换失败: {}，使用单一 0".format(e))
            idx_origin_list = [0]
            idx_plane_list  = [0]
            n = 1

        Wrap = bool(wrap_raw)

        # 清空旧值，准备写入多个结果
        self.PF1_BasePlane   = []
        self.PF1_OriginPoint = []
        self.PF1_ResultPlane = []
        self.PF1_Log         = []

        try:
            pf_builder = FTPlaneFromLists(wrap=Wrap)

            for i in range(n):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]

                base_plane, origin_point, result_plane, pf_log = pf_builder.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip
                )

                self.PF1_BasePlane.append(base_plane)
                self.PF1_OriginPoint.append(origin_point)
                self.PF1_ResultPlane.append(result_plane)

                # 日志附带索引信息
                self.PF1_Log.extend(["[{}] {}".format(i, str(l)) for l in pf_log])

            self.Log.append(
                "[PF1] FTPlaneFromLists.build_plane 完成，共 {} 组索引".format(n)
            )

        except Exception as e:
            self.PF1_BasePlane   = []
            self.PF1_OriginPoint = []
            self.PF1_ResultPlane = []
            self.PF1_Log         = ["错误: {}".format(e)]
            self.Log.append("[ERROR] FTPlaneFromLists.build_plane 出错: {}".format(e))
            return self

        # ========== 3.3 FT_AlignToolToTimber::1（多位置对位） ==========

        # 多位置：以 PF1_ResultPlane 的长度为基准
        block_planes = to_list(self.PF1_ResultPlane)
        if len(block_planes) == 0:
            self.Align1_DebugInfo = ["PF1_ResultPlane 为空，无法对位。"]
            self.Log.append("[ALIGN1] PF1_ResultPlane 为空，跳过对位。")
            return self

        N = len(block_planes)

        # 从 DB 取 BlockRotDeg / FlipY（可能是标量或列表）
        block_rot_raw = self.all_get("FT_AlignToolToTimber_1__BlockRotDeg", 0.0)
        flip_y_raw    = self.all_get("FT_AlignToolToTimber_1__FlipY", 0)

        # 广播所有参数到 N
        tool_geo_list        = _broadcast_param(self.JuanShaToolBrep,        N, "ToolGeo")
        tool_base_plane_list = _broadcast_param(self.JuanShaHeightFacePlane, N, "ToolBasePlane")
        block_face_plane_list= _broadcast_param(block_planes,                N, "BlockFacePlane")
        block_rot_list       = _broadcast_param(block_rot_raw,               N, "BlockRotDeg")
        flip_y_list          = _broadcast_param(flip_y_raw,                  N, "FlipY")

        # 其他参数当前统一标量默认，并广播
        tool_contact_point_list = _broadcast_param(None, N, "ToolContactPoint")
        block_target_point_list = _broadcast_param(None, N, "BlockTargetPoint")
        mode_list               = _broadcast_param(0,    N, "Mode")
        tool_dir_list           = _broadcast_param(None, N, "ToolDir")
        target_dir_list         = _broadcast_param(None, N, "TargetDir")
        depth_offset_list       = _broadcast_param(0.0,  N, "DepthOffset")
        move_u_list             = _broadcast_param(0.0,  N, "MoveU")
        move_v_list             = _broadcast_param(0.0,  N, "MoveV")
        flip_x_list             = _broadcast_param(0,    N, "FlipX")
        flip_z_list             = _broadcast_param(0,    N, "FlipZ")
        tool_rot_deg_list       = _broadcast_param(0.0,  N, "ToolRotDeg")

        # 清空旧对位结果
        self.Align1_AlignedTool = []
        self.Align1_XForm       = []
        self.Align1_SourcePlane = []
        self.Align1_TargetPlane = []
        self.Align1_SourcePoint = []
        self.Align1_TargetPoint = []
        self.Align1_DebugInfo   = []

        for i in range(N):
            tool_geo        = tool_geo_list[i]
            tool_base_plane = tool_base_plane_list[i]
            block_face_plane= block_face_plane_list[i]

            if tool_geo is None or tool_base_plane is None or block_face_plane is None:
                msg = "[ALIGN1][{}] 参数缺失，跳过对位。".format(i)
                self.Align1_AlignedTool.append(None)
                self.Align1_XForm.append(None)
                self.Align1_SourcePlane.append(None)
                self.Align1_TargetPlane.append(None)
                self.Align1_SourcePoint.append(None)
                self.Align1_TargetPoint.append(None)
                self.Align1_DebugInfo.append(msg)
                self.Log.append(msg)
                continue

            block_rot_deg = float(block_rot_list[i]) if block_rot_list[i] is not None else 0.0
            flip_y        = int(flip_y_list[i]) if flip_y_list[i] is not None else 0

            try:
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tool_geo,
                    tool_base_plane,
                    tool_contact_point_list[i],
                    block_face_plane,
                    block_target_point_list[i],
                    mode_list[i],
                    tool_dir_list[i],
                    target_dir_list[i],
                    depth_offset_list[i],
                    move_u_list[i],
                    move_v_list[i],
                    flip_x_list[i],
                    flip_y,
                    flip_z_list[i],
                    tool_rot_deg_list[i],
                    block_rot_deg
                )

                self.Align1_AlignedTool.append(aligned)
                self.Align1_XForm.append(xf)
                self.Align1_SourcePlane.append(src_pl)
                self.Align1_TargetPlane.append(tgt_pl)
                self.Align1_SourcePoint.append(src_pt)
                self.Align1_TargetPoint.append(tgt_pt)

                if aligned is None:
                    msg = "[ALIGN1][{}] 对位失败: {}".format(i, dbg)
                    self.Align1_DebugInfo.append(msg)
                    self.Log.append(msg)
                else:
                    msg = "[ALIGN1][{}] 对位完成 BlockRotDeg={}, FlipY={}".format(i, block_rot_deg, flip_y)
                    self.Align1_DebugInfo.append(dbg)
                    self.Log.append(msg)

            except Exception as e:
                msg = "[ERROR][ALIGN1][{}] FTAligner.align 出错: {}".format(i, e)
                self.Align1_AlignedTool.append(None)
                self.Align1_XForm.append(None)
                self.Align1_SourcePlane.append(None)
                self.Align1_TargetPlane.append(None)
                self.Align1_SourcePoint.append(None)
                self.Align1_TargetPoint.append(None)
                self.Align1_DebugInfo.append(msg)
                self.Log.append(msg)

        return self

    # ------------------------------------------------------
    # Step 4：BlockCutter + AlignToolToTimber::2
    # ------------------------------------------------------
    def step4_block_cutter(self):
        """
        4.1 使用 build_timber_block_uniform 构建 BlockCutter 木块
        4.2 用 FT_AlignToolToTimber::2 将 BlockCutter 对位到主木坯指定面
        """

        # ---------------- 4.1 FT_BlockCutter ----------------
        # 尺寸
        bc_len_raw = self.all_get("FT_BlockCutter__length_fen", 32.0)
        bc_wid_raw = self.all_get("FT_BlockCutter__width_fen", 32.0)
        bc_hei_raw = self.all_get("FT_BlockCutter__height_fen", 20.0)

        try:
            bc_length_fen = float(bc_len_raw)
            bc_width_fen  = float(bc_wid_raw)
            bc_height_fen = float(bc_hei_raw)
        except Exception as e:
            self.Log.append("[BLOCK] fen 尺寸转换失败，使用默认值: {}".format(e))
            bc_length_fen = 32.0
            bc_width_fen  = 32.0
            bc_height_fen = 20.0

        # base_point：来自 DB；若无 → 原点
        bp_raw = self.all_get("FT_BlockCutter__base_point", [0.0, 0.0, 0.0])
        if isinstance(bp_raw, rg.Point3d):
            bc_base_point = bp_raw
        elif isinstance(bp_raw, rg.Point):
            bc_base_point = bp_raw.Location
        elif isinstance(bp_raw, (list, tuple)) and len(bp_raw) >= 3:
            try:
                bc_base_point = rg.Point3d(float(bp_raw[0]), float(bp_raw[1]), float(bp_raw[2]))
            except:
                bc_base_point = rg.Point3d(0.0, 0.0, 0.0)
        else:
            bc_base_point = rg.Point3d(0.0, 0.0, 0.0)

        # 参考平面
        bc_ref_mode = self.all_get("FT_BlockCutter__reference_plane", "WorldXZ")
        bc_reference_plane = make_ref_plane(bc_ref_mode)

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
                bc_length_fen,
                bc_width_fen,
                bc_height_fen,
                bc_base_point,
                bc_reference_plane,
            )

            self.BlockCutter_TimberBrep      = timber_brep
            self.BlockCutter_FaceList        = faces
            self.BlockCutter_PointList       = points
            self.BlockCutter_EdgeList        = edges
            self.BlockCutter_CenterPoint     = center_pt
            self.BlockCutter_CenterAxisLines = center_axes
            self.BlockCutter_EdgeMidPoints   = edge_midpts
            self.BlockCutter_FacePlaneList   = face_planes
            self.BlockCutter_Corner0Planes   = corner0_planes
            self.BlockCutter_LocalAxesPlane  = local_axes_plane
            self.BlockCutter_AxisX           = axis_x
            self.BlockCutter_AxisY           = axis_y
            self.BlockCutter_AxisZ           = axis_z
            self.BlockCutter_FaceDirTags     = face_tags
            self.BlockCutter_EdgeDirTags     = edge_tags
            self.BlockCutter_Corner0EdgeDirs = corner0_dirs
            self.BlockCutter_Log             = log_lines

            self.Log.append("[BLOCK] FT_BlockCutter 木块构建完成，length={} width={} height={}".format(
                bc_length_fen, bc_width_fen, bc_height_fen))

        except Exception as e:
            # 出错时清空 Cutter 几何
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
            self.Log.append("[ERROR] FT_BlockCutter 构建出错: {}".format(e))
            return self

        # ---------------- 4.2 FT_AlignToolToTimber::2 ----------------
        if self.BlockCutter_TimberBrep is None or not self.BlockCutter_FacePlaneList or not self.FacePlaneList:
            self.Align2_DebugInfo = ["BlockCutter 或主木坯面为空，跳过 Align2 对位。"]
            self.Log.append("[ALIGN2] BlockCutter 或主木坯面为空，跳过对位。")
            return self

        # 索引参数：ToolBasePlane / BlockFacePlane
        tb_idx_raw = self.all_get("FT_AlignToolToTimber_2__ToolBasePlane", 0)
        bf_idx_raw = self.all_get("FT_AlignToolToTimber_2__BlockFacePlane", 0)
        try:
            tb_idx = int(tb_idx_raw)
        except:
            tb_idx = 0
        try:
            bf_idx = int(bf_idx_raw)
        except:
            bf_idx = 0

        # 从 FacePlaneList 中安全取值
        if tb_idx < 0 or tb_idx >= len(self.BlockCutter_FacePlaneList):
            tb_idx = 0
        if bf_idx < 0 or bf_idx >= len(self.FacePlaneList):
            bf_idx = 0

        tool_geo        = self.BlockCutter_TimberBrep
        tool_base_plane = self.BlockCutter_FacePlaneList[tb_idx]
        block_face_plane= self.FacePlaneList[bf_idx]

        # FlipX/Y/Z
        fx_raw = self.all_get("FT_AlignToolToTimber_2__FlipX", 0)
        fy_raw = self.all_get("FT_AlignToolToTimber_2__FlipY", 0)
        fz_raw = self.all_get("FT_AlignToolToTimber_2__FlipZ", 0)
        try:
            flip_x = int(first_or_default(fx_raw, 0))
        except:
            flip_x = 0
        try:
            flip_y = int(first_or_default(fy_raw, 0))
        except:
            flip_y = 0
        try:
            flip_z = int(first_or_default(fz_raw, 0))
        except:
            flip_z = 0

        # 其它参数全部默认
        tool_contact_point = None
        block_target_point = None
        mode         = 0
        tool_dir     = None
        target_dir   = None
        depth_offset = 0.0
        move_u       = 0.0
        move_v       = 0.0
        tool_rot_deg = 0.0
        block_rot_deg= 0.0

        try:
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                tool_geo,
                tool_base_plane,
                tool_contact_point,
                block_face_plane,
                block_target_point,
                mode,
                tool_dir,
                target_dir,
                depth_offset,
                move_u,
                move_v,
                flip_x,
                flip_y,
                flip_z,
                tool_rot_deg,
                block_rot_deg
            )

            self.Align2_AlignedTool = aligned
            self.Align2_XForm       = xf
            self.Align2_SourcePlane = src_pl
            self.Align2_TargetPlane = tgt_pl
            self.Align2_SourcePoint = src_pt
            self.Align2_TargetPoint = tgt_pt
            self.Align2_DebugInfo   = [dbg]

            if aligned is None:
                self.Log.append("[ALIGN2] 对位失败: {}".format(dbg))
            else:
                self.Log.append("[ALIGN2] 对位完成 ToolBasePlaneIndex={} BlockFacePlaneIndex={} Flip=({}, {}, {})".format(
                    tb_idx, bf_idx, flip_x, flip_y, flip_z))

        except Exception as e:
            self.Align2_AlignedTool = None
            self.Align2_XForm       = None
            self.Align2_SourcePlane = None
            self.Align2_TargetPlane = None
            self.Align2_SourcePoint = None
            self.Align2_TargetPoint = None
            self.Align2_DebugInfo   = ["错误: {}".format(e)]
            self.Log.append("[ERROR] AlignToolToTimber::2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5：栱眼部分
    #   5.1 FT_GongYanSection_Cai
    #   5.2 PlaneFromLists::2
    #   5.3 FT_AlignToolToTimber::3
    #   5.4 FT_CutTimberByTools
    # ------------------------------------------------------
    def step5_gongyan(self):

        # ========== 5.1 FT_GongYanSection_Cai（FT_GongYanSectionABFEA） ==========
        sec_mode = self.all_get("FT_GongYanSection_Cai__SectionPlane", "WorldXZ")
        SectionPlane = make_ref_plane(sec_mode)
        A = rg.Point3d(0.0, 0.0, 0.0)

        r_raw   = self.all_get("FT_GongYanSection_Cai__RadiusFen", 3.0)
        l_raw   = self.all_get("FT_GongYanSection_Cai__LengthFen", 20.0)
        ir_raw  = self.all_get("FT_GongYanSection_Cai__InnerRadiusFen", 1.0)
        mv_raw  = self.all_get("FT_GongYanSection_Cai__MoveFen", 5.0)

        try:
            RadiusFen      = float(r_raw)
            LengthFen      = float(l_raw)
            InnerRadiusFen = float(ir_raw)
            MoveFen        = float(mv_raw)
        except Exception as e:
            self.Log.append("[GONG] 参数转换失败，使用默认值: {}".format(e))
            RadiusFen      = 3.0
            LengthFen      = 20.0
            InnerRadiusFen = 1.0
            MoveFen        = 5.0

        try:
            builder = FT_GongYanSectionABFEA(
                section_plane=SectionPlane,
                A_input=A,
                radius_fen=RadiusFen,
                length_fen=LengthFen,
                inner_radius_fen=InnerRadiusFen,
                move_fen=MoveFen,
                doc=sc.doc
            )

            (
                SectionFace,
                Points,
                InnerSection,
                InnerSectionMoved,
                InnerPoints,
                LoftFace,
                TopFace,
                ToolBrep,
                TopPlaneA,
                TopPlaneB,
                LogG
            ) = builder.build()

            self.GongSectionFace       = SectionFace
            self.GongPoints            = Points
            self.GongInnerSection      = InnerSection
            self.GongInnerSectionMoved = InnerSectionMoved
            self.GongInnerPoints       = InnerPoints
            self.GongLoftFace          = LoftFace
            self.GongTopFace           = TopFace
            self.GongToolBrep          = ToolBrep
            self.GongTopPlaneA         = TopPlaneA
            self.GongTopPlaneB         = TopPlaneB
            self.GongLog               = LogG

            self.Log.append("[GONG] FT_GongYanSectionABFEA.build 完成")
            for l in LogG:
                self.Log.append("[GONG] " + str(l))

        except Exception as e:
            self.GongSectionFace       = None
            self.GongPoints            = []
            self.GongInnerSection      = None
            self.GongInnerSectionMoved = None
            self.GongInnerPoints       = []
            self.GongLoftFace          = None
            self.GongTopFace           = None
            self.GongToolBrep          = None
            self.GongTopPlaneA         = None
            self.GongTopPlaneB         = None
            self.GongLog               = ["错误: {}".format(e)]
            self.Log.append("[ERROR] FT_GongYanSectionABFEA.build 出错: {}".format(e))
            return self

        # ========== 5.2 PlaneFromLists::2（PF2） ==========
        if not self.EdgeMidPoints or not self.Corner0Planes:
            self.Log.append("[PF2] EdgeMidPoints 或 Corner0Planes 为空，跳过 PlaneFromLists::2")
            return self

        idx_origin_raw = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
        idx_plane_raw  = self.all_get("PlaneFromLists_2__IndexPlane", 0)
        wrap_raw       = self.all_get("PlaneFromLists_2__wrap", True)

        idx_origin_list = to_list(idx_origin_raw)
        idx_plane_list  = to_list(idx_plane_raw)

        n_orig = len(idx_origin_list)
        n_pl   = len(idx_plane_list)
        n      = max(n_orig, n_pl, 1)

        def _broadcast_idx(seq, n):
            if len(seq) == 0:
                return [0] * n
            if len(seq) >= n:
                return list(seq)[:n]
            last = seq[-1]
            return list(seq) + [last] * (n - len(seq))

        try:
            idx_origin_list = [int(i) for i in _broadcast_idx(idx_origin_list, n)]
            idx_plane_list  = [int(i) for i in _broadcast_idx(idx_plane_list,  n)]
        except Exception as e:
            self.Log.append("[PF2] IndexOrigin/IndexPlane 转换失败: {}，使用单一 0".format(e))
            idx_origin_list = [0]
            idx_plane_list  = [0]
            n = 1

        Wrap = bool(wrap_raw)

        self.PF2_BasePlane   = []
        self.PF2_OriginPoint = []
        self.PF2_ResultPlane = []
        self.PF2_Log         = []

        try:
            pf_builder = FTPlaneFromLists(wrap=Wrap)

            for i in range(n):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]

                base_plane, origin_point, result_plane, pf_log = pf_builder.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip
                )

                self.PF2_BasePlane.append(base_plane)
                self.PF2_OriginPoint.append(origin_point)
                self.PF2_ResultPlane.append(result_plane)
                self.PF2_Log.extend(["[{}] {}".format(i, str(l)) for l in pf_log])

            self.Log.append("[PF2] FTPlaneFromLists.build_plane 完成，共 {} 组索引".format(n))

        except Exception as e:
            self.PF2_BasePlane   = []
            self.PF2_OriginPoint = []
            self.PF2_ResultPlane = []
            self.PF2_Log         = ["错误: {}".format(e)]
            self.Log.append("[ERROR] FTPlaneFromLists.build_plane(PF2) 出错: {}".format(e))
            return self

        # ========== 5.3 FT_AlignToolToTimber::3 ==========
        block_planes2 = to_list(self.PF2_ResultPlane)
        if len(block_planes2) == 0:
            self.Align3_DebugInfo = ["PF2_ResultPlane 为空，无法对位。"]
            self.Log.append("[ALIGN3] PF2_ResultPlane 为空，跳过对位。")
            return self

        if self.GongToolBrep is None or self.GongTopPlaneA is None or self.GongTopPlaneB is None:
            self.Align3_DebugInfo = ["GongToolBrep 或 TopPlaneA/B 为空，无法对位。"]
            self.Log.append("[ALIGN3] GongTool 或 TopPlaneA/B 为空，跳过对位。")
            return self

        N = len(block_planes2)

        # ToolBasePlane = [TopPlaneB, TopPlaneA] 列表参与广播
        tool_base_raw = [self.GongTopPlaneB, self.GongTopPlaneA]

        block_rot_raw = self.all_get("FT_AlignToolToTimber_3__BlockRotDeg", 0.0)
        flip_z_raw    = self.all_get("FT_AlignToolToTimber_3__FlipZ", 0)
        move_u_raw    = self.all_get("FT_AlignToolToTimber_3__MoveU", 0.0)

        tool_geo_list        = _broadcast_param(self.GongToolBrep,  N, "ToolGeo")
        tool_base_plane_list = _broadcast_param(tool_base_raw,      N, "ToolBasePlane")
        block_face_plane_list= _broadcast_param(block_planes2,      N, "BlockFacePlane")
        block_rot_list       = _broadcast_param(block_rot_raw,      N, "BlockRotDeg")
        flip_z_list          = _broadcast_param(flip_z_raw,         N, "FlipZ")
        move_u_list          = _broadcast_param(move_u_raw,         N, "MoveU")

        # 其它对位参数默认值
        tool_contact_point_list = _broadcast_param(None, N, "ToolContactPoint")
        block_target_point_list = _broadcast_param(None, N, "BlockTargetPoint")
        mode_list               = _broadcast_param(0,    N, "Mode")
        tool_dir_list           = _broadcast_param(None, N, "ToolDir")
        target_dir_list         = _broadcast_param(None, N, "TargetDir")
        depth_offset_list       = _broadcast_param(0.0,  N, "DepthOffset")
        move_v_list             = _broadcast_param(0.0,  N, "MoveV")
        flip_x_list             = _broadcast_param(0,    N, "FlipX")
        flip_y_list             = _broadcast_param(0,    N, "FlipY")
        tool_rot_deg_list       = _broadcast_param(0.0,  N, "ToolRotDeg")

        self.Align3_AlignedTool = []
        self.Align3_XForm       = []
        self.Align3_SourcePlane = []
        self.Align3_TargetPlane = []
        self.Align3_SourcePoint = []
        self.Align3_TargetPoint = []
        self.Align3_DebugInfo   = []

        for i in range(N):
            tool_geo        = tool_geo_list[i]
            tool_base_plane = tool_base_plane_list[i]
            block_face_plane= block_face_plane_list[i]

            if tool_geo is None or tool_base_plane is None or block_face_plane is None:
                msg = "[ALIGN3][{}] 参数缺失，跳过对位。".format(i)
                self.Align3_AlignedTool.append(None)
                self.Align3_XForm.append(None)
                self.Align3_SourcePlane.append(None)
                self.Align3_TargetPlane.append(None)
                self.Align3_SourcePoint.append(None)
                self.Align3_TargetPoint.append(None)
                self.Align3_DebugInfo.append(msg)
                self.Log.append(msg)
                continue

            try:
                block_rot_deg = float(block_rot_list[i]) if block_rot_list[i] is not None else 0.0
            except:
                block_rot_deg = 0.0

            try:
                flip_z = int(flip_z_list[i]) if flip_z_list[i] is not None else 0
            except:
                flip_z = 0

            try:
                move_u = float(move_u_list[i]) if move_u_list[i] is not None else 0.0
            except:
                move_u = 0.0

            try:
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tool_geo,
                    tool_base_plane,
                    tool_contact_point_list[i],
                    block_face_plane,
                    block_target_point_list[i],
                    mode_list[i],
                    tool_dir_list[i],
                    target_dir_list[i],
                    depth_offset_list[i],
                    move_u,
                    move_v_list[i],
                    flip_x_list[i],
                    flip_y_list[i],
                    flip_z,
                    tool_rot_deg_list[i],
                    block_rot_deg
                )

                self.Align3_AlignedTool.append(aligned)
                self.Align3_XForm.append(xf)
                self.Align3_SourcePlane.append(src_pl)
                self.Align3_TargetPlane.append(tgt_pl)
                self.Align3_SourcePoint.append(src_pt)
                self.Align3_TargetPoint.append(tgt_pt)

                if aligned is None:
                    msg = "[ALIGN3][{}] 对位失败: {}".format(i, dbg)
                    self.Align3_DebugInfo.append(msg)
                    self.Log.append(msg)
                else:
                    msg = "[ALIGN3][{}] 对位完成 BlockRotDeg={} FlipZ={} MoveU={}".format(
                        i, block_rot_deg, flip_z, move_u)
                    self.Align3_DebugInfo.append(dbg)
                    self.Log.append(msg)

            except Exception as e:
                msg = "[ERROR][ALIGN3][{}] FTAligner.align 出错: {}".format(i, e)
                self.Align3_AlignedTool.append(None)
                self.Align3_XForm.append(None)
                self.Align3_SourcePlane.append(None)
                self.Align3_TargetPlane.append(None)
                self.Align3_SourcePoint.append(None)
                self.Align3_TargetPoint.append(None)
                self.Align3_DebugInfo.append(msg)
                self.Log.append(msg)

        # ========== 5.4 FT_CutTimberByTools ==========
        tools_flat = []

        # Align1 刀具（卷殺）
        if isinstance(self.Align1_AlignedTool, list):
            for t in self.Align1_AlignedTool:
                if t is not None:
                    tools_flat.append(t)

        # Align2 刀具（BlockCutter）
        if self.Align2_AlignedTool is not None:
            tools_flat.append(self.Align2_AlignedTool)

        # Align3 刀具（栱眼）
        if isinstance(self.Align3_AlignedTool, list):
            for t in self.Align3_AlignedTool:
                if t is not None:
                    tools_flat.append(t)

        if self.TimberBrep is None:
            self.CutByToolsLog = ["[CUT] TimberBrep 为空，无法切割。"]
            self.Log.append("[CUT] TimberBrep 为空，跳过 CutTimberByTools。")
            return self

        if len(tools_flat) == 0:
            self.CutByToolsLog = ["[CUT] Tools 为空，无法切割。"]
            self.Log.append("[CUT] Tools 为空，跳过 CutTimberByTools。")
            return self

        try:
            cutter = FT_CutTimberByTools(self.TimberBrep, tools_flat)
            cut, fail, clog = cutter.run()

            self.CutTimbers   = cut
            self.FailTimbers  = fail
            self.CutByToolsLog= clog

            self.Log.append("[CUT] FT_CutTimberByTools 完成，Cut={}，Fail={}".format(
                len(cut) if cut else 0,
                len(fail) if fail else 0
            ))
            for l in clog:
                self.Log.append("[CUT] " + str(l))

        except Exception as e:
            self.CutTimbers   = []
            self.FailTimbers  = []
            self.CutByToolsLog= ["错误: {}".format(e)]
            self.Log.append("[ERROR] FT_CutTimberByTools 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------
    def run(self):

        # Step 1：数据库
        self.step1_read_db()

        # 若 All 为空，可以视情况提前返回
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：原始木料构建
        self.step2_timber()

        # Step 3：卷殺
        self.step3_juansha()

        # Step 4：BlockCutter + Align2
        self.step4_block_cutter()

        # Step 5：栱眼 + PF2 + Align3 + Cut
        self.step5_gongyan()

        return self

if __name__=="__main__":
    # ==============================================================
    # GH Python 组件输出绑定区
    # ==============================================================

    solver = GuaZiGongSolver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- 开发模式输出：DB + 木坯 ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

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

    # --- Step3: JuanShaToolBuilder 输出 ---
    JuanShaToolBrep        = solver.JuanShaToolBrep
    JuanShaSectionEdges    = solver.JuanShaSectionEdges
    JuanShaHL_Intersection = solver.JuanShaHL_Intersection
    JuanShaHeightFacePlane = solver.JuanShaHeightFacePlane
    JuanShaLengthFacePlane = solver.JuanShaLengthFacePlane
    JuanShaLog             = solver.JuanShaLog

    # --- Step3: PlaneFromLists::1 输出（多值）---
    PF1_BasePlane   = solver.PF1_BasePlane
    PF1_OriginPoint = solver.PF1_OriginPoint
    PF1_ResultPlane = solver.PF1_ResultPlane
    PF1_Log         = solver.PF1_Log

    # --- Step3: FT_AlignToolToTimber::1 输出（多位置）---
    Align1_AlignedTool = solver.Align1_AlignedTool
    Align1_XForm       = solver.Align1_XForm
    Align1_SourcePlane = solver.Align1_SourcePlane
    Align1_TargetPlane = solver.Align1_TargetPlane
    Align1_SourcePoint = solver.Align1_SourcePoint
    Align1_TargetPoint = solver.Align1_TargetPoint
    Align1_DebugInfo   = solver.Align1_DebugInfo

    # --- Step4: FT_BlockCutter 输出 ---
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

    # --- Step4: FT_AlignToolToTimber::2 输出 ---
    Align2_AlignedTool = solver.Align2_AlignedTool
    Align2_XForm       = solver.Align2_XForm
    Align2_SourcePlane = solver.Align2_SourcePlane
    Align2_TargetPlane = solver.Align2_TargetPlane
    Align2_SourcePoint = solver.Align2_SourcePoint
    Align2_TargetPoint = solver.Align2_TargetPoint
    Align2_DebugInfo   = solver.Align2_DebugInfo

    # --- Step5: FT_GongYanSection_Cai 输出 ---
    GongSectionFace       = solver.GongSectionFace
    GongPoints            = solver.GongPoints
    GongInnerSection      = solver.GongInnerSection
    GongInnerSectionMoved = solver.GongInnerSectionMoved
    GongInnerPoints       = solver.GongInnerPoints
    GongLoftFace          = solver.GongLoftFace
    GongTopFace           = solver.GongTopFace
    GongToolBrep          = solver.GongToolBrep
    GongTopPlaneA         = solver.GongTopPlaneA
    GongTopPlaneB         = solver.GongTopPlaneB
    GongLog               = solver.GongLog

    # --- Step5: PlaneFromLists::2 输出 ---
    PF2_BasePlane   = solver.PF2_BasePlane
    PF2_OriginPoint = solver.PF2_OriginPoint
    PF2_ResultPlane = solver.PF2_ResultPlane
    PF2_Log         = solver.PF2_Log

    # --- Step5: FT_AlignToolToTimber::3 输出 ---
    Align3_AlignedTool = solver.Align3_AlignedTool
    Align3_XForm       = solver.Align3_XForm
    Align3_SourcePlane = solver.Align3_SourcePlane
    Align3_TargetPlane = solver.Align3_TargetPlane
    Align3_SourcePoint = solver.Align3_SourcePoint
    Align3_TargetPoint = solver.Align3_TargetPoint
    Align3_DebugInfo   = solver.Align3_DebugInfo

    # --- Step5: FT_CutTimberByTools 日志 ---
    CutByToolsLog = solver.CutByToolsLog


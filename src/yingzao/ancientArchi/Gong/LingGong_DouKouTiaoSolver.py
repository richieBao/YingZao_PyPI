# -*- coding: utf-8 -*-
"""
BiNeiManGongSolver · Step 1（数据库读取）+ Step 2（原始木料构建）+ Step 3（卷殺：JuanSha + PlaneFromLists::1 + Align::1）
+ Step 4（BlockCutter：FT_BlockCutter + FT_AlignToolToTimber::2）
+ Step 5（栱眼：FT_GongYanSection_Cai_B + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::1 + FT_CutTimberByTools_V2）

用途：
将“壁内慢栱（四鋪作裏外並一抄卷頭，壁內用重栱）”
的一组 GH 组件，逐步整合为一个数据库驱动的 Solver。

当前步骤已完成：
Step 1：
1) 从数据库 DG_Dou 表中读取 params_json
2) type_code = BiNeiManGong_4PU_INOUT_1ChaoJuantouChongG
3) ExportAll = True
4) 构造 All / AllDict，供后续步骤统一取值

Step 2：
1) 运行 FT_timber_block_uniform：原始木料构建
2) length/width/height 从 AllDict 读取（无则默认）
3) base_point 来自组件输入端（无则原点）
4) reference_plane 固定为 GH 的 XZ Plane（X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)）

Step 3：
卷殺部分：JuanShaToolBuilder + PlaneFromLists::1 + FT_AlignToolToTimber::1
- JuanShaToolBuilder 参数来自 AllDict：JunShaToolBuilder__HeightFen/LengthFen/DivCount/ThicknessFen
- PlaneFromLists::1 参数来自 AllDict：PlaneFromLists_1__IndexOrigin/IndexPlane，输入来自 Step2 EdgeMidPoints/Corner0Planes
- FT_AlignToolToTimber::1 参数来自 AllDict：FT_AlignToolToTimber_1__BlockRotDeg / FT_AlignToolToTimber_1__FlipY
  其余输入保持 None（走库默认/组件默认）

Step 4：
BlockCutter 部分：FT_BlockCutter + FT_AlignToolToTimber::2
- FT_BlockCutter 参数来自 AllDict：FT_BlockCutter__length_fen/width_fen/height_fen
- FT_BlockCutter base_point 固定为原点，reference_plane 固定 XZ Plane
- FT_AlignToolToTimber::2：
    ToolGeo      ← FT_BlockCutter 的 TimberBrep
    ToolBasePlane← FT_BlockCutter 的 FacePlaneList[FT_AlignToolToTimber_2__ToolBasePlane]
    BlockFacePlane← FT_timber_block_uniform 的 FacePlaneList[FT_AlignToolToTimber_2__BlockFacePlane]
    其它参数（FlipX/Y/Z、Rot 等）如有则从 AllDict 读取，否则为 None

Step 5：
栱眼部分：FT_GongYanSection_Cai_B + PlaneFromLists::2 + PlaneFromLists::3 + GeoAligner::1 + FT_CutTimberByTools_V2
- FT_GongYanSection_Cai_B：
    SectionPlane 固定 GH XZ Plane，A 为原点
    RadiusFen / LengthFen / OffsetFen / ExtrudeFen 从 AllDict 读取
- PlaneFromLists::2：
    OriginPoints ← FT_GongYanSection_Cai_B 的 BridgePoints
    BasePlanes   ← FT_GongYanSection_Cai_B 的 BridgePlane
    IndexOrigin, IndexPlane ← AllDict 中 PlaneFromLists_2__*
- PlaneFromLists::3：
    OriginPoints ← FT_timber_block_uniform 的 PointList
    BasePlanes   ← FT_timber_block_uniform 的 Corner0Planes
    IndexOrigin, IndexPlane ← AllDict 中 PlaneFromLists_3__*
- GeoAligner::1：
    Geo        ← FT_GongYanSection_Cai_B 的 ToolBrep
    SourcePlane← PlaneFromLists::2 的 ResultPlane
    TargetPlane← PlaneFromLists::3 的 ResultPlane
    RotateDeg / FlipX / MoveX 从 AllDict 中 GeoAligner_1__* 获取
- FT_CutTimberByTools_V2：
    Timbers ← FT_timber_block_uniform 的 TimberBrep
    Tools   ← [Align1_AlignedTool, Align2_AlignedTool, GeoAligner::1 的 MovedGeo] 扁平化后的列表
    keep_inside ← AllDict 中 FT_CutTimberByTools_V2__KeepInside（无则 False）

输入：
    DBPath     : str       - SQLite 数据库路径
    base_point : Point3d   - 木料定位点（Step 2 使用）
    Refresh    : bool      - 手动刷新（可用于触发重算）

输出（开发模式）：
    Value, All, AllDict, DBLog
    TimberBrep...（Step2 全套）
    JuanShaToolBrep, JuanShaSectionEdges, JuanShaHL_Intersection, JuanShaHeightFacePlane, JuanShaLengthFacePlane, JuanShaLog
    PF1_BasePlane, PF1_OriginPoint, PF1_ResultPlane, PF1_Log
    Align1_AlignedTool, Align1_XForm, Align1_SourcePlane, Align1_TargetPlane, Align1_SourcePoint, Align1_TargetPoint, Align1_DebugInfo

    BlockCutter_TimberBrep, BlockCutter_FacePlaneList, BlockCutter_Log
    Align2_AlignedTool, Align2_XForm, Align2_SourcePlane, Align2_TargetPlane, Align2_SourcePoint, Align2_TargetPoint, Align2_DebugInfo

    GongYan_SectionFace, GongYan_OffsetFace, GongYan_Points, GongYan_OffsetPoints,
    GongYan_ToolBrep, GongYan_BridgePoints, GongYan_BridgeMidPoints, GongYan_BridgePlane, GongYan_Log
    PF2_BasePlane, PF2_OriginPoint, PF2_ResultPlane, PF2_Log
    PF3_BasePlane, PF3_OriginPoint, PF3_ResultPlane, PF3_Log
    GeoAligner1_SourceOut, GeoAligner1_TargetOut, GeoAligner1_MovedGeo

    Log

输出（最终）：
    CutTimbers
    FailTimbers
"""

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    JuanShaToolBuilder,
    FTPlaneFromLists,
    FTAligner,
    FT_GongYanSection_Cai_B,
    FT_GeoAligner,
    FT_CutTimberByTools_V2,
    FT_AnZhiToolBuilder
)


# ==============================================================
# 通用工具
# ==============================================================

def all_to_dict(all_list):
    """
    All = [
        ('FT_timber_block_uniform__length_fen', 92),
        ('PlaneFromLists_1__IndexOrigin', [8, 9]),
        ...
    ]
    → dict
    """
    d = {}
    if not all_list:
        return d
    for item in all_list:
        if isinstance(item, tuple) and len(item) == 2:
            d[item[0]] = item[1]
    return d


def _to_list(x):
    """若为 list/tuple 则转为 list，否则包装成 [x]。"""
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _param_length(val):
    """返回参数的“长度”：list/tuple → len；None → 0；其他 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1


def _broadcast_param(val, n, name="param"):
    """
    广播/截断参数到长度 n：

    - 若 val 为 list/tuple：
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
# 主 Solver 类 —— BiNeiManGongSolver
# ==============================================================

class LingGong_DouKouTiaoSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):

        # ---- GH 输入 ----
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # ---- Step 1：数据库 ----
        self.Value = None
        self.All = []
        self.AllDict = {}
        self.DBLog = []

        # ---- Step 2：FT_timber_block_uniform 输出（开发模式）----
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

        # ---- Step 3：JuanShaToolBuilder 输出（开发模式）----
        self.JuanShaToolBrep = None
        self.JuanShaSectionEdges = []
        self.JuanShaHL_Intersection = None
        self.JuanShaHeightFacePlane = None
        self.JuanShaLengthFacePlane = None
        self.JuanShaLog = []

        # ---- Step 3：PlaneFromLists::1 输出（开发模式）----
        self.PF1_BasePlane = None
        self.PF1_OriginPoint = None
        self.PF1_ResultPlane = None
        self.PF1_Log = []

        # ---- Step 3：FT_AlignToolToTimber::1 输出（开发模式）----
        self.Align1_AlignedTool = []
        self.Align1_XForm = []
        self.Align1_SourcePlane = []
        self.Align1_TargetPlane = []
        self.Align1_SourcePoint = []
        self.Align1_TargetPoint = []
        self.Align1_DebugInfo = []

        # ---- Step 4：FT_BlockCutter 输出（开发模式）----
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

        # ---- Step 4：FT_AlignToolToTimber::2 输出（开发模式）----
        self.Align2_AlignedTool = []
        self.Align2_XForm = []
        self.Align2_SourcePlane = []
        self.Align2_TargetPlane = []
        self.Align2_SourcePoint = []
        self.Align2_TargetPoint = []
        self.Align2_DebugInfo = []

        # ---- Step 5：栱眼 FT_GongYanSection_Cai_B 输出（开发模式）----
        self.GongYan_SectionFace = None
        self.GongYan_OffsetFace = None
        self.GongYan_Points = []
        self.GongYan_OffsetPoints = []
        self.GongYan_ToolBrep = None
        self.GongYan_BridgePoints = []
        self.GongYan_BridgeMidPoints = []
        self.GongYan_BridgePlane = []
        self.GongYan_Log = []

        # ---- Step 5：PlaneFromLists::2 输出（开发模式）----
        self.PF2_BasePlane = []
        self.PF2_OriginPoint = []
        self.PF2_ResultPlane = []
        self.PF2_Log = []

        # ---- Step 5：PlaneFromLists::3 输出（开发模式）----
        self.PF3_BasePlane = []
        self.PF3_OriginPoint = []
        self.PF3_ResultPlane = []
        self.PF3_Log = []

        # ---- Step 5：GeoAligner::1 输出（开发模式）----
        self.GeoAligner1_SourceOut = None
        self.GeoAligner1_TargetOut = None
        self.GeoAligner1_MovedGeo = None

        # ---- Step 6：闇栔 FT_AnZhi 输出（开发模式）----
        self.AnZhi_ToolBrep = None
        self.AnZhi_CubeBrep = None
        self.AnZhi_PinBreps = []
        self.AnZhi_AnZhiToolBrep = None
        self.AnZhi_FacePlane = None
        self.AnZhi_Log = []

        # ---- Step 6：PlaneFromLists::4 输出 ----
        self.PF4_BasePlane = []
        self.PF4_OriginPoint = []
        self.PF4_ResultPlane = []
        self.PF4_Log = []

        # ---- Step 6：GeoAligner::2 输出 ----
        self.GeoAligner2_SourceOut = None
        self.GeoAligner2_TargetOut = None
        self.GeoAligner2_MovedGeo = None

        # ---- Step 6：最终合并输出 ----
        self.CutTimbersPlusAnZhi = []

        # ---- 全局日志 ----
        self.Log = []

        # ---- 最终输出 ----
        self.CutTimbers = []
        self.FailTimbers = []

    # ----------------------------------------------------------
    # Step 1：读取数据库
    # ----------------------------------------------------------
    def step1_read_db(self):
        """
        从 DG_Dou 表中读取壁内慢栱 params_json
        """

        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="LingGong_DouKouTiao",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成")
            for l in self.DBLog:
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append(
                "[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict))
            )

        except Exception as e:
            self.Value = None
            self.All = []
            self.AllDict = {}
            self.DBLog = []
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # ----------------------------------------------------------
    def step2_timber_block_uniform(self):
        """
        组件映射：
        - length_fen  ← FT_timber_block_uniform__length_fen（无则默认 32）
        - width_fen   ← FT_timber_block_uniform__width_fen （无则默认 32）
        - height_fen  ← FT_timber_block_uniform__height_fen（无则默认 20）
        - base_point  ← GH 输入端 base_point（无则原点）
        - reference_plane ← 固定 GH XZ Plane
            X = (1,0,0)
            Y = (0,0,1)
            Z = (0,-1,0)
        """

        # 1) fen 参数：数据库 → 默认
        length_fen = self.AllDict.get("FT_timber_block_uniform__length_fen", 32.0)
        width_fen = self.AllDict.get("FT_timber_block_uniform__width_fen", 32.0)
        height_fen = self.AllDict.get("FT_timber_block_uniform__height_fen", 20.0)

        try:
            length_fen = float(length_fen) if length_fen is not None else 32.0
            width_fen = float(width_fen) if width_fen is not None else 32.0
            height_fen = float(height_fen) if height_fen is not None else 20.0
        except Exception as e:
            self.Log.append("[TIMBER] fen 参数转换失败，回退默认值: {}".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        # 2) base_point：输入端优先 → 原点
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location
        elif not isinstance(bp, rg.Point3d):
            # 尝试将任意带 X/Y/Z 的对象转 Point3d
            try:
                bp = rg.Point3d(bp.X, bp.Y, bp.Z)
            except:
                bp = rg.Point3d(0.0, 0.0, 0.0)

        # 3) reference_plane：固定 GH XZ Plane（显式构造避免歧义）
        origin = rg.Point3d(0.0, 0.0, 0.0)
        xaxis = rg.Vector3d(1.0, 0.0, 0.0)
        yaxis = rg.Vector3d(0.0, 0.0, 1.0)  # XZ 平面中的“Y 轴”指向世界 +Z
        reference_plane = rg.Plane(origin, xaxis, yaxis)

        # 4) 调用 yingzao.ancientArchi
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

            # 与原组件输出一致的成员变量
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

            self.Log.append("[TIMBER] FT_timber_block_uniform 构建完成")
            for l in log_lines:
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            # 清空几何输出，保留日志
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

            self.Log.append("[ERROR] step2_timber_block_uniform 出错: {}".format(e))

        return self

    # ----------------------------------------------------------
    # Step 3：卷殺（JuanShaToolBuilder + PlaneFromLists::1 + FT_AlignToolToTimber::1）
    # ----------------------------------------------------------
    def step3_juan_sha(self):

        # ---------------------------
        # 3.1 JuanShaToolBuilder
        # ---------------------------
        HeightFen = self.AllDict.get("JunShaToolBuilder__HeightFen", None)
        LengthFen = self.AllDict.get("JunShaToolBuilder__LengthFen", None)
        DivCount = self.AllDict.get("JunShaToolBuilder__DivCount", None)
        ThicknessFen = self.AllDict.get("JunShaToolBuilder__ThicknessFen", None)

        # SectionPlane：固定 GH XZ Plane
        origin = rg.Point3d(0.0, 0.0, 0.0)
        xaxis = rg.Vector3d(1.0, 0.0, 0.0)
        yaxis = rg.Vector3d(0.0, 0.0, 1.0)
        SectionPlane = rg.Plane(origin, xaxis, yaxis)

        # PositionPoint：此步骤不做额外定位（按你给的原组件走）
        PositionPoint = None

        try:
            builder = JuanShaToolBuilder(
                height_fen=HeightFen,
                length_fen=LengthFen,
                thickness_fen=ThicknessFen,
                div_count=DivCount,
                section_plane=SectionPlane,
                position_point=PositionPoint
            )

            (
                ToolBrep,
                SectionEdges,
                HL_Intersection,
                HeightFacePlane,
                LengthFacePlane,
                LogLines
            ) = builder.build()

            self.JuanShaToolBrep = ToolBrep
            self.JuanShaSectionEdges = SectionEdges
            self.JuanShaHL_Intersection = HL_Intersection
            self.JuanShaHeightFacePlane = HeightFacePlane
            self.JuanShaLengthFacePlane = LengthFacePlane
            self.JuanShaLog = LogLines if LogLines is not None else []

            self.Log.append("[JUANSHA] JuanShaToolBuilder 完成")
            for l in self.JuanShaLog:
                self.Log.append("[JUANSHA] " + str(l))

        except Exception as e:
            self.JuanShaToolBrep = None
            self.JuanShaSectionEdges = []
            self.JuanShaHL_Intersection = None
            self.JuanShaHeightFacePlane = None
            self.JuanShaLengthFacePlane = None
            self.JuanShaLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step3_juan_sha · JuanShaToolBuilder 出错: {}".format(e))
            return self

        # ---------------------------
        # 3.2 PlaneFromLists::1   ★★ 多索引展开 ★★
        # ---------------------------
        try:
            OriginPoints = self.EdgeMidPoints
            BasePlanes = self.Corner0Planes

            idx_origin_raw = self.AllDict.get("PlaneFromLists_1__IndexOrigin", 0)
            idx_plane_raw = self.AllDict.get("PlaneFromLists_1__IndexPlane", 0)

            idx_origin_list = _to_list(idx_origin_raw)
            idx_plane_list = _to_list(idx_plane_raw)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _broadcast_idx(seq, n):
                if len(seq) == 0:
                    return [0] * n
                if len(seq) >= n:
                    return list(seq)[:n]
                return list(seq) + [seq[-1]] * (n - len(seq))

            try:
                idx_origin_list = [int(i) for i in _broadcast_idx(idx_origin_list, n)]
                idx_plane_list = [int(i) for i in _broadcast_idx(idx_plane_list, n)]
            except Exception as e_idx:
                self.Log.append("[PF1] IndexOrigin/IndexPlane 转换失败: {}".format(e_idx))
                idx_origin_list = [0]
                idx_plane_list = [0]
                n = 1

            Wrap = True

            # 结果为列表形式保存（支持多 ResultPlane）
            self.PF1_BasePlane = []
            self.PF1_OriginPoint = []
            self.PF1_ResultPlane = []
            self.PF1_Log = []

            pfl = FTPlaneFromLists(wrap=Wrap)

            for i in range(n):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]

                BasePlane, OriginPoint, ResultPlane, PFLog = pfl.build_plane(
                    OriginPoints,
                    BasePlanes,
                    io,
                    ip
                )

                self.PF1_BasePlane.append(BasePlane)
                self.PF1_OriginPoint.append(OriginPoint)
                self.PF1_ResultPlane.append(ResultPlane)
                if PFLog:
                    self.PF1_Log.extend(PFLog)

            self.Log.append("[PF1] PlaneFromLists::1 完成，N={}".format(n))
            for l in self.PF1_Log:
                self.Log.append("[PF1] " + str(l))

        except Exception as e:
            self.PF1_BasePlane = None
            self.PF1_OriginPoint = None
            self.PF1_ResultPlane = None
            self.PF1_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step3_juan_sha · PlaneFromLists::1 出错: {}".format(e))
            return self

        # ---------------------------
        # 3.3 FT_AlignToolToTimber::1（多刀具 & 广播）
        # ---------------------------
        ToolGeo = self.JuanShaToolBrep
        ToolBasePlane = self.JuanShaHeightFacePlane
        # PF1_ResultPlane 是 list[Plane]，广播播入
        BlockFacePlane = self.PF1_ResultPlane

        BlockRotDeg = self.AllDict.get("FT_AlignToolToTimber_1__BlockRotDeg", None)
        FlipY = self.AllDict.get("FT_AlignToolToTimber_1__FlipY", None)

        # 其余输入端保持 None
        ToolRotDeg = None
        ToolContactPoint = None
        BlockTargetPoint = None
        FlipX = None
        FlipZ = None
        Mode = None
        ToolDir = None
        TargetDir = None
        DepthOffset = None
        MoveU = None
        MoveV = None

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
                lengths.append(_param_length(ToolRotDeg))
                lengths.append(_param_length(ToolContactPoint))
                lengths.append(_param_length(BlockFacePlane))
                lengths.append(_param_length(BlockRotDeg))
                lengths.append(_param_length(FlipX))
                lengths.append(_param_length(FlipY))
                lengths.append(_param_length(FlipZ))
                lengths.append(_param_length(BlockTargetPoint))
                lengths.append(_param_length(Mode))
                lengths.append(_param_length(ToolDir))
                lengths.append(_param_length(TargetDir))
                lengths.append(_param_length(DepthOffset))
                lengths.append(_param_length(MoveU))
                lengths.append(_param_length(MoveV))
                lengths = [l for l in lengths if l > 0]
                N = max(lengths) if lengths else 1
            else:
                N = tool_count

            tools_list = _broadcast_param(tools_list_base, N, "ToolGeo")
            tool_planes = _broadcast_param(ToolBasePlane, N, "ToolBasePlane")
            tool_rots = _broadcast_param(ToolRotDeg, N, "ToolRotDeg")
            tool_pts = _broadcast_param(ToolContactPoint, N, "ToolContactPoint")
            block_planes = _broadcast_param(BlockFacePlane, N, "BlockFacePlane")
            block_rots = _broadcast_param(BlockRotDeg, N, "BlockRotDeg")
            flip_xs = _broadcast_param(FlipX, N, "FlipX")
            flip_ys = _broadcast_param(FlipY, N, "FlipY")
            flip_zs = _broadcast_param(FlipZ, N, "FlipZ")
            block_pts = _broadcast_param(BlockTargetPoint, N, "BlockTargetPoint")
            modes = _broadcast_param(Mode, N, "Mode")
            tool_dirs = _broadcast_param(ToolDir, N, "ToolDir")
            target_dirs = _broadcast_param(TargetDir, N, "TargetDir")
            depth_offsets = _broadcast_param(DepthOffset, N, "DepthOffset")
            move_us = _broadcast_param(MoveU, N, "MoveU")
            move_vs = _broadcast_param(MoveV, N, "MoveV")

            for i in range(N):
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tools_list[i],
                    tool_planes[i],
                    tool_pts[i],
                    block_planes[i],
                    block_pts[i],
                    modes[i],
                    tool_dirs[i],
                    target_dirs[i],
                    depth_offsets[i],
                    move_us[i],
                    move_vs[i],
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

        self.Align1_AlignedTool = AlignedTool
        self.Align1_XForm = XForm
        self.Align1_SourcePlane = SourcePlane
        self.Align1_TargetPlane = TargetPlane
        self.Align1_SourcePoint = SourcePoint
        self.Align1_TargetPoint = TargetPoint
        self.Align1_DebugInfo = DebugInfo

        self.Log.append("[ALIGN1] FT_AlignToolToTimber::1 完成（N={}）".format(len(self.Align1_DebugInfo)))
        for l in self.Align1_DebugInfo:
            self.Log.append("[ALIGN1] " + str(l))

        return self

    # ----------------------------------------------------------
    # Step 4：BlockCutter（FT_BlockCutter + FT_AlignToolToTimber::2）
    # ----------------------------------------------------------
    def step4_block_cutter(self):

        # ---------------------------
        # 4.1 FT_BlockCutter（同 build_timber_block_uniform，小木块）
        # ---------------------------
        length_fen = self.AllDict.get("FT_BlockCutter__length_fen", 32.0)
        width_fen = self.AllDict.get("FT_BlockCutter__width_fen", 32.0)
        height_fen = self.AllDict.get("FT_BlockCutter__height_fen", 20.0)

        try:
            length_fen = float(length_fen) if length_fen is not None else 32.0
            width_fen = float(width_fen) if width_fen is not None else 32.0
            height_fen = float(height_fen) if height_fen is not None else 20.0
        except Exception as e:
            self.Log.append("[BLOCKCUT] fen 参数转换失败，回退默认值: {}".format(e))
            length_fen, width_fen, height_fen = 32.0, 32.0, 20.0

        base_point = rg.Point3d(0.0, 0.0, 0.0)
        origin = rg.Point3d(0.0, 0.0, 0.0)
        xaxis = rg.Vector3d(1.0, 0.0, 0.0)
        yaxis = rg.Vector3d(0.0, 0.0, 1.0)
        reference_plane = rg.Plane(origin, xaxis, yaxis)

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

            self.BlockCutter_TimberBrep = timber_brep
            self.BlockCutter_FaceList = faces
            self.BlockCutter_PointList = points
            self.BlockCutter_EdgeList = edges
            self.BlockCutter_CenterPoint = center_pt
            self.BlockCutter_CenterAxisLines = center_axes
            self.BlockCutter_EdgeMidPoints = edge_midpts
            self.BlockCutter_FacePlaneList = face_planes
            self.BlockCutter_Corner0Planes = corner0_planes
            self.BlockCutter_LocalAxesPlane = local_axes_plane
            self.BlockCutter_AxisX = axis_x
            self.BlockCutter_AxisY = axis_y
            self.BlockCutter_AxisZ = axis_z
            self.BlockCutter_FaceDirTags = face_tags
            self.BlockCutter_EdgeDirTags = edge_tags
            self.BlockCutter_Corner0EdgeDirs = corner0_dirs
            self.BlockCutter_Log = log_lines

            self.Log.append("[BLOCKCUT] FT_BlockCutter 构建完成")
            for l in log_lines:
                self.Log.append("[BLOCKCUT] " + str(l))

        except Exception as e:
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
            self.BlockCutter_Log = ["错误: {}".format(e)]

            self.Log.append("[ERROR] step4_block_cutter · FT_BlockCutter 出错: {}".format(e))
            return self

        # ---------------------------
        # 4.2 FT_AlignToolToTimber::2
        # ---------------------------
        ToolGeo = self.BlockCutter_TimberBrep

        # 索引来自 AllDict，指向 FacePlaneList
        tool_plane_idx_raw = self.AllDict.get("FT_AlignToolToTimber_2__ToolBasePlane", 0)
        block_plane_idx_raw = self.AllDict.get("FT_AlignToolToTimber_2__BlockFacePlane", 0)

        try:
            tool_plane_idx = int(tool_plane_idx_raw)
        except Exception:
            tool_plane_idx = 0
        try:
            block_plane_idx = int(block_plane_idx_raw)
        except Exception:
            block_plane_idx = 0

        ToolBasePlane = None
        if self.BlockCutter_FacePlaneList and 0 <= tool_plane_idx < len(self.BlockCutter_FacePlaneList):
            ToolBasePlane = self.BlockCutter_FacePlaneList[tool_plane_idx]

        BlockFacePlane = None
        if self.FacePlaneList and 0 <= block_plane_idx < len(self.FacePlaneList):
            BlockFacePlane = self.FacePlaneList[block_plane_idx]

        # 其余参数（若 DB 中存在则读取，否则为 None）
        ToolRotDeg = self.AllDict.get("FT_AlignToolToTimber_2__ToolRotDeg", None)
        BlockRotDeg = self.AllDict.get("FT_AlignToolToTimber_2__BlockRotDeg", None)
        ToolContactPoint = self.AllDict.get("FT_AlignToolToTimber_2__ToolContactPoint", None)
        BlockTargetPoint = self.AllDict.get("FT_AlignToolToTimber_2__BlockTargetPoint", None)
        FlipX = self.AllDict.get("FT_AlignToolToTimber_2__FlipX", None)
        FlipY = self.AllDict.get("FT_AlignToolToTimber_2__FlipY", None)
        FlipZ = self.AllDict.get("FT_AlignToolToTimber_2__FlipZ", None)
        Mode = self.AllDict.get("FT_AlignToolToTimber_2__Mode", None)
        ToolDir = self.AllDict.get("FT_AlignToolToTimber_2__ToolDir", None)
        TargetDir = self.AllDict.get("FT_AlignToolToTimber_2__TargetDir", None)
        DepthOffset = self.AllDict.get("FT_AlignToolToTimber_2__DepthOffset", None)
        MoveU = self.AllDict.get("FT_AlignToolToTimber_2__MoveU", None)
        MoveV = self.AllDict.get("FT_AlignToolToTimber_2__MoveV", None)

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
                lengths.append(_param_length(ToolRotDeg))
                lengths.append(_param_length(ToolContactPoint))
                lengths.append(_param_length(BlockFacePlane))
                lengths.append(_param_length(BlockRotDeg))
                lengths.append(_param_length(FlipX))
                lengths.append(_param_length(FlipY))
                lengths.append(_param_length(FlipZ))
                lengths.append(_param_length(BlockTargetPoint))
                lengths.append(_param_length(Mode))
                lengths.append(_param_length(ToolDir))
                lengths.append(_param_length(TargetDir))
                lengths.append(_param_length(DepthOffset))
                lengths.append(_param_length(MoveU))
                lengths.append(_param_length(MoveV))
                lengths = [l for l in lengths if l > 0]
                N = max(lengths) if lengths else 1
            else:
                N = tool_count

            tools_list = _broadcast_param(tools_list_base, N, "ToolGeo")
            tool_planes = _broadcast_param(ToolBasePlane, N, "ToolBasePlane")
            tool_rots = _broadcast_param(ToolRotDeg, N, "ToolRotDeg")
            tool_pts = _broadcast_param(ToolContactPoint, N, "ToolContactPoint")
            block_planes = _broadcast_param(BlockFacePlane, N, "BlockFacePlane")
            block_rots = _broadcast_param(BlockRotDeg, N, "BlockRotDeg")
            flip_xs = _broadcast_param(FlipX, N, "FlipX")
            flip_ys = _broadcast_param(FlipY, N, "FlipY")
            flip_zs = _broadcast_param(FlipZ, N, "FlipZ")
            block_pts = _broadcast_param(BlockTargetPoint, N, "BlockTargetPoint")
            modes = _broadcast_param(Mode, N, "Mode")
            tool_dirs = _broadcast_param(ToolDir, N, "ToolDir")
            target_dirs = _broadcast_param(TargetDir, N, "TargetDir")
            depth_offsets = _broadcast_param(DepthOffset, N, "DepthOffset")
            move_us = _broadcast_param(MoveU, N, "MoveU")
            move_vs = _broadcast_param(MoveV, N, "MoveV")

            for i in range(N):
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    tools_list[i],
                    tool_planes[i],
                    tool_pts[i],
                    block_planes[i],
                    block_pts[i],
                    modes[i],
                    tool_dirs[i],
                    target_dirs[i],
                    depth_offsets[i],
                    move_us[i],
                    move_vs[i],
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

        self.Align2_AlignedTool = AlignedTool
        self.Align2_XForm = XForm
        self.Align2_SourcePlane = SourcePlane
        self.Align2_TargetPlane = TargetPlane
        self.Align2_SourcePoint = SourcePoint
        self.Align2_TargetPoint = TargetPoint
        self.Align2_DebugInfo = DebugInfo

        self.Log.append("[ALIGN2] FT_AlignToolToTimber::2 完成（N={}）".format(len(self.Align2_DebugInfo)))
        for l in self.Align2_DebugInfo:
            self.Log.append("[ALIGN2] " + str(l))

        return self

    # ----------------------------------------------------------
    # Step 5：栱眼 + 切割
    # ----------------------------------------------------------
    def step5_gongyan_and_cut(self):

        # ==========================
        # 5.1 FT_GongYanSection_Cai_B
        # ==========================
        try:
            # SectionPlane：GH XZ Plane
            origin = rg.Point3d(0.0, 0.0, 0.0)
            xaxis = rg.Vector3d(1.0, 0.0, 0.0)
            yaxis = rg.Vector3d(0.0, 0.0, 1.0)
            SectionPlane = rg.Plane(origin, xaxis, yaxis)

            A_input = rg.Point3d(0.0, 0.0, 0.0)

            RadiusFen = self.AllDict.get("FT_GongYanSection_Cai_B__RadiusFen", 3.0)
            LengthFen = self.AllDict.get("FT_GongYanSection_Cai_B__LengthFen", 30.0)
            OffsetFen = self.AllDict.get("FT_GongYanSection_Cai_B__OffsetFen", 10.0)
            ExtrudeFen = self.AllDict.get("FT_GongYanSection_Cai_B__ExtrudeFen", 1.0)

            try:
                RadiusFen = float(RadiusFen) if RadiusFen is not None else 3.0
                LengthFen = float(LengthFen) if LengthFen is not None else 30.0
                OffsetFen = float(OffsetFen) if OffsetFen is not None else 10.0
                ExtrudeFen = float(ExtrudeFen) if ExtrudeFen is not None else 1.0
            except Exception as e_num:
                self.Log.append("[GONGYAN] 数值参数转换失败，使用默认值: {}".format(e_num))
                RadiusFen, LengthFen, OffsetFen, ExtrudeFen = 3.0, 30.0, 10.0, 1.0

            builder = FT_GongYanSection_Cai_B(
                section_plane=SectionPlane,
                A_input=A_input,
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

            self.GongYan_SectionFace = SectionFace
            self.GongYan_OffsetFace = OffsetFace
            self.GongYan_Points = Points
            self.GongYan_OffsetPoints = OffsetPoints
            self.GongYan_ToolBrep = ToolBrep
            self.GongYan_BridgePoints = BridgePoints
            self.GongYan_BridgeMidPoints = BridgeMidPoints
            self.GongYan_BridgePlane = BridgePlane
            self.GongYan_Log = LogLines if LogLines is not None else []

            self.Log.append("[GONGYAN] FT_GongYanSection_Cai_B 构建完成")
            for l in self.GongYan_Log:
                self.Log.append("[GONGYAN] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step5_gongyan_and_cut · FT_GongYanSection_Cai_B 出错: {}".format(e))
            return self

        # ==========================
        # 5.2 PlaneFromLists::2
        # ==========================
        try:
            OriginPoints = self.GongYan_BridgePoints
            BasePlanes = self.GongYan_BridgePlane

            idx_origin_raw = self.AllDict.get("PlaneFromLists_2__IndexOrigin", 0)
            idx_plane_raw = self.AllDict.get("PlaneFromLists_2__IndexPlane", 0)

            idx_origin_list = _to_list(idx_origin_raw)
            idx_plane_list = _to_list(idx_plane_raw)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _broadcast_idx(seq, n):
                if len(seq) == 0:
                    return [0] * n
                if len(seq) >= n:
                    return list(seq)[:n]
                return list(seq) + [seq[-1]] * (n - len(seq))

            try:
                idx_origin_list = [int(i) for i in _broadcast_idx(idx_origin_list, n)]
                idx_plane_list = [int(i) for i in _broadcast_idx(idx_plane_list, n)]
            except Exception as e_idx:
                self.Log.append("[PF2] IndexOrigin/IndexPlane 转换失败: {}".format(e_idx))
                idx_origin_list = [0]
                idx_plane_list = [0]
                n = 1

            Wrap = True

            self.PF2_BasePlane = []
            self.PF2_OriginPoint = []
            self.PF2_ResultPlane = []
            self.PF2_Log = []

            pfl2 = FTPlaneFromLists(wrap=Wrap)

            for i in range(n):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]

                BasePlane, OriginPoint, ResultPlane, PFLog = pfl2.build_plane(
                    OriginPoints,
                    BasePlanes,
                    io,
                    ip
                )

                self.PF2_BasePlane.append(BasePlane)
                self.PF2_OriginPoint.append(OriginPoint)
                self.PF2_ResultPlane.append(ResultPlane)
                if PFLog:
                    self.PF2_Log.extend(PFLog)

            self.Log.append("[PF2] PlaneFromLists::2 完成，N={}".format(n))
            for l in self.PF2_Log:
                self.Log.append("[PF2] " + str(l))

        except Exception as e:
            self.PF2_BasePlane = None
            self.PF2_OriginPoint = None
            self.PF2_ResultPlane = None
            self.PF2_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step5_gongyan_and_cut · PlaneFromLists::2 出错: {}".format(e))
            return self

        # ==========================
        # 5.3 PlaneFromLists::3
        # ==========================
        try:
            OriginPoints = self.PointList
            BasePlanes = self.Corner0Planes

            idx_origin_raw = self.AllDict.get("PlaneFromLists_3__IndexOrigin", 0)
            idx_plane_raw = self.AllDict.get("PlaneFromLists_3__IndexPlane", 0)

            idx_origin_list = _to_list(idx_origin_raw)
            idx_plane_list = _to_list(idx_plane_raw)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _broadcast_idx3(seq, n):
                if len(seq) == 0:
                    return [0] * n
                if len(seq) >= n:
                    return list(seq)[:n]
                return list(seq) + [seq[-1]] * (n - len(seq))

            try:
                idx_origin_list = [int(i) for i in _broadcast_idx3(idx_origin_list, n)]
                idx_plane_list = [int(i) for i in _broadcast_idx3(idx_plane_list, n)]
            except Exception as e_idx:
                self.Log.append("[PF3] IndexOrigin/IndexPlane 转换失败: {}".format(e_idx))
                idx_origin_list = [0]
                idx_plane_list = [0]
                n = 1

            Wrap = True

            self.PF3_BasePlane = []
            self.PF3_OriginPoint = []
            self.PF3_ResultPlane = []
            self.PF3_Log = []

            pfl3 = FTPlaneFromLists(wrap=Wrap)

            for i in range(n):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]

                BasePlane, OriginPoint, ResultPlane, PFLog = pfl3.build_plane(
                    OriginPoints,
                    BasePlanes,
                    io,
                    ip
                )

                self.PF3_BasePlane.append(BasePlane)
                self.PF3_OriginPoint.append(OriginPoint)
                self.PF3_ResultPlane.append(ResultPlane)
                if PFLog:
                    self.PF3_Log.extend(PFLog)

            self.Log.append("[PF3] PlaneFromLists::3 完成，N={}".format(n))
            for l in self.PF3_Log:
                self.Log.append("[PF3] " + str(l))

        except Exception as e:
            self.PF3_BasePlane = None
            self.PF3_OriginPoint = None
            self.PF3_ResultPlane = None
            self.PF3_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step5_gongyan_and_cut · PlaneFromLists::3 出错: {}".format(e))
            return self

        # ==========================
        # 5.4 GeoAligner::1
        # 规则：
        # - Geo 若为 list/tuple：视为一个“组 G”，不按 i 拆分
        # - 其他参数若为多值列表：按 n 次广播，与每次对位一一对应
        # - 其他参数若为单值：也广播到 n
        # - 输出：n==1 输出单个；n>1 输出 list
        # ==========================
        try:
            Geo = self.GongYan_ToolBrep  # 允许为 Brep 或 list[Breps]，这里都当作“组 G”

            # ---------- 本段局部广播工具（不影响全局） ----------
            def _param_len(x):
                if x is None:
                    return 0
                return len(x) if isinstance(x, (list, tuple)) else 1

            def _broadcast(val, n):
                """把标量/列表广播到长度 n；列表不足用最后一个补齐；空列表→[None]*n"""
                if isinstance(val, (list, tuple)):
                    lst = list(val)
                    if len(lst) == 0:
                        return [None] * n
                    if len(lst) >= n:
                        return lst[:n]
                    return lst + [lst[-1]] * (n - len(lst))
                return [val] * n

            def _to_float(x, default=0.0):
                try:
                    return float(x)
                except:
                    return default

            def _to_bool01(x, default=False):
                # 兼容 0/1、bool、"0"/"1"、"True"/"False"、None
                if isinstance(x, bool):
                    return x
                if x is None:
                    return default
                try:
                    s = str(x).strip().lower()
                    if s in ("true", "t", "yes", "y"):
                        return True
                    if s in ("false", "f", "no", "n"):
                        return False
                    return bool(int(float(x)))
                except:
                    return default

            # ---------- 读取输入（允许 list） ----------
            SourcePlane_raw = self.PF2_ResultPlane
            TargetPlane_raw = self.PF3_ResultPlane

            RotateDeg_raw = self.AllDict.get("GeoAligner_1__RotateDeg", 0.0)
            FlipX_raw = self.AllDict.get("GeoAligner_1__FlipX", 0)
            FlipY_raw = self.AllDict.get("GeoAligner_1__FlipY", 0)
            FlipZ_raw = self.AllDict.get("GeoAligner_1__FlipZ", 0)
            MoveX_raw = self.AllDict.get("GeoAligner_1__MoveX", 0.0)
            MoveY_raw = self.AllDict.get("GeoAligner_1__MoveY", 0.0)
            MoveZ_raw = self.AllDict.get("GeoAligner_1__MoveZ", 0.0)

            # ---------- 计算广播次数 n（由“除 Geo 外”的参数决定） ----------
            n = max(
                1,
                _param_len(SourcePlane_raw),
                _param_len(TargetPlane_raw),
                _param_len(RotateDeg_raw),
                _param_len(FlipX_raw),
                _param_len(FlipY_raw),
                _param_len(FlipZ_raw),
                _param_len(MoveX_raw),
                _param_len(MoveY_raw),
                _param_len(MoveZ_raw),
            )

            # ---------- 广播并规范化 ----------
            SourcePlane_list = _broadcast(SourcePlane_raw, n)
            TargetPlane_list = _broadcast(TargetPlane_raw, n)

            RotateDeg_list = [_to_float(v, 0.0) for v in _broadcast(RotateDeg_raw, n)]
            MoveX_list = [_to_float(v, 0.0) for v in _broadcast(MoveX_raw, n)]
            MoveY_list = [_to_float(v, 0.0) for v in _broadcast(MoveY_raw, n)]
            MoveZ_list = [_to_float(v, 0.0) for v in _broadcast(MoveZ_raw, n)]

            FlipX_list = [_to_bool01(v, False) for v in _broadcast(FlipX_raw, n)]
            FlipY_list = [_to_bool01(v, False) for v in _broadcast(FlipY_raw, n)]
            FlipZ_list = [_to_bool01(v, False) for v in _broadcast(FlipZ_raw, n)]

            # ---------- 逐次对位：Geo 始终作为“组 G”输入 ----------
            SourceOut_list, TargetOut_list, MovedGeo_list = [], [], []

            for i in range(n):
                SourcePlane = SourcePlane_list[i]
                TargetPlane = TargetPlane_list[i]

                (SourceOut, TargetOut, MovedGeo) = FT_GeoAligner.align(
                    Geo,
                    SourcePlane,
                    TargetPlane,
                    rotate_deg=RotateDeg_list[i],
                    flip_x=FlipX_list[i],
                    flip_y=FlipY_list[i],
                    flip_z=FlipZ_list[i],
                    move_x=MoveX_list[i],
                    move_y=MoveY_list[i],
                    move_z=MoveZ_list[i],
                )

                SourceOut_list.append(SourceOut)
                TargetOut_list.append(TargetOut)
                MovedGeo_list.append(MovedGeo)

            # ---------- 输出兼容：n==1 输出单个；否则输出 list ----------
            self.GeoAligner1_SourceOut = SourceOut_list[0] if n == 1 else SourceOut_list
            self.GeoAligner1_TargetOut = TargetOut_list[0] if n == 1 else TargetOut_list
            self.GeoAligner1_MovedGeo = MovedGeo_list[0] if n == 1 else MovedGeo_list

            self.Log.append("[GEOALIGN1] GeoAligner::1 完成，N={}".format(n))

        except Exception as e:
            self.GeoAligner1_SourceOut = None
            self.GeoAligner1_TargetOut = None
            self.GeoAligner1_MovedGeo = None
            self.Log.append("[ERROR] step5_gongyan_and_cut · GeoAligner::1 出错: {}".format(e))
            return self

        # ==========================
        # 5.5 FT_CutTimberByTools_V2
        # ==========================
        try:
            # Timbers：主木坯
            if self.TimberBrep is None:
                self.Log.append("[CUT] TimberBrep 为空，无法切割。")
                return self

            timbers_list = _to_list(self.TimberBrep)

            # Tools = Align1_AlignedTool + Align2_AlignedTool + [GeoAligner1_MovedGeo]
            tools_flat = []

            if isinstance(self.Align1_AlignedTool, list):
                for t in self.Align1_AlignedTool:
                    if t is not None:
                        tools_flat.append(t)
            elif self.Align1_AlignedTool is not None:
                tools_flat.append(self.Align1_AlignedTool)

            if isinstance(self.Align2_AlignedTool, list):
                for t in self.Align2_AlignedTool:
                    if t is not None:
                        tools_flat.append(t)
            elif self.Align2_AlignedTool is not None:
                tools_flat.append(self.Align2_AlignedTool)

            if self.GeoAligner1_MovedGeo is not None:
                if isinstance(self.GeoAligner1_MovedGeo, list):
                    for t in self.GeoAligner1_MovedGeo:
                        if t is not None:
                            tools_flat.append(t)
                else:
                    tools_flat.append(self.GeoAligner1_MovedGeo)

            if len(tools_flat) == 0:
                self.Log.append("[CUT] Tools 为空，跳过切割。")
                return self

            keep_inside_raw = self.AllDict.get("FT_CutTimberByTools_V2__KeepInside", False)
            try:
                _keep_inside_flag = bool(keep_inside_raw)
            except:
                _keep_inside_flag = False

            cutter = FT_CutTimberByTools_V2(
                timbers_list,
                tools_flat,
                keep_inside=_keep_inside_flag
            )

            CutTimbers, FailTimbers, CutLog = cutter.run()

            self.CutTimbers = CutTimbers
            self.FailTimbers = FailTimbers

            self.Log.append("[CUT] FT_CutTimberByTools_V2 完成")
            if CutLog:
                for l in CutLog:
                    self.Log.append("[CUT] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step5_gongyan_and_cut · FT_CutTimberByTools_V2 出错: {}".format(e))

        return self

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def run(self):

        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤未执行。")
            return self

        # Step 2：原始木料
        self.step2_timber_block_uniform()

        # Step 3：卷殺
        self.step3_juan_sha()

        # Step 4：BlockCutter
        self.step4_block_cutter()

        # Step 5：栱眼 + 切割
        self.step5_gongyan_and_cut()

        return self


# ==============================================================
# GH Python 组件 · 输出绑定区
# ==============================================================

if __name__ == "__main__":
    solver = LingGong_DouKouTiaoSolver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # ---- 最终输出 ----
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers

    # ---- 日志 ----
    Log = solver.Log

    # ---- Step 1：数据库调试输出 ----
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # ---- Step 2：FT_timber_block_uniform 调试输出 ----
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

    # ---- Step 3：JuanShaToolBuilder 调试输出 ----
    JuanShaToolBrep = solver.JuanShaToolBrep
    JuanShaSectionEdges = solver.JuanShaSectionEdges
    JuanShaHL_Intersection = solver.JuanShaHL_Intersection
    JuanShaHeightFacePlane = solver.JuanShaHeightFacePlane
    JuanShaLengthFacePlane = solver.JuanShaLengthFacePlane
    JuanShaLog = solver.JuanShaLog

    # ---- Step 3：PlaneFromLists::1 调试输出 ----
    PF1_BasePlane = solver.PF1_BasePlane
    PF1_OriginPoint = solver.PF1_OriginPoint
    PF1_ResultPlane = solver.PF1_ResultPlane
    PF1_Log = solver.PF1_Log

    # ---- Step 3：FT_AlignToolToTimber::1 调试输出 ----
    Align1_AlignedTool = solver.Align1_AlignedTool
    Align1_XForm = solver.Align1_XForm
    Align1_SourcePlane = solver.Align1_SourcePlane
    Align1_TargetPlane = solver.Align1_TargetPlane
    Align1_SourcePoint = solver.Align1_SourcePoint
    Align1_TargetPoint = solver.Align1_TargetPoint
    Align1_DebugInfo = solver.Align1_DebugInfo

    # ---- Step 4：FT_BlockCutter 调试输出 ----
    BlockCutter_TimberBrep = solver.BlockCutter_TimberBrep
    BlockCutter_FacePlaneList = solver.BlockCutter_FacePlaneList
    BlockCutter_Log = solver.BlockCutter_Log

    # ---- Step 4：FT_AlignToolToTimber::2 调试输出 ----
    Align2_AlignedTool = solver.Align2_AlignedTool
    Align2_XForm = solver.Align2_XForm
    Align2_SourcePlane = solver.Align2_SourcePlane
    Align2_TargetPlane = solver.Align2_TargetPlane
    Align2_SourcePoint = solver.Align2_SourcePoint
    Align2_TargetPoint = solver.Align2_TargetPoint
    Align2_DebugInfo = solver.Align2_DebugInfo

    # ---- Step 5：FT_GongYanSection_Cai_B 调试输出 ----
    GongYan_SectionFace = solver.GongYan_SectionFace
    GongYan_OffsetFace = solver.GongYan_OffsetFace
    GongYan_Points = solver.GongYan_Points
    GongYan_OffsetPoints = solver.GongYan_OffsetPoints
    GongYan_ToolBrep = solver.GongYan_ToolBrep
    GongYan_BridgePoints = solver.GongYan_BridgePoints
    GongYan_BridgeMidPoints = solver.GongYan_BridgeMidPoints
    GongYan_BridgePlane = solver.GongYan_BridgePlane
    GongYan_Log = solver.GongYan_Log

    # ---- Step 5：PlaneFromLists::2 调试输出 ----
    PF2_BasePlane = solver.PF2_BasePlane
    PF2_OriginPoint = solver.PF2_OriginPoint
    PF2_ResultPlane = solver.PF2_ResultPlane
    PF2_Log = solver.PF2_Log

    # ---- Step 5：PlaneFromLists::3 调试输出 ----
    PF3_BasePlane = solver.PF3_BasePlane
    PF3_OriginPoint = solver.PF3_OriginPoint
    PF3_ResultPlane = solver.PF3_ResultPlane
    PF3_Log = solver.PF3_Log

    # ---- Step 5：GeoAligner::1 调试输出 ----
    GeoAligner1_SourceOut = solver.GeoAligner1_SourceOut
    GeoAligner1_TargetOut = solver.GeoAligner1_TargetOut
    GeoAligner1_MovedGeo = solver.GeoAligner1_MovedGeo



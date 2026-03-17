# -*- coding: utf-8 -*-
"""
ROUND_ANG_LU_Solver —— 角圓櫨枓一体化求解器 · Step1 + Step2 + Step3（耳平）

Step 1:
    使用 DBJsonReader 从 DG_Dou / ROUND_ANG_LU / params_json 读取参数，
    并展开为 All（[(key, value), ...]），构造 All_dict 供后续 all_get() 使用。

Step 2:
    原始木料构建（FT_timber_block_uniform）：
        length_fen = CleanTree_FT_timber_block_uniform__length_fen
        width_fen  = CleanTree_FT_timber_block_uniform__width_fen
        height_fen = CleanTree_FT_timber_block_uniform__height_fen
        base_point = 组件输入 base_point（无则取原点）
        reference_plane = GH 默认 XZ Plane
            X = (1, 0, 0)
            Y = (0, 0, 1)
            Z = (0,-1, 0)

Step 3（耳平部分）：
    3.1 FT_BlockCutter
    3.2 PlaneFromLists::1（主木坯）
    3.3 PlaneFromLists::2（BlockCutter）
    3.4 FT_AlignToolToTimber::1
    3.5 FT_CutTimberByTools::1

GhPython 输入：
    DBPath     : str       - SQLite 数据库路径
    base_point : Point3d   - 木料定位点
    Refresh    : bool      - 预留刷新按钮

GhPython 输出（建议至少包含）：
    Step1: Value, All, All_dict
    Step2: TimberBrep, FaceList, PointList, EdgeList, ...
    Step3: 各组件输出（BlockTimberBreps, BasePlane1/2, AlignedTool1, CutTimbers, FailTimbers 等）
"""

import Rhino.Geometry as rg
from yingzao.ancientArchi import (
    DBJsonReader,
    FTPlaneFromLists,
    FTAligner,
    FT_CutTimberByTools,
    build_timber_block_uniform,
    YinCornerToolPlaneCalculator,
    InscribedCylinderInBox,
    build_qi_ao_circular_revolve
)


# ---------- 基础工具（全局方法，供 Step3 使用） ----------
def _to_list(x):
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _param_length(v):
    if v is None:
        return 0
    if isinstance(v, (list, tuple)):
        return len(v)
    return 1


def _broadcast(v, n):
    if isinstance(v, (list, tuple)):
        seq = list(v)
        if len(seq) == 0:
            return [None] * n
        if len(seq) >= n:
            return seq[:n]
        return seq + [seq[-1]] * (n - len(seq))
    return [v] * n


# =============================================================================
# 主 Solver 类
# =============================================================================

class RoundAngLuSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):

        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # 固定最终输出
        self.CutTimbers = []
        self.FailTimbers = []
        self.Log = []

        # -------- Step 1: DBJsonReader 结果 --------
        self.Value = None
        self.All = None  # list[(key, value), ...]
        self.All_dict = {}  # dict[key] = value
        self.Log_DB = []  # DBJsonReader 日志（若有）

        # -------- Step 2: FT_timber_block_uniform 结果 --------
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

        # -------- Step 3: 预初始化（可选，不是必须，但有助于调试） --------
        self.BlockTimberBreps = []
        self.BlockFaceList = []
        self.BlockPointList = []
        self.BlockEdgeList = []
        self.BlockCenterPoint = []
        self.BlockCenterAxisLines = []
        self.BlockEdgeMidPoints = []
        self.BlockFacePlaneList = []
        self.BlockCorner0Planes = []
        self.BlockLocalAxesPlane = []
        self.BlockAxisX = []
        self.BlockAxisY = []
        self.BlockAxisZ = []
        self.BlockFaceDirTags = []
        self.BlockEdgeDirTags = []
        self.BlockCorner0EdgeDirs = []

        self.BasePlane1 = []
        self.OriginPoint1 = []
        self.ResultPlane1 = []

        self.BasePlane2 = []
        self.OriginPoint2 = []
        self.ResultPlane2 = []

        self.AlignedTool1 = []
        self.XForm1 = []
        self.SourcePlane1 = []
        self.TargetPlane1 = []
        self.SourcePoint1 = []
        self.TargetPoint1 = []
        self.DebugInfo1 = []

    # ----------------------------------------------------------------------
    # 从 All_dict 中按 key 取值
    # ----------------------------------------------------------------------
    def all_get(self, name, default=None):
        return self.All_dict.get(name, default)

    # ======================================================================
    # Step 1: DBJsonReader
    # ======================================================================
    def step1_read_db(self):

        self.Log.append("===== Step 1: DBJsonReader (ROUND_ANG_LU) =====")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="DG_Dou",
            key_field="type_code",
            key_value="ROUND_ANG_LU",
            field="params_json",
            json_path=[],
            export_all=True,
            ghenv=self.ghenv
        )

        # 与原 DBJsonReader 组件保持同样调用方式
        self.Value, self.All, db_log = reader.run()

        # 记录 DBJsonReader 日志
        if isinstance(db_log, (list, tuple)):
            self.Log_DB = list(db_log)
            for line in self.Log_DB:
                self.Log.append("[DB] " + str(line))
        elif db_log:
            self.Log.append("[DB] " + str(db_log))

        if not self.All:
            self.Log.append("Step 1: All 为空，可能没有 ROUND_ANG_LU 的记录。")
            self.All_dict = {}
        else:
            self.All_dict = dict(self.All)
            self.Log.append("Step 1: All 共读取 {} 项参数。".format(len(self.All)))

    # ======================================================================
    # Step 2: FT_timber_block_uniform（原始木料构建）
    # ======================================================================
    def step2_timber_block_uniform(self):

        self.Log.append("===== Step 2: FT_timber_block_uniform =====")

        # ==========================================================
        # 1) 木料尺寸优先级：
        #    （当前组件没有长度输入端，所以是：数据库 → 默认值）
        #    兼容 CleanTree_ 前缀 和 原始 key 两种写法
        # ==========================================================

        # length_fen
        L_raw = self.all_get("CleanTree_FT_timber_block_uniform__length_fen", None)
        if L_raw is None:
            L_raw = self.all_get("FT_timber_block_uniform__length_fen", None)

        # width_fen
        W_raw = self.all_get("CleanTree_FT_timber_block_uniform__width_fen", None)
        if W_raw is None:
            W_raw = self.all_get("FT_timber_block_uniform__width_fen", None)

        # height_fen
        H_raw = self.all_get("CleanTree_FT_timber_block_uniform__height_fen", None)
        if H_raw is None:
            H_raw = self.all_get("FT_timber_block_uniform__height_fen", None)

        # 数据库 → 默认值
        length_fen = float(L_raw) if L_raw is not None else 32.0
        width_fen = float(W_raw) if W_raw is not None else 32.0
        height_fen = float(H_raw) if H_raw is not None else 20.0

        # 2) base_point：优先组件输入端 → 默认原点
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        elif isinstance(bp, rg.Point):
            bp = bp.Location
        elif isinstance(bp, rg.Point3d):
            pass
        else:
            self.Log.append("[Step2] base_point 类型异常，使用默认原点。")
            bp = rg.Point3d(0.0, 0.0, 0.0)

        # 3) 明确构造 GH XZ Plane
        origin = rg.Point3d(0.0, 0.0, 0.0)
        x_axis = rg.Vector3d(1.0, 0.0, 0.0)
        y_axis = rg.Vector3d(0.0, 0.0, 1.0)
        reference_plane = rg.Plane(origin, x_axis, y_axis)

        # 4) 调用 build_timber_block_uniform
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

            # 保存为成员变量（对应原组件输出端）
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

            # 将内部 log_lines 也写入总体 Log
            if log_lines:
                for l in log_lines:
                    self.Log.append("[Timber] " + str(l))

            self.Log.append(
                "Step 2: 木坯生成成功 (L={}, W={}, H={})，定位点 = ({:.3f}, {:.3f}, {:.3f})".format(
                    length_fen, width_fen, height_fen, bp.X, bp.Y, bp.Z
                )
            )

        except Exception as e:
            self.Log.append("[Timber] 错误: {}".format(e))

            # 出错时清空几何数据
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

    # ======================================================================
    # Step 3.1 —— FT_BlockCutter（木块耳平）
    # ======================================================================
    def step3_block_cutter(self):
        self.Log.append("===== Step 3.1：FT_BlockCutter =====")

        # 从数据库读取 cutter 的长宽高
        L_raw = self.all_get("FT_BlockCutter__length_fen", 32.0)
        W_raw = self.all_get("FT_BlockCutter__width_fen", 32.0)
        H_raw = self.all_get("FT_BlockCutter__height_fen", 20.0)

        Nc = max(_param_length(L_raw), _param_length(W_raw), _param_length(H_raw))
        Nc = max(Nc, 1)

        L_list = _broadcast(L_raw, Nc)
        W_list = _broadcast(W_raw, Nc)
        H_list = _broadcast(H_raw, Nc)

        # GH XZ plane
        origin = rg.Point3d(0, 0, 0)
        ref_plane = rg.Plane(origin, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)

        # Tree 型存储
        self.BlockTimberBreps = []
        self.BlockFaceList = []
        self.BlockPointList = []
        self.BlockEdgeList = []
        self.BlockCenterPoint = []
        self.BlockCenterAxisLines = []
        self.BlockEdgeMidPoints = []
        self.BlockFacePlaneList = []
        self.BlockCorner0Planes = []
        self.BlockLocalAxesPlane = []
        self.BlockAxisX = []
        self.BlockAxisY = []
        self.BlockAxisZ = []
        self.BlockFaceDirTags = []
        self.BlockEdgeDirTags = []
        self.BlockCorner0EdgeDirs = []

        for i in range(Nc):
            Li, Wi, Hi = L_list[i], W_list[i], H_list[i]

            (
                brep,
                faces,
                points,
                edges,
                cpt,
                caxes,
                edge_mid,
                face_planes,
                corner_planes,
                local_axes,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                Li, Wi, Hi,
                rg.Point3d(0, 0, 0),
                ref_plane
            )

            self.BlockTimberBreps.append(brep)
            self.BlockFaceList.append(faces)
            self.BlockPointList.append(points)
            self.BlockEdgeList.append(edges)
            self.BlockCenterPoint.append(cpt)
            self.BlockCenterAxisLines.append(caxes)
            self.BlockEdgeMidPoints.append(edge_mid)
            self.BlockFacePlaneList.append(face_planes)
            self.BlockCorner0Planes.append(corner_planes)
            self.BlockLocalAxesPlane.append(local_axes)
            self.BlockAxisX.append(axis_x)
            self.BlockAxisY.append(axis_y)
            self.BlockAxisZ.append(axis_z)
            self.BlockFaceDirTags.append(face_tags)
            self.BlockEdgeDirTags.append(edge_tags)
            self.BlockCorner0EdgeDirs.append(corner_dirs)

            for l in log_lines:
                self.Log.append(f"[BlockCutter][{i}] {l}")

    # ======================================================================
    # Step 3.2 —— PlaneFromLists::1（用主木坯 EdgeMidPoints + Corner0Planes）
    # ======================================================================
    def step3_pfl1(self):
        self.Log.append("===== Step 3.2：PlaneFromLists::1 =====")

        idx_O = _to_list(self.all_get("PlaneFromLists_1__IndexOrigin", []))
        idx_P = _to_list(self.all_get("PlaneFromLists_1__IndexPlane", []))
        wrap = bool(self.all_get("PlaneFromLists_1__wrap", True))

        n = min(len(idx_O), len(idx_P))
        if n == 0:
            self.BasePlane1 = []
            self.OriginPoint1 = []
            self.ResultPlane1 = []
            self.Log.append("[PFL1] 无有效索引，跳过。")
            return

        builder = FTPlaneFromLists(wrap=wrap)

        self.BasePlane1 = []
        self.OriginPoint1 = []
        self.ResultPlane1 = []

        for i in range(n):
            base, org, res, logp = builder.build_plane(
                self.EdgeMidPoints,
                self.Corner0Planes,
                idx_O[i],
                idx_P[i]
            )
            self.BasePlane1.append(base)
            self.OriginPoint1.append(org)
            self.ResultPlane1.append(res)

            for l in logp:
                self.Log.append(f"[PFL1][{i}] {l}")

                # ======================================================================

    # Step 3.3 —— PlaneFromLists::2（用 BlockCutter 的 EdgeMidPoints + Corner0Planes）
    #   规则：
    #       · PlaneFromLists_2__IndexOrigin / PlaneFromLists_2__IndexPlane 为单个索引值
    #       · BlockEdgeMidPoints / BlockCorner0Planes 为「嵌套列表」
    #         外层维度 = BlockCutter 数量
    #       · 对每一个 BlockCutter 分支，用同一对索引，从各自子列表中取点和平面
    # ======================================================================
    def step3_pfl2(self):
        self.Log.append("===== Step 3.3：PlaneFromLists::2 =====")

        # 从 All 中取出索引值（允许是标量或长度为 1 的列表）
        idxO_raw = self.all_get("PlaneFromLists_2__IndexOrigin", 0)
        idxP_raw = self.all_get("PlaneFromLists_2__IndexPlane", 0)
        wrap = bool(self.all_get("PlaneFromLists_2__wrap", True))

        def _as_index(v, default=0):
            """支持：标量 / 列表 / 元组；列表则取第一个元素。"""
            if v is None:
                return int(default)
            if isinstance(v, (list, tuple)):
                if len(v) == 0:
                    return int(default)
                return int(v[0])
            return int(v)

        idxO = _as_index(idxO_raw, 0)
        idxP = _as_index(idxP_raw, 0)

        # 若没有任何 BlockCutter 分支，直接退出
        n_cutters = len(self.BlockEdgeMidPoints) if self.BlockEdgeMidPoints else 0
        if n_cutters == 0:
            self.BasePlane2 = []
            self.OriginPoint2 = []
            self.ResultPlane2 = []
            self.Log.append("[PFL2] BlockEdgeMidPoints 为空，跳过。")
            return

        builder = FTPlaneFromLists(wrap=wrap)

        self.BasePlane2 = []
        self.OriginPoint2 = []
        self.ResultPlane2 = []

        # 对每一个 BlockCutter 分支，分别调用一次 build_plane
        for i in range(n_cutters):
            origin_pts = self.BlockEdgeMidPoints[i] if i < len(self.BlockEdgeMidPoints) else []
            base_planes = self.BlockCorner0Planes[i] if i < len(self.BlockCorner0Planes) else []

            base, org, res, logp = builder.build_plane(
                origin_pts,  # 当前 cutter 的 EdgeMidPoints 子列表
                base_planes,  # 当前 cutter 的 Corner0Planes 子列表
                idxO,
                idxP
            )

            self.BasePlane2.append(base)
            self.OriginPoint2.append(org)
            self.ResultPlane2.append(res)

            if logp:
                for l in logp:
                    self.Log.append(f"[PFL2][{i}] {l}")

    # ======================================================================
    # Step 3.4 —— FT_AlignToolToTimber::1
    # ======================================================================
    def step3_align1(self):
        self.Log.append("===== Step 3.4：FT_AlignToolToTimber::1 =====")

        # 对位输入来自数据库
        BlockRot_raw = self.all_get("FT_AlignToolToTimber_1__BlockRotDeg", 0)
        FlipX_raw = self.all_get("FT_AlignToolToTimber_1__FlipX", 0)
        FlipY_raw = self.all_get("FT_AlignToolToTimber_1__FlipY", 0)
        FlipZ_raw = self.all_get("FT_AlignToolToTimber_1__FlipZ", 0)

        # 工具是 BlockCutter Breps
        ToolGeo = self.BlockTimberBreps
        tool_n = len(ToolGeo)

        N = max(tool_n, 1)

        ToolGeo_list = _broadcast(ToolGeo, N)
        ToolBasePlane = _broadcast(self.ResultPlane2, N)
        BlockFacePlane = _broadcast(self.ResultPlane1, N)
        BlockRot = _broadcast(BlockRot_raw, N)
        FlipX = _broadcast(FlipX_raw, N)
        FlipY = _broadcast(FlipY_raw, N)
        FlipZ = _broadcast(FlipZ_raw, N)

        self.AlignedTool1 = []
        self.XForm1 = []
        self.SourcePlane1 = []
        self.TargetPlane1 = []
        self.SourcePoint1 = []
        self.TargetPoint1 = []
        self.DebugInfo1 = []

        for i in range(N):
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                ToolGeo_list[i],
                ToolBasePlane[i],
                None,  # ToolContactPoint
                BlockFacePlane[i],
                None,  # BlockTargetPoint
                None, None, None, None, None, None,
                FlipX[i], FlipY[i], FlipZ[i],
                None,  # ToolRotDeg
                BlockRot[i],
            )

            self.AlignedTool1.append(aligned)
            self.XForm1.append(xf)
            self.SourcePlane1.append(src_pl)
            self.TargetPlane1.append(tgt_pl)
            self.SourcePoint1.append(src_pt)
            self.TargetPoint1.append(tgt_pt)
            self.DebugInfo1.append(dbg)

    # ======================================================================
    # Step 3.5 —— FT_CutTimberByTools::1
    # ======================================================================
    def step3_cut1(self):
        self.Log.append("===== Step 3.5：FT_CutTimberByTools::1 =====")

        cutter = FT_CutTimberByTools(self.TimberBrep, self.AlignedTool1)
        self.CutTimbers, self.FailTimbers, logc = cutter.run()

        for l in logc:
            self.Log.append(f"[Cut1] {l}")

    # ======================================================================
    # Step 4.1 —— FT_Yin（廕）刀具平面生成
    # ======================================================================
    def step4_yin(self):

        self.Log.append("===== Step 4.1：FT_Yin（廕） =====")

        # 读取索引：FT_Yin_IDX__Index → 两个点
        idx_raw = self.all_get("FT_Yin_IDX__Index", [])
        idx_list = _to_list(idx_raw)

        if len(idx_list) < 2:
            self.Log.append("[YIN] 索引数量不足 2，无法形成 Diag。")
            self.YinToolPlanes = []
            return

        iA, iB = idx_list[0], idx_list[1]

        # 从主木料 PointList 取两个点
        try:
            ptA = self.PointList[iA]
            ptB = self.PointList[iB]
        except:
            self.Log.append("[YIN] 索引超出 PointList 范围。")
            self.YinToolPlanes = []
            return

        # 构造折线
        import Rhino.Geometry as rg
        diag_curve = rg.Polyline([ptA, ptB]).ToNurbsCurve()

        # 参数
        ToolWidth = float(self.all_get("FT_Yin__ToolWidth", 10.0))
        YinValue = float(self.all_get("FT_Yin__Yin", 0.5))
        ShapeMode = int(self.all_get("FT_Yin__ShapeMode", 0))

        from yingzao.ancientArchi import YinCornerToolPlaneCalculator

        calc = YinCornerToolPlaneCalculator(
            diag_curve, ToolWidth, YinValue, ShapeMode
        )

        ToolPlanes, logY = calc.run()

        self.YinToolPlanes = ToolPlanes
        for l in logY:
            self.Log.append("[YIN] " + str(l))

    # ======================================================================
    # Step 4.2 —— FT_AlignToolToTimber::2
    # ======================================================================
    def step4_align2(self):

        self.Log.append("===== Step 4.2：FT_AlignToolToTimber::2 =====")

        # 索引取 ToolGeo
        tool_idx = self.all_get("ToolGeo_IDX__Index", 0)
        tool_idx = int(tool_idx)

        try:
            ToolGeo_raw = self.BlockTimberBreps[tool_idx]
        except:
            self.Log.append("[Align2] ToolGeo index 超出范围。")
            self.AlignedTool2 = []
            return

        # 索引取 ToolBasePlane
        base_idx = self.all_get("ToolBasePlane_IDX__Index", 0)
        base_idx = int(base_idx)

        try:
            ToolBasePlane_raw = self.ResultPlane2[base_idx]
        except:
            self.Log.append("[Align2] ToolBasePlane index 超出范围。")
            self.AlignedTool2 = []
            return

        # BlockFacePlane = Yin 生成的刀具方向平面
        BlockFacePlane_raw = self.YinToolPlanes

        # 参数
        BlockRot_raw = self.all_get("FT_AlignToolToTimber_2__BlockRotDeg", 0)
        FlipY_raw = self.all_get("FT_AlignToolToTimber_2__FlipY", 0)
        FlipZ_raw = self.all_get("FT_AlignToolToTimber_2__FlipZ", 0)

        # 广播
        N = max(
            _param_length(BlockFacePlane_raw),
            1
        )

        ToolGeo_list = _broadcast(ToolGeo_raw, N)
        ToolBasePlane_list = _broadcast(ToolBasePlane_raw, N)
        BlockPlanes_list = _broadcast(BlockFacePlane_raw, N)
        BlockRot_list = _broadcast(BlockRot_raw, N)
        FlipY_list = _broadcast(FlipY_raw, N)
        FlipZ_list = _broadcast(FlipZ_raw, N)

        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []

        for i in range(N):
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                ToolGeo_list[i],
                ToolBasePlane_list[i],
                None,  # ToolContactPoint
                BlockPlanes_list[i],  # BlockFacePlane
                None, None, None, None, None, None, None,
                0,  # FlipX 无此参数，固定为0
                FlipY_list[i],
                FlipZ_list[i],
                None,  # ToolRotDeg
                BlockRot_list[i],
            )

            self.AlignedTool2.append(aligned)
            self.XForm2.append(xf)
            self.SourcePlane2.append(src_pl)
            self.TargetPlane2.append(tgt_pl)
            self.SourcePoint2.append(src_pt)
            self.TargetPoint2.append(tgt_pt)
            self.DebugInfo2.append(dbg)

    # ======================================================================
    # Step 4.3 —— FT_CutTimberByTools::2
    # ======================================================================
    def step4_cut2(self):

        self.Log.append("===== Step 4.3：FT_CutTimberByTools::2 =====")

        cutter = FT_CutTimberByTools(
            self.CutTimbers,  # 上一步的木料
            self.AlignedTool2  # Step 4.2 对位刀具
        )

        Cut2, Fail2, log2 = cutter.run()

        self.CutTimbers2 = Cut2
        self.FailTimbers2 = Fail2

        for l in log2:
            self.Log.append("[Cut2] " + str(l))

    # ======================================================================
    # Step 5.1 —— FT_InscribedCylinderInBox（在木坯盒内求内接圆柱）
    # ======================================================================
    def step5_inscribed_cylinder(self):

        self.Log.append("===== Step 5.1：FT_InscribedCylinderInBox =====")

        # 按你给的组件：BoxGeo 来自 FT_timber_block_uniform 的 TimberBrep
        box_geo = self.TimberBrep

        # 预设输出
        self.InscribedCylBrep = None
        self.InscribedAxis = None
        self.InscribedBaseCircle = None
        self.InscribedCylinderLog = []

        if box_geo is None:
            msg = "[Inscribed] 提示：BoxGeo（TimberBrep）为空，无法求内接圆柱。"
            self.InscribedCylinderLog.append(msg)
            self.Log.append(msg)
            return

        # FaceIndex：若 JSON 中有配置，则优先采用，否则默认 0
        face_idx_raw = self.all_get("FT_InscribedCylinderInBox__FaceIndex", None)
        try:
            face_index = int(face_idx_raw) if face_idx_raw is not None else 0
        except:
            face_index = 0

        try:
            solver = InscribedCylinderInBox(box_geo, face_index)
            cyl_brep, axis, base_circle, log_lines = solver.run()

            self.InscribedCylBrep = cyl_brep
            self.InscribedAxis = axis
            self.InscribedBaseCircle = base_circle
            self.InscribedCylinderLog = log_lines or []

            for l in self.InscribedCylinderLog:
                self.Log.append("[Inscribed] " + str(l))

        except Exception as e:
            msg = "[Inscribed] 计算内接圆柱时出错: {}".format(e)
            self.InscribedCylinderLog.append(msg)
            self.Log.append(msg)
            self.InscribedCylBrep = None
            self.InscribedAxis = None
            self.InscribedBaseCircle = None

    # ======================================================================
    # Step 5.2 —— FT_CutTimberByTools::3（用圆柱切出圆形枓，KeepInside=True）
    # ======================================================================
    def step5_cut3(self):

        self.Log.append("===== Step 5.2：FT_CutTimberByTools::3 =====")

        # Timbers：来自上一步（Step 4）的 CutTimbers2
        timbers = getattr(self, "CutTimbers2", None)
        tools = self.InscribedCylBrep

        if not timbers or tools is None:
            self.Log.append("[Cut3] Timbers 或工具几何为空，跳过切割。")
            self.CutTimbers3 = timbers if timbers is not None else []
            self.FailTimbers3 = []
            return

        # KeepInside 固定 True（按你的描述）
        keep_inside_flag = True

        try:
            cutter = FT_CutTimberByTools(timbers, tools, keep_inside=keep_inside_flag)
            cut3, fail3, log3 = cutter.run()

            self.CutTimbers3 = cut3
            self.FailTimbers3 = fail3

            for l in log3:
                self.Log.append("[Cut3] " + str(l))

        except Exception as e:
            self.Log.append("[Cut3] 切割出错: {}".format(e))
            self.CutTimbers3 = []
            self.FailTimbers3 = timbers

    # ======================================================================
    # Step 6.1 —— FT_QiAo_CircularRevolve_DualDiag（圆形欹䫜刀具生成）
    # ======================================================================
    def step6_qi_ao_circular(self):

        self.Log.append("===== Step 6.1：FT_QiAo_CircularRevolve_DualDiag =====")

        # 读取参数
        qi_height = float(self.all_get("FT_QiAo_CircularRevolve_DualDiag__qi_height", 8.0))
        sha_width = float(self.all_get("FT_QiAo_CircularRevolve_DualDiag__sha_width", 4.0))
        radius = float(self.all_get("FT_QiAo_CircularRevolve_DualDiag__radius", 36.0 / 2.0))
        QiDirInward = bool(self.all_get("FT_QiAo_CircularRevolve_DualDiag__QiDirInward", True))

        # 默认 base_point = (0,0,0)
        base_point = rg.Point3d(0, 0, 0)

        # reference_plane：使用 Step2 的构造
        ref_plane = rg.Plane(rg.Point3d(0, 0, 0),
                             rg.Vector3d(1, 0, 0),
                             rg.Vector3d(0, 0, 1))

        from yingzao.ancientArchi import build_qi_ao_circular_revolve

        ToolBrep = None
        BasePoint = None
        BaseLine = None
        SecPlane = None
        CirclePlane = None

        try:
            ToolBrep, BasePoint, BaseLine, SecPlane, CirclePlane, logY = \
                build_qi_ao_circular_revolve(
                    qi_height,
                    sha_width,
                    base_point,
                    radius,
                    ref_plane,
                    QiDirInward,
                    log=[]
                )

            self.CircularToolBrep = ToolBrep
            self.CircularBasePoint = BasePoint
            self.CircularBaseLine = BaseLine
            self.CircularSecPlane = SecPlane
            self.CircularCirclePlane = CirclePlane

            for l in logY:
                self.Log.append("[QiAoCircular] " + str(l))

        except Exception as e:
            self.Log.append("[QiAoCircular] 错误: {}".format(e))
            self.CircularToolBrep = None
            self.CircularBasePoint = None
            self.CircularBaseLine = None
            self.CircularSecPlane = None
            self.CircularCirclePlane = None

    # ======================================================================
    # Step 6.2 —— FT_AlignToolToTimber::3 （圆形欹䫜对位）
    # ======================================================================
    def step6_align3(self):

        self.Log.append("===== Step 6.2：FT_AlignToolToTimber::3 =====")

        # ToolGeo = Step 6.1 生成的 ToolBrep
        ToolGeo_raw = self.CircularToolBrep
        if ToolGeo_raw is None:
            self.Log.append("[Align3] 无 ToolBrep，跳过。")
            self.AlignedTool3 = []
            return

        # ToolBasePlane = CirclePlane
        ToolBasePlane_raw = self.CircularCirclePlane

        # BlockFacePlane：由数据库给出 index，提取 Step2.FacePlaneList
        idx_raw = self.all_get("BlockFacePlane__Index", [])
        idx_list = _to_list(idx_raw)

        BlockFacePlane_raw = []
        for idx in idx_list:
            try:
                BlockFacePlane_raw.append(self.FacePlaneList[int(idx)])
            except:
                BlockFacePlane_raw.append(None)

        # FlipZ 参数
        FlipZ_raw = self.all_get("FT_AlignToolToTimber_3__FlipZ", 0)

        # 广播
        N = max(
            _param_length(BlockFacePlane_raw),
            1
        )

        ToolGeo_list = _broadcast(ToolGeo_raw, N)
        ToolBasePlane_list = _broadcast(ToolBasePlane_raw, N)
        BlockPlanes_list = _broadcast(BlockFacePlane_raw, N)
        FlipZ_list = _broadcast(FlipZ_raw, N)

        self.AlignedTool3 = []
        self.XForm3 = []
        self.SourcePlane3 = []
        self.TargetPlane3 = []
        self.SourcePoint3 = []
        self.TargetPoint3 = []
        self.DebugInfo3 = []

        for i in range(N):
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                ToolGeo_list[i],
                ToolBasePlane_list[i],
                None,  # ToolContactPoint
                BlockPlanes_list[i],  # BlockFacePlane
                None, None, None, None, None, None, None,
                0, 0, FlipZ_list[i],  # FlipX=0, FlipY=0, FlipZ=FlipZ_list[i]
                None,  # ToolRotDeg
                None  # BlockRotDeg
            )

            self.AlignedTool3.append(aligned)
            self.XForm3.append(xf)
            self.SourcePlane3.append(src_pl)
            self.TargetPlane3.append(tgt_pl)
            self.SourcePoint3.append(src_pt)
            self.TargetPoint3.append(tgt_pt)
            self.DebugInfo3.append(dbg)

    # ======================================================================
    # Step 6.3 —— FT_CutTimberByTools::4 （对圆形枓做欹䫜切削）
    # ======================================================================
    def step6_cut4(self):

        self.Log.append("===== Step 6.3：FT_CutTimberByTools::4 =====")

        # 输入 Timbers：Step5.2 的 CutTimbers3
        timbers = getattr(self, "CutTimbers3", None)
        tools = self.AlignedTool3

        if not timbers or not tools:
            self.Log.append("[Cut4] Timbers 或 Tools 为空，跳过切割。")
            self.CutTimbers4 = timbers if timbers else []
            self.FailTimbers4 = []
            return

        # KeepInside 默认 False（欹䫜切削一般为外削）
        keep_inside_flag = False

        try:
            cutter = FT_CutTimberByTools(timbers, tools, keep_inside=keep_inside_flag)
            cut4, fail4, log4 = cutter.run()

            self.CutTimbers4 = cut4
            self.FailTimbers4 = fail4

            for l in log4:
                self.Log.append("[Cut4] " + str(l))

        except Exception as e:
            self.Log.append("[Cut4] 错误: {}".format(e))
            self.CutTimbers4 = []
            self.FailTimbers4 = timbers

    # ----------------------------------------------------------------------
    # Solver 主流程
    # ----------------------------------------------------------------------
    def run(self):

        self.step1_read_db()
        self.step2_timber_block_uniform()

        # ========== Step 3 ==========
        self.step3_block_cutter()
        self.step3_pfl1()
        self.step3_pfl2()
        self.step3_align1()
        self.step3_cut1()

        # ========== Step 4 ==========
        self.step4_yin()
        self.step4_align2()
        self.step4_cut2()

        # === 在这里加上 Step 5 ===
        self.step5_inscribed_cylinder()
        self.step5_cut3()

        # ========== Step 6 ==========
        self.step6_qi_ao_circular()
        self.step6_align3()
        self.step6_cut4()

        return self


# =============================================================================
# GH PYTHON 组件输出绑定区
# =============================================================================

if __name__ == "__main__":
    # 执行当前已实现的所有步骤（Step1 + Step2 + Step3）
    solver = RoundAngLuSolver(DBPath, base_point, Refresh, ghenv).run()

    # -------- Step 1：DBJsonReader --------
    Value = solver.Value
    All = solver.All
    All_dict = solver.All_dict

    # -------- Step 2：FT_timber_block_uniform 原始木料 --------
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

    # -------- Step 3.1：FT_BlockCutter --------
    BlockTimberBreps = solver.BlockTimberBreps
    BlockFaceList = solver.BlockFaceList
    BlockPointList = solver.BlockPointList
    BlockEdgeList = solver.BlockEdgeList
    BlockCenterPoint = solver.BlockCenterPoint
    BlockCenterAxisLines = solver.BlockCenterAxisLines
    BlockEdgeMidPoints = solver.BlockEdgeMidPoints
    BlockFacePlaneList = solver.BlockFacePlaneList
    BlockCorner0Planes = solver.BlockCorner0Planes
    BlockLocalAxesPlane = solver.BlockLocalAxesPlane
    BlockAxisX = solver.BlockAxisX
    BlockAxisY = solver.BlockAxisY
    BlockAxisZ = solver.BlockAxisZ
    BlockFaceDirTags = solver.BlockFaceDirTags
    BlockEdgeDirTags = solver.BlockEdgeDirTags
    BlockCorner0EdgeDirs = solver.BlockCorner0EdgeDirs

    # -------- Step 3.2：PlaneFromLists::1 --------
    BasePlane1 = solver.BasePlane1
    OriginPoint1 = solver.OriginPoint1
    ResultPlane1 = solver.ResultPlane1

    # -------- Step 3.3：PlaneFromLists::2 --------
    BasePlane2 = solver.BasePlane2
    OriginPoint2 = solver.OriginPoint2
    ResultPlane2 = solver.ResultPlane2

    # -------- Step 3.4：FT_AlignToolToTimber::1 --------
    AlignedTool1 = solver.AlignedTool1
    XForm1 = solver.XForm1
    SourcePlane1 = solver.SourcePlane1
    TargetPlane1 = solver.TargetPlane1
    SourcePoint1 = solver.SourcePoint1
    TargetPoint1 = solver.TargetPoint1
    DebugInfo1 = solver.DebugInfo1

    # -------- Step 3.5：FT_CutTimberByTools::1 --------
    CutTimbers1 = solver.CutTimbers
    FailTimbers = solver.FailTimbers

    # -------- Step 4：FT_CutTimberByTools::1 --------
    YinToolPlanes = solver.YinToolPlanes

    AlignedTool2 = solver.AlignedTool2
    XForm2 = solver.XForm2
    SourcePlane2 = solver.SourcePlane2
    TargetPlane2 = solver.TargetPlane2
    SourcePoint2 = solver.SourcePoint2
    TargetPoint2 = solver.TargetPoint2
    DebugInfo2 = solver.DebugInfo2

    CutTimbers2 = solver.CutTimbers2
    FailTimbers2 = solver.FailTimbers2

    # -------- Step 5.1：FT_InscribedCylinderInBox --------
    InscribedCylBrep = solver.InscribedCylBrep
    InscribedAxis = solver.InscribedAxis
    InscribedBaseCircle = solver.InscribedBaseCircle
    InscribedCylinderLog = solver.InscribedCylinderLog

    # -------- Step 5.2：FT_CutTimberByTools::3 --------
    CutTimbers3 = solver.CutTimbers3
    FailTimbers3 = solver.FailTimbers3

    # -------- Step 6.1：FT_QiAo_CircularRevolve_DualDiag --------
    CircularToolBrep = solver.CircularToolBrep
    CircularBasePoint = solver.CircularBasePoint
    CircularBaseLine = solver.CircularBaseLine
    CircularSecPlane = solver.CircularSecPlane
    CircularCirclePlane = solver.CircularCirclePlane

    # -------- Step 6.2：FT_AlignToolToTimber::3 --------
    AlignedTool3 = solver.AlignedTool3
    XForm3 = solver.XForm3
    SourcePlane3 = solver.SourcePlane3
    TargetPlane3 = solver.TargetPlane3
    SourcePoint3 = solver.SourcePoint3
    TargetPoint3 = solver.TargetPoint3
    DebugInfo3 = solver.DebugInfo3

    # -------- Step 6.3：FT_CutTimberByTools::4 --------
    CutTimbers4 = solver.CutTimbers4
    FailTimbers4 = solver.FailTimbers4

    # -------- Log --------
    Log = solver.Log

    CutTimbers = CutTimbers4
    FailTimbers = FailTimbers4



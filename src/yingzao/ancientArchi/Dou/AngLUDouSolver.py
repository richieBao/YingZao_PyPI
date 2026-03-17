# -*- coding: utf-8 -*-
"""
AngLUDouSolver —— 角櫨枓一体化求解器 (Step 1 + Step 2 + Step 3 + Step 4)

步骤说明：
    Step 1: DBJsonReader 读取 DG_Dou 表中 ANG_LU_DOU 的 params_json
    Step 2: FT_timber_block_uniform —— 构造主木坯
    Step 3: PlaneFromLists::1 + FT_QiAo + FT_AlignToolToTimber::1 + FT_CutTimberByTools
    Step 4: FT_BlockCutter + PlaneFromLists::2 + PlaneFromLists::3
            + FT_AlignToolToTimber::2 + FT_CutTimberByTools::2

输入（GhPython）：
    DBPath     : str         - SQLite 数据库路径
    base_point : Point3d     - 主木坯定位点（优先于 DB 中的 base_point）
    Refresh    : bool        - 保留接口（目前未使用）

输出（见文末 __main__ 绑定区）
"""

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    build_qiao_tool,
    FTAligner,
    FT_CutTimberByTools,
    YinCornerToolPlaneCalculator
)


# ======================================================================
# 通用工具函数
# ======================================================================
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
    广播/截断参数到长度 n（与 FT_AlignToolToTimber 组件一致）：

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


def _scalar_from_list(val, default=None):
    """
    将可能为 list/tuple 的值收敛为标量：
    - list/tuple → 第一个元素
    - 其他类型：原样返回，None → default

    ⚠ 仅用于“本来就是标量语义”的参数：
       如 qi_height / sha_width / qi_offset_fen / extrude_length 等；
       不用于 FlipY / BlockRotDeg / IndexOrigin / IndexPlane 等
       需要循环或广播的参数。
    """
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) > 0 else default
    return val


def _normalize_flip_list(val, n, name="Flip"):
    """
    归一化 FlipX / FlipY / FlipZ 输入，保证：
    - None → [None] * n
    - 0 / False / "0" → "0"
    - 1 / True  / "1" → "1"
    - 其余值自动 string 化（与原组件行为保持一致）

    返回长度 n 的字符串列表或 None 列表。
    """
    lst = _broadcast_param(val, n, name)

    normalized = []
    for v in lst:
        if v is None:
            normalized.append(None)
        elif v in (0, "0", False):
            normalized.append("0")
        elif v in (1, "1", True):
            normalized.append("1")
        else:
            normalized.append(str(v))  # 避免 GH 中混入数字类型导致方向错位
    return normalized


# ======================================================================
# Solver 主类
# ======================================================================
class AngLUDouSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # ============ 全局日志 ============
        self.Log = []

        # ============ Step 1 ============
        self.Value = None  # DBJsonReader run() 返回的 Value
        self.All = None  # [(name, value), ...]
        self.All_dict = None  # 可选

        # ============ Step 2：主木坯 ============
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

        # ============ Step 3：PlaneFromLists::1 ============
        # 多项输出：每组索引对应一组
        self.BasePlane1 = []  # list[Plane]
        self.OriginPoint1 = []  # list[Point3d]
        self.ResultPlane1 = []  # list[Plane]

        # ============ FT_QiAo ============
        self.ToolBrep = None
        self.BasePoint = None
        self.BaseLine = None
        self.SecPlane = None
        self.FacePlane = None

        # ============ AlignToolToTimber::1 ============
        self.AlignedTool = []  # QiAo 刀具对位结果
        self.XForm = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo = []

        # ============ 切割（第 1 次） ============
        self.CutTimbers = []
        self.FailTimbers = []

        # ============ Step 4：FT_BlockCutter ============
        # 多个 cutter：几何用 BlockTimberBreps 列表保存
        self.BlockTimberBreps = []  # list[rg.Brep]

        # 为了给 PlaneFromLists::3 和输出做“代表性”信息，仍保留第一块的详细特征
        self.BlockTimberBrep = None  # 第 1 个 cutter
        self.BlockFaceList = []
        self.BlockPointList = []
        self.BlockEdgeList = []
        self.BlockCenterPoint = None
        self.BlockCenterAxisLines = []
        self.BlockEdgeMidPoints = []
        self.BlockFacePlaneList = []
        self.BlockCorner0Planes = []
        self.BlockLocalAxesPlane = None
        self.BlockAxisX = None
        self.BlockAxisY = None
        self.BlockAxisZ = None
        self.BlockFaceDirTags = []
        self.BlockEdgeDirTags = []
        self.BlockCorner0EdgeDirs = []

        # PlaneFromLists::2 —— 主木坯上的多个基准面
        self.BasePlane2 = []  # list[Plane]
        self.OriginPoint2 = []  # list[Point3d]
        self.ResultPlane2 = []  # list[Plane]

        # PlaneFromLists::3 —— BlockCutter 木块上的基准面
        self.BasePlane3 = []  # list[Plane]
        self.OriginPoint3 = []  # list[Point3d]
        self.ResultPlane3 = []  # list[Plane]

        # AlignToolToTimber::2 —— BlockCutter 对位
        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []

        # 第二次切割
        self.CutTimbers2 = []
        self.FailTimbers2 = []

    # ------------------------------------------------------------------
    # 从 All 中按名字取值：name 完全等于 All 中的 key
    # ------------------------------------------------------------------
    def all_get(self, name, default=None):
        """
        在 self.All（[(key, value), ...]）中查找名称为 name 的项。
        若找不到，返回 default。
        """
        if not self.All:
            return default
        for k, v in self.All:
            if k == name:
                return v
        return default

    # ==================================================================
    # Step 1 — 读取数据库 (DBJsonReader)
    # ==================================================================
    def step1_read_db(self):

        self.Log.append("===== Step 1: DBJsonReader =====")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="DG_Dou",
            key_field="type_code",
            key_value="ANG_LU_DOU",
            field="params_json",
            json_path=[],
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value, self.All, self.All_dict = reader.run()

        # 简单日志：确认 All 是否读取成功
        if self.All is None or len(self.All) == 0:
            self.Log.append("Step1: All 为空，可能数据库中没有 params_json。")
        else:
            self.Log.append("Step1: All 共读取 {} 项参数。".format(len(self.All)))
            sample_keys = [
                "FT_timber_block_uniform__length_fen",
                "FT_timber_block_uniform__width_fen",
                "FT_timber_block_uniform__height_fen",
                "PlaneFromLists_1__IndexOrigin",
                "PlaneFromLists_1__IndexPlane",
                "FT_AlignToolToTimber_1__BlockRotDeg",
                "FT_AlignToolToTimber_1__FlipY",
                "FT_BlockCutter__length_fen",
                "FT_BlockCutter__width_fen",
                "FT_BlockCutter__height_fen",
                "PlaneFromLists_2__IndexOrigin",
                "PlaneFromLists_2__IndexPlane",
                "PlaneFromLists_3__IndexOrigin",
                "PlaneFromLists_3__IndexPlane",
                "FT_AlignToolToTimber_2__BlockRotDeg",
                "FT_AlignToolToTimber_2__FlipX",
                "FT_AlignToolToTimber_2__FlipY",
            ]
            for sk in sample_keys:
                v = self.all_get(sk, None)
                self.Log.append("  [All] {} = {!r}".format(sk, v))

    # ==================================================================
    # Step 2 — 主木坯 FT_timber_block_uniform
    # ==================================================================
    def step2_timber(self):

        self.Log.append("===== Step 2: FT_timber_block_uniform =====")

        # 从 All 中读取参数
        L = self.all_get("FT_timber_block_uniform__length_fen", 36.0)
        W = self.all_get("FT_timber_block_uniform__width_fen", 36.0)
        H = self.all_get("FT_timber_block_uniform__height_fen", 20.0)

        # base_point：优先使用组件输入 base_point，其次 DB base_point
        db_bp = self.all_get("FT_timber_block_uniform__base_point", [0.0, 0.0, 0.0])
        if isinstance(db_bp, (list, tuple)) and len(db_bp) >= 3:
            db_base_pt = rg.Point3d(db_bp[0], db_bp[1], db_bp[2])
        else:
            db_base_pt = rg.Point3d(0.0, 0.0, 0.0)

        base_pt = self.base_point if self.base_point is not None else db_base_pt

        # reference_plane：暂时统一用 World XZ（和组件默认一致）
        ref_plane_name = self.all_get("FT_timber_block_uniform__reference_plane", "WorldXZ")
        ref_plane = rg.Plane(
            rg.Point3d(0, 0, 0),
            rg.Vector3d.XAxis,
            rg.Vector3d.ZAxis
        )

        try:
            (
                self.TimberBrep,
                self.FaceList,
                self.PointList,
                self.EdgeList,
                self.CenterPoint,
                self.CenterAxisLines,
                self.EdgeMidPoints,
                self.FacePlaneList,
                self.Corner0Planes,
                self.LocalAxesPlane,
                self.AxisX,
                self.AxisY,
                self.AxisZ,
                self.FaceDirTags,
                self.EdgeDirTags,
                self.Corner0EdgeDirs,
                log_lines
            ) = build_timber_block_uniform(L, W, H, base_pt, ref_plane)

            for l in log_lines:
                self.Log.append("[Timber] " + l)

        except Exception as e:
            self.Log.append("木坯构造失败: {}".format(e))

    # ==================================================================
    # Step 3 — PlaneFromLists::1 + FT_QiAo + Align::1 + Cut::1
    # ==================================================================
    def step3_qiao(self):

        self.Log.append("===== Step 3: PlaneFromLists::1 + FT_QiAo + Align::1 + Cut::1 =====")

        # --------------------------------------------------------------
        # 3.1 PlaneFromLists::1 —— 列表 index 一一对应执行
        # --------------------------------------------------------------
        idx_o_raw = self.all_get("PlaneFromLists_1__IndexOrigin", [])
        idx_p_raw = self.all_get("PlaneFromLists_1__IndexPlane", [])
        wrap_raw = self.all_get("PlaneFromLists_1__wrap", True)

        idx_o_list = _to_list(idx_o_raw)
        idx_p_list = _to_list(idx_p_raw)
        n_pf = min(len(idx_o_list), len(idx_p_list))

        if n_pf == 0:
            self.Log.append("[PFL1] IndexOrigin / IndexPlane 列表为空，跳过 PlaneFromLists::1。")
            self.BasePlane1 = []
            self.OriginPoint1 = []
            self.ResultPlane1 = []
        else:
            wrap = bool(_scalar_from_list(wrap_raw, True))
            builder = FTPlaneFromLists(wrap=wrap)

            self.BasePlane1 = []
            self.OriginPoint1 = []
            self.ResultPlane1 = []

            for i in range(n_pf):
                io = idx_o_list[i]
                ip = idx_p_list[i]
                self.Log.append(
                    "[PFL1] 第 {} 组：IndexOrigin = {}, IndexPlane = {}".format(i, io, ip)
                )

                base_pl, org_pt, res_pl, log_pf = builder.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip
                )

                self.BasePlane1.append(base_pl)
                self.OriginPoint1.append(org_pt)
                self.ResultPlane1.append(res_pl)

                for l in log_pf:
                    self.Log.append("[PFL1][{}] ".format(i) + l)

        # --------------------------------------------------------------
        # 3.2 FT_QiAo（欹䫜）
        # --------------------------------------------------------------
        qi_h_raw = self.all_get("FT_QiAo__qi_height", 8.0)
        sha_w_raw = self.all_get("FT_QiAo__sha_width", 4.0)
        qi_offset_raw = self.all_get("FT_QiAo__qi_offset_fen", 1.0)
        extrude_len_raw = self.all_get("FT_QiAo__extrude_length", 46.0)

        qi_h = _scalar_from_list(qi_h_raw, 8.0)
        sha_w = _scalar_from_list(sha_w_raw, 4.0)
        qi_offset = _scalar_from_list(qi_offset_raw, 1.0)
        extrude_len = _scalar_from_list(extrude_len_raw, 46.0)

        base_pt = rg.Point3d(0, 0, 0)
        ref_plane = rg.Plane(
            rg.Point3d(0, 0, 0),
            rg.Vector3d.XAxis,
            rg.Vector3d.ZAxis
        )
        extrude_positive = False

        (
            self.ToolBrep,
            self.BasePoint,
            self.BaseLine,
            self.SecPlane,
            self.FacePlane
        ) = build_qiao_tool(
            qi_h, sha_w, qi_offset, extrude_len,
            base_pt,
            ref_plane,
            extrude_positive
        )

        # --------------------------------------------------------------
        # 3.3 FT_AlignToolToTimber::1 —— 多刀具广播（QiAo 刀具）
        # --------------------------------------------------------------
        BlockRotDeg_raw = self.all_get("FT_AlignToolToTimber_1__BlockRotDeg", 0.0)
        FlipY_raw = self.all_get("FT_AlignToolToTimber_1__FlipY", 0)

        self.Log.append("[Align1] BlockRotDeg 原始值 = {!r}".format(BlockRotDeg_raw))
        self.Log.append("[Align1] FlipY       原始值 = {!r}".format(FlipY_raw))

        # 其它参数默认
        ToolRotDeg_raw = None
        ToolContactPt_raw = None
        BlockTargetPt_raw = None
        Mode_raw = None
        ToolDir_raw = None
        TargetDir_raw = None
        DepthOffset_raw = None
        MoveU_raw = None
        MoveV_raw = None
        FlipX_raw = 0
        FlipZ_raw = 0

        BlockFacePlane_raw = self.ResultPlane1  # 多个 plane

        # 1) 基础 ToolGeo 列表
        tools_list_base = _to_list(self.ToolBrep)
        tool_count = len(tools_list_base)

        # 2) 决定运算次数 N
        if tool_count == 1:
            lengths = [1]
            lengths.append(_param_length(self.FacePlane))
            lengths.append(_param_length(ToolRotDeg_raw))
            lengths.append(_param_length(ToolContactPt_raw))
            lengths.append(_param_length(BlockFacePlane_raw))
            lengths.append(_param_length(BlockRotDeg_raw))
            lengths.append(_param_length(FlipX_raw))
            lengths.append(_param_length(FlipY_raw))
            lengths.append(_param_length(FlipZ_raw))
            lengths.append(_param_length(BlockTargetPt_raw))
            lengths.append(_param_length(Mode_raw))
            lengths.append(_param_length(ToolDir_raw))
            lengths.append(_param_length(TargetDir_raw))
            lengths.append(_param_length(DepthOffset_raw))
            lengths.append(_param_length(MoveU_raw))
            lengths.append(_param_length(MoveV_raw))

            lengths = [l for l in lengths if l > 0]
            N = max(lengths) if lengths else 1
        else:
            N = tool_count

        self.Log.append("[Align1] 计算得到对位次数 N = {}".format(N))

        # 3) 广播
        tools_list = _broadcast_param(tools_list_base, N, "ToolGeo")
        tool_planes = _broadcast_param(self.FacePlane, N, "ToolBasePlane")
        tool_rots = _broadcast_param(ToolRotDeg_raw, N, "ToolRotDeg")
        tool_pts = _broadcast_param(ToolContactPt_raw, N, "ToolContactPoint")
        block_planes = _broadcast_param(BlockFacePlane_raw, N, "BlockFacePlane")
        block_rots = _broadcast_param(BlockRotDeg_raw, N, "BlockRotDeg")
        flip_xs = _broadcast_param(FlipX_raw, N, "FlipX")
        flip_ys = _broadcast_param(FlipY_raw, N, "FlipY")
        flip_zs = _broadcast_param(FlipZ_raw, N, "FlipZ")
        block_pts = _broadcast_param(BlockTargetPt_raw, N, "BlockTargetPoint")
        modes = _broadcast_param(Mode_raw, N, "Mode")
        tool_dirs = _broadcast_param(ToolDir_raw, N, "ToolDir")
        target_dirs = _broadcast_param(TargetDir_raw, N, "TargetDir")
        depth_offsets = _broadcast_param(DepthOffset_raw, N, "DepthOffset")
        move_us = _broadcast_param(MoveU_raw, N, "MoveU")
        move_vs = _broadcast_param(MoveV_raw, N, "MoveV")

        # 4) 清空旧结果
        self.AlignedTool = []
        self.XForm = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo = []

        # 5) 对位
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

            self.AlignedTool.append(aligned)
            self.XForm.append(xf)
            self.SourcePlane.append(src_pl)
            self.TargetPlane.append(tgt_pl)
            self.SourcePoint.append(src_pt)
            self.TargetPoint.append(tgt_pt)

            if aligned is None:
                self.DebugInfo.append("对位失败[{}]: {}".format(i, dbg))
            else:
                self.DebugInfo.append("对位成功[{}]: {}".format(i, dbg))

        # --------------------------------------------------------------
        # 3.4 第一次切割 FT_CutTimberByTools
        # --------------------------------------------------------------
        cutter = FT_CutTimberByTools(self.TimberBrep, self.AlignedTool)
        self.CutTimbers, self.FailTimbers, logc = cutter.run()

        for l in logc:
            self.Log.append("[Cut1] " + l)

    # ==================================================================
    # Step 4 — FT_BlockCutter + PlaneFromLists::2/3 + Align::2 + Cut::2
    # ==================================================================
    def step4_block_cutter(self):

        self.Log.append("===== Step 4: FT_BlockCutter + PFL2 + PFL3 + Align::2 + Cut::2 =====")

        # --------------------------------------------------------------
        # 4.1 FT_BlockCutter —— 多个 cutter（Tree 结构）
        #
        #   对应 GH 组件：
        #       每当 length_fen / width_fen / height_fen 有多项时，
        #       GH 会对 GhPython 组件多次求解：
        #           每一次求解输出一组：
        #               TimberBrep, FaceList, PointList, EdgeList,
        #               CenterPoint, CenterAxisLines, EdgeMidPoints,
        #               FacePlaneList, Corner0Planes, ...
        #       在 Grasshopper 中，这些被组织为 Tree：
        #           {0;0} → 第 0 个 cutter 的所有输出
        #           {0;1} → 第 1 个 cutter 的所有输出
        #           ...
        #
        #   在 Solver 里手动模拟这一点：
        #       - 对每个 cutter 调用一次 build_timber_block_uniform
        #       - 把每一轮的输出包装成“一个分支”，形成嵌套列表：
        #           self.BlockEdgeMidPoints = [edge_midpts_0, edge_midpts_1, ...]
        #           self.BlockCorner0Planes = [corner0_planes_0, corner0_planes_1, ...]
        # --------------------------------------------------------------
        bc_L_raw = self.all_get("FT_BlockCutter__length_fen", 32.0)
        bc_W_raw = self.all_get("FT_BlockCutter__width_fen", 32.0)
        bc_H_raw = self.all_get("FT_BlockCutter__height_fen", 20.0)

        # 计算 cutter 数量 Nc（最长列表驱动）
        Nc = max(
            _param_length(bc_L_raw),
            _param_length(bc_W_raw),
            _param_length(bc_H_raw),
        )
        if Nc <= 0:
            Nc = 1

        # 广播到长度 Nc
        bc_L_list = _broadcast_param(bc_L_raw, Nc, "FT_BlockCutter__length_fen")
        bc_W_list = _broadcast_param(bc_W_raw, Nc, "FT_BlockCutter__width_fen")
        bc_H_list = _broadcast_param(bc_H_raw, Nc, "FT_BlockCutter__height_fen")

        self.Log.append("[BlockCutter] 读取到 {} 组长宽高，准备生成 {} 个 cutter。".format(Nc, Nc))

        # 与组件保持一致：base_point 为原点，reference_plane 为 GH 的 XZ 平面
        bc_base_pt = rg.Point3d(0.0, 0.0, 0.0)
        bc_ref_plane = rg.Plane(
            rg.Point3d(0, 0, 0),
            rg.Vector3d.XAxis,
            rg.Vector3d.ZAxis
        )

        # ====== 初始化为 Tree 结构（嵌套列表） ======
        # 第 i 个 cutter 对应“第 i 个分支”
        self.BlockTimberBreps = []  # [Brep0, Brep1, ...]
        self.BlockFaceList = []  # [[faces_0], [faces_1], ...]
        self.BlockPointList = []  # [[points_0], [points_1], ...]
        self.BlockEdgeList = []  # [[edges_0], [edges_1], ...]
        self.BlockCenterPoint = []  # [center_pt_0, center_pt_1, ...]
        self.BlockCenterAxisLines = []  # [[axis_lines_0], [axis_lines_1], ...]
        self.BlockEdgeMidPoints = []  # ★ [[edge_midpts_0], [edge_midpts_1], ...]
        self.BlockFacePlaneList = []  # [[face_planes_0], [face_planes_1], ...]
        self.BlockCorner0Planes = []  # ★ [[corner0_planes_0], [corner0_planes_1], ...]
        self.BlockLocalAxesPlane = []  # [local_axes_plane_0, local_axes_plane_1, ...]
        self.BlockAxisX = []  # [axis_x_0, axis_x_1, ...]
        self.BlockAxisY = []  # [axis_y_0, axis_y_1, ...]
        self.BlockAxisZ = []  # [axis_z_0, axis_z_1, ...]
        self.BlockFaceDirTags = []  # [[face_tags_0], [face_tags_1], ...]
        self.BlockEdgeDirTags = []  # [[edge_tags_0], [edge_tags_1], ...]
        self.BlockCorner0EdgeDirs = []  # [[corner0_dirs_0], [corner0_dirs_1], ...]

        try:
            for i in range(Nc):
                Li = bc_L_list[i]
                Wi = bc_W_list[i]
                Hi = bc_H_list[i]

                self.Log.append(
                    "[BlockCutter] 第 {} 个 cutter: L={}, W={}, H={}".format(i, Li, Wi, Hi)
                )

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
                    bc_log_lines
                ) = build_timber_block_uniform(
                    Li, Wi, Hi,
                    bc_base_pt,
                    bc_ref_plane
                )

                # 单个 Brep：直接 append
                self.BlockTimberBreps.append(timber_brep)

                # 以下均视为“第 i 个分支”的内容，保持为嵌套列表
                self.BlockFaceList.append(faces)
                self.BlockPointList.append(points)
                self.BlockEdgeList.append(edges)
                self.BlockCenterPoint.append(center_pt)
                self.BlockCenterAxisLines.append(center_axes)
                self.BlockEdgeMidPoints.append(edge_midpts)  # ★ Tree 结构
                self.BlockFacePlaneList.append(face_planes)
                self.BlockCorner0Planes.append(corner0_planes)  # ★ Tree 结构
                self.BlockLocalAxesPlane.append(local_axes_plane)
                self.BlockAxisX.append(axis_x)
                self.BlockAxisY.append(axis_y)
                self.BlockAxisZ.append(axis_z)
                self.BlockFaceDirTags.append(face_tags)
                self.BlockEdgeDirTags.append(edge_tags)
                self.BlockCorner0EdgeDirs.append(corner0_dirs)

                for l in bc_log_lines:
                    self.Log.append("[BlockCutter][{}] ".format(i) + l)

        except Exception as e:
            self.Log.append("BlockCutter 构造失败: {}".format(e))
            # 这里可以直接 return，后续 PFL3/Align2/Cut2 都不再执行
            return

        # --------------------------------------------------------------
        # 4.2 PlaneFromLists::2 —— 主木坯上的多个基准面
        #
        # 对应 GH 组件：
        #   OriginPoints = FT_timber_block_uniform 的 EdgeMidPoints
        #   BasePlanes   = FT_timber_block_uniform 的 Corner0Planes
        #   IndexOrigin  = PlaneFromLists_2__IndexOrigin
        #   IndexPlane   = PlaneFromLists_2__IndexPlane
        # --------------------------------------------------------------
        idx2_o_raw = self.all_get("PlaneFromLists_2__IndexOrigin", [])
        idx2_p_raw = self.all_get("PlaneFromLists_2__IndexPlane", [])
        wrap2_raw = self.all_get("PlaneFromLists_2__wrap", True)

        idx2_o_list = _to_list(idx2_o_raw)
        idx2_p_list = _to_list(idx2_p_raw)
        n_pf2 = min(len(idx2_o_list), len(idx2_p_list))

        self.BasePlane2 = []
        self.OriginPoint2 = []
        self.ResultPlane2 = []

        if n_pf2 == 0:
            self.Log.append("[PFL2] IndexOrigin / IndexPlane 列表为空，跳过 PlaneFromLists::2。")
        else:
            wrap2 = bool(_scalar_from_list(wrap2_raw, True))
            builder2 = FTPlaneFromLists(wrap=wrap2)

            for i in range(n_pf2):
                io = idx2_o_list[i]
                ip = idx2_p_list[i]

                base_pl, org_pt, res_pl, log_pf = builder2.build_plane(
                    self.EdgeMidPoints,
                    self.Corner0Planes,
                    io,
                    ip
                )

                self.BasePlane2.append(base_pl)
                self.OriginPoint2.append(org_pt)
                self.ResultPlane2.append(res_pl)

                for l in log_pf:
                    self.Log.append("[PFL2][{}] ".format(i) + l)

        # --------------------------------------------------------------
        # 4.3 PlaneFromLists::3 —— BlockCutter 木块上的基准面（4 个分支）
        #
        # 对应 GH 组件：
        #   OriginPoints = FT_BlockCutter 的 EdgeMidPoints（有 4 个分支）
        #   BasePlanes   = FT_BlockCutter 的 Corner0Planes（有 4 个分支）
        #   IndexOrigin  = PlaneFromLists_3__IndexOrigin（单个 int）
        #   IndexPlane   = PlaneFromLists_3__IndexPlane（单个 int）
        #
        # 目标：当 BlockEdgeMidPoints / BlockCorner0Planes 为嵌套列表（Tree）时，
        #       对每个分支各取一个点 + 一个平面，返回多个 ResultPlane。
        # --------------------------------------------------------------
        idx3_o_raw = self.all_get("PlaneFromLists_3__IndexOrigin", None)
        idx3_p_raw = self.all_get("PlaneFromLists_3__IndexPlane", None)
        wrap3_raw = self.all_get("PlaneFromLists_3__wrap", True)

        # 先初始化输出
        self.BasePlane3 = []
        self.OriginPoint3 = []
        self.ResultPlane3 = []

        # 没有配置索引 → 等价于组件输入端空 → 不执行
        if idx3_o_raw is None or idx3_p_raw is None:
            self.Log.append("[PFL3] IndexOrigin 或 IndexPlane 未指定，跳过 PlaneFromLists::3。")
        else:
            idx3_o_list = _to_list(idx3_o_raw)
            idx3_p_list = _to_list(idx3_p_raw)

            if not idx3_o_list or not idx3_p_list:
                self.Log.append("[PFL3] IndexOrigin / IndexPlane 为空列表，跳过 PlaneFromLists::3。")
            else:
                idx3_o = idx3_o_list[0]
                idx3_p = idx3_p_list[0]
                wrap3 = bool(wrap3_raw)

                builder3 = FTPlaneFromLists(wrap=wrap3)

                try:
                    # ====== 保留你指定的这一次调用，不改传入值 ======
                    base_pl3, org_pt3, res_pl3, log_pf3 = builder3.build_plane(
                        self.BlockEdgeMidPoints,  # OriginPoints（可能是 4 个分支）
                        self.BlockCorner0Planes,  # BasePlanes（可能是 4 个分支）
                        idx3_o,  # IndexOrigin（单个 int）
                        idx3_p  # IndexPlane（单个 int）
                    )

                    # 先把这次调用的日志记下来
                    for l in log_pf3:
                        self.Log.append("[PFL3][raw] " + l)

                    # 判断是否是 Tree 结构：外层是 list，且第一个元素还是 list/tuple
                    is_tree = (
                            isinstance(self.BlockEdgeMidPoints, (list, tuple)) and
                            len(self.BlockEdgeMidPoints) > 0 and
                            isinstance(self.BlockEdgeMidPoints[0], (list, tuple))
                    )

                    # 情况 A：不是 Tree，或者 build_plane 已经返回了“可用结果”（Plane 或 Plane 列表）
                    #        → 直接沿用一次调用的结果
                    if (not is_tree) or (res_pl3 is not None and not isinstance(res_pl3, list)):
                        # 将单值统一包装成列表，保持后续统一接口
                        self.BasePlane3 = base_pl3 if isinstance(base_pl3, list) else [base_pl3]
                        self.OriginPoint3 = org_pt3 if isinstance(org_pt3, list) else [org_pt3]
                        self.ResultPlane3 = res_pl3 if isinstance(res_pl3, list) else [res_pl3]

                    # 情况 B：是 Tree 且第一次调用没真正算出 Plane（res_pl3 为 None）
                    #        → 对每个分支单独调用一次 build_plane（不展平）
                    else:
                        origin_tree = self.BlockEdgeMidPoints
                        plane_tree = self.BlockCorner0Planes

                        if not origin_tree or not plane_tree:
                            self.Log.append("[PFL3] BlockEdgeMidPoints / BlockCorner0Planes 为空，无法按分支处理。")
                        else:
                            n_branches = min(len(origin_tree), len(plane_tree))
                            self.Log.append("[PFL3] 检测到嵌套列表结构，按分支循环处理，分支数 = {}".format(n_branches))

                            for bi in range(n_branches):
                                branch_pts = origin_tree[bi]
                                branch_pls = plane_tree[bi]

                                bp_b, op_b, rp_b, log_b = builder3.build_plane(
                                    branch_pts,
                                    branch_pls,
                                    idx3_o,
                                    idx3_p
                                )

                                self.BasePlane3.append(bp_b)
                                self.OriginPoint3.append(op_b)
                                self.ResultPlane3.append(rp_b)

                                for l in log_b:
                                    self.Log.append("[PFL3][branch {}] ".format(bi) + l)

                except Exception as e:
                    self.Log.append("[PFL3] 调用 FTPlaneFromLists.build_plane 出错: {}".format(e))
                    self.BasePlane3 = []
                    self.OriginPoint3 = []
                    self.ResultPlane3 = []

        # --------------------------------------------------------------
        # 4.4 FT_AlignToolToTimber::2 —— BlockCutter 作为刀具对位主木坯
        #
        # 对应 GH 组件：
        #   ToolGeo       = FT_BlockCutter 的 TimberBrep（self.BlockTimberBreps）
        #   ToolBasePlane = PlaneFromLists::3 的 ResultPlane3
        #   BlockFacePlane= PlaneFromLists::2 的 ResultPlane2
        #   BlockRotDeg   = FT_AlignToolToTimber_2__BlockRotDeg
        #   FlipX / FlipY / FlipZ = FT_AlignToolToTimber_2__FlipX / __FlipY / __FlipZ
        #
        # 完全参考 Step 3 中 Align::1 的写法，只是变量加上 “2” 后缀，
        # 并修正 FlipX / FlipY / FlipZ 缺省值为 None（等价于 GH 未接线）。
        # --------------------------------------------------------------
        BlockRotDeg2_raw = self.all_get("FT_AlignToolToTimber_2__BlockRotDeg", 0.0)
        FlipX2_raw = self.all_get("FT_AlignToolToTimber_2__FlipX", None)
        FlipY2_raw = self.all_get("FT_AlignToolToTimber_2__FlipY", None)
        FlipZ2_raw = self.all_get("FT_AlignToolToTimber_2__FlipZ", None)

        self.Log.append("[Align2] BlockRotDeg 原始值 = {!r}".format(BlockRotDeg2_raw))
        self.Log.append("[Align2] FlipX       原始值 = {!r}".format(FlipX2_raw))
        self.Log.append("[Align2] FlipY       原始值 = {!r}".format(FlipY2_raw))
        self.Log.append("[Align2] FlipZ       原始值 = {!r}".format(FlipZ2_raw))

        # 其它参数暂时均为 None，等价于 GH 中未接线
        ToolRotDeg2_raw = None
        ToolContactPt2_raw = None
        BlockTargetPt2_raw = None
        Mode2_raw = None
        ToolDir2_raw = None
        TargetDir2_raw = None
        DepthOffset2_raw = None
        MoveU2_raw = None
        MoveV2_raw = None

        # 与组件一致：BlockCutter 的对位输入
        ToolBasePlane2_raw = self.ResultPlane3  # PFL3（通常长度 = cutter 数）
        BlockFacePlane2_raw = self.ResultPlane2  # PFL2（通常长度 = cutter 数）

        # 1) 基础 ToolGeo 列表（BlockCutter 生成的 cutter Brep）
        tools2_list_base = _to_list(self.BlockTimberBreps)
        tool2_count = len(tools2_list_base)

        if tool2_count == 0 or all(t is None for t in tools2_list_base):
            self.Log.append("[Align2] BlockTimberBreps 为空，未进行第二轮对位。")
            self.AlignedTool2 = []
            self.XForm2 = []
            self.SourcePlane2 = []
            self.TargetPlane2 = []
            self.SourcePoint2 = []
            self.TargetPoint2 = []
            self.DebugInfo2 = []
            return

        self.Log.append("[Align2] 输入刀具数量 = {}".format(tool2_count))

        # 2) 决定运算次数 N2 —— 完全复刻 Align::1 的策略
        if tool2_count == 1:
            lengths = [1]
            lengths.append(_param_length(ToolBasePlane2_raw))
            lengths.append(_param_length(ToolRotDeg2_raw))
            lengths.append(_param_length(ToolContactPt2_raw))
            lengths.append(_param_length(BlockFacePlane2_raw))
            lengths.append(_param_length(BlockRotDeg2_raw))
            lengths.append(_param_length(FlipX2_raw))
            lengths.append(_param_length(FlipY2_raw))
            lengths.append(_param_length(FlipZ2_raw))
            lengths.append(_param_length(BlockTargetPt2_raw))
            lengths.append(_param_length(Mode2_raw))
            lengths.append(_param_length(ToolDir2_raw))
            lengths.append(_param_length(TargetDir2_raw))
            lengths.append(_param_length(DepthOffset2_raw))
            lengths.append(_param_length(MoveU2_raw))
            lengths.append(_param_length(MoveV2_raw))

            lengths = [l for l in lengths if l > 0]
            N2 = max(lengths) if lengths else 1
        else:
            # 多刀具：N2 = ToolGeo 数量，所有输入列表按索引一一对应
            N2 = tool2_count

        self.Log.append("[Align2] 计算得到对位次数 N2 = {}".format(N2))
        self.Log.append(
            "[Align2] 长度信息: ToolGeo={}, ToolBasePlane2={}, BlockFacePlane2={}".format(
                tool2_count,
                _param_length(ToolBasePlane2_raw),
                _param_length(BlockFacePlane2_raw)
            )
        )

        # 3) 广播到长度 N2（与组件 _broadcast_param 一致）
        tools2_list = _broadcast_param(tools2_list_base, N2, "ToolGeo")
        tool2_planes = _broadcast_param(ToolBasePlane2_raw, N2, "ToolBasePlane")
        tool2_rots = _broadcast_param(ToolRotDeg2_raw, N2, "ToolRotDeg")
        tool2_pts = _broadcast_param(ToolContactPt2_raw, N2, "ToolContactPoint")
        block2_planes = _broadcast_param(BlockFacePlane2_raw, N2, "BlockFacePlane")
        block2_rots = _broadcast_param(BlockRotDeg2_raw, N2, "BlockRotDeg")
        flip2_xs = _broadcast_param(FlipX2_raw, N2, "FlipX")
        flip2_ys = _broadcast_param(FlipY2_raw, N2, "FlipY")
        flip2_zs = _broadcast_param(FlipZ2_raw, N2, "FlipZ")
        block2_pts = _broadcast_param(BlockTargetPt2_raw, N2, "BlockTargetPoint")
        modes2 = _broadcast_param(Mode2_raw, N2, "Mode")
        tool2_dirs = _broadcast_param(ToolDir2_raw, N2, "ToolDir")
        target2_dirs = _broadcast_param(TargetDir2_raw, N2, "TargetDir")
        depth2_offsets = _broadcast_param(DepthOffset2_raw, N2, "DepthOffset")
        move2_us = _broadcast_param(MoveU2_raw, N2, "MoveU")
        move2_vs = _broadcast_param(MoveV2_raw, N2, "MoveV")

        # 4) 清空旧结果
        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []

        # 5) 一一对应调用 FTAligner.align
        for i in range(N2):
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                tools2_list[i],
                tool2_planes[i],
                tool2_pts[i],
                block2_planes[i],
                block2_pts[i],
                modes2[i],
                tool2_dirs[i],
                target2_dirs[i],
                depth2_offsets[i],
                move2_us[i],
                move2_vs[i],
                flip2_xs[i],
                flip2_ys[i],
                flip2_zs[i],
                tool2_rots[i],
                block2_rots[i]
            )

            self.AlignedTool2.append(aligned)
            self.XForm2.append(xf)
            self.SourcePlane2.append(src_pl)
            self.TargetPlane2.append(tgt_pl)
            self.SourcePoint2.append(src_pt)
            self.TargetPoint2.append(tgt_pt)

            if aligned is None:
                self.DebugInfo2.append("对位失败[{}]: {}".format(i, dbg))
            else:
                self.DebugInfo2.append("对位成功[{}]: {}".format(i, dbg))

        # --------------------------------------------------------------
        # 4.5 第二次切割 FT_CutTimberByTools::2
        #
        # 对应 GH 组件：
        #   Timbers = 第一次切割后的 CutTimbers
        #   Tools   = 第二轮对位后的 AlignedTool2
        # --------------------------------------------------------------
        cutter2 = FT_CutTimberByTools(self.CutTimbers, self.AlignedTool2)
        self.CutTimbers2, self.FailTimbers2, logc2 = cutter2.run()

        for l in logc2:
            self.Log.append("[Cut2] " + l)

    # ==================================================================
    # Step 5 — FT_Yin(廕) + Align::3 + Cut::3
    # ==================================================================
    def step5_yin(self):

        self.Log.append("===== Step 5: FT_Yin + Align::3 + Cut::3 =====")

        # ==============================================================
        # 5.1 从 FT_Yin_IDX__Index 读取多个索引，生成对角折线 Diag Polyline
        #    说明：
        #      - FT_Yin_IDX__Index 可以是单个 int，也可以是 [i0, i1, i2, ...]
        #      - 至少需要 2 个有效索引，按顺序连成一条折线
        # ==============================================================

        idx_raw = self.all_get("FT_Yin_IDX__Index", [])
        idx_list = _to_list(idx_raw)  # 保证是 list

        if len(idx_list) < 2:
            self.Log.append("[YIN] FT_Yin_IDX__Index 少于 2 个索引，无法生成对角线。")
            self.YinToolPlanes = []
            return

        diag_pts = []
        for k, idx in enumerate(idx_list):
            try:
                i = int(idx)
            except Exception:
                self.Log.append("[YIN] 索引 {} 无法转为 int，已跳过。".format(idx))
                continue

            if i < 0 or i >= len(self.PointList):
                self.Log.append("[YIN] 索引 {} 超出 PointList 范围，已跳过。".format(i))
                continue

            diag_pts.append(self.PointList[i])

        if len(diag_pts) < 2:
            self.Log.append("[YIN] 有效点数少于 2，无法生成 Diag。")
            self.YinToolPlanes = []
            return

        # 按顺序连成一条折线
        diag = rg.Polyline(diag_pts)

        # ==============================================================
        # 5.2 运行 FT_Yin(廕) 组件核心：YinCornerToolPlaneCalculator
        # ==============================================================

        ToolWidth_raw = self.all_get("FT_Yin__ToolWidth", 10.0)
        Yin_raw = self.all_get("FT_Yin__Yin", 0.5)
        ShapeMode_raw = self.all_get("FT_Yin__ShapeMode", 0)

        ToolWidth = float(ToolWidth_raw)
        YinValue = float(Yin_raw)
        ShapeMode = int(ShapeMode_raw)

        # ---------- 关键：将 Polyline 转为 Line-like Curve ----------
        diag_for_yin = diag

        # diag 是 rg.Polyline 时，先转为 PolylineCurve，再让内部去抽取端点直线
        if isinstance(diag, rg.Polyline):
            if diag.Count >= 2:
                try:
                    # 方式 1：直接用 ToPolylineCurve（推荐，最稳妥）
                    diag_for_yin = diag.ToPolylineCurve()
                except Exception:
                    # 方式 2：退而求其次，手动用首尾点生成一条 LineCurve
                    p0 = diag[0]
                    p1 = diag[diag.Count - 1]
                    diag_for_yin = rg.LineCurve(p0, p1)
            else:
                diag_for_yin = None

        # 如果转换失败，直接记 log 并中止 Yin 步骤
        if diag_for_yin is None:
            self.Log.append("[YIN] 错误：Diag 为 Polyline 且点数不足 2，无法生成对角线。")
            self.YinToolPlanes = []
            return

        try:
            calc = YinCornerToolPlaneCalculator(diag_for_yin, ToolWidth, YinValue, ShapeMode)
            YinToolPlanes, YinLog = calc.run()
            self.YinToolPlanes = YinToolPlanes

            for l in YinLog:
                self.Log.append("[YIN] " + l)

        except Exception as e:
            self.Log.append("[YIN] YinCornerToolPlaneCalculator 出错: {}".format(e))
            self.YinToolPlanes = []
            return

        # ==============================================================
        # 5.3 Align::3 — 将 Yin 工具面与 BlockCutter 对位
        # ==============================================================

        # ToolGeo = 第 0 个 cutter
        if not self.BlockTimberBreps:
            self.Log.append("[Align3] BlockTimberBreps 为空，无法进行第三轮对位。")
            return
        ToolGeo3_raw = self.BlockTimberBreps[0]

        # ToolBasePlane = PFL3 中的第 0 个结果平面
        if not self.ResultPlane3:
            self.Log.append("[Align3] ResultPlane3 为空，无法进行第三轮对位。")
            return
        ToolBasePlane3_raw = self.ResultPlane3[0]

        # BlockFacePlane = YinToolPlanes（多个 → N3 次对位）
        BlockFacePlane3_raw = self.YinToolPlanes
        N3 = len(BlockFacePlane3_raw)
        if N3 == 0:
            self.Log.append("[Align3] YinToolPlanes 为空，跳过 Align::3。")
            return

        self.Log.append("[Align3] 对位次数 N3 = {}".format(N3))

        # 翻转与旋转信息
        BlockRotDeg3_raw = self.all_get("FT_AlignToolToTimber_3__BlockRotDeg", 0.0)
        FlipY3_raw = self.all_get("FT_AlignToolToTimber_3__FlipY", None)
        FlipZ3_raw = self.all_get("FT_AlignToolToTimber_3__FlipZ", None)

        # 其它均为 None
        ToolRotDeg3_raw = None
        ToolContactPt3_raw = None
        BlockTargetPt3_raw = None
        Mode3_raw = None
        ToolDir3_raw = None
        TargetDir3_raw = None
        DepthOffset3_raw = None
        MoveU3_raw = None
        MoveV3_raw = None

        # --- 广播为长度 N3 ---
        tool3_list = _broadcast_param(ToolGeo3_raw, N3, "ToolGeo")
        base3_list = _broadcast_param(ToolBasePlane3_raw, N3, "ToolBasePlane")
        face3_list = _broadcast_param(BlockFacePlane3_raw, N3, "BlockFacePlane")
        block_rot3 = _broadcast_param(BlockRotDeg3_raw, N3, "BlockRotDeg")

        # 如果你已经定义了 _normalize_flip_list，则用它；否则可以直接用 _broadcast_param
        flipY3 = _broadcast_param(FlipY3_raw, N3, "FlipY")
        flipZ3 = _broadcast_param(FlipZ3_raw, N3, "FlipZ")
        # 或者（若你已实现 _normalize_flip_list）：
        # flipY3         = _normalize_flip_list(FlipY3_raw,      N3, "FlipY")
        # flipZ3         = _normalize_flip_list(FlipZ3_raw,      N3, "FlipZ")

        # 其它参数广播
        tool_rot3 = _broadcast_param(ToolRotDeg3_raw, N3, "ToolRotDeg")
        tool_pts3 = _broadcast_param(ToolContactPt3_raw, N3, "ToolContactPoint")
        block_pts3 = _broadcast_param(BlockTargetPt3_raw, N3, "BlockTargetPoint")
        modes3 = _broadcast_param(Mode3_raw, N3, "Mode")
        tool_dirs3 = _broadcast_param(ToolDir3_raw, N3, "ToolDir")
        target_dirs3 = _broadcast_param(TargetDir3_raw, N3, "TargetDir")
        depth3 = _broadcast_param(DepthOffset3_raw, N3, "DepthOffset")
        moveU3 = _broadcast_param(MoveU3_raw, N3, "MoveU")
        moveV3 = _broadcast_param(MoveV3_raw, N3, "MoveV")

        # --- 执行对位 ---
        self.AlignedTool3 = []
        self.XForm3 = []
        self.SourcePlane3 = []
        self.TargetPlane3 = []
        self.SourcePoint3 = []
        self.TargetPoint3 = []
        self.DebugInfo3 = []

        for i in range(N3):

            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                tool3_list[i],
                base3_list[i],
                tool_pts3[i],
                face3_list[i],
                block_pts3[i],
                modes3[i],
                tool_dirs3[i],
                target_dirs3[i],
                depth3[i],
                moveU3[i],
                moveV3[i],
                None,  # FlipX3 不使用
                flipY3[i],
                flipZ3[i],
                tool_rot3[i],
                block_rot3[i]
            )

            self.AlignedTool3.append(aligned)
            self.XForm3.append(xf)
            self.SourcePlane3.append(src_pl)
            self.TargetPlane3.append(tgt_pl)
            self.SourcePoint3.append(src_pt)
            self.TargetPoint3.append(tgt_pt)

            if aligned is None:
                self.DebugInfo3.append("对位失败[{}]: {}".format(i, dbg))
            else:
                self.DebugInfo3.append("对位成功[{}]: {}".format(i, dbg))

        # ==============================================================
        # 5.4 Cut::3 — 根据第三轮对位刀具切削
        # ==============================================================

        timbers3 = self.CutTimbers2  # 上一步的切削结果
        tools3 = self.AlignedTool3

        if not timbers3 or not tools3:
            self.Log.append("[Cut3] Timbers/Tools 为空，无法切削。")
            self.CutTimbers3 = []
            self.FailTimbers3 = []
            return

        try:
            cutter3 = FT_CutTimberByTools(timbers3, tools3)
            cut3, fail3, log3 = cutter3.run()

            self.CutTimbers3 = cut3
            self.FailTimbers3 = fail3

            for l in log3:
                self.Log.append("[Cut3] " + l)

        except Exception as e:
            self.Log.append("[Cut3] 切削失败: {}".format(e))
            self.CutTimbers3 = []
            self.FailTimbers3 = []

    # ==================================================================
    # 主控入口
    # ==================================================================
    def run(self):

        self.step1_read_db()

        if self.All is None or len(self.All) == 0:
            self.Log.append("run: All 为空，终止后续步骤。")
            return self

        self.step2_timber()
        self.step3_qiao()
        self.step4_block_cutter()
        self.step5_yin()

        return self


# ======================================================================
# GH PYTHON 组件输出绑定区
# ======================================================================
if __name__ == "__main__":
    # 执行所有步骤（包含 Step 5）
    solver = AngLUDouSolver(DBPath, base_point, Refresh, ghenv).run()

    # -------- Step 1 --------
    Value = solver.Value
    All = solver.All
    All_dict = solver.All_dict

    # -------- Step 2：主木坯 --------
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

    # -------- Step 3：PlaneFromLists::1 --------
    BasePlane1 = solver.BasePlane1
    OriginPoint1 = solver.OriginPoint1
    ResultPlane1 = solver.ResultPlane1

    # -------- Step 3：QiAo --------
    ToolBrep = solver.ToolBrep
    BasePoint = solver.BasePoint
    BaseLine = solver.BaseLine
    SecPlane = solver.SecPlane
    FacePlane = solver.FacePlane

    # -------- Align::1 --------
    AlignedTool = solver.AlignedTool
    XForm = solver.XForm
    SourcePlane = solver.SourcePlane
    TargetPlane = solver.TargetPlane
    SourcePoint = solver.SourcePoint
    TargetPoint = solver.TargetPoint
    DebugInfo = solver.DebugInfo

    # -------- Cut::1 --------
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers

    # -------- Step 4：BlockCutter 主块 --------
    BlockTimberBrep = solver.BlockTimberBreps
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

    # -------- Step 4：PlaneFromLists::2/3 --------
    BasePlane2 = solver.BasePlane2
    OriginPoint2 = solver.OriginPoint2
    ResultPlane2 = solver.ResultPlane2

    BasePlane3 = solver.BasePlane3
    OriginPoint3 = solver.OriginPoint3
    ResultPlane3 = solver.ResultPlane3

    # -------- Align::2 --------
    AlignedTool2 = solver.AlignedTool2
    XForm2 = solver.XForm2
    SourcePlane2 = solver.SourcePlane2
    TargetPlane2 = solver.TargetPlane2
    SourcePoint2 = solver.SourcePoint2
    TargetPoint2 = solver.TargetPoint2
    DebugInfo2 = solver.DebugInfo2

    # -------- Cut::2 --------
    CutTimbers2 = solver.CutTimbers2
    FailTimbers2 = solver.FailTimbers2

    # ==============================================================
    # Step 5：输出全部 Yin 对位与切割信息
    # ==============================================================

    YinToolPlanes = getattr(solver, "YinToolPlanes", [])

    # Align::3
    AlignedTool3 = getattr(solver, "AlignedTool3", [])
    XForm3 = getattr(solver, "XForm3", [])
    SourcePlane3 = getattr(solver, "SourcePlane3", [])
    TargetPlane3 = getattr(solver, "TargetPlane3", [])
    SourcePoint3 = getattr(solver, "SourcePoint3", [])
    TargetPoint3 = getattr(solver, "TargetPoint3", [])
    DebugInfo3 = getattr(solver, "DebugInfo3", [])

    # Cut::3
    CutTimbers3 = getattr(solver, "CutTimbers3", [])
    FailTimbers3 = getattr(solver, "FailTimbers3", [])

    # -------- Log --------
    Log = solver.Log








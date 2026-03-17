# -*- coding: utf-8 -*-
"""
JiaoHuDouSolver —— 交互枓一体化求解器 (Step 1 + Step 2 + Step 3 + Step 4)

步骤说明：
    Step 1: DBJsonReader 读取 DG_Dou 表中 JIAOHU_DOU 的 params_json
    Step 2: FT_timber_block_uniform —— 构造主木坯
    Step 3: PlaneFromLists::1 + FT_QiAo + FT_AlignToolToTimber::1
    Step 4: FT_BlockCutter + PlaneFromLists::2 + PlaneFromLists::3
            + FT_AlignToolToTimber::2 + FT_CutTimberByTools（一次性总切削）

输入（GhPython）：
    DBPath     : str         - SQLite 数据库路径
    base_point : Point3d     - 主木坯定位点（优先于 DB 中的 base_point）
    Refresh    : bool        - 保留接口（目前未使用）

输出（GhPython · 开发模式）：
    - Step1: All, AllDict, DBLog
    - Step2: TimberBrep, FaceList, PointList, EdgeList, ...
    - Step3: BasePlane1, OriginPoint1, ResultPlane1, ToolBrep, AlignedTool, ...
    - Step4: BlockTimberBreps, ResultPlane2, ResultPlane3, AlignedTool2, ...
    - 全局日志: Log
    - 最终构件: CutTimbers, FailTimbers
"""

import sys
import traceback

import Rhino.Geometry as rg
from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    build_qiao_tool,
    FTAligner,
    FT_CutTimberByTools,
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
    广播/截断参数到长度 n（参考 FT_AlignToolToTimber 中的策略）：

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

    仅用于“本来就是标量语义”的参数：
    如 qi_height / sha_width / qi_offset_fen / extrude_length 等；
    不用于 FlipY / BlockRotDeg / IndexOrigin / IndexPlane 等
    需要广播或多次运算的参数。
    """
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) > 0 else default
    return val


# =========================================================
# 工具函数：All → 嵌套字典
# =========================================================
def parse_all_to_dict(all_list):
    """
    输入：
        all_list = [
            ("FT_AlignToolToTimber_1__FlipY", [...]),
            ("FT_AlignToolToTimber_1__BlockRotDeg", 90),
            ("FT_timber_block_uniform__length_fen", 36),
            ...
        ]

    输出为嵌套 dict：
        {
            "FT_AlignToolToTimber_1": {
                "FlipY": [...],
                "BlockRotDeg": 90
            },
            "FT_timber_block_uniform": {
                "length_fen": 36,
                "width_fen":  36,
                "height_fen": 20,
                "reference_plane": "WorldXZ"
            },
            "PlaneFromLists_1": {
                "IndexOrigin": [...],
                "IndexPlane":  [...],
                "wrap": true
            },
            ...
        }
    """
    result = {}

    if not all_list:
        return result

    for key, value in all_list:
        if "__" not in key:
            comp = key
            param = None
        else:
            comp, param = key.split("__", 1)

        if comp not in result:
            result[comp] = {}

        if param is None:
            result[comp] = value
        else:
            result[comp][param] = value

    return result


# =========================================================
# 工具函数：从 AllDict 获取参数值（组件名 + 参数名）
# =========================================================
def all_get(AllDict, comp_name, param_name, default=None):
    """
    AllDict 结构示意：
        AllDict["FT_timber_block_uniform"]["length_fen"] = 36

    优先从 AllDict 中读取：
        - 若存在：返回其值
        - 若不存在：返回 default
    """
    if AllDict is None:
        return default

    comp = AllDict.get(comp_name, None)
    if comp is None or not isinstance(comp, dict):
        return default

    return comp.get(param_name, default)


# =========================================================
# 工具函数：列表/标量 → 标量
# =========================================================
def to_scalar(val, default=None):
    """
    有些参数在 JSON 中可能写成 [36] 这样的单元素列表。
    为了简化使用，这里把：
        - list/tuple → 取第一个元素（若为空则用 default）
        - 其它标量 → 原样返回
        - None      → default
    """
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        if len(val) == 0:
            return default
        return val[0]
    return val


# =========================================================
# 工具函数：根据字符串构造参考平面
# =========================================================
def make_reference_plane(tag=None):
    """
    根据数据库中的字符串构造 GH 参考平面：
        - XY Plane：X = (1,0,0)，Y = (0,1,0)，Z = (0,0,1)
        - XZ Plane：X = (1,0,0)，Y = (0,0,1)，Z = (0,-1,0)
        - YZ Plane：X = (0,1,0)，Y = (0,0,1)，Z = (1,0,0)

    若 tag 为 None 或无法识别，默认使用 XZ Plane。
    """
    origin = rg.Point3d(0.0, 0.0, 0.0)
    if tag is None:
        mode = "XZ"
    else:
        s = str(tag).upper()
        if "XY" in s:
            mode = "XY"
        elif "YZ" in s:
            mode = "YZ"
        else:
            mode = "XZ"

    if mode == "XY":
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
    elif mode == "YZ":
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
    else:  # XZ
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)

    return rg.Plane(origin, x, y)


# ======================================================================
# Solver 主类
# ======================================================================
class JIAOHU_DOU_doukoutiaoSolver(object):

    def __init__(self, DBPath, base_point, Refresh):
        # ------------------------------
        # 组件输入
        # ------------------------------
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh

        # ------------------------------
        # Step 1 输出
        # ------------------------------
        self.All = None          # 原始 All 列表
        self.AllDict = None      # 嵌套字典
        self.DBLog = []          # DBJsonReader 的日志

        # ------------------------------
        # Step 2 输出：主木坯
        # ------------------------------
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
        self.TimberLog = []

        # ------------------------------
        # Step 3：PlaneFromLists::1
        # ------------------------------
        self.BasePlane1 = []      # list[Plane]
        self.OriginPoint1 = []    # list[Point3d]
        self.ResultPlane1 = []    # list[Plane]

        # ------------------------------
        # Step 3：FT_QiAo
        # ------------------------------
        self.ToolBrep = None
        self.BasePoint = None
        self.BaseLine = None
        self.SecPlane = None
        self.FacePlane = None

        # ------------------------------
        # Step 3：FT_AlignToolToTimber::1
        # ------------------------------
        self.AlignedTool = []
        self.XForm = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo = []

        # ------------------------------
        # Step 4：FT_BlockCutter + PFL2 + PFL3 + Align::2
        # ------------------------------
        self.BlockTimberBreps = []      # [Brep0, Brep1, ...]
        self.BlockFaceList = []         # [[faces_0], [faces_1], ...]
        self.BlockPointList = []        # [[points_0], [points_1], ...]
        self.BlockEdgeList = []         # [[edges_0], [edges_1], ...]
        self.BlockCenterPoint = []      # [center_pt_0, center_pt_1, ...]
        self.BlockCenterAxisLines = []  # [[axis_lines_0], [axis_lines_1], ...]
        self.BlockEdgeMidPoints = []    # [[edge_midpts_0], [edge_midpts_1], ...]
        self.BlockFacePlaneList = []    # [[face_planes_0], [face_planes_1], ...]
        self.BlockCorner0Planes = []    # [[corner0_planes_0], [corner0_planes_1], ...]
        self.BlockLocalAxesPlane = []   # [local_axes_plane_0, ...]
        self.BlockAxisX = []            # [axis_x_0, ...]
        self.BlockAxisY = []            # [axis_y_0, ...]
        self.BlockAxisZ = []            # [axis_z_0, ...]
        self.BlockFaceDirTags = []      # [[face_tags_0], ...]
        self.BlockEdgeDirTags = []      # [[edge_tags_0], ...]
        self.BlockCorner0EdgeDirs = []  # [[corner0_dirs_0], ...]

        # PlaneFromLists::2 —— 主木坯上的 BlockFacePlane
        self.BasePlane2 = []
        self.OriginPoint2 = []
        self.ResultPlane2 = []

        # PlaneFromLists::3 —— BlockCutter 上的 ToolBasePlane
        self.BasePlane3 = []
        self.OriginPoint3 = []
        self.ResultPlane3 = []

        # Align::2 结果
        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []

        # ------------------------------
        # 最终切削结果
        # ------------------------------
        self.CutTimbers = []
        self.FailTimbers = []

        # 全局日志
        self.Log = []

    # -----------------------------------------------------
    # Step 1：读取数据库
    # -----------------------------------------------------
    def step1_read_db(self):

        self.Log.append("Step 1：读取数据库…")

        try:
            ghenv_obj = globals().get("ghenv", None)

            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="JIAOHU_DOU_doukoutiao",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=ghenv_obj
            )

            Value, All, LogLines = reader.run()

            self.DBLog.extend(LogLines)
            self.All = All
            self.AllDict = parse_all_to_dict(All)

            self.Log.append("Step 1 完成：已读取 All 列表并转换为 AllDict。")

        except Exception as e:
            msg = "[DB ERROR] {}".format(e)
            self.Log.append(msg)
            self.DBLog.append(msg)
            traceback.print_exc()
            self.All = None
            self.AllDict = None

    # -----------------------------------------------------
    # Step 2：原始木料构建（FT_timber_block_uniform）
    # -----------------------------------------------------
    def step2_timber(self):
        """
        使用 FT_timber_block_uniform 的参数，从 AllDict 中读取：
            - length_fen  → FT_timber_block_uniform__length_fen
            - width_fen   → FT_timber_block_uniform__width_fen
            - height_fen  → FT_timber_block_uniform__height_fen
            - reference_plane → FT_timber_block_uniform__reference_plane (可选)
        base_point：
            - 优先使用组件输入端 base_point
            - 若为 None 则使用原点 (0,0,0)
        """
        self.Log.append("Step 2：FT_timber_block_uniform · 原始木料构建…")

        if self.AllDict is None:
            self.Log.append("[Step 2] AllDict 为空，跳过木料构建。")
            return

        # 2.1 从 AllDict 中获取参数（若缺失则用默认值）
        length_raw = all_get(self.AllDict, "FT_timber_block_uniform", "length_fen", 32.0)
        width_raw  = all_get(self.AllDict, "FT_timber_block_uniform", "width_fen",  32.0)
        height_raw = all_get(self.AllDict, "FT_timber_block_uniform", "height_fen", 20.0)
        plane_tag  = all_get(self.AllDict, "FT_timber_block_uniform", "reference_plane", None)

        try:
            length_fen = float(to_scalar(length_raw, 32.0))
        except Exception:
            length_fen = 32.0
            self.Log.append("[Step 2] length_fen 解析失败，使用默认 32.0。")

        try:
            width_fen = float(to_scalar(width_raw, 32.0))
        except Exception:
            width_fen = 32.0
            self.Log.append("[Step 2] width_fen 解析失败，使用默认 32.0。")

        try:
            height_fen = float(to_scalar(height_raw, 20.0))
        except Exception:
            height_fen = 20.0
            self.Log.append("[Step 2] height_fen 解析失败，使用默认 20.0。")

        # 2.2 base_point：优先组件输入端，其次原点
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)
        else:
            if isinstance(bp, rg.Point):
                bp = bp.Location
            elif isinstance(bp, rg.Point3d):
                pass
            else:
                try:
                    bp = rg.Point3d(bp)
                except Exception:
                    self.Log.append("[Step 2] base_point 类型无法识别，使用原点。")
                    bp = rg.Point3d(0.0, 0.0, 0.0)

        # 2.3 参考平面：默认为 XZ Plane
        reference_plane = make_reference_plane(plane_tag)

        # 2.4 调用 build_timber_block_uniform
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
            self.FaceList        = faces
            self.PointList       = points
            self.EdgeList        = edges
            self.CenterPoint     = center_pt
            self.CenterAxisLines = center_axes
            self.EdgeMidPoints   = edge_midpts
            self.FacePlaneList   = face_planes
            self.Corner0Planes   = corner0_planes
            self.LocalAxesPlane  = local_axes_plane
            self.AxisX           = axis_x
            self.AxisY           = axis_y
            self.AxisZ           = axis_z
            self.FaceDirTags     = face_tags
            self.EdgeDirTags     = edge_tags
            self.Corner0EdgeDirs = corner0_dirs
            self.TimberLog       = log_lines

            for l in log_lines:
                self.Log.append("[TIMBER] " + str(l))

            self.Log.append("Step 2 完成：木料已成功构建。")

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

            err_msg = "[Step 2 ERROR] {}".format(e)
            self.Log.append(err_msg)
            traceback.print_exc()

    # -----------------------------------------------------
    # Step 3：欹䫜（QiAo）—— PFL1 + FT_QiAo + Align::1
    # -----------------------------------------------------
    def step3_qiao(self):

        self.Log.append("Step 3：PlaneFromLists::1 + FT_QiAo + Align::1…")

        # ----------------- 3.1 PlaneFromLists::1 -----------------
        idx_o_raw = all_get(self.AllDict, "PlaneFromLists_1", "IndexOrigin", [])
        idx_p_raw = all_get(self.AllDict, "PlaneFromLists_1", "IndexPlane", [])
        wrap_raw  = all_get(self.AllDict, "PlaneFromLists_1", "wrap", True)

        idx_o_list = _to_list(idx_o_raw)
        idx_p_list = _to_list(idx_p_raw)
        n_pf = min(len(idx_o_list), len(idx_p_list))

        self.BasePlane1 = []
        self.OriginPoint1 = []
        self.ResultPlane1 = []

        if n_pf == 0:
            self.Log.append("[PFL1] IndexOrigin / IndexPlane 列表为空，跳过 PlaneFromLists::1。")
        else:
            wrap = bool(_scalar_from_list(wrap_raw, True))
            builder = FTPlaneFromLists(wrap=wrap)

            for i in range(n_pf):
                io = idx_o_list[i]
                ip = idx_p_list[i]
                self.Log.append("[PFL1] 第 {} 组：IndexOrigin = {}, IndexPlane = {}".format(i, io, ip))

                try:
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

                except Exception as e:
                    self.Log.append("[PFL1] 第 {} 组 build_plane 出错: {}".format(i, e))

        # ----------------- 3.2 FT_QiAo -----------------
        qi_h_raw       = all_get(self.AllDict, "FT_QiAo", "qi_height",       8.0)
        sha_w_raw      = all_get(self.AllDict, "FT_QiAo", "sha_width",       4.0)
        qi_offset_raw  = all_get(self.AllDict, "FT_QiAo", "qi_offset_fen",   1.0)
        extrude_len_raw= all_get(self.AllDict, "FT_QiAo", "extrude_length", 46.0)

        qi_h       = _scalar_from_list(qi_h_raw,       8.0)
        sha_w      = _scalar_from_list(sha_w_raw,      4.0)
        qi_offset  = _scalar_from_list(qi_offset_raw,  1.0)
        extrude_len= _scalar_from_list(extrude_len_raw,46.0)

        base_pt = rg.Point3d(0, 0, 0)
        ref_plane = rg.Plane(
            rg.Point3d(0, 0, 0),
            rg.Vector3d.XAxis,
            rg.Vector3d.ZAxis
        )
        extrude_positive = False

        try:
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
        except Exception as e:
            self.Log.append("[QiAo] build_qiao_tool 出错: {}".format(e))
            self.ToolBrep = None
            self.BasePoint = None
            self.BaseLine = None
            self.SecPlane = None
            self.FacePlane = None
            return

        # ----------------- 3.3 Align::1 -----------------
        BlockRotDeg_raw = all_get(self.AllDict, "FT_AlignToolToTimber_1", "BlockRotDeg", 0.0)
        FlipY_raw       = all_get(self.AllDict, "FT_AlignToolToTimber_1", "FlipY",       0)

        self.Log.append("[Align1] BlockRotDeg 原始值 = {!r}".format(BlockRotDeg_raw))
        self.Log.append("[Align1] FlipY       原始值 = {!r}".format(FlipY_raw))

        # 其它对位参数默认 None
        ToolRotDeg_raw     = None
        ToolContactPt_raw  = None
        BlockTargetPt_raw  = None
        Mode_raw           = None
        ToolDir_raw        = None
        TargetDir_raw      = None
        DepthOffset_raw    = None
        MoveU_raw          = None
        MoveV_raw          = None
        FlipX_raw          = 0
        FlipZ_raw          = 0

        BlockFacePlane_raw = self.ResultPlane1

        tools_list_base = _to_list(self.ToolBrep)
        tool_count = len(tools_list_base)

        if tool_count == 0:
            self.Log.append("[Align1] ToolBrep 为空，无法对位。")
            self.AlignedTool = []
            self.XForm = []
            self.SourcePlane = []
            self.TargetPlane = []
            self.SourcePoint = []
            self.TargetPoint = []
            self.DebugInfo = []
            return

        # N：运算次数
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

        tools_list   = _broadcast_param(tools_list_base,    N, "ToolGeo")
        tool_planes  = _broadcast_param(self.FacePlane,     N, "ToolBasePlane")
        tool_rots    = _broadcast_param(ToolRotDeg_raw,     N, "ToolRotDeg")
        tool_pts     = _broadcast_param(ToolContactPt_raw,  N, "ToolContactPoint")
        block_planes = _broadcast_param(BlockFacePlane_raw, N, "BlockFacePlane")
        block_rots   = _broadcast_param(BlockRotDeg_raw,    N, "BlockRotDeg")
        flip_xs      = _broadcast_param(FlipX_raw,          N, "FlipX")
        flip_ys      = _broadcast_param(FlipY_raw,          N, "FlipY")
        flip_zs      = _broadcast_param(FlipZ_raw,          N, "FlipZ")
        block_pts    = _broadcast_param(BlockTargetPt_raw,  N, "BlockTargetPoint")
        modes        = _broadcast_param(Mode_raw,           N, "Mode")
        tool_dirs    = _broadcast_param(ToolDir_raw,        N, "ToolDir")
        target_dirs  = _broadcast_param(TargetDir_raw,      N, "TargetDir")
        depth_offsets= _broadcast_param(DepthOffset_raw,    N, "DepthOffset")
        move_us      = _broadcast_param(MoveU_raw,          N, "MoveU")
        move_vs      = _broadcast_param(MoveV_raw,          N, "MoveV")

        self.AlignedTool = []
        self.XForm = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo = []

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

    # -----------------------------------------------------
    # Step 4：耳平 —— BlockCutter + PFL2 + PFL3 + Align::2 + Cut
    # -----------------------------------------------------
    def step4_block_cutter(self):

        self.Log.append("===== Step 4: FT_BlockCutter + PFL2 + PFL3 + Align::2 + Cut =====")

        # ----------------- 4.1 FT_BlockCutter -----------------
        bc_L_raw = all_get(self.AllDict, "FT_BlockCutter", "length_fen", 32.0)
        bc_W_raw = all_get(self.AllDict, "FT_BlockCutter", "width_fen",  32.0)
        bc_H_raw = all_get(self.AllDict, "FT_BlockCutter", "height_fen", 20.0)

        Nc = max(
            _param_length(bc_L_raw),
            _param_length(bc_W_raw),
            _param_length(bc_H_raw),
        )
        if Nc <= 0:
            Nc = 1

        bc_L_list = _broadcast_param(bc_L_raw, Nc, "FT_BlockCutter__length_fen")
        bc_W_list = _broadcast_param(bc_W_raw, Nc, "FT_BlockCutter__width_fen")
        bc_H_list = _broadcast_param(bc_H_raw, Nc, "FT_BlockCutter__height_fen")

        self.Log.append("[BlockCutter] 读取到 {} 组长宽高，准备生成 {} 个 cutter。".format(Nc, Nc))

        bc_base_pt = rg.Point3d(0.0, 0.0, 0.0)
        bc_ref_plane = rg.Plane(
            rg.Point3d(0, 0, 0),
            rg.Vector3d.XAxis,
            rg.Vector3d.ZAxis
        )

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
            Li = float(bc_L_list[i])
            Wi = float(bc_W_list[i])
            Hi = float(bc_H_list[i])

            self.Log.append(
                "[BlockCutter] 第 {} 个 cutter: L={}, W={}, H={}".format(i, Li, Wi, Hi)
            )

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
                    log_c,
                ) = build_timber_block_uniform(
                    Li,
                    Wi,
                    Hi,
                    bc_base_pt,
                    bc_ref_plane
                )

                self.BlockTimberBreps.append(timber_brep)
                self.BlockFaceList.append(faces)
                self.BlockPointList.append(points)
                self.BlockEdgeList.append(edges)
                self.BlockCenterPoint.append(center_pt)
                self.BlockCenterAxisLines.append(center_axes)
                self.BlockEdgeMidPoints.append(edge_midpts)
                self.BlockFacePlaneList.append(face_planes)
                self.BlockCorner0Planes.append(corner0_planes)
                self.BlockLocalAxesPlane.append(local_axes_plane)
                self.BlockAxisX.append(axis_x)
                self.BlockAxisY.append(axis_y)
                self.BlockAxisZ.append(axis_z)
                self.BlockFaceDirTags.append(face_tags)
                self.BlockEdgeDirTags.append(edge_tags)
                self.BlockCorner0EdgeDirs.append(corner0_dirs)

                for l in log_c:
                    self.Log.append("[BlockCutter {}] {}".format(i, l))

            except Exception as e:
                self.Log.append("[BlockCutter {}] 生成失败: {}".format(i, e))

        # ----------------- 4.2 PlaneFromLists::2 （主木坯上）-----------------
        idx2_o_raw = all_get(self.AllDict, "PlaneFromLists_2", "IndexOrigin", [])
        idx2_p_raw = all_get(self.AllDict, "PlaneFromLists_2", "IndexPlane", [])
        wrap2_raw  = all_get(self.AllDict, "PlaneFromLists_2", "wrap", True)

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
                io2 = idx2_o_list[i]
                ip2 = idx2_p_list[i]
                self.Log.append(
                    "[PFL2] 第 {} 组：IndexOrigin = {}, IndexPlane = {}".format(i, io2, ip2)
                )

                try:
                    base_pl2, org_pt2, res_pl2, log_pf2 = builder2.build_plane(
                        self.EdgeMidPoints,
                        self.Corner0Planes,
                        io2,
                        ip2
                    )

                    self.BasePlane2.append(base_pl2)
                    self.OriginPoint2.append(org_pt2)
                    self.ResultPlane2.append(res_pl2)

                    for l in log_pf2:
                        self.Log.append("[PFL2][{}] ".format(i) + l)
                except Exception as e:
                    self.Log.append("[PFL2] 第 {} 组 build_plane 出错: {}".format(i, e))

        # ----------------- 4.3 PlaneFromLists::3 （BlockCutter 上）-----------------
        idx3_o_raw = all_get(self.AllDict, "PlaneFromLists_3", "IndexOrigin", [])
        idx3_p_raw = all_get(self.AllDict, "PlaneFromLists_3", "IndexPlane", [])
        wrap3_raw  = all_get(self.AllDict, "PlaneFromLists_3", "wrap", True)

        idx3_o_list = _to_list(idx3_o_raw)
        idx3_p_list = _to_list(idx3_p_raw)
        n_pf3 = min(len(idx3_o_list), len(idx3_p_list))

        self.BasePlane3 = []
        self.OriginPoint3 = []
        self.ResultPlane3 = []

        if n_pf3 == 0:
            self.Log.append("[PFL3] IndexOrigin / IndexPlane 列表为空，跳过 PlaneFromLists::3。")
        else:
            wrap3 = bool(_scalar_from_list(wrap3_raw, True))
            builder3 = FTPlaneFromLists(wrap=wrap3)

            if not self.BlockEdgeMidPoints or not self.BlockCorner0Planes:
                self.Log.append("[PFL3] BlockEdgeMidPoints / BlockCorner0Planes 为空，无法处理 PFL3。")
            else:
                n_branches = min(len(self.BlockEdgeMidPoints), len(self.BlockCorner0Planes))
                self.Log.append("[PFL3] 检测到 {} 个 BlockCutter 分支。".format(n_branches))

                for bi in range(n_branches):
                    branch_pts = self.BlockEdgeMidPoints[bi]
                    branch_pls = self.BlockCorner0Planes[bi]

                    for i in range(n_pf3):
                        io3 = idx3_o_list[i]
                        ip3 = idx3_p_list[i]

                        try:
                            bp3, op3, rp3, log_pf3 = builder3.build_plane(
                                branch_pts,
                                branch_pls,
                                io3,
                                ip3
                            )

                            self.BasePlane3.append(bp3)
                            self.OriginPoint3.append(op3)
                            self.ResultPlane3.append(rp3)

                            for l in log_pf3:
                                self.Log.append("[PFL3][branch {}][{}] ".format(bi, i) + l)
                        except Exception as e:
                            self.Log.append("[PFL3][branch {}][{}] build_plane 出错: {}".format(bi, i, e))

        # ----------------- 4.4 Align::2 （BlockCutter 对位）-----------------
        BlockRotDeg2_raw = all_get(self.AllDict, "FT_AlignToolToTimber_2", "BlockRotDeg", 0.0)
        FlipX2_raw       = all_get(self.AllDict, "FT_AlignToolToTimber_2", "FlipX",       0)
        FlipY2_raw       = all_get(self.AllDict, "FT_AlignToolToTimber_2", "FlipY",       0)
        FlipZ2_raw       = all_get(self.AllDict, "FT_AlignToolToTimber_2", "FlipZ",       0)

        self.Log.append("[Align2] BlockRotDeg 原始值 = {!r}".format(BlockRotDeg2_raw))
        self.Log.append("[Align2] FlipX       原始值 = {!r}".format(FlipX2_raw))
        self.Log.append("[Align2] FlipY       原始值 = {!r}".format(FlipY2_raw))
        self.Log.append("[Align2] FlipZ       原始值 = {!r}".format(FlipZ2_raw))

        ToolRotDeg2_raw   = None
        ToolContactPt2_raw= None
        BlockTargetPt2_raw= None
        Mode2_raw         = None
        ToolDir2_raw      = None
        TargetDir2_raw    = None
        DepthOffset2_raw  = None
        MoveU2_raw        = None
        MoveV2_raw        = None

        ToolBasePlane2_raw  = self.ResultPlane3
        BlockFacePlane2_raw = self.ResultPlane2

        tools2_list_base = _to_list(self.BlockTimberBreps)
        tool2_count = len(tools2_list_base)

        if tool2_count == 0 or all(t is None for t in tools2_list_base):
            self.Log.append("[Align2] 没有 BlockCutter 几何，跳过对位。")
            self.AlignedTool2 = []
            self.XForm2 = []
            self.SourcePlane2 = []
            self.TargetPlane2 = []
            self.SourcePoint2 = []
            self.TargetPoint2 = []
            self.DebugInfo2 = []
            return

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
            N2 = tool2_count

        self.Log.append("[Align2] 计算得到对位次数 N2 = {}".format(N2))

        tools2_list   = _broadcast_param(tools2_list_base,    N2, "ToolGeo")
        tool2_planes  = _broadcast_param(ToolBasePlane2_raw,  N2, "ToolBasePlane")
        tool2_rots    = _broadcast_param(ToolRotDeg2_raw,     N2, "ToolRotDeg")
        tool2_pts     = _broadcast_param(ToolContactPt2_raw,  N2, "ToolContactPoint")
        block2_planes = _broadcast_param(BlockFacePlane2_raw, N2, "BlockFacePlane")
        block2_rots   = _broadcast_param(BlockRotDeg2_raw,    N2, "BlockRotDeg")
        flip2_xs      = _broadcast_param(FlipX2_raw,          N2, "FlipX")
        flip2_ys      = _broadcast_param(FlipY2_raw,          N2, "FlipY")
        flip2_zs      = _broadcast_param(FlipZ2_raw,          N2, "FlipZ")
        block2_pts    = _broadcast_param(BlockTargetPt2_raw,  N2, "BlockTargetPoint")
        modes2        = _broadcast_param(Mode2_raw,           N2, "Mode")
        tool2_dirs    = _broadcast_param(ToolDir2_raw,        N2, "ToolDir")
        target2_dirs  = _broadcast_param(TargetDir2_raw,      N2, "TargetDir")
        depth2_offsets= _broadcast_param(DepthOffset2_raw,    N2, "DepthOffset")
        move2_us      = _broadcast_param(MoveU2_raw,          N2, "MoveU")
        move2_vs      = _broadcast_param(MoveV2_raw,          N2, "MoveV")

        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []

        for i in range(N2):
            aligned2, xf2, src_pl2, tgt_pl2, src_pt2, tgt_pt2, dbg2 = FTAligner.align(
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
                block2_rots[i],
            )

            self.AlignedTool2.append(aligned2)
            self.XForm2.append(xf2)
            self.SourcePlane2.append(src_pl2)
            self.TargetPlane2.append(tgt_pl2)
            self.SourcePoint2.append(src_pt2)
            self.TargetPoint2.append(tgt_pt2)

            if aligned2 is None:
                self.DebugInfo2.append("对位失败[{}]: {}".format(i, dbg2))
            else:
                self.DebugInfo2.append("对位成功[{}]: {}".format(i, dbg2))

        # ----------------- 4.5 最终切削：QiAo + BlockCutter 一次性切主木坯 -----------------
        tools_all = []

        if self.AlignedTool:
            tools_all.extend([t for t in self.AlignedTool if t is not None])
        if self.AlignedTool2:
            tools_all.extend([t for t in self.AlignedTool2 if t is not None])

        if self.TimberBrep is None or not tools_all:
            self.Log.append("[Cut] TimberBrep 或 Tools 为空，无法切削。")
            self.CutTimbers = []
            self.FailTimbers = []
            return

        try:
            cutter = FT_CutTimberByTools(self.TimberBrep, tools_all)
            cut, fail, logc = cutter.run()

            self.CutTimbers = cut
            self.FailTimbers = fail

            for l in logc:
                self.Log.append("[Cut] " + l)

        except Exception as e:
            self.Log.append("[Cut] 切削失败: {}".format(e))
            self.CutTimbers = []
            self.FailTimbers = []

    # -----------------------------------------------------
    # 主控入口
    # -----------------------------------------------------
    def run(self):
        """
        当前阶段：
            - Step 1：读 DB
            - Step 2：主木坯
            - Step 3：欹䫜对位
            - Step 4：耳平 BlockCutter + 总切削
        """
        self.step1_read_db()

        if self.All is None or self.AllDict is None:
            self.Log.append("run: All / AllDict 为空，终止后续步骤。")
            return self

        self.step2_timber()
        self.step3_qiao()
        self.step4_block_cutter()

        return self


# ======================================================================
# GH Python 组件输出绑定区
# ======================================================================
if __name__ == "__main__":

    solver = JIAOHU_DOU_doukoutiaoSolver(DBPath, base_point, Refresh)
    solver.run()

    # --------- Step 1 ---------
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = solver.DBLog

    # --------- Step 2：主木坯 ---------
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

    # --------- Step 3：欹䫜 ---------
    BasePlane1   = solver.BasePlane1
    OriginPoint1 = solver.OriginPoint1
    ResultPlane1 = solver.ResultPlane1

    ToolBrep  = solver.ToolBrep
    BasePoint = solver.BasePoint
    BaseLine  = solver.BaseLine
    SecPlane  = solver.SecPlane
    FacePlane = solver.FacePlane

    AlignedTool = solver.AlignedTool
    XForm       = solver.XForm
    SourcePlane = solver.SourcePlane
    TargetPlane = solver.TargetPlane
    SourcePoint = solver.SourcePoint
    TargetPoint = solver.TargetPoint
    DebugInfo   = solver.DebugInfo

    # --------- Step 4：BlockCutter + 对位 ---------
    BlockTimberBreps   = solver.BlockTimberBreps
    BlockFaceList      = solver.BlockFaceList
    BlockPointList     = solver.BlockPointList
    BlockEdgeList      = solver.BlockEdgeList
    BlockCenterPoint   = solver.BlockCenterPoint
    BlockCenterAxisLines = solver.BlockCenterAxisLines
    BlockEdgeMidPoints = solver.BlockEdgeMidPoints
    BlockFacePlaneList = solver.BlockFacePlaneList
    BlockCorner0Planes = solver.BlockCorner0Planes
    BlockLocalAxesPlane= solver.BlockLocalAxesPlane
    BlockAxisX         = solver.BlockAxisX
    BlockAxisY         = solver.BlockAxisY
    BlockAxisZ         = solver.BlockAxisZ
    BlockFaceDirTags   = solver.BlockFaceDirTags
    BlockEdgeDirTags   = solver.BlockEdgeDirTags
    BlockCorner0EdgeDirs = solver.BlockCorner0EdgeDirs

    BasePlane2   = solver.BasePlane2
    OriginPoint2 = solver.OriginPoint2
    ResultPlane2 = solver.ResultPlane2

    BasePlane3   = solver.BasePlane3
    OriginPoint3 = solver.OriginPoint3
    ResultPlane3 = solver.ResultPlane3

    AlignedTool2 = solver.AlignedTool2
    XForm2       = solver.XForm2
    SourcePlane2 = solver.SourcePlane2
    TargetPlane2 = solver.TargetPlane2
    SourcePoint2 = solver.SourcePoint2
    TargetPoint2 = solver.TargetPoint2
    DebugInfo2   = solver.DebugInfo2

    # --------- 全局日志 ---------
    Log = solver.Log

    # --------- 最终成品 ---------
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers



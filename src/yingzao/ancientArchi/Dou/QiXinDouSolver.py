# -*- coding: utf-8 -*-
"""
QiXinDouSolver.py
齊心枓 一体化组件 · Step 1 + Step 2 + Step 3 + Step 4

Step 1：DBJsonReader 读取 DG_Dou / QIXIN_DOU / params_json（All, AllDict）
Step 2：FT_timber_block_uniform 主木料（XZ Plane）
Step 3：PlaneFromLists::1 + FT_QiAo + FT_AlignToolToTimber::1
Step 4：耳平 · FT_BlockCutter + PlaneFromLists::2 + PlaneFromLists::3
        + FT_AlignToolToTimber::2 + FT_CutTimberByTools
"""

import Rhino.Geometry as rg
import Grasshopper as gh

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    build_qiao_tool,
    FTAligner,
    FT_CutTimberByTools,   # ★ 新增：切削主木坯
)

from yingzao.ancientArchi import (
    _to_list,
    _param_length,
    _broadcast_param,
    _scalar_from_list,
    parse_all_to_dict,
    all_get,
    to_scalar,
    make_reference_plane,
)

# ======================================================================
# 工具函数
# ======================================================================

def all_to_dict(all_list):
    """将 [(key,value), ...] 转成 dict"""
    d = {}
    if not all_list:
        return d
    for item in all_list:
        try:
            k, v = item
        except:
            continue
            # 跳过不合法条目
        d[k] = v
    return d


# 下面这几个工具函数虽然已从 yingzao.ancientArchi 导入，
# 但这里保留本地版本，以防未来库侧实现有调整时不影响当前 Solver 行为。

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


# ======================================================================
# Solver 主类
# ======================================================================

class QiXinDouSolver(object):

    def __init__(self, DBPath=None, base_point=None, Refresh=False, ghenv=None):

        # ---------------- 输入 ----------------
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = bool(Refresh)
        self.ghenv = ghenv

        # ---------------- 通用输出 ----------------
        self.Log = []
        self.CutTimbers = []
        self.FailTimbers = []

        # ---------------- Step1：DB ----------------
        self.DBValue = None
        self.All = []
        self.AllDict = {}
        self.DBLog = []

        # ---------------- Step2：FT_timber_block_uniform ----------------
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

        # ---------------- Step3：PlaneFromLists::1 ----------------
        self.QiAo_BasePlane = None
        self.QiAo_OriginPoint = None
        self.QiAo_BlockFacePlane = None  # ResultPlane
        self.QiAo_PlaneLog = []

        # ---------------- Step3：FT_QiAo ----------------
        self.QiAo_ToolBrep = None
        self.QiAo_BasePoint = None
        self.QiAo_BaseLine = None
        self.QiAo_SecPlane = None
        self.QiAo_FacePlane = None

        # ---------------- Step3：FT_AlignToolToTimber::1 ----------------
        self.QiAo_AlignedTools = []
        self.QiAo_XForms = []
        self.QiAo_SourcePlanes = []
        self.QiAo_TargetPlanes = []
        self.QiAo_SourcePoints = []
        self.QiAo_TargetPoints = []
        self.QiAo_DebugInfo = []

        # ---------------- Step4：FT_BlockCutter + PFL2 + PFL3 + Align::2 ----------------
        # BlockCutter（耳平刀具）几何 / 特征
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

        # Align::2 结果（BlockCutter 对位）
        self.AlignedTool2 = []
        self.XForm2 = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2 = []


    # ------------------------------------------------------------------
    # STEP 1：读取数据库
    # ------------------------------------------------------------------
    def step1_read_db(self):

        if not self.DBPath:
            self.Log.append("[DB] DBPath 为空")
            return

        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="QIXIN_DOU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            value, all_items, db_log = reader.run()

            self.DBValue = value
            self.All = list(all_items) if all_items else []
            self.DBLog = list(db_log) if db_log else []
            self.AllDict = all_to_dict(self.All)

            for m in self.DBLog:
                self.Log.append("[DB] " + m)

            self.Log.append("[DB] All 项数 = {}".format(len(self.All)))

        except Exception as e:
            self.Log.append("[DB] 读取数据库异常: {}".format(e))


    # ------------------------------------------------------------------
    # STEP 2：原始木料（FT_timber_block_uniform）
    # ------------------------------------------------------------------
    def step2_timber_block(self):

        self.Log.append("[STEP2] 构建原始木料 FT_timber_block_uniform")

        A = self.AllDict

        # length / width / height
        length_fen = A.get("FT_timber_block_uniform__length_fen", 32.0)
        width_fen  = A.get("FT_timber_block_uniform__width_fen", 32.0)
        height_fen = A.get("FT_timber_block_uniform__height_fen", 20.0)

        try:
            length_fen = float(length_fen)
        except:
            length_fen = 32.0
        try:
            width_fen = float(width_fen)
        except:
            width_fen = 32.0
        try:
            height_fen = float(height_fen)
        except:
            height_fen = 20.0

        # base_point：优先 GH 输入；否则原点
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0, 0, 0)
        else:
            if isinstance(bp, rg.Point):
                bp = bp.Location

        # reference_plane = XZ Plane
        X = rg.Vector3d(1, 0, 0)
        Y = rg.Vector3d(0, 0, 1)
        origin = rg.Point3d(0, 0, 0)
        reference_plane = rg.Plane(origin, X, Y)

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
            self.TimberLog = log_lines

            for line in log_lines:
                self.Log.append("[STEP2] " + line)

        except Exception as e:
            self.Log.append("[STEP2] build_timber_block_uniform 出错: {}".format(e))
            self.TimberBrep = None


    # ------------------------------------------------------------------
    # STEP 3：PlaneFromLists::1 + FT_QiAo + FT_AlignToolToTimber::1
    # ------------------------------------------------------------------
    def step3_qiao_tool(self):

        A = self.AllDict
        self.Log.append("[STEP3] 欹䫜部分：PlaneFromLists::1 + FT_QiAo + 对位")

        # ----------------- 3.1 PlaneFromLists::1 -----------------
        self.Log.append("[STEP3] PlaneFromLists::1 开始处理…")

        idx_o_raw = A.get("PlaneFromLists_1__IndexOrigin", [])
        idx_p_raw = A.get("PlaneFromLists_1__IndexPlane", [])
        wrap_raw  = A.get("PlaneFromLists_1__wrap", True)

        idx_o_list = _to_list(idx_o_raw)
        idx_p_list = _to_list(idx_p_raw)

        n_pf = min(len(idx_o_list), len(idx_p_list))

        self.QiAo_BasePlane = []
        self.QiAo_OriginPoint = []
        self.QiAo_BlockFacePlane = []

        if n_pf == 0:
            self.Log.append("[STEP3:Plane] IndexOrigin 或 IndexPlane 列表为空，跳过 PlaneFromLists::1。")
        else:
            wrap = bool(_scalar_from_list(wrap_raw, True))
            builder = FTPlaneFromLists(wrap=wrap)

            for i in range(n_pf):
                io = idx_o_list[i]
                ip = idx_p_list[i]

                try:
                    base_pl, org_pt, res_pl, log_pf = builder.build_plane(
                        self.EdgeMidPoints,
                        self.Corner0Planes,
                        io,
                        ip
                    )

                    self.QiAo_BasePlane.append(base_pl)
                    self.QiAo_OriginPoint.append(org_pt)
                    self.QiAo_BlockFacePlane.append(res_pl)

                    for l in log_pf:
                        self.Log.append("[STEP3:Plane][{}] {}".format(i, l))

                except Exception as e:
                    self.Log.append("[STEP3:Plane] 第 {} 次 build_plane 出错: {}".format(i, e))

        # ----------------- 3.2 FT_QiAo -----------------
        try:
            qi_height      = A.get("FT_QiAo__qi_height",      8.0)
            sha_width      = A.get("FT_QiAo__sha_width",      4.0)
            qi_offset_fen  = A.get("FT_QiAo__qi_offset_fen",  1.0)
            extrude_length = A.get("FT_QiAo__extrude_length", 36.0 + 10.0)

            try:
                qi_height = float(qi_height)
            except:
                qi_height = 8.0
            try:
                sha_width = float(sha_width)
            except:
                sha_width = 4.0
            try:
                qi_offset_fen = float(qi_offset_fen)
            except:
                qi_offset_fen = 1.0
            try:
                extrude_length = float(extrude_length)
            except:
                extrude_length = 46.0

            tool_bp = rg.Point3d(0.0, 0.0, 0.0)

            X = rg.Vector3d(1, 0, 0)
            Y = rg.Vector3d(0, 0, 1)
            origin = rg.Point3d(0, 0, 0)
            ref_plane = rg.Plane(origin, X, Y)

            extrude_positive_raw = A.get("FT_QiAo__extrude_positive", False)
            extrude_positive = bool(extrude_positive_raw)

            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset_fen,
                extrude_length,
                tool_bp,
                ref_plane,
                extrude_positive
            )

            self.QiAo_ToolBrep  = ToolBrep
            self.QiAo_BasePoint = BasePoint
            self.QiAo_BaseLine  = BaseLine
            self.QiAo_SecPlane  = SecPlane
            self.QiAo_FacePlane = FacePlane

        except Exception as e:
            self.Log.append("[STEP3:QiAo] build_qiao_tool 出错: {}".format(e))
            self.QiAo_ToolBrep = None

        # ----------------- 3.3 FT_AlignToolToTimber::1 -----------------
        try:
            if self.QiAo_ToolBrep is None or self.QiAo_BlockFacePlane is None:
                self.QiAo_DebugInfo.append("欹䫜刀具或 BlockFacePlane 为空，跳过对位。")
                self.Log.append("[STEP3:Align] 数据为空，未进行对位。")
                return

            ToolGeo        = self.QiAo_ToolBrep
            ToolBasePlane  = self.QiAo_FacePlane
            BlockFacePlane = self.QiAo_BlockFacePlane

            ToolRotDeg    = A.get("FT_AlignToolToTimber_1__ToolRotDeg",    0.0)
            BlockRotDeg   = A.get("FT_AlignToolToTimber_1__BlockRotDeg",   0.0)
            FlipX         = A.get("FT_AlignToolToTimber_1__FlipX",         0)
            FlipY         = A.get("FT_AlignToolToTimber_1__FlipY",         0)
            FlipZ         = A.get("FT_AlignToolToTimber_1__FlipZ",         0)
            ToolContactPt = A.get("FT_AlignToolToTimber_1__ToolContactPoint",  None)
            BlockTargetPt = A.get("FT_AlignToolToTimber_1__BlockTargetPoint",  None)
            Mode          = A.get("FT_AlignToolToTimber_1__Mode",          0)
            ToolDir       = A.get("FT_AlignToolToTimber_1__ToolDir",       0)
            TargetDir     = A.get("FT_AlignToolToTimber_1__TargetDir",     0)
            DepthOffset   = A.get("FT_AlignToolToTimber_1__DepthOffset",   0.0)
            MoveU         = A.get("FT_AlignToolToTimber_1__MoveU",         0.0)
            MoveV         = A.get("FT_AlignToolToTimber_1__MoveV",         0.0)

            AlignedTool  = []
            XForm        = []
            SrcPlaneList = []
            TgtPlaneList = []
            SrcPointList = []
            TgtPointList = []
            DebugInfo    = []

            tools_raw = ToolGeo
            if tools_raw is None:
                tools_raw = []
            tools_list_base = _to_list(tools_raw)

            if len(tools_list_base) == 0 or all(t is None for t in tools_list_base):
                DebugInfo.append("ToolGeo 输入为空，未进行对位。")
            else:
                tool_count = len(tools_list_base)

                if tool_count == 1:
                    lengths = [1]
                    lengths.append(_param_length(ToolBasePlane))
                    lengths.append(_param_length(ToolRotDeg))
                    lengths.append(_param_length(ToolContactPt))
                    lengths.append(_param_length(BlockFacePlane))
                    lengths.append(_param_length(BlockRotDeg))
                    lengths.append(_param_length(FlipX))
                    lengths.append(_param_length(FlipY))
                    lengths.append(_param_length(FlipZ))
                    lengths.append(_param_length(BlockTargetPt))
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

                tools_list   = _broadcast_param(tools_list_base, N, "ToolGeo")
                tool_planes  = _broadcast_param(ToolBasePlane,   N, "ToolBasePlane")
                tool_rots    = _broadcast_param(ToolRotDeg,      N, "ToolRotDeg")
                tool_pts     = _broadcast_param(ToolContactPt,   N, "ToolContactPoint")
                block_planes = _broadcast_param(BlockFacePlane,  N, "BlockFacePlane")
                block_rots   = _broadcast_param(BlockRotDeg,     N, "BlockRotDeg")
                flip_xs      = _broadcast_param(FlipX,           N, "FlipX")
                flip_ys      = _broadcast_param(FlipY,           N, "FlipY")
                flip_zs      = _broadcast_param(FlipZ,           N, "FlipZ")
                block_pts    = _broadcast_param(BlockTargetPt,   N, "BlockTargetPoint")
                modes        = _broadcast_param(Mode,            N, "Mode")
                tool_dirs    = _broadcast_param(ToolDir,         N, "ToolDir")
                target_dirs  = _broadcast_param(TargetDir,       N, "TargetDir")
                depth_offsets= _broadcast_param(DepthOffset,     N, "DepthOffset")
                move_us      = _broadcast_param(MoveU,           N, "MoveU")
                move_vs      = _broadcast_param(MoveV,           N, "MoveV")

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
                    SrcPlaneList.append(src_pl)
                    TgtPlaneList.append(tgt_pl)
                    SrcPointList.append(src_pt)
                    TgtPointList.append(tgt_pt)

                    if aligned is None:
                        DebugInfo.append("对位失败: {0}".format(dbg))
                    else:
                        DebugInfo.append(dbg)

            self.QiAo_AlignedTools = AlignedTool
            self.QiAo_XForms       = XForm
            self.QiAo_SourcePlanes = SrcPlaneList
            self.QiAo_TargetPlanes = TgtPlaneList
            self.QiAo_SourcePoints = SrcPointList
            self.QiAo_TargetPoints = TgtPointList
            self.QiAo_DebugInfo    = DebugInfo

            for d in DebugInfo:
                self.Log.append("[STEP3:Align] " + str(d))

        except Exception as e:
            self.Log.append("[STEP3:Align] 对位过程异常: {}".format(e))


    # ------------------------------------------------------------------
    # STEP 4：耳平 —— BlockCutter + PFL2 + PFL3 + Align::2 + Cut
    # ------------------------------------------------------------------
    def step4_block_cutter(self):

        A = self.AllDict
        self.Log.append("===== STEP4: FT_BlockCutter + PlaneFromLists::2 + PlaneFromLists::3 + Align::2 + Cut =====")

        # ----------------- 4.1 FT_BlockCutter -----------------
        bc_L_raw = A.get("FT_BlockCutter__length_fen", 32.0)
        bc_W_raw = A.get("FT_BlockCutter__width_fen",  32.0)
        bc_H_raw = A.get("FT_BlockCutter__height_fen", 20.0)

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
            rg.Vector3d.ZAxis   # XZ Plane
        )

        # 清空旧数据
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
            try:
                Li = float(bc_L_list[i])
                Wi = float(bc_W_list[i])
                Hi = float(bc_H_list[i])
            except Exception as e:
                self.Log.append("[BlockCutter] 第 {} 组参数转 float 出错: {}".format(i, e))
                continue

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

        # ----------------- 4.2 PlaneFromLists::2（主木坯上） -----------------
        idx2_o_raw = A.get("PlaneFromLists_2__IndexOrigin", [])
        idx2_p_raw = A.get("PlaneFromLists_2__IndexPlane",  [])
        wrap2_raw  = A.get("PlaneFromLists_2__wrap",        True)

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

        # ----------------- 4.3 PlaneFromLists::3（BlockCutter 上） -----------------
        idx3_o_raw = A.get("PlaneFromLists_3__IndexOrigin", [])
        idx3_p_raw = A.get("PlaneFromLists_3__IndexPlane",  [])
        wrap3_raw  = A.get("PlaneFromLists_3__wrap",        True)

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
                            self.Log.append(
                                "[PFL3][branch {}][{}] build_plane 出错: {}".format(bi, i, e)
                            )

        # ----------------- 4.4 Align::2（BlockCutter 对位） -----------------
        BlockRotDeg2_raw = A.get("FT_AlignToolToTimber_2__BlockRotDeg", 0.0)
        FlipX2_raw       = A.get("FT_AlignToolToTimber_2__FlipX",       0)
        FlipY2_raw       = A.get("FT_AlignToolToTimber_2__FlipY",       0)
        FlipZ2_raw       = A.get("FT_AlignToolToTimber_2__FlipZ",       0)

        self.Log.append("[Align2] BlockRotDeg 原始值 = {!r}".format(BlockRotDeg2_raw))
        self.Log.append("[Align2] FlipX       原始值 = {!r}".format(FlipX2_raw))
        self.Log.append("[Align2] FlipY       原始值 = {!r}".format(FlipY2_raw))
        self.Log.append("[Align2] FlipZ       原始值 = {!r}".format(FlipZ2_raw))

        ToolRotDeg2_raw    = None
        ToolContactPt2_raw = None
        BlockTargetPt2_raw = None
        Mode2_raw          = None
        ToolDir2_raw       = None
        TargetDir2_raw     = None
        DepthOffset2_raw   = None
        MoveU2_raw         = None
        MoveV2_raw         = None

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

        for d2 in self.DebugInfo2:
            self.Log.append("[Align2] " + str(d2))

        # ----------------- 4.5 最终切削：QiAo + BlockCutter 一次性切主木坯 -----------------
        tools_all = []

        if self.QiAo_AlignedTools:
            tools_all.extend([t for t in self.QiAo_AlignedTools if t is not None])
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


    # ------------------------------------------------------------------
    # 主执行
    # ------------------------------------------------------------------
    def run(self):

        self.CutTimbers = []
        self.FailTimbers = []
        self.Log = []

        if self.Refresh:
            self.Log.append("[SYS] Refresh=True，强制重算")

        self.step1_read_db()
        self.step2_timber_block()
        self.step3_qiao_tool()
        self.step4_block_cutter()   # ★ 已启用耳平 + 切削

        return self


# ======================================================================
# GH 输出绑定区
# ======================================================================
if __name__ == "__main__":

    try:
        _db = DBPath
    except:
        _db = None

    try:
        _bp = base_point
    except:
        _bp = None

    try:
        _rf = Refresh
    except:
        _rf = False

    solver = QiXinDouSolver(DBPath=_db, base_point=_bp, Refresh=_rf, ghenv=ghenv)
    solver.run()

    # 核心对外输出
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log

    # 开发模式：按需在 GH 中添加同名输出端即可看到内部数据
    try:
        # Step1
        DBValue = solver.DBValue
        All     = solver.All
        AllDict = solver.AllDict
        DBLog   = solver.DBLog

        # Step2
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

        # Step3 - PlaneFromLists::1
        QiAo_BasePlane      = solver.QiAo_BasePlane
        QiAo_OriginPoint    = solver.QiAo_OriginPoint
        QiAo_BlockFacePlane = solver.QiAo_BlockFacePlane
        QiAo_PlaneLog       = solver.QiAo_PlaneLog

        # Step3 - FT_QiAo
        QiAo_ToolBrep  = solver.QiAo_ToolBrep
        QiAo_BasePoint = solver.QiAo_BasePoint
        QiAo_BaseLine  = solver.QiAo_BaseLine
        QiAo_SecPlane  = solver.QiAo_SecPlane
        QiAo_FacePlane = solver.QiAo_FacePlane

        # Step3 - AlignToolToTimber::1
        QiAo_AlignedTools = solver.QiAo_AlignedTools
        QiAo_XForms       = solver.QiAo_XForms
        QiAo_SourcePlanes = solver.QiAo_SourcePlanes
        QiAo_TargetPlanes = solver.QiAo_TargetPlanes
        QiAo_SourcePoints = solver.QiAo_SourcePoints
        QiAo_TargetPoints = solver.QiAo_TargetPoints
        QiAo_DebugInfo    = solver.QiAo_DebugInfo

        # Step4 - BlockCutter + PFL2 + PFL3 + Align::2
        BlockTimberBreps     = solver.BlockTimberBreps
        BlockFaceList        = solver.BlockFaceList
        BlockPointList       = solver.BlockPointList
        BlockEdgeList        = solver.BlockEdgeList
        BlockCenterPoint     = solver.BlockCenterPoint
        BlockCenterAxisLines = solver.BlockCenterAxisLines
        BlockEdgeMidPoints   = solver.BlockEdgeMidPoints
        BlockFacePlaneList   = solver.BlockFacePlaneList
        BlockCorner0Planes   = solver.BlockCorner0Planes
        BlockLocalAxesPlane  = solver.BlockLocalAxesPlane
        BlockAxisX           = solver.BlockAxisX
        BlockAxisY           = solver.BlockAxisY
        BlockAxisZ           = solver.BlockAxisZ
        BlockFaceDirTags     = solver.BlockFaceDirTags
        BlockEdgeDirTags     = solver.BlockEdgeDirTags
        BlockCorner0EdgeDirs = solver.BlockCorner0EdgeDirs

        BasePlane2   = solver.BasePlane2
        OriginPoint2 = solver.OriginPoint2
        ResultPlane2 = solver.ResultPlane2

        BasePlane3   = solver.BasePlane3
        OriginPoint3 = solver.OriginPoint3
        ResultPlane3 = solver.ResultPlane3

        AlignedTool2  = solver.AlignedTool2
        XForm2        = solver.XForm2
        SourcePlane2  = solver.SourcePlane2
        TargetPlane2  = solver.TargetPlane2
        SourcePoint2  = solver.SourcePoint2
        TargetPoint2  = solver.TargetPoint2
        DebugInfo2    = solver.DebugInfo2

    except:
        pass



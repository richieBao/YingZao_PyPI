# -*- coding: utf-8 -*-
"""PingPanDouSolver —— 平盤枓一体化求解器（阶段：Step 1 + Step 2）

目标：把构建 PingPanDou（平盤枓）的多组件 GH 流程，逐步合并为单一 GhPython 组件。

当前已实现：
    Step 1: DBJsonReader 读取 DG_Dou 表中 PingPanDou 的 params_json（ExportAll=True）
    Step 2: Timber_block_uniform —— 构造主木坯（build_timber_block_uniform）

GhPython 输入：
    DBPath     : str      - SQLite 数据库路径
    base_point : Point3d  - 主木坯定位点（优先于 DB；None 则原点）
    Refresh    : bool     - 刷新接口（触发重算即可；此处不做 sticky）

GhPython 输出（开发模式 · developer-friendly）：
    CutTimbers, FailTimbers, Log
    （并额外暴露 Step1/Step2 的中间变量，便于后续逐步扩展输出端）

说明：
    - 严格遵守“参数优先级”：组件输入端 > AllDict(数据库) > 默认值
    - 后续步骤用到数据库字段，一律从 All / AllDict 提取，不再二次读库
    - 参考平面采用 GH 约定：
        XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
        XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
        YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)

版本：2026.01.17
"""

import traceback
import Rhino.Geometry as rg

from yingzao.ancientArchi import DBJsonReader, build_timber_block_uniform

# StepX 依赖（QiAo / PlaneFromLists / GeoAligner / CutTimbersByTools）
from yingzao.ancientArchi import (
    build_qiao_tool,
    FTPlaneFromLists,
    GeoAligner_xfm,
    FT_CutTimbersByTools_GH_SolidDifference,
)

# 这些工具函数在 JiaoHuDouSolver 中也有使用；此处尽量复用库内实现
try:
    from yingzao.ancientArchi import parse_all_to_dict, all_get, to_scalar, make_reference_plane
except Exception:
    parse_all_to_dict = None
    all_get = None
    to_scalar = None
    make_reference_plane = None


# =========================================================
# 工具函数（本 Solver 最小必需）
# =========================================================

def _safe_point3d(p):
    """把 GH 输入端 base_point 收敛为 Point3d。"""
    if p is None:
        return rg.Point3d(0.0, 0.0, 0.0)
    if isinstance(p, rg.Point):
        return p.Location
    if isinstance(p, rg.Point3d):
        return p
    try:
        return rg.Point3d(p)
    except Exception:
        return rg.Point3d(0.0, 0.0, 0.0)


def _make_reference_plane_local(tag=None):
    """若 yingzao.ancientArchi.make_reference_plane 不可用，则用本地实现。"""
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


def _to_scalar_local(val, default=None):
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) else default
    return val


def flatten_any(x):
    """递归拍平 list/tuple/NET List，避免 System.Collections.Generic.List 套娃。

    - Rhino.GeometryBase / Plane / Point3d 等作为“原子”不展开。
    """
    out = []
    if x is None:
        return out

    # 原子类型
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]
    try:
        if isinstance(x, rg.GeometryBase):
            return [x]
    except Exception:
        pass

    # list / tuple
    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out

    # .NET IEnumerable（常见：System.Collections.Generic.List`1[System.Object]）
    try:
        it = iter(x)
    except Exception:
        return [x]

    # 如果能迭代，则逐项展开
    try:
        for v in it:
            out.extend(flatten_any(v))
        return out
    except Exception:
        return [x]


def _is_gh_tree(x):
    """粗略判断是否为 GH DataTree。"""
    if x is None:
        return False
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


def to_py_list(x):
    """把 GH 输入（item/list/DataTree）尽量转换为 Python list。

    - item -> [item]
    - list/tuple -> list
    - DataTree -> [branch0_list, branch1_list, ...]
    """
    if x is None:
        return []
    if _is_gh_tree(x):
        branches = []
        try:
            bc = int(x.BranchCount)
        except Exception:
            bc = 0
        for i in range(bc):
            try:
                b = x.Branch(i)
                branches.append(list(b) if b is not None else [])
            except Exception:
                branches.append([])
        return branches
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _broadcast_pair(a_list, b_list):
    """GH 风格广播：短列表循环对齐到长列表长度。"""
    la = len(a_list)
    lb = len(b_list)
    if la == 0 and lb == 0:
        return [], []
    if la == 0:
        a_list = [None]
        la = 1
    if lb == 0:
        b_list = [None]
        lb = 1
    n = max(la, lb)
    a2 = [a_list[i % la] for i in range(n)]
    b2 = [b_list[i % lb] for i in range(n)]
    return a2, b2


def _broadcast_multi(lists):
    """多列表广播到同一长度。"""
    lens = [len(x) for x in lists]
    n = max(lens) if lens else 0
    if n == 0:
        return [[] for _ in lists]
    out = []
    for arr in lists:
        if not arr:
            arr = [None]
        m = len(arr)
        out.append([arr[i % m] for i in range(n)])
    return out


# =========================================================
# Solver 主类
# =========================================================


class PingPanDouSolver(object):

    def __init__(self, DBPath, base_point, Refresh):
        # 输入端
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh

        # Step 1 输出
        self.All = None
        self.AllDict = None
        self.DBLog = []

        # Step 2 输出：主木坯（保持与 Timber_block_uniform 组件输出命名一致）
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

        # Step X：QiAo + PlaneFromLists + GeoAligner + CutTimbersByTools
        self.QiAo__ToolBrep = None
        self.QiAo__BasePoint = None
        self.QiAo__BaseLine = None
        self.QiAo__SecPlane = None
        self.QiAo__FacePlane = None
        self.QiAo__Log = []

        self.PlaneFromLists__BasePlane = None
        self.PlaneFromLists__OriginPoint = None
        self.PlaneFromLists__ResultPlane = None
        self.PlaneFromLists__Log = []

        self.GeoAligner__SourceOut = None
        self.GeoAligner__TargetOut = None
        self.GeoAligner__TransformOut = None
        self.GeoAligner__MovedGeo = None
        self.GeoAligner__Log = []

        self.CutTimbersByTools__CutTimbers = []
        self.CutTimbersByTools__FailTimbers = []
        self.CutTimbersByTools__Log = []

        # 最终结果（当前阶段仅占位：后续步骤会覆盖）
        self.CutTimbers = []
        self.FailTimbers = []

        # 全局日志
        self.Log = []

    # -----------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # -----------------------------------------------------
    def step1_read_db(self):
        self.Log.append("Step 1：读取数据库（PingPanDou）…")

        try:
            ghenv_obj = globals().get("ghenv", None)

            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="PingPanDou",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=ghenv_obj,
            )

            Value, All, LogLines = reader.run()
            self.DBLog = list(LogLines) if LogLines else []
            self.All = All

            if parse_all_to_dict is not None:
                self.AllDict = parse_all_to_dict(All)
            else:
                # 兜底：简单解析
                self.AllDict = {}
                if All:
                    for k, v in All:
                        if not isinstance(k, str) or "__" not in k:
                            continue
                        comp, port = k.split("__", 1)
                        self.AllDict.setdefault(comp, {})[port] = v

            self.Log.append("Step 1 完成：已读取 All 并转换为 AllDict。")

        except Exception as e:
            msg = "[Step 1 DB ERROR] {}".format(e)
            self.Log.append(msg)
            self.DBLog.append(msg)
            self.All = None
            self.AllDict = None
            traceback.print_exc()

    # -----------------------------------------------------
    # Step 2：原始木料构建（Timber_block_uniform）
    # -----------------------------------------------------
    def step2_timber_block(self):
        self.Log.append("Step 2：Timber_block_uniform · 原始木料构建…")

        if not self.AllDict:
            self.Log.append("[Step 2] AllDict 为空，跳过木料构建。")
            return

        # 2.1 参数读取：兼容 Timber_block_uniform / FT_timber_block_uniform 两种命名
        def _get(comp, port, default=None):
            if all_get is not None:
                v = all_get(self.AllDict, comp, port, None)
                if v is not None:
                    return v
            # 兜底：直接 dict
            return self.AllDict.get(comp, {}).get(port, default)

        length_raw = _get("Timber_block_uniform", "length_fen", None)
        width_raw = _get("Timber_block_uniform", "width_fen", None)
        height_raw = _get("Timber_block_uniform", "height_fen", None)
        plane_tag = _get("Timber_block_uniform", "reference_plane", None)

        if length_raw is None:
            length_raw = _get("FT_timber_block_uniform", "length_fen", 32.0)
        if width_raw is None:
            width_raw = _get("FT_timber_block_uniform", "width_fen", 32.0)
        if height_raw is None:
            height_raw = _get("FT_timber_block_uniform", "height_fen", 20.0)
        if plane_tag is None:
            plane_tag = _get("FT_timber_block_uniform", "reference_plane", None)

        # 2.2 标量化（length/width/height 应为标量语义）
        try:
            length_fen = float((to_scalar or _to_scalar_local)(length_raw, 32.0))
        except Exception:
            length_fen = 32.0
            self.Log.append("[Step 2] length_fen 解析失败，使用默认 32.0。")

        try:
            width_fen = float((to_scalar or _to_scalar_local)(width_raw, 32.0))
        except Exception:
            width_fen = 32.0
            self.Log.append("[Step 2] width_fen 解析失败，使用默认 32.0。")

        try:
            height_fen = float((to_scalar or _to_scalar_local)(height_raw, 20.0))
        except Exception:
            height_fen = 20.0
            self.Log.append("[Step 2] height_fen 解析失败，使用默认 20.0。")

        # 2.3 base_point：优先组件输入端，其次原点
        bp = _safe_point3d(self.base_point)

        # 2.4 参考平面：默认 GH XZ Plane（按你给定的 GH 方向约定）
        if make_reference_plane is not None:
            ref_plane = make_reference_plane(plane_tag)
        else:
            ref_plane = _make_reference_plane_local(plane_tag)

        # 2.5 调用 build_timber_block_uniform
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
                ref_plane,
            )

            # 保持与原组件一致的输出字段
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

            for l in (log_lines or []):
                self.Log.append("[TIMBER] " + str(l))

            self.Log.append("Step 2 完成：木料已成功构建。")

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
            self.TimberLog = ["错误: {}".format(e)]

            self.Log.append("[Step 2 ERROR] {}".format(e))
            traceback.print_exc()

    # -----------------------------------------------------
    # Step X：QiAo → PlaneFromLists → GeoAligner → CutTimbersByTools
    # -----------------------------------------------------
    def stepX_qiao_plane_align_cut(self):
        """实现：起翘刀具生成 → 抽取木坯定位平面 → 对齐刀具 → 切割木坯。"""

        self.Log.append("Step X：QiAo + PlaneFromLists + GeoAligner + CutTimbersByTools …")

        if self.TimberBrep is None:
            self.Log.append("[Step X] TimberBrep 为空，无法切割。")
            return

        # ---------- 统一取值：组件输入端 > AllDict > 默认值 ----------
        def _get(comp, port, default=None):
            if all_get is not None:
                try:
                    v = all_get(self.AllDict, comp, port, None)
                except Exception:
                    v = None
                if v is not None:
                    return v
            return self.AllDict.get(comp, {}).get(port, default) if isinstance(self.AllDict, dict) else default

        # =========================================================
        # 1) QiAo
        # =========================================================
        try:
            qi_height = _get("QiAo", "qi_height", None)
            sha_width = _get("QiAo", "sha_width", None)
            qi_offset_fen = _get("QiAo", "qi_offset_fen", None)
            extrude_length = _get("QiAo", "extrude_length", None)
            extrude_positive = _get("QiAo", "extrude_positive", None)
            plane_tag = _get("QiAo", "reference_plane", None)

            # defaults（对齐原组件）
            if qi_height is None:
                qi_height = 8.0
            if sha_width is None:
                sha_width = 4.0
            if qi_offset_fen is None:
                qi_offset_fen = 1.0
            if extrude_length is None:
                extrude_length = 46.0
            if extrude_positive is None:
                extrude_positive = True

            bp = _safe_point3d(self.base_point)
            if make_reference_plane is not None:
                reference_plane = make_reference_plane(plane_tag) if plane_tag is not None else make_reference_plane("XZ")
            else:
                reference_plane = _make_reference_plane_local(plane_tag if plane_tag is not None else "XZ")

            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                float((to_scalar or _to_scalar_local)(qi_height, 8.0)),
                float((to_scalar or _to_scalar_local)(sha_width, 4.0)),
                float((to_scalar or _to_scalar_local)(qi_offset_fen, 1.0)),
                float((to_scalar or _to_scalar_local)(extrude_length, 46.0)),
                bp,
                reference_plane,
                bool(extrude_positive),
            )

            self.QiAo__ToolBrep = ToolBrep
            self.QiAo__BasePoint = BasePoint
            self.QiAo__BaseLine = BaseLine
            self.QiAo__SecPlane = SecPlane
            self.QiAo__FacePlane = FacePlane
            self.QiAo__Log = [
                "qi_height={}".format(qi_height),
                "sha_width={}".format(sha_width),
                "qi_offset_fen={}".format(qi_offset_fen),
                "extrude_length={}".format(extrude_length),
                "extrude_positive={}".format(extrude_positive),
            ]

            self.Log.append("[Step X] QiAo OK")

        except Exception as e:
            self.QiAo__ToolBrep = None
            self.QiAo__FacePlane = None
            self.QiAo__Log = ["QiAo ERROR: {}".format(e)]
            self.Log.append("[Step X QiAo ERROR] {}".format(e))
            traceback.print_exc()
            return

        # =========================================================
        # 2) PlaneFromLists（从 Timber_block_uniform 提取 ResultPlane）
        # =========================================================
        try:
            OriginPoints = self.EdgeMidPoints
            BasePlanes = self.Corner0Planes

            IndexOrigin_in = _get("PlaneFromLists", "IndexOrigin", None)
            IndexPlane_in = _get("PlaneFromLists", "IndexPlane", None)
            Wrap_in = _get("PlaneFromLists", "Wrap", None)
            if Wrap_in is None:
                Wrap_in = True

            # 允许 tree/list/item
            idx_origin_any = to_py_list(IndexOrigin_in)
            idx_plane_any = to_py_list(IndexPlane_in)

            # 如果是 tree，则 idx_*_any 结构为 [branch0_list, ...]
            idx_origin_is_tree = _is_gh_tree(IndexOrigin_in)
            idx_plane_is_tree = _is_gh_tree(IndexPlane_in)

            builder = FTPlaneFromLists(wrap=bool(Wrap_in))

            # 分支对齐：若其中一个是单分支，广播到另一方分支数量
            if idx_origin_is_tree or idx_plane_is_tree:
                # 分支数
                b1 = len(idx_origin_any) if idx_origin_is_tree else 1
                b2 = len(idx_plane_any) if idx_plane_is_tree else 1
                bn = max(b1, b2)
                res_planes = []
                origin_pts_out = []
                base_planes_out = []
                logs = []
                for bi in range(bn):
                    o_list = idx_origin_any[bi % b1] if idx_origin_is_tree else idx_origin_any
                    p_list = idx_plane_any[bi % b2] if idx_plane_is_tree else idx_plane_any
                    o_list = list(o_list) if isinstance(o_list, (list, tuple)) else [o_list]
                    p_list = list(p_list) if isinstance(p_list, (list, tuple)) else [p_list]
                    o2, p2 = _broadcast_pair(o_list, p_list)
                    # 每对索引取一次
                    rp_branch = []
                    op_branch = []
                    bp_branch = []
                    for oi, pi in zip(o2, p2):
                        BasePlane, OriginPoint, ResultPlane, LogLine = builder.build_plane(
                            OriginPoints, BasePlanes, oi, pi
                        )
                        rp_branch.append(ResultPlane)
                        op_branch.append(OriginPoint)
                        bp_branch.append(BasePlane)
                        if LogLine is not None:
                            logs.append(str(LogLine))
                    res_planes.append(rp_branch)
                    origin_pts_out.append(op_branch)
                    base_planes_out.append(bp_branch)

                self.PlaneFromLists__ResultPlane = res_planes
                self.PlaneFromLists__OriginPoint = origin_pts_out
                self.PlaneFromLists__BasePlane = base_planes_out
                self.PlaneFromLists__Log = logs

            else:
                # 非 tree：索引列表广播
                idx_origin_list = idx_origin_any if isinstance(idx_origin_any, list) else [idx_origin_any]
                idx_plane_list = idx_plane_any if isinstance(idx_plane_any, list) else [idx_plane_any]
                if len(idx_origin_list) == 1 and isinstance(idx_origin_list[0], list):
                    idx_origin_list = idx_origin_list[0]
                if len(idx_plane_list) == 1 and isinstance(idx_plane_list[0], list):
                    idx_plane_list = idx_plane_list[0]
                o2, p2 = _broadcast_pair(idx_origin_list, idx_plane_list)

                BasePlanes_out = []
                OriginPoints_out = []
                ResultPlanes_out = []
                logs = []
                for oi, pi in zip(o2, p2):
                    BasePlane, OriginPoint, ResultPlane, LogLine = builder.build_plane(
                        OriginPoints, BasePlanes, oi, pi
                    )
                    BasePlanes_out.append(BasePlane)
                    OriginPoints_out.append(OriginPoint)
                    ResultPlanes_out.append(ResultPlane)
                    if LogLine is not None:
                        logs.append(str(LogLine))

                self.PlaneFromLists__BasePlane = BasePlanes_out
                self.PlaneFromLists__OriginPoint = OriginPoints_out
                self.PlaneFromLists__ResultPlane = ResultPlanes_out
                self.PlaneFromLists__Log = logs

            self.Log.append("[Step X] PlaneFromLists OK")

        except Exception as e:
            self.PlaneFromLists__ResultPlane = None
            self.PlaneFromLists__Log = ["PlaneFromLists ERROR: {}".format(e)]
            self.Log.append("[Step X PlaneFromLists ERROR] {}".format(e))
            traceback.print_exc()
            return

        # =========================================================
        # 3) GeoAligner（对齐刀具到目标平面）
        # =========================================================
        try:
            Geo = self.QiAo__ToolBrep
            SourcePlane = self.QiAo__FacePlane
            TargetPlane_in = self.PlaneFromLists__ResultPlane

            RotateDeg_in = _get("GeoAligner", "RotateDeg", 0)
            FlipX_in = _get("GeoAligner", "FlipX", False)
            FlipY_in = _get("GeoAligner", "FlipY", False)
            FlipZ_in = _get("GeoAligner", "FlipZ", False)
            MoveX_in = _get("GeoAligner", "MoveX", 0)
            MoveY_in = _get("GeoAligner", "MoveY", 0)
            MoveZ_in = _get("GeoAligner", "MoveZ", 0)

            # 目标平面（可能为 tree/list）展开
            tp_any = TargetPlane_in
            tp_list = to_py_list(tp_any)
            tp_is_tree = _is_gh_tree(tp_any)

            # 旋转/移动也可能为 tree/list
            r_any = to_py_list(RotateDeg_in)
            mx_any = to_py_list(MoveX_in)
            my_any = to_py_list(MoveY_in)
            mz_any = to_py_list(MoveZ_in)
            fx_any = to_py_list(FlipX_in)
            fy_any = to_py_list(FlipY_in)
            fz_any = to_py_list(FlipZ_in)

            moved_out = []
            xfm_out = []
            src_out = []
            tgt_out = []
            logs = []

            if tp_is_tree:
                # 分支循环
                bn = len(tp_list)
                # 广播：若某参数为 tree，则 branch 对齐，否则视为单支
                def _branch_get(any_list, is_tree, bi):
                    if is_tree:
                        return any_list[bi % len(any_list)]
                    return any_list

                r_is_tree = _is_gh_tree(RotateDeg_in)
                mx_is_tree = _is_gh_tree(MoveX_in)
                my_is_tree = _is_gh_tree(MoveY_in)
                mz_is_tree = _is_gh_tree(MoveZ_in)
                fx_is_tree = _is_gh_tree(FlipX_in)
                fy_is_tree = _is_gh_tree(FlipY_in)
                fz_is_tree = _is_gh_tree(FlipZ_in)

                for bi in range(bn):
                    tp_branch = tp_list[bi]
                    if not isinstance(tp_branch, (list, tuple)):
                        tp_branch = [tp_branch]

                    r_branch = _branch_get(r_any, r_is_tree, bi)
                    mx_branch = _branch_get(mx_any, mx_is_tree, bi)
                    my_branch = _branch_get(my_any, my_is_tree, bi)
                    mz_branch = _branch_get(mz_any, mz_is_tree, bi)
                    fx_branch = _branch_get(fx_any, fx_is_tree, bi)
                    fy_branch = _branch_get(fy_any, fy_is_tree, bi)
                    fz_branch = _branch_get(fz_any, fz_is_tree, bi)

                    # branch 内 item 广播
                    (tp2, r2, mx2, my2, mz2, fx2, fy2, fz2) = _broadcast_multi(
                        [
                            list(tp_branch),
                            list(r_branch) if isinstance(r_branch, (list, tuple)) else [r_branch],
                            list(mx_branch) if isinstance(mx_branch, (list, tuple)) else [mx_branch],
                            list(my_branch) if isinstance(my_branch, (list, tuple)) else [my_branch],
                            list(mz_branch) if isinstance(mz_branch, (list, tuple)) else [mz_branch],
                            list(fx_branch) if isinstance(fx_branch, (list, tuple)) else [fx_branch],
                            list(fy_branch) if isinstance(fy_branch, (list, tuple)) else [fy_branch],
                            list(fz_branch) if isinstance(fz_branch, (list, tuple)) else [fz_branch],
                        ]
                    )

                    moved_branch = []
                    xfm_branch = []
                    src_branch = []
                    tgt_branch = []

                    for _tp, _r, _mx, _my, _mz, _fx, _fy, _fz in zip(tp2, r2, mx2, my2, mz2, fx2, fy2, fz2):
                        so, to, xfm, mg = GeoAligner_xfm.align(
                            Geo,
                            SourcePlane,
                            _tp,
                            rotate_deg=_r,
                            flip_x=_fx,
                            flip_y=_fy,
                            flip_z=_fz,
                            move_x=_mx,
                            move_y=_my,
                            move_z=_mz,
                        )
                        moved_branch.append(mg)
                        xfm_branch.append(xfm)
                        src_branch.append(so)
                        tgt_branch.append(to)

                    moved_out.append(moved_branch)
                    xfm_out.append(xfm_branch)
                    src_out.append(src_branch)
                    tgt_out.append(tgt_branch)

            else:
                # 非 tree：item/list 广播到同一长度
                tp_flat = tp_list
                # to_py_list(item) 会变成 [item]，恰好广播
                (tp2, r2, mx2, my2, mz2, fx2, fy2, fz2) = _broadcast_multi(
                    [tp_flat, r_any, mx_any, my_any, mz_any, fx_any, fy_any, fz_any]
                )
                for _tp, _r, _mx, _my, _mz, _fx, _fy, _fz in zip(tp2, r2, mx2, my2, mz2, fx2, fy2, fz2):
                    so, to, xfm, mg = GeoAligner_xfm.align(
                        Geo,
                        SourcePlane,
                        _tp,
                        rotate_deg=_r,
                        flip_x=_fx,
                        flip_y=_fy,
                        flip_z=_fz,
                        move_x=_mx,
                        move_y=_my,
                        move_z=_mz,
                    )
                    src_out.append(so)
                    tgt_out.append(to)
                    xfm_out.append(xfm)
                    moved_out.append(mg)

            self.GeoAligner__SourceOut = src_out
            self.GeoAligner__TargetOut = tgt_out
            self.GeoAligner__TransformOut = xfm_out
            self.GeoAligner__MovedGeo = moved_out
            self.GeoAligner__Log = logs

            self.Log.append("[Step X] GeoAligner OK")

        except Exception as e:
            self.GeoAligner__MovedGeo = None
            self.GeoAligner__TransformOut = None
            self.GeoAligner__Log = ["GeoAligner ERROR: {}".format(e)]
            self.Log.append("[Step X GeoAligner ERROR] {}".format(e))
            traceback.print_exc()
            return

        # =========================================================
        # 4) CutTimbersByTools
        # =========================================================
        try:
            Timbers = self.TimberBrep
            Tools = flatten_any(self.GeoAligner__MovedGeo)
            KeepInside_in = _get("CutTimbersByTools", "KeepInside", None)
            if KeepInside_in is None:
                KeepInside_in = False
            keep_inside = bool((to_scalar or _to_scalar_local)(KeepInside_in, False))

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=False)
            CutTimbers, FailTimbers, LogLines = cutter.cut(
                timbers=Timbers,
                tools=Tools,
                keep_inside=keep_inside,
                debug=None,
            )

            self.CutTimbersByTools__CutTimbers = CutTimbers
            self.CutTimbersByTools__FailTimbers = FailTimbers
            self.CutTimbersByTools__Log = list(LogLines) if LogLines else []

            # 作为总输出
            self.CutTimbers = flatten_any(CutTimbers)
            self.FailTimbers = flatten_any(FailTimbers)
            self.Log.append("[Step X] CutTimbersByTools OK")

        except Exception as e:
            self.CutTimbersByTools__CutTimbers = []
            self.CutTimbersByTools__FailTimbers = []
            self.CutTimbersByTools__Log = ["CutTimbersByTools ERROR: {}".format(e)]
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[Step X CutTimbersByTools ERROR] {}".format(e))
            traceback.print_exc()

    # -----------------------------------------------------
    # 主控入口
    # -----------------------------------------------------
    def run(self):
        self.step1_read_db()
        if self.All is None or self.AllDict is None:
            self.Log.append("run: All / AllDict 为空，终止后续步骤。")
            return self

        self.step2_timber_block()

        # Step X：切割链
        self.stepX_qiao_plane_align_cut()

        # 输出端常见套娃，统一拍平（后续步骤会大量用到）
        self.CutTimbers = flatten_any(self.CutTimbers)
        self.FailTimbers = flatten_any(self.FailTimbers)

        return self


# ======================================================================
# GH Python 组件输出绑定区（developer-friendly）
# ======================================================================
if __name__ == "__main__":

    solver = PingPanDouSolver(DBPath, base_point, Refresh)
    solver.run()

    # ---- 最终输出（接口固定）----
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log

    # Log 也可能被嵌套 List 包裹
    Log = flatten_any(Log)

    # ---- Step 1 ----
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = solver.DBLog

    # ---- Step 2：Timber_block_uniform ----
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

    # ---- Step X：QiAo ----
    QiAo__ToolBrep   = solver.QiAo__ToolBrep
    QiAo__BasePoint  = solver.QiAo__BasePoint
    QiAo__BaseLine   = solver.QiAo__BaseLine
    QiAo__SecPlane   = solver.QiAo__SecPlane
    QiAo__FacePlane  = solver.QiAo__FacePlane
    QiAo__Log        = solver.QiAo__Log

    # ---- Step X：PlaneFromLists ----
    PlaneFromLists__BasePlane   = solver.PlaneFromLists__BasePlane
    PlaneFromLists__OriginPoint = solver.PlaneFromLists__OriginPoint
    PlaneFromLists__ResultPlane = solver.PlaneFromLists__ResultPlane
    PlaneFromLists__Log         = solver.PlaneFromLists__Log

    # ---- Step X：GeoAligner ----
    GeoAligner__SourceOut    = solver.GeoAligner__SourceOut
    GeoAligner__TargetOut    = solver.GeoAligner__TargetOut
    GeoAligner__TransformOut = solver.GeoAligner__TransformOut
    GeoAligner__MovedGeo     = solver.GeoAligner__MovedGeo
    GeoAligner__Log          = solver.GeoAligner__Log

    # ---- Step X：CutTimbersByTools ----
    CutTimbersByTools__CutTimbers  = solver.CutTimbersByTools__CutTimbers
    CutTimbersByTools__FailTimbers = solver.CutTimbersByTools__FailTimbers
    CutTimbersByTools__Log         = solver.CutTimbersByTools__Log

    # ---- 开发模式：暴露全部成员变量（可用 Panel 查看，后续需要时再拆成多个输出端）----
    DebugMembers = dict(sorted([(k, v) for k, v in solver.__dict__.items()], key=lambda kv: kv[0]))



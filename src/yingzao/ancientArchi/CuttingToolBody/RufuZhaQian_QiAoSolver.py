# -*- coding: utf-8 -*-
"""
RufuZhaQian_QiAoSover.py

乳栿劄牽_欹䫜刀（QiAo）·宋 · 单一 GhPython 组件（数据库驱动）
Step 1 ~ Step 6（完整）

✅ 本版改动（按你的要求）：
1) 输入端参数可“按需增加”并覆盖数据库：
   输入端优先 > 数据库(AllDict) > 默认值
   - 你只需要在 GH 里给 GhPython 组件“新增输入端口”，并用同名变量即可覆盖。
   - 不连线/为 None 时自动回落到数据库值。

2) sticky 缓存 key 加入 __version__，避免旧 solver 对象导致 AttributeError。
3) 输出绑定区对可选成员用 getattr 安全读取（防止开发阶段临时缺步骤就红）。

【最小输入（建议初始）】
    DBPath   : str
    base_point : Point3d
    Refresh  : bool

【可选“覆盖型”输入端（你需要时才加）示例】
    # Step2 timber 覆盖
    length_fen, width_fen, height_fen, timber_ref_plane_mode

    # Step3 QiAo 覆盖
    qi_height, sha_width, qi_offset_fen, extrude_length, extrude_positive, qi_ref_plane_mode

    # Step4 PlaneFromLists 覆盖
    IndexOrigin, IndexPlane

    # Step5 Align 覆盖
    ToolRotDeg

作者：richiebao [coding-x.tech]
"""

__author__  = "richiebao [coding-x.tech]"
__version__ = "2025.12.28-rfq-inputoverride-v1"

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    build_qiao_tool,
    FTPlaneFromLists,
    FTAligner,
    FT_CutTimberByTools,
)

# =========================================================
# 通用工具函数
# =========================================================

def all_to_dict(all_list):
    """All=[(k,v),...] -> dict"""
    d = {}
    if not all_list:
        return d
    try:
        for k, v in all_list:
            d[k] = v
    except:
        for item in all_list:
            if isinstance(item, tuple) and len(item) == 2:
                d[item[0]] = item[1]
    return d

def _flatten_list(x):
    """递归拍平 list/tuple"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        out = []
        for i in x:
            out.extend(_flatten_list(i))
        return out
    return [x]

def first_or_default(v, default=None):
    """若 v 为 list/tuple 取第一个；标量直接返回；None -> default"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        return v[0] if len(v) else default
    return v

def _as_point3d(pt, default=None):
    """统一转 Point3d"""
    if default is None:
        default = rg.Point3d(0.0, 0.0, 0.0)
    if pt is None:
        return default
    if isinstance(pt, rg.Point3d):
        return pt
    if isinstance(pt, rg.Point):
        return pt.Location
    if isinstance(pt, (list, tuple)) and len(pt) >= 3:
        try:
            return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
        except:
            return default
    try:
        return rg.Point3d(pt.X, pt.Y, pt.Z)
    except:
        return default

def _to_float(v, default=0.0):
    try:
        return float(first_or_default(v, default))
    except:
        return float(default)

def _to_bool(v, default=False):
    """兼容 bool / 0/1 / 'true'/'false' / None"""
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(int(v))
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f"):
        return False
    return bool(default)

def make_ref_plane(mode_str, origin=None):
    """
    根据字符串构造 GH 参考平面（严格按用户给定轴关系）：
    XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
    YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    origin = _as_point3d(origin)

    if mode_str is None:
        mode_str = "WorldXZ"
    m = str(mode_str).upper().strip()

    if m in ("WORLDXY", "XY", "XY_PLANE", "PLANE.XY"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WORLDYZ", "YZ", "YZ_PLANE", "PLANE.YZ"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)

def _getA(A, key, default=None):
    """从 AllDict 取值（key 不存在或 A 为空则 default）"""
    if not A:
        return default
    return A.get(key, default)

def _getA_any(A, keys, default=None):
    """按候选 key 列表依次尝试取值"""
    if not A:
        return default
    for k in keys:
        if k in A:
            v = A.get(k, None)
            if v is not None:
                return v
    return default

def _get_in_or_db(A, in_var_name, db_key, default=None, cast=None):
    """
    输入端优先 > 数据库(AllDict) > default

    - in_var_name: 组件输入端变量名（字符串），例如 "qi_height"
    - db_key:      AllDict 键名，例如 "FT_QiAo__qi_height"
    - cast:        可选类型转换函数，如 float/int/_to_bool/_as_point3d
    """
    # 1) 输入端优先（只有当 GH 里真的存在这个输入端变量且不为 None）
    if in_var_name in globals():
        v = globals().get(in_var_name, None)
        if v is not None:
            try:
                return cast(v) if cast else v
            except:
                return v

    # 2) 数据库
    v = _getA(A, db_key, None)
    if v is not None:
        try:
            return cast(v) if cast else v
        except:
            return v

    # 3) 默认
    try:
        return cast(default) if cast else default
    except:
        return default


# =========================================================
# Step5 广播工具（按你提供的 FT_AlignToolToTimber::1 代码）
# =========================================================

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

def _broadcast_param(val, n, name="param"):
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


# =========================================================
# Solver 主类 —— QiAoSolver
# =========================================================

class RufuZhaQian_QiAoSolver(object):

    def __init__(self, DBPath, base_point_in, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point_in = base_point_in
        self.Refresh = Refresh
        self.ghenv = ghenv

        self.Log = []

        # ---- Step1 ----
        self.Step1_Value = None
        self.Step1_All = []
        self.Step1_AllDict = {}
        self.Step1_DBLog = []

        # ---- Step2: timber ----
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
        self.Step2_Log       = []

        # ---- Step3: QiAo tool ----
        self.ToolBrep         = None
        self.QiAo_BasePoint   = None
        self.QiAo_BaseLine    = None
        self.QiAo_SecPlane    = None
        self.QiAo_FacePlane   = None
        self.Step3_Log        = []

        # ---- Step4: PlaneFromLists::1 ----
        self.PFL1_BasePlane   = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlane = None
        self.Step4_Log        = []

        # ---- Step5: AlignToolToTimber::1 ----
        self.AlignedTool  = []
        self.XForm        = []
        self.SourcePlane  = []
        self.TargetPlane  = []
        self.SourcePoint  = []
        self.TargetPoint  = []
        self.DebugInfo    = []
        self.Step5_Log    = []

        # ---- Step6: CutTimberByTools ----
        self.CutTimbers   = None
        self.FailTimbers  = []
        self.Step6_Log    = []


    # ------------------------------------------------------
    # Step1：读取数据库（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        CommonComponents / type_code='RufuZhaQian_QiAoTool' / params_json / ExportAll=True
        """
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="CommonComponents",
                key_field="type_code",
                key_value="RufuZhaQian_QiAoTool",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            v, all_list, db_log = reader.run()

            self.Step1_Value = v
            self.Step1_All = all_list if all_list else []
            self.Step1_DBLog = db_log if isinstance(db_log, list) else [str(db_log)]
            self.Step1_AllDict = all_to_dict(self.Step1_All)

            self.Log.append("[DB] 数据库读取完成：AllDict={} 项".format(len(self.Step1_AllDict)))
            for l in self.Step1_DBLog:
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step2：FT_timber_block_uniform（输入覆盖：length_fen/width_fen/height_fen/timber_ref_plane_mode）
    # ------------------------------------------------------
    def step2_timber_block(self):
        A = self.Step1_AllDict

        # base_point：组件输入端优先（你已经这样设计）
        base_point = _as_point3d(self.base_point_in, rg.Point3d(0.0, 0.0, 0.0))

        # 尺寸：输入端优先 > DB > 默认
        length_fen = _get_in_or_db(A, "length_fen", "FT_timber_block_uniform__length_fen", 32.0, float)
        width_fen  = _get_in_or_db(A, "width_fen",  "FT_timber_block_uniform__width_fen",  32.0, float)
        height_fen = _get_in_or_db(A, "height_fen", "FT_timber_block_uniform__height_fen", 20.0, float)

        # reference_plane 模式：输入端 timber_ref_plane_mode 可覆盖 DB
        ref_mode = _get_in_or_db(A, "timber_ref_plane_mode", "FT_timber_block_uniform__reference_plane", "WorldXZ", str)
        reference_plane = make_ref_plane(ref_mode, origin=base_point)

        self.Log.append("[TIMBER] reference_plane={}".format(ref_mode))
        self.Log.append("[TIMBER] base_point=({:.3f},{:.3f},{:.3f})".format(base_point.X, base_point.Y, base_point.Z))

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
            self.Step2_Log       = log_lines if isinstance(log_lines, list) else [str(log_lines)]

            self.Log.append("[TIMBER] OK: L/W/H = {}/{}/{}".format(length_fen, width_fen, height_fen))

        except Exception as e:
            self.Step2_Log = ["[TIMBER][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step2_timber_block 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step3：FT_QiAo（build_qiao_tool）
    # 输入覆盖：qi_height/sha_width/qi_offset_fen/extrude_length/extrude_positive/qi_ref_plane_mode
    # base_point：仍按组件输入端 base_point（输入优先），无输入则原点
    # ------------------------------------------------------
    def step3_build_qiao_tool(self):
        A = self.Step1_AllDict

        # 默认值（对齐你给的 FT_QiAo 脚本）
        qi_height = _get_in_or_db(A, "qi_height", "FT_QiAo__qi_height", 8.0, float)
        sha_width = _get_in_or_db(A, "sha_width", "FT_QiAo__sha_width", 4.0, float)
        qi_offset_fen = _get_in_or_db(A, "qi_offset_fen", "FT_QiAo__qi_offset_fen", 1.0, float)
        extrude_length = _get_in_or_db(A, "extrude_length", "FT_QiAo__extrude_length", 36.0 + 10.0, float)
        extrude_positive = _get_in_or_db(A, "extrude_positive", "FT_QiAo__extrude_positive", True, _to_bool)

        # base_point：输入端优先，否则原点
        base_point = _as_point3d(self.base_point_in, rg.Point3d(0.0, 0.0, 0.0))

        # reference_plane：允许 None；输入端 qi_ref_plane_mode 可覆盖 DB 的字符串
        rp = None
        if "qi_ref_plane_mode" in globals() and globals().get("qi_ref_plane_mode", None) is not None:
            rp = globals().get("qi_ref_plane_mode", None)
        else:
            rp = _getA(A, "FT_QiAo__reference_plane", None)

        if rp is None:
            reference_plane = None
        elif isinstance(rp, rg.Plane):
            reference_plane = rg.Plane(rp)
        else:
            reference_plane = make_ref_plane(rp, origin=base_point)

        self.Log.append("[QIAO] qi_height={} sha_width={} qi_offset_fen={} extrude_length={} extrude_positive={}".format(
            qi_height, sha_width, qi_offset_fen, extrude_length, extrude_positive
        ))

        try:
            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset_fen,
                extrude_length,
                base_point,
                reference_plane,
                extrude_positive
            )

            self.ToolBrep       = ToolBrep
            self.QiAo_BasePoint = BasePoint
            self.QiAo_BaseLine  = BaseLine
            self.QiAo_SecPlane  = SecPlane
            self.QiAo_FacePlane = FacePlane
            self.Step3_Log      = ["[QIAO] OK"]

        except Exception as e:
            self.ToolBrep = None
            self.QiAo_BasePoint = None
            self.QiAo_BaseLine = None
            self.QiAo_SecPlane = None
            self.QiAo_FacePlane = None
            self.Step3_Log = ["[QIAO][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step3_build_qiao_tool 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step4：PlaneFromLists::1（FTPlaneFromLists）
    # 输入覆盖：IndexOrigin/IndexPlane
    # OriginPoints=EdgeMidPoints; BasePlanes=Corner0Planes
    # ------------------------------------------------------
    def step4_plane_from_lists_1(self):
        A = self.Step1_AllDict

        OriginPoints = self.EdgeMidPoints
        BasePlanes   = self.Corner0Planes

        # 默认从 DB（兼容两种命名），但允许输入端 IndexOrigin/IndexPlane 覆盖
        db_idx_origin = _getA_any(A, ["PlaneFromLists_1__IndexOrigin", "PlaneFromLists::1__IndexOrigin"], 0)
        db_idx_plane  = _getA_any(A, ["PlaneFromLists_1__IndexPlane",  "PlaneFromLists::1__IndexPlane"], 0)

        IndexOrigin = _get_in_or_db(A, "IndexOrigin", "PlaneFromLists_1__IndexOrigin", db_idx_origin, int)
        IndexPlane  = _get_in_or_db(A, "IndexPlane",  "PlaneFromLists_1__IndexPlane",  db_idx_plane,  int)

        Wrap = True

        try:
            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                int(IndexOrigin),
                int(IndexPlane)
            )
            self.PFL1_BasePlane   = BasePlane
            self.PFL1_OriginPoint = OriginPoint
            self.PFL1_ResultPlane = ResultPlane
            self.Step4_Log = _flatten_list(Log)

            self.Log.append("[PFL1] OK: IndexOrigin={} IndexPlane={}".format(IndexOrigin, IndexPlane))

        except Exception as e:
            self.PFL1_BasePlane = None
            self.PFL1_OriginPoint = None
            self.PFL1_ResultPlane = None
            self.Step4_Log = ["[PFL1][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step4_plane_from_lists_1 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step5：FT_AlignToolToTimber::1（FTAligner + 广播机制）
    # 输入覆盖：ToolRotDeg（覆盖 DB 的 FT_AlignToolToTimber_1__ToolRotDeg）
    # 说明：此步骤你只给了 ToolRotDeg，其余参数按 None 默认。
    # ------------------------------------------------------
    def step5_align_tool_to_timber_1(self):
        A = self.Step1_AllDict

        ToolGeo         = self.ToolBrep
        ToolBasePlane   = self.QiAo_FacePlane
        BlockFacePlane  = self.PFL1_ResultPlane

        # 覆盖优先级：输入端 ToolRotDeg > DB > 默认 0
        BlockRotDeg = _get_in_or_db(A, "ToolRotDeg", "FT_AlignToolToTimber_1__ToolRotDeg", 0.0, float)

        # 其余参数默认（保持你给的脚本结构）
        ToolRotDeg       = None
        ToolContactPoint = None
        BlockTargetPoint = None
        Mode             = None
        ToolDir          = None
        TargetDir        = None
        DepthOffset      = None
        MoveU            = None
        MoveV            = None
        FlipX            = None
        FlipY            = None
        FlipZ            = None

        AlignedTool  = []
        XForm        = []
        SourcePlane  = []
        TargetPlane  = []
        SourcePoint  = []
        TargetPoint  = []
        DebugInfo    = []

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

            tools_list   = _broadcast_param(tools_list_base, N, "ToolGeo")
            tool_planes  = _broadcast_param(ToolBasePlane,   N, "ToolBasePlane")
            tool_rots    = _broadcast_param(ToolRotDeg,      N, "ToolRotDeg")
            tool_pts     = _broadcast_param(ToolContactPoint,N, "ToolContactPoint")
            block_planes = _broadcast_param(BlockFacePlane,  N, "BlockFacePlane")
            block_rots   = _broadcast_param(BlockRotDeg,     N, "BlockRotDeg")
            flip_xs      = _broadcast_param(FlipX,           N, "FlipX")
            flip_ys      = _broadcast_param(FlipY,           N, "FlipY")
            flip_zs      = _broadcast_param(FlipZ,           N, "FlipZ")
            block_pts    = _broadcast_param(BlockTargetPoint,N, "BlockTargetPoint")
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
                SourcePlane.append(src_pl)
                TargetPlane.append(tgt_pl)
                SourcePoint.append(src_pt)
                TargetPoint.append(tgt_pt)

                if aligned is None:
                    DebugInfo.append("对位失败: {0}".format(dbg))
                else:
                    DebugInfo.append(dbg)

        self.AlignedTool = AlignedTool
        self.XForm       = XForm
        self.SourcePlane = SourcePlane
        self.TargetPlane = TargetPlane
        self.SourcePoint = SourcePoint
        self.TargetPoint = TargetPoint
        self.DebugInfo   = DebugInfo
        self.Step5_Log   = _flatten_list(DebugInfo)

        self.Log.append("[ALIGN] OK: N={}".format(len(_to_list(self.AlignedTool))))

        return self


    # ------------------------------------------------------
    # Step6：FT_CutTimberByTools
    # Timbers=TimberBrep; Tools=AlignedTool
    # ------------------------------------------------------
    def step6_cut_timber_by_tools(self):
        Timbers = self.TimberBrep
        Tools   = self.AlignedTool

        try:
            cutter = FT_CutTimberByTools(Timbers, Tools)
            CutTimbers, FailTimbers, Log = cutter.run()

            self.CutTimbers  = CutTimbers
            self.FailTimbers = FailTimbers if FailTimbers is not None else []
            self.Step6_Log   = _flatten_list(Log)

            self.Log.append("[CUT] OK: FailTimbers={}".format(len(self.FailTimbers)))

        except Exception as e:
            self.CutTimbers  = None
            self.FailTimbers = []
            self.Step6_Log   = ["[CUT][ERROR] {}".format(e)]
            self.Log.append("[ERROR] step6_cut_timber_by_tools 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # 主入口
    # ------------------------------------------------------
    def run(self):
        self.step1_read_db()
        self.step2_timber_block()
        self.step3_build_qiao_tool()
        self.step4_plane_from_lists_1()
        self.step5_align_tool_to_timber_1()
        self.step6_cut_timber_by_tools()

        self.Log = _flatten_list(
            self.Log
            + self.Step2_Log
            + self.Step3_Log
            + self.Step4_Log
            + self.Step5_Log
            + self.Step6_Log
        )
        return self


# =========================================================
# GhPython 组件入口 + 缓存（sc.sticky）
# =========================================================

if __name__ == "__main__":

    # 1) 解析组件输入端
    try:
        _db = DBPath
    except:
        _db = None

    try:
        _bp = base_point
    except:
        _bp = None

    try:
        _rf = bool(Refresh)
    except:
        _rf = False

    # 2) DBPath 判定
    if _db is None or str(_db).strip() == "":
        CutTimbers  = None
        FailTimbers = []
        TimberBrep  = None
        Log         = ["[ERROR] DBPath 为空：请连接 Song-styleArchi.db 路径"]

    else:
        # 3) 缓存：key 加 __version__，避免旧 solver 对象缺成员导致 AttributeError
        # --- 构造输入签名：base_point（以及你想参与触发重算的其它输入） ---
        bp3 = _as_point3d(_bp, rg.Point3d(0, 0, 0))
        bp_sig = (round(bp3.X, 6), round(bp3.Y, 6), round(bp3.Z, 6))

        # 如果你还希望“某些可选覆盖输入”变化也触发重算，可以加在 sig 里：
        # 例：ToolRotDeg / IndexOrigin / IndexPlane（不加也行）
        _toolrot = globals().get("ToolRotDeg", None) if "ToolRotDeg" in globals() else None
        _iO = globals().get("IndexOrigin", None) if "IndexOrigin" in globals() else None
        _iP = globals().get("IndexPlane", None) if "IndexPlane" in globals() else None

        _input_sig = (bp_sig, _toolrot, _iO, _iP)

        # --- 缓存 key：加入输入签名 ---
        _key = "QiAoSolver::{}::{}::{}".format(str(ghenv.Component.InstanceGuid), __version__, str(_input_sig))
        _cached = sc.sticky.get(_key, None)

        if _rf or _cached is None:
            solver = RufuZhaQian_QiAoSolver(_db, _bp, _rf, ghenv)
            solver = solver.run()
            sc.sticky[_key] = solver
        else:
            solver = _cached

        # ==============================================================
        # GH Python 组件输出绑定区（主输出）—— 显式绑定（LingGongSolver 风格）
        # ==============================================================

        # --- 主输出 ---
        CutTimbers  = getattr(solver, "CutTimbers", None)
        FailTimbers = getattr(solver, "FailTimbers", [])
        Log         = getattr(solver, "Log", [])

        # TimberBrep（便于调试）
        TimberBrep  = getattr(solver, "TimberBrep", None)

        # ------------------------------
        # Step 1（DBJsonReader）
        # ------------------------------
        Step1_Value   = getattr(solver, "Step1_Value", None)
        Step1_All     = getattr(solver, "Step1_All", [])
        Step1_AllDict = getattr(solver, "Step1_AllDict", {})
        Step1_DBLog   = getattr(solver, "Step1_DBLog", [])

        # ------------------------------
        # Step 2（FT_timber_block_uniform）
        # ------------------------------
        FaceList        = _flatten_list(getattr(solver, "FaceList", []))
        PointList       = _flatten_list(getattr(solver, "PointList", []))
        EdgeList        = _flatten_list(getattr(solver, "EdgeList", []))
        CenterPoint     = getattr(solver, "CenterPoint", None)
        CenterAxisLines = _flatten_list(getattr(solver, "CenterAxisLines", []))
        EdgeMidPoints   = _flatten_list(getattr(solver, "EdgeMidPoints", []))
        FacePlaneList   = _flatten_list(getattr(solver, "FacePlaneList", []))
        Corner0Planes   = _flatten_list(getattr(solver, "Corner0Planes", []))
        LocalAxesPlane  = getattr(solver, "LocalAxesPlane", None)
        AxisX           = getattr(solver, "AxisX", None)
        AxisY           = getattr(solver, "AxisY", None)
        AxisZ           = getattr(solver, "AxisZ", None)
        FaceDirTags     = _flatten_list(getattr(solver, "FaceDirTags", []))
        EdgeDirTags     = _flatten_list(getattr(solver, "EdgeDirTags", []))
        Corner0EdgeDirs = _flatten_list(getattr(solver, "Corner0EdgeDirs", []))
        Step2_Log       = _flatten_list(getattr(solver, "Step2_Log", []))

        # ------------------------------
        # Step 3（FT_QiAo）
        # ------------------------------
        ToolBrep         = getattr(solver, "ToolBrep", None)
        QiAo_BasePoint   = getattr(solver, "QiAo_BasePoint", None)
        QiAo_BaseLine    = getattr(solver, "QiAo_BaseLine", None)
        QiAo_SecPlane    = getattr(solver, "QiAo_SecPlane", None)
        QiAo_FacePlane   = getattr(solver, "QiAo_FacePlane", None)
        Step3_Log        = _flatten_list(getattr(solver, "Step3_Log", []))

        # ------------------------------
        # Step 4（PlaneFromLists::1）
        # ------------------------------
        PFL1_BasePlane   = getattr(solver, "PFL1_BasePlane", None)
        PFL1_OriginPoint = getattr(solver, "PFL1_OriginPoint", None)
        PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
        Step4_Log        = _flatten_list(getattr(solver, "Step4_Log", []))

        # ------------------------------
        # Step 5（FT_AlignToolToTimber::1）
        # ------------------------------
        AlignedTool  = _flatten_list(getattr(solver, "AlignedTool", []))
        XForm        = _flatten_list(getattr(solver, "XForm", []))
        SourcePlane  = _flatten_list(getattr(solver, "SourcePlane", []))
        TargetPlane  = _flatten_list(getattr(solver, "TargetPlane", []))
        SourcePoint  = _flatten_list(getattr(solver, "SourcePoint", []))
        TargetPoint  = _flatten_list(getattr(solver, "TargetPoint", []))
        DebugInfo    = _flatten_list(getattr(solver, "DebugInfo", []))
        Step5_Log    = _flatten_list(getattr(solver, "Step5_Log", []))

        # ------------------------------
        # Step 6（FT_CutTimberByTools）
        # ------------------------------
        Step6_Log    = _flatten_list(getattr(solver, "Step6_Log", []))



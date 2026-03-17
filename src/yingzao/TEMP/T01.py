# -*- coding: utf-8 -*-
"""
ANG_LU_DOU 一体化组件（修复参考平面 + 对位方向 + 通用工具函数优化版）

关键修复：
1) 统一参考平面：添加 normalize_plane()，保证 Z 轴始终向上（Z-Up）
2) 修复 Step 3.3 对位时 GH 默认 XZPlane 导致的角度错误
3) 所有参考平面来源（主木坯、PlaneFromLists、QiAo、Align）均自动 normalize
4) 整理大量重复工具函数，与 LUDouSolver 完全对齐
"""

from __future__ import print_function, division
import json
import scriptcontext as sc
import System
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
# 0. Refresh 按钮：清空输出和 sticky 缓存
# ======================================================================

if 'Refresh' not in globals() or Refresh is None:
    Refresh = False

if Refresh:
    comp = ghenv.Component
    for p in comp.Params.Output:
        try:
            p.VolatileData.Clear()
        except:
            pass

    key = "ANG_LU_DOU_CACHE_{}".format(comp.InstanceGuid)
    if key in sc.sticky:
        del sc.sticky[key]


# ======================================================================
# 统一平面工具函数（新增 normalize_plane）
# ======================================================================

def gh_xy_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis)

def gh_xz_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)

def gh_yz_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.YAxis, rg.Vector3d.ZAxis)

def normalize_plane(pl):
    """
    GH 默认 XZPlane 的 ZAxis = (0,0,1)，但其 Y 轴向下，导致对位错误。
    此函数统一将所有平面转换为 Z-Up 坐标系，避免 FT_AlignToolToTimber 对位失败。
    """
    if pl is None:
        return gh_xz_plane()

    # 若 ZAxis 不朝上 → 重新构造
    if abs(pl.ZAxis.Z) < 0.9:
        newZ = rg.Vector3d(0,0,1)
        newX = rg.Vector3d(pl.XAxis.X, pl.XAxis.Y, 0)
        if newX.IsZero:
            newX = rg.Vector3d(1,0,0)
        newX.Unitize()
        newY = rg.Vector3d.CrossProduct(newZ, newX)
        return rg.Plane(pl.Origin, newX, newY)

    return pl


# ======================================================================
# 布尔/数值/点/平面解析函数（与 LUDouSolver 完全一致）
# ======================================================================

def _to_bool(val, default=True):
    if isinstance(val, (list, tuple)) and len(val) > 0:
        val = val[0]

    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true","yes","1"):  return True
        if s in ("false","no","0"): return False
    return default


def parse_scalar(d, key, default, log):
    if not isinstance(d, dict) or key not in d:
        log.append(u"参数 {} 缺失，使用默认值 {}。".format(key, default))
        return float(default)
    v = d[key]
    if isinstance(v, (list, tuple)) and v:
        v = v[0]
    try:
        f = float(v)
        log.append(u"参数 {} = {}".format(key, f))
        return f
    except:
        log.append(u"参数 {} 无法转换，使用默认值 {}".format(key, default))
        return float(default)


def parse_bool(d, key, default, log):
    if not isinstance(d, dict) or key not in d:
        log.append(u"布尔参数 {} 缺失，使用默认={}".format(key, default))
        return default
    v = d[key]
    b = _to_bool(v, default)
    log.append(u"布尔参数 {} = {}".format(key, b))
    return b


def parse_point(d, key, default_pt, log):
    if isinstance(d, dict) and key in d:
        raw = d[key]
        try:
            if isinstance(raw, (list,tuple)) and len(raw)>=3:
                x,y,z = float(raw[0]), float(raw[1]), float(raw[2])
                pt = rg.Point3d(x,y,z)
                log.append(u"Point {} = ({},{},{})".format(key,x,y,z))
                return pt
        except:
            log.append(u"Point {} 解析失败，使用默认".format(key))
    log.append(u"Point {} 缺失，使用默认".format(key))
    return default_pt


def parse_plane(d, key, log):
    """
    解析 WorldXY / WorldXZ / WorldYZ，解析后自动 normalize
    """
    if isinstance(d, dict) and key in d:
        v = d[key]
        if isinstance(v, str):
            k = v.lower()
            if k == "worldxy": p = gh_xy_plane()
            elif k == "worldxz": p = gh_xz_plane()
            elif k == "worldyz": p = gh_yz_plane()
            else:
                log.append(u"未知平面关键字 {} → 使用默认 XZ".format(v))
                p = gh_xz_plane()
            return normalize_plane(p)

    log.append(u"未指定平面 {} → 使用默认 XZ".format(key))
    return normalize_plane(gh_xz_plane())


# ======================================================================
# 1. 主类：AngLUDouSolver
# ======================================================================

class AngLUDouSolver(object):

    def __init__(self, db_path, base_point, ghenv):
        self.db_path = db_path
        self.base_point_input = base_point
        self.ghenv = ghenv

        # DB 结果
        self.Value    = None
        self.All      = None
        self.All_dict = None
        self.DBLog    = []

        # 主木坯
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

        # PlaneFromLists::1
        self.P1_BasePlane    = None
        self.P1_OriginPoint  = None
        self.P1_ResultPlane  = None
        self.Plane1Log       = []

        # FT_QiAo
        self.QiAo_ToolBrep   = None
        self.QiAo_BasePoint  = None
        self.QiAo_BaseLine   = None
        self.QiAo_SecPlane   = None
        self.QiAo_FacePlane  = None
        self.QiAoLog         = []

        # 对位结果
        self.Align1_AlignedTool = None
        self.Align1_XForm       = None
        self.Align1_SourcePlane = None
        self.Align1_TargetPlane = None
        self.Align1_SourcePoint = None
        self.Align1_TargetPoint = None
        self.AlignLog           = []

        # 切割结果
        self.CutTimbers  = []
        self.FailTimbers = []
        self.Log = []
    # ==================================================================
    # Step 1：数据库读取
    # ==================================================================
    def step_db(self):
        if not self.db_path:
            self.DBLog.append(u"错误：DBPath 为空。")
            return

        Table     = "DG_Dou"
        KeyField  = "type_code"
        KeyValue  = "ANG_LU_DOU"
        Field     = "params_json"
        JsonPath  = ""
        ExportAll = True

        try:
            reader = DBJsonReader(
                db_path   = self.db_path,
                table     = Table,
                key_field = KeyField,
                key_value = KeyValue,
                field     = Field,
                json_path = JsonPath,
                export_all= ExportAll,
                ghenv     = self.ghenv,
            )

            self.Value, self.All, self.DBLog = reader.run()

            if self.All is None:
                self.All_dict = None
                self.DBLog.append(u"All 为空。")
                return

            # 正常情况：[(key, value), ...]
            if isinstance(self.All, list):
                try:
                    self.All_dict = {
                        k: v for (k, v) in self.All
                        if isinstance(k, str)
                    }
                    self.DBLog.append(u"All 已转换为字典，共 {} 项".format(len(self.All_dict)))
                except:
                    self.All_dict = {"Raw": self.All}
                    self.DBLog.append(u"All 无法转换为 dict，已存 Raw")
            else:
                try:
                    self.All_dict = json.loads(str(self.All))
                    self.DBLog.append(u"All 为 JSON 字符串，已解析。")
                except:
                    self.All_dict = {"Raw": self.All}
                    self.DBLog.append(u"All 解析失败，存 Raw")

        except Exception as e:
            self.DBLog.append(u"DBJsonReader 异常 → {}".format(e))
            self.All_dict = None


    # ==================================================================
    # Step 2：主木坯（已修复 reference_plane = normalize）
    # ==================================================================
    def step_block(self):
        d   = self.All_dict
        log = self.TimberLog

        if d is None:
            log.append(u"All_dict 为空，不能读取主木坯参数。")
            return

        PREFIX = "FT_timber_block_uniform__"

        length_fen = parse_scalar(d, PREFIX + "length_fen", 32.0, log)
        width_fen  = parse_scalar(d, PREFIX + "width_fen",  32.0, log)
        height_fen = parse_scalar(d, PREFIX + "height_fen", 20.0, log)

        # base_point（组件输入优先）
        base_in = None
        if isinstance(self.base_point_input, rg.Point3d):
            base_in = self.base_point_input
        elif isinstance(self.base_point_input, rg.Point):
            base_in = self.base_point_input.Location

        base_final = parse_point(
            d, PREFIX + "base_point",
            base_in if base_in else rg.Point3d(0,0,0),
            log
        )

        # ============ ★ 修复点：reference_plane 统一 normalize ★ ============
        ref_plane = parse_plane(d, PREFIX + "reference_plane", log)
        ref_plane = normalize_plane(ref_plane)

        log.append(
            u"主木坯：L={}, W={}, H={}, base={}, plane={}".format(
                length_fen, width_fen, height_fen, base_final, ref_plane
            )
        )

        try:
            (
                timber_brep,
                faces, pts, edges,
                center_pt, center_axes,
                edge_midpts, face_planes,
                corner0_planes, local_axes_plane,
                ax, ay, az,
                face_tags, edge_tags,
                corner0_dirs,
                log_lines
            ) = build_timber_block_uniform(
                length_fen,
                width_fen,
                height_fen,
                base_final,
                ref_plane,
            )

            self.TimberBrep      = timber_brep
            self.FaceList        = faces
            self.PointList       = pts
            self.EdgeList        = edges
            self.CenterPoint     = center_pt
            self.CenterAxisLines = center_axes
            self.EdgeMidPoints   = edge_midpts
            self.FacePlaneList   = face_planes
            self.Corner0Planes   = corner0_planes
            self.LocalAxesPlane  = local_axes_plane
            self.AxisX           = ax
            self.AxisY           = ay
            self.AxisZ           = az
            self.FaceDirTags     = face_tags
            self.EdgeDirTags     = edge_tags
            self.Corner0EdgeDirs = corner0_dirs

            if isinstance(log_lines, list):
                log.extend(log_lines)

        except Exception as e:
            log.append(u"主木坯生成失败 → {}".format(e))
            self.TimberBrep = None


    # ==================================================================
    # Step 3.1：PlaneFromLists::1
    # ==================================================================
    def step_plane1(self):
        log = self.Plane1Log
        d   = self.All_dict

        if self.TimberBrep is None:
            log.append(u"主木坯不存在，跳过 PlaneFromLists::1。")
            return

        if d is None:
            log.append(u"All_dict 为空。")
            return

        if not self.EdgeMidPoints or not self.Corner0Planes:
            log.append(u"EdgeMidPoints / Corner0Planes 为空。")
            return

        PREFIX = "PlaneFromLists_1__"

        idx_origin = int(parse_scalar(d, PREFIX + "IndexOrigin", 0, log))
        idx_plane  = int(parse_scalar(d, PREFIX + "IndexPlane",  0, log))
        wrap       = parse_bool(d, PREFIX + "wrap", True, log)

        try:
            builder = FTPlaneFromLists(wrap=wrap)
            base_pl, org_pt, res_pl, logs = builder.build_plane(
                self.EdgeMidPoints,
                self.Corner0Planes,
                idx_origin,
                idx_plane
            )

            # =========== ★ 新增：normalize 对齐平面方向 ★ ===========
            self.P1_BasePlane   = normalize_plane(base_pl)
            self.P1_OriginPoint = org_pt
            self.P1_ResultPlane = normalize_plane(res_pl)

            if isinstance(logs, list):
                log.extend(logs)

        except Exception as e:
            log.append(u"PlaneFromLists::1 失败 → {}".format(e))
            self.P1_ResultPlane = None

    # ==================================================================
    # Step 3.2：FT_QiAo 欹䫜刀具（已修复 reference plane 统一 normalize）
    # ==================================================================
    def step_qi_ao(self):
        log = self.QiAoLog
        d   = self.All_dict

        if d is None:
            log.append(u"All_dict 为空，无法读取 FT_QiAo 参数。")
            return

        PREFIX = "FT_QiAo__"

        qi_height      = parse_scalar(d, PREFIX + "qi_height",      8.0,  log)
        sha_width      = parse_scalar(d, PREFIX + "sha_width",      4.0,  log)
        qi_offset_fen  = parse_scalar(d, PREFIX + "qi_offset_fen",  1.0,  log)
        extrude_length = parse_scalar(d, PREFIX + "extrude_length", 46.0, log)

        # QiAo 基准点通常为原点
        base_point = rg.Point3d(0,0,0)

        # =========== ★ 修复点：QiAo 的 reference_plane 也统一 normalize ★ ===========
        ref_plane_raw = gh_xz_plane()
        ref_plane     = normalize_plane(ref_plane_raw)

        extrude_positive = False   # 固定逻辑：向后 extrude

        log.append(
            u"FT_QiAo 参数：qi_height={}, sha_width={}, qi_offset_fen={}, extrude_length={}, plane={}"
            .format(qi_height, sha_width, qi_offset_fen, extrude_length, ref_plane)
        )

        try:
            tool_brep, bp, baseline, sec_pl, face_pl = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset_fen,
                extrude_length,
                base_point,
                ref_plane,
                extrude_positive
            )

            # =========== ★ normalize：FacePlane & SecPlane 对位起始平面必须稳定 ★ ===========
            self.QiAo_ToolBrep  = tool_brep
            self.QiAo_BasePoint = bp
            self.QiAo_BaseLine  = baseline
            self.QiAo_SecPlane  = normalize_plane(sec_pl)
            self.QiAo_FacePlane = normalize_plane(face_pl)

        except Exception as e:
            self.QiAo_ToolBrep  = None
            self.QiAo_FacePlane = None
            log.append(u"FT_QiAo 生成失败 → {}".format(e))


    # ==================================================================
    # Step 3.3：FT_AlignToolToTimber::1（核心修复）
    # ==================================================================
    def step_align(self):
        log = self.AlignLog
        d   = self.All_dict

        if self.QiAo_ToolBrep is None:
            log.append(u"警告：QiAo_ToolBrep 为空，无法对位。")
            return

        if self.QiAo_FacePlane is None:
            log.append(u"警告：QiAo_FacePlane 为空。")
            return

        if self.P1_ResultPlane is None:
            log.append(u"警告：PlaneFromLists::1 结果平面为空，无法对位。")
            return

        PREFIX = "FT_AlignToolToTimber_1__"

        block_rot_deg = parse_scalar(d, PREFIX + "BlockRotDeg", 0.0, log)
        flip_y        = parse_bool(d,   PREFIX + "FlipY",      False, log)

        ToolGeo          = self.QiAo_ToolBrep
        ToolBasePlane    = normalize_plane(self.QiAo_FacePlane)    # ★ 修复
        BlockFacePlane   = normalize_plane(self.P1_ResultPlane)    # ★ 修复

        ToolContactPoint = None
        BlockTargetPoint = None
        Mode             = "plane"
        ToolDir          = None
        TargetDir        = None
        DepthOffset      = 0.0
        MoveU            = 0.0
        MoveV            = 0.0
        FlipX            = False
        FlipZ            = False
        ToolRotDeg       = 0.0
        BlockRotDeg      = block_rot_deg

        try:
            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                ToolGeo,
                ToolBasePlane,
                ToolContactPoint,
                BlockFacePlane,
                BlockTargetPoint,
                Mode,
                ToolDir,
                TargetDir,
                DepthOffset,
                MoveU,
                MoveV,
                FlipX,
                flip_y,
                FlipZ,
                ToolRotDeg,
                BlockRotDeg
            )

            self.Align1_AlignedTool = aligned
            self.Align1_XForm       = xf
            self.Align1_SourcePlane = src_pl
            self.Align1_TargetPlane = tgt_pl
            self.Align1_SourcePoint = src_pt
            self.Align1_TargetPoint = tgt_pt

            if aligned is None:
                log.append(u"对位失败：{}".format(dbg))
            else:
                log.append(u"对位成功。")
                if dbg:
                    log.append(str(dbg))

        except Exception as e:
            log.append(u"FT_AlignToolToTimber::1 异常 → {}".format(e))
            self.Align1_AlignedTool = None


    # ==================================================================
    # Step 3.4：FT_CutTimberByTools
    # ==================================================================
    def step_cut(self):
        if self.TimberBrep is None:
            self.Log.append(u"主木坯不存在，不能切割。")
            return

        if self.Align1_AlignedTool is None:
            self.Log.append(u"对位后的欹䫜刀具为空，不能切割。")
            return

        try:
            cutter = FT_CutTimberByTools(
                self.TimberBrep,
                self.Align1_AlignedTool
            )

            cut_timbers, fail_timbers, logs = cutter.run()
            self.CutTimbers  = cut_timbers or []
            self.FailTimbers = fail_timbers or []

            if logs:
                if isinstance(logs, list):
                    self.Log.extend(logs)
                else:
                    self.Log.append(str(logs))

        except Exception as e:
            self.FailTimbers = [self.TimberBrep]
            self.Log.append(u"切割失败 → {}".format(e))


    # ==================================================================
    # 汇总日志
    # ==================================================================
    def build_log(self):
        self.Log = (
            self.DBLog +
            [u"------ 主木坯 ------"] + self.TimberLog +
            [u"------ PlaneFromLists::1 ------"] + self.Plane1Log +
            [u"------ FT_QiAo ------"] + self.QiAoLog +
            [u"------ 对位 FT_AlignToolToTimber::1 ------"] + self.AlignLog +
            [u"------ 切割 ------"] + self.Log
        )


    # ==================================================================
    # 执行整个流程
    # ==================================================================
    def run(self):
        self.step_db()
        if self.All_dict is None:
            return self

        self.step_block()
        if self.TimberBrep is None:
            return self

        self.step_plane1()
        self.step_qi_ao()
        self.step_align()
        self.step_cut()
        return self


# ======================================================================
# Grasshopper 输出绑定
# ======================================================================

if __name__ == "__main__":
    solver = AngLUDouSolver(DBPath, base_point, ghenv).run()
    solver.build_log()

    # DB
    Value    = solver.Value
    All      = solver.All
    All_dict = solver.All_dict

    # 主木坯
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
    TimberLogOut    = solver.TimberLog

    # PlaneFromLists::1
    BasePlane1   = solver.P1_BasePlane
    OriginPoint1 = solver.P1_OriginPoint
    ResultPlane1 = solver.P1_ResultPlane
    PlaneLog1    = solver.Plane1Log

    # FT_QiAo
    QiAo_ToolBrep  = solver.QiAo_ToolBrep
    QiAo_BasePoint = solver.QiAo_BasePoint
    QiAo_BaseLine  = solver.QiAo_BaseLine
    QiAo_SecPlane  = solver.QiAo_SecPlane
    QiAo_FacePlane = solver.QiAo_FacePlane
    QiAo_Log       = solver.QiAoLog

    # Align
    Align1_AlignedTool = solver.Align1_AlignedTool
    Align1_XForm       = solver.Align1_XForm
    Align1_SourcePlane = solver.Align1_SourcePlane
    Align1_TargetPlane = solver.Align1_TargetPlane
    Align1_SourcePoint = solver.Align1_SourcePoint
    Align1_TargetPoint = solver.Align1_TargetPoint
    Align1_Log         = solver.AlignLog

    # Cutting
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log



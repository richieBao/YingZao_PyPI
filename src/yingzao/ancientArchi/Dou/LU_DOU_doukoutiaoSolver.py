# -*- coding: utf-8 -*-
"""
LU_DOU 一体化组件（类封装版）

从数据库读取櫨枓（LU_DOU）参数，并依次完成：
1) 主木坯 build_timber_block_uniform
2) PlaneFromLists::1 / ::2 / ::3
3) FT_QiAo（欹䫜刀具）
4) FT_AlignToolToTimber::1（欹䫜刀具对位到主木坯）
5) FT_BlockCutter（多块待切木料）
6) FT_AlignToolToTimber::2（待切木料对位到主木坯）
7) FT_CutTimberByTools（完成切割）

输入：
    DBPath      : SQLite 数据库路径
    base_point  : 主木坯基点（优先用此点生成主木坯）
    Refresh     : bool，接 Button，True 时清空输出并清 sticky 缓存

所有中间结果都保留为类属性，便于后续自由选择输出端。
"""

from yingzao.ancientArchi import (
    DBJsonReader,
    build_timber_block_uniform,
    FTPlaneFromLists,
    build_qiao_tool,
    FTAligner,
)
from yingzao.ancientArchi import FT_CutTimberByTools

import Rhino.Geometry as rg
import json
import scriptcontext as sc


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

    key = "LU_DOU_CACHE_{}".format(comp.InstanceGuid)
    if key in sc.sticky:
        del sc.sticky[key]


# ======================================================================
# 一些通用工具函数（类会调用）
# ======================================================================

def gh_xy_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.YAxis)

def gh_xz_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)

def gh_yz_plane():
    return rg.Plane(rg.Point3d.Origin, rg.Vector3d.YAxis, rg.Vector3d.ZAxis)


def _to_bool(val, default=True):
    if isinstance(val, (list, tuple)) and len(val) > 0:
        val = val[0]

    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
    return default


def _broadcast(seq, n, default):
    seq = list(seq)
    if n <= 0:
        return []
    if not seq:
        return [default] * n
    if len(seq) >= n:
        return seq[:n]
    last = seq[-1]
    return seq + [last] * (n - len(seq))


# ======================================================================
# 1. 封装类：LUDouSolver
# ======================================================================

class LU_DOU_doukoutiaoSolver(object):
    """
    把櫨枓整套流水线封装为一个类：
        solver = LUDouSolver(DBPath, base_point, ghenv)
        solver.run()
    然后从 solver.xxx 取任意中间/最终结果作为输出端。
    """

    def __init__(self, db_path, base_point, ghenv):
        self.db_path = db_path
        self.base_point_input = base_point
        self.ghenv = ghenv

        # 数据库相关
        self.Value    = None
        self.All      = None
        self.All_dict = None
        self.DBLog    = []

        # 主木坯相关输出
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

        # PlaneFromLists::1 / ::2
        self.BasePlane1   = []
        self.OriginPoint1 = []
        self.ResultPlane1 = []
        self.PlaneLog1    = []

        self.BasePlane2   = []
        self.OriginPoint2 = []
        self.ResultPlane2 = []
        self.PlaneLog2    = []

        # FT_QiAo
        self.ToolBrep  = None
        self.BasePoint = None
        self.BaseLine  = None
        self.SecPlane  = None
        self.FacePlane = None
        self.QiLog     = []

        # FT_AlignToolToTimber::1
        self.AlignedTool = []
        self.XForm       = []
        self.SourcePlane = []
        self.TargetPlane = []
        self.SourcePoint = []
        self.TargetPoint = []
        self.DebugInfo   = []
        self.AlignLog1   = []

        # FT_BlockCutter
        self.BlockTimbers     = []
        self.BC_EdgeMidPoints = []
        self.BC_Corner0Planes = []
        self.BlockCutterLog   = []

        # PlaneFromLists::3
        self.BasePlane3   = []
        self.OriginPoint3 = []
        self.ResultPlane3 = []
        self.PlaneLog3    = []

        # FT_AlignToolToTimber::2
        self.AlignedTool2 = []
        self.XForm2       = []
        self.SourcePlane2 = []
        self.TargetPlane2 = []
        self.SourcePoint2 = []
        self.TargetPoint2 = []
        self.DebugInfo2   = []
        self.AlignLog2    = []

        # FT_CutTimberByTools
        self.CutTimbers  = []
        self.FailTimbers = []
        self.CutLog      = []

        # 最终总 Log
        self.Log = []

    # ------------------ 通用读参数函数（全部变成实例方法） ------------------

    def _get_scalar_from_dict(self, d, full_key, default, log_list):
        if not isinstance(d, dict):
            log_list.append(u"警告：All_dict 不是字典，参数 {} 使用默认值 {}。"
                            .format(full_key, default))
            return float(default)

        if full_key not in d:
            log_list.append(u"提示：All_dict 中未找到键 '{}'，参数使用默认值 {}。"
                            .format(full_key, default))
            return float(default)

        val = d[full_key]
        if isinstance(val, (list, tuple)) and len(val) > 0:
            val = val[0]

        try:
            f = float(val)
            log_list.append(u"参数 {} 来自 All_dict，值 = {}。".format(full_key, f))
            return f
        except Exception:
            log_list.append(
                u"警告：All_dict['{}'] = {!r} 无法转换为 float，使用默认值 {}。"
                .format(full_key, val, default)
            )
            return float(default)

    def _get_plane_from_dict(self, d, full_key, log_list):
        default_plane = gh_xz_plane()

        if isinstance(d, dict) and full_key in d:
            val = d[full_key]
            try:
                if isinstance(val, str):
                    key = val.lower()
                    if key == "worldxy":
                        plane = gh_xy_plane()
                    elif key == "worldxz":
                        plane = gh_xz_plane()
                    elif key == "worldyz":
                        plane = gh_yz_plane()
                    else:
                        log_list.append(
                            u"提示：All_dict['{}'] = '{}' 非标准关键字，使用默认 XZ 平面。"
                            .format(full_key, val)
                        )
                        return default_plane

                    log_list.append(
                        u"reference_plane 由 All_dict['{}'] 提供，值 = '{}'。"
                        .format(full_key, val)
                    )
                    return plane
            except Exception as e:
                log_list.append(
                    u"警告：All_dict['{}'] = {!r} 无法解析为 Plane，原因：{}，使用默认 XZ 平面。"
                    .format(full_key, val, e)
                )
                return default_plane

        log_list.append(u"reference_plane 未在 All_dict 中指定，使用默认 GH XZ 平面。")
        return default_plane

    def _get_point_from_dict(self, d, full_key, default_pt, log_list):
        if isinstance(d, dict) and full_key in d:
            val = d[full_key]
            try:
                if isinstance(val, (list, tuple)) and len(val) >= 3:
                    x, y, z = float(val[0]), float(val[1]), float(val[2])
                    pt = rg.Point3d(x, y, z)
                    log_list.append(
                        u"Point 来自 All_dict['{}']，值 = ({}, {}, {})。"
                        .format(full_key, x, y, z)
                    )
                    return pt
            except Exception as e:
                log_list.append(
                    u"警告：All_dict['{}'] = {!r} 无法解析为 Point3d，原因：{}，使用默认点。"
                    .format(full_key, val, e)
                )

        if default_pt is not None:
            log_list.append(u"Point 使用默认点 ({:.3f}, {:.3f}, {:.3f})。"
                            .format(default_pt.X, default_pt.Y, default_pt.Z))
            return default_pt

        log_list.append(u"Point 无可用值，使用原点 (0,0,0)。")
        return rg.Point3d(0.0, 0.0, 0.0)

    def _get_index_list_from_dict(self, d, key, log_list):
        idx_list = []
        if not isinstance(d, dict) or key not in d:
            log_list.append(u"提示：All_dict 中未找到键 '{}'，索引列表为空。".format(key))
            return idx_list

        raw = d[key]
        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        for i, v in enumerate(raw):
            try:
                idx = int(v)
                idx_list.append(idx)
            except Exception as e:
                log_list.append(
                    u"警告：{} 第 {} 个元素 {!r} 无法转为 int（{}），已忽略。"
                    .format(key, i, v, e)
                )

        log_list.append(u"参数 {} 来自 All_dict，索引列表 = {}。".format(key, idx_list))
        return idx_list

    def _get_number_list_from_dict(self, d, key, log_list, default=None):
        if not isinstance(d, dict) or key not in d:
            if default is None:
                log_list.append(u"提示：All_dict 中未找到键 '{}'。".format(key))
                return []
            else:
                log_list.append(u"提示：All_dict 中未找到键 '{}'，使用默认值 {}。".format(key, default))
                return [default]

        raw = d[key]
        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        result = []
        for i, v in enumerate(raw):
            try:
                result.append(float(v))
            except Exception as e:
                log_list.append(
                    u"警告：{} 第 {} 个元素 {!r} 无法转为 float（{}），已忽略。"
                    .format(key, i, v, e)
                )
        log_list.append(u"参数 {} → 数值列表 = {}。".format(key, result))
        return result

    def _get_bool_list_from_dict(self, d, key, log_list, default=None):
        if not isinstance(d, dict) or key not in d:
            if default is None:
                log_list.append(u"提示：All_dict 中未找到键 '{}'。".format(key))
                return []
            else:
                log_list.append(u"提示：All_dict 中未找到键 '{}'，使用默认值 {}。".format(key, default))
                return [default]

        raw = d[key]
        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        result = []
        for i, v in enumerate(raw):
            result.append(_to_bool(v, False))
        log_list.append(u"参数 {} → 布尔列表 = {}。".format(key, result))
        return result

    # ------------------ 步骤 1：数据库读取 ------------------

    def step_db(self):
        if self.db_path is None:
            self.DBLog.append(u"错误：DBPath 为空，请提供数据库路径。")
            return

        Table     = "DG_Dou"
        KeyField  = "type_code"
        KeyValue  = "LU_DOU_doukoutiao"
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
                self.DBLog.append(u"提示：数据库返回的 All 为空。")
            else:
                if isinstance(self.All, list):
                    try:
                        self.All_dict = {
                            item[0]: item[1]
                            for item in self.All
                            if isinstance(item, (list, tuple)) and len(item) == 2
                        }
                        self.DBLog.append(u"信息：All 已按 (key, value) 列表成功转换为 All_dict。")
                    except Exception as e:
                        self.DBLog.append(u"警告：All 转换为字典失败({})，尝试 JSON 解析。".format(e))
                        try:
                            self.All_dict = json.loads(str(self.All))
                            self.DBLog.append(u"信息：已通过 json.loads 成功解析 All。")
                        except Exception as e2:
                            self.All_dict = {"Raw": self.All}
                            self.DBLog.append(
                                u"警告：JSON 解析失败({})，将 All 原样存入 All_dict['Raw']。"
                                .format(e2)
                            )
                elif isinstance(self.All, str):
                    try:
                        self.All_dict = json.loads(self.All)
                        self.DBLog.append(u"信息：All 为 JSON 字符串，已成功解析为 All_dict。")
                    except Exception as e:
                        self.All_dict = {"Raw": self.All}
                        self.DBLog.append(
                            u"警告：All 字符串 JSON 解析失败({})，将原文存入 All_dict['Raw']。"
                            .format(e)
                        )
                else:
                    self.All_dict = {"Raw": self.All}
                    self.DBLog.append(
                        u"提示：All 为非常规类型({})，已存入 All_dict['Raw']。"
                        .format(type(self.All))
                    )
        except Exception as e:
            self.Value    = None
            self.All      = None
            self.All_dict = None
            self.DBLog    = [u"异常：DBJsonReader 执行失败 → {}".format(e)]

    # ------------------ 步骤 2：主木坯 ------------------

    def step_main_timber(self):
        PREFIX_BLOCK = "build_timber_block_uniform__"
        d = self.All_dict
        log = self.TimberLog

        # base_point 输入转 Point3d
        if self.base_point_input is None:
            base_point_in = None
        elif isinstance(self.base_point_input, rg.Point):
            base_point_in = self.base_point_input.Location
        elif isinstance(self.base_point_input, rg.Point3d):
            base_point_in = self.base_point_input
        else:
            base_point_in = None
            log.append(u"提示：base_point 输入类型为 {}，已忽略，由 DB/默认决定。"
                       .format(type(self.base_point_input)))

        def _get_base_point_for_block(dct, full_key, base_point_input, log_list):
            if isinstance(base_point_input, rg.Point3d):
                log_list.append(
                    u"base_point 采用组件输入值：({:.3f}, {:.3f}, {:.3f})。"
                    .format(base_point_input.X, base_point_input.Y, base_point_input.Z)
                )
                return base_point_input
            return self._get_point_from_dict(dct, full_key, rg.Point3d(0, 0, 0), log_list)

        length_fen = self._get_scalar_from_dict(d, PREFIX_BLOCK + "length_fen", 32.0, log)
        width_fen  = self._get_scalar_from_dict(d, PREFIX_BLOCK + "width_fen",  32.0, log)
        height_fen = self._get_scalar_from_dict(d, PREFIX_BLOCK + "height_fen", 20.0, log)

        base_point_final      = _get_base_point_for_block(
            d, PREFIX_BLOCK + "base_point", base_point_in, log
        )
        reference_plane_final = self._get_plane_from_dict(
            d, PREFIX_BLOCK + "reference_plane", log
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
                log_lines,
            ) = build_timber_block_uniform(
                length_fen,
                width_fen,
                height_fen,
                base_point_final,
                reference_plane_final,
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

            if isinstance(log_lines, list):
                log.extend(log_lines)
            else:
                log.append(u"注意：build_timber_block_uniform 未返回日志列表。")

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
            log.append(u"错误：build_timber_block_uniform 执行失败 → {}".format(e))

    # ------------------ 步骤 3：PlaneFromLists::1 / ::2 ------------------

    def step_plane12(self):
        def run_plane_from_lists(prefix, origin_points, base_planes, all_dict, log_list):
            out_base   = []
            out_origin = []
            out_result = []

            if not origin_points or not base_planes:
                log_list.append(u"提示：OriginPoints 或 BasePlanes 为空，跳过 {}。".format(prefix))
                return out_base, out_origin, out_result

            idx_origin_list = self._get_index_list_from_dict(all_dict, prefix + "IndexOrigin", log_list)
            idx_plane_list  = self._get_index_list_from_dict(all_dict, prefix + "IndexPlane",  log_list)

            count = min(len(idx_origin_list), len(idx_plane_list))
            if count == 0:
                log_list.append(u"提示：{} 索引列表长度为 0，未计算任何 ResultPlane。".format(prefix))
                return out_base, out_origin, out_result

            wrap_val = all_dict.get(prefix + "wrap", True) if isinstance(all_dict, dict) else True
            wrap = _to_bool(wrap_val, True)
            log_list.append(u"{} wrap 值 = {!r} → bool = {}。".format(prefix, wrap_val, wrap))

            builder = FTPlaneFromLists(wrap=wrap)

            for i in range(count):
                io = idx_origin_list[i]
                ip = idx_plane_list[i]
                log_list.append(u"{} 第 {} 组：IndexOrigin = {}，IndexPlane = {}。"
                                .format(prefix, i, io, ip))

                bp, op, rp, log_plane = builder.build_plane(
                    origin_points,
                    base_planes,
                    io,
                    ip
                )

                out_base.append(bp)
                out_origin.append(op)
                out_result.append(rp)

                if isinstance(log_plane, list):
                    log_list.extend(log_plane)
                elif log_plane is not None:
                    log_list.append(str(log_plane))

            return out_base, out_origin, out_result

        self.BasePlane1, self.OriginPoint1, self.ResultPlane1 = run_plane_from_lists(
            "FTPlaneFromLists_1__", self.EdgeMidPoints, self.Corner0Planes,
            self.All_dict, self.PlaneLog1
        )

        self.BasePlane2, self.OriginPoint2, self.ResultPlane2 = run_plane_from_lists(
            "FTPlaneFromLists_2__", self.EdgeMidPoints, self.Corner0Planes,
            self.All_dict, self.PlaneLog2
        )

    # ------------------ 步骤 4：FT_QiAo ------------------

    def step_qi_ao(self):
        PREFIX_QI = "FT_QiAo__"
        d   = self.All_dict
        log = self.QiLog

        qi_height      = self._get_scalar_from_dict(d, PREFIX_QI + "qi_height",       8.0, log)
        sha_width      = self._get_scalar_from_dict(d, PREFIX_QI + "sha_width",       4.0, log)
        qi_offset_fen  = self._get_scalar_from_dict(d, PREFIX_QI + "qi_offset_fen",   1.0, log)
        extrude_length = self._get_scalar_from_dict(d, PREFIX_QI + "extrude_length", 46.0, log)

        qi_base_point      = self._get_point_from_dict(d, PREFIX_QI + "base_point",
                                                       rg.Point3d(0, 0, 0), log)
        qi_reference_plane = self._get_plane_from_dict(d, PREFIX_QI + "reference_plane", log)

        if isinstance(d, dict) and PREFIX_QI + "extrude_positive" in d:
            extrude_positive_raw = d[PREFIX_QI + "extrude_positive"]
        else:
            extrude_positive_raw = True
        extrude_positive = _to_bool(extrude_positive_raw, True)
        log.append(u"extrude_positive 值 = {!r} → bool = {}。"
                   .format(extrude_positive_raw, extrude_positive))

        try:
            qi_brep, qi_bp, qi_baseline, qi_sec_plane, qi_face_plane = build_qiao_tool(
                qi_height,
                sha_width,
                qi_offset_fen,
                extrude_length,
                qi_base_point,
                qi_reference_plane,
                extrude_positive
            )

            self.ToolBrep  = qi_brep
            self.BasePoint = qi_bp
            self.BaseLine  = qi_baseline
            self.SecPlane  = qi_sec_plane
            self.FacePlane = qi_face_plane

        except Exception as e:
            self.ToolBrep  = None
            self.BasePoint = None
            self.BaseLine  = None
            self.SecPlane  = None
            self.FacePlane = None
            log.append(u"错误：build_qiao_tool 执行失败 → {}".format(e))

    # ------------------ 步骤 5：FT_AlignToolToTimber::1 ------------------

    def step_align1(self):
        PREFIX_ALIGN1 = "FT_AlignToolToTimber_1__"
        d   = self.All_dict
        log = self.AlignLog1

        if self.ToolBrep is None or not self.ResultPlane1:
            log.append(u"提示：ToolBrep 为 None 或 ResultPlane1 为空，未执行对位。")
            return

        try:
            block_rot_deg = self._get_scalar_from_dict(
                d, PREFIX_ALIGN1 + "BlockRotDeg", 0.0, log
            )

            flip_y_list = self._get_bool_list_from_dict(
                d, PREFIX_ALIGN1 + "FlipY", log, default=False
            )

            count = len(self.ResultPlane1)
            log.append(u"FT_AlignToolToTimber::1 将执行 {} 组对位。".format(count))

            for i in range(count):
                block_plane = self.ResultPlane1[i]
                flip_y = flip_y_list[i] if i < len(flip_y_list) else False

                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    self.ToolBrep,      # ToolGeo
                    self.FacePlane,     # ToolBasePlane
                    None,               # ToolContactPoint
                    block_plane,        # BlockFacePlane
                    None,               # BlockTargetPoint
                    "plane",            # Mode
                    None, None,         # ToolDir, TargetDir
                    0.0,                # DepthOffset
                    0.0, 0.0,           # MoveU, MoveV
                    False,              # FlipX
                    flip_y,             # FlipY
                    False,              # FlipZ
                    0.0,                # ToolRotDeg
                    block_rot_deg       # BlockRotDeg
                )

                self.AlignedTool.append(aligned)
                self.XForm.append(xf)
                self.SourcePlane.append(src_pl)
                self.TargetPlane.append(tgt_pl)
                self.SourcePoint.append(src_pt)
                self.TargetPoint.append(tgt_pt)

                if isinstance(dbg, list):
                    self.DebugInfo.extend(dbg)
                    log.append(u"[{}] 对位完成，调试信息条数：{}。".format(i, len(dbg)))
                else:
                    self.DebugInfo.append(str(dbg))
                    log.append(u"[{}] 对位完成，返回单条调试信息。".format(i))

        except Exception as e:
            log.append(u"错误：FT_AlignToolToTimber::1 执行失败 → {}".format(e))
            self.AlignedTool = []
            self.XForm       = []
            self.SourcePlane = []
            self.TargetPlane = []
            self.SourcePoint = []
            self.TargetPoint = []
            self.DebugInfo   = []

    # ------------------ 步骤 6：FT_BlockCutter ------------------

    def step_block_cutter(self):
        PREFIX_BC = "FT_BlockCutter__"
        d   = self.All_dict
        log = self.BlockCutterLog

        bc_len_list = self._get_number_list_from_dict(d, PREFIX_BC + "length_fen",
                                                      log, default=32.0)
        bc_wid_list = self._get_number_list_from_dict(d, PREFIX_BC + "width_fen",
                                                      log, default=32.0)
        bc_hei_list = self._get_number_list_from_dict(d, PREFIX_BC + "height_fen",
                                                      log, default=20.0)

        N_bc = max(len(bc_len_list), len(bc_wid_list), len(bc_hei_list))
        bc_len_list = _broadcast(bc_len_list, N_bc, 32.0)
        bc_wid_list = _broadcast(bc_wid_list, N_bc, 32.0)
        bc_hei_list = _broadcast(bc_hei_list, N_bc, 20.0)

        bc_base_point = self._get_point_from_dict(
            d, PREFIX_BC + "base_point", rg.Point3d(0, 0, 0), log
        )
        bc_ref_plane  = self._get_plane_from_dict(
            d, PREFIX_BC + "reference_plane", log
        )

        if N_bc <= 0:
            log.append(u"FT_BlockCutter：未检测到有效尺寸，未生成木料。")
            return

        log.append(u"FT_BlockCutter：将生成 {} 块木料。".format(N_bc))

        for i in range(N_bc):
            L = bc_len_list[i]
            W = bc_wid_list[i]
            H = bc_hei_list[i]
            log.append(u"第 {} 块：L={}，W={}，H={}。".format(i, L, W, H))
            try:
                (
                    b_brep,
                    _faces,
                    _points,
                    _edges,
                    _cpt,
                    _caxes,
                    _emids,
                    _fplanes,
                    _c0planes,
                    _loc_plane,
                    _ax, _ay, _az,
                    _ftags, _etags,
                    _c0dirs,
                    b_log
                ) = build_timber_block_uniform(
                    L, W, H,
                    bc_base_point,
                    bc_ref_plane,
                )
                self.BlockTimbers.append(b_brep)

                self.BC_EdgeMidPoints.append(list(_emids)    if _emids    else [])
                self.BC_Corner0Planes.append(list(_c0planes) if _c0planes else [])

                if isinstance(b_log, list):
                    log.extend(b_log)
            except Exception as e:
                log.append(u"警告：第 {} 块 BlockCutter 生成失败 → {}。".format(i, e))

    # ------------------ 步骤 7：PlaneFromLists::3 ------------------

    def step_plane3(self):
        d   = self.All_dict
        log = self.PlaneLog3

        def run_plane_from_lists_nested(prefix, nested_origins, nested_planes, all_dict, log_list):
            out_base   = []
            out_origin = []
            out_result = []

            if not nested_origins or not nested_planes:
                log_list.append(u"提示：{}：OriginPoints 或 BasePlanes 为空，跳过。".format(prefix))
                return out_base, out_origin, out_result

            idx_origin_list = self._get_index_list_from_dict(all_dict, prefix + "IndexOrigin", log_list)
            idx_plane_list  = self._get_index_list_from_dict(all_dict, prefix + "IndexPlane",  log_list)
            count_pair = min(len(idx_origin_list), len(idx_plane_list))

            if count_pair == 0:
                log_list.append(u"提示：{} 索引列表长度为 0，未计算任何 ResultPlane。".format(prefix))
                return out_base, out_origin, out_result

            wrap_val = all_dict.get(prefix + "wrap", True) if isinstance(all_dict, dict) else True
            wrap = _to_bool(wrap_val, True)
            log_list.append(u"{} wrap 值 = {!r} → bool = {}。".format(prefix, wrap_val, wrap))

            builder = FTPlaneFromLists(wrap=wrap)

            for bi, (origins, planes) in enumerate(zip(nested_origins, nested_planes)):
                if (not origins) or (not planes):
                    log_list.append(u"{}：第 {} 块木料 OriginPoints 或 BasePlanes 为空，跳过。"
                                    .format(prefix, bi))
                    continue

                for pi in range(count_pair):
                    io = idx_origin_list[pi]
                    ip = idx_plane_list[pi]
                    log_list.append(
                        u"{}：木料 {}，组 {} → IndexOrigin = {}，IndexPlane = {}。"
                        .format(prefix, bi, pi, io, ip)
                    )

                    bp, op, rp, log_plane = builder.build_plane(
                        origins,
                        planes,
                        io,
                        ip
                    )
                    out_base.append(bp)
                    out_origin.append(op)
                    out_result.append(rp)

                    if isinstance(log_plane, list):
                        log_list.extend(log_plane)
                    elif log_plane is not None:
                        log_list.append(str(log_plane))

            return out_base, out_origin, out_result

        self.BasePlane3, self.OriginPoint3, self.ResultPlane3 = run_plane_from_lists_nested(
            "FTPlaneFromLists_3__",
            self.BC_EdgeMidPoints,
            self.BC_Corner0Planes,
            d,
            log
        )

    # ------------------ 步骤 8：FT_AlignToolToTimber::2 ------------------

    def step_align2(self):
        PREFIX_ALIGN2 = "FT_AlignToolToTimber_2__"
        d   = self.All_dict
        log = self.AlignLog2

        tool_count  = len(self.BlockTimbers)
        base_count  = len(self.ResultPlane3)
        block_count = len(self.ResultPlane2)
        N_align2    = min(tool_count, base_count, block_count)

        if N_align2 <= 0:
            log.append(
                u"提示：FT_AlignToolToTimber::2 无法执行，对象数量：ToolGeo={}，ToolBasePlane={}，BlockFacePlane={}"
                .format(tool_count, base_count, block_count)
            )
            return

        rot_list  = self._get_number_list_from_dict(
            d, PREFIX_ALIGN2 + "BlockRotDeg", log, default=0.0
        )
        flipy_raw = self._get_bool_list_from_dict(
            d, PREFIX_ALIGN2 + "FlipY", log, default=False
        )

        rot_list  = _broadcast(rot_list,  N_align2, 0.0)
        flipy_raw = _broadcast(flipy_raw, N_align2, False)

        log.append(u"FT_AlignToolToTimber::2 将执行 {} 组对位。".format(N_align2))

        for i in range(N_align2):
            geo   = self.BlockTimbers[i]
            tbase = self.ResultPlane3[i]
            block = self.ResultPlane2[i]
            brot  = rot_list[i]
            fy    = flipy_raw[i]

            aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                geo,            # ToolGeo
                tbase,          # ToolBasePlane
                None,           # ToolContactPoint
                block,          # BlockFacePlane
                None,           # BlockTargetPoint
                "plane",        # Mode
                None, None,     # ToolDir, TargetDir
                0.0,            # DepthOffset
                0.0, 0.0,       # MoveU, MoveV
                False,          # FlipX
                fy,             # FlipY
                False,          # FlipZ
                0.0,            # ToolRotDeg
                brot            # BlockRotDeg
            )

            self.AlignedTool2.append(aligned)
            self.XForm2.append(xf)
            self.SourcePlane2.append(src_pl)
            self.TargetPlane2.append(tgt_pl)
            self.SourcePoint2.append(src_pt)
            self.TargetPoint2.append(tgt_pt)

            if isinstance(dbg, list):
                self.DebugInfo2.extend(dbg)
                log.append(u"[{}] 对位完成，调试信息条数：{}。".format(i, len(dbg)))
            else:
                self.DebugInfo2.append(str(dbg))
                log.append(u"[{}] 对位完成，返回单条调试信息。".format(i))

    # ------------------ 步骤 9：FT_CutTimberByTools ------------------

    def step_cut(self):
        self.CutTimbers   = []
        self.FailTimbers  = []
        log = self.CutLog

        Timbers = []
        if self.TimberBrep is not None:
            Timbers.append(self.TimberBrep)
        else:
            log.append(u"提示：主木坯 TimberBrep 为 None，无法进行切割。")

        Tools = []
        if self.AlignedTool:
            Tools.extend([t for t in self.AlignedTool if t is not None])
        if self.AlignedTool2:
            Tools.extend([t for t in self.AlignedTool2 if t is not None])

        if Timbers and Tools:
            try:
                cutter = FT_CutTimberByTools(Timbers, Tools)
                cut_timbers, fail_timbers, cut_log_inner = cutter.run()
                self.CutTimbers  = cut_timbers or []
                self.FailTimbers = fail_timbers or []

                if isinstance(cut_log_inner, list):
                    log.extend(cut_log_inner)
                elif cut_log_inner is not None:
                    log.append(str(cut_log_inner))

                log.append(
                    u"FT_CutTimberByTools：完成切割，成功 {} 件，失败 {} 件。"
                    .format(len(self.CutTimbers), len(self.FailTimbers))
                )
            except Exception as e:
                self.CutTimbers  = []
                self.FailTimbers = []
                log.append(u"错误：FT_CutTimberByTools 执行失败 → {}".format(e))
        else:
            log.append(
                u"提示：FT_CutTimberByTools 未执行，Timbers 数 = {}，Tools 数 = {}。"
                .format(len(Timbers), len(Tools))
            )

    # ------------------ 步骤 10：汇总 Log ------------------

    def build_log(self):
        self.Log = (self.DBLog or []) \
            + [u"---- Timber Block ----"]            + (self.TimberLog or []) \
            + [u"---- PlaneFromLists::1 ----"]       + (self.PlaneLog1 or []) \
            + [u"---- PlaneFromLists::2 ----"]       + (self.PlaneLog2 or []) \
            + [u"---- FT_QiAo ----"]                + (self.QiLog or []) \
            + [u"---- FT_AlignToolToTimber::1 ----"] + (self.AlignLog1 or []) \
            + [u"---- FT_BlockCutter ----"]          + (self.BlockCutterLog or []) \
            + [u"---- PlaneFromLists::3 ----"]       + (self.PlaneLog3 or []) \
            + [u"---- FT_AlignToolToTimber::2 ----"] + (self.AlignLog2 or []) \
            + [u"---- FT_CutTimberByTools ----"]     + (self.CutLog or [])

    # ------------------ 一键执行 ------------------

    def run(self):
        self.step_db()
        if self.All_dict is None:
            self.build_log()
            return self

        self.step_main_timber()
        self.step_plane12()
        self.step_qi_ao()
        self.step_align1()
        self.step_block_cutter()
        self.step_plane3()
        self.step_align2()
        self.step_cut()
        self.build_log()
        return self

if __name__=="__main__":
    # ======================================================================
    # 实际执行 & 绑定到 GH 输出
    # ======================================================================

    solver = LU_DOU_doukoutiaoSolver(DBPath, base_point, ghenv).run()

    # 1) DB 相关
    Value    = solver.Value
    All      = solver.All
    All_dict = solver.All_dict

    # 2) 主木坯
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

    # 3) PlaneFromLists::1 / ::2 / ::3
    BasePlane1   = solver.BasePlane1
    OriginPoint1 = solver.OriginPoint1
    ResultPlane1 = solver.ResultPlane1

    BasePlane2   = solver.BasePlane2
    OriginPoint2 = solver.OriginPoint2
    ResultPlane2 = solver.ResultPlane2

    BasePlane3   = solver.BasePlane3
    OriginPoint3 = solver.OriginPoint3
    ResultPlane3 = solver.ResultPlane3

    # 4) FT_QiAo
    ToolBrep  = solver.ToolBrep
    BasePoint = solver.BasePoint
    BaseLine  = solver.BaseLine
    SecPlane  = solver.SecPlane
    FacePlane = solver.FacePlane

    # 5) FT_AlignToolToTimber::1
    AlignedTool  = solver.AlignedTool
    XForm        = solver.XForm
    SourcePlane  = solver.SourcePlane
    TargetPlane  = solver.TargetPlane
    SourcePoint  = solver.SourcePoint
    TargetPoint  = solver.TargetPoint
    DebugInfo    = solver.DebugInfo

    # 6) FT_BlockCutter
    BlockTimbers = solver.BlockTimbers

    # 7) FT_AlignToolToTimber::2
    AlignedTool2  = solver.AlignedTool2
    XForm2        = solver.XForm2
    SourcePlane2  = solver.SourcePlane2
    TargetPlane2  = solver.TargetPlane2
    SourcePoint2  = solver.SourcePoint2
    TargetPoint2  = solver.TargetPoint2
    DebugInfo2    = solver.DebugInfo2

    # 8) 切割结果
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log



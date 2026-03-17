# -*- coding: utf-8 -*-
"""FT_AlignToolToTimber (v3.9 - multi tools, smart broadcasting)

规则总结：
    - ToolGeo 可以为 1 个，也可以为多个：
        * 若 ToolGeo 数量 = 1：
            - 取所有其它输入参数的“长度”最大值 n（若都为标量或 None，则 n = 1）；
            - 对该 ToolGeo 执行 n 次运算；
            - 其它参数：
                · 标量 → 广播到 n；
                · 列表：长度 < n 用“最后一个值”补齐；长度 > n 只取前 n 个。
        * 若 ToolGeo 数量 = m > 1：
            - 运算次数 n = m；
            - 其它参数：
                · 标量 → 广播到 m；
                · 列表：长度 < m 用“最后一个值”补齐；长度 > m 只取前 m 个。

    - 这样可以实现：
        * 只有 1 把刀具，FlipX/FlipY/FlipZ 给成列表 → 对同一刀具做多次不同姿态对位；
        * 有多把刀具时，只要给出 ≤ 数量的参数，就自动用“最后一个值”补齐到每把刀具。

其余对位逻辑与前版一致，这里不再赘述，只列输入/输出说明供 setup_io 使用。
（如果需要我可以再帮你单独做一个 setup_io 版本。）

---------------------------------------------------------------
【GhPython 输入参数（用于 setup_io 配置参考，只列名称）】
---------------------------------------------------------------
ToolGeo, ToolBasePlane, ToolRotDeg, ToolContactPoint,
BlockFacePlane, BlockRotDeg,
FlipX, FlipY, FlipZ,
BlockTargetPoint, Mode,
ToolDir, TargetDir,
DepthOffset, MoveU, MoveV

【GhPython 输出参数】
---------------------------------------------------------------
AlignedTool, XForm, SourcePlane, TargetPlane,
SourcePoint, TargetPoint, DebugInfo
"""

import Rhino
import Rhino.Geometry as rg
import System
import scriptcontext as sc
import traceback


class FTAligner(object):
    """对位与微调工具类（接受 Guid / GeometryBase，带日志）"""

    # -------------------- 基础“coerce”工具 --------------------

    @staticmethod
    def _log(msg):
        """统一输出到 Rhino 命令行。"""
        try:
            Rhino.RhinoApp.WriteLine("[FTAligner] " + msg)
        except:
            pass

    @staticmethod
    def _coerce_first(seq):
        """若是 list/tuple，取第一个；否则原样返回。"""
        if isinstance(seq, (list, tuple)):
            if len(seq) == 0:
                return None
            return seq[0]
        return seq

    @staticmethod
    def _coerce_geometry(geo):
        """
        尝试把输入转成 Rhino.Geometry.GeometryBase。
        支持 Guid / Brep / Surface / Extrusion / Mesh / Curve 等。
        """
        geo = FTAligner._coerce_first(geo)

        if geo is None:
            return None

        # Guid -> RhinoObject -> Geometry
        if isinstance(geo, System.Guid):
            rh_obj = sc.doc.Objects.Find(geo)
            if rh_obj is None:
                return None
            geo = rh_obj.Geometry

        # Surface / Extrusion -> Brep
        if isinstance(geo, rg.Surface):
            return rg.Brep.CreateFromSurface(geo)
        if isinstance(geo, rg.Extrusion):
            return geo.ToBrep()

        # 其它 GeometryBase 子类直接用
        if isinstance(geo, rg.GeometryBase):
            return geo

        return None

    @staticmethod
    def _coerce_plane(pl):
        """把输入转成 Plane（支持 Plane 或 [Plane]）。"""
        pl = FTAligner._coerce_first(pl)
        if isinstance(pl, rg.Plane):
            return rg.Plane(pl)
        return None

    @staticmethod
    def _coerce_point(pt, fallback_plane=None):
        """把输入转成 Point3d。为空则用平面原点作为回退。"""
        pt = FTAligner._coerce_first(pt)
        if isinstance(pt, rg.Point3d):
            return rg.Point3d(pt)
        if isinstance(pt, rg.Point):
            return rg.Point3d(pt.Location)
        if fallback_plane is not None and isinstance(fallback_plane, rg.Plane):
            return rg.Point3d(fallback_plane.Origin)
        return None

    @staticmethod
    def _vector_from_input(obj, fallback):
        """
        从输入对象中获得 Vector3d：
          - 若为 Vector3d，直接返回
          - 若为 Line，取其 Direction
          - 若为 None/其它，则用 fallback
        """
        obj = FTAligner._coerce_first(obj)

        if isinstance(obj, rg.Vector3d):
            v = rg.Vector3d(obj)
        elif isinstance(obj, rg.Line):
            v = obj.Direction
        else:
            v = None

        if v is None or not v.IsValid or v.IsZero:
            v = rg.Vector3d(fallback)

        if v.IsZero:
            return None

        v.Unitize()
        return v

    @staticmethod
    def _coerce_bool(val, default=False):
        """把 bool/int/float/str 统一转换成布尔值。"""
        val = FTAligner._coerce_first(val)

        if val is None:
            return default

        if isinstance(val, bool):
            return val

        if isinstance(val, (int, float)):
            return bool(val)

        if isinstance(val, System.String):
            val = str(val)

        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "1", "yes", "y", "on"):
                return True
            if s in ("false", "0", "no", "n", "off", ""):
                return False

        return default

    # -------------------- 基础变换方法 --------------------

    @staticmethod
    def _plane_to_plane_transform(source_plane, target_plane):
        """返回从 source_plane 到 target_plane 的 Transform。"""
        if source_plane is None or target_plane is None:
            return None
        if not source_plane.IsValid or not target_plane.IsValid:
            return None
        xf = rg.Transform.PlaneToPlane(source_plane, target_plane)
        if not xf.IsValid:
            return None
        return xf

    @staticmethod
    def _translation_transform(vec):
        """返回平移变换矩阵。"""
        return rg.Transform.Translation(vec)

    @staticmethod
    def _mirror_in_plane(plane):
        """关于给定平面的镜像变换。"""
        if plane is None or not plane.IsValid:
            return None
        return rg.Transform.Mirror(plane)

    @staticmethod
    def _flip_around_direction(origin, direction):
        """围绕给定方向旋转 180° 的变换。"""
        v = rg.Vector3d(direction)
        if not v.IsValid or v.IsZero:
            return None
        v.Unitize()
        angle = Rhino.RhinoMath.ToRadians(180.0)
        xf = rg.Transform.Rotation(angle, v, origin)
        if not xf.IsValid:
            return None
        return xf

    @staticmethod
    def _apply_transform(geo, xf):
        """对任意 GeometryBase 进行变换，返回变换后的新几何。"""
        if geo is None or xf is None:
            return None

        if hasattr(geo, "Duplicate"):
            dup = geo.Duplicate()
        elif hasattr(geo, "DuplicateGeometry"):
            dup = geo.DuplicateGeometry()
        else:
            dup = geo

        dup.Transform(xf)
        return dup

    # -------------------- 核心对位方法（单个刀具） --------------------

    @staticmethod
    def align(tool_geo,
              tool_plane,
              tool_contact_pt,
              block_plane,
              block_target_pt,
              mode_str,
              tool_dir_input,
              target_dir_input,
              depth_offset,
              move_u,
              move_v,
              flip_x,
              flip_y,
              flip_z,       # FlipZ 作为输入参数
              tool_rot_deg,
              block_rot_deg):
        """
        核心总方法：根据模式执行对位，再做微调（单刀具版本）。

        返回:
            aligned_geom, total_xform, src_plane, tgt_plane_out, src_pt, tgt_pt, debug_msg

        其中:
            tgt_plane_out 为 BlockFacePlane 经过 BlockRotDeg 与 FlipX/Y/Z 后的结果平面
        """

        try:
            # ---------- 1. 输入与预处理 ----------
            geom = FTAligner._coerce_geometry(tool_geo)
            if geom is None:
                tname = type(tool_geo).__name__ if tool_geo is not None else "None"
                debug = "ToolGeo 不是可识别的 Rhino.Geometry 类型（实际类型：{0}）。".format(tname)
                FTAligner._log(debug)
                return (None, None, None, None, None, None, debug)

            src_plane = FTAligner._coerce_plane(tool_plane)
            if src_plane is None:
                debug = "ToolBasePlane 为空或类型不对（请传 Plane）。"
                FTAligner._log(debug)
                return (None, None, None, None, None, None, debug)

            tgt_plane = FTAligner._coerce_plane(block_plane)
            if tgt_plane is None:
                debug = "BlockFacePlane 为空或类型不对（请传 Plane）。"
                FTAligner._log(debug)
                return (None, None, src_plane, None, None, None, debug)

            # ---------- 1.1 解析数值 ----------
            def _to_float(val, default=0.0):
                try:
                    return float(val) if val is not None else default
                except:
                    return default

            tool_rot = _to_float(tool_rot_deg, 0.0)
            block_rot = _to_float(block_rot_deg, 0.0)
            d_offset = _to_float(depth_offset, 0.0)
            u_offset = _to_float(move_u, 0.0)
            v_offset = _to_float(move_v, 0.0)
            flip_x = FTAligner._coerce_bool(flip_x, False)
            flip_y = FTAligner._coerce_bool(flip_y, False)
            flip_z = FTAligner._coerce_bool(flip_z, False)

            # ---------- 1.2 先对两个基准平面做旋转 ----------
            if abs(tool_rot) > 1e-9:
                ang = Rhino.RhinoMath.ToRadians(tool_rot)
                src_plane.Rotate(ang, src_plane.ZAxis)

            if abs(block_rot) > 1e-9:
                ang = Rhino.RhinoMath.ToRadians(block_rot)
                tgt_plane.Rotate(ang, tgt_plane.ZAxis)

            # ---------- 1.3 取接触点 / 目标点 ----------
            src_pt = FTAligner._coerce_point(tool_contact_pt, src_plane)
            base_target_pt = FTAligner._coerce_point(block_target_pt, tgt_plane)

            if base_target_pt is not None:
                tgt_plane.Origin = base_target_pt

            # ---------- 1.4 先对 BlockFacePlane 做 FlipX/Y/Z ----------
            if flip_x:
                FTAligner._log("Pre-align: mirror BlockFacePlane along local YZ-plane (flip local X).")
                plane_fx = rg.Plane(base_target_pt,
                                    tgt_plane.YAxis,
                                    tgt_plane.ZAxis)
                xf_fx = FTAligner._mirror_in_plane(plane_fx)
                if xf_fx is not None and xf_fx.IsValid:
                    tgt_plane.Transform(xf_fx)
                else:
                    FTAligner._log("FlipX mirror transform invalid, skipped.")

            if flip_y:
                FTAligner._log("Pre-align: mirror BlockFacePlane along local XZ-plane (flip local Y).")
                plane_fy = rg.Plane(base_target_pt,
                                    tgt_plane.XAxis,
                                    tgt_plane.ZAxis)
                xf_fy = FTAligner._mirror_in_plane(plane_fy)
                if xf_fy is not None and xf_fy.IsValid:
                    tgt_plane.Transform(xf_fy)
                else:
                    FTAligner._log("FlipY mirror transform invalid, skipped.")

            if flip_z:
                FTAligner._log("Pre-align: flip local Z axis (mirror across local XY plane).")
                y_flipped = rg.Vector3d(tgt_plane.YAxis)
                y_flipped *= -1.0
                x_keep = rg.Vector3d(tgt_plane.XAxis)
                tgt_plane = rg.Plane(tgt_plane.Origin, x_keep, y_flipped)

            tgt_plane_out = rg.Plane(tgt_plane)

            # ---------- 1.5 模式规范化 ----------
            if not mode_str:
                mode_str = "plane"
            if isinstance(mode_str, System.String):
                mode = mode_str.lower()
            else:
                mode = str(mode_str).lower()

            # ---------- 1.6 方向向量 ----------
            target_dir = FTAligner._vector_from_input(
                target_dir_input,
                tgt_plane.ZAxis
            )
            if target_dir is None:
                debug = "TargetDir 无效（为零向量），无法继续。"
                FTAligner._log(debug)
                return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

            tool_dir = FTAligner._vector_from_input(
                tool_dir_input,
                src_plane.ZAxis
            )

            FTAligner._log(
                "Mode={0}, ToolRot={1}, BlockRot={2}, DepthOffset={3}, MoveU={4}, MoveV={5}, "
                "FlipX={6}, FlipY={7}, FlipZ={8}".format(
                    mode, tool_rot, block_rot, d_offset, u_offset, v_offset,
                    flip_x, flip_y, flip_z)
            )

            total_xf = rg.Transform.Identity

            # ---------- 2. 模式一：plane ----------
            if mode == "plane":
                FTAligner._log("Using PLANE mode (PlaneToPlane, after rotations + flips).")
                xf_pp = FTAligner._plane_to_plane_transform(src_plane, tgt_plane)
                if xf_pp is None:
                    debug = "Plane 模式：PlaneToPlane 变换失败。"
                    FTAligner._log(debug)
                    return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

                total_xf = xf_pp
                main_dir = rg.Vector3d(tgt_plane.ZAxis)
                main_dir.Unitize()

            # ---------- 3. 模式二：point_dir ----------
            elif mode == "point_dir":
                FTAligner._log("Using POINT_DIR mode (point + direction, after rotations + flips).")

                if tool_contact_pt is None or block_target_pt is None:
                    debug = "PointDir 模式需要提供 ToolContactPoint 与 BlockTargetPoint。"
                    FTAligner._log(debug)
                    return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

                if tool_dir is None:
                    debug = "PointDir 模式下 ToolDir 无效（为零向量）。"
                    FTAligner._log(debug)
                    return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

                move_vec = base_target_pt - src_pt
                xf_move = FTAligner._translation_transform(move_vec)
                total_xf = xf_move

                xf_rot = rg.Transform.Rotation(tool_dir, target_dir, base_target_pt)
                if not xf_rot.IsValid:
                    debug = "PointDir 模式下方向旋转变换无效。"
                    FTAligner._log(debug)
                    return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

                total_xf *= xf_rot
                main_dir = rg.Vector3d(target_dir)
                main_dir.Unitize()

            else:
                debug = "未知模式: {0}，请使用 'plane' 或 'point_dir'。".format(mode)
                FTAligner._log(debug)
                return (None, None, src_plane, tgt_plane_out, src_pt, base_target_pt, debug)

            # ---------- 4. 微调：平移 ----------
            tgt_pt = rg.Point3d(base_target_pt)
            translation_vec = rg.Vector3d(0, 0, 0)

            if main_dir is not None and not main_dir.IsZero and abs(d_offset) > 1e-9:
                v_depth = rg.Vector3d(main_dir)
                v_depth *= d_offset
                tgt_pt += v_depth
                translation_vec += v_depth

            if abs(u_offset) > 1e-9:
                vx = rg.Vector3d(tgt_plane.XAxis)
                vx.Unitize()
                vx *= u_offset
                translation_vec += vx

            if abs(v_offset) > 1e-9:
                vy = rg.Vector3d(tgt_plane.YAxis)
                vy.Unitize()
                vy *= v_offset
                translation_vec += vy

            if not translation_vec.IsZero:
                FTAligner._log("Apply fine translation (after align): {0}".format(translation_vec))
                xf_tr2 = FTAligner._translation_transform(translation_vec)
                total_xf *= xf_tr2

            # ---------- 5. 应用总变换 ----------
            aligned = FTAligner._apply_transform(geom, total_xf)
            if aligned is None:
                debug = "ApplyTransform 失败（xf 或几何体为空）。"
                FTAligner._log(debug)
                return (None, None, src_plane, tgt_plane_out, src_pt, tgt_pt, debug)

            debug_msg = ("Mode: {0}; ToolRotDeg: {1}; BlockRotDeg: {2}; "
                         "DepthOffset: {3}; MoveU: {4}; MoveV: {5}; "
                         "FlipX: {6}; FlipY: {7}; FlipZ: {8}").format(
                mode, tool_rot, block_rot, d_offset, u_offset, v_offset,
                flip_x, flip_y, flip_z
            )

            FTAligner._log("Align success.")
            return aligned, total_xf, src_plane, tgt_plane_out, src_pt, tgt_pt, debug_msg

        except Exception as e:
            tb = traceback.format_exc()
            msg = "Align() 发生异常: {0}\n{1}".format(e, tb)
            FTAligner._log(msg)
            return (None, None, None, None, None, None, msg)


if __name__=="__main__":
    # ======================================================================
    # GH-Python 主执行区（多刀具 & 智能广播）
    # ======================================================================

    def _to_list(x):
        """如果是列表/元组则转 list，否则包装成 [x]。"""
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]


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
            # l < n，用最后一个值补齐
            last = seq[-1]
            return seq + [last] * (n - l)
        else:
            return [val] * n


    AlignedTool  = []
    XForm        = []
    SourcePlane  = []
    TargetPlane  = []
    SourcePoint  = []
    TargetPoint  = []
    DebugInfo    = []

    # 1. 基础 ToolGeo 列表
    tools_raw = ToolGeo
    if tools_raw is None:
        tools_raw = []
    tools_list_base = _to_list(tools_raw)

    if len(tools_list_base) == 0 or all(t is None for t in tools_list_base):
        DebugInfo = ["ToolGeo 输入为空，未进行对位。"]
    else:
        tool_count = len(tools_list_base)

        # 2. 决定运算次数 N
        if tool_count == 1:
            # 单刀具：N = max(其它参数长度, 1)
            lengths = [1]  # 至少 1
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
            # 多刀具：N = ToolGeo 数量
            N = tool_count

        # 3. 广播所有参数到长度 N
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

        # 4. 逐次运算
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

# -*- coding: utf-8 -*-
"""FT_QiAo_CircularRevolve_DualDiag_v6

圆形欹䫜刀具：
- 在矩形截面上执行直线欹䫜（两条对角线可选）
- 截面放置在以圆心为基准的径向平面上
- 旋转 360° 得到圆形欹䫜刀具
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import math
import traceback


# ------------------------------------------------------------
# 1) 矩形四顶点
# ------------------------------------------------------------

def _rect_vertices(section_plane, qi_height, sha_width):
    """返回矩形 O, A, B, C 四点"""
    O = section_plane.Origin
    A = section_plane.PointAt(sha_width, 0.0)
    C = section_plane.PointAt(0.0, qi_height)
    B = section_plane.PointAt(sha_width, qi_height)
    return O, A, B, C


# ------------------------------------------------------------
# 2) 构造欹䫜截面：可选两条对角线 A-C 或 O-B
# ------------------------------------------------------------

def build_qi_section_with_diag(section_plane,
                               qi_height,
                               sha_width,
                               offset_fen,
                               use_AC_diag,
                               log):

    tol = 1e-6
    O, A, B, C = _rect_vertices(section_plane, qi_height, sha_width)

    # ---------- 使用 A-C 对角线（原始欹䫜方法） ----------
    if use_AC_diag:
        log.append(u"[build_qi_section] 使用对角线 A-C 欹䫜")

        pt1 = A
        pt2 = C
        origin = O

        diag_vec = pt2 - pt1
        mid_pt = rg.Point3d( (pt1.X + pt2.X)/2.0,
                             (pt1.Y + pt2.Y)/2.0,
                             (pt1.Z + pt2.Z)/2.0 )

        perp_vec = rg.Vector3d.CrossProduct(section_plane.ZAxis, diag_vec)

        # 朝向局部 Y 轴（高方向）
        y_axis = section_plane.YAxis
        if perp_vec * y_axis < 0:
            perp_vec.Reverse()

        if not perp_vec.Unitize():
            log.append(u"[A-C] perp_vec.Unitize 失败")
            return None, None, None

        mid_offset = mid_pt + perp_vec * offset_fen

        arc = rg.Arc(pt1, mid_offset, pt2)
        if not arc.IsValid:
            log.append(u"[A-C] Arc 无效")
            return None, None, None

        arc_crv = rg.ArcCurve(arc)

        bottom  = rg.LineCurve(rg.Line(O, A))
        vertical = rg.LineCurve(rg.Line(C, O))

        poly = rg.PolyCurve()
        poly.Append(bottom)
        poly.Append(arc_crv)
        poly.Append(vertical)
        poly.MakeClosed(tol)

        if not poly.IsClosed:
            j = rg.Curve.JoinCurves([bottom, arc_crv, vertical], tol)
            if not j or len(j)!=1 or not j[0].IsClosed:
                log.append(u"[A-C] Join 未闭合")
                return None, None, None
            poly = j[0]

        return poly, origin, section_plane

    # ---------- 使用 O-B 对角线 ----------
    else:
        log.append(u"[build_qi_section] 使用对角线 O-B 欹䫜")

        pt1 = O
        pt2 = B
        origin = O

        diag_vec = pt2 - pt1
        mid_pt = rg.Point3d( (pt1.X + pt2.X)/2.0,
                             (pt1.Y + pt2.Y)/2.0,
                             (pt1.Z + pt2.Z)/2.0 )

        perp_vec = rg.Vector3d.CrossProduct(section_plane.ZAxis, diag_vec)
        y_axis = section_plane.YAxis
        if perp_vec * y_axis < 0:
            perp_vec.Reverse()

        if not perp_vec.Unitize():
            log.append(u"[O-B] perp_vec.Unitize 失败")
            return None, None, None

        mid_offset = mid_pt + perp_vec * offset_fen

        arc = rg.Arc(pt1, mid_offset, pt2)
        if not arc.IsValid:
            log.append(u"[O-B] Arc 无效")
            return None, None, None

        arc_crv = rg.ArcCurve(arc)

        bottom = rg.LineCurve(rg.Line(O, A))   # O → A
        right  = rg.LineCurve(rg.Line(A, B))   # A → B

        poly = rg.PolyCurve()
        poly.Append(bottom)
        poly.Append(right)
        poly.Append(arc_crv)   # B → O
        poly.MakeClosed(tol)

        if not poly.IsClosed:
            j = rg.Curve.JoinCurves([bottom, right, arc_crv], tol)
            if not j or len(j)!=1 or not j[0].IsClosed:
                log.append(u"[O-B] Join 未闭合")
                return None, None, None
            poly = j[0]

        return poly, origin, section_plane


# ------------------------------------------------------------
# 3) 圆形欹䫜（旋转成体）
# ------------------------------------------------------------

def build_qi_ao_circular_revolve(qi_height,
                                 sha_width,
                                 base_point,
                                 radius,
                                 reference_plane=None,
                                 qi_dir_inward=True,
                                 log=None):

    if log is None:
        log = []

    tol = sc.doc.ModelAbsoluteTolerance if sc.doc else 0.001
    log.append(u"=== FT_QiAo_CircularRevolve_DualDiag_v6 开始 ===")

    try:
        # 1) 参考平面
        if reference_plane is None:
            reference_plane = rg.Plane(
                base_point, rg.Vector3d(1,0,0), rg.Vector3d(0,1,0)
            )
            log.append(u"使用默认 XY 平面作为参考平面")
        else:
            reference_plane = rg.Plane(reference_plane)
            reference_plane.Origin = base_point
            log.append(u"使用输入 reference_plane，并将原点设为 base_point")

        # 2) 底边圆：作为 BaseLine 输出
        base_circle = rg.Circle(reference_plane, radius)
        log.append(u"底边圆已构建（最外层圆边线）")

        # 3) 半径方向（圆心 → 圆周 param=0）
        outer_pt = base_circle.PointAt(0.0)
        radial_vec = outer_pt - base_point
        radial_vec.Unitize()

        # 4) 截面平面（放在 radius - sha_width 处）
        origin = base_point + radial_vec * (radius - sha_width)
        x_axis = radial_vec             # 杀方向
        y_axis = reference_plane.ZAxis  # 欹高方向
        x_axis.Unitize()
        y_axis.Unitize()

        sec_plane = rg.Plane(origin, x_axis, y_axis)
        log.append(u"截面平面 sec_plane 已构建")

        # 5) 构造截面（两条对角线其一）
        offset_fen = 1.0
        use_AC_diag = bool(qi_dir_inward)

        section_curve, corner_pt, sec_plane2 = build_qi_section_with_diag(
            sec_plane, qi_height, sha_width, offset_fen,
            use_AC_diag, log
        )
        if section_curve is None:
            log.append(u"构造截面失败")
            return None, None, None, None, None, log

        # 6) 旋转轴：圆心沿 Z 轴
        axis_line = rg.Line(base_point, base_point + reference_plane.ZAxis)

        # 7) 回转体
        rev_srf = rg.RevSurface.Create(
            section_curve, axis_line, 0.0, 2.0 * math.pi
        )
        brep = rev_srf.ToBrep()

        # 封顶
        if not brep.IsSolid:
            capped = brep.CapPlanarHoles(tol)
            if capped: brep = capped

        # 8) CirclePlane = 以 base_point 为 origin 的参考平面
        circle_plane = rg.Plane(reference_plane)
        circle_plane.Origin = base_point
        log.append(u"CirclePlane 已生成（过圆心）")

        log.append(u"=== FT_QiAo_CircularRevolve_DualDiag_v6 完成 ===")
        return brep, corner_pt, base_circle, sec_plane2, circle_plane, log

    except Exception as e:
        log.append(u"运行异常: %s" % e)
        log.append(traceback.format_exc())
        return None, None, None, None, None, log

if __name__ == "__main__":
    # ------------------------------------------------------------
    # 4) GhPython 主体
    # ------------------------------------------------------------

    Log = []
    if qi_height is None: qi_height = 8.0
    if sha_width is None: sha_width = 4.0
    if radius    is None: radius    = 36.0 / 2.0

    if base_point is None:
        base_point = rg.Point3d(0,0,0)
    elif isinstance(base_point, rg.Point):
        base_point = base_point.Location

    if QiDirInward is None:
        QiDirInward = True

    ToolBrep  = None
    BasePoint = None
    BaseLine  = None
    SecPlane  = None
    CirclePlane = None

    ToolBrep, BasePoint, BaseLine, SecPlane, CirclePlane, Log = \
        build_qi_ao_circular_revolve(
            qi_height,
            sha_width,
            base_point,
            radius,
            reference_plane,
            QiDirInward,
            log=Log
        )

# -*- coding: utf-8 -*-
import Rhino.Geometry as rg


# ================================================================
# 闇栔 (An Zhi) 特征刀具 - 类封装
# ================================================================
class FT_AnZhiToolBuilder(object):
    """
    闇栔特征刀具构造器

    截面平面 SectionPlane：
        XAxis → 殺（宽向）
        YAxis → 欹（高向）
        ZAxis → 挤出方向（基准）

    base_point 为直角点（水平边与垂直边交点）
    """

    def __init__(self, base_point, reference_plane=None):
        """
        base_point      : rg.Point3d，截面直角点
        reference_plane : rg.Plane 或 None
            - None：World X 作为宽向，World Z 作为高向
            - 非 None：继承其坐标轴，Origin 改为 base_point
        """
        if reference_plane is None:
            x_axis = rg.Vector3d(1.0, 0.0, 0.0)  # 殺向
            y_axis = rg.Vector3d(0.0, 0.0, 1.0)  # 欹向
            self.section_plane = rg.Plane(base_point, x_axis, y_axis)
        else:
            self.section_plane = rg.Plane(reference_plane)
            self.section_plane.Origin = base_point

    # ------------------------------------------------------------
    # 1. 构造欹栈截面
    # ------------------------------------------------------------
    def _build_qiao_section(self, qi_height, sha_width, offset_fen):
        """
        在 section_plane 内构造欹栈截面：
        Origin -> 水平端点 -> 弧 -> 垂直端点 -> Origin
        """
        plane = rg.Plane(self.section_plane)
        origin = plane.Origin

        # 水平端点（沿 X）
        ptH = plane.PointAt(sha_width, 0.0)
        # 垂直端点（沿 Y）
        ptV = plane.PointAt(0.0, qi_height)

        # 对角线中点
        mid = rg.Point3d(
            0.5 * (ptH.X + ptV.X),
            0.5 * (ptH.Y + ptV.Y),
            0.5 * (ptH.Z + ptV.Z)
        )

        diag_vec = ptV - ptH
        # 平面内垂直于对角线的向量：Z × diag
        perp_vec = rg.Vector3d.CrossProduct(plane.ZAxis, diag_vec)

        # 调整到与 YAxis 同向
        if rg.Vector3d.Multiply(perp_vec, plane.YAxis) < 0:
            perp_vec.Reverse()

        if not perp_vec.Unitize():
            return None, None, None

        mid_offset = mid + perp_vec * offset_fen

        # 三点弧
        arc = rg.Arc(ptH, mid_offset, ptV)
        if not arc.IsValid:
            return None, None, None

        arc_crv = rg.ArcCurve(arc)

        # 水平、垂直边
        bottom_crv = rg.LineCurve(origin, ptH)
        vertical_crv = rg.LineCurve(ptV, origin)

        poly = rg.PolyCurve()
        poly.Append(bottom_crv)
        poly.Append(arc_crv)
        poly.Append(vertical_crv)
        poly.MakeClosed(1e-6)

        section_curve = poly
        if not section_curve.IsClosed:
            joined = rg.Curve.JoinCurves(
                [bottom_crv, arc_crv, vertical_crv], 1e-6
            )
            if not joined or len(joined) != 1 or not joined[0].IsClosed:
                return None, None, None
            section_curve = joined[0]

        return section_curve, origin, plane

    # ------------------------------------------------------------
    # 2. 构造欹栈弧体（原 ToolBrep 部分）
    # ------------------------------------------------------------
    def _build_qiao_body(self, qi_height, sha_width, extrude_length, offset_fen=1.0):
        """
        构造欹栈弧体（挤出体），并给出原有输出：
            tool_brep   : 弧体实体
            corner_pt   : 直角点
            base_line   : 直角点沿挤出方向线段
            sec_plane   : 截面平面
            face_plane  : 参考立面平面（由 欹向 + 挤出方向 构成）
            dir_vec     : 实际挤出方向（考虑 extrude_positive 后）
        """
        section_curve, corner_pt, sec_plane = self._build_qiao_section(
            qi_height, sha_width, offset_fen
        )
        if section_curve is None:
            return None, None, None, None, None, None

        # 挤出方向
        dir_vec = sec_plane.ZAxis
        if not dir_vec.Unitize():
            return None, None, None, None, None, None

        # 内部默认 extrude_positive = False
        extrude_positive = False
        if not extrude_positive:
            dir_vec.Reverse()

        height_signed = extrude_length if extrude_positive else -extrude_length

        extrusion = rg.Extrusion.Create(section_curve, height_signed, True)
        if extrusion is None:
            return None, None, None, None, None, None

        tool_brep = extrusion.ToBrep()
        if tool_brep is None:
            return None, None, None, None, None, None

        # BaseLine：直角点沿真实挤出方向
        base_line = rg.Line(corner_pt, corner_pt + dir_vec * extrude_length)

        # FacePlane：以 BaseLine 中点为原点，轴向为 (欹向, 挤出方向)
        mid_base = base_line.PointAt(0.5)
        vertical_dir = sec_plane.YAxis
        vertical_dir.Unitize()
        face_plane = rg.Plane(mid_base, vertical_dir, dir_vec)

        return tool_brep, corner_pt, base_line, sec_plane, face_plane, dir_vec

    # ------------------------------------------------------------
    # 3. 构造长方体（高×宽 面完全落在 FacePlane 上）
    # 同时返回：Brep、顶点、边中点、各面平面
    # ------------------------------------------------------------
    def _build_cube_body(self, qi_height, sha_width, extra_height, cube_length,
                         extrude_length, sec_plane, corner_pt, dir_vec, face_plane):
        """
        构造长方体，使其"高×宽"的矩形面完全位于 FacePlane 上，且：
        - 高 H  = qi_height + extra_height
        - 宽 W  = extrude_length   （与欹栈弧体挤出厚度一致）
        - 长 L  = cube_length
        并返回：
            cube_brep         : 长方体 Brep
            cube_vertices     : 8 个顶点列表
            cube_edge_centers : 12 条边的中点列表
            cube_face_planes  : 6 个面过几何中心点的参考平面
        """
        # 高方向 = FacePlane.XAxis（即 SecPlane.YAxis）
        H_dir = rg.Vector3d(face_plane.XAxis)
        H_dir.Unitize()

        # 宽方向 = FacePlane.YAxis
        W_dir = rg.Vector3d(face_plane.YAxis)
        W_dir.Unitize()

        # 长方向 = FacePlane.ZAxis
        L_dir = rg.Vector3d(face_plane.ZAxis)
        L_dir.Unitize()

        H = qi_height + extra_height
        W = extrude_length    # ★ 改为挤出长度
        L = cube_length

        # FacePlane 上的高×宽矩形面起点（靠弧形侧的直角点）
        origin = corner_pt

        # 使用 Box 构建立方体
        plane_box = rg.Plane(origin, H_dir, W_dir)
        plane_box.ZAxis = L_dir
        box = rg.Box(plane_box,
                     rg.Interval(0, H),
                     rg.Interval(0, W),
                     rg.Interval(0, L))
        cube_brep = box.ToBrep()

        # ---------- 顶点 ----------
        vx = H_dir * H
        vy = W_dir * W
        vz = L_dir * L

        p000 = origin
        p100 = origin + vx
        p010 = origin + vy
        p110 = origin + vx + vy
        p001 = origin + vz
        p101 = origin + vx + vz
        p011 = origin + vy + vz
        p111 = origin + vx + vy + vz

        cube_vertices = [p000, p100, p110, p010,
                         p001, p101, p111, p011]

        # ---------- 边中点（12 条边） ----------
        edge_index_pairs = [
            (0, 1), (1, 2), (2, 3), (3, 0),   # L = 0 面的四条边
            (4, 5), (5, 6), (6, 7), (7, 4),   # L = L 面的四条边
            (0, 4), (1, 5), (2, 6), (3, 7)    # 四条“竖向”边
        ]
        cube_edge_centers = []
        for i, j in edge_index_pairs:
            a = cube_vertices[i]
            b = cube_vertices[j]
            mid = rg.Point3d((a.X + b.X) * 0.5,
                             (a.Y + b.Y) * 0.5,
                             (a.Z + b.Z) * 0.5)
            cube_edge_centers.append(mid)

        # ---------- 各面过几何中心点的参考平面 ----------
        face_index_quads = [
            (0, 1, 2, 3),  # L_min  面
            (4, 5, 6, 7),  # L_max  面
            (0, 3, 7, 4),  # W_min  面
            (1, 2, 6, 5),  # W_max  面
            (0, 1, 5, 4),  # H_min  面
            (3, 2, 6, 7),  # H_max  面
        ]
        cube_face_planes = []
        for ia, ib, ic, id_ in face_index_quads:
            pa = cube_vertices[ia]
            pb = cube_vertices[ib]
            pc = cube_vertices[ic]
            pd = cube_vertices[id_]

            # 几何中心 = 四点平均
            cx = (pa.X + pb.X + pc.X + pd.X) * 0.25
            cy = (pa.Y + pb.Y + pc.Y + pd.Y) * 0.25
            cz = (pa.Z + pb.Z + pc.Z + pd.Z) * 0.25
            center = rg.Point3d(cx, cy, cz)

            # 面内两条边方向作为 X/Y 轴
            x_dir = pb - pa
            y_dir = pc - pa
            if not x_dir.IsZero and not y_dir.IsZero:
                plane_face = rg.Plane(center, x_dir, y_dir)
                cube_face_planes.append(plane_face)

        return cube_brep, cube_vertices, cube_edge_centers, cube_face_planes

    # ------------------------------------------------------------
    # 4. 构造插销长方体（上下各一个）
    # ------------------------------------------------------------
    def _build_pin_bodies(self, pin_height, pin_width, pin_length, pin_offset,
                          cube_length, qi_height, extra_height, extrude_length,
                          corner_pt, face_plane, log_list):
        """
        在主长方体的上下表面添加两个插销长方体 (PinBreps)。
        几何约定同 _build_cube_body。
        """

        # 主长方体局部坐标系
        H_dir = rg.Vector3d(face_plane.XAxis)   # 高向
        W_dir = rg.Vector3d(face_plane.YAxis)   # 宽向
        L_dir = rg.Vector3d(face_plane.ZAxis)   # 长向
        H_dir.Unitize()
        W_dir.Unitize()
        L_dir.Unitize()

        # 主长方体尺寸
        H = qi_height + extra_height
        W = extrude_length   # ★ 与 cube_body 一致，宽 = 挤出长度
        L = cube_length

        if pin_offset is None:
            pin_offset = 6.0

        log_list.append("=== PIN BODIES BUILD (length-offset) ===")
        log_list.append("Cube: H={}, W={}, L={}".format(H, W, L))
        log_list.append("Pin:  h={}, w={}, l={}, offset={}".format(
            pin_height, pin_width, pin_length, pin_offset))

        pin_breps = []

        # 宽向中心：W/2（保持插销在截面宽度方向居中）
        # 长向中心：L - pin_offset（距远端 L 面 pin_offset）
        width_center  = W * 0.5
        length_center = L - pin_offset

        # 下表面 (H = 0) 上的长向中心线点
        base_center_bottom = (corner_pt
                              + W_dir * width_center
                              + L_dir * length_center)

        # 上表面 (H = H) 上的长向中心线点
        base_center_top = (corner_pt
                           + H_dir * H
                           + W_dir * width_center
                           + L_dir * length_center)

        # 计算两种插销的几何中心点
        centers = {
            # 下插销：顶部贴 H=0 ⇒ 中心在 H = -pin_height/2
            'bottom': base_center_bottom - H_dir * (pin_height * 0.5),
            # 上插销：底部贴 H=H ⇒ 中心在 H = H + pin_height/2
            'top':    base_center_top    + H_dir * (pin_height * 0.5),
        }

        for pin_type, center in centers.items():
            # 由几何中心点推回到立方体最小角点 p0
            p0 = (center
                  - H_dir * (pin_height * 0.5)
                  - W_dir * (pin_width  * 0.5)
                  - L_dir * (pin_length * 0.5))

            # 其余 7 个角点
            p1 = p0 + W_dir * pin_width
            p2 = p1 + H_dir * pin_height
            p3 = p0 + H_dir * pin_height

            p4 = p0 + L_dir * pin_length
            p5 = p1 + L_dir * pin_length
            p6 = p2 + L_dir * pin_length
            p7 = p3 + L_dir * pin_length

            log_list.append(
                "Pin {} center: ({:.3f}, {:.3f}, {:.3f})".format(
                    pin_type, center.X, center.Y, center.Z)
            )

            try:
                box_pts = [p0, p1, p5, p4, p3, p2, p6, p7]
                pin_brep = rg.Brep.CreateFromBox(box_pts)

                if pin_brep is not None and pin_brep.IsValid:
                    pin_breps.append(pin_brep)
                    log_list.append("  -> Pin({}) created successfully".format(pin_type))
                else:
                    log_list.append("  -> ERROR: Pin({}) brep invalid".format(pin_type))
            except Exception as e:
                log_list.append("  -> ERROR: Pin({}) exception: {}".format(pin_type, str(e)))

        log_list.append("Total pins: {}".format(len(pin_breps)))
        return pin_breps

    # ------------------------------------------------------------
    # 5. 主函数：构造 闇栔 (An Zhi) 特征工具
    # ------------------------------------------------------------
    def build_an_zhi(self, qi_height, sha_width, extrude_length, cube_length,
                     extra_height, offset_fen, pin_height, pin_width, pin_length,
                     pin_offset, log_list):
        """
        构造闇栔特征工具
        """
        log_list.append("=== AN ZHI BUILD START ===")

        # 先构造欹栈弧体
        tool_brep, corner_pt, base_line, sec_plane, face_plane, dir_vec = \
            self._build_qiao_body(qi_height, sha_width, extrude_length, offset_fen)

        log_list.append("Tool brep: {}".format(tool_brep is not None))

        if tool_brep is None:
            log_list.append("ERROR: tool_brep is None")
            return (None, None, None, None,
                    corner_pt, base_line, sec_plane, face_plane,
                    None, None, None)

        # 再构造长方体部分（宽度 = extrude_length）
        cube_brep, cube_vertices, cube_edge_centers, cube_face_planes = \
            self._build_cube_body(qi_height, sha_width, extra_height, cube_length,
                                  extrude_length,
                                  sec_plane, corner_pt, dir_vec, face_plane)

        log_list.append("Cube brep: {}".format(cube_brep is not None))

        if cube_brep is None:
            log_list.append("ERROR: cube_brep is None")
            return (tool_brep, None, None, None,
                    corner_pt, base_line, sec_plane, face_plane,
                    None, None, None)

        # 构造插销长方体（同样以 extrude_length 为宽）
        pin_breps = self._build_pin_bodies(pin_height, pin_width, pin_length, pin_offset,
                                           cube_length, qi_height, extra_height, extrude_length,
                                           corner_pt, face_plane, log_list)

        # Join 为一个封闭 Brep，包含所有部件
        all_breps = [tool_brep, cube_brep] + pin_breps
        log_list.append("Total breps to join: {}".format(len(all_breps)))

        joined = rg.Brep.JoinBreps(all_breps, 1e-3)
        log_list.append("JoinBreps result: {} breps".format(len(joined) if joined else 0))

        an_zhi_brep = None
        if joined and len(joined) >= 1:
            if len(joined) == 1:
                an_zhi_brep = joined[0]
                log_list.append("Successfully joined to 1 brep")
            else:
                joined2 = rg.Brep.JoinBreps(joined, 1e-3)
                if joined2 and len(joined2) == 1:
                    an_zhi_brep = joined2[0]
                    log_list.append("2nd pass join successful")
                else:
                    log_list.append("Attempting Boolean Union...")

        # 如果 Join 失败，尝试使用 Boolean Union
        if an_zhi_brep is None:
            try:
                result = rg.Brep.CreateBooleanUnion(all_breps, 1e-3)
                if result and len(result) > 0:
                    an_zhi_brep = result[0]
                    log_list.append("Boolean Union successful")
                else:
                    log_list.append("Boolean Union returned empty")
            except Exception as e:
                log_list.append("Boolean Union error: {}".format(str(e)))

        log_list.append("=== AN ZHI BUILD END ===")

        return (tool_brep, cube_brep, pin_breps, an_zhi_brep,
                corner_pt, base_line, sec_plane, face_plane,
                cube_edge_centers, cube_face_planes, cube_vertices)

if __name__ == '__main__':
    # ================================================================
    # GhPython 主执行区
    # ================================================================

    if qi_height is None:
        qi_height = 8.0

    if sha_width is None:
        sha_width = 4.0

    if extrude_length is None:
        extrude_length = 4.0

    if cube_length is None:
        cube_length = 31.0 - 4.0 - 7

    if extra_height is None:
        extra_height = 2.0

    if offset_fen is None:
        offset_fen = 1.0

    if pin_height is None:
        pin_height = 4.0

    if pin_width is None:
        pin_width = 2.5

    if pin_length is None:
        pin_length = 4.0

    if pin_offset is None:
        pin_offset = 6.0

    if base_point is None:
        base_point = rg.Point3d(0.0, 0.0, 0.0)
    elif isinstance(base_point, rg.Point):
        base_point = base_point.Location

    log_list = []

    builder = FT_AnZhiToolBuilder(base_point, reference_plane)

    (tool_brep, cube_brep, pin_breps, an_zhi_brep,
     corner_pt, base_line, sec_plane, face_plane,
     cube_edge_centers, cube_face_planes, cube_vertices) = \
        builder.build_an_zhi(qi_height, sha_width, extrude_length, cube_length,
                             extra_height, offset_fen,
                             pin_height, pin_width, pin_length, pin_offset,
                             log_list)

    # ---- 输出到 GhPython 组件 ----
    ToolBrep         = tool_brep
    BasePoint        = corner_pt
    BaseLine         = base_line
    SecPlane         = sec_plane
    FacePlane        = face_plane
    CubeBrep         = cube_brep
    PinBreps         = pin_breps
    AnZhiToolBrep    = an_zhi_brep
    CubeEdgeCenters  = cube_edge_centers   # 1. 边中点列表（12 个）
    CubeFacePlanes   = cube_face_planes    # 2. 各面参考平面（6 个）
    CubeVertices     = cube_vertices       # 3. 顶点列表（8 个）
    Log              = log_list


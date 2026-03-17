import Rhino.Geometry as rg


# ===========================
# 构造欹䫜截面
# ===========================

def build_qiao_section(section_plane, qi_height, sha_width, offset_fen):
    """
    在给定平面 section_plane 内构造欹䫜截面：

    几何约定：
    - section_plane.Origin = 直角点 = 水平边与垂直边交点；
    - X 轴方向 = 殺（宽）方向；
    - Y 轴方向 = 欹（高）方向；
    - 水平边：Origin -> Origin + X * sha_width
    - 垂直边：Origin -> Origin + Y * qi_height
    - 对角线：水平端点 <-> 垂直端点
    - 对角线中点沿平面内、垂直对角线方向，
      并朝 Y 轴正方向偏移 offset_fen（单位：分°），形成三点弧；
    - 截面轮廓：Origin -> 水平端点 -> 弧 -> 垂直端点 -> Origin。
    """

    origin = section_plane.Origin

    # 水平端点（沿 X 轴）
    ptH = section_plane.PointAt(sha_width, 0.0)
    # 垂直端点（沿 Y 轴）
    ptV = section_plane.PointAt(0.0, qi_height)

    # 对角线向量与中点（ptH -> ptV）
    diag_vec = ptV - ptH
    mid_pt = rg.Point3d(
        0.5 * (ptH.X + ptV.X),
        0.5 * (ptH.Y + ptV.Y),
        0.5 * (ptH.Z + ptV.Z)
    )

    # 平面内一条垂直对角线的向量：plane.ZAxis × diag_vec
    perp_vec = rg.Vector3d.CrossProduct(section_plane.ZAxis, diag_vec)

    # 朝向“高”方向（局部 Y 轴）的一侧
    y_axis = section_plane.YAxis
    if rg.Vector3d.Multiply(perp_vec, y_axis) < 0:
        perp_vec.Reverse()

    if not perp_vec.Unitize():
        return None, None, None

    # 偏移向量（offset_fen 为“欹䫜量”，单位分°）
    offset_vec = perp_vec * offset_fen
    mid_offset_pt = mid_pt + offset_vec

    # 三点弧：ptH → mid_offset_pt → ptV
    arc = rg.Arc(ptH, mid_offset_pt, ptV)
    if not arc.IsValid:
        return None, None, None

    arc_crv = rg.ArcCurve(arc)

    # 水平边与垂直边
    bottom_crv   = rg.LineCurve(rg.Line(origin, ptH))
    vertical_crv = rg.LineCurve(rg.Line(ptV, origin))

    # 组合闭合截面：Origin -> H -> arc -> V -> Origin
    poly = rg.PolyCurve()
    poly.Append(bottom_crv)
    poly.Append(arc_crv)
    poly.Append(vertical_crv)
    poly.MakeClosed(1e-6)

    section_curve = poly
    if not section_curve.IsClosed:
        joined = rg.Curve.JoinCurves([bottom_crv, arc_crv, vertical_crv], 1e-6)
        if not joined or len(joined) != 1 or not joined[0].IsClosed:
            return None, None, None
        section_curve = joined[0]

    # 返回：截面曲线、直角点、截面平面
    return section_curve, origin, section_plane


# ===========================
# 构造欹䫜刀具（体）
# ===========================

def build_qiao_tool(qi_height,
                        sha_width,
                        offset_fen,
                        extrude_length,
                        base_point,
                        reference_plane=None,
                        extrude_positive=True):
    """
    构造欹䫜刀具：

    - qi_height     : 欹高（分°）
    - sha_width     : 殺宽（分°）
    - offset_fen    : 欹䫜量（对角线中点向内偏移量，分°）
    - extrude_length: 刀具沿法线方向厚度（分°）

    - 默认截面位于 XZ 平面：
        X = World X（殺），Y = World Z（欹），Z = ±World Y（法线）。
    - 若 reference_plane 不为空：
        使用其朝向，仅将 Origin 改为 base_point。
    - base_point 总是设为“水平边与垂直边的交点”（直角点）。
    - extrude_positive 控制沿平面法线正向或反向拉伸。
    """

    # 1. 确定截面平面（origin = base_point）
    if reference_plane is None:
        world_x = rg.Vector3d(1, 0, 0)
        world_z = rg.Vector3d(0, 0, 1)
        section_plane = rg.Plane(base_point, world_x, world_z)
    else:
        section_plane = rg.Plane(reference_plane)
        section_plane.Origin = base_point

    # 2. 构造截面（偏移使用输入的 offset_fen）
    section_curve, corner_pt, sec_plane = build_qiao_section(
        section_plane, qi_height, sha_width, offset_fen
    )
    if section_curve is None:
        return None, None, None, None, None

    # 3. 计算拉伸方向向量与高度标量
    dir_vec = sec_plane.ZAxis
    if not dir_vec.Unitize():
        return None, None, None, None, None

    if not extrude_positive:
        dir_vec.Reverse()

    height_signed = extrude_length if extrude_positive else -extrude_length

    # 使用 Extrusion.Create 生成体
    extrusion = rg.Extrusion.Create(section_curve, height_signed, True)
    if extrusion is None:
        return None, None, None, None, None

    tool_brep = extrusion.ToBrep()

    # 4. BaseLine：直角点沿真实拉伸方向的线段
    base_line = rg.Line(corner_pt, corner_pt + dir_vec * extrude_length)

    # 5. FacePlane：BaseLine 中点为原点，由“垂直线方向 + 拉伸方向”构成的面的参考平面
    mid_base = base_line.PointAt(0.5)      # BaseLine 中点
    vertical_dir = sec_plane.YAxis         # 垂直线方向（欹方向）
    vertical_dir.Unitize()
    face_plane = rg.Plane(mid_base, vertical_dir, dir_vec)

    return tool_brep, corner_pt, base_line, sec_plane, face_plane


if __name__=='__main__':
    # ===========================
    # GhPython 主逻辑
    # ===========================

    # 默认值处理
    if qi_height is None:
        qi_height = 8.0

    if sha_width is None:
        sha_width = 4.0

    # 新增：欹䫜量输入（分°），默认 1 分°
    if 'qi_offset_fen' in globals():
        # 如果在 GhPython 组件中已经声明了输入 qi_offset_fen
        if qi_offset_fen is None:
            qi_offset_fen = 1.0
    else:
        # 防御性：脚本单独跑时也有默认值
        qi_offset_fen = 1.0

    if extrude_length is None:
        extrude_length = 36.0 + 10.0  # 46 分°

    # base_point 统一为 Point3d
    if base_point is None:
        base_point = rg.Point3d(0.0, 0.0, 0.0)
    elif isinstance(base_point, rg.Point):
        base_point = base_point.Location

    if extrude_positive is None:
        extrude_positive = True

    # reference_plane 允许为 None，直接传入

    ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
        qi_height,
        sha_width,
        qi_offset_fen,
        extrude_length,
        base_point,
        reference_plane,
        extrude_positive
    )


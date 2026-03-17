import Rhino.Geometry as rg


def build_timber_block(length_fen,
                       width_fen,
                       height_fen,
                       base_point,
                       reference_plane=None):
    """
    构建一个用于加工的木料长方体，并返回：
    - timber_brep      : Brep
    - faces            : list[rg.BrepFace]
    - vertices         : list[rg.Point3d]
    - edges_curves     : list[rg.Curve]
    - center_point     : rg.Point3d
    - center_axis_list : list[rg.Line] （6 条，中心沿 ±X/±Y/±Z）
    - edge_midpoints   : list[rg.Point3d]
    - face_planes      : list[rg.Plane]（每个面的参考平面，原点为该面的几何中心）
    """

    # 1. 确定参考平面：
    if reference_plane is None:
        world_x = rg.Vector3d(1, 0, 0)
        world_z = rg.Vector3d(0, 0, 1)
        base_plane = rg.Plane(base_point, world_x, world_z)
    else:
        base_plane = rg.Plane(reference_plane)
        base_plane.Origin = base_point

    # 2. 在该平面下建立 Box：
    x_interval = rg.Interval(0.0, length_fen)
    y_interval = rg.Interval(0.0, height_fen)
    z_interval = rg.Interval(0.0, width_fen)

    box = rg.Box(base_plane, x_interval, y_interval, z_interval)
    timber_brep = box.ToBrep()

    # 3. 顶点列表（8 个点）
    corners = list(box.GetCorners())

    # 4. 面列表（BrepFace）
    faces = [f for f in timber_brep.Faces]

    # 5. 边线列表（转为 Curve）
    edges_curves = [e.DuplicateCurve() for e in timber_brep.Edges]

    # 6. 几何中心点（用 Box 的中心）
    center_point = box.Center

    # 7. 中心点沿参考平面 XYZ ±方向的轴线
    axis_x = base_plane.XAxis
    axis_y = base_plane.YAxis
    axis_z = base_plane.ZAxis

    axis_x.Unitize()
    axis_y.Unitize()
    axis_z.Unitize()

    half_len = length_fen * 0.5
    half_hgt = height_fen * 0.5
    half_wid = width_fen * 0.5

    center_axis_list = []

    # +X / -X
    center_axis_list.append(
        rg.Line(center_point, center_point + axis_x * half_len)
    )
    center_axis_list.append(
        rg.Line(center_point, center_point - axis_x * half_len)
    )

    # +Y / -Y
    center_axis_list.append(
        rg.Line(center_point, center_point + axis_y * half_hgt)
    )
    center_axis_list.append(
        rg.Line(center_point, center_point - axis_y * half_hgt)
    )

    # +Z / -Z
    center_axis_list.append(
        rg.Line(center_point, center_point + axis_z * half_wid)
    )
    center_axis_list.append(
        rg.Line(center_point, center_point - axis_z * half_wid)
    )

    # 8. 各边中点列表
    edge_midpoints = []
    for crv in edges_curves:
        t_mid = crv.Domain.ParameterAt(0.5)
        edge_midpoints.append(crv.PointAt(t_mid))

    # 9. 各面的参考平面（原点为该面的几何中心）
    face_planes = []
    for face in faces:
        # 复制成单独的 Brep 来算面积性质
        face_brep = face.DuplicateFace(True)
        amp = rg.AreaMassProperties.Compute(face_brep)

        if amp is not None:
            centroid = amp.Centroid
        else:
            bb = face_brep.GetBoundingBox(True)
            centroid = bb.Center

        # 取中间参数的法线方向
        u_dom = face.Domain(0)
        v_dom = face.Domain(1)
        u_mid = 0.5 * (u_dom.T0 + u_dom.T1)
        v_mid = 0.5 * (v_dom.T0 + v_dom.T1)

        normal = face.NormalAt(u_mid, v_mid)
        if normal.IsTiny():
            # 如果极端情况法线很小，给个默认
            normal = rg.Vector3d(0, 0, 1)
        normal.Unitize()

        # 用中心点和法线构造平面
        pl = rg.Plane(centroid, normal)
        face_planes.append(pl)

    return (timber_brep,
            faces,
            corners,
            edges_curves,
            center_point,
            center_axis_list,
            edge_midpoints,
            face_planes)


if __name__ == "__main__":
    # ===========================
    # GhPython 主逻辑
    # ===========================

    # 输入默认值处理
    if length_fen is None:
        length_fen = 32.0

    if width_fen is None:
        width_fen = 32.0

    if height_fen is None:
        height_fen = 20.0

    # base_point 统一为 Point3d
    if base_point is None:
        base_point = rg.Point3d(0.0, 0.0, 0.0)
    elif isinstance(base_point, rg.Point):
        base_point = base_point.Location

    (timber_brep,
     faces,
     points,
     edges,
     center_pt,
     center_axes,
     edge_midpts,
     face_planes) = build_timber_block(
        length_fen,
        width_fen,
        height_fen,
        base_point,
        reference_plane
    )

    # 输出到 Grasshopper
    TimberBrep      = timber_brep
    FaceList        = faces
    PointList       = points
    EdgeList        = edges
    CenterAxisLines = center_axes
    EdgeMidPoints   = edge_midpts
    FacePlaneList   = face_planes

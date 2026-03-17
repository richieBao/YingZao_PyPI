# -*- coding: utf-8 -*-
"""
FT_timber_block
===========================
根据 length_fen / width_fen / height_fen 和 base_point / reference_plane
构造一个木料长方体 Brep，并用与 FT_TimberBoxFeatures 完全一致的
方法提取几何特征（Up–Forward–Left 稳定局部坐标系）。

GhPython 输入：
------------------------------------------------
length_fen      : float
width_fen       : float
height_fen      : float
base_point      : rg.Point3d 或 rg.Point
reference_plane : rg.Plane (可选)

GhPython 输出（与 FT_TimberBoxFeatures 对齐）：
------------------------------------------------
TimberBrep      : Brep
FaceList        : list[rg.BrepFace]
PointList       : list[rg.Point3d]
EdgeList        : list[rg.Curve]
CenterPoint     : rg.Point3d
CenterAxisLines : list[rg.Line]
EdgeMidPoints   : list[rg.Point3d]
FacePlaneList   : list[rg.Plane]
Corner0Planes   : list[rg.Plane]
LocalAxesPlane  : rg.Plane
AxisX           : rg.Vector3d
AxisY           : rg.Vector3d
AxisZ           : rg.Vector3d
FaceDirTags     : list[str]
EdgeDirTags     : list[str]
Corner0EdgeDirs : list[rg.Vector3d]
Log             : list[str]
"""

import Rhino.Geometry as rg


# =========================================================
# 与 FT_TimberBoxFeatures 组件完全一致的特征提取类
# （原样拷贝，以保证计算方法 100% 一致）
# =========================================================

class FT_TimberBoxFeatures(object):

    def __init__(self):
        self._log = []

    def log(self, msg):
        self._log.append(str(msg))

    @property
    def log_lines(self):
        return self._log

    def _axis_tag(self, idx, sign):
        return ["+X", "-X", "+Y", "-Y", "+Z", "-Z"][(idx * 2) + (0 if sign >= 0 else 1)]

    # ----------------------------------------------------------------------
    # Corner0 = Brep.Vertices[0]（拓扑稳定，不随旋转改变）
    # ----------------------------------------------------------------------
    def _get_corner0(self, brep):
        if brep.Vertices.Count == 0:
            raise ValueError("Brep 无顶点")
        P0 = brep.Vertices[0].Location
        self.log("Corner0 = Brep.Vertices[0]")
        return P0

    # ----------------------------------------------------------------------
    # 获取 Corner0 三条邻边方向
    # ----------------------------------------------------------------------
    def _neighbor_edge_dirs(self, brep, P0, tol=1e-9):
        dirs = []
        for e in brep.Edges:
            pA = e.StartVertex.Location
            pB = e.EndVertex.Location
            if pA.DistanceTo(P0) < tol:
                dirs.append(pB - P0)
            elif pB.DistanceTo(P0) < tol:
                dirs.append(pA - P0)
        if len(dirs) != 3:
            raise ValueError("Corner0 未找到 3 条邻边，找到 {}".format(len(dirs)))
        for i, d in enumerate(dirs):
            self.log(
                "NeighborEdge[{}]={:.3f},{:.3f},{:.3f}".format(i, d.X, d.Y, d.Z)
            )
        return dirs

    # ----------------------------------------------------------------------
    # Up–Forward–Left 局部坐标系（最终版）
    # ----------------------------------------------------------------------
    def _stable_axes(self, dirs):
        worldZ = rg.Vector3d(0, 0, 1)

        # Step 1：按 abs(Z) 排序区分水平边和竖边
        d_sorted = sorted(dirs, key=lambda v: abs(v.Z))
        H1, H2, V = d_sorted[0], d_sorted[1], d_sorted[2]

        self.log("水平边 H1, H2；竖边 V")

        # 单位化
        H1u = rg.Vector3d(H1)
        H1u.Unitize()
        H2u = rg.Vector3d(H2)
        H2u.Unitize()
        Vu = rg.Vector3d(V)
        Vu.Unitize()

        # Step 2：根据左手规则选局部 X（Forward）
        # 若 H1 的左侧是 H2，则 X=H1；否则 X=H2
        # 左侧判定：Cross(H1, H2)·worldZ > 0？
        if rg.Vector3d.Multiply(rg.Vector3d.CrossProduct(H1u, H2u), worldZ) > 0:
            axis_x = H1u
            axis_y = H2u
        else:
            axis_x = H2u
            axis_y = H1u

        # Step 3：校正 Left，使 Cross(X,Y) 与 worldZ 同向（保持左手系）
        if (
            rg.Vector3d.Multiply(rg.Vector3d.CrossProduct(axis_x, axis_y), worldZ)
            < 0
        ):
            axis_y *= -1

        # Step 4：局部 Z = 竖边方向 V，调整符号使其与 worldZ 同向
        axis_z = Vu
        if rg.Vector3d.Multiply(axis_z, worldZ) < 0:
            axis_z *= -1

        axis_x.Unitize()
        axis_y.Unitize()
        axis_z.Unitize()

        self.log(
            "AxisX(Forward)=({:.3f},{:.3f},{:.3f})".format(
                axis_x.X, axis_x.Y, axis_x.Z
            )
        )
        self.log(
            "AxisY(Left)   =({:.3f},{:.3f},{:.3f})".format(
                axis_y.X, axis_y.Y, axis_y.Z
            )
        )
        self.log(
            "AxisZ(Up)     =({:.3f},{:.3f},{:.3f})".format(
                axis_z.X, axis_z.Y, axis_z.Z
            )
        )

        return axis_x, axis_y, axis_z

    # ----------------------------------------------------------------------
    # 主函数：从 Box 或 Brep 提取所有特征
    # ----------------------------------------------------------------------
    def extract(self, timber):

        self._log = []
        self.log("== TimberBox Up–Forward–Left 计算开始 ==")

        # 转为 Brep
        if isinstance(timber, rg.Box):
            brep = timber.ToBrep()
            pts = list(timber.GetCorners())
        elif isinstance(timber, rg.Brep):
            brep = timber
            pts = [v.Location for v in brep.Vertices]
        else:
            raise TypeError("输入必须是 Box 或 Brep")

        P0 = self._get_corner0(brep)
        dirs = self._neighbor_edge_dirs(brep, P0)
        axis_x, axis_y, axis_z = self._stable_axes(dirs)

        # LocalAxesPlane（以 Corner0 为原点）
        local_axes_plane = rg.Plane(P0, axis_x, axis_y)

        # CenterPoint：顶点平均
        cx = sum(p.X for p in pts) / len(pts)
        cy = sum(p.Y for p in pts) / len(pts)
        cz = sum(p.Z for p in pts) / len(pts)
        center = rg.Point3d(cx, cy, cz)

        # 半长 hx, hy, hz
        hx = hy = hz = 0
        for p in pts:
            v = p - center
            hx = max(hx, abs(rg.Vector3d.Multiply(v, axis_x)))
            hy = max(hy, abs(rg.Vector3d.Multiply(v, axis_y)))
            hz = max(hz, abs(rg.Vector3d.Multiply(v, axis_z)))

        center_axes = [
            rg.Line(center, center + axis_x * hx),
            rg.Line(center, center - axis_x * hx),
            rg.Line(center, center + axis_y * hy),
            rg.Line(center, center - axis_y * hy),
            rg.Line(center, center + axis_z * hz),
            rg.Line(center, center - axis_z * hz),
        ]

        # Edge 列表及中点
        EdgeList = [e.DuplicateCurve() for e in brep.Edges]
        EdgeMid = []
        for cr in EdgeList:
            t = cr.Domain.ParameterAt(0.5)
            EdgeMid.append(cr.PointAt(t))

        # Face planes + tags
        FaceList = [f for f in brep.Faces]
        FacePlaneList = []
        FaceDirTags = []
        axes = [axis_x, axis_y, axis_z]

        for face in FaceList:
            fb = face.DuplicateFace(True)
            amp = rg.AreaMassProperties.Compute(fb)
            if amp:
                fc = amp.Centroid
            else:
                fc = fb.GetBoundingBox(True).Center

            udom = face.Domain(0)
            vdom = face.Domain(1)
            nf = face.NormalAt(
                (udom.T0 + udom.T1) / 2.0, (vdom.T0 + vdom.T1) / 2.0
            )
            nf.Unitize()

            dots = [rg.Vector3d.Multiply(nf, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1

            # 标签
            FaceDirTags.append(self._axis_tag(idx, sign))

            # 余下两个轴为平面 X/Y
            rem = [0, 1, 2]
            rem.remove(idx)
            xax = rg.Vector3d(axes[rem[0]])
            xax.Unitize()
            yax = rg.Vector3d(axes[rem[1]])
            yax.Unitize()

            pl = rg.Plane(fc, xax, yax)
            if rg.Vector3d.Multiply(pl.ZAxis, axes[idx] * sign) < 0:
                pl.Flip()
            FacePlaneList.append(pl)

        # Edge tags
        EdgeDirTags = []
        for cr in EdgeList:
            v = cr.PointAtEnd - cr.PointAtStart
            dots = [rg.Vector3d.Multiply(v, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1
            EdgeDirTags.append(self._axis_tag(idx, sign))

        # Corner0 三种局部平面
        Corner0Planes = [
            rg.Plane(P0, axis_x, axis_y),
            rg.Plane(P0, axis_x, axis_z),
            rg.Plane(P0, axis_y, axis_z),
        ]

        return (
            FaceList,
            pts,
            EdgeList,
            center,
            center_axes,
            EdgeMid,
            FacePlaneList,
            Corner0Planes,
            local_axes_plane,
            axis_x,
            axis_y,
            axis_z,
            FaceDirTags,
            EdgeDirTags,
            dirs,
        )


def _canonicalize_corner0_outputs(corner0_origin, base_plane, corner0_dirs):
    """
    Reorder Corner0 outputs by the construction plane axes instead of Brep edge
    enumeration order, so the list stays stable when the reference plane rotates.
    """
    target_axes = [
        rg.Vector3d(base_plane.XAxis),
        rg.Vector3d(base_plane.YAxis),
        rg.Vector3d(base_plane.ZAxis),
    ]
    for axis in target_axes:
        axis.Unitize()

    remaining = list(corner0_dirs or [])
    ordered_dirs = []

    for axis in target_axes:
        if not remaining:
            break

        best_idx = max(
            range(len(remaining)),
            key=lambda i: abs(rg.Vector3d.Multiply(remaining[i], axis)),
        )
        direction = rg.Vector3d(remaining.pop(best_idx))
        if rg.Vector3d.Multiply(direction, axis) < 0:
            direction.Reverse()
        direction.Unitize()
        ordered_dirs.append(direction)

    if len(ordered_dirs) != 3:
        return [], []

    corner0_planes = [
        rg.Plane(corner0_origin, ordered_dirs[0], ordered_dirs[1]),
        rg.Plane(corner0_origin, ordered_dirs[0], ordered_dirs[2]),
        rg.Plane(corner0_origin, ordered_dirs[1], ordered_dirs[2]),
    ]

    return corner0_planes, ordered_dirs


def _unitized_copy(vector):
    result = rg.Vector3d(vector)
    result.Unitize()
    return result


def _local_components(point, origin, axes):
    vec = point - origin
    return tuple(rg.Vector3d.Multiply(vec, axis) for axis in axes)


def _axis_tag_from_vector(vector, axes):
    dots = [rg.Vector3d.Multiply(vector, axis) for axis in axes]
    absd = [abs(value) for value in dots]
    idx = absd.index(max(absd))
    sign = 1 if dots[idx] >= 0 else -1
    return ["+X", "-X", "+Y", "-Y", "+Z", "-Z"][(idx * 2) + (0 if sign >= 0 else 1)]


def _reversed_copy(vector):
    result = rg.Vector3d(vector)
    result.Reverse()
    return result


def _build_canonical_box_outputs(
    timber_brep,
    base_point,
    base_plane,
    length_fen,
    height_fen,
    width_fen,
):
    axis_x = _unitized_copy(base_plane.XAxis)
    axis_y = _unitized_copy(base_plane.YAxis)
    axis_z = _unitized_copy(base_plane.ZAxis)
    axes = [axis_x, axis_y, axis_z]

    point_list = [
        base_point,
        base_point + axis_x * length_fen,
        base_point + axis_x * length_fen + axis_y * height_fen,
        base_point + axis_y * height_fen,
        base_point + axis_z * width_fen,
        base_point + axis_x * length_fen + axis_z * width_fen,
        base_point + axis_x * length_fen + axis_y * height_fen + axis_z * width_fen,
        base_point + axis_y * height_fen + axis_z * width_fen,
    ]

    center_point = (
        base_point
        + axis_x * (length_fen * 0.5)
        + axis_y * (height_fen * 0.5)
        + axis_z * (width_fen * 0.5)
    )

    center_axis_lines = [
        rg.Line(center_point, center_point + axis_x * (length_fen * 0.5)),
        rg.Line(center_point, center_point - axis_x * (length_fen * 0.5)),
        rg.Line(center_point, center_point + axis_y * (height_fen * 0.5)),
        rg.Line(center_point, center_point - axis_y * (height_fen * 0.5)),
        rg.Line(center_point, center_point + axis_z * (width_fen * 0.5)),
        rg.Line(center_point, center_point - axis_z * (width_fen * 0.5)),
    ]

    edge_specs = [
        (0, 1), (3, 2), (4, 5), (7, 6),
        (0, 3), (1, 2), (4, 7), (5, 6),
        (0, 4), (1, 5), (3, 7), (2, 6),
    ]
    edge_list = []
    edge_mid_points = []
    edge_dir_tags = []
    for start_idx, end_idx in edge_specs:
        curve = rg.LineCurve(point_list[start_idx], point_list[end_idx])
        edge_list.append(curve)
        edge_mid_points.append(curve.PointAtNormalizedLength(0.5))
        edge_dir_tags.append(_axis_tag_from_vector(
            point_list[end_idx] - point_list[start_idx],
            axes,
        ))

    face_axis_map = {
        "+X": (axis_y, axis_z),
        "-X": (axis_y, axis_z),
        "+Y": (axis_x, axis_z),
        "-Y": (axis_x, axis_z),
        "+Z": (axis_x, axis_y),
        "-Z": (axis_x, axis_y),
    }
    face_tag_order = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    face_infos = []
    for face in timber_brep.Faces:
        face_brep = face.DuplicateFace(True)
        amp = rg.AreaMassProperties.Compute(face_brep)
        centroid = amp.Centroid if amp else face_brep.GetBoundingBox(True).Center
        udom = face.Domain(0)
        vdom = face.Domain(1)
        normal = face.NormalAt(
            (udom.T0 + udom.T1) / 2.0,
            (vdom.T0 + vdom.T1) / 2.0,
        )
        normal.Unitize()
        tag = _axis_tag_from_vector(normal, axes)
        plane_x, plane_y = face_axis_map[tag]
        plane = rg.Plane(centroid, plane_x, plane_y)
        target_normal = {
            "+X": axis_x,
            "-X": _reversed_copy(axis_x),
            "+Y": axis_y,
            "-Y": _reversed_copy(axis_y),
            "+Z": axis_z,
            "-Z": _reversed_copy(axis_z),
        }[tag]
        if rg.Vector3d.Multiply(plane.ZAxis, target_normal) < 0:
            plane.Flip()
        face_infos.append((tag, face, plane))

    tag_rank = {tag: idx for idx, tag in enumerate(face_tag_order)}
    face_infos.sort(key=lambda item: tag_rank[item[0]])
    face_list = [item[1] for item in face_infos]
    face_plane_list = [item[2] for item in face_infos]
    face_dir_tags = [item[0] for item in face_infos]

    local_axes_plane = rg.Plane(base_point, axis_x, axis_y)
    corner0_dirs = [axis_x, axis_y, axis_z]
    corner0_planes = [
        rg.Plane(base_point, axis_x, axis_y),
        rg.Plane(base_point, axis_x, axis_z),
        rg.Plane(base_point, axis_y, axis_z),
    ]

    return (
        face_list,
        point_list,
        edge_list,
        center_point,
        center_axis_lines,
        edge_mid_points,
        face_plane_list,
        corner0_planes,
        local_axes_plane,
        axis_x,
        axis_y,
        axis_z,
        face_dir_tags,
        edge_dir_tags,
        corner0_dirs,
    )


# =========================================================
# 方材构造 + 统一特征提取
# =========================================================

def build_timber_block_uniform(length_fen, width_fen, height_fen, base_point, reference_plane=None):
    """
    构建一个用于加工的木料长方体，并使用 FT_TimberBoxFeatures
    统一计算特征，保证与 FT_TimberBoxFeatures 组件输出一致。
    """

    # 1. 确定参考平面
    if reference_plane is None:
        world_x = rg.Vector3d(1, 0, 0)
        world_z = rg.Vector3d(0, 0, 1)
        base_plane = rg.Plane(base_point, world_x, world_z)
    else:
        base_plane = rg.Plane(reference_plane)
        base_plane.Origin = base_point

    # 2. 在该平面下建立 Box
    # 这里仍然按照你原来的 fen 方向定义：
    #   X: length_fen
    #   Y: height_fen
    #   Z: width_fen
    x_interval = rg.Interval(0.0, length_fen)
    y_interval = rg.Interval(0.0, height_fen)
    z_interval = rg.Interval(0.0, width_fen)

    box = rg.Box(base_plane, x_interval, y_interval, z_interval)
    timber_brep = box.ToBrep()

    # 3. 用“标准版”特征提取（与 FT_TimberBoxFeatures 组件相同）
    fx = FT_TimberBoxFeatures()
    fx.extract(timber_brep)

    (
        FaceList,
        PointList,
        EdgeList,
        CenterPoint,
        CenterAxisLines,
        EdgeMidPoints,
        FacePlaneList,
        Corner0Planes,
        LocalAxesPlane,
        AxisX,
        AxisY,
        AxisZ,
        FaceDirTags,
        EdgeDirTags,
        Corner0EdgeDirs,
    ) = _build_canonical_box_outputs(
        timber_brep,
        base_point,
        base_plane,
        length_fen,
        height_fen,
        width_fen,
    )

    Log = fx.log_lines

    return (
        timber_brep,
        FaceList,
        PointList,
        EdgeList,
        CenterPoint,
        CenterAxisLines,
        EdgeMidPoints,
        FacePlaneList,
        Corner0Planes,
        LocalAxesPlane,
        AxisX,
        AxisY,
        AxisZ,
        FaceDirTags,
        EdgeDirTags,
        Corner0EdgeDirs,
        Log,
    )

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

        # 输出到 Grasshopper —— 与 FT_TimberBoxFeatures 保持一致命名
        TimberBrep      = timber_brep
        FaceList        = faces
        PointList       = points
        EdgeList        = edges
        CenterPoint     = center_pt
        CenterAxisLines = center_axes
        EdgeMidPoints   = edge_midpts
        FacePlaneList   = face_planes
        Corner0Planes   = corner0_planes
        LocalAxesPlane  = local_axes_plane
        AxisX           = axis_x
        AxisY           = axis_y
        AxisZ           = axis_z
        FaceDirTags     = face_tags
        EdgeDirTags     = edge_tags
        Corner0EdgeDirs = corner0_dirs
        Log             = log_lines

    except Exception as e:
        # 发生错误时，清空几何输出，Log 输出错误信息
        TimberBrep      = None
        FaceList        = []
        PointList       = []
        EdgeList        = []
        CenterPoint     = None
        CenterAxisLines = []
        EdgeMidPoints   = []
        FacePlaneList   = []
        Corner0Planes   = []
        LocalAxesPlane  = None
        AxisX           = None
        AxisY           = None
        AxisZ           = None
        FaceDirTags     = []
        EdgeDirTags     = []
        Corner0EdgeDirs = []
        Log             = ["错误: {}".format(e)]

# -*- coding: utf-8 -*-
"""
BuildTimberBlockUniform_SkewAxis
================================
方材统一构造 + Skew（斜移）参考平面与控制点构造
"""

import Rhino.Geometry as rg


# ---------------------------------------------------------
# GH 默认参考平面（按 Grasshopper 约定的坐标轴定义）
# XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
# XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
# YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
# ---------------------------------------------------------
def gh_plane_XZ(origin):
    """Grasshopper 的 XZ Plane（按约定轴向）"""
    x = rg.Vector3d(1, 0, 0)
    y = rg.Vector3d(0, 0, 1)
    pl = rg.Plane(origin, x, y)
    return pl


# =========================================================
# 与 FT_TimberBoxFeatures 完全一致的特征提取类
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

    def _get_corner0(self, brep):
        if brep.Vertices.Count == 0:
            raise ValueError("Brep 无顶点")
        return brep.Vertices[0].Location

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
            raise ValueError("Corner0 未找到 3 条邻边")
        return dirs

    def _stable_axes(self, dirs):
        axes = [rg.Vector3d(d) for d in dirs]
        for a in axes:
            a.Unitize()
        return axes

    def extract(self, timber):
        self._log = []
        self.log("== TimberBox 特征提取 ==")

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
        axes = self._stable_axes(dirs)

        axis_x, axis_y, axis_z = axes
        local_axes_plane = rg.Plane(P0, axis_x, axis_y)

        cx = sum(p.X for p in pts) / len(pts)
        cy = sum(p.Y for p in pts) / len(pts)
        cz = sum(p.Z for p in pts) / len(pts)
        center = rg.Point3d(cx, cy, cz)

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

        EdgeList = [e.DuplicateCurve() for e in brep.Edges]
        EdgeMid = []
        for cr in EdgeList:
            t = cr.Domain.ParameterAt(0.5)
            EdgeMid.append(cr.PointAt(t))

        FaceList = []
        FacePlaneList = []
        FaceDirTags = []

        for face in brep.Faces:
            fb = face.DuplicateFace(True)
            amp = rg.AreaMassProperties.Compute(fb)
            fc = amp.Centroid if amp else fb.GetBoundingBox(True).Center

            udom = face.Domain(0)
            vdom = face.Domain(1)
            nf = face.NormalAt(
                (udom.T0 + udom.T1) / 2.0,
                (vdom.T0 + vdom.T1) / 2.0,
            )
            nf.Unitize()

            dots = [rg.Vector3d.Multiply(nf, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1

            FaceDirTags.append(self._axis_tag(idx, sign))

            rem = [0, 1, 2]
            rem.remove(idx)
            xax = rg.Vector3d(axes[rem[0]])
            yax = rg.Vector3d(axes[rem[1]])
            xax.Unitize()
            yax.Unitize()

            FacePlaneList.append(rg.Plane(fc, xax, yax))
            FaceList.append(fb)

        EdgeDirTags = []
        for cr in EdgeList:
            tan = cr.TangentAt(cr.Domain.Mid)
            tan.Unitize()
            dots = [rg.Vector3d.Multiply(tan, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1
            EdgeDirTags.append(self._axis_tag(idx, sign))

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


# =========================================================
# 方案 A：对象化 Builder（Skew 版本）
# =========================================================
class BuildTimberBlockUniform_SkewAxis(object):

    def __init__(
        self,
        length_fen,
        width_fen,
        height_fen,
        base_point,
        reference_plane=None,
        Skew_len=20.0,
    ):
        self.length_fen = float(length_fen)
        self.width_fen = float(width_fen)
        self.height_fen = float(height_fen)
        self.Skew_len = float(Skew_len)

        if base_point is None:
            base_point = rg.Point3d(0, 0, 0)
        elif isinstance(base_point, rg.Point):
            base_point = base_point.Location
        self.base_point = base_point

        self.reference_plane = reference_plane
        self._solve()

    def _solve(self):
        try:
            # ---- 基准参考平面 ----
            if self.reference_plane is None:
                base_plane = gh_plane_XZ(self.base_point)
            else:
                base_plane = rg.Plane(self.reference_plane)
                base_plane.Origin = self.base_point

            # ---- Box ----
            box = rg.Box(
                base_plane,
                rg.Interval(0, self.length_fen),
                rg.Interval(0, self.height_fen),
                rg.Interval(0, self.width_fen),
            )
            timber_brep = box.ToBrep()

            # ---- 特征 ----
            ft = FT_TimberBoxFeatures()
            (
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
            ) = ft.extract(timber_brep)

            # ---- Skew 构造 ----
            Skew_A = self.base_point + base_plane.ZAxis * (self.width_fen * 0.5)
            Skew_Point_B = Skew_A + base_plane.XAxis * self.Skew_len
            Skew_Point_C = Skew_Point_B + base_plane.YAxis * self.height_fen

            pl_B = rg.Plane(base_plane)
            pl_B.Origin = Skew_Point_B
            pl_B_X = rg.Plane(Skew_Point_B, pl_B.XAxis, pl_B.ZAxis)
            pl_B_Y = rg.Plane(Skew_Point_B, pl_B.YAxis, pl_B.ZAxis)
            Skew_Planes = [pl_B, pl_B_X, pl_B_Y]

            x_dir = base_plane.XAxis
            y_dir = base_plane.YAxis
            z_dir = base_plane.ZAxis

            P00 = base_plane.Origin
            P01 = base_plane.Origin + z_dir * self.width_fen
            P11 = base_plane.Origin + y_dir * self.height_fen + z_dir * self.width_fen
            P10 = base_plane.Origin + y_dir * self.height_fen

            G = P00 + x_dir * self.Skew_len
            F = P01 + x_dir * self.Skew_len
            E = P11 + x_dir * self.Skew_len
            H = P10 + x_dir * self.Skew_len

            # ---- 输出 ----
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
            self.Log = ft.log_lines

            self.Skew_A = Skew_A
            self.Skew_Point_B = Skew_Point_B
            self.Skew_Point_C = Skew_Point_C
            self.Skew_Planes = Skew_Planes
            self.Skew_ExtraPoints_GF_EH = [G, F, E, H]

        except Exception as e:
            self.TimberBrep = None
            self.Log = ["错误: {}".format(e)]

if __name__ == "__main__":
    # =========================================================
    # GhPython 主入口
    # =========================================================
    if __name__ == "__main__":

        if length_fen is None:
            length_fen = 32.0
        if width_fen is None:
            width_fen = 32.0
        if height_fen is None:
            height_fen = 20.0
        if Skew_len is None:
            Skew_len = 20.0

        if base_point is None:
            base_point = rg.Point3d(0, 0, 0)
        elif isinstance(base_point, rg.Point):
            base_point = base_point.Location

        if reference_plane is None:
            reference_plane = gh_plane_XZ(base_point)

        try:
            _obj = BuildTimberBlockUniform_SkewAxis(
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
                Skew_len,
            )

            TimberBrep = _obj.TimberBrep
            FaceList = _obj.FaceList
            PointList = _obj.PointList
            EdgeList = _obj.EdgeList
            CenterPoint = _obj.CenterPoint
            CenterAxisLines = _obj.CenterAxisLines
            EdgeMidPoints = _obj.EdgeMidPoints
            FacePlaneList = _obj.FacePlaneList
            Corner0Planes = _obj.Corner0Planes
            LocalAxesPlane = _obj.LocalAxesPlane
            AxisX = _obj.AxisX
            AxisY = _obj.AxisY
            AxisZ = _obj.AxisZ
            FaceDirTags = _obj.FaceDirTags
            EdgeDirTags = _obj.EdgeDirTags
            Corner0EdgeDirs = _obj.Corner0EdgeDirs
            Log = _obj.Log

            Skew_A = _obj.Skew_A
            Skew_Point_B = _obj.Skew_Point_B
            Skew_Point_C = _obj.Skew_Point_C
            Skew_Planes = _obj.Skew_Planes
            Skew_ExtraPoints_GF_EH = _obj.Skew_ExtraPoints_GF_EH

        except Exception as e:
            TimberBrep = None
            Log = ["主逻辑错误: {}".format(e)]

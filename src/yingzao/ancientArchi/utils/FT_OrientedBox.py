# -*- coding: utf-8 -*-
"""
GhPython 组件：按两种方法生成紧贴外接立方体（OOBB）

输入（GhPython 组件）:
    Geo    : list[Any] 或单个几何
        输入的任意几何体对象（或对象列表），可包含：
        - Point / Point3d
        - Curve / PolylineCurve
        - Surface
        - Brep
        - Mesh
        - Extrusion
        - SubD
        - Guid（从 Rhino 里引用的对象）
        组件会自动将复杂对象炸开 / 网格化，提取所有可用于包围盒的点。

    Method : str | int | None
        外接立方体求解方法：
        - "pca" / "PCA" / 0  : 纯 PCA 主轴方法
        - "face" / "normal" / 1 / "B" : BrepFace Normal 法
        为空或其它时，默认使用 "pca"。

输出:
    OOBB_Box      : rg.Box | None
        最终选定方法得到的紧贴外接立方体 Box 对象
        （包含 Plane 和三方向 Interval）。

    Plane         : list[rg.Plane] | None
        3 个过外接立方体几何中心点的局部坐标参考平面：
        - Plane[0] : XY 平面（Z 为法向）
        - Plane[1] : XZ 平面（Y 为法向）
        - Plane[2] : YZ 平面（X 为法向）
        其中 X/Y/Z 均为外接立方体的局部轴向。

    Corners       : list[rg.Point3d] | None
        外接立方体的 8 个顶点，顺序为：
        [0,1,2,3] = 底面四点（逆时针）
        [4,5,6,7] = 顶面四点（逆时针）

    Edges         : list[rg.Curve] | None
        12 条边线，每条为 Line 的 NurbsCurve：
        (0-1),(1-2),(2-3),(3-0)
        (4-5),(5-6),(6-7),(7-4)
        (0-4),(1-5),(2-6),(3-7)

    EdgeMidPoints : list[rg.Point3d] | None
        12 条边线的中点列表，顺序与 Edges 对应。

    FaceCenters   : list[rg.Point3d] | None
        6 个面的几何中心点（四角点平均，位于面上，按 FacePlanes 顺序）。

    FacePlanes    : list[rg.Plane] | None
        6 个面的参考平面：
        - 原点为对应面的几何中心点
        - X/Y 轴由该面的两条边向量定义
        顺序对应于：
        [bottom, top, side1, side2, side3, side4]

    Dims          : tuple[float, float, float] | None
        外接盒的长宽高（沿局部 X/Y/Z 方向的尺寸，来自 Box.X/Y/Z.Length）。

    Log           : list[str] | None
        运行日志，用于调试。
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import System
import math
import numpy as np


# ============================================================
# 面向对象封装：FT_OrientedBox
# ============================================================

class FT_OrientedBox(object):
    """
    用于计算紧贴几何体的外接立方体（OOBB）的工具类，支持两种方法：
        - PCA：按点云主轴方向构造 Box
        - FaceNormal：用 Brep 面法向作为候选 Z 轴，再选体积最小的 Box

    调用示例（GhPython 内）:
        builder = FT_OrientedBox(Geo, Method)
        box, planes, corners, edges, edge_mids, face_centers, face_planes, dims, log = builder.build()
    """

    # ------------------ 构造 & 配置 ------------------

    def __init__(self, geos, method=None, face_angle_tol_deg=10.0):
        self.geos_raw = geos
        self.method_raw = method
        self.face_angle_tol_deg = face_angle_tol_deg

        # 运行中产生的数据
        self.log = []
        self.geos = []        # 标准化后的几何列表
        self.all_pts = []     # 所有采样点
        self.method = "pca"   # 最终采用的方法（"pca" 或 "face"）

        # PCA 结果
        self.center = None
        self.pca_x = None
        self.pca_y = None
        self.pca_z = None

    # ------------------ 公共主入口 ------------------

    def build(self):
        """主入口：执行全部步骤，返回各输出。"""

        # 1) 规范化输入 & 收集点
        if not self._prepare_geometry_and_points():
            return None, None, None, None, None, None, None, None, self.log

        # 2) PCA 计算主轴
        if not self._compute_pca_axes():
            return None, None, None, None, None, None, None, None, self.log

        # 3) 根据方法构造 Box
        box, _ = self._build_box_by_method()
        if box is None or (hasattr(box, "IsValid") and not box.IsValid):
            self.log.append("❌ 最终 Box 无效。")
            return None, None, None, None, None, None, None, None, self.log

        # 4) 从 Box 解析其他输出
        planes, corners, edges, edge_mids, face_centers, face_planes, dims = self._extract_box_outputs(box)

        return box, planes, corners, edges, edge_mids, face_centers, face_planes, dims, self.log

    # ============================================================
    # 步骤 1：几何 & 点预处理
    # ============================================================

    def _normalize_method(self):
        """把外部传入的 Method 规范为 'pca' 或 'face'"""
        m = "pca"
        method = self.method_raw

        if isinstance(method, str):
            s = method.strip().lower()
            if s in ("pca",):
                m = "pca"
            elif s in ("face", "normal", "brep", "b"):
                m = "face"
        elif isinstance(method, (int, float)):
            if int(method) == 1:
                m = "face"
            else:
                m = "pca"

        self.method = m
        self.log.append("当前外接盒方法 = {0}".format(m.upper()))

    def _prepare_geometry_and_points(self):
        """统一处理 Geo 输入，并提取所有点。"""

        self._normalize_method()

        geos = self.geos_raw
        if geos is None:
            self.log.append("⚠ Geo 输入为 None。")
            return False

        if not isinstance(geos, (list, tuple)):
            geos = [geos]

        if len(geos) == 0:
            self.log.append("⚠ Geo 列表为空。")
            return False

        self.geos = geos

        for g in geos:
            g2 = self._coerce_geometry(g)
            if g2 is None:
                continue

            try:
                pts = self._extract_points(g2)
                self.all_pts.extend(pts)
                self.log.append("提取点 {0} 个：{1}".format(len(pts), type(g2)))
            except Exception as e:
                self.log.append("❌ 提取失败：{0} | {1}".format(type(g2), e))

        if len(self.all_pts) < 3:
            self.log.append("❌ 点太少（{0} 个），无法生成 OOBB。".format(len(self.all_pts)))
            return False

        return True

    # ---- Guid 转 Geometry ----
    def _coerce_geometry(self, obj):
        """如果是 Guid，则从当前 doc 里找到真实几何"""
        if isinstance(obj, System.Guid):
            rh_obj = sc.doc.Objects.FindId(obj)
            if rh_obj is None:
                self.log.append("⚠ Guid 在文档中未找到：{0}".format(obj))
                return None
            return rh_obj.Geometry
        return obj

    # ---- 提取各种几何的点 ----
    def _extract_points(self, obj):
        """
        从任意几何对象提取点（含自动炸开和网格化），
        返回 list[rg.Point3d]
        """
        pts = []

        # Point3d
        if isinstance(obj, rg.Point3d):
            pts.append(obj)
            return pts

        # GH Point
        if isinstance(obj, rg.Point):
            pts.append(obj.Location)
            return pts

        # Curve
        if isinstance(obj, rg.Curve):
            t_list = obj.DivideByCount(100, True)
            if t_list:
                pts.extend([obj.PointAt(t) for t in t_list])
            return pts

        # Surface
        if isinstance(obj, rg.Surface):
            mesh = rg.Mesh.CreateFromSurface(obj)
            if mesh:
                for i in range(mesh.Vertices.Count):
                    v = mesh.Vertices[i]
                    pts.append(rg.Point3d(v.X, v.Y, v.Z))
            return pts

        # Mesh
        if isinstance(obj, rg.Mesh):
            for i in range(obj.Vertices.Count):
                v = obj.Vertices[i]
                pts.append(rg.Point3d(v.X, v.Y, v.Z))
            return pts

        # Brep
        if isinstance(obj, rg.Brep):
            meshes = rg.Mesh.CreateFromBrep(obj, rg.MeshingParameters.Default)
            if meshes:
                for m in meshes:
                    for i in range(m.Vertices.Count):
                        v = m.Vertices[i]
                        pts.append(rg.Point3d(v.X, v.Y, v.Z))
            return pts

        # Extrusion → Brep
        if isinstance(obj, rg.Extrusion):
            brep = obj.ToBrep()
            if brep:
                return self._extract_points(brep)
            return pts

        # SubD → Mesh
        if isinstance(obj, rg.SubD):
            mesh = rg.Mesh.CreateFromSubD(obj)
            if mesh:
                for i in range(mesh.Vertices.Count):
                    v = mesh.Vertices[i]
                    pts.append(rg.Point3d(v.X, v.Y, v.Z))
            return pts

        self.log.append("⚠ 未处理的几何类型：{0}".format(type(obj)))
        return pts

    # ============================================================
    # 步骤 2：PCA 主轴
    # ============================================================

    def _compute_pca_axes(self):
        """对 all_pts 做 PCA，得到中心与 3 个主轴"""

        pts = self.all_pts
        if len(pts) < 3:
            self.log.append("❌ 点数不足，无法 PCA。")
            return False

        arr = np.array([[p.X, p.Y, p.Z] for p in pts], dtype=float)

        mean = arr.mean(axis=0)
        arr_centered = arr - mean

        # SVD：arr_centered = U * S * Vt
        try:
            U, S, Vt = np.linalg.svd(arr_centered, full_matrices=False)
        except Exception as e:
            self.log.append("❌ PCA (SVD) 异常：{0}".format(e))
            return False

        V = Vt.T

        vx = V[:, 0]
        vy = V[:, 1]
        vz = V[:, 2]

        XAxis = rg.Vector3d(vx[0], vx[1], vx[2])
        YAxis = rg.Vector3d(vy[0], vy[1], vy[2])
        ZAxis = rg.Vector3d(vz[0], vz[1], vz[2])
        XAxis.Unitize()
        YAxis.Unitize()
        ZAxis.Unitize()

        center = rg.Point3d(mean[0], mean[1], mean[2])

        self.center = center
        self.pca_x = XAxis
        self.pca_y = YAxis
        self.pca_z = ZAxis

        self.log.append("✔ PCA 主轴：X={0}, Y={1}, Z={2}".format(XAxis, YAxis, ZAxis))
        return True

    # ============================================================
    # 步骤 3：根据方法构造 Box
    # ============================================================

    def _build_box_by_method(self):
        """根据 self.method 构造 Box，并返回 (box, plane)"""

        if self.method == "pca":
            return self._build_box_pca()
        else:
            return self._build_box_face_normal()

    # ---- 3.1 纯 PCA 方法 ----
    def _build_box_pca(self):
        plane = rg.Plane(self.center, self.pca_x, self.pca_y)
        try:
            box = rg.Box(plane, self.all_pts)
        except Exception as e:
            self.log.append("❌ Box(plane, points) 失败：{0}".format(e))
            return None, None

        if not box.IsValid:
            self.log.append("❌ PCA 生成的 Box 无效。")
            return None, None

        lx = box.X.Length
        ly = box.Y.Length
        lz = box.Z.Length
        vol = lx * ly * lz
        self.log.append("✔ PCA Box 体积 = {0:.3f}".format(vol))

        return box, plane

    # ---- 3.2 Brep Face Normal 方法 ----

    def _collect_face_normals(self):
        """
        从所有 Brep / Extrusion 中提取近似平面面的法线，
        聚类得到若干唯一方向。
        """
        normals = []
        angle_tol = math.radians(self.face_angle_tol_deg)

        for g in self.geos:
            g2 = self._coerce_geometry(g)
            if g2 is None:
                continue

            brep = None
            if isinstance(g2, rg.Brep):
                brep = g2
            elif isinstance(g2, rg.Extrusion):
                brep = g2.ToBrep()

            if brep is None:
                continue

            for f in brep.Faces:
                try:
                    ok, pl = f.TryGetPlane()
                except:
                    ok = False
                    pl = None
                if not ok or pl is None:
                    continue
                n = pl.Normal
                if n.IsZero:
                    continue
                n.Unitize()
                normals.append(n)

        if not normals:
            self.log.append("⚠ 未从 Brep 面中提取到任何法线，无法使用 FaceNormal 法。")
            return []

        unique_dirs = []

        for n in normals:
            merged = False
            for i, d in enumerate(unique_dirs):
                angle = rg.Vector3d.VectorAngle(n, d)
                if angle < angle_tol or abs(angle - math.pi) < angle_tol:
                    tmp = rg.Vector3d(d)
                    tmp += n
                    if not tmp.IsZero:
                        tmp.Unitize()
                        unique_dirs[i] = tmp
                    merged = True
                    break
            if not merged:
                unique_dirs.append(rg.Vector3d(n))

        self.log.append("✔ 从 Brep 面提取到主要法线方向 {0} 个".format(len(unique_dirs)))
        return unique_dirs

    def _project_to_plane(self, v, n):
        """把向量 v 投影到法线为 n 的平面内"""
        v2 = rg.Vector3d(v)
        dot = rg.Vector3d.Multiply(v2, n)
        v2 -= n * dot
        return v2

    def _build_box_with_normal(self, normal):
        """
        给定一个候选法线 normal：
            - 用 PCA 的主轴在该法平面内求 X/Y
            - 构造 Plane(center, X, Y)
            - 用 Box(plane, all_pts) 求对应外接盒
        返回 (box, volume) 或 (None, None)
        """
        n = rg.Vector3d(normal)
        if n.IsZero:
            return None, None
        n.Unitize()

        # 在 normal 所在平面内投影 PCA 轴
        x = self._project_to_plane(self.pca_x, n)
        if x.IsZero or x.Length < 1e-6:
            x = self._project_to_plane(self.pca_y, n)

        if x.IsZero or x.Length < 1e-6:
            x = rg.Vector3d(1, 0, 0)
            if abs(rg.Vector3d.Multiply(x, n)) > 0.9:
                x = rg.Vector3d(0, 1, 0)

        x.Unitize()
        y = rg.Vector3d.CrossProduct(n, x)
        if y.IsZero:
            return None, None
        y.Unitize()

        plane = rg.Plane(self.center, x, y)

        try:
            box = rg.Box(plane, self.all_pts)
        except Exception as e:
            self.log.append("❌ Box(plane, points) 失败：{0}".format(e))
            return None, None

        if not box.IsValid:
            return None, None

        lx = box.X.Length
        ly = box.Y.Length
        lz = box.Z.Length
        volume = lx * ly * lz
        return box, volume

    def _build_box_face_normal(self):
        """FaceNormal 方法：遍历候选法线方向，选体积最小的 Box"""

        normals = self._collect_face_normals()
        if not normals:
            self.log.append("⚠ 无法获取面法线，退回 PCA 方法。")
            return self._build_box_pca()

        best_box = None
        best_plane = None
        best_vol = None
        candidate_count = 0

        for n in normals:
            box, vol = self._build_box_with_normal(n)
            if box is None:
                continue
            candidate_count += 1
            if best_box is None or vol < best_vol:
                best_box = box
                best_plane = box.Plane
                best_vol = vol

        self.log.append("✔ FaceNormal 候选方向数量 = {0}".format(candidate_count))
        if best_box is not None:
            self.log.append("✔ FaceNormal 最优 Box 体积 = {0:.3f}".format(best_vol))
            return best_box, best_plane

        self.log.append("❌ 所有 FaceNormal 候选都失败，退回 PCA。")
        return self._build_box_pca()

    # ============================================================
    # 步骤 4：从 Box 解析其他输出
    # ============================================================

    def _extract_box_outputs(self, box):
        """
        从 Box 生成：
        - 3 个局部坐标参考平面（XY/XZ/YZ）
        - 8 个角点
        - 12 条边线 + 中点
        - 6 个面的几何中心点 + 面参考平面
        - 尺寸
        """

        # 角点
        corners = list(box.GetCorners())

        # 盒子局部轴向（X/Y/Z）
        vx = corners[1] - corners[0]   # X 方向边
        vy = corners[3] - corners[0]   # Y 方向边
        vz = corners[4] - corners[0]   # Z 方向边

        vx_u = rg.Vector3d(vx)
        vy_u = rg.Vector3d(vy)
        vz_u = rg.Vector3d(vz)
        vx_u.Unitize()
        vy_u.Unitize()
        vz_u.Unitize()

        # 几何中心点（8 个角点平均）
        cx = sum(p.X for p in corners) / 8.0
        cy = sum(p.Y for p in corners) / 8.0
        cz = sum(p.Z for p in corners) / 8.0
        center = rg.Point3d(cx, cy, cz)

        # 3 个局部平面：XY, XZ, YZ
        plane_xy = rg.Plane(center, vx_u, vy_u)  # normal = Z
        plane_xz = rg.Plane(center, vx_u, vz_u)  # normal = Y
        plane_yz = rg.Plane(center, vy_u, vz_u)  # normal = X
        planes = [plane_xy, plane_xz, plane_yz]

        # 边线 + 中点
        edges = []
        edge_midpoints = []
        ci = corners

        edge_pairs = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)
        ]
        for a, b in edge_pairs:
            pa = ci[a]
            pb = ci[b]
            line = rg.Line(pa, pb)
            edges.append(line.ToNurbsCurve())
            mid = rg.Point3d((pa.X + pb.X) * 0.5,
                             (pa.Y + pb.Y) * 0.5,
                             (pa.Z + pb.Z) * 0.5)
            edge_midpoints.append(mid)

        # 面中心 + 面参考平面
        face_centers = []
        face_planes = []
        face_idx = [
            (0, 1, 2, 3),  # bottom
            (4, 5, 6, 7),  # top
            (0, 1, 5, 4),
            (2, 3, 7, 6),
            (0, 3, 7, 4),
            (1, 2, 6, 5)
        ]
        for ids in face_idx:
            p0 = ci[ids[0]]
            p1 = ci[ids[1]]
            p2 = ci[ids[2]]
            p3 = ci[ids[3]]

            # 面中心 = 四角点平均
            fc = rg.Point3d(
                (p0.X + p1.X + p2.X + p3.X) * 0.25,
                (p0.Y + p1.Y + p2.Y + p3.Y) * 0.25,
                (p0.Z + p1.Z + p2.Z + p3.Z) * 0.25
            )
            face_centers.append(fc)

            # 面参考平面：原点设为面中心，方向仍用 p1-p0, p3-p0
            x_dir = p1 - p0
            y_dir = p3 - p0
            pl = rg.Plane(fc, x_dir, y_dir)
            face_planes.append(pl)

        dims = (box.X.Length, box.Y.Length, box.Z.Length)

        return planes, corners, edges, edge_midpoints, face_centers, face_planes, dims

if __name__ == '__main__':
    # ============================================================
    # Grasshopper 脚本入口：调用类并解包输出
    # ============================================================

    OOBB_Box = None
    Plane = None
    Corners = None
    Edges = None
    EdgeMidPoints = None
    FaceCenters = None
    FacePlanes = None
    Dims = None
    Log = None

    try:
        builder = FT_OrientedBox(Geo, Method)
        (OOBB_Box,
         Plane,
         Corners,
         Edges,
         EdgeMidPoints,
         FaceCenters,
         FacePlanes,
         Dims,
         Log) = builder.build()
    except Exception as e:
        Log = ["组件运行异常: {0}".format(e)]

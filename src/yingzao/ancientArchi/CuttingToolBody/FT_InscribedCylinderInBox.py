# -*- coding: utf-8 -*-
"""InscribedCylinderInBoxWithFace

给定一个长方体几何，求取指定面的内接圆柱体：
- 圆柱底面圆位于指定面上，并与该矩形面内切
- 圆柱轴线垂直于该面，朝盒子内部伸展到对面
- 支持立方体和一般长方体（轴对齐）

输入（GhPython 组件里设置）:
    BoxGeo    : 长方体几何（Brep / Box / Extrusion / Mesh 等）
    FaceIndex : 指定圆截面所在的面 (int, 0~5)
                0: Z- 底面
                1: Z+ 顶面
                2: Y- 后面
                3: Y+ 前面
                4: X- 左侧
                5: X+ 右侧

输出:
    CylBrep    : 内接圆柱体 Brep
    Axis       : 圆柱轴线 Line
    BaseCircle : 底面圆 Circle
    Log        : list[str] 调试信息
"""

import Rhino.Geometry as rg


class InscribedCylinderInBox(object):
    """根据 BoundingBox 和指定面求内接圆柱。"""

    def __init__(self, geo, face_index=0):
        self.geo = geo
        self.face_index = int(face_index) if face_index is not None else 0
        self.bb = None
        self.log = []

    # ---------- 工具：取 BoundingBox ----------
    def _get_bounding_box(self):
        g = self.geo
        if g is None:
            return None

        if isinstance(g, rg.Brep):
            return g.GetBoundingBox(True)

        if isinstance(g, rg.Box):
            return g.BoundingBox

        if hasattr(g, "GetBoundingBox"):
            return g.GetBoundingBox(True)

        return None

    # ---------- 主计算 ----------
    def run(self):
        """
        执行计算，返回:
            (cyl_brep, axis_line, base_circle, log)
        失败时前三个为 None。
        """
        self.bb = self._get_bounding_box()
        if self.bb is None or (hasattr(self.bb, "IsValid") and not self.bb.IsValid):
            self.log.append("错误：输入几何无法获取有效 BoundingBox。")
            return None, None, None, self.log

        dx = self.bb.Max.X - self.bb.Min.X
        dy = self.bb.Max.Y - self.bb.Min.Y
        dz = self.bb.Max.Z - self.bb.Min.Z

        self.log.append("BoundingBox 尺寸: dx={:.3f}, dy={:.3f}, dz={:.3f}".format(dx, dy, dz))

        cx = 0.5 * (self.bb.Min.X + self.bb.Max.X)
        cy = 0.5 * (self.bb.Min.Y + self.bb.Max.Y)
        cz = 0.5 * (self.bb.Min.Z + self.bb.Max.Z)

        # 规范 faceIndex
        fi = max(0, min(5, self.face_index))
        if fi != self.face_index:
            self.log.append("提示：FaceIndex 超出范围，已裁剪为 {}。".format(fi))
        self.face_index = fi

        # 根据面确定：
        #   - 底面中心 base_center
        #   - 法向 normal（指向盒子内部）
        #   - 面的两个边长 size1, size2（决定圆半径）
        #   - 圆柱高度 height（沿 normal 方向的长度）
        if fi == 0:  # Z- 底面
            base_center = rg.Point3d(cx, cy, self.bb.Min.Z)
            normal = rg.Vector3d(0, 0, 1)  # 向上进入盒子
            size1, size2 = dx, dy
            height = dz
            face_name = "Z- 底面"
        elif fi == 1:  # Z+ 顶面
            base_center = rg.Point3d(cx, cy, self.bb.Max.Z)
            normal = rg.Vector3d(0, 0, -1)  # 向下进入盒子
            size1, size2 = dx, dy
            height = dz
            face_name = "Z+ 顶面"
        elif fi == 2:  # Y- 后面
            base_center = rg.Point3d(cx, self.bb.Min.Y, cz)
            normal = rg.Vector3d(0, 1, 0)  # 向前进入盒子
            size1, size2 = dx, dz
            height = dy
            face_name = "Y- 后面"
        elif fi == 3:  # Y+ 前面
            base_center = rg.Point3d(cx, self.bb.Max.Y, cz)
            normal = rg.Vector3d(0, -1, 0)  # 向后进入盒子
            size1, size2 = dx, dz
            height = dy
            face_name = "Y+ 前面"
        elif fi == 4:  # X- 左侧
            base_center = rg.Point3d(self.bb.Min.X, cy, cz)
            normal = rg.Vector3d(1, 0, 0)  # 向右进入盒子
            size1, size2 = dy, dz
            height = dx
            face_name = "X- 左侧"
        else:  # fi == 5, X+ 右侧
            base_center = rg.Point3d(self.bb.Max.X, cy, cz)
            normal = rg.Vector3d(-1, 0, 0)  # 向左进入盒子
            size1, size2 = dy, dz
            height = dx
            face_name = "X+ 右侧"

        self.log.append("选定面: {} (FaceIndex = {})".format(face_name, fi))

        # 圆半径 = 该矩形面的较短边的一半（内切圆）
        radius = 0.5 * min(size1, size2)

        self.log.append(
            "面边长: {:.3f} x {:.3f}, 半径 radius = {:.3f}, 高度 height = {:.3f}".format(
                size1, size2, radius, height
            )
        )

        # 构造圆柱
        plane = rg.Plane(base_center, normal)
        circle = rg.Circle(plane, radius)
        cylinder = rg.Cylinder(circle, height)
        cyl_brep = cylinder.ToBrep(True, True)

        # 轴线（从底面中心指向对面）
        top_center = base_center + normal * height
        axis_line = rg.Line(base_center, top_center)

        return cyl_brep, axis_line, circle, self.log

if __name__ == "__main__":
    # ==========================================================
    # GhPython 组件入口：调用类并输出
    # ==========================================================

    CylBrep = None
    Axis = None
    BaseCircle = None
    Log = []

    if BoxGeo is not None:
        if FaceIndex is None:
            FaceIndex = 0  # 默认用底面
        solver = InscribedCylinderInBox(BoxGeo, FaceIndex)
        CylBrep, Axis, BaseCircle, Log = solver.run()
    else:
        Log = ["提示：BoxGeo 输入为空。"]

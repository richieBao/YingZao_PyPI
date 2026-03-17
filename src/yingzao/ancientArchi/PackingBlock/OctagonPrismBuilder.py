# -*- coding: utf-8 -*-
"""
GhPython component: OctagonPrism (8-sided prism)

==================== 1) 输入端参数（GH 组件配置建议）====================
Name         Access    TypeHint                     Default
---------------------------------------------------------------------------
edge_len     Item      float (Number)               10.0     # A-B 平边长度
chamfer_len  Item      float (Number)               7.07     # A-C / B-D 斜边长度（45°边）
height       Item      float (Number)               10.0     # 拉伸高度（沿 ref_plane.ZAxis）
base_point   Item      Rhino.Geometry.Point3d       Point3d(0,0,0)
ref_plane    Item      Rhino.Geometry.Plane         Plane.WorldXY  # 会自动过 base_point

==================== 2) 输出端参数（GH 组件配置建议）====================
Name         Access    TypeHint
------------------------------------------
PrismBrep    Item      Rhino.Geometry.Brep
SectionCrv   Item      Rhino.Geometry.Curve
Log          Item      str

Notes:
- 截面中心点 = base_point，并且截面绘制在 ref_plane 内。
- 拉伸方向 = ref_plane.ZAxis（垂直于参考平面“向上”）。
"""

import math
import Rhino
from Rhino.Geometry import Point3d, Plane, Polyline, Brep
import ghpythonlib.components as ghc

__author__ = "AncientCHArchi / YingZaoLab"
__version__ = "2026.01.22"


class OctagonPrismBuilder(object):
    def __init__(self, edge_len=10.0, chamfer_len=7.07, height=10.0,
                 base_point=None, ref_plane=None, tol=1e-6):

        self.edge_len = float(edge_len) if edge_len is not None else 10.0
        self.chamfer_len = float(chamfer_len) if chamfer_len is not None else 7.07
        self.height = float(height) if height is not None else 10.0
        self.base_point = base_point if base_point is not None else Point3d(0, 0, 0)
        self.ref_plane = ref_plane if ref_plane is not None else Plane.WorldXY
        self.tol = float(tol)

        # —— 强制 ref_plane 过 base_point ——
        try:
            self.ref_plane.Origin = self.base_point
        except:
            self.ref_plane = Plane(
                self.base_point,
                self.ref_plane.XAxis,
                self.ref_plane.YAxis
            )

        # ✅ 明确保存“过 base_point 的参考平面”
        self.ref_plane_bp = self.ref_plane

        self.log = []

    def _safe_positive(self, v, name):
        if v is None or not (v > self.tol):
            raise ValueError("{} must be > 0".format(name))
        return v

    def build_section_curve(self):
        """
        构造“轴对齐 + 45°削角”的八角形闭合曲线：
        - 平边长度 = edge_len
        - 45°斜边长度 = chamfer_len
        """
        e = self._safe_positive(self.edge_len, "edge_len")
        c = self._safe_positive(self.chamfer_len, "chamfer_len")

        # 45°斜边长度 c 对应的削角偏移量 t：斜边= t*sqrt(2)
        t = c / math.sqrt(2.0)

        # 以中心为原点的“外包正方形”半边长 half = e/2 + t
        half = (e * 0.5) + t
        eh = e * 0.5

        # 8 个顶点（在 ref_plane 的局部二维坐标里）
        # 顺序：从右上“竖边顶点”开始，逆时针
        pts2d = [
            ( half,  eh),
            (  eh, half),
            ( -eh, half),
            (-half,  eh),
            (-half, -eh),
            ( -eh,-half),
            (  eh,-half),
            ( half, -eh),
        ]

        # 映射到 3D：ref_plane.PointAt(x,y)
        pts3d = []
        for (x, y) in pts2d:
            pts3d.append(self.ref_plane.PointAt(x, y, 0.0))
        pts3d.append(pts3d[0])  # 闭合

        pl = Polyline(pts3d)
        if not pl.IsValid or pl.Count < 4:
            raise RuntimeError("Failed to build valid polyline for section.")

        crv = pl.ToNurbsCurve()
        if crv is None or not crv.IsClosed:
            raise RuntimeError("Section curve is invalid or not closed.")

        self.log.append("Section OK: edge_len={:.4f}, chamfer_len={:.4f}, t={:.4f}".format(e, c, t))
        return crv

    def build_prism_brep(self):
        """
        由截面曲线先封面（Boundary Surface），再用 ghc.Extrude 向 ref_plane.ZAxis 拉伸 height。
        输出 Brep（尽量封闭）。
        """
        h = self._safe_positive(self.height, "height")

        section_crv = self.build_section_curve()
        dir_vec = self.ref_plane.ZAxis
        dir_vec.Unitize()
        dir_vec *= h

        # 1) 曲线封面：Boundary Surfaces
        #    ghc.BoundarySurfaces 返回通常是 Brep（或列表），这里做兼容处理
        prof = ghc.BoundarySurfaces(section_crv)
        if prof is None:
            raise RuntimeError("BoundarySurfaces returned None (section may be non-planar or not closed).")

        # GH 组件常返回 list / IronPython list / 单个几何
        if isinstance(prof, (list, tuple)):
            prof_list = [p for p in prof if p is not None]
            if len(prof_list) == 0:
                raise RuntimeError("BoundarySurfaces returned empty list.")
            prof = prof_list[0]

        # 2) 挤出：ghc.Extrude
        print(dir_vec, prof)
        ext = ghc.Extrude(prof, dir_vec)
        print(ext)
        if ext is None:
            raise RuntimeError("ghc.Extrude returned None.")

        # Extrude 也可能返回 list
        if isinstance(ext, (list, tuple)):
            ext_list = [e for e in ext if e is not None]
            if len(ext_list) == 0:
                raise RuntimeError("ghc.Extrude returned empty list.")
            ext = ext_list[0]

        # 3) 尽量转为 Brep
        brep = None
        if isinstance(ext, Brep):
            brep = ext
        else:
            # 某些情况下 ext 可能是 Surface/Extrusion 等
            try:
                brep = ext.ToBrep()
            except:
                brep = None

        if brep is None or (hasattr(brep, "IsValid") and not brep.IsValid):
            raise RuntimeError("Extrusion result cannot be converted to a valid Brep.")

        # 4) 封顶封底（可选）
        capped = Brep.CapPlanarHoles(brep, self.tol)
        if capped is not None and capped.IsValid:
            brep = capped
            self.log.append("Cap OK.")
        else:
            self.log.append("Cap skipped (may already be closed or tolerance too tight).")

        self.log.append("Extrude OK: height={:.4f}".format(h))
        return brep, section_crv


    def solve(self):
        try:
            prism, section = self.build_prism_brep()
            return prism, section, self.ref_plane_bp, "\n".join(self.log)
        except Exception as e:
            self.log.append("ERROR: {}".format(e))
            return None, None, self.ref_plane_bp, "\n".join(self.log)


if __name__ == "__main__":
    # ==================== GH 执行区（未连线用默认值；消除 pyflakes 未定义提示）====================

    try:
        edge_len
    except NameError:
        edge_len = 10.0
    if edge_len is None:
        edge_len = 10.0

    try:
        chamfer_len
    except NameError:
        chamfer_len = 7.07
    if chamfer_len is None:
        chamfer_len = 7.07

    try:
        height
    except NameError:
        height = 41.0
    if height is None:
        height = 41.0

    try:
        base_point
    except NameError:
        base_point = Point3d(0, 0, 0)
    if base_point is None:
        base_point = Point3d(0, 0, 0)

    try:
        ref_plane
    except NameError:
        ref_plane = Plane.WorldXY
    if ref_plane is None:
        ref_plane = Plane.WorldXY


    builder = OctagonPrismBuilder(
        edge_len=edge_len,
        chamfer_len=chamfer_len,
        height=height,
        base_point=base_point,
        ref_plane=ref_plane,
        tol=1e-6
    )

    PrismBrep, SectionCrv, RefPlane_BP, Log = builder.solve()

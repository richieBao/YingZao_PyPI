"""
GhPython Component: SectionExtrude_SymmetricTrapezoid_V4
-------------------------------------------------------
按示意图绘制截面 A-B-D-C-A，沿“垂直于参考平面的 -Z 方向”拉伸成封闭体；
再沿参考平面 +Y 方向得到 O'，以“过 AC 轴线且沿参考平面 Z 轴方向的镜像平面”（即包含 AC 直线与 ref_plane.ZAxis 的平面）
镜像 solid_brep 得到上部实体；
并输出相关参考平面（O'处平面及其 X/Y 轴垂直平面）与轴线 AC。

✅ 重要修正（按你最新要求）：
- 镜像不是“过 O' 且垂直参考平面的任意平面”，而是：
  **包含 AC 直线（平行 ref_plane.XAxis，过 O'）并包含 ref_plane.ZAxis 的平面**，
  等价于：mirror_plane = Plane(O', XAxis=ref_plane.XAxis, YAxis=ref_plane.ZAxis)

Inputs (GH 端口建议配置)
----------------------------------------------------
base_point : Point3d   Access:item  TypeHint: Point3d
ref_plane  : Plane     Access:item  TypeHint: Plane
ab_len     : float     Access:item  TypeHint: float
oe_len     : float     Access:item  TypeHint: float
angle_deg  : float     Access:item  TypeHint: float
extrude_h  : float     Access:item  TypeHint: float
oo_prime   : float     Access:item  TypeHint: float

Outputs (GH 端口建议配置)
----------------------------------------------------
A, B, C, D, O, E, Oprime : Point3d   Access:item  TypeHint: Point3d
AB, CD, AC, BD           : Line      Access:item  TypeHint: Line
Axis_AC                  : Line      Access:item  TypeHint: Line
section_polyline         : Polyline  Access:item  TypeHint: Polyline
section_curve            : Curve     Access:item  TypeHint: Curve
section_brep             : Brep      Access:item  TypeHint: Brep
solid_brep               : Brep      Access:item  TypeHint: Brep
solid_brep_mirror        : Brep      Access:item  TypeHint: Brep
solid_list               : list      Access:list  TypeHint: Brep
Plane_Oprime             : Plane     Access:item  TypeHint: Plane
Plane_Oprime_X           : Plane     Access:item  TypeHint: Plane
Plane_Oprime_Y           : Plane     Access:item  TypeHint: Plane
MirrorPlane_ACZ          : Plane     Access:item  TypeHint: Plane
log                      : list[str] Access:list  TypeHint: str

Notes on GH planes (你给出的约定)
----------------------------------------------------
XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
"""

import math
import Rhino.Geometry as rg


class SectionExtrude_SymmetricTrapezoid(object):
    def __init__(self,
                 base_point=None,
                 ref_plane=None,
                 ab_len=24.142136,
                 oe_len=1.0,
                 angle_deg=45.0,
                 extrude_h=11.0,
                 oo_prime=5.0):
        self.log = []

        # ---- Defaults ----
        self.O = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d(0, 0, 0)
        self.Plane = ref_plane if isinstance(ref_plane, rg.Plane) else rg.Plane.WorldXY  # 默认 GH XY

        self.ab_len = float(ab_len) if ab_len is not None else 24.142136
        self.oe_len = float(oe_len) if oe_len is not None else 1.0
        self.angle_deg = float(angle_deg) if angle_deg is not None else 45.0
        self.extrude_h = float(extrude_h) if extrude_h is not None else 11.0
        self.oo_prime = float(oo_prime) if oo_prime is not None else 5.0

        # ---- Outputs placeholders ----
        self.A = self.B = self.C = self.D = self.E = None
        self.AB = self.CD = self.AC = self.BD = None

        self.Oprime = None
        self.Axis_AC = None

        self.section_polyline = None
        self.section_curve = None
        self.section_brep = None
        self.solid_brep = None

        self.MirrorPlane_ACZ = None
        self.solid_brep_mirror = None
        self.solid_list = []

        self.Plane_Oprime = None
        self.Plane_Oprime_X = None
        self.Plane_Oprime_Y = None

    def _unitize(self, v):
        vv = rg.Vector3d(v)
        if vv.IsTiny():
            return vv
        vv.Unitize()
        return vv

    def build(self):
        try:
            # Reference plane axes
            x = self._unitize(self.Plane.XAxis)
            y = self._unitize(self.Plane.YAxis)
            z = self._unitize(self.Plane.ZAxis)

            # 2) A-B：过 O，沿 X；OA=OB=ab_len/2
            half = 0.5 * self.ab_len
            self.A = self.O - x * half
            self.B = self.O + x * half
            self.AB = rg.Line(self.A, self.B)

            # 3) E：沿 +Y
            self.E = self.O + y * self.oe_len

            # 4) 过 E 作平行于 AB 的直线 C-D；并满足两侧角度对称
            ang = math.radians(self.angle_deg)

            # 在参考平面 X-Y 内构造对称射线
            dirL = self._unitize(x * math.cos(ang) + y * math.sin(ang))
            dirR = self._unitize((-x) * math.cos(ang) + y * math.sin(ang))

            lineCD = rg.Line(self.E - x * 1e6, self.E + x * 1e6)
            crvCD = rg.LineCurve(lineCD)

            rayA = rg.Line(self.A, self.A + dirL * 1e6)
            crvRayA = rg.LineCurve(rayA)
            xA = rg.Intersect.Intersection.CurveCurve(crvRayA, crvCD, 1e-9, 1e-9)
            if not xA or xA.Count == 0:
                raise Exception("Failed to intersect ray from A with line through E (CD).")
            self.C = xA[0].PointA

            rayB = rg.Line(self.B, self.B + dirR * 1e6)
            crvRayB = rg.LineCurve(rayB)
            xB = rg.Intersect.Intersection.CurveCurve(crvRayB, crvCD, 1e-9, 1e-9)
            if not xB or xB.Count == 0:
                raise Exception("Failed to intersect ray from B with line through E (CD).")
            self.D = xB[0].PointA

            self.CD = rg.Line(self.C, self.D)
            self.AC = rg.Line(self.A, self.C)
            self.BD = rg.Line(self.B, self.D)

            # 截面闭合：A-B-D-C-A
            pl = rg.Polyline([self.A, self.B, self.D, self.C, self.A])
            self.section_polyline = pl
            self.section_curve = pl.ToNurbsCurve()

            # 平面面域
            breps = rg.Brep.CreatePlanarBreps(self.section_curve, 1e-7)
            if not breps or len(breps) == 0:
                raise Exception("CreatePlanarBreps failed. Section may not be planar/closed.")
            self.section_brep = breps[0]

            # 5) 沿“垂直于参考平面的 -Z 方向”拉伸
            ext_dir = self._unitize(-z) * self.extrude_h
            srf = rg.Surface.CreateExtrusion(self.section_curve, ext_dir)
            brep_ext = srf.ToBrep()
            capped = brep_ext.CapPlanarHoles(1e-7)
            self.solid_brep = capped if capped and capped.IsSolid else brep_ext

            # ------------------------------------------------------------
            # 6) 新增：O' 与轴线 AC；按“过 AC 且沿 ref_plane.ZAxis”的镜像平面镜像
            # ------------------------------------------------------------
            # O'：沿参考平面 +Y 方向
            self.Oprime = self.O + y * self.oo_prime

            # 过 O' 的轴线 AC（平行 ref_plane.XAxis）
            self.Axis_AC = rg.Line(self.Oprime - x * 1e6, self.Oprime + x * 1e6)

            # ✅ 镜像平面：包含 AC 直线(=XAxis方向) + ref_plane.ZAxis 方向
            # 即：Plane(origin=O', XAxis=x, YAxis=z)
            self.MirrorPlane_ACZ = rg.Plane(self.Oprime, x, z)

            xform = rg.Transform.Mirror(self.MirrorPlane_ACZ)

            # 镜像实体
            b2 = self.solid_brep.DuplicateBrep()
            ok = b2.Transform(xform)
            if not ok:
                raise Exception("Mirror transform failed on brep.")
            self.solid_brep_mirror = b2

            # 合并输出到一个端口（列表）
            self.solid_list = [self.solid_brep, self.solid_brep_mirror]

            # ------------------------------------------------------------
            # 7) 新增输出参考平面
            # ------------------------------------------------------------
            # 过 O' 的参考平面（与 ref_plane 同向）
            self.Plane_Oprime = rg.Plane(self.Oprime, x, y)

            # 垂直于 Plane_Oprime 的两个平面（分别过其 X 轴 / Y 轴）
            self.Plane_Oprime_X = rg.Plane(self.Oprime, x, z)  # 含 X 与 Z（法向 ~ Y）
            self.Plane_Oprime_Y = rg.Plane(self.Oprime, y, z)  # 含 Y 与 Z（法向 ~ X）

            self.log.append("OK: built section, solid, O', axis AC, mirrored by Plane(O', x, z), and planes at O'.")
        except Exception as e:
            self.log.append("ERROR: {}".format(str(e)))

        return self

if __name__ == "__main__":
    # --------------------------
    # GH 调用区（把下面变量名绑定到 GH 输出）
    # --------------------------
    solver = SectionExtrude_SymmetricTrapezoid(
        base_point=base_point,
        ref_plane=ref_plane,
        ab_len=ab_len,
        oe_len=oe_len,
        angle_deg=angle_deg,
        extrude_h=extrude_h,
        oo_prime=oo_prime
    ).build()

    # Points
    A = solver.A
    B = solver.B
    C = solver.C
    D = solver.D
    O = solver.O
    E = solver.E
    Oprime = solver.Oprime

    # Lines
    AB = solver.AB
    CD = solver.CD
    AC = solver.AC
    BD = solver.BD
    Axis_AC = solver.Axis_AC

    # Section
    section_polyline = solver.section_polyline
    section_curve = solver.section_curve
    section_brep = solver.section_brep

    # Solids
    solid_brep = solver.solid_brep
    solid_brep_mirror = solver.solid_brep_mirror
    solid_list = solver.solid_list

    # Planes
    Plane_Oprime = solver.Plane_Oprime
    Plane_Oprime_X = solver.Plane_Oprime_X
    Plane_Oprime_Y = solver.Plane_Oprime_Y
    MirrorPlane_ACZ = solver.MirrorPlane_ACZ

    # Log
    log = solver.log



"""
GhPython Component: WedgeShapedTool (RightTriangle_Prism)
--------------------------------------------------------
在 reference_plane 上绘制直角三角形截面 A-B-C（A 为 base_point），
再沿 reference_plane 的“GH-ZAxis”双向偏移 offset 距离得到两个平行截面，
用两截面 Loft 成侧面，并封闭两端，Join 成一个封闭体 Brep 输出。

✅ GH 平面轴向约定（按你给定）
- GH XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
- GH XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
- GH YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)

✅ 本组件几何约定（按你最新要求）
- A-B 沿 plane.YAxis
- A-C 沿 plane.XAxis
- 偏移沿 plane.ZAxis

=============================================================
【GhPython 输入 Inputs（建议在 GH 中这样配置）】
--------------------------------------------------------------
base_point : rg.Point3d   Access:item  TypeHint:Point3d
reference_plane : object  Access:item  TypeHint:generic
    - 支持：rg.Plane / "WorldXY" / "WorldXZ" / "WorldYZ" / "XY" / "XZ" / "YZ"
AB : float               Access:item  TypeHint:float   默认=6.0
AC : float               Access:item  TypeHint:float   默认=14.0
offset : float           Access:item  TypeHint:float   默认=3.0

=============================================================
【GhPython 输出 Outputs（建议在 GH 中这样配置）】
--------------------------------------------------------------
SolidBrep     : rg.Brep      Access:item  TypeHint:Brep
SectionCrv    : rg.Curve     Access:item  TypeHint:Curve
PlaneOut      : rg.Plane     Access:item  TypeHint:Plane
A_RefPlanes   : list         Access:list  TypeHint:generic
    - [0]=过A点主参考平面（即 PlaneOut）
    - [1]=垂直于主平面、过A点、包含主平面 XAxis 的平面（主平面绕 XAxis 旋转90°）
    - [2]=垂直于主平面、过A点、包含主平面 YAxis 的平面（主平面绕 YAxis 旋转90°）
Log           : str          Access:item  TypeHint:str
"""

import Rhino.Geometry as rg

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.10"


class WedgeShapedTool(object):
    TOL = 1e-6

    def __init__(self, base_point=None, reference_plane=None, AB=6.0, AC=14.0, offset=3.0, output_lower_a=True):
        self.base_point = rg.Point3d(0, 0, 0) if base_point is None else rg.Point3d(base_point)
        self.reference_plane_input = "WorldXZ" if reference_plane is None else reference_plane

        self.AB = float(AB) if AB is not None else 6.0
        self.AC = float(AC) if AC is not None else 14.0
        self.offset = float(offset) if offset is not None else 3.0
        self.output_lower_a = bool(output_lower_a)

        # outputs / debug
        self.plane_out = None
        self.a_ref_planes = None   # <-- NEW
        self.section_crv = None
        self.solid_brep = None
        self.solid_brep_A = None
        self.solid_brep_B = None
        self.log_lines = []

        self.ptA = None
        self.ptB = None
        self.ptC = None

    # -------------------------
    # Logging
    # -------------------------
    def log(self, msg):
        self.log_lines.append(str(msg))

    def get_log(self):
        return "\n".join(self.log_lines) + ("\n" if self.log_lines else "")

    # -------------------------
    # GH Plane Factory (strict to your axis definitions)
    # -------------------------
    @staticmethod
    def _make_gh_plane(token, origin):
        t = str(token).strip().lower()

        # GH XY
        if t in ("worldxy", "xy", "plane.xy"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 1, 0)
            return rg.Plane(origin, x, y)

        # GH XZ
        if t in ("worldxz", "xz", "plane.xz"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)  # x×y => (0,-1,0)
            return rg.Plane(origin, x, y)

        # GH YZ
        if t in ("worldyz", "yz", "plane.yz"):
            x = rg.Vector3d(0, 1, 0)
            y = rg.Vector3d(0, 0, 1)  # x×y => (1,0,0)
            return rg.Plane(origin, x, y)

        # fallback => GH XZ
        x = rg.Vector3d(1, 0, 0)
        y = rg.Vector3d(0, 0, 1)
        return rg.Plane(origin, x, y)

    def coerce_plane(self):
        p = self.reference_plane_input
        o = self.base_point

        if isinstance(p, rg.Plane):
            pl = rg.Plane(p)
            pl.Origin = o
            return pl

        if isinstance(p, (str, bytes)):
            return self._make_gh_plane(p, o)

        try:
            pl = rg.Plane(p)
            pl.Origin = o
            return pl
        except Exception:
            return self._make_gh_plane("WorldXZ", o)

    # -------------------------
    # NEW: A-point reference planes set
    # -------------------------
    def build_A_reference_planes(self, main_plane):
        """
        输出三张过A点的互相垂直参考平面：
        P0: 主参考平面（main_plane）
        P1: 垂直于P0，且包含 P0.XAxis（等价：P0 围绕 XAxis 旋转 90°）
            -> 用 (XAxis, ZAxis) 作为该平面的 (X,Y)
        P2: 垂直于P0，且包含 P0.YAxis（等价：P0 围绕 YAxis 旋转 90°）
            -> 用 (YAxis, ZAxis) 作为该平面的 (X,Y)
        """
        A = rg.Point3d(self.base_point)

        # 复制避免外部引用被改
        P0 = rg.Plane(main_plane)
        P0.Origin = A

        # P1: span {XAxis, ZAxis} => Normal = X×Z = -Y（与主平面法向垂直）
        P1 = rg.Plane(A, P0.XAxis, P0.ZAxis)

        # P2: span {YAxis, ZAxis} => Normal = Y×Z =  X（与主平面法向垂直）
        P2 = rg.Plane(A, P0.YAxis, P0.ZAxis)

        return [P0, P1, P2]

    # -------------------------
    # Geometry builders
    # -------------------------
    def build_section_curve(self, plane):
        """
        Right triangle on the given plane (per your requirement):
          A = base_point
          B = A + YAxis * AB   (A-B 沿参考平面 Y 轴)
          C = A + XAxis * AC   (A-C 沿参考平面 X 轴)
        """
        A = rg.Point3d(self.base_point)
        B = A + plane.YAxis * self.AB
        C = A + plane.XAxis * self.AC

        self.ptA, self.ptB, self.ptC = A, B, C

        poly = rg.Polyline([A, B, C, A])
        return poly.ToNurbsCurve()


    def build_box_section_curve(self, plane):
        """Rectangle section A-B-D-C-A on the given plane.
        A = base_point
        B = A + YAxis*AB
        C = A + XAxis*AC
        D = A + XAxis*AC + YAxis*AB
        """
        A = rg.Point3d(self.base_point)
        B = A + plane.YAxis * self.AB
        C = A + plane.XAxis * self.AC
        D = A + plane.XAxis * self.AC + plane.YAxis * self.AB
        poly = rg.Polyline([A, B, D, C, A])
        return poly.ToNurbsCurve()

    def build_box_brep(self, plane):
        """Build a *guaranteed-solid* box Brep (AC x AB x 2*offset) aligned to the given plane.

        Why: using Loft+Cap for the box may fail silently in some Rhino tolerance situations, which makes
        boolean difference (Box - A) always fail, so the output never switches to B.
        """
        try:
            # Oriented box aligned with plane axes:
            # X interval: [0, AC], Y interval: [0, AB], Z interval: [-offset, +offset]
            x_int = rg.Interval(0.0, float(self.AC))
            y_int = rg.Interval(0.0, float(self.AB))
            z_int = rg.Interval(-float(self.offset), float(self.offset))
            bx = rg.Box(plane, x_int, y_int, z_int)
            brep = bx.ToBrep()
            return brep
        except Exception:
            # Fallback to previous construction if Box creation fails for any reason
            rect_crv = self.build_box_section_curve(plane)
            crv_neg, crv_pos = self.offset_section_curves(rect_crv, plane)
            side = self.loft_between(crv_neg, crv_pos)
            cap0 = self.planar_cap_from_curve(crv_neg)
            cap1 = self.planar_cap_from_curve(crv_pos)
            joined = self.join_breps([side, cap0, cap1])
            if joined is None:
                return None
            closed = self.cap_planar_holes(joined)
            return closed

    def _pick_largest_volume(self, breps):
        if not breps:
            return None
        best = breps[0]
        best_v = -1.0
        for b in breps:
            try:
                vmp = rg.VolumeMassProperties.Compute(b)
                v = vmp.Volume if vmp else 0.0
            except Exception:
                v = 0.0
            if v > best_v:
                best_v = v
                best = b
        return best

    def build_upper_brep_B(self, plane):
        """Build the upper solid B by explicit construction steps.

        Steps:
          1) Along plane.XAxis through point B, get D with |B-D| = AC
          2) Build triangle section B-D-C-B
          3) Offset this section to both sides along plane.ZAxis by +/-offset
          4) Loft + cap + join => closed brep B
        """
        if self.ptB is None or self.ptC is None:
            _ = self.build_section_curve(plane)

        B = rg.Point3d(self.ptB)
        C = rg.Point3d(self.ptC)
        D = B + plane.XAxis * float(self.AC)
        self.ptD = D

        tri = rg.Polyline([B, D, C, B]).ToNurbsCurve()
        return self.build_closed_prism_from_section(tri, plane)


    def build_closed_prism_from_section(self, section_crv, plane):
        """Offset section to +/- plane.ZAxis by self.offset, loft, cap, and join to a closed brep."""
        crv_neg, crv_pos = self.offset_section_curves(section_crv, plane)

        side = self.loft_between(crv_neg, crv_pos)
        if side is None:
            self.log("[ERROR] Loft failed while building prism.")
            return None

        cap0 = self.planar_cap_from_curve(crv_neg)
        cap1 = self.planar_cap_from_curve(crv_pos)

        solid = self.join_breps([side, cap0, cap1])
        if solid is None:
            self.log("[WARN] JoinBreps failed, try CapPlanarHoles fallback.")
            solid = self.cap_planar_holes(side)

        return solid

    def offset_section_curves(self, section_crv, plane):
        d = self.offset
        n = plane.ZAxis  # GH-style normal
        xfm_pos = rg.Transform.Translation(n * d)
        xfm_neg = rg.Transform.Translation(n * (-d))

        crv_pos = section_crv.DuplicateCurve()
        crv_neg = section_crv.DuplicateCurve()
        crv_pos.Transform(xfm_pos)
        crv_neg.Transform(xfm_neg)
        return crv_neg, crv_pos

    def loft_between(self, curve0, curve1):
        breps = rg.Brep.CreateFromLoft(
            [curve0, curve1],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )
        if not breps or len(breps) == 0:
            return None
        return breps[0]

    def planar_cap_from_curve(self, crv):
        caps = rg.Brep.CreatePlanarBreps(crv, self.TOL)
        if not caps or len(caps) == 0:
            return None
        return caps[0]

    def join_breps(self, breps):
        breps = [b for b in breps if b is not None]
        if not breps:
            return None

        joined = rg.Brep.JoinBreps(breps, self.TOL)
        if not joined or len(joined) == 0:
            return None

        if len(joined) == 1:
            return joined[0]

        best = joined[0]
        best_score = -1.0
        for b in joined:
            try:
                amp = rg.AreaMassProperties.Compute(b)
                score = amp.Area if amp else float(b.Faces.Count)
            except Exception:
                score = float(b.Faces.Count)
            if score > best_score:
                best = b
                best_score = score
        return best

    def cap_planar_holes(self, brep):
        try:
            return brep.CapPlanarHoles(self.TOL)
        except Exception:
            return None

    # -------------------------
    # Public API
    # -------------------------
    def build(self):
        self.log("== WedgeShapedTool Build Start ==")

        pl = self.coerce_plane()
        self.plane_out = pl

        # NEW: reference planes at A
        self.a_ref_planes = self.build_A_reference_planes(pl)

        self.log("PlaneOut: Origin={}, XAxis={}, YAxis={}, ZAxis={}".format(
            pl.Origin, pl.XAxis, pl.YAxis, pl.ZAxis
        ))

        section = self.build_section_curve(pl)
        self.section_crv = section
        self.log("Section: AB={}, AC={}, offset={}".format(self.AB, self.AC, self.offset))
        self.log("Points: A={}, B={}, C={}".format(self.ptA, self.ptB, self.ptC))

        solid = self.build_closed_prism_from_section(section, pl)

        # A: lower wedge (current behavior)
        self.solid_brep_A = solid

        if self.solid_brep_A is None:
            self.log("[ERROR] Failed to build closed wedge brep (A).")
            self.solid_brep = None
            return None

        # B: upper complementary solid inside the same (AC x AB x 2*offset) box
        self.solid_brep_B = self.build_upper_brep_B(pl)
        if self.solid_brep_B is None:
            self.log("[WARN] Failed to build upper solid (B) via boolean; will fallback to A only.")

        # Output switch
        if self.output_lower_a or self.solid_brep_B is None:
            self.solid_brep = self.solid_brep_A
            self.log("OK: Output = A (lower wedge).")
        else:
            self.solid_brep = self.solid_brep_B
            self.log("OK: Output = B (upper solid).")

        return self.solid_brep

if __name__ == "__main__":
    # =========================================================
    # GH Main (Inputs -> Class -> Outputs)
    # =========================================================
    if 'base_point' not in globals() or base_point is None:
        base_point = rg.Point3d(0, 0, 0)
    if 'reference_plane' not in globals() or reference_plane is None:
        reference_plane = "WorldXZ"
    if 'AB' not in globals() or AB is None:
        AB = 6.0
    if 'AC' not in globals() or AC is None:
        AC = 14.0
    if 'offset' not in globals() or offset is None:
        offset = 3.0
    if 'output_lower_a' not in globals() or output_lower_a is None:
        output_lower_a = True  # True=A(下部), False=B(上部)

    tool = WedgeShapedTool(
        base_point=base_point,
        reference_plane=reference_plane,
        AB=AB,
        AC=AC,
        offset=offset,
        output_lower_a=output_lower_a
    )

    SolidBrep = tool.build()
    SectionCrv = tool.section_crv
    PlaneOut = tool.plane_out
    A_RefPlanes = tool.a_ref_planes  # <-- NEW OUTPUT
    Log = tool.get_log()
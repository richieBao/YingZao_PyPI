# -*- coding: utf-8 -*-
"""
HuaTouZi (GhPython-ready) - v1.3r3 (class+methods + refresh fix + planes at B)
------------------------------------------------------------------------------
新增输出：
- PlaneAtB        : 过 B 点的参考平面（与 ref_plane 同轴，Origin=B）
- PlaneAtB_X      : 垂直于 PlaneAtB，且“包含 PlaneAtB 的 X 轴”的平面（Origin=B, X=PlaneAtB.XAxis, Y=PlaneAtB.ZAxis）
- PlaneAtB_Y      : 垂直于 PlaneAtB，且“包含 PlaneAtB 的 Y 轴”的平面（Origin=B, X=PlaneAtB.YAxis, Y=PlaneAtB.ZAxis）

说明（对应你的描述）：
- “过B点的参考平面” => PlaneAtB
- “垂直于过B点的参考平面的两个过其X和Y轴的参考平面” =>
    PlaneAtB_X：通过 B 点且包含 X 轴方向的侧向平面
    PlaneAtB_Y：通过 B 点且包含 Y 轴方向的侧向平面

==============================================================
【GhPython 输入 Inputs（建议在 GH 中这样配置）】
--------------------------------------------------------------
base_point : rg.Point3d   Access:item  TypeHint:Point3d     默认=WorldOrigin
ref_plane_mode : object   Access:item  TypeHint:generic     默认="XZ Plane"
    - "XY Plane" / "XZ Plane" / "YZ Plane" 或直接输入 rg.Plane
Refresh : bool            Access:item  TypeHint:bool        默认=False

AB : float       Access:item TypeHint:float   默认=10.0
BC : float       Access:item TypeHint:float   默认=4.0
DE : float       Access:item TypeHint:float   默认=0.5
IG : float       Access:item TypeHint:float   默认=1.5
Offset : float   Access:item TypeHint:float   默认=5.0
Tol : float      Access:item TypeHint:float   默认=ModelAbsoluteTolerance

==============================================================
【GhPython 输出 Outputs（建议在 GH 中这样配置）】
--------------------------------------------------------------
SolidBrep      : rg.Brep   Access:item TypeHint:Brep
SectionCrv     : rg.Curve  Access:item TypeHint:Curve
SectionCrv_Pos : rg.Curve  Access:item TypeHint:Curve
SectionCrv_Neg : rg.Curve  Access:item TypeHint:Curve
LoftBrep       : rg.Brep   Access:item TypeHint:Brep
CapPosBrep     : rg.Brep   Access:item TypeHint:Brep
CapNegBrep     : rg.Brep   Access:item TypeHint:Brep

Pts_A : rg.Point3d  Access:item TypeHint:Point3d
Pts_B : rg.Point3d  Access:item TypeHint:Point3d
Pts_C : rg.Point3d  Access:item TypeHint:Point3d
Pts_H : rg.Point3d  Access:item TypeHint:Point3d
Pts_D : rg.Point3d  Access:item TypeHint:Point3d
Pts_I : rg.Point3d  Access:item TypeHint:Point3d
Pts_F : rg.Point3d  Access:item TypeHint:Point3d
Pts_E : rg.Point3d  Access:item TypeHint:Point3d
Pts_G : rg.Point3d  Access:item TypeHint:Point3d

Arc1 : rg.Curve  Access:item TypeHint:Curve
Arc2 : rg.Curve  Access:item TypeHint:Curve

PlaneAtB   : rg.Plane Access:item TypeHint:Plane
PlaneAtB_X : rg.Plane Access:item TypeHint:Plane
PlaneAtB_Y : rg.Plane Access:item TypeHint:Plane

Log  : list       Access:list TypeHint:str
"""

import Rhino.Geometry as rg
import Rhino.Geometry.Intersect as rgi
import scriptcontext as sc


# ============================================================
# Utilities
# ============================================================
def _bool(x, default=False):
    try:
        if x is None:
            return bool(default)
        return bool(x)
    except:
        return bool(default)


def _float(x, default):
    try:
        if x is None:
            return float(default)
        return float(x)
    except:
        return float(default)


def plane_from_gh_mode(ref_plane_mode, base_point):
    """Build GH-style planes using explicit axis vectors (world coords):
    XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
    YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    if isinstance(ref_plane_mode, rg.Plane):
        pl = rg.Plane(ref_plane_mode)
        pl.Origin = base_point
        return pl

    mode = ref_plane_mode if isinstance(ref_plane_mode, (str, bytes)) else "XZ Plane"
    mode = mode.decode("utf-8") if isinstance(mode, bytes) else mode
    mode = mode.strip()

    aliases = {
        "WorldXY": "XY Plane",
        "WorldXZ": "XZ Plane",
        "WorldYZ": "YZ Plane",
        "XY": "XY Plane",
        "XZ": "XZ Plane",
        "YZ": "YZ Plane",
    }
    mode = aliases.get(mode, mode)

    if mode == "XY Plane":
        x = rg.Vector3d(1, 0, 0)
        y = rg.Vector3d(0, 1, 0)
    elif mode == "YZ Plane":
        x = rg.Vector3d(0, 1, 0)
        y = rg.Vector3d(0, 0, 1)
    else:  # XZ Plane
        x = rg.Vector3d(1, 0, 0)
        y = rg.Vector3d(0, 0, 1)

    return rg.Plane(base_point, x, y)


def arc_tangent_start(A, tangent_dir, E):
    """Arc with start point A, start tangent, end point E."""
    try:
        t = rg.Vector3d(tangent_dir)
        if not t.Unitize():
            return None
        arc = rg.Arc(A, t, E)
        return arc.ToNurbsCurve()
    except:
        return None


def arc_through_3pts(p0, p1, p2):
    try:
        return rg.Arc(p0, p1, p2).ToNurbsCurve()
    except:
        try:
            return rg.Curve.CreateInterpolatedCurve([p0, p1, p2], 3)
        except:
            return None


def join_curves(curves, tol):
    crvs = [c for c in curves if c is not None]
    if not crvs:
        return None
    try:
        joined = rg.Curve.JoinCurves(crvs, tol)
        if joined and len(joined) > 0:
            joined.sort(key=lambda c: c.GetLength(), reverse=True)
            return joined[0]
    except:
        pass
    try:
        pc = rg.PolyCurve()
        for c in crvs:
            pc.Append(c)
        return pc
    except:
        return None


def cap_planar(brep, tol):
    if brep is None:
        return None
    try:
        capped = brep.CapPlanarHoles(tol)
        return capped if capped else brep
    except:
        return brep


def safe_join_breps(breps, tol):
    bs = [b for b in breps if b is not None]
    if not bs:
        return None
    try:
        joined = rg.Brep.JoinBreps(bs, tol)
        if joined and len(joined) > 0:
            return joined[0] if len(joined) == 1 else joined
    except:
        pass
    return bs


def line_from_point_dir(p, v, length):
    v = rg.Vector3d(v)
    if v.IsTiny():
        return None
    v.Unitize()
    a = rg.Point3d(p)
    b = a + v * float(length)
    return rg.LineCurve(a, b)


def intersect_curve_with_line(curve, linecurve, tol):
    pts = []
    if curve is None or linecurve is None:
        return pts
    try:
        events = rgi.Intersection.CurveCurve(curve, linecurve, tol, tol)
        if events:
            for ev in events:
                try:
                    if ev.IsPoint:
                        pts.append(ev.PointA)
                except:
                    pass
    except:
        pass
    return pts


def closest_point_on_curve_to_line(curve, linecurve, samples=80):
    if curve is None or linecurve is None:
        return None
    try:
        dom = curve.Domain
        best = None
        best_d = 1e100
        for i in range(samples + 1):
            t = dom.T0 + (dom.T1 - dom.T0) * (float(i) / float(samples))
            p = curve.PointAt(t)
            ok, tt = linecurve.ClosestPoint(p)
            if ok:
                q = linecurve.PointAt(tt)
                d = q.DistanceTo(p)
                if d < best_d:
                    best_d = d
                    best = p
        return best
    except:
        return None


def planes_at_point(base_plane, origin_pt):
    """
    Return (PlaneAtOrigin, PlaneAtOrigin_X, PlaneAtOrigin_Y)
    - PlaneAtOrigin: same axes as base_plane, origin moved to origin_pt
    - PlaneAtOrigin_X: perpendicular to PlaneAtOrigin, contains its X axis (X + Z define the plane)
    - PlaneAtOrigin_Y: perpendicular to PlaneAtOrigin, contains its Y axis (Y + Z define the plane)
    """
    p0 = rg.Plane(base_plane)
    p0.Origin = origin_pt

    # X-Z plane through origin (contains X axis, perpendicular to base plane)
    px = rg.Plane(origin_pt, p0.XAxis, p0.ZAxis)

    # Y-Z plane through origin (contains Y axis, perpendicular to base plane)
    py = rg.Plane(origin_pt, p0.YAxis, p0.ZAxis)

    return p0, px, py


# ============================================================
# Reusable class
# ============================================================
class HuaTouZi(object):
    """Reusable builder for HuaTouZi solid."""

    def __init__(self, base_point=None, ref_plane_mode="XZ Plane", tol=None):
        self.base_point = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d.Origin
        self.ref_plane_mode = ref_plane_mode
        self.pl = plane_from_gh_mode(ref_plane_mode, self.base_point)
        self.tol = float(tol) if (tol is not None and float(tol) > 0) else sc.doc.ModelAbsoluteTolerance

        # defaults
        self.AB = 10.0
        self.BC = 4.0
        self.DE = 0.5
        self.IG = 1.5
        self.Offset = 5.0

        self.reset_outputs()

    def reset_outputs(self):
        self.log = []
        self.A = self.B = self.C = None
        self.H = self.D = self.I = None
        self.F = self.E = self.G = None
        self.arc1 = None
        self.arc2 = None
        self.section_crv = None
        self.section_crv_pos = None
        self.section_crv_neg = None
        self.loft_brep = None
        self.cap_pos_brep = None
        self.cap_neg_brep = None
        self.solid_brep = None

        # planes at B (new)
        self.plane_at_b = None
        self.plane_at_b_x = None
        self.plane_at_b_y = None

    def set_plane(self, base_point=None, ref_plane_mode=None):
        if base_point is not None and isinstance(base_point, rg.Point3d):
            self.base_point = base_point
        if ref_plane_mode is not None:
            self.ref_plane_mode = ref_plane_mode
        self.pl = plane_from_gh_mode(self.ref_plane_mode, self.base_point)

    def set_params(self, AB=None, BC=None, DE=None, IG=None, Offset=None, Tol=None):
        if AB is not None: self.AB = float(AB)
        if BC is not None: self.BC = float(BC)
        if DE is not None: self.DE = float(DE)
        if IG is not None: self.IG = float(IG)
        if Offset is not None: self.Offset = float(Offset)
        if Tol is not None and float(Tol) > 0: self.tol = float(Tol)

    def build_section(self):
        pl = self.pl
        x = rg.Vector3d(pl.XAxis)
        y = rg.Vector3d(pl.YAxis)

        # A-B-C
        A = rg.Point3d(pl.Origin)
        B = A + x * self.AB
        C = B + y * self.BC
        self.A, self.B, self.C = A, B, C
        self.log.append("Plane axes: X={}, Y={}, Z={}".format(pl.XAxis, pl.YAxis, pl.ZAxis))
        self.log.append("A={}, B={}, C={}".format(A, B, C))

        # planes at B (new outputs)
        self.plane_at_b, self.plane_at_b_x, self.plane_at_b_y = planes_at_point(pl, B)

        # midpoints on AC
        D = rg.Point3d((A.X + C.X) * 0.5, (A.Y + C.Y) * 0.5, (A.Z + C.Z) * 0.5)
        H = rg.Point3d((A.X + D.X) * 0.5, (A.Y + D.Y) * 0.5, (A.Z + D.Z) * 0.5)
        I = rg.Point3d((D.X + C.X) * 0.5, (D.Y + C.Y) * 0.5, (D.Z + C.Z) * 0.5)
        self.H, self.D, self.I = H, D, I

        # down = -YAxis (toward AB)
        down = rg.Vector3d(y)
        if down.IsTiny():
            self.log.append("ERROR: YAxis is tiny.")
            return None
        down.Unitize()
        down *= -1.0

        # E fixed by DE
        E = D + down * self.DE
        self.E = E

        # Arc1 tangent at A to AB
        tan_ab = rg.Vector3d(B - A)
        if tan_ab.IsTiny():
            self.log.append("ERROR: AB is tiny.")
            return None
        arc1 = arc_tangent_start(A, tan_ab, E)
        if arc1 is None:
            self.log.append("ERROR: Arc1(A,tanAB,E) failed.")
            return None

        # F from intersection with line through H
        L = max(self.AB, self.BC, 1.0) * 10.0
        lineH = line_from_point_dir(H, down, L)
        ptsF = intersect_curve_with_line(arc1, lineH, self.tol)
        if ptsF:
            ptsF.sort(key=lambda p: p.DistanceTo(H))
            F = ptsF[0]
            self.log.append("F from intersection (H-down with Arc1).")
        else:
            F = closest_point_on_curve_to_line(arc1, lineH, samples=80)
            self.log.append("F fallback: closest point to H-down line.")
        self.F = F

        # Arc2 initial by 3 points
        G_guess = I + down * self.IG
        arc2 = arc_through_3pts(C, G_guess, E)
        if arc2 is None:
            self.log.append("ERROR: Arc2(C,G,E) failed.")
            return None

        # G from intersection with line through I
        lineI = line_from_point_dir(I, down, L)
        ptsG = intersect_curve_with_line(arc2, lineI, self.tol)
        if ptsG:
            ptsG.sort(key=lambda p: p.DistanceTo(I))
            G = ptsG[0]
            self.log.append("G from intersection (I-down with Arc2).")
        else:
            G = closest_point_on_curve_to_line(arc2, lineI, samples=80)
            self.log.append("G fallback: closest point to I-down line.")
        self.G = G

        self.arc1, self.arc2 = arc1, arc2

        # directions: arc2 C->E ; arc1 E->A
        if arc2.PointAtStart.DistanceTo(C) > arc2.PointAtEnd.DistanceTo(C):
            arc2.Reverse()
        if arc1.PointAtStart.DistanceTo(E) > arc1.PointAtEnd.DistanceTo(E):
            arc1.Reverse()

        ln_AB = rg.LineCurve(A, B)
        ln_BC = rg.LineCurve(B, C)

        section = join_curves([ln_AB, ln_BC, arc2, arc1], self.tol)
        if section is None:
            self.log.append("ERROR: join section curves failed.")
            return None

        self.section_crv = section
        try:
            self.log.append("Section IsClosed = {}".format(bool(section.IsClosed)))
        except:
            pass
        return section

    def build_solid(self):
        if self.section_crv is None:
            if self.build_section() is None:
                return None

        z = rg.Vector3d(self.pl.ZAxis)

        crv_pos = self.section_crv.DuplicateCurve()
        crv_neg = self.section_crv.DuplicateCurve()
        crv_pos.Transform(rg.Transform.Translation(z * self.Offset))
        crv_neg.Transform(rg.Transform.Translation(z * (-self.Offset)))

        self.section_crv_pos = crv_pos
        self.section_crv_neg = crv_neg

        # loft with 3 sections
        try:
            lofts = rg.Brep.CreateFromLoft(
                [crv_neg, self.section_crv, crv_pos],
                rg.Point3d.Unset, rg.Point3d.Unset,
                rg.LoftType.Normal, False
            )
            self.loft_brep = lofts[0] if lofts and len(lofts) > 0 else None
        except Exception as e:
            self.loft_brep = None
            self.log.append("ERROR: loft failed: {}".format(e))

        if self.loft_brep is None:
            return None

        # planar caps
        try:
            cap_pos = rg.Brep.CreatePlanarBreps(crv_pos, self.tol)
            self.cap_pos_brep = cap_pos[0] if cap_pos and len(cap_pos) > 0 else None
        except:
            self.cap_pos_brep = None

        try:
            cap_neg = rg.Brep.CreatePlanarBreps(crv_neg, self.tol)
            self.cap_neg_brep = cap_neg[0] if cap_neg and len(cap_neg) > 0 else None
        except:
            self.cap_neg_brep = None

        joined = safe_join_breps([self.loft_brep, self.cap_pos_brep, self.cap_neg_brep], self.tol)

        solid = None
        if isinstance(joined, list):
            try:
                js = rg.Brep.JoinBreps(joined, self.tol)
                solid = js[0] if js and len(js) > 0 else None
            except:
                solid = None
        else:
            solid = joined

        if isinstance(solid, list):
            solid = solid[0] if solid else None

        solid = cap_planar(solid, self.tol)
        self.solid_brep = solid

        try:
            self.log.append("Solid IsSolid = {}".format(bool(solid.IsSolid) if solid else None))
        except:
            pass

        return solid

    def build(self, reset=True):
        if reset:
            self.reset_outputs()
            self.set_plane(self.base_point, self.ref_plane_mode)
        self.build_section()
        self.build_solid()
        return self

if __name__ == "__main__":
    # ============================================================
    # GhPython component entry (NO sticky cache)
    # ============================================================
    Log = []
    SolidBrep = None
    SectionCrv = None
    SectionCrv_Pos = None
    SectionCrv_Neg = None
    LoftBrep = None
    CapPosBrep = None
    CapNegBrep = None

    Pts_A = Pts_B = Pts_C = None
    Pts_H = Pts_D = Pts_I = None
    Pts_F = Pts_E = Pts_G = None

    Arc1 = Arc2 = None

    PlaneAtB = None
    PlaneAtB_X = None
    PlaneAtB_Y = None

    base_point = globals().get("base_point", rg.Point3d.Origin)
    ref_plane_mode = globals().get("ref_plane_mode", "XZ Plane")
    Refresh = _bool(globals().get("Refresh", False), False)

    AB = _float(globals().get("AB", None), 10.0)
    BC = _float(globals().get("BC", None), 4.0)
    DE = _float(globals().get("DE", None), 0.5)
    IG = _float(globals().get("IG", None), 1.5)
    Offset = _float(globals().get("Offset", None), 5.0)
    Tol = _float(globals().get("Tol", None), sc.doc.ModelAbsoluteTolerance)

    ht = HuaTouZi(base_point=base_point, ref_plane_mode=ref_plane_mode, tol=Tol)
    ht.set_params(AB=AB, BC=BC, DE=DE, IG=IG, Offset=Offset, Tol=Tol)

    if Refresh:
        ht.log.append("Refresh=True: recompute triggered by button.")

    ht.build(reset=True)

    SolidBrep = ht.solid_brep
    SectionCrv = ht.section_crv
    SectionCrv_Pos = ht.section_crv_pos
    SectionCrv_Neg = ht.section_crv_neg
    LoftBrep = ht.loft_brep
    CapPosBrep = ht.cap_pos_brep
    CapNegBrep = ht.cap_neg_brep

    Pts_A, Pts_B, Pts_C = ht.A, ht.B, ht.C
    Pts_H, Pts_D, Pts_I = ht.H, ht.D, ht.I
    Pts_F, Pts_E, Pts_G = ht.F, ht.E, ht.G

    Arc1, Arc2 = ht.arc1, ht.arc2

    PlaneAtB = ht.plane_at_b
    PlaneAtB_X = ht.plane_at_b_x
    PlaneAtB_Y = ht.plane_at_b_y

    Log = ht.log

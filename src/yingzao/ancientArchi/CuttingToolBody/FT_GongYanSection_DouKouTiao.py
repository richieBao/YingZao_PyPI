# -*- coding: utf-8 -*-
import Rhino.Geometry as rg
import math

# =========================================================
# FT_GongYanSection_DouKouTiao (Class-based)
#
# 功能：
# 1) 生成闭合截面曲线：B-A-C-B'-D-G-F-E-B
# 2) 截面曲线 -> ProfilePlane / PlanarFace / ExtrudeSolid(Thickness, along SectionPlane.ZAxis)
# 3) 实体沿 SectionPlane.ZAxis 偏移复制 Offset
# 4) 输出以 E 点为原点的 3 个互相垂直参考平面
#
# 默认值：
#   GongYan_RadiusFen = 3
#   GongYan_LengthFen = 18
#   AnZhi_QiHeightFen = 4
#   AnZhi_ShaWidthFen = 2
#   AnZhi_OffsetFen   = 0.5
#   PingHeight        = 2
#   Thickness         = 1
#   Offset            = 9   (10-1)
#
# SectionPlane 默认：GH XZ Plane
#   X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
# =========================================================


class FT_GongYanSection_DouKouTiaoBuilder(object):
    """
    将原脚本封装为类，便于后续调用：
        builder = FT_GongYanSection_DouKouTiaoBuilder(SectionPlane, BasePoint, ...)
        builder.run()
        boundary = builder.section_boundary
        solid = builder.section_solid
        planes = builder.ref_planes
    """

    def __init__(self,
                 SectionPlane=None,
                 BasePoint=None,
                 GongYan_RadiusFen=None,
                 GongYan_LengthFen=None,
                 AnZhi_QiHeightFen=None,
                 AnZhi_ShaWidthFen=None,
                 AnZhi_OffsetFen=None,
                 GapFen=None,
                 PingHeight=None,
                 Thickness=None,
                 Offset=None,
                 tol=1e-6):
        self.log = []
        self.tol = float(tol)

        # ---- SectionPlane 默认：GH XZ Plane ----
        if SectionPlane is None:
            SectionPlane = rg.Plane(
                rg.Point3d(0, 0, 0),
                rg.Vector3d(1, 0, 0),
                rg.Vector3d(0, 0, 1)
            )
        if BasePoint is None:
            BasePoint = rg.Point3d(0, 0, 0)

        self.section_plane = SectionPlane
        self.base_point = BasePoint

        # ---- defaults ----
        self.gy_r = 3.0 if GongYan_RadiusFen is None else float(GongYan_RadiusFen)
        self.gy_L = 18.0 if GongYan_LengthFen is None else float(GongYan_LengthFen)

        self.az_qi_h = 4.0 if AnZhi_QiHeightFen is None else float(AnZhi_QiHeightFen)
        self.az_sha_w = 2.0 if AnZhi_ShaWidthFen is None else float(AnZhi_ShaWidthFen)
        self.az_off = 0.5 if AnZhi_OffsetFen is None else float(AnZhi_OffsetFen)

        self.gap = 0.0 if GapFen is None else float(GapFen)

        self.ping_h = 2.0 if PingHeight is None else float(PingHeight)
        self.thickness = 1.0 if Thickness is None else float(Thickness)
        self.offset = 9.0 if Offset is None else float(Offset)

        # ---- outputs / cached ----
        self.gongyan_lower = None          # E-F-G-D
        self.section_boundary = None       # closed boundary
        self.section_curves = []           # list of curves for debug
        self.debug_pts = []                # [A,B,E,F,G,D,Bp,C]

        self.profile_plane = None
        self.section_face = None
        self.section_solid = None
        self.section_solid_offset = None
        self.section_solids = None         # [solid, solid_offset]

        self.ref_plane_E = None
        self.perp_to_x_plane_E = None
        self.perp_to_y_plane_E = None
        self.ref_planes = None             # [RefPlane_E, PerpToXPlane_E, PerpToYPlane_E]

    # =========================================================
    # static helpers
    # =========================================================
    @staticmethod
    def _pt_uv(plane, u, v):
        return plane.PointAt(float(u), float(v))

    def _clamp_gongyan(self, r, L):
        if r <= 0:
            r = 3.0
            self.log.append("GongYan_RadiusFen <=0 -> 3.0")
        min_len = 2.0 * r + 0.01
        if L < min_len:
            L = min_len
            self.log.append("GongYan_LengthFen < 2*r -> {:.3f}".format(min_len))
        return r, L

    # =========================================================
    # Step 1: build GongYan lower curve (E-F-G-D)
    # =========================================================
    def build_gongyan_lower(self):
        r, L = self._clamp_gongyan(self.gy_r, self.gy_L)
        self.gy_r, self.gy_L = r, L

        pl = rg.Plane(self.base_point, self.section_plane.XAxis, self.section_plane.YAxis)

        E = self._pt_uv(pl, 0.0, 0.0)
        D = self._pt_uv(pl, L,   0.0)
        F = self._pt_uv(pl, r,  -r)
        G = self._pt_uv(pl, L-r, -r)

        # left arc: E -> F
        center_left = self._pt_uv(pl, r, 0.0)
        plane_cL = rg.Plane(center_left, pl.XAxis, pl.YAxis)
        uL = r * math.cos(-0.75 * math.pi)
        vL = r * math.sin(-0.75 * math.pi)
        mid_left = plane_cL.PointAt(uL, vL)
        arc_left = rg.Arc(E, mid_left, F)
        crv_left = rg.ArcCurve(arc_left)

        bottom = rg.Line(F, G).ToNurbsCurve()

        # right arc: G -> D
        center_right = self._pt_uv(pl, L-r, 0.0)
        plane_cR = rg.Plane(center_right, pl.XAxis, pl.YAxis)
        uR = r * math.cos(-0.25 * math.pi)
        vR = r * math.sin(-0.25 * math.pi)
        mid_right = plane_cR.PointAt(uR, vR)
        arc_right = rg.Arc(G, mid_right, D)
        crv_right = rg.ArcCurve(arc_right)

        joined = rg.Curve.JoinCurves([crv_left, bottom, crv_right], self.tol)
        if not joined:
            self.log.append("GongYanLower: JoinCurves failed")
            self.gongyan_lower = None
            return None, (E, F, G, D)

        self.log.append("GongYanLower: ok")
        self.gongyan_lower = joined[0]
        return self.gongyan_lower, (E, F, G, D)

    # =========================================================
    # Step 2: build AnZhi arc (original)
    # =========================================================
    def build_anzhi_arc_original(self, origin_point):
        qi_h = float(self.az_qi_h)
        sha_w = float(self.az_sha_w)
        off = float(self.az_off)

        if qi_h <= 0:
            qi_h = 4.0
            self.log.append("AnZhi_QiHeightFen <=0 -> 4.0")
        if sha_w <= 0:
            sha_w = 2.0
            self.log.append("AnZhi_ShaWidthFen <=0 -> 2.0")

        pl = rg.Plane(origin_point, self.section_plane.XAxis, self.section_plane.YAxis)

        C = pl.PointAt(0.0, qi_h)
        B = pl.PointAt(sha_w, 0.0)

        mid = rg.Point3d((C.X + B.X) * 0.5, (C.Y + B.Y) * 0.5, (C.Z + B.Z) * 0.5)
        chord = B - C
        perp = rg.Vector3d.CrossProduct(pl.ZAxis, chord)
        if rg.Vector3d.Multiply(perp, pl.YAxis) < 0:
            perp.Reverse()
        if not perp.Unitize():
            self.log.append("AnZhiArc: perp unitize failed")
            return None, (C, B)

        mid_offset = mid + perp * off
        arc = rg.Arc(C, mid_offset, B)
        if not arc.IsValid:
            self.log.append("AnZhiArc: invalid")
            return None, (C, B)

        self.log.append("AnZhiArc: ok (original)")
        return rg.ArcCurve(arc), (C, B)

    def rotate_curve_and_point_ccw90(self, curve, pivot_point, point_to_rotate):
        ang = 0.5 * math.pi
        rot = rg.Transform.Rotation(ang, self.section_plane.ZAxis, pivot_point)

        crv2 = curve.DuplicateCurve()
        crv2.Transform(rot)

        p2 = rg.Point3d(point_to_rotate)
        p2.Transform(rot)

        self.log.append("RotateCCW90 about C: ok")
        return crv2, p2

    def align_curve_by_two_points(self, curve, source_C, source_B, target_C, target_B):
        crv = curve.DuplicateCurve()

        v_src = rg.Vector3d(source_B - source_C)
        v_tgt = rg.Vector3d(target_B - target_C)

        if not v_src.Unitize():
            self.log.append("Align: source vec unitize failed")
            return crv
        if not v_tgt.Unitize():
            self.log.append("Align: target vec unitize failed")
            return crv

        x0 = rg.Transform.Translation(target_C - source_C)
        crv.Transform(x0)

        cross = rg.Vector3d.CrossProduct(v_src, v_tgt)
        dot = rg.Vector3d.Multiply(v_src, v_tgt)
        sign = rg.Vector3d.Multiply(cross, self.section_plane.ZAxis)
        ang = math.atan2(sign, dot)

        rot = rg.Transform.Rotation(ang, self.section_plane.ZAxis, target_C)
        crv.Transform(rot)

        self.log.append("Align: ang={:.3f} rad".format(ang))
        return crv

    def mirror_curve_about_fg_mid_perp(self, curve, mid_x_u, mid_y_v):
        origin = self.section_plane.PointAt(float(mid_x_u), float(mid_y_v), 0.0)
        mirror_plane = rg.Plane(origin, self.section_plane.YAxis, self.section_plane.ZAxis)
        xfm = rg.Transform.Mirror(mirror_plane)

        crv = curve.DuplicateCurve()
        crv.Transform(xfm)

        self.log.append("Mirror about FG-mid-perp: x={:.3f}, y={:.3f}".format(float(mid_x_u), float(mid_y_v)))
        return crv

    # =========================================================
    # Step 3: compose boundary section (B-A-C-B'-D-G-F-E-B)
    # =========================================================
    def build_section(self):
        gy_lower, (E, F, G, D) = self.build_gongyan_lower()
        if gy_lower is None:
            self.section_boundary = None
            return None

        L = float(self.gy_L)
        r = float(self.gy_r)

        # C 对齐 E；C' 对齐 D
        B  = rg.Point3d(E + self.section_plane.XAxis * self.az_sha_w + self.section_plane.YAxis * (self.az_qi_h + self.gap))
        Bp = rg.Point3d(D - self.section_plane.XAxis * self.az_sha_w + self.section_plane.YAxis * (self.az_qi_h + self.gap))

        # 平高：B->A, B'->C, A->C
        A  = rg.Point3d(B  + self.section_plane.YAxis * self.ping_h)
        C  = rg.Point3d(Bp + self.section_plane.YAxis * self.ping_h)

        seg_BA = rg.Line(B, A).ToNurbsCurve()
        seg_AC = rg.Line(A, C).ToNurbsCurve()
        seg_CBp = rg.Line(C, Bp).ToNurbsCurve()

        # 左闇栔弧：E->B
        az_arc0, (C0, B0) = self.build_anzhi_arc_original(rg.Point3d(0, 0, 0))
        if az_arc0 is None:
            self.section_boundary = None
            self.debug_pts = [A, B, E, F, G, D, Bp, C]
            return None

        az_arc1, B1 = self.rotate_curve_and_point_ccw90(az_arc0, C0, B0)
        left_arc = self.align_curve_by_two_points(az_arc1, C0, B1, E, B)

        # 右闇栔弧：镜像得到 B'->D
        mid_x = 0.5 * L
        mid_y = -r
        right_arc = self.mirror_curve_about_fg_mid_perp(left_arc, mid_x, mid_y)

        # 数值安全：把右弧“靠近D的端”平移到 D
        try:
            ds = right_arc.PointAtStart.DistanceTo(D)
            de = right_arc.PointAtEnd.DistanceTo(D)
            pD = right_arc.PointAtStart if ds <= de else right_arc.PointAtEnd
            dd = D - pD
            if dd.Length > self.tol:
                right_arc.Transform(rg.Transform.Translation(dd))
        except:
            pass

        # 统一方向
        left2 = left_arc.DuplicateCurve()
        if left2.PointAtStart.DistanceTo(E) > left2.PointAtEnd.DistanceTo(E):
            left2.Reverse()

        right2 = right_arc.DuplicateCurve()
        if right2.PointAtStart.DistanceTo(Bp) > right2.PointAtEnd.DistanceTo(Bp):
            right2.Reverse()
        if right2.PointAtEnd.DistanceTo(D) > right2.PointAtStart.DistanceTo(D):
            right2.Reverse()

        gy2 = gy_lower.DuplicateCurve()
        if gy2.PointAtStart.DistanceTo(D) > gy2.PointAtEnd.DistanceTo(D):
            gy2.Reverse()

        # Join：B->A->C->B' + B'->D + D->E + E->B
        segs = [seg_BA, seg_AC, seg_CBp, right2, gy2, left2]
        joined = rg.Curve.JoinCurves(segs, self.tol)

        if not joined:
            self.log.append("Compose(PingHeight): JoinCurves failed")
            self.section_boundary = None
            self.debug_pts = [A, B, E, F, G, D, Bp, C]
            return None

        boundary = joined[0]
        if not boundary.IsClosed:
            boundary.MakeClosed(self.tol)

        self.log.append("Compose(PingHeight): closed={}".format(boundary.IsClosed))

        # cache outputs
        self.section_boundary = boundary
        self.section_curves = []
        if gy_lower is not None:
            self.section_curves.append(gy_lower)
        if boundary is not None:
            self.section_curves.append(boundary)

        self.debug_pts = [A, B, E, F, G, D, Bp, C]
        return boundary

    # =========================================================
    # Step 4: section curve -> plane/face/solid
    # =========================================================
    def build_solid(self):
        section_crv = self.section_boundary
        if section_crv is None or (not section_crv.IsValid):
            self.log.append("Solid: section_crv invalid")
            self.profile_plane = None
            self.section_face = None
            self.section_solid = None
            return None

        t = float(self.thickness)
        if abs(t) < 1e-12:
            t = 1.0
            self.log.append("Thickness=0 -> 1.0")
        self.thickness = t

        # plane
        ok, pl_out = section_crv.TryGetPlane()
        if ok:
            pl = pl_out
        else:
            pl = rg.Plane(self.base_point, self.section_plane.XAxis, self.section_plane.YAxis)
            self.log.append("ProfilePlane: TryGetPlane failed -> fallback to SectionPlane @ BasePoint")

        # planar face (optional)
        planar_breps = rg.Brep.CreatePlanarBreps(section_crv, self.tol)
        section_face = planar_breps[0] if planar_breps and len(planar_breps) > 0 else None
        if section_face is None:
            self.log.append("SectionFace: CreatePlanarBreps failed (still try extrusion)")

        # extrude direction (perpendicular to reference plane)
        dir_vec = rg.Vector3d(self.section_plane.ZAxis)
        if not dir_vec.Unitize():
            self.log.append("Solid: SectionPlane.ZAxis unitize failed")
            self.profile_plane = pl
            self.section_face = section_face
            self.section_solid = None
            return None
        dir_vec *= t

        solid = None
        try:
            srf = rg.Surface.CreateExtrusion(section_crv, dir_vec)
            if srf is None:
                self.log.append("Solid: Surface.CreateExtrusion failed (returned None)")
            else:
                brep = srf.ToBrep()
                if brep is None:
                    brep = rg.Brep.CreateFromSurface(srf)
                solid = brep
        except Exception as e:
            self.log.append("Solid: CreateExtrusion exception: {}".format(e))
            solid = None

        if solid is None:
            self.log.append("Solid: failed")
            self.profile_plane = pl
            self.section_face = section_face
            self.section_solid = None
            return None

        # cap
        try:
            capped = solid.CapPlanarHoles(self.tol)
            if capped is not None:
                solid = capped
        except Exception as e:
            self.log.append("Solid: CapPlanarHoles exception: {}".format(e))

        self.log.append("Solid: ok, IsSolid={}".format(solid.IsSolid))

        self.profile_plane = pl
        self.section_face = section_face
        self.section_solid = solid
        return solid

    # =========================================================
    # Step 5: offset copy solid along Z
    # =========================================================
    def build_offset_copy(self):
        if self.section_solid is None:
            self.log.append("OffsetSolid: solid is None")
            self.section_solid_offset = None
            return None

        d = float(self.offset)
        v = rg.Vector3d(self.section_plane.ZAxis)
        if not v.Unitize():
            self.log.append("OffsetSolid: ZAxis unitize failed")
            self.section_solid_offset = None
            return None
        v *= d

        dup = self.section_solid.DuplicateBrep()
        dup.Transform(rg.Transform.Translation(v))
        self.log.append("OffsetSolid: ok, dist={}".format(d))

        self.section_solid_offset = dup
        self.section_solids = [self.section_solid, self.section_solid_offset]
        return dup

    # =========================================================
    # Step 6: three orthogonal planes at E
    # =========================================================
    def build_ref_planes(self):
        E_pt = None
        try:
            if self.debug_pts and len(self.debug_pts) >= 3:
                E_pt = self.debug_pts[2]  # [A,B,E,...]
        except:
            E_pt = None

        if E_pt is None:
            self.log.append("RefPlanes@E: failed (E_pt is None)")
            self.ref_plane_E = None
            self.perp_to_x_plane_E = None
            self.perp_to_y_plane_E = None
            self.ref_planes = None
            return None

        refE = rg.Plane(E_pt, self.section_plane.XAxis, self.section_plane.YAxis)
        perpX = rg.Plane(E_pt, self.section_plane.YAxis, self.section_plane.ZAxis)   # normal = X
        perpY = rg.Plane(E_pt, self.section_plane.ZAxis, self.section_plane.XAxis)   # normal = Y

        self.ref_plane_E = refE
        self.perp_to_x_plane_E = perpX
        self.perp_to_y_plane_E = perpY
        self.ref_planes = [refE, perpX, perpY]
        self.log.append("RefPlanes@E: ok")
        return self.ref_planes

    # =========================================================
    # run all
    # =========================================================
    def run(self):
        self.build_section()
        self.build_solid()
        self.build_offset_copy()
        self.build_ref_planes()
        self.log.append("Done.")
        return self

if __name__ == "__main__":
    # =========================================================
    # GhPython 主入口（输出绑定）
    # =========================================================
    Log = []
    DebugPts = []
    SectionCurves = []
    GongYanSectionCrv = None
    AnZhiSectionCrv = None

    ProfilePlane = None
    SectionFaceBrep = None
    SectionSolidBrep = None
    SectionSolidBrep_Offset = None
    SectionSolidBreps = None

    RefPlane_E = None
    PerpToXPlane_E = None
    PerpToYPlane_E = None
    RefPlane = None

    # ---- 读取输入并给默认值（保持你之前“输入端可缺省”风格）----
    try:
        _sp = SectionPlane
    except:
        _sp = None

    try:
        _bp = BasePoint
    except:
        _bp = None

    try:
        _gy_r = GongYan_RadiusFen
    except:
        _gy_r = None

    try:
        _gy_L = GongYan_LengthFen
    except:
        _gy_L = None

    try:
        _az_qh = AnZhi_QiHeightFen
    except:
        _az_qh = None

    try:
        _az_sw = AnZhi_ShaWidthFen
    except:
        _az_sw = None

    try:
        _az_of = AnZhi_OffsetFen
    except:
        _az_of = None

    try:
        _gap = GapFen
    except:
        _gap = None

    try:
        _ph = PingHeight
    except:
        _ph = None

    try:
        _th = Thickness
    except:
        _th = None

    try:
        _off = Offset
    except:
        _off = None

    # ---- build ----
    builder = FT_GongYanSection_DouKouTiaoBuilder(
        SectionPlane=_sp,
        BasePoint=_bp,
        GongYan_RadiusFen=_gy_r,
        GongYan_LengthFen=_gy_L,
        AnZhi_QiHeightFen=_az_qh,
        AnZhi_ShaWidthFen=_az_sw,
        AnZhi_OffsetFen=_az_of,
        GapFen=_gap,
        PingHeight=_ph,
        Thickness=_th,
        Offset=_off,
        tol=1e-6
    ).run()

    # ---- outputs ----
    Log = builder.log

    DebugPts = builder.debug_pts
    SectionCurves = builder.section_curves

    GongYanSectionCrv = builder.gongyan_lower
    AnZhiSectionCrv = builder.section_boundary

    ProfilePlane = builder.profile_plane
    SectionFaceBrep = builder.section_face

    SectionSolidBrep = builder.section_solid
    SectionSolidBrep_Offset = builder.section_solid_offset
    SectionSolidBreps = builder.section_solids

    RefPlane_E = builder.ref_plane_E
    PerpToXPlane_E = builder.perp_to_x_plane_E
    PerpToYPlane_E = builder.perp_to_y_plane_E
    RefPlane = builder.ref_planes

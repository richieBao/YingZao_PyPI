# -*- coding: utf-8 -*-
"""
FT_ShuaTouTool (v1.8)

几何要点：
- D = BasePoint（左下角）
- SideSectionFace = H-L-C-D-A-H
- OffsetSideFaces = SideSectionFace 沿 RefPlane.ZAxis ± OffsetFen 偏移
- OffsetSideCrvs  = SideSectionCrv 沿 RefPlane.ZAxis ± OffsetFen 偏移
- SideLoftFace    = Straight Loft(OffsetSideCrvs[0], I-K-E, OffsetSideCrvs[1])
- TriFace         = 三角面(H'_neg, I, H'_pos)
- H'AD'Loft       = Straight Loft( H'_neg-A'_neg-D'_neg, H'_pos-A'_pos-D'_pos )
- BottomFace      = 由 D'_neg, C'_neg, E, C'_pos, D'_pos 外围封闭（三个三角面拼合）
- ToolBrep        = Join( SideLoftFace, TriFace, H'AD'Loft, BottomFace, OffsetSideFaces )
- RefPlanes       = [
    过 BasePoint 的 RefPlane 同向平面,
    过 BasePoint 的“水平”参考平面（RefPlane 沿 X 轴旋转 90°）
  ]
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import math


# ================================
# 默认值处理
# ================================
def _default_point(p):
    return p if (p is not None) else rg.Point3d(0, 0, 0)

def _default_plane(pl):
    if pl is not None:
        return pl
    origin = rg.Point3d(0, 0, 0)
    xaxis  = rg.Vector3d(1, 0, 0)
    yaxis  = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, xaxis, yaxis)

def _default_float(x, v):
    try:
        return float(x)
    except:
        return v


class ShuaTouBuilder(object):

    @staticmethod
    def build(base_point, ref_plane,
              width_fen, height_fen,
              AH_fen, DF_fen, FE_fen, EC_fen,
              DG_fen, offset_fen):

        # -------- 默认值 --------
        base_point = _default_point(base_point)
        ref_plane  = _default_plane(ref_plane)
        width_fen  = _default_float(width_fen,  16)
        height_fen = _default_float(height_fen, 15)
        AH_fen     = _default_float(AH_fen,     5)
        DF_fen     = _default_float(DF_fen,     6)
        FE_fen     = _default_float(FE_fen,     5)
        EC_fen     = _default_float(EC_fen,     5)
        DG_fen     = _default_float(DG_fen,     2)
        offset_fen = _default_float(offset_fen, 5)

        tol = sc.doc.ModelAbsoluteTolerance

        log = []
        dbg_pts = []
        dbg_lines = []

        log.append("=== FT_ShuaTouTool v1.8 START ===")
        log.append("RefPlane: Origin={0}, X={1}, Y={2}, Z={3}".format(
            ref_plane.Origin, ref_plane.XAxis, ref_plane.YAxis, ref_plane.ZAxis))

        # ------------------------------------------------------
        # 0. 主要参考平面 RefPlanes
        # ------------------------------------------------------
        # 过 BasePoint 的 RefPlane 同向平面
        base_ref_plane = rg.Plane(base_point, ref_plane.XAxis, ref_plane.YAxis)

        # 过 BasePoint 的“水平”平面：由 base_ref_plane 围绕 X 轴旋转 90°
        xy_like_plane = rg.Plane(base_ref_plane)
        rot = rg.Transform.Rotation(math.radians(90.0), base_ref_plane.XAxis, base_point)
        xy_like_plane.Transform(rot)

        RefPlanes = [base_ref_plane, xy_like_plane]

        # ------------------------------------------------------
        # 1. 基础矩形 A B C D（D = BasePoint）
        # ------------------------------------------------------
        A, B, C, D = ShuaTouBuilder._build_base_rect(
            base_point, ref_plane, width_fen, height_fen)
        dbg_pts.extend([A, B, C, D])

        # ------------------------------------------------------
        # 2. 构建关键点
        # ------------------------------------------------------
        H, F, E, G, J, K, I, L, aux_lines = \
            ShuaTouBuilder._build_key_points(
                A, B, C, D,
                AH_fen, DF_fen, FE_fen, DG_fen,
                ref_plane, log)

        dbg_pts.extend([H, F, E, G, J, K, I, L])
        dbg_lines.extend(aux_lines)

        # ------------------------------------------------------
        # 3. 中心截面线 / 面
        # ------------------------------------------------------
        CenterSectionCrv = rg.Polyline([H, I, K, E]).ToNurbsCurve()

        center_face_poly = rg.Polyline([H, I, K, E, D, A, H]).ToNurbsCurve()
        cf = rg.Brep.CreatePlanarBreps(center_face_poly)
        CenterSectionFace = cf[0] if cf else None

        # ------------------------------------------------------
        # 4. 侧截面线 / 面
        # ------------------------------------------------------
        SideSectionCrv = rg.Polyline([H, L, C]).ToNurbsCurve()

        side_face_poly = rg.Polyline([H, L, C, D, A, H]).ToNurbsCurve()
        sf = rg.Brep.CreatePlanarBreps(side_face_poly)
        SideSectionFace = sf[0] if sf else None

        # ------------------------------------------------------
        # 5. 两侧偏移：关键点 & 截面线 / 面
        # ------------------------------------------------------
        normal = ref_plane.ZAxis
        n_vec  = normal * offset_fen

        # 关键点偏移（全部新建 Point3d）
        H_neg = H + (-n_vec)
        L_neg = L + (-n_vec)
        C_neg = C + (-n_vec)
        A_neg = A + (-n_vec)
        D_neg = D + (-n_vec)

        H_pos = H + n_vec
        L_pos = L + n_vec
        C_pos = C + n_vec
        A_pos = A + n_vec
        D_pos = D + n_vec

        # 面偏移
        OffsetSideFaces = []
        if SideSectionFace:
            T_neg = rg.Transform.Translation(-n_vec)
            T_pos = rg.Transform.Translation( n_vec)

            face_neg = SideSectionFace.DuplicateBrep()
            face_neg.Transform(T_neg)
            face_pos = SideSectionFace.DuplicateBrep()
            face_pos.Transform(T_pos)

            OffsetSideFaces = [face_neg, face_pos]

        # 曲线偏移
        OffsetSideCrvs = []
        if SideSectionCrv:
            T_neg_c = rg.Transform.Translation(-n_vec)
            T_pos_c = rg.Transform.Translation( n_vec)

            crv_neg = SideSectionCrv.DuplicateCurve()
            crv_neg.Transform(T_neg_c)
            crv_pos = SideSectionCrv.DuplicateCurve()
            crv_pos.Transform(T_pos_c)

            OffsetSideCrvs = [crv_neg, crv_pos]

        # ------------------------------------------------------
        # 6. SideLoftFace：直线放样
        # ------------------------------------------------------
        SideLoftFace = None
        if len(OffsetSideCrvs) == 2:
            IKELine = rg.Polyline([I, K, E]).ToNurbsCurve()

            loft_curves = [OffsetSideCrvs[0], IKELine, OffsetSideCrvs[1]]

            loft = rg.Brep.CreateFromLoft(
                loft_curves,
                rg.Point3d.Unset,
                rg.Point3d.Unset,
                rg.LoftType.Straight,
                False
            )

            if loft:
                SideLoftFace = loft[0]
                log.append("SideLoftFace created (Straight Loft).")
            else:
                log.append("Loft failed - SideLoftFace is None.")
        else:
            log.append("OffsetSideCrvs != 2, cannot loft SideLoftFace.")

        # ------------------------------------------------------
        # 7. TriFace：三角面 H'_neg – I – H'_pos
        # ------------------------------------------------------
        TriFace = None
        tri_brep = rg.Brep.CreateFromCornerPoints(H_neg, I, H_pos, tol)
        if tri_brep:
            TriFace = tri_brep
            log.append("TriFace created (H_neg, I, H_pos).")
        else:
            log.append("TriFace creation failed (points may be collinear).")

        # ------------------------------------------------------
        # 8. H'AD'Loft：两侧偏移后的 H'-A'-D' 直线放样
        # ------------------------------------------------------
        HADLoftFace = None
        had_crv_neg = rg.Polyline([H_neg, A_neg, D_neg]).ToNurbsCurve()
        had_crv_pos = rg.Polyline([H_pos, A_pos, D_pos]).ToNurbsCurve()

        had_loft = rg.Brep.CreateFromLoft(
            [had_crv_neg, had_crv_pos],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Straight,
            False
        )

        if had_loft:
            HADLoftFace = had_loft[0]
            log.append("H'AD'Loft created (Straight Loft).")
        else:
            log.append("H'AD'Loft creation failed.")

        # ------------------------------------------------------
        # 9. BottomFace：D'_neg, C'_neg, E, C'_pos, D'_pos 外围封闭
        # ------------------------------------------------------
        BottomFace = None
        bottom_tris = []

        t1 = rg.Brep.CreateFromCornerPoints(D_neg, C_neg, E, tol)
        if t1: bottom_tris.append(t1)
        t2 = rg.Brep.CreateFromCornerPoints(E, C_pos, D_pos, tol)
        if t2: bottom_tris.append(t2)
        t3 = rg.Brep.CreateFromCornerPoints(D_neg, E, D_pos, tol)
        if t3: bottom_tris.append(t3)

        if bottom_tris:
            joined_bottom = rg.Brep.JoinBreps(bottom_tris, tol)
            if joined_bottom and len(joined_bottom) > 0:
                BottomFace = joined_bottom[0]
                log.append("BottomFace created from {0} triangles.".format(len(bottom_tris)))
            else:
                log.append("JoinBreps failed for BottomFace.")
        else:
            log.append("No triangles created for BottomFace.")

        # ------------------------------------------------------
        # 10. Join 所有面 → ToolBrep
        # ------------------------------------------------------
        ToolBrep = None
        join_list = []

        if SideLoftFace:   join_list.append(SideLoftFace)
        if TriFace:        join_list.append(TriFace)
        if HADLoftFace:    join_list.append(HADLoftFace)
        if BottomFace:     join_list.append(BottomFace)
        if OffsetSideFaces:
            join_list.extend([f for f in OffsetSideFaces if f is not None])

        if join_list:
            joined = rg.Brep.JoinBreps(join_list, tol)
            if joined and len(joined) > 0:
                ToolBrep = joined[0]
                log.append("ToolBrep joined from {0} breps.".format(len(join_list)))

                # 尝试 Cap（如果存在开口）
                if not ToolBrep.IsSolid:
                    if ToolBrep.CapPlanarHoles(tol):
                        log.append("ToolBrep CapPlanarHoles succeeded, solid = {0}".format(ToolBrep.IsSolid))
                    else:
                        log.append("CapPlanarHoles did not fully close ToolBrep.")
        else:
            log.append("No breps to join for ToolBrep.")

        log.append("=== FT_ShuaTouTool v1.8 END ===")

        return (CenterSectionCrv,
                SideSectionCrv,
                CenterSectionFace,
                SideSectionFace,
                OffsetSideFaces,
                OffsetSideCrvs,
                SideLoftFace,
                ToolBrep,
                RefPlanes,
                dbg_pts,
                dbg_lines,
                log)

    # =======================
    # 基础矩形
    # =======================
    @staticmethod
    def _build_base_rect(base_point, plane, width, height):
        X = plane.XAxis
        Y = plane.YAxis
        D = base_point
        C = D + X * width
        A = D + Y * height
        B = A + X * width
        return A, B, C, D

    # =======================
    # 关键点
    # =======================
    @staticmethod
    def _build_key_points(A, B, C, D,
                          AH, DF, FE, DG,
                          plane, log):
        X = plane.XAxis
        Y = plane.YAxis

        H = A + X * AH
        F = D + X * DF
        E = F + X * FE
        G = D + Y * DG

        BC = rg.Line(B, C)
        GJ = rg.Line(G, G + X * 500)

        rc, t1, t2 = rg.Intersect.Intersection.LineLine(GJ, BC)
        J = GJ.PointAt(t1) if rc else C

        AF = rg.Line(A, F)
        rc2, t3, t4 = rg.Intersect.Intersection.LineLine(AF, GJ)
        K = AF.PointAt(t3) if rc2 else F

        I = ShuaTouBuilder._perpendicular_foot(H, A, F)

        HL = rg.Line(H, H + (F - A) * 200)
        rc3, t5, t6 = rg.Intersect.Intersection.LineLine(HL, GJ)
        L = HL.PointAt(t5) if rc3 else H

        aux = [
            AF.ToNurbsCurve(),
            GJ.ToNurbsCurve(),
            HL.ToNurbsCurve(),
            BC.ToNurbsCurve()
        ]
        return H, F, E, G, J, K, I, L, aux

    @staticmethod
    def _perpendicular_foot(P, A, B):
        line = rg.Line(A, B)
        t = line.ClosestParameter(P)
        return line.PointAt(t)

if __name__ == '__main__':
    # =======================
    # GH Python 输出
    # =======================
    (CenterSectionCrv,
     SideSectionCrv,
     CenterSectionFace,
     SideSectionFace,
     OffsetSideFaces,
     OffsetSideCrvs,
     SideLoftFace,
     ToolBrep,
     RefPlanes,
     DebugPoints,
     DebugLines,
     Log) = ShuaTouBuilder.build(
        BasePoint,
        RefPlane,
        WidthFen,
        HeightFen,
        AH_Fen,
        DF_Fen,
        FE_Fen,
        EC_Fen,
        DG_Fen,
        OffsetFen
    )

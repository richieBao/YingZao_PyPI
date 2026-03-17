# -*- coding: utf-8 -*-
"""
SuoZhuJuanShaToolBuilder
殺梭柱之制 · 梭柱卷殺刀具（旋转成体）构建器

（本版修复要点）
- 修复 “Line-Plane 求交” 的 RhinoCommon Python 返回值差异：
  Intersection.LinePlane(...) 在不同环境可能返回：
    1) None（平行无交）
    2) float (t)
    3) (bool, t)
    4) (t) 但 t 为 System.Double
  旧版把返回值强转 float，遇到 (bool, t) 会失败，从而误报：
    ERROR: cannot intersect F-B with moved plane at I => J.
  本版 _line_plane_intersection() 做了全兼容解析，并允许 t 超出[0,1]（按“直线段/延长线”等价处理）。

几何步骤摘要（同你原描述，命名新旧对照见下）：
1) O 为 BasePlane（旧 RefPlane）原点；沿 X 得 A（OA=SuoZhuRadius/旧Radius）
   OA 上取 B、C：AB=JuanShaLen_AB/旧AB，BC=JuanShaLen_BC/旧BC；AB 三等分得 D/E
2) 以 A 沿 -Z 得 H（AH=SuoZhuHeight_AH/旧AH）；AH 三等分得 F/G
3) HD ∩ GE = L；GE ∩ FB = K
4) 以 C 沿 -Z 得 I（CI=JuanShaDrop_CI/旧CI），把 BasePlane 平移到 I 得 PlaneI；
   PlaneI 与 “直线(段) F-B 的延长线”等价求交得 J
   由 OA 与 AH 构成垂直于 BasePlane 的平面 P'；
   在 P' 上作 C-J 圆弧，严格与两条给定母线相切（默认 OA 与 BF；失败则用 OC 与 JF 兜底）
5) 弧 C-J + JK + KL + LH -> SectionOutlineCrv（旧 OutlineCrv）
   加 A-C 与 A-H 封闭 -> SectionProfileCrv（旧 ProfileCrv） -> SectionFace（旧 ProfileFace）
6) 以 BasePlane.ZAxis 过 O 为轴旋转一周 -> JuanShaToolBrep（旧 ToolBrep）

----------------------------------------------------------------------
输入（GhPython 建议设置）:
    BasePlane : rg.Plane (Item)      （旧名 RefPlane）
    SuoZhuRadius : float (Item)      （旧名 Radius）
    JuanShaLen_AB : float (Item)     （旧名 AB）
    JuanShaLen_BC : float (Item)     （旧名 BC）
    SuoZhuHeight_AH : float (Item)   （旧名 AH）
    JuanShaDrop_CI : float (Item)    （旧名 CI）
    Tolerance : float (Item)         （旧名 Tol）

输出（GhPython 建议设置）:
    JuanShaToolBrep : rg.Brep (Item)         （旧名 ToolBrep）
    SectionProfileCrv : rg.Curve (Item)      （旧名 ProfileCrv）
    SectionOutlineCrv : rg.Curve (Item)      （旧名 OutlineCrv）
    SectionFace : rg.Brep (Item)             （旧名 ProfileFace）
    KeyPts : list[rg.Point3d] (List)         （旧名 Pts）
    GuideCrvs : list[rg.Curve] (List)        （旧名 AuxCrvs）
    DebugLog : str (Item)                    （旧名 Log）
"""

import Rhino
import Rhino.Geometry as rg
import math


# ----------------------------
# 小工具
# ----------------------------
def _is_valid_number(x):
    try:
        return x is not None and float(x) == float(x)
    except Exception:
        return False


def _safe_unitize(v, tol=1e-12):
    vv = rg.Vector3d(v)
    if vv.IsTiny(tol):
        return rg.Vector3d(0, 0, 0), False
    vv.Unitize()
    return vv, True


def _line_line_intersection_3d(lineA, lineB, tol=1e-7):
    """
    返回 (ok, point, ta, tb)
    """
    ok, ta, tb = rg.Intersect.Intersection.LineLine(lineA, lineB, tol, False)
    if not ok:
        return False, rg.Point3d.Unset, None, None
    pa = lineA.PointAt(ta)
    pb = lineB.PointAt(tb)
    p = (pa + pb) * 0.5
    return True, p, ta, tb


def _parse_lineplane_result(res):
    """
    兼容 RhinoCommon Python 不同返回形式：
    - None
    - float
    - (bool, t)
    - (t,)
    """
    if res is None:
        return False, None
    # tuple/list
    if isinstance(res, (tuple, list)):
        if len(res) == 0:
            return False, None
        if len(res) == 1:
            try:
                return True, float(res[0])
            except Exception:
                return False, None
        # 常见： (bool, t)
        if len(res) >= 2:
            b = res[0]
            t = res[1]
            try:
                bb = bool(b)
            except Exception:
                bb = True
            try:
                tt = float(t)
            except Exception:
                return False, None
            return bb, tt
    # scalar
    try:
        return True, float(res)
    except Exception:
        return False, None


def _line_plane_intersection(line, plane, tol=1e-7):
    """
    返回 (ok, point, t)
    - 注意：t 的语义在不同 RhinoCommon 绑定里可能是：
      a) 0~1 归一化参数（Line.PointAt(t)）
      b) 以 line.Direction 为基的参数（Line.PointAt(t) 仍可用，但可能超出 0~1）
    本函数统一：直接用 line.PointAt(t)；不限制 t 范围（允许延长线交点）
    """
    res = rg.Intersect.Intersection.LinePlane(line, plane)
    ok, t = _parse_lineplane_result(res)
    if not ok or t is None:
        return False, rg.Point3d.Unset, None
    try:
        p = line.PointAt(t)
    except Exception:
        # 兜底：用 From + Direction * t（某些绑定 t 是“距离参数”时也可成立）
        try:
            p = line.From + line.Direction * t
        except Exception:
            return False, rg.Point3d.Unset, None
    return True, p, t


def _strict_tangent_arc_CJ_in_plane(C, J, Pprime, tanC_vec3, tanJ_vec3, tol=1e-7):
    """
    在平面 Pprime 内构造严格相切圆弧 C->J：
    - 弧在 Pprime 平面内
    - C 端切向方向 = tanC_vec3 投影到 Pprime
    - J 端切向方向 = tanJ_vec3 投影到 Pprime

    2D 严格解：
    圆心 = 过 C 点、沿“切向法线”的直线  与  过 J 点、沿“切向法线”的直线 的交点

    返回 (curve_or_None, log)
    """
    log = ""

    okC2, uC, vC = Pprime.ClosestParameter(C)
    okJ2, uJ, vJ = Pprime.ClosestParameter(J)
    if not okC2 or not okJ2:
        return None, "ERROR: ClosestParameter failed for C or J on P'.\n"

    C2 = rg.Point2d(uC, vC)
    J2 = rg.Point2d(uJ, vJ)

    n = Pprime.Normal

    def _proj_to_plane(v):
        vv = rg.Vector3d(v)
        vv = vv - rg.Vector3d.Multiply(vv * n, n)  # remove normal component
        vvU, ok = _safe_unitize(vv, tol=1e-12)
        return vvU, ok

    tC3, okTC = _proj_to_plane(tanC_vec3)
    tJ3, okTJ = _proj_to_plane(tanJ_vec3)
    if not okTC or not okTJ:
        return None, "ERROR: Tangent vectors too small after projection to P'.\n"

    def _vec3_to_vec2(v3):
        # Origin 对应 (0,0) 参数
        pt = Pprime.Origin + v3
        okp, uu, vv = Pprime.ClosestParameter(pt)
        if not okp:
            return None, False
        v2 = rg.Vector2d(uu, vv)
        if v2.IsTiny(tol * 10.0):
            return None, False
        v2.Unitize()
        return v2, True

    tC2, ok1 = _vec3_to_vec2(tC3)
    tJ2, ok2 = _vec3_to_vec2(tJ3)
    if not ok1 or not ok2:
        return None, "ERROR: Failed to convert tangents to 2D on P'.\n"

    def perp(v2):
        return rg.Vector2d(-v2.Y, v2.X)

    nC2 = perp(tC2)
    nJ2 = perp(tJ2)

    rhs = rg.Vector2d(J2.X - C2.X, J2.Y - C2.Y)

    a11 = nC2.X
    a12 = -nJ2.X
    a21 = nC2.Y
    a22 = -nJ2.Y
    det = a11 * a22 - a12 * a21

    if abs(det) < max(tol, 1e-12):
        return None, "ERROR: Tangent normals nearly parallel in 2D; cannot construct unique arc.\n"

    s = (rhs.X * a22 - rhs.Y * a12) / det
    center2 = rg.Point2d(C2.X + nC2.X * s, C2.Y + nC2.Y * s)

    center3 = Pprime.PointAt(center2.X, center2.Y)
    r = center3.DistanceTo(C)
    if r <= max(tol * 10.0, 1e-9):
        return None, "ERROR: Radius too small.\n"

        # 构造圆：为避免不同 RhinoCommon 绑定下 Circle(Plane, Point3d, r) 重载不一致，
    # 这里统一使用 Circle(Plane_at_center, r)
    plane_at_center = rg.Plane(Pprime)
    plane_at_center.Origin = center3
    circle = rg.Circle(plane_at_center, r)
    if not circle.IsValid:
        return None, "ERROR: Circle invalid.\n"

    okpC, tCpar = circle.ClosestParameter(C)
    okpJ, tJpar = circle.ClosestParameter(J)
    if not okpC or not okpJ:
        return None, "ERROR: Circle parameterization failed for C or J.\n"

    arc = rg.Arc(circle, rg.Interval(tCpar, tJpar))
    if not arc.IsValid:
        return None, "ERROR: Arc invalid.\n"

    log += "INFO: Strict tangent arc C-J constructed on P'.\n"
    return rg.ArcCurve(arc), log


# ----------------------------
# 主类
# ----------------------------
class SuoZhuJuanShaToolBuilder(object):
    def __init__(self,
                 base_plane,
                 suo_zhu_radius,
                 juansha_len_ab=5.0,
                 juansha_len_bc=4.0,
                 suo_zhu_height_ah=10.0,
                 juansha_drop_ci=4.0,
                 tolerance=1e-7):

        # ---- inputs (new names) ----
        self.BasePlane = base_plane if isinstance(base_plane, rg.Plane) else rg.Plane.WorldXY
        self.SuoZhuRadius = float(suo_zhu_radius) if _is_valid_number(suo_zhu_radius) else 10.0
        self.JuanShaLen_AB = float(juansha_len_ab) if _is_valid_number(juansha_len_ab) else 5.0
        self.JuanShaLen_BC = float(juansha_len_bc) if _is_valid_number(juansha_len_bc) else 4.0
        self.SuoZhuHeight_AH = float(suo_zhu_height_ah) if _is_valid_number(suo_zhu_height_ah) else 10.0
        self.JuanShaDrop_CI = float(juansha_drop_ci) if _is_valid_number(juansha_drop_ci) else 4.0
        self.Tolerance = float(tolerance) if _is_valid_number(tolerance) else 1e-7

        # ---- debug / storage (new names) ----
        self.DebugLog = ""
        self.KeyPts = []
        self.GuideCrvs = []

        self.SectionOutlineCrv = None
        self.SectionProfileCrv = None
        self.SectionFace = None
        self.JuanShaToolBrep = None

        # ---- legacy aliases (old names) for verification ----
        self.RefPlane = self.BasePlane
        self.Radius = self.SuoZhuRadius
        self.AB = self.JuanShaLen_AB
        self.BC = self.JuanShaLen_BC
        self.AH = self.SuoZhuHeight_AH
        self.CI = self.JuanShaDrop_CI
        self.Tol = self.Tolerance

        self.Log = self.DebugLog
        self.Pts = self.KeyPts
        self.AuxCrvs = self.GuideCrvs
        self.OutlineCrv = self.SectionOutlineCrv
        self.ProfileCrv = self.SectionProfileCrv
        self.ProfileFace = self.SectionFace
        self.ToolBrep = self.JuanShaToolBrep

        self._build()
        self._sync_legacy_outputs()

    def _sync_legacy_outputs(self):
        self.Log = self.DebugLog
        self.Pts = self.KeyPts
        self.AuxCrvs = self.GuideCrvs
        self.OutlineCrv = self.SectionOutlineCrv
        self.ProfileCrv = self.SectionProfileCrv
        self.ProfileFace = self.SectionFace
        self.ToolBrep = self.JuanShaToolBrep

    def _build(self):
        tol = self.Tolerance

        P = rg.Plane(self.BasePlane)
        O = P.Origin
        x = rg.Vector3d(P.XAxis)
        z = rg.Vector3d(P.ZAxis)

        xU, okx = _safe_unitize(x)
        zU, okz = _safe_unitize(z)
        if not okx or not okz:
            self.DebugLog += "ERROR: BasePlane axes invalid.\n"
            return

        # 1) OA，A/B/C/D/E
        A = O + xU * self.SuoZhuRadius
        B = A - xU * self.JuanShaLen_AB
        C = B - xU * self.JuanShaLen_BC

        D = A + (B - A) * (1.0 / 3.0)
        E = A + (B - A) * (2.0 / 3.0)

        # 2) AH，F/G/H （沿 -Z）
        H = A - zU * self.SuoZhuHeight_AH
        F = A + (H - A) * (1.0 / 3.0)
        G = A + (H - A) * (2.0 / 3.0)

        # 辅助线
        ln_OA = rg.Line(O, A)
        ln_AB = rg.Line(A, B)
        ln_BC = rg.Line(B, C)
        ln_AH = rg.Line(A, H)
        self.GuideCrvs += [ln_OA.ToNurbsCurve(), ln_AB.ToNurbsCurve(), ln_BC.ToNurbsCurve(), ln_AH.ToNurbsCurve()]

        # 3) 求 K/L：HD ∩ GE = L；GE ∩ FB = K
        ln_HD = rg.Line(H, D)
        ln_GE = rg.Line(G, E)
        ln_FB = rg.Line(F, B)  # NOTE: 这里就是“线段FB”；求交时允许延长线
        self.GuideCrvs += [ln_HD.ToNurbsCurve(), ln_GE.ToNurbsCurve(), ln_FB.ToNurbsCurve()]

        okL, L, _, _ = _line_line_intersection_3d(ln_HD, ln_GE, tol)
        if not okL:
            self.DebugLog += "ERROR: cannot intersect H-D and G-E => L.\n"
            return

        okK, K, _, _ = _line_line_intersection_3d(ln_GE, ln_FB, tol)
        if not okK:
            self.DebugLog += "ERROR: cannot intersect G-E and F-B => K.\n"
            return

        # 4) I / PlaneI / J
        I = C - zU * self.JuanShaDrop_CI
        ln_CI = rg.Line(C, I)
        self.GuideCrvs.append(ln_CI.ToNurbsCurve())

        PlaneI = rg.Plane(P)
        PlaneI.Origin = I

        okJ, J, tJ = _line_plane_intersection(ln_FB, PlaneI, tol)
        if not okJ:
            # 输出更多信息辅助你校核
            self.DebugLog += "ERROR: cannot intersect F-B with moved plane at I => J.\n"
            self.DebugLog += "INFO: PlaneI={}\n".format(str(PlaneI))
            self.DebugLog += "INFO: ln_FB From={}, To={}\n".format(str(ln_FB.From), str(ln_FB.To))
            return
        else:
            self.DebugLog += "INFO: J computed. (t={})\n".format(tJ)

        # P'：由 OA 与 -Z 构成的竖向平面（过 O）
        Pprime = rg.Plane(O, xU, -zU)

        # ---- 严格相切弧：C-J ----
        # 默认：C端=OA，J端=BF
        tanC = rg.Vector3d(A - O)   # OA
        tanJ = rg.Vector3d(F - B)   # BF
        arcCJ, arc_log = _strict_tangent_arc_CJ_in_plane(C, J, Pprime, tanC, tanJ, tol)
        self.DebugLog += arc_log
        if arcCJ is None:
            # 兜底：C端=OC，J端=JF
            self.DebugLog += "WARN: Fallback to equivalent tangents OC and JF.\n"
            tanC2 = rg.Vector3d(C - O)
            tanJ2 = rg.Vector3d(F - J)
            arcCJ, arc_log2 = _strict_tangent_arc_CJ_in_plane(C, J, Pprime, tanC2, tanJ2, tol)
            self.DebugLog += arc_log2
            if arcCJ is None:
                self.DebugLog += "ERROR: Strict tangent arc C-J construction failed (both tangent pairs).\n"
                return

        # 5) 外轮廓：弧 C-J + J-K + K-L + L-H
        seg_JK = rg.Line(J, K).ToNurbsCurve()
        seg_KL = rg.Line(K, L).ToNurbsCurve()
        seg_LH = rg.Line(L, H).ToNurbsCurve()

        outline = rg.PolyCurve()
        outline.Append(arcCJ)
        outline.Append(seg_JK)
        outline.Append(seg_KL)
        outline.Append(seg_LH)
        self.SectionOutlineCrv = outline

        # 闭合截面：A-C、(C->J->K->L->H)、H-A
        seg_AC = rg.Line(A, C).ToNurbsCurve()
        seg_HA = rg.Line(H, A).ToNurbsCurve()

        profile = rg.PolyCurve()
        profile.Append(seg_AC)
        profile.Append(outline)
        profile.Append(seg_HA)

        prof_crv = profile.ToNurbsCurve()
        if not prof_crv.IsClosed:
            if prof_crv.PointAtStart.DistanceTo(prof_crv.PointAtEnd) <= max(tol * 10.0, 1e-6):
                prof_crv.MakeClosed(max(tol * 10.0, 1e-6))
            else:
                self.DebugLog += "WARN: profile curve not closed; planar face may fail.\n"

        self.SectionProfileCrv = prof_crv

        # 成面（Planar Brep）
        breps = rg.Brep.CreatePlanarBreps(self.SectionProfileCrv, tol)
        if breps and len(breps) > 0 and breps[0] and breps[0].IsValid:
            self.SectionFace = breps[0]
        else:
            self.DebugLog += "WARN: CreatePlanarBreps failed.\n"
            self.SectionFace = None

        # 6) 旋转成体：绕 BasePlane 的 Z 轴（过 O）
        axis = rg.Line(O, O + zU * 1000.0)
        rev_srf = rg.RevSurface.Create(self.SectionProfileCrv, axis, 0.0, 2.0 * math.pi)
        if rev_srf is None or not rev_srf.IsValid:
            self.DebugLog += "ERROR: RevSurface.Create failed.\n"
            return

        tool_brep = rev_srf.ToBrep()
        if tool_brep is None or not tool_brep.IsValid:
            self.DebugLog += "ERROR: RevSurface.ToBrep failed.\n"
            return

        # 尝试封口
        if tool_brep.IsSolid:
            self.JuanShaToolBrep = tool_brep
        else:
            capped = tool_brep.CapPlanarHoles(tol)
            if capped and capped.IsValid and capped.IsSolid:
                self.JuanShaToolBrep = capped
                self.DebugLog += "INFO: Tool capped by CapPlanarHoles.\n"
            else:
                self.JuanShaToolBrep = tool_brep
                self.DebugLog += "WARN: Tool brep not solid (open edges remain).\n"

        self.KeyPts = [O, A, B, C, D, E, F, G, H, I, J, K, L]

        # 额外辅助线（便于 debug）
        self.GuideCrvs += [
            rg.Line(O, C).ToNurbsCurve(),
            rg.Line(J, F).ToNurbsCurve(),
            rg.Line(G, E).ToNurbsCurve(),
            rg.Line(H, D).ToNurbsCurve(),
        ]

        self._sync_legacy_outputs()

if __name__ == '__main__':
    # ----------------------------
    # GH Python 组件运行区（新旧名兼容）
    # ----------------------------
    def _gh_get(name, default=None, aliases=None):
        """
        在 GhPython 里安全读取输入变量：
        - 先读 name（新名）
        - 再按 aliases 顺序读别名（旧名）
        - 都没有则用 default
        """
        if aliases is None:
            aliases = []
        try:
            return eval(name)
        except Exception:
            pass
        for a in aliases:
            try:
                return eval(a)
            except Exception:
                continue
        return default


    # ---- 输入：推荐新名，同时兼容旧名 ----
    BasePlane       = _gh_get("BasePlane",       default=rg.Plane.WorldXY, aliases=["RefPlane"])
    SuoZhuRadius    = _gh_get("SuoZhuRadius",    default=10.0,             aliases=["Radius"])
    JuanShaLen_AB   = _gh_get("JuanShaLen_AB",   default=5.0,              aliases=["AB"])
    JuanShaLen_BC   = _gh_get("JuanShaLen_BC",   default=4.0,              aliases=["BC"])
    SuoZhuHeight_AH = _gh_get("SuoZhuHeight_AH", default=10.0,             aliases=["AH"])
    JuanShaDrop_CI  = _gh_get("JuanShaDrop_CI",  default=4.0,              aliases=["CI"])
    Tolerance       = _gh_get("Tolerance",       default=1e-7,             aliases=["Tol"])


    # ---- 构建 ----
    builder = SuoZhuJuanShaToolBuilder(
        base_plane=BasePlane,
        suo_zhu_radius=SuoZhuRadius,
        juansha_len_ab=JuanShaLen_AB,
        juansha_len_bc=JuanShaLen_BC,
        suo_zhu_height_ah=SuoZhuHeight_AH,
        juansha_drop_ci=JuanShaDrop_CI,
        tolerance=Tolerance
    )


    # ---- 输出：推荐新名，同时保留旧名便于校核 ----
    JuanShaToolBrep     = builder.JuanShaToolBrep
    SectionProfileCrv   = builder.SectionProfileCrv
    SectionOutlineCrv   = builder.SectionOutlineCrv
    SectionFace         = builder.SectionFace
    KeyPts              = builder.KeyPts
    GuideCrvs           = builder.GuideCrvs
    DebugLog            = builder.DebugLog

    # 旧名（保留）
    ToolBrep    = builder.ToolBrep
    ProfileCrv  = builder.ProfileCrv
    OutlineCrv  = builder.OutlineCrv
    ProfileFace = builder.ProfileFace
    Pts         = builder.Pts
    AuxCrvs     = builder.AuxCrvs
    Log         = builder.Log

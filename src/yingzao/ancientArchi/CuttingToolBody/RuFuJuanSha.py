"""
GhPython Component: RuFuJuanSha (Step-A + Step-B + Step-C)
--------------------------------------
用 GhPython 构建 乳栿卷殺（RuFuJuanSha）：
- Step-A：点位与线段骨架
- Step-B：三条曲线（I-J'-A、A-L'-H、H-?-E）
- Step-C：2个弧面 + 平面封板 + Join 输出 ClosedBrep

本版在你已有代码基础上的增量修改（除必要外不改动已完成部分）：
1) Step-C 增加平面 P0：弧线 I-J'-A + 线段 A-B + 线段 B-I
2) Step-C 确保平面 P4：O-E、E-C、C-A（为闭合补 A-O）
3) 新增输出端 ReferencePlanes_O：
   - 过 O 点的参考平面（RefPlaneUsed）
   - 垂直于该参考平面、同过 O 点、分别包含其 XAxis / YAxis 的两个平面（共3个平面）
4) 新增“可切换”替代 H-N'-E 逻辑（UsePolylineHE=True 时启用）：
   - 在 F->H 方向（FH线段或延长线）取点 X，使 |X-F| = FX_len
   - 将 E-F 与 F-X 各等分 DivN 段（默认 4）
   - 连接：E0-X1, E1-X2, ..., E{N-1}-X{N}
   - 取相邻直线交点：q_{N-1}=L0∩L1, q_{N-2}=L1∩L2, ..., q1=L{N-2}∩L{N-1}
   - 折线：
       * 若 FX_len <= |F-H|（X 在 FH 段内），折线为 H-X-q1-...-E
       * 否则（X 超过 H），折线为 H-q1-...-E（不包含 X）
   - Step-C 中：
       * S2：用折线替代原 H-N'-E
       * P3：原 H-E-F 平面改为：F-X、E-F、以及折线(X->...->E) 构成的平面
5) 新增输出端 ClosedBreps_Mirrored：
   - [0] ClosedBrep（当前）
   - [1] MirrorClosedBrep（以参考平面 RefPlaneUsed 镜像）

==============================================================
Inputs (GH 建议配置 / 名称大小写按你习惯可改，但要与代码一致)
--------------------------------------------------------------
BasePoint     : rg.Point3d   Access:item   TypeHint:Point3d
RefPlane      : object       Access:item   TypeHint:generic

OA_len        : float        Access:item   TypeHint:float
OB_len        : float        Access:item   TypeHint:float
AC_len        : float        Access:item   TypeHint:float
BI_len        : float        Access:item   TypeHint:float
LiftY_len     : float        Access:item   TypeHint:float

JJp_len       : float        Access:item   TypeHint:float
LLp_len       : float        Access:item   TypeHint:float
NNp_len       : float        Access:item   TypeHint:float   # 原弧线用（UsePolylineHE=False）

UsePolylineHE : bool         Access:item   TypeHint:bool
FX_len        : float        Access:item   TypeHint:float
DivN          : int          Access:item   TypeHint:int

==============================================================
Outputs (GH 建议配置)
--------------------------------------------------------------
Points              : list[rg.Point3d]    Access:list
Lines               : list[rg.LineCurve]  Access:list
ArcCurves           : list[rg.Curve]      Access:list
ArcCtrlPts          : list[rg.Point3d]    Access:list
ArcPlanes           : list[rg.Plane]      Access:list
ArcData             : list               Access:list   TypeHint:generic

StepCSurfaces        : list[rg.Brep]      Access:list
StepCPlanes          : list[rg.Brep]      Access:list
ClosedBrep           : rg.Brep            Access:item
ClosedBreps_Mirrored : list[rg.Brep]      Access:list

RefPlanes            : list[rg.Plane]     Access:list
ReferencePlanes_O    : list[rg.Plane]     Access:list   TypeHint:Plane
Debug                : str                Access:item
==============================================================
"""

import Rhino.Geometry as rg


# --------------------------------------------------------------
# Plane 工厂：严格按你给的 GH 轴系定义
# --------------------------------------------------------------
class GHPlaneFactory(object):
    @staticmethod
    def from_input(ref_plane, origin_pt):
        pl = None

        if isinstance(ref_plane, rg.Plane):
            pl = rg.Plane(ref_plane)

        elif isinstance(ref_plane, (str, bytes)):
            key = ref_plane.decode("utf-8") if isinstance(ref_plane, bytes) else ref_plane
            key = key.strip()

            # 你提供的轴系：
            # XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
            # XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
            # YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
            if key in ["WorldXY", "XY", "GhXY", "WorldXY_GH"]:
                pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 1, 0))
            elif key in ["WorldXZ", "XZ", "GhXZ", "WorldXZ_GH"]:
                pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))
            elif key in ["WorldYZ", "YZ", "GhYZ", "WorldYZ_GH"]:
                pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d(0, 1, 0), rg.Vector3d(0, 0, 1))
            else:
                pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))
        else:
            pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))

        pl.Origin = origin_pt
        return pl


# --------------------------------------------------------------
# 核心 RuFuJuanSha（Step-A + Step-B + Step-C）
# --------------------------------------------------------------
class RuFuJuanSha(object):
    def __init__(self,
                 base_point=None,
                 ref_plane=None,
                 OA_len=5.0,
                 OB_len=14.0,
                 AC_len=50.0,
                 BI_len=60.0,
                 LiftY_len=21.0,
                 JJp_len=1.0,
                 LLp_len=1.0,
                 NNp_len=1.0,
                 UsePolylineHE=False,
                 FX_len=40.0,
                 DivN=4):

        self.base_point = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d.Origin
        self.ref_plane_in = ref_plane if ref_plane is not None else "WorldXZ"

        self.OA_len = float(OA_len)
        self.OB_len = float(OB_len)
        self.AC_len = float(AC_len)
        self.BI_len = float(BI_len)
        self.LiftY_len = float(LiftY_len)

        self.JJp_len = float(JJp_len)
        self.LLp_len = float(LLp_len)
        self.NNp_len = float(NNp_len)

        self.use_polyline_he = bool(UsePolylineHE)
        self.fx_len = float(FX_len)
        self.div_n = int(DivN)

        self.debug_lines = []

        self.pl = None
        self.pts = {}
        self.lines = {}

        # Step-B containers
        self.arc_ctrl_pts = {}
        self.arc_planes = {}
        self.arc_curves = {}
        self.arc_data = []

        # Step-B polyline extra (only when use_polyline_he)
        self.he_poly_pts = None
        self.he_poly_pts_XE = None
        self.he_diag_lines = None

        # Step-C containers
        self.step_c_surfaces = {}
        self.step_c_planes = {}
        self.closed_brep = None

    def _log(self, s):
        self.debug_lines.append(str(s))

    @staticmethod
    def _unitize(v):
        vv = rg.Vector3d(v)
        if vv.IsZero:
            return vv
        vv.Unitize()
        return vv

    @staticmethod
    def _midpoint(p, q):
        return rg.Point3d((p.X + q.X) * 0.5, (p.Y + q.Y) * 0.5, (p.Z + q.Z) * 0.5)

    @staticmethod
    def _perp_in_plane(plane, chord_dir, flip=False):
        n = rg.Vector3d(plane.Normal)
        d = rg.Vector3d(chord_dir)
        perp = rg.Vector3d.CrossProduct(n, d)
        if perp.IsZero:
            return perp
        perp.Unitize()
        if flip:
            perp = -perp
        return perp

    @staticmethod
    def _line_line_intersection_3d(l1, l2):
        """
        计算两条直线（rg.Line）的交点。
        Python 中最稳定重载：
            rc, a, b = rg.Intersect.Intersection.LineLine(line1, line2)
        """
        try:
            rc, a, b = rg.Intersect.Intersection.LineLine(l1, l2)
        except:
            return None
        if not rc:
            return None
        p1 = l1.PointAt(a)
        p2 = l2.PointAt(b)
        return rg.Point3d((p1.X + p2.X) * 0.5, (p1.Y + p2.Y) * 0.5, (p1.Z + p2.Z) * 0.5)

    def build_step_a(self):
        self.pl = GHPlaneFactory.from_input(self.ref_plane_in, self.base_point)
        xaxis = rg.Vector3d(self.pl.XAxis)
        yaxis = rg.Vector3d(self.pl.YAxis)
        zaxis = rg.Vector3d(self.pl.ZAxis)

        self._log("RefPlaneUsed: Origin={}, XAxis={}, YAxis={}, ZAxis={}".format(
            self.pl.Origin, xaxis, yaxis, zaxis
        ))

        O = rg.Point3d(self.base_point)

        A = O + zaxis * self.OA_len
        B = O + zaxis * self.OB_len

        C = A - xaxis * self.AC_len
        D = B - xaxis * self.AC_len

        I = B + xaxis * self.BI_len

        G = A + yaxis * self.LiftY_len
        H = B + yaxis * self.LiftY_len
        E = C + yaxis * self.LiftY_len
        F = D + yaxis * self.LiftY_len

        self.pts = {
            "O": O, "A": A, "B": B, "C": C, "D": D,
            "E": E, "F": F, "G": G, "H": H, "I": I
        }

        def lc(p, q):
            return rg.LineCurve(p, q)

        self.lines = {
            "OA": lc(O, A),
            "OB": lc(O, B),
            "AC": lc(A, C),
            "BD": lc(B, D),
            "BI": lc(B, I),
            "AG": lc(A, G),
            "BH": lc(B, H),
            "CE": lc(C, E),
            "DF": lc(D, F),

            "AH": lc(A, H),
            "HE": lc(H, E),
            "AE": lc(A, E),
            "AI": lc(A, I),
            "HI": lc(H, I)
        }

        self._log("Points built: " + ", ".join(["{}{}".format(k, self.pts[k]) for k in ["O","A","B","C","D","E","F","G","H","I"]]))
        self._log("Lines built: " + ", ".join(list(self.lines.keys())))
        return self

    def _build_polyline_H_to_E_in_HEF_plane(self, H, E, F):
        N = max(2, int(self.div_n))

        dir_FH = self._unitize(H - F)
        FH_len = F.DistanceTo(H)
        X = F + dir_FH * self.fx_len

        EF_vec = (F - E)
        FX_vec = (X - F)

        E_pts = [E + EF_vec * (float(i) / float(N)) for i in range(N + 1)]
        X_pts = [F + FX_vec * (float(i) / float(N)) for i in range(N + 1)]

        diag_lines = []
        for i in range(N):
            diag_lines.append(rg.Line(E_pts[i], X_pts[i + 1]))

        q_pts = []
        for i in range(N - 1):
            q = self._line_line_intersection_3d(diag_lines[i], diag_lines[i + 1])
            if q is None:
                p1 = diag_lines[i].PointAt(0.5)
                p2 = diag_lines[i + 1].PointAt(0.5)
                q = rg.Point3d((p1.X + p2.X) * 0.5, (p1.Y + p2.Y) * 0.5, (p1.Z + p2.Z) * 0.5)
                self._log("[Step-B][WARN] LineLine intersection failed at i={}, fallback midpoint.".format(i))
            q_pts.append(q)

        q_pts_reversed = list(reversed(q_pts))  # [q1..q_{N-1}]
        include_X = (self.fx_len <= FH_len + 1e-6)

        poly_pts_full = [H]
        if include_X:
            poly_pts_full.append(X)
        poly_pts_full.extend(q_pts_reversed)
        poly_pts_full.append(E)

        poly_pts_XE = [X] + q_pts_reversed + [E]
        return poly_pts_full, poly_pts_XE, diag_lines

    def build_step_b(self):
        if not self.pts:
            self.build_step_a()

        A = self.pts["A"]; B = self.pts["B"]; I = self.pts["I"]
        H = self.pts["H"]; E = self.pts["E"]; F = self.pts["F"]

        # Arc 1: I-J'-A
        pl_ABI = rg.Plane(A, B, I)
        J = self._midpoint(A, I)
        dir_AI = self._unitize(I - A)
        perp1 = self._perp_in_plane(pl_ABI, dir_AI, flip=True)
        Jp = J + perp1 * self.JJp_len
        crv1 = rg.Arc(I, Jp, A).ToNurbsCurve()

        # Arc 2: A-L'-H
        pl_ABH = rg.Plane(A, B, H)
        L = self._midpoint(A, H)
        dir_AH = self._unitize(H - A)
        perp2 = self._perp_in_plane(pl_ABH, dir_AH, flip=True)
        Lp = L + perp2 * self.LLp_len
        crv2 = rg.Arc(A, Lp, H).ToNurbsCurve()

        # Curve 3: H-?-E
        pl_HEF = rg.Plane(H, E, F)
        N_mid = self._midpoint(H, E)
        dir_HE = self._unitize(E - H)
        perp3 = self._perp_in_plane(pl_HEF, dir_HE, flip=False)
        Np = N_mid + perp3 * self.NNp_len

        if not self.use_polyline_he:
            crv3 = rg.Arc(H, Np, E).ToNurbsCurve()
            self.he_poly_pts = None
            self.he_poly_pts_XE = None
            self.he_diag_lines = None
            self._log("Step-B: UsePolylineHE=False -> Arc(H-N'-E)")
        else:
            poly_pts_full, poly_pts_XE, diag_lines = self._build_polyline_H_to_E_in_HEF_plane(H, E, F)
            crv3 = rg.Polyline(poly_pts_full).ToNurbsCurve()
            self.he_poly_pts = poly_pts_full
            self.he_poly_pts_XE = poly_pts_XE
            self.he_diag_lines = diag_lines
            self._log("Step-B: UsePolylineHE=True -> Polyline(H-(X?)-q..-E), FX_len={}, DivN={}".format(self.fx_len, self.div_n))

        self.arc_planes = {"Plane_ABI": pl_ABI, "Plane_ABH": pl_ABH, "Plane_HEF": pl_HEF}
        self.arc_ctrl_pts = {"J": J, "Jp": Jp, "L": L, "Lp": Lp, "N": N_mid, "Np": Np}
        self.arc_curves = {"Arc_IJpA": crv1, "Arc_ALpH": crv2, "Arc_HNpE": crv3}

        third_item = {"name": "H-Np-E" if (not self.use_polyline_he) else "H-Polyline-E",
                      "curve": crv3,
                      "ctrl_pts": (H, N_mid, Np, E),
                      "plane": pl_HEF}
        if self.use_polyline_he and self.he_poly_pts:
            third_item["poly_pts"] = list(self.he_poly_pts)

        self.arc_data = [
            {"name": "I-Jp-A", "curve": crv1, "ctrl_pts": (I, J, Jp, A), "plane": pl_ABI},
            {"name": "A-Lp-H", "curve": crv2, "ctrl_pts": (A, L, Lp, H), "plane": pl_ABH},
            third_item,
        ]

        self._log("Step-B: Curve1=Arc_IJpA, Curve2=Arc_ALpH, Curve3={}".format("Polyline" if self.use_polyline_he else "Arc_HNpE"))
        return self

    def build_step_c(self, tol=None):
        if not self.arc_curves:
            self.build_step_a().build_step_b()

        if tol is None:
            tol = 1e-3

        P = self.pts
        O,A,B,C,D,E,F,H,I = P["O"],P["A"],P["B"],P["C"],P["D"],P["E"],P["F"],P["H"],P["I"]
        crv_IJpA = self.arc_curves["Arc_IJpA"]
        crv_ALpH = self.arc_curves["Arc_ALpH"]
        crv_HE = self.arc_curves["Arc_HNpE"]

        def _line(p, q):
            return rg.LineCurve(p, q)

        def _edge_surface(curves, name):
            brep = rg.Brep.CreateEdgeSurface(curves)
            if isinstance(brep, rg.Brep) and brep is not None:
                self._log("[Step-C] EdgeSurface OK: {}".format(name))
                return brep
            self._log("[Step-C][WARN] EdgeSurface FAIL: {}".format(name))
            return None

        def _planar_from_curves(curves, name):
            joined = rg.Curve.JoinCurves(curves, tol)
            loops = joined if joined and len(joined) > 0 else curves
            breps = rg.Brep.CreatePlanarBreps(loops, tol)
            if breps and len(breps) > 0 and breps[0] is not None:
                self._log("[Step-C] PlanarBrep OK: {}".format(name))
                return breps[0]
            self._log("[Step-C][WARN] PlanarBrep FAIL: {}".format(name))
            return None

        c_HI = _line(H, I)
        S1 = _edge_surface([crv_IJpA, crv_ALpH, c_HI], "S1(I-H + arcs)")

        c_EA = _line(E, A)
        S2 = _edge_surface([c_EA, crv_ALpH, crv_HE], "S2(E-A + (A-L'-H) + (H-?-E))")

        P0 = _planar_from_curves([crv_IJpA, _line(A, B), _line(B, I)], "P0(ArcIJA-AB-BI)")
        P1 = _planar_from_curves([_line(I,B), _line(B,H), _line(H,I)], "P1(IB-IH-BH)")
        P2 = _planar_from_curves([_line(B,H), _line(H,F), _line(F,D), _line(D,B)], "P2(BH-HF-FD-DB)")

        if not self.use_polyline_he:
            crv_EH = rg.Curve.DuplicateCurve(crv_HE)
            if crv_EH:
                crv_EH.Reverse()
            P3 = _planar_from_curves([_line(H,F), _line(F,E), crv_EH], "P3(HF-FE-Arc(EH))")
        else:
            if not self.he_poly_pts_XE:
                crv_EH = rg.Curve.DuplicateCurve(crv_HE)
                if crv_EH:
                    crv_EH.Reverse()
                P3 = _planar_from_curves([_line(H,F), _line(F,E), crv_EH], "P3_Fallback(HF-FE-Curve(EH))")
                self._log("[Step-C][WARN] he_poly_pts_XE missing, fallback to original P3.")
            else:
                poly_XE = rg.Polyline(self.he_poly_pts_XE).ToNurbsCurve()
                X_pt = self.he_poly_pts_XE[0]
                P3 = _planar_from_curves([_line(F, X_pt), poly_XE, _line(E, F)], "P3(FX + Poly(X..E) + EF)")

        P4 = _planar_from_curves([_line(O,E), _line(E,C), _line(C,A), _line(A,O)], "P4(OE-EC-CA-AO)")
        P5 = _planar_from_curves([_line(A,B), _line(B,D), _line(D,C), _line(C,A)], "P5(AB-BD-DC-CA)")
        P6 = _planar_from_curves([_line(E,F), _line(F,D), _line(D,C), _line(C,E)], "P6(EF-FD-DC-CE)")

        pieces = [x for x in [S1, S2, P0, P1, P2, P3, P4, P5, P6] if x is not None]

        self.step_c_surfaces = {"S1": S1, "S2": S2}
        self.step_c_planes = {"P0": P0, "P1": P1, "P2": P2, "P3": P3, "P4": P4, "P5": P5, "P6": P6}

        if not pieces:
            self.closed_brep = None
            self._log("[Step-C][ERROR] No Brep pieces generated.")
            return self

        joined = rg.Brep.JoinBreps(pieces, tol)
        if joined and len(joined) > 0:
            brep = joined[0]
            if not brep.IsSolid:
                capped = brep.CapPlanarHoles(tol)
                if capped and capped.IsSolid:
                    brep = capped
                    self._log("[Step-C] CapPlanarHoles OK -> Solid")
                else:
                    self._log("[Step-C][WARN] Result not solid (Join/Cap incomplete).")
            else:
                self._log("[Step-C] JoinBreps OK -> Solid")
            self.closed_brep = brep
        else:
            self.closed_brep = None
            self._log("[Step-C][ERROR] JoinBreps failed.")

        return self

    def build_reference_planes_at_O(self):
        if not isinstance(self.pl, rg.Plane):
            return []
        O = self.pl.Origin
        X = rg.Vector3d(self.pl.XAxis)
        Y = rg.Vector3d(self.pl.YAxis)
        Z = rg.Vector3d(self.pl.ZAxis)
        P0 = rg.Plane(O, X, Y)
        PX = rg.Plane(O, X, Z)
        PY = rg.Plane(O, Y, Z)
        return [P0, PX, PY]

    def get_closed_breps_mirrored(self):
        orig = self.closed_brep
        if orig is None or (not isinstance(orig, rg.Brep)) or (not isinstance(self.pl, rg.Plane)):
            return [orig, None]

        mirrored = orig.DuplicateBrep()
        try:
            xform = rg.Transform.Mirror(self.pl)
            mirrored.Transform(xform)
        except Exception as ex:
            self._log("[Mirror][ERROR] {}".format(ex))
            return [orig, None]

        return [orig, mirrored]

    # outputs
    def get_output_points_ordered(self):
        order = ["O", "A", "B", "C", "D", "E", "F", "G", "H", "I"]
        return [self.pts[k] for k in order]

    def get_output_lines_ordered(self):
        order = ["OA","OB","AC","BD","BI","AG","BH","CE","DF","AH","HE","AE","AI","HI"]
        return [self.lines[k] for k in order if k in self.lines]

    def get_output_arcs_ordered(self):
        order = ["Arc_IJpA", "Arc_ALpH", "Arc_HNpE"]
        return [self.arc_curves[k] for k in order if k in self.arc_curves]

    def get_output_arc_ctrlpts_ordered(self):
        order = ["J", "Jp", "L", "Lp", "N", "Np"]
        return [self.arc_ctrl_pts[k] for k in order if k in self.arc_ctrl_pts]

    def get_output_arc_planes_ordered(self):
        order = ["Plane_ABI", "Plane_ABH", "Plane_HEF"]
        return [self.arc_planes[k] for k in order if k in self.arc_planes]

    def get_arc_data(self):
        return list(self.arc_data) if self.arc_data else []

    def get_step_c_surfaces_ordered(self):
        order = ["S1", "S2"]
        out = []
        for k in order:
            v = self.step_c_surfaces.get(k) if isinstance(self.step_c_surfaces, dict) else None
            if v is not None:
                out.append(v)
        return out

    # ✅ FIXED: 不再用 list comprehension，避免把 Brep 当 iterable
    def get_step_c_planes_ordered(self):
        order = ["P0","P1","P2","P3","P4","P5","P6"]
        out = []
        if not isinstance(self.step_c_planes, dict):
            return out
        for k in order:
            v = self.step_c_planes.get(k, None)
            if v is not None:
                out.append(v)
        return out

    def get_closed_brep(self):
        return self.closed_brep

    def get_refplanes(self):
        return [self.pl] if isinstance(self.pl, rg.Plane) else []

    def get_debug(self):
        return "\n".join(self.debug_lines)

if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    # ==============================================================

    if 'BasePoint' not in globals() or BasePoint is None:
        BasePoint = rg.Point3d.Origin
    if 'RefPlane' not in globals() or RefPlane is None:
        RefPlane = "WorldXZ"

    if 'OA_len' not in globals() or OA_len is None:
        OA_len = 5.0
    if 'OB_len' not in globals() or OB_len is None:
        OB_len = 14.0
    if 'AC_len' not in globals() or AC_len is None:
        AC_len = 50.0
    if 'BI_len' not in globals() or BI_len is None:
        BI_len = 60.0
    if 'LiftY_len' not in globals() or LiftY_len is None:
        LiftY_len = 21.0

    if 'JJp_len' not in globals() or JJp_len is None:
        JJp_len = 1.0
    if 'LLp_len' not in globals() or LLp_len is None:
        LLp_len = 1.0
    if 'NNp_len' not in globals() or NNp_len is None:
        NNp_len = 1.0

    if 'UsePolylineHE' not in globals() or UsePolylineHE is None:
        UsePolylineHE = False
    if 'FX_len' not in globals() or FX_len is None:
        FX_len = 40.0
    if 'DivN' not in globals() or DivN is None:
        DivN = 4

    solver = RuFuJuanSha(
        base_point=BasePoint,
        ref_plane=RefPlane,
        OA_len=OA_len,
        OB_len=OB_len,
        AC_len=AC_len,
        BI_len=BI_len,
        LiftY_len=LiftY_len,
        JJp_len=JJp_len,
        LLp_len=LLp_len,
        NNp_len=NNp_len,
        UsePolylineHE=UsePolylineHE,
        FX_len=FX_len,
        DivN=DivN
    ).build_step_a().build_step_b().build_step_c()

    Points              = solver.get_output_points_ordered()
    Lines               = solver.get_output_lines_ordered()
    ArcCurves           = solver.get_output_arcs_ordered()
    ArcCtrlPts          = solver.get_output_arc_ctrlpts_ordered()
    ArcPlanes           = solver.get_output_arc_planes_ordered()
    ArcData             = solver.get_arc_data()
    StepCSurfaces       = solver.get_step_c_surfaces_ordered()
    StepCPlanes         = solver.get_step_c_planes_ordered()
    ClosedBrep          = solver.get_closed_brep()
    RefPlanes           = solver.get_refplanes()
    ReferencePlanes_O   = solver.build_reference_planes_at_O()

    ClosedBreps_Mirrored = solver.get_closed_breps_mirrored()

    Debug               = solver.get_debug()

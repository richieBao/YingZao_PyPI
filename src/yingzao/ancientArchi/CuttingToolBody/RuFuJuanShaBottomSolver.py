"""
GhPython Component: RuFuJuanSha_Bottom (class-based, Step-A + Step-B + Step-C + Step-D + Step-E) - FIXED
--------------------------------------------------------------------------------------------------------
在 Step-A~D 基础上追加 Step-E：

Step-E:
1) 以点 A 与点 P 连成直线 A-P；将该直线沿 RefPlane.YAxis 平移 IJ_len 得到 A1-P1；
   将 A1-P1 沿“垂直参考平面方向”（RefPlane.ZAxis）分别 +BI_len 与 -BI_len 偏移复制两条线；
   以两条偏移线 Loft 成面 Top_S（顶部面）。
2) 将 Top_S 沿 RefPlane.YAxis 反方向拉伸成封闭体 Cube，拉伸距离 = OA_len + IJ_len。
3) 用 Step-D 的 Surface_Final 分割 Cube 得两部分（或多部分），计算每部分体积，输出最大体积者。

说明：
- Step-D 输出的 Surface_Final 需为有效 Brep（通常为开口曲面/面组）。
- 使用 Brep.Split(closed_brep, cutter_brep, tol) 生成的分块通常已包含切割面形成的封闭体；
  若出现非封闭，则会尝试 CapPlanarHoles（仅对平面孔有效）。

Inputs (GH 建议配置):
    BasePoint : rg.Point3d
    RefPlane  : object
    OA_len    : float
    AB_len    : float
    DivCount  : int
    BI_len    : float
    IJ_len    : float
    KL_len    : float
    BP_len    : float

Outputs（新增 Step-E）:
    Top_S            : rg.Brep
    Cube_Brep        : rg.Brep
    Cube_Parts       : list[rg.Brep]
"""

import Rhino.Geometry as rg
from Rhino.Geometry.Intersect import Intersection
import scriptcontext as sc

import ghpythonlib.components as ghc
__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.11"


class GHPlaneFactory(object):
    @staticmethod
    def from_name(name, origin):
        if not isinstance(name, str):
            return None

        key = name.strip().lower()
        if key in ["worldxy", "xy", "worldxy_gh"]:
            return rg.Plane(origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 1, 0))
        if key in ["worldxz", "xz", "worldxz_gh"]:
            return rg.Plane(origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))
        if key in ["worldyz", "yz", "worldyz_gh"]:
            return rg.Plane(origin, rg.Vector3d(0, 1, 0), rg.Vector3d(0, 0, 1))
        return None

    @staticmethod
    def coerce(ref_plane, base_point):
        if isinstance(ref_plane, rg.Plane):
            pl = rg.Plane(ref_plane)
            pl.Origin = base_point
            return pl
        if isinstance(ref_plane, str):
            pl = GHPlaneFactory.from_name(ref_plane, origin=base_point)
            if pl is not None:
                return pl
        return GHPlaneFactory.from_name("WorldXZ_GH", origin=base_point)


class RuFuJuanShaBottomSolver(object):
    def __init__(self,
                 base_point=None,
                 ref_plane=None,
                 oa_len=10.0,
                 ab_len=20.0,
                 div_count=4,
                 bi_len=5.0,
                 ij_len=2.0,
                 kl_len=0.5,
                 bp_len=10.0):
        self.base_point = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d.Origin
        self.ref_plane_in = ref_plane

        # Step-A params
        self.oa_len = 10.0 if oa_len is None else float(oa_len)
        self.ab_len = 20.0 if ab_len is None else float(ab_len)
        try:
            self.div_count = int(div_count)
        except:
            self.div_count = 4
        if self.div_count < 2:
            self.div_count = 2

        # Step-B/Step-C/Step-E shared
        self.bi_len = 5.0 if bi_len is None else float(bi_len)

        # Step-B / Step-E
        self.ij_len = 2.0 if ij_len is None else float(ij_len)
        self.kl_len = 0.5 if kl_len is None else float(kl_len)

        # Step-D
        self.bp_len = 10.0 if bp_len is None else float(bp_len)

        # tolerance
        try:
            self.tol = sc.doc.ModelAbsoluteTolerance
        except:
            self.tol = 0.01

        self._log = []

        # ---- Step-A results ----
        self.plane = None
        # Reference planes through O (computed in Step-A)
        self.ref_plane_O = None
        self.ref_plane_O_XZ = None
        self.ref_plane_O_YZ = None
        self.O = None
        self.A = None
        self.B = None
        self.line_OA = None
        self.line_AB = None
        self.points_OA = []
        self.points_AB = []
        self.connector_lines = []
        self.intersections = []      # [F,G,H] when div_count=4
        self.polyline_curve = None

        # ---- Step-B results ----
        self.I = None
        self.J = None
        self.K = None
        self.L = None
        self.plane_bji = None
        self.curve_blj = None

        # ---- Step-C results ----
        self.O_p = None              # O'
        self.FGH_p = []              # [F',G',H']
        self.I_from_move = None      # I (=B moved)
        self.FGH_pp = []             # [F'',G'',H'']
        self.polyline_op_to_j = None # O'-F''-G''-H''-J

        # ---- Step-D results ----
        self.P = None
        self.rail_bp = None
        self.surface_red = None
        self.surface_purple = None
        self.surface_s = None
        self.surface_s_mirror = None
        self.surface_final = None

        # ---- Step-E results ----
        self.top_s = None
        self.cube_brep = None
        self.cube_parts_raw = []  # raw split fragments (no join/cap)
        self.cube_parts = []
        self.cube_parts_joined_all = []

        # ---- Step-F results ----
        self.cube_parts_vol = []
        self.solid_max_volume = None

    # ----------------------------
    # logging
    # ----------------------------
    def log(self, msg):
        self._log.append(str(msg))

    def debug_text(self):
        return "\n".join(self._log)

    # ----------------------------
    # geometry helpers
    # ----------------------------
    @staticmethod
    def divide_segment(p0, p1, n):
        if n <= 0:
            return [p0, p1]
        v = p1 - p0
        pts = []
        for i in range(n + 1):
            t = float(i) / float(n)
            pts.append(p0 + v * t)
        return pts

    @staticmethod
    def line_line_intersection_pt(line_a, line_b):
        ok, ta, tb = Intersection.LineLine(line_a, line_b)
        if not ok:
            return None
        return line_a.PointAt(ta)

    @staticmethod
    def midpoint(p0, p1):
        return rg.Point3d((p0.X + p1.X) * 0.5, (p0.Y + p1.Y) * 0.5, (p0.Z + p1.Z) * 0.5)

    @staticmethod
    def unitize(v):
        vv = rg.Vector3d(v)
        if vv.IsTiny():
            return vv
        vv.Unitize()
        return vv

    @staticmethod
    def _try_cap_planar(brep, tol):
        if brep is None:
            return None
        try:
            if brep.IsSolid:
                return brep
            capped = brep.CapPlanarHoles(tol)
            if capped is not None and capped.IsValid:
                return capped
        except:
            pass
        return brep

    @staticmethod
    def _volume_of_brep(brep, tol):
        if brep is None:
            return 0.0
        try:
            if not brep.IsSolid:
                # 尝试先封闭
                b2 = RuFuJuanShaBottomSolver._try_cap_planar(brep, tol)
            else:
                b2 = brep
            mp = rg.MassProperties.Compute(b2)
            if mp:
                return abs(mp.Volume)
        except:
            pass
        return 0.0

    # ----------------------------
    # Step-A
    # ----------------------------
    def step_a_build_base_lines(self):
        self.plane = GHPlaneFactory.coerce(self.ref_plane_in, self.base_point)

        self.O = rg.Point3d(self.base_point)
        # Build reference planes through O
        try:
            self.ref_plane_O = rg.Plane(self.plane)
            self.ref_plane_O.Origin = self.O
            # Planes perpendicular to RefPlane, passing through O, containing X and Y axes respectively
            self.ref_plane_O_XZ = rg.Plane(self.O, self.plane.XAxis, self.plane.ZAxis)
            self.ref_plane_O_YZ = rg.Plane(self.O, self.plane.YAxis, self.plane.ZAxis)
        except:
            self.ref_plane_O = self.plane
            self.ref_plane_O_XZ = None
            self.ref_plane_O_YZ = None
        self.A = self.O + self.plane.YAxis * self.oa_len
        self.B = self.A + self.plane.XAxis * self.ab_len

        self.line_OA = rg.Line(self.O, self.A)
        self.line_AB = rg.Line(self.A, self.B)

        self.log("[A2] Build lines OK: OA_len={}, AB_len={}, DivCount={}".format(
            self.oa_len, self.ab_len, self.div_count
        ))

    def step_a_divide(self):
        n = self.div_count
        self.points_OA = self.divide_segment(self.O, self.A, n)
        self.points_AB = self.divide_segment(self.A, self.B, n)
        self.log("[A3] Divide OK: OA_pts={}, AB_pts={}".format(len(self.points_OA), len(self.points_AB)))

    def step_a_connectors(self):
        n = self.div_count
        self.connector_lines = []
        for k in range(n):
            p = self.points_OA[k]
            q = self.points_AB[k + 1]
            self.connector_lines.append(rg.LineCurve(rg.Line(p, q)))
        self.log("[A3] Connectors OK: {}".format(len(self.connector_lines)))

    def step_a_intersections(self):
        n = self.div_count
        self.intersections = []
        for k in range(n - 1):
            la = self.connector_lines[k].Line
            lb = self.connector_lines[k + 1].Line
            ipt = self.line_line_intersection_pt(la, lb)
            if ipt is None:
                self.log("[WARN] Intersection failed between L{} and L{}".format(k, k + 1))
            else:
                self.intersections.append(ipt)
        self.log("[A3] Intersections OK: {}".format(len(self.intersections)))

    def step_a_polyline(self):
        pts = [self.O] + list(self.intersections) + [self.B]
        self.polyline_curve = rg.PolylineCurve(pts)
        self.log("[A3] Polyline OK: {} pts".format(len(pts)))

    def solve_step_a(self):
        self.step_a_build_base_lines()
        self.step_a_divide()
        self.step_a_connectors()
        self.step_a_intersections()
        self.step_a_polyline()

    # ----------------------------
    # Step-B
    # ----------------------------
    def step_b_build_IJ(self):
        if self.B is None or self.plane is None:
            raise Exception("Step-B requires Step-A result (B/plane).")

        self.I = self.B + self.plane.ZAxis * self.bi_len
        self.J = self.I + self.plane.YAxis * self.ij_len
        self.log("[B1] Build I,J OK: BI_len={}, IJ_len={}".format(self.bi_len, self.ij_len))

    def step_b_build_KL(self):
        if self.B is None or self.I is None or self.J is None:
            raise Exception("Step-B requires B, I, J.")

        self.K = self.midpoint(self.B, self.J)
        self.plane_bji = rg.Plane(self.B, self.J, self.I)
        if not self.plane_bji.IsValid:
            raise Exception("Plane_BJI is invalid (points may be collinear).")

        v_bj = self.J - self.B
        if v_bj.IsTiny():
            raise Exception("B and J are too close; cannot define BJ direction.")
        v_bj = self.unitize(v_bj)

        v_perp = rg.Vector3d.CrossProduct(self.plane_bji.Normal, v_bj)
        if v_perp.IsTiny():
            v_perp = rg.Vector3d.CrossProduct(v_bj, self.plane_bji.Normal)
        v_perp = self.unitize(v_perp)
        if v_perp.IsTiny():
            raise Exception("Cannot compute perpendicular direction in Plane_BJI.")

        self.L = self.K + v_perp * self.kl_len
        self.log("[B2] Build K,L,Plane_BJI OK: KL_len={}".format(self.kl_len))

    def step_b_curve_BLJ(self):
        if self.B is None or self.L is None or self.J is None:
            raise Exception("Step-B requires B, L, J.")

        try:
            arc = rg.Arc(self.B, self.L, self.J)
            if not arc.IsValid:
                raise Exception("Arc(B,L,J) invalid (points may be collinear).")
            self.curve_blj = arc.ToNurbsCurve()
            self.log("[B2] Curve B-L-J OK (Arc).")
        except Exception as e:
            pts = [self.B, self.L, self.J]
            self.curve_blj = rg.Curve.CreateInterpolatedCurve(pts, 3)
            self.log("[WARN] Arc failed, fallback to interpolated curve: {}".format(e))

    def solve_step_b(self):
        self.step_b_build_IJ()
        self.step_b_build_KL()
        self.step_b_curve_BLJ()

    # ----------------------------
    # Step-C
    # ----------------------------
    def step_c_move_points(self):
        if self.plane is None or self.O is None or self.B is None:
            raise Exception("Step-C requires Step-A result (O/B/plane).")
        if not self.intersections or len(self.intersections) < 1:
            raise Exception("Step-C requires Step-A intersections (F,G,H...).")

        move_vec = self.plane.ZAxis * self.bi_len
        self.O_p = self.O + move_vec
        self.FGH_p = [pt + move_vec for pt in list(self.intersections)]
        self.I_from_move = self.B + move_vec

        if self.I is not None:
            d = self.I.DistanceTo(self.I_from_move)
            if d > 1e-6:
                self.log("[WARN][C1] I mismatch: Step-B I vs moved-B I_from_move, dist={}".format(d))

        self.log("[C1] Move points OK.")

    def step_c_map_points(self):
        if self.O_p is None or self.I_from_move is None:
            raise Exception("Step-C mapping requires O' and I_from_move.")
        if self.J is None:
            raise Exception("Step-C mapping requires Step-B J.")
        if not self.FGH_p:
            raise Exception("Step-C mapping requires F',G',H'.")

        y_axis = self.unitize(self.plane.YAxis)

        def s_of(P):
            v = P - self.O_p
            return v.X * y_axis.X + v.Y * y_axis.Y + v.Z * y_axis.Z

        s_I = s_of(self.I_from_move)
        s_J = s_of(self.J)
        if abs(s_I) < 1e-9:
            raise Exception("Step-C mapping failed: s(I) equals s(O') (degenerate).")

        self.FGH_pp = []
        for Pp in self.FGH_p:
            s_P = s_of(Pp)
            t = (s_P) / (s_I)
            s_target = t * (s_J)
            delta = s_target - s_P
            self.FGH_pp.append(Pp + y_axis * delta)

        self.log("[C2] Map points OK.")

    def step_c_polyline(self):
        if self.O_p is None or self.J is None or not self.FGH_pp:
            raise Exception("Step-C polyline requires O', mapped points, J.")
        pts = [self.O_p] + list(self.FGH_pp) + [self.J]
        self.polyline_op_to_j = rg.PolylineCurve(pts)
        self.log("[C2] Polyline O'-...-J OK.")

    def solve_step_c(self):
        self.step_c_move_points()
        self.step_c_map_points()
        self.step_c_polyline()

    # ----------------------------
    # Step-D
    # ----------------------------
    def step_d_build_red_surface(self):
        if self.polyline_curve is None or self.polyline_op_to_j is None:
            raise Exception("Step-D requires rails from Step-A and Step-C.")
        if self.curve_blj is None or self.O is None or self.O_p is None:
            raise Exception("Step-D requires section Curve_BLJ and O/O'.")

        rail1 = self.polyline_curve
        rail2 = self.polyline_op_to_j
        sec1 = rg.LineCurve(rg.Line(self.O, self.O_p))
        sec2 = self.curve_blj

        breps = rg.Brep.CreateFromSweep(rail1, rail2, [sec1, sec2], False, self.tol)
        if not breps or len(breps) == 0:
            raise Exception("Red surface sweep failed.")
        self.surface_red = breps[0]
        self.log("[D1] Red surface OK.")

    def step_d_build_purple_surface(self):
        if self.B is None or self.plane is None or self.curve_blj is None:
            raise Exception("Step-D purple requires B/plane/Curve_BLJ.")

        self.P = self.B + self.plane.XAxis * self.bp_len
        self.rail_bp = rg.LineCurve(rg.Line(self.B, self.P))

        breps = rg.Brep.CreateFromSweep(self.rail_bp, self.curve_blj, False, self.tol)
        if not breps or len(breps) == 0:
            raise Exception("Purple surface sweep failed.")
        self.surface_purple = breps[0]
        self.log("[D2] Purple surface OK.")

    def step_d_join_and_mirror(self):
        if self.surface_red is None or self.surface_purple is None:
            raise Exception("Step-D join requires red and purple surfaces.")

        joined = rg.Brep.JoinBreps([self.surface_red, self.surface_purple], self.tol)
        if joined and len(joined) > 0:
            self.surface_s = joined[0]
        else:
            self.surface_s = self.surface_red
            self.log("[WARN][D3] Join red+purple failed; Surface_S uses red only.")

        xform = rg.Transform.Mirror(self.plane)
        self.surface_s_mirror = self.surface_s.DuplicateBrep()
        self.surface_s_mirror.Transform(xform)

        joined2 = rg.Brep.JoinBreps([self.surface_s, self.surface_s_mirror], self.tol)
        if joined2 and len(joined2) > 0:
            self.surface_final = joined2[0]
        else:
            self.surface_final = self.surface_s
            self.log("[WARN][D4] Join S+S' failed; Surface_Final uses S only.")

        self.log("[D4] Surface_Final OK.")

    def solve_step_d(self):
        self.step_d_build_red_surface()
        self.step_d_build_purple_surface()
        self.step_d_join_and_mirror()

    # ----------------------------
    # Step-E (NEW)
    # ----------------------------
    def step_e_build_top_surface(self):
        """
        Top_S:
          base line: A-P
          move along +Y by IJ_len => A1-P1
          offset along +/-Z by BI_len => two lines
          loft => Top_S
        """
        if self.A is None:
            raise Exception("Step-E requires point A (Step-A).")
        if self.P is None:
            raise Exception("Step-E requires point P (Step-D).")
        if self.plane is None:
            raise Exception("Step-E requires RefPlane.")

        y = self.plane.YAxis
        z = self.plane.ZAxis

        A1 = self.A + y * self.ij_len
        P1 = self.P + y * self.ij_len

        l0 = rg.LineCurve(rg.Line(A1, P1))
        l_plus = l0.DuplicateCurve()
        l_minus = l0.DuplicateCurve()
        l_plus.Translate(z * self.bi_len)
        l_minus.Translate(z * (-self.bi_len))

        breps = rg.Brep.CreateFromLoft([l_plus, l_minus], rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)
        if not breps or len(breps) == 0:
            raise Exception("Top_S loft failed.")
        self.top_s = breps[0]
        self.log("[E1] Top_S OK.")

    def step_e_extrude_cube(self):
        """
        Cube:
          使用 GH API 的 ghc.Extrude(base, direction) 将 Top_S 沿参考平面 Y 轴反方向拉伸成体。

          - base: Top_S (rg.Brep)
          - direction: -RefPlane.YAxis * (OA_len + IJ_len)

        说明：
          ghc.Extrude 返回 [Geometry]（通常是 Brep）。这里做统一归一化与有效性检查，
          并在必要时仅对“未封闭”的结果做一次 CapPlanarHoles 兜底，以保证输出为有效体。
        """
        if self.top_s is None or (hasattr(self.top_s, "IsValid") and not self.top_s.IsValid):
            raise Exception("Step-E extrude requires valid Top_S.")

        if self.plane is None:
            raise Exception("Step-E extrude requires RefPlane.")

        dist = self.oa_len + self.ij_len
        vec = self.plane.YAxis * (-dist)

        # GH API: Extrude(base, direction) -> [Geometry]
        try:
            extruded = ghc.Extrude(self.top_s, vec)
        except Exception as ex:
            raise Exception("Cube extrusion failed: ghc.Extrude error: {}".format(ex))

        if extruded is None:
            raise Exception("Cube extrusion failed: ghc.Extrude returned None.")

        # Normalize to first geometry
        geo0 = None
        if isinstance(extruded, rg.GeometryBase):
            geo0 = extruded
        else:
            # IronPython.Runtime.List / list / iterable
            try:
                geo0 = extruded[0]
            except Exception:
                try:
                    geo0 = list(extruded)[0]
                except Exception:
                    geo0 = None

        if geo0 is None:
            raise Exception("Cube extrusion failed: no geometry returned by ghc.Extrude.")

        # Coerce to Brep
        cube = None
        if isinstance(geo0, rg.Brep):
            cube = geo0
        elif isinstance(geo0, rg.Surface):
            cube = geo0.ToBrep()
        elif isinstance(geo0, rg.Extrusion):
            cube = geo0.ToBrep()
        else:
            # last resort: try ToBrep
            try:
                cube = geo0.ToBrep()
            except Exception:
                cube = None

        if cube is None or (hasattr(cube, "IsValid") and not cube.IsValid):
            raise Exception("Cube extrusion failed: result is not a valid Brep (type={}).".format(type(geo0)))

        # Ensure solid (minimal fallback)
        if not cube.IsSolid:
            cube = self._try_cap_planar(cube, self.tol)

        if cube is None or not cube.IsValid:
            raise Exception("Cube extrusion failed: invalid Brep after cap fallback.")

        self.cube_brep = cube
        self.log("[E2] Cube_Brep OK. IsSolid={}".format(self.cube_brep.IsSolid))

    def step_e_split_and_pick(self):
        """
        Step E (Refactor):
        - Split Cube_Brep with Surface_Final using GH API:
              ghc.SplitBrep(brep, cutter) -> [Brep] fragments
        - For EACH fragment, join it with the cutter using GH API:
              ghc.BrepJoin([breps]) -> (joined_breps, closed_flags)

        Outputs (as attributes):
          - self.cube_parts_raw:  raw split fragments (list[rg.Brep])
          - self.cube_parts_joined_all: joined results from each fragment (list[rg.Brep])

        Notes:
          - We keep ONLY valid Breps in both lists.
          - `closed_flags` is returned for reference, but we do NOT compute volumes or pick max volume here.
        """
        if self.cube_brep is None or not isinstance(self.cube_brep, rg.Brep) or not self.cube_brep.IsValid:
            raise Exception("Step-E requires valid Cube_Brep.")
        if self.surface_final is None:
            raise Exception("Step-E requires Surface_Final for splitting/joining.")

        # ----------------------------
        # Split (GH API)
        # ----------------------------
        try:
            parts_raw = ghc.SplitBrep(self.cube_brep, self.surface_final)
        except Exception as ex:
            parts_raw = []
            self.log("[E3][WARN] ghc.SplitBrep failed: {}".format(ex))

        # Normalize + filter
        self.cube_parts_raw = []
        if parts_raw:
            for p in parts_raw:
                self.cube_parts_raw.append(p)

        if len(self.cube_parts_raw) == 0:
            # Ensure downstream outputs are stable
            self.cube_parts = []
            self.cube_parts_joined_all = []
            self.log("[E3][WARN] Split produced no valid parts.")
            return

        # For backward-compatible outputs (if any):
        # Cube_Parts == raw split parts
        self.cube_parts = list(self.cube_parts_raw)

        # ----------------------------
        # Join each part with cutter (GH API)
        # ----------------------------
        # Ensure cutter is a Brep
        cutter_brep = self.surface_final
        if isinstance(cutter_brep, rg.Surface):
            cutter_brep = cutter_brep.ToBrep()
        elif isinstance(cutter_brep, rg.BrepFace):
            cutter_brep = cutter_brep.DuplicateFace(True)
        # If it's already a Brep, keep as-is.

        self.cube_parts_joined_all = []

        # ---- Step-F results ----
        self.cube_parts_vol = []
        self.solid_max_volume = None
        self.cube_parts_closed_flags_all = []  # parallel list (optional debug)

        for i, part in enumerate(self.cube_parts_raw):
            try:
                joined_breps, closed_flags = ghc.BrepJoin([part, cutter_brep])
            except Exception as ex:
                self.log("[E4][WARN] ghc.BrepJoin failed on part {}: {}".format(i, ex))
                continue

            # ghc may return a single Brep/Bool or lists. Normalize.
            jb_list = []
            cf_list = []
            if isinstance(joined_breps, rg.Brep):
                jb_list = [joined_breps]
            elif joined_breps:
                try:
                    jb_list = list(joined_breps)
                except Exception:
                    jb_list = []

            if isinstance(closed_flags, bool):
                cf_list = [closed_flags] * max(1, len(jb_list))
            elif closed_flags:
                try:
                    cf_list = list(closed_flags)
                except Exception:
                    cf_list = [False] * len(jb_list)
            else:
                cf_list = [False] * len(jb_list)

            # Append all valid joined breps (no max-volume picking here)
            for j, brep_j in enumerate(jb_list):
                self.cube_parts_joined_all.append(brep_j)
                # keep the corresponding closed flag if aligned, else False
                flag = cf_list[j] if j < len(cf_list) else False
                self.cube_parts_closed_flags_all.append(bool(flag))

        # Remove volume/max-volume outputs (by requirement). Keep stable, empty.



    # ----------------------------
    # Step-F: volumes + max
    # ----------------------------
    def step_f_pick_max_volume(self):
        """Compute volume for each Brep in Cube_Parts_JoinedAll and pick the max-volume Brep."""
        self.cube_parts_vol = []
        self.solid_max_volume = None

        if not self.cube_parts_joined_all:
            self.log("[F1][WARN] Cube_Parts_JoinedAll is empty; skip volume.")
            return

        max_v = -1.0
        max_b = None

        for b in self.cube_parts_joined_all:
            vol = 0.0
            if isinstance(b, rg.Brep) and b.IsValid:
                try:
                    vmp = rg.VolumeMassProperties.Compute(b)
                    if vmp is not None:
                        vol = float(vmp.Volume)
                except Exception:
                    vol = 0.0
            self.cube_parts_vol.append(vol)
            if vol > max_v:
                max_v = vol
                max_b = b

        self.solid_max_volume = max_b
        self.log("[F1] Volume OK: count={} max={}".format(len(self.cube_parts_vol), max_v))

    def solve_step_e(self):
        self.step_e_build_top_surface()
        self.step_e_extrude_cube()
        self.step_e_split_and_pick()

    def solve_step_f(self):
        self.step_f_pick_max_volume()

    # ----------------------------
    # Solve orchestration
    # ----------------------------
    def solve(self):
        self.solve_step_a()
        self.solve_step_b()
        self.solve_step_c()
        self.solve_step_d()
        self.solve_step_e()
        self.solve_step_f()
        return self

if __name__=="__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    # ==============================================================

    # Step-A outputs
    RefPlane_O = None
    RefPlane_O_XZ = None
    RefPlane_O_YZ = None
    Polyline_O_to_B = None
    Points_OA = []
    Points_AB = []
    ConnectorLines = []
    Intersections_FGH = []

    # Step-B outputs
    Point_I = None
    Point_J = None
    Point_K = None
    Point_L = None
    Plane_BJI = None
    Curve_BLJ = None

    # Step-C outputs
    Point_Op = None
    Points_FGHp = []
    Point_I_from_move = None
    Points_FGHpp = []
    Polyline_Op_to_J = None

    # Step-D outputs
    Point_P = None
    Rail_BP = None
    Surface_Red = None
    Surface_Purple = None
    Surface_S = None
    Surface_S_mirror = None
    Surface_Final = None

    # Step-E outputs
    Top_S = None
    Cube_Brep = None
    Cube_Parts_Raw = []  # raw split fragments (no join)
    Cube_Parts = []
    Cube_Parts_JoinedAll = []

    # Step-F outputs
    Cube_Parts_Vol = []
    Solid_MaxVolume = None

    Debug = ""

    try:
        solver = RuFuJuanShaBottomSolver(
            base_point=BasePoint,
            ref_plane=RefPlane,
            oa_len=OA_len,
            ab_len=AB_len,
            div_count=DivCount,
            bi_len=BI_len,
            ij_len=IJ_len,
            kl_len=KL_len,
            bp_len=BP_len
        ).solve()

        # Step-A
        RefPlane_O = solver.ref_plane_O
        RefPlane_O_XZ = solver.ref_plane_O_XZ
        RefPlane_O_YZ = solver.ref_plane_O_YZ
        Polyline_O_to_B = solver.polyline_curve
        Points_OA = solver.points_OA
        Points_AB = solver.points_AB
        ConnectorLines = solver.connector_lines
        Intersections_FGH = solver.intersections

        # Step-B
        Point_I = solver.I
        Point_J = solver.J
        Point_K = solver.K
        Point_L = solver.L
        Plane_BJI = solver.plane_bji
        Curve_BLJ = solver.curve_blj

        # Step-C
        Point_Op = solver.O_p
        Points_FGHp = solver.FGH_p
        Point_I_from_move = solver.I_from_move
        Points_FGHpp = solver.FGH_pp
        Polyline_Op_to_J = solver.polyline_op_to_j

        # Step-D
        Point_P = solver.P
        Rail_BP = solver.rail_bp
        Surface_Red = solver.surface_red
        Surface_Purple = solver.surface_purple
        Surface_S = solver.surface_s
        Surface_S_mirror = solver.surface_s_mirror
        Surface_Final = solver.surface_final

        # Step-E
        Top_S = solver.top_s
        Cube_Brep = solver.cube_brep
        Cube_Parts_Raw = solver.cube_parts_raw
        Cube_Parts = solver.cube_parts
        Cube_Parts_JoinedAll = solver.cube_parts_joined_all

        # Step-F
        Cube_Parts_Vol = solver.cube_parts_vol
        Solid_MaxVolume = solver.solid_max_volume

        Debug = solver.debug_text()

    except Exception as e:
        Debug = "[ERROR] {}".format(e)
# -*- coding: utf-8 -*-
"""
GHpy :: ChaAng4Pu / TimberSection_ABFE_SchemeD  (+ Qin / PiZhu switch)
------------------------------------------------------------
方案 D（按用户要求）：
- 约束1：E_L 过 A
- 约束2：E_U 过 D
- 约束3：E_U ∥ E_L，且两线法向距离 = thickness（默认15）
- 不约束 B（B 作为计算结果），但仍保持 A、B 位于 H 轴（v=0）
- E 在 E_L 上，且 u=GE（即 G 在 V 轴，GE 为水平距离）
- F 为 E 沿法向回到 E_U 的对应点 => 自动满足 EF=thickness 且 EF ⟂ E_U/E_L
- 截面输出：A-B-F-E-A（矩形）
- 将截面沿参考平面法向 ±offset_dist 偏移并封盖，得到 SolidBrep

新增（琴面昂 / 批竹昂切换）：
- 输入 use_qin (bool)，默认 True：
  - True  -> 使用琴面昂 QinSurface（弧面）裁切 SolidBrep，取体积最大块 QinCutKeep，并尝试 Join QinCutKeep+QinSurface => QinJoinBrep
  - False -> 使用批竹昂：在 EF 上取 H(EH=2)，连 D-H；
            D-H 沿 plane.Normal ±offset_dist 偏移为 D1-H1, D2-H2；
            用两条线 Loft(Straight) 成面 PiZhuPlane，裁切 SolidBrep，取体积最大块 PiZhuCutKeep

最终输出：
- FinalKeepBrep：use_qin=True => 优先 QinCutKeep，否则 QinJoinBrep，否则 SolidBrep
                use_qin=False => 优先 PiZhuCutKeep，否则 SolidBrep

============================================================
【GhPython 输入 Inputs（建议 GH 端配置）】
base_point      : rg.Point3d   Access:item  TypeHint:Point3d   默认 World Origin
ref_plane_mode  : object       Access:item  TypeHint:generic   默认 "WorldXZ"

OA              : float        Access:item  TypeHint:float     默认 5.0
OC              : float        Access:item  TypeHint:float     默认 36.0   （O->C 的 H 向距离；D 位于 C 正下方，即 u_D = u_C = OC）
CD              : float        Access:item  TypeHint:float     默认 6.0    （C->D 的 V 向落差，D 的 v=-CD）

thickness       : float        Access:item  TypeHint:float     默认 15.0
GE              : float        Access:item  TypeHint:float     默认 53.0
tol             : float        Access:item  TypeHint:float     默认 1e-6
offset_dist     : float        Access:item  TypeHint:float     默认 5.0    （截面法向对称偏移距离）

use_qin         : bool         Access:item  TypeHint:bool      默认 True   （True=琴面昂，False=批竹昂）

（已移除）OB, BC：由于 B 点不再固定（在 O-C 线段上滑动满足约束），因此不再作为输入端。

============================================================
【GhPython 输出 Outputs（建议 GH 端配置）】
O,A,B,C,D,E,F,G         : rg.Point3d   Access:item  TypeHint:Point3d
EU_line,EL_line,EF_line : rg.Line      Access:item  TypeHint:Line
Edges                   : list         Access:list  TypeHint:generic
SectionPolyline         : rg.Polyline  Access:item  TypeHint:Polyline
SectionCurve            : rg.Curve     Access:item  TypeHint:Curve
SectionBrep             : rg.Brep      Access:item  TypeHint:Brep
SectionCurve_In/Out      : rg.Curve
SolidBrep               : rg.Brep

# 琴面昂（Qin）
H,I,J,K,L,N,D1,D2,H1,H2,N1,N2 : rg.Point3d
Arc_JLI, Arc_DNH, Arc_D1N1H1, Arc_D2N2H2, Arc_D1JD2, Arc_H1IH2 : rg.Curve
QinSurface               : rg.Brep
QinCutBreps              : list[rg.Brep]
QinCutKeep               : rg.Brep
QinJoinBrep              : rg.Brep

# 批竹昂（PiZhu）
PiZhu_H                   : rg.Point3d
PiZhu_DH                  : rg.Line
PiZhu_D1H1, PiZhu_D2H2     : rg.Line
PiZhuPlane                : rg.Brep
PiZhuCutBreps             : list[rg.Brep]
PiZhuCutKeep              : rg.Brep

# 最终
FinalKeepBrep            : rg.Brep
Log                      : list[str]
"""

import Rhino.Geometry as rg
import math
import ghpythonlib.components as ghc


# =========================================================
# 输入健壮性：把 base_point 从多种可能类型强制转为 Point3d
# =========================================================
def _coerce_point3d(p, default=None):
    if default is None:
        default = rg.Point3d(0, 0, 0)
    if p is None:
        return default
    if isinstance(p, rg.Point3d):
        return p
    try:
        if isinstance(p, rg.Point):
            return p.Location
    except:
        pass
    if isinstance(p, (list, tuple)) and len(p) >= 3:
        try:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        except:
            return default
    if isinstance(p, str):
        s = p.strip().replace("，", ",")
        if "," in s:
            parts = [k.strip() for k in s.split(",") if k.strip() != ""]
        else:
            parts = [k for k in s.split() if k != ""]
        if len(parts) >= 3:
            try:
                return rg.Point3d(float(parts[0]), float(parts[1]), float(parts[2]))
            except:
                return default
    return default


def _coerce_bool(v, default=True):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    # GH Panel 常见输入为 0/1、True/False 字符串
    if isinstance(v, (int, float)):
        return bool(int(v))
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "yes", "y", "1", "on"):
            return True
        if s in ("false", "f", "no", "n", "0", "off"):
            return False
    return default


# =========================================================
# GhPython 输入变量兜底定义（防 pylance / pyflakes 报错）
# =========================================================
try:
    base_point
except NameError:
    base_point = rg.Point3d(0, 0, 0)
base_point = _coerce_point3d(base_point, rg.Point3d(0, 0, 0))

try:
    ref_plane_mode
except NameError:
    ref_plane_mode = "WorldXZ"

try:
    OA
except NameError:
    OA = 5.0
try:
    OC
except NameError:
    OC = 36.0
try:
    CD
except NameError:
    CD = 6.0
try:
    thickness
except NameError:
    thickness = 15.0
try:
    GE
except NameError:
    GE = 53.0
try:
    tol
except NameError:
    tol = 1e-6
try:
    offset_dist
except NameError:
    offset_dist = 5.0

try:
    use_qin
except NameError:
    use_qin = True
use_qin = _coerce_bool(use_qin, default=True)

# OB / BC 已移除：B 在 O-C 线段滑动，OB/BC 不再作为输入端


class GHRefPlane(object):
    @staticmethod
    def from_mode(base_point_, mode):
        if isinstance(mode, rg.Plane):
            pl = rg.Plane(mode)
            pl.Origin = base_point_
            return pl

        m = "WorldXZ" if mode is None else str(mode).strip()

        # 用户给定三种参考平面轴向关系：
        # XY: X=(1,0,0) Y=(0,1,0)
        # XZ: X=(1,0,0) Y=(0,0,1)
        # YZ: X=(0,1,0) Y=(0,0,1)
        if m == "WorldXY":
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 1, 0)
        elif m == "WorldYZ":
            x = rg.Vector3d(0, 1, 0)
            y = rg.Vector3d(0, 0, 1)
        else:  # WorldXZ
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)

        return rg.Plane(base_point_, x, y)


class ChaAngQiAoV2(object):
    def __init__(self, base_point_, ref_plane_mode_="WorldXZ",
                 OA_=5.0, OC_=36.0, CD_=6.0,
                 thickness_=15.0, GE_=53.0, tol_=1e-6,
                 offset_dist_=5.0, use_qin_=True):
        self.base_point = base_point_ if base_point_ is not None else rg.Point3d(0, 0, 0)
        self.ref_plane_mode = ref_plane_mode_ if ref_plane_mode_ is not None else "WorldXZ"

        self.OA = float(OA_)
        self.OC = float(OC_)
        self.CD = float(CD_)
        self.thickness = float(thickness_)
        self.GE = float(GE_)
        self.tol = float(tol_)
        self.offset_dist = float(offset_dist_) if offset_dist_ is not None else 5.0
        self.use_qin = _coerce_bool(use_qin_, default=True)

        self.log = []
        self.plane = None

        # base outputs
        self.O = self.A = self.B = self.C = self.D = None
        self.E = self.F = self.G = None
        self.EU_line = None
        self.EL_line = None
        self.EF_line = None
        self.edges = []
        self.section_polyline = None
        self.section_curve = None
        self.section_brep = None
        self.section_curve_in = None
        self.section_curve_out = None
        self.solid_brep = None

        # SolidBrep debug faces
        # face (as Brep) that contains / is closest to segment A-E on SolidBrep
        self.solid_face_AE = None

        # =====================================================
        # 琴面昂（Qin）
        # =====================================================
        self.H = self.I = self.J = self.K = self.L = self.N = None
        self.D1 = self.D2 = self.H1 = self.H2 = None
        self.N1 = self.N2 = None
        self.arc_JLI = None
        self.arc_DNH = None
        self.arc_D1N1H1 = None
        self.arc_D2N2H2 = None
        self.arc_D1JD2 = None
        self.arc_H1IH2 = None
        self.qin_surface = None
        self.qin_cut_breps = None
        self.qin_cut_keep = None
        self.qin_join_brep = None

        # =====================================================
        # 批竹昂（PiZhu）
        # =====================================================
        self.pizhu_H = None
        self.pizhu_DH = None
        self.pizhu_D1H1 = None
        self.pizhu_D2H2 = None
        self.pizhu_plane = None
        self.pizhu_cut_breps = None
        self.pizhu_cut_keep = None
        self.pizhu_join_brep = None

        # final
        self.final_keep_brep = None

    def _pt_uv(self, u, v):
        return self.plane.PointAt(u, v)

    def _unit2(self, x, y):
        l = math.sqrt(x * x + y * y)
        if l <= self.tol:
            return None
        return (x / l, y / l)

    def _perp_ccw(self, x, y):
        return (-y, x)

    def _pick_direction(self, candidates):
        # 优先选择“向右下”（du>0 且 dv<0）
        for du, dv in candidates:
            if du > 0 and dv < 0:
                return (du, dv)
        for du, dv in candidates:
            if du > 0:
                return (du, dv)
        return candidates[0]

    # -----------------------------
    # 琴面昂：几何小工具
    # -----------------------------
    def _arc3(self, p0, pm, p1):
        """三点成弧（Arc->NurbsCurve）。若三点近共线则返回折线。"""
        try:
            a = rg.Arc(p0, pm, p1)
            if a.IsValid:
                return a.ToNurbsCurve()
        except:
            pass
        pl = rg.Polyline([p0, pm, p1])
        return pl.ToNurbsCurve()

    def _vec_unit(self, v):
        v = rg.Vector3d(v)
        if v.IsTiny(self.tol):
            return None
        v.Unitize()
        return v

    def _closest_point_param_on_line(self, line, pt):
        d = line.To - line.From
        if d.IsTiny(self.tol):
            return None
        d = rg.Vector3d(d)
        denom = d * d
        if abs(denom) <= self.tol:
            return None
        t = rg.Vector3d(pt - line.From) * d / denom
        return t

    def _brep_volume(self, brep):
        if brep is None:
            return None
        try:
            mp = rg.VolumeMassProperties.Compute(brep)
            if mp is None:
                return None
            return float(mp.Volume)
        except:
            return None

    def _pick_larger_brep(self, breps):
        best = None
        best_v = None
        for b in (breps or []):
            v = self._brep_volume(b)
            if v is None:
                continue
            if (best_v is None) or (v > best_v):
                best_v = v
                best = b
        return best, best_v

    def _closest_face_index(self, brep, pt):
        """Return index of the BrepFace that is closest to pt. None if failed."""
        if brep is None or pt is None:
            return None
        try:
            faces = brep.Faces
        except:
            return None
        best_i = None
        best_d2 = None
        for i in range(faces.Count):
            f = faces[i]
            try:
                ok, u, v = f.ClosestPoint(pt)
                if not ok:
                    continue
                cp = f.PointAt(u, v)
                d2 = cp.DistanceToSquared(pt)
                if (best_d2 is None) or (d2 < best_d2):
                    best_d2 = d2
                    best_i = i
            except:
                continue
        return best_i

    def _is_rectangular_planar_face(self, brep_face, tol):
        """Heuristic: planar face with 4 straight edges (rectangle-ish)."""
        if brep_face is None:
            return False, None
        try:
            if not brep_face.IsPlanar(tol):
                return False, None
        except:
            return False, None
        try:
            fb = brep_face.DuplicateFace(False)  # Brep
        except:
            fb = None
        if fb is None:
            return False, None
        try:
            if fb.Edges.Count != 4:
                return False, fb
            # all 4 edges are lines
            for ei in range(fb.Edges.Count):
                crv = fb.Edges[ei].DuplicateCurve()
                ln = rg.Line()
                if not crv.TryGetLine(ln):
                    return False, fb
            return True, fb
        except:
            return False, fb

    def _closest_planar_rect_face_index(self, brep, pt, tol):
        """Return closest planar-rect face index to pt."""
        if brep is None or pt is None:
            return None
        best_i = None
        best_d2 = None
        for i in range(brep.Faces.Count):
            f = brep.Faces[i]
            ok_rect, _ = self._is_rectangular_planar_face(f, tol)
            if not ok_rect:
                continue
            try:
                ok, u, v = f.ClosestPoint(pt)
                if not ok:
                    continue
                cp = f.PointAt(u, v)
                d2 = cp.DistanceToSquared(pt)
                if (best_d2 is None) or (d2 < best_d2):
                    best_d2 = d2
                    best_i = i
            except:
                continue
        return best_i

    def _find_planar_rect_face_index_by_edge_points(self, brep, p0, p1, tol):
        """Find the planar-rect face adjacent to the brep edge that matches segment p0-p1."""
        if brep is None or p0 is None or p1 is None:
            return None
        # eps: be a bit looser than model tol (GH user points may carry tiny noise)
        eps = max(float(tol) * 10.0, 1e-4)
        best_i = None
        best_area = None

        try:
            edges = brep.Edges
        except:
            return None

        for ei in range(edges.Count):
            e = edges[ei]
            try:
                s = e.PointAtStart
                t = e.PointAtEnd
                match = (s.DistanceTo(p0) <= eps and t.DistanceTo(p1) <= eps) or (
                            s.DistanceTo(p1) <= eps and t.DistanceTo(p0) <= eps)
                if not match:
                    continue

                # candidate faces adjacent to this edge
                try:
                    adj = e.AdjacentFaces()
                except:
                    adj = e.AdjacentFaces  # some RhinoCommon versions expose as property

                for fi in adj:
                    if fi is None or fi < 0:
                        continue
                    f = brep.Faces[fi]
                    ok_rect, _fb = self._is_rectangular_planar_face(f, tol)
                    if not ok_rect:
                        continue
                    try:
                        amp = rg.AreaMassProperties.Compute(_fb)
                        area = amp.Area if amp else None
                    except:
                        area = None

                    # pick the larger planar-rect among adjacent (usually the end-cap)
                    if best_area is None:
                        best_area = area
                        best_i = fi
                    else:
                        if (area is not None) and (best_area is None or area > best_area):
                            best_area = area
                            best_i = fi
            except:
                continue

        return best_i

    def _duplicate_face_brep(self, brep, face_index):
        """Duplicate the face at index as a single-face Brep (untrimmed=False)."""
        if brep is None or face_index is None:
            return None
        try:
            f = brep.Faces[face_index]
            # DuplicateFace(False) -> keep trims (single face brep)
            return f.DuplicateFace(False)
        except:
            return None

    def _ensure_closed_brep(self, brep):
        """
        方法1：对 CutKeep 封面/封孔（cap），确保输出为有效 Brep（尽量闭合）。
        - 若 brep 已为 solid/closed，则直接返回
        - 否则尝试 CapPlanarHoles / CapPlanarHolesEx（版本兼容）
        """
        if brep is None:
            return None
        try:
            # 若已经是实心或闭合，直接返回
            if brep.IsSolid:
                return brep
        except:
            pass

        # 尝试封孔（通常 Split 后已闭合；若因数值问题变成开口，这里补救）
        try:
            capped = brep.CapPlanarHoles(self.tol)
            if capped is not None:
                return capped
        except:
            pass
        # 有些版本提供 CapPlanarHolesEx
        try:
            capped = brep.CapPlanarHolesEx(self.tol)
            if capped is not None:
                return capped
        except:
            pass

        return brep

    def solve(self):
        self.plane = GHRefPlane.from_mode(self.base_point, self.ref_plane_mode)
        # =====================================================
        # 参考平面输出（新增）
        # - Plane_Main : 当前 ref_plane_mode 对应的参考平面
        # - Plane_X    : 垂直于 Plane_Main，过 X 轴
        # - Plane_Y    : 垂直于 Plane_Main，过 Y 轴
        # =====================================================
        self.Plane_Main = rg.Plane(self.plane)
        self.Plane_X = rg.Plane(
            self.base_point,
            rg.Vector3d(self.plane.XAxis),
            rg.Vector3d(self.plane.Normal)
        )
        self.Plane_Y = rg.Plane(
            self.base_point,
            rg.Vector3d(self.plane.YAxis),
            rg.Vector3d(self.plane.Normal)
        )

        # 始终保证 O 输出为 base_point
        self.O = rg.Point3d(self.base_point)

        # O, A 在 H 轴 (v=0)
        self.O = self._pt_uv(0.0, 0.0)
        self.A = self._pt_uv(-self.OA, 0.0)

        # C / D：C 在 H 轴，D 为其正下方（固定 OC, CD）
        self.C = self._pt_uv(self.OC, 0.0)
        self.D = self._pt_uv(self.OC, -self.CD)

        # 在 (u,v) 中：v = A - D
        v_u = (-self.OA) - (self.OC)
        v_v = 0.0 - (-self.CD)  # = CD

        dist_AD = math.sqrt(v_u * v_u + v_v * v_v)
        if self.thickness >= dist_AD - self.tol:
            self.log.append("ERROR: thickness >= |A-D|，无解。")
            return self._pack()

        # 单位向量 v_hat
        v_hat = (v_u / dist_AD, v_v / dist_AD)
        alpha_list = [self.thickness / dist_AD, -self.thickness / dist_AD]

        # 与 v_hat 垂直的单位向量 w_hat
        w_hat = (-v_hat[1], v_hat[0])

        n_candidates = []
        for alpha in alpha_list:
            t = 1.0 - alpha * alpha
            if t < -self.tol:
                continue
            t = max(0.0, t)
            beta = math.sqrt(t)
            n_candidates.append((alpha * v_hat[0] + beta * w_hat[0], alpha * v_hat[1] + beta * w_hat[1], alpha))
            if beta > self.tol:
                n_candidates.append((alpha * v_hat[0] - beta * w_hat[0], alpha * v_hat[1] - beta * w_hat[1], alpha))

        if not n_candidates:
            self.log.append("ERROR: 无法构造单位法向。")
            return self._pack()

        # 每个 n -> 两个方向 d（±perp(n)）。
        # 这里改为“带约束选择”：
        # - B 必须落在 O-C 线段（uB in [0, OC]，允许 tol）
        # - 优先 E 在 H 轴下方（vE < 0），且 d 指向“右下”（du>0,dv<0）
        d_candidates = []
        for nx, ny, alpha in n_candidates:
            du0, dv0 = self._perp_ccw(nx, ny)
            d_candidates.append((du0, dv0, nx, ny, alpha))
            d_candidates.append((-du0, -dv0, nx, ny, alpha))

        best_pack = None
        best_score = 1e99

        for du0, dv0, nx, ny, alpha in d_candidates:
            d_unit = self._unit2(du0, dv0)
            if d_unit is None:
                continue
            du, dv = d_unit

            # 基本退化保护
            if abs(dv) <= self.tol or abs(du) <= self.tol:
                continue

            # B：EU(过D) 与 H 轴(v=0)交点
            tB = (0.0 - (-self.CD)) / dv
            uB = self.OC + tB * du

            # E：EL(过A) 与 u=GE 竖线交点
            tE = (self.GE - (-self.OA)) / du
            vE = 0.0 + tE * dv

            # shift（EU -> EL 的法向位移），优先让其 v 分量为负（E_U 在 E_L 上方）
            s_signed = alpha * dist_AD
            shift_v = ny * s_signed

            # 评分（越小越好）
            score = 0.0
            # 1) 强约束：B 在 [0, OC]
            if uB < -self.tol:
                score += 1e6 + (-uB) * 1e3
            elif uB > self.OC + self.tol:
                score += 1e6 + (uB - self.OC) * 1e3

            # 2) 期望：E 在下方（vE < 0）
            if vE >= 0:
                score += 1e3 + vE * 10.0

            # 3) 期望：d 指向右下
            if not (du > 0 and dv < 0):
                score += 50.0

            # 4) 期望：shift_v < 0
            if shift_v >= 0:
                score += 10.0

            if score < best_score:
                best_score = score
                best_pack = (du, dv, nx, ny, s_signed)

        if best_pack is None:
            # 兜底：沿原逻辑取一个“右下”方向
            d_only = [(du, dv) for du, dv, _, _, _ in d_candidates]
            du, dv = self._pick_direction(d_only)
            d_unit = self._unit2(du, dv)
            if d_unit is None:
                self.log.append("ERROR: 方向退化。")
                return self._pack()
            du, dv = d_unit
            nx, ny, alpha = n_candidates[0]
            s_signed = alpha * dist_AD
        else:
            du, dv, nx, ny, s_signed = best_pack

        # 记录约束满足情况
        try:
            tB_dbg = (0.0 - (-self.CD)) / dv
            uB_dbg = self.OC + tB_dbg * du
            self.log.append("B on OC check: uB={:.6f}, range=[0,{:.6f}]".format(uB_dbg, self.OC))
        except:
            pass

        # 构造 EU / EL（长线用于显示/求交）
        L = 1e4
        EU_p0 = self._pt_uv(self.OC - du * L, -self.CD - dv * L)
        EU_p1 = self._pt_uv(self.OC + du * L, -self.CD + dv * L)
        self.EU_line = rg.Line(EU_p0, EU_p1)

        EL_p0 = self._pt_uv(-self.OA - du * L, 0.0 - dv * L)
        EL_p1 = self._pt_uv(-self.OA + du * L, 0.0 + dv * L)
        self.EL_line = rg.Line(EL_p0, EL_p1)

        # shift（EU -> EL 的法向位移）
        n_world = self.plane.XAxis * nx + self.plane.YAxis * ny
        n_world.Unitize()
        shift = n_world * s_signed

        self.log.append("Check: |s_signed| = {:.6f} (target {})".format(abs(s_signed), self.thickness))

        # B = EU 与 H 轴(v=0)交点
        if abs(dv) <= self.tol:
            self.log.append("ERROR: dv≈0，无法得到 B。")
            return self._pack()
        tB = (0.0 - (-self.CD)) / dv
        uB = self.OC + tB * du
        self.B = self._pt_uv(uB, 0.0)

        # E：EL 与 u=GE 竖线交点
        if abs(du) <= self.tol:
            self.log.append("ERROR: du≈0，无法得到 E。")
            return self._pack()
        tE = (self.GE - (-self.OA)) / du
        vE = 0.0 + tE * dv
        self.E = self._pt_uv(self.GE, vE)

        # G：u=0 且与 E 同 v
        self.G = self._pt_uv(0.0, vE)

        # F：从 EL 回到 EU
        self.F = self.E - shift
        self.EF_line = rg.Line(self.E, self.F)

        # 组装矩形 A-B-F-E-A
        AB = rg.Line(self.A, self.B)
        BF = rg.Line(self.B, self.F)
        FE = rg.Line(self.F, self.E)
        EA = rg.Line(self.E, self.A)
        self.edges = [AB, BF, FE, EA]

        pts = [self.A, self.B, self.F, self.E, self.A]
        self.section_polyline = rg.Polyline(pts)
        self.section_curve = self.section_polyline.ToNurbsCurve()
        breps = rg.Brep.CreatePlanarBreps(self.section_curve, self.tol)
        self.section_brep = breps[0] if breps and len(breps) > 0 else None

        # =====================================================
        # 对称偏移截面并封面为体（SolidBrep）
        # =====================================================
        if self.section_curve is not None and self.section_curve.IsClosed and self.offset_dist > self.tol:
            n = rg.Vector3d(self.plane.Normal)
            if n.IsTiny(self.tol):
                self.log.append("ERROR: plane.Normal is tiny; cannot build solid.")
            else:
                n.Unitize()
                self.section_curve_in = self.section_curve.DuplicateCurve()
                self.section_curve_out = self.section_curve.DuplicateCurve()
                self.section_curve_in.Transform(rg.Transform.Translation(-n * self.offset_dist))
                self.section_curve_out.Transform(rg.Transform.Translation(n * self.offset_dist))

                try:
                    c_in = self.section_curve_in
                    c_out = self.section_curve_out
                    lofts = rg.Brep.CreateFromLoft([c_in, c_out], rg.Point3d.Unset, rg.Point3d.Unset,
                                                   rg.LoftType.Normal, False)
                    if not lofts:
                        self.solid_brep = None
                        self.log.append("ERROR: Brep.CreateFromLoft failed (no side brep).")
                    else:
                        side = lofts[0]
                        cap_in = rg.Brep.CreatePlanarBreps(c_in, self.tol)
                        cap_out = rg.Brep.CreatePlanarBreps(c_out, self.tol)
                        if not cap_in or not cap_out:
                            self.solid_brep = None
                            self.log.append("ERROR: CreatePlanarBreps failed for caps (in/out).")
                        else:
                            parts = [side, cap_in[0], cap_out[0]]
                            joined = rg.Brep.JoinBreps(parts, self.tol)
                            self.solid_brep = joined[0] if joined and len(joined) > 0 else None
                            if self.solid_brep is None:
                                self.log.append("ERROR: JoinBreps failed; solid is None.")
                except Exception as ex:
                    self.solid_brep = None
                    self.log.append("ERROR: solid build (loft+cap) failed: {}".format(ex))
        else:
            if self.offset_dist <= self.tol:
                self.log.append("Info: offset_dist <= tol; solid generation skipped.")
            else:
                self.log.append("Warning: SectionCurve is None or not closed; solid generation skipped.")

        # =====================================================
        # SolidBrep face that corresponds to edge A-E (debug output)
        # 目标：找到“包含 A-E 这条边”的那个矩形平面（通常是实体的端面 / 封盖面）
        # =====================================================
        self.solid_face_AE = None
        try:
            if (self.solid_brep is not None) and (self.A is not None) and (self.E is not None):
                mid_AE = rg.Point3d(
                    (self.A.X + self.E.X) * 0.5,
                    (self.A.Y + self.E.Y) * 0.5,
                    (self.A.Z + self.E.Z) * 0.5,
                )

                # 将这一圈侧面“炸开”（等价 Rhino 的 Explode 对带折线/kink 的面拆分）
                # 说明：放样侧面在 Rhino 中往往是一张带折线的面，Explode 后会被拆成 4 个矩形平面；
                # RhinoCommon 中用 SplitKinkyFaces 可得到同样效果。
                brep_work = self.solid_brep.DuplicateBrep()
                try:
                    angle_tol = math.radians(1.0)  # 1°：足以分离直角折线
                    brep_work.Faces.SplitKinkyFaces(angle_tol, True)
                except Exception:
                    # 若拆分失败也没关系，后续会继续用未拆分的 brep_work 做兜底
                    pass

                # 1) 优先：在“炸开后”的各个矩形平面里，找包含 A–E 这条边的那一片
                fi = self._find_planar_rect_face_index_by_edge_points(brep_work, self.A, self.E, self.tol)

                # 2) 兜底1：若边匹配不易（数值误差/点非同一实例），取离 A–E 中点最近的矩形平面
                if fi is None:
                    fi = self._closest_planar_rect_face_index(brep_work, mid_AE, self.tol)

                # 3) 兜底2：最后退回最近面（仅作保险）
                if fi is None:
                    fi = self._closest_face_index(brep_work, mid_AE)

                self.solid_face_AE = self._duplicate_face_brep(brep_work, fi)
        except Exception as _fae_ex:
            self.solid_face_AE = None
            self.log.append("[SolidFace_AE] ERROR: {}".format(_fae_ex))

        # 校验
        d_world = self.plane.XAxis * du + self.plane.YAxis * dv
        d_world.Unitize()
        ef_vec = self.F - self.E
        ef_len = ef_vec.Length
        if ef_len > self.tol:
            ef_u = rg.Vector3d(ef_vec)
            ef_u.Unitize()
            dot = abs(rg.Vector3d.Multiply(d_world, ef_u))
            self.log.append("Check: EF = {:.6f} (target {})".format(self.E.DistanceTo(self.F), self.thickness))
            self.log.append("Check: |dot(EF, EU_dir)| = {:.6e} (target ~0)".format(dot))

        self.log.append("Check: GE = {:.6f} (target {})".format(self.G.DistanceTo(self.E), self.GE))
        self.log.append("Info: Solved uB (O->B) = {:.6f}".format(uB))

        # =====================================================
        # 切割：use_qin=True => 琴面昂；False => 批竹昂
        # =====================================================

        if self.use_qin:
            # =====================================================
            # 琴面昂弧形截面与弧面（按用户 1~5 步）
            # =====================================================
            try:
                EF_dir = self._vec_unit(self.F - self.E)
                if EF_dir is None:
                    raise Exception("EF_dir tiny")

                self.H = rg.Point3d(self.E) + EF_dir * 2.0  # EH=2
                self.I = rg.Point3d(self.H) + EF_dir * 1.0  # HI=1

                DH_dir = self._vec_unit(self.H - self.D)
                if DH_dir is None:
                    raise Exception("DH_dir tiny")

                BF_line = rg.Line(self.B, self.F)
                Ltmp = 1e4
                I_line = rg.Line(self.I - DH_dir * Ltmp, self.I + DH_dir * Ltmp)

                J_pt = None
                try:
                    ok, a, b = rg.Intersect.Intersection.LineLine(I_line, BF_line, self.tol, True)
                    if ok:
                        J_pt = I_line.PointAt(a)
                except:
                    pass
                if J_pt is None:
                    try:
                        a, b = rg.Intersect.Intersection.LineLine(I_line, BF_line, self.tol, True)
                        J_pt = I_line.PointAt(a)
                    except:
                        pass
                if J_pt is None:
                    t = self._closest_point_param_on_line(BF_line, self.I)
                    if t is None:
                        raise Exception("LineLine failed")
                    J_pt = BF_line.PointAt(t)

                self.J = J_pt

                self.K = rg.Point3d((self.J.X + self.I.X) * 0.5, (self.J.Y + self.I.Y) * 0.5,
                                    (self.J.Z + self.I.Z) * 0.5)

                JI_dir = self._vec_unit(self.I - self.J)
                if JI_dir is None:
                    raise Exception("JI_dir tiny")

                pln_n = rg.Vector3d(self.plane.Normal)
                pln_n.Unitize()
                perp_u = self._vec_unit(rg.Vector3d.CrossProduct(pln_n, JI_dir))
                if perp_u is None:
                    perp_u = self._vec_unit(rg.Vector3d.CrossProduct(JI_dir, pln_n))
                if perp_u is None:
                    raise Exception("perp tiny")

                cand1 = rg.Point3d(self.K) + perp_u * 2.0
                cand2 = rg.Point3d(self.K) - perp_u * 2.0
                self.L = cand1 if cand1.DistanceTo(self.D) < cand2.DistanceTo(self.D) else cand2
                self.arc_JLI = self._arc3(self.J, self.L, self.I)

                dir_KL = self._vec_unit(self.L - self.K)
                if dir_KL is None:
                    raise Exception("dir_KL tiny")
                self.N = rg.Point3d(self.K) + dir_KL * 3.0
                self.arc_DNH = self._arc3(self.D, self.N, self.H)

                n = rg.Vector3d(self.plane.Normal)
                if n.IsTiny(self.tol):
                    raise Exception("plane normal tiny")
                n.Unitize()
                off = float(self.offset_dist)

                self.D1 = rg.Point3d(self.D) - n * off
                self.D2 = rg.Point3d(self.D) + n * off
                self.H1 = rg.Point3d(self.H) - n * off
                self.H2 = rg.Point3d(self.H) + n * off
                self.N1 = rg.Point3d(self.N) - n * off
                self.N2 = rg.Point3d(self.N) + n * off

                self.arc_D1N1H1 = self._arc3(self.D1, self.N1, self.H1)
                self.arc_D2N2H2 = self._arc3(self.D2, self.N2, self.H2)

                self.arc_D1JD2 = self._arc3(self.D1, self.J, self.D2)
                self.arc_H1IH2 = self._arc3(self.H1, self.I, self.H2)

                self.qin_surface = None
                try:
                    self.qin_surface = rg.Brep.CreateEdgeSurface(
                        [self.arc_D1N1H1, self.arc_D2N2H2, self.arc_D1JD2, self.arc_H1IH2])
                    if self.qin_surface is None:
                        raise Exception("EdgeSurface None")
                except:
                    lofts = rg.Brep.CreateFromLoft([self.arc_D1N1H1, self.arc_D2N2H2],
                                                   rg.Point3d.Unset, rg.Point3d.Unset,
                                                   rg.LoftType.Normal, False)
                    self.qin_surface = lofts[0] if lofts and len(lofts) > 0 else None

                if self.qin_surface is None:
                    self.log.append("[Qin] WARN: qin_surface is None.")
                else:
                    self.log.append("[Qin] OK: qin_surface built.")

                # QinSurface 裁切 SolidBrep
                self.qin_cut_breps = None
                self.qin_cut_keep = None
                self.qin_join_brep = None

                if (self.qin_surface is not None) and (self.solid_brep is not None):
                    pieces = self.solid_brep.Split(self.qin_surface, self.tol)
                    if pieces and len(pieces) >= 2:
                        self.qin_cut_breps = list(pieces)
                        keep, keep_v = self._pick_larger_brep(self.qin_cut_breps)
                        self.qin_cut_keep = keep
                        self.log.append("[QinCut] OK: split pieces={}, keep_volume={}".format(len(pieces), keep_v))

                        # Join QinCutKeep + QinSurface
                        try:
                            join_list = []
                            if self.qin_cut_keep is not None:
                                join_list.append(self.qin_cut_keep)
                            join_list.append(self.qin_surface)
                            joined = rg.Brep.JoinBreps(join_list, self.tol)
                            if joined and len(joined) > 0:
                                self.qin_join_brep = joined[0]
                                if len(joined) > 1:
                                    self.log.append(
                                        "[QinJoin] WARN: JoinBreps returned {} breps; take first.".format(len(joined)))
                                else:
                                    self.log.append("[QinJoin] OK: joined into 1 brep.")
                            else:
                                self.log.append(
                                    "[QinJoin] WARN: JoinBreps returned None/empty; fallback to capped QinCutKeep.")
                                self.qin_join_brep = self._ensure_closed_brep(self.qin_cut_keep)
                        except Exception as _jex:
                            self.qin_join_brep = self._ensure_closed_brep(self.qin_cut_keep)
                            self.log.append("[QinJoin] ERROR: {} (fallback to capped QinCutKeep)".format(_jex))
                    else:
                        self.log.append("[QinCut] WARN: Split returned <2 pieces; no keep brep.")
                else:
                    self.log.append("[QinCut] SKIP: QinSurface or SolidBrep is None.")
            except Exception as _qin_ex:
                self.log.append("[Qin] ERROR: {}".format(_qin_ex))

        else:
            # =====================================================
            # 批竹昂：D-H 偏移两侧成面 -> 切割
            # =====================================================
            try:
                EF_dir = self._vec_unit(self.F - self.E)
                if EF_dir is None:
                    raise Exception("EF_dir tiny")

                self.pizhu_H = rg.Point3d(self.E) + EF_dir * 2.0  # EH=2
                self.pizhu_DH = rg.Line(self.D, self.pizhu_H)

                n = rg.Vector3d(self.plane.Normal)
                if n.IsTiny(self.tol):
                    raise Exception("plane normal tiny")
                n.Unitize()
                off = float(self.offset_dist)

                D1 = rg.Point3d(self.D) - n * off
                H1 = rg.Point3d(self.pizhu_H) - n * off
                D2 = rg.Point3d(self.D) + n * off
                H2 = rg.Point3d(self.pizhu_H) + n * off

                self.pizhu_D1H1 = rg.Line(D1, H1)
                self.pizhu_D2H2 = rg.Line(D2, H2)

                # 两条线段成面：Straight loft
                crv1 = self.pizhu_D1H1.ToNurbsCurve()
                crv2 = self.pizhu_D2H2.ToNurbsCurve()
                lofts = rg.Brep.CreateFromLoft([crv1, crv2],
                                               rg.Point3d.Unset, rg.Point3d.Unset,
                                               rg.LoftType.Straight, False)
                self.pizhu_plane = lofts[0] if lofts and len(lofts) > 0 else None
                if self.pizhu_plane is None:
                    self.log.append("[PiZhu] WARN: PiZhuPlane is None.")
                else:
                    self.log.append("[PiZhu] OK: PiZhuPlane built.")

                # 裁切
                self.pizhu_cut_breps = None
                self.pizhu_cut_keep = None
                if (self.pizhu_plane is not None) and (self.solid_brep is not None):
                    pieces = self.solid_brep.Split(self.pizhu_plane, self.tol)
                    if pieces and len(pieces) >= 2:
                        self.pizhu_cut_breps = list(pieces)
                        keep, keep_v = self._pick_larger_brep(self.pizhu_cut_breps)
                        self.pizhu_cut_keep = keep
                        self.log.append("[PiZhuCut] OK: split pieces={}, keep_volume={}".format(len(pieces), keep_v))
                    else:
                        self.log.append("[PiZhuCut] WARN: Split returned <2 pieces; no keep brep.")
                else:
                    self.log.append("[PiZhuCut] SKIP: PiZhuPlane or SolidBrep is None.")

                    # =====================================================
                # PiZhuJoin：用 GH 的 Brep Join 将 PiZhuCutKeep 与 PiZhuPlane Join 为一个 Brep
                # - 这是用户要求的“Grasshopper API Join”，比 RhinoCommon.JoinBreps 更接近 GH 组件表现
                # - 若 Join 失败或返回空，则回退为对 PiZhuCutKeep 封孔（CutKeep 通常已包含切割面）
                # =====================================================
                self.pizhu_join_brep = None
                try:
                    if (self.pizhu_cut_keep is not None) and (self.pizhu_plane is not None):
                        joined = ghc.BrepJoin(self.pizhu_cut_keep, self.pizhu_plane)
                        # ghc.BrepJoin 可能返回单 Brep 或 list[ Brep ]
                        if isinstance(joined, list):
                            self.pizhu_join_brep = joined[0] if len(joined) > 0 else None
                        else:
                            self.pizhu_join_brep = joined

                        if self.pizhu_join_brep is None:
                            self.log.append(
                                "[PiZhuJoin] WARN: ghc.BrepJoin returned None; fallback to capped PiZhuCutKeep.")
                            self.pizhu_join_brep = self._ensure_closed_brep(self.pizhu_cut_keep)
                        else:
                            self.log.append("[PiZhuJoin] OK: ghc.BrepJoin success.")
                    else:
                        # 没有足够输入则回退到 cut_keep（若存在）
                        self.log.append(
                            "[PiZhuJoin] SKIP: need PiZhuCutKeep and PiZhuPlane; fallback to capped PiZhuCutKeep.")
                        self.pizhu_join_brep = self._ensure_closed_brep(self.pizhu_cut_keep)
                except Exception as _pjex:
                    self.pizhu_join_brep = self._ensure_closed_brep(self.pizhu_cut_keep)
                    self.log.append(
                        "[PiZhuJoin] ERROR (ghc.BrepJoin): {} (fallback to capped PiZhuCutKeep)".format(_pjex))

            except Exception as _pz_ex:
                self.log.append("[PiZhu] ERROR: {}".format(_pz_ex))

                # --- 选择前兜底：确保 JoinBrep 不为空（尤其是 PiZhu 分支） ---
        if (not self.use_qin) and (self.pizhu_join_brep is None):
            self.pizhu_join_brep = self._ensure_closed_brep(self.pizhu_cut_keep)
        if self.use_qin and (self.qin_join_brep is None):
            # Qin 分支同样做最弱兜底，避免 FinalKeepBrep 为空
            self.qin_join_brep = self._ensure_closed_brep(self.qin_cut_keep)

        # =====================================================
        # FinalKeepBrep 选择（按用户要求）：
        # - use_qin=True  -> FinalKeepBrep = QinJoinBrep
        # - use_qin=False -> FinalKeepBrep = PiZhuJoinBrep
        # 若 Join 失败，则 JoinBrep 已在上方回退为（封面/封孔后的）CutKeep，保证不为空
        # =====================================================
        try:
            if self.use_qin:
                self.final_keep_brep = self.qin_join_brep
            else:
                self.final_keep_brep = self.pizhu_join_brep
        except Exception as _sel_ex:
            self.log.append("[Select] ERROR: {}".format(_sel_ex))
            # 最后兜底：仍然不让其为空
            self.final_keep_brep = self._ensure_closed_brep(self.qin_cut_keep if self.use_qin else self.pizhu_cut_keep)

        return self._pack()

    def _pack(self):
        return {
            "O": (self.O if self.O is not None else rg.Point3d(self.base_point)),
            "A": self.A, "B": self.B, "C": self.C, "D": self.D,
            "E": self.E, "F": self.F, "G": self.G,
            "EU_line": self.EU_line, "EL_line": self.EL_line, "EF_line": self.EF_line,
            "Edges": self.edges,
            "SectionPolyline": self.section_polyline,
            "SectionCurve": self.section_curve,
            "SectionBrep": self.section_brep,
            "SectionCurve_In": self.section_curve_in,
            "SectionCurve_Out": self.section_curve_out,
            "SolidBrep": self.solid_brep,
            "SolidFace_AE": self.solid_face_AE,
            "Plane_Main": self.Plane_Main,
            "Plane_X": self.Plane_X,
            "Plane_Y": self.Plane_Y,
            "RefPlanes": [self.Plane_Main, self.Plane_X, self.Plane_Y],

            # switch
            "use_qin": self.use_qin,

            # Qin outputs
            "H": self.H, "I": self.I, "J": self.J, "K": self.K, "L": self.L, "N": self.N,
            "D1": self.D1, "D2": self.D2, "H1": self.H1, "H2": self.H2, "N1": self.N1, "N2": self.N2,
            "Arc_JLI": self.arc_JLI,
            "Arc_DNH": self.arc_DNH,
            "Arc_D1N1H1": self.arc_D1N1H1,
            "Arc_D2N2H2": self.arc_D2N2H2,
            "Arc_D1JD2": self.arc_D1JD2,
            "Arc_H1IH2": self.arc_H1IH2,
            "QinSurface": self.qin_surface,
            "QinCutBreps": self.qin_cut_breps,
            "QinCutKeep": self.qin_cut_keep,
            "QinJoinBrep": self.qin_join_brep,

            # PiZhu outputs
            "PiZhu_H": self.pizhu_H,
            "PiZhu_DH": self.pizhu_DH,
            "PiZhu_D1H1": self.pizhu_D1H1,
            "PiZhu_D2H2": self.pizhu_D2H2,
            "PiZhuPlane": self.pizhu_plane,
            "PiZhuCutBreps": self.pizhu_cut_breps,
            "PiZhuCutKeep": self.pizhu_cut_keep,
            "PiZhuJoinBrep": self.pizhu_join_brep,

            # final
            "FinalKeepBrep": self.final_keep_brep,

            "Log": self.log
        }


if __name__ == "__main__":
    solver = ChaAngQiAoV2(
        base_point_=base_point,
        ref_plane_mode_=ref_plane_mode,
        OA_=OA, OC_=OC, CD_=CD,
        thickness_=thickness, GE_=GE, tol_=tol,
        offset_dist_=offset_dist,
        use_qin_=use_qin
    )
    out = solver.solve()

    # 输出绑定：在 GH 中添加同名输出端即可看到
    O = out["O"];
    A = out["A"];
    B = out["B"];
    C = out["C"];
    D = out["D"]
    E = out["E"];
    F = out["F"];
    G = out["G"]
    EU_line = out["EU_line"];
    EL_line = out["EL_line"];
    EF_line = out["EF_line"]
    Edges = out["Edges"]
    SectionPolyline = out["SectionPolyline"]
    SectionCurve = out["SectionCurve"]
    SectionBrep = out["SectionBrep"]
    SectionCurve_In = out["SectionCurve_In"]
    SectionCurve_Out = out["SectionCurve_Out"]
    SolidBrep = out["SolidBrep"]
    SolidFace_AE = out["SolidFace_AE"]
    Plane_Main = out["Plane_Main"]
    Plane_X = out["Plane_X"]
    Plane_Y = out["Plane_Y"]
    RefPlanes = out["RefPlanes"]
    use_qin = out["use_qin"]

    # --- Qin outputs ---
    H = out["H"];
    I = out["I"];
    J = out["J"];
    K = out["K"];
    L = out["L"];
    N = out["N"]
    D1 = out["D1"];
    D2 = out["D2"];
    H1 = out["H1"];
    H2 = out["H2"];
    N1 = out["N1"];
    N2 = out["N2"]
    Arc_JLI = out["Arc_JLI"]
    Arc_DNH = out["Arc_DNH"]
    Arc_D1N1H1 = out["Arc_D1N1H1"]
    Arc_D2N2H2 = out["Arc_D2N2H2"]
    Arc_D1JD2 = out["Arc_D1JD2"]
    Arc_H1IH2 = out["Arc_H1IH2"]
    QinSurface = out["QinSurface"]
    QinCutBreps = out["QinCutBreps"]
    QinCutKeep = out["QinCutKeep"]
    QinJoinBrep = out["QinJoinBrep"]

    # --- PiZhu outputs ---
    PiZhu_H = out["PiZhu_H"]
    PiZhu_DH = out["PiZhu_DH"]
    PiZhu_D1H1 = out["PiZhu_D1H1"]
    PiZhu_D2H2 = out["PiZhu_D2H2"]
    PiZhuPlane = out["PiZhuPlane"]
    PiZhuCutBreps = out["PiZhuCutBreps"]
    PiZhuCutKeep = out["PiZhuCutKeep"]
    PiZhuJoinBrep = out["PiZhuJoinBrep"]

    # --- Final ---
    FinalKeepBrep = out["FinalKeepBrep"]

    Log = out["Log"]


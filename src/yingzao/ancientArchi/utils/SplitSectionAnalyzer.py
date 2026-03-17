# -*- coding: utf-8 -*-
"""
SplitBrep_Cap_SortByVolume_AndSectionFromBrepXBrep (GhPython Component) - Class Refactor v2f
-----------------------------------------------------------------------------------------
更新内容：
1) 输入端增加 Refresh（Button/Bool）：用于强制重算（否则可走 sticky 缓存）
2) 修正 SortedClosedBreps 可能为空的问题：
   - 不再只依赖 Brep.IsSolid
   - 只要 VolumeMassProperties.Compute 能得到有效体积（> eps），就接受该 Brep 为“可用闭体”
   - CapPlanarHoles 失败也会回退使用原 brep，并尝试计算体积

[FIX 2026-01-14]
3) 修复 ghc.BrepXBrep 返回嵌套 list(DataTree) 时导致的报错：
   - 原因：_dedupe_and_sort_curves 中 _curve_key 期望 Curve，但收到 List
   - 方案：新增 _flatten + _filter_by_type；在 step_section_curves_by_brep_x_brep 里 flatten+过滤
   - 并在 _dedupe_and_sort_curves/_dedupe_and_sort_segments 增加类型保险
"""

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import ghpythonlib.components as ghc
import math


class SplitSectionAnalyzer(object):
    """
    Encapsulate:
    - Split -> Cap -> Volume -> sort
    - GH BrepXBrep -> intersection curves/points
    - Build planar SectionFaces from curves (closed+planar)
    - Stable edges + stable line segments
    - Segment midpoints + feature points
    """

    def __init__(self,
                 brep,
                 cutter,
                 cap_tol=None,
                 split_tol=None,
                 polyline_div_n=64,
                 polyline_min_seg=0.0,
                 planar_tol_factor=50.0,
                 plane_ref=None):
        self.brep = brep
        self.cutter = cutter

        self.cap_tol = self._tol_or_model(cap_tol)
        self.split_tol = self._tol_or_model(split_tol)

        self.polyline_div_n = self._int_or_default(polyline_div_n, 64)
        self.polyline_min_seg = self._float_or_default(polyline_min_seg, 0.0)
        self.planar_tol_factor = self._float_or_default(planar_tol_factor, 50.0)

        self.planar_tol = max(self.cap_tol * self.planar_tol_factor, self.cap_tol + 1e-6)

        self.log = []
        self.cutter_angles_hv = self.compute_cutter_angles_hv()

        # outputs
        self.sorted_closed_breps = []
        self.sorted_volumes = []
        self.max_closed_brep = None

        self.section_curves = []
        self.section_points = []
        self.section_faces = []

        self.stable_edge_curves = []
        self.stable_line_segments = []

        self.segment_midpoints = []
        self.lowest_midpoint = None
        self.highest_midpoint = None

        self.minx_midpoint = None
        self.maxx_midpoint = None
        self.miny_midpoint = None
        self.maxy_midpoint = None
        self.minz_midpoint = None
        self.maxz_midpoint = None

        # plane x cutter intersection (optional)
        self.plane_ref = plane_ref
        self.plane_cutter_curves = []
        self.plane_cutter_midpoint = None

    # =========================================================
    # Cutter orientation helpers
    # =========================================================
    def _best_face_normal(self, brep):
        """Return a representative normal for the Brep (prefer largest planar face).
        Fallback: largest face normal at its mid-UV.
        """
        if not self._is_brep(brep) or brep.Faces.Count == 0:
            return None

        best = None
        best_area = -1.0
        best_is_planar = False

        for fi in range(brep.Faces.Count):
            f = brep.Faces[fi]
            try:
                amp = rg.AreaMassProperties.Compute(f)
                area = float(amp.Area) if amp else 0.0
            except Exception:
                area = 0.0

            plane = rg.Plane.Unset
            is_planar = False
            try:
                is_planar, plane = f.TryGetPlane()
            except Exception:
                is_planar = False

            if is_planar:
                # Prefer planar faces; among them choose the largest by area
                if (not best_is_planar) or (area > best_area):
                    best_is_planar = True
                    best_area = area
                    best = plane.Normal
            else:
                # Only use non-planar faces if we never find a planar face
                if (not best_is_planar) and (area > best_area):
                    best_area = area
                    try:
                        u = 0.5 * (f.Domain(0).T0 + f.Domain(0).T1)
                        v = 0.5 * (f.Domain(1).T0 + f.Domain(1).T1)
                        n = f.NormalAt(u, v)
                        best = n
                    except Exception:
                        pass

        if best is None:
            return None

        try:
            v = rg.Vector3d(best)
            if v.IsTiny():
                return None
            v.Unitize()
            return v
        except Exception:
            return None

    def _angle_deg_between_normals(self, n1, n2):
        """Angle between normals (0~90), in degrees, using absolute dot."""
        if n1 is None or n2 is None:
            return None
        try:
            a = rg.Vector3d(n1); b = rg.Vector3d(n2)
            if a.IsTiny() or b.IsTiny():
                return None
            a.Unitize(); b.Unitize()
            d = abs(rg.Vector3d.Multiply(a, b))
            # clamp
            if d < 0.0: d = 0.0
            if d > 1.0: d = 1.0
            return math.degrees(math.acos(d))
        except Exception:
            return None

    def compute_cutter_angles_hv(self):
        """Compute angles between Cutter's main cutting face and:
        - WorldXY (horizontal plane)
        - a best-fit vertical plane (whose normal is the projection of cutter normal onto XY).
        Returns [angle_to_horizontal_deg, angle_to_vertical_deg].
        """
        n = self._best_face_normal(self.cutter)
        if n is None:
            return [None, None]

        # Horizontal plane normal
        nz = rg.Vector3d(0, 0, 1)

        ang_h = self._angle_deg_between_normals(n, nz)

        # Vertical plane normal: projection of n onto XY
        vref = rg.Vector3d(n.X, n.Y, 0.0)
        if vref.IsTiny():
            vref = rg.Vector3d(1, 0, 0)  # arbitrary vertical plane normal if cutter is almost horizontal
        else:
            vref.Unitize()

        ang_v = self._angle_deg_between_normals(n, vref)

        return [ang_h, ang_v]

    # ----------------------------
    # basic helpers
    # ----------------------------
    @staticmethod
    def _tol_or_model(x):
        try:
            if x is None:
                return sc.doc.ModelAbsoluteTolerance
            x = float(x)
            if x <= 0:
                return sc.doc.ModelAbsoluteTolerance
            return x
        except:
            return sc.doc.ModelAbsoluteTolerance

    @staticmethod
    def _float_or_default(x, default):
        try:
            if x is None:
                return float(default)
            return float(x)
        except:
            return float(default)

    @staticmethod
    def _int_or_default(x, default):
        try:
            if x is None:
                return int(default)
            return int(x)
        except:
            return int(default)

    @staticmethod
    def _is_brep(x):
        return isinstance(x, rg.Brep)

    @staticmethod
    def _bbox_key(brep):
        bb = brep.GetBoundingBox(True)
        mn = bb.Min
        mx = bb.Max
        q = 1e-6
        return (round(mn.X/q)*q, round(mn.Y/q)*q, round(mn.Z/q)*q,
                round(mx.X/q)*q, round(mx.Y/q)*q, round(mx.Z/q)*q)

    @staticmethod
    def _pt_key(p, q=1e-6):
        return (round(p.X/q)*q, round(p.Y/q)*q, round(p.Z/q)*q)

    @staticmethod
    def _curve_key(curve):
        if curve is None:
            return (1e100,)*7
        try:
            l = curve.GetLength()
        except:
            l = 1e100

        a = curve.PointAtStart
        b = curve.PointAtEnd
        pa = (a.X, a.Y, a.Z)
        pb = (b.X, b.Y, b.Z)
        p0, p1 = (pa, pb) if pa <= pb else (pb, pa)

        q = 1e-6
        p0 = (round(p0[0]/q)*q, round(p0[1]/q)*q, round(p0[2]/q)*q)
        p1 = (round(p1[0]/q)*q, round(p1[1]/q)*q, round(p1[2]/q)*q)
        return (round(l/q)*q, p0[0], p0[1], p0[2], p1[0], p1[1], p1[2])

    @staticmethod
    def _segment_key(linecurve):
        if linecurve is None:
            return (1e100,)*8
        try:
            l = linecurve.GetLength()
        except:
            l = 1e100
        a = linecurve.PointAtStart
        b = linecurve.PointAtEnd
        pa = SplitSectionAnalyzer._pt_key(a)
        pb = SplitSectionAnalyzer._pt_key(b)
        p0, p1 = (pa, pb) if pa <= pb else (pb, pa)
        q = 1e-6
        return (round(l/q)*q, p0[0], p0[1], p0[2], p1[0], p1[1], p1[2])

    @staticmethod
    def _coerce_list(x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]

    # =========================================================
    # [FIX] DataTree/nested list helpers
    # =========================================================
    @staticmethod
    def _flatten(items):
        """递归展平 list/tuple（GH DataTree 常表现为嵌套 list）"""
        if items is None:
            return []
        if isinstance(items, (list, tuple)):
            out = []
            for it in items:
                out.extend(SplitSectionAnalyzer._flatten(it))
            return out
        return [items]

    @staticmethod
    def _filter_by_type(items, t):
        """只保留指定类型（例如 rg.Curve / rg.Point3d）；支持 GH Goo 自动解包"""
        out = []
        for it in items or []:
            if it is None:
                continue
            v = it
            # GH Goo: .Value
            try:
                if hasattr(v, "Value"):
                    v = v.Value
            except:
                pass
            # GH Goo: .ScriptVariable()
            try:
                if hasattr(v, "ScriptVariable"):
                    v2 = v.ScriptVariable()
                    if v2 is not None:
                        v = v2
            except:
                pass
            try:
                if isinstance(v, t):
                    out.append(v)
            except:
                pass
        return out

    # ----------------------------
    # geometry helpers
    # ----------------------------
    @staticmethod
    def _volume_of_brep(brep):
        """Return abs(volume) or None."""
        if brep is None:
            return None
        try:
            mp = rg.VolumeMassProperties.Compute(brep)
            if mp is None:
                return None
            v = mp.Volume
            if v is None:
                return None
            return abs(float(v))
        except:
            return None

    @classmethod
    def _cap_and_accept_by_volume(cls, brep, tol):
        """
        Try cap/join; accept as 'closed piece' if volume is computable and > eps.
        Return (brep_out_or_None, volume_or_None, note)
        """
        if brep is None:
            return None, None, "cap: input None"

        note_bits = []

        # 1) CapPlanarHoles
        try:
            capped = brep.CapPlanarHoles(tol)
            if capped is None:
                capped = brep
                note_bits.append("CapPlanarHoles failed->use original")
            else:
                note_bits.append("CapPlanarHoles ok")
        except Exception as e:
            capped = brep
            note_bits.append("CapPlanarHoles exception->use original: {}".format(e))

        # 2) JoinBreps (sometimes helps)
        try:
            joined = rg.Brep.JoinBreps([capped], tol)
            out = joined[0] if joined and len(joined) > 0 else capped
            note_bits.append("JoinBreps tried")
        except Exception as e:
            out = capped
            note_bits.append("JoinBreps exception: {}".format(e))

        # 3) Accept by volume (robust fallback when IsSolid is False)
        v = cls._volume_of_brep(out)
        eps = max(tol**3, 1e-12)  # scale-ish
        if v is not None and v > eps:
            solid_flag = False
            try:
                solid_flag = bool(out.IsSolid)
            except:
                solid_flag = False
            note_bits.append("accept_by_volume (IsSolid={})".format(solid_flag))
            return out, v, "; ".join(note_bits)

        note_bits.append("reject: no valid volume")
        return None, None, "; ".join(note_bits)

    @staticmethod
    def _try_get_polyline_points(curve):
        if curve is None:
            return None
        try:
            ok, pl = curve.TryGetPolyline()
            if ok:
                return list(pl)
        except:
            pass
        return None

    @staticmethod
    def _fallback_divide_points(curve, div_n):
        if curve is None:
            return None
        try:
            n = max(4, int(div_n))
            tparams = curve.DivideByCount(n, True)
            if not tparams or len(tparams) < 2:
                return [curve.PointAtStart, curve.PointAtEnd]
            return [curve.PointAt(t) for t in tparams]
        except:
            try:
                return [curve.PointAtStart, curve.PointAtEnd]
            except:
                return None

    @staticmethod
    def _poly_points_to_linecurves(pts, min_seg=0.0):
        if not pts or len(pts) < 2:
            return []
        out = []
        min_seg = float(min_seg) if min_seg is not None else 0.0
        for i in range(len(pts)-1):
            p0 = pts[i]
            p1 = pts[i+1]
            if p0.DistanceTo(p1) <= 1e-12:
                continue
            lc = rg.LineCurve(p0, p1)
            if min_seg > 0 and lc.GetLength() < min_seg:
                continue
            out.append(lc)
        return out

    @staticmethod
    def _dedupe_and_sort_curves(curves):
        """[FIX] 加类型保险：只处理 rg.Curve，避免 list/None 混入导致 _curve_key 崩溃"""
        uniq = {}
        for c in curves or []:
            if not isinstance(c, rg.Curve):
                continue
            k = SplitSectionAnalyzer._curve_key(c)
            if k not in uniq:
                uniq[k] = c
        out = list(uniq.values())
        out.sort(key=SplitSectionAnalyzer._curve_key)
        return out

    @staticmethod
    def _dedupe_and_sort_segments(segs):
        """[FIX] 加类型保险：只处理 rg.Curve（线段也是 Curve），避免脏数据"""
        uniq = {}
        for s in segs or []:
            if not isinstance(s, rg.Curve):
                continue
            k = SplitSectionAnalyzer._segment_key(s)
            if k not in uniq:
                uniq[k] = s
        out = list(uniq.values())
        out.sort(key=SplitSectionAnalyzer._segment_key)
        return out

    @staticmethod
    def _is_curve_planar_closed(curve, planar_tol):
        if curve is None:
            return False, None
        try:
            if not curve.IsClosed:
                return False, None
        except:
            return False, None
        try:
            ok, pln = curve.TryGetPlane(planar_tol)
            if ok:
                return True, pln
        except:
            pass

        pts = SplitSectionAnalyzer._try_get_polyline_points(curve)
        if pts and len(pts) >= 3:
            rc, pln = rg.Plane.FitPlaneToPoints(pts)
            if rc == rg.PlaneFitResult.Success:
                maxd = 0.0
                for p in pts:
                    maxd = max(maxd, abs(pln.DistanceTo(p)))
                if maxd <= planar_tol:
                    return True, pln
        return False, None

    @staticmethod
    def _build_planar_face_from_curve(curve, planar_tol):
        ok, _ = SplitSectionAnalyzer._is_curve_planar_closed(curve, planar_tol)
        if not ok:
            return None
        try:
            breps = rg.Brep.CreatePlanarBreps(curve, planar_tol)
            if breps and len(breps) > 0:
                return breps[0]
        except:
            pass
        return None

    @staticmethod
    def _stable_edges_from_faces(faces_breps):
        curves = []
        for fb in faces_breps or []:
            try:
                cs = fb.DuplicateEdgeCurves(True)
                if cs:
                    curves.extend(list(cs))
            except:
                pass
        return SplitSectionAnalyzer._dedupe_and_sort_curves(curves)

    @staticmethod
    def _linecurve_midpoint(lc):
        if lc is None:
            return None
        try:
            dom = lc.Domain
            t = 0.5 * (dom.T0 + dom.T1)
            return lc.PointAt(t)
        except:
            try:
                a = lc.PointAtStart
                b = lc.PointAtEnd
                return rg.Point3d(0.5*(a.X+b.X), 0.5*(a.Y+b.Y), 0.5*(a.Z+b.Z))
            except:
                return None

    # ----------------------------
    # pipeline steps
    # ----------------------------
    def step_split_cap_sort(self):
        pieces = []
        try:
            res = self.brep.Split(self.cutter, self.split_tol)
            if res:
                pieces = list(res)
        except Exception as e:
            self.log.append("Split exception: {}".format(e))
            pieces = []

        # Split 可能返回 None；兜底把原 Brep 当作 1 个 piece
        if not pieces:
            pieces = [self.brep]
            self.log.append("Split returned 0 pieces -> fallback to [Brep]")

        self.log.append("Split pieces count = {}".format(len(pieces)))

        closed_items = []
        for i, p in enumerate(pieces):
            out, v, note = self._cap_and_accept_by_volume(p, self.cap_tol)
            if out is not None and v is not None:
                closed_items.append((float(v), out))
                self.log.append("piece[{}] accept, vol={:.6g} | {}".format(i, v, note))
            else:
                self.log.append("piece[{}] reject | {}".format(i, note))

        closed_items.sort(key=lambda t: (-t[0], self._bbox_key(t[1])))
        self.sorted_volumes = [t[0] for t in closed_items]
        self.sorted_closed_breps = [t[1] for t in closed_items]
        self.max_closed_brep = self.sorted_closed_breps[0] if self.sorted_closed_breps else None

        if self.max_closed_brep:
            self.log.append("Max volume = {:.6g}".format(self.sorted_volumes[0]))
        else:
            self.log.append("MaxClosedBrep is None (no valid volume pieces).")

    def step_section_curves_by_brep_x_brep(self):
        """
        [FIX]
        ghc.BrepXBrep 可能返回嵌套 list（类似 DataTree 的分支结构）。
        原实现只 _coerce_list，会导致后续把 list 当作 curve 处理。
        这里：coerce -> flatten -> 过滤类型 -> dedupe/sort
        """
        try:
            crvs, pts = ghc.BrepXBrep(self.brep, self.cutter)
        except Exception as e:
            crvs, pts = [], []
            self.log.append("GH BrepXBrep exception: {}".format(e))

        # 记录原始形态
        crvs_raw = self._coerce_list(crvs)
        pts_raw = self._coerce_list(pts)
        self.log.append("GH BrepXBrep curves(raw top-level) = {}".format(len(crvs_raw)))
        self.log.append("GH BrepXBrep points(raw top-level) = {}".format(len(pts_raw)))

        # 展平
        crvs_flat = self._flatten(crvs_raw)
        pts_flat = self._flatten(pts_raw)
        self.log.append("GH BrepXBrep curves(flat) = {}".format(len(crvs_flat)))
        self.log.append("GH BrepXBrep points(flat) = {}".format(len(pts_flat)))

        # 类型过滤
        crvs_only = self._filter_by_type(crvs_flat, rg.Curve)
        pts_only = self._filter_by_type(pts_flat, rg.Point3d)

        self.log.append("GH BrepXBrep curves(Curve only) = {}".format(len(crvs_only)))
        self.log.append("GH BrepXBrep points(Point3d only) = {}".format(len(pts_only)))

        # dedupe + sort
        self.section_curves = self._dedupe_and_sort_curves(crvs_only)
        self.section_points = pts_only
        self.log.append("SectionCurves (dedup/sorted) = {}".format(len(self.section_curves)))

    def step_build_section_faces(self):
        self.log.append("Planar tol = {:.6g} (CapTol * PlanarTolFactor)".format(self.planar_tol))
        faces = []
        fail = 0
        for c in self.section_curves:
            fb = self._build_planar_face_from_curve(c, self.planar_tol)
            if fb:
                faces.append(fb)
            else:
                fail += 1
        self.section_faces = faces
        self.log.append("SectionFaces built = {}".format(len(self.section_faces)))
        self.log.append("SectionFaces failed curves = {}".format(fail))

    def step_edges_and_segments(self):
        if self.section_faces:
            self.stable_edge_curves = self._stable_edges_from_faces(self.section_faces)
            self.log.append("StableEdgeCurves from SectionFaces = {}".format(len(self.stable_edge_curves)))
        else:
            self.stable_edge_curves = self.section_curves
            self.log.append("StableEdgeCurves fallback to SectionCurves = {}".format(len(self.stable_edge_curves)))

        segs = []
        non_poly = 0
        for c in self.stable_edge_curves:
            pts_poly = self._try_get_polyline_points(c)
            if pts_poly is None:
                non_poly += 1
                pts_poly = self._fallback_divide_points(c, self.polyline_div_n)
            segs.extend(self._poly_points_to_linecurves(pts_poly, self.polyline_min_seg))

        self.log.append("Non-polyline edges (fallback divided) = {}".format(non_poly))
        self.stable_line_segments = self._dedupe_and_sort_segments(segs)
        self.log.append("StableLineSegments (dedup/sorted) = {}".format(len(self.stable_line_segments)))

    def step_midpoints_and_features(self):
        self.segment_midpoints = []
        for seg in self.stable_line_segments or []:
            mp = self._linecurve_midpoint(seg)
            if mp:
                self.segment_midpoints.append(mp)
        self.log.append("SegmentMidPoints = {}".format(len(self.segment_midpoints)))

        if not self.segment_midpoints:
            return

        mps = self.segment_midpoints

        self.lowest_midpoint = min(mps, key=lambda p: (p.Z, p.Y, p.X))
        self.highest_midpoint = max(mps, key=lambda p: (p.Z, p.Y, p.X))

        self.minx_midpoint = min(mps, key=lambda p: (p.X, p.Y, p.Z))
        self.maxx_midpoint = max(mps, key=lambda p: (p.X, p.Y, p.Z))

        self.miny_midpoint = min(mps, key=lambda p: (p.Y, p.X, p.Z))
        self.maxy_midpoint = max(mps, key=lambda p: (p.Y, p.X, p.Z))

        self.minz_midpoint = self.lowest_midpoint
        self.maxz_midpoint = self.highest_midpoint

        self.log.append("LowestMidPoint  = ({:.6g},{:.6g},{:.6g})".format(
            self.lowest_midpoint.X, self.lowest_midpoint.Y, self.lowest_midpoint.Z))
        self.log.append("HighestMidPoint = ({:.6g},{:.6g},{:.6g})".format(
            self.highest_midpoint.X, self.highest_midpoint.Y, self.highest_midpoint.Z))


    def step_plane_x_cutter(self):
        """
        用 ghpythonlib.components.BrepXPlane 求取 Cutter 与 PlaneRef 的交线（剖切线），并输出：
        - plane_cutter_curves : 交线 Curve 列表
        - plane_cutter_midpoint : 取最长交线的中点（Point3d）
        说明：BrepXPlane 可能返回 GH Goo 或嵌套 list，这里会做 flatten + 解包 + 类型过滤。
        """
        self.plane_cutter_curves = []
        self.plane_cutter_midpoint = None

        if not self._is_brep(self.cutter):
            try:
                self.log.append("[PlaneXCutter] Cutter is not a Brep.")
            except:
                pass
            return

        pl = getattr(self, "plane_ref", None)
        if pl is None:
            try:
                self.log.append("[PlaneXCutter] PlaneRef is None.")
            except:
                pass
            return

        # 尝试解包 GH Plane Goo
        try:
            if hasattr(pl, "Value"):
                pl = pl.Value
        except:
            pass
        try:
            if hasattr(pl, "ScriptVariable"):
                v2 = pl.ScriptVariable()
                if v2 is not None:
                    pl = v2
        except:
            pass

        # 允许 duck-typing：有 Origin/ZAxis 就构造一个 Plane
        try:
            if not isinstance(pl, rg.Plane) and hasattr(pl, "Origin") and hasattr(pl, "ZAxis"):
                # 用 ZAxis + XAxis（若无则用任意向量）构造
                xaxis = getattr(pl, "XAxis", rg.Vector3d(1, 0, 0))
                pl = rg.Plane(pl.Origin, xaxis, pl.ZAxis)
        except:
            pass

        if not isinstance(pl, rg.Plane) or (hasattr(pl, "IsValid") and (not pl.IsValid)):
            try:
                self.log.append("[PlaneXCutter] PlaneRef is not a valid rg.Plane.")
            except:
                pass
            return

        # ---- 核心：直接用 GH 组件 BrepXPlane ----
        try:
            crvs, pts = ghc.BrepXPlane(self.cutter, pl)
        except Exception as e:
            try:
                self.log.append("[PlaneXCutter] ghc.BrepXPlane exception: {}".format(e))
            except:
                pass
            return

        # 统一处理返回结构（可能是 DataTree/嵌套 list/Goo）
        crvs_flat = self._flatten(self._coerce_list(crvs))
        crvs_only = self._filter_by_type(crvs_flat, rg.Curve)

        self.plane_cutter_curves = crvs_only

        try:
            self.log.append("[PlaneXCutter] Curves count = {}".format(len(crvs_only)))
        except:
            pass

        if not crvs_only:
            try:
                self.log.append("[PlaneXCutter] Curves empty (Plane may not cut the cutter, or output is non-curve).")
            except:
                pass
            return

        # 取最长交线的中点作为代表点
        best = None
        best_len = -1.0
        for c in crvs_only:
            try:
                L = c.GetLength()
                if L > best_len:
                    best_len = L
                    best = c
            except:
                pass

        if best is None:
            try:
                self.log.append("[PlaneXCutter] Failed to pick a valid curve for midpoint.")
            except:
                pass
            return

        try:
            dom = best.Domain
            t = 0.5 * (dom.T0 + dom.T1)
            self.plane_cutter_midpoint = best.PointAt(t)
            try:
                self.log.append("[PlaneXCutter] MidPoint computed on longest curve, length={:.6g}".format(best_len))
            except:
                pass
        except Exception as e:
            self.plane_cutter_midpoint = None
            try:
                self.log.append("[PlaneXCutter] MidPoint compute exception: {}".format(e))
            except:
                pass

    def run(self):
        if not self._is_brep(self.brep):
            self.log.append("ERROR: Brep input is not a Rhino.Geometry.Brep")
            return self
        if not self._is_brep(self.cutter):
            self.log.append("ERROR: Cutter input is not a Rhino.Geometry.Brep")
            return self

        self.step_split_cap_sort()
        self.step_section_curves_by_brep_x_brep()
        self.step_build_section_faces()
        self.step_edges_and_segments()
        self.step_midpoints_and_features()
        self.step_plane_x_cutter()
        return self


def _bool_or_false(x):
    try:
        return bool(x)
    except:
        return False


if __name__ == "__main__":
    # ============================================================
    # GhPython main: Refresh + sticky cache
    # ============================================================
    _brep_in = globals().get("Brep", None)
    _cutter_in = globals().get("Cutter", None)

    _plane_ref = globals().get("PlaneRef", None)

    _refresh = _bool_or_false(globals().get("Refresh", False))

    _cap_tol = globals().get("CapTol", None)
    _split_tol = globals().get("SplitTol", None)

    _poly_div_n = globals().get("PolylineDivN", 64)
    _poly_min_seg = globals().get("PolylineMinSeg", 0.0)
    _planar_factor = globals().get("PlanarTolFactor", 50.0)

    # cache key: keep simple but stable in session
    # NOTE: bump cache key when script structure/outputs change.
    # This avoids reusing older cached analyzer objects that may miss new attributes.
    _cache_key = "SplitSectionAnalyzer::cache::v4"

    _use_cache = (not _refresh) and (_cache_key in sc.sticky)

    if _use_cache:
        _an = sc.sticky[_cache_key]
        # update runtime PlaneRef (may change between solutions)
        try:
            _an.plane_ref = _plane_ref
        except:
            pass
        # still append a log line for visibility
        try:
            _an.log.append("CACHE HIT (Refresh=False) -> reused previous result.")
        except:
            pass

        # Backward-compat: if an older cached object is reused for any reason,
        # ensure newly added attributes exist.
        if not hasattr(_an, "cutter_angles_hv"):
            try:
                _an.cutter_angles_hv = _an.compute_cutter_angles_hv()
                try:
                    _an.log.append("Compat: computed missing cutter_angles_hv on cached analyzer.")
                except:
                    pass
            except:
                _an.cutter_angles_hv = [None, None]
        # Compat: ensure plane x cutter outputs exist and up-to-date
        if not hasattr(_an, "plane_cutter_curves") or not hasattr(_an, "plane_cutter_midpoint"):
            try:
                _an.plane_cutter_curves = []
                _an.plane_cutter_midpoint = None
            except:
                pass
        try:
            _an.plane_ref = _plane_ref
            _an.step_plane_x_cutter()
        except:
            pass
    else:
        _an = SplitSectionAnalyzer(
            brep=_brep_in,
            cutter=_cutter_in,
            cap_tol=_cap_tol,
            split_tol=_split_tol,
            polyline_div_n=_poly_div_n,
            polyline_min_seg=_poly_min_seg,
            planar_tol_factor=_planar_factor,
            plane_ref=_plane_ref
        ).run()
        sc.sticky[_cache_key] = _an
        try:
            _an.log.append("CACHE UPDATE (Refresh=True or cache miss) -> recomputed.")
        except:
            pass

    # outputs
    SortedClosedBreps = _an.sorted_closed_breps
    SortedVolumes = _an.sorted_volumes
    MaxClosedBrep = _an.max_closed_brep

    SectionCurves = _an.section_curves
    SectionFaces = _an.section_faces
    StableEdgeCurves = _an.stable_edge_curves
    StableLineSegments = _an.stable_line_segments

    SegmentMidPoints = _an.segment_midpoints
    LowestMidPoint = _an.lowest_midpoint
    HighestMidPoint = _an.highest_midpoint

    MinXMidPoint = _an.minx_midpoint
    MaxXMidPoint = _an.maxx_midpoint
    MinYMidPoint = _an.miny_midpoint
    MaxYMidPoint = _an.maxy_midpoint
    MinZMidPoint = _an.minz_midpoint
    MaxZMidPoint = _an.maxz_midpoint

    CutterAnglesHV = _an.cutter_angles_hv

    PlaneCutterCurves = _an.plane_cutter_curves
    PlaneCutterMidPoint = _an.plane_cutter_midpoint

    Log = _an.log

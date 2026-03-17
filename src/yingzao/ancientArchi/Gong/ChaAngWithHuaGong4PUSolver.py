# -*- coding: utf-8 -*-
"""
ChaAngWithHuaGong4PU_Step1_3 · Step1-3（DBJsonReader + ChaAng + HuaGongWithChaAng + GeoAligner::1 + Step3切割&華頭子）

输入（仅 3 个）：
    DBPath     : str
    base_point : Point3d（若 None → 原点）
    Refresh    : bool（True 强制重读 DB）

输出（固定 3 个）：
    CutTimbers    # Step3 最终切割后的木料
    FailTimbers
    Log

开发模式输出（显式绑定，参考 LingGongSolver.py 风格）：
    Value_1 / All_1 / AllDict_1 / DBLog_1
    ChaAng_* / HuaGong_* / GA_*
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import Grasshopper.Kernel.Types as ght
import ghpythonlib.components as ghc

from yingzao.ancientArchi import (
    DBJsonReader,
    ChaAng4PUSolver,
    HuaGong_MatchedChaAng_4PU,
    flatten_tree,
    GeoAligner_xfm,

    SplitSectionAnalyzer,
    RightTrianglePrismBuilder,
    HuaTouZi,
    FT_CutTimbersByTools_GH_SolidDifference,
)


# ============================================================
# GH Reference Plane helpers
#   Grasshopper built-in planes:
#     "XY Plane": X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
#     "XZ Plane": X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
#     "YZ Plane": X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
# NOTE:
#   Rhino.Geometry.Plane provides WorldXY/WorldYZ/WorldZX constants,
#   but it does NOT provide WorldXZ. GH's "XZ Plane" must be built
#   explicitly with XAxis=WorldX and YAxis=WorldZ.
# ============================================================
def coerce_gh_ref_plane(ref_plane, base_point=None, default_tag="XZ Plane"):
    import Rhino.Geometry as rg

    # If already a Plane, return as-is (optionally re-origin)
    if isinstance(ref_plane, rg.Plane):
        if base_point is None:
            return ref_plane
        p = rg.Plane(ref_plane)
        p.Origin = base_point
        return p

    # Normalize tag
    tag = ref_plane if isinstance(ref_plane, (str, bytes)) else default_tag
    if isinstance(tag, bytes):
        tag = tag.decode("utf-8", "ignore")
    tag = (tag or default_tag).strip()

    # Aliases
    tag_u = tag.upper().replace("WORLD", "").replace("PLANE", "").replace(" ", "")
    # e.g. "XZ", "XY", "YZ", or legacy "WORLDXZ" -> "XZ"
    if tag_u in ("XY", "WORLDXY"):
        pl = rg.Plane.WorldXY
    elif tag_u in ("YZ", "WORLDYZ"):
        pl = rg.Plane.WorldYZ
    elif tag_u in ("ZX", "WORLDZX"):
        # Rhino constant exists; GH rarely uses this tag directly
        pl = rg.Plane.WorldZX
    elif tag_u in ("XZ", "WORLDXZ"):
        # GH XZ Plane: X=WorldX, Y=WorldZ, Z=WorldX x WorldZ = -WorldY
        pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)
    else:
        # fallback to GH XZ
        pl = rg.Plane(rg.Point3d.Origin, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)

    if base_point is not None:
        pl.Origin = base_point
    return pl




# ==============================================================
# 通用工具函数（与 LingGongSolver 的风格一致：明确、可控）
# ==============================================================

def to_list(x):
    """若为 list/tuple 则直接返回 list；标量则包装成 [x]；None -> []"""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def all_to_dict(all_list):
    d = {}
    if all_list is None:
        return d
    for item in all_list:
        if isinstance(item, tuple) and len(item) == 2:
            k, v = item
            d[k] = v
    return d


def first_or_default(v, default=None):
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        return v[0] if len(v) else default
    return v


def _coerce_point3d(p, default=None):
    if default is None:
        default = rg.Point3d(0, 0, 0)
    if p is None:
        return default
    if isinstance(p, rg.Point3d):
        return p
    if isinstance(p, rg.Point):
        return p.Location
    if isinstance(p, (list, tuple)) and len(p) >= 3:
        try:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        except:
            return default
    return default


def _safe_int(x, default=0):
    try:
        return int(first_or_default(x, default))
    except:
        return default


def _safe_float(x, default=0.0):
    try:
        return float(first_or_default(x, default))
    except:
        return default


def _gh_count(x):
    """统一计数：None->0；list/tuple->len；标量(Brep等)->1（解决 len(Brep) 报错）"""
    if x is None:
        return 0
    if isinstance(x, (list, tuple)):
        return len(x)
    return 1


def _pick_by_index(seq, idx, default=None):
    """seq 可为标量或列表：标量直接返回；列表按 idx（越界夹逼）"""
    if seq is None:
        return default
    if not isinstance(seq, (list, tuple)):
        return seq
    if len(seq) == 0:
        return default
    if idx < 0:
        idx = 0
    if idx >= len(seq):
        idx = len(seq) - 1
    return seq[idx]


def _coerce_plane(p, default=None):
    if default is None:
        default = coerce_gh_ref_plane('XZ Plane')
    if p is None:
        return default
    if isinstance(p, rg.Plane):
        return p
    # allow GH wrappers
    try:
        if hasattr(p, "Value") and isinstance(p.Value, rg.Plane):
            return p.Value
    except:
        pass
    return default


def _plane_with_origin(pl, origin_pt):
    pl = _coerce_plane(pl, None)
    if pl is None:
        return None
    try:
        return rg.Plane(origin_pt, pl.XAxis, pl.YAxis)
    except:
        try:
            p2 = rg.Plane(pl)
            p2.Origin = origin_pt
            return p2
        except:
            return None


def _gh_transform_value(x):
    # GH_Transform / Transform / xform wrapper
    if x is None:
        return None
    try:
        if isinstance(x, ght.GH_Transform):
            return x.Value
    except:
        pass
    try:
        if hasattr(x, "Value"):
            return x.Value
    except:
        pass
    return x


def _geom_signature(geo):
    """Lightweight geometry signature used to auto-invalidate sticky cache.

    Purpose: avoid stale SplitSectionAnalyzer results when Refresh=False but inputs changed.
    Strategy: bbox (rounded) + basic Brep counts. Cheap and stable enough for GH sessions.
    """
    try:
        if geo is None:
            return "None"

        # lists/tuples: aggregate first few to keep string short
        if isinstance(geo, (list, tuple)):
            parts = []
            for g in geo[:5]:
                parts.append(_geom_signature(g))
            return "L[{}]::{}".format(len(geo), ";".join(parts))

        # GH wrapper
        if hasattr(geo, "Value"):
            try:
                return _geom_signature(geo.Value)
            except:
                pass

        bb_s = "noBB"
        try:
            bb = geo.GetBoundingBox(True)
            mn, mx = bb.Min, bb.Max
            bb_s = "{:.3f},{:.3f},{:.3f}|{:.3f},{:.3f},{:.3f}".format(
                mn.X, mn.Y, mn.Z, mx.X, mx.Y, mx.Z
            )
        except:
            pass

        vcnt = fcnt = ecnt = "?"
        try:
            if isinstance(geo, rg.Brep):
                vcnt = geo.Vertices.Count
                fcnt = geo.Faces.Count
                ecnt = geo.Edges.Count
        except:
            pass

        return "{}::bb({})::v{}f{}e{}".format(type(geo).__name__, bb_s, vcnt, fcnt, ecnt)
    except:
        return "sigErr"


# ==============================================================
# 主 Solver 类 —— ChaAngWithHuaGong4PU（仅 Step1-2）
# ==============================================================

class ChaAngWithHuaGong4PUSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = _coerce_point3d(base_point, rg.Point3d(0, 0, 0))
        self.Refresh = bool(Refresh) if Refresh is not None else False
        self.ghenv = ghenv

        # 最终输出
        self.CutTimbers = []
        self.FailTimbers = []
        self.Log = []

        # Step1：DB
        self.Value_1 = None
        self.All_1 = None
        self.AllDict_1 = {}
        self.DBLog_1 = []

        # Step2：ChaAng
        self.solver_chaang = None
        self.ChaAng_CutTimbers = None
        self.ChaAng_FailTimbers = None
        self.ChaAng_Log = None
        self.ChaAng_RefPlanes = None

        # Step2：HuaGong
        self.solver_huagong = None
        self.HuaGong_CutTimbers = None
        self.HuaGong_FailTimbers = None
        self.HuaGong_Log = None
        self.HuaGong_FacePlaneList = None

        # Step2：GeoAligner::1
        self.GA_SourceOut = None
        self.GA_TargetOut = None
        self.GA_TransformOut = None
        self.GA_MovedGeo = None

        # Step3：SplitSectionAnalyzer
        self.solver_split = None
        self.SSA_SortedClosedBreps = None
        self.SSA_SortedVolumes = None
        self.SSA_MaxClosedBrep = None
        self.SSA_SectionCurves = None
        self.SSA_SectionFaces = None
        self.SSA_StableEdgeCurves = None
        self.SSA_StableLineSegments = None
        self.SSA_SegmentMidPoints = None
        self.SSA_LowestMidPoint = None
        self.SSA_HighestMidPoint = None
        self.SSA_MinXMidPoint = None
        self.SSA_MaxXMidPoint = None
        self.SSA_MinYMidPoint = None
        self.SSA_MaxYMidPoint = None
        self.SSA_MinZMidPoint = None
        self.SSA_MaxZMidPoint = None
        self.SSA_CutterAnglesHV = None
        self.SSA_Log = None

        # Step3：FindingAnglesInARightTriangle（RightTrianglePrismBuilder）
        self.RTP_dist = None
        self.RTP_SectionCurve = None
        self.RTP_SectionPts = None
        self.RTP_BrepSolid = None
        self.RTP_BrepParts = None
        self.RTP_OPlanes = None
        self.RTP_Log = None

        # Step3：HuaTouZi
        self.HTZ_SolidBrep = None
        self.HTZ_SectionCrv = None
        self.HTZ_SectionCrv_Pos = None
        self.HTZ_SectionCrv_Neg = None
        self.HTZ_LoftBrep = None
        self.HTZ_CapPosBrep = None
        self.HTZ_CapNegBrep = None
        self.HTZ_Pts = None
        self.HTZ_Arc1 = None
        self.HTZ_Arc2 = None
        self.HTZ_PlaneAtB = None
        self.HTZ_PlaneAtB_X = None
        self.HTZ_PlaneAtB_Y = None
        self.HTZ_Log = None

        # Step3：GeoAligner::2
        self.GA2_SourceOut = None
        self.GA2_TargetOut = None
        self.GA2_TransformOut = None
        self.GA2_MovedGeo = None
        self.GA2_TargetPlane_in = None
        self.GA2_SourcePlane_in = None

        # Step3：GeoAligner::3
        self.GA3_SourceOut = None
        self.GA3_TargetOut = None
        self.GA3_TransformOut = None
        self.GA3_MovedGeo = None
        self.GA3_MoveX = None

        # Step3：CutTimbersByTools_V3（两次切割）
        self.CutV3_1_CutTimbers = None
        self.CutV3_1_FailTimbers = None
        self.CutV3_1_Log = None
        self.CutV3_2_CutTimbers = None
        self.CutV3_2_FailTimbers = None
        self.CutV3_2_Log = None
        # CutTimbersByTools_V3::3（HuaGongWithChaAng 的 AlignToolToTimber_4_MovedGeo_tree 作为 Tools）
        self.CutV3_3_CutTimbers = None
        self.CutV3_3_FailTimbers = None
        self.CutV3_3_Log = None
        self.CutV3_3_Tools_in = None
        self.CutV3_3_Timbers_in = None
        # GeoAligner 输入快照（方便调试）
        self.GA_Geo_in = None
        self.GA_SourcePlane_in = None
        self.GA_TargetPlane_in = None
        self.GA_src_idx = None
        self.GA_tgt_idx = None
        self.GA_rotate_deg = None
        self.GA_flip_x = None

    def all_get(self, key, default=None):
        if not self.AllDict_1:
            return default

        if key not in self.AllDict_1:
            return default

        v = self.AllDict_1[key]
        # 与 LingGongSolver 一致：长度为1的列表/元组解包
        if isinstance(v, (list, tuple)) and len(v) == 1:
            return v[0]
        return v

    # ----------------------------
    # Step1：读取数据库（带 sticky 缓存）
    # ----------------------------
    def step1_read_db(self):
        table = "DG_Dou"
        key_field = "type_code"
        key_value = "ChaAngWithHuaGong4PU"
        field = "params_json"
        json_path = None
        export_all = True

        cache_key = "YZL_DB_ALL::{}::{}::{}::{}".format(self.DBPath, table, key_field, key_value)

        if (not self.Refresh) and (cache_key in sc.sticky):
            cached = sc.sticky.get(cache_key, None)
            if isinstance(cached, dict):
                self.Value_1 = cached.get("Value")
                self.All_1 = cached.get("All")
                self.AllDict_1 = cached.get("AllDict", {})
                self.DBLog_1 = cached.get("DBLog", [])
                self.Log.append("[DB] 使用缓存 All（Refresh=False）")
                return self

        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table=table,
                key_field=key_field,
                key_value=key_value,
                field=field,
                json_path=json_path,
                export_all=export_all,
                ghenv=self.ghenv
            )

            self.Value_1, self.All_1, self.DBLog_1 = reader.run()
            self.AllDict_1 = all_to_dict(self.All_1)

            self.Log.append("[DB] 数据库读取完成")
            for l in (self.DBLog_1 or []):
                self.Log.append("[DB] " + str(l))
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict_1)))

            sc.sticky[cache_key] = {
                "Value": self.Value_1,
                "All": self.All_1,
                "AllDict": self.AllDict_1,
                "DBLog": self.DBLog_1
            }

        except Exception as e:
            self.Value_1 = None
            self.All_1 = None
            self.AllDict_1 = {}
            self.DBLog_1 = ["错误: {}".format(e)]
            self.Log.append("[ERROR][DB] step1_read_db 出错: {}".format(e))

        return self

    # ----------------------------
    # Step2：ChaAng / HuaGong / GeoAligner::1
    # ----------------------------
    def step2_chain(self):

        if not self.All_1:
            self.Log.append("[STEP2] All 为空，跳过 Step2。")
            return self

        # ---- 2.1 ChaAng ----
        try:
            self.solver_chaang = ChaAng4PUSolver(self.DBPath, self.base_point, self.Refresh)
            self.solver_chaang.run()

            self.ChaAng_CutTimbers = getattr(self.solver_chaang, "CutTimbers", None)
            self.ChaAng_FailTimbers = getattr(self.solver_chaang, "FailTimbers", None)
            self.ChaAng_Log = getattr(self.solver_chaang, "Log", None)
            self.ChaAng_RefPlanes = getattr(self.solver_chaang, "RefPlanes", None)

            self.Log.append("[ChaAng] 完成：Cut={}, Fail={}".format(
                _gh_count(self.ChaAng_CutTimbers),
                _gh_count(self.ChaAng_FailTimbers)
            ))

        except Exception as e:
            self.ChaAng_CutTimbers = None
            self.ChaAng_FailTimbers = None
            self.ChaAng_Log = ["错误: {}".format(e)]
            self.ChaAng_RefPlanes = None
            self.Log.append("[ERROR][ChaAng] ChaAng4PUSolver 出错: {}".format(e))

        # ---- 2.2 HuaGongWithChaAng ----
        try:
            self.solver_huagong = HuaGong_MatchedChaAng_4PU(self.DBPath, self.base_point, self.Refresh,
                                                            self.ghenv).run()

            self.HuaGong_CutTimbers = getattr(self.solver_huagong, "CutTimbers", None)
            self.HuaGong_FailTimbers = getattr(self.solver_huagong, "FailTimbers", None)
            self.HuaGong_Log = getattr(self.solver_huagong, "Log", None)
            self.HuaGong_FacePlaneList = getattr(self.solver_huagong, "FacePlaneList", None)

            self.Log.append("[HuaGong] 完成：FacePlaneList={}".format(_gh_count(self.HuaGong_FacePlaneList)))

        except Exception as e:
            self.HuaGong_CutTimbers = None
            self.HuaGong_FailTimbers = None
            self.HuaGong_Log = ["错误: {}".format(e)]
            self.HuaGong_FacePlaneList = None
            self.Log.append("[ERROR][HuaGong] HuaGong_MatchedChaAng_4PU 出错: {}".format(e))

        # ---- 2.3 GeoAligner::1 ----
        try:
            geo_in = self.ChaAng_CutTimbers
            ref_planes = self.ChaAng_RefPlanes
            face_planes = self.HuaGong_FacePlaneList

            self.GA_Geo_in = geo_in

            # Geo：标量 Brep 也应视为有效
            geo_list = [g for g in to_list(geo_in) if g is not None]
            if len(geo_list) == 0:
                self.Log.append("[GA] Geo 为空（ChaAng_CutTimbers=None/[]），跳过 GeoAligner。")
                self.GA_MovedGeo = None
                return self

            # DB 参数（来自 AllDict）
            src_idx = _safe_int(self.all_get("GeoAligner_1__SourcePlane", 0), 0)
            tgt_idx = _safe_int(self.all_get("GeoAligner_1__TargetPlane", 0), 0)
            rotate_deg = _safe_float(self.all_get("GeoAligner_1__RotateDeg", 0.0), 0.0)
            flip_x = _safe_int(self.all_get("GeoAligner_1__FlipX", 0), 0)

            self.GA_src_idx = src_idx
            self.GA_tgt_idx = tgt_idx
            self.GA_rotate_deg = rotate_deg
            self.GA_flip_x = flip_x

            src_plane = _pick_by_index(ref_planes, src_idx, None)
            tgt_plane = _pick_by_index(face_planes, tgt_idx, None)

            self.GA_SourcePlane_in = src_plane
            self.GA_TargetPlane_in = tgt_plane

            if src_plane is None or tgt_plane is None:
                self.Log.append("[GA] SourcePlane/TargetPlane 为空，跳过 GeoAligner。")
                self.GA_MovedGeo = None
                return self

            # 其余参数默认（与组件版一致）
            flip_y = 0
            flip_z = 0
            move_x = 0.0
            move_y = 0.0
            move_z = 0.0

            # 若只有一个几何，传标量；多个则传 list（尊重原库函数可能的两种输入）
            geo_arg = geo_list[0] if len(geo_list) == 1 else geo_list

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo_arg,
                src_plane,
                tgt_plane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            self.GA_SourceOut = SourceOut
            self.GA_TargetOut = TargetOut
            self.GA_TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            self.GA_MovedGeo = MovedGeo

            self.Log.append("[GA] 完成：src_idx={} tgt_idx={} rot={} flipx={} | Geo={}".format(
                src_idx, tgt_idx, rotate_deg, flip_x, _gh_count(geo_in)
            ))

        except Exception as e:
            self.GA_SourceOut = None
            self.GA_TargetOut = None
            self.GA_TransformOut = None
            self.GA_MovedGeo = None
            self.Log.append("[ERROR][GA] GeoAligner_xfm.align 出错: {}".format(e))

        return self

    # ----------------------------
    # Step3：切割与“華頭子”相关链
    #   SplitSectionAnalyzer -> RightTrianglePrismBuilder -> HuaTouZi
    #   -> GeoAligner::2 / GeoAligner::3 -> CutTimbersByTools_V3（两次）
    # ----------------------------
    def step3_cut_and_huatouzi(self):
        # 3.1 SplitSectionAnalyzer
        try:
            if self.HuaGong_CutTimbers is None:
                self.Log.append("[STEP3] HuaGong_CutTimbers 为空，跳过 Step3。")
                return self

            brep_in = self.HuaGong_CutTimbers

            # Cutter = Transform( ChaAng.SolidFace_AE, GA1.TransformOut )
            cutter_geo = self.all_get("ChaAng__SolidFace_AE", None)
            if cutter_geo is None and self.solver_chaang is not None:
                cutter_geo = getattr(self.solver_chaang, "SolidFace_AE", None)

            xfm = _gh_transform_value(self.GA_TransformOut)
            if cutter_geo is None or xfm is None:
                self.Log.append("[STEP3][SSA] cutter_geo 或 GA_TransformOut 为空。")
                cutter_in = None
            else:
                # 使用 ghc.Transform 保持与 GH 一致；失败则 RhinoCommon 复制+Transform
                try:
                    cutter_in = ghc.Transform(cutter_geo, xfm)
                except:
                    try:
                        dup = cutter_geo.Duplicate() if hasattr(cutter_geo, "Duplicate") else cutter_geo.DuplicateBrep()
                        dup.Transform(xfm)
                        cutter_in = dup
                    except:
                        cutter_in = cutter_geo

            _cap_tol = self.all_get("SplitSectionAnalyzer__CapTol", 0.001)
            _split_tol = self.all_get("SplitSectionAnalyzer__SplitTol", 0.001)
            _poly_div_n = _safe_int(self.all_get("SplitSectionAnalyzer__PolylineDivN", 64), 64)
            _poly_min_seg = _safe_float(self.all_get("SplitSectionAnalyzer__PolylineMinSeg", 0.0), 0.0)
            _planar_factor = _safe_float(self.all_get("SplitSectionAnalyzer__PlanarTolFactor", 50.0), 50.0)

            # SplitSectionAnalyzer（Solver 版：移除 sticky cache，避免几何链变动导致输出为空）
            try:
                an = SplitSectionAnalyzer(
                    brep=brep_in[0],
                    cutter=cutter_in,
                    cap_tol=_cap_tol,
                    split_tol=_split_tol,
                    polyline_div_n=_poly_div_n,
                    polyline_min_seg=_poly_min_seg,
                    planar_tol_factor=_planar_factor
                ).run()
            except Exception as e:
                class _SSAEmpty(object):
                    pass

                an = _SSAEmpty()
                an.sorted_closed_breps = None
                an.sorted_volumes = None
                an.max_closed_brep = None
                an.section_curves = None
                an.section_faces = None
                an.stable_edge_curves = None
                an.stable_line_segments = None
                an.segment_midpoints = None
                an.lowest_midpoint = None
                an.highest_midpoint = None
                an.minx_midpoint = None
                an.maxx_midpoint = None
                an.miny_midpoint = None
                an.maxy_midpoint = None
                an.minz_midpoint = None
                an.maxz_midpoint = None
                an.cutter_angles_hv = [None, None]
                an.log = ["[ERROR] SplitSectionAnalyzer exception: {}".format(e)]
                self.Log.append("[STEP3][SSA] SplitSectionAnalyzer 出错: {}".format(e))
            self.solver_split = an
            self.SSA_SortedClosedBreps = getattr(an, "sorted_closed_breps", None)
            self.SSA_SortedVolumes = getattr(an, "sorted_volumes", None)
            self.SSA_MaxClosedBrep = getattr(an, "max_closed_brep", None)

            self.SSA_SectionCurves = getattr(an, "section_curves", None)
            self.SSA_SectionFaces = getattr(an, "section_faces", None)
            self.SSA_StableEdgeCurves = getattr(an, "stable_edge_curves", None)
            self.SSA_StableLineSegments = getattr(an, "stable_line_segments", None)

            self.SSA_SegmentMidPoints = getattr(an, "segment_midpoints", None)
            self.SSA_LowestMidPoint = getattr(an, "lowest_midpoint", None)
            self.SSA_HighestMidPoint = getattr(an, "highest_midpoint", None)

            self.SSA_MinXMidPoint = getattr(an, "minx_midpoint", None)
            self.SSA_MaxXMidPoint = getattr(an, "maxx_midpoint", None)
            self.SSA_MinYMidPoint = getattr(an, "miny_midpoint", None)
            self.SSA_MaxYMidPoint = getattr(an, "maxy_midpoint", None)
            self.SSA_MinZMidPoint = getattr(an, "minz_midpoint", None)
            self.SSA_MaxZMidPoint = getattr(an, "maxz_midpoint", None)

            self.SSA_CutterAnglesHV = getattr(an, "cutter_angles_hv", None)
            self.SSA_Log = getattr(an, "log", None)

            self.Log.append("[SSA] 完成：MaxClosedBrep={}, CutterAnglesHV={}".format(
                "OK" if self.SSA_MaxClosedBrep is not None else "None",
                self.SSA_CutterAnglesHV
            ))

        except Exception as e:
            self.Log.append("[ERROR][SSA] SplitSectionAnalyzer 出错: {}".format(e))
            return self

        # 3.2 FindingAnglesInARightTriangle（RightTrianglePrismBuilder）
        try:
            if self.SSA_CutterAnglesHV is None:
                self.Log.append("[RTP] CutterAnglesHV 为空，跳过 RightTrianglePrismBuilder。")
                return self

            theta_list = to_list(self.SSA_CutterAnglesHV)
            theta_idx = _safe_int(self.all_get("FindingAnglesInARightTriangle__theta", 0), 0)
            theta = _pick_by_index(theta_list, theta_idx, None)

            offset = _safe_float(self.all_get("FindingAnglesInARightTriangle__offset", 0.0), 0.0)
            h = _safe_float(self.all_get("FindingAnglesInARightTriangle__h", 0.0), 0.0)

            base_pt = self.base_point if self.base_point is not None else rg.Point3d.Origin
            ref_plane = coerce_gh_ref_plane('XZ Plane', base_pt)

            builder = RightTrianglePrismBuilder(
                theta_deg=theta,
                h=h,
                base_point=base_pt,
                ref_plane=ref_plane,
                offset=offset,
                tol=(sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6),
                default_plane_tag="XZ Plane"
            )

            out = builder.run()
            self.RTP_dist = out.get("dist", None)
            self.RTP_SectionCurve = out.get("SectionCurve", None)
            self.RTP_SectionPts = out.get("SectionPts", None)
            self.RTP_BrepSolid = out.get("BrepSolid", None)
            self.RTP_BrepParts = out.get("BrepParts", None)
            self.RTP_OPlanes = out.get("OPlanes", None)
            self.RTP_Log = out.get("Log", None)

            self.Log.append("[RTP] 完成：theta_idx={} theta={} dist={}".format(theta_idx, theta, self.RTP_dist))

        except Exception as e:
            self.Log.append("[ERROR][RTP] RightTrianglePrismBuilder 出错: {}".format(e))
            return self

        # 3.3 HuaTouZi
        try:
            base_pt = self.base_point if self.base_point is not None else rg.Point3d.Origin
            ref_plane_mode = self.all_get("HuaTouZi__ref_plane_mode", "XZ Plane")

            AB = _safe_float(self.all_get("HuaTouZi__AB", 10.0), 10.0)
            BC = _safe_float(self.all_get("HuaTouZi__BC", 4.0), 4.0)
            DE = _safe_float(self.all_get("HuaTouZi__DE", 0.5), 0.5)
            # HF 在旧版面板/草图中可能存在，但当前 HuaTouZi.set_params() 并不接收该参数。
            # 为保持兼容，这里读取到也直接忽略（不参与运算，也不传入 set_params）。
            _ = self.all_get("HuaTouZi__HF", None)
            IG = _safe_float(self.all_get("HuaTouZi__IG", 1.5), 1.5)
            Offset = _safe_float(self.all_get("HuaTouZi__Offset", 5.0), 5.0)
            Tol = _safe_float(self.all_get("HuaTouZi__Tol", sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6),
                              sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6)

            ht = HuaTouZi(base_point=base_pt, ref_plane_mode=ref_plane_mode, tol=Tol)
            ht.set_params(AB=AB, BC=BC, DE=DE, IG=IG, Offset=Offset, Tol=Tol)
            ht.build(reset=True)

            self.HTZ_SolidBrep = getattr(ht, "solid_brep", None)
            self.HTZ_SectionCrv = getattr(ht, "section_crv", None)
            self.HTZ_SectionCrv_Pos = getattr(ht, "section_crv_pos", None)
            self.HTZ_SectionCrv_Neg = getattr(ht, "section_crv_neg", None)
            self.HTZ_LoftBrep = getattr(ht, "loft_brep", None)
            self.HTZ_CapPosBrep = getattr(ht, "cap_pos_brep", None)
            self.HTZ_CapNegBrep = getattr(ht, "cap_neg_brep", None)

            self.HTZ_Pts = {
                "A": getattr(ht, "A", None),
                "B": getattr(ht, "B", None),
                "C": getattr(ht, "C", None),
                "H": getattr(ht, "H", None),
                "D": getattr(ht, "D", None),
                "I": getattr(ht, "I", None),
                "F": getattr(ht, "F", None),
                "E": getattr(ht, "E", None),
                "G": getattr(ht, "G", None),
            }

            self.HTZ_Arc1 = getattr(ht, "arc1", None)
            self.HTZ_Arc2 = getattr(ht, "arc2", None)
            self.HTZ_PlaneAtB = getattr(ht, "plane_at_b", None)
            self.HTZ_PlaneAtB_X = getattr(ht, "plane_at_b_x", None)
            self.HTZ_PlaneAtB_Y = getattr(ht, "plane_at_b_y", None)
            self.HTZ_Log = getattr(ht, "log", None)

            self.Log.append("[HTZ] 完成：SolidBrep={}".format("OK" if self.HTZ_SolidBrep is not None else "None"))

        except Exception as e:
            self.Log.append("[ERROR][HTZ] HuaTouZi 出错: {}".format(e))
            return self

        # 3.4 GeoAligner::2 目标平面：PlaneOrigin( Transform(ChaAng.RefPlanes[idx], GA1.TransformOut), MaxXMidPoint )
        try:
            geo = self.RTP_BrepSolid
            if geo is None:
                self.Log.append("[GA2] RTP_BrepSolid 为空，跳过 GeoAligner::2。")
                return self

            src_idx = _safe_int(self.all_get("GeoAligner_2__SourcePlane", 0), 0)
            src_plane = _pick_by_index(self.RTP_OPlanes, src_idx, None)
            self.GA2_SourcePlane_in = src_plane

            # Transform 基准平面：ChaAng.RefPlanes[GeoAligner_1__SourcePlane]
            ref_idx = _safe_int(self.all_get("GeoAligner_1__SourcePlane", 0), 0)
            base_pl = _pick_by_index(self.ChaAng_RefPlanes, ref_idx, None)
            base_pl = _coerce_plane(base_pl, None)

            xfm = _gh_transform_value(self.GA_TransformOut)

            if base_pl is None or xfm is None:
                target_pl = None
            else:
                try:
                    # GH 的 Plane 是 value type，不建议直接变换原对象
                    p2 = rg.Plane(base_pl)
                    p2.Transform(xfm)
                    target_pl = p2
                except:
                    try:
                        target_pl = ghc.Transform(base_pl, xfm)
                    except:
                        target_pl = base_pl

            # PlaneOrigin：Base=target_pl, Origin=MaxXMidPoint
            if target_pl is not None and self.SSA_MaxXMidPoint is not None:
                target_pl = _plane_with_origin(target_pl, self.SSA_MaxXMidPoint)

            self.GA2_TargetPlane_in = target_pl

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                src_plane,
                target_pl,
                rotate_deg=_safe_float(self.all_get("GeoAligner_2__RotateDeg", 0.0), 0.0),
                flip_x=_safe_int(self.all_get("GeoAligner_2__FlipX", 0), 0),
                flip_y=_safe_int(self.all_get("GeoAligner_2__FlipY", 0), 0),
                flip_z=_safe_int(self.all_get("GeoAligner_2__FlipZ", 0), 0),
                move_x=_safe_float(self.all_get("GeoAligner_2__MoveX", 0.0), 0.0),
                move_y=_safe_float(self.all_get("GeoAligner_2__MoveY", 0.0), 0.0),
                move_z=_safe_float(self.all_get("GeoAligner_2__MoveZ", 0.0), 0.0),
            )

            self.GA2_SourceOut = SourceOut
            self.GA2_TargetOut = TargetOut
            self.GA2_TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            self.GA2_MovedGeo = MovedGeo

            self.Log.append(
                "[GA2] 完成：src_idx={} target_plane={}".format(src_idx, "OK" if target_pl is not None else "None"))

        except Exception as e:
            self.Log.append("[ERROR][GA2] GeoAligner::2 出错: {}".format(e))
            return self

        # 3.5 GeoAligner::3（MoveX = -dist）
        try:
            geo = self.HTZ_SolidBrep
            if geo is None:
                self.Log.append("[GA3] HTZ_SolidBrep 为空，跳过 GeoAligner::3。")
                return self

            src_plane = self.HTZ_PlaneAtB_X
            tgt_plane = self.GA2_TargetPlane_in
            move_x = -(float(self.RTP_dist) if self.RTP_dist is not None else 0.0)
            self.GA3_MoveX = move_x

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                src_plane,
                tgt_plane,
                rotate_deg=_safe_float(self.all_get("GeoAligner_3__RotateDeg", 0.0), 0.0),
                flip_x=_safe_int(self.all_get("GeoAligner_3__FlipX", 0), 0),
                flip_y=_safe_int(self.all_get("GeoAligner_3__FlipY", 0), 0),
                flip_z=_safe_int(self.all_get("GeoAligner_3__FlipZ", 0), 0),
                move_x=move_x,
                move_y=_safe_float(self.all_get("GeoAligner_3__MoveY", 0.0), 0.0),
                move_z=_safe_float(self.all_get("GeoAligner_3__MoveZ", 0.0), 0.0),
            )

            self.GA3_SourceOut = SourceOut
            self.GA3_TargetOut = TargetOut
            self.GA3_TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None
            self.GA3_MovedGeo = MovedGeo

            self.Log.append("[GA3] 完成：MoveX={}".format(move_x))

        except Exception as e:
            self.Log.append("[ERROR][GA3] GeoAligner::3 出错: {}".format(e))
            return self

        # 3.6 CutTimbersByTools_V3：先切 GA2，再切 GA3
        try:
            if self.SSA_MaxClosedBrep is None:
                self.Log.append("[CUT] SSA_MaxClosedBrep 为空，跳过切割。")
                return self

            keep_inside = bool(self.all_get("CutTimbersByTools_V3__KeepInside", False))

            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=False)

            # first cut
            self.CutV3_1_CutTimbers, self.CutV3_1_FailTimbers, self.CutV3_1_Log = cutter.cut(
                timbers=self.SSA_MaxClosedBrep,
                tools=self.GA2_MovedGeo,
                keep_inside=keep_inside,
                debug=None
            )

            # second cut using output as input
            self.CutV3_2_CutTimbers, self.CutV3_2_FailTimbers, self.CutV3_2_Log = cutter.cut(
                timbers=self.CutV3_1_CutTimbers,
                tools=self.GA3_MovedGeo,
                keep_inside=keep_inside,
                debug=None
            )

            self.Log.append("[CUT] 完成：first_fail={} second_fail={}".format(
                _gh_count(self.CutV3_1_FailTimbers),
                _gh_count(self.CutV3_2_FailTimbers),
            ))

        except Exception as e:
            self.Log.append("[ERROR][CUT] CutTimbersByTools_V3 出错: {}".format(e))

        # 3.7 CutTimbersByTools_V3::3
        # Timbers = GeoAligner::1 的 MovedGeo
        # Tools   = HuaGongWithChaAng 输出 AlignToolToTimber_4_MovedGeo_tree
        # 目的：用 HuaGongWithChaAng 的对位刀具树切割 GA1 对位后的木料（用于后续/对比）
        try:
            tools_tree = None
            try:
                tools_tree = getattr(self.solver_huagong, "AlignToolToTimber_4_MovedGeo_tree", None)
            except:
                tools_tree = None

            timbers_in = self.GA_MovedGeo

            self.CutV3_3_Tools_in = tools_tree
            self.CutV3_3_Timbers_in = timbers_in

            if timbers_in is None:
                self.Log.append("[CUT3] GA_MovedGeo 为空，跳过 CutTimbersByTools_V3::3。")
            elif tools_tree is None:
                self.Log.append("[CUT3] AlignToolToTimber_4_MovedGeo_tree 为空，跳过 CutTimbersByTools_V3::3。")
            else:
                keep_inside3 = bool(self.all_get("CutTimbersByTools_V3__KeepInside", False))
                cutter3 = FT_CutTimbersByTools_GH_SolidDifference(debug=False)
                self.CutV3_3_CutTimbers, self.CutV3_3_FailTimbers, self.CutV3_3_Log = cutter3.cut(
                    timbers=timbers_in,
                    tools=tools_tree,
                    keep_inside=keep_inside3,
                    debug=None
                )
                self.Log.append("[CUT3] 完成：Cut={}, Fail={}".format(
                    _gh_count(self.CutV3_3_CutTimbers),
                    _gh_count(self.CutV3_3_FailTimbers)
                ))
        except Exception as e:
            self.Log.append("[ERROR][CUT3] CutTimbersByTools_V3::3 出错: {}".format(e))

        return self

    def run(self):
        self.step1_read_db()

        if not self.All_1:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        self.step2_chain()
        self.step3_cut_and_huatouzi()

        # 最终 CutTimbers：输出 = Step3 二次切割最终 CutTimbers + GeoAligner::1 的 MovedGeo 列表（用于调试/比对）
        if self.CutV3_2_CutTimbers is not None:
            _final_cut = self.CutV3_2_CutTimbers
        else:
            _final_cut = self.GA_MovedGeo if self.GA_MovedGeo is not None else self.ChaAng_CutTimbers

        # 统一为 list 并拼接：先放最终木料，再附加 GA1 对位后的几何列表
        self.CutTimbers = []
        for g in to_list(_final_cut):
            if g is not None:
                self.CutTimbers.append(g)
        # 用 CutTimbersByTools_V3::3 的 CutTimbers 替代原先附加的 GeoAligner::1.MovedGeo
        _cut3_out = self.CutV3_3_CutTimbers if self.CutV3_3_CutTimbers is not None else self.GA_MovedGeo
        for g in to_list(_cut3_out):
            if g is not None:
                self.CutTimbers.append(g)

        # FailTimbers：聚合（保持顺序）
        fail = []
        for f in to_list(self.ChaAng_FailTimbers):
            if f is not None:
                fail.append(f)
        for f in to_list(self.HuaGong_FailTimbers):
            if f is not None:
                fail.append(f)

        for f in to_list(self.CutV3_1_FailTimbers):
            if f is not None:
                fail.append(f)
        for f in to_list(self.CutV3_2_FailTimbers):
            if f is not None:
                fail.append(f)
        self.FailTimbers = fail

        return self


if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    #   ※ 显式逐项绑定 —— 参考附件 LingGongSolver.py 风格
    # ==============================================================

    solver = ChaAngWithHuaGong4PUSolver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- Step1: DB 输出 ---
    Value_1 = solver.Value_1
    All_1 = solver.All_1
    AllDict_1 = solver.AllDict_1
    DBLog_1 = solver.DBLog_1

    # --- Step2: ChaAng 输出 ---
    ChaAng_CutTimbers = solver.ChaAng_CutTimbers
    ChaAng_FailTimbers = solver.ChaAng_FailTimbers
    ChaAng_Log = solver.ChaAng_Log
    ChaAng_RefPlanes = solver.ChaAng_RefPlanes

    # --- Step2: HuaGongWithChaAng 输出 ---
    HuaGong_CutTimbers = solver.HuaGong_CutTimbers
    HuaGong_FailTimbers = solver.HuaGong_FailTimbers
    HuaGong_Log = solver.HuaGong_Log
    HuaGong_FacePlaneList = solver.HuaGong_FacePlaneList

    # --- Step2: GeoAligner::1 输出 ---
    GA_SourceOut = solver.GA_SourceOut
    GA_TargetOut = solver.GA_TargetOut
    GA_TransformOut = solver.GA_TransformOut
    GA_MovedGeo = solver.GA_MovedGeo

    # --- GeoAligner::1 输入快照（调试用） ---
    GA_Geo_in = solver.GA_Geo_in
    GA_SourcePlane_in = solver.GA_SourcePlane_in
    GA_TargetPlane_in = solver.GA_TargetPlane_in
    GA_src_idx = solver.GA_src_idx
    GA_tgt_idx = solver.GA_tgt_idx
    GA_rotate_deg = solver.GA_rotate_deg
    GA_flip_x = solver.GA_flip_x

    # --- Step3: SplitSectionAnalyzer 输出 ---
    SSA_SortedClosedBreps = solver.SSA_SortedClosedBreps
    SSA_SortedVolumes = solver.SSA_SortedVolumes
    SSA_MaxClosedBrep = solver.SSA_MaxClosedBrep
    SSA_SectionCurves = solver.SSA_SectionCurves
    SSA_SectionFaces = solver.SSA_SectionFaces
    SSA_StableEdgeCurves = solver.SSA_StableEdgeCurves
    SSA_StableLineSegments = solver.SSA_StableLineSegments
    SSA_SegmentMidPoints = solver.SSA_SegmentMidPoints
    SSA_LowestMidPoint = solver.SSA_LowestMidPoint
    SSA_HighestMidPoint = solver.SSA_HighestMidPoint
    SSA_MinXMidPoint = solver.SSA_MinXMidPoint
    SSA_MaxXMidPoint = solver.SSA_MaxXMidPoint
    SSA_MinYMidPoint = solver.SSA_MinYMidPoint
    SSA_MaxYMidPoint = solver.SSA_MaxYMidPoint
    SSA_MinZMidPoint = solver.SSA_MinZMidPoint
    SSA_MaxZMidPoint = solver.SSA_MaxZMidPoint
    SSA_CutterAnglesHV = solver.SSA_CutterAnglesHV
    SSA_Log = solver.SSA_Log

    # --- Step3: RightTrianglePrismBuilder 输出 ---
    RTP_dist = solver.RTP_dist
    RTP_SectionCurve = solver.RTP_SectionCurve
    RTP_SectionPts = solver.RTP_SectionPts
    RTP_BrepSolid = solver.RTP_BrepSolid
    RTP_BrepParts = solver.RTP_BrepParts
    RTP_OPlanes = solver.RTP_OPlanes
    RTP_Log = solver.RTP_Log

    # --- Step3: HuaTouZi 输出 ---
    HTZ_SolidBrep = solver.HTZ_SolidBrep
    HTZ_SectionCrv = solver.HTZ_SectionCrv
    HTZ_SectionCrv_Pos = solver.HTZ_SectionCrv_Pos
    HTZ_SectionCrv_Neg = solver.HTZ_SectionCrv_Neg
    HTZ_LoftBrep = solver.HTZ_LoftBrep
    HTZ_CapPosBrep = solver.HTZ_CapPosBrep
    HTZ_CapNegBrep = solver.HTZ_CapNegBrep
    HTZ_Pts = solver.HTZ_Pts
    HTZ_Arc1 = solver.HTZ_Arc1
    HTZ_Arc2 = solver.HTZ_Arc2
    HTZ_PlaneAtB = solver.HTZ_PlaneAtB
    HTZ_PlaneAtB_X = solver.HTZ_PlaneAtB_X
    HTZ_PlaneAtB_Y = solver.HTZ_PlaneAtB_Y
    HTZ_Log = solver.HTZ_Log

    # --- Step3: GeoAligner::2 输出 ---
    GA2_SourceOut = solver.GA2_SourceOut
    GA2_TargetOut = solver.GA2_TargetOut
    GA2_TransformOut = solver.GA2_TransformOut
    GA2_MovedGeo = solver.GA2_MovedGeo
    GA2_SourcePlane_in = solver.GA2_SourcePlane_in
    GA2_TargetPlane_in = solver.GA2_TargetPlane_in

    # --- Step3: GeoAligner::3 输出 ---
    GA3_SourceOut = solver.GA3_SourceOut
    GA3_TargetOut = solver.GA3_TargetOut
    GA3_TransformOut = solver.GA3_TransformOut
    GA3_MovedGeo = solver.GA3_MovedGeo
    GA3_MoveX = solver.GA3_MoveX

    # --- Step3: CutTimbersByTools_V3 输出 ---
    CutV3_1_CutTimbers = solver.CutV3_1_CutTimbers
    CutV3_1_FailTimbers = solver.CutV3_1_FailTimbers
    CutV3_1_Log = solver.CutV3_1_Log
    CutV3_2_CutTimbers = solver.CutV3_2_CutTimbers
    CutV3_2_FailTimbers = solver.CutV3_2_FailTimbers
    CutV3_2_Log = solver.CutV3_2_Log

    # --- Step3: CutTimbersByTools_V3::3 输出 ---
    CutV3_3_CutTimbers = solver.CutV3_3_CutTimbers
    CutV3_3_FailTimbers = solver.CutV3_3_FailTimbers
    CutV3_3_Log = solver.CutV3_3_Log
    CutV3_3_Tools_in = solver.CutV3_3_Tools_in
    CutV3_3_Timbers_in = solver.CutV3_3_Timbers_in

    # ==============================================================
    # Passthrough developer-friendly outputs from sub-solvers
    #   - HuaGongWithChaAng (HuaGong_MatchedChaAng_4PU)
    #   - ChaAng (ChaAng4PUSolver)
    # NOTE:
    #   These bindings mirror the original component "输出绑定区" so that
    #   ChaAngWithHuaGong4PU exposes the same debug ports without losing any.
    # ==============================================================

    _hg = solver.solver_huagong
    _ca = solver.solver_chaang


    def _ga(obj, name, default=None):
        try:
            return getattr(obj, name, default) if obj is not None else default
        except:
            return default


    # ------------------------------
    # HuaGongWithChaAng passthrough
    # ------------------------------
    # --- 最终主输出（来自 HuaGongWithChaAng 组件） ---
    HuaGongWithChaAng_CutTimbers = flatten_tree(_ga(_hg, "CutTimbers", []))
    HuaGongWithChaAng_FailTimbers = flatten_tree(_ga(_hg, "FailTimbers", []))
    HuaGongWithChaAng_Log = flatten_tree(_ga(_hg, "Log", []))

    # --- Step1: DB 输出 ---
    Value = _ga(_hg, "Value", None)
    All = _ga(_hg, "All", None)
    AllDict = _ga(_hg, "AllDict", None)
    DBLog = flatten_tree(_ga(_hg, "DBLog", []))

    # --- Step2: Timber_block_uniform 输出 ---
    TimberBrep = _ga(_hg, "TimberBrep", None)
    FaceList = flatten_tree(_ga(_hg, "FaceList", []))
    PointList = flatten_tree(_ga(_hg, "PointList", []))
    EdgeList = flatten_tree(_ga(_hg, "EdgeList", []))
    CenterPoint = _ga(_hg, "CenterPoint", None)
    CenterAxisLines = flatten_tree(_ga(_hg, "CenterAxisLines", []))
    EdgeMidPoints = flatten_tree(_ga(_hg, "EdgeMidPoints", []))
    FacePlaneList = flatten_tree(_ga(_hg, "FacePlaneList", []))
    Corner0Planes = flatten_tree(_ga(_hg, "Corner0Planes", []))
    LocalAxesPlane = _ga(_hg, "LocalAxesPlane", None)
    AxisX = _ga(_hg, "AxisX", None)
    AxisY = _ga(_hg, "AxisY", None)
    AxisZ = _ga(_hg, "AxisZ", None)
    FaceDirTags = flatten_tree(_ga(_hg, "FaceDirTags", []))
    EdgeDirTags = flatten_tree(_ga(_hg, "EdgeDirTags", []))
    Corner0EdgeDirs = flatten_tree(_ga(_hg, "Corner0EdgeDirs", []))
    TimberLog = flatten_tree(_ga(_hg, "TimberLog", []))

    # --- Step3: Juansha / PlaneFromLists::1 / AlignToolToTimber::1 输出 ---
    Juansha_ToolBrep = _ga(_hg, "Juansha_ToolBrep", None)
    Juansha_SectionEdges = flatten_tree(_ga(_hg, "Juansha_SectionEdges", []))
    Juansha_HL_Intersection = _ga(_hg, "Juansha_HL_Intersection", None)
    Juansha_HeightFacePlane = _ga(_hg, "Juansha_HeightFacePlane", None)
    Juansha_LengthFacePlane = _ga(_hg, "Juansha_LengthFacePlane", None)
    Juansha_Log = flatten_tree(_ga(_hg, "Juansha_Log", []))

    PlaneFromLists_1_BasePlane = flatten_tree(_ga(_hg, "PlaneFromLists_1_BasePlane", []))
    PlaneFromLists_1_OriginPoint = flatten_tree(_ga(_hg, "PlaneFromLists_1_OriginPoint", []))
    PlaneFromLists_1_ResultPlane = flatten_tree(_ga(_hg, "PlaneFromLists_1_ResultPlane", []))
    PlaneFromLists_1_Log = flatten_tree(_ga(_hg, "PlaneFromLists_1_Log", []))

    AlignToolToTimber_1_SourceOut = flatten_tree(_ga(_hg, "AlignToolToTimber_1_SourceOut", []))
    AlignToolToTimber_1_TargetOut = flatten_tree(_ga(_hg, "AlignToolToTimber_1_TargetOut", []))
    AlignToolToTimber_1_TransformOut = flatten_tree(_ga(_hg, "AlignToolToTimber_1_TransformOut", []))
    AlignToolToTimber_1_MovedGeo = flatten_tree(_ga(_hg, "AlignToolToTimber_1_MovedGeo", []))
    AlignToolToTimber_1_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_1_Log", []))

    # --- Step4: BlockCutter::1 / AlignToolToTimber::2 输出 ---
    BlockCutter_1_TimberBrep = _ga(_hg, "BlockCutter_1_TimberBrep", None)
    BlockCutter_1_TimberBrep_Branches = flatten_tree(_ga(_hg, "BlockCutter_1_TimberBrep_Branches", []))
    BlockCutter_1_FaceList = flatten_tree(_ga(_hg, "BlockCutter_1_FaceList", []))
    BlockCutter_1_PointList = flatten_tree(_ga(_hg, "BlockCutter_1_PointList", []))
    BlockCutter_1_EdgeList = flatten_tree(_ga(_hg, "BlockCutter_1_EdgeList", []))
    BlockCutter_1_CenterPoint = _ga(_hg, "BlockCutter_1_CenterPoint", None)
    BlockCutter_1_CenterAxisLines = flatten_tree(_ga(_hg, "BlockCutter_1_CenterAxisLines", []))
    BlockCutter_1_EdgeMidPoints = flatten_tree(_ga(_hg, "BlockCutter_1_EdgeMidPoints", []))
    BlockCutter_1_FacePlaneList = flatten_tree(_ga(_hg, "BlockCutter_1_FacePlaneList", []))
    BlockCutter_1_FacePlaneList_Branches = flatten_tree(_ga(_hg, "BlockCutter_1_FacePlaneList_Branches", []))
    BlockCutter_1_Corner0Planes = flatten_tree(_ga(_hg, "BlockCutter_1_Corner0Planes", []))
    BlockCutter_1_LocalAxesPlane = _ga(_hg, "BlockCutter_1_LocalAxesPlane", None)
    BlockCutter_1_AxisX = _ga(_hg, "BlockCutter_1_AxisX", None)
    BlockCutter_1_AxisY = _ga(_hg, "BlockCutter_1_AxisY", None)
    BlockCutter_1_AxisZ = _ga(_hg, "BlockCutter_1_AxisZ", None)
    BlockCutter_1_FaceDirTags = flatten_tree(_ga(_hg, "BlockCutter_1_FaceDirTags", []))
    BlockCutter_1_EdgeDirTags = flatten_tree(_ga(_hg, "BlockCutter_1_EdgeDirTags", []))
    BlockCutter_1_Corner0EdgeDirs = flatten_tree(_ga(_hg, "BlockCutter_1_Corner0EdgeDirs", []))
    BlockCutter_1_Log = flatten_tree(_ga(_hg, "BlockCutter_1_Log", []))

    # Tree 输出保持嵌套列表结构（GH 会自动识别为 Tree）
    AlignToolToTimber_2_SourceOut_tree = _ga(_hg, "AlignToolToTimber_2_SourceOut_tree", [])
    AlignToolToTimber_2_TargetOut_tree = _ga(_hg, "AlignToolToTimber_2_TargetOut_tree", [])
    AlignToolToTimber_2_TransformOut_tree = _ga(_hg, "AlignToolToTimber_2_TransformOut_tree", [])
    AlignToolToTimber_2_MovedGeo_tree = _ga(_hg, "AlignToolToTimber_2_MovedGeo_tree", [])
    AlignToolToTimber_2_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_2_Log", []))

    # --- Step5: BlockCutter::2 / AlignToolToTimber::3 输出 ---
    BlockCutter_2_TimberBrep = flatten_tree(_ga(_hg, "BlockCutter_2_TimberBrep", []))
    BlockCutter_2_FaceList = flatten_tree(_ga(_hg, "BlockCutter_2_FaceList", []))
    BlockCutter_2_PointList = flatten_tree(_ga(_hg, "BlockCutter_2_PointList", []))
    BlockCutter_2_EdgeList = flatten_tree(_ga(_hg, "BlockCutter_2_EdgeList", []))
    BlockCutter_2_CenterPoint = _ga(_hg, "BlockCutter_2_CenterPoint", None)
    BlockCutter_2_CenterAxisLines = flatten_tree(_ga(_hg, "BlockCutter_2_CenterAxisLines", []))
    BlockCutter_2_EdgeMidPoints = flatten_tree(_ga(_hg, "BlockCutter_2_EdgeMidPoints", []))
    BlockCutter_2_FacePlaneList = flatten_tree(_ga(_hg, "BlockCutter_2_FacePlaneList", []))
    BlockCutter_2_Corner0Planes = flatten_tree(_ga(_hg, "BlockCutter_2_Corner0Planes", []))
    BlockCutter_2_LocalAxesPlane = _ga(_hg, "BlockCutter_2_LocalAxesPlane", None)
    BlockCutter_2_AxisX = _ga(_hg, "BlockCutter_2_AxisX", None)
    BlockCutter_2_AxisY = _ga(_hg, "BlockCutter_2_AxisY", None)
    BlockCutter_2_AxisZ = _ga(_hg, "BlockCutter_2_AxisZ", None)
    BlockCutter_2_FaceDirTags = flatten_tree(_ga(_hg, "BlockCutter_2_FaceDirTags", []))
    BlockCutter_2_EdgeDirTags = flatten_tree(_ga(_hg, "BlockCutter_2_EdgeDirTags", []))
    BlockCutter_2_Corner0EdgeDirs = flatten_tree(_ga(_hg, "BlockCutter_2_Corner0EdgeDirs", []))
    BlockCutter_2_Log = flatten_tree(_ga(_hg, "BlockCutter_2_Log", []))

    AlignToolToTimber_3_SourceOut_tree = _ga(_hg, "AlignToolToTimber_3_SourceOut_tree", [])
    AlignToolToTimber_3_TargetOut_tree = _ga(_hg, "AlignToolToTimber_3_TargetOut_tree", [])
    AlignToolToTimber_3_TransformOut_tree = _ga(_hg, "AlignToolToTimber_3_TransformOut_tree", [])
    AlignToolToTimber_3_MovedGeo_tree = _ga(_hg, "AlignToolToTimber_3_MovedGeo_tree", [])
    AlignToolToTimber_3_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_3_Log", []))

    # --- Step6: BlockCutter::3 / AlignToolToTimber::4 输出 ---
    BlockCutter_3_TimberBrep = flatten_tree(_ga(_hg, "BlockCutter_3_TimberBrep", []))
    BlockCutter_3_FaceList = flatten_tree(_ga(_hg, "BlockCutter_3_FaceList", []))
    BlockCutter_3_PointList = flatten_tree(_ga(_hg, "BlockCutter_3_PointList", []))
    BlockCutter_3_EdgeList = flatten_tree(_ga(_hg, "BlockCutter_3_EdgeList", []))
    BlockCutter_3_CenterPoint = _ga(_hg, "BlockCutter_3_CenterPoint", None)
    BlockCutter_3_CenterAxisLines = flatten_tree(_ga(_hg, "BlockCutter_3_CenterAxisLines", []))
    BlockCutter_3_EdgeMidPoints = flatten_tree(_ga(_hg, "BlockCutter_3_EdgeMidPoints", []))
    BlockCutter_3_FacePlaneList = flatten_tree(_ga(_hg, "BlockCutter_3_FacePlaneList", []))
    BlockCutter_3_Corner0Planes = flatten_tree(_ga(_hg, "BlockCutter_3_Corner0Planes", []))
    BlockCutter_3_LocalAxesPlane = _ga(_hg, "BlockCutter_3_LocalAxesPlane", None)
    BlockCutter_3_AxisX = _ga(_hg, "BlockCutter_3_AxisX", None)
    BlockCutter_3_AxisY = _ga(_hg, "BlockCutter_3_AxisY", None)
    BlockCutter_3_AxisZ = _ga(_hg, "BlockCutter_3_AxisZ", None)
    BlockCutter_3_FaceDirTags = flatten_tree(_ga(_hg, "BlockCutter_3_FaceDirTags", []))
    BlockCutter_3_EdgeDirTags = flatten_tree(_ga(_hg, "BlockCutter_3_EdgeDirTags", []))
    BlockCutter_3_Corner0EdgeDirs = flatten_tree(_ga(_hg, "BlockCutter_3_Corner0EdgeDirs", []))
    BlockCutter_3_Log = flatten_tree(_ga(_hg, "BlockCutter_3_Log", []))

    AlignToolToTimber_4_SourceOut_tree = _ga(_hg, "AlignToolToTimber_4_SourceOut_tree", [])
    AlignToolToTimber_4_TargetOut_tree = _ga(_hg, "AlignToolToTimber_4_TargetOut_tree", [])
    AlignToolToTimber_4_TransformOut_tree = _ga(_hg, "AlignToolToTimber_4_TransformOut_tree", [])
    AlignToolToTimber_4_MovedGeo_tree = _ga(_hg, "AlignToolToTimber_4_MovedGeo_tree", [])
    AlignToolToTimber_4_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_4_Log", []))

    # --- Step7: QiAOTool / PlaneFromLists::2-3 / AlignToolToTimber::5 输出 ---
    QiAOTool_CutTimbers = flatten_tree(_ga(_hg, "QiAOTool_CutTimbers", []))
    QiAOTool_FailTimbers = flatten_tree(_ga(_hg, "QiAOTool_FailTimbers", []))
    QiAOTool_TimberBrep = _ga(_hg, "QiAOTool_TimberBrep", None)
    QiAOTool_EdgeMidPoints = flatten_tree(_ga(_hg, "QiAOTool_EdgeMidPoints", []))
    QiAOTool_Corner0Planes = flatten_tree(_ga(_hg, "QiAOTool_Corner0Planes", []))
    QiAOTool_FacePlaneList = flatten_tree(_ga(_hg, "QiAOTool_FacePlaneList", []))
    QiAOTool_Log = flatten_tree(_ga(_hg, "QiAOTool_Log", []))

    PlaneFromLists_2_BasePlane = flatten_tree(_ga(_hg, "PlaneFromLists_2_BasePlane", []))
    PlaneFromLists_2_OriginPoint = flatten_tree(_ga(_hg, "PlaneFromLists_2_OriginPoint", []))
    PlaneFromLists_2_ResultPlane = flatten_tree(_ga(_hg, "PlaneFromLists_2_ResultPlane", []))
    PlaneFromLists_2_Log = flatten_tree(_ga(_hg, "PlaneFromLists_2_Log", []))

    PlaneFromLists_3_BasePlane = flatten_tree(_ga(_hg, "PlaneFromLists_3_BasePlane", []))
    PlaneFromLists_3_OriginPoint = flatten_tree(_ga(_hg, "PlaneFromLists_3_OriginPoint", []))
    PlaneFromLists_3_ResultPlane = flatten_tree(_ga(_hg, "PlaneFromLists_3_ResultPlane", []))
    PlaneFromLists_3_Log = flatten_tree(_ga(_hg, "PlaneFromLists_3_Log", []))

    AlignToolToTimber_5_SourceOut = flatten_tree(_ga(_hg, "AlignToolToTimber_5_SourceOut", []))
    AlignToolToTimber_5_TargetOut = flatten_tree(_ga(_hg, "AlignToolToTimber_5_TargetOut", []))
    AlignToolToTimber_5_TransformOut = flatten_tree(_ga(_hg, "AlignToolToTimber_5_TransformOut", []))
    AlignToolToTimber_5_MovedGeo = flatten_tree(_ga(_hg, "AlignToolToTimber_5_MovedGeo", []))
    AlignToolToTimber_5_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_5_Log", []))

    # --- Step8: GongYan / PlaneFromLists::4 / AlignToolToTimber::6 输出 ---
    GongYan_SectionCurve = _ga(_hg, "GongYan_SectionCurve", None)
    GongYan_SectionFace = _ga(_hg, "GongYan_SectionFace", None)
    GongYan_LeftCurve = _ga(_hg, "GongYan_LeftCurve", None)
    GongYan_RightCurve = _ga(_hg, "GongYan_RightCurve", None)
    GongYan_SymmetryAxis = _ga(_hg, "GongYan_SymmetryAxis", None)
    GongYan_AllPoints = _ga(_hg, "GongYan_AllPoints", None)
    GongYan_ToolBrep = _ga(_hg, "GongYan_ToolBrep", None)
    GongYan_SectionPlanes = flatten_tree(_ga(_hg, "GongYan_SectionPlanes", []))
    GongYan_Log = flatten_tree(_ga(_hg, "GongYan_Log", []))

    PlaneFromLists_4_BasePlane = flatten_tree(_ga(_hg, "PlaneFromLists_4_BasePlane", []))
    PlaneFromLists_4_OriginPoint = flatten_tree(_ga(_hg, "PlaneFromLists_4_OriginPoint", []))
    PlaneFromLists_4_ResultPlane = flatten_tree(_ga(_hg, "PlaneFromLists_4_ResultPlane", []))
    PlaneFromLists_4_Log = flatten_tree(_ga(_hg, "PlaneFromLists_4_Log", []))

    AlignToolToTimber_6_SourceOut_tree = _ga(_hg, "AlignToolToTimber_6_SourceOut_tree", [])
    AlignToolToTimber_6_TargetOut_tree = _ga(_hg, "AlignToolToTimber_6_TargetOut_tree", [])
    AlignToolToTimber_6_TransformOut_tree = _ga(_hg, "AlignToolToTimber_6_TransformOut_tree", [])
    AlignToolToTimber_6_MovedGeo_tree_raw = _ga(_hg, "AlignToolToTimber_6_MovedGeo_tree", [])
    AlignToolToTimber_6_MovedGeo_tree = flatten_tree(AlignToolToTimber_6_MovedGeo_tree_raw)
    AlignToolToTimber_6_Log = flatten_tree(_ga(_hg, "AlignToolToTimber_6_Log", []))

    # ------------------------------
    # ChaAng passthrough (developer outputs)
    # ------------------------------
    ChaAng_Passthrough_CutTimbers = _ga(_ca, "CutTimbers", None)
    ChaAng_Passthrough_FailTimbers = _ga(_ca, "FailTimbers", None)
    ChaAng_Passthrough_Log = _ga(_ca, "Log", None)

    All_1_CA = _ga(_ca, "All_1", None)
    AllDict_1_CA = _ga(_ca, "AllDict_1", None)
    DBLog_1_CA = _ga(_ca, "DBLog_1", None)

    base_point_used = _ga(_ca, "base_point", None)
    ref_plane_mode = _ga(_ca, "ref_plane_mode", None)
    OA = _ga(_ca, "OA", None);
    OB = _ga(_ca, "OB", None)
    BC_CA = _ga(_ca, "BC", None);
    CD = _ga(_ca, "CD", None)
    thickness = _ga(_ca, "thickness", None)
    GE = _ga(_ca, "GE", None)
    tol = _ga(_ca, "tol", None)
    offset_dist = _ga(_ca, "offset_dist", None)
    use_qin = _ga(_ca, "use_qin", None)

    out_chaang4pu = _ga(_ca, "out_chaang4pu", None)

    O = _ga(_ca, "O", None);
    A = _ga(_ca, "A", None);
    B = _ga(_ca, "B", None);
    D = _ga(_ca, "D", None)
    E = _ga(_ca, "E", None);
    F = _ga(_ca, "F", None);
    G = _ga(_ca, "G", None)

    EU_line = _ga(_ca, "EU_line", None);
    EL_line = _ga(_ca, "EL_line", None);
    EF_line = _ga(_ca, "EF_line", None)
    Edges = _ga(_ca, "Edges", None)
    SectionPolyline = _ga(_ca, "SectionPolyline", None)
    SectionCurve = _ga(_ca, "SectionCurve", None)
    SectionBrep = _ga(_ca, "SectionBrep", None)
    SectionCurve_In = _ga(_ca, "SectionCurve_In", None)
    SectionCurve_Out = _ga(_ca, "SectionCurve_Out", None)
    SolidBrep = _ga(_ca, "SolidBrep", None)
    SolidFace_AE = _ga(_ca, "SolidFace_AE", None)

    Plane_Main = _ga(_ca, "Plane_Main", None)
    Plane_X = _ga(_ca, "Plane_X", None)
    Plane_Y = _ga(_ca, "Plane_Y", None)
    RefPlanes = _ga(_ca, "RefPlanes", None)

    # Qin
    H = _ga(_ca, "H", None);
    I = _ga(_ca, "I", None);
    J = _ga(_ca, "J", None);
    K = _ga(_ca, "K", None)
    L = _ga(_ca, "L", None);
    N = _ga(_ca, "N", None)
    D1 = _ga(_ca, "D1", None);
    D2 = _ga(_ca, "D2", None);
    H1 = _ga(_ca, "H1", None);
    H2 = _ga(_ca, "H2", None)
    N1 = _ga(_ca, "N1", None);
    N2 = _ga(_ca, "N2", None)
    Arc_JLI = _ga(_ca, "Arc_JLI", None)
    Arc_DNH = _ga(_ca, "Arc_DNH", None)
    Arc_D1N1H1 = _ga(_ca, "Arc_D1N1H1", None)
    Arc_D2N2H2 = _ga(_ca, "Arc_D2N2H2", None)
    Arc_D1JD2 = _ga(_ca, "Arc_D1JD2", None)
    Arc_H1IH2 = _ga(_ca, "Arc_H1IH2", None)
    QinSurface = _ga(_ca, "QinSurface", None)
    QinCutBreps = _ga(_ca, "QinCutBreps", None)
    QinCutKeep = _ga(_ca, "QinCutKeep", None)
    QinJoinBrep = _ga(_ca, "QinJoinBrep", None)

    # PiZhu
    PiZhu_H = _ga(_ca, "PiZhu_H", None)
    PiZhu_DH = _ga(_ca, "PiZhu_DH", None)
    PiZhu_D1H1 = _ga(_ca, "PiZhu_D1H1", None)
    PiZhu_D2H2 = _ga(_ca, "PiZhu_D2H2", None)
    PiZhuPlane = _ga(_ca, "PiZhuPlane", None)
    PiZhuCutBreps = _ga(_ca, "PiZhuCutBreps", None)
    PiZhuCutKeep = _ga(_ca, "PiZhuCutKeep", None)
    PiZhuJoinBrep = _ga(_ca, "PiZhuJoinBrep", None)

    FinalKeepBrep = _ga(_ca, "FinalKeepBrep", None)

    # --- Step3 developer outputs (ChaAng solver internal chain) ---
    QiAo_Params = _ga(_ca, "QiAo_Params", None)
    QiAo_CutTimbers = _ga(_ca, "QiAo_CutTimbers", None)
    QiAo_FailTimbers = _ga(_ca, "QiAo_FailTimbers", None)

    TimberBrep_CA = _ga(_ca, "TimberBrep", None)
    ToolBrep = _ga(_ca, "ToolBrep", None)
    AlignedTool = _ga(_ca, "AlignedTool", None)

    EdgeMidPoints_CA = _ga(_ca, "EdgeMidPoints", None)
    Corner0Planes_CA = _ga(_ca, "Corner0Planes", None)
    PFL1_ResultPlane_CA = _ga(_ca, "PFL1_ResultPlane", None)
    QiAo_FacePlane = _ga(_ca, "QiAo_FacePlane", None)

    CutTimbers_QiAo = _ga(_ca, "CutTimbers_QiAo", None)
    FailTimbers_QiAo = _ga(_ca, "FailTimbers_QiAo", None)

    ChaAngPlane_PA = _ga(_ca, "ChaAngPlane_PA", None)
    PtA = _ga(_ca, "PtA", None)
    PtC = _ga(_ca, "PtC", None)
    PtE = _ga(_ca, "PtE", None)
    ChaAngSectionCurve = _ga(_ca, "ChaAngSectionCurve", None)
    ChaAngCutterBrep = _ga(_ca, "ChaAngCutterBrep", None)

    FaceList_CA = _ga(_ca, "FaceList", None)
    PointList_CA = _ga(_ca, "PointList", None)
    EdgeList_CA = _ga(_ca, "EdgeList", None)
    CenterPoint_CA = _ga(_ca, "CenterPoint", None)
    CenterAxisLines_CA = _ga(_ca, "CenterAxisLines", None)
    FacePlaneList_CA = _ga(_ca, "FacePlaneList", None)
    LocalAxesPlane_CA = _ga(_ca, "LocalAxesPlane", None)
    AxisX_CA = _ga(_ca, "AxisX", None)
    AxisY_CA = _ga(_ca, "AxisY", None)
    AxisZ_CA = _ga(_ca, "AxisZ", None)
    FaceDirTags_CA = _ga(_ca, "FaceDirTags", None)
    EdgeDirTags_CA = _ga(_ca, "EdgeDirTags", None)
    Corner0EdgeDirs_CA = _ga(_ca, "Corner0EdgeDirs", None)

    PFL1_BasePlane_CA = _ga(_ca, "PFL1_BasePlane", None)
    PFL1_OriginPoint_CA = _ga(_ca, "PFL1_OriginPoint", None)
    PFL1_ResultPlanes_CA = _ga(_ca, "PFL1_ResultPlanes", None)
    PFL1_Log_CA = _ga(_ca, "PFL1_Log", None)

    PFL2_BasePlane_CA = _ga(_ca, "PFL2_BasePlane", None)
    PFL2_OriginPoint_CA = _ga(_ca, "PFL2_OriginPoint", None)
    PFL2_ResultPlanes_CA = _ga(_ca, "PFL2_ResultPlanes", None)
    PFL2_Log_CA = _ga(_ca, "PFL2_Log", None)

    GA_SourceOut_CA = _ga(_ca, "GA_SourceOut", None)
    GA_TargetOut_CA = _ga(_ca, "GA_TargetOut", None)
    GA_TransformOut_CA = _ga(_ca, "GA_TransformOut", None)
    GA_MovedGeo_CA = _ga(_ca, "GA_MovedGeo", None)

    CutByTools_CutTimbers_CA = _ga(_ca, "CutByTools_CutTimbers", None)
    CutByTools_FailTimbers_CA = _ga(_ca, "CutByTools_FailTimbers", None)
    CutByTools_Log_CA = _ga(_ca, "CutByTools_Log", None)



# -*- coding: utf-8 -*-
"""
ChaAng_4PU_Solver_STEP1_3
------------------------------------------------------------
Step 1: DBJsonReader -> 读取 DG_Dou 表中 type_code=ChaAng_4PU 的 params_json
        并导出 All(list[tuple]) + AllDict(nested dict)
Step 2: ChaAng4Pu -> 调用 yingzao.ancientArchi.ChaAngQiAoV2 生成插昂剖面/实体等
Step 3: 䫜（QiAoChaAng + PlaneFromLists::1 + PlaneFromLists::2 + GeoAligner + CutTimbersByTools）

Inputs (GH):
    DBPath     : str
    base_point : rg.Point3d (优先于 DB)
    Refresh    : bool

Outputs (GH):
    CutTimbers  : Brep / list[Brep]
    FailTimbers : list
    Log         : list[str] (可直接接 Panel)

Developer-friendly:
    在 GH 中添加同名输出端即可看到所有 solver 成员变量。
"""

import traceback
import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

from yingzao.ancientArchi import (
    DBJsonReader,
    _to_list,
    parse_all_to_dict,
    all_get,
    to_scalar,
)

from yingzao.ancientArchi import (
    _coerce_point3d, _coerce_bool,
    QiAo_ChaAngToolSolver, InputHelper, GHPlaneFactory,
    FTPlaneFromLists,
    GeoAligner_xfm,
    FT_CutTimbersByTools_GH_SolidDifference,
)

# --- Robust import for ChaAngQiAoV2 (module vs class) ---
try:
    # preferred: import class from submodule
    from yingzao.ancientArchi.Gong.ChaAngQiAoV2 import ChaAngQiAoV2 as _ChaAngQiAoV2_CTOR
except Exception:
    # fallback: package may expose submodule as attribute
    import yingzao.ancientArchi as _aa
    _maybe = getattr(_aa, 'ChaAngQiAoV2', None)
    _ChaAngQiAoV2_CTOR = getattr(_maybe, 'ChaAngQiAoV2', _maybe)


# ======================================================================
# 小工具：GH 风格广播 + 递归拍平
# ======================================================================

def _is_seq(x):
    return isinstance(x, (list, tuple))

def _deep_flatten(x):
    """Requirement #11: recursively flatten list/tuple."""
    if x is None:
        return []
    if _is_seq(x):
        out = []
        for it in x:
            out.extend(_deep_flatten(it))
        return out
    return [x]

def _to_list_safe(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]

def _broadcast_n(*args):
    """
    GH 长度对齐：取最大长度 L
    - 标量/None -> 作为长度1
    - 短列表 -> 用最后一个元素补齐（GH 常见“最长列表”行为）
    返回：(broadcast_lists, L)
    """
    lists = []
    lens = []
    for a in args:
        if isinstance(a, (list, tuple)):
            lst = list(a)
        else:
            lst = [a]
        lists.append(lst)
        lens.append(len(lst))
    L = max(lens) if lens else 1

    out = []
    for lst in lists:
        if len(lst) == 0:
            out.append([None] * L)
            continue
        if len(lst) == L:
            out.append(lst)
            continue
        last = lst[-1]
        padded = lst[:] + [last] * (L - len(lst))
        out.append(padded)
    return out, L

def _get_param(AD, comp_names, port, default=None):
    """
    兼容命名差异：
    comp_names: str 或 list[str]，会依次尝试 all_get(AD, comp, port)
    """
    if AD is None:
        return default
    if isinstance(comp_names, (str, bytes)):
        comp_names = [comp_names]
    for cn in comp_names:
        try:
            v = all_get(AD, cn, port, None)
        except Exception:
            v = None
        if v is not None:
            return v
    return default


# ======================================================================
# Solver 主类
# ======================================================================
class ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver(object):

    def __init__(self, DBPath, base_point, Refresh):
        # ---- inputs
        self.DBPath = DBPath
        self.base_point_in = base_point
        self.Refresh = Refresh

        # ---- step1 outputs
        self.All_1 = None
        self.AllDict_1 = None
        self.DBLog_1 = []

        # ---- step2 outputs (ChaAng4Pu)
        self.base_point = None
        self.ref_plane_mode = None
        self.OA = None
        self.OB = None
        self.BC = None
        self.OC = None
        self.CD = None
        self.thickness = None
        self.GE = None
        self.tol = None
        self.offset_dist = None
        self.use_qin = None

        # 原 ChaAng4Pu 输出变量（全部保留）
        self.out_chaang4pu = None

        self.O = None
        self.A = None
        self.B = None
        self.C = None
        self.D = None
        self.E = None
        self.F = None
        self.G = None

        self.EU_line = None
        self.EL_line = None
        self.EF_line = None
        self.Edges = None
        self.SectionPolyline = None
        self.SectionCurve = None
        self.SectionBrep = None
        self.SectionCurve_In = None
        self.SectionCurve_Out = None
        self.SolidBrep = None
        self.SolidFace_AE = None
        self.Plane_Main = None
        self.Plane_X = None
        self.Plane_Y = None
        self.RefPlanes = None

        # Qin outputs
        self.H = None; self.I = None; self.J = None; self.K = None; self.L = None; self.N = None
        self.D1 = None; self.D2 = None; self.H1 = None; self.H2 = None; self.N1 = None; self.N2 = None
        self.Arc_JLI = None
        self.Arc_DNH = None
        self.Arc_D1N1H1 = None
        self.Arc_D2N2H2 = None
        self.Arc_D1JD2 = None
        self.Arc_H1IH2 = None
        self.QinSurface = None
        self.QinCutBreps = None
        self.QinCutKeep = None
        self.QinJoinBrep = None

        # PiZhu outputs
        self.PiZhu_H = None
        self.PiZhu_DH = None
        self.PiZhu_D1H1 = None
        self.PiZhu_D2H2 = None
        self.PiZhuPlane = None
        self.PiZhuCutBreps = None
        self.PiZhuCutKeep = None
        self.PiZhuJoinBrep = None

        # Final
        self.FinalKeepBrep = None

        # ---- step3 outputs / intermediates
        self.QiAo_Params = None

        # QiAoChaAng 核心输出
        self.QiAo_CutTimbers = None
        self.QiAo_FailTimbers = None

        # QiAoChaAng 开发输出（尽量保留同名）
        self.TimberBrep = None
        self.ToolBrep = None
        self.AlignedTool = None
        self.EdgeMidPoints = None
        self.Corner0Planes = None
        self.PFL1_ResultPlane = None
        self.QiAo_FacePlane = None

        self.CutTimbers_QiAo = None
        self.FailTimbers_QiAo = None
        self.ChaAngPlane_PA = None
        self.PtA = None
        self.PtC = None
        self.PtE = None
        self.ChaAngSectionCurve = None
        self.ChaAngCutterBrep = None

        self.FaceList = None
        self.PointList = None
        self.EdgeList = None
        self.CenterPoint = None
        self.CenterAxisLines = None
        self.FacePlaneList = None
        self.LocalAxesPlane = None
        self.AxisX = None
        self.AxisY = None
        self.AxisZ = None
        self.FaceDirTags = None
        self.EdgeDirTags = None
        self.Corner0EdgeDirs = None

        # PlaneFromLists::1
        self.PFL1_BasePlane = None
        self.PFL1_OriginPoint = None
        self.PFL1_ResultPlanes = None
        self.PFL1_Log = None

        # PlaneFromLists::2
        self.PFL2_BasePlane = None
        self.PFL2_OriginPoint = None
        self.PFL2_ResultPlanes = None
        self.PFL2_Log = None

        # GeoAligner
        self.GA_SourceOut = None
        self.GA_TargetOut = None
        self.GA_TransformOut = None
        self.GA_MovedGeo = None

        # CutTimbersByTools
        self.CutByTools_CutTimbers = None
        self.CutByTools_FailTimbers = None
        self.CutByTools_Log = None

        # ---- global
        self.CutTimbers = None
        self.FailTimbers = []
        self.Log = []

    # -----------------------------------------------------
    # Step 1：读取数据库（DG_Dou / type_code=ChaAng_4PU）
    # -----------------------------------------------------
    def step1_read_db(self):
        self.Log.append("Step1: DBJsonReader 读取 DG_Dou[type_code=ChaAng_4PU] ...")
        try:
            ghenv_obj = globals().get("ghenv", None)
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="ChaAng_4PU_JiaoAngInLineWJiaoHuaGong",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=ghenv_obj
            )
            Value, All, LogLines = reader.run()

            self.DBLog_1 = list(LogLines) if LogLines else []
            self.All_1 = All
            self.AllDict_1 = parse_all_to_dict(All)

            self.Log.append("Step1: OK (All / AllDict 已生成)")
        except Exception as e:
            self.Log.append("[Step1][DB ERROR] {}".format(e))
            self.DBLog_1.append(str(e))
            self.All_1 = None
            self.AllDict_1 = None
            traceback.print_exc()

    # -----------------------------------------------------
    # Step 2：ChaAng4Pu
    # -----------------------------------------------------
    def step2_chaang4pu(self):
        self.Log.append("Step2: ChaAng4Pu ...")

        AD = self.AllDict_1
        if AD is None:
            self.Log.append("[Step2] AllDict_1 为空，跳过。")
            return

        # base_point：输入端优先，其次 DB，其次原点
        bp = self.base_point_in
        if bp is None:
            bp_db = all_get(AD, "ChaAng4Pu", "base_point", None)
            if bp_db is not None:
                try:
                    bp = rg.Point3d(float(bp_db[0]), float(bp_db[1]), float(bp_db[2]))
                except Exception:
                    bp = rg.Point3d(0, 0, 0)
            else:
                bp = rg.Point3d(0, 0, 0)

        bp = _coerce_point3d(bp, rg.Point3d(0, 0, 0))
        self.base_point = bp

        self.ref_plane_mode = all_get(AD, "ChaAng4Pu", "ref_plane_mode", "WorldXZ") or "WorldXZ"

        self.OA = to_scalar(all_get(AD, "ChaAng4Pu", "OA", 5.0), 5.0)
        # OB / BC 在 ChaAngQiAoV2 中已移除（B 在 O-C 线段滑动），此处保留读取以兼容旧库字段
        self.OB = to_scalar(all_get(AD, "ChaAng4Pu", "OB", 22.0), 22.0)
        self.BC = to_scalar(all_get(AD, "ChaAng4Pu", "BC", 14.0), 14.0)
        # O-C（新）：优先读 OC；若旧库仍用 OD 字段则回退读取
        self.OC = to_scalar(
            all_get(AD, "ChaAng4Pu", "OC", all_get(AD, "ChaAng4Pu", "OD", 36.0)),
            36.0
        )
        self.CD = to_scalar(all_get(AD, "ChaAng4Pu", "CD", 6.0), 6.0)
        self.thickness = to_scalar(all_get(AD, "ChaAng4Pu", "thickness", 15.0), 15.0)
        self.GE = to_scalar(all_get(AD, "ChaAng4Pu", "GE", 53.0), 53.0)
        self.tol = to_scalar(all_get(AD, "ChaAng4Pu", "tol", 1e-6), 1e-6)
        self.offset_dist = to_scalar(all_get(AD, "ChaAng4Pu", "offset_dist", 5.0), 5.0)

        use_qin_raw = all_get(AD, "ChaAng4Pu", "use_qin", True)
        self.use_qin = _coerce_bool(use_qin_raw, default=True)

        try:
            solver = _ChaAngQiAoV2_CTOR(
                base_point_=self.base_point,
                ref_plane_mode_=self.ref_plane_mode,
                OA_=float(self.OA),
                OC_=float(self.OC),
                CD_=float(self.CD),
                thickness_=float(self.thickness),
                GE_=float(self.GE),
                tol_=float(self.tol),
                offset_dist_=float(self.offset_dist),
                use_qin_=bool(self.use_qin)
            )
            out = solver.solve()
            self.out_chaang4pu = out

            self.O = out.get("O")
            self.A = out.get("A")
            self.B = out.get("B")
            self.C = out.get("C")
            self.D = out.get("D")
            self.E = out.get("E")
            self.F = out.get("F")
            self.G = out.get("G")

            self.EU_line = out.get("EU_line")
            self.EL_line = out.get("EL_line")
            self.EF_line = out.get("EF_line")
            self.Edges = out.get("Edges")
            self.SectionPolyline = out.get("SectionPolyline")
            self.SectionCurve = out.get("SectionCurve")
            self.SectionBrep = out.get("SectionBrep")
            self.SectionCurve_In = out.get("SectionCurve_In")
            self.SectionCurve_Out = out.get("SectionCurve_Out")
            self.SolidBrep = out.get("SolidBrep")
            self.SolidFace_AE = out.get("SolidFace_AE")
            self.Plane_Main = out.get("Plane_Main")
            self.Plane_X = out.get("Plane_X")
            self.Plane_Y = out.get("Plane_Y")
            self.RefPlanes = out.get("RefPlanes")
            self.use_qin = out.get("use_qin", self.use_qin)

            # Qin
            self.H = out.get("H"); self.I = out.get("I"); self.J = out.get("J")
            self.K = out.get("K"); self.L = out.get("L"); self.N = out.get("N")
            self.D1 = out.get("D1"); self.D2 = out.get("D2")
            self.H1 = out.get("H1"); self.H2 = out.get("H2")
            self.N1 = out.get("N1"); self.N2 = out.get("N2")
            self.Arc_JLI = out.get("Arc_JLI")
            self.Arc_DNH = out.get("Arc_DNH")
            self.Arc_D1N1H1 = out.get("Arc_D1N1H1")
            self.Arc_D2N2H2 = out.get("Arc_D2N2H2")
            self.Arc_D1JD2 = out.get("Arc_D1JD2")
            self.Arc_H1IH2 = out.get("Arc_H1IH2")
            self.QinSurface = out.get("QinSurface")
            self.QinCutBreps = out.get("QinCutBreps")
            self.QinCutKeep = out.get("QinCutKeep")
            self.QinJoinBrep = out.get("QinJoinBrep")

            # PiZhu
            self.PiZhu_H = out.get("PiZhu_H")
            self.PiZhu_DH = out.get("PiZhu_DH")
            self.PiZhu_D1H1 = out.get("PiZhu_D1H1")
            self.PiZhu_D2H2 = out.get("PiZhu_D2H2")
            self.PiZhuPlane = out.get("PiZhuPlane")
            self.PiZhuCutBreps = out.get("PiZhuCutBreps")
            self.PiZhuCutKeep = out.get("PiZhuCutKeep")
            self.PiZhuJoinBrep = out.get("PiZhuJoinBrep")

            self.FinalKeepBrep = out.get("FinalKeepBrep")

            # 暂时输出 step2 的结果（step3 会覆盖为最终 CutTimbers）
            self.CutTimbers = self.FinalKeepBrep
            self.FailTimbers = []

            l2 = out.get("Log", [])
            if isinstance(l2, (list, tuple)):
                self.Log.extend([str(x) for x in l2])
            else:
                self.Log.append(str(l2))

            self.Log.append("Step2: OK (ChaAng4Pu 完成)")

        except Exception as e:
            self.Log.append("[Step2][ChaAng4Pu ERROR] {}".format(e))
            traceback.print_exc()
            self.CutTimbers = None
            self.FailTimbers = []

    # -----------------------------------------------------
    # Step 3：䫜（QiAoChaAng + PlaneFromLists + GeoAligner + CutTimbersByTools）
    # -----------------------------------------------------
    def step3_qiao(self):
        self.Log.append("Step3: 䫜（QiAoChaAng / PlaneFromLists / GeoAligner / Cut）...")

        AD = self.AllDict_1
        if AD is None:
            self.Log.append("[Step3] AllDict_1 为空，跳过。")
            return
        if self.FinalKeepBrep is None:
            self.Log.append("[Step3] FinalKeepBrep 为空，跳过。")
            return

        # ---- 1) QiAoChaAng
        try:
            bp = _coerce_point3d(self.base_point if self.base_point is not None else rg.Point3d(0,0,0),
                                 rg.Point3d(0,0,0))

            comp_qiao = ["QiAoChaAng", "QiAo_ChaAng", "QiAoChaAngTool", "QiAoChaAng::1"]

            def _tf(name, default):
                return float(to_scalar(_get_param(AD, comp_qiao, name, default), default))

            params = {
                "length_fen": _tf("length_fen", 41.0),
                "width_fen":  _tf("width_fen", 16.0),
                "height_fen": _tf("height_fen", 6.0),
                "base_point": bp,
                "timber_ref_plane": GHPlaneFactory.make(
                    _get_param(AD, comp_qiao, "timber_ref_plane_mode", "XZ"),
                    origin=bp
                ),
                "qi_height": _tf("qi_height", 4.0),
                "sha_width": _tf("sha_width", 2.0),
                "qi_offset_fen": _tf("qi_offset_fen", 0.5),
                "extrude_length": _tf("extrude_length", 28.0),
                "extrude_positive": InputHelper.to_bool(
                    _get_param(AD, comp_qiao, "extrude_positive", False),
                    default=False
                ),
                "qi_ref_plane": GHPlaneFactory.make(
                    _get_param(AD, comp_qiao, "qi_ref_plane_mode", "XZ"),
                    origin=bp
                ),
                "AE_length": _tf("AE_length", 14.0),
                "offset": _tf("offset", 4.0),
            }
            self.QiAo_Params = params

            qsolver = QiAo_ChaAngToolSolver(ghenv=globals().get("ghenv", None))
            qsolver.run(params)

            self.QiAo_CutTimbers = qsolver.CutTimbers
            self.QiAo_FailTimbers = qsolver.FailTimbers

            # 按你 QiAoChaAng 组件 try: 输出的字段名抓取（不存在就略过）
            for attr in [
                "TimberBrep","ToolBrep","AlignedTool","EdgeMidPoints","Corner0Planes","PFL1_ResultPlane",
                "QiAo_FacePlane","CutTimbers_QiAo","FailTimbers_QiAo","ChaAngPlane_PA","PtA","PtC","PtE",
                "ChaAngSectionCurve","ChaAngCutterBrep","FaceList","PointList","EdgeList","CenterPoint",
                "CenterAxisLines","FacePlaneList","LocalAxesPlane","AxisX","AxisY","AxisZ",
                "FaceDirTags","EdgeDirTags","Corner0EdgeDirs"
            ]:
                if hasattr(qsolver, attr):
                    setattr(self, attr, getattr(qsolver, attr))

            # 合并日志
            try:
                qlog = qsolver.Log
                if isinstance(qlog, (list, tuple)):
                    self.Log.extend([str(x) for x in qlog])
                else:
                    self.Log.append(str(qlog))
            except Exception:
                pass

        except Exception as e:
            self.Log.append("[Step3][QiAoChaAng ERROR] {}".format(e))
            traceback.print_exc()
            return

        # ---- 2) PlaneFromLists::1
        try:
            origin_points_1 = _to_list(self.D)          # ChaAng4Pu.D
            base_planes_1   = _to_list(self.RefPlanes)  # ChaAng4Pu.RefPlanes

            comp_pfl1 = ["PlaneFromLists::1", "PlaneFromLists_1", "PlaneFromLists1"]
            idx_origin_1 = _get_param(AD, comp_pfl1, "IndexOrigin", 0)
            idx_plane_1  = _get_param(AD, comp_pfl1, "IndexPlane", 0)

            idx_origin_1 = _to_list_safe(idx_origin_1)
            idx_plane_1  = _to_list_safe(idx_plane_1)

            (io_list, ip_list), L = _broadcast_n(idx_origin_1, idx_plane_1)

            builder1 = FTPlaneFromLists(wrap=True)
            BP_list, OP_list, RP_list, LOG_list = [], [], [], []
            for i in range(L):
                BP, OP, RP, LG = builder1.build_plane(
                    origin_points_1,
                    base_planes_1,
                    io_list[i],
                    ip_list[i]
                )
                BP_list.append(BP); OP_list.append(OP); RP_list.append(RP); LOG_list.append(LG)

            self.PFL1_BasePlane    = BP_list
            self.PFL1_OriginPoint  = OP_list
            self.PFL1_ResultPlanes = RP_list
            self.PFL1_Log          = LOG_list

        except Exception as e:
            self.Log.append("[Step3][PlaneFromLists::1 ERROR] {}".format(e))
            traceback.print_exc()
            return

        # ---- 3) PlaneFromLists::2
        try:
            origin_points_2 = _to_list(self.PtA)          # QiAoChaAng.PtA
            base_planes_2   = _to_list(self.Corner0Planes)# QiAoChaAng.Corner0Planes

            comp_pfl2 = ["PlaneFromLists::2", "PlaneFromLists_2", "PlaneFromLists2"]
            idx_origin_2 = _get_param(AD, comp_pfl2, "IndexOrigin", 0)
            idx_plane_2  = _get_param(AD, comp_pfl2, "IndexPlane", 0)

            idx_origin_2 = _to_list_safe(idx_origin_2)
            idx_plane_2  = _to_list_safe(idx_plane_2)

            (io2_list, ip2_list), L2 = _broadcast_n(idx_origin_2, idx_plane_2)

            builder2 = FTPlaneFromLists(wrap=True)
            BP2_list, OP2_list, RP2_list, LOG2_list = [], [], [], []
            for i in range(L2):
                BP, OP, RP, LG = builder2.build_plane(
                    origin_points_2,
                    base_planes_2,
                    io2_list[i],
                    ip2_list[i]
                )
                BP2_list.append(BP); OP2_list.append(OP); RP2_list.append(RP); LOG2_list.append(LG)

            self.PFL2_BasePlane    = BP2_list
            self.PFL2_OriginPoint  = OP2_list
            self.PFL2_ResultPlanes = RP2_list
            self.PFL2_Log          = LOG2_list

        except Exception as e:
            self.Log.append("[Step3][PlaneFromLists::2 ERROR] {}".format(e))
            traceback.print_exc()
            return

        # ---- 4) GeoAligner
        try:
            comp_ga = ["GeoAligner", "GeoAligner::1"]
            rotate_deg = _get_param(AD, comp_ga, "RotateDeg", 0)
            flip_x     = _get_param(AD, comp_ga, "FlipX", False)
            move_y     = _get_param(AD, comp_ga, "MoveY", 0)

            geo_in = self.QiAo_CutTimbers
            sp_in  = self.PFL2_ResultPlanes
            tp_in  = self.PFL1_ResultPlanes

            geo_list = _to_list_safe(geo_in)
            sp_list  = _to_list_safe(sp_in)
            tp_list  = _to_list_safe(tp_in)
            rd_list  = _to_list_safe(rotate_deg)
            my_list  = _to_list_safe(move_y)
            fx_list  = _to_list_safe(flip_x)

            (geo_b, sp_b, tp_b, rd_b, fx_b, my_b), Lg = _broadcast_n(
                geo_list, sp_list, tp_list, rd_list, fx_list, my_list
            )

            so_list, to_list_, xfm_list, moved_list = [], [], [], []
            for i in range(Lg):
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_b[i],
                    sp_b[i],
                    tp_b[i],
                    rotate_deg=rd_b[i],
                    flip_x=fx_b[i],
                    flip_y=False,
                    flip_z=False,
                    move_x=0,
                    move_y=my_b[i],
                    move_z=0,
                )
                so_list.append(SourceOut)
                to_list_.append(TargetOut)
                xfm_list.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                moved_list.append(MovedGeo)

            self.GA_SourceOut    = so_list
            self.GA_TargetOut    = to_list_
            self.GA_TransformOut = xfm_list
            self.GA_MovedGeo     = moved_list

        except Exception as e:
            self.Log.append("[Step3][GeoAligner ERROR] {}".format(e))
            traceback.print_exc()
            return

        # ---- 5) CutTimbersByTools
        try:
            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=False)

            timbers_in = self.FinalKeepBrep
            tools_in   = self.GA_MovedGeo
            tools_flat = _deep_flatten(tools_in)  # 避免嵌套树

            CutTimbers, FailTimbers, LogLines = cutter.cut(
                timbers=timbers_in,
                tools=tools_flat,
                keep_inside=False,
                debug=None
            )

            self.CutByTools_CutTimbers  = _deep_flatten(CutTimbers)
            self.CutByTools_FailTimbers = _deep_flatten(FailTimbers)
            self.CutByTools_Log         = LogLines

            # 最终输出（插昂构件）
            ct_flat = self.CutByTools_CutTimbers
            self.CutTimbers = ct_flat[0] if len(ct_flat) == 1 else ct_flat
            self.FailTimbers = self.CutByTools_FailTimbers

            if isinstance(LogLines, (list, tuple)):
                self.Log.extend([str(x) for x in LogLines])
            else:
                self.Log.append(str(LogLines))

            self.Log.append("Step3: OK (CutTimbersByTools 完成)")

        except Exception as e:
            self.Log.append("[Step3][CutTimbersByTools ERROR] {}".format(e))
            traceback.print_exc()
            return

    # -----------------------------------------------------
    # run
    # -----------------------------------------------------
    def run(self):
        self.step1_read_db()
        if self.AllDict_1 is None:
            self.Log.append("run: AllDict_1 为空，终止。")
            return self

        self.step2_chaang4pu()
        self.step3_qiao()
        return self


# ======================================================================
# GH Python 组件输出绑定区（开发模式）
# ======================================================================
if __name__ == "__main__":

    solver = ChaAng4PU_JiaoAngInLineWJiaoHuaGongSolver(DBPath, base_point, Refresh)
    solver.run()

    # --- 必要输出端 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- Step1 outputs ---
    All_1 = solver.All_1
    AllDict_1 = solver.AllDict_1
    DBLog_1 = solver.DBLog_1

    # --- Step2 inputs used ---
    base_point_used = solver.base_point
    ref_plane_mode = solver.ref_plane_mode
    OA = solver.OA
    OB = solver.OB
    BC = solver.BC
    CD = solver.CD
    thickness = solver.thickness
    GE = solver.GE
    tol = solver.tol
    offset_dist = solver.offset_dist
    use_qin = solver.use_qin

    # --- Step2 outputs (mirror ChaAng4Pu) ---
    out_chaang4pu = solver.out_chaang4pu

    O = solver.O; A = solver.A; B = solver.B; D = solver.D
    E = solver.E; F = solver.F; G = solver.G

    EU_line = solver.EU_line; EL_line = solver.EL_line; EF_line = solver.EF_line
    Edges = solver.Edges
    SectionPolyline = solver.SectionPolyline
    SectionCurve = solver.SectionCurve
    SectionBrep = solver.SectionBrep
    SectionCurve_In = solver.SectionCurve_In
    SectionCurve_Out = solver.SectionCurve_Out
    SolidBrep = solver.SolidBrep
    SolidFace_AE = solver.SolidFace_AE

    Plane_Main = solver.Plane_Main
    Plane_X = solver.Plane_X
    Plane_Y = solver.Plane_Y
    RefPlanes = solver.RefPlanes

    # Qin
    H = solver.H; I = solver.I; J = solver.J; K = solver.K; L = solver.L; N = solver.N
    D1 = solver.D1; D2 = solver.D2; H1 = solver.H1; H2 = solver.H2; N1 = solver.N1; N2 = solver.N2
    Arc_JLI = solver.Arc_JLI
    Arc_DNH = solver.Arc_DNH
    Arc_D1N1H1 = solver.Arc_D1N1H1
    Arc_D2N2H2 = solver.Arc_D2N2H2
    Arc_D1JD2 = solver.Arc_D1JD2
    Arc_H1IH2 = solver.Arc_H1IH2
    QinSurface = solver.QinSurface
    QinCutBreps = solver.QinCutBreps
    QinCutKeep = solver.QinCutKeep
    QinJoinBrep = solver.QinJoinBrep

    # PiZhu
    PiZhu_H = solver.PiZhu_H
    PiZhu_DH = solver.PiZhu_DH
    PiZhu_D1H1 = solver.PiZhu_D1H1
    PiZhu_D2H2 = solver.PiZhu_D2H2
    PiZhuPlane = solver.PiZhuPlane
    PiZhuCutBreps = solver.PiZhuCutBreps
    PiZhuCutKeep = solver.PiZhuCutKeep
    PiZhuJoinBrep = solver.PiZhuJoinBrep

    FinalKeepBrep = solver.FinalKeepBrep

    # --- Step3 developer outputs ---
    QiAo_Params = solver.QiAo_Params
    QiAo_CutTimbers = solver.QiAo_CutTimbers
    QiAo_FailTimbers = solver.QiAo_FailTimbers

    TimberBrep = solver.TimberBrep
    ToolBrep = solver.ToolBrep
    AlignedTool = solver.AlignedTool

    EdgeMidPoints = solver.EdgeMidPoints
    Corner0Planes = solver.Corner0Planes
    PFL1_ResultPlane = solver.PFL1_ResultPlane
    QiAo_FacePlane = solver.QiAo_FacePlane

    CutTimbers_QiAo = solver.CutTimbers_QiAo
    FailTimbers_QiAo = solver.FailTimbers_QiAo

    ChaAngPlane_PA = solver.ChaAngPlane_PA
    PtA = solver.PtA
    PtC = solver.PtC
    PtE = solver.PtE
    ChaAngSectionCurve = solver.ChaAngSectionCurve
    ChaAngCutterBrep = solver.ChaAngCutterBrep

    FaceList = solver.FaceList
    PointList = solver.PointList
    EdgeList = solver.EdgeList
    CenterPoint = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    FacePlaneList = solver.FacePlaneList
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = solver.FaceDirTags
    EdgeDirTags = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs

    # PlaneFromLists
    PFL1_BasePlane = solver.PFL1_BasePlane
    PFL1_OriginPoint = solver.PFL1_OriginPoint
    PFL1_ResultPlanes = solver.PFL1_ResultPlanes
    PFL1_Log = solver.PFL1_Log

    PFL2_BasePlane = solver.PFL2_BasePlane
    PFL2_OriginPoint = solver.PFL2_OriginPoint
    PFL2_ResultPlanes = solver.PFL2_ResultPlanes
    PFL2_Log = solver.PFL2_Log

    # GeoAligner
    GA_SourceOut = solver.GA_SourceOut
    GA_TargetOut = solver.GA_TargetOut
    GA_TransformOut = solver.GA_TransformOut
    GA_MovedGeo = solver.GA_MovedGeo

    # CutByTools
    CutByTools_CutTimbers = solver.CutByTools_CutTimbers
    CutByTools_FailTimbers = solver.CutByTools_FailTimbers
    CutByTools_Log = solver.CutByTools_Log


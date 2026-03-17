# -*- coding: utf-8 -*-
"""
DanGongComponentAssemblySolver (refactor: templates-from-dangong)

说明：
- 本文件以「DanGongComponentAssemblySolver.py」原始稳定实现为基准；
- 仅把“可复用工具/模板函数”抽到 yingzao.ancientArchi.archi_component_templates_dangong；
- 这里每个 step 尽量只做：取值 + 调模板/调用子 Solver。
"""

from __future__ import division

import Rhino.Geometry as rg  # type: ignore
import Grasshopper.Kernel.Types as ght  # type: ignore

from yingzao.ancientArchi import (  # type: ignore
    JiaoHuDou_dangongSolver,
    LingGongSolver,
    SanDouSolver,
    QiXinDouSolver,
    GeoAligner_xfm,
    build_timber_block_uniform,
)

from yingzao.ancientArchi.Temp.archi_component_templates import (  # type: ignore
    default_place_plane,
    read_puzuo_params,
    ensure_list,
    flatten_items,
    as_int, as_float, as_01,
    as_float_list,
    xform_plane,
    ft_plane_from_lists_broadcast,
    wrap_gh_transform,
    unwrap_transform,
    broadcast_lists,
    resolve_reference_plane,
)


__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.08-dangong-tpl-from-single"

# 兼容旧名：部分模块/旧重构版仍使用 make_reference_plane
make_reference_plane = resolve_reference_plane


class DanGongComponentAssemblySolver_ACT(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, IncludeSuFangLuoHanFang=False, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane if PlacePlane is not None else default_place_plane()
        self.Refresh = bool(Refresh)
        self.IncludeSuFangLuoHanFang = bool(IncludeSuFangLuoHanFang)
        self.ghenv = ghenv

        self.ComponentAssembly = []
        self.LogLines = []
        self.Log = ""

        # Step1
        self.Value = None
        self.All = None
        self.AllDict = {}

    # -----------------------------------------------------
    # Step1: 读取数据库
    # -----------------------------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库…")

        self.Value, self.All, self.AllDict, self.DBLog = read_puzuo_params(
            db_path=self.DBPath,
            type_code="DanGong",
            field="params_json",
            table="PuZuo",
            ghenv=self.ghenv,
        )

        self.LogLines.append("[DB] 数据库读取完成")
        self.LogLines.append("[DB] table=PuZuo type_code=DanGong field=params_json export_all=默认(True)")
        self.LogLines.append("[DB] All 条目数={}".format(len(self.All) if self.All else 0))
        self.LogLines.append("[DB] AllDict 条目数={}".format(len(self.AllDict) if self.AllDict else 0))
        self.LogLines.append("Step 1 完成：已读取 All 列表并转换为 AllDict。")

    # -----------------------------------------------------
    # Step2: 交互枓 + SVG1 对位到 PlacePlane
    # -----------------------------------------------------
    def step2_jiaohudou_svg1(self):
        self.LogLines.append("Step 2：交互枓 JiaoHuDou + SVG1 对位…")

        base_point = rg.Point3d(0, 0, 0)

        jhd = JiaoHuDou_dangongSolver(self.DBPath, base_point, self.Refresh)
        jhd.run()

        self.JHD_CutTimbers = getattr(jhd, "CutTimbers", None)
        self.JHD_FacePlaneList = getattr(jhd, "FacePlaneList", None)
        self.JHD_Log = getattr(jhd, "Log", "")

        src_idx = as_int(self.AllDict.get("SVG1_GA_JiaoHuDou__SourcePlane", 0), 0)
        rotate_deg = as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__RotateDeg", 0.0), 0.0)

        flipx = as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipX", 0), 0)
        flipy = as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipY", 0), 0)
        flipz = as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipZ", 0), 0)

        movex = as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveX", 0.0), 0.0)
        movey = as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveY", 0.0), 0.0)
        movez = as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveZ", 0.0), 0.0)

        sp_list = ensure_list(self.JHD_FacePlaneList)
        sp = sp_list[src_idx] if sp_list and src_idx < len(sp_list) else (sp_list[0] if sp_list else None)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.JHD_CutTimbers,
            sp,
            self.PlacePlane,
            rotate_deg=rotate_deg,
            flip_x=flipx, flip_y=flipy, flip_z=flipz,
            move_x=movex, move_y=movey, move_z=movez,
        )

        self.SVG1_SourceOut = so
        self.SVG1_TargetOut = to
        self.SVG1_TransformOut = wrap_gh_transform(xf)
        self.SVG1_MovedGeo = mg

        self.LogLines.append("[STEP2] JiaoHuDou_dangongSolver 完成：CutTimbers={}".format("OK" if self.JHD_CutTimbers else "None"))
        self.LogLines.append("[STEP2][SVG1] 对位完成：SourceIdx={} RotateDeg={} Flip=({},{},{}) Move=({},{},{})".format(
            src_idx, rotate_deg, flipx, flipy, flipz, movex, movey, movez
        ))

    # -----------------------------------------------------
    # Step3: 令栱 + SVG2
    # -----------------------------------------------------
    def step3_linggong_svg2(self):
        self.LogLines.append("Step 3：令栱 LingGong + SVG2 对位…")

        base_point = rg.Point3d(0, 0, 0)

        lg = LingGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
        lg = lg.run()

        self.LG_CutTimbers = getattr(lg, "CutTimbers", None)
        self.LG_FacePlaneList = getattr(lg, "FacePlaneList", None)
        self.LG_EdgeMidPoints = getattr(lg, "EdgeMidPoints", None)
        self.LG_Log = getattr(lg, "Log", "")

        src_idx = as_int(self.AllDict.get("SVG2_GA_LingGong__SourcePlane", 0), 0)
        tgt_idx = as_int(self.AllDict.get("SVG2_GA_LingGong__TargetPlane", 0), 0)
        rotate_deg = as_float(self.AllDict.get("SVG2_GA_LingGong__RotateDeg", 0.0), 0.0)
        flipz = as_01(self.AllDict.get("SVG2_GA_LingGong__FlipZ", 0), 0)
        movez = as_float(self.AllDict.get("SVG2_GA_LingGong__MoveZ", 0.0), 0.0)

        sp_list = ensure_list(self.LG_FacePlaneList)
        sp = sp_list[src_idx] if sp_list and src_idx < len(sp_list) else (sp_list[0] if sp_list else None)

        xf1 = unwrap_transform(self.SVG1_TransformOut)
        tp_list = [xform_plane(pl, xf1) for pl in ensure_list(self.JHD_FacePlaneList)]
        tp = tp_list[tgt_idx] if tp_list and tgt_idx < len(tp_list) else (tp_list[0] if tp_list else None)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.LG_CutTimbers,
            sp,
            tp,
            rotate_deg=rotate_deg,
            flip_x=0, flip_y=0, flip_z=flipz,
            move_x=0.0, move_y=0.0, move_z=movez,
        )

        self.SVG2_SourceOut = so
        self.SVG2_TargetOut = to
        self.SVG2_TransformOut = wrap_gh_transform(xf)
        self.SVG2_MovedGeo = mg

        self.LogLines.append("[STEP3] LingGongSolver 完成：CutTimbers={}".format("OK" if self.LG_CutTimbers else "None"))
        self.LogLines.append("[STEP3][SVG2] 对位完成：SourceIdx={} TargetIdx={} RotateDeg={} FlipZ={} MoveZ={}".format(
            src_idx, tgt_idx, rotate_deg, flipz, movez
        ))

    # -----------------------------------------------------
    # Step4: 散枓 + 齊心枓 + PFL + SVG3
    # -----------------------------------------------------
    def step4_sandou_qixindou_svg3(self):
        self.LogLines.append("Step 4：散枓 SanDou + 齊心枓 QiXinDou + PFL + SVG3…")

        base_point = rg.Point3d(0, 0, 0)

        sd = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        sd.run()
        self.SD_CutTimbers = getattr(sd, "CutTimbers", None)
        self.SD_EdgeMidPoints = getattr(sd, "EdgeMidPoints", None)
        self.SD_Corner0Planes = getattr(sd, "Corner0Planes", None)

        qx = QiXinDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        qx.run()
        self.QX_CutTimbers = getattr(qx, "CutTimbers", None)
        self.QX_FacePlaneList = getattr(qx, "FacePlaneList", None)

        # PFL1: SanDou edgeMid + corner0
        idxO1 = self.AllDict.get("PlaneFromLists_1__IndexOrigin", None)
        idxP1 = self.AllDict.get("PlaneFromLists_1__IndexPlane", None)
        wrap1 = bool(self.AllDict.get("PlaneFromLists_1__Wrap", True))
        self.PFL1_BasePlane, self.PFL1_OriginPoint, self.PFL1_ResultPlane, self.PFL1_LogLines = ft_plane_from_lists_broadcast(
            self.SD_EdgeMidPoints, self.SD_Corner0Planes, idxO1, idxP1, wrap=wrap1, tag="PFL1"
        )

        # PFL2: LingGong edgeMid + facePlaneList
        idxO2 = self.AllDict.get("PlaneFromLists_2__IndexOrigin", None)
        idxP2 = self.AllDict.get("PlaneFromLists_2__IndexPlane", None)
        wrap2 = bool(self.AllDict.get("PlaneFromLists_2__Wrap", True))
        self.PFL2_BasePlane, self.PFL2_OriginPoint, self.PFL2_ResultPlane, self.PFL2_LogLines = ft_plane_from_lists_broadcast(
            self.LG_EdgeMidPoints, self.LG_FacePlaneList, idxO2, idxP2, wrap=wrap2, tag="PFL2"
        )

        # SVG3: SanDou -> (PFL1 as source) to (PFL2 transformed as target)
        xf2 = unwrap_transform(self.SVG2_TransformOut)
        tp_sd = [xform_plane(pl, xf2) for pl in ensure_list(self.PFL2_ResultPlane)]

        rot_sd = as_float(self.AllDict.get("SVG3_GA_SanDou__RotateDeg", 0.0), 0.0)
        flipz_sd = as_01(self.AllDict.get("SVG3_GA_SanDou__FlipZ", 0), 0)
        movey_sd_list = as_float_list(self.AllDict.get("SVG3_GA_SanDou__MoveY", None), 0.0)

        geo_l = ensure_list(self.SD_CutTimbers)
        sp_l = ensure_list(self.PFL1_ResultPlane)
        tp_l = ensure_list(tp_sd)
        my_l = movey_sd_list if movey_sd_list else [0.0]

        (_blists, n) = broadcast_lists(geo_l, sp_l, tp_l, my_l)
        geo_b, sp_b, tp_b, my_b = _blists

        # 为了和 GH 输出端一致：把 SD 对位的中间结果也缓存为 list
        self.SVG3_SD_SourceOut = []
        self.SVG3_SD_TargetOut = []
        self.SVG3_SD_MovedGeo = []
        self.SVG3_SD_TransformOut = []
        for i in range(n):
            so, to, xf, mg = GeoAligner_xfm.align(
                geo_b[i], sp_b[i], tp_b[i],
                rotate_deg=rot_sd,
                flip_x=0, flip_y=0, flip_z=flipz_sd,
                move_x=0.0, move_y=my_b[i], move_z=0.0,
            )
            self.SVG3_SD_SourceOut.append(so)
            self.SVG3_SD_TargetOut.append(to)
            self.SVG3_SD_MovedGeo.append(mg)
            self.SVG3_SD_TransformOut.append(wrap_gh_transform(xf))

        # SVG3: QiXinDou 对位到 LingGong facePlaneList（经 SVG2 Transform）
        src_idx = as_int(self.AllDict.get("SVG3_GA_QiXinDou__SourcePlane", 0), 0)
        tgt_idx = as_int(self.AllDict.get("SVG3_GA_QiXinDou__TargetPlane", 0), 0)
        rot_qx = as_float(self.AllDict.get("SVG3_GA_QiXinDou__RotateDeg", 0.0), 0.0)
        flipx_qx = as_01(self.AllDict.get("SVG3_GA_QiXinDou__FlipX", 0), 0)

        sp_list = ensure_list(self.QX_FacePlaneList)
        sp_qx = sp_list[src_idx] if sp_list and src_idx < len(sp_list) else (sp_list[0] if sp_list else None)

        tp_raw = ensure_list(self.LG_FacePlaneList)
        tp_list = [xform_plane(pl, xf2) for pl in tp_raw]
        tp_qx = tp_list[tgt_idx] if tp_list and tgt_idx < len(tp_list) else (tp_list[0] if tp_list else None)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.QX_CutTimbers, sp_qx, tp_qx,
            rotate_deg=rot_qx, flip_x=flipx_qx, flip_y=0, flip_z=0,
            move_x=0.0, move_y=0.0, move_z=0.0,
        )
        self.SVG3_QX_SourceOut = so
        self.SVG3_QX_TargetOut = to
        self.SVG3_QX_MovedGeo = mg
        self.SVG3_QX_TransformOut = wrap_gh_transform(xf)

        self.LogLines.append("[STEP4] SanDou/QiXinDou 完成：SD={} QX={}".format(
            "OK" if self.SD_CutTimbers else "None",
            "OK" if self.QX_CutTimbers else "None",
        ))

    # -----------------------------------------------------
    # Step5: 素方羅漢方 + SVG4
    # -----------------------------------------------------
    def step5_sufang_luohan_svg4(self):
        self.LogLines.append("Step 5：叠级4-羅漢方/素方 SuFangLuoHanFang + SVG4 对位…")

        base_point = rg.Point3d(0.0, 0.0, 0.0)

        length_fen = as_float(self.AllDict.get("SuFangLuoHanFang__length_fen", 32.0), 32.0)
        width_fen  = as_float(self.AllDict.get("SuFangLuoHanFang__width_fen",  32.0), 32.0)
        height_fen = as_float(self.AllDict.get("SuFangLuoHanFang__height_fen", 20.0), 20.0)

        ref_plane = make_reference_plane("WorldXZ")

        (
            timber_brep,
            face_list,
            point_list,
            edge_list,
            center_pt,
            center_axis_lines,
            edge_mid_points,
            face_plane_list,
            corner0_planes,
            local_axes_plane,
            axis_x, axis_y, axis_z,
            face_tags, edge_tags, corner0_dirs,
            log_lines,
        ) = build_timber_block_uniform(length_fen, width_fen, height_fen, base_point, ref_plane)

        self.SFLHF_TimberBrep = timber_brep
        self.SFLHF_FacePlaneList = face_plane_list
        self.SFLHF_Log = log_lines

        src_idx = as_int(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__SourcePlane", 0), 0)
        sp_list = ensure_list(self.SFLHF_FacePlaneList)
        sp = sp_list[src_idx] if sp_list and src_idx < len(sp_list) else (sp_list[0] if sp_list else None)

        tgt_idx = as_int(self.AllDict.get("SVG3_GA_QiXinDou__TargetPlane", 0), 0)
        xf2 = unwrap_transform(self.SVG2_TransformOut)
        tp_list = [xform_plane(pl, xf2) for pl in ensure_list(self.LG_FacePlaneList)]
        tp = tp_list[tgt_idx] if tp_list and tgt_idx < len(tp_list) else (tp_list[0] if tp_list else None)

        rot = as_float(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__RotateDeg", 0.0), 0.0)
        flipx = as_01(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__FlipX", 0), 0)
        movez = as_float(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__MoveZ", 0.0), 0.0)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.SFLHF_TimberBrep, sp, tp,
            rotate_deg=rot,
            flip_x=flipx, flip_y=0, flip_z=0,
            move_x=0.0, move_y=0.0, move_z=movez,
        )
        self.SVG4_SFLHF_SourceOut = so
        self.SVG4_SFLHF_TargetOut = to
        self.SVG4_SFLHF_MovedGeo = mg
        self.SVG4_SFLHF_TransformOut = wrap_gh_transform(xf)

        self.LogLines.append("[STEP5] SuFangLuoHanFang 完成：TimberBrep={}".format("OK" if self.SFLHF_TimberBrep else "None"))

    # -----------------------------------------------------
    # Step6: 组合输出（关键：永远拍平）
    # -----------------------------------------------------
    def step6_assemble(self):
        self.LogLines.append("Step 6：组合输出 ComponentAssembly（list of items）…")

        parts = []
        flatten_items(getattr(self, "SVG1_MovedGeo", None), parts)
        flatten_items(getattr(self, "SVG2_MovedGeo", None), parts)
        flatten_items(getattr(self, "SVG3_SD_MovedGeo", None), parts)
        flatten_items(getattr(self, "SVG3_QX_MovedGeo", None), parts)

        if self.IncludeSuFangLuoHanFang:
            flatten_items(getattr(self, "SVG4_SFLHF_MovedGeo", None), parts)
            self.LogLines.append("[STEP6] IncludeSuFangLuoHanFang=True：已加入 SVG4_SFLHF_MovedGeo")
        else:
            self.LogLines.append("[STEP6] IncludeSuFangLuoHanFang=False：不加入 SVG4_SFLHF_MovedGeo")

        self.ComponentAssembly = parts
        self.LogLines.append("Step 6 完成：ComponentAssembly items={}".format(len(parts)))

    def run(self):
        if self.PlacePlane is None:
            self.PlacePlane = default_place_plane()

        self.step1_read_db()
        self.step2_jiaohudou_svg1()
        self.step3_linggong_svg2()
        self.step4_sandou_qixindou_svg3()
        self.step5_sufang_luohan_svg4()
        self.step6_assemble()

        # 合并日志
        try:
            self.LogLines.extend(ensure_list(getattr(self, "PFL1_LogLines", [])))
            self.LogLines.extend(ensure_list(getattr(self, "PFL2_LogLines", [])))
        except Exception:
            pass

        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GH Python 组件输出绑定区
# =========================================================

if __name__ == "__main__":

    try:
        _db = DBPath
    except Exception:
        _db = None

    try:
        _pp = PlacePlane
    except Exception:
        _pp = None
    if _pp is None:
        _pp = default_place_plane()

    try:
        _rf = Refresh
    except Exception:
        _rf = False

    try:
        _inc = IncludeSuFangLuoHanFang
    except Exception:
        _inc = False

    solver = DanGongComponentAssemblySolver_ACT(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        IncludeSuFangLuoHanFang=_inc,
        ghenv=ghenv
    )
    solver = solver.run()

    # --------- 最终成品 ---------
    ComponentAssembly = getattr(solver, "ComponentAssembly", None)
    Log = getattr(solver, "Log", None)

    # --------- Step 1：DB ---------
    Value = getattr(solver, "Value", None)
    All = getattr(solver, "All", None)
    AllDict = getattr(solver, "AllDict", None)
    DBLog = getattr(solver, "DBLog", None)

    # --------- Step 2：JiaoHuDou + SVG1 ---------
    JHD_CutTimbers = getattr(solver, "JHD_CutTimbers", None)
    JHD_FacePlaneList = getattr(solver, "JHD_FacePlaneList", None)
    JHD_Log = getattr(solver, "JHD_Log", None)

    SVG1_SourceOut = getattr(solver, "SVG1_SourceOut", None)
    SVG1_TargetOut = getattr(solver, "SVG1_TargetOut", None)
    SVG1_TransformOut = getattr(solver, "SVG1_TransformOut", None)
    SVG1_MovedGeo = getattr(solver, "SVG1_MovedGeo", None)

    # --------- Step 3：LingGong + SVG2 ---------
    LG_CutTimbers = getattr(solver, "LG_CutTimbers", None)
    LG_FacePlaneList = getattr(solver, "LG_FacePlaneList", None)
    LG_EdgeMidPoints = getattr(solver, "LG_EdgeMidPoints", None)
    LG_Log = getattr(solver, "LG_Log", None)

    SVG2_SourceOut = getattr(solver, "SVG2_SourceOut", None)
    SVG2_TargetOut = getattr(solver, "SVG2_TargetOut", None)
    SVG2_TransformOut = getattr(solver, "SVG2_TransformOut", None)
    SVG2_MovedGeo = getattr(solver, "SVG2_MovedGeo", None)

    # --------- Step 4：SanDou + QiXinDou + PFL1/PFL2 + SVG3 ---------
    SD_CutTimbers = getattr(solver, "SD_CutTimbers", None)
    SD_EdgeMidPoints = getattr(solver, "SD_EdgeMidPoints", None)
    SD_Corner0Planes = getattr(solver, "SD_Corner0Planes", None)

    QX_CutTimbers = getattr(solver, "QX_CutTimbers", None)
    QX_FacePlaneList = getattr(solver, "QX_FacePlaneList", None)

    PFL1_BasePlane = getattr(solver, "PFL1_BasePlane", None)
    PFL1_OriginPoint = getattr(solver, "PFL1_OriginPoint", None)
    PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
    PFL1_LogLines = getattr(solver, "PFL1_LogLines", None)

    PFL2_BasePlane = getattr(solver, "PFL2_BasePlane", None)
    PFL2_OriginPoint = getattr(solver, "PFL2_OriginPoint", None)
    PFL2_ResultPlane = getattr(solver, "PFL2_ResultPlane", None)
    PFL2_LogLines = getattr(solver, "PFL2_LogLines", None)

    SVG3_SD_SourceOut = getattr(solver, "SVG3_SD_SourceOut", None)
    SVG3_SD_TargetOut = getattr(solver, "SVG3_SD_TargetOut", None)
    SVG3_SD_TransformOut = getattr(solver, "SVG3_SD_TransformOut", None)
    SVG3_SD_MovedGeo = getattr(solver, "SVG3_SD_MovedGeo", None)

    SVG3_QX_SourceOut = getattr(solver, "SVG3_QX_SourceOut", None)
    SVG3_QX_TargetOut = getattr(solver, "SVG3_QX_TargetOut", None)
    SVG3_QX_TransformOut = getattr(solver, "SVG3_QX_TransformOut", None)
    SVG3_QX_MovedGeo = getattr(solver, "SVG3_QX_MovedGeo", None)

    # --------- Step 5：SuFangLuoHanFang + SVG4 ---------
    SFLHF_TimberBrep = getattr(solver, "SFLHF_TimberBrep", None)
    SFLHF_FacePlaneList = getattr(solver, "SFLHF_FacePlaneList", None)
    SFLHF_Log = getattr(solver, "SFLHF_Log", None)

    SVG4_SFLHF_SourceOut = getattr(solver, "SVG4_SFLHF_SourceOut", None)
    SVG4_SFLHF_TargetOut = getattr(solver, "SVG4_SFLHF_TargetOut", None)
    SVG4_SFLHF_TransformOut = getattr(solver, "SVG4_SFLHF_TransformOut", None)
    SVG4_SFLHF_MovedGeo = getattr(solver, "SVG4_SFLHF_MovedGeo", None)


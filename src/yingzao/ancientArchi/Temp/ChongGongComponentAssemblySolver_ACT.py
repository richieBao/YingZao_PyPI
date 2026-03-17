# -*- coding: utf-8 -*-
"""
ChongGongComponentAssemblySolver.py

【调整】Step 7 增加输入端参数 IncludeSuFangLuoHanFang（默认 False）
- True：将 VSG6_MovedGeo（羅漢方/素方对位后结果）加入 ComponentAssembly
- False：不加入（仍可在内部/输出端查看 VSG6_* 相关变量）

输入（新增）:
    IncludeSuFangLuoHanFang : bool
        是否把羅漢方/素方加入最终 ComponentAssembly
        Access: item
        TypeHint: bool
        Default: False
"""

from __future__ import print_function, division

import Rhino.Geometry as rg

from yingzao.ancientArchi import (
    JiaoHuDou_dangongSolver,
    GuaZiGongSolver,
    ManGongSolver,
    SanDouSolver,
    QiXinDouSolver,
    QIXIN_DOU_chonggongSolver,
    build_timber_block_uniform,
    GeoAligner_xfm,
)


# =========================================================
# 通用模板函数（来自 archi_component_templates_*）
# =========================================================

from yingzao.ancientArchi.Temp.archi_component_templates import (  # type: ignore
    default_place_plane,
    ensure_list,
    flatten_items,
    append_flat,
    as_int,
    as_float,
    as_float_or_list,
    as_01,
    as_01_or_list,
    as_bool,
    pick_by_index,
    xform_planes,
    ft_plane_from_lists_broadcast_wrap,
    geoalign_broadcast_wrap,
    wrap_gh_transform,
    unwrap_transform,
    read_puzuo_params,
    all_to_dict,
)


# （兼容旧名：尽量少改业务代码）
_default_place_plane = default_place_plane
_ensure_list = ensure_list
_flatten_items = flatten_items
_as_int = as_int
_as_float = as_float
_as_float_or_list = as_float_or_list
_as_01 = as_01
_as_01_or_list = as_01_or_list
_pick_by_index = pick_by_index
_xform_planes = xform_planes
_pfl_broadcast = ft_plane_from_lists_broadcast_wrap
_align_broadcast = geoalign_broadcast_wrap
_as_bool = as_bool

# =========================================================
# Solver 主类
# =========================================================

class ChongGongComponentAssemblySolver_ACT(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False,
                 IncludeSuFangLuoHanFang=False, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane if PlacePlane is not None else default_place_plane()
        self.Refresh = bool(Refresh)
        self.IncludeSuFangLuoHanFang = bool(IncludeSuFangLuoHanFang)
        self.ghenv = ghenv

        self.LogLines = []
        self.ComponentAssembly = []
        self.Log = ""

        # Step1 数据（必须保留）
        self.Value0 = None
        self.All0 = None
        self.AllDict0 = {}
        self.DBLog0 = None

    # -------------------------------
    # Step 1：读取数据库
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 params_json -> All / AllDict0 …")

        self.Value0, self.All0, self.AllDict0, self.DBLog0 = read_puzuo_params(
            self.DBPath,
            type_code="ChongGong",
            field="params_json",
            table="PuZuo",
            ghenv=self.ghenv,
        )

        self.LogLines.append("Step 1 完成：All items={} AllDict0 keys={}".format(
            len(_ensure_list(self.All0)), len(self.AllDict0.keys())
        ))

    # -------------------------------
    # Step 2：交互枓 + VSG1 对位
    # -------------------------------
    def step2_jiaohudou(self):
        self.LogLines.append("Step 2：叠级1-交互枓 JiaoHuDou + VSG1 对位…")

        base_point = rg.Point3d(0, 0, 0)
        jhd = JiaoHuDou_dangongSolver(self.DBPath, base_point, self.Refresh)
        jhd.run()

        self.JHD_All = getattr(jhd, "All", None)
        self.JHD_AllDict = getattr(jhd, "AllDict", None)
        self.JHD_Log = getattr(jhd, "Log", "")

        self.JHD_CutTimbers = getattr(jhd, "CutTimbers", None)
        self.JHD_FacePlaneList = getattr(jhd, "FacePlaneList", None)

        src_idx = _as_int(self.AllDict0.get("VSG1_GA_JiaoHuDou__SourcePlane", 0), 0)
        flipz = _as_01_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__FlipZ", 0), 0)

        rotate_deg = _as_float_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__RotateDeg", 0.0), 0.0)
        flipx = _as_01_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__FlipX", 0), 0)
        flipy = _as_01_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__FlipY", 0), 0)
        movex = _as_float_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__MoveX", 0.0), 0.0)
        movey = _as_float_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__MoveY", 0.0), 0.0)
        movez = _as_float_or_list(self.AllDict0.get("VSG1_GA_JiaoHuDou__MoveZ", 0.0), 0.0)

        sp = _pick_by_index(self.JHD_FacePlaneList, src_idx, None)
        tp = self.PlacePlane

        so, to, xf, mg = GeoAligner_xfm.align(
            self.JHD_CutTimbers, sp, tp,
            rotate_deg=rotate_deg,
            flip_x=flipx, flip_y=flipy, flip_z=flipz,
            move_x=movex, move_y=movey, move_z=movez,
        )

        self.VSG1_SourceOut = so
        self.VSG1_TargetOut = to
        self.VSG1_TransformOut = wrap_gh_transform(xf)
        self.VSG1_MovedGeo = mg

    # -------------------------------
    # Step 3：瓜子栱 + VSG2 对位
    # -------------------------------
    def step3_guazigong(self):
        self.LogLines.append("Step 3：叠级2-瓜子栱 GuaZiGong + VSG2 对位…")

        base_point = rg.Point3d(0, 0, 0)
        gg = GuaZiGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
        gg = gg.run()

        self.GG_All = getattr(gg, "All", None)
        self.GG_AllDict = getattr(gg, "AllDict", None)
        self.GG_Log = getattr(gg, "Log", "")

        self.GG_CutTimbers = getattr(gg, "CutTimbers", None)
        self.GG_FacePlaneList = getattr(gg, "FacePlaneList", None)
        self.GG_EdgeMidPoints = getattr(gg, "EdgeMidPoints", None)

        src_idx = _as_int(self.AllDict0.get("VSG2_GA_GuaZiGong__SourcePlane", 0), 0)

        rotate_deg = _as_float_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__RotateDeg", 0.0), 0.0)
        flipx = _as_01_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__FlipX", 0), 0)
        flipy = _as_01_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__FlipY", 0), 0)
        flipz = _as_01_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__FlipZ", 0), 0)
        movex = _as_float_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__MoveX", 0.0), 0.0)
        movey = _as_float_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__MoveY", 0.0), 0.0)
        movez = _as_float_or_list(self.AllDict0.get("VSG2_GA_GuaZiGong__MoveZ", 0.0), 0.0)

        sp = _pick_by_index(self.GG_FacePlaneList, src_idx, None)

        tgt_idx = _as_int(self.AllDict0.get("VSG2_GA_GuaZiGong__TargetPlane", 0), 0)
        xf1 = self.VSG1_TransformOut.Value if self.VSG1_TransformOut is not None else None
        jhd_planes_xf = _xform_planes(self.JHD_FacePlaneList, xf1)
        tp = _pick_by_index(jhd_planes_xf, tgt_idx, None)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.GG_CutTimbers, sp, tp,
            rotate_deg=rotate_deg,
            flip_x=flipx, flip_y=flipy, flip_z=flipz,
            move_x=movex, move_y=movey, move_z=movez,
        )

        self.VSG2_SourceOut = so
        self.VSG2_TargetOut = to
        self.VSG2_TransformOut = wrap_gh_transform(xf)
        self.VSG2_MovedGeo = mg

    # -------------------------------
    # Step 4：散枓 + 齊心枓 + PFL1/PFL2 + VSG3
    # -------------------------------
    def step4_sandou_qixindou(self):
        self.LogLines.append("Step 4：叠级3-散枓/齊心枓 + PFL1/PFL2 + VSG3 对位…")

        base_point = rg.Point3d(0, 0, 0)

        sd = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        sd.run()
        self.SD_CutTimbers = getattr(sd, "CutTimbers", None)
        self.SD_EdgeMidPoints = getattr(sd, "EdgeMidPoints", None)
        self.SD_Corner0Planes = getattr(sd, "Corner0Planes", None)
        self.SD_FacePlaneList = getattr(sd, "FacePlaneList", None)

        # QiXinDouSolver-->QIXIN_DOU_chonggongSolver
        qx = QIXIN_DOU_chonggongSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh) # , ghenv=self.ghenv
        qx.run()
        self.QX_CutTimbers = getattr(qx, "CutTimbers", None)
        self.QX_FacePlaneList = getattr(qx, "FacePlaneList", None)

        idx_o1 = self.AllDict0.get("PlaneFromLists_1__IndexOrigin", 0)
        idx_p1 = self.AllDict0.get("PlaneFromLists_1__IndexPlane", 0)
        wrap1 = self.AllDict0.get("PlaneFromLists_1__Wrap", True)
        self.PFL1_BasePlane, self.PFL1_OriginPoint, self.PFL1_ResultPlane, self.PFL1_Log = _pfl_broadcast(
            origin_points=_ensure_list(self.SD_EdgeMidPoints),
            base_planes=_ensure_list(self.SD_Corner0Planes),
            index_origin=idx_o1,
            index_plane=idx_p1,
            wrap=bool(wrap1)
        )

        idx_o2 = self.AllDict0.get("PlaneFromLists_2__IndexOrigin", 0)
        idx_p2 = self.AllDict0.get("PlaneFromLists_2__IndexPlane", 0)
        wrap2 = self.AllDict0.get("PlaneFromLists_2__Wrap", True)

        origin_pts_2 = _ensure_list(getattr(self, "GG_EdgeMidPoints", None))
        if not origin_pts_2:
            try:
                origin_pts_2 = [p.Origin for p in _ensure_list(self.GG_FacePlaneList)]
            except:
                origin_pts_2 = []

        self.PFL2_BasePlane, self.PFL2_OriginPoint, self.PFL2_ResultPlane, self.PFL2_Log = _pfl_broadcast(
            origin_points=origin_pts_2,
            base_planes=_ensure_list(self.GG_FacePlaneList),
            index_origin=idx_o2,
            index_plane=idx_p2,
            wrap=bool(wrap2)
        )

        rotate_sd = _as_float_or_list(self.AllDict0.get("VSG3_GA_SanDou__RotateDeg", 0.0), 0.0)
        flipx_sd = _as_01_or_list(self.AllDict0.get("VSG3_GA_SanDou__FlipX", 0), 0)
        flipy_sd = _as_01_or_list(self.AllDict0.get("VSG3_GA_SanDou__FlipY", 0), 0)
        flipz_sd = _as_01_or_list(self.AllDict0.get("VSG3_GA_SanDou__FlipZ", 0), 0)
        movex_sd = _as_float_or_list(self.AllDict0.get("VSG3_GA_SanDou__MoveX", 0.0), 0.0)

        # ★修复：movey_sd 应该允许多值（例如 [-12, 12]）
        movey_sd = _as_float_or_list(self.AllDict0.get("VSG3_GA_SanDou__MoveY", 0.0), 0.0)

        movez_sd = _as_float_or_list(self.AllDict0.get("VSG3_GA_SanDou__MoveZ", 0.0), 0.0)

        xf2 = self.VSG2_TransformOut.Value if self.VSG2_TransformOut is not None else None
        tp_sd_list = _xform_planes(self.PFL2_ResultPlane, xf2)

        so_list, to_list, xf_list, mg_list = _align_broadcast(
            Geo=self.SD_CutTimbers,
            SourcePlane=self.PFL1_ResultPlane,
            TargetPlane=tp_sd_list,
            rotate_deg=rotate_sd,
            flip_x=flipx_sd,
            flip_y=flipy_sd,
            flip_z=flipz_sd,
            move_x=movex_sd,
            move_y=movey_sd,
            move_z=movez_sd,
        )
        self.VSG3_SD_MovedGeo = mg_list

        src_idx_qx = _as_int(self.AllDict0.get("VSG3_GA_QiXinDou__SourcePlane", 0), 0)
        tgt_idx_qx = _as_int(self.AllDict0.get("VSG3_GA_QiXinDou__TargetPlane", 0), 0)
        rotate_qx = _as_float(self.AllDict0.get("VSG3_GA_QiXinDou__RotateDeg", 0.0), 0.0)
        flipx_qx = _as_01(self.AllDict0.get("VSG3_GA_QiXinDou__FlipX", 0), 0)

        sp_qx = _pick_by_index(self.QX_FacePlaneList, src_idx_qx, None)
        gg_planes_xf = _xform_planes(self.GG_FacePlaneList, xf2)
        tp_qx = _pick_by_index(gg_planes_xf, tgt_idx_qx, None)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.QX_CutTimbers, sp_qx, tp_qx,
            rotate_deg=rotate_qx,
            flip_x=flipx_qx,
            flip_y=_as_01(self.AllDict0.get("VSG3_GA_QiXinDou__FlipY", 0), 0),
            flip_z=_as_01(self.AllDict0.get("VSG3_GA_QiXinDou__FlipZ", 0), 0),
            move_x=_as_float(self.AllDict0.get("VSG3_GA_QiXinDou__MoveX", 0.0), 0.0),
            move_y=_as_float(self.AllDict0.get("VSG3_GA_QiXinDou__MoveY", 0.0), 0.0),
            move_z=_as_float(self.AllDict0.get("VSG3_GA_QiXinDou__MoveZ", 0.0), 0.0),
        )
        self.VSG3_QX_MovedGeo = mg
        self.VSG3_QX_TargetPlane = tp_qx  # 供后续 VSG4 / VSG6 复用

    # -------------------------------
    # Step 5：慢栱 + VSG4 对位
    # -------------------------------
    def step5_mangong(self):
        self.LogLines.append("Step 5：叠级4-慢栱 ManGong + VSG4 对位…")

        base_point = rg.Point3d(0, 0, 0)
        mg = ManGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
        mg = mg.run()

        self.MG_CutTimbers = getattr(mg, "CutTimbers", None)
        self.MG_FacePlaneList = getattr(mg, "FacePlaneList", None)
        self.MG_EdgeMidPoints = getattr(mg, "EdgeMidPoints", None)

        src_idx = _as_int(self.AllDict0.get("VSG4_GA_ManGong__SourcePlane", 0), 0)
        sp = _pick_by_index(self.MG_FacePlaneList, src_idx, None)
        tp = getattr(self, "VSG3_QX_TargetPlane", None)

        so, to, xf, moved = GeoAligner_xfm.align(
            self.MG_CutTimbers, sp, tp,
            rotate_deg=_as_float_or_list(self.AllDict0.get("VSG4_GA_ManGong__RotateDeg", 0.0), 0.0),
            flip_x=_as_01_or_list(self.AllDict0.get("VSG4_GA_ManGong__FlipX", 0), 0),
            flip_y=_as_01_or_list(self.AllDict0.get("VSG4_GA_ManGong__FlipY", 0), 0),
            flip_z=_as_01_or_list(self.AllDict0.get("VSG4_GA_ManGong__FlipZ", 0), 0),
            move_x=_as_float_or_list(self.AllDict0.get("VSG4_GA_ManGong__MoveX", 0.0), 0.0),
            move_y=_as_float_or_list(self.AllDict0.get("VSG4_GA_ManGong__MoveY", 0.0), 0.0),
            move_z=_as_float_or_list(self.AllDict0.get("VSG4_GA_ManGong__MoveZ", 0.0), 0.0),
        )

        self.VSG4_TransformOut = wrap_gh_transform(xf)
        self.VSG4_MovedGeo = moved

# -------------------------------
    # Step 6：散枓 + 齊心枓（第二层）+ PlaneFromLists::3/4 + VSG5
    # -------------------------------
    def step6_sandou_qixindou_2(self):
        self.LogLines.append("Step 6：叠级5-散枓/齊心枓 + PFL3/PFL4 + VSG5 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # --- SanDou（二次） ---
        sd2 = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        sd2.run()

        self.SD2_All = getattr(sd2, "All", None)
        self.SD2_AllDict = getattr(sd2, "AllDict", None)
        self.SD2_Log = getattr(sd2, "Log", "")

        self.SD2_CutTimbers = getattr(sd2, "CutTimbers", None)
        self.SD2_EdgeMidPoints = getattr(sd2, "EdgeMidPoints", None)
        self.SD2_Corner0Planes = getattr(sd2, "Corner0Planes", None)

        # --- QiXinDou（二次） ---
        qx2 = QiXinDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        qx2.run()

        self.QX2_All = getattr(qx2, "All", None)
        self.QX2_AllDict = getattr(qx2, "AllDict", None)
        self.QX2_Log = getattr(qx2, "Log", "")

        self.QX2_CutTimbers = getattr(qx2, "CutTimbers", None)
        self.QX2_FacePlaneList = getattr(qx2, "FacePlaneList", None)

        # --- PlaneFromLists::3（OriginPoints=SD2.EdgeMidPoints, BasePlanes=SD2.Corner0Planes）---
        idx_o3 = self.AllDict0.get("PlaneFromLists_3__IndexOrigin", 0)
        idx_p3 = self.AllDict0.get("PlaneFromLists_3__IndexPlane", 0)
        wrap3 = self.AllDict0.get("PlaneFromLists_3__Wrap", True)

        self.PFL3_BasePlane, self.PFL3_OriginPoint, self.PFL3_ResultPlane, self.PFL3_Log = _pfl_broadcast(
            origin_points=_ensure_list(self.SD2_EdgeMidPoints),
            base_planes=_ensure_list(self.SD2_Corner0Planes),
            index_origin=idx_o3,
            index_plane=idx_p3,
            wrap=bool(wrap3)
        )

        # --- PlaneFromLists::4（OriginPoints=MG.EdgeMidPoints, BasePlanes=MG.FacePlaneList）---
        idx_o4 = self.AllDict0.get("PlaneFromLists_4__IndexOrigin", 0)
        idx_p4 = self.AllDict0.get("PlaneFromLists_4__IndexPlane", 0)
        wrap4 = self.AllDict0.get("PlaneFromLists_4__Wrap", True)

        origin_pts_4 = _ensure_list(getattr(self, "MG_EdgeMidPoints", None))
        if not origin_pts_4:
            try:
                origin_pts_4 = [p.Origin for p in _ensure_list(self.MG_FacePlaneList)]
            except:
                origin_pts_4 = []

        self.PFL4_BasePlane, self.PFL4_OriginPoint, self.PFL4_ResultPlane, self.PFL4_Log = _pfl_broadcast(
            origin_points=origin_pts_4,
            base_planes=_ensure_list(self.MG_FacePlaneList),
            index_origin=idx_o4,
            index_plane=idx_p4,
            wrap=bool(wrap4)
        )

        # --- VSG5_GA_SanDou（二次）---
        rotate_sd = _as_float_or_list(self.AllDict0.get("VSG5_GA_SanDou__RotateDeg", 0.0), 0.0)
        flipx_sd = _as_01_or_list(self.AllDict0.get("VSG5_GA_SanDou__FlipX", 0), 0)
        flipy_sd = _as_01_or_list(self.AllDict0.get("VSG5_GA_SanDou__FlipY", 0), 0)
        flipz_sd = _as_01_or_list(self.AllDict0.get("VSG5_GA_SanDou__FlipZ", 0), 0)
        movex_sd = _as_float_or_list(self.AllDict0.get("VSG5_GA_SanDou__MoveX", 0.0), 0.0)
        movey_sd = _as_float_or_list(self.AllDict0.get("VSG5_GA_SanDou__MoveY", 0.0), 0.0)
        movez_sd = _as_float_or_list(self.AllDict0.get("VSG5_GA_SanDou__MoveZ", 0.0), 0.0)

        xf4 = self.VSG4_TransformOut.Value if self.VSG4_TransformOut is not None else None
        tp_sd_list = _xform_planes(self.PFL4_ResultPlane, xf4)

        so_list, to_list, xf_list, mg_list = _align_broadcast(
            Geo=self.SD2_CutTimbers,
            SourcePlane=self.PFL3_ResultPlane,
            TargetPlane=tp_sd_list,
            rotate_deg=rotate_sd,
            flip_x=flipx_sd,
            flip_y=flipy_sd,
            flip_z=flipz_sd,
            move_x=movex_sd,
            move_y=movey_sd,
            move_z=movez_sd,
        )

        self.VSG5_SD_SourceOut = so_list
        self.VSG5_SD_TargetOut = to_list
        self.VSG5_SD_TransformOut = [wrap_gh_transform(xf) for xf in xf_list]
        self.VSG5_SD_MovedGeo = mg_list

        # --- VSG5_GA_QiXinDou（二次）---
        src_idx_qx = _as_int(self.AllDict0.get("VSG5_GA_QiXinDou__SourcePlane", 0), 0)
        tgt_idx_qx = _as_int(self.AllDict0.get("VSG5_GA_QiXinDou__TargetPlane", 0), 0)

        rotate_qx = _as_float_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__RotateDeg", 0.0), 0.0)
        flipx_qx = _as_01_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__FlipX", 0), 0)
        flipy_qx = _as_01_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__FlipY", 0), 0)
        flipz_qx = _as_01_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__FlipZ", 0), 0)
        movex_qx = _as_float_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__MoveX", 0.0), 0.0)
        movey_qx = _as_float_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__MoveY", 0.0), 0.0)
        movez_qx = _as_float_or_list(self.AllDict0.get("VSG5_GA_QiXinDou__MoveZ", 0.0), 0.0)

        sp_qx = _pick_by_index(self.QX2_FacePlaneList, src_idx_qx, None)

        mg_planes_xf = _xform_planes(self.MG_FacePlaneList, xf4)
        tp_qx = _pick_by_index(mg_planes_xf, tgt_idx_qx, None)

        so, to, xf, mg_geo = GeoAligner_xfm.align(
            self.QX2_CutTimbers,
            sp_qx,
            tp_qx,
            rotate_deg=rotate_qx,
            flip_x=flipx_qx,
            flip_y=flipy_qx,
            flip_z=flipz_qx,
            move_x=movex_qx,
            move_y=movey_qx,
            move_z=movez_qx,
            )

        self.VSG5_QX_SourceOut = so
        self.VSG5_QX_TargetOut = to
        self.VSG5_QX_TransformOut = wrap_gh_transform(xf)
        self.VSG5_QX_MovedGeo = mg_geo
        self.VSG5_QX_TargetPlane = tp_qx

        self.LogLines.append("[STEP6][PFL3] IndexOrigin={} IndexPlane={} -> ResultPlane count={}".format(
            idx_o3, idx_p3, len(_ensure_list(self.PFL3_ResultPlane))
        ))
        self.LogLines.append("[STEP6][PFL4] IndexOrigin={} IndexPlane={} -> ResultPlane count={}".format(
            idx_o4, idx_p4, len(_ensure_list(self.PFL4_ResultPlane))
        ))
        self.LogLines.append("[STEP6][VSG5_SD] items={}".format(len(_ensure_list(self.VSG5_SD_MovedGeo))))
        self.LogLines.append("[STEP6][VSG5_QX] TransformOut={}".format("OK" if xf is not None else "None"))


    # -------------------------------
    # Step 7：SuFangLuoHanFang + VSG6 对位
    # -------------------------------
    def step7_sufang_luohan(self):
        self.LogLines.append("Step 7：叠级6-羅漢方/素方 SuFangLuoHanFang + VSG6 对位…")

        length_fen = _as_float(self.AllDict0.get("SuFangLuoHanFang__length_fen", 32.0), 32.0)
        width_fen  = _as_float(self.AllDict0.get("SuFangLuoHanFang__width_fen", 32.0), 32.0)
        height_fen = _as_float(self.AllDict0.get("SuFangLuoHanFang__height_fen", 20.0), 20.0)

        base_point = rg.Point3d(0.0, 0.0, 0.0)

        # RhinoCommon 没有 WorldXZ；按 GH 的 XZ Plane 构造：
        # X=(1,0,0), Y=(0,0,1) => Z=X×Y=(0,-1,0)
        reference_plane = rg.Plane(
            rg.Point3d(0.0, 0.0, 0.0),
            rg.Vector3d(1.0, 0.0, 0.0),
            rg.Vector3d(0.0, 0.0, 1.0),
        )

        try:
            (
                timber_brep,
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines,
            ) = build_timber_block_uniform(
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
            )

            self.SF_TimberBrep = timber_brep
            self.SF_FacePlaneList = face_planes
            self.SF_Log = log_lines

        except Exception as e:
            self.SF_TimberBrep = None
            self.SF_FacePlaneList = []
            self.SF_Log = ["错误: {}".format(e)]

        src_idx = _as_int(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__SourcePlane", 0), 0)

        sp = _pick_by_index(self.SF_FacePlaneList, src_idx, None)

        # TargetPlane：优先用 VSG5_QX_TargetPlane，否则回退 VSG3_QX_TargetPlane
        tp = getattr(self, "VSG5_QX_TargetPlane", None)
        if tp is None:
            tp = getattr(self, "VSG3_QX_TargetPlane", None)

        so, to, xf, moved_geo = GeoAligner_xfm.align(
            self.SF_TimberBrep,
            sp,
            tp,
            rotate_deg=_as_float_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__RotateDeg", 0.0), 0.0),
            flip_x=_as_01_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipX", 0), 0),
            flip_y=_as_01_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipY", 0), 0),
            flip_z=_as_01_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipZ", 0), 0),
            move_x=_as_float_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveX", 0.0), 0.0),
            move_y=_as_float_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveY", 0.0), 0.0),
            move_z=_as_float_or_list(self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveZ", 0.0), 0.0),
        )

        self.VSG6_SourceOut = so
        self.VSG6_TargetOut = to
        self.VSG6_TransformOut = wrap_gh_transform(xf)
        self.VSG6_MovedGeo = moved_geo

    # -------------------------------
    # Step 8：组合输出（根据 IncludeSuFangLuoHanFang 控制是否加入 VSG6）
    # -------------------------------
    def step8_assemble(self):
        self.LogLines.append("Step 8：组合输出 ComponentAssembly（含可选羅漢方/素方）…")

        parts = []
        _flatten_items(getattr(self, "VSG1_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG2_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG3_SD_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG3_QX_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG4_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG5_SD_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG5_QX_MovedGeo", None), parts)

        if self.IncludeSuFangLuoHanFang:
            _flatten_items(getattr(self, "VSG6_MovedGeo", None), parts)
            self.LogLines.append("[ASSEMBLY] IncludeSuFangLuoHanFang=True：已加入 VSG6_MovedGeo")
        else:
            self.LogLines.append("[ASSEMBLY] IncludeSuFangLuoHanFang=False：不加入 VSG6_MovedGeo")

        self.ComponentAssembly = parts
        self.LogLines.append("Step 8 完成：ComponentAssembly items={}".format(len(parts)))

    # -------------------------------
    # run
    # -------------------------------
    def run(self):
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self.step1_read_db()
        self.step2_jiaohudou()
        self.step3_guazigong()
        self.step4_sandou_qixindou()
        self.step5_mangong()

        # 保持你当前文件中已有的 step6 / step7 / step8 完整实现逻辑
        self.step6_sandou_qixindou_2()
        self.step7_sufang_luohan()
        self.step8_assemble()

        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GhPython 组件输出绑定区
# =========================================================

if __name__ == "__main__":

    try:
        _db = DBPath
    except:
        _db = None

    try:
        _pp = PlacePlane
    except:
        _pp = None

    try:
        _rf = Refresh
    except:
        _rf = False

    # 【新增输入端】IncludeSuFangLuoHanFang（默认 False）
    try:
        _inc_sf = IncludeSuFangLuoHanFang
    except:
        _inc_sf = False

    solver = ChongGongComponentAssemblySolver_ACT(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        IncludeSuFangLuoHanFang=_inc_sf,
        ghenv=ghenv
    )
    solver.run()

    # --------- 最终成品 ---------
    ComponentAssembly = getattr(solver, "ComponentAssembly", None)
    Log = getattr(solver, "Log", None)

    # （其余内部输出端绑定区，保持你当前文件里完整列出的那一套即可，不需要改名）

    # --------- Step 1 ---------
    Value0 = getattr(solver, "Value0", None)
    All0 = getattr(solver, "All0", None)
    AllDict0 = getattr(solver, "AllDict0", None)
    DBLog0 = getattr(solver, "DBLog0", None)

    # --------- Step 2：JiaoHuDou + VSG1 ---------
    JHD_All = getattr(solver, "JHD_All", None)
    JHD_AllDict = getattr(solver, "JHD_AllDict", None)
    JHD_Log = getattr(solver, "JHD_Log", None)

    JHD_CutTimbers = getattr(solver, "JHD_CutTimbers", None)
    JHD_FacePlaneList = getattr(solver, "JHD_FacePlaneList", None)

    VSG1_SourceOut = getattr(solver, "VSG1_SourceOut", None)
    VSG1_TargetOut = getattr(solver, "VSG1_TargetOut", None)
    VSG1_TransformOut = getattr(solver, "VSG1_TransformOut", None)
    VSG1_MovedGeo = getattr(solver, "VSG1_MovedGeo", None)

    # --------- Step 3：GuaZiGong + VSG2 ---------
    GG_All = getattr(solver, "GG_All", None)
    GG_AllDict = getattr(solver, "GG_AllDict", None)
    GG_Log = getattr(solver, "GG_Log", None)

    GG_CutTimbers = getattr(solver, "GG_CutTimbers", None)
    GG_FacePlaneList = getattr(solver, "GG_FacePlaneList", None)

    VSG2_SourceOut = getattr(solver, "VSG2_SourceOut", None)
    VSG2_TargetOut = getattr(solver, "VSG2_TargetOut", None)
    VSG2_TransformOut = getattr(solver, "VSG2_TransformOut", None)
    VSG2_MovedGeo = getattr(solver, "VSG2_MovedGeo", None)

    # --------- Step 4：SanDou + QiXinDou + PFL + VSG3 ---------
    SD_All = getattr(solver, "SD_All", None)
    SD_AllDict = getattr(solver, "SD_AllDict", None)
    SD_Log = getattr(solver, "SD_Log", None)

    SD_CutTimbers = getattr(solver, "SD_CutTimbers", None)
    SD_EdgeMidPoints = getattr(solver, "SD_EdgeMidPoints", None)
    SD_Corner0Planes = getattr(solver, "SD_Corner0Planes", None)
    SD_FacePlaneList = getattr(solver, "SD_FacePlaneList", None)

    QX_All = getattr(solver, "QX_All", None)
    QX_AllDict = getattr(solver, "QX_AllDict", None)
    QX_Log = getattr(solver, "QX_Log", None)

    QX_CutTimbers = getattr(solver, "QX_CutTimbers", None)
    QX_FacePlaneList = getattr(solver, "QX_FacePlaneList", None)

    PFL1_BasePlane = getattr(solver, "PFL1_BasePlane", None)
    PFL1_OriginPoint = getattr(solver, "PFL1_OriginPoint", None)
    PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
    PFL1_Log = getattr(solver, "PFL1_Log", None)

    PFL2_BasePlane = getattr(solver, "PFL2_BasePlane", None)
    PFL2_OriginPoint = getattr(solver, "PFL2_OriginPoint", None)
    PFL2_ResultPlane = getattr(solver, "PFL2_ResultPlane", None)
    PFL2_Log = getattr(solver, "PFL2_Log", None)

    VSG3_SD_SourceOut = getattr(solver, "VSG3_SD_SourceOut", None)
    VSG3_SD_TargetOut = getattr(solver, "VSG3_SD_TargetOut", None)
    VSG3_SD_TransformOut = getattr(solver, "VSG3_SD_TransformOut", None)
    VSG3_SD_MovedGeo = getattr(solver, "VSG3_SD_MovedGeo", None)

    VSG3_QX_SourceOut = getattr(solver, "VSG3_QX_SourceOut", None)
    VSG3_QX_TargetOut = getattr(solver, "VSG3_QX_TargetOut", None)
    VSG3_QX_TransformOut = getattr(solver, "VSG3_QX_TransformOut", None)
    VSG3_QX_MovedGeo = getattr(solver, "VSG3_QX_MovedGeo", None)

    # --------- Step 5：ManGong + VSG4 ---------
    MG_All = getattr(solver, "MG_All", None)
    MG_AllDict = getattr(solver, "MG_AllDict", None)
    MG_Log = getattr(solver, "MG_Log", None)

    MG_CutTimbers = getattr(solver, "MG_CutTimbers", None)
    MG_FacePlaneList = getattr(solver, "MG_FacePlaneList", None)
    MG_EdgeMidPoints = getattr(solver, "MG_EdgeMidPoints", None)

    VSG4_SourceOut = getattr(solver, "VSG4_SourceOut", None)
    VSG4_TargetOut = getattr(solver, "VSG4_TargetOut", None)
    VSG4_TransformOut = getattr(solver, "VSG4_TransformOut", None)
    VSG4_MovedGeo = getattr(solver, "VSG4_MovedGeo", None)

    # --------- Step 6：SanDou/QiXinDou（二次）+ PFL3/PFL4 + VSG5 ---------
    SD2_All = getattr(solver, "SD2_All", None)
    SD2_AllDict = getattr(solver, "SD2_AllDict", None)
    SD2_Log = getattr(solver, "SD2_Log", None)
    SD2_CutTimbers = getattr(solver, "SD2_CutTimbers", None)
    SD2_EdgeMidPoints = getattr(solver, "SD2_EdgeMidPoints", None)
    SD2_Corner0Planes = getattr(solver, "SD2_Corner0Planes", None)

    QX2_All = getattr(solver, "QX2_All", None)
    QX2_AllDict = getattr(solver, "QX2_AllDict", None)
    QX2_Log = getattr(solver, "QX2_Log", None)
    QX2_CutTimbers = getattr(solver, "QX2_CutTimbers", None)
    QX2_FacePlaneList = getattr(solver, "QX2_FacePlaneList", None)

    PFL3_BasePlane = getattr(solver, "PFL3_BasePlane", None)
    PFL3_OriginPoint = getattr(solver, "PFL3_OriginPoint", None)
    PFL3_ResultPlane = getattr(solver, "PFL3_ResultPlane", None)
    PFL3_Log = getattr(solver, "PFL3_Log", None)

    PFL4_BasePlane = getattr(solver, "PFL4_BasePlane", None)
    PFL4_OriginPoint = getattr(solver, "PFL4_OriginPoint", None)
    PFL4_ResultPlane = getattr(solver, "PFL4_ResultPlane", None)
    PFL4_Log = getattr(solver, "PFL4_Log", None)

    VSG5_SD_SourceOut = getattr(solver, "VSG5_SD_SourceOut", None)
    VSG5_SD_TargetOut = getattr(solver, "VSG5_SD_TargetOut", None)
    VSG5_SD_TransformOut = getattr(solver, "VSG5_SD_TransformOut", None)
    VSG5_SD_MovedGeo = getattr(solver, "VSG5_SD_MovedGeo", None)

    VSG5_QX_SourceOut = getattr(solver, "VSG5_QX_SourceOut", None)
    VSG5_QX_TargetOut = getattr(solver, "VSG5_QX_TargetOut", None)
    VSG5_QX_TransformOut = getattr(solver, "VSG5_QX_TransformOut", None)
    VSG5_QX_MovedGeo = getattr(solver, "VSG5_QX_MovedGeo", None)

    # --------- Step 7：SuFangLuoHanFang + VSG6 ---------
    SF_TimberBrep = getattr(solver, "SF_TimberBrep", None)
    SF_FacePlaneList = getattr(solver, "SF_FacePlaneList", None)
    SF_Log = getattr(solver, "SF_Log", None)

    VSG6_SourceOut = getattr(solver, "VSG6_SourceOut", None)
    VSG6_TargetOut = getattr(solver, "VSG6_TargetOut", None)
    VSG6_TransformOut = getattr(solver, "VSG6_TransformOut", None)
    VSG6_MovedGeo = getattr(solver, "VSG6_MovedGeo", None)

    # --------- 最终成品 ---------
    ComponentAssembly = getattr(solver, "ComponentAssembly", None)

    # --------- 全局日志 ---------
    Log = getattr(solver, "Log", None)

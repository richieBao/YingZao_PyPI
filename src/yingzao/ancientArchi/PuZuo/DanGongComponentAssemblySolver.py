# -*- coding: utf-8 -*-
"""
DanGongSolver.py

将「单栱 DanGong」的多个 GhPython 自定义组件（枓/栱/对位等）串联为一个单一 GhPython 组件脚本。

【输入（GhPython 建议设置）】
    DBPath : str
        Access: item
        TypeHint: str
        SQLite 数据库路径（Song-styleArchi.db）

    PlacePlane : rg.Plane
        Access: item
        TypeHint: Plane
        放置参考平面（默认 GH 的 XY Plane；默认原点(100,100,0)）

    Refresh : bool
        Access: item
        TypeHint: bool
        刷新开关（重读数据库/重算）

    IncludeSuFangLuoHanFang : bool
        Access: item
        TypeHint: bool
        是否将「叠级4-羅漢方/素方」加入 ComponentAssembly（默认 False）

【输出（GhPython 建议设置）】
    ComponentAssembly : object
        Access: list
        TypeHint: object
        最终组合体（必须输出 list；每个元素为几何 item，禁止 list 套 list）

    Log : str
        Access: item
        TypeHint: str
        全局日志

【开发模式输出】
    在 GH Python 组件中按需新增同名输出端口，即可查看 solver 的内部成员变量。
    本脚本末尾“输出绑定区”会把当前已实现步骤的所有 Solver 成员变量逐一暴露出来（若输出端存在）。

说明：
- 各步骤读取数据库得到的 All/AllDict 必须避免覆盖 Step1 的 All/AllDict。
  因此每个子 Solver 的数据库结果均使用前缀命名（JHD_All、LG_All、SD_All、QX_All 等）。
- 广播机制：尽量模拟 GH 的一对多、多对多（以最大长度为准，长度=1 则重复；否则取最小公共长度）。
"""

from __future__ import division

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

from yingzao.ancientArchi import (
    DBJsonReader,
    JiaoHuDou_dangongSolver,
    LingGongSolver,
    SanDouSolver,
    QiXinDouSolver,
    FTPlaneFromLists,
    GeoAligner_xfm,
    build_timber_block_uniform
)


# =========================================================
# 通用工具函数
# =========================================================

def _default_place_plane():
    """默认 PlacePlane：GH XY Plane，原点 (100,100,0)。"""
    try:
        pl = rg.Plane.WorldXY
        pl.Origin = rg.Point3d(100.0, 100.0, 0.0)
        return pl
    except:
        return None


def all_to_dict(all_list):
    """All(list[(k,v)]) -> dict"""
    d = {}
    if not all_list:
        return d
    for kv in all_list:
        if isinstance(kv, (list, tuple)) and len(kv) == 2:
            d[str(kv[0])] = kv[1]
    return d


def _as_int(val, default=0):
    """
    安全转 int：兼容 None / bool / 数字 / 字符串 / list/tuple
    注意：在 CPython3 环境下没有 long 类型；此处不使用 long。
    """
    try:
        if val is None:
            return int(default)
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, int):
            return int(val)
        if isinstance(val, float):
            return int(round(val))
        if isinstance(val, str):
            s = val.strip()
            if s == '':
                return int(default)
            return int(float(s))
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_int(val[0], default)
    except:
        pass
    return int(default)


def _as_float(val, default=0.0):
    try:
        if val is None:
            return float(default)
        if isinstance(val, bool):
            return float(int(val))
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            s = val.strip()
            if s == '':
                return float(default)
            return float(s)
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_float(val[0], default)
    except:
        pass
    return float(default)


def _as_float_list(val, default=0.0):
    """
    安全转 float 列表：兼容 None / 单值 / str / list/tuple
    - None -> []
    - 单值 -> [float]
    - list/tuple -> [float...]
    """
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        out = []
        for x in val:
            out.append(_as_float(x, default))
        return out
    return [_as_float(val, default)]


def _as_01(val, default=0):
    """Flip 参数：兼容 int/bool/str/list -> 0/1"""
    try:
        if val is None:
            return int(default)
        if isinstance(val, bool):
            return 1 if val else 0
        if isinstance(val, int):
            return 1 if val != 0 else 0
        if isinstance(val, float):
            return 1 if float(val) != 0.0 else 0
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("1", "true", "yes", "y", "t"):
                return 1
            if s in ("0", "false", "no", "n", "f", ""):
                return 0
            return 1 if float(s) != 0.0 else 0
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_01(val[0], default)
    except:
        pass
    return int(default)


def _ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    return [x]


def _broadcast_n(*seqs):
    """
    GH 风格广播（简化版）：
    - 先把所有输入转 list
    - 目标长度 = max(len)
    - len==1 的列表重复填充
    - 若存在多个 len>1 且不相等：取最小公共长度（避免越界）
    """
    lists = [_ensure_list(s) for s in seqs]
    lens = [len(a) for a in lists]
    if not lens or max(lens) == 0:
        return [[] for _ in lists], 0

    max_len = max(lens)
    multi = [l for l in lens if l > 1]
    if multi and len(set(multi)) > 1:
        tgt = min(multi)
    else:
        tgt = max_len

    out = []
    for a in lists:
        if len(a) == 0:
            out.append([None] * tgt)
        elif len(a) == 1:
            out.append([a[0]] * tgt)
        else:
            out.append(a[:tgt])
    return out, tgt


def _xform_plane(pl, xform):
    """对 Plane 应用 Transform（对 Origin/XAxis/YAxis 分别变换）。"""
    if pl is None or xform is None:
        return pl
    try:
        o = rg.Point3d(pl.Origin)
        x = rg.Vector3d(pl.XAxis)
        y = rg.Vector3d(pl.YAxis)
        o.Transform(xform)
        x.Transform(xform)
        y.Transform(xform)
        return rg.Plane(o, x, y)
    except:
        return pl


def _plane_from_lists_broadcast(origin_points, base_planes, index_origin, index_plane, wrap=True, tag="PFL"):
    """
    调用 FTPlaneFromLists.build_plane，并对 (IndexOrigin, IndexPlane) 做广播。
    返回：
        BasePlane_list, OriginPoint_list, ResultPlane_list, Log_list(str)
    """
    builder = FTPlaneFromLists(wrap=wrap)

    idxO = _ensure_list(index_origin)
    idxP = _ensure_list(index_plane)
    (idxO_b, idxP_b), n = _broadcast_n(idxO, idxP)

    base_out, org_out, res_out, log_out = [], [], [], []
    for i in range(n):
        bp, op, rp, lg = builder.build_plane(origin_points, base_planes, idxO_b[i], idxP_b[i])
        base_out.append(bp)
        org_out.append(op)
        res_out.append(rp)
        log_out.append("[{}][{}] {}".format(tag, i, lg))
    return base_out, org_out, res_out, log_out


def _geoalign_broadcast(geo, src_planes, tgt_planes, rotate_deg=0.0, flip_x=0, flip_y=0, flip_z=0, move_x=0.0, move_y=0.0, move_z=0.0):
    """
    GeoAligner_xfm.align 广播版：支持 geo/src/tgt 三者广播。
    返回：
        SourceOut_list, TargetOut_list, TransformOut_list, MovedGeo_list
    """
    geo_l = _ensure_list(geo)
    sp_l = _ensure_list(src_planes)
    tp_l = _ensure_list(tgt_planes)

    (geo_b, sp_b, tp_b), n = _broadcast_n(geo_l, sp_l, tp_l)

    so_list, to_list, xf_list, mg_list = [], [], [], []
    for i in range(n):
        so, to, xf, mg = GeoAligner_xfm.align(
            geo_b[i],
            sp_b[i],
            tp_b[i],
            rotate_deg=rotate_deg,
            flip_x=flip_x,
            flip_y=flip_y,
            flip_z=flip_z,
            move_x=move_x,
            move_y=move_y,
            move_z=move_z,
        )
        so_list.append(so)
        to_list.append(to)
        xf_list.append(xf)
        mg_list.append(mg)
    return so_list, to_list, xf_list, mg_list


def _flatten_items(obj, out_list):
    """
    把 obj 递归拍平成“一维 items”，追加到 out_list。
    目标：避免 list 套 list，保证 out_list 中每个元素是一个几何 item。
    """
    if obj is None:
        return
    # 常见嵌套：list/tuple
    if isinstance(obj, (list, tuple)):
        for it in obj:
            _flatten_items(it, out_list)
        return
    # 其他类型：直接当作 item
    out_list.append(obj)


def _make_reference_plane(name):
    """
    把数据库/项目里常见的参考平面字符串转成 RhinoCommon 的 rg.Plane
    兼容：WorldXY / WorldYZ / WorldXZ
    其中 WorldXZ 使用你项目中约定的 GH XZ Plane 定义。
    """
    if name is None:
        return rg.Plane.WorldXY
    s = str(name).strip()

    if s == "WorldXY":
        return rg.Plane.WorldXY
    if s == "WorldYZ":
        return rg.Plane.WorldYZ
    if s in ("WorldXZ", "XZ", "WorldZX"):  # 兼容写法
        return rg.Plane(rg.Point3d(0,0,0), rg.Vector3d(1,0,0), rg.Vector3d(0,0,1))

    # 兜底
    return rg.Plane.WorldXY


# =========================================================
# Solver 主类
# =========================================================

class DanGongComponentAssemblySolver(object):
    """
    单栱：按步骤串联
        Step1  : 读取数据库（PuZuo / DanGong）
        Step2  : 交互枓（JiaoHuDou） + SVG1 对位到 PlacePlane
        Step3  : 令栱（LingGong）  + SVG2 对位到 Step2 的参考
        Step4  : 散枓（SanDou） + 齊心枓（QiXinDou） + PFL1/PFL2 + SVG3 对位
        Step5  : 叠级4-羅漢方/素方（SuFangLuoHanFang） + SVG4 对位
        Step6  : 组合输出 ComponentAssembly（永远输出一维 list）
    """

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, IncludeSuFangLuoHanFang=False, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane if PlacePlane is not None else _default_place_plane()
        self.Refresh = bool(Refresh)
        self.IncludeSuFangLuoHanFang = bool(IncludeSuFangLuoHanFang)
        self.ghenv = ghenv

        self.ComponentAssembly = []
        self.Log = ""

        # Step1（全局 DB：PuZuo/DanGong）
        self.Value = None
        self.All = None
        self.AllDict = None
        self.DBLog = ""

        self.LogLines = []

    # -------------------------------
    # Step 1：读取数据库（全局）
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库…")
        reader = DBJsonReader(
            db_path=self.DBPath,
            table="PuZuo",
            key_field="type_code",
            key_value="DanGong",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )
        self.Value, self.All, self.DBLog = reader.run()
        self.AllDict = all_to_dict(self.All)

        self.LogLines.append("[DB] 数据库读取完成")
        self.LogLines.append("[DB] table=PuZuo type_code=DanGong field=params_json export_all=True")
        self.LogLines.append("[DB] All 条目数={}".format(len(self.All) if self.All else 0))
        self.LogLines.append("[DB] AllDict 条目数={}".format(len(self.AllDict) if self.AllDict else 0))
        self.LogLines.append("Step 1 完成：已读取 All 列表并转换为 AllDict。")

    # -------------------------------
    # Step 2：交互枓 + SVG1 对位
    # -------------------------------
    def step2_jiaohudou(self):
        self.LogLines.append("Step 2：交互枓 JiaoHuDou + SVG1 对位…")

        base_point = rg.Point3d(0, 0, 0)

        jhd = JiaoHuDou_dangongSolver(self.DBPath, base_point, self.Refresh)
        jhd.run()

        # 子模块 DB 输出：避免覆盖 Step1 的 All/AllDict
        self.JHD_All = getattr(jhd, "All", None)
        self.JHD_AllDict = getattr(jhd, "AllDict", None)
        self.JHD_Log = getattr(jhd, "Log", "")

        self.JHD_CutTimbers = getattr(jhd, "CutTimbers", None)
        self.JHD_FacePlaneList = getattr(jhd, "FacePlaneList", None)

        # SVG1 参数（来自 Step1 全局 AllDict）
        src_idx = _as_int(self.AllDict.get("SVG1_GA_JiaoHuDou__SourcePlane", 0), 0)
        rotate_deg = _as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__RotateDeg", 0.0), 0.0)
        flipx = _as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipX", 0), 0)
        flipy = _as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipY", 0), 0)
        flipz = _as_01(self.AllDict.get("SVG1_GA_JiaoHuDou__FlipZ", 0), 0)
        movex = _as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveX", 0.0), 0.0)
        movey = _as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveY", 0.0), 0.0)
        movez = _as_float(self.AllDict.get("SVG1_GA_JiaoHuDou__MoveZ", 0.0), 0.0)

        # SourcePlane（单个）
        sp = None
        try:
            sp_list = _ensure_list(self.JHD_FacePlaneList)
            if sp_list:
                sp = sp_list[src_idx] if src_idx < len(sp_list) else sp_list[0]
        except:
            sp = None

        # 对位到 PlacePlane
        so, to, xf, mg = GeoAligner_xfm.align(
            self.JHD_CutTimbers,
            sp,
            self.PlacePlane,
            rotate_deg=rotate_deg,
            flip_x=flipx,
            flip_y=flipy,
            flip_z=flipz,
            move_x=movex,
            move_y=movey,
            move_z=movez,
        )

        self.SVG1_SourceOut = so
        self.SVG1_TargetOut = to
        self.SVG1_TransformOut = ght.GH_Transform(xf) if xf is not None else None
        self.SVG1_MovedGeo = mg

        self.LogLines.append("[STEP2] JiaoHuDou_dangongSolver 完成：CutTimbers={}".format("OK" if self.JHD_CutTimbers else "None"))
        self.LogLines.append("[STEP2][SVG1] 对位完成：SourceIdx={} RotateDeg={} Flip=({},{},{}) Move=({},{},{})".format(
            src_idx, rotate_deg, flipx, flipy, flipz, movex, movey, movez
        ))

    # -------------------------------
    # Step 3：令栱 + SVG2 对位
    # -------------------------------
    def step3_linggong(self):
        self.LogLines.append("Step 3：令栱 LingGong + SVG2 对位…")

        base_point = rg.Point3d(0, 0, 0)

        lg = LingGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
        lg = lg.run()

        # 子模块 DB 输出：避免覆盖 Step1
        self.LG_All = getattr(lg, "All", None)
        self.LG_AllDict = getattr(lg, "AllDict", None)
        self.LG_Log = getattr(lg, "Log", "")

        self.LG_CutTimbers = getattr(lg, "CutTimbers", None)
        self.LG_FacePlaneList = getattr(lg, "FacePlaneList", None)
        self.LG_EdgeMidPoints = getattr(lg, "EdgeMidPoints", None)

        # SVG2 参数（来自 Step1 全局 AllDict）
        src_idx = _as_int(self.AllDict.get("SVG2_GA_LingGong__SourcePlane", 0), 0)
        tgt_idx = _as_int(self.AllDict.get("SVG2_GA_LingGong__TargetPlane", 0), 0)
        rotate_deg = _as_float(self.AllDict.get("SVG2_GA_LingGong__RotateDeg", 0.0), 0.0)
        flipz = _as_01(self.AllDict.get("SVG2_GA_LingGong__FlipZ", 0), 0)
        movez = _as_float(self.AllDict.get("SVG2_GA_LingGong__MoveZ", 0.0), 0.0)

        # SourcePlane：LG FacePlaneList 索引
        sp = None
        try:
            sp_list = _ensure_list(self.LG_FacePlaneList)
            if sp_list:
                sp = sp_list[src_idx] if src_idx < len(sp_list) else sp_list[0]
        except:
            sp = None

        # TargetPlane：JHD FacePlaneList，先应用 SVG1 Transform，再取索引
        tp = None
        try:
            tp_list_raw = _ensure_list(self.JHD_FacePlaneList)
            xf1 = self.SVG1_TransformOut.Value if self.SVG1_TransformOut is not None else None
            tp_list = [_xform_plane(pl, xf1) for pl in tp_list_raw]
            if tp_list:
                tp = tp_list[tgt_idx] if tgt_idx < len(tp_list) else tp_list[0]
        except:
            tp = None

        so, to, xf, mg = GeoAligner_xfm.align(
            self.LG_CutTimbers,
            sp,
            tp,
            rotate_deg=rotate_deg,
            flip_x=0,
            flip_y=0,
            flip_z=flipz,
            move_x=0.0,
            move_y=0.0,
            move_z=movez,
        )

        self.SVG2_SourceOut = so
        self.SVG2_TargetOut = to
        self.SVG2_TransformOut = ght.GH_Transform(xf) if xf is not None else None
        self.SVG2_MovedGeo = mg

        self.LogLines.append("[STEP3] LingGongSolver 完成：CutTimbers={}".format("OK" if self.LG_CutTimbers else "None"))
        self.LogLines.append("[STEP3][SVG2] 对位完成：SourceIdx={} TargetIdx={} RotateDeg={} FlipZ={} MoveZ={}".format(
            src_idx, tgt_idx, rotate_deg, flipz, movez
        ))

    # -------------------------------
    # Step 4：散枓+齊心枓 + PFL + SVG3
    # -------------------------------
    def step4_sandou_qixindou(self):
        self.LogLines.append("Step 4：散枓 SanDou + 齊心枓 QiXinDou + PFL + SVG3…")

        base_point = rg.Point3d(0, 0, 0)

        # --- 4.1 SanDou ---
        sd = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        sd.run()
        self.SD_All = getattr(sd, "All", None)
        self.SD_AllDict = getattr(sd, "AllDict", None)
        self.SD_Log = getattr(sd, "Log", "")

        self.SD_CutTimbers = getattr(sd, "CutTimbers", None)
        self.SD_EdgeMidPoints = getattr(sd, "EdgeMidPoints", None)
        self.SD_Corner0Planes = getattr(sd, "Corner0Planes", None)

        # --- 4.2 QiXinDou ---
        qx = QiXinDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        qx.run()
        self.QX_All = getattr(qx, "All", None)
        self.QX_AllDict = getattr(qx, "AllDict", None)
        self.QX_Log = getattr(qx, "Log", "")

        self.QX_CutTimbers = getattr(qx, "CutTimbers", None)
        self.QX_FacePlaneList = getattr(qx, "FacePlaneList", None)

        # --- 4.3 PlaneFromLists::1（SanDou：EdgeMidPoints + Corner0Planes）---
        idxO1 = self.AllDict.get("PlaneFromLists_1__IndexOrigin", None)
        idxP1 = self.AllDict.get("PlaneFromLists_1__IndexPlane", None)
        wrap1 = bool(self.AllDict.get("PlaneFromLists_1__Wrap", True))

        self.PFL1_BasePlane, self.PFL1_OriginPoint, self.PFL1_ResultPlane, self.PFL1_LogLines = _plane_from_lists_broadcast(
            origin_points=self.SD_EdgeMidPoints,
            base_planes=self.SD_Corner0Planes,
            index_origin=idxO1,
            index_plane=idxP1,
            wrap=wrap1,
            tag="PFL1"
        )

        # --- 4.4 PlaneFromLists::2（LingGong：EdgeMidPoints + FacePlaneList）---
        idxO2 = self.AllDict.get("PlaneFromLists_2__IndexOrigin", None)
        idxP2 = self.AllDict.get("PlaneFromLists_2__IndexPlane", None)
        wrap2 = bool(self.AllDict.get("PlaneFromLists_2__Wrap", True))

        self.PFL2_BasePlane, self.PFL2_OriginPoint, self.PFL2_ResultPlane, self.PFL2_LogLines = _plane_from_lists_broadcast(
            origin_points=self.LG_EdgeMidPoints,
            base_planes=self.LG_FacePlaneList,
            index_origin=idxO2,
            index_plane=idxP2,
            wrap=wrap2,
            tag="PFL2"
        )

        # --- 4.5 SVG3_GA_SanDou ---
        xf2 = self.SVG2_TransformOut.Value if self.SVG2_TransformOut is not None else None
        tp_sd = [_xform_plane(pl, xf2) for pl in _ensure_list(self.PFL2_ResultPlane)]

        rot_sd = _as_float(self.AllDict.get("SVG3_GA_SanDou__RotateDeg", 0.0), 0.0)
        flipz_sd = _as_01(self.AllDict.get("SVG3_GA_SanDou__FlipZ", 0), 0)

        # MoveY 允许多值（需要参与广播）
        movey_sd_list = _as_float_list(self.AllDict.get("SVG3_GA_SanDou__MoveY", None), 0.0)

        # 让 MoveY 参与广播：与 geo/src/tgt 一起对齐长度
        geo_l = _ensure_list(self.SD_CutTimbers)
        sp_l  = _ensure_list(self.PFL1_ResultPlane)
        tp_l  = _ensure_list(tp_sd)
        my_l  = movey_sd_list if movey_sd_list else [0.0]

        (geo_b, sp_b, tp_b, my_b), n = _broadcast_n(geo_l, sp_l, tp_l, my_l)

        so3_sd, to3_sd, xf3_sd, mg3_sd = [], [], [], []
        for i in range(n):
            so, to, xf, mg = GeoAligner_xfm.align(
                geo_b[i],
                sp_b[i],
                tp_b[i],
                rotate_deg=rot_sd,
                flip_x=0,
                flip_y=0,
                flip_z=flipz_sd,
                move_x=0.0,
                move_y=my_b[i],
                move_z=0.0
            )
            so3_sd.append(so)
            to3_sd.append(to)
            xf3_sd.append(xf)
            mg3_sd.append(mg)

        self.SVG3_SD_SourceOut = so3_sd
        self.SVG3_SD_TargetOut = to3_sd
        self.SVG3_SD_TransformOut = [ght.GH_Transform(xf) if xf is not None else None for xf in xf3_sd]
        self.SVG3_SD_MovedGeo = mg3_sd

        # --- 4.6 SVG3_GA_QiXinDou ---
        src_idx = _as_int(self.AllDict.get("SVG3_GA_QiXinDou__SourcePlane", 0), 0)
        tgt_idx = _as_int(self.AllDict.get("SVG3_GA_QiXinDou__TargetPlane", 0), 0)
        rot_qx = _as_float(self.AllDict.get("SVG3_GA_QiXinDou__RotateDeg", 0.0), 0.0)
        flipx_qx = _as_01(self.AllDict.get("SVG3_GA_QiXinDou__FlipX", 0), 0)

        sp_qx = None
        try:
            sp_list = _ensure_list(self.QX_FacePlaneList)
            if sp_list:
                sp_qx = sp_list[src_idx] if src_idx < len(sp_list) else sp_list[0]
        except:
            sp_qx = None

        tp_qx = None
        try:
            tp_list_raw = _ensure_list(self.LG_FacePlaneList)
            tp_list = [_xform_plane(pl, xf2) for pl in tp_list_raw]
            if tp_list:
                tp_qx = tp_list[tgt_idx] if tgt_idx < len(tp_list) else tp_list[0]
        except:
            tp_qx = None

        so3_qx, to3_qx, xf3_qx, mg3_qx = GeoAligner_xfm.align(
            self.QX_CutTimbers,
            sp_qx,
            tp_qx,
            rotate_deg=rot_qx,
            flip_x=flipx_qx,
            flip_y=0,
            flip_z=0,
            move_x=0.0,
            move_y=0.0,
            move_z=0.0
        )
        self.SVG3_QX_SourceOut = so3_qx
        self.SVG3_QX_TargetOut = to3_qx
        self.SVG3_QX_TransformOut = ght.GH_Transform(xf3_qx) if xf3_qx is not None else None
        self.SVG3_QX_MovedGeo = mg3_qx

        self.LogLines.append("[STEP4] SanDou/QiXinDou 完成：SD={} QX={}".format(
            "OK" if self.SD_CutTimbers else "None",
            "OK" if self.QX_CutTimbers else "None",
        ))

    # -------------------------------
    # Step 5：叠级4-羅漢方/素方 + SVG4 对位
    # -------------------------------
    def step5_sufang_luohan(self):
        self.LogLines.append("Step 5：叠级4-羅漢方/素方 SuFangLuoHanFang + SVG4 对位…")

        # --- 5.1 SuFangLuoHanFang（木料：timber block）---
        # 参数来自 Step1 全局 AllDict；base_point 默认为原点
        base_point = rg.Point3d(0.0, 0.0, 0.0)

        length_fen = _as_float(self.AllDict.get("SuFangLuoHanFang__length_fen", 32.0), 32.0)
        width_fen  = _as_float(self.AllDict.get("SuFangLuoHanFang__width_fen", 32.0), 32.0)
        height_fen = _as_float(self.AllDict.get("SuFangLuoHanFang__height_fen", 20.0), 20.0)

        # 参考平面：此组件规范中未给出数据库字段，默认使用 WorldXZ（与多数木料坯体一致）
        reference_plane = _make_reference_plane("WorldXZ")


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

            self.SFLHF_TimberBrep = timber_brep
            self.SFLHF_FaceList = faces
            self.SFLHF_PointList = points
            self.SFLHF_EdgeList = edges
            self.SFLHF_CenterPoint = center_pt
            self.SFLHF_CenterAxisLines = center_axes
            self.SFLHF_EdgeMidPoints = edge_midpts
            self.SFLHF_FacePlaneList = face_planes
            self.SFLHF_Corner0Planes = corner0_planes
            self.SFLHF_LocalAxesPlane = local_axes_plane
            self.SFLHF_AxisX = axis_x
            self.SFLHF_AxisY = axis_y
            self.SFLHF_AxisZ = axis_z
            self.SFLHF_FaceDirTags = face_tags
            self.SFLHF_EdgeDirTags = edge_tags
            self.SFLHF_Corner0EdgeDirs = corner0_dirs
            self.SFLHF_Log = log_lines

        except Exception as e:
            self.SFLHF_TimberBrep = None
            self.SFLHF_FaceList = []
            self.SFLHF_PointList = []
            self.SFLHF_EdgeList = []
            self.SFLHF_CenterPoint = None
            self.SFLHF_CenterAxisLines = []
            self.SFLHF_EdgeMidPoints = []
            self.SFLHF_FacePlaneList = []
            self.SFLHF_Corner0Planes = []
            self.SFLHF_LocalAxesPlane = None
            self.SFLHF_AxisX = None
            self.SFLHF_AxisY = None
            self.SFLHF_AxisZ = None
            self.SFLHF_FaceDirTags = []
            self.SFLHF_EdgeDirTags = []
            self.SFLHF_Corner0EdgeDirs = []
            self.SFLHF_Log = ["错误: {}".format(e)]

        # --- 5.2 SVG4_GA_SuFangLuoHanFang 对位 ---
        # Geo：SuFangLuoHanFang.TimberBrep
        # SourcePlane：SuFangLuoHanFang.FacePlaneList[SVG4__SourcePlane]
        src_idx = _as_int(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__SourcePlane", 0), 0)

        sp = None
        try:
            sp_list = _ensure_list(self.SFLHF_FacePlaneList)
            if sp_list:
                sp = sp_list[src_idx] if src_idx < len(sp_list) else sp_list[0]
        except:
            sp = None

        # TargetPlane：
        #   LingGong.FacePlaneList 先应用 SVG2 Transform（即：SVG2_GA_LingGong 的 TransformOut）
        #   再取索引 SVG3_GA_QiXinDou__TargetPlane
        tgt_idx = _as_int(self.AllDict.get("SVG3_GA_QiXinDou__TargetPlane", 0), 0)

        tp = None
        try:
            tp_list_raw = _ensure_list(self.LG_FacePlaneList)
            xf2 = self.SVG2_TransformOut.Value if self.SVG2_TransformOut is not None else None
            tp_list = [_xform_plane(pl, xf2) for pl in tp_list_raw]
            if tp_list:
                tp = tp_list[tgt_idx] if tgt_idx < len(tp_list) else tp_list[0]
        except:
            tp = None

        rot = _as_float(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__RotateDeg", 0.0), 0.0)
        flipx = _as_01(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__FlipX", 0), 0)
        movez = _as_float(self.AllDict.get("SVG4_GA_SuFangLuoHanFang__MoveZ", 0.0), 0.0)

        so, to, xf, mg = GeoAligner_xfm.align(
            self.SFLHF_TimberBrep,
            sp,
            tp,
            rotate_deg=rot,
            flip_x=flipx,
            flip_y=0,
            flip_z=0,
            move_x=0.0,
            move_y=0.0,
            move_z=movez,
        )

        self.SVG4_SFLHF_SourceOut = so
        self.SVG4_SFLHF_TargetOut = to
        self.SVG4_SFLHF_TransformOut = ght.GH_Transform(xf) if xf is not None else None
        self.SVG4_SFLHF_MovedGeo = mg

        self.LogLines.append("[STEP5] SuFangLuoHanFang 完成：TimberBrep={}".format("OK" if self.SFLHF_TimberBrep else "None"))
        self.LogLines.append("[STEP5][SVG4] 对位完成：SourceIdx={} TargetIdx={} RotateDeg={} FlipX={} MoveZ={}".format(
            src_idx, tgt_idx, rot, flipx, movez
        ))

    # -------------------------------
    # Step 6：组合输出（关键修复：永远输出一维 list）
    # -------------------------------
    def step6_assemble(self):
        self.LogLines.append("Step 6：组合输出 ComponentAssembly（list of items）…")

        parts = []

        # 主序：JHD -> LG -> SD -> QX
        _flatten_items(getattr(self, "SVG1_MovedGeo", None), parts)
        _flatten_items(getattr(self, "SVG2_MovedGeo", None), parts)

        # SanDou：广播返回的 MovedGeo 可能是 list（甚至 list of list），这里统一拍平
        _flatten_items(getattr(self, "SVG3_SD_MovedGeo", None), parts)

        # QiXinDou：可能也是 list（取决于上游），也统一拍平
        _flatten_items(getattr(self, "SVG3_QX_MovedGeo", None), parts)

        # 可选加入：叠级4-羅漢方/素方
        if self.IncludeSuFangLuoHanFang:
            _flatten_items(getattr(self, "SVG4_SFLHF_MovedGeo", None), parts)
            self.LogLines.append("[STEP6] IncludeSuFangLuoHanFang=True：已加入 SVG4_SFLHF_MovedGeo")
        else:
            self.LogLines.append("[STEP6] IncludeSuFangLuoHanFang=False：不加入 SVG4_SFLHF_MovedGeo")

        # 永远输出 list（空则 []），禁止单元素解包
        self.ComponentAssembly = parts

        self.LogLines.append("Step 6 完成：ComponentAssembly items={}".format(len(parts)))

    # -------------------------------
    # run
    # -------------------------------
    def run(self):
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self.step1_read_db()
        self.step2_jiaohudou()
        self.step3_linggong()
        self.step4_sandou_qixindou()
        self.step5_sufang_luohan()
        self.step6_assemble()

        # 汇总日志（不覆盖 Step1 的 DBLog）
        if self.DBLog:
            self.LogLines.append(self.DBLog)
        if getattr(self, "JHD_Log", ""):
            self.LogLines.append(str(self.JHD_Log))
        if getattr(self, "LG_Log", ""):
            self.LogLines.append(str(self.LG_Log))
        if getattr(self, "SD_Log", ""):
            self.LogLines.append(str(self.SD_Log))
        if getattr(self, "QX_Log", ""):
            self.LogLines.append(str(self.QX_Log))

        # PFL 日志
        try:
            self.LogLines.extend(_ensure_list(getattr(self, "PFL1_LogLines", [])))
            self.LogLines.extend(_ensure_list(getattr(self, "PFL2_LogLines", [])))
        except:
            pass

        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GhPython 组件输出绑定区
# =========================================================

if __name__ == "__main__":

    # --- 输入优先级：组件输入端 > 数据库 > 默认 ---
    try:
        _db = DBPath
    except:
        _db = None

    try:
        _pp = PlacePlane
    except:
        _pp = None

    if _pp is None:
        _pp = _default_place_plane()

    try:
        _rf = Refresh
    except:
        _rf = False

    try:
        _inc = IncludeSuFangLuoHanFang
    except:
        _inc = False

    solver = DanGongComponentAssemblySolver(DBPath=_db, PlacePlane=_pp, Refresh=_rf, IncludeSuFangLuoHanFang=_inc, ghenv=ghenv)
    solver = solver.run()

    # --------- 核心对外输出（永远 list，每个元素是 item）---------
    ComponentAssembly = solver.ComponentAssembly
    Log = solver.Log

    IncludeSuFangLuoHanFang = getattr(solver, "IncludeSuFangLuoHanFang", False)

    # --------- Step 1：全局 DB ---------
    Value   = solver.Value
    All     = solver.All
    AllDict = solver.AllDict
    DBLog   = solver.DBLog

    # --------- Step 2：交互枓 + SVG1 ---------
    JHD_All     = getattr(solver, "JHD_All", None)
    JHD_AllDict = getattr(solver, "JHD_AllDict", None)
    JHD_Log     = getattr(solver, "JHD_Log", None)

    JHD_CutTimbers    = getattr(solver, "JHD_CutTimbers", None)
    JHD_FacePlaneList = getattr(solver, "JHD_FacePlaneList", None)

    SVG1_SourceOut    = getattr(solver, "SVG1_SourceOut", None)
    SVG1_TargetOut    = getattr(solver, "SVG1_TargetOut", None)
    SVG1_TransformOut = getattr(solver, "SVG1_TransformOut", None)
    SVG1_MovedGeo     = getattr(solver, "SVG1_MovedGeo", None)

    # --------- Step 3：令栱 + SVG2 ---------
    LG_All     = getattr(solver, "LG_All", None)
    LG_AllDict = getattr(solver, "LG_AllDict", None)
    LG_Log     = getattr(solver, "LG_Log", None)

    LG_CutTimbers    = getattr(solver, "LG_CutTimbers", None)
    LG_FacePlaneList = getattr(solver, "LG_FacePlaneList", None)
    LG_EdgeMidPoints = getattr(solver, "LG_EdgeMidPoints", None)

    SVG2_SourceOut    = getattr(solver, "SVG2_SourceOut", None)
    SVG2_TargetOut    = getattr(solver, "SVG2_TargetOut", None)
    SVG2_TransformOut = getattr(solver, "SVG2_TransformOut", None)
    SVG2_MovedGeo     = getattr(solver, "SVG2_MovedGeo", None)

    # --------- Step 4：散枓 + 齊心枓 + PFL + SVG3 ---------
    SD_All     = getattr(solver, "SD_All", None)
    SD_AllDict = getattr(solver, "SD_AllDict", None)
    SD_Log     = getattr(solver, "SD_Log", None)

    SD_CutTimbers    = getattr(solver, "SD_CutTimbers", None)
    SD_EdgeMidPoints = getattr(solver, "SD_EdgeMidPoints", None)
    SD_Corner0Planes = getattr(solver, "SD_Corner0Planes", None)

    QX_All     = getattr(solver, "QX_All", None)
    QX_AllDict = getattr(solver, "QX_AllDict", None)
    QX_Log     = getattr(solver, "QX_Log", None)

    QX_CutTimbers    = getattr(solver, "QX_CutTimbers", None)
    QX_FacePlaneList = getattr(solver, "QX_FacePlaneList", None)

    PFL1_BasePlane   = getattr(solver, "PFL1_BasePlane", None)
    PFL1_OriginPoint = getattr(solver, "PFL1_OriginPoint", None)
    PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
    PFL1_LogLines    = getattr(solver, "PFL1_LogLines", None)

    PFL2_BasePlane   = getattr(solver, "PFL2_BasePlane", None)
    PFL2_OriginPoint = getattr(solver, "PFL2_OriginPoint", None)
    PFL2_ResultPlane = getattr(solver, "PFL2_ResultPlane", None)
    PFL2_LogLines    = getattr(solver, "PFL2_LogLines", None)

    SVG3_SD_SourceOut    = getattr(solver, "SVG3_SD_SourceOut", None)
    SVG3_SD_TargetOut    = getattr(solver, "SVG3_SD_TargetOut", None)
    SVG3_SD_TransformOut = getattr(solver, "SVG3_SD_TransformOut", None)
    SVG3_SD_MovedGeo     = getattr(solver, "SVG3_SD_MovedGeo", None)

    SVG3_QX_SourceOut    = getattr(solver, "SVG3_QX_SourceOut", None)
    SVG3_QX_TargetOut    = getattr(solver, "SVG3_QX_TargetOut", None)
    SVG3_QX_TransformOut = getattr(solver, "SVG3_QX_TransformOut", None)
    SVG3_QX_MovedGeo     = getattr(solver, "SVG3_QX_MovedGeo", None)

    # --------- Step 5：叠级4-羅漢方/素方 + SVG4 ---------
    SFLHF_TimberBrep = getattr(solver, "SFLHF_TimberBrep", None)
    SFLHF_FacePlaneList = getattr(solver, "SFLHF_FacePlaneList", None)
    SFLHF_Log = getattr(solver, "SFLHF_Log", None)

    SVG4_SFLHF_SourceOut    = getattr(solver, "SVG4_SFLHF_SourceOut", None)
    SVG4_SFLHF_TargetOut    = getattr(solver, "SVG4_SFLHF_TargetOut", None)
    SVG4_SFLHF_TransformOut = getattr(solver, "SVG4_SFLHF_TransformOut", None)
    SVG4_SFLHF_MovedGeo     = getattr(solver, "SVG4_SFLHF_MovedGeo", None)


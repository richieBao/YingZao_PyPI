# -*- coding: utf-8 -*-
"""
YouAngSolver · Step 1（DBJsonReader: DG_Dou / type_code=YouAng_4PU / params_json / ExportAll=True）
            + Step 2（由昂截面构建：AngSectionBuilder）

功能概述：
1) 读取数据库 DG_Dou / type_code = YouAng_4PU / params_json，并得到：
   - Value, All, Log（DBLog）
   - AllDict = { key: value } 供后续所有步骤按键名读取
2) 调用 yingzao.ancientArchi.AngSectionBuilder 构建由昂截面及放样/封闭体（若组件输出提供）
   - base_point 优先取组件输入端 base_point；若 None → 原点
   - RefPlaneMode 默认 "WorldXZ"（GH XZ Plane）
   - 其余参数按“组件输入端 > 数据库(AllDict) > 默认值”的优先级取值
3) 当前仅实现到 Step2（按你的“逐步转换”要求）。后续切割/对位等步骤将在下一次增量实现。

注意：
- 参考平面为 GH 参考平面（XY / XZ / YZ）轴关系按你的要求：
  XY : X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
  XZ : X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  ← 默认
  YZ : X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
- 本文件结构与 LingGongSolver.py 一致（通用工具函数 + Solver 主类 + GH 输出绑定区），
  但不照搬其步骤内容；仅复刻通用约定与“developer-friendly 输出绑定区”组织方式。
"""

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.21"

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    DBJsonReader,
    AngSectionBuilder,
    QiAoToolSolver,
    InputHelper,
    GHPlaneFactory,
    FTPlaneFromLists,
    GeoAligner_xfm,
    FT_CutTimbersByTools_GH_SolidDifference,
)


# ==============================================================
# 通用工具函数（与 LingGongSolver 约定保持一致）
# ==============================================================

def all_to_dict(all_list):
    """
    All = [('A',1), ('B',[...]), ...] -> {'A':1, 'B':[...]}
    """
    d = {}
    if all_list is None:
        return d
    for item in all_list:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        k, v = item
        d[k] = v
    return d


def first_or_default(v, default=None):
    """若 v 为 list/tuple，则取第一个；否则直接返回；None → default。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        if len(v) == 0:
            return default
        return v[0]
    return v


def flatten_any(x):
    """
    递归拍平 list/tuple / .NET List(System.Collections.Generic.List`1[System.Object]) 等可迭代嵌套。
    """
    out = []
    if x is None:
        return out

    # RhinoCommon/GH 常见：System.Collections.Generic.List`1[...] 也能被 isinstance(x, (list, tuple)) 捕获不到
    # 这里用 duck-typing：可迭代且不是字符串/几何对象时再展开
    if isinstance(x, (list, tuple)):
        for i in x:
            out.extend(flatten_any(i))
        return out

    # 排除字符串
    if isinstance(x, (str, bytes)):
        return [x]

    # 排除 Rhino 几何（大多数几何都不是可迭代，但这里做个保险）
    if isinstance(x, (rg.GeometryBase, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]

    # 尝试迭代展开
    try:
        it = iter(x)
    except Exception:
        return [x]

    try:
        for i in it:
            out.extend(flatten_any(i))
        return out
    except Exception:
        return [x]


def make_ref_plane(mode_str, origin=None):
    """
    根据字符串构造参考平面（满足你在要求5给出的轴关系）：
    - XY : X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
    - XZ : X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)  ← 默认
    - YZ : X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    if mode_str is None:
        mode_str = "WorldXZ"
    m = str(mode_str).upper()

    if m in ("WORLDXY", "XY", "XY_PLANE"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WORLDYZ", "YZ", "YZ_PLANE"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


# ==============================================================
# 主 Solver 类 —— 由昂_四鋪作 YouAngSolver
# ==============================================================

class YouAngSolver(object):
    def __init__(self, DBPath, base_point, Refresh, ghenv):
        # 输入缓存
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1：数据库读取相关成员
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # 全局日志（含 DB / Step 日志）
        self.Log = []

        # Step 2：AngSectionBuilder 输出成员（保持组件命名，便于后续挂输出端）
        self.Ang_PtsKeys = []
        self.Ang_PtsValues = []
        self.Ang_CrvsKeys = []
        self.Ang_CrvsValues = []
        self.Ang_PlanesAKeys = []
        self.Ang_PlanesAValues = []
        self.Ang_PlanesBKeys = []
        self.Ang_PlanesBValues = []
        self.Ang_SectionCrvs = None
        self.Ang_LoftBrep = None
        self.Ang_SolidBrep = None
        self.OBLoftBrep =None
        self.Ang_Log = []

        # 最终 Cut 结果（当前仅实现到 Step2：先以 SolidBrep 作为主输出占位）
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：从 AllDict 中取值（遵循 LingGongSolver 习惯：len==1 则解包）
    # ------------------------------------------------------
    def all_get(self, key, default=None):
        if not self.AllDict:
            return default
        if key not in self.AllDict:
            return default
        v = self.AllDict[key]
        if isinstance(v, (list, tuple)):
            if len(v) == 0:
                return default
            if len(v) == 1:
                return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        DG_Dou / type_code = YouAng_4PU / params_json
        """
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="YouAng_4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            self.Value, self.All, self.DBLog = reader.run()

            self.Log.append("[DB] 数据库读取完成")
            for l in self.DBLog:
                self.Log.append("[DB] " + str(l))

            self.AllDict = all_to_dict(self.All)
            self.Log.append("[DB] AllDict 构建完成，共 {} 项".format(len(self.AllDict)))

        except Exception as e:
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：由昂截面构建（AngSectionBuilder）
    # ------------------------------------------------------
    def step2_ang_section_builder(self):
        """
        参数优先级：组件输入端 > 数据库 > 默认值
        组件输入端本 Solver 只暴露 base_point（另 RefPlaneMode 可由数据库控制；若你要暴露输入端，后续增量可加）
        """
        # 1) base_point：组件输入优先
        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)

        # 2) RefPlaneMode：默认 GH XZ
        #    这里传 mode 字符串给 AngSectionBuilder；其内部会按库实现处理
        ref_mode = self.all_get("AngSectionBuilder__RefPlaneMode", None)
        if ref_mode is None:
            ref_mode = "WorldXZ"

        # 3) 其余参数：数据库键名与描述对齐
        OA_len = first_or_default(self.all_get("AngSectionBuilder__OA_len", None), None)
        AC_len = first_or_default(self.all_get("AngSectionBuilder__AC_len", None), None)
        BD_len = first_or_default(self.all_get("AngSectionBuilder__BD_len", None), None)
        OffsetY = first_or_default(self.all_get("AngSectionBuilder__OffsetY", None), None)
        H_dist = first_or_default(self.all_get("AngSectionBuilder__H_dist", None), None)
        GH_len = first_or_default(self.all_get("AngSectionBuilder__GH_len", None), None)
        SectionOffsetZ = first_or_default(self.all_get("AngSectionBuilder__SectionOffsetZ", None), None)

        # 4) 默认值（与给出的 AngSectionBuilder 组件代码一致）
        def _coalesce(v, default):
            return default if v is None else v

        try:
            b = AngSectionBuilder(
                base_point=bp,
                ref_plane_mode=ref_mode,
                OA_len=_coalesce(OA_len, 21.0),
                AC_len=_coalesce(AC_len, 52.4),
                BD_len=_coalesce(BD_len, 115.22),
                OffsetY=_coalesce(OffsetY, 15.0),
                H_dist=_coalesce(H_dist, 82.72),
                GH_len=_coalesce(GH_len, 6.0),
                SectionOffsetZ=_coalesce(SectionOffsetZ, 5.0),
            )

            (
                PtsKeys, PtsValues,
                CrvsKeys, CrvsValues,
                PlanesAKeys, PlanesAValues,
                PlanesBKeys, PlanesBValues,
                SectionCrvs, LoftBrep, SolidBrep, OBLoftBrep,
                LogLines
            ) = b.build()

            # --- 存成员变量（开发模式输出） ---
            self.Ang_PtsKeys = PtsKeys or []
            self.Ang_PtsValues = PtsValues or []
            self.Ang_CrvsKeys = CrvsKeys or []
            # 注意：若 CrvsValues 内有嵌套 List，按要求10递归拍平
            self.Ang_CrvsValues = flatten_any(CrvsValues) if CrvsValues is not None else []
            self.Ang_PlanesAKeys = PlanesAKeys or []
            self.Ang_PlanesAValues = PlanesAValues or []
            self.Ang_PlanesBKeys = PlanesBKeys or []
            self.Ang_PlanesBValues = PlanesBValues or []
            self.Ang_SectionCrvs = SectionCrvs
            self.Ang_LoftBrep = LoftBrep
            self.Ang_SolidBrep = SolidBrep
            self.Ang_Log = LogLines or []
            self.OBLoftBrep = OBLoftBrep

            self.Log.append("[ANG] AngSectionBuilder.build 完成")
            for l in self.Ang_Log:
                self.Log.append("[ANG] " + str(l))

        except Exception as e:
            self.Ang_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step2_ang_section_builder 出错: {}".format(e))

        # 5) 暂定最终输出（仅到 Step2）：以 SolidBrep 作为 CutTimbers
        if self.Ang_SolidBrep is not None:
            self.CutTimbers = [self.Ang_SolidBrep]
            self.FailTimbers = []
        else:
            self.CutTimbers = []
            self.FailTimbers = []

        return self

    # ------------------------------------------------------
    # Step 3：QiAOTool + PlaneFromLists::1 + (ListItem+PlaneOrigin) + GeoAligner::1
    # ------------------------------------------------------
    def step3_qiaotool_planeFromLists_geoAligner(self):
        """
        Step3 语义：
        1) QiAOTool 生成刀具切割相关几何（CutTimbers/FailTimbers/EdgeMidPoints/Corner0Planes 等）
        2) PlaneFromLists::1：以 EdgeMidPoints + Corner0Planes 按索引得到 SourcePlane（可 Tree）
        3) List Item(2) + Plane Origin：从 AngSectionBuilder 的 PtsValues / PlanesAValues 取索引，
           生成 GeoAligner::1 的 TargetPlane（保持 Base 轴向，仅替换 Origin）
        4) GeoAligner::1：将 QiAOTool 的 CutTimbers 对位到 TargetPlane（按 Tree 分支一一对应）
        """
        log_lines = []

        # -------------------------
        # A) QiAOTool
        # -------------------------
        # base_point：组件输入端优先；AllDict 若给则允许覆盖
        bp = self.base_point
        bp_db = self.all_get("QiAOTool__base_point", None)
        if bp_db is not None:
            bp = InputHelper.as_point3d(bp_db, bp if bp is not None else rg.Point3d(0, 0, 0))
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)

        def _to_float(v, default):
            try:
                if v is None:
                    return float(default)
                # 允许 [x] 形式
                if isinstance(v, (list, tuple)) and len(v) > 0:
                    return float(v[0])
                return float(v)
            except:
                return float(default)

        def _to_bool(v, default=False):
            try:
                if v is None:
                    return bool(default)
                return InputHelper.to_bool(v, default=default)
            except:
                try:
                    return bool(v)
                except:
                    return bool(default)

        length_fen = self.all_get("QiAOTool__length_fen", None)
        width_fen = self.all_get("QiAOTool__width_fen", None)
        height_fen = self.all_get("QiAOTool__height_fen", None)

        timber_ref_plane_mode = self.all_get("QiAOTool__timber_ref_plane_mode", None)
        if timber_ref_plane_mode is None:
            timber_ref_plane_mode = "WorldXZ"

        qi_height = self.all_get("QiAOTool__qi_height", None)
        sha_width = self.all_get("QiAOTool__sha_width", None)
        qi_offset_fen = self.all_get("QiAOTool__qi_offset_fen", None)
        extrude_length = self.all_get("QiAOTool__extrude_length", None)
        extrude_positive = self.all_get("QiAOTool__extrude_positive", None)

        qi_ref_plane_mode = self.all_get("QiAOTool__qi_ref_plane_mode", None)
        if qi_ref_plane_mode is None:
            qi_ref_plane_mode = self.all_get("QiAOTool__qi_ref_plane_mode_default", None)
        if qi_ref_plane_mode is None:
            qi_ref_plane_mode = "WorldXZ"

        params = {
            "length_fen": _to_float(length_fen, 41.0),
            "width_fen": _to_float(width_fen, 16.0),
            "height_fen": _to_float(height_fen, 10.0),
            "base_point": bp,
            "timber_ref_plane": GHPlaneFactory.make(
                timber_ref_plane_mode if timber_ref_plane_mode is not None else "XZ",
                origin=bp
            ),
            "qi_height": _to_float(qi_height, 4.0),
            "sha_width": _to_float(sha_width, 2.0),
            "qi_offset_fen": _to_float(qi_offset_fen, 0.5),
            "extrude_length": _to_float(extrude_length, 28.0),
            "extrude_positive": _to_bool(extrude_positive, default=False),
            "qi_ref_plane": GHPlaneFactory.make(
                qi_ref_plane_mode if qi_ref_plane_mode is not None else "XZ",
                origin=bp
            ),
        }

        try:
            qsolver = QiAoToolSolver(ghenv=self.ghenv)
            qsolver.run(params)

            self.QiAOTool__CutTimbers = qsolver.CutTimbers
            self.QiAOTool__FailTimbers = qsolver.FailTimbers
            self.QiAOTool__Log = qsolver.Log

            # 中间/调试输出（若 solver 提供）
            self.QiAOTool__EdgeMidPoints = getattr(qsolver, "EdgeMidPoints", None)
            self.QiAOTool__Corner0Planes = getattr(qsolver, "Corner0Planes", None)

            # 额外调试字段（存在则保存）
            for k in (
                    "TimberBrep", "ToolBrep", "AlignedTool",
                    "PFL1_ResultPlane", "QiAo_FacePlane",
                    "FaceList", "PointList", "EdgeList", "CenterPoint",
                    "CenterAxisLines", "FacePlaneList", "LocalAxesPlane",
                    "AxisX", "AxisY", "AxisZ", "FaceDirTags", "EdgeDirTags", "Corner0EdgeDirs"
            ):
                if hasattr(qsolver, k):
                    setattr(self, "QiAOTool__" + k, getattr(qsolver, k))

            log_lines.append("[Step3] QiAOTool ok.")
        except Exception as e:
            self.QiAOTool__CutTimbers = []
            self.QiAOTool__FailTimbers = []
            self.QiAOTool__Log = ["[Step3][QiAOTool] ERROR: {}".format(e)]
            self.QiAOTool__EdgeMidPoints = None
            self.QiAOTool__Corner0Planes = None
            log_lines.append("[Step3] QiAOTool failed: {}".format(e))
            # 若失败，直接结束 Step3，但不抛异常
            self.Log.extend(log_lines)
            return self

        # -------------------------
        # B) PlaneFromLists::1
        # -------------------------
        try:
            op = self.QiAOTool__EdgeMidPoints
            bp_list = self.QiAOTool__Corner0Planes

            idx_origin = self.all_get("PlaneFromLists_1__IndexOrigin", 0)
            idx_plane = self.all_get("PlaneFromLists_1__IndexPlane", 0)
            wrap = self.all_get("PlaneFromLists_1__Wrap", True)
            wrap = _to_bool(wrap, default=True)

            pfl = FTPlaneFromLists(wrap=wrap)
            BasePlane, OriginPoint, ResultPlane, Log = pfl.build_plane(op, bp_list, idx_origin, idx_plane)

            self.PlaneFromLists_1__BasePlane = BasePlane
            self.PlaneFromLists_1__OriginPoint = OriginPoint
            self.PlaneFromLists_1__ResultPlane = ResultPlane
            self.PlaneFromLists_1__Log = Log
            log_lines.append("[Step3] PlaneFromLists::1 ok.")
        except Exception as e:
            self.PlaneFromLists_1__BasePlane = None
            self.PlaneFromLists_1__OriginPoint = None
            self.PlaneFromLists_1__ResultPlane = None
            self.PlaneFromLists_1__Log = ["[Step3][PlaneFromLists::1] ERROR: {}".format(e)]
            log_lines.append("[Step3] PlaneFromLists::1 failed: {}".format(e))
            self.Log.extend(log_lines)
            return self

        # -------------------------
        # C) List Item + Plane Origin（TargetPlane）
        # -------------------------
        # 说明：AngSectionBuilder 输出可能是 Tree/嵌套；本处必须按“分支”取索引
        def _is_tree(obj):
            return hasattr(obj, "Paths") and hasattr(obj, "Branch")

        def _branches(obj):
            """返回 branches(list) 与 paths(list|None)；若非 Tree，则把嵌套 list 当 branches；否则单 branch。"""
            if obj is None:
                return [], None
            if _is_tree(obj):
                try:
                    paths = list(obj.Paths)
                    brs = [list(obj.Branch(p)) for p in paths]
                    return brs, paths
                except:
                    # 退化：当作单 branch
                    return [list(obj)], None
            if isinstance(obj, (list, tuple)):
                # 若是 [ [..], [..] ] 视作 branches；否则单 branch
                if len(obj) > 0 and isinstance(obj[0], (list, tuple)):
                    return [list(b) for b in obj], None
                return [list(obj)], None
            # 单值
            return [[obj]], None

        def _broadcast_list(v, n):
            """GH 风格广播：单值/短列表循环到长度 n。"""
            if n <= 0:
                return []
            if v is None:
                return [None] * n
            if isinstance(v, (list, tuple)):
                if len(v) == 0:
                    return [None] * n
                if len(v) == n:
                    return list(v)
                # 循环广播
                out = []
                for i in range(n):
                    out.append(v[i % len(v)])
                return out
            return [v] * n

        def _safe_index(seq, idx, wrap=True):
            if seq is None or len(seq) == 0:
                return None
            try:
                ii = int(idx)
            except:
                ii = 0
            if wrap:
                ii = ii % len(seq)
            else:
                if ii < 0 or ii >= len(seq):
                    return None
            return seq[ii]

        pts_values = getattr(self, "Ang_PtsValues", None)
        planesA_values = getattr(self, "Ang_PlanesAValues", None)

        idx_tp_origin = self.all_get("GeoAligner_1__TargetPlane_origin", 0)
        idx_tp_base = self.all_get("GeoAligner_1__TargetPlane_base", 0)

        pts_brs, pts_paths = _branches(pts_values)
        base_brs, base_paths = _branches(planesA_values)

        br_count = max(len(pts_brs), len(base_brs))
        if br_count == 0:
            self.GeoAligner_1__TargetPlane_origin_item = None
            self.GeoAligner_1__TargetPlane_base_item = None
            self.PlaneOrigin_1__Plane = None
            log_lines.append("[Step3] TargetPlane inputs empty.")
        else:
            # 对齐分支数（短的广播）
            if len(pts_brs) != br_count:
                pts_brs = _broadcast_list(pts_brs, br_count)
            if len(base_brs) != br_count:
                base_brs = _broadcast_list(base_brs, br_count)

            idx_o_list = _broadcast_list(idx_tp_origin, br_count)
            idx_b_list = _broadcast_list(idx_tp_base, br_count)

            origin_items = []
            base_items = []
            target_planes = []

            for bi in range(br_count):
                br_pts = pts_brs[bi] if pts_brs[bi] is not None else []
                br_base = base_brs[bi] if base_brs[bi] is not None else []

                o_item = _safe_index(br_pts, idx_o_list[bi], wrap=True)
                b_item = _safe_index(br_base, idx_b_list[bi], wrap=True)

                origin_items.append(o_item)
                base_items.append(b_item)

                tp = None
                try:
                    if o_item is not None and b_item is not None:
                        # 保持 Base 轴向，仅替换 Origin
                        tp = rg.Plane(o_item, b_item.XAxis, b_item.YAxis)
                except:
                    tp = None
                target_planes.append(tp)

            self.GeoAligner_1__TargetPlane_origin_item = origin_items
            self.GeoAligner_1__TargetPlane_base_item = base_items
            self.PlaneOrigin_1__Plane = target_planes
            log_lines.append("[Step3] PlaneOrigin(TargetPlane) ok.")

        # -------------------------
        # D) GeoAligner::1（按分支一一对应）
        # -------------------------
        try:
            import Grasshopper.Kernel.Types as ght

            geo_in = self.QiAOTool__CutTimbers
            src_pl = self.PlaneFromLists_1__ResultPlane
            tgt_pl = self.PlaneOrigin_1__Plane

            rotate_deg = self.all_get("GeoAligner_1__RotateDeg", 0.0)
            flip_x = _to_bool(self.all_get("GeoAligner_1__FlipX", False), default=False)
            flip_y = _to_bool(self.all_get("GeoAligner_1__FlipY", False), default=False)
            flip_z = _to_bool(self.all_get("GeoAligner_1__FlipZ", False), default=False)
            move_x = self.all_get("GeoAligner_1__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_1__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_1__MoveZ", 0.0)

            # 统一为 branches
            geo_brs, geo_paths = _branches(geo_in)
            src_brs, _ = _branches(src_pl)
            tgt_brs, _ = _branches(tgt_pl)

            br_count = max(len(geo_brs), len(src_brs), len(tgt_brs))
            geo_brs = _broadcast_list(geo_brs, br_count)
            src_brs = _broadcast_list(src_brs, br_count)
            tgt_brs = _broadcast_list(tgt_brs, br_count)

            # MoveX/Y/Z 可单值或列表：按分支广播
            move_x_l = _broadcast_list(move_x, br_count)
            move_y_l = _broadcast_list(move_y, br_count)
            move_z_l = _broadcast_list(move_z, br_count)

            moved_brs = []
            src_out_brs = []
            tgt_out_brs = []
            xfm_out_brs = []

            for bi in range(br_count):
                g_b = geo_brs[bi]
                s_b = src_brs[bi]
                t_b = tgt_brs[bi]

                # 每分支的 SourcePlane/TargetPlane 取第 1 个（与“每分支一个值”契合）
                s_plane = None
                if isinstance(s_b, (list, tuple)):
                    s_plane = s_b[0] if len(s_b) > 0 else None
                else:
                    s_plane = s_b
                t_plane = None
                if isinstance(t_b, (list, tuple)):
                    t_plane = t_b[0] if len(t_b) > 0 else None
                else:
                    t_plane = t_b

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    g_b,
                    s_plane,
                    t_plane,
                    rotate_deg=rotate_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x_l[bi],
                    move_y=move_y_l[bi],
                    move_z=move_z_l[bi],
                )

                src_out_brs.append(SourceOut)
                tgt_out_brs.append(TargetOut)
                xfm_out_brs.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                moved_brs.append(MovedGeo)

            self.GeoAligner_1__SourceOut = src_out_brs
            self.GeoAligner_1__TargetOut = tgt_out_brs
            self.GeoAligner_1__TransformOut = xfm_out_brs
            self.GeoAligner_1__MovedGeo = moved_brs

            # Step3 作为当前阶段的最终 CutTimbers 输出
            self.CutTimbers = flatten_any(moved_brs)
            self.FailTimbers = self.QiAOTool__FailTimbers if self.QiAOTool__FailTimbers is not None else []
            log_lines.append("[Step3] GeoAligner::1 ok.")
        except Exception as e:
            self.GeoAligner_1__SourceOut = None
            self.GeoAligner_1__TargetOut = None
            self.GeoAligner_1__TransformOut = None
            self.GeoAligner_1__MovedGeo = None
            log_lines.append("[Step3] GeoAligner::1 failed: {}".format(e))

        self.Log.extend(log_lines)
        return self

    # ------------------------------------------------------
    # ------------------------------------------------------
    # Step 4：YouAngQiao + PlaneFromLists::2 + (ListItem:FPlanes) + GeoAligner::2
    # ------------------------------------------------------
    def step4_youangqiao_planeFromLists2_geoAligner2(self):
        """
        Step4 语义（严格按 GH 连线复刻）：
        - YouAngQiao.base_point ← 输入 base_point
        - PlaneFromLists::2.OriginPoints ← AngSectionBuilder.PtsValues
        - PlaneFromLists::2.BasePlanes  ← AngSectionBuilder.PlanesBValues
        - GeoAligner::2.TargetPlane     ← PlaneFromLists::2.ResultPlane
        - GeoAligner::2.SourcePlane     ← ListItem(YouAngQiao.FPlanes, GeoAligner_2__SourcePlane)
        - GeoAligner::2.Geo             ← YouAngQiao.Brep

        关键规则：
        - PlaneFromLists 广播规则 / Tree 分支规则：依 FTPlaneFromLists 组件实现（库内）
        - List Item：Tree List + Tree/列表 Index → 必须按分支取值；Index 单值对所有分支广播
        - GeoAligner::2：若任一输入为 Tree，则按分支一一对应计算；单值参数广播；不得产生笛卡尔积
        """
        log_lines = []

        # -------------------------
        # A) YouAngQiao
        # -------------------------
        try:
            from yingzao.ancientArchi import YouAngQiao
        except Exception as e:
            log_lines.append("[Step4][YouAngQiao] IMPORT ERROR: {}".format(e))
            self.YouAngQiao__Log = log_lines
            self.Log.extend(log_lines)
            return self

        bp = self.base_point
        if bp is None:
            bp = rg.Point3d(0.0, 0.0, 0.0)

        rect_len = first_or_default(self.all_get("YouAngQiao__rect_len", None), 34.560343)
        rect_h = first_or_default(self.all_get("YouAngQiao__rect_h", None), 15.0)
        EH_len = first_or_default(self.all_get("YouAngQiao__EH_len", None), 2.0)
        HI_len = first_or_default(self.all_get("YouAngQiao__HI_len", None), 1.0)
        KL_len = first_or_default(self.all_get("YouAngQiao__KL_len", None), 2.0)
        KN_len = first_or_default(self.all_get("YouAngQiao__KN_len", None), 3.0)
        offset_dist = first_or_default(self.all_get("YouAngQiao__offset_dist", None), 5.0)
        ref_mode = first_or_default(self.all_get("YouAngQiao__RefPlaneMode", None), "WorldXZ")

        # 类型健壮转换（尽量不改变原有 Tree/列表结构；这里只对数值做 float 化）
        def _to_float_safe(v, default):
            if v is None:
                return default
            try:
                return float(v)
            except Exception:
                return default

        rect_len = _to_float_safe(rect_len, 34.560343)
        rect_h = _to_float_safe(rect_h, 15.0)
        EH_len = _to_float_safe(EH_len, 2.0)
        HI_len = _to_float_safe(HI_len, 1.0)
        KL_len = _to_float_safe(KL_len, 2.0)
        KN_len = _to_float_safe(KN_len, 3.0)
        offset_dist = _to_float_safe(offset_dist, 5.0)

        try:
            generator = YouAngQiao(
                base_point=bp,
                ref_plane_mode=ref_mode,
                rect_len=rect_len,
                rect_h=rect_h,
                EH_len=EH_len,
                HI_len=HI_len,
                KL_len=KL_len,
                KN_len=KN_len,
                offset_dist=offset_dist
            )
            generator.generate()

            # 必要缓存（按要求）
            self.YouAngQiao__Brep = generator.get_closed_brep()
            self.YouAngQiao__FPlanes = generator.get_F_planes()
            self.YouAngQiao__DH_OffsetLoft = generator.get_DH_offset_loft()
            self.YouAngQiao__Log = generator.get_log()
        except Exception as e:
            log_lines.append("[Step4][YouAngQiao] ERROR: {}".format(e))
            self.YouAngQiao__Brep = None
            self.YouAngQiao__FPlanes = None
            self.YouAngQiao__DH_OffsetLoft = None
            self.YouAngQiao__Log = log_lines
            self.Log.extend(log_lines)
            return self

        # -------------------------
        # B) PlaneFromLists::2（来自 AngSectionBuilder）
        # -------------------------
        try:
            from yingzao.ancientArchi import FTPlaneFromLists
        except Exception as e:
            log_lines.append("[Step4][PlaneFromLists::2] IMPORT ERROR: {}".format(e))
            self.PlaneFromLists_2__Log = log_lines
            self.Log.extend(log_lines)
            return self

        OriginPoints = getattr(self, "Ang_PtsValues", None)  # AngSectionBuilder.PtsValues
        BasePlanes = getattr(self, "Ang_PlanesBValues", None)  # AngSectionBuilder.PlanesBValues

        idx_origin = first_or_default(self.all_get("PlaneFromLists_2__IndexOrigin", None), 0)
        idx_plane = first_or_default(self.all_get("PlaneFromLists_2__IndexPlane", None), 0)
        wrap2 = first_or_default(self.all_get("PlaneFromLists_2__Wrap", None), True)

        try:
            builder = FTPlaneFromLists(wrap=wrap2)
            BasePlane2, OriginPoint2, ResultPlane2, Log2 = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )
            self.PlaneFromLists_2__BasePlane = BasePlane2
            self.PlaneFromLists_2__OriginPoint = OriginPoint2
            self.PlaneFromLists_2__ResultPlane = ResultPlane2
            self.PlaneFromLists_2__Log = Log2
        except Exception as e:
            self.PlaneFromLists_2__BasePlane = None
            self.PlaneFromLists_2__OriginPoint = None
            self.PlaneFromLists_2__ResultPlane = None
            self.PlaneFromLists_2__Log = ["[Step4][PlaneFromLists::2] ERROR: {}".format(e)]
            log_lines.append("[Step4] PlaneFromLists::2 failed: {}".format(e))
            self.Log.extend(log_lines)
            return self

        # -------------------------
        # C) List Item（FPlanes, GeoAligner_2__SourcePlane）→ SourcePlane(Tree)
        # -------------------------
        def _is_tree(obj):
            return hasattr(obj, "Paths") and hasattr(obj, "Branch")

        def _branches(obj):
            # 返回：branches(list[list]), paths(list[GH_Path|None])
            if obj is None:
                return [], []
            if _is_tree(obj):
                paths = list(obj.Paths)
                brs = []
                for p in paths:
                    b = obj.Branch(p)
                    brs.append(list(b) if b is not None else [])
                return brs, paths
            if isinstance(obj, (list, tuple)):
                # 判定为“嵌套列表模拟 Tree”
                if len(obj) > 0 and all(isinstance(x, (list, tuple)) for x in obj):
                    return [list(x) for x in obj], [None] * len(obj)
                return [list(obj)], [None]
            return [[obj]], [None]

        def _broadcast_list(v, n):
            if n <= 0:
                return []
            if v is None:
                return [None] * n
            if not isinstance(v, (list, tuple)):
                return [v] * n
            if len(v) == 0:
                return [None] * n
            out = []
            for i in range(n):
                out.append(v[i % len(v)])
            return out

        def _safe_index(seq, idx, wrap=True):
            if seq is None or len(seq) == 0:
                return None
            try:
                ii = int(idx)
            except:
                ii = 0
            if wrap:
                ii = ii % len(seq)
            else:
                if ii < 0 or ii >= len(seq):
                    return None
            return seq[ii]

        fplanes = getattr(self, "YouAngQiao__FPlanes", None)
        idx_src = self.all_get("GeoAligner_2__SourcePlane", 0)

        f_brs, f_paths = _branches(fplanes)
        i_brs, i_paths = _branches(idx_src)

        br_count = max(len(f_brs), len(i_brs))
        if br_count == 0:
            self.GeoAligner_2__SourcePlane__ListItem_Result = None
        else:
            if len(f_brs) != br_count:
                f_brs = _broadcast_list(f_brs, br_count)
            if len(i_brs) != br_count:
                i_brs = _broadcast_list(i_brs, br_count)

            src_plane_brs = []
            for bi in range(br_count):
                planes_list = f_brs[bi] if isinstance(f_brs[bi], (list, tuple)) else [f_brs[bi]]
                idx_list = i_brs[bi] if isinstance(i_brs[bi], (list, tuple)) else [i_brs[bi]]
                # GH 习惯：每分支 index 通常是单值；若多值，则逐个取（输出分支为多值）
                out_planes = []
                for j, idxv in enumerate(idx_list):
                    out_planes.append(_safe_index(planes_list, idxv, wrap=True))
                src_plane_brs.append(out_planes)

            # 这里用“嵌套列表”表示 Tree（与 step3 既有约定一致）
            self.GeoAligner_2__SourcePlane__ListItem_Result = src_plane_brs

        # -------------------------
        # D) GeoAligner::2（按 Tree 分支一一对应）
        # -------------------------
        try:
            from yingzao.ancientArchi import GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght
        except Exception as e:
            log_lines.append("[Step4][GeoAligner::2] IMPORT ERROR: {}".format(e))
            self.Log.extend(log_lines)
            return self

        Geo = getattr(self, "YouAngQiao__Brep", None)
        SourcePlane = getattr(self, "GeoAligner_2__SourcePlane__ListItem_Result", None)
        TargetPlane = getattr(self, "PlaneFromLists_2__ResultPlane", None)

        rotate_deg = first_or_default(self.all_get("GeoAligner_2__RotateDeg", None), 0.0)
        flip_x = first_or_default(self.all_get("GeoAligner_2__FlipX", None), False)
        flip_y = first_or_default(self.all_get("GeoAligner_2__FlipY", None), False)
        flip_z = first_or_default(self.all_get("GeoAligner_2__FlipZ", None), False)

        move_x = first_or_default(self.all_get("GeoAligner_2__MoveX", None), 0.0)
        move_y = first_or_default(self.all_get("GeoAligner_2__MoveY", None), 0.0)
        move_z = first_or_default(self.all_get("GeoAligner_2__MoveZ", None), 0.0)

        # 分支拆解
        geo_brs, geo_paths = _branches(Geo)
        src_brs, src_paths = _branches(SourcePlane)
        tgt_brs, tgt_paths = _branches(TargetPlane)

        br_count = max(len(geo_brs), len(src_brs), len(tgt_brs))
        if br_count == 0:
            self.GeoAligner_2__SourceOut = None
            self.GeoAligner_2__TargetOut = None
            self.GeoAligner_2__TransformOut = None
            self.GeoAligner_2__MovedGeo = None
            log_lines.append("[Step4] GeoAligner::2 inputs empty.")
            self.Log.extend(log_lines)
            return self

        # 广播对齐分支数
        if len(geo_brs) != br_count:
            geo_brs = _broadcast_list(geo_brs, br_count)
        if len(src_brs) != br_count:
            src_brs = _broadcast_list(src_brs, br_count)
        if len(tgt_brs) != br_count:
            tgt_brs = _broadcast_list(tgt_brs, br_count)

        # 广播单值参数到 br_count
        move_x_l = _broadcast_list(move_x, br_count)
        move_y_l = _broadcast_list(move_y, br_count)
        move_z_l = _broadcast_list(move_z, br_count)

        moved_brs = []
        src_out_brs = []
        tgt_out_brs = []
        xfm_out_brs = []

        for bi in range(br_count):
            g_b = geo_brs[bi]
            s_b = src_brs[bi]
            t_b = tgt_brs[bi]

            # 每分支：Geo 一般单值；若列表则取第1个
            geo_item = None
            if isinstance(g_b, (list, tuple)):
                geo_item = g_b[0] if len(g_b) > 0 else None
            else:
                geo_item = g_b

            s_plane = None
            if isinstance(s_b, (list, tuple)):
                s_plane = s_b[0] if len(s_b) > 0 else None
            else:
                s_plane = s_b

            t_plane = None
            if isinstance(t_b, (list, tuple)):
                t_plane = t_b[0] if len(t_b) > 0 else None
            else:
                t_plane = t_b

            try:
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo_item,
                    s_plane,
                    t_plane,
                    rotate_deg=rotate_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x_l[bi],
                    move_y=move_y_l[bi],
                    move_z=move_z_l[bi],
                )
                moved_brs.append(MovedGeo)
                src_out_brs.append(SourceOut)
                tgt_out_brs.append(TargetOut)
                xfm_out_brs.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
            except Exception as e:
                moved_brs.append(None)
                src_out_brs.append(None)
                tgt_out_brs.append(None)
                xfm_out_brs.append(None)
                log_lines.append("[Step4][GeoAligner::2] branch {} ERROR: {}".format(bi, e))

        # 缓存（按要求）
        self.GeoAligner_2__SourceOut = src_out_brs
        self.GeoAligner_2__TargetOut = tgt_out_brs
        self.GeoAligner_2__TransformOut = xfm_out_brs
        self.GeoAligner_2__MovedGeo = flatten_any(moved_brs)

        # 不修改主输出 CutTimbers（避免破坏 Step3 既有结果），仅写日志
        if log_lines:
            self.Log.extend(log_lines)
        return self

    # ------------------------------------------------------
    # Step 5：CutTimbersByTools（SolidDifference）
    # ------------------------------------------------------
    def step5_cutTimbersByTools(self):
        """
        Step5 语义（严格按 GH 连线复刻）：
        - Timbers ← AngSectionBuilder.SolidBrep
        - Tools   ← GeoAligner::1~2 的 MovedGeo 列表（可能 Tree/嵌套；必须完全拍平后送入）
        - keep_inside：组件输入端若无，则按 AllDict > 默认(False)

        输出：
        - CutTimbers / FailTimbers / Log 直接来自 FT_CutTimbersByTools_GH_SolidDifference.cut
        """
        log_lines = []

        # Timbers
        timbers = getattr(self, "Ang_SolidBrep", None)

        # Tools：GeoAligner::1~2 的 MovedGeo 列表（完全拍平）
        tools_1 = getattr(self, "GeoAligner_1__MovedGeo", None)
        tools_2 = getattr(self, "GeoAligner_2__MovedGeo", None)

        tools_list = []
        if tools_1 is not None:
            tools_list.append(tools_1)
        if tools_2 is not None:
            tools_list.append(tools_2)

        tools_flat = flatten_any(tools_list)

        # 去除 None
        tools_flat = [g for g in tools_flat if g is not None]

        # keep_inside：无输入端，按 AllDict > 默认值
        keep_inside = self.all_get("CutTimbersByTools__KeepInside", None)
        keep_inside = InputHelper.to_bool(keep_inside, default=False) if keep_inside is not None else False

        # debug：本 Solver 不暴露输入端，默认 False；若 AllDict 提供则允许覆盖
        dbg_in = self.all_get("CutTimbersByTools__debug", None)
        debug_flag = InputHelper.to_bool(dbg_in, default=False) if dbg_in is not None else False

        try:
            cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(debug_flag))
            CutTimbers, FailTimbers, Log = cutter.cut(
                timbers=timbers,
                tools=tools_flat,
                keep_inside=keep_inside,
                debug=dbg_in
            )

            # 缓存（开发输出）
            self.CutTimbersByTools__CutTimbers = CutTimbers
            self.CutTimbersByTools__FailTimbers = FailTimbers
            self.CutTimbersByTools__Log = Log

            # Step5 作为最终主输出
            self.CutTimbers = CutTimbers
            self.FailTimbers = FailTimbers

            log_lines.append(
                "[Step5] CutTimbersByTools ok. tools={}".format(len(tools_flat) if tools_flat is not None else 0))
        except Exception as e:
            self.CutTimbersByTools__CutTimbers = []
            self.CutTimbersByTools__FailTimbers = []
            self.CutTimbersByTools__Log = ["[Step5][CutTimbersByTools] ERROR: {}".format(e)]
            # 若失败，不覆盖已有 CutTimbers（避免破坏之前结果）
            log_lines.append("[Step5] CutTimbersByTools failed: {}".format(e))

        if log_lines:
            self.Log.extend(log_lines)
        return self

    # 主控入口
    # ------------------------------------------------------
    def run(self):
        # Step 1：数据库
        self.step1_read_db()

        # 若 All 为空，可提前返回
        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：由昂截面构建
        self.step2_ang_section_builder()

        # Step 3：QiAOTool + PlaneFromLists::1 + GeoAligner::1
        self.step3_qiaotool_planeFromLists_geoAligner()

        # Step 4：YouAngQiao + PlaneFromLists::2 + GeoAligner::2
        self.step4_youangqiao_planeFromLists2_geoAligner2()

        # Step 5：CutTimbersByTools（SolidDifference）
        self.step5_cutTimbersByTools()

        return self


if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    #   - 最终主输出：CutTimbers / FailTimbers / Log
    #   - 同时暴露到当前步骤为止 Solver 内部成员变量，方便你随时挂到输出端调试
    # ==============================================================
    solver = YouAngSolver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- 开发模式输出：Step1(DB) ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- 开发模式输出：Step2(AngSectionBuilder) ---
    Ang_PtsKeys = solver.Ang_PtsKeys
    Ang_PtsValues = solver.Ang_PtsValues
    Ang_CrvsKeys = solver.Ang_CrvsKeys
    Ang_CrvsValues = solver.Ang_CrvsValues
    Ang_PlanesAKeys = solver.Ang_PlanesAKeys
    Ang_PlanesAValues = solver.Ang_PlanesAValues
    Ang_PlanesBKeys = solver.Ang_PlanesBKeys
    Ang_PlanesBValues = solver.Ang_PlanesBValues
    Ang_SectionCrvs = solver.Ang_SectionCrvs
    Ang_LoftBrep = solver.Ang_LoftBrep
    Ang_SolidBrep = solver.Ang_SolidBrep
    Ang_OBLoftBrep = solver.OBLoftBrep
    Ang_Log = solver.Ang_Log

    # --- 开发模式输出：Step3(QiAOTool / PlaneFromLists::1 / PlaneOrigin / GeoAligner::1) ---
    QiAOTool__CutTimbers = getattr(solver, "QiAOTool__CutTimbers", None)
    QiAOTool__FailTimbers = getattr(solver, "QiAOTool__FailTimbers", None)
    QiAOTool__Log = getattr(solver, "QiAOTool__Log", None)
    QiAOTool__EdgeMidPoints = getattr(solver, "QiAOTool__EdgeMidPoints", None)
    QiAOTool__Corner0Planes = getattr(solver, "QiAOTool__Corner0Planes", None)

    PlaneFromLists_1__BasePlane = getattr(solver, "PlaneFromLists_1__BasePlane", None)
    PlaneFromLists_1__OriginPoint = getattr(solver, "PlaneFromLists_1__OriginPoint", None)
    PlaneFromLists_1__ResultPlane = getattr(solver, "PlaneFromLists_1__ResultPlane", None)
    PlaneFromLists_1__Log = getattr(solver, "PlaneFromLists_1__Log", None)

    GeoAligner_1__TargetPlane_origin_item = getattr(solver, "GeoAligner_1__TargetPlane_origin_item", None)
    GeoAligner_1__TargetPlane_base_item = getattr(solver, "GeoAligner_1__TargetPlane_base_item", None)
    PlaneOrigin_1__Plane = getattr(solver, "PlaneOrigin_1__Plane", None)

    GeoAligner_1__SourceOut = getattr(solver, "GeoAligner_1__SourceOut", None)
    GeoAligner_1__TargetOut = getattr(solver, "GeoAligner_1__TargetOut", None)
    GeoAligner_1__TransformOut = getattr(solver, "GeoAligner_1__TransformOut", None)
    GeoAligner_1__MovedGeo = getattr(solver, "GeoAligner_1__MovedGeo", None)

    # --- 开发模式输出：Step4(YouAngQiao / PlaneFromLists::2 / ListItem(FPlanes) / GeoAligner::2) ---
    YouAngQiao__FPlanes = getattr(solver, "YouAngQiao__FPlanes", None)
    YouAngQiao__Brep = getattr(solver, "YouAngQiao__Brep", None)
    YouAngQiao__DH_OffsetLoft = getattr(solver, "YouAngQiao__DH_OffsetLoft", None)
    YouAngQiao__Log = getattr(solver, "YouAngQiao__Log", None)

    PlaneFromLists_2__BasePlane = getattr(solver, "PlaneFromLists_2__BasePlane", None)
    PlaneFromLists_2__OriginPoint = getattr(solver, "PlaneFromLists_2__OriginPoint", None)
    PlaneFromLists_2__ResultPlane = getattr(solver, "PlaneFromLists_2__ResultPlane", None)
    PlaneFromLists_2__Log = getattr(solver, "PlaneFromLists_2__Log", None)

    GeoAligner_2__SourcePlane__ListItem_Result = getattr(solver, "GeoAligner_2__SourcePlane__ListItem_Result", None)

    GeoAligner_2__SourceOut = getattr(solver, "GeoAligner_2__SourceOut", None)
    GeoAligner_2__TargetOut = getattr(solver, "GeoAligner_2__TargetOut", None)
    GeoAligner_2__TransformOut = getattr(solver, "GeoAligner_2__TransformOut", None)
    GeoAligner_2__MovedGeo = getattr(solver, "GeoAligner_2__MovedGeo", None)

    # --- 开发模式输出：Step5(CutTimbersByTools) ---
    CutTimbersByTools__CutTimbers = getattr(solver, "CutTimbersByTools__CutTimbers", None)
    CutTimbersByTools__FailTimbers = getattr(solver, "CutTimbersByTools__FailTimbers", None)
    CutTimbersByTools__Log = getattr(solver, "CutTimbersByTools__Log", None)



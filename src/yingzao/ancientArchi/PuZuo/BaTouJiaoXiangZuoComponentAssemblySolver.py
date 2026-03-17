# -*- coding: utf-8 -*-
"""
BaTouJiaoXiangZuoComponentAssemblySolver.py

将「把頭絞項造 BaTouJiaoXiangZuo」的多 ghpy 组件流程，逐步收拢为一个单独 GhPython 组件。

【当前实现范围：Step 1-5】
- Step 1：DBJsonReader 读取 params_json → All0 / AllDict0（作为“全局主参数”，后续不覆盖）
- Step 2：叠级1-櫨枓（LuDou）→ CutTimbers
          + VSG1_GA_LuDou（GeoAligner_xfm）→ 对位到 PlacePlane
- Step 3：叠级2-泥道栱（NiDaoGong）→ CutTimbers
          + VSG2_GA_NiDaoGong（GeoAligner_xfm）→ 对位到「经 VSG1 变换后的 LuDou.FacePlaneList 指定面」
- Step 4：叠级3-乳栿劄牽（RuFuZhaQian）→ CutTimbers
          + FTPlaneFromLists::1 → 由 EdgeMidPoints + Corner0Planes 索引生成 SourcePlane
          + VSG3_GA_RuFuZhaQian（GeoAligner_xfm）→ 对位到「经 VSG1 变换后的 LuDou.FacePlaneList 指定面」
- Step 5：叠级4-散枓（SanDou）+ 齊心枓（QiXinDou）→ CutTimbers
          + FTPlaneFromLists::2/3 → 生成对位 Source/TargetPlane
          + VSG4_GA_SanDou / VSG4_GA_QiXinDou（GeoAligner_xfm）→ 对位到「经 VSG2 变换后的 NiDaoGong 参考面体系」

输入（初始 3 个）：
    DBPath : str
        SQLite 数据库路径（Song-styleArchi.db）

    PlacePlane : rg.Plane
        放置参考平面（默认 GH 的 XY Plane，但原点为 (100,100,0)）

    Refresh : bool
        刷新开关：True 强制重读数据库并重算

输出：
    ComponentAssembly : object
        最终组合体（当前 Step2：仅含 VSG1 对位后的 LuDou 几何）
    Log : list[str] / str
        日志

注意：
- 所有后续步骤用到数据库值，一律从 Step1 的 All0/AllDict0 取，不再重复读库。
- 若后续步骤需要“局部再读库”产生新 AllX/AllDictX，必须用新变量名，禁止覆盖 All0/AllDict0。
"""

from __future__ import print_function, division

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

from yingzao.ancientArchi import (
    DBJsonReader,
    LU_DOU_batoujiaoxiangSolver,
    NiDaoGongSolver,
    RufuZhaQianSolver,
    SanDouSolver,
    QiXinDouSolver,
    FTPlaneFromLists,
    GeoAligner_xfm,
    build_timber_block_uniform
)

__author__ = "richiebao [coding-x.tech]"
__version__ = "2025.12.29"


# =========================================================
# 通用工具函数（对齐 ChongGong 的风格 + 补齐广播/拍平/索引逻辑）
# =========================================================

def _default_place_plane():
    """默认 GH XY Plane，但原点固定为 (100,100,0)。"""
    return rg.Plane(rg.Point3d(100, 100, 0), rg.Vector3d(1, 0, 0), rg.Vector3d(0, 1, 0))


def _is_gh_tree(x):
    try:
        from Grasshopper import DataTree
        return isinstance(x, DataTree)
    except:
        return False


def _ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    # GH 常见 .NET List
    try:
        import System
        if isinstance(x, System.Collections.IEnumerable) and not isinstance(x, (str, rg.GeometryBase, rg.Plane,
                                                                                rg.Point3d)):
            return [i for i in x]
    except:
        pass
    return [x]


def _flatten_items(x, out_list):
    """递归拍平 list/tuple/.NET list，避免出现 System.Collections.Generic.List`1[System.Object] 的层层嵌套。"""
    if x is None:
        return
    # 不拍平：几何/平面/点/字符串
    if isinstance(x, (rg.GeometryBase, rg.Plane, rg.Point3d, str)):
        out_list.append(x)
        return

    # DataTree：按分支拍平到同一个 out_list（最终输出的 ComponentAssembly 需要是 list）
    if _is_gh_tree(x):
        try:
            paths = x.Paths
            for p in paths:
                branch = x.Branch(p)
                _flatten_items(branch, out_list)
        except:
            out_list.append(x)
        return

    # list/tuple/可迭代
    if isinstance(x, (list, tuple)):
        for it in x:
            _flatten_items(it, out_list)
        return

    try:
        import System
        if isinstance(x, System.Collections.IEnumerable) and not isinstance(x, (str, rg.GeometryBase, rg.Plane,
                                                                                rg.Point3d)):
            for it in x:
                _flatten_items(it, out_list)
            return
    except:
        pass

    out_list.append(x)


def _as_bool(x, default=False):
    if x is None:
        return bool(default)
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(int(x) != 0)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("1", "true", "t", "yes", "y", "on"):
            return True
        if s in ("0", "false", "f", "no", "n", "off", ""):
            return False
    return bool(default)


def _broadcast_lists(*args):
    """
    GH 广播（简化版）：
    - item 与 list 混用时，item 自动扩展
    - 多个 list 长度不一致时：按 max_len 广播（短的用最后一个值延展）
    """
    seqs = []
    max_len = 1
    for a in args:
        if isinstance(a, (list, tuple)):
            aa = list(a)
        else:
            aa = [a]
        seqs.append(aa)
        if len(aa) > max_len:
            max_len = len(aa)

    rows = []
    for i in range(max_len):
        row = []
        for aa in seqs:
            if len(aa) == 0:
                row.append(None)
            elif len(aa) == 1:
                row.append(aa[0])
            else:
                row.append(aa[i] if i < len(aa) else aa[-1])
        rows.append(tuple(row))
    return rows


def _pick_from_list_by_index(items, idx):
    """
    从 items（list/tuple 或 Tree）按 idx 取元素：
    - idx 为 int：取一个
    - idx 为 list：取多个（长度随 idx）
    - items 为 Tree 且 idx 为 list：当前先做“扁平取”（后续若遇到你定义的特例2/3，再单独加 Tree 分支规则）
    """
    if items is None:
        return None

    # Tree：先扁平为 list（当前 step2 足够）
    if _is_gh_tree(items):
        flat = []
        _flatten_items(items, flat)
        items = flat

    arr = _ensure_list(items)

    def _safe_get(i):
        try:
            ii = int(i)
            if ii < 0:
                ii = len(arr) + ii
            if 0 <= ii < len(arr):
                return arr[ii]
        except:
            pass
        return None

    if isinstance(idx, (list, tuple)):
        return [_safe_get(i) for i in idx]
    else:
        return _safe_get(idx)


def _ft_plane_from_lists_broadcast(origin_points, base_planes, index_origin, index_plane, wrap=True):
    """
    用于替代 FTPlaneFromLists.build_plane 的“广播增强版”：
    - index_origin / index_plane 允许为 int 或 list
    - 若两者长度不一致：按 max_len 广播（短的用最后一个值延展）
    - origin_points / base_planes 允许为 GH Tree / .NET list，内部会扁平化
    返回：
        BasePlane, OriginPoint, ResultPlane, Log
        - 若输入 index_* 任意为 list/tuple，则对应返回 list（与广播长度一致）
        - 否则返回单值
    """
    # 扁平化 points / planes
    if _is_gh_tree(origin_points):
        op_flat = []
        _flatten_items(origin_points, op_flat)
        origin_points = op_flat
    if _is_gh_tree(base_planes):
        bp_flat = []
        _flatten_items(base_planes, bp_flat)
        base_planes = bp_flat

    ops = _ensure_list(origin_points)
    bps = _ensure_list(base_planes)

    log = []
    if not ops:
        log.append("[WARN] OriginPoints 为空")
    if not bps:
        log.append("[WARN] BasePlanes 为空")

    idxO = index_origin if isinstance(index_origin, (list, tuple)) else [index_origin]
    idxP = index_plane if isinstance(index_plane, (list, tuple)) else [index_plane]

    # 广播对齐
    max_len = max(len(idxO), len(idxP), 1)
    if len(idxO) < max_len:
        idxO = (idxO + [idxO[-1]] * (max_len - len(idxO))) if idxO else [0] * max_len
    if len(idxP) < max_len:
        idxP = (idxP + [idxP[-1]] * (max_len - len(idxP))) if idxP else [0] * max_len

    def _wrap_index(i, n):
        if n <= 0:
            return None
        try:
            ii = int(i)
        except:
            return None
        if wrap:
            return ii % n
        # 允许负索引
        if ii < 0:
            ii = n + ii
        if 0 <= ii < n:
            return ii
        return None

    def _safe_pick(arr, i):
        ii = _wrap_index(i, len(arr))
        if ii is None:
            return None
        try:
            return arr[ii]
        except:
            return None

    base_out, org_out, res_out = [], [], []
    for io, ip in zip(idxO, idxP):
        bp = _safe_pick(bps, ip)
        op = _safe_pick(ops, io)

        base_out.append(bp)
        org_out.append(op)

        if bp is None or op is None:
            res_out.append(None)
        else:
            try:
                rp = rg.Plane(bp)
                rp.Origin = op
                res_out.append(rp)
            except Exception as e:
                res_out.append(None)
                log.append("[WARN] ResultPlane 构造失败：{}".format(e))

    # 输出形态：单值 or list
    multi = isinstance(index_origin, (list, tuple)) or isinstance(index_plane, (list, tuple))
    if not multi:
        return (base_out[0] if base_out else None,
                org_out[0] if org_out else None,
                res_out[0] if res_out else None,
                log)
    return base_out, org_out, res_out, log


def _align_broadcast(Geo, SourcePlane, TargetPlane,
                     rotate_deg=0.0, flip_x=0, flip_y=0, flip_z=0,
                     move_x=0.0, move_y=0.0, move_z=0.0):
    """对 GeoAligner_xfm.align 做 GH 广播封装。"""
    rows = _broadcast_lists(
        Geo, SourcePlane, TargetPlane,
        rotate_deg, flip_x, flip_y, flip_z,
        move_x, move_y, move_z
    )

    so_list, to_list, xf_list, mg_list = [], [], [], []
    for (g, sp, tp, rd, fx, fy, fz, mx, my, mz) in rows:
        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                g, sp, tp,
                rotate_deg=rd,
                flip_x=fx,
                flip_y=fy,
                flip_z=fz,
                move_x=mx,
                move_y=my,
                move_z=mz,
            )
        except Exception:
            so, to, xf, mg = None, None, None, None
        so_list.append(so)
        to_list.append(to)
        xf_list.append(xf)
        mg_list.append(mg)

    return so_list, to_list, xf_list, mg_list


# =========================================================
# 变换与平面工具
# =========================================================

def _first_valid_xform(xforms):
    """从 list/tuple 中取第一个有效 rg.Transform；若传入单个 Transform 也直接返回。"""
    if xforms is None:
        return None
    if isinstance(xforms, rg.Transform):
        return xforms
    xs = _ensure_list(xforms)
    for x in xs:
        if isinstance(x, rg.Transform):
            return x
        # GH_Transform
        try:
            if hasattr(x, "Value") and isinstance(x.Value, rg.Transform):
                return x.Value
        except:
            pass
    return None


def _transform_plane(pl, xform):
    if pl is None or xform is None:
        return pl
    try:
        p2 = rg.Plane(pl)
        p2.Transform(xform)
        return p2
    except:
        return pl


def _transform_planes(planes, xform):
    if planes is None:
        return None
    arr = _ensure_list(planes)
    return [_transform_plane(p, xform) for p in arr]


def _resolve_reference_plane(ref, base_point):
    """将 reference_plane（可能是 token 字符串）解析为 Rhino 的 rg.Plane，并把原点设置到 base_point。

    兼容常见 token：
      - "WorldXY" -> rg.Plane.WorldXY
      - "WorldYZ" -> rg.Plane.WorldYZ
      - "WorldXZ"/"WorldZX" -> rg.Plane.WorldZX  （RhinoCommon 用 WorldZX 表示 XZ 平面语义）
    """
    # base_point 统一
    if base_point is None:
        base_point = rg.Point3d(0.0, 0.0, 0.0)
    elif isinstance(base_point, rg.Point):
        base_point = base_point.Location

    # 1) None -> 默认 XZ（用 WorldZX 语义）
    if ref is None:
        pl = rg.Plane.WorldZX
        pl = rg.Plane(pl)
        pl.Origin = base_point
        return pl

    # 2) 已经是 Plane
    if isinstance(ref, rg.Plane):
        pl = rg.Plane(ref)
        pl.Origin = base_point
        return pl

    # 3) token 字符串
    if isinstance(ref, str):
        s = ref.strip()
        if s in ("WorldXY", "XY", "PlaneXY"):
            pl = rg.Plane.WorldXY
        elif s in ("WorldYZ", "YZ", "PlaneYZ"):
            pl = rg.Plane.WorldYZ
        elif s in ("WorldXZ", "XZ", "PlaneXZ", "WorldZX", "ZX", "PlaneZX"):
            pl = rg.Plane.WorldZX
        else:
            # 兜底：尝试直接构造
            try:
                pl = rg.Plane(ref)
            except:
                pl = rg.Plane.WorldXY

        pl = rg.Plane(pl)
        pl.Origin = base_point
        return pl

    # 4) 其他对象：尽量转 Plane
    try:
        pl = rg.Plane(ref)
        pl.Origin = base_point
        return pl
    except:
        pl = rg.Plane.WorldXY
        pl = rg.Plane(pl)
        pl.Origin = base_point
        return pl


# =========================================================
# Solver 主类
# =========================================================

class BaTouJiaoXiangZuoComponentAssemblySolver(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, IncludeSuFangLuoHanFang=False, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = _as_bool(Refresh, default=False)
        self.IncludeSuFangLuoHanFang = _as_bool(IncludeSuFangLuoHanFang, default=False)
        self.ghenv = ghenv

        self.LogLines = []
        self.ComponentAssembly = []
        self.Log = ""

        # Step1 数据（必须保留：后续不覆盖）
        self.Value0 = None
        self.All0 = None
        self.AllDict0 = {}
        self.DBLog0 = None

    # -------------------------------
    # Step 1：读取数据库
    # -------------------------------
    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 params_json -> All0 / AllDict0 …")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="PuZuo",
            key_field="type_code",
            key_value="BaTouJiaoXiangZuo",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value0, self.All0, self.DBLog0 = reader.run()

        d = {}
        try:
            for k, v in _ensure_list(self.All0):
                d[str(k)] = v
        except:
            pass
        self.AllDict0 = d

        self.LogLines.append("Step 1 完成：All0 items={} AllDict0 keys={}".format(
            len(_ensure_list(self.All0)), len(self.AllDict0.keys())
        ))

    # -------------------------------
    # Step 2：叠级1-櫨枓 + VSG1 对位
    # -------------------------------
    def step2_ludou(self):
        self.LogLines.append("Step 2：叠级1-櫨枓 LuDou + VSG1_GA_LuDou 对位…")

        # 2.1 LuDou（base_point 默认原点）
        base_point = rg.Point3d(0, 0, 0)
        try:
            ld = LU_DOU_batoujiaoxiangSolver(self.DBPath, base_point, self.ghenv).run()
        except Exception as e:
            ld = None
            self.LogLines.append("[ERROR] LuDou 失败：{}".format(e))

        # ---- 保留 LuDou 输出（尽量完整，不强依赖每个字段都存在）----
        self.LD_Solver = ld
        self.Value = getattr(ld, "Value", None) if ld else None
        self.All = getattr(ld, "All", None) if ld else None
        self.All_dict = getattr(ld, "All_dict", None) if ld else None

        self.TimberBrep = getattr(ld, "TimberBrep", None) if ld else None
        self.FaceList = getattr(ld, "FaceList", None) if ld else None
        self.PointList = getattr(ld, "PointList", None) if ld else None
        self.EdgeList = getattr(ld, "EdgeList", None) if ld else None
        self.CenterPoint = getattr(ld, "CenterPoint", None) if ld else None
        self.CenterAxisLines = getattr(ld, "CenterAxisLines", None) if ld else None
        self.EdgeMidPoints = getattr(ld, "EdgeMidPoints", None) if ld else None
        self.FacePlaneList = getattr(ld, "FacePlaneList", None) if ld else None
        self.Corner0Planes = getattr(ld, "Corner0Planes", None) if ld else None
        self.LocalAxesPlane = getattr(ld, "LocalAxesPlane", None) if ld else None
        self.AxisX = getattr(ld, "AxisX", None) if ld else None
        self.AxisY = getattr(ld, "AxisY", None) if ld else None
        self.AxisZ = getattr(ld, "AxisZ", None) if ld else None
        self.FaceDirTags = getattr(ld, "FaceDirTags", None) if ld else None
        self.EdgeDirTags = getattr(ld, "EdgeDirTags", None) if ld else None
        self.Corner0EdgeDirs = getattr(ld, "Corner0EdgeDirs", None) if ld else None

        self.BasePlane1 = getattr(ld, "BasePlane1", None) if ld else None
        self.OriginPoint1 = getattr(ld, "OriginPoint1", None) if ld else None
        self.ResultPlane1 = getattr(ld, "ResultPlane1", None) if ld else None

        self.BasePlane2 = getattr(ld, "BasePlane2", None) if ld else None
        self.OriginPoint2 = getattr(ld, "OriginPoint2", None) if ld else None
        self.ResultPlane2 = getattr(ld, "ResultPlane2", None) if ld else None

        self.BasePlane3 = getattr(ld, "BasePlane3", None) if ld else None
        self.OriginPoint3 = getattr(ld, "OriginPoint3", None) if ld else None
        self.ResultPlane3 = getattr(ld, "ResultPlane3", None) if ld else None

        self.ToolBrep = getattr(ld, "ToolBrep", None) if ld else None
        self.BasePoint = getattr(ld, "BasePoint", None) if ld else None
        self.BaseLine = getattr(ld, "BaseLine", None) if ld else None
        self.SecPlane = getattr(ld, "SecPlane", None) if ld else None
        self.FacePlane = getattr(ld, "FacePlane", None) if ld else None

        self.AlignedTool = getattr(ld, "AlignedTool", None) if ld else None
        self.XForm = getattr(ld, "XForm", None) if ld else None
        self.SourcePlane = getattr(ld, "SourcePlane", None) if ld else None
        self.TargetPlane = getattr(ld, "TargetPlane", None) if ld else None
        self.SourcePoint = getattr(ld, "SourcePoint", None) if ld else None
        self.TargetPoint = getattr(ld, "TargetPoint", None) if ld else None
        self.DebugInfo = getattr(ld, "DebugInfo", None) if ld else None

        self.BlockTimbers = getattr(ld, "BlockTimbers", None) if ld else None

        self.AlignedTool2 = getattr(ld, "AlignedTool2", None) if ld else None
        self.XForm2 = getattr(ld, "XForm2", None) if ld else None
        self.SourcePlane2 = getattr(ld, "SourcePlane2", None) if ld else None
        self.TargetPlane2 = getattr(ld, "TargetPlane2", None) if ld else None
        self.SourcePoint2 = getattr(ld, "SourcePoint2", None) if ld else None
        self.TargetPoint2 = getattr(ld, "TargetPoint2", None) if ld else None
        self.DebugInfo2 = getattr(ld, "DebugInfo2", None) if ld else None

        self.CutTimbers = getattr(ld, "CutTimbers", None) if ld else None
        self.FailTimbers = getattr(ld, "FailTimbers", None) if ld else None
        self.LuDouLog = getattr(ld, "Log", None) if ld else None

        # 2.2 VSG1_GA_LuDou（从 AllDict0 取输入）
        # Geo = LuDou.CutTimbers
        Geo = self.CutTimbers

        # SourcePlane = LuDou.FacePlaneList[ idx ]，其中 idx 来自 AllDict0['VSG1_GA_LuDou__SourcePlane']
        idx_sp = self.AllDict0.get("VSG1_GA_LuDou__SourcePlane", 0)
        sp = _pick_from_list_by_index(self.FacePlaneList, idx_sp)

        # TargetPlane = PlacePlane（组件输入端 / 默认）
        tp = self.PlacePlane

        # FlipZ 来自 AllDict0
        fz = self.AllDict0.get("VSG1_GA_LuDou__FlipZ", 0)

        # 其余未说明的 RotateDeg / FlipX / FlipY / MoveX/Y/Z：遵循“数据库优先/默认为 0”
        rd = self.AllDict0.get("VSG1_GA_LuDou__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG1_GA_LuDou__FlipX", 0)
        fy = self.AllDict0.get("VSG1_GA_LuDou__FlipY", 0)
        mx = self.AllDict0.get("VSG1_GA_LuDou__MoveX", 0.0)
        my = self.AllDict0.get("VSG1_GA_LuDou__MoveY", 0.0)
        mz = self.AllDict0.get("VSG1_GA_LuDou__MoveZ", 0.0)

        # 广播对齐（支持 Geo / sp / tp 等为 item 或 list）
        so, to, xf, mg = _align_broadcast(
            Geo, sp, tp,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        # 输出与 Transform 包装（与原 VSG 组件一致）
        self.VSG1_SourceOut = so
        self.VSG1_TargetOut = to
        self.VSG1_XFormRaw = xf
        self.VSG1_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG1_MovedGeo = mg

        self.LogLines.append("Step 2 完成：LuDou + VSG1 对位完成。")

    # -------------------------------
    # Step 3：叠级2-泥道栱 + VSG2 对位
    # -------------------------------
    def step3_nidaogong(self):
        self.LogLines.append("Step 3：叠级2-泥道栱 NiDaoGong + VSG2_GA_NiDaoGong 对位…")

        base_point = rg.Point3d(0, 0, 0)
        try:
            nd = NiDaoGongSolver(self.DBPath, base_point, self.Refresh, self.ghenv).run()
        except Exception as e:
            nd = None
            self.LogLines.append("[ERROR] NiDaoGong 失败：{}".format(e))

        self.ND_Solver = nd

        # --- 主输出（保持与独立组件一致的字段名，但加前缀避免覆盖 LuDou）---
        self.NiDaoGong_CutTimbers = getattr(nd, "CutTimbers", None) if nd else None
        self.NiDaoGong_FailTimbers = getattr(nd, "FailTimbers", None) if nd else None
        self.NiDaoGong_Log = getattr(nd, "Log", None) if nd else None

        # --- 开发模式输出：DB + 木坯 ---
        self.NiDaoGong_Value = getattr(nd, "Value", None) if nd else None
        self.NiDaoGong_All = getattr(nd, "All", None) if nd else None
        self.NiDaoGong_AllDict = getattr(nd, "AllDict", None) if nd else None
        self.NiDaoGong_DBLog = getattr(nd, "DBLog", None) if nd else None

        self.NiDaoGong_TimberBrep = getattr(nd, "TimberBrep", None) if nd else None
        self.NiDaoGong_FaceList = getattr(nd, "FaceList", None) if nd else None
        self.NiDaoGong_PointList = getattr(nd, "PointList", None) if nd else None
        self.NiDaoGong_EdgeList = getattr(nd, "EdgeList", None) if nd else None
        self.NiDaoGong_CenterPoint = getattr(nd, "CenterPoint", None) if nd else None
        self.NiDaoGong_CenterAxisLines = getattr(nd, "CenterAxisLines", None) if nd else None
        self.NiDaoGong_EdgeMidPoints = getattr(nd, "EdgeMidPoints", None) if nd else None
        self.NiDaoGong_FacePlaneList = getattr(nd, "FacePlaneList", None) if nd else None
        self.NiDaoGong_Corner0Planes = getattr(nd, "Corner0Planes", None) if nd else None
        self.NiDaoGong_LocalAxesPlane = getattr(nd, "LocalAxesPlane", None) if nd else None
        self.NiDaoGong_AxisX = getattr(nd, "AxisX", None) if nd else None
        self.NiDaoGong_AxisY = getattr(nd, "AxisY", None) if nd else None
        self.NiDaoGong_AxisZ = getattr(nd, "AxisZ", None) if nd else None
        self.NiDaoGong_FaceDirTags = getattr(nd, "FaceDirTags", None) if nd else None
        self.NiDaoGong_EdgeDirTags = getattr(nd, "EdgeDirTags", None) if nd else None
        self.NiDaoGong_Corner0EdgeDirs = getattr(nd, "Corner0EdgeDirs", None) if nd else None

        # --- 继续透出 NiDaoGong 内部步骤（若字段不存在则为 None）---
        self.NiDaoGong_JuanShaToolBrep = getattr(nd, "JuanShaToolBrep", None) if nd else None
        self.NiDaoGong_JuanShaSectionEdges = getattr(nd, "JuanShaSectionEdges", None) if nd else None
        self.NiDaoGong_JuanShaHL_Intersection = getattr(nd, "JuanShaHL_Intersection", None) if nd else None
        self.NiDaoGong_JuanShaHeightFacePlane = getattr(nd, "JuanShaHeightFacePlane", None) if nd else None
        self.NiDaoGong_JuanShaLengthFacePlane = getattr(nd, "JuanShaLengthFacePlane", None) if nd else None
        self.NiDaoGong_JuanShaLog = getattr(nd, "JuanShaLog", None) if nd else None

        self.NiDaoGong_PF1_BasePlane = getattr(nd, "PF1_BasePlane", None) if nd else None
        self.NiDaoGong_PF1_OriginPoint = getattr(nd, "PF1_OriginPoint", None) if nd else None
        self.NiDaoGong_PF1_ResultPlane = getattr(nd, "PF1_ResultPlane", None) if nd else None
        self.NiDaoGong_PF1_Log = getattr(nd, "PF1_Log", None) if nd else None

        self.NiDaoGong_Align1_AlignedTool = getattr(nd, "Align1_AlignedTool", None) if nd else None
        self.NiDaoGong_Align1_XForm = getattr(nd, "Align1_XForm", None) if nd else None
        self.NiDaoGong_Align1_SourcePlane = getattr(nd, "Align1_SourcePlane", None) if nd else None
        self.NiDaoGong_Align1_TargetPlane = getattr(nd, "Align1_TargetPlane", None) if nd else None
        self.NiDaoGong_Align1_SourcePoint = getattr(nd, "Align1_SourcePoint", None) if nd else None
        self.NiDaoGong_Align1_TargetPoint = getattr(nd, "Align1_TargetPoint", None) if nd else None
        self.NiDaoGong_Align1_DebugInfo = getattr(nd, "Align1_DebugInfo", None) if nd else None

        self.NiDaoGong_BlockCutter_TimberBrep = getattr(nd, "BlockCutter_TimberBrep", None) if nd else None
        self.NiDaoGong_BlockCutter_FaceList = getattr(nd, "BlockCutter_FaceList", None) if nd else None
        self.NiDaoGong_BlockCutter_PointList = getattr(nd, "BlockCutter_PointList", None) if nd else None
        self.NiDaoGong_BlockCutter_EdgeList = getattr(nd, "BlockCutter_EdgeList", None) if nd else None
        self.NiDaoGong_BlockCutter_CenterPoint = getattr(nd, "BlockCutter_CenterPoint", None) if nd else None
        self.NiDaoGong_BlockCutter_CenterAxisLines = getattr(nd, "BlockCutter_CenterAxisLines", None) if nd else None
        self.NiDaoGong_BlockCutter_EdgeMidPoints = getattr(nd, "BlockCutter_EdgeMidPoints", None) if nd else None
        self.NiDaoGong_BlockCutter_FacePlaneList = getattr(nd, "BlockCutter_FacePlaneList", None) if nd else None
        self.NiDaoGong_BlockCutter_Corner0Planes = getattr(nd, "BlockCutter_Corner0Planes", None) if nd else None
        self.NiDaoGong_BlockCutter_LocalAxesPlane = getattr(nd, "BlockCutter_LocalAxesPlane", None) if nd else None
        self.NiDaoGong_BlockCutter_AxisX = getattr(nd, "BlockCutter_AxisX", None) if nd else None
        self.NiDaoGong_BlockCutter_AxisY = getattr(nd, "BlockCutter_AxisY", None) if nd else None
        self.NiDaoGong_BlockCutter_AxisZ = getattr(nd, "BlockCutter_AxisZ", None) if nd else None
        self.NiDaoGong_BlockCutter_FaceDirTags = getattr(nd, "BlockCutter_FaceDirTags", None) if nd else None
        self.NiDaoGong_BlockCutter_EdgeDirTags = getattr(nd, "BlockCutter_EdgeDirTags", None) if nd else None
        self.NiDaoGong_BlockCutter_Corner0EdgeDirs = getattr(nd, "BlockCutter_Corner0EdgeDirs", None) if nd else None
        self.NiDaoGong_BlockCutter_Log = getattr(nd, "BlockCutter_Log", None) if nd else None

        self.NiDaoGong_Align2_AlignedTool = getattr(nd, "Align2_AlignedTool", None) if nd else None
        self.NiDaoGong_Align2_XForm = getattr(nd, "Align2_XForm", None) if nd else None
        self.NiDaoGong_Align2_SourcePlane = getattr(nd, "Align2_SourcePlane", None) if nd else None
        self.NiDaoGong_Align2_TargetPlane = getattr(nd, "Align2_TargetPlane", None) if nd else None
        self.NiDaoGong_Align2_SourcePoint = getattr(nd, "Align2_SourcePoint", None) if nd else None
        self.NiDaoGong_Align2_TargetPoint = getattr(nd, "Align2_TargetPoint", None) if nd else None
        self.NiDaoGong_Align2_DebugInfo = getattr(nd, "Align2_DebugInfo", None) if nd else None

        self.NiDaoGong_GongSectionFace = getattr(nd, "GongSectionFace", None) if nd else None
        self.NiDaoGong_GongPoints = getattr(nd, "GongPoints", None) if nd else None
        self.NiDaoGong_GongInnerSection = getattr(nd, "GongInnerSection", None) if nd else None
        self.NiDaoGong_GongInnerSectionMoved = getattr(nd, "GongInnerSectionMoved", None) if nd else None
        self.NiDaoGong_GongInnerPoints = getattr(nd, "GongInnerPoints", None) if nd else None
        self.NiDaoGong_GongLoftFace = getattr(nd, "GongLoftFace", None) if nd else None
        self.NiDaoGong_GongTopFace = getattr(nd, "GongTopFace", None) if nd else None
        self.NiDaoGong_GongToolBrep = getattr(nd, "GongToolBrep", None) if nd else None
        self.NiDaoGong_GongTopPlaneA = getattr(nd, "GongTopPlaneA", None) if nd else None
        self.NiDaoGong_GongTopPlaneB = getattr(nd, "GongTopPlaneB", None) if nd else None
        self.NiDaoGong_GongLog = getattr(nd, "GongLog", None) if nd else None

        self.NiDaoGong_PF2_BasePlane = getattr(nd, "PF2_BasePlane", None) if nd else None
        self.NiDaoGong_PF2_OriginPoint = getattr(nd, "PF2_OriginPoint", None) if nd else None
        self.NiDaoGong_PF2_ResultPlane = getattr(nd, "PF2_ResultPlane", None) if nd else None
        self.NiDaoGong_PF2_Log = getattr(nd, "PF2_Log", None) if nd else None

        self.NiDaoGong_Align3_AlignedTool = getattr(nd, "Align3_AlignedTool", None) if nd else None
        self.NiDaoGong_Align3_XForm = getattr(nd, "Align3_XForm", None) if nd else None
        self.NiDaoGong_Align3_SourcePlane = getattr(nd, "Align3_SourcePlane", None) if nd else None
        self.NiDaoGong_Align3_TargetPlane = getattr(nd, "Align3_TargetPlane", None) if nd else None
        self.NiDaoGong_Align3_SourcePoint = getattr(nd, "Align3_SourcePoint", None) if nd else None
        self.NiDaoGong_Align3_TargetPoint = getattr(nd, "Align3_TargetPoint", None) if nd else None
        self.NiDaoGong_Align3_DebugInfo = getattr(nd, "Align3_DebugInfo", None) if nd else None

        self.NiDaoGong_CutByToolsLog = getattr(nd, "CutByToolsLog", None) if nd else None

        # -------------------------
        # VSG2_GA_NiDaoGong
        # -------------------------
        Geo = self.NiDaoGong_CutTimbers

        idx_sp = self.AllDict0.get("VSG2_GA_NiDaoGong__SourcePlane", 0)
        sp = _pick_from_list_by_index(self.NiDaoGong_FacePlaneList, idx_sp)

        # 目标平面：把 LuDou.FacePlaneList 先用 VSG1 的 Transform 变换，再取索引
        xform1 = _first_valid_xform(getattr(self, "VSG1_XFormRaw", None))
        ld_planes_xfm = _transform_planes(self.FacePlaneList, xform1)
        idx_tp = self.AllDict0.get("VSG2_GA_NiDaoGong__TargetPlane", 0)
        tp = _pick_from_list_by_index(ld_planes_xfm, idx_tp)

        rd = self.AllDict0.get("VSG2_GA_NiDaoGong__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG2_GA_NiDaoGong__FlipX", 0)
        fy = self.AllDict0.get("VSG2_GA_NiDaoGong__FlipY", 0)
        fz = self.AllDict0.get("VSG2_GA_NiDaoGong__FlipZ", 0)
        mx = self.AllDict0.get("VSG2_GA_NiDaoGong__MoveX", 0.0)
        my = self.AllDict0.get("VSG2_GA_NiDaoGong__MoveY", 0.0)
        mz = self.AllDict0.get("VSG2_GA_NiDaoGong__MoveZ", 0.0)

        so, to, xf, mg = _align_broadcast(
            Geo, sp, tp,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        self.VSG2_SourceOut = so
        self.VSG2_TargetOut = to
        self.VSG2_XFormRaw = xf
        self.VSG2_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG2_MovedGeo = mg

        self.LogLines.append("Step 3 完成：NiDaoGong + VSG2 对位完成。")

    # -------------------------------
    # Step 4：叠级3-乳栿劄牽 + FTPlaneFromLists::1 + VSG3 对位
    # -------------------------------
    def step4_rufuzhaqian(self):
        self.LogLines.append("Step 4：叠级3-乳栿劄牽 RuFuZhaQian + FTPlaneFromLists::1 + VSG3_GA_RuFuZhaQian 对位…")

        base_point = rg.Point3d(0, 0, 0)

        _tl = self.AllDict0.get("RuFuZhaQian__FT_timber_block_uniform_length_fen", None)
        _ql = self.AllDict0.get("RuFuZhaQian__RuFuZhaQian_QiAoSolver_length_fen", None)

        try:
            rq = RufuZhaQianSolver(
                self.DBPath,
                base_point,
                self.Refresh,
                self.ghenv,
                FT_timber_block_uniform_length_fen=_tl,
                RufuZhaQian_QiAoSolver_length_fen=_ql
            ).run()
        except Exception as e:
            rq = None
            self.LogLines.append("[ERROR] RuFuZhaQian 失败：{}".format(e))

        self.RQ_Solver = rq

        # 主输出（加前缀避免覆盖）
        self.RuFuZhaQian_CutTimbers = getattr(rq, "CutTimbers", None) if rq else None
        self.RuFuZhaQian_FailTimbers = getattr(rq, "FailTimbers", None) if rq else None
        self.RuFuZhaQian_Log = getattr(rq, "Log", None) if rq else None

        # 开发模式：把 RuFuZhaQian 的关键字段也保留（字段名按 solver 内部）
        self.RuFuZhaQian_Value = getattr(rq, "Value", None) if rq else None
        self.RuFuZhaQian_All = getattr(rq, "All", None) if rq else None
        self.RuFuZhaQian_AllDict = getattr(rq, "AllDict", None) if rq else None
        self.RuFuZhaQian_DBLog = getattr(rq, "DBLog", None) if rq else None

        self.RuFuZhaQian_TimberBrep = getattr(rq, "TimberBrep", None) if rq else None
        self.RuFuZhaQian_FaceList = getattr(rq, "FaceList", None) if rq else None
        self.RuFuZhaQian_PointList = getattr(rq, "PointList", None) if rq else None
        self.RuFuZhaQian_EdgeList = getattr(rq, "EdgeList", None) if rq else None
        self.RuFuZhaQian_CenterPoint = getattr(rq, "CenterPoint", None) if rq else None
        self.RuFuZhaQian_CenterAxisLines = getattr(rq, "CenterAxisLines", None) if rq else None
        self.RuFuZhaQian_EdgeMidPoints = getattr(rq, "EdgeMidPoints", None) if rq else None
        self.RuFuZhaQian_FacePlaneList = getattr(rq, "FacePlaneList", None) if rq else None
        self.RuFuZhaQian_Corner0Planes = getattr(rq, "Corner0Planes", None) if rq else None
        self.RuFuZhaQian_LocalAxesPlane = getattr(rq, "LocalAxesPlane", None) if rq else None
        self.RuFuZhaQian_AxisX = getattr(rq, "AxisX", None) if rq else None
        self.RuFuZhaQian_AxisY = getattr(rq, "AxisY", None) if rq else None
        self.RuFuZhaQian_AxisZ = getattr(rq, "AxisZ", None) if rq else None
        self.RuFuZhaQian_FaceDirTags = getattr(rq, "FaceDirTags", None) if rq else None
        self.RuFuZhaQian_EdgeDirTags = getattr(rq, "EdgeDirTags", None) if rq else None
        self.RuFuZhaQian_Corner0EdgeDirs = getattr(rq, "Corner0EdgeDirs", None) if rq else None

        # -------------------------
        # FTPlaneFromLists::1
        # -------------------------
        OriginPoints = getattr(rq, "EdgeMidPoints", None) if rq else None
        BasePlanes = getattr(rq, "Corner0Planes", None) if rq else None

        IndexOrigin = self.AllDict0.get("FTPlaneFromLists_1__IndexOrigin", 0)
        IndexPlane = self.AllDict0.get("FTPlaneFromLists_1__IndexPlane", 0)

        Wrap = self.AllDict0.get("FTPlaneFromLists_1__Wrap", True)

        try:
            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints, BasePlanes, IndexOrigin, IndexPlane
            )
        except Exception as e:
            BasePlane, OriginPoint, ResultPlane, Log = None, None, None, [
                "[ERROR] FTPlaneFromLists::1 失败：{}".format(e)]

        self.FTPL1_BasePlane = BasePlane
        self.FTPL1_OriginPoint = OriginPoint
        self.FTPL1_ResultPlane = ResultPlane
        self.FTPL1_Log = Log

        # -------------------------
        # VSG3_GA_RuFuZhaQian
        # -------------------------
        Geo = self.RuFuZhaQian_CutTimbers
        sp = ResultPlane

        xform1 = _first_valid_xform(getattr(self, "VSG1_XFormRaw", None))
        ld_planes_xfm = _transform_planes(self.FacePlaneList, xform1)
        idx_tp = self.AllDict0.get("VSG3_GA_RuFuZhaQian__TargetPlane", 0)
        tp = _pick_from_list_by_index(ld_planes_xfm, idx_tp)

        rd = self.AllDict0.get("VSG3_GA_RuFuZhaQian__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG3_GA_RuFuZhaQian__FlipX", 0)
        fy = self.AllDict0.get("VSG3_GA_RuFuZhaQian__FlipY", 0)
        fz = self.AllDict0.get("VSG3_GA_RuFuZhaQian__FlipZ", 0)
        mx = self.AllDict0.get("VSG3_GA_RuFuZhaQian__MoveX", 0.0)
        my = self.AllDict0.get("VSG3_GA_RuFuZhaQian__MoveY", 0.0)
        mz = self.AllDict0.get("VSG3_GA_RuFuZhaQian__MoveZ", 0.0)

        so, to, xf, mg = _align_broadcast(
            Geo, sp, tp,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        self.VSG3_SourceOut = so
        self.VSG3_TargetOut = to
        self.VSG3_XFormRaw = xf
        self.VSG3_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG3_MovedGeo = mg

        self.LogLines.append("Step 4 完成：RuFuZhaQian + FTPlaneFromLists::1 + VSG3 对位完成。")

    # -------------------------------
    # Step 5：叠级4-散枓 + 齊心枓 + FTPlaneFromLists::2/3 + VSG4 对位
    # -------------------------------
    def step5_sandou_qixindou(self):
        self.LogLines.append("Step 5：叠级4-散枓 SanDou + 齊心枓 QiXinDou + FTPlaneFromLists::2/3 + VSG4 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # -------------------------
        # 5.1 SanDou
        # -------------------------
        try:
            sd = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            sd.run()
        except Exception as e:
            sd = None
            self.LogLines.append("[ERROR] SanDou 失败：{}".format(e))

        self.SD_Solver = sd
        self.SanDou_CutTimbers = getattr(sd, "CutTimbers", None) if sd else None
        self.SanDou_FailTimbers = getattr(sd, "FailTimbers", None) if sd else None
        self.SanDou_Log = getattr(sd, "Log", None) if sd else None

        # 透出 SanDou 关键几何信息（用于后续 PFL2）
        self.SanDou_EdgeMidPoints = getattr(sd, "EdgeMidPoints", None) if sd else None
        self.SanDou_Corner0Planes = getattr(sd, "Corner0Planes", None) if sd else None
        self.SanDou_FacePlaneList = getattr(sd, "FacePlaneList", None) if sd else None

        # -------------------------
        # 5.2 QiXinDou
        # -------------------------
        try:
            qx = QiXinDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            qx.run()
        except Exception as e:
            qx = None
            self.LogLines.append("[ERROR] QiXinDou 失败：{}".format(e))

        self.QX_Solver = qx
        self.QiXinDou_CutTimbers = getattr(qx, "CutTimbers", None) if qx else None
        self.QiXinDou_FailTimbers = getattr(qx, "FailTimbers", None) if qx else None
        self.QiXinDou_Log = getattr(qx, "Log", None) if qx else None

        self.QiXinDou_FacePlaneList = getattr(qx, "FacePlaneList", None) if qx else None

        # -------------------------
        # 5.3 FTPlaneFromLists::2（OriginPoints=SanDou.EdgeMidPoints, BasePlanes=SanDou.Corner0Planes）
        # -------------------------
        OriginPoints2 = getattr(self, "SanDou_EdgeMidPoints", None)
        BasePlanes2 = getattr(self, "SanDou_Corner0Planes", None)

        IndexOrigin2 = self.AllDict0.get("FTPlaneFromLists_2__IndexOrigin", 0)
        IndexPlane2 = self.AllDict0.get("FTPlaneFromLists_2__IndexPlane", 0)
        Wrap2 = self.AllDict0.get("FTPlaneFromLists_2__Wrap", True)

        try:
            BasePlane2, OriginPoint2, ResultPlane2, Log2 = _ft_plane_from_lists_broadcast(
                OriginPoints2, BasePlanes2, IndexOrigin2, IndexPlane2, wrap=Wrap2
            )
        except Exception as e:
            BasePlane2, OriginPoint2, ResultPlane2, Log2 = None, None, None, [
                "[ERROR] FTPlaneFromLists::2 失败：{}".format(e)]

        self.FTPL2_BasePlane = BasePlane2
        self.FTPL2_OriginPoint = OriginPoint2
        self.FTPL2_ResultPlane = ResultPlane2
        self.FTPL2_Log = Log2

        # -------------------------
        # 5.4 FTPlaneFromLists::3（OriginPoints=NiDaoGong.EdgeMidPoints, BasePlanes=NiDaoGong.FacePlaneList）
        # -------------------------
        OriginPoints3 = getattr(self, "NiDaoGong_EdgeMidPoints", None)
        BasePlanes3 = getattr(self, "NiDaoGong_FacePlaneList", None)

        IndexOrigin3 = self.AllDict0.get("FTPlaneFromLists_3__IndexOrigin", 0)
        IndexPlane3 = self.AllDict0.get("FTPlaneFromLists_3__IndexPlane", 0)
        Wrap3 = self.AllDict0.get("FTPlaneFromLists_3__Wrap", True)

        try:
            BasePlane3, OriginPoint3, ResultPlane3, Log3 = _ft_plane_from_lists_broadcast(
                OriginPoints3, BasePlanes3, IndexOrigin3, IndexPlane3, wrap=Wrap3
            )
        except Exception as e:
            BasePlane3, OriginPoint3, ResultPlane3, Log3 = None, None, None, [
                "[ERROR] FTPlaneFromLists::3 失败：{}".format(e)]

        self.FTPL3_BasePlane = BasePlane3
        self.FTPL3_OriginPoint = OriginPoint3
        self.FTPL3_ResultPlane = ResultPlane3
        self.FTPL3_Log = Log3

        # -------------------------
        # 5.5 VSG4_GA_SanDou
        #   TargetPlane = Transform(FTPlaneFromLists::3.ResultPlane, VSG2.TransformOut)
        # -------------------------
        Geo_sd = self.SanDou_CutTimbers
        sp_sd = self.FTPL2_ResultPlane

        xform2 = _first_valid_xform(getattr(self, "VSG2_XFormRaw", None))
        tp_sd = None
        try:
            if isinstance(self.FTPL3_ResultPlane, list):
                tp_sd = _transform_planes(self.FTPL3_ResultPlane, xform2)
            else:
                tp_sd = _transform_plane(self.FTPL3_ResultPlane, xform2)
        except:
            tp_sd = self.FTPL3_ResultPlane

        rd = self.AllDict0.get("VSG4_GA_SanDou__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG4_GA_SanDou__FlipX", 0)
        fy = self.AllDict0.get("VSG4_GA_SanDou__FlipY", 0)
        fz = self.AllDict0.get("VSG4_GA_SanDou__FlipZ", 0)
        mx = self.AllDict0.get("VSG4_GA_SanDou__MoveX", 0.0)
        my = self.AllDict0.get("VSG4_GA_SanDou__MoveY", 0.0)
        mz = self.AllDict0.get("VSG4_GA_SanDou__MoveZ", 0.0)

        so, to, xf, mg = _align_broadcast(
            Geo_sd, sp_sd, tp_sd,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        self.VSG4_SanDou_SourceOut = so
        self.VSG4_SanDou_TargetOut = to
        self.VSG4_SanDou_XFormRaw = xf
        self.VSG4_SanDou_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG4_SanDou_MovedGeo = mg

        # -------------------------
        # 5.6 VSG4_GA_QiXinDou（注意：数据库键名按你给的 VSG5_*）
        # -------------------------
        Geo_qx = self.QiXinDou_CutTimbers

        idx_sp_qx = self.AllDict0.get("VSG5_GA_QiXinDou__SourcePlane", 0)
        sp_qx = _pick_from_list_by_index(self.QiXinDou_FacePlaneList, idx_sp_qx)

        nd_planes_xfm = _transform_planes(getattr(self, "NiDaoGong_FacePlaneList", None), xform2)
        idx_tp_qx = self.AllDict0.get("VSG5_GA_QiXinDou__TargetPlane", 0)
        tp_qx = _pick_from_list_by_index(nd_planes_xfm, idx_tp_qx)

        rd = self.AllDict0.get("VSG5_GA_QiXinDou__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG5_GA_QiXinDou__FlipX", 0)
        fy = self.AllDict0.get("VSG5_GA_QiXinDou__FlipY", 0)
        fz = self.AllDict0.get("VSG5_GA_QiXinDou__FlipZ", 0)
        mx = self.AllDict0.get("VSG5_GA_QiXinDou__MoveX", 0.0)
        my = self.AllDict0.get("VSG5_GA_QiXinDou__MoveY", 0.0)
        mz = self.AllDict0.get("VSG5_GA_QiXinDou__MoveZ", 0.0)

        so, to, xf, mg = _align_broadcast(
            Geo_qx, sp_qx, tp_qx,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        self.VSG4_QiXinDou_SourceOut = so
        self.VSG4_QiXinDou_TargetOut = to
        self.VSG4_QiXinDou_XFormRaw = xf
        self.VSG4_QiXinDou_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG4_QiXinDou_MovedGeo = mg

        self.LogLines.append("Step 5 完成：SanDou/QiXinDou + FTPlaneFromLists::2/3 + VSG4 对位完成。")

    # -------------------------------
    # Step N：组装输出
    # -------------------------------

    # -------------------------------
    # Step 6：叠级5-羅漢方/素方 + VSG5 对位（可选加入 Assembly）
    # -------------------------------
    def step6_sufang_luohan(self):
        self.LogLines.append("Step 6：叠级5-羅漢方/素方 SuFangLuoHanFang + VSG5_GA_SuFangLuoHanFang 对位（可选）…")

        # ---------- 参数（数据库优先，缺省用组件默认）----------
        length_fen = self.AllDict0.get("SuFangLuoHanFang__length_fen", 32.0)
        width_fen = self.AllDict0.get("SuFangLuoHanFang__width_fen", 32.0)
        height_fen = self.AllDict0.get("SuFangLuoHanFang__height_fen", 20.0)

        try:
            length_fen = float(length_fen)
        except:
            length_fen = 32.0
        try:
            width_fen = float(width_fen)
        except:
            width_fen = 32.0
        try:
            height_fen = float(height_fen)
        except:
            height_fen = 20.0

        base_point = rg.Point3d(0.0, 0.0, 0.0)

        # reference_plane：避免使用 rg.Plane.WorldXZ（RhinoCommon 没有此属性）
        # 这里沿用数据库常用写法 "WorldXZ"；如库里提供则优先使用
        reference_plane = self.AllDict0.get("SuFangLuoHanFang__reference_plane", "WorldXZ")

        ref_pl = _resolve_reference_plane(reference_plane, base_point)
        self.SuFang_ReferencePlane = ref_pl

        # ---------- 构造木料（与独立组件 SuFangLuoHanFang 一致的输出命名）----------
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
                ref_pl,
            )

            self.SuFang_TimberBrep = timber_brep
            self.SuFang_FaceList = faces
            self.SuFang_PointList = points
            self.SuFang_EdgeList = edges
            self.SuFang_CenterPoint = center_pt
            self.SuFang_CenterAxisLines = center_axes
            self.SuFang_EdgeMidPoints = edge_midpts
            self.SuFang_FacePlaneList = face_planes
            self.SuFang_Corner0Planes = corner0_planes
            self.SuFang_LocalAxesPlane = local_axes_plane
            self.SuFang_AxisX = axis_x
            self.SuFang_AxisY = axis_y
            self.SuFang_AxisZ = axis_z
            self.SuFang_FaceDirTags = face_tags
            self.SuFang_EdgeDirTags = edge_tags
            self.SuFang_Corner0EdgeDirs = corner0_dirs
            self.SuFang_Log = log_lines

        except Exception as e:
            self.SuFang_TimberBrep = None
            self.SuFang_FaceList = []
            self.SuFang_PointList = []
            self.SuFang_EdgeList = []
            self.SuFang_CenterPoint = None
            self.SuFang_CenterAxisLines = []
            self.SuFang_EdgeMidPoints = []
            self.SuFang_FacePlaneList = []
            self.SuFang_Corner0Planes = []
            self.SuFang_LocalAxesPlane = None
            self.SuFang_AxisX = None
            self.SuFang_AxisY = None
            self.SuFang_AxisZ = None
            self.SuFang_FaceDirTags = []
            self.SuFang_EdgeDirTags = []
            self.SuFang_Corner0EdgeDirs = []
            self.SuFang_Log = ["错误: {}".format(e)]

        # ---------- VSG5_GA_SuFangLuoHanFang ----------
        # Geo = TimberBrep
        Geo = getattr(self, "SuFang_TimberBrep", None)

        # SourcePlane = FacePlaneList[ idx ]
        idx_sp = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__SourcePlane", 0)
        sp = _pick_from_list_by_index(getattr(self, "SuFang_FacePlaneList", None), idx_sp)

        # TargetPlane：与 VSG4_GA_QiXinDou 的输入 TargetPlane 同值（即：NiDaoGong.FacePlaneList 经 VSG2 变换后的指定面）
        tp = getattr(self, "VSG4_QiXinDou_TargetPlaneUsed", None)
        if tp is None:
            # 兜底：重新按 Step5 的逻辑计算一次
            xform2 = _first_valid_xform(getattr(self, "VSG2_XFormRaw", None))
            nd_planes_xfm = _transform_planes(getattr(self, "NiDaoGong_FacePlaneList", None), xform2)
            idx_tp_qx = self.AllDict0.get("VSG5_GA_QiXinDou__TargetPlane", 0)
            tp = _pick_from_list_by_index(nd_planes_xfm, idx_tp_qx)

        self.VSG5_SuFang_TargetPlaneUsed = tp

        rd = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__RotateDeg", 0.0)
        fx = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipX", 0)
        fy = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipY", 0)
        fz = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__FlipZ", 0)
        mx = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveX", 0.0)
        my = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveY", 0.0)
        mz = self.AllDict0.get("VSG6_GA_SuFangLuoHanFang__MoveZ", 0.0)

        so, to, xf, mg = _align_broadcast(
            Geo, sp, tp,
            rotate_deg=rd,
            flip_x=fx, flip_y=fy, flip_z=fz,
            move_x=mx, move_y=my, move_z=mz
        )

        self.VSG5_SuFang_SourceOut = so
        self.VSG5_SuFang_TargetOut = to
        self.VSG5_SuFang_XFormRaw = xf
        self.VSG5_SuFang_TransformOut = [ght.GH_Transform(x) if x is not None else None for x in _ensure_list(xf)]
        self.VSG5_SuFang_MovedGeo = mg

        self.LogLines.append(
            "Step 6 完成：SuFangLuoHanFang + VSG5 对位完成（是否加入 Assembly 由 IncludeSuFangLuoHanFang 决定）。")

    def stepN_assemble(self):
        parts = []
        _flatten_items(getattr(self, "VSG1_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG2_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG3_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG4_SanDou_MovedGeo", None), parts)
        _flatten_items(getattr(self, "VSG4_QiXinDou_MovedGeo", None), parts)
        if getattr(self, "IncludeSuFangLuoHanFang", False):
            _flatten_items(getattr(self, "VSG5_SuFang_MovedGeo", None), parts)
        self.ComponentAssembly = parts
        self.LogLines.append("Assemble 完成：ComponentAssembly items={}".format(len(parts)))

    # -------------------------------
    # run
    # -------------------------------
    def run(self):
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        self.step1_read_db()
        self.step2_ludou()
        self.step3_nidaogong()
        self.step4_rufuzhaqian()
        self.step5_sandou_qixindou()
        self.step6_sufang_luohan()
        self.stepN_assemble()

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

    try:
        _rf = Refresh
    except:
        _rf = False

    try:
        _inc_sufang = IncludeSuFangLuoHanFang
    except:
        _inc_sufang = False

    solver = BaTouJiaoXiangZuoComponentAssemblySolver(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        IncludeSuFangLuoHanFang=_inc_sufang,
        ghenv=ghenv
    ).run()

    # --------- 最终成品 ---------
    ComponentAssembly = getattr(solver, "ComponentAssembly", None)
    Log = getattr(solver, "Log", None)

    # --------- Step 1 ---------
    Value0 = getattr(solver, "Value0", None)
    All0 = getattr(solver, "All0", None)
    AllDict0 = getattr(solver, "AllDict0", None)
    DBLog0 = getattr(solver, "DBLog0", None)

    # --------- Step 2：LuDou（内部尽量全保留）---------
    Value = getattr(solver, "Value", None)
    All = getattr(solver, "All", None)
    All_dict = getattr(solver, "All_dict", None)

    TimberBrep = getattr(solver, "TimberBrep", None)
    FaceList = getattr(solver, "FaceList", None)
    PointList = getattr(solver, "PointList", None)
    EdgeList = getattr(solver, "EdgeList", None)
    CenterPoint = getattr(solver, "CenterPoint", None)
    CenterAxisLines = getattr(solver, "CenterAxisLines", None)
    EdgeMidPoints = getattr(solver, "EdgeMidPoints", None)
    FacePlaneList = getattr(solver, "FacePlaneList", None)
    Corner0Planes = getattr(solver, "Corner0Planes", None)
    LocalAxesPlane = getattr(solver, "LocalAxesPlane", None)
    AxisX = getattr(solver, "AxisX", None)
    AxisY = getattr(solver, "AxisY", None)
    AxisZ = getattr(solver, "AxisZ", None)
    FaceDirTags = getattr(solver, "FaceDirTags", None)
    EdgeDirTags = getattr(solver, "EdgeDirTags", None)
    Corner0EdgeDirs = getattr(solver, "Corner0EdgeDirs", None)

    BasePlane1 = getattr(solver, "BasePlane1", None)
    OriginPoint1 = getattr(solver, "OriginPoint1", None)
    ResultPlane1 = getattr(solver, "ResultPlane1", None)

    BasePlane2 = getattr(solver, "BasePlane2", None)
    OriginPoint2 = getattr(solver, "OriginPoint2", None)
    ResultPlane2 = getattr(solver, "ResultPlane2", None)

    BasePlane3 = getattr(solver, "BasePlane3", None)
    OriginPoint3 = getattr(solver, "OriginPoint3", None)
    ResultPlane3 = getattr(solver, "ResultPlane3", None)

    ToolBrep = getattr(solver, "ToolBrep", None)
    BasePoint = getattr(solver, "BasePoint", None)
    BaseLine = getattr(solver, "BaseLine", None)
    SecPlane = getattr(solver, "SecPlane", None)
    FacePlane = getattr(solver, "FacePlane", None)

    AlignedTool = getattr(solver, "AlignedTool", None)
    XForm = getattr(solver, "XForm", None)
    SourcePlane = getattr(solver, "SourcePlane", None)
    TargetPlane = getattr(solver, "TargetPlane", None)
    SourcePoint = getattr(solver, "SourcePoint", None)
    TargetPoint = getattr(solver, "TargetPoint", None)
    DebugInfo = getattr(solver, "DebugInfo", None)

    BlockTimbers = getattr(solver, "BlockTimbers", None)

    AlignedTool2 = getattr(solver, "AlignedTool2", None)
    XForm2 = getattr(solver, "XForm2", None)
    SourcePlane2 = getattr(solver, "SourcePlane2", None)
    TargetPlane2 = getattr(solver, "TargetPlane2", None)
    SourcePoint2 = getattr(solver, "SourcePoint2", None)
    TargetPoint2 = getattr(solver, "TargetPoint2", None)
    DebugInfo2 = getattr(solver, "DebugInfo2", None)

    CutTimbers = getattr(solver, "CutTimbers", None)
    FailTimbers = getattr(solver, "FailTimbers", None)
    LuDouLog = getattr(solver, "LuDouLog", None)

    # --------- Step 2：VSG1_GA_LuDou ---------
    VSG1_SourceOut = getattr(solver, "VSG1_SourceOut", None)
    VSG1_TargetOut = getattr(solver, "VSG1_TargetOut", None)
    VSG1_TransformOut = getattr(solver, "VSG1_TransformOut", None)
    VSG1_MovedGeo = getattr(solver, "VSG1_MovedGeo", None)

    # --------- Step 3：NiDaoGong ---------
    NiDaoGong_CutTimbers = getattr(solver, "NiDaoGong_CutTimbers", None)
    NiDaoGong_FailTimbers = getattr(solver, "NiDaoGong_FailTimbers", None)
    NiDaoGong_Log = getattr(solver, "NiDaoGong_Log", None)

    NiDaoGong_Value = getattr(solver, "NiDaoGong_Value", None)
    NiDaoGong_All = getattr(solver, "NiDaoGong_All", None)
    NiDaoGong_AllDict = getattr(solver, "NiDaoGong_AllDict", None)
    NiDaoGong_DBLog = getattr(solver, "NiDaoGong_DBLog", None)

    NiDaoGong_TimberBrep = getattr(solver, "NiDaoGong_TimberBrep", None)
    NiDaoGong_FaceList = getattr(solver, "NiDaoGong_FaceList", None)
    NiDaoGong_PointList = getattr(solver, "NiDaoGong_PointList", None)
    NiDaoGong_EdgeList = getattr(solver, "NiDaoGong_EdgeList", None)
    NiDaoGong_CenterPoint = getattr(solver, "NiDaoGong_CenterPoint", None)
    NiDaoGong_CenterAxisLines = getattr(solver, "NiDaoGong_CenterAxisLines", None)
    NiDaoGong_EdgeMidPoints = getattr(solver, "NiDaoGong_EdgeMidPoints", None)
    NiDaoGong_FacePlaneList = getattr(solver, "NiDaoGong_FacePlaneList", None)
    NiDaoGong_Corner0Planes = getattr(solver, "NiDaoGong_Corner0Planes", None)
    NiDaoGong_LocalAxesPlane = getattr(solver, "NiDaoGong_LocalAxesPlane", None)
    NiDaoGong_AxisX = getattr(solver, "NiDaoGong_AxisX", None)
    NiDaoGong_AxisY = getattr(solver, "NiDaoGong_AxisY", None)
    NiDaoGong_AxisZ = getattr(solver, "NiDaoGong_AxisZ", None)
    NiDaoGong_FaceDirTags = getattr(solver, "NiDaoGong_FaceDirTags", None)
    NiDaoGong_EdgeDirTags = getattr(solver, "NiDaoGong_EdgeDirTags", None)
    NiDaoGong_Corner0EdgeDirs = getattr(solver, "NiDaoGong_Corner0EdgeDirs", None)

    NiDaoGong_JuanShaToolBrep = getattr(solver, "NiDaoGong_JuanShaToolBrep", None)
    NiDaoGong_JuanShaSectionEdges = getattr(solver, "NiDaoGong_JuanShaSectionEdges", None)
    NiDaoGong_JuanShaHL_Intersection = getattr(solver, "NiDaoGong_JuanShaHL_Intersection", None)
    NiDaoGong_JuanShaHeightFacePlane = getattr(solver, "NiDaoGong_JuanShaHeightFacePlane", None)
    NiDaoGong_JuanShaLengthFacePlane = getattr(solver, "NiDaoGong_JuanShaLengthFacePlane", None)
    NiDaoGong_JuanShaLog = getattr(solver, "NiDaoGong_JuanShaLog", None)

    NiDaoGong_PF1_BasePlane = getattr(solver, "NiDaoGong_PF1_BasePlane", None)
    NiDaoGong_PF1_OriginPoint = getattr(solver, "NiDaoGong_PF1_OriginPoint", None)
    NiDaoGong_PF1_ResultPlane = getattr(solver, "NiDaoGong_PF1_ResultPlane", None)
    NiDaoGong_PF1_Log = getattr(solver, "NiDaoGong_PF1_Log", None)

    NiDaoGong_Align1_AlignedTool = getattr(solver, "NiDaoGong_Align1_AlignedTool", None)
    NiDaoGong_Align1_XForm = getattr(solver, "NiDaoGong_Align1_XForm", None)
    NiDaoGong_Align1_SourcePlane = getattr(solver, "NiDaoGong_Align1_SourcePlane", None)
    NiDaoGong_Align1_TargetPlane = getattr(solver, "NiDaoGong_Align1_TargetPlane", None)
    NiDaoGong_Align1_SourcePoint = getattr(solver, "NiDaoGong_Align1_SourcePoint", None)
    NiDaoGong_Align1_TargetPoint = getattr(solver, "NiDaoGong_Align1_TargetPoint", None)
    NiDaoGong_Align1_DebugInfo = getattr(solver, "NiDaoGong_Align1_DebugInfo", None)

    NiDaoGong_BlockCutter_TimberBrep = getattr(solver, "NiDaoGong_BlockCutter_TimberBrep", None)
    NiDaoGong_BlockCutter_FaceList = getattr(solver, "NiDaoGong_BlockCutter_FaceList", None)
    NiDaoGong_BlockCutter_PointList = getattr(solver, "NiDaoGong_BlockCutter_PointList", None)
    NiDaoGong_BlockCutter_EdgeList = getattr(solver, "NiDaoGong_BlockCutter_EdgeList", None)
    NiDaoGong_BlockCutter_CenterPoint = getattr(solver, "NiDaoGong_BlockCutter_CenterPoint", None)
    NiDaoGong_BlockCutter_CenterAxisLines = getattr(solver, "NiDaoGong_BlockCutter_CenterAxisLines", None)
    NiDaoGong_BlockCutter_EdgeMidPoints = getattr(solver, "NiDaoGong_BlockCutter_EdgeMidPoints", None)
    NiDaoGong_BlockCutter_FacePlaneList = getattr(solver, "NiDaoGong_BlockCutter_FacePlaneList", None)
    NiDaoGong_BlockCutter_Corner0Planes = getattr(solver, "NiDaoGong_BlockCutter_Corner0Planes", None)
    NiDaoGong_BlockCutter_LocalAxesPlane = getattr(solver, "NiDaoGong_BlockCutter_LocalAxesPlane", None)
    NiDaoGong_BlockCutter_AxisX = getattr(solver, "NiDaoGong_BlockCutter_AxisX", None)
    NiDaoGong_BlockCutter_AxisY = getattr(solver, "NiDaoGong_BlockCutter_AxisY", None)
    NiDaoGong_BlockCutter_AxisZ = getattr(solver, "NiDaoGong_BlockCutter_AxisZ", None)
    NiDaoGong_BlockCutter_FaceDirTags = getattr(solver, "NiDaoGong_BlockCutter_FaceDirTags", None)
    NiDaoGong_BlockCutter_EdgeDirTags = getattr(solver, "NiDaoGong_BlockCutter_EdgeDirTags", None)
    NiDaoGong_BlockCutter_Corner0EdgeDirs = getattr(solver, "NiDaoGong_BlockCutter_Corner0EdgeDirs", None)
    NiDaoGong_BlockCutter_Log = getattr(solver, "NiDaoGong_BlockCutter_Log", None)

    NiDaoGong_Align2_AlignedTool = getattr(solver, "NiDaoGong_Align2_AlignedTool", None)
    NiDaoGong_Align2_XForm = getattr(solver, "NiDaoGong_Align2_XForm", None)
    NiDaoGong_Align2_SourcePlane = getattr(solver, "NiDaoGong_Align2_SourcePlane", None)
    NiDaoGong_Align2_TargetPlane = getattr(solver, "NiDaoGong_Align2_TargetPlane", None)
    NiDaoGong_Align2_SourcePoint = getattr(solver, "NiDaoGong_Align2_SourcePoint", None)
    NiDaoGong_Align2_TargetPoint = getattr(solver, "NiDaoGong_Align2_TargetPoint", None)
    NiDaoGong_Align2_DebugInfo = getattr(solver, "NiDaoGong_Align2_DebugInfo", None)

    NiDaoGong_GongSectionFace = getattr(solver, "NiDaoGong_GongSectionFace", None)
    NiDaoGong_GongPoints = getattr(solver, "NiDaoGong_GongPoints", None)
    NiDaoGong_GongInnerSection = getattr(solver, "NiDaoGong_GongInnerSection", None)
    NiDaoGong_GongInnerSectionMoved = getattr(solver, "NiDaoGong_GongInnerSectionMoved", None)
    NiDaoGong_GongInnerPoints = getattr(solver, "NiDaoGong_GongInnerPoints", None)
    NiDaoGong_GongLoftFace = getattr(solver, "NiDaoGong_GongLoftFace", None)
    NiDaoGong_GongTopFace = getattr(solver, "NiDaoGong_GongTopFace", None)
    NiDaoGong_GongToolBrep = getattr(solver, "NiDaoGong_GongToolBrep", None)
    NiDaoGong_GongTopPlaneA = getattr(solver, "NiDaoGong_GongTopPlaneA", None)
    NiDaoGong_GongTopPlaneB = getattr(solver, "NiDaoGong_GongTopPlaneB", None)
    NiDaoGong_GongLog = getattr(solver, "NiDaoGong_GongLog", None)

    NiDaoGong_PF2_BasePlane = getattr(solver, "NiDaoGong_PF2_BasePlane", None)
    NiDaoGong_PF2_OriginPoint = getattr(solver, "NiDaoGong_PF2_OriginPoint", None)
    NiDaoGong_PF2_ResultPlane = getattr(solver, "NiDaoGong_PF2_ResultPlane", None)
    NiDaoGong_PF2_Log = getattr(solver, "NiDaoGong_PF2_Log", None)

    NiDaoGong_Align3_AlignedTool = getattr(solver, "NiDaoGong_Align3_AlignedTool", None)
    NiDaoGong_Align3_XForm = getattr(solver, "NiDaoGong_Align3_XForm", None)
    NiDaoGong_Align3_SourcePlane = getattr(solver, "NiDaoGong_Align3_SourcePlane", None)
    NiDaoGong_Align3_TargetPlane = getattr(solver, "NiDaoGong_Align3_TargetPlane", None)
    NiDaoGong_Align3_SourcePoint = getattr(solver, "NiDaoGong_Align3_SourcePoint", None)
    NiDaoGong_Align3_TargetPoint = getattr(solver, "NiDaoGong_Align3_TargetPoint", None)
    NiDaoGong_Align3_DebugInfo = getattr(solver, "NiDaoGong_Align3_DebugInfo", None)

    NiDaoGong_CutByToolsLog = getattr(solver, "NiDaoGong_CutByToolsLog", None)

    # --------- Step 3：VSG2_GA_NiDaoGong ---------
    VSG2_SourceOut = getattr(solver, "VSG2_SourceOut", None)
    VSG2_TargetOut = getattr(solver, "VSG2_TargetOut", None)
    VSG2_TransformOut = getattr(solver, "VSG2_TransformOut", None)
    VSG2_MovedGeo = getattr(solver, "VSG2_MovedGeo", None)

    # --------- Step 4：RuFuZhaQian ---------
    RuFuZhaQian_CutTimbers = getattr(solver, "RuFuZhaQian_CutTimbers", None)
    RuFuZhaQian_FailTimbers = getattr(solver, "RuFuZhaQian_FailTimbers", None)
    RuFuZhaQian_Log = getattr(solver, "RuFuZhaQian_Log", None)

    RuFuZhaQian_Value = getattr(solver, "RuFuZhaQian_Value", None)
    RuFuZhaQian_All = getattr(solver, "RuFuZhaQian_All", None)
    RuFuZhaQian_AllDict = getattr(solver, "RuFuZhaQian_AllDict", None)
    RuFuZhaQian_DBLog = getattr(solver, "RuFuZhaQian_DBLog", None)

    RuFuZhaQian_TimberBrep = getattr(solver, "RuFuZhaQian_TimberBrep", None)
    RuFuZhaQian_FaceList = getattr(solver, "RuFuZhaQian_FaceList", None)
    RuFuZhaQian_PointList = getattr(solver, "RuFuZhaQian_PointList", None)
    RuFuZhaQian_EdgeList = getattr(solver, "RuFuZhaQian_EdgeList", None)
    RuFuZhaQian_CenterPoint = getattr(solver, "RuFuZhaQian_CenterPoint", None)
    RuFuZhaQian_CenterAxisLines = getattr(solver, "RuFuZhaQian_CenterAxisLines", None)
    RuFuZhaQian_EdgeMidPoints = getattr(solver, "RuFuZhaQian_EdgeMidPoints", None)
    RuFuZhaQian_FacePlaneList = getattr(solver, "RuFuZhaQian_FacePlaneList", None)
    RuFuZhaQian_Corner0Planes = getattr(solver, "RuFuZhaQian_Corner0Planes", None)
    RuFuZhaQian_LocalAxesPlane = getattr(solver, "RuFuZhaQian_LocalAxesPlane", None)
    RuFuZhaQian_AxisX = getattr(solver, "RuFuZhaQian_AxisX", None)
    RuFuZhaQian_AxisY = getattr(solver, "RuFuZhaQian_AxisY", None)
    RuFuZhaQian_AxisZ = getattr(solver, "RuFuZhaQian_AxisZ", None)
    RuFuZhaQian_FaceDirTags = getattr(solver, "RuFuZhaQian_FaceDirTags", None)
    RuFuZhaQian_EdgeDirTags = getattr(solver, "RuFuZhaQian_EdgeDirTags", None)
    RuFuZhaQian_Corner0EdgeDirs = getattr(solver, "RuFuZhaQian_Corner0EdgeDirs", None)

    # --------- Step 4：FTPlaneFromLists::1 ---------
    FTPL1_BasePlane = getattr(solver, "FTPL1_BasePlane", None)
    FTPL1_OriginPoint = getattr(solver, "FTPL1_OriginPoint", None)
    FTPL1_ResultPlane = getattr(solver, "FTPL1_ResultPlane", None)
    FTPL1_Log = getattr(solver, "FTPL1_Log", None)

    # --------- Step 4：VSG3_GA_RuFuZhaQian ---------
    VSG3_SourceOut = getattr(solver, "VSG3_SourceOut", None)
    VSG3_TargetOut = getattr(solver, "VSG3_TargetOut", None)
    VSG3_TransformOut = getattr(solver, "VSG3_TransformOut", None)
    VSG3_MovedGeo = getattr(solver, "VSG3_MovedGeo", None)

    # --------- Step 5：SanDou ---------
    SanDou_CutTimbers = getattr(solver, "SanDou_CutTimbers", None)
    SanDou_FailTimbers = getattr(solver, "SanDou_FailTimbers", None)
    SanDou_Log = getattr(solver, "SanDou_Log", None)

    SanDou_EdgeMidPoints = getattr(solver, "SanDou_EdgeMidPoints", None)
    SanDou_Corner0Planes = getattr(solver, "SanDou_Corner0Planes", None)
    SanDou_FacePlaneList = getattr(solver, "SanDou_FacePlaneList", None)

    # --------- Step 5：QiXinDou ---------
    QiXinDou_CutTimbers = getattr(solver, "QiXinDou_CutTimbers", None)
    QiXinDou_FailTimbers = getattr(solver, "QiXinDou_FailTimbers", None)
    QiXinDou_Log = getattr(solver, "QiXinDou_Log", None)

    QiXinDou_FacePlaneList = getattr(solver, "QiXinDou_FacePlaneList", None)

    # --------- Step 5：FTPlaneFromLists::2 ---------
    FTPL2_BasePlane = getattr(solver, "FTPL2_BasePlane", None)
    FTPL2_OriginPoint = getattr(solver, "FTPL2_OriginPoint", None)
    FTPL2_ResultPlane = getattr(solver, "FTPL2_ResultPlane", None)
    FTPL2_Log = getattr(solver, "FTPL2_Log", None)

    # --------- Step 5：FTPlaneFromLists::3 ---------
    FTPL3_BasePlane = getattr(solver, "FTPL3_BasePlane", None)
    FTPL3_OriginPoint = getattr(solver, "FTPL3_OriginPoint", None)
    FTPL3_ResultPlane = getattr(solver, "FTPL3_ResultPlane", None)
    FTPL3_Log = getattr(solver, "FTPL3_Log", None)

    # --------- Step 5：VSG4_GA_SanDou ---------
    VSG4_SanDou_SourceOut = getattr(solver, "VSG4_SanDou_SourceOut", None)
    VSG4_SanDou_TargetOut = getattr(solver, "VSG4_SanDou_TargetOut", None)
    VSG4_SanDou_TransformOut = getattr(solver, "VSG4_SanDou_TransformOut", None)
    VSG4_SanDou_MovedGeo = getattr(solver, "VSG4_SanDou_MovedGeo", None)

    # --------- Step 5：VSG4_GA_QiXinDou ---------
    VSG4_QiXinDou_SourceOut = getattr(solver, "VSG4_QiXinDou_SourceOut", None)
    VSG4_QiXinDou_TargetOut = getattr(solver, "VSG4_QiXinDou_TargetOut", None)
    VSG4_QiXinDou_TransformOut = getattr(solver, "VSG4_QiXinDou_TransformOut", None)
    VSG4_QiXinDou_MovedGeo = getattr(solver, "VSG4_QiXinDou_MovedGeo", None)

    # --------- Step 6：SuFangLuoHanFang（羅漢方/素方）---------
    SuFang_TimberBrep = getattr(solver, "SuFang_TimberBrep", None)
    SuFang_FacePlaneList = getattr(solver, "SuFang_FacePlaneList", None)
    SuFang_Corner0Planes = getattr(solver, "SuFang_Corner0Planes", None)
    SuFang_EdgeMidPoints = getattr(solver, "SuFang_EdgeMidPoints", None)
    SuFang_Log = getattr(solver, "SuFang_Log", None)

    # --------- Step 6：VSG5_GA_SuFangLuoHanFang ---------
    VSG5_SuFang_SourceOut = getattr(solver, "VSG5_SuFang_SourceOut", None)
    VSG5_SuFang_TargetOut = getattr(solver, "VSG5_SuFang_TargetOut", None)
    VSG5_SuFang_TransformOut = getattr(solver, "VSG5_SuFang_TransformOut", None)
    VSG5_SuFang_MovedGeo = getattr(solver, "VSG5_SuFang_MovedGeo", None)


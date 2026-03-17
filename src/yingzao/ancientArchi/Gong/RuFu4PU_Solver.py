"""
GhPython Component: RuFu4PU_Solver_STEP1_2
-----------------------------------------
将用于构建 乳栿[四鋪作]（RuFu4PU） 的 GH 连线流程（部分步骤）合并为一个单独 ghpy 组件。

✅ 当前实现到 Step 2（对位组装）：
Step 1：DBJsonReader（DG_Dou / type_code=RuFu4PU / params_json / export_all=True）
Step 2：ShuaTou4RuFU + RuFuInner + PlaneFromLists::1 + PlaneFromLists::2 + GeoAligner::1

Inputs (GH 建议配置)
--------------------------------------------------------------
DBPath      : str        Access:item
base_point  : Point3d    Access:item   (木料定位点)
Refresh     : bool       Access:item   (刷新/重读数据库)

Outputs (面向使用者)
--------------------------------------------------------------
CutTimbers  : list[Geometry]
FailTimbers : list[Geometry]
Log         : list[str]

Notes
--------------------------------------------------------------
1) 所有 DB 参数只在 Step1 读取一次，后续均从 All / AllDict 取值；
2) PlaneFromLists 支持 IndexOrigin / IndexPlane 标量或列表，并做 GH 风格广播；
3) 若输出出现 System.Collections.Generic.List`1[System.Object] 这类嵌套，使用 deep_flatten 递归拍平；
4) developer-friendly 输出区：把 solver 成员变量逐一同名输出（必要时加前缀避免重名）。
"""

import Rhino.Geometry as rg
import scriptcontext as sc

# yingzao.ancientArchi：按你要求，直接调用库方法，不在此重复实现
from yingzao.ancientArchi import (
    DBJsonReader,
    FTPlaneFromLists,
    GeoAligner_xfm,
    ShuaTou4RuFu_4PU,
    RuFuInner4PUSolver,
)

import Grasshopper.Kernel.Types as ght


# ==============================================================
# 通用工具函数（参考 LingGongSolver 的风格，但不照搬业务步骤）
# ==============================================================

def _is_gh_scalar_geometry(x):
    # RhinoCommon 常见几何：当作“原子”，不要尝试迭代
    return isinstance(x, (
        rg.GeometryBase,
        rg.Point3d,
        rg.Vector3d,
        rg.Plane,
        rg.Transform,
    ))

def to_list(x):
    """标量 → [标量]；list/tuple → list(x)；GH 的 .NET List → list(x)（几何除外）"""
    if x is None:
        return []
    if _is_gh_scalar_geometry(x):
        return [x]
    if isinstance(x, (list, tuple)):
        return list(x)
    # 处理 System.Collections.Generic.List[object] 等
    try:
        return list(x)
    except:
        return [x]

def deep_flatten(x):
    """
    递归拍平 list/tuple/NET List 等容器，但 Rhino 几何对象视为原子。
    解决输出端出现：
      System.Collections.Generic.List`1[System.Object]
    """
    if x is None:
        return []
    if _is_gh_scalar_geometry(x):
        return [x]
    if isinstance(x, (str, bytes)):
        return [x]
    if isinstance(x, (list, tuple)):
        out = []
        for it in x:
            out.extend(deep_flatten(it))
        return out
    # .NET IEnumerable
    try:
        seq = list(x)
        out = []
        for it in seq:
            out.extend(deep_flatten(it))
        return out
    except:
        return [x]

def all_to_dict(all_list):
    """
    All = [('A',1),('B',[1,2])] → dict
    """
    d = {}
    if all_list is None:
        return d
    for item in all_list:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        k = item[0]
        v = item[1]
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

def _param_length(val):
    """返回参数长度：list/tuple → len；None → 0；其它标量 → 1。"""
    if isinstance(val, (list, tuple)):
        return len(val)
    if val is None:
        return 0
    return 1

def _broadcast_param(val, n):
    """
    广播/截断参数到长度 n（GH 风格）：
    - list/tuple:
        * len==0 → [None]*n
        * 0<len<n → 用最后一个补齐
        * len>=n → 取前 n
    - scalar → [scalar]*n
    """
    if isinstance(val, (list, tuple)):
        seq = list(val)
        l = len(seq)
        if l == 0:
            return [None] * n
        if l >= n:
            return seq[:n]
        last = seq[-1]
        return seq + [last] * (n - l)
    else:
        return [val] * n

def make_ref_plane(mode="WorldXZ", origin=None):
    """
    注意：参考平面为 GH 的 XY / XZ / YZ 约定（按你的描述）：
    XY: X=(1,0,0) Y=(0,1,0) Z=(0,0,1)
    XZ: X=(1,0,0) Y=(0,0,1) Z=(0,-1,0)
    YZ: X=(0,1,0) Y=(0,0,1) Z=(1,0,0)
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)

    s = str(mode) if mode is not None else "WorldXZ"
    s = s.strip()

    if s in ("WorldXY", "XY", "PlaneXY"):
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if s in ("WorldYZ", "YZ", "PlaneYZ"):
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


# ==============================================================
# 主 Solver 类 —— RuFu4PU_Solver_STEP1_2
# ==============================================================

class RuFu4PU_Solver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = base_point if isinstance(base_point, rg.Point3d) else rg.Point3d(0, 0, 0)
        self.Refresh = bool(Refresh) if Refresh is not None else False
        self.ghenv = ghenv

        # --------------------------
        # Step 1：数据库读取（All / AllDict）
        # --------------------------
        self.Value = None
        self.All_1 = None          # 注意：保留步骤号，避免后续步骤覆盖
        self.AllDict_1 = {}
        self.DBLog_1 = []

        # 全局日志
        self.Log = []

        # --------------------------
        # Step 2：子 Solver 输出（加前缀避免重名）
        # --------------------------
        # ShuaTou4RuFU
        self.ShuaTou4RuFU__CutTimbers = []
        self.ShuaTou4RuFU__FailTimbers = []
        self.ShuaTou4RuFU__Log = []

        self.ShuaTou4RuFU__All = None
        self.ShuaTou4RuFU__AllDict = {}
        self.ShuaTou4RuFU__DBLog = []
        self.ShuaTou4RuFU__TimberBrep = None
        self.ShuaTou4RuFU__FaceList = []
        self.ShuaTou4RuFU__PointList = []
        self.ShuaTou4RuFU__EdgeList = []
        self.ShuaTou4RuFU__CenterPoint = None
        self.ShuaTou4RuFU__CenterAxisLines = []
        self.ShuaTou4RuFU__EdgeMidPoints = []
        self.ShuaTou4RuFU__FacePlaneList = []
        self.ShuaTou4RuFU__Corner0Planes = []
        self.ShuaTou4RuFU__LocalAxesPlane = None
        self.ShuaTou4RuFU__AxisX = None
        self.ShuaTou4RuFU__AxisY = None
        self.ShuaTou4RuFU__AxisZ = None
        self.ShuaTou4RuFU__FaceDirTags = []
        self.ShuaTou4RuFU__EdgeDirTags = []
        self.ShuaTou4RuFU__Corner0EdgeDirs = []
        self.ShuaTou4RuFU__TimberLog = []

        # RuFuInner
        self.RuFuInner__CutTimbers = []
        self.RuFuInner__FailTimbers = []
        self.RuFuInner__Log = []

        self.RuFuInner__All = None
        self.RuFuInner__AllDict = {}
        self.RuFuInner__DBLog = []
        self.RuFuInner__TimberBrep = None
        self.RuFuInner__FaceList = []
        self.RuFuInner__PointList = []
        self.RuFuInner__EdgeList = []
        self.RuFuInner__CenterPoint = None
        self.RuFuInner__CenterAxisLines = []
        self.RuFuInner__EdgeMidPoints = []
        self.RuFuInner__FacePlaneList = []
        self.RuFuInner__Corner0Planes = []
        self.RuFuInner__LocalAxesPlane = None
        self.RuFuInner__AxisX = None
        self.RuFuInner__AxisY = None
        self.RuFuInner__AxisZ = None
        self.RuFuInner__FaceDirTags = []
        self.RuFuInner__EdgeDirTags = []
        self.RuFuInner__Corner0EdgeDirs = []
        self.RuFuInner__TimberLog = []

        # PlaneFromLists::1（来自 ShuaTou4RuFU）
        self.PlaneFromLists_1__BasePlane = []
        self.PlaneFromLists_1__OriginPoint = []
        self.PlaneFromLists_1__ResultPlane = []
        self.PlaneFromLists_1__Log = []

        # PlaneFromLists::2（来自 RuFuInner）
        self.PlaneFromLists_2__BasePlane = []
        self.PlaneFromLists_2__OriginPoint = []
        self.PlaneFromLists_2__ResultPlane = []
        self.PlaneFromLists_2__Log = []

        # GeoAligner::1（对位 RuFuInner 的 CutTimbers 到 ShuaTou 的目标平面）
        self.GeoAligner_1__SourceOut = []
        self.GeoAligner_1__TargetOut = []
        self.GeoAligner_1__TransformOut = []
        self.GeoAligner_1__MovedGeo = []

        # 最终主输出（到当前 step 为止的组合逻辑）
        self.CutTimbers = []
        self.FailTimbers = []

    # --------------------------
    # 小工具：从 AllDict_1 取值
    # --------------------------
    def all_get_1(self, key, default=None):
        d = self.AllDict_1 if self.AllDict_1 else {}
        if key not in d:
            return default
        v = d[key]
        # 若是长度为 1 的 list/tuple，则解包
        if isinstance(v, (list, tuple)) and len(v) == 1:
            return v[0]
        return v

    # ------------------------------------------------------
    # Step 1：读取数据库（只做一次）
    # ------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="RuFu4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            # ✅ 注意：DBJsonReader 用 run()，不是 read()
            self.Value, self.All_1, self.DBLog_1 = reader.run()

            if self.DBLog_1 is None:
                self.DBLog_1 = []

            self.AllDict_1 = all_to_dict(self.All_1)

            self.Log.append("[DB] 读取 RuFu4PU 完成：All={} 项".format(len(self.All_1) if self.All_1 else 0))
            for l in self.DBLog_1:
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Value = None
            self.All_1 = None
            self.AllDict_1 = {}
            self.DBLog_1 = ["错误: {}".format(e)]
            self.Log.append("[ERROR] step1_read_db 出错: {}".format(e))

        return self


    # ------------------------------------------------------
    # Step 2：对位组装（ShuaTou4RuFU + RuFuInner + PFL + GeoAligner）
    # ------------------------------------------------------
    def step2_assemble_align(self):
        # ========== 2.1 ShuaTou4RuFU ==========
        try:
            st_solver = ShuaTou4RuFu_4PU(self.DBPath, self.base_point, self.Refresh, self.ghenv).run()

            self.ShuaTou4RuFU__CutTimbers = deep_flatten(getattr(st_solver, "CutTimbers", []))
            self.ShuaTou4RuFU__FailTimbers = deep_flatten(getattr(st_solver, "FailTimbers", []))
            self.ShuaTou4RuFU__Log = getattr(st_solver, "Log", [])

            # 关键几何输出
            self.ShuaTou4RuFU__EdgeMidPoints = deep_flatten(getattr(st_solver, "EdgeMidPoints", []))
            self.ShuaTou4RuFU__Corner0Planes = deep_flatten(getattr(st_solver, "Corner0Planes", []))

            # 可选：把它的 DB/Timber 也挂出来（若存在）
            self.ShuaTou4RuFU__All = getattr(st_solver, "All", None)
            self.ShuaTou4RuFU__AllDict = getattr(st_solver, "AllDict", {}) if hasattr(st_solver, "AllDict") else {}
            self.ShuaTou4RuFU__DBLog = getattr(st_solver, "DBLog", [])

            self.ShuaTou4RuFU__TimberBrep = getattr(st_solver, "TimberBrep", None)
            self.ShuaTou4RuFU__FaceList = getattr(st_solver, "FaceList", [])
            self.ShuaTou4RuFU__PointList = getattr(st_solver, "PointList", [])
            self.ShuaTou4RuFU__EdgeList = getattr(st_solver, "EdgeList", [])
            self.ShuaTou4RuFU__CenterPoint = getattr(st_solver, "CenterPoint", None)
            self.ShuaTou4RuFU__CenterAxisLines = getattr(st_solver, "CenterAxisLines", [])
            self.ShuaTou4RuFU__FacePlaneList = getattr(st_solver, "FacePlaneList", [])
            self.ShuaTou4RuFU__LocalAxesPlane = getattr(st_solver, "LocalAxesPlane", None)
            self.ShuaTou4RuFU__AxisX = getattr(st_solver, "AxisX", None)
            self.ShuaTou4RuFU__AxisY = getattr(st_solver, "AxisY", None)
            self.ShuaTou4RuFU__AxisZ = getattr(st_solver, "AxisZ", None)
            self.ShuaTou4RuFU__FaceDirTags = getattr(st_solver, "FaceDirTags", [])
            self.ShuaTou4RuFU__EdgeDirTags = getattr(st_solver, "EdgeDirTags", [])
            self.ShuaTou4RuFU__Corner0EdgeDirs = getattr(st_solver, "Corner0EdgeDirs", [])
            self.ShuaTou4RuFU__TimberLog = getattr(st_solver, "TimberLog", [])

            self.Log.append("[STEP2] ShuaTou4RuFU 完成：Cut={} Fail={}".format(
                len(self.ShuaTou4RuFU__CutTimbers), len(self.ShuaTou4RuFU__FailTimbers)
            ))
        except Exception as e:
            self.Log.append("[ERROR][STEP2] ShuaTou4RuFU 出错: {}".format(e))

        # ========== 2.2 RuFuInner ==========
        try:
            rf_solver = RuFuInner4PUSolver(self.DBPath, self.base_point, self.Refresh, self.ghenv).run()

            self.RuFuInner__CutTimbers = deep_flatten(getattr(rf_solver, "CutTimbers", []))
            self.RuFuInner__FailTimbers = deep_flatten(getattr(rf_solver, "FailTimbers", []))
            self.RuFuInner__Log = getattr(rf_solver, "Log", [])

            self.RuFuInner__EdgeMidPoints = deep_flatten(getattr(rf_solver, "EdgeMidPoints", []))
            self.RuFuInner__Corner0Planes = deep_flatten(getattr(rf_solver, "Corner0Planes", []))

            self.RuFuInner__All = getattr(rf_solver, "All", None)
            self.RuFuInner__AllDict = getattr(rf_solver, "AllDict", {}) if hasattr(rf_solver, "AllDict") else {}
            self.RuFuInner__DBLog = getattr(rf_solver, "DBLog", [])

            self.RuFuInner__TimberBrep = getattr(rf_solver, "TimberBrep", None)
            self.RuFuInner__FaceList = getattr(rf_solver, "FaceList", [])
            self.RuFuInner__PointList = getattr(rf_solver, "PointList", [])
            self.RuFuInner__EdgeList = getattr(rf_solver, "EdgeList", [])
            self.RuFuInner__CenterPoint = getattr(rf_solver, "CenterPoint", None)
            self.RuFuInner__CenterAxisLines = getattr(rf_solver, "CenterAxisLines", [])
            self.RuFuInner__FacePlaneList = getattr(rf_solver, "FacePlaneList", [])
            self.RuFuInner__LocalAxesPlane = getattr(rf_solver, "LocalAxesPlane", None)
            self.RuFuInner__AxisX = getattr(rf_solver, "AxisX", None)
            self.RuFuInner__AxisY = getattr(rf_solver, "AxisY", None)
            self.RuFuInner__AxisZ = getattr(rf_solver, "AxisZ", None)
            self.RuFuInner__FaceDirTags = getattr(rf_solver, "FaceDirTags", [])
            self.RuFuInner__EdgeDirTags = getattr(rf_solver, "EdgeDirTags", [])
            self.RuFuInner__Corner0EdgeDirs = getattr(rf_solver, "Corner0EdgeDirs", [])
            self.RuFuInner__TimberLog = getattr(rf_solver, "TimberLog", [])

            self.Log.append("[STEP2] RuFuInner 完成：Cut={} Fail={}".format(
                len(self.RuFuInner__CutTimbers), len(self.RuFuInner__FailTimbers)
            ))
        except Exception as e:
            self.Log.append("[ERROR][STEP2] RuFuInner 出错: {}".format(e))

        # ========== 2.3 PlaneFromLists::1（ShuaTou4RuFU 的 EdgeMidPoints + Corner0Planes） ==========
        try:
            OriginPoints = self.ShuaTou4RuFU__EdgeMidPoints
            BasePlanes = self.ShuaTou4RuFU__Corner0Planes

            idx_o = self.all_get_1("PlaneFromLists_1__IndexOrigin", 0)
            idx_p = self.all_get_1("PlaneFromLists_1__IndexPlane", 0)
            wrap = self.all_get_1("PlaneFromLists_1__Wrap", True)

            idx_o_list = to_list(idx_o)
            idx_p_list = to_list(idx_p)
            n = max(_param_length(idx_o_list), _param_length(idx_p_list), 1)
            idx_o_b = _broadcast_param(idx_o_list, n)
            idx_p_b = _broadcast_param(idx_p_list, n)

            builder = FTPlaneFromLists(wrap=bool(first_or_default(wrap, True)))

            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints, BasePlanes, idx_o_b[i], idx_p_b[i]
                )
                self.PlaneFromLists_1__BasePlane.append(BasePlane)
                self.PlaneFromLists_1__OriginPoint.append(OriginPoint)
                self.PlaneFromLists_1__ResultPlane.append(ResultPlane)
                self.PlaneFromLists_1__Log.append(Log)

            self.Log.append("[STEP2] PlaneFromLists::1 完成：count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_1__BasePlane = []
            self.PlaneFromLists_1__OriginPoint = []
            self.PlaneFromLists_1__ResultPlane = []
            self.PlaneFromLists_1__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][STEP2] PlaneFromLists::1 出错: {}".format(e))

        # ========== 2.4 PlaneFromLists::2（RuFuInner 的 EdgeMidPoints + Corner0Planes） ==========
        try:
            OriginPoints = self.RuFuInner__EdgeMidPoints
            BasePlanes = self.RuFuInner__Corner0Planes

            idx_o = self.all_get_1("PlaneFromLists_2__IndexOrigin", 0)
            idx_p = self.all_get_1("PlaneFromLists_2__IndexPlane", 0)
            wrap = self.all_get_1("PlaneFromLists_2__Wrap", True)

            idx_o_list = to_list(idx_o)
            idx_p_list = to_list(idx_p)
            n = max(_param_length(idx_o_list), _param_length(idx_p_list), 1)
            idx_o_b = _broadcast_param(idx_o_list, n)
            idx_p_b = _broadcast_param(idx_p_list, n)

            builder = FTPlaneFromLists(wrap=bool(first_or_default(wrap, True)))

            for i in range(n):
                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints, BasePlanes, idx_o_b[i], idx_p_b[i]
                )
                self.PlaneFromLists_2__BasePlane.append(BasePlane)
                self.PlaneFromLists_2__OriginPoint.append(OriginPoint)
                self.PlaneFromLists_2__ResultPlane.append(ResultPlane)
                self.PlaneFromLists_2__Log.append(Log)

            self.Log.append("[STEP2] PlaneFromLists::2 完成：count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_2__BasePlane = []
            self.PlaneFromLists_2__OriginPoint = []
            self.PlaneFromLists_2__ResultPlane = []
            self.PlaneFromLists_2__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][STEP2] PlaneFromLists::2 出错: {}".format(e))

        # ========== 2.5 GeoAligner::1（RuFuInner.CutTimbers 从 PFL2 → PFL1） ==========
        try:
            Geo = self.RuFuInner__CutTimbers
            SourcePlane = self.PlaneFromLists_2__ResultPlane
            TargetPlane = self.PlaneFromLists_1__ResultPlane

            # GeoAligner 参数：优先输入端（此组件当前未提供），因此这里从 DB / 默认取
            RotateDeg = self.all_get_1("GeoAligner_1__RotateDeg", 0)
            FlipX = self.all_get_1("GeoAligner_1__FlipX", 0)
            FlipY = self.all_get_1("GeoAligner_1__FlipY", 0)
            FlipZ = self.all_get_1("GeoAligner_1__FlipZ", 0)
            MoveX = self.all_get_1("GeoAligner_1__MoveX", 0)
            MoveY = self.all_get_1("GeoAligner_1__MoveY", 0)

            print(FlipZ)


            # 你给的连线描述里：MoveY=GeoAligner_1__MoveZ（疑似口误），这里兼容：若 MoveY 未写而 MoveZ 写了，则取 MoveZ
            MoveZ = self.all_get_1("GeoAligner_1__MoveZ", None)
            if (MoveY in (None, 0, 0.0)) and (MoveZ not in (None, 0, 0.0)):
                MoveY = MoveZ

            # 广播：以 Geo 的数量为主（若 plane 数量更大，也会扩展）
            geo_list = to_list(Geo)
            sp_list = to_list(SourcePlane)
            tp_list = to_list(TargetPlane)

            n = max(len(geo_list), len(sp_list), len(tp_list), 1)
            geo_b = _broadcast_param(geo_list, n)
            sp_b = _broadcast_param(sp_list, n)
            tp_b = _broadcast_param(tp_list, n)

            rd_b = _broadcast_param(to_list(RotateDeg), n)
            fx_b = _broadcast_param(to_list(FlipX), n)
            fy_b = _broadcast_param(to_list(FlipY), n)
            fz_b = _broadcast_param(to_list(FlipZ), n)
            mx_b = _broadcast_param(to_list(MoveX), n)
            my_b = _broadcast_param(to_list(MoveY), n)
            mz_b = _broadcast_param(to_list(self.all_get_1("GeoAligner_1__MoveZ", 0)), n)

            print(fx_b,fy_b,fz_b)

            for i in range(n):
                so, to, xf, mv = GeoAligner_xfm.align(
                    geo_b[i],
                    sp_b[i],
                    tp_b[i],
                    rotate_deg=rd_b[i],
                    flip_x=fx_b[i],
                    flip_y=fy_b[i],
                    flip_z=fz_b[i],
                    move_x=mx_b[i],
                    move_y=my_b[i],
                    move_z=mz_b[i],
                )
                self.GeoAligner_1__SourceOut.append(so)
                self.GeoAligner_1__TargetOut.append(to)
                self.GeoAligner_1__TransformOut.append(ght.GH_Transform(xf) if xf is not None else None)
                self.GeoAligner_1__MovedGeo.append(mv)

            self.GeoAligner_1__MovedGeo = deep_flatten(self.GeoAligner_1__MovedGeo)

            self.Log.append("[STEP2] GeoAligner::1 完成：count={}".format(n))

        except Exception as e:
            self.GeoAligner_1__SourceOut = []
            self.GeoAligner_1__TargetOut = []
            self.GeoAligner_1__TransformOut = []
            self.GeoAligner_1__MovedGeo = []
            self.Log.append("[ERROR][STEP2] GeoAligner::1 出错: {}".format(e))

        # ========== 2.6 最终主输出（到当前步骤） ==========
        # 组合策略（当前 step2）：耍头切后结果 + 对位后的乳栿内段
        self.CutTimbers = deep_flatten([
            self.ShuaTou4RuFU__CutTimbers,
            self.GeoAligner_1__MovedGeo
        ])
        self.FailTimbers = deep_flatten([
            self.ShuaTou4RuFU__FailTimbers,
            self.RuFuInner__FailTimbers
        ])

        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------
    def run(self):
        self.step1_read_db()
        if not self.All_1:
            self.Log.append("[RUN] All_1 为空，后续步骤跳过。")
            return self

        self.step2_assemble_align()
        return self


# ==============================================================
# GH Python 组件输出绑定区（developer-friendly）
#   说明：
#   1) CutTimbers/FailTimbers/Log 为“面向使用者”的主输出；
#   2) 其余为“开发模式输出”，你在 GH 里增加同名输出端即可随时挂出调试。
# ==============================================================

# ==============================================================
# GH Python 组件输出绑定区（developer-friendly）
#   说明：
#   1) CutTimbers / FailTimbers / Log 为“面向使用者”的主输出；
#   2) 其余为“开发模式输出”，在 GH 中增加同名输出端即可随时挂出调试；
#   3) 尽量做到：solver 里有哪些成员变量，这里就绑定哪些，避免漏项。
# ==============================================================

if __name__ == "__main__":

    solver = RuFu4PU_Solver(DBPath, base_point, Refresh, ghenv).run()

    # ----------------------------------------------------------
    # 主输出（面向使用者）
    # ----------------------------------------------------------
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log

    # ----------------------------------------------------------
    # Step0 / Inputs echo（可选，便于核对）
    # ----------------------------------------------------------
    DBPath_out     = solver.DBPath
    base_point_out = solver.base_point
    Refresh_out    = solver.Refresh

    # ----------------------------------------------------------
    # Step1: DB 输出（注意 _1 后缀避免后续步骤覆盖）
    # ----------------------------------------------------------
    Value     = solver.Value
    All_1     = solver.All_1
    AllDict_1 = solver.AllDict_1
    DBLog_1   = solver.DBLog_1

    # ----------------------------------------------------------
    # Step2: ShuaTou4RuFU 输出（全量）
    # ----------------------------------------------------------
    ShuaTou4RuFU__CutTimbers       = solver.ShuaTou4RuFU__CutTimbers
    ShuaTou4RuFU__FailTimbers      = solver.ShuaTou4RuFU__FailTimbers
    ShuaTou4RuFU__Log              = solver.ShuaTou4RuFU__Log

    ShuaTou4RuFU__All              = solver.ShuaTou4RuFU__All
    ShuaTou4RuFU__AllDict          = solver.ShuaTou4RuFU__AllDict
    ShuaTou4RuFU__DBLog            = solver.ShuaTou4RuFU__DBLog

    ShuaTou4RuFU__TimberBrep       = solver.ShuaTou4RuFU__TimberBrep
    ShuaTou4RuFU__FaceList         = solver.ShuaTou4RuFU__FaceList
    ShuaTou4RuFU__PointList        = solver.ShuaTou4RuFU__PointList
    ShuaTou4RuFU__EdgeList         = solver.ShuaTou4RuFU__EdgeList

    ShuaTou4RuFU__CenterPoint      = solver.ShuaTou4RuFU__CenterPoint
    ShuaTou4RuFU__CenterAxisLines  = solver.ShuaTou4RuFU__CenterAxisLines
    ShuaTou4RuFU__EdgeMidPoints    = solver.ShuaTou4RuFU__EdgeMidPoints

    ShuaTou4RuFU__FacePlaneList    = solver.ShuaTou4RuFU__FacePlaneList
    ShuaTou4RuFU__Corner0Planes    = solver.ShuaTou4RuFU__Corner0Planes
    ShuaTou4RuFU__LocalAxesPlane   = solver.ShuaTou4RuFU__LocalAxesPlane
    ShuaTou4RuFU__AxisX            = solver.ShuaTou4RuFU__AxisX
    ShuaTou4RuFU__AxisY            = solver.ShuaTou4RuFU__AxisY
    ShuaTou4RuFU__AxisZ            = solver.ShuaTou4RuFU__AxisZ

    ShuaTou4RuFU__FaceDirTags      = solver.ShuaTou4RuFU__FaceDirTags
    ShuaTou4RuFU__EdgeDirTags      = solver.ShuaTou4RuFU__EdgeDirTags
    ShuaTou4RuFU__Corner0EdgeDirs  = solver.ShuaTou4RuFU__Corner0EdgeDirs

    ShuaTou4RuFU__TimberLog        = solver.ShuaTou4RuFU__TimberLog

    # ----------------------------------------------------------
    # Step2: RuFuInner 输出（全量）
    # ----------------------------------------------------------
    RuFuInner__CutTimbers          = solver.RuFuInner__CutTimbers
    RuFuInner__FailTimbers         = solver.RuFuInner__FailTimbers
    RuFuInner__Log                 = solver.RuFuInner__Log

    RuFuInner__All                 = solver.RuFuInner__All
    RuFuInner__AllDict             = solver.RuFuInner__AllDict
    RuFuInner__DBLog               = solver.RuFuInner__DBLog

    RuFuInner__TimberBrep          = solver.RuFuInner__TimberBrep
    RuFuInner__FaceList            = solver.RuFuInner__FaceList
    RuFuInner__PointList           = solver.RuFuInner__PointList
    RuFuInner__EdgeList            = solver.RuFuInner__EdgeList

    RuFuInner__CenterPoint         = solver.RuFuInner__CenterPoint
    RuFuInner__CenterAxisLines     = solver.RuFuInner__CenterAxisLines
    RuFuInner__EdgeMidPoints       = solver.RuFuInner__EdgeMidPoints

    RuFuInner__FacePlaneList       = solver.RuFuInner__FacePlaneList
    RuFuInner__Corner0Planes       = solver.RuFuInner__Corner0Planes
    RuFuInner__LocalAxesPlane      = solver.RuFuInner__LocalAxesPlane
    RuFuInner__AxisX               = solver.RuFuInner__AxisX
    RuFuInner__AxisY               = solver.RuFuInner__AxisY
    RuFuInner__AxisZ               = solver.RuFuInner__AxisZ

    RuFuInner__FaceDirTags         = solver.RuFuInner__FaceDirTags
    RuFuInner__EdgeDirTags         = solver.RuFuInner__EdgeDirTags
    RuFuInner__Corner0EdgeDirs     = solver.RuFuInner__Corner0EdgeDirs

    RuFuInner__TimberLog           = solver.RuFuInner__TimberLog

    # ----------------------------------------------------------
    # Step2: PlaneFromLists::1（来自 ShuaTou4RuFU）
    # ----------------------------------------------------------
    PlaneFromLists_1__BasePlane    = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint  = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__ResultPlane  = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log          = solver.PlaneFromLists_1__Log

    # ----------------------------------------------------------
    # Step2: PlaneFromLists::2（来自 RuFuInner）
    # ----------------------------------------------------------
    PlaneFromLists_2__BasePlane    = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint  = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane  = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log          = solver.PlaneFromLists_2__Log

    # ----------------------------------------------------------
    # Step2: GeoAligner::1
    # ----------------------------------------------------------
    GeoAligner_1__SourceOut        = solver.GeoAligner_1__SourceOut
    GeoAligner_1__TargetOut        = solver.GeoAligner_1__TargetOut
    GeoAligner_1__TransformOut     = solver.GeoAligner_1__TransformOut
    GeoAligner_1__MovedGeo         = solver.GeoAligner_1__MovedGeo



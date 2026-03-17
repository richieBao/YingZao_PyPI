"""
GhPython Component: RuFuInner4PU_Solver (STEP 1-8)
-------------------------------------------------
将用于构建【乳栿内段】(type_code = RuFuInner4PU) 的多个 GhPython 组件串联，
逐步转换为单一 Solver 组件（数据库驱动）。

本文件当前实现：
- Step 1：DBJsonReader 读取 CommonComponents / type_code=RuFuInner4PU / params_json / ExportAll=True
         得到 All（list[tuple(key, value)]）并转换为 AllDict
- Step 2：Timber_block_uniform 原始木料构建（reference_plane 默认 XZ Plane；base_point 为输入端）

输入端（GH）：
    DBPath     : str          数据库文件路径
    base_point : Point3d      木料定位点（None -> World Origin）
    Refresh    : bool         True 强制重读数据库；False 使用缓存（如 DBJsonReader 内部支持）

输出端（GH，主输出）：
    CutTimbers  : list[Breps]   最终几何（当前 step2 仅输出原始木料 Brep）
    FailTimbers : list[Breps]   失败几何（当前为空）
    Log         : list[str]     全局日志（含各 Step 日志）

并保留 developer-friendly 输出端（按需在 GH 端增加同名输出即可）：
    Value, All, AllDict, DBLog,
    TimberBrep, FaceList, PointList, EdgeList, CenterPoint, CenterAxisLines,
    EdgeMidPoints, FacePlaneList, Corner0Planes, LocalAxesPlane, AxisX, AxisY, AxisZ,
    FaceDirTags, EdgeDirTags, Corner0EdgeDirs
"""

from yingzao.ancientArchi import DBJsonReader, build_timber_block_uniform, FTPlaneFromLists, JuanShaToolBuilder, \
    GeoAligner_xfm, RuFuJuanShaBottomSolver, WedgeShapedTool, RuFuJuanSha, FT_CutTimbersByTools_GH_SolidDifference
import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

__author__ = "richiebao [coding-x.tech]"
__version__ = "2026.01.12"



# ==============================================================
# 通用工具函数（对齐 LingGongSolver 的风格）
# ==============================================================

def _as_point3d(p, default=None):
    """把 GH 传入点统一成 rg.Point3d。"""
    if p is None:
        return default
    if isinstance(p, rg.Point3d):
        return p
    if isinstance(p, rg.Point):
        return p.Location
    return default


def _deep_flatten(x):
    """
    递归拍平 list/tuple，避免输出为：
    System.Collections.Generic.List`1[System.Object]
    """
    if x is None:
        return []
    # 常见：list/tuple
    if isinstance(x, (list, tuple)):
        out = []
        for it in x:
            out.extend(_deep_flatten(it))
        return out
    # 其它标量
    return [x]


def _safe_list(v):
    """把 v 变成 python list；若 v 已是 list/tuple 则递归拍平；否则 [v]。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return _deep_flatten(v)
    return [v]


def _ensure_list(v):
    """把输入规范为 list（标量 -> [标量]；list/tuple -> 递归拍平）。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return _deep_flatten(v)
    return [v]


def _gh_broadcast(*seqs):
    """
    GH 风格广播：给定若干个序列（已是 list），按最大长度对齐，
    较短的序列循环重复（cycle），空序列视为 [None]。
    返回：迭代器，每次 yield 一个 tuple(各序列当前项)
    """
    lists = []
    max_len = 1
    for s in seqs:
        lst = _ensure_list(s)
        if len(lst) == 0:
            lst = [None]
        lists.append(lst)
        if len(lst) > max_len:
            max_len = len(lst)

    for i in range(max_len):
        yield tuple(lst[i % len(lst)] for lst in lists)


def _as_number(v, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    # 常见：单元素 list/tuple
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return _as_number(v[0], default)
    try:
        return float(v)
    except:
        return default


def _as_int(v, default=0):
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v))
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return _as_int(v[0], default)
    try:
        return int(v)
    except:
        return default


def _as_bool01(v, default=False):
    """把 0/1、True/False、'0'/'1' 等转为 bool。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(int(round(v)))
    if isinstance(v, (list, tuple)) and len(v) == 1:
        return _as_bool01(v[0], default)
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return default


class GHPlaneFactory(object):
    """
    注意：这里的 XY/XZ/YZ 与你给定的 GH 参考平面轴向一致：
    XY: X(1,0,0), Y(0,1,0), Z(0,0,1)
    XZ: X(1,0,0), Y(0,0,1), Z(0,-1,0)
    YZ: X(0,1,0), Y(0,0,1), Z(1,0,0)
    """

    @staticmethod
    def from_name(name="XZ", origin=None):
        if origin is None:
            origin = rg.Point3d(0, 0, 0)

        n = (name or "XZ").upper().replace("WORLD", "").replace("PLANE", "").strip()
        if n in ("XY", "WXY"):
            x = rg.Vector3d(1.0, 0.0, 0.0)
            y = rg.Vector3d(0.0, 1.0, 0.0)
            return rg.Plane(origin, x, y)

        if n in ("YZ", "WYZ"):
            x = rg.Vector3d(0.0, 1.0, 0.0)
            y = rg.Vector3d(0.0, 0.0, 1.0)
            return rg.Plane(origin, x, y)

        # 默认 XZ
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)  # Z 会自动为 X×Y = (0,-1,0)
        return rg.Plane(origin, x, y)


# ==============================================================
# 主 Solver 类 —— 乳栿内段 RuFuInner4PUSolver（当前 Step1~2）
# ==============================================================

class RuFuInner4PUSolver(object):

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

        # 全局日志
        self.Log = []

        # Step 2：木坯几何输出成员（与 Timber_block_uniform 命名保持一致）
        self.TimberBrep = None
        self.FaceList = []
        self.PointList = []
        self.EdgeList = []
        self.CenterPoint = None
        self.CenterAxisLines = []
        self.EdgeMidPoints = []
        self.FacePlaneList = []
        self.Corner0Planes = []
        self.LocalAxesPlane = None
        self.AxisX = None
        self.AxisY = None
        self.AxisZ = None
        self.FaceDirTags = []
        self.EdgeDirTags = []
        self.Corner0EdgeDirs = []
        self.TimberLog = []

        # Step 3：顶部卷殺（JuanSha::1 + PlaneFromLists::1 + GeoAligner::1）
        # PlaneFromLists::1
        self.PFL1_BasePlane = []
        self.PFL1_OriginPoint = []
        self.PFL1_ResultPlane = []
        self.PFL1_Log = []

        # JuanSha::1（未对位原始刀具）
        self.JuanSha1_ToolBrep = []
        self.JuanSha1_SectionEdges = []
        self.JuanSha1_HL_Intersection = []
        self.JuanSha1_HeightFacePlane = []
        self.JuanSha1_LengthFacePlane = []
        self.JuanSha1_Log = []

        # GeoAligner::1（对位后刀具）
        self.GA1_SourceOut = []
        self.GA1_TargetOut = []
        self.GA1_TransformOut = []
        self.GA1_MovedGeo = []

        # Step 4：两侧卷殺（JuanSha::2 + PlaneFromLists::2 + GeoAligner::2）
        # PlaneFromLists::2
        self.PFL2_BasePlane = []
        self.PFL2_OriginPoint = []
        self.PFL2_ResultPlane = []
        self.PFL2_Log = []

        # JuanSha::2（未对位原始刀具）
        self.JuanSha2_ToolBrep = []
        self.JuanSha2_SectionEdges = []
        self.JuanSha2_HL_Intersection = []
        self.JuanSha2_HeightFacePlane = []
        self.JuanSha2_LengthFacePlane = []
        self.JuanSha2_Log = []

        # GeoAligner::2（对位后刀具）
        self.GA2_SourceOut = []
        self.GA2_TargetOut = []
        self.GA2_TransformOut = []
        self.GA2_MovedGeo = []

        # Step 5：底部卷殺（JuanShaV3 + PlaneFromLists::3 + GeoAligner::3）
        # PlaneFromLists::3
        self.PFL3_BasePlane = []
        self.PFL3_OriginPoint = []
        self.PFL3_ResultPlane = []
        self.PFL3_Log = []

        # JuanShaV3（未对位原始刀具）—— RuFuJuanShaBottomSolver
        # Step-A
        self.JSV3_RefPlane_O = None
        self.JSV3_RefPlane_O_XZ = None
        self.JSV3_RefPlane_O_YZ = None
        self.JSV3_Polyline_O_to_B = None
        self.JSV3_Points_OA = []
        self.JSV3_Points_AB = []
        self.JSV3_ConnectorLines = []
        self.JSV3_Intersections_FGH = []

        # Step-B
        self.JSV3_Point_I = None
        self.JSV3_Point_J = None
        self.JSV3_Point_K = None
        self.JSV3_Point_L = None
        self.JSV3_Plane_BJI = None
        self.JSV3_Curve_BLJ = None

        # Step-C
        self.JSV3_Point_Op = None
        self.JSV3_Points_FGHp = []
        self.JSV3_Point_I_from_move = None
        self.JSV3_Points_FGHpp = []
        self.JSV3_Polyline_Op_to_J = None

        # Step-D
        self.JSV3_Point_P = None
        self.JSV3_Rail_BP = None
        self.JSV3_Surface_Red = None
        self.JSV3_Surface_Purple = None
        self.JSV3_Surface_S = None
        self.JSV3_Surface_S_mirror = None
        self.JSV3_Surface_Final = None

        # Step-E
        self.JSV3_Top_S = None
        self.JSV3_Cube_Brep = None
        self.JSV3_Cube_Parts_Raw = []
        self.JSV3_Cube_Parts = []
        self.JSV3_Cube_Parts_JoinedAll = []

        # Step-F
        self.JSV3_Cube_Parts_Vol = []
        self.JSV3_Solid_MaxVolume = None

        self.JSV3_Debug = ""

        # GeoAligner::3（对位后底部卷杀刀具）
        self.GA3_SourceOut = []
        self.GA3_TargetOut = []
        self.GA3_TransformOut = []
        self.GA3_MovedGeo = []

        # Step 6：楔形刀（XieXingTool + GeoAligner::4）
        self.XieXing_SolidBrep = None
        self.XieXing_SectionCrv = None
        self.XieXing_PlaneOut = None
        self.XieXing_A_RefPlanes = []
        self.XieXing_Log = []

        # GeoAligner::4（对位后楔形刀）
        self.GA4_SourceOut = []
        self.GA4_TargetOut = []
        self.GA4_TransformOut = []

        # Step 7：乳栿卷殺（RuFUJuanSha + GeoAligner::5）
        # RuFUJuanSha outputs
        self.RFJS_Points = []
        self.RFJS_Lines = []
        self.RFJS_ArcCurves = []
        self.RFJS_ArcCtrlPts = []
        self.RFJS_ArcPlanes = []
        self.RFJS_ArcData = None
        self.RFJS_StepCSurfaces = []
        self.RFJS_StepCPlanes = []
        self.RFJS_ClosedBrep = None
        self.RFJS_RefPlanes = []
        self.RFJS_ReferencePlanes_O = []
        self.RFJS_ClosedBreps_Mirrored = []
        self.RFJS_Debug = ""

        # GeoAligner::5（对位后乳栿卷杀刀具）
        self.GA5_SourceOut = []
        self.GA5_TargetOut = []
        self.GA5_TransformOut = []
        self.GA5_MovedGeo = []

        self.GA4_MovedGeo = []

        # Step 8：裁切（BlockCutterV3 / FT_CutTimbersByTools_GH_SolidDifference）
        self.BC_Tools = []
        self.BC_CutTimbers = []
        self.BC_FailTimbers = []
        self.BC_Log = []

        # 最终 Cut 结果（当前 step2 先输出原木料）
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # 小工具：构造 AllDict / 取值策略
    # ------------------------------------------------------
    def _build_all_dict(self, All):
        d = {}
        if not All:
            return d
        # All: list of (key, value)
        try:
            for kv in All:
                if not isinstance(kv, (list, tuple)) or len(kv) < 2:
                    continue
                k = kv[0]
                v = kv[1]
                d[k] = v
        except:
            pass
        return d

    def all_get(self, key, default=None):
        """
        从 AllDict 取值：
        - 不存在返回 default
        - 若 v 为单元素 list/tuple，则自动解包
        """
        if not self.AllDict or key not in self.AllDict:
            return default
        v = self.AllDict.get(key, default)
        if isinstance(v, (list, tuple)) and len(v) == 1:
            return v[0]
        return v

    def _pick_from_list(self, items, idx, default=None, wrap=True):
        """从 items(list) 中按 idx 取元素；idx 可为任意数值；越界则 wrap 或返回 default。"""
        lst = _ensure_list(items)
        if len(lst) == 0:
            return default
        i = _as_int(idx, 0)
        if wrap:
            i = i % len(lst)
            return lst[i]
        if 0 <= i < len(lst):
            return lst[i]
        return default

    # ------------------------------------------------------
    # Step 1：读取数据库
    # ------------------------------------------------------
    def step1_read_db(self):
        """
        DBJsonReader:
            Table     = CommonComponents
            KeyField  = type_code
            KeyValue  = RuFuInner4PU
            Field     = params_json
            ExportAll = True
        """
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="CommonComponents",
                key_field="type_code",
                key_value="RuFuInner4PU",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )

            self.Value, self.All, self.DBLog = reader.run()
            self.AllDict = self._build_all_dict(self.All)

            if self.All:
                self.Log.append("[DB] 读取成功：All={} 项".format(len(self.All)))
            else:
                self.Log.append("[DB] 读取完成，但 All 为空。")

            # DBLog 合并进总 Log
            for l in _safe_list(self.DBLog):
                self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Value = None
            self.All = None
            self.AllDict = {}
            self.DBLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR][DB] DBJsonReader 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：原始木料构建 Timber_block_uniform
    # ------------------------------------------------------
    def step2_timber(self):
        """
        Timber_block_uniform:
            length_fen      <- AllDict['Timber_block_uniform__length_fen'] or default
            width_fen       <- AllDict['Timber_block_uniform__width_fen']  or default
            height_fen      <- AllDict['Timber_block_uniform__height_fen'] or default
            base_point      <- 输入端 base_point（None->Origin）
            reference_plane <- 默认 GH XZ Plane
        """
        # 参数优先级：本 Solver 只有 3 个输入端；这里按“数据库 -> 默认”取
        length_fen = self.all_get("Timber_block_uniform__length_fen", None)
        width_fen = self.all_get("Timber_block_uniform__width_fen", None)
        height_fen = self.all_get("Timber_block_uniform__height_fen", None)

        if length_fen is None:
            length_fen = 32.0
        if width_fen is None:
            width_fen = 32.0
        if height_fen is None:
            height_fen = 20.0

        bp = _as_point3d(self.base_point, rg.Point3d(0, 0, 0))
        ref_plane = GHPlaneFactory.from_name("XZ", origin=bp)

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
                bp,
                ref_plane,
            )

            self.TimberBrep = timber_brep
            self.FaceList = _safe_list(faces)
            self.PointList = _safe_list(points)
            self.EdgeList = _safe_list(edges)
            self.CenterPoint = center_pt
            self.CenterAxisLines = _safe_list(center_axes)
            self.EdgeMidPoints = _safe_list(edge_midpts)
            self.FacePlaneList = _safe_list(face_planes)
            self.Corner0Planes = _safe_list(corner0_planes)
            self.LocalAxesPlane = local_axes_plane
            self.AxisX = axis_x
            self.AxisY = axis_y
            self.AxisZ = axis_z
            self.FaceDirTags = _safe_list(face_tags)
            self.EdgeDirTags = _safe_list(edge_tags)
            self.Corner0EdgeDirs = _safe_list(corner0_dirs)
            self.TimberLog = _safe_list(log_lines)

            self.Log.append("[TIMBER] OK: L/W/H = {}/{}/{}".format(length_fen, width_fen, height_fen))
            for l in self.TimberLog:
                self.Log.append("[TIMBER] " + str(l))

            # 当前只到 Step2：CutTimbers 暂用原始木料占位（后续 Step3+ 会被切割结果覆盖）
            self.CutTimbers = [self.TimberBrep] if self.TimberBrep else []
            self.FailTimbers = []

        except Exception as e:
            self.TimberBrep = None
            self.FaceList = []
            self.PointList = []
            self.EdgeList = []
            self.CenterPoint = None
            self.CenterAxisLines = []
            self.EdgeMidPoints = []
            self.FacePlaneList = []
            self.Corner0Planes = []
            self.LocalAxesPlane = None
            self.AxisX = None
            self.AxisY = None
            self.AxisZ = None
            self.FaceDirTags = []
            self.EdgeDirTags = []
            self.Corner0EdgeDirs = []
            self.TimberLog = ["错误: {}".format(e)]

            self.CutTimbers = []
            self.FailTimbers = []

            self.Log.append("[ERROR][TIMBER] build_timber_block_uniform 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3：顶部卷殺（JuanSha::1 + PlaneFromLists::1 + GeoAligner::1）
    # ------------------------------------------------------
    def step3_top_juansha(self):
        """
        Step 3 包括：
        1) PlaneFromLists::1
            OriginPoints = Step2.EdgeMidPoints
            BasePlanes   = Step2.Corner0Planes
            IndexOrigin  = AllDict['PlaneFromLists_1__IndexOrigin']
            IndexPlane   = AllDict['PlaneFromLists_1__IndexPlane']
            Wrap         = True（默认）
            支持 GH 广播：IndexOrigin/IndexPlane 为列表时，按最大长度对齐，短的循环重复。
        2) JuanSha::1
            HeightFen     = AllDict['JuanSha_1__HeightFen']
            LengthFen     = AllDict['JuanSha_1__LengthFen']
            DivCount      = AllDict['JuanSha_1__DivCount']
            ThicknessFen  = AllDict['JuanSha_1__ThicknessFen']
            SectionPlane  = 默认 World XZ（原点）
            PositionPoint = 默认原点
        3) GeoAligner::1
            Geo         = JuanSha1_ToolBrep
            SourcePlane = JuanSha1_LengthFacePlane
            TargetPlane = PFL1_ResultPlane
            RotateDeg   = AllDict['GeoAligner_1__RotateDeg']
            FlipX/Y/Z, MoveX/Y/Z 若 DB 中存在则读取，否则默认 False/0
        """

        # ---- 3.1 PlaneFromLists::1 ----
        try:
            origin_pts = _ensure_list(self.EdgeMidPoints)
            base_pls = _ensure_list(self.Corner0Planes)

            idx_origin = self.all_get("PlaneFromLists_1__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_1__IndexPlane", None)
            wrap_val = self.all_get("PlaneFromLists_1__Wrap", True)
            wrap_val = _as_bool01(wrap_val, True)

            pfl = FTPlaneFromLists(wrap=wrap_val)

            self.PFL1_BasePlane = []
            self.PFL1_OriginPoint = []
            self.PFL1_ResultPlane = []
            self.PFL1_Log = []

            for io, ip in _gh_broadcast(idx_origin, idx_plane):
                BasePlane, OriginPoint, ResultPlane, Log = pfl.build_plane(
                    origin_pts,
                    base_pls,
                    _as_int(io, 0),
                    _as_int(ip, 0)
                )
                self.PFL1_BasePlane.append(BasePlane)
                self.PFL1_OriginPoint.append(OriginPoint)
                self.PFL1_ResultPlane.append(ResultPlane)
                self.PFL1_Log.append(Log)

            # 拍平 Log
            self.PFL1_Log = _safe_list(self.PFL1_Log)

            self.Log.append("[PFL1] OK: OriginPoints={} BasePlanes={} Pairs={}".format(
                len(origin_pts), len(base_pls),
                max(len(_ensure_list(idx_origin)) or [1], len(_ensure_list(idx_plane)) or [1])
            ))

        except Exception as e:
            self.PFL1_BasePlane = []
            self.PFL1_OriginPoint = []
            self.PFL1_ResultPlane = []
            self.PFL1_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][PFL1] PlaneFromLists::1 出错: {}".format(e))
            return self  # Step3 后续依赖 PFL1，不继续

        # ---- 3.2 JuanSha::1 ----
        try:
            h_fen = self.all_get("JuanSha_1__HeightFen", None)
            l_fen = self.all_get("JuanSha_1__LengthFen", None)
            divc = self.all_get("JuanSha_1__DivCount", None)
            t_fen = self.all_get("JuanSha_1__ThicknessFen", None)

            # 默认值（未给出时）
            if h_fen is None: h_fen = 2.0
            if l_fen is None: l_fen = 10.0
            if t_fen is None: t_fen = 1.0
            if divc is None: divc = 10

            # JuanShaToolBuilder 生成的刀具先按“原点/XZ”构建，再由 GeoAligner 对位到木料
            sec_plane = GHPlaneFactory.from_name("XZ", origin=rg.Point3d(0, 0, 0))
            pos_pt = rg.Point3d(0, 0, 0)

            builder = JuanShaToolBuilder(
                height_fen=h_fen,
                length_fen=l_fen,
                thickness_fen=t_fen,
                div_count=_as_int(divc, 10),
                section_plane=sec_plane,
                position_point=pos_pt
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, JLog = builder.build()

            self.JuanSha1_ToolBrep = _safe_list(ToolBrep)
            self.JuanSha1_SectionEdges = _safe_list(SectionEdges)
            self.JuanSha1_HL_Intersection = _safe_list(HL_Intersection)
            self.JuanSha1_HeightFacePlane = _safe_list(HeightFacePlane)
            self.JuanSha1_LengthFacePlane = _safe_list(LengthFacePlane)
            self.JuanSha1_Log = _safe_list(JLog)

            self.Log.append("[JUANSHA1] OK: HeightFen={} LengthFen={} ThicknessFen={} DivCount={}".format(
                h_fen, l_fen, t_fen, _as_int(divc, 10)
            ))

        except Exception as e:
            self.JuanSha1_ToolBrep = []
            self.JuanSha1_LengthFacePlane = []
            self.JuanSha1_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][JUANSHA1] JuanSha::1 出错: {}".format(e))
            return self

        # ---- 3.3 GeoAligner::1 ----
        try:
            rotate_deg = self.all_get("GeoAligner_1__RotateDeg", 0.0)
            flip_x = _as_bool01(self.all_get("GeoAligner_1__FlipX", False), False)
            flip_y = _as_bool01(self.all_get("GeoAligner_1__FlipY", False), False)
            flip_z = _as_bool01(self.all_get("GeoAligner_1__FlipZ", False), False)
            move_x = _as_number(self.all_get("GeoAligner_1__MoveX", 0.0), 0.0)
            move_y = _as_number(self.all_get("GeoAligner_1__MoveY", 0.0), 0.0)
            move_z = _as_number(self.all_get("GeoAligner_1__MoveZ", 0.0), 0.0)

            self.GA1_SourceOut = []
            self.GA1_TargetOut = []
            self.GA1_TransformOut = []
            self.GA1_MovedGeo = []

            geos = _ensure_list(self.JuanSha1_ToolBrep)
            sps = _ensure_list(self.JuanSha1_LengthFacePlane)
            tps = _ensure_list(self.PFL1_ResultPlane)
            rds = _ensure_list(rotate_deg)

            for geo, sp, tp, rd in _gh_broadcast(geos, sps, tps, rds):
                if geo is None or sp is None or tp is None:
                    continue
                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    sp,
                    tp,
                    rotate_deg=_as_number(rd, 0.0),
                    flip_x=flip_x,
                    flip_y=flip_y,
                    flip_z=flip_z,
                    move_x=move_x,
                    move_y=move_y,
                    move_z=move_z,
                )
                self.GA1_SourceOut.append(SourceOut)
                self.GA1_TargetOut.append(TargetOut)
                self.GA1_TransformOut.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                self.GA1_MovedGeo.append(MovedGeo)

            self.GA1_MovedGeo = _safe_list(self.GA1_MovedGeo)

            if len(self.GA1_MovedGeo) == 0:
                self.Log.append("[GA1] Geo 为空或对位失败，跳过。")
            else:
                self.Log.append("[GA1] OK: aligned={} rotate_deg={}".format(len(self.GA1_MovedGeo), rotate_deg))

        except Exception as e:
            self.GA1_SourceOut = []
            self.GA1_TargetOut = []
            self.GA1_TransformOut = []
            self.GA1_MovedGeo = []
            self.Log.append("[ERROR][GA1] GeoAligner::1 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4：两侧卷殺（JuanSha::2 + PlaneFromLists::2 + GeoAligner::2）
    # ------------------------------------------------------
    def step4_side_juansha(self):
        """
        Step 4 包括：
        1) PlaneFromLists::2
            OriginPoints = Step2.EdgeMidPoints
            BasePlanes   = Step2.Corner0Planes
            IndexOrigin  = AllDict['PlaneFromLists_2__IndexOrigin']
            IndexPlane   = AllDict['PlaneFromLists_2__IndexPlane']
            Wrap         = True（默认）
            支持 GH 广播：IndexOrigin/IndexPlane 为列表时，按最大长度对齐，短的循环重复。
        2) JuanSha::2
            HeightFen     = AllDict['JuanSha_2__HeightFen']
            LengthFen     = AllDict['JuanSha_2__LengthFen']
            DivCount      = AllDict['JuanSha_2__DivCount']
            ThicknessFen  = AllDict['JuanSha_2__ThicknessFen']
            SectionPlane  = 默认 World XZ（原点）
            PositionPoint = 默认原点
        3) GeoAligner::2
            Geo         = JuanSha2_ToolBrep
            SourcePlane = JuanSha2_LengthFacePlane
            TargetPlane = PFL2_ResultPlane
            FlipY       = AllDict['GeoAligner_2__FlipY']   （重点：允许为列表 -> 广播）
            其它 RotateDeg/FlipX/FlipZ/MoveX/Y/Z 若 DB 中存在则读取，否则默认。
        """

        # ---- 4.1 PlaneFromLists::2 ----
        try:
            origin_pts = _ensure_list(self.EdgeMidPoints)
            base_pls = _ensure_list(self.Corner0Planes)

            idx_origin = self.all_get("PlaneFromLists_2__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_2__IndexPlane", None)
            wrap_val = self.all_get("PlaneFromLists_2__Wrap", True)
            wrap_val = _as_bool01(wrap_val, True)

            pfl = FTPlaneFromLists(wrap=wrap_val)

            self.PFL2_BasePlane = []
            self.PFL2_OriginPoint = []
            self.PFL2_ResultPlane = []
            self.PFL2_Log = []

            for io, ip in _gh_broadcast(idx_origin, idx_plane):
                BasePlane, OriginPoint, ResultPlane, Log = pfl.build_plane(
                    origin_pts,
                    base_pls,
                    _as_int(io, 0),
                    _as_int(ip, 0)
                )
                self.PFL2_BasePlane.append(BasePlane)
                self.PFL2_OriginPoint.append(OriginPoint)
                self.PFL2_ResultPlane.append(ResultPlane)
                self.PFL2_Log.append(Log)

            self.PFL2_Log = _safe_list(self.PFL2_Log)

            self.Log.append("[PFL2] OK: OriginPoints={} BasePlanes={} Pairs={}".format(
                len(origin_pts), len(base_pls),
                max(len(_ensure_list(idx_origin)) or [1], len(_ensure_list(idx_plane)) or [1])
            ))

        except Exception as e:
            self.PFL2_BasePlane = []
            self.PFL2_OriginPoint = []
            self.PFL2_ResultPlane = []
            self.PFL2_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][PFL2] PlaneFromLists::2 出错: {}".format(e))
            return self

        # ---- 4.2 JuanSha::2 ----
        try:
            h_fen = self.all_get("JuanSha_2__HeightFen", None)
            l_fen = self.all_get("JuanSha_2__LengthFen", None)
            divc = self.all_get("JuanSha_2__DivCount", None)
            t_fen = self.all_get("JuanSha_2__ThicknessFen", None)

            # 默认值（未给出时）
            if h_fen is None: h_fen = 2.0
            ifq = l_fen
            if l_fen is None: l_fen = 10.0
            if t_fen is None: t_fen = 1.0
            if divc is None: divc = 10

            sec_plane = GHPlaneFactory.from_name("XZ", origin=rg.Point3d(0, 0, 0))
            pos_pt = rg.Point3d(0, 0, 0)

            builder = JuanShaToolBuilder(
                height_fen=h_fen,
                length_fen=l_fen,
                thickness_fen=t_fen,
                div_count=_as_int(divc, 10),
                section_plane=sec_plane,
                position_point=pos_pt
            )

            ToolBrep, SectionEdges, HL_Intersection, HeightFacePlane, LengthFacePlane, JLog = builder.build()

            self.JuanSha2_ToolBrep = _safe_list(ToolBrep)
            self.JuanSha2_SectionEdges = _safe_list(SectionEdges)
            self.JuanSha2_HL_Intersection = _safe_list(HL_Intersection)
            self.JuanSha2_HeightFacePlane = _safe_list(HeightFacePlane)
            self.JuanSha2_LengthFacePlane = _safe_list(LengthFacePlane)
            self.JuanSha2_Log = _safe_list(JLog)

            self.Log.append("[JUANSHA2] OK: HeightFen={} LengthFen={} ThicknessFen={} DivCount={}".format(
                h_fen, l_fen, t_fen, _as_int(divc, 10)
            ))

        except Exception as e:
            self.JuanSha2_ToolBrep = []
            self.JuanSha2_LengthFacePlane = []
            self.JuanSha2_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][JUANSHA2] JuanSha::2 出错: {}".format(e))
            return self

        # ---- 4.3 GeoAligner::2 ----
        try:
            # 允许这些参数为标量或列表（列表用于多对位）
            rotate_deg = self.all_get("GeoAligner_2__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_2__FlipX", False)
            flip_y = self.all_get("GeoAligner_2__FlipY", False)  # 重点：常见为 [0,1] 或 [1,0,0,1]
            flip_z = self.all_get("GeoAligner_2__FlipZ", False)
            move_x = self.all_get("GeoAligner_2__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_2__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_2__MoveZ", 0.0)

            self.GA2_SourceOut = []
            self.GA2_TargetOut = []
            self.GA2_TransformOut = []
            self.GA2_MovedGeo = []

            geos = _ensure_list(self.JuanSha2_ToolBrep)
            sps = _ensure_list(self.JuanSha2_LengthFacePlane)
            tps = _ensure_list(self.PFL2_ResultPlane)

            # 广播把 flip/rotate/move 也一起考虑
            for geo, sp, tp, rd, fx, fy, fz, mx, my, mz in _gh_broadcast(
                    geos, sps, tps, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z
            ):
                if geo is None or sp is None or tp is None:
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    sp,
                    tp,
                    rotate_deg=_as_number(rd, 0.0),
                    flip_x=_as_bool01(fx, False),
                    flip_y=_as_bool01(fy, False),
                    flip_z=_as_bool01(fz, False),
                    move_x=_as_number(mx, 0.0),
                    move_y=_as_number(my, 0.0),
                    move_z=_as_number(mz, 0.0),
                )

                self.GA2_SourceOut.append(SourceOut)
                self.GA2_TargetOut.append(TargetOut)
                self.GA2_TransformOut.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                self.GA2_MovedGeo.append(MovedGeo)

            self.GA2_MovedGeo = _safe_list(self.GA2_MovedGeo)

            if len(self.GA2_MovedGeo) == 0:
                self.Log.append("[GA2] Geo 为空或对位失败，跳过。")
            else:
                self.Log.append("[GA2] OK: aligned={} flip_y={}".format(len(self.GA2_MovedGeo), flip_y))

        except Exception as e:
            self.GA2_SourceOut = []
            self.GA2_TargetOut = []
            self.GA2_TransformOut = []
            self.GA2_MovedGeo = []
            self.Log.append("[ERROR][GA2] GeoAligner::2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5：底部卷殺（JuanShaV3 + PlaneFromLists::3 + GeoAligner::3）
    # ------------------------------------------------------
    def step5_bottom_juansha(self):
        """
        Step 5 包括：
        1) PlaneFromLists::3
            OriginPoints = Step2.EdgeMidPoints
            BasePlanes   = Step2.Corner0Planes
            IndexOrigin  = AllDict['PlaneFromLists_3__IndexOrigin']
            IndexPlane   = AllDict['PlaneFromLists_3__IndexPlane']
            Wrap         = True（默认）
            支持 GH 广播：IndexOrigin/IndexPlane 为列表时，按最大长度对齐，短的循环重复。
        2) JuanShaV3（RuFuJuanShaBottomSolver）
            OA_len   = AllDict['JuanShaV3__OA_len']
            AB_len   = AllDict['JuanShaV3__AB_len']
            DivCount = AllDict['JuanShaV3__DivCount']
            BI_len   = AllDict['JuanShaV3__BI_len']
            IJ_len   = AllDict['JuanShaV3__IJ_len']
            KL_len   = AllDict['JuanShaV3__KL_len']
            BP_len   = Timber_block_uniform__length_fen - (JuanShaV3__AB_BP + JuanShaV3__AB_len)
            先在原点 XZ Plane 构建，再由 GeoAligner::3 对位到木料。
        3) GeoAligner::3
            Geo         = JuanShaV3.Solid_MaxVolume
            SourcePlane = JuanShaV3.RefPlane_O_XZ
            TargetPlane = PFL3.ResultPlane
            RotateDeg   = AllDict['GeoAligner_3__RotateDeg']
            FlipZ       = AllDict['GeoAligner_3__FlipZ']
            其它 FlipX/FlipY/MoveX/Y/Z 若 DB 中存在则读取，否则默认。
        """

        # ---- 5.1 PlaneFromLists::3 ----
        try:
            origin_pts = _ensure_list(self.EdgeMidPoints)
            base_pls = _ensure_list(self.Corner0Planes)

            idx_origin = self.all_get("PlaneFromLists_3__IndexOrigin", None)
            idx_plane = self.all_get("PlaneFromLists_3__IndexPlane", None)
            wrap_val = self.all_get("PlaneFromLists_3__Wrap", True)
            wrap_val = _as_bool01(wrap_val, True)

            pfl = FTPlaneFromLists(wrap=wrap_val)

            self.PFL3_BasePlane = []
            self.PFL3_OriginPoint = []
            self.PFL3_ResultPlane = []
            self.PFL3_Log = []

            for io, ip in _gh_broadcast(idx_origin, idx_plane):
                BasePlane, OriginPoint, ResultPlane, Log = pfl.build_plane(
                    origin_pts,
                    base_pls,
                    _as_int(io, 0),
                    _as_int(ip, 0)
                )
                self.PFL3_BasePlane.append(BasePlane)
                self.PFL3_OriginPoint.append(OriginPoint)
                self.PFL3_ResultPlane.append(ResultPlane)
                self.PFL3_Log.append(Log)

            self.PFL3_Log = _safe_list(self.PFL3_Log)

            self.Log.append("[PFL3] OK: OriginPoints={} BasePlanes={} Pairs={}".format(
                len(origin_pts), len(base_pls),
                max(len(_ensure_list(idx_origin)) or [1], len(_ensure_list(idx_plane)) or [1])
            ))

        except Exception as e:
            self.PFL3_BasePlane = []
            self.PFL3_OriginPoint = []
            self.PFL3_ResultPlane = []
            self.PFL3_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][PFL3] PlaneFromLists::3 出错: {}".format(e))
            return self

        # ---- 5.2 JuanShaV3 ----
        try:
            oa_len = self.all_get("JuanShaV3__OA_len", None)
            ab_len = self.all_get("JuanShaV3__AB_len", None)
            divc = self.all_get("JuanShaV3__DivCount", None)
            bi_len = self.all_get("JuanShaV3__BI_len", None)
            ij_len = self.all_get("JuanShaV3__IJ_len", None)
            kl_len = self.all_get("JuanShaV3__KL_len", None)
            ab_bp = self.all_get("JuanShaV3__AB_BP", 0.0)

            # Timber length 取数据库（与 Step2 一致）
            timber_len = self.all_get("Timber_block_uniform__length_fen", 32.0)

            # 默认值（若 DB 无）
            if oa_len is None: oa_len = 5.0
            if ab_len is None: ab_len = 14.0
            if bi_len is None: bi_len = 60.0
            if ij_len is None: ij_len = 10.0
            if kl_len is None: kl_len = 0.5
            if divc is None: divc = 10
            if ab_bp is None: ab_bp = 0.0

            bp_len = _as_number(timber_len, 32.0) - (_as_number(ab_bp, 0.0) + _as_number(ab_len, 14.0))

            base_pt0 = rg.Point3d(0, 0, 0)
            ref_pl0 = GHPlaneFactory.from_name("XZ", origin=base_pt0)

            js = RuFuJuanShaBottomSolver(
                base_point=base_pt0,
                ref_plane=ref_pl0,
                oa_len=_as_number(oa_len, 5.0),
                ab_len=_as_number(ab_len, 14.0),
                div_count=_as_int(divc, 10),
                bi_len=_as_number(bi_len, 60.0),
                ij_len=_as_number(ij_len, 10.0),
                kl_len=_as_number(kl_len, 0.5),
                bp_len=_as_number(bp_len, 0.0),
            ).solve()

            # Step-A
            self.JSV3_RefPlane_O = getattr(js, "ref_plane_O", None)
            self.JSV3_RefPlane_O_XZ = getattr(js, "ref_plane_O_XZ", None)
            self.JSV3_RefPlane_O_YZ = getattr(js, "ref_plane_O_YZ", None)
            self.JSV3_Polyline_O_to_B = getattr(js, "polyline_curve", None)
            self.JSV3_Points_OA = _safe_list(getattr(js, "points_OA", []))
            self.JSV3_Points_AB = _safe_list(getattr(js, "points_AB", []))
            self.JSV3_ConnectorLines = _safe_list(getattr(js, "connector_lines", []))
            self.JSV3_Intersections_FGH = _safe_list(getattr(js, "intersections", []))

            # Step-B
            self.JSV3_Point_I = getattr(js, "I", None)
            self.JSV3_Point_J = getattr(js, "J", None)
            self.JSV3_Point_K = getattr(js, "K", None)
            self.JSV3_Point_L = getattr(js, "L", None)
            self.JSV3_Plane_BJI = getattr(js, "plane_bji", None)
            self.JSV3_Curve_BLJ = getattr(js, "curve_blj", None)

            # Step-C
            self.JSV3_Point_Op = getattr(js, "O_p", None)
            self.JSV3_Points_FGHp = _safe_list(getattr(js, "FGH_p", []))
            self.JSV3_Point_I_from_move = getattr(js, "I_from_move", None)
            self.JSV3_Points_FGHpp = _safe_list(getattr(js, "FGH_pp", []))
            self.JSV3_Polyline_Op_to_J = getattr(js, "polyline_op_to_j", None)

            # Step-D
            self.JSV3_Point_P = getattr(js, "P", None)
            self.JSV3_Rail_BP = getattr(js, "rail_bp", None)
            self.JSV3_Surface_Red = getattr(js, "surface_red", None)
            self.JSV3_Surface_Purple = getattr(js, "surface_purple", None)
            self.JSV3_Surface_S = getattr(js, "surface_s", None)
            self.JSV3_Surface_S_mirror = getattr(js, "surface_s_mirror", None)
            self.JSV3_Surface_Final = getattr(js, "surface_final", None)

            # Step-E
            self.JSV3_Top_S = getattr(js, "top_s", None)
            self.JSV3_Cube_Brep = getattr(js, "cube_brep", None)
            self.JSV3_Cube_Parts_Raw = _safe_list(getattr(js, "cube_parts_raw", []))
            self.JSV3_Cube_Parts = _safe_list(getattr(js, "cube_parts", []))
            self.JSV3_Cube_Parts_JoinedAll = _safe_list(getattr(js, "cube_parts_joined_all", []))

            # Step-F
            self.JSV3_Cube_Parts_Vol = _safe_list(getattr(js, "cube_parts_vol", []))
            self.JSV3_Solid_MaxVolume = getattr(js, "solid_max_volume", None)

            try:
                self.JSV3_Debug = js.debug_text()
            except:
                self.JSV3_Debug = ""

            self.Log.append("[JUANSHA_V3] OK: OA={} AB={} BP_len={} DivCount={}".format(
                oa_len, ab_len, bp_len, _as_int(divc, 10)
            ))

        except Exception as e:
            self.JSV3_Debug = "[ERROR] {}".format(e)
            self.JSV3_Solid_MaxVolume = None
            self.Log.append("[ERROR][JUANSHA_V3] JuanShaV3 出错: {}".format(e))
            return self

        # ---- 5.3 GeoAligner::3 ----
        try:
            rotate_deg = self.all_get("GeoAligner_3__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_3__FlipX", False)
            flip_y = self.all_get("GeoAligner_3__FlipY", False)
            flip_z = self.all_get("GeoAligner_3__FlipZ", False)  # 重点：此步要求 FlipZ
            move_x = self.all_get("JuanShaV3__AB_BP", 0.0)  # MoveX 来自 JuanShaV3__AB_BP
            move_y = self.all_get("GeoAligner_3__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_3__MoveZ", 0.0)

            self.GA3_SourceOut = []
            self.GA3_TargetOut = []
            self.GA3_TransformOut = []
            self.GA3_MovedGeo = []

            geos = _ensure_list(self.JSV3_Solid_MaxVolume)
            sps = _ensure_list(self.JSV3_RefPlane_O_XZ)
            tps = _ensure_list(self.PFL3_ResultPlane)

            for geo, sp, tp, rd, fx, fy, fz, mx, my, mz in _gh_broadcast(
                    geos, sps, tps, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z
            ):
                if geo is None or sp is None or tp is None:
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    sp,
                    tp,
                    rotate_deg=_as_number(rd, 0.0),
                    flip_x=_as_bool01(fx, False),
                    flip_y=_as_bool01(fy, False),
                    flip_z=_as_bool01(fz, False),
                    move_x=_as_number(mx, 0.0),
                    move_y=_as_number(my, 0.0),
                    move_z=_as_number(mz, 0.0),
                )

                self.GA3_SourceOut.append(SourceOut)
                self.GA3_TargetOut.append(TargetOut)
                self.GA3_TransformOut.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                self.GA3_MovedGeo.append(MovedGeo)

            self.GA3_MovedGeo = _safe_list(self.GA3_MovedGeo)

            if len(self.GA3_MovedGeo) == 0:
                self.Log.append("[GA3] Geo 为空或对位失败，跳过。")
            else:
                self.Log.append("[GA3] OK: aligned={} flip_z={}".format(len(self.GA3_MovedGeo), flip_z))

        except Exception as e:
            self.GA3_SourceOut = []
            self.GA3_TargetOut = []
            self.GA3_TransformOut = []
            self.GA3_MovedGeo = []
            self.Log.append("[ERROR][GA3] GeoAligner::3 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # 主控入口
    # ------------------------------------------------------

    # ------------------------------------------------------
    # Step 6：楔形刀（XieXingTool + GeoAligner::4）
    # ------------------------------------------------------
    def step6_wedge_tool(self):
        """
        Step 6 包括：
        1) XieXingTool（WedgeShapedTool）
            AB            = AllDict['XieXingTool__AB']
            AC            = AllDict['XieXingTool__AC']
            offset        = AllDict['XieXingTool__offset']
            output_lower_a= AllDict['XieXingTool__output_lower_a']
            base_point    = 原点（典型做法：先在原点建，再对位）
            reference_plane = "WorldXZ"
        2) GeoAligner::4
            Geo         = XieXingTool.SolidBrep
            SourcePlane = XieXingTool.A_RefPlanes[ GeoAligner_4__SourcePlane ]
            TargetPlane = PlaneFromLists::3.ResultPlane
            RotateDeg   = AllDict['GeoAligner_4__RotateDeg']
            FlipZ       = AllDict['GeoAligner_4__FlipZ']
            其它 FlipX/FlipY/MoveX/Y/Z 若 DB 中存在则读取，否则默认。
        """

        # ---- 6.1 build XieXingTool ----
        try:
            ab = self.all_get("XieXingTool__AB", None)
            ac = self.all_get("XieXingTool__AC", None)
            off = self.all_get("XieXingTool__offset", None)
            out_lower = self.all_get("XieXingTool__output_lower_a", True)

            if ab is None: ab = 6.0
            if ac is None: ac = 14.0
            if off is None: off = 3.0

            out_lower = _as_bool01(out_lower, True)

            tool = WedgeShapedTool(
                base_point=rg.Point3d(0, 0, 0),
                reference_plane="WorldXZ",
                AB=_as_number(ab, 6.0),
                AC=_as_number(ac, 14.0),
                offset=_as_number(off, 3.0),
                output_lower_a=out_lower
            )

            self.XieXing_SolidBrep = tool.build()
            self.XieXing_SectionCrv = getattr(tool, "section_crv", None)
            self.XieXing_PlaneOut = getattr(tool, "plane_out", None)
            self.XieXing_A_RefPlanes = _safe_list(getattr(tool, "a_ref_planes", []))
            try:
                self.XieXing_Log = _safe_list(tool.get_log())
            except:
                self.XieXing_Log = []

            self.Log.append("[XieXingTool] OK: AB={} AC={} offset={} lowerA={}".format(
                ab, ac, off, out_lower
            ))

        except Exception as e:
            self.XieXing_SolidBrep = None
            self.XieXing_A_RefPlanes = []
            self.XieXing_Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR][XieXingTool] 出错: {}".format(e))
            return self

        # ---- 6.2 GeoAligner::4 ----
        try:
            # SourcePlane index (can be scalar or list)
            src_idx = self.all_get("GeoAligner_4__SourcePlane", 0)

            rotate_deg = self.all_get("GeoAligner_4__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_4__FlipX", False)
            flip_y = self.all_get("GeoAligner_4__FlipY", False)
            flip_z = self.all_get("GeoAligner_4__FlipZ", False)
            move_x = self.all_get("GeoAligner_4__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_4__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_4__MoveZ", 0.0)

            self.GA4_SourceOut = []
            self.GA4_TargetOut = []
            self.GA4_TransformOut = []
            self.GA4_MovedGeo = []

            geo_list = _ensure_list(self.XieXing_SolidBrep)
            # target planes use PFL3
            tp_list = _ensure_list(self.PFL3_ResultPlane)

            for geo, tp, idx, rd, fx, fy, fz, mx, my, mz in _gh_broadcast(
                    geo_list, tp_list, src_idx, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z
            ):
                if geo is None or tp is None:
                    continue

                sp = self._pick_from_list(self.XieXing_A_RefPlanes, idx, default=None, wrap=True)
                if sp is None:
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    sp,
                    tp,
                    rotate_deg=_as_number(rd, 0.0),
                    flip_x=_as_bool01(fx, False),
                    flip_y=_as_bool01(fy, False),
                    flip_z=_as_bool01(fz, False),
                    move_x=_as_number(mx, 0.0),
                    move_y=_as_number(my, 0.0),
                    move_z=_as_number(mz, 0.0),
                )

                self.GA4_SourceOut.append(SourceOut)
                self.GA4_TargetOut.append(TargetOut)
                self.GA4_TransformOut.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                self.GA4_MovedGeo.append(MovedGeo)

            self.GA4_MovedGeo = _safe_list(self.GA4_MovedGeo)

            if len(self.GA4_MovedGeo) == 0:
                self.Log.append("[GA4] Geo 为空或对位失败，跳过。")
            else:
                self.Log.append("[GA4] OK: aligned={} src_idx={}".format(len(self.GA4_MovedGeo), src_idx))

        except Exception as e:
            self.GA4_SourceOut = []
            self.GA4_TargetOut = []
            self.GA4_TransformOut = []
            self.GA4_MovedGeo = []
            self.Log.append("[ERROR][GA4] GeoAligner::4 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 7：乳栿卷殺（RuFUJuanSha + GeoAligner::5）
    # ------------------------------------------------------
    def step7_rufu_juansha(self):
        """
        Step 7 包括：
        1) RuFUJuanSha（yingzao.ancientArchi.RuFuJuanSha）
            OA_len        = AllDict['RuFUJuanSha__OA_len']
            OB_len        = AllDict['RuFUJuanSha__OB_len']
            AC_len        = AllDict['XieXingTool__AC']
            BI_len        = AllDict['RuFUJuanSha__BI_len']
            LiftY_len     = AllDict['XieXingTool__AB']
            JJp_len       = AllDict['RuFUJuanSha__JJp_len']
            LLp_len       = AllDict['RuFUJuanSha__LLp_len']
            NNp_len       = AllDict['RuFUJuanSha__NNp_len']
            UsePolylineHE = AllDict['RuFUJuanSha__UsePolylineHE']
            FX_len        = AllDict['RuFUJuanSha__FX_len']
            DivN          = AllDict['RuFUJuanSha__DivN']
        2) GeoAligner::5
            Geo         = RuFUJuanSha.ClosedBreps_Mirrored
            SourcePlane = RuFUJuanSha.ReferencePlanes_O[ GeoAligner_5__SourcePlane ]
            TargetPlane = Transform( JuanShaV3.RefPlane_O_XZ, GeoAligner::3.TransformOut )
                         即：先用 GA3 的变换把 RefPlane_O_XZ 变换到目标空间，再作为 TargetPlane
        """

        # ---- 7.1 RuFUJuanSha ----
        try:
            OA_len = self.all_get("RuFUJuanSha__OA_len", 5.0)
            OB_len = self.all_get("RuFUJuanSha__OB_len", 14.0)
            AC_len = self.all_get("XieXingTool__AC", 50.0)
            BI_len = self.all_get("RuFUJuanSha__BI_len", 60.0)
            LiftY_len = self.all_get("XieXingTool__AB", 21.0)

            JJp_len = self.all_get("RuFUJuanSha__JJp_len", 1.0)
            LLp_len = self.all_get("RuFUJuanSha__LLp_len", 1.0)
            NNp_len = self.all_get("RuFUJuanSha__NNp_len", 1.0)

            UsePolylineHE = _as_bool01(self.all_get("RuFUJuanSha__UsePolylineHE", False), False)
            FX_len = self.all_get("RuFUJuanSha__FX_len", 40.0)
            DivN = self.all_get("RuFUJuanSha__DivN", 4)

            rufu = RuFuJuanSha(
                base_point=rg.Point3d(0, 0, 0),
                ref_plane="WorldXZ",
                OA_len=_as_number(OA_len, 5.0),
                OB_len=_as_number(OB_len, 14.0),
                AC_len=_as_number(AC_len, 50.0),
                BI_len=_as_number(BI_len, 60.0),
                LiftY_len=_as_number(LiftY_len, 21.0),
                JJp_len=_as_number(JJp_len, 1.0),
                LLp_len=_as_number(LLp_len, 1.0),
                NNp_len=_as_number(NNp_len, 1.0),
                UsePolylineHE=UsePolylineHE,
                FX_len=_as_number(FX_len, 40.0),
                DivN=_as_int(DivN, 4),
            ).build_step_a().build_step_b().build_step_c()

            # 按组件输出接口提取（developer-friendly）
            self.RFJS_Points = _safe_list(rufu.get_output_points_ordered())
            self.RFJS_Lines = _safe_list(rufu.get_output_lines_ordered())
            self.RFJS_ArcCurves = _safe_list(rufu.get_output_arcs_ordered())
            self.RFJS_ArcCtrlPts = _safe_list(rufu.get_output_arc_ctrlpts_ordered())
            self.RFJS_ArcPlanes = _safe_list(rufu.get_output_arc_planes_ordered())
            try:
                self.RFJS_ArcData = rufu.get_arc_data()
            except:
                self.RFJS_ArcData = None
            self.RFJS_StepCSurfaces = _safe_list(rufu.get_step_c_surfaces_ordered())
            self.RFJS_StepCPlanes = _safe_list(rufu.get_step_c_planes_ordered())
            self.RFJS_ClosedBrep = rufu.get_closed_brep()
            try:
                self.RFJS_RefPlanes = _safe_list(rufu.get_refplanes())
            except:
                self.RFJS_RefPlanes = []
            try:
                self.RFJS_ReferencePlanes_O = _safe_list(rufu.build_reference_planes_at_O())
            except:
                self.RFJS_ReferencePlanes_O = []
            try:
                self.RFJS_ClosedBreps_Mirrored = _safe_list(rufu.get_closed_breps_mirrored())
            except:
                self.RFJS_ClosedBreps_Mirrored = []
            try:
                self.RFJS_Debug = rufu.get_debug()
            except:
                self.RFJS_Debug = ""

            self.Log.append("[RuFUJuanSha] OK: OA={} OB={} AC={} BI={} LiftY={} DivN={}".format(
                OA_len, OB_len, AC_len, BI_len, LiftY_len, DivN
            ))

        except Exception as e:
            self.RFJS_Debug = "[ERROR] {}".format(e)
            self.RFJS_ClosedBreps_Mirrored = []
            self.RFJS_ReferencePlanes_O = []
            self.Log.append("[ERROR][RuFUJuanSha] 出错: {}".format(e))
            return self

        # ---- 7.2 GeoAligner::5 ----
        try:
            # SourcePlane index（可为标量或列表）
            src_idx = self.all_get("GeoAligner_5__SourcePlane", 0)

            rotate_deg = self.all_get("GeoAligner_5__RotateDeg", 0.0)
            flip_x = self.all_get("GeoAligner_5__FlipX", False)
            flip_y = self.all_get("GeoAligner_5__FlipY", False)
            flip_z = self.all_get("GeoAligner_5__FlipZ", False)
            move_x = self.all_get("GeoAligner_5__MoveX", 0.0)
            move_y = self.all_get("GeoAligner_5__MoveY", 0.0)
            move_z = self.all_get("GeoAligner_5__MoveZ", 0.0)

            # TargetPlane：把 JuanShaV3.RefPlane_O_XZ 用 GA3.TransformOut 做变换
            base_tp = self.JSV3_RefPlane_O_XZ
            if base_tp is None:
                # 兜底：优先用 PFL3_ResultPlane[0]，否则用 WorldXZ@Origin
                base_tp = self.PFL3_ResultPlane[0] if len(
                    _ensure_list(self.PFL3_ResultPlane)) > 0 else GHPlaneFactory.from_name("XZ",
                                                                                           origin=rg.Point3d(0, 0, 0))

            def _unwrap_xform(t):
                if t is None:
                    return None
                # GH_Transform
                if hasattr(t, "Value"):
                    try:
                        return t.Value
                    except:
                        pass
                if hasattr(t, "Transform"):
                    try:
                        return t.Transform
                    except:
                        pass
                return t

            xforms = [_unwrap_xform(t) for t in _ensure_list(self.GA3_TransformOut)]
            if len(xforms) == 0:
                xforms = [None]

            target_planes = []
            for xf in xforms:
                pl = rg.Plane(base_tp)
                if xf is not None:
                    try:
                        pl.Transform(xf)
                    except:
                        pass
                target_planes.append(pl)

            self.GA5_SourceOut = []
            self.GA5_TargetOut = []
            self.GA5_TransformOut = []
            self.GA5_MovedGeo = []

            geos = _ensure_list(self.RFJS_ClosedBreps_Mirrored)
            tps = _ensure_list(target_planes)

            for geo, tp, idx, rd, fx, fy, fz, mx, my, mz in _gh_broadcast(
                    geos, tps, src_idx, rotate_deg, flip_x, flip_y, flip_z, move_x, move_y, move_z
            ):
                if geo is None or tp is None:
                    continue

                sp = self._pick_from_list(self.RFJS_ReferencePlanes_O, idx, default=None, wrap=True)
                if sp is None:
                    continue

                SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                    geo,
                    sp,
                    tp,
                    rotate_deg=_as_number(rd, 0.0),
                    flip_x=_as_bool01(fx, False),
                    flip_y=_as_bool01(fy, False),
                    flip_z=_as_bool01(fz, False),
                    move_x=_as_number(mx, 0.0),
                    move_y=_as_number(my, 0.0),
                    move_z=_as_number(mz, 0.0),
                )

                self.GA5_SourceOut.append(SourceOut)
                self.GA5_TargetOut.append(TargetOut)
                self.GA5_TransformOut.append(ght.GH_Transform(TransformOut) if TransformOut is not None else None)
                self.GA5_MovedGeo.append(MovedGeo)

            self.GA5_MovedGeo = _safe_list(self.GA5_MovedGeo)

            if len(self.GA5_MovedGeo) == 0:
                self.Log.append("[GA5] Geo 为空或对位失败，跳过。")
            else:
                self.Log.append("[GA5] OK: aligned={} src_idx={}".format(len(self.GA5_MovedGeo), src_idx))

        except Exception as e:
            self.GA5_SourceOut = []
            self.GA5_TargetOut = []
            self.GA5_TransformOut = []
            self.GA5_MovedGeo = []
            self.Log.append("[ERROR][GA5] GeoAligner::5 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 8：裁切（BlockCutterV3）
    # ------------------------------------------------------
    def step8_cut(self):
        """
        BlockCutterV3:
            Timbers = Timber_block_uniform.TimberBrep
            Tools   = [GA1.MovedGeo, GA2.MovedGeo, GA3.MovedGeo, GA4.MovedGeo, GA5.MovedGeo] 组合列表（递归拍平）
        """
        try:
            timbers = self.TimberBrep
            tools = _deep_flatten([
                self.GA1_MovedGeo,
                self.GA2_MovedGeo,
                self.GA3_MovedGeo,
                self.GA4_MovedGeo,
                self.GA5_MovedGeo
            ])
            tools = [t for t in tools if t is not None]
            self.BC_Tools = tools

            keep_inside = _as_bool01(self.all_get("BlockCutterV3__KeepInside", False), False)
            dbg_in = self.all_get("BlockCutterV3__Debug", None)

            cutter = FT_CutTimbersByTools_GH_SolidDifference(
                debug=bool(dbg_in) if dbg_in is not None else False
            )
            CutTimbers, FailTimbers, CLog = cutter.cut(
                timbers=timbers,
                tools=tools,
                keep_inside=keep_inside,
                debug=dbg_in
            )

            self.BC_CutTimbers = _safe_list(CutTimbers)
            self.BC_FailTimbers = _safe_list(FailTimbers)
            self.BC_Log = _safe_list(CLog)

            # 最终主输出覆盖
            self.CutTimbers = self.BC_CutTimbers
            self.FailTimbers = self.BC_FailTimbers

            self.Log.append("[BlockCutterV3] OK: tools={} keep_inside={} cut={} fail={}".format(
                len(tools), keep_inside, len(self.CutTimbers), len(self.FailTimbers)
            ))
            for l in self.BC_Log:
                self.Log.append("[BC] " + str(l))

        except Exception as e:
            self.BC_CutTimbers = []
            self.BC_FailTimbers = []
            self.BC_Log = ["错误: {}".format(e)]
            self.BC_Tools = []
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[ERROR][BlockCutterV3] 出错: {}".format(e))

        return self

    def run(self):

        # Step 1：数据库
        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            return self

        # Step 2：原始木料构建
        self.step2_timber()

        # Step 3：顶部卷殺
        self.step3_top_juansha()

        # Step 4：两侧卷殺
        self.step4_side_juansha()

        # Step 5：底部卷殺
        self.step5_bottom_juansha()

        # Step 6：楔形刀
        self.step6_wedge_tool()

        # Step 7：乳栿卷殺
        self.step7_rufu_juansha()

        self.step8_cut()

        return self


if __name__ == "__main__":
    # ==============================================================
    # GH Python 组件输出绑定区（developer-friendly）
    #   说明：
    #   1) CutTimbers/FailTimbers/Log 为“面向使用者”的主输出；
    #   2) 其余为“开发模式输出”，你在 GH 里增加同名输出端即可随时挂出调试。
    # ==============================================================

    solver = RuFuInner4PUSolver(DBPath, base_point, Refresh, ghenv).run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- Step1: DB 输出 ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- Step2: Timber 输出（与 Timber_block_uniform 保持一致命名）---
    TimberBrep = solver.TimberBrep
    FaceList = solver.FaceList
    PointList = solver.PointList
    EdgeList = solver.EdgeList
    CenterPoint = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    EdgeMidPoints = solver.EdgeMidPoints
    FacePlaneList = solver.FacePlaneList
    Corner0Planes = solver.Corner0Planes
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = solver.FaceDirTags
    EdgeDirTags = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs
    TimberLog = solver.TimberLog

    # --- Step3: 顶部卷殺输出（developer-friendly）---
    PFL1_BasePlane = solver.PFL1_BasePlane
    PFL1_OriginPoint = solver.PFL1_OriginPoint
    PFL1_ResultPlane = solver.PFL1_ResultPlane
    PFL1_Log = solver.PFL1_Log

    JuanSha1_ToolBrep = solver.JuanSha1_ToolBrep
    JuanSha1_SectionEdges = solver.JuanSha1_SectionEdges
    JuanSha1_HL_Intersection = solver.JuanSha1_HL_Intersection
    JuanSha1_HeightFacePlane = solver.JuanSha1_HeightFacePlane
    JuanSha1_LengthFacePlane = solver.JuanSha1_LengthFacePlane
    JuanSha1_Log = solver.JuanSha1_Log

    GA1_SourceOut = solver.GA1_SourceOut
    GA1_TargetOut = solver.GA1_TargetOut
    GA1_TransformOut = solver.GA1_TransformOut
    GA1_MovedGeo = solver.GA1_MovedGeo

    # --- Step4: 两侧卷殺输出（developer-friendly）---
    PFL2_BasePlane = solver.PFL2_BasePlane
    PFL2_OriginPoint = solver.PFL2_OriginPoint
    PFL2_ResultPlane = solver.PFL2_ResultPlane
    PFL2_Log = solver.PFL2_Log

    JuanSha2_ToolBrep = solver.JuanSha2_ToolBrep
    JuanSha2_SectionEdges = solver.JuanSha2_SectionEdges
    JuanSha2_HL_Intersection = solver.JuanSha2_HL_Intersection
    JuanSha2_HeightFacePlane = solver.JuanSha2_HeightFacePlane
    JuanSha2_LengthFacePlane = solver.JuanSha2_LengthFacePlane
    JuanSha2_Log = solver.JuanSha2_Log

    GA2_SourceOut = solver.GA2_SourceOut
    GA2_TargetOut = solver.GA2_TargetOut
    GA2_TransformOut = solver.GA2_TransformOut
    GA2_MovedGeo = solver.GA2_MovedGeo

    # --- Step5: 底部卷殺输出（developer-friendly）---
    PFL3_BasePlane = solver.PFL3_BasePlane
    PFL3_OriginPoint = solver.PFL3_OriginPoint
    PFL3_ResultPlane = solver.PFL3_ResultPlane
    PFL3_Log = solver.PFL3_Log

    # JuanShaV3 (RuFuJuanShaBottomSolver) outputs
    JSV3_RefPlane_O = solver.JSV3_RefPlane_O
    JSV3_RefPlane_O_XZ = solver.JSV3_RefPlane_O_XZ
    JSV3_RefPlane_O_YZ = solver.JSV3_RefPlane_O_YZ
    JSV3_Polyline_O_to_B = solver.JSV3_Polyline_O_to_B
    JSV3_Points_OA = solver.JSV3_Points_OA
    JSV3_Points_AB = solver.JSV3_Points_AB
    JSV3_ConnectorLines = solver.JSV3_ConnectorLines
    JSV3_Intersections_FGH = solver.JSV3_Intersections_FGH

    JSV3_Point_I = solver.JSV3_Point_I
    JSV3_Point_J = solver.JSV3_Point_J
    JSV3_Point_K = solver.JSV3_Point_K
    JSV3_Point_L = solver.JSV3_Point_L
    JSV3_Plane_BJI = solver.JSV3_Plane_BJI
    JSV3_Curve_BLJ = solver.JSV3_Curve_BLJ

    JSV3_Point_Op = solver.JSV3_Point_Op
    JSV3_Points_FGHp = solver.JSV3_Points_FGHp
    JSV3_Point_I_from_move = solver.JSV3_Point_I_from_move
    JSV3_Points_FGHpp = solver.JSV3_Points_FGHpp
    JSV3_Polyline_Op_to_J = solver.JSV3_Polyline_Op_to_J

    JSV3_Point_P = solver.JSV3_Point_P
    JSV3_Rail_BP = solver.JSV3_Rail_BP
    JSV3_Surface_Red = solver.JSV3_Surface_Red
    JSV3_Surface_Purple = solver.JSV3_Surface_Purple
    JSV3_Surface_S = solver.JSV3_Surface_S
    JSV3_Surface_S_mirror = solver.JSV3_Surface_S_mirror
    JSV3_Surface_Final = solver.JSV3_Surface_Final

    JSV3_Top_S = solver.JSV3_Top_S
    JSV3_Cube_Brep = solver.JSV3_Cube_Brep
    JSV3_Cube_Parts_Raw = solver.JSV3_Cube_Parts_Raw
    JSV3_Cube_Parts = solver.JSV3_Cube_Parts
    JSV3_Cube_Parts_JoinedAll = solver.JSV3_Cube_Parts_JoinedAll

    JSV3_Cube_Parts_Vol = solver.JSV3_Cube_Parts_Vol
    JSV3_Solid_MaxVolume = solver.JSV3_Solid_MaxVolume
    JSV3_Debug = solver.JSV3_Debug

    GA3_SourceOut = solver.GA3_SourceOut
    GA3_TargetOut = solver.GA3_TargetOut
    GA3_TransformOut = solver.GA3_TransformOut
    GA3_MovedGeo = solver.GA3_MovedGeo

    # --- Step6: 楔形刀输出（developer-friendly）---
    XieXing_SolidBrep = solver.XieXing_SolidBrep
    XieXing_SectionCrv = solver.XieXing_SectionCrv
    XieXing_PlaneOut = solver.XieXing_PlaneOut
    XieXing_A_RefPlanes = solver.XieXing_A_RefPlanes
    XieXing_Log = solver.XieXing_Log

    GA4_SourceOut = solver.GA4_SourceOut
    GA4_TargetOut = solver.GA4_TargetOut
    GA4_TransformOut = solver.GA4_TransformOut
    GA4_MovedGeo = solver.GA4_MovedGeo

    # --- Step7: 乳栿卷殺输出（developer-friendly）---
    RFJS_Points = solver.RFJS_Points
    RFJS_Lines = solver.RFJS_Lines
    RFJS_ArcCurves = solver.RFJS_ArcCurves
    RFJS_ArcCtrlPts = solver.RFJS_ArcCtrlPts
    RFJS_ArcPlanes = solver.RFJS_ArcPlanes
    RFJS_ArcData = solver.RFJS_ArcData
    RFJS_StepCSurfaces = solver.RFJS_StepCSurfaces
    RFJS_StepCPlanes = solver.RFJS_StepCPlanes
    RFJS_ClosedBrep = solver.RFJS_ClosedBrep
    RFJS_RefPlanes = solver.RFJS_RefPlanes
    RFJS_ReferencePlanes_O = solver.RFJS_ReferencePlanes_O
    RFJS_ClosedBreps_Mirrored = solver.RFJS_ClosedBreps_Mirrored
    RFJS_Debug = solver.RFJS_Debug

    GA5_SourceOut = solver.GA5_SourceOut
    GA5_TargetOut = solver.GA5_TargetOut
    GA5_TransformOut = solver.GA5_TransformOut
    GA5_MovedGeo = solver.GA5_MovedGeo


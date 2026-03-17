# -*- coding: utf-8 -*-
"""
QiAoToolSolver.py (Refactored)

乳栿劄牽_欹䫜刀（QiAo）·宋 · 单一 GhPython 组件（不使用数据库）
------------------------------------------------------------
本版本解决：
- Script Editor 的 Pyflakes 报错：undefined name 'timbers' / 'tools'
  （原因：旧文件中 step5 方法后残留了未缩进/重复片段）
- 将代码重构为“工具类 + Solver 类 + GH 入口”三段，便于后续复用/调用
- CutTimbers = TimberBrep - AlignedTool 的裁切方式：优先 GH SolidDifference（更贴近 GH 原生）
- 参考平面：严格按 Grasshopper XY/XZ/YZ Plane 的轴系定义构造

【输入 Inputs（GhPython 建议设置）】
------------------------------------------------------------
# --- FT_timber_block_uniform（木料）---
length_fen : float        Access:item  TypeHint:float   默认 41
width_fen  : float        Access:item  TypeHint:float   默认 16
height_fen : float        Access:item  TypeHint:float   默认 10
base_point : rg.Point3d   Access:item  TypeHint:Point3d 默认 World Origin
timber_ref_plane_mode : object Access:item TypeHint:generic 默认 "XZ"
    - 支持: "XY"/"XZ"/"YZ" 或 "WorldXY"/"WorldXZ"/"WorldYZ"
    - 或直接传入 rg.Plane（会仅替换 Origin）

# --- FT_QiAo（欹䫜刀）---
qi_height       : float   Access:item TypeHint:float 默认 4
sha_width       : float   Access:item TypeHint:float 默认 2
qi_offset_fen   : float   Access:item TypeHint:float 默认 0.5
extrude_length  : float   Access:item TypeHint:float 默认 28
extrude_positive: bool    Access:item TypeHint:bool  默认 False
qi_ref_plane_mode : object Access:item TypeHint:generic 默认 "XZ"

# --- 可选 ---
Refresh : bool  Access:item TypeHint:bool 默认 False

【内部固定默认（不提供输入端）】
------------------------------------------------------------
PlaneFromLists::1:
    IndexOrigin = 8
    IndexPlane  = 1

FT_AlignToolToTimber::1:
    BlockRotDeg = 90   （与附件参考实现一致：字段名 ToolRotDeg 但实际作为 BlockRotDeg 使用）
    ToolRotDeg  = None

【输出 Outputs（建议）】
------------------------------------------------------------
CutTimbers  : list[Brep] 或 Brep
FailTimbers : list[Brep]
TimberBrep  : Brep
ToolBrep    : Brep
AlignedTool : list[Brep]
Log         : list[str]
"""

__author__  = "richiebao [coding-x.tech]"
__version__ = "2026.01.03-qiao-noDB-v8.4-allTimberOutputs"

import Rhino.Geometry as rg
import scriptcontext as sc

from yingzao.ancientArchi import (
    build_timber_block_uniform,
    build_qiao_tool,
    FTPlaneFromLists,
    FTAligner,
    FT_CutTimberByTools,   # fallback
)

# ---------------------------------------------------------
# 可选：GH 组件调用（SolidDifference）
# ---------------------------------------------------------
try:
    import ghpythonlib.components as ghc
except Exception:
    ghc = None


# =========================================================
# 小工具：输入安全读取 + 类型转换 + GH Plane 构造
# =========================================================

class InputHelper(object):
    """GhPython 输入读取：变量不存在/None -> 默认值。

    重要说明（为兼容“从 yingzao.ancientArchi 导入 InputHelper”这种用法）：
    - 当本文件作为 GhPython 脚本直接运行时，globals() 就是组件脚本全局，能读到输入端变量；
    - 当 InputHelper 从外部模块被 import 到 GhPython 脚本时，InputHelper 所在模块的 globals()
      不包含组件输入端变量，这会导致读取失败而回退默认值；
    - 因此这里额外尝试从 sys.modules['__main__'].__dict__ 读取（它对应 GhPython 组件脚本的全局域）。
    """
    @staticmethod
    def IN(name, default):
        # 1) 优先：当前模块全局（本文件直接作为 GhPython 脚本时适用）
        try:
            g = globals()
            if name in g:
                v = g.get(name, None)
                if v is not None:
                    return v
        except Exception:
            pass

        # 2) 兼容：GhPython 组件脚本的全局域（从外部模块 import 时适用）
        try:
            import sys
            main_mod = sys.modules.get("__main__", None)
            if main_mod is not None:
                mg = getattr(main_mod, "__dict__", None)
                if mg and (name in mg):
                    v = mg.get(name, None)
                    if v is not None:
                        return v
        except Exception:
            pass

        return default
    @staticmethod
    def to_bool(x, default=False):
        if x is None:
            return default
        if isinstance(x, bool):
            return x
        s = str(x).strip().lower()
        if s in ("true", "1", "yes", "y", "t"):
            return True
        if s in ("false", "0", "no", "n", "f"):
            return False
        return default

    @staticmethod
    def as_point3d(pt, default=None):
        if default is None:
            default = rg.Point3d(0, 0, 0)
        if pt is None:
            return rg.Point3d(default)
        if isinstance(pt, rg.Point3d):
            return rg.Point3d(pt)
        try:
            if isinstance(pt, (list, tuple)) and len(pt) >= 3:
                return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
        except Exception:
            pass
        return rg.Point3d(default)

    @staticmethod
    def flatten(x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            out = []
            for it in x:
                out.extend(InputHelper.flatten(it))
            return out
        return [x]


class GHPlaneFactory(object):
    """
    按 Grasshopper 的基准平面轴系定义构造参考平面：
    GH XY: X(1,0,0) Y(0,1,0) Z(0,0,1)
    GH XZ: X(1,0,0) Y(0,0,1) Z(0,-1,0)
    GH YZ: X(0,1,0) Y(0,0,1) Z(1,0,0)
    """
    @staticmethod
    def _unit(v):
        v = rg.Vector3d(v)
        if v.IsZero:
            return v
        v.Unitize()
        return v

    @staticmethod
    def make(mode, origin=None):
        if origin is None:
            origin = rg.Point3d(0, 0, 0)

        if isinstance(mode, rg.Plane):
            p = rg.Plane(mode)
            p.Origin = origin
            return p

        m = None if mode is None else str(mode).strip()
        if not m:
            return None

        ml = m.lower()
        if ml in ("worldxy", "xy"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 1, 0)
        elif ml in ("worldxz", "xz"):
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)
        elif ml in ("worldyz", "yz"):
            x = rg.Vector3d(0, 1, 0)
            y = rg.Vector3d(0, 0, 1)
        else:
            # 默认 XZ
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)

        x = GHPlaneFactory._unit(x)
        y = GHPlaneFactory._unit(y)
        return rg.Plane(origin, x, y)


# =========================================================
# GH SolidDifference Cutter（贴近 GH 原生差集）
# =========================================================

class GHSolidDifferenceCutter(object):
    def __init__(self, debug=False):
        self.debug = bool(debug)

    @staticmethod
    def _coerce_brep(x):
        if x is None:
            return None
        if isinstance(x, rg.Brep):
            return x
        try:
            v = getattr(x, "Value", None)
            if isinstance(v, rg.Brep):
                return v
        except Exception:
            pass
        try:
            b = rg.Brep.TryConvertBrep(x)
            if isinstance(b, rg.Brep):
                return b
        except Exception:
            pass
        return None

    def _as_brep_list(self, x):
        items = InputHelper.flatten(x)
        out = []
        for it in items:
            b = self._coerce_brep(it)
            if b is not None:
                out.append(b)
        return out

    def cut(self, timbers, tools):
        Log = []
        if ghc is None:
            Log.append("[ERROR] ghpythonlib.components 不可用：无法调用 GH SolidDifference。")
            return [], [], Log

        timber_list = self._as_brep_list(timbers)
        tool_list   = self._as_brep_list(tools)

        Log.append("[INFO] Timbers count = {}".format(len(timber_list)))
        Log.append("[INFO] Tools count   = {}".format(len(tool_list)))

        if not timber_list:
            Log.append("[WARN] Timbers 为空：无输出。")
            return [], [], Log

        if not tool_list:
            Log.append("[WARN] Tools 为空：不切削，直接输出 Timbers。")
            return timber_list[:], [], Log

        CutTimbers = []
        FailTimbers = []

        for i, tb in enumerate(timber_list):
            try:
                res = ghc.SolidDifference(tb, tool_list)
                res0 = res[0] if (isinstance(res, tuple) and len(res) > 0) else res
                parts = InputHelper.flatten(res0)
                parts = [p for p in parts if p is not None]

                # 尽量转 Brep（部分情况下 GH 会返回 BrepGoo）
                brep_parts = []
                for p in parts:
                    bp = self._coerce_brep(p)
                    brep_parts.append(bp if bp is not None else p)

                if not brep_parts:
                    FailTimbers.append(tb)
                    Log.append("[WARN] timber#{} 差集结果为空（可能无交/失败）。".format(i))
                else:
                    CutTimbers.extend(brep_parts)
                    if self.debug:
                        Log.append("[DEBUG] timber#{} -> parts={}".format(i, len(brep_parts)))
            except Exception as e:
                FailTimbers.append(tb)
                Log.append("[ERROR] timber#{} SolidDifference 异常: {}".format(i, e))

        return InputHelper.flatten(CutTimbers), InputHelper.flatten(FailTimbers), InputHelper.flatten(Log)


# =========================================================
# Solver：QiAoToolSolver
# =========================================================

class QiAoToolSolver(object):

    def __init__(self, ghenv=None):
        self.ghenv = ghenv
        self.Log = []

        # outputs / debug
        self.TimberBrep = None
        self.ToolBrep = None
        self.AlignedTool = []   # list
        self.CutTimbers = []
        self.FailTimbers = []

        # Step1 intermediates (for PlaneFromLists)
        self.EdgeMidPoints = []
        self.Corner0Planes = []
        self.PFL1_ResultPlane = None
        self.QiAo_FacePlane = None

    # ----------------------------
    # Step1 Timber
    # ----------------------------
    def step1_timber_block(self, params):
        try:
            bp = params["base_point"]
            reference_plane = params["timber_ref_plane"]

            (
                TimberBrep,
                FaceList,
                PointList,
                EdgeList,
                CenterPoint,
                CenterAxisLines,
                EdgeMidPoints,
                FacePlaneList,
                Corner0Planes,
                LocalAxesPlane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
                log_lines
            ) = build_timber_block_uniform(
                params["length_fen"],
                params["width_fen"],
                params["height_fen"],
                bp,
                reference_plane
            )

            # --- 全量保存（供开发模式输出）---
            self.TimberBrep      = TimberBrep
            self.FaceList        = FaceList
            self.PointList       = PointList
            self.EdgeList        = EdgeList
            self.CenterPoint     = CenterPoint
            self.CenterAxisLines = CenterAxisLines
            self.EdgeMidPoints   = EdgeMidPoints
            self.FacePlaneList   = FacePlaneList
            self.Corner0Planes   = Corner0Planes
            self.LocalAxesPlane  = LocalAxesPlane
            self.AxisX           = axis_x
            self.AxisY           = axis_y
            self.AxisZ           = axis_z
            self.FaceDirTags     = face_tags
            self.EdgeDirTags     = edge_tags
            self.Corner0EdgeDirs = corner0_dirs

            self.Log.append(
                "[TIMBER] OK: L/W/H = {}/{}/{}".format(
                    params["length_fen"], params["width_fen"], params["height_fen"]
                )
            )
            self.Log.extend(InputHelper.flatten(log_lines))

        except Exception as e:
            # 清空但仍暴露属性名，避免 GH 输出端报错
            self.TimberBrep      = None
            self.FaceList        = []
            self.PointList       = []
            self.EdgeList        = []
            self.CenterPoint     = None
            self.CenterAxisLines = []
            self.EdgeMidPoints   = []
            self.FacePlaneList   = []
            self.Corner0Planes   = []
            self.LocalAxesPlane  = None
            self.AxisX           = None
            self.AxisY           = None
            self.AxisZ           = None
            self.FaceDirTags     = []
            self.EdgeDirTags     = []
            self.Corner0EdgeDirs = []

            self.Log.append("[TIMBER][ERROR] {}".format(e))

        return self


    # ----------------------------
    # Step2 Tool
    # ----------------------------
    def step2_build_qiao_tool(self, params):
        try:
            bp = params["base_point"]
            reference_plane = params["qi_ref_plane"]

            ToolBrep, BasePoint, BaseLine, SecPlane, FacePlane = build_qiao_tool(
                params["qi_height"],
                params["sha_width"],
                params["qi_offset_fen"],
                params["extrude_length"],
                bp,
                reference_plane,
                params["extrude_positive"]
            )
            self.ToolBrep = ToolBrep
            self.QiAo_FacePlane = FacePlane
            self.Log.append("[QIAO] OK")
        except Exception as e:
            self.ToolBrep = None
            self.QiAo_FacePlane = None
            self.Log.append("[QIAO][ERROR] {}".format(e))
        return self

    # ----------------------------
    # Step3 PlaneFromLists::1 (fixed)
    # ----------------------------
    def step3_plane_from_lists_1(self, IndexOrigin=8, IndexPlane=1, Wrap=True):
        try:
            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, log_lines = builder.build_plane(
                self.EdgeMidPoints,
                self.Corner0Planes,
                int(IndexOrigin),
                int(IndexPlane)
            )
            self.PFL1_ResultPlane = ResultPlane
            self.Log.append("[PFL1] OK: IndexOrigin={} IndexPlane={}".format(IndexOrigin, IndexPlane))
            self.Log.extend(InputHelper.flatten(log_lines))
        except Exception as e:
            self.PFL1_ResultPlane = None
            self.Log.append("[PFL1][ERROR] {}".format(e))
        return self

    # ----------------------------
    # Step4 Align (match reference behavior)
    # - ToolRotDeg=None
    # - BlockRotDeg=90
    # ----------------------------
    def step4_align_tool_to_timber_1(self, BlockRotDeg=90.0):
        ToolGeo = self.ToolBrep
        ToolBasePlane = self.QiAo_FacePlane
        BlockFacePlane = self.PFL1_ResultPlane

        # normalize tools to list
        tools = []
        if ToolGeo is None:
            tools = []
        elif isinstance(ToolGeo, (list, tuple)):
            tools = list(ToolGeo)
        else:
            tools = [ToolGeo]

        if (not tools) or ToolBasePlane is None or BlockFacePlane is None:
            self.AlignedTool = []
            self.Log.append("[ALIGN][SKIP] missing Tool/Planes (Tool={}, ToolPlane={}, BlockPlane={})".format(
                "None" if ToolGeo is None else "OK",
                "None" if ToolBasePlane is None else "OK",
                "None" if BlockFacePlane is None else "OK"
            ))
            return self

        aligned_list = []
        try:
            for t in tools:
                aligned, xf, src_pl, tgt_pl, src_pt, tgt_pt, dbg = FTAligner.align(
                    t,
                    ToolBasePlane,
                    None,           # ToolContactPoint
                    BlockFacePlane,
                    None,           # BlockTargetPoint
                    None,           # Mode
                    None,           # ToolDir
                    None,           # TargetDir
                    None,           # DepthOffset
                    None,           # MoveU
                    None,           # MoveV
                    None,           # FlipX
                    None,           # FlipY
                    None,           # FlipZ
                    None,           # ToolRotDeg (关键：None)
                    float(BlockRotDeg)  # BlockRotDeg (关键：90)
                )
                aligned_list.append(aligned)
            self.AlignedTool = aligned_list
            self.Log.append("[ALIGN] OK: BlockRotDeg={}".format(BlockRotDeg))
        except Exception as e:
            self.AlignedTool = []
            self.Log.append("[ALIGN][ERROR] {}".format(e))
        return self

    # ----------------------------
    # Step5 Cut (GH SolidDifference first)
    # ----------------------------
    def step5_cut(self):
        try:
            if self.TimberBrep is None:
                self.CutTimbers = []
                self.FailTimbers = []
                self.Log.append("[CUT][WARN] TimberBrep is None")
                return self

            # Use GH SolidDifference when available
            if ghc is not None:
                cutter = GHSolidDifferenceCutter(debug=False)
                cut, fail, log_lines = cutter.cut(self.TimberBrep, self.AlignedTool)
                self.CutTimbers = cut
                self.FailTimbers = fail
                self.Log.append("[CUT] OK(GH): CutTimbers={}, FailTimbers={}".format(len(InputHelper.flatten(cut)), len(InputHelper.flatten(fail))))
                self.Log.extend(InputHelper.flatten(log_lines))
                return self

            # Fallback
            cutter = FT_CutTimberByTools(self.TimberBrep, self.AlignedTool)
            cut, fail, log_lines = cutter.run()
            self.CutTimbers = cut
            self.FailTimbers = fail if fail is not None else []
            self.Log.append("[CUT] OK(Fallback)")
            self.Log.extend(InputHelper.flatten(log_lines))
        except Exception as e:
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[CUT][ERROR] {}".format(e))
        return self

    # ----------------------------
    # Run all steps
    # ----------------------------
    def run(self, params):
        self.Log = []
        self.step1_timber_block(params)
        self.step2_build_qiao_tool(params)
        self.step3_plane_from_lists_1(IndexOrigin=8, IndexPlane=1, Wrap=True)
        self.step4_align_tool_to_timber_1(BlockRotDeg=90.0)
        self.step5_cut()
        return self


# =========================================================
# GH 入口：把所有输入端设为 Optional=True（一次）
# =========================================================

def _ensure_all_inputs_optional_once():
    try:
        comp = ghenv.Component
        if comp is None:
            return
        key = "QiAoToolSolver::inputs_optional_set::{}".format(__version__)
        if key in sc.sticky:
            return
        for p in comp.Params.Input:
            p.Optional = True
        sc.sticky[key] = True
    except Exception:
        pass

_ensure_all_inputs_optional_once()


# =========================================================
# GH 输出绑定区（参考 QiXinDouSolver 的写法）
# - 先安全读取输入端（不存在/未接线 -> None）
# - 组装 params（含默认值）
# - 运行 solver
# - 核心对外输出 + 开发模式可选输出
# =========================================================
if __name__ == "__main__":

    # -------------------------
    # 1) 读取 GhPython 输入端
    # -------------------------
    try:
        _length_fen = length_fen
    except:
        _length_fen = None

    try:
        _width_fen = width_fen
    except:
        _width_fen = None

    try:
        _height_fen = height_fen
    except:
        _height_fen = None

    try:
        _base_point = base_point
    except:
        _base_point = None

    try:
        _timber_ref_plane_mode = timber_ref_plane_mode
    except:
        _timber_ref_plane_mode = None

    try:
        _qi_height = qi_height
    except:
        _qi_height = None

    try:
        _sha_width = sha_width
    except:
        _sha_width = None

    try:
        _qi_offset_fen = qi_offset_fen
    except:
        _qi_offset_fen = None

    try:
        _extrude_length = extrude_length
    except:
        _extrude_length = None

    try:
        _extrude_positive = extrude_positive
    except:
        _extrude_positive = None

    try:
        _qi_ref_plane_mode = qi_ref_plane_mode
    except:
        _qi_ref_plane_mode = None

    try:
        _rf = Refresh
    except:
        _rf = False

    # -------------------------
    # 2) 默认值处理（未接线也不报错）
    # -------------------------
    bp = InputHelper.as_point3d(_base_point, rg.Point3d(0, 0, 0))

    def _to_float(x, default):
        try:
            if x is None:
                return float(default)
            return float(x)
        except:
            return float(default)

    params = {
        # timber
        "length_fen": _to_float(_length_fen, 41.0),
        "width_fen":  _to_float(_width_fen,  16.0),
        "height_fen": _to_float(_height_fen, 10.0),
        "base_point": bp,
        "timber_ref_plane": GHPlaneFactory.make(
            _timber_ref_plane_mode if _timber_ref_plane_mode is not None else "XZ",
            origin=bp
        ),

        # qiao
        "qi_height": _to_float(_qi_height, 4.0),
        "sha_width": _to_float(_sha_width, 2.0),
        "qi_offset_fen": _to_float(_qi_offset_fen, 0.5),
        "extrude_length": _to_float(_extrude_length, 28.0),
        "extrude_positive": InputHelper.to_bool(
            _extrude_positive if _extrude_positive is not None else False,
            default=False
        ),
        "qi_ref_plane": GHPlaneFactory.make(
            _qi_ref_plane_mode if _qi_ref_plane_mode is not None else "XZ",
            origin=bp
        ),
    }

    # Refresh（仅用于 sticky 缓存重建 solver 对象）
    _rf = InputHelper.to_bool(_rf, default=False)

    # -------------------------
    # 3) solver（sticky 可选）
    # -------------------------
    sticky_key = "QiAoToolSolver::{ver}".format(ver=__version__)

    solver = None
    if (not _rf) and (sticky_key in sc.sticky):
        solver = sc.sticky.get(sticky_key, None)

    if solver is None:
        solver = QiAoToolSolver(ghenv=ghenv)
        sc.sticky[sticky_key] = solver

    solver.run(params)

    # -------------------------
    # 4) 核心对外输出
    # -------------------------
    CutTimbers  = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log         = solver.Log

    # -------------------------
    # 5) 开发模式：按需在 GH 中添加同名输出端即可看到内部数据
    # （不影响正式使用，未添加输出端时不会产生额外开销）
    #
    # 可用调试输出端名（示例）：
    #   TimberBrep
    #   ToolBrep
    #   AlignedTool
    #   EdgeMidPoints
    #   Corner0Planes
    #   PFL1_ResultPlane
    #   QiAo_FacePlane
    # -------------------------
    try:
        TimberBrep  = solver.TimberBrep
        ToolBrep    = solver.ToolBrep
        AlignedTool = solver.AlignedTool

        # Step3 intermediates
        EdgeMidPoints   = solver.EdgeMidPoints
        Corner0Planes   = solver.Corner0Planes
        PFL1_ResultPlane= solver.PFL1_ResultPlane

        # QiAo tool planes
        QiAo_FacePlane  = solver.QiAo_FacePlane

        # --- Timber 全量调试输出 ---
        FaceList        = solver.FaceList
        PointList       = solver.PointList
        EdgeList        = solver.EdgeList
        CenterPoint     = solver.CenterPoint
        CenterAxisLines = solver.CenterAxisLines
        EdgeMidPoints   = solver.EdgeMidPoints
        FacePlaneList   = solver.FacePlaneList
        Corner0Planes   = solver.Corner0Planes
        LocalAxesPlane  = solver.LocalAxesPlane
        AxisX           = solver.AxisX
        AxisY           = solver.AxisY
        AxisZ           = solver.AxisZ
        FaceDirTags     = solver.FaceDirTags
        EdgeDirTags     = solver.EdgeDirTags
        Corner0EdgeDirs = solver.Corner0EdgeDirs


    except:
        pass



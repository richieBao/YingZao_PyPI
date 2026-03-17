# -*- coding: utf-8 -*-
"""
SiPU_ChaAng_CornerPU_ComponentAssemblySolver.py

【目标】
- 将用于构建“四鋪作插昂轉角鋪作（SiPU_ChaAng_CornerPU）”的一组 ghpy 自定义组件
  逐步转换为一个单独的 GH Python 组件（Solver）。
- 当前版本：仅完成 Step 1：DBJsonReader 读取数据库 params_json -> All / AllDict0
- 后续每次你提供一个“组件名 + 原 ghpy 代码”，我将新增一个 StepX（严格按 GH 连线串联）
  并在“输出绑定区”继续暴露到当前步骤为止的所有 solver 成员变量，便于调试与增减输出端。

=========================================================
GH Python 组件端口配置建议（当前 Step1 版本）
=========================================================

[Inputs]
DBPath      : item / str      # 数据库文件路径
PlacePlane  : item / Plane    # 放置参考平面（默认 GH XY Plane，Origin=(100,100,0)）
Refresh     : item / bool     # 刷新（重读数据库/重算）

[Outputs]
ComponentAssembly : list      # 最终组合体（当前 Step1 为空列表，占位）
Log               : str       # 日志

# --------- Step 1 暴露（便于检查 DBJsonReader 输出）---------
Value0    : any
All0      : list(tuple)  # [('key', value), ...]
AllDict0  : dict
DBLog0    : str/any

=========================================================
注意（Plane 轴向约定）
=========================================================
XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
XZ Plane: X=(1,0,0), Y=(0,0,1), Z=(0,0,-1)
YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)

=========================================================
输入端参数优先级
=========================================================
- 组件输入端有值：优先用输入端
- 输入端无值：取数据库 AllDict0
- 数据库无值：用默认值（或 None）
"""

from __future__ import print_function, division

import re

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

from yingzao.ancientArchi import DBJsonReader
from yingzao.ancientArchi import GeoAligner_xfm
from yingzao.ancientArchi import FTPlaneFromLists
from yingzao.ancientArchi import GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC


# =========================================================
# 通用工具：flatten_any / 安全运行 solver / 安全取值
# =========================================================

def flatten_any(x):
    """
    递归拍平 list/tuple/NET List，避免 System.Collections.Generic.List 套娃。
    - Rhino.GeometryBase / Plane / Point3d 等作为“原子”不展开。
    """
    out = []
    if x is None:
        return out

    # 原子类型（不展开）
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return [x]
    try:
        if isinstance(x, rg.GeometryBase):
            return [x]
    except Exception:
        pass

    if isinstance(x, (list, tuple)):
        for it in x:
            out.extend(flatten_any(it))
        return out

    # .NET IEnumerable
    try:
        it = iter(x)
    except Exception:
        return [x]

    try:
        for v in it:
            out.extend(flatten_any(v))
        return out
    except Exception:
        return [x]


def _safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


# =========================================================
# Step 2：构件类（封装所有构件组件：每个组件一个方法）
# - DBPath：使用主组件输入端 DBPath
# - base_point：统一默认原点
# - 忽略 FailTimbers / Log（不对外暴露）
# - 输出若出现嵌套列表：完全展平
# =========================================================

class SiPU_ChaAng_CornerPU_Components(object):
    class _Dummy(object):
        """极简对象，用于模拟 ghenv / Component / Params。"""
        pass

    def __init__(
            self,
            DBPath=None,
            reference_plane=None,
            Refresh=False,
            ghenv=None
    ):
        self.DBPath = DBPath
        self.base_point = rg.Point3d(0, 0, 0)
        # ✅ 兼容：reference_plane 允许为 None（上层不提供时保持 None）
        #    这样可避免把 Plane.WorldXY 强行当默认值传入，导致部分 solver 签名/内部逻辑异常。
        self.reference_plane = reference_plane
        self.Refresh = bool(Refresh)

        # ✅ 兼容：若外部未提供 ghenv，则构造一个“足够用”的 dummy，避免原 ghpy 组件内部访问报错
        if ghenv is None:
            g = self._Dummy()
            c = self._Dummy()
            p = self._Dummy()
            # 常见字段
            c.Name = "SiPU_ChaAng_CornerPU_Components"
            c.NickName = "SiPU_ChaAng_CornerPU_Components"
            c.Description = ""
            c.Message = ""
            c.Category = "YingZaoLab"
            c.SubCategory = ""
            c.AdditionalHelpFromDocStrings = "1"
            c.Params = p
            g.Component = c
            self.ghenv = g
        else:
            self.ghenv = ghenv

    def _run_solver(self, SolverCls):
        """
        兼容不同 solver 的构造签名：
        - (DBPath, base_point, reference_plane, Refresh, ghenv)
        - (DBPath, base_point, reference_plane, Refresh)
        - (DBPath, base_point, reference_plane)
        - (DBPath, base_point, Refresh, ghenv)
        - (DBPath, base_point, Refresh)
        - (DBPath, base_point)
        - named args 版本
        """
        _rf = bool(self.Refresh)
        s = None

        # 1) named args（最全）+ ghenv
        try:
            s = SolverCls(
                DBPath=self.DBPath,
                base_point=self.base_point,
                reference_plane=self.reference_plane,
                Refresh=_rf,
                ghenv=self.ghenv
            )
        except Exception:
            pass

        # 2) positional（最全）+ ghenv
        if s is None:
            try:
                s = SolverCls(self.DBPath, self.base_point, self.reference_plane, _rf, self.ghenv)
            except Exception:
                pass

        # 3) named args（无 ghenv）
        if s is None:
            try:
                s = SolverCls(
                    DBPath=self.DBPath,
                    base_point=self.base_point,
                    reference_plane=self.reference_plane,
                    Refresh=_rf
                )
            except Exception:
                pass

        # 4) positional（无 ghenv）
        if s is None:
            try:
                s = SolverCls(self.DBPath, self.base_point, self.reference_plane, _rf)
            except Exception:
                pass

        # 5) named args（仅 reference_plane）
        if s is None:
            try:
                s = SolverCls(DBPath=self.DBPath, base_point=self.base_point, reference_plane=self.reference_plane)
            except Exception:
                pass

        # 6) positional（仅 reference_plane）
        if s is None:
            try:
                s = SolverCls(self.DBPath, self.base_point, self.reference_plane)
            except Exception:
                pass

        # 7) named args + ghenv（旧签名：无 reference_plane）
        if s is None:
            try:
                s = SolverCls(DBPath=self.DBPath, base_point=self.base_point, Refresh=_rf, ghenv=self.ghenv)
            except Exception:
                pass

        # 8) positional + ghenv（旧签名：无 reference_plane）
        if s is None:
            try:
                s = SolverCls(self.DBPath, self.base_point, _rf, self.ghenv)
            except Exception:
                pass

        # 9) named args（无 ghenv）（旧签名：无 reference_plane）
        if s is None:
            try:
                s = SolverCls(DBPath=self.DBPath, base_point=self.base_point, Refresh=_rf)
            except Exception:
                pass

        # 10) positional（无 ghenv）（旧签名：无 reference_plane）
        if s is None:
            try:
                s = SolverCls(self.DBPath, self.base_point, _rf)
            except Exception:
                pass

        # 11) 最简
        if s is None:
            s = SolverCls(self.DBPath, self.base_point)

        # run / run()
        try:
            if hasattr(s, "run"):
                out = s.run()
                # 兼容：
                # - 有的 run 返回 None（结果存到成员变量）
                # - 有的 run 返回 self
                # - 有的 run 返回 (CutTimbers, FailTimbers, Log) 这样的 tuple
                if out is None:
                    return s

                # tuple/list：把前三项（若存在）回写到 solver 成员上，保证后续 _pack 可取到
                if isinstance(out, (list, tuple)):
                    try:
                        if len(out) > 0:
                            s.CutTimbers = out[0]
                        if len(out) > 1:
                            s.FailTimbers = out[1]
                        if len(out) > 2:
                            s.Log = out[2]
                    except Exception:
                        pass
                    return s

                # dict：也回写常用键
                if isinstance(out, dict):
                    try:
                        if "CutTimbers" in out:
                            s.CutTimbers = out.get("CutTimbers")
                        if "FailTimbers" in out:
                            s.FailTimbers = out.get("FailTimbers")
                        if "Log" in out:
                            s.Log = out.get("Log")
                    except Exception:
                        pass
                    return s

                # 其它：若返回的对象本身像 solver（有属性），就直接用它，否则仍返回 s
                return out if hasattr(out, "__dict__") else s
        except Exception:
            pass

        try:
            if hasattr(s, "Run"):
                out = s.Run()
                if out is None:
                    return s
                if isinstance(out, (list, tuple)):
                    try:
                        if len(out) > 0:
                            s.CutTimbers = out[0]
                        if len(out) > 1:
                            s.FailTimbers = out[1]
                        if len(out) > 2:
                            s.Log = out[2]
                    except Exception:
                        pass
                    return s
                if isinstance(out, dict):
                    try:
                        if "CutTimbers" in out:
                            s.CutTimbers = out.get("CutTimbers")
                        if "FailTimbers" in out:
                            s.FailTimbers = out.get("FailTimbers")
                        if "Log" in out:
                            s.Log = out.get("Log")
                    except Exception:
                        pass
                    return s
                return out if hasattr(out, "__dict__") else s
        except Exception:
            pass

        # 兼容：部分 solver 使用 Run() 而非 run()
        try:
            if hasattr(s, "Run"):
                out = s.Run()
                if out is None:
                    return s

                if isinstance(out, (list, tuple)):
                    try:
                        if len(out) > 0:
                            s.CutTimbers = out[0]
                        if len(out) > 1:
                            s.FailTimbers = out[1]
                        if len(out) > 2:
                            s.Log = out[2]
                    except Exception:
                        pass
                    return s

                if isinstance(out, dict):
                    try:
                        if "CutTimbers" in out:
                            s.CutTimbers = out.get("CutTimbers")
                        if "FailTimbers" in out:
                            s.FailTimbers = out.get("FailTimbers")
                        if "Log" in out:
                            s.Log = out.get("Log")
                    except Exception:
                        pass
                    return s

                return out if hasattr(out, "__dict__") else s
        except Exception:
            pass

        return s

    def _pack(self, solver, out_names):
        """
        返回 dict：{out_name: value}
        若 value 为 list/嵌套 list：完全展平（保持 Rhino 几何为原子）
        """
        d = {}
        for nm in out_names:
            v = _safe_getattr(solver, nm, None)
            if isinstance(v, (list, tuple)) or (v is not None and hasattr(v, "__iter__") and not isinstance(v, (str,
                                                                                                                rg.GeometryBase,
                                                                                                                rg.Plane,
                                                                                                                rg.Point3d,
                                                                                                                rg.Vector3d,
                                                                                                                rg.Transform))):
                v = flatten_any(v)
            d[nm] = v
        return d

    # --------------------
    # 枓类
    # --------------------
    def ANG_LU_DOU(self):
        from yingzao.ancientArchi import AngLUDouSolver
        s = self._run_solver(AngLUDouSolver)

        return self._pack(s, ["CutTimbers3", "FacePlaneList"])

    def QiAng_DOU(self):
        from yingzao.ancientArchi import QiAngDouSolver
        s = self._run_solver(QiAngDouSolver)
        return self._pack(s, ["CutTimbers", "FacePlaneList"])

    def SAN_DOU(self):
        from yingzao.ancientArchi import SanDouSolver
        s = self._run_solver(SanDouSolver)
        return self._pack(s, ["CutTimbers", "FacePlaneList"])

    def PingPanDou(self):
        from yingzao.ancientArchi import PingPanDouSolver
        s = self._run_solver(PingPanDouSolver)
        return self._pack(s, ["CutTimbers", "FacePlaneList"])

    def JIAOHU_DOU(self):
        from yingzao.ancientArchi import JIAOHU_DOU_doukoutiaoSolver
        s = self._run_solver(JIAOHU_DOU_doukoutiaoSolver)
        return self._pack(s, ["CutTimbers", "FacePlaneList"])

    # --------------------
    # 栱类
    # --------------------
    def ChaAngInLineWNiDaoGong2(self):
        from yingzao.ancientArchi import ChaAngInLineWNiDaoGong2Solver
        s = self._run_solver(ChaAngInLineWNiDaoGong2Solver)
        # ✅ 兼容（来自 Components.md）：
        # 组件脚本在 solver.run() 之后会执行：
        #   CutTimbers.extend(CutTimbersByTools_V3_1__CutTimbers)
        try:
            ct = list(flatten_any(_safe_getattr(s, "CutTimbers", None)))
            extra = flatten_any(_safe_getattr(s, "CutTimbersByTools_V3_1__CutTimbers", None))
            if extra:
                ct.extend(extra)
            s.CutTimbers = ct
        except Exception:
            pass
        return self._pack(s, ["CutTimbers", "FacePlaneList", "EdgeMidPoints", "Corner0Planes"])

    def ChaAngInLineWNiDaoGong1(self):
        from yingzao.ancientArchi import ChaAngInLineWNiDaoGongSolver
        s = self._run_solver(ChaAngInLineWNiDaoGongSolver)
        # ✅ 兼容（来自 Components.md）：
        # 组件脚本在 solver.run() 之后会执行：
        #   CutTimbers.extend(CutTimbersByTools_V3_1__CutTimbers)
        try:
            ct = list(flatten_any(_safe_getattr(s, "CutTimbers", None)))
            extra = flatten_any(_safe_getattr(s, "CutTimbersByTools_V3_1__CutTimbers", None))
            if extra:
                ct.extend(extra)
            s.CutTimbers = ct
        except Exception:
            pass
        return self._pack(s, ["CutTimbers", "FacePlaneList", "EdgeMidPoints", "Corner0Planes"])

    def JiaoAngInLineWJiaoHuaGong(self):
        from yingzao.ancientArchi import JiaoAngInLineWJiaoHuaGongSolver
        s = self._run_solver(JiaoAngInLineWJiaoHuaGongSolver)
        s.solve()
        # ✅ 兼容（来自 Components.md）：
        # GH 组件脚本在 solver.solve()/run() 之后，会把最终 CutTimbers 指定为：
        #   CutTimbers = [CutTimbersByTools_1_CutTimbers[0], CutTimbersByTools_4_CutTimbers[0]]
        # 这里按相同逻辑重构 CutTimbers，确保与 GH 输出一致。
        try:
            ct_list = []

            ct1 = _safe_getattr(s, "CutTimbersByTools_1__CutTimbers", None)
            ct4 = _safe_getattr(s, "CutTimbersByTools_4__CutTimbers", None)

            ct1_0 = None
            if ct1 is not None:
                if isinstance(ct1, (list, tuple)):
                    if len(ct1) > 0:
                        ct1_0 = ct1[0]
                else:
                    # 非列表则直接视为单对象
                    ct1_0 = ct1

            ct4_0 = None
            if ct4 is not None:
                if isinstance(ct4, (list, tuple)):
                    if len(ct4) > 0:
                        ct4_0 = ct4[0]
                else:
                    ct4_0 = ct4

            if ct1_0 is not None:
                ct_list.append(ct1_0)
            if ct4_0 is not None:
                ct_list.append(ct4_0)

            # 覆盖写回，供 _pack 读取
            s.CutTimbers = ct_list
        except Exception:
            pass
        return self._pack(s, ["CutTimbers", "FacePlaneList", "EdgeMidPoints", "Corner0Planes"])

    def LingGongInLineWXiaoGongTou1(self):
        from yingzao.ancientArchi import LingGongInLineWXiaoGongTou_4PU_Solver
        s = self._run_solver(LingGongInLineWXiaoGongTou_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "SkewTimber_EdgeMidPoints", "SkewTimber_Corner0Planes"])

    def LingGongInLineWXiaoGongTou2(self):
        from yingzao.ancientArchi import LingGongInLineWXiaoGongTou2_4PU_Solver
        s = self._run_solver(LingGongInLineWXiaoGongTou2_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "SkewTimber_EdgeMidPoints", "SkewTimber_Corner0Planes"])

    def ShuaTouInLineWManGong1(self):
        from yingzao.ancientArchi import ShuaTouInLineWManGong1_4PU_Solver
        s = self._run_solver(ShuaTouInLineWManGong1_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "Skew_Point_C", "EdgeMidPoints", "Corner0Planes"])

    def ShuaTouInLineWManGong2(self):
        from yingzao.ancientArchi import ShuaTouInLineWManGong2_4PU_Solver
        s = self._run_solver(ShuaTouInLineWManGong2_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "Skew_Point_C", "EdgeMidPoints", "Corner0Planes"])

    def GuaZiGongInLineWLingGong1(self):
        from yingzao.ancientArchi import GuaZiGongInLineWLingGong1_4PU_Solver
        s = self._run_solver(GuaZiGongInLineWLingGong1_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "EdgeMidPoints", "Corner0Planes"])

    def GuaZiGongInLineWLingGong2(self):
        from yingzao.ancientArchi import GuaZiGongInLineWLingGong2_4PU_Solver
        s = self._run_solver(GuaZiGongInLineWLingGong2_4PU_Solver)
        return self._pack(s, ["CutTimbers", "Skew_Planes", "EdgeMidPoints", "Corner0Planes"])

    def YouAngInLineWJiaoShuaTou(self):
        from yingzao.ancientArchi import YouAngInLineWJiaoShuaTou_4PU_Solver
        s = self._run_solver(YouAngInLineWJiaoShuaTou_4PU_Solver)

        # ✅ 兼容（来自 Components.md）：
        # GH 组件脚本在 solver.run() 之后，会把两个对象安全追加到 CutTimbers：
        #   SplitSectionAnalyzer__MaxClosedBrep
        #   AlignToolToTimber_11__MovedGeo[0] / AlignToolToTimber_11__MovedGeo
        try:
            CutTimbers = list(flatten_any(_safe_getattr(s, "CutTimbers", None)))

            SplitSectionAnalyzer__MaxClosedBrep = _safe_getattr(s, "SplitSectionAnalyzer__MaxClosedBrep", None)
            AlignToolToTimber_11__MovedGeo = _safe_getattr(s, "AlignToolToTimber_11__MovedGeo", None)

            moved_geo_11 = None
            if AlignToolToTimber_11__MovedGeo is not None:
                if isinstance(AlignToolToTimber_11__MovedGeo, (list, tuple)):
                    if len(AlignToolToTimber_11__MovedGeo) > 0:
                        moved_geo_11 = AlignToolToTimber_11__MovedGeo[0]
                else:
                    moved_geo_11 = AlignToolToTimber_11__MovedGeo

            if SplitSectionAnalyzer__MaxClosedBrep is not None:
                CutTimbers.append(SplitSectionAnalyzer__MaxClosedBrep)
            if moved_geo_11 is not None:
                CutTimbers.append(moved_geo_11)

            s.CutTimbers = CutTimbers
        except Exception:
            pass

        return self._pack(s,
                          ["CutTimbers", "TimberBlock_SkewAxis_M__Skew_Point_C", "TimberBlock_SkewAxis_M__Skew_Planes",
                           "YouAng__Ang_PtsValues", "AlignToolToTimber_9__TransformOut", "Corner0Planes"])

    # --------------------
    # 襯補类
    # --------------------
    def Vase(self):
        from yingzao.ancientArchi import VaseA_Solver_4PU
        s = self._run_solver(VaseA_Solver_4PU)
        return self._pack(s, ["CutTimbers", "base_ref_plane"])

    def OctagonPrism(self):
        from yingzao.ancientArchi import OctagonPrismBuilder

        s = OctagonPrismBuilder(
            edge_len=10,
            chamfer_len=7.07,
            height=41,
            tol=1e-6
        )

        PrismBrep, SectionCrv, RefPlane_BP, Log = s.solve()
        s.PrismBrep = PrismBrep
        s.RefPlane_BP = RefPlane_BP

        return self._pack(s, ["PrismBrep", "RefPlane_BP"])


# =========================================================
# 通用工具函数（参考 ChongGongComponentAssemblySolver 结构）
# =========================================================

def _default_place_plane():
    """默认放置平面：GH 的 XY Plane，原点为 (100,100,0)"""
    pl = rg.Plane.WorldXY
    pl.Origin = rg.Point3d(100.0, 100.0, 0.0)
    return pl


def _ensure_list(x):
    """把 None/单值/tuple/list 统一成 list（不做深度拍平）。"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    return [x]


def _is_listlike(x):
    """GH 广播用：判断是否为可迭代序列（list/tuple）。"""
    return isinstance(x, (list, tuple))


def _broadcast_cycle(*args):
    """GH 风格广播对齐（短列表循环）。
    返回 (n, getter)，其中 n 为广播长度，getter(arg, i) 获取第 i 项（短列表循环 / 标量重复）。
    """
    lens = [len(a) for a in args if _is_listlike(a)]
    n = max(lens) if lens else 1

    def _get(a, i):
        if _is_listlike(a):
            if len(a) == 0:
                return None
            return a[i % len(a)]
        return a

    return n, _get


def _flatten_items(x, out_list):
    """递归拍平 list/tuple（用于输出端避免嵌套 List`1[Object] 的表现）。"""
    if x is None:
        return
    if isinstance(x, (list, tuple)):
        for it in x:
            _flatten_items(it, out_list)
    else:
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


def _coerce_plane(pl, default=None):
    """
    尽可能把 GH 输入端传入的 Plane / GH_Plane / string("WorldXY"/"XY"/"XZ"/"YZ") 转为 rg.Plane
    """
    if pl is None:
        return default

    # RhinoCommon Plane
    if isinstance(pl, rg.Plane):
        return pl

    # GH Plane wrapper
    try:
        if isinstance(pl, ght.GH_Plane):
            return pl.Value
    except:
        pass

    # 常见字符串
    if isinstance(pl, str):
        s = pl.strip().lower()
        if s in ("worldxy", "xy", "plane.xy", "plane_worldxy"):
            return None
        if s in ("worldxz", "xz", "plane.xz", "plane_worldxz"):
            return rg.Plane.WorldXZ
        if s in ("worldyz", "yz", "plane.yz", "plane_worldyz"):
            return rg.Plane.WorldYZ

    return default


def _all_to_dict(all_list):
    """
    All: [('Key', value), ...] -> dict
    注意：Key 统一转 str；若遇到异常则跳过
    """
    d = {}
    for kv in _ensure_list(all_list):
        try:
            k, v = kv
            d[str(k)] = v
        except:
            continue
    return d


# =========================================================
# Solver 主类（逐步实现 Step1/Step2/...）
# =========================================================

class SiPU_ChaAng_CornerPU_ComponentAssemblySolver(object):

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, EnableChenBu=None, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane
        self.Refresh = bool(Refresh)
        self.EnableChenBu = _as_bool(EnableChenBu, default=True)
        self.ghenv = ghenv

        self.LogLines = []
        self.Log = ""
        self.ComponentAssembly = []

        # -----------------------
        # Step 1：DBJsonReader 输出（必须保留）
        # -----------------------
        self.Value0 = None
        self.All0 = None
        self.AllDict0 = {}
        self.DBLog0 = None

        # -----------------------
        # Step 2：构件类对外输出（初始化占位，避免属性缺失）
        # -----------------------
        self.ANG_LU_DOU__CutTimbers = None
        self.ANG_LU_DOU__FacePlaneList = None
        self.QiAng_DOU__CutTimbers = None
        self.QiAng_DOU__FacePlaneList = None
        self.SAN_DOU__CutTimbers = None
        self.SAN_DOU__FacePlaneList = None
        self.PingPanDou__CutTimbers = None
        self.PingPanDou__FacePlaneList = None
        self.JIAOHU_DOU__CutTimbers = None
        self.JIAOHU_DOU__FacePlaneList = None
        self.ChaAngInLineWNiDaoGong2__CutTimbers = None
        self.ChaAngInLineWNiDaoGong2__FacePlaneList = None
        self.ChaAngInLineWNiDaoGong2__EdgeMidPoints = None
        self.ChaAngInLineWNiDaoGong2__Corner0Planes = None
        self.ChaAngInLineWNiDaoGong1__CutTimbers = None
        self.ChaAngInLineWNiDaoGong1__FacePlaneList = None
        self.ChaAngInLineWNiDaoGong1__EdgeMidPoints = None
        self.ChaAngInLineWNiDaoGong1__Corner0Planes = None
        self.JiaoAngInLineWJiaoHuaGong__CutTimbers = None
        self.JiaoAngInLineWJiaoHuaGong__FacePlaneList = None
        self.JiaoAngInLineWJiaoHuaGong__EdgeMidPoints = None
        self.JiaoAngInLineWJiaoHuaGong__Corner0Planes = None
        self.LingGongInLineWXiaoGongTou1__CutTimbers = None
        self.LingGongInLineWXiaoGongTou1__Skew_Planes = None
        self.LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints = None
        self.LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes = None
        self.LingGongInLineWXiaoGongTou2__CutTimbers = None
        self.LingGongInLineWXiaoGongTou2__Skew_Planes = None
        self.LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints = None
        self.LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes = None
        self.ShuaTouInLineWManGong1__CutTimbers = None
        self.ShuaTouInLineWManGong1__Skew_Planes = None
        self.ShuaTouInLineWManGong1__Skew_Point_C = None
        self.ShuaTouInLineWManGong1__EdgeMidPoints = None
        self.ShuaTouInLineWManGong1__Corner0Planes = None
        self.ShuaTouInLineWManGong2__CutTimbers = None
        self.ShuaTouInLineWManGong2__Skew_Planes = None
        self.ShuaTouInLineWManGong2__Skew_Point_C = None
        self.ShuaTouInLineWManGong2__EdgeMidPoints = None
        self.ShuaTouInLineWManGong2__Corner0Planes = None
        self.GuaZiGongInLineWLingGong1__CutTimbers = None
        self.GuaZiGongInLineWLingGong1__Skew_Planes = None
        self.GuaZiGongInLineWLingGong1__EdgeMidPoints = None
        self.GuaZiGongInLineWLingGong1__Corner0Planes = None
        self.GuaZiGongInLineWLingGong2__CutTimbers = None
        self.GuaZiGongInLineWLingGong2__Skew_Planes = None
        self.GuaZiGongInLineWLingGong2__EdgeMidPoints = None
        self.GuaZiGongInLineWLingGong2__Corner0Planes = None
        self.YouAngInLineWJiaoShuaTou__CutTimbers = None
        self.YouAngInLineWJiaoShuaTou__Skew_Point_C = None
        self.YouAngInLineWJiaoShuaTou__Skew_Planes = None
        self.YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues = None
        self.YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut = None
        self.YouAngInLineWJiaoShuaTou__Corner0Planes = None
        self.Vase__CutTimbers = None
        self.Vase__base_ref_plane = None
        self.OctagonPrism__PrismBrep = None
        self.OctagonPrism__RefPlane_BP = None

        # 预留：后续 Step2/Step3/... 的成员变量在对应 step 内赋值并在输出绑定区暴露

        # -------------------------------
        # Step 1：读取数据库（PuZuo / type_code=SiPU_ChaAng_CornerPU / params_json）
        # -------------------------------
        # -----------------------
        # Step 3：vsg1_ga__ANG_LU_DOU（初始化占位）
        # -----------------------
        self.vsg1_ga__ANG_LU_DOU__SourceOut = None
        self.vsg1_ga__ANG_LU_DOU__TargetOut = None
        self.vsg1_ga__ANG_LU_DOU__TransformOut = None
        self.vsg1_ga__ANG_LU_DOU__MovedGeo = None

        # -----------------------
        # Step 4-1：vsg2_ga__ChaAngInLineWNiDaoGong1（初始化占位）
        # -----------------------
        self.vsg2_ga__ChaAngInLineWNiDaoGong1__SourceOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong1__TargetOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong1__MovedGeo = None

        # -----------------------
        # Step 4-2：vsg2_ga__ChaAngInLineWNiDaoGong2（初始化占位）
        # -----------------------
        self.vsg2_ga__ChaAngInLineWNiDaoGong2__SourceOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong2__TargetOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut = None
        self.vsg2_ga__ChaAngInLineWNiDaoGong2__MovedGeo = None

        # -----------------------
        # Step 4-3：vsg2_ga__JiaoAngInLineWJiaoHuaGong（初始化占位）
        # -----------------------
        self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourceOut = None
        self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TargetOut = None
        self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut = None
        self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__MovedGeo = None

        # -----------------------
        # Step 5-1：叠次-3：vsg3_PlaneFromLists1（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists1__BasePlane = None
        self.vsg3_PlaneFromLists1__OriginPoint = None
        self.vsg3_PlaneFromLists1__ResultPlane = None
        self.vsg3_PlaneFromLists1__Log = None

        # -----------------------
        # Step 5-1：叠次-3：vsg3_ga__QiAng_DOU1（初始化占位）
        # -----------------------
        self.vsg3_ga__QiAng_DOU1__SourceOut = None
        self.vsg3_ga__QiAng_DOU1__TargetOut = None
        self.vsg3_ga__QiAng_DOU1__TransformOut = None
        self.vsg3_ga__QiAng_DOU1__MovedGeo = None

        # -----------------------
        # Step 5-2：叠次-3：vsg3_PlaneFromLists2（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists2__BasePlane = None
        self.vsg3_PlaneFromLists2__OriginPoint = None
        self.vsg3_PlaneFromLists2__ResultPlane = None
        self.vsg3_PlaneFromLists2__Log = None

        # -----------------------
        # Step 5-2：叠次-3：vsg3_ga__QiAng_DOU2（初始化占位）
        # -----------------------
        self.vsg3_ga__QiAng_DOU2__SourceOut = None
        self.vsg3_ga__QiAng_DOU2__TargetOut = None
        self.vsg3_ga__QiAng_DOU2__TransformOut = None
        self.vsg3_ga__QiAng_DOU2__MovedGeo = None

        # -----------------------
        # Step 5-3：叠次-3：vsg3_PlaneFromLists3（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists3__BasePlane = None
        self.vsg3_PlaneFromLists3__OriginPoint = None
        self.vsg3_PlaneFromLists3__ResultPlane = None
        self.vsg3_PlaneFromLists3__Log = None

        # -----------------------
        # Step 5-3：叠次-3：vsg3_ga__SAN_DOU1（初始化占位）
        # -----------------------
        self.vsg3_ga__SAN_DOU1__SourceOut = None
        self.vsg3_ga__SAN_DOU1__TargetOut = None
        self.vsg3_ga__SAN_DOU1__TransformOut = None
        self.vsg3_ga__SAN_DOU1__MovedGeo = None

        # -----------------------
        # Step 5-4：叠次-3：vsg3_PlaneFromLists4（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists4__BasePlane = None
        self.vsg3_PlaneFromLists4__OriginPoint = None
        self.vsg3_PlaneFromLists4__ResultPlane = None
        self.vsg3_PlaneFromLists4__Log = None

        # -----------------------
        # Step 5-4：叠次-3：vsg3_ga__SAN_DOU2（初始化占位）
        # -----------------------
        self.vsg3_ga__SAN_DOU2__SourceOut = None
        self.vsg3_ga__SAN_DOU2__TargetOut = None
        self.vsg3_ga__SAN_DOU2__TransformOut = None
        self.vsg3_ga__SAN_DOU2__MovedGeo = None

        # -----------------------
        # Step 5-5：叠次-3：vsg3_PlaneFromLists5（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists5__BasePlane = None
        self.vsg3_PlaneFromLists5__OriginPoint = None
        self.vsg3_PlaneFromLists5__ResultPlane = None
        self.vsg3_PlaneFromLists5__Log = None

        # -----------------------
        # Step 5-5：叠次-3：vsg3_ga__PingPanDou1（初始化占位）
        # -----------------------
        self.vsg3_ga__PingPanDou1__SourceOut = None
        self.vsg3_ga__PingPanDou1__TargetOut = None
        self.vsg3_ga__PingPanDou1__TransformOut = None
        self.vsg3_ga__PingPanDou1__MovedGeo = None

        # -----------------------
        # Step 5-6：叠次-3：vsg3_PlaneFromLists6（初始化占位）
        # -----------------------
        self.vsg3_PlaneFromLists6__BasePlane = None
        self.vsg3_PlaneFromLists6__OriginPoint = None
        self.vsg3_PlaneFromLists6__ResultPlane = None
        self.vsg3_PlaneFromLists6__Log = None

        # -----------------------
        # Step 5-6：叠次-3：vsg3_ga__PingPanDou2（初始化占位）
        # -----------------------
        self.vsg3_ga__PingPanDou2__SourceOut = None
        self.vsg3_ga__PingPanDou2__TargetOut = None
        self.vsg3_ga__PingPanDou2__TransformOut = None
        self.vsg3_ga__PingPanDou2__MovedGeo = None

        # -----------------------
        # Step 6-1：叠次-4：令栱與小栱頭相列一（vsg4_ga__LingGongInLineWXiaoGongTou1）（初始化占位）
        # -----------------------
        self.vsg4_ga__LingGongInLineWXiaoGongTou1__SourceOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou1__TargetOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou1__MovedGeo = None

        # -----------------------
        # Step 6-2：叠次-4：令栱與小栱頭相列二（vsg4_ga__LingGongInLineWXiaoGongTou2）（初始化占位）
        # -----------------------
        self.vsg4_ga__LingGongInLineWXiaoGongTou2__SourceOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou2__TargetOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut = None
        self.vsg4_ga__LingGongInLineWXiaoGongTou2__MovedGeo = None

        # -----------------------
        # Step 6-3：叠次-4：耍頭與慢栱相列一（vsg4_ga__ShuaTouInLineWManGong1）（初始化占位）
        # -----------------------
        self.vsg4_ga__ShuaTouInLineWManGong1__SourceOut = None
        self.vsg4_ga__ShuaTouInLineWManGong1__TargetOut = None
        self.vsg4_ga__ShuaTouInLineWManGong1__TransformOut = None
        self.vsg4_ga__ShuaTouInLineWManGong1__MovedGeo = None

        # -----------------------
        # Step 6-4：叠次-4：耍頭與慢栱相列二（vsg4_ga__ShuaTouInLineWManGong2）（初始化占位）
        # -----------------------
        self.vsg4_ga__ShuaTouInLineWManGong2__SourceOut = None
        self.vsg4_ga__ShuaTouInLineWManGong2__TargetOut = None
        self.vsg4_ga__ShuaTouInLineWManGong2__TransformOut = None
        self.vsg4_ga__ShuaTouInLineWManGong2__MovedGeo = None

        # -----------------------
        # Step 6-5：叠次-4：瓜子栱與令栱相列一（vsg4_ga__GuaZiGongInLineWLingGong1）（初始化占位）
        # -----------------------
        self.vsg4_ga__GuaZiGongInLineWLingGong1__SourceOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong1__TargetOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong1__MovedGeo = None

        # -----------------------
        # Step 6-6：叠次-4：瓜子栱與令栱相列二（vsg4_ga__GuaZiGongInLineWLingGong2）（初始化占位）
        # -----------------------
        self.vsg4_ga__GuaZiGongInLineWLingGong2__SourceOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong2__TargetOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut = None
        self.vsg4_ga__GuaZiGongInLineWLingGong2__MovedGeo = None

        # -----------------------
        # Step 6-7：叠次-4：由昂與角耍頭相列（vsg4_TreeItem_ListItem_PlaneOrigin_Transform1 + vsg4_ga__YouAngInLineWJiaoShuaTou）（初始化占位）
        # -----------------------
        self.vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = None

        self.vsg4_ga__YouAngInLineWJiaoShuaTou__SourceOut = None
        self.vsg4_ga__YouAngInLineWJiaoShuaTou__TargetOut = None
        self.vsg4_ga__YouAngInLineWJiaoShuaTou__TransformOut = None
        self.vsg4_ga__YouAngInLineWJiaoShuaTou__MovedGeo = None

        # -----------------------
        # Step 8-1：叠次-6：寳瓶（vsg6_ga__Vase）（初始化占位）
        # -----------------------
        self.vsg6_ga__Vase__SourceOut = None
        self.vsg6_ga__Vase__TargetOut = None
        self.vsg6_ga__Vase__MovedGeo = None

        # TargetPlane Transform 中间结果（便于调试）
        self.vsg6_ga__Vase__TargetPlane_Transform = None

    def step1_read_db(self):
        self.LogLines.append("Step 1：读取数据库 params_json -> All / AllDict0 ...")

        reader = DBJsonReader(
            db_path=self.DBPath,
            table="PuZuo",
            key_field="type_code",
            key_value="SiPU_ChaAng_CornerPU",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )

        self.Value0, self.All0, self.DBLog0 = reader.run()
        self.AllDict0 = _all_to_dict(self.All0)

        self.LogLines.append("Step 1 完成：All items={} / AllDict0 keys={}".format(
            len(_ensure_list(self.All0)), len(self.AllDict0.keys())
        ))

    # -------------------------------
    # Step N：后续逐步加入（占位）
    # -------------------------------
    def step2_build_components(self):
        """
        Step 2：构件类（按 Components.md）
        - 将各个构件组件封装为一个大类（SiPU_ChaAng_CornerPU_Components）
        - 逐个运行并把“对外输出端参数”写入本 Solver 成员变量（组件名前缀）
        - 忽略 FailTimbers / Log
        - 若输出出现嵌套 list：完全展平
        """
        try:
            # ✅ 兼容模式：构件类初始化参数全部使用默认值（base_point/reference_plane/Refresh/ghenv）
            # 仅传 DBPath，避免原 ghpy 组件 __init__ 缺参
            comp_lib = SiPU_ChaAng_CornerPU_Components(DBPath=self.DBPath)

            # 枓类
            d = comp_lib.ANG_LU_DOU()
            self.ANG_LU_DOU__CutTimbers = d.get("CutTimbers3")
            self.ANG_LU_DOU__FacePlaneList = d.get("FacePlaneList")

            d = comp_lib.QiAng_DOU()
            self.QiAng_DOU__CutTimbers = d.get("CutTimbers")
            self.QiAng_DOU__FacePlaneList = d.get("FacePlaneList")

            d = comp_lib.SAN_DOU()
            self.SAN_DOU__CutTimbers = d.get("CutTimbers")
            self.SAN_DOU__FacePlaneList = d.get("FacePlaneList")

            d = comp_lib.PingPanDou()
            self.PingPanDou__CutTimbers = d.get("CutTimbers")
            self.PingPanDou__FacePlaneList = d.get("FacePlaneList")

            d = comp_lib.JIAOHU_DOU()
            self.JIAOHU_DOU__CutTimbers = d.get("CutTimbers")
            self.JIAOHU_DOU__FacePlaneList = d.get("FacePlaneList")

            # 栱类
            d = comp_lib.ChaAngInLineWNiDaoGong2()
            self.ChaAngInLineWNiDaoGong2__CutTimbers = d.get("CutTimbers")
            self.ChaAngInLineWNiDaoGong2__FacePlaneList = d.get("FacePlaneList")
            self.ChaAngInLineWNiDaoGong2__EdgeMidPoints = d.get("EdgeMidPoints")
            self.ChaAngInLineWNiDaoGong2__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.ChaAngInLineWNiDaoGong1()
            self.ChaAngInLineWNiDaoGong1__CutTimbers = d.get("CutTimbers")
            self.ChaAngInLineWNiDaoGong1__FacePlaneList = d.get("FacePlaneList")
            self.ChaAngInLineWNiDaoGong1__EdgeMidPoints = d.get("EdgeMidPoints")
            self.ChaAngInLineWNiDaoGong1__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.JiaoAngInLineWJiaoHuaGong()
            self.JiaoAngInLineWJiaoHuaGong__CutTimbers = d.get("CutTimbers")
            self.JiaoAngInLineWJiaoHuaGong__FacePlaneList = d.get("FacePlaneList")
            self.JiaoAngInLineWJiaoHuaGong__EdgeMidPoints = d.get("EdgeMidPoints")
            self.JiaoAngInLineWJiaoHuaGong__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.LingGongInLineWXiaoGongTou1()
            self.LingGongInLineWXiaoGongTou1__CutTimbers = d.get("CutTimbers")
            self.LingGongInLineWXiaoGongTou1__Skew_Planes = d.get("Skew_Planes")
            self.LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints = d.get("SkewTimber_EdgeMidPoints")
            self.LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes = d.get("SkewTimber_Corner0Planes")

            d = comp_lib.LingGongInLineWXiaoGongTou2()
            self.LingGongInLineWXiaoGongTou2__CutTimbers = d.get("CutTimbers")
            self.LingGongInLineWXiaoGongTou2__Skew_Planes = d.get("Skew_Planes")
            self.LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints = d.get("SkewTimber_EdgeMidPoints")
            self.LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes = d.get("SkewTimber_Corner0Planes")

            d = comp_lib.ShuaTouInLineWManGong1()
            self.ShuaTouInLineWManGong1__CutTimbers = d.get("CutTimbers")
            self.ShuaTouInLineWManGong1__Skew_Planes = d.get("Skew_Planes")
            self.ShuaTouInLineWManGong1__Skew_Point_C = d.get("Skew_Point_C")
            self.ShuaTouInLineWManGong1__EdgeMidPoints = d.get("EdgeMidPoints")
            self.ShuaTouInLineWManGong1__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.ShuaTouInLineWManGong2()
            self.ShuaTouInLineWManGong2__CutTimbers = d.get("CutTimbers")
            self.ShuaTouInLineWManGong2__Skew_Planes = d.get("Skew_Planes")
            self.ShuaTouInLineWManGong2__Skew_Point_C = d.get("Skew_Point_C")
            self.ShuaTouInLineWManGong2__EdgeMidPoints = d.get("EdgeMidPoints")
            self.ShuaTouInLineWManGong2__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.GuaZiGongInLineWLingGong1()
            self.GuaZiGongInLineWLingGong1__CutTimbers = d.get("CutTimbers")
            self.GuaZiGongInLineWLingGong1__Skew_Planes = d.get("Skew_Planes")
            self.GuaZiGongInLineWLingGong1__EdgeMidPoints = d.get("EdgeMidPoints")
            self.GuaZiGongInLineWLingGong1__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.GuaZiGongInLineWLingGong2()
            self.GuaZiGongInLineWLingGong2__CutTimbers = d.get("CutTimbers")
            self.GuaZiGongInLineWLingGong2__Skew_Planes = d.get("Skew_Planes")
            self.GuaZiGongInLineWLingGong2__EdgeMidPoints = d.get("EdgeMidPoints")
            self.GuaZiGongInLineWLingGong2__Corner0Planes = d.get("Corner0Planes")

            d = comp_lib.YouAngInLineWJiaoShuaTou()
            self.YouAngInLineWJiaoShuaTou__CutTimbers = d.get("CutTimbers")
            self.YouAngInLineWJiaoShuaTou__Skew_Point_C = d.get("TimberBlock_SkewAxis_M__Skew_Point_C")
            self.YouAngInLineWJiaoShuaTou__Skew_Planes = d.get("TimberBlock_SkewAxis_M__Skew_Planes")
            self.YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues = d.get("YouAng__Ang_PtsValues")
            self.YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut = d.get(
                "AlignToolToTimber_9__TransformOut")
            self.YouAngInLineWJiaoShuaTou__Corner0Planes = d.get("Corner0Planes")

            # 襯補类
            d = comp_lib.Vase()
            self.Vase__CutTimbers = d.get("CutTimbers")
            self.Vase__base_ref_plane = d.get("base_ref_plane")

            d = comp_lib.OctagonPrism()
            print("@@@@@", d)
            self.OctagonPrism__PrismBrep = d.get("PrismBrep")
            self.OctagonPrism__RefPlane_BP = d.get("RefPlane_BP")

            self.LogLines.append("Step 2：构件类（Components）已运行完成")
        except Exception as e:
            self.LogLines.append("Step 2：构件类（Components）运行失败：{}".format(e))

    def step3_vsg1_ga__ANG_LU_DOU(self):
        """
        Step 3: 叠次-1：角櫨枓（vsg1_ga__ANG_LU_DOU）
        - Geo        = ANG_LU_DOU__CutTimbers
        - SourcePlane= ANG_LU_DOU__FacePlaneList[ vsg1_ga__ANG_LU_DOU__SourcePlane ]
        - FlipZ      = AllDict0['vsg1_ga__ANG_LU_DOU__FlipZ']
        - TargetPlane= PlacePlane（本 Solver 的放置参考平面）
        其余 Rotate/FlipX/FlipY/MoveX/MoveY/MoveZ 按原组件默认值（0/False/0）。
        输出写入：
        - self.vsg1_ga__ANG_LU_DOU__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.ANG_LU_DOU__CutTimbers
            face_planes = _ensure_list(self.ANG_LU_DOU__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg1_ga__ANG_LU_DOU__SourcePlane", 0)
            flip_z = self.AllDict0.get("vsg1_ga__ANG_LU_DOU__FlipZ", False)

            # SourcePlane 取值（兼容 idx 为 list/tuple/单值）
            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
                # 若取出的列表仍嵌套，保持为 list（Plane 为原子，不拍平）
            else:
                SourcePlane = _pick_plane(sp_idx)

            TargetPlane = _coerce_plane(self.PlacePlane, None)
            if TargetPlane is None:
                TargetPlane = _default_place_plane()

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=0,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=0,
                move_y=0,
                move_z=0,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg1_ga__ANG_LU_DOU__SourceOut = SourceOut
            self.vsg1_ga__ANG_LU_DOU__TargetOut = TargetOut
            self.vsg1_ga__ANG_LU_DOU__TransformOut = TransformOut

            # 输出端若出现嵌套列表：完全展平（Geo 类型作为原子）
            self.vsg1_ga__ANG_LU_DOU__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 3 完成：vsg1_ga__ANG_LU_DOU")
        except Exception as e:
            self.LogLines.append("Step 3 失败：vsg1_ga__ANG_LU_DOU -> {}".format(e))

    def step4_1_vsg2_ga__ChaAngInLineWNiDaoGong1(self):
        """
        Step 4-1: 叠次-2：插昂與泥道栱相列一（vsg2_ga__ChaAngInLineWNiDaoGong1）

        组件输入端（按你提供的说明严格复刻）：
        - Geo        = ChaAngInLineWNiDaoGong1__CutTimbers
        - SourcePlane= vsg2_ga__ChaAngInLineWNiDaoGong1__SourcePlane（索引 ChaAngInLineWNiDaoGong1__FacePlaneList）
        - TargetPlane= Transform( Geometry = vsg1_ga__ANG_LU_DOU 的 SourcePlane, Transform = vsg1_ga__ANG_LU_DOU 的 TransformOut )
        - MoveZ      = vsg2_ga__ChaAngInLineWNiDaoGong2__MoveZ
        其余 RotateDeg/FlipX/FlipY/FlipZ/MoveX/MoveY 按原组件默认值（0/False/0）。
        """
        try:
            geo = self.ChaAngInLineWNiDaoGong1__CutTimbers
            face_planes = _ensure_list(self.ChaAngInLineWNiDaoGong1__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong1__SourcePlane", 0)
            move_z = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong2__MoveZ", 0)

            # SourcePlane 取值（兼容 idx 为 list/tuple/单值）
            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( ANG_LU_DOU_SourcePlane , ANG_LU_DOU_TransformOut )
            # ----------------------------
            ang_face_planes = _ensure_list(self.ANG_LU_DOU__FacePlaneList)
            ang_sp_idx = self.AllDict0.get("vsg1_ga__ANG_LU_DOU__SourcePlane", 0)

            if isinstance(ang_sp_idx, (list, tuple)):
                # Transform 输入几何需要与 step3 的 SourcePlane 一致：若是 list，取首个可用 Plane
                _base_geo = None
                for i in ang_sp_idx:
                    _base_geo = _pick_plane_from_list(ang_face_planes, i)
                    if _base_geo is not None:
                        break
                base_plane = _base_geo
            else:
                base_plane = _pick_plane_from_list(ang_face_planes, ang_sp_idx)

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg1_ga__ANG_LU_DOU__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = None
            if base_plane is not None:
                try:
                    TargetPlane = rg.Plane(base_plane)
                    TargetPlane.Transform(xfm)
                except Exception:
                    TargetPlane = base_plane

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=0,
                flip_x=False,
                flip_y=False,
                flip_z=False,
                move_x=0,
                move_y=0,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg2_ga__ChaAngInLineWNiDaoGong1__SourceOut = SourceOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong1__TargetOut = TargetOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut = TransformOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 4-1 完成：vsg2_ga__ChaAngInLineWNiDaoGong1")
        except Exception as e:
            self.LogLines.append("Step 4-1 失败：vsg2_ga__ChaAngInLineWNiDaoGong1 -> {}".format(e))

    def step4_2_vsg2_ga__ChaAngInLineWNiDaoGong2(self):
        """
        Step 4-2: 叠次-2：插昂與泥道栱相列二（vsg2_ga__ChaAngInLineWNiDaoGong2）

        组件输入端（按你提供的说明严格复刻）：
        - Geo        = ChaAngInLineWNiDaoGong2__CutTimbers
        - SourcePlane= vsg2_ga__ChaAngInLineWNiDaoGong2__SourcePlane（索引 ChaAngInLineWNiDaoGong2__FacePlaneList）
        - TargetPlane= Transform( Geometry = vsg1_ga__ANG_LU_DOU 的 SourcePlane, Transform = vsg1_ga__ANG_LU_DOU 的 TransformOut )
        - RotateDeg  = vsg2_ga__ChaAngInLineWNiDaoGong2__RotateDegv（若库中为 RotateDeg，则自动兼容）
        - MoveZ      = vsg2_ga__ChaAngInLineWNiDaoGong2__MoveZ
        其余 FlipX/FlipY/FlipZ/MoveX/MoveY 按原组件默认值（False/0）。
        """
        try:
            geo = self.ChaAngInLineWNiDaoGong2__CutTimbers
            face_planes = _ensure_list(self.ChaAngInLineWNiDaoGong2__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong2__SourcePlane", 0)

            # RotateDeg：兼容可能的字段名（RotateDegv / RotateDeg）
            rotate_deg = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong2__RotateDegv", None)
            if rotate_deg is None:
                rotate_deg = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong2__RotateDeg", 0)

            move_z = self.AllDict0.get("vsg2_ga__ChaAngInLineWNiDaoGong2__MoveZ", 0)

            # SourcePlane 取值（兼容 idx 为 list/tuple/单值）
            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( ANG_LU_DOU_SourcePlane , ANG_LU_DOU_TransformOut )
            # ----------------------------
            ang_face_planes = _ensure_list(self.ANG_LU_DOU__FacePlaneList)
            ang_sp_idx = self.AllDict0.get("vsg1_ga__ANG_LU_DOU__SourcePlane", 0)

            if isinstance(ang_sp_idx, (list, tuple)):
                _base_geo = None
                for i in ang_sp_idx:
                    _base_geo = _pick_plane_from_list(ang_face_planes, i)
                    if _base_geo is not None:
                        break
                base_plane = _base_geo
            else:
                base_plane = _pick_plane_from_list(ang_face_planes, ang_sp_idx)

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg1_ga__ANG_LU_DOU__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = None
            if base_plane is not None:
                try:
                    TargetPlane = rg.Plane(base_plane)
                    TargetPlane.Transform(xfm)
                except Exception:
                    TargetPlane = base_plane

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=False,
                move_x=0,
                move_y=0,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg2_ga__ChaAngInLineWNiDaoGong2__SourceOut = SourceOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong2__TargetOut = TargetOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut = TransformOut
            self.vsg2_ga__ChaAngInLineWNiDaoGong2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 4-2 完成：vsg2_ga__ChaAngInLineWNiDaoGong2")
        except Exception as e:
            self.LogLines.append("Step 4-2 失败：vsg2_ga__ChaAngInLineWNiDaoGong2 -> {}".format(e))

    def step4_3_vsg2_ga__JiaoAngInLineWJiaoHuaGong(self):
        """
        Step 4-3: 叠次-2：插昂與泥道栱相列二角昂與角華栱相列（vsg2_ga__JiaoAngInLineWJiaoHuaGong）

        组件输入端（按你提供的说明严格复刻）：
        - Geo        = JiaoAngInLineWJiaoHuaGong__CutTimbers
        - SourcePlane= vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourcePlane（索引 JiaoAngInLineWJiaoHuaGong__FacePlaneList）
        - TargetPlane= Transform( Geometry = vsg1_ga__ANG_LU_DOU 的 SourcePlane, Transform = vsg1_ga__ANG_LU_DOU 的 TransformOut )
        - RotateDeg  = vsg2_ga__JiaoAngInLineWJiaoHuaGong__RotateDeg
        - MoveZ      = vsg2_ga__JiaoAngInLineWJiaoHuaGong__MoveZ
        其余 FlipX/FlipY/FlipZ/MoveX/MoveY 按原组件默认值（False/0）。
        """
        try:
            geo = self.JiaoAngInLineWJiaoHuaGong__CutTimbers
            face_planes = _ensure_list(self.JiaoAngInLineWJiaoHuaGong__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg2_ga__JiaoAngInLineWJiaoHuaGong__RotateDeg", 0)
            move_z = self.AllDict0.get("vsg2_ga__JiaoAngInLineWJiaoHuaGong__MoveZ", 0)

            # SourcePlane 取值（兼容 idx 为 list/tuple/单值）
            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( ANG_LU_DOU_SourcePlane , ANG_LU_DOU_TransformOut )
            # ----------------------------
            ang_face_planes = _ensure_list(self.ANG_LU_DOU__FacePlaneList)
            ang_sp_idx = self.AllDict0.get("vsg1_ga__ANG_LU_DOU__SourcePlane", 0)

            if isinstance(ang_sp_idx, (list, tuple)):
                _base_geo = None
                for i in ang_sp_idx:
                    _base_geo = _pick_plane_from_list(ang_face_planes, i)
                    if _base_geo is not None:
                        break
                base_plane = _base_geo
            else:
                base_plane = _pick_plane_from_list(ang_face_planes, ang_sp_idx)

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg1_ga__ANG_LU_DOU__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = None
            if base_plane is not None:
                try:
                    TargetPlane = rg.Plane(base_plane)
                    TargetPlane.Transform(xfm)
                except Exception:
                    TargetPlane = base_plane

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=False,
                move_x=0,
                move_y=0,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourceOut = SourceOut
            self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TargetOut = TargetOut
            self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut = TransformOut
            self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 4-3 完成：vsg2_ga__JiaoAngInLineWJiaoHuaGong")
        except Exception as e:
            self.LogLines.append("Step 4-3 失败：vsg2_ga__JiaoAngInLineWJiaoHuaGong -> {}".format(e))

    def step5_1_vsg3_PlaneFromLists1(self):
        """
        Step 5-1（组件1）: 叠次-3：vsg3_PlaneFromLists1

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ChaAngInLineWNiDaoGong2__EdgeMidPoints
        - BasePlanes   = ChaAngInLineWNiDaoGong2__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists1__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists1__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists1__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists1__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.ChaAngInLineWNiDaoGong2__EdgeMidPoints)
            BasePlanes = _ensure_list(self.ChaAngInLineWNiDaoGong2__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists1__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists1__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists1__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists1__BasePlane = BasePlane
            self.vsg3_PlaneFromLists1__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists1__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists1__Log = Log

            self.LogLines.append("Step 5-1 完成：vsg3_PlaneFromLists1")
        except Exception as e:
            self.LogLines.append("Step 5-1 失败：vsg3_PlaneFromLists1 -> {}".format(e))

    def step5_1_vsg3_ga__QiAng_DOU1(self):
        """
        Step 5-1（组件2）: 叠次-3：騎昂枓1（vsg3_ga__QiAng_DOU1）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = QiAng_DOU__CutTimbers
        - SourcePlane= QiAng_DOU__FacePlaneList[ AllDict0['vsg3_ga__QiAng_DOU1__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists1.ResultPlane,
                                Transform = vsg2_ga__ChaAngInLineWNiDaoGong2.TransformOut )
        - RotateDeg  = AllDict0['vsg3_ga__QiAng_DOU1__RotateDeg']
        - FlipZ      = AllDict0['vsg3_ga__QiAng_DOU1__FlipZ']
        - MoveY      = AllDict0['vsg3_ga__QiAng_DOU1__MoveY']
        - MoveZ      = AllDict0['vsg3_ga__QiAng_DOU1__MoveZ']
        其余 FlipX/FlipY/MoveX 按原组件默认值（False/0）。

        输出写入：
        - self.vsg3_ga__QiAng_DOU1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.QiAng_DOU__CutTimbers
            face_planes = _ensure_list(self.QiAng_DOU__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__QiAng_DOU1__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg3_ga__QiAng_DOU1__RotateDeg", 0)
            flip_z = self.AllDict0.get("vsg3_ga__QiAng_DOU1__FlipZ", False)
            move_y = self.AllDict0.get("vsg3_ga__QiAng_DOU1__MoveY", 0)
            move_z = self.AllDict0.get("vsg3_ga__QiAng_DOU1__MoveZ", 0)

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists1.ResultPlane , vsg2_ga__ChaAngInLineWNiDaoGong2.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists1__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Transform(xfm)
                    return p2
                except Exception:
                    try:
                        pl.Transform(xfm)
                        return pl
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=0,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__QiAng_DOU1__SourceOut = SourceOut
            self.vsg3_ga__QiAng_DOU1__TargetOut = TargetOut
            self.vsg3_ga__QiAng_DOU1__TransformOut = TransformOut
            self.vsg3_ga__QiAng_DOU1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-1 完成：vsg3_ga__QiAng_DOU1")
        except Exception as e:
            self.LogLines.append("Step 5-1 失败：vsg3_ga__QiAng_DOU1 -> {}".format(e))

    def step5_2_vsg3_PlaneFromLists2(self):
        """
        Step 5-2（组件1）: 叠次-3：vsg3_PlaneFromLists2

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ChaAngInLineWNiDaoGong1__EdgeMidPoints
        - BasePlanes   = ChaAngInLineWNiDaoGong1__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists2__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists2__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists2__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists2__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.ChaAngInLineWNiDaoGong1__EdgeMidPoints)
            BasePlanes = _ensure_list(self.ChaAngInLineWNiDaoGong1__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists2__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists2__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists2__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists2__BasePlane = BasePlane
            self.vsg3_PlaneFromLists2__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists2__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists2__Log = Log

            self.LogLines.append("Step 5-2 完成：vsg3_PlaneFromLists2")
        except Exception as e:
            self.LogLines.append("Step 5-2 失败：vsg3_PlaneFromLists2 -> {}".format(e))

    def step5_2_vsg3_ga__QiAng_DOU2(self):
        """
        Step 5-2（组件2）: 叠次-3：騎昂枓2（vsg3_ga__QiAng_DOU2）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = QiAng_DOU__CutTimbers
        - SourcePlane= QiAng_DOU__FacePlaneList[ AllDict0['vsg3_ga__QiAng_DOU2__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists2.ResultPlane,
                                Transform = vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut )
        - RotateDeg  = AllDict0['vsg3_ga__QiAng_DOU2__RotateDeg']
        - FlipZ      = AllDict0['vsg3_ga__QiAng_DOU2__FlipZ']
        - MoveY      = AllDict0['vsg3_ga__QiAng_DOU2__MoveY']
        - MoveZ      = AllDict0['vsg3_ga__QiAng_DOU2__MoveZ']
        其余 FlipX/FlipY/MoveX 按原组件默认值（False/0）。

        输出写入：
        - self.vsg3_ga__QiAng_DOU2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.QiAng_DOU__CutTimbers
            face_planes = _ensure_list(self.QiAng_DOU__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__QiAng_DOU2__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg3_ga__QiAng_DOU2__RotateDeg", 0)
            flip_z = self.AllDict0.get("vsg3_ga__QiAng_DOU2__FlipZ", False)
            move_y = self.AllDict0.get("vsg3_ga__QiAng_DOU2__MoveY", 0)
            move_z = self.AllDict0.get("vsg3_ga__QiAng_DOU2__MoveZ", 0)

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists2.ResultPlane , vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists2__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Transform(xfm)
                    return p2
                except Exception:
                    try:
                        pl.Transform(xfm)
                        return pl
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=0,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__QiAng_DOU2__SourceOut = SourceOut
            self.vsg3_ga__QiAng_DOU2__TargetOut = TargetOut
            self.vsg3_ga__QiAng_DOU2__TransformOut = TransformOut
            self.vsg3_ga__QiAng_DOU2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-2 完成：vsg3_ga__QiAng_DOU2")
        except Exception as e:
            self.LogLines.append("Step 5-2 失败：vsg3_ga__QiAng_DOU2 -> {}".format(e))

    def step5_3_vsg3_PlaneFromLists3(self):
        """
        Step 5-3（组件1）: 叠次-3：vsg3_PlaneFromLists3

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ChaAngInLineWNiDaoGong2__EdgeMidPoints
        - BasePlanes   = ChaAngInLineWNiDaoGong2__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists3__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists3__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists3__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists3__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.ChaAngInLineWNiDaoGong2__EdgeMidPoints)
            BasePlanes = _ensure_list(self.ChaAngInLineWNiDaoGong2__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists3__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists3__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists3__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists3__BasePlane = BasePlane
            self.vsg3_PlaneFromLists3__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists3__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists3__Log = Log

            self.LogLines.append("Step 5-3 完成：vsg3_PlaneFromLists3")
        except Exception as e:
            self.LogLines.append("Step 5-3 失败：vsg3_PlaneFromLists3 -> {}".format(e))

    def step5_3_vsg3_ga__SAN_DOU1(self):
        """
        Step 5-3（组件2）: 叠次-3：散枓1（vsg3_ga__SAN_DOU1）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = SAN_DOU__CutTimbers
        - SourcePlane= SAN_DOU__FacePlaneList[ AllDict0['vsg3_ga__SAN_DOU1__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists3.ResultPlane,
                                Transform = vsg2_ga__ChaAngInLineWNiDaoGong2.TransformOut )
        - RotateDeg  = AllDict0['vsg3_ga__SAN_DOU1__RotateDeg']
        - FlipZ      = AllDict0['vsg3_ga__SAN_DOU1__FlipZ']（若库中缺失则默认 False）
        - MoveX      = AllDict0['vsg3_ga__SAN_DOU1__MoveX']
        - MoveZ      = AllDict0['vsg3_ga__SAN_DOU1__MoveZ']
        其余 FlipX/FlipY/MoveY 按原组件默认值（False/0）。

        输出写入：
        - self.vsg3_ga__SAN_DOU1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.SAN_DOU__CutTimbers
            face_planes = _ensure_list(self.SAN_DOU__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__SAN_DOU1__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg3_ga__SAN_DOU1__RotateDeg", 0)
            flip_z = self.AllDict0.get("vsg3_ga__SAN_DOU1__FlipZ", False)
            move_x = self.AllDict0.get("vsg3_ga__SAN_DOU1__MoveX", 0)
            move_z = self.AllDict0.get("vsg3_ga__SAN_DOU1__MoveZ", 0)

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists3.ResultPlane , vsg2_ga__ChaAngInLineWNiDaoGong2.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists3__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Transform(xfm)
                    return p2
                except Exception:
                    try:
                        pl.Transform(xfm)
                        return pl
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=move_x,
                move_y=0,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__SAN_DOU1__SourceOut = SourceOut
            self.vsg3_ga__SAN_DOU1__TargetOut = TargetOut
            self.vsg3_ga__SAN_DOU1__TransformOut = TransformOut
            self.vsg3_ga__SAN_DOU1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-3 完成：vsg3_ga__SAN_DOU1")
        except Exception as e:
            self.LogLines.append("Step 5-3 失败：vsg3_ga__SAN_DOU1 -> {}".format(e))

    def step5_4_vsg3_PlaneFromLists4(self):
        """
        Step 5-4（组件1）: 叠次-3：vsg3_PlaneFromLists4

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ChaAngInLineWNiDaoGong1__EdgeMidPoints
        - BasePlanes   = ChaAngInLineWNiDaoGong1__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists4__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists4__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists4__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists4__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.ChaAngInLineWNiDaoGong1__EdgeMidPoints)
            BasePlanes = _ensure_list(self.ChaAngInLineWNiDaoGong1__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists4__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists4__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists4__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists4__BasePlane = BasePlane
            self.vsg3_PlaneFromLists4__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists4__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists4__Log = Log

            self.LogLines.append("Step 5-4 完成：vsg3_PlaneFromLists4")
        except Exception as e:
            self.LogLines.append("Step 5-4 失败：vsg3_PlaneFromLists4 -> {}".format(e))

    def step5_4_vsg3_ga__SAN_DOU2(self):
        """
        Step 5-4（组件2）: 叠次-3：散枓1（vsg3_ga__SAN_DOU2）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = SAN_DOU__CutTimbers
        - SourcePlane= SAN_DOU__FacePlaneList[ AllDict0['vsg3_ga__SAN_DOU2__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists4.ResultPlane,
                                Transform = vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut )
        - RotateDeg  = AllDict0['vsg3_ga__SAN_DOU2__RotateDeg']
        - FlipZ      = AllDict0['vsg3_ga__SAN_DOU2__FlipZ']（若库中缺失则默认 False）
        - MoveX      = AllDict0['vsg3_ga__SAN_DOU2__MoveX']
        - MoveZ      = AllDict0['vsg3_ga__SAN_DOU2__MoveZ']
        其余 FlipX/FlipY/MoveY 按原组件默认值（False/0）。

        输出写入：
        - self.vsg3_ga__SAN_DOU2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.SAN_DOU__CutTimbers
            face_planes = _ensure_list(self.SAN_DOU__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__SAN_DOU2__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg3_ga__SAN_DOU2__RotateDeg", 0)
            flip_z = self.AllDict0.get("vsg3_ga__SAN_DOU2__FlipZ", False)
            move_x = self.AllDict0.get("vsg3_ga__SAN_DOU2__MoveX", 0)
            move_z = self.AllDict0.get("vsg3_ga__SAN_DOU2__MoveZ", 0)

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists4.ResultPlane , vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists4__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Transform(xfm)
                    return p2
                except Exception:
                    try:
                        pl.Transform(xfm)
                        return pl
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=move_x,
                move_y=0,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__SAN_DOU2__SourceOut = SourceOut
            self.vsg3_ga__SAN_DOU2__TargetOut = TargetOut
            self.vsg3_ga__SAN_DOU2__TransformOut = TransformOut
            self.vsg3_ga__SAN_DOU2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-4 完成：vsg3_ga__SAN_DOU2")
        except Exception as e:
            self.LogLines.append("Step 5-4 失败：vsg3_ga__SAN_DOU2 -> {}".format(e))

    def step5_5_vsg3_PlaneFromLists5(self):
        """
        Step 5-5（组件1）: 叠次-3：vsg3_PlaneFromLists5

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = JiaoAngInLineWJiaoHuaGong__EdgeMidPoints
        - BasePlanes   = JiaoAngInLineWJiaoHuaGong__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists5__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists5__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists5__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists5__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.JiaoAngInLineWJiaoHuaGong__EdgeMidPoints)
            BasePlanes = _ensure_list(self.JiaoAngInLineWJiaoHuaGong__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists5__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists5__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists5__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists5__BasePlane = BasePlane
            self.vsg3_PlaneFromLists5__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists5__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists5__Log = Log

            self.LogLines.append("Step 5-5 完成：vsg3_PlaneFromLists5")
        except Exception as e:
            self.LogLines.append("Step 5-5 失败：vsg3_PlaneFromLists5 -> {}".format(e))

    def step5_5_vsg3_ga__PingPanDou1(self):
        """
        Step 5-5（组件2）: 叠次-3：平盤枓1（vsg3_ga__PingPanDou1）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = PingPanDou__CutTimbers
        - SourcePlane= PingPanDou__FacePlaneList[ AllDict0['vsg3_ga__PingPanDou1__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists5.ResultPlane,
                                Transform = vsg2_ga__JiaoAngInLineWJiaoHuaGong.TransformOut )
        - RotateDeg  = AllDict0['vsg3_ga__PingPanDou1__RotateDeg']
        - FlipZ      = AllDict0['vsg3_ga__PingPanDou1__FlipZ']（若库中缺失则默认 False）
        - MoveY      = AllDict0['vsg3_ga__PingPanDou1__MoveY']
        - MoveZ      = AllDict0['vsg3_ga__PingPanDou1__MoveZ']
        其余 FlipX/FlipY/MoveX 按原组件默认值（False/0）。

        输出写入：
        - self.vsg3_ga__PingPanDou1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.PingPanDou__CutTimbers
            face_planes = _ensure_list(self.PingPanDou__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__PingPanDou1__SourcePlane", 0)
            rotate_deg = self.AllDict0.get("vsg3_ga__PingPanDou1__RotateDeg", 0)
            flip_z = self.AllDict0.get("vsg3_ga__PingPanDou1__FlipZ", False)
            move_y = self.AllDict0.get("vsg3_ga__PingPanDou1__MoveY", 0)
            move_z = self.AllDict0.get("vsg3_ga__PingPanDou1__MoveZ", 0)

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists5.ResultPlane , vsg2_ga__JiaoAngInLineWJiaoHuaGong.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists5__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    p2 = rg.Plane(pl)
                    p2.Transform(xfm)
                    return p2
                except Exception:
                    try:
                        pl.Transform(xfm)
                        return pl
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=False,
                flip_y=False,
                flip_z=bool(flip_z),
                move_x=0,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__PingPanDou1__SourceOut = SourceOut
            self.vsg3_ga__PingPanDou1__TargetOut = TargetOut
            self.vsg3_ga__PingPanDou1__TransformOut = TransformOut
            self.vsg3_ga__PingPanDou1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-5 完成：vsg3_ga__PingPanDou1")
        except Exception as e:
            self.LogLines.append("Step 5-5 失败：vsg3_ga__PingPanDou1 -> {}".format(e))

    def step5_6_vsg3_PlaneFromLists6(self):
        """
        Step 5-6（组件1）: 叠次-3：vsg3_PlaneFromLists6

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = JiaoAngInLineWJiaoHuaGong__EdgeMidPoints
        - BasePlanes   = JiaoAngInLineWJiaoHuaGong__Corner0Planes
        - IndexOrigin  = AllDict0['vsg3_PlaneFromLists6__IndexOrigin']
        - IndexPlane   = AllDict0['vsg3_PlaneFromLists6__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg3_PlaneFromLists6__Wrap']，默认 True

        输出写入：
        - self.vsg3_PlaneFromLists6__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            OriginPoints = _ensure_list(self.JiaoAngInLineWJiaoHuaGong__EdgeMidPoints)
            BasePlanes = _ensure_list(self.JiaoAngInLineWJiaoHuaGong__Corner0Planes)

            idx_origin = self.AllDict0.get("vsg3_PlaneFromLists6__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg3_PlaneFromLists6__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg3_PlaneFromLists6__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg3_PlaneFromLists6__BasePlane = BasePlane
            self.vsg3_PlaneFromLists6__OriginPoint = OriginPoint
            self.vsg3_PlaneFromLists6__ResultPlane = ResultPlane
            self.vsg3_PlaneFromLists6__Log = Log

            self.LogLines.append("Step 5-6 完成：vsg3_PlaneFromLists6")
        except Exception as e:
            self.LogLines.append("Step 5-6 失败：vsg3_PlaneFromLists6 -> {}".format(e))

    def step5_6_vsg3_ga__PingPanDou2(self):
        """
        Step 5-6（组件2）: 叠次-3：平盤枓2（vsg3_ga__PingPanDou2）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = PingPanDou__CutTimbers
        - SourcePlane= PingPanDou__FacePlaneList[ AllDict0['vsg3_ga__PingPanDou2__SourcePlane'] ]
        - TargetPlane= Transform( Geometry = vsg3_PlaneFromLists6.ResultPlane,
                                Transform = vsg2_ga__JiaoAngInLineWJiaoHuaGong.TransformOut )
        - FlipZ      = AllDict0['vsg3_ga__PingPanDou2__FlipZ']（若库中缺失则默认 False）
        - MoveY      = AllDict0['vsg3_ga__PingPanDou2__MoveY']
        - MoveZ      = AllDict0['vsg3_ga__PingPanDou2__MoveZ']

        ⚠️ 你提供的该步说明中未包含 RotateDeg / FlipX / FlipY / MoveX：
        - RotateDeg 按 0
        - FlipX/FlipY 按 False
        - MoveX 按 0

        输出写入：
        - self.vsg3_ga__PingPanDou2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.PingPanDou__CutTimbers
            face_planes = _ensure_list(self.PingPanDou__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg3_ga__PingPanDou2__SourcePlane", 0)
            flip_z = self.AllDict0.get("vsg3_ga__PingPanDou2__FlipZ", False)
            move_y = self.AllDict0.get("vsg3_ga__PingPanDou2__MoveY", 0)
            move_z = self.AllDict0.get("vsg3_ga__PingPanDou2__MoveZ", 0)

            # defaults (not provided in step说明)
            rotate_deg = 0
            flip_x = False
            flip_y = False
            move_x = 0

            def _pick_plane_from_list(planes, idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(planes):
                    ii = len(planes) - 1 if len(planes) > 0 else 0
                return planes[ii] if len(planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane_from_list(face_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane_from_list(face_planes, sp_idx)

            # ----------------------------
            # TargetPlane = Transform( vsg3_PlaneFromLists6.ResultPlane , vsg2_ga__JiaoAngInLineWJiaoHuaGong.TransformOut )
            # ----------------------------
            base_plane = self.vsg3_PlaneFromLists6__ResultPlane

            # 解包 Transform（可能为 GH_Transform）
            xfm = self.vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    pl2 = rg.Plane(pl)
                    pl2.Transform(xfm)
                    return pl2
                except Exception:
                    try:
                        pl2 = pl
                        pl2.Transform(xfm)
                        return pl2
                    except Exception:
                        return pl

            if isinstance(base_plane, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_plane]
            else:
                TargetPlane = _xfm_plane(base_plane)

            # 运行 GeoAligner_xfm.align（按原组件签名）
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg3_ga__PingPanDou2__SourceOut = SourceOut
            self.vsg3_ga__PingPanDou2__TargetOut = TargetOut
            self.vsg3_ga__PingPanDou2__TransformOut = TransformOut
            self.vsg3_ga__PingPanDou2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 5-6 完成：vsg3_ga__PingPanDou2")
        except Exception as e:
            self.LogLines.append("Step 5-6 失败：vsg3_ga__PingPanDou2 -> {}".format(e))

    def step6_1_vsg4_ga__LingGongInLineWXiaoGongTou1(self):
        """
        Step 6-1：叠次-4：令栱與小栱頭相列一（vsg4_ga__LingGongInLineWXiaoGongTou1）

        组件输入端（严格按你提供的说明复刻）：
        - Geo = LingGongInLineWXiaoGongTou1__CutTimbers
        - SourcePlane = LingGongInLineWXiaoGongTou1__Skew_Planes[
              AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou1__SourcePlane']
          ]
        - TargetPlane = Transform(
              Geometry  = PingPanDou__FacePlaneList[
                    AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou1__TargetPlane_Geometry']
              ],
              Transform = vsg3_ga__PingPanDou2.TransformOut
          )
        - RotateDeg = AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou1__RotateDeg']
        - FlipX     = AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou1__FlipX']

        ⚠️ 原 ghpy 组件还支持 FlipY/FlipZ/MoveX/MoveY/MoveZ，但本步说明未提供：
        - FlipY/FlipZ 默认 False
        - MoveX/MoveY/MoveZ 默认 0

        输出写入：
        - self.vsg4_ga__LingGongInLineWXiaoGongTou1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = self.LingGongInLineWXiaoGongTou1__CutTimbers
            skew_planes = _ensure_list(self.LingGongInLineWXiaoGongTou1__Skew_Planes)

            face_planes = _ensure_list(self.PingPanDou__FacePlaneList)

            # DB 参数
            sp_idx = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou1__SourcePlane", 0)
            tp_geo_idx = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou1__TargetPlane_Geometry", 0)
            rotate_deg = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou1__RotateDeg", 0)
            flip_x = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou1__FlipX", False)

            # defaults (not provided in step说明)
            flip_y = False
            flip_z = False
            move_x = 0
            move_y = 0
            move_z = 0

            def _pick_from_list(arr, idx_val):
                arr = _ensure_list(arr)
                if len(arr) == 0:
                    return None
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(arr):
                    ii = len(arr) - 1
                return arr[ii]

            # SourcePlane：来自 Skew_Planes 按索引
            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_from_list(skew_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_from_list(skew_planes, sp_idx)

            # TargetPlane：先从 PingPanDou__FacePlaneList 取 Plane，再应用 vsg3_ga__PingPanDou2.TransformOut
            if isinstance(tp_geo_idx, (list, tuple)):
                base_tp = [_pick_from_list(face_planes, i) for i in tp_geo_idx]
            else:
                base_tp = _pick_from_list(face_planes, tp_geo_idx)

            xfm = self.vsg3_ga__PingPanDou2__TransformOut
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    pl2 = rg.Plane(pl)
                    pl2.Transform(xfm)
                    return pl2
                except Exception:
                    try:
                        pl2 = pl
                        pl2.Transform(xfm)
                        return pl2
                    except Exception:
                        return pl

            if isinstance(base_tp, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_tp]
            else:
                TargetPlane = _xfm_plane(base_tp)

            # 运行 GeoAligner_xfm.align（按原组件签名）
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=bool(flip_x),
                flip_y=bool(flip_y),
                flip_z=bool(flip_z),
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg4_ga__LingGongInLineWXiaoGongTou1__SourceOut = SourceOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou1__TargetOut = TargetOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut = TransformOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-1 完成：vsg4_ga__LingGongInLineWXiaoGongTou1")
        except Exception as e:
            self.LogLines.append("Step 6-1 失败：vsg4_ga__LingGongInLineWXiaoGongTou1 -> {}".format(e))

    def step6_2_vsg4_ga__LingGongInLineWXiaoGongTou2(self):
        """
        Step 6-2：叠次-4：令栱與小栱頭相列二（vsg4_ga__LingGongInLineWXiaoGongTou2）

        组件输入端（严格按你提供的说明复刻）：
        - Geo = LingGongInLineWXiaoGongTou2（优先取 LingGongInLineWXiaoGongTou2__CutTimbers）
        - SourcePlane = LingGongInLineWXiaoGongTou2__Skew_Planes[
            AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou2__SourcePlane']
        ]
        - TargetPlane = Transform(
            Geometry  = PingPanDou__FacePlaneList[
                    AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou2__TargetPlane_Geometry']
            ],
            Transform = vsg3_ga__PingPanDou2.TransformOut
        )
        - RotateDeg = AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou2__RotateDeg']
        - FlipX     = AllDict0['vsg4_ga__LingGongInLineWXiaoGongTou2__FlipX']

        ⚠️ 原 ghpy 组件还支持 FlipY/FlipZ/MoveX/MoveY/MoveZ，但本步说明未提供：
        - FlipY/FlipZ 默认 False
        - MoveX/MoveY/MoveZ 默认 0

        输出写入：
        - self.vsg4_ga__LingGongInLineWXiaoGongTou2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            geo = getattr(self, "LingGongInLineWXiaoGongTou2__CutTimbers", None)
            if geo is None:
                geo = getattr(self, "LingGongInLineWXiaoGongTou2", None)

            skew_planes = _ensure_list(getattr(self, "LingGongInLineWXiaoGongTou2__Skew_Planes", None))
            face_planes = _ensure_list(getattr(self, "PingPanDou__FacePlaneList", None))

            # DB 参数
            sp_idx = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou2__SourcePlane", 0)
            tp_geo_idx = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou2__TargetPlane_Geometry", 0)
            rotate_deg = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou2__RotateDeg", 0)
            flip_x = self.AllDict0.get("vsg4_ga__LingGongInLineWXiaoGongTou2__FlipX", False)

            # defaults (not provided in step说明)
            flip_y = False
            flip_z = False
            move_x = 0
            move_y = 0
            move_z = 0

            def _pick_from_list(arr, idx_val):
                arr = _ensure_list(arr)
                if len(arr) == 0:
                    return None
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(arr):
                    ii = len(arr) - 1
                return arr[ii]

            # SourcePlane：来自 Skew_Planes 按索引
            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_from_list(skew_planes, i) for i in sp_idx]
            else:
                SourcePlane = _pick_from_list(skew_planes, sp_idx)

            # TargetPlane：先从 PingPanDou__FacePlaneList 取 Plane，再应用 vsg3_ga__PingPanDou2.TransformOut
            if isinstance(tp_geo_idx, (list, tuple)):
                base_tp = [_pick_from_list(face_planes, i) for i in tp_geo_idx]
            else:
                base_tp = _pick_from_list(face_planes, tp_geo_idx)

            xfm = getattr(self, "vsg3_ga__PingPanDou2__TransformOut", None)
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            def _xfm_plane(pl):
                if pl is None:
                    return None
                try:
                    pl2 = rg.Plane(pl)
                    pl2.Transform(xfm)
                    return pl2
                except Exception:
                    try:
                        pl2 = pl
                        pl2.Transform(xfm)
                        return pl2
                    except Exception:
                        return pl

            if isinstance(base_tp, (list, tuple)):
                TargetPlane = [_xfm_plane(p) for p in base_tp]
            else:
                TargetPlane = _xfm_plane(base_tp)

            # 运行 GeoAligner_xfm.align（按原组件签名）
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=bool(flip_x),
                flip_y=bool(flip_y),
                flip_z=bool(flip_z),
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            self.vsg4_ga__LingGongInLineWXiaoGongTou2__SourceOut = SourceOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou2__TargetOut = TargetOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut = TransformOut
            self.vsg4_ga__LingGongInLineWXiaoGongTou2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-2 完成：vsg4_ga__LingGongInLineWXiaoGongTou2")
        except Exception as e:
            self.LogLines.append("Step 6-2 失败：vsg4_ga__LingGongInLineWXiaoGongTou2 -> {}".format(e))

    def step6_3_vsg4_ga__ShuaTouInLineWManGong1(self):
        """
        Step 6-3：叠次-4：耍頭與慢栱相列一（vsg4_ga__ShuaTouInLineWManGong1）

        组件输入端（参考 step6_4 的实现方式，按工作流说明复刻）：

        * Geo
        = ShuaTouInLineWManGong1__CutTimbers

        * SourcePlane
        = Tree Item 的结果，其中：
        - Tree  = ShuaTouInLineWManGong1__Skew_Planes
        - Path  = AllDict0['vsg4_ga__ShuaTouInLineWManGong1__SourcePlanem_Path']
        - Index = AllDict0['vsg4_ga__ShuaTouInLineWManGong1__SourcePlane_Index']
        - Wrap = False（默认不启用）

        * TargetPlane
        = Transform 的变换结果，其中：
        - Transform.Geometry  = ChaAngInLineWNiDaoGong1__FacePlaneList[
                AllDict0['vsg4_ga__ShuaTouInLineWManGong1__TargetPlane_Geometry']
            ]
        - Transform.Transform = vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut

        * RotateDeg
        默认值 0

        * FlipX
        = AllDict0['vsg4_ga__ShuaTouInLineWManGong1__FlipX']

        其余 FlipY/FlipZ/MoveX/MoveY/MoveZ 未连接：按默认值处理。
        """
        try:
            import ghpythonlib.components as ghc

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "ShuaTouInLineWManGong1__CutTimbers", None)
            if geo is None:
                geo = getattr(self, "ShuaTouInLineWManGong1", None)

            # -----------------------------
            # Tree Item：SourcePlane
            # -----------------------------
            tree = getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None)

            # DB 参数（按字段名；最小兼容：若字段不存在则回退到 SourcePlane_Path）
            path_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__SourcePlanem_Path", None)
            if path_spec is None:
                path_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__SourcePlane_Path", "{0}")
            index_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__SourcePlane_Index", 0)

            SourcePlane = ghc.TreeItem(
                tree,
                path_spec,
                index_spec,
                False
            )

            # -----------------------------
            # TargetPlane：FacePlaneList + TransformOut（来自 vsg2_ga__ChaAngInLineWNiDaoGong1）
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "ChaAngInLineWNiDaoGong1__FacePlaneList", None))
            tp_geo_idx = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__TargetPlane_Geometry", 0)

            def _pick_from_list(arr, idx_val):
                arr = _ensure_list(arr)
                if len(arr) == 0:
                    return None
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(arr):
                    ii = len(arr) - 1
                return arr[ii]

            base_tp = _pick_from_list(face_planes, tp_geo_idx)

            xfm = getattr(self, "vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut", None)
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(base_tp, xfm) if (base_tp is not None and xfm is not None) else base_tp

            # -----------------------------
            # 其余参数
            # -----------------------------
            rotate_deg = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__RotateDeg", 0)
            flip_x = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong1__FlipX", False)

            flip_y = False
            flip_z = False
            move_x = 0
            move_y = 0
            move_z = 0

            # 运行 GeoAligner_xfm.align（按原组件签名）
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # 输出（展平）
            self.vsg4_ga__ShuaTouInLineWManGong1__SourceOut = SourceOut
            self.vsg4_ga__ShuaTouInLineWManGong1__TargetOut = TargetOut
            self.vsg4_ga__ShuaTouInLineWManGong1__TransformOut = TransformOut
            self.vsg4_ga__ShuaTouInLineWManGong1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-3 完成：vsg4_ga__ShuaTouInLineWManGong1")
        except Exception as e:
            self.LogLines.append("Step 6-3 失败：vsg4_ga__ShuaTouInLineWManGong1 -> {}".format(e))

    def step6_4_vsg4_ga__ShuaTouInLineWManGong2(self):
        """
        Step 6-4：叠次-4：耍頭與慢栱相列二（vsg4_ga__ShuaTouInLineWManGong2）

        组件输入端（严格按你提供的说明复刻）：

        * Geo
          = ShuaTouInLineWManGong2__CutTimbers

        * SourcePlane
          = Tree Item 的结果，其中：
          - Tree  = ShuaTouInLineWManGong2__Skew_Planes
          - Path  = AllDict0['vsg4_ga__ShuaTouInLineWManGong2__SourcePlanem_Path']
          - Index = AllDict0['vsg4_ga__ShuaTouInLineWManGong2__SourcePlane_Index']
          - Wrap = False（默认不启用）

          注意：Tree Item 使用 ghc.TreeItem（import ghpythonlib.components as ghc）

        * TargetPlane
          = Transform 的变换结果，其中：
          - Transform.Geometry  = ChaAngInLineWNiDaoGong1__FacePlaneList[
                AllDict0['vsg4_ga__ShuaTouInLineWManGong2__TargetPlane_Geometry']
            ]
          - Transform.Transform = vsg2_ga__ChaAngInLineWNiDaoGong1.TransformOut

          注意：Transform 使用 ghc.Transform（import ghpythonlib.components as ghc）

        * RotateDeg
          默认值 0

        * FlipX
          = AllDict0['vsg4_ga__ShuaTouInLineWManGong2__FlipX']

        其余 FlipY/FlipZ/MoveX/MoveY/MoveZ 在该工作流中未连接：按默认值处理。
        - FlipY/FlipZ 默认 False
        - MoveX/MoveY/MoveZ 默认 0

        输出写入：
        - self.vsg4_ga__ShuaTouInLineWManGong2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import ghpythonlib.components as ghc

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "ShuaTouInLineWManGong2__CutTimbers", None)
            if geo is None:
                geo = getattr(self, "ShuaTouInLineWManGong2", None)

            # -----------------------------
            # Tree Item：SourcePlane
            # -----------------------------
            tree = getattr(self, "ShuaTouInLineWManGong2__Skew_Planes", None)

            # DB 参数（按你给的字段名；同时做最小兼容：若字段不存在则回退到 SourcePlane_Path）
            path_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong2__SourcePlanem_Path", None)
            if path_spec is None:
                path_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong2__SourcePlane_Path", "{0}")
            index_spec = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong2__SourcePlane_Index", 0)

            SourcePlane = ghc.TreeItem(
                tree,
                path_spec,
                index_spec,
                False
            )

            # -----------------------------
            # TargetPlane：FacePlaneList + TransformOut（来自 vsg2_ga__ChaAngInLineWNiDaoGong1）
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "ChaAngInLineWNiDaoGong1__FacePlaneList", None))
            tp_geo_idx = self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong2__TargetPlane_Geometry", 0)

            def _pick_from_list(arr, idx_val):
                arr = _ensure_list(arr)
                if len(arr) == 0:
                    return None
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(arr):
                    ii = len(arr) - 1
                return arr[ii]

            base_tp = _pick_from_list(face_planes, tp_geo_idx)

            xfm = getattr(self, "vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut", None)
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(base_tp, xfm) if (base_tp is not None and xfm is not None) else base_tp

            # -----------------------------
            # 其余参数
            # -----------------------------
            rotate_deg = 0
            flip_x = bool(self.AllDict0.get("vsg4_ga__ShuaTouInLineWManGong2__FlipX", False))

            flip_y = False
            flip_z = False
            move_x = 0
            move_y = 0
            move_z = 0

            # 运行 GeoAligner_xfm.align（按原组件签名）
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=rotate_deg,
                flip_x=flip_x,
                flip_y=flip_y,
                flip_z=flip_z,
                move_x=move_x,
                move_y=move_y,
                move_z=move_z,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # 输出（展平）
            self.vsg4_ga__ShuaTouInLineWManGong2__SourceOut = SourceOut
            self.vsg4_ga__ShuaTouInLineWManGong2__TargetOut = TargetOut
            self.vsg4_ga__ShuaTouInLineWManGong2__TransformOut = TransformOut
            self.vsg4_ga__ShuaTouInLineWManGong2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-4 完成：vsg4_ga__ShuaTouInLineWManGong2")
        except Exception as e:
            self.LogLines.append("Step 6-4 失败：vsg4_ga__ShuaTouInLineWManGong2 -> {}".format(e))

    def step6_5_vsg4_ga__GuaZiGongInLineWLingGong1(self):
        """
        Step 6-5：叠次-4：瓜子栱與令栱相列一（vsg4_ga__GuaZiGongInLineWLingGong1）

        组件输入端（严格按你提供的说明复刻）：

        * Geo
          = GuaZiGongInLineWLingGong1__CutTimbers

        * SourcePlane
          = Tree Item 的结果，其中：
          - Tree  = GuaZiGongInLineWLingGong1__Skew_Planes
          - Path  = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong1__SourcePlane_Path']
          - Index = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong1__SourcePlane_Index']
          - Wrap = False（默认不启用）

          注意：Tree Item 使用 ghc.TreeItem（import ghpythonlib.components as ghc）

        * TargetPlane
          = Transform 的变换结果，其中：
          - Transform.Geometry = Tree Item 的提取结果，Tree Item 输入端：
                Tree  = ShuaTouInLineWManGong2__Skew_Planes
                Path  = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong1__TargetPlane_Geometrym_Path']
                Index = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong1__TargetPlane_Geometry_Index']
                Wrap  = False
          - Transform.Transform = vsg4_ga__ShuaTouInLineWManGong2.TransformOut

          注意：Transform 使用 ghc.Transform（import ghpythonlib.components as ghc）

        * RotateDeg
          默认值：AllDict0['vsg4_ga__GuaZiGongInLineWLingGong1__RotateDeg']（若缺省则 0）

        其余 FlipX/FlipY/FlipZ/MoveX/MoveY/MoveZ 在该工作流中未连接：按默认值处理。
        - FlipX/FlipY/FlipZ 默认 False
        - MoveX/MoveY/MoveZ 默认 0

        输出写入：
        - self.vsg4_ga__GuaZiGongInLineWLingGong1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "GuaZiGongInLineWLingGong1__CutTimbers", None)
            if geo is None:
                geo = []
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：Tree Item
            # -----------------------------
            tree = getattr(self, "GuaZiGongInLineWLingGong1__Skew_Planes", None)
            if tree is None:
                tree = []

            path_spec = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__SourcePlane_Path", "{0}")
            index_spec = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__SourcePlane_Index", 0)

            SourcePlane = ghc.TreeItem(
                tree,
                path_spec,
                index_spec,
                False
            )

            # -----------------------------
            # TargetPlane：TreeItem + Transform(plane)
            # -----------------------------
            tgt_tree = getattr(self, "ShuaTouInLineWManGong2__Skew_Planes", None)
            if tgt_tree is None:
                tgt_tree = []

            tgt_path = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__TargetPlane_Geometrym_Path", "{0}")
            tgt_index = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__TargetPlane_Geometry_Index", 0)

            tgt_geo_item = ghc.TreeItem(
                tgt_tree,
                tgt_path,
                tgt_index,
                False
            )

            xfm = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)
            if xfm is None:
                xfm = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)

            TargetPlane = ghc.Transform(tgt_geo_item, xfm) if (
                        tgt_geo_item is not None and xfm is not None) else tgt_geo_item

            # -----------------------------
            # Rotate / Flip / Move（默认）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__FlipX", False)
            FlipY = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__FlipY", False)
            FlipZ = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__FlipZ", False)

            MoveX = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__MoveX", 0)
            MoveY = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong1__MoveZ", 0)

            # -----------------------------
            # 调用 GeoAligner_xfm（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )
            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # -----------------------------
            # 输出写入（注意：完全展平）
            # -----------------------------
            self.vsg4_ga__GuaZiGongInLineWLingGong1__SourceOut = SourceOut
            self.vsg4_ga__GuaZiGongInLineWLingGong1__TargetOut = TargetOut
            self.vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut = TransformOut
            self.vsg4_ga__GuaZiGongInLineWLingGong1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-5 完成：vsg4_ga__GuaZiGongInLineWLingGong1")
        except Exception as e:
            self.LogLines.append("Step 6-5 失败：vsg4_ga__GuaZiGongInLineWLingGong1 -> {}".format(e))

    def step6_6_vsg4_ga__GuaZiGongInLineWLingGong2(self):
        """
        Step 6-6：叠次-4：瓜子栱與令栱相列二（vsg4_ga__GuaZiGongInLineWLingGong2）

        组件输入端（严格按你提供的说明复刻）：

        * Geo
          = GuaZiGongInLineWLingGong2__CutTimbers

        * SourcePlane
          = Tree Item 的结果，其中：
          - Tree  = GuaZiGongInLineWLingGong2__Skew_Planes
          - Path  = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong2__SourcePlane_Path']
          - Index = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong2__SourcePlane_Index']
          - Wrap = False（默认不启用）

        * TargetPlane
          = Transform 的变换结果，其中：
          - Transform.Geometry = Tree Item 的提取结果，Tree Item 输入端：
                Tree  = ShuaTouInLineWManGong1__Skew_Planes
                Path  = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong2__TargetPlane_Geometrym_Path']
                Index = AllDict0['vsg4_ga__GuaZiGongInLineWLingGong2__TargetPlane_Geometry_Index']
                Wrap  = False
          - Transform.Transform = vsg4_ga__ShuaTouInLineWManGong1.TransformOut

        * RotateDeg
          默认值：AllDict0['vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg']（若缺省则 0）

        其余 FlipX/FlipY/FlipZ/MoveX/MoveY/MoveZ 在该工作流中未连接：按默认值处理。

        输出写入：
        - self.vsg4_ga__GuaZiGongInLineWLingGong2__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm
            import Grasshopper.Kernel.Types as ght
            import Rhino.Geometry as rg

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "GuaZiGongInLineWLingGong2__CutTimbers", None)
            if geo is None:
                geo = []
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：Tree Item
            # -----------------------------
            tree = getattr(self, "GuaZiGongInLineWLingGong2__Skew_Planes", None)
            if tree is None:
                tree = []

            path_spec = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__SourcePlane_Path", "{0}")
            index_spec = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__SourcePlane_Index", 0)

            SourcePlane = ghc.TreeItem(
                tree,
                path_spec,
                index_spec,
                False
            )

            # -----------------------------
            # TargetPlane：TreeItem + Transform(plane)
            # -----------------------------
            tgt_tree = getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None)
            if tgt_tree is None:
                tgt_tree = []

            tgt_path = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__TargetPlane_Geometrym_Path", "{0}")
            tgt_index = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__TargetPlane_Geometry_Index", 0)

            tgt_geo_item = ghc.TreeItem(
                tgt_tree,
                tgt_path,
                tgt_index,
                False
            )

            xfm = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            # ghc.Transform 需要 Rhino.Geometry.Transform；若上游是 GH_Transform，则取其 Value
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(tgt_geo_item, xfm) if (
                        tgt_geo_item is not None and xfm is not None) else tgt_geo_item

            # -----------------------------
            # Rotate / Flip / Move（默认/数据库）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__FlipX", False)
            FlipY = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__FlipY", False)
            FlipZ = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__FlipZ", False)

            MoveX = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__MoveX", 0)
            MoveY = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg4_ga__GuaZiGongInLineWLingGong2__MoveZ", 0)

            # -----------------------------
            # 调用 GeoAligner_xfm（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )
            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg4_ga__GuaZiGongInLineWLingGong2__SourceOut = SourceOut
            self.vsg4_ga__GuaZiGongInLineWLingGong2__TargetOut = TargetOut
            self.vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut = TransformOut
            self.vsg4_ga__GuaZiGongInLineWLingGong2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-6 完成：vsg4_ga__GuaZiGongInLineWLingGong2")
        except Exception as e:
            self.LogLines.append("Step 6-6 失败：vsg4_ga__GuaZiGongInLineWLingGong2 -> {}".format(e))

    def step6_7_vsg4_ga__YouAngInLineWJiaoShuaTou(self):
        """
        Step 6-7：叠次-4：由昂與角耍頭相列
        包括组件：
        - vsg4_TreeItem_ListItem_PlaneOrigin_Transform1
        - vsg4_ga__YouAngInLineWJiaoShuaTou

        组件输入端（严格按你提供的说明复刻）：

        * Geo
          = YouAngInLineWJiaoShuaTou__CutTimbers

        * SourcePlane
          = Tree Item 的结果，其中：
          - Tree  = YouAngInLineWJiaoShuaTou__Skew_Planes
          - Path  = AllDict0['vsg4_ga__YouAngInLineWJiaoShuaTou__SourcePlane_Path']
          - Index = AllDict0['vsg4_ga__YouAngInLineWJiaoShuaTou__SourcePlane_Index']
          - Wrap = False

        * TargetPlane
          = vsg4_TreeItem_ListItem_PlaneOrigin_Transform1 的计算结果（Transform_Geometry_Out），其中：
          - TreeItem_Tree  = ShuaTouInLineWManGong1__Skew_Planes
          - ListItem_List  = ShuaTouInLineWManGong1__Skew_Point_C
          - TreeItem_Path  = AllDict0['vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path']
          - TreeItem_Index = AllDict0['vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Index']
          - ListItem_Index = AllDict0['vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__ListItem_Index']
          - Transform_Transform = vsg4_ga__ShuaTouInLineWManGong1__TransformOut

        * RotateDeg
          = AllDict0['vsg4_ga__YouAngInLineWJiaoShuaTou__RotateDeg']（若缺省则 0）

        * MoveZ
          = AllDict0['vsg4_ga__YouAngInLineWJiaoShuaTou__MoveZ']（若缺省则 0）

        其余 FlipX/FlipY/FlipZ/MoveX/MoveY 在该工作流中未连接：按默认值（或数据库同名键）处理。
        """
        try:
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            import Rhino.Geometry as rg
            from yingzao.ancientArchi import GeoAligner_xfm
            from yingzao.ancientArchi import GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "YouAngInLineWJiaoShuaTou__CutTimbers", None)
            if geo is None:
                geo = []
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：Tree Item（ghc.TreeItem）
            # -----------------------------
            src_tree = getattr(self, "YouAngInLineWJiaoShuaTou__Skew_Planes", None)
            if src_tree is None:
                src_tree = []

            src_path = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__SourcePlane_Path", "{0}")
            src_index = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__SourcePlane_Index", 0)

            SourcePlane = ghc.TreeItem(src_tree, src_path, src_index, False)

            # -----------------------------
            # TargetPlane：vsg4_TreeItem_ListItem_PlaneOrigin_Transform1
            # -----------------------------
            TreeItem_Tree = getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None)
            if TreeItem_Tree is None:
                TreeItem_Tree = []

            ListItem_List = getattr(self, "ShuaTouInLineWManGong1__Skew_Point_C", None)
            if ListItem_List is None:
                ListItem_List = []

            TreeItem_Path = self.AllDict0.get("vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path", "{0}")
            TreeItem_Index = self.AllDict0.get("vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Index", 0)

            ListItem_Index = self.AllDict0.get("vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__ListItem_Index", 0)

            Transform_Transform = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            try:
                if isinstance(Transform_Transform, ght.GH_Transform):
                    Transform_Transform = Transform_Transform.Value
            except Exception:
                pass
            if Transform_Transform is None:
                Transform_Transform = rg.Transform.Identity

            helper = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()
            TargetPlane = helper.solve(
                TreeItem_Tree,
                TreeItem_Path,
                TreeItem_Index,
                False,  # TreeItem_Wrap
                ListItem_List,
                ListItem_Index,
                False,  # ListItem_Wrap
                Transform_Transform
            )

            # 记录 helper 输出（便于调试/输出端）
            self.vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__FlipX", False)
            FlipY = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__FlipY", False)
            FlipZ = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__FlipZ", False)

            MoveX = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__MoveX", 0)
            MoveY = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg4_ga__YouAngInLineWJiaoShuaTou__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )
            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg4_ga__YouAngInLineWJiaoShuaTou__SourceOut = SourceOut
            self.vsg4_ga__YouAngInLineWJiaoShuaTou__TargetOut = TargetOut
            self.vsg4_ga__YouAngInLineWJiaoShuaTou__TransformOut = TransformOut
            self.vsg4_ga__YouAngInLineWJiaoShuaTou__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step 6-7 完成：vsg4_ga__YouAngInLineWJiaoShuaTou")
        except Exception as e:
            self.LogLines.append("Step 6-7 失败：vsg4_ga__YouAngInLineWJiaoShuaTou -> {}".format(e))

    def step7_1_vsg5_ga__JIAOHU_DOU1(self):
        """
        Step7-1：叠次-5：交互枓-1
        包括组件：
        - vsg5_TreeItem_ListItem_PlaneOrigin_Transform1
        - vsg5_ga__JIAOHU_DOU1

        * Geo
          为 JIAOHU_DOU__CutTimbers

        * SourcePlane
          为 JIAOHU_DOU__FacePlaneList，索引值为 vsg5_ga__JIAOHU_DOU1__SourcePlane 的对象。

        * TargetPlane
          为 vsg5_TreeItem_ListItem_PlaneOrigin_Transform1 计算结果，其中：
            TreeItem_Tree = ShuaTouInLineWManGong1__Skew_Planes
            ListItem_List = ShuaTouInLineWManGong1__Skew_Point_C
            TreeItem_Path = vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path
            TreeItem_Index= vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Index
            ListItem_Index= vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__ListItem_Index
            Transform_Transform = vsg4_ga__ShuaTouInLineWManGong1__TransformOut

        * RotateDeg
          = vsg5_ga__JIAOHU_DOU1__RotateDeg

        * MoveZ
          = vsg5_ga__JIAOHU_DOU2__MoveZ

        注意：
        - 严格按原 ghpy 组件：vsg5_ga__JIAOHU_DOU1 使用 FT_GeoAligner.align，输出仅 SourceOut/TargetOut/MovedGeo。
        - 若数据库中不存在某键，则按默认值（Rotate=0 / Flip=False / Move=0）处理。
        """
        try:
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            import Rhino.Geometry as rg
            from yingzao.ancientArchi import FT_GeoAligner
            from yingzao.ancientArchi import GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "JIAOHU_DOU__CutTimbers", None)
            if geo is None:
                geo = []
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：FacePlaneList[ idx ]
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "JIAOHU_DOU__FacePlaneList", None))
            sp_idx = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__SourcePlane", 0)

            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：vsg5_TreeItem_ListItem_PlaneOrigin_Transform1
            # -----------------------------
            TreeItem_Tree = getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None)
            if TreeItem_Tree is None:
                TreeItem_Tree = []

            ListItem_List = getattr(self, "ShuaTouInLineWManGong1__Skew_Point_C", None)
            if ListItem_List is None:
                ListItem_List = []

            TreeItem_Path = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path", "{0}")
            TreeItem_Index = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Index", 0)
            ListItem_Index = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__ListItem_Index", 0)

            Transform_Transform = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            try:
                if isinstance(Transform_Transform, ght.GH_Transform):
                    Transform_Transform = Transform_Transform.Value
            except Exception:
                pass
            if Transform_Transform is None:
                Transform_Transform = rg.Transform.Identity

            helper = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()
            TargetPlane = helper.solve(
                TreeItem_Tree,
                TreeItem_Path,
                TreeItem_Index,
                False,  # TreeItem_Wrap
                ListItem_List,
                ListItem_Index,
                False,  # ListItem_Wrap
                Transform_Transform
            )

            self.vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__JIAOHU_DOU1__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__MoveZ", 0)

            # -----------------------------
            # FT_GeoAligner.align（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, MovedGeo = FT_GeoAligner.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg5_ga__JIAOHU_DOU1__SourceOut = SourceOut
            self.vsg5_ga__JIAOHU_DOU1__TargetOut = TargetOut
            self.vsg5_ga__JIAOHU_DOU1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step7-1 完成：vsg5_ga__JIAOHU_DOU1")
        except Exception as e:
            self.LogLines.append("Step7-1 失败：vsg5_ga__JIAOHU_DOU1 -> {}".format(e))

    def step7_2_vsg5_ga__JIAOHU_DOU2(self):
        """
        Step7-2：叠次-5：交互枓-2
        包括组件：
        - vsg5_TreeItem_ListItem_PlaneOrigin_Transform2
        - vsg5_ga__JIAOHU_DOU2

        * Geo
          为 JIAOHU_DOU__CutTimbers

        * SourcePlane
          为 JIAOHU_DOU__FacePlaneList，索引值为 vsg5_ga__JIAOHU_DOU2__SourcePlane 的对象。

        * TargetPlane
          为 vsg5_TreeItem_ListItem_PlaneOrigin_Transform2 计算结果，其中：
            TreeItem_Tree = ShuaTouInLineWManGong2__Skew_Planes
            ListItem_List = ShuaTouInLineWManGong2__Skew_Point_C
            TreeItem_Path = vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Path
            TreeItem_Index= vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index
            ListItem_Index= vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index
            Transform_Transform = vsg4_ga__ShuaTouInLineWManGong2__TransformOut

        * RotateDeg
          = vsg5_ga__JIAOHU_DOU2__RotateDeg

        * MoveZ
          = vsg5_ga__JIAOHU_DOU2__MoveZ

        注意：
        - 严格按原 ghpy 组件：vsg5_ga__JIAOHU_DOU2 使用 FT_GeoAligner.align，输出仅 SourceOut/TargetOut/MovedGeo。
        - 若数据库中不存在某键，则按默认值（Rotate=0 / Flip=False / Move=0）处理。
        """
        try:
            import Grasshopper.Kernel.Types as ght
            import Rhino.Geometry as rg
            from yingzao.ancientArchi import FT_GeoAligner
            from yingzao.ancientArchi import GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "JIAOHU_DOU__CutTimbers", None)
            if geo is None:
                geo = []
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：FacePlaneList[ idx ]
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "JIAOHU_DOU__FacePlaneList", None))
            sp_idx = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__SourcePlane", 0)

            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：vsg5_TreeItem_ListItem_PlaneOrigin_Transform2
            # -----------------------------
            TreeItem_Tree = getattr(self, "ShuaTouInLineWManGong2__Skew_Planes", None)
            if TreeItem_Tree is None:
                TreeItem_Tree = []

            ListItem_List = getattr(self, "ShuaTouInLineWManGong2__Skew_Point_C", None)
            if ListItem_List is None:
                ListItem_List = []

            TreeItem_Path = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Path", "{0}")
            TreeItem_Index = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index", 0)
            ListItem_Index = self.AllDict0.get("vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index", 0)

            Transform_Transform = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)
            try:
                if isinstance(Transform_Transform, ght.GH_Transform):
                    Transform_Transform = Transform_Transform.Value
            except Exception:
                pass
            if Transform_Transform is None:
                Transform_Transform = rg.Transform.Identity

            helper = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()
            TargetPlane = helper.solve(
                TreeItem_Tree,
                TreeItem_Path,
                TreeItem_Index,
                False,  # TreeItem_Wrap
                ListItem_List,
                ListItem_Index,
                False,  # ListItem_Wrap
                Transform_Transform
            )

            self.vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__MoveZ", 0)

            # -----------------------------
            # FT_GeoAligner.align（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, MovedGeo = FT_GeoAligner.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg5_ga__JIAOHU_DOU2__SourceOut = SourceOut
            self.vsg5_ga__JIAOHU_DOU2__TargetOut = TargetOut
            self.vsg5_ga__JIAOHU_DOU2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step7-2 完成：vsg5_ga__JIAOHU_DOU2")
        except Exception as e:
            self.LogLines.append("Step7-2 失败：vsg5_ga__JIAOHU_DOU2 -> {}".format(e))

    def step7_3_vsg5_PlaneFromLists1(self):
        """
        Step7-3（组件1）：叠次-5：vsg5_PlaneFromLists1

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ShuaTouInLineWManGong1__EdgeMidPoints
        - BasePlanes   = ShuaTouInLineWManGong1__Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists1__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists1__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists1__Wrap']，默认 True

        输出写入：
        - self.vsg5_PlaneFromLists1__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "ShuaTouInLineWManGong1__EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "ShuaTouInLineWManGong1__Corner0Planes", None))

            idx_origin = self.AllDict0.get("vsg5_PlaneFromLists1__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg5_PlaneFromLists1__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists1__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg5_PlaneFromLists1__BasePlane = BasePlane
            self.vsg5_PlaneFromLists1__OriginPoint = OriginPoint
            self.vsg5_PlaneFromLists1__ResultPlane = ResultPlane
            self.vsg5_PlaneFromLists1__Log = Log

            self.LogLines.append("Step7-3 完成：vsg5_PlaneFromLists1")
        except Exception as e:
            self.LogLines.append("Step7-3 失败：vsg5_PlaneFromLists1 -> {}".format(e))

    def step7_3_vsg5_ga__SAN_DOU1(self):
        """
        Step7-3（组件2）：叠次-5：散枓-1（vsg5_ga__SAN_DOU1）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists1.ResultPlane,
                                   Transform = vsg4_ga__ShuaTouInLineWManGong1.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU2__MoveX']（若不存在则回退 vsg5_ga__SAN_DOU1__MoveX）
        - MoveZ       = AllDict0['vsg5_ga__SAN_DOU2__MoveZ']（若不存在则回退 vsg5_ga__SAN_DOU1__MoveZ）
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY：若库中无对应键，则按原组件默认（0 / False / 0）

        输出写入：
        - self.vsg5_ga__SAN_DOU1__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import Rhino.Geometry as rg
            import Grasshopper.Kernel.Types as ght
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "SAN_DOU__CutTimbers", None)
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：FacePlaneList[ idx ]
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))
            sp_idx = self.AllDict0.get("vsg5_ga__SAN_DOU1__SourcePlane", 0)

            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists1.ResultPlane , vsg4_ga__ShuaTouInLineWManGong1.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists1__ResultPlane", None)

            xfm = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            try:
                TargetPlane = ghc.Transform(base_plane, xfm)
            except Exception:
                # 兜底：用 RhinoCommon 变换 Plane
                def _xfm_plane(pl):
                    if pl is None:
                        return None
                    try:
                        p2 = rg.Plane(pl)
                        p2.Transform(xfm)
                        return p2
                    except Exception:
                        try:
                            pl.Transform(xfm)
                            return pl
                        except Exception:
                            return pl

                if isinstance(base_plane, (list, tuple)):
                    TargetPlane = [_xfm_plane(p) for p in base_plane]
                else:
                    TargetPlane = _xfm_plane(base_plane)

            self.vsg5_ga__SAN_DOU1__TargetPlane = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move（严格按原组件默认）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU1__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU1__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU1__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU1__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU2__MoveX", None)
            if MoveX is None:
                MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU1__MoveX", 0)

            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU1__MoveY", 0)

            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU1__MoveZ", None)
            if MoveZ is None:
                MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU1__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=bool(FlipX),
                flip_y=bool(FlipY),
                flip_z=bool(FlipZ),
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg5_ga__SAN_DOU1__SourceOut = SourceOut
            self.vsg5_ga__SAN_DOU1__TargetOut = TargetOut
            self.vsg5_ga__SAN_DOU1__TransformOut = TransformOut
            self.vsg5_ga__SAN_DOU1__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step7-3 完成：vsg5_ga__SAN_DOU1")
        except Exception as e:
            self.LogLines.append("Step7-3 失败：vsg5_ga__SAN_DOU1 -> {}".format(e))

    def step7_4_vsg5_PlaneFromLists2(self):
        """
        Step7-4（组件1）：叠次-5：vsg5_PlaneFromLists2

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = ShuaTouInLineWManGong2__EdgeMidPoints
        - BasePlanes   = ShuaTouInLineWManGong2__Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists2__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists2__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists2__Wrap']，默认 True

        输出写入：
        - self.vsg5_PlaneFromLists2__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "ShuaTouInLineWManGong2__EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "ShuaTouInLineWManGong2__Corner0Planes", None))

            idx_origin = self.AllDict0.get("vsg5_PlaneFromLists2__IndexOrigin", 0)
            idx_plane = self.AllDict0.get("vsg5_PlaneFromLists2__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists2__Wrap", True)

            builder = FTPlaneFromLists(wrap=Wrap)
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                OriginPoints,
                BasePlanes,
                idx_origin,
                idx_plane
            )

            self.vsg5_PlaneFromLists2__BasePlane = BasePlane
            self.vsg5_PlaneFromLists2__OriginPoint = OriginPoint
            self.vsg5_PlaneFromLists2__ResultPlane = ResultPlane
            self.vsg5_PlaneFromLists2__Log = Log

            self.LogLines.append("Step7-4 完成：vsg5_PlaneFromLists2")
        except Exception as e:
            self.LogLines.append("Step7-4 失败：vsg5_PlaneFromLists2 -> {}".format(e))

    def step7_4_vsg5_ga__SAN_DOU2(self):
        """
        Step7-4（组件2）：叠次-5：散枓-2（vsg5_ga__SAN_DOU2）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
          （注意：按说明用 vsg5_ga__SAN_DOU1__SourcePlane 作为索引键）
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists2.ResultPlane,
                                   Transform = vsg4_ga__ShuaTouInLineWManGong2.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU2__MoveX']
        - MoveZ       = AllDict0['vsg5_ga__SAN_DOU2__MoveZ']
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY：若库中无对应键，则按原组件默认（0 / False / 0）

        输出写入：
        - self.vsg5_ga__SAN_DOU2__SourceOut / TargetOut / TransformOut / MovedGeo
        """
        try:
            import Rhino.Geometry as rg
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "SAN_DOU__CutTimbers", None)

            # -----------------------------
            # SourcePlane：从 SAN_DOU__FacePlaneList 按索引取
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))

            def _pick_plane(i):
                if not face_planes:
                    return None
                try:
                    ii = int(i)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1
                return face_planes[ii]

            sp_idx = self.AllDict0.get("vsg5_ga__SAN_DOU1__SourcePlane", 0)
            SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists2.ResultPlane , vsg4_ga__ShuaTouInLineWManGong2.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists2__ResultPlane", None)

            xfm = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            try:
                TargetPlane = ghc.Transform(base_plane, xfm)
            except Exception:
                # 兜底：用 RhinoCommon 变换 Plane
                def _xfm_plane(pl):
                    if pl is None:
                        return None
                    try:
                        p2 = rg.Plane(pl)
                        p2.Transform(xfm)
                        return p2
                    except Exception:
                        try:
                            pl.Transform(xfm)
                            return pl
                        except Exception:
                            return pl

                if isinstance(base_plane, (list, tuple)):
                    TargetPlane = [_xfm_plane(p) for p in base_plane]
                else:
                    TargetPlane = _xfm_plane(base_plane)

            self.vsg5_ga__SAN_DOU2__TargetPlane = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move（严格按原组件默认）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU2__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU2__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU2__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU2__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU2__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU2__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU2__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（与原 ghpy 组件一致）
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=bool(FlipX),
                flip_y=bool(FlipY),
                flip_z=bool(FlipZ),
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg5_ga__SAN_DOU2__SourceOut = SourceOut
            self.vsg5_ga__SAN_DOU2__TargetOut = TargetOut
            self.vsg5_ga__SAN_DOU2__TransformOut = TransformOut
            self.vsg5_ga__SAN_DOU2__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step7-4 完成：vsg5_ga__SAN_DOU2")
        except Exception as e:
            self.LogLines.append("Step7-4 失败：vsg5_ga__SAN_DOU2 -> {}".format(e))

    def step7_5_vsg5_PlaneFromLists3(self):
        """
        Step7-5（组件1）：叠次-5：vsg5_PlaneFromLists3

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = GuaZiGongInLineWLingGong1__EdgeMidPoints
        - BasePlanes   = GuaZiGongInLineWLingGong1__Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists3__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists3__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists3__Wrap']，默认 True

        关键：实现 GH 风格广播对齐
        - 当 IndexOrigin / IndexPlane 为列表且长度不一致时：按“短列表循环”方式广播对齐；
        - 逐项调用 FTPlaneFromLists.build_plane()，输出对应长度的结果列表。

        输出写入：
        - self.vsg5_PlaneFromLists3__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "GuaZiGongInLineWLingGong1__EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "GuaZiGongInLineWLingGong1__Corner0Planes", None))

            idx_origin_spec = self.AllDict0.get("vsg5_PlaneFromLists3__IndexOrigin", 0)
            idx_plane_spec = self.AllDict0.get("vsg5_PlaneFromLists3__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists3__Wrap", True)

            # ---- GH 风格广播：短列表循环对齐 ----
            def _as_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            idx_origin_list = _as_list(idx_origin_spec)
            idx_plane_list = _as_list(idx_plane_spec)

            # 广播长度（至少为 1）
            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _pick(lst, i):
                # 空列表兜底：返回 0（尽量不抛错）
                if not lst:
                    return 0
                return lst[i % len(lst)]

            builder = FTPlaneFromLists(wrap=Wrap)

            out_baseplanes = []
            out_originpts = []
            out_resultplanes = []
            out_logs = []

            for i in range(n):
                idx_o = _pick(idx_origin_list, i)
                idx_p = _pick(idx_plane_list, i)

                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o,
                    idx_p
                )

                out_baseplanes.append(BasePlane)
                out_originpts.append(OriginPoint)
                out_resultplanes.append(ResultPlane)
                out_logs.append(Log)

            # 若未发生广播（n==1 且两者均为标量），保持单值输出；否则输出列表
            is_broadcast = (
                    (isinstance(idx_origin_spec, (list, tuple)) and len(idx_origin_list) != 1) or
                    (isinstance(idx_plane_spec, (list, tuple)) and len(idx_plane_list) != 1)
            )

            self.vsg5_PlaneFromLists3__BasePlane = out_baseplanes if is_broadcast else out_baseplanes[0]
            self.vsg5_PlaneFromLists3__OriginPoint = out_originpts if is_broadcast else out_originpts[0]
            self.vsg5_PlaneFromLists3__ResultPlane = out_resultplanes if is_broadcast else out_resultplanes[0]
            self.vsg5_PlaneFromLists3__Log = out_logs if is_broadcast else out_logs[0]

            self.LogLines.append("Step7-5 完成：vsg5_PlaneFromLists3（广播长度 n={}）".format(n))
        except Exception as e:
            self.LogLines.append("Step7-5 失败：vsg5_PlaneFromLists3 -> {}".format(e))

    def step7_5_vsg5_ga__SAN_DOU3(self):
        """
        Step7-5（组件2）：叠次-5：散枓-3（vsg5_ga__SAN_DOU3）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
          （注意：按说明用 vsg5_ga__SAN_DOU1__SourcePlane 作为索引键）
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists3.ResultPlane,
                                   Transform = vsg4_ga__GuaZiGongInLineWLingGong1.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU3__MoveX']
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY / MoveZ：若库中无对应键，则按原组件默认（0 / False / 0）

        输出写入：
        - self.vsg5_ga__SAN_DOU3__SourceOut / TargetOut / TransformOut / MovedGeo
        """
        try:
            import Rhino.Geometry as rg
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "SAN_DOU__CutTimbers", None)

            # -----------------------------
            # SourcePlane：从 SAN_DOU__FacePlaneList 按索引取
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))

            def _pick_plane(i):
                if not face_planes:
                    return None
                try:
                    ii = int(i)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1
                return face_planes[ii]

            sp_idx = self.AllDict0.get("vsg5_ga__SAN_DOU1__SourcePlane", 0)
            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists3.ResultPlane , vsg4_ga__GuaZiGongInLineWLingGong1.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists3__ResultPlane", None)

            xfm = getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut", None)

            # 兼容 GH_Transform / 列表[GH_Transform] / Rhino Transform / 列表[Transform]
            def _unwrap_xfm(x):
                try:
                    if isinstance(x, ght.GH_Transform):
                        return x.Value
                except Exception:
                    pass
                return x

            if isinstance(xfm, (list, tuple)):
                xfm = [_unwrap_xfm(x) for x in xfm]
            else:
                xfm = _unwrap_xfm(xfm)

            if xfm is None:
                xfm = rg.Transform.Identity

            # 按 GH 广播：base_plane 与 xfm 任一为列表时，短列表循环对齐逐项 Transform
            try:
                if isinstance(base_plane, (list, tuple)) or isinstance(xfm, (list, tuple)):
                    n_tp, _get_tp = _broadcast_cycle(base_plane, xfm)
                    TargetPlane = []
                    for i in range(n_tp):
                        pl_i = _get_tp(base_plane, i)
                        xfm_i = _get_tp(xfm, i) or rg.Transform.Identity
                        try:
                            TargetPlane.append(ghc.Transform(pl_i, xfm_i))
                        except Exception:
                            # 兜底：RhinoCommon 变换 Plane
                            try:
                                p2 = rg.Plane(pl_i)
                                p2.Transform(xfm_i)
                                TargetPlane.append(p2)
                            except Exception:
                                TargetPlane.append(pl_i)
                else:
                    TargetPlane = ghc.Transform(base_plane, xfm)
            except Exception:
                # 兜底：用 RhinoCommon 变换 Plane
                def _xfm_plane(pl, t):
                    if pl is None:
                        return None
                    try:
                        p2 = rg.Plane(pl)
                        p2.Transform(t)
                        return p2
                    except Exception:
                        try:
                            pl.Transform(t)
                            return pl
                        except Exception:
                            return pl

                if isinstance(base_plane, (list, tuple)) or isinstance(xfm, (list, tuple)):
                    n_tp, _get_tp = _broadcast_cycle(base_plane, xfm)
                    TargetPlane = [_xfm_plane(_get_tp(base_plane, i), _get_tp(xfm, i) or rg.Transform.Identity) for i in
                                   range(n_tp)]
                else:
                    TargetPlane = _xfm_plane(base_plane, xfm)

            self.vsg5_ga__SAN_DOU3__TargetPlane = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move（严格按原组件默认）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU3__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU3__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU3__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU3__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU3__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU3__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU3__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（GH 广播对齐 + 循环逐项计算）
            # -----------------------------
            # - 取参与广播的输入中最大长度 n
            # - 标量重复；短列表循环
            # - 逐项调用 GeoAligner_xfm.align
            # - 输出端嵌套统一展平
            n, _get = _broadcast_cycle(
                geo, SourcePlane, TargetPlane,
                RotateDeg, FlipX, FlipY, FlipZ,
                MoveX, MoveY, MoveZ
            )

            _src_out_list = []
            _tgt_out_list = []
            _xfm_out_list = []
            _moved_geo_list = []

            for i in range(n):
                gi = _get(geo, i)
                spi = _get(SourcePlane, i)
                tpi = _get(TargetPlane, i)
                rdi = _get(RotateDeg, i)
                fxi = _get(FlipX, i)
                fyi = _get(FlipY, i)
                fzi = _get(FlipZ, i)
                mxi = _get(MoveX, i)
                myi = _get(MoveY, i)
                mzi = _get(MoveZ, i)

                SourceOut_i, TargetOut_i, TransformOut_i, MovedGeo_i = GeoAligner_xfm.align(
                    gi,
                    spi,
                    tpi,
                    rotate_deg=rdi,
                    flip_x=bool(fxi),
                    flip_y=bool(fyi),
                    flip_z=bool(fzi),
                    move_x=mxi,
                    move_y=myi,
                    move_z=mzi,
                )

                _src_out_list.append(SourceOut_i)
                _tgt_out_list.append(TargetOut_i)
                _xfm_out_list.append(TransformOut_i)
                _moved_geo_list.append(MovedGeo_i)

            # TransformOut：逐项包装 GH_Transform（保持原组件一致）
            _xfm_out_list = [ght.GH_Transform(x) if x is not None else None for x in _xfm_out_list]

            # -----------------------------
            # 输出写入（完全展平）
            # -----------------------------
            self.vsg5_ga__SAN_DOU3__SourceOut = flatten_any(_src_out_list) if n > 1 else _src_out_list[0]
            self.vsg5_ga__SAN_DOU3__TargetOut = flatten_any(_tgt_out_list) if n > 1 else _tgt_out_list[0]
            self.vsg5_ga__SAN_DOU3__TransformOut = _xfm_out_list if n > 1 else _xfm_out_list[0]
            self.vsg5_ga__SAN_DOU3__MovedGeo = flatten_any(_moved_geo_list)

            self.LogLines.append("Step7-5 完成：vsg5_ga__SAN_DOU3")
        except Exception as e:
            self.LogLines.append("Step7-5 失败：vsg5_ga__SAN_DOU3 -> {}".format(e))

    def step7_6_vsg5_PlaneFromLists4(self):
        """
        Step7-6（组件1）：叠次-5：vsg5_PlaneFromLists4

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = GuaZiGongInLineWLingGong2__EdgeMidPoints
        - BasePlanes   = GuaZiGongInLineWLingGong2__Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists4__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists4__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists4__Wrap']，默认 True

        关键：实现 GH 风格广播对齐
        - 当 IndexOrigin / IndexPlane 为列表且长度不一致时：按“短列表循环”方式广播对齐；
        - 逐项调用 FTPlaneFromLists.build_plane()，输出对应长度的结果列表。

        输出写入：
        - self.vsg5_PlaneFromLists4__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "GuaZiGongInLineWLingGong2__EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "GuaZiGongInLineWLingGong2__Corner0Planes", None))

            idx_origin_spec = self.AllDict0.get("vsg5_PlaneFromLists4__IndexOrigin", 0)
            idx_plane_spec = self.AllDict0.get("vsg5_PlaneFromLists4__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists4__Wrap", True)

            def _as_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            idx_origin_list = _as_list(idx_origin_spec)
            idx_plane_list = _as_list(idx_plane_spec)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _pick(lst, i):
                if not lst:
                    return 0
                return lst[i % len(lst)]

            builder = FTPlaneFromLists(wrap=Wrap)

            out_baseplanes = []
            out_originpts = []
            out_resultplanes = []
            out_logs = []

            for i in range(n):
                idx_o = _pick(idx_origin_list, i)
                idx_p = _pick(idx_plane_list, i)

                BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o,
                    idx_p
                )

                out_baseplanes.append(BasePlane)
                out_originpts.append(OriginPoint)
                out_resultplanes.append(ResultPlane)
                out_logs.append(Log)

            is_broadcast = (
                    (isinstance(idx_origin_spec, (list, tuple)) and len(idx_origin_list) != 1) or
                    (isinstance(idx_plane_spec, (list, tuple)) and len(idx_plane_list) != 1)
            )

            self.vsg5_PlaneFromLists4__BasePlane = out_baseplanes if is_broadcast else out_baseplanes[0]
            self.vsg5_PlaneFromLists4__OriginPoint = out_originpts if is_broadcast else out_originpts[0]
            self.vsg5_PlaneFromLists4__ResultPlane = out_resultplanes if is_broadcast else out_resultplanes[0]
            self.vsg5_PlaneFromLists4__Log = out_logs if is_broadcast else out_logs[0]

            self.LogLines.append("Step7-6 完成：vsg5_PlaneFromLists4（广播长度 n={}）".format(n))
        except Exception as e:
            self.LogLines.append("Step7-6 失败：vsg5_PlaneFromLists4 -> {}".format(e))

    def step7_6_vsg5_ga__SAN_DOU4(self):
        """
        Step7-6（组件2）：叠次-5：散枓-4（vsg5_ga__SAN_DOU4）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists4.ResultPlane,
                                Transform = vsg4_ga__GuaZiGongInLineWLingGong2.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU4__MoveX']
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY / MoveZ：若库中无对应键，则按原组件默认（0 / False / 0）

        说明：
        1) 操作对象为 Geo；
        2) 若 TargetPlane / MoveX 等输入端为列表：按 GH 广播对齐（短列表循环）逐项计算；

        输出写入：
        - self.vsg5_ga__SAN_DOU4__SourceOut / TargetOut / TransformOut / MovedGeo
        """
        try:
            import Rhino.Geometry as rg
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import GeoAligner_xfm

            geo = getattr(self, "SAN_DOU__CutTimbers", None)

            # -----------------------------
            # SourcePlane：从 SAN_DOU__FacePlaneList 按索引取
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))

            def _pick_plane(i):
                if not face_planes:
                    return None
                try:
                    ii = int(i)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1
                return face_planes[ii]

            sp_idx = self.AllDict0.get("vsg5_ga__SAN_DOU1__SourcePlane", 0)
            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists4.ResultPlane , vsg4_ga__GuaZiGongInLineWLingGong2.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists4__ResultPlane", None)
            xfm = getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut", None)

            def _unwrap_xfm(x):
                try:
                    if isinstance(x, ght.GH_Transform):
                        return x.Value
                except Exception:
                    pass
                return x

            if isinstance(xfm, (list, tuple)):
                xfm = [_unwrap_xfm(x) for x in xfm]
            else:
                xfm = _unwrap_xfm(xfm)

            if xfm is None:
                xfm = rg.Transform.Identity

            try:
                if isinstance(base_plane, (list, tuple)) or isinstance(xfm, (list, tuple)):
                    n_tp, _get_tp = _broadcast_cycle(base_plane, xfm)
                    TargetPlane = []
                    for i in range(n_tp):
                        pl_i = _get_tp(base_plane, i)
                        xfm_i = _get_tp(xfm, i) or rg.Transform.Identity
                        try:
                            TargetPlane.append(ghc.Transform(pl_i, xfm_i))
                        except Exception:
                            try:
                                p2 = rg.Plane(pl_i)
                                p2.Transform(xfm_i)
                                TargetPlane.append(p2)
                            except Exception:
                                TargetPlane.append(pl_i)
                else:
                    TargetPlane = ghc.Transform(base_plane, xfm)
            except Exception:
                def _xfm_plane(pl, t):
                    if pl is None:
                        return None
                    try:
                        p2 = rg.Plane(pl)
                        p2.Transform(t)
                        return p2
                    except Exception:
                        try:
                            pl.Transform(t)
                            return pl
                        except Exception:
                            return pl

                if isinstance(base_plane, (list, tuple)) or isinstance(xfm, (list, tuple)):
                    n_tp, _get_tp = _broadcast_cycle(base_plane, xfm)
                    TargetPlane = [_xfm_plane(_get_tp(base_plane, i), _get_tp(xfm, i) or rg.Transform.Identity) for i in
                                   range(n_tp)]
                else:
                    TargetPlane = _xfm_plane(base_plane, xfm)

            self.vsg5_ga__SAN_DOU4__TargetPlane = TargetPlane

            # -----------------------------
            # Rotate / Flip / Move（严格按原组件默认）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU4__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU4__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU4__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU4__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU4__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU4__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU4__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（GH 广播对齐 + 循环逐项计算）
            # -----------------------------
            n, _get = _broadcast_cycle(
                geo, SourcePlane, TargetPlane,
                RotateDeg, FlipX, FlipY, FlipZ,
                MoveX, MoveY, MoveZ
            )

            _src_out_list = []
            _tgt_out_list = []
            _xfm_out_list = []
            _moved_geo_list = []

            for i in range(n):
                gi = _get(geo, i)
                spi = _get(SourcePlane, i)
                tpi = _get(TargetPlane, i)
                rdi = _get(RotateDeg, i)
                fxi = _get(FlipX, i)
                fyi = _get(FlipY, i)
                fzi = _get(FlipZ, i)
                mxi = _get(MoveX, i)
                myi = _get(MoveY, i)
                mzi = _get(MoveZ, i)

                SourceOut_i, TargetOut_i, TransformOut_i, MovedGeo_i = GeoAligner_xfm.align(
                    gi,
                    spi,
                    tpi,
                    rotate_deg=rdi,
                    flip_x=bool(fxi),
                    flip_y=bool(fyi),
                    flip_z=bool(fzi),
                    move_x=mxi,
                    move_y=myi,
                    move_z=mzi,
                )

                _src_out_list.append(SourceOut_i)
                _tgt_out_list.append(TargetOut_i)
                _xfm_out_list.append(TransformOut_i)
                _moved_geo_list.append(MovedGeo_i)

            _xfm_out_list = [ght.GH_Transform(x) if x is not None else None for x in _xfm_out_list]

            self.vsg5_ga__SAN_DOU4__SourceOut = flatten_any(_src_out_list) if n > 1 else _src_out_list[0]
            self.vsg5_ga__SAN_DOU4__TargetOut = flatten_any(_tgt_out_list) if n > 1 else _tgt_out_list[0]
            self.vsg5_ga__SAN_DOU4__TransformOut = _xfm_out_list if n > 1 else _xfm_out_list[0]
            self.vsg5_ga__SAN_DOU4__MovedGeo = flatten_any(_moved_geo_list)

            self.LogLines.append("Step7-6 完成：vsg5_ga__SAN_DOU4")
        except Exception as e:
            self.LogLines.append("Step7-6 失败：vsg5_ga__SAN_DOU4 -> {}".format(e))

    def step7_7_vsg5_PlaneFromLists5(self):
        """
        Step7-7（组件1）：叠次-5：vsg5_PlaneFromLists5

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints
        - BasePlanes   = LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists5__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists5__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists5__Wrap']，默认 True

        关键：实现 GH 风格广播对齐
        - 当 IndexOrigin / IndexPlane 为列表且长度不一致时：按“短列表循环”方式广播对齐；
        - 逐项调用 FTPlaneFromLists.build_plane()，输出对应长度的结果列表。

        输出写入：
        - self.vsg5_PlaneFromLists5__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes", None))

            idx_origin_spec = self.AllDict0.get("vsg5_PlaneFromLists5__IndexOrigin", 0)
            idx_plane_spec = self.AllDict0.get("vsg5_PlaneFromLists5__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists5__Wrap", True)

            def _as_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            idx_origin_list = _as_list(idx_origin_spec)
            idx_plane_list = _as_list(idx_plane_spec)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _pick(lst, i):
                if not lst:
                    return 0
                return lst[i % len(lst)] if len(lst) > 0 else 0

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_plane_out = []
            origin_point_out = []
            result_plane_out = []
            log_out = []

            for i in range(n):
                io = _pick(idx_origin_list, i)
                ip = _pick(idx_plane_list, i)

                bp, op, rp, lg = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    io,
                    ip
                )
                base_plane_out.append(bp)
                origin_point_out.append(op)
                result_plane_out.append(rp)
                log_out.append(lg)

            self.vsg5_PlaneFromLists5__BasePlane = base_plane_out if n > 1 else base_plane_out[0]
            self.vsg5_PlaneFromLists5__OriginPoint = origin_point_out if n > 1 else origin_point_out[0]
            self.vsg5_PlaneFromLists5__ResultPlane = result_plane_out if n > 1 else result_plane_out[0]
            self.vsg5_PlaneFromLists5__Log = log_out if n > 1 else log_out[0]

            self.LogLines.append("Step7-7 完成：vsg5_PlaneFromLists5")
        except Exception as e:
            self.LogLines.append("Step7-7 失败：vsg5_PlaneFromLists5 -> {}".format(e))

    def step7_7_vsg5_ga__SAN_DOU5(self):
        """
        Step7-7（组件2）：叠次-5：散枓-5（vsg5_ga__SAN_DOU5）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
                      （若该键不存在，则回退 AllDict0['vsg5_ga__SAN_DOU5__SourcePlane']）
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists5.ResultPlane,
                                   Transform = vsg4_ga__LingGongInLineWXiaoGongTou2.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU5__MoveX']
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY / MoveZ：若库中无对应键，则按原组件默认（0 / False / 0）

        输出写入：
        - self.vsg5_ga__SAN_DOU5__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import Grasshopper.Kernel.Types as ght
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "SAN_DOU__CutTimbers", None)
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：FacePlaneList[ idx ]
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))
            sp_idx = self.AllDict0.get(
                "vsg5_ga__SAN_DOU1__SourcePlane",
                self.AllDict0.get("vsg5_ga__SAN_DOU5__SourcePlane", 0)
            )

            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists5.ResultPlane , vsg4_ga__LingGongInLineWXiaoGongTou2.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists5__ResultPlane", None)
            xfm = getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut", None)
            TargetPlane = ghc.Transform(base_plane, xfm)

            # -----------------------------
            # 其它参数（按原组件默认；允许从 DB 覆盖）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU5__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU5__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU5__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU5__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU5__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU5__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU5__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（GH 广播对齐 + 循环逐项计算）
            # -----------------------------
            n, _get = _broadcast_cycle(
                geo, SourcePlane, TargetPlane,
                RotateDeg, FlipX, FlipY, FlipZ,
                MoveX, MoveY, MoveZ
            )

            _src_out_list = []
            _tgt_out_list = []
            _xfm_out_list = []
            _moved_geo_list = []

            for i in range(n):
                gi = _get(geo, i)
                spi = _get(SourcePlane, i)
                tpi = _get(TargetPlane, i)
                rdi = _get(RotateDeg, i)
                fxi = _get(FlipX, i)
                fyi = _get(FlipY, i)
                fzi = _get(FlipZ, i)
                mxi = _get(MoveX, i)
                myi = _get(MoveY, i)
                mzi = _get(MoveZ, i)

                SourceOut_i, TargetOut_i, TransformOut_i, MovedGeo_i = GeoAligner_xfm.align(
                    gi,
                    spi,
                    tpi,
                    rotate_deg=rdi,
                    flip_x=bool(fxi),
                    flip_y=bool(fyi),
                    flip_z=bool(fzi),
                    move_x=mxi,
                    move_y=myi,
                    move_z=mzi,
                )

                _src_out_list.append(SourceOut_i)
                _tgt_out_list.append(TargetOut_i)
                _xfm_out_list.append(TransformOut_i)
                _moved_geo_list.append(MovedGeo_i)

            _xfm_out_list = [ght.GH_Transform(x) if x is not None else None for x in _xfm_out_list]

            self.vsg5_ga__SAN_DOU5__SourceOut = flatten_any(_src_out_list) if n > 1 else _src_out_list[0]
            self.vsg5_ga__SAN_DOU5__TargetOut = flatten_any(_tgt_out_list) if n > 1 else _tgt_out_list[0]
            self.vsg5_ga__SAN_DOU5__TransformOut = _xfm_out_list if n > 1 else _xfm_out_list[0]
            self.vsg5_ga__SAN_DOU5__MovedGeo = flatten_any(_moved_geo_list)

            self.LogLines.append("Step7-7 完成：vsg5_ga__SAN_DOU5")
        except Exception as e:
            self.LogLines.append("Step7-7 失败：vsg5_ga__SAN_DOU5 -> {}".format(e))

    def step7_8_vsg5_PlaneFromLists6(self):
        """
        Step7-8（组件1）：叠次-5：vsg5_PlaneFromLists6

        组件输入端（严格按你提供的说明复刻）：
        - OriginPoints = LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints
        - BasePlanes   = LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes
        - IndexOrigin  = AllDict0['vsg5_PlaneFromLists6__IndexOrigin']
        - IndexPlane   = AllDict0['vsg5_PlaneFromLists6__IndexPlane']
        - Wrap         = （可选）AllDict0['vsg5_PlaneFromLists6__Wrap']，默认 True

        关键：实现 GH 风格广播对齐
        - 当 IndexOrigin / IndexPlane 为列表且长度不一致时：按“短列表循环”方式广播对齐；
        - 逐项调用 FTPlaneFromLists.build_plane()，输出对应长度的结果列表。

        输出写入：
        - self.vsg5_PlaneFromLists6__BasePlane / OriginPoint / ResultPlane / Log
        """
        try:
            from yingzao.ancientArchi import FTPlaneFromLists

            OriginPoints = _ensure_list(getattr(self, "LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints", None))
            BasePlanes = _ensure_list(getattr(self, "LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes", None))

            idx_origin_spec = self.AllDict0.get("vsg5_PlaneFromLists6__IndexOrigin", 0)
            idx_plane_spec = self.AllDict0.get("vsg5_PlaneFromLists6__IndexPlane", 0)
            Wrap = self.AllDict0.get("vsg5_PlaneFromLists6__Wrap", True)

            def _as_list(x):
                if isinstance(x, (list, tuple)):
                    return list(x)
                return [x]

            idx_origin_list = _as_list(idx_origin_spec)
            idx_plane_list = _as_list(idx_plane_spec)

            n = max(len(idx_origin_list), len(idx_plane_list), 1)

            def _pick(lst, i):
                if not lst:
                    return 0
                return lst[i % len(lst)] if len(lst) > 0 else 0

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_plane_out = []
            origin_point_out = []
            result_plane_out = []
            log_out = []

            for i in range(n):
                io = _pick(idx_origin_list, i)
                ip = _pick(idx_plane_list, i)

                bp, op, rp, lg = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    io,
                    ip
                )
                base_plane_out.append(bp)
                origin_point_out.append(op)
                result_plane_out.append(rp)
                log_out.append(lg)

            self.vsg5_PlaneFromLists6__BasePlane = base_plane_out if n > 1 else base_plane_out[0]
            self.vsg5_PlaneFromLists6__OriginPoint = origin_point_out if n > 1 else origin_point_out[0]
            self.vsg5_PlaneFromLists6__ResultPlane = result_plane_out if n > 1 else result_plane_out[0]
            self.vsg5_PlaneFromLists6__Log = log_out if n > 1 else log_out[0]

            self.LogLines.append("Step7-8 完成：vsg5_PlaneFromLists6")
        except Exception as e:
            self.LogLines.append("Step7-8 失败：vsg5_PlaneFromLists6 -> {}".format(e))

    def step7_8_vsg5_ga__SAN_DOU6(self):
        """
        Step7-8（组件2）：叠次-5：散枓-6（vsg5_ga__SAN_DOU6）

        组件输入端（严格按你提供的说明复刻）：
        - Geo         = SAN_DOU__CutTimbers
        - SourcePlane = SAN_DOU__FacePlaneList[ AllDict0['vsg5_ga__SAN_DOU1__SourcePlane'] ]
                    （若该键不存在，则回退 AllDict0['vsg5_ga__SAN_DOU6__SourcePlane']）
        - TargetPlane = Transform( Geometry = vsg5_PlaneFromLists6.ResultPlane,
                                Transform = vsg4_ga__LingGongInLineWXiaoGongTou1.TransformOut )
        - MoveX       = AllDict0['vsg5_ga__SAN_DOU6__MoveX']
        - RotateDeg / FlipX / FlipY / FlipZ / MoveY / MoveZ：若库中无对应键，则按原组件默认（0 / False / 0）

        输出写入：
        - self.vsg5_ga__SAN_DOU6__SourceOut / TargetOut / TransformOut / MovedGeo
        并将 TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）。
        """
        try:
            import Grasshopper.Kernel.Types as ght
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo
            # -----------------------------
            geo = getattr(self, "SAN_DOU__CutTimbers", None)
            geo = flatten_any(geo)

            # -----------------------------
            # SourcePlane：FacePlaneList[ idx ]
            # -----------------------------
            face_planes = _ensure_list(getattr(self, "SAN_DOU__FacePlaneList", None))
            sp_idx = self.AllDict0.get(
                "vsg5_ga__SAN_DOU1__SourcePlane",
                self.AllDict0.get("vsg5_ga__SAN_DOU6__SourcePlane", 0)
            )

            def _pick_plane(idx_val):
                try:
                    ii = int(idx_val)
                except Exception:
                    ii = 0
                if ii < 0:
                    ii = 0
                if ii >= len(face_planes):
                    ii = len(face_planes) - 1 if len(face_planes) > 0 else 0
                return face_planes[ii] if len(face_planes) > 0 else None

            if isinstance(sp_idx, (list, tuple)):
                SourcePlane = [_pick_plane(i) for i in sp_idx]
            else:
                SourcePlane = _pick_plane(sp_idx)

            # -----------------------------
            # TargetPlane：Transform( vsg5_PlaneFromLists6.ResultPlane , vsg4_ga__LingGongInLineWXiaoGongTou1.TransformOut )
            # 注意：按要求使用 ghc.Transform
            # -----------------------------
            base_plane = getattr(self, "vsg5_PlaneFromLists6__ResultPlane", None)
            xfm = getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut", None)
            TargetPlane = ghc.Transform(base_plane, xfm)

            # -----------------------------
            # 其它参数（按原组件默认；允许从 DB 覆盖）
            # -----------------------------
            RotateDeg = self.AllDict0.get("vsg5_ga__SAN_DOU6__RotateDeg", 0)

            FlipX = self.AllDict0.get("vsg5_ga__SAN_DOU6__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__SAN_DOU6__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__SAN_DOU6__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__SAN_DOU6__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__SAN_DOU6__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__SAN_DOU6__MoveZ", 0)

            # -----------------------------
            # GeoAligner_xfm.align（GH 广播对齐 + 循环逐项计算）
            # -----------------------------
            n, _get = _broadcast_cycle(
                geo, SourcePlane, TargetPlane,
                RotateDeg, FlipX, FlipY, FlipZ,
                MoveX, MoveY, MoveZ
            )

            _src_out_list = []
            _tgt_out_list = []
            _xfm_out_list = []
            _moved_geo_list = []

            for i in range(n):
                gi = _get(geo, i)
                spi = _get(SourcePlane, i)
                tpi = _get(TargetPlane, i)
                rdi = _get(RotateDeg, i)
                fxi = _get(FlipX, i)
                fyi = _get(FlipY, i)
                fzi = _get(FlipZ, i)
                mxi = _get(MoveX, i)
                myi = _get(MoveY, i)
                mzi = _get(MoveZ, i)

                SourceOut_i, TargetOut_i, TransformOut_i, MovedGeo_i = GeoAligner_xfm.align(
                    gi,
                    spi,
                    tpi,
                    rotate_deg=rdi,
                    flip_x=bool(fxi),
                    flip_y=bool(fyi),
                    flip_z=bool(fzi),
                    move_x=mxi,
                    move_y=myi,
                    move_z=mzi,
                )

                _src_out_list.append(SourceOut_i)
                _tgt_out_list.append(TargetOut_i)
                _xfm_out_list.append(TransformOut_i)
                _moved_geo_list.append(MovedGeo_i)

            _xfm_out_list = [ght.GH_Transform(x) if x is not None else None for x in _xfm_out_list]

            self.vsg5_ga__SAN_DOU6__SourceOut = flatten_any(_src_out_list) if n > 1 else _src_out_list[0]
            self.vsg5_ga__SAN_DOU6__TargetOut = flatten_any(_tgt_out_list) if n > 1 else _tgt_out_list[0]
            self.vsg5_ga__SAN_DOU6__TransformOut = _xfm_out_list if n > 1 else _xfm_out_list[0]
            self.vsg5_ga__SAN_DOU6__MovedGeo = flatten_any(_moved_geo_list)

            self.LogLines.append("Step7-8 完成：vsg5_ga__SAN_DOU6")
        except Exception as e:
            self.LogLines.append("Step7-8 失败：vsg5_ga__SAN_DOU6 -> {}".format(e))

    def step7_9_vsg5_ga__PingPanDou(self):
        """
        Step7-9：叠次-5：平盤枓（vsg5_ga__PingPanDou）

        组件输入端（严格按你提供的说明复刻）：
        - Geo        = PingPanDou__CutTimbers
        - SourcePlane= PingPanDou__FacePlaneList
        - TargetPlane 串联步骤：
            1) Transform1:
               Geometry  = YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues
               Transform = YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut
            2) Plane Origin:
               Base   = YouAngInLineWJiaoShuaTou__Corner0Planes[ AllDict0['vsg5_ga__PingPanDou__TargetPlane_Geometry_Base'] ]
               Origin = Transform1 结果[ AllDict0['vsg5_ga__PingPanDou__TargetPlane_Geometry_Origin'] ]
            3) Transform2:
               Geometry  = Plane Origin 结果
               Transform = vsg4_ga__YouAngInLineWJiaoShuaTou.TransformOut
            4) Transform2 结果作为 TargetPlane

        - MoveX      = AllDict0['vsg5_ga__PingPanDou__MoveX']
        - RotateDeg  默认值：vsg4_ga__GuaZiGongInLineWLingGong1__RotateDeg
                    （若库中有 vsg5_ga__PingPanDou__RotateDeg 则以库为准）
        - FlipX/FlipY/FlipZ/MoveY/MoveZ：若库中无对应键，则按原组件默认（False/0）

        输出写入：
        - self.vsg5_ga__PingPanDou__SourceOut / TargetOut / TransformOut / MovedGeo
        - TransformOut 包装为 GH_Transform（与原 ghpy 组件一致）
        - 同时暴露 TargetPlane 串联中间结果，便于调试
        """
        try:
            import Grasshopper.Kernel.Types as ght
            import ghpythonlib.components as ghc
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # Geo / SourcePlane
            # -----------------------------
            geo = flatten_any(getattr(self, "PingPanDou__CutTimbers", None))
            SourcePlane_lst = getattr(self, "PingPanDou__FacePlaneList", None)
            SourcePlane = SourcePlane_lst[self.AllDict0.get("vsg5_ga__JIAOHU_DOU2__SourcePlane", 0)]

            # -----------------------------
            # TargetPlane：Transform1 -> PlaneOrigin -> Transform2
            # -----------------------------
            t1_geo = getattr(self, "YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues", None)
            t1_xfm = getattr(self, "YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut", None)
            t1_out = ghc.Transform(t1_geo, t1_xfm)
            self.vsg5_ga__PingPanDou__TargetPlane_Transform1 = t1_out

            base_planes = _ensure_list(getattr(self, "YouAngInLineWJiaoShuaTou__Corner0Planes", None))
            base_idx = self.AllDict0.get("vsg5_ga__PingPanDou__TargetPlane_Geometry_Base", 0)
            origin_idx = self.AllDict0.get("vsg5_ga__PingPanDou__TargetPlane_Geometry_Origin", 0)

            def _safe_idx(v, n):
                try:
                    i = int(v)
                except Exception:
                    i = 0
                if n <= 0:
                    return 0
                if i < 0:
                    i = 0
                if i >= n:
                    i = n - 1
                return i

            bp = base_planes[_safe_idx(base_idx, len(base_planes))] if len(base_planes) > 0 else None

            t1_list = _ensure_list(t1_out)
            op_lst = t1_list[_safe_idx(origin_idx, len(t1_list))] if len(t1_list) > 0 else None
            op = op_lst[self.AllDict0.get("vsg5_ga__PingPanDou__TargetPlane_Geometry_Origin", 0)]

            po_out = ghc.PlaneOrigin(bp, op)
            self.vsg5_ga__PingPanDou__TargetPlane_PlaneOrigin = po_out

            t2_xfm = getattr(self, "vsg4_ga__YouAngInLineWJiaoShuaTou__TransformOut", None)
            t2_out = ghc.Transform(po_out, t2_xfm)
            self.vsg5_ga__PingPanDou__TargetPlane_Transform2 = t2_out

            TargetPlane = t2_out

            # -----------------------------
            # Parameters（DB-driven）
            # -----------------------------
            RotateDeg = self.AllDict0.get(
                "vsg5_ga__PingPanDou__RotateDeg",
                getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong1__RotateDeg", 0)
            )
            FlipX = self.AllDict0.get("vsg5_ga__PingPanDou__FlipX", False)
            FlipY = self.AllDict0.get("vsg5_ga__PingPanDou__FlipY", False)
            FlipZ = self.AllDict0.get("vsg5_ga__PingPanDou__FlipZ", False)

            MoveX = self.AllDict0.get("vsg5_ga__PingPanDou__MoveX", 0)
            MoveY = self.AllDict0.get("vsg5_ga__PingPanDou__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg5_ga__PingPanDou__MoveZ", 0)

            # -----------------------------
            # Align
            # -----------------------------
            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            # 输出：TransformOut 包装 GH_Transform；其余强制 flatten，避免多层嵌套
            self.vsg5_ga__PingPanDou__SourceOut = flatten_any(SourceOut)
            self.vsg5_ga__PingPanDou__TargetOut = flatten_any(TargetOut)

            if isinstance(TransformOut, (list, tuple)):
                self.vsg5_ga__PingPanDou__TransformOut = [ght.GH_Transform(x) if x is not None else None for x in
                                                          TransformOut]
            else:
                self.vsg5_ga__PingPanDou__TransformOut = ght.GH_Transform(
                    TransformOut) if TransformOut is not None else None

            self.vsg5_ga__PingPanDou__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step7-9 完成：vsg5_ga__PingPanDou")
        except Exception as e:
            self.LogLines.append("Step7-9 失败：vsg5_ga__PingPanDou -> {}".format(e))

    def step8_1_vsg6_ga__Vase(self):
        """
        Step8-1：叠次-6：寳瓶（vsg6_ga__Vase）

        vsg6_ga__Vase 组件输入端（严格按你提供的说明复刻）：
        - Geo        = Vase__CutTimbers
        - SourcePlane= Vase__base_ref_plane
        - TargetPlane= Transform 计算结果：
            * Geometry  = PingPanDou__FacePlaneList[ AllDict0['vsg6_ga__Vase__TargetPlane_Geometry'] ]
            * Transform = vsg5_ga__PingPanDou.TransformOut
        注意：Transform 使用 ghc.Transform（import ghpythonlib.components as ghc）

        - RotateDeg  默认值：vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg

        输出写入：
        - self.vsg6_ga__Vase__SourceOut / TargetOut / MovedGeo
        - 同时暴露 TargetPlane Transform 中间结果：self.vsg6_ga__Vase__TargetPlane_Transform
        """
        try:
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            import Rhino.Geometry as rg
            from yingzao.ancientArchi import FT_GeoAligner

            # -----------------------------
            # Geo / SourcePlane
            # -----------------------------
            Geo = flatten_any(getattr(self, "Vase__CutTimbers", None))
            SourcePlane = getattr(self, "Vase__base_ref_plane", None)

            # -----------------------------
            # TargetPlane：Transform(PingPanDou__FacePlaneList[idx], vsg5_ga__PingPanDou__TransformOut)
            # -----------------------------
            face_planes = getattr(self, "PingPanDou__FacePlaneList", None)
            if face_planes is None:
                face_planes = []
            face_planes = _ensure_list(face_planes)

            tp_idx = self.AllDict0.get("vsg6_ga__Vase__TargetPlane_Geometry", 0)
            try:
                tp_idx = int(tp_idx)
            except Exception:
                tp_idx = 0
            if tp_idx < 0:
                tp_idx = 0
            if tp_idx >= len(face_planes) and len(face_planes) > 0:
                tp_idx = len(face_planes) - 1

            tgt_geo = face_planes[tp_idx] if len(face_planes) > 0 else None

            xfm = getattr(self, "vsg5_ga__PingPanDou__TransformOut", None)
            # 若是列表，取第一个（与 GH 常见用法一致）
            if isinstance(xfm, (list, tuple)):
                xfm = xfm[0] if len(xfm) > 0 else None
            # ghc.Transform 需要 Rhino.Geometry.Transform；若上游是 GH_Transform，则取其 Value
            try:
                if isinstance(xfm, ght.GH_Transform):
                    xfm = xfm.Value
            except Exception:
                pass
            if xfm is None:
                xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(tgt_geo, xfm) if (tgt_geo is not None and xfm is not None) else tgt_geo
            self.vsg6_ga__Vase__TargetPlane_Transform = TargetPlane

            # -----------------------------
            # Parameters（RotateDeg 默认值 + 其余按原组件默认）
            # -----------------------------
            RotateDeg = getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg", 0)

            FlipX = False
            FlipY = False
            FlipZ = False
            MoveX = 0
            MoveY = 0
            MoveZ = 0

            # -----------------------------
            # Align（严格按原组件：FT_GeoAligner.align）
            # -----------------------------
            SourceOut, TargetOut, MovedGeo = FT_GeoAligner.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            self.vsg6_ga__Vase__SourceOut = flatten_any(SourceOut)
            self.vsg6_ga__Vase__TargetOut = flatten_any(TargetOut)
            self.vsg6_ga__Vase__MovedGeo = flatten_any(MovedGeo)

            self.LogLines.append("Step8-1 完成：vsg6_ga__Vase")
        except Exception as e:
            self.LogLines.append("Step8-1 失败：vsg6_ga__Vase -> {}".format(e))

    def step8_2_vsg6_ga__OctagonPrism(self):
        """
        Step8-2：叠次-6：八角柱（OctagonPrism）
        包括组件：
        - vsg6_TreeItem_ListItem_PlaneOrigin_Transform1
        - vsg6_ga__OctagonPrism

        1) vsg6_TreeItem_ListItem_PlaneOrigin_Transform1
           TreeItem_Tree      = ShuaTouInLineWManGong1__Skew_Planes
           ListItem_List      = ShuaTouInLineWManGong1__Skew_Point_C
           Transform_Transform= vsg4_ga__ShuaTouInLineWManGong1 的 Transform（此处使用其 TransformOut）
           TreeItem_Path      = vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path
           TreeItem_Index     = vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index
           ListItem_Index     = vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index

        2) vsg6_ga__OctagonPrism
           Geo        = OctagonPrism__PrismBrep
           SourcePlane= OctagonPrism__RefPlane_BP
           TargetPlane= vsg6_TreeItem_ListItem_PlaneOrigin_Transform1 的 Transform_Geometry_Out
           FlipZ      = vsg6_ga__OctagonPrism__FlipZ

        注意：
        - 严格按你提供的原组件代码：
          * vsg6_TreeItem_ListItem_PlaneOrigin_Transform1：使用 GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC().solve
          * vsg6_ga__OctagonPrism：使用 GeoAligner_xfm.align，并将 TransformOut 包装为 ght.GH_Transform
        - 不使用 sticky（原组件若有 sticky，此处已移除且不兼容）。
        - 若输出为嵌套列表，统一 flatten_any 展平。
        """
        try:
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC
            from yingzao.ancientArchi import GeoAligner_xfm

            # -----------------------------
            # vsg6_TreeItem_ListItem_PlaneOrigin_Transform1
            # -----------------------------
            TreeItem_Tree = getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None)
            ListItem_List = getattr(self, "ShuaTouInLineWManGong1__Skew_Point_C", None)

            # Transform_Transform：来自 vsg4_ga__ShuaTouInLineWManGong1（此工程中已暴露为 TransformOut）
            Transform_Transform = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)

            TreeItem_Path = self.AllDict0.get("vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Path", "{0}")
            TreeItem_Index = self.AllDict0.get("vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__TreeItem_Index", 0)
            ListItem_Index = self.AllDict0.get("vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__ListItem_Index", 0)

            helper = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = helper.solve(
                TreeItem_Tree,
                TreeItem_Path,
                TreeItem_Index,
                False,  # TreeItem_Wrap
                ListItem_List,
                ListItem_Index,
                False,  # ListItem_Wrap
                Transform_Transform
            )
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = (
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out
            )

            # -----------------------------
            # vsg6_ga__OctagonPrism
            # -----------------------------
            Geo = getattr(self, "OctagonPrism__PrismBrep", None)
            SourcePlane = getattr(self, "OctagonPrism__RefPlane_BP", None)
            TargetPlane = vsg6_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out

            # 暴露 TargetPlane 中间结果（对齐 Step8-1 的端口习惯）
            self.vsg6_ga__OctagonPrism__TargetPlane_Transform = TargetPlane
            # 参数（若数据库无键则给默认）
            RotateDeg = self.AllDict0.get("vsg6_ga__OctagonPrism__RotateDeg", 0)
            FlipX = self.AllDict0.get("vsg6_ga__OctagonPrism__FlipX", False)
            FlipY = self.AllDict0.get("vsg6_ga__OctagonPrism__FlipY", False)
            FlipZ = self.AllDict0.get("vsg6_ga__OctagonPrism__FlipZ", False)
            MoveX = self.AllDict0.get("vsg6_ga__OctagonPrism__MoveX", 0)
            MoveY = self.AllDict0.get("vsg6_ga__OctagonPrism__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg6_ga__OctagonPrism__MoveZ", 0)

            print("((())))", Geo)

            vsg6_ga__OctagonPrism__SourceOut, vsg6_ga__OctagonPrism__TargetOut, vsg6_ga__OctagonPrism__TransformOut, vsg6_ga__OctagonPrism__MovedGeo = GeoAligner_xfm.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            print("+_", vsg6_ga__OctagonPrism__MovedGeo)

            # 输出：与原组件一致（TransformOut 包装为 GH_Transform）
            self.vsg6_ga__OctagonPrism__SourceOut = vsg6_ga__OctagonPrism__SourceOut
            self.vsg6_ga__OctagonPrism__TargetOut = vsg6_ga__OctagonPrism__TargetOut
            self.vsg6_ga__OctagonPrism__TransformOut = (
                ght.GH_Transform(vsg6_ga__OctagonPrism__TransformOut)
                if vsg6_ga__OctagonPrism__TransformOut is not None
                else None
            )
            self.vsg6_ga__OctagonPrism__MovedGeo = flatten_any(vsg6_ga__OctagonPrism__MovedGeo)

            self.LogLines.append("Step8-2 完成：vsg6_ga__OctagonPrism")
        except Exception as e:
            self.LogLines.append("Step8-2 失败：vsg6_ga__OctagonPrism -> {}".format(e))

    def step8_3_vsg6_ga__LaoYanFang12(self):
        """
        Step8-3：叠次-6：橑檐方一、橑檐方二
        包括组件：
        - vsg6_timber_block1
        - vsg6_PlaneFromLists1 / vsg6_PlaneFromLists2 / vsg6_PlaneFromLists3
        - vsg6_ga__LaoYanFang1 / vsg6_ga__LaoYanFang2

        严格按你提供的 GH 组件说明实现（并移除 sticky，不做兼容）：

        1) vsg6_timber_block1
           length_fen = AllDict0['vsg6_timber_block1__length_fen'] (默认 32)
           width_fen  = AllDict0['vsg6_timber_block1__width_fen']  (默认 32)
           height_fen = AllDict0['vsg6_timber_block2__height_fen'] (默认 20)  # 按你的说明键名
           调用 build_timber_block_uniform 输出 TimberBrep / EdgeMidPoints / Corner0Planes / ...

           为避免变量重名，所有输出均以 vsg6_timber_block1__ 前缀暴露。

        2) vsg6_PlaneFromLists1
           OriginPoints = vsg6_timber_block1__EdgeMidPoints
           BasePlanes   = vsg6_timber_block1__Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists1__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists1__IndexPlane']

        3) vsg6_PlaneFromLists2
           OriginPoints = GuaZiGongInLineWLingGong1__EdgeMidPoints
           BasePlanes   = GuaZiGongInLineWLingGong1__Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists2__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists2__IndexPlane']

        4) vsg6_PlaneFromLists3
           OriginPoints = GuaZiGongInLineWLingGong2__EdgeMidPoints
           BasePlanes   = GuaZiGongInLineWLingGong2__Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists3__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists3__IndexPlane']

        5) vsg6_ga__LaoYanFang1
           Geo        = vsg6_timber_block1__TimberBrep
           SourcePlane= vsg6_PlaneFromLists1__ResultPlane
           TargetPlane= ghc.Transform(vsg6_PlaneFromLists2__ResultPlane, vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut)
           RotateDeg  = AllDict0['vsg6_ga__LaoYanFang1__RotateDeg']（默认 vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg）
           FlipZ      = AllDict0['vsg6_ga__LaoYanFang1__FlipZ']
           MoveY      = AllDict0['vsg6_ga__LaoYanFang1__MoveY']
           MoveZ      = AllDict0['vsg6_ga__LaoYanFang1__MoveZ']

        6) vsg6_ga__LaoYanFang2
           Geo        = vsg6_timber_block1__TimberBrep
           SourcePlane= vsg6_PlaneFromLists1__ResultPlane
           TargetPlane= ghc.Transform(vsg6_PlaneFromLists3__ResultPlane, vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut)
           RotateDeg  = AllDict0['vsg6_ga__LaoYanFang2__RotateDeg']（默认 vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg）
           FlipZ      = AllDict0['vsg6_ga__LaoYanFang2__FlipZ']
           MoveY      = AllDict0['vsg6_ga__LaoYanFang2__MoveY']
           MoveZ      = AllDict0['vsg6_ga__LaoYanFang2__MoveZ']

        说明：
        - Transform 计算用 ghc.Transform（import ghpythonlib.components as ghc）
        - GeoAligner 用 GeoAligner_xfm.align，并将 TransformOut 包装为 ght.GH_Transform
        - 若输出端出现嵌套列表：统一 flatten_any 展平
        """
        try:
            import Rhino.Geometry as rg
            import ghpythonlib.components as ghc
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import build_timber_block_uniform, FTPlaneFromLists, GeoAligner_xfm

            # =========================================================
            # 1) vsg6_timber_block1
            # =========================================================
            length_fen = self.AllDict0.get("vsg6_timber_block1__length_fen", 32.0)
            width_fen = self.AllDict0.get("vsg6_timber_block1__width_fen", 32.0)
            height_fen = self.AllDict0.get("vsg6_timber_block1__height_fen", 20.0)  # 按你的说明

            try:
                length_fen = float(length_fen)
            except Exception:
                length_fen = 32.0
            try:
                width_fen = float(width_fen)
            except Exception:
                width_fen = 32.0
            try:
                height_fen = float(height_fen)
            except Exception:
                height_fen = 20.0

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = _coerce_plane(getattr(self, "PlacePlane", None), None)

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
                # reference_plane,
            )

            # 以组件名前缀暴露，避免与其它 TimberBlock 冲突
            self.vsg6_timber_block1__TimberBrep = timber_brep
            self.vsg6_timber_block1__FaceList = faces
            self.vsg6_timber_block1__PointList = points
            self.vsg6_timber_block1__EdgeList = edges
            self.vsg6_timber_block1__CenterPoint = center_pt
            self.vsg6_timber_block1__CenterAxisLines = center_axes
            self.vsg6_timber_block1__EdgeMidPoints = edge_midpts
            self.vsg6_timber_block1__FacePlaneList = face_planes
            self.vsg6_timber_block1__Corner0Planes = corner0_planes
            self.vsg6_timber_block1__LocalAxesPlane = local_axes_plane
            self.vsg6_timber_block1__AxisX = axis_x
            self.vsg6_timber_block1__AxisY = axis_y
            self.vsg6_timber_block1__AxisZ = axis_z
            self.vsg6_timber_block1__FaceDirTags = face_tags
            self.vsg6_timber_block1__EdgeDirTags = edge_tags
            self.vsg6_timber_block1__Corner0EdgeDirs = corner0_dirs
            self.vsg6_timber_block1__Log = log_lines

            # =========================================================
            # 2) vsg6_PlaneFromLists1
            # =========================================================
            Wrap = True
            builder = FTPlaneFromLists(wrap=Wrap)

            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                getattr(self, "vsg6_timber_block1__EdgeMidPoints", None),
                getattr(self, "vsg6_timber_block1__Corner0Planes", None),
                self.AllDict0.get("vsg6_PlaneFromLists1__IndexOrigin", 0),
                self.AllDict0.get("vsg6_PlaneFromLists1__IndexPlane", 0),
            )
            self.vsg6_PlaneFromLists1__BasePlane = BasePlane
            self.vsg6_PlaneFromLists1__OriginPoint = OriginPoint
            self.vsg6_PlaneFromLists1__ResultPlane = ResultPlane
            self.vsg6_PlaneFromLists1__Log = Log

            # =========================================================
            # 3) vsg6_PlaneFromLists2
            # =========================================================
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                getattr(self, "GuaZiGongInLineWLingGong1__EdgeMidPoints", None),
                getattr(self, "GuaZiGongInLineWLingGong1__Corner0Planes", None),
                self.AllDict0.get("vsg6_PlaneFromLists2__IndexOrigin", 0),
                self.AllDict0.get("vsg6_PlaneFromLists2__IndexPlane", 0),
            )
            self.vsg6_PlaneFromLists2__BasePlane = BasePlane
            self.vsg6_PlaneFromLists2__OriginPoint = OriginPoint
            self.vsg6_PlaneFromLists2__ResultPlane = ResultPlane
            self.vsg6_PlaneFromLists2__Log = Log

            # =========================================================
            # 4) vsg6_PlaneFromLists3
            # =========================================================
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                getattr(self, "GuaZiGongInLineWLingGong2__EdgeMidPoints", None),
                getattr(self, "GuaZiGongInLineWLingGong2__Corner0Planes", None),
                self.AllDict0.get("vsg6_PlaneFromLists3__IndexOrigin", 0),
                self.AllDict0.get("vsg6_PlaneFromLists3__IndexPlane", 0),
            )
            self.vsg6_PlaneFromLists3__BasePlane = BasePlane
            self.vsg6_PlaneFromLists3__OriginPoint = OriginPoint
            self.vsg6_PlaneFromLists3__ResultPlane = ResultPlane
            self.vsg6_PlaneFromLists3__Log = Log

            # =========================================================
            # 5) vsg6_ga__LaoYanFang1
            # =========================================================
            Geo = getattr(self, "vsg6_timber_block1__TimberBrep", None)
            SourcePlane = getattr(self, "vsg6_PlaneFromLists1__ResultPlane", None)

            tp_geo = getattr(self, "vsg6_PlaneFromLists2__ResultPlane", None)
            tp_xfm = getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut", None)

            # 取 GH_Transform.Value / 列表第一个
            if isinstance(tp_xfm, (list, tuple)):
                tp_xfm = tp_xfm[0] if len(tp_xfm) > 0 else None
            try:
                if isinstance(tp_xfm, ght.GH_Transform):
                    tp_xfm = tp_xfm.Value
            except Exception:
                pass
            if tp_xfm is None:
                tp_xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(tp_geo, tp_xfm) if (tp_geo is not None and tp_xfm is not None) else tp_geo
            self.vsg6_ga__LaoYanFang1__TargetPlane_Transform = TargetPlane

            RotateDeg = self.AllDict0.get(
                "vsg6_ga__LaoYanFang1__RotateDeg",
                getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg", 0)
            )
            FlipX = self.AllDict0.get("vsg6_ga__LaoYanFang1__FlipX", False)
            FlipY = self.AllDict0.get("vsg6_ga__LaoYanFang1__FlipY", False)
            FlipZ = self.AllDict0.get("vsg6_ga__LaoYanFang1__FlipZ", False)
            MoveX = self.AllDict0.get("vsg6_ga__LaoYanFang1__MoveX", 0)
            MoveY = self.AllDict0.get("vsg6_ga__LaoYanFang1__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg6_ga__LaoYanFang1__MoveZ", 0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            self.vsg6_ga__LaoYanFang1__SourceOut = flatten_any(SourceOut)
            self.vsg6_ga__LaoYanFang1__TargetOut = flatten_any(TargetOut)
            self.vsg6_ga__LaoYanFang1__MovedGeo = flatten_any(MovedGeo)
            self.vsg6_ga__LaoYanFang1__TransformOut = (
                [ght.GH_Transform(x) if x is not None else None for x in TransformOut]
                if isinstance(TransformOut, (list, tuple))
                else (ght.GH_Transform(TransformOut) if TransformOut is not None else None)
            )

            # =========================================================
            # 6) vsg6_ga__LaoYanFang2
            # =========================================================
            Geo = getattr(self, "vsg6_timber_block1__TimberBrep", None)
            SourcePlane = getattr(self, "vsg6_PlaneFromLists1__ResultPlane", None)

            tp_geo = getattr(self, "vsg6_PlaneFromLists3__ResultPlane", None)
            tp_xfm = getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut", None)

            if isinstance(tp_xfm, (list, tuple)):
                tp_xfm = tp_xfm[0] if len(tp_xfm) > 0 else None
            try:
                if isinstance(tp_xfm, ght.GH_Transform):
                    tp_xfm = tp_xfm.Value
            except Exception:
                pass
            if tp_xfm is None:
                tp_xfm = rg.Transform.Identity

            TargetPlane = ghc.Transform(tp_geo, tp_xfm) if (tp_geo is not None and tp_xfm is not None) else tp_geo
            self.vsg6_ga__LaoYanFang2__TargetPlane_Transform = TargetPlane

            RotateDeg = self.AllDict0.get(
                "vsg6_ga__LaoYanFang2__RotateDeg",
                getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__RotateDeg", 0)
            )
            FlipX = self.AllDict0.get("vsg6_ga__LaoYanFang2__FlipX", False)
            FlipY = self.AllDict0.get("vsg6_ga__LaoYanFang2__FlipY", False)
            FlipZ = self.AllDict0.get("vsg6_ga__LaoYanFang2__FlipZ", False)
            MoveX = self.AllDict0.get("vsg6_ga__LaoYanFang2__MoveX", 0)
            MoveY = self.AllDict0.get("vsg6_ga__LaoYanFang2__MoveY", 0)
            MoveZ = self.AllDict0.get("vsg6_ga__LaoYanFang2__MoveZ", 0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                Geo,
                SourcePlane,
                TargetPlane,
                rotate_deg=RotateDeg,
                flip_x=FlipX,
                flip_y=FlipY,
                flip_z=FlipZ,
                move_x=MoveX,
                move_y=MoveY,
                move_z=MoveZ,
            )

            self.vsg6_ga__LaoYanFang2__SourceOut = flatten_any(SourceOut)
            self.vsg6_ga__LaoYanFang2__TargetOut = flatten_any(TargetOut)
            self.vsg6_ga__LaoYanFang2__MovedGeo = flatten_any(MovedGeo)
            self.vsg6_ga__LaoYanFang2__TransformOut = (
                [ght.GH_Transform(x) if x is not None else None for x in TransformOut]
                if isinstance(TransformOut, (list, tuple))
                else (ght.GH_Transform(TransformOut) if TransformOut is not None else None)
            )

            self.LogLines.append("Step8-3 完成：vsg6_ga__LaoYanFang1 / vsg6_ga__LaoYanFang2")
        except Exception as e:
            self.LogLines.append("Step8-3 失败：LaoYanFang1/2 -> {}".format(e))

    def step8_4_vsg6_ga__ZhuTouFang12(self):
        """
        Step8-4：叠次-6：柱頭方一、柱頭方二
        包括组件：
        - vsg6_timber_block2
        - vsg6_PlaneFromLists4
        - vsg6_TreeItem_ListItem_PlaneOrigin_Transform2
        - vsg6_TreeItem_ListItem_PlaneOrigin_Transform3
        - vsg6_ga__ZhuTouFang1
        - vsg6_ga__ZhuTouFang2

        严格按你提供的 GH 组件说明实现（移除 sticky，不做兼容）：
        1) vsg6_timber_block2：build_timber_block_uniform(length_fen, width_fen, height_fen, base_point, reference_plane)
           - base_point 默认原点；reference_plane 不输入（None）
           - length/width/height 默认：32/32/20

        2) vsg6_PlaneFromLists4：
           OriginPoints = vsg6_timber_block2.EdgeMidPoints
           BasePlanes   = vsg6_timber_block2.Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists4__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists4__IndexPlane']

        3) vsg6_TreeItem_ListItem_PlaneOrigin_Transform2：
           TreeItem_Tree = ShuaTouInLineWManGong1__Skew_Planes
           ListItem_List = ShuaTouInLineWManGong1__Skew_Point_C
           Transform_Transform = vsg4_ga__ShuaTouInLineWManGong1.TransformOut

        4) vsg6_TreeItem_ListItem_PlaneOrigin_Transform3：
           TreeItem_Tree = ShuaTouInLineWManGong2__Skew_Planes
           ListItem_List = ShuaTouInLineWManGong2__Skew_Point_C
           Transform_Transform = vsg4_ga__ShuaTouInLineWManGong2.TransformOut

        5) vsg6_ga__ZhuTouFang1 / vsg6_ga__ZhuTouFang2：
           Geo        = vsg6_timber_block2.TimberBrep
           SourcePlane= vsg6_PlaneFromLists4.ResultPlane
           TargetPlane= vsg6_TreeItem_ListItem_PlaneOrigin_Transform{2/3}.Transform_Geometry_Out
           RotateDeg  = AllDict0['vsg6_ga__ZhuTouFang{1/2}__RotateDeg']
           FlipZ      = AllDict0['vsg6_ga__ZhuTouFang{1/2}__FlipZ']
           其余 FlipX/FlipY/MoveX/MoveY/MoveZ 若数据库存在则取值，否则默认 False/0
        """
        try:
            import Rhino.Geometry as rg
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import (
                build_timber_block_uniform,
                FTPlaneFromLists,
                GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC,
                GeoAligner_xfm,
            )

            # -----------------------------
            # 便捷：取 DB 参数（带默认）
            # -----------------------------
            AllDict0 = getattr(self, "AllDict0", {}) or {}

            def _dbget(k, default=None):
                return AllDict0[k] if (isinstance(AllDict0, dict) and k in AllDict0) else default

            # ===========================
            # 1) vsg6_timber_block2
            # ===========================
            vsg6_timber_block2__length_fen = _dbget("vsg6_timber_block2__length_fen", 32.0)
            vsg6_timber_block2__width_fen = _dbget("vsg6_timber_block2__width_fen", 32.0)
            vsg6_timber_block2__height_fen = _dbget("vsg6_timber_block2__height_fen", 20.0)

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = None  # 按说明：不输入

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
                vsg6_timber_block2__length_fen,
                vsg6_timber_block2__width_fen,
                vsg6_timber_block2__height_fen,
                base_point,
                reference_plane,
            )

            # 输出（统一加前缀避免重名）
            self.vsg6_timber_block2__TimberBrep = timber_brep
            self.vsg6_timber_block2__FaceList = faces
            self.vsg6_timber_block2__PointList = points
            self.vsg6_timber_block2__EdgeList = edges
            self.vsg6_timber_block2__CenterPoint = center_pt
            self.vsg6_timber_block2__CenterAxisLines = center_axes
            self.vsg6_timber_block2__EdgeMidPoints = edge_midpts
            self.vsg6_timber_block2__FacePlaneList = face_planes
            self.vsg6_timber_block2__Corner0Planes = corner0_planes
            self.vsg6_timber_block2__LocalAxesPlane = local_axes_plane
            self.vsg6_timber_block2__AxisX = axis_x
            self.vsg6_timber_block2__AxisY = axis_y
            self.vsg6_timber_block2__AxisZ = axis_z
            self.vsg6_timber_block2__FaceDirTags = face_tags
            self.vsg6_timber_block2__EdgeDirTags = edge_tags
            self.vsg6_timber_block2__Corner0EdgeDirs = corner0_dirs
            self.vsg6_timber_block2__Log = log_lines

            # ===========================
            # 2) vsg6_PlaneFromLists4
            # ===========================
            vsg6_PlaneFromLists4__IndexOrigin = _dbget("vsg6_PlaneFromLists4__IndexOrigin", 0)
            vsg6_PlaneFromLists4__IndexPlane = _dbget("vsg6_PlaneFromLists4__IndexPlane", 0)
            vsg6_PlaneFromLists4__Wrap = _dbget("vsg6_PlaneFromLists4__Wrap", True)

            builder = FTPlaneFromLists(wrap=bool(vsg6_PlaneFromLists4__Wrap))
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                self.vsg6_timber_block2__EdgeMidPoints,
                self.vsg6_timber_block2__Corner0Planes,
                vsg6_PlaneFromLists4__IndexOrigin,
                vsg6_PlaneFromLists4__IndexPlane,
            )

            self.vsg6_PlaneFromLists4__BasePlane = BasePlane
            self.vsg6_PlaneFromLists4__OriginPoint = OriginPoint
            self.vsg6_PlaneFromLists4__ResultPlane = ResultPlane
            self.vsg6_PlaneFromLists4__Log = Log

            # ===========================
            # 3) vsg6_TreeItem_ListItem_PlaneOrigin_Transform2
            # ===========================
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Path = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Path", "{0}")
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Wrap", True)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Wrap", True)

            xfm_in_1 = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            if isinstance(xfm_in_1, ght.GH_Transform):
                xfm_in_1 = xfm_in_1.Value

            solver_tp = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()
            Transform_Geometry_Out_2 = solver_tp.solve(
                getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Path,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__TreeItem_Wrap,
                getattr(self, "ShuaTouInLineWManGong1__Skew_Point_C", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__ListItem_Wrap,
                xfm_in_1,
            )
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out = Transform_Geometry_Out_2

            # ===========================
            # 4) vsg6_TreeItem_ListItem_PlaneOrigin_Transform3
            # ===========================
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Path = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Path", "{0}")
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Wrap", True)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Wrap", True)

            xfm_in_2 = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)
            if isinstance(xfm_in_2, ght.GH_Transform):
                xfm_in_2 = xfm_in_2.Value

            Transform_Geometry_Out_3 = solver_tp.solve(
                getattr(self, "ShuaTouInLineWManGong2__Skew_Planes", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Path,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__TreeItem_Wrap,
                getattr(self, "ShuaTouInLineWManGong2__Skew_Point_C", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__ListItem_Wrap,
                xfm_in_2,
            )
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__Transform_Geometry_Out = Transform_Geometry_Out_3

            # ===========================
            # 5) vsg6_ga__ZhuTouFang1
            # ===========================
            def _wrap_ght(x):
                # x 可能是 Transform / GH_Transform / list
                if isinstance(x, list):
                    return [ght.GH_Transform(v) if v is not None else None for v in x]
                return (ght.GH_Transform(x) if x is not None else None)

            r1 = _dbget("vsg6_ga__ZhuTouFang1__RotateDeg", 0.0)
            fx1 = _dbget("vsg6_ga__ZhuTouFang1__FlipX", False)
            fy1 = _dbget("vsg6_ga__ZhuTouFang1__FlipY", False)
            fz1 = _dbget("vsg6_ga__ZhuTouFang1__FlipZ", False)
            mx1 = _dbget("vsg6_ga__ZhuTouFang1__MoveX", 0.0)
            my1 = _dbget("vsg6_ga__ZhuTouFang1__MoveY", 0.0)
            mz1 = _dbget("vsg6_ga__ZhuTouFang1__MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                self.vsg6_timber_block2__TimberBrep,
                self.vsg6_PlaneFromLists4__ResultPlane,
                self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out,
                rotate_deg=r1,
                flip_x=fx1,
                flip_y=fy1,
                flip_z=fz1,
                move_x=mx1,
                move_y=my1,
                move_z=mz1,
            )

            self.vsg6_ga__ZhuTouFang1__SourceOut = SourceOut
            self.vsg6_ga__ZhuTouFang1__TargetOut = TargetOut
            self.vsg6_ga__ZhuTouFang1__TransformOut = _wrap_ght(TransformOut)
            self.vsg6_ga__ZhuTouFang1__MovedGeo = flatten_any(MovedGeo)

            # ===========================
            # 6) vsg6_ga__ZhuTouFang2
            # ===========================
            r2 = _dbget("vsg6_ga__ZhuTouFang2__RotateDeg", 0.0)
            fx2 = _dbget("vsg6_ga__ZhuTouFang2__FlipX", False)
            fy2 = _dbget("vsg6_ga__ZhuTouFang2__FlipY", False)
            fz2 = _dbget("vsg6_ga__ZhuTouFang2__FlipZ", False)
            mx2 = _dbget("vsg6_ga__ZhuTouFang2__MoveX", 0.0)
            my2 = _dbget("vsg6_ga__ZhuTouFang2__MoveY", 0.0)
            mz2 = _dbget("vsg6_ga__ZhuTouFang2__MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                self.vsg6_timber_block2__TimberBrep,
                self.vsg6_PlaneFromLists4__ResultPlane,
                self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__Transform_Geometry_Out,
                rotate_deg=r2,
                flip_x=fx2,
                flip_y=fy2,
                flip_z=fz2,
                move_x=mx2,
                move_y=my2,
                move_z=mz2,
            )

            self.vsg6_ga__ZhuTouFang2__SourceOut = SourceOut
            self.vsg6_ga__ZhuTouFang2__TargetOut = TargetOut
            self.vsg6_ga__ZhuTouFang2__TransformOut = _wrap_ght(TransformOut)
            self.vsg6_ga__ZhuTouFang2__MovedGeo = flatten_any(MovedGeo)

        except Exception as e:
            # 发生错误时：记录日志，且清空关键输出，避免后续崩溃
            self.LogLines.append("Step8-4 error (ZhuTouFang12): {}".format(e))
            self.vsg6_timber_block2__TimberBrep = None
            self.vsg6_PlaneFromLists4__ResultPlane = None
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out = None
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__Transform_Geometry_Out = None
            self.vsg6_ga__ZhuTouFang1__MovedGeo = None
            self.vsg6_ga__ZhuTouFang2__MovedGeo = None

    def step8_5_vsg6_ga__NiuJiFang12(self):
        """
        Step8-5：叠次-6：牛脊方一、牛脊方二
        包括组件：
        - vsg6_timber_block3
        - vsg6_PlaneFromLists5
        - vsg6_TreeItem_ListItem_PlaneOrigin_Transform4
        - vsg6_TreeItem_ListItem_PlaneOrigin_Transform5
        - vsg6_ga__NiuJiFang1
        - vsg6_ga__NiuJiFang2

        严格按你提供的 GH 组件说明实现（移除 sticky，不做兼容）：
        1) vsg6_timber_block3：build_timber_block_uniform(length_fen, width_fen, height_fen, base_point, reference_plane)
           - base_point 默认原点；reference_plane 不输入（None）
           - length/width/height 默认：32/32/20

        2) vsg6_PlaneFromLists5：
           OriginPoints = vsg6_timber_block3.EdgeMidPoints
           BasePlanes   = vsg6_timber_block3.Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists5__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists5__IndexPlane']

        3) vsg6_TreeItem_ListItem_PlaneOrigin_Transform4：
           TreeItem_Tree = ShuaTouInLineWManGong1__Skew_Planes
           ListItem_List = ShuaTouInLineWManGong1__Skew_Point_C
           Transform_Transform = vsg4_ga__ShuaTouInLineWManGong1.TransformOut

        4) vsg6_TreeItem_ListItem_PlaneOrigin_Transform5：
           TreeItem_Tree = ShuaTouInLineWManGong2__Skew_Planes
           ListItem_List = ShuaTouInLineWManGong2__Skew_Point_C
           Transform_Transform = vsg4_ga__ShuaTouInLineWManGong2.TransformOut

        5) vsg6_ga__NiuJiFang1 / vsg6_ga__NiuJiFang2：
           Geo        = vsg6_timber_block3.TimberBrep
           SourcePlane= vsg6_PlaneFromLists5.ResultPlane
           TargetPlane= vsg6_TreeItem_ListItem_PlaneOrigin_Transform{4/5}.Transform_Geometry_Out
           RotateDeg  = AllDict0['vsg6_ga__NiuJiFang{1/2}__RotateDeg']
           FlipZ      = AllDict0['vsg6_ga__NiuJiFang{1/2}__FlipZ']
           MoveZ      = AllDict0['vsg6_ga__NiuJiFang{1/2}__MoveZ']
           其余 FlipX/FlipY/MoveX/MoveY 若数据库存在则取值，否则默认 False/0
        """
        try:
            import Rhino.Geometry as rg
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import (
                build_timber_block_uniform,
                FTPlaneFromLists,
                GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC,
                GeoAligner_xfm,
            )

            # -----------------------------
            # 便捷：取 DB 参数（带默认）
            # -----------------------------
            AllDict0 = getattr(self, "AllDict0", {}) or {}

            def _dbget(k, default=None):
                return AllDict0[k] if (isinstance(AllDict0, dict) and k in AllDict0) else default

            # ===========================
            # 1) vsg6_timber_block3
            # ===========================
            vsg6_timber_block3__length_fen = _dbget("vsg6_timber_block3__length_fen", 32.0)
            vsg6_timber_block3__width_fen = _dbget("vsg6_timber_block3__width_fen", 32.0)
            vsg6_timber_block3__height_fen = _dbget("vsg6_timber_block3__height_fen", 20.0)

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = None  # 按说明：不输入

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
                vsg6_timber_block3__length_fen,
                vsg6_timber_block3__width_fen,
                vsg6_timber_block3__height_fen,
                base_point,
                reference_plane,
            )

            # 输出（统一加前缀避免重名）
            self.vsg6_timber_block3__TimberBrep = timber_brep
            self.vsg6_timber_block3__FaceList = faces
            self.vsg6_timber_block3__PointList = points
            self.vsg6_timber_block3__EdgeList = edges
            self.vsg6_timber_block3__CenterPoint = center_pt
            self.vsg6_timber_block3__CenterAxisLines = center_axes
            self.vsg6_timber_block3__EdgeMidPoints = edge_midpts
            self.vsg6_timber_block3__FacePlaneList = face_planes
            self.vsg6_timber_block3__Corner0Planes = corner0_planes
            self.vsg6_timber_block3__LocalAxesPlane = local_axes_plane
            self.vsg6_timber_block3__AxisX = axis_x
            self.vsg6_timber_block3__AxisY = axis_y
            self.vsg6_timber_block3__AxisZ = axis_z
            self.vsg6_timber_block3__FaceDirTags = face_tags
            self.vsg6_timber_block3__EdgeDirTags = edge_tags
            self.vsg6_timber_block3__Corner0EdgeDirs = corner0_dirs
            self.vsg6_timber_block3__Log = log_lines

            # ===========================
            # 2) vsg6_PlaneFromLists5
            # ===========================
            vsg6_PlaneFromLists5__IndexOrigin = _dbget("vsg6_PlaneFromLists5__IndexOrigin", 0)
            vsg6_PlaneFromLists5__IndexPlane = _dbget("vsg6_PlaneFromLists5__IndexPlane", 0)
            vsg6_PlaneFromLists5__Wrap = _dbget("vsg6_PlaneFromLists5__Wrap", True)

            builder = FTPlaneFromLists(wrap=bool(vsg6_PlaneFromLists5__Wrap))
            BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
                self.vsg6_timber_block3__EdgeMidPoints,
                self.vsg6_timber_block3__Corner0Planes,
                vsg6_PlaneFromLists5__IndexOrigin,
                vsg6_PlaneFromLists5__IndexPlane,
            )

            self.vsg6_PlaneFromLists5__BasePlane = BasePlane
            self.vsg6_PlaneFromLists5__OriginPoint = OriginPoint
            self.vsg6_PlaneFromLists5__ResultPlane = ResultPlane
            self.vsg6_PlaneFromLists5__Log = Log

            # 共用 Tree+List 对位 solver
            solver_tp = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()

            # ===========================
            # 3) vsg6_TreeItem_ListItem_PlaneOrigin_Transform4
            # ===========================
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Path = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Path", "{0}")
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Wrap", True)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Wrap", True)

            xfm_in_1 = getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut", None)
            if isinstance(xfm_in_1, ght.GH_Transform):
                xfm_in_1 = xfm_in_1.Value

            Transform_Geometry_Out_4 = solver_tp.solve(
                getattr(self, "ShuaTouInLineWManGong1__Skew_Planes", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Path,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__TreeItem_Wrap,
                getattr(self, "ShuaTouInLineWManGong1__Skew_Point_C", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__ListItem_Wrap,
                xfm_in_1,
            )
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__Transform_Geometry_Out = Transform_Geometry_Out_4

            # ===========================
            # 4) vsg6_TreeItem_ListItem_PlaneOrigin_Transform5
            # ===========================
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Path = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Path", "{0}")
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Index = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Index", 0)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Wrap", True)
            vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Wrap = _dbget(
                "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Wrap", True)

            xfm_in_2 = getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut", None)
            if isinstance(xfm_in_2, ght.GH_Transform):
                xfm_in_2 = xfm_in_2.Value

            Transform_Geometry_Out_5 = solver_tp.solve(
                getattr(self, "ShuaTouInLineWManGong2__Skew_Planes", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Path,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__TreeItem_Wrap,
                getattr(self, "ShuaTouInLineWManGong2__Skew_Point_C", None),
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Index,
                vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__ListItem_Wrap,
                xfm_in_2,
            )
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__Transform_Geometry_Out = Transform_Geometry_Out_5

            # ===========================
            # 5) vsg6_ga__NiuJiFang1 / vsg6_ga__NiuJiFang2
            # ===========================
            def _wrap_ght(x):
                # x 可能是 Transform / GH_Transform / list
                if isinstance(x, list):
                    return [ght.GH_Transform(v) if v is not None else None for v in x]
                return (ght.GH_Transform(x) if x is not None else None)

            # -- NiuJiFang1
            r1 = _dbget("vsg6_ga__NiuJiFang1__RotateDeg", 0.0)
            fx1 = _dbget("vsg6_ga__NiuJiFang1__FlipX", False)
            fy1 = _dbget("vsg6_ga__NiuJiFang1__FlipY", False)
            fz1 = _dbget("vsg6_ga__NiuJiFang1__FlipZ", False)
            mx1 = _dbget("vsg6_ga__NiuJiFang1__MoveX", 0.0)
            my1 = _dbget("vsg6_ga__NiuJiFang1__MoveY", 0.0)
            mz1 = _dbget("vsg6_ga__NiuJiFang1__MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                self.vsg6_timber_block3__TimberBrep,
                self.vsg6_PlaneFromLists5__ResultPlane,
                self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__Transform_Geometry_Out,
                rotate_deg=r1,
                flip_x=fx1,
                flip_y=fy1,
                flip_z=fz1,
                move_x=mx1,
                move_y=my1,
                move_z=mz1,
            )
            self.vsg6_ga__NiuJiFang1__SourceOut = SourceOut
            self.vsg6_ga__NiuJiFang1__TargetOut = TargetOut
            self.vsg6_ga__NiuJiFang1__TransformOut = _wrap_ght(TransformOut)
            self.vsg6_ga__NiuJiFang1__MovedGeo = flatten_any(MovedGeo)

            # -- NiuJiFang2
            r2 = _dbget("vsg6_ga__NiuJiFang2__RotateDeg", 0.0)
            fx2 = _dbget("vsg6_ga__NiuJiFang2__FlipX", False)
            fy2 = _dbget("vsg6_ga__NiuJiFang2__FlipY", False)
            fz2 = _dbget("vsg6_ga__NiuJiFang2__FlipZ", False)
            mx2 = _dbget("vsg6_ga__NiuJiFang2__MoveX", 0.0)
            my2 = _dbget("vsg6_ga__NiuJiFang2__MoveY", 0.0)
            mz2 = _dbget("vsg6_ga__NiuJiFang2__MoveZ", 0.0)

            SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
                self.vsg6_timber_block3__TimberBrep,
                self.vsg6_PlaneFromLists5__ResultPlane,
                self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__Transform_Geometry_Out,
                rotate_deg=r2,
                flip_x=fx2,
                flip_y=fy2,
                flip_z=fz2,
                move_x=mx2,
                move_y=my2,
                move_z=mz2,
            )
            self.vsg6_ga__NiuJiFang2__SourceOut = SourceOut
            self.vsg6_ga__NiuJiFang2__TargetOut = TargetOut
            self.vsg6_ga__NiuJiFang2__TransformOut = _wrap_ght(TransformOut)
            self.vsg6_ga__NiuJiFang2__MovedGeo = flatten_any(MovedGeo)

        except Exception as e:
            self.LogLines.append("Step8-5 error (NiuJiFang12): {}".format(e))
            self.vsg6_timber_block3__TimberBrep = None
            self.vsg6_PlaneFromLists5__ResultPlane = None
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__Transform_Geometry_Out = None
            self.vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__Transform_Geometry_Out = None
            self.vsg6_ga__NiuJiFang1__MovedGeo = None
            self.vsg6_ga__NiuJiFang2__MovedGeo = None

    def step8_6_vsg6_ga__PingJiFang12(self):
        """
        Step8-6：叠次-6：平基方一、平基方二
        包括组件：
        - vsg6_timber_block4
        - vsg6_PlaneFromLists6
        - vsg6_PlaneFromLists7
        - vsg6_PlaneFromLists8
        - vsg6_ga__PingJiFang1
        - vsg6_ga__PingJiFang2

        严格按你提供的 GH 组件说明实现（移除 sticky，不做兼容）：
        1) vsg6_timber_block4：build_timber_block_uniform(length_fen, width_fen, height_fen, base_point, reference_plane)
           - base_point 默认原点；reference_plane 不输入（None）
           - length/width/height 默认：32/32/20

        2) vsg6_PlaneFromLists6：
           OriginPoints = vsg6_timber_block4.EdgeMidPoints
           BasePlanes   = vsg6_timber_block4.Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists6__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists6__IndexPlane']

        3) vsg6_PlaneFromLists7：
           OriginPoints = LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints
           BasePlanes   = LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists7__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists7__IndexPlane']

        4) vsg6_PlaneFromLists8：
           OriginPoints = LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints
           BasePlanes   = LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes
           IndexOrigin  = AllDict0['vsg6_PlaneFromLists8__IndexOrigin']
           IndexPlane   = AllDict0['vsg6_PlaneFromLists8__IndexPlane']

        5) vsg6_ga__PingJiFang1 / vsg6_ga__PingJiFang2：
           Geo        = vsg6_timber_block4.TimberBrep
           SourcePlane= vsg6_PlaneFromLists6.ResultPlane
           TargetPlane= ghc.Transform( vsg6_PlaneFromLists{7/8}.ResultPlane, vsg4_ga__LingGongInLineWXiaoGongTou{1/2}.TransformOut )
           RotateDeg  = AllDict0['vsg6_ga__PingJiFang{1/2}__RotateDeg']
           FlipZ      = AllDict0['vsg6_ga__PingJiFang{1/2}__FlipZ']
           MoveY      = AllDict0['vsg6_ga__PingJiFang{1/2}__MoveY']
           MoveZ      = AllDict0['vsg6_ga__PingJiFang{1/2}__MoveZ']
           其余 FlipX/FlipY/MoveX 默认 False/0；若数据库存在则取值
        """
        try:
            import ghpythonlib.components as ghc
            import Rhino.Geometry as rg
            import Grasshopper.Kernel.Types as ght
            from yingzao.ancientArchi import build_timber_block_uniform, FTPlaneFromLists, GeoAligner_xfm

            # -----------------------------
            # 便捷：取 DB 参数（带默认）
            # -----------------------------
            AllDict0 = getattr(self, "AllDict0", {}) or {}

            def _dbget(k, default=None):
                return AllDict0[k] if (isinstance(AllDict0, dict) and k in AllDict0) else default

            # ===========================
            # 1) vsg6_timber_block4
            # ===========================
            vsg6_timber_block4__length_fen = _dbget("vsg6_timber_block4__length_fen", 32.0)
            vsg6_timber_block4__width_fen = _dbget("vsg6_timber_block4__width_fen", 32.0)
            vsg6_timber_block4__height_fen = _dbget("vsg6_timber_block4__height_fen", 20.0)

            base_point = rg.Point3d(0.0, 0.0, 0.0)
            reference_plane = None  # 按说明：不输入

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
                vsg6_timber_block4__length_fen,
                vsg6_timber_block4__width_fen,
                vsg6_timber_block4__height_fen,
                base_point,
                reference_plane,
            )

            self.vsg6_timber_block4__TimberBrep = timber_brep
            self.vsg6_timber_block4__EdgeMidPoints = edge_midpts
            self.vsg6_timber_block4__Corner0Planes = corner0_planes
            self.vsg6_timber_block4__FacePlaneList = face_planes
            self.vsg6_timber_block4__LocalAxesPlane = local_axes_plane
            self.vsg6_timber_block4__AxisX = axis_x
            self.vsg6_timber_block4__AxisY = axis_y
            self.vsg6_timber_block4__AxisZ = axis_z
            self.vsg6_timber_block4__Log = log_lines

            # ===========================
            # 2) vsg6_PlaneFromLists6
            # ===========================
            p6 = FTPlaneFromLists(wrap=True)
            vsg6_PlaneFromLists6__IndexOrigin = _dbget("vsg6_PlaneFromLists6__IndexOrigin", 0)
            vsg6_PlaneFromLists6__IndexPlane = _dbget("vsg6_PlaneFromLists6__IndexPlane", 0)

            (
                vsg6_PlaneFromLists6__BasePlane,
                vsg6_PlaneFromLists6__OriginPoint,
                vsg6_PlaneFromLists6__ResultPlane,
                vsg6_PlaneFromLists6__Log,
            ) = p6.build_plane(
                self.vsg6_timber_block4__EdgeMidPoints,
                self.vsg6_timber_block4__Corner0Planes,
                vsg6_PlaneFromLists6__IndexOrigin,
                vsg6_PlaneFromLists6__IndexPlane,
            )

            self.vsg6_PlaneFromLists6__BasePlane = vsg6_PlaneFromLists6__BasePlane
            self.vsg6_PlaneFromLists6__OriginPoint = vsg6_PlaneFromLists6__OriginPoint
            self.vsg6_PlaneFromLists6__ResultPlane = vsg6_PlaneFromLists6__ResultPlane
            self.vsg6_PlaneFromLists6__Log = vsg6_PlaneFromLists6__Log

            # ===========================
            # 3) vsg6_PlaneFromLists7
            # ===========================
            p7 = FTPlaneFromLists(wrap=True)
            vsg6_PlaneFromLists7__IndexOrigin = _dbget("vsg6_PlaneFromLists7__IndexOrigin", 0)
            vsg6_PlaneFromLists7__IndexPlane = _dbget("vsg6_PlaneFromLists7__IndexPlane", 0)

            (
                vsg6_PlaneFromLists7__BasePlane,
                vsg6_PlaneFromLists7__OriginPoint,
                vsg6_PlaneFromLists7__ResultPlane,
                vsg6_PlaneFromLists7__Log,
            ) = p7.build_plane(
                getattr(self, "LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints", None),
                getattr(self, "LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes", None),
                vsg6_PlaneFromLists7__IndexOrigin,
                vsg6_PlaneFromLists7__IndexPlane,
            )

            self.vsg6_PlaneFromLists7__BasePlane = vsg6_PlaneFromLists7__BasePlane
            self.vsg6_PlaneFromLists7__OriginPoint = vsg6_PlaneFromLists7__OriginPoint
            self.vsg6_PlaneFromLists7__ResultPlane = vsg6_PlaneFromLists7__ResultPlane
            self.vsg6_PlaneFromLists7__Log = vsg6_PlaneFromLists7__Log

            # ===========================
            # 4) vsg6_PlaneFromLists8
            # ===========================
            p8 = FTPlaneFromLists(wrap=True)
            vsg6_PlaneFromLists8__IndexOrigin = _dbget("vsg6_PlaneFromLists8__IndexOrigin", 0)
            vsg6_PlaneFromLists8__IndexPlane = _dbget("vsg6_PlaneFromLists8__IndexPlane", 0)

            (
                vsg6_PlaneFromLists8__BasePlane,
                vsg6_PlaneFromLists8__OriginPoint,
                vsg6_PlaneFromLists8__ResultPlane,
                vsg6_PlaneFromLists8__Log,
            ) = p8.build_plane(
                getattr(self, "LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints", None),
                getattr(self, "LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes", None),
                vsg6_PlaneFromLists8__IndexOrigin,
                vsg6_PlaneFromLists8__IndexPlane,
            )

            self.vsg6_PlaneFromLists8__BasePlane = vsg6_PlaneFromLists8__BasePlane
            self.vsg6_PlaneFromLists8__OriginPoint = vsg6_PlaneFromLists8__OriginPoint
            self.vsg6_PlaneFromLists8__ResultPlane = vsg6_PlaneFromLists8__ResultPlane
            self.vsg6_PlaneFromLists8__Log = vsg6_PlaneFromLists8__Log

            # ===========================
            # 5) vsg6_ga__PingJiFang1 / 2
            # ===========================
            SourcePlane = self.vsg6_PlaneFromLists6__ResultPlane

            # ---- PingJiFang1 ----
            TargetPlane1_geo = self.vsg6_PlaneFromLists7__ResultPlane
            xfm1 = getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut", None)
            TargetPlane1 = ghc.Transform(TargetPlane1_geo, xfm1)

            RotateDeg1 = _dbget("vsg6_ga__PingJiFang1__RotateDeg", 0.0)
            FlipX1 = _dbget("vsg6_ga__PingJiFang1__FlipX", False)
            FlipY1 = _dbget("vsg6_ga__PingJiFang1__FlipY", False)
            FlipZ1 = _dbget("vsg6_ga__PingJiFang1__FlipZ", False)
            MoveX1 = _dbget("vsg6_ga__PingJiFang1__MoveX", 0.0)
            MoveY1 = _dbget("vsg6_ga__PingJiFang1__MoveY", 0.0)
            MoveZ1 = _dbget("vsg6_ga__PingJiFang1__MoveZ", 0.0)

            SourceOut1, TargetOut1, TransformOut1, MovedGeo1 = GeoAligner_xfm.align(
                self.vsg6_timber_block4__TimberBrep,
                SourcePlane,
                TargetPlane1,
                rotate_deg=RotateDeg1,
                flip_x=FlipX1,
                flip_y=FlipY1,
                flip_z=FlipZ1,
                move_x=MoveX1,
                move_y=MoveY1,
                move_z=MoveZ1,
            )
            self.vsg6_ga__PingJiFang1__SourceOut = SourceOut1
            self.vsg6_ga__PingJiFang1__TargetOut = TargetOut1
            self.vsg6_ga__PingJiFang1__TransformOut = ght.GH_Transform(
                TransformOut1) if TransformOut1 is not None else None
            self.vsg6_ga__PingJiFang1__MovedGeo = flatten_any(MovedGeo1)

            # ---- PingJiFang2 ----
            TargetPlane2_geo = self.vsg6_PlaneFromLists8__ResultPlane
            xfm2 = getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut", None)
            TargetPlane2 = ghc.Transform(TargetPlane2_geo, xfm2)

            RotateDeg2 = _dbget("vsg6_ga__PingJiFang2__RotateDeg", 0.0)
            FlipX2 = _dbget("vsg6_ga__PingJiFang2__FlipX", False)
            FlipY2 = _dbget("vsg6_ga__PingJiFang2__FlipY", False)
            FlipZ2 = _dbget("vsg6_ga__PingJiFang2__FlipZ", False)
            MoveX2 = _dbget("vsg6_ga__PingJiFang2__MoveX", 0.0)
            MoveY2 = _dbget("vsg6_ga__PingJiFang2__MoveY", 0.0)
            MoveZ2 = _dbget("vsg6_ga__PingJiFang2__MoveZ", 0.0)

            SourceOut2, TargetOut2, TransformOut2, MovedGeo2 = GeoAligner_xfm.align(
                self.vsg6_timber_block4__TimberBrep,
                SourcePlane,
                TargetPlane2,
                rotate_deg=RotateDeg2,
                flip_x=FlipX2,
                flip_y=FlipY2,
                flip_z=FlipZ2,
                move_x=MoveX2,
                move_y=MoveY2,
                move_z=MoveZ2,
            )
            self.vsg6_ga__PingJiFang2__SourceOut = SourceOut2
            self.vsg6_ga__PingJiFang2__TargetOut = TargetOut2
            self.vsg6_ga__PingJiFang2__TransformOut = ght.GH_Transform(
                TransformOut2) if TransformOut2 is not None else None
            self.vsg6_ga__PingJiFang2__MovedGeo = flatten_any(MovedGeo2)

        except Exception as e:
            # 出错时：清空本步关键输出，写入日志
            self.LogLines.append("Step8-6 Error: {}".format(e))
            self.vsg6_timber_block4__TimberBrep = None
            self.vsg6_PlaneFromLists6__ResultPlane = None
            self.vsg6_PlaneFromLists7__ResultPlane = None
            self.vsg6_PlaneFromLists8__ResultPlane = None
            self.vsg6_ga__PingJiFang1__MovedGeo = None
            self.vsg6_ga__PingJiFang2__MovedGeo = None

    def stepN_assemble(self):
        """
        最终组合：把各 step 的 movedGeo / cutTimbers 等按约定加入 ComponentAssembly

        规则：
        - 默认包含所有构件的 *_MovedGeo 输出（与 GH 端口列表一致）
        - 当 EnableChenBu=False 时，不包含“襯補”相关的 8 个构件：
          LaoYanFang1/2、ZhuTouFang1/2、NiuJiFang1/2、PingJiFang1/2
        """
        parts = []

        # === 基础构件（始终包含）===
        _flatten_items(getattr(self, "vsg1_ga__ANG_LU_DOU__MovedGeo", None), parts)

        _flatten_items(getattr(self, "vsg2_ga__ChaAngInLineWNiDaoGong1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg2_ga__ChaAngInLineWNiDaoGong2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg2_ga__JiaoAngInLineWJiaoHuaGong__MovedGeo", None), parts)

        _flatten_items(getattr(self, "vsg3_ga__QiAng_DOU1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg3_ga__QiAng_DOU2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg3_ga__SAN_DOU1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg3_ga__SAN_DOU2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg3_ga__PingPanDou1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg3_ga__PingPanDou2__MovedGeo", None), parts)

        _flatten_items(getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__LingGongInLineWXiaoGongTou2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__ShuaTouInLineWManGong1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__ShuaTouInLineWManGong2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__GuaZiGongInLineWLingGong2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg4_ga__YouAngInLineWJiaoShuaTou__MovedGeo", None), parts)

        _flatten_items(getattr(self, "vsg5_ga__JIAOHU_DOU1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__JIAOHU_DOU2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU1__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU2__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU3__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU4__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU5__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__SAN_DOU6__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg5_ga__PingPanDou__MovedGeo", None), parts)

        # 襯補：寳瓶、八角柱（始终包含）
        _flatten_items(getattr(self, "vsg6_ga__Vase__MovedGeo", None), parts)
        _flatten_items(getattr(self, "vsg6_ga__OctagonPrism__MovedGeo", None), parts)

        # 襯補：檐方/柱头方/扭际方/平基方（受 EnableChenBu 控制）
        if _as_bool(getattr(self, "EnableChenBu", None), default=True):
            _flatten_items(getattr(self, "vsg6_ga__LaoYanFang1__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__LaoYanFang2__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__ZhuTouFang1__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__ZhuTouFang2__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__NiuJiFang1__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__NiuJiFang2__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__PingJiFang1__MovedGeo", None), parts)
            _flatten_items(getattr(self, "vsg6_ga__PingJiFang2__MovedGeo", None), parts)

        self.ComponentAssembly = parts
        self.LogLines.append("Assemble：ComponentAssembly items={}".format(len(parts)))

    # -------------------------------
    # run：串联执行
    # -------------------------------
    def run(self):
        # PlacePlane 默认值
        self.PlacePlane = _coerce_plane(self.PlacePlane, None)
        if self.PlacePlane is None:
            self.PlacePlane = _default_place_plane()

        # Step1
        self.step1_read_db()

        # 后续 Step2/Step3/... 在这里依次串联
        self.step2_build_components()

        # Step3
        self.step3_vsg1_ga__ANG_LU_DOU()

        # Step4-1
        self.step4_1_vsg2_ga__ChaAngInLineWNiDaoGong1()

        # Step4-2
        self.step4_2_vsg2_ga__ChaAngInLineWNiDaoGong2()

        # Step4-3
        self.step4_3_vsg2_ga__JiaoAngInLineWJiaoHuaGong()

        # Step5-1
        self.step5_1_vsg3_PlaneFromLists1()
        self.step5_1_vsg3_ga__QiAng_DOU1()

        # Step5-2
        self.step5_2_vsg3_PlaneFromLists2()
        self.step5_2_vsg3_ga__QiAng_DOU2()

        # Step5-3
        self.step5_3_vsg3_PlaneFromLists3()
        self.step5_3_vsg3_ga__SAN_DOU1()

        # Step5-4
        self.step5_4_vsg3_PlaneFromLists4()
        self.step5_4_vsg3_ga__SAN_DOU2()

        # Step5-5
        self.step5_5_vsg3_PlaneFromLists5()
        self.step5_5_vsg3_ga__PingPanDou1()

        # Step5-6
        self.step5_6_vsg3_PlaneFromLists6()
        self.step5_6_vsg3_ga__PingPanDou2()

        # Step6-1
        self.step6_1_vsg4_ga__LingGongInLineWXiaoGongTou1()

        # Step6-2
        self.step6_2_vsg4_ga__LingGongInLineWXiaoGongTou2()

        # Step6-3
        self.step6_3_vsg4_ga__ShuaTouInLineWManGong1()

        # Step6-4
        self.step6_4_vsg4_ga__ShuaTouInLineWManGong2()

        # Step6-5
        self.step6_5_vsg4_ga__GuaZiGongInLineWLingGong1()

        # Step6-6
        self.step6_6_vsg4_ga__GuaZiGongInLineWLingGong2()

        # Step6-7
        self.step6_7_vsg4_ga__YouAngInLineWJiaoShuaTou()

        # Step7-1
        self.step7_1_vsg5_ga__JIAOHU_DOU1()

        # Step7-2
        self.step7_2_vsg5_ga__JIAOHU_DOU2()

        # Step7-3
        self.step7_3_vsg5_PlaneFromLists1()
        self.step7_3_vsg5_ga__SAN_DOU1()

        # Step7-4
        self.step7_4_vsg5_PlaneFromLists2()
        self.step7_4_vsg5_ga__SAN_DOU2()
        # Step7-5
        self.step7_5_vsg5_PlaneFromLists3()
        self.step7_5_vsg5_ga__SAN_DOU3()
        # Step7-6
        self.step7_6_vsg5_PlaneFromLists4()
        self.step7_6_vsg5_ga__SAN_DOU4()

        # Step7-7
        self.step7_7_vsg5_PlaneFromLists5()
        self.step7_7_vsg5_ga__SAN_DOU5()

        # Step7-8
        self.step7_8_vsg5_PlaneFromLists6()
        self.step7_8_vsg5_ga__SAN_DOU6()

        # Step7-9
        self.step7_9_vsg5_ga__PingPanDou()

        # Step8-1
        self.step8_1_vsg6_ga__Vase()

        # Step8-2
        self.step8_2_vsg6_ga__OctagonPrism()

        # Step8-3
        self.step8_3_vsg6_ga__LaoYanFang12()
        # Step8-4
        self.step8_4_vsg6_ga__ZhuTouFang12()

        # Step8-5
        self.step8_5_vsg6_ga__NiuJiFang12()

        # Step8-6
        self.step8_6_vsg6_ga__PingJiFang12()

        # Assemble
        self.stepN_assemble()

        # Log
        self.Log = "\n".join([str(x) for x in self.LogLines if x is not None])
        return self


# =========================================================
# GhPython 组件输出绑定区（developer-friendly：暴露 solver 成员变量）
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

    try:
        _ecb = EnableChenBu
    except:
        _ecb = True

    solver = SiPU_ChaAng_CornerPU_ComponentAssemblySolver(
        DBPath=_db,
        PlacePlane=_pp,
        Refresh=_rf,
        EnableChenBu=_ecb,
        ghenv=ghenv
    )
    solver.run()

    # --------- 最终成品 ---------
    ComponentAssembly = getattr(solver, "ComponentAssembly", None)
    Log = getattr(solver, "Log", None)

    # --------- Step 1（务必保留，便于核对 All/AllDict）---------
    Value0 = getattr(solver, "Value0", None)
    All0 = getattr(solver, "All0", None)
    AllDict0 = getattr(solver, "AllDict0", None)
    DBLog0 = getattr(solver, "DBLog0", None)

    # --------- 其它内部输出端（后续逐步增加）---------
    PlacePlane_Out = getattr(solver, "PlacePlane", None)

    # --------- Step 2：构件类对外输出（Components.md）---------
    ANG_LU_DOU__CutTimbers = getattr(solver, "ANG_LU_DOU__CutTimbers", None)
    ANG_LU_DOU__FacePlaneList = getattr(solver, "ANG_LU_DOU__FacePlaneList", None)
    QiAng_DOU__CutTimbers = getattr(solver, "QiAng_DOU__CutTimbers", None)
    QiAng_DOU__FacePlaneList = getattr(solver, "QiAng_DOU__FacePlaneList", None)
    SAN_DOU__CutTimbers = getattr(solver, "SAN_DOU__CutTimbers", None)
    SAN_DOU__FacePlaneList = getattr(solver, "SAN_DOU__FacePlaneList", None)
    PingPanDou__CutTimbers = getattr(solver, "PingPanDou__CutTimbers", None)
    PingPanDou__FacePlaneList = getattr(solver, "PingPanDou__FacePlaneList", None)
    JIAOHU_DOU__CutTimbers = getattr(solver, "JIAOHU_DOU__CutTimbers", None)
    JIAOHU_DOU__FacePlaneList = getattr(solver, "JIAOHU_DOU__FacePlaneList", None)
    ChaAngInLineWNiDaoGong2__CutTimbers = getattr(solver, "ChaAngInLineWNiDaoGong2__CutTimbers", None)
    ChaAngInLineWNiDaoGong2__FacePlaneList = getattr(solver, "ChaAngInLineWNiDaoGong2__FacePlaneList", None)
    ChaAngInLineWNiDaoGong2__EdgeMidPoints = getattr(solver, "ChaAngInLineWNiDaoGong2__EdgeMidPoints", None)
    ChaAngInLineWNiDaoGong2__Corner0Planes = getattr(solver, "ChaAngInLineWNiDaoGong2__Corner0Planes", None)
    ChaAngInLineWNiDaoGong1__CutTimbers = getattr(solver, "ChaAngInLineWNiDaoGong1__CutTimbers", None)
    ChaAngInLineWNiDaoGong1__FacePlaneList = getattr(solver, "ChaAngInLineWNiDaoGong1__FacePlaneList", None)
    ChaAngInLineWNiDaoGong1__EdgeMidPoints = getattr(solver, "ChaAngInLineWNiDaoGong1__EdgeMidPoints", None)
    ChaAngInLineWNiDaoGong1__Corner0Planes = getattr(solver, "ChaAngInLineWNiDaoGong1__Corner0Planes", None)
    JiaoAngInLineWJiaoHuaGong__CutTimbers = getattr(solver, "JiaoAngInLineWJiaoHuaGong__CutTimbers", None)
    JiaoAngInLineWJiaoHuaGong__FacePlaneList = getattr(solver, "JiaoAngInLineWJiaoHuaGong__FacePlaneList", None)
    JiaoAngInLineWJiaoHuaGong__EdgeMidPoints = getattr(solver, "JiaoAngInLineWJiaoHuaGong__EdgeMidPoints", None)
    JiaoAngInLineWJiaoHuaGong__Corner0Planes = getattr(solver, "JiaoAngInLineWJiaoHuaGong__Corner0Planes", None)
    LingGongInLineWXiaoGongTou1__CutTimbers = getattr(solver, "LingGongInLineWXiaoGongTou1__CutTimbers", None)
    LingGongInLineWXiaoGongTou1__Skew_Planes = getattr(solver, "LingGongInLineWXiaoGongTou1__Skew_Planes", None)
    LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints = getattr(solver,
                                                                    "LingGongInLineWXiaoGongTou1__SkewTimber_EdgeMidPoints",
                                                                    None)
    LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes = getattr(solver,
                                                                    "LingGongInLineWXiaoGongTou1__SkewTimber_Corner0Planes",
                                                                    None)
    LingGongInLineWXiaoGongTou2__CutTimbers = getattr(solver, "LingGongInLineWXiaoGongTou2__CutTimbers", None)
    LingGongInLineWXiaoGongTou2__Skew_Planes = getattr(solver, "LingGongInLineWXiaoGongTou2__Skew_Planes", None)
    LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints = getattr(solver,
                                                                    "LingGongInLineWXiaoGongTou2__SkewTimber_EdgeMidPoints",
                                                                    None)
    LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes = getattr(solver,
                                                                    "LingGongInLineWXiaoGongTou2__SkewTimber_Corner0Planes",
                                                                    None)
    ShuaTouInLineWManGong1__CutTimbers = getattr(solver, "ShuaTouInLineWManGong1__CutTimbers", None)
    ShuaTouInLineWManGong1__Skew_Planes = getattr(solver, "ShuaTouInLineWManGong1__Skew_Planes", None)
    ShuaTouInLineWManGong1__Skew_Point_C = getattr(solver, "ShuaTouInLineWManGong1__Skew_Point_C", None)
    ShuaTouInLineWManGong1__EdgeMidPoints = getattr(solver, "ShuaTouInLineWManGong1__EdgeMidPoints", None)
    ShuaTouInLineWManGong1__Corner0Planes = getattr(solver, "ShuaTouInLineWManGong1__Corner0Planes", None)
    ShuaTouInLineWManGong2__CutTimbers = getattr(solver, "ShuaTouInLineWManGong2__CutTimbers", None)
    ShuaTouInLineWManGong2__Skew_Planes = getattr(solver, "ShuaTouInLineWManGong2__Skew_Planes", None)
    ShuaTouInLineWManGong2__Skew_Point_C = getattr(solver, "ShuaTouInLineWManGong2__Skew_Point_C", None)
    ShuaTouInLineWManGong2__EdgeMidPoints = getattr(solver, "ShuaTouInLineWManGong2__EdgeMidPoints", None)
    ShuaTouInLineWManGong2__Corner0Planes = getattr(solver, "ShuaTouInLineWManGong2__Corner0Planes", None)
    GuaZiGongInLineWLingGong1__CutTimbers = getattr(solver, "GuaZiGongInLineWLingGong1__CutTimbers", None)
    GuaZiGongInLineWLingGong1__Skew_Planes = getattr(solver, "GuaZiGongInLineWLingGong1__Skew_Planes", None)
    GuaZiGongInLineWLingGong1__EdgeMidPoints = getattr(solver, "GuaZiGongInLineWLingGong1__EdgeMidPoints", None)
    GuaZiGongInLineWLingGong1__Corner0Planes = getattr(solver, "GuaZiGongInLineWLingGong1__Corner0Planes", None)
    GuaZiGongInLineWLingGong2__CutTimbers = getattr(solver, "GuaZiGongInLineWLingGong2__CutTimbers", None)
    GuaZiGongInLineWLingGong2__Skew_Planes = getattr(solver, "GuaZiGongInLineWLingGong2__Skew_Planes", None)
    GuaZiGongInLineWLingGong2__EdgeMidPoints = getattr(solver, "GuaZiGongInLineWLingGong2__EdgeMidPoints", None)
    GuaZiGongInLineWLingGong2__Corner0Planes = getattr(solver, "GuaZiGongInLineWLingGong2__Corner0Planes", None)
    YouAngInLineWJiaoShuaTou__CutTimbers = getattr(solver, "YouAngInLineWJiaoShuaTou__CutTimbers", None)
    YouAngInLineWJiaoShuaTou__Skew_Point_C = getattr(solver, "TimberBlock_SkewAxis_M__Skew_Point_C", None)
    YouAngInLineWJiaoShuaTou__Skew_Planes = getattr(solver, "TimberBlock_SkewAxis_M__Skew_Planes", None)
    YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues = getattr(solver, "YouAngInLineWJiaoShuaTou__YouAng__Ang_PtsValues",
                                                              None)
    YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut = getattr(solver,
                                                                          "YouAngInLineWJiaoShuaTou__AlignToolToTimber_9__TransformOut",
                                                                          None)
    YouAngInLineWJiaoShuaTou__Corner0Planes = getattr(solver, "YouAngInLineWJiaoShuaTou__Corner0Planes", None)
    Vase__CutTimbers = getattr(solver, "Vase__CutTimbers", None)
    Vase__base_ref_plane = getattr(solver, "Vase__base_ref_plane", None)
    OctagonPrism__PrismBrep = getattr(solver, "OctagonPrism__PrismBrep", None)
    OctagonPrism__RefPlane_BP = getattr(solver, "OctagonPrism__RefPlane_BP", None)

    # --------- Step 3：叠次-1：角櫨枓（vsg1_ga__ANG_LU_DOU）---------
    vsg1_ga__ANG_LU_DOU__SourceOut = getattr(solver, "vsg1_ga__ANG_LU_DOU__SourceOut", None)
    vsg1_ga__ANG_LU_DOU__TargetOut = getattr(solver, "vsg1_ga__ANG_LU_DOU__TargetOut", None)
    vsg1_ga__ANG_LU_DOU__TransformOut = getattr(solver, "vsg1_ga__ANG_LU_DOU__TransformOut", None)
    vsg1_ga__ANG_LU_DOU__MovedGeo = getattr(solver, "vsg1_ga__ANG_LU_DOU__MovedGeo", None)

    # --------- Step 4-1：叠次-2：插昂與泥道栱相列一（vsg2_ga__ChaAngInLineWNiDaoGong1）---------
    vsg2_ga__ChaAngInLineWNiDaoGong1__SourceOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong1__SourceOut", None)
    vsg2_ga__ChaAngInLineWNiDaoGong1__TargetOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong1__TargetOut", None)
    vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong1__TransformOut",
                                                             None)
    vsg2_ga__ChaAngInLineWNiDaoGong1__MovedGeo = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong1__MovedGeo", None)

    # --------- Step 4-2：叠次-2：插昂與泥道栱相列二（vsg2_ga__ChaAngInLineWNiDaoGong2）---------
    vsg2_ga__ChaAngInLineWNiDaoGong2__SourceOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong2__SourceOut", None)
    vsg2_ga__ChaAngInLineWNiDaoGong2__TargetOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong2__TargetOut", None)
    vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong2__TransformOut",
                                                             None)
    vsg2_ga__ChaAngInLineWNiDaoGong2__MovedGeo = getattr(solver, "vsg2_ga__ChaAngInLineWNiDaoGong2__MovedGeo", None)

    # --------- Step 4-3：叠次-2：插昂與泥道栱相列二角昂與角華栱相列（vsg2_ga__JiaoAngInLineWJiaoHuaGong）---------
    vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourceOut = getattr(solver, "vsg2_ga__JiaoAngInLineWJiaoHuaGong__SourceOut",
                                                            None)
    vsg2_ga__JiaoAngInLineWJiaoHuaGong__TargetOut = getattr(solver, "vsg2_ga__JiaoAngInLineWJiaoHuaGong__TargetOut",
                                                            None)
    vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut = getattr(solver,
                                                               "vsg2_ga__JiaoAngInLineWJiaoHuaGong__TransformOut", None)
    vsg2_ga__JiaoAngInLineWJiaoHuaGong__MovedGeo = getattr(solver, "vsg2_ga__JiaoAngInLineWJiaoHuaGong__MovedGeo", None)

    # --------- Step 5-1：叠次-3：騎昂枓1（vsg3_PlaneFromLists1 / vsg3_ga__QiAng_DOU1）---------
    vsg3_PlaneFromLists1__BasePlane = getattr(solver, "vsg3_PlaneFromLists1__BasePlane", None)
    vsg3_PlaneFromLists1__OriginPoint = getattr(solver, "vsg3_PlaneFromLists1__OriginPoint", None)
    vsg3_PlaneFromLists1__ResultPlane = getattr(solver, "vsg3_PlaneFromLists1__ResultPlane", None)
    vsg3_PlaneFromLists1__Log = getattr(solver, "vsg3_PlaneFromLists1__Log", None)

    vsg3_ga__QiAng_DOU1__SourceOut = getattr(solver, "vsg3_ga__QiAng_DOU1__SourceOut", None)
    vsg3_ga__QiAng_DOU1__TargetOut = getattr(solver, "vsg3_ga__QiAng_DOU1__TargetOut", None)
    vsg3_ga__QiAng_DOU1__TransformOut = getattr(solver, "vsg3_ga__QiAng_DOU1__TransformOut", None)
    vsg3_ga__QiAng_DOU1__MovedGeo = getattr(solver, "vsg3_ga__QiAng_DOU1__MovedGeo", None)

    # --------- Step 5-2（vsg3_PlaneFromLists2 / vsg3_ga__QiAng_DOU2）---------
    vsg3_PlaneFromLists2__BasePlane = getattr(solver, "vsg3_PlaneFromLists2__BasePlane", None)
    vsg3_PlaneFromLists2__OriginPoint = getattr(solver, "vsg3_PlaneFromLists2__OriginPoint", None)
    vsg3_PlaneFromLists2__ResultPlane = getattr(solver, "vsg3_PlaneFromLists2__ResultPlane", None)
    vsg3_PlaneFromLists2__Log = getattr(solver, "vsg3_PlaneFromLists2__Log", None)

    vsg3_ga__QiAng_DOU2__SourceOut = getattr(solver, "vsg3_ga__QiAng_DOU2__SourceOut", None)
    vsg3_ga__QiAng_DOU2__TargetOut = getattr(solver, "vsg3_ga__QiAng_DOU2__TargetOut", None)
    vsg3_ga__QiAng_DOU2__TransformOut = getattr(solver, "vsg3_ga__QiAng_DOU2__TransformOut", None)
    vsg3_ga__QiAng_DOU2__MovedGeo = getattr(solver, "vsg3_ga__QiAng_DOU2__MovedGeo", None)

    # --------- Step 5-3（vsg3_PlaneFromLists3 / vsg3_ga__SAN_DOU1）---------
    vsg3_PlaneFromLists3__BasePlane = getattr(solver, "vsg3_PlaneFromLists3__BasePlane", None)
    vsg3_PlaneFromLists3__OriginPoint = getattr(solver, "vsg3_PlaneFromLists3__OriginPoint", None)
    vsg3_PlaneFromLists3__ResultPlane = getattr(solver, "vsg3_PlaneFromLists3__ResultPlane", None)
    vsg3_PlaneFromLists3__Log = getattr(solver, "vsg3_PlaneFromLists3__Log", None)

    vsg3_ga__SAN_DOU1__SourceOut = getattr(solver, "vsg3_ga__SAN_DOU1__SourceOut", None)
    vsg3_ga__SAN_DOU1__TargetOut = getattr(solver, "vsg3_ga__SAN_DOU1__TargetOut", None)
    vsg3_ga__SAN_DOU1__TransformOut = getattr(solver, "vsg3_ga__SAN_DOU1__TransformOut", None)
    vsg3_ga__SAN_DOU1__MovedGeo = getattr(solver, "vsg3_ga__SAN_DOU1__MovedGeo", None)

    # --------- Step 5-4（vsg3_PlaneFromLists4 / vsg3_ga__SAN_DOU2）---------
    vsg3_PlaneFromLists4__BasePlane = getattr(solver, "vsg3_PlaneFromLists4__BasePlane", None)
    vsg3_PlaneFromLists4__OriginPoint = getattr(solver, "vsg3_PlaneFromLists4__OriginPoint", None)
    vsg3_PlaneFromLists4__ResultPlane = getattr(solver, "vsg3_PlaneFromLists4__ResultPlane", None)
    vsg3_PlaneFromLists4__Log = getattr(solver, "vsg3_PlaneFromLists4__Log", None)

    vsg3_ga__SAN_DOU2__SourceOut = getattr(solver, "vsg3_ga__SAN_DOU2__SourceOut", None)
    vsg3_ga__SAN_DOU2__TargetOut = getattr(solver, "vsg3_ga__SAN_DOU2__TargetOut", None)
    vsg3_ga__SAN_DOU2__TransformOut = getattr(solver, "vsg3_ga__SAN_DOU2__TransformOut", None)
    vsg3_ga__SAN_DOU2__MovedGeo = getattr(solver, "vsg3_ga__SAN_DOU2__MovedGeo", None)

    # --------- Step 5-5（vsg3_PlaneFromLists5 / vsg3_ga__PingPanDou1）---------
    vsg3_PlaneFromLists5__BasePlane = getattr(solver, "vsg3_PlaneFromLists5__BasePlane", None)
    vsg3_PlaneFromLists5__OriginPoint = getattr(solver, "vsg3_PlaneFromLists5__OriginPoint", None)
    vsg3_PlaneFromLists5__ResultPlane = getattr(solver, "vsg3_PlaneFromLists5__ResultPlane", None)
    vsg3_PlaneFromLists5__Log = getattr(solver, "vsg3_PlaneFromLists5__Log", None)

    vsg3_ga__PingPanDou1__SourceOut = getattr(solver, "vsg3_ga__PingPanDou1__SourceOut", None)
    vsg3_ga__PingPanDou1__TargetOut = getattr(solver, "vsg3_ga__PingPanDou1__TargetOut", None)
    vsg3_ga__PingPanDou1__TransformOut = getattr(solver, "vsg3_ga__PingPanDou1__TransformOut", None)
    vsg3_ga__PingPanDou1__MovedGeo = getattr(solver, "vsg3_ga__PingPanDou1__MovedGeo", None)

    # --------- Step 5-6：叠次-3：平盤枓2 ---------
    vsg3_PlaneFromLists6__BasePlane = getattr(solver, "vsg3_PlaneFromLists6__BasePlane", None)
    vsg3_PlaneFromLists6__OriginPoint = getattr(solver, "vsg3_PlaneFromLists6__OriginPoint", None)
    vsg3_PlaneFromLists6__ResultPlane = getattr(solver, "vsg3_PlaneFromLists6__ResultPlane", None)
    vsg3_PlaneFromLists6__Log = getattr(solver, "vsg3_PlaneFromLists6__Log", None)

    vsg3_ga__PingPanDou2__SourceOut = getattr(solver, "vsg3_ga__PingPanDou2__SourceOut", None)
    vsg3_ga__PingPanDou2__TargetOut = getattr(solver, "vsg3_ga__PingPanDou2__TargetOut", None)
    vsg3_ga__PingPanDou2__TransformOut = getattr(solver, "vsg3_ga__PingPanDou2__TransformOut", None)
    vsg3_ga__PingPanDou2__MovedGeo = getattr(solver, "vsg3_ga__PingPanDou2__MovedGeo", None)

    # --------- Step 6-1：叠次-4：令栱與小栱頭相列一 ---------
    vsg4_ga__LingGongInLineWXiaoGongTou1__SourceOut = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou1__SourceOut",
                                                              None)
    vsg4_ga__LingGongInLineWXiaoGongTou1__TargetOut = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou1__TargetOut",
                                                              None)
    vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut = getattr(solver,
                                                                 "vsg4_ga__LingGongInLineWXiaoGongTou1__TransformOut",
                                                                 None)
    vsg4_ga__LingGongInLineWXiaoGongTou1__MovedGeo = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou1__MovedGeo",
                                                             None)

    # --------- Step 6-2：叠次-4：令栱與小栱頭相列二 ---------
    vsg4_ga__LingGongInLineWXiaoGongTou2__SourceOut = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou2__SourceOut",
                                                              None)
    vsg4_ga__LingGongInLineWXiaoGongTou2__TargetOut = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou2__TargetOut",
                                                              None)
    vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut = getattr(solver,
                                                                 "vsg4_ga__LingGongInLineWXiaoGongTou2__TransformOut",
                                                                 None)
    vsg4_ga__LingGongInLineWXiaoGongTou2__MovedGeo = getattr(solver, "vsg4_ga__LingGongInLineWXiaoGongTou2__MovedGeo",
                                                             None)

    # --------- Step 6-3：叠次-4：耍頭與慢栱相列一 ---------
    vsg4_ga__ShuaTouInLineWManGong1__SourceOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong1__SourceOut", None)
    vsg4_ga__ShuaTouInLineWManGong1__TargetOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong1__TargetOut", None)
    vsg4_ga__ShuaTouInLineWManGong1__TransformOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong1__TransformOut",
                                                            None)
    vsg4_ga__ShuaTouInLineWManGong1__MovedGeo = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong1__MovedGeo", None)

    # --------- Step 6-4：叠次-4：耍頭與慢栱相列二 ---------
    vsg4_ga__ShuaTouInLineWManGong2__SourceOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong2__SourceOut", None)
    vsg4_ga__ShuaTouInLineWManGong2__TargetOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong2__TargetOut", None)
    vsg4_ga__ShuaTouInLineWManGong2__TransformOut = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong2__TransformOut",
                                                            None)
    vsg4_ga__ShuaTouInLineWManGong2__MovedGeo = getattr(solver, "vsg4_ga__ShuaTouInLineWManGong2__MovedGeo", None)

    # --------- Step 6-5：叠次-4：瓜子栱與令栱相列一 ---------
    vsg4_ga__GuaZiGongInLineWLingGong1__SourceOut = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong1__SourceOut",
                                                            None)
    vsg4_ga__GuaZiGongInLineWLingGong1__TargetOut = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong1__TargetOut",
                                                            None)
    vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut = getattr(solver,
                                                               "vsg4_ga__GuaZiGongInLineWLingGong1__TransformOut", None)
    vsg4_ga__GuaZiGongInLineWLingGong1__MovedGeo = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong1__MovedGeo", None)

    # --------- Step 6-6：叠次-4：瓜子栱與令栱相列二 ---------
    vsg4_ga__GuaZiGongInLineWLingGong2__SourceOut = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong2__SourceOut",
                                                            None)
    vsg4_ga__GuaZiGongInLineWLingGong2__TargetOut = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong2__TargetOut",
                                                            None)
    vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut = getattr(solver,
                                                               "vsg4_ga__GuaZiGongInLineWLingGong2__TransformOut", None)
    vsg4_ga__GuaZiGongInLineWLingGong2__MovedGeo = getattr(solver, "vsg4_ga__GuaZiGongInLineWLingGong2__MovedGeo", None)

    # --------- Step 6-7：叠次-4：由昂與角耍頭相列 ---------
    vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = getattr(
        solver, "vsg4_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out", None
    )

    vsg4_ga__YouAngInLineWJiaoShuaTou__SourceOut = getattr(solver, "vsg4_ga__YouAngInLineWJiaoShuaTou__SourceOut", None)
    vsg4_ga__YouAngInLineWJiaoShuaTou__TargetOut = getattr(solver, "vsg4_ga__YouAngInLineWJiaoShuaTou__TargetOut", None)
    vsg4_ga__YouAngInLineWJiaoShuaTou__TransformOut = getattr(solver, "vsg4_ga__YouAngInLineWJiaoShuaTou__TransformOut",
                                                              None)
    vsg4_ga__YouAngInLineWJiaoShuaTou__MovedGeo = getattr(solver, "vsg4_ga__YouAngInLineWJiaoShuaTou__MovedGeo", None)

    # --------- Step7-1：叠次-5：交互枓-1 ---------
    vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out = getattr(
        solver, "vsg5_TreeItem_ListItem_PlaneOrigin_Transform1__Transform_Geometry_Out", None
    )

    vsg5_ga__JIAOHU_DOU1__SourceOut = getattr(solver, "vsg5_ga__JIAOHU_DOU1__SourceOut", None)
    vsg5_ga__JIAOHU_DOU1__TargetOut = getattr(solver, "vsg5_ga__JIAOHU_DOU1__TargetOut", None)
    vsg5_ga__JIAOHU_DOU1__MovedGeo = getattr(solver, "vsg5_ga__JIAOHU_DOU1__MovedGeo", None)

    # --------- Step7-2：叠次-5：交互枓-2 ---------
    vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out = getattr(
        solver, "vsg5_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out", None
    )

    vsg5_ga__JIAOHU_DOU2__SourceOut = getattr(solver, "vsg5_ga__JIAOHU_DOU2__SourceOut", None)
    vsg5_ga__JIAOHU_DOU2__TargetOut = getattr(solver, "vsg5_ga__JIAOHU_DOU2__TargetOut", None)
    vsg5_ga__JIAOHU_DOU2__MovedGeo = getattr(solver, "vsg5_ga__JIAOHU_DOU2__MovedGeo", None)

    # --------- Step7-3：叠次-5：散枓-1 ---------
    vsg5_PlaneFromLists1__BasePlane = getattr(solver, "vsg5_PlaneFromLists1__BasePlane", None)
    vsg5_PlaneFromLists1__OriginPoint = getattr(solver, "vsg5_PlaneFromLists1__OriginPoint", None)
    vsg5_PlaneFromLists1__ResultPlane = getattr(solver, "vsg5_PlaneFromLists1__ResultPlane", None)
    vsg5_PlaneFromLists1__Log = getattr(solver, "vsg5_PlaneFromLists1__Log", None)

    vsg5_ga__SAN_DOU1__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU1__SourceOut", None)
    vsg5_ga__SAN_DOU1__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU1__TargetOut", None)
    vsg5_ga__SAN_DOU1__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU1__TransformOut", None)
    vsg5_ga__SAN_DOU1__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU1__MovedGeo", None)

    # --------- Step7-4：叠次-5：散枓-2 ---------
    vsg5_PlaneFromLists2__BasePlane = getattr(solver, "vsg5_PlaneFromLists2__BasePlane", None)
    vsg5_PlaneFromLists2__OriginPoint = getattr(solver, "vsg5_PlaneFromLists2__OriginPoint", None)
    vsg5_PlaneFromLists2__ResultPlane = getattr(solver, "vsg5_PlaneFromLists2__ResultPlane", None)
    vsg5_PlaneFromLists2__Log = getattr(solver, "vsg5_PlaneFromLists2__Log", None)

    vsg5_ga__SAN_DOU2__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU2__SourceOut", None)
    vsg5_ga__SAN_DOU2__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU2__TargetOut", None)
    vsg5_ga__SAN_DOU2__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU2__TransformOut", None)
    vsg5_ga__SAN_DOU2__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU2__MovedGeo", None)

    # --------- Step7-5：叠次-5：散枓-3 ---------
    vsg5_PlaneFromLists3__BasePlane = getattr(solver, "vsg5_PlaneFromLists3__BasePlane", None)
    vsg5_PlaneFromLists3__OriginPoint = getattr(solver, "vsg5_PlaneFromLists3__OriginPoint", None)
    vsg5_PlaneFromLists3__ResultPlane = getattr(solver, "vsg5_PlaneFromLists3__ResultPlane", None)
    vsg5_PlaneFromLists3__Log = getattr(solver, "vsg5_PlaneFromLists3__Log", None)

    vsg5_ga__SAN_DOU3__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU3__SourceOut", None)
    vsg5_ga__SAN_DOU3__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU3__TargetOut", None)
    vsg5_ga__SAN_DOU3__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU3__TransformOut", None)
    vsg5_ga__SAN_DOU3__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU3__MovedGeo", None)

    # --------- Step7-6：叠次-5：散枓-4 ---------
    vsg5_PlaneFromLists4__BasePlane = getattr(solver, "vsg5_PlaneFromLists4__BasePlane", None)
    vsg5_PlaneFromLists4__OriginPoint = getattr(solver, "vsg5_PlaneFromLists4__OriginPoint", None)
    vsg5_PlaneFromLists4__ResultPlane = getattr(solver, "vsg5_PlaneFromLists4__ResultPlane", None)
    vsg5_PlaneFromLists4__Log = getattr(solver, "vsg5_PlaneFromLists4__Log", None)

    vsg5_ga__SAN_DOU4__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU4__SourceOut", None)
    vsg5_ga__SAN_DOU4__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU4__TargetOut", None)
    vsg5_ga__SAN_DOU4__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU4__TransformOut", None)
    vsg5_ga__SAN_DOU4__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU4__MovedGeo", None)

    # --------- Step7-7：叠次-5：散枓-5 ---------
    vsg5_PlaneFromLists5__BasePlane = getattr(solver, "vsg5_PlaneFromLists5__BasePlane", None)
    vsg5_PlaneFromLists5__OriginPoint = getattr(solver, "vsg5_PlaneFromLists5__OriginPoint", None)
    vsg5_PlaneFromLists5__ResultPlane = getattr(solver, "vsg5_PlaneFromLists5__ResultPlane", None)
    vsg5_PlaneFromLists5__Log = getattr(solver, "vsg5_PlaneFromLists5__Log", None)

    vsg5_ga__SAN_DOU5__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU5__SourceOut", None)
    vsg5_ga__SAN_DOU5__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU5__TargetOut", None)
    vsg5_ga__SAN_DOU5__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU5__TransformOut", None)
    vsg5_ga__SAN_DOU5__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU5__MovedGeo", None)

    # --------- Step7-8：叠次-5：散枓-6 ---------
    vsg5_PlaneFromLists6__BasePlane = getattr(solver, "vsg5_PlaneFromLists6__BasePlane", None)
    vsg5_PlaneFromLists6__OriginPoint = getattr(solver, "vsg5_PlaneFromLists6__OriginPoint", None)
    vsg5_PlaneFromLists6__ResultPlane = getattr(solver, "vsg5_PlaneFromLists6__ResultPlane", None)
    vsg5_PlaneFromLists6__Log = getattr(solver, "vsg5_PlaneFromLists6__Log", None)

    vsg5_ga__SAN_DOU6__SourceOut = getattr(solver, "vsg5_ga__SAN_DOU6__SourceOut", None)
    vsg5_ga__SAN_DOU6__TargetOut = getattr(solver, "vsg5_ga__SAN_DOU6__TargetOut", None)
    vsg5_ga__SAN_DOU6__TransformOut = getattr(solver, "vsg5_ga__SAN_DOU6__TransformOut", None)
    vsg5_ga__SAN_DOU6__MovedGeo = getattr(solver, "vsg5_ga__SAN_DOU6__MovedGeo", None)

    # --------- Step7-9：叠次-5：平盤枓 ---------
    vsg5_ga__PingPanDou__SourceOut = getattr(solver, "vsg5_ga__PingPanDou__SourceOut", None)
    vsg5_ga__PingPanDou__TargetOut = getattr(solver, "vsg5_ga__PingPanDou__TargetOut", None)
    vsg5_ga__PingPanDou__TransformOut = getattr(solver, "vsg5_ga__PingPanDou__TransformOut", None)
    vsg5_ga__PingPanDou__MovedGeo = getattr(solver, "vsg5_ga__PingPanDou__MovedGeo", None)

    vsg5_ga__PingPanDou__TargetPlane_Transform1 = getattr(solver, "vsg5_ga__PingPanDou__TargetPlane_Transform1", None)
    vsg5_ga__PingPanDou__TargetPlane_PlaneOrigin = getattr(solver, "vsg5_ga__PingPanDou__TargetPlane_PlaneOrigin", None)
    vsg5_ga__PingPanDou__TargetPlane_Transform2 = getattr(solver, "vsg5_ga__PingPanDou__TargetPlane_Transform2", None)

    # --------- Step8-1：叠次-6：寳瓶 ---------
    vsg6_ga__Vase__SourceOut = getattr(solver, "vsg6_ga__Vase__SourceOut", None)
    vsg6_ga__Vase__TargetOut = getattr(solver, "vsg6_ga__Vase__TargetOut", None)
    vsg6_ga__Vase__MovedGeo = getattr(solver, "vsg6_ga__Vase__MovedGeo", None)
    vsg6_ga__Vase__TargetPlane_Transform = getattr(solver, "vsg6_ga__Vase__TargetPlane_Transform", None)

    # --------- Step8-2：叠次-6：八角柱 ---------
    vsg6_ga__OctagonPrism__SourceOut = getattr(solver, "vsg6_ga__OctagonPrism__SourceOut", None)
    vsg6_ga__OctagonPrism__TargetOut = getattr(solver, "vsg6_ga__OctagonPrism__TargetOut", None)
    vsg6_ga__OctagonPrism__MovedGeo = getattr(solver, "vsg6_ga__OctagonPrism__MovedGeo", None)
    vsg6_ga__OctagonPrism__TargetPlane_Transform = getattr(solver, "vsg6_ga__OctagonPrism__TargetPlane_Transform", None)
    vsg6_ga__OctagonPrism__TransformOut = getattr(solver, "vsg6_ga__OctagonPrism__TransformOut", None)

    # --------- Step8-3：叠次-6：橑檐方一、橑檐方二 ---------
    vsg6_timber_block1__TimberBrep = getattr(solver, "vsg6_timber_block1__TimberBrep", None)
    vsg6_timber_block1__EdgeMidPoints = getattr(solver, "vsg6_timber_block1__EdgeMidPoints", None)
    vsg6_timber_block1__Corner0Planes = getattr(solver, "vsg6_timber_block1__Corner0Planes", None)
    vsg6_timber_block1__FacePlaneList = getattr(solver, "vsg6_timber_block1__FacePlaneList", None)
    vsg6_timber_block1__LocalAxesPlane = getattr(solver, "vsg6_timber_block1__LocalAxesPlane", None)
    vsg6_timber_block1__AxisX = getattr(solver, "vsg6_timber_block1__AxisX", None)
    vsg6_timber_block1__AxisY = getattr(solver, "vsg6_timber_block1__AxisY", None)
    vsg6_timber_block1__AxisZ = getattr(solver, "vsg6_timber_block1__AxisZ", None)
    vsg6_timber_block1__Log = getattr(solver, "vsg6_timber_block1__Log", None)

    vsg6_PlaneFromLists1__BasePlane = getattr(solver, "vsg6_PlaneFromLists1__BasePlane", None)
    vsg6_PlaneFromLists1__OriginPoint = getattr(solver, "vsg6_PlaneFromLists1__OriginPoint", None)
    vsg6_PlaneFromLists1__ResultPlane = getattr(solver, "vsg6_PlaneFromLists1__ResultPlane", None)
    vsg6_PlaneFromLists1__Log = getattr(solver, "vsg6_PlaneFromLists1__Log", None)

    vsg6_PlaneFromLists2__BasePlane = getattr(solver, "vsg6_PlaneFromLists2__BasePlane", None)
    vsg6_PlaneFromLists2__OriginPoint = getattr(solver, "vsg6_PlaneFromLists2__OriginPoint", None)
    vsg6_PlaneFromLists2__ResultPlane = getattr(solver, "vsg6_PlaneFromLists2__ResultPlane", None)
    vsg6_PlaneFromLists2__Log = getattr(solver, "vsg6_PlaneFromLists2__Log", None)

    vsg6_PlaneFromLists3__BasePlane = getattr(solver, "vsg6_PlaneFromLists3__BasePlane", None)
    vsg6_PlaneFromLists3__OriginPoint = getattr(solver, "vsg6_PlaneFromLists3__OriginPoint", None)
    vsg6_PlaneFromLists3__ResultPlane = getattr(solver, "vsg6_PlaneFromLists3__ResultPlane", None)
    vsg6_PlaneFromLists3__Log = getattr(solver, "vsg6_PlaneFromLists3__Log", None)

    vsg6_ga__LaoYanFang1__SourceOut = getattr(solver, "vsg6_ga__LaoYanFang1__SourceOut", None)
    vsg6_ga__LaoYanFang1__TargetOut = getattr(solver, "vsg6_ga__LaoYanFang1__TargetOut", None)
    vsg6_ga__LaoYanFang1__TransformOut = getattr(solver, "vsg6_ga__LaoYanFang1__TransformOut", None)
    vsg6_ga__LaoYanFang1__MovedGeo = getattr(solver, "vsg6_ga__LaoYanFang1__MovedGeo", None)
    vsg6_ga__LaoYanFang1__TargetPlane_Transform = getattr(solver, "vsg6_ga__LaoYanFang1__TargetPlane_Transform", None)

    vsg6_ga__LaoYanFang2__SourceOut = getattr(solver, "vsg6_ga__LaoYanFang2__SourceOut", None)
    vsg6_ga__LaoYanFang2__TargetOut = getattr(solver, "vsg6_ga__LaoYanFang2__TargetOut", None)
    vsg6_ga__LaoYanFang2__TransformOut = getattr(solver, "vsg6_ga__LaoYanFang2__TransformOut", None)
    vsg6_ga__LaoYanFang2__MovedGeo = getattr(solver, "vsg6_ga__LaoYanFang2__MovedGeo", None)
    vsg6_ga__LaoYanFang2__TargetPlane_Transform = getattr(solver, "vsg6_ga__LaoYanFang2__TargetPlane_Transform", None)

    # --------- Step8-4：叠次-6：柱頭方一、柱頭方二 ---------
    vsg6_timber_block2__TimberBrep = getattr(solver, "vsg6_timber_block2__TimberBrep", None)
    vsg6_timber_block2__EdgeMidPoints = getattr(solver, "vsg6_timber_block2__EdgeMidPoints", None)
    vsg6_timber_block2__Corner0Planes = getattr(solver, "vsg6_timber_block2__Corner0Planes", None)
    vsg6_timber_block2__FacePlaneList = getattr(solver, "vsg6_timber_block2__FacePlaneList", None)
    vsg6_timber_block2__LocalAxesPlane = getattr(solver, "vsg6_timber_block2__LocalAxesPlane", None)
    vsg6_timber_block2__AxisX = getattr(solver, "vsg6_timber_block2__AxisX", None)
    vsg6_timber_block2__AxisY = getattr(solver, "vsg6_timber_block2__AxisY", None)
    vsg6_timber_block2__AxisZ = getattr(solver, "vsg6_timber_block2__AxisZ", None)
    vsg6_timber_block2__Log = getattr(solver, "vsg6_timber_block2__Log", None)

    vsg6_PlaneFromLists4__BasePlane = getattr(solver, "vsg6_PlaneFromLists4__BasePlane", None)
    vsg6_PlaneFromLists4__OriginPoint = getattr(solver, "vsg6_PlaneFromLists4__OriginPoint", None)
    vsg6_PlaneFromLists4__ResultPlane = getattr(solver, "vsg6_PlaneFromLists4__ResultPlane", None)
    vsg6_PlaneFromLists4__Log = getattr(solver, "vsg6_PlaneFromLists4__Log", None)

    vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out = getattr(solver,
                                                                                    "vsg6_TreeItem_ListItem_PlaneOrigin_Transform2__Transform_Geometry_Out",
                                                                                    None)
    vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__Transform_Geometry_Out = getattr(solver,
                                                                                    "vsg6_TreeItem_ListItem_PlaneOrigin_Transform3__Transform_Geometry_Out",
                                                                                    None)

    vsg6_ga__ZhuTouFang1__SourceOut = getattr(solver, "vsg6_ga__ZhuTouFang1__SourceOut", None)
    vsg6_ga__ZhuTouFang1__TargetOut = getattr(solver, "vsg6_ga__ZhuTouFang1__TargetOut", None)
    vsg6_ga__ZhuTouFang1__TransformOut = getattr(solver, "vsg6_ga__ZhuTouFang1__TransformOut", None)
    vsg6_ga__ZhuTouFang1__MovedGeo = getattr(solver, "vsg6_ga__ZhuTouFang1__MovedGeo", None)

    vsg6_ga__ZhuTouFang2__SourceOut = getattr(solver, "vsg6_ga__ZhuTouFang2__SourceOut", None)
    vsg6_ga__ZhuTouFang2__TargetOut = getattr(solver, "vsg6_ga__ZhuTouFang2__TargetOut", None)
    vsg6_ga__ZhuTouFang2__TransformOut = getattr(solver, "vsg6_ga__ZhuTouFang2__TransformOut", None)
    vsg6_ga__ZhuTouFang2__MovedGeo = getattr(solver, "vsg6_ga__ZhuTouFang2__MovedGeo", None)

    # --------- Step8-5：叠次-6：牛脊方一、牛脊方二 ---------
    vsg6_timber_block3__TimberBrep = getattr(solver, "vsg6_timber_block3__TimberBrep", None)
    vsg6_timber_block3__EdgeMidPoints = getattr(solver, "vsg6_timber_block3__EdgeMidPoints", None)
    vsg6_timber_block3__Corner0Planes = getattr(solver, "vsg6_timber_block3__Corner0Planes", None)
    vsg6_timber_block3__FacePlaneList = getattr(solver, "vsg6_timber_block3__FacePlaneList", None)
    vsg6_timber_block3__LocalAxesPlane = getattr(solver, "vsg6_timber_block3__LocalAxesPlane", None)
    vsg6_timber_block3__AxisX = getattr(solver, "vsg6_timber_block3__AxisX", None)
    vsg6_timber_block3__AxisY = getattr(solver, "vsg6_timber_block3__AxisY", None)
    vsg6_timber_block3__AxisZ = getattr(solver, "vsg6_timber_block3__AxisZ", None)
    vsg6_timber_block3__Log = getattr(solver, "vsg6_timber_block3__Log", None)

    vsg6_PlaneFromLists5__BasePlane = getattr(solver, "vsg6_PlaneFromLists5__BasePlane", None)
    vsg6_PlaneFromLists5__OriginPoint = getattr(solver, "vsg6_PlaneFromLists5__OriginPoint", None)
    vsg6_PlaneFromLists5__ResultPlane = getattr(solver, "vsg6_PlaneFromLists5__ResultPlane", None)
    vsg6_PlaneFromLists5__Log = getattr(solver, "vsg6_PlaneFromLists5__Log", None)

    vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__Transform_Geometry_Out = getattr(solver,
                                                                                    "vsg6_TreeItem_ListItem_PlaneOrigin_Transform4__Transform_Geometry_Out",
                                                                                    None)
    vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__Transform_Geometry_Out = getattr(solver,
                                                                                    "vsg6_TreeItem_ListItem_PlaneOrigin_Transform5__Transform_Geometry_Out",
                                                                                    None)

    vsg6_ga__NiuJiFang1__SourceOut = getattr(solver, "vsg6_ga__NiuJiFang1__SourceOut", None)
    vsg6_ga__NiuJiFang1__TargetOut = getattr(solver, "vsg6_ga__NiuJiFang1__TargetOut", None)
    vsg6_ga__NiuJiFang1__TransformOut = getattr(solver, "vsg6_ga__NiuJiFang1__TransformOut", None)
    vsg6_ga__NiuJiFang1__MovedGeo = getattr(solver, "vsg6_ga__NiuJiFang1__MovedGeo", None)

    vsg6_ga__NiuJiFang2__SourceOut = getattr(solver, "vsg6_ga__NiuJiFang2__SourceOut", None)
    vsg6_ga__NiuJiFang2__TargetOut = getattr(solver, "vsg6_ga__NiuJiFang2__TargetOut", None)
    vsg6_ga__NiuJiFang2__TransformOut = getattr(solver, "vsg6_ga__NiuJiFang2__TransformOut", None)
    vsg6_ga__NiuJiFang2__MovedGeo = getattr(solver, "vsg6_ga__NiuJiFang2__MovedGeo", None)

    # --------- Step8-6：叠次-6：平基方一、平基方二 ---------
    vsg6_timber_block4__TimberBrep = getattr(solver, "vsg6_timber_block4__TimberBrep", None)
    vsg6_timber_block4__EdgeMidPoints = getattr(solver, "vsg6_timber_block4__EdgeMidPoints", None)
    vsg6_timber_block4__Corner0Planes = getattr(solver, "vsg6_timber_block4__Corner0Planes", None)
    vsg6_timber_block4__FacePlaneList = getattr(solver, "vsg6_timber_block4__FacePlaneList", None)
    vsg6_timber_block4__LocalAxesPlane = getattr(solver, "vsg6_timber_block4__LocalAxesPlane", None)
    vsg6_timber_block4__AxisX = getattr(solver, "vsg6_timber_block4__AxisX", None)
    vsg6_timber_block4__AxisY = getattr(solver, "vsg6_timber_block4__AxisY", None)
    vsg6_timber_block4__AxisZ = getattr(solver, "vsg6_timber_block4__AxisZ", None)
    vsg6_timber_block4__Log = getattr(solver, "vsg6_timber_block4__Log", None)

    vsg6_PlaneFromLists6__BasePlane = getattr(solver, "vsg6_PlaneFromLists6__BasePlane", None)
    vsg6_PlaneFromLists6__OriginPoint = getattr(solver, "vsg6_PlaneFromLists6__OriginPoint", None)
    vsg6_PlaneFromLists6__ResultPlane = getattr(solver, "vsg6_PlaneFromLists6__ResultPlane", None)
    vsg6_PlaneFromLists6__Log = getattr(solver, "vsg6_PlaneFromLists6__Log", None)

    vsg6_PlaneFromLists7__BasePlane = getattr(solver, "vsg6_PlaneFromLists7__BasePlane", None)
    vsg6_PlaneFromLists7__OriginPoint = getattr(solver, "vsg6_PlaneFromLists7__OriginPoint", None)
    vsg6_PlaneFromLists7__ResultPlane = getattr(solver, "vsg6_PlaneFromLists7__ResultPlane", None)
    vsg6_PlaneFromLists7__Log = getattr(solver, "vsg6_PlaneFromLists7__Log", None)

    vsg6_PlaneFromLists8__BasePlane = getattr(solver, "vsg6_PlaneFromLists8__BasePlane", None)
    vsg6_PlaneFromLists8__OriginPoint = getattr(solver, "vsg6_PlaneFromLists8__OriginPoint", None)
    vsg6_PlaneFromLists8__ResultPlane = getattr(solver, "vsg6_PlaneFromLists8__ResultPlane", None)
    vsg6_PlaneFromLists8__Log = getattr(solver, "vsg6_PlaneFromLists8__Log", None)

    vsg6_ga__PingJiFang1__SourceOut = getattr(solver, "vsg6_ga__PingJiFang1__SourceOut", None)
    vsg6_ga__PingJiFang1__TargetOut = getattr(solver, "vsg6_ga__PingJiFang1__TargetOut", None)
    vsg6_ga__PingJiFang1__TransformOut = getattr(solver, "vsg6_ga__PingJiFang1__TransformOut", None)
    vsg6_ga__PingJiFang1__MovedGeo = getattr(solver, "vsg6_ga__PingJiFang1__MovedGeo", None)

    vsg6_ga__PingJiFang2__SourceOut = getattr(solver, "vsg6_ga__PingJiFang2__SourceOut", None)
    vsg6_ga__PingJiFang2__TargetOut = getattr(solver, "vsg6_ga__PingJiFang2__TargetOut", None)
    vsg6_ga__PingJiFang2__TransformOut = getattr(solver, "vsg6_ga__PingJiFang2__TransformOut", None)
    vsg6_ga__PingJiFang2__MovedGeo = getattr(solver, "vsg6_ga__PingJiFang2__MovedGeo", None)


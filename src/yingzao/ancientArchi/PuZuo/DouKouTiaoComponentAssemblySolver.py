# -*- coding: utf-8 -*-
"""
DouKouTiaoSolver.py

将「枓口跳 DouKouTiao」的多个 GhPython 自定义组件（叠级/对位等）串联为一个单一 GhPython 组件脚本。

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


    IncludeStep8_LaoYanFangFang : bool
        Access: item
        TypeHint: bool
        是否包含 Step 8（叠级4-橑檐方 + 枋 + PlaneFromLists::3 + 对位）到 ComponentAssembly
        - True  : 计算并把橑檐方与枋加入 ComponentAssembly（默认）
        - False : 跳过 Step 8（不计算/不加入）
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
- Step1 读取 PuZuo / type_code=DouKouTiao / field=params_json / export_all=True，得到 All 与 AllDict。
- 子步骤若再次读取 DB（未来步骤可能会），必须避免覆盖 Step1 的 All/AllDict，因此统一加前缀（如 LD_All 等）。
- 广播机制：尽量模拟 GH 的一对多、多对多：以最大长度为准，长度=1 则重复；否则按最小公共长度裁切。
- 输出 list 若出现 “System.Collections.Generic.List`1[System.Object]” 的嵌套显示问题，需要递归拍平（本脚本提供 _flatten_items）。
"""

from __future__ import division

import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght

# -------------------------
# yingzao.ancientArchi 导入
# -------------------------
from yingzao.ancientArchi import (
    DBJsonReader,
    GeoAligner_xfm,
    FTPlaneFromLists,
    RufuZhaQian_DouKouTiaoSolver_V2,
    SanDouSolver,
    RuFangEaveToolBuilder,
    build_timber_block_uniform,
)

# LuDou_DouKouTiao：你未提供原 ghpy 代码，这里做多重兜底导入
_LUDOU_SOLVER = None
_import_err = None
try:
    # 可能存在的命名 1
    from yingzao.ancientArchi import LU_DOU_doukoutiaoSolver as _LUDOU_SOLVER
except Exception as e1:
    _import_err = e1
    try:
        # 可能存在的命名 2（与 DanGong 的 JiaoHuDou_dangongSolver 类似风格）
        from yingzao.ancientArchi import LuDou_DouKouTiao as _LUDOU_SOLVER
    except Exception as e2:
        _import_err = e2
        _LUDOU_SOLVER = None

# LingGong_DouKouTiao：已提供组件壳代码，这里按 yingzao.ancientArchi 的 Solver 进行兜底导入
_LINGGONG_SOLVER = None
_lg_import_err = None
try:
    from yingzao.ancientArchi import LingGong_DouKouTiaoSolver as _LINGGONG_SOLVER
except Exception as e1:
    _lg_import_err = e1
    try:
        from yingzao.ancientArchi import LingGong_DouKouTiao as _LINGGONG_SOLVER
    except Exception as e2:
        _lg_import_err = e2
        _LINGGONG_SOLVER = None

# JiaoHuDou_DouKouTiao：交互枓[枓口跳] Solver 兜底导入
_JIAOHU_SOLVER = None
_jh_import_err = None
try:
    from yingzao.ancientArchi import JIAOHU_DOU_doukoutiaoSolver as _JIAOHU_SOLVER
except Exception as e1:
    _jh_import_err = e1
    try:
        # 可能的别名兜底
        from yingzao.ancientArchi import JiaoHuDou_DouKouTiaoSolver as _JIAOHU_SOLVER
    except Exception as e2:
        _jh_import_err = e2
        _JIAOHU_SOLVER = None

# TieErDou_DouKouTiao：贴耳枓[枓口跳] Solver 兜底导入
_TIEER_SOLVER = None
_te_import_err = None
try:
    from yingzao.ancientArchi import TIEER_DOU_doukoutiaoSolver as _TIEER_SOLVER
except Exception as e1:
    _te_import_err = e1
    try:
        # 可能的别名兜底
        from yingzao.ancientArchi import TieErDou_DouKouTiaoSolver as _TIEER_SOLVER
    except Exception as e2:
        _te_import_err = e2
        _TIEER_SOLVER = None


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


def _world_xz_plane(origin=None):
    """构造 GH 语义的 XZ Plane：XAxis=(1,0,0), YAxis=(0,0,1), ZAxis=(0,-1,0)。"""
    try:
        o = origin if isinstance(origin, rg.Point3d) else rg.Point3d(0.0, 0.0, 0.0)
        return rg.Plane(o, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 0, 1))
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


def _ensure_list(x):
    """把 item / tuple / list / GH list 包成 python list（None->[]）"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    # GH 常见：System.Collections.Generic.List[object] 进来表现成可迭代
    try:
        if hasattr(x, "__iter__") and not isinstance(x, (str, bytes)):
            return list(x)
    except:
        pass
    return [x]


def _unwrap_xform(xf):
    """将 GH_Transform / Rhino Transform / None 统一解包为 rg.Transform 或 None。

    - xf: 可能为 ght.GH_Transform、rg.Transform、或其他可转换对象
    """
    if xf is None:
        return None

    try:
        # Grasshopper GH_Transform
        if isinstance(xf, ght.GH_Transform):
            return xf.Value
    except Exception:
        pass

    # 已经是 Rhino Transform
    if isinstance(xf, rg.Transform):
        return xf

    # 某些情况下可能有 .Value
    try:
        if hasattr(xf, "Value") and isinstance(xf.Value, rg.Transform):
            return xf.Value
    except Exception:
        pass

    # 尝试强转
    try:
        return rg.Transform(xf)
    except Exception:
        return None


def _as_int(val, default=0):
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
            if s == "":
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
            if s == "":
                return float(default)
            return float(s)
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_float(val[0], default)
    except:
        pass
    return float(default)


def _as_01(val, default=0):
    """把 FlipX/FlipY/FlipZ 之类转成 0/1"""
    try:
        if val is None:
            return int(default)
        if isinstance(val, bool):
            return 1 if val else 0
        if isinstance(val, (int, float)):
            return 1 if float(val) != 0.0 else 0
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("1", "true", "yes", "y", "t"):
                return 1
            if s in ("0", "false", "no", "n", "f", ""):
                return 0
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return _as_01(val[0], default)
    except:
        pass
    return int(default)


def _flatten_items(obj, out_list):
    """
    把 obj 递归拍平成“一维 items”，追加到 out_list。
    目标：避免 list 套 list，保证 out_list 中每个元素是一个几何 item。
    """
    if obj is None:
        return
    if isinstance(obj, (list, tuple)):
        for it in obj:
            _flatten_items(it, out_list)
        return
    # GH .NET List 也可能进来
    try:
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)) and not isinstance(obj, rg.GeometryBase):
            # 注意：Brep/Curve 也是可迭代风险很低，但这里做个 GeometryBase 特判
            for it in list(obj):
                _flatten_items(it, out_list)
            return
    except:
        pass
    out_list.append(obj)


def _broadcast_lists(*lists):
    """
    简化版 GH 广播：
    - 取所有输入 list 的最大长度 n_max
    - 若某个 list 长度为 1，则重复
    - 若长度既不是 1 也不是 n_max，则裁切到 min_len（避免越界）
    """
    L = [_ensure_list(x) for x in lists]
    lens = [len(x) for x in L]
    n_max = max(lens) if lens else 0
    if n_max == 0:
        return [[] for _ in L], 0

    # 若存在“非 1 且 非 n_max”的长度，则取 min_len 保守对齐
    bad = [ln for ln in lens if ln not in (1, n_max)]
    if bad:
        n = min(lens)
    else:
        n = n_max

    out = []
    for arr in L:
        if len(arr) == 1 and n > 1:
            out.append(arr * n)
        else:
            out.append(arr[:n])
    return out, n


def _pick_by_index(seq, idx, default=None):
    """从 seq 取 idx（安全）"""
    arr = _ensure_list(seq)
    if not arr:
        return default
    i = _as_int(idx, 0)
    if i < 0:
        i = 0
    if i >= len(arr):
        i = len(arr) - 1
    return arr[i]


def _coerce_plane(p, default=None):
    """尽量把输入转换为 Rhino.Geometry.Plane。支持：
    - Rhino.Geometry.Plane
    - Grasshopper.Kernel.Types.GH_Plane（.Value）
    - 字符串 'WorldXY' / 'WorldXZ'（容错）
    """
    if default is None:
        default = rg.Plane.WorldXY
    if p is None:
        return default
    try:
        if isinstance(p, rg.Plane):
            return rg.Plane(p)
    except:
        pass
    # GH_Plane / 其他包装
    try:
        if hasattr(p, "Value"):
            v = p.Value
            try:
                if isinstance(v, rg.Plane):
                    return v
            except:
                return v
    except:
        pass
    # 字符串容错
    try:
        if isinstance(p, (str, bytes)):
            s = str(p)
            if s.lower() in ["worldxz", "xz", "world_xz"]:
                w = _world_xz_plane()
                return w if w is not None else default
            if s.lower() in ["worldxy", "xy", "world_xy"]:
                return rg.Plane.WorldXY
    except:
        pass
    return default


def _coerce_geo(g):
    """尽量把 GH_Brep / GH_Geometry 等包装拆出 Rhino.Geometry 几何对象。"""
    if g is None:
        return None
    try:
        if hasattr(g, "Value"):
            return g.Value
    except:
        pass
    return g


def _unwrap_transform(xf):
    """把 GH_Transform / Rhino Transform 包装拆成 Rhino.Geometry.Transform。"""
    if xf is None:
        return None
    # 已是 Rhino.Geometry.Transform
    try:
        import Rhino.Geometry as rg
        if isinstance(xf, rg.Transform):
            return xf
    except Exception:
        pass
    # Grasshopper.Kernel.Types.GH_Transform: 常见属性 Value
    for attr in ('Value', 'Transform', 'value'):
        try:
            v = getattr(xf, attr)
            # Value 可能是属性也可能是方法
            v = v() if callable(v) else v
            try:
                import Rhino.Geometry as rg
                if isinstance(v, rg.Transform):
                    return v
            except Exception:
                return v
        except Exception:
            continue
    return xf


# =========================================================
# Solver 主类
# =========================================================

class DouKouTiaoComponentAssemblySolver(object):
    """
    枓口跳：按步骤串联（先实现到 Step2）
        Step1 : 读取数据库（PuZuo / DouKouTiao）
        Step2 : 叠级1-櫨枓（LuDou_DouKouTiao）+ VSG1_GA_LuDou 对位到 PlacePlane
        StepX : 后续逐步补齐（你后面继续给组件拆解步骤）
    """

    def __init__(self, DBPath=None, PlacePlane=None, Refresh=False, IncludeStep8_LaoYanFangFang=True, ghenv=None):
        self.DBPath = DBPath
        self.PlacePlane = PlacePlane if PlacePlane is not None else _default_place_plane()
        self.Refresh = bool(Refresh)
        # Step8 开关：默认 True（包含 Step8 橑檐方+枋）
        self.IncludeStep8_LaoYanFangFang = True if IncludeStep8_LaoYanFangFang is None else bool(
            IncludeStep8_LaoYanFangFang)
        self.ghenv = ghenv

        # 可选输入端：用户可在 GH 增加 FT_timber_block_uniform_length_fen 输入端
        self.FT_timber_block_uniform_length_fen = None

        self.ComponentAssembly = []
        self.AssemblyParts = []
        self.Log = ""

        # Step1（全局 DB：PuZuo/DouKouTiao）
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
            key_value="DouKouTiao",
            field="params_json",
            json_path=None,
            export_all=True,
            ghenv=self.ghenv
        )
        self.Value, self.All, self.DBLog = reader.run()
        self.AllDict = all_to_dict(self.All)

        self.LogLines.append("[DB] 数据库读取完成")
        self.LogLines.append("[DB] table=PuZuo type_code=DouKouTiao field=params_json export_all=True")
        self.LogLines.append("[DB] All 条目数={}".format(len(self.All) if self.All else 0))
        self.LogLines.append("[DB] AllDict 条目数={}".format(len(self.AllDict) if self.AllDict else 0))
        self.LogLines.append("Step 1 完成：已读取 All 列表并转换为 AllDict。")

    # -------------------------------
    # Step 2：叠级1-櫨枓 + VSG1_GA_LuDou 对位
    # -------------------------------
    def step2_ludou_and_align(self):
        self.LogLines.append("Step 2：叠级1-櫨枓 LuDou_DouKouTiao + VSG1_GA_LuDou 对位…")

        # 2.1 LuDou_DouKouTiao
        base_point = rg.Point3d(0, 0, 0)

        if _LUDOU_SOLVER is None:
            self.LogLines.append("[ERROR] 无法导入 LuDou_DouKouTiao 相关 Solver（yingzao.ancientArchi）。")
            self.LogLines.append("[ERROR] import_err={}".format(_import_err))
            # 给空输出，确保不中断 GH
            self.LD_CutTimbers = []
            self.LD_FacePlaneList = []
            self.LD_Log = "LuDou_DouKouTiao Solver import failed."
            return

        # 兼容两类调用签名： (DBPath, base_point, Refresh) 或关键字
        ld = None
        try:
            ld = _LUDOU_SOLVER(self.DBPath, base_point, self.Refresh)
        except:
            try:
                ld = _LUDOU_SOLVER(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            except Exception as e:
                self.LogLines.append("[ERROR] LuDou_DouKouTiao Solver 初始化失败：{}".format(e))
                self.LD_CutTimbers = []
                self.LD_FacePlaneList = []
                self.LD_Log = "LuDou solver init failed."
                return

        # 运行
        try:
            if hasattr(ld, "run"):
                ld.run()
            elif callable(ld):
                ld()
        except Exception as e:
            self.LogLines.append("[ERROR] LuDou_DouKouTiao 执行失败：{}".format(e))
            self.LD_CutTimbers = []
            self.LD_FacePlaneList = []
            self.LD_Log = "LuDou solver run failed."
            return

        # 保留子模块输出（前缀化，避免覆盖 Step1）
        self.LD_All = getattr(ld, "All", None)
        self.LD_AllDict = getattr(ld, "AllDict", None)
        self.LD_Log = getattr(ld, "Log", "")

        self.LD_CutTimbers = getattr(ld, "CutTimbers", None)
        self.LD_FacePlaneList = getattr(ld, "FacePlaneList", None)

        # 2.2 VSG1_GA_LuDou（GeoAligner）
        # 输入端：
        # Geo = LD_CutTimbers
        # SourcePlane = LD_FacePlaneList[ VSG1_GA_LuDou__SourcePlane ]
        # TargetPlane = PlacePlane
        # FlipZ = VSG1_GA_LuDou__FlipZ
        geo_list = _ensure_list(self.LD_CutTimbers)

        # SourcePlane index（允许单值或列表）
        src_idx_val = self.AllDict.get("VSG1_GA_LuDou__SourcePlane", 0)
        src_idx_list = _ensure_list(src_idx_val) if isinstance(src_idx_val, (list, tuple)) else [src_idx_val]

        # FlipZ（允许单值或列表）
        flipz_val = self.AllDict.get("VSG1_GA_LuDou__FlipZ", 0)
        flipz_list = _ensure_list(flipz_val) if isinstance(flipz_val, (list, tuple)) else [flipz_val]

        # 目标平面（PlacePlane）：允许 item 或 list，这里按 GH 习惯广播
        tp_list = [self.PlacePlane]

        # 广播：geo, src_idx, flipz, targetplane
        (geo_b, src_idx_b, flipz_b, tp_b), n = _broadcast_lists(geo_list, src_idx_list, flipz_list, tp_list)

        moved, xfs, src_out, tgt_out = [], [], [], []
        used_tps = []
        msgs = []

        for i in range(n):
            g = geo_b[i]
            # 从 FacePlaneList 取 SourcePlane
            sp = _pick_by_index(self.LD_FacePlaneList, src_idx_b[i], default=rg.Plane.WorldXY)
            tp = tp_b[i] if tp_b[i] is not None else _default_place_plane()

            flip_z = _as_01(flipz_b[i], 0)

            try:
                # rotate/flip/move：本步骤只明确 FlipZ，其它默认 0
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=0.0,
                    flip_x=0, flip_y=0, flip_z=flip_z,
                    move_x=0.0, move_y=0.0, move_z=0.0
                )
                src_out.append(so)
                tgt_out.append(to)
                xfs.append(xf)
                moved.append(mg)
            except Exception as e:
                msgs.append("GA fail @{} : {}".format(i, e))
                moved.append(None)
                xfs.append(None)
                src_out.append(sp)
                tgt_out.append(tp)

        self.VSG1_SourceOut = src_out
        self.VSG1_TargetOut = tgt_out
        self.VSG1_TransformOut = xfs
        self.VSG1_MovedGeo = moved
        self.VSG1_LogLines = msgs

        # 2.3 组装输出（到 Step2 为止）
        parts = []
        _flatten_items(self.VSG1_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 2 完成：LuDou items={} | Moved items={}".format(
            len(_ensure_list(self.LD_CutTimbers)),
            len(_ensure_list(self.VSG1_MovedGeo))
        ))

    # -------------------------------
    # Step 3：叠级2-令栱 + VSG2_GA_LingGong 对位（基于 Step2 的变换结果）
    # -------------------------------
    def step3_linggong_and_align(self):
        self.LogLines.append("Step 3：叠级2-令栱 LingGong_DouKouTiao + VSG2_GA_LingGong 对位…")

        base_point = rg.Point3d(0, 0, 0)

        if _LINGGONG_SOLVER is None:
            self.LogLines.append("[ERROR] 无法导入 LingGong_DouKouTiaoSolver（yingzao.ancientArchi）。")
            self.LogLines.append("[ERROR] lg_import_err={}".format(_lg_import_err))
            self.LG_CutTimbers = []
            self.LG_FacePlaneList = []
            self.LG_Log = "LingGong_DouKouTiao Solver import failed."
            return

        # 3.1 LingGong_DouKouTiao
        lg = None
        try:
            lg = _LINGGONG_SOLVER(self.DBPath, base_point, self.Refresh, self.ghenv)
        except:
            try:
                lg = _LINGGONG_SOLVER(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            except Exception as e:
                self.LogLines.append("[ERROR] LingGong_DouKouTiaoSolver 初始化失败：{}".format(e))
                self.LG_CutTimbers = []
                self.LG_FacePlaneList = []
                self.LG_Log = "LingGong solver init failed."
                return

        try:
            if hasattr(lg, "run"):
                lg = lg.run()
            elif hasattr(lg, "Run"):
                lg = lg.Run()
        except Exception as e:
            self.LogLines.append("[ERROR] LingGong_DouKouTiao 执行失败：{}".format(e))
            self.LG_CutTimbers = []
            self.LG_FacePlaneList = []
            self.LG_Log = "LingGong solver run failed."
            return

        # 3.1.1 复制 LingGong solver 的调试输出（前缀 LG_，避免覆盖 Step1）
        # 你提供的组件壳里列出的字段尽量全收录（没有就置 None）
        lg_fields = [
            # 最终输出
            "CutTimbers", "FailTimbers", "Log",
            # Step1 DB
            "Value", "All", "AllDict", "DBLog",
            # Step2 timber_block_uniform
            "TimberBrep", "FaceList", "PointList", "EdgeList", "CenterPoint", "CenterAxisLines",
            "EdgeMidPoints", "FacePlaneList", "Corner0Planes", "LocalAxesPlane",
            "AxisX", "AxisY", "AxisZ", "FaceDirTags", "EdgeDirTags", "Corner0EdgeDirs",
            # Step3 JuanShaToolBuilder
            "JuanShaToolBrep", "JuanShaSectionEdges", "JuanShaHL_Intersection",
            "JuanShaHeightFacePlane", "JuanShaLengthFacePlane", "JuanShaLog",
            # Step3 PlaneFromLists::1
            "PF1_BasePlane", "PF1_OriginPoint", "PF1_ResultPlane", "PF1_Log",
            # Step3 FT_AlignToolToTimber::1
            "Align1_AlignedTool", "Align1_XForm", "Align1_SourcePlane", "Align1_TargetPlane",
            "Align1_SourcePoint", "Align1_TargetPoint", "Align1_DebugInfo",
            # Step4 FT_BlockCutter
            "BlockCutter_TimberBrep", "BlockCutter_FacePlaneList", "BlockCutter_Log",
            # Step4 FT_AlignToolToTimber::2
            "Align2_AlignedTool", "Align2_XForm", "Align2_SourcePlane", "Align2_TargetPlane",
            "Align2_SourcePoint", "Align2_TargetPoint", "Align2_DebugInfo",
            # Step5 GongYan
            "GongYan_SectionFace", "GongYan_OffsetFace", "GongYan_Points", "GongYan_OffsetPoints",
            "GongYan_ToolBrep", "GongYan_BridgePoints", "GongYan_BridgeMidPoints",
            "GongYan_BridgePlane", "GongYan_Log",
            # Step5 PlaneFromLists::2、::3
            "PF2_BasePlane", "PF2_OriginPoint", "PF2_ResultPlane", "PF2_Log",
            "PF3_BasePlane", "PF3_OriginPoint", "PF3_ResultPlane", "PF3_Log",
            # Step5 GeoAligner::1
            "GeoAligner1_SourceOut", "GeoAligner1_TargetOut", "GeoAligner1_MovedGeo",
        ]

        for nm in lg_fields:
            setattr(self, "LG_" + nm, getattr(lg, nm, None))

        self.LG_CutTimbers = getattr(lg, "CutTimbers", None)
        self.LG_FacePlaneList = getattr(lg, "FacePlaneList", None)
        self.LG_Log = getattr(lg, "Log", "")

        # 3.2 计算 VSG2 TargetPlane：
        # TargetPlane = Transform( LD_FacePlaneList, VSG1_TransformOut ) 的结果列表，然后按索引取 VSG2_GA_LingGong__TargetPlane
        # 注意：VSG1_TransformOut 是 Step2 GeoAligner 返回的 Transform（期望为 rg.Transform）
        ld_planes = _ensure_list(getattr(self, "LD_FacePlaneList", None))
        vsg1_xfs = _ensure_list(getattr(self, "VSG1_TransformOut", None))

        # 广播：planes 与 xforms（通常 xform=1 或与 planes 同长）
        (ldp_b, xfb), n_tp = _broadcast_lists(ld_planes, vsg1_xfs)
        transformed_planes = []
        for i in range(n_tp):
            pl = ldp_b[i]
            xf = xfb[i]
            try:
                if isinstance(pl, rg.Plane):
                    _pl = rg.Plane(pl)
                    if xf is not None:
                        try:
                            _pl.Transform(xf)
                        except:
                            # xf 可能是 GH_Transform
                            try:
                                _pl.Transform(xf.Value)
                            except:
                                pass
                    transformed_planes.append(_pl)
                else:
                    transformed_planes.append(pl)
            except:
                transformed_planes.append(pl)

        self.VSG2_TargetPlaneCandidates = transformed_planes

        # 3.3 VSG2_GA_LingGong（GeoAligner_xfm.align）
        geo_list = _ensure_list(self.LG_CutTimbers)

        # SourcePlane index（来自 LingGong 的 FacePlaneList）
        src_idx_val = self.AllDict.get("VSG2_GA_LingGong__SourcePlane", 0)
        src_idx_list = _ensure_list(src_idx_val) if isinstance(src_idx_val, (list, tuple)) else [src_idx_val]

        # TargetPlane index（来自 transformed_planes）
        tgt_idx_val = self.AllDict.get("VSG2_GA_LingGong__TargetPlane", 0)
        tgt_idx_list = _ensure_list(tgt_idx_val) if isinstance(tgt_idx_val, (list, tuple)) else [tgt_idx_val]

        # RotateDeg / FlipZ / MoveZ（允许列表）
        rot_val = self.AllDict.get("VSG2_GA_LingGong__RotateDeg", 0.0)
        rot_list = _ensure_list(rot_val) if isinstance(rot_val, (list, tuple)) else [rot_val]

        flipz_val = self.AllDict.get("VSG2_GA_LingGong__FlipZ", 0)
        flipz_list = _ensure_list(flipz_val) if isinstance(flipz_val, (list, tuple)) else [flipz_val]

        movez_val = self.AllDict.get("VSG2_GA_LingGong__MoveZ", 0.0)
        movez_list = _ensure_list(movez_val) if isinstance(movez_val, (list, tuple)) else [movez_val]

        # 其它未指定输入：FlipX/FlipY/MoveX/MoveY 统一为 0
        flipx_list = [0]
        flipy_list = [0]
        movex_list = [0.0]
        movey_list = [0.0]

        # 广播：geo, src_idx, tgt_idx, rot, flipz, movez, flipx, flipy, movex, movey
        (geo_b, src_idx_b, tgt_idx_b, rot_b, flipz_b, movez_b, flipx_b, flipy_b, movex_b,
         movey_b), n = _broadcast_lists(
            geo_list, src_idx_list, tgt_idx_list, rot_list, flipz_list, movez_list,
            flipx_list, flipy_list, movex_list, movey_list
        )

        moved, xfs, src_out, tgt_out = [], [], [], []
        used_tps = []
        msgs = []

        for i in range(n):
            g = geo_b[i]
            sp = _pick_by_index(self.LG_FacePlaneList, src_idx_b[i], default=rg.Plane.WorldXY)
            tp = _pick_by_index(transformed_planes, tgt_idx_b[i], default=_default_place_plane())
            used_tps.append(tp)

            rot_deg = _as_float(rot_b[i], 0.0)
            flip_z = _as_01(flipz_b[i], 0)
            move_z = _as_float(movez_b[i], 0.0)

            flip_x = _as_01(flipx_b[i], 0)
            flip_y = _as_01(flipy_b[i], 0)
            move_x = _as_float(movex_b[i], 0.0)
            move_y = _as_float(movey_b[i], 0.0)

            try:
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rot_deg,
                    flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
                    move_x=move_x, move_y=move_y, move_z=move_z
                )
                src_out.append(so)
                tgt_out.append(to)
                xfs.append(xf)
                moved.append(mg)
            except Exception as e:
                msgs.append("VSG2 GA fail @{} : {}".format(i, e))
                moved.append(None)
                xfs.append(None)
                src_out.append(sp)
                tgt_out.append(tp)

        self.VSG2_SourceOut = src_out
        self.VSG2_TargetOut = tgt_out
        self.VSG2_TransformOut = xfs
        self.VSG2_MovedGeo = moved
        self.VSG2_TargetPlaneUsed = used_tps
        self.VSG2_LogLines = msgs

        # 3.4 组装输出：在 Step2 的基础上追加 Step3
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        _flatten_items(self.VSG2_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 3 完成：LingGong items={} | Moved items={}".format(
            len(_ensure_list(self.LG_CutTimbers)),
            len(_ensure_list(self.VSG2_MovedGeo))
        ))

    # -------------------------------
    # Step 4：乳栿劄牽[枓口跳]V2 + PlaneFromLists::1 + VSG2_GA_RufuZhaQian_DouKouTiao
    # -------------------------------
    def step4_rufuzhaqian_and_align(self):
        self.LogLines.append("Step 4：乳栿劄牽[枓口跳]V2 + PlaneFromLists::1 + VSG2_GA_RufuZhaQian_DouKouTiao 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # 4.1 RuFuZhaQian_DouKouTiaoV2（允许输入端覆盖 timber_length）
        # 输入优先级：组件输入端 > DB > 默认（此处按你提供的 V2 组件壳逻辑）
        rf = None
        try:
            rf = RufuZhaQian_DouKouTiaoSolver_V2(
                self.DBPath, base_point, self.Refresh, self.ghenv,
                FT_timber_block_uniform_length_fen=self.FT_timber_block_uniform_length_fen
            ).run()
        except Exception as e1:
            # 兼容不同签名
            try:
                rf = RufuZhaQian_DouKouTiaoSolver_V2(
                    DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv,
                    FT_timber_block_uniform_length_fen=self.FT_timber_block_uniform_length_fen
                ).run()
            except Exception as e2:
                self.LogLines.append("[ERROR] RufuZhaQian_DouKouTiaoSolver_V2 初始化/执行失败：{} | {}".format(e1, e2))
                self.RF_CutTimbers = []
                self.RF_Log = "RufuZhaQian solver V2 failed."
                return

        # 保存 RufuZhaQian solver 输出（前缀 RF_，避免覆盖 Step1/2/3）
        rf_fields = [
            "CutTimbers", "FailTimbers", "Log",
            # Step1
            "Value_1", "All_1", "AllDict_1",
            # Step2 timber block outputs
            "TimberBrep", "FaceList", "PointList", "EdgeList", "CenterPoint", "CenterAxisLines",
            "EdgeMidPoints", "FacePlaneList", "Corner0Planes", "LocalAxesPlane",
            "AxisX", "AxisY", "AxisZ", "FaceDirTags", "EdgeDirTags", "Corner0EdgeDirs",
        ]
        for nm in rf_fields:
            setattr(self, "RF_" + nm, getattr(rf, nm, None))

        # 你给的壳里还有大量字段（BC1/BC2/.../FinalCut...），这里不枚举写死，
        # 但仍可按需通过 getattr(rf, name, None) 再补；目前保证 Step4 需要的关键字段：
        self.RF_CutTimbers = getattr(rf, "CutTimbers", None)
        self.RF_EdgeMidPoints = getattr(rf, "EdgeMidPoints", None)
        self.RF_Corner0Planes = getattr(rf, "Corner0Planes", None)
        self.RF_Log = getattr(rf, "Log", "")

        # 4.2 PlaneFromLists::1
        # OriginPoints = RF_EdgeMidPoints
        # BasePlanes   = RF_Corner0Planes
        # IndexOrigin  = PlaneFromLists_1__IndexOrigin（来自 Step1 AllDict）
        # IndexPlane   = PlaneFromLists_1__IndexPlane（来自 Step1 AllDict）
        OriginPoints = _ensure_list(self.RF_EdgeMidPoints)
        BasePlanes = _ensure_list(self.RF_Corner0Planes)

        idx_origin_val = self.AllDict.get("PlaneFromLists_1__IndexOrigin", 0)
        idx_plane_val = self.AllDict.get("PlaneFromLists_1__IndexPlane", 0)

        idx_origin_list = _ensure_list(idx_origin_val) if isinstance(idx_origin_val, (list, tuple)) else [
            idx_origin_val]
        idx_plane_list = _ensure_list(idx_plane_val) if isinstance(idx_plane_val, (list, tuple)) else [idx_plane_val]

        pfl_builder = FTPlaneFromLists(wrap=True)

        (io_b, ip_b), n_pfl = _broadcast_lists(idx_origin_list, idx_plane_list)

        pfl_baseplanes, pfl_originpts, pfl_resultplanes, pfl_logs = [], [], [], []
        for i in range(n_pfl):
            try:
                bp, op, rp, lg = pfl_builder.build_plane(OriginPoints, BasePlanes, io_b[i], ip_b[i])
            except Exception as e:
                bp, op, rp, lg = None, None, None, "PFL1 build failed @{} : {}".format(i, e)

            pfl_baseplanes.append(bp)
            pfl_originpts.append(op)
            pfl_resultplanes.append(rp)
            pfl_logs.append(lg)

        self.PFL1_BasePlane = pfl_baseplanes
        self.PFL1_OriginPoint = pfl_originpts
        self.PFL1_ResultPlane = pfl_resultplanes
        self.PFL1_Log = pfl_logs

        # 4.3 VSG2_GA_RufuZhaQian_DouKouTiao
        # Geo         = RF_CutTimbers
        # SourcePlane = PFL1_ResultPlane
        # TargetPlane = 同 VSG2_GA_LingGong 的 TargetPlane（即 Step3 选出来并用于对位的 plane 列表）
        # RotateDeg / MoveY / MoveZ 来自 Step1 AllDict
        geo_list = _ensure_list(self.RF_CutTimbers)
        sp_list = _ensure_list(self.PFL1_ResultPlane)

        tp_used = _ensure_list(getattr(self, "VSG2_TargetPlaneUsed", None))
        if not tp_used:
            # 兜底：若 Step3 尚未生成 used planes，则用 candidates
            tp_used = _ensure_list(getattr(self, "VSG2_TargetPlaneCandidates", None))
        if not tp_used:
            tp_used = [_default_place_plane()]

        rot_val = self.AllDict.get("VSG2_GA_RufuZhaQian_DouKouTiao__RotateDeg", 0.0)
        movey_val = self.AllDict.get("VSG2_GA_RufuZhaQian_DouKouTiao__MoveY", 0.0)
        movez_val = self.AllDict.get("VSG2_GA_RufuZhaQian_DouKouTiao__MoveZ", 0.0)

        rot_list = _ensure_list(rot_val) if isinstance(rot_val, (list, tuple)) else [rot_val]
        movey_list = _ensure_list(movey_val) if isinstance(movey_val, (list, tuple)) else [movey_val]
        movez_list = _ensure_list(movez_val) if isinstance(movez_val, (list, tuple)) else [movez_val]

        # 未指定：FlipX/FlipY/FlipZ/MoveX 均为 0
        flipx_list = [0]
        flipy_list = [0]
        flipz_list = [0]
        movex_list = [0.0]

        (geo_b, sp_b, tp_b, rot_b, movex_b, movey_b, movez_b, flipx_b, flipy_b, flipz_b), n_ga = _broadcast_lists(
            geo_list, sp_list, tp_used, rot_list, movex_list, movey_list, movez_list, flipx_list, flipy_list, flipz_list
        )

        moved, xfs, src_out, tgt_out, msgs = [], [], [], [], []

        for i in range(n_ga):
            g = geo_b[i]
            sp = sp_b[i] if sp_b[i] is not None else rg.Plane.WorldXY
            tp = tp_b[i] if tp_b[i] is not None else _default_place_plane()

            rot_deg = _as_float(rot_b[i], 0.0)
            mx = _as_float(movex_b[i], 0.0)
            my = _as_float(movey_b[i], 0.0)
            mz = _as_float(movez_b[i], 0.0)

            fx = _as_01(flipx_b[i], 0)
            fy = _as_01(flipy_b[i], 0)
            fz = _as_01(flipz_b[i], 0)

            try:
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rot_deg,
                    flip_x=fx, flip_y=fy, flip_z=fz,
                    move_x=mx, move_y=my, move_z=mz
                )
                src_out.append(so)
                tgt_out.append(to)
                xfs.append(xf)
                moved.append(mg)
            except Exception as e:
                msgs.append("VSG2_RF GA fail @{} : {}".format(i, e))
                moved.append(None)
                xfs.append(None)
                src_out.append(sp)
                tgt_out.append(tp)

        self.VSG2_RF_SourceOut = src_out
        self.VSG2_RF_TargetOut = tgt_out
        self.VSG2_RF_TransformOut = xfs
        self.VSG2_RF_MovedGeo = moved
        self.VSG2_RF_LogLines = msgs

        # 4.4 组装输出：在 Step3 的基础上追加 Step4
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        _flatten_items(self.VSG2_RF_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 4 完成：RufuZhaQian items={} | Moved items={}".format(
            len(_ensure_list(self.RF_CutTimbers)),
            len(_ensure_list(self.VSG2_RF_MovedGeo))
        ))

        # -------------------------------
        # Step 5：叠级3-交互枓 + VSG3_GA_JiaoHuDou（基于 Step4 的 PFL1_ResultPlane 与 VSG2_RF_TransformOut）
        # -------------------------------

    def step5_jiaohudou_and_align(self):
        self.LogLines.append("Step 5：叠级3-交互枓 JiaoHuDou_DouKouTiao + VSG3_GA_JiaoHuDou 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # 5.1 JiaoHuDou_DouKouTiao
        if _JIAOHU_SOLVER is None:
            self.LogLines.append("[ERROR] 无法导入 JIAOHU_DOU_doukoutiaoSolver（yingzao.ancientArchi）。")
            self.LogLines.append("[ERROR] jh_import_err={}".format(_jh_import_err))
            self.JH_CutTimbers = []
            self.JH_FacePlaneList = []
            self.JH_Log = "JiaoHuDou solver import failed."
            return

        jh = None
        try:
            jh = _JIAOHU_SOLVER(self.DBPath, base_point, self.Refresh)
        except:
            try:
                jh = _JIAOHU_SOLVER(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            except Exception as e:
                self.LogLines.append("[ERROR] JiaoHuDou Solver 初始化失败：{}".format(e))
                self.JH_CutTimbers = []
                self.JH_FacePlaneList = []
                self.JH_Log = "JiaoHuDou solver init failed."
                return

        try:
            if hasattr(jh, "run"):
                jh = jh.run()
            elif hasattr(jh, "Run"):
                jh = jh.Run()
            elif hasattr(jh, "execute"):
                jh = jh.execute()
        except Exception as e:
            self.LogLines.append("[ERROR] JiaoHuDou_DouKouTiao 执行失败：{}".format(e))
            self.JH_CutTimbers = []
            self.JH_FacePlaneList = []
            self.JH_Log = "JiaoHuDou solver run failed."
            return

        # 5.1.1 保存子模块核心输出（前缀 JH_）
        self.JH_All = getattr(jh, "All", None)
        self.JH_AllDict = getattr(jh, "AllDict", None)
        self.JH_DBLog = getattr(jh, "DBLog", None)
        self.JH_Log = getattr(jh, "Log", None)

        self.JH_CutTimbers = getattr(jh, "CutTimbers", None)
        self.JH_FailTimbers = getattr(jh, "FailTimbers", None)
        self.JH_FacePlaneList = getattr(jh, "FacePlaneList", None)

        # 5.2 计算 VSG3 TargetPlane：
        # TargetPlane = Transform( PlaneFromLists::1.ResultPlane, VSG2_RF_TransformOut )
        # - PlaneFromLists::1.ResultPlane 是 Step4 产生（可能 list）
        # - VSG2_RF_TransformOut 是 Step4 GeoAligner 返回 Transform（可能 list）
        pfl1_planes = _ensure_list(getattr(self, "PFL1_ResultPlane", None))
        if not pfl1_planes:
            pfl1_planes = [rg.Plane.WorldXY]

        vsg2rf_xfs = _ensure_list(getattr(self, "VSG2_RF_TransformOut", None))
        if not vsg2rf_xfs:
            vsg2rf_xfs = [None]

        (pl_b, xf_b), n_tp = _broadcast_lists(pfl1_planes, vsg2rf_xfs)
        tp_transformed = []
        for i in range(n_tp):
            pl = pl_b[i]
            xf = xf_b[i]
            try:
                if isinstance(pl, rg.Plane):
                    _pl = rg.Plane(pl)
                    if xf is not None:
                        try:
                            _pl.Transform(xf)
                        except:
                            try:
                                _pl.Transform(xf.Value)  # GH_Transform
                            except:
                                pass
                    tp_transformed.append(_pl)
                else:
                    tp_transformed.append(pl)
            except:
                tp_transformed.append(pl)

        self.VSG3_TargetPlaneCandidates = tp_transformed

        # 5.3 VSG3_GA_JiaoHuDou
        geo_list = _ensure_list(self.JH_CutTimbers)

        # SourcePlane：JH_FacePlaneList 的索引
        src_idx_val = self.AllDict.get("VSG3_GA_JiaoHuDou__SourcePlane", 0)
        src_idx_list = _ensure_list(src_idx_val) if isinstance(src_idx_val, (list, tuple)) else [src_idx_val]

        # RotateDeg（未显式给出时默认 0）
        rot_val = self.AllDict.get("VSG3_GA_JiaoHuDou__RotateDeg", 0.0)
        rot_list = _ensure_list(rot_val) if isinstance(rot_val, (list, tuple)) else [rot_val]

        flipx_val = self.AllDict.get("VSG3_GA_JiaoHuDou__FlipX", 0)
        flipy_val = self.AllDict.get("VSG3_GA_JiaoHuDou__FlipY", 0)
        flipz_val = self.AllDict.get("VSG3_GA_JiaoHuDou__FlipZ", 0)
        movey_val = self.AllDict.get("VSG3_GA_JiaoHuDou__MoveY", 0.0)
        movez_val = self.AllDict.get("VSG3_GA_JiaoHuDou__MoveZ", 0.0)

        flipx_list = _ensure_list(flipx_val) if isinstance(flipx_val, (list, tuple)) else [flipx_val]
        flipy_list = _ensure_list(flipy_val) if isinstance(flipy_val, (list, tuple)) else [flipy_val]
        flipz_list = _ensure_list(flipz_val) if isinstance(flipz_val, (list, tuple)) else [flipz_val]
        movey_list = _ensure_list(movey_val) if isinstance(movey_val, (list, tuple)) else [movey_val]
        movez_list = _ensure_list(movez_val) if isinstance(movez_val, (list, tuple)) else [movez_val]

        # 其它未指定：MoveX = 0
        movex_list = [0.0]

        (geo_b, src_idx_b, tp_b, rot_b, fx_b, fy_b, fz_b, mx_b, my_b, mz_b), n = _broadcast_lists(
            geo_list, src_idx_list, tp_transformed, rot_list, flipx_list, flipy_list, flipz_list, movex_list,
            movey_list, movez_list
        )

        moved, xfs, src_out, tgt_out, used_tps, msgs = [], [], [], [], [], []
        sp_in_used = []

        for i in range(n):
            g = geo_b[i]
            sp = _pick_by_index(self.JH_FacePlaneList, src_idx_b[i], default=rg.Plane.WorldXY)
            sp_in_used.append(sp)
            tp = tp_b[i] if tp_b[i] is not None else _default_place_plane()
            used_tps.append(tp)

            rot_deg = _as_float(rot_b[i], 0.0)
            fx = _as_01(fx_b[i], 0)
            fy = _as_01(fy_b[i], 0)
            fz = _as_01(fz_b[i], 0)
            mx = _as_float(mx_b[i], 0.0)
            my = _as_float(my_b[i], 0.0)
            mz = _as_float(mz_b[i], 0.0)

            try:
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rot_deg,
                    flip_x=fx, flip_y=fy, flip_z=fz,
                    move_x=mx, move_y=my, move_z=mz
                )
                src_out.append(so)
                tgt_out.append(to)
                xfs.append(xf)
                moved.append(mg)
            except Exception as e:
                msgs.append("VSG3 GA fail @{} : {}".format(i, e))
                moved.append(None)
                xfs.append(None)
                src_out.append(sp)
                tgt_out.append(tp)

        self.VSG3_SourceOut = src_out
        self.VSG3_TargetOut = tgt_out
        self.VSG3_TransformOut = xfs
        self.VSG3_MovedGeo = moved
        self.VSG3_TargetPlaneUsed = used_tps
        self.VSG3_LogLines = msgs

        # 5.3.1 供 Step8 使用：保存「交互枓对位」的源平面输入值与 TransformRaw（取第一个有效值，避免广播）
        try:
            _sp_first = None
            for _v in _ensure_list(src_out):
                if _v is not None:
                    _sp_first = _v
                    break
            _xf_first = None
            for _v in _ensure_list(xfs):
                if _v is not None:
                    _xf_first = _v
                    break

            self.VSG3_JH_SourcePlaneUsed = _sp_first
            self.VSG3_JH_TransformRaw = _unwrap_xform(_xf_first) if _xf_first is not None else None
        except Exception as _e:
            try:
                msgs.append("[WARN] cache VSG3_JH_SourcePlaneUsed / TransformRaw failed: {}".format(_e))
            except:
                pass

        # 5.4 组装输出：在 Step4 的基础上追加 Step5
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        _flatten_items(self.VSG3_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 5 完成：JiaoHuDou items={} | Moved items={}".format(
            len(_ensure_list(self.JH_CutTimbers)),
            len(_ensure_list(self.VSG3_MovedGeo))
        ))

    # -------------------------------
    # run（GH Python 组件依赖入口）
    # -------------------------------
    # -------------------------------
    # Step 6：叠级3-散枓 + PlaneFromLists::2 + VSG3_GA_SanDou（基于 Step3 的 VSG2_TransformOut）
    # -------------------------------
    def step6_sandou_and_align(self):
        self.LogLines.append("Step 6：叠级3-散枓 SanDou + PlaneFromLists::2 + VSG3_GA_SanDou 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # 6.1 SanDou
        sd = None
        try:
            sd = SanDouSolver(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
        except Exception as e1:
            # 兼容不同签名
            try:
                sd = SanDouSolver(self.DBPath, base_point, self.Refresh, self.ghenv)
            except Exception as e2:
                self.LogLines.append("[ERROR] SanDouSolver 初始化失败：{} | {}".format(e1, e2))
                self.SD_CutTimbers = []
                self.SD_FacePlaneList = []
                self.SD_Log = "SanDou init failed."
                return

        try:
            if hasattr(sd, "run"):
                sd = sd.run()
            elif hasattr(sd, "Run"):
                sd = sd.Run()
            else:
                sd.run()
        except Exception as e:
            self.LogLines.append("[ERROR] SanDou 执行失败：{}".format(e))
            self.SD_CutTimbers = []
            self.SD_FacePlaneList = []
            self.SD_Log = "SanDou run failed."
            return

        # 保存 SanDou 子模块关键输出（前缀 SD_）
        self.SD_DBValue = getattr(sd, "DBValue", None)
        self.SD_All = getattr(sd, "All", None)
        self.SD_AllDict = getattr(sd, "AllDict", None)
        self.SD_DBLog = getattr(sd, "DBLog", None)

        self.SD_CutTimbers = getattr(sd, "CutTimbers", None)
        self.SD_FailTimbers = getattr(sd, "FailTimbers", None)
        self.SD_FacePlaneList = getattr(sd, "FacePlaneList", None)
        self.SD_Log = getattr(sd, "Log", None)

        self.SD_EdgeMidPoints = getattr(sd, "EdgeMidPoints", None)
        self.SD_Corner0Planes = getattr(sd, "Corner0Planes", None)

        # 6.2 PlaneFromLists::2（注意：来自 LingGong 的 EdgeMidPoints / Corner0Planes）
        OriginPoints = _ensure_list(getattr(self, "LG_EdgeMidPoints", None))
        BasePlanes = _ensure_list(getattr(self, "LG_Corner0Planes", None))

        idx_origin_val = self.AllDict.get("PlaneFromLists_2__IndexOrigin", 0)
        idx_plane_val = self.AllDict.get("PlaneFromLists_2__IndexPlane", 0)

        idx_origin_list = _ensure_list(idx_origin_val) if isinstance(idx_origin_val, (list, tuple)) else [
            idx_origin_val]
        idx_plane_list = _ensure_list(idx_plane_val) if isinstance(idx_plane_val, (list, tuple)) else [idx_plane_val]

        pfl_builder = FTPlaneFromLists(wrap=True)
        (io_b, ip_b), n_pfl = _broadcast_lists(idx_origin_list, idx_plane_list)

        pfl2_baseplanes, pfl2_originpts, pfl2_resultplanes, pfl2_logs = [], [], [], []
        for i in range(n_pfl):
            try:
                bp, op, rp, lg = pfl_builder.build_plane(OriginPoints, BasePlanes, io_b[i], ip_b[i])
            except Exception as e:
                bp, op, rp, lg = None, None, None, "PFL2 build failed @{} : {}".format(i, e)
            pfl2_baseplanes.append(bp)
            pfl2_originpts.append(op)
            pfl2_resultplanes.append(rp)
            pfl2_logs.append(lg)

        self.PFL2_BasePlane = pfl2_baseplanes
        self.PFL2_OriginPoint = pfl2_originpts
        self.PFL2_ResultPlane = pfl2_resultplanes
        self.PFL2_Log = pfl2_logs

        # 6.3 VSG3_GA_SanDou 的 TargetPlane：
        # TargetPlane = Transform( PlaneFromLists::2.ResultPlane, VSG2_GA_LingGong.TransformOut )
        pfl2_planes = _ensure_list(self.PFL2_ResultPlane)
        if not pfl2_planes:
            pfl2_planes = [rg.Plane.WorldXY]

        vsg2_xfs = _ensure_list(getattr(self, "VSG2_TransformOut", None))
        if not vsg2_xfs:
            vsg2_xfs = [None]

        (pl_b, xf_b), n_tp = _broadcast_lists(pfl2_planes, vsg2_xfs)
        tp_transformed = []
        for i in range(n_tp):
            pl = pl_b[i]
            xf = xf_b[i]
            try:
                if isinstance(pl, rg.Plane):
                    _pl = rg.Plane(pl)
                    if xf is not None:
                        try:
                            _pl.Transform(xf)
                        except:
                            try:
                                _pl.Transform(xf.Value)
                            except:
                                pass
                    tp_transformed.append(_pl)
                else:
                    tp_transformed.append(pl)
            except:
                tp_transformed.append(pl)

        self.VSG3_SD_TargetPlaneCandidates = tp_transformed

        # 6.4 VSG3_GA_SanDou（GeoAligner）
        geo_list = _ensure_list(self.SD_CutTimbers)

        src_idx_val = self.AllDict.get("VSG3_GA_SanDou__SourcePlane", 0)
        src_idx_list = _ensure_list(src_idx_val) if isinstance(src_idx_val, (list, tuple)) else [src_idx_val]

        rot_val = self.AllDict.get("VSG3_GA_SanDou__RotateDeg", 0.0)
        rot_list = _ensure_list(rot_val) if isinstance(rot_val, (list, tuple)) else [rot_val]

        flipx_val = self.AllDict.get("VSG3_GA_SanDou__FlipX", 0)
        flipx_list = _ensure_list(flipx_val) if isinstance(flipx_val, (list, tuple)) else [flipx_val]

        movex_val = self.AllDict.get("VSG3_GA_SanDou__MoveX", 0.0)
        movex_list = _ensure_list(movex_val) if isinstance(movex_val, (list, tuple)) else [movex_val]

        # 未指定：FlipY/FlipZ/MoveY/MoveZ = 0
        flipy_list = [0]
        flipz_list = [0]
        movey_list = [0.0]
        movez_list = [0.0]

        (geo_b, src_idx_b, tp_b, rot_b, fx_b, fy_b, fz_b, mx_b, my_b, mz_b), n = _broadcast_lists(
            geo_list, src_idx_list, tp_transformed, rot_list, flipx_list, flipy_list, flipz_list, movex_list,
            movey_list, movez_list
        )

        moved, xfs, src_out, tgt_out, used_tps, msgs = [], [], [], [], [], []
        sp_in_used = []

        for i in range(n):
            g = geo_b[i]
            sp = _pick_by_index(self.SD_FacePlaneList, src_idx_b[i], default=rg.Plane.WorldXY)
            tp = tp_b[i] if tp_b[i] is not None else _default_place_plane()
            used_tps.append(tp)

            rot_deg = _as_float(rot_b[i], 0.0)
            fx = _as_01(fx_b[i], 0)
            fy = _as_01(fy_b[i], 0)
            fz = _as_01(fz_b[i], 0)
            mx = _as_float(mx_b[i], 0.0)
            my = _as_float(my_b[i], 0.0)
            mz = _as_float(mz_b[i], 0.0)

            try:
                so, to, xf, mg = GeoAligner_xfm.align(
                    g, sp, tp,
                    rotate_deg=rot_deg,
                    flip_x=fx, flip_y=fy, flip_z=fz,
                    move_x=mx, move_y=my, move_z=mz
                )
                src_out.append(so)
                tgt_out.append(to)
                xfs.append(xf)
                moved.append(mg)
            except Exception as e:
                msgs.append("VSG3_SD GA fail @{} : {}".format(i, e))
                moved.append(None)
                xfs.append(None)
                src_out.append(sp)
                tgt_out.append(tp)

        self.VSG3_SD_SourceOut = src_out
        self.VSG3_SD_TargetOut = tgt_out
        self.VSG3_SD_TransformOut = xfs
        self.VSG3_SD_MovedGeo = moved
        self.VSG3_SD_TargetPlaneUsed = used_tps
        self.VSG3_SD_LogLines = msgs

        # 6.5 组装输出：在 Step5 基础上追加 Step6
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        _flatten_items(self.VSG3_SD_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 6 完成：SanDou items={} | Moved items={}".format(
            len(_ensure_list(self.SD_CutTimbers)),
            len(_ensure_list(self.VSG3_SD_MovedGeo))
        ))

        # -------------------------------
        # Step 7：叠级3-贴耳枓 + VSG3_GA_TieErDou（基于 Step3 的 VSG2_TransformOut）
        # -------------------------------

    def step7_tieerdou_and_align(self):
        self.LogLines.append("Step 7：叠级3-贴耳枓 TieErDou_DouKouTiao + VSG3_GA_TieErDou 对位…")

        base_point = rg.Point3d(0, 0, 0)

        # 7.1 TieErDou_DouKouTiao
        if _TIEER_SOLVER is None:
            self.LogLines.append("[ERROR] 无法导入 TIEER_DOU_doukoutiaoSolver（yingzao.ancientArchi）。")
            self.LogLines.append("[ERROR] te_import_err={}".format(_te_import_err))
            self.TE_CutTimbers = []
            self.TE_FacePlaneList = []
            self.TE_Log = "TieErDou solver import failed."
            return

        te = None
        try:
            te = _TIEER_SOLVER(self.DBPath, base_point, self.Refresh)
        except:
            try:
                te = _TIEER_SOLVER(DBPath=self.DBPath, base_point=base_point, Refresh=self.Refresh, ghenv=self.ghenv)
            except Exception as e:
                self.LogLines.append("[ERROR] TieErDou Solver 初始化失败：{}".format(e))
                self.TE_CutTimbers = []
                self.TE_FacePlaneList = []
                self.TE_Log = "TieErDou solver init failed."
                return

        try:
            if hasattr(te, "run"):
                te = te.run()
            elif hasattr(te, "Run"):
                te = te.Run()
            else:
                te.run()
        except Exception as e:
            self.LogLines.append("[ERROR] TieErDou_DouKouTiao 执行失败：{}".format(e))
            self.TE_CutTimbers = []
            self.TE_FacePlaneList = []
            self.TE_Log = "TieErDou solver run failed."
            return

        # 保存子模块关键输出（前缀 TE_）
        self.TE_All = getattr(te, "All", None)
        self.TE_AllDict = getattr(te, "AllDict", None)
        self.TE_DBLog = getattr(te, "DBLog", None)
        self.TE_Log = getattr(te, "Log", None)

        self.TE_CutTimbers = getattr(te, "CutTimbers", None)
        self.TE_FailTimbers = getattr(te, "FailTimbers", None)
        self.TE_FacePlaneList = getattr(te, "FacePlaneList", None)

        # 7.2 计算 VSG3_GA_TieErDou 的 TargetPlane（单值，不广播）：
        # TargetPlane = Transform( LingGong.FacePlaneList[target_idx], VSG2_GA_LingGong.TransformOut )
        lg_planes = _ensure_list(getattr(self, "LG_FacePlaneList", None))
        if not lg_planes:
            lg_planes = [rg.Plane.WorldXY]

        tgt_idx_val = self.AllDict.get("VSG3_GA_TieErDou__TargetPlane", 0)
        if isinstance(tgt_idx_val, (list, tuple)) and len(tgt_idx_val) > 0:
            tgt_idx_val = tgt_idx_val[0]

        picked_plane = _pick_by_index(lg_planes, tgt_idx_val, default=rg.Plane.WorldXY)

        vsg2_xfs = _ensure_list(getattr(self, "VSG2_TransformOut", None))
        vsg2_xf = vsg2_xfs[0] if len(vsg2_xfs) > 0 else None

        tp = picked_plane
        try:
            if isinstance(tp, rg.Plane) and vsg2_xf is not None:
                tp = rg.Plane(tp)
                tp.Transform(vsg2_xf)
        except Exception as e:
            self.LogLines.append("[WARN] VSG3_TE TargetPlane transform failed: {}".format(e))

        self.VSG3_TE_TargetPlaneCandidates = [tp]

        # 7.3 VSG3_GA_TieErDou（GeoAligner，单值，不广播）
        geo_list = _ensure_list(getattr(self, "TE_CutTimbers", None))
        geo = geo_list[0] if len(geo_list) > 0 else None

        te_planes = _ensure_list(getattr(self, "TE_FacePlaneList", None))
        if not te_planes:
            te_planes = [rg.Plane.WorldXY]

        src_idx_val = self.AllDict.get("VSG3_GA_TieErDou__SourcePlane", 0)
        if isinstance(src_idx_val, (list, tuple)) and len(src_idx_val) > 0:
            src_idx_val = src_idx_val[0]
        sp = _pick_by_index(te_planes, src_idx_val, default=rg.Plane.WorldXY)

        rot_val = self.AllDict.get("VSG3_GA_TieErDou__RotateDeg", 0.0)
        if isinstance(rot_val, (list, tuple)) and len(rot_val) > 0:
            rot_val = rot_val[0]

        flipx_val = self.AllDict.get("VSG3_GA_TieErDou__FlipX", 0)
        if isinstance(flipx_val, (list, tuple)) and len(flipx_val) > 0:
            flipx_val = flipx_val[0]

        so = to = xf_out = mg = None
        msgs = []
        try:
            so, to, xf_out, mg = GeoAligner_xfm.align(
                geo,
                sp,
                tp,
                rotate_deg=_as_float(rot_val, 0.0),
                flip_x=int(_as_float(flipx_val, 0)),
                flip_y=0,
                flip_z=0,
                move_x=0.0,
                move_y=0.0,
                move_z=0.0,
            )
            msgs.append("VSG3_TE GA ok")
        except Exception as e:
            msgs.append("VSG3_TE GA fail: {}".format(e))

        self.VSG3_TE_SourceOut = so
        self.VSG3_TE_TargetOut = to
        self.VSG3_TE_TransformOut = xf_out
        self.VSG3_TE_MovedGeo = mg
        self.VSG3_TE_SourcePlaneUsed = sp
        self.VSG3_TE_TargetPlaneUsed = tp
        self.VSG3_TE_LogLines = msgs

        # 7.4 追加到总装（单值）
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        if getattr(self, 'VSG3_TE_MovedGeo', None) is not None:
            parts.append(self.VSG3_TE_MovedGeo)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 7 完成：TieErDou items={} | Moved items={}".format(
            len(_ensure_list(self.TE_CutTimbers)),
            (1 if getattr(self, 'VSG3_TE_MovedGeo', None) is not None else 0)
        ))

    # -------------------------------
    # Step 8：叠级4-橑檐方 + 枋 + PlaneFromLists::3 + 对位
    # -------------------------------
    def step8_laoyanfang_fang_and_align(self):
        self.LogLines.append("Step 8：叠级4-橑檐方 + 枋 + PlaneFromLists::3 + VSG4 对位…")

        # -------------------------------------------------
        # 8.1 LaoYanFang（使用默认值）
        # -------------------------------------------------
        self.LYF_LogLines = []
        self.LYF_EveTool = None
        self.LYF_Section = None
        self.LYF_RectEdgeMidPoints = None
        self.LYF_RefPlaneList = None
        try:
            builder = RuFangEaveToolBuilder(
                input_point=rg.Point3d(0.0, 0.0, 0.0),
                ref_plane=None,
                width_fen=10.0,
                height_fen=30.0,
                extrude_fen=100.0
            )
            result = builder.build() or {}
            self.LYF_EveTool = result.get("EveTool", None)
            self.LYF_Section = result.get("Section", None)
            self.LYF_SectionVertices = result.get("SectionVertices", None)
            self.LYF_SectionVertexNames = result.get("SectionVertexNames", None)
            self.LYF_RectEdgeMidPoints = result.get("RectEdgeMidPoints", None)
            self.LYF_RectEdgeNames = result.get("RectEdgeNames", None)
            self.LYF_RefPlaneList = result.get("RefPlaneList", None)
            self.LYF_RefPlaneNames = result.get("RefPlaneNames", None)
            rlog = result.get("Log", [])
            self.LYF_LogLines.extend([str(x) for x in _ensure_list(rlog)])
        except Exception as e:
            self.LYF_LogLines.append("[ERROR] LaoYanFang build failed: {}".format(e))

        # -------------------------------------------------
        # 8.2 Fang_DouKouTiao（木坯工具体）
        # -------------------------------------------------
        self.Fang_LogLines = []
        self.Fang_TimberBrep = None
        self.Fang_FacePlaneList = None

        # DB 参数（输入端优先：本步骤暂未增加输入端，所以直接从 AllDict/默认）
        fang_len = _as_float(self.AllDict.get("Fang_DouKouTiao__length_fen", 32.0), 32.0)
        fang_wid = _as_float(self.AllDict.get("Fang_DouKouTiao__width_fen", 32.0), 32.0)
        fang_hgt = _as_float(self.AllDict.get("Fang_DouKouTiao__height_fen", 20.0), 20.0)

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
                fang_len,
                fang_wid,
                fang_hgt,
                rg.Point3d(0.0, 0.0, 0.0),
                _world_xz_plane(),
            )

            self.Fang_TimberBrep = timber_brep
            self.Fang_FaceList = faces
            self.Fang_PointList = points
            self.Fang_EdgeList = edges
            self.Fang_CenterPoint = center_pt
            self.Fang_CenterAxisLines = center_axes
            self.Fang_EdgeMidPoints = edge_midpts
            self.Fang_FacePlaneList = face_planes
            self.Fang_Corner0Planes = corner0_planes
            self.Fang_LocalAxesPlane = local_axes_plane
            self.Fang_AxisX = axis_x
            self.Fang_AxisY = axis_y
            self.Fang_AxisZ = axis_z
            self.Fang_FaceDirTags = face_tags
            self.Fang_EdgeDirTags = edge_tags
            self.Fang_Corner0EdgeDirs = corner0_dirs
            self.Fang_LogLines.extend([str(x) for x in _ensure_list(log_lines)])
        except Exception as e:
            self.Fang_LogLines.append("[ERROR] Fang_DouKouTiao build failed: {}".format(e))

        # -------------------------------------------------
        # 8.3 PlaneFromLists::3（LaoYanFang 的 RectEdgeMidPoints + RefPlaneList）
        # -------------------------------------------------
        try:
            idx_o = self.AllDict.get("PlaneFromLists_3__IndexOrigin", 0)
            idx_p = self.AllDict.get("PlaneFromLists_3__IndexPlane", 0)
            # IndexOrigin/IndexPlane 当前为单值列表时，取第一个值
            if isinstance(idx_o, (list, tuple)):
                idx_o = idx_o[0] if len(idx_o) > 0 else 0
            if isinstance(idx_p, (list, tuple)):
                idx_p = idx_p[0] if len(idx_p) > 0 else 0

            builder = FTPlaneFromLists(wrap=True)
            self.PFL3_BasePlane, self.PFL3_OriginPoint, self.PFL3_ResultPlane, self.PFL3_Log = builder.build_plane(
                self.LYF_RectEdgeMidPoints,
                self.LYF_RefPlaneList,
                idx_o,
                idx_p
            )
            # build_plane 返回 list 时，按当前需求仅取 1 个
            if isinstance(self.PFL3_BasePlane, (list, tuple)):
                self.PFL3_BasePlane = self.PFL3_BasePlane[0] if len(self.PFL3_BasePlane) else None
            if isinstance(self.PFL3_OriginPoint, (list, tuple)):
                self.PFL3_OriginPoint = self.PFL3_OriginPoint[0] if len(self.PFL3_OriginPoint) else None
            if isinstance(self.PFL3_ResultPlane, (list, tuple)):
                self.PFL3_ResultPlane = self.PFL3_ResultPlane[0] if len(self.PFL3_ResultPlane) else None
        except Exception as e:
            self.PFL3_BasePlane, self.PFL3_OriginPoint, self.PFL3_ResultPlane, self.PFL3_Log = None, None, None, [
                "PFL3 failed: {}".format(e)]

        # -------------------------------------------------
        # 8.4 VSG4_GA_LaoYanFang：对位 EveTool（严格单值）
        #   Geo        = LaoYanFang.EveTool（单值）
        #   SourcePlane= PlaneFromLists::3.ResultPlane（单值）
        #   TargetPlane= Transform( VSG3_GA_JiaoHuDou 的 SourcePlane输入值, VSG3_GA_JiaoHuDou 的 TransformOut )
        # -------------------------------------------------
        self.VSG4_LYF_SourceOut = None
        self.VSG4_LYF_TargetOut = None
        self.VSG4_LYF_TransformOut = None
        self.VSG4_LYF_MovedGeo = None
        self.VSG4_LYF_LogLines = []

        # --- Geo 单值 ---
        geo_single = self.LYF_EveTool
        if isinstance(geo_single, (list, tuple)):
            geo_single = geo_single[0] if len(geo_single) else None

        # --- SourcePlane 单值 ---
        sp_single = self.PFL3_ResultPlane
        if isinstance(sp_single, (list, tuple)):
            sp_single = sp_single[0] if len(sp_single) else None

        # --- TargetPlane 单值：Transform( Step5 交互枓对位的 SourcePlane输入值 , Step5 的 TransformOut ) ---
        tp_single = None
        try:
            sp_in = getattr(self, "VSG3_JH_SourcePlaneUsed", None)
            xf_raw = getattr(self, "VSG3_JH_TransformRaw", None)

            # 兼容旧字段（历史文件）
            if sp_in is None:
                sp_in = getattr(self, "VSG3_JH_SourcePlane", None)
            if xf_raw is None:
                xf_raw = getattr(self, "VSG3_JH_TransformOutRaw", None)

            # 若仍是列表，取第一个
            if isinstance(sp_in, (list, tuple)):
                sp_in = sp_in[0] if len(sp_in) else None
            if isinstance(xf_raw, (list, tuple)):
                xf_raw = xf_raw[0] if len(xf_raw) else None

            if sp_in is not None:
                tp_single = rg.Plane(sp_in) if isinstance(sp_in, rg.Plane) else sp_in
                try:
                    if xf_raw is not None and isinstance(tp_single, rg.Plane):
                        tp_single.Transform(xf_raw)
                except Exception:
                    pass
        except Exception as e:
            self.VSG4_LYF_LogLines.append("[WARN] build TargetPlane failed: {}".format(e))

        if tp_single is None:
            tp_single = _default_place_plane()

        # --- 对位参数（单值）---
        rot_val = _as_float(self.AllDict.get("VSG4_GA_LaoYanFang__RotateDeg", 0.0), 0.0)
        movey_val = _as_float(self.AllDict.get("VSG4_GA_LaoYanFang__MoveY", 0.0), 0.0)
        movez_val = _as_float(self.AllDict.get("VSG4_GA_LaoYanFang__MoveZ", 0.0), 0.0)

        try:
            so, to, xf, mg = GeoAligner_xfm.align(
                geo_single,
                sp_single if sp_single is not None else rg.Plane.WorldXY,
                tp_single,
                rotate_deg=rot_val,
                flip_x=0, flip_y=0, flip_z=0,
                move_x=0.0,
                move_y=movey_val,
                move_z=movez_val,
            )
            self.VSG4_LYF_SourceOut = so
            self.VSG4_LYF_TargetOut = to
            self.VSG4_LYF_TransformOut = xf
            self.VSG4_LYF_MovedGeo = mg
        except Exception as e:
            self.VSG4_LYF_LogLines.append("VSG4_LYF GA fail: {}".format(e))
            self.VSG4_LYF_MovedGeo = None

        # 组件装配：保持单值追加
        if self.VSG4_LYF_MovedGeo is not None:
            self.AssemblyParts.append(self.VSG4_LYF_MovedGeo)

        # -------------------------------------------------
        # 8.5 VSG4_GA_Fang：对位 枋（TimberBrep）
        #   按你的补充：该步骤只需要 1 个值，不做广播
        #   TargetPlane = 同 VSG3_GA_TieErDou 的 TargetPlane（已对 VSG2 变换后的平面）
        #   且必须严格等于 self.VSG3_TE_TargetPlaneUsed（避免被其它 tp 覆盖）
        # -------------------------------------------------
        # TargetPlane：只读锁定值（单值）
        tp_vsg3 = getattr(self, "VSG3_TE_TargetPlaneUsed", None)
        if tp_vsg3 is None:
            tp_vsg3 = getattr(self, "VSG3_TE_TargetOut", None)
        if isinstance(tp_vsg3, (list, tuple)):
            tp_vsg3 = tp_vsg3[0] if len(tp_vsg3) > 0 else None

        # 本步骤内部独立变量名，避免覆盖任何其它 tp
        tp_fang = _coerce_plane(tp_vsg3, default=_default_place_plane())

        # 枋几何：TimberBrep（单值）
        g = getattr(self, "Fang_TimberBrep", None)
        if isinstance(g, (list, tuple)):
            g = g[0] if len(g) > 0 else None
        g = _coerce_geo(g)

        # SourcePlane：FacePlaneList 按索引取一个
        src_idx_val = self.AllDict.get("VSG4_GA_Fang__SourcePlane", 0)
        src_idx = _as_int(src_idx_val[0], 0) if isinstance(src_idx_val, (list, tuple)) else _as_int(src_idx_val, 0)
        sp = _pick_by_index(getattr(self, "Fang_FacePlaneList", []), src_idx, default=rg.Plane.WorldXY)
        sp = _coerce_plane(sp, default=rg.Plane.WorldXY)

        # 参数：只取一个
        rot_val = self.AllDict.get("VSG4_GA_Fang__RotateDeg", 0.0)
        rotate_deg = _as_float(rot_val[0], 0.0) if isinstance(rot_val, (list, tuple)) else _as_float(rot_val, 0.0)

        flipx_val = self.AllDict.get("VSG4_GA_Fang__FlipX", 0)
        flip_x = _as_01(flipx_val[0], 0) if isinstance(flipx_val, (list, tuple)) else _as_01(flipx_val, 0)

        movez_val = self.AllDict.get("VSG4_GA_Fang__MoveZ", 0.0)
        move_z = _as_float(movez_val[0], 0.0) if isinstance(movez_val, (list, tuple)) else _as_float(movez_val, 0.0)

        so = to = xf = mg = None
        msgs = []
        try:
            if g is None:
                raise ValueError("Geo is None (Fang_TimberBrep)")
            if sp is None:
                sp = rg.Plane.WorldXY
            if tp_fang is None:
                tp_fang = _default_place_plane()

            # 注意：TargetPlane 严格使用 tp_fang（来源为 VSG3_TE_TargetPlaneUsed）
            so, to, xf, mg = GeoAligner_xfm.align(
                g, sp, tp_fang,
                rotate_deg=rotate_deg,
                flip_x=flip_x, flip_y=0, flip_z=0,
                move_x=0.0, move_y=0.0, move_z=move_z
            )
        except Exception as e:
            msgs.append("VSG4_Fang GA fail : {}".format(e))

        # 输出保持“单值语义”：MovedGeo 仅一个
        self.VSG4_Fang_SourceOut = so
        self.VSG4_Fang_TargetOut = to
        self.VSG4_Fang_TransformOut = xf
        self.VSG4_Fang_MovedGeo = mg
        self.VSG4_Fang_LogLines = msgs
        # 8.6 组装输出：在 Step7 基础上追加 Step8
        parts = []
        _flatten_items(getattr(self, "AssemblyParts", []), parts)
        _flatten_items(self.VSG4_LYF_MovedGeo, parts)
        _flatten_items(self.VSG4_Fang_MovedGeo, parts)
        self.AssemblyParts = parts
        self.ComponentAssembly = parts

        self.LogLines.append("Step 8 完成：LaoYanFang moved={} | Fang moved={}".format(
            (1 if self.VSG4_LYF_MovedGeo is not None else 0),
            (1 if self.VSG4_Fang_MovedGeo is not None else 0)
        ))

    def run(self):
        """执行入口：按 Step1-8 串联计算，并汇总日志。"""

        # PlacePlane 默认兜底
        if getattr(self, "PlacePlane", None) is None:
            try:
                self.PlacePlane = _default_place_plane()
            except Exception:
                pass

        # Step 1：读取数据库（全局）
        self.step1_read_db()

        # Step 2：櫨枓 + 对位
        self.step2_ludou_and_align()

        # Step 3：令栱 + 对位
        self.step3_linggong_and_align()

        # Step 4：乳栿劄牽V2 + PlaneFromLists::1 + 对位
        self.step4_rufuzhaqian_and_align()

        # Step 5：交互枓 + 对位
        self.step5_jiaohudou_and_align()

        # Step 6：散枓 + 对位
        self.step6_sandou_and_align()

        # Step 7：贴耳枓 + 对位
        self.step7_tieerdou_and_align()

        # Step 8：橑檐方 + 枋 + 对位（可选）
        if getattr(self, 'IncludeStep8_LaoYanFangFang', True):
            self.step8_laoyanfang_fang_and_align()
        else:
            try:
                self.LogLines.append('Step 8 跳过：IncludeStep8_LaoYanFangFang=False（不计算/不加入 ComponentAssembly）')
            except:
                pass

        # 追加各对位子模块日志（避免只存到 VSGx_LogLines 而没进全局 LogLines）
        for _nm in [
            "VSG1_LogLines",
            "VSG2_LogLines",
            "VSG2_RF_LogLines",
            "VSG3_LogLines",
            "VSG3_SD_LogLines",
            "VSG3_TE_LogLines",
            "VSG4_LYF_LogLines",
            "VSG4_Fang_LogLines",
        ]:
            try:
                self.LogLines.extend(_ensure_list(getattr(self, _nm, [])))
            except:
                pass

        # 汇总日志
        try:
            # 注意：必须使用显式 "\\n"，避免编辑器把换行打断成非法字符串字面量
            self.Log = "\\n".join([str(x) for x in getattr(self, "LogLines", []) if x is not None])
        except Exception:
            pass

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

    # 可选输入端：是否包含 Step8（橑檐方+枋）
    try:
        _inc8 = IncludeStep8_LaoYanFangFang
    except Exception:
        _inc8 = True

    # 可选输入端：用户可自行在 GH 增加 FT_timber_block_uniform_length_fen 输入端
    try:
        _tlen = FT_timber_block_uniform_length_fen
    except Exception:
        _tlen = None

    solver = DouKouTiaoComponentAssemblySolver(DBPath=_db, PlacePlane=_pp, Refresh=_rf,
                                               IncludeStep8_LaoYanFangFang=_inc8, ghenv=ghenv)
    solver.FT_timber_block_uniform_length_fen = _tlen
    solver = solver.run()

    # --------- 核心对外输出（永远 list，每个元素是 item）---------
    ComponentAssembly = solver.ComponentAssembly
    Log = solver.Log

    # --------- Step 1：全局 DB ---------
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --------- Step 2：LuDou + VSG1_GA_LuDou ---------
    LD_All = getattr(solver, "LD_All", None)
    LD_AllDict = getattr(solver, "LD_AllDict", None)
    LD_Log = getattr(solver, "LD_Log", None)

    LD_CutTimbers = getattr(solver, "LD_CutTimbers", None)
    LD_FacePlaneList = getattr(solver, "LD_FacePlaneList", None)

    VSG1_SourceOut = getattr(solver, "VSG1_SourceOut", None)
    VSG1_TargetOut = getattr(solver, "VSG1_TargetOut", None)
    VSG1_TransformOut = getattr(solver, "VSG1_TransformOut", None)
    VSG1_MovedGeo = getattr(solver, "VSG1_MovedGeo", None)
    VSG1_LogLines = getattr(solver, "VSG1_LogLines", None)

    # --------- Step 3：LingGong + VSG2_GA_LingGong ---------
    # -- LingGong solver（前缀 LG_） --
    LG_CutTimbers = getattr(solver, "LG_CutTimbers", None)
    LG_FailTimbers = getattr(solver, "LG_FailTimbers", None)
    LG_Log = getattr(solver, "LG_Log", None)

    LG_Value = getattr(solver, "LG_Value", None)
    LG_All = getattr(solver, "LG_All", None)
    LG_AllDict = getattr(solver, "LG_AllDict", None)
    LG_DBLog = getattr(solver, "LG_DBLog", None)

    LG_TimberBrep = getattr(solver, "LG_TimberBrep", None)
    LG_FaceList = getattr(solver, "LG_FaceList", None)
    LG_PointList = getattr(solver, "LG_PointList", None)
    LG_EdgeList = getattr(solver, "LG_EdgeList", None)
    LG_CenterPoint = getattr(solver, "LG_CenterPoint", None)
    LG_CenterAxisLines = getattr(solver, "LG_CenterAxisLines", None)
    LG_EdgeMidPoints = getattr(solver, "LG_EdgeMidPoints", None)
    LG_FacePlaneList = getattr(solver, "LG_FacePlaneList", None)
    LG_Corner0Planes = getattr(solver, "LG_Corner0Planes", None)
    LG_LocalAxesPlane = getattr(solver, "LG_LocalAxesPlane", None)
    LG_AxisX = getattr(solver, "LG_AxisX", None)
    LG_AxisY = getattr(solver, "LG_AxisY", None)
    LG_AxisZ = getattr(solver, "LG_AxisZ", None)
    LG_FaceDirTags = getattr(solver, "LG_FaceDirTags", None)
    LG_EdgeDirTags = getattr(solver, "LG_EdgeDirTags", None)
    LG_Corner0EdgeDirs = getattr(solver, "LG_Corner0EdgeDirs", None)

    LG_JuanShaToolBrep = getattr(solver, "LG_JuanShaToolBrep", None)
    LG_JuanShaSectionEdges = getattr(solver, "LG_JuanShaSectionEdges", None)
    LG_JuanShaHL_Intersection = getattr(solver, "LG_JuanShaHL_Intersection", None)
    LG_JuanShaHeightFacePlane = getattr(solver, "LG_JuanShaHeightFacePlane", None)
    LG_JuanShaLengthFacePlane = getattr(solver, "LG_JuanShaLengthFacePlane", None)
    LG_JuanShaLog = getattr(solver, "LG_JuanShaLog", None)

    LG_PF1_BasePlane = getattr(solver, "LG_PF1_BasePlane", None)
    LG_PF1_OriginPoint = getattr(solver, "LG_PF1_OriginPoint", None)
    LG_PF1_ResultPlane = getattr(solver, "LG_PF1_ResultPlane", None)
    LG_PF1_Log = getattr(solver, "LG_PF1_Log", None)

    LG_Align1_AlignedTool = getattr(solver, "LG_Align1_AlignedTool", None)
    LG_Align1_XForm = getattr(solver, "LG_Align1_XForm", None)
    LG_Align1_SourcePlane = getattr(solver, "LG_Align1_SourcePlane", None)
    LG_Align1_TargetPlane = getattr(solver, "LG_Align1_TargetPlane", None)
    LG_Align1_SourcePoint = getattr(solver, "LG_Align1_SourcePoint", None)
    LG_Align1_TargetPoint = getattr(solver, "LG_Align1_TargetPoint", None)
    LG_Align1_DebugInfo = getattr(solver, "LG_Align1_DebugInfo", None)

    LG_BlockCutter_TimberBrep = getattr(solver, "LG_BlockCutter_TimberBrep", None)
    LG_BlockCutter_FacePlaneList = getattr(solver, "LG_BlockCutter_FacePlaneList", None)
    LG_BlockCutter_Log = getattr(solver, "LG_BlockCutter_Log", None)

    LG_Align2_AlignedTool = getattr(solver, "LG_Align2_AlignedTool", None)
    LG_Align2_XForm = getattr(solver, "LG_Align2_XForm", None)
    LG_Align2_SourcePlane = getattr(solver, "LG_Align2_SourcePlane", None)
    LG_Align2_TargetPlane = getattr(solver, "LG_Align2_TargetPlane", None)
    LG_Align2_SourcePoint = getattr(solver, "LG_Align2_SourcePoint", None)
    LG_Align2_TargetPoint = getattr(solver, "LG_Align2_TargetPoint", None)
    LG_Align2_DebugInfo = getattr(solver, "LG_Align2_DebugInfo", None)

    LG_GongYan_SectionFace = getattr(solver, "LG_GongYan_SectionFace", None)
    LG_GongYan_OffsetFace = getattr(solver, "LG_GongYan_OffsetFace", None)
    LG_GongYan_Points = getattr(solver, "LG_GongYan_Points", None)
    LG_GongYan_OffsetPoints = getattr(solver, "LG_GongYan_OffsetPoints", None)
    LG_GongYan_ToolBrep = getattr(solver, "LG_GongYan_ToolBrep", None)
    LG_GongYan_BridgePoints = getattr(solver, "LG_GongYan_BridgePoints", None)
    LG_GongYan_BridgeMidPoints = getattr(solver, "LG_GongYan_BridgeMidPoints", None)
    LG_GongYan_BridgePlane = getattr(solver, "LG_GongYan_BridgePlane", None)
    LG_GongYan_Log = getattr(solver, "LG_GongYan_Log", None)

    LG_PF2_BasePlane = getattr(solver, "LG_PF2_BasePlane", None)
    LG_PF2_OriginPoint = getattr(solver, "LG_PF2_OriginPoint", None)
    LG_PF2_ResultPlane = getattr(solver, "LG_PF2_ResultPlane", None)
    LG_PF2_Log = getattr(solver, "LG_PF2_Log", None)

    LG_PF3_BasePlane = getattr(solver, "LG_PF3_BasePlane", None)
    LG_PF3_OriginPoint = getattr(solver, "LG_PF3_OriginPoint", None)
    LG_PF3_ResultPlane = getattr(solver, "LG_PF3_ResultPlane", None)
    LG_PF3_Log = getattr(solver, "LG_PF3_Log", None)

    LG_GeoAligner1_SourceOut = getattr(solver, "LG_GeoAligner1_SourceOut", None)
    LG_GeoAligner1_TargetOut = getattr(solver, "LG_GeoAligner1_TargetOut", None)
    LG_GeoAligner1_MovedGeo = getattr(solver, "LG_GeoAligner1_MovedGeo", None)

    # -- VSG2 对位输出 --
    VSG2_TargetPlaneCandidates = getattr(solver, "VSG2_TargetPlaneCandidates", None)
    VSG2_SourceOut = getattr(solver, "VSG2_SourceOut", None)
    VSG2_TargetOut = getattr(solver, "VSG2_TargetOut", None)
    VSG2_TransformOut = getattr(solver, "VSG2_TransformOut", None)
    VSG2_MovedGeo = getattr(solver, "VSG2_MovedGeo", None)
    VSG2_LogLines = getattr(solver, "VSG2_LogLines", None)

    # --------- Step 4：RufuZhaQianV2 + PlaneFromLists::1 + VSG2_GA_RufuZhaQian ---------
    RF_CutTimbers = getattr(solver, "RF_CutTimbers", None)
    RF_FailTimbers = getattr(solver, "RF_FailTimbers", None)
    RF_Log = getattr(solver, "RF_Log", None)
    RF_EdgeMidPoints = getattr(solver, "RF_EdgeMidPoints", None)
    RF_Corner0Planes = getattr(solver, "RF_Corner0Planes", None)

    PFL1_BasePlane = getattr(solver, "PFL1_BasePlane", None)
    PFL1_OriginPoint = getattr(solver, "PFL1_OriginPoint", None)
    PFL1_ResultPlane = getattr(solver, "PFL1_ResultPlane", None)
    PFL1_Log = getattr(solver, "PFL1_Log", None)

    VSG2_TargetPlaneUsed = getattr(solver, "VSG2_TargetPlaneUsed", None)

    VSG2_RF_SourceOut = getattr(solver, "VSG2_RF_SourceOut", None)
    VSG2_RF_TargetOut = getattr(solver, "VSG2_RF_TargetOut", None)
    VSG2_RF_TransformOut = getattr(solver, "VSG2_RF_TransformOut", None)
    VSG2_RF_MovedGeo = getattr(solver, "VSG2_RF_MovedGeo", None)
    VSG2_RF_LogLines = getattr(solver, "VSG2_RF_LogLines", None)

    # --------- Step 5：JiaoHuDou + VSG3_GA_JiaoHuDou ---------
    JH_CutTimbers = getattr(solver, "JH_CutTimbers", None)
    JH_FailTimbers = getattr(solver, "JH_FailTimbers", None)
    JH_FacePlaneList = getattr(solver, "JH_FacePlaneList", None)
    JH_Log = getattr(solver, "JH_Log", None)
    JH_DBLog = getattr(solver, "JH_DBLog", None)

    VSG3_TargetPlaneCandidates = getattr(solver, "VSG3_TargetPlaneCandidates", None)
    VSG3_TargetPlaneUsed = getattr(solver, "VSG3_TargetPlaneUsed", None)

    VSG3_SourceOut = getattr(solver, "VSG3_SourceOut", None)
    VSG3_TargetOut = getattr(solver, "VSG3_TargetOut", None)
    VSG3_TransformOut = getattr(solver, "VSG3_TransformOut", None)
    VSG3_MovedGeo = getattr(solver, "VSG3_MovedGeo", None)
    VSG3_LogLines = getattr(solver, "VSG3_LogLines", None)

    # --------- Step 6：SanDou + PlaneFromLists::2 + VSG3_GA_SanDou ---------
    SD_CutTimbers = getattr(solver, "SD_CutTimbers", None)
    SD_FailTimbers = getattr(solver, "SD_FailTimbers", None)
    SD_FacePlaneList = getattr(solver, "SD_FacePlaneList", None)
    SD_Log = getattr(solver, "SD_Log", None)

    PFL2_BasePlane = getattr(solver, "PFL2_BasePlane", None)
    PFL2_OriginPoint = getattr(solver, "PFL2_OriginPoint", None)
    PFL2_ResultPlane = getattr(solver, "PFL2_ResultPlane", None)
    PFL2_Log = getattr(solver, "PFL2_Log", None)

    VSG3_SD_SourceOut = getattr(solver, "VSG3_SD_SourceOut", None)
    VSG3_SD_TargetOut = getattr(solver, "VSG3_SD_TargetOut", None)
    VSG3_SD_TransformOut = getattr(solver, "VSG3_SD_TransformOut", None)
    VSG3_SD_MovedGeo = getattr(solver, "VSG3_SD_MovedGeo", None)
    VSG3_SD_LogLines = getattr(solver, "VSG3_SD_LogLines", None)

    # --------- Step 7：TieErDou + VSG3_GA_TieErDou ---------
    TE_CutTimbers = getattr(solver, "TE_CutTimbers", None)
    TE_FailTimbers = getattr(solver, "TE_FailTimbers", None)
    TE_FacePlaneList = getattr(solver, "TE_FacePlaneList", None)
    TE_Log = getattr(solver, "TE_Log", None)

    VSG3_TE_SourceOut = getattr(solver, "VSG3_TE_SourceOut", None)
    VSG3_TE_TargetOut = getattr(solver, "VSG3_TE_TargetOut", None)
    VSG3_TE_TransformOut = getattr(solver, "VSG3_TE_TransformOut", None)
    VSG3_TE_MovedGeo = getattr(solver, "VSG3_TE_MovedGeo", None)
    VSG3_TE_TargetPlaneUsed = getattr(solver, "VSG3_TE_TargetPlaneUsed", None)
    VSG3_TE_LogLines = getattr(solver, "VSG3_TE_LogLines", None)

    # --------- Step 8：LaoYanFang + Fang + PlaneFromLists::3 + VSG4 ---------
    LYF_EveTool = getattr(solver, "LYF_EveTool", None)
    LYF_RectEdgeMidPoints = getattr(solver, "LYF_RectEdgeMidPoints", None)
    LYF_RefPlaneList = getattr(solver, "LYF_RefPlaneList", None)
    LYF_LogLines = getattr(solver, "LYF_LogLines", None)

    Fang_TimberBrep = getattr(solver, "Fang_TimberBrep", None)
    Fang_FacePlaneList = getattr(solver, "Fang_FacePlaneList", None)
    Fang_LogLines = getattr(solver, "Fang_LogLines", None)

    PFL3_BasePlane = getattr(solver, "PFL3_BasePlane", None)
    PFL3_OriginPoint = getattr(solver, "PFL3_OriginPoint", None)
    PFL3_ResultPlane = getattr(solver, "PFL3_ResultPlane", None)
    PFL3_Log = getattr(solver, "PFL3_Log", None)

    VSG4_LYF_SourceOut = getattr(solver, "VSG4_LYF_SourceOut", None)
    VSG4_LYF_TargetOut = getattr(solver, "VSG4_LYF_TargetOut", None)
    VSG4_LYF_TransformOut = getattr(solver, "VSG4_LYF_TransformOut", None)
    VSG4_LYF_MovedGeo = getattr(solver, "VSG4_LYF_MovedGeo", None)
    VSG4_LYF_LogLines = getattr(solver, "VSG4_LYF_LogLines", None)

    VSG4_Fang_SourceOut = getattr(solver, "VSG4_Fang_SourceOut", None)
    VSG4_Fang_TargetOut = getattr(solver, "VSG4_Fang_TargetOut", None)
    VSG4_Fang_TransformOut = getattr(solver, "VSG4_Fang_TransformOut", None)
    VSG4_Fang_MovedGeo = getattr(solver, "VSG4_Fang_MovedGeo", None)
    VSG4_Fang_LogLines = getattr(solver, "VSG4_Fang_LogLines", None)

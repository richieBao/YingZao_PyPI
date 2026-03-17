# -*- coding: utf-8 -*-
"""
FT_CutTimbersByTools_GH_SolidDifference (v1.0)
------------------------------------------------------------
将“Timbers - Tools”裁切逻辑封装为一个独立 GhPython 组件，内部直接调用
Grasshopper 内置组件：Solid Difference（Region / Solid / Brep 差集）。

适用场景：
- 你在 Solver 内部调用 RhinoCommon BooleanDifference 可能失败/不稳定；
- 直接调用 ghpythonlib.components.SolidDifference 的表现更接近 GH 原生组件；
- Tools 支持嵌套 list/tuple（会递归拍平）；
- 输出端避免出现 System.Collections.Generic.List`1[System.Object] 的嵌套列表问题。

输入（GhPython 组件输入端建议）：
    Timbers    : object / Brep / list
        要裁切的木料（可为单个 Brep 或列表）
    Tools      : object / Brep / list / tree-like
        刀具（可嵌套 list/tuple；会递归拍平并过滤 None）
    KeepInside : bool (optional)
        兼容你原先组件的输入端，但 GH SolidDifference 本身不带 keep_inside；
        这里仅用于日志记录（不参与运算）。
    Debug      : bool (optional)
        True 时输出更多日志。

输出：
    CutTimbers  : list
    FailTimbers : list
    Log         : list[str]

FT_CutTimbersByTools_GH_SolidDifference (Class Version v1.0)
------------------------------------------------------------
把 “Timbers - Tools” 差集裁切封装成可复用的类：
- 内部调用 ghpythonlib.components.SolidDifference（更贴近 GH 原生）
- Tools 支持嵌套 list/tuple（递归拍平）
- 统一做 Brep coercion，避免 Goo/Proxy 问题
- 输出拍平，避免出现 System.Collections.Generic.List`1[System.Object] 的嵌套

用法：
    cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=True)
    cut, fail, log = cutter.cut(Timbers, Tools, keep_inside=False)

或：
    cutter = FT_CutTimbersByTools_GH_SolidDifference()
    cut, fail, log = cutter(Timbers, Tools)  # __call__
"""

import Rhino.Geometry as rg

try:
    import ghpythonlib.components as ghc
except Exception:
    ghc = None


class FT_CutTimbersByTools_GH_SolidDifference(object):
    def __init__(self, debug=False):
        self.debug = bool(debug)

    # =========================================================
    # Helpers (as methods for easy overriding)
    # =========================================================
    def _flatten_any(self, x):
        """递归拍平 list/tuple；不对 Rhino 几何做 iterable 展开。"""
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            out = []
            for it in x:
                if isinstance(it, (list, tuple)):
                    out.extend(self._flatten_any(it))
                else:
                    out.append(it)
            return out
        return [x]

    def _coerce_brep(self, x):
        """尽可能把 Goo/Proxy 转为 Rhino.Geometry.Brep。"""
        if x is None:
            return None
        if isinstance(x, rg.Brep):
            return x

        # GH Goo
        try:
            v = getattr(x, "Value", None)
            if isinstance(v, rg.Brep):
                return v
        except Exception:
            pass

        # TryConvert
        try:
            b = rg.Brep.TryConvertBrep(x)
            if isinstance(b, rg.Brep):
                return b
        except Exception:
            pass

        return None

    def _as_brep_list(self, x):
        items = self._flatten_any(x)
        breps = []
        for it in items:
            b = self._coerce_brep(it)
            if b is not None:
                breps.append(b)
        return breps

    # =========================================================
    # Core API
    # =========================================================
    def cut(self, timbers, tools, keep_inside=False, debug=None):
        """
        返回 (CutTimbers, FailTimbers, Log)
        keep_inside：仅记录（兼容旧接口），不参与 GH SolidDifference 运算
        debug：可临时覆盖 self.debug
        """
        Log = []
        CutTimbers = []
        FailTimbers = []

        dbg = self.debug if debug is None else bool(debug)
        _keep_inside = bool(keep_inside)

        if ghc is None:
            Log.append("[ERROR] ghpythonlib.components 不可用：无法调用 GH SolidDifference。")
            return CutTimbers, FailTimbers, Log

        timber_list = self._as_brep_list(timbers)
        tool_list = self._as_brep_list(tools)

        Log.append("[INFO] KeepInside(仅记录) = {}".format(_keep_inside))
        Log.append("[INFO] Timbers count = {}".format(len(timber_list)))
        Log.append("[INFO] Tools count   = {}".format(len(tool_list)))

        if len(timber_list) == 0:
            Log.append("[WARN] Timbers 为空：无输出。")
            return CutTimbers, FailTimbers, Log

        if len(tool_list) == 0:
            Log.append("[WARN] Tools 为空：不切削，直接输出 Timbers。")
            CutTimbers = timber_list[:]
            CutTimbers = self._flatten_any(CutTimbers)
            FailTimbers = self._flatten_any(FailTimbers)
            Log = [str(x) for x in self._flatten_any(Log)]
            return CutTimbers, FailTimbers, Log

        # 对每个 timber 做一次 SolidDifference
        for i, tb in enumerate(timber_list):
            try:
                res = ghc.SolidDifference(tb, tool_list)

                # 兼容 ghc 返回 tuple 的情况
                res0 = res[0] if (isinstance(res, tuple) and len(res) > 0) else res

                parts = self._flatten_any(res0)
                parts = [p for p in parts if p is not None]

                # GH 可能返回非 Brep（极少数），这里尽量再 coerce 一次
                parts_brep = []
                for p in parts:
                    b = self._coerce_brep(p)
                    parts_brep.append(b if b is not None else p)

                if len(parts_brep) == 0:
                    FailTimbers.append(tb)
                    Log.append("[WARN] timber#{} 差集结果为空（可能无交/失败）。".format(i))
                else:
                    CutTimbers.extend(parts_brep)
                    if dbg:
                        Log.append("[DEBUG] timber#{} -> parts={}".format(i, len(parts_brep)))

            except Exception as e:
                FailTimbers.append(tb)
                Log.append("[ERROR] timber#{} SolidDifference 异常: {}".format(i, e))

        # 输出拍平，避免 GH 嵌套列表显示
        CutTimbers = self._flatten_any(CutTimbers)
        FailTimbers = self._flatten_any(FailTimbers)
        Log = [str(x) for x in self._flatten_any(Log)]
        return CutTimbers, FailTimbers, Log

    def __call__(self, timbers, tools, keep_inside=False, debug=None):
        """允许 cutter(Timbers, Tools) 这样直接调用。"""
        return self.cut(timbers, tools, keep_inside=keep_inside, debug=debug)


# =========================================================
# GH 组件式入口（可选）
# 你也可以把下面这段删掉，只保留类，然后在 Solver 里 import 使用
# =========================================================
if __name__ == "__main__":
    # 兼容 GH：未提供输入时的默认处理
    if "Debug" in globals():
        _dbg_in = Debug
    else:
        _dbg_in = None

    if "KeepInside" in globals():
        _ki_in = KeepInside
    else:
        _ki_in = False

    cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(_dbg_in) if _dbg_in is not None else False)
    CutTimbers, FailTimbers, Log = cutter.cut(
        timbers=globals().get("Timbers", None),
        tools=globals().get("Tools", None),
        keep_inside=_ki_in,
        debug=_dbg_in
    )

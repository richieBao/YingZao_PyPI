# -*- coding: utf-8 -*-
"""FT_CutTimberByTools

用对位后的刀具几何裁切木料几何。
"""

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System
import traceback

# ------------------------------------------------------------
# 可选：调用 Grasshopper 组件（Solid Difference/Intersection）兜底
# ------------------------------------------------------------
try:
    import ghpythonlib.components as ghcomp
    _HAS_GHCOMP = True
except:
    ghcomp = None
    _HAS_GHCOMP = False


class FT_CutTimberByTools_V2(object):
    """封装全部裁切逻辑的类。"""

    # --------- 构造函数 ---------
    def __init__(self, timbers, tools, keep_inside=False, doc=None, tol=None):

        self._raw_timbers = timbers
        self._raw_tools = tools
        self.keep_inside = bool(keep_inside)
        self.doc = doc or sc.doc

        if tol is not None:
            self.tol = float(tol)
        else:
            self.tol = self.doc.ModelAbsoluteTolerance if self.doc else 0.001

        # 微推进量（避免共面）
        self.eps = max(self.tol * 2.0, 0.05)

        self.cut_timbers = []
        self.fail_timbers = []
        self.log = []
        self.log.append(u"模型公差: %.6f" % self.tol)
        self.log.append(u"Eps (nudge) = %.4f" % self.eps)
        self.log.append(u"KeepInside = %s" % self.keep_inside)
        self.log.append(u"GH Solid Fallback = %s" % (_HAS_GHCOMP))

        self.tool_breps = []
        self.union_tools = None

    # =========================================================
    # 原有工具函数（不改）
    # =========================================================
    @staticmethod
    def _to_brep(geo):
        if geo is None:
            return None
        if isinstance(geo, rg.Brep):
            return geo
        if isinstance(geo, rg.Extrusion):
            return geo.ToBrep()
        if isinstance(geo, rg.Surface):
            return rg.Brep.CreateFromSurface(geo)
        if isinstance(geo, rg.Mesh):
            breps = rg.Brep.CreateFromMesh(geo, True)
            if breps:
                return breps[0]
        return None

    def _as_brep_list(self, x):
        if x is None:
            return []
        try:
            from Grasshopper import DataTree
            if isinstance(x, DataTree):
                out = []
                for p in x.Paths:
                    for it in x.Branch(p):
                        b = self._to_brep(it)
                        if b: out.append(b)
                return out
        except:
            pass
        if isinstance(x, (list, tuple)):
            return [self._to_brep(i) for i in x if self._to_brep(i)]
        b = self._to_brep(x)
        return [b] if b else []

    # =========================================================
    # 新增：调度辅助工具
    # =========================================================
    def _flatten(self, x):
        out = []
        if x is None:
            return out
        try:
            from Grasshopper import DataTree
            if isinstance(x, DataTree):
                for p in x.Paths:
                    out.extend(list(x.Branch(p)))
                return out
        except:
            pass
        if isinstance(x, (list, tuple)):
            for i in x:
                out.extend(self._flatten(i))
            return out
        return [x]

    def _bbox_intersects(self, a, b):
        return a.GetBoundingBox(True).Intersects(b.GetBoundingBox(True))

    def _classify_tool(self, timber, tool):
        if not self._bbox_intersects(timber, tool):
            return "NO_INTERSECT"

        d = rg.Brep.CreateBooleanDifference([timber], [tool], self.tol)
        if d and len(d) > 0:
            return "GOOD"

        i = rg.Brep.CreateBooleanIntersection([timber], [tool], self.tol)
        if i and len(i) > 0:
            return "PROBLEMATIC"

        return "TOUCH_ONLY"

    def _nudge_tool(self, tool):
        bb = tool.GetBoundingBox(True)
        v = bb.Max - bb.Min
        axis = rg.Vector3d(v.X, v.Y, v.Z)
        if axis.IsZero: return tool
        axis.Unitize()
        t = rg.Transform.Translation(axis * self.eps)
        b = tool.DuplicateBrep()
        b.Transform(t)
        return b

    # =========================================================
    # 原有 Boolean / GH fallback（不改）
    # =========================================================
    def _boolean_union(self, breps):
        try:
            u = rg.Brep.CreateBooleanUnion(breps, self.tol)
            return list(u) if u else None
        except:
            return None

    def _gh_solid_difference(self, targets, cutters):
        if not _HAS_GHCOMP: return None
        try:
            r = ghcomp.SolidDifference(targets, cutters)
            out = self._as_brep_list(r)
            return out if out else None
        except:
            return None

    # =========================================================
    # 原有步骤 1（不改）
    # =========================================================
    def _preprocess_tools(self):
        tools = self._flatten(self._raw_tools)
        self.log.append(u"输入刀具数量: %d" % len(tools))

        for i, g in enumerate(tools):
            b = self._to_brep(g)
            if not b:
                self.log.append(u"工具 #%d 无法转为 Brep，忽略。" % i)
                continue
            self.tool_breps.append(b)
            self.log.append(u"工具 #%d 转为封闭 Brep。" % i)

        if self.tool_breps:
            self.union_tools = self._boolean_union(self.tool_breps)
            if self.union_tools:
                self.log.append(u"刀具 BooleanUnion 成功，数量：%d" % len(self.union_tools))
            else:
                self.log.append(u"刀具 BooleanUnion 失败，将逐个刀具布尔运算。")

    # =========================================================
    # 步骤 2：裁切（保留原逻辑 + 鲁棒调度兜底）
    # =========================================================
    def _cut_all_timbers(self):

        timbers = self._flatten(self._raw_timbers)
        self.log.append(u"输入木料数量: %d" % len(timbers))

        for idx, geo in enumerate(timbers):

            timber = self._to_brep(geo)
            if not timber:
                self.fail_timbers.append(geo)
                continue

            current = timber
            success = False

            # ---------- 原有 Difference / Union / 逐刀逻辑 ----------
            if self.union_tools:
                r = self._gh_solid_difference([current], self.union_tools)
                if r:
                    self.cut_timbers.extend(r)
                    success = True

            if not success:
                tmp = current
                ok = True
                for tb in self.tool_breps:
                    r = rg.Brep.CreateBooleanDifference([tmp], [tb], self.tol)
                    if not r:
                        ok = False
                        break
                    tmp = r[0]
                if ok:
                    self.cut_timbers.append(tmp)
                    success = True

            # ---------- 新增：鲁棒调度器兜底 ----------
            if not success:
                self.log.append(u"[ROBUST] 启动鲁棒调度器。")

                GOOD, PROB = [], []
                for j, tb in enumerate(self.tool_breps):
                    cls = self._classify_tool(current, tb)
                    self.log.append(u"[ROBUST] Tool #%d → %s" % (j, cls))
                    if cls == "GOOD":
                        GOOD.append(tb)
                    elif cls == "PROBLEMATIC":
                        PROB.append(tb)

                for tb in GOOD:
                    r = rg.Brep.CreateBooleanDifference([current], [tb], self.tol)
                    if r:
                        current = r[0]

                for tb in PROB:
                    r = self._gh_solid_difference([current], [tb])
                    if r:
                        current = r[0]
                        continue
                    nudged = self._nudge_tool(tb)
                    r2 = rg.Brep.CreateBooleanDifference([current], [nudged], self.tol)
                    if r2:
                        current = r2[0]

                self.cut_timbers.append(current)
                success = True

            if not success:
                self.fail_timbers.append(geo)

    # =========================================================
    # 主入口
    # =========================================================
    def run(self):
        try:
            self._preprocess_tools()
            self._cut_all_timbers()
        except Exception as e:
            self.log.append(u"异常: %s" % e)
            self.log.append(traceback.format_exc())

        self.log.append(u"最终 CutTimbers 数量: %d" % len(self.cut_timbers))
        self.log.append(u"最终 FailTimbers 数量: %d" % len(self.fail_timbers))
        return self.cut_timbers, self.fail_timbers, self.log


if __name__ == "__main__":

    try:
        _keep_inside_flag = bool(KeepInside)
    except:
        _keep_inside_flag = False

    cutter = FT_CutTimberByTools_V2(
        Timbers,
        Tools,
        keep_inside=_keep_inside_flag
    )

    CutTimbers, FailTimbers, Log = cutter.run()
    print("CutTimbers:", CutTimbers)

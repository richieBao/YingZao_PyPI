# -*- coding: utf-8 -*-
"""
FrontRafterArranger.py
正面布椽组件（GhPython / ghpy 可直接粘贴版本）

功能概要：
    依据一组空间水平直线（或可转为直线的曲线），按高度排序后形成
    L_0, L_1, L_2, ... 的逻辑层级；
    若 IncludeLa=True，则默认输入中包含 L_a（牛脊槫上皮线），
    会将排序后的“第二根线”剔除，再重新编号；
    随后对每一对相邻水平线：
        (L_n, L_{n-1})
    按椽距布置步椽线，并按“隔组错半椽距”的方式交错排布；
    最下组（L_1-L_0）在 L_0 端按出檐椽长延长，其余组两端按常规延长长度处理；
    最终输出：
        1) 所有组的步椽线（Tree）
        2) 所有组的封闭管状椽（Tree）

------------------------------------------------------------
输入（GhPython 建议设置）:
    HorizontalLines : list[rg.Curve]
        Access = List
        TypeHint = Curve
        一组空间水平直线列表。
        建议输入为 Line / LineCurve / NurbsCurve(直线)。
        要求大体彼此平行，且均为“水平线”（端点 Z 基本相同）。

    RefPlane : rg.Plane
        Access = Item
        TypeHint = Plane
        参考平面。可为空；为空时默认 WorldXY。

    RafterDiameter : float
        Access = Item
        TypeHint = float
        椽径。

    RafterSpacing : float
        Access = Item
        TypeHint = float
        椽距。

    EaveRafterLength : float
        Access = Item
        TypeHint = float
        最下组（L_1-L_0）在 L_0 端的出檐椽长。

    ExtendLength : float
        Access = Item
        TypeHint = float
        常规步椽两端延长长度；
        最下组仅上端仍使用该值。

    IncludeLa : bool
        Access = Item
        TypeHint = bool
        输入列表是否包含 L_a（牛脊槫上皮线）。
        默认 True。
        若为 True，则排序后会移除第 2 根线（索引 1），
        即视其为 L_a，并对剩余线重新编号为 L_0, L_1, L_2...

输出（可按需在 GH 中添加同名输出端）:
    RafterLinesTree : DataTree[object]
        Tree 型步椽中心线。每个 branch 对应一组相邻水平线之间的步椽。

    RafterSolidsTree : DataTree[object]
        Tree 型封闭椽体（Pipe Brep）。

    SortedInputLines : list[rg.LineCurve]
        按输入起点 Z 从低到高排序后的线（未剔除 L_a 前）。

    EffectiveLines : list[rg.LineCurve]
        实际参与计算的水平线（可能已剔除 L_a）。

    EffectiveLabels : list[str]
        EffectiveLines 对应逻辑编号标签，如 ["L_0","L_1","L_2"...]。

    GroupLabelPairs : list[str]
        每一组对应标签，如 ["L_1-L_0","L_2-L_1","L_3-L_2"...]。

    DivisionPtsTree : DataTree[object]
        每组的配对分点，按 branch 输出。
        每个 branch 内按 [上线点, 下线点, 上线点, 下线点, ...] 顺序排列。

    Log : list[str]
        过程日志，便于调试。

依赖：
    RhinoCommon
    Grasshopper DataTree

作者说明：
    该脚本已封装为类与方法，后续便于拆分为 ghpy 模块或被其他组件调用。
"""

import math
import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc

from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path


# ============================================================
# 工具类
# ============================================================

class FrontRafterArranger(object):
    def __init__(self, ref_plane=None, tol=None, ang_tol=None):
        self.ref_plane = ref_plane if (ref_plane and ref_plane.IsValid) else rg.Plane.WorldXY
        self.tol = tol if tol is not None else sc.doc.ModelAbsoluteTolerance
        self.ang_tol = ang_tol if ang_tol is not None else sc.doc.ModelAngleToleranceRadians
        self.log = []

    # -----------------------------
    # 日志
    # -----------------------------
    def _add_log(self, msg):
        self.log.append(msg)

    # -----------------------------
    # 输入转直线
    # -----------------------------
    def to_linecurve(self, crv_like):
        if crv_like is None:
            return None

        if isinstance(crv_like, rg.Line):
            return rg.LineCurve(crv_like)

        if isinstance(crv_like, rg.LineCurve):
            return crv_like

        if isinstance(crv_like, rg.Curve):
            ok, ln = crv_like.TryGetLine()
            if ok:
                return rg.LineCurve(ln)

        return None

    # -----------------------------
    # 判定水平
    # -----------------------------
    def is_horizontal_linecurve(self, lc):
        if lc is None:
            return False
        sp = lc.PointAtStart
        ep = lc.PointAtEnd
        return abs(sp.Z - ep.Z) <= self.tol

    # -----------------------------
    # 统一方向（尽量与参考平面 XAxis 同向；若更接近反向则翻转）
    # -----------------------------
    def unify_direction(self, lc):
        if lc is None:
            return None

        sp = lc.PointAtStart
        ep = lc.PointAtEnd
        v = ep - sp
        if not v.Unitize():
            return lc

        rx = rg.Vector3d(self.ref_plane.XAxis)
        ry = rg.Vector3d(self.ref_plane.YAxis)
        rx.Unitize()
        ry.Unitize()

        # 选择与 X/Y 更接近的参考方向作为“正向”
        dotx = abs(rg.Vector3d.Multiply(v, rx))
        doty = abs(rg.Vector3d.Multiply(v, ry))
        ref = rx if dotx >= doty else ry

        if rg.Vector3d.Multiply(v, ref) < 0:
            return rg.LineCurve(ep, sp)

        return lc

    # -----------------------------
    # 平均起点 Z 排序
    # -----------------------------
    def sort_lines_by_start_z(self, linecurves):
        valid = []
        for i, lc in enumerate(linecurves):
            if lc is None:
                self._add_log("[WARN] 第 {} 个输入无法转为直线，已跳过。".format(i))
                continue
            if not self.is_horizontal_linecurve(lc):
                self._add_log("[WARN] 第 {} 个输入不是水平线，已跳过。".format(i))
                continue
            lc2 = self.unify_direction(lc)
            valid.append(lc2)

        valid.sort(key=lambda c: c.PointAtStart.Z)
        return valid

    # -----------------------------
    # 若输入包含 L_a，则移除排序后索引 1 的线
    # -----------------------------
    def build_effective_lines(self, sorted_lines, include_la=True):
        lines = list(sorted_lines)
        if include_la:
            if len(lines) >= 2:
                removed = lines.pop(1)
                self._add_log("[OK] IncludeLa=True，已移除排序后索引 1 的线，视为 L_a。")
                self._add_log("      被移除线起点 Z = {:.6f}".format(removed.PointAtStart.Z))
            else:
                self._add_log("[WARN] IncludeLa=True，但有效线数量不足 2，无法移除 L_a。")

        labels = ["L_{}".format(i) for i in range(len(lines))]
        return lines, labels

    # -----------------------------
    # 获取线方向
    # -----------------------------
    def line_unit_dir(self, lc):
        v = lc.PointAtEnd - lc.PointAtStart
        v.Unitize()
        return v

    # -----------------------------
    # 获取某条线在给定方向上的标量范围
    # -----------------------------
    def scalar_range_on_axis(self, lc, origin, axis_u):
        s0 = rg.Vector3d.Multiply(lc.PointAtStart - origin, axis_u)
        s1 = rg.Vector3d.Multiply(lc.PointAtEnd - origin, axis_u)
        return (min(s0, s1), max(s0, s1))

    # -----------------------------
    # 由“参考轴上的标量位置”找线上的对应点
    # 做法：先构造轴上目标点，再求其在线上的最近点
    # -----------------------------
    def point_on_line_by_scalar(self, lc, origin, axis_u, scalar_s):
        target = origin + axis_u * scalar_s
        ok, t = lc.ClosestPoint(target)
        if not ok:
            return None
        return lc.PointAt(t)

    # -----------------------------
    # 计算一组相邻水平线的布点标量
    #
    # 规则：
    #   - 相邻组交错半个椽距
    #   - i=0 (L_1-L_0) 不错半距
    #   - i=1 (L_2-L_1) 错半距
    #   - i=2 (L_3-L_2) 不错半距
    #   ...
    #
    #   其中 pair_index 取“下线编号”，
    #   即：
    #       组 L_(i+1)-L_i 的 pair_index = i
    # -----------------------------
    def build_pair_scalars(self, lower_lc, upper_lc, pair_index, spacing):
        if spacing <= self.tol:
            self._add_log("[ERR] 椽距必须大于 0。")
            return [], None, None, None

        # 以参考平面原点为投影标量基点，方向使用 lower_lc 方向
        axis_u = self.line_unit_dir(lower_lc)
        axis_origin = self.ref_plane.Origin

        r0 = self.scalar_range_on_axis(lower_lc, axis_origin, axis_u)
        r1 = self.scalar_range_on_axis(upper_lc, axis_origin, axis_u)

        overlap_min = max(r0[0], r1[0])
        overlap_max = min(r0[1], r1[1])

        if overlap_max - overlap_min <= self.tol:
            self._add_log("[WARN] 一组相邻线无有效重叠区间，跳过该组。")
            return [], axis_origin, axis_u, (overlap_min, overlap_max)

        offset = 0.0 if (pair_index % 2 == 0) else spacing * 0.5

        scalars = []
        s = overlap_min + offset

        # 若偏移后已经越界，则尝试往前回退一个 spacing 周期内的最近点
        while s - spacing >= overlap_min - self.tol:
            s -= spacing

        while s < overlap_min - self.tol:
            s += spacing

        while s <= overlap_max + self.tol:
            if s >= overlap_min - self.tol and s <= overlap_max + self.tol:
                scalars.append(s)
            s += spacing

        # 若一个点都没有，则取重叠中点兜底
        if len(scalars) == 0:
            scalars = [(overlap_min + overlap_max) * 0.5]
            self._add_log("[WARN] 该组按椽距未得到分点，已自动使用中点兜底。")

        return scalars, axis_origin, axis_u, (overlap_min, overlap_max)

    # -----------------------------
    # 构造单根步椽线并延长
    # upper_pt -> lower_pt
    # 上端延 upper_ext
    # 下端延 lower_ext
    # -----------------------------
    def build_rafter_line(self, upper_pt, lower_pt, upper_ext, lower_ext):
        if upper_pt is None or lower_pt is None:
            return None

        v = lower_pt - upper_pt
        if not v.Unitize():
            return None

        new_start = upper_pt - v * upper_ext
        new_end = lower_pt + v * lower_ext
        return rg.LineCurve(new_start, new_end)

    # -----------------------------
    # Pipe 成实体
    # -----------------------------
    def pipe_from_curve(self, crv, diameter):
        if crv is None:
            return None
        radius = max(0.0, diameter * 0.5)
        if radius <= self.tol:
            return None

        breps = rg.Brep.CreatePipe(
            crv,
            radius,
            False,
            rg.PipeCapMode.Flat,
            True,
            self.tol,
            self.ang_tol
        )
        if breps and len(breps) > 0:
            return breps[0]
        return None

    # -----------------------------
    # 主流程
    # -----------------------------
    def solve(
        self,
        horizontal_lines,
        rafter_diameter,
        rafter_spacing,
        eave_rafter_length,
        extend_length,
        include_la=True
    ):
        # 输出对象
        rafter_lines_tree = DataTree[object]()
        rafter_solids_tree = DataTree[object]()
        division_pts_tree = DataTree[object]()

        sorted_input_lines = []
        effective_lines = []
        effective_labels = []
        group_label_pairs = []

        # -------- 输入检查 --------
        if horizontal_lines is None or len(horizontal_lines) < 2:
            self._add_log("[ERR] 输入水平直线数量不足，至少需要 2 根。")
            return (
                rafter_lines_tree,
                rafter_solids_tree,
                sorted_input_lines,
                effective_lines,
                effective_labels,
                group_label_pairs,
                division_pts_tree,
                self.log
            )

        linecurves = [self.to_linecurve(x) for x in horizontal_lines]
        sorted_input_lines = self.sort_lines_by_start_z(linecurves)

        self._add_log("[OK] 排序后有效水平线数量 = {}".format(len(sorted_input_lines)))

        if len(sorted_input_lines) < 2:
            self._add_log("[ERR] 可参与排序的有效水平线不足 2 根。")
            return (
                rafter_lines_tree,
                rafter_solids_tree,
                sorted_input_lines,
                effective_lines,
                effective_labels,
                group_label_pairs,
                division_pts_tree,
                self.log
            )

        effective_lines, effective_labels = self.build_effective_lines(sorted_input_lines, include_la)

        if len(effective_lines) < 2:
            self._add_log("[ERR] 剔除 L_a 后，有效水平线不足 2 根。")
            return (
                rafter_lines_tree,
                rafter_solids_tree,
                sorted_input_lines,
                effective_lines,
                effective_labels,
                group_label_pairs,
                division_pts_tree,
                self.log
            )

        self._add_log("[OK] 实际参与计算水平线数量 = {}".format(len(effective_lines)))
        self._add_log("[OK] 逻辑编号 = {}".format(", ".join(effective_labels)))

        # -------- 按相邻层配组 --------
        # 组 0: L_1-L_0
        # 组 1: L_2-L_1
        # ...
        for i in range(len(effective_lines) - 1):
            lower_lc = effective_lines[i]
            upper_lc = effective_lines[i + 1]

            lower_label = effective_labels[i]
            upper_label = effective_labels[i + 1]
            pair_label = "{}-{}".format(upper_label, lower_label)
            group_label_pairs.append(pair_label)

            path = GH_Path(i)
            self._add_log("[OK] 开始处理组 {}。".format(pair_label))

            scalars, axis_origin, axis_u, overlap = self.build_pair_scalars(
                lower_lc, upper_lc, i, rafter_spacing
            )

            if len(scalars) == 0:
                self._add_log("[WARN] 组 {} 未获得可用分点，跳过。".format(pair_label))
                continue

            self._add_log(
                "[OK] 组 {} 重叠区间 = [{:.6f}, {:.6f}]，分点数 = {}。".format(
                    pair_label, overlap[0], overlap[1], len(scalars)
                )
            )

            # 是否是最下组（L_1-L_0）
            is_bottom_pair = (i == 0)

            upper_ext = max(0.0, extend_length)
            lower_ext = max(0.0, eave_rafter_length if is_bottom_pair else extend_length)

            for j, s in enumerate(scalars):
                upper_pt = self.point_on_line_by_scalar(upper_lc, axis_origin, axis_u, s)
                lower_pt = self.point_on_line_by_scalar(lower_lc, axis_origin, axis_u, s)

                if upper_pt is None or lower_pt is None:
                    self._add_log("[WARN] 组 {} 第 {} 根步椽配点失败，已跳过。".format(pair_label, j))
                    continue

                division_pts_tree.Add(upper_pt, path)
                division_pts_tree.Add(lower_pt, path)

                rafter_lc = self.build_rafter_line(
                    upper_pt,
                    lower_pt,
                    upper_ext,
                    lower_ext
                )

                if rafter_lc is None:
                    self._add_log("[WARN] 组 {} 第 {} 根步椽中心线生成失败。".format(pair_label, j))
                    continue

                rafter_lines_tree.Add(rafter_lc, path)

                solid = self.pipe_from_curve(rafter_lc, rafter_diameter)
                if solid is not None:
                    rafter_solids_tree.Add(solid, path)
                else:
                    self._add_log("[WARN] 组 {} 第 {} 根步椽 Pipe 生成失败。".format(pair_label, j))

        self._add_log("[OK] 全部处理完成。")

        return (
            rafter_lines_tree,
            rafter_solids_tree,
            sorted_input_lines,
            effective_lines,
            effective_labels,
            group_label_pairs,
            division_pts_tree,
            self.log
        )

if __name__ == "__main__":
    # ============================================================
    # GhPython 执行入口
    # ============================================================

    def _safe_plane(p):
        if p and isinstance(p, rg.Plane) and p.IsValid:
            return p
        return rg.Plane.WorldXY

    def _safe_bool(x, default=True):
        if x is None:
            return default
        try:
            return bool(x)
        except:
            return default


    # -----------------------------
    # 输入默认值兜底
    # -----------------------------
    if RefPlane is None:
        RefPlane = rg.Plane.WorldXY

    if IncludeLa is None:
        IncludeLa = True

    if RafterDiameter is None:
        RafterDiameter = 0.1

    if RafterSpacing is None:
        RafterSpacing = 0.3

    if EaveRafterLength is None:
        EaveRafterLength = 0.5

    if ExtendLength is None:
        ExtendLength = 0.2


    solver = FrontRafterArranger(ref_plane=_safe_plane(RefPlane))

    (
        RafterLinesTree,
        RafterSolidsTree,
        SortedInputLines,
        EffectiveLines,
        EffectiveLabels,
        GroupLabelPairs,
        DivisionPtsTree,
        Log
    ) = solver.solve(
        HorizontalLines,
        RafterDiameter,
        RafterSpacing,
        EaveRafterLength,
        ExtendLength,
        _safe_bool(IncludeLa, True)
    )
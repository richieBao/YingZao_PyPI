# -*- coding: utf-8 -*-
"""
SongStyle_JuZheLineBuilder
宋代举折法折线构建器（支持 ScaleFactor 比例缩放）

原有输出保持不变：
- JuZheCurves
- JuZhePoints           : DataTree[Point3d]
- JuZhePoints_ProjectOnEaveLine : DataTree[Point3d]  （投影到“原始 EaveHeartLine”高度）
- EaveHeartLine         : 原始橑檐枋心线（由 EaveJump + n*l 确定，位于 Z=O.Z）
- RidgeVerticalLine
- EaveLineKeyPoints

新增（按你的 3 条调整逻辑）：
1) 计算“微调的橑檐枋心”（两侧各一个）：
   - 取“牛脊槫前一举折”的折线段 A 的方向（默认用 pts[1] -> pts[2] 这段的外延方向）
   - 过 pts[1] 沿该方向作延长线
   - 与“原始橑檐枋心（eave_pos/eave_neg）沿参考平面 Z 轴的垂直线”相交
   - 得到新的微调橑檐枋心点（XY 与原 eave_pt 相同，Z 被微调）

2) 过微调的橑檐枋心继续延长，新增输入端：EaveOverhangDist（檐出距离）：
   - 在水平（沿 ±Y）方向从“原 eave_pt（也等价于微调点的垂直投影）”偏移 EaveOverhangDist，
     得到“檐出垂直线”的基点
   - 延长线与该“檐出垂直线”相交处为檐口点（eave_tip）
   - 微调橑檐枋心 -> 檐口点 这段输出为 EaveOverhangLines

3) 因为获得微调橑檐枋心：
   - 输出新增 EaveHeartLine_Adjusted（两侧微调点连线）
   - 输出新增 EaveLineKeyPoints_Adjusted（与原 key_pts 同结构，但 eave_pos/neg 替换为微调点）
   - 输出新增 JuZhePoints_ProjectOnEaveLine_Adjusted（投影到微调 EaveHeartLine_Adjusted 高度）

新增（整体变换）：
4) AlignPlane：先对位整体平移
5) ZOffsetDist：再整体沿 RefPlane.ZAxis 偏移（不受 ScaleFactor 影响；可选叠加 EaveHeartLine_HorizontalDistance）

新增输出修正：
- EaveHeartLine_HorizontalDistance：按你的定义改为：
  “原始橑檐枋心点” 与 “微调橑檐枋心点” 的距离（两侧取平均；若仅一侧有效则取该侧）。
  由于微调点与原点 XY 一致，该距离通常等同于 |Z差|，但这里用 Point3d.DistanceTo 直接计算。

------------------------------------------------------------
输入（GhPython 建议设置）:
    RefPlane : rg.Plane (Item)
    RafterCount : int (Item)
    PurlinSpacing : float (Item)
    EaveJump : float (Item)
    HeightH : float (Item)
    EaveOverhangDist : float (Item)
    ScaleFactor : float (Item)
    ZOffsetDist : float (Item)
    ZOffsetAddEaveHeartLineHDist : bool (Item)
        若为 True：实际 Z 偏移 = ZOffsetDist(不缩放) + EaveHeartLine_HorizontalDistance
        若为 False：实际 Z 偏移 = ZOffsetDist(不缩放)
        默认 False
    AlignPlane : rg.Plane (Item)

输出（GhPython 建议设置）:
    JuZheCurves : list[rg.Curve]
    JuZhePoints : DataTree[rg.Point3d]
    JuZhePoints_ProjectOnEaveLine : DataTree[rg.Point3d]
    EaveHeartLine : rg.Line
    RidgeVerticalLine : rg.Line
    EaveLineKeyPoints : list[rg.Point3d]

    EaveHeartLine_Adjusted : rg.Line
    EaveLineKeyPoints_Adjusted : list[rg.Point3d]
    JuZhePoints_ProjectOnEaveLine_Adjusted : DataTree[rg.Point3d]
    EaveOverhangLines : list[rg.Line]          （[pos, neg]）
    EaveTips : list[rg.Point3d]                （[pos_tip, neg_tip]）
    EaveHearts_Adjusted : list[rg.Point3d]     （[pos_adj, neg_adj]）
    EaveHeartLine_HorizontalDistance : float
        说明见上（已按“橑檐枋心点—微调橑檐枋心点”距离修正）
"""

import Rhino
import Rhino.Geometry as rg
from Rhino.Geometry.Intersect import Intersection

import Grasshopper
from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path


class SongStyle_JuZheLineBuilder(object):

    def __init__(self,
                 ref_plane,
                 rafter_count,
                 purlin_spacing,
                 eave_jump,
                 height_h,
                 eave_overhang_dist=0.0,
                 scale_factor=1.0,
                 z_offset_dist=0.0,
                 align_plane=None,
                 z_offset_add_eave_hdist=False,
                 tol=1e-9):

        self.tol = float(tol)

        self.plane = ref_plane if isinstance(ref_plane, rg.Plane) else rg.Plane.WorldXY
        self.O = self.plane.Origin
        self.Y = rg.Vector3d(self.plane.YAxis)
        self.Z = rg.Vector3d(self.plane.ZAxis)

        try:
            self.sf = float(scale_factor) if scale_factor is not None else 1.0
        except:
            self.sf = 1.0

        try:
            self.rafter_count = int(float(rafter_count)) if rafter_count is not None else 0
        except:
            self.rafter_count = 0

        def _sf_float(v, default=0.0):
            try:
                if v is None:
                    return float(default)
                return float(v)
            except:
                return float(default)

        def _to_bool(v, default=False):
            """尽量把 GhPython 可能传入的 bool/0/1/'true'/'false' 等转为 bool。"""
            if v is None:
                return bool(default)
            if isinstance(v, bool):
                return v
            try:
                if isinstance(v, (int, float)):
                    return bool(int(v))
            except:
                pass
            try:
                s = str(v).strip().lower()
                if s in ("true", "t", "yes", "y", "1", "on"):
                    return True
                if s in ("false", "f", "no", "n", "0", "off", ""):
                    return False
            except:
                pass
            return bool(default)

        self._to_bool = _to_bool

        self.l = _sf_float(purlin_spacing, 0.0) * self.sf
        self.x = _sf_float(eave_jump, 0.0) * self.sf
        self.H = _sf_float(height_h, 0.0) * self.sf

        # 新增：整体沿 RefPlane.ZAxis 的偏移距离（不受 ScaleFactor 影响）
        self.z_offset = _sf_float(z_offset_dist, 0.0)

        # 新增：是否把 EaveHeartLine_HorizontalDistance 叠加到 ZOffsetDist（不缩放）
        self.z_offset_add_eave_hdist = self._to_bool(z_offset_add_eave_hdist, default=False)

        # 新增：定位参考平面（可为 None）
        self.align_plane = align_plane if isinstance(align_plane, rg.Plane) else None

        # 新增：檐出距离（同样受 ScaleFactor 影响）
        self.eave_overhang = _sf_float(eave_overhang_dist, 0.0) * self.sf

        self.n = max(0, self.rafter_count // 2)

    # =====================================================
    # 主入口
    # =====================================================
    def build(self):

        # 兼容原返回（加新增输出时，也保持最前面 6 项不变）
        if self.n <= 0 or abs(self.l) <= self.tol or abs(self.H) <= self.tol:
            empty_tree = DataTree[rg.Point3d]()
            empty_line = rg.Line(self.O, self.O)

            # 新增输出的默认空值
            empty_line2 = rg.Line(self.O, self.O)
            empty_tree2 = DataTree[rg.Point3d]()
            return (
                [],                 # JuZheCurves
                empty_tree,         # JuZhePoints
                empty_tree,         # JuZhePoints_ProjectOnEaveLine
                empty_line,         # EaveHeartLine
                empty_line,         # RidgeVerticalLine
                [],                 # EaveLineKeyPoints
                empty_line2,        # EaveHeartLine_Adjusted
                [],                 # EaveLineKeyPoints_Adjusted
                empty_tree2,        # JuZhePoints_ProjectOnEaveLine_Adjusted
                [],                 # EaveOverhangLines
                [],                 # EaveTips
                [],                 # EaveHearts_Adjusted
                0.0                 # EaveHeartLine_HorizontalDistance
            )

        ridge_pt = self.O + self.Z * self.H
        ridge_line = rg.Line(self.O, ridge_pt)

        half_span = self.x + self.n * self.l

        # 原始橑檐枋心（平面位置）：Z = O.Z
        eave_pos = self.O + self.Y * half_span
        eave_neg = self.O - self.Y * half_span
        eave_line = rg.Line(eave_neg, eave_pos)  # 原始 EaveHeartLine

        colproj_pos = self.O + self.Y * (self.n * self.l)
        colproj_neg = self.O - self.Y * (self.n * self.l)

        key_pts = [self.O, colproj_pos, eave_pos, colproj_neg, eave_neg]

        # -------- 原始半坡折线点（起点是原 eave_pos/eave_neg）--------
        pts_pos = self._build_half(eave_pos, ridge_pt, +1)
        pts_neg = self._build_half(eave_neg, ridge_pt, -1)

        # -------- 微调橑檐枋心 + 檐口点（两侧）--------
        eave_pos_adj, eave_pos_tip, eave_pos_out_line = self._compute_adjusted_eave_and_tip(pts_pos, eave_pos, +1)
        eave_neg_adj, eave_neg_tip, eave_neg_out_line = self._compute_adjusted_eave_and_tip(pts_neg, eave_neg, -1)

        eave_hearts_adj = []
        eave_tips = []
        eave_overhang_lines = []

        if eave_pos_adj is not None:
            eave_hearts_adj.append(rg.Point3d(eave_pos_adj))
        if eave_neg_adj is not None:
            eave_hearts_adj.append(rg.Point3d(eave_neg_adj))

        if eave_pos_tip is not None:
            eave_tips.append(rg.Point3d(eave_pos_tip))
        if eave_neg_tip is not None:
            eave_tips.append(rg.Point3d(eave_neg_tip))

        if eave_pos_out_line is not None:
            eave_overhang_lines.append(eave_pos_out_line)
        if eave_neg_out_line is not None:
            eave_overhang_lines.append(eave_neg_out_line)

        # 用微调点替换半坡起点，得到“调整后的举折折线”
        pts_pos_adj = self._replace_start_point(pts_pos, eave_pos_adj)
        pts_neg_adj = self._replace_start_point(pts_neg, eave_neg_adj)

        # -------- 曲线输出（用调整后的折线更符合你的描述）--------
        curves = []
        if len(pts_pos_adj) >= 2:
            curves.append(rg.PolylineCurve(pts_pos_adj))
        if len(pts_neg_adj) >= 2:
            curves.append(rg.PolylineCurve(pts_neg_adj))

        pts_tree = DataTree[rg.Point3d]()
        pts_tree.AddRange(pts_pos_adj, GH_Path(0))
        pts_tree.AddRange(pts_neg_adj, GH_Path(1))

        # -------- 原投影（到原始 EaveHeartLine）--------
        proj_tree = DataTree[rg.Point3d]()
        proj_tree.AddRange(self._project_points_to_line_by_Z(pts_pos_adj, eave_line), GH_Path(0))
        proj_tree.AddRange(self._project_points_to_line_by_Z(pts_neg_adj, eave_line), GH_Path(1))

        # -------- 新增：微调 EaveHeartLine / KeyPoints / 投影--------
        # 若某侧微调失败，则退回原点，保证不炸组件
        if eave_pos_adj is None:
            eave_pos_adj = rg.Point3d(eave_pos)
        if eave_neg_adj is None:
            eave_neg_adj = rg.Point3d(eave_neg)

        # ✅ 修正：EaveHeartLine_HorizontalDistance 按“檐心点—微调檐心点距离”计算（两侧平均）
        eave_hdist = self._distance_between_eave_hearts(eave_pos, eave_pos_adj, eave_neg, eave_neg_adj)

        eave_line_adj = rg.Line(eave_neg_adj, eave_pos_adj)
        key_pts_adj = [self.O, colproj_pos, rg.Point3d(eave_pos_adj), colproj_neg, rg.Point3d(eave_neg_adj)]

        proj_tree_adj = DataTree[rg.Point3d]()
        proj_tree_adj.AddRange(self._project_points_to_line_by_Z(pts_pos_adj, eave_line_adj), GH_Path(0))
        proj_tree_adj.AddRange(self._project_points_to_line_by_Z(pts_neg_adj, eave_line_adj), GH_Path(1))

        # ---- 执行顺序（按你的要求）：
        # 1) 先对位 AlignPlane（若输入）
        # 2) 再整体沿 RefPlane.ZAxis 偏移 ZOffsetDist（若非 0）

        # ---- 1) 对位 ----
        if self.align_plane is not None:
            source_pt = eave_line_adj.PointAt(0.5)
            target_pt = self._align_target_point_on_eave_line(self.align_plane, eave_line_adj)
            if target_pt is not None:
                move_vec = rg.Vector3d(target_pt - source_pt)
                if not move_vec.IsTiny(self.tol):
                    xform_a = rg.Transform.Translation(move_vec)
                    (
                        curves, pts_tree, proj_tree, eave_line, ridge_line, key_pts,
                        eave_line_adj, key_pts_adj, proj_tree_adj,
                        eave_overhang_lines, eave_tips, eave_hearts_adj
                    ) = self._apply_translation_to_outputs(
                        xform_a,
                        curves, pts_tree, proj_tree, eave_line, ridge_line, key_pts,
                        eave_line_adj, key_pts_adj, proj_tree_adj,
                        eave_overhang_lines, eave_tips, eave_hearts_adj
                    )

        # ---- 2) ZOffset ----
        zoff_eff = float(self.z_offset)
        if self.z_offset_add_eave_hdist:
            zoff_eff += float(eave_hdist)

        if abs(zoff_eff) > self.tol:
            xform_z = rg.Transform.Translation(self.Z * zoff_eff)
            (
                curves, pts_tree, proj_tree, eave_line, ridge_line, key_pts,
                eave_line_adj, key_pts_adj, proj_tree_adj,
                eave_overhang_lines, eave_tips, eave_hearts_adj
            ) = self._apply_translation_to_outputs(
                xform_z,
                curves, pts_tree, proj_tree, eave_line, ridge_line, key_pts,
                eave_line_adj, key_pts_adj, proj_tree_adj,
                eave_overhang_lines, eave_tips, eave_hearts_adj
            )

        return (
            curves,
            pts_tree,
            proj_tree,
            eave_line,
            ridge_line,
            key_pts,
            eave_line_adj,
            key_pts_adj,
            proj_tree_adj,
            eave_overhang_lines,
            eave_tips,
            eave_hearts_adj,
            eave_hdist
        )

    # =====================================================
    # 新增：檐心点距离（两侧平均）
    # =====================================================
    def _distance_between_eave_hearts(self, eave_pos, eave_pos_adj, eave_neg, eave_neg_adj):
        try:
            vals = []
            if eave_pos is not None and eave_pos_adj is not None:
                vals.append(rg.Point3d(eave_pos).DistanceTo(rg.Point3d(eave_pos_adj)))
            if eave_neg is not None and eave_neg_adj is not None:
                vals.append(rg.Point3d(eave_neg).DistanceTo(rg.Point3d(eave_neg_adj)))
            if len(vals) == 0:
                return 0.0
            if len(vals) == 1:
                return float(vals[0])
            return float(sum(vals) / float(len(vals)))
        except:
            return 0.0

    # =====================================================
    # 后处理：整体变换（Z 偏移 / 对位）
    # =====================================================
    def _apply_translation_to_outputs(self, xform, curves, pts_tree, proj_tree, eave_line, ridge_line,
                                      key_pts, eave_line_adj, key_pts_adj, proj_tree_adj,
                                      eave_overhang_lines, eave_tips, eave_hearts_adj):
        """对全部输出进行统一平移（不改变结构、分支）。"""

        curves_t = [self._xform_curve(c, xform) for c in curves] if curves else []

        pts_tree_t = self._xform_datatree_points(pts_tree, xform)
        proj_tree_t = self._xform_datatree_points(proj_tree, xform)
        proj_tree_adj_t = self._xform_datatree_points(proj_tree_adj, xform)

        eave_line_t = self._xform_line(eave_line, xform)
        ridge_line_t = self._xform_line(ridge_line, xform)
        eave_line_adj_t = self._xform_line(eave_line_adj, xform)

        key_pts_t = [self._xform_point(p, xform) for p in key_pts] if key_pts else []
        key_pts_adj_t = [self._xform_point(p, xform) for p in key_pts_adj] if key_pts_adj else []

        eave_overhang_lines_t = [self._xform_line(ln, xform) for ln in eave_overhang_lines] if eave_overhang_lines else []
        eave_tips_t = [self._xform_point(p, xform) for p in eave_tips] if eave_tips else []
        eave_hearts_adj_t = [self._xform_point(p, xform) for p in eave_hearts_adj] if eave_hearts_adj else []

        return (curves_t, pts_tree_t, proj_tree_t, eave_line_t, ridge_line_t, key_pts_t,
                eave_line_adj_t, key_pts_adj_t, proj_tree_adj_t,
                eave_overhang_lines_t, eave_tips_t, eave_hearts_adj_t)

    def _xform_point(self, pt, xform):
        if pt is None:
            return None
        p = rg.Point3d(pt)
        p.Transform(xform)
        return p

    def _xform_line(self, ln, xform):
        if ln is None:
            return None
        l = rg.Line(ln.From, ln.To)
        l.Transform(xform)
        return l

    def _xform_curve(self, crv, xform):
        if crv is None:
            return None
        c = crv.DuplicateCurve()
        c.Transform(xform)
        return c

    def _xform_datatree_points(self, tree, xform):
        dt = DataTree[rg.Point3d]()
        if tree is None:
            return dt
        try:
            for i in range(tree.BranchCount):
                path = tree.Path(i)
                br = tree.Branch(i)
                new_br = []
                for p in br:
                    if p is None:
                        continue
                    pp = rg.Point3d(p)
                    pp.Transform(xform)
                    new_br.append(pp)
                dt.AddRange(new_br, path)
        except:
            return dt
        return dt

    def _align_target_point_on_eave_line(self, align_plane, eave_line_adj):
        """计算对位目标点：AlignPlane 的 Z 轴直线与 EaveHeartLine_Adjusted 的交/最近点。"""
        try:
            ap = align_plane if isinstance(align_plane, rg.Plane) else None
            if ap is None:
                return None
            big = max(1.0, abs(self.H) * 1000.0)
            z = rg.Vector3d(ap.ZAxis)
            if z.IsTiny(self.tol):
                z = rg.Vector3d(0, 0, 1)
            z.Unitize()

            z_line = rg.Line(ap.Origin - z * big, ap.Origin + z * big)
            e_line = rg.Line(eave_line_adj.From - rg.Vector3d(eave_line_adj.Direction) * big,
                             eave_line_adj.To + rg.Vector3d(eave_line_adj.Direction) * big)

            ok, ta, tb = Intersection.LineLine(z_line, e_line, self.tol, False)
            if ok:
                return z_line.PointAt(ta)

            ok2, ta2, tb2 = Intersection.LineLine(z_line, e_line, self.tol, True)
            if ok2:
                return z_line.PointAt(ta2)

            return rg.Point3d(ap.Origin)
        except:
            return None

    # =====================================================
    # 单侧半坡（原逻辑不变）
    # =====================================================
    def _build_half(self, eave_pt, ridge_pt, sign):

        A = rg.Point3d(eave_pt)
        R = rg.Point3d(ridge_pt)

        fold_pts = []
        prev_target = R

        for i in range(1, self.n + 1):

            y_offset = float(i) * self.l
            base_on_v = self.O + self.Y * (sign * y_offset)

            v0 = base_on_v - self.Z * (self.H * 10.0)
            v1 = base_on_v + self.Z * (self.H * 10.0)
            vertical_line = rg.Line(v0, v1)

            slant_line = rg.Line(A, prev_target)

            ok, ta, tb = Intersection.LineLine(
                slant_line,
                vertical_line,
                self.tol,
                False
            )

            if not ok:
                break

            inter_pt = slant_line.PointAt(ta)

            denom = 10.0 * (2.0 ** (i - 1))
            drop = self.H / denom

            fold = inter_pt - self.Z * drop

            fold_pts.append(rg.Point3d(fold))
            prev_target = fold

        pts = [A]
        pts.extend(list(reversed(fold_pts)))
        pts.append(R)
        return pts

    # =====================================================
    # 计算微调橑檐枋心 + 檐口点 + 出檐线段
    # =====================================================
    def _compute_adjusted_eave_and_tip(self, pts_half, eave_plan_pt, sign):
        if pts_half is None or len(pts_half) < 2:
            return None, None, None

        if len(pts_half) >= 3:
            p1 = rg.Point3d(pts_half[1])
            p2 = rg.Point3d(pts_half[2])
        else:
            p1 = rg.Point3d(pts_half[0])
            p2 = rg.Point3d(pts_half[1])

        dir_vec = rg.Vector3d(p1 - p2)  # 从屋面向外（离脊方向）延长
        if dir_vec.IsTiny(self.tol):
            return None, None, None

        d = rg.Vector3d(dir_vec)
        d.Unitize()
        big = max(1.0, abs(self.H) * 1000.0)

        ext0 = p1 - d * big
        ext1 = p1 + d * big
        extend_line = rg.Line(ext0, ext1)

        base_on_v = rg.Point3d(eave_plan_pt)
        v0 = base_on_v - self.Z * big
        v1 = base_on_v + self.Z * big
        vertical_at_eave = rg.Line(v0, v1)

        ok, ta, tb = Intersection.LineLine(extend_line, vertical_at_eave, self.tol, False)
        if not ok:
            return None, None, None

        eave_adj = extend_line.PointAt(ta)

        if abs(self.eave_overhang) <= self.tol:
            return rg.Point3d(eave_adj), rg.Point3d(eave_adj), rg.Line(eave_adj, eave_adj)

        tip_plan = base_on_v + self.Y * (sign * self.eave_overhang)
        tv0 = tip_plan - self.Z * big
        tv1 = tip_plan + self.Z * big
        vertical_at_tip = rg.Line(tv0, tv1)

        ok2, ta2, tb2 = Intersection.LineLine(extend_line, vertical_at_tip, self.tol, False)
        if not ok2:
            return rg.Point3d(eave_adj), None, None

        eave_tip = extend_line.PointAt(ta2)
        out_line = rg.Line(rg.Point3d(eave_adj), rg.Point3d(eave_tip))
        return rg.Point3d(eave_adj), rg.Point3d(eave_tip), out_line

    # =====================================================
    # 用微调点替换起点（不破坏其余举折点）
    # =====================================================
    def _replace_start_point(self, pts, new_start):
        if pts is None:
            return []
        if len(pts) == 0:
            return []
        if new_start is None:
            return [rg.Point3d(p) for p in pts]
        out = [rg.Point3d(new_start)]
        for i in range(1, len(pts)):
            out.append(rg.Point3d(pts[i]))
        return out

    # =====================================================
    # 最终稳定投影版本（跨 Rhino 版本）
    # =====================================================
    def _project_points_to_line_by_Z(self, pts, line):
        out = []
        if pts is None:
            return out

        z_target = line.From.Z

        a = line.From
        b = line.To

        y_dir = rg.Vector3d(b - a)
        if y_dir.IsTiny(self.tol):
            return out
        y_dir.Unitize()

        seg_len = a.DistanceTo(b)

        for p in pts:
            if p is None:
                continue

            P = rg.Point3d(p)
            proj = rg.Point3d(P.X, P.Y, z_target)

            v = rg.Vector3d(proj - a)
            t = v * y_dir

            if t < 0.0:
                proj = rg.Point3d(a.X, a.Y, z_target)
            elif t > seg_len:
                proj = rg.Point3d(b.X, b.Y, z_target)
            else:
                on_seg = a + y_dir * t
                proj = rg.Point3d(on_seg.X, on_seg.Y, z_target)

            out.append(proj)

        return out

if __name__ == '__main__':
    # =====================================================
    # GH 输出绑定区
    # =====================================================

    try:
        _sf = ScaleFactor
    except:
        _sf = 1.0

    try:
        _sf = float(_sf)
    except:
        _sf = 1.0

    try:
        _overhang = EaveOverhangDist
    except:
        _overhang = 0.0

    try:
        _overhang = float(_overhang)
    except:
        _overhang = 0.0

    try:
        _zoff = ZOffsetDist
    except:
        _zoff = 0.0
    try:
        _zoff = float(_zoff)
    except:
        _zoff = 0.0


    try:
        _add_hdist = ZOffsetAddEaveHeartLineHDist
    except:
        _add_hdist = False

    # 兼容 GhPython 可能给的 0/1 或 "true"/"false"
    try:
        if isinstance(_add_hdist, bool):
            _add_hdist = _add_hdist
        elif isinstance(_add_hdist, (int, float)):
            _add_hdist = bool(int(_add_hdist))
        else:
            _s = str(_add_hdist).strip().lower()
            _add_hdist = _s in ("true", "t", "yes", "y", "1", "on")
    except:
        _add_hdist = False
    try:
        _align = AlignPlane
    except:
        _align = None

    _builder = SongStyle_JuZheLineBuilder(
        RefPlane,
        RafterCount,
        PurlinSpacing,
        EaveJump,
        HeightH,
        _overhang,   # 檐出距离（受 ScaleFactor 影响）
        _sf,
        _zoff,       # 新增：整体 Z 偏移（不受 ScaleFactor 影响）
        _align,      # 新增：定位参考平面
        _add_hdist   # 新增：是否叠加 EaveHeartLine_HorizontalDistance 到 ZOffsetDist
    )

    (
        JuZheCurves,
        JuZhePoints,
        JuZhePoints_ProjectOnEaveLine,
        EaveHeartLine,
        RidgeVerticalLine,
        EaveLineKeyPoints,
        EaveHeartLine_Adjusted,
        EaveLineKeyPoints_Adjusted,
        JuZhePoints_ProjectOnEaveLine_Adjusted,
        EaveOverhangLines,
        EaveTips,
        EaveHearts_Adjusted,
        EaveHeartLine_HorizontalDistance
    ) = _builder.build()

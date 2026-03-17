# -*- coding: utf-8 -*-
"""
CaiZhi Support Link Lines
材栔[zhì]支撑点连线：从 CaiZhiPts 里按 Index 取“基准点”，
再按 Direction（向量列表）逐一做“平移复制”得到偏移点 OffsetPts，
并将每个 OffsetPt 与 SupportPts 中“同索引”的点连成线段输出。

------------------------------------------------------------
输入（GhPython 建议设置）:
    Direction : rg.Vector3d (List)
        偏移向量列表（向量长度即偏移距离；不会 Normalize）
        允许输入 GH_Vector / DataTree / 嵌套列表
        Access: List
        TypeHints: Vector3d

    CaiZhiPts : rg.Point3d (List)
        材栔点列表（从中按 Index 提取基准点）
        允许输入 GH_Point / DataTree / 嵌套列表
        Access: List
        TypeHints: Point3d

    Index : int (Item)
        从 CaiZhiPts 中提取点的索引（会自动夹紧）
        Access: Item
        TypeHints: int

    SupportPts : rg.Point3d (List)
        支撑点列表（与 Direction 同索引对应连线）
        允许输入 GH_Point / DataTree / 嵌套列表
        Access: List
        TypeHints: Point3d

输出（GhPython 建议设置）:
    OffsetPts : rg.Point3d (List)
        偏移后的点（数量 = len(Direction) 的有效项）
        Access: List
        TypeHints: Point3d

    LinkLines : rg.Line (List)
        OffsetPts[i] -> SupportPts[i] 的连线（若 SupportPts 为空则为空）
        Access: List
        TypeHints: Line
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg


class CaiZhiSupportLinkLines(object):
    def __init__(self, direction_vecs, caizhi_pts, index, support_pts, tol=1e-9):
        self.tol = tol
        self.direction_vecs = self._to_flat_list(direction_vecs)
        self.caizhi_pts = self._to_flat_list(caizhi_pts)
        self.support_pts = self._to_flat_list(support_pts)
        self.index = self._as_int(index, default=0)

        # 统一“去 Goo + 取 Value + 过滤有效类型”
        self.direction_vecs = self._as_vec_list(self.direction_vecs)
        self.caizhi_pts = self._as_pt_list(self.caizhi_pts)
        self.support_pts = self._as_pt_list(self.support_pts)

    # ---------- public ----------
    def solve(self):
        """
        Returns:
            offset_pts : list[rg.Point3d]
            link_lines : list[rg.Line]
        """
        # 至少要有：基准点列表 + 方向列表
        if not self.caizhi_pts or not self.direction_vecs:
            return [], []

        idx = self._clamp_index(self.index, len(self.caizhi_pts))
        base_pt = self.caizhi_pts[idx]

        offset_pts = []
        for v in self.direction_vecs:
            if not self._is_valid_vec(v):
                continue
            op = rg.Point3d(base_pt)
            op += v  # 延 Direction（包含长度）移动
            offset_pts.append(op)

        # 线段：需要 SupportPts，按索引对应
        link_lines = []
        if self.support_pts:
            n = min(len(offset_pts), len(self.support_pts))
            for i in range(n):
                sp = self.support_pts[i]
                if not self._is_valid_pt(sp):
                    continue
                link_lines.append(rg.Line(offset_pts[i], sp))

        return offset_pts, link_lines

    # ---------- helpers (GH 兼容) ----------
    def _to_flat_list(self, x):
        """把 DataTree / 嵌套 list / 单项 展平成 python list"""
        if x is None:
            return []

        # DataTree -> list（尽量）
        try:
            import ghpythonlib.treehelpers as th
            # tree_to_list 会保留层级；我们再手动展平
            lst = th.tree_to_list(x)
            return self._flatten(lst)
        except:
            pass

        # 本身就是可迭代
        if self._is_iterable(x):
            return self._flatten(x)

        return [x]

    def _flatten(self, seq):
        out = []
        try:
            for it in seq:
                if it is None:
                    continue
                if self._is_iterable(it) and (not isinstance(it, (rg.Point3d, rg.Vector3d))):
                    out.extend(self._flatten(it))
                else:
                    out.append(it)
        except:
            # 不是可迭代就当单项
            out.append(seq)
        return out

    def _is_iterable(self, obj):
        if isinstance(obj, (str, bytes)):
            return False
        try:
            iter(obj)
            return True
        except:
            return False

    def _unwrap_goo(self, obj):
        """GH_Goo 常见有 .Value；否则原样返回"""
        try:
            if hasattr(obj, "Value"):
                return obj.Value
        except:
            pass
        return obj

    def _as_pt_list(self, pts):
        res = []
        for p in pts:
            p = self._unwrap_goo(p)

            # GH_Point 有时是 .Value(Point3d)，上面已 unwrap
            if isinstance(p, rg.Point3d) and self._is_valid_pt(p):
                res.append(p)
                continue

            # 某些情况下进来是 Point3f
            try:
                if hasattr(p, "X") and hasattr(p, "Y") and hasattr(p, "Z"):
                    pp = rg.Point3d(float(p.X), float(p.Y), float(p.Z))
                    if self._is_valid_pt(pp):
                        res.append(pp)
            except:
                pass
        return res

    def _as_vec_list(self, vecs):
        res = []
        for v in vecs:
            v = self._unwrap_goo(v)

            if isinstance(v, rg.Vector3d) and self._is_valid_vec(v):
                res.append(v)
                continue

            # 兼容一些“有 XYZ 属性”的向量对象
            try:
                if hasattr(v, "X") and hasattr(v, "Y") and hasattr(v, "Z"):
                    vv = rg.Vector3d(float(v.X), float(v.Y), float(v.Z))
                    if self._is_valid_vec(vv):
                        res.append(vv)
            except:
                pass
        return res

    def _as_int(self, x, default=0):
        try:
            if x is None:
                return default
            if isinstance(x, bool):
                return int(x)
            if isinstance(x, int):
                return int(x)
            return int(float(x))
        except:
            return default


    def _clamp_index(self, idx, n):
        if n <= 0:
            return 0
        if idx < 0:
            return 0
        if idx > n - 1:
            return n - 1
        return idx

    def _is_valid_pt(self, p):
        try:
            return (
                Rhino.RhinoMath.IsValidDouble(p.X) and
                Rhino.RhinoMath.IsValidDouble(p.Y) and
                Rhino.RhinoMath.IsValidDouble(p.Z)
            )
        except:
            return False

    def _is_valid_vec(self, v):
        try:
            return (
                Rhino.RhinoMath.IsValidDouble(v.X) and
                Rhino.RhinoMath.IsValidDouble(v.Y) and
                Rhino.RhinoMath.IsValidDouble(v.Z)
            )
        except:
            return False

if __name__ == "__main__":
    # ---------------- GH bind ----------------
    Direction = Direction if 'Direction' in globals() else None
    CaiZhiPts = CaiZhiPts if 'CaiZhiPts' in globals() else None
    Index = Index if 'Index' in globals() else 0
    SupportPts = SupportPts if 'SupportPts' in globals() else None

    solver = CaiZhiSupportLinkLines(Direction, CaiZhiPts, Index, SupportPts)
    OffsetPts, LinkLines = solver.solve()

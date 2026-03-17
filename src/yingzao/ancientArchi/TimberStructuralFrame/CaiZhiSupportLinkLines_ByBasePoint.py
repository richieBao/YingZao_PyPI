# -*- coding: utf-8 -*-

"""
模块重定义（基于原 CaiZhiSupportLinkLines.py 改造）：
- 重新命名：类名已更改
- 移除输入端：CaiZhiPts、Index
- 新增输入端：BasePt（一个点），用于直接作为“基准点”，等价替代原 CaiZhiPts[Index]
- 其它逻辑保持不变：
  1) BasePt + Direction[i] => OffsetPts[i]
  2) OffsetPts[i] 与 SupportPts[i] 连线 => LinkLines[i]

GhPython 输入:
    Direction : Vector3d (List)
    BasePt    : Point3d  (Item)
    SupportPts: Point3d  (List)

GhPython 输出:
    OffsetPts : Point3d (List)
    LinkLines : Line    (List)
"""

import Rhino
import Rhino.Geometry as rg


class CaiZhiSupportLinkLines_ByBasePoint(object):
    def __init__(self, direction_vecs, base_pt, support_pts, tol=1e-9):
        self.tol = tol

        # 展平输入（兼容 DataTree / 嵌套列表 / Goo）
        self.direction_vecs = self._as_vec_list(self._to_flat_list(direction_vecs))
        self.support_pts = self._as_pt_list(self._to_flat_list(support_pts))

        # BasePt：取第一个有效点（即便用户给了 list/tree 也兜底）
        self.base_pt = self._as_single_pt(base_pt)

    # ---------- public ----------
    def solve(self):
        """
        Returns:
            offset_pts : list[rg.Point3d]
            link_lines : list[rg.Line]
        """
        if self.base_pt is None or not self.direction_vecs:
            return [], []

        base_pt = self.base_pt

        # 1) OffsetPts = BasePt + Direction[i]
        offset_pts = []
        for v in self.direction_vecs:
            if not self._is_valid_vec(v):
                continue
            op = rg.Point3d(base_pt)
            op += v
            offset_pts.append(op)

        # 2) LinkLines = Line(OffsetPts[i], SupportPts[i])
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

        # 先 unwrap goo（很关键：避免 goo 被当成 iterable 或其它怪类型）
        x = self._unwrap_goo(x)

        # 关键修复：Point/Vector 这类 Rhino 结构体在 IronPython 下可能可迭代，
        # 但我们语义上要把它当“单项”，不能拆成 (x,y,z)
        if isinstance(x, (rg.Point3d, rg.Vector3d, rg.Point3f, rg.Vector3f)):
            return [x]

        # DataTree -> list（尽量）
        try:
            import ghpythonlib.treehelpers as th
            lst = th.tree_to_list(x)
            return self._flatten(lst)
        except:
            pass

        # 可迭代（普通 list/tuple 等）
        if self._is_iterable(x):
            return self._flatten(x)

        return [x]

    def _flatten(self, seq):
        out = []
        try:
            for it in seq:
                if it is None:
                    continue
                it = self._unwrap_goo(it)

                # 同样保护：Point/Vector 不展开
                if isinstance(it, (rg.Point3d, rg.Vector3d, rg.Point3f, rg.Vector3f)):
                    out.append(it)
                    continue

                if self._is_iterable(it):
                    out.extend(self._flatten(it))
                else:
                    out.append(it)
        except:
            out.append(seq)
        return out

    def _is_iterable(self, obj):
        # 字符串不当 iterable
        if isinstance(obj, (str, bytes)):
            return False

        # 关键修复：Rhino 常见几何结构体不当 iterable（避免被拆成数值）
        if isinstance(obj, (rg.Point3d, rg.Vector3d, rg.Point3f, rg.Vector3f,
                            rg.Line, rg.Plane, rg.Transform)):
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

            if isinstance(p, rg.Point3d) and self._is_valid_pt(p):
                res.append(p)
                continue

            # 兼容 Point3f 或其它有 XYZ 属性的点对象
            try:
                if hasattr(p, "X") and hasattr(p, "Y") and hasattr(p, "Z"):
                    pp = rg.Point3d(float(p.X), float(p.Y), float(p.Z))
                    if self._is_valid_pt(pp):
                        res.append(pp)
            except:
                pass
        return res

    def _as_single_pt(self, p):
        """BasePt 取第一个有效点"""
        pts = self._as_pt_list(self._to_flat_list(p))
        return pts[0] if pts else None

    def _as_vec_list(self, vecs):
        res = []
        for v in vecs:
            v = self._unwrap_goo(v)

            if isinstance(v, rg.Vector3d) and self._is_valid_vec(v):
                res.append(v)
                continue

            # 兼容 Vector3f 或其它有 XYZ 属性的向量对象
            try:
                if hasattr(v, "X") and hasattr(v, "Y") and hasattr(v, "Z"):
                    vv = rg.Vector3d(float(v.X), float(v.Y), float(v.Z))
                    if self._is_valid_vec(vv):
                        res.append(vv)
            except:
                pass
        return res

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
    # =========================
    # GhPython 执行区（注意：不要用 __main__）
    # =========================
    solver = CaiZhiSupportLinkLines_ByBasePoint(Direction, BasePt, SupportPts)
    OffsetPts, LinkLines = solver.solve()

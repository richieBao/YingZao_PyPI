# -*- coding: utf-8 -*-
"""
OffsetCopy_BiDirection (沿方向与反方向偏移复制) - 最终版

Tree 规则：
- 输入为列表时：每个输入对象 i -> 一个分支 {i}
    {i}[0] = 正向（+Direction）移动后的对象
    {i}[1] = 反向（-Direction）移动后的对象

向量规则：
- MoveVecList[0] = 正向移动向量
- MoveVecList[1] = 反向移动向量

------------------------------------------------------------
输入（GhPython 建议设置）:
    Geometry : object (List)
        Access: List
        TypeHints: No Type Hint（或 Geometry）

    Direction : rg.Vector3d (Item)
        Access: Item
        TypeHints: Vector3d

    Distance : float (Item)
        Access: Item
        TypeHints: float

输出（GhPython 组件输出端）:
    OffsetTree : DataTree[object]
        Access: Tree

    MoveVecList : list[rg.Vector3d]
        [ 正向移动向量, 反向移动向量 ]

    Log : str
"""

import Rhino
import Rhino.Geometry as rg

try:
    from Grasshopper import DataTree
    from Grasshopper.Kernel.Data import GH_Path
except:
    DataTree = None
    GH_Path = None


class OffsetCopyBiDirection(object):
    """沿指定方向与反方向复制并移动几何（Tree 对齐 + 向量列表输出）。"""

    def __init__(self, direction, distance, tol=1e-12):
        self.tol = tol
        self.dir = self._prepare_direction(direction)
        self.dist = self._prepare_distance(distance)

        self.vec_pos = rg.Vector3d(self.dir)
        if (not self.vec_pos.IsValid) or self.vec_pos.IsZero:
            self.vec_pos = rg.Vector3d(1, 0, 0)
        self.vec_pos.Unitize()
        self.vec_pos *= self.dist

        self.vec_neg = -self.vec_pos

        # 按移动顺序组成列表
        self.vec_list = [self.vec_pos, self.vec_neg]

        self._log_lines = []

    # ---------------- public ----------------
    def build_tree(self, geometries):
        geos = self._as_list(geometries)

        tree = DataTree[object]() if DataTree else None
        if not geos:
            self._log("Geometry is empty.")
            return tree, self.vec_list, self.log

        for i, g in enumerate(geos):
            g_unwrap = self._unwrap_gh(g)
            if g_unwrap is None:
                self._log("Item[%d] unwrap failed." % i)
                continue

            g_pos = self._move_copy_any(g_unwrap, self.vec_pos)  # index 0
            g_neg = self._move_copy_any(g_unwrap, self.vec_neg)  # index 1

            if tree:
                p = GH_Path(i)
                tree.Add(g_pos, p)
                tree.Add(g_neg, p)

        return tree, self.vec_list, self.log

    @property
    def log(self):
        return "\n".join(self._log_lines)

    # ---------------- internals ----------------
    def _log(self, s):
        self._log_lines.append(str(s))

    def _prepare_direction(self, d):
        if isinstance(d, rg.Vector3d):
            v = rg.Vector3d(d)
        else:
            try:
                v = rg.Vector3d(float(d[0]), float(d[1]), float(d[2]))
            except:
                v = rg.Vector3d(1, 0, 0)

        if (not v.IsValid) or v.IsZero:
            v = rg.Vector3d(1, 0, 0)
        return v

    def _prepare_distance(self, x):
        try:
            d = float(x)
        except:
            d = 0.0
        if d < 0:
            d = abs(d)
        return d

    def _as_list(self, x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]

    def _unwrap_gh(self, obj):
        if obj is None:
            return None

        if isinstance(obj, rg.GeometryBase):
            return obj
        if isinstance(obj, (rg.Point3d, rg.Line, rg.Plane)):
            return obj

        try:
            sv = getattr(obj, "ScriptVariable", None)
            if callable(sv):
                v = sv()
                if v is not None:
                    return v
        except:
            pass

        try:
            if hasattr(obj, "Value"):
                v = obj.Value
                if v is not None:
                    return v
        except:
            pass

        return obj

    def _duplicate_if_possible(self, obj):
        if isinstance(obj, rg.GeometryBase):
            return obj.Duplicate()

        if isinstance(obj, rg.Point3d):
            return rg.Point3d(obj)

        if isinstance(obj, rg.Line):
            return rg.Line(obj.From, obj.To)

        if isinstance(obj, rg.Plane):
            return rg.Plane(obj)

        return obj

    def _move_copy_any(self, obj, move_vec):
        dup = self._duplicate_if_possible(obj)
        xform = rg.Transform.Translation(move_vec)

        if isinstance(dup, rg.GeometryBase):
            dup.Transform(xform)
            return dup

        if isinstance(dup, rg.Point3d):
            return dup + move_vec

        if isinstance(dup, rg.Line):
            return rg.Line(dup.From + move_vec, dup.To + move_vec)

        if isinstance(dup, rg.Plane):
            p = rg.Plane(dup)
            p.Origin = p.Origin + move_vec
            return p

        return dup

if __name__ == "__main__":
    # ---------------- GH 组件主体 ----------------
    builder = OffsetCopyBiDirection(Direction, Distance)
    OffsetTree, MoveVecList, Log = builder.build_tree(Geometry)

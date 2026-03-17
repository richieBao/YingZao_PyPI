# -*- coding: utf-8 -*-
"""
3点生成唯一矩形面
稳定版：无输入时不报错，不变红
"""

import Rhino
import Rhino.Geometry as rg


class UniqueRectangleFrom3Pts(object):

    def __init__(self, pts, tol=1e-9):
        self.tol = tol
        self.pts = self._prepare_points(pts)
        self.A = None
        self.B = None
        self.C = None
        self.A2 = None
        self.B2 = None

    # ---------- 公共主方法 ----------
    def build(self):
        """
        返回:
            face  : Brep or None
            ab_line : Line or None
        """

        # 输入不足3点 → 直接返回None
        if len(self.pts) != 3:
            return None, None

        if not self._identify_AB_C():
            return None, None

        if not self._compute_bottom():
            return None, None

        face = self._create_face()
        if face is None:
            return None, None

        ab_line = rg.Line(self.A, self.B)
        return face, ab_line

    # ---------- 内部方法 ----------

    def _prepare_points(self, pts):
        pts = self._as_list(pts)
        result = []
        for p in pts:
            pt = self._to_point3d(p)
            if pt:
                result.append(pt)
        return result

    def _identify_AB_C(self):
        """
        找最长边作为 AB
        并保证 A/B 顺序稳定（字典序）
        """

        p0, p1, p2 = self.pts

        pairs = [
            (p0, p1, self._dist2(p0, p1)),
            (p0, p2, self._dist2(p0, p2)),
            (p1, p2, self._dist2(p1, p2))
        ]

        pairs.sort(key=lambda x: x[2], reverse=True)

        A, B, dist2 = pairs[0]

        if dist2 <= self.tol:
            return False

        # 找C
        for p in self.pts:
            if p != A and p != B:
                C = p
                break

        # 唯一性排序
        if self._lexi_key(A) > self._lexi_key(B):
            A, B = B, A

        self.A = A
        self.B = B
        self.C = C

        return True

    def _compute_bottom(self):

        top_line = rg.Line(self.A, self.B)
        if top_line.Length <= self.tol:
            return False

        t = top_line.ClosestParameter(self.C)
        D = top_line.PointAt(t)

        v = self.C - D
        if v.Length <= self.tol:
            return False

        self.A2 = self.A + v
        self.B2 = self.B + v

        return True

    def _create_face(self):

        pl = rg.Polyline([
            self.A,
            self.B,
            self.B2,
            self.C,
            self.A2,
            self.A
        ])

        crv = rg.PolylineCurve(pl)

        breps = rg.Brep.CreatePlanarBreps(crv, 1e-6)

        if not breps or len(breps) == 0:
            return None

        return breps[0]

    # ---------- 工具函数 ----------

    def _as_list(self, x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]

    def _to_point3d(self, p):
        if isinstance(p, rg.Point3d):
            return p
        if isinstance(p, rg.Point):
            return p.Location
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            return rg.Point3d(float(p[0]), float(p[1]), float(p[2]))
        try:
            return rg.Point3d(p.X, p.Y, p.Z)
        except:
            return None

    def _dist2(self, p, q):
        v = q - p
        return v.X*v.X + v.Y*v.Y + v.Z*v.Z

    def _lexi_key(self, pt):
        return (pt.X, pt.Y, pt.Z)

if __name__ == '__main__':
    # =========================
    # GH 调用（外层再加保险）
    # =========================

    Face = None
    AB = None

    if Pts:
        try:
            builder = UniqueRectangleFrom3Pts(Pts)
            Face, AB = builder.build()
        except:
            Face = None
            AB = None

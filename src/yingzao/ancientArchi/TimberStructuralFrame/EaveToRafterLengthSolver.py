# -*- coding: utf-8 -*-
"""
EaveToRafterLengthSolver.py
由出檐長计算椽長（GhPython 组件）

功能说明：
    已知：
        1) 下平槫点 A
        2) 檫檐枋点 B
        3) 出檐長距离 EaveLength
        4) 参考平面 RefPlane（可为空，默认 WorldXY）

    计算逻辑：
        1. 连接 A、B，得直线段 A-B；
        2. 从点 B 沿参考平面的 X / Y 轴方向平移，构造候选点 C；
        3. 要求：点 C 沿参考平面 Z 轴方向的投影线，需与 A-B 的延长线相交，
           相交点记为 C'；
        4. 计算 B 到 C' 的距离，作为椽長；
        5. 输出点 C、C'，折线 A-B-C'，线段 B-C、C-C' 等。

------------------------------------------------------------
输入（GhPython 建议设置）:
    A : rg.Point3d
        Access = Item
        TypeHint = Point3d
        下平槫点 A。

    B : rg.Point3d
        Access = Item
        TypeHint = Point3d
        檫檐枋点 B。

    EaveLength : float
        Access = Item
        TypeHint = float
        出檐長距离，即 B 到 C 的水平移动长度。

    RefPlane : rg.Plane
        Access = Item
        TypeHint = Plane
        参考平面。可为空；
        若为空，默认使用 WorldXY。
        计算中使用其 XAxis / YAxis / ZAxis。

输出（GhPython 建议设置）:
    C : rg.Point3d
        自动判断得到的点 C。

    CPrime : rg.Point3d
        点 C 沿 RefPlane.ZAxis 方向投影到 A-B 延长线所得交点 C'。

    RafterLength : float
        点 B 到点 C' 的距离，即椽長。

    ABLine : rg.Line
        直线段 A-B。

    ABExtendedToCPrime : rg.PolylineCurve
        折线 A-B-C'。

    BCLine : rg.Line
        直线段 B-C。

    CCPrimeLine : rg.Line
        直线段 C-C'。

    ChosenAxisName : str
        自动判断选中的移动方向名称：
        "+X", "-X", "+Y", "-Y"

    Log : list[str]
        过程日志，便于调试。
------------------------------------------------------------
"""

import Rhino.Geometry as rg
import scriptcontext as sc


class EaveToRafterLengthSolver(object):
    """
    由出檐長计算椽長
    """

    def __init__(self, A, B, eave_length, ref_plane=None, tol=None):
        self.A = A
        self.B = B
        self.eave_length = float(eave_length) if eave_length is not None else 0.0
        self.ref_plane = self._build_base_plane(ref_plane, A)
        self.tol = tol if tol is not None else sc.doc.ModelAbsoluteTolerance
        self.log = []

    # ------------------------------------------------------------------
    # 基础方法
    # ------------------------------------------------------------------
    def _build_base_plane(self, ref_plane, origin_point):
        """
        构造实际计算平面：
        - 若输入为空，默认 WorldXY
        - 原点重设到 A（仅为了便于理解和后续扩展；轴方向保持输入平面方向）
        """
        if ref_plane is None:
            p = rg.Plane.WorldXY
            p.Origin = origin_point
            return p

        p = rg.Plane(ref_plane)
        p.Origin = origin_point
        return p

    def _point_along_vector(self, pt, vec, dist):
        v = rg.Vector3d(vec)
        if not v.Unitize():
            raise ValueError("输入向量无法单位化。")
        return pt + v * dist

    def _make_vertical_line_through_point(self, pt):
        """
        过点 pt，沿 RefPlane.ZAxis 构造一条足够长的直线（有限线段形式）。
        """
        z = rg.Vector3d(self.ref_plane.ZAxis)
        if not z.Unitize():
            raise ValueError("参考平面的 Z 轴无效。")

        span = max(1000.0, abs(self.eave_length) * 20.0, self.A.DistanceTo(self.B) * 20.0)
        p0 = pt - z * span
        p1 = pt + z * span
        return rg.Line(p0, p1)

    def _intersect_vertical_with_ab_extension(self, C_candidate):
        """
        求：
            过 C_candidate 的 RefPlane.ZAxis 方向直线
            与 A-B 延长线
        是否相交。

        返回：
            success, CPrime, distance_error, t_ab, t_vertical
        说明：
            - CPrime 为交点（若成功）
            - distance_error 为两线最近距离
            - t_ab / t_vertical 为对应参数
        """
        ab_line = rg.Line(self.A, self.B)
        vertical_line = self._make_vertical_line_through_point(C_candidate)

        success, t_ab, t_v = rg.Intersect.Intersection.LineLine(
            ab_line, vertical_line, self.tol, False
        )

        if not success:
            # 再用最近点距离兜底
            success2, ta, tv = rg.Intersect.Intersection.LineLine(
                ab_line, vertical_line
            )
            if not success2:
                return False, None, float("inf"), None, None
            p_ab = ab_line.PointAt(ta)
            p_v = vertical_line.PointAt(tv)
            dist_err = p_ab.DistanceTo(p_v)
            if dist_err <= self.tol:
                return True, p_ab, dist_err, ta, tv
            return False, None, dist_err, ta, tv

        p_ab = ab_line.PointAt(t_ab)
        p_v = vertical_line.PointAt(t_v)
        dist_err = p_ab.DistanceTo(p_v)

        if dist_err <= self.tol:
            return True, p_ab, dist_err, t_ab, t_v

        return False, None, dist_err, t_ab, t_v

    def _build_candidates(self):
        """
        构造候选 C 点。
        为增强鲁棒性，这里同时测试：
            +X, -X, +Y, -Y
        最终优先选择真正满足相交条件的解。
        """
        x = self.ref_plane.XAxis
        y = self.ref_plane.YAxis

        return [
            ("+X", self._point_along_vector(self.B, x, self.eave_length)),
            ("-X", self._point_along_vector(self.B, x, -self.eave_length)),
            ("+Y", self._point_along_vector(self.B, y, self.eave_length)),
            ("-Y", self._point_along_vector(self.B, y, -self.eave_length)),
        ]

    # ------------------------------------------------------------------
    # 主求解
    # ------------------------------------------------------------------
    def solve(self):
        result = {
            "C": None,
            "CPrime": None,
            "RafterLength": None,
            "ABLine": None,
            "ABExtendedToCPrime": None,
            "BCLine": None,
            "CCPrimeLine": None,
            "ChosenAxisName": None,
            "Log": self.log
        }

        # ---- 输入检查 ----
        if self.A is None or self.B is None:
            self.log.append("[ERR] 输入点 A 或 B 为空。")
            return result

        if self.eave_length <= 0:
            self.log.append("[ERR] 出檐長距离 EaveLength 必须大于 0。")
            return result

        if self.A.DistanceTo(self.B) <= self.tol:
            self.log.append("[ERR] 点 A 与点 B 重合或过近，无法构造 A-B。")
            return result

        ab_line = rg.Line(self.A, self.B)
        result["ABLine"] = ab_line
        self.log.append("[OK] 已建立直线段 A-B。")

        # ---- 测试候选 C ----
        candidates = self._build_candidates()
        valid_solutions = []
        fallback_solutions = []

        for axis_name, c_pt in candidates:
            ok, c_prime, err, t_ab, t_v = self._intersect_vertical_with_ab_extension(c_pt)

            if ok and c_prime is not None:
                # 加一个偏好：C' 尽量位于 B 之后的 A-B 延长方向上
                # A->B 为参数 0~1，B 之后通常 t_ab >= 1
                score = 0
                if t_ab is not None:
                    if t_ab >= 1.0 - self.tol:
                        score -= 1000.0  # 强烈偏好 B 之后的延长线
                    score += abs(t_ab - 1.0)

                valid_solutions.append({
                    "axis_name": axis_name,
                    "C": c_pt,
                    "CPrime": c_prime,
                    "err": err,
                    "t_ab": t_ab,
                    "t_v": t_v,
                    "score": score
                })
                self.log.append(
                    "[OK] 候选 {0} 可行：找到 C'，误差={1:.6g}, t_ab={2}".format(
                        axis_name, err, t_ab
                    )
                )
            else:
                fallback_solutions.append({
                    "axis_name": axis_name,
                    "C": c_pt,
                    "err": err
                })
                self.log.append(
                    "[--] 候选 {0} 不可行：垂线与 A-B 延长线未有效相交，误差={1:.6g}".format(
                        axis_name, err
                    )
                )

        if not valid_solutions:
            self.log.append("[ERR] 未找到满足条件的 C 点；请检查 RefPlane、A/B 位置关系，或输入的出檐長。")
            return result

        # 优先选 score 最小者，再按误差最小
        valid_solutions.sort(key=lambda x: (x["score"], x["err"]))
        best = valid_solutions[0]

        C = best["C"]
        CPrime = best["CPrime"]
        chosen_axis_name = best["axis_name"]

        # ---- 构造输出几何 ----
        bc_line = rg.Line(self.B, C)
        ccprime_line = rg.Line(C, CPrime)

        # 折线 A-B-C'
        poly = rg.Polyline([self.A, self.B, CPrime])
        ab_extended_to_cprime = poly.ToPolylineCurve()

        rafter_length = self.B.DistanceTo(CPrime)

        result["C"] = C
        result["CPrime"] = CPrime
        result["RafterLength"] = rafter_length
        result["BCLine"] = bc_line
        result["CCPrimeLine"] = ccprime_line
        result["ABExtendedToCPrime"] = ab_extended_to_cprime
        result["ChosenAxisName"] = chosen_axis_name

        self.log.append("[OK] 已选定移动方向：{0}".format(chosen_axis_name))
        self.log.append("[OK] 已构造点 C、点 C'。")
        self.log.append("[OK] 已构造折线 A-B-C'、线段 B-C、线段 C-C'。")
        self.log.append("[OK] 椽長 RafterLength = B-C' = {0:.6f}".format(rafter_length))

        return result

if __name__ == "__main__":
    # ==============================================================================
    # GhPython 运行入口
    # ==============================================================================

    solver = EaveToRafterLengthSolver(A, B, EaveLength, RefPlane)
    _res = solver.solve()

    C = _res["C"]
    CPrime = _res["CPrime"]
    RafterLength = _res["RafterLength"]
    ABLine = _res["ABLine"]
    ABExtendedToCPrime = _res["ABExtendedToCPrime"]
    BCLine = _res["BCLine"]
    CCPrimeLine = _res["CCPrimeLine"]
    ChosenAxisName = _res["ChosenAxisName"]
    Log = _res["Log"]
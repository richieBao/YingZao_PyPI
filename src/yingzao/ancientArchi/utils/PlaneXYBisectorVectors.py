# -*- coding: utf-8 -*-
"""
PlaneXYBisectorVectors
给定参考平面，计算其 X/Y 轴“中心夹角”的单位向量（角平分线），并输出其反向向量；
同时输出参考平面的 X/Y/Z 轴（单位向量）。

支持“自定义 X/Y 轴向量”覆盖：
- 如果 CustomXAxis 与 CustomYAxis 都有效（非零向量），则不使用 RefPlane 的轴，
  而是使用这两个向量【原样 unitize 后】计算角平分线；
  注意：不会对 CustomYAxis 做正交化/重建（否则会改变夹角）。

------------------------------------------------------------
输入（GhPython 建议设置）:
    RefPlane : rg.Plane (Item)
        参考平面（提供 X/Y/Z 轴）
        Access: Item
        TypeHints: Plane

    CustomXAxis : rg.Vector3d (Item)
        可选，自定义 X 轴向量（若与 CustomYAxis 都有效，则覆盖 RefPlane）
        Access: Item
        TypeHints: Vector3d（建议在 GH 端勾 Optional；或 TypeHint 用 Vector/NoHint）

    CustomYAxis : rg.Vector3d (Item)
        可选，自定义 Y 轴向量（若与 CustomXAxis 都有效，则覆盖 RefPlane）
        Access: Item
        TypeHints: Vector3d（建议在 GH 端勾 Optional；或 TypeHint 用 Vector/NoHint）

输出（GhPython 组件输出端）:
    Bisector_U      : rg.Vector3d (Item)
        X/Y 的单位角平分线向量（内角：unit(X)+unit(Y)）
    Bisector_U_Neg  : rg.Vector3d (Item)
        Bisector_U 的反向单位向量
    XAxis_U         : rg.Vector3d (Item)
        使用的 X 轴单位向量（来自 RefPlane 或 CustomXAxis）
    YAxis_U         : rg.Vector3d (Item)
        使用的 Y 轴单位向量（来自 RefPlane 或 CustomYAxis）
    ZAxis_U         : rg.Vector3d (Item)
        使用的 Z 轴单位向量（RefPlane.ZAxis 或 unit(X×Y)）
------------------------------------------------------------
"""

import Rhino
import Rhino.Geometry as rg


class PlaneXYBisectorVectors(object):
    """封装：从 Plane 或自定义 X/Y 轴计算角平分线与 XYZ 输出"""

    def __init__(self, ref_plane=None, custom_x=None, custom_y=None, tol=1e-12):
        self.tol = float(tol)

        self.ref_plane = ref_plane if isinstance(ref_plane, rg.Plane) else rg.Plane.WorldXY

        # 允许 GH 端传 None / Unset / 其它类型：这里不强制
        self.custom_x = custom_x
        self.custom_y = custom_y

        # 结果
        self.x_u = rg.Vector3d.Unset
        self.y_u = rg.Vector3d.Unset
        self.z_u = rg.Vector3d.Unset
        self.bis_u = rg.Vector3d.Unset
        self.bis_u_neg = rg.Vector3d.Unset

    # ---------------- public ----------------
    def build(self):
        self._pick_axes()
        self._compute_bisector()
        return self.bis_u, self.bis_u_neg, self.x_u, self.y_u, self.z_u

    # ---------------- internal helpers ----------------
    def _coerce_vec3d(self, v):
        """尽量把 GH 输入转成 Vector3d；失败返回 Unset"""
        if v is None:
            return rg.Vector3d.Unset
        if isinstance(v, rg.Vector3d):
            return rg.Vector3d(v)
        # GH 里有时是 Vector3f 或者可迭代
        try:
            return rg.Vector3d(v)
        except:
            return rg.Vector3d.Unset

    def _is_valid_vec(self, v):
        if not isinstance(v, rg.Vector3d):
            return False
        if (not v.IsValid) or v.IsTiny(self.tol):
            return False
        return True

    def _unitize_copy(self, v):
        vv = rg.Vector3d(v)
        if vv.IsTiny(self.tol):
            return rg.Vector3d.Unset
        vv.Unitize()
        return vv

    def _pick_axes(self):
        """决定使用 RefPlane 轴还是 CustomX/Y（Custom 模式不改变夹角）"""
        cx = self._coerce_vec3d(self.custom_x)
        cy = self._coerce_vec3d(self.custom_y)
        use_custom = self._is_valid_vec(cx) and self._is_valid_vec(cy)

        if use_custom:
            # 关键：不做正交化，不重建 Y；只做 unitize
            x = self._unitize_copy(cx)
            y = self._unitize_copy(cy)

            # Z 用 X×Y（仅输出/退化判断）
            z = rg.Vector3d.CrossProduct(x, y)

            if z.IsTiny(self.tol):
                # X 与 Y 近似平行：Z 无法由叉积得到，退化用世界 Z
                z = rg.Vector3d(0, 0, 1)
            z.Unitize()

            self.x_u, self.y_u, self.z_u = x, y, z
        else:
            # 使用 plane 轴（确保单位化）
            x = self._unitize_copy(self.ref_plane.XAxis)
            y = self._unitize_copy(self.ref_plane.YAxis)
            z = self._unitize_copy(self.ref_plane.ZAxis)

            # 保险：如果 plane 轴异常则回退 WorldXY
            if (not self._is_valid_vec(x)) or (not self._is_valid_vec(y)) or (not self._is_valid_vec(z)):
                p = rg.Plane.WorldXY
                x = self._unitize_copy(p.XAxis)
                y = self._unitize_copy(p.YAxis)
                z = self._unitize_copy(p.ZAxis)

            self.x_u, self.y_u, self.z_u = x, y, z

    def _compute_bisector(self):
        """计算 X/Y 的角平分线单位向量与其反向"""
        # 内角平分线：unit(X)+unit(Y)
        s = rg.Vector3d(self.x_u + self.y_u)

        if s.IsTiny(self.tol):
            # X 与 Y 近似反向：用在“XY 平面”内、与 X 垂直的方向作为稳定退化解
            # 取 Cross(Z, X) 可以保证落在 XY 平面（相对 Z）
            s = rg.Vector3d.CrossProduct(self.z_u, self.x_u)
            if s.IsTiny(self.tol):
                s = rg.Vector3d(1, 0, 0)

        s.Unitize()
        self.bis_u = s
        self.bis_u_neg = rg.Vector3d(-s.X, -s.Y, -s.Z)


if __name__ == '__main__':
    # ---------------- GH Python entry ----------------
    # 期望输入变量名：
    #   RefPlane, CustomXAxis, CustomYAxis
    # 期望输出变量名：
    #   Bisector_U, Bisector_U_Neg, XAxis_U, YAxis_U, ZAxis_U

    try:
        builder = PlaneXYBisectorVectors(RefPlane, CustomXAxis, CustomYAxis)
        Bisector_U, Bisector_U_Neg, XAxis_U, YAxis_U, ZAxis_U = builder.build()
    except Exception:
        # 避免 GH 组件变红：回退到 WorldXY 的稳定输出
        p = rg.Plane.WorldXY
        XAxis_U = rg.Vector3d(p.XAxis); XAxis_U.Unitize()
        YAxis_U = rg.Vector3d(p.YAxis); YAxis_U.Unitize()
        ZAxis_U = rg.Vector3d(p.ZAxis); ZAxis_U.Unitize()
        Bisector_U = rg.Vector3d(XAxis_U + YAxis_U)
        if not Bisector_U.IsTiny(1e-12):
            Bisector_U.Unitize()
        else:
            Bisector_U = rg.Vector3d(1, 0, 0)
        Bisector_U_Neg = rg.Vector3d(-Bisector_U.X, -Bisector_U.Y, -Bisector_U.Z)

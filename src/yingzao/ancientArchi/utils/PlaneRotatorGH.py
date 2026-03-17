# -*- coding: utf-8 -*-
import Rhino.Geometry as rg

"""
FT_PlaneRotator_GH

以输入点为原点，以 GH 的参考平面(RefPlane)为基准，通过绕平面自身的 X/Y/Z 轴旋转（弧度）
+ 轴翻转（FlipX/Y/Z）生成最终参考平面，并输出从 RefPlane → Plane 的变换 Transform。

说明：
- 默认 RefPlane 为 GH 的 XY Plane（XAxis=(1,0,0), YAxis=(0,1,0), ZAxis=(0,0,1)）。
- 旋转顺序固定为：Rx(about X) → Ry(about Y) → Rz(about Z)，均为“平面自身轴”(局部轴)旋转。
- Transform 输出为：把 RefPlane 坐标系中的几何，直接变换到最终 Plane 坐标系。

------------------------------------------------------------
输入（GhPython 建议设置）:
    Origin : rg.Point3d
        Access: item
        TypeHint: Point3d
        平面原点（必填）。

    RefPlane : rg.Plane
        Access: item
        TypeHint: Plane
        参考平面（默认 GH XY Plane）。

    RotX : float
        Access: item
        TypeHint: float
        绕 RefPlane.XAxis 旋转角（弧度）。默认 0.0

    RotY : float
        Access: item
        TypeHint: float
        绕 RefPlane.YAxis 旋转角（弧度）。默认 0.0

    RotZ : float
        Access: item
        TypeHint: float
        绕 RefPlane.ZAxis 旋转角（弧度）。默认 0.0

    FlipX : bool
        Access: item
        TypeHint: bool
        翻转最终平面 X 轴（相当于关于 YZ 镜像），默认 False。

    FlipY : bool
        Access: item
        TypeHint: bool
        翻转最终平面 Y 轴（相当于关于 XZ 镜像），默认 False。

    FlipZ : bool
        Access: item
        TypeHint: bool
        翻转最终平面 Z 轴（相当于关于 XY 镜像），默认 False。

输出:
    Plane : rg.Plane
        Access: item
        TypeHint: Plane
        最终参考平面。

    XAxis : rg.Vector3d
        Access: item
        TypeHint: Vector3d
        Plane 的 XAxis（单位向量）。

    YAxis : rg.Vector3d
        Access: item
        TypeHint: Vector3d
        Plane 的 YAxis（单位向量）。

    ZAxis : rg.Vector3d
        Access: item
        TypeHint: Vector3d
        Plane 的 ZAxis（单位向量）。

    Transform : rg.Transform
        Access: item
        TypeHint: Transform
        从 RefPlane → Plane 的变换（PlaneToPlane）。

    Log : str
        Access: item
        TypeHint: str
------------------------------------------------------------
"""


class PlaneRotatorGH(object):
    EPS = 1e-12

    @staticmethod
    def gh_xy_plane(origin=None):
        """GH XY Plane 模板（原点可替换）。"""
        if origin is None:
            origin = rg.Point3d(0, 0, 0)
        return rg.Plane(origin, rg.Vector3d(1, 0, 0), rg.Vector3d(0, 1, 0))

    @staticmethod
    def _safe_float(x, default=0.0):
        try:
            if x is None:
                return float(default)
            return float(x)
        except:
            return float(default)

    @staticmethod
    def _safe_bool(x, default=False):
        try:
            if x is None:
                return bool(default)
            return bool(x)
        except:
            return bool(default)

    @staticmethod
    def _unit(v, fallback):
        """单位化；失败则用 fallback（并单位化）。"""
        vv = rg.Vector3d(v)
        if vv.IsValid and vv.Length > PlaneRotatorGH.EPS and vv.Unitize():
            return vv
        ff = rg.Vector3d(fallback)
        ff.Unitize()
        return ff

    @staticmethod
    def _apply_flip_on_plane_axes(pl, flip_x, flip_y, flip_z, log):
        x = rg.Vector3d(pl.XAxis)
        y = rg.Vector3d(pl.YAxis)
        z = rg.Vector3d(pl.ZAxis)

        if flip_x:
            x *= -1; log.append("[FLIP] FlipX")
        if flip_y:
            y *= -1; log.append("[FLIP] FlipY")
        if flip_z:
            z *= -1; log.append("[FLIP] FlipZ")

        # 单位化与重建：按“被翻转的轴”优先保留
        def unit(v, fb):
            vv = rg.Vector3d(v)
            if vv.IsValid and vv.Length > PlaneRotatorGH.EPS and vv.Unitize():
                return vv
            ff = rg.Vector3d(fb); ff.Unitize()
            return ff

        # 情况1：翻转了 Y（以 Y+Z 重建 X）
        if flip_y and not flip_x:
            z = unit(z, rg.Vector3d(0,0,1))
            y = y - rg.Vector3d.Multiply(rg.Vector3d.Multiply(y, z), z)  # y ⟂ z
            y = unit(y, rg.Vector3d(0,1,0))
            x = rg.Vector3d.CrossProduct(y, z)  # 右手：Y×Z=X
            x = unit(x, rg.Vector3d(1,0,0))
            # 再修正：Y = Z×X
            y = rg.Vector3d.CrossProduct(z, x)
            y = unit(y, rg.Vector3d(0,1,0))
            return rg.Plane(pl.Origin, x, y)

        # 默认：以 X+Z 重建 Y（FlipX / FlipZ 或无 FlipY）
        z = unit(z, rg.Vector3d(0,0,1))
        x = x - rg.Vector3d.Multiply(rg.Vector3d.Multiply(x, z), z)      # x ⟂ z
        x = unit(x, rg.Vector3d(1,0,0))
        y = rg.Vector3d.CrossProduct(z, x)  # 右手：Z×X=Y
        y = unit(y, rg.Vector3d(0,1,0))
        x = rg.Vector3d.CrossProduct(y, z)  # 修正
        x = unit(x, rg.Vector3d(1,0,0))
        return rg.Plane(pl.Origin, x, y)


    @staticmethod
    def build(origin, ref_plane=None,
              rot_x=0.0, rot_y=0.0, rot_z=0.0,
              flip_x=False, flip_y=False, flip_z=False):
        """
        返回: (plane, xAxis, yAxis, zAxis, xform, log_str)
        xform = PlaneToPlane(ref_plane, plane)
        """
        log = []

        # Origin
        if origin is None:
            origin = rg.Point3d(0, 0, 0)
            log.append("[INPUT] Origin None -> (0,0,0)")

        # RefPlane：默认 GH XY，并强制原点跟随 Origin
        if ref_plane is None or (isinstance(ref_plane, rg.Plane) and not ref_plane.IsValid):
            ref_plane = PlaneRotatorGH.gh_xy_plane(origin)
            log.append("[INPUT] RefPlane None/invalid -> GH XY Plane")
        else:
            ref_plane = rg.Plane(ref_plane)
            ref_plane.Origin = origin
            log.append("[INPUT] RefPlane valid; origin overridden by Origin input")

        # angles (radians)
        ax = PlaneRotatorGH._safe_float(rot_x, 0.0)
        ay = PlaneRotatorGH._safe_float(rot_y, 0.0)
        az = PlaneRotatorGH._safe_float(rot_z, 0.0)

        # flips
        fx = PlaneRotatorGH._safe_bool(flip_x, False)
        fy = PlaneRotatorGH._safe_bool(flip_y, False)
        fz = PlaneRotatorGH._safe_bool(flip_z, False)

        # 从 RefPlane 拷贝出工作平面
        pl = rg.Plane(ref_plane)

        # 关键：绕“平面自身轴”（局部轴）旋转，轴通过平面原点
        # 顺序：Rx -> Ry -> Rz
        if abs(ax) > PlaneRotatorGH.EPS:
            t = rg.Transform.Rotation(ax, pl.XAxis, pl.Origin)
            pl.Transform(t)
            log.append("[ROT] Rx about XAxis = {:.6f} rad".format(ax))

        if abs(ay) > PlaneRotatorGH.EPS:
            t = rg.Transform.Rotation(ay, pl.YAxis, pl.Origin)
            pl.Transform(t)
            log.append("[ROT] Ry about YAxis = {:.6f} rad".format(ay))

        if abs(az) > PlaneRotatorGH.EPS:
            t = rg.Transform.Rotation(az, pl.ZAxis, pl.Origin)
            pl.Transform(t)
            log.append("[ROT] Rz about ZAxis = {:.6f} rad".format(az))

        # Flip（对最终平面轴处理）
        if fx or fy or fz:
            pl = PlaneRotatorGH._apply_flip_on_plane_axes(pl, fx, fy, fz, log)

        # 输出轴单位化
        xo = rg.Vector3d(pl.XAxis); xo.Unitize()
        yo = rg.Vector3d(pl.YAxis); yo.Unitize()
        zo = rg.Vector3d(pl.ZAxis); zo.Unitize()

        # Transform：从 RefPlane 到最终 Plane
        xform = rg.Transform.PlaneToPlane(ref_plane, pl)

        return pl, xo, yo, zo, xform, "\n".join(log)

if __name__ == "__main__":
    # =========================================================
    # GhPython 组件入口
    # =========================================================
    Plane, XAxis, YAxis, ZAxis, Transform, Log = PlaneRotatorGH.build(
        origin=Origin,
        ref_plane=RefPlane,
        rot_x=RotX,
        rot_y=RotY,
        rot_z=RotZ,
        flip_x=FlipX,
        flip_y=FlipY,
        flip_z=FlipZ
    )

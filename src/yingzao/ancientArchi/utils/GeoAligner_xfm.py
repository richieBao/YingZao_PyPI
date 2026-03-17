# -*- coding: utf-8 -*-
"""
GeoAligner_xfm

GhPython 组件：按参考平面对位并移动 / 旋转输入几何

输入（GhPython 组件）:
    Geo : Any | list[Any]
        需要移动 / 旋转的几何或几何列表。
        支持：
        - Point / Point3d
        - Curve / PolylineCurve
        - Surface
        - Brep
        - Mesh
        - Extrusion
        - SubD
        建议：保持类型一致，方便后续操作与下游处理。

    SourcePlane : rg.Plane
        原定位参考平面，视作“几何当前所处的局部坐标系”。

    TargetPlane : rg.Plane
        目标定位参考平面，视作“几何应对齐到的局部坐标系”。
        注意：本组件会先对该平面执行：
            1) RotateDeg 绕自身 Z 轴旋转
            2) FlipX / FlipY / FlipZ 轴向翻转
            3) MoveX / MoveY / MoveZ 沿旋转+Flip 后平面 X/Y/Z 轴平移
        然后再用于 PlaneToPlane 对位。

    RotateDeg : float
        目标参考平面绕自身 Z 轴的旋转角度（单位：度）。
        先旋转，再执行 FlipX / FlipY / FlipZ，再执行 MoveX/Y/Z。

    FlipX : bool
        是否沿目标平面的 YZ 平面镜像（翻转局部 X 轴符号）。
        实现方式参考 FT_AlignToolToTimber：
        - Mirror 平面 = Plane(Origin, YAxis, ZAxis)。

    FlipY : bool
        是否沿目标平面的 XZ 平面镜像（翻转局部 Y 轴符号）。
        Mirror 平面 = Plane(Origin, XAxis, ZAxis)。

    FlipZ : bool
        是否沿目标平面的 XY 平面镜像（翻转局部 Z 轴符号）。
        实现方式与 FT_AlignToolToTimber 一致：
        - 保持 X 不变，把 Y 反向，用新 X/Y 重建平面，
          此时 Normal = X × Y = 原来的 -Z。

    MoveX : float
        沿“旋转 + Flip 后” TargetPlane.XAxis 方向平移的距离。
        使用单位向量，因此数值即为实际模型空间的移动距离。

    MoveY : float
        沿“旋转 + Flip 后” TargetPlane.YAxis 方向平移的距离。

    MoveZ : float
        沿“旋转 + Flip 后” TargetPlane.ZAxis（法线方向）平移的距离。

输出:
    SourceOut : rg.Plane | None
        原参考平面（与输入 SourcePlane 一致，便于可视化 / 检查）。

    TargetOut : rg.Plane | None
        经过 RotateDeg & FlipX / FlipY / FlipZ & MoveX/Y/Z 调整后的目标参考平面。
        即实际用于 PlaneToPlane 对位的平面。

    TransformOut : rg.Transform | None
        最终变换矩阵：PlaneToPlane(SourceOut -> TargetOut)。
        可用于变换其它对象（不局限于 Geo 输入）。

    MovedGeo  : list[rg.GeometryBase] | None
        使用 PlaneToPlane(SourcePlane → TargetOut) 变换后的几何列表。
        若输入 Geo 为单个对象，也会输出为长度为 1 的列表。
"""

import Rhino.Geometry as rg
import math
import Grasshopper.Kernel.Types as ght


class GeoAligner_xfm(object):
    """
    平面对位 + 几何移动 / 旋转 工具类。
    可在多个 GhPython 脚本中复用。
    """

    # ----------------- Flip / 旋转 / 偏移工具 -----------------

    @staticmethod
    def _mirror_plane_like_align_tool(pl, flip_x=False, flip_y=False, flip_z=False):
        """
        仿 FT_AlignToolToTimber 中对 BlockFacePlane 的 FlipX/Y/Z 处理：

        - FlipX : 沿局部 YZ 平面镜像（平面由 Y/Z 向量张成）
                  Mirror 平面 = Plane(Origin, YAxis, ZAxis)
        - FlipY : 沿局部 XZ 平面镜像（平面由 X/Z 向量张成）
                  Mirror 平面 = Plane(Origin, XAxis, ZAxis)
        - FlipZ : 沿局部 XY 平面镜像（翻转局部 Z 轴）
                  实现方式与 FT_AlignToolToTimber 完全一致：
                  保持 X 不变，把 Y 反向，用新的 X/Y 重建平面，
                  Normal = X × Y 自动变成原来的 -Z。

        镜像平面都过 pl.Origin，因此不会改变原点，仅改变局部坐标轴方向。
        """
        if pl is None or not pl.IsValid:
            return None

        plane = rg.Plane(pl)  # 拷贝一份

        # FlipX：沿局部 YZ 平面镜像 -> 翻转局部 X
        if flip_x:
            plane_fx = rg.Plane(
                plane.Origin,
                plane.YAxis,  # Y
                plane.ZAxis   # Z -> YZ 平面
            )
            xf_fx = rg.Transform.Mirror(plane_fx)
            if xf_fx is not None and xf_fx.IsValid:
                plane.Transform(xf_fx)

        # FlipY：沿局部 XZ 平面镜像 -> 翻转局部 Y
        if flip_y:
            plane_fy = rg.Plane(
                plane.Origin,
                plane.XAxis,  # X
                plane.ZAxis   # Z -> XZ 平面
            )
            xf_fy = rg.Transform.Mirror(plane_fy)
            if xf_fy is not None and xf_fy.IsValid:
                plane.Transform(xf_fy)

        # FlipZ：沿局部 XY 平面镜像 -> 翻转局部 Z
        if flip_z:
            # 与 FT_AlignToolToTimber 一致：保持 X，不变；反转 Y；重建平面
            y_flipped = rg.Vector3d(plane.YAxis)
            y_flipped *= -1.0
            x_keep = rg.Vector3d(plane.XAxis)
            plane = rg.Plane(plane.Origin, x_keep, y_flipped)

        return plane

    @staticmethod
    def _coerce_to_float(val, default=0.0):
        """
        通用 float 安全转换：
        - None          → default
        - list/tuple    → 取第一个元素再转换
        - 其他          → 尝试 float()
        - 转换失败      → default
        """
        if val is None:
            return default
        if isinstance(val, (list, tuple)):
            if not val:
                return default
            val = val[0]
        try:
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _rotate_plane(pl, deg):
        """
        让参考平面绕自身 Z 轴旋转 deg 度。
        若 deg 为 None 或不可转换为数字，则不旋转。
        """
        if pl is None:
            return None

        deg_f = GeoAligner_xfm._coerce_to_float(deg, 0.0)
        if abs(deg_f) < 1e-9:
            # 角度极小，视为不旋转
            return rg.Plane(pl)

        rad = math.radians(deg_f)
        new_pl = rg.Plane(pl)
        new_pl.Rotate(rad, new_pl.ZAxis, new_pl.Origin)
        return new_pl

    @staticmethod
    def _offset_plane_along_axes(pl, move_x, move_y, move_z):
        """
        沿平面的 X/Y/Z 轴方向移动平面原点：
        - move_x: 沿 XAxis
        - move_y: 沿 YAxis
        - move_z: 沿 ZAxis

        这里将轴向单位化，确保 MoveX/Y/Z 是“真实距离”。
        """
        if pl is None or not pl.IsValid:
            return None

        dx = GeoAligner_xfm._coerce_to_float(move_x, 0.0)
        dy = GeoAligner_xfm._coerce_to_float(move_y, 0.0)
        dz = GeoAligner_xfm._coerce_to_float(move_z, 0.0)

        if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
            return rg.Plane(pl)

        plane = rg.Plane(pl)

        vx = rg.Vector3d(plane.XAxis)
        vy = rg.Vector3d(plane.YAxis)
        vz = rg.Vector3d(plane.ZAxis)
        if not vx.IsZero: vx.Unitize()
        if not vy.IsZero: vy.Unitize()
        if not vz.IsZero: vz.Unitize()

        move_vec = rg.Vector3d(0, 0, 0)
        if abs(dx) > 1e-9:
            mv = rg.Vector3d(vx)
            mv *= dx
            move_vec += mv
        if abs(dy) > 1e-9:
            mv = rg.Vector3d(vy)
            mv *= dy
            move_vec += mv
        if abs(dz) > 1e-9:
            mv = rg.Vector3d(vz)
            mv *= dz
            move_vec += mv

        if not move_vec.IsZero:
            plane.Origin = plane.Origin + move_vec

        return plane

    @staticmethod
    def build_target_plane(base_plane,
                           rotate_deg,
                           flip_x,
                           flip_y,
                           flip_z,
                           move_x,
                           move_y,
                           move_z):
        """
        从原始 TargetPlane 生成“最终对位用”的目标平面：

        1. 以 base_plane 为起点
        2. 先绕自身 Z 轴旋转 rotate_deg（度）
        3. 再按 flip_x / flip_y / flip_z 执行轴向镜像
           （镜像逻辑与 FT_AlignToolToTimber 完全一致）
        4. 最后沿当前平面的 X/Y/Z 轴方向平移 move_x / move_y / move_z
        """
        if base_plane is None:
            return None

        pl = rg.Plane(base_plane)
        pl = GeoAligner_xfm._rotate_plane(pl, rotate_deg)
        pl = GeoAligner_xfm._mirror_plane_like_align_tool(pl, flip_x, flip_y, flip_z)
        pl = GeoAligner_xfm._offset_plane_along_axes(pl, move_x, move_y, move_z)
        return pl

    # ----------------- 变换与几何 -----------------

    @staticmethod
    def build_transform(source_plane, target_plane):
        """
        构建从 source_plane → target_plane 的 PlaneToPlane 变换。
        """
        if (source_plane is None) or (target_plane is None):
            return None
        if (not source_plane.IsValid) or (not target_plane.IsValid):
            return None

        xf = rg.Transform.PlaneToPlane(source_plane, target_plane)
        if not xf.IsValid:
            return None
        return xf

    @staticmethod
    def transform_geometry(geo, xf):
        """
        对单个或多个几何执行变换，返回列表。
        """
        if geo is None or xf is None:
            return None

        # 统一为列表
        if not isinstance(geo, (list, tuple)):
            geo_list = [geo]
        else:
            geo_list = list(geo)

        out = []
        for g in geo_list:
            if g is None:
                continue
            # Duplicate 兼容常见 GeometryBase；Point3d 特殊处理
            try:
                gg = g.Duplicate()
            except Exception:
                if isinstance(g, rg.Point3d):
                    gg = rg.Point3d(g)
                else:
                    # 其他不支持的类型先跳过
                    continue
            gg.Transform(xf)
            out.append(gg)

        return out if out else None

    @staticmethod
    def align(geo,
              source_plane,
              target_plane,
              rotate_deg=0.0,
              flip_x=False,
              flip_y=False,
              flip_z=False,
              move_x=0.0,
              move_y=0.0,
              move_z=0.0):
        """
        核心对位函数：从输入参数计算对位后的目标平面、Transform 与几何。

        参数:
            geo          : Any | list[Any]
            source_plane : rg.Plane
            target_plane : rg.Plane
            rotate_deg   : float | None
            flip_x/y/z   : bool
            move_x/y/z   : float（沿最终 TargetPlane X/Y/Z 轴方向平移）

        返回:
            (source_out, target_out, transform_out, moved_geo)
        """
        if (geo is None) or (source_plane is None) or (target_plane is None):
            return (None, None, None, None)

        source_out = rg.Plane(source_plane)
        target_out = GeoAligner_xfm.build_target_plane(
            target_plane,
            rotate_deg,
            flip_x,
            flip_y,
            flip_z,
            move_x,
            move_y,
            move_z
        )

        xf = GeoAligner_xfm.build_transform(source_out, target_out)
        moved_geo = GeoAligner_xfm.transform_geometry(geo, xf)

        return (source_out, target_out, xf, moved_geo)


if __name__ == '__main__':
    # =========================================================
    # GhPython 组件主调用区
    # =========================================================
    # 请在组件中设置输入：
    #   Geo, SourcePlane, TargetPlane, RotateDeg, FlipX, FlipY, FlipZ, MoveX, MoveY, MoveZ
    # 输出：
    #   SourceOut, TargetOut, TransformOut, MovedGeo

    SourceOut, TargetOut, TransformOut, MovedGeo = GeoAligner_xfm.align(
        Geo,
        SourcePlane,
        TargetPlane,
        rotate_deg=RotateDeg,
        flip_x=FlipX,
        flip_y=FlipY,
        flip_z=FlipZ,
        move_x=MoveX,
        move_y=MoveY,
        move_z=MoveZ,
    )

    TransformOut = ght.GH_Transform(TransformOut) if TransformOut is not None else None

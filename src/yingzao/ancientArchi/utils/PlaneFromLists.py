# -*- coding: utf-8 -*-
import Rhino.Geometry as rg


class FTPlaneFromLists(object):
    """
    等价于：
    - List Item (OriginPoints)
    - List Item (BasePlanes)
    - Plane Origin
    并带有详细 Log，方便调试和复用。
    """

    def __init__(self, wrap=True):
        """
        Parameters
        ----------
        wrap : bool
            是否采用环绕索引（等价于 GH List Item 的 Wrap）。
        """
        self.wrap = bool(wrap)

    # ---------- 工具方法：输入描述 ----------
    @staticmethod
    def describe_input(name, value):
        if value is None:
            return "{}: None".format(name)
        if isinstance(value, (list, tuple)):
            return "{}: type=list/tuple, len={}".format(name, len(value))
        return "{}: type={}, treated as single value".format(name, type(value))

    # ---------- 工具方法：鲁棒 List Item ----------
    def get_item_any(self, lst, index, label=""):
        """
        模仿 GH List Item 行为，并对非 list 输入做兼容：
        - None           -> 返回 None
        - 非 list/tuple  -> 当作单元素列表 [value]
        返回: (item, log_list)
        """
        info = []

        if lst is None:
            info.append("{}: input is None".format(label))
            return None, info

        if not isinstance(lst, (list, tuple)):
            info.append(
                "{}: input is not list/tuple, wrap into [value], type={}".format(
                    label, type(lst)
                )
            )
            lst = [lst]
        else:
            info.append("{}: input is list/tuple, len={}".format(label, len(lst)))

        if len(lst) == 0:
            info.append("{}: list is empty".format(label))
            return None, info

        if index is None:
            idx = 0
            info.append("{}: index is None, use 0".format(label))
        else:
            idx = int(index)
            info.append("{}: raw index = {}".format(label, idx))

        if self.wrap:
            idx = idx % len(lst)
            info.append(
                "{}: wrap=True, final index = {} (len={})".format(
                    label, idx, len(lst)
                )
            )
        else:
            if idx < 0 or idx >= len(lst):
                info.append(
                    "{}: wrap=False and index out of range (len={}), return None".format(
                        label, len(lst)
                    )
                )
                return None, info

        item = lst[idx]
        info.append("{}: selected item type = {}".format(label, type(item)))
        return item, info

    # ---------- 主功能方法 ----------
    def build_plane(
        self,
        origin_points,
        base_planes,
        index_origin,
        index_plane
    ):
        """
        根据点列表和参考平面列表，构造新平面。

        Parameters
        ----------
        origin_points : list[rg.Point3d] or Point3d
        base_planes   : list[rg.Plane] or Plane
        index_origin  : int
        index_plane   : int

        Returns
        -------
        base_plane   : rg.Plane or None
        origin_point : rg.Point3d or None
        result_plane : rg.Plane or None
        log          : list[str]
        """
        log = []

        log.append("Wrap = {}".format(self.wrap))
        log.append(self.describe_input("OriginPoints", origin_points))
        log.append(self.describe_input("BasePlanes", base_planes))
        log.append("IndexOrigin = {}".format(index_origin))
        log.append("IndexPlane  = {}".format(index_plane))

        base_plane, info_plane = self.get_item_any(
            base_planes, index_plane, label="BasePlanes"
        )
        origin_point, info_point = self.get_item_any(
            origin_points, index_origin, label="OriginPoints"
        )
        log.extend(info_plane)
        log.extend(info_point)

        result_plane = None

        if isinstance(base_plane, rg.Plane) and isinstance(origin_point, rg.Point3d):
            result_plane = rg.Plane(origin_point, base_plane.XAxis, base_plane.YAxis)
            log.append("ResultPlane successfully created.")
        else:
            log.append(
                "ResultPlane NOT created: BasePlane is {}, OriginPoint is {}".format(
                    type(base_plane), type(origin_point)
                )
            )

        return base_plane, origin_point, result_plane, log

if __name__ == "__main__":
    # ==================== 以下为 GhPython 组件入口 ====================

    # 输入端（建议）：
    #   OriginPoints : list[Point3d]
    #   BasePlanes   : list[Plane]
    #   IndexOrigin  : int
    #   IndexPlane   : int
    #   Wrap         : bool (可选)

    # 输出端：
    #   BasePlane
    #   OriginPoint
    #   ResultPlane
    #   Log

    if 'Wrap' not in globals() or Wrap is None:
        Wrap = True

    builder = FTPlaneFromLists(wrap=Wrap)
    BasePlane, OriginPoint, ResultPlane, Log = builder.build_plane(
        OriginPoints,
        BasePlanes,
        IndexOrigin,
        IndexPlane
    )

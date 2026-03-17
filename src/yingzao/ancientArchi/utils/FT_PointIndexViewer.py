# -*- coding: utf-8 -*-
"""Grasshopper Script Instance"""

import System
import Rhino
import Grasshopper
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs


# =========================================================
# 工具：更安全的拍平（只展开“容器”，绝不展开几何对象）
# =========================================================
def _is_container(x):
    """仅把真正的“容器”当作可展开对象。"""
    if x is None:
        return False
    # Python 容器
    if isinstance(x, (list, tuple)):
        return True
    # .NET List / Array
    if isinstance(x, (System.Collections.IList, System.Array)):
        return True
    return False


def _flatten(items):
    if items is None:
        return []
    if _is_container(items):
        out = []
        for it in items:
            out.extend(_flatten(it))
        return out
    # 其它一律视为“原子”（包括所有 Rhino 几何、Point3d、Curve、Mesh…）
    return [items]


# =========================================================
# 工具：提取点
# =========================================================
class PointExtractor(object):
    @staticmethod
    def _bb_center(geo):
        try:
            bb = geo.GetBoundingBox(True)
            if bb.IsValid:
                return bb.Center
        except:
            pass
        return None

    @staticmethod
    def from_one(geo):
        if geo is None:
            return None

        # Plane
        if isinstance(geo, rg.Plane):
            return geo.Origin

        # GH 里点可能是 Point3d，也可能是 Point
        if isinstance(geo, rg.Point3d):
            return geo
        if isinstance(geo, rg.Point):
            return geo.Location

        # Curve
        if isinstance(geo, rg.Curve):
            try:
                amp = rg.AreaMassProperties.Compute(geo)
                if amp:
                    return amp.Centroid
            except:
                pass
            try:
                L = geo.GetLength()
                if L and L > 1e-9:
                    ok, t = geo.LengthParameter(L * 0.5)
                    if ok:
                        return geo.PointAt(t)
            except:
                pass
            return PointExtractor._bb_center(geo)

        # Surface
        if isinstance(geo, rg.Surface):
            try:
                amp = rg.AreaMassProperties.Compute(geo)
                if amp:
                    return amp.Centroid
            except:
                pass
            return PointExtractor._bb_center(geo)

        # BrepFace
        if isinstance(geo, rg.BrepFace):
            try:
                amp = rg.AreaMassProperties.Compute(geo)
                if amp:
                    return amp.Centroid
            except:
                pass
            return PointExtractor._bb_center(geo)

        # Brep
        if isinstance(geo, rg.Brep):
            try:
                vmp = rg.VolumeMassProperties.Compute(geo)
                if vmp:
                    return vmp.Centroid
            except:
                pass
            try:
                amp = rg.AreaMassProperties.Compute(geo)
                if amp:
                    return amp.Centroid
            except:
                pass
            return PointExtractor._bb_center(geo)

        # Mesh（格网）
        if isinstance(geo, rg.Mesh):
            try:
                # Mesh 的几何中心：用包围盒中心最稳
                return PointExtractor._bb_center(geo)
            except:
                pass

        # GeometryBase fallback
        if isinstance(geo, rg.GeometryBase):
            return PointExtractor._bb_center(geo)

        return None

    @staticmethod
    def from_any(inputs):
        geos = _flatten(inputs)
        pts = []
        for g in geos:
            p = PointExtractor.from_one(g)
            if isinstance(p, rg.Point3d):
                pts.append(p)
        return pts


# =========================================================
# TextDot 生成器（交给 GH 预览绘制）
# =========================================================
class FT_PointIndexViewer(object):
    def __init__(self, key="FT_PointIndexViewer"):
        self.key = key or "FT_PointIndexViewer"

    @staticmethod
    def _try_set_dot_size(dot, size):
        # 注意：TextDot 的“大小”在很多 Rhino 版本里基本不可控，
        # 这里尽力设置（若属性存在且生效则生效）
        if size is None:
            return
        try:
            s = float(size)
        except:
            return

        for attr in ("FontHeight", "TextHeight", "Height"):
            try:
                if hasattr(dot, attr):
                    setattr(dot, attr, s)
                    return
            except:
                pass

    def build(self, geo_in, size=1.0, enable=True):
        log = []
        pts = PointExtractor.from_any(geo_in)
        idx = list(range(len(pts)))

        dots = []
        if bool(enable):
            for i, p in enumerate(pts):
                d = rg.TextDot(str(i), p)
                self._try_set_dot_size(d, size)
                dots.append(d)

        log.append("[FT_PointIndexViewer] Key={}".format(self.key))
        log.append("[FT_PointIndexViewer] Inputs(flat)={}".format(len(_flatten(geo_in))))
        log.append("[FT_PointIndexViewer] Extracted Points={}".format(len(pts)))
        log.append("[FT_PointIndexViewer] Size={}".format(size))
        log.append("[FT_PointIndexViewer] Enable={}".format(bool(enable)))

        return pts, idx, dots, "\n".join(log)


# =========================================================
# GH ScriptInstance
# =========================================================
class MyComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self,
            GeoIn: System.Collections.Generic.List[object],
            Size,
            Enable,
            Key):

        if Size is None:
            Size = 1.0
        if Enable is None:
            Enable = True
        if Key is None or str(Key).strip() == "":
            Key = "FT_PointIndexViewer"

        viewer = FT_PointIndexViewer(key=str(Key))
        Points, Indices, Dots, Log = viewer.build(GeoIn, size=Size, enable=Enable)

        # 关键：Dots 输出端打开预览（小眼睛），Rhino 视窗就会显示序号
        return Points, Indices, Dots, Log

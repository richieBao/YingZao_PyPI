# -*- coding: utf-8 -*-
import Rhino
import System
import ghpythonlib.components as ghc
import scriptcontext as sc


class GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC(object):

    def __init__(self):
        self.identity = Rhino.Geometry.Transform.Identity

    @staticmethod
    def _unwrap(x):
        if isinstance(x, (list, tuple)) and len(x) == 1:
            return x[0]
        return x

    @staticmethod
    def _coerce_point3d_from_doc(doc, guid):
        """
        在指定 doc 里通过 guid 查对象并取 Point3d
        """
        if doc is None:
            return None
        try:
            rh_obj = doc.Objects.Find(guid)  # RhinoObject or None (works for RhinoDoc and ghdoc)
            if rh_obj is None:
                return None
            geo = rh_obj.Geometry
            if isinstance(geo, Rhino.Geometry.Point):
                return geo.Location
            if isinstance(geo, Rhino.Geometry.Point3d):
                return geo
        except:
            return None
        return None

    @classmethod
    def _coerce_point3d(cls, origin):
        """
        Guid / GH_Goo(Guid) / Point / Point3d -> Point3d
        查找顺序：
          1) RhinoDoc.ActiveDoc
          2) ghdoc (scriptcontext.doc)
        """
        if origin is None:
            return None

        # unwrap GH_Goo
        if hasattr(origin, "Value"):
            try:
                return cls._coerce_point3d(origin.Value)
            except:
                pass

        if isinstance(origin, Rhino.Geometry.Point3d):
            return origin
        if isinstance(origin, Rhino.Geometry.Point):
            return origin.Location

        # string guid
        if isinstance(origin, str):
            try:
                origin = System.Guid(origin)
            except:
                return None

        if isinstance(origin, System.Guid):
            # 1) RhinoDoc
            pt = cls._coerce_point3d_from_doc(Rhino.RhinoDoc.ActiveDoc, origin)
            if pt is not None:
                return pt
            # 2) GH doc
            pt = cls._coerce_point3d_from_doc(sc.doc, origin)
            if pt is not None:
                return pt
            return None

        return None

    def solve(self,
              TreeItem_Tree,
              TreeItem_Path,
              TreeItem_Index,
              TreeItem_Wrap,
              ListItem_List,
              ListItem_Index,
              ListItem_Wrap,
              Transform_Transform):

        # 1) Tree Item -> base plane（保持 ghc.TreeItem 语义）
        base = ghc.TreeItem(TreeItem_Tree, TreeItem_Path, TreeItem_Index, TreeItem_Wrap)
        base = self._unwrap(base)

        # 2) 你要求：ListItem_List 是 python list[Guid]，直接 python 方式提取
        #    注意 wrap 规则
        if ListItem_List is None or (hasattr(ListItem_List, "__len__") and len(ListItem_List) == 0):
            return None

        n = len(ListItem_List) if hasattr(ListItem_List, "__len__") else 0
        idx = int(ListItem_Index) if ListItem_Index is not None else 0
        if bool(ListItem_Wrap) and n > 0:
            idx = idx % n
        else:
            idx = max(0, min(idx, n - 1)) if n > 0 else 0

        origin_item = ListItem_List[idx]
        origin_pt = self._coerce_point3d(origin_item)

        if origin_pt is None:
            # 解不出点就不要喂给 PlaneOrigin，避免 Guid->Point 报错
            return None

        # 3) Plane Origin
        plane = ghc.PlaneOrigin(base, origin_pt)
        plane = self._unwrap(plane)

        # 4) Transform
        xform = Transform_Transform if Transform_Transform is not None else self.identity
        geo_out = ghc.Transform(plane, xform)
        geo_out = self._unwrap(geo_out)

        return geo_out

if __name__ == '__main__':
    # ===========================
    # GhPython 主调用区
    # ===========================
    solver = GH_TreeItem_ListItem_PlaneOrigin_Transform_GHC()

    Transform_Geometry_Out = solver.solve(
        TreeItem_Tree,
        TreeItem_Path,
        TreeItem_Index,
        TreeItem_Wrap,
        ListItem_List,
        ListItem_Index,
        ListItem_Wrap,
        Transform_Transform
    )

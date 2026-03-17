import Rhino.Geometry as rg
import scriptcontext as sc
import System
import math
from typing import List, Optional


# ----------------- 把任何输入强制转为 Point3d -----------------
def coerce_point3d(p) -> Optional[rg.Point3d]:
    """把 GH 传进来的 Probe 统一转成 Point3d。"""
    if isinstance(p, rg.Point3d):
        return p

    if isinstance(p, rg.Point):
        return p.Location

    if isinstance(p, System.Guid):
        obj = sc.doc.Objects.FindId(p)
        if not obj:
            return None
        geo = obj.Geometry
        if isinstance(geo, rg.Point):
            return geo.Location
        if isinstance(geo, rg.Point3d):
            return geo

    # 其他类型，直接放弃
    return None


# ===========================================================
#                Proximity Picker
# ===========================================================
class ProximityPicker:
    def __init__(self, geo_list):
        # 所有炸开后的点、线、面
        self.pts:  List[rg.Point3d]   = []
        self.crvs: List[rg.Curve]     = []
        self.faces: List[rg.BrepFace] = []

        self._flatten(geo_list)

    # ----------------- Guid → Geometry -----------------
    @staticmethod
    def _from_guid(g) -> Optional[rg.GeometryBase]:
        obj = sc.doc.Objects.FindId(g)
        return obj.Geometry if obj else None

    # ----------------- 统一处理 Brep -----------------
    def _add_brep(self, brep: rg.Brep):
        if not brep:
            return
        # faces
        for f in brep.Faces:
            self.faces.append(f)
        # edges → curves
        for e in brep.Edges:
            c = e.DuplicateCurve()
            if c:
                self.crvs.append(c)
        # vertices → points
        for v in brep.Vertices:
            self.pts.append(v.Location)

    # -----------------  Flatten 所有输入 -----------------
    def _flatten(self, objs):
        if objs is None:
            return
        if not isinstance(objs, list):
            objs = [objs]

        for obj in objs:
            # Guid：从文档查几何
            if isinstance(obj, System.Guid):
                geo = self._from_guid(obj)
            else:
                geo = obj

            if geo is None:
                continue

            # --- Point ---
            if isinstance(geo, rg.Point):
                self.pts.append(geo.Location)
                continue

            if isinstance(geo, rg.Point3d):
                self.pts.append(geo)
                continue

            # --- Curve / PolyCurve ---
            if isinstance(geo, rg.Curve):
                if hasattr(geo, "DuplicateSegments"):
                    segs = geo.DuplicateSegments()
                    if segs:
                        self.crvs.extend(list(segs))
                    else:
                        self.crvs.append(geo)
                else:
                    self.crvs.append(geo)
                continue

            # --- Surface ---
            if isinstance(geo, rg.Surface):
                brep = geo.ToBrep()
                if brep:
                    self._add_brep(brep)
                continue

            # --- Brep ---
            if isinstance(geo, rg.Brep):
                self._add_brep(geo)
                continue

            # --- Mesh ---
            if isinstance(geo, rg.Mesh):
                brep = rg.Brep.CreateFromMesh(geo, True)
                if brep:
                    self._add_brep(brep)
                continue

            # --- SubD ---
            if isinstance(geo, rg.SubD):
                mesh = rg.Mesh.CreateFromSubD(geo)
                brep = rg.Brep.CreateFromMesh(mesh, True)
                if brep:
                    self._add_brep(brep)
                continue

    # ===========================================================
    #                    Nearest Search
    # ===========================================================
    def update(self, probe: rg.Point3d):
        """probe 必须已经是 Point3d。"""
        self.last_probe = probe
        return (
            self._nearest_pt(probe),
            self._nearest_crv(probe),
            self._nearest_face(probe)
        )

    def _nearest_pt(self, probe):
        if not self.pts:
            return None
        min_d = math.inf
        min_i = -1
        for i, p in enumerate(self.pts):
            d = p.DistanceTo(probe)
            if d < min_d:
                min_d = d
                min_i = i
        return self.pts[min_i], min_i, min_d  # (点坐标, 索引, 距离)

    def _nearest_crv(self, probe):
        if not self.crvs:
            return None

        min_d = math.inf
        best_i = -1
        best_t = 0.0

        for i, c in enumerate(self.crvs):
            ok, t = c.ClosestPoint(probe)
            if not ok:
                continue
            pt = c.PointAt(t)
            d = pt.DistanceTo(probe)
            if d < min_d:
                min_d = d
                best_i = i
                best_t = t

        if best_i < 0:
            return None

        pt_on = self.crvs[best_i].PointAt(best_t)
        return pt_on, best_i, min_d  # (最近点, 索引, 距离)

    def _nearest_face(self, probe):
        """BrepFace.ClosestPoint 返回 (ok, u, v)。"""
        if not self.faces:
            return None

        min_d = math.inf
        best_i = -1
        best_u = None
        best_v = None

        for i, f in enumerate(self.faces):
            ok, u, v = f.ClosestPoint(probe)
            if not ok:
                continue

            pt = f.PointAt(u, v)
            d = pt.DistanceTo(probe)

            if d < min_d:
                min_d = d
                best_i = i
                best_u = u
                best_v = v

        if best_i < 0 or best_u is None or best_v is None:
            return None

        pt_on = self.faces[best_i].PointAt(best_u, best_v)
        return pt_on, best_i, min_d  # (最近点, 索引, 距离)

    # ===========================================================
    #                    TextDot 生成
    # ===========================================================
    def make_dots(self, pt_res, crv_res, face_res):
        """根据最近结果生成 TextDot：
           - 点：最近点位置
           - 线：曲线中心点
           - 面：面重心（面积质心），失败则包围盒中心
        """
        dots_pt = []
        dots_crv = []
        dots_face = []

        # 点 dot
        if pt_res:
            loc, idx, _ = pt_res
            dots_pt.append(rg.TextDot("PT:{}".format(idx), loc))

        # 线 dot：放在曲线中点
        if crv_res:
            _, idx, _ = crv_res
            crv = self.crvs[idx]
            dom = crv.Domain
            mid_t = 0.5 * (dom.T0 + dom.T1)
            mid_pt = crv.PointAt(mid_t)
            dots_crv.append(rg.TextDot("CRV:{}".format(idx), mid_pt))

        # 面 dot：放在面重心
        if face_res:
            _, idx, _ = face_res
            face = self.faces[idx]
            amp = rg.AreaMassProperties.Compute(face)
            if amp:
                cen = amp.Centroid
            else:
                cen = face.GetBoundingBox(True).Center
            dots_face.append(rg.TextDot("FACE:{}".format(idx), cen))

        return dots_pt, dots_crv, dots_face

if __name__ == "__main__":
    # ===========================================================
    #                    Grasshopper I/O
    # ===========================================================
    # Probe 可能是 Guid / Point / Point3d，先强制转成 Point3d
    _probe_raw = Probe
    probe_pt = coerce_point3d(_probe_raw)

    geo_raw = Geo  # GH 里一般是 list，也兼容单个

    if probe_pt is None:
        # 没有合法探针点，全部输出 None
        NearestPoint = None
        NearestCurve = None
        NearestFace  = None
        DotPts   = []
        DotCrvs  = []
        DotFaces = []
    else:
        picker = ProximityPicker(geo_raw)

        # 最近点/线/面结果 (最近点坐标, 索引, 距离)
        nearest_pt, nearest_crv, nearest_face = picker.update(probe_pt)

        # TextDot：分别在点、线中点、面重心处
        dots_pt, dots_crv, dots_face = picker.make_dots(nearest_pt, nearest_crv, nearest_face)

        # 输出最近的几何对象本身
        NearestPoint = picker.pts[nearest_pt[1]]   if nearest_pt   else None
    NearestCurve = picker.crvs[nearest_crv[1]] if nearest_crv  else None
    NearestFace  = picker.faces[nearest_face[1]] if nearest_face else None

    DotPts   = dots_pt
    DotCrvs  = dots_crv
    DotFaces = dots_face

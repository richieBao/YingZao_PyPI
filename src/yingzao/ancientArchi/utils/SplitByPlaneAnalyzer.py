"""
GH Python: Split surface/brep by a reference plane and find max area piece.
封装为类 SplitByPlaneAnalyzer，方便复用。

Inputs:
    PlaneRef  : Plane (Access:item)
    SrfOrBrep : Surface or Brep (Access:item)
    Tol       : float (Access:item, optional)

Outputs:
    SplitBreps     : list[Brep]
    Areas          : list[float]
    MaxAreaBrep    : Brep
    MaxArea        : float
    SectionCurves  : list[Curve]
    SectionPoints  : list[Point3d]
    Log            : list[str]
"""

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import ghpythonlib.components as ghc


class SplitByPlaneAnalyzer(object):
    """
    用参考平面剖切 Brep/Surface，输出分割片段、面积列表、最大面积片段。
    - 求交线使用 ghc.BrepXPlane（用于输出/检查）
    - 实际裁切使用 RhinoCommon：用 PlaneSurface->Brep 作为 cutter，再 Split
      这样避免 IronPython 重载误选导致的 “PolylineCurve cannot convert to Brep” 错误
    """

    def __init__(self, brep_or_srf, plane_ref, tol=None, cutter_scale=2.0):
        self.brep_in = self._as_brep(brep_or_srf)
        self.plane_ref = self._as_plane(plane_ref)
        self.tol = tol
        self.cutter_scale = float(cutter_scale)

        self.section_curves = []
        self.section_points = []

        self.split_breps = []
        self.areas = []
        self.max_area_brep = None
        self.max_area = None

        self.log = []

    # ---------- helpers ----------
    @staticmethod
    def _ensure_list(x):
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]

    @staticmethod
    def _as_plane(p):
        if p is None:
            return None
        if isinstance(p, rg.Plane):
            return p
        # GH plane-like object (has Origin/XAxis/YAxis)
        try:
            return rg.Plane(p.Origin, p.XAxis, p.YAxis)
        except:
            return None

    @staticmethod
    def _as_brep(g):
        if g is None:
            return None
        if isinstance(g, rg.Brep):
            return g
        if isinstance(g, rg.Surface):
            try:
                return g.ToBrep()
            except:
                return None
        # other geometry that might support ToBrep
        try:
            if hasattr(g, "ToBrep"):
                return g.ToBrep()
        except:
            pass
        return None

    @staticmethod
    def _area_of_brep(b):
        if b is None:
            return None
        try:
            if hasattr(b, "IsValid") and (not b.IsValid):
                return None
            amp = rg.AreaMassProperties.Compute(b)
            return amp.Area if amp else None
        except:
            return None

    def _get_tol(self):
        if self.tol is not None:
            return float(self.tol)
        try:
            return sc.doc.ModelAbsoluteTolerance
        except:
            return 0.01

    def _make_big_plane_cutter_brep(self, brep_in, plane_ref, tol):
        """
        构造一个足够大的平面 Brep 作为 cutter，覆盖 brep bbox
        """
        bb = brep_in.GetBoundingBox(True)
        diag = bb.Diagonal.Length
        if diag <= 0:
            diag = 1000.0

        size = diag * self.cutter_scale
        itv = rg.Interval(-size, size)
        ps = rg.PlaneSurface(plane_ref, itv, itv)
        cb = ps.ToBrep()
        return cb

    # ---------- core ----------
    def run(self):
        tol = self._get_tol()

        if self.plane_ref is None:
            self.log.append("[ERROR] PlaneRef is None or not a valid rg.Plane.")
            return self

        if self.brep_in is None or (hasattr(self.brep_in, "IsValid") and not self.brep_in.IsValid):
            self.log.append("[ERROR] SrfOrBrep is None or not a valid Brep/Surface.")
            return self

        # 1) Section curves (BrepXPlane) - mainly for output/inspection
        try:
            crvs, pts = ghc.BrepXPlane(self.brep_in, self.plane_ref)
            self.section_curves = self._ensure_list(crvs)
            self.section_points = self._ensure_list(pts)
            self.log.append("[OK] BrepXPlane curves = {}, points = {}".format(
                len(self.section_curves), len(self.section_points)
            ))
        except Exception as e:
            self.section_curves = []
            self.section_points = []
            self.log.append("[ERROR] BrepXPlane failed: {}".format(e))

        # 2) Split by planar cutter brep (avoid overload mismatch)
        try:
            cutter_brep = self._make_big_plane_cutter_brep(self.brep_in, self.plane_ref, tol)
            pieces = self.brep_in.Split(cutter_brep, tol)  # <--关键：Brep cutter
            self.split_breps = list(pieces) if pieces else []
            self.log.append("[OK] Split pieces count = {}".format(len(self.split_breps)))
        except Exception as e:
            self.split_breps = []
            self.log.append("[ERROR] brep.Split failed: {}".format(e))

        if not self.split_breps:
            self.log.append("[WARN] Split produced 0 pieces. Return original brep as single piece.")
            self.split_breps = [self.brep_in]

        # 3) Areas + max
        max_a = -1.0
        max_b = None
        self.areas = []

        for i, b in enumerate(self.split_breps):
            a = self._area_of_brep(b)
            self.areas.append(a)
            if a is None:
                self.log.append("[WARN] piece[{}] area compute failed.".format(i))
                continue
            if a > max_a:
                max_a = a
                max_b = b

        self.max_area_brep = max_b
        self.max_area = max_a if max_b is not None else None

        if self.max_area is not None:
            self.log.append("[OK] Max area = {}".format(self.max_area))
        else:
            self.log.append("[WARN] No valid area computed.")

        return self

if __name__ == "__main__":
    # ===========================
    # GH Python main (调用示例)
    # ===========================
    _plane = globals().get("PlaneRef", None)
    _geo = globals().get("SrfOrBrep", None)
    _tol = globals().get("Tol", None)

    _an = SplitByPlaneAnalyzer(_geo, _plane, tol=_tol, cutter_scale=2.0).run()

    SplitBreps = _an.split_breps
    Areas = _an.areas
    MaxAreaBrep = _an.max_area_brep
    MaxArea = _an.max_area

    SectionCurves = _an.section_curves
    SectionPoints = _an.section_points
    Log = _an.log

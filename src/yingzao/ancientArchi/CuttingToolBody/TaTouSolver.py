# -*- coding: utf-8 -*-
"""
TaTouSolver.py
榻頭 GhPython 组件（二维截面 + 双侧偏移成体 + 指定侧面固定顺序输出）

说明：
    本脚本按用户给定的“榻頭”几何生成逻辑组织为类与方法，
    参考 SanBanTouSolver.py 的组织方式，保留：
        1) 类封装
        2) run() 统一执行
        3) GH 输出绑定区
        4) 开发模式下可按需增加同名输出端查看内部数据

-------------------------------------------------------------------------------
输入（GhPython 建议设置）:
    O : rg.Point3d
        Access = Item
        TypeHint = Point3d
        定位点 / 参考原点。

    P : rg.Plane
        Access = Item
        TypeHint = Plane
        参考平面。可为空。
        若为空，默认使用 WorldXY；但其原点会被重置到 O。
        实际计算平面记为 PBase：
            - Origin = O
            - XAxis  = 放样厚度方向
            - YAxis  = O->B 方向
            - ZAxis  = O->O' 方向

    Height_OOPrime : float
        Access = Item
        TypeHint = float
        O-O' 直线长度，即高。

    Length_BO : float
        Access = Item
        TypeHint = float
        B-O 直线长度。
        点 B 位于 O 点沿 PBase.YAxis 方向。

    HalfThicknessX : float
        Access = Item
        TypeHint = float
        沿参考平面 X 轴双侧偏移复制 Section 的半厚度。
        即：
            SectionNeg = 沿 -PBase.XAxis 平移 HalfThicknessX
            SectionPos = 沿 +PBase.XAxis 平移 HalfThicknessX

    Refresh : bool
        Access = Item
        TypeHint = bool
        是否强制重算；用于和其他组件风格保持一致。

输出（正式输出端建议）:
    SolidBrep : rg.Brep
        榻頭实体。

    OOPrimeFace : rg.Brep
        实体中由截面边 O-O' 沿 X 轴双侧偏移形成的侧面。

    OOPrimeFaceCornerPoints : list[rg.Point3d]
        O-O' 所在面四角点，固定顺序：
            [neg_start, neg_end, pos_end, pos_start]
        对应此处：
            [neg_O, neg_OPrime, pos_OPrime, pos_O]

    OOPrimeFaceEdgeMidPoints : list[rg.Point3d]
        O-O' 所在面四边中点，固定顺序对应四条边：
            0: neg_start -> neg_end
            1: neg_end   -> pos_end
            2: pos_end   -> pos_start
            3: pos_start -> neg_start

    OOPrimeFacePlaneList : list[rg.Plane]
        O-O' 所在面的参考平面列表，固定顺序：
            [edge_mid_0_plane, edge_mid_1_plane, edge_mid_2_plane, edge_mid_3_plane,
             corner_0_plane,  corner_1_plane,  corner_2_plane,  corner_3_plane]

    OBFace : rg.Brep
        实体中由截面边 O-B 沿 X 轴双侧偏移形成的侧面。

    OBFaceCornerPoints : list[rg.Point3d]
        O-B 所在面四角点，固定顺序：
            [neg_start, neg_end, pos_end, pos_start]
        对应此处：
            [neg_O, neg_B, pos_B, pos_O]

    OBFaceEdgeMidPoints : list[rg.Point3d]
        O-B 所在面四边中点，固定顺序同上。

    OBFacePlaneList : list[rg.Plane]
        O-B 所在面的参考平面列表，固定顺序同上。

    OOut : rg.Point3d
        输出点 O。

    AOut : rg.Point3d
        输出点 A。

    BOut : rg.Point3d
        输出点 B。

    OPrimeOut : rg.Point3d
        输出点 O'。

    COut : rg.Point3d
        输出点 C。

    D1Out : rg.Point3d
        输出点 d1（靠近 O' 的四等分点）。

    D2Out : rg.Point3d
        输出点 d2。

    D3Out : rg.Point3d
        输出点 d3（靠近 O 的四等分点）。

    Log : list[str]
        调试输出。

开发模式输出（按需在 GH 中添加同名输出端）:
    PBase, Line_OOPrime, Line_BO, Line_BD3, Line_OPrimeA, SectionCurve, SectionSegments,
    SectionNeg, SectionPos, LoftBrep, CapNeg, CapPos, FacePlane_OOPrime, FacePlane_OB
-------------------------------------------------------------------------------
"""

try:
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
except Exception:
    rg = None
    sc = None


class TaTouResult(object):
    def __init__(self):
        self.Log = []


class TaTouSolver(object):
    def __init__(self,
                 O=None,
                 P=None,
                 Height_OOPrime=None,
                 Length_BO=None,
                 HalfThicknessX=None,
                 Refresh=False,
                 ghenv=None):
        self.O = O
        self.P = P
        self.Height_OOPrime = Height_OOPrime
        self.Length_BO = Length_BO
        self.HalfThicknessX = HalfThicknessX
        self.Refresh = Refresh
        self.ghenv = ghenv
        self.Log = []

    def run(self):
        result = TaTouResult()
        try:
            self._validate_inputs()
            self._build_base_frame()
            self._build_key_points()
            self._build_lines_and_intersection()
            self._build_section()
            self._build_solid()
            self._build_named_faces()
            self._publish(result)
        except Exception as e:
            self.Log.append("[ERR] 榻頭构建失败: {}".format(e))
            self._publish(result)
        return self

    def _validate_inputs(self):
        if rg is None:
            raise Exception("当前环境未加载 RhinoCommon。")
        if self.O is None:
            raise Exception("输入 O 不能为空。")
        if self.Height_OOPrime is None or self.Height_OOPrime <= 0:
            raise Exception("Height_OOPrime 必须为正数。")
        if self.Length_BO is None or self.Length_BO <= 0:
            raise Exception("Length_BO 必须为正数。")
        if self.HalfThicknessX is None or self.HalfThicknessX <= 0:
            raise Exception("HalfThicknessX 必须为正数。")

    def _build_base_frame(self):
        if self.P is None:
            p = rg.Plane.WorldXY
        else:
            p = rg.Plane(self.P)
        p.Origin = self.O
        p = self._orthonormal_plane(p)
        self.PBase = p
        self.X = rg.Vector3d(p.XAxis)
        self.Y = rg.Vector3d(p.YAxis)
        self.Z = rg.Vector3d(p.ZAxis)
        self.X.Unitize()
        self.Y.Unitize()
        self.Z.Unitize()
        self.Log.append("[OK] 已建立参考平面 PBase。")

    def _build_key_points(self):
        self.OPrime = self.O + self.Z * self.Height_OOPrime

        # 依题意：A 与 B 均位于 O 点沿参考平面 Y 轴方向。
        self.A = self.O + self.Y * (self.Height_OOPrime * 2.0 / 4.0)
        self.B = self.O + self.Y * self.Length_BO

        # O-O' 四等分点；按图意命名 d1, d2, d3 为自上而下
        self.d1 = self.O + self.Z * (self.Height_OOPrime * 3.0 / 4.0)
        self.d2 = self.O + self.Z * (self.Height_OOPrime * 2.0 / 4.0)
        self.d3 = self.O + self.Z * (self.Height_OOPrime * 1.0 / 4.0)

        self.Log.append("[OK] 已完成 O, A, B, O' 及 d1, d2, d3 关键点构造。")

    def _build_lines_and_intersection(self):
        self.Line_OOPrime = rg.Line(self.O, self.OPrime)
        self.Line_BO = rg.Line(self.B, self.O)
        self.Line_BD3 = rg.Line(self.B, self.d3)
        self.Line_OPrimeA = rg.Line(self.OPrime, self.A)

        line1 = rg.LineCurve(self.Line_BD3)
        line2 = rg.LineCurve(self.Line_OPrimeA)
        events = rg.Intersect.Intersection.CurveCurve(line1, line2, self._tol(), self._tol())
        if events is None or events.Count == 0:
            raise Exception("直线 B-d3 与 O'-A 未求得交点 C。")

        self.C = None
        for i in range(events.Count):
            ev = events[i]
            if ev.IsPoint:
                self.C = ev.PointA
                break

        if self.C is None:
            raise Exception("交点事件存在，但未解析出点交点 C。")

        self.Log.append("[OK] 已完成直线 B-d3 与 O'-A 的交点 C 求解。")

    def _build_section(self):
        self.Line_O_to_OPrime = rg.LineCurve(self.O, self.OPrime)
        self.Line_OPrime_to_C = rg.LineCurve(self.OPrime, self.C)
        self.Line_C_to_B = rg.LineCurve(self.C, self.B)
        self.Line_B_to_O = rg.LineCurve(self.B, self.O)

        pieces = [
            self.Line_O_to_OPrime,
            self.Line_OPrime_to_C,
            self.Line_C_to_B,
            self.Line_B_to_O,
        ]

        joined = rg.Curve.JoinCurves(pieces, self._tol())
        if not joined or len(joined) != 1:
            raise Exception("SectionCurve 拼接失败，未形成唯一闭合曲线。")

        self.SectionCurve = joined[0]

        if not self.SectionCurve.IsClosed:
            raise Exception("SectionCurve 未闭合。")

        self.SectionSegments = pieces
        self.Log.append("[OK] 已形成封闭截面 SectionCurve（O-O'-C-B-O）。")

    def _build_solid(self):
        total_thickness = self.HalfThicknessX * 2.0
        x_neg = -self.X * self.HalfThicknessX
        x_pos = self.X * self.HalfThicknessX

        self.SectionNeg = self._duplicate_and_translate(self.SectionCurve, x_neg)
        self.SectionPos = self._duplicate_and_translate(self.SectionCurve, x_pos)

        extrude_vec = self.X * total_thickness
        extrusion_srf = rg.Surface.CreateExtrusion(self.SectionNeg, extrude_vec)
        if extrusion_srf is None:
            raise Exception("Surface.CreateExtrusion 失败。")

        extrude_brep = rg.Brep.CreateFromSurface(extrusion_srf)
        if extrude_brep is None:
            raise Exception("Brep.CreateFromSurface 失败。")

        self.LoftBrep = extrude_brep

        capped = extrude_brep.CapPlanarHoles(self._tol())
        if capped is None:
            raise Exception("CapPlanarHoles 失败，无法封闭榻頭实体。")
        if not capped.IsSolid:
            raise Exception("CapPlanarHoles 后结果不是封闭实体。")

        self.SolidBrep = capped

        cap_neg = rg.Brep.CreatePlanarBreps(self.SectionNeg, self._tol())
        cap_pos = rg.Brep.CreatePlanarBreps(self.SectionPos, self._tol())
        self.CapNeg = cap_neg[0] if cap_neg and len(cap_neg) > 0 else None
        self.CapPos = cap_pos[0] if cap_pos and len(cap_pos) > 0 else None

        self.Log.append("[OK] 已通过挤出 + 封盖构建榻頭实体 SolidBrep。")

    def _build_named_faces(self):
        self.FacePlane_OOPrime = self._side_face_plane(self.O, self.OPrime)
        self.FacePlane_OB = self._side_face_plane(self.O, self.B)

        oo_face_data = self._make_ordered_side_face(self.O, self.OPrime)
        self.OOPrimeFace = oo_face_data["FaceBrep"]
        self.OOPrimeFaceCornerPoints = oo_face_data["CornerPoints"]
        self.OOPrimeFaceEdgeMidPoints = oo_face_data["EdgeMidPoints"]
        self.OOPrimeFacePlaneList = oo_face_data["PlaneList"]

        ob_face_data = self._make_ordered_side_face(self.O, self.B)
        self.OBFace = ob_face_data["FaceBrep"]
        self.OBFaceCornerPoints = ob_face_data["CornerPoints"]
        self.OBFaceEdgeMidPoints = ob_face_data["EdgeMidPoints"]
        self.OBFacePlaneList = ob_face_data["PlaneList"]

        self.Log.append("[OK] 已生成 O-O' 与 O-B 两个指定侧面的固定顺序输出。")

    def _publish(self, result):
        result.SolidBrep = getattr(self, "SolidBrep", None)

        result.OOPrimeFace = getattr(self, "OOPrimeFace", None)
        result.OOPrimeFaceCornerPoints = getattr(self, "OOPrimeFaceCornerPoints", [])
        result.OOPrimeFaceEdgeMidPoints = getattr(self, "OOPrimeFaceEdgeMidPoints", [])
        result.OOPrimeFacePlaneList = getattr(self, "OOPrimeFacePlaneList", [])

        result.OBFace = getattr(self, "OBFace", None)
        result.OBFaceCornerPoints = getattr(self, "OBFaceCornerPoints", [])
        result.OBFaceEdgeMidPoints = getattr(self, "OBFaceEdgeMidPoints", [])
        result.OBFacePlaneList = getattr(self, "OBFacePlaneList", [])

        result.OOut = getattr(self, "O", None)
        result.AOut = getattr(self, "A", None)
        result.BOut = getattr(self, "B", None)
        result.OPrimeOut = getattr(self, "OPrime", None)
        result.COut = getattr(self, "C", None)
        result.D1Out = getattr(self, "d1", None)
        result.D2Out = getattr(self, "d2", None)
        result.D3Out = getattr(self, "d3", None)
        result.Log = list(self.Log)

        names = [
            "PBase", "Line_OOPrime", "Line_BO", "Line_BD3", "Line_OPrimeA",
            "SectionCurve", "SectionSegments", "SectionNeg", "SectionPos",
            "LoftBrep", "CapNeg", "CapPos", "FacePlane_OOPrime", "FacePlane_OB",
            "d1", "d2", "d3"
        ]
        for n in names:
            setattr(result, n, getattr(self, n, None))

        for k, v in result.__dict__.items():
            setattr(self, k, v)

    def _make_ordered_side_face(self, start_pt, end_pt):
        neg_start = start_pt - self.X * self.HalfThicknessX
        neg_end = end_pt - self.X * self.HalfThicknessX
        pos_end = end_pt + self.X * self.HalfThicknessX
        pos_start = start_pt + self.X * self.HalfThicknessX

        corners = [neg_start, neg_end, pos_end, pos_start]

        edges = [
            rg.Line(neg_start, neg_end),
            rg.Line(neg_end, pos_end),
            rg.Line(pos_end, pos_start),
            rg.Line(pos_start, neg_start),
        ]
        edge_mid_pts = [ln.PointAt(0.5) for ln in edges]

        face_plane = self._side_face_plane(start_pt, end_pt)
        plane_list = [
            self._plane_at(face_plane, edge_mid_pts[0]),
            self._plane_at(face_plane, edge_mid_pts[1]),
            self._plane_at(face_plane, edge_mid_pts[2]),
            self._plane_at(face_plane, edge_mid_pts[3]),
            self._plane_at(face_plane, corners[0]),
            self._plane_at(face_plane, corners[1]),
            self._plane_at(face_plane, corners[2]),
            self._plane_at(face_plane, corners[3]),
        ]

        poly = rg.Polyline(corners + [corners[0]])
        crv = poly.ToNurbsCurve()
        face_breps = rg.Brep.CreatePlanarBreps(crv, self._tol())
        face_brep = face_breps[0] if face_breps and len(face_breps) > 0 else None

        return {
            "FaceBrep": face_brep,
            "CornerPoints": corners,
            "EdgeMidPoints": edge_mid_pts,
            "PlaneList": plane_list,
        }

    def _side_face_plane(self, start_pt, end_pt):
        edge_dir = rg.Vector3d(end_pt - start_pt)
        if not edge_dir.Unitize():
            raise Exception("侧面边方向长度为 0。")

        x_dir = rg.Vector3d(self.X)
        if not x_dir.Unitize():
            raise Exception("X 方向非法。")

        normal = rg.Vector3d.CrossProduct(edge_dir, x_dir)
        if not normal.Unitize():
            raise Exception("无法建立侧面平面法向。")

        y_dir = rg.Vector3d.CrossProduct(normal, edge_dir)
        y_dir.Unitize()

        plane = rg.Plane(start_pt, edge_dir, y_dir)
        return self._orthonormal_plane(plane)

    def _duplicate_and_translate(self, curve, vec):
        dup = curve.DuplicateCurve()
        xf = rg.Transform.Translation(vec)
        dup.Transform(xf)
        return dup

    @staticmethod
    def _plane_at(base_plane, origin):
        p = rg.Plane(base_plane)
        p.Origin = origin
        return p

    @staticmethod
    def _orthonormal_plane(plane):
        x = rg.Vector3d(plane.XAxis)
        y = rg.Vector3d(plane.YAxis)
        if not x.Unitize():
            x = rg.Vector3d.XAxis
        z = rg.Vector3d.CrossProduct(x, y)
        if not z.Unitize():
            z = rg.Vector3d.ZAxis
        y = rg.Vector3d.CrossProduct(z, x)
        y.Unitize()
        return rg.Plane(plane.Origin, x, y)

    @staticmethod
    def _tol():
        try:
            if sc is not None and sc.doc is not None:
                return sc.doc.ModelAbsoluteTolerance
        except Exception:
            pass
        return 1e-6


# ============================================================================
# GH 输出绑定区
# ============================================================================
if __name__ == "__main__":

    try:
        _O = O
    except:
        _O = None

    try:
        _P = P
    except:
        _P = None

    try:
        _Height_OOPrime = Height_OOPrime
    except:
        _Height_OOPrime = None

    try:
        _Length_BO = Length_BO
    except:
        _Length_BO = None

    try:
        _HalfThicknessX = HalfThicknessX
    except:
        _HalfThicknessX = None

    try:
        _Refresh = Refresh
    except:
        _Refresh = False

    solver = TaTouSolver(
        O=_O,
        P=_P,
        Height_OOPrime=_Height_OOPrime,
        Length_BO=_Length_BO,
        HalfThicknessX=_HalfThicknessX,
        Refresh=_Refresh,
        ghenv=ghenv
    )
    solver.run()

    # 正式输出
    SolidBrep = solver.SolidBrep

    OOPrimeFace = solver.OOPrimeFace
    OOPrimeFaceCornerPoints = solver.OOPrimeFaceCornerPoints
    OOPrimeFaceEdgeMidPoints = solver.OOPrimeFaceEdgeMidPoints
    OOPrimeFacePlaneList = solver.OOPrimeFacePlaneList

    OBFace = solver.OBFace
    OBFaceCornerPoints = solver.OBFaceCornerPoints
    OBFaceEdgeMidPoints = solver.OBFaceEdgeMidPoints
    OBFacePlaneList = solver.OBFacePlaneList

    OOut = solver.OOut
    AOut = solver.AOut
    BOut = solver.BOut
    OPrimeOut = solver.OPrimeOut
    COut = solver.COut
    D1Out = solver.D1Out
    D2Out = solver.D2Out
    D3Out = solver.D3Out

    Log = solver.Log

    # 开发模式：按需在 GH 中添加同名输出端即可看到内部数据
    try:
        PBase = solver.PBase
        Line_OOPrime = solver.Line_OOPrime
        Line_BO = solver.Line_BO
        Line_BD3 = solver.Line_BD3
        Line_OPrimeA = solver.Line_OPrimeA

        SectionCurve = solver.SectionCurve
        SectionSegments = solver.SectionSegments
        SectionNeg = solver.SectionNeg
        SectionPos = solver.SectionPos
        LoftBrep = solver.LoftBrep
        CapNeg = solver.CapNeg
        CapPos = solver.CapPos

        FacePlane_OOPrime = solver.FacePlane_OOPrime
        FacePlane_OB = solver.FacePlane_OB

        d1 = solver.d1
        d2 = solver.d2
        d3 = solver.d3
    except:
        pass
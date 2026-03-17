# -*- coding: utf-8 -*-
"""
SanBanTouSolver.py
三瓣头 GhPython 组件（二维截面 + 双侧偏移放样成体 + 指定侧面固定顺序输出）

说明：
    本脚本按用户给定的“三瓣头”几何生成逻辑组织为类与方法，
    并参考 JiaoLiangSolver.py 的 GhPython 组件组织方式，保留：
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

    AToOPrime : float
        Access = Item
        TypeHint = float
        A-O' 直线长度。
        点 A 位于 O-O' 线上，满足：A = O' - PBase.ZAxis * AToOPrime。

    EOffset : float
        Access = Item
        TypeHint = float
        点 E 到 E' 的垂直偏移长度。
        E' 取在 O-A-B 三角形内部一侧。

    PetalOffset : float
        Access = Item
        TypeHint = float
        I-I'、H-H'、J-J'、K-K' 的统一偏移长度。
        其中：
            - H'、J' 与 E' 同侧（位于 O-A-B 三角形内部侧）
            - I'、K' 反向（位于外侧）

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
        三瓣头实体。

    OAFace : rg.Brep
        实体中由截面边 O-A 沿 X 轴双侧偏移形成的侧面。

    OAFaceCornerPoints : list[rg.Point3d]
        O-A 所在面四角点，固定顺序：
            [neg_start, neg_end, pos_end, pos_start]
        对应此处：
            [neg_O, neg_A, pos_A, pos_O]

    OAFaceEdgeMidPoints : list[rg.Point3d]
        O-A 所在面四边中点，固定顺序对应四条边：
            0: neg_start -> neg_end
            1: neg_end   -> pos_end
            2: pos_end   -> pos_start
            3: pos_start -> neg_start

    OAFacePlaneList : list[rg.Plane]
        O-A 所在面的参考平面列表，固定顺序：
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

    Log : list[str]
        调试输出。

开发模式输出（按需在 GH 中添加同名输出端）:
    PBase, ABLine, SectionCurve, SectionSegments, Arc_BIF, Arc_FHD, Arc_DEC,
    Arc_CJG, Arc_GKA, C, D, E, F, G, H, I, J, K, EPrime, IPrime, HPrime,
    JPrime, KPrime, SectionNeg, SectionPos, LoftBrep, CapNeg, CapPos,
    FacePlane_OA, FacePlane_OB
-------------------------------------------------------------------------------
"""

try:
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
except Exception:
    rg = None
    sc = None


class SanBanTouResult(object):
    def __init__(self):
        self.Log = []


class SanBanTouSolver(object):
    def __init__(self,
                 O=None,
                 P=None,
                 Height_OOPrime=None,
                 AToOPrime=None,
                 EOffset=None,
                 PetalOffset=None,
                 HalfThicknessX=None,
                 Refresh=False,
                 ghenv=None):
        self.O = O
        self.P = P
        self.Height_OOPrime = Height_OOPrime
        self.AToOPrime = AToOPrime
        self.EOffset = EOffset
        self.PetalOffset = PetalOffset
        self.HalfThicknessX = HalfThicknessX
        self.Refresh = Refresh
        self.ghenv = ghenv
        self.Log = []

    def run(self):
        result = SanBanTouResult()
        try:
            self._validate_inputs()
            self._build_base_frame()
            self._build_key_points()
            self._build_offset_points()
            self._build_section()
            self._build_solid()
            self._build_named_faces()
            self._publish(result)
        except Exception as e:
            self.Log.append("[ERR] 三瓣头构建失败: {}".format(e))
            self._publish(result)
        return self

    def _validate_inputs(self):
        if rg is None:
            raise Exception("当前环境未加载 RhinoCommon。")
        if self.O is None:
            raise Exception("输入 O 不能为空。")
        if self.Height_OOPrime is None or self.Height_OOPrime <= 0:
            raise Exception("Height_OOPrime 必须为正数。")
        if self.AToOPrime is None or self.AToOPrime < 0:
            raise Exception("AToOPrime 必须 >= 0。")
        if self.AToOPrime > self.Height_OOPrime:
            raise Exception("AToOPrime 不能大于 Height_OOPrime，否则 A 会落到 O 以下。")
        if self.EOffset is None or self.EOffset <= 0:
            raise Exception("EOffset 必须为正数。")
        if self.PetalOffset is None or self.PetalOffset <= 0:
            raise Exception("PetalOffset 必须为正数。")
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
        self.A = self.OPrime - self.Z * self.AToOPrime
        self.B = self.O + self.Y * (self.Height_OOPrime * 2.0 / 3.0)

        self.ABLine = rg.Line(self.A, self.B)
        self.C = self.ABLine.PointAt(1.0 / 3.0)
        self.D = self.ABLine.PointAt(2.0 / 3.0)

        self.G = self._midpoint(self.C, self.A)
        self.F = self._midpoint(self.D, self.B)

        self.I = self._midpoint(self.B, self.F)
        self.H = self._midpoint(self.F, self.D)
        self.E = self._midpoint(self.D, self.C)
        self.J = self._midpoint(self.C, self.G)
        self.K = self._midpoint(self.G, self.A)

        self.Log.append("[OK] 已完成 O, A, B, O' 及 C~K 关键点构造。")

    def _build_offset_points(self):
        ab_dir = rg.Vector3d(self.B - self.A)
        if not ab_dir.Unitize():
            raise Exception("A 与 B 重合，无法建立 AB 方向。")

        # 在 PBase 内垂直于 AB 的方向
        perp = rg.Vector3d.CrossProduct(self.X, ab_dir)
        if not perp.Unitize():
            raise Exception("无法在 PBase 内建立 AB 的垂直方向。")

        # 判定哪一侧更接近三角形 OAB 内部
        tri_centroid = rg.Point3d(
            (self.O.X + self.A.X + self.B.X) / 3.0,
            (self.O.Y + self.A.Y + self.B.Y) / 3.0,
            (self.O.Z + self.A.Z + self.B.Z) / 3.0,
        )
        ab_mid = self._midpoint(self.A, self.B)
        test_pos = ab_mid + perp
        test_neg = ab_mid - perp

        d_pos = test_pos.DistanceTo(tri_centroid)
        d_neg = test_neg.DistanceTo(tri_centroid)

        self.InnerPerp = perp if d_pos <= d_neg else -perp
        self.OuterPerp = -self.InnerPerp

        self.EPrime = self.E + self.InnerPerp * self.EOffset
        self.IPrime = self.I + self.OuterPerp * self.PetalOffset
        self.HPrime = self.H + self.InnerPerp * self.PetalOffset
        self.JPrime = self.J + self.InnerPerp * self.PetalOffset
        self.KPrime = self.K + self.OuterPerp * self.PetalOffset

        self.Log.append("[OK] 已建立 E'、I'、H'、J'、K' 偏移控制点。")

    def _build_section(self):
        self.Arc_BIF = self._arc3(self.B, self.IPrime, self.F, "B-I'-F")
        self.Arc_FHD = self._arc3(self.F, self.HPrime, self.D, "F-H'-D")
        self.Arc_DEC = self._arc3(self.D, self.EPrime, self.C, "D-E'-C")
        self.Arc_CJG = self._arc3(self.C, self.JPrime, self.G, "C-J'-G")
        self.Arc_GKA = self._arc3(self.G, self.KPrime, self.A, "G-K'-A")

        self.Line_OB = rg.LineCurve(self.O, self.B)
        self.Line_AO = rg.LineCurve(self.A, self.O)

        pieces = [
            self.Line_OB,
            self.Arc_BIF,
            self.Arc_FHD,
            self.Arc_DEC,
            self.Arc_CJG,
            self.Arc_GKA,
            self.Line_AO,
        ]

        joined = rg.Curve.JoinCurves(pieces, self._tol())
        if not joined or len(joined) != 1:
            raise Exception("SectionCurve 拼接失败，未形成唯一闭合曲线。")

        self.SectionCurve = joined[0]
        if not self.SectionCurve.IsClosed:
            raise Exception("SectionCurve 未闭合。")

        self.SectionSegments = pieces
        self.Log.append("[OK] 已形成封闭截面 SectionCurve。")


    def _build_solid(self):
        """
        原先用两条闭合曲线 Loft，RhinoCommon 在某些情况下会失败。
        这里改为更稳妥的做法：
            1) 将原 SectionCurve 平移到 -X 侧，作为起始截面；
            2) 沿 +X 方向挤出总厚度 2 * HalfThicknessX；
            3) 对挤出 Brep 做平面封盖，得到封闭实体。
        """
        total_thickness = self.HalfThicknessX * 2.0

        x_neg = -self.X * self.HalfThicknessX
        x_pos = self.X * self.HalfThicknessX

        # 保留两侧截面输出，供开发模式查看
        self.SectionNeg = self._duplicate_and_translate(self.SectionCurve, x_neg)
        self.SectionPos = self._duplicate_and_translate(self.SectionCurve, x_pos)

        # 以负侧截面为起始轮廓，沿 +X 挤出
        extrude_vec = self.X * total_thickness

        # 注意：CreateExtrusion 对这种“平面闭合截面沿直线方向挤出”更稳定
        extrusion_srf = rg.Surface.CreateExtrusion(self.SectionNeg, extrude_vec)
        if extrusion_srf is None:
            raise Exception("Surface.CreateExtrusion 失败。")

        extrude_brep = rg.Brep.CreateFromSurface(extrusion_srf)
        if extrude_brep is None:
            raise Exception("Brep.CreateFromSurface 失败。")

        # 先保留一个中间对象，便于开发模式查看
        self.LoftBrep = extrude_brep

        # 封平面孔，形成闭合实体
        capped = extrude_brep.CapPlanarHoles(self._tol())
        if capped is None:
            raise Exception("CapPlanarHoles 失败，无法封闭三瓣头实体。")

        if not capped.IsSolid:
            raise Exception("CapPlanarHoles 后结果不是封闭实体。")

        self.SolidBrep = capped

        # 这里的端盖不再来自 CreatePlanarBreps，但为了兼容开发模式输出名，仍尽量补上
        cap_neg = rg.Brep.CreatePlanarBreps(self.SectionNeg, self._tol())
        cap_pos = rg.Brep.CreatePlanarBreps(self.SectionPos, self._tol())
        self.CapNeg = cap_neg[0] if cap_neg and len(cap_neg) > 0 else None
        self.CapPos = cap_pos[0] if cap_pos and len(cap_pos) > 0 else None

        self.Log.append("[OK] 已通过挤出 + 封盖构建三瓣头实体 SolidBrep。")

    def _build_named_faces(self):
        self.FacePlane_OA = self._side_face_plane(self.O, self.A)
        self.FacePlane_OB = self._side_face_plane(self.O, self.B)

        oa_face_data = self._make_ordered_side_face(self.O, self.A)
        self.OAFace = oa_face_data["FaceBrep"]
        self.OAFaceCornerPoints = oa_face_data["CornerPoints"]
        self.OAFaceEdgeMidPoints = oa_face_data["EdgeMidPoints"]
        self.OAFacePlaneList = oa_face_data["PlaneList"]

        ob_face_data = self._make_ordered_side_face(self.O, self.B)
        self.OBFace = ob_face_data["FaceBrep"]
        self.OBFaceCornerPoints = ob_face_data["CornerPoints"]
        self.OBFaceEdgeMidPoints = ob_face_data["EdgeMidPoints"]
        self.OBFacePlaneList = ob_face_data["PlaneList"]

        self.Log.append("[OK] 已生成 O-A 与 O-B 两个指定侧面的固定顺序输出。")

    def _publish(self, result):
        result.SolidBrep = getattr(self, "SolidBrep", None)

        result.OAFace = getattr(self, "OAFace", None)
        result.OAFaceCornerPoints = getattr(self, "OAFaceCornerPoints", [])
        result.OAFaceEdgeMidPoints = getattr(self, "OAFaceEdgeMidPoints", [])
        result.OAFacePlaneList = getattr(self, "OAFacePlaneList", [])

        result.OBFace = getattr(self, "OBFace", None)
        result.OBFaceCornerPoints = getattr(self, "OBFaceCornerPoints", [])
        result.OBFaceEdgeMidPoints = getattr(self, "OBFaceEdgeMidPoints", [])
        result.OBFacePlaneList = getattr(self, "OBFacePlaneList", [])

        result.OOut = getattr(self, "O", None)
        result.AOut = getattr(self, "A", None)
        result.BOut = getattr(self, "B", None)
        result.OPrimeOut = getattr(self, "OPrime", None)
        result.Log = list(self.Log)

        names = [
            "PBase", "ABLine", "SectionCurve", "SectionSegments",
            "Arc_BIF", "Arc_FHD", "Arc_DEC", "Arc_CJG", "Arc_GKA",
            "C", "D", "E", "F", "G", "H", "I", "J", "K",
            "EPrime", "IPrime", "HPrime", "JPrime", "KPrime",
            "SectionNeg", "SectionPos", "LoftBrep", "CapNeg", "CapPos",
            "FacePlane_OA", "FacePlane_OB"
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

    def _arc3(self, p0, p1, p2, name):
        arc = rg.Arc(p0, p1, p2)
        if not arc.IsValid:
            raise Exception("三点弧 {} 构建失败。".format(name))
        return rg.ArcCurve(arc)

    def _duplicate_and_translate(self, curve, vec):
        dup = curve.DuplicateCurve()
        xf = rg.Transform.Translation(vec)
        dup.Transform(xf)
        return dup

    @staticmethod
    def _midpoint(a, b):
        return rg.Point3d(
            (a.X + b.X) * 0.5,
            (a.Y + b.Y) * 0.5,
            (a.Z + b.Z) * 0.5
        )

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
        _AToOPrime = AToOPrime
    except:
        _AToOPrime = None

    try:
        _EOffset = EOffset
    except:
        _EOffset = None

    try:
        _PetalOffset = PetalOffset
    except:
        _PetalOffset = None

    try:
        _HalfThicknessX = HalfThicknessX
    except:
        _HalfThicknessX = None

    try:
        _Refresh = Refresh
    except:
        _Refresh = False

    solver = SanBanTouSolver(
        O=_O,
        P=_P,
        Height_OOPrime=_Height_OOPrime,
        AToOPrime=_AToOPrime,
        EOffset=_EOffset,
        PetalOffset=_PetalOffset,
        HalfThicknessX=_HalfThicknessX,
        Refresh=_Refresh,
        ghenv=ghenv
    )
    solver.run()

    # 正式输出
    SolidBrep = solver.SolidBrep

    OAFace = solver.OAFace
    OAFaceCornerPoints = solver.OAFaceCornerPoints
    OAFaceEdgeMidPoints = solver.OAFaceEdgeMidPoints
    OAFacePlaneList = solver.OAFacePlaneList

    OBFace = solver.OBFace
    OBFaceCornerPoints = solver.OBFaceCornerPoints
    OBFaceEdgeMidPoints = solver.OBFaceEdgeMidPoints
    OBFacePlaneList = solver.OBFacePlaneList

    OOut = solver.OOut
    AOut = solver.AOut
    BOut = solver.BOut
    OPrimeOut = solver.OPrimeOut

    Log = solver.Log

    # 开发模式：按需在 GH 中添加同名输出端即可看到内部数据
    try:
        PBase = solver.PBase
        ABLine = solver.ABLine
        SectionCurve = solver.SectionCurve
        SectionSegments = solver.SectionSegments

        Arc_BIF = solver.Arc_BIF
        Arc_FHD = solver.Arc_FHD
        Arc_DEC = solver.Arc_DEC
        Arc_CJG = solver.Arc_CJG
        Arc_GKA = solver.Arc_GKA

        C = solver.C
        D = solver.D
        E = solver.E
        F = solver.F
        G = solver.G
        H = solver.H
        I = solver.I
        J = solver.J
        K = solver.K

        EPrime = solver.EPrime
        IPrime = solver.IPrime
        HPrime = solver.HPrime
        JPrime = solver.JPrime
        KPrime = solver.KPrime

        SectionNeg = solver.SectionNeg
        SectionPos = solver.SectionPos
        LoftBrep = solver.LoftBrep
        CapNeg = solver.CapNeg
        CapPos = solver.CapPos

        FacePlane_OA = solver.FacePlane_OA
        FacePlane_OB = solver.FacePlane_OB
    except:
        pass
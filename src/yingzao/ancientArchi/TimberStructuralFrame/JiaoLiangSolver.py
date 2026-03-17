# -*- coding: utf-8 -*-
"""
JiaoLiangSolver.py
角梁 一体化组件 · Step 1（大角梁二维定位） + Step 2（子角梁二维截面） + Step 3（隱角梁二维截面） + Step 4（截面双侧偏移放样成体）

用途:
    在 GhPython 中完成“角梁”体系中的：
        1) 大角梁二维定位几何
        2) 子角梁二维截面几何（仍位于参考平面 P' 内）
        3) 隱角梁二维截面几何（仍位于参考平面 P' 内）
        4) 将大角梁、子角梁、隱角梁截面，沿垂直于参考平面 P' 的方向双侧偏移，
           再以两侧偏移后的截面放样成体并封面

新增（开发模式输出）:
    1) DaJiaoSolid 中 C-D 所在面：
        - 面对象
        - 边线中点列表（固定顺序）
        - 四角点列表（固定顺序）
        - 过中点与四角点的参考平面列表（固定顺序）
    2) DaJiaoSolid 中 C'-D' 所在面：
        - 面对象
        - 边线中点列表（固定顺序）
        - 四角点列表（固定顺序）
        - 过中点与四角点的参考平面列表（固定顺序）
    3) ChildSolid 中 I-H 所在面：
        - 面对象
        - 边线中点列表（固定顺序）
        - 四角点列表（固定顺序）
        - 过中点与四角点的参考平面列表（固定顺序）

固定顺序定义（所有“指定面”统一）:
    对于原截面上的一条基准边 start -> end，沿 P'.ZAxis 双侧偏移形成四边形面，
    其四角点固定顺序为：
        [neg_start, neg_end, pos_end, pos_start]

    四条边固定顺序为：
        0: neg_start -> neg_end
        1: neg_end   -> pos_end
        2: pos_end   -> pos_start
        3: pos_start -> neg_start

    四边中点列表顺序与边顺序一致。
    参考平面列表固定为：
        [edge_mid_0_plane, edge_mid_1_plane, edge_mid_2_plane, edge_mid_3_plane,
         corner_0_plane,  corner_1_plane,  corner_2_plane,  corner_3_plane]

当前版本依据用户描述，完成以下四部分：

一、大角梁几何：
    1) 建立参考平面 P'
    2) 绘制以 O 为圆心、Diameter 为直径的圆
    3) 由点 A 所在竖向线（P' 的 Y 轴方向）向上求点 B
    4) 过点 B 作圆的切线，切点为 C'
    5) 过点 A 作与切线平行的下边线
    6) 由 BeamWidth 确定 D' 与上、下两条平行边间距
    7) 新增输入参数 ExtendAtPrimeLength：
         将 C-C' 沿 C->C' 的当前直线方向继续延长指定距离，得 C''；
         将 D-D' 沿 D->D' 的当前直线方向继续延长指定距离，得 D''
    8) 由 TailLength 从 A 延长至 D
    9) 由上、下边平行、端头边垂直关系求得 C
   10) 之后所有与 C'、D' 相关的构建，均改以 C''、D'' 为参照
   11) 输出矩形 C''-C-D-D''-C''

二、子角梁几何：
    1) 输入点 E（角柱中点）；若 E 不在 P' 上，先垂直投影到 P' 上
    2) 沿 P'.Y 方向将 E 投影到直线段 C''-C 上，得点 E'（输出参数）
    3) 延长线段 D-C，得点 F，满足 C-F = ChildWidth（子角梁的廣）
    4) 连接 E' 与 F，得直线 E'-F；过 C 作平行于 P'.Y 的直线，与 E'-F 相交得 G
    5) 增加输入参数：
         - CHPrimeLength：C-H' 的长度，且 C-H' 是 C''-C 的延长线
         - HPrimeHLength：H'-H 的长度，且 H'-H ⟂ C'-C
       由此先求 H'，再求 H，并连接 C-H
    6) 过点 G 作直线 G-I，使其平行于直线 C-H；
       再由点 H 向 G-I 作垂线，垂足为 I。
       故 I-H 同时垂直于直线 C-H 与直线 G-I
    7) 用点 E'、G、I、H、C 连为子角梁截面线，即：
       E'-G-I-H-C-E'（输出参数）

三、隱角梁几何：
    1) 延 D''-C''，以 C'' 为起点，得点 J，满足 C''-J = HiddenLength
    2) 连接点 C''、J、E'，得隱角梁截面：
       C''-J-E'-C''（输出参数）

四、截面双侧偏移放样成体：
    1) 对大角梁、子角梁、隱角梁截面，分别沿垂直于参考平面 P' 的方向偏移
    2) 偏移方式为：
         - 向 +P'.ZAxis 方向平移 thickness / 2
         - 向 -P'.ZAxis 方向平移 thickness / 2
       则两侧偏移后的截面之间距离 = 对应梁厚（输入端参数）
    3) 以两侧偏移后的截面进行 Loft，得到侧壁放样面
    4) 对两侧偏移后的截面分别创建封面（正侧封面、负侧封面）
    5) 将“侧壁放样面 + 两端封面”分别组合为各自完整封闭体
    6) 输出三类梁的体对象：
         - DaJiaoSolid
         - ChildSolid
         - HiddenSolid

本版关于 P' 的定义:
    - P'.Origin = O
    - P'.YAxis  = 参考平面 P 的 ZAxis
    - P' 过直线段 O-A
    - 因此 P'.XAxis 取为：
        将 OA 向量投影到垂直于 P.ZAxis 的平面后的方向
    - 再由叉积得到 P'.ZAxis

说明:
    1) 大角梁部分仍采用：
        BeamWidth = C'-D' = C-D
        TailLength = A-D
    2) 子角梁部分中：
        - H' 位于直线 C''-C 从 C 向外的延长线上
        - H 从 H' 沿垂直于 C'-C 的方向偏移 HPrimeHLength 得到
        - 当前默认偏移方向取使 H 相对 H' 位于“P' 2D 坐标中更高”的一侧，
          即与示意图一致的上侧法向
    3) 隱角梁部分中：
        - J 位于 D''-C'' 的延长线上，从 C'' 沿 D''->C'' 的方向继续延长
        - E' 复用子角梁步骤 2 中求得的点
        - 若未输入 E，则无法构建隱角梁
    4) 实体化部分中：
        - 三种梁的厚度分别独立输入
        - 厚度为 0 或未输入时，对应实体不构建
        - 实体通过“平移两侧轮廓 + Loft + 正负两端封面 + Join”生成
        - DaJiaoSideLoft / ChildSideLoft / HiddenSideLoft 表示“侧壁放样面”
        - DaJiaoCapPos / DaJiaoCapNeg 等表示两端封面
        - DaJiaoSolid / ChildSolid / HiddenSolid 表示完整封闭体

输入（GhPython 建议设置）:
    O : rg.Point3d
        Access = Item
        TypeHint = Point3d
        大角梁起算圆心点 / 参考原点。

    A : rg.Point3d
        Access = Item
        TypeHint = Point3d
        大角梁下边控制点。B 将在过 A 且沿 P'.Y 方向的竖线上求得。

    Diameter : float
        Access = Item
        TypeHint = float
        过 O 所作圆的直径。

    BeamWidth : float
        Access = Item
        TypeHint = float
        大角梁带状矩形宽度，即 C'-D' = C-D。

    TailLength : float
        Access = Item
        TypeHint = float
        从 A 沿梁身方向延长到 D 的长度，即 A-D。

    ExtendAtPrimeLength : float
        Access = Item
        TypeHint = float
        将 C-C' 沿 C->C' 当前直线方向、D-D' 沿 D->D' 当前直线方向继续延长的距离。
        延长后分别得到 C''、D''。
        后续所有与 C'、D' 相关的构建均以 C''、D'' 为参照。

    E : rg.Point3d
        Access = Item
        TypeHint = Point3d
        角柱中点。若不在 P' 上，将先垂直投影到 P' 上。

    ChildWidth : float
        Access = Item
        TypeHint = float
        子角梁的“廣”，即 C-F 的长度。

    CHPrimeLength : float
        Access = Item
        TypeHint = float
        C-H' 的长度。
        H' 位于 C'-C 的延长线上，从 C 沿 C'-C 方向继续延伸。

    HPrimeHLength : float
        Access = Item
        TypeHint = float
        H'-H 的长度，且 H'-H 垂直于 C'-C。

    HiddenLength : float
        Access = Item
        TypeHint = float
        隱角梁中 C'-J 的长度。
        J 位于 D'-C' 的延长线上，从 C' 沿 D'->C' 方向继续延伸。

    DaJiaoThickness : float
        Access = Item
        TypeHint = float
        大角梁厚度。两侧偏移后的大角梁截面之间距离。

    ChildThickness : float
        Access = Item
        TypeHint = float
        子角梁厚度。两侧偏移后的子角梁截面之间距离。

    HiddenThickness : float
        Access = Item
        TypeHint = float
        隱角梁厚度。两侧偏移后的隱角梁截面之间距离。

    P : rg.Plane
        Access = Item
        TypeHint = Plane
        参考平面。可为空。
        若为空，默认使用 WorldXY，但其原点不直接沿用，而是以 O 为原点重建。
        本版中 P' 的建立规则为：
            P'.Origin = O
            P'.YAxis  = P.ZAxis
            P' 过 O-A
            P'.XAxis  = OA 在垂直于 P.ZAxis 的平面上的投影方向

    Refresh : bool
        Access = Item
        TypeHint = bool
        是否执行重算。

正式输出（建议保留以下 10 个输出端）:
    PPrime : rg.Plane
        大角梁二维作图参考平面 P'

    Circle : rg.Circle
        过 O、直径为 Diameter 的圆

    Rect : rg.Curve
        大角梁矩形 C''-C-D-D''-C'' 的 NurbsCurve

    EPrime : rg.Point3d
        子角梁步骤 2 求得的点 E'

    ChildProfile : rg.Curve
        子角梁截面线 E'-G-I-H-C-E' 的 NurbsCurve

    J : rg.Point3d
        隱角梁步骤 1 求得的点 J

    HiddenProfile : rg.Curve
        隱角梁截面线 C''-J-E'-C'' 的 NurbsCurve

    DaJiaoSolid : rg.Brep
        大角梁完整封闭体

    ChildSolid : rg.Brep
        子角梁完整封闭体

    HiddenSolid : rg.Brep
        隱角梁完整封闭体

开发模式可选输出（按需在 GH 中增加同名输出端即可看到内部数据）:
    O2D : rg.Point3d
    A2D : rg.Point3d
    B : rg.Point3d
    CPrime : rg.Point3d
    DPrime : rg.Point3d
    CDoublePrime : rg.Point3d
    DDoublePrime : rg.Point3d
    C : rg.Point3d
    D : rg.Point3d
    UpperLine : rg.Line
    LowerLine : rg.Line
    VerticalAB : rg.Line
    RectPolyline : rg.Polyline
    RectBrep : rg.Brep
    TangentPoint2D : rg.Point3d
    B2D : rg.Point3d
    NormalVec : rg.Vector3d
    TangentVec : rg.Vector3d

    EProj : rg.Point3d
    EProj2D : rg.Point3d
    EPrime2D : rg.Point3d
    F : rg.Point3d
    G : rg.Point3d
    HPrime : rg.Point3d
    H : rg.Point3d
    I : rg.Point3d
    ChildGuideLine : rg.Line
    ChildVerticalAtC : rg.Line
    CHLine : rg.Line
    GHLine : rg.Line
    IHLine : rg.Line
    ChildPolyline : rg.Polyline
    ChildBrep : rg.Brep

    J2D : rg.Point3d
    HiddenEdgeLine : rg.Line
    HiddenPolyline : rg.Polyline
    HiddenBrep : rg.Brep

    DaJiaoProfilePos : rg.Curve
    DaJiaoProfileNeg : rg.Curve
    ChildProfilePos : rg.Curve
    ChildProfileNeg : rg.Curve
    HiddenProfilePos : rg.Curve
    HiddenProfileNeg : rg.Curve

    DaJiaoSideLoft : rg.Brep
    ChildSideLoft : rg.Brep
    HiddenSideLoft : rg.Brep

    DaJiaoCapPos : rg.Brep
    DaJiaoCapNeg : rg.Brep
    ChildCapPos : rg.Brep
    ChildCapNeg : rg.Brep
    HiddenCapPos : rg.Brep
    HiddenCapNeg : rg.Brep

    # 新增：DaJiaoSolid 中 C-D 所在面
    DaJiaoFace_CD : rg.Brep
    DaJiaoFace_CD_CornerPoints : list[rg.Point3d]
    DaJiaoFace_CD_EdgeMidPoints : list[rg.Point3d]
    DaJiaoFace_CD_PlaneList : list[rg.Plane]

    # 新增：DaJiaoSolid 中 CDoublePrime-DDoublePrime 所在面（兼容沿用旧输出名）
    DaJiaoFace_CPrimeDPrime : rg.Brep
    DaJiaoFace_CPrimeDPrime_CornerPoints : list[rg.Point3d]
    DaJiaoFace_CPrimeDPrime_EdgeMidPoints : list[rg.Point3d]
    DaJiaoFace_CPrimeDPrime_PlaneList : list[rg.Plane]

    # 新增：ChildSolid 中 I-H 所在面
    ChildFace_IH : rg.Brep
    ChildFace_IH_CornerPoints : list[rg.Point3d]
    ChildFace_IH_EdgeMidPoints : list[rg.Point3d]
    ChildFace_IH_PlaneList : list[rg.Plane]

    Log : list[str]
"""

import math
import Rhino.Geometry as rg


# ======================================================================
# 工具类：平面 2D / 3D 映射
# ======================================================================

class Plane2DMapper(object):
    """在指定平面中进行 2D <-> 3D 映射。"""

    def __init__(self, plane):
        self.plane = plane

    def world_to_plane_pt(self, pt):
        ok, u, v = self.plane.ClosestParameter(pt)
        if not ok:
            raise ValueError("无法将点映射到参考平面。")
        return rg.Point3d(u, v, 0.0)

    def plane_to_world_pt(self, pt2):
        return self.plane.PointAt(pt2.X, pt2.Y)

    def plane_vec_to_world_vec(self, vec2):
        return self.plane.XAxis * vec2.X + self.plane.YAxis * vec2.Y

    def distance_to_plane_signed(self, pt):
        return self.plane.DistanceTo(pt)


# ======================================================================
# 二维几何工具
# ======================================================================

class Geo2D(object):

    @staticmethod
    def dot(v1, v2):
        return v1.X * v2.X + v1.Y * v2.Y

    @staticmethod
    def cross(v1, v2):
        return v1.X * v2.Y - v1.Y * v2.X

    @staticmethod
    def vec(a, b):
        return rg.Vector3d(b.X - a.X, b.Y - a.Y, 0.0)

    @staticmethod
    def add_pt_vec(p, v, s=1.0):
        return rg.Point3d(p.X + v.X * s, p.Y + v.Y * s, 0.0)

    @staticmethod
    def length(v):
        return math.sqrt(v.X * v.X + v.Y * v.Y)

    @staticmethod
    def unitize(v):
        l = Geo2D.length(v)
        if l <= 1e-12:
            raise ValueError("二维向量长度过小，无法单位化。")
        return rg.Vector3d(v.X / l, v.Y / l, 0.0)

    @staticmethod
    def perp_left(v):
        return rg.Vector3d(-v.Y, v.X, 0.0)

    @staticmethod
    def line_intersection(p1, d1, p2, d2):
        """
        二维直线交点：
            L1 = p1 + t*d1
            L2 = p2 + s*d2
        返回:
            (ok, pt, t, s)
        """
        den = Geo2D.cross(d1, d2)
        if abs(den) <= 1e-12:
            return False, None, None, None

        p21 = Geo2D.vec(p1, p2)
        t = Geo2D.cross(p21, d2) / den
        s = Geo2D.cross(p21, d1) / den
        pt = Geo2D.add_pt_vec(p1, d1, t)
        return True, pt, t, s

    @staticmethod
    def project_point_to_line(pt, line_pt, line_dir):
        """
        点到二维直线投影
        """
        d = Geo2D.unitize(line_dir)
        v = Geo2D.vec(line_pt, pt)
        t = Geo2D.dot(v, d)
        foot = Geo2D.add_pt_vec(line_pt, d, t)
        return foot, t


# ======================================================================
# 三维放样实体工具
# ======================================================================

class SolidBuilder(object):
    """
    将位于某平面内的闭合截面曲线，沿平面法向双侧偏移后，通过 loft + 正负封面 + Join 生成完整封闭体。
    """

    @staticmethod
    def duplicate_curve(curve):
        if curve is None:
            return None
        return curve.DuplicateCurve()

    @staticmethod
    def translated_curve(curve, vec):
        if curve is None:
            return None
        crv = curve.DuplicateCurve()
        xf = rg.Transform.Translation(vec)
        crv.Transform(xf)
        return crv

    @staticmethod
    def create_planar_cap(curve, tol):
        if curve is None:
            return None
        breps = rg.Brep.CreatePlanarBreps(curve, tol)
        if breps and len(breps) > 0:
            return breps[0]
        return None

    @staticmethod
    def _try_join_to_closed_brep(parts, tol):
        if not parts:
            return None

        joined = rg.Brep.JoinBreps(parts, tol)
        if joined and len(joined) > 0:
            # 优先返回 solid
            for b in joined:
                try:
                    if b is not None and b.IsSolid:
                        return b
                except:
                    pass

            # 若 join 后仍非 solid，尝试逐个 CapPlanarHoles
            for b in joined:
                try:
                    if b is not None:
                        capped = b.CapPlanarHoles(tol)
                        if capped is not None and capped.IsSolid:
                            return capped
                except:
                    pass

            # 再退一步，返回第一个 join 结果
            return joined[0]

        return None

    @staticmethod
    def build_solid_from_profile(profile_curve, ref_plane, thickness, tol=0.01):
        """
        输入:
            profile_curve : 平面内闭合曲线
            ref_plane     : 参考平面 P'
            thickness     : 总厚度（两侧曲线间距）
        输出:
            dict{
                "pos_curve": rg.Curve,
                "neg_curve": rg.Curve,
                "side_loft": rg.Brep,
                "cap_pos": rg.Brep,
                "cap_neg": rg.Brep,
                "solid": rg.Brep
            }
        """
        result = {
            "pos_curve": None,
            "neg_curve": None,
            "side_loft": None,
            "cap_pos": None,
            "cap_neg": None,
            "solid": None
        }

        if profile_curve is None:
            return result

        if thickness is None:
            return result

        thickness = float(thickness)
        if thickness <= 0:
            return result

        if ref_plane is None:
            return result

        n = rg.Vector3d(ref_plane.ZAxis)
        if not n.Unitize():
            return result

        half = thickness * 0.5
        pos_vec = n * half
        neg_vec = n * (-half)

        pos_curve = SolidBuilder.translated_curve(profile_curve, pos_vec)
        neg_curve = SolidBuilder.translated_curve(profile_curve, neg_vec)

        result["pos_curve"] = pos_curve
        result["neg_curve"] = neg_curve

        # 侧壁 loft
        lofts = rg.Brep.CreateFromLoft(
            [neg_curve, pos_curve],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )

        side_loft = None
        if lofts and len(lofts) > 0:
            side_loft = lofts[0]
        result["side_loft"] = side_loft

        # 正负封面
        cap_neg = SolidBuilder.create_planar_cap(neg_curve, tol)
        cap_pos = SolidBuilder.create_planar_cap(pos_curve, tol)

        result["cap_neg"] = cap_neg
        result["cap_pos"] = cap_pos

        # 组合为完整封闭体
        parts = []
        if side_loft is not None:
            parts.append(side_loft)
        if cap_neg is not None:
            parts.append(cap_neg)
        if cap_pos is not None:
            parts.append(cap_pos)

        solid = SolidBuilder._try_join_to_closed_brep(parts, tol)

        # 兜底：若未形成完整体，但 side_loft 可封孔，则尝试
        if solid is None and side_loft is not None:
            try:
                capped = side_loft.CapPlanarHoles(tol)
                if capped is not None:
                    solid = capped
            except:
                pass

        result["solid"] = solid
        return result


# ======================================================================
# 指定侧面固定顺序数据提取工具
# ======================================================================

class FaceFeatureBuilder(object):
    """
    通过“截面上一条基准边 + 厚度 + 参考平面法向”，稳定构造对应侧面数据。
    不依赖 Brep 面索引，便于后续固定调用。
    """

    @staticmethod
    def midpoint(a, b):
        return rg.Point3d(
            0.5 * (a.X + b.X),
            0.5 * (a.Y + b.Y),
            0.5 * (a.Z + b.Z)
        )

    @staticmethod
    def build_face_from_profile_edge(start_pt, end_pt, ref_plane, thickness, tol=0.01):
        """
        输入:
            start_pt, end_pt : 截面上一条边的两个端点（世界坐标）
            ref_plane        : P'
            thickness        : 对应实体厚度
        输出:
            dict{
                "face_brep": rg.Brep,
                "corner_points": list[rg.Point3d],  # [neg_start, neg_end, pos_end, pos_start]
                "edge_midpoints": list[rg.Point3d], # 4个，固定顺序
                "plane_list": list[rg.Plane]        # 8个，先中点后角点，固定顺序
            }
        """
        result = {
            "face_brep": None,
            "corner_points": [],
            "edge_midpoints": [],
            "plane_list": []
        }

        if start_pt is None or end_pt is None or ref_plane is None or thickness is None:
            return result

        thickness = float(thickness)
        if thickness <= 0:
            return result

        z = rg.Vector3d(ref_plane.ZAxis)
        if not z.Unitize():
            return result

        edge_x = end_pt - start_pt
        if edge_x.Length <= 1e-12:
            return result
        edge_x.Unitize()

        # 面平面局部坐标：
        # X = 基准边方向
        # Y = +P'.ZAxis
        # Z = X × Y
        face_y = rg.Vector3d(z)
        face_z = rg.Vector3d.CrossProduct(edge_x, face_y)
        if face_z.Length <= 1e-12:
            return result
        face_z.Unitize()

        half = 0.5 * thickness
        neg_vec = face_y * (-half)
        pos_vec = face_y * (half)

        neg_start = rg.Point3d(start_pt)
        neg_start += neg_vec

        neg_end = rg.Point3d(end_pt)
        neg_end += neg_vec

        pos_end = rg.Point3d(end_pt)
        pos_end += pos_vec

        pos_start = rg.Point3d(start_pt)
        pos_start += pos_vec

        corners = [neg_start, neg_end, pos_end, pos_start]

        mids = [
            FaceFeatureBuilder.midpoint(corners[0], corners[1]),
            FaceFeatureBuilder.midpoint(corners[1], corners[2]),
            FaceFeatureBuilder.midpoint(corners[2], corners[3]),
            FaceFeatureBuilder.midpoint(corners[3], corners[0]),
        ]

        # 平面列表：先4个边中点，再4个角点
        plane_list = []
        for p in mids:
            plane_list.append(rg.Plane(p, edge_x, face_y))
        for p in corners:
            plane_list.append(rg.Plane(p, edge_x, face_y))

        poly = rg.Polyline([corners[0], corners[1], corners[2], corners[3], corners[0]])
        face_curve = poly.ToNurbsCurve()
        face_brep = None
        breps = rg.Brep.CreatePlanarBreps(face_curve, tol)
        if breps and len(breps) > 0:
            face_brep = breps[0]

        result["face_brep"] = face_brep
        result["corner_points"] = corners
        result["edge_midpoints"] = mids
        result["plane_list"] = plane_list
        return result


# ======================================================================
# 结果容器
# ======================================================================

class JiaoLiangResult(object):
    """角梁结果容器。"""

    def __init__(self):
        # 大角梁核心
        self.PPrime = None
        self.Circle = None

        self.O2D = None
        self.A2D = None
        self.B2D = None
        self.CPrime2D = None
        self.DPrime2D = None
        self.CDoublePrime2D = None
        self.DDoublePrime2D = None
        self.C2D = None
        self.D2D = None

        self.B = None
        self.CPrime = None
        self.DPrime = None
        self.CDoublePrime = None
        self.DDoublePrime = None
        self.C = None
        self.D = None

        self.UpperLine = None
        self.LowerLine = None
        self.VerticalAB = None

        self.RectPolyline = None
        self.RectNurbs = None
        self.RectBrep = None

        self.NormalVec = None
        self.TangentVec = None

        # 子角梁
        self.EProj = None
        self.EProj2D = None
        self.EPrime = None
        self.EPrime2D = None
        self.F = None
        self.F2D = None
        self.G = None
        self.G2D = None
        self.HPrime = None
        self.HPrime2D = None
        self.H = None
        self.H2D = None
        self.I = None
        self.I2D = None

        self.ChildGuideLine = None     # E'-F
        self.ChildVerticalAtC = None   # 过 C 的 P'.Y 方向线
        self.CHLine = None
        self.GHLine = None
        self.IHLine = None
        self.ChildPolyline = None
        self.ChildNurbs = None
        self.ChildBrep = None

        # 隱角梁
        self.J = None
        self.J2D = None
        self.HiddenEdgeLine = None     # C'-J
        self.HiddenPolyline = None
        self.HiddenNurbs = None
        self.HiddenBrep = None

        # 实体
        self.DaJiaoProfilePos = None
        self.DaJiaoProfileNeg = None
        self.ChildProfilePos = None
        self.ChildProfileNeg = None
        self.HiddenProfilePos = None
        self.HiddenProfileNeg = None

        self.DaJiaoSideLoft = None
        self.ChildSideLoft = None
        self.HiddenSideLoft = None

        self.DaJiaoCapPos = None
        self.DaJiaoCapNeg = None
        self.ChildCapPos = None
        self.ChildCapNeg = None
        self.HiddenCapPos = None
        self.HiddenCapNeg = None

        self.DaJiaoSolid = None
        self.ChildSolid = None
        self.HiddenSolid = None

        # 新增：DaJiaoSolid 中 C-D 所在面
        self.DaJiaoFace_CD = None
        self.DaJiaoFace_CD_CornerPoints = []
        self.DaJiaoFace_CD_EdgeMidPoints = []
        self.DaJiaoFace_CD_PlaneList = []

        # 新增：DaJiaoSolid 中 CDoublePrime-DDoublePrime 所在面（兼容沿用旧输出名）
        self.DaJiaoFace_CPrimeDPrime = None
        self.DaJiaoFace_CPrimeDPrime_CornerPoints = []
        self.DaJiaoFace_CPrimeDPrime_EdgeMidPoints = []
        self.DaJiaoFace_CPrimeDPrime_PlaneList = []

        # 新增：ChildSolid 中 I-H 所在面
        self.ChildFace_IH = None
        self.ChildFace_IH_CornerPoints = []
        self.ChildFace_IH_EdgeMidPoints = []
        self.ChildFace_IH_PlaneList = []

        self.Log = []


# ======================================================================
# 大角梁 + 子角梁 + 隱角梁构建器
# ======================================================================

class JiaoLiangBuilder(object):
    """
    角梁二维定位几何构建器：
        - 大角梁
        - 子角梁
        - 隱角梁
        - 三类梁截面双侧偏移放样实体
        - 指定侧面固定顺序提取
    """

    def __init__(
        self,
        O,
        A,
        diameter,
        beam_width,
        tail_length,
        extend_at_prime_length=0.0,
        E=None,
        child_width=None,
        chprime_length=None,
        hprimeh_length=None,
        hidden_length=None,
        dajiao_thickness=None,
        child_thickness=None,
        hidden_thickness=None,
        ref_plane=None
    ):
        self.O = O
        self.A = A
        self.diameter = float(diameter)
        self.beam_width = float(beam_width)
        self.tail_length = float(tail_length)
        self.extend_at_prime_length = 0.0 if extend_at_prime_length is None else float(extend_at_prime_length)

        self.E = E
        self.child_width = None if child_width is None else float(child_width)
        self.chprime_length = None if chprime_length is None else float(chprime_length)
        self.hprimeh_length = None if hprimeh_length is None else float(hprimeh_length)
        self.hidden_length = None if hidden_length is None else float(hidden_length)

        self.dajiao_thickness = None if dajiao_thickness is None else float(dajiao_thickness)
        self.child_thickness = None if child_thickness is None else float(child_thickness)
        self.hidden_thickness = None if hidden_thickness is None else float(hidden_thickness)

        self.ref_plane = ref_plane
        self.Log = []

        self._validate_inputs()

    def _validate_inputs(self):
        if self.O is None:
            raise ValueError("输入 O 不能为空。")
        if self.A is None:
            raise ValueError("输入 A 不能为空。")
        if self.diameter <= 0:
            raise ValueError("Diameter 必须 > 0。")
        if self.beam_width <= 0:
            raise ValueError("BeamWidth 必须 > 0。")
        if self.tail_length < 0:
            raise ValueError("TailLength 必须 >= 0。")
        if self.extend_at_prime_length < 0:
            raise ValueError("ExtendAtPrimeLength 必须 >= 0。")

        if self.E is not None:
            if self.child_width is None:
                raise ValueError("已输入 E 时，必须同时输入 ChildWidth。")
            if self.chprime_length is None:
                raise ValueError("已输入 E 时，必须同时输入 CHPrimeLength。")
            if self.hprimeh_length is None:
                raise ValueError("已输入 E 时，必须同时输入 HPrimeHLength。")

            if self.child_width <= 0:
                raise ValueError("ChildWidth 必须 > 0。")
            if self.chprime_length < 0:
                raise ValueError("CHPrimeLength 必须 >= 0。")
            if self.hprimeh_length < 0:
                raise ValueError("HPrimeHLength 必须 >= 0。")

        # 隱角梁依赖 E'，故需 E 与 HiddenLength 同时具备
        if self.hidden_length is not None:
            if self.hidden_length < 0:
                raise ValueError("HiddenLength 必须 >= 0。")
            if self.E is None:
                raise ValueError("已输入 HiddenLength 时，必须同时输入 E，以便先求得 E'。")

        # 厚度校验
        if self.dajiao_thickness is not None and self.dajiao_thickness < 0:
            raise ValueError("DaJiaoThickness 必须 >= 0。")
        if self.child_thickness is not None and self.child_thickness < 0:
            raise ValueError("ChildThickness 必须 >= 0。")
        if self.hidden_thickness is not None and self.hidden_thickness < 0:
            raise ValueError("HiddenThickness 必须 >= 0。")

        if self.hidden_thickness is not None and self.hidden_thickness > 0:
            if self.hidden_length is None:
                raise ValueError("已输入 HiddenThickness 时，必须同时输入 HiddenLength。")
            if self.E is None:
                raise ValueError("已输入 HiddenThickness 时，必须同时输入 E，以便先求得 E'。")

        if self.child_thickness is not None and self.child_thickness > 0:
            if self.E is None:
                raise ValueError("已输入 ChildThickness 时，必须同时输入 E，以便先构建子角梁截面。")

    def _build_base_plane(self):
        """
        构造参考平面 P：
        - 若用户未输入 P，则用 WorldXY
        - 无论如何，将原点重置到 O
        """
        if self.ref_plane is None:
            p = rg.Plane.WorldXY
            self.Log.append("[Plane] 未输入 P，使用 WorldXY。")
        else:
            p = self.ref_plane
            self.Log.append("[Plane] 使用输入参考平面 P。")

        return rg.Plane(self.O, p.XAxis, p.YAxis)

    def _project_vector_to_plane(self, vec, plane_normal):
        """
        将向量 vec 投影到法向为 plane_normal 的平面上。
        """
        n = rg.Vector3d(plane_normal)
        if not n.Unitize():
            raise ValueError("参考法向无效，无法投影向量。")

        v = rg.Vector3d(vec)
        proj = v - (v * n) * n
        return proj

    def _build_pprime(self, base_plane):
        """
        按要求建立 P'：
            - 原点 O
            - Y轴 = P.ZAxis
            - 平面过 O-A
        """
        y_axis = rg.Vector3d(base_plane.ZAxis)
        if not y_axis.Unitize():
            raise ValueError("参考平面 P 的 Z 轴无效，无法建立 P'。")

        oa = self.A - self.O
        if oa.Length <= 1e-12:
            raise ValueError("点 O 与点 A 重合，无法通过 O-A 建立参考平面 P'。")

        x_axis = self._project_vector_to_plane(oa, y_axis)

        if x_axis.Length <= 1e-12:
            raise ValueError(
                "O-A 平行于 P.ZAxis，无法唯一建立满足“Y轴=P.ZAxis 且过 O-A”的参考平面 P'。"
            )

        x_axis.Unitize()

        pprime = rg.Plane(self.O, x_axis, y_axis)
        self.Log.append("[Plane] 已按规则建立参考平面 P'：Origin=O, Y=P.ZAxis, Plane passes O-A。")
        return pprime

    def _solve_unit_normals(self, ax, ay, target_dot):
        """
        求单位法向 n=(nx,ny)，满足:
            ax*nx + ay*ny = target_dot
            nx^2 + ny^2 = 1
        """
        a_len = math.sqrt(ax * ax + ay * ay)
        if a_len < 1e-12:
            raise ValueError("A 与 O 在 P' 中重合，无法确定切线。")

        if abs(target_dot) > a_len + 1e-10:
            raise ValueError(
                "几何无解：|r - BeamWidth| > |OA在P'中的长度|，"
                "无法找到同时满足“过A作平行线”与“上边为圆切线”的法向。"
            )

        ratio = max(-1.0, min(1.0, target_dot / a_len))
        base_ang = math.atan2(ay, ax)
        alpha = math.acos(ratio)

        ang1 = base_ang + alpha
        ang2 = base_ang - alpha

        n1 = rg.Vector3d(math.cos(ang1), math.sin(ang1), 0.0)
        n2 = rg.Vector3d(math.cos(ang2), math.sin(ang2), 0.0)
        return [n1, n2]

    def _choose_upper_normal(self, normal_candidates, radius):
        """
        从两个法向候选中选“上侧切线”对应法向。
        优先规则：
            1) ny > 0
            2) 切点 y 更高
            3) 若接近，则 x 更偏左
        """
        scored = []
        for n in normal_candidates:
            cp = rg.Point3d(radius * n.X, radius * n.Y, 0.0)
            score = (
                1 if n.Y > 0 else 0,
                cp.Y,
                -cp.X
            )
            scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _build_dajiao_geometry_2d(self, mapper, res):
        """
        在 P' 二维坐标系中完成大角梁求解。
        """
        res.PPrime = mapper.plane
        r = self.diameter * 0.5
        res.Circle = rg.Circle(mapper.plane, r)
        self.Log.append("[Circle] 已建立直径为 {} 的圆。".format(self.diameter))

        O2 = rg.Point3d(0.0, 0.0, 0.0)
        A2 = mapper.world_to_plane_pt(self.A)

        res.O2D = O2
        res.A2D = A2

        ax = A2.X
        ay = A2.Y

        target_dot = r - self.beam_width
        normal_candidates = self._solve_unit_normals(ax, ay, target_dot)
        n = self._choose_upper_normal(normal_candidates, r)
        n.Unitize()

        # 切点 C'
        cprime2 = rg.Point3d(r * n.X, r * n.Y, 0.0)

        # D' 为从 C' 沿法向下移 BeamWidth
        dprime2 = rg.Point3d(
            cprime2.X - self.beam_width * n.X,
            cprime2.Y - self.beam_width * n.Y,
            0.0
        )

        # 梁身方向 t：先按未延长端点 D' 取 D'->A 方向，
        # 待 C、D 求出后，再严格沿 C->C' 与 D->D' 当前直线方向延长到 C''、D''。
        t = rg.Vector3d(A2.X - dprime2.X, A2.Y - dprime2.Y, 0.0)
        if t.Length < 1e-12:
            t = rg.Vector3d(-n.Y, n.X, 0.0)
        t.Unitize()

        # 下边末端 D：从 A 沿梁身方向延长 TailLength
        d2 = rg.Point3d(
            A2.X + self.tail_length * t.X,
            A2.Y + self.tail_length * t.Y,
            0.0
        )

        # 上边末端 C：由 D 沿法向上移 BeamWidth
        c2 = rg.Point3d(
            d2.X + self.beam_width * n.X,
            d2.Y + self.beam_width * n.Y,
            0.0
        )

        # 由输入距离分别沿“当前直线方向”继续延长：
        #   - C-C'：沿 C -> C' 方向延长到 C''
        #   - D-D'：沿 D -> D' 方向延长到 D''
        # 注意：这里不是统一沿法向 n 延长，而是严格沿各自线段当前方向延长。
        c_to_cprime_dir = Geo2D.vec(c2, cprime2)
        if c_to_cprime_dir.Length <= 1e-12:
            raise ValueError("C 与 C' 重合，无法沿 C-C' 当前方向延长到 C''。")
        c_to_cprime_dir.Unitize()

        d_to_dprime_dir = Geo2D.vec(d2, dprime2)
        if d_to_dprime_dir.Length <= 1e-12:
            # 兜底：D-D' 与 C-C' 在带状矩形中应平行，此时退回使用 C->C' 方向
            d_to_dprime_dir = rg.Vector3d(c_to_cprime_dir)
        d_to_dprime_dir.Unitize()

        cdoubleprime2 = rg.Point3d(
            cprime2.X + self.extend_at_prime_length * c_to_cprime_dir.X,
            cprime2.Y + self.extend_at_prime_length * c_to_cprime_dir.Y,
            0.0
        )
        ddoubleprime2 = rg.Point3d(
            dprime2.X + self.extend_at_prime_length * d_to_dprime_dir.X,
            dprime2.Y + self.extend_at_prime_length * d_to_dprime_dir.Y,
            0.0
        )

        # B：上切线与过 A 的竖线（x=ax）交点
        if abs(n.Y) < 1e-12:
            raise ValueError("当前解导致上切线近乎水平，无法按“过 A 竖向求 B”的方式稳定求点 B。")
        by = (r - n.X * ax) / n.Y
        b2 = rg.Point3d(ax, by, 0.0)

        # 转回 3D
        res.CPrime2D = cprime2
        res.DPrime2D = dprime2
        res.CDoublePrime2D = cdoubleprime2
        res.DDoublePrime2D = ddoubleprime2
        res.C2D = c2
        res.D2D = d2
        res.B2D = b2

        res.CPrime = mapper.plane_to_world_pt(cprime2)
        res.DPrime = mapper.plane_to_world_pt(dprime2)
        res.CDoublePrime = mapper.plane_to_world_pt(cdoubleprime2)
        res.DDoublePrime = mapper.plane_to_world_pt(ddoubleprime2)
        res.C = mapper.plane_to_world_pt(c2)
        res.D = mapper.plane_to_world_pt(d2)
        res.B = mapper.plane_to_world_pt(b2)

        # 方向向量
        res.NormalVec = mapper.plane_vec_to_world_vec(n)
        res.TangentVec = mapper.plane_vec_to_world_vec(t)

        # 线
        res.UpperLine = rg.Line(res.CDoublePrime, res.C)
        res.LowerLine = rg.Line(res.DDoublePrime, res.D)
        res.VerticalAB = rg.Line(self.A, res.B)

        # 矩形
        poly = rg.Polyline([res.CDoublePrime, res.C, res.D, res.DDoublePrime, res.CDoublePrime])
        res.RectPolyline = poly
        res.RectNurbs = poly.ToNurbsCurve()

        breps = rg.Brep.CreatePlanarBreps(res.RectNurbs)
        if breps and len(breps) > 0:
            res.RectBrep = breps[0]
        else:
            res.RectBrep = None

        self.Log.append("[DaJiao] 已求得点 B、C'、D'、C''、D''、C、D。")
        self.Log.append("[DaJiao] 已生成矩形 C''-C-D-D''-C''。")

        return res

    def _build_zijiao_geometry_2d(self, mapper, res):
        """
        在 P' 二维坐标系中完成子角梁求解。
        """
        if self.E is None:
            self.Log.append("[ZiJiao] 未输入 E，跳过子角梁几何。")
            return res

        # ----------------------------
        # 1) E 若不在 P' 上，则垂直投影到 P'
        # ----------------------------
        dist_to_p = mapper.distance_to_plane_signed(self.E)
        if abs(dist_to_p) > 1e-9:
            e_proj_world = mapper.plane.ClosestPoint(self.E)
            self.Log.append("[ZiJiao] 输入点 E 不在 P' 上，已垂直投影到 P'。")
        else:
            e_proj_world = self.E
            self.Log.append("[ZiJiao] 输入点 E 已在 P' 上。")

        e_proj2 = mapper.world_to_plane_pt(e_proj_world)
        res.EProj = e_proj_world
        res.EProj2D = e_proj2

        # 已知大角梁上边线：C'' -> C
        cp2 = res.CDoublePrime2D
        c2 = res.C2D
        d2 = res.D2D

        upper_dir = Geo2D.vec(cp2, c2)
        upper_dir_u = Geo2D.unitize(upper_dir)

        # ----------------------------
        # 2) 沿 P'.Y 方向将 E 投影到直线段 C''-C 上，得 E'
        # ----------------------------
        y_dir = rg.Vector3d(0.0, 1.0, 0.0)
        ok, eprime2, t_line, s_line = Geo2D.line_intersection(cp2, upper_dir, e_proj2, y_dir)
        if not ok:
            raise ValueError("子角梁步骤 2 失败：过 E 的 P'.Y 方向线与 C''-C 无交点。")

        if t_line < -1e-9 or t_line > 1.0 + 1e-9:
            self.Log.append(
                "[ZiJiao] 警告：E 沿 P'.Y 投影与直线 C''-C 的交点落在线段外，当前仍取该交点作为 E'。"
            )

        eprime_world = mapper.plane_to_world_pt(eprime2)
        res.EPrime2D = eprime2
        res.EPrime = eprime_world

        # ----------------------------
        # 3) 延长线段 D-C，得点 F，满足 C-F = ChildWidth
        # ----------------------------
        dc_dir = Geo2D.vec(d2, c2)   # D -> C
        dc_dir_u = Geo2D.unitize(dc_dir)
        f2 = Geo2D.add_pt_vec(c2, dc_dir_u, self.child_width)
        f_world = mapper.plane_to_world_pt(f2)

        res.F2D = f2
        res.F = f_world

        # ----------------------------
        # 4) 连接 E' 和 F；过 C 作 P'.Y 方向线，与 E'-F 相交得 G
        # ----------------------------
        ef_dir = Geo2D.vec(eprime2, f2)
        ok, g2, t_ef, s_vert = Geo2D.line_intersection(eprime2, ef_dir, c2, y_dir)
        if not ok:
            raise ValueError("子角梁步骤 4 失败：E'-F 与过 C 的 P'.Y 方向线平行或重合。")

        g_world = mapper.plane_to_world_pt(g2)
        res.G2D = g2
        res.G = g_world

        # ----------------------------
        # 5) 求 H'、H
        # ----------------------------
        hprime2 = Geo2D.add_pt_vec(c2, upper_dir_u, self.chprime_length)

        # 垂直于 C''-C 的上侧法向
        perp_u = Geo2D.unitize(Geo2D.perp_left(upper_dir_u))
        if perp_u.Y < 0:
            perp_u = rg.Vector3d(-perp_u.X, -perp_u.Y, 0.0)

        h2 = Geo2D.add_pt_vec(hprime2, perp_u, self.hprimeh_length)

        hprime_world = mapper.plane_to_world_pt(hprime2)
        h_world = mapper.plane_to_world_pt(h2)

        res.HPrime2D = hprime2
        res.HPrime = hprime_world
        res.H2D = h2
        res.H = h_world

        # C-H 线
        ch_dir = Geo2D.vec(c2, h2)
        if Geo2D.length(ch_dir) <= 1e-12:
            raise ValueError("子角梁步骤 5 失败：C 与 H 重合，无法建立 C-H。")

        # ----------------------------
        # 6) 过 G 作 G-I 平行于 C-H；由 H 向 G-I 作垂线，垂足为 I
        # ----------------------------
        i2, ti = Geo2D.project_point_to_line(h2, g2, ch_dir)
        i_world = mapper.plane_to_world_pt(i2)

        res.I2D = i2
        res.I = i_world

        # ----------------------------
        # 7) 子角梁截面线 E'-G-I-H-C-E'
        # ----------------------------
        child_poly = rg.Polyline([
            res.EPrime,
            res.G,
            res.I,
            res.H,
            res.C,
            res.EPrime
        ])
        child_nurbs = child_poly.ToNurbsCurve()

        child_breps = rg.Brep.CreatePlanarBreps(child_nurbs)
        if child_breps and len(child_breps) > 0:
            child_brep = child_breps[0]
        else:
            child_brep = None

        res.ChildGuideLine = rg.Line(res.EPrime, res.F)
        res.ChildVerticalAtC = rg.Line(
            mapper.plane_to_world_pt(Geo2D.add_pt_vec(c2, y_dir, -1000.0)),
            mapper.plane_to_world_pt(Geo2D.add_pt_vec(c2, y_dir, 1000.0))
        )
        res.CHLine = rg.Line(res.C, res.H)
        res.GHLine = rg.Line(res.G, res.I)
        res.IHLine = rg.Line(res.I, res.H)
        res.ChildPolyline = child_poly
        res.ChildNurbs = child_nurbs
        res.ChildBrep = child_brep

        self.Log.append("[ZiJiao] 已完成 E 的投影，得到 E'。")
        self.Log.append("[ZiJiao] 已延长 D-C 得点 F，满足 C-F = ChildWidth。")
        self.Log.append("[ZiJiao] 已由 E'-F 与过 C 的 P'.Y 方向线求得 G。")
        self.Log.append("[ZiJiao] 已由 C-H' 与 H'-H 求得 H'、H，并建立 C-H。")
        self.Log.append("[ZiJiao] 已由过 G 的平行线与 H 的垂足求得 I。")
        self.Log.append("[ZiJiao] 已生成子角梁截面线 E'-G-I-H-C-E'。")

        return res

    def _build_yinjiao_geometry_2d(self, mapper, res):
        """
        在 P' 二维坐标系中完成隱角梁求解。
        """
        if self.hidden_length is None:
            self.Log.append("[YinJiao] 未输入 HiddenLength，跳过隱角梁几何。")
            return res

        if res.EPrime2D is None:
            self.Log.append("[YinJiao] 未能获得 E'，跳过隱角梁几何。")
            return res

        cp2 = res.CDoublePrime2D
        dp2 = res.DDoublePrime2D

        # 1) 延 D''-C''，以 C'' 为起点，得点 J
        dpcp_dir = Geo2D.vec(dp2, cp2)   # D'' -> C''
        dpcp_dir_u = Geo2D.unitize(dpcp_dir)
        j2 = Geo2D.add_pt_vec(cp2, dpcp_dir_u, self.hidden_length)
        j_world = mapper.plane_to_world_pt(j2)

        res.J2D = j2
        res.J = j_world

        # 2) 连接点 C'', J, E'，得隱角梁截面 C''-J-E'-C''
        hidden_poly = rg.Polyline([
            res.CDoublePrime,
            res.J,
            res.EPrime,
            res.CDoublePrime
        ])
        hidden_nurbs = hidden_poly.ToNurbsCurve()

        hidden_breps = rg.Brep.CreatePlanarBreps(hidden_nurbs)
        if hidden_breps and len(hidden_breps) > 0:
            hidden_brep = hidden_breps[0]
        else:
            hidden_brep = None

        res.HiddenEdgeLine = rg.Line(res.CDoublePrime, res.J)
        res.HiddenPolyline = hidden_poly
        res.HiddenNurbs = hidden_nurbs
        res.HiddenBrep = hidden_brep

        self.Log.append("[YinJiao] 已延 D''-C''，以 C'' 为起点求得 J，满足 C''-J = HiddenLength。")
        self.Log.append("[YinJiao] 已生成隱角梁截面 C''-J-E'-C''。")

        return res

    def _build_solids(self, mapper, res):
        """
        将三类截面沿垂直于 P' 的方向双侧偏移后放样成体并封面。
        """
        tol = 0.01

        # 大角梁实体
        if res.RectNurbs is not None and self.dajiao_thickness is not None and self.dajiao_thickness > 0:
            da = SolidBuilder.build_solid_from_profile(
                profile_curve=res.RectNurbs,
                ref_plane=mapper.plane,
                thickness=self.dajiao_thickness,
                tol=tol
            )
            res.DaJiaoProfilePos = da["pos_curve"]
            res.DaJiaoProfileNeg = da["neg_curve"]
            res.DaJiaoSideLoft = da["side_loft"]
            res.DaJiaoCapPos = da["cap_pos"]
            res.DaJiaoCapNeg = da["cap_neg"]
            res.DaJiaoSolid = da["solid"]
            self.Log.append("[Solid] 已完成大角梁截面双侧偏移、放样侧壁、正负封面及封闭体组合。")
        else:
            self.Log.append("[Solid] 未输入有效 DaJiaoThickness 或大角梁截面缺失，跳过大角梁实体。")

        # 子角梁实体
        if res.ChildNurbs is not None and self.child_thickness is not None and self.child_thickness > 0:
            ch = SolidBuilder.build_solid_from_profile(
                profile_curve=res.ChildNurbs,
                ref_plane=mapper.plane,
                thickness=self.child_thickness,
                tol=tol
            )
            res.ChildProfilePos = ch["pos_curve"]
            res.ChildProfileNeg = ch["neg_curve"]
            res.ChildSideLoft = ch["side_loft"]
            res.ChildCapPos = ch["cap_pos"]
            res.ChildCapNeg = ch["cap_neg"]
            res.ChildSolid = ch["solid"]
            self.Log.append("[Solid] 已完成子角梁截面双侧偏移、放样侧壁、正负封面及封闭体组合。")
        else:
            self.Log.append("[Solid] 未输入有效 ChildThickness 或子角梁截面缺失，跳过子角梁实体。")

        # 隱角梁实体
        if res.HiddenNurbs is not None and self.hidden_thickness is not None and self.hidden_thickness > 0:
            hi = SolidBuilder.build_solid_from_profile(
                profile_curve=res.HiddenNurbs,
                ref_plane=mapper.plane,
                thickness=self.hidden_thickness,
                tol=tol
            )
            res.HiddenProfilePos = hi["pos_curve"]
            res.HiddenProfileNeg = hi["neg_curve"]
            res.HiddenSideLoft = hi["side_loft"]
            res.HiddenCapPos = hi["cap_pos"]
            res.HiddenCapNeg = hi["cap_neg"]
            res.HiddenSolid = hi["solid"]
            self.Log.append("[Solid] 已完成隱角梁截面双侧偏移、放样侧壁、正负封面及封闭体组合。")
        else:
            self.Log.append("[Solid] 未输入有效 HiddenThickness 或隱角梁截面缺失，跳过隱角梁实体。")

        return res

    def _build_requested_face_features(self, mapper, res):
        """
        构建用户指定的三个侧面固定顺序数据：
            1) DaJiaoSolid 中 C-D 所在面
            2) DaJiaoSolid 中 C'-D' 所在面
            3) ChildSolid 中 I-H 所在面
        """
        tol = 0.01

        # 1) 大角梁 C-D 所在面
        if res.C is not None and res.D is not None and self.dajiao_thickness is not None and self.dajiao_thickness > 0:
            fd = FaceFeatureBuilder.build_face_from_profile_edge(
                start_pt=res.C,
                end_pt=res.D,
                ref_plane=mapper.plane,
                thickness=self.dajiao_thickness,
                tol=tol
            )
            res.DaJiaoFace_CD = fd["face_brep"]
            res.DaJiaoFace_CD_CornerPoints = fd["corner_points"]
            res.DaJiaoFace_CD_EdgeMidPoints = fd["edge_midpoints"]
            res.DaJiaoFace_CD_PlaneList = fd["plane_list"]
            self.Log.append("[Face] 已构建 DaJiaoSolid 中 C-D 所在面固定顺序数据。")
        else:
            self.Log.append("[Face] 大角梁 C-D 所在面数据构建条件不足，已跳过。")

        # 2) 大角梁 C''-D'' 所在面（兼容沿用旧输出名）
        if res.CDoublePrime is not None and res.DDoublePrime is not None and self.dajiao_thickness is not None and self.dajiao_thickness > 0:
            fdp = FaceFeatureBuilder.build_face_from_profile_edge(
                start_pt=res.CDoublePrime,
                end_pt=res.DDoublePrime,
                ref_plane=mapper.plane,
                thickness=self.dajiao_thickness,
                tol=tol
            )
            res.DaJiaoFace_CPrimeDPrime = fdp["face_brep"]
            res.DaJiaoFace_CPrimeDPrime_CornerPoints = fdp["corner_points"]
            res.DaJiaoFace_CPrimeDPrime_EdgeMidPoints = fdp["edge_midpoints"]
            res.DaJiaoFace_CPrimeDPrime_PlaneList = fdp["plane_list"]
            self.Log.append("[Face] 已构建 DaJiaoSolid 中 C''-D'' 所在面固定顺序数据（输出名兼容沿用 CPrimeDPrime）。")
        else:
            self.Log.append("[Face] 大角梁 C''-D'' 所在面数据构建条件不足，已跳过。")

        # 3) 子角梁 I-H 所在面
        if res.I is not None and res.H is not None and self.child_thickness is not None and self.child_thickness > 0:
            fih = FaceFeatureBuilder.build_face_from_profile_edge(
                start_pt=res.I,
                end_pt=res.H,
                ref_plane=mapper.plane,
                thickness=self.child_thickness,
                tol=tol
            )
            res.ChildFace_IH = fih["face_brep"]
            res.ChildFace_IH_CornerPoints = fih["corner_points"]
            res.ChildFace_IH_EdgeMidPoints = fih["edge_midpoints"]
            res.ChildFace_IH_PlaneList = fih["plane_list"]
            self.Log.append("[Face] 已构建 ChildSolid 中 I-H 所在面固定顺序数据。")
        else:
            self.Log.append("[Face] 子角梁 I-H 所在面数据构建条件不足，已跳过。")

        return res

    def build(self):
        """
        对外主方法
        """
        base_plane = self._build_base_plane()
        pprime = self._build_pprime(base_plane)
        mapper = Plane2DMapper(pprime)

        res = JiaoLiangResult()
        res = self._build_dajiao_geometry_2d(mapper, res)
        res = self._build_zijiao_geometry_2d(mapper, res)
        res = self._build_yinjiao_geometry_2d(mapper, res)
        res = self._build_solids(mapper, res)
        res = self._build_requested_face_features(mapper, res)

        res.Log = list(self.Log)
        return res


# ======================================================================
# Solver 主类
# ======================================================================

class JiaoLiangSolver(object):

    def __init__(
        self,
        O=None,
        A=None,
        Diameter=None,
        BeamWidth=None,
        TailLength=None,
        ExtendAtPrimeLength=None,
        E=None,
        ChildWidth=None,
        CHPrimeLength=None,
        HPrimeHLength=None,
        HiddenLength=None,
        DaJiaoThickness=None,
        ChildThickness=None,
        HiddenThickness=None,
        P=None,
        Refresh=False,
        ghenv=None
    ):
        self.O = O
        self.A = A
        self.Diameter = Diameter
        self.BeamWidth = BeamWidth
        self.TailLength = TailLength
        self.ExtendAtPrimeLength = ExtendAtPrimeLength

        self.E = E
        self.ChildWidth = ChildWidth
        self.CHPrimeLength = CHPrimeLength
        self.HPrimeHLength = HPrimeHLength
        self.HiddenLength = HiddenLength

        self.DaJiaoThickness = DaJiaoThickness
        self.ChildThickness = ChildThickness
        self.HiddenThickness = HiddenThickness

        self.P = P
        self.Refresh = bool(Refresh)
        self.ghenv = ghenv

        self.Log = []

        # 核心输出
        self.PPrime = None
        self.Circle = None
        self.Rect = None
        self.EPrime = None
        self.ChildProfile = None
        self.J = None
        self.HiddenProfile = None
        self.DaJiaoSolid = None
        self.ChildSolid = None
        self.HiddenSolid = None

        # 大角梁开发模式输出
        self.O2D = None
        self.A2D = None
        self.B = None
        self.CPrime = None
        self.DPrime = None
        self.CDoublePrime = None
        self.DDoublePrime = None
        self.C = None
        self.D = None
        self.UpperLine = None
        self.LowerLine = None
        self.VerticalAB = None
        self.RectPolyline = None
        self.RectBrep = None
        self.TangentPoint2D = None
        self.B2D = None
        self.NormalVec = None
        self.TangentVec = None

        # 子角梁开发模式输出
        self.EProj = None
        self.EProj2D = None
        self.EPrime2D = None
        self.F = None
        self.G = None
        self.HPrime = None
        self.H = None
        self.I = None
        self.ChildGuideLine = None
        self.ChildVerticalAtC = None
        self.CHLine = None
        self.GHLine = None
        self.IHLine = None
        self.ChildPolyline = None
        self.ChildBrep = None

        # 隱角梁开发模式输出
        self.J2D = None
        self.HiddenEdgeLine = None
        self.HiddenPolyline = None
        self.HiddenBrep = None

        # 实体开发模式输出
        self.DaJiaoProfilePos = None
        self.DaJiaoProfileNeg = None
        self.ChildProfilePos = None
        self.ChildProfileNeg = None
        self.HiddenProfilePos = None
        self.HiddenProfileNeg = None

        self.DaJiaoSideLoft = None
        self.ChildSideLoft = None
        self.HiddenSideLoft = None

        self.DaJiaoCapPos = None
        self.DaJiaoCapNeg = None
        self.ChildCapPos = None
        self.ChildCapNeg = None
        self.HiddenCapPos = None
        self.HiddenCapNeg = None

        # 新增：DaJiaoSolid 中 C-D 所在面
        self.DaJiaoFace_CD = None
        self.DaJiaoFace_CD_CornerPoints = []
        self.DaJiaoFace_CD_EdgeMidPoints = []
        self.DaJiaoFace_CD_PlaneList = []

        # 新增：DaJiaoSolid 中 C'-D' 所在面
        self.DaJiaoFace_CPrimeDPrime = None
        self.DaJiaoFace_CPrimeDPrime_CornerPoints = []
        self.DaJiaoFace_CPrimeDPrime_EdgeMidPoints = []
        self.DaJiaoFace_CPrimeDPrime_PlaneList = []

        # 新增：ChildSolid 中 I-H 所在面
        self.ChildFace_IH = None
        self.ChildFace_IH_CornerPoints = []
        self.ChildFace_IH_EdgeMidPoints = []
        self.ChildFace_IH_PlaneList = []

    def run(self):
        self.Log = []

        if self.Refresh:
            self.Log.append("[SYS] Refresh=True，强制重算。")

        try:
            builder = JiaoLiangBuilder(
                O=self.O,
                A=self.A,
                diameter=self.Diameter,
                beam_width=self.BeamWidth,
                tail_length=self.TailLength,
                extend_at_prime_length=self.ExtendAtPrimeLength,
                E=self.E,
                child_width=self.ChildWidth,
                chprime_length=self.CHPrimeLength,
                hprimeh_length=self.HPrimeHLength,
                hidden_length=self.HiddenLength,
                dajiao_thickness=self.DaJiaoThickness,
                child_thickness=self.ChildThickness,
                hidden_thickness=self.HiddenThickness,
                ref_plane=self.P
            )

            result = builder.build()

            # 核心输出
            self.PPrime = result.PPrime
            self.Circle = result.Circle
            self.Rect = result.RectNurbs
            self.EPrime = result.EPrime
            self.ChildProfile = result.ChildNurbs
            self.J = result.J
            self.HiddenProfile = result.HiddenNurbs
            self.DaJiaoSolid = result.DaJiaoSolid
            self.ChildSolid = result.ChildSolid
            self.HiddenSolid = result.HiddenSolid

            # 大角梁开发模式输出
            self.O2D = result.O2D
            self.A2D = result.A2D
            self.B = result.B
            self.CPrime = result.CPrime
            self.DPrime = result.DPrime
            self.CDoublePrime = result.CDoublePrime
            self.DDoublePrime = result.DDoublePrime
            self.C = result.C
            self.D = result.D
            self.UpperLine = result.UpperLine
            self.LowerLine = result.LowerLine
            self.VerticalAB = result.VerticalAB
            self.RectPolyline = result.RectPolyline
            self.RectBrep = result.RectBrep
            self.TangentPoint2D = result.CPrime2D
            self.B2D = result.B2D
            self.NormalVec = result.NormalVec
            self.TangentVec = result.TangentVec

            # 子角梁开发模式输出
            self.EProj = result.EProj
            self.EProj2D = result.EProj2D
            self.EPrime2D = result.EPrime2D
            self.F = result.F
            self.G = result.G
            self.HPrime = result.HPrime
            self.H = result.H
            self.I = result.I
            self.ChildGuideLine = result.ChildGuideLine
            self.ChildVerticalAtC = result.ChildVerticalAtC
            self.CHLine = result.CHLine
            self.GHLine = result.GHLine
            self.IHLine = result.IHLine
            self.ChildPolyline = result.ChildPolyline
            self.ChildBrep = result.ChildBrep

            # 隱角梁开发模式输出
            self.J2D = result.J2D
            self.HiddenEdgeLine = result.HiddenEdgeLine
            self.HiddenPolyline = result.HiddenPolyline
            self.HiddenBrep = result.HiddenBrep

            # 实体开发模式输出
            self.DaJiaoProfilePos = result.DaJiaoProfilePos
            self.DaJiaoProfileNeg = result.DaJiaoProfileNeg
            self.ChildProfilePos = result.ChildProfilePos
            self.ChildProfileNeg = result.ChildProfileNeg
            self.HiddenProfilePos = result.HiddenProfilePos
            self.HiddenProfileNeg = result.HiddenProfileNeg

            self.DaJiaoSideLoft = result.DaJiaoSideLoft
            self.ChildSideLoft = result.ChildSideLoft
            self.HiddenSideLoft = result.HiddenSideLoft

            self.DaJiaoCapPos = result.DaJiaoCapPos
            self.DaJiaoCapNeg = result.DaJiaoCapNeg
            self.ChildCapPos = result.ChildCapPos
            self.ChildCapNeg = result.ChildCapNeg
            self.HiddenCapPos = result.HiddenCapPos
            self.HiddenCapNeg = result.HiddenCapNeg

            # 新增：指定面固定顺序输出
            self.DaJiaoFace_CD = result.DaJiaoFace_CD
            self.DaJiaoFace_CD_CornerPoints = result.DaJiaoFace_CD_CornerPoints
            self.DaJiaoFace_CD_EdgeMidPoints = result.DaJiaoFace_CD_EdgeMidPoints
            self.DaJiaoFace_CD_PlaneList = result.DaJiaoFace_CD_PlaneList

            self.DaJiaoFace_CPrimeDPrime = result.DaJiaoFace_CPrimeDPrime
            self.DaJiaoFace_CPrimeDPrime_CornerPoints = result.DaJiaoFace_CPrimeDPrime_CornerPoints
            self.DaJiaoFace_CPrimeDPrime_EdgeMidPoints = result.DaJiaoFace_CPrimeDPrime_EdgeMidPoints
            self.DaJiaoFace_CPrimeDPrime_PlaneList = result.DaJiaoFace_CPrimeDPrime_PlaneList

            self.ChildFace_IH = result.ChildFace_IH
            self.ChildFace_IH_CornerPoints = result.ChildFace_IH_CornerPoints
            self.ChildFace_IH_EdgeMidPoints = result.ChildFace_IH_EdgeMidPoints
            self.ChildFace_IH_PlaneList = result.ChildFace_IH_PlaneList

            self.Log.extend(result.Log)

        except Exception as e:
            self.Log.append("[ERR] 构建失败: {}".format(e))

        return self


# ======================================================================
# GH 输出绑定区
# ======================================================================
if __name__ == "__main__":

    try:
        _O = O
    except:
        _O = None

    try:
        _A = A
    except:
        _A = None

    try:
        _Diameter = Diameter
    except:
        _Diameter = None

    try:
        _BeamWidth = BeamWidth
    except:
        _BeamWidth = None

    try:
        _TailLength = TailLength
    except:
        _TailLength = None

    try:
        _ExtendAtPrimeLength = ExtendAtPrimeLength
    except:
        _ExtendAtPrimeLength = 0.0

    try:
        _E = E
    except:
        _E = None

    try:
        _ChildWidth = ChildWidth
    except:
        _ChildWidth = None

    try:
        _CHPrimeLength = CHPrimeLength
    except:
        _CHPrimeLength = None

    try:
        _HPrimeHLength = HPrimeHLength
    except:
        _HPrimeHLength = None

    try:
        _HiddenLength = HiddenLength
    except:
        _HiddenLength = None

    try:
        _DaJiaoThickness = DaJiaoThickness
    except:
        _DaJiaoThickness = None

    try:
        _ChildThickness = ChildThickness
    except:
        _ChildThickness = None

    try:
        _HiddenThickness = HiddenThickness
    except:
        _HiddenThickness = None

    try:
        _P = P
    except:
        _P = None

    try:
        _Refresh = Refresh
    except:
        _Refresh = False

    solver = JiaoLiangSolver(
        O=_O,
        A=_A,
        Diameter=_Diameter,
        BeamWidth=_BeamWidth,
        TailLength=_TailLength,
        ExtendAtPrimeLength=_ExtendAtPrimeLength,
        E=_E,
        ChildWidth=_ChildWidth,
        CHPrimeLength=_CHPrimeLength,
        HPrimeHLength=_HPrimeHLength,
        HiddenLength=_HiddenLength,
        DaJiaoThickness=_DaJiaoThickness,
        ChildThickness=_ChildThickness,
        HiddenThickness=_HiddenThickness,
        P=_P,
        Refresh=_Refresh,
        ghenv=ghenv
    )
    solver.run()

    # ------------------------------------------------------------------
    # 核心对外输出（正式输出端建议保留这 10 个）
    # ------------------------------------------------------------------
    PPrime        = solver.PPrime
    Circle        = solver.Circle
    Rect          = solver.Rect
    EPrime        = solver.EPrime
    ChildProfile  = solver.ChildProfile
    J             = solver.J
    HiddenProfile = solver.HiddenProfile
    DaJiaoSolid   = solver.DaJiaoSolid
    ChildSolid    = solver.ChildSolid
    HiddenSolid   = solver.HiddenSolid

    # ------------------------------------------------------------------
    # 开发模式：按需在 GH 中添加同名输出端即可看到内部数据
    # ------------------------------------------------------------------
    try:
        # 大角梁
        O2D            = solver.O2D
        A2D            = solver.A2D
        B              = solver.B
        CPrime         = solver.CPrime
        DPrime         = solver.DPrime
        CDoublePrime   = solver.CDoublePrime
        DDoublePrime   = solver.DDoublePrime
        C              = solver.C
        D              = solver.D
        UpperLine      = solver.UpperLine
        LowerLine      = solver.LowerLine
        VerticalAB     = solver.VerticalAB
        RectPolyline   = solver.RectPolyline
        RectBrep       = solver.RectBrep
        TangentPoint2D = solver.TangentPoint2D
        B2D            = solver.B2D
        NormalVec      = solver.NormalVec
        TangentVec     = solver.TangentVec

        # 子角梁
        EProj            = solver.EProj
        EProj2D          = solver.EProj2D
        EPrime2D         = solver.EPrime2D
        F                = solver.F
        G                = solver.G
        HPrime           = solver.HPrime
        H                = solver.H
        I                = solver.I
        ChildGuideLine   = solver.ChildGuideLine
        ChildVerticalAtC = solver.ChildVerticalAtC
        CHLine           = solver.CHLine
        GHLine           = solver.GHLine
        IHLine           = solver.IHLine
        ChildPolyline    = solver.ChildPolyline
        ChildBrep        = solver.ChildBrep

        # 隱角梁
        J2D             = solver.J2D
        HiddenEdgeLine  = solver.HiddenEdgeLine
        HiddenPolyline  = solver.HiddenPolyline
        HiddenBrep      = solver.HiddenBrep

        # 实体
        DaJiaoProfilePos = solver.DaJiaoProfilePos
        DaJiaoProfileNeg = solver.DaJiaoProfileNeg
        ChildProfilePos  = solver.ChildProfilePos
        ChildProfileNeg  = solver.ChildProfileNeg
        HiddenProfilePos = solver.HiddenProfilePos
        HiddenProfileNeg = solver.HiddenProfileNeg

        DaJiaoSideLoft   = solver.DaJiaoSideLoft
        ChildSideLoft    = solver.ChildSideLoft
        HiddenSideLoft   = solver.HiddenSideLoft

        DaJiaoCapPos     = solver.DaJiaoCapPos
        DaJiaoCapNeg     = solver.DaJiaoCapNeg
        ChildCapPos      = solver.ChildCapPos
        ChildCapNeg      = solver.ChildCapNeg
        HiddenCapPos     = solver.HiddenCapPos
        HiddenCapNeg     = solver.HiddenCapNeg

        # 新增：DaJiaoSolid 中 C-D 所在面
        DaJiaoFace_CD                  = solver.DaJiaoFace_CD
        DaJiaoFace_CD_CornerPoints     = solver.DaJiaoFace_CD_CornerPoints
        DaJiaoFace_CD_EdgeMidPoints    = solver.DaJiaoFace_CD_EdgeMidPoints
        DaJiaoFace_CD_PlaneList        = solver.DaJiaoFace_CD_PlaneList

        # 新增：DaJiaoSolid 中 CDoublePrime-DDoublePrime 所在面（兼容沿用旧输出名）
        DaJiaoFace_CPrimeDPrime               = solver.DaJiaoFace_CPrimeDPrime
        DaJiaoFace_CPrimeDPrime_CornerPoints  = solver.DaJiaoFace_CPrimeDPrime_CornerPoints
        DaJiaoFace_CPrimeDPrime_EdgeMidPoints = solver.DaJiaoFace_CPrimeDPrime_EdgeMidPoints
        DaJiaoFace_CPrimeDPrime_PlaneList     = solver.DaJiaoFace_CPrimeDPrime_PlaneList

        # 新增：ChildSolid 中 I-H 所在面
        ChildFace_IH               = solver.ChildFace_IH
        ChildFace_IH_CornerPoints  = solver.ChildFace_IH_CornerPoints
        ChildFace_IH_EdgeMidPoints = solver.ChildFace_IH_EdgeMidPoints
        ChildFace_IH_PlaneList     = solver.ChildFace_IH_PlaneList

        Log              = solver.Log
    except:
        pass
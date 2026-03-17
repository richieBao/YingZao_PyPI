# -*- coding: utf-8 -*-
"""
ZhuanJiaoBuChuanSolver.py
轉角布椽 组件（第1部分 + 第2部分 + 第3部分绘制 + 椽管实体 + 镜像）

用途:
    第1部分：
        1) 基于空间直线段 A-B、A-C、C-D 与参考平面，识别 A/B/C/D
        2) 将 A-B 沿 A-C 方向平移，得到与 A-B 平行的 A'-B'
        3) 由 C-D 与参考平面 Z 方向构建参考平面 P（原点 D）
           点 E 为直线 A'-B' 与平面 P 的交点
           再将点 E 沿输入参考平面 RefPlane 的 Z 轴方向投影到直线 D-C 上，得到点 D'
           连接 E-D'，并在 D'-E 上提取点 E'
           再取 E-C 中点 F
           在平面 P 内，过 F 作垂直于 E'-C 的方向，并朝截面内部取点 F'
           满足 F-F' = 输入参数 FFPrimeLength
           构造弧线段 E'-F'-C
           最终截面为：C-D'-E'-(弧)-C
        4) 将该截面沿平面 P 法向双侧偏移，得到两个新截面
           通过 Loft + Cap + Join 生成封闭体

    第2部分：
        1) 在 A'-B' 直线段上提取点 G，其中 B'-G 长度为输入参数 BPrimeGLength
        2) 输入点 H，新建参考平面 P'：
           将输入参考平面复制，仅将原点移动到 H
        3) 将点 G 沿输入参考平面 Z 轴方向投影到参考平面 P' 上，得点 G'
        4) 连接 G'-H，得线段 G'-H
           取其中点 I
           在 P' 平面内，作垂直于 G'-H 的方向，取点 I'
           满足 I-I' 长度为输入参数 IIPrimeLength
           且 I' 始终朝向 A' 方向，即：I'-A' < I-A'
        5) 过 G'、I'、H 构造弧线 G'-I'-H

    第3部分：
        1) 输入端增加参数椽距 ChuanJu
        2) 根据该椽距，对弧线段 C-E'（即 ArcCurve）从 C 端开始按弧长等分
        3) 以 A' 为起点，以各等分点为终点，绘制直线段
        4) 以弧线 G'-I'-H 沿输入参考平面 Z 轴正方向拉伸得到曲面参照
        5) 将各等分直线段沿自身方向延伸到该曲面上
        6) 输出最终各转角步椽中心线列表
        7) 输入端增加椽径 ChuanJing，将各椽中心线按椽径成管，
           并以平口封闭为实体，输出 Brep 列表
        8) 以输入端直线段 AB 与输入参考平面 RefPlane 的 ZAxis 构建参考平面 P_hipRafter
           该平面：
                - 原点为 A 点
                - 包含直线段 AB
                - 包含 RefPlane.ZAxis
        9) 将 RafterPipes 和 SectionSolid 以 P_hipRafter 为镜面镜像到另一侧

输入（GhPython 建议设置）:
    AB : rg.LineCurve / rg.Line / rg.Curve / 其他可转直线对象
        Access = Item
        TypeHint = No Type Hint（推荐改为 Curve）

    AC : rg.LineCurve / rg.Line / rg.Curve / 其他可转直线对象
        Access = Item
        TypeHint = No Type Hint（推荐改为 Curve）

    CD : rg.LineCurve / rg.Line / rg.Curve / 其他可转直线对象
        Access = Item
        TypeHint = No Type Hint（推荐改为 Curve）

    RefPlane : rg.Plane
        Access = Item
        TypeHint = Plane

    AAPrimeLength : float
        Access = Item
        TypeHint = float

    DEPrimeLength : float
        Access = Item
        TypeHint = float

    FFPrimeLength : float
        Access = Item
        TypeHint = float

    Thickness : float
        Access = Item
        TypeHint = float

    H : rg.Point3d
        Access = Item
        TypeHint = Point3d

    BPrimeGLength : float
        Access = Item
        TypeHint = float

    IIPrimeLength : float
        Access = Item
        TypeHint = float

    ChuanJu : float
        Access = Item
        TypeHint = float
        椽距。用于从 C 端开始按弧长等分弧线段 C-E'。

    ChuanJing : float
        Access = Item
        TypeHint = float
        椽径。用于各椽中心线成管。

固定输出:
    SectionCurve : rg.Curve
        含弧闭合截面：C-D'-E'-(Arc E'-F'-C)-C

    SectionSolid : rg.Brep
        截面双侧偏移、Loft、封面并 Join 后得到的封闭体。

    Log : list[str]
        过程日志。

绑定区可选输出（按需在 GH 中添加同名输出端）:
    SectionPlane : rg.Plane
    APoint : rg.Point3d
    BPoint : rg.Point3d
    CPoint : rg.Point3d
    DPoint : rg.Point3d
    DPrime : rg.Point3d
    APrime : rg.Point3d
    BPrime : rg.Point3d
    EPoint : rg.Point3d
    EPrime : rg.Point3d
    FPoint : rg.Point3d
    FPrime : rg.Point3d
    ABPrimeLine : rg.LineCurve
    EDLine : rg.LineCurve
    ArcCurve : rg.ArcCurve
    ProfilePos : rg.Curve
    ProfileNeg : rg.Curve
    SideLoft : rg.Brep
    CapPos : rg.Brep
    CapNeg : rg.Brep

    GPoint : rg.Point3d
    PPrime : rg.Plane
    GPrime : rg.Point3d
    GHLine : rg.LineCurve
    IPoint : rg.Point3d
    IPrime : rg.Point3d
    Arc_GPrime_IPrime_H : rg.ArcCurve

    Arc_CToEPrime : rg.Curve
    ArcDivisionPoints : list[rg.Point3d]
    ArcDivisionLines : list[rg.LineCurve]
    GuideSurface : rg.Brep
    RafterCenterLines : list[rg.LineCurve]
    RafterPipes : list[rg.Brep]

    P_hipRafter : rg.Plane
    MirroredRafterPipes : list[rg.Brep]
    MirroredSectionSolid : rg.Brep
"""

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc


# ======================================================================
# 数据对象
# ======================================================================
class ZhuanJiaoBuChuanResult(object):
    def __init__(self):
        self.SectionPlane = None
        self.SectionCurve = None
        self.SectionSolid = None

        self.APoint = None
        self.BPoint = None
        self.CPoint = None
        self.DPoint = None
        self.DPrime = None

        self.APrime = None
        self.BPrime = None
        self.EPoint = None
        self.EPrime = None
        self.FPoint = None
        self.FPrime = None

        self.ABPrimeLine = None
        self.EDLine = None
        self.ArcCurve = None

        self.ProfilePos = None
        self.ProfileNeg = None
        self.SideLoft = None
        self.CapPos = None
        self.CapNeg = None

        # Part 2
        self.GPoint = None
        self.PPrime = None
        self.GPrime = None
        self.GHLine = None
        self.IPoint = None
        self.IPrime = None
        self.Arc_GPrime_IPrime_H = None

        # Part 3
        self.Arc_CToEPrime = None
        self.ArcDivisionPoints = None
        self.ArcDivisionLines = None
        self.GuideSurface = None
        self.RafterCenterLines = None
        self.RafterPipes = None

        # Mirror
        self.P_hipRafter = None
        self.MirroredRafterPipes = None
        self.MirroredSectionSolid = None

        self.Log = []


# ======================================================================
# 核心构建器
# ======================================================================
class ZhuanJiaoBuChuanBuilder(object):
    def __init__(self,
                 AB=None,
                 AC=None,
                 CD=None,
                 RefPlane=None,
                 AAPrimeLength=None,
                 DEPrimeLength=None,
                 FFPrimeLength=None,
                 Thickness=None,
                 H=None,
                 BPrimeGLength=None,
                 IIPrimeLength=None,
                 ChuanJu=None,
                 ChuanJing=None,
                 ghenv=None):
        self.AB = AB
        self.AC = AC
        self.CD = CD
        self.RefPlane = RefPlane
        self.AAPrimeLength = AAPrimeLength
        self.DEPrimeLength = DEPrimeLength
        self.FFPrimeLength = FFPrimeLength
        self.Thickness = Thickness

        self.H = H
        self.BPrimeGLength = BPrimeGLength
        self.IIPrimeLength = IIPrimeLength
        self.ChuanJu = ChuanJu
        self.ChuanJing = ChuanJing

        self.ghenv = ghenv
        self.Log = []
        self.tol = sc.doc.ModelAbsoluteTolerance if sc.doc else 1e-6
        self.angle_tol = sc.doc.ModelAngleToleranceRadians if sc.doc else 0.1

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def _coerce_point(self, obj):
        if obj is None:
            return None
        if isinstance(obj, rg.Point3d):
            return rg.Point3d(obj)

        for attr in ["Value", "Location", "Point"]:
            try:
                v = getattr(obj, attr)
                if isinstance(v, rg.Point3d):
                    return rg.Point3d(v)
            except:
                pass

        try:
            return rg.Point3d(obj.X, obj.Y, obj.Z)
        except:
            pass
        return None

    def _get_endpoints_from_any(self, geo):
        if geo is None:
            return None, None

        if isinstance(geo, rg.Line):
            return rg.Point3d(geo.From), rg.Point3d(geo.To)

        if isinstance(geo, rg.LineCurve):
            return rg.Point3d(geo.PointAtStart), rg.Point3d(geo.PointAtEnd)

        if isinstance(geo, rg.Curve):
            try:
                return rg.Point3d(geo.PointAtStart), rg.Point3d(geo.PointAtEnd)
            except:
                pass

        if isinstance(geo, rg.Polyline):
            if geo.Count >= 2:
                return rg.Point3d(geo[0]), rg.Point3d(geo[geo.Count - 1])

        try:
            v = geo.Value
            if v is not None and v is not geo:
                return self._get_endpoints_from_any(v)
        except:
            pass

        try:
            line_attr = geo.Line
            if isinstance(line_attr, rg.Line):
                return rg.Point3d(line_attr.From), rg.Point3d(line_attr.To)
        except:
            pass

        try:
            p0 = self._coerce_point(geo.From)
            p1 = self._coerce_point(geo.To)
            if p0 is not None and p1 is not None:
                return p0, p1
        except:
            pass

        try:
            p0 = self._coerce_point(geo.PointAtStart)
            p1 = self._coerce_point(geo.PointAtEnd)
            if p0 is not None and p1 is not None:
                return p0, p1
        except:
            pass

        try:
            sv = geo.ScriptVariable()
            if sv is not None and sv is not geo:
                return self._get_endpoints_from_any(sv)
        except:
            pass

        return None, None

    def _as_line(self, geo, name):
        if geo is None:
            raise ValueError("输入 {} 不能为空。".format(name))

        self.Log.append("[INFO] {} 输入类型: {}".format(name, type(geo)))

        if isinstance(geo, rg.Line):
            line = rg.Line(geo.From, geo.To)
            if line.Length > self.tol:
                self.Log.append("[OK] {} 已识别为 rg.Line。".format(name))
                return line

        if isinstance(geo, rg.LineCurve):
            line = geo.Line
            if line.Length > self.tol:
                self.Log.append("[OK] {} 已识别为 rg.LineCurve。".format(name))
                return line

        if isinstance(geo, rg.Curve):
            ok, line = geo.TryGetLine()
            if ok and line.Length > self.tol:
                self.Log.append("[OK] {} 已由 Curve.TryGetLine 转为直线。".format(name))
                return line

        p0, p1 = self._get_endpoints_from_any(geo)
        if p0 is not None and p1 is not None and p0.DistanceTo(p1) > self.tol:
            self.Log.append("[WARN] {} 非标准直线对象，已按起终点转为 rg.Line。".format(name))
            return rg.Line(p0, p1)

        raise TypeError("输入 {} 必须是直线或可按起终点转为直线的 Curve。当前类型: {}".format(name, type(geo)))

    def _shared_endpoint(self, line1, line2, name1, name2):
        pts1 = [line1.From, line1.To]
        pts2 = [line2.From, line2.To]

        best = None
        best_d = 1e99
        best_i = 0
        best_j = 0

        for i, p1 in enumerate(pts1):
            for j, p2 in enumerate(pts2):
                d = p1.DistanceTo(p2)
                if d < best_d:
                    best_d = d
                    best = rg.Point3d(
                        0.5 * (p1.X + p2.X),
                        0.5 * (p1.Y + p2.Y),
                        0.5 * (p1.Z + p2.Z)
                    )
                    best_i = i
                    best_j = j

        if best is None:
            raise ValueError("无法识别 {} 与 {} 的公共端点。".format(name1, name2))

        if best_d > max(self.tol * 10.0, 1e-4):
            self.Log.append("[WARN] {} 与 {} 未严格共点，已按最近端点识别共享点，距离={:.6f}".format(name1, name2, best_d))
        else:
            self.Log.append("[OK] 已识别 {} 与 {} 的共享端点。".format(name1, name2))

        return best, best_i, best_j

    def _point_along(self, start_pt, end_pt, dist):
        vec = end_pt - start_pt
        if vec.IsTiny(self.tol):
            raise ValueError("方向构造失败：起点与终点重合。")
        vec.Unitize()
        return start_pt + vec * dist

    def _move_point(self, pt, vec):
        p = rg.Point3d(pt)
        p.Transform(rg.Transform.Translation(vec))
        return p

    def _move_curve(self, crv, vec):
        dup = crv.DuplicateCurve()
        dup.Transform(rg.Transform.Translation(vec))
        return dup

    def _duplicate_brep_safe(self, brep):
        if brep is None:
            return None
        try:
            return brep.DuplicateBrep()
        except:
            return None

    def _line_curve(self, p0, p1):
        return rg.LineCurve(p0, p1)

    def _make_ref_plane_at_a(self, a_pt):
        if self.RefPlane is None:
            p = rg.Plane.WorldXY
            p.Origin = a_pt
            self.Log.append("[OK] RefPlane 为空，已使用 WorldXY 并将原点重置到 A。")
            return p

        p = rg.Plane(self.RefPlane)
        p.Origin = a_pt
        self.Log.append("[OK] 已使用输入 RefPlane，并将原点重置到 A。")
        return p

    def _make_plane_at_point(self, source_plane, origin_pt):
        p = rg.Plane(source_plane)
        p.Origin = origin_pt
        if not p.IsValid:
            raise ValueError("参考平面复制失败。")
        return p

    def _project_point_to_plane_along_vector(self, point, plane, direction_vec):
        v = rg.Vector3d(direction_vec)
        if v.IsTiny(self.tol):
            raise ValueError("投影方向向量无效。")
        v.Unitize()

        line = rg.Line(point - v * 1e6, point + v * 1e6)
        ok, t = rg.Intersect.Intersection.LinePlane(line, plane)
        if not ok:
            raise ValueError("点无法沿指定方向投影到目标平面上。")
        return line.PointAt(t)

    def _build_section_plane(self, d_pt, c_pt, ref_plane):
        xaxis = c_pt - d_pt
        if xaxis.IsTiny(self.tol):
            raise ValueError("C 与 D 重合，无法构建截面平面。")
        xaxis.Unitize()

        zref = rg.Vector3d(ref_plane.ZAxis)
        if zref.IsTiny(self.tol):
            raise ValueError("参考平面的 Z 轴无效。")
        zref.Unitize()

        yaxis = zref - xaxis * (zref * xaxis)
        if yaxis.IsTiny(self.tol):
            raise ValueError("C-D 与参考平面 Z 轴平行，无法构建唯一截面平面。")
        yaxis.Unitize()

        plane = rg.Plane(d_pt, xaxis, yaxis)
        if not plane.IsValid:
            raise ValueError("截面平面 P 构建失败。")
        return plane

    def _build_hip_rafter_plane(self, line_ab, ref_plane, a_pt):
        """
        以输入端直线段 AB 和输入参考平面 RefPlane 的 ZAxis 构建 P_hipRafter
        且：
            - 原点为 A 点
            - 平面包含直线段 AB
            - 平面包含 RefPlane.ZAxis

        构造方式：
            XAxis = AB 方向
            YAxis = 将 RefPlane.ZAxis 投影到垂直于 XAxis 的方向
            ZAxis = XAxis × YAxis
        """
        xaxis = rg.Vector3d(line_ab.Direction)
        if xaxis.IsTiny(self.tol):
            raise ValueError("输入直线段 AB 无效，无法构建 P_hipRafter。")
        xaxis.Unitize()

        ref_z = rg.Vector3d(ref_plane.ZAxis)
        if ref_z.IsTiny(self.tol):
            ref_z = rg.Vector3d.ZAxis
        ref_z.Unitize()

        # 将 ref_z 投影到垂直于 xaxis 的方向，保证平面“过 AB 且过 ref_z”
        yaxis = ref_z - xaxis * (ref_z * xaxis)

        if yaxis.IsTiny(self.tol):
            raise ValueError("输入直线段 AB 与 RefPlane.ZAxis 平行，无法唯一构建过 AB 和 ZAxis 的 P_hipRafter。")
        yaxis.Unitize()

        zaxis = rg.Vector3d.CrossProduct(xaxis, yaxis)
        if zaxis.IsTiny(self.tol):
            raise ValueError("P_hipRafter 的 ZAxis 构建失败。")
        zaxis.Unitize()

        # 再正交化一次
        yaxis = rg.Vector3d.CrossProduct(zaxis, xaxis)
        if yaxis.IsTiny(self.tol):
            raise ValueError("P_hipRafter 的 YAxis 正交化失败。")
        yaxis.Unitize()

        plane = rg.Plane(a_pt, xaxis, yaxis)
        if not plane.IsValid:
            raise ValueError("P_hipRafter 无效。")

        self.Log.append("[OK] 已由输入直线段 AB 与 RefPlane.ZAxis 构建 P_hipRafter，原点为 A 点。")
        return plane

    def _mirror_brep_list_to_other_side(self, brep_list, plane):
        out = []
        if brep_list is None:
            return out

        xform = rg.Transform.Mirror(plane)
        for i, brep in enumerate(brep_list):
            dup = self._duplicate_brep_safe(brep)
            if dup is None:
                self.Log.append("[WARN] 第 {} 个 RafterPipe 无法复制，已跳过镜像。".format(i + 1))
                continue

            ok = dup.Transform(xform)
            if ok:
                out.append(dup)
            else:
                self.Log.append("[WARN] 第 {} 个 RafterPipe 镜像失败。".format(i + 1))
        return out

    def _mirror_brep_single_to_other_side(self, brep, plane):
        if brep is None:
            return None

        dup = self._duplicate_brep_safe(brep)
        if dup is None:
            self.Log.append("[WARN] SectionSolid 无法复制，镜像失败。")
            return None

        xform = rg.Transform.Mirror(plane)
        ok = dup.Transform(xform)
        if not ok:
            self.Log.append("[WARN] SectionSolid 镜像失败。")
            return None

        return dup

    def _line_plane_intersection(self, p0, p1, plane):
        dir_vec = p1 - p0
        if dir_vec.IsTiny(self.tol):
            raise ValueError("A'-B' 方向无效，无法与平面求交。")
        dir_vec.Unitize()

        ext = 1e6
        line = rg.Line(p0 - dir_vec * ext, p0 + dir_vec * ext)
        ok, t = rg.Intersect.Intersection.LinePlane(line, plane)
        if not ok:
            raise ValueError("直线 A'-B' 与截面平面 P 未求得交点。")
        return line.PointAt(t)

    def _project_point_to_line_along_vector(self, point, line_point0, line_point1, direction_vec):
        v = rg.Vector3d(direction_vec)
        if v.IsTiny(self.tol):
            raise ValueError("投影方向向量无效。")
        v.Unitize()

        line_dir = line_point1 - line_point0
        if line_dir.IsTiny(self.tol):
            raise ValueError("目标直线 D-C 无效。")
        line_dir.Unitize()

        line1 = rg.Line(point - v * 1e6, point + v * 1e6)
        line2 = rg.Line(line_point0 - line_dir * 1e6, line_point0 + line_dir * 1e6)

        success, ta, tb = rg.Intersect.Intersection.LineLine(line1, line2)
        if success:
            p_on_1 = line1.PointAt(ta)
            p_on_2 = line2.PointAt(tb)
            if p_on_1.DistanceTo(p_on_2) <= max(self.tol * 10.0, 1e-4):
                return rg.Point3d(
                    0.5 * (p_on_1.X + p_on_2.X),
                    0.5 * (p_on_1.Y + p_on_2.Y),
                    0.5 * (p_on_1.Z + p_on_2.Z)
                )

        raise ValueError("点 E 沿参考平面 Z 轴无法投影到直线 D-C 上。")

    def _midpoint(self, p0, p1):
        return rg.Point3d(
            0.5 * (p0.X + p1.X),
            0.5 * (p0.Y + p1.Y),
            0.5 * (p0.Z + p1.Z)
        )

    def _choose_interior_fprime(self, f_pt, eprime_pt, c_pt, dprime_pt, plane, ffprime_len):
        tangent = c_pt - eprime_pt
        if tangent.IsTiny(self.tol):
            raise ValueError("E' 与 C 重合，无法构建垂线方向。")
        tangent.Unitize()

        plane_normal = rg.Vector3d(plane.ZAxis)
        if plane_normal.IsTiny(self.tol):
            raise ValueError("参考平面 P 法向无效。")
        plane_normal.Unitize()

        perp = rg.Vector3d.CrossProduct(plane_normal, tangent)
        if perp.IsTiny(self.tol):
            raise ValueError("无法在平面 P 内构造垂直于 E'-C 的方向。")
        perp.Unitize()

        cand1 = f_pt + perp * ffprime_len
        cand2 = f_pt - perp * ffprime_len

        d1 = cand1.DistanceTo(dprime_pt)
        d2 = cand2.DistanceTo(dprime_pt)

        if d1 <= d2:
            return cand1
        return cand2

    def _choose_iprime_toward_aprime(self, i_pt, gprime_pt, h_pt, pprime, ii_len, aprime_pt):
        tangent = h_pt - gprime_pt
        if tangent.IsTiny(self.tol):
            raise ValueError("G' 与 H 重合，无法构造垂线方向。")
        tangent.Unitize()

        plane_normal = rg.Vector3d(pprime.ZAxis)
        if plane_normal.IsTiny(self.tol):
            raise ValueError("P' 法向无效。")
        plane_normal.Unitize()

        perp = rg.Vector3d.CrossProduct(plane_normal, tangent)
        if perp.IsTiny(self.tol):
            raise ValueError("无法在 P' 内构造垂直于 G'-H 的方向。")
        perp.Unitize()

        cand1 = i_pt + perp * ii_len
        cand2 = i_pt - perp * ii_len

        base_dist = i_pt.DistanceTo(aprime_pt)
        d1 = cand1.DistanceTo(aprime_pt)
        d2 = cand2.DistanceTo(aprime_pt)

        ok1 = d1 < base_dist - self.tol
        ok2 = d2 < base_dist - self.tol

        if ok1 and not ok2:
            return cand1
        if ok2 and not ok1:
            return cand2
        if d1 <= d2:
            return cand1
        return cand2

    def _build_arc_curve(self, p0, p1, p2, name_text):
        arc = rg.Arc(p0, p1, p2)
        if not arc.IsValid:
            raise ValueError("弧线 {} 构建失败。".format(name_text))
        return rg.ArcCurve(arc)

    def _build_section_curve_with_arc(self, c_pt, dprime_pt, eprime_pt, arc_curve):
        seg_cd = rg.LineCurve(c_pt, dprime_pt)
        seg_de = rg.LineCurve(dprime_pt, eprime_pt)

        pc = rg.PolyCurve()
        if not pc.Append(seg_cd):
            raise ValueError("截面线段 C-D' 添加失败。")
        if not pc.Append(seg_de):
            raise ValueError("截面线段 D'-E' 添加失败。")
        if not pc.Append(arc_curve):
            raise ValueError("截面弧段 E'-F'-C 添加失败。")

        joined = pc.ToNurbsCurve()
        if joined is None or not joined.IsValid:
            raise ValueError("截面曲线拼合失败。")

        if not joined.IsClosed:
            if joined.PointAtEnd.DistanceTo(joined.PointAtStart) <= max(self.tol * 10.0, 1e-4):
                joined.MakeClosed(self.tol)

        if not joined.IsClosed:
            raise ValueError("截面曲线未闭合。")

        return joined

    def _cap_curve(self, curve):
        planar_breps = rg.Brep.CreatePlanarBreps(curve, self.tol)
        if planar_breps and len(planar_breps) > 0:
            return planar_breps[0]
        return None

    def _build_solid(self, section_curve, plane):
        if self.Thickness is None:
            self.Log.append("[WARN] Thickness 为空，跳过实体构建。")
            return None, None, None, None, None, None

        t = float(self.Thickness)
        if t <= self.tol:
            self.Log.append("[WARN] Thickness <= 0，跳过实体构建。")
            return None, None, None, None, None, None

        normal = rg.Vector3d(plane.ZAxis)
        if normal.IsTiny(self.tol):
            raise ValueError("截面平面法向无效，无法偏移截面。")
        normal.Unitize()

        vec_pos = normal * (t * 0.5)
        vec_neg = -normal * (t * 0.5)

        profile_pos = self._move_curve(section_curve, vec_pos)
        profile_neg = self._move_curve(section_curve, vec_neg)

        if profile_pos is None or profile_neg is None:
            raise ValueError("截面偏移失败。")

        cap_pos = self._cap_curve(profile_pos)
        cap_neg = self._cap_curve(profile_neg)
        if cap_pos is None or cap_neg is None:
            raise ValueError("截面封面失败。")

        lofts = rg.Brep.CreateFromLoft(
            [profile_neg, profile_pos],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )
        side_loft = lofts[0] if lofts and len(lofts) > 0 else None
        if side_loft is None:
            raise ValueError("CreateFromLoft 失败，无法生成侧壁。")

        joined = rg.Brep.JoinBreps([side_loft, cap_pos, cap_neg], self.tol)
        if not joined or len(joined) == 0:
            raise ValueError("JoinBreps 失败，无法形成实体。")

        solid = joined[0]
        if not solid.IsSolid:
            try:
                capped = solid.CapPlanarHoles(self.tol)
                if capped is not None:
                    solid = capped
            except:
                pass

        if solid.IsSolid:
            self.Log.append("[OK] 已通过双侧偏移 + Loft + 封面成功生成封闭体。")
        else:
            self.Log.append("[WARN] 已生成 Brep，但结果不是严格封闭体。")

        return solid, profile_pos, profile_neg, side_loft, cap_pos, cap_neg

    # ------------------------------------------------------------------
    # Part 3 helpers
    # ------------------------------------------------------------------
    def _curve_from_c_to_eprime(self, arc_curve, c_pt):
        dup = arc_curve.DuplicateCurve()
        if dup.PointAtStart.DistanceTo(c_pt) > dup.PointAtEnd.DistanceTo(c_pt):
            dup.Reverse()
        return dup

    def _divide_curve_by_length_from_start(self, curve, step_len):
        if curve is None:
            raise ValueError("待等分曲线为空。")
        if step_len is None:
            raise ValueError("椽距 ChuanJu 不能为空。")

        d = float(step_len)
        if d <= self.tol:
            raise ValueError("椽距 ChuanJu 必须大于 0。")

        params = curve.DivideByLength(d, True)
        if params is None or len(params) == 0:
            return [curve.PointAtStart, curve.PointAtEnd]

        pts = [curve.PointAt(t) for t in params]

        if pts[0].DistanceTo(curve.PointAtStart) > self.tol:
            pts.insert(0, curve.PointAtStart)

        if pts[-1].DistanceTo(curve.PointAtEnd) > self.tol:
            pts.append(curve.PointAtEnd)

        return pts

    def _make_guide_surface_from_arc(self, arc_curve, zaxis, ref_pts):
        if arc_curve is None:
            raise ValueError("参照弧线 G'-I'-H 为空，无法生成导向曲面。")

        v = rg.Vector3d(zaxis)
        if v.IsTiny(self.tol):
            raise ValueError("参考平面 Z 轴无效，无法拉伸导向曲面。")
        v.Unitize()

        max_d = 0.0
        if ref_pts:
            for i in range(len(ref_pts)):
                for j in range(i + 1, len(ref_pts)):
                    d = ref_pts[i].DistanceTo(ref_pts[j])
                    if d > max_d:
                        max_d = d
        height = max(1000.0, max_d * 5.0)

        srf = rg.Surface.CreateExtrusion(arc_curve, v * height)
        if srf is None:
            raise ValueError("导向曲面拉伸失败。")

        brep = srf.ToBrep()
        if brep is None or not brep.IsValid:
            raise ValueError("导向曲面 Brep 转换失败。")
        return brep

    def _ray_intersect_brep(self, origin_pt, through_pt, brep):
        dir_vec = through_pt - origin_pt
        if dir_vec.IsTiny(self.tol):
            raise ValueError("射线方向无效。")
        dir_vec.Unitize()

        ext = max(10000.0, origin_pt.DistanceTo(through_pt) * 20.0)
        line = rg.Line(origin_pt, origin_pt + dir_vec * ext)
        line_crv = rg.LineCurve(line)

        try:
            rc, overlaps, pts = rg.Intersect.Intersection.CurveBrep(line_crv, brep, self.tol)
        except:
            rc = False
            pts = None

        if not rc or pts is None or len(pts) == 0:
            raise ValueError("射线未与导向曲面相交。")

        base_dist = origin_pt.DistanceTo(through_pt)
        valid_pts = []
        for p in pts:
            dd = origin_pt.DistanceTo(p)
            if dd >= base_dist - self.tol:
                valid_pts.append((dd, p))

        if len(valid_pts) == 0:
            valid_pts = [(origin_pt.DistanceTo(p), p) for p in pts]

        valid_pts.sort(key=lambda x: x[0])
        return valid_pts[0][1]

    def _build_rafter_pipes(self, center_lines, chuanjing):
        if center_lines is None or len(center_lines) == 0:
            return []

        if chuanjing is None:
            self.Log.append("[INFO] ChuanJing 为空，跳过椽管实体生成。")
            return []

        d = float(chuanjing)
        if d <= self.tol:
            self.Log.append("[WARN] ChuanJing <= 0，跳过椽管实体生成。")
            return []

        radius = d * 0.5
        pipes = []

        for i, ln_crv in enumerate(center_lines):
            if ln_crv is None or not ln_crv.IsValid:
                self.Log.append("[WARN] 第 {} 根椽中心线无效，已跳过成管。".format(i + 1))
                continue

            try:
                pipe_breps = rg.Brep.CreatePipe(
                    ln_crv,
                    radius,
                    False,
                    rg.PipeCapMode.Flat,
                    True,
                    self.tol,
                    self.angle_tol
                )
            except Exception as ex:
                self.Log.append("[WARN] 第 {} 根椽成管失败: {}".format(i + 1, ex))
                continue

            if pipe_breps and len(pipe_breps) > 0:
                pipes.append(pipe_breps[0])
            else:
                self.Log.append("[WARN] 第 {} 根椽成管未返回结果。".format(i + 1))

        return pipes

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def build(self):
        res = ZhuanJiaoBuChuanResult()

        self.Log.append("[INFO] 开始执行轉角布椽构建。")

        line_ab = self._as_line(self.AB, "AB")
        line_ac = self._as_line(self.AC, "AC")
        line_cd = self._as_line(self.CD, "CD")
        self.Log.append("[OK] 已读取 AB、AC、CD 三条输入直线。")

        a_pt, ab_i, _ = self._shared_endpoint(line_ab, line_ac, "AB", "AC")
        c_pt, _, cd_i = self._shared_endpoint(line_ac, line_cd, "AC", "CD")

        b_pt = line_ab.To if ab_i == 0 else line_ab.From
        d_pt = line_cd.To if cd_i == 0 else line_cd.From

        res.APoint = a_pt
        res.BPoint = b_pt
        res.CPoint = c_pt
        res.DPoint = d_pt
        self.Log.append("[OK] 已自动识别关键点 A、B、C、D。")

        ref_plane = self._make_ref_plane_at_a(a_pt)

        if self.AAPrimeLength is None:
            raise ValueError("AAPrimeLength 不能为空。")
        if self.DEPrimeLength is None:
            raise ValueError("DEPrimeLength 不能为空。")
        if self.FFPrimeLength is None:
            raise ValueError("FFPrimeLength 不能为空。")

        aaprime_len = float(self.AAPrimeLength)
        deprime_len = float(self.DEPrimeLength)
        ffprime_len = float(self.FFPrimeLength)

        self.Log.append("[INFO] AAPrimeLength = {:.6f}".format(aaprime_len))
        self.Log.append("[INFO] DEPrimeLength = {:.6f}".format(deprime_len))
        self.Log.append("[INFO] FFPrimeLength = {:.6f}".format(ffprime_len))

        # ---------------------------
        # 第1部分
        # ---------------------------
        a_prime = self._point_along(a_pt, c_pt, aaprime_len)
        move_vec = a_prime - a_pt
        b_prime = self._move_point(b_pt, move_vec)
        ab_prime_line = self._line_curve(a_prime, b_prime)

        res.APrime = a_prime
        res.BPrime = b_prime
        res.ABPrimeLine = ab_prime_line
        self.Log.append("[OK] 已由 A-B 沿 A-C 方向平移得到 A'-B'。")

        section_plane = self._build_section_plane(d_pt, c_pt, ref_plane)
        res.SectionPlane = section_plane
        self.Log.append("[OK] 已由 C-D 与参考平面 Z 方向构建截面平面 P。")

        e_pt = self._line_plane_intersection(a_prime, b_prime, section_plane)
        res.EPoint = e_pt
        self.Log.append("[OK] 已求得 A'-B' 与截面平面 P 的交点 E。")

        d_prime = self._project_point_to_line_along_vector(
            e_pt, d_pt, c_pt, ref_plane.ZAxis
        )
        res.DPrime = d_prime
        self.Log.append("[OK] 已将点 E 沿参考平面 Z 轴方向投影到直线 D-C 上，得到 D'。")

        dist_dprime_e = d_prime.DistanceTo(e_pt)
        self.Log.append("[INFO] D'-E = {:.6f}".format(dist_dprime_e))
        if dist_dprime_e <= self.tol:
            raise ValueError("D' 与 E 重合，无法继续求 E'。")
        if deprime_len > dist_dprime_e + self.tol:
            self.Log.append("[WARN] DEPrimeLength 大于 D'-E 实际长度，E' 将落在线段延长线上。")

        e_prime = self._point_along(d_prime, e_pt, deprime_len)
        ed_line = self._line_curve(e_pt, d_prime)

        res.EPrime = e_prime
        res.EDLine = ed_line
        self.Log.append("[OK] 已在 E-D' 上按 D'-E' 长度提取 E'，并构建 E-D'。")

        f_pt = self._midpoint(e_pt, c_pt)
        res.FPoint = f_pt
        self.Log.append("[OK] 已取 E-C 中点 F。")

        f_prime = self._choose_interior_fprime(
            f_pt, e_prime, c_pt, d_prime, section_plane, ffprime_len
        )
        res.FPrime = f_prime
        self.Log.append("[OK] 已在平面 P 内得到垂直于 E'-C 且位于截面内部的点 F'。")

        arc_curve = self._build_arc_curve(e_prime, f_prime, c_pt, "E'-F'-C")
        res.ArcCurve = arc_curve
        self.Log.append("[OK] 已构建弧线段 E'-F'-C。")

        section_curve = self._build_section_curve_with_arc(c_pt, d_prime, e_prime, arc_curve)
        res.SectionCurve = section_curve
        self.Log.append("[OK] 已构建含弧闭合截面 C-D'-E'-(Arc)-C。")

        solid, profile_pos, profile_neg, side_loft, cap_pos, cap_neg = self._build_solid(section_curve, section_plane)
        res.SectionSolid = solid
        res.ProfilePos = profile_pos
        res.ProfileNeg = profile_neg
        res.SideLoft = side_loft
        res.CapPos = cap_pos
        res.CapNeg = cap_neg

        if solid is not None:
            self.Log.append("[OK] 已完成基于含弧截面的双侧偏移、Loft、封面并合并为封闭体。")

        # ---------------------------
        # 第2部分
        # ---------------------------
        h_pt = None
        p_prime = None
        g_prime = None
        arc_gih = None

        if self.H is None:
            self.Log.append("[INFO] 第2部分未执行：H 为空。")
        elif self.BPrimeGLength is None:
            self.Log.append("[INFO] 第2部分未执行：BPrimeGLength 为空。")
        elif self.IIPrimeLength is None:
            self.Log.append("[INFO] 第2部分未执行：IIPrimeLength 为空。")
        else:
            h_pt = self._coerce_point(self.H)
            if h_pt is None:
                raise ValueError("输入 H 无法识别为 Point3d。")

            bprime_g_len = float(self.BPrimeGLength)
            iiprime_len = float(self.IIPrimeLength)

            self.Log.append("[INFO] BPrimeGLength = {:.6f}".format(bprime_g_len))
            self.Log.append("[INFO] IIPrimeLength = {:.6f}".format(iiprime_len))

            ab_prime_len = a_prime.DistanceTo(b_prime)
            if bprime_g_len > ab_prime_len + self.tol:
                self.Log.append("[WARN] BPrimeGLength 大于 A'-B' 实际长度，G 将落在线段延长线上。")

            g_pt = self._point_along(b_prime, a_prime, bprime_g_len)
            res.GPoint = g_pt
            self.Log.append("[OK] 已在 A'-B' 上提取点 G。")

            p_prime = self._make_plane_at_point(ref_plane, h_pt)
            res.PPrime = p_prime
            self.Log.append("[OK] 已建立参考平面 P'，其原点位于 H。")

            g_prime = self._project_point_to_plane_along_vector(g_pt, p_prime, ref_plane.ZAxis)
            res.GPrime = g_prime
            self.Log.append("[OK] 已将点 G 沿参考平面 Z 轴方向投影到 P' 上，得到 G'。")

            gh_line = self._line_curve(g_prime, h_pt)
            res.GHLine = gh_line
            i_pt = self._midpoint(g_prime, h_pt)
            res.IPoint = i_pt
            self.Log.append("[OK] 已构建 G'-H，并取得其中点 I。")

            i_prime = self._choose_iprime_toward_aprime(
                i_pt, g_prime, h_pt, p_prime, iiprime_len, a_prime
            )
            res.IPrime = i_prime
            self.Log.append("[OK] 已在 P' 内得到垂直于 G'-H 且朝向 A' 的点 I'。")
            self.Log.append("[INFO] I-A' = {:.6f}".format(i_pt.DistanceTo(a_prime)))
            self.Log.append("[INFO] I'-A' = {:.6f}".format(i_prime.DistanceTo(a_prime)))

            arc_gih = self._build_arc_curve(g_prime, i_prime, h_pt, "G'-I'-H")
            res.Arc_GPrime_IPrime_H = arc_gih
            self.Log.append("[OK] 已构建弧线 G'-I'-H。")

        # ---------------------------
        # 第3部分
        # ---------------------------
        if self.ChuanJu is None:
            self.Log.append("[INFO] 第3部分未执行：ChuanJu 为空。")
        elif arc_gih is None or g_prime is None or p_prime is None or h_pt is None:
            self.Log.append("[INFO] 第3部分未执行：第2部分关键几何未完成。")
        else:
            chuanju = float(self.ChuanJu)
            self.Log.append("[INFO] ChuanJu = {:.6f}".format(chuanju))

            arc_c_to_eprime = self._curve_from_c_to_eprime(arc_curve, c_pt)
            res.Arc_CToEPrime = arc_c_to_eprime
            div_pts = self._divide_curve_by_length_from_start(arc_c_to_eprime, chuanju)
            res.ArcDivisionPoints = div_pts
            self.Log.append("[OK] 已从 C 端开始按椽距等分弧线 C-E'，得到 {} 个点。".format(len(div_pts)))

            div_lines = []
            for pt in div_pts:
                div_lines.append(rg.LineCurve(a_prime, pt))
            res.ArcDivisionLines = div_lines
            self.Log.append("[OK] 已由 A' 到各等分点构建等分直线段。")

            guide_surface = self._make_guide_surface_from_arc(
                arc_gih,
                ref_plane.ZAxis,
                [a_prime, b_prime, c_pt, d_prime, e_prime, g_prime, h_pt]
            )
            res.GuideSurface = guide_surface
            self.Log.append("[OK] 已由弧线 G'-I'-H 沿参考平面 Z 轴正方向拉伸得到导向曲面。")

            rafter_center_lines = []
            hit_count = 0
            for pt in div_pts:
                try:
                    hit_pt = self._ray_intersect_brep(a_prime, pt, guide_surface)
                    rafter_center_lines.append(rg.LineCurve(a_prime, hit_pt))
                    hit_count += 1
                except Exception as ex:
                    self.Log.append("[WARN] 某条椽中心线未能延伸到导向曲面: {}".format(ex))

            res.RafterCenterLines = rafter_center_lines
            self.Log.append("[OK] 已获得 {} 条最终转角步椽中心线。".format(hit_count))

            pipes = self._build_rafter_pipes(rafter_center_lines, self.ChuanJing)
            res.RafterPipes = pipes
            self.Log.append("[OK] 已生成 {} 个椽管实体。".format(len(pipes)))

            # 镜像到 P_hipRafter 的另一侧
            try:
                p_hip = self._build_hip_rafter_plane(line_ab, ref_plane, a_pt)
                res.P_hipRafter = p_hip

                mirrored_pipes = self._mirror_brep_list_to_other_side(pipes, p_hip)
                res.MirroredRafterPipes = mirrored_pipes
                self.Log.append("[OK] 已将 RafterPipes 镜像到 P_hipRafter 的另一侧，共 {} 个。".format(len(mirrored_pipes)))

                mirrored_section = self._mirror_brep_single_to_other_side(solid, p_hip)
                res.MirroredSectionSolid = mirrored_section
                if mirrored_section is not None:
                    self.Log.append("[OK] 已将 SectionSolid 镜像到 P_hipRafter 的另一侧。")

            except Exception as ex:
                self.Log.append("[WARN] 第3部分镜像失败: {}".format(ex))

        res.Log = list(self.Log)
        return res


# ======================================================================
# Solver 主类
# ======================================================================
class ZhuanJiaoBuChuanSolver(object):
    def __init__(self,
                 AB=None,
                 AC=None,
                 CD=None,
                 RefPlane=None,
                 AAPrimeLength=None,
                 DEPrimeLength=None,
                 FFPrimeLength=None,
                 Thickness=None,
                 H=None,
                 BPrimeGLength=None,
                 IIPrimeLength=None,
                 ChuanJu=None,
                 ChuanJing=None,
                 ghenv=None):

        self.AB = AB
        self.AC = AC
        self.CD = CD
        self.RefPlane = RefPlane
        self.AAPrimeLength = AAPrimeLength
        self.DEPrimeLength = DEPrimeLength
        self.FFPrimeLength = FFPrimeLength
        self.Thickness = Thickness

        self.H = H
        self.BPrimeGLength = BPrimeGLength
        self.IIPrimeLength = IIPrimeLength
        self.ChuanJu = ChuanJu
        self.ChuanJing = ChuanJing

        self.ghenv = ghenv

        self.SectionPlane = None
        self.SectionCurve = None
        self.SectionSolid = None

        self.APoint = None
        self.BPoint = None
        self.CPoint = None
        self.DPoint = None
        self.DPrime = None

        self.APrime = None
        self.BPrime = None
        self.EPoint = None
        self.EPrime = None
        self.FPoint = None
        self.FPrime = None

        self.ABPrimeLine = None
        self.EDLine = None
        self.ArcCurve = None

        self.ProfilePos = None
        self.ProfileNeg = None
        self.SideLoft = None
        self.CapPos = None
        self.CapNeg = None

        self.GPoint = None
        self.PPrime = None
        self.GPrime = None
        self.GHLine = None
        self.IPoint = None
        self.IPrime = None
        self.Arc_GPrime_IPrime_H = None

        self.Arc_CToEPrime = None
        self.ArcDivisionPoints = None
        self.ArcDivisionLines = None
        self.GuideSurface = None
        self.RafterCenterLines = None
        self.RafterPipes = None

        self.P_hipRafter = None
        self.MirroredRafterPipes = None
        self.MirroredSectionSolid = None

        self.Log = []

    def _apply_result(self, result):
        self.SectionPlane = result.SectionPlane
        self.SectionCurve = result.SectionCurve
        self.SectionSolid = result.SectionSolid

        self.APoint = result.APoint
        self.BPoint = result.BPoint
        self.CPoint = result.CPoint
        self.DPoint = result.DPoint
        self.DPrime = result.DPrime

        self.APrime = result.APrime
        self.BPrime = result.BPrime
        self.EPoint = result.EPoint
        self.EPrime = result.EPrime
        self.FPoint = result.FPoint
        self.FPrime = result.FPrime

        self.ABPrimeLine = result.ABPrimeLine
        self.EDLine = result.EDLine
        self.ArcCurve = result.ArcCurve

        self.ProfilePos = result.ProfilePos
        self.ProfileNeg = result.ProfileNeg
        self.SideLoft = result.SideLoft
        self.CapPos = result.CapPos
        self.CapNeg = result.CapNeg

        self.GPoint = result.GPoint
        self.PPrime = result.PPrime
        self.GPrime = result.GPrime
        self.GHLine = result.GHLine
        self.IPoint = result.IPoint
        self.IPrime = result.IPrime
        self.Arc_GPrime_IPrime_H = result.Arc_GPrime_IPrime_H

        self.Arc_CToEPrime = result.Arc_CToEPrime
        self.ArcDivisionPoints = result.ArcDivisionPoints
        self.ArcDivisionLines = result.ArcDivisionLines
        self.GuideSurface = result.GuideSurface
        self.RafterCenterLines = result.RafterCenterLines
        self.RafterPipes = result.RafterPipes

        self.P_hipRafter = result.P_hipRafter
        self.MirroredRafterPipes = result.MirroredRafterPipes
        self.MirroredSectionSolid = result.MirroredSectionSolid

        self.Log = list(result.Log) if result.Log else []

    def run(self):
        try:
            builder = ZhuanJiaoBuChuanBuilder(
                AB=self.AB,
                AC=self.AC,
                CD=self.CD,
                RefPlane=self.RefPlane,
                AAPrimeLength=self.AAPrimeLength,
                DEPrimeLength=self.DEPrimeLength,
                FFPrimeLength=self.FFPrimeLength,
                Thickness=self.Thickness,
                H=self.H,
                BPrimeGLength=self.BPrimeGLength,
                IIPrimeLength=self.IIPrimeLength,
                ChuanJu=self.ChuanJu,
                ChuanJing=self.ChuanJing,
                ghenv=self.ghenv
            )
            result = builder.build()
            self._apply_result(result)

        except Exception as e:
            self.Log.append("[ERR] 轉角布椽构建失败: {}".format(e))

        return self

if __name__=="__main__":
    # ======================================================================
    # GH 输入读取
    # 不依赖 if __name__ == "__main__"
    # ======================================================================

    try:
        _AB = AB
    except:
        _AB = None

    try:
        _AC = AC
    except:
        _AC = None

    try:
        _CD = CD
    except:
        _CD = None

    try:
        _RefPlane = RefPlane
    except:
        _RefPlane = None

    try:
        _AAPrimeLength = AAPrimeLength
    except:
        _AAPrimeLength = None

    try:
        _DEPrimeLength = DEPrimeLength
    except:
        _DEPrimeLength = None

    try:
        _FFPrimeLength = FFPrimeLength
    except:
        _FFPrimeLength = None

    try:
        _Thickness = Thickness
    except:
        _Thickness = None

    try:
        _H = H
    except:
        _H = None

    try:
        _BPrimeGLength = BPrimeGLength
    except:
        _BPrimeGLength = None

    try:
        _IIPrimeLength = IIPrimeLength
    except:
        _IIPrimeLength = None

    try:
        _ChuanJu = ChuanJu
    except:
        _ChuanJu = None

    try:
        _ChuanJing = ChuanJing
    except:
        _ChuanJing = None


    # ======================================================================
    # 执行求解
    # ======================================================================
    solver = ZhuanJiaoBuChuanSolver(
        AB=_AB,
        AC=_AC,
        CD=_CD,
        RefPlane=_RefPlane,
        AAPrimeLength=_AAPrimeLength,
        DEPrimeLength=_DEPrimeLength,
        FFPrimeLength=_FFPrimeLength,
        Thickness=_Thickness,
        H=_H,
        BPrimeGLength=_BPrimeGLength,
        IIPrimeLength=_IIPrimeLength,
        ChuanJu=_ChuanJu,
        ChuanJing=_ChuanJing,
        ghenv=ghenv
    )
    solver.run()


    # ======================================================================
    # 固定正式输出
    # ======================================================================
    SectionCurve = solver.SectionCurve
    SectionSolid = solver.SectionSolid
    Log = solver.Log


    # ======================================================================
    # 绑定区可选输出（按需在 GH 中添加同名输出端）
    # ======================================================================
    try:
        SectionPlane = solver.SectionPlane

        APoint = solver.APoint
        BPoint = solver.BPoint
        CPoint = solver.CPoint
        DPoint = solver.DPoint
        DPrime = solver.DPrime

        APrime = solver.APrime
        BPrime = solver.BPrime
        EPoint = solver.EPoint
        EPrime = solver.EPrime
        FPoint = solver.FPoint
        FPrime = solver.FPrime

        ABPrimeLine = solver.ABPrimeLine
        EDLine = solver.EDLine
        ArcCurve = solver.ArcCurve

        ProfilePos = solver.ProfilePos
        ProfileNeg = solver.ProfileNeg
        SideLoft = solver.SideLoft
        CapPos = solver.CapPos
        CapNeg = solver.CapNeg

        GPoint = solver.GPoint
        PPrime = solver.PPrime
        GPrime = solver.GPrime
        GHLine = solver.GHLine
        IPoint = solver.IPoint
        IPrime = solver.IPrime
        Arc_GPrime_IPrime_H = solver.Arc_GPrime_IPrime_H

        Arc_CToEPrime = solver.Arc_CToEPrime
        ArcDivisionPoints = solver.ArcDivisionPoints
        ArcDivisionLines = solver.ArcDivisionLines
        GuideSurface = solver.GuideSurface
        RafterCenterLines = solver.RafterCenterLines
        RafterPipes = solver.RafterPipes

        P_hipRafter = solver.P_hipRafter
        MirroredRafterPipes = solver.MirroredRafterPipes
        MirroredSectionSolid = solver.MirroredSectionSolid
    except:
        pass
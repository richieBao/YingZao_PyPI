# -*- coding: utf-8 -*-
import Rhino
import Rhino.Geometry as rg
import math


# =========================================================
# GhPython Inputs (建议你在组件Inputs中按这些命名)
# ---------------------------------------------------------
# base_point   : Point3d   # F 点（定位点）
# RefPlaneMode : str       # "WorldXZ"(默认) / "WorldXY" / "WorldYZ" / "XY" / "XZ" / "YZ"
#
# rect_len     : float     # D-F (以及 A-E) 长度，默认 34.560343
# rect_h       : float     # D-A (以及 F-E) 高度，默认 15
#
# EH_len       : float     # E-H，默认 2
# HI_len       : float     # H-I，默认 1
# KL_len       : float     # L-K，默认 2
# KN_len       : float     # N-K，默认 3
# offset_dist  : float     # 偏移到两侧距离，默认 5
#
# Outputs (你可以按需改成你组件的输出端名)
# ---------------------------------------------------------
# PtsKeys  : list[str]
# PtsVals  : list[Point3d]
# Curves   : list[Curve]
# Surface  : Brep      # 最终闭合 Brep（若闭合失败则回退为 side_surface）
# SideSurface : Brep   # 原始封闭曲面（侧向曲面，便于调试）
# Brep     : Brep      # 同 Surface（为兼容你可能已有的输出端命名）
# FPlanes  : list[Plane] # 过点F的参考平面 + 两个垂直参考平面的列表
# DH_OffsetLoft : Brep    # 直线 D-H 两侧偏移后放样得到的曲面（Brep）
# Log      : str
# =========================================================


class GeometryHelper:
    """几何辅助工具类"""

    @staticmethod
    def make_ref_plane(mode_str, origin=None):
        """创建参考平面
        Args:
            mode_str: "WorldXY"/"XY", "WorldXZ"/"XZ", "WorldYZ"/"YZ"
            origin: 平面原点，默认世界原点
        Returns:
            rg.Plane
        """
        if origin is None:
            origin = rg.Point3d(0.0, 0.0, 0.0)
        if mode_str is None:
            mode_str = "WorldXZ"
        m = str(mode_str).upper()

        if m in ("WORLDXY", "XY", "XY_PLANE"):
            x = rg.Vector3d(1.0, 0.0, 0.0)
            y = rg.Vector3d(0.0, 1.0, 0.0)
            return rg.Plane(origin, x, y)

        if m in ("WORLDYZ", "YZ", "YZ_PLANE"):
            x = rg.Vector3d(0.0, 1.0, 0.0)
            y = rg.Vector3d(0.0, 0.0, 1.0)
            return rg.Plane(origin, x, y)

        # 默认 XZ
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    @staticmethod
    def pt_on_plane(pl, x, y):
        """在平面上根据局部坐标创建点"""
        return pl.Origin + pl.XAxis * x + pl.YAxis * y

    @staticmethod
    def safe_unitize(v):
        """安全单位化向量"""
        vv = rg.Vector3d(v)
        if vv.IsTiny():
            return rg.Vector3d(0, 0, 0)
        vv.Unitize()
        return vv

    @staticmethod
    def line_line_intersection(p0, d0, p1, d1):
        """计算两条直线的交点"""
        l0 = rg.Line(p0, p0 + d0)
        l1 = rg.Line(p1, p1 + d1)
        rc, a, b = rg.Intersect.Intersection.LineLine(l0, l1)
        if not rc:
            return None
        return l0.PointAt(a)

    @staticmethod
    def create_arc_3pt(p1, p2, p3):
        """创建三点圆弧"""
        try:
            arc = rg.Arc(p1, p2, p3)
            if arc.IsValid:
                return rg.ArcCurve(arc)
        except:
            pass
        return rg.PolylineCurve([p1, p2, p3])

    @staticmethod
    def reverse_curve(crv):
        """反转曲线"""
        c = crv.DuplicateCurve()
        c.Reverse()
        return c

    @staticmethod
    def doc_tolerance(default_tol=0.001):
        """获取当前 RhinoDoc 的绝对公差（无 doc 时给默认值）"""
        try:
            doc = Rhino.RhinoDoc.ActiveDoc
            if doc is not None:
                tol = float(getattr(doc, 'ModelAbsoluteTolerance', default_tol))
                if tol > 0:
                    return tol
        except:
            pass
        return default_tol

    @staticmethod
    def create_planar_brep_from_curves(curves, tol=0.001):
        """由若干边界曲线创建平面 Brep（容错 Join/Close）"""
        if not curves:
            return None

        # 先尝试 Join
        joined = None
        try:
            j = rg.Curve.JoinCurves(curves, tol)
            if j and len(j) > 0:
                joined = j[0]
        except:
            joined = None

        if joined is None:
            # 退化：用 PolyCurve 顺序拼接
            try:
                pc = rg.PolyCurve()
                for c in curves:
                    if c is None:
                        continue
                    pc.Append(c)
                joined = pc
            except:
                joined = None

        if joined is None:
            return None

        # 确保闭合
        try:
            if not joined.IsClosed:
                joined.MakeClosed(tol)
        except:
            pass

        try:
            breps = rg.Brep.CreatePlanarBreps(joined, tol)
            if breps and len(breps) > 0:
                return breps[0]
        except:
            pass
        return None


class YouAngQiao:
    """有盎桥几何生成器"""

    def __init__(self, base_point=None, ref_plane_mode="WorldXZ",
                 rect_len=34.560343, rect_h=15.0,
                 EH_len=2.0, HI_len=1.0, KL_len=2.0, KN_len=3.0,
                 offset_dist=5.0):
        """初始化参数
        Args:
            base_point: F点位置
            ref_plane_mode: 参考平面模式
            rect_len: 矩形长度 (D-F, A-E)
            rect_h: 矩形高度 (D-A, F-E)
            EH_len: E到H的距离
            HI_len: H到I的距离
            KL_len: K到L的距离
            KN_len: K到N的距离
            offset_dist: 偏移距离
        """
        self.base_point = base_point if base_point else rg.Point3d(0, 0, 0)
        self.ref_plane_mode = ref_plane_mode
        self.rect_len = rect_len
        self.rect_h = rect_h
        self.EH_len = EH_len
        self.HI_len = HI_len
        self.KL_len = KL_len
        self.KN_len = KN_len
        self.offset_dist = offset_dist

        # 存储计算结果
        self.plane = None
        self.points = {}
        self.curves = []
        # 原始封闭曲面（侧向曲面）
        self.side_surface = None
        # 最终闭合 Brep（实体）
        self.closed_brep = None
        # 端部/侧部封口平面
        self.cap_surfaces = []
        # 过点 F 的参考平面及其垂直参考平面
        self.F_planes = []
        # 直线 D-H 两侧偏移后放样的曲面
        self.DH_offset_loft = None
        self.log = []

        self.helper = GeometryHelper()

    def generate(self):
        """生成完整几何"""
        self._create_reference_plane()
        self._create_F_planes()
        self._create_base_rectangle()
        self._create_middle_points()
        self._create_DH_offset_loft_surface()
        self._create_side_arcs()
        self._create_offset_arcs()
        self._create_top_bottom_arcs()
        self._create_surface()
        self._create_cap_surfaces()
        self._create_closed_brep()
        return self

    def _create_reference_plane(self):
        """步骤1: 创建参考平面"""
        self.plane = self.helper.make_ref_plane(self.ref_plane_mode, self.base_point)
        self.log.append("RefPlaneMode = {}".format(self.ref_plane_mode))
        self.log.append("F(base_point) = {}".format(self.base_point))

    def _create_F_planes(self):
        """新增：输出过点F的参考平面 + 两个垂直参考平面

        - FPlane0: 参考平面（self.plane，过点F）
        - FPlaneX: 过点F、包含参考平面 X 轴与 Z 轴（即与参考平面垂直）
        - FPlaneY: 过点F、包含参考平面 Y 轴与 Z 轴（即与参考平面垂直）
        """
        if self.plane is None:
            self.F_planes = []
            self.log.append("WARN: Ref plane missing, F_planes not created")
            return

        F = self.plane.Origin
        # 参考平面本身
        p0 = rg.Plane(self.plane)
        # 垂直平面1：X-Z 平面（法向 ~ Y）
        px = rg.Plane(F, self.plane.XAxis, self.plane.ZAxis)
        # 垂直平面2：Y-Z 平面（法向 ~ X）
        py = rg.Plane(F, self.plane.YAxis, self.plane.ZAxis)

        self.F_planes = [p0, px, py]
        self.log.append("F_planes created: [RefPlane, Plane(XZ@F), Plane(YZ@F)]")

    def _create_base_rectangle(self):
        """步骤2: 创建基础矩形 D-F-E-A"""
        pt = self.helper.pt_on_plane

        self.points['F'] = pt(self.plane, 0.0, 0.0)
        self.points['D'] = pt(self.plane, -self.rect_len, 0.0)
        self.points['E'] = pt(self.plane, 0.0, -self.rect_h)
        self.points['A'] = pt(self.plane, -self.rect_len, -self.rect_h)

        rect_pl = rg.Polyline([
            self.points['D'], self.points['F'],
            self.points['E'], self.points['A'],
            self.points['D']
        ])
        self.curves.append(rg.PolylineCurve(rect_pl))

    def _create_middle_points(self):
        """步骤3-4: 创建中间点 H, I, J, K, L, N"""
        E = self.points['E']
        D = self.points['D']
        F = self.points['F']

        # H, I 在 EF 上
        self.points['H'] = E + self.plane.YAxis * self.EH_len
        self.points['I'] = self.points['H'] + self.plane.YAxis * self.HI_len

        # 计算 J (DH平行线与DF的交点)
        v_DH = self.points['H'] - D
        v_DF = F - D

        J = self.helper.line_line_intersection(
            self.points['I'], v_DH, D, v_DF
        )
        if J is None:
            J = D + v_DF * 0.5
            self.log.append("WARN: J intersection failed, using fallback")
        self.points['J'] = J

        # 添加辅助线
        self.curves.append(rg.LineCurve(D, self.points['H']))
        self.curves.append(rg.LineCurve(J, self.points['I']))

        # K 为 J-I 中点
        I = self.points['I']
        self.points['K'] = rg.Point3d(
            0.5 * (J.X + I.X),
            0.5 * (J.Y + I.Y),
            0.5 * (J.Z + I.Z)
        )

        # L, N 垂直于 JI
        v_JI = I - J
        if v_JI.IsTiny():
            v_JI = self.plane.XAxis

        perp = rg.Vector3d.CrossProduct(self.plane.ZAxis, v_JI)
        perp = self.helper.safe_unitize(perp)

        # 选择向内方向
        if rg.Vector3d.Multiply(perp, -self.plane.YAxis) < 0:
            perp = -perp

        K = self.points['K']
        self.points['L'] = K + perp * self.KL_len
        self.points['N'] = K + perp * self.KN_len

    def _create_DH_offset_loft_surface(self):
        """新增：直线 D-H 垂直于参考平面两侧偏移后放样成面

        逻辑：
        - 取直线 D-H
        - 沿参考平面 ZAxis 方向 ±offset_dist 平移两条线
        - 对两条线 Loft 得到曲面（Brep）
        """
        D = self.points.get('D', None)
        H = self.points.get('H', None)
        if D is None or H is None or self.plane is None:
            self.DH_offset_loft = None
            self.log.append("WARN: D/H/plane missing, DH_offset_loft not created")
            return

        ln = rg.LineCurve(D, H)
        t1 = rg.Transform.Translation(self.plane.ZAxis * self.offset_dist)
        t2 = rg.Transform.Translation(-self.plane.ZAxis * self.offset_dist)
        ln1 = ln.DuplicateCurve();
        ln1.Transform(t1)
        ln2 = ln.DuplicateCurve();
        ln2.Transform(t2)

        # Loft
        loft = None
        try:
            loft = rg.Brep.CreateFromLoft(
                [ln1, ln2],
                rg.Point3d.Unset, rg.Point3d.Unset,
                rg.LoftType.Normal, False
            )
        except:
            loft = None

        brep = None
        if loft:
            try:
                brep = loft[0]
            except:
                if isinstance(loft, rg.Brep):
                    brep = loft

        self.DH_offset_loft = brep
        if self.DH_offset_loft is None:
            self.log.append("WARN: DH offset loft creation failed")
        else:
            self.log.append("DH offset loft created")
            # 记录偏移线便于检查
            self.curves.extend([ln1, ln2])

    def _create_side_arcs(self):
        """步骤5: 创建参考平面内的侧边弧线"""
        arc_JLI = self.helper.create_arc_3pt(
            self.points['J'], self.points['L'], self.points['I']
        )
        arc_DNH = self.helper.create_arc_3pt(
            self.points['D'], self.points['N'], self.points['H']
        )

        self.curves.append(arc_JLI)
        self.curves.append(arc_DNH)

        # 保存用于后续偏移
        self._arc_DNH = arc_DNH

    def _create_offset_arcs(self):
        """步骤6: 创建偏移后的侧边弧线"""
        t1 = rg.Transform.Translation(self.plane.ZAxis * self.offset_dist)
        t2 = rg.Transform.Translation(-self.plane.ZAxis * self.offset_dist)

        # 偏移弧线
        arc_side_1 = self._arc_DNH.DuplicateCurve()
        arc_side_2 = self._arc_DNH.DuplicateCurve()
        arc_side_1.Transform(t1)
        arc_side_2.Transform(t2)

        self._arc_side_1 = arc_side_1
        self._arc_side_2 = arc_side_2

        self.curves.append(arc_side_1)
        self.curves.append(arc_side_2)

        # 偏移点
        for suffix, transform in [('1', t1), ('2', t2)]:
            for key in ['D', 'N', 'H']:
                pt = rg.Point3d(self.points[key])
                pt.Transform(transform)
                self.points[key + suffix] = pt

    def _create_top_bottom_arcs(self):
        """步骤7: 创建顶部和底部弧线"""
        arc_top = self.helper.create_arc_3pt(
            self.points['D1'], self.points['J'], self.points['D2']
        )
        arc_bottom = self.helper.create_arc_3pt(
            self.points['H1'], self.points['I'], self.points['H2']
        )

        self._arc_top = arc_top
        self._arc_bottom = arc_bottom

        self.curves.append(arc_top)
        self.curves.append(arc_bottom)

        self.log.append("Arc D1-J-D2 created")
        self.log.append("Arc H1-I-H2 created")

    def _create_surface(self):
        """步骤8: 创建曲面"""
        # 构建边界循环: D1->H1->H2->D2->D1
        c1 = self._arc_side_1  # D1 -> H1
        c2 = self._arc_bottom  # H1 -> H2
        c3 = self.helper.reverse_curve(self._arc_side_2)  # H2 -> D2
        c4 = self.helper.reverse_curve(self._arc_top)  # D2 -> D1

        _edge = rg.Brep.CreateEdgeSurface([c1, c2, c3, c4])

        # 兼容不同 Rhino 版本
        surf_brep = None
        if isinstance(_edge, rg.Brep):
            surf_brep = _edge
        elif _edge is not None:
            try:
                if len(_edge) > 0:
                    surf_brep = _edge[0]
            except:
                try:
                    for b in _edge:
                        surf_brep = b
                        break
                except:
                    surf_brep = None

        # 失败则用 Loft
        if surf_brep is None:
            self.log.append("WARN: CreateEdgeSurface failed, using Loft")
            loft = rg.Brep.CreateFromLoft(
                [self._arc_side_1, self._arc_side_2],
                rg.Point3d.Unset, rg.Point3d.Unset,
                rg.LoftType.Normal, False
            )
            if loft:
                try:
                    surf_brep = loft[0]
                except:
                    if isinstance(loft, rg.Brep):
                        surf_brep = loft

        self.side_surface = surf_brep

    def _create_cap_surfaces(self):
        """步骤9: 依据图示封闭 S1~S4 四个平面"""
        tol = self.helper.doc_tolerance(0.001)

        # 1) 过点 F，沿参考平面 Z 轴两侧偏移得到 F1/F2
        F = self.points.get('F', None)
        if F is None:
            self.log.append("ERROR: F point missing")
            self._cap_surfaces = []
            return

        t1 = rg.Transform.Translation(self.plane.ZAxis * self.offset_dist)
        t2 = rg.Transform.Translation(-self.plane.ZAxis * self.offset_dist)

        F1 = rg.Point3d(F);
        F1.Transform(t1)
        F2 = rg.Point3d(F);
        F2.Transform(t2)
        self.points['F1'] = F1
        self.points['F2'] = F2

        # 线段
        ln_F1F2 = rg.LineCurve(F1, F2)
        ln_D1F1 = rg.LineCurve(self.points['D1'], F1)
        ln_D2F2 = rg.LineCurve(self.points['D2'], F2)
        ln_F1H1 = rg.LineCurve(F1, self.points['H1'])
        ln_F2H2 = rg.LineCurve(F2, self.points['H2'])

        # 用于 S1 的 D2->F2（比 D2->F 更符合两侧偏移闭合）
        ln_D2F2_for_S1 = ln_D2F2

        # 2) 四个平面：S1~S4
        # S1: 弧线 D1-J-D2 + D2-F2 + F2-F1 + F1-D1
        S1 = self.helper.create_planar_brep_from_curves(
            [self._arc_top, ln_D2F2_for_S1, ln_F1F2, ln_D1F1], tol
        )

        # S2: 线 F1-F2 + F1-H1 + F2-H2 + 弧线 H1-I-H2
        S2 = self.helper.create_planar_brep_from_curves(
            [ln_F1F2, ln_F1H1, ln_F2H2, self._arc_bottom], tol
        )

        # S3: 线 D1-F1 + F1-H1 + 弧线 D1-N1-H1
        S3 = self.helper.create_planar_brep_from_curves(
            [ln_D1F1, ln_F1H1, self._arc_side_1], tol
        )

        # S4: 线 D2-F2 + F2-H2 + 弧线 D2-N2-H2
        S4 = self.helper.create_planar_brep_from_curves(
            [ln_D2F2, ln_F2H2, self._arc_side_2], tol
        )

        self._cap_surfaces = [S1, S2, S3, S4]

        # 记录并输出到 Curves 便于检查
        self.curves.extend([ln_F1F2, ln_D1F1, ln_D2F2, ln_F1H1, ln_F2H2])

        for idx, s in enumerate(self._cap_surfaces, start=1):
            if s is None:
                self.log.append("WARN: S{} planar surface creation failed".format(idx))
            else:
                self.log.append("S{} created".format(idx))

    def _create_closed_brep(self):
        """步骤10: 将 S1~S4 与 side_surface 封闭为一个 Brep（实体）"""
        tol = self.helper.doc_tolerance(0.001)

        breps = []
        if self.side_surface is not None:
            breps.append(self.side_surface)

        caps = getattr(self, '_cap_surfaces', None)
        if caps:
            for b in caps:
                if b is not None:
                    breps.append(b)

        if not breps:
            self.log.append("ERROR: No breps to join")
            self.closed_brep = None
            return

        joined = None
        try:
            jb = rg.Brep.JoinBreps(breps, tol)
            if jb and len(jb) > 0:
                # JoinBreps 可能返回多个壳体，这里优先取面积最大的
                if len(jb) == 1:
                    joined = jb[0]
                else:
                    areas = []
                    for b in jb:
                        try:
                            amp = rg.AreaMassProperties.Compute(b)
                            areas.append((amp.Area if amp else 0.0, b))
                        except:
                            areas.append((0.0, b))
                    areas.sort(key=lambda x: x[0], reverse=True)
                    joined = areas[0][1]
        except:
            joined = None

        # 若还未闭合，再尝试 CreateSolid / CapPlanarHoles
        solid = None
        if joined is not None:
            try:
                if joined.IsSolid:
                    solid = joined
                else:
                    # CreateSolid 需要集合
                    sol = rg.Brep.CreateSolid([joined], tol)
                    if sol and len(sol) > 0:
                        solid = sol[0]
            except:
                solid = None

        if solid is None and joined is not None:
            try:
                capped = joined.CapPlanarHoles(tol)
                if capped is not None and capped.IsSolid:
                    solid = capped
            except:
                solid = None

        self.closed_brep = solid
        if self.closed_brep is None:
            self.log.append("WARN: Closed Brep creation failed (output side_surface instead)")
        else:
            self.log.append("Closed Brep created (IsSolid={})".format(self.closed_brep.IsSolid))

    def get_points_dict(self):
        """获取点字典"""
        return self.points

    def get_points_keys(self):
        """获取点名称列表"""
        return list(self.points.keys())

    def get_points_values(self):
        """获取点坐标列表"""
        return [self.points[k] for k in self.get_points_keys()]

    def get_curves(self):
        """获取所有曲线"""
        return self.curves

    def get_surface(self):
        """获取原始封闭曲面（侧向曲面）"""
        return self.side_surface

    def get_closed_brep(self):
        """获取最终闭合 Brep（实体）"""
        return self.closed_brep

    def get_F_planes(self):
        """获取过点 F 的参考平面及其两个垂直参考平面"""
        return self.F_planes

    def get_DH_offset_loft(self):
        """获取 D-H 两侧偏移后放样得到的曲面（Brep）"""
        return self.DH_offset_loft

    def get_log(self):
        """获取日志"""
        return "\n".join(self.log)

if __name__ == "__main__":
    # =========================================================
    # 主程序：从 GH 输入创建几何
    # =========================================================

    # 设置默认值
    if "rect_len" not in globals() or rect_len is None:
        rect_len = 34.560343
    if "rect_h" not in globals() or rect_h is None:
        rect_h = 15.0
    if "EH_len" not in globals() or EH_len is None:
        EH_len = 2.0
    if "HI_len" not in globals() or HI_len is None:
        HI_len = 1.0
    if "KL_len" not in globals() or KL_len is None:
        KL_len = 2.0
    if "KN_len" not in globals() or KN_len is None:
        KN_len = 3.0
    if "offset_dist" not in globals() or offset_dist is None:
        offset_dist = 5.0
    if "RefPlaneMode" not in globals() or RefPlaneMode is None:
        RefPlaneMode = "WorldXZ"
    if "base_point" not in globals() or base_point is None:
        base_point = rg.Point3d(0.0, 0.0, 0.0)

    # 创建几何生成器并生成
    generator = YouAngQiao(
        base_point=base_point,
        ref_plane_mode=RefPlaneMode,
        rect_len=rect_len,
        rect_h=rect_h,
        EH_len=EH_len,
        HI_len=HI_len,
        KL_len=KL_len,
        KN_len=KN_len,
        offset_dist=offset_dist
    )

    generator.generate()

    # 输出到 GH
    PtsKeys = generator.get_points_keys()
    PtsVals = generator.get_points_values()
    Curves = generator.get_curves()
    Brep = generator.get_closed_brep()
    SideSurface = generator.get_surface()
    Surface = Brep if Brep is not None else SideSurface
    Log = generator.get_log()
    FPlanes = generator.get_F_planes()
    DH_OffsetLoft = generator.get_DH_offset_loft()
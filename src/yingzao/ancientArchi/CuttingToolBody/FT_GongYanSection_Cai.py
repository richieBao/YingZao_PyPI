# -*- coding: utf-8 -*-
"""
FT_GongYan_SectionABFEA + Inner G-H-L-K-G + Loft + TopFace + ToolBrep (v4)

外截面：A-B-F-E-A
内截面：G-H-L-K-G
额外几何：
    - A-G、B-H 两条直线（隐含在截面构造中）
    - A-E-F-B 与“偏移后的”G-K-L-H 放样得到的侧面 LoftFace
    - 顶部 A-B-H'-G' 封面 TopFace（G'/H' 为 G/H 偏移后点）
    - SectionFace + LoftFace + TopFace join 成半个刀具壳体
    - 再沿 InnerSectionMoved 所在平面镜像，并 BooleanUnion 得到完整刀具 ToolBrep
    - 将 A 与镜像后的 A' 连线、B 与镜像后的 B' 连线，
      取各自中点作为原点，建立上表面的两个参考平面 TopPlaneA / TopPlaneB

参考平面：
- 默认为 XZ 平面
  - XAxis = World X（A-B 方向）
  - YAxis = World Z（截面“高”方向）
  - ZAxis = 法向（垂直截面）

输入（GhPython 组件）:
    SectionPlane   : rg.Plane | None
    A              : Point / Guid / Point3d
    RadiusFen      : float   (外弧半径 A-C / B-D)
    LengthFen      : float   (A-B 总长)
    InnerRadiusFen : float   (I-K / J-L 半径，同时 A-G、G-I、B-H、H-J 的长度)
    MoveFen        : float   (内截面沿平面法向平移距离)

输出:
    SectionFace        : rg.Brep | None
    Points             : list[rg.Point3d]  # [A,B,C,D,E,F]
    InnerSection       : rg.Brep | None
    InnerSectionMoved  : rg.Brep | None
    InnerPoints        : list[rg.Point3d]  # [G,I,J,H,L,K]
    LoftFace           : rg.Brep | None    # A-E-F-B vs moved G-K-L-H 放样面
    TopFace            : rg.Brep | None    # A-B-H'-G' 顶面
    ToolBrep           : rg.Brep | None    # 卷殺-材最终刀具
    TopPlaneA          : rg.Plane | None   # A-A' 中点为原点的上表面参考平面
    TopPlaneB          : rg.Plane | None   # B-B' 中点为原点的上表面参考平面
    Log                : list[str]
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import System
import math


# =========================================================
# 工具类：栱眼-材截面 & 侧面 & 顶面 & 刀具
# =========================================================
class FT_GongYanSectionABFEA(object):
    """
    构造栱眼-材端部外截面 A-B-F-E-A、
    内截面 G-H-L-K-G、
    A-E-F-B 与偏移 G-K-L-H 的放样面、
    顶部 A-B-H'-G' 封面、
    以及镜像并合并后的完整刀具 Brep，
    并基于 A/A'、B/B' 的中点生成两个上表面参考平面。
    """

    # ---------- 静态工具：把 GH 输入转为 Point3d ----------
    @staticmethod
    def coerce_point3d(obj, doc):
        """将 GH 输入转换为 Rhino.Geometry.Point3d。"""
        if isinstance(obj, rg.Point3d):
            return obj
        if isinstance(obj, rg.Point):
            return obj.Location
        if isinstance(obj, System.Guid):
            rh_obj = doc.Objects.Find(obj) if doc else None
            if rh_obj:
                geo = rh_obj.Geometry
                if isinstance(geo, rg.Point):
                    return geo.Location
        return None

    # ---------- 构造函数 ----------
    def __init__(self,
                 section_plane,
                 A_input,
                 radius_fen,
                 length_fen,
                 inner_radius_fen,
                 move_fen,
                 doc=None):
        self.doc = doc or sc.doc
        self.log = []

        # 原始输入
        self.raw_plane = section_plane
        self.raw_A = A_input
        self.raw_radius = radius_fen
        self.raw_length = length_fen
        self.raw_inner_radius = inner_radius_fen
        self.raw_move = move_fen

        # 内部状态
        self.tol = self.doc.ModelAbsoluteTolerance if self.doc else 1e-3
        self.base_plane = None      # 初始参考平面
        self.section_plane = None   # 原点平移到 A 后的参考平面

        # 外截面点
        self.A = self.B = self.C = self.D = self.E = self.F = None
        # 内截面点
        self.G = self.H = self.I = self.J = self.K = self.L = None

        # 参数
        self.radius = None          # 外弧半径
        self.length = None          # 总长
        self.inner_radius = None    # 内弧半径 + 内偏距
        self.move_dist = None       # 内截面平移距离
        self.move_xform = None      # 内截面平移的 Transform

        # 外截面各段曲线
        self.outer_arc_left_crv = None
        self.outer_arc_right_crv = None
        self.outer_top_crv = None
        self.outer_bot_crv = None

        # 内截面各段曲线
        self.inner_arc_left_crv = None
        self.inner_arc_right_crv = None
        self.inner_top_crv = None
        self.inner_bot_crv = None

        # 几何
        self.boundary_outer = None
        self.section_face_outer = None
        self.boundary_inner = None
        self.section_face_inner = None
        self.section_face_inner_moved = None

        self.loft_face = None       # A-E-F-B 与 moved G-K-L-H 放样面
        self.top_face = None        # A-B-H'-G' 顶面
        self.tool_brep = None       # 最终刀具 Brep

        # 上表面两个参考平面（A-A' 中点 & B-B' 中点）
        self.top_plane_A = None
        self.top_plane_B = None

    # ---------- 构建主入口 ----------
    def build(self):
        """
        返回:
            section_face_outer,
            outer_points [A..F],
            section_face_inner,
            section_face_inner_moved,
            inner_points [G,I,J,H,L,K],
            loft_face,
            top_face,
            tool_brep,
            top_plane_A,
            top_plane_B,
            log
        """
        self.log.append("=== FT_GongYanSectionABFEA.build() 开始 ===")
        self.log.append("Model tolerance = {:.6f}".format(self.tol))

        self._prepare_plane()
        self._prepare_A()
        self._prepare_params()
        self._move_plane_to_A()
        self._build_outer_feature_points()
        self._build_outer_curves_and_face()
        self._build_inner_section()
        self._build_loft_and_top()
        self._build_tool_brep()

        outer_points = [self.A, self.B, self.C, self.D, self.E, self.F]
        inner_points = [self.G, self.I, self.J, self.H, self.L, self.K]

        self.log.append("=== FT_GongYanSectionABFEA.build() 结束 ===")

        return (self.section_face_outer,
                outer_points,
                self.section_face_inner,
                self.section_face_inner_moved,
                inner_points,
                self.loft_face,
                self.top_face,
                self.tool_brep,
                self.top_plane_A,
                self.top_plane_B,
                self.log)

    # ---------- 步骤 1：处理参考平面（默认 XZ） ----------
    def _prepare_plane(self):
        if self.raw_plane is None:
            # 默认 XZ 平面：
            #   X 轴 = 世界 X (A-B 方向)
            #   Y 轴 = 世界 Z (截面“高”方向)
            origin = rg.Point3d(0, 0, 0)
            xdir   = rg.Vector3d(1, 0, 0)
            ydir   = rg.Vector3d(0, 0, 1)
            self.base_plane = rg.Plane(origin, xdir, ydir)
            self.log.append("SectionPlane 为空：使用默认 XZ 平面 (X=WorldX, Y=WorldZ)。")
        else:
            self.base_plane = self.raw_plane
            self.log.append("使用输入的 SectionPlane 作为参考平面。")

    # ---------- 步骤 2：处理 A 点 ----------
    def _prepare_A(self):
        self.A = self.coerce_point3d(self.raw_A, self.doc)
        if self.A is None:
            self.A = self.base_plane.Origin
            self.log.append("A 输入不是有效点，使用参考平面原点作为 A。")
        else:
            self.log.append("成功读取输入点 A：({:.3f}, {:.3f}, {:.3f})".format(
                self.A.X, self.A.Y, self.A.Z))

    # ---------- 步骤 3：处理参数 ----------
    def _prepare_params(self):
        # 外弧半径
        if self.raw_radius is None or self.raw_radius <= 0:
            self.radius = 3.0
            self.log.append("RadiusFen 未给或不合法，使用默认 3.0 分°。")
        else:
            self.radius = float(self.raw_radius)
            self.log.append("RadiusFen = {:.3f} 分°".format(self.radius))

        # 总长
        default_len = 20.0
        if self.raw_length is None:
            self.length = default_len
            self.log.append("LengthFen 未给，使用默认 20.0 分°。")
        else:
            self.length = float(self.raw_length)
            if self.length <= 2.0 * self.radius:
                self.log.append(
                    "LengthFen = {:.3f} <= 2*RadiusFen，几何会退化，强制改用默认 20.0 分°。".format(self.length)
                )
                self.length = default_len
            else:
                self.log.append("LengthFen = {:.3f} 分°".format(self.length))

        # 内弧半径 + 内偏距
        if self.raw_inner_radius is None or self.raw_inner_radius <= 0:
            self.inner_radius = 1.0
            self.log.append(
                "InnerRadiusFen 未给或不合法，使用默认 1.0 分°；"
                "并假定 A-G, G-I, B-H, H-J 均 = InnerRadiusFen。"
            )
        else:
            self.inner_radius = float(self.raw_inner_radius)
            self.log.append(
                "InnerRadiusFen = {:.3f} 分°，并假定 A-G, G-I, B-H, H-J 均为此值。".format(
                    self.inner_radius)
            )

        # 内截面平移距离
        if self.raw_move is None:
            self.move_dist = 5.0
            self.log.append("MoveFen 未给，使用默认 5.0 分°。")
        else:
            self.move_dist = float(self.raw_move)
            self.log.append("MoveFen = {:.3f} 分°".format(self.move_dist))

    # ---------- 步骤 4：把参考平面原点移到 A 点 ----------
    def _move_plane_to_A(self):
        self.section_plane = rg.Plane(self.A,
                                      self.base_plane.XAxis,
                                      self.base_plane.YAxis)
        self.log.append("已将参考平面原点移动到 A 点。")

    # 小工具：在 section_plane 局部 (u, v) 生成 3D 点
    def _pt_uv(self, u, v):
        return self.section_plane.PointAt(u, v)

    # ---------- 步骤 5：构建外截面特征点 A..F ----------
    def _build_outer_feature_points(self):
        r = self.radius
        L = self.length

        # 约定：上边在 v=0，下边在 v=-r
        self.A = self._pt_uv(0.0, 0.0)
        self.B = self._pt_uv(L, 0.0)
        self.C = self._pt_uv(r, 0.0)
        self.D = self._pt_uv(L - r, 0.0)
        self.E = self._pt_uv(r, -r)
        self.F = self._pt_uv(L - r, -r)

        self.log.append("外截面特征点 A,B,C,D,E,F 已生成。")

    # ---------- 步骤 6：构造外截面圆弧 + 直线 + 面 ----------
    def _build_outer_curves_and_face(self):
        r = self.radius

        # —— 两端圆弧（外）——
        plane_C = rg.Plane(self.C, self.section_plane.XAxis, self.section_plane.YAxis)
        plane_D = rg.Plane(self.D, self.section_plane.XAxis, self.section_plane.YAxis)

        # 左端弧 A-E：中间角 -3π/4
        uL = r * math.cos(-0.75 * math.pi)
        vL = r * math.sin(-0.75 * math.pi)
        mid_left = plane_C.PointAt(uL, vL)
        arc_left = rg.Arc(self.A, mid_left, self.E)
        self.outer_arc_left_crv = rg.ArcCurve(arc_left)

        # 右端弧 B-F：中间角 -π/4
        uR = r * math.cos(-0.25 * math.pi)
        vR = r * math.sin(-0.25 * math.pi)
        mid_right = plane_D.PointAt(uR, vR)
        arc_right = rg.Arc(self.B, mid_right, self.F)
        self.outer_arc_right_crv = rg.ArcCurve(arc_right)

        self.log.append("外截面两端 1/4 圆弧 AE 与 BF 已生成。")

        # 顶边 & 底边直线
        top_line = rg.Line(self.A, self.B)
        bot_line = rg.Line(self.F, self.E)  # F -> E，便于闭合方向一致

        self.outer_top_crv = top_line.ToNurbsCurve()
        self.outer_bot_crv = bot_line.ToNurbsCurve()

        seg_curves = [
            self.outer_top_crv,
            self.outer_arc_right_crv,
            self.outer_bot_crv,
            self.outer_arc_left_crv
        ]
        joined = rg.Curve.JoinCurves(seg_curves, self.tol)

        if not joined or len(joined) == 0:
            self.log.append("外截面：曲线拼接失败，无法得到闭合边界。")
            self.section_face_outer = None
            return

        boundary = joined[0]
        self.boundary_outer = boundary

        if not boundary.IsClosed:
            self.log.append("外截面：拼接后的边界不是闭合曲线，无法生成截面面。")
            self.section_face_outer = None
            return

        breps = rg.Brep.CreatePlanarBreps(boundary, self.tol)
        if breps and len(breps) > 0:
            self.section_face_outer = breps[0]
            self.log.append("外截面平面 Brep 生成成功。")
        else:
            self.section_face_outer = None
            self.log.append("外截面：CreatePlanarBreps 失败。")

    # ---------- 步骤 7：构造内截面 G-H-L-K-G ----------
    def _build_inner_section(self):
        r_in = self.inner_radius
        L = self.length

        # A(0) ... G(r_in) ... I(2r_in) ...
        # B(L) ... H(L-r_in) ... J(L-2r_in) ...
        self.G = self._pt_uv(r_in, 0.0)
        self.I = self._pt_uv(2.0 * r_in, 0.0)
        self.H = self._pt_uv(L - r_in, 0.0)
        self.J = self._pt_uv(L - 2.0 * r_in, 0.0)
        self.K = self._pt_uv(2.0 * r_in, -r_in)
        self.L = self._pt_uv(L - 2.0 * r_in, -r_in)

        self.log.append("内截面特征点 G,I,J,H,K,L 已生成。")

        # 两端内圆弧
        plane_I = rg.Plane(self.I, self.section_plane.XAxis, self.section_plane.YAxis)
        plane_J = rg.Plane(self.J, self.section_plane.XAxis, self.section_plane.YAxis)

        # 左端内弧 G-K：中间角 -3π/4
        uL = r_in * math.cos(-0.75 * math.pi)
        vL = r_in * math.sin(-0.75 * math.pi)
        mid_left = plane_I.PointAt(uL, vL)
        arc_left_in = rg.Arc(self.G, mid_left, self.K)
        self.inner_arc_left_crv = rg.ArcCurve(arc_left_in)

        # 右端内弧 H-L：中间角 -π/4
        uR = r_in * math.cos(-0.25 * math.pi)
        vR = r_in * math.sin(-0.25 * math.pi)
        mid_right = plane_J.PointAt(uR, vR)
        arc_right_in = rg.Arc(self.H, mid_right, self.L)
        self.inner_arc_right_crv = rg.ArcCurve(arc_right_in)

        self.log.append("内截面两端 1/4 圆弧 GK 与 HL 已生成。")

        # 顶边 G-H、底边 L-K（L->K，便于闭合）
        top_line_in = rg.Line(self.G, self.H)
        bot_line_in = rg.Line(self.L, self.K)

        self.inner_top_crv = top_line_in.ToNurbsCurve()
        self.inner_bot_crv = bot_line_in.ToNurbsCurve()

        seg_curves_in = [
            self.inner_top_crv,
            self.inner_arc_right_crv,
            self.inner_bot_crv,
            self.inner_arc_left_crv
        ]
        joined_in = rg.Curve.JoinCurves(seg_curves_in, self.tol)

        if not joined_in or len(joined_in) == 0:
            self.log.append("内截面：曲线拼接失败，无法得到闭合边界。")
            self.section_face_inner = None
            self.section_face_inner_moved = None
            self.move_xform = None
            return

        boundary_in = joined_in[0]
        self.boundary_inner = boundary_in

        if not boundary_in.IsClosed:
            self.log.append("内截面：拼接后的边界不是闭合曲线，无法生成截面面。")
            self.section_face_inner = None
            self.section_face_inner_moved = None
            self.move_xform = None
            return

        breps_in = rg.Brep.CreatePlanarBreps(boundary_in, self.tol)
        if breps_in and len(breps_in) > 0:
            self.section_face_inner = breps_in[0]
            self.log.append("内截面平面 Brep 生成成功。")
        else:
            self.section_face_inner = None
            self.section_face_inner_moved = None
            self.move_xform = None
            self.log.append("内截面：CreatePlanarBreps 失败。")
            return

        # 内截面沿参考平面法向 (ZAxis) 平移 MoveFen
        if self.move_dist is not None and self.section_face_inner is not None:
            move_vec = self.section_plane.ZAxis
            move_vec.Unitize()
            move_vec *= self.move_dist

            # 保存 Transform，Loft 与 TopFace 都会用到
            self.move_xform = rg.Transform.Translation(move_vec)

            self.section_face_inner_moved = self.section_face_inner.DuplicateBrep()
            self.section_face_inner_moved.Transform(self.move_xform)

            self.log.append(
                "内截面沿参考平面法向 (ZAxis) 平移 {:.3f} 分° 完成。".format(self.move_dist)
            )
        else:
            self.section_face_inner_moved = None
            self.move_xform = None
            self.log.append("内截面未进行平移（缺少 MoveFen 或内截面生成失败）。")

    # ---------- 步骤 8：构造放样面 + 顶面 ----------
    def _build_loft_and_top(self):
        # 必要曲线都要存在
        if not (self.outer_arc_left_crv and self.outer_arc_right_crv and
                self.outer_bot_crv and self.inner_arc_left_crv and
                self.inner_arc_right_crv and self.inner_bot_crv):
            self.log.append("放样面构造失败：必要的曲线尚未生成。")
            return

        # 1）构造外侧开曲线 A-E-F-B：
        bot_EF = self.outer_bot_crv.DuplicateCurve()
        bot_EF.Reverse()                    # E->F
        arc_FB = self.outer_arc_right_crv.DuplicateCurve()
        arc_FB.Reverse()                    # F->B

        curves_outer = [self.outer_arc_left_crv, bot_EF, arc_FB]
        joined_outer = rg.Curve.JoinCurves(curves_outer, self.tol)
        if not joined_outer or len(joined_outer) == 0:
            self.log.append("外截面 A-E-F-B 开曲线拼接失败。")
            return
        crv_AEFB = joined_outer[0]

        # 2）构造内侧开曲线 G-K-L-H（原位置）：
        bot_KL = self.inner_bot_crv.DuplicateCurve()
        bot_KL.Reverse()                    # K->L
        arc_LH = self.inner_arc_right_crv.DuplicateCurve()
        arc_LH.Reverse()                    # L->H

        curves_inner = [self.inner_arc_left_crv, bot_KL, arc_LH]
        joined_inner = rg.Curve.JoinCurves(curves_inner, self.tol)
        if not joined_inner or len(joined_inner) == 0:
            self.log.append("内截面 G-K-L-H 开曲线拼接失败。")
            return
        crv_GKLH = joined_inner[0]

        # 2.5）如果内截面有平移变换，则对 G-K-L-H 也做同样平移
        if self.move_xform is not None:
            crv_GKLH_moved = crv_GKLH.DuplicateCurve()
            crv_GKLH_moved.Transform(self.move_xform)
            self.log.append("G-K-L-H 开曲线已按 MoveFen 平移，用于 Loft。")
        else:
            crv_GKLH_moved = crv_GKLH
            self.log.append("未找到 Move Transform，Loft 使用未平移的 G-K-L-H。")

        # 3）Loft：A-E-F-B 与「偏移后的」G-K-L-H 放样得到“侧面”
        lofts = rg.Brep.CreateFromLoft(
            [crv_AEFB, crv_GKLH_moved],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )
        if lofts and len(lofts) > 0:
            self.loft_face = lofts[0]
            self.log.append("放样面 LoftFace (A-E-F-B vs moved G-K-L-H) 生成成功。")
        else:
            self.loft_face = None
            self.log.append("放样面 LoftFace 生成失败。")

        # 4）顶部 A-B-H'-G' 封面：
        #    G',H' 为 G,H 在 move_xform 作用下的点
        if self.move_xform is not None and self.move_dist > self.tol:
            Gm = rg.Point3d(self.G)
            Hm = rg.Point3d(self.H)
            Gm.Transform(self.move_xform)
            Hm.Transform(self.move_xform)

            pts_top = [self.A, self.B, Hm, Gm, self.A]
            poly_top = rg.Polyline(pts_top)
            top_crv = poly_top.ToNurbsCurve()
            breps_top = rg.Brep.CreatePlanarBreps(top_crv, self.tol)
            if breps_top and len(breps_top) > 0:
                self.top_face = breps_top[0]
                self.log.append("顶部 A-B-H'-G' 封面 TopFace 生成成功。")
            else:
                self.top_face = None
                self.log.append("顶部 A-B-H'-G' 封面 TopFace 生成失败。")
        else:
            self.top_face = None
            self.log.append("MoveFen 过小或未平移，不生成 TopFace。")

    # ---------- 步骤 9：构造最终刀具 ToolBrep ----------
    def _build_tool_brep(self):
        self.tool_brep = None
        self.top_plane_A = None
        self.top_plane_B = None

        # 先构造“半个”刀具壳体
        if not (self.section_face_outer and self.loft_face and self.top_face):
            self.log.append("ToolBrep：缺少 SectionFace/LoftFace/TopFace，无法生成半刀具壳体。")
            return

        half_breps = [self.section_face_outer, self.loft_face, self.top_face]
        joined_half = rg.Brep.JoinBreps(half_breps, self.tol)

        if not joined_half or len(joined_half) == 0:
            self.log.append("ToolBrep：半刀具壳体 JoinBreps 失败。")
            return

        half = joined_half[0]
        self.log.append("ToolBrep：半刀具壳体 JoinBreps 成功。")

        # ============ 以 InnerSectionMoved 所在的平面作为镜像面 ============
        if self.section_face_inner_moved is None:
            self.log.append("ToolBrep：InnerSectionMoved 为空，无法以其所在平面镜像，直接返回半刀具。")
            self.tool_brep = half
            return

        inner_brep = self.section_face_inner_moved
        if inner_brep.Faces.Count <= 0:
            self.log.append("ToolBrep：InnerSectionMoved 没有面，无法提取镜像平面，直接返回半刀具。")
            self.tool_brep = half
            return

        inner_face = inner_brep.Faces[0]
        # RhinoCommon Python 里 TryGetPlane() 通常返回 (bool, Plane)
        ok, mirror_plane = inner_face.TryGetPlane()
        if not ok:
            # 回退：用 section_plane + move_xform 的方式
            self.log.append("ToolBrep：从 InnerSectionMoved 提取平面失败，退回到平移 SectionPlane 的镜像方式。")

            if self.move_xform is None:
                self.log.append("ToolBrep：同时 move_xform 也为空，只能返回半刀具。")
                self.tool_brep = half
                return

            mirror_plane = rg.Plane(self.section_plane)
            mirror_plane.Origin.Transform(self.move_xform)
        else:
            self.log.append("ToolBrep：已以 InnerSectionMoved 的平面作为镜像垂直面。")

        # 构造镜像变换
        xf_mirror = rg.Transform.Mirror(mirror_plane)

        # -------- 使用 A/A'、B/B' 构造上表面两个参考平面 --------
        # 计算镜像后的 A'、B'
        A_mirror = rg.Point3d(self.A)
        B_mirror = rg.Point3d(self.B)
        A_mirror.Transform(xf_mirror)
        B_mirror.Transform(xf_mirror)

        # 计算 A-A' 和 B-B' 的中点
        mid_A = rg.Point3d(
            0.5 * (self.A.X + A_mirror.X),
            0.5 * (self.A.Y + A_mirror.Y),
            0.5 * (self.A.Z + A_mirror.Z)
        )
        mid_B = rg.Point3d(
            0.5 * (self.B.X + B_mirror.X),
            0.5 * (self.B.Y + B_mirror.Y),
            0.5 * (self.B.Z + B_mirror.Z)
        )

        # 上表面局部坐标系：
        # X 轴：沿 A->B（长度方向）
        # Y 轴：沿 A->A'（厚度方向）
        dir_AB = self.B - self.A           # 上表面长度方向
        dir_AA = A_mirror - self.A        # 跨内截面镜像面的厚度方向

        if dir_AB.IsTiny():
            dir_AB = self.section_plane.XAxis
        if dir_AA.IsTiny():
            dir_AA = self.section_plane.YAxis

        dir_AB.Unitize()
        dir_AA.Unitize()

        x_axis = dir_AB
        y_axis = dir_AA

        # 在 A-A'、B-B' 中点上各放一个平面
        self.top_plane_A = rg.Plane(mid_A, x_axis, y_axis)
        self.top_plane_B = rg.Plane(mid_B, x_axis, y_axis)
        self.log.append("ToolBrep：基于 A-A' 与 B-B' 中点生成上表面两个参考平面。")

        # -------- 实际几何镜像 --------
        half_mirror = half.DuplicateBrep()
        half_mirror.Transform(xf_mirror)

        # BooleanUnion 合成一个 Brep
        all_breps = [half, half_mirror]
        unioned = rg.Brep.CreateBooleanUnion(all_breps, self.tol)

        if unioned and len(unioned) > 0:
            self.tool_brep = unioned[0]
            self.log.append("ToolBrep：BooleanUnion 成功，得到完整刀具。")
        else:
            self.log.append("ToolBrep：BooleanUnion 失败，尝试 JoinBreps。")
            joined = rg.Brep.JoinBreps(all_breps, self.tol)
            if joined and len(joined) > 0:
                self.tool_brep = joined[0]
                self.log.append("ToolBrep：JoinBreps 成功，得到壳体形式的刀具。")
            else:
                self.tool_brep = None
                self.log.append("ToolBrep：JoinBreps 仍失败，未能生成最终刀具。")

if __name__ == '__main__':
    # =========================================================
    # GhPython 组件入口：调用类
    # =========================================================

    builder = FT_GongYanSectionABFEA(
        section_plane=SectionPlane,
        A_input=A,
        radius_fen=RadiusFen,
        length_fen=LengthFen,
        inner_radius_fen=InnerRadiusFen,
        move_fen=MoveFen,
        doc=sc.doc
    )

    (SectionFace,
     Points,
     InnerSection,
     InnerSectionMoved,
     InnerPoints,
     LoftFace,
     TopFace,
     ToolBrep,
     TopPlaneA,
     TopPlaneB,
     Log) = builder.build()

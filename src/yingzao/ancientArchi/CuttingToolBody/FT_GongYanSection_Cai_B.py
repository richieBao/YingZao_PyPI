# -*- coding: utf-8 -*-
"""
FT_GongYanSection_Cai_B
栱眼-材-B 型：外截面 + 垂直偏移副本 + 两截面相向拉伸成体 ToolBrep
并在两拉伸体的“上表面相对最外边线”之间放样一个连接面，输出其顶点、
边线中点和过面中心点的参考平面。

输入（GhPython 组件）:
    SectionPlane : rg.Plane | None
    A            : Point / Guid / Point3d
    RadiusFen    : float
    LengthFen    : float
    OffsetFen    : float
    ExtrudeFen   : float

输出:
    SectionFace      : rg.Brep | None
    OffsetFace       : rg.Brep | None
    Points           : list[rg.Point3d]
    OffsetPoints     : list[rg.Point3d]
    ToolBrep         : list[rg.Brep] | None
    BridgePoints     : list[rg.Point3d]  # 外侧连接面四个顶点
    BridgeMidPoints  : list[rg.Point3d]  # 四条边的中点
    BridgePlane      : rg.Plane | None   # 过连接面中心点的参考平面
    Log              : list[str]
"""

import Rhino.Geometry as rg
import scriptcontext as sc
import System
import math


class FT_GongYanSection_Cai_B(object):

    @staticmethod
    def coerce_point3d(obj, doc):
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

    def __init__(self,
                 section_plane,
                 A_input,
                 radius_fen,
                 length_fen,
                 offset_fen,
                 extrude_fen,
                 doc=None):

        self.doc = doc or sc.doc
        self.log = []

        self.raw_plane   = section_plane
        self.raw_A       = A_input
        self.raw_radius  = radius_fen
        self.raw_length  = length_fen
        self.raw_offset  = offset_fen
        self.raw_extrude = extrude_fen

        self.tol = self.doc.ModelAbsoluteTolerance if self.doc else 1e-3
        self.base_plane    = None
        self.section_plane = None

        self.A = self.B = self.C = self.D = self.E = self.F = None

        self.radius       = None
        self.length       = None
        self.offset_dist  = None
        self.extrude_dist = None

        self.outer_arc_left_crv  = None
        self.outer_arc_right_crv = None
        self.outer_top_crv       = None
        self.outer_bot_crv       = None
        self.boundary_outer      = None

        self.section_face_outer   = None
        self.section_face_offset  = None
        self.points_offset        = []
        self.offset_xform         = None

        self.body_main   = None
        self.body_offset = None
        self.tool_brep   = None

        self.bridge_face      = None
        self.bridge_points    = []
        self.bridge_midpoints = []
        self.bridge_plane     = None

    # -------------- 主入口 --------------
    def build(self):
        self.log.append("=== FT_GongYanSection_Cai_B.build() 开始 ===")

        self._prepare_plane()
        self._prepare_A()
        self._prepare_params()
        self._move_plane_to_A()
        self._build_outer_feature_points()
        self._build_outer_curves_and_face()
        self._build_offset_copy()
        self._build_tool_brep()
        self._build_bridge_face()

        points = [self.A, self.B, self.C, self.D, self.E, self.F]

        self.log.append("=== FT_GongYanSection_Cai_B.build() 结束 ===")

        return (self.section_face_outer,
                self.section_face_offset,
                points,
                self.points_offset,
                self.tool_brep,
                self.bridge_points,
                self.bridge_midpoints,
                self.bridge_plane,
                self.log)

    # -------------- 1. 参考平面 --------------
    def _prepare_plane(self):
        if self.raw_plane is None:
            origin = rg.Point3d(0, 0, 0)
            xdir   = rg.Vector3d(1, 0, 0)
            ydir   = rg.Vector3d(0, 0, 1)
            self.base_plane = rg.Plane(origin, xdir, ydir)
            self.log.append("SectionPlane 为空：使用默认 XZ 平面。")
        else:
            self.base_plane = self.raw_plane
            self.log.append("使用输入的 SectionPlane。")

    # -------------- 2. A 点 --------------
    def _prepare_A(self):
        self.A = self.coerce_point3d(self.raw_A, self.doc)
        if self.A is None:
            self.A = self.base_plane.Origin
            self.log.append("A 无效 → 使用 SectionPlane.Origin 作为 A。")
        else:
            self.log.append("读取 A = ({:.3f}, {:.3f}, {:.3f})".format(
                self.A.X, self.A.Y, self.A.Z))

    # -------------- 3. 参数 --------------
    def _prepare_params(self):
        if self.raw_radius is None or self.raw_radius <= 0:
            self.radius = 3.0
            self.log.append("RadiusFen 未给或 <=0 → 默认 3.0。")
        else:
            self.radius = float(self.raw_radius)
            self.log.append("RadiusFen = {:.3f}".format(self.radius))

        default_len = 20.0
        if self.raw_length is None:
            self.length = default_len
            self.log.append("LengthFen 未给 → 默认 20.0。")
        else:
            L_in = float(self.raw_length)
            min_len = 2.0 * self.radius + 0.01
            if L_in < min_len:
                self.length = min_len
                self.log.append(
                    "LengthFen = {:.3f} < 2*RadiusFen，夹紧为 {:.3f}。".format(
                        L_in, min_len))
            else:
                self.length = L_in
                self.log.append("LengthFen = {:.3f}".format(self.length))

        if self.raw_offset is None or self.raw_offset <= 0:
            self.offset_dist = 10.0
            self.log.append("OffsetFen 未给或 <=0 → 默认 10.0。")
        else:
            self.offset_dist = float(self.raw_offset)
            self.log.append("OffsetFen = {:.3f}".format(self.offset_dist))

        if self.raw_extrude is None or self.raw_extrude <= 0:
            self.extrude_dist = 1.0
            self.log.append("ExtrudeFen 未给或 <=0 → 默认 1.0。")
        else:
            self.extrude_dist = float(self.raw_extrude)
            self.log.append("ExtrudeFen = {:.3f}".format(self.extrude_dist))

    # -------------- 4. 平面移到 A --------------
    def _move_plane_to_A(self):
        self.section_plane = rg.Plane(
            self.A, self.base_plane.XAxis, self.base_plane.YAxis)
        self.log.append("已将参考平面原点移动到 A。")

    def _pt_uv(self, u, v):
        return self.section_plane.PointAt(u, v)

    # -------------- 5. 特征点 --------------
    def _build_outer_feature_points(self):
        r = self.radius
        L = self.length

        self.A = self._pt_uv(0.0, 0.0)
        self.B = self._pt_uv(L,   0.0)
        self.C = self._pt_uv(r,   0.0)
        self.D = self._pt_uv(L-r, 0.0)
        self.E = self._pt_uv(r,   -r)
        self.F = self._pt_uv(L-r, -r)

        self.log.append("特征点 A,B,C,D,E,F 已生成。")

    # -------------- 6. 外截面面 --------------
    def _build_outer_curves_and_face(self):
        r = self.radius

        plane_C = rg.Plane(self.C, self.section_plane.XAxis, self.section_plane.YAxis)
        plane_D = rg.Plane(self.D, self.section_plane.XAxis, self.section_plane.YAxis)

        # 左侧四分之一圆弧
        uL = r * math.cos(-0.75 * math.pi)
        vL = r * math.sin(-0.75 * math.pi)
        mid_left = plane_C.PointAt(uL, vL)
        arc_left = rg.Arc(self.A, mid_left, self.E)
        self.outer_arc_left_crv = rg.ArcCurve(arc_left)

        # 右侧四分之一圆弧
        uR = r * math.cos(-0.25 * math.pi)
        vR = r * math.sin(-0.25 * math.pi)
        mid_right = plane_D.PointAt(uR, vR)
        arc_right = rg.Arc(self.B, mid_right, self.F)
        self.outer_arc_right_crv = rg.ArcCurve(arc_right)

        top_line = rg.Line(self.A, self.B).ToNurbsCurve()
        bot_line = rg.Line(self.F, self.E).ToNurbsCurve()

        self.outer_top_crv = top_line
        self.outer_bot_crv = bot_line

        segs = [
            self.outer_top_crv,
            self.outer_arc_right_crv,
            self.outer_bot_crv,
            self.outer_arc_left_crv
        ]
        joined = rg.Curve.JoinCurves(segs, self.tol)
        if not joined:
            self.log.append("外截面：曲线拼接失败。")
            return

        boundary = joined[0]
        self.boundary_outer = boundary

        if not boundary.IsClosed:
            self.log.append("外截面：边界不是闭合曲线。")
            return

        breps = rg.Brep.CreatePlanarBreps(boundary, self.tol)
        if breps:
            self.section_face_outer = breps[0]
            self.log.append("外截面平面 Brep 生成成功。")
        else:
            self.log.append("外截面：CreatePlanarBreps 失败。")

    # -------------- 7. 偏移截面 --------------
    def _build_offset_copy(self):
        self.section_face_offset = None
        self.points_offset = []

        if self.section_face_outer is None:
            self.log.append("OffsetFace：原截面为空，无法偏移。")
            return

        move_vec = self.section_plane.ZAxis
        if move_vec.IsZero:
            self.log.append("OffsetFace：ZAxis 为零。")
            return

        move_vec.Unitize()
        move_vec *= self.offset_dist
        self.offset_xform = rg.Transform.Translation(move_vec)

        brep_cp = self.section_face_outer.DuplicateBrep()
        brep_cp.Transform(self.offset_xform)
        self.section_face_offset = brep_cp

        for p in [self.A, self.B, self.C, self.D, self.E, self.F]:
            q = rg.Point3d(p)
            q.Transform(self.offset_xform)
            self.points_offset.append(q)

        self.log.append("OffsetFace：偏移 {:.3f} 完成。".format(self.offset_dist))

    # -------------- 8. 拉伸两个截面（封闭体版本） --------------
    def _build_tool_brep(self):
        """
        兼容 Rhino 7 的稳定封闭挤出体构造方法：
        1) 用 Surface.CreateExtrusion 得到侧面
        2) 通过 CreatePlanarBreps 添加顶面和底面
        3) JoinBreps → 得到完整闭合 Brep（Solid）
        """

        self.tool_brep   = None
        self.body_main   = None
        self.body_offset = None

        if self.boundary_outer is None or self.section_face_offset is None:
            self.log.append("ToolBrep：缺少截面。")
            return

        if self.extrude_dist is None or self.extrude_dist <= 0:
            self.log.append("ToolBrep：ExtrudeFen 无效。")
            return

        # 挤出方向向量
        vec_up = self.section_plane.ZAxis
        if vec_up.IsZero:
            self.log.append("ToolBrep：ZAxis 为零。")
            return

        vec_up.Unitize()
        vec_up *= self.extrude_dist
        vec_down = -vec_up

        #-----------------------------------------
        # 1. 主截面：boundary_outer 挤出
        #-----------------------------------------

        # 1.1 侧面
        surf_main = rg.Surface.CreateExtrusion(self.boundary_outer, vec_up)
        if not surf_main:
            self.log.append("主截面 CreateExtrusion 失败。")
            return
        brep_side_main = surf_main.ToBrep()

        # 1.2 底面（原平面）
        bottom_main = rg.Brep.CreatePlanarBreps(self.boundary_outer, self.tol)
        if not bottom_main:
            self.log.append("主截面底面 CreatePlanarBreps 失败。")
            return
        bottom_main = bottom_main[0]

        # 1.3 顶面（挤出后的 boundary）
        top_crv_main = self.boundary_outer.DuplicateCurve()
        top_crv_main.Transform(rg.Transform.Translation(vec_up))
        top_main = rg.Brep.CreatePlanarBreps(top_crv_main, self.tol)
        if not top_main:
            self.log.append("主截面顶面 CreatePlanarBreps 失败。")
            return
        top_main = top_main[0]

        # 1.4 Join 成封闭体
        joined_main = rg.Brep.JoinBreps(
            [brep_side_main, bottom_main, top_main], self.tol)
        if not joined_main:
            self.log.append("主截面 JoinBreps 失败。")
            return
        self.body_main = joined_main[0]

        #-----------------------------------------
        # 2. 偏移截面：boundary_outer 复制后挤出
        #-----------------------------------------

        # 偏移后 boundary
        boundary_off = self.boundary_outer.DuplicateCurve()
        boundary_off.Transform(self.offset_xform)

        # 2.1 侧面：反向挤出
        surf_offset = rg.Surface.CreateExtrusion(boundary_off, vec_down)
        if not surf_offset:
            self.log.append("偏移 CreateExtrusion 失败。")
            return
        brep_side_offset = surf_offset.ToBrep()

        # 2.2 顶面（挤出后得到的是“靠内侧”）
        top_off = rg.Brep.CreatePlanarBreps(boundary_off, self.tol)
        if not top_off:
            self.log.append("偏移顶面 CreatePlanarBreps 失败。")
            return
        top_off = top_off[0]

        # 2.3 底面（挤出后 boundary_off + vec_down）
        bottom_crv_off = boundary_off.DuplicateCurve()
        bottom_crv_off.Transform(rg.Transform.Translation(vec_down))
        bottom_off = rg.Brep.CreatePlanarBreps(bottom_crv_off, self.tol)
        if not bottom_off:
            self.log.append("偏移底面 CreatePlanarBreps 失败。")
            return
        bottom_off = bottom_off[0]

        # 2.4 Join 成封闭体
        joined_offset = rg.Brep.JoinBreps(
            [brep_side_offset, top_off, bottom_off], self.tol)
        if not joined_offset:
            self.log.append("偏移 JoinBreps 失败。")
            return
        self.body_offset = joined_offset[0]

        #-----------------------------------------
        # 输出两个完全封闭体
        #-----------------------------------------
        self.tool_brep = [self.body_main, self.body_offset]

        self.log.append("ToolBrep：两个封闭实体已成功生成（兼容 Rhino7 的稳定方案）。")

        # Solid 检查
        if not self.body_main.IsSolid:
            self.log.append("警告：主 Solid 未闭合！")
        if not self.body_offset.IsSolid:
            self.log.append("警告：偏移 Solid 未闭合！")


    # -------------- 9. 外侧上表面连接面 --------------
    def _build_bridge_face(self):
        self.bridge_face      = None
        self.bridge_points    = []
        self.bridge_midpoints = []
        self.bridge_plane     = None

        if self.body_main is None or self.body_offset is None:
            self.log.append("BridgeFace：ToolBrep 不完整，跳过。")
            return

        if not self.points_offset or len(self.points_offset) < 2:
            self.log.append("BridgeFace：OffsetPoints 不足。")
            return

        # 外侧最外边线：
        # 主截面：A, B
        # 偏移截面：A_offset, B_offset
        A_main = self.A
        B_main = self.B
        A_off  = self.points_offset[0]
        B_off  = self.points_offset[1]

        # 顶点顺序：主截面外边 A-B → 偏移截面外边 B'-A'
        self.bridge_points = [A_main, B_main, B_off, A_off]

        # 用多段线建平面
        poly = rg.Polyline(self.bridge_points + [A_main])
        crv  = poly.ToNurbsCurve()
        breps = rg.Brep.CreatePlanarBreps(crv, self.tol)
        if breps:
            self.bridge_face = breps[0]

        # 四条边的中点
        edges = [
            (A_main, B_main),
            (B_main, B_off),
            (B_off,  A_off),
            (A_off,  A_main)
        ]
        for p, q in edges:
            mid = rg.Point3d((p.X + q.X)/2.0,
                             (p.Y + q.Y)/2.0,
                             (p.Z + q.Z)/2.0)
            self.bridge_midpoints.append(mid)

        # 面的中心点
        if self.bridge_face:
            amp = rg.AreaMassProperties.Compute(self.bridge_face)
            origin = amp.Centroid if amp else sum(self.bridge_points, rg.Point3d(0,0,0))/4.0
        else:
            origin = sum(self.bridge_points, rg.Point3d(0,0,0))/4.0

        # X 轴：沿长度方向 A_main → B_main
        x_axis = B_main - A_main
        if x_axis.IsTiny():
            x_axis = self.section_plane.XAxis
        x_axis.Unitize()

        # Y 轴：沿厚度方向 A_main → A_off
        y_axis = A_off - A_main
        if y_axis.IsTiny():
            y_axis = self.section_plane.ZAxis
        y_axis.Unitize()

        self.bridge_plane = rg.Plane(origin, x_axis, y_axis)
        self.log.append("BridgeFace：已生成外侧连接面的顶点、中点和参考平面。")

if __name__=='__main__':
    # ----------------- GH Python 入口 -----------------

    builder = FT_GongYanSection_Cai_B(
        section_plane=SectionPlane,
        A_input=A,
        radius_fen=RadiusFen,
        length_fen=LengthFen,
        offset_fen=OffsetFen,
        extrude_fen=ExtrudeFen,
        doc=sc.doc
    )

    (SectionFace,
     OffsetFace,
     Points,
     OffsetPoints,
     ToolBrep,
     BridgePoints,
     BridgeMidPoints,
     BridgePlane,
     Log) = builder.build()

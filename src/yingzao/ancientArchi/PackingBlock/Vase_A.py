"""
宝瓶放样建模组件
根据圆形截面通过轨道放样创建宝瓶模型

输入端参数配置:
- base_point: 名称='base_point', Access=item, TypeHint=Point3d, 默认=原点
- ref_plane: 名称='ref_plane', Access=item, TypeHint=Plane, 默认=XY平面
- cut_plane_height: 名称='cut_plane_height', Access=item, TypeHint=float, 默认=40.0 (沿ref_plane.ZAxis的高度)
- cut_plane_tilt_deg: 名称='cut_plane_tilt_deg', Access=item, TypeHint=float, 默认=16.0 (参考平面绕ref_plane.YAxis倾斜角度，单位度)
- cut_enabled: 名称='cut_enabled', Access=item, TypeHint=bool, 默认=True
- section_diameters: 名称='section_diameters', Access=list, TypeHint=float, 默认=[14,14,12,13.5,13.5,12,11,11.5,11.5,11,8]
- section_heights: 名称='section_heights', Access=list, TypeHint=float, 默认=[0,2.2,11,12,13,14,27.5,28.5,29.5,30.5,49]
- bulge_distances: 名称='bulge_distances', Access=list, TypeHint=float, 默认=[2,2,2,2,2,2,2,2,2,2] (10个值，对应C1-C2到C10-C11)
- close_caps: 名称='close_caps', Access=item, TypeHint=bool, 默认=True

输出端参数配置:
- base_ref_plane: 名称='base_ref_plane', Access=item, TypeHint=Plane  (过 base_point 的参考平面；等于把 ref_plane 的原点平移到 base_point 后的平面)
- circles: 名称='circles', Access=list, TypeHint=Circle
- rails: 名称='rails', Access=list, TypeHint=Curve
- cut_plane: 名称='cut_plane', Access=item, TypeHint=Plane  (⚠️ 默认不输出以避免显示；组件输出变量将置为 None)
- vase: 名称='vase', Access=item, TypeHint=Brep (裁切并封闭后的宝瓶)
- info: 名称='info', Access=item, TypeHint=string
"""

import Rhino.Geometry as rg
import math

# ghpythonlib.components: 用于 SplitBrep / CapHoles（在 GH 内可用）
try:
    import ghpythonlib.components as ghc
except:
    ghc = None


class VaseGenerator:
    """宝瓶生成器类 - 使用轨道放样方法"""

    def __init__(self, base_point=None, ref_plane=None,
                 section_diameters=None, section_heights=None,
                 bulge_distances=None,
                 cut_plane_height=40.0, cut_plane_tilt_deg=16.0, cut_enabled=True):
        """
        初始化宝瓶生成器

        参数:
            base_point: 基点位置，默认为原点
            ref_plane: 参考平面，默认为XY平面
            section_diameters: 各截面圆直径列表
            section_heights: 各截面圆高度列表
            bulge_distances: 各段凸起距离列表
        """
        self.base_point = base_point if base_point else rg.Point3d(0, 0, 0)

        if ref_plane is None:
            self.ref_plane = rg.Plane.WorldXY
        else:
            self.ref_plane = ref_plane

        # 将ref_plane的原点移动到base_point
        self.ref_plane = rg.Plane(self.base_point, self.ref_plane.XAxis, self.ref_plane.YAxis)

        # 默认直径配置
        if section_diameters is None or len(section_diameters) == 0:
            self.section_diameters = [
                14.0,  # C1
                14.0,  # C2
                12.0,  # C3 底部收缩
                13.5,  # C4 第一个凸起开始
                13.5,  # C5 第一个凸起结束
                12.0,  # C6 第一个凸起后收缩
                11.0,  # C7 第二个凸起开始
                11.5,  # C8 第二个凸起中间
                11.5,  # C9 第二个凸起中间
                11.0,  # C10 第二个凸起结束
                8.0  # C11 顶部收缩
            ]
        else:
            self.section_diameters = list(section_diameters)

        # 默认高度配置
        if section_heights is None or len(section_heights) == 0:
            self.section_heights = [
                0.0,  # C1 - 底部
                2.2,  # C2 - 底座上沿
                11.0,  # C3 - 第一个球体底部
                12.0,  # C4 - 第一个凸起开始
                13.0,  # C5 - 第一个凸起结束
                14.0,  # C6 - 第一个球体顶部 (C3+3)
                27.5,  # C7 - 第二个球体底部
                28.5,  # C8 - 第二个凸起开始
                29.5,  # C9 - 第二个凸起结束
                30.5,  # C10 - 第二个球体顶部 (C7+3)
                49.0  # C11 - 顶部收口
            ]
        else:
            self.section_heights = list(section_heights)

        # 默认凸起距离配置（10个值，对应C1-C2到C10-C11）
        if bulge_distances is None or len(bulge_distances) == 0:
            self.bulge_distances = [0, 0.4, 0.1, 0.3, 0.1, 0.6, 0.1, 0.3, 0.1, 0.3, 0.3]
        else:
            self.bulge_distances = list(bulge_distances)

        self.circles = []
        self.rails = []
        self.vase = None
        self.cut_plane = None
        self.cut_plane_height = float(cut_plane_height) if cut_plane_height is not None else 40.0
        self.cut_plane_tilt_deg = float(cut_plane_tilt_deg) if cut_plane_tilt_deg is not None else 16.0
        self.cut_enabled = bool(cut_enabled) if cut_enabled is not None else True
        self.close_caps = True  # 在 generate(close_ends=...) 时写入

        # ==================== Cut debugging outputs (for GH visual check) ====================
        # Brep | Plane (BrepXPlane)
        self.BXPlane_Curves = []  # [Curve]
        self.BXPlane_Points = []  # [Point3d]
        # Boundary Surface (BoundarySurfaces)
        self.BoundarySurfaces_Surfaces = []  # [Surface]
        self.BoundarySurfaces_CutterBrep = None  # Brep cutter (joined if possible)
        # Split Brep (SplitBrep)
        self.SplitBrep_Fragments = []  # [Brep]
        self.SplitBrep_Areas = []  # [float]
        self.SplitBrep_SortedIndex = []  # [int]  sort indices by area asc
        self.SplitBrep_KeptBrep = None  # Brep (max area)
        # Cap Holes Ex (CapHolesEx)
        self.CappedBrep = None  # Brep
        self.Cap_Count = 0  # int
        self.Cap_IsSolid = False  # bool

    # ------------------------------------------------------------------
    # Cut plane + boolean cut
    # ------------------------------------------------------------------
    def build_cut_plane(self, height=None, tilt_deg=None):
        """构造用于裁切宝瓶的参考平面。

        约定：
        - 先以 ref_plane 平行上移 height（沿 ref_plane.ZAxis）得到水平切平面；
        - 再绕 ref_plane.YAxis（过平面原点）旋转 tilt_deg 形成倾斜切平面。

        返回:
            rg.Plane
        """
        if height is None:
            height = self.cut_plane_height
        if tilt_deg is None:
            tilt_deg = self.cut_plane_tilt_deg

        z = rg.Vector3d(self.ref_plane.ZAxis)
        z.Unitize()
        origin = self.ref_plane.Origin + z * float(height)

        pl = rg.Plane(origin, self.ref_plane.XAxis, self.ref_plane.YAxis)

        # 倾斜：绕 ref_plane.YAxis（通过 origin）旋转
        ang = math.radians(float(tilt_deg))
        axis = rg.Vector3d(self.ref_plane.YAxis)
        axis.Unitize()
        xform = rg.Transform.Rotation(ang, axis, origin)
        pl.Transform(xform)

        self.cut_plane = pl
        return pl

    def cut_brep_with_plane_fallback(self, brep, plane, keep_lower=True, tol=0.001):
        """用平面裁切 Brep，并输出封闭后的保留部分（优先使用 ghc.SplitBrep + ghc.CapHoles）。

        约定（按你的最新要求）：
        - **保留裁切面“底部”部分**（沿 ref_plane.ZAxis 投影更低的那一侧）。
        - 裁切完成后再用 CapHoles 封闭开口，避免出现“巨大的封口面”。

        参数:
            brep: rg.Brep
            plane: rg.Plane
            keep_lower: True 表示保留“更低”的那一侧（默认 True）
            tol: 容差

        返回:
            (closed_brep, pieces)
              - closed_brep: 封闭结果（可能为 None）
              - pieces: 分割结果列表（可能为空）
        """
        if brep is None or (not brep.IsValid) or plane is None:
            return None, []

        # 用一个足够大的平面面片作为切割体（用于 SplitBrep / BooleanSplit）
        bbox = brep.GetBoundingBox(True)
        diag = bbox.Diagonal.Length
        if diag <= 0:
            diag = 1000.0
        size = diag * 5.0

        ps = rg.PlaneSurface(plane, rg.Interval(-size, size), rg.Interval(-size, size))
        cutter = ps.ToBrep()

        pieces = []

        # 1) 优先：GH SplitBrep（用户指定）
        if ghc is not None:
            try:
                sp = ghc.SplitBrep(brep, cutter)
                # ghc 返回可能是 list / tuple / DataTree；这里做保守兼容
                if sp:
                    if isinstance(sp, (list, tuple)):
                        pieces = [p for p in sp if p is not None]
                    else:
                        pieces = [sp]
            except:
                pieces = []

        # 2) 兜底：RhinoCommon BooleanSplit
        if not pieces:
            try:
                bs = rg.Brep.CreateBooleanSplit(brep, cutter, tol)
                if bs:
                    pieces = list(bs)
            except:
                pieces = []

        # 3) 兜底：RhinoCommon Split
        if not pieces:
            try:
                sp2 = brep.Split(cutter, tol)
                if sp2:
                    pieces = list(sp2)
            except:
                pieces = []

        if not pieces:
            return None, []

        # 选取保留部分：按 ref_plane.ZAxis 投影分数选择更低的一侧
        zax = rg.Vector3d(self.ref_plane.ZAxis)
        zax.Unitize()

        def zscore(b):
            bb = b.GetBoundingBox(True)
            return rg.Vector3d.Multiply(zax, bb.Center - self.ref_plane.Origin)

        valid_pieces = [p for p in pieces if p is not None and getattr(p, "IsValid", False)]
        if not valid_pieces:
            return None, pieces

        key_piece = min(valid_pieces, key=zscore) if keep_lower else max(valid_pieces, key=zscore)
        out = key_piece

        # 封口：优先 CapHoles（更符合 GH 组件行为）
        if ghc is not None:
            try:
                capped = ghc.CapHoles(out)
                # ghc.CapHoles 通常返回 [Brep] 或 Brep；做兼容提取
                if isinstance(capped, (list, tuple)):
                    capped = capped[0] if capped else None
                if capped is not None and getattr(capped, "IsValid", False):
                    out = capped
            except:
                pass
        else:
            # 兜底：RhinoCommon
            try:
                out = out.CapPlanarHoles(tol)
            except:
                pass

        return out, pieces

    def cut_brep_with_plane(self, brep, plane, tol=0.001):
        """按“附图流程”用平面裁切 Brep，并输出封闭后的保留部分（面积最大者）。

        流程严格复刻你附图的 GH 组件串联：
        1) Brep | Plane（ghc.BrepXPlane）：Vase 与 _cut_plane_internal 求交线 curves
        2) Boundary Surface（ghc.BoundarySurfaces）：由交线生成封面 surfaces
        3) Split Brep（ghc.SplitBrep）：用封面(转 Brep)作为 cutter 裁切 brep，得到 fragments
        4) Area（ghc.Area）：计算每段面积 area
        5) Sort List + List Item(-1)：按面积升序排序后取最后一个（面积最大 fragment）
        6) Cap Holes Ex（ghc.CapHolesEx）：对该段封孔，得到最终 brep

        返回:
            (closed_brep, fragments, debug)
              - closed_brep: 面积最大且封孔后的结果（失败则可能为 None）
              - fragments: Split 产生的片段列表（可能为空）
              - debug: 过程调试信息（dict）
        """
        debug = {
            "curves": None,
            "surfaces": None,
            "cutter": None,
            "fragments": None,
            "areas": None,
            "sorted_areas": None,
            "sorted_frags": None,
            "picked_index": None,
            "cap_added": None,
            "is_solid": None,
            "fallback_used": False,
            "error": None,
        }

        # Reset intermediate outputs each run (so GH can see latest states)
        self.BXPlane_Curves = []
        self.BXPlane_Points = []
        self.BoundarySurfaces_Surfaces = []
        self.BoundarySurfaces_CutterBrep = None
        self.SplitBrep_Fragments = []
        self.SplitBrep_Areas = []
        self.SplitBrep_SortedIndex = []
        self.SplitBrep_KeptBrep = None
        self.CappedBrep = None
        self.Cap_Count = 0
        self.Cap_IsSolid = False

        if brep is None or (not brep.IsValid) or plane is None:
            debug["error"] = "Invalid brep or plane."
            return None, [], debug

        # 若 GH 组件库不可用，则退化使用原先的 cutter split 方案
        if ghc is None:
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        # ------------------------------------------------------------
        # 1) Brep|Plane 求交线
        # ------------------------------------------------------------
        try:
            curves, _pts = ghc.BrepXPlane(brep, plane)
        except Exception as e:
            debug["error"] = "BrepXPlane failed: {}".format(e)
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        # 兼容单条/列表/嵌套
        def _flatten(obj):
            if obj is None:
                return []
            if isinstance(obj, (list, tuple)):
                out = []
                for it in obj:
                    out.extend(_flatten(it))
                return out
            return [obj]

        curves = [c for c in _flatten(curves) if c is not None]
        debug["curves"] = curves
        # GH-debug outputs: Brep | Plane results
        self.BXPlane_Curves = curves
        try:
            self.BXPlane_Points = [p for p in _flatten(_pts) if p is not None]
        except Exception:
            self.BXPlane_Points = []

        if len(curves) == 0:
            debug["error"] = "No intersection curves."
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        # 交线可能是多段：尽量 Join 成闭合环（更贴合 BoundarySurfaces 输入期望）
        joined_loops = []
        try:
            jc = rg.Curve.JoinCurves(curves, tol)
            if jc:
                joined_loops = list(jc)
        except Exception:
            joined_loops = []

        if joined_loops:
            loops = joined_loops
        else:
            loops = curves

        # 仅保留闭合且近似共面的环（BoundarySurfaces 的常见要求）
        closed_loops = []
        for crv in loops:
            try:
                if hasattr(crv, "IsClosed") and crv.IsClosed:
                    closed_loops.append(crv)
            except Exception:
                pass

        # 若没有闭合曲线，就直接用原 curves（有些情况下 GH 仍能生成面）
        edges_for_boundary = closed_loops if closed_loops else loops

        # ------------------------------------------------------------
        # 2) Boundary Surfaces 封面
        # ------------------------------------------------------------
        try:
            surfaces = ghc.BoundarySurfaces(edges_for_boundary)
        except Exception as e:
            debug["error"] = "BoundarySurfaces failed: {}".format(e)
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        surfaces = [s for s in _flatten(surfaces) if s is not None]
        debug["surfaces"] = surfaces
        # GH-debug outputs: Boundary Surface results
        self.BoundarySurfaces_Surfaces = surfaces

        if len(surfaces) == 0:
            debug["error"] = "No boundary surfaces."
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        # Surface -> Brep cutter（尽量 Join 成单一 cutter）
        cutter_breps = []
        for s in surfaces:
            try:
                if isinstance(s, rg.Brep):
                    cutter_breps.append(s)
                elif hasattr(s, "ToBrep"):
                    b = s.ToBrep()
                    if b is not None:
                        cutter_breps.append(b)
            except Exception:
                pass

        if len(cutter_breps) == 0:
            debug["error"] = "Surface->Brep conversion failed."
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        cutter = None
        try:
            joined = rg.Brep.JoinBreps(cutter_breps, tol)
            if joined and len(joined) > 0:
                cutter = joined[0]
        except Exception:
            cutter = None

        if cutter is None:
            cutter = cutter_breps[0]

        debug["cutter"] = cutter
        # GH-debug outputs: cutter brep (for SplitBrep)
        self.BoundarySurfaces_CutterBrep = cutter

        # ------------------------------------------------------------
        # 3) Split Brep
        # ------------------------------------------------------------
        fragments = []
        try:
            sp = ghc.SplitBrep(brep, cutter)
            fragments = [p for p in _flatten(sp) if p is not None]
        except Exception as e:
            debug["error"] = "SplitBrep failed: {}".format(e)
            fragments = []

        debug["fragments"] = fragments
        # GH-debug outputs: Split Brep fragments
        self.SplitBrep_Fragments = fragments

        if len(fragments) == 0:
            debug["fallback_used"] = True
            out, pieces = self.cut_brep_with_plane_fallback(brep, plane, keep_lower=True, tol=tol)
            debug["fragments"] = pieces
            return out, pieces, debug

        # ------------------------------------------------------------
        # 4) Area
        # ------------------------------------------------------------
        areas = []
        for f in fragments[0]:
            a_val = 0.0
            try:
                a, _c = ghc.Area(f)
                if isinstance(a, (list, tuple)):
                    a_val = float(a[0]) if len(a) else 0.0
                else:
                    a_val = float(a)
            except Exception:
                # 兜底：RhinoCommon
                try:
                    mp = rg.AreaMassProperties.Compute(f)
                    a_val = float(mp.Area) if mp else 0.0
                except Exception:
                    a_val = 0.0
            areas.append(a_val)

        debug["areas"] = areas
        # GH-debug outputs: Areas of fragments
        self.SplitBrep_Areas = areas

        # ------------------------------------------------------------
        # 5) Sort List + List Item(-1)：按面积升序排序，取最后一个（最大面积）
        # ------------------------------------------------------------
        pairs = list(zip(areas, fragments[0]))
        pairs.sort(key=lambda t: (t[0] if t[0] is not None else -1.0))
        sorted_areas = [p[0] for p in pairs]
        sorted_frags = [p[1] for p in pairs]
        debug["sorted_areas"] = sorted_areas
        debug["sorted_frags"] = sorted_frags
        # GH-debug outputs: Sort order (by area asc) - indices refer to original fragments list
        try:
            self.SplitBrep_SortedIndex = [fragments.index(f) for f in sorted_frags]
        except Exception:
            self.SplitBrep_SortedIndex = []

        if len(sorted_frags) == 0:
            return None, fragments, debug

        keep = sorted_frags[-1]
        # GH-debug outputs: kept brep (max area)
        self.SplitBrep_KeptBrep = keep

        debug["picked_index"] = len(sorted_frags) - 1

        # ------------------------------------------------------------
        # 6) Cap Holes Ex 封孔
        # ------------------------------------------------------------
        try:
            capped, caps, solid = ghc.CapHolesEx(keep)
            debug["cap_added"] = caps
            debug["is_solid"] = solid
            # GH-debug outputs: CapHolesEx results
            self.CappedBrep = capped
            try:
                self.Cap_Count = int(caps) if caps is not None else 0
            except Exception:
                self.Cap_Count = 0
            self.Cap_IsSolid = bool(solid) if solid is not None else False
            if capped is not None and getattr(capped, "IsValid", False):
                return capped, fragments, debug
            return keep, fragments, debug
        except Exception as e:
            debug["error"] = (debug["error"] or "") + " | CapHolesEx failed: {}".format(e)
            return keep, fragments, debug

    def create_section_circles(self, diameters=None, heights=None):
        """
        创建截面圆

        参数:
            diameters: 各圆直径列表，如果为None则使用初始化时的值
            heights: 各圆高度列表，如果为None则使用初始化时的值

        返回:
            circles: 圆列表
        """
        if diameters is None:
            diameters = self.section_diameters
        if heights is None:
            heights = self.section_heights

        if len(diameters) != len(heights):
            raise ValueError("直径和高度列表长度必须相同")

        self.circles = []

        for d, h in zip(diameters, heights):
            # 确保d和h是数值类型
            diameter = float(d)
            height = float(h)

            # 计算圆心位置（沿ref_plane的Z轴方向移动）
            z_vector = self.ref_plane.ZAxis
            z_vector.Unitize()
            offset = z_vector * height
            center = self.ref_plane.Origin + offset

            # 创建圆的平面（与ref_plane平行）
            circle_plane = rg.Plane(center, self.ref_plane.XAxis, self.ref_plane.YAxis)
            # 创建圆
            circle = rg.Circle(circle_plane, diameter / 2.0)
            self.circles.append(circle)

        return self.circles

    def create_rail_between_circles(self, circle1, circle2, bulge_dist):
        """
        在两个圆之间创建放样轨道

        参数:
            circle1: 下方圆
            circle2: 上方圆
            bulge_dist: 凸起距离

        返回:
            (rail1, rail2): 两条轨道弧线/直线
        """
        t1 = 0.0
        t2 = math.pi

        point_A = circle1.PointAt(t1)
        point_B = circle1.PointAt(t2)
        point_E = circle2.PointAt(t1)
        point_F = circle2.PointAt(t2)

        # 计算中点M1和M2
        M1 = (point_A + point_E) * 0.5
        M2 = (point_B + point_F) * 0.5

        # 计算径向外方向（在ref_plane的XY平面内）
        radial_dir_1 = M1 - circle1.Center
        radial_dir_1.Z = 0
        if not radial_dir_1.Unitize():
            radial_dir_1 = rg.Vector3d(self.ref_plane.XAxis)
            radial_dir_1.Unitize()

        radial_dir_2 = M2 - circle1.Center
        radial_dir_2.Z = 0
        if not radial_dir_2.Unitize():
            radial_dir_2 = rg.Vector3d(-self.ref_plane.XAxis)
            radial_dir_2.Unitize()

        # M1' / M2'
        M1_prime = M1 + radial_dir_1 * float(bulge_dist)
        M2_prime = M2 + radial_dir_2 * float(bulge_dist)

        # 创建弧线 A-M1'-E 和 B-M2'-F
        # 当 bulge_dist = 0（或非常接近 0）时：
        #   M1' == M1 且 A-M1-E 三点共线（同理 B-M2-F），Arc(三点) 会生成无效弧，
        #   进而导致后续 Brep.CreateFromSweep(...) 触发 NullReferenceException。
        # 此时几何应退化为“过 M1'/M2' 的直线”：A-M1'-E 与 B-M2'-F。
        tol = 1e-9
        if abs(float(bulge_dist)) <= tol:
            rail1 = rg.LineCurve(point_A, point_E)
            rail2 = rg.LineCurve(point_B, point_F)
            return rail1, rail2

        arc1 = rg.Arc(point_A, M1_prime, point_E)
        arc2 = rg.Arc(point_B, M2_prime, point_F)

        # 若由于数值原因仍然无效，则同样退化为直线
        if (not arc1.IsValid) or (not arc2.IsValid):
            rail1 = rg.LineCurve(point_A, point_E)
            rail2 = rg.LineCurve(point_B, point_F)
        else:
            rail1 = arc1.ToNurbsCurve()
            rail2 = arc2.ToNurbsCurve()

        return rail1, rail2

    def sweep_between_circles(self, circle1, circle2, rail1, rail2):
        """
        使用两条轨道在两个圆之间进行扫掠放样
        """
        # 防止 rail / circle 为空导致 CreateFromSweep 直接抛 NullReferenceException
        if rail1 is None or rail2 is None:
            return None

        c1 = circle1.ToNurbsCurve() if circle1 else None
        c2 = circle2.ToNurbsCurve() if circle2 else None
        if c1 is None or c2 is None:
            return None

        curves = [c1, c2]

        sweep_result = rg.Brep.CreateFromSweep(
            rail1,
            rail2,
            curves,
            False,
            0.001
        )

        if sweep_result and len(sweep_result) > 0:
            return sweep_result[0]

        return None

    def generate_vase(self):
        """
        生成完整宝瓶
        """
        if not self.circles:
            raise ValueError("请先调用create_section_circles创建截面圆")

        if len(self.circles) != 11:
            raise ValueError("需要11个截面圆（C1到C11）")

        breps = []
        self.rails = []

        for i in range(len(self.circles) - 1):
            bulge_dist = self.bulge_distances[i] if i < len(self.bulge_distances) else 2.0

            rail1, rail2 = self.create_rail_between_circles(
                self.circles[i],
                self.circles[i + 1],
                bulge_dist
            )

            self.rails.extend([rail1, rail2])

            segment_brep = self.sweep_between_circles(
                self.circles[i],
                self.circles[i + 1],
                rail1,
                rail2
            )

            if segment_brep:
                breps.append(segment_brep)

        # 合并所有Brep
        if breps:
            self.vase = rg.Brep.JoinBreps(breps, 0.001)
            if self.vase and len(self.vase) > 0:
                self.vase = self.vase[0]
                # ⚠️ 先不封口：避免在裁切前生成错误的巨大封口面。
                # 封口将在：1)裁切后用 CapHoles 处理；或 2)未启用裁切但 close_caps=True 时处理。

        # ==================== 顶部倾斜平面裁切（封闭输出） ====================
        if self.vase and self.vase.IsValid and self.cut_enabled:
            try:
                pl = self.build_cut_plane(self.cut_plane_height, self.cut_plane_tilt_deg)

                # ✅ 按要求：保留裁切面“底部”部分
                cut_vase, _pieces, _cut_debug = self.cut_brep_with_plane(self.vase, pl, tol=0.001)
                self.cut_debug = _cut_debug
                if cut_vase and cut_vase.IsValid:
                    self.vase = cut_vase
            except:
                # 裁切失败则退回原 vase
                pass

        return self.vase

    def generate(self, close_ends=True):
        """一键生成宝瓶"""
        self.close_caps = bool(close_ends)

        self.create_section_circles()
        self.generate_vase()

        # 若未启用裁切，但仍要求封口，则在此封闭
        if self.vase and self.vase.IsValid and (not self.cut_enabled) and self.close_caps:
            if ghc is not None:
                try:
                    capped = ghc.CapHoles(self.vase)
                    if isinstance(capped, (list, tuple)):
                        capped = capped[0] if capped else None
                    if capped is not None and getattr(capped, "IsValid", False):
                        self.vase = capped
                except:
                    pass
            else:
                try:
                    self.vase = self.vase.CapPlanarHoles(0.001)
                except:
                    pass

        # generate_vase() 内部已处理裁切与封闭（若 cut_enabled=True）
        return self.circles, self.rails, self.cut_plane, self.vase

    def get_info(self):
        """
        获取宝瓶信息
        """
        info = "宝瓶生成信息:\n"
        info += f"基点: {self.base_point}\n"
        info += f"截面圆数量: {len(self.circles)}\n"
        info += f"轨道数量: {len(self.rails)}\n"
        if self.vase:
            info += f"宝瓶体积: {self.vase.GetVolume():.2f}\n"
            bbox = self.vase.GetBoundingBox(True)
            info += f"高度: {bbox.Max.Z - bbox.Min.Z:.2f}\n"
            info += f"最大直径: {max([c.Diameter for c in self.circles]):.2f}\n"
        if self.cut_plane:
            info += f"裁切平面高度(height): {self.cut_plane_height:.2f}\n"
            info += f"裁切平面倾角(tilt_deg): {self.cut_plane_tilt_deg:.2f}\n"
        return info

if __name__ == "__main__":
    # ==================== GhPython组件主体 ====================

    # 处理输入参数默认值
    if base_point is None:
        base_point = rg.Point3d(0, 0, 0)

    if ref_plane is None:
        ref_plane = rg.Plane.WorldXY

    # 裁切输入：缺省用默认值
    if 'cut_plane_height' not in dir() or cut_plane_height is None:
        cut_plane_height = 40.0

    if 'cut_plane_tilt_deg' not in dir() or cut_plane_tilt_deg is None:
        cut_plane_tilt_deg = 16.0

    if 'cut_enabled' not in dir() or cut_enabled is None:
        cut_enabled = True

    if 'section_diameters' not in dir() or section_diameters is None or len(section_diameters) == 0:
        section_diameters = None

    if 'section_heights' not in dir() or section_heights is None or len(section_heights) == 0:
        section_heights = None

    if 'bulge_distances' not in dir() or bulge_distances is None or len(bulge_distances) == 0:
        bulge_distances = None

    if 'close_caps' not in dir() or close_caps is None:
        close_caps = True

    # 创建宝瓶生成器
    vase_gen = VaseGenerator(
        base_point, ref_plane,
        section_diameters, section_heights,
        bulge_distances,
        cut_plane_height=cut_plane_height,
        cut_plane_tilt_deg=cut_plane_tilt_deg,
        cut_enabled=cut_enabled
    )

    # 生成宝瓶（返回：circles, rails, cut_plane_internal, vase）
    circles, rails, _cut_plane_internal, vase = vase_gen.generate(close_ends=close_caps)

    # ✅ 输出端增加：过 base_point 的参考平面（ref_plane 的原点已平移到 base_point）
    base_ref_plane = vase_gen.ref_plane

    # ⚠️ 按你的要求：不显示裁切面，因此不向 GH 输出 cut_plane（置为 None）
    cut_plane = None

    # 获取信息
    info = vase_gen.get_info()

    # ==================== Debug outputs for cut pipeline (Brep|Plane -> BoundarySurfaces -> SplitBrep) ====================
    # Brep | Plane
    BXPlane_Curves = getattr(vase_gen, 'BXPlane_Curves', [])
    BXPlane_Points = getattr(vase_gen, 'BXPlane_Points', [])

    # Boundary Surfaces
    BoundarySurfaces_Surfaces = getattr(vase_gen, 'BoundarySurfaces_Surfaces', [])
    BoundarySurfaces_CutterBrep = getattr(vase_gen, 'BoundarySurfaces_CutterBrep', None)

    # Split Brep
    SplitBrep_Fragments = getattr(vase_gen, 'SplitBrep_Fragments', [])
    SplitBrep_Areas = getattr(vase_gen, 'SplitBrep_Areas', [])
    SplitBrep_SortedIndex = getattr(vase_gen, 'SplitBrep_SortedIndex', [])
    SplitBrep_KeptBrep = getattr(vase_gen, 'SplitBrep_KeptBrep', None)

    # Cap Holes Ex (final cap state on kept brep)
    CappedBrep = getattr(vase_gen, 'CappedBrep', None)
    Cap_Count = getattr(vase_gen, 'Cap_Count', 0)
    Cap_IsSolid = getattr(vase_gen, 'Cap_IsSolid', False)

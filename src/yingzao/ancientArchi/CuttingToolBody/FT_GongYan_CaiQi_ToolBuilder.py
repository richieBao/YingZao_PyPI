# -*- coding: utf-8 -*-
"""
FT_GongYan_CaiQi_ToolBuilder (v2.6-OffsetToolBreps-NormalsOutward-QiaoArc)
栱眼-材栔 截面特征工具 - 完整K-N-O-B-F-E-A-H-K截面

新增 / 调整:
    - Thickness : 截面挤出厚度（沿参考平面 ZAxis）
    - OffsetDist: 第二个实体相对于第一个实体的总偏移距离（分°），
                  第二个实体的平移量 = OffsetDist - Thickness
    - 自动确保 ToolBrep 中各个 Brep 为“外法向”闭合体（SolidOrientation = Outward）
    - A-R-H 三点弧的构造方式与 qiao (build_qiao_section) 完全一致：
        * diag_vec = H - A
        * mid_pt = (A, H) 中点
        * perp_vec = ZAxis × diag_vec
        * 根据与 YAxis 的点积确定方向，朝“高”方向 (Y+) 偏移
        * R = mid_pt + perp_vec * JR
        * arc = Arc(A, R, H) → ArcCurve
"""

import Rhino.Geometry as rg
import math
import System


class FT_GongYan_CaiQi_ToolBuilder(object):
    """
    栱眼-材栔 截面特征工具构建器

    构建完整对称截面: K-N-O-B-F-E-A-H-K

    左半部分: L → K → H →(弧 H→A)→ A →(弧 A→E)→ E → M

    镜像轴: L-M（垂直线）

    最后通过L-M轴对称生成右半部分，Join后封面

    输入参数：
        base_point:    Point3d - 基准点E的位置
        section_plane: Plane   - 参考平面（默认XZ平面）
        EM_fen:        float   - E-M线段长度（默认10.0）
        EC_fen:        float   - E-C辅助线段高度（默认3.0）
        AI_fen:        float   - A-I线段长度（默认2.0）
        AG_fen:        float   - A-G线段高度（默认4.0）
        JR_fen:        float   - J到R的距离（默认0.5）
        HK_fen:        float   - H-K线段高度（默认2.0）
        Thickness:     float   - 截面厚度（沿参考平面Z轴挤出，默认1.0）
        OffsetDist:    float   - 偏移距离（默认10.0），
                                 第二个实体 = 第一个实体沿Z轴移动 (OffsetDist - Thickness)

    输出：
        SectionCurve : 完整闭合截面轮廓 K-N-O-B-F-E-A-H-K
        SectionFace  : 平面封面 Brep
        LeftCurve    : 左半部分轮廓（调试用）
        RightCurve   : 右半部分轮廓（调试用）
        SymmetryAxis : 对称轴L-M（线段）
        AllPoints    : 所有关键点列表
        ToolBrep     : [Brep0, Brep1] 两个封闭实体的列表
        SectionPlanes: list[rg.Plane]，过 A 点与 A' 点（A 沿挤出方向移动 Thickness 后）的
                       XY / XZ / YZ 共 6 个参考平面
        Log          : 详细日志
    """

    def __init__(self,
                 base_point,
                 section_plane=None,
                 EM_fen=None,
                 EC_fen=None,
                 AI_fen=None,
                 AG_fen=None,
                 JR_fen=None,
                 HK_fen=None,
                 Thickness=None,
                 OffsetDist=None
                 ):

        self.base = base_point if base_point else rg.Point3d(0, 0, 0)

        # 参考平面（默认XZ平面）
        if section_plane is None:
            x = rg.Vector3d(1, 0, 0)
            y = rg.Vector3d(0, 0, 1)
            section_plane = rg.Plane(self.base, x, y)

        self.plane = section_plane

        # 参数
        self.EM = 10.0 if EM_fen is None else float(EM_fen)
        self.EC = 3.0 if EC_fen is None else float(EC_fen)
        self.AI = 2.0 if AI_fen is None else float(AI_fen)
        self.AG = 4.0 if AG_fen is None else float(AG_fen)
        self.JR = 0.5 if JR_fen is None else float(JR_fen)
        self.HK = 2.0 if HK_fen is None else float(HK_fen)

        # Thickness：截面厚度
        self.Thickness = 1.0 if Thickness is None else float(Thickness)
        # OffsetDist：偏移总距离
        self.OffsetDist = 10.0 if OffsetDist is None else float(OffsetDist)

        self.log = ""
        self.tolerance = 0.001

    # ----------------------------------------------------------------------
    # 日志工具
    # ----------------------------------------------------------------------
    def logln(self, s):
        self.log += str(s) + "\n"

    def log_point(self, name, pt):
        self.logln("  {}: ({:.4f}, {:.4f}, {:.4f})".format(name, pt.X, pt.Y, pt.Z))

    # ----------------------------------------------------------------------
    # 法向修正工具：确保封闭体为“外法向”
    # ----------------------------------------------------------------------
    def _ensure_outward_normals(self, brep, tag=""):
        """
        若 brep 为封闭体(IsSolid=True)，则检测 brep.SolidOrientation，
        如为 Inward，则执行 brep.Flip()，使之变为 Outward。
        对于非封闭体，仅记录日志，不强行处理。
        """
        if brep is None:
            self.logln("  {}: Brep 为 None，无法修正法向".format(tag))
            return None

        try:
            if not brep.IsSolid:
                self.logln("  {}: Brep.IsSolid = False，非封闭体，无法严格定义“外法向”".format(tag))
                return brep

            # RhinoCommon: Brep.SolidOrientation 枚举
            try:
                ori = brep.SolidOrientation
                self.logln("  {}: SolidOrientation = {}".format(tag, ori))
            except Exception as e:
                # 某些旧版本若无该属性，则跳过
                self.logln("  {}: 无法获取 SolidOrientation，异常: {}".format(tag, str(e)))
                return brep

            if ori == rg.BrepSolidOrientation.Inward:
                brep.Flip()
                self.logln("  {}: SolidOrientation 为 Inward，已执行 brep.Flip() → 使法向朝外 (Outward)".format(tag))
            elif ori == rg.BrepSolidOrientation.Outward:
                self.logln("  {}: SolidOrientation 已为 Outward，无需调整".format(tag))
            else:
                # Unknown 或 None 等情况
                self.logln("  {}: SolidOrientation = {} (未知/不确定)，未做 Flip".format(tag, ori))

        except Exception as e:
            self.logln("  {}: 检测/修正法向时异常: {}".format(tag, str(e)))

        return brep

    # ========================================================================
    # build()
    # ========================================================================
    def build(self):

        try:
            self.logln("=" * 70)
            self.logln("FT_GongYan_CaiQi_ToolBuilder v2.6 - Thickness & OffsetDist & NormalsOutward & QiaoArc")
            self.logln("=" * 70)

            P = self.plane
            X = P.XAxis
            Y = P.YAxis
            Z = P.ZAxis

            self.logln("\n[参考平面] 使用传入的 SectionPlane（默认 XZ 平面）")
            self.logln(
                "[参数] EM={:.2f} EC={:.2f} AI={:.2f} AG={:.2f} JR={:.2f} HK={:.2f} Thickness={:.2f} OffsetDist={:.2f}".format(
                    self.EM, self.EC, self.AI, self.AG, self.JR, self.HK, self.Thickness, self.OffsetDist))

            # ================================================================
            # 第1部分：构建左半部分所有点
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤1] 构建左半部分点")
            self.logln("-" * 70)

            # E, M, C
            E = rg.Point3d(self.base)
            M = E + X * self.EM
            C = E + Y * self.EC

            self.log_point("E (基准点)", E)
            self.log_point("M (E沿X+)", M)
            self.log_point("C (E沿Y+)", C)

            radius = E.DistanceTo(C)
            self.logln("  半径 EC = {:.4f}".format(radius))

            # A = C - X * radius
            A = C - X * radius
            self.log_point("A (C-X*radius)", A)

            # I, G, H
            I = A + X * self.AI
            G = A + Y * self.AG
            H = I + Y * self.AG

            self.log_point("I (A+X*AI)", I)
            self.log_point("G (A+Y*AG)", G)
            self.log_point("H (I+Y*AG)", H)

            # J = A-H 中点
            J = rg.Point3d(
                0.5 * (A.X + H.X),
                0.5 * (A.Y + H.Y),
                0.5 * (A.Z + H.Z)
            )
            self.log_point("J (A-H中点)", J)

            # ================================
            # R 点：完全按 qiao 的构造方法来
            # ----------------
            # qiao 中的做法：
            #   diag_vec = ptV - ptH
            #   mid_pt = (ptH + ptV)/2
            #   perp_vec = ZAxis × diag_vec
            #   如果 perp_vec·YAxis < 0 则反向
            #   perp_vec.Unitize()
            #   mid_offset_pt = mid_pt + perp_vec * offset_fen
            #
            # 这里映射为：
            #   ptH → A
            #   ptV → H
            #   mid_pt → J (A-H 中点)
            #   offset_fen → JR
            #   mid_offset_pt → R
            # ================================
            self.logln("\n  [R 点构造] 与 qiao 的三点弧算法保持一致")

            diag_vec = H - A  # 对角线向量 (A -> H)
            perp_vec = rg.Vector3d.CrossProduct(Z, diag_vec)  # 平面内垂直于 AH 的向量

            y_axis = Y
            if rg.Vector3d.Multiply(perp_vec, y_axis) < 0:
                perp_vec.Reverse()

            if not perp_vec.Unitize():
                # 如果对角线退化，退而用 Y 轴方向
                perp_vec = rg.Vector3d(y_axis)

            R = J + perp_vec * self.JR
            self.log_point("R (J+perp_vec*JR, qiao 同源算法)", R)

            # K = H + Y * HK
            K = H + Y * self.HK
            self.log_point("K (H+Y*HK)", K)

            # L = M.X, K.Y
            L = rg.Point3d(M.X, K.Y, K.Z)
            self.log_point("L (K水平线与M竖直线交点)", L)

            # ================================================================
            # 第2部分：构建弧线
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤2] 构建弧线")
            self.logln("-" * 70)

            # 弧 AE （近似 1/4 圆）—— 保持原来算法，不过用 Arc + ArcCurve 更统一
            try:
                vA = A - C
                vE = E - C
                mid_vec = vA + vE
                if mid_vec.IsTiny():
                    mid_vec = vA
                mid_vec.Unitize()
                mid = C + mid_vec * radius
                AE_arc = rg.Arc(A, mid, E)
                AE = rg.ArcCurve(AE_arc)
                self.logln("  ✓ 弧 AE 创建成功（ArcCurve）")
            except Exception as e:
                self.logln("  ✗ 弧 AE 创建失败，使用直线代替: {}".format(str(e)))
                AE = rg.LineCurve(rg.Line(A, E))

            # 弧 ARH（三点弧）—— 完全按 qiao 的三点弧风格：Arc + ArcCurve(A, R, H)
            try:
                ARH_arc = rg.Arc(A, R, H)
                if not ARH_arc.IsValid:
                    raise Exception("Arc(A, R, H) 无效")
                ARH = rg.ArcCurve(ARH_arc)
                self.logln("  ✓ 弧 ARH 创建成功（与 qiao 三点弧方法同源）")
            except Exception as e:
                self.logln("  ✗ 弧 ARH 创建失败，使用折线代替: {}".format(str(e)))
                poly = rg.Polyline([A, R, H])
                ARH = poly.ToNurbsCurve()

            # ================================================================
            # 第3部分：拼接左半曲线
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤3] 拼接左半部分轮廓")
            self.logln("-" * 70)

            segs_left = []
            # L → K
            segs_left.append(rg.LineCurve(rg.Line(L, K)))
            # K → H
            segs_left.append(rg.LineCurve(rg.Line(K, H)))
            # H → A（弧 ARH 反向）
            ARH_rev = ARH.DuplicateCurve()
            ARH_rev.Reverse()
            segs_left.append(ARH_rev)
            # A → E（弧 AE）
            segs_left.append(AE)
            # E → M
            segs_left.append(rg.LineCurve(rg.Line(E, M)))

            left_join = rg.Curve.JoinCurves(segs_left, self.tolerance)
            if not left_join or len(left_join) == 0:
                self.logln("  ✗ 左半部分连接失败")
                return None, None, None, None, None, None, None, None, self.log

            left_curve = left_join[0]
            self.logln("  ✓ 左半部分轮廓构建完成")

            # ================================================================
            # 第4部分：镜像右半部分
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤4] 镜像生成右半部分")
            self.logln("-" * 70)

            # 镜像平面：过 M，法向 X（即以 L-M 竖直线为对称轴）
            MirrorPlane = rg.Plane(M, X)
            self.logln("  镜像平面：过 M，法向 XAxis")
            xf = rg.Transform.Mirror(MirrorPlane)

            right_curve = left_curve.DuplicateCurve()
            right_curve.Transform(xf)
            self.logln("  ✓ 右半部分镜像完成")

            # ================================================================
            # 第5部分：合并完整轮廓
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤5] 合并完整轮廓")
            self.logln("-" * 70)

            full_join = rg.Curve.JoinCurves([left_curve, right_curve], self.tolerance)
            if not full_join or len(full_join) == 0:
                self.logln("  ✗ 完整轮廓连接失败")
                return None, None, None, None, None, None, None, None, self.log

            SectionCurve = full_join[0]
            if SectionCurve.IsClosed:
                self.logln("  ✓ 完整轮廓已闭合")
            else:
                self.logln("  ⚠ 警告：完整轮廓未闭合")

            # ================================================================
            # 第6部分：创建平面封面
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤6] 创建平面封面 SectionFace")
            self.logln("-" * 70)

            try:
                breps = rg.Brep.CreatePlanarBreps(SectionCurve, self.tolerance)
                if breps and len(breps) > 0:
                    SectionFace = breps[0]
                    self.logln("  ✓ 平面封面创建成功")
                else:
                    SectionFace = None
                    self.logln("  ⚠ 无法从轮廓创建平面封面")
            except Exception as e:
                SectionFace = None
                self.logln("  ✗ 创建平面封面异常: {}".format(str(e)))

            # ================================================================
            # 第7部分：收集所有关键点
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤7] 收集所有关键点")
            self.logln("-" * 70)

            LeftPoints = [E, M, C, A, I, G, H, J, R, K, L]

            RightPoints = []
            for p in LeftPoints:
                q = rg.Point3d(p)
                q.Transform(xf)
                RightPoints.append(q)

            AllPoints = LeftPoints + RightPoints
            self.logln("  左半部分点数: {}".format(len(LeftPoints)))
            self.logln("  右半部分点数: {}".format(len(RightPoints)))
            self.logln("  总点数: {}".format(len(AllPoints)))

            SymmetryAxis = rg.Line(M, L)

            # ================================================================
            # 第8部分：沿 ZAxis 挤出 Thickness => 第一个实体
            #            再复制并沿 ZAxis 平移 (OffsetDist - Thickness)
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤8] 按 Thickness 挤出实体，并按 OffsetDist 复制偏移")
            self.logln("-" * 70)

            ToolBreps = []

            if SectionCurve is not None and SectionCurve.IsClosed:
                try:
                    # 挤出方向：Z 轴 * Thickness
                    direction = Z * self.Thickness
                    self.logln("  挤出方向: ({:.4f}, {:.4f}, {:.4f})".format(direction.X, direction.Y, direction.Z))

                    # Step 1: 用截面曲线挤出成曲面
                    srf = rg.Surface.CreateExtrusion(SectionCurve, direction)
                    if srf is None:
                        self.logln("  ✗ Surface.CreateExtrusion 失败")
                    else:
                        brep_extrude = rg.Brep.CreateFromSurface(srf)
                        if brep_extrude is None:
                            self.logln("  ✗ Brep.CreateFromSurface 失败")
                        else:
                            # Step 2: CapPlanarHoles —— 兼容两种返回类型
                            capped = rg.Brep.CapPlanarHoles(brep_extrude, self.tolerance)

                            ToolBrep0 = None

                            if capped is None:
                                self.logln("  ⚠ CapPlanarHoles 返回 None")
                            elif isinstance(capped, rg.Brep):
                                ToolBrep0 = capped
                                self.logln("  ✓ ToolBrep0 生成成功（单个 Brep）")
                            elif isinstance(capped, System.Array[rg.Brep]) or isinstance(capped, list):
                                if len(capped) > 0:
                                    ToolBrep0 = capped[0]
                                    self.logln("  ✓ ToolBrep0 生成成功（数组/列表版本）")
                                else:
                                    self.logln("  ⚠ CapPlanarHoles 返回空数组")
                            else:
                                self.logln("  ⚠ CapPlanarHoles 返回未知类型：{}".format(type(capped)))

                            if ToolBrep0 is not None:
                                # ★ 确保第一个实体法向朝外
                                ToolBrep0 = self._ensure_outward_normals(ToolBrep0, tag="ToolBrep0")

                                ToolBreps.append(ToolBrep0)

                                # 计算偏移量: OffsetDist - Thickness
                                offset_delta = self.OffsetDist - self.Thickness
                                offset_vec = Z * offset_delta
                                self.logln("  第二个实体偏移量: OffsetDist - Thickness = {:.4f}".format(offset_delta))
                                self.logln("  偏移向量: ({:.4f}, {:.4f}, {:.4f})".format(
                                    offset_vec.X, offset_vec.Y, offset_vec.Z))

                                # 复制并平移得到 ToolBrep1
                                ToolBrep1 = ToolBrep0.DuplicateBrep()
                                xform_move = rg.Transform.Translation(offset_vec)
                                ToolBrep1.Transform(xform_move)

                                # ★ 同样确保第二个实体法向朝外（理论上复制后仍为 Outward，仅日志确认）
                                ToolBrep1 = self._ensure_outward_normals(ToolBrep1, tag="ToolBrep1")

                                ToolBreps.append(ToolBrep1)
                                self.logln("  ✓ ToolBrep1 复制并偏移成功（共2个实体）")

                except Exception as e:
                    self.logln("  ✗ 挤出生成 ToolBrep 异常: {}".format(str(e)))
            else:
                self.logln("  ⚠ SectionCurve 不存在或未闭合，无法挤出")

            # ================================================================
            # 第8.5部分：检查 ToolBreps 是否为封闭体（IsSolid）及法向
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤8.5] 检查 ToolBreps 封闭性（IsSolid）及法向方向")
            self.logln("-" * 70)

            if not ToolBreps:
                self.logln("  ⚠ ToolBreps 为空，未生成任何刀具实体")
            else:
                for idx, brep in enumerate(ToolBreps):
                    if brep is None:
                        self.logln("  ToolBrep[{}]: 为 None".format(idx))
                        continue
                    is_valid = brep.IsValid
                    is_solid = brep.IsSolid
                    self.logln("  ToolBrep[{}]: IsValid = {}, IsSolid = {}".format(idx, is_valid, is_solid))

                    # 再次记录 SolidOrientation（此时应已为 Outward）
                    try:
                        ori = brep.SolidOrientation
                        self.logln("    SolidOrientation = {}".format(ori))
                    except Exception as e:
                        self.logln("    无法获取 SolidOrientation: {}".format(str(e)))

                    if is_solid and is_valid:
                        self.logln("    ✓ 该刀具为有效封闭体，可用于布尔裁切。")
                    elif not is_valid:
                        self.logln("    ⚠ 该刀具 Brep 无效（IsValid=False），建议检查几何构造。")
                    else:
                        self.logln("    ⚠ 该刀具不是封闭体（IsSolid=False），可能无法用于布尔裁切。")

            # ================================================================
            # 第9部分：过 A 点和 A' 点的参考平面（XY, XZ, YZ）
            # ================================================================
            self.logln("\n" + "-" * 70)
            self.logln("[步骤9] 构建过 A 点与 A' 点的参考平面 SectionPlanes")
            self.logln("-" * 70)

            # A 点的三平面
            Plane_XY_A = rg.Plane(A, X, Y)
            Plane_XZ_A = rg.Plane(A, X, Z)
            Plane_YZ_A = rg.Plane(A, Y, Z)

            # A' 点 = A 沿挤出方向 Z 移动 Thickness 距离
            A_offset = A + Z * self.Thickness
            self.log_point("A_offset (A+Z*Thickness)", A_offset)

            Plane_XY_A2 = rg.Plane(A_offset, X, Y)
            Plane_XZ_A2 = rg.Plane(A_offset, X, Z)
            Plane_YZ_A2 = rg.Plane(A_offset, Y, Z)

            SectionPlanes = [
                Plane_XY_A, Plane_XZ_A, Plane_YZ_A,
                Plane_XY_A2, Plane_XZ_A2, Plane_YZ_A2
            ]

            self.logln("  ✓ SectionPlanes 已生成（A 与 A' 的 XY/XZ/YZ 共 6 个平面）")

            # ================================================================
            # 完成
            # ================================================================
            self.logln("\n" + "=" * 70)
            self.logln("✓ 截面与 ToolBreps 构建完成")
            self.logln("=" * 70)

            return (SectionCurve,
                    SectionFace,
                    left_curve,
                    right_curve,
                    SymmetryAxis,
                    AllPoints,
                    ToolBreps,
                    SectionPlanes,
                    self.log)

        except Exception as e:
            import traceback
            self.logln("\n✗ 构建异常：")
            self.logln(str(e))
            self.logln(traceback.format_exc())
            return None, None, None, None, None, None, None, None, self.log

if __name__ == "__main__":
    # =====================================================================
    # Grasshopper Python 执行区
    # =====================================================================

    try:
        builder = FT_GongYan_CaiQi_ToolBuilder(
            base_point=BasePoint,
            section_plane=SectionPlane,
            EM_fen=EM_fen,
            EC_fen=EC_fen,
            AI_fen=AI_fen,
            AG_fen=AG_fen,
            JR_fen=JR_fen,
            HK_fen=HK_fen,
            Thickness=Thickness,
            OffsetDist=OffsetDist
        )

        SectionCurve, SectionFace, LeftCurve, RightCurve, SymmetryAxis, AllPoints, ToolBrep, SectionPlanes, Log = builder.build()

    except Exception as e:
        import traceback

        SectionCurve = None
        SectionFace = None
        LeftCurve = None
        RightCurve = None
        SymmetryAxis = None
        AllPoints = None
        ToolBrep = None
        SectionPlanes = None
        Log = "执行异常: {}\n{}".format(str(e), traceback.format_exc())


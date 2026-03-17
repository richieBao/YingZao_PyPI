# -*- coding: utf-8 -*-
"""
ASR_ColumnBaseBuilder
用 GH Python（ghpy）按“柱礎”剖面图构建：
剖面线 → 截面面 → 旋转放样成体 + 顶部立方体布尔合并

----------------------------------------------------------------------
输入（GhPython 建议设置）:
    PlacePlane : rg.Plane (Item)
        放置参考平面（默认 GH 的 XY Plane，原点(0,0,0)）
        点 O = PlacePlane.Origin
        Access: Item
        TypeHints: Plane

    ColumnDiameter_Fen : float (Item)
        柱径 d（单位：分°）
        约定：O-A = d/2
        Access: Item
        TypeHints: float

    ZhiGao_Fen : float (Item)
        櫍高（O-H），默认 7 分°
        Access: Item
        TypeHints: float

    JB_Len_Fen : float (Item)
        J-B 水平外挑长度（= 圆弧 K-B 的半径），默认 3 分°
        Access: Item
        TypeHints: float

    PenChunGao_Fen : float (Item)
        盆唇高（H-I），默认 3 分°
        Access: Item
        TypeHints: float

    CS_Len_Fen : float (Item)
        C-S 水平长度，默认 1 分°
        Access: Item
        TypeHints: float

    ScaleFactor : float (Item)
        比例缩放因子（默认 1.0）。
        按比例缩放“尺寸参数值”（在生成几何之前缩放），从而所有几何与输出同步缩放。
        Access: Item
        TypeHints: float

    Tol : float (Item)
        容差（求交/布尔/封口等），默认 1e-6
        Access: Item
        TypeHints: float

输出（GhPython 建议设置）:
    StoneColumnBase : rg.Brep (Item)
        石质柱礎组合体（RevolvedBrep + CubeBrep 的布尔合并结果）
        Access: Item
        TypeHints: Brep

    Log : str (Item)
        日志
        Access: Item
        TypeHints: str

    # ---- debug outputs ----
    SectionPlane : rg.Plane
    AxisLine     : rg.Line
    Pts          : dict[str, rg.Point3d]
    SectionCrv   : rg.Curve
    SectionCrv_Closed : rg.Curve
    SectionFaceBrep   : rg.Brep
    RevolvedBrep : rg.Brep
    CubeBrep     : rg.Brep
----------------------------------------------------------------------

说明（与附图一致的几何约定）：
- 截面参考平面：以 O 为原点；平面内 X 轴 = PlacePlane.X；平面内 Y 轴 = PlacePlane.Z（此处“Y”为截面平面内竖向）。
  因此 SectionPlane.ZAxis（法向）= PlacePlane.X × PlacePlane.Z = -PlacePlane.Y。
- 旋转轴：过 O，方向为 PlacePlane.Z（也就是 SectionPlane.YAxis）。
"""

import Rhino
import Rhino.Geometry as rg
import math


# =====================================================
# 通用：缩放“尺寸参数值”（参考附件 Solver 的做法：先缩放参数，再生成几何）
# =====================================================
def _scale_numeric_like(x, scale_factor):
    """数值/字符串数值/嵌套 list/tuple 内的数值整体乘以 scale_factor。
    注意：这里用于“尺寸参数”，不用于 Tol。
    """
    if x is None:
        return None
    if scale_factor is None:
        return x
    try:
        sf = float(scale_factor)
    except:
        return x
    if abs(sf - 1.0) < 1e-12:
        return x

    if isinstance(x, (list, tuple)):
        t = [_scale_numeric_like(it, sf) for it in x]
        return t if isinstance(x, list) else tuple(t)

    try:
        v = float(x)
        return v * sf
    except:
        return x


# =====================================================
# Core Builder
# =====================================================
class ColumnBaseBuilder(object):
    def __init__(self, place_plane, d_fen, zhi_gao, jb_len, penchun_gao, cs_len, scale_factor=1.0, tol=1e-6):
        self.PlacePlane = place_plane

        # ScaleFactor：缩放“尺寸参数”（不在最后 Transform.Scale）
        try:
            self.ScaleFactor = float(scale_factor) if scale_factor is not None else 1.0
        except:
            self.ScaleFactor = 1.0

        # ---- 尺寸参数先缩放 ----
        d_scaled = _scale_numeric_like(d_fen, self.ScaleFactor)
        zhi_scaled = _scale_numeric_like(zhi_gao, self.ScaleFactor)
        jb_scaled = _scale_numeric_like(jb_len, self.ScaleFactor)
        penchun_scaled = _scale_numeric_like(penchun_gao, self.ScaleFactor)
        cs_scaled = _scale_numeric_like(cs_len, self.ScaleFactor)

        # ---- 内部数值 ----
        self.d = float(d_scaled)
        self.r = 0.5 * self.d
        self.ZhiGao = float(zhi_scaled)
        self.JB = float(jb_scaled)
        self.PenChunGao = float(penchun_scaled)
        self.CS = float(cs_scaled)

        # Tol 不参与缩放（容差是算法精度，不是尺寸）
        self.Tol = float(tol) if tol and tol > 0 else 1e-6

        self.LogLines = []
        self.SectionPlane = None
        self.AxisLine = None
        self.Pts = {}

        self.SectionCrv = None            # 开母线（用于旋转）
        self.SectionCrv_Closed = None     # 闭合剖面（用于生成截面面）
        self.SectionFaceBrep = None       # 剖面面

        self.RevolvedBrep = None
        self.CubeBrep = None

        # 内部仍保留 AbsStructRep（便于兼容旧命名），最终对外输出 StoneColumnBase
        self.AbsStructRep = None
        self.StoneColumnBase = None

    def _log(self, s):
        self.LogLines.append(str(s))

    # -------------------------------------------------
    # 截面平面
    # -------------------------------------------------
    def build_section_plane(self):
        O = self.PlacePlane.Origin
        xaxis = self.PlacePlane.XAxis
        yaxis = self.PlacePlane.ZAxis  # 截面内竖向
        self.SectionPlane = rg.Plane(O, xaxis, yaxis)
        return self.SectionPlane

    # -------------------------------------------------
    # 平面内定位点（x 水平，z 竖向；都在截面平面内）
    # -------------------------------------------------
    def _pt(self, x, z):
        return self.SectionPlane.PointAt(x, z)

    # -------------------------------------------------
    # 计算关键点
    # -------------------------------------------------
    def compute_points(self):
        d = self.d
        r = self.r

        O = self._pt(0, 0)
        A = self._pt(r, 0)
        H = self._pt(0, -self.ZhiGao)
        J = self._pt(r, -self.ZhiGao)
        B = self._pt(r + self.JB, -self.ZhiGao)
        H2 = self._pt(r + self.JB, -self.ZhiGao + self.JB)
        K = self._pt(r, -self.ZhiGao + self.JB)
        I = self._pt(0, -self.ZhiGao - self.PenChunGao)
        C = self._pt(r + self.JB, -self.ZhiGao - self.PenChunGao)
        S = self._pt(r + self.JB + self.CS, -self.ZhiGao - self.PenChunGao)

        N = self._pt(0, (-self.ZhiGao - self.PenChunGao) - d/50.0)
        M = self._pt((r + self.JB + self.CS),
                     (-self.ZhiGao - self.PenChunGao) - d/50.0)

        G = self._pt(0,
                     (-self.ZhiGao - self.PenChunGao) - d/50.0 - d/5.0)

        P = self._pt((r + self.JB + self.CS),
                     (-self.ZhiGao - self.PenChunGao) - d/50.0 - d/5.0)

        D = self._pt((r + self.JB + self.CS) + d/5.0,
                     (-self.ZhiGao - self.PenChunGao) - d/50.0 - d/5.0)

        O2 = self._pt(0,
                      (-self.ZhiGao - self.PenChunGao)
                      - d/50.0 - d/5.0 - d)

        self.Pts = {
            "O": O, "A": A, "H": H, "J": J, "B": B,
            "H2": H2, "K": K,
            "I": I, "C": C, "S": S,
            "N": N, "M": M,
            "G": G, "P": P, "D": D,
            "O'": O2
        }
        return self.Pts

    # -------------------------------------------------
    # 构建剖面曲线：开母线 + 闭合剖面
    # -------------------------------------------------
    def build_section_curve(self):
        pts = self.Pts
        tol = self.Tol

        seg_OA = rg.LineCurve(pts["O"], pts["A"])
        seg_AK = rg.LineCurve(pts["A"], pts["K"])

        # --- K-B 圆弧（圆心 H2）---
        center1 = pts["H2"]
        radius1 = center1.DistanceTo(pts["B"])
        vK = pts["K"] - center1
        vB = pts["B"] - center1
        vK.Unitize()
        vB.Unitize()
        vMid = vK + vB
        if vMid.IsTiny(tol):
            vMid = rg.Vector3d(-1, 0, -1)
        vMid.Unitize()
        midPt1 = center1 + vMid * radius1
        arc_KB = rg.Arc(pts["K"], midPt1, pts["B"])
        crv_KB = rg.ArcCurve(arc_KB)

        seg_BC = rg.LineCurve(pts["B"], pts["C"])
        seg_CS = rg.LineCurve(pts["C"], pts["S"])
        seg_SM = rg.LineCurve(pts["S"], pts["M"])

        # --- M-D 圆弧（圆心 P）---
        center2 = pts["P"]
        radius2 = center2.DistanceTo(pts["D"])
        vM = pts["M"] - center2
        vD = pts["D"] - center2
        vM.Unitize()
        vD.Unitize()
        vMid2 = vM + vD
        if vMid2.IsTiny(tol):
            vMid2 = rg.Vector3d(1, 0, 1)
        vMid2.Unitize()
        midPt2 = center2 + vMid2 * radius2
        arc_MD = rg.Arc(pts["M"], midPt2, pts["D"])
        crv_MD = rg.ArcCurve(arc_MD)

        seg_DG = rg.LineCurve(pts["D"], pts["G"])
        seg_GO2 = rg.LineCurve(pts["D"], pts["G"])  # 先占位再覆盖（保持结构不变）
        seg_GO2 = rg.LineCurve(pts["G"], pts["O'"])

        # ------------------------
        # 开母线（用于旋转）：O-A-K-B-C-S-M-D-G-O'
        # ------------------------
        profile = rg.PolyCurve()
        for c in [seg_OA, seg_AK, crv_KB,
                  seg_BC, seg_CS, seg_SM,
                  crv_MD, seg_DG, seg_GO2]:
            profile.Append(c)
        self.SectionCrv = profile

        # ------------------------
        # 闭合剖面（用于生成截面面）：追加 O'->O
        # ------------------------
        seg_O2O = rg.LineCurve(pts["O'"], pts["O"])
        closed = rg.PolyCurve()
        for c in [seg_OA, seg_AK, crv_KB,
                  seg_BC, seg_CS, seg_SM,
                  crv_MD, seg_DG, seg_GO2,
                  seg_O2O]:
            closed.Append(c)
        closed.MakeClosed(tol)
        self.SectionCrv_Closed = closed

        return self.SectionCrv

    # -------------------------------------------------
    # 旋转放样：闭合剖面 -> 截面面；开母线 -> 旋转一周成体
    # -------------------------------------------------
    def build_revolved_brep(self):
        O = self.Pts["O"]
        axis_dir = rg.Vector3d(self.PlacePlane.ZAxis)
        axis_dir.Unitize()
        axis = rg.Line(O, O + axis_dir * 1000.0)
        self.AxisLine = axis

        # 1) 先生成截面面
        self.SectionFaceBrep = None
        if self.SectionCrv_Closed:
            faces = rg.Brep.CreatePlanarBreps(self.SectionCrv_Closed, self.Tol)
            if faces and len(faces) > 0:
                self.SectionFaceBrep = faces[0]
            else:
                self._log("CreatePlanarBreps failed.")

        # 2) 再旋转开母线
        if not self.SectionCrv:
            self._log("SectionCrv missing.")
            self.RevolvedBrep = None
            return None

        revsrf = rg.RevSurface.Create(self.SectionCrv, axis)
        if not revsrf:
            self._log("RevSurface.Create failed.")
            self.RevolvedBrep = None
            return None

        b = revsrf.ToBrep()
        if not b:
            self._log("ToBrep failed.")
            self.RevolvedBrep = None
            return None

        b2 = b.CapPlanarHoles(self.Tol)
        if b2:
            b = b2

        self.RevolvedBrep = b
        return self.RevolvedBrep

    # -------------------------------------------------
    # 构建立方体
    # -------------------------------------------------
    def build_cube_brep(self):
        d = self.d
        G = self.Pts["G"]

        top_plane = rg.Plane(G, self.PlacePlane.XAxis, self.PlacePlane.YAxis)
        half_side = d  # 因为边长 = 2*d
        xint = rg.Interval(-half_side, half_side)
        yint = rg.Interval(-half_side, half_side)
        zint = rg.Interval(-d, 0.0)

        box = rg.Box(top_plane, xint, yint, zint)
        self.CubeBrep = box.ToBrep()
        return self.CubeBrep

    # -------------------------------------------------
    # 布尔合并
    # -------------------------------------------------
    def boolean_union(self):
        breps = []
        if self.RevolvedBrep:
            breps.append(self.RevolvedBrep)
        if self.CubeBrep:
            breps.append(self.CubeBrep)

        if not breps:
            self.AbsStructRep = None
            self.StoneColumnBase = None
            return None

        if len(breps) == 1:
            self.AbsStructRep = breps[0]
            self.StoneColumnBase = self.AbsStructRep
            return self.AbsStructRep

        u = rg.Brep.CreateBooleanUnion(breps, self.Tol)
        if u and len(u) > 0:
            self.AbsStructRep = u[0]
            self.StoneColumnBase = self.AbsStructRep
            return self.AbsStructRep

        self._log("BooleanUnion failed.")
        j = rg.Brep.JoinBreps(breps, self.Tol)
        if j and len(j) > 0:
            self.AbsStructRep = j[0]
        else:
            self.AbsStructRep = breps[0]

        self.StoneColumnBase = self.AbsStructRep
        return self.AbsStructRep

    # -------------------------------------------------
    def solve(self):
        try:
            self.build_section_plane()
            self.compute_points()
            self.build_section_curve()
            self.build_revolved_brep()
            self.build_cube_brep()
            self.boolean_union()
        except Exception as e:
            self._log("EXCEPTION: {}".format(e))

        return self.StoneColumnBase, "\n".join(self.LogLines)

if __name__ == "__main__":
    # =====================================================
    # GH Python 入口（以 GH 输入端变量名为准）
    # =====================================================
    # 期望 GH 输入端变量：
    # PlacePlane, ColumnDiameter_Fen, ZhiGao_Fen, JB_Len_Fen, PenChunGao_Fen, CS_Len_Fen, ScaleFactor, Tol

    _builder = ColumnBaseBuilder(
        PlacePlane,
        ColumnDiameter_Fen,
        ZhiGao_Fen,
        JB_Len_Fen,
        PenChunGao_Fen,
        CS_Len_Fen,
        ScaleFactor,
        Tol
    )

    StoneColumnBase, Log = _builder.solve()


    # =====================================================
    # GH Python 组件 · 输出绑定区（保留全部绑定，便于调试/后续扩展）
    # =====================================================
    SectionPlane      = _builder.SectionPlane
    AxisLine          = _builder.AxisLine
    Pts               = _builder.Pts
    SectionCrv        = _builder.SectionCrv
    SectionCrv_Closed = _builder.SectionCrv_Closed
    SectionFaceBrep   = _builder.SectionFaceBrep

    RevolvedBrep      = _builder.RevolvedBrep
    CubeBrep          = _builder.CubeBrep

    StoneColumnBase   = _builder.StoneColumnBase
    Log               = Log
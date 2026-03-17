# -*- coding: utf-8 -*-
"""
GhPython | YingZaoLab
由昂（昂）截面（按用户草图与步骤说明）

把本文件内容粘贴到 GhPython 组件中即可运行（或作为模块 import）。
脚本采用"类 + 方法"的组织方式，便于后续扩展调用。

------------------------------------------------------------
GH 组件建议输入端（Inputs）
------------------------------------------------------------
base_point   : Rhino.Geometry.Point3d   # O 点（定位点）
RefPlaneMode : str                     # 参考平面模式：WorldXY/XY, WorldXZ/XZ, WorldYZ/YZ（默认 WorldXZ）

OA_len       : float   # O->A 沿 refPlane -Y 方向（默认 15）
AC_len       : float   # A->C 沿 refPlane -X 方向（默认 52.4）
BD_len       : float   # B 到 refPlane 的 Y 轴（过O点）距离（默认 115.22）
OffsetY      : float   # 将 OB 向 +Y 方向偏移得到 EF 的偏移距离（默认 15）
H_dist       : float   # H 到 refPlane Y 轴距离（默认 82.72）
GH_len       : float   # H->G 沿 -X 方向长度（默认 6）

SectionOffsetZ : float # 截面沿 refPlane 的 ±Z 方向偏移距离（默认 5）

------------------------------------------------------------
GH 组件输出端（Outputs）
------------------------------------------------------------
PtsKeys      : list[str]      # 点名（索引标识）
PtsValues    : list[Point3d]   # 点几何
CrvsKeys     : list[str]      # 曲线名（索引标识）
CrvsValues   : list            # Line/Polyline 等几何
PlanesAKeys  : list[str]      # 平面A名（索引标识）
PlanesAValues: list[Plane]     # 平面A几何
PlanesBKeys  : list[str]      # 平面B名（索引标识）
PlanesBValues: list[Plane]     # 平面B几何

SectionCrvs  : list            # [原截面, +Z 偏移截面, -Z 偏移截面]（便于调试）
LoftBrep     : rg.Brep         # 两侧截面放样得到的侧面 Brep（不封端）
SolidBrep    : rg.Brep         # 由两侧截面放样+封端得到的实体
OBLoftBrep   : rg.Brep         # O-B线段垂直偏移后放样的面
Log          : list[str]        # 日志

修复说明：
- RhinoCommon 的 Plane.ClosestParameter(Point3d) 在 Python 中返回 (success, u, v) 三元组，
  之前代码用 (ok, uv) 二元组解包会触发：ValueError: too many values to unpack (expected 2)。
  本版已改为 ok, u, v = pl.ClosestParameter(G) 并做失败兜底。
- 新增：O-B线段垂直于参考平面两侧偏移SectionOffsetZ距离，然后放样成面输出到OBLoftBrep
"""
import Rhino.Geometry as rg


# ------------------------------------------------------------
# 工具方法
# ------------------------------------------------------------
def _coalesce(v, default):
    return default if v is None else v


def make_ref_plane(mode_str, origin=None):
    """GH 参考平面：XY / XZ / YZ；origin 默认为世界原点。"""
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    if mode_str is None:
        mode_str = "WorldXZ"
    m = str(mode_str).upper()

    if m in ("WORLDXY", "XY", "XY_PLANE"):
        # XY Plane: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if m in ("WORLDYZ", "YZ", "YZ_PLANE"):
        # 按用户给定：YZ Plane: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ：X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def plane_perp_to_xaxis(pl, origin=None):
    """过 origin 的平面，法向量与 pl.XAxis 平行（即"垂直于X轴"的参考平面）。"""
    if origin is None:
        origin = pl.Origin
    # 以 (pl.YAxis, pl.ZAxis) 为该平面的 (X,Y) 轴 => 法向 = cross(YAxis, ZAxis) = XAxis
    return rg.Plane(origin, pl.YAxis, pl.ZAxis)


def plane_perp_to_yaxis(pl, origin=None):
    """过 origin 的平面，法向量与 pl.YAxis 平行（即"垂直于Y轴"的参考平面）。"""
    if origin is None:
        origin = pl.Origin
    # 以 (pl.ZAxis, pl.XAxis) 为该平面的 (X,Y) 轴 => 法向 = cross(ZAxis, XAxis) = YAxis
    return rg.Plane(origin, pl.ZAxis, pl.XAxis)


def plane_from_two_vectors(origin, vx, vy):
    """由两向量构建平面（vx 作为 XAxis，vy 将被正交化后作为 YAxis）。"""
    x = rg.Vector3d(vx)
    y = rg.Vector3d(vy)

    if not x.Unitize():
        x = rg.Vector3d(1, 0, 0)

    # 正交化 y
    y = y - rg.Vector3d.Multiply(rg.Vector3d.Multiply(y, x), x)
    if not y.Unitize():
        # 如果共线，则挑一个与 x 不共线的向量
        tmp = rg.Vector3d(0, 0, 1)
        if abs(rg.Vector3d.Multiply(tmp, x)) > 0.99:
            tmp = rg.Vector3d(0, 1, 0)
        y = tmp - rg.Vector3d.Multiply(rg.Vector3d.Multiply(tmp, x), x)
        y.Unitize()

    return rg.Plane(origin, x, y)


def dict_to_kv(d, order=None):
    """
    将 dict 拆分为 (keys, values) 两个列表，供 GhPython 输出端使用。
    - order: 指定键顺序；若不给则按 d.keys() 的当前顺序（不推荐）。
    """
    if d is None:
        return [], []
    if order is None:
        keys = list(d.keys())
    else:
        keys = [k for k in order if k in d]
    vals = [d[k] for k in keys]
    return keys, vals


def get_model_tolerance(default=0.01):
    """尽量读取 Rhino 文档的绝对公差；在 GH 中不可用时回退。"""
    try:
        import Rhino
        doc = Rhino.RhinoDoc.ActiveDoc
        if doc and doc.ModelAbsoluteTolerance > 0:
            return float(doc.ModelAbsoluteTolerance)
    except Exception:
        pass
    return float(default)


# ------------------------------------------------------------
# 主类
# ------------------------------------------------------------
class AngSectionBuilder(object):
    def __init__(self,
                 base_point=None,
                 ref_plane_mode=None,
                 OA_len=21.0,
                 AC_len=52.4,
                 BD_len=115.22,
                 OffsetY=15.0,
                 H_dist=82.72,
                 GH_len=6.0,
                 SectionOffsetZ=5.0):
        self.O = _coalesce(base_point, rg.Point3d(0, 0, 0))
        self.ref_mode = _coalesce(ref_plane_mode, "WorldXZ")

        self.OA_len = float(_coalesce(OA_len, 21.0))
        self.AC_len = float(_coalesce(AC_len, 52.4))
        self.BD_len = float(_coalesce(BD_len, 115.22))
        self.OffsetY = float(_coalesce(OffsetY, 15.0))
        self.H_dist = float(_coalesce(H_dist, 82.72))
        self.GH_len = float(_coalesce(GH_len, 6.0))
        self.SectionOffsetZ = float(_coalesce(SectionOffsetZ, 5.0))

        # 参考平面（过 O 点）
        self.refPlane = make_ref_plane(self.ref_mode, origin=self.O)

        self.pts = {}
        self.crvs = {}
        self.planesA = {}
        self.planesB = {}

    def build(self):
        log = []
        pl = self.refPlane
        O = pl.Origin
        x = pl.XAxis
        y = pl.YAxis
        z = pl.ZAxis

        # 3) O -> A : 沿 -Y
        A = O + (-y) * self.OA_len

        # 4) A -> C : 沿 -X
        C = A + (-x) * self.AC_len

        # 5) 延长 O-C 至 B，使 B 到 refPlane 的 Y 轴距离为 BD_len（平面内 x=-BD_len）
        if abs(self.AC_len) < 1e-9:
            t = 0.0
        else:
            t = self.BD_len / self.AC_len

        B_y = -t * self.OA_len
        B = O + x * (-self.BD_len) + y * (B_y)

        # 6) 用户补充：E-B、F-O 垂直于 B-O，故截面 B-E-F-O-B 为矩形。
        #    即：EF ∥ BO，且 EB、FO 为 refPlane 内对 BO 的法向偏移。
        v_bo = O - B  # B->O
        if not v_bo.Unitize():
            v_bo = rg.Vector3d(x)  # 兜底

        # 在 refPlane 内取垂直于 BO 的方向：perp = ZAxis × BO
        perp = rg.Vector3d.CrossProduct(z, v_bo)
        if not perp.Unitize():
            # 极端情况下（数值问题）兜底为 refPlane 的 YAxis
            perp = rg.Vector3d(y)
            perp.Unitize()

        E = B + perp * self.OffsetY
        F = O + perp * self.OffsetY
        rect = rg.Polyline([B, E, F, O, B])
        section_crv = rg.PolylineCurve(rect)

        # --- 矩形截面沿 refPlane 的 ±Z 偏移，并放样封体 ---
        dz = self.SectionOffsetZ
        xform_p = rg.Transform.Translation(z * dz)
        xform_n = rg.Transform.Translation(z * (-dz))

        sec_p = section_crv.DuplicateCurve()
        sec_n = section_crv.DuplicateCurve()
        sec_p.Transform(xform_p)
        sec_n.Transform(xform_n)

        # 放样生成侧面
        loft_breps = rg.Brep.CreateFromLoft(
            [sec_n, sec_p],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )

        loft_brep = None
        if loft_breps and len(loft_breps) > 0:
            loft_brep = loft_breps[0]
        else:
            log.append("Loft failed: Brep.CreateFromLoft returned empty.")

        # 两端封面（截面是共面的闭合曲线）
        cap_n = rg.Brep.CreatePlanarBreps(sec_n)
        cap_p = rg.Brep.CreatePlanarBreps(sec_p)
        if not cap_n:
            log.append("Cap failed: CreatePlanarBreps(sec_n) returned empty.")
        if not cap_p:
            log.append("Cap failed: CreatePlanarBreps(sec_p) returned empty.")

        # 合并与兜底封孔
        tol = get_model_tolerance(0.01)

        solid = None
        breps_to_join = []
        if loft_brep:
            breps_to_join.append(loft_brep)
        if cap_n:
            breps_to_join.extend(list(cap_n))
        if cap_p:
            breps_to_join.extend(list(cap_p))

        if breps_to_join:
            joined = rg.Brep.JoinBreps(breps_to_join, tol)
            if joined and len(joined) > 0:
                solid = joined[0]
                if not solid.IsSolid:
                    # 尝试封孔
                    try:
                        capped = solid.CapPlanarHoles(tol)
                        if capped and capped.IsSolid:
                            solid = capped
                        else:
                            log.append("Solid is not closed after join/cap.")
                    except Exception as e:
                        log.append("CapPlanarHoles exception: %s" % e)
            else:
                log.append("JoinBreps failed: returned empty.")
        else:
            log.append("No breps to join (loft/caps all missing).")

        # --- 新增：O-B 线段垂直偏移并放样 ---
        line_ob = rg.LineCurve(O, B)

        # 复制 O-B 线段并沿 ±Z 方向偏移
        line_ob_p = line_ob.DuplicateCurve()
        line_ob_n = line_ob.DuplicateCurve()
        line_ob_p.Transform(xform_p)
        line_ob_n.Transform(xform_n)

        # 放样 O-B 线段的两个偏移副本
        ob_loft_breps = rg.Brep.CreateFromLoft(
            [line_ob_n, line_ob_p],
            rg.Point3d.Unset,
            rg.Point3d.Unset,
            rg.LoftType.Normal,
            False
        )

        ob_loft_brep = None
        if ob_loft_breps and len(ob_loft_breps) > 0:
            ob_loft_brep = ob_loft_breps[0]
        else:
            log.append("OB Loft failed: Brep.CreateFromLoft returned empty.")

        # 7) EF 线上取 H，使 H 到 refPlane 的 Y 轴距离为 H_dist（即 |u|=H_dist；取负向 u=-H_dist）
        #    这里用 refPlane 参数(u,v)做线性插值求解。
        okF, uF, vF = pl.ClosestParameter(F)
        okE, uE, vE = pl.ClosestParameter(E)
        if (not okF) or (not okE) or abs(uE - uF) < 1e-12:
            # 兜底：按线段中点
            H = F + (E - F) * 0.5
            log.append("H solve fallback: invalid plane parameters on EF.")
        else:
            u_target = -float(self.H_dist)
            sH = (u_target - float(uF)) / (float(uE) - float(uF))
            H = F + (E - F) * sH

        # 8) H -> G : 沿 -X，长度 GH_len
        G = H + (-x) * self.GH_len

        # 9) 过 G 沿 refPlane 的 -Y 方向，与线段 EF 相交得 J
        line_g = rg.Line(G, G + (-y) * 99999.0)
        line_ef = rg.Line(E, F)
        try:
            import Rhino
            tol_i = get_model_tolerance(0.01)
            rc, ta, tb = Rhino.Geometry.Intersect.Intersection.LineLine(line_g, line_ef, tol_i, False)
            if rc:
                J = line_g.PointAt(ta)
            else:
                # 兜底：投影到 EF
                t_closest = line_ef.ClosestParameter(G)
                J = line_ef.PointAt(t_closest)
                log.append("J intersection failed; used closest point on EF.")
        except Exception as e:
            t_closest = line_ef.ClosestParameter(G)
            J = line_ef.PointAt(t_closest)
            log.append("J solve exception; used closest point on EF: %s" % e)

        # 点字典
        self.pts = {"O": O, "A": A, "C": C, "B": B, "E": E, "F": F, "H": H, "G": G, "J": J}

        # 线/曲线字典
        self.crvs = {
            "OC": rg.Line(O, C),
            "OB": rg.Line(O, B),
            "OB_PlusZ": line_ob_p,
            "OB_MinusZ": line_ob_n,
            "EF": rg.Line(E, F),
            "Rectangle": rect,
            "SectionCrv": section_crv,
            "SectionCrv_PlusZ": sec_p,
            "SectionCrv_MinusZ": sec_n,
            "HG": rg.Line(H, G),
            "GJ": rg.Line(G, J),
        }

        # 输出平面 A：refPlane + 垂直于其 X/Y 轴的两个平面
        plA = pl
        self.planesA = {
            "RefPlane_O": plA,
            "PerpToX_O": plane_perp_to_xaxis(plA, origin=O),
            "PerpToY_O": plane_perp_to_yaxis(plA, origin=O),
        }

        # 输出平面 B：由 OF 与 OB 构建的参考平面 + 垂直于其 X/Y 轴的两个平面
        v_of = F - O
        v_ob = B - O
        plB = plane_from_two_vectors(O, v_of, v_ob)
        self.planesB = {
            "Plane_OF_OB_O": plB,
            "PerpToX_O": plane_perp_to_xaxis(plB, origin=O),
            "PerpToY_O": plane_perp_to_yaxis(plB, origin=O),
        }

        # GhPython 输出端不建议直接输出 dict；此处拆分为 Key/Value 两列并保持固定顺序
        pts_order = ["O", "A", "C", "B", "E", "F", "H", "G", "J"]
        crv_order = [
            "OC", "OB", "OB_PlusZ", "OB_MinusZ", "EF", "Rectangle",
            "SectionCrv", "SectionCrv_PlusZ", "SectionCrv_MinusZ",
            "HG", "GJ",
        ]
        plA_order = ["RefPlane_O", "PerpToX_O", "PerpToY_O"]
        plB_order = ["Plane_OF_OB_O", "PerpToX_O", "PerpToY_O"]

        PtsKeys, PtsValues = dict_to_kv(self.pts, pts_order)
        CrvsKeys, CrvsValues = dict_to_kv(self.crvs, crv_order)
        PlanesAKeys, PlanesAValues = dict_to_kv(self.planesA, plA_order)
        PlanesBKeys, PlanesBValues = dict_to_kv(self.planesB, plB_order)

        # 附加输出：截面曲线列表 + 放样 Brep + 实体 + O-B放样面 + 日志
        SectionCrvs = [section_crv, sec_p, sec_n]
        LoftBrep = loft_brep
        SolidBrep = solid
        OBLoftBrep = ob_loft_brep
        Log = log

        return (PtsKeys, PtsValues,
                CrvsKeys, CrvsValues,
                PlanesAKeys, PlanesAValues,
                PlanesBKeys, PlanesBValues,
                SectionCrvs, LoftBrep, SolidBrep, OBLoftBrep, Log)


if __name__ == "__main__":
    # ------------------------------------------------------------
    # GhPython 入口（可直接调用）
    # ------------------------------------------------------------
    def solve(base_point=None,
              RefPlaneMode=None,
              OA_len=None,
              AC_len=None,
              BD_len=None,
              OffsetY=None,
              H_dist=None,
              GH_len=None,
              SectionOffsetZ=None):
        b = AngSectionBuilder(
            base_point=base_point,
            ref_plane_mode=RefPlaneMode,
            OA_len=_coalesce(OA_len, 21.0),
            AC_len=_coalesce(AC_len, 52.4),
            BD_len=_coalesce(BD_len, 115.22),
            OffsetY=_coalesce(OffsetY, 15.0),
            H_dist=_coalesce(H_dist, 82.72),
            GH_len=_coalesce(GH_len, 6.0),
            SectionOffsetZ=_coalesce(SectionOffsetZ, 5.0),
        )
        return b.build()

    # ------------------------------------------------------------
    # GH 输出端赋值（把这段放在脚本最末尾即可）
    # ------------------------------------------------------------
    PtsKeys, PtsValues, CrvsKeys, CrvsValues, PlanesAKeys, PlanesAValues, PlanesBKeys, PlanesBValues, SectionCrvs, LoftBrep, SolidBrep, OBLoftBrep, Log = \
        solve(base_point, RefPlaneMode, OA_len, AC_len, BD_len, OffsetY, H_dist, GH_len, SectionOffsetZ)
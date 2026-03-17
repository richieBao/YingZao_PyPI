# -*- coding: utf-8 -*-
"""
BuildTimberBlockUniform_SkewAxis_M
================================
方材统一构造 + Skew（斜移）参考平面与控制点构造
"""

import Rhino.Geometry as rg

# ---------------------------------------------------------
# GH 运行时：强制 Skew_len 输入端为 List Access，避免 GH 对 Item 输入进行隐式迭代
# （隐式迭代会导致脚本被执行 N 次，从而 TimberBrep 出现 N 个 Closed Brep）
# ---------------------------------------------------------
try:
    import Grasshopper
    import Grasshopper.Kernel as ghk
    # ghenv 在 GhPython 环境中可用
    if "ghenv" in globals():
        _c = ghenv.Component
        if _c is not None:
            for _p in _c.Params.Input:
                try:
                    if _p.NickName == "Skew_len" or _p.Name == "Skew_len":
                        _p.Access = ghk.GH_ParamAccess.list
                except Exception:
                    pass
except Exception:
    pass


# ---------------------------------------------------------
# GH 运行时：主几何（TimberBrep）自动预览，其它输出自动关闭 Preview
# 说明：这会把除 TimberBrep 之外的输出参数的 IGH_PreviewObject.Hidden 设为 True
# 以避免 Rhino 视窗中出现多层叠加的预览干扰（特别是 Tree/多分支调试几何）。
# 不影响数据输出，只影响预览显示。
# ---------------------------------------------------------
try:
    import Grasshopper
    # ghenv 在 GhPython 环境中可用
    if "ghenv" in globals():
        _c = ghenv.Component
        if _c is not None:
            try:
                # TimberBrep 允许预览，其它输出默认关闭预览
                for _op in _c.Params.Output:
                    try:
                        _is_timber = (_op.NickName == "TimberBrep") or (_op.Name == "TimberBrep")
                        # IGH_PreviewObject.Hidden
                        if hasattr(_op, "Hidden"):
                            _op.Hidden = (False if _is_timber else True)
                    except Exception:
                        pass
            except Exception:
                pass
except Exception:
    pass


# ---------------------------------------------------------
# GH / Python 输入适配工具
# ---------------------------------------------------------
def _is_gh_tree(x):
    """粗略判断是否为 GH DataTree / IGH_Structure。"""
    if x is None:
        return False
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


def _iterable_but_not_geom(x):
    """用于判断是否应当把输入当作“多值列表”。"""
    if x is None:
        return False
    # 不把字符串、Rhino 几何、Transform 等当作可迭代展开
    if isinstance(x, (str, rg.Point3d, rg.Vector3d, rg.Plane, rg.Transform)):
        return False
    try:
        if isinstance(x, rg.GeometryBase):
            return False
    except Exception:
        pass
    try:
        iter(x)
        return True
    except Exception:
        return False


def _to_value_list(x):
    """把 GH Tree / list / tuple / 单值 统一转换为 Python list（扁平一层）。"""
    if x is None:
        return []
    if _is_gh_tree(x):
        out = []
        try:
            # GH: Branch(i) -> IList
            for i in range(int(x.BranchCount)):
                br = x.Branch(i)
                for j in range(int(br.Count)):
                    out.append(br[j])
        except Exception:
            # 兜底：尽力遍历
            try:
                for br in x.Branches:
                    for item in br:
                        out.append(item)
            except Exception:
                pass
        return out
    if _iterable_but_not_geom(x):
        try:
            return list(x)
        except Exception:
            return [x]
    return [x]


def _make_tree(branch_lists):
    """把 list[list[items]] 变成 GH DataTree；若不在 GH 环境则返回原结构。"""
    try:
        import Grasshopper
        from Grasshopper import DataTree
        from Grasshopper.Kernel.Data import GH_Path

        t = DataTree[object]()
        # 分支路径强制简化为最简：{0},{1},{2}...（避免出现 {0:0},{0:1} 等）
        # 并且严格按输入顺序（i 递增）写入，确保次序稳定且与 Skew_len 输入一一对应。
        for i, br in enumerate(branch_lists):
            p = GH_Path(int(i))
            if br is None:
                continue
            for item in br:
                t.Add(item, p)
        return t
    except Exception:
        # 非 GH 环境：返回嵌套 list 作为降级
        return branch_lists


def _first_item(x):
    """从 GH Tree / list / tuple 中取第一个元素；若为单值则原样返回。"""
    if x is None:
        return None
    if _is_gh_tree(x):
        try:
            if int(x.BranchCount) <= 0:
                return None
            br0 = x.Branch(0)
            if br0 is None or int(br0.Count) <= 0:
                return None
            return br0[0]
        except Exception:
            return None
    if isinstance(x, (list, tuple)):
        return x[0] if len(x) else None
    return x


def _ensure_single_closed_brep(x):
    """确保输出为单个 Closed Brep：若传入为多值容器，则取第一个 Brep。"""
    v = x
    # 如果是 Tree/list/tuple，则尝试取第一个元素
    if _is_gh_tree(v) or isinstance(v, (list, tuple)):
        v = _first_item(v)
    # 尽力保证是 Brep
    if isinstance(v, rg.Box):
        v = v.ToBrep()
    if isinstance(v, rg.Brep):
        # 如果不是闭合也不强制修补，这里只保证“单个 Brep 对象”
        return v
    return v


# ---------------------------------------------------------
# GH 默认参考平面（按 Grasshopper 约定的坐标轴定义）
# XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
# XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
# YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
# ---------------------------------------------------------
def gh_plane_XZ(origin):
    """Grasshopper 的 XZ Plane（按约定轴向）"""
    x = rg.Vector3d(1, 0, 0)
    y = rg.Vector3d(0, 0, 1)
    pl = rg.Plane(origin, x, y)
    return pl


# =========================================================
# 与 FT_TimberBoxFeatures 完全一致的特征提取类
# =========================================================
class FT_TimberBoxFeatures(object):

    def __init__(self):
        self._log = []

    def log(self, msg):
        self._log.append(str(msg))

    @property
    def log_lines(self):
        return self._log

    def _axis_tag(self, idx, sign):
        return ["+X", "-X", "+Y", "-Y", "+Z", "-Z"][(idx * 2) + (0 if sign >= 0 else 1)]

    def _get_corner0(self, brep):
        if brep.Vertices.Count == 0:
            raise ValueError("Brep 无顶点")
        return brep.Vertices[0].Location

    def _neighbor_edge_dirs(self, brep, P0, tol=1e-9):
        dirs = []
        for e in brep.Edges:
            pA = e.StartVertex.Location
            pB = e.EndVertex.Location
            if pA.DistanceTo(P0) < tol:
                dirs.append(pB - P0)
            elif pB.DistanceTo(P0) < tol:
                dirs.append(pA - P0)
        if len(dirs) != 3:
            raise ValueError("Corner0 未找到 3 条邻边")
        return dirs

    def _stable_axes(self, dirs):
        axes = [rg.Vector3d(d) for d in dirs]
        for a in axes:
            a.Unitize()
        return axes

    def extract(self, timber):
        self._log = []
        self.log("== TimberBox 特征提取 ==")

        if isinstance(timber, rg.Box):
            brep = timber.ToBrep()
            pts = list(timber.GetCorners())
        elif isinstance(timber, rg.Brep):
            brep = timber
            pts = [v.Location for v in brep.Vertices]
        else:
            raise TypeError("输入必须是 Box 或 Brep")

        P0 = self._get_corner0(brep)
        dirs = self._neighbor_edge_dirs(brep, P0)
        axes = self._stable_axes(dirs)

        axis_x, axis_y, axis_z = axes
        local_axes_plane = rg.Plane(P0, axis_x, axis_y)

        cx = sum(p.X for p in pts) / len(pts)
        cy = sum(p.Y for p in pts) / len(pts)
        cz = sum(p.Z for p in pts) / len(pts)
        center = rg.Point3d(cx, cy, cz)

        hx = hy = hz = 0
        for p in pts:
            v = p - center
            hx = max(hx, abs(rg.Vector3d.Multiply(v, axis_x)))
            hy = max(hy, abs(rg.Vector3d.Multiply(v, axis_y)))
            hz = max(hz, abs(rg.Vector3d.Multiply(v, axis_z)))

        center_axes = [
            rg.Line(center, center + axis_x * hx),
            rg.Line(center, center - axis_x * hx),
            rg.Line(center, center + axis_y * hy),
            rg.Line(center, center - axis_y * hy),
            rg.Line(center, center + axis_z * hz),
            rg.Line(center, center - axis_z * hz),
        ]

        EdgeList = [e.DuplicateCurve() for e in brep.Edges]
        EdgeMid = []
        for cr in EdgeList:
            t = cr.Domain.ParameterAt(0.5)
            EdgeMid.append(cr.PointAt(t))

        FaceList = []
        FacePlaneList = []
        FaceDirTags = []

        for face in brep.Faces:
            fb = face.DuplicateFace(True)
            amp = rg.AreaMassProperties.Compute(fb)
            fc = amp.Centroid if amp else fb.GetBoundingBox(True).Center

            udom = face.Domain(0)
            vdom = face.Domain(1)
            nf = face.NormalAt(
                (udom.T0 + udom.T1) / 2.0,
                (vdom.T0 + vdom.T1) / 2.0,
            )
            nf.Unitize()

            dots = [rg.Vector3d.Multiply(nf, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1

            FaceDirTags.append(self._axis_tag(idx, sign))

            rem = [0, 1, 2]
            rem.remove(idx)
            xax = rg.Vector3d(axes[rem[0]])
            yax = rg.Vector3d(axes[rem[1]])
            xax.Unitize()
            yax.Unitize()

            FacePlaneList.append(rg.Plane(fc, xax, yax))
            FaceList.append(fb)

        EdgeDirTags = []
        for cr in EdgeList:
            tan = cr.TangentAt(cr.Domain.Mid)
            tan.Unitize()
            dots = [rg.Vector3d.Multiply(tan, a) for a in axes]
            absd = [abs(d) for d in dots]
            idx = absd.index(max(absd))
            sign = 1 if dots[idx] >= 0 else -1
            EdgeDirTags.append(self._axis_tag(idx, sign))

        Corner0Planes = [
            rg.Plane(P0, axis_x, axis_y),
            rg.Plane(P0, axis_x, axis_z),
            rg.Plane(P0, axis_y, axis_z),
        ]

        return (
            FaceList,
            pts,
            EdgeList,
            center,
            center_axes,
            EdgeMid,
            FacePlaneList,
            Corner0Planes,
            local_axes_plane,
            axis_x,
            axis_y,
            axis_z,
            FaceDirTags,
            EdgeDirTags,
            dirs,
        )


# =========================================================
# 方案 A：对象化 Builder（Skew 版本）
# =========================================================
class BuildTimberBlockUniform_SkewAxis_M(object):

    def __init__(
        self,
        length_fen,
        width_fen,
        height_fen,
        base_point,
        reference_plane=None,
        Skew_len=20.0,
    ):
        self.length_fen = float(length_fen)
        self.width_fen = float(width_fen)
        self.height_fen = float(height_fen)

        # 允许 Skew_len 为单值 / list / GH Tree
        # 必须保持输入顺序稳定（GH Tree: 先分支序，再分支内序）
        _raw_vals = []
        if _is_gh_tree(Skew_len):
            try:
                # Branch(i) 顺序由 GH 保证可重复；我们按 i 递增提取
                for bi in range(int(Skew_len.BranchCount)):
                    br = Skew_len.Branch(bi)
                    for j in range(int(br.Count)):
                        _raw_vals.append(br[j])
            except Exception:
                # 兜底
                _raw_vals = _to_value_list(Skew_len)
        else:
            _raw_vals = _to_value_list(Skew_len)

        if len(_raw_vals) == 0:
            _raw_vals = [20.0]

        # 统一转 float（忽略无法转换的项）
        _sk_vals = []
        for v in _raw_vals:
            try:
                _sk_vals.append(float(v))
            except Exception:
                pass
        if len(_sk_vals) == 0:
            _sk_vals = [20.0]

        self.Skew_len_list = _sk_vals
        self.Skew_len = float(_sk_vals[0])
        self._is_multi_skew = len(_sk_vals) > 1

        if base_point is None:
            base_point = rg.Point3d(0, 0, 0)
        elif isinstance(base_point, rg.Point):
            base_point = base_point.Location
        self.base_point = base_point

        self.reference_plane = reference_plane
        self._solve()

    def _solve(self):
        try:
            # ---- 基准参考平面 ----
            if self.reference_plane is None:
                base_plane = gh_plane_XZ(self.base_point)
            else:
                base_plane = rg.Plane(self.reference_plane)
                base_plane.Origin = self.base_point

            # ---- Box ----
            box = rg.Box(
                base_plane,
                rg.Interval(0, self.length_fen),
                rg.Interval(0, self.height_fen),
                rg.Interval(0, self.width_fen),
            )
            timber_brep = box.ToBrep()

            # ---- 特征 ----
            ft = FT_TimberBoxFeatures()
            (
                faces,
                points,
                edges,
                center_pt,
                center_axes,
                edge_midpts,
                face_planes,
                corner0_planes,
                local_axes_plane,
                axis_x,
                axis_y,
                axis_z,
                face_tags,
                edge_tags,
                corner0_dirs,
            ) = ft.extract(timber_brep)

            # ---- Skew 构造（支持单值 / 多值） ----
            def _calc_skew(skew_len):
                _sk = float(skew_len)
                _Skew_A = self.base_point + base_plane.ZAxis * (self.width_fen * 0.5)
                _Skew_Point_B = _Skew_A + base_plane.XAxis * _sk
                _Skew_Point_C = _Skew_Point_B + base_plane.YAxis * self.height_fen

                _pl_B = rg.Plane(base_plane)
                _pl_B.Origin = _Skew_Point_B
                _pl_B_X = rg.Plane(_Skew_Point_B, _pl_B.XAxis, _pl_B.ZAxis)
                _pl_B_Y = rg.Plane(_Skew_Point_B, _pl_B.YAxis, _pl_B.ZAxis)
                _Skew_Planes = [_pl_B, _pl_B_X, _pl_B_Y]

                _x_dir = base_plane.XAxis
                _y_dir = base_plane.YAxis
                _z_dir = base_plane.ZAxis

                _P00 = base_plane.Origin
                _P01 = base_plane.Origin + _z_dir * self.width_fen
                _P11 = base_plane.Origin + _y_dir * self.height_fen + _z_dir * self.width_fen
                _P10 = base_plane.Origin + _y_dir * self.height_fen

                _G = _P00 + _x_dir * _sk
                _F = _P01 + _x_dir * _sk
                _E = _P11 + _x_dir * _sk
                _H = _P10 + _x_dir * _sk

                return _Skew_A, _Skew_Point_B, _Skew_Point_C, _Skew_Planes, [_G, _F, _E, _H]

            if not self._is_multi_skew:
                Skew_A, Skew_Point_B, Skew_Point_C, Skew_Planes, Skew_ExtraPoints_GF_EH = _calc_skew(self.Skew_len)

                # ---- 输出（单偏轴：保持原类型） ----
                self.TimberBrep = timber_brep
                self.FaceList = faces
                self.PointList = points
                self.EdgeList = edges
                self.CenterPoint = center_pt
                self.CenterAxisLines = center_axes
                self.EdgeMidPoints = edge_midpts
                self.FacePlaneList = face_planes
                self.Corner0Planes = corner0_planes
                self.LocalAxesPlane = local_axes_plane
                self.AxisX = axis_x
                self.AxisY = axis_y
                self.AxisZ = axis_z
                self.FaceDirTags = face_tags
                self.EdgeDirTags = edge_tags
                self.Corner0EdgeDirs = corner0_dirs
                self.Log = ft.log_lines

                self.Skew_A = Skew_A
                self.Skew_Point_B = Skew_Point_B
                self.Skew_Point_C = Skew_Point_C
                self.Skew_Planes = Skew_Planes
                self.Skew_ExtraPoints_GF_EH = Skew_ExtraPoints_GF_EH

            else:
                # ✅ 多 Skew_len 仅影响“新增加的 Skew_* 输出端”
                # 其余输出（方材长方体的几何与特征提取）应当保持只有一组，避免 GH 端出现
                # 重复分支/列表项，从而污染后续步骤的广播/树结构。
                # TimberBrep：即便多 Skew，也只保留一个 Closed Brep 对象
                self.TimberBrep = timber_brep
                self.FaceList = faces
                self.PointList = points
                self.EdgeList = edges
                self.CenterPoint = center_pt
                self.CenterAxisLines = center_axes
                self.EdgeMidPoints = edge_midpts
                self.FacePlaneList = face_planes
                self.Corner0Planes = corner0_planes
                self.LocalAxesPlane = local_axes_plane
                self.AxisX = axis_x
                self.AxisY = axis_y
                self.AxisZ = axis_z
                self.FaceDirTags = face_tags
                self.EdgeDirTags = edge_tags
                self.Corner0EdgeDirs = corner0_dirs
                self.Log = ft.log_lines

                # Skew 相关：单值 -> list；列表 -> Tree
                Skew_A_list = []
                Skew_B_list = []
                Skew_C_list = []
                Skew_Planes_branches = []
                Skew_ExtraPoints_branches = []

                for sk in self.Skew_len_list:
                    _a, _b, _c, _pls, _ex = _calc_skew(sk)
                    Skew_A_list.append(_a)
                    Skew_B_list.append(_b)
                    Skew_C_list.append(_c)
                    Skew_Planes_branches.append(_pls)
                    Skew_ExtraPoints_branches.append(_ex)

                self.Skew_A = Skew_A_list
                self.Skew_Point_B = Skew_B_list
                self.Skew_Point_C = Skew_C_list
                self.Skew_Planes = _make_tree(Skew_Planes_branches)
                self.Skew_ExtraPoints_GF_EH = _make_tree(Skew_ExtraPoints_branches)

        except Exception as e:
            self.TimberBrep = None
            self.Log = ["错误: {}".format(e)]

if __name__ == "__main__":
    # =========================================================
    # GhPython 主入口
    # =========================================================
    if __name__ == "__main__":

        if length_fen is None:
            length_fen = 32.0
        if width_fen is None:
            width_fen = 32.0
        if height_fen is None:
            height_fen = 20.0
        if Skew_len is None:
            Skew_len = 20.0

        if base_point is None:
            base_point = rg.Point3d(0, 0, 0)
        elif isinstance(base_point, rg.Point):
            base_point = base_point.Location

        if reference_plane is None:
            reference_plane = gh_plane_XZ(base_point)

        try:
            _obj = BuildTimberBlockUniform_SkewAxis_M(
                length_fen,
                width_fen,
                height_fen,
                base_point,
                reference_plane,
                Skew_len,
            )
            # TimberBrep：无论 Skew_len 是否为多值，输出端始终只给 1 个 Closed Brep
            _tb = _obj.TimberBrep
            try:
                # 若因为历史版本或外部封装导致返回 list/tree，则只取第一个非空对象
                if _tb is not None and (hasattr(_tb, "BranchCount") and hasattr(_tb, "Branch")):
                    if int(_tb.BranchCount) > 0:
                        br0 = _tb.Branch(0)
                        if br0 is not None and int(br0.Count) > 0:
                            _tb = br0[0]
                elif isinstance(_tb, (list, tuple)):
                    for _it in _tb:
                        if _it is not None:
                            _tb = _it
                            break
            except Exception:
                pass
            TimberBrep = _tb
            FaceList = _obj.FaceList
            PointList = _obj.PointList
            EdgeList = _obj.EdgeList
            CenterPoint = _obj.CenterPoint
            CenterAxisLines = _obj.CenterAxisLines
            EdgeMidPoints = _obj.EdgeMidPoints
            FacePlaneList = _obj.FacePlaneList
            Corner0Planes = _obj.Corner0Planes
            LocalAxesPlane = _obj.LocalAxesPlane
            AxisX = _obj.AxisX
            AxisY = _obj.AxisY
            AxisZ = _obj.AxisZ
            FaceDirTags = _obj.FaceDirTags
            EdgeDirTags = _obj.EdgeDirTags
            Corner0EdgeDirs = _obj.Corner0EdgeDirs
            Log = _obj.Log

            Skew_A = _obj.Skew_A
            Skew_Point_B = _obj.Skew_Point_B
            Skew_Point_C = _obj.Skew_Point_C
            Skew_Planes = _obj.Skew_Planes
            Skew_ExtraPoints_GF_EH = _obj.Skew_ExtraPoints_GF_EH

        except Exception as e:
            TimberBrep = None
            Log = ["主逻辑错误: {}".format(e)]
# -*- coding: utf-8 -*-
"""
ShuaTouSolver · Step 1（DBJsonReader） + Step 2（Timber_block_uniform） + Step 3（耍头工具+定位）
------------------------------------------------------------
将“耍頭（ShuaTou_4PU_INOUT_1ChaoJuantou）”的多组件流程，逐步整合为单一 GhPython 组件。
本文件为第 3 次增量：在 Step 1-3 基础上新增
  Step 4：欹䫜部分（QiAOTool、PlaneFromLists::2、PlaneFromLists::3、AlignToolToTimber::2）
  Step 5：散枓令栱切削准备（BlockCutter::1、PlaneFromLists::4、AlignToolToTimber::3）

输入端（固定三项）：
  DBPath    : str   数据库文件路径
  base_point: Point 木料定位点（若 None → 原点）
  Refresh   : bool  刷新开关（用于重读数据库等）

输出端（固定三项主输出）：
  CutTimbers  : list[Breps]  当前版本仍输出 [TimberBrep]（尚未进入切削步骤）
  FailTimbers : list[Breps]  当前版本为空
  Log         : list[str]    全局日志

并支持“开发模式输出”：
  在 GH Python 输出绑定区，将 solver 成员变量逐一赋给同名输出端（你可随时在 GH 中新增同名输出端查看）。

修复（2026.01.04）：
  - AlignToolToTimber_1__MovedGeo 输出出现 System.Collections.Generic.List`1[System.Object] 嵌套：
    对 AlignToolToTimber::1 的 MovedGeo 做递归拍平输出（支持多层嵌套 list/tuple）。
"""

from yingzao.ancientArchi import DBJsonReader, build_timber_block_uniform, FTPlaneFromLists, GeoAligner_xfm, \
    QiAoToolSolver, InputHelper, GHPlaneFactory
import Rhino.Geometry as rg
import Grasshopper.Kernel.Types as ght
import scriptcontext as sc
import math

# ==============================================================
# 通用工具函数
# ==============================================================

def _to_point3d(pt, default=None):
    """将 GH/DB 可能传入的点值统一为 Rhino.Geometry.Point3d。

    支持输入类型：
      - None → default（若 default 也为 None，则回退原点）
      - rg.Point3d / rg.Point
      - GH Goo（带 .Value，Value 为 Point3d/Point 或 [x,y,z]）
      - list/tuple(len>=3) → Point3d(x,y,z)

    注意：你在 Step7 中会用 _to_point3d(pt, default) 的两参形式，
    所以这里必须兼容两参调用，避免 TypeError 导致组件中断。
    """
    if default is None:
        default = rg.Point3d(0.0, 0.0, 0.0)

    if pt is None:
        return default

    # GH Goo / wrapper
    try:
        if hasattr(pt, "Value"):
            pt = pt.Value
    except:
        pass

    if isinstance(pt, rg.Point3d):
        return pt

    if isinstance(pt, rg.Point):
        return pt.Location

    if isinstance(pt, (list, tuple)) and len(pt) >= 3:
        try:
            return rg.Point3d(float(pt[0]), float(pt[1]), float(pt[2]))
        except:
            return default

    return default


def gh_plane(name="XZ", origin=None):
    """
    构造 GH 约定的基准平面：
      XY: X=(1,0,0), Y=(0,1,0), Z=(0,0,1)
      XZ: X=(1,0,0), Y=(0,0,1), Z=(0,-1,0)
      YZ: X=(0,1,0), Y=(0,0,1), Z=(1,0,0)
    Rhino Plane 用 origin + xaxis + yaxis 构造，Z 自动为 X×Y
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    else:
        origin = _to_point3d(origin)

    n = (name or "XZ").upper().strip()

    if n == "XY":
        x = rg.Vector3d(1.0, 0.0, 0.0)
        y = rg.Vector3d(0.0, 1.0, 0.0)
        return rg.Plane(origin, x, y)

    if n == "YZ":
        x = rg.Vector3d(0.0, 1.0, 0.0)
        y = rg.Vector3d(0.0, 0.0, 1.0)
        return rg.Plane(origin, x, y)

    # 默认 XZ
    x = rg.Vector3d(1.0, 0.0, 0.0)
    y = rg.Vector3d(0.0, 0.0, 1.0)
    return rg.Plane(origin, x, y)


def flatten_list(x):
    """深度拍平（兼容 Python list/tuple 与 .NET List[object] 等 IEnumerable）。

    目标：避免 GH 输出出现
        System.Collections.Generic.List`1[System.Object]
        System.Collections.Generic.List`1[System.Object]

    注意：
    - 会递归展开“看起来像集合”的对象；
    - 会尽量避开 RhinoCommon 的几何/基础值类型（Brep/Curve/Plane/Point3d/Transform 等）；
    - dict 按值展开（保持 key 不重要时），字符串不展开。
    """
    # 延迟导入，避免在非 Rhino/GH 环境报错
    try:
        import System
    except:
        System = None

    try:
        import Rhino.Geometry as rg
    except:
        rg = None

    def _is_atomic(obj):
        if obj is None:
            return True
        # 基础类型
        if isinstance(obj, (str, bytes, int, float, bool)):
            return True
        # dict 不是原子，但我们要特殊处理
        if isinstance(obj, dict):
            return False
        # RhinoCommon 常见原子类型（不应展开）
        if rg is not None:
            try:
                if isinstance(obj, (rg.GeometryBase, rg.Point3d, rg.Plane, rg.Transform, rg.Vector3d, rg.Line)):
                    return True
            except:
                pass
        return False

    def _is_iterable_collection(obj):
        if obj is None:
            return False
        if isinstance(obj, (list, tuple)):
            return True
        if isinstance(obj, dict):
            return True
        # .NET IEnumerable（常见：System.Collections.Generic.List[object]）
        if System is not None:
            try:
                if isinstance(obj, System.Collections.IEnumerable):
                    # 排除 string（也是 IEnumerable<char>）
                    if isinstance(obj, (str, bytes)):
                        return False
                    # 排除 RhinoCommon 原子
                    if _is_atomic(obj):
                        return False
                    return True
            except:
                pass
        # 兜底：Python 可迭代，但排除原子
        try:
            if hasattr(obj, "__iter__") and (not _is_atomic(obj)):
                return True
        except:
            pass
        return False

    def _flatten(obj, out):
        if obj is None:
            return
        if _is_atomic(obj):
            out.append(obj)
            return

        # dict：按 values 递归展开
        if isinstance(obj, dict):
            for v in obj.values():
                _flatten(v, out)
            return

        if _is_iterable_collection(obj):
            try:
                for it in obj:
                    _flatten(it, out)
                return
            except:
                # 迭代失败则当作原子
                out.append(obj)
                return

        # 默认原子
        out.append(obj)

    res = []
    _flatten(x, res)
    return res


def _as_list(v):
    """标量→[v]，None→[]，list/tuple→list(v)。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _to_datatree(branches):
    """将“分支列表”转换为 Grasshopper DataTree[object]。

    - branches 形如: [[a,b],[c,d]] 或更深嵌套（会深度展平到每个分支）
    - 解决 Panel 显示为 System.Collections.Generic.List`1[System.Object] 的问题
    """
    try:
        import Grasshopper as gh
        from Grasshopper import DataTree
        from Grasshopper.Kernel.Data import GH_Path
    except:
        # 非 GH 环境下回退为原样
        return branches

    tree = DataTree[object]()
    if branches is None:
        return tree

    # 若传入不是“分支列表”，包一层
    if not isinstance(branches, (list, tuple)):
        branches = [branches]

    for bi, br in enumerate(branches):
        path = GH_Path(bi)
        items = flatten_list(br)  # 深度展平分支内部
        if len(items) == 0:
            # 保留空分支
            continue
        for it in items:
            tree.Add(it, path)

    return tree


def _broadcast_to_len(seq, n):
    """
    GH 风格广播：当输入长度不足时，用最后一个值补齐。
    seq 为空时，返回 [None]*n
    """
    if n <= 0:
        return []
    if seq is None:
        return [None] * n
    seq = list(seq)
    if len(seq) == 0:
        return [None] * n
    if len(seq) >= n:
        return seq[:n]
    last = seq[-1]
    return seq + [last] * (n - len(seq))


def _broadcast_pair(a, b):
    """将 a,b 广播到同一长度（取 max(len(a),len(b))），长度不足用末值补齐。"""
    la = len(a)
    lb = len(b)
    n = max(la, lb, 1)
    return _broadcast_to_len(a, n), _broadcast_to_len(b, n), n


def _to_plane(p, default_plane_name="XZ", origin=None):
    """将 GH/Rhino/字符串等平面输入统一为 Rhino.Geometry.Plane。

    支持：
    - rg.Plane
    - ght.GH_Plane / 任何带 .Value 的 GH Goo（Value 为 rg.Plane）
    - 字符串: 'WorldXY'/'WorldXZ'/'WorldYZ'/'XY'/'XZ'/'YZ'
    - None: 返回默认平面（default_plane_name）
    """
    if origin is None:
        origin = rg.Point3d(0.0, 0.0, 0.0)
    else:
        origin = _to_point3d(origin)

    if p is None:
        return gh_plane(default_plane_name, origin)

    # 直接是 Rhino Plane
    if isinstance(p, rg.Plane):
        return p

    # GH_Plane 或 GH Goo：取 Value
    try:
        if hasattr(p, "Value"):
            v = p.Value
            if isinstance(v, rg.Plane):
                return v
    except:
        pass

    # 字符串平面名
    try:
        if isinstance(p, str):
            s = p.strip()
            s_up = s.upper()
            if s_up in ("WORLDXY", "XY"):
                return gh_plane("XY", origin)
            if s_up in ("WORLDYZ", "YZ"):
                return gh_plane("YZ", origin)
            if s_up in ("WORLDXZ", "XZ"):
                return gh_plane("XZ", origin)
            # 兜底
            return gh_plane(default_plane_name, origin)
    except:
        pass

    # 兜底
    return gh_plane(default_plane_name, origin)


def _is_tree(obj):
    """粗略判断输入是否为 GH Tree（DataTree / GH_Structure / GH_Structure<IGH_Goo> 等）。

    说明：
    - 在 GhPython 中，Tree 常表现为 Grasshopper.DataTree 或 GH_Structure；
    - 有些情况下表现为带 Branch/Paths 接口的对象；
    """
    if obj is None:
        return False

    # Grasshopper 类型判断（在 GH 环境中可用）
    try:
        import Grasshopper
        try:
            from Grasshopper import DataTree
        except:
            DataTree = None
        try:
            from Grasshopper.Kernel.Data import GH_Structure
        except:
            GH_Structure = None

        if DataTree is not None and isinstance(obj, DataTree):
            return True
        if GH_Structure is not None and isinstance(obj, GH_Structure):
            return True
    except:
        pass

    # 结构特征判断
    try:
        if hasattr(obj, "Paths") and hasattr(obj, "BranchCount") and hasattr(obj, "Branches"):
            return True
        if hasattr(obj, "Path") and hasattr(obj, "Branches"):
            return True
    except:
        pass

    return False


def get_input_or_db(AllDict, key, default=None):
    """
    输入端优先级：GH 输入端同名变量（若存在且非 None） > AllDict[key] > default
    """
    try:
        if key in globals() and globals()[key] is not None:
            return globals()[key]
    except:
        pass

    if isinstance(AllDict, dict) and key in AllDict and AllDict[key] is not None:
        return AllDict[key]

    return default


def tree_to_branches(x):
    """将 GH DataTree / 嵌套 list 统一为 branches(list[list]) 形式。
    - 若 x 为 DataTree：每个 Branch(path) → list
    - 若 x 为 list/tuple：
        * 若内部包含 list/tuple → 视作多分支
        * 否则每个元素视作一个分支（单元素）
    - 若 x 为标量：视作单分支
    """
    if x is None:
        return []
    # GH DataTree（尽量弱依赖：用反射判断）
    if hasattr(x, "BranchCount") and hasattr(x, "Branch"):
        branches = []
        try:
            # 优先用 Paths（Rhino 8/ GH2/ GH1 都可能存在）
            paths = list(getattr(x, "Paths")) if hasattr(x, "Paths") else None
        except Exception:
            paths = None

        for i in range(int(getattr(x, "BranchCount", 0))):
            try:
                br = list(x.Branch(i))
            except Exception:
                try:
                    if paths is not None and i < len(paths):
                        br = list(x.Branch(paths[i]))
                    else:
                        br = list(x.Branch(x.Path(i))) if hasattr(x, "Path") else []
                except Exception:
                    br = []
            branches.append(br)
        return branches

    # Python list/tuple
    if isinstance(x, (list, tuple)):
        # 嵌套 list → 直接作为分支；否则每个元素都是一个分支
        if any(isinstance(i, (list, tuple)) for i in x):
            return [list(i) if isinstance(i, (list, tuple)) else [i] for i in x]
        return [[i] for i in x]

    # 标量
    return [[x]]


def _param_to_branch_lists(param, branch_count):
    """把参数（标量/列表/树）规范为 list[branch][values]。
    规则：
    - 若 param 为 DataTree 或 (list of lists) 且分支数 == branch_count：按分支提供
    - 否则：视作一个“操作序列”，对所有分支共享
    """
    if branch_count <= 0:
        return []

    # DataTree
    if hasattr(param, "BranchCount") and hasattr(param, "Branch"):
        b = tree_to_branches(param)
        if len(b) == branch_count:
            return [list(x) for x in b]
        # 分支数不匹配时：降级为全局序列
        return [_as_list(flatten_list(b)) for _ in range(branch_count)]

    # list/tuple：若为 list-of-lists 且数量匹配，认为是 per-branch
    if isinstance(param, (list, tuple)) and any(isinstance(i, (list, tuple)) for i in param) and len(
            param) == branch_count:
        return [list(i) if isinstance(i, (list, tuple)) else [i] for i in param]

    # 全局序列
    seq = _as_list(param)
    return [seq for _ in range(branch_count)]


def _to_bool(v, default=False):
    """严格布尔归一化：True/False → 原值；1/0 → True/False；其它/None → default"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _apply_transform(geo, xfm):
    """对单个 RhinoCommon 几何应用 Transform，返回复制后的几何。
    支持 Brep / GeometryBase；失败则返回原对象（不抛异常）。"""
    if geo is None or xfm is None:
        return geo
    try:
        # 多数 GeometryBase 支持 Duplicate()
        if hasattr(geo, "Duplicate"):
            g2 = geo.Duplicate()
        elif hasattr(geo, "DuplicateBrep"):
            g2 = geo.DuplicateBrep()
        elif hasattr(geo, "DuplicateCurve"):
            g2 = geo.DuplicateCurve()
        else:
            g2 = geo  # 兜底：直接引用
        try:
            g2.Transform(xfm)
            return g2
        except Exception:
            # 若 g2 不支持 Transform，则尝试在原对象上 Transform（少数类型）
            try:
                geo.Transform(xfm)
                return geo
            except Exception:
                return geo
    except Exception:
        return geo


def _translate_in_plane_axes(geo, plane, dx=0.0, dy=0.0, dz=0.0):
    """沿给定 Plane 的局部 XYZ 轴平移（Phase2 推荐用法）。
    - dx/dy/dz 是“局部轴距离”，不是世界 XYZ。
    - 返回：(xfm, moved_geo)
    """
    if geo is None or plane is None:
        return None, geo
    try:
        v = rg.Vector3d(0.0, 0.0, 0.0)
        v += plane.XAxis * float(dx)
        v += plane.YAxis * float(dy)
        v += plane.ZAxis * float(dz)
        xfm = rg.Transform.Translation(v)
        moved = _apply_transform(geo, xfm)
        return xfm, moved
    except Exception:
        return None, geo


# ==============================================================
# Step 3 / ShuaTou：保持原组件几何算法（去除 ghenv 元信息，避免覆盖总组件）
# ==============================================================

def _default_point(p):
    return p if (p is not None) else rg.Point3d(0, 0, 0)


def _default_plane(pl):
    if pl is not None:
        return pl
    origin = rg.Point3d(0, 0, 0)
    xaxis = rg.Vector3d(1, 0, 0)
    yaxis = rg.Vector3d(0, 0, 1)
    return rg.Plane(origin, xaxis, yaxis)


def _default_float(x, v):
    try:
        return float(x)
    except:
        return v


class ShuaTouBuilder(object):
    """
    FT_ShuaTouTool (v1.8) - 原 ShuaTou GhPython 组件核心算法封装
    """

    @staticmethod
    def build(base_point, ref_plane,
              width_fen, height_fen,
              AH_fen, DF_fen, FE_fen, EC_fen,
              DG_fen, offset_fen):

        base_point = _default_point(base_point)
        ref_plane = _default_plane(ref_plane)
        width_fen = _default_float(width_fen, 16)
        height_fen = _default_float(height_fen, 15)
        AH_fen = _default_float(AH_fen, 5)
        DF_fen = _default_float(DF_fen, 6)
        FE_fen = _default_float(FE_fen, 5)
        EC_fen = _default_float(EC_fen, 5)
        DG_fen = _default_float(DG_fen, 2)
        offset_fen = _default_float(offset_fen, 5)

        tol = sc.doc.ModelAbsoluteTolerance

        log = []
        dbg_pts = []
        dbg_lines = []

        log.append("=== FT_ShuaTouTool v1.8 START ===")
        log.append("RefPlane: Origin={0}, X={1}, Y={2}, Z={3}".format(
            ref_plane.Origin, ref_plane.XAxis, ref_plane.YAxis, ref_plane.ZAxis))

        # 0. RefPlanes
        base_ref_plane = rg.Plane(base_point, ref_plane.XAxis, ref_plane.YAxis)
        xy_like_plane = rg.Plane(base_ref_plane)
        rot = rg.Transform.Rotation(math.radians(90.0), base_ref_plane.XAxis, base_point)
        xy_like_plane.Transform(rot)
        RefPlanes = [base_ref_plane, xy_like_plane]

        # 1. base rect A B C D（D=BasePoint）
        A, B, C, D = ShuaTouBuilder._build_base_rect(base_point, ref_plane, width_fen, height_fen)
        dbg_pts.extend([A, B, C, D])

        # 2. key points
        H, F, E, G, J, K, I, L, aux_lines = ShuaTouBuilder._build_key_points(
            A, B, C, D, AH_fen, DF_fen, FE_fen, DG_fen, ref_plane, log)
        dbg_pts.extend([H, F, E, G, J, K, I, L])
        dbg_lines.extend(aux_lines)

        # 3. Center section
        CenterSectionCrv = rg.Polyline([H, I, K, E]).ToNurbsCurve()
        center_face_poly = rg.Polyline([H, I, K, E, D, A, H]).ToNurbsCurve()
        cf = rg.Brep.CreatePlanarBreps(center_face_poly)
        CenterSectionFace = cf[0] if cf else None

        # 4. Side section
        SideSectionCrv = rg.Polyline([H, L, C]).ToNurbsCurve()
        side_face_poly = rg.Polyline([H, L, C, D, A, H]).ToNurbsCurve()
        sf = rg.Brep.CreatePlanarBreps(side_face_poly)
        SideSectionFace = sf[0] if sf else None

        # 5. offset
        normal = ref_plane.ZAxis
        n_vec = normal * offset_fen

        H_neg = H + (-n_vec);
        L_neg = L + (-n_vec);
        C_neg = C + (-n_vec);
        A_neg = A + (-n_vec);
        D_neg = D + (-n_vec)
        H_pos = H + (n_vec);
        L_pos = L + (n_vec);
        C_pos = C + (n_vec);
        A_pos = A + (n_vec);
        D_pos = D + (n_vec)

        OffsetSideFaces = []
        if SideSectionFace:
            T_neg = rg.Transform.Translation(-n_vec)
            T_pos = rg.Transform.Translation(n_vec)
            face_neg = SideSectionFace.DuplicateBrep();
            face_neg.Transform(T_neg)
            face_pos = SideSectionFace.DuplicateBrep();
            face_pos.Transform(T_pos)
            OffsetSideFaces = [face_neg, face_pos]

        OffsetSideCrvs = []
        if SideSectionCrv:
            T_neg_c = rg.Transform.Translation(-n_vec)
            T_pos_c = rg.Transform.Translation(n_vec)
            crv_neg = SideSectionCrv.DuplicateCurve();
            crv_neg.Transform(T_neg_c)
            crv_pos = SideSectionCrv.DuplicateCurve();
            crv_pos.Transform(T_pos_c)
            OffsetSideCrvs = [crv_neg, crv_pos]

        # 6. SideLoftFace
        SideLoftFace = None
        if len(OffsetSideCrvs) == 2:
            IKELine = rg.Polyline([I, K, E]).ToNurbsCurve()
            loft = rg.Brep.CreateFromLoft(
                [OffsetSideCrvs[0], IKELine, OffsetSideCrvs[1]],
                rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Straight, False
            )
            if loft:
                SideLoftFace = loft[0]
                log.append("SideLoftFace created (Straight Loft).")
            else:
                log.append("Loft failed - SideLoftFace is None.")
        else:
            log.append("OffsetSideCrvs != 2, cannot loft SideLoftFace.")

        # 7. TriFace
        TriFace = None
        tri_brep = rg.Brep.CreateFromCornerPoints(H_neg, I, H_pos, tol)
        if tri_brep:
            TriFace = tri_brep
            log.append("TriFace created (H_neg, I, H_pos).")
        else:
            log.append("TriFace creation failed (points may be collinear).")

        # 8. HADLoftFace
        HADLoftFace = None
        had_crv_neg = rg.Polyline([H_neg, A_neg, D_neg]).ToNurbsCurve()
        had_crv_pos = rg.Polyline([H_pos, A_pos, D_pos]).ToNurbsCurve()
        had_loft = rg.Brep.CreateFromLoft(
            [had_crv_neg, had_crv_pos],
            rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Straight, False
        )
        if had_loft:
            HADLoftFace = had_loft[0]
            log.append("H'AD'Loft created (Straight Loft).")
        else:
            log.append("H'AD'Loft creation failed.")

        # 9. BottomFace
        BottomFace = None
        bottom_tris = []
        t1 = rg.Brep.CreateFromCornerPoints(D_neg, C_neg, E, tol)
        if t1: bottom_tris.append(t1)
        t2 = rg.Brep.CreateFromCornerPoints(E, C_pos, D_pos, tol)
        if t2: bottom_tris.append(t2)
        t3 = rg.Brep.CreateFromCornerPoints(D_neg, E, D_pos, tol)
        if t3: bottom_tris.append(t3)

        if bottom_tris:
            joined_bottom = rg.Brep.JoinBreps(bottom_tris, tol)
            if joined_bottom and len(joined_bottom) > 0:
                BottomFace = joined_bottom[0]
                log.append("BottomFace created from {0} triangles.".format(len(bottom_tris)))
            else:
                log.append("JoinBreps failed for BottomFace.")
        else:
            log.append("No triangles created for BottomFace.")

        # 10. Join → ToolBrep
        ToolBrep = None
        join_list = []
        if SideLoftFace: join_list.append(SideLoftFace)
        if TriFace: join_list.append(TriFace)
        if HADLoftFace: join_list.append(HADLoftFace)
        if BottomFace: join_list.append(BottomFace)
        if OffsetSideFaces:
            join_list.extend([f for f in OffsetSideFaces if f is not None])

        if join_list:
            joined = rg.Brep.JoinBreps(join_list, tol)
            if joined and len(joined) > 0:
                ToolBrep = joined[0]
                log.append("ToolBrep joined from {0} breps.".format(len(join_list)))
                if not ToolBrep.IsSolid:
                    if ToolBrep.CapPlanarHoles(tol):
                        log.append("ToolBrep CapPlanarHoles succeeded, solid = {0}".format(ToolBrep.IsSolid))
                    else:
                        log.append("CapPlanarHoles did not fully close ToolBrep.")
        else:
            log.append("No breps to join for ToolBrep.")

        log.append("=== FT_ShuaTouTool v1.8 END ===")

        return (CenterSectionCrv, SideSectionCrv,
                CenterSectionFace, SideSectionFace,
                OffsetSideFaces, OffsetSideCrvs,
                SideLoftFace, ToolBrep,
                RefPlanes, dbg_pts, dbg_lines, log)

    @staticmethod
    def _build_base_rect(base_point, plane, width, height):
        X = plane.XAxis
        Y = plane.YAxis
        D = base_point
        C = D + X * width
        A = D + Y * height
        B = A + X * width
        return A, B, C, D

    @staticmethod
    def _build_key_points(A, B, C, D, AH, DF, FE, DG, plane, log):
        X = plane.XAxis
        Y = plane.YAxis

        H = A + X * AH
        F = D + X * DF
        E = F + X * FE
        G = D + Y * DG

        BC = rg.Line(B, C)
        GJ = rg.Line(G, G + X * 500)

        rc, t1, t2 = rg.Intersect.Intersection.LineLine(GJ, BC)
        J = GJ.PointAt(t1) if rc else C

        AF = rg.Line(A, F)
        rc2, t3, t4 = rg.Intersect.Intersection.LineLine(AF, GJ)
        K = AF.PointAt(t3) if rc2 else F

        I = ShuaTouBuilder._perpendicular_foot(H, A, F)

        HL = rg.Line(H, H + (F - A) * 200)
        rc3, t5, t6 = rg.Intersect.Intersection.LineLine(HL, GJ)
        L = HL.PointAt(t5) if rc3 else H

        aux = [AF.ToNurbsCurve(), GJ.ToNurbsCurve(), HL.ToNurbsCurve(), BC.ToNurbsCurve()]
        return H, F, E, G, J, K, I, L, aux

    @staticmethod
    def _perpendicular_foot(P, A, B):
        line = rg.Line(A, B)
        t = line.ClosestParameter(P)
        return line.PointAt(t)


# ==============================================================
# 主 Solver 类 —— ShuaTouSolver（当前 Step 1-3）
# ==============================================================

class ShuaTou_4PU_INOUT_1ChaoJuantouSolver(object):

    def __init__(self, DBPath, base_point, Refresh, ghenv):
        self.DBPath = DBPath
        self.base_point = base_point
        self.Refresh = Refresh
        self.ghenv = ghenv

        # Step 1
        self.Value = None
        self.All = None
        self.AllDict = {}
        self.DBLog = []

        # Global log
        self.Log = []

        # Step 2
        self.TimberBrep = None
        self.FaceList = []
        self.PointList = []
        self.EdgeList = []
        self.CenterPoint = None
        self.CenterAxisLines = []
        self.EdgeMidPoints = []
        self.FacePlaneList = []
        self.Corner0Planes = []
        self.LocalAxesPlane = None
        self.AxisX = None
        self.AxisY = None
        self.AxisZ = None
        self.FaceDirTags = []
        self.EdgeDirTags = []
        self.Corner0EdgeDirs = []
        self.TimberLog = []

        # Step 3 / ShuaTou outputs
        self.ShuaTou__CenterSectionCrv = None
        self.ShuaTou__SideSectionCrv = None
        self.ShuaTou__CenterSectionFace = None
        self.ShuaTou__SideSectionFace = None
        self.ShuaTou__OffsetSideFaces = []
        self.ShuaTou__OffsetSideCrvs = []
        self.ShuaTou__SideLoftFace = None
        self.ShuaTou__ToolBrep = None
        self.ShuaTou__RefPlanes = []
        self.ShuaTou__DebugPoints = []
        self.ShuaTou__DebugLines = []
        self.ShuaTou__Log = []

        # Step 3 / PlaneFromLists::1
        self.PlaneFromLists_1__BasePlane = None
        self.PlaneFromLists_1__OriginPoint = None
        self.PlaneFromLists_1__ResultPlane = None
        self.PlaneFromLists_1__Log = []

        # Step 3 / AlignToolToTimber::1
        self.AlignToolToTimber_1__SourceOut = None
        self.AlignToolToTimber_1__TargetOut = None
        self.AlignToolToTimber_1__TransformOut = None
        self.AlignToolToTimber_1__MovedGeo = None

        # ------------------------------------------------------
        # Step 4 / QiAoTool outputs（欹䫜）
        # ------------------------------------------------------
        self.QiAOTool__CutTimbers = []
        self.QiAOTool__FailTimbers = []
        self.QiAOTool__Log = []
        # developer outputs from QiAoToolSolver（按需输出端可查看）
        self.QiAOTool__TimberBrep = None
        self.QiAOTool__ToolBrep = None
        self.QiAOTool__AlignedTool = None
        self.QiAOTool__FaceList = []
        self.QiAOTool__PointList = []
        self.QiAOTool__EdgeList = []
        self.QiAOTool__CenterPoint = None
        self.QiAOTool__CenterAxisLines = []
        self.QiAOTool__EdgeMidPoints = []
        self.QiAOTool__FacePlaneList = []
        self.QiAOTool__Corner0Planes = []
        self.QiAOTool__LocalAxesPlane = None
        self.QiAOTool__AxisX = None
        self.QiAOTool__AxisY = None
        self.QiAOTool__AxisZ = None
        self.QiAOTool__FaceDirTags = []
        self.QiAOTool__EdgeDirTags = []
        self.QiAOTool__Corner0EdgeDirs = []

        # Step 4 / PlaneFromLists::2（基于 Timber_block_uniform）
        self.PlaneFromLists_2__BasePlane = None
        self.PlaneFromLists_2__OriginPoint = None
        self.PlaneFromLists_2__ResultPlane = None
        self.PlaneFromLists_2__Log = []

        # Step 4 / PlaneFromLists::3（基于 QiAOTool）
        self.PlaneFromLists_3__BasePlane = None
        self.PlaneFromLists_3__OriginPoint = None
        self.PlaneFromLists_3__ResultPlane = None
        self.PlaneFromLists_3__Log = []

        # Step 4 / AlignToolToTimber::2
        self.AlignToolToTimber_2__SourceOut = None
        self.AlignToolToTimber_2__TargetOut = None
        self.AlignToolToTimber_2__TransformOut = None
        self.AlignToolToTimber_2__MovedGeo = None

        # ------------------------------------------------------
        # Step 5 / BlockCutter::1（散枓令栱切削准备：块刀具）
        # ------------------------------------------------------
        self.BlockCutter_1__TimberBrep = None
        self.BlockCutter_1__FaceList = []
        self.BlockCutter_1__PointList = []
        self.BlockCutter_1__EdgeList = []
        self.BlockCutter_1__CenterPoint = None
        self.BlockCutter_1__CenterAxisLines = []
        self.BlockCutter_1__EdgeMidPoints = []
        self.BlockCutter_1__FacePlaneList = []
        self.BlockCutter_1__Corner0Planes = []
        self.BlockCutter_1__LocalAxesPlane = None
        self.BlockCutter_1__AxisX = None
        self.BlockCutter_1__AxisY = None
        self.BlockCutter_1__AxisZ = None
        self.BlockCutter_1__FaceDirTags = []
        self.BlockCutter_1__EdgeDirTags = []
        self.BlockCutter_1__Corner0EdgeDirs = []
        self.BlockCutter_1__Log = []

        # Step 5 / PlaneFromLists::4（来自 Timber_block_uniform）
        self.PlaneFromLists_4__BasePlane = None
        self.PlaneFromLists_4__OriginPoint = None
        self.PlaneFromLists_4__ResultPlane = None
        self.PlaneFromLists_4__Log = []

        # Step 5 / AlignToolToTimber::3（对位 BlockCutter::1 到 Timber）
        self.AlignToolToTimber_3__SourceOut = None
        self.AlignToolToTimber_3__TargetOut = None
        self.AlignToolToTimber_3__TransformOut = None
        self.AlignToolToTimber_3__MovedGeo_Tree = None

        # --- 开发模式输出：Step 5 / BlockCutter::2 ---
        self.AlignToolToTimber_3__MovedGeo = None

        # Step 5（单令栱切削）:: BlockCutter::2 + AlignToolToTimber::4
        self.BlockCutter_2__TimberBrep = None
        self.BlockCutter_2__FacePlaneList = []
        self.BlockCutter_2__EdgeMidPoints = []
        self.BlockCutter_2__Corner0Planes = []
        self.BlockCutter_2__Log = []

        self.AlignToolToTimber_4__SourceOut = None
        self.AlignToolToTimber_4__TargetOut = None
        self.AlignToolToTimber_4__TransformOut = None
        self.AlignToolToTimber_4__MovedGeo = None

        # ------------------------------------------------------
        # Step 6（泥道栱切削准备）:: BlockCutter::3 + AlignToolToTimber::5
        # ------------------------------------------------------
        self.BlockCutter_3__TimberBrep = None
        self.BlockCutter_3__FaceList = []
        self.BlockCutter_3__PointList = []
        self.BlockCutter_3__EdgeList = []
        self.BlockCutter_3__CenterPoint = None
        self.BlockCutter_3__CenterAxisLines = []
        self.BlockCutter_3__EdgeMidPoints = []
        self.BlockCutter_3__FacePlaneList = []
        self.BlockCutter_3__Corner0Planes = []
        self.BlockCutter_3__LocalAxesPlane = None
        self.BlockCutter_3__AxisX = None
        self.BlockCutter_3__AxisY = None
        self.BlockCutter_3__AxisZ = None
        self.BlockCutter_3__FaceDirTags = []
        self.BlockCutter_3__EdgeDirTags = []
        self.BlockCutter_3__Corner0EdgeDirs = []
        self.BlockCutter_3__Log = []

        self.AlignToolToTimber_5__SourceOut = None
        self.AlignToolToTimber_5__TargetOut = None
        self.AlignToolToTimber_5__TransformOut = None
        self.AlignToolToTimber_5__MovedGeo = None

        # ------------------------------------------------------
        # Step 7（壁内慢栱和闇栔切削准备）:: BlockCutter::4 + AlignToolToTimber::6
        # ------------------------------------------------------
        self.BlockCutter_4__TimberBrep = None
        self.BlockCutter_4__FaceList = []
        self.BlockCutter_4__PointList = []
        self.BlockCutter_4__EdgeList = []
        self.BlockCutter_4__CenterPoint = None
        self.BlockCutter_4__CenterAxisLines = []
        self.BlockCutter_4__EdgeMidPoints = []
        self.BlockCutter_4__FacePlaneList = []
        self.BlockCutter_4__Corner0Planes = []
        self.BlockCutter_4__LocalAxesPlane = None
        self.BlockCutter_4__AxisX = None
        self.BlockCutter_4__AxisY = None
        self.BlockCutter_4__AxisZ = None
        self.BlockCutter_4__FaceDirTags = []
        self.BlockCutter_4__EdgeDirTags = []
        self.BlockCutter_4__Corner0EdgeDirs = []
        self.BlockCutter_4__Log = []

        self.AlignToolToTimber_6__SourceOut = None
        self.AlignToolToTimber_6__TargetOut = None
        self.AlignToolToTimber_6__TransformOut = None
        self.AlignToolToTimber_6__MovedGeo = None

        self.AlignToolToTimber_6__MovedGeoTree = []  # [[geo_branch0_op0, op1], [geo_branch1_op0, op1], ...]

        # final outputs
        self.CutTimbers = []
        self.FailTimbers = []

    # ------------------------------------------------------
    # Step 1：读取数据库（DBJsonReader）
    # ------------------------------------------------------
    def step1_read_db(self):
        try:
            reader = DBJsonReader(
                db_path=self.DBPath,
                table="DG_Dou",
                key_field="type_code",
                key_value="ShuaTou_4PU_INOUT_1ChaoJuantou",
                field="params_json",
                json_path=None,
                export_all=True,
                ghenv=self.ghenv
            )
            self.Value, self.All, self.DBLog = reader.run()

            d = {}
            if isinstance(self.All, (list, tuple)):
                for kv in self.All:
                    try:
                        k, v = kv
                        d[str(k)] = v
                    except:
                        pass
            self.AllDict = d

            self.Log.append("[DB] 读取完成：All={} 项".format(len(self.All) if self.All else 0))
            if self.DBLog:
                for l in self.DBLog:
                    self.Log.append("[DB] " + str(l))

        except Exception as e:
            self.Value = None
            self.All = None
            self.AllDict = {}
            self.DBLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step1_read_db 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 2：构建原始木料（Timber_block_uniform）
    # ------------------------------------------------------
    def step2_timber(self):
        length_fen = get_input_or_db(self.AllDict, "Timber_block_uniform__length_fen", 32.0)
        width_fen = get_input_or_db(self.AllDict, "Timber_block_uniform__width_fen", 32.0)
        height_fen = get_input_or_db(self.AllDict, "Timber_block_uniform__height_fen", 20.0)

        bp = _to_point3d(self.base_point)

        ref_plane_in = get_input_or_db(self.AllDict, "Timber_block_uniform__reference_plane", "XZ")
        if isinstance(ref_plane_in, rg.Plane):
            ref_plane = ref_plane_in
        elif isinstance(ref_plane_in, str):
            ref_plane = gh_plane(ref_plane_in, origin=rg.Point3d(0, 0, 0))
        else:
            ref_plane = gh_plane("XZ", origin=rg.Point3d(0, 0, 0))

        try:
            (
                timber_brep,
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
                log_lines,
            ) = build_timber_block_uniform(
                float(length_fen),
                float(width_fen),
                float(height_fen),
                bp,
                ref_plane,
            )

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
            self.TimberLog = log_lines if log_lines else []

            self.Log.append("[TIMBER] 构建完成：TimberBrep={}".format("OK" if self.TimberBrep else "None"))
            for l in self.TimberLog:
                self.Log.append("[TIMBER] " + str(l))

        except Exception as e:
            self.TimberBrep = None
            self.FaceList = []
            self.PointList = []
            self.EdgeList = []
            self.CenterPoint = None
            self.CenterAxisLines = []
            self.EdgeMidPoints = []
            self.FacePlaneList = []
            self.Corner0Planes = []
            self.LocalAxesPlane = None
            self.AxisX = None
            self.AxisY = None
            self.AxisZ = None
            self.FaceDirTags = []
            self.EdgeDirTags = []
            self.Corner0EdgeDirs = []
            self.TimberLog = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step2_timber 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3.1：构建耍头刀具（ShuaTou）
    # ------------------------------------------------------
    def step3_1_shuatou_tool(self):
        BasePoint = _to_point3d(self.base_point)

        RefPlane_in = get_input_or_db(self.AllDict, "ShuaTou__RefPlane", None)
        if isinstance(RefPlane_in, rg.Plane):
            RefPlane = RefPlane_in
        elif isinstance(RefPlane_in, str):
            RefPlane = gh_plane(RefPlane_in, origin=rg.Point3d(0, 0, 0))
        else:
            RefPlane = gh_plane("XZ", origin=rg.Point3d(0, 0, 0))

        WidthFen = get_input_or_db(self.AllDict, "ShuaTou__WidthFen", None)
        HeightFen = get_input_or_db(self.AllDict, "ShuaTou__HeightFen", None)
        AH_Fen = get_input_or_db(self.AllDict, "ShuaTou__AH_Fen", None)
        DF_Fen = get_input_or_db(self.AllDict, "ShuaTou__DF_Fen", None)
        FE_Fen = get_input_or_db(self.AllDict, "ShuaTou__FE_Fen", None)
        EC_Fen = get_input_or_db(self.AllDict, "ShuaTou__EC_Fen", None)
        DG_Fen = get_input_or_db(self.AllDict, "ShuaTou__DG_Fen", None)
        OffsetFen = get_input_or_db(self.AllDict, "ShuaTou__OffsetFen", None)

        try:
            (CenterSectionCrv,
             SideSectionCrv,
             CenterSectionFace,
             SideSectionFace,
             OffsetSideFaces,
             OffsetSideCrvs,
             SideLoftFace,
             ToolBrep,
             RefPlanes,
             DebugPoints,
             DebugLines,
             LogLines) = ShuaTouBuilder.build(
                BasePoint,
                RefPlane,
                WidthFen,
                HeightFen,
                AH_Fen,
                DF_Fen,
                FE_Fen,
                EC_Fen,
                DG_Fen,
                OffsetFen
            )

            self.ShuaTou__CenterSectionCrv = CenterSectionCrv
            self.ShuaTou__SideSectionCrv = SideSectionCrv
            self.ShuaTou__CenterSectionFace = CenterSectionFace
            self.ShuaTou__SideSectionFace = SideSectionFace
            self.ShuaTou__OffsetSideFaces = OffsetSideFaces
            self.ShuaTou__OffsetSideCrvs = OffsetSideCrvs
            self.ShuaTou__SideLoftFace = SideLoftFace
            self.ShuaTou__ToolBrep = ToolBrep
            self.ShuaTou__RefPlanes = RefPlanes
            self.ShuaTou__DebugPoints = DebugPoints
            self.ShuaTou__DebugLines = DebugLines
            self.ShuaTou__Log = LogLines if LogLines else []

            self.Log.append("[ShuaTou] ToolBrep={}".format("OK" if ToolBrep else "None"))
            for l in self.ShuaTou__Log:
                self.Log.append("[ShuaTou] " + str(l))

        except Exception as e:
            self.ShuaTou__ToolBrep = None
            self.ShuaTou__RefPlanes = []
            self.ShuaTou__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step3_1_shuatou_tool 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3.2：PlaneFromLists::1
    # ------------------------------------------------------
    def step3_2_plane_from_lists(self):
        OriginPoints = self.EdgeMidPoints
        BasePlanes = self.Corner0Planes

        IndexOrigin = get_input_or_db(self.AllDict, "PlaneFromLists_1__IndexOrigin", 0)
        IndexPlane = get_input_or_db(self.AllDict, "PlaneFromLists_1__IndexPlane", 0)
        Wrap = get_input_or_db(self.AllDict, "PlaneFromLists_1__Wrap", True)

        try:
            idx_o = _as_list(IndexOrigin)
            idx_p = _as_list(IndexPlane)
            idx_o, idx_p, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_planes_out = []
            origin_pts_out = []
            result_planes_out = []
            logs = []

            for i in range(n):
                BasePlane_i, OriginPoint_i, ResultPlane_i, Log_i = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o[i],
                    idx_p[i]
                )
                base_planes_out.append(BasePlane_i)
                origin_pts_out.append(OriginPoint_i)
                result_planes_out.append(ResultPlane_i)
                if Log_i:
                    logs.extend(flatten_list(Log_i))

            self.PlaneFromLists_1__BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PlaneFromLists_1__OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PlaneFromLists_1__ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PlaneFromLists_1__Log = logs

            self.Log.append("[PlaneFromLists::1] ResultPlane count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_1__BasePlane = None
            self.PlaneFromLists_1__OriginPoint = None
            self.PlaneFromLists_1__ResultPlane = None
            self.PlaneFromLists_1__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step3_2_plane_from_lists 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 3.3：AlignToolToTimber::1（MovedGeo 递归拍平）
    # ------------------------------------------------------
    def step3_3_align_tool_to_timber(self):
        Geo = self.ShuaTou__ToolBrep

        sp_idx = get_input_or_db(self.AllDict, "AlignToolToTimber_1__SourcePlane", 0)
        refplanes = self.ShuaTou__RefPlanes if self.ShuaTou__RefPlanes else []
        try:
            if isinstance(sp_idx, (list, tuple)):
                sp_idx0 = sp_idx[0] if len(sp_idx) else 0
            else:
                sp_idx0 = sp_idx
            sp_idx0 = int(sp_idx0)
        except:
            sp_idx0 = 0

        SourcePlane = None
        if isinstance(refplanes, (list, tuple)) and len(refplanes) > 0:
            SourcePlane = refplanes[sp_idx0] if (0 <= sp_idx0 < len(refplanes)) else refplanes[0]

        TargetPlane = self.PlaneFromLists_1__ResultPlane

        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_1__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_1__FlipX", False)
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_1__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_1__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_1__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_1__MoveY", 0.0)
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_1__MoveZ", 0.0)

        try:
            tp_list = [TargetPlane] if isinstance(TargetPlane, rg.Plane) else _as_list(TargetPlane)

            rd_list = _as_list(RotateDeg)
            fx_list = [_to_bool(v, False) for v in _as_list(FlipX)]
            fy_list = [_to_bool(v, False) for v in _as_list(FlipY)]
            fz_list = [_to_bool(v, False) for v in _as_list(FlipZ)]
            mx_list = _as_list(MoveX)
            my_list = _as_list(MoveY)
            mz_list = _as_list(MoveZ)

            # 若 Flip 列表为空（None/未配置），按默认 False 处理
            if len(fx_list) == 0: fx_list = [False]
            if len(fy_list) == 0: fy_list = [False]
            if len(fz_list) == 0: fz_list = [False]

            n = max(len(tp_list), len(rd_list), len(fx_list), len(fy_list), len(fz_list),
                    len(mx_list), len(my_list), len(mz_list), 1)

            tp_list = _broadcast_to_len(tp_list, n)
            rd_list = _broadcast_to_len(rd_list, n)
            fx_list = _broadcast_to_len(fx_list, n)
            fy_list = _broadcast_to_len(fy_list, n)
            fz_list = _broadcast_to_len(fz_list, n)
            mx_list = _broadcast_to_len(mx_list, n)
            my_list = _broadcast_to_len(my_list, n)
            mz_list = _broadcast_to_len(mz_list, n)

            sp_list = _broadcast_to_len([SourcePlane], n)

            source_out = []
            target_out = []
            xfm_out = []
            moved_geo = []

            for i in range(n):
                so, to, xfm, mg = GeoAligner_xfm.align(
                    Geo,
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=rd_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                source_out.append(so)
                target_out.append(to)
                xfm_out.append(xfm)
                moved_geo.append(mg)

            xfm_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xfm_out]

            # ===== 关键修复：MovedGeo 做递归拍平（多层嵌套 list/tuple）=====
            moved_geo_flat = flatten_list(moved_geo)

            self.AlignToolToTimber_1__SourceOut = source_out[0] if n == 1 else source_out
            self.AlignToolToTimber_1__TargetOut = target_out[0] if n == 1 else target_out
            self.AlignToolToTimber_1__TransformOut = xfm_wrapped[0] if n == 1 else xfm_wrapped

            # 输出为“平坦列表”（便于直接作为 Tools 列表使用）
            self.AlignToolToTimber_1__MovedGeo = moved_geo_flat

            self.Log.append(
                "[AlignToolToTimber::1] MovedGeo raw_count={} -> flat_count={}".format(n, len(moved_geo_flat)))

        except Exception as e:
            self.AlignToolToTimber_1__SourceOut = None
            self.AlignToolToTimber_1__TargetOut = None
            self.AlignToolToTimber_1__TransformOut = None
            self.AlignToolToTimber_1__MovedGeo = None
            self.Log.append("[ERROR] Step3_3_align_tool_to_timber 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4.1：QiAOTool（欹䫜刀）- 参考独立 QiAOTool 组件写法
    # ------------------------------------------------------
    def step4_1_qiao_tool(self):
        try:
            bp = _to_point3d(self.base_point)

            def _to_float(x, default):
                try:
                    if x is None:
                        return float(default)
                    return float(x)
                except:
                    return float(default)

            # --- 参数读取（DB 优先；如未来需要 GH 输入端扩展，同名变量会覆盖 DB） ---
            _length_fen = get_input_or_db(self.AllDict, "QiAOTool__length_fen", 41.0)
            _width_fen = get_input_or_db(self.AllDict, "QiAOTool__width_fen", 16.0)
            _height_fen = get_input_or_db(self.AllDict, "QiAOTool__height_fen", 10.0)

            _qi_height = get_input_or_db(self.AllDict, "QiAOTool__qi_height", 4.0)
            _sha_width = get_input_or_db(self.AllDict, "QiAOTool__sha_width", 2.0)
            _qi_offset_fen = get_input_or_db(self.AllDict, "QiAOTool__qi_offset_fen", 0.5)
            _extrude_length = get_input_or_db(self.AllDict, "QiAOTool__extrude_length", 28.0)
            _extrude_positive = get_input_or_db(self.AllDict, "QiAOTool__extrude_positive", False)

            # 可选：参考平面模式（若 DB 未给，按独立组件默认 XZ）
            _timber_ref_plane_mode = get_input_or_db(self.AllDict, "QiAOTool__timber_ref_plane_mode", "XZ")
            _qi_ref_plane_mode = get_input_or_db(self.AllDict, "QiAOTool__qi_ref_plane_mode", "XZ")

            params = {
                # timber
                "length_fen": _to_float(_length_fen, 41.0),
                "width_fen": _to_float(_width_fen, 16.0),
                "height_fen": _to_float(_height_fen, 10.0),
                "base_point": bp,
                "timber_ref_plane": GHPlaneFactory.make(
                    _timber_ref_plane_mode if _timber_ref_plane_mode is not None else "XZ",
                    origin=bp
                ),

                # qi ao
                "qi_height": _to_float(_qi_height, 4.0),
                "sha_width": _to_float(_sha_width, 2.0),
                "qi_offset_fen": _to_float(_qi_offset_fen, 0.5),
                "extrude_length": _to_float(_extrude_length, 28.0),
                "extrude_positive": InputHelper.to_bool(
                    _extrude_positive if _extrude_positive is not None else False,
                    default=False
                ),
                "qi_ref_plane": GHPlaneFactory.make(
                    _qi_ref_plane_mode if _qi_ref_plane_mode is not None else "XZ",
                    origin=bp
                ),
            }

            solver = QiAoToolSolver(ghenv=self.ghenv)
            solver.run(params)

            self.QiAOTool__CutTimbers = flatten_list(solver.CutTimbers) if solver.CutTimbers else []
            self.QiAOTool__FailTimbers = flatten_list(solver.FailTimbers) if solver.FailTimbers else []
            self.QiAOTool__Log = solver.Log if hasattr(solver, "Log") else []

            # developer outputs
            self.QiAOTool__TimberBrep = getattr(solver, "TimberBrep", None)
            self.QiAOTool__ToolBrep = getattr(solver, "ToolBrep", None)
            self.QiAOTool__AlignedTool = getattr(solver, "AlignedTool", None)

            self.QiAOTool__FaceList = getattr(solver, "FaceList", []) or []
            self.QiAOTool__PointList = getattr(solver, "PointList", []) or []
            self.QiAOTool__EdgeList = getattr(solver, "EdgeList", []) or []
            self.QiAOTool__CenterPoint = getattr(solver, "CenterPoint", None)
            self.QiAOTool__CenterAxisLines = getattr(solver, "CenterAxisLines", []) or []
            self.QiAOTool__EdgeMidPoints = getattr(solver, "EdgeMidPoints", []) or []
            self.QiAOTool__FacePlaneList = getattr(solver, "FacePlaneList", []) or []
            self.QiAOTool__Corner0Planes = getattr(solver, "Corner0Planes", []) or []
            self.QiAOTool__LocalAxesPlane = getattr(solver, "LocalAxesPlane", None)
            self.QiAOTool__AxisX = getattr(solver, "AxisX", None)
            self.QiAOTool__AxisY = getattr(solver, "AxisY", None)
            self.QiAOTool__AxisZ = getattr(solver, "AxisZ", None)
            self.QiAOTool__FaceDirTags = getattr(solver, "FaceDirTags", []) or []
            self.QiAOTool__EdgeDirTags = getattr(solver, "EdgeDirTags", []) or []
            self.QiAOTool__Corner0EdgeDirs = getattr(solver, "Corner0EdgeDirs", []) or []

            self.Log.append("[QiAOTool] CutTimbers={} FailTimbers={}".format(len(self.QiAOTool__CutTimbers),
                                                                             len(self.QiAOTool__FailTimbers)))
            if self.QiAOTool__Log:
                for l in self.QiAOTool__Log:
                    self.Log.append("[QiAOTool] " + str(l))

        except Exception as e:
            self.QiAOTool__CutTimbers = []
            self.QiAOTool__FailTimbers = []
            self.QiAOTool__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step4_1_qiao_tool 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4.2：PlaneFromLists::2（来自 Timber_block_uniform）
    # ------------------------------------------------------
    def step4_2_plane_from_lists_2(self):
        OriginPoints = self.EdgeMidPoints
        BasePlanes = self.Corner0Planes

        IndexOrigin = get_input_or_db(self.AllDict, "PlaneFromLists_2__IndexOrigin", 0)
        IndexPlane = get_input_or_db(self.AllDict, "PlaneFromLists_2__IndexPlane", 0)
        Wrap = get_input_or_db(self.AllDict, "PlaneFromLists_2__Wrap", True)

        try:
            idx_o = _as_list(IndexOrigin)
            idx_p = _as_list(IndexPlane)
            idx_o, idx_p, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_planes_out = []
            origin_pts_out = []
            result_planes_out = []
            logs = []

            for i in range(n):
                BasePlane_i, OriginPoint_i, ResultPlane_i, Log_i = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o[i],
                    idx_p[i]
                )
                base_planes_out.append(BasePlane_i)
                origin_pts_out.append(OriginPoint_i)
                result_planes_out.append(ResultPlane_i)
                if Log_i:
                    logs.extend(flatten_list(Log_i))

            self.PlaneFromLists_2__BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PlaneFromLists_2__OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PlaneFromLists_2__ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PlaneFromLists_2__Log = logs

            self.Log.append("[PlaneFromLists::2] ResultPlane count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_2__BasePlane = None
            self.PlaneFromLists_2__OriginPoint = None
            self.PlaneFromLists_2__ResultPlane = None
            self.PlaneFromLists_2__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step4_2_plane_from_lists_2 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4.3：PlaneFromLists::3（来自 QiAOTool）
    # ------------------------------------------------------
    def step4_3_plane_from_lists_3(self):
        OriginPoints = self.QiAOTool__EdgeMidPoints
        BasePlanes = self.QiAOTool__Corner0Planes

        IndexOrigin = get_input_or_db(self.AllDict, "PlaneFromLists_3__IndexOrigin", 0)
        IndexPlane = get_input_or_db(self.AllDict, "PlaneFromLists_3__IndexPlane", 0)
        Wrap = get_input_or_db(self.AllDict, "PlaneFromLists_3__Wrap", True)

        try:
            idx_o = _as_list(IndexOrigin)
            idx_p = _as_list(IndexPlane)
            idx_o, idx_p, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_planes_out = []
            origin_pts_out = []
            result_planes_out = []
            logs = []

            for i in range(n):
                BasePlane_i, OriginPoint_i, ResultPlane_i, Log_i = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o[i],
                    idx_p[i]
                )
                base_planes_out.append(BasePlane_i)
                origin_pts_out.append(OriginPoint_i)
                result_planes_out.append(ResultPlane_i)
                if Log_i:
                    logs.extend(flatten_list(Log_i))

            self.PlaneFromLists_3__BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PlaneFromLists_3__OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PlaneFromLists_3__ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PlaneFromLists_3__Log = logs

            self.Log.append("[PlaneFromLists::3] ResultPlane count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_3__BasePlane = None
            self.PlaneFromLists_3__OriginPoint = None
            self.PlaneFromLists_3__ResultPlane = None
            self.PlaneFromLists_3__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step4_3_plane_from_lists_3 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 4.4：AlignToolToTimber::2（广播对齐 + MovedGeo 递归拍平）
    # Geo=QiAOTool.CutTimbers；SourcePlane=PFL3.ResultPlane；TargetPlane=PFL2.ResultPlane
    # ------------------------------------------------------
    def step4_4_align_tool_to_timber_2(self):
        Geo = self.QiAOTool__CutTimbers

        SourcePlane = self.PlaneFromLists_3__ResultPlane
        TargetPlane = self.PlaneFromLists_2__ResultPlane

        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_2__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_2__FlipX", False)
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_2__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_2__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_2__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_2__MoveY", 0.0)
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_2__MoveZ", 0.0)

        try:
            geo_list = flatten_list(Geo)
            sp_list = [SourcePlane] if isinstance(SourcePlane, rg.Plane) else _as_list(SourcePlane)
            tp_list = [TargetPlane] if isinstance(TargetPlane, rg.Plane) else _as_list(TargetPlane)

            rd_list = _as_list(RotateDeg)
            fx_list = [_to_bool(v, False) for v in _as_list(FlipX)]
            fy_list = [_to_bool(v, False) for v in _as_list(FlipY)]
            fz_list = [_to_bool(v, False) for v in _as_list(FlipZ)]
            mx_list = _as_list(MoveX)
            my_list = _as_list(MoveY)
            mz_list = _as_list(MoveZ)

            if len(fx_list) == 0: fx_list = [False]
            if len(fy_list) == 0: fy_list = [False]
            if len(fz_list) == 0: fz_list = [False]

            n = max(len(geo_list), len(sp_list), len(tp_list), len(rd_list),
                    len(fx_list), len(fy_list), len(fz_list),
                    len(mx_list), len(my_list), len(mz_list), 1)

            geo_list = _broadcast_to_len(geo_list, n)
            sp_list = _broadcast_to_len(sp_list, n)
            tp_list = _broadcast_to_len(tp_list, n)
            rd_list = _broadcast_to_len(rd_list, n)
            fx_list = _broadcast_to_len(fx_list, n)
            fy_list = _broadcast_to_len(fy_list, n)
            fz_list = _broadcast_to_len(fz_list, n)
            mx_list = _broadcast_to_len(mx_list, n)
            my_list = _broadcast_to_len(my_list, n)
            mz_list = _broadcast_to_len(mz_list, n)

            source_out = []
            target_out = []
            xfm_out = []
            moved_geo = []

            for i in range(n):
                so, to, xfm, mg = GeoAligner_xfm.align(
                    geo_list[i],
                    sp_list[i],
                    tp_list[i],
                    rotate_deg=rd_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                source_out.append(so)
                target_out.append(to)
                xfm_out.append(xfm)
                moved_geo.append(mg)

            xfm_wrapped = [ght.GH_Transform(x) if x is not None else None for x in xfm_out]
            moved_geo_flat = flatten_list(moved_geo)

            self.AlignToolToTimber_2__SourceOut = source_out[0] if n == 1 else source_out
            self.AlignToolToTimber_2__TargetOut = target_out[0] if n == 1 else target_out
            self.AlignToolToTimber_2__TransformOut = xfm_wrapped[0] if n == 1 else xfm_wrapped
            self.AlignToolToTimber_2__MovedGeo = moved_geo_flat

            self.Log.append(
                "[AlignToolToTimber::2] MovedGeo raw_count={} -> flat_count={}".format(n, len(moved_geo_flat)))

        except Exception as e:
            self.AlignToolToTimber_2__SourceOut = None
            self.AlignToolToTimber_2__TargetOut = None
            self.AlignToolToTimber_2__TransformOut = None
            self.AlignToolToTimber_2__MovedGeo = None
            self.Log.append("[ERROR] Step4_4_align_tool_to_timber_2 出错: {}".format(e))

        return self

    # ------------------------------------------------------

    # ------------------------------------------------------
    # Step 5.1：BlockCutter::1（块切割器，生成散枓/令栱切削用刀具体）
    # - 使用 build_timber_block_uniform 生成矩形块 Brep
    # - base_point：若 DB 未提供，按组件约定默认原点（不使用总 base_point，避免跟木料放置点混淆）
    # - reference_plane：若 DB 未提供，默认 "XZ"
    # ------------------------------------------------------
    def step5_1_blockcutter_1(self):
        """Step 5-1 :: BlockCutter::1

        说明（按 GH 定义）：
        - length_fen / width_fen / height_fen 允许为单值或列表；
        - 当三者均为多值时，同一索引对应生成一组（L,W,H）的长方体；
        - 若三者长度不一致，采用广播（短的重复/补齐到最长长度）。
        """
        try:
            length_fen = get_input_or_db(self.AllDict, "BlockCutter_1__length_fen", 32.0)
            width_fen = get_input_or_db(self.AllDict, "BlockCutter_1__width_fen", 32.0)
            height_fen = get_input_or_db(self.AllDict, "BlockCutter_1__height_fen", 20.0)

            bp_in = get_input_or_db(self.AllDict, "BlockCutter_1__base_point", None)
            bp = _to_point3d(bp_in) if bp_in is not None else rg.Point3d(0.0, 0.0, 0.0)

            ref_plane_in = get_input_or_db(self.AllDict, "BlockCutter_1__reference_plane", "XZ")
            if isinstance(ref_plane_in, rg.Plane):
                ref_plane = ref_plane_in
            elif isinstance(ref_plane_in, str):
                ref_plane = gh_plane(ref_plane_in, origin=rg.Point3d(0, 0, 0))
            else:
                ref_plane = gh_plane("XZ", origin=rg.Point3d(0, 0, 0))

            l_list = _as_list(length_fen)
            w_list = _as_list(width_fen)
            h_list = _as_list(height_fen)

            # 允许用户只给单值：广播到最大长度
            n = max(len(l_list), len(w_list), len(h_list), 1)
            l_list = _broadcast_to_len(l_list if len(l_list) else [32.0], n)
            w_list = _broadcast_to_len(w_list if len(w_list) else [32.0], n)
            h_list = _broadcast_to_len(h_list if len(h_list) else [20.0], n)

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            logs_all = []

            for i in range(n):
                (
                    timber_brep,
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
                    log_lines,
                ) = build_timber_block_uniform(
                    float(l_list[i]),
                    float(w_list[i]),
                    float(h_list[i]),
                    bp,
                    ref_plane,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                logs_all.append(log_lines if log_lines else [])

            # n==1 时保持兼容（输出单值）；n>1 输出列表/嵌套列表
            if n == 1:
                self.BlockCutter_1__TimberBrep = timber_breps[0]
                self.BlockCutter_1__FaceList = faces_list[0]
                self.BlockCutter_1__PointList = points_list[0]
                self.BlockCutter_1__EdgeList = edges_list[0]
                self.BlockCutter_1__CenterPoint = center_pts[0]
                self.BlockCutter_1__CenterAxisLines = center_axes_list[0]
                self.BlockCutter_1__EdgeMidPoints = edge_midpts_list[0]
                self.BlockCutter_1__FacePlaneList = face_planes_list[0]
                self.BlockCutter_1__Corner0Planes = corner0_planes_list[0]
                self.BlockCutter_1__LocalAxesPlane = local_axes_planes[0]
                self.BlockCutter_1__AxisX = axis_x_list[0]
                self.BlockCutter_1__AxisY = axis_y_list[0]
                self.BlockCutter_1__AxisZ = axis_z_list[0]
                self.BlockCutter_1__FaceDirTags = face_tags_list[0]
                self.BlockCutter_1__EdgeDirTags = edge_tags_list[0]
                self.BlockCutter_1__Corner0EdgeDirs = corner0_dirs_list[0]
                self.BlockCutter_1__Log = logs_all[0]
            else:
                self.BlockCutter_1__TimberBrep = timber_breps
                self.BlockCutter_1__FaceList = faces_list
                self.BlockCutter_1__PointList = points_list
                self.BlockCutter_1__EdgeList = edges_list
                self.BlockCutter_1__CenterPoint = center_pts
                self.BlockCutter_1__CenterAxisLines = center_axes_list
                self.BlockCutter_1__EdgeMidPoints = edge_midpts_list
                self.BlockCutter_1__FacePlaneList = face_planes_list
                self.BlockCutter_1__Corner0Planes = corner0_planes_list
                self.BlockCutter_1__LocalAxesPlane = local_axes_planes
                self.BlockCutter_1__AxisX = axis_x_list
                self.BlockCutter_1__AxisY = axis_y_list
                self.BlockCutter_1__AxisZ = axis_z_list
                self.BlockCutter_1__FaceDirTags = face_tags_list
                self.BlockCutter_1__EdgeDirTags = edge_tags_list
                self.BlockCutter_1__Corner0EdgeDirs = corner0_dirs_list
                self.BlockCutter_1__Log = logs_all

            self.Log.append("[BlockCutter::1] ToolBlockCount={}".format(n))
            if n > 1:
                for i in range(n):
                    self.Log.append("[BlockCutter::1] idx={} L/W/H={}/{}/{}".format(i, l_list[i], w_list[i], h_list[i]))
            else:
                for l in (self.BlockCutter_1__Log or []):
                    self.Log.append("[BlockCutter::1] " + str(l))

        except Exception as e:
            self.BlockCutter_1__TimberBrep = None
            self.BlockCutter_1__FaceList = []
            self.BlockCutter_1__PointList = []
            self.BlockCutter_1__EdgeList = []
            self.BlockCutter_1__CenterPoint = None
            self.BlockCutter_1__CenterAxisLines = []
            self.BlockCutter_1__EdgeMidPoints = []
            self.BlockCutter_1__FacePlaneList = []
            self.BlockCutter_1__Corner0Planes = []
            self.BlockCutter_1__LocalAxesPlane = None
            self.BlockCutter_1__AxisX = None
            self.BlockCutter_1__AxisY = None
            self.BlockCutter_1__AxisZ = None
            self.BlockCutter_1__FaceDirTags = []
            self.BlockCutter_1__EdgeDirTags = []
            self.BlockCutter_1__Corner0EdgeDirs = []
            self.BlockCutter_1__Log = ["错误: {}".format(e)]
            self.Log.append("[BlockCutter::1] ERROR: {}".format(e))

        return self

    def step5_2_plane_from_lists_4(self):
        OriginPoints = self.EdgeMidPoints
        BasePlanes = self.Corner0Planes

        IndexOrigin = get_input_or_db(self.AllDict, "PlaneFromLists_4__IndexOrigin", 0)
        IndexPlane = get_input_or_db(self.AllDict, "PlaneFromLists_4__IndexPlane", 0)
        Wrap = get_input_or_db(self.AllDict, "PlaneFromLists_4__Wrap", True)

        try:
            idx_o = _as_list(IndexOrigin)
            idx_p = _as_list(IndexPlane)
            idx_o, idx_p, n = _broadcast_pair(idx_o, idx_p)

            builder = FTPlaneFromLists(wrap=bool(Wrap))

            base_planes_out = []
            origin_pts_out = []
            result_planes_out = []
            logs = []

            for i in range(n):
                BasePlane_i, OriginPoint_i, ResultPlane_i, Log_i = builder.build_plane(
                    OriginPoints,
                    BasePlanes,
                    idx_o[i],
                    idx_p[i]
                )
                base_planes_out.append(BasePlane_i)
                origin_pts_out.append(OriginPoint_i)
                result_planes_out.append(ResultPlane_i)
                if Log_i:
                    logs.extend(flatten_list(Log_i))

            self.PlaneFromLists_4__BasePlane = base_planes_out[0] if n == 1 else base_planes_out
            self.PlaneFromLists_4__OriginPoint = origin_pts_out[0] if n == 1 else origin_pts_out
            self.PlaneFromLists_4__ResultPlane = result_planes_out[0] if n == 1 else result_planes_out
            self.PlaneFromLists_4__Log = logs

            self.Log.append("[PlaneFromLists::4] ResultPlane count={}".format(n))

        except Exception as e:
            self.PlaneFromLists_4__BasePlane = None
            self.PlaneFromLists_4__OriginPoint = None
            self.PlaneFromLists_4__ResultPlane = None
            self.PlaneFromLists_4__Log = ["错误: {}".format(e)]
            self.Log.append("[ERROR] Step5_2_plane_from_lists_4 出错: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 5.3：AlignToolToTimber::3（对位 BlockCutter::1 到 Timber）
    # Geo=BlockCutter::1.TimberBrep；SourcePlane=BlockCutter::1.FacePlaneList[idx]；TargetPlane=PFL4.ResultPlane
    # - 注意：Geo 在 GH 中常为 Tree；此处允许 Geo 为单 brep 或 list（会拍平后广播）
    # - SourcePlane：由索引（可为列表）从 FacePlaneList 取出；索引不足广播对齐
    # ------------------------------------------------------

    def step5_3_align_tool_to_timber_3(self):
        """AlignToolToTimber::3（Tree 分支逐一对位 + 操作序列广播）

        关键行为（与你描述一致）：
        - Geo 为 Tree：每个分支 1 个对象（若分支多对象则逐个作为独立分支元素处理）
        - 其它参数若广播后长度为 k，则对每个 Geo 分支分别执行 k 次对位
        例如：Geo 有 2 个分支；RotateDeg/MoveX 等广播后为 2
        -> 每个分支输出 2 个结果，总计 4 个
        - 参数支持：标量 / list / tree（tree 且分支数匹配时按分支提供，否则视作全局操作序列）
        """
        Geo = self.BlockCutter_1__TimberBrep
        FacePlaneList = self.BlockCutter_1__FacePlaneList if self.BlockCutter_1__FacePlaneList else []

        TargetPlane = self.PlaneFromLists_4__ResultPlane

        SourcePlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_3__SourcePlane", 0)
        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_3__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_3__FlipX", False)

        # 其余参数未在本 step 描述中出现，但 GeoAligner_xfm.align 需要完整签名；默认为 False/0
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_3__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_3__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_3__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_3__MoveY", 0.0)
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_3__MoveZ", 0.0)

        try:
            # --------------------------------------------------
            # 1) Geo Tree -> branches
            # --------------------------------------------------
            geo_branches = tree_to_branches(Geo)
            # 每个分支可能不止 1 个对象：按 GH “每分支一个对象”的假设取第 1 个；
            # 若确实多对象，也尽量把它们拆成多个分支元素，避免丢失。
            geo_items = []
            for br in geo_branches:
                if br is None or len(br) == 0:
                    geo_items.append(None)
                elif len(br) == 1:
                    geo_items.append(br[0])
                else:
                    # 多对象：拆分成多个“伪分支”
                    for g in br:
                        geo_items.append(g)

            branch_count = len(geo_items)

            if branch_count == 0:
                self.AlignToolToTimber_3__SourceOut = None
                self.AlignToolToTimber_3__TargetOut = None
                self.AlignToolToTimber_3__TransformOut = None
                self.AlignToolToTimber_3__MovedGeo = None
                self.Log.append("[WARN] Step5_3_align_tool_to_timber_3: Geo 为空")
                return self

            # --------------------------------------------------
            # 2) 规范化参数：变成 per-branch 的“操作序列”
            # --------------------------------------------------
            idx_branch = _param_to_branch_lists(SourcePlaneIndex, branch_count)
            rd_branch = _param_to_branch_lists(RotateDeg, branch_count)
            fx_branch = _param_to_branch_lists(FlipX, branch_count)
            fy_branch = _param_to_branch_lists(FlipY, branch_count)
            fz_branch = _param_to_branch_lists(FlipZ, branch_count)
            mx_branch = _param_to_branch_lists(MoveX, branch_count)
            my_branch = _param_to_branch_lists(MoveY, branch_count)
            mz_branch = _param_to_branch_lists(MoveZ, branch_count)

            # TargetPlane：标量/列表/树 都支持
            tp_branch = _param_to_branch_lists(TargetPlane, branch_count)

            # --------------------------------------------------
            # 3) FacePlaneList：支持单块(list[Plane]) / 多块(list[list[Plane]])
            # --------------------------------------------------
            def _faceplanes_for_branch(i):
                if FacePlaneList is None:
                    return []
                if isinstance(FacePlaneList, (list, tuple)) and len(FacePlaneList) > 0 and isinstance(FacePlaneList[0],
                                                                                                      (list, tuple)):
                    # 多块：按分支取对应子列表（不足则用最后一个）
                    j = i if i < len(FacePlaneList) else (len(FacePlaneList) - 1)
                    return list(FacePlaneList[j]) if FacePlaneList[j] is not None else []
                # 单块
                return list(FacePlaneList)

            # --------------------------------------------------
            # 4) 执行：每个分支 i 执行 k_i 次操作
            #    k_i = max(该分支各参数序列长度)
            # --------------------------------------------------
            source_out_all = []
            target_out_all = []
            xfm_out_all = []
            moved_geo_all = []

            for i in range(branch_count):
                geo_i = geo_items[i]

                idx_seq = _as_list(idx_branch[i])
                rd_seq = _as_list(rd_branch[i])
                fx_seq = [_to_bool(v, False) for v in _as_list(fx_branch[i])]
                fy_seq = [_to_bool(v, False) for v in _as_list(fy_branch[i])]
                fz_seq = [_to_bool(v, False) for v in _as_list(fz_branch[i])]
                mx_seq = _as_list(mx_branch[i])
                my_seq = _as_list(my_branch[i])
                mz_seq = _as_list(mz_branch[i])

                # TargetPlane 序列：支持 Plane / list[Plane] / 其它（尽量容错）
                tp_seq_raw = tp_branch[i]
                if isinstance(tp_seq_raw, rg.Plane):
                    tp_seq = [tp_seq_raw]
                else:
                    tp_seq = _as_list(tp_seq_raw)

                # 至少 1 次操作
                k = max(
                    len(idx_seq), len(rd_seq), len(fx_seq), len(fy_seq), len(fz_seq),
                    len(mx_seq), len(my_seq), len(mz_seq), len(tp_seq), 1
                )

                idx_seq = _broadcast_to_len(idx_seq if len(idx_seq) else [0], k)
                rd_seq = _broadcast_to_len(rd_seq if len(rd_seq) else [0.0], k)
                fx_seq = _broadcast_to_len(fx_seq if len(fx_seq) else [False], k)
                fy_seq = _broadcast_to_len(fy_seq if len(fy_seq) else [False], k)
                fz_seq = _broadcast_to_len(fz_seq if len(fz_seq) else [False], k)
                mx_seq = _broadcast_to_len(mx_seq if len(mx_seq) else [0.0], k)
                my_seq = _broadcast_to_len(my_seq if len(my_seq) else [0.0], k)
                mz_seq = _broadcast_to_len(mz_seq if len(mz_seq) else [0.0], k)
                tp_seq = _broadcast_to_len(tp_seq if len(tp_seq) else [None], k)

                # SourcePlane：由 FacePlaneList + 索引得到（索引可广播）
                fps = _faceplanes_for_branch(i)
                sp_seq = []
                for j in range(k):
                    sp = None
                    if fps and len(fps) > 0:
                        try:
                            _idx = int(idx_seq[j])
                        except Exception:
                            _idx = 0
                        sp = fps[_idx % len(fps)]
                    sp_seq.append(sp)

                so_list = []
                to_list = []
                xfm_list = []
                mg_list = []

                for j in range(k):
                    so, to, xfm, mg = GeoAligner_xfm.align(
                        geo_i,
                        sp_seq[j],
                        tp_seq[j],
                        rotate_deg=rd_seq[j],
                        flip_x=fx_seq[j],
                        flip_y=fy_seq[j],
                        flip_z=fz_seq[j],
                        move_x=mx_seq[j],
                        move_y=my_seq[j],
                        move_z=mz_seq[j],
                    )
                    so_list.append(so)
                    to_list.append(to)
                    xfm_list.append(xfm)
                    mg_list.append(mg)

                source_out_all.append(so_list)
                target_out_all.append(to_list)
                xfm_out_all.append(xfm_list)
                moved_geo_all.append(mg_list)

            # --------------------------------------------------
            # 5) 写回输出（保持 Tree 语义：list[branch][op]）
            # --------------------------------------------------
            self.AlignToolToTimber_3__SourceOut = source_out_all
            self.AlignToolToTimber_3__TargetOut = target_out_all
            self.AlignToolToTimber_3__TransformOut = xfm_out_all
            # 保留 Tree 结构（开发/调试用）
            self.AlignToolToTimber_3__MovedGeo_Tree = moved_geo_all

            # GH 输出端：默认给“深度拍平”的结果，避免出现 System.Collections.Generic.List`1[System.Object]
            self.AlignToolToTimber_3__MovedGeo = flatten_list(moved_geo_all)

            # 同时提供一个别名（拍平版本），便于后续 CutTimbersByTools 直接使用
            self.AlignToolToTimber_3__MovedGeo_Flat = self.AlignToolToTimber_3__MovedGeo

            self.Log.append(
                "[OK] Step5_3 AlignToolToTimber::3 完成（branches={}, per-branch ops<=see data）".format(branch_count))

        except Exception as e:
            self.AlignToolToTimber_3__SourceOut = None
            self.AlignToolToTimber_3__TargetOut = None
            self.AlignToolToTimber_3__TransformOut = None
            self.AlignToolToTimber_3__MovedGeo = None
            self.Log.append("[ERROR] Step5_3_align_tool_to_timber_3 出错: {}".format(e))

        return self

    def step5_4_blockcutter_2(self):
        """Step 5-4 :: BlockCutter::2（单令栱块刀具）

        - length_fen / width_fen / height_fen 可为单值或列表
        - 当三者均为多值时，同一索引对应生成一组（L,W,H）的长方体
        - base_point：未提供则用原点（0,0,0）
        """
        try:
            l_in = get_input_or_db(self.AllDict, "BlockCutter_2__length_fen", 32.0)
            w_in = get_input_or_db(self.AllDict, "BlockCutter_2__width_fen", 32.0)
            h_in = get_input_or_db(self.AllDict, "BlockCutter_2__height_fen", 20.0)

            # base_point：沿用系统 BasePoint（若未设置则原点）
            bp = self.BasePoint if isinstance(getattr(self, "BasePoint", None), rg.Point3d) else rg.Point3d(0.0, 0.0,
                                                                                                            0.0)

            # 参考平面：若 DB 未提供则用 WorldXZ（与 timber_block_uniform 一致）
            ref_mode = get_input_or_db(self.AllDict, "BlockCutter_2__reference_plane", "WorldXZ")
            ref_plane = GHPlaneFactory.make(ref_mode, origin=bp)

            # list 化并“同索引配对”
            Ls = _as_list(l_in)
            Ws = _as_list(w_in)
            Hs = _as_list(h_in)

            n = max(len(Ls), len(Ws), len(Hs), 1)
            Ls = _broadcast_to_len(Ls, n)
            Ws = _broadcast_to_len(Ws, n)
            Hs = _broadcast_to_len(Hs, n)

            breps = []
            faceplanes_all = []
            edge_mid_all = []
            corner0_all = []
            logs = []

            for i in range(n):
                try:
                    (
                        timber_brep,
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
                        log_lines,
                    ) = build_timber_block_uniform(
                        float(Ls[i]),
                        float(Ws[i]),
                        float(Hs[i]),
                        bp,
                        ref_plane,
                    )
                    breps.append(timber_brep)
                    faceplanes_all.append(face_planes)
                    edge_mid_all.append(edge_midpts)
                    corner0_all.append(corner0_planes)
                    logs.extend(log_lines if isinstance(log_lines, list) else [str(log_lines)])
                except Exception as e:
                    logs.append("[BlockCutter::2] idx={} ERROR: {}".format(i, e))

            self.BlockCutter_2__TimberBrep = breps if n != 1 else (breps[0] if breps else None)
            self.BlockCutter_2__FacePlaneList = faceplanes_all if n != 1 else (
                faceplanes_all[0] if faceplanes_all else [])
            self.BlockCutter_2__EdgeMidPoints = edge_mid_all if n != 1 else (edge_mid_all[0] if edge_mid_all else [])
            self.BlockCutter_2__Corner0Planes = corner0_all if n != 1 else (corner0_all[0] if corner0_all else [])
            self.BlockCutter_2__Log = logs

            self.Log.append("[BlockCutter::2] OK (n={})".format(n))
        except Exception as e:
            self.BlockCutter_2__TimberBrep = None
            self.BlockCutter_2__FacePlaneList = []
            self.BlockCutter_2__EdgeMidPoints = []
            self.BlockCutter_2__Corner0Planes = []
            self.BlockCutter_2__Log = ["错误: {}".format(e)]
            self.Log.append("[BlockCutter::2] ERROR: {}".format(e))

        return self

    def step5_5_align_tool_to_timber_4(self):
        """Step 5-5 :: AlignToolToTimber::4（单令栱切削对位）

        按 GH 输入端配置复现行为（结合你截图与描述）：
        - Geo：BlockCutter::2 的 TimberBrep（通常为单 Brep，也允许 list/tree）
        - SourcePlane：BlockCutter::2 的 FacePlaneList，经 AlignToolToTimber_4__SourcePlane 索引得到 *一个 Plane*
          （在 GH 中通常由 List Item 先取出，因此这里以“索引 -> 单 Plane”为准）
        - TargetPlane：复用 PlaneFromLists::4 的 ResultPlane（可为单 Plane 或 list/tree）
        - RotateDeg / FlipX / MoveX：作为 Phase1 的“操作序列”，长度 k 由广播对齐得到
        - MoveY：Tree（两个分支，每分支一个值）。对 Phase1 的每个结果，分别执行这两个 MoveY 分支
          => 若 Phase1 产生 k 个结果，则最终输出数量 = k * (MoveY 分支数)

        重要：输出端避免 GH 出现 System.Collections.Generic.List`1[System.Object]，因此提供深度展平输出。
        """

        Geo = self.BlockCutter_2__TimberBrep
        FacePlaneList = self.BlockCutter_2__FacePlaneList if self.BlockCutter_2__FacePlaneList else []
        TargetPlane = self.PlaneFromLists_4__ResultPlane  # 与 AlignToolToTimber::3 相同来源

        # --- 参数（来自数据库 AllDict；如你后续给该 Solver 增加同名 GH 输入端，也会被 get_input_or_db 覆盖） ---
        SourcePlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_4__SourcePlane", 0)
        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_4__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_4__FlipX", False)
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_4__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_4__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_4__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_4__MoveY", 0.0)  # Tree（两个分支）
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_4__MoveZ", 0.0)

        print(MoveY)

        # ------------------------------------------------------------
        # A) Geo：按“分支”组织（Tree -> branches；非 tree 则视为单分支）
        # ------------------------------------------------------------
        geo_branches = tree_to_branches(Geo)
        if not geo_branches:
            geo_branches = [[Geo]] if Geo is not None else []
        # 组件约束：每分支一个对象；若分支里有多个，仍逐个处理
        geo_items = []
        for br in geo_branches:
            if br is None:
                continue
            for g in _as_list(br):
                if g is not None:
                    geo_items.append(g)

        # ------------------------------------------------------------
        # B) MoveY：Tree 两个分支
        # - 若输入是 {0}[a,b] 这种“单分支多项”，按你的需求将其视为 2 个分支（等价 GH 的 Graft）
        # ------------------------------------------------------------
        my_branches = tree_to_branches(MoveY)
        if not my_branches:
            my_branches = [[MoveY]]

        # 单分支多项 -> 视为每项一个分支（更贴近你当前 MoveY 已改 Tree 的目的）
        if len(my_branches) == 1 and isinstance(my_branches[0], (list, tuple)) and len(my_branches[0]) > 1:
            my_branches = [[v] for v in my_branches[0]]

        # 每分支只取第一个值（符合“每分支一个值”）
        my_values = []
        for br in my_branches:
            br_list = _as_list(br)
            if br_list:
                my_values.append(float(br_list[0]))
        if not my_values:
            my_values = [0.0]

        # ------------------------------------------------------------
        # C) Phase1：对位 + MoveX（MoveY/MoveZ 置 0）
        # - 关键：SourcePlane 先由索引取到 *单 Plane*
        # - RotateDeg / FlipX / MoveX / TargetPlane 广播到长度 k
        # ------------------------------------------------------------
        # SourcePlaneIndex 也允许是 list（数据库可能写成 [0,1] 等）
        sp_idx_list = _as_list(SourcePlaneIndex)
        if not sp_idx_list:
            sp_idx_list = [0]

        rot_list = _as_list(RotateDeg) or [0.0]
        fx_list = _as_list(FlipX) or [False]
        fy_list = _as_list(FlipY) or [False]
        fz_list = _as_list(FlipZ) or [False]
        mx_list = _as_list(MoveX) or [0.0]

        # TargetPlane：允许 scalar / list / tree（若是 tree，取其所有分支首项）
        tp_list = []
        tp_branches = tree_to_branches(TargetPlane)
        if tp_branches:
            for br in tp_branches:
                br_list = _as_list(br)
                if br_list:
                    tp_list.append(br_list[0])
        else:
            tp_list = _as_list(TargetPlane)
        if not tp_list:
            tp_list = [TargetPlane]

        # k：GH 广播常见做法：按最长序列对齐
        k = max(len(sp_idx_list), len(rot_list), len(fx_list), len(fy_list), len(fz_list), len(mx_list), len(tp_list))
        sp_idx_list = _broadcast_to_len(sp_idx_list, k)
        rot_list = _broadcast_to_len(rot_list, k)
        fx_list = _broadcast_to_len(fx_list, k)
        fy_list = _broadcast_to_len(fy_list, k)
        fz_list = _broadcast_to_len(fz_list, k)
        mx_list = _broadcast_to_len(mx_list, k)
        tp_list = _broadcast_to_len(tp_list, k)

        # FacePlaneList：可能是 list[Plane] 或 list[list[Plane]]（当 BlockCutter 多块时）
        def _pick_face_plane(face_plane_list, idx, geo_i=0):
            # idx 支持 wrap
            try:
                ii = int(idx)
            except:
                ii = 0

            if not face_plane_list:
                return None

            # 多块：face_plane_list[geo_i] 是该块的 face planes
            if isinstance(face_plane_list[0], (list, tuple)):
                gi = max(0, min(int(geo_i), len(face_plane_list) - 1))
                sub = face_plane_list[gi]
                if not sub:
                    return None
                ii = ii % len(sub)
                return sub[ii]
            # 单块
            ii = ii % len(face_plane_list)
            return face_plane_list[ii]

        # --- Plane 兼容：支持 rg.Plane / GH_Plane / GH_Plane-like（带 Value 属性） ---
        def _plane_value(p):
            if p is None:
                return None
            # GH_Plane / GH_Goo 平面
            if hasattr(p, "Value"):
                try:
                    pv = p.Value
                    if isinstance(pv, rg.Plane):
                        return pv
                except:
                    pass
            # 直接是 Rhino 平面
            if isinstance(p, rg.Plane):
                return p
            # 某些对象可能有 Plane 属性
            if hasattr(p, "Plane"):
                try:
                    pv = p.Plane
                    if isinstance(pv, rg.Plane):
                        return pv
                except:
                    pass
            return p

        def _wrap_gh_plane(p):
            p = _plane_value(p)
            try:
                return ght.GH_Plane(p) if isinstance(p, rg.Plane) else p
            except:
                return p

        phase1_results = []  # list[geo_item][op_i] -> brep
        phase1_xforms = []  # 同维度
        phase1_sourceouts = []  # list[geo_item][op_i] -> plane
        phase1_targetouts = []  # list[geo_item][op_i] -> plane

        for gi, g in enumerate(geo_items):
            per_geo_res = []
            per_geo_xf = []
            per_geo_so = []
            per_geo_to = []
            for i in range(k):
                sp = _pick_face_plane(FacePlaneList, sp_idx_list[i], geo_i=gi)
                tp = tp_list[i]
                sp = _plane_value(sp)
                tp = _plane_value(tp)

                so, to, xf, moved = GeoAligner_xfm.align(
                    g,
                    sp,
                    tp,
                    rotate_deg=rot_list[i],
                    flip_x=InputHelper.to_bool(fx_list[i], default=False),
                    flip_y=InputHelper.to_bool(fy_list[i], default=False),
                    flip_z=InputHelper.to_bool(fz_list[i], default=False),
                    move_x=float(mx_list[i]),
                    move_y=0.0,
                    move_z=0.0,
                )
                # 记录 SourceOut / TargetOut（若 GeoAligner 返回 None，则回退到输入平面）
                so = _plane_value(so) if so is not None else sp
                to = _plane_value(to) if to is not None else tp
                per_geo_res.append(moved)
                per_geo_xf.append(xf)
                per_geo_so.append(so)
                per_geo_to.append(to)
            phase1_results.append(per_geo_res)
            phase1_xforms.append(per_geo_xf)
            phase1_sourceouts.append(per_geo_so)
            phase1_targetouts.append(per_geo_to)

        # ------------------------------------------------------------
        # D) Phase2：仅 MoveY Tree 分支（每个 Phase1 结果都执行所有 MoveY 分支）
        # - 保持沿 TargetPlane 的 Y 轴平移
        # ------------------------------------------------------------
        moved_tree = []  # list[geo_i][op_i][my_branch] -> brep
        xform_tree = []
        source_out_tree = []  # same shape as moved_tree: plane
        target_out_tree = []

        for gi in range(len(phase1_results)):
            geo_tree = []
            geo_xf_t = []
            geo_so_t = []
            geo_to_t = []
            for i in range(k):
                base_geo = phase1_results[gi][i]
                # Phase2 的参考平面 tp：优先使用 Phase1 输出的 TargetOut（已包含 rotate/flip 的影响）
                base_so = phase1_sourceouts[gi][i] if gi < len(phase1_sourceouts) and i < len(
                    phase1_sourceouts[gi]) else None
                base_to = phase1_targetouts[gi][i] if gi < len(phase1_targetouts) and i < len(
                    phase1_targetouts[gi]) else None
                tp = _plane_value(base_to) if base_to is not None else _plane_value(tp_list[i])
                op_tree = []
                op_xfs = []
                op_sos = []
                op_tos = []
                for my in my_values:
                    # Phase2：仅做“沿 TargetPlane 局部 Y 轴”的平移（显式向量，不再二次调用 align）
                    # 这样不会因 Phase1 的 rotate/flip 导致 move_y 语义在世界坐标里“看起来跑到 X”。
                    # Phase2：用 align 做“仅沿 TargetPlane 局部轴”的位移（SourcePlane=TargetPlane=tp）
                    # 这样既复用 GeoAligner_xfm 内部对 GH_Plane/rg.Plane 的兼容处理，
                    # 又保证 move_y 语义始终是 “沿 tp.YAxis”。
                    so2, to2, xf2, moved2 = GeoAligner_xfm.align(
                        base_geo,
                        tp,
                        tp,
                        rotate_deg=0.0,
                        flip_x=False,
                        flip_y=False,
                        flip_z=False,
                        move_x=0.0,
                        move_y=float(my),
                        move_z=0.0,
                    )
                    op_tree.append(moved2)
                    op_xfs.append(xf2)
                    op_sos.append(_plane_value(so2) if so2 is not None else (base_so if base_so is not None else tp))
                    op_tos.append(_plane_value(to2) if to2 is not None else (base_to if base_to is not None else tp))
                geo_tree.append(op_tree)
                geo_xf_t.append(op_xfs)
                geo_so_t.append(op_sos)
                geo_to_t.append(op_tos)
            moved_tree.append(geo_tree)
            xform_tree.append(geo_xf_t)
            source_out_tree.append(geo_so_t)
            target_out_tree.append(geo_to_t)

        # ------------------------------------------------------------
        # E) 输出：深度展平 +（可选）保留 Tree 结构
        # ------------------------------------------------------------
        self.AlignToolToTimber_4__MovedGeo_Tree = moved_tree
        self.AlignToolToTimber_4__Transform_Tree = xform_tree

        self.AlignToolToTimber_4__SourceOut_Tree = source_out_tree
        self.AlignToolToTimber_4__TargetOut_Tree = target_out_tree

        flat = flatten_list(moved_tree)
        self.AlignToolToTimber_4__MovedGeo = flat
        self.AlignToolToTimber_4__MovedGeo_Flat = flat

        # SourceOut / TargetOut：与 MovedGeo 一一对应（展平）
        flat_so = flatten_list(source_out_tree)
        flat_to = flatten_list(target_out_tree)
        self.AlignToolToTimber_4__SourceOut = [_wrap_gh_plane(p) for p in flat_so]
        self.AlignToolToTimber_4__TargetOut = [_wrap_gh_plane(p) for p in flat_to]

        # 兼容 TransformOut 的 GH 包装（若后续你把它作为输出端）
        self.AlignToolToTimber_4__TransformOut = [ght.GH_Transform(xf) if xf is not None else None for xf in
                                                  flatten_list(xform_tree)]

        self.Log.append("step5_5 AlignToolToTimber::4 done. geo_items={}, k={}, my_branches={}, out={}".format(
            len(geo_items), k, len(my_values), len(flat)
        ))

        return self

    # ------------------------------------------------------
    # Step 6.1：BlockCutter::3（泥道栱切削块刀具）
    # 对应独立组件 BlockCutter::3
    # ------------------------------------------------------
    def step6_1_blockcutter_3(self):
        try:
            length_fen = get_input_or_db(self.AllDict, "BlockCutter_3__length_fen", 32.0)
            width_fen = get_input_or_db(self.AllDict, "BlockCutter_3__width_fen", 32.0)
            height_fen = get_input_or_db(self.AllDict, "BlockCutter_3__height_fen", 20.0)

            bp_in = get_input_or_db(self.AllDict, "BlockCutter_3__base_point", None)
            bp = _to_point3d(bp_in) if bp_in is not None else rg.Point3d(0.0, 0.0, 0.0)

            # reference_plane：DB 未提供则默认 "XZ"（与独立组件一致）
            ref_plane_in = get_input_or_db(self.AllDict, "BlockCutter_3__reference_plane", "XZ")
            if isinstance(ref_plane_in, rg.Plane):
                reference_plane = ref_plane_in
            elif isinstance(ref_plane_in, str):
                reference_plane = gh_plane(ref_plane_in, origin=rg.Point3d(0, 0, 0))
            else:
                reference_plane = gh_plane("XZ", origin=rg.Point3d(0, 0, 0))

            # 允许 L/W/H 为 list：同索引配对，长度不足广播
            Ls = _as_list(length_fen) or [32.0]
            Ws = _as_list(width_fen) or [32.0]
            Hs = _as_list(height_fen) or [20.0]

            n = max(len(Ls), len(Ws), len(Hs), 1)
            Ls = _broadcast_to_len(Ls, n)
            Ws = _broadcast_to_len(Ws, n)
            Hs = _broadcast_to_len(Hs, n)

            timber_breps = []
            faces_list = []
            points_list = []
            edges_list = []
            center_pts = []
            center_axes_list = []
            edge_midpts_list = []
            face_planes_list = []
            corner0_planes_list = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_list = []
            edge_tags_list = []
            corner0_dirs_list = []
            logs_all = []

            for i in range(n):
                (
                    timber_brep,
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
                    log_lines,
                ) = build_timber_block_uniform(
                    float(Ls[i]),
                    float(Ws[i]),
                    float(Hs[i]),
                    bp,
                    reference_plane,
                )

                timber_breps.append(timber_brep)
                faces_list.append(faces)
                points_list.append(points)
                edges_list.append(edges)
                center_pts.append(center_pt)
                center_axes_list.append(center_axes)
                edge_midpts_list.append(edge_midpts)
                face_planes_list.append(face_planes)
                corner0_planes_list.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_list.append(face_tags)
                edge_tags_list.append(edge_tags)
                corner0_dirs_list.append(corner0_dirs)
                logs_all.append(log_lines if log_lines else [])

            # n==1 时输出单值；n>1 输出列表（与 step5_1 保持一致）
            if n == 1:
                self.BlockCutter_3__TimberBrep = timber_breps[0]
                self.BlockCutter_3__FaceList = faces_list[0]
                self.BlockCutter_3__PointList = points_list[0]
                self.BlockCutter_3__EdgeList = edges_list[0]
                self.BlockCutter_3__CenterPoint = center_pts[0]
                self.BlockCutter_3__CenterAxisLines = center_axes_list[0]
                self.BlockCutter_3__EdgeMidPoints = edge_midpts_list[0]
                self.BlockCutter_3__FacePlaneList = face_planes_list[0]
                self.BlockCutter_3__Corner0Planes = corner0_planes_list[0]
                self.BlockCutter_3__LocalAxesPlane = local_axes_planes[0]
                self.BlockCutter_3__AxisX = axis_x_list[0]
                self.BlockCutter_3__AxisY = axis_y_list[0]
                self.BlockCutter_3__AxisZ = axis_z_list[0]
                self.BlockCutter_3__FaceDirTags = face_tags_list[0]
                self.BlockCutter_3__EdgeDirTags = edge_tags_list[0]
                self.BlockCutter_3__Corner0EdgeDirs = corner0_dirs_list[0]
                self.BlockCutter_3__Log = logs_all[0]
            else:
                self.BlockCutter_3__TimberBrep = timber_breps
                self.BlockCutter_3__FaceList = faces_list
                self.BlockCutter_3__PointList = points_list
                self.BlockCutter_3__EdgeList = edges_list
                self.BlockCutter_3__CenterPoint = center_pts
                self.BlockCutter_3__CenterAxisLines = center_axes_list
                self.BlockCutter_3__EdgeMidPoints = edge_midpts_list
                self.BlockCutter_3__FacePlaneList = face_planes_list
                self.BlockCutter_3__Corner0Planes = corner0_planes_list
                self.BlockCutter_3__LocalAxesPlane = local_axes_planes
                self.BlockCutter_3__AxisX = axis_x_list
                self.BlockCutter_3__AxisY = axis_y_list
                self.BlockCutter_3__AxisZ = axis_z_list
                self.BlockCutter_3__FaceDirTags = face_tags_list
                self.BlockCutter_3__EdgeDirTags = edge_tags_list
                self.BlockCutter_3__Corner0EdgeDirs = corner0_dirs_list
                self.BlockCutter_3__Log = logs_all

            self.Log.append("[BlockCutter::3] OK (n={})".format(n))

        except Exception as e:
            self.BlockCutter_3__TimberBrep = None
            self.BlockCutter_3__FaceList = []
            self.BlockCutter_3__PointList = []
            self.BlockCutter_3__EdgeList = []
            self.BlockCutter_3__CenterPoint = None
            self.BlockCutter_3__CenterAxisLines = []
            self.BlockCutter_3__EdgeMidPoints = []
            self.BlockCutter_3__FacePlaneList = []
            self.BlockCutter_3__Corner0Planes = []
            self.BlockCutter_3__LocalAxesPlane = None
            self.BlockCutter_3__AxisX = None
            self.BlockCutter_3__AxisY = None
            self.BlockCutter_3__AxisZ = None
            self.BlockCutter_3__FaceDirTags = []
            self.BlockCutter_3__EdgeDirTags = []
            self.BlockCutter_3__Corner0EdgeDirs = []
            self.BlockCutter_3__Log = ["错误: {}".format(e)]
            self.Log.append("[BlockCutter::3] ERROR: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 6.2：AlignToolToTimber::5（对位 BlockCutter::3 到 Timber_block_uniform）
    # 组件约定：
    #   Geo        = BlockCutter::3.TimberBrep
    #   SourcePlane= BlockCutter::3.FacePlaneList[idx]
    #   TargetPlane= Timber_block_uniform.FacePlaneList[idx]
    # ------------------------------------------------------
    def step6_2_align_tool_to_timber_5(self):
        Geo = self.BlockCutter_3__TimberBrep
        src_faceplanes = self.BlockCutter_3__FacePlaneList if self.BlockCutter_3__FacePlaneList else []
        tgt_faceplanes = self.FacePlaneList if self.FacePlaneList else []  # Timber_block_uniform 的 FacePlaneList

        SourcePlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_5__SourcePlane", 0)
        TargetPlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_5__TargetPlane", 0)

        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_5__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_5__FlipX", False)
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_5__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_5__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_5__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_5__MoveY", 0.0)
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_5__MoveZ", 0.0)

        def _pick_plane(plane_list, idx):
            if not plane_list:
                return None
            try:
                ii = int(idx)
            except:
                ii = 0
            ii = ii % len(plane_list)
            return plane_list[ii]

        try:
            geo_list = flatten_list(Geo) if isinstance(Geo, (list, tuple)) else _as_list(Geo)
            if not geo_list:
                geo_list = [Geo]

            sp_idx_list = _as_list(SourcePlaneIndex) or [0]
            tp_idx_list = _as_list(TargetPlaneIndex) or [0]

            rd_list = _as_list(RotateDeg) or [0.0]
            fx_list = [_to_bool(v, False) for v in (_as_list(FlipX) or [False])]
            fy_list = [_to_bool(v, False) for v in (_as_list(FlipY) or [False])]
            fz_list = [_to_bool(v, False) for v in (_as_list(FlipZ) or [False])]
            mx_list = _as_list(MoveX) or [0.0]
            my_list = _as_list(MoveY) or [0.0]
            mz_list = _as_list(MoveZ) or [0.0]

            n = max(len(geo_list), len(sp_idx_list), len(tp_idx_list), len(rd_list),
                    len(fx_list), len(fy_list), len(fz_list),
                    len(mx_list), len(my_list), len(mz_list), 1)

            geo_list = _broadcast_to_len(geo_list, n)
            sp_idx_list = _broadcast_to_len(sp_idx_list, n)
            tp_idx_list = _broadcast_to_len(tp_idx_list, n)
            rd_list = _broadcast_to_len(rd_list, n)
            fx_list = _broadcast_to_len(fx_list, n)
            fy_list = _broadcast_to_len(fy_list, n)
            fz_list = _broadcast_to_len(fz_list, n)
            mx_list = _broadcast_to_len(mx_list, n)
            my_list = _broadcast_to_len(my_list, n)
            mz_list = _broadcast_to_len(mz_list, n)

            source_out = []
            target_out = []
            xfm_out = []
            moved_geo = []

            for i in range(n):
                sp = _pick_plane(src_faceplanes, sp_idx_list[i])
                tp = _pick_plane(tgt_faceplanes, tp_idx_list[i])

                so, to, xfm, mg = GeoAligner_xfm.align(
                    geo_list[i],
                    sp,
                    tp,
                    rotate_deg=rd_list[i],
                    flip_x=fx_list[i],
                    flip_y=fy_list[i],
                    flip_z=fz_list[i],
                    move_x=mx_list[i],
                    move_y=my_list[i],
                    move_z=mz_list[i],
                )
                source_out.append(so)
                target_out.append(to)
                xfm_out.append(xfm)
                moved_geo.append(mg)

            self.AlignToolToTimber_5__SourceOut = source_out[0] if n == 1 else source_out
            self.AlignToolToTimber_5__TargetOut = target_out[0] if n == 1 else target_out
            self.AlignToolToTimber_5__TransformOut = (
                ght.GH_Transform(xfm_out[0]) if (n == 1 and xfm_out[0] is not None) else
                [ght.GH_Transform(x) if x is not None else None for x in xfm_out])
            self.AlignToolToTimber_5__MovedGeo = moved_geo[0] if n == 1 else flatten_list(moved_geo)

            self.Log.append("[AlignToolToTimber::5] OK (n={})".format(n))

        except Exception as e:
            self.AlignToolToTimber_5__SourceOut = None
            self.AlignToolToTimber_5__TargetOut = None
            self.AlignToolToTimber_5__TransformOut = None
            self.AlignToolToTimber_5__MovedGeo = None
            self.Log.append("[AlignToolToTimber::5] ERROR: {}".format(e))

        return self

    # ------------------------------------------------------
    # Step 7：壁内慢栱和闇栔切削准备（BlockCutter::4 + AlignToolToTimber::6）
    # ------------------------------------------------------
    # BlockCutter::4
    #   length_fen / width_fen / height_fen 允许为 list（长度 n），输出 TimberBrep 为 n 个 Brep 列表
    # ------------------------------------------------------
    def step7_1_blockcutter_4(self):
        try:
            length_fen = get_input_or_db(self.AllDict, "BlockCutter_4__length_fen", 32.0)
            width_fen = get_input_or_db(self.AllDict, "BlockCutter_4__width_fen", 32.0)
            height_fen = get_input_or_db(self.AllDict, "BlockCutter_4__height_fen", 20.0)

            # base_point 默认为原点
            base_point = get_input_or_db(self.AllDict, "BlockCutter_4__base_point", None)
            base_point = _to_point3d(base_point, rg.Point3d(0.0, 0.0, 0.0))

            reference_plane = get_input_or_db(self.AllDict, "BlockCutter_4__reference_plane", None)
            rp = _to_plane(reference_plane)

            # 将三组参数统一为 list，并按最大长度 n 进行广播
            Ls = _as_list(length_fen) or [32.0]
            Ws = _as_list(width_fen) or [32.0]
            Hs = _as_list(height_fen) or [20.0]

            n = max(len(Ls), len(Ws), len(Hs))
            if n <= 0:
                n = 1

            def _bcast(seq, n_, default_val):
                seq = _as_list(seq) or [default_val]
                if len(seq) == 1 and n_ > 1:
                    return [seq[0]] * n_
                if len(seq) < n_:
                    # 末尾重复
                    return [seq[i % len(seq)] for i in range(n_)]
                return seq[:n_]

            Ls = _bcast(Ls, n, 32.0)
            Ws = _bcast(Ws, n, 32.0)
            Hs = _bcast(Hs, n, 20.0)

            timber_breps = []
            face_lists = []
            point_lists = []
            edge_lists = []
            center_pts = []
            center_axes_lists = []
            edge_midpts_lists = []
            face_plane_lists = []
            corner0_planes_lists = []
            local_axes_planes = []
            axis_x_list = []
            axis_y_list = []
            axis_z_list = []
            face_tags_lists = []
            edge_tags_lists = []
            corner0_dirs_lists = []
            log_all = []

            for i in range(n):
                (
                    timber_brep,
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
                    log_lines,
                ) = build_timber_block_uniform(
                    float(Ls[i]),
                    float(Ws[i]),
                    float(Hs[i]),
                    base_point,
                    rp,
                )

                timber_breps.append(timber_brep)
                face_lists.append(faces)
                point_lists.append(points)
                edge_lists.append(edges)
                center_pts.append(center_pt)
                center_axes_lists.append(center_axes)
                edge_midpts_lists.append(edge_midpts)
                face_plane_lists.append(face_planes)
                corner0_planes_lists.append(corner0_planes)
                local_axes_planes.append(local_axes_plane)
                axis_x_list.append(axis_x)
                axis_y_list.append(axis_y)
                axis_z_list.append(axis_z)
                face_tags_lists.append(face_tags)
                edge_tags_lists.append(edge_tags)
                corner0_dirs_lists.append(corner0_dirs)
                log_all.append(log_lines)

            # 输出（与 BlockCutter::4 组件一致：TimberBrep 为列表）
            self.BlockCutter_4__TimberBrep = timber_breps
            self.BlockCutter_4__FaceList = face_lists
            self.BlockCutter_4__PointList = point_lists
            self.BlockCutter_4__EdgeList = edge_lists
            self.BlockCutter_4__CenterPoint = center_pts
            self.BlockCutter_4__CenterAxisLines = center_axes_lists
            self.BlockCutter_4__EdgeMidPoints = edge_midpts_lists
            self.BlockCutter_4__FacePlaneList = face_plane_lists
            self.BlockCutter_4__Corner0Planes = corner0_planes_lists
            self.BlockCutter_4__LocalAxesPlane = local_axes_planes
            self.BlockCutter_4__AxisX = axis_x_list
            self.BlockCutter_4__AxisY = axis_y_list
            self.BlockCutter_4__AxisZ = axis_z_list
            self.BlockCutter_4__FaceDirTags = face_tags_lists
            self.BlockCutter_4__EdgeDirTags = edge_tags_lists
            self.BlockCutter_4__Corner0EdgeDirs = corner0_dirs_lists
            self.BlockCutter_4__Log = log_all

            self.Log.append("[BlockCutter::4] OK (n={})".format(n))

        except Exception as e:
            self.BlockCutter_4__TimberBrep = None
            self.BlockCutter_4__FaceList = []
            self.BlockCutter_4__PointList = []
            self.BlockCutter_4__EdgeList = []
            self.BlockCutter_4__CenterPoint = None
            self.BlockCutter_4__CenterAxisLines = []
            self.BlockCutter_4__EdgeMidPoints = []
            self.BlockCutter_4__FacePlaneList = []
            self.BlockCutter_4__Corner0Planes = []
            self.BlockCutter_4__LocalAxesPlane = None
            self.BlockCutter_4__AxisX = None
            self.BlockCutter_4__AxisY = None
            self.BlockCutter_4__AxisZ = None
            self.BlockCutter_4__FaceDirTags = []
            self.BlockCutter_4__EdgeDirTags = []
            self.BlockCutter_4__Corner0EdgeDirs = []
            self.BlockCutter_4__Log = ["错误: {}".format(e)]
            self.Log.append("[BlockCutter::4] ERROR: {}".format(e))

        return self

    # ------------------------------------------------------
    # AlignToolToTimber::6
    #   Geo: BlockCutter::4.TimberBrep（通常为 2 个对象的 Tree：每分支 1 个）
    #   SourcePlane: BlockCutter::4.FacePlaneList（Tree：每分支对应 Geo 分支）
    #   TargetPlane: Timber_block_uniform.FacePlaneList（需广播对齐）
    #   MoveY: list（通常 2 个值）—— 对每个分支执行 MoveY 序列，总共 2*2 = 4 次复制变换
    # ------------------------------------------------------
    def step7_2_align_tool_to_timber_6(self):
        Geo = self.BlockCutter_4__TimberBrep
        src_faceplanes_tree = self.BlockCutter_4__FacePlaneList if self.BlockCutter_4__FacePlaneList else []
        tgt_faceplanes = self.FacePlaneList if self.FacePlaneList else []  # Timber_block_uniform

        SourcePlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_6__SourcePlane", 0)
        TargetPlaneIndex = get_input_or_db(self.AllDict, "AlignToolToTimber_6__TargetPlane", 0)

        RotateDeg = get_input_or_db(self.AllDict, "AlignToolToTimber_6__RotateDeg", 0.0)
        FlipX = get_input_or_db(self.AllDict, "AlignToolToTimber_6__FlipX", False)
        FlipY = get_input_or_db(self.AllDict, "AlignToolToTimber_6__FlipY", False)
        FlipZ = get_input_or_db(self.AllDict, "AlignToolToTimber_6__FlipZ", False)
        MoveX = get_input_or_db(self.AllDict, "AlignToolToTimber_6__MoveX", 0.0)
        MoveY = get_input_or_db(self.AllDict, "AlignToolToTimber_6__MoveY", 0.0)
        MoveZ = get_input_or_db(self.AllDict, "AlignToolToTimber_6__MoveZ", 0.0)

        def _pick_plane(plane_list, idx_):
            if not plane_list:
                return None
            try:
                ii = int(idx_)
            except Exception:
                ii = 0
            ii = ii % len(plane_list)
            return plane_list[ii]

        try:
            # 1) Geo -> branches（每分支 1 个）
            geo_branches = tree_to_branches(Geo)
            branch_count = len(geo_branches)

            if branch_count == 0:
                # 兼容：空输入
                self.AlignToolToTimber_6__SourceOut = None
                self.AlignToolToTimber_6__TargetOut = None
                self.AlignToolToTimber_6__TransformOut = None
                self.AlignToolToTimber_6__MovedGeo = None
                self.AlignToolToTimber_6__MovedGeoTree = []
                self.Log.append("[AlignToolToTimber::6] SKIP (empty Geo)")
                return self

            # 2) SourcePlaneIndex / TargetPlaneIndex -> per branch（广播）
            def _idx_per_branch(idx_param):
                # idx_param 允许 scalar / list / tree
                if _is_tree(idx_param):
                    b = tree_to_branches(idx_param)
                    out = []
                    for i in range(branch_count):
                        if i < len(b) and b[i]:
                            out.append(b[i][0])
                        else:
                            out.append(0)
                    return out
                seq = _as_list(idx_param)
                if not seq:
                    return [0] * branch_count
                if len(seq) == 1 and branch_count > 1:
                    return [seq[0]] * branch_count
                if len(seq) < branch_count:
                    return [seq[i % len(seq)] for i in range(branch_count)]
                return seq[:branch_count]

            sp_idx_b = _idx_per_branch(SourcePlaneIndex)
            tp_idx_b = _idx_per_branch(TargetPlaneIndex)

            # 3) per-branch parameters（MoveY 需要支持 “每分支一组值” 或 “全局一组值”）
            def _param_to_branch_lists(param, default_val):
                if _is_tree(param):
                    br = tree_to_branches(param)
                    out = []
                    for i in range(branch_count):
                        if i < len(br) and br[i]:
                            out.append([br[i][j] for j in range(len(br[i]))])
                        else:
                            out.append([default_val])
                    return out
                seq = _as_list(param)
                if not seq:
                    seq = [default_val]
                # 注意：非 Tree 情况下，默认对每个分支都应用同一组 seq
                return [list(seq) for _ in range(branch_count)]

            rd_b = _param_to_branch_lists(RotateDeg, 0.0)
            fx_b = _param_to_branch_lists(FlipX, False)
            fy_b = _param_to_branch_lists(FlipY, False)
            fz_b = _param_to_branch_lists(FlipZ, False)
            mx_b = _param_to_branch_lists(MoveX, 0.0)
            my_b = _param_to_branch_lists(MoveY, 0.0)
            mz_b = _param_to_branch_lists(MoveZ, 0.0)

            moved_tree = []
            source_out_tree = []
            target_out_tree = []
            xfm_out_tree = []

            # 4) 对每个分支执行序列变换（通常 MoveY 有 2 个值）
            for bi in range(branch_count):
                geo_item = geo_branches[bi][0] if geo_branches[bi] else None

                # SourcePlane：来自 BlockCutter::4.FacePlaneList[bi][idx]
                sp_list = None
                if isinstance(src_faceplanes_tree, (list, tuple)) and bi < len(src_faceplanes_tree):
                    sp_list = src_faceplanes_tree[bi]
                sp = _pick_plane(sp_list, sp_idx_b[bi])

                # TargetPlane：来自 Timber_block_uniform.FacePlaneList[idx]（广播）
                tp = _pick_plane(tgt_faceplanes, tp_idx_b[bi])

                # 每分支的 op 次数：取该分支所有参数序列的 max 长度
                lens = [
                    len(rd_b[bi]), len(fx_b[bi]), len(fy_b[bi]), len(fz_b[bi]),
                    len(mx_b[bi]), len(my_b[bi]), len(mz_b[bi]),
                ]
                op_n = max(lens) if lens else 1
                if op_n <= 0:
                    op_n = 1

                def _pick(seq, j, default_val):
                    if not seq:
                        return default_val
                    return seq[j] if j < len(seq) else seq[-1]

                moved_ops = []
                sp_ops = []
                tp_ops = []
                xfm_ops = []

                for j in range(op_n):
                    rd = float(_pick(rd_b[bi], j, 0.0))
                    fx = _to_bool(_pick(fx_b[bi], j, False), False)
                    fy = _to_bool(_pick(fy_b[bi], j, False), False)
                    fz = _to_bool(_pick(fz_b[bi], j, False), False)
                    mx = float(_pick(mx_b[bi], j, 0.0))
                    my = float(_pick(my_b[bi], j, 0.0))
                    mz = float(_pick(mz_b[bi], j, 0.0))

                    so, to, xfm, mg = GeoAligner_xfm.align(
                        geo_item,
                        sp,
                        tp,
                        rotate_deg=rd,
                        flip_x=fx,
                        flip_y=fy,
                        flip_z=fz,
                        move_x=mx,
                        move_y=my,
                        move_z=mz,
                    )

                    # GeoAligner_xfm.align 在 GH 环境下可能返回：
                    #   - 单个几何
                    #   - 或被包装/嵌套的 list（导致输出端显示 System.Collections.Generic.List`1[System.Object]）
                    # 这里对每次操作的结果做“深度拍平”，再写入每个分支。
                    mg_flat = flatten_list(mg)
                    if len(mg_flat) == 0:
                        moved_ops.append(None)
                    elif len(mg_flat) == 1:
                        moved_ops.append(mg_flat[0])
                    else:
                        moved_ops.extend(mg_flat)

                    # SourceOut / TargetOut 也做同样处理（通常是 Plane，但兼容 list 输出）
                    so_flat = flatten_list(so)
                    to_flat = flatten_list(to)
                    xfm_flat = flatten_list(xfm)

                    sp_ops.append(so_flat[0] if len(so_flat) == 1 else (so_flat if so_flat else None))
                    tp_ops.append(to_flat[0] if len(to_flat) == 1 else (to_flat if to_flat else None))
                    xfm_ops.append(xfm_flat[0] if len(xfm_flat) == 1 else (xfm_flat if xfm_flat else None))

                moved_tree.append(moved_ops)
                source_out_tree.append(sp_ops)
                target_out_tree.append(tp_ops)
                xfm_out_tree.append(xfm_ops)

            # 输出：
            # - MovedGeoTree: [[...],[...]]
            # - MovedGeo: flatten
            # MovedGeoTree：为了避免下游出现 System.Collections.Generic.List`1[System.Object]，这里直接输出深度拍平后的 list。
            # 如需保留 GH DataTree 结构，可使用 AlignToolToTimber_6__MovedGeoDataTree。
            self.AlignToolToTimber_6__MovedGeoDataTree = _to_datatree(moved_tree)
            self.AlignToolToTimber_6__MovedGeoTree = flatten_list(moved_tree)
            self.AlignToolToTimber_6__MovedGeo = self.AlignToolToTimber_6__MovedGeoTree

            self.AlignToolToTimber_6__SourceOut = source_out_tree
            self.AlignToolToTimber_6__TargetOut = target_out_tree
            self.AlignToolToTimber_6__TransformOut = [[ght.GH_Transform(x) if x is not None else None for x in branch]
                                                      for branch in xfm_out_tree]

            self.Log.append("[AlignToolToTimber::6] OK (branches={}, total={})".format(branch_count,
                                                                                       len(self.AlignToolToTimber_6__MovedGeo)))

        except Exception as e:
            self.AlignToolToTimber_6__SourceOut = None
            self.AlignToolToTimber_6__TargetOut = None
            self.AlignToolToTimber_6__TransformOut = None
            self.AlignToolToTimber_6__MovedGeo = None
            self.AlignToolToTimber_6__MovedGeoTree = []
            self.Log.append("[AlignToolToTimber::6] ERROR: {}".format(e))

        return self

    # =========================================================
    # Step 8：刀具切割木料（CutTimbersByTools_V3）
    # =========================================================
    def step8_cut_timbers_by_tools_v3(self):
        """
        CutTimbersByTools_V3 组件逻辑：用多个刀具对 Timber_block_uniform 进行 GH Solid Difference 裁切。
        - Timbers: Timber_block_uniform.TimberBrep
        - Tools  : AlignToolToTimber::1/2/3/4/5/6 的 MovedGeo（深度拍平）
        """
        try:
            from yingzao.ancientArchi import FT_CutTimbersByTools_GH_SolidDifference
        except Exception as e:
            self.Log.append("[CutTimbersByTools_V3] ERROR: {}".format(e))
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        timbers = self.TimberBrep
        tools = flatten_list([
            getattr(self, "AlignToolToTimber_1__MovedGeo", None),
            getattr(self, "AlignToolToTimber_2__MovedGeo", None),
            getattr(self, "AlignToolToTimber_3__MovedGeo", None),
            getattr(self, "AlignToolToTimber_4__MovedGeo", None),
            getattr(self, "AlignToolToTimber_5__MovedGeo", None),
            getattr(self, "AlignToolToTimber_6__MovedGeo", None),
        ])

        # 兼容：某些 MovedGeo 可能仍是 tree/list 嵌套，这里再次深度拍平
        tools = flatten_list(tools)

        if timbers is None:
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[CutTimbersByTools_V3] SKIP (Timbers is None)")
            return self

        if not tools:
            # 没有刀具时，按 GH 习惯直接输出原木料
            self.CutTimbers = flatten_list([timbers])
            self.FailTimbers = []
            self.Log.append("[CutTimbersByTools_V3] SKIP (empty Tools) -> passthrough timbers")
            return self

        keep_inside = get_input_or_db(self.AllDict, "CutTimbersByTools_V3__KeepInside", False)
        debug_flag = get_input_or_db(self.AllDict, "CutTimbersByTools_V3__Debug", False)

        cutter = FT_CutTimbersByTools_GH_SolidDifference(debug=bool(debug_flag))
        try:
            CutTimbers, FailTimbers, LogLines = cutter.cut(
                timbers=timbers,
                tools=tools,
                keep_inside=bool(keep_inside),
                debug=debug_flag,
            )
            self.CutTimbers = flatten_list(CutTimbers)
            self.FailTimbers = flatten_list(FailTimbers)
            # cutter.cut 的 Log 可能为 None/str/list
            if LogLines is None:
                self.Log.append(
                    "[CutTimbersByTools_V3] OK: CutTimbers={}, FailTimbers={} (no log)".format(len(self.CutTimbers),
                                                                                               len(self.FailTimbers)))
            else:
                for ln in flatten_list(LogLines):
                    self.Log.append("[CutTimbersByTools_V3] {}".format(ln))
                self.Log.append("[CutTimbersByTools_V3] OK: CutTimbers={}, FailTimbers={}".format(len(self.CutTimbers),
                                                                                                  len(self.FailTimbers)))
        except Exception as e:
            self.CutTimbers = []
            self.FailTimbers = []
            self.Log.append("[CutTimbersByTools_V3] ERROR: {}".format(e))
        return self

    def run(self):
        self.step1_read_db()

        if not self.All:
            self.Log.append("[RUN] All 为空，后续步骤跳过。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        self.step2_timber()

        if self.TimberBrep is None:
            self.Log.append("[RUN] TimberBrep 为空，后续步骤跳过。")
            self.CutTimbers = []
            self.FailTimbers = []
            return self

        # Step 3：耍头刀具（若你前面步骤仍在用，可保留）
        self.step3_1_shuatou_tool()
        self.step3_2_plane_from_lists()
        self.step3_3_align_tool_to_timber()

        # Step 4：欹䫜刀具
        self.step4_1_qiao_tool()
        self.step4_2_plane_from_lists_2()
        self.step4_3_plane_from_lists_3()
        self.step4_4_align_tool_to_timber_2()

        # Step 5：散枓令栱切削块刀具（BlockCutter::1）+ 对位（AlignToolToTimber::3）
        self.step5_1_blockcutter_1()
        self.step5_2_plane_from_lists_4()
        self.step5_3_align_tool_to_timber_3()

        # Step 5：单令栱切削块刀具（BlockCutter::2）+ 对位（AlignToolToTimber::4）
        self.step5_4_blockcutter_2()
        self.step5_5_align_tool_to_timber_4()
        # Step 6: 泥道栱切削部分（BlockCutter::3 + AlignToolToTimber::5）
        self.step6_1_blockcutter_3()
        self.step6_2_align_tool_to_timber_5()

        # Step 7: 壁内慢栱和闇栔切削部分（BlockCutter::4 + AlignToolToTimber::6）
        self.step7_1_blockcutter_4()
        self.step7_2_align_tool_to_timber_6()

        # Step 8: 刀具切割木料（CutTimbersByTools_V3）
        self.step8_cut_timbers_by_tools_v3()

        self.Log.append("[RUN] 当前 Step1-8 完成：已生成并对位全部刀具，并对原木料执行切削。")

        return self


# GH Python 组件输出绑定区（developer-friendly）
# ==============================================================
if __name__ == "__main__":
    solver = ShuaTou_4PU_INOUT_1ChaoJuantouSolver(DBPath, base_point, Refresh, ghenv)
    solver = solver.run()

    # --- 最终主输出 ---
    CutTimbers = solver.CutTimbers
    FailTimbers = solver.FailTimbers
    Log = solver.Log

    # --- 开发模式输出：DB ---
    Value = solver.Value
    All = solver.All
    AllDict = solver.AllDict
    DBLog = solver.DBLog

    # --- 开发模式输出：Timber_block_uniform ---
    TimberBrep = solver.TimberBrep
    FaceList = solver.FaceList
    PointList = solver.PointList
    EdgeList = solver.EdgeList
    CenterPoint = solver.CenterPoint
    CenterAxisLines = solver.CenterAxisLines
    EdgeMidPoints = solver.EdgeMidPoints
    FacePlaneList = solver.FacePlaneList
    Corner0Planes = solver.Corner0Planes
    LocalAxesPlane = solver.LocalAxesPlane
    AxisX = solver.AxisX
    AxisY = solver.AxisY
    AxisZ = solver.AxisZ
    FaceDirTags = solver.FaceDirTags
    EdgeDirTags = solver.EdgeDirTags
    Corner0EdgeDirs = solver.Corner0EdgeDirs
    TimberLog = solver.TimberLog

    # --- 开发模式输出：Step 3 / ShuaTou ---
    ShuaTou__CenterSectionCrv = solver.ShuaTou__CenterSectionCrv
    ShuaTou__SideSectionCrv = solver.ShuaTou__SideSectionCrv
    ShuaTou__CenterSectionFace = solver.ShuaTou__CenterSectionFace
    ShuaTou__SideSectionFace = solver.ShuaTou__SideSectionFace
    ShuaTou__OffsetSideFaces = solver.ShuaTou__OffsetSideFaces
    ShuaTou__OffsetSideCrvs = solver.ShuaTou__OffsetSideCrvs
    ShuaTou__SideLoftFace = solver.ShuaTou__SideLoftFace
    ShuaTou__ToolBrep = solver.ShuaTou__ToolBrep
    ShuaTou__RefPlanes = solver.ShuaTou__RefPlanes
    ShuaTou__DebugPoints = solver.ShuaTou__DebugPoints
    ShuaTou__DebugLines = solver.ShuaTou__DebugLines
    ShuaTou__Log = solver.ShuaTou__Log

    # --- 开发模式输出：Step 3 / PlaneFromLists::1 ---
    PlaneFromLists_1__BasePlane = solver.PlaneFromLists_1__BasePlane
    PlaneFromLists_1__OriginPoint = solver.PlaneFromLists_1__OriginPoint
    PlaneFromLists_1__ResultPlane = solver.PlaneFromLists_1__ResultPlane
    PlaneFromLists_1__Log = solver.PlaneFromLists_1__Log

    # --- 开发模式输出：Step 3 / AlignToolToTimber::1 ---
    AlignToolToTimber_1__SourceOut = solver.AlignToolToTimber_1__SourceOut
    AlignToolToTimber_1__TargetOut = solver.AlignToolToTimber_1__TargetOut
    AlignToolToTimber_1__TransformOut = solver.AlignToolToTimber_1__TransformOut
    AlignToolToTimber_1__MovedGeo = solver.AlignToolToTimber_1__MovedGeo

    # --- 开发模式输出：Step 4 / QiAOTool（欹䫜） ---
    QiAOTool__CutTimbers = solver.QiAOTool__CutTimbers
    QiAOTool__FailTimbers = solver.QiAOTool__FailTimbers
    QiAOTool__Log = solver.QiAOTool__Log

    QiAOTool__TimberBrep = solver.QiAOTool__TimberBrep
    QiAOTool__ToolBrep = solver.QiAOTool__ToolBrep
    QiAOTool__AlignedTool = solver.QiAOTool__AlignedTool
    QiAOTool__FaceList = solver.QiAOTool__FaceList
    QiAOTool__PointList = solver.QiAOTool__PointList
    QiAOTool__EdgeList = solver.QiAOTool__EdgeList
    QiAOTool__CenterPoint = solver.QiAOTool__CenterPoint
    QiAOTool__CenterAxisLines = solver.QiAOTool__CenterAxisLines
    QiAOTool__EdgeMidPoints = solver.QiAOTool__EdgeMidPoints
    QiAOTool__FacePlaneList = solver.QiAOTool__FacePlaneList
    QiAOTool__Corner0Planes = solver.QiAOTool__Corner0Planes
    QiAOTool__LocalAxesPlane = solver.QiAOTool__LocalAxesPlane
    QiAOTool__AxisX = solver.QiAOTool__AxisX
    QiAOTool__AxisY = solver.QiAOTool__AxisY
    QiAOTool__AxisZ = solver.QiAOTool__AxisZ
    QiAOTool__FaceDirTags = solver.QiAOTool__FaceDirTags
    QiAOTool__EdgeDirTags = solver.QiAOTool__EdgeDirTags
    QiAOTool__Corner0EdgeDirs = solver.QiAOTool__Corner0EdgeDirs

    # --- 开发模式输出：Step 4 / PlaneFromLists::2 & ::3 ---
    PlaneFromLists_2__BasePlane = solver.PlaneFromLists_2__BasePlane
    PlaneFromLists_2__OriginPoint = solver.PlaneFromLists_2__OriginPoint
    PlaneFromLists_2__ResultPlane = solver.PlaneFromLists_2__ResultPlane
    PlaneFromLists_2__Log = solver.PlaneFromLists_2__Log

    PlaneFromLists_3__BasePlane = solver.PlaneFromLists_3__BasePlane
    PlaneFromLists_3__OriginPoint = solver.PlaneFromLists_3__OriginPoint
    PlaneFromLists_3__ResultPlane = solver.PlaneFromLists_3__ResultPlane
    PlaneFromLists_3__Log = solver.PlaneFromLists_3__Log

    # --- 开发模式输出：Step 4 / AlignToolToTimber::2 ---
    AlignToolToTimber_2__SourceOut = solver.AlignToolToTimber_2__SourceOut
    AlignToolToTimber_2__TargetOut = solver.AlignToolToTimber_2__TargetOut
    AlignToolToTimber_2__TransformOut = solver.AlignToolToTimber_2__TransformOut
    AlignToolToTimber_2__MovedGeo = solver.AlignToolToTimber_2__MovedGeo

    # --- 开发模式输出：Step 5 / BlockCutter::1 ---
    BlockCutter_1__TimberBrep = solver.BlockCutter_1__TimberBrep
    BlockCutter_1__FaceList = solver.BlockCutter_1__FaceList
    BlockCutter_1__PointList = solver.BlockCutter_1__PointList
    BlockCutter_1__EdgeList = solver.BlockCutter_1__EdgeList
    BlockCutter_1__CenterPoint = solver.BlockCutter_1__CenterPoint
    BlockCutter_1__CenterAxisLines = solver.BlockCutter_1__CenterAxisLines
    BlockCutter_1__EdgeMidPoints = solver.BlockCutter_1__EdgeMidPoints
    BlockCutter_1__FacePlaneList = solver.BlockCutter_1__FacePlaneList
    BlockCutter_1__Corner0Planes = solver.BlockCutter_1__Corner0Planes
    BlockCutter_1__LocalAxesPlane = solver.BlockCutter_1__LocalAxesPlane
    BlockCutter_1__AxisX = solver.BlockCutter_1__AxisX
    BlockCutter_1__AxisY = solver.BlockCutter_1__AxisY
    BlockCutter_1__AxisZ = solver.BlockCutter_1__AxisZ
    BlockCutter_1__FaceDirTags = solver.BlockCutter_1__FaceDirTags
    BlockCutter_1__EdgeDirTags = solver.BlockCutter_1__EdgeDirTags
    BlockCutter_1__Corner0EdgeDirs = solver.BlockCutter_1__Corner0EdgeDirs
    BlockCutter_1__Log = solver.BlockCutter_1__Log

    # --- 开发模式输出：Step 5 / PlaneFromLists::4 ---
    PlaneFromLists_4__BasePlane = solver.PlaneFromLists_4__BasePlane
    PlaneFromLists_4__OriginPoint = solver.PlaneFromLists_4__OriginPoint
    PlaneFromLists_4__ResultPlane = solver.PlaneFromLists_4__ResultPlane
    PlaneFromLists_4__Log = solver.PlaneFromLists_4__Log

    # --- 开发模式输出：Step 5 / AlignToolToTimber::3 ---
    AlignToolToTimber_3__SourceOut = solver.AlignToolToTimber_3__SourceOut
    AlignToolToTimber_3__TargetOut = solver.AlignToolToTimber_3__TargetOut
    AlignToolToTimber_3__TransformOut = solver.AlignToolToTimber_3__TransformOut
    AlignToolToTimber_3__MovedGeo = solver.AlignToolToTimber_3__MovedGeo

    # --- 开发模式输出：Step 5 / BlockCutter::2 ---
    BlockCutter_2__TimberBrep = solver.BlockCutter_2__TimberBrep
    BlockCutter_2__FacePlaneList = solver.BlockCutter_2__FacePlaneList
    BlockCutter_2__EdgeMidPoints = solver.BlockCutter_2__EdgeMidPoints
    BlockCutter_2__Corner0Planes = solver.BlockCutter_2__Corner0Planes
    BlockCutter_2__Log = solver.BlockCutter_2__Log

    # --- 开发模式输出：Step 5 / AlignToolToTimber::4 ---
    AlignToolToTimber_4__SourceOut = solver.AlignToolToTimber_4__SourceOut
    AlignToolToTimber_4__TargetOut = solver.AlignToolToTimber_4__TargetOut
    AlignToolToTimber_4__TransformOut = solver.AlignToolToTimber_4__TransformOut
    AlignToolToTimber_4__MovedGeo = solver.AlignToolToTimber_4__MovedGeo

    # --- 开发模式输出：Step 6 / BlockCutter::3 ---
    BlockCutter_3__TimberBrep = solver.BlockCutter_3__TimberBrep
    BlockCutter_3__FacePlaneList = solver.BlockCutter_3__FacePlaneList
    BlockCutter_3__EdgeMidPoints = solver.BlockCutter_3__EdgeMidPoints
    BlockCutter_3__Corner0Planes = solver.BlockCutter_3__Corner0Planes
    BlockCutter_3__Log = solver.BlockCutter_3__Log

    # --- 开发模式输出：Step 6 / AlignToolToTimber::5 ---
    AlignToolToTimber_5__SourceOut = solver.AlignToolToTimber_5__SourceOut
    AlignToolToTimber_5__TargetOut = solver.AlignToolToTimber_5__TargetOut
    AlignToolToTimber_5__TransformOut = solver.AlignToolToTimber_5__TransformOut
    AlignToolToTimber_5__MovedGeo = solver.AlignToolToTimber_5__MovedGeo

    # --- 开发模式输出：Step 7 / BlockCutter::4 ---
    BlockCutter_4__TimberBrep = solver.BlockCutter_4__TimberBrep
    BlockCutter_4__FaceList = solver.BlockCutter_4__FaceList
    BlockCutter_4__PointList = solver.BlockCutter_4__PointList
    BlockCutter_4__EdgeList = solver.BlockCutter_4__EdgeList
    BlockCutter_4__CenterPoint = solver.BlockCutter_4__CenterPoint
    BlockCutter_4__CenterAxisLines = solver.BlockCutter_4__CenterAxisLines
    BlockCutter_4__EdgeMidPoints = solver.BlockCutter_4__EdgeMidPoints
    BlockCutter_4__FacePlaneList = solver.BlockCutter_4__FacePlaneList
    BlockCutter_4__Corner0Planes = solver.BlockCutter_4__Corner0Planes
    BlockCutter_4__LocalAxesPlane = solver.BlockCutter_4__LocalAxesPlane
    BlockCutter_4__AxisX = solver.BlockCutter_4__AxisX
    BlockCutter_4__AxisY = solver.BlockCutter_4__AxisY
    BlockCutter_4__AxisZ = solver.BlockCutter_4__AxisZ
    BlockCutter_4__FaceDirTags = solver.BlockCutter_4__FaceDirTags
    BlockCutter_4__EdgeDirTags = solver.BlockCutter_4__EdgeDirTags
    BlockCutter_4__Corner0EdgeDirs = solver.BlockCutter_4__Corner0EdgeDirs
    BlockCutter_4__Log = solver.BlockCutter_4__Log

    # --- 开发模式输出：Step 7 / AlignToolToTimber::6 ---
    AlignToolToTimber_6__SourceOut = solver.AlignToolToTimber_6__SourceOut
    AlignToolToTimber_6__TargetOut = solver.AlignToolToTimber_6__TargetOut
    AlignToolToTimber_6__TransformOut = solver.AlignToolToTimber_6__TransformOut
    AlignToolToTimber_6__MovedGeo = solver.AlignToolToTimber_6__MovedGeo
    AlignToolToTimber_6__MovedGeoTree = solver.AlignToolToTimber_6__MovedGeoTree
    AlignToolToTimber_6__MovedGeoDataTree = getattr(solver, 'AlignToolToTimber_6__MovedGeoDataTree', None)

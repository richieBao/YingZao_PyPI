# -*- coding: utf-8 -*-
import Grasshopper as gh

def setup_io(comp):
    """
    自动配置当前 GHPython 组件的输入 / 输出参数：
    - 名称 (Name)
    - 昵称 (NickName)
    - 描述 (Description)
    - 访问方式 (Access)
    """

    # ---------- 定义输入参数 ----------
    in_defs = [
        ("ToolGeo",          "刀具几何（Brep / Surface / Extrusion）",
         gh.Kernel.GH_ParamAccess.item),

        ("ToolBasePlane",    "刀具基准平面（Plane），其 Z 轴为刀具“加工方向”",
         gh.Kernel.GH_ParamAccess.item),

        ("ToolContactPoint", "刀具接触点（Point3d），将贴合到木料上的点",
         gh.Kernel.GH_ParamAccess.item),

        ("BlockGeo",         "木料 Brep（FT_timber_block 输出）",
         gh.Kernel.GH_ParamAccess.item),

        ("BlockFacePlane",   "目标木料面平面（Plane）",
         gh.Kernel.GH_ParamAccess.item),

        ("BlockTargetPoint", "木料上的目标点（Point3d），如该面中心或某边中点",
         gh.Kernel.GH_ParamAccess.item),

        ("Mode",             "对位模式字符串: \"plane_to_plane\" / \"point_plane\" / \"point_only\"",
         gh.Kernel.GH_ParamAccess.item),

        ("DepthOffset",      "沿 BlockFacePlane 法向的插入深度（double）",
         gh.Kernel.GH_ParamAccess.item),

        ("FlipDirection",    "是否翻转目标平面法向（bool）",
         gh.Kernel.GH_ParamAccess.item),

        ("Run",              "是否执行（bool）",
         gh.Kernel.GH_ParamAccess.item),
    ]

    # ---------- 定义输出参数 ----------
    out_defs = [
        ("AlignedTool", "对位后的刀具 Brep",
         gh.Kernel.GH_ParamAccess.item),

        ("XForm",       "总变换矩阵（Transform）",
         gh.Kernel.GH_ParamAccess.item),

        ("SourcePlane", "源平面（刀具基准平面）",
         gh.Kernel.GH_ParamAccess.item),

        ("TargetPlane", "实际用于对位的目标平面（已考虑 FlipDirection）",
         gh.Kernel.GH_ParamAccess.item),

        ("SourcePoint", "源点（刀具接触点，经必要的平面变换前）",
         gh.Kernel.GH_ParamAccess.item),

        ("TargetPoint", "目标点（BlockTargetPoint 加上 DepthOffset 后）",
         gh.Kernel.GH_ParamAccess.item),

        ("DebugInfo",   "调试信息字符串",
         gh.Kernel.GH_ParamAccess.item),
    ]

    # ---------- 应用到输入 ----------
    for i, (name, desc, access) in enumerate(in_defs):
        if i >= comp.Params.Input.Count:
            break  # 当前输入插口不够，就先不设
        p = comp.Params.Input[i]
        p.Name = name
        p.NickName = name
        p.Description = desc
        p.Access = access

    # ---------- 应用到输出 ----------
    for i, (name, desc, access) in enumerate(out_defs):
        if i >= comp.Params.Output.Count:
            break
        p = comp.Params.Output[i]
        p.Name = name
        p.NickName = name
        p.Description = desc
        p.Access = access

# 在组件求值时自动执行一次
setup_io(ghenv.Component)

# 下面写你真正的对位逻辑代码即可，比如：
# ToolGeo, ToolBasePlane, ToolContactPoint, BlockGeo,
# BlockFacePlane, BlockTargetPoint, Mode, DepthOffset,
# FlipDirection, Run
# ↑ 这些名称已经被上面自动配置好


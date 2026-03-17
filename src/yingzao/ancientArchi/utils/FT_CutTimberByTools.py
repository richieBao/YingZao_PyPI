# -*- coding: utf-8 -*-
"""FT_CutTimberByTools

用对位后的刀具几何裁切木料几何。

输入（请在 GhPython 组件中对应设置名字）:
    Timbers    : list
        木料几何列表（推荐 Brep，亦可为 Extrusion / Surface / Mesh）
    Tools      : list
        刀具几何列表（推荐 Brep 或封闭 Extrusion / Mesh，已经完成对位）
    KeepInside : bool（新增）
        - False（默认）：保留木料“刀具外部”的部分（Difference）
        - True         ：保留木料“刀具内部”的部分（Intersection）

输出:
    CutTimbers : list[rg.Brep]
        裁切后的结果（按输入木料一一对应，可能一个输入对应多个 Brep）
    FailTimbers : list
        裁切失败的木料（保留原几何）
    Log : list[str]
        过程信息，用于调试
"""

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System
import traceback


class FT_CutTimberByTools(object):
    """封装全部裁切逻辑的类。"""

    # --------- 构造函数 ---------
    def __init__(self, timbers, tools, keep_inside=False, doc=None, tol=None):
        """
        keep_inside:
            - False: 使用 BooleanDifference (timber - tools)，保留刀具外部分。
            - True : 使用 BooleanIntersection (timber ∩ tools)，保留刀具内部分。
        """
        self._raw_timbers = timbers
        self._raw_tools = tools
        self.keep_inside = bool(keep_inside)
        self.doc = doc or sc.doc

        # 公差
        if tol is not None:
            self.tol = float(tol)
        else:
            self.tol = self.doc.ModelAbsoluteTolerance if self.doc else 0.001

        # 输出容器
        self.cut_timbers = []
        self.fail_timbers = []
        self.log = []
        self.log.append(u"模型公差: %.6f" % self.tol)
        self.log.append(u"KeepInside = %s" % self.keep_inside)

        # 预处理后的数据
        self.tool_breps = []
        self.union_tools = None

    # --------- 工具方法：类型转换 ---------
    @staticmethod
    def _to_brep(geo):
        """尽量将输入几何转成 Brep；失败则返回 None。"""
        if geo is None:
            return None

        if isinstance(geo, rg.Brep):
            return geo

        if isinstance(geo, rg.Extrusion):
            return geo.ToBrep()

        if isinstance(geo, rg.Surface):
            return rg.Brep.CreateFromSurface(geo)

        if isinstance(geo, rg.Mesh):
            breps = rg.Brep.CreateFromMesh(geo, True)
            if breps and len(breps) > 0:
                return breps[0]

        return None

    # --------- 工具方法：布尔运算封装 ---------
    def _boolean_union(self, breps):
        """对一组 Brep 尝试做一次 BooleanUnion。成功则返回 list[rg.Brep]，失败返回 None。"""
        if not breps:
            return None

        try:
            unioned = rg.Brep.CreateBooleanUnion(breps, self.tol)
            if not unioned or len(unioned) == 0:
                self.log.append(u"BooleanUnion 返回空。")
                return None
            return list(unioned)
        except Exception as e:
            self.log.append(u"BooleanUnion 异常: %s" % e)
            self.log.append(traceback.format_exc())
            return None

    def _boolean_difference(self, targets, cutters):
        """targets - cutters，参数都是 list[rg.Brep]。成功返回 list[rg.Brep]，失败返回 None。"""
        if not targets:
            return None
        if not cutters:
            # 没有刀具，相当于不裁切
            return targets

        try:
            res = rg.Brep.CreateBooleanDifference(targets, cutters, self.tol)
            if not res or len(res) == 0:
                self.log.append(u"BooleanDifference 返回空。")
                return None
            return list(res)
        except Exception as e:
            self.log.append(u"BooleanDifference 异常: %s" % e)
            self.log.append(traceback.format_exc())
            return None

    def _boolean_intersection(self, targets, cutters):
        """targets ∩ cutters，参数都是 list[rg.Brep]。成功返回 list[rg.Brep]，失败返回 None。"""
        if not targets:
            return None
        if not cutters:
            # 理论上不会在无刀具时调用；如调用则视为无交集
            self.log.append(u"BooleanIntersection 被调用但 cutters 为空。")
            return None

        try:
            res = rg.Brep.CreateBooleanIntersection(targets, cutters, self.tol)
            if not res or len(res) == 0:
                self.log.append(u"BooleanIntersection 返回空。")
                return None
            return list(res)
        except Exception as e:
            self.log.append(u"BooleanIntersection 异常: %s" % e)
            self.log.append(traceback.format_exc())
            return None

    # --------- 步骤 1：预处理刀具 ---------
    def _preprocess_tools(self):
        """把所有刀具转为 Brep，并尝试做一次 BooleanUnion。"""
        self.tool_breps = []

        tools = self._raw_tools
        if tools:
            # 确保是可迭代序列
            if not isinstance(tools, (list, tuple)):
                tools = [tools]

            self.log.append(u"输入刀具数量: %d" % len(tools))

            for i, geo in enumerate(tools):
                b = self._to_brep(geo)
                if b is None:
                    self.log.append(u"工具 #%d 无法转为 Brep，已忽略。" % i)
                    continue

                if b.IsSolid:
                    self.tool_breps.append(b)
                    self.log.append(u"工具 #%d 转为封闭 Brep。" % i)
                else:
                    self.log.append(
                        u"工具 #%d 不是封闭 Brep，仍尝试参与布尔运算。" % i
                    )
                    self.tool_breps.append(b)
        else:
            self.log.append(u"未提供刀具列表，所有木料将保持不变。")

        # 如果有有效刀具，先尝试 Union
        if self.tool_breps:
            self.union_tools = self._boolean_union(self.tool_breps)
            if self.union_tools is not None:
                self.log.append(
                    u"刀具 BooleanUnion 成功，数量：%d" % len(self.union_tools)
                )
            else:
                self.log.append(u"刀具 BooleanUnion 失败，将逐个刀具布尔运算。")
        else:
            self.log.append(u"没有有效的刀具 Brep。")
            self.union_tools = None

    # --------- 步骤 2：裁切所有木料 ---------
    def _cut_all_timbers(self):
        timbers = self._raw_timbers
        if not timbers:
            self.log.append(u"未提供木料列表。")
            return

        # 保证 timbers 是列表（GH 可能给单个对象）
        if not isinstance(timbers, (list, tuple)):
            timbers = [timbers]

        self.log.append(u"输入木料数量: %d" % len(timbers))

        for idx, geo in enumerate(timbers):
            # 转 Brep
            timber_brep = self._to_brep(geo)
            if timber_brep is None:
                self.log.append(u"木料 #%d 无法转为 Brep，跳过。" % idx)
                self.fail_timbers.append(geo)
                continue

            # 没刀具：直接保留（无论 keep_inside 与否）
            if not self.tool_breps:
                self.cut_timbers.append(timber_brep)
                if self.keep_inside:
                    self.log.append(u"木料 #%d：KeepInside=True 但无刀具，保留原件。" % idx)
                else:
                    self.log.append(u"木料 #%d：无刀具，直接保留原件。" % idx)
                continue

            current = [timber_brep]
            success = False

            # ------------ 模式分支：Difference / Intersection ------------
            if not self.keep_inside:
                # ====== 原逻辑：Difference，保留刀具外部 ======
                # 先尝试联合刀具
                if self.union_tools is not None:
                    res = self._boolean_difference(current, self.union_tools)
                    if res is not None:
                        self.cut_timbers.extend(res)
                        self.log.append(
                            u"木料 #%d：使用联合刀具差集裁切成功（得到 %d 个 Brep）。"
                            % (idx, len(res))
                        )
                        success = True
                    else:
                        self.log.append(
                            u"木料 #%d：联合刀具差集裁切失败，将尝试逐个刀具。" % idx
                        )

                # 联合失败则逐个刀具裁切
                if not success:
                    tmp = current
                    ok = True
                    for j, tb in enumerate(self.tool_breps):
                        r = self._boolean_difference(tmp, [tb])
                        if r is None:
                            self.log.append(
                                u"木料 #%d：在刀具 #%d 差集布尔失败，停止该木料的进一步裁切。"
                                % (idx, j)
                            )
                            ok = False
                            break
                        tmp = r

                    if ok and tmp:
                        self.cut_timbers.extend(tmp)
                        self.log.append(
                            u"木料 #%d：逐个刀具差集裁切成功（得到 %d 个 Brep）。"
                            % (idx, len(tmp))
                        )
                    else:
                        self.fail_timbers.append(geo)
                        self.log.append(
                            u"木料 #%d：裁切失败，已放入 FailTimbers 保留原件。" % idx
                        )

            else:
                # ====== 新逻辑：Intersection，保留刀具内部 ======
                # 先尝试联合刀具
                if self.union_tools is not None:
                    res = self._boolean_intersection(current, self.union_tools)
                    if res is not None:
                        self.cut_timbers.extend(res)
                        self.log.append(
                            u"木料 #%d：使用联合刀具求交成功（得到 %d 个 Brep）。"
                            % (idx, len(res))
                        )
                        success = True
                    else:
                        self.log.append(
                            u"木料 #%d：联合刀具求交失败，将尝试逐个刀具。" % idx
                        )

                # 联合失败则逐个刀具求交
                if not success:
                    tmp = current
                    ok = True
                    for j, tb in enumerate(self.tool_breps):
                        r = self._boolean_intersection(tmp, [tb])
                        if r is None:
                            self.log.append(
                                u"木料 #%d：在刀具 #%d 求交失败，停止该木料的进一步裁切。"
                                % (idx, j)
                            )
                            ok = False
                            break
                        tmp = r

                    if ok and tmp:
                        self.cut_timbers.extend(tmp)
                        self.log.append(
                            u"木料 #%d：逐个刀具求交成功（得到 %d 个 Brep）。"
                            % (idx, len(tmp))
                        )
                    else:
                        # 交集为空或失败 → 视为 Fail，保留原件
                        self.fail_timbers.append(geo)
                        self.log.append(
                            u"木料 #%d：求交失败或无交集，已放入 FailTimbers 保留原件。" % idx
                        )

    # --------- 对外主入口 ---------
    def run(self):
        """执行全部流程，返回 (CutTimbers, FailTimbers, Log)。"""
        try:
            self._preprocess_tools()
            self._cut_all_timbers()
        except Exception as e:
            # 捕捉到任何未预料错误时，也保证输出不为空，并在日志中记录
            self.log.append(u"运行过程中出现未捕捉异常: %s" % e)
            self.log.append(traceback.format_exc())

        self.log.append(u"最终 CutTimbers 数量: %d" % len(self.cut_timbers))
        self.log.append(u"最终 FailTimbers 数量: %d" % len(self.fail_timbers))

        return self.cut_timbers, self.fail_timbers, self.log

if __name__ == "__main__":
    # ================= GhPython I/O 区 =================
    # 输入:  Timbers, Tools, KeepInside
    # 输出:  CutTimbers, FailTimbers, Log

    # 兼容未连接 KeepInside 的情况
    try:
        _keep_inside_flag = bool(KeepInside)
    except:
        _keep_inside_flag = False

    cutter = FT_CutTimberByTools(Timbers, Tools, keep_inside=_keep_inside_flag)
    CutTimbers, FailTimbers, Log = cutter.run()

    # 调试用：在 Rhino 的命令行打印一行摘要（也可以去掉）
    print("CutTimbers:", CutTimbers)

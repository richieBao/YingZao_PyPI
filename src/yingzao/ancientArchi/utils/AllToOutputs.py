# -*- coding: utf-8 -*-
"""
AllToDynamicOutputs (safe auto-clear version)

功能：
- 根据 All ([(name, value), ...]) 动态生成输出端：
    标量      -> item
    一维 list -> list
    嵌套 list -> tree
- ClearAll=True 或 All 为空时：
    使用 ScheduleSolution 在“下一轮”安全删除所有动态输出端
    （只保留 Log），不会触发 Panel expired，也不会卡死

附加修正：
- 避免输出端使用 "type" 等 Python 保留名作为变量名
- 写入后自动清理 VolatileData 中 “全空的分支”，
  彻底消除 {0;0} 之类只有 <null> 的空路径
"""

import re
import Grasshopper as gh
import Grasshopper.Kernel as ghk
from Grasshopper.Kernel.Data import GH_Path
import RhinoCodePluginGH.Parameters as rcparams

# ================== Python 保留名 / 内置名黑名单 ==================

PY_RESERVED_NAMES = {
    "type", "list", "dict", "set", "tuple",
    "str", "int", "float", "bool",
    "input", "print", "len", "max", "min",
    "sum", "any", "all"
}

# =============== 工具函数 ===============

def is_list(x):
    return isinstance(x, (list, tuple))

def is_nested_list(x):
    if not is_list(x):
        return False
    return any(is_list(i) for i in x)

def prune_empty_branches(param):
    """
    在 param.VolatileData 中删除所有“完全空”的路径：
    - branch 为 None
    - branch.Count == 0
    - branch 内所有元素均为 None 或无效 IGH_Goo
    用于彻底清除 {0;0} 这种只有 <null> 的空分支。
    """
    structure = param.VolatileData
    if structure is None:
        return

    # 拷贝一份路径列表，避免遍历时修改集合
    try:
        paths = [p for p in structure.Paths]
    except Exception:
        return

    for path in paths:
        try:
            branch = structure.get_Branch(path)
        except Exception:
            continue

        if branch is None or branch.Count == 0:
            structure.RemovePath(path)
            continue

        # 判断该 branch 是否全是“无效 / 空”元素
        all_empty = True
        for item in branch:
            if item is None:
                continue
            # IGH_Goo 一般有 IsValid，防止某些类型没有这个属性
            try:
                has_valid = getattr(item, "IsValid", True)
            except Exception:
                has_valid = True
            if has_valid:
                all_empty = False
                break

        if all_empty:
            structure.RemovePath(path)

def schedule_clear_outputs_if_needed(comp, log_list):
    """
    若当前存在动态输出端，则安排在下一轮解算中清除它们（保留 Log）。
    - 只调度一次：如果已无动态端，则不调度 → 不会形成死循环
    - 回调中不再 ExpireSolution → 避免连续解算
    """
    outs = comp.Params.Output
    if outs.Count <= 1:
        # 没有动态端，无需清理
        log_list.append("ScheduleClear: 无动态输出端，不需要清理。")
        return

    doc = comp.OnPingDocument()
    if doc is None:
        log_list.append("ScheduleClear: 无 Doc，无法调度清理。")
        return

    def _do_clear(document):
        o = comp.Params.Output
        # 保留 index 0(Log)，其余全部删除
        while o.Count > 1:
            last = o.Count - 1
            comp.Params.UnregisterOutputParameter(o[last])
        comp.Params.OnParametersChanged()
        # 不再 ExpireSolution —— 这一轮解算会按新端口结构继续执行

    doc.ScheduleSolution(1, _do_clear)
    log_list.append("已调度：下一轮将清除所有动态输出端，只保留 Log。")


# =============== 主类 ===============

class AllToOutputs(object):

    def __init__(self, comp, all_pairs, clear_flag=False):
        self.comp = comp
        self.all_pairs = list(all_pairs) if all_pairs is not None else []
        self.clear_flag = bool(clear_flag)
        self.log = []

    @staticmethod
    def _safe_name(name):
        """
        将上游的任意 name 转为 GH 输出端可用且安全的变量名：
        - 替换非法字符
        - 避免数字开头
        - 避免与 Python 内置 / 关键字冲突（如 "type"）
        """
        s = str(name)

        # 1) 基础清洗
        s = s.replace("::", "_")
        s = re.sub(r"[^0-9A-Za-z_]+", "_", s)

        # 2) 空字符串兜底
        if not s:
            s = "v"

        # 3) 不能以数字开头
        if s[0].isdigit():
            s = "_" + s

        # 4) 避开 Python 保留名 / 内置名
        if s in PY_RESERVED_NAMES:
            s = s + "_v"

        return s

    def _create_param(self, nickname, description):
        p = rcparams.ScriptVariableParam()
        p.Access = ghk.GH_ParamAccess.item
        p.NickName = nickname
        p.Name = nickname
        p.Description = description
        return p

    # ---------- 确保输出端数量（只增不减） ----------
    def ensure_output_params(self):
        outputs = self.comp.Params.Output

        # 确保 Log 存在
        if outputs.Count == 0:
            p0 = self._create_param("Log", "Debug log")
            self.comp.Params.RegisterOutputParam(p0)
            outputs = self.comp.Params.Output
        else:
            p0 = outputs[0]
            p0.NickName = "Log"
            p0.Name = "Log"
            p0.Description = "Debug log"

        need = len(self.all_pairs)
        cur_dynamic = max(outputs.Count - 1, 0)

        # 只增加，不减少
        while cur_dynamic < need:
            idx = cur_dynamic + 1
            p = self._create_param(f"v{idx}", f"Auto output #{idx}")
            self.comp.Params.RegisterOutputParam(p)
            cur_dynamic += 1
            outputs = self.comp.Params.Output

        self.comp.Params.OnParametersChanged()
        self.log.append(
            "All 条目: {0}，当前动态端总数: {1}".format(
                need, max(self.comp.Params.Output.Count - 1, 0)
            )
        )

    # ---------- 写入值（+ 清理空路径） ----------
    def assign_values(self):
        outputs = list(self.comp.Params.Output)
        if len(outputs) <= 1:
            return

        dyn_outputs = outputs[1:]
        total_dyn = len(dyn_outputs)
        real_count = len(self.all_pairs)

        # 写入真实数据
        for i, ((name, value), param) in enumerate(zip(self.all_pairs, dyn_outputs)):
            safe = self._safe_name(name)
            param.NickName = safe
            param.Name = safe
            param.Description = str(name)

            # 完全清空旧数据，防止残留
            param.VolatileData.Clear()

            # value 为空（None 或 []）时：
            #   - 不写入 item / list / tree
            #   - Access 固定为 item
            #   - VolatileData 为空 → 不会产生任何 GH_Path
            if value is None or value == []:
                param.Access = ghk.GH_ParamAccess.item
                self.log.append(f"[{i+1}] {safe} = <EMPTY>")
                # 写完后再做一次空分支清理（防御性）
                prune_empty_branches(param)
                continue

            # -------- 非列表：标量 --------
            if not is_list(value):
                param.Access = ghk.GH_ParamAccess.item
                param.AddVolatileData(GH_Path(0), 0, value)

            # -------- 一维列表 --------
            elif not is_nested_list(value):
                param.Access = ghk.GH_ParamAccess.list
                for j, v in enumerate(value):
                    if v is None:
                        continue
                    param.AddVolatileData(GH_Path(0), j, v)

            # -------- 树结构（二维及以上）--------
            else:
                param.Access = ghk.GH_ParamAccess.tree
                for bi, branch in enumerate(value):
                    # 跳过空 branch，避免产生空路径 {i}
                    if branch is None or branch == []:
                        continue

                    if not is_list(branch):
                        # 退化为单值分支
                        param.AddVolatileData(GH_Path(bi), 0, branch)
                    else:
                        for jj, v in enumerate(branch):
                            if v is None:
                                continue
                            param.AddVolatileData(GH_Path(bi), jj, v)

            # 写入完成后，清理所有“仅含 null / 空”的 branch
            prune_empty_branches(param)

            self.log.append(f"[{i+1}] {safe} = {repr(value)}")

        # 若动态端多于真实条目：清空并标记为 unused（不删）
        if total_dyn > real_count:
            for k in range(real_count, total_dyn):
                p = dyn_outputs[k]
                nick = f"unused_{k+1}"
                p.NickName = nick
                p.Name = nick
                p.Description = "Unused output"
                p.Access = ghk.GH_ParamAccess.item
                p.VolatileData.Clear()
                prune_empty_branches(p)

    # ---------- 入口 ----------
    def run(self):
        outputs = self.comp.Params.Output
        dynamic_count = max(outputs.Count - 1, 0)

        # 1) ClearAll 优先：无论 All 是否为空，都清除动态端（如果有的话）
        if self.clear_flag:
            schedule_clear_outputs_if_needed(self.comp, self.log)
            return "\n".join(self.log)

        # 2) All 为空且当前有动态端 → 自动调度清理一次
        if len(self.all_pairs) == 0 and dynamic_count > 0:
            schedule_clear_outputs_if_needed(self.comp, self.log)
            return "\n".join(self.log)

        # 3) All 为空且本来就没有动态端 → 什么都不做
        if len(self.all_pairs) == 0 and dynamic_count == 0:
            self.log.append("All 为空，且无动态输出端，无需清理。")
            return "\n".join(self.log)

        # 4) 正常模式：根据 All 创建 / 写入输出端
        self.log.append(f"收到 All 条目：{len(self.all_pairs)}")
        self.ensure_output_params()
        self.assign_values()
        return "\n".join(self.log)


# =============== GhPython 入口 ===============
if __name__ == "__main__":

    if All is None:
        All = []

    if ClearAll is None:
        ClearAll = False

    converter = AllToOutputs(ghenv.Component, All, ClearAll)
    Log = converter.run()

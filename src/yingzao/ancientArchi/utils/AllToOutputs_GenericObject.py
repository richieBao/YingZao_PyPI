# -*- coding: utf-8 -*-
"""
AllToDynamicOutputs（修复空路径版本 · 集成 CleanTree 逻辑 · 双层空路径清理 · No-Access-Switch 版）

核心思路：
1. clean_tree_data(value, remove_nulls=True, remove_invalid=True, remove_empty=True)
   等价于 Clean Tree 里勾选 Nulls / Invalid / Empty（但不过度判定）
2. DataCollector 只在真正有数据时才写入 VolatileData
3. 不再根据数据结构动态切换 Access（item/list/tree）：
   - 输出端在创建时统一设为 item
   - 之后所有逻辑只操作 VolatileData，完全不再改 Access
   - 这样即使本轮完全没有数据，也不会因为 Access=list/tree 而出现 GH 自动制造的空路径
4. 类内（方案 B）：写入前用 clean_tree_data 清理数据；
   若清理后无任何数据，则只清空 VolatileData，不写入任何 path。
5. 类外（方案 A）：在 run() 之后，再遍历所有输出端：
   - 删除所有“空分支”（分支内没有元素）
   - 删除所有“只包含无效 Goo 的分支”（IsValid=False / ToString 为 null）
6. 新增：对每个输出端执行 DataTree 级 CleanTree（clean_all_output_trees）：
   - 过滤 Null / Invalid / 空对象
   - 删除清理后仍为空的分支
"""

import re
import Grasshopper as gh
import Grasshopper.Kernel as ghk
from Grasshopper.Kernel.Data import GH_Path
import RhinoCodePluginGH.Parameters as rcparams
import scriptcontext as sc
from Grasshopper.Kernel.Parameters import Param_GenericObject

# DataTree / Goo
from Grasshopper import DataTree
import Grasshopper.Kernel.Types as ght


# =============== Python 名字黑名单 ===============
PY_RESERVED_NAMES = {
    "type", "list", "dict", "set", "tuple",
    "str", "int", "float", "bool",
    "input", "print", "len", "max", "min",
    "sum", "any", "all"
}


# =============== 通用工具函数 ===============

def is_list(x):
    return isinstance(x, (list, tuple))


def is_nested_list(x):
    if not is_list(x):
        return False
    return any(is_list(i) for i in x)


# ---------- Goo 层：判断 GH 输出端里的元素是否“无效”（方案 A 用） ----------

def _goo_is_invalid(g):
    """
    统一判断 Grasshopper Goo 是否“无效”（用于类外方案 A）：

    满足以下任一条件即视为无效：
    - g is None
    - 有 IsValid 属性且 IsValid == False
    - str(g) 为 "null" 或 "<null>"（GH_Null 在面板中的典型表现）
    """
    if g is None:
        return True

    # ① IsValid == False
    try:
        if hasattr(g, "IsValid") and not g.IsValid:
            return True
    except:
        pass

    # ② 字符串表现为 "null" / "<null>"
    try:
        s = str(g).strip().lower()
        if s in ("null", "<null>"):
            return True
    except:
        pass

    return False


# ---------- 更贴近 CleanTree 的判空逻辑（用于 DataTree 级清理） ----------

def is_null_or_invalid(x):
    """
    尽量贴近 Clean Tree 对 Null / Invalid / 空对象的判定：
    - None
    - 空字符串 ""
    - 空 list/tuple
    - GH Goo：IsNull / IsValid / Value.IsValid
    - RhinoCommon 几何：IsValid=False
    """
    # 显式 None
    if x is None:
        return True

    # 空字符串
    if isinstance(x, str) and x == "":
        return True

    # 空 list / tuple
    if isinstance(x, (list, tuple)) and len(x) == 0:
        return True

    # GH Goo 类型
    if isinstance(x, ght.IGH_Goo):
        try:
            if hasattr(x, "IsNull") and x.IsNull:
                return True
            if hasattr(x, "IsValid") and (not x.IsValid):
                return True
        except:
            pass

        # 有些 Goo 的 Value 才是真正几何
        try:
            v = x.Value
            if hasattr(v, "IsValid") and (not v.IsValid):
                return True
        except:
            pass

        # 能走到这里就认为是有效 Goo
        return False

    # RhinoCommon 几何：大多带 IsValid
    if hasattr(x, "IsValid"):
        try:
            if x.IsValid is False:
                return True
        except:
            pass

    return False


# ---------- Python 值层：判断 All 里的值是否有效（方案 B 用） ----------

def is_value_valid(value):
    """
    判断值是否有效（用于 DataCollector 的二次防守 · 温和版）：
    - None 视为无效
    - 空 list / 空 tuple 视为无效
    - 带 IsValid 且 IsValid=False 视为无效
    - 空字符串视为无效
    """
    if value is None:
        return False

    # 空列表 / 空元组 当作无效
    if is_list(value) and len(value) == 0:
        return False

    # Invalid（几何或其它带 IsValid 的对象）
    try:
        if hasattr(value, "IsValid") and not value.IsValid:
            return False
    except:
        pass

    # 空字符串
    if isinstance(value, str) and value.strip() == "":
        return False

    return True


def force_clear_param(param, log=None):
    """强制清空参数的所有数据（Volatile + Persistent）"""
    try:
        # 1) 清空易失数据
        if param.VolatileData is not None:
            param.VolatileData.Clear()

        # 2) ★ 再把默认的 PersistentData 也清掉，干掉 {0;0;0}<null>
        if hasattr(param, "PersistentData") and param.PersistentData is not None:
            param.PersistentData.Clear()

        if log is not None:
            log.append("  参数已清空 VolatileData & PersistentData: {}".format(param.NickName))
    except Exception as e:
        if log is not None:
            log.append("  清空参数数据失败: {} - {}".format(param.NickName, e))


def schedule_clear_outputs_if_needed(comp, log_list):
    """下一轮安全清除所有动态输出端（保留 Log）"""
    outs = comp.Params.Output
    if outs.Count <= 1:
        log_list.append("ScheduleClear：无动态输出端，无需清理。")
        return

    doc = comp.OnPingDocument()
    if doc is None:
        log_list.append("ScheduleClear：无法获取 Doc。")
        return

    def _clear(document):
        o = comp.Params.Output
        while o.Count > 1:
            comp.Params.UnregisterOutputParameter(o[o.Count - 1])
        comp.Params.OnParametersChanged()

    doc.ScheduleSolution(1, _clear)
    log_list.append("已调度：下一轮将清除所有动态输出端（仅保留 Log）。")


# =============== 类外空路径清理（方案 A） ===============

def clear_empty_paths_for_outputs(comp):
    """
    在 AllToOutputs.run() 结束之后调用：
    遍历组件所有“动态输出端”（跳过 Log），删除 VolatileData 中的“空分支路径”：
        - 分支长度为 0
        - 分支内所有元素均为“无效值”（_goo_is_invalid 为 True）
    """
    outs = comp.Params.Output
    if outs is None or outs.Count <= 1:
        return

    for i in range(1, outs.Count):
        param = outs[i]
        vd = param.VolatileData
        if vd is None:
            continue

        try:
            paths = list(vd.Paths)
        except Exception:
            continue

        for path in paths:
            try:
                branch = vd.Branch(path)
            except Exception:
                try:
                    branch = vd.get_Branch(path)
                except Exception:
                    branch = None

            # ① 完全没有元素：直接删路径
            if branch is None or len(branch) == 0:
                vd.RemovePath(path)
                continue

            # ② 分支存在，但所有元素都是“无效值”：也当作空路径删掉
            all_invalid = True
            try:
                for g in branch:
                    if not _goo_is_invalid(g):
                        all_invalid = False
                        break
            except Exception:
                # 取分支失败时，保守处理：认为不是全无效，避免误删
                all_invalid = False

            if all_invalid:
                vd.RemovePath(path)


# =============== DataTree 级 CleanTree（增强） ===============

def clean_param_volatiledata(param):
    """
    类似 Clean Tree：
    - 读取 param.VolatileData -> DataTree[object]
    - 过滤每个分支里的 Null / Invalid / 空值（is_null_or_invalid）
    - 丢弃清理后仍为空的分支（Remove Empty）
    - 再写回 VolatileData
    """
    vd = param.VolatileData
    if vd is None:
        return

    try:
        paths = list(vd.Paths)
    except Exception:
        return

    new_tree = DataTree[object]()
    has_any = False

    for path in paths:
        try:
            branch = list(vd.Branch(path))
        except Exception:
            try:
                branch = list(vd.get_Branch(path))
            except Exception:
                branch = []

        # 逐元素过滤 Null / Invalid / 空对象
        valid_items = []
        for item in branch:
            if is_null_or_invalid(item):
                continue
            valid_items.append(item)

        # Remove Empty：清理后仍为空则跳过该路径
        if not valid_items:
            continue

        has_any = True
        for v in valid_items:
            new_tree.Add(v, path)

    # 清空旧数据
    vd.Clear()

    # 若完全空，则保持 VolatileData 为空，不再改 Access
    if not has_any:
        return

    # 写回清理后的 DataTree
    try:
        for path in new_tree.Paths:
            branch = list(new_tree.Branch(path))
            for i, v in enumerate(branch):
                param.AddVolatileData(path, i, v)
    except Exception:
        # 写回失败避免崩溃，静默略过
        pass


def clean_all_output_trees(comp):
    """
    对当前组件的所有“动态输出端”（跳过 Log）执行一次 DataTree 级 CleanTree 清理
    用于在每轮写入之后扫掉空路径
    """
    outs = comp.Params.Output
    if outs is None or outs.Count <= 1:
        return

    for i in range(1, outs.Count):
        param = outs[i]
        clean_param_volatiledata(param)


# =============== Clean Tree 清理逻辑（方案 B：值层）===============

def clean_tree_data(value, remove_nulls=True, remove_invalid=True, remove_empty=True):
    """
    清理数据树，移除 Nulls、Invalid 和 Empty 值
    等价于 Grasshopper Clean Tree 组件勾选：
        - Remove Nulls
        - Remove Invalid
        - Remove Empty
    返回清理后的数据，如果全部被清理则返回 None
    """

    # 内部判定函数，对单个值应用 CleanTree 三个选项
    def _keep(v):
        # Null
        if v is None and remove_nulls:
            return False

        # Invalid（几何或其它带 IsValid 的对象）
        if remove_invalid:
            try:
                if hasattr(v, "IsValid") and not v.IsValid:
                    return False
            except:
                pass

        # Empty（这里以空字符串 + 空 list 处理）
        if remove_empty:
            if isinstance(v, str) and v.strip() == "":
                return False
            if is_list(v) and len(v) == 0:
                return False

        return True

    # 直接 None
    if value is None:
        return None

    # 标量值
    if not is_list(value):
        return value if _keep(value) else None

    # 一维列表
    if not is_nested_list(value):
        cleaned = [v for v in value if _keep(v)]
        return cleaned if len(cleaned) > 0 else None

    # 树结构（二维嵌套列表）
    cleaned_tree = []

    for branch in value:
        if branch is None:
            continue

        # 分支是标量
        if not is_list(branch):
            if _keep(branch):
                cleaned_tree.append(branch)
        else:
            # 分支是列表
            cleaned_branch = [v for v in branch if _keep(v)]
            # 只有非空分支才加入（等价于 Clean Tree 的 Remove Empty）
            if len(cleaned_branch) > 0:
                cleaned_tree.append(cleaned_branch)

    return cleaned_tree if len(cleaned_tree) > 0 else None


# =============== 数据准备器（关键改进）===============

class DataCollector(object):
    """先收集所有有效数据，再一次性写入，避免创建空路径"""

    def __init__(self):
        self.data = {}  # {path_index: {item_index: value}}
        self.has_data = False

    def add(self, path_idx, item_idx, value):
        """添加一个有效数据项"""
        if not is_value_valid(value):
            return False

        if path_idx not in self.data:
            self.data[path_idx] = {}
        self.data[path_idx][item_idx] = value
        self.has_data = True
        return True

    def write_to_param(self, param):
        """将收集的数据写入参数（只有有数据时才写）"""
        if not self.has_data:
            return 0

        total = 0
        for path_idx in sorted(self.data.keys()):
            items = self.data[path_idx]
            for item_idx in sorted(items.keys()):
                param.AddVolatileData(GH_Path(path_idx), item_idx, items[item_idx])
                total += 1
        return total


# =============== 主类 ===============

class AllToOutputsGenericObject(object):

    def __init__(self, comp, all_pairs, clear_flag=False, refresh=False):
        self.comp = comp
        self.all_pairs = list(all_pairs) if all_pairs is not None else []
        self.clear_flag = bool(clear_flag)
        self.refresh = bool(refresh)
        self.log = []

    @staticmethod
    def _safe_name(name):
        s = str(name)
        s = s.replace("::", "_")
        s = re.sub(r"[^0-9A-Za-z_]+", "_", s)

        if not s:
            s = "v"
        if s[0].isdigit():
            s = "_" + s
        if s in PY_RESERVED_NAMES:
            s += "_v"

        return s

    def _create_param(self, nickname, description):
        # ★ 输出端改用标准的 GH 泛型参数，而不是 ScriptVariableParam
        p = Param_GenericObject()
        p.Access = ghk.GH_ParamAccess.item
        p.NickName = nickname
        p.Name = nickname
        p.Description = description

        # 可改名（可选）
        try:
            p.MutableNickName = True
        except:
            pass

        # ★ 这里不再需要 PersistentData.Clear()，GenericObject 清一次即可
        try:
            if p.PersistentData is not None:
                p.PersistentData.Clear()
        except:
            pass

        return p



    def ensure_output_params(self):
        """确保输出端数量"""
        outs = self.comp.Params.Output

        # 确保 Log 存在
        if outs.Count == 0:
            p0 = self._create_param("Log", "Debug log")
            self.comp.Params.RegisterOutputParam(p0)
            self.log.append("创建 Log 输出端")
        else:
            p0 = outs[0]
            p0.NickName = "Log"
            p0.Name = "Log"
            p0.Description = "Debug log"

        need = len(self.all_pairs)
        exist_dyn = max(self.comp.Params.Output.Count - 1, 0)

        self.log.append("需要输出端数：{}，当前动态输出端：{}".format(need, exist_dyn))

        if need > exist_dyn:
            add_count = need - exist_dyn
            self.log.append("需要新增 {} 个输出端".format(add_count))
            for i in range(add_count):
                idx = exist_dyn + i + 1
                p = self._create_param(f"v{idx}", f"Auto output #{idx}")
                self.comp.Params.RegisterOutputParam(p)
                self.log.append("  已添加输出端 v{}".format(idx))

            self.comp.Params.OnParametersChanged()
            self.log.append("输出端更新完成，当前总数：{}".format(self.comp.Params.Output.Count))
        else:
            self.log.append("无需添加新输出端")


    def assign_values(self, allow_resize=False):
        """
        写入数据（关键改进：使用 CleanTree + DataCollector 避免空路径）

        Access 在本版本中始终保持 item，不再根据数据结构切换。
        """
        outs = list(self.comp.Params.Output)
        if len(outs) <= 1:
            return

        dyn = outs[1:]
        real_count = min(len(self.all_pairs), len(dyn))

        self.log.append("====== 开始写入数据 ======")
        self.log.append("All 条目数 = {}，动态输出端数 = {}，本轮实际写入 = {}".format(
            len(self.all_pairs), len(dyn), real_count))

        for i in range(real_count):
            (name, value) = self.all_pairs[i]
            param = dyn[i]

            safe = self._safe_name(name)
            idx = i + 1

            self.log.append("\n[{}] 处理输出端：{}".format(idx, safe))

            param.NickName = safe
            param.Name = safe
            param.Description = str(name)

            # 清空旧数据
            force_clear_param(param, self.log)

            # ★ 步骤1：使用 Clean Tree 清理数据（移除 Nulls、Invalid、Empty）
            cleaned_value = clean_tree_data(
                value,
                remove_nulls=True,
                remove_invalid=True,
                remove_empty=True
            )

            # 若清理后无任何数据：只保持 VolatileData 为空，不写入任何 path
            if cleaned_value is None:
                self.log.append("[{}] {} 清理后无有效数据，本轮不写入任何数据（保持完全空状态）".format(idx, safe))
                continue

            self.log.append("[{}] {} 数据清理完成".format(idx, safe))

            # ★ 步骤2：使用 DataCollector 收集清理后的数据
            collector = DataCollector()

            # 标量
            if not is_list(cleaned_value):
                collector.add(0, 0, cleaned_value)

            # 一维列表
            elif not is_nested_list(cleaned_value):
                for j, v in enumerate(cleaned_value):
                    collector.add(0, j, v)

            # 树结构（二维嵌套列表）
            else:
                for bi, branch in enumerate(cleaned_value):
                    if branch is None:
                        continue

                    if not is_list(branch):
                        collector.add(bi, 0, branch)
                    else:
                        for vi, v in enumerate(branch):
                            collector.add(bi, vi, v)

            # ★ 步骤3：只有在有有效数据时才写入
            written_count = collector.write_to_param(param)

            if written_count > 0:
                self.log.append("[{}] {} 写入成功（有效数据项 = {}）".format(
                    idx, safe, written_count))
            else:
                # 没有有效数据写入：保持 VolatileData 为空即可
                force_clear_param(param, self.log)
                self.log.append("[{}] {} 无有效数据，本轮保持完全空状态".format(idx, safe))

        # 清理未使用的输出端（只清数据，不删端口）
        if len(dyn) > real_count:
            self.log.append("\n====== 清理未使用输出端 ======")
            for k in range(real_count, len(dyn)):
                p = dyn[k]
                p.NickName = f"unused_{k+1}"
                p.Name = f"unused_{k+1}"
                p.Description = "Unused output"
                # 这里保持 Access=item（创建时已设），只清空数据
                force_clear_param(p, self.log)

        # ★★ 本轮写完数据后，对所有输出端做一次 DataTree 层级的 CleanTree 清理
        clean_all_output_trees(self.comp)

    def refresh_all_output_data(self):
        """Refresh：只刷新数据，不改端口结构"""
        outs = self.comp.Params.Output
        dyn_count = max(outs.Count - 1, 0)

        if dyn_count <= 0:
            self.log.append("Refresh：无动态输出端，无需刷新。")
            return

        dyn_params = list(outs)[1:]
        self.log.append("Refresh：开始清空所有动态输出端的数据（保留端口结构）...")

        # 清空所有动态输出端的 VolatileData
        for param in dyn_params:
            force_clear_param(param, self.log)

        # 清除 sticky 缓存（按你原来的逻辑）
        try:
            key = "LU_DOU_CACHE_{}".format(self.comp.InstanceGuid)
            if key in sc.sticky:
                del sc.sticky[key]
                self.log.append("Refresh：已清除 sticky 缓存 {}".format(key))
        except Exception as e:
            self.log.append("Refresh：清 sticky 缓存时出错: {}".format(e))

        # 重新写入当前 All 的数据
        self.log.append("Refresh：开始重新写入数据...")
        self.assign_values(allow_resize=False)
        self.log.append("Refresh：数据刷新完成。")

        # Refresh 模式结束后，同样清理一次所有输出端的空路径
        clean_all_output_trees(self.comp)

    def run(self):
        """主执行"""
        # 清空 Log 输出端
        try:
            outs0 = self.comp.Params.Output
            if outs0.Count > 0:
                log_param = outs0[0]
                force_clear_param(log_param, None)
        except:
            pass

        self.log.append("====== AllToDynamicOutputs · 修复空路径版（CleanTree + 双层空路径清理 · No-Access-Switch）======")
        self.log.append("All 总条目数 = {}".format(len(self.all_pairs)))

        outs = self.comp.Params.Output
        dyn_count = max(outs.Count - 1, 0)

        mode_str = "模式：ClearAll={}, Refresh={}".format(self.clear_flag, self.refresh)
        self.log.append(mode_str)
        self.log.append("当前动态输出端数 = {}".format(dyn_count))

        sticky_key = "ATD_ALL_COUNT_{}".format(self.comp.InstanceGuid)

        # Refresh 模式
        if self.refresh:
            self.log.append("\n→ Refresh 模式：重新读取并刷新所有输出数据")
            self.refresh_all_output_data()

        # ClearAll 模式
        elif self.clear_flag:
            self.log.append("\n→ ClearAll 模式：调度清除所有动态输出端")
            schedule_clear_outputs_if_needed(self.comp, self.log)

        # All 为空
        elif len(self.all_pairs) == 0:
            # All 既然为空，就把上次记录的 All 数清掉，避免下一次误判“未变化”
            if sticky_key in sc.sticky:
                del sc.sticky[sticky_key]
                self.log.append("All 为空：已重置 sticky 中的 All 项数记录。")

            if dyn_count > 0:
                self.log.append("\n→ All 为空，将在下一轮清除输出端")
                schedule_clear_outputs_if_needed(self.comp, self.log)
            else:
                self.log.append("All 为空，且无动态输出端。")

        # 正常模式
        else:
            self.log.append("\n→ 正常模式：处理数据")

            # 1) 检测输入端 “All” 是否有连线（没连线就不处理）
            all_connected = False
            try:
                for ip in self.comp.Params.Input:
                    if ip.NickName == "All":
                        all_connected = (ip.SourceCount > 0)
                        break
            except Exception:
                all_connected = False

            if not all_connected:
                self.log.append("All 输入端未连接，跳过 ensure_output_params 和数据写入。")
            else:
                # 2) 只有当 All 结构变化 或 当前没有动态输出端 时才执行 ensure_output_params
                all_count = len(self.all_pairs)
                prev_count = sc.sticky.get(sticky_key, None)

                need_ensure = False
                if dyn_count == 0:
                    need_ensure = True
                    self.log.append("当前无动态输出端 (dyn_count=0)，需要执行 ensure_output_params。")
                elif prev_count is None:
                    need_ensure = True
                    self.log.append("首次记录 All 项数 = {}，需要执行 ensure_output_params。".format(all_count))
                elif prev_count != all_count:
                    need_ensure = True
                    self.log.append("All 项数变化: {} → {}，需要执行 ensure_output_params。".format(prev_count, all_count))
                else:
                    self.log.append("All 项数未变化 ({}), 跳过 ensure_output_params（仅刷新数据）。".format(all_count))

                print(need_ensure)
                if need_ensure:
                    sc.sticky[sticky_key] = all_count
                    self.log.append("执行 ensure_output_params() ...")
                    self.ensure_output_params()
                    dyn_count = max(self.comp.Params.Output.Count - 1, 0)
                    self.log.append("ensure_output_params 完成，当前动态输出端数 = {}".format(dyn_count))

            # 3) 不管结构是否变化，只要 All 有数据就写入数据
            if self.comp.Params.Output.Count <= 1:
                self.log.append("⚠ 警告：输出端数量异常！")
            else:
                self.log.append("准备写入数据...")
                self.assign_values(allow_resize=True)

        return "\n".join(self.log)


# =============== GhPython 入口 ===============
if __name__ == "__main__":

    if All is None:
        All = []

    if ClearAll is None:
        ClearAll = False

    if Refresh is None:
        Refresh = False

    converter = AllToOutputsGenericObject(
        ghenv.Component,
        All,
        ClearAll,
        Refresh
    )

    _log_text = converter.run()

    # run 之后：类外再做一次空路径清理（老方案 A + 新方案）
    try:
        clear_empty_paths_for_outputs(ghenv.Component)
    except Exception:
        pass

    try:
        clean_all_output_trees(ghenv.Component)
    except Exception:
        pass

    # 写入 Log
    try:
        outs = ghenv.Component.Params.Output
        if outs.Count > 0:
            log_param = outs[0]
            log_param.Access = ghk.GH_ParamAccess.item
            log_param.NickName = "Log"
            log_param.Name = "Log"
            log_param.Description = "Debug log"

            force_clear_param(log_param, None)
            log_param.AddVolatileData(GH_Path(0), 0, _log_text)

    except Exception:
        Log = _log_text

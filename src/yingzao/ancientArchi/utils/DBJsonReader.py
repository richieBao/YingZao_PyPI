# -*- coding: utf-8 -*-
"""
DBJsonReader (类版，适用于 Rhino 8 / GhPython Python 3)

功能：
1. 从 SQLite 数据库中读取指定表、指定记录的一列（Field）。
2. 如果该列是 JSON 字符串：
    - 根据 JsonPath（面板多行字符串）提取嵌套字段值 → 输出到 Value。
    - 当 ExportAll=True 时，展开整个 JSON 的所有叶子节点，按
        <一级键>__<二级键>__...
      形成键名，并以 (name, value) 列表的形式输出到 All。
      （注意：此处已不再在前面加 Field 名，如 params_json）
3. 如果该列不是 JSON，则直接把原始值返回到 Value。

GhPython 输入：
    DBPath   : str   - SQLite 数据库路径
    Table    : str   - 表名，如 "DG_Dou"
    KeyField : str   - 用来筛选记录的字段名，如 "type_code"
    KeyValue : any   - 对应的值，如 "LU_DOU"
    Field    : str   - 要读取的字段名，如 "params_json"
    JsonPath : list[str] - 多行字符串，每一行是一层 JSON 键名
    ExportAll: bool  - True 时展开整个 JSON 到 All

GhPython 输出：
    Value : any          - 按 JsonPath 取到的值（或普通字段值）
    All   : list[tuple]  - ExportAll=True 时，为 (name, value) 列表
    Log   : list[str]    - 调试信息
"""

import os
import re
import json
import sqlite3

from yingzao.ancientArchi.utils.DBPathContext import resolve_db_path


class DBJsonReader(object):
    """负责从 SQLite 读取字段并解析 JSON 的工具类"""

    def __init__(self, db_path, table, key_field, key_value,
                 field, json_path=None, export_all=False, ghenv=None):
        self.db_path = db_path
        self.table = table
        self.key_field = key_field
        self.key_value = key_value
        self.field = field
        self.json_path = json_path or []
        self.export_all = export_all
        self.ghenv = ghenv

        self.log = []          # 日志列表
        self._row_value = None # 原始字段值
        self._json_obj = None  # 解析后的 JSON 对象

    # ---------------- 基础工具 ----------------

    def _set_message(self, msg):
        """设置组件 Message（若在 GhPython 环境中）"""
        if self.ghenv is not None:
            try:
                self.ghenv.Component.Message = msg
            except Exception:
                pass

    def _append_log(self, text):
        self.log.append(text)

    # ---------------- 输入检查 & 读取 ----------------

    def validate_inputs(self):
        """检查基本输入是否有效，不抛异常，返回 bool"""
        resolved_db_path, source = resolve_db_path(self.db_path, ghenv=self.ghenv)
        if not resolved_db_path:
            self._append_log("DBPath 为空。")
            self._set_message("No DBPath")
            return False

        self.db_path = resolved_db_path
        if source == "document_default":
            self._append_log("DBPath 未显式输入，已回退到当前 GH 文档默认 DBPath。")
        else:
            self._append_log("DBPath 来源: {0}".format(source))

        db_path = os.path.expanduser(self.db_path)
        if not os.path.isfile(db_path):
            self._append_log("数据库不存在: {0}".format(db_path))
            self._set_message("DB not found")
            return False

        if not self.table:
            self._append_log("Table 为空。")
            self._set_message("No Table")
            return False

        if not self.field:
            self._append_log("Field 为空。")
            self._set_message("No Field")
            return False

        # 替换为展开后的路径
        self.db_path = db_path
        return True

    def load_field_value(self):
        """从数据库读取一条记录的指定字段值，保存到 self._row_value"""
        sql = "SELECT {0} FROM {1}".format(self.field, self.table)
        params = []

        if self.key_field and self.key_value is not None:
            sql += " WHERE {0} = ?".format(self.key_field)
            params.append(self.key_value)

        sql += " LIMIT 1"

        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            conn.close()
        except Exception as e:
            self._append_log("数据库访问异常: {0}".format(e))
            self._set_message("DB error")
            return False

        if row is None:
            self._append_log("未找到符合条件的记录。SQL = {0}".format(sql))
            self._set_message("No row")
            return False

        self._row_value = row[0]
        self._append_log(
            "字段 {0} 原始值类型: {1}".format(self.field, type(self._row_value).__name__)
        )
        return True

    # ---------------- JSON 解析 ----------------

    def try_parse_json(self):
        """尝试把字段值解析为 JSON，成功则保存 self._json_obj 并返回 True"""
        raw = self._row_value
        json_obj = None

        if isinstance(raw, (str, bytes)):
            try:
                json_obj = json.loads(raw)
                self._append_log("成功将字段 {0} 解析为 JSON 对象。".format(self.field))
            except Exception as e:
                self._append_log("解析 JSON 失败，按普通字段返回。错误: {0}".format(e))

        self._json_obj = json_obj
        return json_obj is not None

    def get_value_by_path(self):
        """根据 json_path 从 self._json_obj 中提取值"""
        if self._json_obj is None:
            return self._row_value  # 非 JSON 字段，直接返回

        result = self._json_obj
        if self.json_path:
            for key in self.json_path:
                if key is None:
                    continue
                k = str(key).strip()
                if not k:
                    continue
                if isinstance(result, dict) and k in result:
                    result = result[k]
                else:
                    self._append_log(
                        "JsonPath 中断：当前对象不是 dict 或缺少键 '{0}'。".format(k)
                    )
                    result = None
                    break
        return result

    # ---------------- JSON 展平 ----------------

    @staticmethod
    def _flatten_json(obj, prefix, out_dict):
        """递归展开 JSON：
        - dict 继续递归
        - 非 dict（包括 list）作为叶子节点
        """
        if isinstance(obj, dict):
            for kk, vv in obj.items():
                DBJsonReader._flatten_json(vv, prefix + [str(kk)], out_dict)
        else:
            out_dict[tuple(prefix)] = obj

    @staticmethod
    def _path_to_name(path_tuple):
        """把 (level1, level2, ...) 转成合法 GH 名称：
        level1__level2__...
        （注意：这里不再包含 Field 名）
        """
        # 只用 JSON 路径本身来组成名字
        parts = [str(p) for p in path_tuple]
        raw_name = "__".join(parts)

        # 替换 :: → _，避免非法字符
        raw_name = raw_name.replace("::", "_")

        # 非字母数字下划线 → 下划线
        name = re.sub(r"[^0-9A-Za-z_]+", "_", raw_name)
        if not name:
            name = "v"
        if name[0].isdigit():
            name = "_" + name
        return name

    def export_all_flat(self):
        """ExportAll=True 时，展开所有叶子节点，返回 (name, value) 列表"""
        if self._json_obj is None:
            return None

        flat = {}
        DBJsonReader._flatten_json(self._json_obj, [], flat)

        all_dict = {}
        for p, v in flat.items():
            # 这里已改为不传 Field，只用 JSON 路径本身生成键名
            n = DBJsonReader._path_to_name(p)
            all_dict[n] = v

        self._append_log(
            "ExportAll=True：展开 JSON 叶子节点共 {0} 个。".format(len(all_dict))
        )

        # 返回 (name, value) 的排序列表，方便 Panel 查看
        pairs = [(name, all_dict[name]) for name in sorted(all_dict.keys())]
        return pairs

    # ---------------- 主入口 ----------------

    def run(self):
        """执行完整流程，返回 (value, all_pairs, log)"""
        # 1. 检查输入
        if not self.validate_inputs():
            return None, None, self.log

        # 2. 读取字段值
        if not self.load_field_value():
            return None, None, self.log

        # 3. 尝试解析 JSON
        has_json = self.try_parse_json()

        # 4. 按路径取单个值
        value = self.get_value_by_path()

        # 5. ExportAll 时展开所有叶子节点
        all_pairs = None
        if has_json:
            self._set_message("JSON OK")
            if self.export_all:
                all_pairs = self.export_all_flat()
        else:
            self._set_message("Field (non-JSON)")

        return value, all_pairs, self.log

if __name__ == "__main__":
    # ======================================================================
    # GhPython 组件入口
    #   假定已在组件中声明以下输入：
    #       DBPath, Table, KeyField, KeyValue, Field, JsonPath, ExportAll
    #   并声明输出：
    #       Value, All, Log
    # ======================================================================

    reader = DBJsonReader(
        db_path=DBPath,
        table=Table,
        key_field=KeyField,
        key_value=KeyValue,
        field=Field,
        json_path=JsonPath,
        export_all=ExportAll,
        ghenv=ghenv  # 传入 ghenv 方便设置组件 Message
    )

    Value, All, Log = reader.run()

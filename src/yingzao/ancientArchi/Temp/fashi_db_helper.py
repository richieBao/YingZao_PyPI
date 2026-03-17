# fashi_db_helper.py
# 统一管理 SQLite + JSON 读取

import sqlite3
import json

from yingzao.ancientArchi.utils.DBPathContext import resolve_db_path

class FashiDB(object):
    def __init__(self, db_path, ghenv=None):
        self.db_path = db_path
        self.ghenv = ghenv

    # 基础查询方法
    def _query_one(self, sql, args=()):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(sql, args)
        row = cur.fetchone()
        conn.close()
        return row

    # ---- 常用接口 ----

    def get_dou_by_type(self, type_code):
        """
        根据斗类型取 JSON 参数，返回 Python dict
        """
        row = self._query_one(
            "SELECT params_json FROM DG_Dou WHERE type_code=?;",
            (type_code,)
        )
        if not row or row[0] is None:
            return None
        return json.loads(row[0])

    def get_dou_by_id(self, dou_id):
        row = self._query_one(
            "SELECT params_json FROM DG_Dou WHERE dou_id=?;",
            (dou_id,)
        )
        if not row or row[0] is None:
            return None
        return json.loads(row[0])

    def get_value(self, type_code, json_path, default=None):
        """
        直接取 JSON 中某个字段，比如 $.plan.width
        json_path 用点路径写：'plan.width' or 'segment_height.upper_ear'
        """
        params = self.get_dou_by_type(type_code)
        if params is None:
            return default

        parts = json_path.split(".")
        v = params
        try:
            for p in parts:
                # 支持简单的数组下标：segments_y[2]
                if "[" in p and p.endswith("]"):
                    name, idx = p[:-1].split("[")
                    v = v[name][int(idx)]
                else:
                    v = v[p]
            return v
        except Exception:
            return default


# ---- 简单单例封装：避免每个组件自己 new 一次 ----

__DB_CACHE = {}

def get_db(db_path, ghenv=None):
    """
    获取某个 db_path 对应的 FashiDB 实例，自动缓存。
    """
    global __DB_CACHE
    resolved_db_path, _ = resolve_db_path(db_path, ghenv=ghenv)
    cache_key = resolved_db_path or db_path
    if cache_key not in __DB_CACHE:
        __DB_CACHE[cache_key] = FashiDB(resolved_db_path, ghenv=ghenv)
    return __DB_CACHE[cache_key]

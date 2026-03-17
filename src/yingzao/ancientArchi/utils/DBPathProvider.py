# -*- coding: utf-8 -*-
"""
DB Path Provider

为当前 Grasshopper 文档注册默认数据库路径。

GhPython 输入：
    DBPath : str
    Clear  : bool

GhPython 输出：
    DBPathOut : str
    DocKey    : str
    Log       : list[str]
"""

import scriptcontext as sc

from yingzao.ancientArchi.utils.DBPathContext import (
    clear_default_db_path,
    get_document_identity,
    get_default_db_path,
    set_default_db_path,
)


class DBPathProvider(object):
    def __init__(self, db_path, ghenv=None):
        self.db_path = db_path
        self.ghenv = ghenv
        self.log = []

    def run(self, clear=False):
        component = getattr(self.ghenv, "Component", None) if self.ghenv is not None else None
        doc_key = get_document_identity(component=component, ghenv=self.ghenv)

        if clear:
            clear_default_db_path(component=component, ghenv=self.ghenv)
            self.log.append("已清除当前 GH 文档的默认 DBPath。")
            return None, doc_key, self.log

        resolved, changed = set_default_db_path(self.db_path, component=component, ghenv=self.ghenv)
        if not resolved:
            current = get_default_db_path(component=component, ghenv=self.ghenv)
            if current:
                self.log.append("输入 DBPath 为空，保持当前文档默认 DBPath: {0}".format(current))
                return current, doc_key, self.log

            self.log.append("输入 DBPath 为空，且当前文档尚未注册默认 DBPath。")
            return None, doc_key, self.log

        self.log.append("已为当前 GH 文档注册默认 DBPath: {0}".format(resolved))
        if changed:
            self._schedule_document_refresh(component)
        return resolved, doc_key, self.log

    def _schedule_document_refresh(self, component):
        if component is None:
            return

        doc = component.OnPingDocument()
        if doc is None:
            return

        flag_key = "YingZaoLab.DBPathProvider.RefreshScheduled.{0}".format(component.InstanceGuid)
        if sc.sticky.get(flag_key):
            return

        sc.sticky[flag_key] = True

        def _refresh(document):
            try:
                for obj in document.Objects:
                    try:
                        obj.ExpireSolution(False)
                    except Exception:
                        pass
            finally:
                if flag_key in sc.sticky:
                    del sc.sticky[flag_key]

        doc.ScheduleSolution(1, _refresh)


if __name__ == "__main__":
    if 'Clear' not in globals() or Clear is None:
        Clear = False

    provider = DBPathProvider(DBPath, ghenv=ghenv)
    DBPathOut, DocKey, Log = provider.run(clear=Clear)

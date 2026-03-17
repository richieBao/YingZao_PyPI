# -*- coding: utf-8 -*-
"""
Grasshopper document-scoped DBPath context helpers.

用途：
- 为当前 GH 文档注册一个默认数据库路径
- 让其它组件在未显式输入 DBPath 时自动回退到该默认值
- 使用文档级 key，避免不同 .gh 文档之间互相污染
"""

import os
import scriptcontext as sc


_NAMESPACE = "YingZaoLab.DBPath"


def _get_document(component=None, ghenv=None, document=None):
    if document is not None:
        return document

    if component is None and ghenv is not None:
        component = getattr(ghenv, "Component", None)

    if component is not None:
        try:
            return component.OnPingDocument()
        except Exception:
            return None

    return None


def get_document_identity(component=None, ghenv=None, document=None):
    doc = _get_document(component=component, ghenv=ghenv, document=document)
    if doc is None:
        return "no_document"

    try:
        file_path = getattr(doc, "FilePath", None)
        if file_path:
            return os.path.normcase(os.path.abspath(file_path))
    except Exception:
        pass

    try:
        return "unsaved:{0}".format(doc.RuntimeID)
    except Exception:
        return "unsaved:{0}".format(id(doc))


def make_document_dbpath_key(component=None, ghenv=None, document=None):
    return (_NAMESPACE, get_document_identity(component=component, ghenv=ghenv, document=document))


def normalize_db_path(db_path):
    if db_path is None:
        return None

    try:
        text = str(db_path).strip()
    except Exception:
        return None

    if not text:
        return None

    return os.path.expanduser(text)


def set_default_db_path(db_path, component=None, ghenv=None, document=None):
    normalized = normalize_db_path(db_path)
    if not normalized:
        return None, False

    key = make_document_dbpath_key(component=component, ghenv=ghenv, document=document)
    previous = sc.sticky.get(key)
    sc.sticky[key] = normalized
    return normalized, previous != normalized


def get_default_db_path(component=None, ghenv=None, document=None):
    key = make_document_dbpath_key(component=component, ghenv=ghenv, document=document)
    return sc.sticky.get(key)


def clear_default_db_path(component=None, ghenv=None, document=None):
    key = make_document_dbpath_key(component=component, ghenv=ghenv, document=document)
    if key in sc.sticky:
        del sc.sticky[key]


def resolve_db_path(db_path, component=None, ghenv=None, document=None):
    explicit_path = normalize_db_path(db_path)
    if explicit_path:
        return explicit_path, "input"

    fallback_path = get_default_db_path(component=component, ghenv=ghenv, document=document)
    if fallback_path:
        return fallback_path, "document_default"

    return None, "missing"

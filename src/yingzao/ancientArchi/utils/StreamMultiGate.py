# -*- coding: utf-8 -*-
"""
FT_StreamMultiGate — 多索引 Stream Gate
可复用于多个 GH Python 模块中
"""

import collections.abc as abc


class StreamMultiGate(object):
    """
    多索引版 Stream Gate 组件逻辑
    - 可传入单一索引（int）
    - 可传入多个索引（list / panel / 其他可迭代）
    - 当 Gate 为单一有效索引时返回单个流
    - 当 Gate 为多个索引时返回列表
    """

    @staticmethod
    def _coerce_int_list(x):
        """把 Gate 输入统一转为【不重复且保持顺序】的 int 列表。"""
        if x is None:
            return []

        if isinstance(x, abc.Iterable) and not isinstance(x, (str, bytes)):
            raw_iter = x
        else:
            raw_iter = [x]

        ints = []
        for v in raw_iter:
            if v is None:
                continue
            try:
                i = int(v)
            except Exception:
                continue
            ints.append(i)

        # 去重保持顺序
        seen = set()
        result = []
        for i in ints:
            if i not in seen:
                seen.add(i)
                result.append(i)
        return result

    @staticmethod
    def filter_streams(streams, gate):
        """
        主方法 — 多索引过滤

        参数:
            streams : list
                输入数据流（建议 flatten）
            gate : int | list
                Gate 索引或索引列表

        返回:
            单对象（单索引时）或对象列表（多索引）
        """
        indices = StreamMultiGate._coerce_int_list(gate)

        if not indices:
            return None   # 没有有效 gate

        n = len(streams)

        # 单索引 -> 返回单对象
        if len(indices) == 1:
            idx = indices[0]
            if 0 <= idx < n:
                return streams[idx]
            return None

        # 多索引 -> 返回列表
        selected = []
        for idx in indices:
            if 0 <= idx < n:
                selected.append(streams[idx])

        return selected if selected else None

if __name__ == '__main__':
    S = StreamMultiGate.filter_streams(Streams, Gate)
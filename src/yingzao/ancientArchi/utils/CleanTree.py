# -*- coding: utf-8 -*-
"""
Legacy ghpy entry for the CleanTree component.

The stable data-processing API lives in `CleanTreeTool`.
Canvas label and port display helpers live in `CleanTreeDisplay`.
"""

from yingzao.ancientArchi.utils.CleanTreeDisplay import (
    auto_set_component_name,
    refresh_clean_tree_display,
)
from yingzao.ancientArchi.utils.CleanTreeTool import CleanTreeTool


if __name__ == "__main__":
    refresh_clean_tree_display(ghenv.Component, prefix="CleanTree")

    if Tree is None:
        Tree_Cleaned = None
    else:
        Tree_Cleaned = CleanTreeTool.clean(Tree)

# -*- coding: utf-8 -*-
"""
Pure CleanTree data helpers.

Keep Grasshopper UI mutations out of this module so ghpy imports always resolve
to a stable, side-effect free `CleanTreeTool`.
"""

from Grasshopper import DataTree
import Grasshopper.Kernel.Types as ght


class CleanTreeTool(object):

    @staticmethod
    def is_null_or_invalid(x):
        """Return True when the item should be removed from the output tree."""
        if x is None:
            return True

        if isinstance(x, str) and x == "":
            return True

        if isinstance(x, (list, tuple)) and len(x) == 0:
            return True

        if isinstance(x, ght.IGH_Goo):
            try:
                if getattr(x, "IsNull", False):
                    return True
                if not getattr(x, "IsValid", True):
                    return True
            except Exception:
                pass

            try:
                value = x.Value
                if hasattr(value, "IsValid") and (not value.IsValid):
                    return True
            except Exception:
                pass

            return False

        if hasattr(x, "IsValid"):
            try:
                if x.IsValid is False:
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def clean(tree_in):
        """Clean a Grasshopper DataTree by removing null or invalid items."""
        if tree_in is None:
            return None

        if not isinstance(tree_in, DataTree[object]):
            return tree_in

        new_tree = DataTree[object]()

        for path in tree_in.Paths:
            try:
                branch = list(tree_in.Branch(path))
            except Exception:
                branch = []

            valid_items = [
                value for value in branch
                if not CleanTreeTool.is_null_or_invalid(value)
            ]

            if not valid_items:
                continue

            for value in valid_items:
                new_tree.Add(value, path)

        return new_tree

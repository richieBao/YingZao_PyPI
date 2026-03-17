# -*- coding: utf-8 -*-
"""
Grasshopper UI helpers for the CleanTree component.

These functions are intentionally separate from `CleanTreeTool` so ghpy code can
depend on stable data-processing imports without pulling in mutable canvas-label
behavior.
"""


def get_input_source_name(component, input_index=0, default=None):
    """Return the first connected source label for an input param."""
    try:
        input_param = component.Params.Input[input_index]
    except Exception:
        return default

    try:
        sources = input_param.Sources
    except Exception:
        return default

    if sources is None or len(sources) == 0:
        return default

    source = sources[0]
    name = getattr(source, "NickName", None) or getattr(source, "Name", None)
    if not name:
        return default

    name = name.strip()
    return name or default


def sync_io_names(
    component,
    input_index=0,
    output_index=0,
    default_input_name="Tree",
    output_name="Tree_Cleaned",
):
    """
    Keep input/output NickNames readable without mutating parameter Name values.
    """
    try:
        in_param = component.Params.Input[input_index]
        in_param.NickName = (
            get_input_source_name(component, input_index, default_input_name)
            or default_input_name
        )
    except Exception:
        pass

    try:
        out_param = component.Params.Output[output_index]
        out_param.NickName = output_name
    except Exception:
        pass


def set_component_message_from_input(
    component,
    prefix="CleanTree",
    input_index=0,
    clear_when_unconnected=True,
):
    """
    Show upstream context in `Message` instead of renaming the component itself.
    """
    source_name = get_input_source_name(component, input_index)
    if source_name:
        component.Message = "{0}:{1}".format(prefix, source_name)
        return component.Message

    if clear_when_unconnected:
        component.Message = ""

    return component.Message


def auto_set_component_name(component=None, prefix="CleanTree", mutate_name=False):
    """
    Backward-compatible wrapper for older ghpy scripts.

    By default this no longer mutates `Name`. It updates `NickName` only when the
    current label is still auto-generated, and always writes the upstream context
    to `Message` for debugging.
    """
    if component is None:
        try:
            component = ghenv.Component
        except NameError:
            return None

    source_name = get_input_source_name(component)
    if not source_name:
        component.Message = ""
        return None

    new_label = "{0}_{1}".format(prefix, source_name)
    current_nickname = getattr(component, "NickName", "") or ""
    current_name = getattr(component, "Name", "") or ""

    if mutate_name:
        component.Name = new_label
        component.NickName = new_label
    elif (
        current_nickname == ""
        or current_nickname == current_name
        or current_nickname.startswith(prefix + "_")
    ):
        component.NickName = new_label

    component.Message = source_name
    return new_label


def refresh_clean_tree_display(component, prefix="CleanTree"):
    """Update port labels and transient status text for the CleanTree component."""
    sync_io_names(component)
    return set_component_message_from_input(component, prefix=prefix)

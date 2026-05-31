#! python3
# -*- coding: UTF-8 -*-
"""Parameter and data utilities shared across all EasyBIM commands."""

from pyrevit import DB


def get_param_value(element, param_name):
    """Return the value of a parameter by name, or None if not found."""
    param = element.LookupParameter(param_name)
    if param is None:
        return None
    storage = param.StorageType
    if storage == DB.StorageType.String:
        return param.AsString()
    if storage == DB.StorageType.Integer:
        return param.AsInteger()
    if storage == DB.StorageType.Double:
        return param.AsDouble()
    if storage == DB.StorageType.ElementId:
        return param.AsElementId()
    return None


def set_param_value(element, param_name, value):
    """Set a parameter value by name. Must be called inside a Transaction."""
    param = element.LookupParameter(param_name)
    if param is None or param.IsReadOnly:
        return False
    param.Set(value)
    return True

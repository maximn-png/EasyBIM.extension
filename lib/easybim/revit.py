#! python3
# -*- coding: UTF-8 -*-
"""Revit API helper utilities shared across all EasyBIM commands."""

from pyrevit import revit, DB


def get_active_doc():
    """Return the currently active Revit document."""
    return revit.doc


def get_active_view():
    """Return the currently active view."""
    return revit.active_view


def get_elements_by_category(doc, built_in_category):
    """Collect all elements of a given BuiltInCategory in the document."""
    return DB.FilteredElementCollector(doc)\
             .OfCategory(built_in_category)\
             .WhereElementIsNotElementType()\
             .ToElements()


def transaction(doc, name):
    """Return an open DB.Transaction. Use as a context manager:
        with revit.transaction(doc, 'My Change') as t:
            ...
    """
    return DB.Transaction(doc, name)

# -*- coding: utf-8 -*-
__title__ = "Scan CAD"
__doc__ = "Scans linked CAD files and counts elements"

from Autodesk.Revit.DB import *
from pyrevit import revit
doc = revit.doc

for imp in FilteredElementCollector(doc).OfClass(ImportInstance):
    name_param = imp.LookupParameter("Name")
    name = name_param.AsString() if name_param else "Unknown"
    print("Link: {} | ID: {}".format(name, imp.Id))
    geo = imp.get_Geometry(Options())
    if geo:
        blocks = texts = lines = 0
        for g in geo:
            if hasattr(g, 'GetInstanceGeometry'):
                for sub in g.GetInstanceGeometry():
                    t = type(sub).__name__
                    if "Text" in t: texts += 1
                    elif "Line" in t or "Curve" in t: lines += 1
                    else: blocks += 1
        print("  Texts: {} | Lines: {} | Other: {}".format(texts, lines, blocks))

print("\nDone!")

# -*- coding: utf-8 -*-
__title__ = "Scan CAD"
__doc__ = "Deep scan of linked CAD files"

from Autodesk.Revit.DB import *
from pyrevit import revit
doc = revit.doc

opts = Options()
opts.DetailLevel = ViewDetailLevel.Fine

for imp in FilteredElementCollector(doc).OfClass(ImportInstance):
    name_param = imp.LookupParameter("Name")
    name = name_param.AsString() if name_param else "Unknown"
    print("=== {} (ID: {}) ===".format(name, imp.Id))

    geo = imp.get_Geometry(opts)
    if not geo:
        print("  No geometry")
        continue

    type_counts = {}
    total = 0

    def scan_geo(geo_elem, depth=0):
        global total
        for g in geo_elem:
            t = type(g).__name__
            type_counts[t] = type_counts.get(t, 0) + 1
            total += 1
            if hasattr(g, 'GetInstanceGeometry'):
                try:
                    sub = g.GetInstanceGeometry()
                    if sub:
                        scan_geo(sub, depth+1)
                except:
                    pass
            if hasattr(g, 'GetSymbolGeometry'):
                try:
                    sub = g.GetSymbolGeometry()
                    if sub:
                        scan_geo(sub, depth+1)
                except:
                    pass

    scan_geo(geo)

    print("  Geometry types found:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print("    {}: {}".format(t, c))
    print("  Total: {}".format(total))

    # Try to read CAD layers
    print("\n  CAD Layers:")
    try:
        cat = imp.Category
        if cat and cat.SubCategories:
            for sub in cat.SubCategories:
                print("    Layer: {}".format(sub.Name))
    except Exception as e:
        print("    Error reading layers: {}".format(e))

print("\nDone!")

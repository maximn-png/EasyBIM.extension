# -*- coding: utf-8 -*-
__title__ = "Scan CAD"
__doc__ = u"סריקת קבצי CAD ויצירת Drafting View עם טבלת כמויות סמלי חשמל"

from Autodesk.Revit.DB import (
    FilteredElementCollector, ImportInstance, Options, ViewDetailLevel,
    GeometryInstance, Transaction, ViewDrafting, ViewFamilyType, ViewFamily,
    TextNote, TextNoteType, TextNoteOptions, XYZ, ElementId, Line,
    DetailLine, GraphicsStyle
)
from pyrevit import revit

doc = revit.doc
uidoc = revit.uidoc

ELECTRICAL_KEYWORDS = [
    u'חשמל', u'לוח', u'שקע',
    u'מפסק', u'תאורה', u'כבל',
    u'גופ', u'צינור',
    'ELEC', 'POWER', 'LIGHT', 'PANEL', 'OUTLET', 'SWITCH',
    'FIXTURE', 'LAMP', 'SOCKET', 'E-', 'EL-', 'CABLE', 'CONDUIT'
]

def is_electrical(name):
    n = name.upper()
    return any(kw.upper() in n for kw in ELECTRICAL_KEYWORDS)

def count_blocks_by_layer(geo_elem, counts, depth=0):
    if depth > 4:
        return
    for g in geo_elem:
        layer = u"Unknown"
        try:
            style_id = g.GraphicsStyleId
            if style_id != ElementId.InvalidElementId:
                style = doc.GetElement(style_id)
                if style and style.GraphicsStyleCategory:
                    layer = style.GraphicsStyleCategory.Name
        except:
            pass
        if isinstance(g, GeometryInstance):
            counts[layer] = counts.get(layer, 0) + 1
            try:
                sub = g.GetInstanceGeometry()
                if sub:
                    count_blocks_by_layer(sub, counts, depth + 1)
            except:
                pass

opts = Options()
opts.DetailLevel = ViewDetailLevel.Fine

all_data = {}

for imp in FilteredElementCollector(doc).OfClass(ImportInstance):
    name_param = imp.LookupParameter("Name")
    cad_name = name_param.AsString() if name_param else u"Unknown"
    geo = imp.get_Geometry(opts)
    if not geo:
        continue
    counts = {}
    count_blocks_by_layer(geo, counts)
    elec = {k: v for k, v in counts.items() if is_electrical(k)}
    if elec:
        all_data[cad_name] = elec
    else:
        all_data[cad_name] = counts

if not all_data:
    print(u"לא נמצאו קבצי CAD עם נתונים.")
else:
    with Transaction(doc, u"CAD Electrical Scan Table") as t:
        t.Start()

        vft = None
        for vt in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            if vt.ViewFamily == ViewFamily.Drafting:
                vft = vt
                break

        view = ViewDrafting.Create(doc, vft.Id)
        try:
            view.Name = u"CAD Electrical Scan"
        except:
            import time
            view.Name = u"CAD Electrical Scan {}".format(int(time.time()) % 10000)

        text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()

        COL0 = 0.0
        COL1 = 2.5
        ROW_H = 0.18
        y = 0.0

        def add_text(x, row, text):
            opts_tn = TextNoteOptions(text_type_id)
            TextNote.Create(doc, view.Id, XYZ(x, y - row * ROW_H, 0), text, opts_tn)

        row = 0
        add_text(COL0, row, u"=== CAD Electrical Symbol Count ===")
        row += 2

        for cad_name, layers in all_data.items():
            add_text(COL0, row, u"File: {}".format(cad_name))
            row += 1
            add_text(COL0, row, u"Layer / Symbol")
            add_text(COL1, row, u"Count")
            row += 1

            total = 0
            for layer, count in sorted(layers.items(), key=lambda x: -x[1]):
                add_text(COL0, row, layer)
                add_text(COL1, row, str(count))
                total += count
                row += 1

            add_text(COL0, row, u"TOTAL")
            add_text(COL1, row, str(total))
            row += 2

        t.Commit()

    uidoc.ActiveView = view
    print(u"Done! Drafting View '{}' created.".format(view.Name))

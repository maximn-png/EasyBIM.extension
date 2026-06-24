# -*- coding: utf-8 -*-
"""MEP Auto-Tagging helpers — saved from Solution Section button.

Intended for reuse in a future dedicated tagging button.

Dependencies:
  - `doc`    : Revit Document (DB.Document) — must be provided by the caller
  - `logger` : pyrevit script logger — must be provided by the caller

Typical usage in a button script:
    from Autodesk.Revit import DB
    from pyrevit import revit, script
    import mep_tag_helpers as th

    doc    = revit.doc
    logger = script.get_logger()
    th.doc    = doc
    th.logger = logger

    with DB.Transaction(doc, "Auto-tag section") as t:
        t.Start()
        th.place_section_tags(active_view)
        t.Commit()
"""

from Autodesk.Revit import DB

# These are set by the caller before using any function.
doc    = None
logger = None

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — tag family / type names
# ─────────────────────────────────────────────────────────────────────────────

# Each entry is (family_name, type_name).
# type_name = None → use the first (and only) type found in the family.
TAG_FAMILY_RECT_DUCT    = (u"EB_Duct Size Tag",                        None)
TAG_FAMILY_CIRC_DUCT    = (u"EB_Circular Duct Size Tag",               None)
TAG_FAMILY_CABLE_TRAY   = (u"EB_M_Cable Tray Type name + Size Tag",    None)
TAG_FAMILY_CONDUIT      = (u"M_Conduit Size Tag",                      None)
TAG_FAMILY_PIPE_PLASTIC = (u"EB_Pipe Tag-Plastic Pressure",  u"3 mm")
TAG_FAMILY_PIPE_METAL   = (u"EB_Pipe Tag-Metal Pressure",    u"3 mm")

# Keywords matched case-insensitively against the pipe "Material" parameter.
# Anything not matching is treated as metal.
PLASTIC_PIPE_MATERIAL_KEYWORDS = [
    u"plastic", u"pvc", u"upvc", u"pe", u"pp", u"pex", u"cpvc",
    u"polyethylene", u"polypropylene",
    u"פלסטיק",            # פלסטיק
    u"פוליאתילן",  # פוליאתילן
    u"פוליפרופילן",  # פוליפרופילן
    u"פי.וי.סי",          # פי.וי.סי
    u"פ.ו.צ",                             # פ.ו.צ
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _find_tag_symbol(family_name, type_name=None):
    """Return a FamilySymbol from the named annotation family.

    Normalises names by extracting ASCII letters/digits only (no re, no
    isalnum) — behaviour is identical across every IronPython 2.7 build.
    Falls back to built-in params for sym.Name because annotation
    FamilySymbols in Revit 2024 raise an exception on the .Name property.
    """
    def _key(s):
        try:
            result = []
            word   = []
            for c in u"{}".format(s).lower():
                if (u'a' <= c <= u'z') or (u'0' <= c <= u'9'):
                    word.append(c)
                elif word:
                    result.append(u"".join(word))
                    word = []
            if word:
                result.append(u"".join(word))
            return u" ".join(result)
        except Exception:
            return u""

    _fn = _key(family_name)
    _tn = _key(type_name) if type_name is not None else None
    family_matches = []
    for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            fname_key = _key(sym.Family.Name)
        except Exception:
            continue
        if fname_key != _fn:
            continue
        try:
            if _tn is None:
                return sym
            tname = None
            try:
                tname = u"{}".format(sym.Name)
            except Exception:
                pass
            if not tname:
                for _bip in (DB.BuiltInParameter.SYMBOL_NAME_PARAM,
                             DB.BuiltInParameter.ALL_MODEL_TYPE_NAME):
                    try:
                        _p = sym.get_Parameter(_bip)
                        if _p:
                            tname = _p.AsString()
                            if tname:
                                break
                    except Exception:
                        pass
            if not tname:
                continue
            if _key(tname) == _tn:
                return sym
            family_matches.append(tname)
        except Exception as _te:
            if logger:
                logger.warning(u"Tag symbol inner error ({}): {}".format(
                    family_name, _te))
    if logger:
        if family_matches:
            logger.warning(
                u"Tag family '{}': type '{}' not found. Available: {}".format(
                    family_name, type_name,
                    u", ".join(u"'{}'".format(n) for n in family_matches)))
        else:
            logger.warning(
                u"Tag family '{}' not found. fn_key='{}' tn_key='{}'".format(
                    family_name, _fn, _tn))
    return None


def _pipe_is_plastic(pipe):
    """Return True if the pipe's Material parameter indicates a plastic material."""
    for source in (pipe, doc.GetElement(pipe.GetTypeId())):
        if source is None:
            continue
        try:
            p = source.LookupParameter(u"Material")
            if p is None:
                continue
            if p.StorageType == DB.StorageType.ElementId:
                mat = doc.GetElement(p.AsElementId())
                val = (mat.Name if mat else u"").lower()
            elif p.StorageType == DB.StorageType.String:
                val = (p.AsString() or u"").lower()
            else:
                continue
            if any(kw in val for kw in PLASTIC_PIPE_MATERIAL_KEYWORDS):
                return True
        except Exception:
            pass
    return False


def _tag_key_for_elem(elem):
    """Return the tag-family key string for a taggable MEP element, or None."""
    try:
        cat_int = elem.Category.Id.IntegerValue
    except Exception:
        return None
    if cat_int == int(DB.BuiltInCategory.OST_DuctCurves):
        p = elem.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
        return u"circ_duct" if (p and p.HasValue) else u"rect_duct"
    if cat_int == int(DB.BuiltInCategory.OST_CableTray):
        return u"cable_tray"
    if cat_int == int(DB.BuiltInCategory.OST_Conduit):
        return u"conduit"
    if cat_int == int(DB.BuiltInCategory.OST_PipeCurves):
        return u"pipe_plastic" if _pipe_is_plastic(elem) else u"pipe_metal"
    return None


def _elem_mid_local_y(elem, inv_transform):
    """Y coordinate of element midpoint in view-local space (height in section)."""
    try:
        loc = elem.Location
        if hasattr(loc, u"Curve"):
            pt = loc.Curve.Evaluate(0.5, True)
        elif hasattr(loc, u"Point"):
            pt = loc.Point
        else:
            return 0.0
        return inv_transform.OfPoint(pt).Y
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def place_section_tags(view):
    """Place auto-aligned MEP tags in a left column for all elements in the view.

    Tags are sorted top-to-bottom by element elevation and distributed evenly
    within the section crop so they never overlap.  Leaders connect each label
    to its element.

    Must be called inside an open Revit Transaction.
    `doc` and `logger` module-level variables must be set by the caller first.
    """
    _sym_map = {
        u"rect_duct":    TAG_FAMILY_RECT_DUCT,
        u"circ_duct":    TAG_FAMILY_CIRC_DUCT,
        u"cable_tray":   TAG_FAMILY_CABLE_TRAY,
        u"conduit":      TAG_FAMILY_CONDUIT,
        u"pipe_plastic": TAG_FAMILY_PIPE_PLASTIC,
        u"pipe_metal":   TAG_FAMILY_PIPE_METAL,
    }

    # Resolve and activate symbols; warn once for any that are missing.
    symbols = {}
    missing = []
    for key, (fname, tname) in _sym_map.items():
        sym = _find_tag_symbol(fname, tname)
        if sym:
            if not sym.IsActive:
                sym.Activate()
            symbols[key] = sym
        else:
            missing.append(u"{}{}".format(
                fname, u" / {}".format(tname) if tname else u""))
    if missing and logger:
        logger.warning(u"Auto-tag: families not loaded — {}".format(
            u", ".join(missing)))

    # Collect taggable elements visible in the view (runs only, not fittings).
    _tag_cats = [
        DB.BuiltInCategory.OST_DuctCurves,
        DB.BuiltInCategory.OST_PipeCurves,
        DB.BuiltInCategory.OST_CableTray,
        DB.BuiltInCategory.OST_Conduit,
    ]
    elems = []
    for cat in _tag_cats:
        try:
            for e in (DB.FilteredElementCollector(doc, view.Id)
                      .OfCategory(cat)
                      .WhereElementIsNotElementType()):
                key = _tag_key_for_elem(e)
                if key and key in symbols:
                    elems.append(e)
        except Exception:
            pass

    if not elems:
        return

    crop = view.CropBox
    ct   = crop.Transform    # local → world
    inv  = ct.Inverse        # world → local

    # Discard elements whose midpoint falls outside the crop box (X and Y).
    # FilteredElementCollector(view) can include elements that are within the
    # section depth but beyond the visible crop region.
    def _in_crop(e):
        try:
            loc = e.Location
            if hasattr(loc, u"Curve"):
                pt = loc.Curve.Evaluate(0.5, True)
            elif hasattr(loc, u"Point"):
                pt = loc.Point
            else:
                return False
            lp = inv.OfPoint(pt)
            return (crop.Min.X <= lp.X <= crop.Max.X and
                    crop.Min.Y <= lp.Y <= crop.Max.Y)
        except Exception:
            return True  # keep if we can't determine position

    elems = [e for e in elems if _in_crop(e)]
    if not elems:
        return

    crop_w = abs(crop.Max.X - crop.Min.X)
    crop_h = abs(crop.Max.Y - crop.Min.Y)

    # Tag column sits OUTSIDE the crop, 3 % of view width to the left of the
    # section boundary.  The leader bridges from the label to the element.
    col_offset = crop_w * 0.03

    # Sort elements top → bottom by midpoint height in section.
    elems.sort(key=lambda e: _elem_mid_local_y(e, inv), reverse=True)

    # Distribute tag Y positions evenly from top to bottom of the visible crop,
    # keeping a 5 % margin from the edges.  This preserves the height-sorted
    # order and guarantees no overlaps and no out-of-bounds tags regardless of
    # how many elements share the same elevation.
    n      = len(elems)
    margin = crop_h * 0.05
    y_top  = crop.Max.Y - margin
    y_bot  = crop.Min.Y + margin
    if n == 1:
        raw    = _elem_mid_local_y(elems[0], inv)
        tag_ys = [max(y_bot, min(y_top, raw))]
    else:
        step   = (y_top - y_bot) / float(n - 1)
        tag_ys = [y_top - step * i for i in range(n)]

    x_local = crop.Min.X - col_offset  # column sits outside crop, left of boundary

    for i, elem in enumerate(elems):
        key = _tag_key_for_elem(elem)
        sym = symbols.get(key)
        if sym is None:
            continue
        tag_pos = ct.OfPoint(DB.XYZ(x_local, tag_ys[i], 0.0))
        ref     = DB.Reference(elem)
        try:
            tag = DB.IndependentTag.Create(
                doc, view.Id, ref,
                True,
                DB.TagMode.TM_ADDBY_CATEGORY,
                DB.TagOrientation.Horizontal,
                tag_pos
            )
            tag.ChangeTypeId(sym.Id)
            try:
                tag.TagOrientation = DB.TagOrientation.Horizontal
            except Exception:
                pass
        except Exception as ex:
            if logger:
                logger.warning(u"Tag failed (id {}): {}".format(
                    elem.Id.IntegerValue, ex))
# -*- coding: utf-8 -*-
"""Dekel — Run All (Cable Trays + Power)"""

__title__  = "Run All"
__doc__    = ("\u05de\u05e8\u05d9\u05e5 \u05d0\u05ea \u05e9\u05e0\u05d9 \u05d4\u05db\u05dc\u05d9\u05dd \u05d1\u05e8\u05e6\u05e3 \u2014 \u05ea\u05e2\u05dc\u05d5\u05ea \u05d5\u05d0\u05d7\u05e8 \u05db\u05da \u05e6\u05d9\u05d5\u05d3 \u05d7\u05e9\u05de\u05dc.\n\n"
              "\u05d1\u05d5\u05d7\u05e8\u05d9\u05dd \u05e7\u05d5\u05d1\u05e5 \u05d0\u05e7\u05e1\u05dc \u05e4\u05e2\u05dd \u05d0\u05d7\u05ea, \u05d5\u05e9\u05e0\u05d9 \u05d4\u05db\u05dc\u05d9\u05dd \u05de\u05e9\u05ea\u05de\u05e9\u05d9\u05dd \u05d1\u05d5.\n"
              "\u05d0\u05dd \u05db\u05dc\u05d9 \u05d0\u05d7\u05d3 \u05e0\u05db\u05e9\u05dc \u2014 \u05d4\u05e9\u05e0\u05d9 \u05d1\u05db\u05dc \u05d6\u05d0\u05ea \u05e8\u05e5, \u05d5\u05d1\u05e1\u05d5\u05e3 \u05de\u05d5\u05e6\u05d2 \u05e1\u05d9\u05db\u05d5\u05dd.")
__author__ = "Yamit Bettman"

import os
import sys
import traceback

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult
from Autodesk.Revit.UI import TaskDialog

# ----------------------------------------------------------------------------
# נתיבי שני הכלים. ברירת מחדל: הקבצים יושבים כל אחד בתיקיית ה-pushbutton שלו,
# לצד כפתור ה-Run All. עדכן את הנתיבים אם המבנה שונה אצלך.
#
# מבנה מומלץ (תוסף pyRevit):
#   DBA.tab/
#     Dekel.panel/
#       CableTrays.pushbutton/script.py
#       Power.pushbutton/script.py
#       RunAll.pushbutton/script.py   <-- הקובץ הזה
# ----------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_panel = os.path.dirname(_here)   # תיקיית ה-panel שמכילה את כל הכפתורים

# ── עקיפה ידנית ──────────────────────────────────────────────────────────
# נתיבים מדויקים לשני הכלים — מקובעים כדי למנוע ניחוש שמות תיקיות.
CABLETRAYS_OVERRIDE = r"C:\Users\YamitBettman\AppData\Roaming\pyRevit\Extensions\EasyBIM.extension\EasyBIM.tab\DBA.Panel\Cable Trays.pushbutton\script.py"
POWER_OVERRIDE      = r"C:\Users\YamitBettman\AppData\Roaming\pyRevit\Extensions\EasyBIM.extension\EasyBIM.tab\DBA.Panel\Power.pushbutton\script.py"

# מועמדים אפשריים לכל כלי — ננסה כמה מיקומים נפוצים ונשתמש בראשון שקיים.
def _find_tool(folder_names, override=None, file_name="script.py"):
    if override and os.path.isfile(override):
        return override
    candidates = []
    for fld in folder_names:
        candidates.append(os.path.join(_panel, fld, file_name))
        candidates.append(os.path.join(_here, fld, file_name))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

CABLETRAYS_SCRIPT = _find_tool(
    ["CableTrays.pushbutton", "Cable Trays.pushbutton", "cabletrays.pushbutton"],
    CABLETRAYS_OVERRIDE)
POWER_SCRIPT = _find_tool(
    ["Power.pushbutton", "power.pushbutton"],
    POWER_OVERRIDE)

# ----------------------------------------------------------------------------
# 1. בחירת קובץ/קבצי אקסל — פעם אחת לשני הכלים
# ----------------------------------------------------------------------------
dlg = OpenFileDialog()
dlg.Title       = u"\u05d1\u05d7\u05e8 \u05e7\u05d5\u05d1\u05e5/\u05e7\u05d1\u05e6\u05d9 \u05d8\u05d1\u05dc\u05d0\u05d5\u05ea \u05d3\u05e7\u05dc (\u05e0\u05d9\u05ea\u05df \u05dc\u05d1\u05d7\u05d5\u05e8 \u05de\u05e1\u05e4\u05e8 \u05e7\u05d1\u05e6\u05d9\u05dd)"
dlg.Filter      = "Excel Files (*.xlsx)|*.xlsx"
dlg.Multiselect = True

if dlg.ShowDialog() != DialogResult.OK or not dlg.FileNames:
    TaskDialog.Show("Dekel", u"\u05dc\u05d0 \u05e0\u05d1\u05d7\u05e8 \u05e7\u05d5\u05d1\u05e5.")
    sys.exit()

paths = list(dlg.FileNames)
print(u"\u05e7\u05d1\u05e6\u05d9\u05dd \u05e9\u05e0\u05d1\u05d7\u05e8\u05d5: {}".format(len(paths)))
for p in paths:
    print(u"  \u2022 {}".format(p))

# נעביר את הבחירה לשני הכלים דרך משתנה סביבה
os.environ["DEKEL_XLSX_PATHS"] = u";".join(paths)

# ----------------------------------------------------------------------------
# 2. הרצת כל כלי בתוך namespace נקי. SystemExit מאחד הכלים לא יפיל את ה-Run All.
# ----------------------------------------------------------------------------
def run_tool(label, script_path):
    if not script_path:
        return (label, "missing", u"\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0 \u05e7\u05d5\u05d1\u05e5 \u05d4\u05e1\u05e7\u05e8\u05d9\u05e4\u05d8 \u05e9\u05dc \u05d4\u05db\u05dc\u05d9")
    print(u"\n" + u"=" * 60)
    print(u">>> \u05de\u05e8\u05d9\u05e5: {}".format(label))
    print(u"=" * 60)
    # תיקיית הסקריפט צריכה להיות ב-path כדי שייבוא dekel_shared_params יעבוד
    folder = os.path.dirname(script_path)
    if folder not in sys.path:
        sys.path.append(folder)
    try:
        # קריאה מפורשת ב-UTF-8 כדי לשמר את הטקסט העברי. בלי זה IronPython
        # קורא את הבייטים בקידוד שגוי והעברית נשברת.
        import codecs as _codecs
        with _codecs.open(script_path, "r", encoding="utf-8") as f:
            src = f.read()
        # הסר BOM אם קיים
        if src and src[0] == u"\ufeff":
            src = src[1:]
        # כשמקמפלים מחרוזת unicode, שורת ה-# -*- coding -*- מיותרת ועלולה
        # להפיל את compile. מנטרלים אותה בשתי השורות הראשונות.
        _lines = src.split(u"\n")
        for _i in range(min(2, len(_lines))):
            if u"coding" in _lines[_i] and u"-*-" in _lines[_i]:
                _lines[_i] = u"# (coding line removed for exec)"
        src = u"\n".join(_lines)
        # __file__ נכון כדי שה-fallback של sys.path בתוך הכלי יעבוד
        ns = {"__name__": "__main__", "__file__": script_path}
        exec(compile(src, script_path, "exec"), ns)
        return (label, "ok", u"")
    except SystemExit:
        # הכלי קרא ל-sys.exit() — נחשב כסיום (ייתכן עקב 'לא נמצאו אלמנטים')
        return (label, "exit", u"הכלי סיים מוקדם (ייתכן ללא אלמנטים מתאימים, או בוטל)")
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return (label, "fail", u"{}".format(e))

results = []
try:
    results.append(run_tool(u"Cable Trays", CABLETRAYS_SCRIPT))
    results.append(run_tool(u"Power", POWER_SCRIPT))
finally:
    # ניקוי — שלא ידלוף לריצות עתידיות של הכלים לבד
    if "DEKEL_XLSX_PATHS" in os.environ:
        del os.environ["DEKEL_XLSX_PATHS"]

# ----------------------------------------------------------------------------
# 3. סיכום
# ----------------------------------------------------------------------------
_STATUS_HE = {
    "ok":      u"\u2713 \u05d4\u05e1\u05ea\u05d9\u05d9\u05dd",
    "exit":    u"\u26a0 \u05e1\u05d9\u05d9\u05dd \u05de\u05d5\u05e7\u05d3\u05dd",
    "fail":    u"\u2717 \u05e0\u05db\u05e9\u05dc",
    "missing": u"\u2717 \u05e7\u05d5\u05d1\u05e5 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0",
}

lines = []
for label, status, detail in results:
    line = u"{}: {}".format(label, _STATUS_HE.get(status, status))
    if detail:
        line += u"\n   {}".format(detail)
    lines.append(line)

summary = u"\u05e1\u05d9\u05db\u05d5\u05dd Run All\n\n" + u"\n".join(lines)
print(u"\n" + summary)
TaskDialog.Show("Dekel - Run All", summary)

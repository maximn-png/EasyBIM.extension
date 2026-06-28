# -*- coding: utf-8 -*-
"""Solution Section — EasyBIM MEP Coordination.

4-step wizard: pick an existing section + sheet, choose which linked models to
capture, then create a coordinated solution section placed on the same sheet.
Wrapped in named transactions (fully undoable).
"""

__title__ = "Solution\nSection"
__author__ = "EasyBIM"
__doc__ = "Create a coordination section from linked MEP models."

import clr
import os
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')
clr.AddReference('System')

from Autodesk.Revit import DB
import System
import System.Windows
import System.Windows.Controls as WC
import System.Windows.Media as WM
import System.Windows.Input as WI
import System.Collections.Generic as SCG

from System.Windows.Markup import XamlReader
from System.IO import StringReader
from System.Xml import XmlReader as SysXmlReader

from pyrevit import revit, script, forms

doc = revit.doc
logger = script.get_logger()

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

EXISTING_TEMPLATE = "EB_MEP_CUR_SE_1-50"
SOLUTION_TEMPLATE = "EB_MEP_SOL_SE_1-50"
SOLUTION_WORKSET  = "MEP Solution"
SCALE             = 50

EB_SS_PREFIX = "EB_SS:"

MEP_CATEGORIES = [
    DB.BuiltInCategory.OST_DuctCurves,
    DB.BuiltInCategory.OST_DuctFitting,
    DB.BuiltInCategory.OST_DuctAccessory,
    DB.BuiltInCategory.OST_PipeCurves,
    DB.BuiltInCategory.OST_PipeFitting,
    DB.BuiltInCategory.OST_PipeAccessory,
    DB.BuiltInCategory.OST_CableTray,
    DB.BuiltInCategory.OST_CableTrayFitting,
    DB.BuiltInCategory.OST_Conduit,
    DB.BuiltInCategory.OST_ConduitFitting,
    DB.BuiltInCategory.OST_MechanicalEquipment,
    DB.BuiltInCategory.OST_PlumbingFixtures,
    DB.BuiltInCategory.OST_ElectricalEquipment,
    DB.BuiltInCategory.OST_ElectricalFixtures,
    DB.BuiltInCategory.OST_LightingFixtures,
    DB.BuiltInCategory.OST_DuctInsulations,
    DB.BuiltInCategory.OST_PipeInsulations,
]

# ─────────────────────────────────────────────────────────────────────────────
# DATA GATHERING
# ─────────────────────────────────────────────────────────────────────────────

def get_section_views():
    views = DB.FilteredElementCollector(doc).OfClass(DB.View)
    return sorted(
        [v for v in views if v.ViewType == DB.ViewType.Section and not v.IsTemplate],
        key=lambda v: v.Name
    )


def get_sheets():
    sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
    return sorted(list(sheets), key=lambda s: s.SheetNumber)


def get_linked_models():
    results = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        link_doc = li.GetLinkDocument()
        name = li.Name
        parts = name.upper().replace(u"-", u" ").split()
        tag = u"MEP"
        disc = u""
        for p in parts:
            if p in (u"ME", u"MECH", u"HVAC"):
                tag = u"MEP"; disc = u"Mechanical"; break
            if p in (u"PL", u"PLM", u"PLUMBING"):
                tag = u"MEP"; disc = u"Plumbing"; break
            if p in (u"EL", u"ELEC", u"ELECTRICAL"):
                tag = u"MEP"; disc = u"Electrical"; break
            if p in (u"ST", u"STR", u"STRUCT", u"STRUCTURAL"):
                tag = u"Structural"; disc = u"Structural"; break
            if p in (u"AR", u"ARC", u"ARCH", u"ARCHITECTURAL"):
                tag = u"Architectural"; disc = u"Architecture"; break
        results.append({
            u"instance": li,
            u"name": name,
            u"disc": disc or name,
            u"tag": tag,
            u"loaded": link_doc is not None,
            u"doc": link_doc,
            u"on": link_doc is not None,
        })
    return results


def find_view_template(name):
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.IsTemplate and v.Name == name:
            return v
    return None


def build_section_box_from_view(view):
    """Build a valid BoundingBoxXYZ for ViewSection.CreateSection.

    CropBox.Transform can have non-unit basis vectors and unset MinEnabled/
    MaxEnabled flags. Rebuild from the CropBox's own (normalized) axes rather
    than view.ViewDirection, which can be opposite to the CropBox's Z convention
    and would flip the new section to face the wrong direction.
    """
    crop = view.CropBox
    ct   = crop.Transform

    t = DB.Transform.Identity
    t.BasisX = ct.BasisX.Normalize()
    t.BasisY = ct.BasisY.Normalize()
    t.BasisZ = ct.BasisZ.Normalize()
    t.Origin = ct.Origin

    c_min, c_max = crop.Min, crop.Max
    z_near = min(c_min.Z, c_max.Z)
    z_far  = max(c_min.Z, c_max.Z)
    if z_far - z_near < 0.5:       # guard: ensure meaningful depth (ft)
        z_far = z_near + 1.0

    box = DB.BoundingBoxXYZ()
    box.Transform = t
    box.Min = DB.XYZ(c_min.X, c_min.Y, z_near)
    box.Max = DB.XYZ(c_max.X, c_max.Y, z_far)
    for i in range(3):
        box.set_MinEnabled(i, True)
        box.set_MaxEnabled(i, True)
    return box


def find_section_vft():
    for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if vft.ViewFamily == DB.ViewFamily.Section:
            return vft
    return None



def _sheet_vp_rects(sheet, exclude_view_id=None):
    """Return (min_x, min_y, max_x, max_y) tuples for viewports on the sheet.

    Optionally skip the viewport that belongs to exclude_view_id (so we don't
    count the existing section against itself when it's already on the sheet).
    """
    rects = []
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        if vp is None:
            continue
        if exclude_view_id is not None and vp.ViewId == exclude_view_id:
            continue
        try:
            ol = vp.GetBoxOutline()
            rects.append((ol.MinimumPoint.X, ol.MinimumPoint.Y,
                           ol.MaximumPoint.X, ol.MaximumPoint.Y))
        except Exception:
            pass
    return rects


def _vp_overlaps(cx, cy, w, h, rects, pad=0.05):
    l, r = cx - w / 2.0 - pad, cx + w / 2.0 + pad
    b, t = cy - h / 2.0 - pad, cy + h / 2.0 + pad
    for (rl, rb, rr, rt) in rects:
        if l < rr and r > rl and b < rt and t > rb:
            return True
    return False


def _find_sheet_spot(rects, s_left, s_right, s_bot, s_top,
                     vp_w, vp_h, margin=0.1, start_x=None, preferred_y=None):
    """Scan left→right, row-by-row until a non-overlapping centre is found."""
    x = start_x if start_x is not None else s_left + margin + vp_w / 2.0
    y = preferred_y if preferred_y is not None else (s_top + s_bot) / 2.0
    step = max(vp_w / 6.0, 0.04)
    for _ in range(400):
        if x + vp_w / 2.0 + margin > s_right:
            # Wrap: start a new row below
            x = s_left + margin + vp_w / 2.0
            y -= (vp_h + margin * 2.0)
            if y - vp_h / 2.0 < s_bot + margin:
                break
        if not _vp_overlaps(x, y, vp_w, vp_h, rects):
            return x, y
        x += step
    return x, y   # best-effort fallback


def get_or_create_workset(name):
    if not doc.IsWorkshared:
        return None
    for ws in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        if ws.Name == name:
            return ws.Id
    new_ws = DB.Workset.Create(doc, name)
    return new_ws.Id

# ─────────────────────────────────────────────────────────────────────────────
# SKIP-DUPLICATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_existing_stamped_uids():
    uids = set()
    collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
    for elem in collector:
        try:
            p = elem.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if p:
                val = p.AsString()
                if val and val.startswith(EB_SS_PREFIX):
                    for uid_part in val[len(EB_SS_PREFIX):].split(u"|"):
                        uid_part = uid_part.strip()
                        if uid_part:
                            uids.add(uid_part)
        except Exception:
            pass
    return uids


def stamp_element(elem, source_uid):
    try:
        p = elem.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and not p.IsReadOnly:
            existing = p.AsString() or u""
            if existing.startswith(EB_SS_PREFIX):
                parts = set(u.strip() for u in existing[len(EB_SS_PREFIX):].split(u"|") if u.strip())
                parts.add(source_uid)
                p.Set(EB_SS_PREFIX + u"|".join(sorted(parts)))
            elif not existing:
                p.Set(EB_SS_PREFIX + source_uid)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# CORE OPERATION
# ─────────────────────────────────────────────────────────────────────────────

def collect_mep_ids_in_volume(link_doc, host_crop_box, link_transform):
    """Collect MEP element IDs from a linked model within the section volume.

    CropBox.Min/Max are in the box's LOCAL coordinate system, not world space.
    Apply CropBox.Transform first to get world corners, then transform to link space.
    """
    try:
        inv = link_transform.Inverse
    except Exception:
        return []

    ct = host_crop_box.Transform   # local → world
    mn = host_crop_box.Min
    mx = host_crop_box.Max

    # 8 box corners: local → world → link-local
    world_corners = [
        ct.OfPoint(DB.XYZ(x, y, z))
        for x in [mn.X, mx.X]
        for y in [mn.Y, mx.Y]
        for z in [mn.Z, mx.Z]
    ]
    lc = [inv.OfPoint(wc) for wc in world_corners]
    outline = DB.Outline(
        DB.XYZ(min(c.X for c in lc), min(c.Y for c in lc), min(c.Z for c in lc)),
        DB.XYZ(max(c.X for c in lc), max(c.Y for c in lc), max(c.Z for c in lc)),
    )
    bbox_filter = DB.BoundingBoxIntersectsFilter(outline)

    ids = []
    for cat in MEP_CATEGORIES:
        try:
            combined = DB.LogicalAndFilter(DB.ElementCategoryFilter(cat), bbox_filter)
            for elem in (DB.FilteredElementCollector(link_doc)
                           .WherePasses(combined)
                           .WhereElementIsNotElementType()
                           .ToElements()):
                ids.append(elem.Id)
        except Exception:
            pass
    return ids


def run(existing_section, sheet, selected_links, skip_duplicates=True,
        existing_template=None):
    """Execute the full coordination build. Returns (per-link-count-dict, new_section_view)."""
    results = {}
    view_name = u"{} Solution".format(existing_section.Name)
    existing_uids = get_existing_stamped_uids() if skip_duplicates else set()
    new_section = [None]

    tg = DB.TransactionGroup(doc, u"EasyBIM: Solution Section")
    tg.Start()
    try:
        # ── Txn 1: workset + copy elements ────────────────────────────────────
        t1 = DB.Transaction(doc, u"EasyBIM: Copy MEP elements")
        t1.Start()
        ws_id = get_or_create_workset(SOLUTION_WORKSET)
        crop_box = existing_section.CropBox

        for link_info in selected_links:
            if not link_info[u"loaded"] or link_info[u"doc"] is None:
                results[link_info[u"name"]] = 0
                continue

            link_doc = link_info[u"doc"]
            transform = link_info[u"instance"].GetTotalTransform()
            src_ids = collect_mep_ids_in_volume(link_doc, crop_box, transform)

            if skip_duplicates:
                filtered = []
                for eid in src_ids:
                    elem = link_doc.GetElement(eid)
                    if elem and elem.UniqueId not in existing_uids:
                        filtered.append(eid)
                src_ids = filtered

            if not src_ids:
                results[link_info[u"name"]] = 0
                continue

            try:
                id_list = SCG.List[DB.ElementId](src_ids)
                new_ids = DB.ElementTransformUtils.CopyElements(
                    link_doc, id_list, doc, transform, DB.CopyPasteOptions()
                )
            except Exception as ex:
                logger.warning(u"Copy from {} failed: {}".format(link_info[u"name"], ex))
                results[link_info[u"name"]] = 0
                continue

            count = 0
            for i, new_id in enumerate(new_ids):
                new_elem = doc.GetElement(new_id)
                if new_elem is None:
                    continue
                if ws_id is not None:
                    try:
                        wp = new_elem.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                        if wp and not wp.IsReadOnly:
                            wp.Set(ws_id.IntegerValue)
                    except Exception:
                        pass
                if i < len(src_ids):
                    src_elem = link_doc.GetElement(src_ids[i])
                    if src_elem:
                        stamp_element(new_elem, src_elem.UniqueId)
                        existing_uids.add(src_elem.UniqueId)
                count += 1
            results[link_info[u"name"]] = count
        t1.Commit()

        # ── Txn 2: create solution section view ───────────────────────────────
        # Duplicate (not CreateSection) so position, orientation and CropBox are
        # inherited exactly — avoids all BoundingBoxXYZ axis-convention guessing.
        t2 = DB.Transaction(doc, u"EasyBIM: Create solution section")
        t2.Start()
        # Assign chosen view template to the existing section if not already set.
        if existing_template is not None:
            try:
                if existing_section.ViewTemplateId != existing_template.Id:
                    existing_section.ViewTemplateId = existing_template.Id
            except Exception as _ex:
                logger.warning(
                    u"Could not assign existing section template: {}".format(_ex))
        new_view_id = existing_section.Duplicate(DB.ViewDuplicateOption.Duplicate)
        sv = doc.GetElement(new_view_id)
        # Ensure unique view name
        existing_names = set(
            v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
        )
        final_name = view_name
        counter = 2
        while final_name in existing_names:
            final_name = u"{} ({})".format(view_name, counter)
            counter += 1
        sv.Name = final_name
        tmpl = find_view_template(SOLUTION_TEMPLATE)
        if tmpl:
            sv.ViewTemplateId = tmpl.Id
        else:
            try:
                sv.ViewTemplateId = DB.ElementId.InvalidElementId
            except Exception:
                pass
            try:
                sv.Scale = SCALE
            except Exception:
                pass
        new_section[0] = sv
        t2.Commit()

        # ── Txn 3: place on sheet ─────────────────────────────────────────────
        if sheet is not None:
            t3 = DB.Transaction(doc, u"EasyBIM: Place solution section on sheet")
            t3.Start()

            # Estimate viewport dimensions on sheet from CropBox and scale.
            crop = existing_section.CropBox
            mn_c, mx_c = crop.Min, crop.Max
            raw_scale = existing_section.Scale
            view_scale = float(raw_scale) if raw_scale and raw_scale > 0 else float(SCALE)
            vp_w = abs(mx_c.X - mn_c.X) / view_scale
            vp_h = abs(mx_c.Y - mn_c.Y) / view_scale + 0.08  # +0.08 ft for title label
            MARGIN = 0.1

            # Sheet bounds.
            try:
                sl = sheet.Outline
                s_left, s_right = sl.Min.U, sl.Max.U
                s_bot,  s_top   = sl.Min.V, sl.Max.V
            except Exception:
                s_left, s_right = 0.0, 2.5
                s_bot,  s_top   = 0.0, 1.8
            sheet_mid_y = (s_top + s_bot) / 2.0

            # ── Step A: check whether existing section is already on the sheet ──
            existing_vp = None
            for vp_id in sheet.GetAllViewports():
                vp = doc.GetElement(vp_id)
                if vp and vp.ViewId == existing_section.Id:
                    existing_vp = vp
                    break

            # ── Step B: place viewports side-by-side (solution LEFT, existing RIGHT)
            # Viewport centers are calculated directly from known geometry to
            # avoid relying on GetBoxOutline() which is unreliable for freshly
            # created viewports inside a transaction.
            if existing_vp is not None:
                # Existing is already placed — put solution directly to its left.
                try:
                    ex_cx = existing_vp.GetBoxCenter().X
                    ex_cy = existing_vp.GetBoxCenter().Y
                except Exception:
                    ex_cx = (s_left + s_right) / 2.0
                    ex_cy = sheet_mid_y
                x_sol = max(s_left + MARGIN + vp_w / 2.0,
                            ex_cx - vp_w - MARGIN)
                y_sol = ex_cy
                sol_vp = DB.Viewport.Create(doc, sheet.Id, sv.Id,
                                            DB.XYZ(x_sol, y_sol, 0))
            else:
                # Neither is on the sheet — find the leftmost open spot for
                # solution, then place existing directly to its right at the
                # same Y (same row, guaranteed side-by-side).
                occ = _sheet_vp_rects(sheet)
                avg_y = (sum((r[1] + r[3]) / 2.0 for r in occ) / len(occ)
                         if occ else sheet_mid_y)
                x_sol, y_sol = _find_sheet_spot(
                    occ, s_left, s_right, s_bot, s_top,
                    vp_w, vp_h, MARGIN,
                    start_x=s_left + MARGIN + vp_w / 2.0,
                    preferred_y=avg_y
                )
                sol_vp = DB.Viewport.Create(doc, sheet.Id, sv.Id,
                                            DB.XYZ(x_sol, y_sol, 0))
                # Existing center = solution center + one viewport width + gap
                x_ex = x_sol + vp_w + MARGIN
                existing_vp = DB.Viewport.Create(
                    doc, sheet.Id, existing_section.Id,
                    DB.XYZ(x_ex, y_sol, 0)
                )

            # ── Step C: apply viewport types ─────────────────────────────────────
            # GetValidTypes() on the newly created viewport returns valid type IDs.
            # Viewport type elements don't expose .Name; read it via built-in params.
            _vp_types = {}
            try:
                for _vid in sol_vp.GetValidTypes():
                    try:
                        _et = doc.GetElement(_vid)
                        if _et is None:
                            continue
                        _name = None
                        try:
                            _name = _et.Name
                        except Exception:
                            pass
                        if not _name:
                            for _bip in (DB.BuiltInParameter.SYMBOL_NAME_PARAM,
                                         DB.BuiltInParameter.ALL_MODEL_TYPE_NAME):
                                try:
                                    _p = _et.get_Parameter(_bip)
                                    if _p:
                                        _name = _p.AsString()
                                        if _name:
                                            break
                                except Exception:
                                    pass
                        if _name:
                            _vp_types[_name.lower().strip()] = _vid
                    except Exception:
                        pass
            except Exception as _ex:
                logger.warning(u"GetValidTypes failed: {}".format(_ex))

            _bubble_tid = _vp_types.get(u"bubble scale")
            _empty_tid  = _vp_types.get(u"empty")

            if _bubble_tid:
                try:
                    existing_vp.ChangeTypeId(_bubble_tid)
                except Exception as e:
                    logger.warning(u"ChangeTypeId 'Bubble Scale': {}".format(e))
            else:
                logger.warning(u"Viewport type 'Bubble Scale' not found in project")
            if _empty_tid:
                try:
                    sol_vp.ChangeTypeId(_empty_tid)
                except Exception as e:
                    logger.warning(u"ChangeTypeId 'Empty': {}".format(e))
            else:
                logger.warning(u"Viewport type 'Empty' not found in project")

            t3.Commit()

        tg.Assimilate()
        return results, new_section[0]

    except Exception as ex:
        tg.RollBack()
        raise

# ─────────────────────────────────────────────────────────────────────────────
# WPF XAML
# ─────────────────────────────────────────────────────────────────────────────

XAML = u"""
<Window
  xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
  Title="Solution Section"
  Width="624" Height="720"
  WindowStartupLocation="CenterScreen"
  ResizeMode="CanMinimize"
  WindowStyle="SingleBorderWindow"
  FontFamily="Segoe UI"
  Background="#f7f8ff">
  <Window.Resources>

    <Style x:Key="PrimaryBtn" TargetType="Button">
      <Setter Property="Background"      Value="#1e248c"/>
      <Setter Property="Foreground"      Value="White"/>
      <Setter Property="FontSize"        Value="13"/>
      <Setter Property="FontWeight"      Value="SemiBold"/>
      <Setter Property="Height"          Value="36"/>
      <Setter Property="Padding"         Value="18,0"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}" CornerRadius="7"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#44b8d3"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.42"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="GhostBtn" TargetType="Button">
      <Setter Property="Background"      Value="Transparent"/>
      <Setter Property="Foreground"      Value="#6b7280"/>
      <Setter Property="FontSize"        Value="13"/>
      <Setter Property="Height"          Value="36"/>
      <Setter Property="Padding"         Value="14,0"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="BorderBrush"     Value="#e8eaff"/>
      <Setter Property="Cursor"          Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}"
                    CornerRadius="7" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Background" Value="#f0f2ff"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="CyanTextBtn" TargetType="Button">
      <Setter Property="Background"      Value="Transparent"/>
      <Setter Property="Foreground"      Value="#44b8d3"/>
      <Setter Property="FontSize"        Value="12"/>
      <Setter Property="FontWeight"      Value="SemiBold"/>
      <Setter Property="Height"          Value="22"/>
      <Setter Property="Padding"         Value="0"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Cursor"          Value="Hand"/>
    </Style>

  </Window.Resources>

  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="76"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- HEADER -->
    <Border Grid.Row="0">
      <Border.Background>
        <LinearGradientBrush StartPoint="0,0" EndPoint="1,0">
          <GradientStop Color="#1e248c" Offset="0"/>
          <GradientStop Color="#2b5cbf" Offset="0.55"/>
          <GradientStop Color="#44b8d3" Offset="1"/>
        </LinearGradientBrush>
      </Border.Background>
      <Grid Margin="20,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="32"/>
        </Grid.ColumnDefinitions>
        <Border Grid.Column="0" Width="44" Height="44" CornerRadius="10" VerticalAlignment="Center"
                Background="#151b6e">
          <Path Data="M7,3.5 V20.5 M7,7 H14 M11.5,4.5 L14.5,7 L11.5,9.5 M7,17 H14 M11.5,14.5 L14.5,17 L11.5,19.5"
                Stroke="White" StrokeThickness="1.5" StrokeLineJoin="Round"
                StrokeStartLineCap="Round" StrokeEndLineCap="Round"
                Width="24" Height="24" Stretch="None"
                HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <StackPanel Grid.Column="1" VerticalAlignment="Center" Margin="14,0,0,0">
          <TextBlock Text="Solution Section" FontSize="16" FontWeight="Bold" Foreground="White"/>
          <TextBlock Text="MEP coordination section · linked-model capture"
                     FontSize="10" Foreground="#b8d8f0" Margin="0,3,0,0"/>
        </StackPanel>
        <Button x:Name="CloseBtn" Grid.Column="2" Content="✕" Width="28" Height="28"
                Background="Transparent" Foreground="White" BorderThickness="0"
                FontSize="13" Cursor="Hand" VerticalAlignment="Center"/>
      </Grid>
    </Border>

    <!-- BANNER -->
    <Border x:Name="BannerBorder" Grid.Row="1"
            Background="#ecf8fc" BorderBrush="#bbe5f0" BorderThickness="0,0,0,1" Padding="20,10">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="i" FontSize="13" FontWeight="Bold" Foreground="#44b8d3"
                   Margin="0,0,9,0" VerticalAlignment="Center" FontFamily="Segoe UI"/>
        <TextBlock x:Name="BannerText" FontSize="12.5" Foreground="#1e6e87"
                   TextWrapping="Wrap" VerticalAlignment="Center"/>
      </StackPanel>
    </Border>

    <!-- STEPPER -->
    <Grid Grid.Row="2" Margin="24,14,24,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <!-- Connector line behind circles -->
      <Border Grid.Column="0" Grid.ColumnSpan="4" Height="1.5" Background="#e0e3f8"
              VerticalAlignment="Top" Margin="38,13,38,0"/>
      <!-- Step 1 -->
      <StackPanel Grid.Column="0" HorizontalAlignment="Center">
        <Border x:Name="SC1" Width="28" Height="28" CornerRadius="14" Background="#1e248c" HorizontalAlignment="Center">
          <TextBlock x:Name="SN1" Text="1" FontSize="12" FontWeight="SemiBold" Foreground="White"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <TextBlock x:Name="SL1" Text="Existing&#x0a;Section" FontSize="10" TextAlignment="Center"
                   Foreground="#1e248c" FontWeight="SemiBold" Margin="0,5,0,0" TextWrapping="Wrap" MaxWidth="90"/>
      </StackPanel>
      <!-- Step 2 -->
      <StackPanel Grid.Column="1" HorizontalAlignment="Center">
        <Border x:Name="SC2" Width="28" Height="28" CornerRadius="14" Background="#c6cbe0" HorizontalAlignment="Center">
          <TextBlock x:Name="SN2" Text="2" FontSize="12" FontWeight="SemiBold" Foreground="White"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <TextBlock x:Name="SL2" Text="Links" FontSize="10" TextAlignment="Center"
                   Foreground="#9aa0ac" Margin="0,5,0,0"/>
      </StackPanel>
      <!-- Step 3 -->
      <StackPanel Grid.Column="2" HorizontalAlignment="Center">
        <Border x:Name="SC3" Width="28" Height="28" CornerRadius="14" Background="#c6cbe0" HorizontalAlignment="Center">
          <TextBlock x:Name="SN3" Text="3" FontSize="12" FontWeight="SemiBold" Foreground="White"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <TextBlock x:Name="SL3" Text="Solution&#x0a;Section" FontSize="10" TextAlignment="Center"
                   Foreground="#9aa0ac" Margin="0,5,0,0" TextWrapping="Wrap" MaxWidth="90"/>
      </StackPanel>
      <!-- Step 4 -->
      <StackPanel Grid.Column="3" HorizontalAlignment="Center">
        <Border x:Name="SC4" Width="28" Height="28" CornerRadius="14" Background="#c6cbe0" HorizontalAlignment="Center">
          <TextBlock x:Name="SN4" Text="4" FontSize="12" FontWeight="SemiBold" Foreground="White"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <TextBlock x:Name="SL4" Text="Final&#x0a;Check" FontSize="10" TextAlignment="Center"
                   Foreground="#9aa0ac" Margin="0,5,0,0" TextWrapping="Wrap" MaxWidth="90"/>
      </StackPanel>
    </Grid>

    <!-- BODY -->
    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
      <Grid Margin="20,6,20,10">

        <!-- STEP 1 -->
        <StackPanel x:Name="Step1Panel">
          <TextBlock Text="SECTION VIEW" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Margin="0,0,0,14">
            <StackPanel x:Name="SectionListPanel"/>
          </Border>

          <TextBlock Text="EXISTING SECTION TEMPLATE" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Grid Margin="0,0,0,14">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="10"/>
              <ColumnDefinition Width="130"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="#fafbff" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Padding="12,10">
              <Grid>
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="32"/>
                  <ColumnDefinition Width="*"/>
                  <ColumnDefinition Width="16"/>
                </Grid.ColumnDefinitions>
                <Border Grid.Column="0" Width="28" Height="28" CornerRadius="7" Background="#e8eaff">
                  <TextBlock Text="&#x229E;" FontSize="13" Foreground="#1e248c"
                             HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Border>
                <StackPanel Grid.Column="1" Margin="9,0,0,0" VerticalAlignment="Center">
                  <TextBlock Text="View template" FontSize="11" Foreground="#9aa0ac"/>
                  <TextBlock x:Name="ExistTmplNameTB" Text="EB_MEP_CUR_SE_1-50" FontFamily="Consolas" FontSize="12"
                             Foreground="#1f2937" FontWeight="SemiBold"/>
                </StackPanel>
                <TextBlock x:Name="ExistTmplLockTB" Grid.Column="2" Text="&#x1F512;" FontSize="10" Foreground="#c0c6e0" VerticalAlignment="Center"/>
              </Grid>
            </Border>
            <Border Grid.Column="2" Background="#fafbff" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Padding="12,10">
              <StackPanel>
                <TextBlock Text="Scale" FontSize="11" Foreground="#9aa0ac"/>
                <TextBlock Text="1 : 50" FontSize="13" Foreground="#1f2937" FontWeight="SemiBold"/>
              </StackPanel>
            </Border>
          </Grid>

          <Border x:Name="ExistTmplPickerContainer" Margin="0,-8,0,14"
                  Background="White" BorderBrush="#e8eaff" BorderThickness="1"
                  CornerRadius="8" MaxHeight="160" Visibility="Collapsed">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
              <StackPanel x:Name="ExistTmplPickerPanel"/>
            </ScrollViewer>
          </Border>

          <TextBlock Text="PLACE EXISTING SECTION ON SHEET" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Border BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="7" Background="White" Margin="0,0,0,5">
            <Grid>
              <TextBox x:Name="SheetSearchBox" Height="34" FontSize="12.5"
                       Padding="32,0,10,0" VerticalContentAlignment="Center"
                       BorderThickness="0" Background="Transparent"/>
              <TextBlock x:Name="SheetHint" Text="Search sheets..." FontSize="12"
                         Foreground="#b0b8c8" Margin="32,0,0,0"
                         VerticalAlignment="Center" IsHitTestVisible="False"/>
            </Grid>
          </Border>
          <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" MaxHeight="150">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
              <StackPanel x:Name="SheetListPanel"/>
            </ScrollViewer>
          </Border>
        </StackPanel>

        <!-- STEP 2 -->
        <StackPanel x:Name="Step2Panel" Visibility="Collapsed">
          <Grid Margin="0,0,0,9">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock x:Name="LinksLabel" Grid.Column="0" FontFamily="Consolas" FontSize="10"
                       Foreground="#9aa0ac" VerticalAlignment="Center"/>
            <Button x:Name="ToggleAllBtn" Grid.Column="1" Content="Select all"
                    Style="{StaticResource CyanTextBtn}"/>
          </Grid>
          <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8">
            <StackPanel x:Name="LinksListPanel"/>
          </Border>
          <StackPanel Orientation="Horizontal" Margin="2,10,0,0">
            <TextBlock Text="i" FontSize="12" FontWeight="Bold" Foreground="#44b8d3"
                       Margin="0,0,7,0" VerticalAlignment="Center"/>
            <TextBlock Text="Unloaded links can't be captured. Elements are copied with each link's transform applied."
                       FontSize="11.5" Foreground="#9aa0ac" TextWrapping="Wrap"/>
          </StackPanel>
        </StackPanel>

        <!-- STEP 3 -->
        <StackPanel x:Name="Step3Panel" Visibility="Collapsed">
          <Border x:Name="ExistSectionTmplNotice"
                  Background="#fff8ec" BorderBrush="#f9c95a" BorderThickness="1"
                  CornerRadius="7" Padding="12,9" Margin="0,0,0,10"
                  Visibility="Collapsed">
            <StackPanel Orientation="Horizontal">
              <TextBlock Text="&#x26A0;" FontSize="13" Foreground="#c8850d"
                         Margin="0,0,8,0" VerticalAlignment="Center"/>
              <TextBlock x:Name="ExistSectionTmplNoticeTB"
                         FontSize="12" Foreground="#7a5100" TextWrapping="Wrap"/>
            </StackPanel>
          </Border>
          <TextBlock Text="SOLUTION SECTION VIEW · FROM TEMPLATE" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Margin="0,0,0,14">
            <StackPanel>
              <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="12,10">
                <Grid>
                  <Grid.ColumnDefinitions><ColumnDefinition Width="34"/><ColumnDefinition Width="*"/><ColumnDefinition Width="20"/></Grid.ColumnDefinitions>
                  <Border Grid.Column="0" Width="28" Height="28" CornerRadius="7" Background="#e8eaff">
                    <Path Data="M7,3.5 V20.5 M7,7 H14 M11.5,4.5 L14.5,7 L11.5,9.5 M7,17 H14 M11.5,14.5 L14.5,17 L11.5,19.5"
                          Stroke="#1e248c" StrokeThickness="1.4" Width="16" Height="16" Stretch="None"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  </Border>
                  <StackPanel Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center">
                    <TextBlock Text="View name (auto · existing name + Solution)" FontSize="11" Foreground="#9aa0ac"/>
                    <TextBlock x:Name="S3ViewName" FontFamily="Consolas" FontSize="12.5" Foreground="#1f2937" FontWeight="SemiBold"/>
                  </StackPanel>
                  <TextBlock Grid.Column="2" Text="&#x1F512;" FontSize="10" Foreground="#c0c6e0" VerticalAlignment="Center"/>
                </Grid>
              </Border>
              <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="12,10">
                <Grid>
                  <Grid.ColumnDefinitions><ColumnDefinition Width="34"/><ColumnDefinition Width="*"/><ColumnDefinition Width="20"/></Grid.ColumnDefinitions>
                  <Border Grid.Column="0" Width="28" Height="28" CornerRadius="7" Background="#e8eaff">
                    <TextBlock Text="&#x229E;" FontSize="13" Foreground="#1e248c" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  </Border>
                  <StackPanel Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center">
                    <TextBlock Text="View template · scale" FontSize="11" Foreground="#9aa0ac"/>
                    <TextBlock Text="EB_MEP_SOL_SE_1-50 · 1 : 50" FontFamily="Consolas" FontSize="12.5" Foreground="#1f2937" FontWeight="SemiBold"/>
                  </StackPanel>
                  <TextBlock Grid.Column="2" Text="&#x1F512;" FontSize="10" Foreground="#c0c6e0" VerticalAlignment="Center"/>
                </Grid>
              </Border>
              <Border Padding="12,10">
                <Grid>
                  <Grid.ColumnDefinitions><ColumnDefinition Width="34"/><ColumnDefinition Width="*"/><ColumnDefinition Width="20"/></Grid.ColumnDefinitions>
                  <Border Grid.Column="0" Width="28" Height="28" CornerRadius="7" Background="#e8eaff">
                    <TextBlock Text="&#x2922;" FontSize="14" Foreground="#1e248c" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  </Border>
                  <StackPanel Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center">
                    <TextBlock Text="Capture depth · inherited from existing section" FontSize="11" Foreground="#9aa0ac"/>
                    <TextBlock x:Name="S3Depth" FontSize="13" Foreground="#1f2937" FontWeight="SemiBold"/>
                  </StackPanel>
                  <TextBlock Grid.Column="2" Text="&#x1F512;" FontSize="10" Foreground="#c0c6e0" VerticalAlignment="Center"/>
                </Grid>
              </Border>
            </StackPanel>
          </Border>

          <TextBlock Text="COPIED ELEMENTS WORKSET" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Padding="0,4" Margin="0,0,0,14">
            <StackPanel>
              <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="12,9">
                <StackPanel Orientation="Horizontal">
                  <TextBlock Text="&#x2630;" FontSize="14" Foreground="#1e248c" VerticalAlignment="Center" Margin="0,0,9,0"/>
                  <TextBlock Text="Workset" FontSize="13.5" Foreground="#374151" VerticalAlignment="Center"/>
                  <TextBlock Text="MEP Solution" FontFamily="Consolas" FontSize="12.5"
                             Foreground="#1e248c" FontWeight="SemiBold" VerticalAlignment="Center" Margin="10,0,0,0"/>
                  <Border Background="#ecf8fc" BorderBrush="#b8e8f2" BorderThickness="1"
                          CornerRadius="10" Padding="7,2" Margin="9,0,0,0">
                    <TextBlock Text="auto-create" FontSize="11" Foreground="#44b8d3" FontWeight="SemiBold"/>
                  </Border>
                </StackPanel>
              </Border>
              <Border Padding="12,9">
                <Grid>
                  <TextBlock Text="Skip elements already copied for this section"
                             FontSize="13.5" Foreground="#374151" VerticalAlignment="Center"/>
                  <ToggleButton x:Name="SkipDupToggle" HorizontalAlignment="Right" IsChecked="True"
                                Width="38" Height="22" Cursor="Hand" BorderThickness="0">
                    <ToggleButton.Template>
                      <ControlTemplate TargetType="ToggleButton">
                        <Border x:Name="Tr" Width="38" Height="22" CornerRadius="11"
                                Background="#44b8d3" Padding="2">
                          <Border x:Name="Th" Width="18" Height="18" CornerRadius="9"
                                  Background="White" HorizontalAlignment="Right">
                            <Border.Effect>
                              <DropShadowEffect Color="#000000" BlurRadius="3" ShadowDepth="1" Opacity="0.18"/>
                            </Border.Effect>
                          </Border>
                        </Border>
                        <ControlTemplate.Triggers>
                          <Trigger Property="IsChecked" Value="False">
                            <Setter TargetName="Tr" Property="Background" Value="#cbd0e0"/>
                            <Setter TargetName="Th" Property="HorizontalAlignment" Value="Left"/>
                          </Trigger>
                        </ControlTemplate.Triggers>
                      </ControlTemplate>
                    </ToggleButton.Template>
                  </ToggleButton>
                </Grid>
              </Border>
            </StackPanel>
          </Border>

          <TextBlock Text="SHEET PLACEMENT" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
          <Border Background="#fafbff" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Padding="12,10">
            <Grid>
              <Grid.ColumnDefinitions><ColumnDefinition Width="34"/><ColumnDefinition Width="*"/><ColumnDefinition Width="20"/></Grid.ColumnDefinitions>
              <Border Grid.Column="0" Width="28" Height="28" CornerRadius="7" Background="#e8eaff">
                <TextBlock Text="&#x29C9;" FontSize="14" Foreground="#1e248c" HorizontalAlignment="Center" VerticalAlignment="Center"/>
              </Border>
              <StackPanel Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center">
                <TextBlock Text="Same sheet as existing section · placed next to it" FontSize="11" Foreground="#9aa0ac"/>
                <TextBlock x:Name="S3Sheet" FontSize="13" Foreground="#1f2937" FontWeight="SemiBold"/>
              </StackPanel>
              <TextBlock Grid.Column="2" Text="&#x1F512;" FontSize="10" Foreground="#c0c6e0" VerticalAlignment="Center"/>
            </Grid>
          </Border>
        </StackPanel>

        <!-- STEP 4: Review + Result -->
        <StackPanel x:Name="Step4Panel" Visibility="Collapsed">

          <!-- Pre-run review -->
          <StackPanel x:Name="ReviewPanel">
            <TextBlock FontSize="13" Foreground="#374151" TextWrapping="Wrap" Margin="0,0,0,14"
                       Text="Review the run. This copies elements into the host model and creates a view — wrapped in named transactions you can undo."/>
            <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Margin="0,0,0,10">
              <StackPanel>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Existing section" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="R_ExistSection" FontSize="13" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Existing template" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="R_ExistTmpl" Text="EB_MEP_CUR_SE_1-50 · 1 : 50" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Sheet" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="R_Sheet" FontSize="13" FontWeight="SemiBold" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Links" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="R_Links" FontSize="13" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Solution section" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="R_SolSection" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Solution template" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock Text="EB_MEP_SOL_SE_1-50 · 1 : 50" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Workset" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock Text="MEP Solution" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border Padding="13,10"><Grid>
                  <TextBlock Text="Capture depth" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock Text="Inherited from existing section" FontSize="13" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
              </StackPanel>
            </Border>
            <StackPanel Orientation="Horizontal" Margin="2,0,0,0">
              <TextBlock Text="&#x23F1;" FontSize="12" Foreground="#44b8d3" Margin="0,0,7,0" VerticalAlignment="Center"/>
              <TextBlock Text="Unloaded links are skipped and noted in the summary." FontSize="11.5" Foreground="#9aa0ac"/>
            </StackPanel>
          </StackPanel>

          <!-- Result panel -->
          <StackPanel x:Name="ResultPanel" Visibility="Collapsed">
            <StackPanel HorizontalAlignment="Center" Margin="0,4,0,18">
              <Border Width="52" Height="52" CornerRadius="26" Background="#e4f7f0"
                      HorizontalAlignment="Center" Margin="0,0,0,12">
                <TextBlock Text="&#x2713;" FontSize="26" FontWeight="Bold" Foreground="#22b07c"
                           HorizontalAlignment="Center" VerticalAlignment="Center"/>
              </Border>
              <TextBlock Text="Coordination section created" FontSize="18" FontWeight="Bold"
                         Foreground="#1e248c" HorizontalAlignment="Center"/>
              <TextBlock x:Name="Res_Summary" FontSize="12.5" Foreground="#6b7280"
                         HorizontalAlignment="Center" Margin="0,3,0,0"/>
            </StackPanel>

            <TextBlock Text="ELEMENTS COPIED PER LINK" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
            <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8" Margin="0,0,0,14">
              <StackPanel x:Name="ResultLinksPanel"/>
            </Border>

            <TextBlock Text="RESULT" FontFamily="Consolas" FontSize="10" Foreground="#9aa0ac" Margin="0,0,0,7"/>
            <Border Background="White" BorderBrush="#e8eaff" BorderThickness="1" CornerRadius="8">
              <StackPanel>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Solution section" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="Res_Name" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border BorderBrush="#f0f1ff" BorderThickness="0,0,0,1" Padding="13,10"><Grid>
                  <TextBlock Text="Solution template" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock Text="EB_MEP_SOL_SE_1-50" FontFamily="Consolas" FontSize="12.5" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
                <Border Padding="13,10"><Grid>
                  <TextBlock Text="Sheet" FontSize="12.5" Foreground="#6b7280" VerticalAlignment="Center"/>
                  <TextBlock x:Name="Res_Sheet" FontSize="13" FontWeight="SemiBold" Foreground="#1f2937" HorizontalAlignment="Right" VerticalAlignment="Center"/></Grid></Border>
              </StackPanel>
            </Border>
          </StackPanel>

        </StackPanel>
      </Grid>
    </ScrollViewer>

    <!-- FOOTER -->
    <Border Grid.Row="4" Background="White" BorderBrush="#e8eaff" BorderThickness="0,1,0,0" Padding="20,12">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock x:Name="StepLabel" Grid.Column="0" Text="Step 1 of 4"
                   FontFamily="Consolas" FontSize="12" Foreground="#9aa0ac" VerticalAlignment="Center"/>
        <StackPanel Grid.Column="1" Orientation="Horizontal">
          <Button x:Name="CancelBtn" Content="Cancel" Style="{StaticResource GhostBtn}"/>
          <Button x:Name="BackBtn"   Content="&#x25C0;  Back"   Style="{StaticResource GhostBtn}"  Visibility="Collapsed" Margin="8,0,0,0"/>
          <Button x:Name="NextBtn"   Content="Next  &#x25B6;"   Style="{StaticResource PrimaryBtn}" Margin="8,0,0,0"/>
          <Button x:Name="RunBtn"    Content="&#x25B6;  Run"    Style="{StaticResource PrimaryBtn}" Visibility="Collapsed" Margin="8,0,0,0"/>
          <Button x:Name="AgainBtn"  Content="&#x21BA;  Run again" Style="{StaticResource GhostBtn}" Visibility="Collapsed" Margin="8,0,0,0"/>
          <Button x:Name="OpenBtn"   Content="Open sheet  &#x2197;" Style="{StaticResource PrimaryBtn}" Visibility="Collapsed" Margin="8,0,0,0"/>
        </StackPanel>
      </Grid>
    </Border>

  </Grid>
</Window>
"""

# ─────────────────────────────────────────────────────────────────────────────
# WIZARD DIALOG
# ─────────────────────────────────────────────────────────────────────────────

BANNERS = [
    u"Pick the existing section to coordinate, confirm its template, and choose the sheet it lives on.",
    u"Select which linked models to pull MEP elements from into the solution.",
    u"Set up the solution section — it is placed on the same sheet, right next to the existing section.",
    u"Review the run. Every change is wrapped in named transactions you can undo.",
]

NAVY_COLOR  = WM.Color.FromRgb(0x1e, 0x24, 0x8c)
CYAN_COLOR  = WM.Color.FromRgb(0x44, 0xb8, 0xd3)
GRAY_COLOR  = WM.Color.FromRgb(0xc6, 0xcb, 0xe0)
GREEN_COLOR = WM.Color.FromRgb(0x22, 0xb0, 0x7c)
BODY_COLOR  = WM.Color.FromRgb(0x37, 0x41, 0x51)
MUTED_COLOR = WM.Color.FromRgb(0x9a, 0xa0, 0xac)
LINE_COLOR  = WM.Color.FromRgb(0xf0, 0xf1, 0xff)
SEL_BG      = WM.Color.FromArgb(0x16, 0x44, 0xb8, 0xd3)


def _color(c):
    return WM.SolidColorBrush(c)


class SolutionSectionDialog(object):

    def __init__(self, sections, sheets, links):
        self._sections = sections   # list of DB.View
        self._sheets   = sheets     # list of DB.ViewSheet
        self._links    = links      # list of dicts from get_linked_models()
        self._step     = 1
        self._done     = False

        # Selection state
        self._sel_section = sections[0].Name if sections else u""
        self._sel_sheet   = None
        self._sheet_query = u""
        self._result_section_view = None

        # Row maps for updating selection UI
        self._section_rows = {}   # name -> (border, icon_tb, name_tb)
        self._sheet_rows   = []   # list of (sheet_obj, border, icon_tb)
        self._link_rows    = []   # list of {info, cb_border, cb_inner}

        # Template for existing section
        self._sel_existing_tmpl   = None  # resolved View template (or user-picked)
        self._available_sec_tmpls = []    # populated only when default is missing
        self._tmpl_rows           = []    # picker row list

        self.cancelled = True
        self._window   = None

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        ctx    = SysXmlReader.Create(StringReader(XAML))
        window = XamlReader.Load(ctx)
        self._window = window
        w = window

        w.FindName(u"CloseBtn").Click += lambda s, e: w.Close()
        w.FindName(u"CancelBtn").Click += self._on_cancel
        w.FindName(u"BackBtn").Click   += self._on_back
        w.FindName(u"NextBtn").Click   += self._on_next
        w.FindName(u"RunBtn").Click    += self._on_run
        w.FindName(u"AgainBtn").Click  += self._on_again
        w.FindName(u"OpenBtn").Click   += self._on_open_sheet

        sb = w.FindName(u"SheetSearchBox")
        sb.TextChanged += self._on_sheet_search
        sb.GotFocus    += lambda s, e: self._hide_hint(s)
        sb.LostFocus   += lambda s, e: self._show_hint(s, w.FindName(u"SheetHint"))

        w.FindName(u"ToggleAllBtn").Click += self._on_toggle_all

        self._populate_sections()
        self._populate_sheets(u"")
        self._populate_links()
        self._setup_existing_template()
        self._go_to_step(1)
        return window

    # ── Populate lists ────────────────────────────────────────────────────────

    def _make_div(self):
        b = WC.Border()
        b.BorderBrush     = _color(LINE_COLOR)
        b.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)
        return b

    def _populate_sections(self):
        panel = self._window.FindName(u"SectionListPanel")
        panel.Children.Clear()
        self._section_rows = {}
        for i, view in enumerate(self._sections):
            is_last = (i == len(self._sections) - 1)
            border, icon_tb, name_tb = self._make_section_row(view.Name, is_last)
            panel.Children.Add(border)
            self._section_rows[view.Name] = (border, icon_tb, name_tb)
        self._update_section_selection()

    def _make_section_row(self, name, is_last):
        border = WC.Border()
        border.Padding = System.Windows.Thickness(10, 9, 10, 9)
        if not is_last:
            border.BorderBrush     = _color(LINE_COLOR)
            border.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)
        border.Background = WM.Brushes.Transparent
        border.Cursor     = WI.Cursors.Hand

        row = WC.StackPanel()
        row.Orientation = WC.Orientation.Horizontal

        icon_tb = WC.TextBlock()
        icon_tb.Text              = u"○"
        icon_tb.FontSize          = 14
        icon_tb.Foreground        = _color(GRAY_COLOR)
        icon_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
        icon_tb.Margin            = System.Windows.Thickness(0, 0, 10, 0)

        name_tb = WC.TextBlock()
        name_tb.Text              = name
        name_tb.FontSize          = 13.5
        name_tb.Foreground        = _color(BODY_COLOR)
        name_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center

        row.Children.Add(icon_tb)
        row.Children.Add(name_tb)
        border.Child = row

        def on_click(s, e, n=name):
            self._sel_section = n
            self._update_section_selection()

        border.MouseLeftButtonUp += on_click
        return border, icon_tb, name_tb

    def _update_section_selection(self):
        for name, (border, icon_tb, name_tb) in self._section_rows.items():
            selected = (name == self._sel_section)
            if selected:
                border.Background = _color(SEL_BG)
                icon_tb.Text      = u"✓"
                icon_tb.Foreground = _color(CYAN_COLOR)
                name_tb.FontWeight = System.Windows.FontWeights.SemiBold
            else:
                border.Background = WM.Brushes.Transparent
                icon_tb.Text      = u"○"
                icon_tb.Foreground = _color(GRAY_COLOR)
                name_tb.FontWeight = System.Windows.FontWeights.Normal

    def _populate_sheets(self, query):
        panel = self._window.FindName(u"SheetListPanel")
        panel.Children.Clear()
        self._sheet_rows = []
        q = query.lower()
        visible = [s for s in self._sheets
                   if not q or q in (s.SheetNumber + u" " + s.Name).lower()]
        for i, sheet in enumerate(visible):
            is_last = (i == len(visible) - 1)
            border, icon_tb = self._make_sheet_row(sheet, is_last)
            panel.Children.Add(border)
            self._sheet_rows.append((sheet, border, icon_tb))
        self._update_sheet_selection()

    def _make_sheet_row(self, sheet, is_last):
        border = WC.Border()
        border.Padding    = System.Windows.Thickness(10, 8, 10, 8)
        border.Background = WM.Brushes.Transparent
        border.Cursor     = WI.Cursors.Hand
        if not is_last:
            border.BorderBrush     = _color(LINE_COLOR)
            border.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)

        row = WC.StackPanel()
        row.Orientation = WC.Orientation.Horizontal

        icon_tb = WC.TextBlock()
        icon_tb.Text              = u"○"
        icon_tb.FontSize          = 13
        icon_tb.Foreground        = _color(GRAY_COLOR)
        icon_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
        icon_tb.Margin            = System.Windows.Thickness(0, 0, 9, 0)

        num_tb = WC.TextBlock()
        num_tb.Text              = sheet.SheetNumber
        num_tb.FontFamily        = WM.FontFamily(u"Consolas")
        num_tb.FontSize          = 12
        num_tb.FontWeight        = System.Windows.FontWeights.SemiBold
        num_tb.Foreground        = _color(NAVY_COLOR)
        num_tb.Width             = 64
        num_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center

        name_tb = WC.TextBlock()
        name_tb.Text              = sheet.Name
        name_tb.FontSize          = 13
        name_tb.Foreground        = _color(BODY_COLOR)
        name_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center

        row.Children.Add(icon_tb)
        row.Children.Add(num_tb)
        row.Children.Add(name_tb)
        border.Child = row

        def on_click(s, e, sh=sheet):
            self._sel_sheet = sh
            self._update_sheet_selection()

        border.MouseLeftButtonUp += on_click
        return border, icon_tb

    def _update_sheet_selection(self):
        for sheet, border, icon_tb in self._sheet_rows:
            selected = (self._sel_sheet is not None and
                        sheet.Id == self._sel_sheet.Id)
            if selected:
                border.Background = _color(SEL_BG)
                icon_tb.Text      = u"✓"
                icon_tb.Foreground = _color(CYAN_COLOR)
            else:
                border.Background = WM.Brushes.Transparent
                icon_tb.Text      = u"○"
                icon_tb.Foreground = _color(GRAY_COLOR)

    def _populate_links(self):
        panel = self._window.FindName(u"LinksListPanel")
        panel.Children.Clear()
        self._link_rows = []
        for i, info in enumerate(self._links):
            is_last = (i == len(self._links) - 1)
            row_data = self._make_link_row(info, is_last)
            panel.Children.Add(row_data[u"border"])
            self._link_rows.append(row_data)
        self._update_links_label()

    def _make_link_row(self, info, is_last):
        loaded = info[u"loaded"]

        outer = WC.Border()
        outer.Padding    = System.Windows.Thickness(12, 10, 12, 10)
        outer.Background = WM.Brushes.White if loaded else _color(WM.Color.FromRgb(0xfa, 0xfb, 0xfc))
        outer.Opacity    = 1.0 if loaded else 0.62
        if not is_last:
            outer.BorderBrush     = _color(LINE_COLOR)
            outer.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)

        grid = WC.Grid()
        grid.ColumnDefinitions.Add(WC.ColumnDefinition())
        grid.ColumnDefinitions.Add(WC.ColumnDefinition())
        grid.ColumnDefinitions[0].Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
        grid.ColumnDefinitions[1].Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Auto)

        # Left: checkbox + name + discipline
        left = WC.StackPanel()
        left.Orientation = WC.Orientation.Horizontal
        WC.Grid.SetColumn(left, 0)

        # Checkbox border
        cb_outer = WC.Border()
        cb_outer.Width           = 18
        cb_outer.Height          = 18
        cb_outer.CornerRadius    = System.Windows.CornerRadius(5)
        cb_outer.VerticalAlignment = System.Windows.VerticalAlignment.Center
        cb_outer.Margin          = System.Windows.Thickness(0, 0, 10, 0)
        cb_outer.Cursor          = WI.Cursors.Hand if loaded else WI.Cursors.No

        cb_check = WC.TextBlock()
        cb_check.Text              = u"✓"
        cb_check.FontSize          = 11
        cb_check.FontWeight        = System.Windows.FontWeights.Bold
        cb_check.Foreground        = WM.Brushes.White
        cb_check.HorizontalAlignment = System.Windows.HorizontalAlignment.Center
        cb_check.VerticalAlignment   = System.Windows.VerticalAlignment.Center
        cb_outer.Child = cb_check

        texts = WC.StackPanel()
        name_tb = WC.TextBlock()
        name_tb.Text       = info[u"name"]
        name_tb.FontFamily = WM.FontFamily(u"Consolas")
        name_tb.FontSize   = 12.5
        name_tb.FontWeight = System.Windows.FontWeights.SemiBold
        disc_tb = WC.TextBlock()
        disc_tb.Text     = info[u"disc"]
        disc_tb.FontSize = 11.5
        disc_tb.Foreground = _color(MUTED_COLOR)
        disc_tb.Margin   = System.Windows.Thickness(0, 1, 0, 0)
        texts.Children.Add(name_tb)
        texts.Children.Add(disc_tb)

        left.Children.Add(cb_outer)
        left.Children.Add(texts)

        # Right: tag badge + status
        right = WC.StackPanel()
        right.Orientation        = WC.Orientation.Horizontal
        right.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        right.VerticalAlignment   = System.Windows.VerticalAlignment.Center
        WC.Grid.SetColumn(right, 1)

        tag_border = WC.Border()
        tag_border.Background    = _color(WM.Color.FromRgb(0xec, 0xf8, 0xfc))
        tag_border.BorderBrush   = _color(WM.Color.FromRgb(0xb8, 0xe8, 0xf2))
        tag_border.BorderThickness = System.Windows.Thickness(1)
        tag_border.CornerRadius  = System.Windows.CornerRadius(10)
        tag_border.Padding       = System.Windows.Thickness(7, 2, 7, 2)
        tag_border.Margin        = System.Windows.Thickness(0, 0, 10, 0)
        tag_tb = WC.TextBlock()
        tag_tb.Text      = info[u"tag"]
        tag_tb.FontSize  = 11
        tag_tb.FontWeight = System.Windows.FontWeights.SemiBold
        tag_tb.Foreground = _color(CYAN_COLOR)
        tag_border.Child = tag_tb

        status_tb = WC.TextBlock()
        status_tb.Text     = u"Loaded" if loaded else u"Unloaded"
        status_tb.FontSize = 11.5
        status_tb.Foreground = _color(GREEN_COLOR) if loaded else _color(MUTED_COLOR)

        right.Children.Add(tag_border)
        right.Children.Add(status_tb)

        grid.Children.Add(left)
        grid.Children.Add(right)
        outer.Child = grid

        row_data = {
            u"info":     info,
            u"border":   outer,
            u"cb_outer": cb_outer,
            u"cb_check": cb_check,
            u"name_tb":  name_tb,
        }

        def _refresh_cb(rd=row_data):
            on = rd[u"info"][u"on"]
            if on:
                rd[u"cb_outer"].Background   = _color(NAVY_COLOR)
                rd[u"cb_outer"].BorderBrush  = _color(NAVY_COLOR)
                rd[u"cb_outer"].BorderThickness = System.Windows.Thickness(1.5)
                rd[u"cb_check"].Visibility   = System.Windows.Visibility.Visible
            else:
                rd[u"cb_outer"].Background   = WM.Brushes.White
                rd[u"cb_outer"].BorderBrush  = _color(WM.Color.FromRgb(0xc6, 0xcb, 0xe0))
                rd[u"cb_outer"].BorderThickness = System.Windows.Thickness(1.5)
                rd[u"cb_check"].Visibility   = System.Windows.Visibility.Collapsed

        row_data[u"refresh_cb"] = _refresh_cb
        _refresh_cb()

        if loaded:
            def on_click(s, e, rd=row_data):
                rd[u"info"][u"on"] = not rd[u"info"][u"on"]
                rd[u"refresh_cb"]()
                self._update_links_label()
                self._update_next_enabled()

            outer.MouseLeftButtonUp += on_click

        return row_data

    def _update_links_label(self):
        loadable = [r for r in self._link_rows if r[u"info"][u"loaded"]]
        sel_count = sum(1 for r in loadable if r[u"info"][u"on"])
        self._window.FindName(u"LinksLabel").Text = (
            u"LINKED MODELS · {} OF {} SELECTED".format(sel_count, len(loadable))
        )
        all_on = all(r[u"info"][u"on"] for r in loadable) if loadable else False
        self._window.FindName(u"ToggleAllBtn").Content = (
            u"Deselect all" if all_on else u"Select all"
        )

    # ── Existing section template setup ──────────────────────────────────────

    def _setup_existing_template(self):
        """Resolve EB_MEP_CUR_SE_1-50; if absent, show a picker for alternatives."""
        default = find_view_template(EXISTING_TEMPLATE)
        if default:
            self._sel_existing_tmpl = default
            return  # locked display stays unchanged

        # Default not found — collect all section view templates.
        all_tmpls = sorted(
            [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
             if v.IsTemplate and v.ViewType == DB.ViewType.Section],
            key=lambda v: v.Name
        )
        self._available_sec_tmpls = all_tmpls

        w = self._window
        tmpl_tb = w.FindName(u"ExistTmplNameTB")
        if tmpl_tb:
            tmpl_tb.Text       = u"Not found — pick below"
            tmpl_tb.Foreground = _color(WM.Color.FromRgb(0xc8, 0x85, 0x0d))
        lock_tb = w.FindName(u"ExistTmplLockTB")
        if lock_tb:
            lock_tb.Text       = u"⚠"
            lock_tb.Foreground = _color(WM.Color.FromRgb(0xc8, 0x85, 0x0d))

        container = w.FindName(u"ExistTmplPickerContainer")
        if container:
            container.Visibility = System.Windows.Visibility.Visible

        panel = w.FindName(u"ExistTmplPickerPanel")
        if panel:
            self._tmpl_rows = []
            for i, tmpl in enumerate(all_tmpls):
                is_last = (i == len(all_tmpls) - 1)
                row = self._make_tmpl_row(tmpl, is_last)
                panel.Children.Add(row[u"border"])
                self._tmpl_rows.append(row)
            if all_tmpls:
                self._sel_existing_tmpl = all_tmpls[0]
                self._update_tmpl_selection()

    def _make_tmpl_row(self, tmpl, is_last):
        border = WC.Border()
        border.Padding    = System.Windows.Thickness(10, 9, 10, 9)
        border.Background = WM.Brushes.Transparent
        border.Cursor     = WI.Cursors.Hand
        if not is_last:
            border.BorderBrush     = _color(LINE_COLOR)
            border.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)

        row = WC.StackPanel()
        row.Orientation = WC.Orientation.Horizontal

        icon_tb = WC.TextBlock()
        icon_tb.Text              = u"○"
        icon_tb.FontSize          = 14
        icon_tb.Foreground        = _color(GRAY_COLOR)
        icon_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
        icon_tb.Margin            = System.Windows.Thickness(0, 0, 10, 0)

        name_tb = WC.TextBlock()
        name_tb.Text              = tmpl.Name
        name_tb.FontFamily        = WM.FontFamily(u"Consolas")
        name_tb.FontSize          = 12.5
        name_tb.Foreground        = _color(BODY_COLOR)
        name_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center

        row.Children.Add(icon_tb)
        row.Children.Add(name_tb)
        border.Child = row

        row_data = {u"tmpl": tmpl, u"border": border, u"icon_tb": icon_tb}

        def on_click(s, e, rd=row_data):
            self._sel_existing_tmpl = rd[u"tmpl"]
            self._update_tmpl_selection()

        border.MouseLeftButtonUp += on_click
        return row_data

    def _update_tmpl_selection(self):
        for rd in self._tmpl_rows:
            sel = (self._sel_existing_tmpl is not None and
                   rd[u"tmpl"].Id == self._sel_existing_tmpl.Id)
            if sel:
                rd[u"border"].Background = _color(SEL_BG)
                rd[u"icon_tb"].Text      = u"✓"
                rd[u"icon_tb"].Foreground = _color(CYAN_COLOR)
            else:
                rd[u"border"].Background = WM.Brushes.Transparent
                rd[u"icon_tb"].Text      = u"○"
                rd[u"icon_tb"].Foreground = _color(GRAY_COLOR)

    # ── Step navigation ───────────────────────────────────────────────────────

    def _go_to_step(self, step):
        self._step = step
        vis  = System.Windows.Visibility.Visible
        col  = System.Windows.Visibility.Collapsed
        w    = self._window

        w.FindName(u"Step1Panel").Visibility = vis if step == 1 else col
        w.FindName(u"Step2Panel").Visibility = vis if step == 2 else col
        w.FindName(u"Step3Panel").Visibility = vis if step == 3 else col
        w.FindName(u"Step4Panel").Visibility = vis if step == 4 else col

        # Footer buttons
        w.FindName(u"CancelBtn").Visibility  = vis if step == 1 else col
        w.FindName(u"BackBtn").Visibility    = vis if step > 1 and not self._done else col
        w.FindName(u"NextBtn").Visibility    = vis if step < 4 and not self._done else col
        w.FindName(u"RunBtn").Visibility     = vis if step == 4 and not self._done else col
        w.FindName(u"AgainBtn").Visibility   = vis if self._done else col
        w.FindName(u"OpenBtn").Visibility    = vis if self._done else col

        # Step count label
        if not self._done:
            w.FindName(u"StepLabel").Text = u"Step {} of 4".format(step)
        else:
            w.FindName(u"StepLabel").Text = u""

        self._update_next_enabled()
        self._update_stepper(step)
        self._update_banner(step)

        if step == 3:
            self._refresh_step3()
        if step == 4 and not self._done:
            self._refresh_step4_review()

    def _update_stepper(self, step):
        circles = [
            (u"SC1", u"SN1", u"SL1"),
            (u"SC2", u"SN2", u"SL2"),
            (u"SC3", u"SN3", u"SL3"),
            (u"SC4", u"SN4", u"SL4"),
        ]
        done_color  = WM.Color.FromRgb(0x22, 0xb0, 0x7c)
        for i, (cn, nn, ln) in enumerate(circles):
            s = i + 1
            circle = self._window.FindName(cn)
            num_tb = self._window.FindName(nn)
            lbl_tb = self._window.FindName(ln)
            if self._done or s < step:
                circle.Background = _color(done_color)
                num_tb.Text       = u"✓"
                lbl_tb.Foreground = _color(done_color)
                lbl_tb.FontWeight = System.Windows.FontWeights.SemiBold
            elif s == step:
                circle.Background = _color(NAVY_COLOR)
                num_tb.Text       = str(s)
                lbl_tb.Foreground = _color(NAVY_COLOR)
                lbl_tb.FontWeight = System.Windows.FontWeights.SemiBold
            else:
                circle.Background = _color(GRAY_COLOR)
                num_tb.Text       = str(s)
                lbl_tb.Foreground = _color(MUTED_COLOR)
                lbl_tb.FontWeight = System.Windows.FontWeights.Normal

    def _update_banner(self, step):
        w = self._window
        banner_border = w.FindName(u"BannerBorder")
        banner_text   = w.FindName(u"BannerText")
        vis = System.Windows.Visibility.Visible
        col = System.Windows.Visibility.Collapsed
        if self._done:
            banner_border.Visibility = col
        else:
            banner_border.Visibility = vis
            banner_text.Text = BANNERS[step - 1]

    def _update_next_enabled(self):
        next_btn = self._window.FindName(u"NextBtn")
        run_btn  = self._window.FindName(u"RunBtn")
        if self._step == 2:
            sel = sum(1 for r in self._link_rows if r[u"info"][u"on"] and r[u"info"][u"loaded"])
            next_btn.IsEnabled = sel > 0
        else:
            next_btn.IsEnabled = True
        if self._step == 4:
            run_btn.IsEnabled = self._sel_sheet is not None

    def _refresh_step3(self):
        w = self._window
        view_name = u"{} Solution".format(self._sel_section) if self._sel_section else u"—"
        w.FindName(u"S3ViewName").Text = view_name
        w.FindName(u"S3Depth").Text    = self._sel_section or u"—"
        if self._sel_sheet:
            w.FindName(u"S3Sheet").Text = u"{} · {}".format(
                self._sel_sheet.SheetNumber, self._sel_sheet.Name)
        else:
            w.FindName(u"S3Sheet").Text = u"No sheet selected — go back to Step 1"

        # Show a notice if the existing section doesn't already have the chosen template.
        notice    = w.FindName(u"ExistSectionTmplNotice")
        notice_tb = w.FindName(u"ExistSectionTmplNoticeTB")
        if notice and notice_tb and self._sel_existing_tmpl:
            sel_view = next(
                (v for v in self._sections if v.Name == self._sel_section), None)
            needs_assign = (
                sel_view is not None and
                sel_view.ViewTemplateId != self._sel_existing_tmpl.Id
            )
            if needs_assign:
                notice_tb.Text = (
                    u"The existing section does not use “{}” — "
                    u"the template will be assigned when you run.".format(
                        self._sel_existing_tmpl.Name))
                notice.Visibility = System.Windows.Visibility.Visible
            else:
                notice.Visibility = System.Windows.Visibility.Collapsed

    def _refresh_step4_review(self):
        w = self._window
        sel_links = [r[u"info"] for r in self._link_rows
                     if r[u"info"][u"on"] and r[u"info"][u"loaded"]]
        tags = list({l[u"tag"] for l in sel_links})
        w.FindName(u"R_ExistSection").Text = self._sel_section or u"—"
        w.FindName(u"R_Links").Text        = u"{} selected · {}".format(
            len(sel_links), u", ".join(tags))
        w.FindName(u"R_SolSection").Text   = u"{} Solution".format(self._sel_section or u"Section")
        if self._sel_sheet:
            sheet_str = u"{} · {}".format(
                self._sel_sheet.SheetNumber, self._sel_sheet.Name)
            w.FindName(u"R_Sheet").Text       = sheet_str
            w.FindName(u"R_Sheet").Foreground = _color(WM.Color.FromRgb(0x1f, 0x29, 0x37))
        else:
            w.FindName(u"R_Sheet").Text       = u"None selected"
            w.FindName(u"R_Sheet").Foreground = _color(WM.Color.FromRgb(0xe0, 0x80, 0x00))

        r_tmpl = w.FindName(u"R_ExistTmpl")
        if r_tmpl:
            tmpl_name = (self._sel_existing_tmpl.Name
                         if self._sel_existing_tmpl else EXISTING_TEMPLATE)
            r_tmpl.Text = u"{} · 1 : 50".format(tmpl_name)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_cancel(self, s, e):
        self.cancelled = True
        self._window.Close()

    def _on_back(self, s, e):
        if self._step > 1:
            self._go_to_step(self._step - 1)

    def _on_next(self, s, e):
        if self._step < 4:
            self._go_to_step(self._step + 1)

    def _on_run(self, s, e):
        w = self._window
        run_btn = w.FindName(u"RunBtn")
        run_btn.IsEnabled = False
        run_btn.Content   = u"Running..."

        selected_section = next(
            (v for v in self._sections if v.Name == self._sel_section), None)
        selected_links = [r[u"info"] for r in self._link_rows
                          if r[u"info"][u"on"] and r[u"info"][u"loaded"]]
        skip_dup = bool(w.FindName(u"SkipDupToggle").IsChecked)

        try:
            results, new_sv = run(selected_section, self._sel_sheet,
                                  selected_links, skip_dup,
                                  existing_template=self._sel_existing_tmpl)
            self._result_section_view = new_sv
            self._show_result(results, selected_links, new_sv)
            self.cancelled = False
            # Revit's main window steals focus after API transactions; bring
            # the dialog back to the front.
            try:
                self._window.Topmost = True
                self._window.Activate()
                self._window.Topmost = False
            except Exception:
                pass
        except Exception as ex:
            run_btn.IsEnabled = True
            run_btn.Content   = u"▶  Run"
            forms.alert(
                u"Solution Section failed:\n\n{}".format(traceback.format_exc()),
                title=u"EasyBIM — Error"
            )

    def _show_result(self, results, sel_links, new_sv):
        self._done = True
        w = self._window
        total = sum(results.values()) if results else 0

        # Show result panel, hide review panel
        w.FindName(u"ReviewPanel").Visibility = System.Windows.Visibility.Collapsed
        w.FindName(u"ResultPanel").Visibility = System.Windows.Visibility.Visible

        # Summary line
        w.FindName(u"Res_Summary").Text = u"{} elements copied to “MEP Solution” · {} links".format(
            total, len(sel_links))

        # Per-link counts
        lp = w.FindName(u"ResultLinksPanel")
        lp.Children.Clear()
        for i, info in enumerate(sel_links):
            cnt   = results.get(info[u"name"], 0)
            is_last = (i == len(sel_links) - 1)
            row   = WC.Border()
            row.Padding = System.Windows.Thickness(12, 9, 12, 9)
            if not is_last:
                row.BorderBrush     = _color(LINE_COLOR)
                row.BorderThickness = System.Windows.Thickness(0, 0, 0, 1)
            inner = WC.Grid()
            c1 = WC.ColumnDefinition()
            c2 = WC.ColumnDefinition()
            c1.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
            c2.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Auto)
            inner.ColumnDefinitions.Add(c1)
            inner.ColumnDefinitions.Add(c2)
            left_row = WC.StackPanel()
            left_row.Orientation = WC.Orientation.Horizontal
            WC.Grid.SetColumn(left_row, 0)
            chk_tb = WC.TextBlock()
            chk_tb.Text      = u"✓"
            chk_tb.FontSize  = 13
            chk_tb.Foreground = _color(GREEN_COLOR)
            chk_tb.Margin    = System.Windows.Thickness(0, 0, 9, 0)
            chk_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
            link_tb = WC.TextBlock()
            link_tb.Text       = info[u"name"]
            link_tb.FontFamily = WM.FontFamily(u"Consolas")
            link_tb.FontSize   = 12.5
            link_tb.Foreground = _color(BODY_COLOR)
            link_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
            left_row.Children.Add(chk_tb)
            left_row.Children.Add(link_tb)
            cnt_tb = WC.TextBlock()
            cnt_tb.Text       = str(cnt)
            cnt_tb.FontFamily = WM.FontFamily(u"Consolas")
            cnt_tb.FontSize   = 12.5
            cnt_tb.FontWeight = System.Windows.FontWeights.Bold
            cnt_tb.Foreground = _color(NAVY_COLOR)
            cnt_tb.VerticalAlignment = System.Windows.VerticalAlignment.Center
            WC.Grid.SetColumn(cnt_tb, 1)
            inner.Children.Add(left_row)
            inner.Children.Add(cnt_tb)
            row.Child = inner
            lp.Children.Add(row)

        # Result details
        view_name = new_sv.Name if new_sv else u"{} Solution".format(self._sel_section)
        w.FindName(u"Res_Name").Text = view_name
        if self._sel_sheet:
            w.FindName(u"Res_Sheet").Text = u"{} · {}".format(
                self._sel_sheet.SheetNumber, self._sel_sheet.Name)
        else:
            w.FindName(u"Res_Sheet").Text = u"—"

        self._go_to_step(4)

    def _on_again(self, s, e):
        self._done = False
        self._result_section_view = None
        w = self._window
        w.FindName(u"ReviewPanel").Visibility = System.Windows.Visibility.Visible
        w.FindName(u"ResultPanel").Visibility = System.Windows.Visibility.Collapsed
        # Reset link selections to all-on for loaded links
        for r in self._link_rows:
            r[u"info"][u"on"] = r[u"info"][u"loaded"]
            r[u"refresh_cb"]()
        self._update_links_label()
        self._go_to_step(1)

    def _on_open_sheet(self, s, e):
        if self._sel_sheet:
            try:
                uidoc = revit.uidoc
                uidoc.ActiveView = self._sel_sheet
            except Exception:
                pass
        self._window.Close()

    def _on_sheet_search(self, sender, e):
        query = sender.Text or u""
        hint  = self._window.FindName(u"SheetHint")
        hint.Visibility = (System.Windows.Visibility.Collapsed
                           if query else System.Windows.Visibility.Visible)
        self._populate_sheets(query)

    def _hide_hint(self, s):
        self._window.FindName(u"SheetHint").Visibility = System.Windows.Visibility.Collapsed

    def _show_hint(self, s, hint_tb):
        if not s.Text:
            hint_tb.Visibility = System.Windows.Visibility.Visible

    def _on_toggle_all(self, s, e):
        loadable = [r for r in self._link_rows if r[u"info"][u"loaded"]]
        all_on = all(r[u"info"][u"on"] for r in loadable)
        new_state = not all_on
        for r in loadable:
            r[u"info"][u"on"] = new_state
            r[u"refresh_cb"]()
        self._update_links_label()
        self._update_next_enabled()

    # ── Show ──────────────────────────────────────────────────────────────────

    def show(self):
        from System.Windows.Threading import Dispatcher, DispatcherFrame
        window = self._build()
        frame  = DispatcherFrame()

        def on_closed(s, e):
            frame.Continue = False

        window.Closed += on_closed
        window.Show()
        Dispatcher.PushFrame(frame)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    sections = get_section_views()
    if not sections:
        forms.alert(u"No section views found in this model.", title=u"EasyBIM")
        return

    sheets = get_sheets()
    links  = get_linked_models()

    dlg = SolutionSectionDialog(sections, sheets, links)
    dlg.show()

    if dlg.cancelled:
        return

    if dlg._result_section_view:
        forms.alert(
            u'Solution section "{}" created successfully.'.format(
                dlg._result_section_view.Name),
            title=u"EasyBIM — Done"
        )


main()

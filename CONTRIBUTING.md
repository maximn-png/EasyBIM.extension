# Contributing to EasyBIM Extension

## Adding a New Command

1. **Pick a panel** — Modeling, Documentation, Data, QC, or Utilities.
2. **Duplicate** `EasyBIM.tab/Utilities.panel/HelloEasyBIM.pushbutton/` into the target panel folder.
3. **Rename** the folder to `YourFeatureName.pushbutton`.
4. **Edit `script.py`** — write your command logic. Always start with `#! python3`.
5. **Edit `bundle.yaml`** — fill in title, tooltip, author, and keep `min_revit_ver: 2023`.
6. **Add to `.layout`** — open the panel's `.layout` file and add `YourFeatureName` on a new line.
7. **Add an icon** — place a `icon.png` (32×32 px) in your button folder (optional but recommended).
8. **Test in Revit** — load PyRevit, reload the extension, and confirm the button works.
9. **Push a branch and open a PR** — use the PR template checklist.

## Shared Library

Put reusable code in `lib/easybim/`:
- `revit.py` — Revit API helpers (collectors, transactions)
- `ui.py` — alerts, dialogs, selection prompts
- `data.py` — parameter read/write utilities

Import in any script:
```python
from easybim import revit, ui, data
```

## Branch Naming

```
feature/short-description
fix/short-description
```

## Rules

- Never commit to `main` directly — always open a PR.
- Keep each PR to one command or one fix.
- No hardcoded file paths or user-specific values.

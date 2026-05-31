# EasyBIM PyRevit Extension

A shared PyRevit extension for the EasyBIM team. Supports Revit 2023 and above.

---

## For Revit Users (non-developers)

### First-time setup

1. Install [PyRevit](https://github.com/pyrevitlabs/pyRevit/releases) (latest release).
2. Open Revit → **pyRevit** tab → **pyRevit Settings**.
3. Go to **Extensions** tab → click **Add Extension from Repository**.
4. Paste the URL: `https://github.com/maxim-png/EasyBIM.extension`
5. Click **Install** → restart Revit.

The **EasyBIM** tab will appear in your Revit ribbon.

### Getting updates

Updates are automatic. Every time Revit starts, PyRevit checks for new commits and pulls them. No action needed.

---

## For Developers

### First-time setup

1. Install PyRevit (see above).
2. Clone this repo into your PyRevit extensions folder:
   ```
   git clone https://github.com/maxim-png/EasyBIM.extension "%APPDATA%\pyRevit\Extensions\EasyBIM.extension"
   ```
3. In PyRevit Settings → Extensions, confirm the extension is listed and enabled.
4. Restart Revit.

### Adding a new command

See [CONTRIBUTING.md](CONTRIBUTING.md) for step-by-step instructions.

---

## Folder Structure

```
EasyBIM.extension/
├── EasyBIM.tab/
│   ├── Modeling.panel/        ← BIM / geometry tools
│   ├── Documentation.panel/   ← sheets, views, annotations
│   ├── Data.panel/            ← parameters, schedules, exports
│   ├── QC.panel/              ← model checking, audits
│   └── Utilities.panel/
│       └── HelloEasyBIM.pushbutton/   ← sample command (copy to start)
├── lib/
│   └── easybim/               ← shared Python library
│       ├── revit.py
│       ├── ui.py
│       └── data.py
├── hooks/                     ← PyRevit event hooks
└── startup.py
```

---

## Requirements

- Revit 2023 or newer
- PyRevit 4.8 or newer

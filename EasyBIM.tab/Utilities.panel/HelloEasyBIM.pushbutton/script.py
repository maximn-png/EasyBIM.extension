#! python3
# -*- coding: UTF-8 -*-
"""Sample EasyBIM command — copy this folder to create a new button.

HOW TO ADD A NEW COMMAND:
1. Duplicate this entire folder (HelloEasyBIM.pushbutton)
2. Rename it to YourFeature.pushbutton
3. Edit script.py and bundle.yaml
4. Add your button name to the parent panel's .layout file
5. Commit and push — the team gets it automatically on next Revit launch
"""

__title__ = "Hello\nEasyBIM"
__doc__ = "Sample command. Shows a welcome message."

from pyrevit import forms

forms.alert("Hello from EasyBIM!\n\nCopy this pushbutton folder to start building a new feature.", title="EasyBIM")

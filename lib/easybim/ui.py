#! python3
# -*- coding: UTF-8 -*-
"""UI helper utilities — alerts, input dialogs, selection prompts."""

from pyrevit import forms


def alert(message, title="EasyBIM"):
    forms.alert(message, title=title)


def ask_yes_no(question, title="EasyBIM"):
    return forms.alert(question, title=title, yes=True, no=True)


def pick_from_list(options, title="Select an option", prompt=""):
    return forms.SelectFromList.show(options, title=title, button_name="Select")

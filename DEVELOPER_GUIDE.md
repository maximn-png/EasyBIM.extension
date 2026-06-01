# Developer Guide — EasyBIM Extension

Welcome to the team. This guide explains everything you need to know to build new buttons for the EasyBIM plugin — from first setup to getting your work into everyone's Revit.

You do not need to be a professional programmer. Claude Code writes the code for you. Your job is to describe what the button should do, test it in Revit, and submit it for review.

---

## The Big Picture

The EasyBIM plugin lives on GitHub — a platform for storing and sharing code. Think of it like a shared folder for code, but with a history of every change ever made and the ability to review changes before they affect everyone.

When Maxim approves a change and it goes into the "main" version, every team member gets that update automatically the next time they open Revit. This means a button you build today could be in everyone's Revit tomorrow — so we have a simple review step to make sure nothing breaks.

---

## Before You Start — Ask Maxim

You need two things from Maxim before you can do anything:

1. **Access to the repository** — the plugin code is private. Maxim needs to add your GitHub account so you can see and work with it. Send him your GitHub username (create a free account at github.com if you don't have one).

2. **A button to work on** — agree with Maxim on which button or panel you will be developing. This avoids two people accidentally working on the same thing at the same time.

---

## First-Time Setup (do this once)

Install these four tools:

| Tool | What it is | Download |
|---|---|---|
| PyRevit | Loads the plugin into Revit | https://github.com/pyrevitlabs/pyRevit/releases |
| Git | Keeps your code in sync with GitHub | https://git-scm.com/download/win |
| VS Code | Code editor | https://code.visualstudio.com |
| Claude Code | AI that writes the code for you | https://claude.ai/download |

Once everything is installed, open PowerShell and run this one command — it downloads the plugin code to the exact folder where Revit will find it:

```powershell
git clone https://github.com/maximn-png/EasyBIM.extension "$env:APPDATA\pyRevit\Extensions\EasyBIM.extension"
```

Then open Revit, go to **pyRevit tab → pyRevit Settings → Extensions**, find EasyBIM in the list, make sure it is enabled, save and restart Revit. You should see the EasyBIM tab in the ribbon.

---

## Building a Button

**Step 1 — Open the plugin folder in VS Code**

```powershell
code "$env:APPDATA\pyRevit\Extensions\EasyBIM.extension"
```

**Step 2 — Start a Claude Code session**

Inside VS Code, open Claude Code and describe what you want to build. Be specific — the more detail you give, the better the result. For example:

> *"Add a button in the Modeling panel called Wall Lengths. When clicked, it should select all walls in the active view and show a message with the total length in meters."*

> *"Create a QC button that checks every room in the model has a value in the Department parameter. List any rooms that are missing it."*

Claude Code will create the button files automatically. You do not need to write any code yourself.

**Step 3 — Test it in Revit immediately**

Go to Revit and click **pyRevit tab → Reload**. Your new button appears in the ribbon right away. Click it and see if it does what you wanted. If something is wrong or you want to change it, go back to Claude Code, describe the issue, and reload again. Repeat until it works correctly.

This loop — describe → reload → test → describe again — is the whole development process. You never need to restart Revit.

---

## Submitting Your Work

Once you are happy with your button, you submit it for Maxim to review. This is a three-step process:

**Step 1 — Save your work to a branch**

A branch is your own private copy of the code on GitHub. Think of it like a draft — it doesn't affect anyone else until Maxim approves it.

Open PowerShell and run:

```powershell
cd "$env:APPDATA\pyRevit\Extensions\EasyBIM.extension"
git checkout -b feature/name-of-your-button
git add .
git commit -m "Add: short description of what the button does"
git push origin feature/name-of-your-button
```

**Step 2 — Open a Pull Request**

Go to `https://github.com/maximn-png/EasyBIM.extension` — you will see a yellow banner saying your branch was recently pushed, with a button **"Compare & pull request"**. Click it, fill in the description of what your button does, and click **Create pull request**.

**Step 3 — Wait for Maxim's review**

Maxim will look at your code, may leave comments or ask for small changes, and when he is happy he will merge it. Once merged, the button goes live for the whole team on their next Revit startup.

---

## Why These Rules Exist

**Why can't I just push directly to the main version?**
The main branch is what everyone on the team runs. A bug there breaks Revit for the whole team simultaneously. The review step is a two-minute safety check that prevents this.

**Why do I need Maxim's approval?**
Maxim knows the full state of the plugin — what other people are building, what naming conventions we follow, and whether your button might conflict with something else. It is not about trust, it is about coordination.

**Why branches?**
A branch lets you work freely without affecting anyone else. You can experiment, break things, and fix them — none of that touches the live version until you are ready and it has been reviewed.

**Why GitHub at all?**
GitHub keeps the full history of every change. If a button breaks something, we can immediately see exactly what changed and who changed it. It also makes sure everyone is always working from the same version of the code.

---

## Quick Reference

| What you want to do | How |
|---|---|
| Get access to the repo | Ask Maxim for your GitHub username to be added |
| Set up for the first time | Run the `git clone` command above, enable in PyRevit Settings |
| Start building a button | Open folder in VS Code, describe to Claude Code |
| Test your button | pyRevit tab → Reload (no restart needed) |
| Submit your work | `git checkout -b`, `git add .`, `git commit`, `git push`, then open PR on GitHub |
| Get help | Ask Maxim |

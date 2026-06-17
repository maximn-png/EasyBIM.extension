@echo off
echo Syncing EasyBIM plugin with the latest changes from GitHub...
echo.
cd /d "%APPDATA%\pyRevit\Extensions\EasyBIM.extension.extension"
git pull
echo.
echo Done! Reload pyRevit in Revit to see the latest buttons (pyRevit tab ^> Reload).
pause

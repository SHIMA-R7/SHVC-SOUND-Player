@echo off
setlocal
cd /d "%~dp0.."
set "SHVC_APU_PORT=%~1"
if not defined SHVC_APU_PORT set "SHVC_APU_PORT=COM6"
set "SHVC_APU_LOG=%CD%\docs\tmp\retroarch-real-apu.log"
set "SHVC_RETROARCH=%CD%\docs\tmp\retroarch-portable\RetroArch-Win64\retroarch.exe"
if not exist "%SHVC_RETROARCH%" (echo Portable RetroArch is missing. & pause & exit /b 1)
if not exist "%CD%\SHVC-SOUND-RetroArch\artifacts\snes9x_shvc_libretro.dll" (echo Build the SHVC core first. & pause & exit /b 1)
"%SHVC_RETROARCH%" --config "%CD%\SHVC-SOUND-RetroArch\shvc-retroarch.cfg" -L "%CD%\SHVC-SOUND-RetroArch\artifacts\snes9x_shvc_libretro.dll" "%CD%\..\..\..\SFC-ROM\SuperMarioWorld.sfc"

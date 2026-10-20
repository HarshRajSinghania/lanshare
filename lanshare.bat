@echo off
rem ============================================================
rem  LAN Share - double-click karo aur chal jayega
rem  (auto: python check + deps install + server start)
rem ============================================================
title LAN Share
cd /d "%~dp0"

rem --- Python check (Store stub bhi pakadna) ---
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo.
  echo  [X] Python nahi mila / install nahi hai.
  echo      https://www.python.org/downloads/ se install karo
  echo      (installer mein "Add Python to PATH" TICK zaroor karna!)
  echo.
  pause
  exit /b 1
)

rem --- Dependencies (ek baar) ---
%PY% -c "import aiohttp, segno" >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [*] Pehli baar: aiohttp + segno install ho rahe hain...
  echo.
  %PY% -m pip install --quiet aiohttp segno
  if errorlevel 1 (
    echo.
    echo  [X] Install fail. Check internet ya chalao:
    echo      %PY% -m pip install aiohttp segno
    echo.
    pause
    exit /b 1
  )
)

rem --- Server start (browser khud khulega) ---
echo.
echo  [*] LAN Share chal raha hai... browser khulega.
echo      Band karne ke liye is window mein Ctrl+C dabao.
echo.
%PY% lanshare.py
echo.
echo  [*] LAN Share band ho gaya.
pause

@echo off
title LAN Share
cd /d "%~dp0"

rem --- banner turant dikhe, buffer na ho ---
set "PYTHONUNBUFFERED=1"

rem --- Python check: cmd python, phir py launcher ---
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if defined PY goto :deps
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if defined PY goto :deps

echo.
echo  [X] Python nahi mila / install nahi hai.
echo      https://www.python.org/downloads/ se install karo.
echo      Installer mein "Add Python to PATH" tick zaroor karna.
echo.
pause
exit /b 1

:deps
rem --- Dependencies sirf pehli baar install hongi ---
%PY% -c "import aiohttp, segno" >nul 2>nul
if not errorlevel 1 goto :run

echo.
echo  [*] Pehli baar: aiohttp + segno install ho rahe hain...
echo.
%PY% -m pip install --quiet aiohttp segno
if not errorlevel 1 goto :run

echo.
echo  [X] Install fail. Internet check karke khud chalao:
echo      %PY% -m pip install aiohttp segno
echo.
pause
exit /b 1

:run
echo.
echo  [*] LAN Share chal raha hai... browser khulega.
echo      Band karne ke liye is window mein Ctrl+C dabao.
echo.
%PY% lanshare.py

echo.
echo  [*] LAN Share band ho gaya.
pause

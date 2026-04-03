@echo off
setlocal

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python -m ksharp.kar_cli %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m ksharp.kar_cli %*
  exit /b %ERRORLEVEL%
)

echo Python was not found on PATH.
exit /b 1

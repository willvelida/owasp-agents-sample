@echo off
rem Starts the harness CLI. Every check lives in .harness\; this only finds Node.
where node >nul 2>&1 || (
  echo error: node not found
  echo next: install Node.js 24.22.0 or later ^(see CONTRIBUTING.md, Prerequisites^)
  exit /b 2
)
node "%~dp0.harness\harness.mjs" %*
exit /b %ERRORLEVEL%

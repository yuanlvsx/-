@echo off
chcp 65001 >nul
setlocal
rem 优先使用项目内的虚拟环境（.venv），没有则用 PATH 里的 pythonw
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0app.py"
endlocal

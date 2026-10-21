@echo off
chcp 65001 >nul
setlocal
rem 优先使用项目内的虚拟环境（.venv），没有则用 PATH 里的 python
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0app.py"
echo.
echo ---- 程序已退出，按任意键关闭窗口 ----
pause >nul
endlocal

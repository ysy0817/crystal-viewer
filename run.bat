@echo off
rem 不安装也能直接运行：把 src 加入 PYTHONPATH 后调用模块入口。
chcp 65001 >nul
setlocal
set "PYTHONPATH=%~dp0src"
python -m crystal_viewer %*
endlocal

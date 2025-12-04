@echo off
chcp 65001 >nul
title Newton Admin (Localhost Only)
cd /d "%~dp0"


:: 1. 检查环境
if not exist "env\Scripts\python.exe" (
    echo [ERROR] 找不到虚拟环境 env，请先运行 install.bat
    pause
    exit
)

".\env\Scripts\streamlit.exe" run admin.py --server.address 127.0.0.1 --server.port 8501

pause
@echo off
:: 设置 UTF-8 编码
chcp 65001 >nul
title Cyber Newton Installer (Final)
cd /d "%~dp0"
:: 1. 检查并创建虚拟环境
if not exist "env\Scripts\python.exe" (
    echo [INFO] 正在创建新的虚拟环境...
    python -m venv env
)
call env\Scripts\activate
:: 3. 更新 pip (防止版本太低装不上新库)
python -m pip install --upgrade pip
:: 4. 安装所有依赖 (已加入 MemoryOS)
pip install fastapi uvicorn google-generativeai pydantic requests MemoryOS
pip install streamlit pandas
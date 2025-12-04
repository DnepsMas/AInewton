@echo off
chcp 65001 >nul
title Cyber Newton Server Launcher
cd /d "%~dp0"

echo ==========================================
echo    🌐 赛博牛顿局域网启动器
echo ==========================================

:: 1. 检查环境
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] 找不到虚拟环境 env，请先运行 install.bat
    pause
    exit
)

:: 2. 启动后端 (API 服务 - 端口 5050)
echo [1/2] 正在启动后端核心 (Port 5050)...
start "Newton_Backend_API" /min ".\venv\Scripts\python.exe" server.py

:: 3. 启动前端 (Web 服务 - 端口 8000)
:: 这就是你想要的那行指令！它把当前文件夹变成一个网站
echo [2/2] 正在启动网页托管 (Port 8000)...
start "Newton_Web_Host" /min ".\venv\Scripts\python.exe" -m http.server 8000

:: 4. 提示访问地址
echo.
echo ==========================================
echo      ✅ 服务已全部上线！
echo ==========================================
echo.
echo 本机访问: http://localhost:8000
echo.
echo 局域网其他设备访问: http://10.21.156.83:8000
echo (确保你已经在 index.html 里改好了 apiBase IP)
echo.
echo ==========================================
pause
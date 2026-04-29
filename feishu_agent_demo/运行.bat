@echo off
setlocal
chcp 65001 > nul

echo ====================================================
echo   飞书多维表格 Agent 启动器 (Conda 驱动版)
echo ====================================================

:: 1. 检查 Conda 是否可用
conda --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未检测到 Conda 命令！请确认是否已将 Conda 正确添加到环境变量。
    pause
    exit /b
)

:: 2. 激活 Conda 环境
echo [INFO] 正在激活 Conda 虚拟环境: feishu_agent ...
call conda activate feishu_agent

:: 3. 检查 .env 文件
if not exist ".env" (
    echo [WARNING] 未发现 .env 配置文件，请确保已配置 API 凭证！
)

:: 4. 启动主程序
echo [START] 正在启动 Agent 主程序 (main.py)...
echo ----------------------------------------------------
python main.py

echo ----------------------------------------------------
echo [END] 程序已停止运行。
pause
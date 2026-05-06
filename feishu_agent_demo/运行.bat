@echo off
setlocal
chcp 65001 > nul

:: 始终切换到本 bat 所在目录（feishu_agent_demo），保证能读到同目录下的 .env
cd /d "%~dp0"

echo ====================================================
echo   采购多 Agent 启动器（飞书 Bitable + WS）
echo ====================================================

if not exist ".env" (
    echo [WARNING] 当前目录下没有 .env，请复制 .env.example 为 .env 并填写凭证。
)

echo [START] 启动 main.py ...
echo ----------------------------------------------------

:: 优先使用 Conda 环境 feishu_agent（若已配置）
where conda >nul 2>&1
if not errorlevel 1 (
    call conda activate feishu_agent 2>nul
    if not errorlevel 1 (
        python main.py
        goto :done
    )
)

:: 否则使用 PATH 中的 Python（适用于 venv：先手动 activate 再双击本脚本，或改用命令行）
python main.py
if errorlevel 1 (
    echo.
    echo [HINT] 若提示找不到 python，请先: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
)

:done
echo ----------------------------------------------------
echo [END] 程序已退出。
pause

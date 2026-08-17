@echo off
title PersonalKB-QA 一键启动
cd /d "%~dp0"

echo ==============================================
echo    PersonalKB-QA 一键启动
echo ==============================================
echo.

REM 环境检查：后端 venv 是否存在
if not exist "backend\.venv\Scripts\python.exe" (
    echo [错误] 未找到后端环境 backend\.venv，请先按 README 初始化依赖。
    pause
    exit /b 1
)

REM 首次运行：自动构建前端
if not exist "frontend\dist\index.html" (
    echo [1/3] 首次运行，正在构建前端（约 10 秒）...
    cd frontend
    call npm run build
    if errorlevel 1 (
        echo [错误] 前端构建失败，请确认已安装 Node 并执行过 npm install。
        cd ..
        pause
        exit /b 1
    )
    cd ..
) else (
    echo [1/3] 前端已构建，跳过
)

echo [2/3] 正在启动服务（将弹出黑色窗口，请勿关闭）...
start "PersonalKB-QA-Backend" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo [3/3] 稍候自动打开浏览器...
timeout /t 4 /nobreak >nul
start "" http://127.0.0.1:8000

echo.
echo ==============================================
echo   已启动！浏览器将自动打开 http://127.0.0.1:8000
echo.
echo   如果页面未加载，请稍等几秒后手动刷新。
echo   关闭服务：关闭弹出的「PersonalKB-QA-Backend」黑色窗口即可。
echo ==============================================
echo.
pause

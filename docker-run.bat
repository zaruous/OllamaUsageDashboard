@echo off

echo [1/3] Checking usage_data.json...
if not exist usage_data.json (
    (echo []) > usage_data.json
    echo Created usage_data.json
)

echo [2/3] Building and starting Docker container...
docker compose up -d --build

if %ERRORLEVEL% neq 0 (
    echo ERROR: Docker failed. Please make sure Docker Desktop is running.
    pause
    exit /b 1
)

echo [3/3] Done!
echo Open http://localhost:8501 in your browser.
pause

@echo off
rem One-click demo launcher. Keep this file ASCII-only: cmd.exe reads
rem batch files in the OEM codepage, so UTF-8 Chinese here breaks parsing.
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=%~dp0..\..\work\hf_cache
rem Models are already cached; offline mode avoids slow hub retries at startup
set HF_HUB_OFFLINE=1
cd /d "%~dp0"

echo [1/2] Starting FastAPI on http://127.0.0.1:8000 ...
start "RAG API" cmd /k python -m uvicorn app.api:app --host 127.0.0.1 --port 8000

echo [2/2] Starting Streamlit on http://127.0.0.1:8501 ...
rem --server.headless true skips the first-run email prompt that would block the console
start "RAG UI" cmd /k python -m streamlit run app\ui.py --server.port 8501 --server.headless true --browser.gatherUsageStats false

echo Model loading takes about 15 seconds. Refresh the page if it says API down.

@echo off
setlocal
cd /d "%~dp0"
REM Make sure Ollama is running (user can just open Ollama app too)
REM start "" ollama  >nul 2>&1
call .\.venv\Scripts\activate.bat
set CITL_LLM_BACKEND=ollama
set CITL_OLLAMA_HOST=http://localhost:11434
set CITL_LLM_MODEL=llama3.1:8b
set CITL_FACTBOOK_INDEX=%CD%\data\factbook_index.jsonl
python factbook_assistant_gui.py

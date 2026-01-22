\# GPT-ANCHOR: CITL-COMBINED-GUI-STABLE-2026-01-16



This anchor marks the known-good “combined” GUI (Factbook + Audio Capture/Transcription) used for CITL demos.



\## Known-good launch (Windows)

1\) Open PowerShell in repo root

2\) Activate venv: .\\.venv\\Scripts\\Activate.ps1

3\) Ensure Ollama is serving: ollama serve

4\) Launch: python .\\factbook-assistant\\factbook\_assistant\_gui.py



\## If the wrong/old GUI launches

\- Confirm you are in the correct repo root

\- Confirm the file being executed is: factbook-assistant\\factbook\_assistant\_gui.py

\- Run: python -m py\_compile .\\factbook-assistant\\factbook\_assistant\_gui.py



\## Dependencies

\- Ollama running locally on http://127.0.0.1:11434

\- faster-whisper installed for offline transcription

\- sounddevice installed for device enumeration




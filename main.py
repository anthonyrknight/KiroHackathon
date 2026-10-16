"""Launcher for the Campus Form Assistant.

Run `py main.py` (or `python main.py`) to start the web app, then open
http://127.0.0.1:8123 in your browser.
"""
import uvicorn

if __name__ == "__main__":
    print("Starting Campus Form Assistant on http://127.0.0.1:8123 ...")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8123, reload=False)

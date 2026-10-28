"""
Server Runner for Live SDE-2 Voicebot Engine
Run with: python projects/sde-2-voicebot/run_server.py
"""

import os
import sys
import uvicorn

# Ensure projects/sde-2-voicebot is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.main import app

if __name__ == "__main__":
    print("===========================================================================")
    print(" SDE-2 VOICEBOT: LIVE REAL-TIME BACKEND ENGINE")
    print(" Access Web App: http://localhost:8001")
    print(" Interactive Swagger Docs: http://localhost:8001/docs")
    print("===========================================================================")
    uvicorn.run(app, host="127.0.0.1", port=8001)

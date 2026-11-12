
from pathlib import Path
import subprocess
import sys

PROJECT_DIR = Path(__file__).resolve().parent

if __name__ == "__main__":
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        cwd=PROJECT_DIR,
        check=True,
    )

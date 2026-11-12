# SDE 2 Voicebot Backend

## 1. Project Overview

This project provides the backend foundation for an AI Voicebot application.

It uses FastAPI and runs in mock mode by default. No external API keys or credentials are required.

## 2. Technologies Used

- Python
- FastAPI
- Uvicorn
- Pytest
- HTTPX

## 3. Project Structure

```text
voicebot-SDE2-teamm/
├── pytest.ini
└── projects/
    └── sde-2-voicebot/
        ├── app/
        │   ├── __init__.py
        │   ├── main.py
        │   ├── errors.py
        │   ├── middleware.py
        │   ├── sessions.py
        │   └── repository.py
        ├── tests/
        │   └── test_api.py
        ├── requirements.txt
        ├── run_mock.py
        ├── run_mock.bat
        └── README.md
```

## 4. Installation

From the repository root, create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r projects/sde-2-voicebot/requirements.txt
```

## 5. Run the Backend

From the repository root, start the backend using the cross-platform Python launcher:

```bash
python projects/sde-2-voicebot/run_mock.py
```

Server URL:

http://127.0.0.1:8001

API documentation:

http://127.0.0.1:8001/docs

## 6. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /ready | Readiness check |
| POST | /sessions | Create session |
| GET | /sessions/{session_id} | Get session |
| POST | /sessions/{session_id}/events | Mock session events |

## 7. Session States

- created
- active
- paused
- stopping
- completed
- failed
- expired

## 8. Run Tests

From the repository root, execute:

```bash
python -m pytest -v
```

The root-level pytest configuration is provided in `pytest.ini`.

## 9. Error Handling

Errors use a standard response format containing:

- code
- message_safe_for_user
- retryable
- correlation_id
- details_redacted

## 10. Mock Mode

The application runs without external API credentials.

Session data is stored using an in-memory repository.
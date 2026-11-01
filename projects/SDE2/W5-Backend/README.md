
# SDE 2 Voicebot Backend

## 1. Project Overview

This project provides the backend foundation for a voicebot application.

It uses FastAPI and runs in mock mode by default. No paid API keys or credentials are required.

## 2. Technologies Used

- Python
- FastAPI
- Uvicorn
- Pytest
- HTTPX

## 3. Project Structure

```text
SDE2-Backend-Work/
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
├── run_mock.bat
└── README.md
```

## 4. Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

## 5. Run the Backend

Start the backend in mock mode:

```powershell
.\run_mock.bat
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

Execute:

```powershell
python -m pytest -v
```

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

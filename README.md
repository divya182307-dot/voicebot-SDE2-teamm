# Academia AI Voice Co-Pilot

Week 3 frontend and local HTTP backend.

## Start the backend

From the repository root, install the backend dependencies and start the API:

```bash
python -m pip install -r projects/sde-2-voicebot/requirements.txt
python projects/sde-2-voicebot/run_backend.py
```

The backend listens on `http://127.0.0.1:8001`; its health endpoint is `/health`.

## Start the frontend

In another terminal:

```bash
cd projects/sde-2-voicebot
cp .env.example .env
npm install
npm run dev
```

The frontend uses the HTTP backend outside test mode. The in-memory `MockLiveBackend` is selected only by Vitest.

Expected API endpoints:

- `POST /sessions` — create and start a session
- `POST /sessions/{id}/stop` — stop a session
- `GET /sessions/{id}/events` — Server-Sent Events stream
- `POST /sessions/{id}/events` — publish validated workflow, transcript, or approval events
- `POST /sessions/{id}/approve` — approve the pending action
- `POST /sessions/{id}/reject` — reject the pending action

The local backend keeps sessions and events in memory for development. SSE events include monotonically increasing IDs and replay events after reconnect. The `approve` endpoint emits an execution event only for a pending approval; `reject` never executes the action.

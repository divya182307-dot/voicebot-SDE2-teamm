# voicebot-week1-teamm
AI Voice Co-Pilot - Team Project

## Frontend setup

The frontend uses a real backend outside test mode and the mock backend under Vitest.

Copy `.env.example` to `.env` in `projects/sde-2-voicebot` and set `VITE_API_BASE_URL` to the backend origin.

Expected API endpoints:

- `POST /sessions` — create a session
- `POST /sessions/{id}/stop` — stop a session
- `GET /sessions/{id}/events` — Server-Sent Events stream
- `POST /sessions/{id}/approve` — approve the pending action
- `POST /sessions/{id}/reject` — reject the pending action

SSE messages must contain JSON matching the frontend `SessionEvent` type, with a numeric `id` field. Successful JSON responses may be returned directly or wrapped in `{ "data": ... }`.

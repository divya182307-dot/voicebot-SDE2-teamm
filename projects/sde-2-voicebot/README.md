# Academia AI Voice Co-Pilot

The frontend is a React/Vite app. Live mode uses the FastAPI backend for
sessions, workflow events, approvals, and the server-sent event stream. Demo
mode uses sample transcript data and an in-memory event backend; it does not
need a backend or API credentials.

## Run locally

Install the JavaScript dependencies:

```sh
npm ci
```

In one terminal, start the backend from this directory:

```sh
python -m pip install -r requirements.txt
python run_backend.py
```

The backend listens on `http://127.0.0.1:8001`. In another terminal, start
the frontend and configure its API URL:

```sh
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). To try the app without
the backend, open `http://localhost:5173/?demo=1` or choose **Try demo mode**
in the app.

## Checks

```sh
npm test -- --run
npm run lint
npm run build
```

Install the Playwright Chromium browser once, then run end-to-end, keyboard,
responsive, and axe accessibility checks:

```sh
npx playwright install chromium
npm run test:e2e
```

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for microphone, backend, and
browser-test recovery steps.

## Known limitations

- The local backend stores sessions and events in memory; restarting it clears
  them. It is a development/demo backend, not a production persistence layer.
- Demo mode exercises the workflow and approval UI with local mock events.
  It does not record a real backend session.
- Browser microphone and screen capture require user permission and a secure
  context (localhost is treated as secure by browsers).

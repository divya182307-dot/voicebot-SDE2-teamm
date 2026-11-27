# Troubleshooting

## Microphone permission or device errors

1. Use `localhost` or HTTPS. Browsers block microphone access on most insecure
   origins.
2. Select the intended input in **Microphone Selection**, then choose
   **Request Microphone Permission**.
3. If permission was previously denied, open the browser's site settings,
   allow microphone access, reload the app, and request permission again.
4. Close other apps that may have exclusive access to the microphone. If the
   device list is stale, reconnect the device and reload the page.

The browser may require a user gesture before it allows microphone access. The
app cannot bypass that permission prompt.

## Backend is unavailable or the session request times out

In live mode, check that the backend is running on port `8001`:

```sh
curl http://127.0.0.1:8001/health
```

The response should contain `{"status":"healthy"}`. Start it from this
directory with `python run_backend.py`. If the frontend is on a different
origin or port, check the backend CORS configuration and set
`VITE_API_BASE_URL` before starting Vite. Restart Vite after changing the
environment variable.

When a request times out, the app displays an error and leaves session start
available to retry. Check the backend health endpoint and network tab before
retrying; a timed-out request may have reached the server even if its response
did not reach the browser.
The default request timeout is 10 seconds; set `VITE_API_TIMEOUT_MS` before
starting Vite to use a different duration.

To keep exploring while the backend is down, use **Try demo mode** or navigate
to `/?demo=1`. Demo mode uses sample data and local events and does not issue
session, event, approval, or rejection requests to the backend.

## Live events do not appear

- Confirm that the session started successfully and that the browser's network
  panel shows an open `/sessions/{id}/events` EventSource connection.
- Check that the backend URL is correct and that the browser has not blocked
  the request due to CORS.
- Use **Reconnect** to retry the stream. The backend replays stored events
  after the last received event ID.
- If the backend was restarted, start a new session; the local backend keeps
  its sessions only in memory.

## Playwright browser or end-to-end test errors

Install the required browser from the project directory:

```sh
npx playwright install chromium
```

Then run `npm run test:e2e`. The tests start their own Vite server on port
`4173`; stop any other process already using that port. They use intercepted
backend responses where appropriate, so the FastAPI server is not required.

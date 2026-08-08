"""Minimal local echo server for verifying the notifier MCP pipeline.

- Listens on 127.0.0.1:9999 by default
- POST /echo -> accepts JSON, writes to ./echo.log, returns JSON ack
- GET  /health -> returns {"status": "UP"}
- GET  /recent -> returns the last 50 entries from echo.log (for inspection)

Run: python3 echo_server.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_PATH = Path(os.environ.get("ECHO_LOG", "./echo.log"))
HOST = os.environ.get("ECHO_HOST", "127.0.0.1")
PORT = int(os.environ.get("ECHO_PORT", "9999"))


class EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        # Quiet stderr — we have our own log file
        pass

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "UP", "log": str(LOG_PATH)})
        elif self.path == "/recent":
            if not LOG_PATH.exists():
                self._send_json(200, {"entries": []})
                return
            lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-50:]
            entries = [json.loads(l) for l in lines if l.strip()]
            self._send_json(200, {"entries": entries})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/echo":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw}

        entry = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "remote": self.client_address[0],
            "body": body,
        }
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._send_json(200, {"ok": True, "received": True, "received_at": entry["received_at"]})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), EchoHandler)
    print(f"[echo] listening on http://{HOST}:{PORT}, log -> {LOG_PATH}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[echo] shutting down", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()

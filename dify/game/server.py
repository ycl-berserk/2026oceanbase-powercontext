"""Serve the District 13 RPG and proxy chat to Dify.

The browser never sees the Dify API key. This small server reads it from
../.runtime/install.json (written by tools/setup.py) and forwards
POST /api/chat to Dify's /v1/chat-messages.

Usage (from dify/):
    python3 game/server.py
    python3 game/server.py --port 8123

The server defaults to 127.0.0.1. Binding it to a public interface turns it
into an unauthenticated proxy for the Dify API key; use an SSH tunnel instead.

Environment overrides:
    DIFY_URL        default from .runtime/install.json
    DIFY_API_KEY    default from .runtime/install.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNTIME_PATH = os.path.join(ROOT, ".runtime", "install.json")
MAX_BODY = 64 * 1024


def load_config():
    runtime = {}
    if os.path.exists(RUNTIME_PATH):
        with open(RUNTIME_PATH, encoding="utf-8") as fh:
            runtime = json.load(fh)
    url = (os.environ.get("DIFY_URL") or runtime.get("dify_url") or "http://127.0.0.1:8080").rstrip("/")
    key = os.environ.get("DIFY_API_KEY") or runtime.get("api_key") or ""
    if not key:
        raise SystemExit("no Dify API key: run tools/setup.py or set DIFY_API_KEY")
    return url, key


DIFY_URL, DIFY_KEY = load_config()


def dify_chat(payload):
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required")
    if len(query) > 1000:
        raise ValueError("query is too long")
    conversation_id = payload.get("conversation_id") or ""
    if not isinstance(conversation_id, str):
        raise ValueError("conversation_id must be a string")
    user = str(payload.get("user") or "rpg-player")[:64]

    body = json.dumps({
        "inputs": {},
        "query": query.strip(),
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": user,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(DIFY_URL + "/v1/chat-messages", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + DIFY_KEY)

    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:600]
        print("[dify] HTTP %s: %s" % (err.code, detail), file=sys.stderr)
        raise RuntimeError("Dify returned HTTP %s" % err.code)
    except urllib.error.URLError as err:
        print("[dify] connection failed: %s" % err.reason, file=sys.stderr)
        raise RuntimeError("cannot reach Dify at %s" % DIFY_URL)

    answer = data.get("answer") or ""
    if not isinstance(answer, str) or not answer:
        raise RuntimeError("Dify returned an empty answer")
    return {
        "answer": answer,
        "conversation_id": data.get("conversation_id") or conversation_id,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/health":
            self.send_json(200, {"ok": True, "dify": DIFY_URL})
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self.send_json(413, {"error": "request body too large or empty"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "invalid payload"})
            return
        try:
            result = dify_chat(payload)
        except ValueError as err:
            self.send_json(400, {"error": str(err)})
        except RuntimeError as err:
            self.send_json(502, {"error": str(err)})
        else:
            self.send_json(200, result)

    def log_message(self, fmt, *args):
        sys.stderr.write("[game] %s - %s\n" % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description="District 13 RPG server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("[game] serving %s" % HERE)
    print("[game] Dify: %s" % DIFY_URL)
    print("[game] open http://%s:%d/" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[game] stopped")


if __name__ == "__main__":
    main()

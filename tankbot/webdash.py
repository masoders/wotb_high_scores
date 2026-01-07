import threading
import sqlite3
import html
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from . import config

# Simple in-memory rate limiter (per IP)
# Defaults: 60 requests per 60 seconds per IP
_RATE_LIMIT = 60
_RATE_WINDOW_SEC = 60
_rate_state: dict[str, list[float]] = {}

def _rate_ok(ip: str) -> bool:
    now = time.time()
    bucket = _rate_state.get(ip, [])
    # prune
    bucket = [t for t in bucket if now - t < _RATE_WINDOW_SEC]
    if len(bucket) >= _RATE_LIMIT:
        _rate_state[ip] = bucket
        return False
    bucket.append(now)
    _rate_state[ip] = bucket
    return True

def _token_required() -> bool:
    # Strict mode: if token not set, deny all requests.
    return True

def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not config.DASHBOARD_TOKEN:
        return False

    # Bearer token in header OR ?token= query param
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == config.DASHBOARD_TOKEN:
        return True

    qs = parse_qs(urlparse(handler.path).query)
    if qs.get("token", [""])[0] == config.DASHBOARD_TOKEN:
        return True

    return False

def _db():
    # read-only connection (SQLite URI)
    uri = f"file:{config.DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)

def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
th {{ background: #f6f6f6; text-align: left; }}
code {{ background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }}
a {{ text-decoration: none; }}
</style>
</head><body>
<h1>{html.escape(title)}</h1>
<nav>
<a href="/">Overview</a> | <a href="/tanks">Tanks</a> | <a href="/recent">Recent</a>
</nav>
<hr>
{body}
</body></html>""".encode("utf-8")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not config.DASHBOARD_ENABLED:
            self._send_plain(404, "Not found")
            return

        ip = self.client_address[0] if self.client_address else "unknown"
        if not _rate_ok(ip):
            self._send_plain(429, "Too Many Requests")
            return

        path = urlparse(self.path).path

        # health endpoint (no data leakage) still requires token (strict)
        if _token_required() and not _auth_ok(self):
            self._send_plain(403, "Forbidden")
            return

        if path == "/healthz":
            self._send_plain(200, "ok")
            return

        try:
            if path == "/":
                self._overview()
            elif path == "/tanks":
                self._tanks()
            elif path == "/recent":
                self._recent()
            else:
                self._send_plain(404, "Not found")
        except Exception as e:
            self._send_plain(500, f"Error: {type(e).__name__}: {e}")

    def _overview(self):
        with _db() as con:
            champ = con.execute("""
            SELECT s.id, s.player_name_raw, s.tank_name, s.score, s.created_at
            FROM submissions s
            ORDER BY s.score DESC, s.id ASC
            LIMIT 1
            """).fetchone()
            tanks = con.execute("SELECT COUNT(*) FROM tanks").fetchone()[0]
            subs = con.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]

        body = f"""
<p><b>Tanks:</b> {tanks} &nbsp; <b>Submissions:</b> {subs}</p>
<h2>Global champion</h2>
<p>{('No submissions yet.' if not champ else f"<b>{champ[3]}</b> — {html.escape(champ[1])} ({html.escape(champ[2])}) <code>#{champ[0]}</code> {html.escape(champ[4])}Z")}</p>
"""
        self._send_html(_page("Tank Highscores — Overview", body))

    def _tanks(self):
        with _db() as con:
            rows = con.execute("SELECT name, tier, type FROM tanks ORDER BY tier DESC, type, name").fetchall()
        trs = "".join(f"<tr><td>{html.escape(n)}</td><td>{t}</td><td>{html.escape(tp)}</td></tr>" for n,t,tp in rows)
        body = f"<h2>Tank roster</h2><table><tr><th>Name</th><th>Tier</th><th>Type</th></tr>{trs}</table>"
        self._send_html(_page("Tank Highscores — Tanks", body))

    def _recent(self):
        with _db() as con:
            rows = con.execute("""
            SELECT id, player_name_raw, tank_name, score, created_at
            FROM submissions
            ORDER BY id DESC
            LIMIT 50
            """).fetchall()
        trs = "".join(
            f"<tr><td><code>#{r[0]}</code></td><td>{html.escape(r[1])}</td><td>{html.escape(r[2])}</td><td><b>{r[3]}</b></td><td>{html.escape(r[4])}Z</td></tr>"
            for r in rows
        )
        body = f"<h2>Recent submissions (last 50)</h2><table><tr><th>ID</th><th>Player</th><th>Tank</th><th>Score</th><th>Time</th></tr>{trs}</table>"
        self._send_html(_page("Tank Highscores — Recent", body))

    def _send_html(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def _send_plain(self, code: int, text: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

def start_dashboard():
    if not config.DASHBOARD_ENABLED:
        return None

    if not config.DASHBOARD_TOKEN:
        # Strict: do not start without token set
        # This prevents accidental exposure when someone binds to 0.0.0.0.
        raise RuntimeError("DASHBOARD_TOKEN must be set when DASHBOARD_ENABLED=1 (strict mode).")

    def run():
        server = HTTPServer((config.DASHBOARD_BIND, config.DASHBOARD_PORT), Handler)
        server.serve_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t

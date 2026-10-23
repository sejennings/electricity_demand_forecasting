"""Serve only dashboard assets on loopback; never expose the project directory."""
import argparse
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'dashboard'
ASSETS = {'/', '/index.html', '/style.css', '/app.js', '/demo.json', '/snapshot.json'}


def refresh_snapshot():
    process = subprocess.Popen(
        [sys.executable, '-m', 'scripts.export_dashboard'], cwd=ROOT.parent,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            # Windows venv launchers can have a child interpreter; stop both.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10, check=False)
        process.kill()
        process.communicate(timeout=5)
        raise
    if process.returncode:
        raise RuntimeError('AWS update failed. Check your CLI sign-in and try again.')


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refresh_lock = threading.Lock()
        self.last_refresh = None


class DashboardHandler(SimpleHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != '/api/refresh':
            self.json_response(404, {'error': 'Unknown action'})
            return
        origin = f'http://127.0.0.1:{self.server.server_port}'
        # Browser refreshes must come from this local page, not an unrelated site.
        if (self.headers.get('Origin') != origin or
                self.headers.get('Host') != origin.removeprefix('http://') or
                self.headers.get('X-GridCast-Refresh') != '1' or
                self.headers.get('Content-Length', '0') != '0'):
            self.json_response(403, {'error': 'Refresh must be requested from this dashboard'})
            return
        if not self.server.refresh_lock.acquire(blocking=False):
            self.json_response(429, {'error': 'An AWS update is already running'})
            return
        try:
            if self.server.last_refresh is not None and time.monotonic()-self.server.last_refresh < 60:
                self.json_response(429, {'error': 'Please wait a minute between AWS updates'})
                return
            self.server.last_refresh = time.monotonic()
            refresh_snapshot()
            self.json_response(200, {'ok': True})
        except subprocess.TimeoutExpired:
            self.json_response(504, {'error': 'AWS update timed out. Reload the saved view to check the latest snapshot.'})
        except RuntimeError as error:
            self.json_response(502, {'error': str(error)})
        except OSError:
            self.json_response(500, {'error': 'The local exporter could not start. Check the Python environment.'})
        finally:
            self.server.refresh_lock.release()

    def allowed(self):
        if urlsplit(self.path).path not in ASSETS:
            self.send_error(404)
            return False
        return True

    def do_GET(self):
        if self.allowed():
            super().do_GET()

    def do_HEAD(self):
        if self.allowed():
            super().do_HEAD()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8870)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1–65535')
    handler = partial(DashboardHandler, directory=str(ROOT))
    with DashboardServer(('127.0.0.1', args.port), handler) as server:
        print(f'GridCast dashboard: http://127.0.0.1:{args.port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

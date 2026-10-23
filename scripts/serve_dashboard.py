"""Serve only dashboard assets on loopback; never expose the project directory."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'dashboard'
ASSETS = {'/', '/index.html', '/style.css', '/app.js', '/demo.json', '/snapshot.json'}


class DashboardHandler(SimpleHTTPRequestHandler):
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
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'GridCast dashboard: http://127.0.0.1:{args.port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

"""Loopback fault proxy; an explicit marker makes it reset client connections."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pathlib
import socket

parser = argparse.ArgumentParser()
parser.add_argument("--offline-marker", required=True)
parser.add_argument("--port", type=int, default=41874)
parser.add_argument("--upstream-port", type=int, default=41873)
parser.add_argument("--blocked-route-marker", help="Optional file containing one exact GET path to reject")
args = parser.parse_args()
marker = pathlib.Path(args.offline_marker)

class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        route_marker = pathlib.Path(args.blocked_route_marker) if args.blocked_route_marker else None
        if self.command == 'GET' and route_marker and route_marker.is_file() and self.path == route_marker.read_text().strip():
            self.send_error(503)
            return
        if marker.exists():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        size = int(self.headers.get("content-length", "0"))
        if size > 1 << 20:
            self.send_error(413)
            return
        connection = http.client.HTTPConnection("127.0.0.1", args.upstream_port, timeout=10)
        try:
            connection.request(self.command, self.path, self.rfile.read(size), headers=dict(self.headers))
            reply = connection.getresponse()
            raw = reply.read()
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (OSError, http.client.HTTPException):
            self.send_error(502)
        finally:
            connection.close()
    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", args.port), Proxy).serve_forever()

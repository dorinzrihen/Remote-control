#!/usr/bin/env python3
"""Serve the screenshot folder on localhost with a tiny file-change manifest."""

import argparse
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


class GalleryHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] != '/__gallery_manifest':
            return super().do_GET()
        output = Path(self.directory)
        files = {}
        for path in output.glob('bulbs-*.png'):
            stat = path.stat()
            files[path.name] = f'{stat.st_mtime_ns}-{stat.st_size}'
        index = output / 'index.html'
        html = sha256(index.read_bytes()).hexdigest() if index.is_file() else None
        body = json.dumps({'html': html, 'files': files}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def log_message(self, *_args):
        pass


def create_server(output: Path, port: int = 0):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(GalleryHandler, directory=str(output.resolve())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.local/preview/live'))
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--address-file', type=Path)
    args = parser.parse_args()
    with create_server(args.output, args.port) as server:
        url = f'http://127.0.0.1:{server.server_port}/index.html'
        if args.address_file:
            args.address_file.write_text(url + '\n')
        print(url, flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()

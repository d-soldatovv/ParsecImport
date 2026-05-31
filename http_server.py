from __future__ import annotations

import urllib.parse
from urllib.parse import parse_qs, urlparse
from email.parser import Parser
from functools import lru_cache
import socket
import threading


class Request:
    def __init__(self, method, target, version, headers, rfile):
        self.method = method
        self.target = target
        self.version = version
        self.headers = headers
        self.__body = None
        self.rfile = rfile

    @property
    def path(self):
        return self.url.path

    @property
    @lru_cache(maxsize=None)
    def query(self):
        return self.url.query

    @property
    @lru_cache(maxsize=None)
    def url(self):
        return urlparse(self.target)

    def __read_body(self):
        size = self.headers.get('Content-Length')
        if not size:
            return None
        try:
            size = int(size)
        except Exception:
            return None
        return self.rfile.read(size)

    @property
    def body(self):
        if not self.__body:
            self.__body = self.__read_body()
        return self.__body

    @property
    def body_payload(self):
        result = self.body
        result = result.decode("utf-8").replace("payload=", "")
        result = urllib.parse.unquote(result)
        return result.replace("+", " ")


class Response:
    def __init__(self, status, reason, headers=None, body=None):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body


class HTTPError(Exception):
    def __init__(self, status, reason, body=None):
        super().__init__()
        self.status = status
        self.reason = reason
        self.body = body


class HttpServer:
    MAX_LINE = 64 * 1024
    MAX_HEADERS = 100

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self.__stopped = False
        self.__run_state_mutex = threading.Lock()

    def start(self):
        thr = threading.Thread(target=self.serve)
        thr.start()

    def stop(self):
        with self.__run_state_mutex:
            if not self.__stopped:
                self.__stopped = True

    def serve(self):
        serv_sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
            proto=0)
        serv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serv_sock.setblocking(0)
        serv_sock.settimeout(1)
        try:
            serv_sock.bind((self._host, self._port))
            serv_sock.listen()
            while True:
                with self.__run_state_mutex:
                    if self.__stopped:
                        break
                try:
                    conn, _ = serv_sock.accept()
                    self.serve_client(conn)
                except socket.timeout:
                    pass
                except Exception as e:
                    print('Client serving failed', e)
        finally:
            serv_sock.close()

    def serve_client(self, conn):
        try:
            req = self.parse_request(conn)
            resp = self.handle_request(req)
            self.send_response(conn, resp)
            req.rfile.close()
        except ConnectionResetError:
            conn = None
        except Exception as e:
            self.send_error(conn, e)

        if conn:
            conn.close()

    def parse_request(self, conn):
        rfile = conn.makefile('rb')
        method, target, ver = self.parse_request_line(rfile)
        headers = self.parse_headers(rfile)
        host = headers.get('Host')
        if not host:
            raise HTTPError(400, 'Bad request', 'Host header is missing')
        return Request(method, target, ver, headers, rfile)

    def parse_request_line(self, rfile):
        raw = rfile.readline(HttpServer.MAX_LINE + 1)
        if len(raw) > HttpServer.MAX_LINE:
            raise HTTPError(400, 'Bad request', 'Request line is too long')

        req_line = str(raw, 'iso-8859-1')
        words = req_line.split()
        if len(words) != 3:
            raise HTTPError(400, 'Bad request', 'Malformed request line')

        method, target, ver = words
        if ver != 'HTTP/1.1':
            raise HTTPError(505, 'HTTP Version Not Supported')
        return method, target, ver

    def parse_headers(self, rfile):
        headers = []
        while True:
            line = rfile.readline(HttpServer.MAX_LINE + 1)
            if len(line) > HttpServer.MAX_LINE:
                raise HTTPError(494, 'Request header too large')

            if line in (b'\r\n', b'\n', b''):
                break

            headers.append(line)
            if len(headers) > HttpServer.MAX_HEADERS:
                raise HTTPError(494, 'Too many headers')

        sheaders = b''.join(headers).decode('iso-8859-1')
        return Parser().parsestr(sheaders)

    def handle_request(self, req: Request):
        print(f"method:{req.method}\npath:{req.path}\nparams:{req.query}\nbody:{req.body if req.body else '' }")
        return Response(200, "OK")

    def send_response(self, conn, resp):
        wfile = conn.makefile('wb')
        status_line = f'HTTP/1.1 {resp.status} {resp.reason}\r\n'
        wfile.write(status_line.encode('iso-8859-1'))

        if resp.headers:
            for (key, value) in resp.headers:
                header_line = f'{key}: {value}\r\n'
                wfile.write(header_line.encode('iso-8859-1'))

        wfile.write(b'\r\n')

        if resp.body:
            wfile.write(resp.body)

        wfile.flush()
        wfile.close()

    def send_error(self, conn, err):
        try:
            status = err.status
            reason = err.reason
            body = (err.body or err.reason).encode('utf-8')
        except Exception:
            status = 500
            reason = b'Internal Server Error'
            body = b'Internal Server Error'
        resp = Response(status, reason, [('Content-Length', len(body))], body)
        self.send_response(conn, resp)

    @property
    def ip_addr(self):
        return f"{self._host}:{self._port}"

    @property
    def addr(self):
        return f"http://{self._host}:{self._port}"
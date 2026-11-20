#!/usr/bin/env python3
"""Receive PrusaSlicer uploads and add them to Print Queue."""

import argparse
import cgi
import json
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


QUEUE_API = "/api/v1/modules/com.github.aux.tbetton.print-queue"
MAX_UPLOAD_BYTES = 4 * 1024**3
GCODE_SUFFIXES = {".gcode", ".bgcode"}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, token, method, expected, body=None, content_type=None, size=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        headers.update({"Content-Type": content_type, "Content-Length": str(size)})
    request = Request(url, data=body, method=method, headers=headers)
    try:
        with build_opener(NoRedirects()).open(request, timeout=120) as response:
            if response.status not in expected:
                raise RuntimeError(f"Unexpected HTTP {response.status}")
            result = json.load(response)
    except HTTPError as error:
        with error:
            try:
                problem = json.loads(error.read(8192))
            except (ValueError, OSError):
                problem = None
        code = problem.get("code") if isinstance(problem, dict) else None
        message = f"HTTP {error.code} ({code})" if isinstance(code, str) else f"HTTP {error.code}"
        raise RuntimeError(message) from error
    except URLError as error:
        raise RuntimeError(str(error.reason)) from error

    if not isinstance(result, dict):
        raise RuntimeError("Unexpected JSON response")
    return result


def normalize_folder(folder):
    folder = folder.strip("/")
    if (folder and any(part in {"", ".", ".."} for part in folder.split("/"))
            or "\\" in folder or any(ord(character) < 32 for character in folder)):
        raise ValueError("Use a folder path relative to the Connect Local storage.")
    return folder


def upload_folder(args, token):
    if args.folder is not None:
        query = urlencode({"device": args.printer})
        request_json(f"{args.server}{QUEUE_API}/jobs?{query}", token, "GET", {200})
        return args.folder

    printer = quote(args.printer, safe="")
    url = f"{args.server}{QUEUE_API}/devices/{printer}/slicer-upload"
    settings = request_json(url, token, "GET", {200})
    folder = settings.get("folder")
    if not isinstance(folder, str):
        raise RuntimeError("Print Queue did not return its upload folder.")
    return normalize_folder(folder)


def enqueue(args, token, folder, gcode, name):
    extension = PurePosixPath(name).suffix.lower()
    if extension not in GCODE_SUFFIXES:
        raise ValueError("Select a .gcode or .bgcode file.")
    gcode.seek(0, os.SEEK_END)
    size = gcode.tell()
    gcode.seek(0)
    if size == 0 or (gcode.read(4) == b"GCDE") != (extension == ".bgcode"):
        raise ValueError("The file is empty or its format does not match its extension.")
    gcode.seek(0)

    # Queued jobs keep their own file, including when a later upload has the same name.
    filename = f"{uuid4().hex[:12]}-{name}"
    remote_path = f"{folder}/{filename}" if folder else filename
    query = urlencode({"path": remote_path})
    upload_url = f"{args.server}/api/v1/storages/{quote(args.storage, safe='')}/content?{query}"
    try:
        upload = request_json(
            upload_url, token, "PUT", {200, 201}, gcode, "application/octet-stream", size,
        )
        uploaded_path = upload.get("path")
        if not isinstance(uploaded_path, str) or not uploaded_path:
            raise RuntimeError("The server did not return the stored file path.")
    except (OSError, ValueError, RuntimeError) as error:
        raise RuntimeError(f"Could not confirm upload of {remote_path}: {error}") from error

    body = json.dumps({
        "device_id": args.printer,
        "storage": args.storage,
        "path": uploaded_path,
        "name": name,
    }).encode("utf-8")
    try:
        job = request_json(
            f"{args.server}{QUEUE_API}/jobs", token, "POST", {201}, body, "application/json", len(body),
        )
        if not isinstance(job.get("id"), str) or not job["id"]:
            raise RuntimeError("The server did not return a queue job ID.")
    except (OSError, ValueError, RuntimeError) as error:
        raise RuntimeError(
            f"Could not confirm the queue job: {error}. "
            f"The file is in storage at {args.storage}/{uploaded_path}. "
            "Check Print Queue before adding it again."
        ) from error

    return job["id"]


class UploadServer(ThreadingHTTPServer):
    def __init__(self, options, tls):
        self.options = options
        self.tls = tls
        super().__init__((str(options.listen), options.port), UploadHandler)
        self.upload_host = f"{options.listen}:{self.server_port}"

    def get_request(self):
        client, address = super().get_request()
        if self.tls:
            client = self.tls.wrap_socket(client, server_side=True, do_handshake_on_connect=False)
        return client, address


class UploadHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(120)
        super().setup()

    def reply(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def token_for(self, path):
        if self.path != path:
            self.reply(404, {"error": "Unknown Print Queue route."})
            return None
        if self.headers.get("Host") != self.server.upload_host:
            self.reply(403, {"error": "Use the configured address of this upload destination."})
            return None
        token = self.headers.get("X-Api-Key", "").strip()
        if not token or any(character.isspace() for character in token):
            self.reply(401, {"error": "Set your Connect Local API credential as the API key."})
            return None
        return token

    def do_GET(self):
        token = self.token_for("/api/version")
        if token is None:
            return
        args = self.server.options
        try:
            upload_folder(args, token)
        except (OSError, ValueError, RuntimeError) as error:
            self.reply(502, {"error": f"Could not access this printer's Print Queue: {error}"})
            return
        self.reply(200, {"api": "0.1", "text": "OctoPrint compatible (Print Queue)"})

    def do_POST(self):
        token = self.token_for("/api/files/local")
        if token is None:
            return
        if self.headers.get_content_type() != "multipart/form-data":
            self.reply(415, {"error": "Expected a PrusaSlicer multipart upload."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= MAX_UPLOAD_BYTES:
            self.reply(413, {"error": "Provide an upload length between 1 byte and 4 GiB."})
            return

        try:
            folder = upload_folder(self.server.options, token)
        except (OSError, ValueError, RuntimeError) as error:
            self.reply(502, {"error": f"Could not access this printer's Print Queue: {error}"})
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"},
                limit=size,
            )
            try:
                job_id = self.enqueue_form(form, token, folder)
            finally:
                for field in form.list or []:
                    if field.file is not None:
                        field.file.close()
        except (OSError, ValueError) as error:
            self.reply(400, {"error": str(error)})
            return
        except RuntimeError as error:
            self.reply(502, {"error": str(error)})
            return
        self.reply(201, {"done": True, "job_id": job_id})

    def enqueue_form(self, form, token, folder):
        if form.getfirst("print", "false").lower() != "false":
            raise ValueError("Choose Upload to add the file to Print Queue.")
        upload = form["file"] if "file" in form else None
        if (not isinstance(upload, cgi.FieldStorage) or upload.file is None
                or not upload.filename or upload.done < 0):
            raise ValueError("Provide one complete G-code file.")
        name = PurePosixPath(upload.filename.replace("\\", "/")).name
        if not name or any(ord(character) < 32 for character in name):
            raise ValueError("Invalid G-code filename.")
        return enqueue(self.server.options, token, folder, upload.file, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="Prusa Connect Local base URL")
    parser.add_argument("--printer", required=True, help="Connect Local printer ID")
    parser.add_argument("--storage", default="local", help="Connect Local storage ID")
    parser.add_argument("--folder", help="override the upload folder set in Print Queue")
    parser.add_argument("--listen", type=IPv4Address, default="127.0.0.1", help="upload address")
    parser.add_argument("--port", type=int, default=17891, help="upload port")
    parser.add_argument("--tls-cert", type=Path, help="PEM certificate for the upload address")
    parser.add_argument("--tls-key", type=Path, help="PEM key for the TLS certificate")
    args = parser.parse_args()

    args.server = args.server.rstrip("/")
    url = urlsplit(args.server)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username is not None or url.query or url.fragment):
        parser.error("Use the HTTP(S) address of your Prusa Connect Local server.")
    if args.folder is not None:
        try:
            args.folder = normalize_folder(args.folder)
        except ValueError as error:
            parser.error(str(error))
    if not 1 <= args.port <= 65535:
        parser.error("Use a port between 1 and 65535.")
    if args.listen.is_unspecified or args.listen.is_multicast:
        parser.error("Use a specific unicast listening address.")
    if bool(args.tls_cert) != bool(args.tls_key) or (not args.listen.is_loopback and not args.tls_cert):
        parser.error("Configure both --tls-cert and --tls-key for HTTPS outside loopback.")

    try:
        tls = None
        if args.tls_cert:
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(args.tls_cert, args.tls_key)
        with UploadServer(args, tls) as server:
            scheme = "https" if tls else "http"
            print(f"Print Queue destination: {scheme}://{server.upload_host}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        print(f"Print Queue: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

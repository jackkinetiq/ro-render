"""Local HTTP bridge. Requests are queued and run on Blender's main thread."""

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 28082

_lock = threading.Lock()
_jobs: dict = {}
_queue: list = []
_meshes: dict = {}
_textures: dict = {}
_session = None
_httpd: ThreadingHTTPServer | None = None


def is_running() -> bool:
    return _httpd is not None


def pump():
    job = None
    with _lock:
        if _queue:
            job = _queue.pop(0)
    if job is not None:
        try:
            from .scene import run

            with _lock:
                meshes = dict(_meshes)
                textures = dict(_textures)
            job["result"] = run(job["kind"], job["payload"], meshes, textures)
            job["status"] = "done"
        except Exception as exc:
            traceback.print_exc()
            message = str(exc).strip().splitlines()
            job["error"] = message[-1] if message else "Render failed."
            job["status"] = "error"
        job["event"].set()
    return 0.05


def _remember_session(session):
    global _session
    if session != _session:
        _meshes.clear()
        _textures.clear()
        _session = session


def _trim_jobs():
    if len(_jobs) <= 32:
        return
    finished = [job_id for job_id, job in _jobs.items() if job["event"].is_set()]
    for job_id in finished[:-16]:
        _jobs.pop(job_id, None)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[ro-render]", fmt % args)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            from .version import ADDON_VERSION

            self._send(200, {"ok": True, "version": ADDON_VERSION})
            return
        if path.startswith("/jobs/"):
            job_id = path[len("/jobs/") :]
            with _lock:
                job = _jobs.get(job_id)
            if job is None:
                self._send(404, {"ok": False, "error": "Unknown render job."})
                return
            if job["status"] == "done":
                result = job.get("result") or {}
                self._send(200, {"ok": True, "status": "done", "path": result.get("path"), "warnings": result.get("warnings") or []})
                return
            if job["status"] == "error":
                self._send(200, {"ok": True, "status": "error", "error": job.get("error") or "Render failed."})
                return
            self._send(200, {"ok": True, "status": "running"})
            return
        self._send(404, {"ok": False, "error": "Unknown request."})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read_json()
        except Exception as exc:
            self._send(400, {"ok": False, "error": str(exc)})
            return
        if path in ("/mesh", "/texture"):
            with _lock:
                _remember_session(payload.get("session"))
                if path == "/mesh":
                    _meshes[payload.get("meshRef")] = payload
                else:
                    _textures[payload.get("textureRef")] = payload
            self._send(200, {"ok": True})
            return
        if path not in ("/preview", "/render"):
            self._send(404, {"ok": False, "error": "Unknown request."})
            return
        job_id = __import__("uuid").uuid4().hex
        job = {
            "id": job_id,
            "kind": "preview" if path == "/preview" else "render",
            "payload": payload,
            "event": threading.Event(),
            "status": "running",
            "result": None,
            "error": None,
        }
        with _lock:
            _jobs[job_id] = job
            _queue.append(job)
            _trim_jobs()
        if path == "/render":
            self._send(200, {"ok": True, "jobId": job_id})
            return
        if not job["event"].wait(180):
            self._send(500, {"ok": False, "error": "Preview timed out."})
            return
        if job["status"] == "error":
            self._send(500, {"ok": False, "error": job.get("error") or "Preview failed."})
            return
        import base64

        result = job.get("result") or {}
        rgba = result.get("rgba") or b""
        job["result"] = None
        self._send(
            200,
            {
                "ok": True,
                "width": result.get("width"),
                "height": result.get("height"),
                "rgbaBase64": base64.b64encode(rgba).decode("ascii"),
                "warnings": result.get("warnings") or [],
            },
        )


def start():
    global _httpd
    if _httpd is not None:
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    except OSError as exc:
        raise RuntimeError(f"Port {PORT} is already in use.") from exc
    thread = threading.Thread(target=server.serve_forever, name="ro-render", daemon=True)
    thread.start()
    _httpd = server


def stop():
    global _httpd
    server = _httpd
    _httpd = None
    if server is not None:
        server.shutdown()
        server.server_close()

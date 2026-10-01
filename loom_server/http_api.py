"""The small web server for Glitch Loom. It answers only to this computer."""
from __future__ import annotations

import http.server
import json
import posixpath
import re
import signal
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import VERSION, engine, storage

MAX_BODY = 64 * 1024 * 1024  # a whole backup must fit: the course, its generation record and up to 24 MB of history
PUBLIC = re.compile(r"^/(index\.html|styles\.css|README\.md|ISSUES\.md|SPEC\.md|favicon\.ico|js/[A-Za-z0-9_./-]+\.js)$")
STARTED = datetime.now().astimezone().isoformat(timespec="seconds")


def build_id() -> str:
    """A short fingerprint of the files that make up this build, so a tester can say exactly what was tested."""
    import hashlib
    h = hashlib.sha1()
    for f in sorted([storage.ROOT / "index.html", storage.ROOT / "styles.css", *(storage.ROOT / "js").glob("*.js"), *(storage.ROOT / "loom_server").glob("*.py")]):
        h.update(f.name.encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


BUILD = build_id()
ENGINE_ACTIONS = ("begin", "revise_outline", "approve_outline", "resume", "retry_session", "retry_project", "verify_evidence", "read_identity", "read_lineage", "resolve_endpoints", "attribution_review", "review_outline", "review", "edit", "ideas")


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "GlitchLoom/" + VERSION
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(storage.ROOT), **kw)

    def log_message(self, fmt, *args):  # quieter log, no query strings with course text
        first = args[0] if args and isinstance(args[0], str) else ""
        try:
            line = fmt % args
        except (TypeError, ValueError):
            line = str(fmt)
        if "/api/" not in first or " 4" in line or " 5" in line:
            super().log_message(fmt, *args)

    def end_headers(self):
        # One request for each connection. Anything left unread on the line is dropped with it and can never run as a second request.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    # ---- safety
    def allowed(self, writing: bool) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if (self.headers.get("Host") or "").lower() not in hosts:
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {"http://" + h for h in hosts}:
            return False
        return not writing or self.headers.get("X-Loom") == "1"

    def send_json(self, obj, status=200, download: str | None = None):
        body = json.dumps(obj, ensure_ascii=False, indent=1 if download else None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, message, **extra):
        self.send_json({"error": message, **extra}, status)

    def body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise storage.StoreError("Loom could not read what was sent.")
        if n < 0 or n > MAX_BODY:
            raise storage.StoreError("That is too large to save.")
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:
            raise storage.StoreError("Only part of the message arrived. Nothing was saved.")
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise storage.StoreError("Loom could not read what was sent.")
        if not isinstance(data, dict):
            raise storage.StoreError("Loom could not read what was sent.")
        return data

    # ---- routing
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path.startswith("/api/"):
            return self.api("GET", url)
        if not self.allowed(False):
            return self.fail(403, "Loom only answers to its own page on this computer.")
        path = posixpath.normpath(urllib.parse.unquote(url.path))
        if path in ("/", "."):
            path = "/index.html"
        if not PUBLIC.match(path) or ".." in path:
            self.send_error(404, "Not found")
            return
        self.path = path
        super().do_GET()

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.api("POST", urllib.parse.urlsplit(self.path))

    def do_PUT(self):
        self.api("PUT", urllib.parse.urlsplit(self.path))

    def api(self, method, url):
        writing = method != "GET"
        if not self.allowed(writing):
            return self.fail(403, "Loom only answers to its own page on this computer.")
        q = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        # A storage name that is misspelt or repeated is refused. It must never fall through to the real library.
        if any(k != "store" and "store" in k.lower() for k in q) or len(q.get("store", [])) > 1:
            return self.fail(400, "Loom could not read the storage name in that address.")
        store = q["store"][0] if "store" in q else None
        parts = [p for p in url.path.split("/") if p][1:]
        try:
            self.route(method, parts, q, store)
        except storage.Conflict as e:
            self.fail(409, str(e), currentVersion=e.current)
        except storage.StoreError as e:
            self.fail(e.status, str(e))
        except Exception as e:  # noqa: BLE001
            self.fail(500, f"Loom's server hit a problem: {type(e).__name__}: {e}")

    def route(self, method, parts, q, store):
        if parts == ["health"] and method == "GET":
            return self.send_json({"ok": True, "version": VERSION, "build": BUILD, "startedAt": STARTED, "filesChangedSinceStart": build_id() != BUILD, "store": storage.store_name(store), "testStorage": store is not None})
        if parts == ["engine"] and method == "GET":
            return self.send_json(engine.status(force="fresh" in q))
        if parts == ["library"] and method == "GET":
            return self.send_json(storage.list_courses(store))
        if parts == ["library", "current"] and method == "POST":
            storage.set_current(store, str(self.body().get("id")))
            return self.send_json({"ok": True})
        if parts == ["courses"] and method == "POST":
            b = self.body()
            raw = b.get("raw")
            if raw is not None and not isinstance(raw, str):
                raise storage.StoreError("Loom could not read what was sent.")
            return self.send_json(storage.create_course(store, raw, b.get("name"), b.get("summary"), b.get("note"), named=b.get("named") is True))
        if parts == ["restore"] and method == "POST":
            return self.send_json(storage.restore(store, self.body()))
        if parts == ["imports"] and method == "POST":
            b = self.body()
            if not isinstance(b.get("reasons") or [], list) or not isinstance(b.get("courseId") or "", str):
                raise storage.StoreError("Loom could not read what was sent.")
            return self.send_json(storage.save_import(store, b.get("origin", ""), b.get("key", ""), b.get("raw"), b.get("status", "damaged"), b.get("reasons") or [], b.get("courseId")))
        if parts == ["imports", "find"] and method == "POST":
            b = self.body()
            return self.send_json(storage.find_import(store, b.get("origin", ""), b.get("raw") or "") or {"hash": None})
        if len(parts) == 2 and parts[0] == "imports" and method == "GET":
            rec = storage.get_import(store, parts[1])
            return self.send_json({"raw": rec["raw"], "origin": rec.get("origin"), "importedAt": rec.get("importedAt"), "status": rec.get("status")}, download=f"glitch-loom-browser-copy-{parts[1][:8]}.json")
        if len(parts) >= 2 and parts[0] == "courses":
            cid, rest = parts[1], parts[2:]
            if not rest and method == "GET":
                return self.send_json(storage.get_course(store, cid))
            if not rest and method == "PUT":
                b = self.body()
                text = b.get("raw")
                if not isinstance(text, str):
                    raise storage.StoreError("Loom could not read what was sent.")
                return self.send_json(storage.put_course(store, cid, text, b.get("baseVersion", -1), b.get("name"), b.get("summary"), b.get("reason")))
            if rest == ["name"] and method == "POST":
                return self.send_json(storage.rename_course(store, cid, self.body().get("name")))
            if rest == ["archive"] and method == "POST":
                return self.send_json(storage.archive_course(store, cid, self.body().get("archived")))
            if rest == ["duplicate"] and method == "POST":
                return self.send_json(storage.duplicate_course(store, cid, self.body().get("name")))
            if rest == ["prepared"] and method == "POST":
                return self.send_json({"prepared": engine.register_prepared(store, cid, self.body().get("items"))})
            if rest == ["exports"] and method == "POST":
                b = self.body()
                return self.send_json(storage.save_export(store, cid, b.get("name"), b.get("text"), b.get("ver"), b.get("kind")))
            if rest == ["exports"] and method == "GET":
                return self.send_json({"exports": storage.list_exports(store, cid)})
            if rest == ["history"] and method == "GET":
                return self.send_json({"history": storage.history(store, cid)})
            if rest == ["backup"] and method == "GET":
                bundle = storage.backup(store, cid)
                name = re.sub(r"[^A-Za-z0-9]+", "-", bundle["course"]["meta"].get("name", "course")).strip("-")[:40] or "course"
                return self.send_json(bundle, download=f"glitch-loom-backup-{name}-{datetime.now().strftime('%Y-%m-%d-%H%M')}.json")
            if rest == ["engine"] and method == "GET":
                storage.course_dir(store, cid)
                rec_ = engine.read(store, cid)
                if isinstance(rec_, dict):
                    # Judgements as they now stand — decisions applied, open questions named, history
                    # attached — computed for readers and never written over the raw record.
                    rs_ = ((rec_.get("stages") or {}).get("research") or {})
                    eff = {k: engine.effective_attribution(rs_, k, store, cid)
                           for k in (rs_.get("attribution") or {})}
                    if eff:
                        rec_ = dict(rec_, effectiveAttribution={k: v for k, v in eff.items() if v})
                if rec_ is not None and rec_.get("prepared"):
                    # The real bytes travel with the record so an export can deliver the original itself.
                    rec_ = dict(rec_, prepared=engine.prepared_manifest(store, cid, rec_))
                return self.send_json({"record": rec_, "busy": engine.runner(store, cid).busy()})
            if rest == ["ideas"] and method == "GET":
                return self.send_json({"ideas": storage.read_ideas(store, cid), "busy": engine.runner(store, cid).busy()})
            if rest == ["engine"] and method == "POST":
                b = self.body()
                action = b.get("action")
                if action not in ENGINE_ACTIONS:
                    raise storage.StoreError("Loom does not know that action.")
                storage.course_dir(store, cid)
                # Work for Claude is tied to the saved course. A page whose save failed, or that is behind another window, may not start any.
                at = b.get("courseVersion")
                now = storage.get_course(store, cid)["meta"].get("version", 0)
                if isinstance(at, bool) or not isinstance(at, int):
                    raise storage.StoreError("The request did not say which saved version of the course it belongs to.")
                if at != now:
                    raise storage.Conflict("This course was changed in another window, or the last save did not arrive. Nothing was started.", now)
                st = engine.status()
                if not st["ready"]:
                    raise storage.StoreError(st["blocker"] or "The Claude tool is not ready.")
                if action == "begin" and not (isinstance(b.get("brief"), dict) and isinstance(b.get("plan"), dict) and isinstance(b["plan"].get("minutes"), list) and b["plan"].get("sessions") == len(b["plan"]["minutes"]) and b["plan"]["sessions"] >= 1):
                    raise storage.StoreError("The brief or its time plan is missing.")
                if action == "edit" and not (isinstance(b.get("parts"), list) and b["parts"] and b.get("scope") in ("activity", "session", "journey") and str(b.get("instruction") or "").strip() and re.match(r"^[a-z0-9]{4,40}$", str(b.get("editId") or ""))):
                    raise storage.StoreError("The change request is incomplete.")
                rec = engine.runner(store, cid).start(action, b)
                return self.send_json({"record": rec, "busy": True})
            if rest == ["attribution-resolution"] and method == "POST":
                # Deliberately NOT under the engine route: that one refuses when the Claude tool is not ready,
                # and a person deciding between two answers the review already gave needs no model at all.
                b = self.body()
                storage.course_dir(store, cid)
                got = engine.record_resolution(store, cid, str(b.get("claimKey") or ""),
                                               str(b.get("disagreement") or ""), b if isinstance(b, dict) else {})
                return self.send_json({"decision": got})
            if rest == ["engine", "stop"] and method == "POST":
                engine.runner(store, cid).halt()
                return self.send_json({"ok": True})
        raise storage.NotFound("Loom's server does not know that address.")


def serve(port: int):
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    http.server.ThreadingHTTPServer.daemon_threads = True
    left = engine.stop_leftovers()
    if left:
        print(f"Stopped {left} request to Claude left running by an earlier server.", flush=True)

    def leave(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, leave)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"Glitch Loom {VERSION} is running at http://127.0.0.1:{port}", flush=True)
        print(f"Courses are kept in {storage.data_root()}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            n = engine.stop_requests()
            print("Glitch Loom has stopped." + (f" {n} unfinished request to Claude was stopped. Finished parts are saved." if n else ""), flush=True)

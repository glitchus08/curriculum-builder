"""Checks for the local web server: what it serves, and who it answers to.

Run: python3 -m unittest discover -s tests/server -t .
"""
import http.client
import http.server
import json
import os
import tempfile
import threading
import unittest

os.environ.setdefault("LOOM_DATA_DIR", tempfile.mkdtemp(prefix="loom-test-"))

from loom_server import http_api  # noqa: E402

STATE = json.dumps({"v": 1, "answers": {}, "at": "topic"})


class Quiet(http_api.Handler):
    lines = []

    def log_message(self, fmt, *args):  # run the real filter, keep the terminal clean
        keep = http.server.SimpleHTTPRequestHandler.log_message
        http.server.SimpleHTTPRequestHandler.log_message = lambda s, f, *a: Quiet.lines.append(f % a)
        try:
            super().log_message(fmt, *args)
        finally:
            http.server.SimpleHTTPRequestHandler.log_message = keep


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def ask(self, method, path, body=None, host=None, origin=None, loom=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin:
            headers["Origin"] = origin
        if method != "GET" and loom:
            headers["X-Loom"] = "1"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            c.request(method, path, body=data, headers=headers)
            r = c.getresponse()
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
        finally:
            c.close()

    def test_the_page_and_its_scripts_are_served_and_nothing_else(self):
        for path in ["/", "/index.html", "/styles.css", "/js/app.js", "/SPEC.md"]:
            self.assertEqual(self.ask("GET", path)[0], 200, path)
        hidden = ["/serve.py", "/loom_server/engine.py", "/loom_server/prompts.py", "/tests/fake_claude.py", "/data/library/library.json",
                  "/loom.config.json", "/start.command", "/js/../serve.py", "/js/%2e%2e/serve.py", "/js/..%2fserve.py", "//serve.py",
                  "/js/../data/library/library.json", "/.git/config", "/js/"]
        for path in hidden:
            self.assertEqual(self.ask("GET", path)[0], 404, path)

    def test_a_missing_file_is_answered_not_dropped(self):
        status, _ = self.ask("GET", "/favicon.ico")
        self.assertEqual(status, 404)
        self.assertEqual(self.ask("GET", "/api/health")[0], 200)

    def test_it_answers_only_to_its_own_page(self):
        me = f"http://127.0.0.1:{self.port}"
        self.assertEqual(self.ask("GET", "/api/health")[0], 200)
        self.assertEqual(self.ask("GET", "/api/health", host=f"localhost:{self.port}")[0], 200)
        self.assertEqual(self.ask("GET", "/api/health", origin=me)[0], 200)
        for host in ["evil.example", f"evil.example:{self.port}", "127.0.0.1", f"127.0.0.1.evil.example:{self.port}"]:
            self.assertEqual(self.ask("GET", "/api/library", host=host)[0], 403, host)
        for origin in ["http://evil.example", "null", f"https://127.0.0.1:{self.port}", f"http://127.0.0.1:{self.port + 1}"]:
            self.assertEqual(self.ask("GET", "/api/library", origin=origin)[0], 403, origin)
            self.assertEqual(self.ask("POST", "/api/courses?store=http", {"raw": STATE}, origin=origin)[0], 403, origin)
        self.assertEqual(self.ask("POST", "/api/courses?store=http", {"raw": STATE}, loom=False)[0], 403)
        self.assertEqual(self.ask("PUT", "/api/courses/cabcdef123?store=http", {"raw": STATE}, loom=False)[0], 403)

    def test_a_refused_message_cannot_carry_a_second_request(self):
        import socket
        inner = json.dumps({"raw": STATE, "name": "SMUGGLED"})
        second = f"POST /api/courses HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-Loom: 1\r\nContent-Type: application/json\r\nContent-Length: {len(inner)}\r\nConnection: close\r\n\r\n{inner}"
        outers = [f"POST /api/courses HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://evil.example\r\nContent-Type: text/plain\r\nContent-Length: {len(second)}\r\n\r\n",
                  f"POST /api/courses HTTP/1.1\r\nHost: evil.example\r\nX-Loom: 1\r\nContent-Length: {len(second)}\r\n\r\n",
                  f"POST /api/courses HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: {len(second)}\r\n\r\n",
                  f"GET /nothing-here HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: {len(second)}\r\n\r\n",
                  f"GET /api/nothing HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: {len(second)}\r\n\r\n",
                  f"DELETE /api/courses HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: {len(second)}\r\n\r\n"]
        for outer in outers:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
            try:
                s.sendall((outer + second).encode("utf-8"))
                got = b""
                while True:
                    try:
                        chunk = s.recv(65536)
                    except (ConnectionResetError, socket.timeout):
                        break
                    if not chunk:
                        break
                    got += chunk
            finally:
                s.close()
            self.assertEqual(got.count(b"HTTP/1."), 1, outer[:60])
            self.assertNotIn(b"SMUGGLED", got, outer[:60])
        names = [c["name"] for c in self.ask("GET", "/api/library")[1]["courses"]]
        self.assertNotIn("SMUGGLED", names)

    def test_a_foreign_host_gets_nothing_at_all(self):
        for path in ["/", "/README.md", "/js/api.js", "/SPEC.md"]:
            self.assertEqual(self.ask("GET", path, host="evil.example")[0], 403, path)
            self.assertEqual(self.ask("GET", path, origin="http://evil.example")[0], 403, path)

    def test_a_misspelt_storage_name_is_refused(self):
        before = len(self.ask("GET", "/api/library")[1]["courses"])
        for query in ["?store[]=x", "?Store=x", "?STORE=x", "?store%20=x", "?%20store=x", "?store=a&store=b", "?store=a&Store=b", "?teststore=x", "?store_name=x"]:
            self.assertEqual(self.ask("POST", "/api/courses" + query, {"raw": STATE, "name": "Wrong place"})[0], 400, query)
            self.assertEqual(self.ask("GET", "/api/library" + query)[0], 400, query)
        self.assertEqual(len(self.ask("GET", "/api/library")[1]["courses"]), before)

    def test_a_save_with_a_wrong_kind_of_value_changes_nothing(self):
        _, made = self.ask("POST", "/api/courses?store=http-e", {"raw": STATE, "name": "Types"})
        url = f"/api/courses/{made['id']}?store=http-e"
        newer = json.dumps({"v": 1, "answers": {"topic": {"value": "window B"}}, "at": "topic"})
        for bad in [{"name": 2026}, {"name": ["x"]}, {"summary": "s"}, {"reason": 1}, {"baseVersion": "1"}, {"baseVersion": None}, {"baseVersion": 1.5}]:
            status, body = self.ask("PUT", url, {"raw": newer, "baseVersion": 1, **bad})
            self.assertEqual(status, 400, bad)
            got = self.ask("GET", url)[1]
            self.assertEqual((got["raw"], got["meta"]["version"]), (STATE, 1), bad)
        for text in ["NaN", "Infinity", '{"a": NaN}', "5", "[]"]:
            self.assertEqual(self.ask("PUT", url, {"raw": text, "baseVersion": 1})[0], 400, text)
        for body in [[1, 2], "text", 5, None]:
            self.assertEqual(self.ask("PUT", url, body)[0], 400, str(body))
        self.assertEqual(self.ask("POST", "/api/restore?store=http-e", {"kind": "glitch-loom-backup", "course": {"raw": STATE}, "history": 5})[0], 200)
        for name in [5, "", "   ", None, ["x"]]:
            self.assertEqual(self.ask("POST", f"/api/courses/{made['id']}/name?store=http-e", {"name": name})[0], 400, str(name))
        self.assertEqual(self.ask("GET", url)[1]["meta"]["name"], "Types")

    def test_a_kept_export_needs_the_page_header_stays_in_its_store_and_reports_what_was_kept(self):
        _, made = self.ask("POST", "/api/courses?store=http-x", {"raw": STATE, "name": "Exports"})
        url = f"/api/courses/{made['id']}/exports?store=http-x"
        self.assertEqual(self.ask("POST", url, {"name": "a.json", "text": "{}", "ver": 1}, loom=False)[0], 403)
        status, kept = self.ask("POST", url, {"name": "a.json", "text": '{"k": 1}', "ver": 1, "kind": "structured"})
        self.assertEqual((status, kept["name"], kept["bytes"]), (200, "a.json", 8))
        self.assertEqual(len(kept["sha256"]), 64)
        self.assertEqual([e["name"] for e in self.ask("GET", url)[1]["exports"]], ["a.json"])
        self.assertEqual(self.ask("GET", f"/api/courses/{made['id']}/exports?store=http-y")[0], 404, "another store does not see it")
        self.assertEqual(self.ask("POST", url, {"name": "../x.json", "text": "{}"})[0], 400)
        self.assertEqual(self.ask("POST", url, {"name": "b.json", "text": ""})[0], 400)

    def test_a_store_name_never_reaches_the_real_library(self):
        status, made = self.ask("POST", "/api/courses?store=http-a", {"raw": STATE, "name": "In test storage"})
        self.assertEqual(status, 200)
        for query in ["", "?store=", "?store=http-b", "?store=http-a.", "?store=library"]:
            status, lib = self.ask("GET", "/api/library" + query)
            self.assertEqual(status, 200, query)
            self.assertNotIn(made["id"], [c["id"] for c in lib["courses"]], query)
            self.assertEqual(self.ask("GET", f"/api/courses/{made['id']}{query}")[0], 404, query)
        status, health = self.ask("GET", "/api/health?store=")
        self.assertTrue(health["testStorage"])
        self.assertFalse(self.ask("GET", "/api/health")[1]["testStorage"])

    def test_saves_are_checked_before_anything_is_written(self):
        _, made = self.ask("POST", "/api/courses?store=http-c", {"raw": STATE, "name": "Saves"})
        cid = made["id"]
        good = json.dumps({"v": 1, "answers": {"topic": {"value": "kept"}}, "at": "topic"})
        status, saved = self.ask("PUT", f"/api/courses/{cid}?store=http-c", {"raw": good, "baseVersion": made["version"]})
        self.assertEqual(status, 200)
        status, clash = self.ask("PUT", f"/api/courses/{cid}?store=http-c", {"raw": STATE, "baseVersion": made["version"]})
        self.assertEqual(status, 409)
        self.assertEqual(clash["currentVersion"], saved["version"])
        for bad in [{"raw": "{not json", "baseVersion": saved["version"]}, {"raw": {"v": 1}, "baseVersion": saved["version"]}, {"baseVersion": saved["version"]}]:
            self.assertEqual(self.ask("PUT", f"/api/courses/{cid}?store=http-c", bad)[0], 400, bad)
        self.assertEqual(self.ask("GET", f"/api/courses/{cid}?store=http-c")[1]["raw"], good)

    def test_work_for_claude_is_refused_unless_it_names_the_saved_version(self):
        _, made = self.ask("POST", "/api/courses?store=http-f", {"raw": STATE, "name": "Bound"})
        url = f"/api/courses/{made['id']}/engine?store=http-f"
        body = {"action": "begin", "brief": {"topics": ["x"]}, "plan": {"sessions": 1, "minutes": [30]}}
        for cv in [None, "1", True, 1.0]:
            self.assertEqual(self.ask("POST", url, dict(body, courseVersion=cv) if cv is not None else body)[0], 400, str(cv))
        for cv in [0, 2, 99]:
            status, got = self.ask("POST", url, dict(body, courseVersion=cv))
            self.assertEqual((status, got.get("currentVersion")), (409, 1), str(cv))
        self.assertEqual(self.ask("GET", url)[1]["record"], None, "nothing was started")

    def test_unknown_addresses_and_actions_are_refused(self):
        _, made = self.ask("POST", "/api/courses?store=http-d", {"raw": STATE, "name": "Actions"})
        self.assertEqual(self.ask("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.ask("GET", "/api/courses/../../etc?store=http-d")[0], 404)
        self.assertEqual(self.ask("GET", "/api/courses/not-an-id?store=http-d")[0], 404)
        status, _ = self.ask("POST", f"/api/courses/{made['id']}/engine?store=http-d", {"action": "delete_everything", "courseVersion": 1})
        self.assertEqual(status, 400)

    def test_the_log_leaves_out_ordinary_course_traffic(self):
        Quiet.lines.clear()
        self.ask("GET", "/api/library?store=http-log")
        self.ask("GET", "/api/nothing?store=http-log")
        self.assertFalse([l for l in Quiet.lines if "/api/library" in l], Quiet.lines)
        self.assertTrue([l for l in Quiet.lines if "/api/nothing" in l], Quiet.lines)


if __name__ == "__main__":
    unittest.main()

"""Course library on disk.

Rules this module keeps:
  * Every course has its own folder: brief, draft, history, approved versions and generation record.
  * A write never destroys the previous copy: files are replaced atomically and earlier versions go to history/.
  * Test storage (any `store` value) lives in a separate tree and can never reach the real library.
  * Restoring a backup always creates a NEW course. It never overwrites one.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.RLock()
HISTORY_KEEP = 40
HISTORY_EVERY_SECONDS = 300
BACKUP_HISTORY_BYTES = 24 * 1024 * 1024
ID_RE = re.compile(r"^c[a-z0-9]{6,40}$")
HASH_RE = re.compile(r"^[a-f0-9]{16,64}$")


class StoreError(Exception):
    status = 400


class NotFound(StoreError):
    status = 404


class Conflict(StoreError):
    status = 409

    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


def data_root() -> Path:
    return Path(os.environ.get("LOOM_DATA_DIR") or (ROOT / "data"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}Z"


def store_name(store) -> str | None:
    """None means the real library. Any other value, even an empty one, is test storage."""
    if store is None:
        return None
    raw = str(store).strip().lower() or "unnamed"
    slug = re.sub(r"[^a-z0-9_-]+", "_", raw)[:40].strip("_") or "x"
    return f"{slug}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"


def store_dir(store, make: bool = True) -> Path:
    """Reading never creates folders. Only writing does."""
    name = store_name(store)
    base = data_root() / "library" if name is None else data_root() / "test-stores" / name
    if make:
        (base / "courses").mkdir(parents=True, exist_ok=True)
        (base / "imports").mkdir(parents=True, exist_ok=True)
    return base


def _refuse(value):
    raise ValueError(f"{value} is not allowed")


def course_data(text) -> dict:
    """Course data must be one JSON object that any browser can read back. NaN and Infinity are refused."""
    if not isinstance(text, str):
        raise StoreError("Loom could not read what was sent.")
    try:
        data = json.loads(text, parse_constant=_refuse)
    except (ValueError, RecursionError):
        raise StoreError("Loom will not save something that is not readable course data.")
    if not isinstance(data, dict):
        raise StoreError("Loom will not save something that is not readable course data.")
    return data


def _text_or_none(value, what: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StoreError(f"The {what} must be text.")
    return value[:limit]


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def read_json(path: Path, default=None):
    text = read_text(path)
    if text is None:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def course_dir(store, cid: str) -> Path:
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise NotFound("That course does not exist.")
    d = store_dir(store, make=False) / "courses" / cid
    if not d.is_dir():
        raise NotFound("That course does not exist.")
    return d


def new_id() -> str:
    return "c" + format(int(time.time() * 1000), "x") + secrets.token_hex(3)


def _meta(d: Path) -> dict:
    m = read_json(d / "meta.json", {}) or {}
    m.setdefault("id", d.name)
    m.setdefault("name", "Untitled course")
    m.setdefault("version", 0)
    return m


def list_courses(store) -> dict:
    with LOCK:
        base = store_dir(store, make=False)
        out = []
        for d in sorted((base / "courses").iterdir()) if (base / "courses").is_dir() else []:
            if d.is_dir() and ID_RE.match(d.name) and (d / "course.json").exists():
                m = _meta(d)
                m["history"] = len(list((d / "history").glob("*.json"))) if (d / "history").is_dir() else 0
                out.append(m)
        out.sort(key=lambda m: m.get("updatedAt", ""), reverse=True)
        lib = read_json(base / "library.json", {}) or {}
        current = lib.get("current")
        if current not in [m["id"] for m in out]:
            current = out[0]["id"] if out else None
        imports = []
        for f in sorted((base / "imports").glob("*.json")) if (base / "imports").is_dir() else []:
            rec = read_json(f, {}) or {}
            imports.append({k: rec.get(k) for k in ("hash", "origin", "key", "status", "reasons", "importedAt", "courseId", "bytes")})
        return {"store": store_name(store), "current": current, "courses": out, "imports": imports}


def set_current(store, cid: str) -> None:
    with LOCK:
        course_dir(store, cid)
        write_atomic(store_dir(store) / "library.json", json.dumps({"current": cid, "at": now_iso()}))


def create_course(store, raw: str | None, name: str | None, summary: dict | None = None, note: str | None = None, named: bool = False) -> dict:
    """raw is the exact text to store as course.json, or None for an empty course (the browser fills it in).

    The name in meta.json is the course's name. `named` says a person or Loom's library gave it on purpose (a copy, a restore,
    a rename). Such a name is only ever changed by a rename. A name that was not given on purpose follows the brief's topics.
    """
    if raw:
        course_data(raw)
    name = _text_or_none(name, "course name", 120)
    note = _text_or_none(note, "note", 400)
    if summary is not None and not isinstance(summary, dict):
        raise StoreError("The course summary could not be read.")
    with LOCK:
        base = store_dir(store)
        cid = new_id()
        while (base / "courses" / cid).exists():
            cid = new_id()
        d = base / "courses" / cid
        (d / "history").mkdir(parents=True)
        now = now_iso()
        meta = {"id": cid, "name": (name or "Untitled course")[:120], "createdAt": now, "updatedAt": now, "version": 1, "summary": summary or {}, "note": note or "", "named": bool(named and name)}
        write_atomic(d / "course.json", raw if raw is not None else "")
        write_atomic(d / "meta.json", json.dumps(meta, indent=1))
        set_current(store, cid)
        return meta


def get_course(store, cid: str) -> dict:
    with LOCK:
        d = course_dir(store, cid)
        return {"id": cid, "meta": _meta(d), "raw": read_text(d / "course.json") or ""}


def _keep_history(d: Path, previous: str, version: int, reason: str | None) -> None:
    if not previous:
        return
    h = d / "history"
    h.mkdir(exist_ok=True)
    files = sorted(h.glob("*.json"))
    newest = files[-1].stat().st_mtime if files else 0
    if reason or time.time() - newest >= HISTORY_EVERY_SECONDS:
        tag = re.sub(r"[^a-z0-9-]+", "-", (reason or "auto").lower())[:24]
        write_atomic(h / f"{stamp()}-v{version}-{tag}.json", previous)
        files = sorted(h.glob("*.json"))
        # Copies made for a reason (approval, restore, weave) are kept longest. Routine ones are trimmed first.
        routine = [f for f in files if f.name.endswith("-auto.json")]
        while len(files) > HISTORY_KEEP and routine:
            old = routine.pop(0)
            old.unlink(missing_ok=True)
            files.remove(old)


def put_course(store, cid: str, text: str, base_version: int, name: str | None, summary: dict | None, reason: str | None) -> dict:
    """Replace the working copy. Refuses if someone else saved since base_version.

    Everything is checked before anything is written. The copy being replaced is always kept as previous.json (one step back),
    and a dated copy goes to history/ at every named event and every few minutes of editing.
    """
    course_data(text)
    name = _text_or_none(name, "course name", 120)
    reason = _text_or_none(reason, "reason", 40)
    if summary is not None and not isinstance(summary, dict):
        raise StoreError("The course summary could not be read.")
    if isinstance(base_version, bool) or not isinstance(base_version, int):
        raise StoreError("The save did not say which version it was made from.")
    with LOCK:
        d = course_dir(store, cid)
        meta = _meta(d)
        if base_version != int(meta.get("version", 0)):
            raise Conflict("This course was changed in another window.", meta.get("version", 0))
        previous = read_text(d / "course.json") or ""
        if previous == text and (name is None or name == meta.get("name") or (meta.get("named") and reason != "rename")):
            return meta
        if previous:
            write_atomic(d / "previous.json", previous)
        _keep_history(d, previous, meta["version"], reason)
        meta["version"] = int(meta["version"]) + 1
        meta["updatedAt"] = now_iso()
        # An ordinary save carries the name the page worked out from the brief. It never replaces a name given on purpose.
        if name and reason == "rename":
            meta["name"] = name
            meta["named"] = True
        elif name and not meta.get("named"):
            meta["name"] = name
        if summary is not None:
            meta["summary"] = summary
        # The version is moved on first. If the next write fails, a later save from an old window is still refused.
        write_atomic(d / "meta.json", json.dumps(meta, indent=1))
        write_atomic(d / "course.json", text)
        if read_text(d / "course.json") != text:
            raise StoreError("The file on disk does not match what was sent. The copy from before is in previous.json.")
        return meta


def rename_course(store, cid: str, name: str) -> dict:
    with LOCK:
        d = course_dir(store, cid)
        meta = _meta(d)
        if not isinstance(name, str) or not name.strip():
            raise StoreError("A course needs a name, written as text.")
        meta["name"] = name.strip()[:120]
        meta["named"] = True
        # A rename is a change like any other: a window that loaded the course before it must not save over it.
        meta["version"] = int(meta.get("version", 0)) + 1
        meta["updatedAt"] = now_iso()
        write_atomic(d / "meta.json", json.dumps(meta, indent=1))
        return meta


def archive_course(store, cid: str, archived: bool) -> dict:
    """Put a course away, or bring it back. Nothing is deleted: the folder, its history and its versions stay where they are."""
    if not isinstance(archived, bool):
        raise StoreError("Say whether the course is to be archived or brought back.")
    with LOCK:
        d = course_dir(store, cid)
        meta = _meta(d)
        meta["archived"] = archived
        meta["archivedAt"] = now_iso() if archived else None
        meta["version"] = int(meta.get("version", 0)) + 1
        write_atomic(d / "meta.json", json.dumps(meta, indent=1))
        return meta


def duplicate_course(store, cid: str, name: str | None = None) -> dict:
    """A new course that starts as a copy of this one, with its approved versions and its generation record. The original is not touched."""
    with LOCK:
        d = course_dir(store, cid)
        old = _meta(d)
        raw = read_text(d / "course.json") or ""
        if raw:
            course_data(raw)
        meta = create_course(store, raw or None, (_text_or_none(name, "course name", 120) or f"{old.get('name', 'Course')} (copy)")[:120], old.get("summary") if isinstance(old.get("summary"), dict) else None, named=True,
                             note=f"Copied from “{old.get('name', '')}” on {datetime.now().strftime('%d %b %Y')}.")
        eng = read_json(d / "engine.json")
        if isinstance(eng, dict):
            if eng.get("status") == "running":
                eng["status"] = "paused"
                eng["pause"] = {"kind": "copied", "reason": "This course was copied while work was unfinished. Resume to finish it here.", "at": now_iso()}
            _place_prepared(store, meta["id"], prepared_bundle(store, cid), eng)
            _place_provenance(store, meta["id"], provenance_bundle(store, cid))
            write_atomic(course_dir(store, meta["id"]) / "engine.json", json.dumps(eng, indent=1, ensure_ascii=False))
        return meta


def history(store, cid: str) -> list:
    with LOCK:
        d = course_dir(store, cid) / "history"
        return [{"file": f.name, "bytes": f.stat().st_size} for f in sorted(d.glob("*.json"))] if d.is_dir() else []


def backup(store, cid: str) -> dict:
    with LOCK:
        d = course_dir(store, cid)
        # The newest copies go in first. Older ones are left out once the file would be too large to restore, and the file says how many.
        files = sorted((d / "history").glob("*.json"), reverse=True) if (d / "history").is_dir() else []
        hist, used = [], 0
        for f in files:
            size = f.stat().st_size
            if used + size > BACKUP_HISTORY_BYTES:
                break
            hist.append({"file": f.name, "raw": f.read_text(encoding="utf-8")})
            used += size
        hist.reverse()
        return {"kind": "glitch-loom-backup", "formatVersion": 1, "madeAt": now_iso(), "course": {"id": cid, "meta": _meta(d), "raw": read_text(d / "course.json") or ""},
                "engine": read_json(d / "engine.json"), "history": hist, "historyLeftOut": len(files) - len(hist), "previous": read_text(d / "previous.json"),
                "prepared": prepared_bundle(store, cid), "provenance": provenance_bundle(store, cid),
                "note": "A full copy of one Loom course for safekeeping. It contains internal notes. It is not an export for teaching and nothing in it is published."}


def restore(store, bundle: dict) -> dict:
    """Always creates a new course. Nothing existing is touched."""
    if not isinstance(bundle, dict) or bundle.get("kind") != "glitch-loom-backup" or not isinstance(bundle.get("course"), dict):
        raise StoreError("That file is not a Loom backup.")
    raw = bundle["course"].get("raw")
    if not isinstance(raw, str) or not raw.strip():
        raise StoreError("That backup has no course in it.")
    try:
        course_data(raw)
    except StoreError:
        raise StoreError("The course inside that backup is not readable.")
    # Everything is read and checked before a course is created, so a bad backup leaves nothing behind.
    old = bundle["course"].get("meta") if isinstance(bundle["course"].get("meta"), dict) else {}
    old_name = old.get("name") if isinstance(old.get("name"), str) else "Course"
    summary = old.get("summary") if isinstance(old.get("summary"), dict) else None
    made = bundle.get("madeAt") if isinstance(bundle.get("madeAt"), str) else "at an unknown time"
    kept = [h for h in (bundle.get("history") if isinstance(bundle.get("history"), list) else [])
            if isinstance(h, dict) and isinstance(h.get("raw"), str) and re.match(r"^[A-Za-z0-9_.-]{1,80}\.json$", str(h.get("file", "")))]
    kept = sorted(kept, key=lambda h: h["file"])[-HISTORY_KEEP:]
    with LOCK:
        meta = create_course(store, raw, f"{old_name} (restored {datetime.now().strftime('%d %b %Y')})"[:120], summary, note=f"Restored from a backup made {made[:40]}.", named=True)
        d = course_dir(store, meta["id"])
        if isinstance(bundle.get("engine"), dict):
            eng = bundle["engine"]
            if eng.get("status") == "running":
                eng["status"] = "paused"
                eng["pause"] = {"kind": "restored", "reason": "This course was restored from a backup while work was unfinished.", "at": now_iso()}
            _place_prepared(store, meta["id"], bundle.get("prepared"), eng)
            if gap := _place_provenance(store, meta["id"], bundle.get("provenance")):
                eng["provenanceIncomplete"] = dict(gap, restoredAt=now_iso())
            write_atomic(d / "engine.json", json.dumps(eng, indent=1))
        if not isinstance(bundle.get("engine"), dict):
            _place_provenance(store, meta["id"], bundle.get("provenance"))
        for h in kept:
            write_atomic(d / "history" / h["file"], h["raw"])
        if isinstance(bundle.get("previous"), str) and bundle["previous"]:
            write_atomic(d / "previous.json", bundle["previous"])
        return meta


def save_import(store, origin: str, key: str, raw: str, status: str, reasons: list, course_id: str | None) -> dict:
    """Keep an exact copy of work found in a browser's own storage. The same content is only stored once."""
    if not isinstance(raw, str) or not raw:
        raise StoreError("There was nothing to import.")
    digest = hashlib.sha256((str(origin) + "\n" + raw).encode("utf-8")).hexdigest()[:32]
    with LOCK:
        f = store_dir(store) / "imports" / f"{digest}.json"
        rec = read_json(f)
        if rec:
            if course_id and not rec.get("courseId"):
                rec["courseId"] = course_id
                write_atomic(f, json.dumps(rec, indent=1))
            return {"hash": digest, "known": True, "courseId": rec.get("courseId"), "status": rec.get("status")}
        rec = {"hash": digest, "origin": str(origin)[:120], "key": str(key)[:120], "status": status if status in ("ok", "damaged") else "damaged", "reasons": [str(r)[:200] for r in (reasons or [])][:8],
               "importedAt": now_iso(), "courseId": course_id, "bytes": len(raw), "raw": raw}
        write_atomic(f, json.dumps(rec, indent=1))
        return {"hash": digest, "known": False, "courseId": course_id, "status": rec["status"]}


def find_import(store, origin: str, raw: str) -> dict | None:
    if not isinstance(raw, str):
        raise StoreError("Loom could not read what was sent.")
    digest = hashlib.sha256((str(origin) + "\n" + raw).encode("utf-8")).hexdigest()[:32]
    rec = read_json(store_dir(store, make=False) / "imports" / f"{digest}.json")
    return {"hash": digest, "courseId": rec.get("courseId"), "status": rec.get("status")} if rec else None


def get_import(store, digest: str) -> dict:
    if not HASH_RE.match(digest or ""):
        raise NotFound("That import does not exist.")
    rec = read_json(store_dir(store, make=False) / "imports" / f"{digest}.json")
    if not rec:
        raise NotFound("That import does not exist.")
    return rec


def read_ideas(store, cid: str) -> dict | None:
    with LOCK:
        return read_json(course_dir(store, cid) / "ideas.json")


def write_ideas(store, cid: str, rec: dict) -> None:
    with LOCK:
        write_atomic(course_dir(store, cid) / "ideas.json", json.dumps(rec, indent=1, ensure_ascii=False))


def engine_path(store, cid: str) -> Path:
    return course_dir(store, cid) / "engine.json"


def read_engine(store, cid: str) -> dict | None:
    with LOCK:
        return read_json(engine_path(store, cid))


def write_engine(store, cid: str, rec: dict) -> None:
    with LOCK:
        rec["savedAt"] = now_iso()
        write_atomic(engine_path(store, cid), json.dumps(rec, indent=1, ensure_ascii=False))


# Durable provenance beside a course. Two directories, both append-only.
#
# `requests/` holds one file per DISTINCT request the attribution reviewer was sent — the whole prompt, the answer
# schema, the system text and the settings in force — so an old judgement can be read back against the exact ask
# that produced it rather than against a hash of it. A hash says two runs differed; it cannot say how.
#
# `attribution-history/` holds judgements that have scrolled out of the working index kept in engine.json. The
# index was trimmed with `del past[:-20]`, which silently destroyed every judgement older than the last twenty
# while the written rule said every one is kept. Trimmed entries are now appended here first.
_FP_RE = re.compile(r"^[a-z0-9]{4,64}(\.[a-z0-9]{1,16})?$")


def _fp_name(fingerprint: str) -> str:
    """A fingerprint as a filename, or a hash of it when it is not one Loom wrote."""
    t = str(fingerprint or "").strip().lower()
    return t.replace(".", "-") if _FP_RE.match(t) else "x" + hashlib.sha256(t.encode("utf-8")).hexdigest()[:24]


def save_request_snapshot(store, cid: str, fingerprint: str, payload: dict) -> str:
    """Keep the whole request under its fingerprint, once. Returns the name it was kept under.

    Written once and never rewritten: a snapshot that could be replaced is not a record of what was asked. The
    same request made by a hundred sources in one batch is one file, because it is one request.
    """
    name = _fp_name(fingerprint) + ".json"
    with LOCK:
        d = course_dir(store, cid) / "requests"
        d.mkdir(exist_ok=True)
        path = d / name
        if not path.exists():
            write_atomic(path, json.dumps(payload, indent=1, ensure_ascii=False))
    return name


def read_request_snapshot(store, cid: str, fingerprint: str) -> dict | None:
    with LOCK:
        return read_json(course_dir(store, cid) / "requests" / (_fp_name(fingerprint) + ".json"))


def archive_judgements(store, cid: str, key: str, entries: list) -> str:
    """Append judgements leaving the working index to a durable file. Nothing is ever deleted from it."""
    if not entries:
        return ""
    name = "k" + hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:24] + ".jsonl"
    with LOCK:
        d = course_dir(store, cid) / "attribution-history"
        d.mkdir(exist_ok=True)
        with (d / name).open("a", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps({"key": key, **e}, ensure_ascii=False) + "\n")
    return name


def read_archived_judgements(store, cid: str, key: str) -> list:
    name = "k" + hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:24] + ".jsonl"
    path = course_dir(store, cid) / "attribution-history" / name
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"unreadable": line[:200]})
    return out


PROVENANCE_BYTES = 8 * 1024 * 1024  # how much request/judgement provenance one backup file will carry
_PROV_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(json|jsonl)$")


def provenance_bundle(store, cid: str) -> dict:
    """The kept requests and the archived judgements, for a backup or a copy.

    These are the records that say what was asked and what was answered before. A backup that leaves them behind
    restores a course whose history begins at the restore, which breaks "nothing is deleted" by a second route:
    not by trimming the list, but by copying everything except the list. Where the cap bites, the most recently
    written provenance is kept and the count of what was left out is carried in the backup rather than implied.
    """
    d = course_dir(store, cid)
    got: dict = {"requests": [], "judgements": [], "leftOut": 0}
    used = 0
    for sub, into in (("requests", "requests"), ("attribution-history", "judgements")):
        p = d / sub
        if not p.is_dir():
            continue
        # `is_file()` follows a symlink, so a link planted in these directories pulled a file from outside the
        # course into the backup. A backup must contain the course and nothing else, so only real files that are
        # really here are read, and anything else is named rather than silently skipped.
        for f in sorted([x for x in p.iterdir() if x.is_file() and not x.is_symlink()],
                        key=lambda x: x.stat().st_mtime, reverse=True):
            if not _PROV_NAME.match(f.name):
                got.setdefault("skipped", []).append(f.name)
                continue
            size = f.stat().st_size
            if used + size > PROVENANCE_BYTES:
                got["leftOut"] += 1
                continue
            got[into].append({"file": f.name, "raw": f.read_text(encoding="utf-8")})
            used += size
        for x in p.iterdir():
            if x.is_symlink():
                got.setdefault("skipped", []).append(x.name + " (a link out of the course, not copied)")
    return got


def _place_provenance(store, cid: str, bundle) -> dict | None:
    """Write kept requests and archived judgements into a course. Names are checked, so nothing escapes the course.

    Returns what the restored course could NOT be given, so the gap can be written down where someone will see
    it. A backup that left records behind restored silently: the new course looked like a complete record of
    everything ever asked and answered, and nothing in it said otherwise.
    """
    if not isinstance(bundle, dict):
        return None
    d = course_dir(store, cid)
    refused: list = []
    for into, sub in (("requests", "requests"), ("judgements", "attribution-history")):
        items = bundle.get(into)
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            name, raw = str(it.get("file") or ""), it.get("raw")
            if not isinstance(raw, str) or not _PROV_NAME.match(name):
                refused.append(str(name)[:80])
                continue
            (d / sub).mkdir(exist_ok=True)
            write_atomic(d / sub / name, raw)
    left = bundle.get("leftOut")
    skipped = bundle.get("skipped") if isinstance(bundle.get("skipped"), list) else []
    if not (isinstance(left, int) and left > 0) and not skipped and not refused:
        return None
    return {"recordsNotInThisCopy": left if isinstance(left, int) else 0,
            "notCopiedFromTheOriginal": [str(x)[:80] for x in skipped][:50],
            "refusedOnRestore": refused[:50],
            "whatThisMeans": ("This course was restored from a backup that did not carry every request and "
                              "judgement the original had. What is here is real; it is not the whole record. "
                              "The original course still holds the rest.")}


EXPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.(json|html)$")
EXPORT_MAX = 24 * 1024 * 1024


def save_export(store, cid: str, name, text, ver, kind) -> dict:
    """Keep a copy of a package the team downloaded, on this computer, and say exactly what was kept.

    A browser may be told to download a file and still not save one. This copy is the record that the package existed, with its size and a checksum.
    It lives inside the course's own folder and is never sent anywhere.
    """
    if not isinstance(name, str) or not EXPORT_NAME.match(name):
        raise StoreError("That file name cannot be kept.")
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > EXPORT_MAX:
        raise StoreError("There was nothing to keep, or it is too large.")
    with LOCK:
        d = course_dir(store, cid) / "exports"
        d.mkdir(exist_ok=True)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        stem, dot, ext = name.rpartition(".")
        final, n = name, 1
        while (d / final).exists():
            if hashlib.sha256((d / final).read_bytes()).hexdigest() == digest:
                break  # the same file again: kept once
            final = f"{stem}-{n}.{ext}"
            n += 1
        write_atomic(d / final, text)
        rec = {"name": final, "bytes": len(text.encode("utf-8")), "sha256": digest, "savedAt": now_iso(), "ver": ver if isinstance(ver, int) and not isinstance(ver, bool) else None, "kind": str(kind or "")[:20], "folder": str(d)}
        return rec


def list_exports(store, cid: str) -> list:
    with LOCK:
        d = course_dir(store, cid) / "exports"
        return [{"name": f.name, "bytes": f.stat().st_size, "savedAt": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")} for f in sorted(d.glob("*")) if f.is_file()] if d.is_dir() else []


PREPARED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
PREPARED_MAX = 400 * 1024


def prepared_path(store, cid: str, name: str, make: bool = False) -> Path:
    """Where a prepared file lives, worked out from its name every time.

    The stored record never decides this. A name is accepted only if it matches PREPARED_NAME and the
    resolved file still sits directly inside this course's own `prepared/` folder, so a name can never
    reach another course or anywhere else on the disk. Because the path is derived and not saved, a
    backup restored under a different folder, user or machine still finds its files.
    """
    if not isinstance(name, str) or not PREPARED_NAME.match(name):
        raise StoreError("That file name cannot be kept.")
    d = course_dir(store, cid) / "prepared"
    if make:
        d.mkdir(exist_ok=True)
    f = d / name
    try:
        base, real = d.resolve(strict=False), f.resolve(strict=False)
    except OSError:
        raise StoreError("That file name cannot be kept.")
    if real.parent != base:
        raise StoreError("That file name cannot be kept.")
    if f.is_symlink():
        raise StoreError(f"{name} is a link, not a kept file. Prepared files are real files inside their own course.")
    if f.exists() and not f.is_file():
        raise StoreError(f"{name} is not a regular file.")
    return f


def read_prepared(store, cid: str, name: str, sha256: str | None = None) -> bytes:
    """The bytes of a prepared file, checked against the checksum the record claims before anything is allowed to use them."""
    f = prepared_path(store, cid, name)
    try:
        data = f.read_bytes()
    except OSError:
        raise StoreError(f"The prepared file {name} is registered but its bytes are not in this course's folder.")
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError(f"The prepared file {name} on disk does not match the checksum recorded for it. It is not used.")
    return data


def prepared_bundle(store, cid: str) -> list:
    """Every prepared file's real bytes, for a backup or a copy, so the new course never depends on the old one's folder.

    The bytes are carried base64-encoded, exactly as they are on disk. An earlier version decoded them as UTF-8
    with replacement, which silently corrupts a PDF or an image; nothing here decodes. `text` is added only when
    the file really is UTF-8, for readability and for restoring a backup written by an older build.
    """
    d = course_dir(store, cid) / "prepared"
    out = []
    if d.is_dir():
        for f in sorted(d.iterdir()):
            if f.is_symlink() or not f.is_file() or not PREPARED_NAME.match(f.name):
                continue
            data = f.read_bytes()
            item = {"name": f.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "b64": base64.b64encode(data).decode("ascii")}
            try:
                item["text"] = data.decode("utf-8")
            except UnicodeDecodeError:
                item["encoding"] = "binary"
            out.append(item)
    return out


def _prepared_item_bytes(it: dict) -> bytes | None:
    """The exact bytes an item carries. base64 is preferred; text is accepted only from a backup that has no base64."""
    if isinstance(it.get("b64"), str):
        try:
            return base64.b64decode(it["b64"], validate=True)
        except (ValueError, binascii.Error):
            return None
    if isinstance(it.get("text"), str) and it.get("encoding") != "binary":
        return it["text"].encode("utf-8")
    return None


def _place_prepared(store, cid: str, items, eng) -> None:
    """Write prepared bytes into the NEW course and re-point the record at it.

    A path saved by another course, machine or user is never carried over: it is stripped, and every file the
    record claims must arrive with bytes that match its recorded checksum, or the record is marked as missing them.
    """
    kept = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("name"), str):
            continue
        data = _prepared_item_bytes(it)
        if data is None or (it.get("sha256") and hashlib.sha256(data).hexdigest() != it["sha256"]):
            continue  # bytes that do not match the checksum they arrived with are never written
        try:
            f = prepared_path(store, cid, it["name"], make=True)
        except StoreError:
            continue
        if not f.exists():
            f.write_bytes(data)
        kept[it["name"]] = hashlib.sha256(data).hexdigest()
    if isinstance(eng, dict) and isinstance(eng.get("prepared"), list):
        for x in eng["prepared"]:
            if not isinstance(x, dict):
                continue
            x.pop("path", None)  # never trust a path from somewhere else
            if x.get("name") not in kept or (x.get("sha256") and kept[x["name"]] != x["sha256"]):
                x["bytesMissing"] = True
            else:
                x.pop("bytesMissing", None)


def save_prepared_file(store, cid: str, name: str, data: bytes) -> str:
    """Keep an exact copy of a prepared file inside the course's own folder. An existing file with different content is never replaced."""
    if not isinstance(data, bytes) or not data or len(data) > PREPARED_MAX:
        raise StoreError("There was nothing to keep, or it is too large.")
    with LOCK:
        f = prepared_path(store, cid, name, make=True)
        if f.exists() and f.read_bytes() != data:
            raise StoreError(f"A different file called {name} is already kept. Prepared files are never replaced.")
        if not f.exists():
            f.write_bytes(data)
        return str(f)

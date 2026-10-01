"""The real generation path: Claude, through the Claude Code command-line tool in its non-interactive mode.

Rules this module keeps:
  * Only the person's own subscription login is used. API keys and custom endpoints are removed from the environment,
    and a run is stopped as soon as the tool reports an API key or paid extra usage. That report comes after the request has started.
  * Work is saved after every finished part. A failure pauses the work with the reason. Nothing is made up to fill a gap.
  * One request runs at a time.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import evidence, lineage, pipeline, prompts, storage

CLI_GATE = threading.Semaphore(1)
RUNNERS: dict = {}
RUNNERS_LOCK = threading.Lock()
CHILDREN: set = set()
CHILDREN_LOCK = threading.Lock()

# Generous on purpose: a request stopped near the end has to be done again from the start.
TIMEOUT = {"research": 20 * 60, "outline": 30 * 60, "materials": 25 * 60, "review": 15 * 60, "edit": 15 * 60, "ideas": 12 * 60,
           "attribution_review": 12 * 60, "identity": 12 * 60, "lineage": 12 * 60, "endpoints": 12 * 60, "map": 10 * 60, "foundation_review": 10 * 60, "source_review": 12 * 60, "outline_review": 10 * 60, "project": 25 * 60}
TURNS = {"research": 40, "outline": 4, "materials": 4, "review": 4, "edit": 4, "ideas": 30,
         "attribution_review": 4, "identity": 4, "lineage": 4, "endpoints": 4, "map": 4, "foundation_review": 4, "source_review": 4, "outline_review": 4, "project": 4}
_HISTORY_INDEX_KEEP = 20  # judgements kept inline per source; older ones move to the durable archive, never away
AUTO_REVISE_ROUNDS = 1  # how many times Loom sends an outline back by itself after its reviewer finds a must-fix. Then the problem is shown, not hidden.
TARGETED_RESEARCH_ROUNDS = 1
EXCERPT_KEEP = 1500     # characters of what a fetch returned that are kept with each source
CACHE_KEEP = 12000      # characters kept for reuse, quote checks and checking data against the page it came from
SAFE_PATH = os.pathsep.join([str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


class Pause(Exception):
    """Work must stop and wait for a person. kind: limit, overage, api_key, auth, cli_missing, timeout, stopped, invalid, error."""

    def __init__(self, kind: str, reason: str, detail: str = "", resets_at: int | None = None):
        super().__init__(reason)
        self.kind, self.reason, self.detail, self.resets_at = kind, reason, detail, resets_at


def config() -> dict:
    cfg = storage.read_json(storage.ROOT / "loom.config.json", {}) or {}
    return {"model": os.environ.get("LOOM_MODEL") or cfg.get("model") or "", "effort": os.environ.get("LOOM_EFFORT") or cfg.get("effort") or ""}


def clean_env() -> dict:
    """Nothing beginning ANTHROPIC_ or CLAUDE is passed on, so only the saved subscription login can be used."""
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "TMPDIR", "SHELL") if k in os.environ}
    env["PATH"] = SAFE_PATH
    env["LANG"] = "en_US.UTF-8"
    for k in ("FAKE_CLAUDE_PLAN",):  # used only by the test double
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def cli_path() -> str | None:
    override = os.environ.get("LOOM_CLAUDE_BIN")
    if override:
        return override if Path(override).exists() else None
    return shutil.which("claude", path=SAFE_PATH)


def work_dir() -> Path:
    d = storage.data_root() / ".cli-work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file(pid: int) -> Path:
    return work_dir() / f"request-{pid}.pid"


def _canon(o) -> str:
    """One exact text for a piece of content. The page builds the same text the same way, so the two can be compared."""
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, int):
        return str(o)
    if isinstance(o, float):
        return json.dumps(o)
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_canon(x) for x in o) + "]"
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + _canon(v) for k, v in sorted(o.items())) + "}"
    return "null"


def _b36(n: int) -> str:
    if n == 0:
        return "0"
    d, out = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while n:
        n, r = divmod(n, 36)
        out = d[r] + out
    return out


def content_print(o) -> str:
    """A short fingerprint of content. Counted over UTF-16 units, so the page and the server always agree."""
    units = _canon(o).encode("utf-16-le")
    h = 5381
    for i in range(0, len(units), 2):
        h = ((h * 33) ^ (units[i] | (units[i + 1] << 8))) & 0xFFFFFFFF
    return _b36(h) + "." + _b36(len(units) // 2)


def stop_requests() -> int:
    """Stop every request this server started. Called when the server is shutting down."""
    with CHILDREN_LOCK:
        procs = list(CHILDREN)
    for proc in procs:
        try:
            proc.kill()
        except OSError:
            pass
        _pid_file(proc.pid).unlink(missing_ok=True)
    return len(procs)


def stop_leftovers() -> int:
    """If the server was killed outright, a request it started may still be running. Stop it, and only it."""
    n = 0
    for f in work_dir().glob("request-*.pid"):
        try:
            pid = int(f.read_text().strip())
            cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=10).stdout
            if "--output-format stream-json" in cmd and "--no-session-persistence" in cmd:
                os.kill(pid, 9)
                n += 1
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        f.unlink(missing_ok=True)
    return n


_status_cache = {"at": 0.0, "value": None}


def status(force: bool = False) -> dict:
    """What a person needs to know before starting: is the tool there, is it signed in, and with what."""
    if not force and _status_cache["value"] and time.time() - _status_cache["at"] < 60:
        return _status_cache["value"]
    out = {"ready": False, "blocker": "", "cli": {"found": False, "path": "", "version": ""}, "auth": {}, "model": config()["model"] or "the tool's own default", "testDouble": bool(os.environ.get("LOOM_CLAUDE_BIN"))}
    path = cli_path()
    if not path:
        out["blocker"] = "The Claude command-line tool was not found on this computer. Install Claude Code, then sign in by running “claude” in a terminal."
    else:
        out["cli"].update(found=True, path=path)
        try:
            v = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, env=clean_env(), cwd=str(work_dir()))
            out["cli"]["version"] = (v.stdout or v.stderr).strip().splitlines()[0][:60] if (v.stdout or v.stderr).strip() else ""
            a = subprocess.run([path, "auth", "status", "--json"], capture_output=True, text=True, timeout=30, env=clean_env(), cwd=str(work_dir()))
            info = json.loads(a.stdout) if a.stdout.strip().startswith("{") else {}
            out["auth"] = {"loggedIn": bool(info.get("loggedIn")), "method": info.get("authMethod") or "", "subscription": info.get("subscriptionType") or ""}
            if not out["auth"]["loggedIn"]:
                out["blocker"] = "The Claude command-line tool is not signed in. Open a terminal, run “claude auth login”, and sign in yourself. Loom never asks for your password."
            elif out["auth"]["method"] != "claude.ai":
                out["blocker"] = f"The Claude tool is signed in with “{out['auth']['method']}”, not with a Claude subscription. Loom only uses a subscription login, so that it cannot run up a bill."
            else:
                out["ready"] = True
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            out["blocker"] = f"Loom could not ask the Claude tool for its status: {e}"
    _status_cache.update(at=time.time(), value=out)
    return out


norm_url = pipeline.norm_url


def run_cli(stage: str, prompt: str, schema: dict, tools: str = "", on_event=None, stop: threading.Event | None = None) -> dict:
    """One request. Returns {output, model, usage, turns, trace, rate, seconds}. Raises Pause when a person is needed."""
    path = cli_path()
    if not path:
        raise Pause("cli_missing", "The Claude command-line tool was not found on this computer.")
    cfg = config()
    cmd = [path, "-p", "--output-format", "stream-json", "--verbose", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
           "--permission-mode", "dontAsk", "--system-prompt", prompts.SYSTEM, "--tools", tools, "--max-turns", str(TURNS[stage]), "--json-schema", json.dumps(schema)]
    if tools:
        cmd += ["--allowedTools", tools]
    if cfg["model"]:
        cmd += ["--model", cfg["model"]]
    if cfg["effort"]:
        cmd += ["--effort", cfg["effort"]]
    started = time.time()
    # A request for a page is not a page. "fetched" holds only pages that came back; every request is kept with what happened to it.
    trace = {"searches": [], "fetched": [], "fetches": []}
    asked = {}
    rate, result, init, stderr_tail = {}, None, {}, []
    while not CLI_GATE.acquire(timeout=0.5):  # one request at a time; a waiting request can still be stopped
        if stop is not None and stop.is_set():
            raise Pause("stopped", "Stopped by you.")
    try:
        if stop is not None and stop.is_set():
            raise Pause("stopped", "Stopped by you.")
        started = time.time()
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=clean_env(), cwd=str(work_dir()))
        except OSError as e:
            raise Pause("cli_missing", "The Claude command-line tool could not be started.", str(e))
        with CHILDREN_LOCK:
            CHILDREN.add(proc)
        try:
            _pid_file(proc.pid).write_text(str(proc.pid))
        except OSError:
            pass
        halt = {"pause": None}

        def kill(p: Pause):
            halt["pause"] = halt["pause"] or p
            try:
                proc.kill()
            except OSError:
                pass

        def watchdog():
            while proc.poll() is None:
                if time.time() - started > TIMEOUT[stage]:
                    kill(Pause("timeout", f"Claude did not finish within {TIMEOUT[stage] // 60} minutes, so Loom stopped waiting."))
                    return
                if stop is not None and stop.is_set():
                    kill(Pause("stopped", "Stopped by you."))
                    return
                time.sleep(0.5)

        def drain_err():
            for line in proc.stderr:
                stderr_tail.append(line.rstrip()[:300])
                del stderr_tail[:-12]

        threading.Thread(target=watchdog, daemon=True).start()
        threading.Thread(target=drain_err, daemon=True).start()
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError:
            pass
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                init = {"model": ev.get("model"), "apiKeySource": ev.get("apiKeySource"), "tools": ev.get("tools")}
                if (ev.get("apiKeySource") or "none") != "none":
                    kill(Pause("api_key", "The Claude tool reported that it was using an API key, not your subscription. Loom stopped the request as soon as it saw this. The request had already started, so check your API account for any charge.", f"apiKeySource={ev.get('apiKeySource')}"))
            elif kind == "rate_limit_event":
                rate = ev.get("rate_limit_info") or {}
                if rate.get("isUsingOverage"):
                    kill(Pause("overage", "The Claude tool reported that paid extra usage was in use. Loom stopped the request as soon as it saw this. The request had already started, so Loom cannot say that nothing was charged. Check your Claude account.", json.dumps(rate), rate.get("resetsAt")))
            elif kind == "assistant":
                for c in (ev.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        inp = c.get("input") or {}
                        if c.get("name") == "WebSearch" and inp.get("query"):
                            trace["searches"].append(str(inp["query"])[:200])
                            if on_event:
                                on_event({"did": "searched", "what": str(inp["query"])[:200]})
                        elif c.get("name") == "WebFetch" and inp.get("url"):
                            rec_ = {"url": str(inp["url"])[:500], "state": "no_result", "note": ""}
                            trace["fetches"].append(rec_)
                            if c.get("id"):
                                asked[c["id"]] = rec_
                            if on_event:
                                on_event({"did": "asked for", "what": rec_["url"]})
            elif kind == "user":
                content = (ev.get("message") or {}).get("content")
                for c in content if isinstance(content, list) else []:
                    rec_ = asked.get(c.get("tool_use_id")) if isinstance(c, dict) and c.get("type") == "tool_result" else None
                    if rec_ is None:
                        continue
                    rec_.update(fetch_outcome(c))
                    if rec_["state"] == "retrieved":
                        trace["fetched"].append(rec_["url"])
                        rec_["text"] = result_text(c)[:20000]
                    if on_event:
                        on_event({"did": "opened" if rec_["state"] == "retrieved" else "could not open", "what": rec_["url"]})
            elif kind == "result":
                result = ev
        proc.wait()
        with CHILDREN_LOCK:
            CHILDREN.discard(proc)
        _pid_file(proc.pid).unlink(missing_ok=True)
        for pipe in (proc.stdout, proc.stderr, proc.stdin):
            try:
                pipe.close()
            except OSError:
                pass
    finally:
        CLI_GATE.release()
    if halt["pause"]:
        raise halt["pause"]
    seconds = round(time.time() - started, 1)
    if result is None:
        raise Pause("error", "The Claude tool stopped without giving an answer.", " / ".join(stderr_tail)[-600:] or f"exit code {proc.returncode}")
    text = str(result.get("result") or "")
    if result.get("is_error") or result.get("subtype") != "success":
        low = (text + " " + " ".join(stderr_tail)).lower()
        resets = rate.get("resetsAt")
        if (rate.get("status") and rate.get("status") not in ("allowed", "allowed_warning")) or re.search(r"(usage|session|weekly|rate) limit|limit reached|hit your .*limit", low):
            raise Pause("limit", "Your Claude plan's usage limit has been reached." + (" It resets at " + time.strftime("%H:%M on %d %b", time.localtime(resets)) + "." if resets else ""), text[:400], resets)
        if re.search(r"log ?in|logged out|authenticat|oauth|unauthori[sz]ed|401", low):
            raise Pause("auth", "The Claude tool is no longer signed in. Open a terminal, run “claude auth login”, sign in yourself, then resume.", text[:400])
        if result.get("subtype") == "error_max_turns":
            raise Pause("error", "Claude ran out of steps before finishing this part.", text[:400])
        raise Pause("error", "The Claude tool reported a problem.", (text or str(result.get("subtype")))[:400])
    out = result.get("structured_output")
    if not isinstance(out, dict):
        raise Pause("invalid", "Claude answered, but not in the form Loom asked for.", text[:400])
    models = result.get("modelUsage") or {}
    main = max(models, key=lambda m: (models[m] or {}).get("outputTokens", 0)) if models else (init.get("model") or "")
    return {"output": out, "model": main, "turns": result.get("num_turns"), "seconds": seconds, "trace": trace, "rate": rate,
            "usage": {"input": (result.get("usage") or {}).get("input_tokens"), "output": (result.get("usage") or {}).get("output_tokens")}}


# ---------------------------------------------------------------- checks on what comes back

def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def check_outline(out: dict, brief: dict, plan: dict) -> list:
    p, topics, mode = [], brief.get("topics") or [], brief.get("mode")
    sessions = out.get("sessions") or []
    if len(sessions) != plan["sessions"]:
        p.append(f"The outline has {len(sessions)} sessions. The brief gives exactly {plan['sessions']}.")
    low = {t.lower(): t for t in topics}
    seen = set()
    for i, s in enumerate(sessions):
        n = i + 1
        for k in ("title", "outcome", "serves", "key_task", "evidence_of_learning"):
            if not _txt(s.get(k)):
                p.append(f"Session {n} has no {k.replace('_', ' ')}.")
        st = [low.get(str(t).lower()) for t in s.get("topics") or []]
        if not st or None in st:
            p.append(f"Session {n} must list topics using the exact names from the brief: {', '.join(topics)}.")
            continue
        s["topics"] = list(dict.fromkeys(st))
        seen.update(s["topics"])
        if mode == "separate" and len(s["topics"]) != 1:
            p.append(f"Session {n} combines topics, but the team chose to keep them separate. Give it exactly one topic.")
        if len(s["topics"]) > 1:
            given = {str(c.get("topic", "")).lower() for c in s.get("contributions") or [] if _txt(c.get("gives"))}
            for t in s["topics"]:
                if t.lower() not in given:
                    p.append(f"Session {n} uses {t} but does not say what {t} contributes to the task.")
        for b in s.get("builds_on") or []:
            if not isinstance(b, int) or b < 1 or b >= n:
                p.append(f"Session {n} says it builds on session {b}, which is not an earlier session.")
    for t in topics:
        if t not in seen and len(sessions) == plan["sessions"]:
            p.append(f"No session teaches {t}. Every topic in the brief must be taught.")
    if not _txt(out.get("final_evidence")):
        p.append("The outline does not say what final evidence shows the outcome.")
    return p


def check_activity(a: dict, where: str) -> list:
    p = []
    if not isinstance(a.get("minutes"), int) or a["minutes"] < 1:
        p.append(f"{where} needs a whole number of minutes, 1 or more.")
    rest = a.get("kind") == "break"  # a break needs a name and its minutes, nothing else
    for k in ("title",) if rest else ("title", "goal"):
        if not _txt(a.get(k)):
            p.append(f"{where} has no {k}.")
    if a.get("kind") not in prompts.ACTIVITY_KINDS:
        p.append(f"{where} has an unknown kind.")
    if rest:
        return p
    steps = [s for s in a.get("instructions") or [] if _txt(s)]
    if a.get("kind") != "setup" and len(steps) < 2:
        p.append(f"{where} needs at least two instruction steps a learner can follow.")
    if a.get("kind") in ("try", "make", "apply", "check", "revise") and not [s for s in a.get("success") or [] if _txt(s)]:
        p.append(f"{where} does not say what success looks like in the learner's work.")
    if a.get("kind") != "setup" and not [s for s in a.get("teacher") or [] if _txt(s)]:
        p.append(f"{where} has no guidance for the teacher.")
    return p


def settle_claims(session: dict, source_ids) -> int:
    """Lower a claim from 'fact' where its own record says the source does not state all of it. No request to Claude is needed for that.

    Returns how many were lowered. The claim keeps its sources and says in its note what Loom did.
    """
    strength = source_ids if isinstance(source_ids, dict) else {}
    n = 0
    for c in session.get("claims") or []:
        if not isinstance(c, dict) or c.get("type") != "fact" or not (c.get("sources") or []):
            continue
        thin = c.get("support") in ("partly", "not_from_source") or (strength and all(s in strength for s in c["sources"]) and not any(strength.get(s) == "direct" for s in c["sources"]))
        if thin:
            c["type"] = "hypothesis" if c.get("support") == "not_from_source" else "uncertain"
            c["note"] = (_txt(c.get("note")) + " Loom lowered this from “fact”: the record says the source does not state all of it.").strip()
            n += 1
    return n


def check_session(out: dict, brief: dict, minutes: int, topics: list, source_ids) -> list:
    """source_ids is the set of listed ids, or a mapping from id to how strongly that source supports its claim."""
    p = []
    strength = source_ids if isinstance(source_ids, dict) else {}
    acts = out.get("activities") or []
    # A short session is not a small workshop. A talk, or a session of under 25 minutes, is not made to carry a
    # full feedback-and-revision cycle: it is asked for one idea, one thing people do, and one check.
    short = brief.get("formatKey") == "talk" or (isinstance(minutes, int) and minutes < 25)
    for k in ("title", "outcome", "serves"):
        if not _txt(out.get(k)):
            p.append(f"The session has no {k}.")
    if len(acts) < (2 if short else 3):
        p.append(f"The session needs at least {'two' if short else 'three'} activities.")
    for i, a in enumerate(acts):
        p += check_activity(a, f"Activity {i + 1} (“{_txt(a.get('title'))[:40]}”)")
    total = sum(a.get("minutes") for a in acts if isinstance(a.get("minutes"), int))
    if total != minutes:
        p.append(f"The activities add up to {total} minutes. The session is exactly {minutes} minutes.")
    kinds = [a.get("kind") for a in acts]
    if not short and ("feedback" not in kinds or "revise" not in kinds):
        p.append("The session needs one activity of kind feedback and, after it, one of kind revise.")
    elif "feedback" in kinds and "revise" in kinds and kinds.index("feedback") > len(kinds) - 1 - kinds[::-1].index("revise"):
        p.append("Revision must come after feedback.")
    doing = ("try", "make", "apply") if not short else ("try", "make", "apply", "discuss", "check")
    if not any(a.get("kind") in doing for a in acts):
        p.append("The session needs at least one activity where learners do the task themselves (try, make or apply)."
                 if not short else "Even a short session needs one activity where people do something: try, make, apply, discuss or check.")
    if len([c for c in out.get("success_criteria") or [] if _txt(c)]) < 2:
        p.append("The session needs at least two success criteria that can be checked by looking at the work.")
    ac = out.get("application_check") or {}
    if not _txt(ac.get("task")) or not _txt(ac.get("when")) or not [x for x in ac.get("looks_for") or [] if _txt(x)]:
        p.append("The later application check needs a task, a time and what to look for.")
    prep = out.get("preparation") or {}
    if not isinstance(prep.get("minutes"), int) or prep["minutes"] < 0 or (prep["minutes"] > 0 and not [x for x in prep.get("steps") or [] if _txt(x)]):
        p.append("Say what the teacher prepares before the session and how many minutes it takes.")
    if not (out.get("prerequisites") or []) and not _txt(out.get("prerequisites_note")):
        p.append("Name the prerequisites, or explain in prerequisites_note why there are none.")
    for q in out.get("prerequisites") or []:
        if not _txt(q.get("name")) or not _txt(q.get("support")):
            p.append("Every prerequisite needs a name and the support for a learner who lacks it.")
            break
    given = {str(c.get("topic", "")).lower(): _txt(c.get("gives")) for c in out.get("contributions") or []}
    for t in topics:
        if not given.get(t.lower()):
            p.append(f"Say what {t} contributes in this session.")
    for c in out.get("claims") or []:
        bad = [s for s in c.get("sources") or [] if s not in source_ids]
        if bad:
            p.append(f"A claim cites {', '.join(bad)}, which is not in the list of sources. Cite only listed ids.")
        if c.get("type") == "fact" and not (c.get("sources") or []):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact but cites no source. Cite a listed source, or mark it uncertain or hypothesis.")
        elif c.get("type") == "fact" and c.get("support") in ("partly", "not_from_source"):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact, but you say the source states it only {'in part' if c.get('support') == 'partly' else 'not at all'}. Split off the part the source states, or mark the claim uncertain or hypothesis.")
        elif c.get("type") == "fact" and not bad and strength and not any(strength.get(s) == "direct" for s in c["sources"]):
            p.append(f"“{_txt(c.get('text'))[:60]}” is marked as a fact, but every source it cites is recorded as supporting it only in part. Mark it uncertain, or cite a source that supports it directly.")
    if not (out.get("claims") or []):
        p.append("List the claims these materials rely on, with their type.")
    return p


def check_session_v2(out: dict, brief: dict, minutes: int, topics: list, source_ids, node_ids: dict, in_hand: list, want: dict | None, record: dict | None = None, source_texts: dict | None = None) -> list:
    """The ordinary session checks, and the ones the expanded pipeline adds: what was to be taught, independent time, assets, and running the code.

    `want` is what the approved outline asks of this session: {teaches, independent, projects}. It is None for an edit, which keeps only the checks that do not need it.
    `record` receives what running the assets showed, so that it can be kept whatever the outcome.
    """
    p = check_session(out, brief, minutes, topics, source_ids)
    acts = out.get("activities") or []
    if want is not None:
        missing = [t for t in want.get("teaches") or [] if t not in (out.get("teaches_nodes") or [])]
        if missing:
            p.append("The session must teach, and list under teaches_nodes: " + ", ".join(f"{node_ids.get(t, t)} ({t})" for t in missing) + ".")
        if want.get("teaches") and brief.get("priorKey") != "solid":
            if not any(_txt(a.get("worked_example")) for a in acts):
                p.append("This session teaches something new, so one activity needs a fully worked example, a different case from the learners' own task.")
            if not [m for a in acts for m in a.get("misconceptions") or [] if _txt(m.get("belief"))]:
                p.append("List at least one common error learners make with what is taught here, and how to respond.")
        ind = want.get("independent")
        iw = out.get("independent_work") or {}
        if isinstance(ind, int):
            if iw.get("minutes") != ind:
                p.append(f"independent_work.minutes must be exactly {ind}, as approved. It is not part of the live minutes.")
            tasks = [t for t in iw.get("tasks") or [] if isinstance(t, dict)]
            if ind > 0:
                if not tasks:
                    p.append("The independent work needs at least one task.")
                if sum(t.get("minutes") for t in tasks if isinstance(t.get("minutes"), int)) != ind:
                    p.append(f"The independent tasks add up to {sum(t.get('minutes') for t in tasks if isinstance(t.get('minutes'), int))} minutes. They must add up to {ind}.")
                for t in tasks:
                    if len([x for x in t.get("instructions") or [] if _txt(x)]) < 2 or not [x for x in t.get("self_check") or [] if _txt(x)] or not _txt(t.get("deliverable")):
                        p.append(f"Independent task “{_txt(t.get('title'))[:40]}” needs instructions a learner can follow alone, a way to check one's own work, and what is handed in and how.")
                        break
        for pr in want.get("projects") or []:
            if pr not in [x.get("project") for x in out.get("project_work") or []] and not any(pr in _txt(x.get("project")) for x in out.get("project_work") or []):
                p.append(f"This session carries a milestone of project {pr}. Say what learners do for it in project_work.")
    assets = [a for a in out.get("assets") or [] if isinstance(a, dict)]
    p += pipeline.check_assets(assets, "Assets")
    if not p:
        results = pipeline.run_assets(assets, in_hand) + pipeline.origin_checks(assets, source_texts or {})
        if record is not None:
            record["results"] = results
        p += pipeline.asset_problems(results, "Running the code")
    return p


# Only the test suite sets this, so its checks can reach a server running on this machine. Loom never sets it.
# It widens which addresses may be opened; it does not disable pinning the connection to the checked address.
ALLOW_LOCAL_FETCH = False


def _build_id() -> str:
    """Which build produced a judgement. Imported late: http_api imports this module, so it cannot be imported here."""
    try:
        from .http_api import BUILD
        return BUILD
    except Exception:
        return "unknown"


def _execution_provenance() -> dict:
    """The build that is actually RUNNING, and whether the files on disk have moved on since it started.

    `BUILD` is fixed when the server imports, so it describes the code in memory. Hashing the files again at the
    moment a judgement is made describes something else: what is on disk now, which is what the NEXT start would
    load. Recording only one of them lets a judgement claim a build it was not produced by. Both are kept, and
    where they differ that is said in the record rather than left for someone to work out.
    """
    running = _build_id()
    try:
        from .http_api import build_id
        on_disk = build_id()
    except Exception:
        on_disk = "unknown"
    got = {"build": running, "buildOfFilesOnDiskNow": on_disk, "filesChangedSinceStart": running != on_disk}
    if got["filesChangedSinceStart"]:
        got["note"] = ("The files on disk are not the ones running. This judgement was produced by the running "
                       "build; a restart would load something else.")
    return got


_CLI_VERSION: dict = {}


def cli_version() -> dict:
    """Which build of the Claude tool is actually answering, read once and remembered.

    "The same request under the same settings" is not the same request when a different build of the tool
    answered it. The model name does not carry that: the tool around it changes independently.
    """
    path = cli_path()
    if not path:
        return {"found": False, "version": "", "path": ""}
    if _CLI_VERSION.get("path") == path:
        return _CLI_VERSION
    got = {"found": True, "path": path, "version": ""}
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20,
                           env=clean_env(), cwd=str(work_dir()))
        got["version"] = (r.stdout or r.stderr or "").strip()[:120]
    except Exception as e:
        got["version"] = ""
        got["couldNotRead"] = type(e).__name__
    _CLI_VERSION.clear()
    _CLI_VERSION.update(got)
    return got


def request_settings() -> dict:
    """The execution configuration a judgement was produced under.

    Two runs can be given the same evidence, the same prompt and the same schema and still be different asks: a
    different model answers differently, and so does a different reasoning effort or a shorter turn limit. None of
    this was in the fingerprint, so runs made under different settings compared as identical requests.
    """
    cfg = config()
    cli = cli_version()
    return {"model": cfg.get("model") or "the tool's own default", "effort": cfg.get("effort") or "",
            "testDouble": bool(os.environ.get("LOOM_CLAUDE_BIN")),
            # How the tool was actually invoked, not merely which model was asked for.
            "cliVersion": cli.get("version") or "not recorded",
            "turns": TURNS.get("attribution_review"), "timeoutSeconds": TIMEOUT.get("attribution_review")}


_DECIDABLE = ("yes", "partly", "no", "cannot_tell")


def valid_resolution(dkey: str, r, fingerprint: str | None):
    """A person's decision on one disagreement, or None. Nothing less than a real decision counts.

    A decision names who made it, when, which answer stands, the words in the document that settle it and why.
    It is tied to the evidence it was made on: if the page, the quotation or the retrieved bytes change
    afterwards, the decision was about something else and the question reopens. An answer Loom does not
    recognise is not a decision either, so a typo cannot quietly settle anything.
    """
    if not isinstance(r, dict):
        return None
    if r.get("evidenceFingerprint") != fingerprint:
        return None
    if not all(str(r.get(f) or "").strip() for f in ("by", "at", "chosen", "becauseWords", "reason")):
        return None
    allowed = ("yes", "partly", "no") if dkey == "overall" else _DECIDABLE
    return r if r.get("chosen") in allowed else None


def apply_resolutions(entry: dict, resolutions) -> dict:
    """The judgement as it stands after a person has decided, with what the model said kept beside it.

    A decision used to clear the warning and change nothing else, so choosing "no" removed the sign of trouble
    and left the effective verdict at "yes" — the worst of both, because the claim then looked settled in
    Loom's favour precisely because someone had rejected it. The chosen answer now governs, and the aggregate is
    worked out again from the decided fields rather than left at whatever the model last said.

    This is a pure function of saved data. Recording a decision therefore takes effect at once and never needs
    another model run, which also means a person is never asked to spend a review to register their own answer.
    """
    live = entry.get("unresolvedDisagreements")
    if not isinstance(live, list) or not live or not isinstance(resolutions, dict):
        return entry
    out = dict(entry)
    detail = dict(out.get("detail")) if isinstance(out.get("detail"), dict) else {}
    rels = [dict(r) if isinstance(r, dict) else r for r in detail.get("relationships") or []] \
        if isinstance(detail.get("relationships"), list) else detail.get("relationships")
    still, decided = [], []
    for d in live:
        dkey = d.get("key") if isinstance(d, dict) else None
        r = valid_resolution(str(dkey), resolutions.get(dkey), out.get("fingerprint")) if dkey else None
        # A decision also has to be about THIS version of the question. Where the review has since answered
        # differently again, the two answers a person chose between are no longer the two on the table.
        if r and str(r.get("questionRevision") or "") not in ("", disagreement_revision(out, d)):
            r = None
        if not r:
            still.append(d)
            continue
        chosen = r["chosen"]
        if dkey == "identity":
            detail["identity_correct"] = chosen
        elif dkey == "role":
            detail["role_correct"] = chosen
        elif dkey == "lineage_supported":
            detail["lineage_supported"] = chosen
        elif dkey == "overall":
            out["verdict"] = chosen
        elif isinstance(rels, list):
            for r_ in rels:
                if isinstance(r_, dict) and lineage.disagreement_key(
                        "relationship", r_.get("earlier_work"), r_.get("relation")) == dkey:
                    r_["supported"] = chosen
        decided.append({"about": d.get("aspect"), "key": dkey, "chosen": chosen, "by": r.get("by"),
                        "at": r.get("at"), "becauseWords": r.get("becauseWords"), "reason": r.get("reason"),
                        "theModelHadSaid": {"earlier": d.get("earlier"), "later": d.get("later")}})
    if not decided:
        return entry
    # What the model answered is never overwritten by what a person decided. Both are kept, and which is which
    # is never in doubt.
    out.setdefault("theModelsOwnAnswer", {"verdict": entry.get("verdict"), "detail": entry.get("detail")})
    if isinstance(rels, list):
        detail["relationships"] = rels
    out["detail"] = detail
    out["decidedByAPerson"] = decided
    if not any(x["key"] == "overall" for x in decided):
        # The aggregate is a consequence of identity, role and descent, so it is worked out again rather than
        # left saying "yes" because that is what the model said before anyone looked.
        ident, role = detail.get("identity_correct"), detail.get("role_correct")
        good = ident == "yes" and role == "yes" and detail.get("lineage_supported") in ("yes", "none_claimed")
        out["verdict"] = "yes" if good else "no" if "no" in (ident, role) else "partly"
    if still:
        out["unresolvedDisagreements"] = still
    else:
        out.pop("unresolvedDisagreements", None)
    return out


def disagreement_revision(entry: dict, d: dict) -> str:
    """A name for one open question AS IT STANDS, so a decision can say which version of it was answered.

    A decision is about what a person read on the screen. Without a name for that, a submission written against
    one state of the evidence was accepted and stamped with whatever the evidence had since become — the record
    then said the person had decided something they were never shown.
    """
    return content_print([entry.get("fingerprint"), d.get("key"), d.get("earlier"), d.get("later"),
                          d.get("earlierRunId"), d.get("laterRunId")])


def open_questions(entry: dict) -> list:
    """The open disagreements on one judgement, each with the revision a decision must name."""
    out = []
    for d in entry.get("unresolvedDisagreements") or []:
        if isinstance(d, dict) and d.get("key"):
            out.append(dict(d, revision=disagreement_revision(entry, d)))
    return out


def record_resolution(store, cid: str, claim_key: str, dkey: str, decision: dict) -> dict:
    """Write one person's decision about one disagreement. No model is asked anything.

    Deciding between two answers the review already gave is a judgement about a document a person has read. It
    needs no new review, and spending one would be a third answer rather than a decision about the first two.
    Nothing here touches an outline, an approval or any other stage: it writes one record and stops.

    Reading, checking and writing all happen inside one hold on the course record. Doing them separately is a
    race whenever two people act at once: both read the same state, both find themselves allowed to write, and
    the second silently replaces the first.
    """
    if runner(store, cid).busy():
        raise storage.Conflict("Loom is working on this course. Decisions are not recorded while a job is "
                               "running, so they cannot be overwritten by what it saves.", None)
    want = {k: str(decision.get(k) or "").strip() for k in ("by", "chosen", "becauseWords", "reason")}
    saw_evidence = str(decision.get("sawEvidence") or "").strip()
    saw_revision = str(decision.get("sawRevision") or "").strip()

    def change(rec):
        # Checked inside the hold on the record, where the answer cannot go stale between asking and writing.
        # `busy()` only knows about work started in this process; a record saved as running is the broader
        # signal, and either means a job may be about to save over whatever is written here.
        if rec.get("status") == "running":
            raise storage.Conflict("Loom is working on this course. Decisions are not recorded while a job is "
                                   "running, so they cannot be overwritten by what it saves.", None)
        rs = ((rec.get("stages") or {}).get("research") or {})
        entry = (rs.get("attribution") or {}).get(claim_key)
        if not isinstance(entry, dict):
            raise storage.StoreError("Loom has no attribution judgement for that source.")
        d = next((x for x in open_questions(entry) if x["key"] == dkey), None)
        if d is None:
            raise storage.StoreError("There is no open disagreement about that to decide.")
        if not all(want.values()):
            raise storage.StoreError("A decision needs who made it, which answer stands, the words in the "
                                     "document that settle it, and why.")
        # What the person saw has to match what is here. Either is enough on its own to make the decision one
        # about a different question, so neither may be left out and neither may be stale.
        if not saw_evidence or not saw_revision:
            raise storage.StoreError("The decision did not say which version of the evidence it was made on.")
        if saw_evidence != str(entry.get("fingerprint") or "") or saw_revision != d["revision"]:
            raise storage.Conflict("The evidence or the question changed after this was shown to you. Reload "
                                   "and look again before deciding.", d["revision"])
        now = dict(want, at=storage.now_iso(), evidenceFingerprint=entry.get("fingerprint"),
                   questionRevision=d["revision"])
        if not valid_resolution(dkey, now, entry.get("fingerprint")):
            raise storage.StoreError(f"{want['chosen']!r} is not an answer Loom recognises for that question.")
        held = (rs.get("attributionResolutions") or {}).get(claim_key, {}).get(dkey)
        if isinstance(held, dict) and held.get("chosen"):
            # Replacing someone's decision means naming the one you saw. Two timestamps can be identical to the
            # second, so the id is what identifies a decision, never the time it was made.
            if str(decision.get("replacing") or "") != str(held.get("decisionId") or ""):
                raise storage.Conflict("Someone else has already decided this. Reload to see their decision.",
                                       held.get("decisionId"))
        # Every decision is kept in full, in the order it was made. Keeping only the newest and a shortened
        # note of the one before it threw away the quotations and the reasons that justified the earlier ones,
        # which is the whole record of how a contested claim came to stand where it does.
        events = rs.setdefault("attributionDecisions", [])
        now["decisionId"] = secrets.token_hex(8)
        now["sequence"] = len(events) + 1
        now["claimKey"], now["question"] = claim_key, dkey
        if isinstance(held, dict) and held.get("decisionId"):
            now["replaces"] = held["decisionId"]
        events.append(dict(now))
        rs.setdefault("attributionResolutions", {}).setdefault(claim_key, {})[dkey] = dict(now)
        rec.setdefault("stages", {}).setdefault("research", rs)
        return dict(now)

    got = storage.update_engine(store, cid, change)
    # The decision is written, but what the app SERVES is the saved record, and the saved record still carries
    # the judgement as it stood before. Writing without this left a decision that was real in the file and
    # invisible on the screen until something else happened to re-merge. The merge is done after the write, not
    # inside it, so a failure here cannot lose a decision that is already safely recorded.
    try:
        rec = storage.read_engine(store, cid)
        if isinstance(rec, dict) and ((rec.get("stages") or {}).get("research") or {}).get("batches"):
            runner(store, cid)._merge_research(rec)
            storage.write_engine(store, cid, rec)
    except Exception:
        pass
    return got


def decision_history(rec: dict, claim_key: str | None = None, dkey: str | None = None) -> list:
    """Every decision ever recorded, oldest first. Nothing here is ever rewritten or removed."""
    events = (((rec or {}).get("stages") or {}).get("research") or {}).get("attributionDecisions") or []
    out = [e for e in events if isinstance(e, dict)
           and (claim_key is None or e.get("claimKey") == claim_key)
           and (dkey is None or e.get("question") == dkey)]
    return sorted(out, key=lambda e: e.get("sequence") or 0)


def attribution_material(s: dict, text: str | None = None) -> dict:
    """Exactly what an attribution verdict was judged against, for one source.

    This is now THE SAME representation the reviewer is shown, built once in prompts.attribution_reviewer_input, so
    the two cannot drift apart. They had: `title`, `directHead`, `directExcerpt`, `retrievedExcerpt` and
    `quoteCaseExact` all went into the reviewer's request while being invisible here, so a verdict could stay bound
    to an "unchanged" record although the request behind it had changed — which is exactly how a comparison of two
    runs was read as evidence about the model when the inputs had in fact differed.

    `text` is the document Loom retrieved, needed because the reviewer is shown the passage behind each claimed
    relationship. Every caller must pass the same text it would pass when prompting, or the fingerprint will not
    describe the request. It is per source, so one changed source does not throw away every other verdict, but note
    that the batch request as a whole still changes: `attributionReview.inputFingerprint` records that separately.
    """
    # No override here any more: the one representation normalises the address itself, so the reviewer and the
    # fingerprint cannot see two different spellings of it.
    return prompts.attribution_reviewer_input(s, text)


def _project_assets(u: dict) -> list:
    c = (u.get("content") or {})
    return (c.get("inputs") or []) + (c.get("solution_assets") or [])


DIRECT_BATCH = 10
IDENTITY_BATCH = 8   # retrieved documents read for their identity in one request
# A fetch is worth trying again only when the reason might not hold next time. An address refused for not being
# public, or a page that is simply not there, is not retried: repeating it would change nothing.
_RETRY_STATUS = (None, 408, 425, 429, 500, 502, 503, 504)


def _worth_retrying(v: dict) -> bool:
    if v.get("blocked") or "not on the public internet" in (v.get("note") or "") or "Not a public web address" in (v.get("note") or ""):
        return False
    return v.get("status") in _RETRY_STATUS


def is_public_host(host: str) -> bool:
    """Whether every address this host answers with is on the public internet.

    Retrieval and link checks no longer ask this separately: deciding here and connecting later is the gap that
    let a second lookup return a private address in between. The one safe transport in `evidence` now checks the
    address it is about to open. This is kept for callers that only want the question answered.
    """
    try:
        evidence.global_addresses(host, ALLOW_LOCAL_FETCH)
        return True
    except evidence.Blocked:
        return False


def link_opens(url: str) -> dict:
    """Records only whether the address opened today. It says nothing about whether the page supports a claim.

    This goes through the same safe transport as evidence retrieval, so a redirect cannot carry a link check to a
    private address after only its first host was looked at.
    """
    rec = {"checkedAt": storage.now_iso(), "opened": False, "status": None, "note": ""}
    if os.environ.get("LOOM_SKIP_LINK_CHECK"):
        rec["note"] = "Link check was switched off for this run."
        return rec
    got = evidence.open_public(url, timeout=12, max_bytes=64 * 1024, allow_local=ALLOW_LOCAL_FETCH)
    rec.update(status=got["status"], note=got["note"], opened=bool(got["ok"]))
    if len(got["hops"]) > 1:
        rec["redirectedThrough"] = [h["url"] for h in got["hops"][1:]]
    return rec


def result_text(result: dict) -> str:
    body = result.get("content")
    return body if isinstance(body, str) else " ".join(str(x.get("text", "")) for x in body if isinstance(x, dict)) if isinstance(body, list) else ""


def fetch_outcome(result: dict) -> dict:
    """What happened to one request for a page: retrieved, failed or redirected. Anything unclear counts as not retrieved."""
    text = result_text(result)
    low = text.lower()
    if result.get("is_error"):
        return {"state": "failed", "note": text.strip()[:160]}
    if "redirect detected" in low or "redirected to a different host" in low:
        return {"state": "redirected", "note": "The address led to another site. That page was not read under this address."}
    if len(text.strip()) < 40 or re.match(r"^\s*(error|request failed|failed to fetch|unable to fetch|http (4|5)\d\d)", low):
        return {"state": "failed", "note": text.strip()[:160] or "Nothing came back."}
    return {"state": "retrieved", "note": ""}


FETCH_NOTE = {"failed": "The AI asked for this page during research and it did not open.", "redirected": "The AI asked for this page during research and was sent to another site.",
              "no_result": "The AI asked for this page during research. Loom has no record that it arrived.", "none": "Loom has no record that this page was asked for during research."}


def finish_research(out: dict, trace: dict, cache: dict | None = None, valid_nodes=None, number: bool = True) -> dict:
    """Turn one research answer into records that say what really happened to each page.

    `cache` holds pages retrieved earlier in the same run (address -> {text, at}). A source that cites one of them counts as retrieved,
    and is not asked for again. What a page really returned is kept, in part, with the source, and a quote is checked against it.
    """
    cache = cache if cache is not None else {}
    fetched = {norm_url(u) for u in trace.get("fetched") or []}
    texts = {}
    for f in trace.get("fetches") or []:
        if f.get("state") == "retrieved" and f.get("text"):
            texts[norm_url(f["url"])] = f["text"]
    tried = {}
    for f in trace.get("fetches") or []:
        if tried.get(norm_url(f["url"])) != "retrieved":
            tried[norm_url(f["url"])] = f["state"]
    today = storage.now_iso()
    sources, demoted = [], []
    for s in out.get("sources") or []:
        url = _txt(s.get("url"))
        if not url.lower().startswith(("http://", "https://")) or not _txt(s.get("claim")):
            continue
        key = norm_url(url)
        opened = key in fetched
        reused = not opened and key in cache
        state = "retrieved" if (opened or reused) else tried.get(key, "none")
        text = texts.get(key) or (cache.get(key) or {}).get("text") or ""
        at = today if opened else (cache.get(key) or {}).get("at") if reused else None
        s = dict(s, url=url, retrievedAt=at, askedAt=today, fetch=state, openedByAI=opened or reused, personChecked=None)
        if valid_nodes is not None:
            s["node_ids"] = [n for n in dict.fromkeys(s.get("node_ids") or []) if n in valid_nodes]
        if reused:
            s["reusedFromEarlierInRun"] = True
        if text:
            s["retrievedExcerpt"] = text[:EXCERPT_KEEP]
            s["evidenceLevel"] = "tool_summary"  # what WebFetch returns is a summary produced by the tool, never the original document
            s["quoteFound"] = pipeline.quote_found(s.get("quote") or "", text)
            if s["quoteFound"] is False:
                s["limits"] = (_txt(s.get("limits")) + " The quoted words were not found in what the fetch returned, so the quote is not shown as verified.").strip()
                s["quote"] = ""
                if s.get("strength") == "direct":
                    s["strength"] = "partial"
        else:
            s["quoteFound"] = None
            s["evidenceLevel"] = "none"
        if not (opened or reused):
            # Claude listed it as read, but the page never arrived. It is kept, clearly marked, and cannot back a fact.
            demoted.append(s["title"])
            s["strength"] = "background"
            s["limits"] = (FETCH_NOTE[state] + " " + _txt(s.get("limits"))).strip()
        sources.append(s)
    if number:
        for i, s in enumerate(sources):
            s["id"] = f"S{i + 1}"
            s["link"] = link_opens(s["url"])
    for u, t in texts.items():
        cache[u] = {"url": u, "text": t[:CACHE_KEEP], "at": today}
    slim_trace = [{k: v for k, v in f.items() if k != "text"} for f in trace.get("fetches") or []]
    return dict(out, sources=sources, searches=trace.get("searches") or [], pagesOpened=trace.get("fetched") or [], pagesAskedFor=slim_trace, researchedAt=today, unconfirmedReads=demoted)


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def date_on_page(dated: str, text: str) -> bool | None:
    """Does the date the AI gave appear in what the page really returned? None when nothing came back to look in.

    This checks that the date is on the page. It cannot show that the page supports a claim of popularity, or that the date is recent.
    """
    if not text:
        return None
    low, want = text.lower(), str(dated or "").lower()
    years = re.findall(r"\b(?:19|20)\d{2}\b", want)
    if not years:
        return False
    if not all(y in low for y in years):
        return False
    months = [m for m in MONTHS if m in want or m[:3] + " " in want.replace(".", " ")]
    return all(m in low or m[:3] in low for m in months)


def finish_ideas(out: dict, trace: dict, kind: str, hint: str) -> dict:
    """Only evidence from pages that actually arrived, and only with a date that is on the page, may back a suggestion. The rest is kept and named."""
    fetched = {norm_url(u) for u in trace.get("fetched") or []}
    texts = {norm_url(f["url"]): f["text"] for f in trace.get("fetches") or [] if f.get("state") == "retrieved" and f.get("text")}
    today = storage.now_iso()
    ideas, dropped = [], []
    for it in out.get("ideas") or []:
        if not _txt(it.get("idea")):
            continue
        ev, weak = [], []
        for e in it.get("evidence") or []:
            url = _txt(e.get("url"))
            if not url.lower().startswith(("http://", "https://")):
                continue
            opened, dated = norm_url(url) in fetched, _txt(e.get("dated"))
            text = texts.get(norm_url(url)) or ""
            on_page = date_on_page(dated, text) if dated else False
            e = dict(e, url=url, openedByAI=opened, dated=dated, dateOnPage=on_page, retrievedExcerpt=text[:600])
            (ev if opened and dated and on_page is not False else weak).append(e)
        ideas.append(dict(it, evidence=ev, unconfirmed=weak, backed=bool(ev)))
        if not ev:
            dropped.append(_txt(it.get("idea")))
    backed = [i for i in ideas if i["backed"]]
    # Only a date belongs in searchedOn; anything else the model wrote there is kept as its own note.
    said = _txt(out.get("searched_on"))
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", said)
    return {"kind": kind, "hint": hint, "status": "done", "askedAt": today, "finishedAt": today, "searchedOn": m.group(1) if m else today[:10], "searchNote": said if not m or len(said) > 10 else "",
            "ideas": ideas, "backedCount": len(backed), "shortfall": _txt(out.get("shortfall")), "unbacked": dropped,
            "notOpened": [n for n in (out.get("not_opened") or []) if _txt(n.get("url"))], "searches": trace.get("searches") or [], "pagesOpened": trace.get("fetched") or []}


def blank_ideas() -> dict:
    """A record with nothing in it but room for receipts, for a course that has only asked for topic ideas so far."""
    return {"version": 1, "brief": {}, "plan": {"sessions": 0, "minutes": [], "unit": "Block", "total": 0}, "briefDigest": "", "status": "idle", "pause": None, "now": None, "startedAt": storage.now_iso(),
            "stages": {"research": {"status": "todo"}, "outline": {"status": "todo", "approved": False}, "materials": {"status": "todo", "sessions": []}, "review": {"status": "todo"}},
            "edits": {}, "calls": [], "ideasOnly": True}


# ---------------------------------------------------------------- the work itself

def blank(brief: dict, plan: dict, digest: str, pipeline_version: int = 1) -> dict:
    if pipeline_version == 2:
        rec = blank(brief, plan, digest)
        rec["pipeline"] = 2
        rec["policy"] = pipeline.project_policy(plan)
        rec["accounting"] = pipeline.accounting(plan)
        rec["stages"].update({"map": {"status": "todo"}, "foundation_review": {"status": "todo"}, "source_review": {"status": "todo"}, "outline_review": {"status": "todo"}, "projects": {"status": "todo", "units": []}})
        return rec
    return {"version": 1, "brief": brief, "plan": plan, "briefDigest": digest, "status": "idle", "pause": None, "now": None, "startedAt": storage.now_iso(),
            "stages": {"research": {"status": "todo"}, "outline": {"status": "todo", "approved": False},
                       "materials": {"status": "todo", "sessions": [{"status": "todo"} for _ in range(plan["sessions"])]},
                       "review": {"status": "todo"}},
            "edits": {}, "calls": []}


def _named_work_records(named: dict) -> list:
    """The works Loom fetched because a relationship named them, as records the lineage graph can hold.

    One per identifier, never a claim record. A work that could not be fetched is still recorded, so the graph can
    say the far end was looked for and name why it is not there.
    """
    out = []
    for ident, w in sorted((named or {}).items()):
        if not isinstance(w, dict):
            continue
        idy = w.get("identityRead") or {}
        ok = bool(w.get("ok") and w.get("sha256"))
        # The work is the one that was named and fetched, so the identifier it was fetched by decides which work
        # this is. Where the document reports a different one that is a discrepancy worth seeing, not a reason to
        # quietly become a different work than the relationship pointed at.
        in_doc = lineage._norm_identifier(idy.get("identifier"))
        rec_ = {"id": "NAMED:" + ident, "url": w.get("finalUrl") or w.get("url"),
                    "title": idy.get("titleAsPublished") or None, "authors": idy.get("authors") or [],
                    "published": idy.get("published"), "version_or_edition": idy.get("version_or_edition"),
                    "identifier": ident, "role": idy.get("role") or "secondary_aid",
                    "evidenceLevel": "direct_text" if ok else "none",
                    "directRetrieval": {"sha256": w.get("sha256"), "quoteVerbatim": None} if ok else {},
                    "namedEndpoint": {"identifier": ident, "kind": w.get("kind"), "fetched": ok,
                                      "namedBy": w.get("namedBy") or [], "note": w.get("note"),
                                      "status": w.get("status"), "retrievedAt": w.get("retrievedAt")},
                    "lineage": []}
        if in_doc and in_doc != lineage._norm_identifier(ident):
            rec_["identifierInTheDocument"] = idy.get("identifier")
            rec_["namedEndpoint"]["identifierDiffersFromTheDocument"] = idy.get("identifier")
        out.append(rec_)
    return out


class Runner:
    def __init__(self, store, cid: str):
        self.store, self.cid = store, cid
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.lock = threading.Lock()

    # -- record helpers
    def load(self) -> dict | None:
        return storage.read_engine(self.store, self.cid)

    def save(self, rec: dict) -> None:
        storage.write_engine(self.store, self.cid, rec)

    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def call(self, rec: dict, stage: str, unit: str, label: str, prompt: str, schema: dict, tools: str = "", check=None) -> dict:
        """Run one request, with one repair attempt if Loom's own checks fail. Every attempt leaves a receipt."""
        rec["now"] = {"stage": stage, "unit": unit, "label": label, "startedAt": storage.now_iso(), "steps": []}
        rec["status"] = "running"
        self.save(rec)

        def on_event(ev):
            rec["now"]["steps"].append(ev)
            del rec["now"]["steps"][:-30]
            self.save(rec)

        attempt, problems, last = 0, [], None
        while attempt < 2:
            attempt += 1
            receipt = {"stage": stage, "unit": unit, "attempt": attempt, "startedAt": storage.now_iso()}
            try:
                r = run_cli(stage, prompt if attempt == 1 else prompts.repair(prompt, last, problems), schema, tools, on_event, self.stop)
            except Pause as p:
                receipt.update(ok=False, finishedAt=storage.now_iso(), error={"kind": p.kind, "reason": p.reason})
                rec["calls"].append(receipt)
                raise
            receipt.update(ok=True, finishedAt=storage.now_iso(), model=r["model"], seconds=r["seconds"], turns=r["turns"], usage=r["usage"], opened=len(r["trace"]["fetched"]), askedFor=len(r["trace"]["fetches"]), searched=len(r["trace"]["searches"]))
            last = r["output"]
            problems = check(last) if check else []
            receipt["problems"] = problems
            rec["calls"].append(receipt)
            if not problems:
                return r
            self.save(rec)
        raise Pause("invalid", "Claude's answer did not pass Loom's checks, even after one correction. Nothing was filled in for it.", " | ".join(problems[:6]))

    @staticmethod
    def written(rec: dict, before: int | None = None) -> list:
        """Sessions as they are written now. The team's own draft, when the page sent it, comes before what Claude first wrote."""
        draft = rec.get("draft") or {}
        out = []
        for i, u in enumerate(rec["stages"]["materials"]["sessions"]):
            if before is not None and i >= before:
                break
            content = draft.get(str(i + 1)) or (u.get("output") if u.get("status") == "done" else None)
            if isinstance(content, dict):
                out.append({"number": i + 1, "content": content})
        return out

    # -- stages
    def do_research(self, rec: dict) -> None:
        st = rec["stages"]["research"]
        st.update(status="running", startedAt=storage.now_iso())
        p, schema = prompts.research(rec["brief"])
        r = self.call(rec, "research", "research", "Looking for sources", p, schema, tools="WebSearch,WebFetch")
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=finish_research(r["output"], r["trace"]))
        self.save(rec)

    def do_outline(self, rec: dict, feedback: str | None = None) -> None:
        st = rec["stages"]["outline"]
        previous = st.get("output")
        st.update(status="running", startedAt=storage.now_iso(), approved=False)
        p, schema = prompts.outline(rec["brief"], rec["plan"], rec["stages"]["research"].get("output"), feedback, previous)
        r = self.call(rec, "outline", "outline", "Proposing an outline", p, schema, check=lambda o: check_outline(o, rec["brief"], rec["plan"]))
        if feedback:
            st.setdefault("feedback", []).append({"at": storage.now_iso(), "text": feedback})
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"])
        self.save(rec)

    @staticmethod
    def source_texts(rec: dict) -> dict:
        """What each listed source really returned, by source id, for checking a dataset against the page it says it came from."""
        cache = rec["stages"]["research"].get("cache") or {}
        out = {}
        for s in ((rec["stages"]["research"].get("output") or {}).get("sources")) or []:
            if s.get("fetch") == "retrieved":
                out[s["id"]] = (cache.get(norm_url(s["url"])) or {}).get("text") or s.get("retrievedExcerpt") or ""
        return out

    def do_materials(self, rec: dict, only: int | None = None) -> None:
        ms = rec["stages"]["materials"]
        outline_out = rec["stages"]["outline"]["approved_outline"]
        research_out = rec["stages"]["research"].get("output")
        ids = {s["id"]: s.get("strength") for s in (research_out or {}).get("sources") or []}
        v2 = self.v2(rec)
        m = (rec["stages"]["outline"].get("approved_map") or rec["stages"]["map"].get("output")) if v2 else None
        node_names = {n["id"]: n["name"] for n in (m or {}).get("nodes") or []}
        ms["status"] = "running"
        for i, unit in enumerate(ms["sessions"]):
            if (only is not None and i != only) or (only is None and unit.get("status") == "done"):
                continue
            unit.update(status="running", startedAt=storage.now_iso(), problems=[])
            self.save(rec)
            topics = outline_out["sessions"][i].get("topics") or rec["brief"].get("topics") or []
            minutes = rec["plan"]["minutes"][i]
            written = self.written(rec, before=i)
            if v2:
                osn = outline_out["sessions"][i]
                hosted = [x for x in outline_out.get("projects") or [] if i + 1 in (x.get("hosted_in_sessions") or [])]
                in_hand = prepared_assets(self.store, self.cid, rec) + [a for w in written for a in w["content"].get("assets") or []]
                want = {"teaches": osn.get("teaches") or [], "independent": (osn.get("independent_work") or {}).get("minutes") if rec["plan"].get("independent") else 0, "projects": [x.get("id") for x in hosted]}
                p, schema = prompts.materials2(rec["brief"], rec["plan"], m, research_out, outline_out, i, written,
                                               [{"id": x.get("id"), "kind": x.get("kind"), "title": x.get("title"), "milestones_in_this_session": [q for q in x.get("milestones") or [] if q.get("session") == i + 1], "deliverable": x.get("deliverable")} for x in hosted], in_hand, rec["policy"])
                record = unit.setdefault("assetRun", {})
                stx = self.source_texts(rec)
                check = lambda o, mi=minutes, t=topics, w=want, ih=in_hand, rc=record: (settle_claims(o, ids), check_session_v2(o, rec["brief"], mi, t, ids, node_names, ih, w, rc, stx))[1]
            else:
                p, schema = prompts.materials(rec["brief"], rec["plan"], research_out, outline_out, i, written)
                check = lambda o, m_=minutes, t=topics: (settle_claims(o, ids), check_session(o, rec["brief"], m_, t, ids))[1]
            try:
                r = self.call(rec, "materials", f"session-{i + 1}", f"Writing session {i + 1} of {len(ms['sessions'])}", p, schema, check=check)
            except Pause as pz:
                unit.update(status="failed" if pz.kind == "invalid" else "todo", reason=pz.reason, detail=pz.detail)
                self.save(rec)
                raise
            unit.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"])
            if v2:
                unit["assetChecks"] = (unit.get("assetRun") or {}).get("results") or []
                unit.pop("assetRun", None)
            unit.pop("reason", None)
            unit.pop("detail", None)
            self.save(rec)  # saved as soon as each session is finished
        ms["status"] = "done" if all(u.get("status") == "done" for u in ms["sessions"]) else "todo"
        self.save(rec)

    def do_ideas(self, rec: dict, payload: dict) -> None:
        kind = "next" if payload.get("kind") == "next" else "trending"
        hint = _txt(payload.get("hint"))[:200]
        storage.write_ideas(self.store, self.cid, {"kind": kind, "hint": hint, "status": "running", "askedAt": storage.now_iso()})
        p, schema = prompts.ideas(kind, hint, storage.now_iso()[:10])
        r = self.call(rec, "ideas", "ideas", "Researching topics", p, schema, tools="WebSearch,WebFetch")
        storage.write_ideas(self.store, self.cid, finish_ideas(r["output"], r["trace"], kind, hint))

    def do_review(self, rec: dict, sessions: list | None = None, projects: list | None = None) -> None:
        """Review exactly the material that was submitted, even across a pause and a resume.

        The material is written into the record when the request is made, so a resume never falls back to what Claude
        first generated. The result is bound to that request, and carries a fingerprint of the material it judged,
        so nothing downstream has to guess whether a review belongs to the draft in front of the team.
        In the expanded pipeline the material is the sessions and the projects together.
        """
        st = rec["stages"]["review"]
        v2 = self.v2(rec)
        if sessions is None:
            sessions = st.get("input")
            if v2 and isinstance(sessions, dict):
                sessions, projects = sessions.get("sessions"), sessions.get("projects")
        if sessions is None:
            # No material was submitted with the request: this is the review that follows generation.
            sessions = [dict(u["output"], number=i + 1, minutes=rec["plan"]["minutes"][i]) for i, u in enumerate(rec["stages"]["materials"]["sessions"]) if u.get("status") == "done"]
            projects = [dict(u["output"], id=u["outline"]["id"]) for u in rec["stages"]["projects"]["units"] if u.get("status") == "done"] if v2 else None
            material = {"sessions": sessions, "projects": projects} if v2 and projects else sessions
            st["input"] = material
            st["inputOrigin"] = "generated"
            st["inputFingerprint"] = content_print(material)
            st.setdefault("requestId", secrets.token_hex(8))
        st.update(status="running", startedAt=storage.now_iso())
        self.save(rec)  # the material under review is on disk before the request goes out
        outline_for = rec["stages"]["outline"].get("approved_outline") or rec["stages"]["outline"].get("output")
        if v2:
            m = rec["stages"]["outline"].get("approved_map") or rec["stages"]["map"]["output"]
            checks = [dict(where=f"session {i + 1}", **c) for i, u in enumerate(rec["stages"]["materials"]["sessions"])
                      for c in pipeline.checks_for(((u.get("output") or {}).get("assets")) or [], u.get("assetChecks") or [])] \
                + [dict(where=f"project {u['outline']['id']}", **c) for u in rec["stages"]["projects"]["units"]
                   for c in pipeline.checks_for(_project_assets(u), u.get("assetChecks") or [])]
            slim_checks = [{k: c.get(k) for k in ("where", "name", "kind", "level", "reason", "output")} for c in checks]
            p, schema = prompts.review2(rec["brief"], rec["plan"], m, rec["stages"]["research"].get("output"), outline_for, sessions, projects or [], slim_checks, self.agent_findings_digest(rec))
            r = self.call(rec, "review", "review", "An independent review of the finished course", p, schema)
        else:
            p, schema = prompts.review(rec["brief"], rec["plan"], rec["stages"]["research"].get("output"), outline_for, sessions)
            r = self.call(rec, "review", "review", "An independent review", p, schema)
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"], reviewed=len(sessions),
                  requestId=st.get("requestId"), inputFingerprint=st.get("inputFingerprint"), inputOrigin=st.get("inputOrigin"))
        self.save(rec)

    def do_edit(self, rec: dict, edit_id: str) -> None:
        e = rec["edits"][edit_id]
        research_out = rec["stages"]["research"].get("output")
        ids = {s["id"]: s.get("strength") for s in (research_out or {}).get("sources") or []}
        e["status"] = "running"
        for part in e["parts"]:
            if part.get("status") == "done":
                continue
            part["status"] = "running"
            self.save(rec)
            p, schema = prompts.edit(rec["brief"], rec["plan"], research_out, e["scope"], e["instruction"], part["number"], part["minutes"], part["content"], part.get("activity"),
                                     e.get("others") or [], part.get("buildsOn"), v2=self.v2(rec))

            def check(o, part=part):
                if not o.get("acted"):
                    return []
                if e["scope"] == "activity":
                    return check_activity(o.get("activity") or {}, "The activity")
                new_total = sum(a.get("minutes") for a in (o.get("session") or {}).get("activities") or [] if isinstance(a.get("minutes"), int))
                settle_claims(o.get("session") or {}, ids)
                if self.v2(rec):
                    in_hand = [a for w in (e.get("others") or []) for a in (w.get("content") or {}).get("assets") or []]
                    got: dict = {}
                    probs = check_session_v2(o.get("session") or {}, rec["brief"], new_total if e.get("aboutTime") else part["minutes"], part.get("topics") or [], ids, {}, in_hand, None, got, self.source_texts(rec))
                    # The edited files were just run. Keep THOSE results: throwing them away left the old ones
                    # standing, so a changed program could still show an earlier pass.
                    part["assetChecks"] = got.get("results") or []
                    return probs
                return check_session(o.get("session") or {}, rec["brief"], new_total if e.get("aboutTime") else part["minutes"], part.get("topics") or [], ids)

            r = self.call(rec, "edit", f"edit-{edit_id}-{part['number']}", f"Working on your change to session {part['number']}", p, schema, check=check)
            part.update(status="done", output=r["output"], model=r["model"])
            self.save(rec)
        e.update(status="done", finishedAt=storage.now_iso())
        self.save(rec)

    # -- the expanded pipeline (version 2). Each step is its own request with its own role, saved when it finishes.
    def v2(self, rec: dict) -> bool:
        return rec.get("pipeline") == 2

    def do_map(self, rec: dict) -> None:
        st = rec["stages"]["map"]
        if st.get("status") == "done":
            return
        st.update(status="running", startedAt=storage.now_iso())
        p, schema = prompts.topic_map(rec["brief"], rec["plan"], rec["policy"], rec["accounting"])
        r = self.call(rec, "map", "map", "Mapping topics and foundations", p, schema, check=lambda o: pipeline.check_map(o, rec["brief"]))
        m = pipeline.derive_map(r["output"])
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=m, fingerprint=content_print(m["nodes"]))
        self.save(rec)

    def do_foundation_review(self, rec: dict) -> None:
        st = rec["stages"]["foundation_review"]
        if st.get("status") == "done":
            if st.get("rejectedAdditions"):
                self._apply_foundation_additions(rec)
                self.save(rec)
            return
        mp = rec["stages"]["map"]
        material = prompts.map_digest(mp["output"])
        st.update(status="running", startedAt=storage.now_iso(), requestId=secrets.token_hex(8), inputFingerprint=content_print(material))
        p, schema = prompts.foundation_review(rec["brief"], rec["plan"], mp["output"])
        r = self.call(rec, "foundation_review", "foundation_review", "A separate check of foundations and order", p, schema)
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"])
        self._apply_foundation_additions(rec)
        self.save(rec)

    def _apply_foundation_additions(self, rec: dict) -> None:
        """Add what the foundations reviewer said was missing. Kept apart so that a saved review can be applied again after a rule improves."""
        st, mp = rec["stages"]["foundation_review"], rec["stages"]["map"]
        adds = [a for a in (st.get("output") or {}).get("missing_foundations") or [] if _txt(a.get("name"))][:8]
        have = {pipeline.norm(n.get("name")) for n in mp["output"]["nodes"]}
        pending = [a for a in adds if pipeline.norm(a["name"]) not in have]
        st["addedNodes"] = [n["name"] for n in mp["output"]["nodes"] if n.get("addedBy")]
        st["rejectedAdditions"] = []
        st.pop("rejectedBecause", None)
        if pending:
            grown, names = pipeline.add_nodes(mp["output"], pending, "foundation review")
            bad = pipeline.check_map(grown, rec["brief"]) if names else []
            if names and not bad:
                mp["output"] = pipeline.derive_map(grown)
                mp["fingerprint"] = content_print(mp["output"]["nodes"])
                mp["revisedByReview"] = names
                st["addedNodes"] = st["addedNodes"] + names
            elif names:
                st["rejectedAdditions"] = names
                st["rejectedBecause"] = bad[:4]
        st["appliedToFingerprint"] = mp.get("fingerprint")

    def _research_batch(self, rec: dict, b: dict, cache: dict, valid: set, label: str, extra_questions: list | None = None) -> None:
        digest = [{"url": c["url"], "retrievedAt": c["at"], "starts": c["text"][:300]} for c in cache.values()][:30]
        p, schema = prompts.research_nodes(rec["brief"], rec["stages"]["map"]["output"], b["nodes"], digest, b["key"])
        if extra_questions:
            p += "\n\n" + prompts.block("questions_from_the_source_reviewer", extra_questions) + "\nAnswer these questions specifically. They come from a reviewer who found a gap."
        r = self.call(rec, "research", f"research-{b['key']}", label, p, schema, tools="WebSearch,WebFetch")
        b["output"] = finish_research(r["output"], r["trace"], cache, valid, number=False)
        b.update(status="done", finishedAt=storage.now_iso(), model=r["model"])

    def _merge_research(self, rec: dict) -> None:
        st = rec["stages"]["research"]
        merged = pipeline.merge_research([b["output"] for b in st["batches"] if b.get("status") == "done" and b.get("output")])
        links = st.setdefault("links", {})
        for s_ in merged["sources"]:
            k = norm_url(s_["url"])
            if k not in links:
                links[k] = link_opens(s_["url"])
            s_["link"] = links[k]
        verdicts = st.get("verdicts") or {}
        audited = bool((rec["stages"].get("source_review") or {}).get("rounds"))
        per_url: dict = {}
        for s_ in merged["sources"]:
            per_url[norm_url(s_["url"])] = per_url.get(norm_url(s_["url"]), 0) + 1
        for i, s_ in enumerate(merged["sources"]):
            # A verdict saved by an earlier build was kept by address alone. It still belongs to a source that is the only claim on its page;
            # where a page carries several claims it cannot be told which the verdict meant, so those are left unjudged and are audited again.
            v = verdicts.get(pipeline.claim_key(s_)) or (verdicts.get(norm_url(s_["url"])) if per_url.get(norm_url(s_["url"])) == 1 else None)
            if v:
                merged["sources"][i] = dict(pipeline.source_effect(s_, v["supports_claim"]), sourceReview=v)
            elif audited and s_.get("fetch") == "retrieved":
                # The audit did not judge this claim on this page. That is unresolved, never support.
                merged["sources"][i] = dict(pipeline.source_effect(s_, None), sourceReview={"supports_claim": "not_judged", "reason": "The source audit did not return a verdict for this claim.", "by": "source_review"})
        direct, attrib = st.get("direct") or {}, st.get("attribution") or {}
        ident = st.get("identity") or {}
        for i, s_ in enumerate(merged["sources"]):
            k = pipeline.claim_key(s_)
            if k in direct:
                merged["sources"][i] = evidence.upgrade(merged["sources"][i], direct[k])
            # Identity read out of the document itself, applied only while it still matches the bytes it was read
            # from. A record that already carries its own identity from research is not overwritten.
            idy = ident.get(norm_url(s_["url"]))
            if idy and idy.get("sha256") and idy["sha256"] == ((merged["sources"][i].get("directRetrieval") or {}).get("sha256")):
                cur = merged["sources"][i]
                for field, key in (("authors", "authors"), ("published", "published"),
                                   ("version_or_edition", "version_or_edition"), ("identifier", "identifier"), ("role", "role")):
                    if not cur.get(field) and idy.get(key):
                        cur[field] = idy[key]
                cur["identityRead"] = {k2: idy.get(k2) for k2 in ("wordsThatShowIt", "unknown", "note", "titleAsPublished", "readAt", "sha256", "inspected")}
                # The document's own title decides. Two acceptance records carried a title belonging to a
                # different paper, and one an invented descriptive title; both pages state their real title
                # plainly. What was on record is kept beside it rather than thrown away.
                published_title = _txt(idy.get("titleAsPublished"))
                overlap = _title_overlap(published_title, cur.get("title")) if published_title else None
                if overlap is not None and overlap < TITLE_DIFFERENT:
                    cur["titleOnRecord"] = cur.get("title")
                    cur["title"] = published_title
                    cur["titleCorrectedFromTheDocument"] = True
                elif overlap is not None and overlap < TITLE_SAME:
                    # A paraphrase, not obviously another work. Loom does not rewrite it and does not hide it:
                    # the document's own title is shown beside the recorded one for a person to judge.
                    cur["titleDiffersFromTheDocument"] = published_title
        # Relationships read from the documents are attached BEFORE the graph is built. Building first and
        # attaching afterwards left every edge out of the graph, however many relationships had been read.
        # They are also attached before attribution is checked below: a relationship is part of what an
        # attribution verdict was judged against, so attaching one after the check let a verdict made without
        # it survive as though it still applied.
        lin_read = st.get("lineageRead") or {}
        for i, s_ in enumerate(merged["sources"]):
            lr = lin_read.get(norm_url(s_["url"]))
            if lr and lr.get("sha256") and lr["sha256"] == ((s_.get("directRetrieval") or {}).get("sha256")):
                if lr.get("relationships") and not s_.get("lineage"):
                    s_["lineage"] = lr["relationships"]
                s_["lineageRead"] = {k2: lr.get(k2) for k2 in ("originOfItsOwnSubject", "note", "readAt", "sha256", "inspected", "notFoundHere")}
        # Identity, quotation, bytes and relationships are all final by here, so each saved attribution verdict is
        # measured against the record as it now stands. Whether a source may be called an original follows from the
        # verdict that survives that check, never from one made on evidence that has since changed.
        for i, s_ in enumerate(merged["sources"]):
            ck = pipeline.claim_key(s_)
            av = dict(attrib.get(ck) or {})
            if av:
                now_print = content_print(attribution_material(merged["sources"][i], (direct.get(ck) or {}).get("text")))
                if av.get("fingerprint") and av["fingerprint"] != now_print:
                    # The identity, the quotation, the retrieved bytes or the relationships have changed since this was judged.
                    av = {"verdict": "stale", "supersededFingerprint": av.get("fingerprint"), "fingerprint": now_print,
                          "reason": "The evidence this judgement was made on has changed, so it no longer applies.",
                          "detail": av.get("detail"), "at": av.get("at")}
            # A person's decisions are applied HERE, on the way out, not during a review run. Applying them only
            # inside the reviewer meant a decision did nothing until somebody spent another model call, which is
            # both a waste and a trap: the screen would keep showing a conflict that had already been settled.
            if av:
                av = apply_resolutions(av, (st.get("attributionResolutions") or {}).get(ck))
                # Each open question travels with the name of its current version, so whatever is shown can be
                # answered against exactly that and nothing else.
                if av.get("unresolvedDisagreements"):
                    av = dict(av, unresolvedDisagreements=open_questions(av))
            merged["sources"][i]["attribution"] = av or None
            # The claim key is what a decision is filed under, so the screen that offers the decision needs it.
            merged["sources"][i]["claimKey"] = ck
            merged["sources"][i]["originalSource"] = evidence.original_status(merged["sources"][i], av.get("verdict") if av else None)
        # Works and how they descend are worked out from the finished source records, so re-running research or a
        # changed verdict is reflected rather than left behind in a saved sentence.
        texts = {s_["id"]: (direct.get(pipeline.claim_key(s_)) or {}).get("text") for s_ in merged["sources"] if s_.get("id")}
        # Works fetched because a relationship named them are works Loom holds, so they go into the graph beside
        # the sources and give the relationships that named them their other end. They are NOT claim records: they
        # carry no claim, they are not counted as sources, and no attribution review has judged them, so they
        # cannot be called an established origin on the strength of having been fetched.
        merged["namedWorks"] = named = _named_work_records(st.get("namedWorks") or {})
        merged["lineage"] = lineage.build(merged["sources"] + named, {k: v for k, v in texts.items() if v})
        merged["lineageChains"] = lineage.chains(merged["lineage"])
        m = rec["stages"]["map"]["output"]
        have = {f.get("node") for f in merged["node_findings"]}
        for nid in st.get("notResearched") or []:
            if nid not in have:
                merged["node_findings"].append({"node": nid, "status": "none_found", "summary": "Not researched: this run researches a limited number of topics.", "limits": "No source was looked for."})

        def standing(n):
            """What a topic really has.

            Only a source Loom retrieved ITSELF counts. `fetch == "retrieved"` means the model's own fetch tool
            returned something, which is a summary of a page and not the page; fifteen records on the acceptance
            course say "retrieved" while Loom holds no text from them at all. A topic resting on those is not
            supported, and full support needs the quotation found in the retrieved text word for word.
            """
            mine = [s_ for s_ in merged["sources"] if n["id"] in (s_.get("node_ids") or [])
                    and s_.get("evidenceLevel") in ("direct_text", "direct_text_quote_found")]
            audited_ = bool((rec["stages"].get("source_review") or {}).get("rounds"))
            strong = [s_ for s_ in mine if s_.get("strength") == "direct" and s_.get("evidenceLevel") == "direct_text_quote_found"
                      and not s_.get("auditUnresolved") and ((s_.get("sourceReview") or {}).get("supports_claim") == "yes" or not audited_)]
            weak = [s_ for s_ in mine if s_.get("strength") in ("direct", "partial") and (s_.get("sourceReview") or {}).get("supports_claim") not in ("no",)
                    # Retrieved page furniture with no quotation matched in it is not support for anything.
                    and not ((s_.get("directRetrieval") or {}).get("textMostlyShortLines") and not (s_.get("directRetrieval") or {}).get("quoteVerbatim"))]
            told = next((f["status"] for f in merged["node_findings"] if f.get("node") == n["id"]), "none_found")
            got = "supported" if strong else "partly" if weak else "none_found"
            rank = {"supported": 2, "partly": 1, "none_found": 0}
            return got if rank[got] <= rank.get(told, 0) else told
        merged.update(researchedAt=storage.now_iso(), unconfirmedReads=[s_["title"] for s_ in merged["sources"] if s_.get("fetch") != "retrieved"],
                      nodeCoverage=[{"node": n["id"], "name": n["name"], "role": n["role"], "sources": [s_["id"] for s_ in merged["sources"] if n["id"] in (s_.get("node_ids") or [])],
                                    "status": standing(n) if n.get("needs_evidence", True) else "not_needed"}
                                   for n in m["nodes"] if n.get("role") in ("required", "optional")])
        st["output"] = merged

    def do_research2(self, rec: dict) -> None:
        st = rec["stages"]["research"]
        if st.get("status") == "done":
            return
        m = rec["stages"]["map"]["output"]
        st.update(status="running", startedAt=storage.now_iso())
        batches, left = pipeline.plan_batches(m)
        if not st.get("batches"):
            st["batches"] = [dict(b, status="todo") for b in batches]
            st["cache"] = {}
            st["verdicts"] = {}
        else:
            # The map grew after research was planned (a reviewer's additions, a better rule): whatever it now holds that no search covers gets its own.
            have = {n for b in st["batches"] for n in b["nodes"]}
            extra = [n for b in batches[1:] for n in b["nodes"] if n not in have]
            for i in range(0, len(extra), pipeline.BATCH_SIZE):
                st["batches"].append({"key": f"nodes-more-{len(st['batches'])}", "nodes": extra[i:i + pipeline.BATCH_SIZE], "status": "todo"})
        st["notResearchedNames"] = left
        st["notResearched"] = [n["id"] for n in m["nodes"] if n["name"] in left]
        valid = {n["id"] for n in m["nodes"]}
        labels = {"approach": "Researching how to teach this"}
        for b in st["batches"]:
            if b.get("status") == "done":
                continue
            b["status"] = "running"
            self.save(rec)
            names = ", ".join(n["name"] for n in m["nodes"] if n["id"] in b["nodes"])
            self._research_batch(rec, b, st["cache"], valid, labels.get(b["key"]) or f"Researching {names}"[:80], b.get("questions"))
            self._merge_research(rec)
            self.save(rec)
        self._merge_research(rec)
        st.update(status="done", finishedAt=storage.now_iso(), model=(st["batches"][-1].get("model") if st["batches"] else ""))
        self.save(rec)

    def do_source_review(self, rec: dict) -> None:
        st = rec["stages"]["source_review"]
        if st.get("status") == "done":
            return
        rs = rec["stages"]["research"]
        st.setdefault("rounds", [])
        st["status"] = "running"
        # A targeted search that was stopped half way is finished before anything is judged again.
        valid = {n["id"] for n in rec["stages"]["map"]["output"]["nodes"]}
        for b in rs["batches"]:
            if b.get("status") != "done":
                b["status"] = "running"
                self.save(rec)
                self._research_batch(rec, b, rs["cache"], valid, "Researching what the source audit found missing", b.get("questions"))
                self._merge_research(rec)
                self.save(rec)
        while len(st["rounds"]) < 1 + TARGETED_RESEARCH_ROUNDS:
            final = len(st["rounds"]) >= TARGETED_RESEARCH_ROUNDS
            sources = rs["output"]["sources"]
            material = [{k: s_.get(k) for k in ("id", "url", "claim", "finding", "quote", "retrievedExcerpt", "strength", "fetch")} for s_ in sources]
            requestId, fp = secrets.token_hex(8), content_print(material)
            p, schema = prompts.source_review(rec["brief"], rec["stages"]["map"]["output"], sources, rs["output"].get("node_findings") or [], final)
            r = self.call(rec, "source_review", f"source_review-{len(st['rounds']) + 1}", "A separate audit of the sources", p, schema)
            out = r["output"]
            ids = {s_["id"] for s_ in sources}
            for v in out.get("sources") or []:
                if v.get("id") in ids:
                    src = next(s_ for s_ in sources if s_["id"] == v["id"])
                    key = pipeline.claim_key(src)
                    rank = {"no": 0, "partly": 1, "cannot_tell": 2, "yes": 3}
                    old_v = rs["verdicts"].get(key)
                    if old_v and rank.get(old_v["supports_claim"], 3) <= rank.get(v.get("supports_claim"), 3):
                        continue  # a source is only ever lowered by a review, never raised again by a later one
                    rs["verdicts"][key] = {"supports_claim": v.get("supports_claim"), "reason": _txt(v.get("reason")), "by": "source_review", "requestId": requestId,
                                           "claim": _txt(src.get("claim"))[:300], "excerptFingerprint": content_print(src.get("retrievedExcerpt") or "")}
            self._merge_research(rec)
            rnd = {"requestId": requestId, "inputFingerprint": fp, "finishedAt": storage.now_iso(), "model": r["model"], "output": out, "finalRound": final, "sourcesJudged": len(material)}
            st["rounds"].append(rnd)
            asks = [] if final else [q for q in out.get("targeted_research") or [] if _txt(q.get("question"))][:3]
            rnd["targetedAsked"] = asks
            self.save(rec)
            if not asks:
                break
            nodes = list(dict.fromkeys(q.get("node") for q in asks if q.get("node") in {n["id"] for n in rec["stages"]["map"]["output"]["nodes"]}))
            b = {"key": f"targeted-{len(st['rounds'])}", "nodes": nodes, "status": "running", "questions": [q["question"] for q in asks]}
            rs["batches"].append(b)
            self.save(rec)
            self._research_batch(rec, b, rs["cache"], {n["id"] for n in rec["stages"]["map"]["output"]["nodes"]}, "Researching what the source audit found missing", b["questions"])
            self._merge_research(rec)
            rnd["targetedDone"] = True
            self.save(rec)
        st.update(status="done", finishedAt=storage.now_iso())
        self.save(rec)

    def do_verify_evidence(self, rec: dict, retry_failed: bool = False) -> None:
        """Loom retrieves each source's page itself and checks its quotation word for word.

        No model is used and nothing is asked of the account. Every source is covered, in bounded batches that
        are saved as they go, so a run that stops can carry on where it left off instead of starting again. One
        page is fetched once however many claims rest on it. `retry_failed` tries again only where trying again
        could help: a refusal or a timeout, never an address that was refused for being private, and never a
        page that was already retrieved.
        """
        rs = rec["stages"]["research"]
        srcs = (rs.get("output") or {}).get("sources") or []
        rs.setdefault("direct", {})
        direct = rs["direct"]
        if retry_failed:
            for k, v in list(direct.items()):
                if isinstance(v, dict) and not v.get("ok") and _worth_retrying(v):
                    direct.pop(k)
        todo = [s_ for s_ in srcs if pipeline.claim_key(s_) not in direct]
        rs["directProgress"] = {"total": len(srcs), "done": len(srcs) - len(todo), "startedAt": storage.now_iso(), "finishedAt": None, "stopped": False}
        self.save(rec)
        seen: dict = {}
        for i, s_ in enumerate(todo):
            if self.stop.is_set():
                rs["directProgress"]["stopped"] = True
                break
            k, u = pipeline.claim_key(s_), norm_url(s_["url"])
            got = seen.get(u) or next((v for kk, v in direct.items() if kk.split("|")[0] == u), None)
            if got is None:
                got = evidence.fetch_original(s_["url"], allow_local=ALLOW_LOCAL_FETCH)
            seen[u] = got
            direct[k] = got
            rs["directProgress"]["done"] += 1
            if (i + 1) % DIRECT_BATCH == 0:
                self._merge_research(rec)
                self.save(rec)
        rs["directProgress"]["finishedAt"] = storage.now_iso()
        rs["directProgress"]["pagesFetched"] = len(seen)
        rs["directProgress"]["retryable"] = sorted({norm_url(s_["url"]) for s_ in srcs
                                                    if isinstance(direct.get(pipeline.claim_key(s_)), dict)
                                                    and not direct[pipeline.claim_key(s_)].get("ok") and _worth_retrying(direct[pipeline.claim_key(s_)])})
        rs["directProgress"]["cannotRetrieve"] = sorted({norm_url(s_["url"]) for s_ in srcs
                                                         if isinstance(direct.get(pipeline.claim_key(s_)), dict)
                                                         and not direct[pipeline.claim_key(s_)].get("ok") and not _worth_retrying(direct[pipeline.claim_key(s_)])})
        self._merge_research(rec)
        rec["stages"].setdefault("source_review", {})["evidenceChangedAfter"] = storage.now_iso()
        self.save(rec)

    def do_lineage_extraction(self, rec: dict, redo: bool = False) -> None:
        """Read what each retrieved document says about the work it builds on.

        Research written before Loom asked for lineage recorded none, and the acceptance course has not one entry:
        an attribution review cannot verify a relationship nobody wrote down. This reads relationships out of the
        documents themselves, requiring a verbatim quotation from the retrieved text for each one, so a claim of
        descent can be checked rather than taken on trust.

        Bound to the bytes it was read from, one reading per page however many claims rest on it, saved in batches
        and skipped when already done, exactly as identity is.
        """
        rs = rec["stages"]["research"]
        srcs = (rs.get("output") or {}).get("sources") or []
        direct = rs.get("direct") or {}
        rs.setdefault("lineageRead", {})
        got = rs["lineageRead"]
        if redo:
            got.clear()
        pages: dict = {}
        for s_ in srcs:
            d = direct.get(pipeline.claim_key(s_)) or {}
            if not d.get("ok") or not d.get("text"):
                continue
            u = norm_url(s_["url"])
            if u in pages:
                continue
            have = got.get(u)
            # A reading is taken again when the bytes changed AND when Loom now inspects more of the document than
            # it did then. An empty result from a narrower scan must never stand in the way of a wider one.
            if have and have.get("sha256") == d.get("sha256") and not redo \
                    and (have.get("inspected") or {}).get("scopeVersion") == evidence.LINEAGE_SCOPE_VERSION:
                continue
            text = d.get("text") or ""
            loc = ((s_.get("directRetrieval") or {}).get("locator") or {})
            quote_at = (loc.get("charStart"), loc.get("charEnd")) if loc.get("charEnd") else None
            head = (s_.get("directHead") or "")[:evidence.HEAD_KEEP]
            excerpt = (s_.get("directExcerpt") or "")[:500]
            sections = evidence.lineage_sections(text, head_chars=len(head), quote_at=quote_at)
            pages[u] = {"key": u, "title": s_.get("title"), "sha256": d.get("sha256"),
                        "the_start_of_the_document": head,
                        "the_passage_around_a_quotation": excerpt,
                        "further_passages_from_the_same_document": [{k2: v2 for k2, v2 in x.items() if k2 != "to"} for x in sections] or None,
                        "inspected": evidence.lineage_scope(text, sections, head_chars=len(head), excerpt_chars=len(excerpt))}
        todo = list(pages.values())
        rs["lineageProgress"] = {"pages": len(todo), "done": 0, "startedAt": storage.now_iso(), "finishedAt": None, "stopped": False}
        self.save(rec)
        for i in range(0, len(todo), IDENTITY_BATCH):
            if self.stop.is_set():
                rs["lineageProgress"]["stopped"] = True
                break
            batch = todo[i:i + IDENTITY_BATCH]
            p, schema = prompts.lineage_extraction([{k: v for k, v in x.items() if k not in ("sha256", "inspected")} for x in batch])
            r = self.call(rec, "lineage", f"lineage-{i // IDENTITY_BATCH + 1}",
                          f"Reading what {len(batch)} document{'s' if len(batch) > 1 else ''} say about earlier work", p, schema)
            by_key = {x["key"]: x for x in batch}
            for v in (r["output"].get("pages") or []):
                page = by_key.get(v.get("key"))
                if not page:
                    continue
                rels = []
                for x in v.get("relationships") or []:
                    if not isinstance(x, dict) or x.get("relation") not in lineage.RELATIONS:
                        continue
                    if not _txt(x.get("words_that_show_it")) or not _txt(x.get("earlier_work")):
                        continue  # a relationship with nothing to show it is not recorded at all
                    rels.append({"relation": x["relation"], "earlier_work": _txt(x.get("earlier_work_identifier")) or _txt(x.get("earlier_work")),
                                 "earlier_work_as_named": _txt(x.get("earlier_work")), "what_changed": _txt(x.get("what_changed")),
                                 "supporting_words": _txt(x.get("words_that_show_it")), "limits": _txt(x.get("limits"))})
                got[v["key"]] = {"relationships": rels, "originOfItsOwnSubject": v.get("origin_of_its_own_subject"),
                                 "note": _txt(v.get("note")), "sha256": page["sha256"], "inspected": page["inspected"],
                                 # An empty result is a statement about the text that was read, and nothing more.
                                 "notFoundHere": not rels,
                                 "readAt": storage.now_iso(), "model": r["model"]}
            rs["lineageProgress"]["done"] = min(i + len(batch), len(todo))
            self._merge_research(rec)
            self.save(rec)
        rs["lineageProgress"]["finishedAt"] = storage.now_iso()
        rec["stages"].setdefault("source_review", {})["evidenceChangedAfter"] = storage.now_iso()
        self._merge_research(rec)
        self.save(rec)

    def do_resolve_endpoints(self, rec: dict, redo: bool = False) -> None:
        """Fetch the earlier works that a relationship names by a published identifier.

        Every relationship in the acceptance course's graph had an unresolved far end: "the earlier work it names
        is not a work Loom holds, so the link has no other end". A chain with one end missing is not a discovery
        history, however many relationships were read.

        Only a work a document actually identified is fetched. A DOI, an arXiv id or an RFC number names something
        precisely enough to go and get; "the computational notebook format" names an idea and no address will
        resolve it. An ISBN is recognised and recorded as unfetchable rather than pointed at a shop. What comes
        back is a work Loom holds, with its own bytes and its own identity read from the document: it is NOT a
        judgement that the relationship is real, which remains for the attribution review to make.
        """
        rs = rec["stages"]["research"]
        edges = ((rs.get("output") or {}).get("lineage") or {}).get("edges") or []
        rs.setdefault("namedWorks", {})
        got = rs["namedWorks"]
        if redo:
            got.clear()
        todo: dict = {}
        for e in edges:
            if e.get("to"):
                continue
            found = lineage.named_work_address(e.get("earlierWorkAsNamed"))
            if not found:
                continue
            ident = found["identifier"]
            named_by = sorted({x for x in (e.get("fromSources") or []) if x})
            if ident in got:
                got[ident]["namedBy"] = sorted(set(got[ident].get("namedBy") or []) | set(named_by))
                if got[ident].get("ok") or not _worth_retrying(got[ident]):
                    continue
            if not found.get("url"):
                got[ident] = dict(found, ok=False, namedBy=named_by, note=found.get("why_not_fetched"),
                                  attemptedAt=storage.now_iso())
                continue
            entry = todo.setdefault(ident, dict(found, namedBy=[]))
            entry["namedBy"] = sorted(set(entry["namedBy"]) | set(named_by))
        rs["endpointProgress"] = {"works": len(todo), "done": 0, "fetched": 0, "startedAt": storage.now_iso(),
                                  "finishedAt": None, "stopped": False}
        self.save(rec)
        pages = []
        for ident, want in todo.items():
            if self.stop.is_set():
                rs["endpointProgress"]["stopped"] = True
                break
            f = evidence.fetch_original(want["url"], timeout=20, allow_local=ALLOW_LOCAL_FETCH)
            got[ident] = {"kind": want["kind"], "identifier": ident, "url": want["url"], "namedBy": want["namedBy"],
                          "ok": bool(f.get("ok") and f.get("text")), "status": f.get("status"), "finalUrl": f.get("finalUrl"),
                          "sha256": f.get("sha256"), "bytes": f.get("bytes"), "contentType": f.get("contentType"),
                          "textMethod": f.get("textMethod"), "note": f.get("note"), "attemptedAt": f.get("attemptedAt"),
                          "retrievedAt": f.get("retrievedAt"), "redirectedThrough": f.get("redirectedThrough"),
                          "addressesOpened": f.get("addressesOpened")}
            rs["endpointProgress"]["done"] += 1
            if got[ident]["ok"]:
                rs["endpointProgress"]["fetched"] += 1
                got[ident]["head"] = (f.get("text") or "")[:evidence.HEAD_KEEP]
                pages.append({"key": ident, "title_on_record": None, "sha256": f.get("sha256"),
                              "the_start_of_the_document": got[ident]["head"],
                              "the_passage_around_a_quotation": ""})
            self.save(rec)
        # Who made each fetched work, read out of the work itself, exactly as identity is read for a source.
        for i in range(0, len(pages), IDENTITY_BATCH):
            if self.stop.is_set():
                rs["endpointProgress"]["stopped"] = True
                break
            batch = pages[i:i + IDENTITY_BATCH]
            p, schema = prompts.identity_extraction([{k: v for k, v in x.items() if k != "sha256"} for x in batch])
            r = self.call(rec, "endpoints", f"endpoints-{i // IDENTITY_BATCH + 1}",
                          f"Reading {len(batch)} work{'s' if len(batch) > 1 else ''} named as earlier work", p, schema)
            by_key = {x["key"]: x for x in batch}
            for v in (r["output"].get("pages") or []):
                page = by_key.get(v.get("key"))
                if not page or v["key"] not in got:
                    continue
                entry = got[v["key"]]
                if entry.get("sha256") != page["sha256"]:
                    continue
                entry["identityRead"] = {"authors": v.get("authors") or [], "published": _txt(v.get("published")),
                                         "version_or_edition": _txt(v.get("version_or_edition")),
                                         "identifier": _txt(v.get("identifier")), "role": v.get("role"),
                                         "titleAsPublished": _txt(v.get("title_as_published")),
                                         "wordsThatShowIt": _txt(v.get("words_that_show_it")),
                                         "unknown": [u for u in (v.get("unknown") or []) if isinstance(u, str)],
                                         "note": _txt(v.get("note")), "sha256": page["sha256"],
                                         "readAt": storage.now_iso(), "model": r["model"]}
            self._merge_research(rec)
            self.save(rec)
        rs["endpointProgress"]["finishedAt"] = storage.now_iso()
        rec["stages"].setdefault("source_review", {})["evidenceChangedAfter"] = storage.now_iso()
        self._merge_research(rec)
        self.save(rec)

    def do_identity_enrichment(self, rec: dict, redo: bool = False) -> None:
        """Read each retrieved document's own identity out of the document, for any source that lacks it.

        Research written before Loom asked for identity left these fields absent, and an attribution review cannot
        repair what was never recorded: rerunning it on unchanged records only rejects them again. This reads the
        identity from the text Loom itself retrieved, never from a tool's summary, and never from the address.

        One page is read once however many claims rest on it, which is how works are deduplicated while every
        distinct claim keeps its own record. Each result is bound to the checksum of the bytes it was read from, so
        it stops applying if the page is fetched again and differs. Work is saved in batches and skipped when
        already done, so an interrupted run continues.
        """
        rs = rec["stages"]["research"]
        srcs = (rs.get("output") or {}).get("sources") or []
        direct = rs.get("direct") or {}
        rs.setdefault("identity", {})
        got = rs["identity"]
        if redo:
            got.clear()
        # One entry per page that Loom actually retrieved text from, keyed by address.
        pages: dict = {}
        for s_ in srcs:
            d = direct.get(pipeline.claim_key(s_)) or {}
            if not d.get("ok") or not d.get("text"):
                continue
            u = norm_url(s_["url"])
            if u in pages:
                continue
            have = got.get(u)
            # Read again when the bytes changed AND when Loom now inspects more of the document than it did then.
            if have and have.get("sha256") == d.get("sha256") and not redo \
                    and (have.get("inspected") or {}).get("scopeVersion") == evidence.IDENTITY_SCOPE_VERSION:
                continue  # already read from these exact bytes, under these rules
            text = d.get("text") or ""
            loc = ((s_.get("directRetrieval") or {}).get("locator") or {})
            quote_at = (loc.get("charStart"), loc.get("charEnd")) if loc.get("charEnd") else None
            head = (s_.get("directHead") or text)[:evidence.HEAD_KEEP]
            excerpt = (s_.get("directExcerpt") or "")[:500]
            sections = evidence.identity_sections(text, head_chars=len(head), quote_at=quote_at)
            pages[u] = {"key": u, "title_on_record": s_.get("title"), "sha256": d.get("sha256"),
                        "the_start_of_the_document": head,
                        "the_passage_around_a_quotation": excerpt,
                        "further_passages_from_the_same_document": [{k2: v2 for k2, v2 in x.items() if k2 != "to"} for x in sections] or None,
                        "inspected": evidence.identity_scope(text, sections, head_chars=len(head), excerpt_chars=len(excerpt))}
        todo = list(pages.values())
        rs["identityProgress"] = {"pages": len(todo), "done": 0, "startedAt": storage.now_iso(), "finishedAt": None, "stopped": False}
        self.save(rec)
        for i in range(0, len(todo), IDENTITY_BATCH):
            if self.stop.is_set():
                rs["identityProgress"]["stopped"] = True
                break
            batch = todo[i:i + IDENTITY_BATCH]
            p, schema = prompts.identity_extraction([{k: v for k, v in x.items() if k not in ("sha256", "inspected")} for x in batch])
            r = self.call(rec, "identity", f"identity-{i // IDENTITY_BATCH + 1}",
                          f"Reading who made {len(batch)} retrieved document{'s' if len(batch) > 1 else ''}", p, schema)
            by_key = {x["key"]: x for x in batch}
            for v in (r["output"].get("pages") or []):
                src_page = by_key.get(v.get("key"))
                if not src_page:
                    continue
                unknown = [u for u in (v.get("unknown") or []) if isinstance(u, str)]
                got[v["key"]] = {"authors": [a for a in (v.get("authors") or []) if _txt(a)], "published": _txt(v.get("published")),
                                 "version_or_edition": _txt(v.get("version_or_edition")), "identifier": _txt(v.get("identifier")),
                                 "role": v.get("role") if v.get("role") in evidence.ROLES else None,
                                 "titleAsPublished": _txt(v.get("title_as_published")),
                                 "wordsThatShowIt": _txt(v.get("words_that_show_it")), "unknown": unknown,
                                 "note": _txt(v.get("note")), "sha256": src_page["sha256"],
                                 "inspected": src_page["inspected"],
                                 "readAt": storage.now_iso(), "model": r["model"]}
            rs["identityProgress"]["done"] = min(i + len(batch), len(todo))
            self._merge_research(rec)
            self.save(rec)
        rs["identityProgress"]["finishedAt"] = storage.now_iso()
        # Identity changed, so any attribution verdict made against the old metadata no longer applies. It is left
        # in place and will be marked stale on merge, rather than deleted, so the record shows what happened.
        rec["stages"].setdefault("source_review", {})["evidenceChangedAfter"] = storage.now_iso()
        self._merge_research(rec)
        self.save(rec)

    def do_attribution_review(self, rec: dict) -> None:
        """A separate check of who made each source and how it connects.

        Every run is kept. A verdict is never silently replaced: the previous one is appended to this source's
        history, and where a new verdict disagrees with the last one JUDGED ON THE SAME INPUT, the disagreement is
        recorded on the verdict itself rather than resolved. Nothing here votes, and nothing re-runs hoping for a
        better answer. Two passes of one model share its errors, so agreement between them is not evidence; what a
        person needs to see is that the same question got two answers, and that is what is written down.
        """
        rs = rec["stages"]["research"]
        srcs = (rs.get("output") or {}).get("sources") or []
        direct = rs.get("direct") or {}
        # The text behind each source, used for BOTH the prompt and the fingerprint so they cannot disagree.
        texts = {s_.get("id"): (direct.get(pipeline.claim_key(s_)) or {}).get("text") for s_ in srcs}
        material = [attribution_material(s_, texts.get(s_.get("id"))) for s_ in srcs]
        batch_print = content_print(material)
        p, schema = prompts.attribution_review(rec["brief"], rec["stages"]["map"]["output"], srcs, texts)
        # The whole request, not just the evidence in it, and not just the part of it this stage writes. The
        # sources digest alone is not the request: the judge rules, the answer schema, the system text every call
        # carries, and the settings the model runs under are all part of what was asked, and changing any of them
        # can move a verdict without touching a single source. `[p, schema]` left out prompts.SYSTEM and the
        # effective configuration, so two runs under different settings compared as the identical request.
        settings = request_settings()
        request = {"prompt": p, "schema": schema, "system": prompts.SYSTEM, "settings": settings}
        request_print = content_print(request)
        execution = _execution_provenance()
        # The request itself, kept once under its own fingerprint. A hash can say two runs differed; only the
        # request can say how. Replaying or inspecting an old ask needs the ask, not a digest of it.
        snapshot = storage.save_request_snapshot(self.store, self.cid, request_print, dict(
            request, at=storage.now_iso(), stage="attribution_review", requestFingerprint=request_print,
            reviewerInputVersion=prompts.REVIEWER_INPUT_VERSION, sourcesInRequest=len(srcs), **execution))
        # A fingerprint is a short hash, and a snapshot is written once and never replaced. If a DIFFERENT
        # request ever lands on an existing name, the stored copy is not the one this run sent, and treating it
        # as such would make a replay silently wrong. Say so rather than let the two be confused.
        kept = storage.read_request_snapshot(self.store, self.cid, request_print)
        collided = bool(kept) and (kept.get("prompt") != p or kept.get("system") != prompts.SYSTEM
                                   or kept.get("schema") != schema or kept.get("settings") != settings)
        r = self.call(rec, "attribution_review", "attribution_review", "A separate check of who made each source and how they connect", p, schema)
        out = r["output"]
        ids = {s_["id"]: s_ for s_ in srcs}
        rs.setdefault("attribution", {})
        history = rs.setdefault("attributionHistory", {})
        # Decisions a person has made about contradictions the review produced. Loom never writes these from a
        # model run: a disagreement is settled by someone reading the document, or it is not settled at all.
        rs.setdefault("attributionResolutions", {})  # a person's decisions; applied when the record is read
        run_id = secrets.token_hex(8)
        # What produced this run, kept with it, so a later disagreement can be read against what actually differed.
        # Three different questions, kept apart because they are answered differently. Equal EVIDENCE is
        # `batchInputFingerprint` and the per-source `fingerprint`. Equal REQUEST is `requestFingerprint`: the
        # same evidence asked the same way. Equal EXECUTION is `settingsFingerprint` with the build: the same
        # request run by the same code under the same configuration. Two runs can match on one and differ on the
        # next, and reading a difference as being about the model needs all three to have held.
        provenance = {"runId": run_id, "at": storage.now_iso(), "model": r["model"], "stage": "attribution_review",
                      "batchInputFingerprint": batch_print, "requestFingerprint": request_print,
                      "settingsFingerprint": content_print(settings), "settings": settings,
                      "requestSnapshot": None if collided else snapshot,
                      **({"requestSnapshotUnavailable": (
                          "Another request is already stored under this fingerprint and its contents differ, so "
                          "the stored copy is NOT this run's request. Nothing was overwritten; this run's "
                          "request was not kept.")} if collided else {}),
                      "promptCharacters": len(p), "sourcesInRequest": len(srcs),
                      "reviewerInputVersion": prompts.REVIEWER_INPUT_VERSION, **execution}

        def answers_in(entry):
            """Every question one judgement answered, keyed so two runs can be compared question by question.

            Comparing runs on the aggregate verdict alone hid the disagreements that matter most. The aggregate is
            "yes" only when identity, role and descent are all affirmative, so it stays "partly" while a single
            relationship underneath it flips from yes to no — and that flip is exactly what decides whether a link
            in the lineage graph stands. Each relationship is therefore its own question, matched across runs by
            the earlier work it names and the relation it claims.
            """
            d = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
            out = {"overall": entry.get("verdict"), "identity": d.get("identity_correct"),
                   "role": d.get("role_correct"), "lineage_supported": d.get("lineage_supported")}
            for r in d.get("relationships") or []:
                if isinstance(r, dict):
                    out[lineage.disagreement_key("relationship", r.get("earlier_work"), r.get("relation"))] = r.get("supported")
            return out

        def remember(claim_key, entry):
            """Append this judgement to the source's history and record what it contradicts, question by question.

            Nothing here resolves a contradiction. Two runs of one model share its errors, so a second answer is
            not a check on the first; where they differ, both are kept and the claim is held until a person
            decides on the evidence. The later answer is not preferred for being later, no answer is averaged
            against another, and no further run is asked in the hope of breaking the tie.
            """
            past = history.setdefault(claim_key, [])
            same_input = [h for h in past if h.get("fingerprint") == entry.get("fingerprint")]
            prev = same_input[-1] if same_input else None
            live: dict = {}
            if prev is not None:
                # A contradiction does not expire by being repeated. Answer yes, then no, then no again, and the
                # last two runs agree, so comparing only against the run before would show nothing wrong by the
                # third — while the first two still contradict each other on the same evidence. Unresolved
                # disagreements are therefore carried forward under their own key until a person settles them.
                # Every earlier judgement on this same evidence is consulted, not only the one before. A
                # conflict raised three runs ago and absent from the latest entry is still unsettled: reading
                # only the previous entry let it drop out of sight the moment one run happened not to repeat it.
                for older in same_input:
                    for d in older.get("unresolvedDisagreements") or []:
                        if isinstance(d, dict) and d.get("key"):
                            live.setdefault(d["key"], d)
                # Same evidence is not the same question. Only call it a disagreement about the model when the
                # WHOLE request matched — same judge rules, same schema, same prompt — otherwise say plainly that
                # the asking changed too, so the difference is never counted as evidence about the model alone.
                same_request = (prev.get("provenance") or {}).get("requestFingerprint") == request_print
                was, now_ = answers_in(prev), answers_in(entry)
                for dkey in list(was) + [k for k in now_ if k not in was]:
                    a, b = was.get(dkey), now_.get(dkey)
                    # An unanswered question is not a contradicting answer. Where one run left a question blank,
                    # that is an omission — handled by failing closed where the answer is needed — and inventing a
                    # disagreement out of it would be the same mistake as reading an omission as a denial.
                    if a is None or b is None or a == b:
                        continue
                    aspect = "relationship" if dkey.startswith("relationship|") else dkey
                    live[dkey] = {"aspect": aspect, "key": dkey, "earlier": a, "later": b,
                                  "earlierRunId": prev.get("runId"), "earlierAt": prev.get("at"),
                                  "laterRunId": run_id, "laterAt": entry.get("at"),
                                  "sameEvidence": True, "sameWholeRequest": same_request,
                                  "note": ("The same evidence produced a different answer to this question in an "
                                           "earlier run. This is an UNRESOLVED disagreement, recorded rather than "
                                           "settled: it is not averaged, not voted on, and the later answer is not "
                                           "assumed to be the better one. A person decides.") +
                                          ("" if same_request else
                                           " NOTE: the rest of the request — the judge rules or the answer schema — "
                                           "also changed between these two runs, so this difference is NOT evidence "
                                           "about the model alone and must not be counted as one.")}
            # Everything contradicted is recorded raw. Whether a person has since decided any of it is applied
            # when the record is read, so the history keeps what the model actually said rather than a version
            # of the past edited by a later decision.
            if live:
                entry["unresolvedDisagreements"] = list(live.values())
            # Kept for anything still reading the older single-verdict field. It says only what it ever said:
            # whether the aggregate verdict moved.
            if agg := live.get("overall"):
                entry["disagreesWithEarlierRun"] = {"earlierVerdict": agg.get("earlier"), "earlierRunId": agg.get("earlierRunId"),
                                                    "earlierAt": agg.get("earlierAt"), "sameEvidence": True,
                                                    "sameWholeRequest": agg.get("sameWholeRequest"), "note": agg.get("note")}
            past.append(dict(entry, runId=run_id, provenance=provenance))
            # Nothing is destroyed. `del past[:-20]` quietly dropped every judgement older than the last twenty,
            # while the rule written above this method says every one is kept. What leaves the working index is
            # appended to a durable file beside the course first, and the index says how many went and where.
            if len(past) > _HISTORY_INDEX_KEEP:
                leaving, past[:] = past[:-_HISTORY_INDEX_KEEP], past[-_HISTORY_INDEX_KEEP:]
                where = storage.archive_judgements(self.store, self.cid, claim_key, leaving)
                moved = rs.setdefault("attributionHistoryArchived", {}).setdefault(claim_key, {"count": 0, "file": where})
                moved["count"] += len(leaving)
                moved["file"] = where or moved.get("file")
                moved["note"] = ("Older judgements for this source are kept in full beside the course, not in "
                                 "this file. None has been deleted.")
            return entry

        for v in out.get("sources") or []:
            s_ = ids.get(v.get("id"))
            if s_:
                good = v.get("identity_correct") == "yes" and v.get("role_correct") == "yes" and v.get("lineage_supported") in ("yes", "none_claimed")
                k_ = pipeline.claim_key(s_)
                rs["attribution"][k_] = remember(k_, {"verdict": "yes" if good else "no" if "no" in (v.get("identity_correct"), v.get("role_correct")) else "partly",
                                                      "detail": v, "requestId": run_id,
                                                      "fingerprint": content_print(attribution_material(s_, texts.get(s_.get("id")))),
                                                      "at": storage.now_iso()})
        judged = {s_["id"] for v in out.get("sources") or [] if (s_ := ids.get(v.get("id")))}
        for s_ in srcs:
            if s_["id"] not in judged:
                k_ = pipeline.claim_key(s_)
                if k_ in rs["attribution"]:
                    # This review looked at the set and returned nothing for this source. An earlier verdict is
                    # not carried forward as though it had been confirmed again.
                    rs["attribution"][k_] = remember(k_, {"verdict": "not_judged", "reason": "The attribution review returned no judgement for this source.",
                                                          "requestId": run_id,
                                                          "fingerprint": content_print(attribution_material(s_, texts.get(s_.get("id")))),
                                                          "at": storage.now_iso()})
        rs["attributionReview"] = {"output": out, "finishedAt": storage.now_iso(), "model": r["model"],
                                   "inputFingerprint": batch_print, "requestFingerprint": request_print,
                                   "provenance": provenance,
                                   "disagreements": sorted(k for k, v2 in rs["attribution"].items() if v2.get("disagreesWithEarlierRun")),
                                   "disagreementsOnAnIdenticalRequest": sorted(
                                       k for k, v2 in rs["attribution"].items()
                                       if (v2.get("disagreesWithEarlierRun") or {}).get("sameWholeRequest"))}
        self._merge_research(rec)
        self.save(rec)

    def do_outline2(self, rec: dict, feedback: str | None = None) -> None:
        st = rec["stages"]["outline"]
        previous = st.get("output")
        st.update(status="running", startedAt=storage.now_iso(), approved=False)
        m = rec["stages"]["map"]["output"]
        gaps = m["derived"]["openGaps"] + m["derived"].get("unresolved", [])
        p, schema = prompts.outline2(rec["brief"], rec["plan"], m, rec["stages"]["research"].get("output"), rec["policy"], rec["accounting"], gaps, feedback, previous, prepared_digest(self.store, self.cid, rec))
        r = self.call(rec, "outline", "outline", "Proposing an outline", p, schema,
                      check=lambda o: check_outline(o, rec["brief"], rec["plan"]) + pipeline.check_outline_v2(o, m, rec["brief"], rec["plan"]))
        if feedback:
            st.setdefault("feedback", []).append({"at": storage.now_iso(), "text": feedback})
        st.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"], coverage=pipeline.coverage(r["output"], m))
        self.save(rec)

    def do_outline_review(self, rec: dict, revise: bool = True) -> None:
        """A separate check that the outline can be delivered.

        `revise` is what happens after a must-fix. On the ordinary route the reviewer's must-fixes are sent back
        and the outline is written again, once. That is right while the outline is the writer's. It is wrong once
        a person has repaired the outline by hand: the acceptance course's outline carries three such repairs,
        recorded under `repairedOutsideTheWriter`, and rewriting it would throw them away to answer a finding
        nobody had read yet. Asked for review only, Loom reports what the reviewer found and changes nothing.
        """
        st = rec["stages"]["outline_review"]
        if st.get("status") == "done":
            return
        st["status"] = "running"
        st.setdefault("rounds", [])
        m = rec["stages"]["map"]["output"]
        while True:
            o = rec["stages"]["outline"]["output"]
            cov = pipeline.coverage(o, m)
            material = {"outline": o, "coverage": cov}
            requestId, fp = secrets.token_hex(8), content_print(material)
            p, schema = prompts.outline_review(rec["brief"], rec["plan"], m, o, rec["policy"], rec["accounting"], cov)
            r = self.call(rec, "outline_review", f"outline_review-{len(st['rounds']) + 1}", "A separate check that it can be delivered", p, schema)
            out = r["output"]
            must = [f for f in out.get("findings") or [] if f.get("severity") == "must_fix"]
            st["rounds"].append({"requestId": requestId, "inputFingerprint": fp, "finishedAt": storage.now_iso(), "model": r["model"], "output": out})
            st["output"], st["inputFingerprint"], st["requestId"] = out, fp, requestId
            self.save(rec)
            if must and revise and len(st["rounds"]) <= AUTO_REVISE_ROUNDS:
                fb = "The feasibility reviewer found these problems that must be fixed. Fix them and keep everything else:\n" + "\n".join(f"- ({f['area']}) {f['finding']} Suggestion: {f['suggestion']}" for f in must)
                st["rounds"][-1]["sentBackForRevision"] = True
                rec["stages"]["outline"]["pendingFeedback"] = fb  # kept, so a stop in the middle does not lose what the reviewer asked for
                self.save(rec)
                self.do_outline2(rec, fb)
                rec["stages"]["outline"].pop("pendingFeedback", None)
                rec["stages"]["outline_review"]["status"] = "running"
                continue
            break
        st.update(status="done", finishedAt=storage.now_iso(), appliedToFingerprint=fp, unresolvedMustFix=len(must),
                  reviewedWithoutRevising=not revise)
        self.save(rec)

    def pre_outline(self, rec: dict) -> None:
        mp = rec["stages"]["map"]
        if mp.get("status") == "done" and mp.get("output"):
            mp["output"] = pipeline.derive_map(mp["output"])  # what follows from the map is worked out afresh, so a rule that improved applies to a saved run
        self.do_map(rec)
        self.do_foundation_review(rec)
        self.do_research2(rec)
        # Loom's own retrieval and the attribution check are part of the ordinary route to an outline, not
        # separate buttons someone must remember to press. Both resume where they stopped, so re-entering
        # pre_outline after an interruption costs only what is left.
        self.do_verify_evidence(rec)
        # Identity is read from the retrieved documents BEFORE anything judges it, so the attribution review has
        # something to judge. Without this a source can only ever be rejected for having no identity recorded.
        self.do_identity_enrichment(rec)
        self.do_lineage_extraction(rec)
        self.do_source_review(rec)
        self.do_attribution_review(rec)
        if rec["stages"]["outline"].get("status") != "done":
            self.do_outline2(rec, rec["stages"]["outline"].get("pendingFeedback") or None)
        self.do_outline_review(rec)

    def do_projects(self, rec: dict, only: int | None = None) -> None:
        ps = rec["stages"]["projects"]
        if not ps.get("units"):
            ps["status"] = "done"  # a format too short for a project has none to write; that is finished, not waiting
            self.save(rec)
            return
        outline_out = rec["stages"]["outline"]["approved_outline"]
        m = rec["stages"]["outline"].get("approved_map") or rec["stages"]["map"]["output"]
        research_out = rec["stages"]["research"].get("output")
        ids = {x["id"]: x.get("strength") for x in (research_out or {}).get("sources") or []}
        written = self.written(rec)
        taught = {}
        for w in written:
            for nid in w["content"].get("teaches_nodes") or []:
                taught.setdefault(nid, w["number"])
        in_hand = prepared_assets(self.store, self.cid, rec) + [a for w in written for a in w["content"].get("assets") or []]
        stx = self.source_texts(rec)
        ps["status"] = "running"
        for i, unit in enumerate(ps["units"]):
            if (only is not None and i != only) or (only is None and unit.get("status") == "done"):
                continue
            unit.update(status="running", startedAt=storage.now_iso())
            self.save(rec)
            proj = unit["outline"]
            p, schema = prompts.project(rec["brief"], rec["plan"], m, research_out, outline_out, proj, written, rec["policy"])
            record = {}

            def check(o, proj=proj, record=record):
                settle_claims(o, ids)
                probs = pipeline.check_project(o, proj, m, taught, ids)
                assets = [a for a in (o.get("inputs") or []) + (o.get("solution_assets") or []) if isinstance(a, dict)]
                probs += pipeline.check_assets(assets, "Assets")
                if not probs:
                    record["results"] = pipeline.run_assets(assets, in_hand) + pipeline.origin_checks(assets, stx)
                    probs += pipeline.asset_problems(record["results"], "Running the code")
                return probs
            try:
                r = self.call(rec, "project", f"project-{proj['id']}", f"Writing project: {proj.get('title', '')}"[:80], p, schema, check=check)
            except Pause as pz:
                unit.update(status="failed" if pz.kind == "invalid" else "todo", reason=pz.reason, detail=pz.detail)
                self.save(rec)
                raise
            unit.update(status="done", finishedAt=storage.now_iso(), model=r["model"], output=r["output"], assetChecks=record.get("results") or [])
            unit.pop("reason", None)
            unit.pop("detail", None)
            self.save(rec)
        ps["status"] = "done" if all(u.get("status") == "done" for u in ps["units"]) else "todo"
        self.save(rec)

    def agent_findings_digest(self, rec: dict) -> dict:
        st = rec["stages"]
        out = {}
        if st.get("foundation_review", {}).get("output"):
            o = st["foundation_review"]["output"]
            out["foundations_reviewer"] = {"verdict": o.get("verdict"), "summary": o.get("summary"), "added_topics": st["foundation_review"].get("addedNodes")}
        if st.get("source_review", {}).get("rounds"):
            o = st["source_review"]["rounds"][-1]["output"]
            out["source_auditor"] = {"verdict": o.get("verdict"), "summary": o.get("summary"), "conflicts": o.get("conflicts"), "node_gaps": o.get("node_gaps")}
        if st.get("outline_review", {}).get("output"):
            o = st["outline_review"]["output"]
            out["feasibility_reviewer"] = {"verdict": o.get("verdict"), "summary": o.get("summary"), "findings": [f["finding"] for f in o.get("findings") or [] if f.get("severity") == "must_fix"]}
        return out

    # -- orchestration
    def run(self, action: str, payload: dict) -> None:
        rec = self.load()
        try:
            rec["pause"] = None
            if action == "begin":
                if self.v2(rec):
                    self.pre_outline(rec)
                else:
                    self.do_research(rec)
                    self.do_outline(rec)
                rec["status"] = "waiting_approval"
            elif action == "review_outline":
                # Review only. The outline is not rewritten, whatever the reviewer finds, so repairs made by hand
                # survive being reviewed.
                rec["stages"]["outline_review"] = {"status": "todo", "rounds": rec["stages"].get("outline_review", {}).get("rounds") or []}
                self.do_outline_review(rec, revise=False)
                rec["status"] = rec.get("statusBeforeEdit") or "waiting_approval"
            elif action == "revise_outline":
                if self.v2(rec):
                    self.do_outline2(rec, payload.get("feedback") or "")
                    rec["stages"]["outline"].pop("pendingFeedback", None)
                    self.do_outline_review(rec)
                else:
                    self.do_outline(rec, payload.get("feedback") or "")
                    rec["stages"]["outline"].pop("pendingFeedback", None)
                rec["status"] = "waiting_approval"
            elif action in ("approve_outline", "resume", "retry_session", "retry_project"):
                if action == "resume":
                    for eid, e in list(rec["edits"].items()):
                        if e.get("status") in ("paused", "todo"):
                            self.do_edit(rec, eid)
                    if self.v2(rec):
                        self.pre_outline(rec)
                    else:
                        if rec["stages"]["research"].get("status") != "done":
                            self.do_research(rec)
                        if rec["stages"]["outline"].get("status") != "done":
                            self.do_outline(rec, rec["stages"]["outline"].get("pendingFeedback") or None)
                rec["stages"]["outline"].pop("pendingFeedback", None)
                if not rec["stages"]["outline"].get("approved"):
                    rec["status"] = "waiting_approval"
                else:
                    if action != "retry_project":
                        self.do_materials(rec, payload.get("index") if action == "retry_session" else None)
                    if self.v2(rec) and rec["stages"]["materials"]["status"] == "done":
                        self.do_projects(rec, payload.get("index") if action == "retry_project" else None)
                    built = rec["stages"]["materials"]["status"] == "done" and (not self.v2(rec) or rec["stages"]["projects"]["status"] == "done")
                    if built and rec["stages"]["review"].get("status") != "done":
                        self.do_review(rec)
                    rec["status"] = "done" if built else "paused"
            elif action == "review":
                self.do_review(rec, payload.get("sessions"), payload.get("projects"))
                rec["status"] = "done" if rec["stages"]["materials"]["status"] == "done" else rec.get("status", "idle")
            elif action == "edit":
                self.do_edit(rec, payload["editId"])
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "verify_evidence":
                self.do_verify_evidence(rec, retry_failed=bool(payload.get("retryFailed")))
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "read_identity":
                self.do_identity_enrichment(rec, redo=bool(payload.get("redo")))
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "read_lineage":
                self.do_lineage_extraction(rec, redo=bool(payload.get("redo")))
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "resolve_endpoints":
                self.do_resolve_endpoints(rec, redo=bool(payload.get("redo")))
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "attribution_review":
                self.do_attribution_review(rec)
                rec["status"] = rec.get("statusBeforeEdit") or "done"
            elif action == "ideas":
                self.do_ideas(rec, payload)
                rec["status"] = rec.get("statusBeforeEdit") or ("idle" if rec.get("ideasOnly") else "done")
            rec["now"] = None
        except Pause as p:
            rec["status"] = "paused"
            rec["now"] = None
            rec["pause"] = {"kind": p.kind, "reason": p.reason, "detail": p.detail, "resetsAt": p.resets_at, "at": storage.now_iso(), "during": action}
            if action == "ideas":
                # A failed search is a failed search. Nothing illustrative is dressed up as its result.
                cur = storage.read_ideas(self.store, self.cid) or {}
                storage.write_ideas(self.store, self.cid, dict(cur, status="failed", failedAt=storage.now_iso(), reason=p.reason, detail=p.detail))
            self.settle_paused(rec)
            for e in rec["edits"].values():
                if e.get("status") == "running":
                    e["status"] = "paused"
                    for part in e["parts"]:
                        if part.get("status") == "running":
                            part["status"] = "todo"
        except Exception as e:  # noqa: BLE001 - anything unexpected also pauses, with the reason shown
            rec["status"] = "paused"
            rec["now"] = None
            rec["pause"] = {"kind": "error", "reason": "Loom hit an unexpected problem and stopped. Your finished work is saved.", "detail": f"{type(e).__name__}: {e}"[:400], "at": storage.now_iso(), "during": action}
        finally:
            self.save(rec)

    @staticmethod
    def settle_paused(rec: dict) -> None:
        """Whatever was running when work stopped is waiting again. Finished parts stay finished."""
        for st in rec["stages"].values():
            if isinstance(st, dict) and st.get("status") == "running":
                st["status"] = "todo"
            for b in (st.get("batches") or []) if isinstance(st, dict) else []:
                if b.get("status") == "running":
                    b["status"] = "todo"
            for u in (st.get("units") or []) if isinstance(st, dict) else []:
                if u.get("status") == "running":
                    u["status"] = "todo"

    def start(self, action: str, payload: dict) -> dict:
        with self.lock:
            if self.busy():
                raise storage.Conflict("Loom is already working on this course.", 0)
            rec = self.load()
            if rec is None and action == "ideas":
                rec = blank_ideas()
            if action in ("ideas", "verify_evidence", "read_identity", "read_lineage", "resolve_endpoints", "attribution_review", "review_outline"):
                rec["statusBeforeEdit"] = rec.get("status") if rec.get("status") in ("done", "waiting_approval", "idle") else rec.get("statusBeforeEdit")
            if action == "begin":
                old = rec
                if old and (old.get("stages", {}).get("research", {}).get("status") == "done" or old.get("stages", {}).get("map", {}).get("status") == "done"):
                    stamp = storage.stamp()
                    storage.write_atomic(storage.course_dir(self.store, self.cid) / "engine-history" / f"{stamp}.json", json.dumps(old, indent=1, ensure_ascii=False))
                rec = blank(payload["brief"], payload["plan"], payload.get("digest", ""), 2 if payload.get("pipeline") == 2 else 1)
            if rec is None:
                raise storage.StoreError("Nothing has been started for this course yet.")
            if action == "approve_outline":
                o = payload.get("outline")
                problems = check_outline(o, rec["brief"], rec["plan"]) if isinstance(o, dict) else ["There is no outline to approve."]
                if self.v2(rec) and isinstance(o, dict):
                    problems += pipeline.check_outline_v2(o, rec["stages"]["map"]["output"], rec["brief"], rec["plan"])
                if problems:
                    raise storage.StoreError("This outline cannot be approved yet: " + problems[0])
                if any(u.get("output") for u in rec["stages"]["materials"]["sessions"]) or rec["stages"]["review"].get("output"):
                    # approving again starts the sessions afresh, so what was written is put aside first, never dropped
                    storage.write_atomic(storage.course_dir(self.store, self.cid) / "engine-history" / f"{storage.stamp()}.json", json.dumps(rec, indent=1, ensure_ascii=False))
                rec["stages"]["outline"].update(approved=True, approvedAt=storage.now_iso(), approved_outline=o, editedByTeam=payload.get("edited", False))
                if self.v2(rec):
                    m = rec["stages"]["map"]["output"]
                    rec["stages"]["outline"].update(approved_map=m, approved_coverage=pipeline.coverage(o, m),
                                                    acknowledged=[str(x)[:300] for x in (payload.get("acknowledged") or [])][:20] if isinstance(payload.get("acknowledged"), list) else [])
                    units = [{"status": "todo", "outline": x} for x in o.get("projects") or [] if isinstance(x, dict)]
                    rec["stages"]["projects"] = {"status": "todo" if units else "done", "units": units}
                for u in rec["stages"]["materials"]["sessions"]:
                    u.update(status="todo")
                    u.pop("output", None)
                rec["stages"]["review"] = {"status": "todo"}
                rec["draft"] = {}
            if action in ("resume", "retry_session") and isinstance(payload.get("written"), list):
                n = len(rec["stages"]["materials"]["sessions"])
                rec["draft"] = {str(w["number"]): prompts.slim(w["content"]) for w in payload["written"]
                                if isinstance(w, dict) and isinstance(w.get("content"), dict) and isinstance(w.get("number"), int) and not isinstance(w.get("number"), bool) and 1 <= w["number"] <= n}
            if action == "review":
                # The exact material to be judged is kept with the request, so a pause and resume cannot swap it
                # for what Claude first generated. A new request replaces any earlier one.
                subs = payload.get("sessions")
                submitted = isinstance(subs, list) and subs
                projs = payload.get("projects") if isinstance(payload.get("projects"), list) and payload.get("projects") else None
                material = {"sessions": subs, "projects": projs} if submitted and projs and self.v2(rec) else subs
                rec["stages"]["review"] = {"status": "todo", "requestId": secrets.token_hex(8),
                                           "input": material if submitted else None,
                                           "inputFingerprint": content_print(material) if submitted else None,
                                           "inputOrigin": "submitted" if submitted else "generated"}
            if action == "revise_outline":
                rec["stages"]["outline"]["pendingFeedback"] = payload.get("feedback") or ""
                if self.v2(rec):
                    rec["stages"]["outline_review"] = {"status": "todo"}
            if action == "edit":
                rec["statusBeforeEdit"] = rec.get("status") if rec.get("status") in ("done", "waiting_approval", "idle") else "done"
                rec["edits"][payload["editId"]] = {"id": payload["editId"], "scope": payload["scope"], "instruction": payload["instruction"], "aboutTime": bool(payload.get("aboutTime")),
                                                   "baseRev": payload.get("baseRev"), "baseUid": payload.get("baseUid"), "status": "todo", "askedAt": storage.now_iso(),
                                                   "req": payload.get("req") if isinstance(payload.get("req"), dict) else None,
                                                   "parts": [dict(p, status="todo") for p in payload["parts"] if isinstance(p, dict)],
                                                   "others": [{"number": w["number"], "content": prompts.slim(w["content"])} for w in (payload.get("context") if isinstance(payload.get("context"), list) else [])
                                                              if isinstance(w, dict) and isinstance(w.get("content"), dict) and isinstance(w.get("number"), int) and not isinstance(w.get("number"), bool)][:60]}
                for k in sorted(rec["edits"], key=lambda k: rec["edits"][k].get("askedAt", ""))[:-12]:
                    del rec["edits"][k]
            rec["status"], rec["pause"] = "running", None
            self.save(rec)
            self.stop.clear()
            self.thread = threading.Thread(target=self.run, args=(action, payload), daemon=True)
            self.thread.start()
            return rec

    def halt(self) -> None:
        self.stop.set()


def _title_overlap(published: str, recorded: str):
    """How much a recorded title has in common with the title the document gives for itself.

    Returns None when the difference is cosmetic — a section number, a site name, a trailing "— pandas user guide"
    — because one contains the other and the recorded title is often the more useful of the two. Otherwise the
    share of words they have in common, so a caller can tell a paraphrase from a different work entirely.
    """
    a, b = pipeline.norm(published), pipeline.norm(recorded)
    if not a or not b or a in b or b in a:
        return None
    wa = {w for w in re.findall(r"[a-z]{4,}", a)}
    wb = {w for w in re.findall(r"[a-z]{4,}", b)}
    if not wa or not wb:
        return None
    return len(wa & wb) / min(len(wa), len(wb))


# Below this, the recorded title is treated as naming a different work and the document's own title is used.
# Between this and TITLE_SAME it is a paraphrase: the recorded title stands, and the difference is shown.
TITLE_DIFFERENT = 0.34
TITLE_SAME = 0.7


def measured_coverage(data: bytes) -> dict:
    """What this file actually holds, counted by Loom from its own bytes.

    A teaching copy used to inherit the description written for the original it came from, so a long-form file of
    232 rows still said "wide, 20 data rows, ten fill codes, 13 header lines". That description then travelled into
    writer prompts and packs. What a model or a person wrote about a file stays under `provenance`; this is
    separate, and it is measured, not described.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"readable": False, "note": "not UTF-8 text, so nothing was counted"}
    lines = text.splitlines()
    end = next((i for i, l in enumerate(lines) if "-END HEADER-" in l), -1)
    header_lines = end + 1 if end >= 0 else 0
    cols = lines[header_lines].split(",") if len(lines) > header_lines else []
    rows = max(0, len(lines) - header_lines - 1)
    def is_fill(f: str) -> bool:
        try:
            return float(f) == -999.0   # the publisher writes it as -999 or -999.00
        except ValueError:
            return False
    fill = sum(1 for l in lines[header_lines + 1:] for f in l.split(",") if is_fill(f))
    return {"readable": True, "preambleLinesBeforeTheColumnNames": header_lines,
            "columnNames": [c.strip() for c in cols], "dataRows": rows,
            "fillCodeMinus999Values": fill,
            "layout": "long: one row per observation" if "MONTH_NUM" in text.split("\n", 1)[0] or (cols and "MONTH" in [c.strip() for c in cols]) else "wide: one row per measure per year",
            "countedBy": "Loom, from this file's own bytes"}


PROVENANCE_KEYS = ("publisher", "publisherUrl", "requestUrl", "retrievedAt", "serviceVersion", "licenceNote", "fields", "coverage", "limitations")


def register_prepared(store, cid: str, items: list) -> list:
    """Files prepared BEFORE the outline is approved, with where each came from. Originals are kept exactly. A changed copy for teaching is a separate file with its parent and a step-by-step log.

    Nothing here is written by a model. Loom computes each checksum itself and refuses a claim that does not match the bytes.
    """
    import hashlib
    r = runner(store, cid)
    with r.lock:
        if r.busy():
            raise storage.Conflict("Loom is working on this course. Prepared files are added between requests.", 0)
        rec = r.load()
        if rec is None:
            raise storage.StoreError("Nothing has been started for this course yet.")
        have = {x["name"]: x for x in rec.get("prepared") or []}
        out = list(rec.get("prepared") or [])
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict) or not isinstance(it.get("text"), str) or not isinstance(it.get("provenance"), dict):
                raise storage.StoreError("A prepared file needs its text and its provenance.")
            data, pv, kind = it["text"].encode("utf-8"), it["provenance"], it.get("kind")
            if kind not in ("original", "teaching_copy"):
                raise storage.StoreError("A prepared file is either an original or a teaching copy.")
            digest = hashlib.sha256(data).hexdigest()
            if pv.get("sha256") and pv["sha256"] != digest:
                raise storage.StoreError(f"The checksum given for {it.get('name')} does not match its bytes.")
            if kind == "original":
                missing = [k for k in PROVENANCE_KEYS if not pv.get(k)]
                if missing:
                    raise storage.StoreError(f"{it.get('name')} needs its provenance: missing {', '.join(missing)}.")
                if pv.get("transformation") not in (None, "none"):
                    raise storage.StoreError("An original is kept exactly as published. A changed file is a teaching copy.")
            else:
                parent = pv.get("derivedFromSha256")
                if not any(x.get("sha256") == parent and x.get("kind") == "original" for x in out) or not [x for x in pv.get("transformationLog") or [] if str(x).strip()] or pv.get("plantedProblems") not in (True, False):
                    raise storage.StoreError("A teaching copy names the original it came from by checksum, gives a step-by-step transformation log, and says whether problems were planted in it.")
            if it["name"] in have and have[it["name"]]["sha256"] != digest:
                raise storage.StoreError(f"A different file called {it['name']} is already registered. Prepared files are never replaced.")
            storage.save_prepared_file(store, cid, it["name"], data)
            entry = {"name": it["name"], "kind": kind, "sha256": digest, "bytes": len(data), "registeredAt": storage.now_iso(),
                     "provenance": pv, "purpose": _txt(it.get("purpose")), "measured": measured_coverage(data)}
            out = [x for x in out if x["name"] != it["name"]] + [entry]
        rec["prepared"] = out
        r.save(rec)
        return [dict(x) for x in out]


def prepared_assets(store, cid: str, rec: dict) -> list:
    """Prepared files as course assets, so sessions and projects can use them by exact name and code can be run on them.

    The bytes are found from the file's name under this course's own folder, never from a path saved earlier,
    so a restored backup still delivers them. A file that is registered but missing is reported, not skipped
    in silence: a writer must never be told a dataset exists when its bytes are gone.
    """
    out = []
    for x in rec.get("prepared") or []:
        try:
            text = storage.read_prepared(store, cid, x["name"], x.get("sha256")).decode("utf-8")
        except (OSError, UnicodeDecodeError, storage.StoreError, storage.NotFound) as e:
            raise storage.StoreError(str(e) if isinstance(e, storage.StoreError) else f"The prepared file {x['name']} could not be read.")
        out.append({"name": x["name"], "kind": "dataset", "language": "", "purpose": x.get("purpose") or "Prepared before approval", "provenance": "public_source" if x["kind"] == "original" else "authored", "source_id": "PREPARED", "run": "no_run", "expected_output": "", "content": text, "prepared": True})
    return out


def prepared_manifest(store, cid: str, rec: dict) -> list:
    """The prepared files as the page needs them for delivery: provenance, checksum and the real bytes.

    This is what makes an export able to hand over the original itself instead of a filename a model typed.
    A file whose bytes are missing or no longer match its checksum is listed and marked, never quietly dropped:
    the page must be able to say a required file cannot be delivered.
    """
    out = []
    for x in rec.get("prepared") or []:
        e = {k: x.get(k) for k in ("name", "kind", "sha256", "bytes", "registeredAt", "provenance", "purpose")}
        e["measured"] = x.get("measured") or measured_coverage(b"")
        try:
            data = storage.read_prepared(store, cid, x["name"], x.get("sha256"))
        except (OSError, storage.StoreError, storage.NotFound) as err:
            out.append(dict(e, available=False, why=str(err)))
            continue
        try:
            e["content"] = data.decode("utf-8")
            e["encoding"] = "utf-8"
        except UnicodeDecodeError:
            e["contentBase64"] = base64.b64encode(data).decode("ascii")
            e["encoding"] = "binary"
        out.append(dict(e, available=True))
    return out


def prepared_digest(store, cid: str, rec: dict, rows: int = 8) -> list:
    """What the outline and the writers are shown: the provenance and the real first lines. Never a description made up from memory.

    Found by name under this course's own folder, so a restored backup shows the real lines rather than none.
    """
    out = []
    for x in rec.get("prepared") or []:
        try:
            lines = storage.read_prepared(store, cid, x["name"], x.get("sha256")).decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError, storage.StoreError, storage.NotFound) as e:
            raise storage.StoreError(str(e) if isinstance(e, storage.StoreError) else f"The prepared file {x['name']} could not be read.")
        head_end = next((i for i, l in enumerate(lines) if "-END HEADER-" in l), -1)
        out.append({"name": x["name"], "kind": x["kind"], "sha256": x["sha256"], "purpose": x.get("purpose"),
                    "what_loom_counted_in_this_file": x.get("measured"),
                    "how_it_was_described_when_registered": x["provenance"],
                    "the_file_starts_with": lines[:head_end + 1 + rows] if head_end >= 0 else lines[:rows + 4]})
    return out


def runner(store, cid: str) -> Runner:
    key = (storage.store_name(store), cid)
    with RUNNERS_LOCK:
        if key not in RUNNERS:
            RUNNERS[key] = Runner(store, cid)
        return RUNNERS[key]


def read(store, cid: str) -> dict | None:
    """The generation record. If the server stopped mid-work, that is said plainly and the work can be resumed.

    The material a review judged stays on disk; only its fingerprint is sent to the page, which is all the page needs
    to tell whether that review belongs to the draft it is showing.
    """
    rec = storage.read_engine(store, cid)
    if rec and rec.get("status") == "running" and not runner(store, cid).busy():
        rec["status"] = "paused"
        rec["now"] = None
        rec["pause"] = {"kind": "interrupted", "reason": "Loom's local server stopped while this was unfinished. Finished parts are saved.", "detail": "", "at": storage.now_iso()}
        for u in rec["stages"]["materials"]["sessions"]:
            if u.get("status") == "running":
                u["status"] = "todo"
        Runner.settle_paused(rec)
        for e in rec["edits"].values():
            if e.get("status") in ("running", "todo"):
                e["status"] = "paused"
        storage.write_engine(store, cid, rec)
    elif rec and rec.get("now") and rec.get("status") != "running" and not runner(store, cid).busy():
        # `now` says what Loom is doing at this moment. At rest there is nothing, and a label left behind reads on
        # the progress screen as though a request were still going. The record of what ran is `calls`, which is kept.
        rec["now"] = None
        storage.write_engine(store, cid, rec)
    if rec and isinstance(rec.get("stages", {}).get("review"), dict) and rec["stages"]["review"].get("input") is not None:
        rec = dict(rec, stages=dict(rec["stages"], review={k: v for k, v in rec["stages"]["review"].items() if k != "input"}))
    if rec and isinstance(rec.get("stages", {}).get("research"), dict) and (rec["stages"]["research"].get("cache") or rec["stages"]["research"].get("batches")):
        # What the page needs from the research is its result. The pages kept for reuse, and each batch's own copy, stay on disk.
        r = dict(rec["stages"]["research"])
        r.pop("cache", None)
        r.pop("links", None)
        r["batches"] = [{k: v for k, v in b.items() if k != "output"} for b in r.get("batches") or []]
        rec = dict(rec, stages=dict(rec["stages"], research=r))
    return rec

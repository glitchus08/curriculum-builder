"""Checks for the generation engine, using the test double instead of Claude.

These rehearse failure, pause and resume. They use no subscription and prove nothing about the quality of real answers.
Run: python3 -m unittest discover -s tests/server -t .
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = os.environ.setdefault("LOOM_DATA_DIR", tempfile.mkdtemp(prefix="loom-test-"))
HERE = Path(__file__).resolve().parent.parent
os.environ["LOOM_CLAUDE_BIN"] = str(HERE / "fake_claude.py")
os.environ["LOOM_SKIP_LINK_CHECK"] = "1"
os.environ["ANTHROPIC_API_KEY"] = "sk-this-must-never-reach-the-tool"
os.environ["CLAUDECODE"] = "1"

from loom_server import engine, storage  # noqa: E402

BRIEF = {"format": "Workshop", "topics": ["Marketing", "Design", "Development"], "mode": "shared", "audience": "College students", "prior": "Some basics", "priorKey": "some", "outcome": "Launch a page", "delivery": "In a room", "requirements": []}
PLAN = {"sessions": 3, "minutes": [60, 60, 60], "unit": "Block", "total": 180}


def plan_file(name, **kw):
    f = Path(TMP) / f"plan-{name}.json"
    f.write_text(json.dumps({"calls": 0, **kw}))
    os.environ["FAKE_CLAUDE_PLAN"] = str(f)
    return f


def course(name, brief=BRIEF, plan=PLAN):
    c = storage.create_course("engine", json.dumps({"v": 1}), name)
    return c["id"]


def wait(cid, want=("paused", "waiting_approval", "done"), limit=40):
    end = time.time() + limit
    while time.time() < end:
        r = engine.runner("engine", cid)
        rec = engine.read("engine", cid)
        if rec and rec["status"] in want and not r.busy():
            return rec
        time.sleep(0.1)
    raise AssertionError("the engine did not settle: " + json.dumps(engine.read("engine", cid))[:400])


def go(cid, action, **payload):
    engine.runner("engine", cid).start(action, {"action": action, **payload})
    return wait(cid)


class Engine(unittest.TestCase):
    def full(self, cid):
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        self.assertEqual(rec["status"], "waiting_approval")
        return go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])

    def test_whole_path_and_incremental_saving(self):
        f = plan_file("full")
        cid = course("full")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        self.assertEqual(rec["status"], "waiting_approval")
        self.assertEqual(rec["stages"]["materials"]["sessions"][0]["status"], "todo", "no lesson is written before the outline is approved")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
        self.assertEqual(rec["status"], "done")
        self.assertTrue(all(u["status"] == "done" for u in rec["stages"]["materials"]["sessions"]))
        self.assertEqual(rec["stages"]["review"]["status"], "done")
        for i, u in enumerate(rec["stages"]["materials"]["sessions"]):
            self.assertEqual(sum(a["minutes"] for a in u["output"]["activities"]), PLAN["minutes"][i])
        log = json.loads(f.read_text())["log"]
        self.assertEqual([c["stage"] for c in log], ["research", "outline", "materials", "materials", "materials", "review"])
        self.assertEqual(log[0]["tools"], "WebSearch,WebFetch")
        self.assertTrue(all(c["tools"] == "" for c in log[1:]), "only research may use the web; nothing else gets any tool")
        self.assertFalse(any(c["has_api_env"] or c["has_claude_env"] for c in log), "no API key or host settings reach the tool")

    def test_sources_record_what_was_really_opened(self):
        plan_file("sources")
        cid = course("sources")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        out = rec["stages"]["research"]["output"]
        a, b = out["sources"]
        self.assertTrue(a["openedByAI"])
        self.assertFalse(b["openedByAI"], "a page Loom never saw opened is not recorded as read")
        self.assertEqual(b["strength"], "background")
        self.assertIn("no record", b["limits"])
        for s in out["sources"]:
            self.assertTrue(s["askedAt"])
            self.assertEqual(bool(s["retrievedAt"]), s["openedByAI"], "only a page that arrived has a retrieval date")
            self.assertIsNone(s["personChecked"], "nothing is marked as checked by a person automatically")
            self.assertFalse(s["link"]["opened"])
        self.assertEqual(out["not_opened"][0]["title"], "Seen only in results")

    def test_a_page_that_did_not_arrive_is_never_recorded_as_read(self):
        for how, state in [("ok", "retrieved"), ("error", "failed"), ("redirect", "redirected"), ("short", "failed"), ("none", "no_result")]:
            plan_file("fetch-" + how, fetch=how)
            cid = course("fetch-" + how)
            rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
            out = rec["stages"]["research"]["output"]
            first, never = out["sources"]
            self.assertEqual(first["fetch"], state, how)
            self.assertEqual(first["openedByAI"], how == "ok", how)
            self.assertEqual(first["strength"], "direct" if how == "ok" else "background", how)
            self.assertEqual(first["retrievedAt"] is not None, how == "ok", how)
            self.assertEqual(out["pagesOpened"], [first["url"]] if how == "ok" else [], how)
            self.assertEqual(len(out["pagesAskedFor"]), 1, how)
            self.assertEqual((never["fetch"], never["openedByAI"], never["strength"]), ("none", False, "background"))
        # a result that names a request nobody made, or arrives twice, changes nothing
        plan_file("fetch-stray", fetch="error", extra_results=[{"type": "tool_result", "tool_use_id": "t99", "content": "A long and convincing page of text that belongs to some other request entirely."}, "junk", {"type": "text", "text": "x"}])
        rec = go(course("fetch-stray"), "begin", brief=BRIEF, plan=PLAN, digest="d")
        self.assertEqual(rec["stages"]["research"]["output"]["sources"][0]["fetch"], "failed")
        for result, want in [({"is_error": True, "content": "HTTP 403"}, "failed"), ({"content": [{"type": "text", "text": "x" * 80}]}, "retrieved"), ({"content": None}, "failed"), ({}, "failed"),
                             ({"content": "Error: unable to reach the host after several attempts, giving up now"}, "failed")]:
            self.assertEqual(engine.fetch_outcome(result)["state"], want, str(result)[:50])

    def test_the_source_must_state_the_claim_itself_for_it_to_be_a_fact(self):
        plan_file("support")
        out = self.full(course("support"))["stages"]["materials"]["sessions"][0]["output"]
        fact = [c for c in out["claims"] if c["type"] == "fact"][0]
        check = lambda support: engine.check_session(dict(out, claims=[dict(fact, support=support)]), BRIEF, 60, BRIEF["topics"], {"S1": "direct"})
        self.assertEqual(check("stated_by_source"), [])
        self.assertIn("only in part", check("partly")[0])
        self.assertIn("not at all", check("not_from_source")[0])

    def test_a_review_interrupted_by_a_usage_limit_resumes_on_the_material_that_was_submitted(self):
        """The team edits the draft, sends it for review, the plan's limit stops it, and Resume judges what they sent.

        Before this was fixed, the resume fell back to what Claude first generated, so the review read the wrong material
        and could still be presented as a review of the edited draft.
        """
        EDITED, ORIGINAL = "EDITED-BY-THE-TEAM-MARKER", "TEST DOUBLE goal for First attempt"
        f = plan_file("review-resume", watch=[EDITED, ORIGINAL])
        cid = course("review-resume")
        rec = self.full(cid)
        self.assertEqual(rec["status"], "done")
        generated = [dict(u["output"], number=i + 1, minutes=PLAN["minutes"][i]) for i, u in enumerate(rec["stages"]["materials"]["sessions"])]
        self.assertIn(ORIGINAL, json.dumps(generated), "the generated material carries the original wording")

        # The team edits the draft, then asks for a review of exactly that.
        edited = json.loads(json.dumps(generated))
        for s in edited:
            s["activities"][1]["goal"] = EDITED
            s["activities"][1]["instructions"] = [EDITED + " step one.", "Step two."]
        self.assertNotIn(ORIGINAL, json.dumps(edited))

        # The next call to Claude fails with a usage limit.
        calls_so_far = json.load(open(f))["calls"]
        plan_file("review-resume", calls=calls_so_far, watch=[EDITED, ORIGINAL], fail={str(calls_so_far + 1): "limit"})
        rec = go(cid, "review", sessions=edited)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual(rec["pause"]["kind"], "limit")
        st = storage.read_engine("engine", cid)["stages"]["review"]
        self.assertEqual(st["status"], "todo", "the review is waiting, not done")
        request_id, fingerprint = st["requestId"], st["inputFingerprint"]
        self.assertTrue(request_id and fingerprint)
        self.assertEqual(st["inputOrigin"], "submitted")
        self.assertEqual(st["input"], edited, "the exact material submitted is kept with the request")
        self.assertEqual(fingerprint, engine.content_print(edited))

        # The page is never handed the whole reviewed material, only the fingerprint it needs.
        self.assertNotIn("input", engine.read("engine", cid)["stages"]["review"])
        self.assertEqual(engine.read("engine", cid)["stages"]["review"]["inputFingerprint"], fingerprint)

        # Resume. The review must judge the edited material, not what Claude first wrote.
        rec = go(cid, "resume")
        self.assertEqual(rec["stages"]["review"]["status"], "done")
        review_calls = [c for c in json.load(open(f))["log"] if c["stage"] == "review"]
        self.assertTrue(review_calls, "a review request was made")
        last = review_calls[-1]
        self.assertIn(EDITED, last["marks"], "the resumed review was sent the team's edited material")
        self.assertNotIn(ORIGINAL, last["marks"], "the resumed review was not sent the original generated material")

        # The result stays bound to the request it belongs to, and to the material it judged.
        done = storage.read_engine("engine", cid)["stages"]["review"]
        self.assertEqual(done["requestId"], request_id)
        self.assertEqual(done["inputFingerprint"], fingerprint)
        self.assertEqual(done["input"], edited)
        self.assertNotEqual(fingerprint, engine.content_print(generated), "the two materials do not share a fingerprint")

    def test_topic_ideas_rest_only_on_dated_pages_that_arrived_and_a_failed_search_says_so(self):
        """Trending and next topics are researched, not made up. Only a page that opened AND shows a date can back one."""
        plan_file("ideas")
        cid = course("ideas")
        engine.runner("engine", cid).start("ideas", {"action": "ideas", "kind": "trending", "hint": "short courses"})
        rec = wait(cid, want=("idle", "paused", "done"))
        self.assertEqual(rec["status"], "idle", "asking for ideas does not start a generation run")
        ideas = storage.read_ideas("engine", cid)
        self.assertEqual(ideas["status"], "done")
        self.assertEqual(ideas["kind"], "trending")
        self.assertEqual(ideas["searchedOn"], "2026-09-29")
        names = [i["idea"] for i in ideas["ideas"]]
        self.assertEqual(len(names), 3)
        backed = [i for i in ideas["ideas"] if i["backed"]]
        self.assertEqual([i["idea"] for i in backed], ["TEST DOUBLE idea with a dated page"])
        self.assertEqual(backed[0]["evidence"][0]["dated"], "3 March 2026")
        self.assertTrue(backed[0]["evidence"][0]["openedByAI"])
        self.assertEqual(ideas["backedCount"], 1)
        self.assertEqual(set(ideas["unbacked"]), {"TEST DOUBLE idea whose page never arrived", "TEST DOUBLE idea with an undated page"})
        never = next(i for i in ideas["ideas"] if "never arrived" in i["idea"])
        self.assertEqual(never["evidence"], [], "a page that did not arrive backs nothing")
        self.assertFalse(never["unconfirmed"][0]["openedByAI"])
        undated = next(i for i in ideas["ideas"] if "undated" in i["idea"])
        self.assertEqual(undated["evidence"], [], "a page with no date cannot speak for currency")
        self.assertIn("only one idea", ideas["shortfall"])
        self.assertEqual(len(ideas["pagesOpened"]), 1)
        # The course record was not turned into a generation run by asking for ideas.
        self.assertEqual(storage.read_engine("engine", cid)["stages"]["research"]["status"], "todo")
        # A search stopped by the plan's limit is recorded as failed, with the reason, and nothing illustrative is put in its place.
        plan_file("ideas-limit", fail={"1": "limit"})
        cid2 = course("ideas-limit")
        engine.runner("engine", cid2).start("ideas", {"action": "ideas", "kind": "next"})
        rec = wait(cid2, want=("idle", "paused", "done"))
        self.assertEqual(rec["status"], "paused")
        failed = storage.read_ideas("engine", cid2)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("limit", failed["reason"].lower())
        self.assertNotIn("ideas", failed)

    def test_each_delivery_mode_and_a_short_talk_reach_the_writer_as_rules_and_are_accepted(self):
        """A fixture run, not real content: it proves the rule for each delivery mode is in the request that writes the
        sessions, and that the test double's answer passes Loom's checks under that mode. It says nothing about quality."""
        cases = [
            ("live", "workshop", [60, 60, 60], "Delivery is ONLINE AND LIVE"),
            ("hybrid", "workshop", [45], "Delivery is ROOM AND ONLINE TOGETHER"),
            ("self", "course", [30], "Delivery is SELF-PACED"),
            ("blended", "course", [60, 60], "Delivery is BLENDED"),
            ("room", "workshop", [50], "Delivery is IN A ROOM"),
            ("live", "talk", [20, 25], "This is SHORT"),
        ]
        for delivery, fmt, minutes, phrase in cases:
            with self.subTest(delivery=delivery, fmt=fmt):
                plan_file(f"mode-{delivery}-{fmt}", watch=[phrase])
                cid = course(f"mode-{delivery}-{fmt}")
                brief = dict(BRIEF, deliveryKey=delivery, formatKey=fmt, delivery=delivery)
                plan = {"sessions": len(minutes), "minutes": minutes, "unit": "Part" if fmt == "talk" else "Block", "total": sum(minutes)}
                rec = go(cid, "begin", brief=brief, plan=plan, digest="d")
                self.assertEqual(rec["status"], "waiting_approval")
                rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
                self.assertEqual(rec["status"], "done", json.dumps(rec.get("pause"))[:300])
                self.assertTrue(all(u["status"] == "done" for u in rec["stages"]["materials"]["sessions"]))
                calls = [c for c in json.load(open(os.environ["FAKE_CLAUDE_PLAN"]))["log"] if c["stage"] == "materials"]
                self.assertEqual(len(calls), len(minutes))
                for c in calls:
                    self.assertIn(phrase, c["marks"], f"the {delivery} rule reached the request that wrote session {c['session']}")
                self.assertTrue(all(sum(a["minutes"] for a in u["output"]["activities"]) == m for u, m in zip(rec["stages"]["materials"]["sessions"], minutes)), "minutes reconcile")

    def test_a_short_talk_is_not_sent_back_for_missing_a_workshop_s_feedback_and_revision(self):
        """A 20-minute talk in two parts is not a small workshop, and Loom must not demand one."""
        from loom_server.engine import check_session
        talk = {"formatKey": "talk", "topics": ["Charts"], "outcome": "Spot a misleading chart"}
        workshop = {"formatKey": "workshop", "topics": ["Charts"], "outcome": "Spot a misleading chart"}
        two = {"title": "Part 1", "outcome": "You can name one way a chart misleads", "serves": "A step to the outcome",
               "activities": [{"kind": "explain", "title": "The cut axis", "goal": "Name it", "minutes": 6, "instructions": ["Watch."], "materials": [], "handout": "", "worked_example": "", "teacher": ["Point at the axis."], "misconceptions": [], "success": ["They name it."]},
                              {"kind": "discuss", "title": "Spot it", "goal": "Find one", "minutes": 4, "instructions": ["Tell your neighbour which chart misleads and how."], "materials": [], "handout": "", "worked_example": "", "teacher": ["Listen."], "misconceptions": [], "success": ["They point at the axis."]}],
               "success_criteria": ["Each person names one way a chart misleads.", "Each person points at the part of the chart that does it."],
               "application_check": {"when": "Next week", "task": "Find one misleading chart at work.", "looks_for": ["They name the technique"]},
               "claims": [], "assumptions": [], "prerequisites": [], "prerequisites_note": "", "contributions": [], "preparation": {"minutes": 5, "steps": ["Print the charts."]}}
        def shape(out, brief, minutes):
            """Only the complaints this rule is about: how many activities, and the feedback/revision cycle."""
            keep = ("activities.", "feedback", "do something", "do the task themselves")
            return [x for x in check_session(out, brief, minutes, ["Charts"], {}) if any(k in x for k in keep)]
        # As a talk, two activities with no feedback or revise step draws no complaint about its shape.
        self.assertEqual(shape(two, talk, 10), [])
        # The same content in a workshop session of the same length is still short, so it is accepted too.
        self.assertEqual(shape(two, workshop, 10), [])
        # A full-length workshop session still has to carry feedback and revision.
        long_acts = [dict(two["activities"][0], minutes=30), dict(two["activities"][1], minutes=30)]
        long_session = dict(two, activities=long_acts)
        problems = shape(long_session, workshop, 60)
        self.assertTrue(any("feedback" in x for x in problems), problems)
        self.assertTrue(any("three activities" in x for x in problems), problems)
        # Order is still enforced on a short session that does include both.
        rev = dict(two["activities"][1], kind="revise")
        fb = dict(two["activities"][0], kind="feedback")
        out_of_order = dict(two, activities=[rev, fb])
        self.assertTrue(any("Revision must come after feedback" in x for x in check_session(out_of_order, talk, 10, ["Charts"], {})), "order still matters")  # noqa: E501
        # And a short session still has to have people doing something, not only listening.
        listen_only = dict(two, activities=[two["activities"][0], dict(two["activities"][0], title="More", kind="explain")])
        self.assertTrue(any("do something" in x for x in shape(listen_only, talk, 10)))

    def test_the_server_and_the_page_fingerprint_the_same_material_the_same_way(self):
        """The comparison only means something if both halves agree. This runs the page's own code to check."""
        import subprocess
        samples = [[{"b": 1, "a": "x"}], "caf\u00e9 \u2019 quote", {"a": [1, 2, {"z": None, "y": True}], "b": "line\nbreak \"quoted\" back\\slash"},
                   [{"number": 1, "minutes": 60, "title": "Block one \u2014 money in", "activities": [{"kind": "try", "instructions": ["Type 25 in B7.", "Press Enter."]}]}]]
        mine = [engine.content_print(s) for s in samples]
        js = HERE.parent / "js" / "journey.js"
        script = "import('" + js.as_uri() + "').then(J=>console.log(JSON.stringify(" + json.dumps(samples) + ".map(s=>J.contentPrint(s)))))"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip()), mine, "the page and the server must agree on every fingerprint")

    def test_a_review_that_follows_generation_is_marked_as_judging_the_generated_material(self):
        plan_file("review-generated")
        cid = course("review-generated")
        rec = self.full(cid)
        st = storage.read_engine("engine", cid)["stages"]["review"]
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["inputOrigin"], "generated")
        self.assertTrue(st["requestId"])
        generated = [dict(u["output"], number=i + 1, minutes=PLAN["minutes"][i]) for i, u in enumerate(rec["stages"]["materials"]["sessions"])]
        self.assertEqual(st["inputFingerprint"], engine.content_print(generated))

    def test_usage_limit_pauses_and_resume_finishes_only_what_is_left(self):
        f = plan_file("limit", fail={"4": "limit"})
        cid = course("limit")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["output"])
        self.assertEqual(rec["status"], "paused")
        self.assertEqual(rec["pause"]["kind"], "limit")
        self.assertIn("limit", rec["pause"]["reason"].lower())
        s = rec["stages"]["materials"]["sessions"]
        self.assertEqual([u["status"] for u in s], ["done", "todo", "todo"])
        first = json.dumps(s[0]["output"])
        self.assertNotIn("output", s[1], "nothing is filled in for the part that failed")
        on_disk = storage.read_engine("engine", cid)
        self.assertEqual(on_disk["stages"]["materials"]["sessions"][0]["status"], "done", "the finished session was already saved")
        rec = go(cid, "resume")
        self.assertEqual(rec["status"], "done")
        self.assertEqual(json.dumps(rec["stages"]["materials"]["sessions"][0]["output"]), first, "finished work was not redone")
        stages = [c["stage"] for c in json.loads(f.read_text())["log"]]
        self.assertEqual(stages, ["research", "outline", "materials", "materials", "materials", "materials", "review"])

    def test_every_kind_of_failure_pauses_with_a_reason_and_no_invented_content(self):
        for mode, kind in [("overage", "overage"), ("api_key", "api_key"), ("auth", "auth"), ("crash", "error"), ("nonsense", "invalid")]:
            plan_file(mode, fail={"1": mode})
            cid = course(mode)
            rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
            self.assertEqual(rec["status"], "paused", mode)
            self.assertEqual(rec["pause"]["kind"], kind, mode)
            self.assertTrue(rec["pause"]["reason"], mode)
            self.assertNotIn("output", rec["stages"]["research"], mode)
            self.assertEqual(rec["stages"]["outline"]["status"], "todo", mode)
            self.assertFalse(rec["calls"][-1]["ok"], mode)
            rec = go(cid, "resume")
            self.assertEqual(rec["status"], "waiting_approval", f"{mode}: resume carries on once the cause is gone")

    def test_an_answer_that_fails_the_checks_gets_one_correction_then_stops(self):
        f = plan_file("repair", bad_minutes_on=[2])
        cid = course("repair")
        rec = self.full(cid)
        self.assertEqual(rec["status"], "done")
        log = json.loads(f.read_text())["log"]
        self.assertEqual([c["repair"] for c in log if c["stage"] == "materials"], [False, False, True, False])
        plan_file("norepair", bad_minutes_on=[2], bad_minutes_always=True)
        cid = course("norepair")
        rec = self.full(cid)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual(rec["pause"]["kind"], "invalid")
        self.assertIn("add up", rec["pause"]["detail"])
        s = rec["stages"]["materials"]["sessions"]
        self.assertEqual([u["status"] for u in s], ["done", "failed", "todo"])
        self.assertNotIn("output", s[1])

    def test_stop_halts_and_keeps_finished_work(self):
        plan_file("stop", fail={"3": "hang"})
        cid = course("stop")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        r = engine.runner("engine", cid)
        r.start("approve_outline", {"outline": rec["stages"]["outline"]["output"]})
        time.sleep(1.2)
        self.assertTrue(r.busy())
        with self.assertRaises(storage.Conflict):
            r.start("resume", {})
        r.halt()
        rec = wait(cid)
        self.assertEqual(rec["pause"]["kind"], "stopped")
        self.assertEqual(rec["stages"]["research"]["status"], "done")

    def test_an_interrupted_server_is_reported_and_can_resume(self):
        plan_file("interrupt")
        cid = course("interrupt")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        rec["status"] = "running"
        rec["stages"]["materials"]["sessions"][0]["status"] = "running"
        storage.write_engine("engine", cid, rec)
        engine.RUNNERS.clear()
        seen = engine.read("engine", cid)
        self.assertEqual(seen["status"], "paused")
        self.assertEqual(seen["pause"]["kind"], "interrupted")
        self.assertEqual(seen["stages"]["materials"]["sessions"][0]["status"], "todo")

    def test_outline_rules(self):
        plan_file("outline")
        cid = course("outline")
        rec = go(cid, "begin", brief=BRIEF, plan=PLAN, digest="d")
        good = rec["stages"]["outline"]["output"]
        self.assertEqual(engine.check_outline(json.loads(json.dumps(good)), BRIEF, PLAN), [])
        def broken(f):
            o = json.loads(json.dumps(good)); f(o); return engine.check_outline(o, BRIEF, PLAN)
        self.assertTrue(any("exactly 3" in p for p in broken(lambda o: o["sessions"].pop())))
        self.assertTrue(any("contributes" in p for p in broken(lambda o: o["sessions"][0].update(contributions=[]))))
        self.assertTrue(any("exact names" in p for p in broken(lambda o: o["sessions"][0].update(topics=["Astrology"]))))
        self.assertTrue(any("not an earlier" in p for p in broken(lambda o: o["sessions"][0].update(builds_on=[2]))))
        def only_marketing(o):
            for s in o["sessions"]:
                s["topics"] = ["Marketing"]
        self.assertTrue(any("No session teaches Design" in p for p in broken(only_marketing)))
        sep = dict(BRIEF, mode="separate")
        self.assertTrue(any("keep them separate" in p for p in engine.check_outline(json.loads(json.dumps(good)), sep, PLAN)))
        with self.assertRaises(storage.StoreError):
            engine.runner("engine", cid).start("approve_outline", {"outline": {"sessions": []}})
        rec = go(cid, "revise_outline", feedback="Make session 1 about research")
        self.assertIn("(revised)", rec["stages"]["outline"]["output"]["sessions"][0]["title"])
        self.assertEqual(rec["stages"]["outline"]["feedback"][0]["text"], "Make session 1 about research")
        self.assertFalse(rec["stages"]["outline"]["approved"])

    def test_session_rules_catch_what_a_teacher_would_need(self):
        plan_file("rules")
        cid = course("rules")
        rec = self.full(cid)
        good = rec["stages"]["materials"]["sessions"][0]["output"]
        ids = {"S1", "S2"}
        check = lambda o: engine.check_session(o, BRIEF, 60, BRIEF["topics"], ids)
        self.assertEqual(check(json.loads(json.dumps(good))), [])
        def broken(f):
            o = json.loads(json.dumps(good)); f(o); return " | ".join(check(o))
        self.assertIn("exactly 60", broken(lambda o: o["activities"][1].update(minutes=99)))
        self.assertIn("feedback", broken(lambda o: o["activities"].__setitem__(2, dict(o["activities"][2], kind="discuss"))))
        self.assertIn("success criteria", broken(lambda o: o.update(success_criteria=["one"])))
        self.assertIn("application check", broken(lambda o: o.update(application_check={"when": "", "task": "", "looks_for": []})))
        self.assertIn("prerequisites", broken(lambda o: o.update(prerequisites=[], prerequisites_note="")))
        self.assertIn("contributes", broken(lambda o: o.update(contributions=[])))
        self.assertIn("not in the list", broken(lambda o: o["claims"].append({"text": "x", "type": "fact", "sources": ["S99"], "note": ""})))
        self.assertIn("cites no source", broken(lambda o: o["claims"].append({"text": "x", "type": "fact", "sources": [], "note": ""})))
        self.assertIn("two instruction steps", broken(lambda o: o["activities"][1].update(instructions=["Do it."])))
        self.assertIn("prepares before", broken(lambda o: o.update(preparation={"minutes": 10, "steps": []})))

    def test_scoped_edits(self):
        plan_file("edit")
        cid = course("edit")
        rec = self.full(cid)
        s1 = rec["stages"]["materials"]["sessions"][0]["output"]
        part = {"number": 1, "minutes": 60, "topics": BRIEF["topics"], "content": s1}
        rec = go(cid, "edit", editId="e0000001", scope="session", instruction="Make the outcome sharper", parts=[part], baseRev=3, baseUid="j1")
        e = rec["edits"]["e0000001"]
        self.assertEqual(e["status"], "done")
        self.assertTrue(e["parts"][0]["output"]["acted"])
        self.assertIn("changed on request", e["parts"][0]["output"]["session"]["outcome"])
        self.assertEqual(rec["stages"]["materials"]["sessions"][0]["output"], s1, "the generated record is not rewritten by an edit")
        self.assertEqual((e["baseRev"], e["baseUid"]), (3, "j1"))
        rec = go(cid, "edit", editId="e0000002", scope="activity", instruction="This is unclear", parts=[dict(part, activity=s1["activities"][1])])
        self.assertFalse(rec["edits"]["e0000002"]["parts"][0]["output"]["acted"])
        plan_file("edit-limit", fail={"2": "limit"})
        parts = [dict(part, number=i + 1, content=rec["stages"]["materials"]["sessions"][i]["output"]) for i in range(3)]
        rec = go(cid, "edit", editId="e0000003", scope="journey", instruction="More practice", parts=parts)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual([p["status"] for p in rec["edits"]["e0000003"]["parts"]], ["done", "todo", "todo"])
        rec = go(cid, "resume")
        self.assertEqual([p["status"] for p in rec["edits"]["e0000003"]["parts"]], ["done", "done", "done"])
        self.assertEqual(rec["status"], "done")

    def test_later_sessions_are_given_what_earlier_sessions_produced(self):
        f = plan_file("carry")
        cid = course("carry")
        rec = self.full(cid)
        self.assertEqual(rec["status"], "done")
        log = [x for x in json.loads(f.read_text())["log"] if x["stage"] == "materials"]
        self.assertEqual([(x["session"], x["carried"]) for x in log], [("1", []), ("2", ["1"]), ("3", ["1", "2"])])
        self.assertEqual([x["continuity_rule"] for x in log], [False, True, True])
        self.assertFalse(any(x["saw_teacher_notes"] for x in log), "teacher notes of other sessions are not needed and are left out")

    def test_a_session_written_after_the_team_edited_uses_the_teams_version(self):
        f = plan_file("carry-draft", fail={"5": "limit"})
        cid = course("carry-draft")
        rec = self.full(cid)
        self.assertEqual([u["status"] for u in rec["stages"]["materials"]["sessions"]], ["done", "done", "todo"])
        mine = dict(rec["stages"]["materials"]["sessions"][0]["output"])
        mine["activities"] = [dict(a, handout="TEST DOUBLE handout made in session 77") if a["kind"] == "try" else a for a in mine["activities"]]
        rec = go(cid, "resume", written=[{"number": 1, "content": mine}, {"number": 9, "content": mine}, {"number": True, "content": mine}, "junk"])
        self.assertEqual(rec["status"], "done")
        last = [x for x in json.loads(f.read_text())["log"] if x["stage"] == "materials"][-1]
        self.assertEqual((last["session"], last["carried"]), ("3", ["2", "77"]))

    def test_a_change_request_is_shown_the_rest_of_the_course(self):
        f = plan_file("carry-edit")
        cid = course("carry-edit")
        rec = self.full(cid)
        outs = [u["output"] for u in rec["stages"]["materials"]["sessions"]]
        rec = go(cid, "edit", editId="fit1", scope="session", instruction="Use the same files as the first session.", baseRev=1, baseUid="j",
                 parts=[{"number": 2, "minutes": 60, "topics": BRIEF["topics"], "content": outs[1], "buildsOn": [1]}], context=[{"number": i + 1, "content": o} for i, o in enumerate(outs)])
        self.assertEqual(rec["edits"]["fit1"]["status"], "done")
        last = json.loads(f.read_text())["log"][-1]
        self.assertEqual((last["stage"], last["carried"], last["saw_teacher_notes"]), ("edit", ["1", "2", "3"], False))
        self.assertNotIn("teacher", json.dumps(rec["edits"]["fit1"]["others"]))

    def test_approving_again_puts_the_written_sessions_aside_first(self):
        plan_file("again")
        cid = course("again")
        rec = self.full(cid)
        self.assertEqual(rec["status"], "done")
        plan_file("again-fails", fail={"1": "limit"})
        rec = go(cid, "approve_outline", outline=rec["stages"]["outline"]["approved_outline"])
        self.assertEqual(rec["status"], "paused")
        self.assertFalse(any(u.get("output") for u in rec["stages"]["materials"]["sessions"]))
        kept = sorted((storage.course_dir("engine", cid) / "engine-history").glob("*.json"))
        self.assertEqual(len(kept), 1)
        old = json.loads(kept[0].read_text())
        self.assertEqual([u["status"] for u in old["stages"]["materials"]["sessions"]], ["done", "done", "done"])
        self.assertTrue(all(u["output"]["activities"] for u in old["stages"]["materials"]["sessions"]))
        self.assertEqual(old["stages"]["review"]["status"], "done")

    def test_a_waiting_request_can_be_stopped_and_shutdown_stops_running_ones(self):
        plan_file("queue", fail={"1": "hang", "2": "hang"})
        a, b = course("queue-a"), course("queue-b")
        engine.runner("engine", a).start("begin", {"action": "begin", "brief": BRIEF, "plan": PLAN, "digest": "d"})
        time.sleep(0.6)
        engine.runner("engine", b).start("begin", {"action": "begin", "brief": BRIEF, "plan": PLAN, "digest": "d"})
        time.sleep(0.3)
        t0 = time.time()
        engine.runner("engine", b).halt()
        rec = wait(b, limit=5)
        self.assertLess(time.time() - t0, 2.5)
        self.assertEqual(rec["pause"]["kind"], "stopped")
        self.assertEqual(len(list(engine.work_dir().glob("request-*.pid"))), 1)
        self.assertEqual(engine.stop_requests(), 1)
        rec = wait(a, limit=10)
        self.assertEqual(rec["status"], "paused")
        self.assertEqual(list(engine.work_dir().glob("request-*.pid")), [])

    def test_a_source_that_only_partly_supports_a_claim_cannot_make_it_a_fact(self):
        plan_file("thin")
        cid = course("thin")
        out = self.full(cid)["stages"]["materials"]["sessions"][0]["output"]
        fact = [c for c in out["claims"] if c["type"] == "fact"][0]
        self.assertEqual(fact["sources"], ["S1"])
        check = lambda strengths: engine.check_session(out, BRIEF, 60, BRIEF["topics"], strengths)
        self.assertEqual(check({"S1": "direct", "S2": "background"}), [])
        self.assertEqual(check({"S1", "S2"}), [], "a plain set of ids still works")
        for weak in ("partial", "background"):
            got = check({"S1": weak, "S2": "direct"})
            self.assertEqual(len(got), 1, got)
            self.assertIn("only in part", got[0])
        mixed = dict(out, claims=[dict(fact, sources=["S1", "S2"])])
        self.assertEqual(engine.check_session(mixed, BRIEF, 60, BRIEF["topics"], {"S1": "partial", "S2": "direct"}), [])

    def test_time_is_all_the_time_there_is_and_long_sittings_get_a_break(self):
        from loom_server import prompts
        long_day = {"sessions": 3, "minutes": [50, 50, 50], "unit": "Block", "total": 150}
        short = {"sessions": 1, "minutes": [45], "unit": "Session", "total": 45}
        weekly = {"sessions": 4, "minutes": [120] * 4, "unit": "Week", "total": 480}
        self.assertIn("kind 'break'", prompts.time_rule(long_day))
        self.assertIn("one sitting of 150 minutes", prompts.time_rule(long_day))
        self.assertNotIn("break of about", prompts.time_rule(short))
        self.assertIn("of each session", prompts.time_rule(weekly))
        for plan in (long_day, short, weekly):
            self.assertIn("ALL the time there is", prompts.time_rule(plan))
        brief = dict(BRIEF, topics=["Design"], mode=None)
        self.assertIn("ALL the time there is", prompts.outline(brief, long_day, None)[0])
        outline_out = {"sessions": [{"title": "t", "topics": ["Design"]}] * 3}
        self.assertIn("ALL the time there is", prompts.materials(brief, long_day, None, outline_out, 1)[0])
        pause = {"kind": "break", "title": "Break", "goal": "", "minutes": 10, "instructions": [], "materials": [], "handout": "", "worked_example": "", "teacher": [], "misconceptions": [], "success": []}
        self.assertEqual(engine.check_activity(pause, "The break"), [])
        self.assertTrue(engine.check_activity(dict(pause, minutes=0), "The break"))
        self.assertTrue(engine.check_activity(dict(pause, title=""), "The break"))
        self.assertTrue(engine.check_activity(dict(pause, kind="nap"), "The nap"))

    def test_a_thin_fact_is_lowered_by_loom_itself_without_another_request(self):
        f = plan_file("settle")
        cid = course("settle")
        rec = self.full(cid)
        out = json.loads(json.dumps(rec["stages"]["materials"]["sessions"][1]["output"]))
        out["claims"] = [{"text": "states it", "type": "fact", "sources": ["S1"], "support": "stated_by_source", "note": ""}, {"text": "half of it", "type": "fact", "sources": ["S1"], "support": "partly", "note": "n"},
                         {"text": "ours", "type": "fact", "sources": ["S1"], "support": "not_from_source", "note": ""}, {"text": "weak source", "type": "fact", "sources": ["S2"], "support": "stated_by_source", "note": ""}]
        self.assertEqual(engine.settle_claims(out, {"S1": "direct", "S2": "background"}), 3)
        self.assertEqual([c["type"] for c in out["claims"]], ["fact", "uncertain", "hypothesis", "uncertain"])
        self.assertIn("Loom lowered this", out["claims"][1]["note"])
        self.assertEqual(engine.check_session(out, BRIEF, 60, BRIEF["topics"], {"S1": "direct", "S2": "background"}), [])
        before = len(json.loads(f.read_text())["log"])
        outs = [u["output"] for u in rec["stages"]["materials"]["sessions"]]
        outs[1]["claims"] = [dict(c, support="partly") if c["type"] == "fact" else c for c in outs[1]["claims"]]
        rec = go(cid, "edit", editId="thin1", scope="session", instruction="Shorten the setup.", baseRev=1, baseUid="j", parts=[{"number": 2, "minutes": 60, "topics": BRIEF["topics"], "content": outs[1]}], context=[])
        self.assertEqual(rec["edits"]["thin1"]["status"], "done")
        self.assertEqual(len(json.loads(f.read_text())["log"]) - before, 1, "one request, no second one to correct a label")

    def test_billing_messages_promise_only_what_loom_can_know(self):
        for kind in ("overage", "api_key"):
            plan_file("bill-" + kind, fail={"1": kind})
            rec = go(course("bill-" + kind), "begin", brief=BRIEF, plan=PLAN, digest="d")
            self.assertEqual(rec["pause"]["kind"], kind)
            said = rec["pause"]["reason"].lower()
            for promise in ("nothing is billed", "will not use", "was about to", "cannot be charged", "no charge"):
                self.assertNotIn(promise, said, kind)
            self.assertIn("already started", said)

    def test_status_names_the_blocker(self):
        st = engine.status(force=True)
        self.assertTrue(st["ready"])
        self.assertTrue(st["testDouble"])
        old = os.environ["LOOM_CLAUDE_BIN"]
        os.environ["LOOM_CLAUDE_BIN"] = "/nonexistent/claude"
        try:
            st = engine.status(force=True)
            self.assertFalse(st["ready"])
            self.assertIn("not found", st["blocker"])
        finally:
            os.environ["LOOM_CLAUDE_BIN"] = old
            engine.status(force=True)


if __name__ == "__main__":
    unittest.main()

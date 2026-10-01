"""Checks for the course library on disk. Run: python3 -m unittest discover -s tests/server -t ."""
import json
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="loom-test-")
os.environ["LOOM_DATA_DIR"] = TMP

from loom_server import storage as st  # noqa: E402

STATE = lambda topic: json.dumps({"v": 1, "answers": {"topic": {"value": topic}}, "at": "topic"})


class Library(unittest.TestCase):
    def test_two_courses_keep_separate_work(self):
        a = st.create_course("t1", STATE("ceramics"), "Ceramics")
        b = st.create_course("t1", STATE("sql"), "SQL")
        self.assertNotEqual(a["id"], b["id"])
        st.put_course("t1", a["id"], STATE("ceramics v2"), 1, None, None, None)
        self.assertIn("ceramics v2", st.get_course("t1", a["id"])["raw"])
        self.assertEqual(st.get_course("t1", b["id"])["raw"], STATE("sql"))
        ids = [c["id"] for c in st.list_courses("t1")["courses"]]
        self.assertEqual(set(ids), {a["id"], b["id"]})

    def test_test_storage_never_reaches_the_real_library(self):
        self.assertIsNone(st.store_name(None))
        for value in ["", " ", "a", "A.B", "a b", "../../library", "x" * 200]:
            d = st.store_dir(value)
            self.assertIn("test-stores", d.parts, value)
            self.assertNotEqual(d, st.store_dir(None))
        self.assertNotEqual(st.store_dir("a.b"), st.store_dir("a_b"))
        self.assertNotEqual(st.store_dir("x" * 200), st.store_dir("x" * 40))
        real = st.create_course(None, STATE("real"), "Real")
        self.assertNotIn(real["id"], [c["id"] for c in st.list_courses("t-sep")["courses"]])
        with self.assertRaises(st.NotFound):
            st.get_course("t-sep", real["id"])

    def test_a_save_keeps_the_previous_copy(self):
        c = st.create_course("t2", STATE("one"), "One")
        m = st.put_course("t2", c["id"], STATE("two"), 1, None, None, "approve")
        self.assertEqual(m["version"], 2)
        h = st.history("t2", c["id"])
        self.assertEqual(len(h), 1)
        bundle = st.backup("t2", c["id"])
        self.assertEqual(bundle["history"][0]["raw"], STATE("one"))
        self.assertEqual(bundle["course"]["raw"], STATE("two"))

    def test_a_save_from_an_out_of_date_window_is_refused(self):
        c = st.create_course("t3", STATE("one"), "One")
        st.put_course("t3", c["id"], STATE("two"), 1, None, None, None)
        with self.assertRaises(st.Conflict) as e:
            st.put_course("t3", c["id"], STATE("stale"), 1, None, None, None)
        self.assertEqual(e.exception.current, 2)
        self.assertEqual(st.get_course("t3", c["id"])["raw"], STATE("two"))

    def test_unreadable_data_is_never_written_over_a_course(self):
        c = st.create_course("t4", STATE("one"), "One")
        with self.assertRaises(st.StoreError):
            st.put_course("t4", c["id"], "{not json", 1, None, None, None)
        self.assertEqual(st.get_course("t4", c["id"])["raw"], STATE("one"))

    def test_the_copy_being_replaced_is_always_kept(self):
        c = st.create_course("t-prev", STATE("A"), "Steps")
        v = c["version"]
        for topic in ["B", "C", "D", "E"]:
            v = st.put_course("t-prev", c["id"], STATE(topic), v, None, None, None)["version"]
        d = st.course_dir("t-prev", c["id"])
        self.assertEqual((d / "previous.json").read_text(), STATE("D"))
        self.assertEqual((d / "course.json").read_text(), STATE("E"))
        self.assertEqual([f.read_text() for f in sorted((d / "history").glob("*.json"))], [STATE("A")])
        self.assertEqual(st.backup("t-prev", c["id"])["previous"], STATE("D"))

    def test_a_bad_save_changes_nothing_and_old_windows_are_still_refused(self):
        c = st.create_course("t-bad", STATE("kept"), "Bad saves")
        d = st.course_dir("t-bad", c["id"])
        for kw in [dict(name=2026), dict(name=["x"]), dict(summary="text"), dict(reason=5), dict(base="1"), dict(base=True), dict(base=None), dict(text="NaN"), dict(text="Infinity"), dict(text='{"a": NaN}'),
                   dict(text='{"a": -Infinity}'), dict(text="5"), dict(text='"words"'), dict(text="[1]"), dict(text="null"), dict(text=None), dict(text={"v": 1})]:
            with self.assertRaises(st.StoreError, msg=str(kw)) as e:
                st.put_course("t-bad", c["id"], kw.get("text", STATE("new")), kw.get("base", 1), kw.get("name"), kw.get("summary"), kw.get("reason"))
            self.assertNotIsInstance(e.exception, st.Conflict, str(kw))
            self.assertEqual((d / "course.json").read_text(), STATE("kept"), str(kw))
            self.assertEqual(st.get_course("t-bad", c["id"])["meta"]["version"], 1, str(kw))
        st.put_course("t-bad", c["id"], STATE("window A"), 1, None, None, None)
        with self.assertRaises(st.Conflict):
            st.put_course("t-bad", c["id"], STATE("window B"), 1, None, None, None)
        self.assertEqual([p.name for p in d.iterdir() if p.name.endswith(".tmp")], [])

    def test_a_rename_counts_as_a_change(self):
        c = st.create_course("t-rn", STATE("a"), "Old name")
        m = st.rename_course("t-rn", c["id"], "New name")
        self.assertEqual(m["version"], 2)
        with self.assertRaises(st.Conflict):
            st.put_course("t-rn", c["id"], STATE("stale"), 1, "Old name", None, None)
        got = st.get_course("t-rn", c["id"])
        self.assertEqual((got["meta"]["name"], got["raw"]), ("New name", STATE("a")))
        st.put_course("t-rn", c["id"], STATE("fresh"), 2, None, None, None)
        self.assertEqual(st.get_course("t-rn", c["id"])["meta"]["name"], "New name")

    def test_archiving_puts_a_course_away_and_brings_it_back_whole(self):
        c = st.create_course("t-arc", STATE("kept"), "Put away")
        st.put_course("t-arc", c["id"], STATE("kept again"), 1, None, None, "approve")
        before = sorted(p.name for p in st.course_dir("t-arc", c["id"]).rglob("*") if p.name != "meta.json")
        m = st.archive_course("t-arc", c["id"], True)
        self.assertTrue(m["archived"])
        self.assertTrue([x for x in st.list_courses("t-arc")["courses"] if x["id"] == c["id"]][0]["archived"])
        self.assertEqual(st.get_course("t-arc", c["id"])["raw"], STATE("kept again"))
        with self.assertRaises(st.Conflict):
            st.put_course("t-arc", c["id"], STATE("stale"), 2, None, None, None)
        self.assertFalse(st.archive_course("t-arc", c["id"], False)["archived"])
        self.assertEqual(sorted(p.name for p in st.course_dir("t-arc", c["id"]).rglob("*") if p.name != "meta.json"), before)
        for bad in (None, "yes", 1):
            with self.assertRaises(st.StoreError):
                st.archive_course("t-arc", c["id"], bad)

    def test_a_copy_is_a_separate_course(self):
        c = st.create_course("t-dup", STATE("original"), "Original")
        st.write_engine("t-dup", c["id"], {"status": "running", "stages": {}, "calls": []})
        d = st.duplicate_course("t-dup", c["id"])
        self.assertNotEqual(d["id"], c["id"])
        self.assertEqual(d["name"], "Original (copy)")
        self.assertEqual(st.get_course("t-dup", d["id"])["raw"], STATE("original"))
        self.assertEqual(st.read_engine("t-dup", d["id"])["status"], "paused")
        st.put_course("t-dup", d["id"], STATE("changed copy"), 1, None, None, None)
        self.assertEqual(st.get_course("t-dup", c["id"])["raw"], STATE("original"))
        self.assertEqual(st.read_engine("t-dup", c["id"])["status"], "running")

    def test_a_name_given_on_purpose_is_kept_through_ordinary_saves(self):
        """A copy, a restored course and a renamed course hold older names inside their saved work. Saving must not bring those back."""
        c = st.create_course("t-name", STATE("original"), "Untitled course")
        self.assertFalse(c["named"])
        # A course nobody has named follows the name the page works out from the brief.
        m = st.put_course("t-name", c["id"], STATE("pottery"), 1, "Pottery", None, None)
        self.assertEqual(m["name"], "Pottery")
        d = st.duplicate_course("t-name", c["id"])
        self.assertEqual(d["name"], "Pottery (copy)")
        self.assertTrue(d["named"])
        # Another course is renamed from the list while the copy is closed.
        other = st.create_course("t-name", STATE("other"), "Untitled course")
        st.rename_course("t-name", other["id"], "Glazes for beginners")
        # The copy is opened and edited: the page sends the name held in the saved work, which is the old one.
        m = st.put_course("t-name", d["id"], STATE("pottery, edited"), d["version"], "Pottery", None, None)
        self.assertEqual(m["name"], "Pottery (copy)")
        m = st.put_course("t-name", other["id"], STATE("other, edited"), st.get_course("t-name", other["id"])["meta"]["version"], "Untitled course", None, None)
        self.assertEqual(m["name"], "Glazes for beginners")
        # Reopened after a refresh, each holds its own name and its own work.
        names = {x["id"]: x["name"] for x in st.list_courses("t-name")["courses"]}
        self.assertEqual(names, {c["id"]: "Pottery", d["id"]: "Pottery (copy)", other["id"]: "Glazes for beginners"})
        self.assertIn("pottery, edited", st.get_course("t-name", d["id"])["raw"])
        self.assertEqual(st.get_course("t-name", c["id"])["raw"], STATE("pottery"))
        # A save that changes nothing but carries the old name is not a change at all.
        v = st.get_course("t-name", d["id"])["meta"]["version"]
        self.assertEqual(st.put_course("t-name", d["id"], STATE("pottery, edited"), v, "Pottery", None, None)["version"], v)
        # A rename from the open course is the one save that changes a given name.
        m = st.put_course("t-name", d["id"], STATE("pottery, edited"), v, "Pottery for two", None, "rename")
        self.assertEqual((m["name"], m["named"]), ("Pottery for two", True))
        self.assertEqual(st.put_course("t-name", d["id"], STATE("again"), m["version"], "Pottery", None, None)["name"], "Pottery for two")
        # A restored course keeps the name it was restored under.
        r = st.restore("t-name", st.backup("t-name", c["id"]))
        self.assertTrue(r["named"])
        self.assertEqual(st.put_course("t-name", r["id"], STATE("restored, edited"), r["version"], "Pottery", None, None)["name"], r["name"])

    def test_reading_never_creates_folders(self):
        before = sorted(p.name for p in (st.data_root() / "test-stores").iterdir())
        self.assertEqual(st.list_courses("never-made")["courses"], [])
        with self.assertRaises(st.NotFound):
            st.get_course("never-made", "cabcdef123")
        self.assertIsNone(st.find_import("never-made", "o", "{}"))
        self.assertEqual(sorted(p.name for p in (st.data_root() / "test-stores").iterdir()), before)

    def test_a_backup_stays_small_enough_to_restore(self):
        big = json.dumps({"v": 1, "answers": {}, "at": "topic", "pad": "x" * 600_000})
        c = st.create_course("t-big", big, "Big")
        v = c["version"]
        keep = st.BACKUP_HISTORY_BYTES
        st.BACKUP_HISTORY_BYTES = 2_000_000
        try:
            for i in range(6):
                v = st.put_course("t-big", c["id"], big.replace('"topic"', f'"t{i}"'), v, None, None, f"event-{i}")["version"]
            b = st.backup("t-big", c["id"])
            self.assertEqual(len(st.history("t-big", c["id"])), 6)
            self.assertEqual(len(b["history"]), 3)
            self.assertEqual(b["historyLeftOut"], 3)
            self.assertEqual([h["file"] for h in b["history"]], sorted(h["file"] for h in b["history"]))
            self.assertIn("event-5", b["history"][-1]["file"], "the newest copies are the ones kept")
            m = st.restore("t-big", json.loads(json.dumps(b)))
            self.assertEqual(st.get_course("t-big", m["id"])["raw"], st.get_course("t-big", c["id"])["raw"])
        finally:
            st.BACKUP_HISTORY_BYTES = keep

    def test_a_bad_backup_leaves_nothing_behind(self):
        good = {"kind": "glitch-loom-backup", "course": {"meta": {"name": "B"}, "raw": STATE("b")}}
        count = lambda: len(st.list_courses("t-rb")["courses"])
        for bad in [dict(good, course={"raw": "NaN"}), dict(good, course={"raw": "[1]"}), dict(good, course="x"), dict(good, kind="other"), "text", 5, None]:
            with self.assertRaises(st.StoreError, msg=str(bad)[:60]):
                st.restore("t-rb", bad)
        self.assertEqual(count(), 0)
        for odd in [dict(good, history=5), dict(good, history="x"), dict(good, history=[5, None, {"file": "../../x.json", "raw": "{}"}]), dict(good, madeAt=7, engine=[1]), dict(good, course={"meta": "m", "raw": STATE("b")}),
                    dict(good, course={"meta": {"name": 9, "summary": "s"}, "raw": STATE("b")})]:
            m = st.restore("t-rb", odd)
            self.assertEqual(st.history("t-rb", m["id"]), [], str(odd)[:60])
        many = dict(good, history=[{"file": f"2026010{1 + i % 9}T0000{i:05d}Z-v{i}-auto.json", "raw": STATE(str(i))} for i in range(300)])
        m = st.restore("t-rb", many)
        self.assertEqual(len(st.history("t-rb", m["id"])), st.HISTORY_KEEP)

    def test_restore_always_makes_a_new_course(self):
        c = st.create_course("t5", STATE("one"), "One")
        st.put_course("t5", c["id"], STATE("two"), 1, None, None, "weave")
        bundle = json.loads(json.dumps(st.backup("t5", c["id"])))
        st.put_course("t5", c["id"], STATE("three"), 2, None, None, None)
        r = st.restore("t5", bundle)
        self.assertNotEqual(r["id"], c["id"])
        self.assertEqual(st.get_course("t5", r["id"])["raw"], STATE("two"))
        self.assertEqual(st.get_course("t5", c["id"])["raw"], STATE("three"), "the original is untouched")
        self.assertEqual(len(st.history("t5", r["id"])), 1)
        for bad in [{}, {"kind": "other"}, {"kind": "glitch-loom-backup", "course": {"raw": "{nope"}}, {"kind": "glitch-loom-backup", "course": {"raw": ""}}, []]:
            with self.assertRaises(st.StoreError):
                st.restore("t5", bad)

    def test_imported_browser_work_is_kept_exactly_and_only_once(self):
        raw = '{"v":1,"answers":{"topic":{"value":"my course"}},"at":"topic"  }'
        a = st.save_import("t6", "http://127.0.0.1:8790", "glitch-loom/v1", raw, "ok", [], None)
        b = st.save_import("t6", "http://127.0.0.1:8790", "glitch-loom/v1", raw, "ok", [], "cabc1234")
        self.assertFalse(a["known"])
        self.assertTrue(b["known"])
        self.assertEqual(a["hash"], b["hash"])
        self.assertEqual(st.get_import("t6", a["hash"])["raw"], raw)
        self.assertEqual(st.get_import("t6", a["hash"])["courseId"], "cabc1234")
        other = st.save_import("t6", "http://localhost:8790", "glitch-loom/v1", raw, "ok", [], None)
        self.assertNotEqual(other["hash"], a["hash"], "the same text from another browser address is kept separately")
        bad = st.save_import("t6", "http://127.0.0.1:8790", "glitch-loom/v1", "{broken", "damaged", ["not readable"], None)
        self.assertEqual(st.get_import("t6", bad["hash"])["raw"], "{broken")

    def test_course_ids_cannot_escape_the_library(self):
        for bad in ["../x", "c/../../etc", "", "C123456", "c12"]:
            with self.assertRaises(st.NotFound):
                st.get_course("t7", bad)

    def test_history_is_trimmed_but_reasoned_copies_are_kept(self):
        c = st.create_course("t8", STATE("0"), "Trim")
        v = 1
        keep = st.HISTORY_KEEP
        st.put_course("t8", c["id"], STATE("approved"), v, None, None, "approve"); v += 1
        old_gap = st.HISTORY_EVERY_SECONDS
        st.HISTORY_EVERY_SECONDS = 0
        try:
            for i in range(keep + 6):
                st.put_course("t8", c["id"], STATE(f"n{i}"), v, None, None, None); v += 1
        finally:
            st.HISTORY_EVERY_SECONDS = old_gap
        names = [h["file"] for h in st.history("t8", c["id"])]
        self.assertLessEqual(len(names), keep)
        self.assertTrue(any(n.endswith("-approve.json") for n in names))


if __name__ == "__main__":
    unittest.main()


class KeptExports(unittest.TestCase):
    """A copy of each downloaded package is kept, so an export can be shown to have existed whatever the browser did."""

    def test_a_copy_is_kept_with_its_size_and_checksum_and_the_same_file_is_kept_once(self):
        c = st.create_course("ex1", STATE("x"), "X")
        a = st.save_export("ex1", c["id"], "pack-v1.json", '{"a": 1}', 1, "structured")
        self.assertEqual((a["name"], a["bytes"], a["ver"]), ("pack-v1.json", 8, 1))
        import hashlib
        self.assertEqual(a["sha256"], hashlib.sha256(b'{"a": 1}').hexdigest())
        again = st.save_export("ex1", c["id"], "pack-v1.json", '{"a": 1}', 1, "structured")
        self.assertEqual(again["name"], "pack-v1.json", "the same bytes are not kept twice")
        other = st.save_export("ex1", c["id"], "pack-v1.json", '{"a": 2}', 1, "structured")
        self.assertEqual(other["name"], "pack-v1-1.json", "different content never replaces an earlier copy")
        self.assertEqual([e["name"] for e in st.list_exports("ex1", c["id"])], ["pack-v1-1.json", "pack-v1.json"])
        self.assertEqual(open(os.path.join(a["folder"], "pack-v1.json")).read(), '{"a": 1}')

    def test_only_plain_names_and_real_content_are_kept_and_courses_stay_apart(self):
        c = st.create_course("ex2", STATE("x"), "X")
        d = st.create_course("ex2", STATE("y"), "Y")
        for bad in ["../evil.json", "a/b.json", ".hidden.json", "x.exe", "", None, "a" * 200 + ".json"]:
            with self.assertRaises(st.StoreError, msg=str(bad)[:20]):
                st.save_export("ex2", c["id"], bad, "text", 1, "x")
        for bad in ["", None, 5]:
            with self.assertRaises(st.StoreError):
                st.save_export("ex2", c["id"], "ok.json", bad, 1, "x")
        st.save_export("ex2", c["id"], "ok.html", "<p>x</p>", 1, "teacher")
        self.assertEqual(st.list_exports("ex2", d["id"]), [])
        with self.assertRaises(st.NotFound):
            st.save_export("ex2", "cnotacourse1", "ok.json", "x", 1, "x")



class ProvenanceSurvivesBackupCopyAndRestore(unittest.TestCase):
    """A backup that leaves the provenance behind breaks "nothing is deleted" by a second route.

    Not by trimming the list, but by copying everything except the list: the restored course would begin its
    history at the restore, with no record of what was asked before or what was answered.
    """

    def _course(self, name):
        cid = st.create_course("prov", STATE(name), name)["id"]
        st.write_engine("prov", cid, {"status": "paused", "stages": {}})
        st.save_request_snapshot("prov", cid, "abc123", {"prompt": "the whole ask", "schema": {"a": 1}})
        st.archive_judgements("prov", cid, "claim-key-one", [{"runId": "r1", "verdict": "yes"}])
        st.archive_judgements("prov", cid, "claim-key-one", [{"runId": "r2", "verdict": "no"}])
        return cid

    def test_a_backup_carries_the_kept_requests_and_the_archived_judgements(self):
        b = st.backup("prov", self._course("backup-carries"))
        self.assertIn("provenance", b, "a backup without the provenance restores a course with no past")
        self.assertEqual(len(b["provenance"]["requests"]), 1)
        self.assertEqual(len(b["provenance"]["judgements"]), 1, "one file per source key, holding both runs")
        self.assertIn("the whole ask", b["provenance"]["requests"][0]["raw"])

    def test_restoring_that_backup_brings_them_back_readable(self):
        new = st.restore("prov", st.backup("prov", self._course("restore-brings-back")))["id"]
        self.assertEqual(st.read_request_snapshot("prov", new, "abc123")["prompt"], "the whole ask")
        got = [e.get("runId") for e in st.read_archived_judgements("prov", new, "claim-key-one")]
        self.assertEqual(got, ["r1", "r2"], "every archived judgement came back, in order")

    def test_copying_a_course_carries_them_too(self):
        new = st.duplicate_course("prov", self._course("copy-carries"))["id"]
        self.assertIsNotNone(st.read_request_snapshot("prov", new, "abc123"))
        self.assertEqual(len(st.read_archived_judgements("prov", new, "claim-key-one")), 2)

    def test_the_original_is_untouched_by_either(self):
        cid = self._course("original-untouched")
        st.restore("prov", st.backup("prov", cid))
        st.duplicate_course("prov", cid)
        self.assertEqual(len(st.read_archived_judgements("prov", cid, "claim-key-one")), 2)

    def test_a_restore_cannot_be_made_to_write_outside_the_course(self):
        b = st.backup("prov", self._course("no-escape"))
        b["provenance"] = {"requests": [{"file": "../../escaped.json", "raw": "{}"},
                                        {"file": "ok.json", "raw": '{"prompt": "kept"}'}], "judgements": []}
        new = st.restore("prov", b)["id"]
        self.assertFalse((st.store_dir("prov") / "escaped.json").exists(), "a name is checked before it is written")
        self.assertTrue((st.course_dir("prov", new) / "requests" / "ok.json").exists())

    def test_a_kept_request_is_written_once_and_not_replaced(self):
        cid = self._course("immutable")
        st.save_request_snapshot("prov", cid, "abc123", {"prompt": "something else entirely"})
        self.assertEqual(st.read_request_snapshot("prov", cid, "abc123")["prompt"], "the whole ask")


class BackupRefusesWhatIsNotTheCourse(unittest.TestCase):
    """A backup must contain the course and nothing else, and must say what it could not carry."""

    def _course(self, name):
        cid = st.create_course("sym", STATE(name), name)["id"]
        st.write_engine("sym", cid, {"status": "paused", "stages": {}})
        st.save_request_snapshot("sym", cid, "abc123", {"prompt": "real"})
        return cid

    def test_a_link_pointing_out_of_the_course_is_not_read_into_the_backup(self):
        cid = self._course("symlink")
        outside = st.store_dir("sym").parent / "OUTSIDE-SECRET.json"
        outside.write_text('{"not":"part of this course"}', encoding="utf-8")
        (st.course_dir("sym", cid) / "requests" / "linked.json").symlink_to(outside)
        b = st.backup("sym", cid)
        names = [r["file"] for r in b["provenance"]["requests"]]
        self.assertEqual(names, ["abc123.json"], "a symlink follows out of the course and must not be read")
        self.assertNotIn("not part of this course", json.dumps(b))
        self.assertTrue(any("linked.json" in x for x in b["provenance"].get("skipped") or []),
                        "and it is named rather than silently dropped")

    def test_a_restore_that_could_not_carry_everything_says_so_in_the_course(self):
        cid = self._course("omitted")
        b = st.backup("sym", cid)
        b["provenance"] = dict(b["provenance"], leftOut=7, requests=[], judgements=[])
        new = st.restore("sym", b)["id"]
        gap = (st.read_engine("sym", new) or {}).get("provenanceIncomplete")
        self.assertIsNotNone(gap, "a restored course cannot look like a complete record when it is not")
        self.assertEqual(gap["recordsNotInThisCopy"], 7)
        self.assertIn("not the whole record", gap["whatThisMeans"])

    def test_a_complete_restore_carries_no_false_warning(self):
        cid = self._course("complete")
        new = st.restore("sym", st.backup("sym", cid))["id"]
        self.assertIsNone((st.read_engine("sym", new) or {}).get("provenanceIncomplete"))
        self.assertEqual(st.read_request_snapshot("sym", new, "abc123")["prompt"], "real")

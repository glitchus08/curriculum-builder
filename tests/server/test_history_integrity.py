"""Malformed archives and repeated request metadata must not change evidence identity."""
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from loom_server import engine, storage

class HistoryIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='loom-history-integrity-')
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict('os.environ', {'LOOM_DATA_DIR': self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cid = storage.create_course(None, '{"v":1}', 'isolated')['id']
        self.key = 'claim-one'
        self.entry = dict(key=self.key, runId='r1', fingerprint='e1', verdict='yes', detail={})
        self.name = 'k' + hashlib.sha256(self.key.encode()).hexdigest()[:24] + '.jsonl'
        self.rs = {'attribution': {self.key: self.entry}, 'attributionHistoryArchived': {self.key: {'count': 1, 'file': self.name}}}
        self.path = storage.course_dir(None, self.cid) / 'attribution-history' / self.name
        self.path.parent.mkdir()

    def test_invalid_and_wrong_source_rows_do_not_satisfy_manifest(self):
        for row in ({}, dict(self.entry, key='other'), dict(self.entry, detail=None)):
            with self.subTest(row=row):
                self.path.write_text(json.dumps(row) + '\n')
                hs = engine.history_state(None, self.cid, self.rs, self.key)
                self.assertEqual(hs['incomplete']['couldRead'], 0)

    def test_default_store_checks_missing_history_and_recovery(self):
        self.assertTrue(engine.effective_attribution(self.rs, self.key, None, self.cid)['historyIncomplete'])
        self.path.write_text(json.dumps(self.entry) + '\n')
        self.assertFalse(engine.effective_attribution(self.rs, self.key, None, self.cid).get('historyIncomplete'))

    def test_duplicate_rows_do_not_count_twice(self):
        self.rs['attributionHistoryArchived'][self.key]['count'] = 2
        self.path.write_text((json.dumps(self.entry) + '\n') * 2)
        self.assertEqual(engine.history_state(None, self.cid, self.rs, self.key)['incomplete']['couldRead'], 1)

    def test_settled_decisions_keep_history(self):
        event = {'claimKey': self.key, 'chosen': 'no'}
        self.rs['attributionDecisions'] = [event]
        self.assertEqual(engine.effective_attribution(self.rs, self.key)['decisionHistory'], [event])

    def test_timestamp_changes_deduplicate_but_real_collision_is_retained(self):
        payload = dict(prompt='one', system='system', schema={}, settings={})
        names = {storage.save_request_snapshot(None, self.cid, 'same.1', dict(payload, at=str(i))) for i in range(70)}
        self.assertEqual(len(names), 1)
        other = storage.save_request_snapshot(None, self.cid, 'same.1', dict(payload, prompt='two'))
        self.assertNotIn(other, names)

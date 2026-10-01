#!/usr/bin/env node
// Apply a set of hand-written corrections to one course draft, through Loom's own server, as ONE change that can be undone.
//
//   node tests/tools/apply_edits.mjs --store acceptance --course <id> --edits path/to/edits.mjs            (dry run, saves nothing)
//   node tests/tools/apply_edits.mjs --store acceptance --course <id> --edits path/to/edits.mjs --apply --label "What this change is"
//
// edits.mjs:  export default function edit(journey) { ...change the journey in place... }
//
// What this tool does and does not do:
//   * It uses the same checks as the page: the draft's invariants (journey.audit) and the saved-file checks (store.validate).
//   * It works on the draft only. Approved versions are compared before and after and the save is refused if one changed.
//   * It refuses to run on the owner's real library: --store is required.
//   * It writes no course content of its own and calls no AI.
//   * It does not judge whether the result teaches well.
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { writeFileSync } from 'node:fs';
import * as Store from '../../js/store.js';
import * as J from '../../js/journey.js';
import * as R from '../../js/real.js';

const arg = k => { const i = process.argv.indexOf('--' + k); return i < 0 ? null : (process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : true); };
const store = arg('store'), cid = arg('course'), file = arg('edits'), apply = arg('apply') === true, label = String(arg('label') === true || !arg('label') ? 'Corrections made outside the page' : arg('label')).slice(0, 120), base = arg('server') || 'http://127.0.0.1:8790';
if (typeof store !== 'string' || typeof cid !== 'string' || typeof file !== 'string') { console.error('Needs --store <name> --course <id> --edits <file>. The real library is never edited by this tool.'); process.exit(2); }
const clone = o => JSON.parse(JSON.stringify(o)), q = '?store=' + encodeURIComponent(store);
async function call(method, path, body) {
  const r = await fetch(base + '/api/' + path + q, { method, headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Loom': '1' }, body: body ? JSON.stringify(body) : undefined });
  const d = await r.json(); if (!r.ok) throw new Error(`${r.status}: ${d.error}`); return d;
}
const fail = m => { console.error('STOPPED: ' + m); process.exit(1); };

const c = await call('GET', 'courses/' + cid), found = Store.inspect(c.raw);
if (found.status !== 'ok') fail('the saved course cannot be read: ' + (found.reasons || []).join('; '));
// The file as it is on disk, not as a newer Loom would tidy it: only the draft and its record of changes are altered.
const S = JSON.parse(c.raw), before = S.journey;
if (!before || !J.isReal(before)) fail('this course has no draft written with Claude.');
if (S.pending || S.pendingEdit) fail('a change is waiting for a decision in the page. Accept or reject it first.');
const eng = await call('GET', `courses/${cid}/engine`); if (eng.busy) fail('Claude is working on this course. Wait until it has finished.');
const snapsBefore = JSON.stringify(S.life.snapshots);

const after = clone(before);
const edit = (await import(pathToFileURL(resolve(file)).href)).default;
try { await edit(after); } catch (e) { fail('the edits did not apply: ' + e.message); }

// Parts that Loom works out from the content are worked out again here, the same way the page does it.
const now = new Date().toISOString(), same = (a, b) => JSON.stringify(a) === JSON.stringify(b), changed = [];
after.sessions.forEach((s, i) => {
  if (s.status !== 'written') return; const old = before.sessions.find(x => x.id === s.id) || { activities: [] };
  for (const x of s.activities) {
    x.kind = R.KIND[x.kindKey] || x.kind || 'Step'; x.instructions = x.instructions || []; x.guidance = x.guidance || []; x.materials = x.materials || []; x.success = x.success || []; x.misconceptions = x.misconceptions || []; x.internal = x.internal || []; x.handout = x.handout || ''; x.example = x.example || ''; x.goal = x.goal || '';
    x.learner = x.instructions.map((t, k) => `${k + 1}. ${t}`).join('\n') || x.goal; x.teacher = x.guidance.join(' ');
    const o = old.activities.find(y => y.id === x.id); if (!o || !same(Object.assign({}, o, { origin: 0, editedAt: 0 }), Object.assign({}, x, { origin: 0, editedAt: 0 }))) { x.origin = 'edited'; x.editedAt = now; }
  }
  s.minutes = s.activities.reduce((n, x) => n + x.minutes, 0); s.aim = s.outcome; s.proof = (s.successCriteria || []).join(' ');
  s.teacher.materials = [...new Set(s.activities.flatMap(x => x.materials))];
  const setupOf = acts => acts.filter(x => x.kindKey === 'setup').map(x => (x.guidance || []).concat(x.instructions || []).join(' ')).join(' ') || 'No separate setup is needed.';
  if (old.teacher && old.teacher.setup === setupOf(old.activities) && s.teacher.setup === old.teacher.setup) s.teacher.setup = setupOf(s.activities); // the setup summary follows the setup steps it was made from
  if (!same(Object.assign({}, old, { origin: 0, editedAt: 0, review: 0 }), Object.assign({}, s, { origin: 0, editedAt: 0, review: 0 }))) { s.origin = 'edited'; s.editedAt = now; s.review = null; changed.push(i); }
});
const courseChanged = ['finalEvidence', 'courseOutcome', 'assumptions', 'feasibility', 'integration', 'connections'].filter(k => !same(before[k], after[k]));
if (courseChanged.length) after.courseEditedAt = now;
const withdrawn = R.withdrawStaleChecks(before, after);

const problems = [];
for (const k of ['rev', 'uid', 'origin', 'topics', 'budget', 'requested', 'sources', 'research', 'internal', 'review']) if (!same(before[k], after[k])) problems.push(`the edits changed “${k}”, which is not course content`);
if (!same(before.sessions.map(s => [s.id, s.key, s.unit, s.threads, s.buildsOn, s.internal, s.teacher.requirements]), after.sessions.map(s => [s.id, s.key, s.unit, s.threads, s.buildsOn, s.internal, s.teacher.requirements]))) problems.push('the edits changed a session’s identity, its notes or its requirements from the brief');
after.sessions.forEach((s, i) => { for (const x of s.activities) if (!['setup', 'break'].includes(x.kindKey) && !x.instructions.length) problems.push(`session ${i + 1}, “${x.title}” has no instruction for the learner`); if (!R.KIND[s.activities[0] && s.activities[0].kindKey]) problems.push(`session ${i + 1} has a step of an unknown kind`); for (const x of s.activities) if (!R.KIND[x.kindKey]) problems.push(`session ${i + 1}, “${x.title}” is of an unknown kind “${x.kindKey}”`); });
const was = J.audit(before); problems.push(...J.audit(after).filter(p => !was.includes(p)));
if (!changed.length && !courseChanged.length) problems.push('the edits changed nothing');

const plan = J.planOf(after);
console.log(`Course ${cid} in test storage “${store}”, saved version ${c.meta.version}, draft revision ${before.rev}`);
after.sessions.forEach((s, i) => { const o = before.sessions[i]; console.log(`  ${s.unit} ${i + 1}: ${o ? o.minutes : '-'} → ${s.minutes} min  [${s.activities.map(x => x.kindKey + ' ' + x.minutes).join(', ')}]  preparation ${o ? o.teacher.prep : '-'} → ${s.teacher.prep} min${changed.includes(i) ? '' : '  (unchanged)'}`); if (o && changed.includes(i)) for (const l of R.diffSession(o, s)) console.log(`      ${l.label}: ${String(l.now).slice(0, 110)}`); });
console.log(`  Whole course: ${J.totalMin(before)} → ${plan.minutes} min. ${plan.differs ? 'DIFFERS FROM THE BRIEF: ' + plan.notes.join('; ') : 'Matches the brief’s time.'}`);
if (courseChanged.length) console.log('  Course statements changed: ' + courseChanged.join(', '));
if (withdrawn) console.log(`  ${withdrawn} check(s) by a person withdrawn, because the claim changed.`);
const look = R.outsideBrief(after); for (const o of look) console.log(`  Word check: “${o.name}” in session ${o.sessions.join(', ')}: ${o.example}`);
writeFileSync(resolve(dirname(resolve(file)), 'after.json'), JSON.stringify(after, null, 1));
if (problems.length) { for (const p of problems) console.error('  PROBLEM: ' + p); fail(`${problems.length} problem(s). Nothing was saved.`); }
if (!apply) { console.log('Dry run: no problems found. Nothing was saved. The result is in after.json next to the edits. Add --apply to save.'); process.exit(0); }

// The same steps as the page's own "commit": a new revision, one Undo step, one line in the record of changes.
S.revSeq = (S.revSeq || 0) + 1; after.rev = S.revSeq; S.undo = (S.undo || []).concat([{ journey: before, label, target: 'Whole journey' }]); while (S.undo.length > 12) S.undo.shift();
S.journey = after; S.log = (S.log || []).concat([{ what: 'Edited', label, target: 'Whole journey' }]); S.editing = null;
const L = S.life; if (L.stage !== 'draft') { const top = Math.max(0, ...L.snapshots.map(p => p.ver)); if (top >= L.ver) L.ver = top + 1; L.stage = 'draft'; }
if (JSON.stringify(S.life.snapshots) !== snapsBefore) fail('an approved version would have changed. Nothing was saved.');
const bad = Store.validate(S); if (bad.length) fail('the result would not be readable by Loom: ' + bad.slice(0, 4).join('; '));
const sum = Object.assign({}, c.meta.summary || {}, { stage: S.life.stage, ver: S.life.ver });
const m = await call('PUT', 'courses/' + cid, { raw: JSON.stringify(S), baseVersion: c.meta.version, name: c.meta.name, summary: sum, reason: 'repair' });
const back = await call('GET', 'courses/' + cid), S2 = JSON.parse(back.raw);
if (JSON.stringify(S2.life.snapshots) !== snapsBefore || S2.journey.rev !== after.rev) fail('the saved file does not match what was sent. The copy from before is in previous.json.');
console.log(`SAVED as version ${m.version}, draft revision ${after.rev}. Working version v${S.life.ver}, stage “${S.life.stage}”. Approved versions are unchanged. It can be undone in the page.`);

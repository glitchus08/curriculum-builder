// Checks for the expanded pipeline as the page sees it: the independent-time question, the draft made from a finished run, projects, files,
// what is left open, the review fingerprint, and the export.
// The fixture is a record made by the test double, not by Claude. It tests Loom's handling, not the quality of anything Claude writes.
// Run: node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as J from '../js/journey.js';
import * as F from '../js/flow.js';
import * as R from '../js/real.js';
import * as V from '../js/v2.js';

const E = JSON.parse(readFileSync(new URL('./fixtures/v2-record.json', import.meta.url), 'utf8'));
const ans = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
const A = ans({ format: 'course', entry: 'mix', mix: ['Python', 'Charts'], mode: 'shared', audience: 'mixed', prior: 'new', outcome: 'Make an honest chart from a small table', delivery: 'blended', time: 'w2', hours: '2', pattern: 'p2', own: 'i1', limits: ['laptops'] });
const H = { esc: s => String(s ?? ''), more: (t, b) => `[${t}]${b}`, ul: l => (l || []).join(';'), host: u => u, clock: x => x, day: x => x };

const draft = () => {
  const o = E.stages.outline.approved_outline, ex = { map: E.stages.outline.approved_map, coverage: E.stages.outline.approved_coverage, accounting: E.accounting, policy: E.policy, acknowledged: E.stages.outline.acknowledged, agents: R.agentsFrom(E) };
  const j = R.fromOutline(o, E.brief, E.plan, E.stages.research.output, A, ex); j.rev = 1; R.absorb(j, E); return j;
};

test('independent time is asked for weekly formats, read exactly, and counted once beside the live time', () => {
  assert.equal(F.ownMinutes(A), 60);
  assert.equal(F.ownMinutes(ans({ own: F.CUSTOM })), null);
  assert.equal(F.ownMinutes({ own: { value: F.CUSTOM, text: '1 hour 30 minutes' } }), 90);
  assert.equal(F.ownMinutes({ own: { value: 'none' } }), null);
  assert.ok(F.activePath(A).some(q => q.id === 'own'));
  assert.ok(!F.activePath(ans({ ...Object.fromEntries(Object.entries(A).map(([k, v]) => [k, v.value])), format: 'workshop', time: 'half', hours: undefined, pattern: undefined, own: undefined })).some(q => q.id === 'own'), 'a one-off format has no weekly independent time');
  const plan = R.planFor(A);
  assert.deepEqual(plan.independent, { perWeekMinutes: 60, weeks: 2, totalMinutes: 120 });
  assert.equal(plan.total, 240);
  assert.equal(J.accountingOf(plan).statement, '4 h live + 2 h independent = 6 h. Each hour is counted once.');
  assert.match(R.briefFor(A).liveAndOwnTime, /1 h of independent work each week/);
  const six = { total: 1080, independent: { totalMinutes: 720 } };
  assert.equal(J.accountingOf(six).statement, '18 h live + 12 h independent = 30 h. Each hour is counted once.');
  assert.equal(R.planFor(ans({ ...Object.fromEntries(Object.entries(A).map(([k, v]) => [k, v.value])), own: undefined })).independent, null);
});

test('a finished run becomes a draft with the map, projects, files and checks, and every part is written', () => {
  const j = draft();
  assert.equal(j.pipeline, 2);
  assert.deepEqual(j.sessions.map(s => s.status), ['written', 'written', 'written', 'written']);
  assert.deepEqual(j.projects.map(p => [p.id, p.status]), [['P1', 'written'], ['P2', 'written']]);
  assert.equal(j.map.nodes.length, 5);
  assert.equal(j.sessions[0].independentWork.minutes, 30);
  assert.deepEqual(j.sessions[0].assetChecks.map(c => [c.name, c.level]), [['count.py', 'executed']]);
  assert.deepEqual(Object.keys(j.agents).sort(), ['foundations', 'outline', 'sources']);
  assert.deepEqual(J.audit(j), []);
  assert.deepEqual(j.research.nodeCoverage.map(c => c.status), ['supported', 'supported', 'supported', 'supported']);
});

test('the page and the server fingerprint the sessions and the projects together the same way', () => {
  const j = draft();
  assert.ok(E.stages.review.inputFingerprint, 'the server stored what it judged');
  assert.equal(R.reviewPrint(j), E.stages.review.inputFingerprint, 'the review reads as current on the draft it judged');
  j.projects[0].content.learner_brief += ' changed';
  assert.notEqual(R.reviewPrint(j), E.stages.review.inputFingerprint, 'an edit to a project makes the review stale');
  const k = draft(); k.sessions[0].assets[0].content += '9,9\n';
  assert.notEqual(R.reviewPrint(k), E.stages.review.inputFingerprint, 'an edit to a supplied file makes it stale too');
  const legacy = draft(); legacy.projects = [];
  assert.ok(Array.isArray(R.reviewMaterial(legacy)), 'a course with no project is fingerprinted as before');
});

test('what is still open is stated plainly and cannot be ticked away', () => {
  const j = draft();
  assert.ok(J.v2Open(j).some(t => /made-up practice data/.test(t)));
  assert.ok(!J.v2Open(j, true).some(t => /made-up practice data/.test(t)), 'labelled practice data is not itself a reason a course is not ready');
  j.timeConflict = { exists: true, explanation: 'Too much for the time.', options: [] };
  j.map.derived.openGaps = ['a gap'];
  j.deferred = [{ node: 'N3', reason: 'no time' }];
  j.sessions[0].assetChecks = [{ name: 'x.py', level: 'not_run', reason: 'No Python here can import pandas' }];
  const open = J.v2Open(j).join(' | ');
  for (const w of ['Time conflict declared', 'Open foundation gap: a gap', 'deferred', '1 code file was not run']) assert.ok(open.includes(w), w + ' in ' + open);
  assert.ok(R.readiness(j).look.some(t => /Time conflict declared/.test(t)));
  assert.ok(J.readinessOf({ ver: 1, at: new Date().toISOString(), journey: j }).why.some(t => /Time conflict declared/.test(t)));
});

test('an outline is not approvable in silence when a conflict, a gap or a must-fix stands', () => {
  const o = JSON.parse(JSON.stringify(E.stages.outline.output));
  assert.deepEqual(V.outlineOpenItems(o, E), []);
  const E2 = JSON.parse(JSON.stringify(E));
  E2.stages.outline_review.output.findings = [{ severity: 'must_fix', area: 'time', finding: 'Too tight.', suggestion: 's' }];
  E2.stages.map.output.derived.openGaps = ['below entry'];
  o.time_conflict = { exists: true, explanation: 'Needs more time.', options: [{ label: 'More time', effect: 'add a week' }, { label: 'Narrower', effect: 'drop the capstone' }] };
  const items = V.outlineOpenItems(o, E2);
  assert.equal(items.length, 3);
  assert.ok(/must be fixed/.test(items[0]), 'a finding that is current comes first');
  assert.ok(items[1].startsWith('Time conflict') && items[2].startsWith('Foundation gap'));
  const html = V.outlineExtras(o, E2, {}, H);
  assert.match(html, /Time conflict/);
  assert.match(html, /data-a="outlineOption" data-v="1"/);
  assert.match(html, /4 h live \+ 2 h independent = 6 h/);
});

test('the screens for the map, projects, files and checks are built from the draft', () => {
  const j = draft();
  assert.match(V.projectsBlock(j, H), /Open the project/);
  const body = V.projectBody(j.projects[1], j, H);
  assert.match(body, /Rubric \(3 criteria\)/);
  assert.match(body, /Milestones/);
  const ex = V.sessionExtras(j.sessions[0], j, H);
  assert.match(ex, /data\.csv/);
  assert.match(ex, /Ran without error/);
  assert.match(ex, /Independent work after the meeting \(30 min, not part of the 60 live\)/);
  assert.match(ex, /Made-up practice data/);
  const ck = V.checksExtras(j, H);
  assert.match(ck, /Scope and evidence by topic/);
  assert.match(ck, /Code that was run/);
  const rows = V.genRows(E, { ...H, host: u => u, clock: x => x });
  assert.equal(rows.length, 9);
  assert.ok(rows.every(r => ['done', 'running', 'failed', 'todo'].includes(r[1])), JSON.stringify(rows.map(r => r[1])));
});

test('the export carries scope, coverage, evidence per topic, projects and files, and none of the reviewers’ words', () => {
  const j = draft();
  const snap = { ver: 1, at: new Date().toISOString(), journey: j, brief: A, openAtApproval: ['x'] };
  const pkg = J.buildPackage(snap);
  assert.deepEqual(pkg.scope.topics.map(t => [t.topic, t.role]), [['Python', 'required'], ['Charts', 'required'], ['Reading a table', 'required'], ['Files and folders', 'already_known'], ['Counting rows', 'required']]);
  assert.ok(pkg.scope.whereEachIsTaught.every(r => r.role !== 'required' || r.taughtInSession));
  assert.equal(pkg.course.timeAccounting, '4 h live + 2 h independent = 6 h. Each hour is counted once.');
  assert.equal(pkg.evidence.perTopic.length, 4);
  assert.ok(pkg.evidence.sources.every(s => 'whatTheFetchReturned' in s || s.pageReachedTheAI !== 'yes'));
  assert.equal(pkg.projects.length, 2);
  assert.ok(pkg.projects[1].learner.howYouWillBeAssessed.length >= 3);
  assert.deepEqual(pkg.learnerMaterials[0].files.map(f => f.name), ['data.csv', 'count.py']);
  assert.equal(pkg.learnerMaterials[0].afterTheMeeting.independentMinutes, 30);
  assert.equal(pkg.teacherMaterials[0].codeChecks[0].checked, 'Run on this computer, no network. It finished without error');
  assert.deepEqual(pkg.checksByOtherAIRoles.foundationsAndOrder, { verdict: 'gaps', topicsAddedOnItsRequest: ['Counting rows'] });
  const text = JSON.stringify(pkg);
  for (const w of ['TEST DOUBLE foundations', 'TEST DOUBLE audit', 'TEST DOUBLE feasibility', 'TEST DOUBLE finding']) assert.ok(!text.includes(w), 'the reviewers’ own words stay in Loom: ' + w);
  const teacher = J.packHTML(pkg, 'teacher'), learner = J.packHTML(pkg, 'learner');
  assert.match(teacher, /Scope: what this course covers, and why/);
  assert.match(teacher, /What good work looks like/);
  assert.match(teacher, /What running the code showed/);
  assert.match(teacher, /What evidence each topic has/);
  assert.doesNotMatch(learner, /What good work looks like/);
  assert.doesNotMatch(learner, /Scope: what this course covers/);
  assert.match(learner, /Files for this session/);
  assert.match(learner, /After the meeting: 30 minutes on your own/);
  assert.match(learner, /How you will be assessed/);
});

test('a leak of a reviewer’s findings into the package is refused', () => {
  const j = draft();
  j.agents.outline.output.findings = [{ severity: 'must_fix', area: 'time', finding: 'A finding that must never leave Loom.', suggestion: 'And its long suggestion text.' }];
  j.sessions[0].title += ' A finding that must never leave Loom.';
  assert.throws(() => J.buildPackage({ ver: 1, at: new Date().toISOString(), journey: j, brief: A, openAtApproval: [] }), /internal note/);
});

test('a person can edit a project’s own words; the review then reads as stale and Undo is possible through the draft copy', () => {
  const j = draft();
  const f = { title: 'A better title', purpose: 'p', learner_brief: 'Do the thing, in full.', deliverables: 'a file\na note', feedback_route: 'peer', revision_route: 'redo', example_or_solution_guidance: 'good looks like this', teacher_guidance: 'watch\nhelp' };
  assert.ok(R.applyDirect(j, { kind: 'project', projectId: 'P1', fields: { ...f, title: '' } }).error);
  assert.ok(R.applyDirect(j, { kind: 'project', projectId: 'P1', fields: { ...f, deliverables: '  ' } }).error);
  const r = R.applyDirect(j, { kind: 'project', projectId: 'P1', fields: f });
  assert.ok(r.after);
  assert.equal(r.after.projects[0].content.title, 'A better title');
  assert.deepEqual(r.after.projects[0].content.deliverables, ['a file', 'a note']);
  assert.equal(j.projects[0].content.title, 'TEST DOUBLE minor project', 'the draft it was made from is not touched');
  assert.notEqual(R.reviewPrint(r.after), E.stages.review.inputFingerprint);
  assert.deepEqual(r.after.projects[0].content.rubric, j.projects[0].content.rubric, 'files, milestones and the rubric are left as they were');
  assert.ok(R.applyDirect(r.after, { kind: 'project', projectId: 'P1', fields: f }).same);
});

test('find and replace never rewrites a supplied file, a check on it, or a topic id', () => {
  const j = draft();
  const r = R.replaceText(j, 'rows', 'lines');
  const after = r.after || j;
  assert.equal(after.sessions[0].assets[1].content, j.sessions[0].assets[1].content, 'the code is not changed by a text replacement');
  assert.deepEqual(after.sessions[0].assetChecks, j.sessions[0].assetChecks);
  const n = R.replaceText(j, 'N3', 'N9');
  assert.deepEqual((n.after || j).sessions[0].teachesNodes, j.sessions[0].teachesNodes, 'topic ids stay ids of the map');
});

test('a project’s facts count as open until a person checks them, and a damaged v2 record is refused', async () => {
  const j = draft();
  j.projects[0].content.claims = [{ text: 'A project fact', type: 'fact', sources: ['S1'], support: 'stated_by_source', note: '' }];
  const before = J.evidenceOpen(j).join(' ');
  assert.match(before, /not been checked/);
  const c = j.projects[0].content.claims[0]; c.personChecked = { at: new Date().toISOString(), of: J.claimPrint(c) };
  assert.ok(J.evidenceOpen(j).join(' ') !== before, 'a person’s check of a project claim is counted');
  const pkg = J.buildPackage({ ver: 1, at: new Date().toISOString(), journey: j, brief: A, openAtApproval: [] });
  assert.ok(pkg.projects[0].teacher.claims[0].checkedAgainstSourceByAPersonOn, 'the export says who checked it, and on what date');
  const Store = await import('../js/store.js');
  const s = Store.fresh(); s.journey = JSON.parse(JSON.stringify(j)); s.life.snapshots = [];
  assert.deepEqual(Store.validate(s).filter(x => /map|projects|reviewers/.test(x)), []);
  s.journey.map = null; assert.ok(Store.validate(s).some(x => /topic map is unreadable/.test(x)));
});

/* ---- prepared originals must physically travel with the package ---- */
const prepFile = (over = {}) => ({ name: 'nasa_power_monthly_pune.csv', kind: 'original', sha256: 'a'.repeat(64), bytes: 12, available: true, encoding: 'utf-8',
  content: 'YEAR,T2M\n2017,24.1\n', purpose: 'The measurements the course is built on',
  provenance: { publisher: 'NASA POWER', publisherUrl: 'https://power.larc.nasa.gov/', requestUrl: 'https://power.larc.nasa.gov/api/x', retrievedAt: '2026-09-29T15:00:00Z', serviceVersion: 'v2.10.0', licenceNote: 'no named licence established', fields: [{ name: 'T2M', units: 'C' }], coverage: { years: '2017-2026' }, limitations: ['model grid-cell values, not a station'] }, ...over });

test('a prepared original is delivered in the package itself, with its checksum and where it came from', () => {
  const j = draft();
  j.preparedFiles = [prepFile()];
  j.sessions[0].activities[0].materials = ['nasa_power_monthly_pune.csv'];
  const pkg = J.buildPackage({ ver: 1, at: '2026-09-29T00:00:00Z', journey: j });
  const f = pkg.preparedOriginals.files[0];
  assert.equal(f.name, 'nasa_power_monthly_pune.csv');
  assert.equal(f.content, 'YEAR,T2M\n2017,24.1\n', 'the real bytes travel, not a description of them');
  assert.equal(f.checksumSha256, 'a'.repeat(64));
  assert.match(f.whatItIs, /exactly as it was published/);
  assert.equal(f.cameFrom.publisher, 'NASA POWER');
  assert.deepEqual(f.cameFrom.limitations, ['model grid-cell values, not a station']);
  assert.equal(f.cameFrom.licence, 'no named licence established', 'an unresolved licence is carried, not invented');
  assert.equal(pkg.learnerMaterials[0].preparedFilesYouNeed[0].name, 'nasa_power_monthly_pune.csv', 'the session that needs it is given it');
});

test('a package that names a prepared file it cannot deliver is refused', () => {
  const j = draft();
  j.preparedFiles = [prepFile({ available: false, why: 'its bytes are not in this course’s folder', content: undefined })];
  j.sessions[0].activities[0].materials = ['nasa_power_monthly_pune.csv'];
  assert.throws(() => J.buildPackage({ ver: 1, at: 'x', journey: j }), /cannot be delivered/,
    'a learner must never be handed a course naming a file that was never supplied');
  const listed = J.buildPackage({ ver: 1, at: 'x', journey: { ...j, sessions: j.sessions.map(s => ({ ...s, activities: s.activities.map(a => ({ ...a, materials: [] })) })) } });
  assert.equal(listed.preparedOriginals.notAvailable[0].name, 'nasa_power_monthly_pune.csv', 'and it is still reported, not hidden');
});

test('a prepared file that is not text keeps its exact bytes through the package', () => {
  const j = draft();
  j.preparedFiles = [prepFile({ name: 'source.pdf', encoding: 'binary', content: undefined, contentBase64: 'JVBERi0xLjQK/w==' })];
  j.sessions[0].activities[0].materials = ['source.pdf'];
  const f = J.buildPackage({ ver: 1, at: 'x', journey: j }).preparedOriginals.files[0];
  assert.equal(f.contentBase64, 'JVBERi0xLjQK/w==', 'binary bytes are carried base64, never decoded');
  assert.equal(f.content, undefined);
});

/* ---- the two readable packs must deliver the files too, not only the structured JSON ---- */
test('both readable packs deliver a prepared original: its bytes, its checksum and a working download', () => {
  const j = draft();
  j.preparedFiles = [prepFile({ content: 'YEAR,T2M\n2017,24.1\n2018,-3.5\n' })];
  j.sessions[0].activities[0].materials = ['nasa_power_monthly_pune.csv'];
  const pkg = J.buildPackage({ ver: 1, at: '2026-09-29T00:00:00Z', journey: j });
  for (const who of ['teacher', 'learner']) {
    const html = J.packHTML(pkg, who);
    assert.ok(html.includes('nasa_power_monthly_pune.csv'), `${who}: the file is named`);
    assert.ok(html.includes('2018,-3.5'), `${who}: the real bytes are printed, not just a name`);
    assert.ok(html.includes('NASA POWER'), `${who}: where it came from travels with it`);
    assert.ok(html.includes('a'.repeat(64).slice(0, 12)), `${who}: the checksum is shown`);
    assert.ok(html.includes('model grid-cell values, not a station'), `${who}: the publisher's own limitation is kept`);
    // the download link must carry exactly the same bytes
    const m = html.match(/href="data:text\/plain;charset=utf-8,([^"]+)"/);
    assert.ok(m, `${who}: a download link is present`);
    assert.equal(decodeURIComponent(m[1]), 'YEAR,T2M\n2017,24.1\n2018,-3.5\n', `${who}: the download is byte-for-byte the prepared file`);
  }
});

test('a prepared file that is not text is offered as a download in the packs and is not printed as text', () => {
  const j = draft();
  j.preparedFiles = [prepFile({ name: 'source.pdf', encoding: 'binary', content: undefined, contentBase64: 'JVBERi0xLjQK/w==' })];
  j.sessions[0].activities[0].materials = ['source.pdf'];
  const html = J.packHTML(J.buildPackage({ ver: 1, at: 'x', journey: j }), 'learner');
  assert.ok(html.includes('data:application/octet-stream;base64,JVBERi0xLjQK/w=='), 'the exact bytes are downloadable');
  assert.ok(html.includes('not text, so it is not printed here'), 'and the pack says why it is not printed');
});

test('a pack says plainly when a named prepared file could not be delivered', () => {
  const j = draft();
  j.preparedFiles = [prepFile({ available: false, why: 'its bytes are not in this course’s folder', content: undefined })];
  const html = J.packHTML(J.buildPackage({ ver: 1, at: 'x', journey: j }), 'teacher');
  assert.ok(html.includes('Named but not delivered'), 'it is reported in the pack, not silently missing');
  assert.ok(html.includes('nasa_power_monthly_pune.csv'));
});

/* ---- works and lineage reach the package and the teacher pack ---- */
test('an original and its supported extension reach the export, and an unestablished link is shown as such', () => {
  const j = draft();
  const W1 = 'w:aaaa1111', W2 = 'w:bbbb2222', W3 = 'w:cccc3333';
  j.research.lineage = {
    works: {
      [W1]: { id: W1, title: 'A first report', creators: ['Ada Ito'], published: '1998-03-01', version_or_edition: '1', identifier: 'doi:10.1234/first', role: 'original_contribution', originStatus: 'established', originWhy: [], seenAt: ['https://example.org/a'] },
      [W2]: { id: W2, title: 'A wider replication', creators: ['Bo Lin'], published: '2011-06-01', identifier: 'doi:10.1234/second', role: 'primary_extension', originStatus: 'established', originWhy: [], seenAt: ['https://example.org/b'] },
      [W3]: { id: W3, title: 'A tutorial blog', creators: [], role: 'secondary_aid', originStatus: 'unknown', originWhy: ['this is a secondary aid, so it does not itself establish an origin'], seenAt: ['https://blog.example/x'] },
    },
    edges: [
      { from: W2, to: W1, relation: 'replicated', whatChanged: 'ten more years of data', supportingWords: 'we repeat the 1998 method', status: 'supported', why: [] },
      { from: W3, to: W1, relation: 'extended', earlierWorkAsNamed: 'doi:10.1234/first', whatChanged: 'a retelling', supportingWords: '', status: 'unknown', why: ['a secondary aid can point at an original but is not evidence for it'] },
    ],
    summary: { works: 3, originalsEstablished: 1, descentEdges: 2, supportedEdges: 1, unknownEdges: 1, disputedEdges: 0 },
  };
  j.research.lineageChains = [{ original: { work: W1, title: 'A first report', creators: ['Ada Ito'], published: '1998-03-01', identifier: 'doi:10.1234/first' },
    supportedExtensions: [{ work: W2, title: 'A wider replication', relation: 'replicated', whatChanged: 'ten more years of data', supportingWords: 'we repeat the 1998 method', status: 'supported' }],
    claimedButNotEstablished: [{ work: W3, title: 'A tutorial blog', relation: 'extended', status: 'unknown' }] }];
  const pkg = J.buildPackage({ ver: 1, at: 'x', journey: j });
  const L = pkg.evidence.worksAndHowTheyDescend;
  assert.equal(L.counts.originalsEstablished, 1);
  assert.equal(L.works.find(w => w.work === W3).originIs, 'unknown');
  assert.ok(L.works.find(w => w.work === W3).whyNotEstablished[0].includes('secondary aid'));
  assert.equal(L.descent.find(e => e.laterWork === W2).standing, 'supported');
  assert.equal(L.descent.find(e => e.laterWork === W3).standing, 'unknown');
  assert.equal(L.originalsAndTheirExtensions[0].supportedExtensions.length, 1);
  assert.equal(L.originalsAndTheirExtensions[0].claimedButNotEstablished.length, 1, 'a claimed link is kept, not dropped');

  const html = J.packHTML(pkg, 'teacher');
  assert.ok(html.includes('A first report') && html.includes('A wider replication'), 'the works are in the teacher pack');
  assert.ok(html.includes('we repeat the 1998 method'), 'the words that support the link are shown');
  assert.ok(html.includes('secondary aid'), 'and why an unestablished link is not supported');
  assert.ok(!J.packHTML(pkg, 'learner').includes('Works this course rests on'), 'internal provenance detail stays in the teacher pack');
});

/* ---- a changed program can never inherit an older run ---- */
test('a file that changed after it was checked loses the old result, everywhere it is shown', () => {
  const good = { name: 'chart.py', kind: 'code', run: 'run', content: 'print("ok")', purpose: 'p', provenance: 'authored' };
  const ran = { name: 'chart.py', kind: 'code', check: 'run', assetPrint: J.assetPrint(good), state: 'ran', level: 'executed', output: 'ok' };
  assert.deepEqual(J.checksFor([good], [ran]), [ran], 'unchanged, so the run still applies');

  const edited = { ...good, content: 'print("ok")  # one character more' };
  const after = J.checksFor([edited], [ran]);
  assert.equal(after[0].state, 'stale');
  assert.equal(after[0].level, 'not_run', 'it is not reported as a pass');
  assert.match(after[0].reason, /changed after it was checked/);
  assert.equal(J.assetPrint(edited) === J.assetPrint(good), false);

  // and it reaches the export and the readable pack in that state
  const j = draft();
  j.sessions[0].assets = [edited];
  j.sessions[0].assetChecks = [ran];
  const pkg = J.buildPackage({ ver: 1, at: 'x', journey: j });
  const line = pkg.teacherMaterials[0].codeChecks.find(c => c.file === 'chart.py');
  assert.match(line.checked, /changed after it was checked/, 'the export does not show an inherited pass');
  assert.match(J.packHTML(pkg, 'teacher'), /changed after it was checked/);
});

test('a check for a file that no longer exists at all is dropped, not carried forward', () => {
  const ran = { name: 'gone.py', kind: 'code', check: 'run', assetPrint: 'aaaa.1', state: 'ran', level: 'executed', output: 'ok' };
  assert.deepEqual(J.checksFor([{ name: 'other.py', content: 'x' }], [ran]), []);
});

test('a result saved before checks carried a fingerprint is left as it was, not called stale', () => {
  const old = { name: 'chart.py', kind: 'code', check: 'run', state: 'ran', level: 'executed', output: 'ok' };
  assert.deepEqual(J.checksFor([{ name: 'chart.py', content: 'anything' }], [old]), [old]);
});

/* ---- a rejected origin must read as disputed everywhere it is shown ---- */
test('a work whose attribution was rejected is exported as disputed, with the reason, and carries no chain', () => {
  const j = draft();
  const W = 'w:dead0001';
  j.research.lineage = {
    works: { [W]: { id: W, title: 'A contested paper', creators: ['Ada Ito'], published: '1998', identifier: 'doi:10.1234/first',
      role: 'original_contribution', originStatus: 'disputed', attributionVerdict: 'no',
      originWhy: ['a separate attribution review judged its identity or its role to be wrong'],
      originContrary: ['no separate attribution review has confirmed its identity and role'], seenAt: ['https://e.org/x'] } },
    edges: [],
    summary: { works: 1, originalsEstablished: 0, descentEdges: 0, supportedEdges: 0, unknownEdges: 0, disputedEdges: 0 },
  };
  j.research.lineageChains = [];
  const pkg = J.buildPackage({ ver: 1, at: 'x', journey: j });
  const w = pkg.evidence.worksAndHowTheyDescend.works[0];
  assert.equal(w.originIs, 'disputed');
  assert.equal(w.attributionVerdict, 'no');
  assert.match(w.whyNotEstablished[0], /judged its identity or its role to be wrong/);
  assert.match(w.contraryEvidenceFromOtherSightings[0], /no separate attribution review/);
  assert.equal(pkg.evidence.worksAndHowTheyDescend.counts.originalsEstablished, 0);
  assert.equal(pkg.evidence.worksAndHowTheyDescend.originalsAndTheirExtensions.length, 0);
  const html = J.packHTML(pkg, 'teacher');
  assert.ok(html.includes('disputed'), 'the teacher pack says disputed');
  assert.ok(html.includes('judged its identity or its role to be wrong'), 'and why');
  assert.ok(html.includes('also seen without confirmation'), 'and does not hide the unconfirmed sighting');
});

/* ---- the approval list must not mix a stale map question with a live finding ---- */
test('a question the topic map asked before the outline is kept, marked as such, and listed after current findings', () => {
  const o = { time_conflict: { exists: false }, deferred: [], assumptions: [], setup: {}, course_outcome: 'x' };
  const E = { stages: { map: { output: { nodes: [], derived: { openGaps: [], unresolved: [
        'Whether learners can install software on their laptops is unknown.'] } } },
      outline_review: { output: { findings: [{ severity: 'must_fix', area: 'assets', finding: 'Five notebooks are missing.' }] } },
      research: { output: { nodeCoverage: [] } }, foundation_review: {} } };
  const items = V.outlineOpenItems(o, E);
  assert.match(items[0], /must be fixed \(assets\)/, 'the finding that is current comes first');
  const mapQ = items[items.length - 1];
  assert.match(mapQ, /install software/, 'the question is kept, not dropped');
  assert.match(mapQ, /Asked when the topic map was made, before this outline was written/, 'and is marked as asked earlier');
  assert.match(mapQ, /Check the outline before treating this as still open/);
  assert.equal(items.filter(x => /Asked when the topic map was made/.test(x)).length, 1);
});

// Checks for content written with Claude: mapping, consistency, edits, export, saved-state validation.
// The fixtures here are artificial. They test Loom's handling, not the quality of anything Claude writes.
// Run: node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import * as J from '../js/journey.js';
import * as F from '../js/flow.js';
import * as R from '../js/real.js';
import * as V2 from '../js/v2.js';
import * as Store from '../js/store.js';

const brief = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
const A = brief({ format: 'workshop', entry: 'mix', mix: ['Marketing', 'Design', 'Development'], mode: 'shared', audience: 'college', prior: 'some', outcome: 'Launch a page for a local event', delivery: 'room', time: 'half', limits: ['laptops', 'free'] });
const act = (kind, title, minutes) => ({ kind, title, goal: `Goal of ${title}`, minutes, instructions: kind === 'setup' ? [] : ['Do the first thing.', 'Do the second thing.'], materials: ['Paper'], handout: kind === 'try' ? 'BRIEF: a craft market on Saturday.' : '', worked_example: '', teacher: kind === 'setup' ? [] : ['Watch the pairs.'], misconceptions: kind === 'try' ? [{ belief: 'More text is better', response: 'Ask what a visitor reads first.' }] : [], success: ['Visible in the work.'] });
const session = (title, minutes, topics) => ({ title, outcome: `Learners can ${title.toLowerCase()}`, serves: 'A step to the outcome', prerequisites: [{ name: 'Can use a browser', support: 'Pair with someone who can.' }], prerequisites_note: '', contributions: topics.map(t => ({ topic: t, gives: `${t} sets a constraint` })), preparation: { minutes: 20, steps: ['Print the brief.'] },
  activities: [act('setup', 'Set up', 5), act('try', 'First attempt', minutes - 20), act('feedback', 'Pair feedback', 5), act('revise', 'Improve', 10)], success_criteria: ['The page names the event.', 'The page has one call to action.'], application_check: { when: 'Next week', task: 'Do it for a different event, alone.', looks_for: ['No help needed'] },
  claims: [{ text: 'Visitors scan before they read', type: 'fact', sources: ['S1'], note: '' }, { text: 'Pairs give better feedback than groups here', type: 'hypothesis', sources: [], note: '' }], assumptions: ['A room with tables'] });
const outline = (topics = ['Marketing', 'Design', 'Development'], n = 3, status = 'partly') => ({ course_outcome: 'Launch a page for a local event', final_evidence: 'A live page and a sign-up count', feasibility: { fits: true, concern: '' }, integration: { status, reason: 'One page needs all three.', joining_task: 'Build and launch the page.' }, assumptions: ['Laptops work'],
  sessions: Array.from({ length: n }, (_, i) => ({ title: `Part ${i + 1}`, outcome: `Do part ${i + 1}`, serves: 'Serves it', topics, contributions: topics.map(t => ({ topic: t, gives: `${t} gives a method` })), builds_on: i ? [i] : [], key_task: 'Given X, hand in Y', evidence_of_learning: 'A finished Y' })) });
const research = { sources: [{ id: 'S1', title: 'A guide', url: 'https://example.org/a', publisher: 'Example', year: '2020', kind: 'textbook_or_reference', topic: 'Design', claim: 'Visitors scan before they read', finding: 'It says so.', quote: '', strength: 'direct', limits: '', retrievedAt: '2026-09-27T10:00:00Z', askedAt: '2026-09-27T10:00:00Z', fetch: 'retrieved', openedByAI: true, personChecked: null, link: { opened: true, checkedAt: '2026-09-27T10:00:00Z' } },
  { id: 'S2', title: 'Unread', url: 'https://example.org/b', publisher: '', year: '', kind: 'other', topic: 'Marketing', claim: 'Something', finding: '', quote: '', strength: 'background', limits: 'Loom has no record that this page was opened during research.', retrievedAt: null, askedAt: '2026-09-27T10:00:00Z', fetch: 'failed', openedByAI: false, personChecked: null, link: { opened: false, checkedAt: '2026-09-27T10:00:00Z' } }], open_questions: ['Is a half day enough?'], not_opened: [], combination_evidence: { status: 'weak', note: '' }, searches: ['q'], researchedAt: '2026-09-27T10:00:00Z', unconfirmedReads: [] };
const record = (n = 3, done = n) => ({ startedAt: 'run1', status: 'done', stages: { research: { status: 'done', output: research }, outline: { status: 'done' }, review: { status: 'todo' }, materials: { sessions: Array.from({ length: n }, (_, i) => i < done ? { status: 'done', output: session(`Part ${i + 1}`, 60, ['Marketing', 'Design', 'Development']) } : { status: 'todo' }) } } });
const draft = (done = 3) => { const j = R.fromOutline(outline(), R.briefFor(A), R.planFor(A), research, A); j.rev = 1; R.absorb(j, record(3, done)); return j; };

test('the brief and time plan sent to Claude carry exactly what was asked', () => {
  const b = R.briefFor(A), p = R.planFor(A);
  assert.deepEqual(b.topics, ['Marketing', 'Design', 'Development']); assert.equal(b.mode, 'shared'); assert.equal(b.outcome, 'Launch a page for a local event');
  assert.deepEqual(b.requirements, ['tasks may assume a laptop for each learner or pair', 'free tools only, with no paid apps, licences or accounts']);
  assert.deepEqual(p, { sessions: 3, minutes: [60, 60, 60], unit: 'Block', total: 180, weekly: false, setByTeam: false, span: 'Half a day (3 h)' });
  const w = R.planFor(brief({ ...Object.fromEntries(Object.entries(A).map(([k, v]) => [k, v.value])), format: 'course', time: { value: F.CUSTOM, text: '12 weeks' }, hours: { value: F.CUSTOM, text: '2 hours 30 minutes' } }));
  assert.equal(w.sessions, 12); assert.ok(w.minutes.every(m => m === 150)); assert.equal(w.total, 1800);
});
test('a draft made from an approved outline starts unwritten and is never filled with anything else', () => {
  const j = R.fromOutline(outline(), R.briefFor(A), R.planFor(A), research, A);
  assert.equal(j.origin, 'claude'); assert.ok(j.sessions.every(s => s.status === 'pending' && s.activities.length === 0));
  assert.equal(J.totalMin(j), 180); assert.equal(J.planOf(j).differs, false);
  assert.equal(J.audit(j).filter(p => /not been written/.test(p)).length, 3);
  assert.throws(() => J.buildPackage({ ver: 1, at: 'x', journey: j }), /not been written/);
  assert.equal(R.absorb(j, record(3, 1)), 1); assert.deepEqual(j.sessions.map(s => s.status), ['written', 'pending', 'pending']);
  assert.equal(Store.inspect(JSON.stringify({ ...Store.fresh(), journey: j })).status, 'ok', 'a part-written draft is valid saved work');
});
test('finished sessions are absorbed once, and the team’s edits are never overwritten by later arrivals', () => {
  const j = draft(1), edited = R.applyDirect(j, { kind: 'session', sessionId: 's1', fields: { title: 'My own title', outcome: 'My outcome', success: 'One\nTwo', checkTask: 'T', checkWhen: 'W', checkLooks: 'L', prerequisites: '' } }).after;
  assert.equal(R.absorb(edited, record(3, 3)), 2); assert.equal(edited.sessions[0].title, 'My own title'); assert.deepEqual(edited.sessions.map(s => s.status), ['written', 'written', 'written']);
  assert.equal(R.absorb(edited, record(3, 3)), 0, 'nothing is absorbed twice');
  assert.deepEqual(J.audit(edited), []);
});
test('a failed session is shown as failed, with the reason', () => {
  const j = R.fromOutline(outline(), R.briefFor(A), R.planFor(A), research, A), rec = record(3, 1); rec.stages.materials.sessions[1] = { status: 'failed', reason: 'Did not pass the checks.', detail: 'Minutes did not add up.' };
  R.absorb(j, rec); assert.equal(j.sessions[1].status, 'failed'); assert.match(j.sessions[1].failure, /add up/); assert.equal(j.sessions[1].activities.length, 0);
});
test('written content keeps every part a teacher needs, and timing is exact', () => {
  const j = draft(), s = j.sessions[0];
  assert.deepEqual(J.audit(j), []); assert.equal(s.activities.reduce((n, x) => n + x.minutes, 0), s.minutes);
  assert.equal(s.activities[1].handout, 'BRIEF: a craft market on Saturday.'); assert.equal(s.activities[1].instructions.length, 2); assert.equal(s.teacher.prep, 20); assert.deepEqual(s.teacher.materials, ['Paper']);
  assert.ok(s.teacher.requirements.every(r => r.startsWith(J.REQ))); assert.equal(s.applicationCheck.task, 'Do it for a different event, alone.'); assert.deepEqual(s.threads, [0, 1, 2]);
  assert.deepEqual(R.sessionBack(s).activities.map(x => x.minutes), [5, 40, 5, 10]); assert.deepEqual(R.sessionBack(s).success_criteria, s.successCriteria);
});
test('the consistency checks catch what would mislead a teacher', () => {
  const broken = f => { const j = draft(); f(j); return J.audit(j).join(' | '); };
  assert.match(broken(j => { j.sessions[0].activities[1].minutes += 5; }), /add up to 65/);
  assert.match(broken(j => { j.sessions[0].contributions = j.sessions[0].contributions.filter(c => c.topic !== 'Design'); }), /does not say what Design contributes/);
  assert.match(broken(j => { j.sessions[0].successCriteria = ['one']; }), /two success criteria/);
  assert.match(broken(j => { j.sessions[0].applicationCheck = null; }), /later check/);
  assert.match(broken(j => { j.sessions[0].activities = j.sessions[0].activities.filter(x => x.kindKey !== 'revise'); j.sessions[0].minutes = 50; }), /feedback step and a revision step/);
  assert.match(broken(j => { j.sessions[0].claims[0].sources = ['S9']; }), /cites S9/);
  assert.match(broken(j => { j.sessions[0].activities[1].guidance.push('Request for the writer: “make it fun”. Not acted on.'); }), /writer request sits in released text/);
  assert.match(broken(j => { j.mode = 'separate'; }), /keeps them separate/);
  assert.match(broken(j => { j.sessions.forEach(s => { s.threads = [0, 1]; }); }), /No session teaches “Development”/);
});
test('a claim is never upgraded by a link that opens or a page the AI read', () => {
  const j = draft(), [fact, guess] = j.sessions[0].claims;
  assert.match(J.standing(fact, j), /reached the AI.*Not yet checked by a person/); assert.match(J.standing(guess, j), /judgement/);
  j.sources[0].personChecked = { at: '2026-09-27T12:00:00Z' }; assert.match(J.standing(fact, j), /A person has read the source, but has not checked this claim against it/); assert.doesNotMatch(J.standing(fact, j), /confirmed|supports this/);
  assert.match(J.standing(Object.assign({}, fact, { personChecked: { at: '2026-09-28T09:00:00Z' } }), j), /checked this claim against its source on 28 Sept? 2026/);
  assert.match(J.standing({ type: 'fact', sources: ['S2'] }, j), /did not reach the AI/); assert.match(J.standing({ type: 'fact', sources: [] }, j), /no source/i); assert.match(J.standing({ type: 'fiction', sources: [] }, j), /Fiction/);
  const rd = R.readiness(j); assert.ok(rd.look.some(l => /1 of 2 sources have not been read/.test(l))); assert.ok(rd.look.some(l => /only partly justified/.test(l)));
});
test('direct edits: applied as typed, timing recalculated, dependents flagged, nothing else rewritten', () => {
  const j = draft(), before = JSON.stringify(j);
  const r = R.applyDirect(j, { kind: 'activity', sessionId: 's1', activityId: 'a2', fields: { title: 'Sketch the page', goal: 'A paper sketch', minutes: '30', instructions: '1. Read the brief.\n2) Sketch it.\n\nShow a partner.', materials: 'Paper\nPens', handout: 'NEW BRIEF', example: '', guidance: 'Walk round.', success: 'A sketch exists.' } });
  assert.equal(JSON.stringify(j), before, 'the draft itself is not touched'); const s = r.after.sessions[0], x = s.activities[1];
  assert.deepEqual(x.instructions, ['Read the brief.', 'Sketch it.', 'Show a partner.']); assert.equal(x.origin, 'edited'); assert.equal(s.minutes, 50); assert.equal(r.plan.differs, true); assert.deepEqual(s.teacher.materials, ['Paper', 'Pens']);
  assert.deepEqual(r.flagged, ['s2']); assert.match(r.after.sessions[1].review.reason, /builds on/); assert.equal(JSON.stringify(r.after.sessions[2]), JSON.stringify(j.sessions[2]), 'a session that does not depend on it is untouched');
  assert.equal(JSON.stringify({ ...r.after.sessions[1], review: null }), JSON.stringify(j.sessions[1]), 'the flagged session is marked, not rewritten');
  assert.equal(r.after.budget, 180); assert.deepEqual(J.audit(r.after), []);
  for (const [f, m] of [[{ minutes: '0' }, /whole number/], [{ minutes: '2.5' }, /whole number/], [{ minutes: 'soon' }, /whole number/], [{ minutes: '30', title: '' }, /title/], [{ minutes: '30', title: 'T', instructions: '  ' }, /instruction/]]) assert.match(R.applyDirect(j, { kind: 'activity', sessionId: 's1', activityId: 'a2', fields: { title: 'T', goal: 'G', instructions: 'a\nb', ...f } }).error, m);
  assert.ok(R.applyDirect(j, { kind: 'activity', sessionId: 's1', activityId: 'a2', fields: { title: x.title && j.sessions[0].activities[1].title, goal: j.sessions[0].activities[1].goal, minutes: '40', instructions: j.sessions[0].activities[1].instructions.join('\n'), materials: 'Paper', handout: j.sessions[0].activities[1].handout, example: '', guidance: 'Watch the pairs.', success: 'Visible in the work.' } }).same, 'saving without a change changes nothing');
  assert.match(R.applyDirect(j, { kind: 'session', sessionId: 's1', fields: { title: 'T', outcome: 'O', success: 'only one', checkTask: 'T', checkWhen: 'W', checkLooks: 'L' } }).error, /two success criteria/);
  assert.match(R.applyDirect(j, { kind: 'activity', sessionId: 'gone', activityId: 'a2', fields: {} }).error, /no longer/);
});
test('a change made by Claude becomes a preview tied to the draft it was made from', () => {
  const j = draft(), before = JSON.stringify(j), changed = session('Part 1', 60, ['Marketing', 'Design', 'Development']); changed.outcome = 'A sharper outcome';
  const edit = { id: 'e1', instruction: 'Sharper', baseRev: 1, baseUid: j.uid, parts: [{ number: 1, output: { acted: true, note: 'Changed the outcome.', session: changed } }] }, req = { scope: 'session', kind: 'text', text: 'Sharper', sessionId: 's1' };
  const p = R.previewFromEdit(j, edit, req); assert.equal(JSON.stringify(j), before); assert.equal(p.noop, false); assert.equal(p.kind, 'ai'); assert.equal(p.baseRev, 1);
  assert.ok(p.lines.some(l => l.label === 'Outcome' && l.now === 'A sharper outcome')); assert.ok(p.effects.some(e => /marked for a look/.test(e)));
  const r = J.applyPreview(j, p, 2); assert.ok(r.ok); assert.equal(r.journey.sessions[0].outcome, 'A sharper outcome'); assert.deepEqual(J.audit(r.journey), []);
  const moved = { ...j, rev: 5 }; assert.equal(R.previewFromEdit(moved, edit, req).gone, true, 'a result for an older draft is refused'); assert.equal(J.applyPreview(moved, p, 6).ok, false);
});
test('when Claude declines a request it stays internal and never reaches an export', () => {
  const j = draft();
  for (const scope of ['activity', 'session', 'journey']) {
    const parts = (scope === 'journey' ? [1, 2, 3] : [1]).map(n => ({ number: n, output: { acted: false, note: 'Too vague to act on.', [scope === 'activity' ? 'activity' : 'session']: {} } }));
    const p = R.previewFromEdit(j, { id: 'e2', instruction: 'Add llamas somehow', baseRev: 1, baseUid: j.uid, parts }, { scope, kind: 'text', text: 'Add llamas somehow', sessionId: 's1', activityId: 'a2' });
    assert.equal(p.noop, false, scope); const after = J.applyPreview(j, p, 2).journey;
    assert.equal(J.internalNotes(after).filter(n => /llamas/.test(n)).length, 1, `${scope}: one note, not one per session`);
    assert.equal(JSON.stringify(after.sessions.map(s => s.activities.map(x => [x.learner, x.teacher, x.instructions, x.guidance]))), JSON.stringify(j.sessions.map(s => s.activities.map(x => [x.learner, x.teacher, x.instructions, x.guidance]))));
    assert.ok(!JSON.stringify(J.buildPackage({ ver: 1, at: 'x', journey: after })).includes('llamas'), scope);
  }
});
test('the export of real content carries tasks, guidance and honest evidence, and no internal notes', () => {
  const j = draft(); j.review = { at: 'x', rev: 1, output: { areas: [{ area: 'clarity', verdict: 'concerns', summary: 'SECRET-REVIEW-SUMMARY' }], findings: [{ severity: 'must_fix', area: 'clarity', session: 1, finding: 'SECRET-FINDING', suggestion: 'SECRET-SUGGESTION' }], teacher_could_run_it: { answer: 'with_changes', why: 'SECRET-WHY' } } };
  j.internal.push('SECRET-JOURNEY-NOTE'); j.sessions[0].internal.push('SECRET-SESSION-NOTE'); j.sessions[0].activities[1].internal.push('SECRET-STEP-NOTE'); j.sessions[1].review = { reason: 'SECRET-LOOK-REASON' };
  const p = J.buildPackage({ ver: 2, at: '2026-09-27T12:00:00Z', journey: j }), out = JSON.stringify(p);
  assert.ok(!/SECRET/.test(out)); assert.equal(p.howItWasMade, 'Written with Claude');
  const step = p.learnerMaterials[0].steps[1]; assert.deepEqual(step.instructions, ['Do the first thing.', 'Do the second thing.']); assert.equal(step.handout, 'BRIEF: a craft market on Saturday.'); assert.deepEqual(p.learnerMaterials[0].successCriteria.length, 2);
  assert.ok(!JSON.stringify(p.learnerMaterials).includes('Watch the pairs'), 'teacher guidance stays out of learner materials');
  const t = p.teacherMaterials[0]; assert.deepEqual(t.stepNotes[1].guidance, ['Watch the pairs.']); assert.equal(t.stepNotes[1].likelyMisconceptions.length, 1); assert.equal(t.requirementsToImplement.length, 2); assert.equal(t.laterCheck.task, 'Do it for a different event, alone.');
  assert.equal(p.evidence.sources[0].readByAPersonOn, null); assert.equal(p.evidence.claims[0].checkedAgainstSourceByAPersonOn, null); assert.equal(p.evidence.sources[1].pageReachedTheAI, 'no'); assert.equal(p.evidence.sources[1].retrievedOn, null); assert.equal(p.evidence.sources[0].pageReachedTheAI, 'yes'); assert.equal(p.evidence.sources[0].retrievedOn, '2026-09-27T10:00:00Z');
  assert.match(p.evidence.claims[0].standing, /Not yet checked by a person/); assert.equal(p.learnerMaterials.reduce((n, s) => n + s.minutes, 0), p.course.planned.minutes);
  assert.equal(p.course.topicConnection.status, 'partly');
});
test('what a brief change affects is listed, and the journey is left alone', () => {
  const now = JSON.parse(JSON.stringify(A)); now.audience = { value: 'pro' }; now.time = { value: 'day' };
  const ch = R.briefChanges(A, now); assert.deepEqual(ch.map(c => c.id).sort(), ['audience', 'time']);
  assert.match(ch.find(c => c.id === 'time').affects, /timing/); assert.equal(ch.find(c => c.id === 'audience').was, 'College students');
  assert.deepEqual(R.briefChanges(A, A), []);
});
test('kept separate: the draft keeps one topic to a session and claims no connection', () => {
  const a = brief({ ...Object.fromEntries(Object.entries(A).map(([k, v]) => [k, v.value])), mode: 'separate' }), o = outline(['Marketing'], 3, 'kept_separate'); o.sessions.forEach((s, i) => { const t = ['Marketing', 'Design', 'Development'][i]; s.topics = [t]; s.contributions = [{ topic: t, gives: 'x' }]; });
  const j = R.fromOutline(o, R.briefFor(a), R.planFor(a), research, a); assert.equal(j.mode, 'separate'); assert.ok(j.sessions.every(s => s.threads.length === 1)); assert.equal(j.connections[0].type, 'Kept separate'); assert.ok(!J.audit(j).some(p => /separate|teaches/.test(p)));
});
test('saved state: real drafts, pending AI previews and damaged records', () => {
  const s = { ...Store.fresh(), answers: A, journey: draft(), revSeq: 1 }; s.journey.review = { at: 'x', rev: 1, output: { areas: [], findings: [], teacher_could_run_it: { answer: 'yes', why: '' } } };
  assert.equal(Store.inspect(JSON.stringify(s)).status, 'ok');
  const withAI = { ...s, pending: { kind: 'ai', editId: 'e1abc', baseRev: 1, baseUid: s.journey.uid, after: { planted: true }, req: { scope: 'session', kind: 'text', text: 'x', sessionId: 's1' }, label: 'x', target: 'y' } };
  const r = Store.inspect(JSON.stringify(withAI)); assert.equal(r.status, 'ok'); assert.equal(r.state.pending.needsRebuild, true); assert.equal(r.state.pending.after, undefined, 'a saved AI preview is never trusted; it is rebuilt from the server’s record');
  const bad = f => { const c = JSON.parse(JSON.stringify(s)); f(c); return Store.inspect(JSON.stringify(c)).status; };
  assert.equal(bad(c => { c.journey.sources = [{ id: 1 }]; }), 'damaged'); assert.equal(bad(c => { c.journey.origin = 'magic'; }), 'damaged'); assert.equal(bad(c => { c.journey.sessions[0].status = 'half'; }), 'damaged');
  assert.equal(bad(c => { c.journey.sessions[0].activities[0].instructions = 'text'; }), 'damaged'); assert.equal(bad(c => { c.journey.sessions[0].activities[1].minutes = 41; }), 'damaged');
});

test('continuity: a request carries the sessions as the team has them now, and never an unwritten one', () => {
  const j = { origin: 'claude', sessions: [
    { id: 's1', status: 'written', title: 'One', outcome: 'o', serves: '', teacher: { prep: 5, prepSteps: ['Print'] }, activities: [{ kindKey: 'make', title: 'Build', goal: 'g', minutes: 60, instructions: ['Type it'], handout: 'GRID', guidance: ['Watch'], internal: ['Request for the writer: x'] }], internal: ['note'] },
    { id: 's2', status: 'pending', title: 'Two', teacher: {}, activities: [], buildsOn: ['s1'] },
    { id: 's3', status: 'failed', title: 'Three', teacher: {}, activities: [], buildsOn: ['s1', 's2', 'gone'] }] };
  const w = R.writtenNow(j);
  assert.deepEqual(w.map(x => x.number), [1]);
  assert.equal(w[0].content.activities[0].handout, 'GRID');
  assert.ok(!JSON.stringify(w).includes('Request for the writer'), 'internal notes are not sent as course content');
  assert.deepEqual(R.numbersOf(j, j.sessions[2].buildsOn), [1, 2]);
  assert.deepEqual(R.writtenNow({ origin: 'simulated', sessions: j.sessions }), []);
  assert.deepEqual(R.writtenNow(null), []);
});

test('a break is a step with a name and minutes, and needs nothing else', () => {
  const out = { kind: 'break', title: 'Break', goal: '', minutes: 10, instructions: [], materials: [], handout: '', worked_example: '', teacher: [], misconceptions: [], success: [] };
  const x = R.activityFrom(out, 'a9');
  assert.equal(x.kind, 'Break');
  assert.equal(x.minutes, 10);
  assert.deepEqual(R.activityBack(x).kind, 'break');
});

test('an export says what stood open at approval, in counts, and never carries the reviewer’s words', () => {
  const j = draft();
  j.review = { at: '2026-09-27T10:00:00Z', rev: j.rev, output: { areas: [{ area: 'clarity', verdict: 'serious_problems', summary: 'SECRET-AREA-SUMMARY the cell addresses disagree' }], findings: [{ severity: 'must_fix', area: 'clarity', session: 2, finding: 'SECRET-FINDING session two cannot be run', suggestion: 'SECRET-SUGGESTION renumber it' }, { severity: 'should_fix', area: 'timing', session: 1, finding: 'SECRET-TIMING tight', suggestion: 'SECRET-CUT trim' }], teacher_could_run_it: { answer: 'with_changes', why: 'SECRET-WHY fix two things' } } };
  const open = ['The independent review lists 1 problem marked “must fix”.', '1 of 1 sources have not been checked by a person.'];
  const snap = { ver: 1, at: '2026-09-27T11:00:00Z', journey: j, brief: A, openAtApproval: open };
  const pkg = J.buildPackage(snap), text = JSON.stringify(pkg);
  assert.equal(pkg.standingAtApproval.findingsMarkedMustFix, 1);
  assert.equal(pkg.standingAtApproval.findingsMarkedShouldFix, 1);
  assert.equal(pkg.standingAtApproval.couldATeacherRunIt, 'with changes');
  assert.deepEqual(pkg.standingAtApproval.openPointsAcknowledgedAtApproval, open);
  assert.match(pkg.standingAtApproval.taughtToLearners, /^No\./);
  assert.match(pkg.standingAtApproval.independentReview, /^Made on this version/);
  assert.ok(!/SECRET/.test(text), 'no finding, suggestion, summary or reason from the review is in the package');
  const later = JSON.parse(JSON.stringify(snap)); later.journey.rev = j.rev + 3;
  assert.match(J.buildPackage(later).standingAtApproval.independentReview, /^Made on an earlier draft/);
  const none = JSON.parse(JSON.stringify(snap)); none.journey.review = null; delete none.openAtApproval;
  assert.equal(J.buildPackage(none).standingAtApproval.independentReview, 'None was run before approval.');
  assert.equal(J.buildPackage(none).standingAtApproval.openPointsAcknowledgedAtApproval, null);
  const s = Object.assign(Store.fresh(), { answers: A, at: 'journey', journey: j, jDigest: F.briefDigest(A), jBrief: A, revSeq: j.rev, life: { stage: 'approved', ver: 1, snapshots: [snap], exports: [], publications: [] } });
  assert.equal(Store.inspect(JSON.stringify(s)).status, 'ok', 'a saved course with this record opens');
});

test('a fact that rests only on partial support is flagged, and the export says so', () => {
  const j = draft();
  const s = j.sessions[0]; s.claims = [{ text: 'Visitors scan before they read', type: 'fact', sources: ['S1'], note: '' }];
  j.sources = j.sources.map(x => Object.assign({}, x, { strength: x.id === 'S1' ? 'partial' : x.strength }));
  assert.equal(J.thinFact(s.claims[0], j), true);
  assert.match(J.standing(s.claims[0], j), /only in part/);
  assert.ok(R.readiness(j).look.some(t => /only in part/.test(t)));
  j.sources = j.sources.map(x => Object.assign({}, x, { strength: 'direct' }));
  assert.equal(J.thinFact(s.claims[0], j), false);
  assert.equal(J.thinFact({ type: 'uncertain', sources: ['S1'] }, j), false);
});

test('asking for a page, the page arriving, supporting a claim and a person reading it are four different things', () => {
  const j = draft(), fact = { text: 'x', type: 'fact', sources: ['S1'], support: 'stated_by_source' };
  const set = o => { j.sources[0] = Object.assign({}, j.sources[0], o); };
  for (const st of ['failed', 'redirected', 'no_result', 'none']) { set({ fetch: st, openedByAI: false }); assert.match(J.standing(fact, j), /did not reach the AI/, st); assert.doesNotMatch(J.fetchLine(j.sources[0]), /reached the AI/, st); }
  set({ fetch: undefined, openedByAI: true }); // a record made before results were kept
  assert.match(J.standing(fact, j), /Whether the page arrived was not recorded/); assert.match(J.fetchLine(j.sources[0]), /Whether it arrived was not recorded/);
  set({ fetch: 'retrieved', openedByAI: true }); assert.match(J.standing(fact, j), /reached the AI/);
  assert.match(J.standing(Object.assign({}, fact, { support: 'partly' }), j), /only in part/);
  assert.equal(J.thinFact(Object.assign({}, fact, { support: 'not_from_source' }), j), true);
  set({ personChecked: { at: '2026-09-28T09:00:00Z' } }); assert.match(J.standing(fact, j), /has not checked this claim/);
  const thin = Object.assign({}, fact, { support: 'partly' }); assert.match(J.standing(thin, j), /only in part/); assert.doesNotMatch(J.standing(thin, j), /confirmed/, 'a source someone has read never confirms a claim it only partly supports');
  set({ fetch: undefined, openedByAI: true, personChecked: null }); j.sources[1] = Object.assign({}, j.sources[1], { fetch: 'retrieved', openedByAI: true }); assert.doesNotMatch(J.standing({ type: 'fact', sources: ['S1', 'S2'], support: 'stated_by_source' }, j), /reached the AI/, 'one older record among the sources is enough to withhold the wording');
});

test('a plain word check finds things the brief does not allow, and is not fooled by “no stapler”', () => {
  const j = draft(); const req = t => j.sessions.forEach(s => { s.teacher.requirements = t.map(x => J.REQ + x); });
  const a = j.sessions[0].activities[1], b = j.sessions[1].activities[1];
  a.instructions = ['Put your notes in the middle of the table.', 'There is no stapler in this room. Fold the slip.']; b.guidance = ['Staple each set before you collect it.'];
  req(['free tools only']); assert.deepEqual(R.outsideBrief(j), [], 'no closed list, nothing to check against');
  req(['Only paper, markers, sticky notes, chairs and printed research that we supply']);
  const got = R.outsideBrief(j), names = got.map(x => x.name).sort();
  assert.deepEqual(names, ['stapler', 'table']);
  assert.deepEqual(got.find(x => x.name === 'stapler').sessions, [2], 'the sentence that rules a stapler out is not counted');
  assert.ok(R.readiness(j).look.some(t => /Word check: “table”/.test(t)));
  req(['Only paper, markers, tables and a stapler']); assert.deepEqual(R.outsideBrief(j), []);
  req(['every task must work on paper, with no devices']); a.instructions = ['Open your laptop.']; assert.deepEqual(R.outsideBrief(j).map(x => x.name), ['laptop']);
  assert.deepEqual(R.outsideBrief({ origin: 'simulated', sessions: j.sessions }), []);
});

test('the course statement and a session’s assumptions can be edited by hand, with Undo-ready copies and honest flags', () => {
  const j = draft(); j.finalEvidence = 'One stapled set.'; j.assumptions = ['A stapler is on the table.'];
  const r = R.applyDirect(j, { kind: 'course', fields: { finalEvidence: 'One folded set.', courseAssumptions: 'Nothing is stapled.\n\nTwo facilitators.' } });
  assert.equal(r.after.finalEvidence, 'One folded set.'); assert.deepEqual(r.after.assumptions, ['Nothing is stapled.', 'Two facilitators.']);
  assert.equal(j.finalEvidence, 'One stapled set.', 'the draft given in is not touched');
  assert.equal(r.flagged.length, 3); assert.ok(r.after.sessions.every(s => s.review && s.review.because === 'course'));
  assert.ok(R.applyDirect(j, { kind: 'course', fields: { finalEvidence: 'One stapled set.', courseAssumptions: 'A stapler is on the table.' } }).same);
  assert.ok(R.applyDirect(j, { kind: 'course', fields: { finalEvidence: ' ' } }).error);
  const only = R.applyDirect(j, { kind: 'course', fields: { finalEvidence: 'One stapled set.', courseAssumptions: 'Changed.' } }); assert.equal(only.flagged.length, 0, 'an assumption alone flags nothing');
  const s = j.sessions[0], f = { title: s.title, outcome: s.outcome, success: s.successCriteria.join('\n'), checkTask: s.applicationCheck.task, checkWhen: s.applicationCheck.when, checkLooks: s.applicationCheck.looksFor.join('\n'), prerequisites: s.prerequisites.map(q => q.name + ' — ' + q.support).join('\n') };
  const e = R.applyDirect(j, { kind: 'session', sessionId: s.id, fields: Object.assign({}, f, { assumptions: 'No stapler.', prepSteps: 'Print 20.\nCut cards.', prep: '35' }) });
  assert.deepEqual(e.after.sessions[0].assumptions, ['No stapler.']); assert.deepEqual(e.after.sessions[0].teacher.prepSteps, ['Print 20.', 'Cut cards.']); assert.equal(e.after.sessions[0].teacher.prep, 35);
  assert.ok(R.applyDirect(j, { kind: 'session', sessionId: s.id, fields: Object.assign({}, f, { assumptions: '', prepSteps: '', prep: 'soon' }) }).error);
});

test('approval with blockers open is an internal draft, in the record and in the export', () => {
  const j = draft(); j.review = { at: 'x', rev: j.rev, output: { areas: [], findings: [{ severity: 'must_fix', area: 'clarity', session: 1, finding: 'REVIEWER-WORDS-ONE', suggestion: 'REVIEWER-WORDS-TWO' }], teacher_could_run_it: { answer: 'with_changes', why: 'REVIEWER-WORDS-THREE' } } };
  const snap = { ver: 1, at: '2026-09-28T09:00:00Z', journey: j, brief: A, openAtApproval: ['x'] };
  assert.equal(J.readinessOf(snap).draft, true); assert.match(J.readinessOf(snap).label, /^Internal draft\. Not ready to teach/);
  const pkg = J.buildPackage(snap); assert.match(pkg.readiness, /Not ready to teach/); assert.equal(Object.keys(pkg)[1], 'readiness'); assert.ok(!/REVIEWER-WORDS/.test(JSON.stringify(pkg)));
  j.review.output = { areas: [], findings: [{ severity: 'note', area: 'clarity', session: 1, finding: 'REVIEWER-WORDS-FOUR', suggestion: 'REVIEWER-WORDS-FIVE' }], teacher_could_run_it: { answer: 'yes', why: 'REVIEWER-WORDS-SIX' } };
  // A clean review is not enough while the evidence is open: a point that was read and ticked at approval is still open.
  const thin = J.readinessOf(snap); assert.equal(thin.draft, true); assert.ok(thin.why.some(w => /called facts.*not been checked against/.test(w)), thin.why.join(' '));
  assert.match(J.buildPackage(snap).threeSeparateQuestions.internalApproval, /1 open point read and ticked\. Ticking a point does not resolve it/); assert.match(J.buildPackage(snap).threeSeparateQuestions.structure, /^Holds/);
  for (const s of j.sessions) s.claims = R.checkClaim(j, s.id, 0).after.sessions.find(x => x.id === s.id).claims;
  const ok = J.readinessOf(snap); assert.equal(ok.draft, false); assert.match(ok.label, /Not yet rehearsed by a teacher or tried with learners/);
  j.rev += 1; assert.equal(J.readinessOf(snap).draft, true, 'a review of an earlier draft does not count');
  j.review = null; assert.equal(J.readinessOf(snap).draft, true);
});

test('brief: a short custom format, room and online together, group size and described prior knowledge', () => {
  const b = o => brief(Object.assign({ entry: 'have', topic: 'Zines', audience: 'mixed', prior: 'new', outcome: 'Make an eight-page zine', delivery: 'hybrid', limits: ['none'] }, o));
  const jam = b({ format: { value: F.CUSTOM, text: 'Design jam' }, shape: 'once', time: { value: F.CUSTOM, text: '90 minutes' } });
  assert.equal(F.usesWeeks(jam), false); assert.ok(!F.activePath(jam).some(q => q.id === 'hours')); assert.equal(F.activePath(jam).filter(q => F.problem(q, jam)).length, 0);
  assert.equal(J.request(jam).total, 90); assert.equal(R.planFor(jam).total, 90); assert.equal(R.briefFor(jam).runsAs, 'In one go');
  const old = b({ format: { value: F.CUSTOM, text: 'Residency' }, time: 'w4', hours: '2' }); assert.equal(F.usesWeeks(old), true, 'a saved brief without the new answer keeps its meaning');
  const ws = b({ format: 'workshop', time: 'half' }); assert.ok(F.byId('delivery').options(ws).some(o => o.v === 'hybrid')); assert.equal(R.briefFor(ws).delivery, 'Room and online together'); assert.equal(R.briefFor(ws).groupSize, 'Not given');
  const before = F.briefDigest(ws); assert.ok(!before.includes('group'), 'an unanswered optional question does not make an old journey look out of date');
  const sized = b({ format: 'workshop', time: 'half', group: { value: F.CUSTOM, text: '18' }, prior: { value: F.CUSTOM, text: 'Can use a ruler. Has never folded a booklet.' } });
  assert.equal(R.briefFor(sized).groupSize, '18'); assert.match(R.briefFor(sized).prior, /never folded/); assert.notEqual(F.briefDigest(sized), before);
  for (const bad of ['0', 'lots', '18 people', '1000']) assert.ok(F.problem(F.byId('group'), b({ format: 'workshop', time: 'half', group: { value: F.CUSTOM, text: bad } })), bad);
  assert.doesNotThrow(() => J.makeJourney(ws)); assert.doesNotThrow(() => J.makeJourney(jam));
});

test('find and replace changes the same words everywhere in the draft, and nothing else', () => {
  const j = draft(); j.finalEvidence = 'One stapled set per learner.'; j.assumptions = ['Sets are stapled.'];
  j.sessions[0].activities[1].instructions = ['Write in B45.', 'Read B45 aloud.']; j.sessions[2].activities[1].misconceptions = [{ belief: 'B45 is typed', response: 'B45 is a formula' }];
  j.sessions[1].claims.push({ text: 'B45 holds the left over figure', type: 'hypothesis', sources: [], note: '' }); j.sessions[2].internal = ['Request for the writer: “B45”'];
  const copy = JSON.stringify(j), r = R.replaceText(j, 'B45', 'the LEFT OVER cell');
  assert.equal(JSON.stringify(j), copy, 'the draft given in is not touched');
  assert.equal(r.total, 5); assert.deepEqual([...new Set(r.hits.map(h => h.where))], ['Block 1', 'Block 2', 'Block 3']);
  const text = JSON.stringify(r.after.sessions.map(s => Object.assign({}, s, { internal: [] }))); assert.ok(!text.includes('B45'));
  assert.deepEqual(r.after.sessions[2].internal, ['Request for the writer: “B45”'], 'internal notes are left alone');
  assert.equal(r.after.sessions[0].activities[1].learner, '1. Write in the LEFT OVER cell.\n2. Read the LEFT OVER cell aloud.');
  assert.equal(r.after.sessions[0].minutes, j.sessions[0].minutes); assert.equal(r.after.sessions[0].origin, 'edited');
  const c = R.replaceText(j, 'stapled', 'folded'); assert.equal(c.after.finalEvidence, 'One folded set per learner.'); assert.deepEqual(c.after.assumptions, ['Sets are folded.']);
  j.sessions[0].prerequisites = [{ name: 'A laptop or a csv file', support: 'Bring the csv on a USB stick' }]; const pr = R.replaceText(j, 'csv', 'xlsx'); assert.deepEqual(pr.after.sessions[0].prerequisites, [{ name: 'A laptop or a xlsx file', support: 'Bring the xlsx on a USB stick' }], 'the support written for a prerequisite is text too');
  assert.ok(R.replaceText(j, 'b45', 'x').none, 'capital letters must match');
  assert.ok(R.replaceText(j, 'B', 'x').error); assert.ok(R.replaceText(j, 'B45', 'B45').error); assert.ok(R.replaceText({ origin: 'simulated', sessions: [] }, 'ab', 'cd').error);
  assert.equal(R.replaceText(j, 'Read B45 aloud.', '').after.sessions[0].activities[1].instructions.length, 2, 'an emptied line is kept for the person to remove by hand');
});

test('a person can lower a claim from fact, and cannot raise one', () => {
  const j = draft(), s = j.sessions[0]; s.claims = [{ text: 'SUM is the right first formula to teach', type: 'fact', sources: ['S1'], note: '' }];
  const r = R.retypeClaim(j, s.id, 0, 'hypothesis'); assert.equal(r.after.sessions[0].claims[0].type, 'hypothesis'); assert.equal(r.after.sessions[0].claims[0].was, 'fact'); assert.equal(j.sessions[0].claims[0].type, 'fact');
  assert.match(J.standing(r.after.sessions[0].claims[0], r.after), /judgement/);
  assert.ok(R.retypeClaim(j, s.id, 0, 'fact').error); assert.ok(R.retypeClaim(j, s.id, 9, 'uncertain').error); assert.ok(R.retypeClaim(j, 'nope', 0, 'uncertain').error);
  assert.doesNotThrow(() => J.buildPackage({ ver: 1, at: '2026-09-28T09:00:00Z', journey: r.after, brief: A }));
});

test('the readable pack: learner handouts hold no teacher guidance, neither holds internal notes, and the status is on the first screen', () => {
  const j = draft(); j.sessions[0].activities[1].guidance = ['TEACHER-ONLY watch the quiet pair']; j.sessions[0].activities[1].misconceptions = [{ belief: 'TEACHER-ONLY belief', response: 'TEACHER-ONLY response' }]; j.sessions[0].activities[1].handout = 'HANDOUT <b>grid</b> & rows'; j.sessions[0].activities[1].example = 'TEACHER-ONLY worked example';
  j.sessions[0].internal = ['INTERNAL-NOTE do not ship']; j.sessions[0].activities[1].teacher = j.sessions[0].activities[1].guidance.join(' ');
  const pkg = J.buildPackage({ ver: 3, at: '2026-09-28T09:00:00Z', journey: j, brief: A }), t = J.packHTML(pkg, 'teacher'), l = J.packHTML(pkg, 'learner');
  assert.ok(!/TEACHER-ONLY/.test(l)); assert.ok(/TEACHER-ONLY watch/.test(t)); assert.ok(/TEACHER-ONLY worked example/.test(t));
  for (const x of [t, l]) { assert.ok(!/INTERNAL-NOTE/.test(x)); assert.ok(x.includes('HANDOUT &lt;b&gt;grid&lt;/b&gt; &amp; rows'), 'text is shown as text'); assert.ok(x.indexOf('Not ready to teach') > 0 && x.indexOf('Not ready to teach') < x.indexOf('<h2'), 'readiness comes before the first session'); assert.ok(!/<script/i.test(x)); }
  assert.ok(/Evidence<\/h2>/.test(t)); assert.ok(!/Evidence<\/h2>/.test(l));
});

test('four levels of readiness, and a tick never moves a version up', () => {
  const j = draft(); j.review = { at: 'x', rev: j.rev, output: { areas: [], findings: [], teacher_could_run_it: { answer: 'yes', why: 'fine' } } };
  const snap = { ver: 2, at: '2026-09-28T09:00:00Z', journey: j, brief: A };
  assert.equal(J.readinessOf(snap).level, 'internal', 'facts nobody has checked keep it an internal draft, however clean the review');
  for (const s of j.sessions) s.claims = R.checkClaim(j, s.id, 0).after.sessions.find(x => x.id === s.id).claims;
  assert.equal(J.readinessOf(snap).level, 'reviewed'); assert.match(J.readinessOf(snap).label, /ready for a facilitator rehearsal/);
  assert.equal(J.readinessOf(snap, [{ ver: 1, kind: 'pilot', at: '2026-09-20T12:00:00Z' }]).level, 'reviewed', 'a pilot of another version does not count');
  assert.equal(J.readinessOf(snap, [{ ver: 2, kind: 'rehearsal', at: '2026-09-29T12:00:00Z', note: 'Ran 8 minutes over' }]).level, 'rehearsed');
  assert.equal(J.readinessOf(snap, [{ ver: 2, kind: 'rehearsal', at: '2026-09-29T12:00:00Z' }, { ver: 2, kind: 'pilot', at: '2026-10-02T12:00:00Z' }]).level, 'piloted');
  j.review.output.findings = [{ severity: 'must_fix', area: 'clarity', session: 1, finding: 'a', suggestion: 'b' }];
  assert.equal(J.readinessOf(snap, [{ ver: 2, kind: 'pilot', at: '2026-10-02T12:00:00Z' }]).level, 'internal', 'open blockers keep it an internal draft whatever is recorded');
  const s = Object.assign(Store.fresh(), { answers: A, at: 'journey', journey: j, jDigest: F.briefDigest(A), jBrief: A, revSeq: j.rev, life: { stage: 'approved', ver: 2, snapshots: [snap], exports: [], publications: [], trials: [{ ver: 2, kind: 'pilot', at: '2026-10-02T12:00:00Z', note: 'x' }, { ver: 2, kind: 'party', at: 'never' }, 'junk'] } });
  const got = Store.inspect(JSON.stringify(s)); assert.equal(got.status, 'ok'); assert.equal(got.state.life.trials.length, 1);
});

test('a person’s check of a claim does not survive a change to the claim, by any route, and the export says so', () => {
  const j = draft(), sid = j.sessions[0].id, legacy = clone_(j);
  // A check made with this build records what was checked.
  const checked = R.checkClaim(j, sid, 0).after, c0 = checked.sessions[0].claims[0];
  assert.ok(c0.personChecked.of, 'the check records the claim it was made on'); assert.equal(J.checkedOn(c0), c0.personChecked.at); assert.match(J.standing(c0, checked), /checked this claim against its source/);
  // Find and replace turns the claim into its opposite.
  const r = R.replaceText(checked, 'Visitors scan', 'Visitors never scan'), c1 = r.after.sessions[0].claims[0];
  assert.equal(c1.text, 'Visitors never scan before they read'); assert.equal(r.withdrawn, 1); assert.equal(c1.personChecked, null); assert.equal(c1.checkWithdrawn.was, c0.personChecked.at);
  assert.equal(checked.sessions[0].claims[0].personChecked.at, c0.personChecked.at, 'the draft given in, and so any earlier copy of it, keeps its check');
  assert.match(J.standing(c1, r.after), /checked an earlier wording of this claim/); assert.doesNotMatch(J.standing(c1, r.after), /checked this claim against its source on/);
  const p = J.buildPackage({ ver: 3, at: '2026-09-28T12:00:00Z', journey: r.after, brief: A }), e = p.evidence.claims[0];
  assert.equal(e.claim, 'Visitors never scan before they read'); assert.equal(e.checkedAgainstSourceByAPersonOn, null); assert.equal(e.checkWithdrawnBecauseTheClaimChanged, true); assert.match(e.standing, /has changed since and has not been checked again/);
  assert.match(J.packHTML(p, 'teacher'), /has changed since and has not been checked again/); assert.doesNotMatch(J.packHTML(p, 'teacher'), /checked this claim against its source on/);
  // The approved version made before the change still says what was true of it.
  const old = J.buildPackage({ ver: 2, at: '2026-09-28T10:00:00Z', journey: checked, brief: A }); assert.equal(old.evidence.claims[0].checkedAgainstSourceByAPersonOn, c0.personChecked.at);
  // A check recorded by an earlier build holds no record of what was checked. It is withdrawn when the claim differs from the one that carried it.
  legacy.sessions[0].claims[0].personChecked = { at: '2026-09-27T09:00:00Z' };
  assert.equal(R.replaceText(legacy, 'Visitors scan', 'Visitors never scan').after.sessions[0].claims[0].personChecked, null);
  assert.equal(R.replaceText(legacy, 'Do the first thing', 'Start').after.sessions[0].claims[0].personChecked.at, '2026-09-27T09:00:00Z', 'a change elsewhere leaves the check alone');
  // Any other route: the words, the label, what the source is recorded as stating, or the sources cited.
  for (const change of [c => { c.text += ' on phones'; }, c => { c.sources = ['S2']; }, c => { c.support = 'partly'; }, c => { c.sources = []; }]) {
    for (const base of [checked, legacy]) { const after = clone_(base); change(after.sessions[0].claims[0]); assert.equal(R.withdrawStaleChecks(base, after), 1); assert.equal(after.sessions[0].claims[0].personChecked, null); }
    const slipped = clone_(checked); change(slipped.sessions[0].claims[0]); assert.equal(J.checkedOn(slipped.sessions[0].claims[0]), null, 'even a change that reached the file some other way is not shown as checked');
    assert.equal(J.buildPackage({ ver: 3, at: '2026-09-28T12:00:00Z', journey: slipped, brief: A }).evidence.claims[0].checkedAgainstSourceByAPersonOn, null);
  }
  const untouched = clone_(checked); assert.equal(R.withdrawStaleChecks(checked, untouched), 0); assert.ok(untouched.sessions[0].claims[0].personChecked);
  // Relabelling withdraws it and says so. Checking again after a change is a new check of the new words.
  assert.ok(R.retypeClaim(checked, sid, 0, 'uncertain').after.sessions[0].claims[0].checkWithdrawn);
  const again = R.checkClaim(r.after, sid, 0).after.sessions[0].claims[0]; assert.ok(J.checkedOn(again)); assert.equal(again.checkWithdrawn, undefined);
  assert.equal(R.checkClaim(checked, sid, 0).after.sessions[0].claims[0].personChecked, null, 'a person can take their own check back');
  assert.deepEqual(Store.validate(Object.assign(Store.fresh(), { journey: r.after })), []);
});
function clone_(o) { return JSON.parse(JSON.stringify(o)); }

test('a review is called current only if it judged this exact material', () => {
  // Mirrors app.js onEngine(): the fingerprint the server returns is compared with the draft in front of the team.
  const absorb = (jr, rv) => { const judged = rv.inputFingerprint || '', forThis = !!judged && judged === R.reviewPrint(jr); jr.review = { at: rv.finishedAt, rev: forThis ? jr.rev : -1, of: judged, requestId: rv.requestId || '', output: rv.output }; return jr; };
  const out = { areas: [], findings: [{ severity: 'must_fix', area: 'x', session: 1, finding: 'a', suggestion: 'b' }], teacher_could_run_it: { answer: 'yes', why: 'ok' } };
  const stale = j => J.readinessOf({ ver: 1, at: 'x', journey: j }).why.join(' ');
  // Reviewed exactly what the team has: current.
  const a = draft(); a.rev = 5;
  absorb(a, { finishedAt: 't1', requestId: 'r1', inputFingerprint: R.reviewPrint(a), output: out });
  assert.equal(a.review.rev, a.rev); assert.doesNotMatch(stale(a), /earlier draft/);
  // The same content reached it, whatever revision number the draft happens to carry.
  const b = draft(); b.rev = 99; absorb(b, { finishedAt: 't1', inputFingerprint: R.reviewPrint(b), output: out });
  assert.equal(b.review.rev, 99, 'identity of the material decides this, not a revision number');
  // One word changed after the review was sent: not current.
  const c = draft(); c.rev = 5; const sentPrint = R.reviewPrint(c);
  c.sessions[0].activities[1].instructions[0] = 'Do the first thing differently.';
  absorb(c, { finishedAt: 't1', inputFingerprint: sentPrint, output: out });
  assert.equal(c.review.rev, -1); assert.match(stale(c), /earlier draft/);
  // A review whose material this build cannot identify is never claimed as current.
  for (const unknown of [undefined, '', null]) { const d = draft(); d.rev = 27; absorb(d, { finishedAt: 't1', inputFingerprint: unknown, output: out }); assert.equal(d.review.rev, -1); assert.match(stale(d), /earlier draft/); }
  // Editing after the review was absorbed still reads as an earlier draft.
  const e = draft(); e.rev = 5; absorb(e, { finishedAt: 't1', inputFingerprint: R.reviewPrint(e), output: out });
  e.rev = 6; assert.match(stale(e), /earlier draft/);
  // The fingerprint covers what a reviewer is actually shown, not incidental fields.
  const f = draft(); const before = R.reviewPrint(f);
  f.sessions[1].successCriteria = ['Something else entirely.']; assert.notEqual(R.reviewPrint(f), before);
  const g = draft(); g.rev = 4321; assert.equal(R.reviewPrint(g), R.reviewPrint(draft()), 'the revision number is not part of the material');
});

test('the page and the server fingerprint the same material the same way', () => {
  // Parity is what makes the comparison meaningful. The server's half of this is checked in tests/server/test_engine.py.
  assert.equal(J.contentPrint([{ b: 1, a: 'x' }]), '1hc1hnn.h');
  assert.equal(J.contentPrint('caf\u00e9 \u2019 quote'), '58vi0b.e');
  assert.equal(J.contentPrint({ a: 'x', b: 1 }), J.contentPrint({ b: 1, a: 'x' }), 'the order keys were written in does not matter');
  assert.notEqual(J.contentPrint({ a: '1' }), J.contentPrint({ a: 1 }), 'text and numbers are told apart');
  assert.notEqual(J.contentPrint([1, 2]), J.contentPrint([2, 1]), 'order within a list matters');
  assert.equal(J.contentPrint(null), J.contentPrint(undefined));
});


test('a simulated example sets aside a break and says what each topic is for', () => {
  // The simulated path is how most people first try the screens, so it must not promise time it has not set aside,
  // or leave a multi-topic plan with nothing to say about why each topic is there.
  const long = J.makeJourney(brief({ format: 'workshop', entry: 'have', topic: 'Negotiation', audience: 'pro', prior: 'some', outcome: 'Run a structured negotiation', delivery: 'room', time: 'half', limits: ['none'] }));
  const breaks = long.sessions.flatMap(s => s.activities).filter(a => a.kind === 'Break');
  assert.ok(breaks.length, 'a three-hour plan sets aside a break');
  assert.ok(breaks.every(b => b.minutes === 10));
  for (const s of long.sessions) assert.equal(s.activities.reduce((n, a) => n + a.minutes, 0), s.minutes, 'the break comes out of the session, it is not added to it');
  assert.deepEqual(J.audit(long), []);
  // A short session is left alone.
  const short = J.makeJourney(brief({ format: 'talk', shape: 'once', entry: 'have', topic: 'Charts', audience: 'pro', prior: 'some', outcome: 'Spot a misleading chart', delivery: 'room', time: 't20', limits: ['none'] }));
  assert.equal(short.sessions.flatMap(s => s.activities).filter(a => a.kind === 'Break').length, 0, 'a short talk is not given a break');
  // Every topic a session is tagged with says what it is for.
  const mixed = J.makeJourney(A);
  for (const s of mixed.sessions) {
    assert.equal(s.contributions.length, s.threads.length, `${s.title} says what each of its topics is for`);
    for (const c of s.contributions) { assert.ok(mixed.topics.includes(c.topic)); assert.match(c.gives, /Simulated/); }
  }
  assert.deepEqual(J.audit(mixed), []);
  // One topic on its own needs no contribution list.
  assert.deepEqual(short.sessions[0].contributions, []);
  assert.deepEqual(Store.validate(Object.assign(Store.fresh(), { journey: mixed })), []);
});

test('the team can set the number of meetings and their length, and Loom uses exactly that', () => {
  const b = o => brief(Object.assign({ format: 'workshop', entry: 'have', topic: 'Zines', audience: 'mixed', prior: 'new', outcome: 'Make an eight-page zine', delivery: 'room', time: 'half', limits: ['none'] }, o));
  // Left to Loom, nothing changes: it still works the split out.
  assert.equal(J.request(b({})).setByTeam, undefined); assert.equal(J.request(b({ pattern: 'auto' })).n, 3);
  // Only splits that use the whole time are offered.
  const offered = F.patternOptions(b({})); assert.ok(offered.length);
  for (const [, , n, per] of offered) assert.equal(n * per, 180, 'every offered pattern adds up to the time in the brief');
  // A pattern the team picks is used exactly, in the plan and in a simulated journey.
  const four = b({ pattern: 'p4' }), rq = J.request(four);
  assert.equal(rq.n, 4); assert.equal(rq.per, 45); assert.equal(rq.setByTeam, true); assert.match(rq.span, /4 meetings of 45 min/);
  assert.deepEqual(R.planFor(four).minutes, [45, 45, 45, 45]);
  const made = J.makeJourney(four); assert.equal(made.sessions.length, 4);
  assert.ok(made.sessions.every(s => s.minutes === 45)); assert.equal(J.totalMin(made), 180); assert.deepEqual(J.audit(made), []);
  // A pattern typed in words is read, and one that does not add up is refused rather than quietly rounded.
  assert.deepEqual(F.parsePattern('2 x 90 minutes', 180), { n: 2, per: 90 });
  assert.deepEqual(F.parsePattern('2 meetings of 90 minutes', 180), { n: 2, per: 90 });
  assert.match(F.parsePattern('4 x 50', 180).error, /is 3 h 20 min\. The brief says 3 h/);
  assert.match(F.parsePattern('nonsense', 180).error, /number of meetings and a length/);
  const bad = b({ pattern: { value: F.CUSTOM, text: '2 x 80' } });
  assert.equal(J.conflicts(bad).filter(c => c.id === 'pattern').length, 1, 'a pattern that does not add up is a conflict, not a silent rounding');
  // The question is optional, so a brief that never answers it is still complete.
  assert.equal(F.activePath(b({})).filter(q => F.problem(q, b({}))).length, 0);
  // A weekly format asks how the week's hours are met, and a cohort can meet more than once a week.
  const wk = o => brief(Object.assign({ format: 'cohort', entry: 'have', topic: 'Zines', audience: 'mixed', prior: 'new', outcome: 'x', delivery: 'room', time: 'w4', hours: '2', limits: ['none'] }, o));
  assert.ok(F.activePath(wk({})).some(q => q.id === 'pattern'));
  assert.ok(F.patternOptions(wk({})).every(([, label, n, per]) => n * per === 120 && / each week$/.test(label)), 'weekly patterns split the hours of one week');
  const plain = J.request(wk({})); assert.equal(plain.n, 4); assert.equal(plain.per, 120); assert.equal(plain.unit, 'Week'); assert.match(plain.cadence, /one meeting each week, 2 h/);
  for (const text of ['2 x 60 minutes', '2 × 60 minutes', '8 x 60 minutes', '2 meetings of 1 hour per week']) {
    const twice = J.request(wk({ pattern: { value: F.CUSTOM, text } }));
    assert.equal(twice.n, 8, text); assert.equal(twice.per, 60, text); assert.equal(twice.meetingsPerWeek, 2, text); assert.equal(twice.unit, 'Meeting', text); assert.equal(twice.total, 480, text); assert.equal(twice.setByTeam, true, text);
    assert.match(twice.cadence, /2 meetings each week, 1 h each/); assert.deepEqual(R.planFor(wk({ pattern: { value: F.CUSTOM, text } })).minutes, Array(8).fill(60), text);
    assert.equal(J.conflicts(wk({ pattern: { value: F.CUSTOM, text } })).filter(c => c.id === 'pattern').length, 0, text);
  }
  const twiceMade = J.makeJourney(wk({ pattern: { value: F.CUSTOM, text: '2 x 60 minutes' } })); assert.equal(twiceMade.sessions.length, 8); assert.ok(twiceMade.sessions.every(s => s.minutes === 60)); assert.deepEqual(J.audit(twiceMade), []);
  assert.deepEqual(Store.validate(Object.assign(Store.fresh(), { journey: twiceMade })), []);
  // The live-and-own-time answer travels with the cadence.
  assert.match(J.request(wk({ split: 'half' })).cadence, /about half and half/i);
  // Patterns that fit neither one week nor the whole run are refused.
  for (const text of ['3 x 60 minutes', '7 x 60 minutes', '2 x 45 minutes']) { const c = J.conflicts(wk({ pattern: { value: F.CUSTOM, text } })).filter(x => x.id === 'pattern'); assert.equal(c.length, 1, text); assert.equal(J.request(wk({ pattern: { value: F.CUSTOM, text } })).n, 4, text + ' falls back to one meeting a week until it is fixed'); }
  // A one-off pattern typed with the multiplication sign is read too.
  assert.deepEqual(F.parsePattern('4 × 45 minutes', 180), { n: 4, per: 45 });
  // A long single meeting still sets aside a break.
  const one = J.makeJourney(b({ pattern: 'p1' }));
  assert.equal(one.sessions.length, 1); assert.ok(one.sessions[0].activities.some(x => x.kind === 'Break'));
});

test('a review of freshly generated material reads as current once the page has absorbed it', () => {
  // The server fingerprints what it handed the reviewer: each session's raw output plus its number and minutes.
  // The page fingerprints its own projection of the absorbed draft. The two must agree, or every first review would
  // wrongly read as "made on an earlier draft". Confirmed live on 29 Sep (jgp19d.1ulp both sides); this keeps it so.
  // Real output always carries 'support' on every claim (the schema requires it); the shared fixture leaves it out for other tests.
  const rec = JSON.parse(JSON.stringify(record(3, 3)));
  for (const u of rec.stages.materials.sessions) for (const c of u.output.claims) c.support = c.type === 'fact' ? 'stated_by_source' : 'not_from_source';
  const j = R.fromOutline(outline(), R.briefFor(A), R.planFor(A), research, A); j.rev = 1; R.absorb(j, rec);
  const serverInput = rec.stages.materials.sessions.map((u, i) => Object.assign({}, u.output, { number: i + 1, minutes: 60 }));
  assert.equal(R.reviewPrint(j), J.contentPrint(serverInput), 'absorbing and projecting back is a round trip');
  // One edit by the team, and the same review no longer matches.
  const e = JSON.parse(JSON.stringify(j)); e.sessions[1].activities[1].instructions[0] = 'Do it differently.';
  assert.notEqual(R.reviewPrint(e), J.contentPrint(serverInput));
});

// The decision panel is markup the server now validates strictly: it must carry the evidence and the question
// revision it was drawn from, or every decision made from it is refused.
test('the decision panel carries what the server requires, and offers no as an answer', () => {
  const h = Object.assign(s => String(s), { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])), more: (a, b) => b });
  const s = { id: 'S1', claimKey: 'https://e.org/later|c1', url: 'https://e.org/later', authors: ['Bo Okafor'],
    evidenceLevel: 'direct_text_quote_found', directRetrieval: { sha256: 'a'.repeat(64) }, lineage: [],
    originalSource: { status: 'not_verified', because: ['two runs disagree'] },
    attribution: { verdict: 'yes', fingerprint: 'e3uhwg.yy',
      unresolvedDisagreements: [{ aspect: 'identity', key: 'identity', earlier: 'no', later: 'yes', revision: '1hrx86a.19' }] } };
  const html = V2.evidenceBlock(s, h);
  assert.match(html, /data-claim="https:\/\/e\.org\/later\|c1"/);
  assert.match(html, /data-key="identity"/);
  assert.match(html, /data-revision="1hrx86a\.19"/, 'without the revision every decision is refused as stale');
  assert.match(html, /data-evidence="e3uhwg\.yy"/, 'without the evidence stamp the server cannot bind the decision');
  for (const a of ['yes', 'partly', 'no', 'cannot_tell']) assert.match(html, new RegExp(`data-chosen="${a}"`), a);
  assert.match(html, /class="because"/); assert.match(html, /class="why"/);
  assert.match(html, /Waiting on a person/);
});

test('a source with nothing contested shows no decision panel', () => {
  const h = Object.assign(s => String(s), { esc: s => String(s == null ? '' : s), more: (a, b) => b });
  const s = { id: 'S1', claimKey: 'k', url: 'https://e.org/a', evidenceLevel: 'direct_text', lineage: [],
    originalSource: { status: 'verified', because: [] }, attribution: { verdict: 'yes' } };
  assert.doesNotMatch(V2.evidenceBlock(s, h), /class="decide"/);
});

test('a decision already made is shown with what Claude had said', () => {
  const h = Object.assign(s => String(s), { esc: s => String(s == null ? '' : s), more: (a, b) => b });
  const s = { id: 'S1', claimKey: 'k', url: 'https://e.org/a', evidenceLevel: 'direct_text', lineage: [],
    originalSource: { status: 'not_verified', because: [] },
    attribution: { verdict: 'no', decidedByAPerson: [{ about: 'identity', chosen: 'no', by: 'A Person',
      at: '2026-10-01T00:00:00Z', reason: 'read the erratum', theModelHadSaid: { later: 'yes' } }] } };
  const html = V2.evidenceBlock(s, h);
  assert.match(html, /Decided by a person/);
  assert.match(html, /A Person/); assert.match(html, /read the erratum/);
  assert.match(html, /Claude had said yes/, 'the model’s answer is not hidden by the decision');
});

test('refreshed evidence persists through serialization without overwriting personal checks or approved copies', () => {
  const j = draft(), approved = structuredClone(j), e = record();
  j.sources[0].personChecked = { at: 'person-check' };
  e.stages.research.output = structuredClone(e.stages.research.output);
  const source = e.stages.research.output.sources[0];
  source.claimKey = 'claim-one'; source.attribution = { verdict: 'no', decisionHistory: [{ chosen: 'no' }] };
  e.stages.research.output.nodeCoverage = [{ node: 'N1', status: 'unsupported' }];
  e.derivedStateStale = { note: 'retry needed' };
  assert.ok(R.mergeEvidence(j, e));
  const reloaded = JSON.parse(JSON.stringify(j));
  assert.equal(reloaded.sources[0].attribution.verdict, 'no');
  assert.equal(reloaded.sources[0].attribution.decisionHistory.length, 1);
  assert.deepEqual(reloaded.sources[0].personChecked, { at: 'person-check' });
  assert.equal(reloaded.research.nodeCoverage[0].status, 'unsupported');
  assert.ok(reloaded.derivedStateStale);
  assert.equal(approved.sources[0].attribution, undefined);
  delete e.derivedStateStale;
  assert.ok(R.mergeEvidence(reloaded, e));
  assert.equal(reloaded.derivedStateStale, undefined);
  assert.equal(R.mergeEvidence(reloaded, e), 0);
});

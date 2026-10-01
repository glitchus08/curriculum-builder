// Regression checks for repair pass 2: exports, previews, saved data, timing, topics. Run: node --test tests/*.test.mjs
// These check data and workflow integrity. They do not show that a course would teach well.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as J from '../js/journey.js';
import * as F from '../js/flow.js';
import * as Store from '../js/store.js';

const C = F.CUSTOM;
const brief = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
const base = { entry: 'have', topic: 'ceramics', audience: 'college', prior: 'some', outcome: 'Make a bowl', delivery: 'room', limits: ['none'] };
const total = j => j.sessions.reduce((s, x) => s + x.minutes, 0);
const accept = (j, req, rev) => { const p = J.previewChange(j, req), r = J.applyPreview(j, p, rev); assert.ok(r.ok, 'preview applies to the draft it was made from'); return r.journey; };
const first = j => ({ sessionId: j.sessions[0].id, activityId: j.sessions[0].activities[0].id });
const threeMixed = mode => brief({ ...base, format: 'course', entry: 'mix', mix: ['Typography', 'SQL', 'Negotiation'], mode, time: 'w4', hours: '2' });

/* ---- 1. writer requests never reach an export ---- */
test('1: a writer request at any scope is stored internally and never exported', () => {
  for (const scope of ['activity', 'session', 'journey']) {
    let j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' }));
    const before = JSON.stringify(j.sessions.map(s => s.activities.map(x => [x.learner, x.teacher])));
    j = accept(j, { scope, kind: 'text', text: 'Replace the example with dolphins', ...first(j) }, 1);
    assert.equal(JSON.stringify(j.sessions.map(s => s.activities.map(x => [x.learner, x.teacher]))), before, `${scope}: learner and teacher text untouched`);
    assert.ok(J.internalNotes(j).some(n => n.includes('dolphins')), `${scope}: request kept as an internal note`);
    const out = JSON.stringify(J.buildPackage({ ver: 1, at: '2026-09-27T00:00:00Z', journey: j }));
    assert.ok(!out.includes('dolphins'), `${scope}: request absent from export`);
    assert.ok(!out.includes(J.WRITER), `${scope}: no writer-request wording in export`);
    assert.deepEqual(J.audit(j), []);
  }
});
test('1: export is checked after several edits, not only after generation', () => {
  let j = J.makeJourney(threeMixed('shared')), rev = 1;
  for (const req of [{ scope: 'journey', kind: 'shorter' }, { scope: 'session', kind: 'text', text: 'Use a bakery as the example' }, { scope: 'activity', kind: 'hands' }, { scope: 'journey', kind: 'found' }, { scope: 'activity', kind: 'text', text: 'Swap this for a quiz' }]) j = accept(j, { ...req, ...first(j) }, rev++);
  const out = JSON.stringify(J.buildPackage({ ver: 2, at: '2026-09-27T00:00:00Z', journey: j }));
  for (const word of ['bakery', 'quiz', J.WRITER, 'No sources were checked']) assert.ok(!out.includes(word), `“${word}” absent`);
});
test('1: the export refuses to run if an internal note is sitting in released text', () => {
  const j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' }));
  j.sessions[0].internal.push('PRIVATE-REVIEW-COMMENT'); j.sessions[0].teacher.setup += ' PRIVATE-REVIEW-COMMENT';
  assert.throws(() => J.buildPackage({ ver: 1, at: 'x', journey: j }), /internal note/);
});
test('1: a writer request left in a teacher note by an older build is moved out on loading', () => {
  const j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' }));
  j.sessions[0].activities[0].teacher += ' Request for the writer: “Replace the example with dolphins”.';
  const s = Store.migrate({ ...Store.fresh(), journey: j }), x = s.journey.sessions[0].activities[0];
  assert.ok(!x.teacher.includes('dolphins')); assert.ok(x.internal.some(n => n.includes('dolphins')));
});

/* ---- 2. stale previews ---- */
test('2: a preview made before an Undo cannot bring the undone change back', () => {
  const j0 = J.makeJourney(brief({ ...base, format: 'workshop', time: 'day' })); j0.rev = 1;
  const j1 = accept(j0, { scope: 'journey', kind: 'found', ...first(j0) }, 2);          // accepted change A
  assert.equal(j1.sessions.length, j0.sessions.length + 1);
  const pB = J.previewChange(j1, { scope: 'session', kind: 'shorter', ...first(j0) });   // preview B on top of A
  const undone = j0;                                                                      // Undo A
  const r = J.applyPreview(undone, pB, 3);
  assert.equal(r.ok, false); assert.equal(r.reason, 'stale');
  const rebuilt = J.previewChange(undone, pB.req), r2 = J.applyPreview(undone, rebuilt, 3);
  assert.ok(r2.ok); assert.equal(r2.journey.sessions.length, j0.sessions.length, 'the undone session did not return');
  assert.ok(!r2.journey.sessions.some(s => s.title === 'Foundations first'));
});
test('2: a preview aimed at something that no longer exists changes nothing', () => {
  const j0 = J.makeJourney(brief({ ...base, format: 'workshop', time: 'day' })); j0.rev = 1;
  const j1 = accept(j0, { scope: 'journey', kind: 'found', ...first(j0) }, 2);
  const p = J.previewChange(j0, { scope: 'session', kind: 'shorter', sessionId: j1.sessions[0].id, activityId: 'a1' });
  assert.equal(p.noop, true); assert.equal(p.gone, true); assert.equal(J.applyPreview(j0, p, 3).ok, false);
});
test('2: previewing never alters the draft it was made from', () => {
  const j = J.makeJourney(threeMixed('linked')), copy = JSON.stringify(j);
  for (const scope of ['activity', 'session', 'journey']) for (const kind of ['shorter', 'hands', 'found', 'text']) J.previewChange(j, { scope, kind, text: 'anything', ...first(j) });
  assert.equal(JSON.stringify(j), copy);
});

/* ---- 3. saved data ---- */
test('3: unreadable saved data is reported as damaged, never treated as empty', () => {
  assert.equal(Store.inspect(null).status, 'empty');
  assert.equal(Store.inspect('').status, 'empty');
  for (const raw of ['{not json', '42', '"text"', '[]', 'null', '{}', '{"v":2,"answers":{}}', '{"v":1}']) assert.equal(Store.inspect(raw).status, 'damaged', raw);
});
test('3: incomplete nested records fail the check even with the right version number', () => {
  const good = { ...Store.fresh(), answers: brief({ ...base, format: 'workshop', time: 'half' }) }; good.journey = J.makeJourney(good.answers);
  good.life.snapshots.push({ ver: 1, at: '2026-09-27T00:00:00Z', journey: JSON.parse(JSON.stringify(good.journey)), brief: good.answers }); good.life.stage = 'approved';
  assert.equal(Store.inspect(JSON.stringify(good)).status, 'ok');
  const breakIt = f => { const c = JSON.parse(JSON.stringify(good)); f(c); return Store.inspect(JSON.stringify(c)); };
  const cases = { 'answer without a value': c => { c.answers.format = {}; }, 'answers not an object': c => { c.answers = []; }, 'session without steps': c => { c.journey.sessions[0].activities = []; }, 'step without minutes': c => { delete c.journey.sessions[0].activities[0].minutes; },
    'step minutes as text': c => { c.journey.sessions[0].activities[0].minutes = '10'; }, 'journey without sessions': c => { delete c.journey.sessions; }, 'lifecycle missing': c => { delete c.life; }, 'unknown stage': c => { c.life.stage = 'live'; },
    'snapshot without a journey': c => { delete c.life.snapshots[0].journey; }, 'snapshot session damaged': c => { c.life.snapshots[0].journey.sessions[0] = null; }, 'undo entry damaged': c => { c.undo = [{ label: 'x' }]; }, 'version not a number': c => { c.life.ver = 'one'; } };
  for (const k in cases) { const r = breakIt(cases[k]); assert.equal(r.status, 'damaged', k); assert.ok(r.reasons.length > 0, k); }
});
test('3: work saved by the earlier build still opens, and approved snapshots are not rewritten', () => {
  const j = J.makeJourney(brief({ ...base, format: 'talk', delivery: 'room', time: 't45' }));
  const old = JSON.parse(JSON.stringify(j)); delete old.rev; delete old.requested; delete old.internal; delete old.mode; old.connections = [{ a: 'X', b: 'Y', type: 'Needs first', why: 'w' }];
  for (const s of old.sessions) { delete s.teacher.requirements; s.teacher.access = ['Large print and strong contrast']; for (const x of s.activities) delete x.internal; }
  const saved = { v: 1, answers: brief({ ...base, format: 'talk', delivery: 'blended', time: 't45' }), at: 'journey', journey: old, undo: [], log: [], pending: { after: old, lines: [] }, life: { stage: 'approved', ver: 1, snapshots: [{ ver: 1, at: '2026-09-27T00:00:00Z', journey: JSON.parse(JSON.stringify(old)), brief: {} }], exports: [], publications: [] } };
  const snapBefore = JSON.stringify(saved.life.snapshots), r = Store.inspect(JSON.stringify(saved));
  assert.equal(r.status, 'ok');
  assert.equal(JSON.stringify(r.state.life.snapshots), snapBefore, 'snapshot untouched');
  assert.equal(r.state.pending, null, 'an untrusted old preview is dropped');
  assert.equal(r.state.answers.delivery.value, 'hybrid');
  assert.ok(Number.isInteger(r.state.journey.rev)); assert.equal(r.state.journey.requested.minutes, 45);
  assert.match(r.state.journey.sessions[0].teacher.requirements[0], /^Requirement to implement: large print/);
  assert.doesNotThrow(() => J.buildPackage(r.state.life.snapshots[0]));
});
test('3: test storage never shares a key with the owner’s real work', () => {
  assert.equal(Store.keyFor('').key, 'glitch-loom/v1'); assert.equal(Store.keyFor('?motion=reduce').key, 'glitch-loom/v1');
  assert.equal(Store.keyFor('?store=audit-1').key, 'glitch-loom/v1#audit-1'); assert.notEqual(Store.keyFor('?store=a').key, Store.keyFor('?store=b').key);
  for (const q of ['?store=', '?store=%20', '?store=a.b', '?store=a%20b', '?store=' + 'x'.repeat(80), '?motion=reduce&store=']) assert.notEqual(Store.keyFor(q).key, 'glitch-loom/v1', q);
  assert.notEqual(Store.keyFor('?store=a.b').key, Store.keyFor('?store=a').key); assert.notEqual(Store.keyFor('?store=' + 'x'.repeat(80)).key, Store.keyFor('?store=' + 'x'.repeat(40)).key);
});

/* ---- 4. durations ---- */
test('4: the audited duration inputs are rejected or read in full', () => {
  for (const t of ['-2 hours', '1-2 hours', '2 weeks 3 days', '90', 'Infinity hours', '0 minutes', '2 hours 2 hours', '1e3 hours', 'about an hour', '4 minutes', '0.5 weeks', '']) assert.ok(F.parseDuration(t).error, `"${t}" is refused with a reason`);
  assert.deepEqual(F.parseDuration('1 hour 15 minutes'), { minutes: 75 }); assert.deepEqual(F.parseDuration('2 days 3 hours'), { minutes: 900 }); assert.deepEqual(F.parseDuration('12 weeks'), { weeks: 12 });
  for (const t of ['0.001', 'Infinity', '-2', '1-2', '41', '0.2', '3 days', 'NaN', '']) assert.ok(F.parseHours(t).error, `weekly "${t}" is refused`);
  assert.deepEqual(F.parseHours('2 hours 30 minutes'), { minutes: 150 }); assert.deepEqual(F.parseHours('2.5'), { minutes: 150 }); assert.deepEqual(F.parseHours('90 minutes'), { minutes: 90 });
});
test('4: whatever passes validation can be generated, with the time the screen says it read', () => {
  const t = text => ({ value: C, text });
  for (const h of ['2 hours 30 minutes', '2.5', '0.25', '40', '1.1', '90 minutes']) {
    const a = brief({ ...base, format: 'course', time: 'w4', hours: t(h) });
    assert.equal(F.problem(F.byId('hours'), a), ''); const j = J.makeJourney(a), per = F.parseHours(h).minutes;
    assert.equal(total(j), 4 * per); assert.ok(j.sessions.every(s => s.minutes === per)); assert.equal(F.reads(F.byId('hours'), a), F.fmtMin(per) + ' each week');
  }
  for (const h of ['0.001', 'Infinity', '-2', '1-2']) { const a = brief({ ...base, format: 'course', time: 'w4', hours: t(h) }); assert.notEqual(F.problem(F.byId('hours'), a), ''); assert.throws(() => J.makeJourney(a)); }
  const w = brief({ ...base, format: 'workshop', time: t('1 hour 15 minutes') }); assert.equal(F.reads(F.byId('time'), w), '1 h 15 min'); assert.equal(total(J.makeJourney(w)), 75);
  assert.match(F.labelOf(F.byId('time'), w), /read as 1 h 15 min/);
});

/* ---- 5. timing after edits ---- */
test('5: the brief’s request and the current plan are kept apart after edits', () => {
  let j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' }));
  assert.equal(J.planOf(j).differs, false);
  j = accept(j, { scope: 'journey', kind: 'shorter', ...first(j) }, 1);
  const p = J.planOf(j); assert.ok(p.minutes < 180); assert.equal(p.requested.minutes, 180); assert.equal(j.budget, 180); assert.equal(p.differs, true);
  const c = J.buildPackage({ ver: 1, at: 'x', journey: j }).course;
  assert.equal(c.planned.minutes, p.minutes); assert.equal(c.requestedInBrief.minutes, 180); assert.equal(c.plannedDiffersFromBrief, true);
  assert.ok(!('duration' in c), 'no single duration field that could go stale');
  assert.equal(c.planned.minutes, J.buildPackage({ ver: 1, at: 'x', journey: j }).learnerMaterials.reduce((s, x) => s + x.minutes, 0));
});
test('5: adding a foundation week is shown as one more week than the brief gives', () => {
  let j = J.makeJourney(brief({ ...base, format: 'course', time: 'w4', hours: '2' }));
  const p = J.previewChange(j, { scope: 'journey', kind: 'found', ...first(j) });
  assert.ok(p.effects.some(e => /Weeks planned: 4 becomes 5/.test(e))); assert.ok(p.effects.some(e => /brief itself is not changed/.test(e)));
  j = J.applyPreview(j, p, 1).journey; const pl = J.planOf(j);
  assert.equal(pl.sessions, 5); assert.equal(pl.requested.sessions, 4); assert.ok(pl.notes.some(n => /5 weeks planned, the brief gives 4/.test(n)));
});
test('5: “Shorter” never makes anything longer, at any scope, on any plan', () => {
  assert.ok([1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 15, 22, 45, 120, 240].every(m => J.shorter(m, .7) <= m && J.shorter(m, .75) <= m && J.shorter(m, .7) > 0));
  for (const time of ['5 minutes', '7 minutes', '10 minutes', '13 minutes', '20 minutes', '45 minutes', '3 hours']) for (const prior of ['some', 'unsure']) for (const scope of ['activity', 'session', 'journey']) {
    let j = J.makeJourney(brief({ ...base, format: 'talk', prior, time: { value: C, text: time } }));
    for (let i = 0; i < 4; i++) { const p = J.previewChange(j, { scope, kind: 'shorter', ...first(j) }); assert.ok(total(p.after) <= total(j), `${time} ${scope}`); if (p.noop) { assert.equal(total(p.after), total(j)); break; } j = J.applyPreview(j, p, i + 1).journey; assert.deepEqual(J.audit(j), []); }
  }
});

/* ---- 6 and 7. topics ---- */
test('6: a shared project with three topics names all three, and its connection points at that task', () => {
  const j = J.makeJourney(threeMixed('shared')), s = j.sessions.find(x => x.key === 'connect');
  assert.ok(s, 'the joining task exists'); for (const t of ['Typography', 'SQL', 'Negotiation']) assert.ok((s.title + s.aim).includes(t), `${t} named in the joining task`);
  const c = j.connections.filter(x => x.type === 'Used together'); assert.equal(c.length, 1); assert.deepEqual(c[0].names, ['Typography', 'SQL', 'Negotiation']); assert.equal(c[0].session, s.id);
  assert.match(c[0].why, /simulated/i); assert.match(c[0].why, /Nobody has checked/);
  assert.ok(!j.connections.some(x => x.names.length === 2 && x.names.includes('SQL') && x.names.includes('Negotiation')), 'no separate SQL–Negotiation claim');
});
test('6: a topic tag always comes with text that names the topic', () => {
  for (const mode of ['shared', 'linked', 'separate']) for (const time of ['w2', 'w4', 'w8']) for (const mix of [['A-topic', 'B-topic'], ['Typography', 'SQL', 'Negotiation']]) {
    const a = brief({ ...base, format: 'course', entry: 'mix', mix, mode, time, hours: '2' }); if (J.conflicts(a).length) continue;
    const j = J.makeJourney(a); assert.deepEqual(J.audit(j), [], `${mode} ${time} ${mix.length}`);
    for (const s of j.sessions) for (const t of s.threads) assert.ok([s.title, s.aim, ...s.activities.map(x => x.learner)].join(' ').includes(mix[t]));
  }
});
test('6: the audit catches a tag without text and a connection that names an absent topic', () => {
  const j = J.makeJourney(threeMixed('linked')), solo = j.sessions.find(s => s.threads.length === 1); solo.threads.push((solo.threads[0] + 1) % 3);
  assert.ok(J.audit(j).some(p => /tagged/.test(p)));
  const k = J.makeJourney(threeMixed('shared')); k.connections[0].names.push('Astronomy'); assert.ok(J.audit(k).some(p => /never mentions/.test(p)));
});
test('7: with “Keep them separate”, a whole-journey foundation edit never combines subjects', () => {
  let j = J.makeJourney(brief({ ...base, format: 'cohort', entry: 'mix', mix: ['Ceramics', 'SQL', 'Negotiation'], mode: 'separate', time: 'w8', hours: '2' }));
  const n = j.sessions.length, p = J.previewChange(j, { scope: 'journey', kind: 'found', ...first(j) });
  assert.ok(p.effects.some(e => /keeps the topics separate/.test(e))); j = J.applyPreview(j, p, 1).journey;
  assert.equal(j.sessions.length, n, 'no combined session added'); assert.equal(j.mode, 'separate'); assert.ok(j.sessions.every(s => s.threads.length === 1)); assert.deepEqual(J.audit(j), []);
  for (const t of [0, 1, 2]) assert.ok(j.sessions.some(s => s.threads[0] === t && s.activities[0].kind === 'Bridge' && s.activities[0].learner.includes(j.topics[t])), `${j.topics[t]} has its own recap`);
});
test('invariants hold after every kind of edit at every scope', () => {
  const briefs = [threeMixed('shared'), threeMixed('linked'), brief({ ...base, format: 'cohort', entry: 'mix', mix: ['Ceramics', 'SQL', 'Negotiation'], mode: 'separate', time: 'w4', hours: '2' }), brief({ ...base, format: 'talk', prior: 'unsure', time: { value: C, text: '10 minutes' } }), brief({ ...base, format: 'workshop', entry: 'worlds', pick: 'dune', worldSubject: 'Ecology and scarcity', time: 'day', limits: ['phones', 'free'] })];
  let n = 0;
  for (const a of briefs) for (const scope of ['activity', 'session', 'journey']) for (const kind of ['shorter', 'hands', 'found', 'text']) {
    let j = J.makeJourney(a); const topics = j.topics.slice(), budget = j.budget, snap = JSON.stringify(j);
    for (let i = 0; i < 3; i++) { const p = J.previewChange(j, { scope, kind, text: 'Secret request about llamas', ...first(j) }); if (p.noop) break; j = J.applyPreview(j, p, i + 1).journey; n++;
      assert.deepEqual(J.audit(j), []); assert.deepEqual(j.topics, topics); assert.equal(j.budget, budget); assert.equal(j.requested.minutes, budget);
      const out = JSON.stringify(J.buildPackage({ ver: 1, at: 'x', journey: j })); assert.ok(!out.includes('llamas')); assert.equal(J.buildPackage({ ver: 1, at: 'x', journey: j }).course.planned.minutes, total(j)); }
    const bare = x => x.replace(/"madeAt":"[^"]*"/, '').replace(/"uid":"[^"]*"/, '');
    assert.equal(bare(JSON.stringify(J.makeJourney(a))), bare(snap), 'generation is repeatable and the first draft was not mutated');
  }
  assert.ok(n > 60, `applied ${n} edits`);
});

/* ---- 8, 9, 10 ---- */
test('8: “room and online together” is not treated as solo preparation', () => {
  const a = brief({ ...base, format: 'talk', delivery: 'hybrid', time: 't45' }), j = J.makeJourney(a), txt = JSON.stringify(j.sessions);
  assert.ok(F.byId('delivery').options(a).some(o => o.v === 'hybrid')); assert.ok(!F.byId('delivery').options(a).some(o => o.v === 'blended'));
  assert.ok(!/alone beforehand|solo task/i.test(txt)); assert.match(j.sessions[0].teacher.setup, /online learners/); assert.match(j.sessions[0].teacher.setup, /room/);
  const b = J.makeJourney(brief({ ...base, format: 'course', delivery: 'blended', time: 'w2', hours: '2' })); assert.match(JSON.stringify(b.sessions), /alone beforehand/);
});
test('9: contradictory device choices are refused, compatible ones are kept', () => {
  const q = F.byId('limits'), p = v => F.problem(q, brief({ limits: v }));
  assert.match(p(['nodevice', 'phones', 'laptops']), /cannot all be true/); assert.match(p(['phones', 'laptops']), /cannot all be true/); assert.match(p(['none', 'free']), /Nothing special/);
  for (const ok of [['phones', 'lowweb', 'free'], ['nodevice', 'language'], ['laptops', 'access', 'free', 'lowweb'], ['none']]) assert.equal(p(ok), '', ok.join('+'));
});
test('10: suggestions state an assumption and promise no checks; stored needs are labelled as still to implement', () => {
  for (const f of ['talk', 'clinic', 'workshop', 'course']) for (const au of ['school', 'college', 'pro', 'mixed']) for (const pr of ['new', 'some', 'solid', 'unsure']) for (const id of ['delivery', 'time', 'hours', 'mode', 'worldSubject']) {
    const a = brief({ format: f, audience: au, prior: pr, entry: id === 'worldSubject' ? 'worlds' : 'mix', pick: 'dune', mix: ['A', 'B'] }), r = F.recommend(F.byId(id), a); if (!r) continue;
    assert.match(r.why, /Assumes|simply/, r.why); assert.ok(!/rarely|always|best|will check|will verify|get more from/i.test(r.why), r.why);
  }
  const j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half', limits: ['phones', 'language', 'access'], language: 'Hindi', access: ['vision', 'reader'] })), s = j.sessions[0];
  assert.equal(s.teacher.requirements.length, 4); assert.ok(s.teacher.requirements.every(r => r.startsWith('Requirement to implement: ')));
  assert.ok(!/Works on a phone|Materials in Hindi|Text works with a screen reader/.test(JSON.stringify(j)), 'no claim that the need is already met');
  assert.deepEqual(J.buildPackage({ ver: 1, at: 'x', journey: j }).teacherMaterials[0].requirementsToImplement.length, 4);
});

/* ---- found by independent review ---- */
const goodState = () => { const s = { ...Store.fresh(), answers: brief({ ...base, format: 'workshop', time: 'half' }) }; s.journey = J.makeJourney(s.answers); s.journey.rev = 1; s.revSeq = 1; s.jDigest = F.briefDigest(s.answers); s.jBrief = JSON.parse(JSON.stringify(s.answers)); return s; };
const load = s => Store.inspect(JSON.stringify(s));
test('review: saved states that would crash or mislead the app are refused', () => {
  assert.equal(load(goodState()).status, 'ok');
  const cases = { 'log is null entries': s => { s.log = [null]; }, 'log is a string': s => { s.log = 'x'; }, 'list answer stored as text': s => { s.answers.limits = { value: 'phones' }; }, 'text answer stored as a list': s => { s.answers.audience = { value: ['school'] }; },
    'steps do not add up': s => { s.journey.sessions[0].activities[0].minutes += 5; }, 'fractional minutes': s => { s.journey.sessions[0].minutes = 60.5; }, 'absurd minutes': s => { s.journey.sessions[0].minutes = 1e308; s.journey.sessions[0].activities = [{ ...s.journey.sessions[0].activities[0], minutes: 1e308 }]; },
    'negative minutes': s => { s.journey.sessions[0].activities[0].minutes = -5; }, 'duplicate session ids': s => { s.journey.sessions[1].id = s.journey.sessions[0].id; }, 'topic tag out of range': s => { s.journey.sessions[0].threads = [99, -1]; },
    'snapshot date unreadable': s => { s.life = { stage: 'approved', ver: 1, snapshots: [{ ver: 1, at: 'soon', journey: s.journey, brief: s.answers }], exports: [], publications: [] }; },
    'unapproved version that already has a snapshot': s => { s.life = { stage: 'review', ver: 1, snapshots: [{ ver: 1, at: '2026-01-01T00:00:00Z', journey: s.journey, brief: s.answers }], exports: [], publications: [] }; },
    'duplicate snapshot versions': s => { const p = { ver: 1, at: '2026-01-01T00:00:00Z', journey: s.journey, brief: s.answers }; s.life = { stage: 'approved', ver: 1, snapshots: [p, p], exports: [], publications: [] }; },
    'approved without a snapshot': s => { s.life.stage = 'approved'; }, 'teacher setup missing': s => { delete s.journey.sessions[0].teacher.setup; }, 'internal notes not text': s => { s.journey.sessions[0].internal = [{ a: 1 }]; } };
  for (const k in cases) { const s = goodState(); cases[k](s); assert.equal(load(s).status, 'damaged', k); }
});
test('review: a damaged request record is rebuilt, and a saved preview is always made again from the current draft', () => {
  const s = goodState(); s.journey.requested = {}; const r = load(s); assert.equal(r.status, 'ok'); assert.equal(r.state.journey.requested.minutes, 180); assert.doesNotThrow(() => J.planOf(r.state.journey));
  const t = goodState(), unrelated = J.makeJourney(brief({ ...base, topic: 'PLANTED', format: 'workshop', time: 'day' })); t.pending = { baseRev: 1, req: { scope: 'journey', kind: 'shorter' }, after: unrelated, lines: [], effects: [], label: 'x', target: 'y' };
  const u = load(t); assert.equal(u.status, 'ok'); assert.ok(!JSON.stringify(u.state.pending.after).includes('PLANTED'), 'planted preview content is discarded'); assert.deepEqual(u.state.pending.after.topics, ['ceramics']); assert.equal(u.state.pending.baseRev, u.state.journey.rev);
  const v = goodState(); v.pending = { baseRev: 1, req: {}, after: unrelated }; assert.equal(load(v).state.pending, null);
});
test('review: renaming “both at once” does not make a matching journey look out of date', () => {
  const s = { ...Store.fresh(), answers: brief({ ...base, format: 'talk', delivery: 'blended', time: 't45' }) }; s.journey = J.makeJourney(brief({ ...base, format: 'talk', delivery: 'hybrid', time: 't45' })); s.jDigest = F.briefDigest(s.answers); s.jBrief = JSON.parse(JSON.stringify(s.answers));
  const r = load(s); assert.equal(r.status, 'ok'); assert.equal(r.state.answers.delivery.value, 'hybrid'); assert.equal(r.state.jBrief.delivery.value, 'hybrid'); assert.equal(r.state.jDigest, F.briefDigest(r.state.answers), 'still matches');
  const again = load(r.state); assert.equal(again.state.jDigest, F.briefDigest(again.state.answers), 'stable across reloads');
  const changed = { ...s, jDigest: 'something else' }; assert.notEqual(load(changed).state.jDigest, F.briefDigest(load(changed).state.answers), 'a journey that was already out of date stays out of date');
});

test('review: a fourth topic, a blank topic or a repeated topic is refused, never trimmed away', () => {
  const q = F.byId('mix'), p = l => F.problem(q, brief({ entry: 'mix', mix: l }));
  assert.match(p(['one', 'two', 'three', 'four']), /at most 3/); assert.match(p(['one', '   ']), /blank/); assert.match(p(['SQL', 'sql']), /same name/); assert.equal(p(['one', 'two', 'three']), '');
  assert.deepEqual(F.topicsOf(brief({ entry: 'mix', mix: ['one', 'two', 'three', 'four'] })).list.length, 4, 'nothing is cut before validation sees it');
});
test('review: a fiction world is only said to be used where a session really uses it', () => {
  const short = J.makeJourney(brief({ ...base, format: 'talk', entry: 'worlds', pick: 'dune', worldSubject: 'Probability', time: 't20' })), c = short.connections.find(x => x.type === 'Inspiration only');
  assert.ok(!short.sessions.some(s => s.key === 'sort')); assert.ok(!/are labelled/.test(c.why)); assert.match(c.why, /not used in any session/);
  const long = J.makeJourney(brief({ ...base, format: 'workshop', entry: 'worlds', pick: 'dune', worldSubject: 'Probability', time: 'day' })), d = long.connections.find(x => x.type === 'Inspiration only');
  assert.ok(d.session); assert.ok(JSON.stringify(long.sessions.find(s => s.id === d.session)).includes('Dune')); assert.deepEqual(J.audit(long), []);
  long.sessions.find(s => s.id === d.session).aim = 'Sort some claims.'; assert.ok(J.audit(long).some(p => /never mentions/.test(p)));
});
test('review: a preview cannot be applied to a different draft, or without a new revision number', () => {
  const A = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' })), B = J.makeJourney(brief({ ...base, topic: 'orbits', format: 'talk', time: 't20' }));
  const p = J.previewChange(A, { scope: 'journey', kind: 'shorter', sessionId: A.sessions[0].id });
  assert.equal(J.applyPreview(B, p, 1).ok, false); assert.throws(() => J.applyPreview(A, p, undefined)); assert.throws(() => J.applyPreview(A, p, 0));
  const A1 = J.applyPreview(A, p, 1).journey; assert.equal(J.applyPreview(A1, p, 2).ok, false, 'the same preview cannot be applied twice');
});
test('review: ordinary sentences never block an export, and real requests still never leak', () => {
  let j = J.makeJourney(brief({ ...base, topic: 'Request for the writer', outcome: 'Write a Request for the writer memo', format: 'workshop', time: 'half', limits: { value: [C], text: 'Simulated draft. No sources were checked and no claim is verified.' } }));
  assert.doesNotThrow(() => J.buildPackage({ ver: 1, at: 'x', journey: j }));
  for (const text of ['Swap in “quoted” otters', 'Request for the writer: “nested”', 'use \\ backslashes and "straight quotes" with otters']) { j = J.applyPreview(j, J.previewChange(j, { scope: 'activity', kind: 'text', text, ...first(j) }), j.rev + 1).journey; assert.ok(!JSON.stringify(J.buildPackage({ ver: 1, at: 'x', journey: j })).includes('otters')); }
  assert.ok(J.internalNotes(j).filter(n => /otters|nested/.test(n)).length === 3);
});
test('review: a request that says “do not” is kept as a note, not guessed at', () => {
  for (const t of ['Do not cut anything', 'Please do not make it shorter', 'No games please', 'never shorten this', 'without the recap']) assert.equal(J.readRequest(t), 'note', t);
  assert.equal(J.readRequest('explain gamete biology'), 'note'); assert.equal(J.readRequest('make it shorter'), 'shorter'); assert.equal(J.readRequest('more hands-on please'), 'hands'); assert.equal(J.readRequest('add a recap of the basics'), 'found');
});
test('review: near-misses in numbers are refused instead of rounded', () => {
  for (const t of ['14.9999999 minutes', '1.999999999 hours', '1.0000001 weeks', '2 hours 90 minutes', '1.5.2 hours', '+2 hours', '0x10 hours', '١٢ weeks', '1e2 minutes']) assert.ok(F.parseDuration(t).error, t);
  for (const t of ['1.999999999', '2.123', '+2', '0x10']) assert.ok(F.parseHours(t).error, t);
  assert.deepEqual(F.parseDuration('1.25 hours'), { minutes: 75 }); assert.deepEqual(F.parseDuration('3 hours 30 minutes'), { minutes: 210 }); assert.deepEqual(F.parseHours('2.25'), { minutes: 135 });
});
test('review: asking for a foundation step twice does not stack copies', () => {
  for (const scope of ['activity', 'session', 'journey']) for (const a of [brief({ ...base, format: 'workshop', time: 'half' }), brief({ ...base, format: 'cohort', entry: 'mix', mix: ['A1', 'B2'], mode: 'separate', time: 'w4', hours: '2' })]) {
    let j = J.makeJourney(a); j = J.applyPreview(j, J.previewChange(j, { scope, kind: 'found', ...first(j) }), 1).journey; const n = JSON.stringify(j.sessions);
    const again = J.previewChange(j, { scope, kind: 'found', sessionId: j.sessions[scope === 'journey' && j.mode !== 'separate' ? 1 : 0].id, activityId: j.sessions[0].activities[scope === 'activity' ? 1 : 0].id });
    if (scope === 'journey' || scope === 'session' && j.sessions[0].activities[0].kind === 'Bridge') { const p = J.previewChange(j, { scope, kind: 'found', ...first(j) }); assert.equal(p.noop, true, scope); assert.match(p.effects[0], /already here/); }
    assert.equal(JSON.stringify(j.sessions), n);
  }
});

test('3: a misspelt storage name still keeps away from the owner\'s work', async () => {
  const { keyFor, storeParam, BASE_KEY } = await import('../js/store.js');
  for (const q of ['?Store=x', '?STORE=x', '?store[]=x', '?store%20=x', '?teststore=', '?a=1&Store=']) assert.notEqual(keyFor(q).key, BASE_KEY, q);
  assert.equal(storeParam('?store=A%20'), 'a');
  assert.equal(storeParam('?store=&Store=x'), 'unnamed');
  assert.equal(storeParam('?motion=reduce'), null);
  assert.equal(keyFor('?motion=reduce').key, BASE_KEY);
});

test('3: opening saved work does not change it', async () => {
  const { migrate, fresh } = await import('../js/store.js');
  const a = { format: { value: 'workshop' }, entry: { value: 'topic' }, topic: { value: 'Bread' }, audience: { value: 'college' }, prior: { value: 'new' }, outcome: { value: 'Bake a loaf' }, delivery: { value: 'room' }, time: { value: 'half' }, limits: { value: [] } };
  const j = J.makeJourney(a); j.rev = 4;
  const s = Object.assign(fresh(), { answers: a, at: 'journey', journey: j, jDigest: F.briefDigest(a), jBrief: a, revSeq: 4, undo: [{ journey: Object.assign(J.makeJourney(a), { rev: 3 }), label: 'x', target: 'y' }] });
  const once = migrate(JSON.parse(JSON.stringify(s))), twice = migrate(JSON.parse(JSON.stringify(once)));
  assert.equal(once.revSeq, 4);
  assert.equal(JSON.stringify(twice), JSON.stringify(once));
  const old = JSON.parse(JSON.stringify(s)); delete old.journey.rev; delete old.revSeq;
  assert.ok(migrate(old).journey.rev >= 1, 'a draft saved without a number still gets one');
});

// A contested claim must not read as a settled one anywhere a person looks: not in the JSON a team keeps, and
// not in the teacher pack. Two runs of the attribution review answering the same question differently on the
// same evidence is a fact about the evidence, and leaving it out of the export hides exactly the thing a
// reader would want before relying on the claim.
const contested = (j) => {
  j.origin = 'claude'; j.pipeline = 2;
  j.research = {
    lineage: {
      works: {
        'w:a': { id: 'w:a', title: 'A first report', creators: ['Ada Ito'], published: '1998', role: 'original_contribution', originStatus: 'established', seenAt: ['https://e.org/a'] },
        'w:b': { id: 'w:b', title: 'A later work', creators: ['Bo Okafor'], published: '2005', role: 'primary_extension', originStatus: 'unknown', originWhy: ['x'], seenAt: ['https://e.org/b'] },
      },
      edges: [{ from: 'w:b', to: 'w:a', earlierWorkAsNamed: 'A first report', relation: 'replicated', whatChanged: 'repeated it', supportingWords: 'we repeated the earlier study', status: 'unresolved', why: ['two runs of the attribution review disagree about this relationship'], unresolvedDisagreements: [{ aspect: 'relationship', key: 'relationship|a first report|replicated', earlier: 'no', later: 'yes', sameEvidence: true, sameWholeRequest: true }] }],
      summary: { works: 2, originalsEstablished: 1, descentEdges: 1, supportedEdges: 0, unresolvedEdges: 1, unknownEdges: 0, disputedEdges: 0 },
    },
    lineageChains: [{ original: { work: 'w:a', title: 'A first report' }, supportedExtensions: [], awaitingAPersonsDecision: [{ work: 'w:b', title: 'A later work', relation: 'replicated', status: 'unresolved' }], claimedButNotEstablished: [{ work: 'w:b', title: 'A later work', relation: 'replicated', status: 'unresolved' }] }],
  };
  j.sources = [{ id: 'S1', title: 'A later work', url: 'https://e.org/b', claim: 'c', finding: 'f', quote: 'we repeated the earlier study', role: 'primary_extension', authors: ['Bo Okafor'], published: '2005', attribution: { verdict: 'yes', unresolvedDisagreements: [{ aspect: 'identity', key: 'identity', earlier: 'no', later: 'yes', sameEvidence: true, sameWholeRequest: true }] } }];
  return j;
};

test('1: a claim the review contradicts itself about is not exported as supported', () => {
  const j = contested(J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' })));
  const pkg = J.buildPackage({ ver: 1, at: '2026-09-27T00:00:00Z', journey: j });
  const L = pkg.evidence.worksAndHowTheyDescend;
  assert.equal(L.descent[0].standing, 'unresolved', 'the standing travels into the export');
  assert.equal(L.counts.supportedEdges, 0);
  assert.equal(L.counts.unresolvedEdges, 1);
  assert.deepEqual(L.originalsAndTheirExtensions[0].supportedExtensions, [], 'and it is not a supported extension');
  assert.equal(L.originalsAndTheirExtensions[0].awaitingAPersonsDecision.length, 1);
  assert.ok(L.readThisFirst.includes('until a person decides'), 'the reader is told what the standing means');
});

test('1: the JSON export says the attribution review contradicted itself about a source', () => {
  const j = contested(J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' })));
  const pkg = J.buildPackage({ ver: 1, at: '2026-09-27T00:00:00Z', journey: j });
  const s = pkg.evidence.sources.find(x => x.id === 'S1');
  assert.ok(s.attributionReviewDisagreesWithItself, 'a verdict of yes alone would read as settled');
  assert.equal(s.attributionReviewDisagreesWithItself[0].about, 'identity');
  assert.equal(s.attributionReviewDisagreesWithItself[0].earlierAnswer, 'no');
  assert.equal(s.nothingRestingOnThisIsSettled, true);
});

test('1: the teacher pack puts what is waiting on a person in front of the teacher', () => {
  const j = contested(J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' })));
  const pkg = J.buildPackage({ ver: 1, at: '2026-09-27T00:00:00Z', journey: j });
  const html = J.packHTML(pkg, 'teacher');
  assert.ok(html.includes('Waiting on a person'), 'a teacher should not have to read a table to find it');
  assert.ok(html.includes('unresolved'), 'and the standing is shown in the relationships table too');
  const learner = J.packHTML(pkg, 'learner');
  assert.ok(!learner.includes('Waiting on a person'), 'the learner pack still carries no internal review detail');
});

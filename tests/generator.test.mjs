// Regression checks for the simulated journey builder. Run: node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import * as J from '../js/journey.js';
import * as F from '../js/flow.js';

const C = F.CUSTOM;
const brief = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
const base = { entry: 'have', topic: 'ceramics', audience: 'college', prior: 'some', outcome: 'Make a bowl', delivery: 'room', limits: ['none'] };
const total = j => j.sessions.reduce((s, x) => s + x.minutes, 0);
const exact = (j, want) => {
  assert.equal(total(j), want, 'sessions add up to the requested time');
  assert.equal(j.budget, want, 'budget is the requested time, not rewritten');
  for (const s of j.sessions) { assert.equal(s.activities.reduce((n, x) => n + x.minutes, 0), s.minutes, `steps add up inside "${s.title}"`); for (const x of s.activities) assert.ok(x.minutes > 0, 'no empty step'); }
};
const covers = j => j.topics.forEach((t, i) => assert.ok(j.sessions.some(s => s.threads.includes(i)), `topic "${t}" appears in a session`));

test('bug 1: three separate topics in 4 weeks x 2 h keep all three topics', () => {
  const j = J.makeJourney(brief({ ...base, format: 'cohort', entry: 'mix', mix: ['Ceramics', 'SQL', 'Negotiation'], mode: 'separate', prior: 'unsure', time: 'w4', hours: '2' }));
  covers(j); exact(j, 480); assert.equal(j.sessions.length, 4);
  assert.ok(j.sessions.some(s => s.title.startsWith('Negotiation')));
});
test('bug 2: 75 minute workshop with an entry check totals 75, budget stays 75', () => {
  const j = J.makeJourney(brief({ ...base, format: 'workshop', prior: 'unsure', time: { value: C, text: '75 minutes' } }));
  exact(j, 75); assert.ok(j.sessions[0].activities.some(x => x.kind === 'Entry check'));
});
test('bug 3: 10 minute talk totals 10', () => {
  exact(J.makeJourney(brief({ ...base, format: 'talk', time: { value: C, text: '10 minutes' } })), 10);
});
test('bug 4: 12 weeks x 2 h stays 12 weeks', () => {
  const j = J.makeJourney(brief({ ...base, format: 'course', time: { value: C, text: '12 weeks' }, hours: '2' }));
  assert.equal(j.sessions.length, 12); exact(j, 1440); assert.match(j.span, /12 weeks/);
});
test('more separate topics than sessions is a visible conflict with choices, never a silent drop', () => {
  const a = brief({ ...base, format: 'course', entry: 'mix', mix: ['A', 'B', 'C'], mode: 'separate', time: 'w2', hours: '2' });
  const c = J.conflicts(a); assert.equal(c.length, 1); assert.ok(c[0].choices.length >= 2);
  assert.throws(() => J.makeJourney(a));
});
test('more than 52 weeks is a visible conflict, not a silent cap', () => {
  const a = brief({ ...base, format: 'course', time: { value: C, text: '80 weeks' }, hours: '2' });
  assert.equal(J.conflicts(a)[0].id, 'long'); assert.throws(() => J.makeJourney(a));
});
test('exact totals and topic coverage across many briefs', () => {
  const times = { talk: ['t20', 't45', 't90', '5 minutes', '7 minutes', '10 minutes', '33 minutes', '1 hour 15 minutes'], workshop: ['half', 'day', 'two', '75 minutes', '50 minutes', '3 days', '2.5 hours'], clinic: ['c60', 'c120', 'cweek', '25 minutes'], course: ['w2', 'w4', 'w8', '1 week', '12 weeks', '30 weeks', '52 weeks'], cohort: ['w4', '9 weeks'] };
  const topics = [{ entry: 'have', topic: 'orbits' }, { entry: 'mix', mix: ['Marketing', 'Design'], mode: 'shared' }, { entry: 'mix', mix: ['Marketing', 'Design', 'Development'], mode: 'linked' }, { entry: 'mix', mix: ['Marketing', 'Design', 'Development'], mode: 'shared' }, { entry: 'mix', mix: ['Ceramics', 'SQL', 'Negotiation'], mode: 'separate' }, { entry: 'worlds', pick: 'dune', worldSubject: 'Ecology and scarcity' }];
  let n = 0;
  for (const f in times) for (const t of times[f]) for (const tp of topics) for (const prior of ['new', 'some', 'solid', 'unsure']) for (const hours of f === 'course' || f === 'cohort' ? ['2', { value: C, text: '1.1' }, '6'] : [null]) {
    const a = brief({ ...base, ...tp, format: f, prior, time: /^\d/.test(t) ? { value: C, text: t } : t, ...(hours ? { hours } : {}) });
    const rq = J.request(a); assert.ok(rq.total > 0, `request readable for ${f} ${t}`);
    if (J.conflicts(a).length) { assert.throws(() => J.makeJourney(a)); continue; }
    const j = J.makeJourney(a); exact(j, rq.total); covers(j); assert.equal(j.sessions.length, rq.n); n++;
  }
  assert.ok(n > 300, `ran ${n} briefs`);
});
test('splitExact always adds up', () => {
  for (let total = 1; total <= 400; total++) for (let n = 1; n <= 8; n++) { const p = J.splitExact(total, n); assert.equal(p.reduce((s, x) => s + x, 0), total); assert.equal(p.length, n); if (total >= n) assert.ok(p.every(x => x > 0)); }
});
test('free tools and a custom constraint are stored as requirements to implement', () => {
  const j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half', limits: { value: ['free', C], text: 'Only Tuesday evenings' } }));
  const m = j.sessions[0].teacher.requirements.join(' | '); assert.match(m, /free tools only/); assert.match(m, /Only Tuesday evenings/);
  assert.ok(j.sessions[0].teacher.requirements.every(r => r.startsWith(J.REQ)), 'stored constraints are labelled as requirements, not as done');
});
test('export package separates learner and teacher materials and leaves out internal notes', () => {
  const j = J.makeJourney(brief({ ...base, format: 'workshop', time: 'half' })); j.sessions[0].internal.push('SECRET-INTERNAL-NOTE');
  const p = J.buildPackage({ ver: 3, at: '2026-09-27T00:00:00Z', journey: j }), txt = JSON.stringify(p);
  assert.ok(Array.isArray(p.learnerMaterials) && Array.isArray(p.teacherMaterials)); assert.equal(p.version, 3);
  assert.ok(!txt.includes('SECRET-INTERNAL-NOTE')); assert.ok(!/No sources were checked/.test(txt));
  assert.ok(!JSON.stringify(p.learnerMaterials).includes('Walk around'), 'teacher notes stay out of learner materials');
});
test('a change that alters nothing is reported as such', () => {
  const j = J.makeJourney(brief({ ...base, format: 'talk', time: { value: C, text: '10 minutes' } }));
  const p = J.previewChange(j, { scope: 'session', kind: 'hands', sessionId: j.sessions[0].id, activityId: j.sessions[0].activities[0].id });
  assert.equal(p.noop, true); assert.match(p.effects[0], /change nothing/);
  const q = J.previewChange(j, { scope: 'journey', kind: 'found', sessionId: j.sessions[0].id });
  assert.equal(q.noop, false); assert.equal(q.after.sessions.length, j.sessions.length + 1);
  assert.equal(j.sessions.length, 2, 'the original journey is untouched by a preview');
});

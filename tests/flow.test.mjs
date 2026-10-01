// Regression checks for the question flow. Run: node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import * as F from '../js/flow.js';

const C = F.CUSTOM;
const brief = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));

test('Back/Continue bug: a stored answer that no longer applies never crashes a label', () => {
  // Picked a "Trending" idea, went Back, switched to "I have a topic". The old pick stays stored.
  const a = brief({ format: 'course', entry: 'have', pick: 'money', topic: 'ceramics', worldSubject: 'Probability' });
  for (const q of F.Q) if (a[q.id]) assert.doesNotThrow(() => F.labelOf(q, a), q.id);
  for (const q of F.Q) assert.doesNotThrow(() => { F.problem(q, a); F.reviewNote(q, a); if (q.options) q.options(a); }, q.id);
  assert.equal(F.labelOf(F.byId('pick'), a), 'Everyday money decisions');
  assert.ok(!F.activePath(a).some(q => q.id === 'pick'));
});
test('every question copes with an empty brief and with every entry point', () => {
  for (const entry of [undefined, 'have', 'trending', 'next', 'mix', 'worlds']) for (const format of [undefined, 'course', 'talk', 'workshop', 'clinic', 'cohort', C]) {
    const a = brief({ ...(entry ? { entry } : {}), ...(format ? { format } : {}) });
    for (const q of F.Q) assert.doesNotThrow(() => { F.titleOf(q, a); if (q.options) q.options(a); F.problem(q, a); F.labelOf(q, a); F.reviewNote(q, a); });
    assert.doesNotThrow(() => { F.activePath(a); F.topicsOf(a); F.briefDigest(a); F.digests(a); });
  }
});
test('follow-up questions appear and disappear with the answer that needs them', () => {
  const ids = a => F.activePath(a).map(q => q.id);
  assert.ok(ids(brief({ format: 'course' })).includes('hours'));
  assert.ok(!ids(brief({ format: 'talk' })).includes('hours'));
  assert.ok(ids(brief({ limits: ['language', 'access'] })).includes('language'));
  assert.ok(!ids(brief({ limits: ['none'] })).includes('access'));
  assert.deepEqual(ids(brief({ entry: 'mix' })).filter(i => ['mix', 'mode', 'topic', 'pick'].includes(i)), ['mix', 'mode']);
});
test('durations are read exactly, and unreadable ones are refused', () => {
  assert.deepEqual(F.readDuration('12 weeks'), { weeks: 12 });
  assert.deepEqual(F.readDuration('75 minutes'), { minutes: 75 });
  assert.deepEqual(F.readDuration('1 hour 15 minutes'), { minutes: 75 });
  assert.deepEqual(F.readDuration('2.5 hours'), { minutes: 150 });
  assert.deepEqual(F.readDuration('10 min'), { minutes: 10 });
  assert.equal(F.readDuration('a while'), null);
  assert.equal(F.readDuration('0 minutes'), null);
});
test('a custom length must suit the format, with a message that says how', () => {
  const t = text => ({ value: C, text });
  assert.match(F.problem(F.byId('time'), brief({ format: 'course', time: t('10 hours') })), /weeks/);
  assert.match(F.problem(F.byId('time'), brief({ format: 'talk', time: t('2 weeks') })), /minutes/);
  assert.equal(F.problem(F.byId('time'), brief({ format: 'course', time: t('12 weeks') })), '');
  assert.equal(F.problem(F.byId('time'), brief({ format: 'workshop', time: t('75 minutes') })), '');
  assert.match(F.problem(F.byId('time'), brief({ format: 'talk', time: 'w4' })), /no longer fits/);
});
test('constraints offer free tools and a custom answer', () => {
  const q = F.byId('limits'); assert.ok(q.options({}).some(o => o.v === 'free')); assert.ok(q.custom);
  assert.notEqual(F.problem(q, brief({ limits: { value: [C], text: '' } })), '');
  assert.equal(F.problem(q, brief({ limits: { value: ['free', C], text: 'No Fridays' } })), '');
  assert.equal(F.labelOf(q, brief({ limits: { value: ['free', C], text: 'No Fridays' } })), 'Free tools only, No Fridays');
});
test('a suggestion is flagged for review when what it was based on changes', () => {
  const a = brief({ format: 'course', audience: 'pro' });
  a.delivery = { value: 'live', source: 'recommended', basedOn: F.basis('delivery', a) };
  assert.equal(F.reviewNote(F.byId('delivery'), a), '');
  a.audience = { value: 'school' };
  assert.match(F.reviewNote(F.byId('delivery'), a), /audience/);
});

test('a suggestion is always one of the answers on offer, for every format and shape', () => {
  const mk = o => Object.fromEntries(Object.entries(Object.assign({ entry: 'have', topic: 'Design thinking', audience: 'mixed', prior: 'new', outcome: 'Run one pass', delivery: 'hybrid', group: 'g20' }, o)).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
  const jam = mk({ format: { value: F.CUSTOM, text: 'Design jam' }, shape: 'once' }), time = F.byId('time');
  const r = F.recommend(time, jam); assert.ok(time.options(jam).some(o => o.v === r.v), 'the reported case: a one-go design jam was offered 4 weeks');
  assert.notEqual(r.v, 'w4'); jam.time = { value: r.v, source: 'recommended' }; assert.equal(F.problem(time, jam), ''); assert.equal(F.reviewNote(time, jam), '');
  for (const format of ['course', 'workshop', 'cohort', 'talk', 'clinic']) for (const prior of ['new', 'some', 'solid', 'unsure']) for (const id of ['time', 'delivery', 'hours']) {
    const a = mk({ format, prior }), q = F.byId(id); if (q.when && !q.when(a)) continue; const s = F.recommend(q, a); assert.ok(s && q.options(a).some(o => o.v === s.v), `${format} ${prior} ${id}`); }
  for (const shape of ['once', 'weeks']) for (const prior of ['new', 'solid']) { const a = mk({ format: { value: F.CUSTOM, text: 'Residency' }, shape, prior }); for (const id of ['time', 'delivery']) { const q = F.byId(id), s = F.recommend(q, a); assert.ok(q.options(a).some(o => o.v === s.v), `${shape} ${prior} ${id}`); } }
});

test('a format the team names must say its shape, and nobody is given a shape by silence', () => {
  const mk = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
  const a = mk({ format: { value: F.CUSTOM, text: 'Design jam' } }), shape = F.byId('shape');
  assert.ok(F.activePath(a).includes(shape)); assert.ok(F.problem(shape, a), 'it cannot be skipped'); assert.ok(shape.hint);
  const group = F.byId('group'); assert.equal(F.problem(group, a), '', 'group size may be left open'); assert.ok(group.options(a).some(o => o.v === 'unknown')); assert.ok(/nobody knows/i.test(group.hint));
});

test('the brief asks only what changes the design, and optional questions can be left open', () => {
  const mk = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v }]));
  const solo = mk({ format: 'workshop', entry: 'have', topic: 'Knots', delivery: 'room' }), ids = a => F.activePath(a).map(q => q.id);
  assert.ok(!ids(solo).includes('priorMix')); assert.ok(!ids(solo).includes('split')); assert.ok(!ids(solo).includes('room')); assert.ok(!ids(solo).includes('shape'));
  const mixed = mk({ format: 'course', entry: 'mix', mix: ['Budgeting', 'Spreadsheets'], delivery: 'blended', limits: ['room'] });
  for (const id of ['priorMix', 'split', 'room', 'hours', 'group']) assert.ok(ids(mixed).includes(id), id);
  assert.equal(F.problem(F.byId('priorMix'), mixed), ''); assert.equal(F.problem(F.byId('priorMix'), Object.assign({}, mixed, { priorMix: { value: '  ' } })), ''); assert.equal(F.problem(F.byId('split'), mixed), '');
  assert.ok(F.problem(F.byId('room'), mixed), 'a list of what is available is needed once the team says the room is limited');
  assert.ok(/Two or three/.test(F.byId('mix').hint));
  const self = mk({ format: 'course', entry: 'have', topic: 'Knots', delivery: 'self' }); assert.deepEqual(F.byId('split').options(self).map(o => o.v), ['none', 'checkin']);
  for (const format of ['course', 'workshop', 'cohort']) assert.ok(F.byId('delivery').options(mk({ format })).some(o => o.v === 'hybrid'), format);
});

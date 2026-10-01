// Glitch Loom — reading saved work safely.
// Rule: saved work that cannot be read is never replaced without an explicit decision by the person.

import { WRITER, REQ, previewChange } from './journey.js';
import { byId, briefDigest } from './flow.js';

export const BASE_KEY = 'glitch-loom/v1';
export const STAGES = ['draft', 'review', 'approved', 'exported'];

// `?store=name` keeps a separate, disposable copy for testing. The owner's real work lives under the plain key.
// If a `store` value is present at all, the owner's key is never used, whatever the value looks like.
// A misspelt name for it (`Store`, `store[]`) counts as well, so a typing slip can never land in the owner's work.
export function storeParam(search) {
  const q = new URLSearchParams(String(search || '').replace(/^\?/, ''));
  const k = q.has('store') ? 'store' : [...q.keys()].find(x => /store/i.test(x));
  return k === undefined ? null : (q.get(k).trim().toLowerCase() || 'unnamed');
}
export function keyFor(search) {
  const s = storeParam(search);
  if (s === null) return { key: BASE_KEY, name: '' };
  const name = encodeURIComponent(s);
  return { key: BASE_KEY + '#' + name, name };
}

export const fresh = () => ({ v: 1, name: '', answers: {}, at: 'format', fromSummary: false, journey: null, jDigest: null, jBrief: null, genBrief: null, genDigest: null, outlineDraft: null, outlineFor: '', ackOutline: false, pendingEdit: null, settled: [], editing: null, act: 'a1', step: 0, revSeq: 0, askOpen: false, undo: [], log: [], pending: null, pendingNote: '', sel: null, act: 'a1', tab: 'learner', scope: 'session', turn: 0, simOpen: false, life: { stage: 'draft', ver: 1, snapshots: [], exports: [], publications: [] } });

const isObj = o => !!o && typeof o === 'object' && !Array.isArray(o);
const isStr = s => typeof s === 'string';
const isNum = n => typeof n === 'number' && Number.isFinite(n);
const isInt = n => isNum(n) && Math.round(n) === n;
const MAX_MIN = 60 * 24 * 366, okMin = n => isInt(n) && n > 0 && n <= MAX_MIN, isDate = s => isStr(s) && !Number.isNaN(Date.parse(s));

function journeyProblems(j, where) {
  const out = [], say = t => out.push(`${where}: ${t}`);
  if (!isObj(j)) return [`${where} is not a journey`];
  if (!Array.isArray(j.topics) || !j.topics.length || !j.topics.every(isStr)) say('topics are missing');
  if (!okMin(j.budget)) say('the requested time is missing or not a whole number of minutes');
  if (!Array.isArray(j.sessions) || !j.sessions.length) { say('sessions are missing'); return out; }
  const ids = j.sessions.map(s => isObj(s) ? s.id : null); if (new Set(ids).size !== ids.length) say('two sessions share the same id');
  const nT = Array.isArray(j.topics) ? j.topics.length : 0;
  if (j.internal != null && !(Array.isArray(j.internal) && j.internal.every(isStr))) say('internal notes are unreadable');
  if (j.connections != null && !(Array.isArray(j.connections) && j.connections.every(isObj))) say('topic connections are unreadable');
  if (j.origin != null && !['simulated', 'claude'].includes(j.origin)) say('it does not say how it was made');
  if (j.sources != null && !(Array.isArray(j.sources) && j.sources.every(x => isObj(x) && isStr(x.id) && isStr(x.url) && isStr(x.title)))) say('the list of sources is unreadable');
  if (j.review != null && !isObj(j.review)) say('the review record is unreadable');
  if (j.reviewLaunch != null && !(isObj(j.reviewLaunch) && isInt(j.reviewLaunch.rev) && isStr(j.reviewLaunch.uid))) say('the review-launch record is unreadable');
  if (j.review != null && isObj(j.review) && j.review.of != null && !isStr(j.review.of)) say('the review record is unreadable');
  if (j.pipeline === 2) {
    if (!isObj(j.map) || !Array.isArray(j.map.nodes) || !j.map.nodes.every(n => isObj(n) && isStr(n.id) && isStr(n.name))) say('the topic map is unreadable');
    if (j.projects != null && !(Array.isArray(j.projects) && j.projects.every(p => isObj(p) && isStr(p.id) && isObj(p.outline) && ['pending', 'written', 'failed'].includes(p.status) && (p.status !== 'written' || isObj(p.content))))) say('the projects are unreadable');
    if (j.agents != null && !isObj(j.agents)) say('the reviewers’ records are unreadable');
  }
  j.sessions.forEach((s, i) => {
    const w = `session ${i + 1}`;
    if (!isObj(s)) return say(`${w} is not readable`);
    if (!isStr(s.id) || !isStr(s.title) || !isStr(s.unit)) say(`${w} has no name`);
    if (!okMin(s.minutes)) say(`${w} has no usable length`);
    if (!Array.isArray(s.threads) || !s.threads.length || !s.threads.every(t => isInt(t) && t >= 0 && t < nT)) say(`${w} has topic tags that match no topic`);
    if (!isObj(s.teacher) || !Array.isArray(s.teacher.materials) || !s.teacher.materials.every(isStr) || !isStr(s.teacher.setup)) say(`${w} has no teacher materials`);
    else for (const k of ['requirements', 'access']) if (s.teacher[k] != null && !(Array.isArray(s.teacher[k]) && s.teacher[k].every(isStr))) say(`${w} has unreadable ${k}`);
    if (s.internal != null && !(Array.isArray(s.internal) && s.internal.every(isStr))) say(`${w} has unreadable internal notes`);
    for (const k of ['aim', 'proof', 'why']) if (!isStr(s[k])) say(`${w} is missing its ${k}`);
    for (const k of ['prerequisites', 'contributions', 'successCriteria', 'claims', 'buildsOn', 'assumptions']) if (s[k] != null && !Array.isArray(s[k])) say(`${w} has unreadable ${k}`);
    if (s.status != null && !['written', 'pending', 'failed'].includes(s.status)) say(`${w} has an unknown state`);
    if (s.status === 'pending' || s.status === 'failed') { if (!Array.isArray(s.activities)) say(`${w} has unreadable steps`); return; } // not written yet: there is nothing more to check
    if (!Array.isArray(s.activities) || !s.activities.length) return say(`${w} has no steps`);
    let sum = 0, okSteps = true;
    s.activities.forEach((x, k) => { if (!isObj(x) || !isStr(x.id) || !isStr(x.kind) || !isStr(x.learner) || !isStr(x.teacher) || !okMin(x.minutes) || (x.internal != null && !(Array.isArray(x.internal) && x.internal.every(isStr))) || ['instructions', 'guidance', 'materials', 'success'].some(k => x[k] != null && !(Array.isArray(x[k]) && x[k].every(isStr))) || (x.misconceptions != null && !(Array.isArray(x.misconceptions) && x.misconceptions.every(isObj)))) { okSteps = false; say(`${w}, step ${k + 1} is incomplete`); } else sum += x.minutes; });
    if (okSteps && new Set(s.activities.map(x => x.id)).size !== s.activities.length) say(`${w} has two steps with the same id`);
    if (okSteps && okMin(s.minutes) && sum !== s.minutes) say(`${w} is ${s.minutes} minutes but its steps add up to ${sum}`);
  });
  return out;
}

// The complete structure is checked, not only the version number.
export function validate(s) {
  const out = [];
  if (!isObj(s)) return ['the saved data is not a Loom project'];
  if (s.v !== 1) out.push('it was saved by a version of Loom this one does not know');
  if (!isObj(s.answers)) out.push('the answers are missing');
  else for (const k in s.answers) { const x = s.answers[k]; if (!isObj(x) || !('value' in x) || x.value === undefined) out.push(`the answer “${k}” is incomplete`); else if (Array.isArray(x.value) ? !x.value.every(isStr) : !(isStr(x.value) || x.value === null)) out.push(`the answer “${k}” has an unreadable value`); else if (byId(k) && x.value !== null && (['multi', 'chips'].includes(byId(k).type) !== Array.isArray(x.value))) out.push(`the answer “${k}” is the wrong kind of answer for its question`); else if ('text' in x && !isStr(x.text)) out.push(`the answer “${k}” has unreadable text`); }
  if (!isStr(s.at)) out.push('the current screen is missing');
  if (s.journey != null) out.push(...journeyProblems(s.journey, 'the draft journey'));
  if (s.undo != null) { if (!Array.isArray(s.undo)) out.push('the undo history is unreadable'); else s.undo.forEach((u, i) => { if (!isObj(u)) out.push(`undo step ${i + 1} is unreadable`); else out.push(...journeyProblems(u.journey, `undo step ${i + 1}`)); }); }
  if (s.log != null && !(Array.isArray(s.log) && s.log.every(l => isObj(l) && isStr(l.what) && isStr(l.label) && isStr(l.target)))) out.push('the change log is unreadable');
  if (s.undo != null && Array.isArray(s.undo) && !s.undo.every(u => isObj(u) && isStr(u.label) && isStr(u.target))) out.push('an undo step has no description');
  if (s.jBrief != null && !isObj(s.jBrief)) out.push('the brief the journey was made from is unreadable');
  if (!isObj(s.life)) out.push('the version history is missing');
  else {
    if (!STAGES.includes(s.life.stage)) out.push('the lifecycle stage is unknown');
    if (!isInt(s.life.ver) || s.life.ver < 1) out.push('the version number is missing');
    for (const k of ['snapshots', 'exports', 'publications']) if (!Array.isArray(s.life[k])) out.push(`the list of ${k} is missing`);
    const snaps = Array.isArray(s.life.snapshots) ? s.life.snapshots.filter(isObj) : [], vers = snaps.map(p => p.ver);
    if (new Set(vers).size !== vers.length) out.push('two approved snapshots share a version number');
    if (isInt(s.life.ver) && vers.some(v => isInt(v) && v > s.life.ver)) out.push('an approved snapshot is newer than the working version');
    if (isInt(s.life.ver) && (s.life.stage === 'draft' || s.life.stage === 'review') && vers.includes(s.life.ver)) out.push(`version ${s.life.ver} is marked unapproved but already has an approved snapshot`);
    if ((s.life.stage === 'approved' || s.life.stage === 'exported') && !vers.includes(s.life.ver)) out.push('the working version is marked approved but has no snapshot');
    (Array.isArray(s.life.snapshots) ? s.life.snapshots : []).forEach((p, i) => { if (!isObj(p) || !isInt(p.ver) || p.ver < 1 || !isDate(p.at) || !isObj(p.brief)) out.push(`approved snapshot ${i + 1} is incomplete`); else out.push(...journeyProblems(p.journey, `approved snapshot v${p.ver}`)); });
    for (const k of ['exports', 'publications']) (Array.isArray(s.life[k]) ? s.life[k] : []).forEach((e, i) => { if (!isObj(e) || !isInt(e.ver) || !isDate(e.at)) out.push(`${k} record ${i + 1} is incomplete`); });
  }
  return out;
}

// Bring work saved by an earlier build up to date. Approved snapshots are never touched.
function liftJourney(j, seq) {
  if (!isInt(j.rev)) j.rev = seq;
  if (!isStr(j.uid) || !j.uid) j.uid = 'j' + Date.now().toString(36) + 'm' + seq;
  if (!isStr(j.origin)) j.origin = 'simulated'; // everything made before the real engine existed was a simulated example
  if (!Array.isArray(j.internal)) j.internal = [];
  const rq = j.requested; if (!(isObj(rq) && isStr(rq.span) && okMin(rq.minutes) && isInt(rq.sessions) && rq.sessions > 0 && isStr(rq.unit))) j.requested = { span: j.span || '', minutes: j.budget, sessions: j.sessions.length, unit: j.sessions[0].unit, weekly: j.sessions[0].unit === 'Week' };
  if (j.mode === undefined) j.mode = j.topics.length > 1 ? 'shared' : null;
  j.connections = (Array.isArray(j.connections) ? j.connections : []).map(c => Array.isArray(c.names) ? c : { names: [c.a, c.b].filter(Boolean), type: c.type === 'Needs first' ? 'Order' : c.type, why: c.why, session: c.session });
  for (const s of j.sessions) {
    if (!Array.isArray(s.internal)) s.internal = [];
    if (!Array.isArray(s.teacher.requirements)) s.teacher.requirements = (s.teacher.access || []).map(t => REQ + t.charAt(0).toLowerCase() + t.slice(1));
    for (const x of s.activities) {
      if (!Array.isArray(x.internal)) x.internal = [];
      // Earlier builds wrote writer requests into the teacher note. They belong in internal notes.
      const m = x.teacher.match(new RegExp('\\s*' + WRITER + ': “[^”]*”\\.?'));
      if (m) { x.internal.push(m[0].trim() + ' Moved here from the teacher note by a later version of Loom.'); x.teacher = x.teacher.replace(m[0], '').trim(); }
    }
  }
  return j;
}
export function migrate(s) {
  const out = Object.assign(fresh(), s);
  if (!isInt(out.revSeq)) out.revSeq = 0;
  // "Both at once" for talks and clinics was stored as 'blended'. It is the same choice under a clearer name,
  // so the journey made from it must not suddenly look out of date.
  const lift = a => { const f = a && a.format && a.format.value, d = a && a.delivery; if (d && d.value === 'blended' && (f === 'talk' || f === 'clinic')) { d.value = 'hybrid'; return true; } return false; };
  const matched = !!out.journey && isStr(out.jDigest) && out.jDigest === briefDigest(out.answers);
  if (lift(out.answers) && matched) out.jDigest = briefDigest(out.answers);
  if (isObj(out.jBrief)) lift(out.jBrief);
  // Opening saved work must not change it. A number is only handed out to a draft that has none.
  const seq = j => isInt(j.rev) ? j.rev : ++out.revSeq;
  if (out.journey) { liftJourney(out.journey, seq(out.journey)); }
  out.undo = (out.undo || []).map(u => Object.assign({}, u, { journey: liftJourney(u.journey, seq(u.journey)) }));
  if (out.journey) out.revSeq = Math.max(out.revSeq, out.journey.rev, ...out.undo.map(u => u.journey.rev));
  // A preview is only trusted if it says which draft it was made from.
  // A saved preview is never trusted as it stands: it is made again from the current draft, or dropped.
  const p = out.pending; out.pending = null;
  if (out.journey && isObj(p) && p.kind === 'ai' && isStr(p.editId) && /^[a-z0-9]{4,40}$/.test(p.editId)) out.pending = { kind: 'ai', editId: p.editId, needsRebuild: true, baseRev: p.baseRev, baseUid: p.baseUid, label: isStr(p.label) ? p.label : '', target: isStr(p.target) ? p.target : '', req: isObj(p.req) ? p.req : {} };
  else if (out.journey && isObj(p) && isObj(p.req) && ['activity', 'session', 'journey'].includes(p.req.scope) && ['shorter', 'hands', 'found', 'text'].includes(p.req.kind)) { try { out.pending = previewChange(out.journey, { scope: p.req.scope, kind: p.req.kind, text: isStr(p.req.text) ? p.req.text : '', sessionId: p.req.sessionId, activityId: p.req.activityId }); } catch (e) { out.pending = null; } }
  if (!isStr(out.pendingNote)) out.pendingNote = '';
  out.life.trials = (Array.isArray(out.life.trials) ? out.life.trials : []).filter(t => isObj(t) && isInt(t.ver) && ['rehearsal', 'pilot'].includes(t.kind) && isDate(t.at)).map(t => ({ ver: t.ver, kind: t.kind, at: t.at, note: isStr(t.note) ? t.note.slice(0, 200) : '' }));
  out.settled = (Array.isArray(out.settled) ? out.settled : []).filter(isStr).slice(-40);
  if (!isStr(out.name)) out.name = '';
  if (out.editing != null && !isObj(out.editing)) out.editing = null;
  if (out.pendingEdit != null && !(isObj(out.pendingEdit) && isStr(out.pendingEdit.id))) out.pendingEdit = null;
  if (out.outlineDraft != null && !(isObj(out.outlineDraft) && Array.isArray(out.outlineDraft.sessions))) out.outlineDraft = null;
  if (!['generate', 'outline', 'checks', 'activity', 'summary', 'journey', 'session', 'project'].includes(out.at) && !byId(out.at)) out.at = 'format';
  return out;
}

export function inspect(raw) {
  if (raw === null || raw === undefined || raw === '') return { status: 'empty' };
  let parsed; try { parsed = JSON.parse(raw); } catch (e) { return { status: 'damaged', reasons: ['it is not readable as saved data'] }; }
  const problems = validate(parsed);
  if (problems.length) return { status: 'damaged', reasons: problems.slice(0, 6) };
  try { return { status: 'ok', state: migrate(parsed) }; } catch (e) { return { status: 'damaged', reasons: ['it could not be brought up to date: ' + e.message] }; }
}

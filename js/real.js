// Glitch Loom — turning Claude's answers into a draft the team can edit, and tracking what edits affect.
// Nothing here writes content. If a part has not been written, it is shown as not written.

import * as F from './flow.js';
import * as J from './journey.js';

const clone = o => JSON.parse(JSON.stringify(o));
const txt = v => typeof v === 'string' ? v.trim() : '';
const list = v => (Array.isArray(v) ? v : []).map(txt).filter(Boolean);
let uid = 0; const newId = p => p + Date.now().toString(36) + (uid++);

export const KIND = { setup: 'Set up', try: 'Try', worked_example: 'Worked example', explain: 'Explain', make: 'Make', feedback: 'Feedback', revise: 'Revise', discuss: 'Discuss', apply: 'Apply', check: 'Check', break: 'Break' };
export const CLAIM = { fact: 'Fact', uncertain: 'Uncertain', hypothesis: 'Judgement', fiction: 'Fiction' };
export const QUICK = {
  shorter: 'Make this about a quarter shorter. Keep the task itself, the feedback step and the revision step.',
  hands: 'Make this more hands-on: less listening and more doing. Keep the outcome the same.',
  found: 'Add a short foundation step at the start for learners who lack the basics. Keep the total time the same by trimming elsewhere.'
};

/* ---------- what is sent to Claude ---------- */
export function briefFor(a) {
  const t = F.topicsOf(a), lab = id => F.labelOf(F.byId(id), a), v = id => a[id] ? a[id].value : null;
  return { format: lab('format'), formatKey: v('format'), topics: t.list, mode: t.list.length > 1 ? (t.mode || 'shared') : null, world: t.world || null,
    audience: lab('audience'), audienceKey: v('audience'), groupSize: a.group && v('group') !== 'unknown' ? lab('group') : 'Not given', runsAs: a.shape ? lab('shape') : undefined, prior: lab('prior'), unevenExperience: a.priorMix && txt(v('priorMix')) ? txt(v('priorMix')) : undefined, liveAndOwnTime: [a.split ? lab('split') : '', F.ownMinutes(a) ? `${F.fmtMin(F.ownMinutes(a))} of independent work each week, outside the meetings and counted apart from them` : ''].filter(Boolean).join('. ') || undefined, priorKey: v('prior'), outcome: txt(v('outcome')), delivery: lab('delivery'), deliveryKey: v('delivery'),
    time: J.request(a).span, independentPerWeek: F.ownMinutes(a) || undefined, requirements: J.requirementsOf(a).map(r => r.replace(J.REQ, '')) };
}
export function planFor(a) {
  const rq = J.request(a);
  // A pattern the team set is used exactly: equal meetings of the length they asked for.
  const minutes = rq.weekly || rq.setByTeam ? Array(rq.n).fill(rq.per) : J.splitExact(rq.total, rq.n);
  return Object.assign({ sessions: rq.n, minutes, unit: rq.unit, total: rq.total, weekly: rq.weekly, setByTeam: !!rq.setByTeam, span: rq.span },
    rq.weekly ? { weeks: rq.weeks, meetingsPerWeek: rq.meetingsPerWeek, cadence: rq.cadence, independent: rq.independent || null } : {});
}

/* ---------- the draft made when an outline is approved: every session is "not written yet" ---------- */
const CONNECT = { justified: 'Used together', partly: 'Partly joined', not_justified: 'Not justified', kept_separate: 'Kept separate' };
export function fromOutline(outline, brief, plan, research, a, ex) {
  const req = J.requirementsOf(a), idx = name => brief.topics.findIndex(t => t.toLowerCase() === String(name).toLowerCase());
  const sessions = outline.sessions.map((s, i) => ({ id: 's' + (i + 1), key: 'real', origin: 'claude', status: 'pending', unit: plan.unit, title: txt(s.title), aim: txt(s.outcome), outcome: txt(s.outcome), proof: txt(s.evidence_of_learning), why: txt(s.serves), serves: txt(s.serves), keyTask: txt(s.key_task),
    threads: [...new Set((s.topics || []).map(idx).filter(n => n >= 0))].sort(), contributions: (s.contributions || []).map(c => ({ topic: txt(c.topic), gives: txt(c.gives) })), buildsOn: (s.builds_on || []).map(n => 's' + n), minutes: plan.minutes[i], activities: [],
    teacher: { materials: [], requirements: req.slice(), setup: '', prep: 0, prepSteps: [] }, prerequisites: [], prerequisitesNote: '', successCriteria: [], applicationCheck: null, claims: [], assumptions: [], internal: [], review: null,
    ...(ex ? { teachesPlanned: list(s.teaches), practisesPlanned: list(s.practises), independentPlanned: (s.independent_work || {}).minutes || 0 } : {}) }));
  const integ = outline.integration || {}, connections = [];
  if (brief.topics.length > 1) {
    const joint = sessions.filter(s => s.threads.length === brief.topics.length)[0];
    const type = CONNECT[integ.status] || 'Not established';
    connections.push({ names: brief.topics.slice(), type: type === 'Used together' && !joint ? 'Partly joined' : type, session: type === 'Used together' && joint ? joint.id : undefined, judgedBy: 'Claude', why: [txt(integ.reason), txt(integ.joining_task) ? 'Joining task: ' + txt(integ.joining_task) : '', 'This is Claude’s judgement. Nobody has tried the task with learners.'].filter(Boolean).join(' ') });
  }
  if (brief.world) connections.push({ names: [brief.world, brief.topics[0]], type: 'Inspiration only', why: 'The world supplies examples only. Fact, guess and fiction are labelled in each session’s claims. No characters, art or text are reproduced, and no permission is implied.' });
  const r = research || {};
  return { rev: 0, uid: newId('j'), origin: 'claude', outcome: brief.outcome, courseOutcome: txt(outline.course_outcome), finalEvidence: txt(outline.final_evidence), feasibility: outline.feasibility || null, integration: outline.integration || null, assumptions: list(outline.assumptions),
    topics: brief.topics.slice(), world: brief.world, mode: brief.mode, format: brief.format, audience: brief.audience, delivery: brief.delivery, span: plan.span, budget: plan.total, requested: { span: plan.span, minutes: plan.total, sessions: plan.sessions, unit: plan.unit, weekly: !!plan.weekly },
    sessions, connections, sources: clone(r.sources || []), research: { openQuestions: list(r.open_questions), notOpened: clone(r.not_opened || []), combination: r.combination_evidence || null, searches: list(r.searches), researchedAt: r.researchedAt || '', unconfirmedReads: list(r.unconfirmedReads), ...(ex ? { nodeCoverage: clone(r.nodeCoverage || []), nodeFindings: clone(r.node_findings || []), lineage: clone(r.lineage || null), lineageChains: clone(r.lineageChains || []) } : {}) },
    review: null, internal: [], madeAt: new Date().toISOString(), ...(ex ? v2Parts(outline, plan, ex) : {}) };
}
// What the expanded pipeline adds to a draft: the map, coverage, projects, time, and what each separate reviewer said. Copied from the generation record at approval.
function v2Parts(outline, plan, ex) {
  const m = ex.map || {}, agents = ex.agents || {};
  return { pipeline: 2, map: clone(m), coverage: clone(ex.coverage || null), accounting: clone(ex.accounting || null), policy: clone(ex.policy || null), independentPlan: plan.independent || null,
    timeConflict: clone(outline.time_conflict || null), deferred: clone(outline.deferred || []), pathwayNote: txt(outline.pathway_note), acknowledged: clone(ex.acknowledged || []),
    projects: (outline.projects || []).map(x => ({ id: x.id, status: 'pending', outline: clone(x), content: null, assetChecks: [] })), agents: clone(agents), preparedFiles: clone(ex.prepared || []) };
}

export function activityFrom(x, id) {
  const steps = list(x.instructions), guidance = list(x.teacher);
  return { id, kindKey: x.kind, kind: KIND[x.kind] || 'Step', title: txt(x.title), goal: txt(x.goal), minutes: x.minutes, instructions: steps, learner: steps.map((t, i) => `${i + 1}. ${t}`).join('\n') || txt(x.goal), materials: list(x.materials), handout: txt(x.handout), example: txt(x.worked_example),
    guidance, teacher: guidance.join(' '), misconceptions: (x.misconceptions || []).filter(m => txt(m.belief)).map(m => ({ belief: txt(m.belief), response: txt(m.response) })), success: list(x.success), internal: [], origin: 'claude' };
}
// Fill one session with what Claude wrote. Only ever called for a session that is still unwritten.
export function fillSession(s, out) {
  const acts = (out.activities || []).map((x, k) => activityFrom(x, 'a' + (k + 1)));
  const setup = acts.filter(x => x.kindKey === 'setup').map(x => x.guidance.concat(x.instructions).join(' ')).join(' ');
  return Object.assign(s, { status: 'written', title: txt(out.title) || s.title, aim: txt(out.outcome) || s.aim, outcome: txt(out.outcome) || s.outcome, why: txt(out.serves) || s.why, serves: txt(out.serves) || s.serves,
    prerequisites: (out.prerequisites || []).filter(q => txt(q.name)).map(q => ({ name: txt(q.name), support: txt(q.support) })), prerequisitesNote: txt(out.prerequisites_note), contributions: (out.contributions || []).map(c => ({ topic: txt(c.topic), gives: txt(c.gives) })),
    ...(out.teaches_nodes !== undefined ? { teachesNodes: clone(out.teaches_nodes), assets: clone(out.assets || []), independentWork: clone(out.independent_work || { minutes: 0, tasks: [] }), projectWork: clone(out.project_work || []) } : {}),
    activities: acts, successCriteria: list(out.success_criteria), proof: list(out.success_criteria).join(' '), applicationCheck: out.application_check ? { when: txt(out.application_check.when), task: txt(out.application_check.task), looksFor: list(out.application_check.looks_for) } : null,
    claims: (out.claims || []).filter(c => txt(c.text)).map(c => Object.assign({ text: txt(c.text), type: c.type, sources: list(c.sources), note: txt(c.note) }, c.support ? { support: c.support } : {})), assumptions: list(out.assumptions),
    teacher: Object.assign({}, s.teacher, { materials: [...new Set(acts.flatMap(x => x.materials))], setup: setup || 'No separate setup is needed.', prep: (out.preparation || {}).minutes || 0, prepSteps: list((out.preparation || {}).steps) }) });
}
export const activityBack = x => ({ kind: x.kindKey, title: x.title, goal: x.goal, minutes: x.minutes, instructions: x.instructions || [], materials: x.materials || [], handout: x.handout || '', worked_example: x.example || '', teacher: x.guidance || [], misconceptions: x.misconceptions || [], success: x.success || [] });
export const sessionBack = s => ({ title: s.title, outcome: s.outcome, serves: s.serves, prerequisites: s.prerequisites || [], prerequisites_note: s.prerequisitesNote || '', contributions: s.contributions || [], preparation: { minutes: s.teacher.prep || 0, steps: s.teacher.prepSteps || [] }, activities: s.activities.map(activityBack), success_criteria: s.successCriteria || [],
  application_check: s.applicationCheck ? { when: s.applicationCheck.when, task: s.applicationCheck.task, looks_for: s.applicationCheck.looksFor || [] } : { when: '', task: '', looks_for: [] }, claims: (s.claims || []).map(c => ({ text: c.text, type: c.type, sources: c.sources || [], support: c.support || (c.type === 'fact' ? 'partly' : 'not_from_source'), note: c.note || '' })), assumptions: s.assumptions || [],
  ...(s.teachesNodes !== undefined ? { teaches_nodes: clone(s.teachesNodes), assets: clone(s.assets || []), independent_work: clone(s.independentWork || { minutes: 0, tasks: [] }), project_work: clone(s.projectWork || []) } : {}) });

// Exactly what is sent to be reviewed: the draft as the team has it now. The same projection is fingerprinted,
// so a finished review can be matched against the draft in front of the team.
export const reviewInput = j => j.sessions.map((s, i) => Object.assign({ number: i + 1, minutes: s.minutes }, sessionBack(s)));
// A project as written, exactly as the server has it: what Claude returned, with the project's id.
export const projectBack = p => Object.assign({}, clone(p.content), { id: p.id });
export const reviewProjects = j => (j.projects || []).filter(p => p.status === 'written' && p.content).map(projectBack);
// The material a review judges: the sessions alone for a course made before projects existed, and the sessions and projects together otherwise.
export const reviewMaterial = j => reviewProjects(j).length ? { sessions: reviewInput(j), projects: reviewProjects(j) } : reviewInput(j);
export const reviewPrint = j => J.contentPrint(reviewMaterial(j));

// The sessions as the team has them now. Sent with a request so that what Claude writes next fits the draft, including the team's own edits.
export const writtenNow = j => !j || !J.isReal(j) ? [] : j.sessions.map((s, i) => ({ s, i })).filter(({ s }) => s.status === 'written' && (s.activities || []).length).map(({ s, i }) => ({ number: i + 1, content: sessionBack(s) }));
export const numbersOf = (j, ids) => (ids || []).map(id => j.sessions.findIndex(s => s.id === id) + 1).filter(n => n > 0);

/* ---------- bringing finished work from the server into the draft ---------- */
// Returns how many sessions were filled. Written sessions are never touched, so the team's edits are safe.
export function absorb(journey, record) {
  if (!journey || !J.isReal(journey) || !record) return 0;
  let n = 0; const units = (record.stages.materials || {}).sessions || [];
  journey.sessions.forEach((s, i) => { const u = units[i]; if (!u || s.key !== 'real') return;
    if ((s.status === 'pending' || s.status === 'failed') && u.status === 'done' && u.output) { fillSession(s, u.output); s.assetChecks = clone(u.assetChecks || []); n++; }
    else if (s.status === 'pending' && u.status === 'failed') { s.status = 'failed'; s.failure = [txt(u.reason), txt(u.detail)].filter(Boolean).join(' '); n++; } });
  const pu = ((record.stages.projects || {}).units) || [];
  (journey.projects || []).forEach((p, i) => { const u = pu[i]; if (!u) return;
    if (p.status !== 'written' && u.status === 'done' && u.output) { p.status = 'written'; p.content = clone(u.output); p.assetChecks = clone(u.assetChecks || []); n++; }
    else if (p.status === 'pending' && u.status === 'failed') { p.status = 'failed'; p.failure = [txt(u.reason), txt(u.detail)].filter(Boolean).join(' '); n++; } });
  return n;
}

/* ---------- a preview built from a change Claude made ---------- */
const stepLine = x => `${x.kind} · ${x.minutes} min · ${x.goal || x.title}`;
export function diffSession(a, b) {
  const lines = [], eq = (p, q) => JSON.stringify(p) === JSON.stringify(q);
  if (a.title !== b.title) lines.push({ label: 'Title', was: a.title, now: b.title });
  if (a.outcome !== b.outcome) lines.push({ label: 'Outcome', was: a.outcome, now: b.outcome });
  if (a.minutes !== b.minutes) lines.push({ label: 'Length', was: F.fmtMin(a.minutes), now: F.fmtMin(b.minutes) });
  const n = Math.max(a.activities.length, b.activities.length);
  for (let i = 0; i < n; i++) { const x = a.activities[i], y = b.activities[i];
    if (!x) lines.push({ label: `New step ${i + 1}`, was: 'Nothing', now: stepLine(y) });
    else if (!y) lines.push({ label: `Step ${i + 1} removed`, was: stepLine(x), now: 'Nothing' });
    else { const p = Object.assign({}, x, { id: 0, internal: 0, origin: 0 }), q = Object.assign({}, y, { id: 0, internal: 0, origin: 0 }); if (!eq(p, q)) { const what = ['instructions', 'handout', 'example', 'guidance', 'misconceptions', 'success', 'materials'].filter(k => !eq(x[k], y[k])).map(k => ({ example: 'worked example', guidance: 'teacher guidance', success: 'success signs' }[k] || k)); lines.push({ label: `Step ${i + 1}`, was: stepLine(x), now: stepLine(y) + (what.length ? ` · changed: ${what.join(', ')}` : '') }); } } }
  if (!eq(a.successCriteria, b.successCriteria)) lines.push({ label: 'Success criteria', was: (a.successCriteria || []).join(' / ') || 'None', now: (b.successCriteria || []).join(' / ') || 'None' });
  if (!eq(a.applicationCheck, b.applicationCheck)) lines.push({ label: 'Later check', was: a.applicationCheck ? a.applicationCheck.task : 'None', now: b.applicationCheck ? b.applicationCheck.task : 'None' });
  if (!eq(a.prerequisites, b.prerequisites)) lines.push({ label: 'Prerequisites', was: (a.prerequisites || []).map(q => q.name).join(', ') || 'None', now: (b.prerequisites || []).map(q => q.name).join(', ') || 'None' });
  if (!eq(a.claims, b.claims)) lines.push({ label: 'Claims', was: `${(a.claims || []).length} listed`, now: `${(b.claims || []).length} listed` });
  return lines;
}
const writerNote = (text, reply) => `${J.WRITER}: “${txt(text)}”. Not acted on.${reply ? ' Claude said: ' + txt(reply) : ''}`;
// Work out the draft that would result from an edit Claude finished. The current draft is not touched.
export function previewFromEdit(journey, edit, req) {
  const after = clone(journey), lines = [], notes = [], base = { kind: 'ai', editId: edit.id, baseRev: journey.rev || 0, baseUid: journey.uid || '', req: clone(req), label: txt(edit.instruction) === txt(QUICK[req.kind]) ? J.KINDS[req.kind] : txt(req.text) || J.KINDS[req.kind] };
  const stale = (edit.baseRev !== (journey.rev || 0)) || (edit.baseUid !== (journey.uid || ''));
  const target = req.scope === 'journey' ? 'Whole journey' : null;
  if (stale) return Object.assign(base, { after: clone(journey), target: target || 'An earlier draft', lines: [], noop: true, gone: true, effects: ['The draft changed while Claude was working, so this result no longer fits it. Nothing will change. Ask again if you still want it.'] });
  let acted = 0, tgt = target;
  for (const part of edit.parts) {
    const s0 = journey.sessions[part.number - 1], s1 = after.sessions[part.number - 1], out = part.output || {};
    if (!s0 || !s1) continue;
    if (!tgt) tgt = req.scope === 'activity' ? `Step “${(s0.activities.find(x => x.id === req.activityId) || {}).title || ''}” in ${s0.unit.toLowerCase()} ${part.number}` : `${s0.unit} ${part.number}: ${s0.title}`;
    if (!out.acted) { const n = writerNote(req.text || edit.instruction, out.note), x = req.scope === 'activity' ? s1.activities.find(y => y.id === req.activityId) : null; (x ? x.internal : req.scope === 'journey' ? after.internal : s1.internal).push(n); if (req.scope !== 'journey' || !notes.length) lines.push({ label: 'Internal note, stays in Loom', was: 'None', now: n }); notes.push(`Claude did not change ${req.scope === 'journey' ? 'session ' + part.number : 'this'}: ${txt(out.note) || 'no reason given'}`); if (req.scope === 'journey' && after.internal.filter(t => t === n).length > 1) after.internal.pop(); continue; }
    acted++;
    if (req.scope === 'activity') { const k = s1.activities.findIndex(y => y.id === req.activityId); if (k < 0) continue; const keep = s1.activities[k]; s1.activities[k] = Object.assign(activityFrom(out.activity, keep.id), { internal: keep.internal || [] }); s1.minutes = s1.activities.reduce((n, y) => n + y.minutes, 0); }
    else { const notesBefore = s1.internal, ids = s1.activities.map(y => y.internal || []); fillSession(s1, out.session); s1.internal = notesBefore; s1.activities.forEach((y, k) => { y.internal = ids[k] || []; }); s1.minutes = s1.activities.reduce((n, y) => n + y.minutes, 0); }
    s1.teacher.materials = [...new Set(s1.activities.flatMap(y => y.materials || []))];
    const d = diffSession(s0, s1); if (txt(out.note)) notes.push(`Claude: ${txt(out.note)}`);
    if (req.scope === 'journey') lines.push({ label: `${part.number}. ${s0.title}`, was: F.fmtMin(s0.minutes), now: `${F.fmtMin(s1.minutes)} · ${d.length} part${d.length === 1 ? '' : 's'} changed` }); else lines.push(...d);
    if (d.length) flagDependents(after, s1.id, `It builds on “${s1.title}”, which was changed.`);
  }
  const before = J.totalMin(journey), now = J.totalMin(after), p1 = J.planOf(after), effects = notes;
  effects.push(now === before ? `Planned time stays ${F.fmtMin(before)}.` : `Planned time: ${F.fmtMin(before)} becomes ${F.fmtMin(now)}.`);
  if (p1.differs) effects.push(`Differs from the brief (${p1.requested.span}): ${p1.notes.join('; ')}. The brief itself is not changed.`);
  const hit = after.sessions.filter((s, i) => s.review && !(journey.sessions[i] || {}).review).map(s => s.title);
  if (hit.length) effects.push(`Will be marked for a look, because ${hit.length === 1 ? 'it builds' : 'they build'} on changed work: ${hit.join('; ')}. Nothing in ${hit.length === 1 ? 'it' : 'them'} is rewritten.`);
  if (!acted) effects.push('The request is kept as an internal note and will never appear in an export.');
  const was = J.audit(journey), problems = J.audit(after).filter(p => !was.includes(p));
  if (problems.length) return Object.assign(base, { after: clone(journey), target: tgt, lines: [], noop: true, blocked: true, effects: ['Loom will not apply this change, because the result would be inconsistent: ' + problems[0]] });
  const noop = JSON.stringify(after.sessions) === JSON.stringify(journey.sessions) && JSON.stringify(after.internal) === JSON.stringify(journey.internal);
  if (noop) return Object.assign(base, { after, target: tgt, lines: [], noop: true, effects: ['Claude returned the same content. Nothing would change.'] });
  return Object.assign(base, { after, target: tgt, lines, effects, noop: false });
}

/* ---------- what an edit touches ---------- */
export function flagDependents(j, changedId, reason) {
  const out = [];
  for (const s of j.sessions) if ((s.buildsOn || []).includes(changedId) && s.id !== changedId) { s.review = { reason, at: new Date().toISOString(), because: changedId }; out.push(s.id); }
  return out;
}
const AFFECTS = { format: 'the whole plan: number of sessions and their length', entry: 'every session', topic: 'every session and every topic connection', pick: 'every session', worldSubject: 'every session', mix: 'every session and every topic connection', mode: 'how topics are joined in every session',
  audience: 'examples, support and worked examples', prior: 'where each session starts and how much is taught first', outcome: 'every outcome, success criterion and later check', delivery: 'setup and the instructions in every step', time: 'the number of sessions and all timing', hours: 'the length of every session',
  limits: 'requirements and materials in every session', language: 'every handout and instruction', access: 'requirements in every session' };
export function briefChanges(was, now) {
  const out = [], ids = new Set([...F.activePath(was || {}).map(q => q.id), ...F.activePath(now || {}).map(q => q.id)]);
  for (const id of ids) { const q = F.byId(id), a = F.labelOf(q, was || {}), b = F.labelOf(q, now || {}); if (a !== b) out.push({ id, short: q.short, was: a || 'Not asked', now: b || 'No longer asked', affects: AFFECTS[id] || 'the plan' }); }
  return out;
}

/* ---------- applying what the team typed themselves ---------- */
const lines = v => String(v || '').split('\n').map(t => t.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean);
export function applyDirect(journey, edit) {
  if (edit.kind === 'course') return applyCourse(journey, edit);
  if (edit.kind === 'project') return applyProject(journey, edit);
  const after = clone(journey), s = after.sessions.find(x => x.id === edit.sessionId); if (!s) return { error: 'That session is no longer in the draft.' };
  const real = J.isReal(journey), f = edit.fields || {};
  if (edit.kind === 'activity') {
    const x = s.activities.find(y => y.id === edit.activityId); if (!x) return { error: 'That step is no longer in the draft.' };
    const m = Number(f.minutes); if (!Number.isInteger(m) || m < 1 || m > 600) return { error: 'Minutes must be a whole number from 1 to 600.', field: 'minutes' };
    if (!txt(f.title) && real) return { error: 'The step needs a title.', field: 'title' };
    if (real) { const steps = lines(f.instructions); if (!['setup', 'break'].includes(x.kindKey) && !steps.length) return { error: 'Write at least one instruction for the learner.', field: 'instructions' };
      Object.assign(x, { title: txt(f.title), goal: txt(f.goal), minutes: m, instructions: steps, learner: steps.map((t, i) => `${i + 1}. ${t}`).join('\n') || txt(f.goal), materials: lines(f.materials), handout: txt(f.handout), example: txt(f.example), guidance: lines(f.guidance), teacher: lines(f.guidance).join(' '), success: lines(f.success), origin: 'edited', editedAt: new Date().toISOString() });
      s.teacher.materials = [...new Set(s.activities.flatMap(y => y.materials || []))]; }
    else { if (!txt(f.learner)) return { error: 'Write what the learner does.', field: 'learner' }; Object.assign(x, { minutes: m, learner: txt(f.learner), teacher: txt(f.teacher), origin: 'edited', editedAt: new Date().toISOString() }); }
    s.minutes = s.activities.reduce((n, y) => n + y.minutes, 0);
  } else {
    if (!txt(f.title)) return { error: 'The session needs a title.', field: 'title' };
    if (real) { if (!txt(f.outcome)) return { error: 'The session needs an outcome.', field: 'outcome' };
      Object.assign(s, { title: txt(f.title), outcome: txt(f.outcome), aim: txt(f.outcome), successCriteria: lines(f.success), proof: lines(f.success).join(' '), applicationCheck: { when: txt(f.checkWhen), task: txt(f.checkTask), looksFor: lines(f.checkLooks) },
        prerequisites: lines(f.prerequisites).map(t => { const k = t.split(/\s+[—–-]{1,2}\s+|:\s+/); return { name: txt(k[0]), support: txt(k.slice(1).join(': ')) }; }) });
      if ('assumptions' in f) s.assumptions = lines(f.assumptions);
      if ('prepSteps' in f) { const m = Number(f.prep); if (!Number.isInteger(m) || m < 0 || m > 6000) return { error: 'Preparation minutes must be a whole number, 0 or more.', field: 'prep' }; s.teacher = Object.assign({}, s.teacher, { prepSteps: lines(f.prepSteps), prep: m }); } }
    else Object.assign(s, { title: txt(f.title), aim: txt(f.aim), proof: txt(f.proof) });
    s.origin = 'edited'; s.editedAt = new Date().toISOString();
  }
  s.review = null; // the person editing it has just looked at it
  const before = journey.sessions.find(x => x.id === edit.sessionId), same = JSON.stringify(Object.assign({}, before, { review: 0 })) === JSON.stringify(Object.assign({}, s, { review: 0, origin: before.origin, editedAt: before.editedAt, activities: s.activities.map((y, i) => Object.assign({}, y, { origin: (before.activities[i] || {}).origin, editedAt: (before.activities[i] || {}).editedAt })) }));
  if (same) return { same: true };
  const flagged = flagDependents(after, s.id, `It builds on “${s.title}”, which was edited.`);
  const was = J.audit(journey), problems = J.audit(after).filter(p => !was.includes(p));
  if (problems.length) return { error: problems[0] };
  return { after, flagged, target: edit.kind === 'activity' ? `Step in ${s.unit.toLowerCase()} ${after.sessions.indexOf(s) + 1}` : `${s.unit} ${after.sessions.indexOf(s) + 1}: ${s.title}`, plan: J.planOf(after) };
}

// A project's own words. Its files, milestones and rubric are not edited here. A change makes any review of the draft stale, because the review fingerprints the project.
function applyProject(journey, edit) {
  const p = (journey.projects || []).find(x => x.id === edit.projectId); if (!p || !p.content) return { error: 'That project is no longer in the draft.' };
  const f = edit.fields || {}, after = clone(journey), q = after.projects.find(x => x.id === edit.projectId), c = q.content;
  if (!txt(f.title)) return { error: 'The project needs a title.', field: 'title' };
  if (!txt(f.learner_brief)) return { error: 'The brief learners read cannot be empty.', field: 'learner_brief' };
  const deliverables = lines(f.deliverables); if (!deliverables.length) return { error: 'Say what learners hand in.', field: 'deliverables' };
  const next = { title: txt(f.title), purpose: txt(f.purpose), learner_brief: txt(f.learner_brief), deliverables, feedback_route: txt(f.feedback_route), revision_route: txt(f.revision_route), example_or_solution_guidance: txt(f.example_or_solution_guidance), teacher_guidance: lines(f.teacher_guidance) };
  if (JSON.stringify(Object.keys(next).map(k => c[k])) === JSON.stringify(Object.keys(next).map(k => next[k]))) return { same: true };
  Object.assign(c, next); q.origin = 'edited'; q.editedAt = new Date().toISOString();
  return { after, flagged: [], target: `Project ${q.id}: ${c.title}`, plan: J.planOf(after) };
}

// The course-level statements that come from the outline: how learners show the outcome, and what was assumed.
// Changing them rewrites no session. Every session is marked for a look, because each was written to the old statement.
function applyCourse(journey, edit) {
  if (!J.isReal(journey)) return { error: 'A simulated example has no course statement to edit.' };
  const after = clone(journey), f = edit.fields || {};
  if (!txt(f.finalEvidence)) return { error: 'Say how learners will show the outcome.', field: 'finalEvidence' };
  after.finalEvidence = txt(f.finalEvidence); after.assumptions = lines(f.courseAssumptions);
  if (after.finalEvidence === journey.finalEvidence && JSON.stringify(after.assumptions) === JSON.stringify(journey.assumptions || [])) return { same: true };
  after.courseEditedAt = new Date().toISOString();
  const flagged = [];
  if (after.finalEvidence !== journey.finalEvidence) for (const s of after.sessions) if (s.status === 'written' && !s.review) { s.review = { reason: 'The course statement “how learners will show it” was edited. Check this session still leads to it.', at: after.courseEditedAt, because: 'course' }; flagged.push(s.id); }
  return { after, flagged, target: 'Whole journey', plan: J.planOf(after) };
}

// A person can lower a claim from "fact". Raising a claim to "fact" is not offered: that needs a source a person has read.
export function retypeClaim(journey, sessionId, index, type) {
  if (!['uncertain', 'hypothesis'].includes(type)) return { error: 'A claim can be marked uncertain or as our judgement.' };
  const after = clone(journey), s = after.sessions.find(x => x.id === sessionId), c = s && (s.claims || [])[index]; if (!c) return { error: 'That claim is no longer in the draft.' };
  if (c.type === type) return { error: 'It already has that label.' };
  c.was = c.type; c.type = type; if (c.personChecked) c.checkWithdrawn = { was: c.personChecked.at, at: new Date().toISOString(), reason: 'The claim was relabelled after a person checked it.' }; c.personChecked = null; c.relabelledAt = new Date().toISOString(); if (type === 'hypothesis') c.support = 'not_from_source'; else if (c.support === 'stated_by_source') c.support = 'partly';
  return { after, target: `Claim in ${s.unit.toLowerCase()} ${after.sessions.indexOf(s) + 1}` };
}

/* ---------- a person's check of a claim does not survive a change to the claim ---------- */
// Called on every draft before it replaces the one before. Approved snapshots are never passed in, so they stay as they were.
// Returns how many checks were withdrawn. The draft given in is changed in place.
export function withdrawStaleChecks(before, after) {
  let n = 0; const same = (a, b) => txt(a.text) === txt(b.text) && a.type === b.type && (a.support || '') === (b.support || '') && JSON.stringify((a.sources || []).slice().sort()) === JSON.stringify((b.sources || []).slice().sort());
  for (const s of (after && after.sessions) || []) { const was = (((before && before.sessions) || []).find(x => x.id === s.id) || {}).claims || [];
    for (const c of s.claims || []) { if (!c.personChecked) continue;
      const old = was.filter(w => w.personChecked && w.personChecked.at === c.personChecked.at);
      const stale = c.personChecked.of ? c.personChecked.of !== J.claimPrint(c) : old.length > 0 && !old.some(w => same(w, c));
      if (stale) { c.checkWithdrawn = { was: c.personChecked.at, at: new Date().toISOString(), reason: 'The claim was changed after a person checked it.' }; c.personChecked = null; n++; } } }
  return n;
}
export function checkClaim(journey, sessionId, index) {
  const after = clone(journey), s = after.sessions.find(x => x.id === sessionId), c = s && (s.claims || [])[index]; if (!c) return { error: 'That claim is no longer in the draft.' };
  if (c.personChecked) c.personChecked = null; else { c.personChecked = { at: new Date().toISOString(), of: J.claimPrint(c) }; delete c.checkWithdrawn; }
  return { after, checked: !!c.personChecked, target: `Claim in ${s.unit.toLowerCase()} ${after.sessions.indexOf(s) + 1}` };
}

/* ---------- find and replace across the whole draft. No AI: the same words change everywhere, or nowhere. ---------- */
const SKIP = new Set(['id', 'key', 'origin', 'status', 'unit', 'kind', 'kindKey', 'internal', 'review', 'threads', 'buildsOn', 'minutes', 'editedAt', 'type', 'sources', 'was', 'relabelledAt', 'personChecked', 'checkWithdrawn', 'learner', 'teacher', 'failure', 'prep', 'assets', 'assetChecks', 'teachesNodes', 'teachesPlanned', 'practisesPlanned', 'independentPlanned']);
const PLACE = { title: 'title', outcome: 'outcome', aim: 'outcome', goal: 'goal', instructions: 'instructions', handout: 'handout', example: 'worked example', guidance: 'teacher guidance', misconceptions: 'misconceptions', success: 'success signs', materials: 'materials',
  successCriteria: 'success criteria', applicationCheck: 'later check', prerequisites: 'prerequisites', prerequisitesNote: 'prerequisites', assumptions: 'assumptions', claims: 'claims', contributions: 'topic contributions', prepSteps: 'preparation', proof: 'success criteria', why: 'why it is here', serves: 'why it is here', keyTask: 'planned task', setup: 'setup' };
function sweep(node, find, replace, place, hits, where) {
  if (typeof node === 'string') { const n = node.split(find).length - 1; if (n) hits.push({ where, place, count: n, was: around(node, find), now: around(node.split(find).join(replace), replace || find) }); return n ? node.split(find).join(replace) : node; }
  if (Array.isArray(node)) return node.map(x => sweep(x, find, replace, place, hits, where));
  if (node && typeof node === 'object') { const o = {}; for (const k in node) o[k] = SKIP.has(k) && !(k === 'teacher' && typeof node[k] === 'object') ? node[k] : sweep(node[k], find, replace, PLACE[k] || place, hits, where); return o; }
  return node;
}
const around = (text, word) => { const i = word ? text.indexOf(word) : 0, a = Math.max(0, i - 50), b = Math.min(text.length, i + word.length + 50); return (a ? '…' : '') + text.slice(a, b).replace(/\s+/g, ' ') + (b < text.length ? '…' : ''); };
// Returns the draft that would result and every place that changes. The draft given in is not touched.
export function replaceText(journey, find, replace) {
  find = String(find || ''); replace = String(replace ?? '');
  if (find.trim().length < 2) return { error: 'Type the exact words to find, at least two characters.', field: 'find' };
  if (find === replace) return { error: 'The replacement is the same as the words to find.', field: 'replace' };
  if (!J.isReal(journey)) return { error: 'Find and replace works on content written with Claude.' };
  const after = clone(journey), hits = [];
  after.sessions = after.sessions.map((s, i) => { if (s.status !== 'written') return s; const mine = [], n = sweep(s, find, replace, 'session', mine, `${s.unit} ${i + 1}`); if (!mine.length) return s;
    n.activities.forEach(x => { x.learner = (x.instructions || []).map((t, k) => `${k + 1}. ${t}`).join('\n') || x.goal; x.teacher = (x.guidance || []).join(' '); });
    n.teacher.materials = [...new Set(n.activities.flatMap(y => y.materials || []))]; n.origin = 'edited'; n.editedAt = new Date().toISOString(); n.review = null; hits.push(...mine); return n; });
  for (const k of ['finalEvidence', 'courseOutcome']) if (typeof after[k] === 'string') after[k] = sweep(after[k], find, replace, k === 'finalEvidence' ? 'how learners show it' : 'course outcome', hits, 'Whole course');
  after.assumptions = sweep(after.assumptions || [], find, replace, 'assumptions', hits, 'Whole course');
  if (!hits.length) return { none: true, hits };
  const withdrawn = withdrawStaleChecks(journey, after);
  const was = J.audit(journey), problems = J.audit(after).filter(p => !was.includes(p)); if (problems.length) return { error: problems[0] };
  return { after, hits, withdrawn, total: hits.reduce((n, h) => n + h.count, 0), target: 'Whole journey', plan: J.planOf(after) };
}

/* ---------- a plain word check against the brief. No AI. It can be wrong, so it only ever asks for a look. ---------- */
const THINGS = { table: /\b(tables?|desks?)\b/i, stapler: /\bstapl(er|ers|e|ed|ing)\b/i, tape: /\b(sticky |masking |adhesive )?tape\b/i, glue: /\bglue\b/i, scissors: /\bscissors\b/i, projector: /\b(projector|slide deck|slideshow|screen share)\b/i,
  laptop: /\b(laptops?|computers?)\b/i, phone: /\b(phones?|smartphones?|tablets?)\b/i, whiteboard: /\b(whiteboards?|flip ?charts?)\b/i, timer: /\b(timer|stopwatch)\b/i, pen: /\b(pens?|pencils?|biros?)\b/i, internet: /\b(wi-?fi|internet|online)\b/i };
const DEVICES = ['laptop', 'phone', 'projector', 'internet'];
// A sentence that rules the thing out, or only compares with it, is not a use of it.
const NOT = /\b(no|not|never|without|instead of|rather than|cannot|than on|nor|neither)\b[^.;!?]*$/i;
export function outsideBrief(j) {
  if (!J.isReal(j)) return [];
  const req = ((j.sessions[0] || {}).teacher || {}).requirements || [], rules = req.map(r => String(r).replace(J.REQ, ''));
  const closed = rules.filter(r => /^\s*(only|nothing but|just)\b/i.test(r)).map(r => r.replace(/^Only this is available in the room:/i, '')), // a list that starts “Only …” is complete
    noDevices = rules.some(r => /no devices|with no devices|on paper/i.test(r));
  if (!closed.length && !noDevices) return [];
  const allowed = closed.join(' ').toLowerCase(), found = {};
  j.sessions.forEach((s, i) => {
    const texts = [...(s.teacher.prepSteps || []), ...(s.teacher.materials || []), ...(s.assumptions || []), ...s.activities.flatMap(x => [...(x.instructions || []), ...(x.materials || []), x.handout || '', x.example || '', ...(x.guidance || [])])];
    for (const name in THINGS) {
      const banned = (closed.length && !THINGS[name].test(allowed)) || (noDevices && DEVICES.includes(name)); if (!banned) continue;
      for (const text of texts) for (const sentence of String(text).split(/(?<=[.!?\n])\s+/)) {
        const m = THINGS[name].exec(sentence); if (!m || NOT.test(sentence.slice(0, m.index))) continue;
        (found[name] = found[name] || { name, sessions: new Set(), count: 0, example: sentence.trim().slice(0, 140) }).sessions.add(i + 1); found[name].count++; break;
      }
    }
  });
  return Object.values(found).map(f => ({ name: f.name, sessions: [...f.sessions], count: f.count, example: f.example }));
}

/* ---------- what is still to do before approval ---------- */
export function readiness(j) {
  const must = J.audit(j), look = [];
  if (!J.isReal(j)) return { must, look, pending: (j.sessions[0].teacher.requirements || []).length };
  for (const s of j.sessions) {
    if (s.review) look.push(`“${s.title}”: ${s.review.reason}`);
    for (const c of s.contributions || []) if (/^weak\b/i.test(c.gives)) look.push(`“${s.title}”: ${c.topic} may not belong here. ${c.gives}`);
    for (const c of s.claims || []) if (c.type === 'fact' && !(c.sources || []).length) look.push(`“${s.title}”: stated as fact with no source: ${c.text}`);
    const thin = (s.claims || []).filter(c => J.thinFact(c, j)).length;
    if (thin) look.push(`“${s.title}”: ${thin} claim${thin > 1 ? 's are' : ' is'} called a fact although the source is recorded as supporting ${thin > 1 ? 'them' : 'it'} only in part.`);
  }
  if (j.integration && ['not_justified', 'partly'].includes(j.integration.status)) look.push(`Topic combination is ${j.integration.status === 'partly' ? 'only partly justified' : 'not justified'}: ${j.integration.reason}`);
  if (j.feasibility && j.feasibility.fits === false) look.push('May not fit the time. Claude judged that the outcome cannot be fully reached in the time given. Read “Will it fit the time?” on the checks screen.');
  for (const o of outsideBrief(j)) look.push(`Word check: “${o.name}” appears in ${o.sessions.length > 1 ? 'sessions' : 'session'} ${o.sessions.join(', ')}, and the brief’s list of what is available does not include it. For example: “${o.example}”`);
  if (j.pipeline === 2) look.push(...J.v2Open(j));
  const unchecked = (j.sources || []).filter(s => !s.personChecked).length;
  if (unchecked) look.push(`${unchecked} of ${(j.sources || []).length} sources have not been read by a person.`);
  if ((j.review && j.review.output ? j.review.output.findings : []).some(f => f.severity === 'must_fix')) look.push('The independent review lists problems marked “must fix”.');
  if (j.review && j.review.rev !== j.rev) look.push('The independent review was made on an earlier draft.');
  return { must, look, pending: (j.sessions[0].teacher.requirements || []).length };
}


// What each separate reviewer said, with the fingerprint of what it read, copied from the generation record. Only the output that matters is kept.
export function agentsFrom(E, outlineEdited) {
  const st = E.stages, out = {}, f = st.foundation_review, sr = st.source_review, ol = st.outline_review;
  if (f && f.output) out.foundations = { output: clone(f.output), added: clone(f.addedNodes || []), rejected: clone(f.rejectedAdditions || []), fingerprint: f.inputFingerprint || '', requestId: f.requestId || '', finishedAt: f.finishedAt || '', model: f.model || '' };
  if (sr && (sr.rounds || []).length) { const last = sr.rounds[sr.rounds.length - 1]; out.sources = { output: clone(last.output), rounds: sr.rounds.length, fingerprint: last.inputFingerprint || '', requestId: last.requestId || '', finishedAt: last.finishedAt || '', model: last.model || '' }; }
  if (ol && ol.output) out.outline = { output: clone(ol.output), rounds: (ol.rounds || []).length, fingerprint: ol.inputFingerprint || '', requestId: ol.requestId || '', finishedAt: ol.finishedAt || '', model: (ol.rounds || [{}]).slice(-1)[0].model || '' };
  return out;
}

// Evidence gathered after the draft was made (Loom's own retrieval, the attribution review) is copied onto the draft's sources.
// A person's own check of a source is never touched. Returns how many sources changed.
const EVIDENCE_KEYS = ['evidenceLevel', 'directRetrieval', 'directExcerpt', 'sourceReview', 'originalSource', 'attribution', 'strength', 'limits', 'auditUnresolved', 'quoteFound', 'quote', 'authors', 'published', 'version_or_edition', 'identifier', 'role', 'lineage'];
export function mergeEvidence(journey, record) {
  if (!journey || !J.isReal(journey) || !record || !record.stages || !record.stages.research || !record.stages.research.output) return 0;
  let n = 0; const fresh = record.stages.research.output.sources || [];
  for (const s of journey.sources || []) {
    const f = fresh.find(x => x.id === s.id && x.url === s.url && x.claim === s.claim); if (!f) continue;
    const before = JSON.stringify(EVIDENCE_KEYS.map(k => s[k]));
    for (const k of EVIDENCE_KEYS) if (f[k] !== undefined) s[k] = clone(f[k]);
    if (JSON.stringify(EVIDENCE_KEYS.map(k => s[k])) !== before) n++;
  }
  return n;
}

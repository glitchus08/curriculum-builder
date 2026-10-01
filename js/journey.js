// Glitch Loom — SIMULATED journey builder.
// No AI runs here. A proposed journey is assembled from the brief by fixed rules,
// so the example reflects what was entered. Nothing in it has been researched or verified,
// and nothing here establishes that the course would teach well.

import { topicsOf, usesWeeks, ownMinutes, timeOptions, parseDuration, parseHours, fmtMin, MAX_WEEKS, MIN_MINUTES, CUSTOM, byId, labelOf, patternOptions, parsePattern } from './flow.js';
export { fmtMin, MAX_WEEKS, MIN_MINUTES };

const clone = o => JSON.parse(JSON.stringify(o));
const r5 = m => Math.max(5, Math.round(m / 5) * 5);
export const listNames = l => l.length < 2 ? String(l[0] ?? '') : l.slice(0, -1).join(', ') + ' and ' + l[l.length - 1];
let uid = 0; const newId = p => p + Date.now().toString(36) + (uid++);
const SIM = 'Simulated draft. No sources were checked and no claim is verified.';
export const WRITER = 'Request for the writer';
const WMARK = WRITER.toLowerCase() + ': “'; // the exact shape of a stored request, so ordinary sentences are never mistaken for one

// Split a total into n whole-minute parts that add up EXACTLY to the total.
// Parts are multiples of 5 where the total allows it; any odd minutes go to the last part.
export function splitExact(total, n, weights) {
  n = Math.max(1, n); weights = weights || Array(n).fill(1);
  if (total < 5 * n) { const out = Array(n).fill(Math.floor(total / n)); out[n - 1] += total - out.reduce((s, x) => s + x, 0); return out; }
  const out = Array(n).fill(5), sum = weights.reduce((s, w) => s + w, 0); let left = total - 5 * n;
  weights.forEach((w, i) => { const add = Math.floor(left * w / sum / 5) * 5; out[i] += add; });
  left = total - out.reduce((s, x) => s + x, 0);
  for (let i = n - 1; left >= 5; i = (i - 1 + n) % n) { out[i] += 5; left -= 5; }
  out[n - 1] += left; return out;
}

// What the brief asks for, read exactly. Nothing is rounded, capped or guessed.
// A weekly pattern may be written for one week ("2 x 60 minutes") or for the whole run ("8 x 60 minutes" over 4 weeks).
// Either is read; anything that does not add up to the week, or to the run in whole weeks, is an error.
export function weeklyPattern(a, weeks, per) {
  const pat = a.pattern ? a.pattern.value : undefined;
  if (!pat || pat === 'auto') return { chosen: null };
  if (pat !== CUSTOM) { const o = patternOptions(a).find(x => x[0] === pat); return { chosen: o ? { n: o[2], per: o[3] } : null }; }
  const text = (a.pattern || {}).text, week = parsePattern(text, per, true);
  if (!week.error) return { chosen: week };
  const run = parsePattern(text, weeks * per, false);
  if (!run.error && run.n % weeks === 0) return { chosen: { n: run.n / weeks, per: run.per } };
  if (!run.error) return { chosen: null, error: `${run.n} meetings do not divide evenly across ${weeks} weeks. Write it for one week, like 2 x ${fmtMin(per / 2)}, or as a number of meetings that ${weeks} divides.` };
  return { chosen: null, error: week.error };
}
// What the brief holds, with live and independent hours each counted once.
export function accountingOf(plan) {
  const live = plan.total || 0, own = plan.independent ? plan.independent.totalMinutes : 0, h = m => (m % 60 ? +(m / 60).toFixed(2) : m / 60) + ' h';
  return { live, own, combined: live + own, statement: own ? `${h(live)} live + ${h(own)} independent = ${h(live + own)}. Each hour is counted once.` : `${h(live)} in all.` };
}
export function request(a) {
  const f = a.format ? a.format.value : 'course', t = a.time || {};
  if (usesWeeks(a)) {
    let weeks = null; if (t.value === CUSTOM) { const d = parseDuration(t.text); weeks = d.weeks || null; } else { const o = timeOptions(a).find(x => x[0] === t.value); weeks = o ? o[2] : null; }
    let per = null; if (a.hours) { const d = a.hours.value === CUSTOM ? parseHours(a.hours.text) : parseHours(String(a.hours.value)); per = d.error ? null : d.minutes; }
    // The team may say how the week's hours are met: several shorter meetings, not one. Loom uses that exactly.
    const chosen = weeks && per ? weeklyPattern(a, weeks, per).chosen : null;
    const k = chosen ? chosen.n : 1, each = chosen ? chosen.per : per, own = a.split ? labelOf(byId('split'), a) : '';
    const ownPer = ownMinutes(a), independent = weeks && ownPer ? { perWeekMinutes: ownPer, weeks, totalMinutes: weeks * ownPer } : null;
    const cadence = weeks && per ? (k > 1 ? `${k} meetings each week, ${fmtMin(each)} each` : `one meeting each week, ${fmtMin(per)}`) + (own ? `; ${own.charAt(0).toLowerCase() + own.slice(1)}` : '') : '';
    return { weekly: true, weeks, per: each, perWeek: per, meetingsPerWeek: k, cadence, n: weeks && k ? weeks * k : weeks, total: weeks && per ? weeks * per : null, unit: k > 1 ? 'Meeting' : 'Week', setByTeam: !!chosen, independent,
      span: weeks && per ? `${weeks} week${weeks > 1 ? 's' : ''}, ${fmtMin(per)} each week${k > 1 ? ` as ${k} meetings of ${fmtMin(each)}` : ''}${independent ? `, plus ${fmtMin(ownPer)} of independent work each week` : ''}` : '' };
  }
  let total = null; if (t.value === CUSTOM) { const d = parseDuration(t.text); total = d.minutes || null; } else { const o = (timeOptions(a) || []).find(x => x[0] === t.value); total = o ? o[2] : null; }
  if (total == null) return { weekly: false, total: null, n: null, unit: 'Block', span: '' };
  // The team may set the pattern themselves. Loom only works it out when they leave it to Loom.
  const pat = a.pattern ? a.pattern.value : undefined;
  let chosen = null;
  if (pat && pat !== 'auto') {
    if (pat === CUSTOM) { const r = parsePattern((a.pattern || {}).text, total); if (!r.error) chosen = r; }
    else { const o = patternOptions(a).find(x => x[0] === pat); if (o) chosen = { n: o[2], per: o[3] }; }
  }
  let n = chosen ? chosen.n : f === 'talk' ? (total <= 20 ? 2 : 3) : f === 'clinic' ? (total <= 60 ? 2 : total <= 120 ? 3 : 4) : total <= 180 ? 3 : total <= 360 ? 5 : 8;
  n = Math.max(1, Math.min(n, Math.floor(total / 5)));
  if (chosen) return { weekly: false, total, n, per: chosen.per, setByTeam: true, unit: f === 'talk' ? 'Part' : 'Block',
    span: `${labelOf(byId('time'), a)}${/\(/.test(labelOf(byId('time'), a)) ? '' : ` (${fmtMin(total)})`}, as ${n} meeting${n > 1 ? 's' : ''} of ${fmtMin(chosen.per)}` };
  return { weekly: false, total, n, unit: f === 'talk' ? 'Part' : f === 'clinic' && t.value === 'cweek' ? 'Week' : 'Block', span: t.value === CUSTOM ? `${String(t.text).trim()} (${fmtMin(total)})` : `${labelOf(byId('time'), a)} (${fmtMin(total)})` };
}

// Things the brief asks for that cannot all be true at once. Loom never resolves these silently.
export function conflicts(a) {
  const out = [], rq = request(a), tp = topicsOf(a), k = tp.list.length, unit = rq.unit.toLowerCase();
  if (rq.weekly && rq.weeks > MAX_WEEKS) out.push({ id: 'long', text: `You asked for ${rq.weeks} weeks. Loom plans up to ${MAX_WEEKS} weeks in one programme.`, choices: [{ label: 'Change the length', edit: 'time' }] });
  if (!rq.weekly && rq.total != null && rq.total < MIN_MINUTES) out.push({ id: 'short', text: `${rq.total} minutes is too short to plan. The shortest Loom plans is ${MIN_MINUTES} minutes.`, choices: [{ label: 'Change the length', edit: 'time' }] });
  if (a.pattern && a.pattern.value === CUSTOM && (rq.weekly ? rq.perWeek : rq.total) != null) {
    const r = rq.weekly ? weeklyPattern(a, rq.weeks, rq.perWeek) : parsePattern(a.pattern.text, rq.total);
    if (r.error) out.push({ id: 'pattern', text: r.error, choices: [{ label: 'Change the meetings', edit: 'pattern' }, { label: 'Change the length', edit: 'time' }] });
  }
  if (tp.mode === 'separate' && rq.n != null && k > rq.n && !out.length) out.push({ id: 'fit', text: `${k} separate topics need at least ${k} ${unit}s. ${rq.span} gives ${rq.n}.`, choices: [{ label: 'Add time', edit: 'time' }, { label: 'Choose fewer topics', edit: 'mix' }, { label: 'Let topics share sessions', edit: 'mode' }] });
  return out;
}

const ORDER = ['hook', 'found', 'make', 'connect', 'sort', 'test', 'improve', 'apply', 'show'];
function arc(n, o) {
  let pri = (o.prior === 'new' || o.prior === 'unsure') ? ['hook', 'found', 'make', 'show', 'test', 'improve', 'apply'] : o.prior === 'solid' ? ['hook', 'make', 'show', 'test', 'apply', 'improve', 'found'] : ['hook', 'make', 'show', 'found', 'test', 'apply', 'improve'];
  // When topics share a course, the joining task is never optional: it comes first in priority.
  if (o.mix && o.mode !== 'separate') pri.unshift('connect');
  if (o.world) pri.splice(2, 0, 'sort');
  const chosen = pri.slice(0, n); let list = ORDER.filter(k => chosen.includes(k)), s = 1;
  while (list.length < n) { list.splice(Math.max(1, list.length - 1), 0, 'studio' + s); s++; }
  return list;
}

function template(key, c) {
  const t = c.t, A = c.A, B = c.B;
  const base = {
    hook: [`First try at ${t}`, `Attempt a real ${t} task before any teaching, and notice what is hard.`, `A first attempt and one question you want answered.`, `A first attempt gives the later explanation something to build on.`],
    found: [`The ideas underneath ${t}`, `Name the ideas that ${t} rests on, and use each one once.`, `Each idea used in a small example of your own.`, `Learners in this group need the foundations before they can make anything.`],
    make: [`Make a small first version`, `Build the smallest thing that shows ${t} working.`, `A working first version, however rough.`, `The outcome asks for something made, so making starts early.`],
    connect: [`Where ${c.all} meet`, `Finish one task that needs ${c.every}.`, `One piece of work that would fail if any one topic were left out.`, `Topics are only joined when one task needs all of them. This session is worded as that task. It is a simulated example and nobody has checked it.`],
    sort: [`Fact, guess or fiction?`, `Sort claims about ${t} from ${c.world} into real knowledge, reasoned guess and pure story.`, `A sorted list with a reason for each item.`, `A fictional world is inspiration only, so learners must separate it from fact.`],
    test: [`Test it on a real person`, `Watch someone use or read your ${t} work without helping them.`, `Notes on what they did, in their own words.`, `Testing shows whether the work does its job for someone else.`],
    improve: [`Fix what the test showed`, `Change one thing in your ${t} work that the test revealed, then test again.`, `A before and after, with the reason for the change.`, `Repairing is where most of the understanding forms.`],
    apply: [`Use it somewhere new`, `Use ${t} on a problem you have not seen before.`, `A solution to the new problem, with what you reused.`, `Transfer to a new situation is the real proof of learning.`],
    show: [`Show and explain`, `Present your ${t} work and explain two decisions you made.`, `A short walkthrough that someone else can follow.`, `Explaining decisions shows what is understood and what was copied.`]
  };
  if (key.startsWith('studio')) return [`Studio time ${key.slice(6)}`, `Keep building your ${t} work toward the outcome, with help when stuck.`, `Visible progress since the last session.`, `Longer programmes need protected making time.`];
  return base[key];
}


const DO = { hook: 'Write down what was hard, and one question you want answered.', found: 'Use each idea once in a small example of your own.', make: 'Build the smallest version that works.', connect: 'Finish the task that needs every topic.', sort: 'Sort the claims and give a reason for each.', test: 'Watch someone use your work. Do not help them.', improve: 'Change one thing, then test again.', apply: 'Solve the new problem and note what you reused.', show: 'Present your work and explain two decisions.', studio: 'Keep building. Ask for help when stuck.' };
const HOW = { live: 'in breakout pairs', room: 'in pairs at a table', self: 'on your own, then share a note or photo', blended: 'started alone beforehand, finished together', hybrid: 'in pairs, matching someone in the room with someone online where you can' };
const SETUP = { live: 'Open the shared board and set up breakout pairs.', self: 'Post the task and the place to share work.', room: 'Seat learners in pairs with materials face down.', blended: 'Post the solo task beforehand. For the session, seat learners in pairs.', hybrid: 'Test the room microphone and camera. Give online learners the same task sheet at the same moment. Ask one person to watch the chat.' };
// Steps inside one session. Their minutes always add up to exactly `mins`.
function activities(key, mins, c, first) {
  const how = HOW[c.delivery] || 'in pairs', gentle = c.prior === 'new' && c.audience === 'school';
  const A0 = gentle ? { kind: 'Watch, then try', learner: `Watch one worked example of ${c.t}, then try a similar one ${how}.`, teacher: `Starts with an example because these learners are new and young. This is a rule in the prototype, not a checked decision. Keep the example under five minutes.` }
    : { kind: 'Try', learner: `Have a go first, ${how}. Getting it wrong is expected.`, teacher: `Do not explain yet. Collect two or three attempts to use in the next step.` };
  const A1 = { kind: 'Explain', learner: `Compare the attempts and name what worked and why.`, teacher: `Build the explanation from what learners actually made.` };
  const A2 = { kind: key === 'apply' || key === 'test' || key === 'show' ? 'Apply' : 'Make', learner: DO[key.startsWith('studio') ? 'studio' : key], teacher: `Walk around. Help with questions, not answers.` };
  const wantEntry = first && c.prior === 'unsure', e = !wantEntry ? 0 : mins >= 30 ? 10 : mins >= 15 ? 5 : 0, body = mins - e;
  const list = body >= 20 ? [A0, A1, A2] : body >= 10 ? [A0, A2] : [A2], w = body >= 20 ? [.25, .3, .45] : body >= 10 ? [.4, .6] : [1];
  const m = splitExact(body, list.length, w), out = list.map((x, i) => Object.assign({ minutes: m[i] }, x));
  if (e) out.unshift({ kind: 'Entry check', minutes: e, learner: `A ${e}-minute task that shows where you are starting from. It is not graded.`, teacher: `Use the results to decide who needs extra help.` });
  else if (wantEntry) out[0].teacher = 'There is no time for a separate entry check. Ask for a show of hands in the first minute. ' + out[0].teacher;
  return out.map((x, i) => ({ id: 'a' + (i + 1), kind: x.kind, minutes: x.minutes, learner: x.learner, teacher: x.teacher, internal: [] }));
}

// Constraints are stored as requirements. Nothing in the simulated text has been made to satisfy them yet.
const NEED = { reader: 'all text must work with a screen reader', vision: 'large print and strong contrast', hearing: 'captions or written instructions for anything spoken', motor: 'no task may need fine hand control', load: 'short steps, one instruction at a time' };
export const REQ = 'Requirement to implement: ';
export const requirementsOf = a => requirements(a, (a.limits && a.limits.value) || []);
function requirements(a, lim) {
  const out = [];
  if (lim.includes('phones')) out.push('every task must work on a phone');
  if (lim.includes('laptops')) out.push('tasks may assume a laptop for each learner or pair');
  if (lim.includes('nodevice')) out.push('every task must work on paper, with no devices');
  if (lim.includes('lowweb')) out.push('all materials must be available to download in advance');
  if (lim.includes('free')) out.push('free tools only, with no paid apps, licences or accounts');
  if (lim.includes('language') && a.language && a.language.value) out.push(`all materials in ${String(a.language.value).trim()}`);
  if (lim.includes('access') && a.access && a.access.value) for (const v of a.access.value) { const t = v === CUSTOM ? String(a.access.text || '').trim() : NEED[v]; if (t) out.push(t); }
  if (lim.includes('room') && a.room && a.room.value) out.push('Only this is available in the room: ' + String(a.room.value).trim().replace(/\.$/, ''));
  if (lim.includes(CUSTOM) && a.limits.text) out.push(String(a.limits.text).trim());
  return out.map(t => REQ + t);
}

export function makeJourney(a) {
  const tp = topicsOf(a), names = tp.list.length ? tp.list : ['the topic'], rq = request(a), cf = conflicts(a);
  if (rq.total == null || !rq.n) throw new Error('The brief has no readable length yet.');
  if (cf.length) throw new Error(cf[0].text);
  const mins = rq.weekly || rq.setByTeam ? Array(rq.n).fill(rq.per) : splitExact(rq.total, rq.n);
  const lim = (a.limits && a.limits.value) || [], k = names.length, mix = k > 1, mode = mix ? (tp.mode || 'shared') : null, sep = mode === 'separate', linked = mode === 'linked';
  const every = k === 2 ? `both ${names[0]} and ${names[1]}` : `all of ${listNames(names)}`;
  const c = { t: listNames(names), all: listNames(names), every, world: tp.world, prior: a.prior && a.prior.value, audience: a.audience && a.audience.value, delivery: a.delivery && a.delivery.value };
  let keys = [];
  if (sep) { const base = Math.floor(rq.n / k), extra = rq.n % k; names.forEach((nm, ti) => arc(base + (ti < extra ? 1 : 0), { prior: c.prior }).forEach(key => keys.push({ k: key, ti }))); }
  else { keys = (mix && rq.n === 1 ? ['connect'] : arc(rq.n, { prior: c.prior, mix, mode, world: !!tp.world })).map(key => ({ k: key })); if (linked) { let turn = 0; keys.forEach(o => { if (o.k !== 'connect' && o.k !== 'show') o.ti = turn++ % k; }); } }
  const req = requirements(a, lim), mat = lim.includes('nodevice') ? ['Paper and pens', 'Printed task sheet'] : lim.includes('phones') ? ['One phone for each pair', 'Task sheet'] : ['Task sheet', 'A way to share work with the group'];
  const sessions = keys.map((o, i) => {
    const own = o.ti != null, cc = own ? Object.assign({}, c, { t: names[o.ti] }) : c, tm = template(o.k, cc);
    const acts = activities(o.k, mins[i], cc, i === 0);
    return { id: 's' + (i + 1), key: o.k, unit: rq.unit, title: (own && mix ? names[o.ti] + ': ' : '') + tm[0], aim: tm[1], proof: tm[2], why: tm[3], threads: own ? [o.ti] : names.map((_, j) => j), minutes: mins[i], activities: acts,
      teacher: { materials: mat.slice(), requirements: req.slice(), setup: SETUP[c.delivery] || SETUP.room, prep: 15 + acts.length * 5 }, internal: [SIM],
      // What each topic is here for. Fixed wording, like the rest of the simulation, so it is never mistaken for a judgement.
      contributions: !mix ? [] : (own ? [o.ti] : names.map((_, x) => x)).map(x => ({ topic: names[x], gives: own ? `This session works on ${names[x]} on its own. Simulated: nobody has checked it.` : `${names[x]} supplies part of the one task this session sets. Simulated: nobody has checked that the task needs it.` })) };
  });
  // A course taught in one sitting and long enough to need a break gets one, taken out of the time already
  // planned rather than added to it, as a generated plan does. Weekly courses have the gap between sessions.
  if (!rq.weekly && rq.total >= 120) {
    const mid = sessions[Math.floor(sessions.length / 2)] || sessions[0], BR = 10;
    const big = mid.activities.reduce((a, b) => (b.minutes > a.minutes ? b : a), mid.activities[0]);
    if (big && big.minutes > BR + 4) {
      big.minutes -= BR;
      mid.activities.splice(mid.activities.indexOf(big) + 1, 0, { id: 'a' + (mid.activities.length + 1), kind: 'Break', minutes: BR,
        learner: `A ${BR}-minute break. Nothing is set to do.`, teacher: `Say the time the room restarts and write it up. This break is inside the ${mid.minutes} minutes, not added to them.`, internal: [] });
    }
  }
  const connections = [], joint = sessions.find(s => s.key === 'connect');
  if (sep) connections.push({ names: names.slice(), type: 'Kept separate', why: 'You chose to keep them separate. No session combines them, and Loom claims no link between them.' });
  else if (mix && joint) connections.push({ names: names.slice(), type: linked ? 'Linked chapters' : 'Used together', session: joint.id, why: `“${joint.title}” is worded as one task that needs ${every}. This is a simulated example. Nobody has checked that such a task works in practice.` });
  else if (mix) connections.push({ names: names.slice(), type: 'Not established', why: 'This plan has no task that joins the topics. The simulation has not established any connection between them.' });
  const sorter = sessions.find(s => s.key === 'sort');
  if (tp.world) connections.push(sorter ? { names: [tp.world, names[0]], type: 'Inspiration only', session: sorter.id, why: `“${sorter.title}” asks learners to separate fact, guess and fiction. No characters, art or text are reproduced, and no permission is implied.` }
    : { names: [tp.world, names[0]], type: 'Inspiration only', why: `This plan is too short for a session that separates fact from fiction, so ${tp.world} is not used in any session. It is recorded as inspiration only. No permission is implied.` });
  const has = key => sessions.find(s => s.key === key);
  if (!mix && has('found') && has('make')) connections.push({ names: [has('found').title, has('make').title], type: 'Order', why: 'The plan puts the ideas before the making. This order is a rule in the prototype, not a checked prerequisite.' });
  if (!mix && has('make') && has('test')) connections.push({ names: [has('make').title, has('test').title], type: 'Order', why: 'There is nothing to test until a first version exists.' });
  const j = { rev: 0, uid: newId('j'), origin: 'simulated', outcome: (a.outcome && a.outcome.value) || '', topics: names, world: tp.world, mode, format: labelOf(byId('format'), a), audience: labelOf(byId('audience'), a), delivery: labelOf(byId('delivery'), a),
    span: rq.span, budget: rq.total, requested: { span: rq.span, minutes: rq.total, sessions: rq.n, unit: rq.unit, weekly: rq.weekly }, sessions, connections, internal: [], madeAt: new Date().toISOString() };
  const bad = audit(j); if (bad.length) throw new Error('The simulated plan failed its own checks: ' + bad[0]);
  return j;
}
export const totalMin = j => j.sessions.reduce((s, x) => s + x.minutes, 0);

// What is planned NOW, kept apart from what the brief asked for.
export function planOf(j) {
  const rq = j.requested || { span: j.span, minutes: j.budget, sessions: j.sessions.length, unit: j.sessions[0].unit, weekly: j.sessions[0].unit === 'Week' };
  const minutes = totalMin(j), n = j.sessions.length, unit = rq.unit, notes = [];
  if (minutes > rq.minutes) notes.push(`${fmtMin(minutes - rq.minutes)} more than the brief asked for`);
  if (minutes < rq.minutes) notes.push(`${fmtMin(rq.minutes - minutes)} less than the brief asked for`);
  if (n !== rq.sessions) notes.push(`${n} ${unit.toLowerCase()}${n > 1 ? 's' : ''} planned, the brief gives ${rq.sessions}`);
  return { minutes, sessions: n, unit, label: `${fmtMin(minutes)} in ${n} ${unit.toLowerCase()}${n > 1 ? 's' : ''}`, requested: rq, differs: notes.length > 0, notes };
}

// Invariants that must hold after generation AND after every edit. Returns a list of plain problems; empty means none found.
// These check internal consistency only. They say nothing about whether the course would teach well.
export const isReal = j => !!j && j.origin === 'claude';
export const unwritten = j => [...j.sessions, ...(j.projects || [])].filter(s => s.status === 'pending' || s.status === 'failed');
export function audit(j) {
  const out = [], real = isReal(j), low = s => String(s).toLowerCase();
  const text = s => low([s.title, s.aim, s.proof, ...s.activities.map(x => x.learner)].join(' '));
  const gives = (s, name) => (s.contributions || []).some(c => low(c.topic) === low(name) && String(c.gives || '').trim());
  if (!j.sessions.length) out.push('The plan has no sessions.');
  for (const s of j.sessions) {
    if (j.mode === 'separate' && s.threads.length > 1) out.push(`“${s.title}” combines topics, but the brief keeps them separate.`);
    if (s.status === 'pending' || s.status === 'failed') { out.push(`“${s.title}” has not been written yet.`); continue; }
    const sum = s.activities.reduce((n, x) => n + x.minutes, 0);
    if (sum !== s.minutes) out.push(`Steps in “${s.title}” add up to ${sum}, not ${s.minutes}.`);
    if (!(s.minutes > 0) || s.activities.some(x => !(x.minutes > 0) || !Number.isInteger(x.minutes))) out.push(`“${s.title}” has a step without a whole number of minutes.`);
    for (const x of s.activities) if ([x.teacher, x.learner, x.goal, x.handout, x.example, ...(x.instructions || []), ...(x.guidance || [])].some(t => low(t || '').includes(WMARK))) out.push(`A writer request sits in released text in “${s.title}”.`);
    if (!real) { for (const t of s.threads) if (!text(s).includes(low(j.topics[t]))) out.push(`“${s.title}” is tagged ${j.topics[t]} but never mentions it.`); continue; }
    // Written with Claude: a topic tag needs a stated contribution, and the parts a teacher relies on must all be there.
    if (s.threads.length > 1) for (const t of s.threads) if (!gives(s, j.topics[t])) out.push(`“${s.title}” is tagged ${j.topics[t]} but does not say what ${j.topics[t]} contributes.`);
    if (!String(s.outcome || '').trim()) out.push(`“${s.title}” has no outcome.`);
    if ((s.successCriteria || []).filter(c => String(c).trim()).length < 2) out.push(`“${s.title}” needs at least two success criteria.`);
    if (!s.applicationCheck || !String(s.applicationCheck.task || '').trim()) out.push(`“${s.title}” has no later check that learners can do this alone.`);
    const kinds = s.activities.map(x => x.kindKey);
    if (!kinds.includes('feedback') || !kinds.includes('revise')) out.push(`“${s.title}” needs a feedback step and a revision step.`);
    if (!s.activities.some(x => ['try', 'make', 'apply'].includes(x.kindKey))) out.push(`“${s.title}” has no step where learners do the task themselves.`);
    for (const x of s.activities) if (!['setup', 'break'].includes(x.kindKey) && (x.instructions || []).filter(t => String(t).trim()).length < 1) out.push(`“${x.title}” in “${s.title}” has no instructions.`);
    const ids = new Set((j.sources || []).map(x => x.id));
    for (const c of s.claims || []) for (const id of c.sources || []) if (!ids.has(id)) out.push(`A claim in “${s.title}” cites ${id}, which is not among the sources.`);
  }
  for (const x of j.projects || []) if (x.status === 'pending' || x.status === 'failed') out.push(`Project “${(x.outline || {}).title || x.id}” has not been written yet.`);
  j.topics.forEach((t, i) => { if (!j.sessions.some(s => s.threads.includes(i) && (real || text(s).includes(low(t))))) out.push(`No session teaches “${t}”.`); });
  for (const c of j.connections) if (c.type === 'Inspiration only' && c.session) { const s = j.sessions.find(x => x.id === c.session); if (!s) out.push('The fiction-world note points at a session that does not exist.'); else if (!real && !text(s).includes(low(c.names[0]))) out.push(`“${s.title}” is said to use ${c.names[0]} but never mentions it.`); }
  for (const c of j.connections) if (c.type === 'Used together' || c.type === 'Linked chapters') {
    const s = j.sessions.find(x => x.id === c.session); if (!s) { out.push('A topic connection points at a session that does not exist.'); continue; }
    if (real) { if (s.status !== 'pending' && s.status !== 'failed') for (const n of c.names) if (!gives(s, n)) out.push(`A connection claims “${s.title}” joins ${n}, but the session does not say what ${n} contributes.`); }
    else for (const n of c.names) if (!text(s).includes(low(n))) out.push(`A connection claims “${s.title}” joins ${n}, but the session never mentions it.`);
  }
  return out;
}

/* ---------- scoped change requests (simulated) ---------- */
export const KINDS = { shorter: 'Shorter', hands: 'More hands-on', found: 'Add a foundation step' };
export function readRequest(text) {
  const t = String(text || '').toLowerCase();
  // A request that says "do not", "no" or "without" is never guessed at. It is kept as a note for a person to read.
  if (/\b(not|no|never|without|don't|dont|do not|isn't|avoid|stop)\b/.test(t)) return 'note';
  if (/\b(short|shorter|shorten|less time|quick|quicker|trim|cut)\b/.test(t)) return 'shorter';
  if (/\b(hands[- ]on|practical|practice|playful|play|games?|active|activity|build|making|make)\b/.test(t)) return 'hands';
  if (/\b(basics?|foundations?|beginners?|recap|prerequisites?|from scratch)\b/.test(t)) return 'found';
  return 'note';
}
function resum(s) { s.minutes = s.activities.reduce((n, x) => n + x.minutes, 0); s.teacher.prep = 15 + s.activities.length * 5; }
// "Shorter" may keep a step the same length when it is already at the minimum. It never makes one longer.
export const shorter = (m, f) => m <= 5 ? m : Math.min(m, Math.max(5, Math.floor(m * f / 5) * 5));
const note = text => `${WRITER}: “${String(text).trim()}”. Not acted on. The prototype cannot interpret free text.`;
const bridge = (what, skip) => ({ id: newId('b'), kind: 'Bridge', minutes: 10, learner: `A quick recap of the basics ${what}.`, teacher: skip, internal: [] });
function changeAct(x, kind, text) {
  if (kind === 'shorter') x.minutes = shorter(x.minutes, .7);
  if (kind === 'hands' && x.kind !== 'Make') { x.kind = 'Make'; x.learner = 'Build it or act it out instead of listening. ' + x.learner.replace(/^Compare the attempts.*$/, 'Then say what worked and why.'); x.teacher = 'Keep talking under two minutes. ' + x.teacher; }
  if (kind === 'note') (x.internal = x.internal || []).push(note(text));
}
function changeSession(s, kind, text) {
  if (kind === 'shorter') s.activities.forEach(x => { x.minutes = shorter(x.minutes, .75); });
  if (kind === 'hands') { const e = s.activities.find(x => x.kind === 'Explain'), m = s.activities[s.activities.length - 1]; if (e && m && e !== m) { const take = Math.min(e.minutes - 5, r5(e.minutes * .5)); if (take > 0) { e.minutes -= take; m.minutes += take; e.learner = 'A short explanation, then straight back to making.'; } } }
  if (kind === 'found') s.activities.unshift(bridge('you need today', 'Skip this for learners who already have them.'));
  if (kind === 'note') s.internal.push(note(text));
  resum(s);
}
export function previewChange(j, req) {
  const after = clone(j), kind = req.kind === 'text' ? readRequest(req.text) : req.kind, lines = [], before = totalMin(j), notes = [];
  const si = after.sessions.findIndex(s => s.id === req.sessionId), S0 = j.sessions[si], S1 = after.sessions[si];
  const ai = S1 ? S1.activities.findIndex(x => x.id === req.activityId) : -1;
  const label = req.kind === 'text' ? String(req.text).trim() : KINDS[req.kind], base = { baseRev: j.rev || 0, baseUid: j.uid || '', req: clone(req), kind, label };
  if ((req.scope === 'activity' && (!S1 || ai < 0)) || (req.scope === 'session' && !S1)) return Object.assign(base, { after: clone(j), target: 'Something that no longer exists', lines: [], noop: true, gone: true, effects: ['The part this change was aimed at is no longer in the draft. Nothing will change.'] });
  let target = '';
  // One recap is enough. Asking again is reported, not stacked.
  const has = req.scope === 'activity' ? (ai > 0 && S1.activities[ai - 1].kind === 'Bridge') || S1.activities[ai].kind === 'Bridge' : req.scope === 'session' ? S1.activities[0].kind === 'Bridge' : j.mode === 'separate' ? j.topics.every((t, ti) => { const s = j.sessions.find(x => x.threads.length === 1 && x.threads[0] === ti); return !s || s.activities[0].kind === 'Bridge'; }) : j.sessions.some(s => s.key === 'bridge');
  if (kind === 'found' && has) return Object.assign(base, { after: clone(j), target: req.scope === 'journey' ? 'Whole journey' : S0.title, lines: [], noop: true, effects: ['A foundation step is already here. Adding another would only repeat it, so nothing will change.'] });
  if (req.scope === 'activity') {
    const x0 = S0.activities[ai], x1 = S1.activities[ai]; target = `Step “${x0.kind}” in ${S0.unit.toLowerCase()} ${si + 1}`;
    if (kind === 'found') { S1.activities.splice(ai, 0, bridge('this step needs', 'Skip for learners who already have them.')); resum(S1); lines.push({ label: 'New step before it', was: 'Nothing', now: 'Bridge · 10 min · a quick recap of the basics' }); }
    else if (kind === 'note') { changeAct(x1, kind, req.text); lines.push({ label: 'Internal note, stays in Loom', was: 'None', now: x1.internal[x1.internal.length - 1] }); }
    else { changeAct(x1, kind, req.text); resum(S1); lines.push({ label: x0.kind, was: `${x0.minutes} min · ${x0.learner}`, now: `${x1.minutes} min · ${x1.learner}` }); }
  } else if (req.scope === 'session') {
    target = `${S0.unit} ${si + 1}: ${S0.title}`; changeSession(S1, kind, req.text);
    if (kind === 'note') lines.push({ label: 'Internal note, stays in Loom', was: 'None', now: S1.internal[S1.internal.length - 1] });
    else { lines.push({ label: 'Length', was: fmtMin(S0.minutes), now: fmtMin(S1.minutes) }); lines.push({ label: 'Steps', was: S0.activities.map(x => `${x.kind} ${x.minutes}`).join(' · '), now: S1.activities.map(x => `${x.kind} ${x.minutes}`).join(' · ') }); }
  } else {
    target = 'Whole journey';
    if (kind === 'note') { (after.internal = after.internal || []).push(note(req.text)); lines.push({ label: 'Internal note, stays in Loom', was: 'None', now: after.internal[after.internal.length - 1] }); }
    else if (kind === 'found' && j.mode === 'separate') {
      // The brief keeps subjects apart, so each one gets its own recap. Nothing is combined.
      j.topics.forEach((t, ti) => { const s = after.sessions.find(x => x.threads.length === 1 && x.threads[0] === ti); if (s) { s.activities.unshift(bridge(`of ${t}`, 'Skip for learners who already have them.')); resum(s); lines.push({ label: `${t}: new first step`, was: 'Nothing', now: `Bridge · 10 min · the basics of ${t}` }); } });
      notes.push('Your brief keeps the topics separate, so each topic gets its own recap. No session combines them.');
    }
    else if (kind === 'found') { const c = listNames(j.topics), s = { id: newId('f'), key: 'bridge', unit: j.sessions[0].unit, title: 'Foundations first', aim: `Cover the basics that ${c} ${j.topics.length > 1 ? 'depend' : 'depends'} on.`, proof: 'A short entry task, passed or repeated.', why: 'Added on request so nobody starts behind.', threads: j.topics.map((_, i) => i), minutes: 0, activities: [{ id: 'a1', kind: 'Entry check', minutes: 10, learner: 'A short task that shows where you are starting from.', teacher: 'Not graded.', internal: [] }, { id: 'a2', kind: 'Explain', minutes: 20, learner: 'The two or three ideas everything else rests on.', teacher: 'Use examples from learners’ own lives.', internal: [] }, { id: 'a3', kind: 'Try', minutes: 30, learner: 'Use each idea once in a small task.', teacher: 'Pair stronger and newer learners.', internal: [] }], teacher: clone(j.sessions[0].teacher), internal: [SIM] }; resum(s); after.sessions.unshift(s); lines.push({ label: `New first ${s.unit.toLowerCase()}`, was: 'Nothing', now: `Foundations first · ${fmtMin(s.minutes)}` }); }
    else { after.sessions.forEach(s => changeSession(s, kind, req.text)); after.sessions.forEach((s, i) => { const o = j.sessions[i]; lines.push({ label: `${i + 1}. ${s.title}`, was: fmtMin(o.minutes), now: fmtMin(s.minutes) + (kind === 'hands' && JSON.stringify(o) !== JSON.stringify(s) ? ' · more making time' : '') }); }); }
  }
  const now = totalMin(after), effects = notes.slice(), p0 = planOf(j), p1 = planOf(after);
  effects.push(now === before ? `Planned time stays ${fmtMin(before)}.` : `Planned time: ${fmtMin(before)} becomes ${fmtMin(now)}.`);
  if (p1.sessions !== p0.sessions) effects.push(`${p1.unit}s planned: ${p0.sessions} becomes ${p1.sessions}.`);
  if (p1.differs) effects.push(`Differs from the brief (${p1.requested.span}): ${p1.notes.join('; ')}. The brief itself is not changed.`);
  if (req.scope === 'journey' && kind !== 'found' && kind !== 'note') effects.push(`Touches all ${j.sessions.length} sessions.`);
  if (kind === 'note') effects.push('The prototype could not interpret this request. It is kept as an internal note and will never appear in an export.');
  const was = audit(j), problems = audit(after).filter(p => !was.includes(p)), noop = JSON.stringify(after.sessions) === JSON.stringify(j.sessions) && JSON.stringify(after.internal || []) === JSON.stringify(j.internal || []);
  if (kind === 'shorter' && now > before) problems.push('“Shorter” would make the plan longer.');
  if (problems.length) return Object.assign(base, { after: clone(j), target, lines: [], noop: true, blocked: true, effects: ['Loom will not make this change, because the result would be inconsistent: ' + problems[0]] });
  if (noop) { effects.length = 0; effects.push(kind === 'shorter' ? 'Every step here is already at the shortest length Loom plans. Nothing would change.' : 'This would change nothing here. There is no step it can act on.'); }
  return Object.assign(base, { after, target, lines, effects, noop });
}
// A preview belongs to the exact draft it was made from. If the draft has moved on, it is refused, never applied.
export function applyPreview(j, p, newRev) {
  if (!p || p.noop) return { ok: false, reason: 'nothing' };
  if ((p.baseRev || 0) !== (j.rev || 0) || (p.baseUid || '') !== (j.uid || '')) return { ok: false, reason: 'stale' };
  if (!Number.isInteger(newRev) || newRev <= (j.rev || 0)) throw new Error('A change needs a new revision number.');
  const next = clone(p.after); next.rev = newRev; return { ok: true, journey: next };
}

/* ---------- export package: learner + teacher only ---------- */
const strip = t => String(t).replace(new RegExp('\\s*' + WRITER + ': “[^”]*”\\.?( Not acted on\\.)?( The prototype cannot interpret free text\\.)?', 'g'), '').trim();
const stripAll = l => (l || []).map(strip).filter(Boolean);
export function internalNotes(j) {
  const review = j.review && j.review.output ? [...(j.review.output.findings || []).flatMap(f => [f.finding, f.suggestion]), ...(j.review.output.areas || []).map(a => a.summary), (j.review.output.teacher_could_run_it || {}).why] : [];
  const ag = j.agents || {}, agent = [(ag.foundations || {}).output, (ag.sources || {}).output, (ag.outline || {}).output].filter(Boolean).flatMap(o => [o.summary, ...(o.findings || []).flatMap(f => [f.finding, f.suggestion]), ...(o.conflicts || []), ...(o.ordering_problems || []), ...(o.project_checks || []).map(c => c.why), (o.time_verdict || {}).why]).filter(t => typeof t === 'string' && t.trim().length >= 20);
  return [...(j.internal || []), ...review, ...agent, ...j.sessions.flatMap(s => [...(s.internal || []), ...(s.review ? [s.review.reason] : []), ...s.activities.flatMap(x => x.internal || [])])].filter(n => typeof n === 'string' && n.trim());
}
// Where a claim stands today. A link that opens, or a page the AI read, never makes a claim "checked".
// Four separate things: the AI asked for a page; the page arrived; the page supports a claim; a person has read it.
// Records made before Loom kept the result of each request only show that the page was asked for.
export const fetchState = s => s.fetch || (s.openedByAI ? 'asked' : 'none');
const dayOf = d => { const x = new Date(d); return Number.isNaN(x.getTime()) ? 'an unknown date' : x.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }); };
export function fetchLine(s) {
  const st = fetchState(s), when = dayOf(s.askedAt || s.retrievedAt);
  return { retrieved: `The page reached the AI during research on ${when}`, asked: `The AI asked for this page on ${when}. Whether it arrived was not recorded`, failed: `The AI asked for this page on ${when} and it did not open`,
    redirected: `The AI asked for this page on ${when} and was sent to another site`, no_result: `The AI asked for this page on ${when}. No record that it arrived` }[st] || 'No record that the AI asked for this page';
}
// A "fact" whose every source is recorded as partial or background support.
export function thinFact(c, j) {
  if (c.type !== 'fact') return false;
  const src = (c.sources || []).map(id => (j.sources || []).find(s => s.id === id)).filter(Boolean);
  if (c.support && c.support !== 'stated_by_source') return true;
  return src.length > 0 && src.every(s => s.strength && s.strength !== 'direct');
}
// One exact text for a piece of content, built the same way as the server builds it, so the two can be compared.
const canon = o => o === null || o === undefined ? 'null'
  : typeof o === 'number' ? (Number.isFinite(o) ? String(o) : 'null')
  : typeof o === 'boolean' ? String(o)
  : typeof o === 'string' ? JSON.stringify(o)
  : Array.isArray(o) ? '[' + o.map(canon).join(',') + ']'
  : '{' + Object.keys(o).sort().map(k => JSON.stringify(k) + ':' + canon(o[k])).join(',') + '}';
// A short fingerprint of content. The server counts the same units and gets the same answer.
export function contentPrint(o) { const s = canon(o); let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(36) + '.' + s.length.toString(36); }

// A person's check belongs to the exact claim they checked: its words, its label, what the source is recorded as stating, and the sources cited.
// If any of those has changed since, the check no longer counts, whichever way the change was made.
export function claimPrint(c) { const s = JSON.stringify([String(c.text || '').trim(), c.type || '', c.support || '', (c.sources || []).slice().sort()]); let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(36) + '.' + s.length.toString(36); }
export const checkedOn = c => c && c.personChecked && c.personChecked.at && (!c.personChecked.of || c.personChecked.of === claimPrint(c)) ? c.personChecked.at : null;
const lapsed = c => c.checkWithdrawn || (c.personChecked && !checkedOn(c)) ? ` A person checked an earlier wording of this claim${(c.checkWithdrawn || {}).was || (c.personChecked || {}).at ? ' on ' + dayOf((c.checkWithdrawn || {}).was || c.personChecked.at) : ''}. It has changed since and has not been checked again.` : '';
export function standing(c, j) { const base = standing_(c, j), l = c.type === 'fact' && !checkedOn(c) ? lapsed(c) : ''; return l ? base.replace(/ (Not yet checked by a person|Not checked by a person)\.$/, '') + l : base; }
function standing_(c, j) {
  if (c.type === 'fiction') return 'Fiction. Not a claim about the real world.';
  if (c.type === 'hypothesis') return 'The writer’s judgement. Not tested.';
  if (c.type === 'uncertain') return 'Uncertain. The evidence is thin or disputed.';
  const src = (c.sources || []).map(id => (j.sources || []).find(s => s.id === id)).filter(Boolean);
  if (!src.length) return 'Stated as fact but no source is attached. Treat as unverified.';
  if (checkedOn(c)) return `A person on the team checked this claim against its source on ${dayOf(checkedOn(c))}.`;
  const read = src.every(s => s.personChecked) ? ' A person has read the source, but has not checked this claim against it.' : '';
  if (src.some(s => ['failed', 'redirected', 'no_result', 'none'].includes(fetchState(s)))) return 'Source listed, but the page did not reach the AI.' + (read || ' Not checked by a person.');
  if (thinFact(c, j)) return 'Called a fact, but the source is recorded as supporting it only in part. Treat as uncertain until a person has checked this claim.' + read;
  if (src.every(s => fetchState(s) === 'retrieved')) return 'The page reached the AI during research.' + (read || ' Not yet checked by a person.');
  return 'The AI asked for the source during research. Whether the page arrived was not recorded.' + (read || ' Not checked by a person.');
  return 'Source listed, but Loom has no record it was read. Not checked by a person.';
}
// What stood open when the team approved. Counts and plain statements only: the reviewer's own words stay in Loom.
export function standingAtApproval(snapshot) {
  const j = snapshot.journey, rv = j.review && j.review.output, open = Array.isArray(snapshot.openAtApproval) ? snapshot.openAtApproval.filter(t => typeof t === 'string') : null;
  const base = { taughtToLearners: 'No. Loom holds no record of this course being taught or piloted.', approvedBy: 'A member of the Glitch team, in Loom.' };
  if (!rv) return Object.assign(base, { independentReview: 'None was run before approval.', openPointsAcknowledgedAtApproval: open });
  return Object.assign(base, { independentReview: j.review.rev === j.rev ? 'Made on this version, by Claude acting as a separate reviewer. It read what is written. It did not open the links or try the course.' : 'Made on an earlier draft, by Claude acting as a separate reviewer. This version was not reviewed again.',
    couldATeacherRunIt: String(rv.teacher_could_run_it.answer).replace(/_/g, ' '), findingsMarkedMustFix: (rv.findings || []).filter(f => f.severity === 'must_fix').length, findingsMarkedShouldFix: (rv.findings || []).filter(f => f.severity === 'should_fix').length,
    openPointsAcknowledgedAtApproval: open, note: 'The findings themselves are internal working notes and are not part of this package.' });
}
const tx = v => typeof v === 'string' ? v.trim() : '';
/* ---------- what the expanded pipeline leaves open. Plain statements: none of them can be ticked away. ---------- */
export function v2Open(j, forReadiness) {
  const out = [], ag = j.agents || {};
  if (j.timeConflict && j.timeConflict.exists) out.push(`Time conflict declared: ${tx(j.timeConflict.explanation)} It was approved as it stands, with the options left open.`);
  for (const g of ((j.map || {}).derived || {}).openGaps || []) out.push(`Open foundation gap: ${g}`);
  for (const g of ((j.map || {}).derived || {}).unresolved || []) out.push(`Left unresolved by the topic map: ${g}`);
  for (const d of j.deferred || []) out.push(`A required topic was deferred: ${tx(d.node)}. ${tx(d.reason)}`);
  const cov = ((j.research || {}).nodeCoverage || []).filter(c => c.role === 'required' && c.status !== 'supported' && c.status !== 'not_needed');
  if (cov.length) out.push(`${cov.length} required topic${cov.length > 1 ? 's have' : ' has'} no source that fully supports ${cov.length > 1 ? 'them' : 'it'}: ${cov.map(c => c.name).join('; ')}.`);
  const must = (((ag.outline || {}).output || {}).findings || []).filter(f => f.severity === 'must_fix');
  if (must.length) out.push(`The feasibility reviewer's ${must.length} must-fix finding${must.length > 1 ? 's were' : ' was'} not resolved before approval.`);
  const bad = (j.sources || []).filter(s => s.sourceReview && s.sourceReview.supports_claim === 'no').length; if (bad) out.push(`The source auditor found ${bad} source${bad > 1 ? 's' : ''} that do not support their claim. They were lowered to background.`);
  const allChecks = [...j.sessions.flatMap(s => checksFor(s.assets || [], s.assetChecks || [])), ...(j.projects || []).flatMap(p => checksFor([...((p.content || {}).inputs || []), ...((p.content || {}).solution_assets || [])], p.assetChecks || []))], notRun = allChecks.filter(c => c.level === 'not_run'), unver = allChecks.filter(c => c.level === 'origin_unverified');
  if (unver.length) out.push(`${unver.length} dataset${unver.length > 1 ? 's say' : ' says'} they are extracts of a public source, but that could not be checked against the page: ${unver.map(c => c.name).join(', ')}.`);
  if (notRun.length) out.push(`${notRun.length} code file${notRun.length > 1 ? 's were' : ' was'} not run on this computer (${[...new Set(notRun.map(c => c.reason))][0]})`);
  const syn = [...j.sessions.flatMap(s => s.assets || []), ...(j.projects || []).flatMap(p => (p.content ? [...(p.content.inputs || []), ...(p.content.solution_assets || [])] : []))].filter(a => a.kind === 'dataset' && a.provenance === 'synthetic_practice');
  if (syn.length && !forReadiness) out.push(`${syn.length} dataset${syn.length > 1 ? 's are' : ' is'} made-up practice data, not real measurements: ${[...new Set(syn.map(a => a.name))].join(', ')}.`);
  return out;
}

// What is open about the evidence. A fact counts as settled only when a person has checked that claim, as it is worded now, against its source.
export function evidenceOpen(j) {
  const facts = [...j.sessions.flatMap(s => s.claims || []), ...(j.projects || []).flatMap(p => (p.content && p.content.claims) || [])].filter(c => c.type === 'fact'), out = [];
  const bare = facts.filter(c => !(c.sources || []).length).length, open = facts.filter(c => (c.sources || []).length && !checkedOn(c)).length, lapsedN = facts.filter(c => c.checkWithdrawn && !checkedOn(c)).length;
  if (bare) out.push(`${bare} claim${bare > 1 ? 's are' : ' is'} stated as fact with no source.`);
  if (open) out.push(`${open} of ${facts.length} claims called facts ${open > 1 ? 'have' : 'has'} not been checked against ${open > 1 ? 'their sources' : 'its source'} by a person.`);
  if (lapsedN) out.push(`${lapsedN} of those ${lapsedN > 1 ? 'were' : 'was'} checked once, then changed, and not checked again.`);
  return out;
}
// Three separate questions, answered separately. A yes to one says nothing about the next.
export function threeParts(j, snapshot, trials) {
  const must = audit(j), rd = snapshot ? readinessOf(snapshot, trials) : null, open = snapshot && Array.isArray(snapshot.openAtApproval) ? snapshot.openAtApproval.length : 0;
  return { structure: must.length ? `${must.length} thing${must.length > 1 ? 's' : ''} to fix: times, parts or sessions do not agree.` : 'Holds. Times, parts and sessions agree with each other. This says nothing about the teaching.',
    internalApproval: !snapshot ? (must.length ? 'Not possible until the structure holds.' : 'Not approved yet. The team may approve; that is a decision, not a test.') : `Approved by the team on ${dayOf(snapshot.at)}${open ? `, with ${open} open point${open > 1 ? 's' : ''} read and ticked. Ticking a point does not resolve it.` : '.'}`,
    teachingReadiness: rd ? rd.label : 'Not established. A draft has no readiness level until it is approved.' };
}
// Approval is a decision by the team. It is not a statement that the course is ready to teach.
// A version approved with blockers open is an internal draft, and says so everywhere it appears.
export function readinessOf(snapshot, trials) {
  const j = snapshot.journey, mine = (Array.isArray(trials) ? trials : snapshot.trials || []).filter(t => t && t.ver === snapshot.ver), day_ = d => dayOf(d);
  const pilot = mine.filter(t => t.kind === 'pilot').pop(), rehearsal = mine.filter(t => t.kind === 'rehearsal').pop();
  if (!isReal(j)) return { draft: true, label: 'Simulated example', short: 'Simulated', why: ['This is filler made by fixed rules. It is not course content.'] };
  const rv = j.review && j.review.output, why = [];
  if (!rv) why.push('No independent review was run.');
  else {
    const must = (rv.findings || []).filter(f => f.severity === 'must_fix').length;
    if (j.review.rev !== j.rev) why.push('The independent review was made on an earlier draft.');
    if (must) why.push(`${must} review finding${must > 1 ? 's' : ''} marked “must fix” ${must > 1 ? 'were' : 'was'} open at approval.`);
    if (rv.teacher_could_run_it.answer !== 'yes') why.push(`The reviewer’s answer to “could a teacher run it?” was “${String(rv.teacher_could_run_it.answer).replace(/_/g, ' ')}”.`);
  }
  if (j.sessions.some(s => s.review)) why.push('One or more sessions were marked “Look” and had not been checked.');
  // A point the team ticked at approval is still open. Reading it is not resolving it.
  const ev = evidenceOpen(j); if (ev.length) why.push(...ev);
  if (j.pipeline === 2) why.push(...v2Open(j, true));
  if (why.length) return { draft: true, level: 'internal', label: 'Internal draft. Not ready to teach.', short: 'Internal draft', why };
  if (pilot) return { draft: false, level: 'piloted', label: `Piloted with learners on ${day_(pilot.at)}, as recorded by the team.`, short: 'Piloted', why: pilot.note ? [pilot.note] : [] };
  if (rehearsal) return { draft: false, level: 'rehearsed', label: `Rehearsed by a facilitator on ${day_(rehearsal.at)}, as recorded by the team. Not yet tried with learners.`, short: 'Rehearsed', why: rehearsal.note ? [rehearsal.note] : [] };
  return { draft: false, level: 'reviewed', label: 'Reviewed on paper and ready for a facilitator rehearsal. Not yet rehearsed by a teacher or tried with learners.', short: 'Ready to rehearse', why: [] };
}
export function buildPackage(snapshot) {
  const j = snapshot.journey, p = planOf(j), real = isReal(j);
  if (unwritten(j).length) throw new Error('Export stopped: some sessions have not been written.');
  const pkg = {
    package: 'Glitch Loom export', readiness: readinessOf(snapshot).label, whyThisReadiness: readinessOf(snapshot).why, threeSeparateQuestions: threeParts(j, snapshot), readinessLevels: 'working draft → internal draft with open issues → reviewed and ready for a facilitator rehearsal → rehearsed → piloted with learners', version: snapshot.ver, approvedAt: snapshot.at, exportedAt: new Date().toISOString(),
    notice: real ? 'Drafted with Claude from the team’s brief and approved by the team on the date shown. See “standingAtApproval” for what was still open. Sources were found by AI research: each one says whether a person has checked it. Exporting does not publish anything. Internal notes are not included.'
      : 'Simulated prototype content, not checked by anyone. Exporting does not publish anything. Internal notes are not included.',
    howItWasMade: real ? 'Written with Claude' : 'Simulated example',
    course: { outcome: j.outcome, format: j.format, audience: j.audience, delivery: j.delivery, topics: j.topics, topicsKeptSeparate: j.mode === 'separate',
      requestedInBrief: { duration: p.requested.span, minutes: p.requested.minutes, sessions: p.requested.sessions },
      planned: { duration: p.label, minutes: p.minutes, sessions: p.sessions, sessionUnit: p.unit }, plannedDiffersFromBrief: p.differs, differences: p.notes },
    learnerMaterials: j.sessions.map((s, i) => Object.assign({ session: i + 1, title: s.title, youWill: strip(s.outcome || s.aim), youProveItBy: real ? stripAll(s.successCriteria).join(' ') : s.proof, minutes: s.minutes },
      real ? { beforeYouStart: (s.prerequisites || []).map(q => q.name), successCriteria: stripAll(s.successCriteria), laterCheck: s.applicationCheck ? { when: s.applicationCheck.when, task: strip(s.applicationCheck.task) } : null } : {},
      { steps: s.activities.map(x => Object.assign({ step: x.kind, minutes: x.minutes, what: strip(x.learner) }, real ? { title: x.title, goal: strip(x.goal), instructions: stripAll(x.instructions), materials: x.materials || [], handout: strip(x.handout || ''), workedExample: strip(x.example || ''), successLooksLike: stripAll(x.success) } : {})) })),
    teacherMaterials: j.sessions.map((s, i) => Object.assign({ session: i + 1, title: s.title, materials: s.teacher.materials, requirementsToImplement: (s.teacher.requirements || []).map(r => r.replace(REQ, '')), setup: s.teacher.setup, preparationMinutes: s.teacher.prep },
      real ? { preparation: s.teacher.prepSteps || [], prerequisites: s.prerequisites || [], prerequisitesNote: s.prerequisitesNote || '', whatEachTopicContributes: s.contributions || [], successCriteria: stripAll(s.successCriteria), laterCheck: s.applicationCheck || null, assumptions: s.assumptions || [] } : {},
      { stepNotes: s.activities.map(x => Object.assign({ step: x.kind, note: strip(x.teacher) }, real ? { title: x.title, guidance: stripAll(x.guidance), likelyMisconceptions: x.misconceptions || [] } : {})) }))
  };
  if (real) {
    pkg.course.finalEvidence = j.finalEvidence || ''; pkg.course.topicConnection = j.integration || null; pkg.course.feasibility = j.feasibility || null;
    pkg.standingAtApproval = standingAtApproval(snapshot);
    pkg.evidence = { readThisFirst: 'Every claim is labelled. A web address that opens, or a page the AI read, does not make a claim true. Only “checked by a person” means someone on the team read the source.',
      sources: (j.sources || []).map(s => ({ id: s.id, title: s.title, ...(s.titleDiffersFromTheDocument ? { theDocumentGivesItsOwnTitleAs: s.titleDiffersFromTheDocument } : {}), ...(s.titleCorrectedFromTheDocument ? { titleCorrectedFromTheDocument: true, titleOnRecordBefore: s.titleOnRecord } : {}), url: s.url, publisher: s.publisher, year: s.year, kind: s.kind, supportsTheClaim: s.claim, whatThePageSays: s.finding, limits: s.limits, askedForOn: s.askedAt || s.retrievedAt, pageReachedTheAI: { retrieved: 'yes', asked: 'not recorded' }[fetchState(s)] || 'no', retrievedOn: fetchState(s) === 'retrieved' ? s.retrievedAt : null, addressOpenedOn: s.link && s.link.opened ? s.link.checkedAt : null, readByAPersonOn: s.personChecked ? s.personChecked.at : null, excerpt: s.quote || '', ...(s.retrievedExcerpt ? { whatTheFetchReturned: cut(s.retrievedExcerpt, 500), quoteFoundInWhatWasReturned: s.quoteFound === null || s.quoteFound === undefined ? undefined : s.quoteFound } : {}), ...(s.node_ids ? { supportsTopics: s.node_ids } : {}), evidenceLevel: s.evidenceLevel || 'tool_summary', ...(s.directRetrieval ? { retrievedByLoom: { sha256: s.directRetrieval.sha256, at: s.directRetrieval.retrievedAt, method: s.directRetrieval.method, textMethod: s.directRetrieval.textMethod, quoteFoundVerbatim: s.directRetrieval.quoteVerbatim, locator: s.directRetrieval.locator } } : {}), ...(s.role ? { identity: { madeBy: s.authors, published: s.published, version: s.version_or_edition, identifier: s.identifier, role: s.role }, lineage: (s.lineage || []).map(x => ({ relation: x.relation, earlierWork: x.earlier_work, whatChanged: x.what_changed, limits: x.limits })) } : {}), originalSource: s.originalSource || { status: 'not_verified', because: ['this record was made before Loom kept source roles or retrieved pages itself'] }, ...(s.sourceReview ? { sourceAuditVerdict: s.sourceReview.supports_claim } : {}), ...((s.attribution && s.attribution.unresolvedDisagreements || []).length ? { attributionReviewDisagreesWithItself: s.attribution.unresolvedDisagreements.map(x => ({ about: x.aspect, earlierAnswer: x.earlier, laterAnswer: x.later, sameEvidence: x.sameEvidence, sameWholeRequest: x.sameWholeRequest })), nothingRestingOnThisIsSettled: true } : {}), ...(s.subject_version ? { subjectVersion: s.subject_version } : {}) })),
      claims: j.sessions.flatMap((s, i) => (s.claims || []).map(c => ({ session: i + 1, claim: strip(c.text), type: c.type, sources: c.sources || [], checkedAgainstSourceByAPersonOn: checkedOn(c), checkWithdrawnBecauseTheClaimChanged: c.checkWithdrawn || (c.personChecked && !checkedOn(c)) ? true : undefined, sourceStatesThisClaim: c.support ? { stated_by_source: 'yes', partly: 'in part', not_from_source: 'no' }[c.support] : 'not recorded', standing: standing(c, j) }))) };
  }
  if (real && j.pipeline === 2) addV2(pkg, snapshot);
  // Last guard. It looks for stored requests and review notes, not for ordinary sentences that happen to share words.
  if (real && j.pipeline === 2) checkPreparedDelivered(pkg, j.preparedFiles || []);
  const out = JSON.stringify(pkg), low = out.toLowerCase(), leak = internalNotes(j).filter(n => n !== SIM).find(n => out.includes(JSON.stringify(n).slice(1, -1)));
  if (leak || low.includes(WMARK)) throw new Error('Export stopped: an internal note was about to be included.');
  return pkg;
}

// What the expanded pipeline adds to a package. Scope, coverage, evidence per topic, projects and files. Reviewers' own words stay in Loom: only their verdicts and counts go out.
const KIND_LEARNER = ['dataset', 'code', 'starter', 'template', 'document'];
const PROV = { public_source: 'A small extract of a real public dataset', synthetic_practice: 'Made-up practice data. These are not real measurements', authored: 'Written for this course' };
const cut = (t, n) => { t = String(t || ''); return t.length > n ? t.slice(0, n) + '…' : t; };
// Prepared originals are the real files the course was built on. They are carried through the package exactly as
// they are on disk, with their checksum, so a teacher or learner receives the file itself rather than a name a
// model typed. Nothing here is rewritten or summarised.
const PREP_KIND = { original: 'The original file, exactly as it was published. Not edited for teaching', teaching_copy: 'A teaching copy made from an original. See what was changed' };
function preparedOut(f) {
  return { name: f.name, whatItIs: PREP_KIND[f.kind] || f.kind, purpose: f.purpose || '', checksumSha256: f.sha256, bytes: f.bytes,
    cameFrom: f.provenance ? { publisher: f.provenance.publisher, page: f.provenance.publisherUrl, askedFor: f.provenance.requestUrl, retrieved: f.provenance.retrievedAt, serviceVersion: f.provenance.serviceVersion, licence: f.provenance.licenceNote, fields: f.provenance.fields, coverage: f.provenance.coverage, limitations: f.provenance.limitations, changedFromTheOriginal: f.provenance.transformationLog || undefined, problemsPlantedOnPurpose: f.provenance.plantedProblems } : undefined,
    ...(f.measured && f.measured.readable ? { loomCountedInThisFile: { dataRows: f.measured.dataRows, linesBeforeTheColumnNames: f.measured.preambleLinesBeforeTheColumnNames, fillCodeValues: f.measured.fillCodeMinus999Values, layout: f.measured.layout, columnNames: f.measured.columnNames } } : {}),
    ...(f.encoding === 'binary' ? { contentBase64: f.contentBase64 } : { content: f.content }) };
}
// Every prepared file the package names must actually travel with it, with bytes that match its checksum.
function checkPreparedDelivered(pkg, prepared) {
  // Only the course's own material counts as naming a file. The list of what could not be delivered names those
  // files too, on purpose, and must not make the package refuse itself.
  const named = JSON.stringify([pkg.course, pkg.learnerMaterials, pkg.teacherMaterials, pkg.projects]);
  const delivered = JSON.stringify((pkg.preparedOriginals || {}).files || []);
  for (const f of prepared) {
    if (f.available === false) {
      if (named.includes(f.name)) throw new Error(`Export stopped: the course refers to ${f.name}, but that prepared file cannot be delivered (${f.why || 'its bytes are not available'}).`);
    } else if (!(f.sha256 && delivered.includes(f.sha256))) {
      throw new Error(`Export stopped: ${f.name} was not included with its checksum.`);
    }
  }
}
function assetOut(a, teacher) { return { name: a.name, kind: a.kind, purpose: a.purpose, origin: PROV[a.provenance] || '', sourceId: a.source_id || undefined, language: a.language || undefined, content: a.content, ...(teacher && a.expected_output ? { whatACorrectRunPrints: a.expected_output } : {}) }; }
// A check belongs to the exact file it was run on. Editing a file changes its checksum, so an older result stops
// matching and is shown as "changed since it was checked" rather than as a pass a changed program never earned.
export const assetPrint = a => contentPrint([String(a.name ?? ''), String(a.content ?? '')]);
export function checksFor(assets, results) {
  const want = new Set((assets || []).map(assetPrint));
  const firstByName = new Map();
  for (const a of assets || []) if (!firstByName.has(String(a.name ?? ''))) firstByName.set(String(a.name ?? ''), assetPrint(a));
  return (results || []).flatMap(r => {
    if (r.assetPrint && want.has(r.assetPrint)) return [r];
    if (!r.assetPrint) return [r];
    if (firstByName.has(r.name)) return [{ name: r.name, kind: r.kind, check: r.check, assetPrint: firstByName.get(r.name), state: 'stale', level: 'not_run', output: '', reason: 'This file changed after it was checked, so the earlier result no longer applies to it.' }];
    return [];
  });
}
const runLine = c => ({ file: c.name, checked: { stale: 'This file changed after it was checked. The earlier result no longer applies', executed: 'Run on this computer, no network. It finished without error', syntax_only: 'Read for errors only. It has gaps on purpose, so it was not run', not_run: 'Not run: ' + (c.reason || ''), failed: 'Failed: ' + (c.reason || ''), origin_checked: 'Checked against the source page: ' + (c.reason || ''), origin_unverified: 'Not verified: ' + (c.reason || ''), origin_failed: 'Failed: ' + (c.reason || '') }[c.state === 'stale' ? 'stale' : c.level] || c.level, output: c.output ? cut(c.output.trim(), 400) : undefined });
function addV2(pkg, snapshot) {
  const j = snapshot.journey, m = j.map || { nodes: [] }, name = id => (m.nodes.find(n => n.id === id) || {}).name || id, ag = j.agents || {};
  pkg.course.timeAccounting = j.accounting ? j.accounting.statement : undefined; pkg.course.independentTime = j.independentPlan || undefined;
  pkg.scope = { readThisFirst: 'What this course covers and why. “Required” topics are taught. “Already known” topics are assumed. “Excluded” topics are left out on purpose. Nothing here is a claim that the course teaches all there is to know about its subject: it covers what the stated learners need to reach the stated outcome.',
    topics: m.nodes.map(n => ({ topic: n.name, kind: { requested: 'asked for', foundation: 'foundation added by Loom', subtopic: 'part of an asked-for topic' }[n.kind] || n.kind, role: n.role, whyItIsHere: n.why_needed || (n.kind === 'requested' ? 'It was asked for.' : ''), neededBy: (n.needed_by || []).map(x => x === 'OUTCOME' ? 'the outcome' : name(x)), needs: (n.requires || []).map(name), depth: n.depth, estimatedMinutes: n.est_minutes, addedOnReviewOf: n.addedBy || undefined })),
    learnersAreAssumedToBeAbleTo: m.assumed_entry || [], whereTheMapStops: m.stop_reason || undefined,
    whereEachIsTaught: (j.coverage || { rows: [] }).rows.map(r => ({ topic: r.name, role: r.role, taughtInSession: r.taughtInSession, alsoPractisedInSessions: r.practisedInSessions, usedByProjects: r.usedByProjects })), deferred: (j.deferred || []).map(d => ({ topic: name(d.node), reason: d.reason })),
    timeConflict: j.timeConflict && j.timeConflict.exists ? { explanation: j.timeConflict.explanation, options: j.timeConflict.options } : null, openFoundationGaps: (m.derived || {}).openGaps || [], leftUnresolvedByTheMap: (m.derived || {}).unresolved || [], projectExpectation: j.policy ? j.policy.note : undefined, fullerPathway: j.pathwayNote || undefined };
  const lin = (j.research || {}).lineage, chains = (j.research || {}).lineageChains || [];
  pkg.evidence = pkg.evidence || {};
  if (lin && lin.works) {
    pkg.evidence.worksAndHowTheyDescend = {
      readThisFirst: 'Which published works this course rests on, and how later ones extend, correct or replicate earlier ones. Where a work was first published is a different question from what the current official version is, and from whether it still holds. A link counts as supported only when words from a page Loom retrieved itself show it and a separate review confirmed it; anything else is shown as claimed but not established. A link whose standing is “unresolved” is one where two runs of the review answered the same question differently on the same evidence: it is not supported and not refused, and it stays that way until a person decides on the evidence.',
      works: Object.values(lin.works).map(w => ({ work: w.id, title: w.title, madeBy: w.creators, published: w.published, versionOrEdition: w.version_or_edition, identifier: w.identifier, role: w.role, originIs: w.originStatus, whyNotEstablished: (w.originWhy || []).length ? w.originWhy : undefined, contraryEvidenceFromOtherSightings: (w.originContrary || []).length ? w.originContrary : undefined, attributionVerdict: w.attributionVerdict, seenAt: w.seenAt })),
      descent: (lin.edges || []).map(e => ({ laterWork: e.from, earlierWork: e.to || null, earlierWorkAsNamed: e.earlierWorkAsNamed, relation: e.relation, whatChanged: e.whatChanged, limits: e.limits, wordsThatShowIt: e.supportingWords, standing: e.status, whyNotSupported: (e.why || []).length ? e.why : undefined })),
      originalsAndTheirExtensions: chains,
      counts: lin.summary };
  }
  pkg.evidence.perTopic = ((j.research || {}).nodeCoverage || []).map(c => ({ topic: c.name, role: c.role, sources: c.sources, status: { supported: 'Sources found that support it', partly: 'Only partly supported', none_found: 'No supporting source found', not_needed: 'Not something a source is needed for' }[c.status] || c.status }));
  pkg.checksByOtherAIRoles = { note: 'Separate requests to Claude, each with its own role, read separately. They are AI, not independent human experts. Their findings stay in Loom; only verdicts and counts are shown.',
    foundationsAndOrder: ag.foundations && ag.foundations.output ? { verdict: ag.foundations.output.verdict, topicsAddedOnItsRequest: ag.foundations.added || [] } : 'Not run',
    sourceAudit: ag.sources && ag.sources.output ? { verdict: ag.sources.output.verdict, sourcesJudgedNotToSupportTheirClaim: (j.sources || []).filter(s => s.sourceReview && s.sourceReview.supports_claim === 'no').length, sourcesJudgedToSupportOnlyPartly: (j.sources || []).filter(s => s.sourceReview && s.sourceReview.supports_claim === 'partly').length } : 'Not run',
    feasibilityOfOutlineAndProjects: ag.outline && ag.outline.output ? { verdict: ag.outline.output.verdict, mustFixLeftOpenAtApproval: (ag.outline.output.findings || []).filter(f => f.severity === 'must_fix').length } : 'Not run' };
  const prepared = (j.preparedFiles || []);
  if (prepared.length) pkg.preparedOriginals = { readThisFirst: 'The files this course was built on, delivered here exactly as they are, with a checksum so you can tell they arrived whole. An original is delivered with the bytes that were registered for it; a teaching copy carries a record of what was changed from its original. The counts are measured from each file. The publisher, licence and limitations are as recorded when the file was registered: a checksum shows the bytes have not changed since, and does not by itself establish who published them.', files: prepared.filter(f => f.available !== false).map(preparedOut), notAvailable: prepared.filter(f => f.available === false).map(f => ({ name: f.name, why: f.why || 'its bytes are not available' })) };
  const namesFor = s => prepared.filter(f => f.available !== false && JSON.stringify([s.activities || [], s.assets || [], s.teacher || {}, s.independentWork || {}]).includes(f.name)).map(preparedOut);
  pkg.learnerMaterials.forEach((x, i) => { const s = j.sessions[i]; if (s.independentWork && s.independentWork.minutes) x.afterTheMeeting = { independentMinutes: s.independentWork.minutes, tasks: s.independentWork.tasks };
    const files = (s.assets || []).filter(a => KIND_LEARNER.includes(a.kind)); if (files.length) x.files = files.map(a => assetOut(a, false));
    const prep = namesFor(s); if (prep.length) x.preparedFilesYouNeed = prep; });
  pkg.teacherMaterials.forEach((x, i) => { const s = j.sessions[i]; x.teachesTopics = (s.teachesNodes || []).map(name); x.projectWork = s.projectWork || [];
    const files = (s.assets || []).filter(a => !KIND_LEARNER.includes(a.kind)); if (files.length) x.teacherFiles = files.map(a => assetOut(a, true)); const cc = checksFor(s.assets || [], s.assetChecks || []); if (cc.length) x.codeChecks = cc.map(runLine); });
  pkg.projects = (j.projects || []).filter(p => p.content).map(p => { const c = p.content, o = p.outline;
    return { id: p.id, kind: o.kind === 'major' ? 'Major project (capstone)' : 'Minor project', title: c.title || o.title, availableAfterSession: o.available_after_session, workedOnInSessions: o.hosted_in_sessions,
      learner: { purpose: c.purpose, brief: c.learner_brief, youNeedFirst: (c.prerequisites || []).map(q => ({ topic: q.name, taughtInSession: q.taught_in_session })), files: (c.inputs || []).map(a => assetOut(a, false)), milestones: c.milestones, whatYouHandIn: c.deliverables, time: c.time, howYouWillBeAssessed: c.rubric, howYouGetFeedbackAndRevise: `${c.feedback_route} ${c.revision_route}`.trim() },
      teacher: { whatGoodWorkLooksLike: c.example_or_solution_guidance, solutionFiles: (c.solution_assets || []).map(a => assetOut(a, true)), guidance: c.teacher_guidance, commonErrors: c.common_errors, claims: (c.claims || []).map(x => ({ claim: x.text, type: x.type, sources: x.sources, checkedAgainstSourceByAPersonOn: checkedOn(x), standing: standing(x, j) })), assumptions: c.assumptions, codeChecks: checksFor([...(c.inputs || []), ...(c.solution_assets || [])], p.assetChecks || []).map(runLine) } }; });
}

/* ---------- a pack people can read and print. Built from the same package as the structured export, so it holds nothing the export does not. ---------- */
const h = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const ol = l => (l || []).length ? `<ol>${l.map(x => `<li>${h(x)}</li>`).join('')}</ol>` : '';
const ulh = l => (l || []).length ? `<ul>${l.map(x => `<li>${h(x)}</li>`).join('')}</ul>` : '';
const pre = (title, text) => text ? `<section class="sheet"><h4>${h(title)}</h4><pre>${h(text)}</pre></section>` : '';
const fileHTML = a => `<section class="sheet"><h4>${h(a.name)} <span class="min">${h(a.kind)}${a.origin ? ' · ' + h(a.origin) : ''}</span></h4>${a.purpose ? `<p class="meta">${h(a.purpose)}</p>` : ''}<pre>${h(a.content)}</pre>${a.whatACorrectRunPrints ? `<p class="meta">A correct run prints: ${h(a.whatACorrectRunPrints)}</p>` : ''}</section>`;
// A prepared original in a readable pack. The bytes are printed in full so the pack can be used on its own, and a
// download link carries the exact same bytes, so nobody has to retype a dataset from a printed page. Binary files
// cannot be printed, so only the link carries them and the pack says so.
const dataURI = f => f.contentBase64 !== undefined
  ? `data:application/octet-stream;base64,${f.contentBase64}`
  : `data:text/plain;charset=utf-8,${encodeURIComponent(String(f.content ?? ''))}`;
function preparedHTML(f) {
  const from = f.cameFrom || {};
  const rows = [['Publisher', from.publisher], ['Page', from.page], ['Asked for', from.askedFor], ['Retrieved', from.retrieved],
    ['Service version', from.serviceVersion], ['Licence', from.licence], ['Coverage', from.coverage ? JSON.stringify(from.coverage) : ''],
    ['Limitations', (from.limitations || []).join('; ')], ['Changed from the original', (from.changedFromTheOriginal || []).join('; ')],
    ['Problems planted on purpose', from.problemsPlantedOnPurpose === undefined ? '' : String(from.problemsPlantedOnPurpose)],
    ['Checksum (SHA-256)', f.checksumSha256], ['Size in bytes', f.bytes]].filter(r => r[1] !== undefined && r[1] !== null && r[1] !== '');
  return `<section class="sheet"><h4>${h(f.name)} <span class="min">prepared file</span></h4><p class="meta">${h(f.whatItIs)}${f.purpose ? ' · ' + h(f.purpose) : ''}</p>
    <p><a href="${dataURI(f)}" download="${h(f.name)}">Save ${h(f.name)}</a> — the exact bytes, checksum ${h(String(f.checksumSha256 || '').slice(0, 12))}.</p>
    ${f.contentBase64 !== undefined ? '<p class="meta">This file is not text, so it is not printed here. Use the link above to save it.</p>' : `<pre>${h(f.content)}</pre>`}
    ${table(['What', 'Value'], rows)}</section>`;
}
function preparedSectionHTML(pkg) {
  const p = pkg.preparedOriginals; if (!p || (!(p.files || []).length && !(p.notAvailable || []).length)) return '';
  return `<h2>Files this course was built on</h2><p>${h(p.readThisFirst)}</p>${(p.files || []).map(preparedHTML).join('')}
    ${(p.notAvailable || []).length ? `<h4>Named but not delivered</h4>${table(['File', 'Why'], p.notAvailable.map(x => [x.name, x.why]))}` : ''}`;
}
const table = (head, rows) => rows.length ? `<table><tr>${head.map(x => `<th>${h(x)}</th>`).join('')}</tr>${rows.map(r => `<tr>${r.map(x => `<td>${h(x)}</td>`).join('')}</tr>`).join('')}</table>` : '';
function scopeHTML(pkg) {
  const sc = pkg.scope; if (!sc) return '';
  return `<h2>Scope: what this course covers, and why</h2><p>${h(sc.readThisFirst)}</p>${pkg.course.timeAccounting ? `<p><strong>Time:</strong> ${h(pkg.course.timeAccounting)}</p>` : ''}
    ${table(['Topic', 'Role', 'Why it is here', 'Needed by', 'Taught in'], sc.topics.map(t => { const w = sc.whereEachIsTaught.find(r => r.topic === t.topic) || {}; return [t.topic, `${t.role.replace(/_/g, ' ')} (${t.kind})`, t.whyItIsHere, t.neededBy.join(', '), t.role === 'required' ? (w.taughtInSession ? 'Session ' + w.taughtInSession : 'Not taught') : '']; }))}
    ${sc.learnersAreAssumedToBeAbleTo.length ? `<h4>Learners are assumed to be able to</h4>${ulh(sc.learnersAreAssumedToBeAbleTo)}` : ''}
    ${sc.timeConflict ? `<div class="status draft"><strong>A time conflict was declared and approved as it stands.</strong> ${h(sc.timeConflict.explanation)}${ulh(sc.timeConflict.options.map(o => `${o.label}: ${o.effect}`))}</div>` : ''}
    ${sc.openFoundationGaps.length ? `<h4>Foundation gaps still open</h4>${ulh(sc.openFoundationGaps)}` : ''}${sc.fullerPathway ? `<p><strong>A fuller pathway, offered separately:</strong> ${h(sc.fullerPathway)}</p>` : ''}
    ${pkg.checksByOtherAIRoles ? `<h4>Checks by other AI roles</h4><p>${h(pkg.checksByOtherAIRoles.note)}</p><pre>${h(JSON.stringify({ foundations: pkg.checksByOtherAIRoles.foundationsAndOrder, sources: pkg.checksByOtherAIRoles.sourceAudit, feasibility: pkg.checksByOtherAIRoles.feasibilityOfOutlineAndProjects }, null, 1))}</pre>` : ''}`;
}
function projectsHTML(pkg, teacher) {
  if (!(pkg.projects || []).length) return '';
  return `<h2>Projects</h2>` + pkg.projects.map(p => { const L = p.learner, T = p.teacher;
    return `<h3>${h(p.kind)}: ${h(p.title)}</h3><p class="meta">Available after session ${h(p.availableAfterSession)} · worked on in session${p.workedOnInSessions.length > 1 ? 's' : ''} ${h(p.workedOnInSessions.join(', '))} · ${h(L.time.live)} min live, ${h(L.time.independent)} min independent</p><p>${h(L.purpose)}</p>
      <h4>The brief</h4><pre>${h(L.brief)}</pre>${L.youNeedFirst.length ? `<h4>You need first</h4>${ulh(L.youNeedFirst.map(q => `${q.topic} (session ${q.taughtInSession})`))}` : ''}${L.files.map(fileHTML).join('')}
      <h4>Milestones</h4>${table(['When', 'Session', 'What you do', 'Minutes', 'How it is checked'], L.milestones.map(m => [m.when, m.session, m.what, m.minutes, m.check]))}<h4>What you hand in</h4>${ulh(L.whatYouHandIn)}
      <h4>How you will be assessed</h4>${(L.howYouWillBeAssessed || []).map(r => `<p><strong>${h(r.criterion)}</strong></p>${table(['Level', 'What the work looks like'], r.levels.map(l => [l.level, l.descriptor]))}`).join('')}<h4>Feedback and revision</h4><p>${h(L.howYouGetFeedbackAndRevise)}</p>
      ${teacher ? `<h4>What good work looks like</h4><p>${h(T.whatGoodWorkLooksLike)}</p>${(T.guidance || []).length ? `<h4>Teacher guidance</h4>${ulh(T.guidance)}` : ''}${(T.commonErrors || []).length ? `<h4>Common errors</h4>${table(['What a learner may think', 'Response'], T.commonErrors.map(m => [m.belief, m.response]))}` : ''}${(T.solutionFiles || []).map(fileHTML).join('')}${(T.codeChecks || []).length ? `<h4>What running the code showed</h4>${table(['File', 'Checked', 'Output'], T.codeChecks.map(c => [c.file, c.checked, c.output || '']))}` : ''}` : ''}`; }).join('');
}
export function packHTML(pkg, who) {
  const teacher = who === 'teacher', c = pkg.course, title = `${c.topics.join(' + ')}: ${teacher ? 'teacher pack' : 'learner handouts'}`;
  const head = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>${h(title)}</title><style>
body{font:16px/1.55 Georgia,'Times New Roman',serif;color:#1b1b1f;background:#fff;max-width:46rem;margin:0 auto;padding:24px 16px}h1,h2,h3,h4{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.25;text-wrap:balance}
h1{font-size:1.7rem;margin:0 0 .3em}h2{font-size:1.3rem;margin:2.2em 0 .4em;padding-top:.8em;border-top:3px solid #1b1b1f}h3{font-size:1.08rem;margin:1.6em 0 .3em}h4{font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;margin:1.1em 0 .3em;color:#444}
.status{border:2px solid #1b1b1f;padding:10px 14px;margin:14px 0;font-family:system-ui,sans-serif}.status.draft{background:#fff3c4}.meta{font-family:system-ui,sans-serif;color:#444;font-size:.92rem}
pre{white-space:pre-wrap;font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;border:1px solid #999;padding:12px;margin:.4em 0;overflow-x:auto}.sheet{break-inside:avoid}table{border-collapse:collapse;width:100%;font-family:system-ui,sans-serif;font-size:.9rem}td,th{border:1px solid #999;padding:6px 8px;text-align:left;vertical-align:top}
.min{font-family:system-ui,sans-serif;font-size:.85rem;color:#444;font-variant-numeric:tabular-nums}@media print{h2{break-before:page}body{padding:0}}</style></head><body>`;
  const status = `<div class="status${/not ready|Simulated/i.test(pkg.readiness) ? ' draft' : ''}"><strong>${h(pkg.readiness)}</strong>${ulh(pkg.whyThisReadiness)}${pkg.threeSeparateQuestions ? `<table><tr><th>Structure</th><td>${h(pkg.threeSeparateQuestions.structure)}</td></tr><tr><th>Internal approval</th><td>${h(pkg.threeSeparateQuestions.internalApproval)}</td></tr><tr><th>Teaching readiness</th><td>${h(pkg.threeSeparateQuestions.teachingReadiness)}</td></tr></table>` : ''}<span class="meta">Version ${h(pkg.version)} · exported ${h(String(pkg.exportedAt).slice(0, 10))} · for Glitch staff. Not published.${pkg.standingAtApproval ? ' ' + h(pkg.standingAtApproval.taughtToLearners) : ''}</span></div>`;
  const top = `<h1>${h(c.outcome)}</h1><p class="meta">${h(c.format)} · ${h(c.audience)} · ${h(c.delivery)} · ${h(c.planned.duration)}${c.plannedDiffersFromBrief ? ` (the brief asked for ${h(c.requestedInBrief.duration)})` : ''}</p>${status}`;
  const sessions = pkg.learnerMaterials.map((s, i) => {
    const t = pkg.teacherMaterials[i] || {};
    const steps = s.steps.map((x, k) => { const n = (t.stepNotes || [])[k] || {};
      return `<h3>${k + 1}. ${h(x.title || x.step)} <span class="min">${h(x.step)} · ${h(x.minutes)} min</span></h3>${x.goal ? `<p>${h(x.goal)}</p>` : ''}${ol(x.instructions) || (x.what ? `<p>${h(x.what)}</p>` : '')}
        ${pre('Handout', x.handout)}${teacher ? pre('Worked example, for the teacher to give', x.workedExample) : ''}
        ${teacher ? `${(x.materials || []).length ? `<h4>Materials</h4>${ulh(x.materials)}` : ''}${(n.guidance || []).length ? `<h4>Teacher guidance</h4>${ulh(n.guidance)}` : n.note ? `<h4>Teacher guidance</h4><p>${h(n.note)}</p>` : ''}
          ${(n.likelyMisconceptions || []).length ? `<h4>Common errors, and what to say</h4><table><tr><th>What a learner may think</th><th>Response</th></tr>${n.likelyMisconceptions.map(m => `<tr><td>${h(m.belief)}</td><td>${h(m.response)}</td></tr>`).join('')}</table>` : ''}
          ${(x.successLooksLike || []).length ? `<h4>What success looks like</h4>${ulh(x.successLooksLike)}` : ''}` : ''}`; }).join('');
    return `<h2>${h(s.session)}. ${h(s.title)} <span class="min">${h(s.minutes)} min</span></h2><p><strong>By the end you can:</strong> ${h(s.youWill)}</p>
      ${teacher ? `${(t.preparation || []).length ? `<h4>Before the session: ${h(t.preparationMinutes)} minutes of preparation</h4>${ol(t.preparation)}` : ''}${(t.prerequisites || []).length ? `<h4>What learners need first, and the support if they lack it</h4><table><tr><th>Needs</th><th>Support</th></tr>${t.prerequisites.map(q => `<tr><td>${h(q.name)}</td><td>${h(q.support)}</td></tr>`).join('')}</table>` : ''}
        ${(t.requirementsToImplement || []).length ? `<h4>Requirements from the brief, still to be confirmed by a person</h4>${ulh(t.requirementsToImplement)}` : ''}${(t.assumptions || []).length ? `<h4>What this session assumes</h4>${ulh(t.assumptions)}` : ''}` : (s.beforeYouStart || []).length ? `<h4>Before you start</h4>${ulh(s.beforeYouStart)}` : ''}
      ${(s.preparedFilesYouNeed || []).length ? `<h4>Prepared files you need for this session</h4>${s.preparedFilesYouNeed.map(preparedHTML).join('')}` : ''}${(s.files || []).length ? `<h4>Files for this session</h4>${s.files.map(fileHTML).join('')}` : ''}${teacher && (t.teacherFiles || []).length ? `<h4>Files for the teacher (solutions)</h4>${t.teacherFiles.map(fileHTML).join('')}` : ''}${teacher && (t.codeChecks || []).length ? `<h4>What running the code showed</h4>${table(['File', 'Checked', 'Output'], t.codeChecks.map(c => [c.file, c.checked, c.output || '']))}` : ''}
      ${steps}${s.afterTheMeeting ? `<h4>After the meeting: ${h(s.afterTheMeeting.independentMinutes)} minutes on your own</h4>${s.afterTheMeeting.tasks.map(k => `<h3>${h(k.title)} <span class="min">${h(k.minutes)} min</span></h3>${ol(k.instructions)}${pre('Handout', k.handout)}<h4>Check your own work</h4>${ulh(k.self_check)}<p><strong>Hand in:</strong> ${h(k.deliverable)}</p>`).join('')}` : ''}${(s.successCriteria || []).length ? `<h4>How you will know it worked</h4>${ulh(s.successCriteria)}` : ''}${s.laterCheck && s.laterCheck.task ? `<h4>Later, on your own: ${h(s.laterCheck.when)}</h4><p>${h(s.laterCheck.task)}</p>${teacher && t.laterCheck ? ulh(t.laterCheck.looksFor) : ''}` : ''}`; }).join('');
  const lineageHTML = teacher && pkg.evidence && pkg.evidence.worksAndHowTheyDescend ? (() => { const L = pkg.evidence.worksAndHowTheyDescend;
    return `<h2>Works this course rests on, and how they descend</h2><p>${h(L.readThisFirst)}</p>
      ${table(['Work', 'Made by', 'Published', 'Version', 'Role', 'Origin'], L.works.map(w => [w.title || w.work, (w.madeBy || []).join(', '), w.published || '', w.versionOrEdition || '', String(w.role || '').replace(/_/g, ' '), w.originIs + ((w.whyNotEstablished || []).length ? ': ' + w.whyNotEstablished.join('; ') : '') + ((w.contraryEvidenceFromOtherSightings || []).length ? ' — also seen without confirmation: ' + w.contraryEvidenceFromOtherSightings.join('; ') : '')]))}
      ${(L.originalsAndTheirExtensions || []).some(c => (c.awaitingAPersonsDecision || []).length) ? `<h3>Waiting on a person</h3><p>Two runs of the attribution review answered the same question differently on the same evidence. Nothing here is settled.</p>${table(['Original', 'Later work', 'Relation'], (L.originalsAndTheirExtensions || []).flatMap(c => (c.awaitingAPersonsDecision || []).map(x => [c.original.title || c.original.work, x.title || x.work, x.relation || ''])))}` : ''}
      ${(L.descent || []).length ? `<h3>Claimed relationships</h3>${table(['Later work', 'Relation', 'Earlier work', 'What changed', 'Words that show it', 'Standing'], L.descent.map(e => [e.laterWork, e.relation || 'not recorded', e.earlierWork || (e.earlierWorkAsNamed ? e.earlierWorkAsNamed + ' (not a work Loom holds)' : 'not named'), e.whatChanged || '', e.wordsThatShowIt || '', e.standing + ((e.whyNotSupported || []).length ? ': ' + e.whyNotSupported.join('; ') : '')]))}` : ''}` ; })() : '';
  const ev = teacher && pkg.evidence ? `<h2>Evidence</h2><p>${h(pkg.evidence.readThisFirst)}</p><table><tr><th>Source</th><th>What the page says</th><th>Limits</th><th>Standing</th></tr>${pkg.evidence.sources.map(s => `<tr><td>${h(s.id)} <a href="${h(s.url)}">${h(s.title)}</a></td><td>${h(s.whatThePageSays)}${s.excerpt ? ` <em>“${h(s.excerpt)}”</em>` : ''}</td><td>${h(s.limits)}</td><td>Reached the AI: ${h(s.pageReachedTheAI)}. Read by a person: ${s.readByAPersonOn ? h(String(s.readByAPersonOn).slice(0, 10)) : 'no'}</td></tr>`).join('')}</table>
    <h3>Claims the materials rely on</h3><table><tr><th>Session</th><th>Claim</th><th>Label</th><th>Standing</th></tr>${pkg.evidence.claims.map(x => `<tr><td>${h(x.session)}</td><td>${h(x.claim)}</td><td>${h({ fact: 'Fact', uncertain: 'Uncertain', hypothesis: 'Our judgement', fiction: 'Fiction' }[x.type] || x.type)} ${h((x.sources || []).join(', '))}</td><td>${h(x.standing)}</td></tr>`).join('')}</table>` : '';
  const out = head + top + (teacher && c.finalEvidence ? `<p><strong>How learners will show it:</strong> ${h(c.finalEvidence)}</p>` : '') + (teacher ? scopeHTML(pkg) : (c.timeAccounting ? `<p class="meta">${h(c.timeAccounting)}</p>` : '')) + preparedSectionHTML(pkg) + sessions + projectsHTML(pkg, teacher)
    + (teacher && pkg.evidence && pkg.evidence.perTopic ? `<h3>What evidence each topic has</h3>${table(['Topic', 'Role', 'Sources', 'Status'], pkg.evidence.perTopic.map(x => [x.topic, x.role.replace(/_/g, ' '), x.sources.join(', '), x.status]))}` : '') + lineageHTML + ev + '</body></html>';
  return out;
}

// Glitch Loom — the brief: questions, branching, recommendations.
// One decision per screen. Follow-ups appear only when they change the course.

export const CUSTOM = '__custom';
const val = (a, id) => a[id] ? a[id].value : undefined;
const has = (a, id, v) => Array.isArray(val(a, id)) && val(a, id).includes(v);

/* Illustrative ideas. These are NOT live trends: no research is connected. */
export const IDEAS = {
  trending: [
    { v: 'ai-work', idea: 'Working alongside AI tools', why: 'Many jobs now expect people to check and direct AI output.', who: 'College students and professionals.', make: 'A checked piece of work, with a note on what the AI got wrong.', mix: 'Any subject with written work to check: report writing, data analysis, coding.' },
    { v: 'short-video', idea: 'Short video storytelling', why: 'Short clips are a common way people now explain ideas.', who: 'School and college students.', make: 'A 60-second explainer that a stranger understands.', mix: 'Science explaining, local history, product demos.' },
    { v: 'climate-data', idea: 'Climate data you can check yourself', why: 'Public data is open, and claims about it are often contested.', who: 'Older school students and up.', make: 'One chart from open data, with its limits stated.', mix: 'Chart reading, statistics, local geography.' },
    { v: 'money', idea: 'Everyday money decisions', why: 'People make these choices early, often without any teaching.', who: 'School leavers and young adults.', make: 'A personal budget tested against a surprise cost.', mix: 'Spreadsheets, negotiation, reading contracts.' }
  ],
  next: [
    { v: 'questions', idea: 'Asking better questions', why: 'Good research starts with a question that can be answered.', who: 'Anyone starting a project.', make: 'Three interview questions, tested on a real person.', mix: 'Interviewing, design thinking, journalism.' },
    { v: 'charts', idea: 'Reading charts without being fooled', why: 'Charts persuade quickly and mislead just as quickly.', who: 'School students and up.', make: 'A misleading chart redrawn honestly.', mix: 'Statistics, news reading, presenting to a group.' },
    { v: 'explain', idea: 'Explaining your work out loud', why: 'Explaining shows what you understand and what you only copied.', who: 'Learners who already make things.', make: 'A two-minute walkthrough of one decision.', mix: 'Any making subject: design, code, craft.' },
    { v: 'paper', idea: 'Prototyping with paper', why: 'Cheap first versions make it safe to be wrong early.', who: 'Groups with few devices.', make: 'A paper version tested by another group.', mix: 'Design thinking, app design, signage and wayfinding.' }
  ],
  worlds: [
    { v: 'minecraft', idea: 'Minecraft', why: 'Its worlds run on resources, rules and trade-offs.', who: 'School students who already play.', make: 'A plan for a shared build with limited resources.', subjects: ['Systems and resource planning', 'Geometry and scale', 'Working as a team'] },
    { v: 'pokemon', idea: 'Pokémon', why: 'It is built on sorting, types and chance.', who: 'Younger school students.', make: 'A sorting system for real animals, with reasons.', subjects: ['Classification in biology', 'Probability', 'Balanced game design'] },
    { v: 'dune', idea: 'Dune', why: 'Its story turns on ecology, scarcity and power.', who: 'College students and professionals.', make: 'A map of who depends on what in a real system.', subjects: ['Ecology and scarcity', 'Systems thinking', 'Negotiation'] },
    { v: 'zelda', idea: 'The Legend of Zelda', why: 'Its puzzles teach a rule, then test it in a new place.', who: 'School and college students.', make: 'A three-room puzzle that teaches one idea.', subjects: ['Puzzle and level design', 'Spatial reasoning', 'Teaching through play'] },
    { v: 'spiderverse', idea: 'Spider-Verse films', why: 'They mix drawing styles on purpose, and the choices can be studied.', who: 'Design and animation learners.', make: 'One short scene drawn in two styles, with reasons.', subjects: ['Animation principles', 'Visual style and mood', 'Storyboarding'] }
  ]
};
export const ideaOf = (entry, v) => (IDEAS[entry] || []).find(i => i.v === v);

const TIME = {
  talk: [['t20', '20 minutes', 20], ['t45', '45 minutes', 45], ['t90', '90 minutes', 90]],
  workshop: [['half', 'Half a day', 180], ['day', 'One day', 360], ['two', 'Two days', 720]],
  clinic: [['c60', 'One hour', 60], ['c120', 'Two hours', 120], ['cweek', 'Weekly, for a month', 240]],
  weeks: [['w2', '2 weeks', 2], ['w4', '4 weeks', 4], ['w8', '8 weeks', 8]],
  once: [['s90', '90 minutes', 90], ['shalf', 'Half a day', 180], ['sday', 'One day', 360]]
};
// A format the team names itself runs week by week unless they say it happens in one go. Saved briefs without that answer keep their old meaning.
// An older saved brief has no shape answer. It was planned week by week, so it keeps that meaning, and is asked the question when next edited.
export const usesWeeks = a => val(a, 'format') === CUSTOM ? val(a, 'shape') !== 'once' : !['talk', 'workshop', 'clinic'].includes(val(a, 'format'));
// Independent time each week, in minutes: null when it was not answered or is none. The team's own words are read exactly or refused.
export function ownMinutes(a) {
  const x = a.own; if (!x || x.value === undefined || x.value === null || x.value === 'none') return null;
  if (x.value === CUSTOM) { const d = parseHours(x.text); return d.error ? null : d.minutes; }
  const m = /^i(\d+)$/.exec(String(x.value)); return m ? +m[1] * 60 : null;
}
export const timeOptions = a => usesWeeks(a) ? TIME.weeks : TIME[val(a, 'format')] || TIME.once;

// The whole time the brief asks for, before it is split into meetings.
export function rawTotal(a) {
  if (usesWeeks(a)) return null;
  const t = a.time || {};
  if (t.value === CUSTOM) { const d = parseDuration(t.text); return d.minutes || null; }
  const o = (timeOptions(a) || []).find(x => x[0] === t.value);
  return o ? o[2] : null;
}

export function fmtMin(m) { m = Math.round(m); if (m < 60) return m + ' min'; const h = Math.floor(m / 60), r = m % 60; return r ? `${h} h ${r} min` : `${h} h`; }

export const DAY_MINUTES = 360; // one day is counted as 6 teaching hours, and the screen says so
export const MIN_MINUTES = 5, MAX_MINUTES = 10 * DAY_MINUTES, MAX_WEEKS = 52, MIN_WEEKLY = 15, MAX_WEEKLY = 40 * 60;
const UNIT = [['weeks', /^(weeks?|wks?|wk|w)$/], ['days', /^(days?|d)$/], ['hours', /^(hours?|hrs?|h)$/], ['minutes', /^(minutes?|mins?|m)$/]];
const whole = n => Math.abs(n - Math.round(n)) < 1e-6;

// Reads the WHOLE answer or refuses it. Returns { weeks } or { minutes }, or { error } saying what to write instead.
export function parseDuration(text) {
  const raw = String(text ?? '').trim().toLowerCase();
  if (!raw) return { error: 'Type a length, with a unit.' };
  if (/[-‐-―−]/.test(raw)) return { error: 'Loom cannot use a minus sign or a range. Write one length, like 90 minutes.' };
  const s = raw.replace(/,/g, ' ').replace(/\band\b/g, ' ').replace(/\s+/g, ' ').trim(), re = /(\d+(?:\.\d{1,2})?)(?![\d.])\s*([a-z]+)\s*/y, got = {};
  let pos = 0;
  while (pos < s.length) {
    re.lastIndex = pos; const m = re.exec(s);
    if (!m) return { error: /\d\.\d{3,}/.test(s) ? 'Use at most two decimal places, like 1.25 hours.' : /^\d+(\.\d+)?$/.test(s) ? 'Add a unit after the number, like 90 minutes.' : 'Loom cannot read all of that. Write a number and a unit, like 90 minutes.' };
    const u = UNIT.find(x => x[1].test(m[2])); if (!u) return { error: `Loom does not know the unit “${m[2]}”. Use minutes, hours, days or weeks.` };
    if (u[0] in got) return { error: `“${u[0]}” appears twice. Write each unit once.` };
    got[u[0]] = +m[1]; pos = re.lastIndex;
  }
  if ('weeks' in got) {
    if (Object.keys(got).length > 1) return { error: 'Loom plans whole weeks. Write only weeks, like 3 weeks.' };
    if (!whole(got.weeks) || got.weeks < 1) return { error: 'Write a whole number of weeks, 1 or more.' };
    return { weeks: Math.round(got.weeks) };
  }
  if ('hours' in got && 'minutes' in got && got.minutes >= 60) return { error: 'When you give hours, keep the minutes under 60. For example 3 hours 30 minutes.' };
  if (!whole(got.weeks ?? 0)) return { error: 'Write a whole number of weeks, 1 or more.' };
  const min = (got.days || 0) * DAY_MINUTES + (got.hours || 0) * 60 + (got.minutes || 0);
  if (!Number.isFinite(min) || !whole(min)) return { error: 'That does not come to whole minutes. Try 90 minutes or 1.5 hours.' };
  if (min < MIN_MINUTES) return { error: `The shortest length Loom plans is ${MIN_MINUTES} minutes.` };
  if (min > MAX_MINUTES) return { error: 'That is longer than 10 days. For longer programmes, choose a course and write weeks.' };
  return { minutes: Math.round(min) };
}
export function readDuration(text) { const d = parseDuration(text); return d.error ? null : d; }
// Weekly time: a plain number means hours. "2 hours 30 minutes" and "90 minutes" also work.
export function parseHours(text) {
  const raw = String(text ?? '').trim().toLowerCase(); let min;
  if (!raw) return { error: 'Type the hours for each week.' };
  if (/^\d+\.\d{3,}$/.test(raw)) return { error: 'Use at most two decimal places, like 2.25.' };
  if (/^\d+(\.\d{1,2})?$/.test(raw)) min = +raw * 60;
  else { const d = parseDuration(raw.replace(/\b(a|per|each|every)\s+week\b|\/\s*week|weekly/g, ' ')); if (d.error && !d.minutes) { if (/^[-−]|\d\s*[-‐-―−]/.test(raw)) return { error: 'Loom cannot use a minus sign or a range. Write one amount, like 2.5 hours.' }; const small = /shortest/.test(d.error); if (!small) return { error: /unit|read|twice|whole minutes/.test(d.error) ? 'Write the weekly time as hours, like 2.5, or as 2 hours 30 minutes.' : d.error }; min = 0; } else if (d.weeks) return { error: 'Write the time for one week, like 2 hours.' }; else min = d.minutes; if (/\bdays?\b|\bd\b/.test(raw)) return { error: 'Write the weekly time in hours and minutes, not days.' }; }
  if (!Number.isFinite(min) || !whole(min)) return { error: 'That does not come to whole minutes. Try 2.5 hours.' };
  min = Math.round(min);
  if (min < MIN_WEEKLY) return { error: `The least Loom plans is ${MIN_WEEKLY} minutes each week.` };
  if (min > MAX_WEEKLY) return { error: 'The most Loom plans is 40 hours each week.' };
  return { minutes: min };
}
// What Loom understood, in words, so the person can check it.
export function reads(q, a) {
  const x = a[q.id]; if (!x || x.value !== CUSTOM || !String(x.text || '').trim()) return '';
  if (q.id === 'time') { const d = parseDuration(x.text); if (d.error) return ''; return d.weeks ? `${d.weeks} week${d.weeks > 1 ? 's' : ''}` : fmtMin(d.minutes) + (/\bdays?\b|\bd\b/i.test(x.text) ? ' of teaching (a day counts as 6 hours)' : ''); }
  if (q.id === 'hours' || q.id === 'own') { const d = parseHours(x.text); return d.error ? '' : fmtMin(d.minutes) + ' each week'; }
  return '';
}

/* ---------- derived topic list ---------- */
export function topicsOf(a) {
  const e = val(a, 'entry'); let list = [], world = null;
  if (e === 'have') list = [val(a, 'topic')];
  else if (e === 'trending' || e === 'next') { const p = a.pick; if (p) list = [p.value === CUSTOM ? p.text : (ideaOf(e, p.value) || {}).idea]; }
  else if (e === 'worlds') { const p = a.pick; if (p) { world = p.value === CUSTOM ? p.text : (ideaOf(e, p.value) || {}).idea; const s = a.worldSubject; list = [s ? (s.value === CUSTOM ? s.text : s.value) : world]; } }
  else if (e === 'mix') list = (val(a, 'mix') || []).slice(); // never trimmed here: too many topics is a validation error, not a silent cut
  list = list.map(s => String(s || '').trim()).filter(Boolean);
  return { list, world, mode: e === 'mix' ? val(a, 'mode') : null };
}

/* ---------- the questions ---------- */
const opt = (v, label) => ({ v, label });

// How the time is split into meetings. Loom can work it out, or the team can say it.
// A pattern is n meetings of m minutes. Only splits that use the whole time are offered.
// The time a pattern splits: the whole time for a one-off, or the time each week for a weekly format.
export function patternBase(a) {
  if (!usesWeeks(a)) return rawTotal(a);
  if (!a.hours) return null;
  const d = a.hours.value === CUSTOM ? parseHours(a.hours.text) : parseHours(String(a.hours.value));
  return d.error ? null : d.minutes;
}
export function patternOptions(a) {
  const rq = patternBase(a), weekly = usesWeeks(a);
  if (rq == null) return [];
  const out = [];
  for (const n of [1, 2, 3, 4, 5, 6, 8]) {
    if (n > 1 && rq % n) continue;
    const per = rq / n;
    if (per < MIN_MINUTES || per > 8 * 60) continue;
    if (weekly && n > 5) continue;
    out.push([`p${n}`, (n === 1 ? `One meeting of ${fmtMin(per)}` : `${n} meetings of ${fmtMin(per)}`) + (weekly ? ' each week' : ''), n, per]);
  }
  return out.slice(0, 5);
}
// "4 x 45", "4 meetings of 45 minutes", "2 of 90". Returns { n, per } or { error }.
export function parsePattern(text, total, weeklyHint) {
  const s = String(text || '').trim().toLowerCase();
  if (!s) return { error: 'Write how many meetings and how long each one is, like 4 x 45 minutes.' };
  const m = s.replace(/\b(a|per|each|every)\s+week\b|\/\s*week|weekly/g, ' ').trim().match(/^(\d{1,2})\s*(?:x|×|\*|meetings? of|of|sessions? of|blocks? of)\s*(.+)$/);
  if (!m) return { error: 'Write it as a number of meetings and a length, like 4 x 45 minutes.' };
  const n = Number(m[1]);
  if (!Number.isInteger(n) || n < 1 || n > 40) return { error: 'Loom plans between 1 and 40 meetings.' };
  const d = parseDuration(m[2].match(/^\d+$/) ? m[2] + ' minutes' : m[2]);
  if (d.error || !d.minutes) return { error: d.error || 'Loom could not read how long each meeting is.' };
  if (d.minutes < MIN_MINUTES) return { error: `The shortest meeting Loom plans is ${MIN_MINUTES} minutes.` };
  if (total != null && n * d.minutes !== total) return { error: `${n} meetings of ${fmtMin(d.minutes)} is ${fmtMin(n * d.minutes)}. The brief says ${fmtMin(total)}${weeklyHint ? ' each week' : ''}. Change one of them so they agree.` };
  return { n, per: d.minutes };
}
export const Q = [
  { id: 'format', station: 0, sub: 0, type: 'single', title: 'What are we making?', short: 'Format', custom: 'Something else',
    options: () => [opt('course', 'Course'), opt('workshop', 'Workshop'), opt('cohort', 'Cohort programme'), opt('talk', 'Talk'), opt('clinic', 'Clinic')] },
  { id: 'shape', station: 0, sub: 1, type: 'single', title: 'Does it happen in one go, or week by week?', short: 'Shape', hint: 'Loom needs this to plan the time. A design jam or a hack day happens in one go. A residency or a study group runs week by week.',
    when: a => val(a, 'format') === CUSTOM, options: () => [opt('once', 'In one go'), opt('weeks', 'Week by week')] },
  { id: 'entry', station: 1, sub: 0, type: 'single', title: 'Where should the topic come from?', short: 'Topic source',
    options: () => [opt('have', 'I have a topic'), opt('trending', 'Trending now'), opt('next', 'Worth learning next'), opt('mix', 'Mix topics'), opt('worlds', 'Popular worlds and IPs')] },
  { id: 'topic', station: 1, sub: 1, type: 'text', title: 'What is the topic?', short: 'Topic', placeholder: 'For example: fermentation, negotiation, orbits',
    when: a => val(a, 'entry') === 'have' },
  { id: 'pick', station: 1, sub: 1, type: 'ideas', short: 'Starting idea', custom: 'Type my own',
    title: a => val(a, 'entry') === 'worlds' ? 'Which world should inspire it?' : 'Which idea should we start from?',
    when: a => ['trending', 'next', 'worlds'].includes(val(a, 'entry')),
    options: a => (IDEAS[val(a, 'entry')] || []).map(i => opt(i.v, i.idea)) },
  { id: 'worldSubject', station: 1, sub: 2, type: 'single', title: 'What real subject should it teach?', short: 'Real subject', custom: 'Another subject', rec: true,
    when: a => val(a, 'entry') === 'worlds' && !!a.pick,
    options: a => { const i = ideaOf('worlds', val(a, 'pick')); return (i ? i.subjects : ['Storytelling', 'Systems thinking', 'Design']).map(s => opt(s, s)); } },
  { id: 'mix', station: 1, sub: 1, type: 'chips', title: 'Which topics should we weave?', short: 'Topics', placeholder: 'Add a topic', min: 2, max: 3, hint: 'Two or three. With more, no single task can give each topic real work to do, and sessions turn into a tour. For four or more, plan linked courses.',
    when: a => val(a, 'entry') === 'mix' },
  { id: 'mode', station: 1, sub: 2, type: 'single', title: 'How should they connect?', short: 'Connection', rec: true,
    when: a => val(a, 'entry') === 'mix',
    options: () => [opt('shared', 'One shared project'), opt('linked', 'Linked chapters'), opt('separate', 'Keep them separate')] },
  { id: 'audience', station: 2, sub: 0, type: 'single', title: 'Who is it for?', short: 'Audience', custom: 'Someone else',
    options: () => [opt('school', 'School students'), opt('college', 'College students'), opt('pro', 'Working professionals'), opt('mixed', 'A mixed group')] },
  { id: 'group', station: 2, sub: 1, type: 'single', title: 'How many learners at a time?', short: 'Group size', optional: true, custom: 'Another number', customHint: 'Write a number, like 18.', hint: 'It changes grouping, print counts and how much a teacher can check. If nobody knows yet, say so: Claude will then state the size it planned for.',
    options: () => [opt('g8', 'Up to 8'), opt('g20', '9 to 20'), opt('g40', '21 to 40'), opt('unknown', 'Not known yet')] },
  { id: 'prior', station: 3, sub: 0, type: 'single', title: 'How much do they already know?', short: 'Starting point', custom: 'Let me describe it', customHint: 'Say what they can already do, and what they cannot.',
    options: () => [opt('new', 'New to it'), opt('some', 'Some basics'), opt('solid', 'Already practising'), opt('unsure', 'Not sure yet')] },
  { id: 'priorMix', station: 3, sub: 1, type: 'text', optional: true, title: 'Do they know some of these topics better than others?', short: 'Uneven experience', placeholder: 'For example: confident with spreadsheets, new to budgeting', hint: 'Leave this empty if they start level, or if you do not know.',
    when: a => val(a, 'entry') === 'mix' && ((a.mix || {}).value || []).length > 1 },
  { id: 'outcome', station: 4, sub: 0, type: 'text', title: 'What should they be able to do on their own?', short: 'Outcome', placeholder: 'Start with a verb: build, explain, test…', suggest: true },
  { id: 'delivery', station: 5, sub: 0, type: 'single', title: 'How will it run?', short: 'Delivery', rec: true,
    options: a => ['talk', 'clinic'].includes(val(a, 'format')) ? [opt('room', 'In a room'), opt('live', 'Online, live'), opt('hybrid', 'Room and online together')] : [opt('live', 'Online, live'), opt('room', 'In a room'), opt('hybrid', 'Room and online together'), opt('self', 'Self-paced'), opt('blended', 'Blended: some live, some in your own time')] },
  { id: 'split', station: 5, sub: 1, type: 'single', optional: true, title: 'How much is done together, live?', short: 'Live and own time', hint: 'It decides which tasks need a teacher present and which must explain themselves. Leave it open if you do not know yet.',
    when: a => ['blended', 'self'].includes(val(a, 'delivery')) || (usesWeeks(a) && ['live', 'room', 'hybrid'].includes(val(a, 'delivery'))),
    options: a => val(a, 'delivery') === 'self' ? [opt('none', 'Nothing live. All in their own time'), opt('checkin', 'Own time, with a short live check-in')] : [opt('mostlive', 'Mostly live, with a little to do alone'), opt('half', 'About half and half'), opt('mostown', 'Mostly alone, with short live sessions')] },
  { id: 'time', station: 6, sub: 0, type: 'single', title: 'How much time is there?', short: 'Time', custom: 'A different length', rec: true, customHint: a => usesWeeks(a) ? 'Write it in weeks, like 12 weeks.' : 'Write it in minutes, hours or days, like 75 minutes. A day counts as 6 teaching hours.',
    options: a => timeOptions(a).map(t => opt(t[0], t[1])) },
  { id: 'hours', station: 6, sub: 1, type: 'single', title: 'How many hours each week?', short: 'Weekly hours', custom: 'Another amount', rec: true, customHint: 'Write hours, like 2.5, or 2 hours 30 minutes.',
    when: a => usesWeeks(a), options: () => [opt('2', '2 hours'), opt('4', '4 hours'), opt('6', '6 hours')] },
  { id: 'pattern', station: 6, sub: 2, type: 'single', title: a => usesWeeks(a) ? 'How are those hours met each week?' : 'How should that time be split into meetings?', short: 'Meetings', custom: 'Another pattern', rec: true, optional: true,
    customHint: a => { const tot = patternBase(a), wk = usesWeeks(a); return `Write how many meetings and how long each one is, like ${wk ? '2 x 60 minutes' : '4 x 45 minutes'}${tot ? `. They must add up to ${fmtMin(tot)}${wk ? ' each week' : ''}` : ''}.`; },
    hint: a => usesWeeks(a) ? 'This decides how many meetings there are each week and how long each one runs. One meeting a week is the usual answer; leave it to Loom if it does not matter yet.' : 'This decides how many meetings there are and how long each one runs. Leave it to Loom if the shape does not matter yet.',
    when: a => patternBase(a) != null && patternBase(a) >= 2 * MIN_MINUTES,
    options: a => [opt('auto', 'Let Loom split it'), ...patternOptions(a).map(p => opt(p[0], p[1]))] },
  { id: 'own', station: 6, sub: 3, type: 'single', optional: true, title: 'How much independent work each week, outside the meetings?', short: 'Independent time', custom: 'Another amount', customHint: 'Write hours, like 2, or 1 hour 30 minutes.',
    hint: 'Time learners work alone, on top of the meetings. Loom counts it apart from the live time, so no hour is counted twice. Leave it if there is none.',
    when: a => usesWeeks(a) && !!a.hours && parseHours(a.hours.value === CUSTOM ? a.hours.text : String(a.hours.value)).minutes >= 2 * MIN_MINUTES,
    options: () => [opt('none', 'None'), opt('i1', '1 hour a week'), opt('i2', '2 hours a week'), opt('i3', '3 hours a week')] },
  { id: 'limits', station: 7, sub: 0, type: 'multi', title: 'Anything we must work around?', short: 'Constraints', exclusive: 'none', custom: 'Something else', groups: [{ name: 'device option', of: ['phones', 'laptops', 'nodevice'] }], hint: 'Choose any that apply. Pick only one device option.',
    options: () => [opt('phones', 'Phones only'), opt('laptops', 'Laptops available'), opt('nodevice', 'No devices'), opt('lowweb', 'Weak internet'), opt('free', 'Free tools only'), opt('language', 'Not in English'), opt('access', 'Accessibility needs'), opt('room', 'Only certain materials or furniture'), opt('none', 'Nothing special')] },
  { id: 'room', station: 7, sub: 1, type: 'text', title: 'What is there to work with?', short: 'Materials and room', placeholder: 'For example: chairs only, paper, markers, sticky notes', hint: 'List everything. Loom treats this list as complete: nothing else will be assumed.',
    when: a => has(a, 'limits', 'room') },
  { id: 'language', station: 7, sub: 1, type: 'text', title: 'Which language will it be taught in?', short: 'Language', placeholder: 'For example: Hindi, Tamil, Spanish',
    when: a => has(a, 'limits', 'language') },
  { id: 'access', station: 7, sub: 2, type: 'multi', title: 'Which needs should we plan for?', short: 'Accessibility', custom: 'Something else',
    when: a => has(a, 'limits', 'access'),
    options: () => [opt('reader', 'Screen reader users'), opt('vision', 'Low vision'), opt('hearing', 'Deaf or hard of hearing'), opt('motor', 'Limited hand movement'), opt('load', 'Reading or attention load')] }
];
export const byId = id => Q.find(q => q.id === id);
export const activePath = a => Q.filter(q => !q.when || q.when(a));
export const titleOf = (q, a) => typeof q.title === 'function' ? q.title(a) : q.title;

/* ---------- validity ---------- */
export function problem(q, a) {
  const x = a[q.id];
  if (q.optional && (!x || x.value === undefined || x.value === null || (q.type === 'text' && !String(x.value).trim()))) return ''; // may be left unanswered
  if (q.id === 'group' && x && x.value === CUSTOM && !/^\s*[1-9]\d{0,2}\s*$/.test(String(x.text || ''))) return 'Write a whole number of learners, from 1 to 999.';
  if (q.type === 'text') return x && String(x.value || '').trim().length >= 2 ? '' : 'Type an answer to continue.';
  if (q.type === 'chips') { const l = x && Array.isArray(x.value) ? x.value : []; if (l.some(t => !String(t).trim())) return 'One topic is blank. Remove it or type a name.'; if (new Set(l.map(t => String(t).trim().toLowerCase())).size !== l.length) return 'Two topics have the same name. Remove one.'; if (l.length > q.max) return `Loom weaves at most ${q.max} topics. Remove ${l.length - q.max}.`; return l.length >= q.min ? '' : `Add at least ${q.min} topics.`; }
  if (q.type === 'multi') { if (!x || !x.value || !x.value.length) return 'Choose at least one.';
    if (q.exclusive && x.value.includes(q.exclusive) && x.value.length > 1) return 'You chose “Nothing special” together with other answers. Keep one or the other.';
    for (const g of q.groups || []) { const hit = q.options(a).filter(o => g.of.includes(o.v) && x.value.includes(o.v)); if (hit.length > 1) return `${hit.map(o => '“' + o.label + '”').join(' and ')} cannot all be true. Keep one ${g.name}.`; } if (x.value.includes(CUSTOM) && !String(x.text || '').trim()) return 'Type your own answer in the box, or untick “' + q.custom + '”.'; return ''; }
  if (!x || x.value === undefined || x.value === null) return 'Choose one to continue.';
  if (x.value === CUSTOM) { if (!String(x.text || '').trim()) return 'Type your own answer.'; if (q.id === 'time') { const d = parseDuration(x.text), wk = usesWeeks(a); if (d.error) return d.error; if (wk && !d.weeks) return 'This format runs week by week. Write the length in weeks, like 12 weeks.'; if (!wk && !d.minutes) return 'This format is planned in minutes, hours or days. Try 75 minutes or 2 days.'; } if (q.id === 'hours' || q.id === 'own') { const d = parseHours(x.text); if (d.error) return d.error; } return ''; }
  if (q.options && !q.options(a).some(o => o.v === x.value)) return 'That earlier answer no longer fits. Choose again.';
  return '';
}
export function labelOf(q, a) {
  const x = a[q.id]; if (!x) return '';
  const name = v => v === CUSTOM ? String(x.text || '').trim() + (reads(q, a) ? ` (read as ${reads(q, a)})` : '') : ((q.options ? q.options(a) : []).find(o => o.v === v) || allLabels(q)[v] || { label: v }).label || v;
  if (q.type === 'text') return x.value || '';
  if (q.type === 'chips') return (x.value || []).join(' + ');
  if (q.type === 'multi') return (x.value || []).map(name).join(', ');
  return name(x.value);
}
function allLabels(q) { const m = {}; if (q.id === 'own') Object.assign(m, { none: { label: 'None' }, i1: { label: '1 hour a week' }, i2: { label: '2 hours a week' }, i3: { label: '3 hours a week' } }); if (q.id === 'time') for (const k in TIME) for (const t of TIME[k]) m[t[0]] = { label: t[1] }; if (q.id === 'delivery') Object.assign(m, { self: { label: 'Self-paced' }, live: { label: 'Online, live' }, room: { label: 'In a room' }, blended: { label: 'Blended' }, hybrid: { label: 'Room and online together' } }); if (q.id === 'pick') for (const k in IDEAS) for (const i of IDEAS[k]) m[i.v] = { label: i.idea }; return m; }

/* ---------- dependencies and review flags ---------- */
export const DEPS = { outcome: ['topic', 'format'], delivery: ['audience', 'format'], time: ['format', 'prior'], hours: ['audience'], mode: ['topic'], worldSubject: ['world'] };
const DEPNAME = { topic: 'the topic', format: 'the format', audience: 'the audience', prior: 'the starting point', world: 'the chosen world' };
export function digests(a) { const t = topicsOf(a); return { topic: t.list.join('|').toLowerCase(), world: String(t.world || ''), format: String(val(a, 'format') || '') + (a.format && a.format.text || ''), audience: String(val(a, 'audience') || '') + (a.audience && a.audience.text || ''), prior: String(val(a, 'prior') || '') }; }
export function basis(id, a) { const d = digests(a), o = {}; for (const k of DEPS[id] || []) o[k] = d[k]; return o; }
export function reviewNote(q, a) {
  const x = a[q.id]; if (!x) return '';
  if (x.source === 'recommended' && x.basedOn) { const d = digests(a), ch = Object.keys(x.basedOn).filter(k => x.basedOn[k] !== d[k]); if (ch.length) return `Suggested earlier, before you changed ${ch.map(k => DEPNAME[k]).join(' and ')}.`; }
  if (q.type === 'single' && x.value !== CUSTOM && q.options && !q.options(a).some(o => o.v === x.value)) return 'This answer no longer fits an earlier choice.';
  return '';
}
export const briefDigest = a => JSON.stringify(activePath(a).filter(q => !(q.optional || q.id === 'shape') || (a[q.id] && String(a[q.id].value ?? '').trim())).map(q => [q.id, a[q.id] ? a[q.id].value : null, a[q.id] ? a[q.id].text || '' : '']));

/* ---------- "Recommend for me": provisional suggestions from simple rules ----------
   Nothing here is researched. Each suggestion states the assumption it rests on, so the person can reject it. */
export function recommend(q, a) {
  const r = suggest(q, a); if (!r || !q.options) return r;
  // A suggestion must be one of the answers on offer for this brief. If the rule's pick is not, the first answer on offer is suggested and the reason says so.
  const on = q.options(a); if (on.some(o => o.v === r.v)) return r;
  return on.length ? { v: on[0].v, why: 'This is simply the first length on offer for this format. Nothing was compared. Change it to fit.' } : null;
}
function suggest(q, a) {
  const f = val(a, 'format'), au = val(a, 'audience'), pr = val(a, 'prior'), t = topicsOf(a);
  if (q.id === 'delivery') {
    if (f === 'talk' || f === 'clinic') return { v: 'room', why: 'Assumes everyone can be in one place. If some cannot, choose online, or room and online together.' };
    if (au === 'pro') return { v: 'live', why: 'Assumes learners are in different places and free at the same time. Change it if they share a workplace.' };
    if (au === 'school') return { v: 'room', why: 'Assumes learners already meet in one place, such as a classroom.' };
    return { v: 'blended', why: 'Assumes learners can do short tasks alone and can also meet. Change it if either is untrue.' };
  }
  if (q.id === 'time') {
    if (f === 'talk') return { v: 't45', why: 'Assumes one idea and one activity. Choose longer if you have more to cover.' };
    if (f === 'workshop') return pr === 'new' || pr === 'unsure' ? { v: 'day', why: 'Assumes beginners need time on the basics before making anything. A rule of thumb, not a measurement.' } : { v: 'half', why: 'Assumes learners already know the basics.' };
    if (f === 'clinic') return { v: 'c60', why: 'Assumes learners bring a few real problems to work on.' };
    if (!usesWeeks(a)) return pr === 'new' || pr === 'unsure' ? { v: 'shalf', why: 'Assumes beginners need time on the basics before making anything. A rule of thumb, not a measurement.' } : { v: 's90', why: 'Assumes learners already know the basics and one task fits.' };
    return pr === 'solid' ? { v: 'w2', why: 'Assumes learners can start a project straight away.' } : { v: 'w4', why: 'Assumes learners need time to make, test and improve once.' };
  }
  if (q.id === 'hours') return au === 'pro' ? { v: '2', why: 'Assumes learners fit this around other work. Ask them if you can.' } : { v: '4', why: 'Assumes two sessions a week of about two hours each.' };
  if (q.id === 'mode') return t.list.length >= 2 ? { v: 'shared', why: 'Assumes one task can be found that needs every topic. This prototype does not check whether such a task exists.' } : { v: 'linked', why: 'Assumes each topic is clearer taught on its own first.' };
  if (q.id === 'worldSubject') { const o = q.options(a)[0]; return { v: o.v, why: 'This is simply the first subject listed for that world. Nothing was compared.' }; }
  return null;
}
export function outcomeIdeas(a) {
  const t = topicsOf(a), f = val(a, 'format'), T = t.list.length ? t.list.join(' and ') : 'the topic';
  const out = [`Make a small working example of ${T} and explain two choices`, `Use ${T} on a problem they have not seen before`];
  if (f === 'talk') out.unshift(`Explain ${T} to a friend in two minutes`);
  if (t.world) out.push(`Tell apart fact, guess and fiction about ${T} in ${t.world}`);
  if (t.list.length > 1) out.push(`Finish one task that needs both ${t.list[0]} and ${t.list[1]}`);
  return out.slice(0, 3);
}

// Glitch Loom — interface. Internal Glitch tool.
// Courses are kept as files by the local server. Real content comes from Claude and is labelled; simulated content is labelled too.
import { createWorld, THREADS } from './world.js';
import * as F from './flow.js';
import * as J from './journey.js';
import * as R from './real.js';
import * as V from './v2.js';
import * as Store from './store.js';
import { api, STORE } from './api.js';

const CUSTOM = F.CUSTOM, fresh = Store.fresh;
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ui = $('#ui'), sheet = $('#sheet'), picker = $('#picker'), liveEl = $('#live');
const say = t => { liveEl.textContent = ''; setTimeout(() => { liveEl.textContent = t; }, 30); };
const clone = o => JSON.parse(JSON.stringify(o));
const day = iso => { const d = new Date(iso); return Number.isNaN(+d) ? '' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); };
const clock = iso => { const d = new Date(iso); return Number.isNaN(+d) ? '' : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u; } };
const newId = () => 'e' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

/* ---------- state ---------- */
let S = fresh(), course = { id: '', version: 0, name: '', named: false }, booted = false;
let recovery = null, conflict = false, unsent = null, fatal = '', bootNote = '', HEALTH = {};
let storageOk = true, saving = false, dirty = false, saveReason = null, saveTimer = 0, lastRaw = '';
let IDEAS = null, ideaTimer = 0; // topic research for this course: none, running, done or failed
let ENG = { ready: false, blocker: 'Loom is still checking the Claude tool.', checking: true }, E = null, EBusy = false, pollTimer = 0, LIB = { courses: [], imports: [] }, repaintLater = false;

const UNSENT = () => `glitch-loom/unsent/${STORE === null ? '-' : STORE}/${course.id}`;
// The library's record holds the course's name. A name given on purpose (a rename, a copy, a restore) stays until it is renamed.
// Only a course nobody has named takes its name from the brief's topics.
const courseName = () => ((course.named && course.name) || S.name || F.topicsOf(S.answers).list.join(' + ') || 'Untitled course').slice(0, 120);
function summaryOf() { const j = S.journey; return { stage: S.life.stage, ver: S.life.ver, topics: F.topicsOf(S.answers).list, format: S.answers.format ? F.labelOf(F.byId('format'), S.answers) : '', sessions: j ? j.sessions.length : 0, made: j ? (J.isReal(j) ? 'claude' : 'simulated') : '', approved: S.life.snapshots.filter(s => !J.readinessOf(s).draft).length, internalDrafts: S.life.snapshots.filter(s => J.readinessOf(s).draft).length, counted: true }; }

// Every change is sent to the server and written to disk. A failure is shown at once and stays visible until a save works again.
// Until the disk has it, the latest state is also held in this browser, so a crash cannot lose it.
function save(reason) {
  if (!booted || recovery || conflict || unsent || !course.id) { paintSave(); return false; }
  const now = JSON.stringify(S); if (now === lastRaw && !reason && !dirty) { paintSave(); return true; } // nothing new to write
  dirty = true; if (reason) saveReason = reason;
  try { localStorage.setItem(UNSENT(), JSON.stringify({ at: Date.now(), baseVersion: course.version, raw: now })); } catch (e) { }
  clearTimeout(saveTimer); saveTimer = setTimeout(flush, reason ? 0 : 350); paintSave(); return true;
}
async function flush(opts = {}) {
  if (saving || !dirty || recovery || conflict || unsent || !course.id) return;
  saving = true; dirty = false; const raw = JSON.stringify(S), reason = saveReason; saveReason = null; paintSave();
  try {
    const m = await api.put(course.id, { raw, baseVersion: course.version, name: courseName(), summary: summaryOf(), reason }, opts);
    course.version = m.version; course.name = m.name; course.named = !!m.named; lastRaw = raw; const was = storageOk; storageOk = true;
    if (!dirty) { try { localStorage.removeItem(UNSENT()); } catch (e) { } }
    if (!was) say('Saving works again. Your work is saved.');
  } catch (e) {
    if (e.status === 409) conflict = true;
    else { const was = storageOk; storageOk = false; dirty = true; if (reason) saveReason = reason; if (was) say('Not saved. Loom’s local server did not take the save.'); clearTimeout(saveTimer); saveTimer = setTimeout(flush, 4000); }
  }
  saving = false; paintSave(); paintBrand();
  if (conflict) softRender();
  else if (dirty && storageOk) { clearTimeout(saveTimer); saveTimer = setTimeout(flush, 200); }
}
async function flushNow() { clearTimeout(saveTimer); for (let i = 0; i < 40 && (saving || dirty) && storageOk && !conflict; i++) { if (!saving) await flush(); else await new Promise(r => setTimeout(r, 50)); } return !dirty && !saving; }
function paintSave() {
  const paused = !!recovery || conflict || !!unsent, w = $('#savewarn'); if (w) w.hidden = storageOk || paused;
  $$('.savestate').forEach(e => { e.textContent = paused ? 'Saving is paused' : !storageOk ? 'Not saved' : (saving || dirty) ? 'Saving…' : 'Saved'; e.classList.toggle('bad', !storageOk || paused); });
}
function paintBrand() {
  const b = $('#coursebtn'); if (b) { b.hidden = !booted; b.querySelector('span').textContent = recovery ? (recovery.name || 'Unreadable course') : courseName(); }
  const bn = $('#bootnote'); if (bn) { bn.hidden = !bootNote; bn.querySelector('span').textContent = bootNote; }
  const s = $('.brand .sub'); if (s) s.textContent = STORE === null ? 'Internal Glitch tool' : `Internal Glitch tool · test storage “${STORE}”`;
}
window.addEventListener('pagehide', () => { if (dirty && !saving) flush({ keepalive: true }); });

/* ---------- world ---------- */
const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
const forceReduce = /[?&]motion=reduce/.test(location.search);
const world = createWorld($('#world'));
const applyMotion = () => { const r = forceReduce || mq.matches; world.setReduce(r); document.documentElement.toggleAttribute('data-reduce', r); };
applyMotion(); mq.addEventListener && mq.addEventListener('change', applyMotion);

const AFTER = ['summary', 'generate', 'outline', 'journey', 'session', 'activity', 'checks', 'project'];
function guessSessions() { if (S.journey) return S.journey.sessions.length; if (E && E.plan && ['generate', 'outline'].includes(S.at)) return E.plan.sessions; if (!S.answers.time) return 0; try { return J.request(S.answers).n || 0; } catch (e) { return 0; } }
function passed(id) { const p = F.activePath(S.answers), i = p.findIndex(q => q.id === id), j = p.findIndex(q => q.id === S.at); return AFTER.includes(S.at) || (j > i && i >= 0); }
function sync(opts = {}) {
  const a = S.answers, t = F.topicsOf(a), out = (a.outcome && a.outcome.value || '').trim();
  const inJ = ['journey', 'session', 'activity', 'checks', 'project'].includes(S.at), written = S.journey ? S.journey.sessions.filter(s => s.status !== 'pending' && s.status !== 'failed').length : 0;
  world.setVis({ format: a.format && a.format.value, entry: a.entry && a.entry.value, topics: t.list, mode: t.mode, world: !!t.world, audience: a.audience && a.audience.value, prior: a.prior && a.prior.value,
    outcome: out.length < 2 ? 0 : passed('outcome') ? 1 : Math.min(1, .25 + out.length / 30), delivery: a.delivery && a.delivery.value, sessions: guessSessions(), turn: S.turn, limits: (a.limits && a.limits.value) || [],
    lit: (inJ && !!S.journey) || (S.at === 'generate' && written > 0), sel: ['session', 'activity'].includes(S.at) && S.journey ? S.journey.sessions.findIndex(s => s.id === S.sel) : -1 });
  const q = F.byId(S.at); if (q && !recovery && !unsent) world.go(q.station, q.sub, opts);
  else world.go(8, { summary: -2, generate: -1, outline: -1, checks: 1 }[S.at] || 0, Object.assign({ centre: S.at === 'journey' }, opts));
}

/* ---------- answers ---------- */
function setAnswer(q, patch, source) {
  const x = Object.assign({}, S.answers[q.id], patch);
  x.source = source || (x.value === CUSTOM ? 'custom' : 'picked');
  if (x.source === 'recommended') x.basedOn = F.basis(q.id, S.answers); else { delete x.basedOn; delete x.why; }
  S.answers[q.id] = x; if (q.id === 'time' || q.id === 'hours') S.turn++;
  save(); sync();
}
const stale = () => !!S.journey && S.jDigest !== F.briefDigest(S.answers);
const real = () => J.isReal(S.journey);
const engineActive = () => !!E && (E.status === 'running' || EBusy);
const engineOurs = () => !!E && !!S.journey && S.journey.engineRun === E.startedAt;

/* ---------- pieces ---------- */
const pill = (v, label, multi, on, extra = '') => `<button type="button" class="pill${extra}" role="${multi ? 'checkbox' : 'radio'}" aria-checked="${on}" data-a="pick" data-v="${esc(v)}"><span class="mk" aria-hidden="true"></span><span>${esc(label)}</span></button>`;
const madeTag = j => J.isReal(j) ? `<button type="button" class="sim made" data-a="sim" aria-expanded="${S.simOpen}">Written with Claude</button>` : `<button type="button" class="sim" data-a="sim" aria-expanded="${S.simOpen}">Simulated example</button>`;
const simTag = () => madeTag(S.journey);
const simNote = () => !S.simOpen ? '' : real()
  ? `<p class="simnote swap">Claude wrote this from your brief and from sources it found on the web. Nobody on the team has checked it unless a part says so. Sources show whether a person has read them. Read before you approve.</p>`
  : `<p class="simnote swap">No AI or research ran here. Fixed rules assembled this from your answers, so it reflects your choices but is not real generated or checked content. Choose “Weave with Claude” on the brief for real content.</p>`;
const ul = (items, cls = 'bul') => items && items.length ? `<ul class="${cls}">${items.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '';
const more = (title, body, open) => body ? `<details class="more"${open ? ' open' : ''}><summary>${esc(title)}</summary>${body}</details>` : '';
const H = { esc, more: (t, b, o) => more(t, b, o), ul: (i, c) => ul(i, c), host, clock, day };
const dots = th => th.map(t => `<i style="background:${THREADS[t % 4]}"></i>`).join('');

function detailHTML(q) {
  const a = S.answers, x = a[q.id] || {}; let h = '';
  const rd = F.reads(q, a); if (rd) h += `<p class="why" id="reads"><span class="tag">Loom reads this as</span> ${esc(rd)}</p>`;
  if (x.source === 'recommended' && x.why) h += `<p class="why"><span class="tag">Provisional</span> ${esc(x.why)} <span class="dim">A simple rule picked this. Nothing was researched.</span></p>`;
  if (q.type === 'ideas' && x.value && x.value !== CUSTOM) { const i = F.ideaOf(a.entry.value, x.value); if (i) h += `<dl class="idea"><dt>Why it matters</dt><dd>${esc(i.why)}</dd><dt>Suits</dt><dd>${esc(i.who)}</dd><dt>They could make</dt><dd>${esc(i.make)}</dd>${i.mix ? `<dt>Combines with</dt><dd>${esc(i.mix)}</dd>` : ''}${i.subjects ? `<dt>Real subjects it can carry</dt><dd>${esc(i.subjects.join(', '))}</dd>` : ''}</dl><p class="dim">Illustrative. Loom has no dated evidence that this is popular or rising. Treat it as a starting idea.</p>`; }
  return h;
}
function ideasNote(q) {
  if (q.type !== 'ideas') return '';
  const e = S.answers.entry.value;
  if (e === 'worlds') return `<p class="note"><span class="tag">Inspiration only</span> Loom will not copy characters, art or text. Rights stay with their owners.</p>`;
  const kind = e === 'trending' ? 'trending' : 'next', mine = IDEAS && IDEAS.kind === kind ? IDEAS : null, busy = engineActive() || (mine && mine.status === 'running');
  const ask = `<p class="pills"><button type="button" class="pill small" data-a="ideaResearch" data-v="${kind}" ${busy || !ENG.ready ? 'aria-disabled="true"' : ''}>${mine && mine.status === 'done' ? 'Research again with Claude' : 'Research this with Claude'}</button><span class="dim">Searches the web for dated pages, using your Claude plan. Nothing below changes until you choose an idea.</span></p>`;
  const fallback = e === 'trending' ? `<p class="note"><span class="tag">Illustrative</span> The examples below are not current trends. Nothing has been researched for them, and they carry no sources or dates.</p>`
    : `<p class="note"><span class="tag">Illustrative</span> The examples below were chosen for learning value, not popularity. No research ran for them.</p>`;
  if (!mine) return ask + fallback;
  if (mine.status === 'running') return `<p class="note" role="status"><span class="tag">Claude</span> Researching ${kind === 'trending' ? 'current topics' : 'what is worth learning next'}. This takes a few minutes. The examples below are illustrative until it finishes.</p>` + fallback;
  if (mine.status === 'failed') return ask + `<p class="note" role="alert"><span class="tag bad">Research failed</span> ${esc(mine.reason || 'The search did not finish.')} Nothing was found, so nothing is shown as a trend.</p>` + fallback;
  const backed = (mine.ideas || []).filter(i => i.backed), rest = (mine.ideas || []).filter(i => !i.backed);
  const one = (i, k) => `<li><strong>${esc(i.idea)}</strong> <button type="button" class="pill small" data-a="ideaUse" data-v="${k}">Use this idea</button><br>${esc(i.why_now)}<br><span class="dim">Suits: ${esc(i.suits)}. They could make: ${esc(i.make)}.${i.combines_with ? ' Combines with: ' + esc(i.combines_with) + '.' : ''}</span><br><span class="dim">What this does not show: ${esc(i.uncertainty)}</span><ul class="conn">${(i.evidence || []).map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a> <span class="dim">${esc(s.publisher)} · dated ${esc(s.dated)} · ${esc(s.what_it_says)}</span></li>`).join('')}</ul></li>`;
  return ask + `<div class="flag"><p><span class="tag ok">Researched</span> Searched on ${esc(mine.searchedOn)}${mine.hint ? ` with the steer “${esc(mine.hint)}”` : ''}.${mine.searchNote ? ' ' + esc(mine.searchNote.replace(/^\s*\d{4}-\d{2}-\d{2}\.?\s*/, '')) : ''} ${backed.length} idea${backed.length === 1 ? '' : 's'} rest on a dated page that opened. Every page is linked with the date it shows; read it before relying on it.</p>
    ${backed.length ? `<ul class="conn">${backed.map((i, k) => one(i, mine.ideas.indexOf(i))).join('')}</ul>` : '<p class="dim">No idea came back with a dated page that opened.</p>'}
    ${mine.shortfall ? `<p class="dim"><span class="tag warn">Short</span> ${esc(mine.shortfall)}</p>` : ''}
    ${rest.length ? `<p class="dim"><span class="tag warn">Not backed</span> Suggested, but no page with a date arrived for: ${esc(rest.map(i => i.idea).join('; '))}. They are not shown as trends.</p>` : ''}
    <p class="dim">The examples in the pills below are still illustrative. Choosing “Use this idea” fills in the answer; nothing is changed until you do.</p></div>`;
}
function watchIdeas() { clearInterval(ideaTimer); ideaTimer = setInterval(async () => { try { const r = await api.ideas(course.id); IDEAS = r.ideas; if (!IDEAS || IDEAS.status !== 'running') { clearInterval(ideaTimer); if (S.at === 'pick' && !typing()) softRender('#qt'); say(IDEAS && IDEAS.status === 'done' ? 'Topic research finished.' : 'Topic research stopped.'); } } catch (e) { } }, 3000); }

/* ---------- question screen ---------- */
function viewQ(q) {
  const a = S.answers, path = F.activePath(a), i = path.indexOf(q), x = a[q.id] || {}, note = F.reviewNote(q, a);
  let b = '';
  if (q.type === 'single' || q.type === 'ideas' || q.type === 'multi') {
    const multi = q.type === 'multi', cur = multi ? (x.value || []) : x.value, on = v => multi ? cur.includes(v) : cur === v;
    b += ideasNote(q) + `<p class="hint">${esc((typeof q.hint === 'function' ? q.hint(S.answers) : q.hint) || (multi ? 'Choose any that apply' : 'Choose one'))}</p><div class="pills" role="${multi ? 'group' : 'radiogroup'}" aria-labelledby="qt">`;
    q.options(a).forEach(o => { b += pill(o.v, o.label, multi, on(o.v)); });
    if (q.custom) b += pill(CUSTOM, q.custom, multi, on(CUSTOM), ' other');
    if (q.rec) b += `<button type="button" class="pill rec" data-a="rec"><span class="spark" aria-hidden="true">✦</span><span>Recommend for me</span></button>`;
    b += `</div><div class="custom" id="cwrap"${on(CUSTOM) ? '' : ' hidden'}><label class="sr" for="cin">Your own answer</label><input id="cin" type="text" autocomplete="off" value="${esc(x.text || '')}" placeholder="Type your own">${q.customHint ? `<p class="hint">${esc(typeof q.customHint === 'function' ? q.customHint(a) : q.customHint)}</p>` : ''}</div>`;
  }
  if (q.type === 'text') {
    b += `<label class="sr" for="tin">${esc(F.titleOf(q, a))}</label><textarea id="tin" rows="2" placeholder="${esc(q.placeholder || '')}">${esc(x.value || '')}</textarea>`;
    if (q.suggest) b += `<div class="pills"><button type="button" class="pill rec" data-a="suggest"><span class="spark" aria-hidden="true">✦</span><span>Recommend for me</span></button></div><div id="sug"></div>`;
  }
  if (q.type === 'chips') b += `<p class="hint">Add ${q.min} or ${q.max} topics</p><ul class="chips" id="chips">${chipsHTML(x.value || [])}</ul><div class="addrow"><label class="sr" for="chin">Topic</label><input id="chin" type="text" autocomplete="off" placeholder="${esc(q.placeholder)}"><button type="button" class="pill" data-a="addchip">Add</button></div>`;
  return `<div class="swap">
    ${progHTML(`Question ${i + 1}`, i)}
    <h1 id="qt" tabindex="-1">${esc(F.titleOf(q, a))}</h1>
    <div id="flag">${note ? flagHTML(note) : ''}</div>
    ${b}<p class="err" id="err" role="alert"></p>
    <div id="detail" aria-live="polite">${detailHTML(q)}</div>
    <div class="foot">${i > 0 || S.fromSummary ? `<button type="button" class="quiet" data-a="back">← Back</button>` : '<span></span>'}<button type="button" class="go" data-a="next">${S.fromSummary ? 'Save' : 'Continue'}</button></div>
  </div>`;
}
// Progress shows where you are and what is behind you. It never promises a total, because follow-ups depend on answers.
const progHTML = (label, done) => `<div class="prog"><span class="dots" aria-hidden="true">${'<i class="done"></i>'.repeat(Math.max(0, done))}${done >= 0 ? '<i class="now"></i>' : ''}</span><span class="px">${esc(label)} · <span class="savestate">Saved</span></span></div>`;
const flagHTML = note => `<p class="flag"><span class="tag warn">Review</span> ${esc(note)} ${/no longer fits/.test(note) ? 'Please choose again.' : 'Still right? Continue to keep it, or choose again.'}</p>`;
const chipsHTML = list => list.map((t, i) => `<li><span class="dot" style="background:${THREADS[i % 4]}"></span>${esc(t)}<button type="button" data-a="delchip" data-i="${i}" aria-label="Remove ${esc(t)}">×</button></li>`).join('');

function patchQ(q) {
  const x = S.answers[q.id] || {}, multi = q.type === 'multi';
  $$('.pill[data-v]').forEach(p => p.setAttribute('aria-checked', multi ? (x.value || []).includes(p.dataset.v) : x.value === p.dataset.v));
  const cw = $('#cwrap'); if (cw) cw.hidden = multi ? !(x.value || []).includes(CUSTOM) : x.value !== CUSTOM;
  $('#detail').innerHTML = detailHTML(q); $('#err').textContent = '';
  const n = F.reviewNote(q, S.answers); $('#flag').innerHTML = n ? flagHTML(n) : '';
  roving(); paintSave();
}
// One radio per group is reachable with Tab; arrow keys move and select, as radio groups normally do.
function roving() {
  $$('[role="radiogroup"]').forEach(g => { const r = $$('[role="radio"]', g), on = r.find(x => x.getAttribute('aria-checked') === 'true') || r[0]; r.forEach(x => { x.tabIndex = x === on ? 0 : -1; }); });
  $$('[role="tablist"]').forEach(g => $$('[role="tab"]', g).forEach(x => { x.tabIndex = x.getAttribute('aria-selected') === 'true' ? 0 : -1; }));
}

/* ---------- summary ---------- */
function staleHTML() {
  const ch = R.briefChanges(S.jBrief, S.answers);
  return `<div class="flag"><p><span class="tag warn">Changed</span> The brief has changed since the journey was made. The journey has not been touched.</p>${more(`What changed and what it affects (${ch.length})`, `<ul class="conn">${ch.map(c => `<li><strong>${esc(c.short)}</strong>: ${esc(c.was)} → ${esc(c.now)}<br><span class="dim">Affects ${esc(c.affects)}.</span></li>`).join('')}</ul>`)}</div>`;
}
function viewSummary() {
  const a = S.answers, path = F.activePath(a), bad = path.filter(q => F.problem(q, a)), cf = bad.length ? [] : J.conflicts(a), flagged = path.filter(q => !F.problem(q, a) && F.reviewNote(q, a));
  const parked = F.Q.filter(q => !path.includes(q) && a[q.id] && F.labelOf(q, a));
  const row = q => { const p = F.problem(q, a), n = F.reviewNote(q, a); return `<li><button type="button" class="rowbtn" data-a="edit" data-id="${q.id}"><span class="k">${esc(q.short)}</span><span class="v">${esc(F.labelOf(q, a)) || (q.optional ? '<em>Not given</em>' : '<em>Not answered</em>')}</span>${p ? '<span class="tag bad">Needs an answer</span>' : n ? '<span class="tag warn">Review</span>' : ''}<span class="edit" aria-hidden="true">Edit</span></button></li>`; };
  const off = bad.length || cf.length ? 'aria-disabled="true"' : '', busy = engineActive(), held = !busy && E && ['paused', 'waiting_approval'].includes(E.status);
  return `<div class="swap">
    ${progHTML('Your brief', -1)}
    <h1 id="qt" tabindex="-1">Ready to weave?</h1>
    ${flagged.length ? `<p class="flag"><span class="tag warn">Review</span> ${flagged.length} suggestion${flagged.length > 1 ? 's were' : ' was'} made before you changed an earlier answer.</p>` : ''}
    <ul class="rows">${path.map(row).join('')}</ul>
    ${(() => { if (bad.length || cf.length) return ''; try { const pl = R.planFor(a); return pl.independent ? `<p class="meta"><strong>${esc(J.accountingOf(pl).statement)}</strong></p>` : ''; } catch (e) { return ''; } })()}
    ${parked.length ? `<details class="more"><summary>Kept, not used now (${parked.length})</summary><ul class="rows plain">${parked.map(q => `<li><span class="k">${esc(q.short)}</span><span class="v">${esc(F.labelOf(q, a))}</span></li>`).join('')}</ul><p class="dim">These answers do not apply to your current choices. They are saved in case you switch back.</p></details>` : ''}
    ${S.journey ? (stale() ? staleHTML() : '<p class="note">A journey already exists for this brief.</p>') : ''}
    ${cf.map(c => `<div class="flag" role="alert"><p><span class="tag bad">Does not fit</span> ${esc(c.text)} Nothing has been changed. Choose a fix:</p><div class="pills">${c.choices.map(ch => `<button type="button" class="pill small" data-a="edit" data-id="${ch.edit}">${esc(ch.label)}</button>`).join('')}</div></div>`).join('')}
    ${busy || held ? `<p class="flag" role="status"><span class="tag">Claude</span> ${E.status === 'waiting_approval' ? 'An outline is waiting for your approval.' : E.status === 'paused' ? 'Work with Claude is paused. Finished parts are saved.' : 'Claude is working on this course.'} <button type="button" class="pill small" data-a="toGenerate">${E.status === 'waiting_approval' ? 'See the outline' : 'See progress'}</button></p>` : ''}
    ${!ENG.ready && !busy ? `<p class="note" id="engnote"><span class="tag ${ENG.checking ? '' : 'bad'}">${ENG.checking ? 'Checking' : 'Claude is not available'}</span> ${esc(ENG.blocker)} ${ENG.checking ? '' : '<button type="button" class="pill small" data-a="engineCheck">Check again</button>'}</p>` : ''}
    <p class="err" id="err" role="alert"></p>
    <div class="foot"><button type="button" class="quiet" data-a="back">← Back</button><span class="grow"></span>
      ${S.journey ? `<button type="button" class="pill" data-a="openJourney">Open current journey</button>` : ''}
      ${busy ? '' : `<button type="button" class="go" data-a="weaveReal" ${off || (ENG.ready ? '' : 'aria-disabled="true"')}>${held ? 'Start again with Claude' : S.journey ? 'Weave again with Claude' : 'Weave with Claude'}</button>`}</div>
    ${busy ? '' : `<div class="foot left"><button type="button" class="pill small" data-a="weave" ${off}>${S.journey ? 'Make a simulated example instead' : 'Make a simulated example'}</button><span class="dim">Instant filler for trying the screens. Not real content.</span></div>`}
    <div id="confirm"></div>
  </div>`;
}

/* ---------- working with Claude ---------- */
const chip = st => `<span class="tag ${{ done: 'ok', running: 'warn', failed: 'bad' }[st] || ''}">${{ done: 'Saved', running: 'Working', failed: 'Needs attention', todo: 'Waiting' }[st] || st}</span>`;
function genBody() {
  if (!E) return `<p class="note">Nothing has been started for this course.</p>`;
  const st = E.stages, r = st.research.output, units = st.materials.sessions, written = units.filter(u => u.status === 'done').length, now = E.now;
  const live = k => now && now.stage === k ? 'running' : null;
  const steps = now && now.steps ? now.steps.slice(-4).map(s => `<li>${s.did === 'opened' ? 'Opened' : 'Searched'}: ${esc(s.did === 'opened' ? host(s.what) : s.what)}</li>`).join('') : '';
  const rows = E.pipeline === 2 ? V.genRows(E, H) : [
    ['Sources', live('research') || st.research.status, r ? `${r.sources.length} source${r.sources.length === 1 ? '' : 's'} recorded, ${r.pagesOpened.length} page${r.pagesOpened.length === 1 ? '' : 's'} opened` : live('research') ? `<ul class="bul small">${steps || '<li>Starting the search</li>'}</ul>` : ''],
    ['Outline', live('outline') || st.outline.status, st.outline.approved ? `Approved by you ${clock(st.outline.approvedAt)}` : st.outline.status === 'done' ? 'Waiting for your approval. No lesson is written before you approve.' : ''],
    [`Sessions`, live('materials') || (written === units.length ? 'done' : st.materials.status === 'done' ? 'done' : units.some(u => u.status === 'failed') ? 'failed' : 'todo'), st.outline.approved ? `${written} of ${units.length} written and saved` + (now && now.stage === 'materials' ? `. ${esc(now.label)}.` : '') : ''],
    ['Independent review', live('review') || st.review.status, st.review.status === 'done' ? `${(st.review.output.findings || []).length} findings` : '']
  ];
  const p = E.pause, saved = [E.pipeline === 2 && st.map.status === 'done' ? 'topic map' : '', r ? 'sources' : '', st.outline.status === 'done' ? 'outline' : '', written ? `${written} of ${units.length} sessions` : ''].filter(Boolean);
  return `<ol class="gen">${rows.map(([k, s, d]) => `<li><span class="k">${k}</span>${chip(s)}<span class="d">${d}</span></li>`).join('')}</ol>
    ${E.status === 'paused' && p ? `<div class="flag" role="alert"><p><span class="tag warn">Paused</span> ${esc(p.reason)}</p>${p.detail ? more('What the Claude tool said', `<p class="dim">${esc(p.detail)}</p>`) : ''}<p class="dim">Nothing was made up to fill the gap. ${saved.length ? 'Saved so far: ' + saved.join(', ') + '.' : 'Nothing had been finished yet.'}</p></div>` : ''}
    ${E.status === 'running' ? `<p class="dim">You can close this page. Each finished part is saved on this computer and is not redone.</p>` : ''}`;
}
function viewGenerate() {
  const st = E ? E.status : 'idle', head = { running: E && E.now ? E.now.label : 'Working', paused: 'Paused', done: 'Written. Ready for you to read.', waiting_approval: 'The outline is ready for you', idle: 'Not started' }[st] || 'Working';
  const any = S.journey && engineOurs() && S.journey.sessions.some(s => s.status === 'written');
  return `<div class="swap">
    <div class="bar"><button type="button" class="quiet" data-a="toSummary">← Brief</button><span class="grow"></span><span class="px savestate">Saved</span><span class="tag ok">Claude</span></div>
    <p class="px eyebrow">Weaving with Claude</p>
    <h1 id="qt" tabindex="-1">${esc(head)}</h1>
    <div id="genbody" aria-live="polite">${genBody()}</div>
    <p class="err" id="err" role="alert"></p>
    <div class="foot left" id="genfoot">${genFoot(any)}</div>
    ${E && E.calls && E.calls.length ? more(`Record of requests (${E.calls.length})`, `<ul class="conn">${E.calls.map(c => `<li><span class="tag ${c.ok ? 'ok' : 'bad'}">${c.ok ? 'Answered' : 'Failed'}</span> ${esc(c.unit)}${c.attempt > 1 ? ', second try' : ''} · ${esc(c.model || '')} ${c.seconds ? '· ' + Math.round(c.seconds) + ' s' : ''}${c.error ? '<br><span class="dim">' + esc(c.error.reason) + '</span>' : ''}${c.problems && c.problems.length ? '<br><span class="dim">Failed Loom’s checks: ' + esc(c.problems[0]) + '</span>' : ''}</li>`).join('')}</ul>`) : ''}
  </div>`;
}
function genFoot(any) {
  const st = E ? E.status : 'idle';
  return [st === 'running' ? `<button type="button" class="pill" data-a="engineStop">Stop</button>` : '', st === 'paused' ? `<button type="button" class="go" data-a="engineResume">Resume unfinished work</button>` : '',
    st === 'waiting_approval' ? `<button type="button" class="go" data-a="toOutline">Read the outline</button>` : '', any || (st === 'done' && S.journey) ? `<button type="button" class="${st === 'done' ? 'go' : 'pill'}" data-a="openJourney">${st === 'done' ? 'Open the journey' : 'Open what is written so far'}</button>` : ''].join('');
}
function sourceHTML(s, editable) {
  return `<li class="src"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || host(s.url))}</a> <span class="dim">${esc([s.publisher, s.year, host(s.url)].filter(Boolean).join(' · '))}</span>
    <p><span class="tag">${esc(s.id)}</span> Supports: ${esc(s.claim)}</p>${s.finding ? `<p class="dim">The page says: ${esc(s.finding)}${s.quote ? ` “${esc(s.quote)}”` : ''}</p>` : ''}${s.limits ? `<p class="dim">Limits: ${esc(s.limits)}</p>` : ''}
    ${V.evidenceBlock(s, H)}
    <ul class="facts"><li>${esc(J.fetchLine(s))}</li><li>${s.link && s.link.opened ? `Address opened when checked ${esc(day(s.link.checkedAt))}` : `Address did not open automatically${s.link && s.link.note ? ': ' + esc(s.link.note) : ''}`}</li>
    <li>${s.personChecked ? `<span class="tag ok">Read by a person</span> ${esc(day(s.personChecked.at))}. Each claim is checked separately` : '<span class="tag warn">Not read by a person</span>'}</li></ul>
    ${editable ? `<button type="button" class="pill small" data-a="sourceCheck" data-v="${esc(s.id)}" aria-pressed="${!!s.personChecked}">${s.personChecked ? 'Undo: I have not read it' : 'I have read this source'}</button>` : ''}</li>`;
}
function viewOutline() {
  const o = S.outlineDraft, r = E && E.stages.research.output, plan = E.plan, integ = o.integration || {}, open = S.outlineOpen;
  const sess = o.sessions.map((s, i) => open === i
    ? `<li class="card edit"><p class="px">${esc(plan.unit)} ${i + 1} · ${F.fmtMin(plan.minutes[i])}</p><label for="o-title">Title</label><input id="o-title" type="text" value="${esc(s.title)}"><label for="o-outcome">What learners can do by the end</label><textarea id="o-outcome" rows="2">${esc(s.outcome)}</textarea><label for="o-task">The task</label><textarea id="o-task" rows="3">${esc(s.key_task)}</textarea><p class="err" id="oerr" role="alert"></p><div class="foot left"><button type="button" class="go" data-a="outlineSave" data-v="${i}">Keep these changes</button><button type="button" class="pill" data-a="outlineEdit" data-v="">Cancel</button></div></li>`
    : `<li class="card"><p class="px">${esc(plan.unit)} ${i + 1} · ${F.fmtMin(plan.minutes[i])}${E.pipeline === 2 && (s.independent_work || {}).minutes ? ` + ${s.independent_work.minutes} min alone` : ''} <span class="th">${dots((s.topics || []).map(t => E.brief.topics.findIndex(x => x.toLowerCase() === String(t).toLowerCase())).filter(n => n >= 0))}</span></p><h3>${esc(s.title)}</h3><p>${esc(s.outcome)}</p><p class="dim">Task: ${esc(s.key_task)}</p>
      ${more('What each topic contributes, and what it builds on', `${(s.contributions || []).length ? `<ul class="conn">${s.contributions.map(c => `<li><strong>${esc(c.topic)}</strong>: ${esc(c.gives)}</li>`).join('')}</ul>` : ''}<p class="dim">Serves the outcome: ${esc(s.serves)}</p>${(s.teaches || []).length ? `<p class="dim">Teaches: ${s.teaches.map(id => esc(((E.stages.map.output.nodes.find(n => n.id === id)) || {}).name || id)).join(', ')}.</p>` : ''}<p class="dim">Evidence at the end: ${esc(s.evidence_of_learning)}</p><p class="dim">${(s.builds_on || []).length ? 'Builds on ' + s.builds_on.map(n => plan.unit.toLowerCase() + ' ' + n).join(', ') : 'Builds on nothing earlier'}.</p>`)}
      <button type="button" class="quiet small" data-a="outlineEdit" data-v="${i}">Edit this ${esc(plan.unit.toLowerCase())}</button></li>`).join('');
  const warn = [o.feasibility && o.feasibility.fits === false ? `<p class="flag"><span class="tag warn">May not fit</span> ${esc(o.feasibility.concern)}</p>` : '',
    ['not_justified', 'partly'].includes(integ.status) ? `<p class="flag"><span class="tag warn">${integ.status === 'partly' ? 'Only partly joined' : 'Combination not justified'}</span> ${esc(integ.reason)}</p>` : ''].join('');
  const v2 = E.pipeline === 2, openItems = v2 ? V.outlineOpenItems(o, E) : [];
  return `<div class="swap">
    <div class="bar"><button type="button" class="quiet" data-a="toGenerate">← Progress</button><span class="grow"></span><span class="px savestate">Saved</span><span class="tag ok">Written by Claude</span></div>
    <p class="px eyebrow">Proposed outline · needs your approval</p>
    <h1 id="qt" tabindex="-1">${esc(o.course_outcome || E.brief.outcome)}</h1>
    <p class="dim">You asked for: ${esc(E.brief.outcome)}</p>
    <p><strong>How learners will show it:</strong> ${esc(o.final_evidence)}</p>
    ${warn}${v2 ? V.outlineExtras(o, E, S, H) : ''}${S.outlineEdited ? '<p class="note"><span class="tag">Edited by you</span> Your changes will be used when the sessions are written.</p>' : ''}
    <ol class="cards">${sess}</ol>
    ${integ.status && !['single_topic'].includes(integ.status) ? more('How the topics are joined', `<p><span class="tag">${esc({ justified: 'Judged to fit', partly: 'Partly', not_justified: 'Not justified', kept_separate: 'Kept separate' }[integ.status] || integ.status)}</span> ${esc(integ.reason)}</p>${integ.joining_task ? `<p class="dim">Joining task: ${esc(integ.joining_task)}</p>` : ''}<p class="dim">This is Claude’s judgement. Nobody has tried it with learners.</p>`) : ''}
    ${r ? more(`Sources found (${r.sources.length})`, `<p class="dim">Found by AI research on ${esc(day(r.researchedAt))}. None has been checked by a person yet.</p><ul class="srcs">${r.sources.map(s => sourceHTML(s, false)).join('')}</ul>${r.open_questions.length ? `<h3>Not settled</h3>${ul(r.open_questions)}` : ''}${r.not_opened.length ? `<h3>Seen in search results but not read</h3>${ul(r.not_opened.map(n => `${n.title} (${host(n.url)})`))}` : ''}`) : ''}
    ${o.feasibility && o.feasibility.concern ? more('Will it fit the time?', `<p><span class="tag ${o.feasibility.fits ? 'ok' : 'warn'}">${o.feasibility.fits ? 'Claude thinks it fits' : 'Claude thinks it may not fit'}</span> ${esc(o.feasibility.concern)}</p><p class="dim">Claude’s judgement. Nobody has timed it with learners.</p>`) : ''}
    ${(o.assumptions || []).length ? more('What Claude assumed', ul(o.assumptions)) : ''}
    <div id="askbox">${S.outlineAsk ? `<label for="ofb">What should be different?</label><textarea id="ofb" rows="3" placeholder="For example: start with the customer research, not the page design"></textarea><div class="foot left"><button type="button" class="go" data-a="outlineRevise">Ask Claude for a new outline</button><button type="button" class="pill" data-a="outlineAsk">Cancel</button></div>` : ''}</div>
    <p class="err" id="err" role="alert"></p>
    ${openItems.length ? `<div class="flag" role="group" aria-label="Before you approve"><p><span class="tag warn">Open</span> These are not settled. Approval is your decision.</p>${ul(openItems)}<label class="ack"><input type="checkbox" id="ackoutline" ${S.ackOutline ? 'checked' : ''}> I have read these. Ticking this does not fix them. They stay listed on the course as open.</label></div>` : ''}
    ${S.outlineAsk || open != null ? '' : `<div class="foot"><button type="button" class="pill" data-a="outlineAsk">Ask for a different outline</button><button type="button" class="go" data-a="outlineApprove" ${openItems.length && !S.ackOutline ? 'aria-disabled="true"' : ''}>Approve and write the sessions</button></div><p class="dim">Approving starts ${o.sessions.length} request${o.sessions.length > 1 ? 's' : ''} to Claude, one for each ${esc(plan.unit.toLowerCase())},${v2 ? ` ${(o.projects || []).length} for the projects,` : ''} then one review.${S.journey ? ' The current draft journey will be replaced. Approved versions are kept.' : ''}</p>`}
  </div>`;
}

/* ---------- journey ---------- */
const stageName = { draft: 'Draft', review: 'In review', approved: 'Approved', exported: 'Exported' };
function stageLabel() { const L = S.life, snap = L.snapshots.find(s => s.ver === L.ver); return snap && ['approved', 'exported'].includes(L.stage) && J.readinessOf(snap).draft ? (L.stage === 'exported' ? 'Draft exported' : 'Internal draft') : stageName[L.stage]; }
function topBar(back = ['toSummary', 'Brief']) { return `<div class="bar"><button type="button" class="quiet" data-a="${back[0]}">← ${back[1]}</button><span class="grow"></span><span class="px savestate">Saved</span>${simTag()}<button type="button" class="status" data-a="life"><span class="px">${stageLabel()} v${S.life.ver}</span><span aria-hidden="true">›</span></button></div>${simNote()}`; }
// A request can run to ten lines. The banner names the change in a few words. The request itself is one tap away.
const brief_ = (t, n = 60) => { t = String(t || '').replace(/\s+/g, ' ').trim(); return t.length <= n ? t : t.slice(0, t.lastIndexOf(' ', n) > 20 ? t.lastIndexOf(' ', n) : n) + '…'; };
const long_ = t => String(t || '').trim().length > 60;
function undoBar() {
  const u = S.undo[S.undo.length - 1]; if (!u) return '';
  const n = S.undo.length, name = u.editId ? 'Claude’s change' : long_(u.label) ? 'Change' : u.label;
  return `<div class="applied swap" role="status"><p><span>Applied: ${esc(name)} <span class="dim">· ${esc(brief_(u.target, 48))}</span></span><button type="button" class="pill small" data-a="undo">Undo</button></p>
    ${long_(u.label) || n > 1 ? `<details class="more"><summary>${n > 1 ? `What changed (${n} steps can be undone)` : 'What was asked'}</summary><ol class="hist">${S.undo.slice().reverse().map(x => `<li>${esc(x.label)} <span class="dim">· ${esc(x.target)}</span></li>`).join('')}</ol></details>` : ''}</div>`;
}
let replacePv = null; // the preview is kept out of the saved course: it holds a whole copy of the draft
function replaceForm() {
  const e = S.editing, pv = replacePv;
  return `<form class="editform" data-form="replace" novalidate><p class="px">Find and replace · the whole draft · no AI</p>
    <label for="e-find">Find these exact words</label><textarea id="e-find" rows="2">${esc(e.find || '')}</textarea>
    <label for="e-replace">Replace with</label><textarea id="e-replace" rows="2">${esc(e.replace || '')}</textarea>
    <p class="hint">Capital letters and spaces must match. Approved versions are never changed.</p>
    ${pv ? pv.none ? '<p class="note" role="status"><span class="tag warn">Not found</span> Those words are not in the draft.</p>' : `<div class="flag" role="status"><p><span class="tag">Preview</span> ${pv.total} place${pv.total > 1 ? 's' : ''} would change, in ${[...new Set(pv.hits.map(h => h.where))].join(', ')}. Nothing has changed yet.</p>${more(`See each place (${pv.hits.length})`, `<ul class="diff">${pv.hits.map(h => `<li><span class="k">${esc(h.where)} · ${esc(h.place)}${h.count > 1 ? ` · ${h.count} times` : ''}</span><span class="was">${esc(h.was)}</span><span class="now">${esc(h.now)}</span></li>`).join('')}</ul>`)}</div>` : ''}
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="pill" data-a="editCancel">Close</button><button type="button" class="pill" data-a="replacePreview">Preview</button>${pv && pv.after ? '<button type="button" class="go" data-a="replaceApply">Replace everywhere</button>' : ''}</div></form>`;
}
function courseForm() {
  const j = S.journey;
  return `<form class="editform" data-form="course" novalidate><p class="px">Editing the course statement · your own words</p>
    <label for="e-finalEvidence">How learners will show the outcome</label><textarea id="e-finalEvidence" rows="6">${esc(j.finalEvidence || '')}</textarea>
    <label for="e-courseAssumptions">What the plan assumes, one on each line</label><textarea id="e-courseAssumptions" rows="6">${esc((j.assumptions || []).join('\n'))}</textarea>
    <p class="hint">No session is rewritten. If you change how learners show the outcome, every session is marked “Look”, and the review is marked as made on an earlier draft.</p>
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="pill" data-a="editCancel">Cancel</button><button type="button" class="go" data-a="editSave">Save my changes</button></div></form>`;
}
function changeUI(lockJourney) {
  if (S.pendingEdit) {
    const paused = E && E.status === 'paused', e = E && E.edits && E.edits[S.pendingEdit.id], done = e ? e.parts.filter(p => p.status === 'done').length : 0;
    return `<section class="change swap" aria-label="Change in progress"><div class="bar"><span class="px">${paused ? 'Paused' : 'Claude is working on your change'}</span><span class="grow"></span><span class="tag ok">Claude</span></div>
      <h2>${esc(brief_(S.pendingEdit.label, 70))}</h2>${long_(S.pendingEdit.label) ? more('What you asked', `<p>${esc(S.pendingEdit.label)}</p>`) : ''}<p class="dim" role="status">${paused ? esc(E.pause.reason) + ' Nothing has changed.' : `Nothing has changed yet. You will see a preview first.${e && e.parts.length > 1 ? ` ${done} of ${e.parts.length} sessions done.` : ''}`}</p>
      <div class="foot left">${paused ? '<button type="button" class="go" data-a="engineResume">Resume</button>' : '<button type="button" class="pill" data-a="engineStop">Stop</button>'}<button type="button" class="pill" data-a="askDrop">Give up this change</button></div></section>`;
  }
  if (S.pending) {
    const p = S.pending;
    return `<section class="change swap" aria-label="Change preview"><div class="bar"><span class="px">Preview · nothing has changed yet</span><span class="grow"></span>${p.kind === 'ai' ? '<span class="tag ok">Written by Claude</span>' : simTag()}</div>
      ${S.pendingNote ? `<p class="flag" role="alert"><span class="tag warn">Rebuilt</span> ${esc(S.pendingNote)}</p>` : ''}
      <h2>${esc(brief_(p.label, 70))}</h2>${long_(p.label) ? more('What you asked', `<p>${esc(p.label)}</p>`) : ''}<p class="dim">Applies to: ${esc(p.target)}</p>
      <ul class="diff">${(p.lines || []).map(l => `<li><span class="k">${esc(l.label)}</span><span class="was">${esc(l.was)}</span><span class="now">${esc(l.now)}</span></li>`).join('')}</ul>
      <ul class="fx">${(p.effects || []).map(e => long_(e) && e.length > 220 ? `<li>${esc(brief_(e, 200))}${more('Read Claude’s whole note', `<p>${esc(e)}</p>`)}</li>` : `<li>${esc(e)}</li>`).join('')}</ul>
      <div class="foot"><button type="button" class="pill" data-a="reject">${p.noop ? 'Close preview' : 'Reject'}</button>${p.noop ? '' : '<button type="button" class="go" data-a="accept">Accept change</button>'}</div></section>`;
  }
  const sc = lockJourney ? 'journey' : S.scope, names = { activity: 'This step', session: 'This session', journey: 'Whole journey' }, isReal = real();
  if (!S.askOpen) return `<button type="button" class="pill" data-a="askOpen" aria-expanded="false">${isReal ? 'Ask Claude for a change' : 'Request a change'}</button>`;
  const blocked = isReal && (engineActive() ? 'Claude is busy with this course. Wait until it finishes.' : !ENG.ready ? ENG.blocker : J.unwritten(S.journey).length && sc === 'journey' ? 'Some sessions are not written yet. Change single sessions for now.' : '');
  return `<section class="change swap" aria-label="Request a change">
    <div class="bar"><h2>${isReal ? 'Ask Claude for a change' : 'Request a change'}</h2><span class="grow"></span><button type="button" class="quiet" data-a="askClose">Close</button></div>
    ${lockJourney ? `<p class="hint">Applies to the whole journey${isReal ? `. One request to Claude for each of ${S.journey.sessions.length} sessions.` : ''}</p>` : `<p class="hint">Applies to</p><div class="pills" role="radiogroup" aria-label="Change applies to">${Object.keys(names).filter(k => k !== 'activity' || S.at === 'activity').map(k => `<button type="button" class="pill small" role="radio" aria-checked="${sc === k}" data-a="scope" data-v="${k}"><span class="mk" aria-hidden="true"></span><span>${names[k]}</span></button>`).join('')}</div>`}
    ${blocked ? `<p class="note"><span class="tag warn">Not now</span> ${esc(blocked)}</p>` : `<div class="pills">${Object.keys(J.KINDS).map(k => `<button type="button" class="pill small" data-a="ask" data-v="${k}">${J.KINDS[k]}</button>`).join('')}</div>
    <div class="addrow"><label class="sr" for="ask">Describe a change</label><input id="ask" type="text" autocomplete="off" placeholder="Or describe it in your own words"><button type="button" class="pill" data-a="askText">${isReal ? 'Ask' : 'Preview'}</button></div>`}
    <p class="err" id="err" role="alert"></p></section>`;
}
const nodeState = s => s.status === 'pending' ? ['…', 'Not written yet'] : s.status === 'failed' ? ['!', 'Needs attention'] : null;
function viewJourney() {
  const j = S.journey, p = J.planOf(j), rd = R.readiness(j), ours = engineOurs() && E.status !== 'done';
  return `<div class="swap">${topBar()}
    ${stale() ? `<div class="flag"><p><span class="tag warn">Changed</span> Your brief changed after this journey was made. The journey has not been touched. <button type="button" class="pill small" data-a="toSummary">Review the brief</button></p></div>` : ''}
    ${ours ? `<p class="flag" role="status"><span class="tag">Claude</span> ${S.pendingEdit ? (E.status === 'paused' ? 'Your change is paused. Nothing has changed.' : 'Claude is working on your change. Nothing has changed yet.') : `${E.status === 'paused' ? 'Writing is paused.' : E.now && E.now.stage === 'review' ? 'Claude is reviewing what is written.' : 'Claude is still writing.'} ${j.sessions.filter(s => s.status === 'written').length} of ${j.sessions.length} sessions are written.`} <button type="button" class="pill small" data-a="toGenerate">See progress</button></p>` : ''}
    <p class="px eyebrow">${esc(j.format)} · ${esc(j.audience)} · ${esc(j.delivery)}</p>
    <h1 id="qt" tabindex="-1">${esc(j.outcome)}</h1>
    ${S.editing && S.editing.kind === 'course' ? courseForm() : r_() || j.finalEvidence ? `<p><strong>How learners will show it:</strong> ${esc(brief_(j.finalEvidence, 150)) || '<em>Not written yet</em>'}</p>${r_() ? more(long_(j.finalEvidence) ? 'Read it in full' : 'Assumptions, and editing', `<p>${esc(j.finalEvidence)}</p>${(j.assumptions || []).length ? `<h3>What the plan assumes</h3>${ul(j.assumptions)}` : ''}<div class="foot left"><button type="button" class="pill small" data-a="editCourse">Edit these statements myself</button></div>`) : ''}` : ''}
    <p class="meta"><strong>Planned: ${esc(p.label)}</strong> · Brief asked for: ${esc(p.requested.span)}${j.accounting ? ` · ${esc(j.accounting.statement)}` : ''}</p>
    ${p.differs ? `<p class="flag" role="status"><span class="tag warn">Differs from brief</span> ${esc(p.notes.join('; '))}. Your brief has not been changed.</p>` : ''}
    <ul class="legend">${j.topics.map((t, i) => `<li><i style="background:${THREADS[i % 4]}"></i>${esc(t)}</li>`).join('')}${j.world ? `<li><span class="tag">Inspired by ${esc(j.world)}</span></li>` : ''}</ul>
    <ol class="path" style="--n:${j.sessions.length}">${j.sessions.map((s, i) => { const ns = nodeState(s); return `<li><button type="button" class="node${ns ? ' wait' : ''}" data-a="open" data-id="${s.id}"><span class="lamp"><span class="px">${ns ? ns[0] : i + 1}</span></span><span class="t">${esc(s.title)}</span><span class="m">${ns ? ns[1] : F.fmtMin(s.minutes)} <span class="th">${dots(s.threads)}</span>${s.review ? ' <span class="tag warn">Look</span>' : ''}</span></button></li>`; }).join('')}</ol>
    ${V.projectsBlock(j, H)}
    ${j.connections.length ? `<details class="more"><summary>Topic connections (${j.connections.length})</summary><ul class="conn">${j.connections.map(c => `<li><span class="tag ${['Not justified', 'Partly joined', 'Not established'].includes(c.type) ? 'warn' : ''}">${esc(c.type)}</span> <strong>${esc(J.listNames(c.names))}</strong><br><span class="dim">${esc(c.why)}</span></li>`).join('')}</ul></details>` : ''}
    ${undoBar()}
    ${S.editing && S.editing.kind === 'replace' ? replaceForm() : ''}
    <div class="foot left"><button type="button" class="pill" data-a="toChecks">Checks before approval${rd.must.length ? ` <span class="tag bad">${rd.must.length} to fix</span>` : rd.look.length ? ` <span class="tag warn">${rd.look.length} to look at</span>` : ''}</button>${r_() && !S.editing ? '<button type="button" class="pill" data-a="replaceOpen">Find and replace</button>' : ''}${S.pending || S.pendingEdit || S.askOpen ? '' : changeUI(true)}</div>
    ${S.pending || S.pendingEdit || S.askOpen ? changeUI(true) : ''}</div>`;
}
const r_ = () => real();

/* ---------- one session, then one step at a time ---------- */
function claimsHTML(s) {
  const j = S.journey;
  return (s.claims || []).length ? `<ul class="conn">${s.claims.map((c, k) => `<li><span class="tag ${c.type === 'fact' && (c.sources || []).length ? 'ok' : c.type === 'fact' ? 'bad' : 'warn'}">${esc(R.CLAIM[c.type] || c.type)}</span> ${esc(c.text)}<br><span class="dim">${esc(J.standing(c, j))}${(c.sources || []).length ? ' Sources: ' + c.sources.map(id => { const x = (j.sources || []).find(y => y.id === id); return x ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(id)} ${esc(host(x.url))}</a>` : esc(id); }).join(', ') : ''}</span>${c.type === 'fact' && !S.editing && !S.pending && !S.pendingEdit ? `<br><span class="pills"><button type="button" class="quiet small" data-a="claimCheck" data-v="${s.id}|${k}" aria-pressed="${!!J.checkedOn(c)}">${J.checkedOn(c) ? 'Undo: I have not checked this claim' : 'I have checked this claim against its source'}</button><button type="button" class="quiet small" data-a="claimType" data-v="${s.id}|${k}|uncertain">Mark as uncertain</button><button type="button" class="quiet small" data-a="claimType" data-v="${s.id}|${k}|hypothesis">Mark as our judgement</button></span>` : ''}</li>`).join('')}</ul>` : '<p class="dim">No claims are recorded for this session.</p>';
}
function notesHTML(s, x) {
  const j = S.journey, all = [...(j.internal || []).map(n => ['Whole journey', n]), ...(s.internal || []).map(n => ['This session', n]), ...(x ? (x.internal || []).map(n => ['This step', n]) : s.activities.flatMap(y => (y.internal || []).map(n => [y.title || y.kind, n])))];
  const rv = j.review && j.review.output ? (j.review.output.findings || []).filter(f => f.session === j.sessions.indexOf(s) + 1) : [];
  return `<p class="note"><span class="tag">Stays in Loom</span> Never included in an exported package.</p>${all.length ? `<ul class="acts plain">${all.map(o => `<li><span class="k">${esc(o[0])}</span><span>${esc(o[1])}</span></li>`).join('')}</ul>` : '<p class="dim">No notes yet.</p>'}
    ${rv.length ? `<h3>From the independent review</h3><ul class="conn">${rv.map(f => `<li><span class="tag ${f.severity === 'must_fix' ? 'bad' : f.severity === 'should_fix' ? 'warn' : ''}">${esc(f.severity.replace('_', ' '))}</span> ${esc(f.finding)}<br><span class="dim">${esc(f.suggestion)}</span></li>`).join('')}</ul>` : ''}`;
}
function sessionForm(s) {
  const r = real();
  return `<form class="editform" data-form="session" novalidate><p class="px">Editing this session · your own words</p>
    <label for="e-title">Title</label><input id="e-title" type="text" value="${esc(s.title)}">
    ${r ? `<label for="e-outcome">What learners can do by the end</label><textarea id="e-outcome" rows="2">${esc(s.outcome)}</textarea>
    <label for="e-success">Success criteria, one on each line</label><textarea id="e-success" rows="4">${esc((s.successCriteria || []).join('\n'))}</textarea>
    <label for="e-prerequisites">Prerequisites, one on each line. Write the support after a dash</label><textarea id="e-prerequisites" rows="3">${esc((s.prerequisites || []).map(q => q.name + (q.support ? ' — ' + q.support : '')).join('\n'))}</textarea>
    <label for="e-checkTask">Later check: the task</label><textarea id="e-checkTask" rows="2">${esc((s.applicationCheck || {}).task || '')}</textarea>
    <label for="e-checkWhen">Later check: when</label><input id="e-checkWhen" type="text" value="${esc((s.applicationCheck || {}).when || '')}">
    <label for="e-checkLooks">Later check: what to look for, one on each line</label><textarea id="e-checkLooks" rows="3">${esc(((s.applicationCheck || {}).looksFor || []).join('\n'))}</textarea>
    <label for="e-assumptions">What this session assumes, one on each line</label><textarea id="e-assumptions" rows="4">${esc((s.assumptions || []).join('\n'))}</textarea>
    <label for="e-prepSteps">Teacher preparation, one step on each line</label><textarea id="e-prepSteps" rows="4">${esc((s.teacher.prepSteps || []).join('\n'))}</textarea>
    <label for="e-prep">Preparation minutes</label><input id="e-prep" type="text" inputmode="numeric" value="${esc(String(s.teacher.prep || 0))}">`
    : `<label for="e-aim">What learners do</label><textarea id="e-aim" rows="2">${esc(s.aim)}</textarea><label for="e-proof">How they prove it</label><textarea id="e-proof" rows="2">${esc(s.proof)}</textarea>`}
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="pill" data-a="editCancel">Cancel</button><button type="button" class="go" data-a="editSave">Save my changes</button></div></form>`;
}
function viewSession() {
  const j = S.journey, i = j.sessions.findIndex(s => s.id === S.sel), s = j.sessions[i]; if (!s) { S.at = 'journey'; return viewJourney(); }
  const r = real(), waiting = s.status === 'pending' || s.status === 'failed', req = s.teacher.requirements || [], editing = S.editing && S.editing.kind === 'session' && S.editing.sessionId === s.id;
  const head = `${topBar(['toJourney', 'Journey'])}
    <p class="px eyebrow">${esc(s.unit)} ${i + 1} of ${j.sessions.length} · ${F.fmtMin(s.minutes)} <span class="th">${dots(s.threads)}</span>${s.origin === 'edited' ? ' · edited by you' : ''}</p>
    <h1 id="qt" tabindex="-1">${esc(s.title)}</h1>`;
  if (editing) return `<div class="swap">${head}${sessionForm(s)}</div>`;
  if (waiting) return `<div class="swap">${head}<p class="lead">${esc(s.outcome || s.aim)}</p>${s.keyTask ? `<p class="dim">Planned task: ${esc(s.keyTask)}</p>` : ''}
    <div class="flag" role="status"><p><span class="tag ${s.status === 'failed' ? 'bad' : 'warn'}">${s.status === 'failed' ? 'Could not be written' : 'Not written yet'}</span> ${s.status === 'failed' ? esc(s.failure || 'Claude’s answer did not pass Loom’s checks.') + ' Nothing was filled in for it.' : 'Claude has not written this session yet. Loom will not fill it with anything else.'}</p>
    <div class="pills">${engineOurs() && !engineActive() ? `<button type="button" class="pill small" data-a="retrySession" data-v="${i}">${s.status === 'failed' ? 'Ask Claude to try again' : 'Write it now'}</button>` : ''}<button type="button" class="pill small" data-a="toGenerate">See progress</button></div></div>
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="quiet" data-a="prevS" ${i === 0 ? 'disabled' : ''}>← Previous</button><button type="button" class="quiet" data-a="nextS" ${i === j.sessions.length - 1 ? 'disabled' : ''}>Next →</button></div></div>`;
  const weak = (s.contributions || []).filter(c => /^weak\b/i.test(c.gives));
  return `<div class="swap">${head}
    <p class="lead">${esc(s.outcome || s.aim)}</p>
    ${s.review ? `<p class="flag" role="status"><span class="tag warn">Look</span> ${esc(s.review.reason)} Nothing here was rewritten. <button type="button" class="pill small" data-a="lookDone">I have checked it still fits</button></p>` : ''}
    ${weak.length ? `<p class="flag"><span class="tag warn">Weak link</span> ${esc(weak.map(c => c.topic).join(', '))} may not belong in this session. See what each topic contributes.</p>` : ''}
    <ol class="steps" aria-label="Steps in this session">${s.activities.map((x, k) => `<li><button type="button" class="step" data-a="act" data-v="${x.id}"><span class="n px">${k + 1}</span><span class="t">${esc(x.title || x.kind)}<span class="dim"> ${x.title ? esc(x.kind) : ''}${x.origin === 'edited' ? ' · edited' : ''}</span></span><span class="m">${x.minutes} min</span></button></li>`).join('')}</ol>
    ${r ? more('Before this session', `${(s.prerequisites || []).length ? `<ul class="conn">${s.prerequisites.map(q => `<li><strong>${esc(q.name)}</strong><br><span class="dim">If a learner lacks it: ${esc(q.support)}</span></li>`).join('')}</ul>` : ''}${s.prerequisitesNote ? `<p class="dim">${esc(s.prerequisitesNote)}</p>` : ''}${(s.buildsOn || []).length ? `<p class="dim">Builds on ${s.buildsOn.map(id => { const k = j.sessions.findIndex(y => y.id === id); return k < 0 ? '' : `${s.unit.toLowerCase()} ${k + 1}`; }).filter(Boolean).join(', ')}.</p>` : ''}`) : ''}
    ${more('How you will know it worked', r ? `${ul(s.successCriteria)}${s.applicationCheck ? `<h3>Later, without help</h3><p>${esc(s.applicationCheck.task)}</p><p class="dim">When: ${esc(s.applicationCheck.when)}</p>${ul(s.applicationCheck.looksFor)}` : ''}` : `<p>${esc(s.proof)}</p>`)}
    ${r && s.threads.length > 1 ? more('What each topic contributes', `<ul class="conn">${(s.contributions || []).map(c => `<li><strong>${esc(c.topic)}</strong>: ${esc(c.gives)}</li>`).join('')}</ul><p class="dim">Claude’s judgement. Naming a topic is not the same as needing it.</p>`) : ''}
    ${more('For the teacher', `<dl class="idea"><dt>Materials</dt><dd>${s.teacher.materials.map(esc).join(', ') || 'None listed'}</dd><dt>Setup</dt><dd>${esc(s.teacher.setup)}</dd><dt>Preparation</dt><dd>About ${s.teacher.prep} minutes before the session${(s.teacher.prepSteps || []).length ? ': ' + s.teacher.prepSteps.map(esc).join(' ') : ''}</dd></dl>${req.length ? `<div class="reqs"><p><span class="tag warn">Requirements to implement</span> From your brief. ${r ? 'Claude was asked to design within them. Nobody has confirmed they are met.' : 'The simulated text has not been made to meet them.'}</p><ul>${req.map(t => `<li>${esc(t.replace(J.REQ, ''))}</li>`).join('')}</ul></div>` : ''}${(s.assumptions || []).length ? `<h3>Assumed</h3>${ul(s.assumptions)}` : ''}`)}
    ${r ? V.sessionExtras(s, j, H) : ''}
    ${r ? more(`Evidence (${(s.claims || []).length} claims)`, claimsHTML(s)) : ''}
    ${more('Why this session is here', `<p>${esc(s.why)}</p>${r ? '' : '<p class="dim">Evidence: none. No sources were checked for this simulated draft.</p>'}`)}
    ${more('Internal notes', notesHTML(s))}
    ${undoBar()}
    <p class="err" id="err" role="alert"></p>
    <div class="foot left"><button type="button" class="pill" data-a="editSession">Edit the text myself</button>${S.pending || S.pendingEdit || S.askOpen ? '' : changeUI(false)}</div>
    ${S.pending || S.pendingEdit || S.askOpen ? changeUI(false) : ''}
    <div class="foot"><button type="button" class="quiet" data-a="prevS" ${i === 0 ? 'disabled' : ''}>← Previous</button><button type="button" class="quiet" data-a="nextS" ${i === j.sessions.length - 1 ? 'disabled' : ''}>Next →</button></div></div>`;
}
function viewProject() {
  const j = S.journey, p = (j.projects || []).find(x => x.id === S.selP); if (!p) { S.at = 'journey'; return viewJourney(); }
  const head = `${topBar(['toJourney', 'Journey'])}<p class="px eyebrow">${p.outline.kind === 'major' ? 'Major project' : 'Minor project'} · ${esc(p.id)}</p><h1 id="qt" tabindex="-1">${esc((p.content || {}).title || p.outline.title)}</h1>`;
  if (p.status !== 'written') return `<div class="swap">${head}<p class="lead">${esc(p.outline.purpose)}</p><p class="dim">Planned: hand in ${esc(p.outline.deliverable)}. ${(p.outline.minutes || {}).live || 0} min live, ${(p.outline.minutes || {}).independent || 0} min independent.</p>
    <div class="flag" role="status"><p><span class="tag ${p.status === 'failed' ? 'bad' : 'warn'}">${p.status === 'failed' ? 'Could not be written' : 'Not written yet'}</span> ${p.status === 'failed' ? esc(p.failure || 'Claude’s answer did not pass Loom’s checks.') + ' Nothing was filled in for it.' : 'Claude has not written this project yet. Loom will not fill it with anything else.'}</p>
    <div class="pills">${engineOurs() && !engineActive() ? `<button type="button" class="pill small" data-a="retryProject" data-v="${(j.projects || []).indexOf(p)}">${p.status === 'failed' ? 'Ask Claude to try again' : 'Write it now'}</button>` : ''}<button type="button" class="pill small" data-a="toGenerate">See progress</button></div></div><p class="err" id="err" role="alert"></p></div>`;
  const c = p.content, editing = S.editing && S.editing.kind === 'project' && S.editing.projectId === p.id;
  if (editing) return `<div class="swap">${head}<form class="editform" data-form="project" novalidate><p class="px">Editing this project · your own words</p>
    <label for="e-title">Title</label><input id="e-title" type="text" value="${esc(c.title)}">
    <label for="e-purpose">Purpose</label><textarea id="e-purpose" rows="2">${esc(c.purpose)}</textarea>
    <label for="e-learner_brief">The brief, as learners read it</label><textarea id="e-learner_brief" rows="10">${esc(c.learner_brief)}</textarea>
    <label for="e-deliverables">What learners hand in, one on each line</label><textarea id="e-deliverables" rows="3">${esc((c.deliverables || []).join('\n'))}</textarea>
    <label for="e-feedback_route">How learners get feedback</label><textarea id="e-feedback_route" rows="3">${esc(c.feedback_route)}</textarea>
    <label for="e-revision_route">How learners revise</label><textarea id="e-revision_route" rows="3">${esc(c.revision_route)}</textarea>
    <label for="e-example_or_solution_guidance">What good work looks like, for the teacher</label><textarea id="e-example_or_solution_guidance" rows="4">${esc(c.example_or_solution_guidance)}</textarea>
    <label for="e-teacher_guidance">Teacher guidance, one point on each line</label><textarea id="e-teacher_guidance" rows="3">${esc((c.teacher_guidance || []).join('\n'))}</textarea>
    <p class="hint">Files, milestones and the rubric are not edited here. Saving makes any review of this draft read as made on an earlier draft.</p>
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="pill" data-a="editCancel">Cancel</button><button type="button" class="go" data-a="editSave">Save my changes</button></div></form></div>`;
  return `<div class="swap">${head}${V.projectBody(p, j, H)}${undoBar()}<p class="err" id="err" role="alert"></p><div class="foot left"><button type="button" class="pill" data-a="editProject">Edit the text myself</button></div></div>`;
}
function activityForm(x) {
  const r = real();
  return `<form class="editform" data-form="activity" novalidate><p class="px">Editing this step · your own words</p>
    ${r ? `<label for="e-title">Title</label><input id="e-title" type="text" value="${esc(x.title)}"><label for="e-goal">Goal</label><textarea id="e-goal" rows="2">${esc(x.goal)}</textarea>` : ''}
    <label for="e-minutes">Minutes</label><input id="e-minutes" type="text" inputmode="numeric" value="${esc(x.minutes)}">
    ${r ? `<label for="e-instructions">Instructions for the learner, one step on each line</label><textarea id="e-instructions" rows="6">${esc((x.instructions || []).join('\n'))}</textarea>
    <label for="e-materials">Materials, one on each line</label><textarea id="e-materials" rows="3">${esc((x.materials || []).join('\n'))}</textarea>
    <label for="e-handout">Handout text</label><textarea id="e-handout" rows="6">${esc(x.handout || '')}</textarea>
    <label for="e-example">Worked example</label><textarea id="e-example" rows="5">${esc(x.example || '')}</textarea>
    <label for="e-guidance">Teacher guidance, one point on each line</label><textarea id="e-guidance" rows="4">${esc((x.guidance || []).join('\n'))}</textarea>
    <label for="e-success">What success looks like, one on each line</label><textarea id="e-success" rows="3">${esc((x.success || []).join('\n'))}</textarea>`
    : `<label for="e-learner">What the learner does</label><textarea id="e-learner" rows="4">${esc(x.learner)}</textarea><label for="e-teacher">Teacher note</label><textarea id="e-teacher" rows="3">${esc(x.teacher)}</textarea>`}
    <p class="err" id="err" role="alert"></p><div class="foot"><button type="button" class="pill" data-a="editCancel">Cancel</button><button type="button" class="go" data-a="editSave">Save my changes</button></div></form>`;
}
function viewActivity() {
  const j = S.journey, si = j.sessions.findIndex(s => s.id === S.sel), s = j.sessions[si]; if (!s || !s.activities.length) { S.at = s ? 'session' : 'journey'; return s ? viewSession() : viewJourney(); }
  let k = s.activities.findIndex(x => x.id === S.act); if (k < 0) { k = 0; S.act = s.activities[0].id; }
  const x = s.activities[k], r = real(), editing = S.editing && S.editing.kind === 'activity' && S.editing.activityId === x.id && S.editing.sessionId === s.id;
  const tabs = r ? { learner: 'Learner', teacher: 'Teacher', evidence: 'Evidence', internal: 'Internal notes' } : { learner: 'Learner', teacher: 'Teacher', internal: 'Internal notes' };
  if (!tabs[S.tab]) S.tab = 'learner';
  let body = '';
  if (S.tab === 'learner') body = r ? `<ol class="instr">${(x.instructions || []).map(t => `<li>${esc(t)}</li>`).join('')}</ol>${(x.materials || []).length ? `<p class="dim">You need: ${x.materials.map(esc).join(', ')}</p>` : ''}${x.handout ? more('Handout', `<div class="handout">${esc(x.handout)}</div>`, true) : ''}${x.example ? more('Worked example', `<div class="handout">${esc(x.example)}</div>`) : ''}${(x.success || []).length ? more('What success looks like', ul(x.success)) : ''}` : `<p>${esc(x.learner)}</p>`;
  if (S.tab === 'teacher') body = r ? `${ul(x.guidance) || '<p class="dim">No guidance written for this step.</p>'}${(x.misconceptions || []).length ? `<h3>Learners often think</h3><ul class="conn">${x.misconceptions.map(m => `<li>“${esc(m.belief)}”<br><span class="dim">Respond: ${esc(m.response)}</span></li>`).join('')}</ul><p class="dim">Claude’s judgement unless the evidence tab cites a source.</p>` : ''}` : `<p>${esc(x.teacher)}</p>`;
  if (S.tab === 'evidence') body = `<p class="dim">Claims the whole session relies on.</p>${claimsHTML(s)}`;
  if (S.tab === 'internal') body = notesHTML(s, x);
  return `<div class="swap">
    <div class="bar"><button type="button" class="quiet" data-a="toSession">← Session overview</button><span class="grow"></span><span class="px savestate">Saved</span>${simTag()}</div>${simNote()}
    <p class="px eyebrow">Step ${k + 1} of ${s.activities.length} · ${esc(x.kind)} · ${x.minutes} min${x.origin === 'edited' ? ' · edited by you' : ''}</p>
    <h1 id="qt" tabindex="-1">${esc(x.title || x.kind)}</h1>
    ${editing ? activityForm(x) : `${x.goal ? `<p class="lead">${esc(x.goal)}</p>` : ''}
    <div class="tabs" role="tablist" aria-label="Details for this step">${Object.keys(tabs).map(t => `<button type="button" role="tab" id="tab-${t}" ${S.tab === t ? `aria-controls="panel-${t}" ` : ''}aria-selected="${S.tab === t}" data-a="tab" data-v="${t}">${tabs[t]}</button>`).join('')}</div>
    <div class="tabbody" role="tabpanel" id="panel-${S.tab}" aria-labelledby="tab-${S.tab}" tabindex="0">${body}</div>
    ${undoBar()}
    <p class="err" id="err" role="alert"></p>
    <div class="foot left"><button type="button" class="pill" data-a="editActivity">Edit the text myself</button>${S.pending || S.pendingEdit || S.askOpen ? '' : changeUI(false)}</div>
    ${S.pending || S.pendingEdit || S.askOpen ? changeUI(false) : ''}
    <div class="foot"><button type="button" class="quiet" data-a="prevA" ${k === 0 ? 'disabled' : ''}>← Previous step</button><button type="button" class="quiet" data-a="nextA" ${k === s.activities.length - 1 ? 'disabled' : ''}>Next step →</button></div>`}
  </div>`;
}

/* ---------- checks before approval ---------- */
function viewChecks() {
  const j = S.journey, rd = R.readiness(j), r = real(), rv = j.review && j.review.output, req = j.sessions[0].teacher.requirements || [];
  const sev = { must_fix: 'bad', should_fix: 'warn', note: '' };
  return `<div class="swap">${topBar(['toJourney', 'Journey'])}
    <p class="px eyebrow">Checks before approval</p>
    <h1 id="qt" tabindex="-1">${rd.must.length ? `${rd.must.length} thing${rd.must.length > 1 ? 's' : ''} to fix` : teachOpen(j).length ? 'The structure holds. It is not ready to teach.' : rd.look.length ? 'The structure holds. Some things need a look.' : 'Loom’s checks found nothing'}</h1>
    ${r ? `<ul class="conn three-q"><li><span class="tag ${rd.must.length ? 'bad' : 'ok'}">Structure</span> ${rd.must.length ? `${rd.must.length} to fix. Approval waits for these.` : 'Holds. Times, parts and sessions agree.'}</li><li><span class="tag ${rd.must.length ? 'bad' : 'warn'}">Internal approval</span> ${rd.must.length ? 'Not possible yet.' : 'Possible. It is the team’s decision, not a test.'}</li><li><span class="tag ${teachOpen(j).length ? 'bad' : 'warn'}">Teaching readiness</span> ${teachOpen(j).length ? `Not ready. ${teachOpen(j).length} open: ${esc(teachOpen(j).join(' '))} Reading and ticking these does not resolve them.` : 'Nothing open on paper. Not rehearsed, and not tried with learners.'}</li></ul>` : ''}
    <p class="dim">These checks look at consistency: time, topics, missing parts, sources. They cannot tell you whether the course teaches well. Try it with a teacher and learners before relying on it.</p>
    ${r ? V.checksExtras(j, H) : ''}
    <h2>Structure: must fix before approval</h2>${rd.must.length ? ul(rd.must) : '<p class="dim">None.</p>'}
    <h2>Worth a look</h2>${rd.look.length ? ul(rd.look) : '<p class="dim">None.</p>'}
    <h2>Requirements still to implement</h2>${req.length ? `${ul(req.map(t => t.replace(J.REQ, '')))}<p class="dim">Shown as pending until a person confirms each one. Loom does not mark them as met.</p>` : '<p class="dim">The brief set none.</p>'}
    ${r ? `<h2>Independent review</h2>${rv ? `<p class="dim">Made by Claude as a separate reviewer on ${esc(clock(j.review.at))}${j.review.rev !== j.rev ? '. <strong>The draft has changed since</strong>' : ''}. It judged what is written. It did not open the links or try the course.</p>
      <p><span class="tag ${{ yes: 'ok', with_changes: 'warn', no: 'bad' }[rv.teacher_could_run_it.answer]}">Could a teacher run it? ${esc(rv.teacher_could_run_it.answer.replace('_', ' '))}</span></p>
      <p class="pills">${rv.areas.map(a => `<span class="tag ${{ sound: 'ok', concerns: 'warn', serious_problems: 'bad' }[a.verdict]}">${esc(a.area.replace(/_/g, ' '))}: ${esc(a.verdict.replace(/_/g, ' '))}</span>`).join(' ')}</p>
      ${more('Why the reviewer says so', `<p>${esc(rv.teacher_could_run_it.why)}</p>`)}
      ${more('What the reviewer said about each area', `<ul class="conn">${rv.areas.map(a => `<li><span class="tag ${{ sound: 'ok', concerns: 'warn', serious_problems: 'bad' }[a.verdict]}">${esc(a.area.replace(/_/g, ' '))}</span> ${esc(a.summary)}</li>`).join('')}</ul>`)}
      ${[['must_fix', 'Must fix'], ['should_fix', 'Should fix'], ['note', 'Notes']].map(([k, name]) => { const fs = rv.findings.filter(f => f.severity === k); return fs.length ? more(`${name} (${fs.length})`, `<ul class="conn">${fs.map(f => `<li><span class="tag ${sev[k]}">${esc(f.area.replace(/_/g, ' '))}</span> ${f.project ? `<button type="button" class="quiet small inline" data-a="openProject" data-id="${esc(f.project)}">Project ${esc(f.project)}</button>` : f.session ? `<button type="button" class="quiet small inline" data-a="open" data-id="${(j.sessions[f.session - 1] || {}).id || ''}">${esc(j.sessions[0].unit)} ${f.session}</button>` : 'Whole course'}: ${esc(f.finding)}<br><span class="dim">${esc(f.suggestion)}</span></li>`).join('')}</ul>`, k === 'must_fix') : ''; }).join('')}` : '<p class="dim">No review yet.</p>'}
      <div class="foot left">${engineActive() ? '<span class="dim">Claude is busy with this course.</span>' : J.unwritten(j).length ? '<span class="dim">A review can run once every session is written.</span>' : `<button type="button" class="pill" data-a="reviewRun" ${ENG.ready ? '' : 'aria-disabled="true"'}>${rv ? 'Run the review again on this draft' : 'Run an independent review'}</button>`}</div>
      ${j.pipeline === 2 && engineOurs() ? `<p class="pills"><button type="button" class="pill small" data-a="verifyEvidence" ${engineActive() ? 'aria-disabled="true"' : ''}>Have Loom fetch these pages itself and check the quotes</button><button type="button" class="pill small" data-a="attributionRun" ${engineActive() || !ENG.ready ? 'aria-disabled="true"' : ''}>Ask a separate reviewer to check who made each source</button></p><p class="dim">Fetching uses no AI and no plan usage. The reviewer is one request to Claude. Neither makes a source “original” alone.</p>` : ''}
      <h2>Sources (${(j.sources || []).length})</h2><p class="dim">Found by AI research${j.research && j.research.researchedAt ? ' on ' + esc(day(j.research.researchedAt)) : ''}. An address that opens is not proof. Only you can mark a source as checked.</p>
      <ul class="srcs">${(j.sources || []).map(s => sourceHTML(s, true)).join('') || '<li class="dim">No sources were recorded.</li>'}</ul>
      ${j.research && j.research.openQuestions.length ? more('Not settled by the research', ul(j.research.openQuestions)) : ''}${(j.assumptions || []).length ? more('What Claude assumed when planning', ul(j.assumptions)) : ''}${j.feasibility && j.feasibility.concern ? more('Will it fit the time?', `<p>${esc(j.feasibility.concern)}</p><p class="dim">Claude’s judgement. Nobody has timed it with learners.</p>`) : ''}${j.research && j.research.notOpened.length ? more('Seen in search results but not read', ul(j.research.notOpened.map(n => `${n.title} (${host(n.url)})`))) : ''}` : '<h2>Evidence</h2><p class="dim">None. This is a simulated example. No sources were looked for.</p>'}
    <p class="err" id="err" role="alert"></p>${undoBar()}</div>`;
}

/* ---------- lifecycle sheet ---------- */
// What a person should know before approving real content. None of these block approval: the team decides. Each must be acknowledged.
// What stands between this draft and "ready for a facilitator rehearsal". The same reasons an approved version would carry.
function teachOpen(j) { return !j || !real() ? [] : J.readinessOf({ ver: 0, at: new Date().toISOString(), journey: j }, []).why; }
let ackApprove = false;
function approvalWarnings() {
  const j = S.journey; if (!j || !real()) return [];
  const rv = j.review && j.review.output, out = [];
  if (!rv) out.push('No independent review has been run on this course.');
  else {
    const must = rv.findings.filter(f => f.severity === 'must_fix').length;
    if (j.review.rev !== j.rev) out.push('The independent review was made on an earlier draft. The draft has changed since.');
    if (must) out.push(`The independent review lists ${must} problem${must > 1 ? 's' : ''} marked “must fix”${j.review.rev !== j.rev ? ' on that earlier draft' : ''}.`);
    if (rv.teacher_could_run_it.answer !== 'yes') out.push(`The reviewer’s answer to “could a teacher run it?” was “${rv.teacher_could_run_it.answer.replace(/_/g, ' ')}”.`);
  }
  const flagged = j.sessions.filter(s => s.review).length; if (flagged) out.push(`${flagged} session${flagged > 1 ? 's are' : ' is'} marked “Look” because earlier work changed.`);
  const unchecked = (j.sources || []).filter(s => !s.personChecked).length; if (unchecked) out.push(`${unchecked} of ${(j.sources || []).length} sources have not been read by a person.`);
  out.push(...J.evidenceOpen(j));
  if (j.pipeline === 2) out.push(...J.v2Open(j));
  return out;
}
const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const fileStem = snap => `glitch-loom-${(courseName() || 'course').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'course'}-v${snap.ver}${J.readinessOf(snap).draft ? '-internal-draft' : ''}`;
function lifeHTML() {
  const L = S.life, order = ['draft', 'review', 'approved', 'exported'], names = ['Draft', 'Review', 'Approved version', 'Exported package'], at = order.indexOf(L.stage);
  const snap = L.snapshots.find(s => s.ver === L.ver), lastExp = L.exports[L.exports.length - 1], old = stale(), must = S.journey ? J.audit(S.journey) : [], look = S.journey ? R.readiness(S.journey).look : [];
  const working = L.stage === 'draft' || L.stage === 'review', blocked = working && (old || must.length > 0), warn = L.stage === 'review' && !blocked ? approvalWarnings() : [];
  const act = blocked ? '' : { draft: `<button type="button" class="go" data-a="lifeTo" data-v="review">Send to review</button>`, review: `<button type="button" class="pill" data-a="lifeTo" data-v="draft">Back to draft</button><button type="button" class="go" data-a="approve" ${warn.length && !ackApprove ? 'aria-disabled="true"' : ''}>${warn.length ? `Keep version ${L.ver} as an internal draft` : `Approve version ${L.ver}`}</button>`, approved: `<button type="button" class="go" data-a="export">Export package v${L.ver}</button>`, exported: `<button type="button" class="pill" data-a="export">Export v${L.ver} again</button>` }[L.stage];
  let pkg = ''; if (lastExp && snap) { try { pkg = `<details class="more"><summary>Show package contents (v${snap.ver})</summary><pre class="pkg" tabindex="0">${esc(JSON.stringify(J.buildPackage(snap), null, 2))}</pre></details>`; } catch (e) { pkg = `<p class="note">${esc(e.message)}</p>`; } }
  return `<div class="sheetin"><div class="bar"><h2 id="sh" tabindex="-1">Course lifecycle</h2><span class="grow"></span><button type="button" class="quiet" data-a="closeSheet">Close</button></div>
    <ol class="track">${names.map((n, i) => `<li${i === at ? ' aria-current="step"' : ''} class="${i < at ? 'past' : ''}">${n}</li>`).join('')}</ol>
    <p class="dim">You are working on version ${L.ver}. ${snap ? `Its snapshot is locked. ${esc(J.readinessOf(snap).label)}` : 'It has not been approved yet.'} Editing after approval starts a new draft and leaves approved snapshots untouched.</p>
    ${old ? `<div class="flag" role="alert"><p><span class="tag warn">Out of date</span> The brief changed after this journey was made. ${working ? 'It cannot go to review or be approved until they match.' : 'The approved snapshot below is unchanged and can still be exported.'}</p><div class="pills"><button type="button" class="pill small" data-a="lifeWeave">Go to the brief and weave again</button>${S.jBrief ? '<button type="button" class="pill small" data-a="lifeRestore">Put the brief back as it was</button>' : ''}</div></div>` : ''}
    ${working && must.length ? `<div class="flag" role="alert"><p><span class="tag bad">Not ready</span> ${must.length} thing${must.length > 1 ? 's' : ''} must be fixed before this can be approved.</p>${ul(must.slice(0, 4))}<div class="pills"><button type="button" class="pill small" data-a="lifeChecks">Open the checks</button></div></div>` : ''}
    ${warn.length ? `<div class="flag" role="group" aria-label="Before you approve"><p><span class="tag warn">Before you approve</span> Approval is your decision. These are open:</p>${ul(warn)}<label class="ack"><input type="checkbox" id="ackapprove" ${ackApprove ? 'checked' : ''}> I have read these. Ticking this does not fix them. Version ${L.ver} will be kept as an <strong>internal draft</strong>, marked “not ready to teach” here and in the exported package.</label></div>` : ''}
    ${working && !blocked && look.length && !warn.length ? `<p class="note"><span class="tag warn">${look.length} to look at</span> The structure holds, so the team may approve. The checks list things a person should read first. Approving does not resolve them. <button type="button" class="pill small" data-a="lifeChecks">Open the checks</button></p>` : ''}
    ${S.journey && J.planOf(S.journey).differs ? `<p class="note"><span class="tag warn">Differs from brief</span> The draft plans ${esc(J.planOf(S.journey).label)}. The brief asked for ${esc(J.planOf(S.journey).requested.span)}. Approving records the plan as it is and leaves the brief unchanged.</p>` : ''}
    <div class="foot left">${act}</div>
    <div class="three"><div><span class="tag ok">In the package</span><h3>Learner materials</h3><p class="dim">What learners do and how they show it.</p></div><div><span class="tag ok">In the package</span><h3>Teacher materials</h3><p class="dim">Materials, setup, guidance, sources and their standing.</p></div><div><span class="tag">Stays in Loom</span><h3>Internal notes</h3><p class="dim">Working notes, requests, review findings, change log.</p></div></div>
    ${L.snapshots.length ? `<h3>Approved snapshots</h3><ul class="conn">${L.snapshots.map(s => `<li><span class="tag ${J.readinessOf(s, L.trials).draft ? 'warn' : 'ok'}">v${s.ver} · ${esc(J.readinessOf(s, L.trials).short)}</span> ${day(s.at)} · ${s.journey.sessions.length} sessions · ${F.fmtMin(J.totalMin(s.journey))} · ${J.isReal(s.journey) ? 'written with Claude' : 'simulated example'}${L.exports.some(e => e.ver === s.ver) ? ' · exported' : ''}<br><span class="pills"><button type="button" class="quiet small" data-a="exportRead" data-v="${s.ver}|teacher">Teacher pack to read</button><button type="button" class="quiet small" data-a="exportRead" data-v="${s.ver}|learner">Learner handouts to read</button><button type="button" class="quiet small" data-a="exportVer" data-v="${s.ver}">Structured file</button></span></li>`).join('')}</ul>` : ''}
    ${pkg}
    ${snap && !J.readinessOf(snap, L.trials).draft ? `<h3>Rehearsal and pilot</h3><p class="dim">Record these only after they have happened. Loom cannot check them.</p><div class="addrow"><label class="sr" for="trk">What happened</label><select id="trk"><option value="rehearsal">A facilitator rehearsed it</option><option value="pilot">It was piloted with learners</option></select><label class="sr" for="trd">On</label><input id="trd" type="date" value="${localDay()}"><label class="sr" for="trn">What was learned</label><input id="trn" type="text" placeholder="What was learned, in a line"><button type="button" class="pill" data-a="trial">Record for v${snap.ver}</button></div>${(L.trials || []).length ? `<ul class="conn">${L.trials.map(t => `<li><span class="tag ok">${t.kind === 'pilot' ? 'Piloted' : 'Rehearsed'}</span> v${t.ver}, ${day(t.at)}${t.note ? ' · ' + esc(t.note) : ''}</li>`).join('')}</ul>` : ''}` : snap ? '<h3>Rehearsal and pilot</h3><p class="dim">This version is an internal draft. Resolve its open points in a new version before recording a rehearsal or a pilot.</p>' : ''}
    <h3>Publication on Glitch</h3>
    <p class="dim">Exporting is not publishing. Loom has no connection to the Glitch website. Record a publication only after the website team confirms it.</p>
    ${lastExp ? `<div class="addrow"><label for="pubd">Confirmed on</label><input id="pubd" type="date" value="${localDay()}"><button type="button" class="pill" data-a="pub">Record confirmation for v${lastExp.ver}</button></div>` : `<p class="note">Nothing has been exported yet.</p>`}
    ${L.publications.length ? `<ul class="conn">${L.publications.map(p => `<li><span class="tag ok">Confirmed</span> v${p.ver} published, confirmed ${day(p.at)}</li>`).join('')}</ul>` : ''}
    <p class="err" id="lerr" role="status"></p></div>`;
}
function bumpDraft() { const L = S.life; if (L.stage !== 'draft') { const top = Math.max(0, ...L.snapshots.map(s => s.ver)); if (top >= L.ver) L.ver = top + 1; L.stage = 'draft'; } }

/* ---------- course list ---------- */
function pickerHTML() {
  const made = { claude: 'written with Claude', simulated: 'simulated example' };
  const row = c => { const s = c.summary || {}, cur = c.id === course.id, facts = [s.format, s.sessions ? `${s.sessions} sessions` : 'no journey yet', made[s.made], s.counted ? (s.internalDrafts ? `${s.internalDrafts} internal draft${s.internalDrafts > 1 ? 's' : ''}, not ready to teach` : '') : '', s.counted ? (s.approved ? `${s.approved} approved on paper` : '') : (s.approved ? `${s.approved} locked version${s.approved > 1 ? 's' : ''}` : ''), 'saved ' + clock(c.updatedAt)].filter(Boolean).join(' · ');
    return `<li${cur ? ' class="cur"' : ''} data-find="${esc((c.name + ' ' + (s.topics || []).join(' ') + ' ' + (s.format || '')).toLowerCase())}">
      ${S.renaming === c.id ? `<div class="addrow"><label class="sr" for="rn">New name</label><input id="rn" type="text" value="${esc(c.name)}"><button type="button" class="pill small" data-a="renameSave" data-v="${c.id}">Save name</button><button type="button" class="quiet small" data-a="renameStart" data-v="">Cancel</button></div>`
      : c.archived ? `<div class="courseopen"><span class="t">${esc(c.name)}</span><span class="dim">${esc(facts)} · archived ${esc(day(c.archivedAt))}</span></div><div class="pills"><button type="button" class="pill small" data-a="courseArchive" data-v="${c.id}|0">Bring back</button><a class="quiet small" href="${esc(api.backupUrl(c.id))}" download>Download a backup</a></div>`
      : `<button type="button" class="courseopen" data-a="courseOpen" data-v="${c.id}" ${cur ? 'aria-current="true"' : ''}><span class="t">${esc(c.name)}</span><span class="dim">${esc(facts)}</span>${cur ? '<span class="tag ok">Open now</span>' : ''}</button>
      <div class="pills"><button type="button" class="quiet small" data-a="renameStart" data-v="${c.id}">Rename</button><button type="button" class="quiet small" data-a="courseCopy" data-v="${c.id}">Make a copy</button>${cur ? '' : `<button type="button" class="quiet small" data-a="courseArchive" data-v="${c.id}|1">Archive</button>`}<a class="quiet small" href="${esc(api.backupUrl(c.id))}" download>Download a backup</a></div>`}</li>`; };
  return `<div class="sheetin"><div class="bar"><h2 id="ph" tabindex="-1">Courses</h2><span class="grow"></span><button type="button" class="quiet" data-a="closePicker">Close</button></div>
    <p class="dim">Each course keeps its own brief, draft, history and approved versions${STORE === null ? '' : `. You are in test storage “${esc(STORE)}”, kept apart from real courses`}.</p>
    ${LIB.courses.length > 5 ? `<label class="sr" for="pf">Find a course by name or topic</label><input id="pf" type="search" autocomplete="off" placeholder="Find a course by name or topic">` : ''}
    <ul class="courses" id="plist">${LIB.courses.filter(c => !c.archived).map(row).join('') || '<li class="dim">No courses here. Start one, or bring one back from the archive below.</li>'}</ul>
    <p class="dim" id="pnone" hidden>No course matches that.</p>
    ${LIB.courses.some(c => c.archived) ? more(`Archive (${LIB.courses.filter(c => c.archived).length})`, `<p class="dim">Archived courses are kept whole, with their history and versions. Nothing is deleted.</p><ul class="courses">${LIB.courses.filter(c => c.archived).map(row).join('')}</ul>`) : ''}
    <div class="foot left"><button type="button" class="go" data-a="courseNew">Start a new course</button><label class="pill filepick" for="restorefile">Restore from a backup file</label><input id="restorefile" class="sr" type="file" accept="application/json,.json"></div>
    <p class="dim">A backup holds the whole course, including internal notes and history. Restoring always makes a new course. It never replaces one.</p>
    ${LIB.imports.length ? more(`Copies taken from browser storage (${LIB.imports.length})`, `<ul class="conn">${LIB.imports.map(i => `<li><span class="tag ${i.status === 'ok' ? 'ok' : 'bad'}">${i.status === 'ok' ? 'Readable' : 'Unreadable'}</span> From ${esc(i.origin)} on ${esc(day(i.importedAt))} · <a href="${esc(api.importUrl(i.hash))}" download>Download the exact copy</a>${i.reasons && i.reasons.length ? `<br><span class="dim">${esc(i.reasons[0])}</span>` : ''}</li>`).join('')}</ul><p class="dim">These are exact copies of work found in a browser when Loom moved to saving on disk. The browser’s own copy was not changed.</p>`) : ''}
    <p class="dim small">Loom ${esc(HEALTH.version || '')} · build ${esc(HEALTH.build || 'unknown')} · server started ${esc(String(HEALTH.startedAt || '').replace('T', ' ').slice(0, 16))}</p>
    <p class="err" id="perr" role="alert"></p></div>`;
}
function paintPicker(sel) { picker.innerHTML = pickerHTML(); const t = (sel && $(sel, picker)) || $('#ph', picker); if (t) t.focus({ preventScroll: true }); }

/* ---------- screens that stop everything else ---------- */
function viewRecovery() {
  return `<div class="swap">
    <div class="prog"><span class="px">Saved work · <span class="savestate bad">Saving is paused</span></span></div>
    <h1 id="qt" tabindex="-1">Loom cannot read this course</h1>
    <p class="lead">Nothing has been changed or deleted. The file on disk stays exactly as it is, and Loom will not save over it.</p>
    <div class="flag"><p><span class="tag warn">What is wrong</span></p><ul class="fx">${recovery.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul></div>
    <div class="pills col">
      <button type="button" class="pill" data-a="recDownload">Download the saved data</button>
      <button type="button" class="pill" data-a="recShow" aria-expanded="false">Show the saved data</button>
      <button type="button" class="pill" data-a="picker">Open another course</button>
      <button type="button" class="pill" data-a="courseNew">Start a new course and keep this one</button>
    </div>
    <pre class="pkg" id="recraw" tabindex="0" hidden></pre>
    <p class="err" id="err" role="alert"></p></div>`;
}
function viewUnsent() {
  return `<div class="swap">
    <div class="prog"><span class="px">Unsaved changes · <span class="savestate bad">Saving is paused</span></span></div>
    <h1 id="qt" tabindex="-1">Loom found changes that never reached the disk</h1>
    <p class="lead">This browser holds changes to “${esc(course.name)}” from ${esc(clock(new Date(unsent.at).toISOString()))} that were not saved, probably because the page closed or the server stopped.</p>
    ${unsent.stale ? '<p class="flag"><span class="tag warn">Note</span> The course on disk has also changed since then, in another window. Using the browser’s changes would replace that newer work, so Loom will save them as a separate course instead.</p>' : ''}
    <div class="pills col"><button type="button" class="pill" data-a="unsentUse">${unsent.stale ? 'Save those changes as a separate course' : 'Use those changes'}</button><button type="button" class="pill" data-a="unsentDrop">Keep what is on disk</button></div>
    <p class="dim">Nothing is deleted either way until you choose.</p><p class="err" id="err" role="alert"></p></div>`;
}
function viewFatal() {
  return `<div class="swap"><div class="prog"><span class="px">Loom</span></div><h1 id="qt" tabindex="-1">Loom’s local server is not answering</h1>
    <p class="lead">${fatal === 'server' ? 'The page opened, but the program that keeps your courses is not running, or it is an older version.' : esc(fatal)}</p>
    <p>Open the “glitch-loom” folder in Documents and double-click <strong>start.command</strong>. Then press the button below.</p>
    <p class="dim">Your courses are files on this computer. Nothing is lost while the server is off.</p>
    <div class="foot left"><button type="button" class="go" data-a="reload">Try again</button></div></div>`;
}
function conflictHTML() { return conflict ? `<div class="flag" role="alert"><p><span class="tag bad">Not saving</span> This course was changed in another window. Loom stopped saving from this window so that nothing is overwritten.</p><div class="pills"><button type="button" class="pill small" data-a="conflictReload">Open the newer version</button><button type="button" class="pill small" data-a="conflictFork">Save this window’s version as a separate course</button></div></div>` : ''; }

/* ---------- render ---------- */
let kbd = false;
// Make sure the current screen exists for the current answers. Branching or a refresh can leave it pointing nowhere.
function settle() {
  if (['journey', 'session', 'activity', 'checks', 'project'].includes(S.at) && !S.journey) S.at = 'summary';
  if (S.at === 'outline' && !(S.outlineDraft && E && E.plan && E.status === 'waiting_approval')) S.at = E ? 'generate' : 'summary';
  if (S.at === 'generate' && !E) S.at = 'summary';
  if (AFTER.includes(S.at)) return;
  const q = F.byId(S.at), path = F.activePath(S.answers);
  if (!q) { S.at = path[0].id; S.fromSummary = false; return; }
  if (!path.includes(q)) { const bad = path.find(k => F.problem(k, S.answers)); S.at = bad ? bad.id : 'summary'; if (!bad) S.fromSummary = false; }
}
function render(dir = 'fwd', focus = true) {
  repaintLater = false;
  const wrap = (html, cls = '') => { ui.className = cls === 'wide' ? 'mode-journey' : 'mode-q'; ui.innerHTML = `<section class="panel ${cls}" style="--dx:${dir === 'back' ? '-12px' : dir === 'none' ? '0px' : '12px'}" aria-labelledby="qt">${html}</section>`; };
  if (fatal) { wrap(viewFatal()); paintBrand(); if (focus) $('#qt').focus({ preventScroll: true }); return; }
  if (!booted) { wrap(`<div class="swap"><div class="prog"><span class="px">Loom</span></div><h1 id="qt" tabindex="-1">Opening your courses</h1></div>`); return; }
  if (recovery || unsent) { wrap(recovery ? viewRecovery() : viewUnsent()); paintSave(); paintBrand(); sync(); if (focus) $('#qt').focus({ preventScroll: true }); return; }
  settle();
  const q = F.byId(S.at);
  const html = q ? viewQ(q) : ({ summary: viewSummary, generate: viewGenerate, outline: viewOutline, journey: viewJourney, session: viewSession, activity: viewActivity, checks: viewChecks, project: viewProject }[S.at])();
  wrap(conflictHTML() + html, S.at === 'journey' ? 'wide' : ['outline', 'checks'].includes(S.at) ? 'mid' : ['session', 'activity', 'generate', 'summary', 'project'].includes(S.at) ? 'roomy' : '');
  roving(); save(); sync(); paintBrand();
  if (focus) { const h = $('#qt'); if (h) h.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }
}
// Redraw without moving the person: same scroll position, and focus back on the same control.
function keepSel() { const a = document.activeElement; if (!a || !ui.contains(a)) return null; if (a.id) return '#' + CSS.escape(a.id); if (a.dataset && a.dataset.a) return `[data-a="${a.dataset.a}"]` + (a.dataset.v !== undefined ? `[data-v="${CSS.escape(a.dataset.v)}"]` : '') + (a.dataset.id ? `[data-id="${CSS.escape(a.dataset.id)}"]` : ''); return null; }
function softRender(sel) { if (!sel) sel = keepSel(); const y = window.scrollY; render('none', false); window.scrollTo({ top: y }); if (sel) { const e = $(sel); if (e) e.focus({ preventScroll: true }); } }
function err(t, id = '#err') { const e = $(id) || $('#err') || $('#perr'); if (e) { e.textContent = t; if (t) e.scrollIntoView({ block: 'nearest' }); } if (t) say(t); }
// When an answer is missing or wrong, say so beside the input and put the cursor there.
function pointAt() { const c = $('#cin'), w = $('#cwrap'), t = (c && w && !w.hidden && c) || $('#tin') || $('#chin') || $('.pill[role][tabindex="0"]') || $('.pill[role]'); if (t) t.focus({ preventScroll: true }); }
const typing = () => { const a = document.activeElement; return !!S.editing || S.outlineOpen != null || S.outlineAsk || (a && /^(INPUT|TEXTAREA)$/.test(a.tagName) && ui.contains(a)); };

/* ---------- the engine, watched from the page ---------- */
function stopPoll() { clearTimeout(pollTimer); pollTimer = 0; }
async function pollEngine() {
  stopPoll(); if (!booted || !course.id || recovery) return;
  const id = course.id; let r; try { r = await api.engineGet(id); } catch (e) { if (E && E.status === 'running') pollTimer = setTimeout(pollEngine, 4000); return; }
  if (id !== course.id) return;
  const was = E ? JSON.stringify([E.status, E.savedAt, E.now && E.now.steps && E.now.steps.length]) : '';
  E = r.record; EBusy = r.busy;
  if (JSON.stringify(E ? [E.status, E.savedAt, E.now && E.now.steps && E.now.steps.length] : '') !== was) onEngine();
  if (E && (E.status === 'running' || EBusy)) pollTimer = setTimeout(pollEngine, 1500);
}
function onEngine() {
  let changed = false, jump = '';
  if (E && engineOurs() && R.absorb(S.journey, E)) { S.journey.rev = ++S.revSeq; changed = true; }
  if (E && engineOurs() && S.journey && S.journey.pipeline === 2 && R.mergeEvidence(S.journey, E)) { changed = true; }
  const rv = E && E.stages.review;
  if (rv && rv.status === 'done' && engineOurs() && !J.unwritten(S.journey).length && (!S.journey.review || S.journey.review.at !== rv.finishedAt)) {
    // The review is of this draft only if it judged this exact material. A review whose material is unknown
    // (an older record, or one this build cannot identify) is never claimed as current.
    const judged = rv.inputFingerprint || '', forThisDraft = !!judged && judged === R.reviewPrint(S.journey);
    S.journey.review = { at: rv.finishedAt, rev: forThisDraft ? S.journey.rev : -1, of: judged, requestId: rv.requestId || '', model: rv.model || '', output: rv.output }; changed = true;
  }
  if (E && E.status === 'waiting_approval' && E.stages.outline.status === 'done' && S.outlineFor !== E.stages.outline.finishedAt) { S.outlineFor = E.stages.outline.finishedAt; S.outlineDraft = clone(E.stages.outline.output); S.outlineEdited = false; S.ackOutline = false; S.outlineOpen = null; S.outlineAsk = false; changed = true; if (S.at === 'generate') jump = 'outline'; say('The outline is ready for you to read.'); }
  if (S.pendingEdit && E && E.edits && E.edits[S.pendingEdit.id] && E.edits[S.pendingEdit.id].status === 'done') { S.pending = R.previewFromEdit(S.journey, E.edits[S.pendingEdit.id], S.pendingEdit.req); S.pendingNote = ''; S.pendingEdit = null; changed = true; say('Preview ready. Nothing has changed yet.'); }
  if (offerAgain()) { changed = true; say('A change Claude finished is waiting for you. Nothing has changed yet.'); }
  if (S.pending && S.pending.needsRebuild && E) { const e = E.edits && E.edits[S.pending.editId]; S.pending = e && e.status === 'done' && S.journey ? R.previewFromEdit(S.journey, e, S.pending.req) : null; changed = true; }
  if (E && E.status === 'done' && S.at === 'generate' && S.journey && engineOurs()) say('Every session is written. Ready for you to read.');
  if (jump) { S.at = jump; render('fwd'); return; }
  if (S.at === 'generate' && !typing()) { const b = $('#genbody'); if (b) { softRender(document.activeElement && document.activeElement.dataset && document.activeElement.dataset.a ? `[data-a="${document.activeElement.dataset.a}"]` : null); return; } }
  if (changed || ['journey', 'session', 'activity', 'checks', 'summary', 'outline', 'project'].includes(S.at)) { if (typing()) { repaintLater = true; if (changed) save(); } else { const a = document.activeElement, sel = a && a.dataset && a.dataset.a ? `[data-a="${a.dataset.a}"]${a.dataset.v ? `[data-v="${CSS.escape(a.dataset.v)}"]` : ''}` : null; softRender(sel); } }
}
// Nothing is asked of Claude unless the course is saved as the person sees it.
async function engineDo(body) {
  if (recovery || conflict || unsent || !(await flushNow())) throw new Error('This course is not saved yet, so nothing was started. Wait for “Saved”, then try again.');
  const r = await api.engineDo(course.id, Object.assign({ courseVersion: course.version }, body)); E = r.record; EBusy = true; pollTimer = setTimeout(pollEngine, 700); return r;
}

/* ---------- actions ---------- */
function flushText() { const q = F.byId(S.at); if (!q) return; const t = $('#tin'), c = $('#cin'); if (t && q.type === 'text') { const cur = S.answers[q.id]; if (!cur || cur.value !== t.value) setAnswer(q, { value: t.value }, 'picked'); } if (c && S.answers[q.id]) S.answers[q.id].text = c.value; }
function goNext() {
  settle(); const q = F.byId(S.at); if (!q) return render('none');
  flushText(); save(); const p = F.problem(q, S.answers); if (p) { err(p); pointAt(); return; }
  const x = S.answers[q.id]; if (x && x.source === 'recommended') x.basedOn = F.basis(q.id, S.answers);
  const path = F.activePath(S.answers), i = path.indexOf(q);
  if (S.fromSummary) { const bad = path.find(k => F.problem(k, S.answers)); S.at = bad ? bad.id : 'summary'; if (!bad) S.fromSummary = false; }
  else S.at = i + 1 < path.length ? path[i + 1].id : 'summary';
  world.spark(); render('fwd');
}
function goBack() {
  flushText();
  if (S.at === 'summary') { const p = F.activePath(S.answers); S.at = p[p.length - 1].id; return render('back'); }
  if (S.fromSummary) { S.fromSummary = false; S.at = 'summary'; return render('back'); }
  const path = F.activePath(S.answers), i = path.findIndex(q => q.id === S.at);
  S.at = i > 0 ? path[i - 1].id : path[0].id; render('back');
}
function briefProblem() {
  const bad = F.activePath(S.answers).find(q => F.problem(q, S.answers)); if (bad) return `“${bad.short}” still needs an answer. Choose Edit beside it.`;
  if (J.conflicts(S.answers).length) return 'The brief does not fit yet. Choose one of the fixes above. Nothing has been changed.';
  return '';
}
function focusPreview(msg) { softRender(); const pv = $('.change'); if (pv) { pv.setAttribute('tabindex', '-1'); pv.focus({ preventScroll: true }); pv.scrollIntoView({ block: 'nearest' }); } if (msg) say(msg); }
async function ask(kind, text) {
  const scope = S.at === 'journey' ? 'journey' : S.at === 'session' && S.scope === 'activity' ? 'session' : S.scope;
  if (kind === 'text' && !String(text || '').trim()) return err('Describe the change, or pick one above.');
  const req = { scope, kind, text: String(text || '').trim(), sessionId: S.sel, activityId: S.act };
  S.pendingNote = '';
  if (!real()) { S.pending = J.previewChange(S.journey, req); return focusPreview('Preview ready. Nothing has changed yet.'); }
  if (engineActive()) return err('Claude is busy with this course. Wait until it finishes.');
  if (!ENG.ready) return err(ENG.blocker);
  const j = S.journey, targets = scope === 'journey' ? j.sessions : j.sessions.filter(s => s.id === S.sel);
  if (targets.some(s => s.status !== 'written' && s.status !== undefined)) return err('A session that is not written yet cannot be changed. Write it first.');
  const instruction = kind === 'text' ? req.text : R.QUICK[kind], id = newId();
  const parts = targets.map(s => { const x = scope === 'activity' ? s.activities.find(y => y.id === S.act) : null; return { number: j.sessions.indexOf(s) + 1, minutes: s.minutes, topics: s.threads.map(t => j.topics[t]), buildsOn: R.numbersOf(j, s.buildsOn), content: R.sessionBack(s), activity: x ? R.activityBack(x) : undefined }; });
  if (scope === 'activity' && !parts[0].activity) return err('Open a step first, then ask for a change to it.');
  const label = kind === 'text' ? req.text : J.KINDS[kind];
  try { await engineDo({ action: 'edit', editId: id, scope, instruction, aboutTime: kind === 'shorter' || /\b(shorter|longer|minutes?|hours?|time|length|quicker)\b/i.test(instruction), parts, context: R.writtenNow(j), req, baseRev: j.rev, baseUid: j.uid }); }
  catch (e) { return err(e.message); }
  S.pendingEdit = { id, req, label, askedAt: new Date().toISOString() }; S.askOpen = false; focusPreview('Claude is working on your change. Nothing has changed yet.');
}
// Moving to another screen closes an instant preview. A change Claude wrote took minutes, so it stays until it is accepted or rejected.
// Each Undo step holds a whole copy of the draft. Twelve steps keep the saved file a sensible size.
function trimUndo() { while (S.undo.length > 12) S.undo.shift(); }
function leave() { if (S.pending && S.pending.kind === 'ai' && !S.pending.noop) return; S.pending = null; S.pendingNote = ''; }
const settle_ = id => { if (id) { S.settled = (S.settled || []).filter(x => x !== id).concat(id).slice(-40); } };
// A finished change that nobody has accepted, rejected or given up is offered again, for example after the page was closed while Claude worked.
function reqOf(e) { if (e.req && typeof e.req === 'object') return e.req; const n = e.parts && e.parts[0] && e.parts[0].number, s = S.journey.sessions[n - 1]; return e.scope === 'activity' || !s ? null : { scope: e.scope, kind: 'text', text: e.instruction, sessionId: s.id, activityId: null }; }
function offerAgain() {
  if (S.pending || S.pendingEdit || !E || !E.edits || !S.journey || !real()) return false;
  const e = Object.values(E.edits).filter(x => x.status === 'done' && !(S.settled || []).includes(x.id) && x.baseUid === S.journey.uid && x.baseRev === S.journey.rev && reqOf(x)).sort((a, b) => String(b.askedAt).localeCompare(String(a.askedAt)))[0];
  if (!e) return false;
  S.pending = R.previewFromEdit(S.journey, e, reqOf(e)); S.pendingNote = ''; return true;
}
// A preview is tied to the draft it was made from. When the draft moves, the preview is made again, never reused.
function rebuildPreview(why) {
  const p = S.pending;
  if (p.kind === 'ai') { settle_(p.editId); S.pending = null; S.pendingNote = ''; softRender('[data-a="askOpen"]'); err('The draft changed, so Claude’s preview no longer fits it. Nothing was applied. Ask again if you still want the change.'); return; }
  S.pending = J.previewChange(S.journey, p.req); S.pendingNote = why; focusPreview(why);
}
function commit(after, label, target, what) { const lost = R.withdrawStaleChecks(S.journey, after); if (lost) setTimeout(() => say(`${lost} claim${lost > 1 ? 's were' : ' was'} changed after a person checked ${lost > 1 ? 'them' : 'it'}. ${lost > 1 ? 'Those checks no longer count' : 'That check no longer counts'}.`), 600); S.revSeq++; after.rev = S.revSeq; S.undo.push({ journey: S.journey, label, target }); trimUndo(); S.journey = after; S.log.push({ what, label, target }); bumpDraft(); }
// Redraw the dialog and keep keyboard focus on a control that still exists.
let lifeReturn = '[data-a="life"]';
function paintSheet(sel) { sheet.innerHTML = lifeHTML(); const t = (sel && $(sel, sheet)) || $('.go', sheet) || $('.foot .pill', sheet) || $('.flag .pill', sheet) || $('#sh', sheet); if (t) t.focus({ preventScroll: true }); paintSave(); }
function fields() { const o = {}; $$('.editform [id^="e-"]').forEach(e => { o[e.id.slice(2)] = e.value; }); return o; }
// The browser is asked to save the file, and Loom cannot tell whether it did. So a copy is also kept on this computer, and the person is told exactly what was kept.
async function keepCopy(text, name, ver, kind) {
  try { const r = await api.saveExport(course.id, { name, text, ver, kind }); return { ok: true, ...r }; } catch (e) { return { ok: false, error: e.message }; }
}
// A receipt belongs to the course that made the export. If the person has opened another course by the time the copy is kept, the receipt is written into the owning course's own file and nothing is said on the wrong screen.
async function settleReceipt(ownerId, ownerState, rec, k) {
  if (!k.ok) return false;
  rec.kept = { name: k.name, sha256: k.sha256, bytes: k.bytes };
  if (course.id === ownerId && S === ownerState) { save('export'); return true; }
  try {
    const c = await api.get(ownerId), st = JSON.parse(c.raw), e = ((st.life || {}).exports || []).find(x => x.at === rec.at && x.ver === rec.ver);
    if (!e) return false; e.kept = rec.kept;
    await api.put(ownerId, { raw: JSON.stringify(st), baseVersion: c.meta.version, name: c.meta.name, summary: c.meta.summary, reason: 'export' });
    return true;
  } catch (err) { return false; }
}
const keptLine = (k, what) => k.ok ? `Download started for ${what}. Loom cannot see whether your browser saved it. A copy is also kept on this computer as “${k.name}” (${Math.round(k.bytes / 1024)} KB, checksum ${k.sha256.slice(0, 12)}) in this course’s exports folder.` : `Download started for ${what}. Loom cannot see whether your browser saved it, and it could not keep its own copy (${k.error}).`;
function download(text, name, type = 'application/json') { const blob = new Blob([text], { type }), url = URL.createObjectURL(blob), l = document.createElement('a'); l.href = url; l.download = name; document.body.appendChild(l); l.click(); l.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000); }

const A = {
  pick(v) {
    const q = F.byId(S.at), multi = q.type === 'multi', x = S.answers[q.id] || {};
    if (multi) { let list = (x.value || []).slice(); if (list.includes(v)) list = list.filter(k => k !== v); else { if (v === q.exclusive) list = [v]; else { const g = (q.groups || []).find(y => y.of.includes(v)); list = list.filter(k => k !== q.exclusive && !(g && g.of.includes(k))); list.push(v); } } setAnswer(q, { value: list }, 'picked'); }
    else setAnswer(q, { value: v }, v === CUSTOM ? 'custom' : 'picked');
    patchQ(q); world.spark(); if (v === CUSTOM && !$('#cwrap').hidden) $('#cin').focus();
  },
  rec() { const q = F.byId(S.at), r = F.recommend(q, S.answers); if (!r) return; setAnswer(q, { value: r.v, why: r.why }, 'recommended'); S.answers[q.id].why = r.why; save(); patchQ(q); world.spark(); say('Suggested: ' + F.labelOf(q, S.answers)); },
  suggest() { $('#sug').innerHTML = `<p class="hint">Pick one to start from, then edit it</p><div class="pills col swap">${F.outcomeIdeas(S.answers).map(s => `<button type="button" class="pill small" data-a="useSug" data-v="${esc(s)}">${esc(s)}</button>`).join('')}</div><p class="dim">Built from your topic by a simple rule. Nothing was researched.</p>`; },
  useSug(v) { const q = F.byId(S.at); $('#tin').value = v; setAnswer(q, { value: v, why: 'Started from a suggestion built from your topic and format.' }, 'recommended'); S.answers[q.id].why = 'Started from a suggestion built from your topic and format.'; save(); $('#detail').innerHTML = detailHTML(q); $('#tin').focus(); },
  addchip() { const q = F.byId(S.at), inp = $('#chin'), t = inp.value.trim(), list = ((S.answers[q.id] || {}).value || []).slice(); if (!t) return; if (list.length >= q.max) return err(`${q.max} topics is the most Loom will weave together.`); if (list.some(k => k.toLowerCase() === t.toLowerCase())) return err('That topic is already added.'); list.push(t); setAnswer(q, { value: list }, 'picked'); $('#chips').innerHTML = chipsHTML(list); inp.value = ''; inp.focus(); err(''); world.spark(); },
  delchip(_, el) { const q = F.byId(S.at), list = (S.answers[q.id].value || []).slice(); list.splice(+el.dataset.i, 1); setAnswer(q, { value: list }, 'picked'); $('#chips').innerHTML = chipsHTML(list); $('#chin').focus(); },
  next: goNext, back: goBack,
  edit(_, el) { S.fromSummary = true; S.at = el.dataset.id; render('back'); },
  noteOk() { bootNote = ''; paintBrand(); const h = $('#qt'); if (h) h.focus({ preventScroll: true }); },
  async engineCheck() { ENG = { ready: false, blocker: 'Checking…', checking: true }; softRender(); try { ENG = await api.engine(true); } catch (e) { ENG = { ready: false, blocker: e.message }; } softRender('[data-a="weaveReal"], [data-a="engineCheck"]'); },

  /* simulated example */
  weave() { const p = briefProblem(); if (p) return err(p); if (S.journey) { $('#confirm').innerHTML = `<p class="flag swap"><span class="tag warn">Check</span> This replaces the current draft journey with a simulated example. Approved snapshots are kept. <button type="button" class="pill small" data-a="weaveYes">Replace the draft</button> <button type="button" class="pill small" data-a="weaveNo">Keep it</button></p>`; $('[data-a="weaveYes"]').focus(); return; } A.weaveYes(); },
  weaveNo() { $('#confirm').innerHTML = ''; },
  weaveYes() { let j; try { j = J.makeJourney(S.answers); } catch (e) { return err('Loom could not make an example from this brief: ' + e.message); } j.rev = ++S.revSeq; S.journey = j; S.jDigest = F.briefDigest(S.answers); S.jBrief = clone(S.answers); S.undo = []; S.pending = null; S.pendingEdit = null; S.pendingNote = ''; S.log.push({ what: 'Woven', label: 'Simulated example from the brief', target: 'Whole journey' }); bumpDraft(); S.at = 'journey'; S.sel = null; render('fwd'); save('weave'); say('Simulated example ready. It is not real content.'); },

  /* real content */
  weaveReal() {
    const p = briefProblem(); if (p) return err(p); if (!ENG.ready) return err(ENG.blocker);
    const n = R.planFor(S.answers).sessions;
    $('#confirm').innerHTML = `<p class="flag swap"><span class="tag">Before you start</span> Claude will first map every topic and foundation your outcome needs, have that checked by a separate reviewer, search the web for sources for each of them, have the sources audited by another, and propose an outline that a third reviewer checks. That is about 8 to 12 requests before you see anything, and can take an hour. Nothing is written until you approve the outline. After that it writes ${n} session${n > 1 ? 's' : ''}, the projects and a review, one request each, using your Claude plan’s included usage. Loom cannot see or change your account’s billing settings. If the Claude tool reports that paid extra usage is in use, Loom stops that request. That is a safeguard after the fact, not a guarantee.${S.journey ? ' The current draft is replaced only when you approve the new outline. Approved snapshots are kept.' : ''} <button type="button" class="pill small" data-a="weaveRealYes">Start</button> <button type="button" class="pill small" data-a="weaveNo">Not now</button></p>`; $('[data-a="weaveRealYes"]').focus();
  },
  async weaveRealYes() {
    const p = briefProblem(); if (p) return err(p);
    const kept = { genBrief: S.genBrief, genDigest: S.genDigest, outlineDraft: S.outlineDraft, outlineFor: S.outlineFor };
    S.genBrief = clone(S.answers); S.genDigest = F.briefDigest(S.answers); S.outlineDraft = null; S.outlineFor = ''; save('weave');
    if (!(await flushNow())) { Object.assign(S, kept); return err('The brief could not be saved, so nothing was started. Wait for “Saved”, then try again.'); }
    try { await engineDo({ action: 'begin', brief: R.briefFor(S.answers), plan: R.planFor(S.answers), digest: S.genDigest, pipeline: 2 }); } catch (e) { return err(e.message); }
    S.at = 'generate'; render('fwd'); say('Claude has started looking for sources.');
  },
  toGenerate() { S.at = E && E.status === 'waiting_approval' && S.outlineDraft ? 'outline' : 'generate'; render('fwd'); },
  toOutline() { S.at = 'outline'; render('fwd'); },
  async engineStop() { try { await api.engineStop(course.id); } catch (e) { return err(e.message); } say('Stopping. Finished parts are kept.'); pollTimer = setTimeout(pollEngine, 600); },
  async engineResume() { try { await engineDo({ action: 'resume', written: engineOurs() ? R.writtenNow(S.journey) : undefined }); } catch (e) { return err(e.message); } softRender('[data-a="engineStop"]'); say('Resumed. Only unfinished work is being done.'); },
  async retrySession(v) { try { await engineDo({ action: 'retry_session', index: +v, written: engineOurs() ? R.writtenNow(S.journey) : undefined }); } catch (e) { return err(e.message); } S.at = 'generate'; render('fwd'); },
  outlineEdit(v) { S.outlineOpen = v === '' || v == null ? null : +v; softRender(S.outlineOpen == null ? '#qt' : '#o-title'); },
  outlineSave(v) { const s = S.outlineDraft.sessions[+v], t = $('#o-title').value.trim(), o = $('#o-outcome').value.trim(), k = $('#o-task').value.trim(); if (!t || !o || !k) return err('A title, an outcome and a task are all needed.', '#oerr'); if (t !== s.title || o !== s.outcome || k !== s.key_task) { Object.assign(s, { title: t, outcome: o, key_task: k }); S.outlineEdited = true; } S.outlineOpen = null; softRender('#qt'); },
  outlineOption(v) { const tc = (S.outlineDraft || {}).time_conflict || {}, x = (tc.options || [])[+v]; if (!x) return; S.outlineAsk = true; softRender('#ofb'); const f = $('#ofb'); if (f) { f.value = `Please revise the outline so that it does this: ${x.label}. ${x.effect}`; f.focus(); } },
  outlineAsk() { S.outlineAsk = !S.outlineAsk; softRender(S.outlineAsk ? '#ofb' : '[data-a="outlineAsk"]'); },
  async outlineRevise() { const t = $('#ofb').value.trim(); if (!t) return err('Say what should be different.'); try { await engineDo({ action: 'revise_outline', feedback: t }); } catch (e) { return err(e.message); } S.outlineAsk = false; S.at = 'generate'; render('fwd'); say('Claude is writing a new outline.'); },
  async outlineApprove() {
    const o = S.outlineDraft, brief = E.brief, plan = E.plan, base = S.genBrief || S.answers, v2 = E.pipeline === 2, open = v2 ? V.outlineOpenItems(o, E) : [];
    if (open.length && !S.ackOutline) return err('Tick the box to confirm you have read what is still open.');
    try { await engineDo({ action: 'approve_outline', outline: o, edited: !!S.outlineEdited, acknowledged: open }); } catch (e) { return err(e.message); }
    const ex = v2 ? { map: E.stages.map.output, coverage: E.stages.outline.coverage || null, accounting: E.accounting, policy: E.policy, acknowledged: open, agents: R.agentsFrom(E), prepared: E.prepared || [] } : null;
    const j = R.fromOutline(o, brief, plan, E.stages.research.output, base, ex); if (v2 && S.outlineEdited) j.outlineEditedAfterReview = true; j.rev = ++S.revSeq; j.engineRun = E.startedAt;
    S.journey = j; S.jDigest = S.genDigest || F.briefDigest(base); S.jBrief = clone(base); S.undo = []; S.pending = null; S.pendingEdit = null; S.pendingNote = ''; S.sel = null;
    S.log.push({ what: 'Outline approved', label: S.outlineEdited ? 'Outline approved with your edits' : 'Outline approved as proposed', target: 'Whole journey' }); bumpDraft();
    S.at = 'generate'; render('fwd'); save('weave'); say('Outline approved. Claude is writing the sessions.');
  },
  async ideaResearch(v) { if (!ENG.ready) return err(ENG.blocker); if (engineActive()) return err('Claude is busy with this course. Wait for it to finish.'); const hint = (S.answers.pick && S.answers.pick.value === CUSTOM && S.answers.pick.text) || ''; try { await engineDo({ action: 'ideas', kind: v === 'next' ? 'next' : 'trending', hint }); } catch (e) { return err(e.message); } IDEAS = { kind: v === 'next' ? 'next' : 'trending', status: 'running' }; watchIdeas(); softRender('#qt'); say('Claude is researching. The brief is not changed.'); },
  ideaUse(v) { const i = IDEAS && IDEAS.ideas && IDEAS.ideas[+v]; if (!i) return; const q = F.byId('pick'); setAnswer(q, { value: CUSTOM, text: i.idea }, 'researched'); save(); softRender('#cin'); say(`“${i.idea}” is now the answer. You can still change it.`); },
  async verifyEvidence() { try { await engineDo({ action: 'verify_evidence' }); } catch (e) { return err(e.message); } softRender('#qt'); say('Loom is fetching the pages itself. No AI is used.'); },
  async attributionRun() { if (!ENG.ready) return err(ENG.blocker); try { await engineDo({ action: 'attribution_review' }); } catch (e) { return err(e.message); } softRender('#qt'); say('A separate reviewer is checking who made each source.'); },
  async reviewRun() { if (!ENG.ready) return err(ENG.blocker); const j = S.journey; S.journey.reviewLaunch = { rev: j.rev, uid: j.uid, of: R.reviewPrint(j) }; try { await engineDo({ action: 'review', sessions: R.reviewInput(j), projects: R.reviewProjects(j).length ? R.reviewProjects(j) : undefined }); } catch (e) { S.journey.reviewLaunch = null; return err(e.message); } save('review'); softRender('#qt'); say('Claude is reviewing this draft.'); },

  /* moving around the journey */
  openJourney() { S.at = 'journey'; render('fwd'); },
  toSummary() { S.at = 'summary'; leave(); S.editing = null; render('back'); },
  toJourney() { S.at = 'journey'; leave(); S.editing = null; S.askOpen = false; render('back'); },
  toSession() { S.at = 'session'; leave(); S.editing = null; S.askOpen = false; S.scope = 'session'; render('back'); },
  toChecks() { S.at = 'checks'; leave(); S.askOpen = false; render('fwd'); },
  openProject(_, el) { S.selP = el.dataset.id; S.at = 'project'; leave(); S.editing = null; S.askOpen = false; render('fwd'); },
  async retryProject(v) { try { await engineDo({ action: 'retry_project', index: +v, written: engineOurs() ? R.writtenNow(S.journey) : undefined }); } catch (e) { return err(e.message); } S.at = 'generate'; render('fwd'); },
  open(_, el) { if (!el.dataset.id) return; S.sel = el.dataset.id; S.at = 'session'; S.tab = 'learner'; leave(); S.editing = null; S.askOpen = false; S.scope = 'session'; render('fwd'); },
  prevS() { const j = S.journey, i = j.sessions.findIndex(s => s.id === S.sel); if (i > 0) { S.sel = j.sessions[i - 1].id; leave(); S.askOpen = false; render('back'); } },
  nextS() { const j = S.journey, i = j.sessions.findIndex(s => s.id === S.sel); if (i < j.sessions.length - 1) { S.sel = j.sessions[i + 1].id; leave(); S.askOpen = false; render('fwd'); } },
  act(v) { S.act = v; S.at = 'activity'; S.tab = 'learner'; S.scope = 'activity'; leave(); S.askOpen = false; render('fwd'); },
  prevA() { const s = S.journey.sessions.find(x => x.id === S.sel), k = s.activities.findIndex(x => x.id === S.act); if (k > 0) { S.act = s.activities[k - 1].id; S.tab = 'learner'; leave(); S.askOpen = false; render('back'); } },
  nextA() { const s = S.journey.sessions.find(x => x.id === S.sel), k = s.activities.findIndex(x => x.id === S.act); if (k < s.activities.length - 1) { S.act = s.activities[k + 1].id; S.tab = 'learner'; leave(); S.askOpen = false; render('fwd'); } },
  tab(v) { S.tab = v; softRender(`[role="tab"][data-v="${v}"]`); },
  scope(v) { S.scope = v; softRender(`[data-a="scope"][data-v="${v}"]`); },
  lookDone() { const j = clone(S.journey), s = j.sessions.find(x => x.id === S.sel); s.review = null; commit(j, 'Marked as checked', `${s.unit} ${j.sessions.indexOf(s) + 1}: ${s.title}`, 'Checked'); softRender('#qt'); },
  sourceCheck(v) { const j = clone(S.journey), s = (j.sources || []).find(x => x.id === v); if (!s) return; s.personChecked = s.personChecked ? null : { at: new Date().toISOString() }; commit(j, s.personChecked ? `Marked ${v} as read by a person` : `Marked ${v} as not read`, s.title, 'Source'); softRender(`[data-a="sourceCheck"][data-v="${CSS.escape(v)}"]`); },

  /* changes */
  ask(v) { return ask(v); },
  askText() { return ask('text', $('#ask').value); },
  askDrop() { settle_(S.pendingEdit && S.pendingEdit.id); S.pendingEdit = null; softRender('[data-a="askOpen"]'); say('Given up. Nothing changed.'); },
  accept() {
    const p = S.pending; if (!p || p.noop) return;
    const r = J.applyPreview(S.journey, p, S.revSeq + 1);
    if (!r.ok) { rebuildPreview('The draft changed after this preview was made, so Loom rebuilt the preview from the current draft. Nothing was applied. Check it, then accept again.'); return; }
    S.revSeq++; S.undo.push({ journey: S.journey, label: p.label, target: p.target, editId: p.kind === 'ai' ? p.editId : undefined }); trimUndo(); S.journey = r.journey; S.log.push({ what: 'Accepted', label: p.label, target: p.target }); settle_(p.editId); S.pending = null; S.pendingNote = ''; S.askOpen = false; bumpDraft();
    if (S.sel && !S.journey.sessions.some(s => s.id === S.sel)) S.sel = S.journey.sessions[0].id; softRender('[data-a="undo"]'); say('Change applied. You can undo it.');
  },
  reject() { const p = S.pending; if (!p) return; if (!p.noop) S.log.push({ what: 'Rejected', label: p.label, target: p.target }); settle_(p.editId); S.pending = null; S.pendingNote = ''; softRender('.change .pill, [data-a="askOpen"]'); say('Rejected. Nothing changed.'); },
  undo() {
    const u = S.undo.pop(); if (!u) return; S.journey = u.journey; S.log.push({ what: 'Undone', label: u.label, target: u.target }); bumpDraft();
    if (S.sel && !S.journey.sessions.some(s => s.id === S.sel)) S.sel = S.journey.sessions[0].id;
    if (S.pending) { rebuildPreview('You undid a change while this preview was open, so Loom rebuilt it from the current draft. The undone change is not part of it.'); return; }
    if (u.editId) { S.settled = (S.settled || []).filter(x => x !== u.editId); if (offerAgain()) { softRender('[data-a="reject"]'); say('Undone. The journey is back to how it was. Claude’s change is kept as a preview in case you want it again.'); return; } }
    softRender('.change .pill, [data-a="askOpen"]'); say('Undone. The journey is back to how it was.');
  },
  askOpen() { S.askOpen = true; softRender('.change h2'); const h = $('.change .pill') || $('.change .quiet'); if (h) h.focus({ preventScroll: true }); },
  askClose() { S.askOpen = false; softRender('[data-a="askOpen"]'); },
  sim() { S.simOpen = !S.simOpen; softRender('[data-a="sim"]'); },
  editProject() { if (S.pending || S.pendingEdit) return err('Finish the open change first.'); S.editing = { kind: 'project', projectId: S.selP }; softRender('#e-title'); },
  editSession() { if (S.pending || S.pendingEdit) return err('Finish the open change first.'); S.editing = { kind: 'session', sessionId: S.sel }; softRender('#e-title'); },
  editActivity() { if (S.pending || S.pendingEdit) return err('Finish the open change first.'); S.editing = { kind: 'activity', sessionId: S.sel, activityId: S.act }; softRender(real() ? '#e-title' : '#e-minutes'); },
  claimCheck(v) { const [sid, k] = String(v).split('|'), r = R.checkClaim(S.journey, sid, +k); if (r.error) return err(r.error); commit(r.after, r.checked ? 'Claim marked as checked against its source' : 'Claim marked as not checked', r.target, 'Source'); softRender(`[data-a="claimCheck"][data-v="${CSS.escape(v)}"]`); },
  projClaimCheck(v) { const [pid, k] = String(v).split('|'), after = clone(S.journey), p = (after.projects || []).find(x => x.id === pid), c = p && p.content && (p.content.claims || [])[+k]; if (!c) return err('That claim is no longer in the draft.'); const was = J.checkedOn(c); if (c.personChecked) c.personChecked = null; else { c.personChecked = { at: new Date().toISOString(), of: J.claimPrint(c) }; delete c.checkWithdrawn; } commit(after, was ? 'Claim marked as not checked' : 'Claim marked as checked against its source', `Claim in project ${pid}`, 'Source'); softRender(`[data-a="projClaimCheck"][data-v="${CSS.escape(v)}"]`); },
  claimType(v) { const [sid, k, type] = String(v).split('|'), r = R.retypeClaim(S.journey, sid, +k, type); if (r.error) return err(r.error); commit(r.after, `Claim marked as ${R.CLAIM[type].toLowerCase()}`, r.target, 'Edited'); softRender(`[data-a="undo"]`); say('Claim relabelled. You can undo it.'); },
  replaceOpen() { if (S.pending || S.pendingEdit) return err('Finish the open change first.'); replacePv = null; S.editing = { kind: 'replace', find: '', replace: '' }; softRender('#e-find'); },
  replacePreview() { const f = fields(), r = R.replaceText(S.journey, f.find, f.replace); replacePv = r.error ? null : r; S.editing = { kind: 'replace', find: f.find, replace: f.replace, rev: S.journey.rev }; softRender(r.error ? '#e-' + (r.field || 'find') : r.after ? '[data-a="replaceApply"]' : '#e-find'); if (r.error) err(r.error); else say(r.none ? 'Those words are not in the draft.' : `${r.total} place${r.total > 1 ? 's' : ''} would change. Nothing has changed yet.${r.withdrawn ? ` ${r.withdrawn} claim${r.withdrawn > 1 ? 's' : ''} a person checked would change, so ${r.withdrawn > 1 ? 'those checks' : 'that check'} would no longer count.` : ''}`); },
  replaceApply() { const e = S.editing, f = fields(); if (!e || !replacePv || !replacePv.after || e.rev !== S.journey.rev || f.find !== e.find || f.replace !== e.replace) return A.replacePreview();
    const n = replacePv.total; commit(replacePv.after, `Replaced “${brief_(e.find, 40)}” with “${brief_(e.replace, 40) || 'nothing'}” in ${n} place${n > 1 ? 's' : ''}`, 'Whole journey', 'Replaced'); replacePv = null; S.editing = { kind: 'replace', find: '', replace: '' }; softRender('#e-find'); say(`Replaced in ${n} place${n > 1 ? 's' : ''}. You can undo it.`); },
  editCourse() { if (S.pending || S.pendingEdit) return err('Finish the open change first.'); S.editing = { kind: 'course' }; softRender('#e-finalEvidence'); },
  editCancel() { S.editing = null; softRender('#qt'); say('Cancelled. Nothing changed.'); },
  editSave() {
    const r = R.applyDirect(S.journey, Object.assign({}, S.editing, { fields: fields() }));
    if (r.error) { err(r.error); const f = r.field && $('#e-' + r.field); if (f) f.focus(); return; }
    if (r.same) { S.editing = null; softRender('#qt'); say('Nothing was different, so nothing changed.'); return; }
    commit(r.after, S.editing.kind === 'activity' ? 'Your edit to a step' : S.editing.kind === 'course' ? 'Your edit to the course statement' : S.editing.kind === 'project' ? 'Your edit to a project' : 'Your edit to a session', r.target, 'Edited'); S.editing = null; softRender('[data-a="undo"]');
    say(`Saved your edit.${r.flagged.length ? ` ${r.flagged.length} later session${r.flagged.length > 1 ? 's are' : ' is'} marked for a look.` : ''}${r.plan.differs ? ' Planned time now differs from the brief.' : ''}`);
  },

  /* lifecycle */
  life() { if (!sheet.open) sheet.showModal(); paintSheet('#sh'); },
  closeSheet() { sheet.close(); },
  lifeTo(v) { if (v === 'review' && (stale() || J.audit(S.journey).length)) return paintSheet(); ackApprove = false; S.life.stage = v; save('stage'); paintSheet(); },
  lifeWeave() { S.at = 'summary'; leave(); lifeReturn = '[data-a="weaveReal"], [data-a="weave"]'; sheet.close(); },
  lifeChecks() { S.at = 'checks'; lifeReturn = '#qt'; sheet.close(); },
  lifeRestore() { if (!S.jBrief) return; S.answers = clone(S.jBrief); save('brief-restored'); paintSheet(); $('#lerr').textContent = 'The brief is back to what this journey was made from.'; },
  approve() {
    if (stale() || J.audit(S.journey).length) return paintSheet(); const L = S.life; if (L.stage !== 'review') return paintSheet();
    const warn = approvalWarnings(); if (warn.length && !ackApprove) { paintSheet('#ackapprove'); $('#lerr').textContent = 'Tick the box to confirm you have read what is still open.'; return; }
    if (L.snapshots.some(s => s.ver === L.ver)) L.ver = Math.max(...L.snapshots.map(s => s.ver)) + 1; // an approved snapshot is never replaced
    L.snapshots.push({ ver: L.ver, at: new Date().toISOString(), journey: clone(S.journey), brief: clone(S.answers), openAtApproval: warn }); if (warn.length) S.log.push({ what: 'Approved with open points', label: warn.join(' '), target: `Version ${L.ver}` }); ackApprove = false; L.stage = 'approved'; save('approve'); paintSheet(); $('#lerr').textContent = warn.length ? `Version ${L.ver} is kept as an internal draft. Its snapshot is locked. It is not ready to teach.` : `Version ${L.ver} approved. Its snapshot is locked.`;
  },
  exportVer(v) { return A.export(v); },
  exportRead(v) { const [ver, who] = String(v).split('|'), snap = S.life.snapshots.find(s => s.ver === +ver); if (!snap) return; let pkg; try { pkg = J.buildPackage(Object.assign({}, snap, { trials: S.life.trials || [] })); } catch (e) { $('#lerr').textContent = e.message; return; } const html = J.packHTML(pkg, who), fname = `${fileStem(snap)}-${who === 'teacher' ? 'teacher-pack' : 'learner-handouts'}.html`; download(html, fname, 'text/html'); $('#lerr').textContent = `Download started: ${who === 'teacher' ? 'teacher pack' : 'learner handouts'} for version ${snap.ver}. Saving a copy on this computer…`; const ownerId = course.id; keepCopy(html, fname, snap.ver, who).then(k => { const e = $('#lerr'); if (e && course.id === ownerId) e.textContent = keptLine(k, `the ${who === 'teacher' ? 'teacher pack' : 'learner handouts'} for version ${snap.ver}`) + ' Nothing is published.'; }); },
  export(v) { const L = S.life, snap = L.snapshots.find(s => s.ver === (v ? +v : L.ver)); if (!snap) return; let pkg; try { pkg = J.buildPackage(Object.assign({}, snap, { trials: L.trials || [] })); } catch (e) { $('#lerr').textContent = e.message; return; } const text = JSON.stringify(pkg, null, 2), fname = `${fileStem(snap)}.json`; download(text, fname); const rec = { ver: snap.ver, at: new Date().toISOString() }; L.exports.push(rec); if (snap.ver === L.ver && L.stage === 'approved') L.stage = 'exported'; save('export'); paintSheet(); $('#lerr').textContent = `Download started for package v${snap.ver}. Saving a copy on this computer…`; const ownerId = course.id, ownerState = S; keepCopy(text, fname, snap.ver, 'structured').then(async k => { const stored = await settleReceipt(ownerId, ownerState, rec, k); const e = $('#lerr'); if (e && course.id === ownerId) e.textContent = (k.ok && !stored ? 'The copy was kept, but its receipt could not be written into the course record. ' : '') + keptLine(k, `package v${snap.ver}`) + ' If nothing arrived in your downloads folder, open “Show package contents” below. Nothing is published.'; }); },
  trial() { const L = S.life, snap = L.snapshots.find(s => s.ver === L.ver), d = $('#trd').value; if (!snap || !d || J.readinessOf(snap).draft) return; const at = new Date(d + 'T12:00:00'); if (at > new Date()) { $('#lerr').textContent = 'That date has not happened yet.'; return; } L.trials = (L.trials || []).concat({ ver: snap.ver, kind: $('#trk').value === 'pilot' ? 'pilot' : 'rehearsal', at: at.toISOString(), note: $('#trn').value.trim().slice(0, 200) }); save('trial'); paintSheet('[data-a="trial"]'); $('#lerr').textContent = 'Recorded.'; },
  pub() { const L = S.life, e = L.exports[L.exports.length - 1], d = $('#pubd').value; if (!d) return; L.publications.push({ ver: e.ver, at: new Date(d).toISOString() }); save('publication'); paintSheet('[data-a="pub"]'); $('#lerr').textContent = 'Publication confirmation recorded.'; },

  /* courses */
  async picker() { try { LIB = await api.library(); } catch (e) { return err(e.message); } S.renaming = null; if (!picker.open) picker.showModal(); paintPicker('#ph'); },
  closePicker() { picker.close(); },
  async courseOpen(v) { if (v === course.id && !recovery) { picker.close(); return; } if (!(await flushNow()) && !recovery && !conflict && !unsent) { $('#perr').textContent = 'The open course has changes that are not saved yet. Loom will not switch until they are.'; return; } if (picker.open) picker.close(); await openCourse(v); say('Opened ' + course.name); },
  async courseNew() { if (!recovery && !conflict && !unsent && !(await flushNow())) return err('The open course has changes that are not saved yet. Loom will not switch until they are.', '#perr'); const m = await api.create({ raw: JSON.stringify(fresh()), name: 'Untitled course', summary: {} }); if (picker.open) picker.close(); await openCourse(m.id); say('New course started. The other courses are untouched.'); },
  async courseCopy(v) { if (v === course.id && !(await flushNow())) return err('The open course has changes that are not saved yet.', '#perr'); try { const m = await api.duplicate(v); LIB = await api.library(); paintPicker(`[data-a="courseOpen"][data-v="${m.id}"]`); $('#perr').textContent = `Copied as “${m.name}”. The original is untouched.`; } catch (e) { err(e.message, '#perr'); } },
  async courseArchive(v) { const [id, on] = String(v).split('|'); if (id === course.id) return err('Open another course first. The open course cannot be archived.', '#perr'); try { await api.archive(id, on === '1'); LIB = await api.library(); paintPicker('#ph'); $('#perr').textContent = on === '1' ? 'Archived. Nothing was deleted. It is under “Archive” below.' : 'Brought back.'; } catch (e) { err(e.message, '#perr'); } },
  renameStart(v) { S.renaming = v || null; paintPicker(v ? '#rn' : '#ph'); },
  async renameSave(v) { const n = $('#rn').value.trim(); if (!n) { $('#perr').textContent = 'Type a name.'; return; } if (v === course.id) { S.name = n; course.name = n; course.named = true; save('rename'); if (!(await flushNow())) { $('#perr').textContent = 'The new name is not saved yet. Loom will keep trying.'; return; } } else await api.rename(v, n); LIB = await api.library(); S.renaming = null; paintPicker(`[data-a="renameStart"][data-v="${v}"]`); paintBrand(); },

  /* recovery */
  recDownload() { download(recovery.raw, 'glitch-loom-unreadable-course.txt', 'text/plain'); err('Download started. Look in your downloads folder.'); },
  recShow(_, el) { const p = $('#recraw'); p.hidden = !p.hidden; p.textContent = recovery.raw; el.setAttribute('aria-expanded', String(!p.hidden)); },
  async unsentUse() { const u = unsent; if (u.stale) { const m = await api.create({ raw: JSON.stringify(u.state), name: course.name + ' (changes from this browser)', named: true, summary: {} }); try { localStorage.removeItem(UNSENT()); } catch (e) { } await openCourse(m.id); return; } unsent = null; S = u.state; render('none'); save('recovered'); say('Your changes are back and are being saved.'); },
  unsentDrop() { try { localStorage.removeItem(UNSENT()); } catch (e) { } unsent = null; render('none'); say('Kept what is on disk.'); },
  async conflictReload() { try { localStorage.removeItem(UNSENT()); } catch (e) { } await openCourse(course.id); },
  async conflictFork() { const m = await api.create({ raw: JSON.stringify(S), name: courseName() + ' (from another window)', named: true, summary: summaryOf() }); try { localStorage.removeItem(UNSENT()); } catch (e) { } await openCourse(m.id); say('Saved as a separate course. The other version is untouched.'); },
  reload() { location.reload(); }
};

// No button may fail silently. If an action breaks, say so where the person is looking.
function oops(e) { console.error('Loom action failed', e); err('That did not work, and nothing was lost. Try again, or go Back. (' + e.message + ')', picker.open ? '#perr' : sheet.open ? '#lerr' : '#err'); }
function run(f, v, el) { try { const r = f(v, el); if (r && typeof r.catch === 'function') r.catch(oops); } catch (e) { oops(e); } }
// Deciding between two answers the attribution review already gave. It is handled here, outside the engine
// actions, because it asks nothing of Claude: a person who has read the document says which answer stands.
document.addEventListener('click', async e => {
  const b = e.target.closest('.decide [data-chosen]');
  if (!b) return;
  const box = b.closest('.decide');
  const because = (box.querySelector('.because') || {}).value || '';
  const why = (box.querySelector('.why') || {}).value || '';
  if (!because.trim() || !why.trim()) { say('Say which words in the document settle it, and why.'); return; }
  box.querySelectorAll('[data-chosen]').forEach(x => { x.disabled = true; });
  try {
    await api.decideAttribution(course.id, { claimKey: box.dataset.claim, disagreement: box.dataset.key,
      chosen: b.dataset.chosen, becauseWords: because, reason: why, by: 'the person at this computer' });
    say('Decision recorded. Nothing was asked of Claude.');
    await pollEngine();
  } catch (e) {
    box.querySelectorAll('[data-chosen]').forEach(x => { x.disabled = false; });
    say(e.message);
  }
});

document.addEventListener('click', e => { const el = e.target.closest('[data-a]'); if (!el || el.disabled) return; if (el.getAttribute('aria-disabled') === 'true' && !['weave', 'weaveReal'].includes(el.dataset.a)) return; const f = A[el.dataset.a]; if (f) run(f, el.dataset.v, el); });
document.addEventListener('pointerdown', () => { kbd = false; document.documentElement.removeAttribute('data-kbd'); });
document.addEventListener('keydown', e => {
  if (!kbd) { kbd = true; document.documentElement.setAttribute('data-kbd', ''); }
  const t = e.target;
  if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(e.key) && t.matches && t.matches('[role="radio"],[role="tab"]')) {
    const role = t.getAttribute('role'), g = $$(`[role="${role}"]`, t.parentElement), i = g.indexOf(t);
    const n = e.key === 'Home' ? g[0] : e.key === 'End' ? g[g.length - 1] : g[(i + (e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1) + g.length) % g.length];
    if (n && n !== t) { e.preventDefault(); const sel = `[role="${role}"][data-a="${n.dataset.a}"][data-v="${CSS.escape(n.dataset.v)}"]`; n.click(); const now = $(sel, sheet.open ? sheet : ui); if (now) now.focus({ preventScroll: true }); }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    if (t.id === 'chin') { e.preventDefault(); run(t.value.trim() ? A.addchip : goNext); }
    else if (t.id === 'tin' || t.id === 'cin') { e.preventDefault(); run(goNext); }
    else if (t.id === 'ask') { e.preventDefault(); run(A.askText); }
    else if (t.id === 'rn') { e.preventDefault(); run(A.renameSave, $('[data-a="renameSave"]').dataset.v); }
    else if (t.tagName === 'INPUT' && t.closest('.editform')) { e.preventDefault(); run(A.editSave); }
    else if ((e.metaKey || e.ctrlKey) && t.closest && t.closest('.editform')) { e.preventDefault(); run(A.editSave); }
    else if ((e.metaKey || e.ctrlKey) && F.byId(S.at)) { e.preventDefault(); run(goNext); }
  }
  if (e.key === 'Escape' && S.editing && !sheet.open && !picker.open) { e.preventDefault(); run(A.editCancel); }
});
document.addEventListener('input', e => {
  if (e.target.id === 'pf') { const q = e.target.value.trim().toLowerCase(); let n = 0; $$('#plist > li').forEach(li => { li.hidden = !!q && !String(li.dataset.find || '').includes(q); if (!li.hidden) n++; }); const none = $('#pnone'); if (none) none.hidden = n > 0; return; }
  const q = F.byId(S.at); if (!q) return;
  if (e.target.id === 'tin') { setAnswer(q, { value: e.target.value }, 'picked'); $('#detail').innerHTML = ''; err(''); }
  if (e.target.id === 'cin' && S.answers[q.id]) { S.answers[q.id].text = e.target.value; if (q.id === 'time' || q.id === 'hours') S.turn++; save(); sync(); err(''); const d = $('#detail'); if (d) d.innerHTML = detailHTML(q); }
});
document.addEventListener('change', e => {
  if (e.target.id === 'ackapprove') { ackApprove = e.target.checked; paintSheet('#ackapprove'); return; }
  if (e.target.id === 'ackoutline') { S.ackOutline = e.target.checked; save(); const b = $('[data-a="outlineApprove"]'); if (b) { if (S.ackOutline) b.removeAttribute('aria-disabled'); else b.setAttribute('aria-disabled', 'true'); } return; }
  if (e.target.id !== 'restorefile' || !e.target.files[0]) return;
  const f = e.target.files[0], rd = new FileReader();
  rd.onerror = () => { $('#perr').textContent = 'Loom could not read that file.'; };
  rd.onload = () => run(async () => { let b; try { b = JSON.parse(String(rd.result)); } catch (x) { $('#perr').textContent = 'That file is not a Loom backup.'; return; } if (!recovery && !conflict && !unsent && !(await flushNow())) { $('#perr').textContent = 'The open course has changes that are not saved yet. Loom will not switch until they are.'; return; } let m; try { m = await api.restore(b); } catch (x) { $('#perr').textContent = x.message; return; } picker.close(); await openCourse(m.id); say('Restored as a new course. Nothing was replaced.'); });
  rd.readAsText(f);
});
document.addEventListener('focusout', () => { if (repaintLater) setTimeout(() => { if (repaintLater && !typing()) softRender(); }, 50); });
sheet.addEventListener('close', () => { const sel = lifeReturn; lifeReturn = '[data-a="life"]'; if (['summary', 'checks'].includes(S.at)) { render('back', false); const t = $(sel) || $('#qt'); if (t) t.focus({ preventScroll: true }); } else softRender(sel); });
picker.addEventListener('close', () => { S.renaming = null; const b = $('#coursebtn'); if (b && !ui.contains(document.activeElement)) b.focus({ preventScroll: true }); });

/* ---------- opening ---------- */
// Work that an earlier version kept inside the browser is copied into the library once. The browser's copy is never changed.
async function importFromBrowser() {
  const key = Store.keyFor(location.search).key; let raw = null; try { raw = localStorage.getItem(key); } catch (e) { return; }
  if (!raw) return;
  const known = await api.findImport({ origin: location.origin, raw }); if (known.hash) return;
  const found = Store.inspect(raw);
  if (found.status === 'ok') {
    const st = found.state, j = st.journey, name = (F.topicsOf(st.answers).list.join(' + ') || 'Course') + ' (from this browser)';
    const m = await api.create({ raw: JSON.stringify(st), name, summary: { stage: st.life.stage, ver: st.life.ver, topics: F.topicsOf(st.answers).list, sessions: j ? j.sessions.length : 0, made: j ? (J.isReal(j) ? 'claude' : 'simulated') : '', approved: st.life.snapshots.length }, note: `Brought in from ${location.origin}` });
    await api.saveImport({ origin: location.origin, key, raw, status: 'ok', courseId: m.id });
    bootNote = 'Loom now keeps courses as files on this computer. The course saved in this browser was copied into the library. The browser’s own copy was left as it was.';
  } else if (found.status === 'damaged') {
    await api.saveImport({ origin: location.origin, key, raw, status: 'damaged', reasons: found.reasons });
    bootNote = 'Loom found saved work in this browser that it cannot read. An exact copy is now kept in the library. Open the course list to download it.';
  }
}
async function openCourse(id) {
  stopPoll(); E = null; EBusy = false; recovery = null; conflict = false; unsent = null; dirty = false;
  const c = await api.get(id); course = { id, version: c.meta.version, name: c.meta.name, named: !!c.meta.named };
  IDEAS = null; clearInterval(ideaTimer); api.ideas(id).then(r => { IDEAS = r.ideas; if (IDEAS && IDEAS.status === 'running') watchIdeas(); if (booted && S.at === 'pick' && !typing()) softRender('#qt'); }).catch(() => { });
  const found = c.raw.trim() ? Store.inspect(c.raw) : { status: 'ok', state: fresh() };
  if (found.status === 'ok') S = found.state; else { S = fresh(); recovery = { raw: c.raw, reasons: found.reasons || ['it is empty'], name: c.meta.name }; }
  lastRaw = c.raw;
  if (!recovery) { try { const u = JSON.parse(localStorage.getItem(UNSENT()) || 'null'); if (u && typeof u.raw === 'string' && u.raw !== c.raw) { const f2 = Store.inspect(u.raw); if (f2.status === 'ok' && JSON.stringify(f2.state) !== JSON.stringify(S)) unsent = { at: u.at, state: f2.state, stale: u.baseVersion !== c.meta.version }; else localStorage.removeItem(UNSENT()); } } catch (e) { } }
  const want = S.at;
  booted = true; api.setCurrent(id).catch(() => { });
  try { render('none', true); } catch (e) { console.error('Loom could not show the saved state', e); recovery = { raw: c.raw, reasons: ['it passed the checks but could not be displayed: ' + e.message], name: c.meta.name }; S = fresh(); render('none', true); }
  sync({ jump: true }); await pollEngine();
  // Come back to where the person was: the progress screen, or the outline that is waiting for them.
  if (!recovery && !unsent && E && ['generate', 'outline'].includes(want) && S.at === 'summary') { S.at = E.status === 'waiting_approval' && S.outlineDraft ? 'outline' : 'generate'; render('none', true); }
}
async function boot() {
  render('none', false);
  try { HEALTH = await api.health(); } catch (e) { fatal = e.offline ? 'server' : e.message; render('none', true); return; }
  api.engine().then(s => { ENG = s; if (booted && !typing() && !recovery && !unsent && !fatal) softRender(); }).catch(e => { ENG = { ready: false, blocker: 'Loom could not check the Claude tool: ' + e.message }; });
  try {
    await importFromBrowser();
    LIB = await api.library();
    if (!LIB.courses.length) { await api.create({ raw: JSON.stringify(fresh()), name: 'Untitled course', summary: {} }); LIB = await api.library(); }
    await openCourse(LIB.current || LIB.courses[0].id);
  } catch (e) { console.error(e); fatal = 'Loom could not open the course library: ' + e.message; render('none', true); }
}
window.__loom = { world, state: () => S, course: () => course, engine: () => E, status: () => ENG, recovery: () => recovery, flushNow, saving: () => ({ saving, dirty, storageOk, conflict }) };
boot();

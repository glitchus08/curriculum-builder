// Glitch Loom — the screens for the expanded pipeline: topic map, evidence per topic, separate reviewers, projects, files and independent time.
// Pure functions from data to HTML. Nothing here reads the page or writes state, so each can be tested on its own.
// Every screen keeps the rule of the rest of Loom: short summaries first, detail on demand, and each thing labelled for what it is.

import { standing, checkedOn } from './journey.js';
const OK = { sound: 'ok', concerns: 'warn', serious_problems: 'bad', gaps: 'warn' };
const say = v => String(v || '').replace(/_/g, ' ');
const nameOf = (m, id) => ((m && m.nodes) || []).find(n => n.id === id) ? ((m.nodes).find(n => n.id === id)).name : id;

/* ---------- what is open before an outline is approved. Nothing here can be ticked away: reading it is not fixing it. ---------- */
// A question the topic map raised before the outline existed may have been answered by the outline since. Loom
// does not judge that for the reader and does not guess from wording: it keeps every question, says plainly when
// it was asked, and lists these below the findings that are current. Nothing is removed, because an outline that
// mentions a subject is not proof that it settled it.
export function outlineOpenItems(o, E) {
  const st = E.stages, m = st.map.output, out = [], later = [], tc = o.time_conflict || {};
  const must = (((st.outline_review || {}).output || {}).findings || []).filter(f => f.severity === 'must_fix');
  for (const f of must) out.push(`The delivery reviewer still says this must be fixed (${f.area}): ${f.finding}`);
  if (tc.exists) out.push(`Time conflict: ${tc.explanation}`);
  for (const g of (m.derived || {}).openGaps || []) out.push(`Foundation gap: ${g}`);
  for (const d of o.deferred || []) out.push(`Deferred topic: ${nameOf(m, d.node)}. ${d.reason}`);
  for (const g of (m.derived || {}).unresolved || []) {
    later.push(`Asked when the topic map was made, before this outline was written: ${g} Check the outline before treating this as still open.`)
  }
  const cov = ((st.research.output || {}).nodeCoverage || []).filter(c => c.role === 'required' && !['supported', 'not_needed'].includes(c.status));
  if (cov.length) out.push(`No source fully supports: ${cov.map(c => c.name).join('; ')}.`);
  if ((st.foundation_review || {}).rejectedAdditions && st.foundation_review.rejectedAdditions.length) out.push(`The foundations reviewer asked for ${st.foundation_review.rejectedAdditions.join(', ')}, but adding it broke the map, so it was not added.`);
  if ((st.research.notResearchedNames || []).length) out.push(`Not researched, because a run researches a limited number of topics: ${st.research.notResearchedNames.join('; ')}.`);
  return out.concat(later);
}

/* ---------- the progress list ---------- */
export function genRows(E, h) {
  const st = E.stages, now = E.now, live = k => now && now.stage === k ? 'running' : null, stg = k => live(k) || (st[k] || {}).status || 'todo';
  const M = st.map && st.map.output, fr = st.foundation_review || {}, rs = st.research, bs = rs.batches || [], r = rs.output, sr = st.source_review || {}, ol = st.outline_review || {}, ps = st.projects || { units: [] };
  const units = st.materials.sessions, written = units.filter(u => u.status === 'done').length, pw = (ps.units || []).filter(u => u.status === 'done').length;
  const steps = now && now.steps ? now.steps.slice(-3).map(s => `<li>${s.did === 'opened' ? 'Opened' : 'Searched'}: ${h.esc(s.did === 'opened' ? h.host(s.what) : s.what)}</li>`).join('') : '';
  const req = M ? M.nodes.filter(n => n.role === 'required').length : 0;
  return [
    ['Topic map', stg('map'), M ? `${M.nodes.length} topics, ${req} required${(fr.addedNodes || []).length ? `, ${fr.addedNodes.length} added when the foundations were checked` : ''}` : ''],
    ['Foundations check', stg('foundation_review'), fr.output ? `A separate reviewer's verdict: ${h.esc(say(fr.output.verdict))}` : ''],
    ['Research', live('research') || rs.status, bs.length ? `${bs.filter(b => b.status === 'done').length} of ${bs.length} searches done${r ? ` · ${r.sources.length} sources, ${r.pagesOpened.length} pages opened` : ''}${live('research') ? `<ul class="bul small">${steps || '<li>Starting the search</li>'}</ul>` : ''}` : ''],
    ['Source audit', stg('source_review'), (sr.rounds || []).length ? `A separate reviewer read what each page returned: ${h.esc(say(sr.rounds[sr.rounds.length - 1].output.verdict))}` : ''],
    ['Outline', live('outline') || st.outline.status, st.outline.approved ? `Approved by you ${h.clock(st.outline.approvedAt)}` : st.outline.status === 'done' ? 'Waiting for your approval. No lesson is written before you approve.' : ''],
    ['Delivery check', stg('outline_review'), ol.output ? `A separate reviewer's verdict: ${h.esc(say(ol.output.verdict))}${ol.unresolvedMustFix ? `, ${ol.unresolvedMustFix} must-fix left` : ''}` : ''],
    ['Sessions', live('materials') || (written === units.length ? 'done' : units.some(u => u.status === 'failed') ? 'failed' : 'todo'), st.outline.approved ? `${written} of ${units.length} written, saved and checked${now && now.stage === 'materials' ? `. ${h.esc(now.label)}.` : ''}` : ''],
    ['Projects', live('project') || (!(ps.units || []).length ? 'todo' : pw === ps.units.length ? 'done' : ps.units.some(u => u.status === 'failed') ? 'failed' : 'todo'), (ps.units || []).length ? `${pw} of ${ps.units.length} written${now && now.stage === 'project' ? `. ${h.esc(now.label)}.` : ''}` : ''],
    ['Independent review', live('review') || st.review.status, st.review.status === 'done' ? `${(st.review.output.findings || []).length} findings` : '']
  ];
}

/* ---------- the outline: scope, time, projects and what the separate reviewers found ---------- */
export function outlineExtras(o, E, S, h) {
  const st = E.stages, M = st.map.output, nm = id => nameOf(M, id), cov = (st.outline.coverage || { rows: [] }).rows, acct = E.accounting || {}, tc = o.time_conflict || {};
  const fr = st.foundation_review || {}, sr = st.source_review || {}, ol = st.outline_review || {}, plan = E.plan, byId = {};
  cov.forEach(r => { byId[r.node] = r; });
  const parts = [];
  if (acct.statement) parts.push(`<p class="meta"><strong>${h.esc(acct.statement)}</strong>${E.policy ? ` <span class="dim">${h.esc(E.policy.note)}</span>` : ''}</p>`);
  if (tc.exists) parts.push(`<div class="flag" role="alert"><p><span class="tag bad">Time conflict</span> ${h.esc(tc.explanation)}</p><p class="dim">Nothing was dropped quietly to make it fit. Choose what to do:</p><ul class="conn">${(tc.options || []).map((x, i) => `<li><strong>${h.esc(x.label)}</strong> <span class="dim">${h.esc(x.effect)}</span> <button type="button" class="pill small" data-a="outlineOption" data-v="${i}">Ask for a new outline that does this</button></li>`).join('')}</ul></div>`);
  const table = M.nodes.map(n => { const r = byId[n.id] || {}; return `<li><span class="tag ${n.role === 'required' ? 'ok' : n.role === 'excluded' ? 'bad' : ''}">${h.esc(say(n.role))}</span> <strong>${h.esc(n.name)}</strong> <span class="dim">${h.esc({ requested: 'asked for', foundation: 'foundation', subtopic: 'part of a topic' }[n.kind] || n.kind)} · ${h.esc(n.depth)} · about ${n.est_minutes || 0} min${n.addedBy ? ' · added when the foundations were checked' : ''}</span><br><span class="dim">${h.esc(n.why_needed || (n.kind === 'requested' ? 'You asked for it.' : ''))}${(n.needed_by || []).length ? ' Needed by: ' + n.needed_by.map(x => x === 'OUTCOME' ? 'the outcome' : h.esc(nm(x))).join(', ') + '.' : ''}${(n.requires || []).length ? ' Needs first: ' + n.requires.map(x => h.esc(nm(x))).join(', ') + '.' : ''} ${n.role === 'required' ? (r.taughtInSession ? `Taught in ${h.esc(plan.unit.toLowerCase())} ${r.taughtInSession}${(r.usedByProjects || []).length ? `; used by ${r.usedByProjects.join(', ')}` : ''}.` : '<strong>Not taught in any session.</strong>') : ''}</span></li>`; }).join('');
  parts.push(h.more(`Topics and foundations (${M.nodes.length}) and where each is taught`, `<p class="dim">Worked out before the outline. Foundations were added because a requested topic or the outcome needs them. Learners are assumed to be able to: ${(M.assumed_entry || []).map(h.esc).join('; ') || 'not stated'}. ${M.stop_reason ? h.esc(M.stop_reason) : ''}</p><ul class="conn">${table}</ul><p class="dim">Complete for this starting level and outcome. It does not cover all there is to know about the subject.</p>`));
  // The real files the course is built on, before anyone approves it. The team should be able to see which files
  // exist, where each came from, and what was done to a teaching copy, rather than take a sentence's word for it.
  const prep = E.prepared || [];
  if (prep.length) {
    const rows = prep.map(f => {
      const pv = f.provenance || {}, log = pv.transformationLog || [];
      const head = f.kind === 'original' ? 'Original, exactly as published' : 'Teaching copy';
      return `<li><span class="tag ${f.kind === 'original' ? 'ok' : ''}">${h.esc(head)}</span> <strong>${h.esc(f.name)}</strong>
        <span class="dim">${f.bytes ? h.esc(f.bytes) + ' bytes · ' : ''}checksum ${h.esc(String(f.sha256 || '').slice(0, 12))}${f.available === false ? ' · <strong>its bytes are missing</strong>' : ''}</span>
        <br><span class="dim">${h.esc(f.purpose || '')}</span>
        ${pv.publisher ? `<br><span class="dim">From ${h.esc(pv.publisher)}${pv.serviceVersion ? ', ' + h.esc(pv.serviceVersion) : ''}${pv.retrievedAt ? ', retrieved ' + h.esc(String(pv.retrievedAt).slice(0, 10)) : ''}.</span>` : ''}
        ${pv.licenceNote ? `<br><span class="dim"><strong>Licence:</strong> ${h.esc(pv.licenceNote)}</span>` : ''}
        ${(pv.limitations || []).length ? `<br><span class="dim"><strong>Limits:</strong> ${(pv.limitations || []).map(h.esc).join(' · ')}</span>` : ''}
        ${f.measured && f.measured.readable ? `<br><span class="dim"><strong>Loom counted in this file:</strong> ${h.esc(f.measured.dataRows)} data rows, ${h.esc(f.measured.preambleLinesBeforeTheColumnNames)} lines before the column names, ${h.esc(f.measured.fillCodeMinus999Values)} fill-code values, ${h.esc(f.measured.layout)}. Columns: ${(f.measured.columnNames || []).map(h.esc).join(', ')}</span>` : ''}
        ${log.length ? `<br><span class="dim"><strong>What was changed from the original:</strong> ${log.map(h.esc).join(' ')}${pv.plantedProblems === false ? ' No problems were planted in it.' : pv.plantedProblems === true ? ' <strong>Problems were planted in it on purpose.</strong>' : ''}</span>` : ''}</li>`;
    }).join('');
    parts.push(h.more(`Files this course is built on (${prep.length})`,
      `<p class="dim">Prepared before this outline. What Loom can vouch for: an original's bytes are unchanged since it was registered, every checksum was computed by Loom from the bytes themselves, and a teaching copy names the original it came from and carries a step-by-step record of what was changed. The counts below were measured by Loom from each file. The publisher, licence and limitations are as recorded when the file was registered, and the purpose and the change log are written descriptions, not facts Loom can check.</p><ul class="conn">${rows}</ul>`));
  }
  const ps = o.projects || [];
  parts.push(ps.length ? h.more(`Projects (${ps.length})`, `<ul class="conn">${ps.map(p => `<li><span class="tag ${p.kind === 'major' ? 'ok' : ''}">${p.kind === 'major' ? 'Major project' : 'Minor project'}</span> <strong>${h.esc(p.title)}</strong><br>${h.esc(p.purpose)}<br><span class="dim">Available after ${h.esc(plan.unit.toLowerCase())} ${p.available_after_session}; worked on in ${h.esc(plan.unit.toLowerCase())}${(p.hosted_in_sessions || []).length > 1 ? 's' : ''} ${(p.hosted_in_sessions || []).join(', ')}. Needs: ${(p.nodes_required || []).map(x => h.esc(nm(x))).join(', ')}. Hand in: ${h.esc(p.deliverable)}. ${(p.minutes || {}).live || 0} min live, ${(p.minutes || {}).independent || 0} min independent.</span></li>`).join('')}</ul>`) : `<p class="note"><span class="tag">No project</span> ${h.esc(o.pathway_note || (E.policy || {}).note || 'This format is too short for a project.')}</p>`);
  if (plan.independent) parts.push(h.more(`Independent work, week by week (${plan.independent.perWeekMinutes} min each week)`, `<ul class="conn">${Array.from({ length: plan.weeks }, (_, w) => { const k = plan.meetingsPerWeek || 1, ss = o.sessions.slice(w * k, w * k + k); return `<li><strong>Week ${w + 1}</strong>: ${ss.reduce((n, s) => n + ((s.independent_work || {}).minutes || 0), 0)} min<br><span class="dim">${ss.flatMap(s => (s.independent_work || {}).tasks || []).map(h.esc).join(' · ') || 'None'}</span></li>`; }).join('')}</ul>`));
  const rv = [];
  if (fr.output) rv.push(`<li><span class="tag ${OK[fr.output.verdict] || ''}">Foundations and order</span> ${h.esc(fr.output.summary)}${(fr.addedNodes || []).length ? `<br><span class="dim">Added on its request: ${fr.addedNodes.map(h.esc).join(', ')}.</span>` : ''}${(fr.output.ordering_problems || []).length ? h.ul(fr.output.ordering_problems) : ''}${(fr.output.depth_problems || []).length ? h.ul(fr.output.depth_problems) : ''}</li>`);
  const last = (sr.rounds || [])[(sr.rounds || []).length - 1];
  if (last) rv.push(`<li><span class="tag ${OK[last.output.verdict] || ''}">Source audit</span> ${h.esc(last.output.summary)}<br><span class="dim">${last.sourcesJudged} sources judged from what each page returned, over ${sr.rounds.length} round${sr.rounds.length > 1 ? 's' : ''}${sr.rounds.some(r => (r.targetedAsked || []).length) ? '; one bounded round of extra research was made for gaps it found' : ''}.</span>${(last.output.conflicts || []).length ? h.ul(last.output.conflicts) : ''}${(last.output.node_gaps || []).length ? h.ul(last.output.node_gaps.map(g => `${nm(g.node)}: ${g.gap}`)) : ''}</li>`);
  if (ol.output) rv.push(`<li><span class="tag ${OK[ol.output.verdict] || ''}">Delivery and projects</span> ${h.esc(ol.output.summary)}${(ol.output.findings || []).length ? `<ul class="conn">${ol.output.findings.map(f => `<li><span class="tag ${f.severity === 'must_fix' ? 'bad' : f.severity === 'should_fix' ? 'warn' : ''}">${h.esc(say(f.severity))}</span> ${h.esc(f.finding)}<br><span class="dim">${h.esc(f.suggestion)}</span></li>`).join('')}</ul>` : ''}${(ol.output.project_checks || []).length ? h.ul(ol.output.project_checks.map(c => `${c.project}: ${say(c.feasible)}. ${c.why}`)) : ''}${(ol.rounds || []).some(r => r.sentBackForRevision) ? '<span class="dim">It found a problem that had to be fixed, so the outline was sent back once and rewritten.</span>' : ''}</li>`);
  if (rv.length) parts.push(h.more('What the separate reviewers said', `<p class="dim">Each is a separate request to Claude with its own role. They are AI, not independent human experts, and they did not see each other's work.</p><ul class="conn">${rv.join('')}</ul>`));
  const cv = (st.research.output || {}).nodeCoverage || [];
  if (cv.length) parts.push(h.more('What evidence each topic has', `<ul class="conn">${cv.map(c => `<li><span class="tag ${c.status === 'supported' ? 'ok' : c.status === 'not_needed' ? '' : 'warn'}">${h.esc({ supported: 'Supported', partly: 'Partly', none_found: 'None found', not_needed: 'No source needed' }[c.status] || c.status)}</span> ${h.esc(c.name)} <span class="dim">${c.sources.length ? c.sources.join(', ') : 'no source'}</span></li>`).join('')}</ul>`));
  return parts.join('');
}

/* ---------- the journey: projects ---------- */
export function projectsBlock(j, h) {
  const ps = j.projects || [];
  if (!ps.length) return j.pathwayNote ? `<p class="note"><span class="tag">No project</span> ${h.esc(j.pathwayNote)}</p>` : '';
  return `<h2 class="sec">Projects</h2><ol class="cards">${ps.map(p => `<li class="card"><p class="px">${p.outline.kind === 'major' ? 'Major project' : 'Minor project'} · after ${h.esc(j.sessions[0].unit.toLowerCase())} ${p.outline.available_after_session}${p.status === 'written' ? '' : ` · <span class="tag ${p.status === 'failed' ? 'bad' : 'warn'}">${p.status === 'failed' ? 'Needs attention' : 'Not written yet'}</span>`}</p><p class=\"k\"><strong>${h.esc((p.content || {}).title || p.outline.title)}</strong></p><p class="dim">${h.esc(p.outline.purpose)}</p><button type="button" class="pill small" data-a="openProject" data-id="${h.esc(p.id)}">Open the project</button></li>`).join('')}</ol>`;
}

const level = (checks, name) => (checks || []).find(c => c.name === name);
const LEVEL = { executed: ['ok', 'Ran without error'], syntax_only: ['', 'Read for errors only'], not_run: ['warn', 'Not run'], failed: ['bad', 'Failed'], origin_checked: ['ok', 'Checked against its source page'], origin_unverified: ['warn', 'Origin not verified'], origin_failed: ['bad', 'Values not in its source'] };
export function fileBlock(a, checks, h) {
  const c = level(checks, a.name), lv = c ? LEVEL[c.level] || ['', c.level] : null;
  return `<details class="more"><summary>${h.esc(a.name)} · ${h.esc(a.kind)}</summary><p><span class="tag ${a.provenance === 'synthetic_practice' ? 'warn' : ''}">${h.esc({ public_source: 'Extract of a public dataset', synthetic_practice: 'Made-up practice data', authored: 'Written for the course' }[a.provenance] || a.provenance || '')}</span> ${lv ? `<span class="tag ${lv[0]}">${h.esc(lv[1])}</span>` : ''}</p><p class="dim">${h.esc(a.purpose)}${a.source_id ? ' Source: ' + h.esc(a.source_id) + '.' : ''}</p>${c && c.reason ? `<p class="dim">${h.esc(c.reason)}</p>` : ''}${c && c.output ? `<p class="dim">Printed when it was run:</p><div class="handout">${h.esc(c.output.trim())}</div>` : ''}<div class="handout">${h.esc(a.content)}</div>${a.expected_output ? `<p class="dim">A correct run prints: ${h.esc(a.expected_output)}</p>` : ''}</details>`;
}

/* ---------- a session: files, independent work and project work ---------- */
export function sessionExtras(s, j, h) {
  const out = [], M = j.map;
  if ((s.teachesNodes || []).length) out.push(`<p class="dim">Teaches: ${s.teachesNodes.map(id => h.esc(nameOf(M, id))).join(', ')}.</p>`);
  if ((s.assets || []).length) out.push(h.more(`Files for this session (${s.assets.length})`, s.assets.map(a => fileBlock(a, s.assetChecks, h)).join('')));
  const iw = s.independentWork;
  if (iw && iw.minutes) out.push(h.more(`Independent work after the meeting (${iw.minutes} min, not part of the ${s.minutes} live)`, (iw.tasks || []).map(t => `<p class=\"k\"><strong>${h.esc(t.title)} <span class="dim">${t.minutes} min</span></strong></p><ol class="instr">${(t.instructions || []).map(x => `<li>${h.esc(x)}</li>`).join('')}</ol>${t.handout ? `<div class="handout">${h.esc(t.handout)}</div>` : ''}<p class="dim">Check your own work:</p>${h.ul(t.self_check || [])}<p class="dim">Hand in: ${h.esc(t.deliverable)}</p>`).join('')));
  if ((s.projectWork || []).length) out.push(h.more(`Project work in this session (${s.projectWork.length})`, `<ul class="conn">${s.projectWork.map(p => `<li><strong>${h.esc(p.project)}</strong>: ${h.esc(p.what_learners_do)}<br><span class="dim">Milestone: ${h.esc(p.milestone)}</span></li>`).join('')}</ul>`));
  return out.join('');
}

/* ---------- one project ---------- */
export function projectBody(p, j, h) {
  const c = p.content; if (!c) return '';
  const M = j.map, checks = p.assetChecks || [];
  return `<p class="lead">${h.esc(c.purpose)}</p>
    <p class="meta">${h.esc(c.time.live)} min live · ${h.esc(c.time.independent)} min independent · available after ${h.esc(j.sessions[0].unit.toLowerCase())} ${p.outline.available_after_session}</p>
    ${h.more('The brief, as learners read it', `<div class="handout">${h.esc(c.learner_brief)}</div>`, true)}
    ${h.more('You need first', (c.prerequisites || []).length ? `<ul class="conn">${c.prerequisites.map(q => `<li><strong>${h.esc(q.name || nameOf(M, q.node))}</strong> <span class="dim">taught in ${h.esc(j.sessions[0].unit.toLowerCase())} ${q.taught_in_session}</span></li>`).join('')}</ul>` : '<p class="dim">Nothing beyond what the sessions taught.</p>')}
    ${(c.inputs || []).length ? h.more(`Files learners are given (${c.inputs.length})`, c.inputs.map(a => fileBlock(a, checks, h)).join('')) : ''}
    ${h.more('Milestones', `<ol class="conn">${(c.milestones || []).map(m => `<li><strong>${h.esc(m.when)}</strong> <span class="dim">${j.sessions[0].unit.toLowerCase()} ${m.session} · ${m.minutes} min</span><br>${h.esc(m.what)}<br><span class="dim">Checked by: ${h.esc(m.check)}</span></li>`).join('')}</ol>`)}
    ${h.more('What learners hand in', h.ul(c.deliverables || []))}
    ${h.more(`Rubric (${(c.rubric || []).length} criteria)`, (c.rubric || []).map(r => `<p class=\"k\"><strong>${h.esc(r.criterion)}</strong></p><ul class="conn">${r.levels.map(l => `<li><strong>${h.esc(l.level)}</strong>: ${h.esc(l.descriptor)}</li>`).join('')}</ul>`).join(''))}
    ${h.more('Feedback and revision', `<p>${h.esc(c.feedback_route)}</p><p>${h.esc(c.revision_route)}</p>`)}
    ${h.more('For the teacher: what good work looks like', `<p>${h.esc(c.example_or_solution_guidance)}</p>${h.ul(c.teacher_guidance || [])}${(c.common_errors || []).length ? `<p class=\"k\"><strong>Learners often</strong></p><ul class="conn">${c.common_errors.map(m => `<li>“${h.esc(m.belief)}”<br><span class="dim">Respond: ${h.esc(m.response)}</span></li>`).join('')}</ul>` : ''}${(c.solution_assets || []).map(a => fileBlock(a, checks, h)).join('')}`)}
    ${(c.claims || []).length ? h.more(`Claims (${c.claims.length})`, `<ul class="conn">${c.claims.map((x, k) => `<li><span class="tag ${x.type === 'fact' && (x.sources || []).length ? 'ok' : x.type === 'fact' ? 'bad' : 'warn'}">${h.esc(x.type)}</span> ${h.esc(x.text)}<br><span class="dim">${h.esc(standing(x, j))}${(x.sources || []).length ? ' Sources: ' + x.sources.join(', ') : ''}</span>${x.type === 'fact' ? `<br><button type="button" class="quiet small" data-a="projClaimCheck" data-v="${h.esc(p.id)}|${k}" aria-pressed="${!!checkedOn(x)}">${checkedOn(x) ? 'Undo: I have not checked this claim' : 'I have checked this claim against its source'}</button>` : ''}</li>`).join('')}</ul>`) : ''}`;
}

/* ---------- the checks screen: what the map, the evidence and each reviewer show ---------- */
export function checksExtras(j, h) {
  if (j.pipeline !== 2) return '';
  const M = j.map, ag = j.agents || {}, parts = [];
  const cv = (j.research || {}).nodeCoverage || [];
  parts.push(`<h2>Scope and evidence by topic</h2><p class="dim">${h.esc((j.accounting || {}).statement || '')} The map covers what the stated learners need for the stated outcome. It is not all there is to know about the subject.</p>${h.more(`Topics and foundations (${M.nodes.length})`, `<ul class="conn">${M.nodes.map(n => { const c = cv.find(x => x.node === n.id), r = ((j.coverage || {}).rows || []).find(x => x.node === n.id) || {}; return `<li><span class="tag ${n.role === 'required' ? 'ok' : ''}">${h.esc(say(n.role))}</span> ${h.esc(n.name)} <span class="dim">${r.taughtInSession ? `session ${r.taughtInSession}` : ''}${c ? ` · evidence: ${h.esc(say(c.status))}${c.sources.length ? ' (' + c.sources.join(', ') + ')' : ''}` : ''}</span></li>`; }).join('')}</ul>`)}`);
  const rows = [];
  if (ag.foundations) rows.push(`<li><span class="tag ${OK[ag.foundations.output.verdict] || ''}">Foundations and order</span> ${h.esc(ag.foundations.output.summary)}<br><span class="dim">Read the map alone. Request ${h.esc(ag.foundations.requestId || '')}.${(ag.foundations.added || []).length ? ' Added on its request: ' + ag.foundations.added.map(h.esc).join(', ') + '.' : ''}</span></li>`);
  if (ag.sources) rows.push(`<li><span class="tag ${OK[ag.sources.output.verdict] || ''}">Source audit</span> ${h.esc(ag.sources.output.summary)}<br><span class="dim">Read what each page returned, not the writer's summary. ${ag.sources.rounds} round${ag.sources.rounds > 1 ? 's' : ''}.</span></li>`);
  if (ag.outline) rows.push(`<li><span class="tag ${OK[ag.outline.output.verdict] || ''}">Delivery and projects</span> ${h.esc(ag.outline.output.summary)}<br><span class="dim">Read the outline and its time. ${(ag.outline.output.findings || []).length} finding${(ag.outline.output.findings || []).length === 1 ? '' : 's'}${j.outlineEditedAfterReview ? '. <strong>You edited the outline after this review.</strong>' : ''}.</span></li>`);
  if (rows.length) parts.push(`<h2>Separate reviewers, before writing</h2><p class="dim">Each was a separate request with its own role. They are AI, not independent human experts.</p><ul class="conn">${rows.join('')}</ul>`);
  const files = [...j.sessions.flatMap((s, i) => (s.assetChecks || []).map(c => ({ where: `${s.unit} ${i + 1}`, ...c }))), ...(j.projects || []).flatMap(p => (p.assetChecks || []).map(c => ({ where: `Project ${p.id}`, ...c })))];
  if (files.length) parts.push(`<h2>Code that was run</h2><p class="dim">Run on this computer with no network and no writing outside a temporary folder. Passing means it finished without error. It does not mean the code teaches well.</p><ul class="conn">${files.map(c => `<li><span class="tag ${(LEVEL[c.level] || [''])[0]}">${h.esc((LEVEL[c.level] || ['', c.level])[1])}</span> ${h.esc(c.where)} · ${h.esc(c.name)}${c.reason ? `<br><span class="dim">${h.esc(c.reason)}</span>` : ''}</li>`).join('')}</ul>`);
  return parts.join('');
}


/* ---------- what a source really is: who made it, what role, what Loom itself retrieved, and whether it may be called an original ---------- */
const LEVEL_TEXT = {
  tool_summary: 'What the AI’s page reader returned is a summary made by a tool. It is not the original text.',
  direct_text: 'Loom fetched this page itself and kept its checksum. No quotation was found in it word for word.',
  direct_text_quote_found: 'Loom fetched this page itself, and the quotation is in it word for word.',
  none: 'No text of this page reached Loom.'
};
export function evidenceBlock(s, h) {
  if (s.evidenceLevel === undefined && !s.role && !s.originalSource && !s.retrievedExcerpt && s.fetch !== 'retrieved') return '';
  const d = s.directRetrieval, os = s.originalSource, lin = s.lineage || [];
  const ABOUT = { identity: 'who made it', role: 'what kind of source it is', overall: 'this source overall', lineage_supported: 'whether it supports descent' };
  const who = [s.authors && `Made by ${s.authors}`, s.published && `published ${s.published}`, s.version_or_edition && `version ${s.version_or_edition}`, s.identifier && `identifier ${s.identifier}`].filter(Boolean).join(' · ');
  return `<div class="evid"><p class="dim">${h.esc(LEVEL_TEXT[s.evidenceLevel || 'tool_summary'] || '')}${d && d.sha256 ? ` Checksum ${h.esc(d.sha256.slice(0, 12))}, fetched ${h.esc(String(d.retrievedAt || d.attemptedAt || '').slice(0, 10))} by ${h.esc(String(d.method || '').replace(/_/g, ' '))}${d.textMethod ? `, text by ${h.esc(String(d.textMethod).replace(/_/g, ' '))}` : ''}.` : d && d.note ? ' ' + h.esc(d.note) : ''}</p>
    ${who ? `<p class="dim">${h.esc(who)}. Role given: ${h.esc(String(s.role || 'not recorded').replace(/_/g, ' '))}.</p>` : s.role ? `<p class="dim">Role given: ${h.esc(String(s.role).replace(/_/g, ' '))}.</p>` : ''}
    ${s.directExcerpt ? `<p class="dim">Text Loom retrieved: “${h.esc(s.directExcerpt)}”${d && d.locator ? ` (characters ${d.locator.charStart} to ${d.locator.charEnd})` : ''}</p>` : ''}
    ${lin.length ? `<ul class="conn">${lin.map(x => `<li>${h.esc(String(x.relation || '').replace(/_/g, ' '))} — ${h.esc(x.earlier_work)}: ${h.esc(x.what_changed)}${x.limits ? ` <span class="dim">Limits: ${h.esc(x.limits)}</span>` : ''}</li>`).join('')}</ul><p class="dim">Lineage as the researcher gave it. Each link is judged by the attribution review, not by Loom.</p>` : ''}
    ${(s.attribution && s.attribution.unresolvedDisagreements || []).length ? `<p><span class="tag warn">Waiting on a person</span> <span class="dim">Two runs of the attribution review answered the same question differently on the same evidence. Nothing resting on it is settled until someone decides. Deciding asks nothing of Claude.</span></p>
      ${(s.attribution.unresolvedDisagreements || []).map(x => `<div class="decide" data-claim="${h.esc(s.claimKey || '')}" data-key="${h.esc(x.key || '')}" data-revision="${h.esc(x.revision || '')}" data-evidence="${h.esc((s.attribution || {}).fingerprint || '')}" data-replacing="${h.esc(x.replacing || '')}">
        <p>${h.esc(ABOUT[x.aspect] || 'This relationship')}: the review said <strong>${h.esc(String(x.earlier))}</strong> earlier and <strong>${h.esc(String(x.later))}</strong> now.</p>
        <p class="dim">Which answer stands? Quote the words in the document that settle it.</p>
        <p>${['yes', 'partly', 'no', 'cannot_tell'].map(c => `<button type="button" class="pill" data-chosen="${c}">${h.esc(c.replace('_', ' '))}</button>`).join(' ')}</p>
        <p><label>Words in the document <input class="because" type="text" placeholder="the sentence that settles it"></label></p>
        <p><label>Why <input class="why" type="text" placeholder="what you checked"></label></p>
      </div>`).join('')}` : ''}
    ${(s.attribution && s.attribution.decidedByAPerson || []).map(x => `<p><span class="tag ok">Decided by a person</span> <span class="dim">${h.esc(ABOUT[x.about] || 'This relationship')}: ${h.esc(String(x.chosen))}, decided by ${h.esc(String(x.by))} on ${h.esc(String(x.at).slice(0, 10))}. ${h.esc(String(x.reason || ''))} Claude had said ${h.esc(String(x.theModelHadSaid && x.theModelHadSaid.later))}.</span></p>`).join('')}
    ${os ? `<p><span class="tag ${os.status === 'verified' ? 'ok' : 'warn'}">${os.status === 'verified' ? 'Original source verified' : 'Not verified as an original source'}</span> ${os.because && os.because.length ? `<span class="dim">${os.because.map(h.esc).join('; ')}.</span>` : ''}</p>` : ''}</div>`;
}

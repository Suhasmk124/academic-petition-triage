'use strict';
const $ = id => document.getElementById(id);
const samples = {
  attendance: 'My attendance is 72% following a medical absence. What are the condonation requirements and supporting records for human review?',
  medical: 'I missed the terminal examination due to illness. What is the medical leave application deadline and what happens next?',
  grade: 'I received an X grade after missing the final examination for medical reasons. What are the retest deadlines and summer term restrictions?'
};
let activeRun = null, generation = 0, privateRecords = false, roleAccounts = false, roleDemo = false, identity = null;
let loginPromise = null, finishLogin = null, failLogin = null;
function ensureLogin() {
  if (!loginPromise) {
    loginPromise = new Promise((resolve,reject)=>{ finishLogin=resolve; failLogin=reject; });
    $('login-dialog').showModal(); $('access-key').focus();
  }
  return loginPromise;
}
$('login-dialog').addEventListener('cancel',()=>{ failLogin?.(new Error('Sign-in was cancelled.')); loginPromise=null; });
$('login-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('login-error').textContent='';
  try {
    const username = roleDemo ? $('demo-account').value : $('account-user').value.trim() || 'admin';
    await request('/auth/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:$('access-key').value, username})});
    $('access-key').value=''; $('login-dialog').close(); finishLogin?.(); loginPromise=null;
    if (roleAccounts) refreshWorkspace().catch(()=>{});
  } catch (error) { $('login-error').textContent=error.message; }
});
function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}
async function request(path, options = {}, reauthenticate = true) {
  const response = await fetch(path, {...options, signal: AbortSignal.timeout(15000)});
  if (response.status===401 && path!=='/auth/session' && reauthenticate) {
    await ensureLogin(); return request(path,options,false);
  }
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) {
    const message = data.error === 'QUEUE_FULL' ? 'The queue is full. Please try again shortly.'
      : data.error === 'INVALID_REQUEST' ? `Please check your petition. No workflow was started. Reference: ${data.quarantine_id}`
      : data.error === 'CONTENT_REQUIRES_REVIEW' ? `Please rephrase without system instructions or abusive language. Reference: ${data.quarantine_id}`
      : typeof data.detail === 'string' ? data.detail
      : response.status === 409 ? 'Please wait until the run finishes before leaving feedback.'
      : response.status === 429 ? 'This workspace is receiving too many requests. Please wait a minute and retry.'
      : response.status === 401 ? (roleAccounts ? 'Check your username and password.' : 'Check your workspace access key.')
      : response.status === 404 ? 'This run could not be found. Please submit a new petition.'
      : 'The service could not complete this request. Please try again.';
    throw new Error(message);
  }
  return data;
}
function count() { $('count').textContent = `${$('petition').value.length.toLocaleString()} / 4,000`; $('form-error').hidden = true; }
$('petition').addEventListener('input', count);
document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', () => {
  $('petition').value = samples[button.dataset.sample]; count(); $('petition').focus();
}));
async function health() {
  try {
    const state = await request('/health');
    $('connection').textContent = state.active_workers ? 'Worker connected' : 'Waiting for worker';
    $('connection').classList.toggle('online', state.active_workers > 0);
    $('mode').textContent = state.mode === 'hosted' ? 'LIVE HOSTED AGENTS' : state.mode === 'stub' ? 'SIMULATED MODEL · NO API CHARGES' : 'LOCAL EXTRACTIVE MODE';
    privateRecords = state.private_records === true;
    roleDemo = state.role_demo === true;
    if (state.role_accounts && !roleAccounts) {
      roleAccounts = true;
      $('account-login').hidden = roleDemo;
      $('demo-account-login').hidden = !roleDemo;
      $('access-label').textContent = roleDemo ? 'Password' : 'Password (administrator: workspace key)';
      $('login-hint').textContent = roleDemo ? 'Choose a role. The demo password is pass@1234.' : 'Enter your username and password.';
      $('workspace-button').hidden = false;
      refreshWorkspace().catch(()=>{});
    }
    $('supporting-file-field').hidden = !privateRecords;
    const fictionalOnly = !privateRecords || roleDemo;
    $('synthetic-label').hidden = !fictionalOnly;
    $('synthetic').required = fictionalOnly;
    $('facts-label').textContent = fictionalOnly ? 'Optional fictional facts for a conditional position' : 'Optional facts for a conditional position';
    $('record-kind').textContent = fictionalOnly ? 'Fictional scenarios only' : 'Private local workspace';
    $('workspace-notice').textContent = fictionalOnly ? 'Use fictional examples and attachments only.' : 'The hosted model receives only a standard handbook question selected by category. Petition text and documents stay in this workspace.';
  } catch (_) { $('connection').textContent = 'Service unavailable'; $('connection').classList.remove('online'); }
}
const initialHealth = health(); setInterval(health, 15000);
$('workspace-button').addEventListener('click', async () => {
  try { await ensureLogin(); await refreshWorkspace(); }
  catch (_) { /* The login dialog shows errors. */ }
});
$('logout-button').addEventListener('click', async () => {
  await request('/auth/logout',{method:'POST'},false).catch(()=>{});
  location.replace('/');
});
$('refresh-cases').addEventListener('click', () => refreshWorkspace().catch(error=>{$('case-list').textContent=error.message;}));
async function refreshWorkspace() {
  try { identity = await request('/workspace/me', {}, false); }
  catch (_) { return; }
  $('role-panel').hidden = false;
  $('workspace-button').hidden = true;
  $('logout-button').hidden = false;
  $('role-label').textContent = `Signed in as ${identity.username} · ${identity.role}`;
  $('cases-title').textContent = identity.role==='student' ? 'My petitions' : 'Officer review queue';
  $('create-account').hidden = roleDemo || identity.role!=='admin';
  $('new-petition').hidden = identity.role==='reviewer';
  $('new-petition').parentElement.classList.toggle('review-only',identity.role==='reviewer');
  const cases = await request('/workspace/cases');
  const list = $('case-list'); list.replaceChildren();
  if (!cases.length) list.append(element('p','No cases yet.','field-hint'));
  for (const item of cases) {
    const button = element('button',`Open ${item.run_id.slice(0,8)} · ${item.outcome ? 'Reviewed' : item.status==='SUCCEEDED' ? 'Awaiting officer review' : item.status}`);
    button.type='button';
    button.addEventListener('click',()=>reopen(item.run_id).catch(error=>{ $('role-label').textContent=error.message; }));
    list.append(button);
  }
}
$('create-account').addEventListener('submit',async event=>{
  event.preventDefault();
  try {
    await request('/workspace/accounts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      username:$('new-username').value.trim().toLowerCase(),password:$('new-password').value,role:$('new-role').value})});
    event.target.reset(); $('account-message').textContent='Account created. Share the credentials privately.';
  } catch (error) { $('account-message').textContent=error.message; }
});
const clauseSummaries = {
  '8.1(i)': 'The normal attendance minimum is 80%. Below it, the handbook restricts mid-term or terminal exam eligibility at the relevant attendance checkpoint. The Dean can condone a shortage in exceptional circumstances.',
  '8.1(ii)': 'Medical condonation can cover the days of medical leave. The handbook calls for a certificate issued by the IISc Health Centre’s Chief Medical Officer.',
  '8.1(iii)': 'Apply for medical leave on SLCM within seven days of recovery and upload the Health Centre certificate on SAP.',
  '5.6(i)': 'If illness caused you to miss a terminal exam, a CMO-certified absence may be condoned and a substitute exam may be permitted. The handbook specifies the SLCM application and SAP upload steps.',
  '5.7(C)(1)': 'An X grade may be available after a final exam missed for medical reasons with a CMO-attested certificate. Without certification, the rule specifies an F grade.',
  '5.7(C)(2)': 'The instructor uploads the supporting record to SAP and provides written justification for the X grade.',
  '5.7(C)(3)': 'The normal retest and grade-update window is 15 days from results; the clause gives a June 30 outer deadline in unavoidable circumstances for August and January term courses.',
  '5.7(C)(4)': 'Courses registered during the summer term are excluded from X grades.',
  '5.7(C)(5)': 'A timely retest replaces the X with the grade earned. Otherwise it lapses to F unless additional certified medical justification is provided.'
};
function renderAnswer(root, result, run, findings) {
  const answer=element('section',undefined,'answer-card');
  answer.append(element('h3','What this means for your petition'));
  const attendance=run.attendance_percent ?? result.entities?.stated_attendance_percent;
  if (findings.some(f=>f.citation?.clause_id==='8.1(i)') && typeof attendance==='number') {
    answer.append(element('p',`You reported ${attendance}% attendance. That is ${attendance<80?'below':'at or above'} the normal 80% threshold. The officer still needs to verify the attendance record and any applicable exception.`));
  } else if (findings.length) {
    answer.append(element('p','Here are the rules that apply to this type of petition and what the officer needs to check.'));
  } else {
    answer.append(element('p','I couldn’t establish a supported handbook answer. An officer needs to review this case.'));
  }
  for (const [i,finding] of findings.entries()) {
    const clause=finding.citation?.clause_id;
    const row=element('p',clauseSummaries[clause] || 'This clause is relevant to the review.');
    const link=element('a',`§ ${clause || 'Source'}`,'source-link');
    link.href=`#source-clause-${i}`;
    link.addEventListener('click',()=>{ const target=$(`source-clause-${i}`); if (target) target.open=true; });
    row.append(document.createTextNode(' '),link); answer.append(row);
  }
  answer.append(element('p',result.provider_response_used ? 'Plain-language summary of the evidence selected and checked by the hosted agents. An officer makes the decision.' : 'Plain-language summary of the locally checked evidence. An officer makes the decision.','field-hint'));
  root.append(answer);
}

function renderOfficerReview(root, run) {
  if (!roleAccounts) return;
  const panel=element('section',undefined,'finding');
  panel.append(element('h3','Human officer review'));
  const current=run.officer_review;
  const labels={needs_information:'More information requested',recommend_exception:'Exception recommended',recommend_standard_rule:'Standard rule recommended'};
  panel.append(element('p',current ? `${labels[current.outcome]} · ${current.reviewer}` : 'Awaiting a human reviewer. No officer recommendation has been recorded.'));
  if (current) panel.append(element('blockquote',current.note));
  if (identity && identity.role!=='student' && ['SUCCEEDED','FAILED'].includes(run.status)) {
    const form=element('form');
    const outcome=element('select'); outcome.setAttribute('aria-label','Reviewer outcome');
    for (const [value,label] of Object.entries(labels)) { const option=element('option',label); option.value=value; outcome.append(option); }
    const note=element('textarea'); note.required=true; note.maxLength=1200; note.setAttribute('aria-label','Reviewer note'); note.placeholder='Explain the recommendation or what information is missing.';
    const save=element('button','Record officer recommendation'); save.type='submit';
    const message=element('p','','field-hint'); message.setAttribute('role','status');
    form.append(outcome,note,save,message);
    form.addEventListener('submit',async event=>{
      event.preventDefault(); save.disabled=true;
      try {
        const review=await request(`/runs/${run.run_id}/officer-review`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({outcome:outcome.value,note:note.value})});
        const next=element('div'); renderOfficerReview(next,{...run,officer_review:review}); panel.replaceWith(...next.children);
        refreshWorkspace().catch(()=>{});
      } catch (error) { message.textContent=error.message; save.disabled=false; }
    });
    panel.append(form);
  }
  root.append(panel);
}

function renderResult(result, run) {
  const root = $('result'); root.replaceChildren();
  const brief = result.draft || result.assessment || {};
  const findings = brief.claims || brief.findings || [];
  renderAnswer(root,result,run,findings);
  renderOfficerReview(root,run);
  const escalation = result.status === 'ESCALATE';
  const outcome = element('div', undefined, 'outcome');
  outcome.append(element('h3', escalation ? 'Officer review needed' : 'Ready for academic officer review'));
  outcome.append(element('p', escalation ? 'This workflow could not establish a complete supported brief. An officer needs to identify the applicable provisions.' : 'Refer to the academic officer or committee. These provisions are supporting context; no final decision has been made.'));
  root.append(outcome);
  if (result.position) {
    const position = element('div',undefined,'outcome');
    position.append(element('h3',result.position.recommendation==='GRANT_UNDER_PROVISION'?'Provision appears to permit processing':result.position.recommendation==='REJECT_UNDER_PROVISION'?'Provision appears to restrict this request':'Local recommendation: refer for officer review'));
    result.position.reasons.forEach(reason=>position.append(element('p',reason)));
    position.append(element('p','Local rule check · facts unverified · officer decision required.')); root.append(position);
  }
  root.append(element('p', result.mode === 'STUB' ? 'Simulated model · real source checks · no hosted model requests. Semantic interpretation has not been validated.' : result.provider_response_used ? 'Live model response used. Citation checks passed locally.' : result.reliability?.reason === 'HOSTED_MODEL_UNAVAILABLE' ? 'The hosted run did not complete. This brief uses local fallback.' : 'Extractive source checks only. Source matches do not establish eligibility.', 'field-hint'));
  const failure = result.reliability?.hosted_failure;
  if (failure) {
    const stage = failure.role ? failure.role[0].toUpperCase() + failure.role.slice(1) : 'Hosted workflow';
    const status = failure.http_status ? ` (HTTP ${failure.http_status})` : '';
    root.append(element('p', `${stage}: ${failure.message}${status}`, 'error'));
  }
  if (result.hosted_review?.length) {
    const review = element('section', undefined, 'finding');
    review.append(element('h3', 'Live agent results'));
    review.append(element('p', 'The investigator selected the clauses. The source auditor reviewed the evidence packet.', 'field-hint'));
    const verdicts = element('ul', undefined, 'checklist');
    for (const verdict of result.hosted_review) {
      verdicts.append(element('li', `§ ${verdict.clause_id} · ${verdict.verifier_supported ? 'Verifier supported this quotation' : 'Verifier did not support this quotation'}`));
    }
    review.append(verdicts);
    root.append(review);
  }
  const activity=element('details',undefined,'finding');
  activity.open = true;
  activity.append(element('summary','Agent activity'));
  const steps=element('ol',undefined,'checklist');
  const toolLabels={search_regulations:'searched the handbook',fetch_exact_clause:'fetched an exact clause',verify_claim_quotes:'checked selected quotations'};
  const audits = result.agent_handoff || [];
  for (const [index, metric] of (result.metrics || []).entries()) {
    const audit = audits[Math.floor(index / 2)];
    const tools = (metric.tools_used || []).map(tool => toolLabels[tool] || tool).join(', ');
    const investigator = metric.agent === 'investigator';
    const item = element('li');
    const name = investigator ? 'Investigator' : 'Source auditor';
    item.append(element('strong', audits.length > 1 ? `Pass ${Math.floor(index / 2) + 1} · ${name}` : name));
    let output = metric.success ? 'Completed' : 'Did not complete';
    if (audit && investigator) output = `Selected ${audit.selected} handbook clauses and sent them for audit.`;
    if (audit && !investigator) {
      const decision = {RETRY: 'Returned to the investigator', ESCALATE: 'Referred unresolved packet to the officer', REVIEW_REQUIRED: 'Cleared for officer review'}[audit.outcome];
      output = `${decision}. ${audit.checked} of ${audit.selected} quotations source-matched. ${audit.rejected} flagged.`;
      if (audit.missing.length) output += ` Missing provisions ${audit.missing.map(clause => `§ ${clause}`).join(', ')}.`;
    }
    item.append(element('p', output), element('p', `${tools || 'No source tool recorded'} · ${metric.latency_seconds.toFixed(2)} s`, 'field-hint'));
    steps.append(item);
  }
  steps.append(element('li',result.safety?.output==='passed' ? 'Local source gate: passed' : 'Local source gate: no verified brief recorded'));
  steps.append(element('li',run.officer_review ? 'Human officer: recommendation recorded' : 'Human officer: no recommendation recorded'));
  activity.append(steps); root.append(activity);
  if (findings.length) root.append(element('h3', `APPLICABLE PROVISIONS · ${findings.length}`, 'result-kicker'));
  for (const [index,finding] of findings.entries()) {
    const cite = finding.citation || {};
    const card = element('details', undefined, 'finding');
    card.id = `source-clause-${index}`;
    const heading = element('summary', undefined, 'citation');
    heading.append(element('strong', `§ ${cite.clause_id || 'Source provision'}`));
    heading.append(element('span', `PDF p. ${cite.pdf_page}${cite.printed_page_verified ? ` · printed p. ${cite.printed_page}` : ''}`));
    heading.append(element('span', 'Source matched', 'verified'));
    card.append(heading, element('blockquote', finding.supporting_quote || cite.exact_quote || finding.statement));
    const detail = element('details'); detail.append(element('summary', 'Citation & source details'));
    detail.append(element('p', `${cite.title || cite.source} · ${cite.version || '2025–26'} · ${cite.locator_label || cite.clause_id}`));
    if (cite.locator_kind?.startsWith('generated')) detail.append(element('p', 'Generated bullet locator for navigation; this numbering is not printed in the handbook.'));
    if (cite.source_note) detail.append(element('p', cite.source_note));
    const sourceLink = element('a', `Open handbook · PDF page ${cite.pdf_page}`, 'source-link');
    sourceLink.href = `/handbook#page=${Number(cite.pdf_page)}`; sourceLink.target = '_blank'; sourceLink.rel = 'noopener';
    detail.append(sourceLink);
    detail.append(element('p', `Evidence reference: ${cite.evidence_id || finding.evidence_id}`));
    card.append(detail); root.append(card);
  }
  if (brief.missing_evidence?.length) {
    root.append(element('h3', 'BEFORE A FINAL DECISION', 'result-kicker'));
    const list = element('ul', undefined, 'checklist');
    brief.missing_evidence.forEach(item => list.append(element('li', item))); root.append(list);
  }
  if (result.safety?.output === 'blocked') root.append(element('p', 'The final source or safety check failed. The proposed output was withheld for officer review.', 'error'));
  const downloads=element('p',undefined,'field-hint');
  for (const [format,label] of [['html','Download printable officer brief'],['json','Download audit JSON']]) {
    const link=element('a',label,'source-link');
    link.href=`/runs/${activeRun}/export?format=${format}`; link.download='';
    downloads.append(link,document.createTextNode('  '));
  }
  root.append(downloads);
  renderPrivateEvidence(root, run);
  renderFeedback(root, activeRun);
  const transparency=element('details',undefined,'transparency'); transparency.open=true; transparency.append(element('summary','Run transparency'));
  const inputTokens=(result.usage||[]).reduce((sum,item)=>sum+(item.input_tokens||0),0);
  const outputTokens=(result.usage||[]).reduce((sum,item)=>sum+(item.output_tokens||0),0);
  transparency.append(element('p',`Cache: ${result.cache?.hit?'reused a source-checked brief':'fresh workflow'}. Input/output tokens: ${inputTokens}/${outputTokens}${(result.usage||[]).some(item=>item.estimated)?' (estimates)':''}.`));
  if (result.provider_request_attempts !== undefined) transparency.append(element('p', `Hosted request attempts: ${result.provider_request_attempts}`));
  transparency.append(element('p',`Trace reference: ${result.trace_id||'unavailable for this older run'}`));
  for (const metric of result.metrics||[]) transparency.append(element('p',`${metric.agent}: ${metric.model_calls} model steps, ${metric.tool_calls} tools, ${metric.latency_seconds.toFixed(2)} seconds · ${metric.prompt_version} · ${metric.success?'completed':'did not complete'}`));
  root.append(transparency);
}

function renderPrivateEvidence(root, run) {
  if (run.private_petition) {
    const details = element('details', undefined, 'finding');
    details.append(element('summary','Original petition (local)'), element('blockquote',run.private_petition));
    root.append(details);
  }
  if (run.attachment_available) {
    const id = activeRun;
    const attachment = element('section', undefined, 'finding');
    attachment.append(element('h3','Supporting document'));
    attachment.append(element('p','Received for officer review. The system has not verified it.', 'field-hint'));
    const link = element('a','Download supporting document','source-link');
    link.href = `/runs/${id}/attachment`; link.download = '';
    const remove = element('button','Remove attachment');
    remove.type = 'button';
    const message = element('p','','field-hint'); message.setAttribute('role','status');
    remove.addEventListener('click', async () => {
      if (!confirm('Remove the supporting document from this run?')) return;
      remove.disabled = true;
      try {
        await request(`/runs/${id}/attachment`, {method:'DELETE'});
        attachment.replaceChildren(element('p','Supporting document removed.'));
      } catch (error) { message.textContent = error.message; remove.disabled = false; }
    });
    attachment.append(link, remove, message); root.append(attachment);
  }
}

function renderFeedback(root, runId) {
  const form = element('form', undefined, 'feedback');
  form.append(element('h3', 'HELP IMPROVE THE REVIEW', 'result-kicker'));
  const label = element('label', 'Was this brief useful?'); label.htmlFor = 'feedback-rating';
  const rating = element('select'); rating.id = 'feedback-rating';
  for (const [value, text] of [['helpful', 'Helpful'], ['needs_review', 'Needs another look']]) {
    const option = element('option', text); option.value = value; rating.append(option);
  }
  const categoryLabel = element('label', 'What should we review?'); categoryLabel.htmlFor = 'feedback-category';
  const category = element('select'); category.id = 'feedback-category';
  for (const [value, text] of [['none','No issue'],['missing_rule','Missing provision'],['incorrect_citation','Citation issue'],['unclear','Unclear explanation'],['other','Other']]) {
    const option = element('option', text); option.value = value; category.append(option);
  }
  const commentLabel = element('label', 'Optional note · fictional details only'); commentLabel.htmlFor = 'feedback-comment';
  const comment = element('textarea'); comment.id = 'feedback-comment'; comment.maxLength = 500; comment.rows = 3;
  const declaration = element('label', undefined, 'consent');
  const synthetic = element('input'); synthetic.type = 'checkbox'; synthetic.required = true;
  declaration.append(synthetic, element('span', 'My feedback contains no real student records or personal information.'));
  const save = element('button', 'Save feedback'); save.type = 'submit';
  const message = element('p', '', 'field-hint'); message.setAttribute('role', 'status');
  form.append(label, rating, categoryLabel, category, commentLabel, comment, declaration, save, message); root.append(form);
  const fields = [rating, category, comment, synthetic]; fields.forEach(field => { field.disabled = true; }); save.disabled = true;
  request(`/runs/${runId}/feedback`).then(data => {
    if (data.feedback) { rating.value = data.feedback.rating; category.value = data.feedback.category; comment.value = data.feedback.comment; message.textContent = 'Your saved feedback is shown. Saving again updates this run’s feedback.'; }
  }).catch(() => { message.textContent = 'Existing feedback could not be loaded. You can retry by reopening the run.'; })
    .finally(() => { fields.forEach(field => { field.disabled = false; }); save.disabled = false; });
  form.addEventListener('submit', async event => {
    event.preventDefault(); save.disabled = true;
    try {
      await request(`/runs/${runId}/feedback`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({rating:rating.value, category:category.value, comment:comment.value, synthetic:synthetic.checked})});
      message.textContent = 'Feedback saved. It helps select cases for review; it does not change this recommendation.';
    } catch (error) { message.textContent = error.message; }
    finally { save.disabled = false; }
  });
}

function showRun(id) {
  activeRun = id; $('empty').hidden = true; $('run').hidden = false; $('result').replaceChildren();
  $('run-id').textContent = `Run ${id}`; $('reopen-id').value = id;
  history.replaceState(null, '', `?run=${encodeURIComponent(id)}#review`);
  $('run-status').textContent = 'Loading your review brief…';
  $('run-status').tabIndex = -1; $('run-status').focus();
}
async function reopen(id) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) throw new Error('Please enter a complete run ID.');
  id = id.toLowerCase(); await request(`/runs/${id}`);
  if (roleAccounts) await refreshWorkspace();
  const token = ++generation;
  showRun(id); $('submit').disabled = true; await poll(id, token);
}
$('reopen-form').addEventListener('submit', async event => {
  event.preventDefault(); $('reopen-error').hidden = true;
  try { await reopen($('reopen-id').value.trim()); }
  catch (error) { $('reopen-error').textContent = error.message; $('reopen-error').hidden = false; }
});
async function poll(id, token) {
  $('resume').hidden = true;
  const started = Date.now(); let errors = 0;
  while (token === generation) {
    try {
      const run = await request(`/runs/${encodeURIComponent(id)}`);
      if (token !== generation) return;
      errors = 0;
      const index = ['QUEUED', 'RUNNING', 'SUCCEEDED'].indexOf(run.status);
      document.querySelectorAll('[data-stage]').forEach((node, i) => node.classList.toggle('done', i <= index));
      $('run-status').textContent = run.status === 'QUEUED' ? 'Your petition is queued. A background worker will pick it up.' : run.status === 'RUNNING' ? 'Finding provisions and checking their source quotations…' : run.status === 'SUCCEEDED' ? 'Source checks completed. Your brief is ready below.' : 'Processing stopped. Please try a new submission or ask the project operator to check the worker.';
      if (run.status === 'SUCCEEDED') { renderResult(run.result || {}, run); $('submit').disabled = false; return; }
      if (run.status === 'FAILED') { $('result').replaceChildren(); renderPrivateEvidence($('result'), run); renderOfficerReview($('result'),run); $('submit').disabled = false; return; }
    } catch (error) {
      if (token !== generation) return;
      $('run-status').textContent = `${error.message} Your accepted run is preserved.`;
      if (++errors >= 3) break;
    }
    if (Date.now() - started > 120000) {
      $('run-status').textContent = 'This run is taking longer than expected. You can check again; it remains in the queue.'; break;
    }
    await new Promise(resolve => setTimeout(resolve, Math.min(1000 * (errors + 1), 4000)));
  }
  if (token === generation) { $('resume').hidden = false; $('submit').disabled = false; }
}
$('resume').addEventListener('click', () => { if (activeRun) { $('submit').disabled = true; poll(activeRun, ++generation); } });
$('petition-form').addEventListener('submit', async event => {
  event.preventDefault(); $('form-error').hidden = true;
  if (!$('petition').value.trim()) { $('form-error').textContent = 'Please enter petition details.'; $('form-error').hidden = false; return; }
  $('submit').disabled = true;
  try {
    const facts={};
    if ($('attendance-percent').value!=='') facts.attendance_percent=Number($('attendance-percent').value);
    for (const [field,id] of [['medical_absence','medical-absence'],['exception_requested','exception-requested'],['summer_term','summer-term']]) if ($(id).value!=='') facts[field]=$(id).value==='true';
    const payload = {petition: $('petition').value, facts};
    if (privateRecords) {
      const file = $('supporting-file').files[0];
      if (file) {
        if (!file.size || file.size > 5 * 1024 * 1024) throw new Error('Choose a non-empty file up to 5 MiB.');
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error('The selected file could not be read.'));
          reader.readAsDataURL(file);
        });
        payload.attachment = {content: dataUrl.split(',')[1]};
      }
    }
    if (!privateRecords || roleDemo) payload.synthetic = $('synthetic').checked;
    const run = await request(privateRecords ? '/petitions/private' : '/petitions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    $('supporting-file').value = '';
    showRun(run.run_id);
    if (roleAccounts) refreshWorkspace().catch(()=>{});
    await poll(activeRun, ++generation);
  } catch (error) { $('form-error').textContent = error.message; $('form-error').hidden = false; $('submit').disabled = false; }
});
const bookmarkedRun = new URLSearchParams(location.search).get('run');
if (bookmarkedRun) initialHealth.then(()=>reopen(bookmarkedRun)).catch(error => { $('reopen-error').textContent = error.message; $('reopen-error').hidden = false; });

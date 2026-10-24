'use strict';
const $ = id => document.getElementById(id);
const samples = {
  attendance: 'My attendance is 72% following a medical absence. What are the condonation requirements and supporting records for human review?',
  medical: 'I missed the terminal examination due to illness. What is the medical leave application deadline and what happens next?',
  grade: 'I received an X grade after missing the final examination for medical reasons. What are the retest deadlines and summer term restrictions?'
};
let activeRun = null, generation = 0;
function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}
async function request(path, options = {}) {
  const response = await fetch(path, {...options, signal: AbortSignal.timeout(15000)});
  const data = await response.json();
  if (!response.ok) {
    const message = data.error === 'QUEUE_FULL' ? 'The queue is full. Please try again shortly.'
      : data.error === 'INVALID_REQUEST' ? `Please check your petition. No workflow was started. Reference: ${data.quarantine_id}`
      : data.error === 'CONTENT_REQUIRES_REVIEW' ? `Please rephrase without system instructions or abusive language. Reference: ${data.quarantine_id}`
      : response.status === 409 ? 'Please wait until the run finishes before leaving feedback.'
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
    $('mode').textContent = state.mode === 'stub' ? 'SIMULATED MODEL · NO API CHARGES' : 'LOCAL EXTRACTIVE MODE';
  } catch (_) { $('connection').textContent = 'Service unavailable'; $('connection').classList.remove('online'); }
}
health(); setInterval(health, 15000);
function renderResult(result) {
  const root = $('result'); root.replaceChildren();
  const brief = result.draft || result.assessment || {};
  const findings = brief.claims || brief.findings || [];
  const escalation = result.status === 'ESCALATE';
  const outcome = element('div', undefined, 'outcome');
  outcome.append(element('h3', escalation ? 'Officer review needed' : 'Ready for academic officer review'));
  outcome.append(element('p', escalation ? 'This workflow could not establish a complete supported brief. An officer needs to identify the applicable provisions.' : 'Refer to the academic officer or committee. These provisions are supporting context; no final decision has been made.'));
  root.append(outcome);
  root.append(element('p', result.mode === 'STUB' ? 'Simulated model · real source checks · no hosted model requests. Semantic interpretation has not been validated.' : 'Extractive source checks only. Source matches do not establish eligibility.', 'field-hint'));
  if (findings.length) root.append(element('h3', `APPLICABLE PROVISIONS · ${findings.length}`, 'result-kicker'));
  for (const finding of findings) {
    const cite = finding.citation || {};
    const card = element('article', undefined, 'finding');
    const heading = element('div', undefined, 'citation');
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
  renderFeedback(root, activeRun);
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
      if (run.status === 'SUCCEEDED') { renderResult(run.result || {}); $('submit').disabled = false; return; }
      if (run.status === 'FAILED') { $('submit').disabled = false; return; }
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
    const run = await request('/petitions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({petition: $('petition').value, synthetic: $('synthetic').checked})});
    showRun(run.run_id);
    await poll(activeRun, ++generation);
  } catch (error) { $('form-error').textContent = error.message; $('form-error').hidden = false; $('submit').disabled = false; }
});
const bookmarkedRun = new URLSearchParams(location.search).get('run');
if (bookmarkedRun) reopen(bookmarkedRun).catch(error => { $('reopen-error').textContent = error.message; $('reopen-error').hidden = false; });

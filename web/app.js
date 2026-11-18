const state = { authenticated: false, projects: [], selectedProject: null, files: [], currentReviewId: null, reviewPage: 1, reviewTotal: 0 };
const $ = (id) => document.getElementById(id);

function api(path, options = {}) {
  const csrf = document.cookie.split('; ').find((item) => item.startsWith('forge_csrf_token='))?.split('=')[1];
  const headers = { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}), ...(options.headers || {}) };
  return fetch(path, { ...options, headers, credentials: 'include' });
}

function uploadApi(path, formData) {
  const headers = {};
  return fetch(path, { method: 'POST', headers, body: formData, credentials: 'include' });
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').style.display = 'block';
  setTimeout(() => { $('toast').style.display = 'none'; }, 2800);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

function renderAuth() {
  $('auth-panel').classList.toggle('hidden', state.authenticated);
  $('workspace').classList.toggle('hidden', !state.authenticated);
  $('account-area').innerHTML = state.authenticated ? '<button class="text-button" id="account-button">Account</button><button class="text-button" id="logout">Sign out</button>' : '';
  if ($('logout')) $('logout').onclick = async () => { await api('/api/v1/auth/logout', { method: 'POST' }); state.authenticated = false; renderAuth(); };
  if ($('account-button')) $('account-button').onclick = () => { $('account-panel').classList.remove('hidden'); loadAccount(); };
}

async function loadHealth() {
  try {
    const response = await fetch('/health/details');
    const health = await response.json();
    const ollama = health.components.ollama.status;
    const redis = health.components.redis.status;
    $('health-label').textContent = ollama === 'ok' && redis === 'ok' ? 'AI + queue online' : 'System partially available';
    $('health-dot').style.background = ollama === 'ok' && redis === 'ok' ? 'var(--accent)' : '#e99a65';
  } catch (error) {
    $('health-label').textContent = 'System status unavailable';
    $('health-dot').style.background = '#e99a65';
  }
}

async function loadAccount() {
  const account = await (await api('/api/v1/me')).json();
  $('account-email').textContent = account.email;
  const usage = await (await api('/api/v1/me/usage')).json();
  $('usage-summary').textContent = `${usage.review_count} of ${usage.limit} reviews used in the current hour.`;
}

async function loadProjects() {
  $('project-list').innerHTML = '<div class="loading-state">Loading projects…</div>';
  const response = await api('/api/v1/projects');
  if (!response.ok) { $('project-list').innerHTML = '<div class="error-text">Could not load projects.</div>'; throw new Error('Could not load projects'); }
  state.projects = await response.json();
  $('project-list').innerHTML = state.projects.length
    ? state.projects.map((project) => `<button class="project-item ${state.selectedProject?.id === project.id ? 'active' : ''}" data-id="${project.id}">${project.name}</button>`).join('')
    : '<div class="empty-state">No projects yet.</div>';
  document.querySelectorAll('.project-item').forEach((button) => {
    button.onclick = () => selectProject(Number(button.dataset.id));
  });
  if (!state.selectedProject && state.projects[0]) selectProject(state.projects[0].id);
}

async function selectProject(id) {
  const response = await api(`/api/v1/projects/${id}`);
  if (!response.ok) return toast('Could not open project');
  state.selectedProject = await response.json();
  state.files = await Promise.all((state.selectedProject.files || []).map(async (file) => {
    const fileResponse = await api(`/api/v1/files/${file.id}`);
    return fileResponse.ok ? fileResponse.json() : file;
  }));
  $('page-title').textContent = state.selectedProject.name;
  $('project-name').textContent = state.selectedProject.name;
  $('settings-name').value = state.selectedProject.name;
  $('settings-instructions').value = state.selectedProject.review_instructions || '';
  $('project-count').textContent = `${state.files.length} file${state.files.length === 1 ? '' : 's'}`;
  $('run-review').disabled = state.files.length === 0;
  renderFiles();
  await loadReviewHistory();
  await loadStats();
  await loadProjects();
}

async function loadStats() {
  if (!state.selectedProject) return;
  $('review-chart').innerHTML = '<div class="loading-state">Loading metrics…</div>';
  $('finding-chart').innerHTML = '';
  const response = await api(`/api/v1/projects/${state.selectedProject.id}/stats`);
  if (!response.ok) { $('review-chart').innerHTML = '<div class="error-text">Metrics unavailable.</div>'; $('finding-chart').innerHTML = ''; return; }
  const stats = await response.json();
  const findingTotal = stats.findings.low + stats.findings.medium + stats.findings.high + stats.findings.critical;
  $('stats-grid').innerHTML = `<div class="stat-card"><span>Files</span><strong>${stats.file_count}</strong></div><div class="stat-card"><span>Reviews</span><strong>${stats.reviews.total}</strong></div><div class="stat-card"><span>Findings</span><strong>${findingTotal}</strong></div>`;
  renderBars('review-chart', [['Completed', stats.reviews.completed], ['Queued', stats.reviews.queued], ['Failed', stats.reviews.failed]]);
  renderBars('finding-chart', [['Critical', stats.findings.critical], ['High', stats.findings.high], ['Medium', stats.findings.medium], ['Low', stats.findings.low]]);
}

function renderBars(elementId, entries) {
  const total = Math.max(...entries.map((entry) => entry[1]), 1);
  $(elementId).innerHTML = entries.map(([label, value]) => `<div class="bar-row"><span>${label}</span><div class="bar-track"><i style="width: ${(value / total) * 100}%"></i></div><strong>${value}</strong></div>`).join('');
}

async function loadReviewHistory() {
  if (!state.selectedProject) return;
  $('review-history').innerHTML = '<div class="loading-state">Loading review history…</div>';
  const filter = $('review-status-filter').value;
  const search = $('review-search').value.trim();
  const params = new URLSearchParams({ page: state.reviewPage, page_size: 8 });
  if (filter) params.set('status', filter);
  if (search) params.set('search', search);
  const response = await api(`/api/v1/projects/${state.selectedProject.id}/reviews?${params}`);
  if (!response.ok) { $('review-history').innerHTML = '<div class="error-text">Could not load review history.</div>'; return; }
  const reviews = await response.json();
  state.reviewTotal = Number(response.headers.get('X-Total-Count') || reviews.length);
  $('history-page').textContent = `Page ${state.reviewPage}`;
  $('history-previous').disabled = state.reviewPage <= 1;
  $('history-next').disabled = state.reviewPage * 8 >= state.reviewTotal;
  $('review-history').innerHTML = reviews.length ? reviews.slice().reverse().map((review) => {
    const status = review.job_status || review.status;
    const attempt = review.attempt_count ? ` · attempt ${review.attempt_count}` : '';
    const timing = review.completed_at ? ` · finished ${new Date(review.completed_at).toLocaleTimeString()}` : '';
    const retry = status === 'failed' ? `<button class="retry-button" data-retry-id="${review.id}" type="button">Retry</button>` : '';
    return `<div class="history-row"><button class="history-review" data-review-id="${review.id}" type="button"><span><strong>Review #${review.id}</strong><small>${escapeHtml(review.prompt_version)}${attempt}${timing}</small></span><em class="history-status ${escapeHtml(status)}">${escapeHtml(status)}</em></button>${retry}</div>`;
  }).join('') : '<div class="empty-state">No review runs yet.</div>';
  document.querySelectorAll('[data-review-id]').forEach((button) => { button.onclick = () => showReview(Number(button.dataset.reviewId)); });
  document.querySelectorAll('[data-retry-id]').forEach((button) => { button.onclick = () => retryReview(Number(button.dataset.retryId)); });
}

async function retryReview(reviewId) {
  const response = await api(`/api/v1/reviews/${reviewId}/retry`, { method: 'POST' });
  if (!response.ok) return toast('Only failed reviews can be retried');
  $('review-status').textContent = 'queued';
  $('stream-output').textContent = 'Retry queued. Ollama will analyze the project again…';
  await loadReviewHistory();
  await loadStats();
  toast('Review retry queued');
}

function renderFiles() {
  const search = $('file-search').value.toLowerCase();
  const files = state.files.filter((file) => file.path.toLowerCase().includes(search));
  $('file-list').innerHTML = files.length ? files.map((file) => `<div class="file-row"><span>${file.path}</span><button data-file-id="${file.id}">remove</button></div>`).join('') : '<div class="empty-state">No matching files.</div>';
  document.querySelectorAll('[data-file-id]').forEach((button) => { button.onclick = () => removeFile(Number(button.dataset.fileId)); });
}

async function createProject() {
  const name = prompt('Project name');
  if (!name) return;
  const response = await api('/api/v1/projects', { method: 'POST', body: JSON.stringify({ name }) });
  if (!response.ok) return toast('Could not create project');
  await loadProjects();
  selectProject((await response.json()).id);
}

async function removeFile(id) {
  const response = await api(`/api/v1/files/${id}`, { method: 'DELETE' });
  if (response.ok) { await selectProject(state.selectedProject.id); toast('File removed'); }
}

async function runReview() {
  if (!state.selectedProject || !state.files.length) return;
  $('run-review').disabled = true;
  $('run-review').textContent = 'Review in progress…';
  $('review-status').textContent = 'Starting';
  $('stream-output').textContent = '';
  $('findings').innerHTML = '';
  const reviewResponse = await api('/api/v1/reviews', { method: 'POST', body: JSON.stringify({ project_name: state.selectedProject.name, files: state.files.map((file) => ({ path: file.path, content: file.content || '' })) }) });
  if (!reviewResponse.ok) { $('review-status').textContent = 'Error'; $('run-review').disabled = false; $('run-review').textContent = 'Run local review ↗'; return toast('Could not create review'); }
  const review = await reviewResponse.json();
  const enqueueResponse = await api(`/api/v1/reviews/${review.review_id}/enqueue`, { method: 'POST' });
  if (!enqueueResponse.ok) { $('review-status').textContent = 'Error'; $('run-review').disabled = false; $('run-review').textContent = 'Run local review ↗'; return toast('Could not enqueue review'); }
  const job = await enqueueResponse.json();
  $('review-status').textContent = 'Queued';
  $('stream-output').textContent = 'The review is running in the background…';
  await pollJob(job.id, review.review_id);
  await loadReviewHistory();
  await loadStats();
  $('run-review').disabled = false;
  $('run-review').textContent = 'Run local review ↗';
}

async function pollJob(jobId, reviewId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const response = await api(`/api/v1/jobs/${jobId}`);
    if (!response.ok) { $('review-status').textContent = 'Error'; return toast('Could not read job status'); }
    const job = await response.json();
    $('review-status').textContent = job.status;
    renderJobMeta(job);
    if (job.status === 'processing') $('stream-output').textContent = 'Ollama is analyzing your project…';
    if (job.status === 'completed') { $('stream-output').textContent = 'Review completed. Findings are ready below.'; await showReview(reviewId); return; }
    if (job.status === 'failed') { $('stream-output').textContent = 'The background review failed.'; return toast(job.error_message || 'Review failed'); }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  $('review-status').textContent = 'Timeout';
  toast('Review is taking longer than expected. Check history shortly.');
}

function renderJobMeta(job) {
  const meta = $('job-meta');
  meta.classList.remove('hidden');
  const started = job.started_at ? new Date(job.started_at).toLocaleTimeString() : 'not started';
  const heartbeat = job.heartbeat_at ? new Date(job.heartbeat_at).toLocaleTimeString() : 'waiting';
  meta.innerHTML = `<span>Attempt ${job.attempt_count}</span><span>Started ${escapeHtml(started)}</span><span>Heartbeat ${escapeHtml(heartbeat)}</span>`;
}

async function showReview(id) {
  state.currentReviewId = id;
  const severity = $('severity-filter').value;
  const response = await api(`/api/v1/reviews/${id}${severity ? `?severity=${encodeURIComponent(severity)}` : ''}`);
  if (!response.ok) return;
  const review = await response.json();
  $('review-status').textContent = review.status;
  const summary = $('review-summary');
  summary.classList.remove('hidden');
  summary.innerHTML = `<div class="summary-heading"><span class="eyebrow">Review summary · ${escapeHtml(review.prompt_version)}</span><span class="export-actions"><button data-export="markdown" type="button">Markdown</button><button data-export="json" type="button">JSON</button></span></div><p>${escapeHtml(review.summary || 'No summary was generated for this review.')}</p>`;
  summary.querySelectorAll('[data-export]').forEach((button) => { button.onclick = () => exportReview(id, button.dataset.export); });
  $('findings').innerHTML = review.findings.map((finding) => `<article class="finding ${escapeHtml(finding.severity)}"><div class="finding-title">${escapeHtml(finding.title)}</div><div class="finding-meta">${escapeHtml(finding.severity.toUpperCase())} · ${escapeHtml(finding.file_path)}${finding.line_number ? `:${finding.line_number}` : ''}</div><p>${escapeHtml(finding.explanation)}</p><p><strong>Recommendation:</strong> ${escapeHtml(finding.recommendation)}</p>${sourceContext(finding)}</article>`).join('') || '<div class="empty-state">No findings detected.</div>';
}

async function exportReview(reviewId, format) {
  const response = await api(`/api/v1/reviews/${reviewId}/export?format=${format}`);
  if (!response.ok) return toast('Could not export this review');
  const blob = await response.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `review-${reviewId}.${format === 'markdown' ? 'md' : 'json'}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function sourceContext(finding) {
  if (!finding.line_number) return '';
  const file = state.files.find((item) => item.path === finding.file_path);
  if (!file || !file.content) return '';
  const lines = file.content.split('\n');
  const start = Math.max(0, finding.line_number - 3);
  const end = Math.min(lines.length, finding.line_number + 2);
  return `<pre class="source-context">${lines.slice(start, end).map((line, index) => `${String(start + index + 1).padStart(4, ' ')}  ${escapeHtml(line)}`).join('\n')}</pre>`;
}

$('auth-form').onsubmit = async (event) => {
  event.preventDefault();
  const mode = $('auth-title').dataset.mode || 'register';
  const response = await api(`/api/v1/auth/${mode}`, { method: 'POST', body: JSON.stringify({ email: $('auth-email').value, password: $('auth-password').value }) });
  if (!response.ok) { $('auth-error').textContent = (await response.json()).detail || 'Authentication failed'; return; }
  await response.json(); state.authenticated = true; renderAuth(); loadProjects();
};

$('auth-toggle').onclick = () => { const title = $('auth-title'); const register = title.dataset.mode !== 'login'; title.dataset.mode = register ? 'login' : 'register'; title.textContent = register ? 'Welcome back' : 'Create your workspace'; $('auth-toggle').textContent = register ? 'Need an account? Create one' : 'Already have an account? Sign in'; };
$('new-project').onclick = createProject;
$('file-form').onsubmit = async (event) => { event.preventDefault(); if (!state.selectedProject) return toast('Select a project first'); const response = await api(`/api/v1/projects/${state.selectedProject.id}/files`, { method: 'POST', body: JSON.stringify({ path: $('file-path').value, content: $('file-content').value }) }); if (response.ok) { $('file-path').value = ''; $('file-content').value = ''; await selectProject(state.selectedProject.id); toast('File added'); } else toast('Could not add file'); };
$('archive-form').onsubmit = async (event) => { event.preventDefault(); if (!state.selectedProject) return toast('Select a project first'); const input = $('archive-input'); if (!input.files.length) return toast('Choose a ZIP archive first'); $('archive-status').textContent = 'Importing archive…'; const formData = new FormData(); formData.append('archive', input.files[0]); const response = await uploadApi(`/api/v1/projects/${state.selectedProject.id}/archive`, formData); if (!response.ok) { $('archive-status').textContent = 'Import failed'; return toast('Could not import archive'); } const result = await response.json(); $('archive-status').textContent = `${result.imported_files} imported · ${result.skipped_files} skipped`; input.value = ''; await selectProject(state.selectedProject.id); toast('Archive imported'); };
$('run-review').onclick = runReview;
$('close-account').onclick = () => $('account-panel').classList.add('hidden');
$('password-form').onsubmit = async (event) => { event.preventDefault(); const response = await api('/api/v1/me/password', { method: 'POST', body: JSON.stringify({ current_password: $('current-password').value, new_password: $('new-password').value }) }); if (!response.ok) { $('password-status').textContent = (await response.json()).detail || 'Could not update password'; return; } $('password-status').textContent = 'Password updated'; $('password-form').reset(); };
$('settings-form').onsubmit = async (event) => { event.preventDefault(); if (!state.selectedProject) return; const response = await api(`/api/v1/projects/${state.selectedProject.id}`, { method: 'PATCH', body: JSON.stringify({ name: $('settings-name').value, review_instructions: $('settings-instructions').value || null }) }); if (!response.ok) { $('settings-status').textContent = 'Could not save settings'; return; } $('settings-status').textContent = 'Settings saved'; await loadProjects(); await selectProject(state.selectedProject.id); toast('Settings saved'); };
$('delete-project').onclick = async () => { if (!state.selectedProject || !confirm(`Delete ${state.selectedProject.name}?`)) return; const response = await api(`/api/v1/projects/${state.selectedProject.id}`, { method: 'DELETE' }); if (!response.ok) return toast('Could not delete project'); state.selectedProject = null; await loadProjects(); $('page-title').textContent = 'Welcome to Forge Review'; $('project-name').textContent = 'Select a project'; $('file-list').innerHTML = '<div class="empty-state">Create or select a project to begin.</div>'; toast('Project deleted'); };
$('file-search').oninput = renderFiles;
$('review-status-filter').onchange = loadReviewHistory;
$('review-search').oninput = () => { state.reviewPage = 1; loadReviewHistory(); };
$('history-previous').onclick = () => { if (state.reviewPage > 1) { state.reviewPage -= 1; loadReviewHistory(); } };
$('history-next').onclick = () => { if (state.reviewPage * 8 < state.reviewTotal) { state.reviewPage += 1; loadReviewHistory(); } };
$('severity-filter').onchange = () => { if (state.currentReviewId) showReview(state.currentReviewId); };

renderAuth();
loadHealth();
api('/api/v1/me').then((response) => {
  if (!response.ok) return;
  state.authenticated = true;
  renderAuth();
  return loadProjects();
}).catch(() => { state.authenticated = false; renderAuth(); });

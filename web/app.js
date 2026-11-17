const state = { token: localStorage.getItem('forge_token'), projects: [], selectedProject: null, files: [] };
const $ = (id) => document.getElementById(id);

function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  return fetch(path, { ...options, headers });
}

function uploadApi(path, formData) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  return fetch(path, { method: 'POST', headers, body: formData });
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').style.display = 'block';
  setTimeout(() => { $('toast').style.display = 'none'; }, 2800);
}

function renderAuth() {
  $('auth-panel').classList.toggle('hidden', Boolean(state.token));
  $('workspace').classList.toggle('hidden', !state.token);
  $('account-area').innerHTML = state.token ? '<button class="text-button" id="logout">Sign out</button>' : '';
  if ($('logout')) $('logout').onclick = () => { localStorage.removeItem('forge_token'); state.token = null; renderAuth(); };
}

async function loadProjects() {
  const response = await api('/api/v1/projects');
  if (!response.ok) throw new Error('Could not load projects');
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
  $('project-count').textContent = `${state.files.length} file${state.files.length === 1 ? '' : 's'}`;
  $('run-review').disabled = state.files.length === 0;
  $('file-list').innerHTML = state.files.length ? state.files.map((file) => `<div class="file-row"><span>${file.path}</span><button data-file-id="${file.id}">remove</button></div>`).join('') : '<div class="empty-state">No files in this project yet.</div>';
  document.querySelectorAll('[data-file-id]').forEach((button) => { button.onclick = () => removeFile(Number(button.dataset.fileId)); });
  await loadReviewHistory();
  await loadStats();
  await loadProjects();
}

async function loadStats() {
  if (!state.selectedProject) return;
  const response = await api(`/api/v1/projects/${state.selectedProject.id}/stats`);
  if (!response.ok) return;
  const stats = await response.json();
  const findingTotal = stats.findings.low + stats.findings.medium + stats.findings.high + stats.findings.critical;
  $('stats-grid').innerHTML = `<div class="stat-card"><span>Files</span><strong>${stats.file_count}</strong></div><div class="stat-card"><span>Reviews</span><strong>${stats.reviews.total}</strong></div><div class="stat-card"><span>Findings</span><strong>${findingTotal}</strong></div>`;
}

async function loadReviewHistory() {
  if (!state.selectedProject) return;
  const response = await api(`/api/v1/projects/${state.selectedProject.id}/reviews`);
  if (!response.ok) { $('review-history').innerHTML = '<div class="error-text">Could not load review history.</div>'; return; }
  const reviews = await response.json();
  $('review-history').innerHTML = reviews.length ? reviews.slice().reverse().map((review) => `<button data-review-id="${review.id}"><span>Review #${review.id}</span><small>${review.status}</small></button>`).join('') : '<div class="empty-state">No review runs yet.</div>';
  document.querySelectorAll('[data-review-id]').forEach((button) => { button.onclick = () => showReview(Number(button.dataset.reviewId)); });
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
    if (job.status === 'processing') $('stream-output').textContent = 'Ollama is analyzing your project…';
    if (job.status === 'completed') { $('stream-output').textContent = 'Review completed. Findings are ready below.'; await showReview(reviewId); return; }
    if (job.status === 'failed') { $('stream-output').textContent = 'The background review failed.'; return toast(job.error_message || 'Review failed'); }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  $('review-status').textContent = 'Timeout';
  toast('Review is taking longer than expected. Check history shortly.');
}

async function showReview(id) {
  const response = await api(`/api/v1/reviews/${id}`);
  if (!response.ok) return;
  const review = await response.json();
  $('findings').innerHTML = review.findings.map((finding) => `<article class="finding ${finding.severity}"><div class="finding-title">${finding.title}</div><div class="finding-meta">${finding.severity.toUpperCase()} · ${finding.file_path}${finding.line_number ? `:${finding.line_number}` : ''}</div><p>${finding.explanation}</p><p><strong>Recommendation:</strong> ${finding.recommendation}</p></article>`).join('') || '<div class="empty-state">No findings detected.</div>';
}

$('auth-form').onsubmit = async (event) => {
  event.preventDefault();
  const mode = $('auth-title').dataset.mode || 'register';
  const response = await api(`/api/v1/auth/${mode}`, { method: 'POST', body: JSON.stringify({ email: $('auth-email').value, password: $('auth-password').value }) });
  if (!response.ok) { $('auth-error').textContent = (await response.json()).detail || 'Authentication failed'; return; }
  state.token = (await response.json()).access_token; localStorage.setItem('forge_token', state.token); renderAuth(); loadProjects();
};

$('auth-toggle').onclick = () => { const title = $('auth-title'); const register = title.dataset.mode !== 'login'; title.dataset.mode = register ? 'login' : 'register'; title.textContent = register ? 'Welcome back' : 'Create your workspace'; $('auth-toggle').textContent = register ? 'Need an account? Create one' : 'Already have an account? Sign in'; };
$('new-project').onclick = createProject;
$('file-form').onsubmit = async (event) => { event.preventDefault(); if (!state.selectedProject) return toast('Select a project first'); const response = await api(`/api/v1/projects/${state.selectedProject.id}/files`, { method: 'POST', body: JSON.stringify({ path: $('file-path').value, content: $('file-content').value }) }); if (response.ok) { $('file-path').value = ''; $('file-content').value = ''; await selectProject(state.selectedProject.id); toast('File added'); } else toast('Could not add file'); };
$('archive-form').onsubmit = async (event) => { event.preventDefault(); if (!state.selectedProject) return toast('Select a project first'); const input = $('archive-input'); if (!input.files.length) return toast('Choose a ZIP archive first'); $('archive-status').textContent = 'Importing archive…'; const formData = new FormData(); formData.append('archive', input.files[0]); const response = await uploadApi(`/api/v1/projects/${state.selectedProject.id}/archive`, formData); if (!response.ok) { $('archive-status').textContent = 'Import failed'; return toast('Could not import archive'); } const result = await response.json(); $('archive-status').textContent = `${result.imported_files} imported · ${result.skipped_files} skipped`; input.value = ''; await selectProject(state.selectedProject.id); toast('Archive imported'); };
$('run-review').onclick = runReview;

renderAuth();
if (state.token) loadProjects().catch(() => { localStorage.removeItem('forge_token'); state.token = null; renderAuth(); });

const state = { token: localStorage.getItem('forge_token'), projects: [], selectedProject: null, files: [] };
const $ = (id) => document.getElementById(id);

function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  return fetch(path, { ...options, headers });
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
  await loadProjects();
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
  const streamResponse = await api(`/api/v1/reviews/${review.review_id}/stream`);
  if (!streamResponse.ok || !streamResponse.body) { $('review-status').textContent = 'Error'; $('run-review').disabled = false; $('run-review').textContent = 'Run local review ↗'; return toast('Could not start stream'); }
  $('review-status').textContent = 'Reviewing';
  const reader = streamResponse.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n'); buffer = events.pop();
    events.forEach((event) => {
      const line = event.split('\n').find((item) => item.startsWith('data: '));
      if (!line) return;
      const payload = JSON.parse(line.slice(6));
      if (payload.type === 'chunk') $('stream-output').textContent += payload.content;
      if (payload.type === 'status') $('review-status').textContent = payload.status;
      if (payload.type === 'error') { $('review-status').textContent = 'Failed'; toast(payload.message); }
    });
  }
  if ($('review-status').textContent === 'completed') await showReview(review.review_id);
  await loadReviewHistory();
  $('run-review').disabled = false;
  $('run-review').textContent = 'Run local review ↗';
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
$('run-review').onclick = runReview;

renderAuth();
if (state.token) loadProjects().catch(() => { localStorage.removeItem('forge_token'); state.token = null; renderAuth(); });

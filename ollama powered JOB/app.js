/**
 * RecruitScreen v1.0 — Dashboard Logic & API Integration
 * Agentic Talent Screening & Evidence Verification Platform
 */

(() => {
  'use strict';

  // ─── Configuration & API Base ──────────────────────────────────────────
  // Connect to Flask backend on port 5000, supporting VS Code Live Server (ports 5500/5501),
  // direct file://, or Flask's own server
  const BACKEND_PORT = 5000;
  const backendHost = (window.location.hostname && window.location.hostname !== '')
    ? window.location.hostname
    : 'localhost';
  const backendProto = window.location.protocol.startsWith('http')
    ? window.location.protocol
    : 'http:';

  const API_BASE = (window.location.port === String(BACKEND_PORT))
    ? window.location.origin
    : `${backendProto}//${backendHost}:${BACKEND_PORT}`;

  const ENDPOINTS = {
    health: `${API_BASE}/api/health`,
    uploadJd: `${API_BASE}/api/recruitment/upload-jd`,
    deleteJd: `${API_BASE}/api/recruitment/delete-jd`,
    uploadResumes: `${API_BASE}/api/recruitment/upload-resumes`,
    deleteResume: `${API_BASE}/api/recruitment/delete-resume`,
    clearResumes: `${API_BASE}/api/recruitment/clear-resumes`,
    analyze: `${API_BASE}/api/recruitment/analyze`,
    status: (runId) => `${API_BASE}/api/recruitment/status/${encodeURIComponent(runId)}`,
    results: (runId) => `${API_BASE}/api/recruitment/results/${encodeURIComponent(runId)}`,
    candidate: (id, runId) => `${API_BASE}/api/recruitment/candidate/${encodeURIComponent(id)}?run_id=${encodeURIComponent(runId)}`,
    deleteCandidate: `${API_BASE}/api/recruitment/delete-candidate`,
    compare: `${API_BASE}/api/recruitment/compare`,
    gaps: (runId) => `${API_BASE}/api/recruitment/gaps/${encodeURIComponent(runId)}`,
    chat: `${API_BASE}/api/chat`,
    latest: `${API_BASE}/api/recruitment/latest`,
    clearResults: `${API_BASE}/api/recruitment/clear-results`,
    githubToken: `${API_BASE}/api/recruitment/github-token`,
  };

  // ─── Application State ─────────────────────────────────────────────────
  function generateUUID() {
    return 'sess_' + Math.random().toString(36).substring(2, 9) + Date.now().toString(36);
  }

  const state = {
    sessionId: generateUUID(),
    runId: null,
    screeningResult: null,
    activePage: 'workspace',
    jdFile: null,
    resumesList: [], // array of File objects
    githubUrlsMap: {}, // [NEW] { filename: githubUrl }
    selectedCandidateId: null,
    chatMessages: [],
    pollingTimer: null,
    isAnalyzing: false,
  };

  // ─── GitHub Token Store (localStorage) ────────────────────────────
  const GITHUB_TOKEN_KEY = 'aria_github_pat';
  const githubTokenStore = {
    get:   ()  => localStorage.getItem(GITHUB_TOKEN_KEY) || '',
    set:   (t) => localStorage.setItem(GITHUB_TOKEN_KEY, t),
    clear: ()  => localStorage.removeItem(GITHUB_TOKEN_KEY),
  };

  // ─── DOM References ────────────────────────────────────────────────────
  const dom = {
    // Topbar
    systemStatusBadge: document.getElementById('system-status-badge'),
    systemStatusText: document.getElementById('system-status-text'),
    activeJobIndicator: document.getElementById('active-job-indicator'),
    activeJobTitle: document.getElementById('active-job-title'),

    // Navigation
    navItems: document.querySelectorAll('.nav-item'),
    pages: document.querySelectorAll('.page'),
    badgeCandidateCount: document.getElementById('badge-candidate-count'),

    // Workspace & Upload
    jdDropZone: document.getElementById('jd-drop-zone'),
    jdFileInput: document.getElementById('jd-file-input'),
    jdStatusTag: document.getElementById('jd-status-tag'),
    jdFileInfo: document.getElementById('jd-file-info'),
    jdPreviewBox: document.getElementById('jd-preview-box'),
    jdPreviewName: document.getElementById('jd-preview-name'),
    jdPreviewStats: document.getElementById('jd-preview-stats'),
    jdPreviewText: document.getElementById('jd-preview-text'),
    btnClearJd: document.getElementById('btn-clear-jd'),

    resumesDropZone: document.getElementById('resumes-drop-zone'),
    resumesFileInput: document.getElementById('resumes-file-input'),
    resumesCountBadge: document.getElementById('resumes-count-badge'),
    resumesFileList: document.getElementById('resumes-file-list'),
    btnClearResumes: document.getElementById('btn-clear-resumes'),

    // GitHub Settings
    btnGithubSettings: document.getElementById('btn-github-settings'),
    githubSettingsPanel: document.getElementById('github-settings-panel'),
    btnGithubSettingsClose: document.getElementById('btn-github-settings-close'),
    githubTokenInput: document.getElementById('github-token-input'),
    btnGithubTokenSave: document.getElementById('btn-github-token-save'),
    btnGithubTokenClear: document.getElementById('btn-github-token-clear'),
    githubTokenStatus: document.getElementById('github-token-status'),

    btnStartScreening: document.getElementById('btn-start-screening'),
    pipelineCard: document.getElementById('pipeline-progress-card'),
    pipelineStatusTitle: document.getElementById('pipeline-status-title'),
    progressPct: document.getElementById('progress-pct'),
    progressBarFill: document.getElementById('progress-bar-fill'),
    progressLog: document.getElementById('progress-log'),
    pipelineDoneActions: document.getElementById('pipeline-done-actions'),
    btnViewResults: document.getElementById('btn-view-results'),

    // Rankings
    statTotalCandidates: document.getElementById('stat-total-candidates'),
    statTopScore: document.getElementById('stat-top-score'),
    statAvgScore: document.getElementById('stat-avg-score'),
    statVerifiedClaims: document.getElementById('stat-verified-claims'),
    rankingsContainer: document.getElementById('rankings-container'),
    filterCandidateInput: document.getElementById('filter-candidate-input'),
    sortCandidateSelect: document.getElementById('sort-candidate-select'),
    btnClearResults: document.getElementById('btn-clear-results'),
    // Feasibility Panel
    feasibilityPanel: document.getElementById('feasibility-panel'),
    feasibilityIcon: document.getElementById('feasibility-icon'),
    feasibilitySubtitle: document.getElementById('feasibility-subtitle'),
    feasibilitySeverityBadge: document.getElementById('feasibility-severity-badge'),
    feasibilityConflicts: document.getElementById('feasibility-conflicts'),
    feasibilityConflictList: document.getElementById('feasibility-conflict-list'),
    feasibilityAdvisory: document.getElementById('feasibility-advisory'),
    coverageBarsContainer: document.getElementById('coverage-bars-container'),
    coverageCandidateCount: document.getElementById('coverage-candidate-count'),
    coverageIntersection: document.getElementById('coverage-intersection'),
    intersectionIcon: document.getElementById('intersection-icon'),
    intersectionCountText: document.getElementById('intersection-count-text'),
    // Trade-Off Shortlist
    tradeoffShortlistSection: document.getElementById('tradeoff-shortlist-section'),
    tradeoffCardsContainer: document.getElementById('tradeoff-cards-container'),

    // Detail
    detailEmptyState: document.getElementById('detail-empty-state'),
    detailContentArea: document.getElementById('detail-content-area'),
    detailHeaderName: document.getElementById('detail-header-name'),
    detailHeaderMeta: document.getElementById('detail-header-meta'),
    detailCandidateName: document.getElementById('detail-candidate-name'),
    detailCandidateSub: document.getElementById('detail-candidate-sub'),
    detailScoreRing: document.getElementById('detail-score-ring'),
    detailTotalScore: document.getElementById('detail-total-score'),
    detailTradeoffNote: document.getElementById('detail-tradeoff-note'),
    scoreCompSkills: document.getElementById('score-comp-skills'),
    scoreCompExp: document.getElementById('score-comp-exp'),
    scoreCompEvidence: document.getElementById('score-comp-evidence'),
    scoreCompOther: document.getElementById('score-comp-other'),
    detailSkillsList: document.getElementById('detail-skills-list'),
    btnBackToRankings: document.getElementById('btn-back-to-rankings'),

    // Compare
    compareSelectA: document.getElementById('compare-select-a'),
    compareSelectB: document.getElementById('compare-select-b'),
    btnRunCompare: document.getElementById('btn-run-compare'),
    compareNarrativeCard: document.getElementById('compare-narrative-card'),
    compareNarrativeText: document.getElementById('compare-narrative-text'),
    compareWinnerBadge: document.getElementById('compare-winner-badge'),
    compareTableContainer: document.getElementById('compare-table-container'),
    compareGrid: document.getElementById('compare-grid'),

    // Gaps
    gapRowsContainer: document.getElementById('gap-rows-container'),

    // Chat
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    btnChatSend: document.getElementById('btn-chat-send'),

    // Toast
    toastContainer: document.getElementById('toast-container'),
  };

  // ─── GitHub Settings Panel ──────────────────────────────────────────
  function updateGithubBtnState() {
    const hasToken = !!githubTokenStore.get();
    if (dom.btnGithubSettings) {
      dom.btnGithubSettings.classList.toggle('token-active', hasToken);
      dom.btnGithubSettings.title = hasToken
        ? '🐙 GitHub token configured (click to update)'
        : '🐙 Configure GitHub Token for evidence retrieval';
    }
  }

  // Restore PAT from localStorage on load
  if (dom.githubTokenInput && githubTokenStore.get()) {
    dom.githubTokenInput.value = githubTokenStore.get();
  }
  updateGithubBtnState();

  if (dom.btnGithubSettings) {
    dom.btnGithubSettings.addEventListener('click', () => {
      dom.githubSettingsPanel.classList.toggle('open');
      dom.githubSettingsPanel.classList.remove('hidden');
    });
  }
  if (dom.btnGithubSettingsClose) {
    dom.btnGithubSettingsClose.addEventListener('click', () => {
      dom.githubSettingsPanel.classList.remove('open');
    });
  }

  if (dom.btnGithubTokenSave) {
    dom.btnGithubTokenSave.addEventListener('click', async () => {
      const token = (dom.githubTokenInput?.value || '').trim();
      if (!token) {
        dom.githubTokenStatus.textContent = '⚠ Please enter a token.';
        dom.githubTokenStatus.style.color = 'var(--amber)';
        return;
      }
      githubTokenStore.set(token);
      updateGithubBtnState();
      // Send to server
      try {
        const res = await fetch(ENDPOINTS.githubToken, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed');
        dom.githubTokenStatus.textContent = `✓ Token saved: ${data.masked_token}`;
        dom.githubTokenStatus.style.color = 'var(--emerald)';
        showToast('🐙 GitHub token configured', 'success');
      } catch (e) {
        dom.githubTokenStatus.textContent = `✓ Saved locally (server sync failed: ${e.message})`;
        dom.githubTokenStatus.style.color = 'var(--amber)';
      }
    });
  }

  if (dom.btnGithubTokenClear) {
    dom.btnGithubTokenClear.addEventListener('click', async () => {
      githubTokenStore.clear();
      if (dom.githubTokenInput) dom.githubTokenInput.value = '';
      dom.githubTokenStatus.textContent = 'Token cleared.';
      dom.githubTokenStatus.style.color = 'var(--text-muted)';
      updateGithubBtnState();
      try {
        await fetch(ENDPOINTS.githubToken, { method: 'DELETE' });
      } catch (_) {}
      showToast('GitHub token cleared', 'info');
    });
  }

  // ─── Toast Notifications ───────────────────────────────────────────────
  function showToast(message, type = 'info', duration = 3500) {
    if (!dom.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    dom.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // ─── Navigation & Router ───────────────────────────────────────────────
  function switchPage(pageId) {
    state.activePage = pageId;

    dom.pages.forEach(p => {
      p.classList.toggle('active', p.id === `page-${pageId}`);
    });

    dom.navItems.forEach(item => {
      const target = item.getAttribute('data-page');
      item.classList.toggle('active', target === pageId);
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  dom.navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      if (e && e.preventDefault) e.preventDefault();
      const pageId = item.getAttribute('data-page');
      if (pageId) {
        if (pageId === 'detail' && (!state.selectedCandidateId || (dom.detailContentArea && dom.detailContentArea.classList.contains('hidden')))) {
          const firstCand = state.screeningResult?.ranked_list?.candidates?.[0];
          if (firstCand?.score?.candidate_id) {
            openCandidateDetail(firstCand.score.candidate_id);
            return;
          }
        }
        switchPage(pageId);
      }
    });
  });

  if (dom.btnBackToRankings) {
    dom.btnBackToRankings.addEventListener('click', (e) => {
      if (e && e.preventDefault) e.preventDefault();
      switchPage('rankings');
    });
  }
  if (dom.btnViewResults) {
    dom.btnViewResults.addEventListener('click', (e) => {
      if (e && e.preventDefault) e.preventDefault();
      switchPage('rankings');
    });
  }

  // ─── System Health Check ───────────────────────────────────────────────
  async function checkSystemHealth() {
    try {
      const res = await fetch(ENDPOINTS.health);
      if (!res.ok) throw new Error('Health check failed');
      const data = await res.json();

      let text = 'Ready · ';
      if (data.ollama) text += ` (${data.local_model})`;
      else text += 'Ollama offline';

      if (data.groq_enabled) text += ` + Groq (${data.groq_model})`;

      dom.systemStatusText.textContent = text;
      dom.systemStatusBadge.className = 'status-badge ok';
    } catch (e) {
      dom.systemStatusText.textContent = 'Server Offline (port 5000)';
      dom.systemStatusBadge.className = 'status-badge error';
    }
  }

  // ─── Drag & Drop Helpers ───────────────────────────────────────────────
  function initDropZone(zone, input, onFiles) {
    ['dragenter', 'dragover'].forEach(name => {
      zone.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      zone.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove('dragover');
      });
    });

    zone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length > 0) {
        onFiles(dt.files);
      }
    });

    input.addEventListener('change', () => {
      if (input.files && input.files.length > 0) {
        onFiles(input.files);
      }
    });
  }

  // ─── JD Upload Handling ────────────────────────────────────────────────
  initDropZone(dom.jdDropZone, dom.jdFileInput, async (files) => {
    const file = files[0];
    if (!file) return;

    state.jdFile = file;
    dom.jdDropZone.classList.add('uploaded');
    dom.jdStatusTag.textContent = 'Uploading...';
    dom.jdStatusTag.className = 'status-badge';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', state.sessionId);

    try {
      const res = await fetch(ENDPOINTS.uploadJd, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.error || 'Failed to upload JD');

      dom.jdStatusTag.textContent = 'Uploaded ✓';
      dom.jdStatusTag.className = 'status-badge ok';

      // Update Preview Box
      dom.jdPreviewBox.classList.remove('hidden');
      dom.jdPreviewName.textContent = data.filename;
      dom.jdPreviewStats.textContent = `${data.word_count || 0} words · ${(data.char_count || 0).toLocaleString()} chars`;
      dom.jdPreviewText.textContent = data.preview || '';

      // Show Remove JD button
      if (dom.btnClearJd) dom.btnClearJd.style.display = 'inline-flex';

      // Update Topbar Active Job Indicator
      dom.activeJobIndicator.style.display = 'inline-flex';
      dom.activeJobTitle.textContent = data.filename.replace(/\.[^/.]+$/, '');

      showToast(`Job Description loaded (${data.word_count} words)`, 'success');
      checkScreeningReadiness();
    } catch (err) {
      dom.jdStatusTag.textContent = 'Error';
      dom.jdStatusTag.className = 'status-badge error';
      showToast(err.message, 'error');
    }
  });

  // Remove JD Handler
  if (dom.btnClearJd) {
    dom.btnClearJd.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();

      try {
        await fetch(ENDPOINTS.deleteJd, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: state.sessionId }),
        });

        state.jdFile = null;
        dom.jdDropZone.classList.remove('uploaded');
        dom.jdStatusTag.textContent = 'Awaiting Upload';
        dom.jdStatusTag.className = 'status-badge';
        dom.jdPreviewBox.classList.add('hidden');
        dom.jdFileInput.value = '';
        dom.btnClearJd.style.display = 'none';

        if (dom.activeJobIndicator) dom.activeJobIndicator.style.display = 'none';

        checkScreeningReadiness();
        showToast('Job Description removed', 'info');
      } catch (err) {
        showToast(`Failed to remove JD: ${err.message}`, 'error');
      }
    });
  }

  // ─── Resumes Batch Upload Handling ─────────────────────────────────────
  initDropZone(dom.resumesDropZone, dom.resumesFileInput, async (files) => {
    if (!files || files.length === 0) return;

    const incoming = Array.from(files);
    let replacedCount = 0;
    let addedCount = 0;

    // Deduplicate incoming files against state.resumesList by filename
    incoming.forEach(newFile => {
      const existingIdx = state.resumesList.findIndex(f => f.name === newFile.name);
      if (existingIdx >= 0) {
        state.resumesList[existingIdx] = newFile;
        replacedCount++;
      } else {
        state.resumesList.push(newFile);
        addedCount++;
      }
    });

    dom.resumesCountBadge.textContent = `${state.resumesList.length} files`;
    dom.resumesDropZone.classList.add('uploaded');
    if (dom.btnClearResumes) dom.btnClearResumes.style.display = 'inline-flex';

    // Send files to backend
    const formData = new FormData();
    formData.append('session_id', state.sessionId);
    incoming.forEach(f => formData.append('files', f));

    try {
      const res = await fetch(ENDPOINTS.uploadResumes, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.error || 'Failed to upload resumes');

      // Update UI File List
      renderResumesList();

      if (replacedCount > 0 && addedCount > 0) {
        showToast(`${addedCount} new resume(s) uploaded, ${replacedCount} updated`, 'success');
      } else if (replacedCount > 0) {
        showToast(`Updated ${replacedCount} existing resume(s)`, 'info');
      } else {
        showToast(`${data.accepted.length} resume(s) uploaded successfully`, 'success');
      }

      if (data.rejected && data.rejected.length > 0) {
        showToast(`${data.rejected.length} files rejected (invalid format)`, 'error');
      }

      checkScreeningReadiness();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  function renderResumesList() {
    dom.resumesFileList.innerHTML = '';
    const hasResumes = state.resumesList.length > 0;

    if (dom.btnClearResumes) {
      dom.btnClearResumes.style.display = hasResumes ? 'inline-flex' : 'none';
    }

    if (!hasResumes) {
      dom.resumesDropZone.classList.remove('uploaded');
      dom.resumesCountBadge.textContent = '0 files';
      return;
    }

    state.resumesList.forEach((f, idx) => {
      const row = document.createElement('div');
      row.className = 'resume-file-row';

      const existingUrl = state.githubUrlsMap[f.name] || '';

      row.innerHTML = `
        <div class="resume-file-header">
          <span class="file-icon">📄</span>
          <span class="resume-file-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
          <span class="text-xs font-mono text-muted">${formatBytes(f.size)}</span>
          <button class="btn-file-delete" type="button" title="Delete ${escapeHtml(f.name)}" data-filename="${escapeHtml(f.name)}">✕</button>
        </div>
        <div class="resume-github-input-row">
          <span class="resume-github-label">🐙 GitHub:</span>
          <input
            type="url"
            class="resume-github-input ${existingUrl ? 'has-url' : ''}"
            placeholder="https://github.com/username (optional)"
            value="${escapeHtml(existingUrl)}"
            data-filename="${escapeHtml(f.name)}"
            id="github-url-${idx}"
          />
        </div>
      `;

      // Delete button
      const deleteBtn = row.querySelector('.btn-file-delete');
      if (deleteBtn) {
        deleteBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          e.preventDefault();
          delete state.githubUrlsMap[f.name];
          await removeResumeFile(f.name, row);
        });
      }

      // GitHub URL input live update
      const ghInput = row.querySelector('.resume-github-input');
      if (ghInput) {
        ghInput.addEventListener('input', () => {
          const url = ghInput.value.trim();
          if (url) {
            state.githubUrlsMap[f.name] = url;
            ghInput.classList.add('has-url');
          } else {
            delete state.githubUrlsMap[f.name];
            ghInput.classList.remove('has-url');
          }
        });
      }

      dom.resumesFileList.appendChild(row);
    });
  }

  async function removeResumeFile(filename, itemElement) {
    try {
      if (itemElement) itemElement.classList.add('deleting');

      // Call backend to delete from session store
      await fetch(ENDPOINTS.deleteResume, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.sessionId, filename }),
      });

      // Remove from local state
      state.resumesList = state.resumesList.filter(f => f.name !== filename);
      dom.resumesCountBadge.textContent = `${state.resumesList.length} files`;

      setTimeout(() => {
        renderResumesList();
        checkScreeningReadiness();
      }, 200);

      showToast(`Removed resume: ${filename}`, 'info');
    } catch (err) {
      showToast(`Failed to delete resume: ${err.message}`, 'error');
      renderResumesList();
    }
  }

  // Clear All Resumes Handler
  if (dom.btnClearResumes) {
    dom.btnClearResumes.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (!confirm('Are you sure you want to remove all uploaded resumes?')) return;

      try {
        await fetch(ENDPOINTS.clearResumes, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: state.sessionId }),
        });

        state.resumesList = [];
        dom.resumesCountBadge.textContent = '0 files';
        dom.resumesDropZone.classList.remove('uploaded');
        if (dom.resumesFileInput) dom.resumesFileInput.value = '';
        renderResumesList();
        checkScreeningReadiness();
        showToast('All uploaded resumes cleared', 'info');
      } catch (err) {
        showToast(`Failed to clear resumes: ${err.message}`, 'error');
      }
    });
  }

  function checkScreeningReadiness() {
    const ready = Boolean(state.jdFile && state.resumesList.length > 0);
    dom.btnStartScreening.disabled = !ready;
  }

  // ─── Pipeline Execution & Progress Polling ─────────────────────────────
  dom.btnStartScreening.addEventListener('click', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (state.isAnalyzing) return;

    state.isAnalyzing = true;
    dom.btnStartScreening.disabled = true;
    dom.pipelineCard.classList.remove('hidden');
    dom.pipelineDoneActions.style.display = 'none';
    dom.pipelineStatusTitle.textContent = 'Initializing Agentic Pipeline...';
    dom.progressPct.textContent = '0%';
    dom.progressBarFill.style.width = '0%';
    dom.progressLog.innerHTML = '<div class="log-line">Sending request to orchestrator...</div>';

    resetVisualStages();

    try {
      const res = await fetch(ENDPOINTS.analyze, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:   state.sessionId,
          github_urls:  state.githubUrlsMap,
          github_token: githubTokenStore.get(),
        }),
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.error || 'Failed to start screening pipeline');

      state.runId = data.run_id;
      showToast('Screening pipeline running', 'info');

      // Begin polling status
      startStatusPolling();
    } catch (err) {
      state.isAnalyzing = false;
      dom.btnStartScreening.disabled = false;
      showToast(err.message, 'error');
      appendLogLine(`[Error] ${err.message}`, 'error');
    }
  });

  function startStatusPolling() {
    if (state.pollingTimer) clearInterval(state.pollingTimer);

    state.pollingTimer = setInterval(async () => {
      if (!state.runId) return;

      try {
        const res = await fetch(ENDPOINTS.status(state.runId));
        if (!res.ok) return;
        const status = await res.json();

        // Update progress bar
        const pct = Math.min(100, Math.max(0, status.progress || 0));
        dom.progressPct.textContent = `${pct}%`;
        dom.progressBarFill.style.width = `${pct}%`;

        // Update title and visual stages
        if (status.stage) {
          dom.pipelineStatusTitle.textContent = `Stage: ${formatStageName(status.stage)}`;
          updateVisualStages(status.stage);
        }

        // Update activity log
        if (status.log && Array.isArray(status.log)) {
          renderLogLines(status.log);
        }

        if (status.error) {
          clearInterval(state.pollingTimer);
          state.isAnalyzing = false;
          dom.btnStartScreening.disabled = false;
          appendLogLine(`[Pipeline Error] ${status.error}`, 'error');
          showToast(`Pipeline stopped: ${status.error}`, 'error');
        }

        if (status.done) {
          clearInterval(state.pollingTimer);
          state.isAnalyzing = false;
          dom.btnStartScreening.disabled = false;
          dom.pipelineStatusTitle.textContent = 'Pipeline Finished';
          dom.progressPct.textContent = '100%';
          dom.progressBarFill.style.width = '100%';
          completeAllVisualStages();

          appendLogLine('All screening agents finished. Fetching structured results...', 'success');
          dom.pipelineDoneActions.style.display = 'flex';

          // Fetch full results
          await fetchResults(state.runId);
        }
      } catch (e) {
        console.warn('Status poll error:', e);
      }
    }, 1200);
  }

  const STAGE_ORDER = [
    'processing_documents',
    'analyzing_jd',
    'feasibility_analysis',
    'analyzing_resumes',
    'extracting_claims',
    'retrieving_evidence',
    'verifying_evidence',
    'github_evidence',    // [NEW] Stage 5b
    'matching_skills',
    'scoring',
    'pool_coverage',
    'ranking',
    'gap_analysis',
  ];

  const STAGE_MAP = {
    'processing_documents':  'stage-doc',
    'analyzing_jd':          'stage-jd',
    'feasibility_analysis':  'stage-feasibility',
    'analyzing_resumes':     'stage-resumes',
    'extracting_claims':     'stage-claims',
    'retrieving_evidence':   'stage-retrieval',
    'verifying_evidence':    'stage-verification',
    'github_evidence':       'stage-github',     // [NEW]
    'matching_skills':       'stage-matching',
    'scoring':               'stage-scoring',
    'pool_coverage':         'stage-pool-coverage',
    'ranking':               'stage-ranking',
    'gap_analysis':          'stage-gaps',
    'tradeoff_analysis':     'stage-ranking',
    'completed':             'stage-gaps',
  };

  function resetVisualStages() {
    STAGE_ORDER.forEach(s => {
      const el = document.getElementById(STAGE_MAP[s]);
      if (el) el.className = 'pipeline-stage';
    });
  }

  function updateVisualStages(currentStage) {
    const currentIndex = STAGE_ORDER.indexOf(currentStage);
    STAGE_ORDER.forEach((s, idx) => {
      const el = document.getElementById(STAGE_MAP[s]);
      if (!el) return;
      if (idx < currentIndex) {
        el.className = 'pipeline-stage done';
      } else if (idx === currentIndex) {
        el.className = 'pipeline-stage active';
      } else {
        el.className = 'pipeline-stage';
      }
    });
  }

  function completeAllVisualStages() {
    STAGE_ORDER.forEach(s => {
      const el = document.getElementById(STAGE_MAP[s]);
      if (el) el.className = 'pipeline-stage done';
    });
  }

  function formatStageName(stage) {
    return stage
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  function renderLogLines(lines) {
    dom.progressLog.innerHTML = '';
    lines.forEach(line => {
      const div = document.createElement('div');
      div.className = 'log-line';
      if (line.includes('✓') || line.includes('Complete') || line.includes('Done')) div.classList.add('success');
      if (line.includes('✗') || line.includes('Error') || line.includes('Failed')) div.classList.add('error');
      if (line.includes('conflict') || line.includes('Conflict') || line.includes('⚠')) div.classList.add('warning');
      div.textContent = line;
      dom.progressLog.appendChild(div);
    });
    dom.progressLog.scrollTop = dom.progressLog.scrollHeight;
  }

  function appendLogLine(text, type = '') {
    const div = document.createElement('div');
    div.className = `log-line ${type}`;
    div.textContent = text;
    dom.progressLog.appendChild(div);
    dom.progressLog.scrollTop = dom.progressLog.scrollHeight;
  }

  // ─── Results Handling & Rendering ──────────────────────────────────────
  async function fetchResults(runId) {
    try {
      const res = await fetch(ENDPOINTS.results(runId));
      if (!res.ok) throw new Error('Failed to retrieve screening results');
      const data = await res.json();

      state.screeningResult = data;
      showToast('Candidate shortlist & evidence report ready!', 'success');

      // Update badge count
      const count = data.ranked_list?.candidates?.length || 0;
      dom.badgeCandidateCount.textContent = count;

      // Populate views
      renderRankings(data);
      populateCompareDropdowns(data);
      renderGapReport(data.gap_report);

      // Render new feasibility views
      renderFeasibilityPanel(data.feasibility_report);
      renderTradeOffShortlist(data.tradeoff_shortlist);

      // Save to localStorage so results persist across any reloads
      saveCurrentState();

      // Automatically transition to Rankings view to display results immediately
      setTimeout(() => {
        switchPage('rankings');
      }, 700);

    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  // ─── Feasibility Panel Renderer ──────────────────────────────────────────
  function renderFeasibilityPanel(report) {
    if (!report || !dom.feasibilityPanel) return;

    const sev = (report.overall_severity || 'NONE').toUpperCase();
    const icon = report.severity_icon || '✅';
    const panel = dom.feasibilityPanel;

    // Show panel
    panel.classList.remove('hidden', 'severity-none', 'severity-moderate', 'severity-high');
    panel.classList.add(`severity-${sev.toLowerCase()}`);

    // Icon & severity badge
    dom.feasibilityIcon.textContent = icon;
    dom.feasibilitySeverityBadge.textContent = sev === 'NONE' ? 'NO CONFLICT'
      : sev === 'MODERATE' ? '⚠ MODERATE CONFLICT'
        : '🚨 HIGH CONFLICT';
    dom.feasibilitySeverityBadge.className = `conflict-badge badge-${sev.toLowerCase()}`;

    // Subtitle
    const n = (report.conflicts || []).length;
    dom.feasibilitySubtitle.textContent = sev === 'NONE'
      ? 'Requirements appear consistent'
      : `${n} requirement conflict${n !== 1 ? 's' : ''} detected`;

    // Conflict rows
    const conflicts = report.conflicts || [];
    if (conflicts.length > 0 && dom.feasibilityConflicts) {
      dom.feasibilityConflicts.classList.remove('hidden');
      dom.feasibilityConflictList.innerHTML = conflicts.map(c => {
        const rowSev = (c.severity || 'moderate').toLowerCase();
        const rowIcon = rowSev === 'high' ? '🚨' : '⚠️';
        return `
          <div class="conflict-row severity-${rowSev}">
            <span class="conflict-row-icon">${rowIcon}</span>
            <div class="conflict-row-body">
              <div class="conflict-reqs">
                ${escapeHtml(c.requirement_a)} — ${escapeHtml(c.requirement_b)}
              </div>
              <div class="conflict-explanation">${escapeHtml(c.explanation)}</div>
            </div>
          </div>
        `;
      }).join('');
    }

    // Advisory text
    if (dom.feasibilityAdvisory) {
      dom.feasibilityAdvisory.textContent = report.recruiter_advisory || '';
    }
  }

  function renderCoverageBars(coverage) {
    if (!coverage || !dom.coverageBarsContainer) return;

    const total = coverage.total_candidates || 0;
    const entries = coverage.entries || [];
    if (!entries.length) return;

    // Show candidate count
    if (dom.coverageCandidateCount) {
      dom.coverageCandidateCount.textContent = `${total} candidate${total !== 1 ? 's' : ''} evaluated`;
    }

    dom.coverageBarsContainer.innerHTML = entries.map(e => {
      const pct = e.percentage || 0;
      let fillClass = pct >= 70 ? 'adequate' : pct >= 40 ? 'moderate' : 'low';
      return `
        <div class="coverage-bar-row">
          <span class="coverage-bar-label" title="${escapeHtml(e.requirement)}">${escapeHtml(e.requirement)}</span>
          <div class="coverage-bar-track">
            <div class="coverage-bar-fill ${fillClass}" style="width:0%" data-pct="${pct}"></div>
          </div>
          <span class="coverage-bar-pct">${pct.toFixed(0)}%</span>
          <span class="coverage-bar-count">${e.count}/${e.total}</span>
        </div>
      `;
    }).join('');

    // Animate bars after insertion
    requestAnimationFrame(() => {
      dom.coverageBarsContainer.querySelectorAll('.coverage-bar-fill').forEach(bar => {
        bar.style.width = bar.dataset.pct + '%';
      });
    });

    // Intersection row
    const ic = coverage.intersection_count || 0;
    if (dom.coverageIntersection) {
      dom.coverageIntersection.classList.remove('hidden');
      dom.coverageIntersection.classList.toggle('match-exists', ic > 0);
      dom.intersectionIcon.textContent = ic > 0 ? '✅' : '⚠️';
      dom.intersectionCountText.textContent = `${ic} / ${total}`;
    }
  }

  // ─── Trade-Off Shortlist Renderer ─────────────────────────────────────────
  function renderTradeOffShortlist(shortlist) {
    if (!shortlist || !dom.tradeoffShortlistSection) return;

    const hasPerfect = shortlist.has_perfect_match;
    const allCands = [...(shortlist.perfect_matches || []),
    ...(shortlist.compromise_candidates || [])];

    // Render coverage bars (always, if coverage data present)
    if (shortlist.coverage) {
      renderCoverageBars(shortlist.coverage);
    }

    // Only show the trade-off section when there are NO perfect matches
    if (hasPerfect || allCands.length === 0) {
      dom.tradeoffShortlistSection.classList.add('hidden');
      return;
    }

    dom.tradeoffShortlistSection.classList.remove('hidden');

    const medals = ['🥇', '🥈', '🥉'];
    const labels = ['Closest Overall Fit', 'Strong Alternative', 'Specialized Alternative', 'Alternative'];

    dom.tradeoffCardsContainer.innerHTML = allCands.map((tc, idx) => {
      const medal = medals[idx] || `#${tc.rank}`;
      const label = labels[Math.min(idx, labels.length - 1)];

      const metTags = (tc.met || []).map(r =>
        `<span class="req-tag req-met">✅ ${escapeHtml(r)}</span>`).join('');
      const partialTags = (tc.partial || []).map(r =>
        `<span class="req-tag req-partial">🟡 ${escapeHtml(r)}</span>`).join('');
      const unmetTags = (tc.unmet || []).map(r =>
        `<span class="req-tag req-unmet">❌ ${escapeHtml(r)}</span>`).join('');

      const narrativeHtml = tc.tradeoff_note
        ? `<div class="tradeoff-narrative">${escapeHtml(tc.tradeoff_note)}</div>`
        : '';

      return `
        <div class="tradeoff-card" style="animation-delay:${idx * 0.08}s">
          <div class="tradeoff-card-header">
            <span class="tradeoff-rank-medal">${medal}</span>
            <div>
              <div class="tradeoff-candidate-name">${escapeHtml(tc.candidate_name)}</div>
              <div class="tradeoff-compromise-label">${label} · ${tc.unmet_count} unmet requirement${tc.unmet_count !== 1 ? 's' : ''}</div>
            </div>
            <span class="tradeoff-score-badge">${Math.round(tc.total_score)}%</span>
          </div>
          <div class="tradeoff-requirements">
            ${metTags}${partialTags}${unmetTags}
          </div>
          ${narrativeHtml}
        </div>
      `;
    }).join('');
  }

  // ─── Render Rankings View ──────────────────────────────────────────────
  function renderRankings(result) {
    const candidates = result.ranked_list?.candidates || [];

    // Stats Strip
    dom.statTotalCandidates.textContent = candidates.length;
    if (candidates.length > 0) {
      const scores = candidates.map(c => c.score.total_score);
      const top = Math.max(...scores);
      const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
      dom.statTopScore.textContent = `${Math.round(top)}%`;
      dom.statAvgScore.textContent = `${Math.round(avg)}%`;

      let groundedCount = 0;
      candidates.forEach(c => {
        (c.score.skill_breakdown || []).forEach(v => {
          if (v.status === 'STRONGLY_SUPPORTED' || v.status === 'PARTIALLY_SUPPORTED') {
            groundedCount++;
          }
        });
      });
      dom.statVerifiedClaims.textContent = groundedCount;
    }

    renderCandidateCards(candidates);
  }

  function renderCandidateCards(candidates) {
    dom.rankingsContainer.innerHTML = '';

    if (candidates.length === 0) {
      dom.rankingsContainer.innerHTML = `
        <div class="card text-center text-muted" style="padding: 48px 24px;">
          No candidates matched the current search criteria.
        </div>
      `;
      return;
    }

    candidates.forEach(ranked => {
      const s = ranked.score;
      const card = document.createElement('div');
      card.className = 'candidate-card';
      card.setAttribute('data-id', s.candidate_id);

      // Score status class
      let scoreClass = 'score-mid';
      if (s.total_score >= 75) scoreClass = 'score-high';
      else if (s.total_score < 50) scoreClass = 'score-low';

      // Skills chips preview
      const chipsHtml = (s.skill_breakdown || []).slice(0, 6).map(v => {
        let chipClass = 'strong';
        if (v.status === 'PARTIALLY_SUPPORTED') chipClass = 'partial';
        else if (v.status === 'UNSUPPORTED' || v.status === 'NOT_MENTIONED') chipClass = 'missing';

        return `<span class="skill-chip ${chipClass}">${escapeHtml(v.jd_skill)}</span>`;
      }).join('');

      card.innerHTML = `
        <div class="candidate-rank">#${ranked.rank}</div>
        <div class="candidate-info">
          <div class="candidate-name">${escapeHtml(s.candidate_name)}</div>
          <div class="candidate-meta">
            ${s.relevant_years ? s.relevant_years.toFixed(1) + ' yrs exp' : 'Experience detected'}
            ${s.education_match ? ' · Degree Matched' : ''}
          </div>
          <div class="candidate-skills">${chipsHtml}</div>
        </div>
        <div class="flex items-center gap-3">
          <div class="score-ring ${scoreClass}">
            <span>${Math.round(s.total_score)}</span>
            <span class="score-ring-label">MATCH</span>
          </div>
          <button class="btn btn-secondary btn-sm btn-evidence-trigger" style="padding: 6px 12px; font-weight: 600;">
            Evidence →
          </button>
          <button class="btn-candidate-delete" title="Remove candidate from shortlist" data-id="${s.candidate_id}">
            🗑️
          </button>
        </div>
      `;

      // Trigger evidence detail on button click
      const evBtn = card.querySelector('.btn-evidence-trigger');
      if (evBtn) {
        evBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          openCandidateDetail(s.candidate_id);
        });
      }

      // Trigger candidate deletion
      const delBtn = card.querySelector('.btn-candidate-delete');
      if (delBtn) {
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          e.preventDefault();
          await removeCandidate(s.candidate_id, s.candidate_name, card);
        });
      }

      card.addEventListener('click', () => {
        openCandidateDetail(s.candidate_id);
      });

      dom.rankingsContainer.appendChild(card);
    });
  }

  async function removeCandidate(candidateId, candidateName, cardElement) {
    if (!confirm(`Remove ${candidateName} from candidate rankings?`)) return;

    try {
      if (cardElement) cardElement.style.opacity = '0.3';

      await fetch(ENDPOINTS.deleteCandidate, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_id: candidateId,
          session_id: state.sessionId,
          run_id: state.runId,
        }),
      });

      if (state.screeningResult?.ranked_list?.candidates) {
        state.screeningResult.ranked_list.candidates = state.screeningResult.ranked_list.candidates
          .filter(c => c.score.candidate_id !== candidateId)
          .map((c, i) => {
            c.rank = i + 1;
            return c;
          });

        if (state.screeningResult.candidates) {
          state.screeningResult.candidates = state.screeningResult.candidates
            .filter(c => c.candidate_id !== candidateId);
        }

        const count = state.screeningResult.ranked_list.candidates.length;
        if (dom.badgeCandidateCount) dom.badgeCandidateCount.textContent = count;

        renderRankings(state.screeningResult);
        populateCompareDropdowns(state.screeningResult);
        saveCurrentState();

        if (state.selectedCandidateId === candidateId) {
          state.selectedCandidateId = null;
          if (dom.detailContentArea) dom.detailContentArea.classList.add('hidden');
          if (dom.detailEmptyState) dom.detailEmptyState.classList.remove('hidden');
        }
      }

      showToast(`Removed candidate: ${candidateName}`, 'info');
    } catch (err) {
      showToast(`Failed to remove candidate: ${err.message}`, 'error');
      if (cardElement) cardElement.style.opacity = '1';
    }
  }

  // Clear Results Handler
  if (dom.btnClearResults) {
    dom.btnClearResults.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (!confirm('Are you sure you want to clear all screening results?')) return;

      try {
        await fetch(ENDPOINTS.clearResults, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: state.sessionId,
            run_id: state.runId,
          }),
        });

        state.screeningResult = null;
        state.runId = null;
        state.selectedCandidateId = null;
        localStorage.removeItem('recruitscreen_saved_state');

        if (dom.badgeCandidateCount) dom.badgeCandidateCount.textContent = '0';
        dom.statTotalCandidates.textContent = '0';
        dom.statTopScore.textContent = '0%';
        dom.statAvgScore.textContent = '0%';
        dom.statVerifiedClaims.textContent = '0';

        dom.rankingsContainer.innerHTML = `
          <div class="card text-center text-muted" style="padding: 48px 24px;">
            Screening results cleared. Upload documents in the Workspace tab and start screening.
          </div>
        `;

        if (dom.detailContentArea) dom.detailContentArea.classList.add('hidden');
        if (dom.detailEmptyState) dom.detailEmptyState.classList.remove('hidden');
        if (dom.pipelineCard) dom.pipelineCard.classList.add('hidden');

        if (dom.compareSelectA) dom.compareSelectA.innerHTML = '<option value="">Select Candidate A...</option>';
        if (dom.compareSelectB) dom.compareSelectB.innerHTML = '<option value="">Select Candidate B...</option>';
        if (dom.compareNarrativeCard) dom.compareNarrativeCard.classList.add('hidden');
        if (dom.compareTableContainer) dom.compareTableContainer.classList.add('hidden');
        if (dom.feasibilityPanel) dom.feasibilityPanel.classList.add('hidden');
        if (dom.tradeoffShortlistSection) dom.tradeoffShortlistSection.classList.add('hidden');

        showToast('Screening results cleared', 'info');
      } catch (err) {
        showToast(`Failed to clear results: ${err.message}`, 'error');
      }
    });
  }

  // Rankings Filter & Sort
  function applyRankingsFilterAndSort() {
    if (!state.screeningResult || !state.screeningResult.ranked_list) return;

    let list = [...state.screeningResult.ranked_list.candidates];
    const query = (dom.filterCandidateInput.value || '').toLowerCase().trim();
    const sort = dom.sortCandidateSelect.value;

    if (query) {
      list = list.filter(c => {
        const name = (c.score.candidate_name || '').toLowerCase();
        const skills = (c.score.skill_breakdown || []).map(s => s.jd_skill.toLowerCase()).join(' ');
        return name.includes(query) || skills.includes(query);
      });
    }

    if (sort === 'evidence') {
      list.sort((a, b) => b.score.component_scores.evidence_strength - a.score.component_scores.evidence_strength);
    } else if (sort === 'experience') {
      list.sort((a, b) => (b.score.relevant_years || 0) - (a.score.relevant_years || 0));
    } else {
      list.sort((a, b) => a.rank - b.rank);
    }

    renderCandidateCards(list);
  }

  dom.filterCandidateInput.addEventListener('input', applyRankingsFilterAndSort);
  dom.sortCandidateSelect.addEventListener('change', applyRankingsFilterAndSort);

  // ─── Render Candidate Detail View ──────────────────────────────────────
  async function openCandidateDetail(candidateId) {
    let ranked = null;

    if (state.screeningResult && state.screeningResult.ranked_list && Array.isArray(state.screeningResult.ranked_list.candidates)) {
      ranked = state.screeningResult.ranked_list.candidates.find(
        c => c.score && c.score.candidate_id === candidateId
      );
    }

    // Remote fallback if not found in current client state
    if (!ranked) {
      try {
        const url = `${ENDPOINTS.candidate(candidateId)}?run_id=${encodeURIComponent(state.runId || '')}`;
        const res = await fetch(url);
        if (res.ok) {
          ranked = await res.json();
        }
      } catch (err) {
        console.warn('Could not fetch candidate detail remotely:', err);
      }
    }

    if (!ranked || !ranked.score) {
      showToast('Could not load candidate evidence details', 'error');
      return;
    }

    state.selectedCandidateId = candidateId;
    const s = ranked.score;

    const expYears = (s.profile && s.profile.total_experience_years != null)
      ? s.profile.total_experience_years
      : (s.relevant_years || 0);

    if (dom.detailEmptyState) dom.detailEmptyState.classList.add('hidden');
    if (dom.detailContentArea) dom.detailContentArea.classList.remove('hidden');

    if (dom.detailCandidateName) dom.detailCandidateName.textContent = `${s.candidate_name || 'Candidate'} — Evidence Profile`;
    if (dom.detailHeaderName) dom.detailHeaderName.textContent = s.candidate_name || 'Candidate';
    const candidateGithubUrl = (s.profile && s.profile.github_url) || s.github_url || '';

    if (dom.detailHeaderMeta) {
      let metaStr = `Rank #${ranked.rank} · ${expYears ? expYears.toFixed(1) + ' Years Experience' : 'Experience detected'} · Match Score: ${Math.round(s.total_score || 0)}/100`;
      if (candidateGithubUrl) {
        const ghDisplay = candidateGithubUrl.replace(/^https?:\/\/(www\.)?github\.com\/?/, '@').replace(/\/$/, '');
        dom.detailHeaderMeta.innerHTML = `<span>${escapeHtml(metaStr)}</span> · <a href="${escapeHtml(candidateGithubUrl)}" target="_blank" rel="noopener noreferrer" class="candidate-github-meta-link font-mono" title="Open Candidate GitHub Profile"><span>🐙</span> <span>${escapeHtml(ghDisplay)}</span></a>`;
      } else {
        dom.detailHeaderMeta.textContent = metaStr;
      }
    }
    if (dom.detailTotalScore) dom.detailTotalScore.textContent = Math.round(s.total_score || 0);

    if (dom.detailScoreRing) {
      let scoreClass = 'score-mid';
      if ((s.total_score || 0) >= 75) scoreClass = 'score-high';
      else if ((s.total_score || 0) < 50) scoreClass = 'score-low';
      dom.detailScoreRing.className = `score-ring ${scoreClass}`;
    }

    if (dom.detailTradeoffNote) {
      if (ranked.tradeoff_note) {
        dom.detailTradeoffNote.textContent = `Executive Note: "${ranked.tradeoff_note}"`;
        dom.detailTradeoffNote.style.display = 'block';
      } else {
        dom.detailTradeoffNote.textContent = '';
        dom.detailTradeoffNote.style.display = 'none';
      }
    }

    // Component scores
    const compMap = {};
    if (Array.isArray(s.component_scores)) {
      s.component_scores.forEach(c => {
        const val = c.weighted != null ? (c.weighted <= 1.0 ? c.weighted * 100 : c.weighted) : (c.score != null ? c.score * (c.weight || 1) * (c.score <= 1.0 ? 100 : 1) : 0);
        if (c.name === 'Required Skills') compMap.required_skills = val;
        else if (c.name === 'Relevant Experience') compMap.relevant_experience = val;
        else if (c.name === 'Evidence Strength') compMap.evidence_strength = val;
        else if (c.name === 'Preferred Skills') compMap.preferred_skills = val;
        else if (c.name === 'Education') compMap.education = val;
      });
    } else if (s.component_scores && typeof s.component_scores === 'object') {
      Object.assign(compMap, s.component_scores);
    }

    if (dom.scoreCompSkills) dom.scoreCompSkills.textContent = `${(compMap.required_skills || 0).toFixed(1)} / 40`;
    if (dom.scoreCompExp) dom.scoreCompExp.textContent = `${(compMap.relevant_experience || 0).toFixed(1)} / 25`;
    if (dom.scoreCompEvidence) dom.scoreCompEvidence.textContent = `${(compMap.evidence_strength || 0).toFixed(1)} / 20`;
    const otherScore = (compMap.preferred_skills || 0) + (compMap.education || 0);
    if (dom.scoreCompOther) dom.scoreCompOther.textContent = `${otherScore.toFixed(1)} / 15`;

    // Render skill verifications
    renderSkillVerifications(s.skill_breakdown || [], candidateGithubUrl);

    switchPage('detail');
  }

  function renderSkillVerifications(verifications, candidateGithubUrl = '') {
    dom.detailSkillsList.innerHTML = '';

    // Update count badge & dynamic summary chips in header
    const skillCountEl = document.getElementById('detail-skill-count');
    if (skillCountEl) {
      skillCountEl.textContent = `${verifications ? verifications.length : 0} Skills`;
    }

    const summaryChipsEl = document.getElementById('detail-skills-summary-chips');
    if (summaryChipsEl && verifications && verifications.length > 0) {
      const supportedCount = verifications.filter(v => v.status === 'STRONGLY_SUPPORTED' || v.status === 'PARTIALLY_SUPPORTED').length;
      const ghCount = verifications.filter(v => v.github_result && (v.github_result.status === 'SUPPORTED' || v.github_result.status === 'PARTIAL')).length;
      summaryChipsEl.innerHTML = `
        <span class="badge" style="background: var(--emerald-dim); color: var(--emerald); border: 1px solid rgba(16,185,129,0.3); font-size: 0.7rem; padding: 2px 8px; border-radius: 12px;">
          ✓ ${supportedCount}/${verifications.length} Resume Grounded
        </span>
        ${candidateGithubUrl ? `
          <span class="badge" style="background: rgba(99,102,241,0.12); color: var(--accent-light); border: 1px solid rgba(99,102,241,0.28); font-size: 0.7rem; padding: 2px 8px; border-radius: 12px;">
            🐙 ${ghCount}/${verifications.length} GitHub Corroborated
          </span>
        ` : ''}
      `;
    } else if (summaryChipsEl) {
      summaryChipsEl.innerHTML = '';
    }

    if (!verifications || verifications.length === 0) {
      dom.detailSkillsList.innerHTML = `
        <div class="card p-6 text-center text-muted" style="background: rgba(255,255,255,0.02); border: 1px dashed var(--border);">
          <div style="font-size: 1.5rem; margin-bottom: 6px;">📋</div>
          <div class="text-sm font-bold text-primary">No verified skills recorded</div>
          <div class="text-xs text-muted mt-1">No skill verification breakdown was found for this candidate.</div>
        </div>
      `;
      return;
    }

    verifications.forEach((v, vIdx) => {
      const card = document.createElement('div');
      card.className = 'skill-card';

      const badgeInfo = getEvidenceBadge(v.status);

      // ── 1. Resume Grounding Column ──────────────────────────
      let passageHtml = '';
      let topConfidenceTag = '';

      if (v.evidence && Array.isArray(v.evidence) && v.evidence.length > 0) {
        const topEv = v.evidence[0];
        const topScore = topEv.similarity_score != null ? topEv.similarity_score : 0.8;
        const topPct = Math.round(topScore <= 1 ? topScore * 100 : topScore);
        const confClass = topPct >= 80 ? 'high' : topPct >= 60 ? 'mid' : '';
        topConfidenceTag = `<span class="confidence-pill ${confClass}">${topPct}% Match</span>`;

        passageHtml = v.evidence.map((e, eIdx) => {
          const rawText = (e.chunk_text || '').trim();
          const isLong = rawText.length > 130;
          const boxId = `ev-quote-${vIdx}-${eIdx}`;
          return `
            <div class="quote-item ${eIdx > 0 ? 'mt-2 pt-2' : ''}" ${eIdx > 0 ? 'style="border-top: 1px dashed rgba(255,255,255,0.05);"' : ''}>
              <div class="evidence-quote-box ${isLong ? 'clamp' : ''}" id="${boxId}">
                "${escapeHtml(rawText)}"
              </div>
              <div class="flex items-center justify-between mt-1 px-1">
                ${isLong ? `
                  <button type="button" class="btn-quote-toggle" data-target="${boxId}">
                    <span>Show full passage</span> ▾
                  </button>
                ` : '<span></span>'}
                ${e.source_section ? `<span class="source-tag">Source: ${escapeHtml(e.source_section)}</span>` : ''}
              </div>
            </div>
          `;
        }).join('');
      } else {
        passageHtml = `
          <div class="evidence-empty-box neutral">
            <span class="empty-icon">📄</span>
            <div>
              <div class="empty-title">No Direct Resume Citation</div>
              <div class="empty-desc">No specific textual excerpt in the resume met the semantic threshold for this skill.</div>
            </div>
          </div>
        `;
      }

      // ── 2. GitHub Evidence Column ───────────────────────────
      const gh = v.github_result;
      let githubHtml = '';
      let ghBadgeHtml = '';
      let reposBadgeTag = '';

      if (gh) {
        const ghStatus  = (gh.status || 'UNVERIFIED').toUpperCase();
        const ghLabel   = gh.status_label || (ghStatus === 'SUPPORTED' ? 'Externally corroborated' : ghStatus === 'PARTIAL' ? 'Partial GitHub evidence' : 'Not externally corroborated');
        const ghIcon    = ghStatus === 'SUPPORTED' ? '🟢' : ghStatus === 'PARTIAL' ? '🟡' : '⚪';
        const badgeClass = ghStatus === 'SUPPORTED' ? 'supported' : ghStatus === 'PARTIAL' ? 'partial' : 'unverified';

        ghBadgeHtml = `
          <span class="github-badge ${badgeClass}" title="GitHub Verification: ${escapeHtml(ghLabel)}">
            <span>${ghIcon}</span>
            <span>${escapeHtml(ghLabel)}</span>
          </span>
        `;

        const repos = gh.evidence_repos || [];
        if (repos.length > 0) {
          reposBadgeTag = `<span class="confidence-pill high">${repos.length} Repo${repos.length > 1 ? 's' : ''}</span>`;
        }

        const repoChips = repos.slice(0, 6).map(r => {
          const repoUrl = candidateGithubUrl ? `${candidateGithubUrl.replace(/\/$/, '')}/${encodeURIComponent(r)}` : null;
          if (repoUrl) {
            return `<a href="${escapeHtml(repoUrl)}" target="_blank" rel="noopener noreferrer" class="github-chip" title="View repository ${escapeHtml(r)} on GitHub">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
              <span>${escapeHtml(r)}</span>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.6;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
            </a>`;
          }
          return `<span class="github-chip">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
            <span>${escapeHtml(r)}</span>
          </span>`;
        }).join('');

        if (ghStatus === 'UNVERIFIED' && repos.length === 0) {
          githubHtml = `
            <div class="evidence-empty-box neutral">
              <span class="empty-icon">⚪</span>
              <div>
                <div class="empty-title">Not Externally Corroborated</div>
                <div class="empty-desc">${escapeHtml(gh.reasoning || 'No public repository code detected for this skill. Absence of public code does not imply lack of skill.')}</div>
              </div>
            </div>
          `;
        } else {
          githubHtml = `
            ${repoChips ? `
              <div class="github-repos-block">
                <div class="repos-title-tag">
                  <span>Corroborating Repositories</span>
                </div>
                <div class="github-repos-list">${repoChips}</div>
              </div>
            ` : ''}
            ${gh.reasoning ? `
              <div class="github-reasoning-box">
                <div class="reasoning-header">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                  <span>Corroboration Analysis</span>
                </div>
                <div class="reasoning-body">${escapeHtml(gh.reasoning)}</div>
              </div>
            ` : ''}
          `;
        }
      } else if (!candidateGithubUrl) {
        ghBadgeHtml = `<span class="github-badge no-github">No GitHub profile</span>`;
        githubHtml = `
          <div class="evidence-empty-box neutral">
            <span class="empty-icon">🐙</span>
            <div>
              <div class="empty-title">No GitHub Profile Linked</div>
              <div class="empty-desc">Candidate did not provide a public GitHub URL with their application.</div>
            </div>
          </div>
        `;
      } else {
        ghBadgeHtml = `<span class="github-badge unverified"><span>⚪</span><span>Not corroborated</span></span>`;
        githubHtml = `
          <div class="evidence-empty-box neutral">
            <span class="empty-icon">⚪</span>
            <div>
              <div class="empty-title">Corroboration Pending</div>
              <div class="empty-desc">GitHub repository cross-check was not completed for this skill.</div>
            </div>
          </div>
        `;
      }

      // ── Assemble Card HTML ─────────────────────────────────
      card.innerHTML = `
        <div class="skill-card-top">
          <div class="skill-card-info">
            <div class="skill-card-heading">
              <h4 class="skill-card-name">${escapeHtml(v.jd_skill || 'Skill')}</h4>
            </div>
            <div class="skill-card-desc">${escapeHtml(v.explanation || 'Verified via semantic matching and evidence checks.')}</div>
            ${v.claim && v.claim.statement ? `
              <div class="skill-claim-callout">
                <span class="claim-tag">Candidate Claim:</span>
                <span class="claim-quote">"${escapeHtml(v.claim.statement)}"</span>
              </div>
            ` : ''}
          </div>
          <div class="skill-card-badges">
            <span class="evidence-badge ${badgeInfo.className}" title="Resume verification: ${badgeInfo.label}">
              <span>${badgeInfo.icon}</span>
              <span>${badgeInfo.label}</span>
            </span>
            ${ghBadgeHtml}
          </div>
        </div>

        <div class="skill-dual-grid">
          <div class="evidence-panel resume-panel">
            <div class="evidence-panel-header">
              <div class="evidence-panel-title">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                <span>Grounded Resume Evidence</span>
              </div>
              ${topConfidenceTag}
            </div>
            <div class="evidence-panel-body">
              ${passageHtml}
            </div>
          </div>

          <div class="evidence-panel github-panel">
            <div class="evidence-panel-header">
              <div class="evidence-panel-title">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                <span>GitHub Repository Evidence</span>
              </div>
              ${reposBadgeTag}
            </div>
            <div class="evidence-panel-body">
              ${githubHtml}
            </div>
          </div>
        </div>
      `;

      // Attach quote toggle events
      card.querySelectorAll('.btn-quote-toggle').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const targetId = btn.getAttribute('data-target');
          const box = document.getElementById(targetId);
          if (box) {
            const isClamped = box.classList.contains('clamp');
            if (isClamped) {
              box.classList.remove('clamp');
              box.classList.add('expanded');
              btn.innerHTML = '<span>Collapse passage</span> ▴';
            } else {
              box.classList.remove('expanded');
              box.classList.add('clamp');
              btn.innerHTML = '<span>Show full passage</span> ▾';
            }
          }
        });
      });

      dom.detailSkillsList.appendChild(card);
    });
  }


  function getEvidenceBadge(status) {
    switch (status) {
      case 'STRONGLY_SUPPORTED':
        return { className: 'badge-strong', label: 'Strong Evidence', icon: '●' };
      case 'PARTIALLY_SUPPORTED':
        return { className: 'badge-partial', label: 'Partial Support', icon: '◐' };
      case 'UNSUPPORTED':
        return { className: 'badge-unsupported', label: 'Unsupported Claim', icon: '○' };
      case 'NOT_MENTIONED':
      default:
        return { className: 'badge-missing', label: 'Not Mentioned', icon: '✕' };
    }
  }

  // ─── Compare View ──────────────────────────────────────────────────────
  function populateCompareDropdowns(result) {
    const candidates = result.ranked_list?.candidates || [];
    dom.compareSelectA.innerHTML = '<option value="">Select Candidate A...</option>';
    dom.compareSelectB.innerHTML = '<option value="">Select Candidate B...</option>';

    candidates.forEach(ranked => {
      const s = ranked.score;
      const optA = document.createElement('option');
      optA.value = s.candidate_id;
      optA.textContent = `#${ranked.rank} - ${s.candidate_name} (${Math.round(s.total_score)}%)`;
      dom.compareSelectA.appendChild(optA);

      const optB = document.createElement('option');
      optB.value = s.candidate_id;
      optB.textContent = `#${ranked.rank} - ${s.candidate_name} (${Math.round(s.total_score)}%)`;
      dom.compareSelectB.appendChild(optB);
    });

    if (candidates.length >= 2) {
      dom.compareSelectA.selectedIndex = 1;
      dom.compareSelectB.selectedIndex = 2;
      dom.btnRunCompare.disabled = false;
    }
  }

  function checkCompareInputs() {
    const a = dom.compareSelectA.value;
    const b = dom.compareSelectB.value;
    dom.btnRunCompare.disabled = !(a && b && a !== b);
  }

  dom.compareSelectA.addEventListener('change', checkCompareInputs);
  dom.compareSelectB.addEventListener('change', checkCompareInputs);

  dom.btnRunCompare.addEventListener('click', async () => {
    const idA = dom.compareSelectA.value;
    const idB = dom.compareSelectB.value;
    if (!idA || !idB || !state.runId) return;

    dom.btnRunCompare.disabled = true;
    showToast('Generating AI trade-off comparison...', 'info');

    try {
      const res = await fetch(ENDPOINTS.compare, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: state.runId,
          candidate_a: idA,
          candidate_b: idB,
        }),
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.error || 'Failed to generate comparison');

      renderComparisonResults(data);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      dom.btnRunCompare.disabled = false;
    }
  });

  function renderComparisonResults(data) {
    dom.compareNarrativeCard.classList.remove('hidden');
    dom.compareTableContainer.classList.remove('hidden');

    dom.compareNarrativeText.textContent = data.narrative || 'Detailed comparison generated.';
    dom.compareWinnerBadge.textContent = data.winner ? `Favored: ${data.winner}` : '';

    // Render Side-by-Side Grid
    dom.compareGrid.innerHTML = `
      <div class="compare-header">Metric / Skill</div>
      <div class="compare-header">${escapeHtml(data.candidate_a_name || 'Candidate A')}</div>
      <div class="compare-header">${escapeHtml(data.candidate_b_name || 'Candidate B')}</div>

      <div class="compare-cell skill-label">Overall Match Score</div>
      <div class="compare-cell font-mono font-bold">${Math.round(data.candidate_a_score || 0)} / 100</div>
      <div class="compare-cell font-mono font-bold">${Math.round(data.candidate_b_score || 0)} / 100</div>

      <div class="compare-cell skill-label">Experience</div>
      <div class="compare-cell">${(data.candidate_a_exp || 0).toFixed(1)} Years</div>
      <div class="compare-cell">${(data.candidate_b_exp || 0).toFixed(1)} Years</div>
    `;

    // Skill breakdown rows
    if (data.skill_comparison && Array.isArray(data.skill_comparison)) {
      data.skill_comparison.forEach(sc => {
        const aStatus = sc.a_status || 'NOT_MENTIONED';
        const bStatus = sc.b_status || 'NOT_MENTIONED';

        const rowHtml = `
          <div class="compare-cell skill-label">${escapeHtml(sc.skill)}</div>
          <div class="compare-cell ${sc.favors === 'A' ? 'winner' : ''}">
            <span class="evidence-badge ${getEvidenceBadge(aStatus).className}">${getEvidenceBadge(aStatus).label}</span>
          </div>
          <div class="compare-cell ${sc.favors === 'B' ? 'winner' : ''}">
            <span class="evidence-badge ${getEvidenceBadge(bStatus).className}">${getEvidenceBadge(bStatus).label}</span>
          </div>
        `;
        dom.compareGrid.insertAdjacentHTML('beforeend', rowHtml);
      });
    }
  }

  // ─── Gap Report View ───────────────────────────────────────────────────
  function renderGapReport(gapReport) {
    if (!gapReport || !gapReport.skill_gaps) {
      dom.gapRowsContainer.innerHTML = '<div class="text-muted p-4 text-center">No gap data available.</div>';
      return;
    }

    dom.gapRowsContainer.innerHTML = '';

    gapReport.skill_gaps.forEach(g => {
      const row = document.createElement('div');
      row.className = 'gap-row';

      const pct = Math.round(g.percentage != null ? g.percentage : (g.coverage_percentage || 0));
      let riskClass = 'risk-adequate';
      let barClass = 'gap-bar-adequate';

      if (g.risk_level === 'HIGH_RISK') {
        riskClass = 'risk-high';
        barClass = 'gap-bar-high-risk';
      } else if (g.risk_level === 'MODERATE') {
        riskClass = 'risk-moderate';
        barClass = 'gap-bar-moderate';
      }

      row.innerHTML = `
        <div class="gap-skill-name">${escapeHtml(g.skill)}</div>
        <div class="gap-bar-wrap">
          <div class="gap-bar-fill ${barClass}" style="width: ${pct}%;"></div>
        </div>
        <div class="gap-count">${g.count_with_skill} / ${g.total_candidates} (${pct}%)</div>
        <div>
          <span class="gap-risk-badge ${riskClass}">${formatRiskLevel(g.risk_level)}</span>
        </div>
      `;

      dom.gapRowsContainer.appendChild(row);
    });
  }

  function formatRiskLevel(level) {
    switch (level) {
      case 'HIGH_RISK': return 'High Risk';
      case 'MODERATE': return 'Moderate';
      case 'ADEQUATE': return 'Adequate';
      default: return level;
    }
  }

  // ─── Recruiter Chat ────────────────────────────────────────────────────
  async function sendChatMessage(queryText = null) {
    const input = dom.chatInput;
    const content = (queryText || input.value || '').trim();
    if (!content) return;

    if (!queryText) input.value = '';

    // Add User Bubble
    appendChatBubble('user', content);
    state.chatMessages.push({ role: 'user', content });

    // Typing bubble
    const typingBubble = appendChatBubble('ai', 'Thinking and retrieving grounded evidence...');

    try {
      const res = await fetch(ENDPOINTS.chat, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: state.chatMessages,
          run_id: state.runId,
          session_id: state.sessionId,
        }),
      });
      const data = await res.json();

      if (!res.ok) throw new Error(data.error || 'Failed to get answer from AI');

      // Replace typing bubble content
      typingBubble.querySelector('.chat-bubble').innerHTML = formatMarkdown(data.content);
      state.chatMessages.push({ role: 'assistant', content: data.content });

      dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
    } catch (err) {
      typingBubble.querySelector('.chat-bubble').textContent = `[Chat Error] ${err.message}`;
    }
  }

  function appendChatBubble(role, text) {
    const msg = document.createElement('div');
    msg.className = `chat-message ${role}`;

    const isAi = role === 'ai';
    msg.innerHTML = `
      <div class="chat-avatar ${isAi ? 'avatar-ai' : 'avatar-user'}">${isAi ? '🤖' : '👤'}</div>
      <div class="chat-bubble ${isAi ? 'bubble-ai' : 'bubble-user'}">${escapeHtml(text)}</div>
    `;

    dom.chatMessages.appendChild(msg);
    dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
    return msg;
  }

  dom.btnChatSend.addEventListener('click', () => sendChatMessage());
  dom.chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // Suggestion chips
  document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-query');
      if (q) sendChatMessage(q);
    });
  });

  // ─── Utility Helpers ───────────────────────────────────────────────────
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatMarkdown(text) {
    if (!text) return '';
    let formatted = escapeHtml(text);
    // Bold
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Bullet points
    formatted = formatted.replace(/^\* (.*$)/gim, '<li>$1</li>');
    formatted = formatted.replace(/^- (.*$)/gim, '<li>$1</li>');
    // Wrap lists
    formatted = formatted.replace(/(<li>.*<\/li>)/s, '<ul style="margin: 8px 0; padding-left: 20px;">$1</ul>');
    // Newlines to br
    formatted = formatted.replace(/\n/g, '<br/>');
    return formatted;
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  // ─── State Persistence ──────────────────────────────────────────────────
  function saveCurrentState() {
    try {
      if (state.screeningResult) {
        localStorage.setItem('recruitscreen_saved_state', JSON.stringify({
          sessionId: state.sessionId,
          runId: state.runId,
          screeningResult: state.screeningResult,
          activeJobTitle: dom.activeJobTitle ? dom.activeJobTitle.textContent : '',
          activePage: state.activePage,
        }));
      }
    } catch (e) {
      console.warn('Could not save state to localStorage:', e);
    }
  }

  function restoreSavedState() {
    try {
      const raw = localStorage.getItem('recruitscreen_saved_state');
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved && saved.screeningResult) {
        state.screeningResult = saved.screeningResult;
        state.runId = saved.runId || state.runId;
        state.sessionId = saved.sessionId || state.sessionId;

        const count = saved.screeningResult.ranked_list?.candidates?.length || 0;
        if (dom.badgeCandidateCount) dom.badgeCandidateCount.textContent = count;

        if (saved.activeJobTitle && dom.activeJobIndicator) {
          dom.activeJobTitle.textContent = saved.activeJobTitle;
          dom.activeJobIndicator.style.display = 'flex';
        }

        renderRankings(saved.screeningResult);
        populateCompareDropdowns(saved.screeningResult);
        renderGapReport(saved.screeningResult.gap_report);
        renderFeasibilityPanel(saved.screeningResult.feasibility_report);
        renderTradeOffShortlist(saved.screeningResult.tradeoff_shortlist);

        if (saved.activePage && saved.activePage !== 'workspace') {
          switchPage(saved.activePage);
        }
        console.log('[RecruitScreen] Restored previous screening results from localStorage.');
      }
    } catch (e) {
      console.warn('Could not restore state from localStorage:', e);
    }
  }

  async function loadLatestResults() {
    try {
      const res = await fetch(ENDPOINTS.latest);
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.ranked_list && Array.isArray(data.ranked_list.candidates) && data.ranked_list.candidates.length > 0) {
        state.screeningResult = data;
        state.runId = data.session_id || state.runId;

        const count = data.ranked_list.candidates.length;
        if (dom.badgeCandidateCount) dom.badgeCandidateCount.textContent = count;

        if (data.jd_analysis && data.jd_analysis.role_title && dom.activeJobIndicator) {
          dom.activeJobTitle.textContent = data.jd_analysis.role_title;
          dom.activeJobIndicator.style.display = 'flex';
        }

        renderRankings(data);
        populateCompareDropdowns(data);
        renderGapReport(data.gap_report);
        renderFeasibilityPanel(data.feasibility_report);
        renderTradeOffShortlist(data.tradeoff_shortlist);
        saveCurrentState();

        // Switch to rankings view so user immediately sees results!
        switchPage('rankings');
        showToast(`Loaded ${count} ranked candidates`, 'success');
      }
    } catch (e) {
      console.warn('Could not load latest screening results from server:', e);
    }
  }

  // ─── Startup Initialization ────────────────────────────────────────────
  // Ensure video background autoplays smoothly
  const bgVideo = document.getElementById('bg-video');
  if (bgVideo) {
    bgVideo.muted = true;
    bgVideo.play().catch(() => {
      const startVideo = () => {
        bgVideo.play().catch(() => { });
        window.removeEventListener('click', startVideo);
        window.removeEventListener('keydown', startVideo);
      };
      window.addEventListener('click', startVideo, { once: true });
      window.addEventListener('keydown', startVideo, { once: true });
    });
  }

  restoreSavedState();
  loadLatestResults();
  checkSystemHealth();
  setInterval(checkSystemHealth, 5000);

})();

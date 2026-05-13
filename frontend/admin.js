'use strict';

const API_BASE = '';
const dom = {};
const state = {
  selectedUserId: '',
  selectedUsername: '',
  selectedSubmissionId: '',
};

function apiFetch(path, opts = {}) {
  return fetch(`${API_BASE}${path}`, { credentials: 'include', ...opts });
}

async function checkAdminAuth() {
  try {
    const resp = await apiFetch('/api/auth/me');
    if (!resp.ok) {
      window.location.replace('/');
      return null;
    }
    const user = await resp.json();
    if (!user.is_admin) {
      window.location.replace('/');
      return null;
    }
    return user;
  } catch {
    window.location.replace('/');
    return null;
  }
}

async function logout() {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch {
    // Redirect even if logout fails.
  }
  window.location.replace('/');
}

async function loadUsers() {
  dom.usersTableContainer.innerHTML = '<p class="loading-msg">Loading users...</p>';
  dom.tableError.hidden = true;

  try {
    const resp = await apiFetch('/api/admin/users');
    if (!resp.ok) throw new Error('Failed to load users');
    const users = await resp.json();
    renderUsers(users);

    if (!state.selectedUserId) {
      return;
    }

    const selectedUser = users.find((user) => user.user_id === state.selectedUserId);
    if (!selectedUser) {
      resetSubmissionInspector('Select a user to inspect their feedback history.');
      return;
    }

    state.selectedUsername = selectedUser.username;
    await inspectUserSubmissions(state.selectedUserId, state.selectedUsername, true);
  } catch {
    dom.tableError.textContent = 'Could not load users. Please refresh the page.';
    dom.tableError.hidden = false;
    dom.usersTableContainer.innerHTML = '';
  }
}

function renderUsers(users) {
  if (users.length === 0) {
    dom.usersTableContainer.innerHTML = '<p class="no-data-msg">No users found.</p>';
    return;
  }

  const rows = users.map((user) => `
    <tr>
      <td>${escapeHtml(user.username)}</td>
      <td class="user-id-cell">
        <span title="${escapeHtml(user.user_id)}">${user.user_id.slice(0, 8)}...</span>
      </td>
      <td>${escapeHtml(user.cohort_id || '-')}</td>
      <td>
        ${user.is_admin
          ? '<span class="badge badge-admin">Admin</span>'
          : '<span class="badge badge-user">User</span>'}
      </td>
      <td>${formatDate(user.created_at)}</td>
      <td class="table-actions">
        <button
          class="btn btn-sm btn-outline inspect-user-btn"
          data-user-id="${escapeHtml(user.user_id)}"
          data-username="${escapeHtml(user.username)}"
          type="button">
          View Submissions
        </button>
        <button
          class="btn btn-sm btn-danger delete-user-btn"
          data-user-id="${escapeHtml(user.user_id)}"
          data-username="${escapeHtml(user.username)}"
          aria-label="Delete user ${escapeHtml(user.username)}"
          type="button">
          Delete
        </button>
      </td>
    </tr>
  `).join('');

  dom.usersTableContainer.innerHTML = `
    <div class="table-wrapper">
      <table class="users-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>User ID</th>
            <th>Cohort</th>
            <th>Role</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  dom.usersTableContainer.querySelectorAll('.delete-user-btn').forEach((btn) => {
    btn.addEventListener('click', () => deleteUser(btn.dataset.userId, btn.dataset.username));
  });

  dom.usersTableContainer.querySelectorAll('.inspect-user-btn').forEach((btn) => {
    btn.addEventListener('click', () => inspectUserSubmissions(btn.dataset.userId, btn.dataset.username));
  });
}

async function inspectUserSubmissions(userId, username, preserveDetail = false) {
  state.selectedUserId = userId;
  state.selectedUsername = username;

  dom.selectedUserLabel.textContent = `Showing submissions for ${username}.`;
  dom.refreshSubmissionsBtn.hidden = false;
  dom.submissionsError.hidden = true;
  dom.submissionsEmpty.hidden = true;
  dom.submissionsList.hidden = false;
  dom.submissionsList.innerHTML = '<p class="loading-msg">Loading submissions...</p>';

  if (!preserveDetail) {
    hideSubmissionDetail();
  }

  try {
    const resp = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/submissions`);
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || 'Failed to load submissions');
    }

    renderSubmissionList(data);
  } catch (error) {
    dom.submissionsList.innerHTML = '';
    dom.submissionsError.textContent = error.message || 'Could not load submissions.';
    dom.submissionsError.hidden = false;
  }
}

function renderSubmissionList(payload) {
  const submissions = payload.submissions || [];
  if (submissions.length === 0) {
    dom.submissionsList.hidden = true;
    dom.submissionsList.innerHTML = '';
    dom.submissionsEmpty.hidden = false;
    return;
  }

  dom.submissionsEmpty.hidden = true;
  dom.submissionsList.hidden = false;
  dom.submissionsList.innerHTML = submissions.map((submission) => {
    const label = escapeHtml(submission.original_filename || 'Previous submission');
    const submittedAt = escapeHtml(buildSubmissionMeta(submission));
    const mediaStatus = submission.has_media ? 'Media available' : 'Media unavailable';
    return `
      <button
        class="history-item admin-history-item open-submission-btn"
        data-submission-id="${escapeHtml(submission.submission_id)}"
        type="button">
        <span class="history-item-title">${label}</span>
        <span class="history-item-date">${submittedAt}</span>
        <span class="history-item-date">${mediaStatus}</span>
      </button>
    `;
  }).join('');

  dom.submissionsList.querySelectorAll('.open-submission-btn').forEach((btn) => {
    btn.addEventListener('click', () => openSubmissionDetail(btn.dataset.submissionId));
  });
}

async function openSubmissionDetail(submissionId) {
  dom.submissionsError.hidden = true;

  try {
    const resp = await apiFetch(`/api/admin/submissions/${encodeURIComponent(submissionId)}`);
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || 'Failed to load submission');
    }

    state.selectedSubmissionId = submissionId;
    dom.submissionDetail.hidden = false;
    dom.submissionDetailTitle.textContent = data.original_filename || 'Previous submission';
    dom.submissionDetailMeta.textContent = [
      data.username,
      buildSubmissionMeta(data),
    ].filter(Boolean).join(' | ');
    dom.submissionFeedback.textContent = data.feedback || statusFallbackMessage(data, 'feedback');
    dom.submissionTranscript.textContent = data.transcript || statusFallbackMessage(data, 'transcript');

    if (data.has_media) {
      dom.submissionMediaLink.hidden = false;
      dom.submissionMediaLink.href =
        `/api/admin/submissions/${encodeURIComponent(submissionId)}/media`;
    } else {
      dom.submissionMediaLink.hidden = true;
      dom.submissionMediaLink.removeAttribute('href');
    }
    dom.deleteSubmissionBtn.hidden = false;
    dom.deleteSubmissionBtn.disabled = false;
    dom.deleteSubmissionBtn.textContent = 'Delete Submission';
  } catch (error) {
    dom.submissionsError.textContent = error.message || 'Could not load submission details.';
    dom.submissionsError.hidden = false;
  }
}

function hideSubmissionDetail() {
  state.selectedSubmissionId = '';
  dom.submissionDetail.hidden = true;
  dom.submissionDetailTitle.textContent = 'Submission';
  dom.submissionDetailMeta.textContent = '';
  dom.submissionFeedback.textContent = '';
  dom.submissionTranscript.textContent = '';
  dom.submissionMediaLink.hidden = true;
  dom.submissionMediaLink.removeAttribute('href');
  dom.deleteSubmissionBtn.hidden = true;
  dom.deleteSubmissionBtn.disabled = false;
  dom.deleteSubmissionBtn.textContent = 'Delete Submission';
}

function resetSubmissionInspector(message) {
  state.selectedUserId = '';
  state.selectedUsername = '';
  state.selectedSubmissionId = '';
  dom.selectedUserLabel.textContent = message;
  dom.refreshSubmissionsBtn.hidden = true;
  dom.submissionsError.hidden = true;
  dom.submissionsEmpty.hidden = true;
  dom.submissionsList.hidden = true;
  dom.submissionsList.innerHTML = '';
  hideSubmissionDetail();
}

async function deleteSelectedSubmission() {
  if (!state.selectedSubmissionId || !state.selectedUserId) {
    return;
  }

  const submissionLabel = dom.submissionDetailTitle.textContent || 'this submission';
  const confirmed = await showConfirmModal(
    'Delete Submission',
    `Delete '${submissionLabel}' for '${state.selectedUsername}'? This cannot be undone.`
  );
  if (!confirmed) return;

  dom.deleteSubmissionBtn.disabled = true;
  dom.deleteSubmissionBtn.textContent = 'Deleting...';

  try {
    const resp = await apiFetch(
      `/api/admin/submissions/${encodeURIComponent(state.selectedSubmissionId)}`,
      { method: 'DELETE' }
    );
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || 'Failed to delete submission.');
    }

    hideSubmissionDetail();
    await inspectUserSubmissions(state.selectedUserId, state.selectedUsername);
  } catch (error) {
    dom.submissionsError.textContent = error.message || 'Could not delete this submission.';
    dom.submissionsError.hidden = false;
    dom.deleteSubmissionBtn.disabled = false;
    dom.deleteSubmissionBtn.textContent = 'Delete Submission';
  }
}

async function handleAddUser(event) {
  event.preventDefault();
  hideAddUserMessages();

  const username = dom.newUsername.value.trim();
  const password = dom.newPassword.value;
  const cohortId = dom.newCohort.value.trim();
  const isAdmin = dom.newIsAdmin.checked;

  if (!username || !password) {
    showAddUserError('Username and password are required.');
    return;
  }

  dom.addUserBtn.disabled = true;
  dom.addUserBtn.textContent = 'Adding...';

  try {
    const resp = await apiFetch('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password,
        cohort_id: cohortId,
        is_admin: isAdmin,
      }),
    });
    const data = await resp.json();

    if (resp.ok) {
      dom.addUserForm.reset();
      showAddUserSuccess(`User '${username}' created successfully.`);
      await loadUsers();
    } else {
      showAddUserError(data.error || 'Failed to create user.');
    }
  } catch {
    showAddUserError('Could not reach the server. Please try again.');
  } finally {
    dom.addUserBtn.disabled = false;
    dom.addUserBtn.textContent = 'Add User';
  }
}

async function deleteUser(userId, username) {
  const confirmed = await showConfirmModal(
    'Delete User',
    `Delete '${username}' and all their submissions? This cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const resp = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });
    const data = await resp.json();

    if (resp.ok) {
      if (state.selectedUserId === userId) {
        resetSubmissionInspector('Select a user to inspect their feedback history.');
      }
      await loadUsers();
    } else {
      dom.tableError.textContent = data.error || 'Failed to delete user.';
      dom.tableError.hidden = false;
    }
  } catch {
    dom.tableError.textContent = 'Could not reach the server. Please try again.';
    dom.tableError.hidden = false;
  }
}

async function handleDeleteCohort(event) {
  event.preventDefault();
  hideDeleteCohortMessages();

  const cohortId = dom.cohortIdInput.value.trim();
  if (!cohortId) {
    showDeleteCohortError('Please enter a cohort ID.');
    return;
  }

  const confirmed = await showConfirmModal(
    'Delete Cohort',
    `Delete all users in cohort '${cohortId}' and their submissions? This cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const resp = await apiFetch(`/api/admin/users/cohort/${encodeURIComponent(cohortId)}`, {
      method: 'DELETE',
    });
    const data = await resp.json();

    if (resp.ok) {
      dom.deleteCohortForm.reset();
      showDeleteCohortSuccess(data.message);
      resetSubmissionInspector('Select a user to inspect their feedback history.');
      await loadUsers();
    } else {
      showDeleteCohortError(data.error || 'Failed to delete cohort.');
    }
  } catch {
    showDeleteCohortError('Could not reach the server. Please try again.');
  }
}

function showConfirmModal(title, body) {
  // The modal is event-driven, so wrap it once and consume it with await at the call sites.
  return new Promise((resolve) => {
    dom.modalTitle.textContent = title;
    dom.modalBody.textContent = body;
    dom.confirmModal.hidden = false;
    dom.modalConfirm.focus();

    function onConfirm() {
      cleanup();
      resolve(true);
    }

    function onCancel() {
      cleanup();
      resolve(false);
    }

    function onKeydown(event) {
      if (event.key === 'Escape') {
        cleanup();
        resolve(false);
      }
    }

    function cleanup() {
      dom.modalConfirm.removeEventListener('click', onConfirm);
      dom.modalCancel.removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKeydown);
      dom.confirmModal.hidden = true;
    }

    dom.modalConfirm.addEventListener('click', onConfirm);
    dom.modalCancel.addEventListener('click', onCancel);
    document.addEventListener('keydown', onKeydown);
  });
}

function showAddUserError(message) {
  dom.addUserError.textContent = message;
  dom.addUserError.hidden = false;
}

function showAddUserSuccess(message) {
  dom.addUserSuccess.textContent = message;
  dom.addUserSuccess.hidden = false;
}

function hideAddUserMessages() {
  dom.addUserError.hidden = true;
  dom.addUserSuccess.hidden = true;
}

function showDeleteCohortError(message) {
  dom.deleteCohortError.textContent = message;
  dom.deleteCohortError.hidden = false;
}

function showDeleteCohortSuccess(message) {
  dom.deleteCohortSuccess.textContent = message;
  dom.deleteCohortSuccess.hidden = false;
}

function hideDeleteCohortMessages() {
  dom.deleteCohortError.hidden = true;
  dom.deleteCohortSuccess.hidden = true;
}

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return isoString;
  }
}

function formatDateTime(isoString) {
  try {
    return new Date(isoString).toLocaleString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoString;
  }
}

function formatDuration(durationSeconds) {
  const rounded = Math.max(0, Math.round(durationSeconds || 0));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  return `Duration ${minutes}:${String(seconds).padStart(2, '0')}`;
}

function formatSourceLabel(source) {
  return source === 'recorded' ? 'Recorded in app' : 'Uploaded file';
}

function buildSubmissionMeta(submission) {
  const parts = [];
  if (submission.submitted_at) {
    parts.push(formatDateTime(submission.submitted_at));
  }
  if (typeof submission.duration_seconds === 'number' && submission.duration_seconds > 0) {
    parts.push(formatDuration(submission.duration_seconds));
  }
  if (submission.submission_source) {
    parts.push(formatSourceLabel(submission.submission_source));
  }
  if (submission.status) {
    parts.push(formatStatusLabel(submission.status));
  }
  return parts.join(' | ');
}

function formatStatusLabel(status) {
  if (status === 'queued') return 'Queued';
  if (status === 'processing') return 'Processing';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return status;
}

function statusFallbackMessage(submission, kind) {
  if (submission.status === 'queued') {
    return kind === 'feedback'
      ? 'Feedback has not been generated yet. This submission is queued.'
      : 'Transcript has not been generated yet. This submission is queued.';
  }
  if (submission.status === 'processing') {
    return kind === 'feedback'
      ? 'Feedback is still being generated.'
      : 'Transcript is still being generated.';
  }
  if (submission.status === 'failed') {
    return submission.error_message || 'This submission failed during processing.';
  }
  return kind === 'feedback' ? 'No feedback stored.' : 'No transcript stored.';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function initEventListeners() {
  dom.logoutBtn.addEventListener('click', async () => {
    await logout();
  });
  dom.addUserForm.addEventListener('submit', handleAddUser);
  dom.deleteCohortForm.addEventListener('submit', handleDeleteCohort);
  dom.refreshSubmissionsBtn.addEventListener('click', async () => {
    if (state.selectedUserId) {
      await inspectUserSubmissions(state.selectedUserId, state.selectedUsername, true);
    }
  });
  dom.deleteSubmissionBtn.addEventListener('click', async () => {
    await deleteSelectedSubmission();
  });

  dom.confirmModal.addEventListener('click', (event) => {
    if (event.target === dom.confirmModal) {
      dom.modalCancel.click();
    }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  dom.displayUsername = document.getElementById('display-username');
  dom.logoutBtn = document.getElementById('logout-btn');

  dom.addUserForm = document.getElementById('add-user-form');
  dom.newUsername = document.getElementById('new-username');
  dom.newPassword = document.getElementById('new-password');
  dom.newCohort = document.getElementById('new-cohort');
  dom.newIsAdmin = document.getElementById('new-is-admin');
  dom.addUserBtn = document.getElementById('add-user-btn');
  dom.addUserError = document.getElementById('add-user-error');
  dom.addUserSuccess = document.getElementById('add-user-success');

  dom.deleteCohortForm = document.getElementById('delete-cohort-form');
  dom.cohortIdInput = document.getElementById('cohort-id-input');
  dom.deleteCohortError = document.getElementById('delete-cohort-error');
  dom.deleteCohortSuccess = document.getElementById('delete-cohort-success');

  dom.tableError = document.getElementById('table-error');
  dom.usersTableContainer = document.getElementById('users-table-container');

  dom.selectedUserLabel = document.getElementById('selected-user-label');
  dom.refreshSubmissionsBtn = document.getElementById('refresh-submissions-btn');
  dom.submissionsError = document.getElementById('submissions-error');
  dom.submissionsEmpty = document.getElementById('submissions-empty');
  dom.submissionsList = document.getElementById('submissions-list');
  dom.submissionDetail = document.getElementById('submission-detail');
  dom.submissionDetailTitle = document.getElementById('submission-detail-title');
  dom.submissionDetailMeta = document.getElementById('submission-detail-meta');
  dom.submissionMediaLink = document.getElementById('submission-media-link');
  dom.deleteSubmissionBtn = document.getElementById('delete-submission-btn');
  dom.submissionFeedback = document.getElementById('submission-feedback');
  dom.submissionTranscript = document.getElementById('submission-transcript');

  dom.confirmModal = document.getElementById('confirm-modal');
  dom.modalTitle = document.getElementById('modal-title');
  dom.modalBody = document.getElementById('modal-body');
  dom.modalConfirm = document.getElementById('modal-confirm');
  dom.modalCancel = document.getElementById('modal-cancel');

  initEventListeners();
  resetSubmissionInspector('Select a user to inspect their feedback history.');

  const user = await checkAdminAuth();
  if (!user) return;

  dom.displayUsername.textContent = user.username;
  document.getElementById('admin-main').hidden = false;
  await loadUsers();
});

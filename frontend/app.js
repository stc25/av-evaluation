'use strict';

const API_BASE = '';
const MAX_MP3_BYTES = 30 * 1024 * 1024;
const MAX_VIDEO_BYTES = 300 * 1024 * 1024;
const MAX_RECORDING_MS = 15 * 60 * 1000;
const WARNING_THRESHOLD_MS = 14 * 60 * 1000;

const state = {
  currentUser: null,
  selectedFile: null,
  selectedFileSubmitted: false,
  selectedFileUrl: null,
  submissions: [],
  uploadInFlight: false,
  recordingSupported: false,
  recordingState: 'idle',
  mediaStream: null,
  mediaRecorder: null,
  recordedChunks: [],
  recordedFile: null,
  recordedFileSubmitted: false,
  recordedFileUrl: null,
  recordingTimerId: null,
  recordingStartedAt: 0,
  recordingWarningShown: false,
  recordingRetrySuggested: false,
  submissionPollTimerId: null,
  historyPollInFlight: false,
  activeSubmissionId: null,
  activeSubmissionStatus: '',
};

const dom = {};

function apiFetch(path, opts = {}) {
  return fetch(`${API_BASE}${path}`, { credentials: 'include', ...opts });
}

async function checkAuth() {
  try {
    const resp = await apiFetch('/api/auth/me');
    if (resp.ok) {
      showAppView(await resp.json());
    } else {
      showLoginView();
    }
  } catch {
    showLoginView();
  }
}

async function login(username, password) {
  setLoginError('');
  dom.loginBtn.disabled = true;
  dom.loginBtn.textContent = 'Signing in...';

  try {
    const resp = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await resp.json();

    if (resp.ok) {
      showAppView(data);
    } else {
      setLoginError(data.error || 'Sign-in failed. Please try again.');
    }
  } catch {
    setLoginError('Could not reach the server. Please check your connection.');
  } finally {
    dom.loginBtn.disabled = false;
    dom.loginBtn.textContent = 'Sign In';
  }
}

async function logout() {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch {
    // Ignore logout network failures and clear local state anyway.
  }

  state.currentUser = null;
  state.submissions = [];
  state.uploadInFlight = false;
  clearFile();
  resetRecordingUi();
  hideFeedback();
  showLoginView();
}

function showLoginView() {
  dom.loginView.hidden = false;
  dom.appView.hidden = true;
  dom.loginForm.reset();
  setLoginError('');
  stopSubmissionPolling();
  state.activeSubmissionId = null;
  state.activeSubmissionStatus = '';
  clearHistoryMessages();
  dom.historyList.innerHTML = '';
  dom.historyEmpty.hidden = true;
}

function showAppView(user) {
  state.currentUser = user;
  dom.displayUsername.textContent = user.username;
  dom.adminLink.hidden = !user.is_admin;
  dom.loginView.hidden = true;
  dom.appView.hidden = false;
  clearFile();
  resetRecordingUi();
  hideFeedback();
  checkRecordingSupport();
  loadSubmissionHistory();
}

function validateFile(file) {
  const ext = getFileExtension(file.name);
  if (!['mp3', 'mp4', 'webm'].includes(ext)) {
    return 'Only MP3 (audio), MP4 (video), and WebM (video) files are accepted.';
  }

  const maxBytes = ext === 'mp3' ? MAX_MP3_BYTES : MAX_VIDEO_BYTES;
  const maxMb = maxBytes / (1024 * 1024);

  if (file.size > maxBytes) {
    return `${ext.toUpperCase()} files must be under ${maxMb} MB. Your file is ${formatSize(file.size)}.`;
  }

  return null;
}

function handleFileSelect(file) {
  if (!file || state.recordingState === 'recording' || state.recordingState === 'stopping') {
    return;
  }

  const error = validateFile(file);
  if (error) {
    showUploadError(error);
    return;
  }

  clearUploadError();
  hideFeedback();
  state.selectedFile = file;
  state.selectedFileSubmitted = false;

  cleanupSelectedFileUrl();
  state.selectedFileUrl = URL.createObjectURL(file);

  dom.fileNameDisplay.textContent = file.name;
  dom.fileSizeDisplay.textContent = formatSize(file.size);
  dom.fileInfo.hidden = false;
  showMediaPreview(file, state.selectedFileUrl, dom.audioPlayer, dom.videoPlayer);
  dom.playerContainer.hidden = false;
  dom.clearBtn.hidden = false;
  updateActionAvailability();
}

function clearFile() {
  state.selectedFile = null;
  state.selectedFileSubmitted = false;
  cleanupSelectedFileUrl();
  dom.fileInput.value = '';
  dom.fileInfo.hidden = true;
  dom.playerContainer.hidden = true;
  dom.audioPlayer.src = '';
  dom.videoPlayer.src = '';
  dom.clearBtn.hidden = true;
  dom.progressArea.hidden = true;
  clearUploadError();
  updateActionAvailability();
}

function cleanupSelectedFileUrl() {
  if (state.selectedFileUrl) {
    URL.revokeObjectURL(state.selectedFileUrl);
    state.selectedFileUrl = null;
  }
}

function cleanupRecordedFileUrl() {
  if (state.recordedFileUrl) {
    URL.revokeObjectURL(state.recordedFileUrl);
    state.recordedFileUrl = null;
  }
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.round(bytes / 1024)} KB`;
}

async function obtainFeedback() {
  if (!state.selectedFile || state.selectedFileSubmitted) return;
  await submitMedia(state.selectedFile, 'upload');
}

async function uploadRecordedMedia() {
  if (!state.recordedFile || state.recordedFileSubmitted) return;
  await submitMedia(state.recordedFile, 'recorded');
}

async function enableCameraPreview() {
  if (!state.recordingSupported || state.uploadInFlight || state.recordingState === 'recording' || state.recordingState === 'stopping') {
    return;
  }

  clearRecordingError();
  clearUploadError();
  hideFeedback();
  clearFile();

  if (state.mediaStream && state.recordingState === 'camera-ready') {
    stopMediaTracks();
    state.recordingState = 'idle';
  }

  let stream = null;

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: true,
    });

    state.mediaStream = stream;
    state.recordingState = 'camera-ready';
    state.recordedChunks = [];
    state.recordedFile = null;
    state.recordedFileSubmitted = false;
    cleanupRecordedFileUrl();

    dom.recordingPreviewPlayback.pause();
    dom.recordingPreviewPlayback.removeAttribute('src');
    dom.recordingPreviewPlayback.hidden = true;
    dom.recordingPreviewLive.srcObject = stream;
    dom.recordingPreviewLive.hidden = false;
    try {
      await dom.recordingPreviewLive.play();
    } catch {
      // Ignore autoplay failures; the live preview can still render once the user interacts.
    }
    dom.recordingStatus.textContent =
      'Camera and microphone are ready. Click Start Recording when you are ready.';
    dom.recordingTimer.hidden = true;
    dom.recordingTimer.textContent = 'Time remaining: 15:00';
    state.recordingRetrySuggested = false;
    clearRecordingWarning();
    updateActionAvailability();
  } catch (error) {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
    state.mediaStream = null;
    state.recordingState = 'idle';
    state.recordingRetrySuggested = shouldSuggestRecordingRetry(error);
    dom.recordingPreviewLive.hidden = true;
    dom.recordingPreviewLive.srcObject = null;
    dom.recordingStatus.textContent = 'Unable to start camera preview.';
    dom.recordingTimer.hidden = true;
    clearRecordingWarning();
    showRecordingError(buildRecordingStartError(error));
    updateActionAvailability();
  }
}

async function releaseCameraAndRetry() {
  if (state.uploadInFlight || state.recordingState === 'recording' || state.recordingState === 'stopping') {
    return;
  }

  clearRecordingError();
  state.recordingRetrySuggested = false;
  stopMediaTracks();
  state.recordingState = 'idle';
  dom.recordingPreviewLive.hidden = true;
  dom.recordingPreviewLive.srcObject = null;
  dom.recordingStatus.textContent = 'Releasing camera and microphone, then trying again...';
  updateActionAvailability();

  await new Promise((resolve) => window.setTimeout(resolve, 400));
  await enableCameraPreview();
}

async function submitMedia(file, submissionSource) {
  state.uploadInFlight = true;
  updateActionAvailability();
  clearUploadError();
  clearRecordingError();
  hideFeedback();
  showProgress('Uploading your presentation...');

  const formData = new FormData();
  formData.append('file', file);
  formData.append('submission_source', submissionSource);

  try {
    const { ok, data } = await uploadWithProgress(formData, (pct) => {
      if (pct < 100) {
        dom.progressMsg.textContent = `Uploading... ${pct}%`;
      } else {
        dom.progressMsg.textContent =
          'Checking duration, transcribing, and analysing your presentation. Please wait...';
      }
    });

    if (ok) {
      if (submissionSource === 'recorded') {
        state.recordedFileSubmitted = true;
      } else {
        state.selectedFileSubmitted = true;
      }
      state.activeSubmissionId = data.submission_id || null;
      state.activeSubmissionStatus = data.status || '';
      if (data.status === 'completed') {
        showFeedback(data.feedback, {
          title: data.original_filename || file.name,
          meta: buildSubmissionMeta(data),
        });
      } else {
        showSubmissionStatus(data);
      }
      await loadSubmissionHistory();
    } else if (submissionSource === 'recorded') {
      showRecordingError(data.error || 'An unexpected error occurred. Please try again.');
    } else {
      showUploadError(data.error || 'An unexpected error occurred. Please try again.');
    }
  } catch {
    const message = 'Could not reach the server. Please check your connection and try again.';
    if (submissionSource === 'recorded') {
      showRecordingError(message);
    } else {
      showUploadError(message);
    }
  } finally {
    state.uploadInFlight = false;
    dom.progressArea.hidden = true;
    updateActionAvailability();
  }
}

function uploadWithProgress(formData, onProgress) {
  // XMLHttpRequest is still the simplest way to expose upload progress as an awaitable operation.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.withCredentials = true;

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.upload.addEventListener('load', () => onProgress(100));

    xhr.addEventListener('load', () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = {};
      }
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        data,
      });
    });

    xhr.addEventListener('error', () => reject(new Error('Network error')));
    xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));

    xhr.open('POST', `${API_BASE}/api/upload`);
    xhr.send(formData);
  });
}

async function loadSubmissionHistory() {
  clearHistoryMessages();
  dom.historyList.innerHTML = '';
  dom.historyEmpty.hidden = true;

  try {
    const resp = await apiFetch('/api/submissions');
    const data = await resp.json();

    if (!resp.ok) {
      showHistoryError(data.error || 'Could not load your previous feedback.');
      return;
    }

    state.submissions = Array.isArray(data) ? data : [];
    renderSubmissionHistory();
    ensureSubmissionPolling();
    await syncActiveSubmissionDetail();
  } catch {
    showHistoryError('Could not load your previous feedback.');
  }
}

function renderSubmissionHistory() {
  dom.historyList.innerHTML = '';

  if (state.submissions.length === 0) {
    dom.historyEmpty.hidden = false;
    return;
  }

  dom.historyEmpty.hidden = true;

  state.submissions.forEach((submission) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item admin-history-item';
    button.innerHTML = `
      <span class="history-item-title">${escapeHtml(submission.original_filename || 'Previous submission')}</span>
      <span class="history-item-date">${escapeHtml(buildSubmissionMeta(submission))}</span>
    `;
    button.addEventListener('click', () => openSubmissionFeedback(submission.submission_id));
    dom.historyList.appendChild(button);
  });
}

async function openSubmissionFeedback(submissionId) {
  clearHistoryMessages();
  state.activeSubmissionId = submissionId;

  try {
    const resp = await apiFetch(`/api/submissions/${encodeURIComponent(submissionId)}`);
    const data = await resp.json();

    if (!resp.ok) {
      showHistoryError(data.error || 'Could not load this feedback.');
      return;
    }

    state.activeSubmissionStatus = data.status || '';
    if (data.status === 'completed') {
      showFeedback(data.feedback, {
        title: data.original_filename || 'Previous Feedback',
        meta: buildSubmissionMeta(data),
      });
    } else {
      showSubmissionStatus(data);
    }
  } catch {
    showHistoryError('Could not load this feedback.');
  }
}

function hasIncompleteSubmission(submission) {
  return submission.status === 'queued' || submission.status === 'processing';
}

function ensureSubmissionPolling() {
  const needsPolling = state.submissions.some(hasIncompleteSubmission);
  if (needsPolling && !state.submissionPollTimerId) {
    state.submissionPollTimerId = window.setInterval(() => {
      void pollIncompleteSubmissions();
    }, 10000);
    return;
  }

  if (!needsPolling) {
    stopSubmissionPolling();
  }
}

function stopSubmissionPolling() {
  if (state.submissionPollTimerId) {
    window.clearInterval(state.submissionPollTimerId);
    state.submissionPollTimerId = null;
  }
}

async function pollIncompleteSubmissions() {
  if (state.historyPollInFlight || state.uploadInFlight || !state.currentUser) {
    return;
  }

  state.historyPollInFlight = true;
  try {
    await loadSubmissionHistory();
  } finally {
    state.historyPollInFlight = false;
  }
}

async function syncActiveSubmissionDetail() {
  if (!state.activeSubmissionId) {
    return;
  }

  const submission = state.submissions.find((item) => item.submission_id === state.activeSubmissionId);
  if (!submission) {
    return;
  }

  if (submission.status !== state.activeSubmissionStatus || hasIncompleteSubmission(submission)) {
    await openSubmissionFeedback(submission.submission_id);
  }
}

function checkRecordingSupport() {
  state.recordingSupported = Boolean(
    navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    typeof window.MediaRecorder !== 'undefined'
  );

  dom.recordingUnsupported.hidden = state.recordingSupported;
  dom.recordingPanel.hidden = !state.recordingSupported;
  updateActionAvailability();
}

async function startRecordingSession() {
  if (!state.recordingSupported || state.uploadInFlight) {
    return;
  }

  if (state.recordingState !== 'camera-ready' || !state.mediaStream) {
    showRecordingError('Enable the camera and microphone first, then start recording when you are ready.');
    return;
  }

  clearRecordingError();
  clearUploadError();
  hideFeedback();
  clearFile();

  try {
    const recorder = createMediaRecorder(state.mediaStream);

    state.mediaRecorder = recorder;
    state.recordedChunks = [];
    state.recordingStartedAt = Date.now();
    state.recordingWarningShown = false;
    state.recordingState = 'recording';
    state.recordedFile = null;
    state.recordedFileSubmitted = false;
    cleanupRecordedFileUrl();

    recorder.ondataavailable = handleRecorderDataAvailable;
    recorder.onstop = handleRecorderStop;
    recorder.start(1000);

    dom.recordingPreviewPlayback.hidden = true;
    dom.recordingPreviewPlayback.removeAttribute('src');
    dom.recordingStatus.textContent = 'Recording in progress.';
    dom.recordingTimer.hidden = false;
    clearRecordingWarning();

    startRecordingTimer();
    updateActionAvailability();
  } catch (error) {
    state.mediaRecorder = null;
    state.recordedChunks = [];
    state.recordingState = 'camera-ready';
    dom.recordingStatus.textContent =
      'Camera and microphone are ready. Click Start Recording when you are ready.';
    dom.recordingTimer.hidden = true;
    clearRecordingWarning();
    showRecordingError(buildRecordingStartError(error));
    updateActionAvailability();
  }
}

function pickRecordingMimeType() {
  const candidates = [
    'video/mp4;codecs=h264,aac',
    'video/mp4',
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm',
  ];

  const canCheckType = typeof window.MediaRecorder?.isTypeSupported === 'function';
  for (const candidate of candidates) {
    if (!canCheckType || window.MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }

  return '';
}

function createMediaRecorder(stream) {
  const mimeType = pickRecordingMimeType();
  const attempts = [];

  if (mimeType) {
    attempts.push(() => new MediaRecorder(stream, { mimeType }));
  }
  attempts.push(() => new MediaRecorder(stream));

  let lastError = null;
  for (const attempt of attempts) {
    try {
      return attempt();
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error('Unable to create a media recorder in this browser.');
}

function handleRecorderDataAvailable(event) {
  if (event.data && event.data.size > 0) {
    state.recordedChunks.push(event.data);
  }
}

function handleRecorderStop() {
  stopRecordingTimer();
  stopMediaTracks();

  if (state.recordedChunks.length === 0) {
    showRecordingError('No recording data was captured. Please try again.');
    resetRecordingUi();
    return;
  }

  const mimeType = state.mediaRecorder?.mimeType || 'video/webm';
  const ext = mimeType.includes('mp4') ? 'mp4' : 'webm';
  const blob = new Blob(state.recordedChunks, { type: mimeType });
  const fileName = buildRecordedFilename(ext);

  state.recordedFile = new File([blob], fileName, {
    type: mimeType || 'video/webm',
    lastModified: Date.now(),
  });
  state.recordedFileSubmitted = false;
  cleanupRecordedFileUrl();
  state.recordedFileUrl = URL.createObjectURL(state.recordedFile);

  dom.recordingPreviewLive.hidden = true;
  dom.recordingPreviewLive.srcObject = null;
  dom.recordingPreviewPlayback.src = state.recordedFileUrl;
  dom.recordingPreviewPlayback.hidden = false;
  dom.recordingStatus.textContent = 'Recording ready to upload.';
  dom.recordingTimer.hidden = true;
  clearRecordingWarning();

  state.mediaRecorder = null;
  state.mediaStream = null;
  state.recordingState = 'preview';
  updateActionAvailability();
}

function stopRecordingSession(autoStop = false) {
  if (!state.mediaRecorder || state.recordingState !== 'recording') {
    return;
  }

  stopRecordingTimer();
  state.recordingState = 'stopping';
  dom.recordingStatus.textContent = autoStop
    ? 'Finalising recording after the 15 minute limit.'
    : 'Finalising recording...';

  if (state.mediaRecorder.state !== 'inactive') {
    state.mediaRecorder.stop();
  }

  updateActionAvailability();
}

function discardRecording() {
  clearRecordingError();
  clearRecordingWarning();
  state.recordedFile = null;
  state.recordedFileSubmitted = false;
  cleanupRecordedFileUrl();
  dom.recordingPreviewPlayback.pause();
  dom.recordingPreviewPlayback.removeAttribute('src');
  dom.recordingPreviewPlayback.hidden = true;
  dom.recordingStatus.textContent = 'Ready to record a new presentation.';
  dom.recordingTimer.hidden = true;
  state.recordingState = 'idle';
  updateActionAvailability();
}

function resetRecordingUi() {
  stopRecordingTimer();

  if (state.mediaRecorder) {
    state.mediaRecorder.ondataavailable = null;
    state.mediaRecorder.onstop = null;
    if (state.mediaRecorder.state !== 'inactive') {
      try {
        state.mediaRecorder.stop();
      } catch {
        // Ignore shutdown errors during reset.
      }
    }
  }

  stopMediaTracks();
  state.mediaRecorder = null;
  state.recordedChunks = [];
  state.recordedFile = null;
  state.recordedFileSubmitted = false;
  cleanupRecordedFileUrl();
  dom.recordingPreviewLive.hidden = true;
  dom.recordingPreviewLive.srcObject = null;
  dom.recordingPreviewPlayback.pause();
  dom.recordingPreviewPlayback.removeAttribute('src');
  dom.recordingPreviewPlayback.hidden = true;
  dom.recordingStatus.textContent = 'Ready to record a new presentation.';
  dom.recordingTimer.hidden = true;
  dom.recordingTimer.textContent = 'Time remaining: 15:00';
  clearRecordingWarning();
  clearRecordingError();
  state.recordingWarningShown = false;
  state.recordingRetrySuggested = false;
  state.recordingState = 'idle';
  updateActionAvailability();
}

function stopMediaTracks() {
  if (!state.mediaStream) {
    return;
  }

  state.mediaStream.getTracks().forEach((track) => track.stop());
  state.mediaStream = null;
}

function startRecordingTimer() {
  stopRecordingTimer();
  updateRecordingTimerUi();

  state.recordingTimerId = window.setInterval(() => {
    const elapsedMs = Date.now() - state.recordingStartedAt;
    if (elapsedMs >= WARNING_THRESHOLD_MS && !state.recordingWarningShown) {
      showOneMinuteWarning();
    }

    if (elapsedMs >= MAX_RECORDING_MS) {
      updateRecordingTimerUi(0);
      stopRecordingSession(true);
      return;
    }

    updateRecordingTimerUi();
  }, 250);
}

function stopRecordingTimer() {
  if (state.recordingTimerId) {
    window.clearInterval(state.recordingTimerId);
    state.recordingTimerId = null;
  }
}

function updateRecordingTimerUi(forcedRemainingMs = null) {
  const elapsedMs = Date.now() - state.recordingStartedAt;
  const remainingMs = forcedRemainingMs === null
    ? Math.max(0, MAX_RECORDING_MS - elapsedMs)
    : forcedRemainingMs;
  dom.recordingTimer.textContent = `Time remaining: ${formatRecordingTime(remainingMs)}`;
}

function showOneMinuteWarning() {
  state.recordingWarningShown = true;
  dom.recordingWarning.textContent =
    '1 minute remaining. Recording will stop automatically at 15:00.';
  dom.recordingWarning.hidden = false;
}

function clearRecordingWarning() {
  dom.recordingWarning.textContent = '';
  dom.recordingWarning.hidden = true;
}

function showRecordingError(message) {
  dom.recordingError.textContent = message;
  dom.recordingError.hidden = false;
}

function clearRecordingError() {
  dom.recordingError.textContent = '';
  dom.recordingError.hidden = true;
}

function shouldSuggestRecordingRetry(error) {
  const name = error?.name || '';
  return name === 'NotReadableError' || name === 'TrackStartError';
}

function formatRecordingTime(milliseconds) {
  const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function buildRecordingStartError(error) {
  const name = error?.name || '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return 'Camera or microphone permission was denied. Please allow access and try again.';
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return 'No usable webcam or microphone was found on this device.';
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return 'The webcam or microphone could not be started because another app or browser tab may still be using it. Close anything using the camera or mic, then try Release Camera and Retry.';
  }
  if (name === 'NotSupportedError') {
    return 'This browser could not start a compatible recording format. Try Chrome or Edge, or upload a file instead.';
  }
  return 'Recording could not be started in this browser. Please try Chrome or Edge, or upload a file instead.';
}

function buildRecordedFilename(ext) {
  const now = new Date();
  const parts = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
  ];
  return `recording-${parts.join('')}.${ext}`;
}

function showMediaPreview(file, objectUrl, audioElement, videoElement) {
  const ext = getFileExtension(file.name);
  if (ext === 'mp4' || ext === 'webm') {
    audioElement.hidden = true;
    videoElement.hidden = false;
    videoElement.src = objectUrl;
  } else {
    videoElement.hidden = true;
    audioElement.hidden = false;
    audioElement.src = objectUrl;
  }
}

function getFileExtension(fileName) {
  return fileName.includes('.')
    ? fileName.split('.').pop().toLowerCase()
    : '';
}

function renderMarkdown(markdown) {
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    const pre = document.createElement('pre');
    pre.className = 'feedback-raw';
    pre.textContent = markdown;
    return pre.outerHTML;
  }
  return DOMPurify.sanitize(marked.parse(markdown));
}

function setLoginError(msg) {
  dom.loginError.textContent = msg;
  dom.loginError.hidden = !msg;
}

function showUploadError(msg) {
  dom.uploadError.textContent = msg;
  dom.uploadError.hidden = false;
}

function clearUploadError() {
  dom.uploadError.textContent = '';
  dom.uploadError.hidden = true;
}

function showProgress(msg) {
  dom.progressMsg.textContent = msg;
  dom.progressArea.hidden = false;
}

function showHistoryError(msg) {
  dom.historyError.textContent = msg;
  dom.historyError.hidden = false;
}

function clearHistoryMessages() {
  dom.historyError.textContent = '';
  dom.historyError.hidden = true;
}

function showFeedback(markdown, opts = {}) {
  dom.feedbackTitle.textContent = opts.title ? `Feedback for ${opts.title}` : 'Your Feedback';
  if (opts.meta) {
    dom.feedbackMeta.textContent = opts.meta;
    dom.feedbackMeta.hidden = false;
  } else {
    dom.feedbackMeta.textContent = '';
    dom.feedbackMeta.hidden = true;
  }

  dom.feedbackContent.innerHTML = renderMarkdown(markdown);
  dom.feedbackContainer.hidden = false;

  setTimeout(() => {
    dom.feedbackContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 50);
}

function showSubmissionStatus(submission) {
  const title = submission.original_filename || 'Submission';
  const message = buildSubmissionStatusMessage(submission);
  dom.feedbackTitle.textContent = `Submission status for ${title}`;
  dom.feedbackMeta.textContent = buildSubmissionMeta(submission);
  dom.feedbackMeta.hidden = false;
  dom.feedbackContent.innerHTML = `
    <p>${escapeHtml(message)}</p>
    ${submission.error_message ? `<p class="error-msg">${escapeHtml(submission.error_message)}</p>` : ''}
  `;
  dom.feedbackContainer.hidden = false;

  setTimeout(() => {
    dom.feedbackContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 50);
}

function hideFeedback() {
  dom.feedbackContainer.hidden = true;
  dom.feedbackTitle.textContent = 'Your Feedback';
  dom.feedbackMeta.textContent = '';
  dom.feedbackMeta.hidden = true;
  dom.feedbackContent.innerHTML = '';
  state.activeSubmissionId = null;
  state.activeSubmissionStatus = '';
}

function buildSubmissionMeta(submission) {
  const parts = [];
  if (submission.submitted_at) {
    parts.push(formatSubmittedAt(submission.submitted_at));
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
  if (submission.has_media === false) {
    parts.push('Media unavailable');
  }
  return parts.join(' | ');
}

function formatSubmittedAt(isoString) {
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
  const rounded = Math.max(0, Math.round(durationSeconds));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  return `Duration ${minutes}:${String(seconds).padStart(2, '0')}`;
}

function formatSourceLabel(source) {
  return source === 'recorded' ? 'Recorded in app' : 'Uploaded file';
}

function formatStatusLabel(status) {
  if (status === 'queued') return 'Queued';
  if (status === 'processing') return 'Processing';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return status;
}

function buildSubmissionStatusMessage(submission) {
  if (submission.status === 'queued') {
    return 'Your presentation has been queued for transcription and feedback. You can close this page and come back later.';
  }
  if (submission.status === 'processing') {
    return 'Your presentation is currently being transcribed and analysed. You can leave this page and check back later.';
  }
  if (submission.status === 'failed') {
    return 'This submission could not be processed successfully.';
  }
  return 'The submission is being updated.';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function updateActionAvailability() {
  const recordingBusy = state.recordingState === 'recording' || state.recordingState === 'stopping';
  const cameraReady = state.recordingState === 'camera-ready';
  const recordingPreviewReady = state.recordingState === 'preview' && state.recordedFile;
  const showReleaseRetry = !recordingBusy
    && !recordingPreviewReady
    && !state.uploadInFlight
    && state.recordingRetrySuggested;
  dom.feedbackBtn.disabled = !state.selectedFile || state.selectedFileSubmitted || state.uploadInFlight || recordingBusy;
  dom.clearBtn.disabled = state.uploadInFlight || recordingBusy;
  dom.enableCameraBtn.hidden = recordingBusy || recordingPreviewReady;
  dom.enableCameraBtn.disabled = !state.recordingSupported || state.uploadInFlight || cameraReady;
  dom.releaseCameraBtn.hidden = !showReleaseRetry;
  dom.releaseCameraBtn.disabled = state.uploadInFlight;
  dom.startRecordingBtn.hidden = recordingBusy || recordingPreviewReady;
  dom.startRecordingBtn.disabled = !cameraReady || state.uploadInFlight;
  dom.stopRecordingBtn.hidden = state.recordingState !== 'recording';
  dom.discardRecordingBtn.hidden = !recordingPreviewReady;
  dom.discardRecordingBtn.disabled = state.uploadInFlight;
  dom.uploadRecordingBtn.hidden = !recordingPreviewReady;
  dom.uploadRecordingBtn.disabled = state.uploadInFlight || state.recordedFileSubmitted;
  dom.fileInput.disabled = state.uploadInFlight || recordingBusy;
  dom.dropZone.classList.toggle('drop-zone-disabled', state.uploadInFlight || recordingBusy);
  if (state.uploadInFlight || recordingBusy) {
    dom.dropZone.setAttribute('aria-disabled', 'true');
  } else {
    dom.dropZone.removeAttribute('aria-disabled');
  }
}

function initEventListeners() {
  dom.loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    await login(dom.usernameInput.value.trim(), dom.passwordInput.value);
  });

  dom.logoutBtn.addEventListener('click', async () => {
    await logout();
  });
  dom.refreshHistoryBtn.addEventListener('click', async () => {
    await loadSubmissionHistory();
  });

  dom.dropZone.addEventListener('click', () => {
    if (!dom.fileInput.disabled) {
      dom.fileInput.click();
    }
  });
  dom.dropZone.addEventListener('keydown', (event) => {
    if (dom.fileInput.disabled) {
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      dom.fileInput.click();
    }
  });

  dom.dropZone.addEventListener('dragover', (event) => {
    if (dom.fileInput.disabled) {
      return;
    }
    event.preventDefault();
    dom.dropZone.classList.add('drag-over');
  });

  ['dragleave', 'dragend'].forEach((evt) => {
    dom.dropZone.addEventListener(evt, () => dom.dropZone.classList.remove('drag-over'));
  });

  dom.dropZone.addEventListener('drop', (event) => {
    if (dom.fileInput.disabled) {
      return;
    }
    event.preventDefault();
    dom.dropZone.classList.remove('drag-over');
    const file = event.dataTransfer?.files[0];
    if (file) {
      handleFileSelect(file);
    }
  });

  dom.fileInput.addEventListener('change', () => {
    const file = dom.fileInput.files[0];
    if (file) {
      handleFileSelect(file);
    }
  });

  dom.clearBtn.addEventListener('click', clearFile);
  dom.feedbackBtn.addEventListener('click', async () => {
    await obtainFeedback();
  });
  dom.enableCameraBtn.addEventListener('click', async () => {
    await enableCameraPreview();
  });
  dom.releaseCameraBtn.addEventListener('click', async () => {
    await releaseCameraAndRetry();
  });
  dom.startRecordingBtn.addEventListener('click', async () => {
    await startRecordingSession();
  });
  dom.stopRecordingBtn.addEventListener('click', () => stopRecordingSession(false));
  dom.discardRecordingBtn.addEventListener('click', discardRecording);
  dom.uploadRecordingBtn.addEventListener('click', async () => {
    await uploadRecordedMedia();
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  dom.loginView = document.getElementById('login-view');
  dom.appView = document.getElementById('app-view');
  dom.loginForm = document.getElementById('login-form');
  dom.usernameInput = document.getElementById('username');
  dom.passwordInput = document.getElementById('password');
  dom.loginError = document.getElementById('login-error');
  dom.loginBtn = document.getElementById('login-btn');
  dom.displayUsername = document.getElementById('display-username');
  dom.adminLink = document.getElementById('admin-link');
  dom.logoutBtn = document.getElementById('logout-btn');
  dom.refreshHistoryBtn = document.getElementById('refresh-history-btn');
  dom.historyError = document.getElementById('history-error');
  dom.historyEmpty = document.getElementById('history-empty');
  dom.historyList = document.getElementById('history-list');
  dom.recordingUnsupported = document.getElementById('recording-unsupported');
  dom.recordingPanel = document.getElementById('recording-panel');
  dom.recordingPreviewLive = document.getElementById('recording-preview-live');
  dom.recordingPreviewPlayback = document.getElementById('recording-preview-playback');
  dom.recordingStatus = document.getElementById('recording-status');
  dom.recordingTimer = document.getElementById('recording-timer');
  dom.recordingWarning = document.getElementById('recording-warning');
  dom.recordingError = document.getElementById('recording-error');
  dom.enableCameraBtn = document.getElementById('enable-camera-btn');
  dom.releaseCameraBtn = document.getElementById('release-camera-btn');
  dom.startRecordingBtn = document.getElementById('start-recording-btn');
  dom.stopRecordingBtn = document.getElementById('stop-recording-btn');
  dom.discardRecordingBtn = document.getElementById('discard-recording-btn');
  dom.uploadRecordingBtn = document.getElementById('upload-recording-btn');
  dom.dropZone = document.getElementById('drop-zone');
  dom.fileInput = document.getElementById('file-input');
  dom.fileInfo = document.getElementById('file-info');
  dom.fileNameDisplay = document.getElementById('file-name-display');
  dom.fileSizeDisplay = document.getElementById('file-size-display');
  dom.playerContainer = document.getElementById('player-container');
  dom.audioPlayer = document.getElementById('audio-player');
  dom.videoPlayer = document.getElementById('video-player');
  dom.uploadError = document.getElementById('upload-error');
  dom.clearBtn = document.getElementById('clear-btn');
  dom.feedbackBtn = document.getElementById('feedback-btn');
  dom.progressArea = document.getElementById('progress-area');
  dom.progressMsg = document.getElementById('progress-msg');
  dom.feedbackContainer = document.getElementById('feedback-container');
  dom.feedbackTitle = document.getElementById('feedback-title');
  dom.feedbackMeta = document.getElementById('feedback-meta');
  dom.feedbackContent = document.getElementById('feedback-content');

  initEventListeners();
  updateActionAvailability();
  await checkAuth();
});

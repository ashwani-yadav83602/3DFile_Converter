import { API_BASE } from '../../config.js';

async function requestJson(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || 'The request could not be completed.');
  }
  return data;
}

export function fetchUploadedFiles() {
  return requestJson('/list', {
    headers: { Accept: 'application/json' }
  });
}

export function openRegisteredFile(fileId) {
  return requestJson(`/api/jt-files/${encodeURIComponent(fileId)}/open-in-jt2go`, {
    method: 'POST',
    headers: { Accept: 'application/json' }
  });
}

export function convertJTFile(file) {
  const form = new FormData();
  form.append('file', file);
  return requestJson('/upload', { method: 'POST', body: form });
}

export function registerJTFile(file) {
  const form = new FormData();
  form.append('file', file);
  return requestJson('/api/jt-files/upload', { method: 'POST', body: form });
}

export function addJTFileToJT2Go(file) {
  const form = new FormData();
  form.append('file', file);
  return requestJson('/add-to-jt2go', { method: 'POST', body: form });
}

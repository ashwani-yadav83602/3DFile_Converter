import {
  addJTFileToJT2Go,
  convertJTFile,
  registerJTFile
} from '../../common/services/api.js';
import { setStatus } from '../../common/components/StatusMessage.js';
import { getErrorMessage } from '../../common/utils/errorUtils.js';
import { getElement } from '../../common/utils/domUtils.js';
import { refreshFiles } from '../files/FilesPage.js';
import { appState } from '../../state.js';
import { loadModelViewer } from './ModelViewer.js';

function setRegistrationStatus(text, isError = false) {
  setStatus(getElement('registrationStatus'), text, isError);
}

function clearSelectedFile() {
  getElement('registerBtn').style.display = 'none';
  getElement('registerBtn').disabled = false;
  getElement('addBtn').style.display = 'none';
  getElement('downloadBtn').style.display = 'none';
  getElement('selectedFile').style.display = 'none';
  getElement('previewStage').classList.remove('has-model');
  getElement('previewBadge').classList.remove('ready');
  getElement('previewBadge').textContent = 'Waiting for a file';
  setRegistrationStatus('');
  getElement('viewer').removeAttribute('src');

  if (appState.downloadUrl) {
    URL.revokeObjectURL(appState.downloadUrl);
    appState.downloadUrl = null;
  }
}

async function handleFileChange() {
  const input = getElement('file');
  const file = input.files[0];
  clearSelectedFile();
  if (!file) return;

  if (!file.name.toLowerCase().endsWith('.jt')) {
    setStatus(getElement('status'), 'Please choose a .jt file.', true);
    input.value = '';
    return;
  }

  getElement('registerBtn').style.display = 'inline-flex';
  getElement('addBtn').style.display = 'inline-flex';
  const selectedFile = getElement('selectedFile');
  selectedFile.textContent = file.name;
  selectedFile.title = file.name;
  selectedFile.style.display = 'block';
  appState.downloadUrl = URL.createObjectURL(file);
  const downloadButton = getElement('downloadBtn');
  downloadButton.href = appState.downloadUrl;
  downloadButton.download = file.name;
  downloadButton.style.display = 'inline-flex';

  setStatus(getElement('status'), 'Uploading and converting... this can take a while for large files.');
  const viewerLoad = loadModelViewer().then(() => null, error => error);

  try {
    const data = await convertJTFile(file);
    const viewerError = await viewerLoad;
    if (viewerError) {
      getElement('previewBadge').textContent = 'Preview unavailable';
      setStatus(
        getElement('status'),
        `The model converted, but the 3D viewer could not be loaded: ${viewerError.message}`,
        true
      );
      return;
    }
    const previewStage = getElement('previewStage');
    const previewBadge = getElement('previewBadge');
    previewStage.classList.add('has-model');
    previewBadge.classList.remove('ready');
    previewBadge.textContent = 'Loading preview...';
    getElement('viewer').src = new URL(data.url, window.location.origin).href;
  } catch (error) {
    setStatus(getElement('status'), getErrorMessage(error), true);
  }
}

async function handleRegistration() {
  const file = getElement('file').files[0];
  const button = getElement('registerBtn');
  if (!file || button.disabled) return;

  button.disabled = true;
  getElement('registerBtnLabel').textContent = 'Uploading to server...';
  setRegistrationStatus('Saving the original JT file and registering its metadata...');
  try {
    const data = await registerJTFile(file);
    setRegistrationStatus(
      `Registered successfully: ${data.filename} (${Number(data.file_size).toLocaleString()} bytes, record #${data.id}).`
    );
    await refreshFiles(true);
  } catch (error) {
    setRegistrationStatus(getErrorMessage(error), true);
  } finally {
    button.disabled = false;
    getElement('registerBtnLabel').textContent = 'Upload to server';
  }
}

async function handleAddToJT2Go() {
  const file = getElement('file').files[0];
  const button = getElement('addBtn');
  if (!file) return;

  button.disabled = true;
  setStatus(getElement('status'), 'Opening a new JT2Go tab...');
  try {
    await addJTFileToJT2Go(file);
    setStatus(getElement('status'), 'Opened in a new JT2Go tab.');
  } catch (error) {
    setStatus(getElement('status'), getErrorMessage(error), true);
  } finally {
    button.disabled = false;
  }
}

export function initializeUploadPage() {
  getElement('viewer').addEventListener('load', () => {
    getElement('previewBadge').classList.add('ready');
    getElement('previewBadge').textContent = 'Preview ready';
    setStatus(getElement('status'), 'Done. Drag to rotate, scroll to zoom.');
  });
  getElement('viewer').addEventListener('error', () => {
    getElement('previewBadge').classList.remove('ready');
    getElement('previewBadge').textContent = 'Preview unavailable';
    setStatus(
      getElement('status'),
      'The converted model could not be displayed. Try selecting the file again.',
      true
    );
  });
  getElement('file').addEventListener('change', handleFileChange);
  getElement('registerBtn').addEventListener('click', handleRegistration);
  getElement('addBtn').addEventListener('click', handleAddToJT2Go);
}

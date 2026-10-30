import {
  fetchUploadedFiles,
  openRegisteredFile
} from '../../common/services/api.js';
import { createFileRow } from '../../common/components/DataTable.js';
import { setStatus } from '../../common/components/StatusMessage.js';
import { getErrorMessage } from '../../common/utils/errorUtils.js';
import { getElement } from '../../common/utils/domUtils.js';
import { getMyFiles } from '../my-files/MyFilesPage.js';
import { appState } from '../../state.js';

let filesPageInitialized = false;
let activeView = 'all';
let sidebar;

function getVisibleFiles() {
  const files = activeView === 'mine' ? getMyFiles(appState.files) : appState.files;
  const query = getElement('fileSearch').value.trim().toLocaleLowerCase();
  return {
    files,
    filteredFiles: files.filter(file => [
      file.id,
      file.filename,
      file.file_location,
      file.type,
      file.size,
      file.attribute_owner
    ].some(value => String(value ?? '').toLocaleLowerCase().includes(query))),
    query
  };
}

function renderFiles() {
  if (!filesPageInitialized) return;
  const { files, filteredFiles, query } = getVisibleFiles();
  const body = getElement('uploadedFilesBody');
  const rows = document.createDocumentFragment();
  filteredFiles.forEach(file => {
    rows.appendChild(createFileRow(file, activeView, openInJT2Go));
  });
  body.replaceChildren(rows);

  const status = getElement('fileListStatus');
  if (!files.length) {
    setStatus(
      status,
      activeView === 'mine'
        ? 'No files are registered to local-user yet.'
        : 'No JT files have been uploaded to the server yet.'
    );
  } else if (!filteredFiles.length) {
    setStatus(status, `No uploaded files match "${getElement('fileSearch').value.trim()}".`);
  } else {
    setStatus(
      status,
      query
        ? `Showing ${filteredFiles.length} of ${files.length} uploaded file(s).`
        : `Showing ${filteredFiles.length} most recent uploaded file(s).`
    );
  }
}

async function openInJT2Go(file, button) {
  button.disabled = true;
  const status = getElement('fileListStatus');
  setStatus(status, `Opening ${file.filename} in JT2Go...`);
  try {
    await openRegisteredFile(file.id);
    setStatus(status, `${file.filename} opened in JT2Go.`);
  } catch (error) {
    setStatus(status, getErrorMessage(error), true);
  } finally {
    button.disabled = false;
  }
}

export async function refreshFiles(forceRefresh = false) {
  if (appState.filesRequest) {
    if (forceRefresh) appState.refreshQueued = true;
    return appState.filesRequest;
  }
  if (appState.filesLoaded && !forceRefresh) return;

  const refreshButton = getElement('refreshFilesBtn');
  const status = getElement('fileListStatus');
  refreshButton.disabled = true;
  setStatus(status, 'Loading uploaded files...');

  appState.filesRequest = (async () => {
    try {
      const data = await fetchUploadedFiles();
      appState.files = data.files;
      appState.filesLoaded = true;
      sidebar.setCounts(appState.files.length, getMyFiles(appState.files).length);
      renderFiles();
    } catch (error) {
      setStatus(status, getErrorMessage(error), true);
    } finally {
      refreshButton.disabled = false;
      appState.filesRequest = null;
      if (appState.refreshQueued) {
        appState.refreshQueued = false;
        refreshFiles(true);
      }
    }
  })();
  return appState.filesRequest;
}

export function initializeFilesPage(sidebarController) {
  if (filesPageInitialized) return;
  sidebar = sidebarController;
  getElement('fileSearch').addEventListener('input', renderFiles);
  getElement('refreshFilesBtn').addEventListener('click', () => refreshFiles(true));
  filesPageInitialized = true;
  refreshFiles();
}

export function setFilesView(view) {
  activeView = view;
  const page = getElement('filesPage');
  page.classList.toggle('active', view !== 'upload');
  getElement('uploadPage').classList.toggle('active', view === 'upload');
  getElement('jt2goActionHeader').hidden = view !== 'mine';
  getElement('uploadedFilesTitle').textContent = view === 'mine' ? 'My Files' : 'All Files';
  getElement('filesSubtitle').textContent = view === 'mine'
    ? 'Files tagged local-user (authentication is not enabled)'
    : 'Files registered in your MySQL database';
  getElement('fileSearch').placeholder = view === 'mine'
    ? 'Search your files by name, path, type or ID...'
    : 'Search filename, path, owner, type or ID...';
  renderFiles();
}

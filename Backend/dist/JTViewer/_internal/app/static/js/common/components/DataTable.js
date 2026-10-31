import { formatDate } from '../utils/dateUtils.js';
import { formatFileSize } from '../utils/fileUtils.js';
import { addTableCell } from '../utils/domUtils.js';

export function createFileRow(file, view, onOpenInJT2Go) {
  const row = document.createElement('tr');
  addTableCell(row, `#${file.id}`, 'file-id');
  // addTableCell(row, file.filename, 'file-name-cell');
  const pathCell = addTableCell(row, file.file_location, 'file-path-cell');
  pathCell.title = file.file_location;

  const typeCell = document.createElement('td');
  const typeBadge = document.createElement('span');
  typeBadge.className = 'file-type-badge';
  typeBadge.textContent = file.type;
  typeCell.appendChild(typeBadge);
  row.appendChild(typeCell);

  addTableCell(row, formatFileSize(file.size), 'file-size-cell');
  addTableCell(row, formatDate(file.createdat));
  addTableCell(row, file.attribute_owner, 'file-owner-cell');

  if (view === 'mine') {
    const actionCell = document.createElement('td');
    const openButton = document.createElement('button');
    openButton.className = 'jt2go-button';
    openButton.type = 'button';
    openButton.title = 'Open in JT2Go';
    openButton.textContent = 'JT2Go';
    openButton.setAttribute('aria-label', `Open ${file.filename} in JT2Go`);
    openButton.addEventListener('click', () => onOpenInJT2Go(file, openButton));
    actionCell.appendChild(openButton);
    row.appendChild(actionCell);
  }

  return row;
}

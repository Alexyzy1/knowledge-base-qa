// icons.js
// ICON SYSTEM — unified inline line icons (24px viewBox, 1.6 stroke)
// ============================================================
var ICON_PATHS = {
  overview:  '<path d="M4 13h7V4H4v9Zm0 7h7v-5H4v5Zm9 0h7v-9h-7v9Zm0-16v5h7V4h-7Z"/>',
  files:     '<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z"/>',
  chat:      '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 4V6a1 1 0 0 1 1-1Z"/>',
  similar:   '<circle cx="11" cy="11" r="6"/><path d="m20 20-3.5-3.5"/>',
  members:   '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 6.2A3 3 0 0 1 16 12m4.5 7a4.8 4.8 0 0 0-3.2-4.5"/>',
  settings:  '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5m15.4-6.4-1.6 1.6M7.7 16.3l-1.6 1.6m11.8 0-1.6-1.6M7.7 7.7 6.1 6.1"/>',
  audit:     '<path d="M8 4h8l4 4v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"/><path d="M8 11h8M8 15h6"/>',
  share:     '<circle cx="6" cy="12" r="2.4"/><circle cx="17" cy="6" r="2.4"/><circle cx="17" cy="18" r="2.4"/><path d="m8.1 10.9 6.8-3.8m0 9.8-6.8-3.8"/>',
  bell:      '<path d="M6.5 17h11l-1.2-1.8a3 3 0 0 1-.5-1.7V11a4.8 4.8 0 0 0-9.6 0v2.5a3 3 0 0 1-.5 1.7L4 17h2.5Z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  upload:    '<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"/>',
  download:  '<path d="M12 4v12m0 0 4.5-4.5M12 16l-4.5-4.5"/><path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"/>',
  eye:       '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.6"/>',
  stop:      '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  more:      '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
  trash:     '<path d="M5 7h14M10 7V5h4v2m-7 0 .8 12.1a1 1 0 0 0 1 .9h4.4a1 1 0 0 0 1-.9L16 7"/>',
  tag:       '<path d="M4 4h7l9 9-7 7-9-9V4Z"/><circle cx="8" cy="8" r="1.3"/>',
  folder:    '<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z"/>',
  folderPlus:'<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z"/><path d="M12 11v5m-2.5-2.5h5"/>',
  plus:      '<path d="M12 5v14M5 12h14"/>',
  search:    '<circle cx="11" cy="11" r="6"/><path d="m20 20-3.5-3.5"/>',
  note:      '<path d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  key:       '<circle cx="8" cy="8" r="3.5"/><path d="m10.5 10.5 7 7m-2.5-2.5 2-2m-4-2 1.5 1.5"/>',
  user:      '<circle cx="12" cy="8" r="3.6"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  logout:    '<path d="M15 5h3a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1h-3"/><path d="M10 12h9m0 0-3-3m3 3-3 3"/>',
  whitelist: '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="m15.5 12 1.8 1.8 3.2-3.6"/>',
  model:     '<circle cx="12" cy="12" r="2.4"/><circle cx="5" cy="6" r="1.8"/><circle cx="19" cy="6" r="1.8"/><circle cx="5" cy="18" r="1.8"/><circle cx="19" cy="18" r="1.8"/><path d="M6.5 7 10 10.5m4 0L17.5 7M6.5 17 10 13.5m4 0 3.5 3.5"/>',
  clock:     '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/>',
  retry:     '<path d="M19 12a7 7 0 1 1-2-4.9M19 4v3.5h-3.5"/>',
  check:     '<path d="m5 12.5 4.5 4.5L19 7"/>',
  x:         '<path d="m6 6 12 12M18 6 6 18"/>',
  caret:     '<path d="m6 9 6 6 6-6"/>',
  spark:     '<path d="M12 3v18M3 12h18"/>',
  doc:       '<path d="M7 3h7l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4"/>',
  pdf:       '<path d="M7 3h7l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4"/><path d="M9 13h1.2a1 1 0 0 1 0 2H9v2m4-4v4m0-4h1.6M16 13h-1.4v4" stroke-width="1.1"/>',
  sheet:     '<path d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"/><path d="M4 9h16M4 14h16M10 4v16"/>',
  image:     '<rect x="4" y="5" width="16" height="14" rx="1.5"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 4-4 3 3 3-3 4 4"/>',
  globe:     '<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4a13 13 0 0 1 0 16M12 4a13 13 0 0 0 0 16"/>',
  dashboard: '<rect x="3" y="3" width="7" height="8" rx="1"/><rect x="14" y="6" width="7" height="5" rx="1"/><rect x="3" y="15" width="7" height="6" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  rename:    '<path d="M15.5 3.5a2.12 2.12 0 0 1 3 3L8 17l-4 1 1-4Z"/>',
  hamburger: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  audio:     '<path d="M9 3l8 5v8l-8 5V3Z"/><rect x="6" y="9" width="3" height="6" rx="1"/><rect x="18" y="8" width="3" height="8" rx="1"/>',
  video:     '<rect x="2" y="5" width="15" height="14" rx="2"/><polygon points="17,8 23,5 23,19 17,16"/><path d="M6 9h6M6 13h4"/>',
};
function icon(name, sizeClass) {
  var p = ICON_PATHS[name] || ICON_PATHS.doc;
  var cls = 'icon' + (sizeClass ? ' ' + sizeClass : '');
  return '<span class="'+cls+'"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p+'</svg></span>';
}
// File-type → icon name
function fileIconName(filename) {
  if (!filename) return 'doc';
  var ext = (filename.split('.').pop()||'').toLowerCase();
  if (ext === 'pdf') return 'pdf';
  if (ext === 'csv' || ext === 'xlsx' || ext === 'xls') return 'sheet';
  if (['jpg','jpeg','png','gif','webp','svg'].indexOf(ext) !== -1) return 'image';
  if (ext === 'pptx') return 'doc';
  if (ext === 'html' || ext === 'xml') return 'globe';
  if (ext === 'md' || ext === 'txt' || ext === 'docx' || ext === 'json') return 'note';
  if (['mp3','flac','wav','aac','m4a','ogg','opus','wma','amr'].indexOf(ext) !== -1) return 'audio';
  if (['mp4','avi','mov','mkv','flv','wmv','webm','mpeg','mpg','3gp','m4v'].indexOf(ext) !== -1) return 'video';
  return 'doc';
}
// Role → avatar initial + class
function roleAvatar(username, role, sizeClass) {
  var initial = (username || '?').trim().charAt(0).toUpperCase() || '?';
  var rc = role || 'reader';
  return '<span class="role-avatar '+rc+(sizeClass?' '+sizeClass:'')+'" title="'+escapeHtmlAttr(rc)+'">'+escapeHtml(initial)+'</span>';
}

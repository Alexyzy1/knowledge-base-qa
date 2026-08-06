// upload-limits.js
// UPLOAD SIZE LIMITS — per file type (P1 2.1), front-end guard
// ============================================================
var FILE_SIZE_LIMITS_MB = {
  // images
  jpg: 10, jpeg: 10, png: 10, gif: 10, webp: 10, bmp: 10, svg: 10,
  // documents
  pdf: 20, docx: 15, doc: 15, pptx: 15,
  // tables
  csv: 15, xlsx: 15, xls: 15,
  // plain text / structured
  txt: 5, md: 5, html: 5, xml: 5,
  // audio
  mp3: 50, flac: 50, wav: 50, aac: 50, m4a: 50, ogg: 50, opus: 50, wma: 50, amr: 50,
  // video
  mp4: 100, avi: 100, mov: 100, mkv: 100, flv: 100, wmv: 100, webm: 100, mpeg: 100, mpg: 100, "3gp": 100, m4v: 100,
  _default: 10
};
var ACCEPTED_EXTS = Object.keys(FILE_SIZE_LIMITS_MB).filter(function(k){ return k !== '_default'; });
function fileSizeLimitMB(filename) {
  var ext = (String(filename).split('.').pop() || '').toLowerCase();
  return FILE_SIZE_LIMITS_MB[ext] || FILE_SIZE_LIMITS_MB._default;
}
// returns {ok:true} or {ok:false, msg}
function validateUploadFile(file) {
  var ext = (file.name.split('.').pop() || '').toLowerCase();
  if (ACCEPTED_EXTS.indexOf(ext) === -1) {
    return { ok: false, msg: '不支持的文件类型 .' + ext };
  }
  var limitMB = fileSizeLimitMB(file.name);
  if (file.size > limitMB * 1024 * 1024) {
    return { ok: false, msg: ('.' + ext).toUpperCase() + ' 文件不能超过 ' + limitMB + 'MB（当前 ' + formatBytes(file.size) + '）' };
  }
  return { ok: true, limitMB: limitMB };
}

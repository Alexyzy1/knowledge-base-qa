// app-state.js
// APP STATE
// ============================================================
var currentUser = null;        // {id, username, role}
var currentKbId = null;        // selected KB ID (单库面板:概览/文件/设置)
var selectedKbIds = [];        // 勾选的 KB ID 列表（全局搜索用）
var kbListCache = [];          // KB list
var kbRoleCache = {};          // {kbId: role} for current user
var pollingTimer = null;
var streamingAbort = null;
var isStreaming = false;
var fileViewMode = 'list';     // 'list' or 'grid'
var currentFolderId = null;    // null = all
var editingModelId = null;     // for model edit modal
var selectedDocIds = new Set();   // batch selection
var batchTagsAction = 'set';      // current tags toggle
var lastClickedDocIndex = null;   // Shift+click range selection anchor (files)
var lastClickedKbIndex = null;    // Shift+click range selection anchor (KB list)
var kbBatchMode = false;          // KB batch-operations mode
var selectedBatchKbIds = [];      // KB IDs selected in batch mode
var lastClickedBatchKbIndex = null; // Shift+click anchor for batch mode

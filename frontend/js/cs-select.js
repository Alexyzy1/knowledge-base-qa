// cs-select.js
// CUSTOM DROPDOWN (P1 2.3) — enhances native <select> in place
// ============================================================
function csEnhance(selectEl) {
  if (!selectEl || selectEl.__cs) return;
  var wrap = document.createElement('div');
  wrap.className = 'cs-select' + (selectEl.classList.contains('full') ? ' full' : '');
  if (selectEl.style.width) { wrap.style.width = selectEl.style.width; }
  var trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'cs-trigger';
  trigger.innerHTML = '<span class="cs-label"></span><span class="cs-caret">' + icon('caret','icon-16') + '</span>';
  var menu = document.createElement('div');
  menu.className = 'cs-menu';
  selectEl.parentNode.insertBefore(wrap, selectEl);
  wrap.appendChild(trigger);
  wrap.appendChild(menu);
  selectEl.style.display = 'none';
  wrap.appendChild(selectEl);
  selectEl.__cs = { wrap: wrap, trigger: trigger, menu: menu };

  function sync() {
    var sel = selectEl.options[selectEl.selectedIndex];
    trigger.querySelector('.cs-label').textContent = sel ? sel.textContent : '';
    menu.innerHTML = Array.prototype.map.call(selectEl.options, function(o, i){
      return '<div class="cs-option' + (i === selectEl.selectedIndex ? ' selected' : '') + '" data-i="' + i + '">' +
        '<span>' + escapeHtml(o.textContent) + '</span>' +
        '<span class="cs-check">' + icon('check','icon-16') + '</span></div>';
    }).join('');
  }
  selectEl.__csSync = sync;
  sync();

  trigger.addEventListener('click', function(e){
    e.stopPropagation();
    var willOpen = !wrap.classList.contains('open');
    document.querySelectorAll('.cs-select.open').forEach(function(x){ x.classList.remove('open'); });
    if (willOpen) {
      var rect = trigger.getBoundingClientRect();
      wrap.classList.toggle('up', (window.innerHeight - rect.bottom) < 260);
      wrap.classList.add('open');
    }
  });
  menu.addEventListener('click', function(e){
    var opt = e.target.closest('.cs-option');
    if (!opt) return;
    selectEl.selectedIndex = parseInt(opt.dataset.i);
    sync();
    wrap.classList.remove('open');
    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
  });
  try { new MutationObserver(sync).observe(selectEl, { childList: true }); } catch(e) {}
}
function csEnhanceAll(root) {
  (root || document).querySelectorAll('select.form-select, select.cs').forEach(csEnhance);
}
function csSync(selectEl) { if (selectEl && selectEl.__csSync) selectEl.__csSync(); }
document.addEventListener('click', function(){ document.querySelectorAll('.cs-select.open').forEach(function(x){ x.classList.remove('open'); }); });

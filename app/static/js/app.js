// 상담관리 공통 JS (모듈 패턴). innerHTML에는 서버가 렌더링한 조각만 넣는다.
const App = (() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  async function post(url, data) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(data || {}) });
    const j = await r.json().catch(() => ({ ok: false, error: '응답 오류' }));
    if (!r.ok || !j.ok) { toast(j.error || '처리에 실패했습니다'); throw new Error(j.error || r.status); }
    return j;
  }
  function toast(msg) {
    let t = $('#toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600);
  }
  const bytes = s => [...s].reduce((n, ch) => n + (ch.charCodeAt(0) > 127 ? 2 : 1), 0);

  // ---------- 사이드바 · 배지 ----------
  $('.menu-toggle')?.addEventListener('click', () => $('.sidebar').classList.toggle('open'));
  const baseTitle = document.title.replace(/^\(\d+\) /, '');
  async function pollBadge() {
    try {
      const r = await fetch('/api/badge'); if (!r.ok) return;
      const b = await r.json();
      for (const k in b) $$(`[data-badge="${k}"]`).forEach(el => el.textContent = b[k]);
      document.title = (b.new > 0 ? `(${b.new}) ` : '') + baseTitle;
    } catch (e) { /* 네트워크 일시 오류는 무시 */ }
  }
  if ($('[data-badge]')) { pollBadge(); setInterval(pollBadge, 30000); }

  // ---------- 모달 ----------
  $$('[data-open]').forEach(b => b.addEventListener('click', () => $('#' + b.dataset.open)?.showModal()));
  $$('[data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog')?.close()));
  $('[data-toggle="filters"]')?.addEventListener('click', () => $('#filters').classList.toggle('open'));
  if ($('#manual .flash')) $('#manual').showModal();

  // ---------- 목록 ↔ 상세 ----------
  const detail = $('#detail'), rowsEl = $('#rows');
  const idOf = el => el?.dataset.id;
  const isDrawer = !!$('#drawer');

  async function openPanel(id, push = true) {
    const url = `/inquiries/${id}/panel` + (isDrawer ? '?layout=drawer' : '');
    const r = await fetch(url); if (!r.ok) return toast('문의를 열 수 없습니다');
    const target = isDrawer ? $('#drawer .drawer-body') : detail;
    target.innerHTML = await r.text();
    $$('.rowbtn, .card').forEach(el => el.classList.toggle('on', idOf(el) === String(id)));
    if (isDrawer) $('#drawer').classList.add('open'); else $('.split')?.classList.add('has-sel', 'mobile-detail');
    if (push) { const u = new URL(location); u.searchParams.set('id', id); history.replaceState(null, '', u); }
    bindPanel(target);
  }
  rowsEl?.addEventListener('click', e => { const row = e.target.closest('.rowbtn'); if (row) openPanel(idOf(row)); });
  document.addEventListener('keydown', e => {
    if (!rowsEl || ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || !['ArrowUp', 'ArrowDown'].includes(e.key)) return;
    const rows = $$('.rowbtn'), i = rows.findIndex(r => r.classList.contains('on'));
    const next = rows[i + (e.key === 'ArrowDown' ? 1 : -1)]; if (next) { e.preventDefault(); openPanel(idOf(next)); next.scrollIntoView({ block: 'nearest' }); }
  });

  function swapRow(id, html) {
    const old = $(`.rowbtn[data-id="${id}"]`); if (!old || !html) return;
    const t = document.createElement('div'); t.innerHTML = html; old.replaceWith(t.firstElementChild);
  }
  function applyResult(id, j) {
    const target = isDrawer ? $('#drawer .drawer-body') : detail;
    target.innerHTML = j.panel_html; bindPanel(target);
    if (j.row_html) swapRow(id, j.row_html);
    if (j.card_html && window.Board) Board.swapCard(id, j.card_html);
  }
  const act = (id, path, data) => post(`/inquiries/${id}/${path}` + (isDrawer ? '?layout=drawer' : ''), data).then(j => applyResult(id, j));

  // ---------- 상세 패널 바인딩 ----------
  function bindPanel(root) {
    const dp = $('.dp', root); if (!dp) return;
    const id = dp.dataset.id;
    $$('[data-back]', dp).forEach(b => b.onclick = () => { $('.split')?.classList.remove('mobile-detail'); $('#drawer')?.classList.remove('open'); });
    $$('[data-pick]', dp).forEach(a => a.onclick = e => { e.preventDefault(); openPanel(a.dataset.pick); });
    // 전화 → 통화 결과 기록 강조
    $('[data-call]', dp)?.addEventListener('click', () => { $$('[data-record^="call"]', dp).forEach(b => b.classList.add('pulse')); $('[data-tab="log"]', dp)?.click(); });
    // 탭
    $$('[data-tab]', dp).forEach(b => b.onclick = () => {
      $$('.dp-tabs [data-tab]', dp).forEach(x => x.classList.toggle('on', x.dataset.tab === b.dataset.tab));
      $$('[data-pane]', dp).forEach(p => p.hidden = p.dataset.pane !== b.dataset.tab);
      const pane = $(`[data-pane="${b.dataset.tab}"]`, dp);
      if (b.dataset.tab === 'sheet' && pane.dataset.src && !pane.dataset.loaded) loadSheet(pane, pane.dataset.src);
    });
    // 상태
    const closeBox = $('.close-reason', dp);
    $$('[data-status-group] button', dp).forEach(b => b.onclick = () => {
      if (b.dataset.status === 'closed') { closeBox.hidden = false; return; }
      act(id, 'status', { status: b.dataset.status });
    });
    $('[data-close-reason]', dp)?.addEventListener('change', e => { $('[data-close-other]', dp).hidden = e.target.value !== '기타'; });
    $('[data-close-confirm]', dp)?.addEventListener('click', () => {
      let reason = $('[data-close-reason]', dp).value;
      if (reason === '기타') { const o = $('[data-close-other]', dp).value.trim(); if (!o) return toast('기타 사유를 입력하세요'); reason = '기타: ' + o; }
      act(id, 'status', { status: 'closed', close_reason: reason });
    });
    $('[data-close-cancel]', dp)?.addEventListener('click', () => closeBox.hidden = true);
    // 배정 · 콜백
    $('[data-assign]', dp)?.addEventListener('change', e => act(id, 'assign', { assignee_id: e.target.value || null }));
    $('[data-callback]', dp)?.addEventListener('change', e => act(id, 'callback', { callback_at: e.target.value || null }));
    $('[data-callback-clear]', dp)?.addEventListener('click', () => act(id, 'callback', { callback_at: null }));
    // 기록
    $$('[data-record]', dp).forEach(b => b.onclick = () => act(id, 'logs', { kind: b.dataset.record, body: $('[data-memo]', dp).value }));
    // 문자
    const sms = $('[data-sms]', dp);
    if (sms) {
      const upd = () => { const n = bytes(sms.value); $('[data-bytes]', dp).textContent = n; $('[data-smstype]', dp).textContent = n > 90 ? 'LMS 장문' : 'SMS 단문'; $('[data-smstype]', dp).classList.toggle('warn', n > 2000); };
      sms.addEventListener('input', upd); upd();
      $$('[data-tpl]', dp).forEach(b => b.onclick = () => { sms.value = b.dataset.tpl; upd(); });
      $$('[data-sms-send]', dp).forEach(b => b.onclick = async () => {
        const body = sms.value.trim(); if (!body) return toast('문자 내용을 입력하세요');
        if (/\{[^}]+\}/.test(body) && !confirm('치환되지 않은 {변수}가 남아 있습니다. 그대로 보낼까요?')) return;
        const data = { body }; if (b.dataset.smsSend === 'scheduled') { const at = $('[data-sms-at]', dp).value; if (!at) return toast('예약 일시를 선택하세요'); data.scheduled_at = at; }
        const j = await post(`/inquiries/${id}/sms` + (isDrawer ? '?layout=drawer' : ''), data);
        applyResult(id, j); const n = $('.sent-note', $('.dp', root)); if (n) { n.hidden = false; $('[data-tab="sms"]', $('.dp', root))?.click(); }
      });
    }
  }

  // ---------- 상담지 ----------
  async function loadSheet(pane, url) {
    const r = await fetch(url); pane.innerHTML = await r.text(); pane.dataset.loaded = '1'; bindSheet(pane);
  }
  function collect(form) {
    const a = {};
    $$('.sf', form).forEach(sf => {
      const k = sf.dataset.key, t = sf.dataset.type;
      if (t === 'multi') a[k] = $$('input:checked', sf).map(i => i.value);
      else if (t === 'bool') a[k] = $('input', sf).checked;
      else { const v = $('[name]', sf)?.value ?? ''; if (v !== '') a[k] = v; }
    });
    return a;
  }
  function refreshShowIf(form) {
    const a = collect(form);
    $$('.sf[data-show-key]', form).forEach(sf => { sf.hidden = String(a[sf.dataset.showKey] ?? '') !== String(JSON.parse(sf.dataset.showEq)); });
  }
  function bindSheet(pane) {
    const box = $('.sheet', pane), form = $('[data-sheet-form-body]', pane), state = $('[data-save-state]', pane);
    $('[data-sheet-form]', pane)?.addEventListener('change', e => { const u = new URL(pane.dataset.src, location); if (e.target.value) u.searchParams.set('form_id', e.target.value); loadSheet(pane, u); });
    if (!form) return;
    let timer;
    const save = async () => {
      state.textContent = '저장 중…';
      try {
        const j = await post(box.dataset.save, { form_id: box.dataset.formId, answers: collect(form) });
        state.textContent = '저장됨 ' + j.saved_at;
        $$('.sf.req', form).forEach(sf => sf.classList.toggle('missing', j.missing.includes($('.sf-label', sf).textContent.replace('*', ''))));
        const dot = $('.dp-tabs [data-tab="sheet"] .req-dot'), tab = $('.dp-tabs [data-tab="sheet"]');
        if (!j.required_done && !dot) tab.insertAdjacentHTML('beforeend', ' <i class="req-dot"></i>'); else if (j.required_done && dot) dot.remove();
      } catch (e) { state.textContent = '저장 실패 — 다시 시도'; }
    };
    const schedule = () => { clearTimeout(timer); state.textContent = '변경됨'; timer = setTimeout(save, 800); refreshShowIf(form); };
    form.addEventListener('input', schedule); form.addEventListener('change', schedule);
    $$('[data-radio]', form).forEach(b => b.onclick = () => { const wrap = b.parentElement, hid = $('input[type=hidden]', wrap); const on = b.classList.contains('on'); $$('button', wrap).forEach(x => x.classList.remove('on')); if (!on) b.classList.add('on'); hid.value = on ? '' : b.dataset.radio; schedule(); });
    $$('.num input', form).forEach(i => i.addEventListener('blur', () => { const n = Number(i.value.replace(/,/g, '')); if (i.value && !isNaN(n)) i.value = n.toLocaleString(); }));
    $('[data-sheet-copy]', pane)?.addEventListener('click', async () => { const r = await fetch(box.dataset.txt); await navigator.clipboard.writeText(await r.text()); toast('상담지 요약을 복사했습니다'); });
    $('[data-sheet-print]', pane)?.addEventListener('click', () => { document.body.classList.add('print-sheet'); window.print(); setTimeout(() => document.body.classList.remove('print-sheet'), 500); });
  }

  if (detail && $('.dp', detail)) bindPanel(detail);
  return { post, toast, openPanel, bindPanel, applyResult };
})();

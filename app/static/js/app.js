// 상담관리 공통 JS — 단일 파일, 모듈 패턴. innerHTML에는 서버가 렌더링한 조각만 넣는다.
const App = (() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

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
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

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

  // ---------- 모달 · 필터 ----------
  $$('[data-open]').forEach(b => b.addEventListener('click', () => $('#' + b.dataset.open)?.showModal()));
  $$('[data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog')?.close()));
  $('[data-toggle="filters"]')?.addEventListener('click', () => $('#filters').classList.toggle('open'));
  if ($('#manual .flash')) $('#manual').showModal();

  // ---------- 상세 페이지 (새 탭) ----------
  const detail = $('#detail');
  const target = () => detail;
  function applyResult(id, j) { target().innerHTML = j.panel_html; bindPanel(target()); }
  const act = (id, path, data) => post(`/inquiries/${id}/${path}`, data).then(j => applyResult(id, j));

  // ---------- 상세 패널 바인딩 ----------
  function bindPanel(root) {
    const dp = $('.dp', root); if (!dp) return;
    const id = dp.dataset.id;
    $$('[data-pick]', dp).forEach(a => { a.target = '_blank'; a.href = `/inquiries/${a.dataset.pick}`; });
    $('[data-call]', dp)?.addEventListener('click', () => { $$('[data-record^="call"]', dp).forEach(b => b.classList.add('pulse')); $('.dp-tabs [data-tab="log"]', dp)?.click(); });
    // 탭 (A안) · 작성기 전환 (B안)
    $$('[data-tab]', dp).forEach(b => b.onclick = () => {
      $$('.dp-tabs [data-tab]', dp).forEach(x => x.classList.toggle('on', x.dataset.tab === b.dataset.tab));
      $$('[data-pane]', dp).forEach(p => p.hidden = p.dataset.pane !== b.dataset.tab);
    });
    $$('[data-ctab]', dp).forEach(b => b.onclick = () => { $$('[data-ctab]', dp).forEach(x => x.classList.toggle('on', x === b)); $$('[data-cpane]', dp).forEach(p => p.hidden = p.dataset.cpane !== b.dataset.ctab); });
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
    // 배정 · 콜백 · 기록
    $('[data-assign]', dp)?.addEventListener('change', e => act(id, 'assign', { assignee_id: e.target.value || null }));
    $('[data-callback]', dp)?.addEventListener('change', e => act(id, 'callback', { callback_at: e.target.value || null }));
    $('[data-callback-clear]', dp)?.addEventListener('click', () => act(id, 'callback', { callback_at: null }));
    $$('[data-record]', dp).forEach(b => b.onclick = () => act(id, 'logs', { kind: b.dataset.record, body: $('[data-memo]', dp).value }));
    // 문자
    const sms = $('[data-sms]', dp);
    if (sms) {
      const upd = () => { const n = bytes(sms.value); $('[data-bytes]', dp).textContent = n; const t = $('[data-smstype]', dp); t.textContent = n > 90 ? 'LMS 장문' : 'SMS 단문'; t.classList.toggle('warn', n > 2000); };
      sms.addEventListener('input', upd); upd();
      $$('[data-tpl]', dp).forEach(b => b.onclick = () => { sms.value = b.dataset.tpl; upd(); });
      $$('[data-sms-send]', dp).forEach(b => b.onclick = async () => {
        const body = sms.value.trim(); if (!body) return toast('문자 내용을 입력하세요');
        if (/\{[^}]+\}/.test(body) && !confirm('치환되지 않은 {변수}가 남아 있습니다. 그대로 보낼까요?')) return;
        const data = { body }; if (b.dataset.smsSend === 'scheduled') { const at = $('[data-sms-at]', dp).value; if (!at) return toast('예약 일시를 선택하세요'); data.scheduled_at = at; }
        const j = await post(`/inquiries/${id}/sms`, data);
        applyResult(id, j); const root2 = target(), n = $('.sent-note', root2); if (n) { n.hidden = false; ($('.dp-tabs [data-tab="sms"]', root2) || $('[data-ctab="sms"]', root2))?.click(); }
      });
    }
  }

  // ---------- 상담지 (상세 페이지 오른쪽) ----------
  async function loadSheet(pane, url) { const r = await fetch(url); pane.innerHTML = await r.text(); pane.dataset.src = url; bindSheet(pane); }
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
    $('[data-sheet-form]', pane)?.addEventListener('change', e => { const u = new URL(pane.dataset.src, location); u.searchParams.delete('form_id'); if (e.target.value) u.searchParams.set('form_id', e.target.value); loadSheet(pane, u); });
    if (!form) return;
    const save = async () => {
      state.textContent = '저장 중…';
      try {
        const j = await post(box.dataset.save, { form_id: box.dataset.formId, answers: collect(form) });
        state.textContent = '저장됨 ' + j.saved_at;
        $$('.sf.req', form).forEach(sf => sf.classList.toggle('missing', j.missing.includes($('.sf-label', sf).textContent.replace('*', ''))));

      } catch (e) { state.textContent = '저장 실패 — 다시 시도'; }
    };
    const schedule = debounce(save, 800);
    const onChange = () => { state.textContent = '변경됨'; refreshShowIf(form); schedule(); };
    form.addEventListener('input', onChange); form.addEventListener('change', onChange);
    $$('[data-radio]', form).forEach(b => b.onclick = () => { const wrap = b.parentElement, hid = $('input[type=hidden]', wrap), on = b.classList.contains('on'); $$('button', wrap).forEach(x => x.classList.remove('on')); if (!on) b.classList.add('on'); hid.value = on ? '' : b.dataset.radio; onChange(); });
    $$('.num input', form).forEach(i => i.addEventListener('blur', () => { const n = Number(i.value.replace(/,/g, '')); if (i.value && !isNaN(n)) i.value = n.toLocaleString(); }));
    $('[data-sheet-copy]', pane)?.addEventListener('click', async () => { const r = await fetch(box.dataset.txt); await navigator.clipboard.writeText(await r.text()); toast('상담지 요약을 복사했습니다'); });
    $('[data-sheet-print]', pane)?.addEventListener('click', () => { document.body.classList.add('print-sheet'); window.print(); setTimeout(() => document.body.classList.remove('print-sheet'), 500); });

  }

  // ---------- 문자 템플릿 편집: 미리보기 ----------
  const tplBody = $('#tpl-body');
  if (tplBody) {
    const prev = $('#tpl-prev'), by = $('#tpl-bytes');
    const upd = debounce(async () => {
      const r = await fetch(tplBody.dataset.previewUrl + '?body=' + encodeURIComponent(tplBody.value)); const j = await r.json();
      prev.textContent = j.text; by.textContent = `${j.bytes} byte · ${j.bytes > 90 ? 'LMS 장문' : 'SMS 단문'}` + (j.unresolved.length ? ` · 알 수 없는 변수: {${j.unresolved.join('} {')}}` : '');
    }, 300);
    tplBody.addEventListener('input', upd); upd();
  }

  // ---------- 상담지 양식 빌더 ----------
  const builder = $('#builder');
  if (builder) (() => {
    const init = JSON.parse($('#fb-data').textContent);
    const state = { schema: init.schema, sel: null };
    const SAVED = new Set(init.saved_keys);
    const TYPES = init.types;
    const TL = { select: '드롭다운', multi: '체크박스 묶음', radio: '세그먼트 버튼', bool: '체크박스 1개', number: '숫자', text: '한 줄', textarea: '여러 줄', date: '날짜' };
    const genKey = (label, exist) => { let b = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''); if (!/^[a-z]/.test(b)) b = 'f_' + Math.random().toString(16).slice(2, 8); let k = b, i = 2; while (exist.has(k)) k = `${b}_${i++}`; return k; };
    const allKeys = () => new Set(state.schema.sections.flatMap(s => s.fields.map(f => f.key)));
    const showErr = m => { const el = $('#fb-error'); el.textContent = m; el.hidden = false; el.scrollIntoView({ block: 'nearest' }); };

    function renderTree() {
      $('#fb-sections').innerHTML = state.schema.sections.map((s, si) => `
        <div class="fb-sec">
          <div class="fb-sec-head"><input value="${esc(s.title)}" data-sec-title="${si}" placeholder="섹션 제목">
            <span class="row"><button type="button" class="btn sm" data-mv="sec:${si}:-1">▲</button><button type="button" class="btn sm" data-mv="sec:${si}:1">▼</button><button type="button" class="btn sm" data-del-sec="${si}">삭제</button></span></div>
          ${(s.fields || []).map((f, fi) => `<button type="button" class="fb-field ${state.sel && state.sel[0] === si && state.sel[1] === fi ? 'on' : ''}" data-pick="${si}:${fi}">
              <span>${esc(f.label || '(라벨 없음)')} ${f.required ? '<i class="req-dot"></i>' : ''}</span><span class="muted small">${esc(TL[f.type] || f.type)} · <code>${esc(f.key)}</code></span></button>`).join('')}
          <div class="row"><button type="button" class="btn sm" data-add-field="${si}">+ 필드</button></div>
        </div>`).join('');
    }
    function renderProps() {
      const p = $('#fb-props');
      if (!state.sel) { p.innerHTML = '<div class="empty small">왼쪽에서 필드를 선택하세요</div>'; return; }
      const [si, fi] = state.sel, f = state.schema.sections[si].fields[fi];
      const others = state.schema.sections.flatMap(s => s.fields).filter(x => x.key !== f.key);
      const eq = f.show_if ? (typeof f.show_if.eq === 'boolean' ? String(f.show_if.eq) : f.show_if.eq) : '';
      p.innerHTML = `
        <div class="fb-head">필드 속성 <span class="row"><button type="button" class="btn sm" data-mv="fld:${si}:${fi}:-1">▲</button><button type="button" class="btn sm" data-mv="fld:${si}:${fi}:1">▼</button><button type="button" class="btn sm" data-del-field>삭제</button></span></div>
        <label>라벨<input data-p="label" value="${esc(f.label)}"></label>
        <label>key <small>${SAVED.has(f.key) ? '저장된 필드는 변경 불가 (기존 답변 보존)' : '영문 snake_case'}</small><input data-p="key" value="${esc(f.key)}" ${SAVED.has(f.key) ? 'readonly' : ''} class="mono"></label>
        <label>타입<select data-p="type">${TYPES.map(t => `<option value="${t}" ${f.type === t ? 'selected' : ''}>${esc(TL[t] || t)}</option>`).join('')}</select></label>
        <label class="check"><input type="checkbox" data-p="required" ${f.required ? 'checked' : ''}> 필수</label>
        ${['select', 'multi', 'radio'].includes(f.type) ? `<label>선택지 (한 줄에 하나)<textarea data-p="options" rows="5">${esc((f.options || []).join('\n'))}</textarea></label>` : ''}
        ${f.type === 'number' ? `<label>단위<input data-p="unit" value="${esc(f.unit || '')}" placeholder="만원 / 명 / 개월"></label>` : ''}
        <label>도움말<input data-p="help" value="${esc(f.help || '')}"></label>
        <label>표시 조건 (다른 답에 따라 표시)<select data-p="show_key"><option value="">항상 표시</option>${others.map(o => `<option value="${esc(o.key)}" ${f.show_if && f.show_if.key === o.key ? 'selected' : ''}>${esc(o.label)} (${esc(o.key)})</option>`).join('')}</select></label>
        ${f.show_if ? `<label>이 값일 때<input data-p="show_eq" value="${esc(eq)}" placeholder="true / 선택지 값"></label>` : ''}`;
      $$('[data-p]', p).forEach(el => el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', () => {
        const k = el.dataset.p, v = el.type === 'checkbox' ? el.checked : el.value;
        if (k === 'options') f.options = v.split('\n').map(x => x.trim()).filter(Boolean);
        else if (k === 'show_key') { if (v) f.show_if = { key: v, eq: f.show_if?.eq ?? true }; else delete f.show_if; renderProps(); }
        else if (k === 'show_eq') f.show_if.eq = v === 'true' ? true : v === 'false' ? false : v;
        else if (k === 'label') { f.label = v; if (!SAVED.has(f.key) && !f._keyTouched) { f.key = genKey(v, new Set([...allKeys()].filter(x => x !== f.key))); $('[data-p="key"]', p).value = f.key; } }
        else if (k === 'key') { f.key = v; f._keyTouched = true; }
        else if (k === 'type') { f.type = v; if (!['select', 'multi', 'radio'].includes(v)) delete f.options; renderProps(); }
        else if (k === 'required') f.required = v;
        else if (v) f[k] = v; else delete f[k];
        renderTree(); preview();
      }));
      $('[data-del-field]', p).onclick = () => { state.schema.sections[si].fields.splice(fi, 1); state.sel = null; refresh(); };
    }
    const clean = () => JSON.parse(JSON.stringify(state.schema, (k, v) => k.startsWith('_') ? undefined : v));
    const preview = debounce(async () => {
      const r = await fetch(builder.dataset.preview, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ schema: clean() }) });
      $('#fb-prev').innerHTML = await r.text();   // 서버가 렌더링한 조각
      $('#fb-json').value = JSON.stringify(clean(), null, 2);
    }, 250);
    function refresh() { renderTree(); renderProps(); preview(); }

    builder.addEventListener('click', e => {
      const t = e.target.closest('button'); if (!t) return;
      if (t.dataset.pick) { state.sel = t.dataset.pick.split(':').map(Number); renderTree(); renderProps(); }
      if (t.dataset.addSection !== undefined) { state.schema.sections.push({ title: '새 섹션', fields: [] }); refresh(); }
      if (t.dataset.addField) { const si = +t.dataset.addField, s = state.schema.sections[si]; s.fields.push({ key: genKey('field', allKeys()), label: '새 항목', type: 'text' }); state.sel = [si, s.fields.length - 1]; refresh(); }
      if (t.dataset.delSec !== undefined) { if (!confirm('섹션과 안의 필드를 모두 삭제할까요?')) return; state.schema.sections.splice(+t.dataset.delSec, 1); state.sel = null; refresh(); }
      if (t.dataset.mv) {
        const [kind, a, b, c] = t.dataset.mv.split(':');
        if (kind === 'sec') { const i = +a, j = i + +b, S = state.schema.sections; if (j >= 0 && j < S.length) { [S[i], S[j]] = [S[j], S[i]]; refresh(); } }
        else { const F = state.schema.sections[+a].fields, i = +b, j = i + +c; if (j >= 0 && j < F.length) { [F[i], F[j]] = [F[j], F[i]]; state.sel = [+a, j]; refresh(); } }
      }
    });
    builder.addEventListener('input', e => { if (e.target.dataset.secTitle !== undefined) { state.schema.sections[+e.target.dataset.secTitle].title = e.target.value; preview(); } });
    $('#fb-json-toggle').onclick = () => { const on = $('#fb-jsonbox').hidden; $('#fb-jsonbox').hidden = !on; $('#fb-visual').hidden = on; $('#fb-json-toggle').textContent = on ? '빌더로 편집' : 'JSON으로 편집'; };
    $('#fb-json-apply').onclick = () => { try { state.schema = JSON.parse($('#fb-json').value); state.schema.sections.forEach(s => s.fields = s.fields || []); state.sel = null; refresh(); $('#fb-error').hidden = true; } catch (err) { showErr('JSON 문법 오류: ' + err.message); } };
    $('#fb-save').onclick = async () => {
      const body = { name: $('#fb-name').value, category: $('#fb-cat').value || null, is_active: $('#fb-active').checked,
        inquiry_type_keys: $('#fb-keys').value.split(',').map(s => s.trim()).filter(Boolean), schema: clean() };
      try {
        const j = await post(builder.dataset.save, body); toast(`저장됨 · v${j.version}`); $('#fb-error').hidden = true;
        if (init.is_new) location.href = builder.dataset.save.replace(/new$/, j.id);
        else { body.schema.sections.forEach(s => s.fields.forEach(f => SAVED.add(f.key))); renderProps(); }
      } catch (err) { showErr(err.message); }
    };
    refresh();
  })();

  // 초기 바인딩: 상세 페이지
  if (detail && $('.dp', detail)) bindPanel(detail);
  const sheetInline = $('#sheet-inline');
  if (sheetInline) { const body = $('.sheet-page-body', sheetInline); body.dataset.src = sheetInline.dataset.src; bindSheet(body); }
  return { post, toast, bindPanel, applyResult };
})();

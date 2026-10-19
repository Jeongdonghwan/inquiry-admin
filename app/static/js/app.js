// 상담관리 공통 JS (모듈 패턴). Phase별로 섹션을 늘린다.
const App = (() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

  // JSON POST 공통 (CSRF 헤더 포함)
  async function post(url, data) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(data || {}) });
    return r.json();
  }

  // 모바일 사이드바
  document.querySelector('.menu-toggle')?.addEventListener('click', () => document.querySelector('.sidebar').classList.toggle('open'));

  return { post };
})();

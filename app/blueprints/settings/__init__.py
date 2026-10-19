"""설정 > 사이트·폼 연동 (admin)."""
import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from ...extensions import db
from ...models import CATEGORIES, Inquiry, Site
from ...permissions import role_required
from ...services.intake import intake

bp = Blueprint("settings", __name__, url_prefix="/settings", template_folder="../../templates")

SITE_FIELDS = ("name", "category", "color", "domain", "allowed_origins", "sender_number", "retention_days")


def _apply_form(site: Site, form) -> list[str]:
    errors = []
    code = (form.get("code") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{2,30}", code):
        errors.append("코드는 영문 소문자·숫자 2~30자")
    elif Site.query.filter(Site.code == code, Site.id != site.id).first():
        errors.append("이미 사용 중인 코드")
    site.code = code
    site.name = (form.get("name") or "").strip()[:100]
    if not site.name:
        errors.append("이름을 입력하세요")
    site.category = form.get("category") if form.get("category") in CATEGORIES else "legal"
    site.color = form.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", form.get("color") or "") else "#475569"
    site.domain = (form.get("domain") or "").strip()[:255] or None
    site.allowed_origins = "\n".join(o.strip().rstrip("/") for o in (form.get("allowed_origins") or "").splitlines() if o.strip()) or None
    site.sender_number = re.sub(r"\D", "", form.get("sender_number") or "") or None
    site.auto_reply = form.get("auto_reply") == "on"
    site.is_active = form.get("is_active") == "on"
    try:
        site.retention_days = max(30, int(form.get("retention_days") or 365))
    except ValueError:
        errors.append("보관일수는 숫자")
    return errors


@bp.get("/sites")
@role_required("admin")
def sites():
    rows = db.session.query(Site, db.func.count(Inquiry.id)).outerjoin(Inquiry).group_by(Site.id).order_by(Site.id).all()
    return render_template("settings/sites.html", rows=rows, new_secret=session.pop("new_secret", None))


@bp.route("/sites/new", methods=["GET", "POST"])
@bp.route("/sites/<int:site_id>", methods=["GET", "POST"])
@role_required("admin")
def site_form(site_id=None):
    site = db.session.get(Site, site_id) if site_id else Site(auto_reply=True, is_active=True, retention_days=365, color="#475569", category="legal")
    if site_id and site is None:
        abort(404)
    if request.method == "POST":
        errors = _apply_form(site, request.form)
        if errors:
            for e in errors:
                flash(e)
        else:
            if site.id is None:
                secret = site.issue_secret()
                site.issue_public()
                db.session.add(site)
                session["new_secret"] = {"code": site.code, "secret": secret}
            db.session.commit()
            flash(f"사이트 저장됨: {site.name}")
            return redirect(url_for("settings.sites"))
    snippet = _snippets(site) if site.id else None
    return render_template("settings/site_form.html", site=site, categories=CATEGORIES, snippet=snippet)


@bp.post("/sites/<int:site_id>/reissue")
@role_required("admin")
def reissue(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    secret = site.issue_secret()
    site.issue_public()
    db.session.commit()
    session["new_secret"] = {"code": site.code, "secret": secret}
    flash("키를 재발급했습니다. 기존 키는 더 이상 쓸 수 없습니다.")
    return redirect(url_for("settings.sites"))


@bp.post("/sites/<int:site_id>/test")
@role_required("admin")
def test_inquiry(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    r = intake(site, {"name": "테스트", "phone": "01000000000", "privacy_agreed": "1", "inquiry_type": "테스트 문의",
                      "message": f"{current_user.name} 관리자가 설정 화면에서 보낸 테스트 문의입니다.", "utm_source": "admin-test"},
               ip=request.remote_addr, user_agent="admin-test",
               company_phone=current_app.config["REPRESENTATIVE_PHONE"], default_sender=current_app.config["SMS_DEFAULT_SENDER"])
    flash(f"테스트 문의 접수됨 · No.{r.inquiry.id}" + (" · 자동문자 큐 등록" if r.auto_sms_queued else ""))
    return redirect(url_for("settings.site_form", site_id=site.id))


def _snippets(site: Site) -> dict:
    base = current_app.config["ADMIN_BASE_URL"].rstrip("/")
    server = f'''import requests
requests.post("{base}/api/v1/inquiries",
    json={{"name": name, "phone": phone, "privacy_agreed": True, "inquiry_type": area, "message": message}},
    headers={{"X-Site-Key": SITE_SECRET}}, timeout=5)   # 실패해도 사이트 폼은 "접수되었습니다" 표시 + 로컬 백업 저장'''
    browser = f'''<form id="consult">
  <input name="name" required> <input name="phone" required>
  <label><input type="checkbox" name="privacy_agreed" value="1" required> 개인정보 수집 동의</label>
  <input name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px"> <!-- 허니팟 -->
  <button>상담 신청</button>
</form>
<script>
document.getElementById('consult').addEventListener('submit', async e => {{
  e.preventDefault();
  const q = new URLSearchParams(location.search), fd = new FormData(e.target);
  fd.append('site_key', '{site.public_key}');
  ['utm_source','utm_medium','utm_campaign','utm_term'].forEach(k => fd.append(k, q.get(k) || ''));
  fd.append('landing_url', location.href); fd.append('referrer', document.referrer);
  const r = await fetch('{base}/api/v1/inquiries', {{ method: 'POST', body: fd }});
  alert(r.ok ? '상담 신청이 접수되었습니다.' : '접수에 실패했습니다. 전화로 문의해 주세요.');
}});
</script>'''
    return {"server": server, "browser": browser, "base": base}

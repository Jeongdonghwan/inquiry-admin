"""설정 > 문자 템플릿 (admin)."""
from flask import abort, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import CATEGORIES, Site, SmsTemplate
from ...permissions import role_required
from ...services.template import render as render_tpl, sms_bytes, unresolved
from . import bp


@bp.get("/templates")
@role_required("admin")
def templates():
    rows = SmsTemplate.query.order_by(SmsTemplate.sort_order, SmsTemplate.id).all()
    sites = {s.id: s for s in Site.query}
    preview = {t.id: render_tpl(t.body, name="홍길동", site_name="법률사무소 알엠", company_phone="031-000-0000") for t in rows}
    return render_template("settings/templates.html", rows=rows, sites=sites, preview=preview, bytes=sms_bytes, cats=CATEGORIES)


@bp.route("/templates/new", methods=["GET", "POST"])
@bp.route("/templates/<int:tid>", methods=["GET", "POST"])
@role_required("admin")
def template_form(tid=None):
    t = db.session.get(SmsTemplate, tid) if tid else SmsTemplate(is_active=True, sort_order=SmsTemplate.query.count())
    if tid and t is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        t.name = (f.get("name") or "").strip()[:50]
        t.body = (f.get("body") or "").strip()
        scope = f.get("scope", "all")
        t.site_id = int(scope[5:]) if scope.startswith("site:") else None
        t.category = scope[4:] if scope.startswith("cat:") else None
        t.is_auto_reply = f.get("is_auto_reply") == "on"
        t.is_active = f.get("is_active") == "on"
        if not t.name or not t.body:
            flash("이름과 내용을 입력하세요")
        elif sms_bytes(render_tpl(t.body, name="홍길동", site_name="법률사무소 알엠", company_phone="031-000-0000")) > 2000:
            flash("LMS 최대 2,000바이트를 넘습니다")
        else:
            db.session.add(t)
            db.session.commit()
            flash("템플릿 저장됨")
            return redirect(url_for("settings.templates"))
    return render_template("settings/template_form.html", t=t, sites=Site.query.filter_by(is_active=True).all(), cats=CATEGORIES)


@bp.post("/templates/<int:tid>/move")
@role_required("admin")
def template_move(tid):
    t = db.session.get(SmsTemplate, tid) or abort(404)
    rows = SmsTemplate.query.order_by(SmsTemplate.sort_order, SmsTemplate.id).all()
    i = rows.index(t)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, r in enumerate(rows):
            r.sort_order = n
        db.session.commit()
    return redirect(url_for("settings.templates"))


@bp.post("/templates/<int:tid>/delete")
@role_required("admin")
def template_delete(tid):
    t = db.session.get(SmsTemplate, tid) or abort(404)
    db.session.delete(t)
    db.session.commit()
    flash("삭제했습니다")
    return redirect(url_for("settings.templates"))


@bp.get("/templates/preview")
@role_required("admin")
def template_preview():
    body = request.args.get("body", "")
    r = render_tpl(body, name="홍길동", site_name="법률사무소 알엠", company_phone="031-000-0000")
    return {"text": r, "bytes": sms_bytes(r), "unresolved": unresolved(r)}

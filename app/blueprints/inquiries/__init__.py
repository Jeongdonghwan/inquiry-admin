from datetime import datetime

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ...extensions import db
from ...models import CLOSE_REASONS, STATUS_LABELS, STATUSES, Inquiry, Site, SmsTemplate, User
from ...permissions import get_inquiry_or_404
from ...services import inquiry as svc

bp = Blueprint("inquiries", __name__, template_folder="../../templates")
PER_PAGE = 50


def _assignable_users(user: User):
    """담당자 select 목록. agent는 본인만."""
    if user.role == "agent":
        return [user]
    return User.query.filter_by(is_active_flag=True).order_by(User.name).all()


def _panel_ctx(inq: Inquiry) -> dict:
    from ...services import sheet as sheet_svc
    site = inq.site
    tpls = (SmsTemplate.query.filter_by(is_active=True, is_auto_reply=False)
            .filter((SmsTemplate.site_id == site.id) | (SmsTemplate.site_id.is_(None)))
            .filter((SmsTemplate.category == site.category) | (SmsTemplate.category.is_(None)))
            .order_by(SmsTemplate.sort_order).all())
    from flask import current_app
    from ...services.template import render as render_tpl
    phone = current_app.config["REPRESENTATIVE_PHONE"]
    return {
        "inq": inq, "logs": sorted(inq.logs, key=lambda l: l.created_at, reverse=True),
        "dups": svc.related_duplicates(current_user, inq), "users": _assignable_users(current_user),
        "close_reasons": CLOSE_REASONS,
        "templates": [{"name": t.name, "body": render_tpl(t.body, inq, company_phone=phone)} for t in tpls],
        "sheet_incomplete": sheet_svc.sheet_incomplete(inq),
    }


def _render_panel(inq: Inquiry) -> str:
    return render_template("inquiries/_detail.html", **_panel_ctx(inq))


def _render_row(inq: Inquiry, selected_id: int | None) -> str:
    return render_template("inquiries/_row.html", r=inq, selected_id=selected_id)


def _action_response(inq: Inquiry):
    return jsonify({"ok": True, "panel_html": _render_panel(inq), "row_html": _render_row(inq, None)})


# ---------- 목록 ----------
@bp.get("/inquiries")
@login_required
def list_view():
    base, q = svc.apply_filters(svc.scoped_query(current_user), current_user, request.args)
    q = q.order_by(db.func.coalesce(Inquiry.last_received_at, Inquiry.received_at).desc())
    page = max(1, request.args.get("page", 1, type=int))
    total = q.count()
    rows = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    counts = {s: 0 for s in STATUSES}
    for status, n in base.with_entities(Inquiry.status, db.func.count(Inquiry.id)).group_by(Inquiry.status).all():
        counts[status] = n
    counts["all"] = sum(counts[s] for s in STATUSES)


    site_name = None
    if request.args.get("site"):
        s = Site.query.filter_by(code=request.args["site"]).first()
        site_name = s.name if s else None
    return render_template("inquiries/list.html", rows=rows, total=total, page=page, per_page=PER_PAGE, counts=counts,
                           site_name=site_name, users=_assignable_users(current_user),
                           sites=[s for s in Site.query.filter_by(is_active=True).order_by(Site.id)
                                  if current_user.site_ids() is None or s.id in current_user.site_ids()],
                           args=request.args, bulk_templates=_bulk_templates())


def _bulk_templates():
    ids = current_user.site_ids()
    q = SmsTemplate.query.filter_by(is_active=True, is_auto_reply=False)
    if ids is not None:
        q = q.filter((SmsTemplate.site_id.is_(None)) | (SmsTemplate.site_id.in_(ids or [-1])))
    return q.order_by(SmsTemplate.sort_order).all()


def _back_url():
    """목록·보드·대시보드에서 들어왔으면 그 화면(필터 포함)으로 돌아가기."""
    from urllib.parse import urlparse
    ref = request.referrer or ""
    if ref.startswith(request.host_url) and urlparse(ref).path in ("/inquiries", "/board", "/dashboard"):
        return ref
    return url_for("inquiries.list_view")


@bp.get("/inquiries/<int:inquiry_id>")
@login_required
def detail_view(inquiry_id):
    """전체 화면 상세 (같은 탭): 왼쪽 상담 기록·상태·문자, 오른쪽 사건별 상담지."""
    from ..sheet import render_sheet
    inq = get_inquiry_or_404(current_user, inquiry_id)
    svc.record_view(current_user, inq, request.remote_addr)
    return render_template("inquiries/detail.html", inq=inq, panel_html=_render_panel(inq), sheet_html=render_sheet(inq),
                           back_url=_back_url())


@bp.get("/inquiries/<int:inquiry_id>/panel")
@login_required
def panel(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    svc.record_view(current_user, inq, request.remote_addr)
    return _render_panel(inq)


# ---------- 액션 ----------
def _json():
    return request.get_json(silent=True) or request.form


@bp.post("/inquiries/<int:inquiry_id>/status")
@login_required
def status(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    d = _json()
    try:
        svc.change_status(inq, current_user, d.get("status"), d.get("close_reason"))
    except svc.ServiceError as e:
        return jsonify(ok=False, error=str(e)), 400
    return _action_response(inq)


@bp.post("/inquiries/<int:inquiry_id>/assign")
@login_required
def assign(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    v = _json().get("assignee_id")
    try:
        svc.assign(inq, current_user, int(v) if v not in (None, "", "null") else None)
    except svc.ServiceError as e:
        return jsonify(ok=False, error=str(e)), 400
    return _action_response(inq)


@bp.post("/inquiries/<int:inquiry_id>/callback")
@login_required
def callback(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    v = _json().get("callback_at")
    try:
        at = datetime.fromisoformat(v) if v else None
    except ValueError:
        return jsonify(ok=False, error="일시 형식이 올바르지 않습니다"), 400
    svc.set_callback(inq, current_user, at)
    return _action_response(inq)


@bp.post("/inquiries/<int:inquiry_id>/logs")
@login_required
def logs(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    d = _json()
    try:
        svc.add_record(inq, current_user, d.get("kind"), d.get("body", ""))
    except svc.ServiceError as e:
        return jsonify(ok=False, error=str(e)), 400
    return _action_response(inq)


@bp.post("/inquiries/<int:inquiry_id>/sms")
@login_required
def send_sms(inquiry_id):
    from ...services.sms import queue as sms_q
    inq = get_inquiry_or_404(current_user, inquiry_id)
    d = _json()
    try:
        at = datetime.fromisoformat(d["scheduled_at"]) if d.get("scheduled_at") else None
        sms_q.enqueue(inq, current_user, d.get("body", ""), at)
    except (sms_q.SmsError, ValueError) as e:
        return jsonify(ok=False, error=str(e)), 400
    db.session.refresh(inq)
    return _action_response(inq)


@bp.post("/inquiries/<int:inquiry_id>/info")
@login_required
def update_info(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    try:
        svc.update_info(inq, current_user, _json())
    except svc.ServiceError as e:
        return jsonify(ok=False, error=str(e)), 400
    return _action_response(inq)


@bp.post("/inquiries/bulk-sms")
@login_required
def bulk_sms():
    """목록에서 선택한 문의들에 같은 문구(변수 치환)로 일괄 발송."""
    from flask import current_app
    from ...permissions import can_access
    from ...services.sms import queue as sms_q
    from ...services.template import render as render_tpl
    d = _json()
    body = (d.get("body") or "").strip()
    ids = [int(x) for x in (d.get("ids") or []) if str(x).isdigit()][:300]
    if not body or not ids:
        return jsonify(ok=False, error="받을 문의와 문자 내용을 확인하세요"), 400
    sent = failed = skipped = 0
    phone = current_app.config["REPRESENTATIVE_PHONE"]
    for i in ids:
        inq = db.session.get(Inquiry, i)
        if inq is None or not can_access(current_user, inq) or inq.is_masked:
            skipped += 1
            continue
        try:
            m = sms_q.enqueue(inq, current_user, render_tpl(body, inq, company_phone=phone))
            sent += m.status == "sent"
            failed += m.status != "sent"
        except sms_q.SmsError:
            failed += 1
    return jsonify(ok=True, sent=sent, failed=failed, skipped=skipped)


# ---------- 직접 등록 ----------
@bp.post("/inquiries")
@login_required
def create_manual():
    from ...services.intake import IntakeError
    site = db.session.get(Site, request.form.get("site_id", type=int)) or abort(400)
    try:
        inq = svc.create_manual(current_user, site, request.form.to_dict())
    except (svc.ServiceError, IntakeError) as e:
        return render_template("inquiries/list.html", rows=[], total=0, page=1, per_page=PER_PAGE,
                               counts={s: 0 for s in STATUSES} | {"all": 0}, site_name=None,
                               users=_assignable_users(current_user), sites=Site.query.filter_by(is_active=True).all(),
                               args=request.args,
                               manual_error={"name_invalid": "이름을 확인하세요", "phone_invalid": "연락처 형식이 올바르지 않습니다"}.get(str(e), str(e))), 400
    return redirect(url_for("inquiries.detail_view", inquiry_id=inq.id))


# ---------- 배지 ----------
@bp.get("/api/badge")
@login_required
def badge():
    return jsonify(svc.badge_counts(current_user))

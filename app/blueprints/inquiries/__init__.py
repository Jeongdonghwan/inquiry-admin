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
    return {
        "inq": inq, "logs": sorted(inq.logs, key=lambda l: l.created_at, reverse=True),
        "dups": svc.related_duplicates(inq), "users": _assignable_users(current_user),
        "close_reasons": CLOSE_REASONS, "templates": tpls,
        "sheet_required_missing": sheet_svc.required_missing(inq),
    }


def _render_panel(inq: Inquiry, layout: str | None = None) -> str:
    tpl = "inquiries/_drawer.html" if layout == "drawer" else "inquiries/_detail.html"
    return render_template(tpl, **_panel_ctx(inq))


def _render_row(inq: Inquiry, selected_id: int | None) -> str:
    return render_template("inquiries/_row.html", r=inq, selected_id=selected_id)


def _action_response(inq: Inquiry):
    layout = request.args.get("layout")
    html = {"ok": True, "panel_html": _render_panel(inq, layout)}
    if layout == "drawer":
        html["card_html"] = render_template("board/_card.html", it=inq)
    else:
        html["row_html"] = _render_row(inq, inq.id)
    return jsonify(html)


# ---------- 목록 ----------
@bp.get("/inquiries")
@login_required
def list_view():
    base, q = svc.apply_filters(svc.scoped_query(current_user), current_user, request.args)
    if request.args.get("cb") == "today":
        q = q.order_by(Inquiry.callback_at.asc())
    else:
        q = q.order_by(Inquiry.received_at.desc())
    page = max(1, request.args.get("page", 1, type=int))
    total = q.count()
    rows = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    counts = {s: 0 for s in STATUSES}
    for status, n in base.with_entities(Inquiry.status, db.func.count(Inquiry.id)).group_by(Inquiry.status).all():
        counts[status] = n
    counts["all"] = sum(counts[s] for s in STATUSES)

    selected = None
    sel_id = request.args.get("id", type=int)
    if sel_id:
        selected = db.session.get(Inquiry, sel_id)
        if selected is None or not svc.can_access(current_user, selected):
            selected = None
    elif rows and not request.args.get("nosel"):
        selected = rows[0]
    if selected:
        svc.record_view(current_user, selected, request.remote_addr)

    site_name = None
    if request.args.get("site"):
        s = Site.query.filter_by(code=request.args["site"]).first()
        site_name = s.name if s else None
    return render_template("inquiries/list.html", rows=rows, total=total, page=page, per_page=PER_PAGE, counts=counts,
                           selected=selected, panel_html=_render_panel(selected) if selected else None,
                           site_name=site_name, users=_assignable_users(current_user),
                           sites=[s for s in Site.query.filter_by(is_active=True).order_by(Site.id)
                                  if current_user.site_ids() is None or s.id in current_user.site_ids()],
                           args=request.args, is_callback_view=request.args.get("cb") == "today")


@bp.get("/inquiries/<int:inquiry_id>/panel")
@login_required
def panel(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    svc.record_view(current_user, inq, request.remote_addr)
    return _render_panel(inq, request.args.get("layout"))


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


# ---------- 수동 등록 ----------
@bp.post("/inquiries")
@login_required
def create_manual():
    from ...services.intake import IntakeError
    site = db.session.get(Site, request.form.get("site_id", type=int)) or abort(400)
    try:
        inq = svc.create_manual(current_user, site, request.form.to_dict())
    except (svc.ServiceError, IntakeError) as e:
        return render_template("inquiries/list.html", rows=[], total=0, page=1, per_page=PER_PAGE,
                               counts={s: 0 for s in STATUSES} | {"all": 0}, selected=None, panel_html=None, site_name=None,
                               users=_assignable_users(current_user), sites=Site.query.filter_by(is_active=True).all(),
                               args=request.args, is_callback_view=False,
                               manual_error={"name_invalid": "이름을 확인하세요", "phone_invalid": "연락처 형식이 올바르지 않습니다"}.get(str(e), str(e))), 400
    return redirect(url_for("inquiries.list_view", id=inq.id))


# ---------- 배지 ----------
@bp.get("/api/badge")
@login_required
def badge():
    return jsonify(svc.badge_counts(current_user))

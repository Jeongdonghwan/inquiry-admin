"""문자 발송내역 (CLAUDE.md 7-6)."""
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ... import now_kst
from ...extensions import db
from ...models import Site, SmsMessage, User
from ...services.sms import queue as q

bp = Blueprint("sms", __name__, url_prefix="/sms", template_folder="../../templates")
PER_PAGE = 50
STATUS_LABELS = {"queued": "대기", "scheduled": "예약", "sending": "발송중", "sent": "성공", "failed": "실패", "canceled": "취소"}


def _scoped():
    qs = SmsMessage.query
    ids = current_user.site_ids()
    if ids is not None:
        qs = qs.filter(SmsMessage.site_id.in_(ids or [-1]))
    return qs


@bp.get("/")
@login_required
def list_view():
    qs = _scoped()
    a = request.args
    if a.get("site"):
        qs = qs.join(Site).filter(Site.code == a["site"])
    if a.get("status") in STATUS_LABELS:
        qs = qs.filter(SmsMessage.status == a["status"])
    if a.get("auto") in ("1", "0"):
        qs = qs.filter(SmsMessage.is_auto.is_(a["auto"] == "1"))
    days = {"today": 0, "7": 7, "30": 30}.get(a.get("period"))
    if days is not None:
        qs = qs.filter(SmsMessage.created_at >= datetime.combine(now_kst().date() - timedelta(days=days), datetime.min.time()))
    page = max(1, a.get("page", 1, type=int))
    total = qs.count()
    rows = qs.order_by(SmsMessage.created_at.desc()).offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    sites = [s for s in Site.query.filter_by(is_active=True).order_by(Site.id) if current_user.site_ids() is None or s.id in current_user.site_ids()]
    return render_template("sms/list.html", rows=rows, total=total, page=page, per_page=PER_PAGE, sites=sites, args=a,
                           labels=STATUS_LABELS, site_map={s.id: s for s in Site.query},
                           users={u.id: u for u in User.query})


def _get(mid):
    m = _scoped().filter(SmsMessage.id == mid).first()
    return m or abort(404)


@bp.post("/<int:mid>/cancel")
@login_required
def cancel(mid):
    try:
        q.cancel(_get(mid), current_user)
        flash("취소했습니다.")
    except q.SmsError as e:
        flash(str(e))
    return redirect(request.referrer or url_for("sms.list_view"))


@bp.post("/<int:mid>/retry")
@login_required
def retry(mid):
    try:
        ok = q.retry(_get(mid), current_user)
        flash("재발송 성공" if ok else "재발송 실패 — 사유를 확인하세요")
    except q.SmsError as e:
        flash(str(e))
    return redirect(request.referrer or url_for("sms.list_view"))

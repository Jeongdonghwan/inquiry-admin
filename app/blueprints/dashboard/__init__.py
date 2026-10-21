"""메인 대시보드: 오늘 할 일 중심 요약."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from ... import now_kst
from ...extensions import db
from ...models import STATUS_LABELS, Inquiry, InquiryLog, Site, SmsMessage
from ...services import inquiry as svc

bp = Blueprint("dashboard", __name__, template_folder="../../templates")


@bp.get("/dashboard")
@login_required
def dashboard():
    now = now_kst()
    today = datetime.combine(now.date(), datetime.min.time())
    week = today - timedelta(days=6)
    q = svc.scoped_query(current_user)
    ids = current_user.site_ids()

    kpi = {
        "today": q.filter(Inquiry.received_at >= today).count(),
        "new": q.filter(Inquiry.status == "new").count(),
        "unassigned": q.filter(Inquiry.assignee_id.is_(None), Inquiry.status.notin_(["closed", "contracted"])).count(),
        "active": q.filter(Inquiry.status.in_(["contacting", "consulted", "hold"])).count(),
        "won_week": q.filter(Inquiry.status == "contracted", Inquiry.contracted_at >= week).count(),
        "mine": q.filter(Inquiry.assignee_id == current_user.id, Inquiry.status.notin_(["closed", "contracted"])).count(),
    }
    status_counts = {s: 0 for s in STATUS_LABELS}
    for s, n in q.with_entities(Inquiry.status, func.count(Inquiry.id)).group_by(Inquiry.status):
        status_counts[s] = n
    total = sum(status_counts.values()) or 1

    sites_q = db.session.query(Site, func.count(Inquiry.id)).outerjoin(Inquiry, (Inquiry.site_id == Site.id) & (Inquiry.received_at >= week)) \
        .filter(Site.is_active)
    if ids is not None:
        sites_q = sites_q.filter(Site.id.in_(ids or [-1]))
    site_rows = sites_q.group_by(Site.id).order_by(func.count(Inquiry.id).desc()).all()
    site_max = max((n for _, n in site_rows), default=0) or 1

    daily = {(week + timedelta(days=i)).date(): 0 for i in range(7)}
    for d, n in q.filter(Inquiry.received_at >= week).with_entities(func.date(Inquiry.received_at), func.count(Inquiry.id)) \
            .group_by(func.date(Inquiry.received_at)):
        d = d if hasattr(d, "year") else datetime.fromisoformat(str(d)).date()
        if d in daily:
            daily[d] = n
    daily_max = max(daily.values()) or 1

    recent_new = q.filter(Inquiry.status == "new").order_by(Inquiry.received_at.desc()).limit(8).all()
    recent_logs = (InquiryLog.query.join(Inquiry).filter(Inquiry.id.in_(q.with_entities(Inquiry.id)))
                   .filter(InquiryLog.kind.in_(["call", "call_missed", "memo", "status", "sms"]))
                   .order_by(InquiryLog.created_at.desc()).limit(8).all())
    sms_fail = SmsMessage.query.filter(SmsMessage.status == "failed")
    if ids is not None:
        sms_fail = sms_fail.filter(SmsMessage.site_id.in_(ids or [-1]))
    return render_template("dashboard/dashboard.html", kpi=kpi, status_counts=status_counts, total=total,
                           site_rows=site_rows, site_max=site_max, daily=daily, daily_max=daily_max,
                           recent_new=recent_new, recent_logs=recent_logs, sms_failed=sms_fail.count())

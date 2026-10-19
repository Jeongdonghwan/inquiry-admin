"""보드 보기 B안 (CLAUDE.md 7-5). 목록과 같은 데이터, 상태 6칸 + 서랍 상세."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from ... import now_kst
from ...models import STATUS_LABELS, Inquiry, Site
from ...services import inquiry as svc

bp = Blueprint("board", __name__, template_folder="../../templates")


@bp.get("/board")
@login_required
def board_view():
    args = request.args.to_dict()
    args.pop("status", None)
    base, q = svc.apply_filters(svc.scoped_query(current_user), current_user, args)
    today = now_kst().date()
    day0 = datetime.combine(today, datetime.min.time())
    rows = base.order_by(Inquiry.received_at.desc()).all()
    cols = {s: [] for s in STATUS_LABELS}
    for r in rows:
        if r.status == "closed" and r.closed_at and r.closed_at < day0 - timedelta(days=30):
            continue  # 종결 칸은 최근 30일만
        cols[r.status].append(r)
    scoped = svc.scoped_query(current_user)
    summary = {
        "today": scoped.filter(Inquiry.received_at >= day0).count(),
        "unassigned": scoped.filter(Inquiry.assignee_id.is_(None), Inquiry.status.notin_(["closed", "contracted"])).count(),
        "cb": scoped.filter(Inquiry.callback_at >= day0, Inquiry.callback_at < day0 + timedelta(days=1)).count(),
        "won": scoped.filter(Inquiry.status == "contracted").count(), "total": scoped.count(),
    }
    sites = [s for s in Site.query.filter_by(is_active=True).order_by(Site.id)
             if current_user.site_ids() is None or s.id in current_user.site_ids()]
    sel = None
    if request.args.get("id", type=int):
        sel = Inquiry.query.get(request.args.get("id", type=int))
        if sel and not svc.can_access(current_user, sel):
            sel = None
    from ..inquiries import _render_panel
    return render_template("board/board.html", cols=cols, summary=summary, sites=sites, args=request.args, selected=sel,
                           drawer_html=_render_panel(sel, "drawer") if sel else None)

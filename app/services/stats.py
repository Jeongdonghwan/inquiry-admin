"""통계 (CLAUDE.md 7-6 /stats)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from ..models import Inquiry, Site, User
from . import inquiry as inq_svc


def period_bounds(period: str, frm: str | None, to: str | None):
    from .. import now_kst
    today = now_kst().date()
    if period == "custom" and frm:
        start = datetime.fromisoformat(frm)
        end = datetime.fromisoformat(to) + timedelta(days=1) if to else datetime.combine(today + timedelta(days=1), datetime.min.time())
    else:
        days = {"7": 7, "30": 30, "90": 90}.get(period, 30)
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    return start, end


def build(user: User, period: str = "30", frm: str | None = None, to: str | None = None) -> dict:
    start, end = period_bounds(period, frm, to)
    rows = inq_svc.scoped_query(user).filter(Inquiry.received_at >= start, Inquiry.received_at < end).all()

    by_site = defaultdict(lambda: {"received": 0, "contracted": 0, "closed": 0})
    daily = Counter()
    by_assignee = defaultdict(lambda: {"handled": 0, "contracted": 0})
    keywords = Counter()
    response_minutes = []
    for r in rows:
        s = by_site[r.site_id]
        s["received"] += 1
        s["contracted"] += r.status == "contracted"
        s["closed"] += r.status == "closed"
        daily[r.received_at.date()] += 1
        if r.assignee_id:
            a = by_assignee[r.assignee_id]
            a["handled"] += 1
            a["contracted"] += r.status == "contracted"
        if r.utm_term:
            keywords[r.utm_term] += 1
        if r.first_contact_at:
            response_minutes.append((r.first_contact_at - r.received_at).total_seconds() / 60)

    sites = {s.id: s for s in Site.query}
    users = {u.id: u for u in User.query}
    days = [(start + timedelta(days=i)).date() for i in range((end - start).days)]
    maxd = max(daily.values(), default=0)
    return {
        "start": start, "end": end - timedelta(days=1), "total": len(rows),
        "contracted": sum(1 for r in rows if r.status == "contracted"),
        "sites": [{"site": sites[k], **v, "rate": round(v["contracted"] / v["received"] * 100, 1) if v["received"] else 0}
                  for k, v in sorted(by_site.items(), key=lambda kv: -kv[1]["received"])],
        "daily": [{"date": d, "n": daily.get(d, 0), "pct": round(daily.get(d, 0) / maxd * 100) if maxd else 0} for d in days],
        "median_response": round(median(response_minutes)) if response_minutes else None,
        "assignees": [{"user": users[k], **v} for k, v in sorted(by_assignee.items(), key=lambda kv: -kv[1]["handled"]) if k in users],
        "keywords": keywords.most_common(20),
    }

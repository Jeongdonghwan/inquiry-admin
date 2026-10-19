"""개인정보 보관기간 처리 (CLAUDE.md 9). 통계용 숫자(사이트·상태·일시·utm)는 남긴다."""
from datetime import timedelta

from .. import now_kst
from ..extensions import db
from ..models import ConsultSheet, Inquiry, InquiryLog, Site, SmsMessage

DELETED = "[보관기간 경과로 삭제]"


def mask_name(name: str) -> str:
    if not name:
        return name
    return name[0] + "*" * max(1, len(name) - 2) + (name[-1] if len(name) > 2 else "")


def mask_phone(phone: str) -> str:
    d = "".join(ch for ch in phone if ch.isdigit())
    return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 10 else "***"


def mask_inquiry(inq: Inquiry) -> None:
    inq.customer_name = mask_name(inq.customer_name)
    inq.phone = mask_phone(inq.phone)
    inq.message = DELETED if inq.message else None
    inq.extra_json = None
    inq.ip = None
    inq.user_agent = None
    inq.region = None
    inq.is_masked = True
    for lg in InquiryLog.query.filter_by(inquiry_id=inq.id):
        if lg.kind in ("memo", "call", "call_missed", "sms"):
            lg.body = DELETED
    for m in SmsMessage.query.filter_by(inquiry_id=inq.id):
        m.body = DELETED
        m.to_phone = mask_phone(m.to_phone)
    for s in ConsultSheet.query.filter_by(inquiry_id=inq.id):
        s.answers_json = {"_masked": True}


def sweep() -> int:
    """closed_at 또는 contracted_at 이 sites.retention_days 를 넘긴 건을 마스킹."""
    now = now_kst()
    n = 0
    for site in Site.query:
        cutoff = now - timedelta(days=site.retention_days)
        q = Inquiry.query.filter(Inquiry.site_id == site.id, Inquiry.is_masked.is_(False),
                                 Inquiry.status.in_(["closed", "contracted"]),
                                 db.or_(Inquiry.closed_at <= cutoff, Inquiry.contracted_at <= cutoff))
        for inq in q:
            mask_inquiry(inq)
            n += 1
    db.session.commit()
    return n

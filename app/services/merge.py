"""같은 연락처 = 문의 1건. 재문의 편입과 기존 중복 일괄 통합."""
from collections import defaultdict

from sqlalchemy import or_

from .. import now_kst
from ..extensions import db
from ..models import AccessLog, ConsultSheet, Inquiry, InquiryLog, SmsMessage

REOPEN_FROM = ("closed",)  # 종결 건에 재문의가 오면 신규로 되돌림


def find_existing(phone: str) -> Inquiry | None:
    """연락처(또는 추가 연락처)가 같은 가장 최근 문의. 마스킹된 건은 제외."""
    return (Inquiry.query.filter(or_(Inquiry.phone == phone, Inquiry.phone2 == phone), Inquiry.is_masked.is_(False))
            .order_by(Inquiry.received_at.desc()).first())


def reinquire(inq: Inquiry, *, source: str, message: str | None, user=None, inquiry_type: str | None = None) -> None:
    """기존 문의에 재문의를 붙인다. 커밋은 호출자가."""
    now = now_kst()
    body = f"{source} 재문의" + (f" ({inquiry_type})" if inquiry_type and inquiry_type != inq.inquiry_type else "")
    if message:
        body += f"\n{message}"
    db.session.add(InquiryLog(inquiry_id=inq.id, kind="received", user_id=user.id if user else None, body=body,
                              meta_json={"reinquiry": True}, created_at=now))
    if inq.status in REOPEN_FROM:
        db.session.add(InquiryLog(inquiry_id=inq.id, kind="status", user_id=user.id if user else None,
                                  body="종결 → 신규 (재문의로 다시 열림)", meta_json={"from": inq.status, "to": "new", "auto": True},
                                  created_at=now))
        inq.status, inq.closed_at, inq.close_reason = "new", None, None
    inq.last_received_at = now


def merge_duplicates() -> int:
    """같은 연락처 문의를 가장 먼저 접수된 건으로 합친다. 합친 건수 반환."""
    groups = defaultdict(list)
    for inq in Inquiry.query.filter(Inquiry.is_masked.is_(False)).order_by(Inquiry.received_at):
        groups[inq.phone].append(inq)
    merged = 0
    for items in groups.values():
        if len(items) < 2:
            continue
        primary, others = items[0], items[1:]
        primary_forms = {s.form_id for s in ConsultSheet.query.filter_by(inquiry_id=primary.id, is_current=True)}
        for o in others:
            InquiryLog.query.filter_by(inquiry_id=o.id).update({"inquiry_id": primary.id})
            SmsMessage.query.filter_by(inquiry_id=o.id).update({"inquiry_id": primary.id})
            AccessLog.query.filter_by(inquiry_id=o.id).update({"inquiry_id": primary.id})
            for s in ConsultSheet.query.filter_by(inquiry_id=o.id):
                s.inquiry_id = primary.id
                if s.is_current and s.form_id in primary_forms:
                    s.is_current = False  # 같은 양식이 이미 있으면 기존 것을 유지
                primary_forms.add(s.form_id)
            db.session.add(InquiryLog(inquiry_id=primary.id, kind="system", created_at=now_kst(),
                                      body=f"No.{o.id} 문의를 통합 ({o.site.name} · {o.received_at:%Y.%m.%d %H:%M}"
                                           + (f" · {o.inquiry_type}" if o.inquiry_type else "") + ")"
                                           + (f"\n{o.message}" if o.message else "")))
            if primary.status == "closed" and o.status != "closed":
                primary.status, primary.closed_at, primary.close_reason = o.status, None, None
            primary.assignee_id = primary.assignee_id or o.assignee_id
            primary.last_received_at = max(filter(None, [primary.last_received_at, o.received_at]))
            Inquiry.query.filter_by(duplicate_of_id=o.id).update({"duplicate_of_id": None})
            db.session.flush()
            db.session.expire(o)  # 옮긴 기록이 delete-orphan cascade 로 지워지지 않게 관계를 새로 읽힘
            db.session.delete(o)
            merged += 1
        primary.duplicate_of_id = None
    db.session.commit()
    return merged

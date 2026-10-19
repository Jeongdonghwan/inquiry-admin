"""문자 큐 적재·즉시 발송·워커 (CLAUDE.md 6-2)."""
from datetime import datetime

from flask import current_app
from sqlalchemy import or_

from ... import now_kst
from ...extensions import db
from ...models import Inquiry, SmsMessage, User
from .. import inquiry as inq_svc
from ..template import LMS_MAX, msg_type, sms_bytes
from .aligo import AligoProvider
from .base import SmsProvider
from .dummy import DummyProvider

MAX_ATTEMPTS = 3
_dummy = DummyProvider()


def provider() -> SmsProvider:
    cfg = current_app.config
    if cfg.get("SMS_PROVIDER") == "aligo":
        return AligoProvider(cfg["ALIGO_API_KEY"], cfg["ALIGO_USER_ID"], testmode=cfg.get("ALIGO_TESTMODE", "Y") != "N")
    return _dummy


class SmsError(ValueError):
    pass


def enqueue(inq: Inquiry, user: User, body: str, scheduled_at: datetime | None = None) -> SmsMessage:
    inq_svc._check(user, inq)
    body = (body or "").strip()
    if not body:
        raise SmsError("문자 내용을 입력하세요")
    n = sms_bytes(body)
    if n > LMS_MAX:
        raise SmsError(f"LMS 최대 {LMS_MAX}바이트를 넘었습니다 ({n}바이트)")
    if scheduled_at and scheduled_at <= now_kst():
        raise SmsError("예약 시각은 현재 이후여야 합니다")
    msg = SmsMessage(inquiry_id=inq.id, site_id=inq.site_id, user_id=user.id, to_phone=inq.phone,
                     from_phone=inq.site.sender_number or current_app.config["SMS_DEFAULT_SENDER"], body=body,
                     msg_type=msg_type(body), byte_len=n, status="scheduled" if scheduled_at else "queued",
                     scheduled_at=scheduled_at, created_at=now_kst())
    db.session.add(msg)
    db.session.flush()
    if scheduled_at:
        inq_svc.log(inq, user, "sms", f"[예약 {scheduled_at:%m.%d %H:%M}] {body}", {"sms_id": msg.id, "scheduled": True})
        db.session.commit()
        return msg
    inq_svc.log(inq, user, "sms", body, {"sms_id": msg.id})
    db.session.commit()
    deliver(msg)  # 지금 보내기: 요청 안에서 1회 시도, 실패하면 queued 유지
    return msg


def deliver(msg: SmsMessage) -> bool:
    """1건 발송 시도. 선점(sending) → 결과 반영 → 로그."""
    if msg.status not in ("queued", "scheduled"):
        return msg.status == "sent"
    msg.status = "sending"
    msg.attempts += 1
    db.session.commit()
    p = provider()
    ok, pid, err = p.send(msg.to_phone, msg.from_phone, msg.body, msg.msg_type)
    msg.provider = p.name
    if ok:
        msg.status, msg.provider_msg_id, msg.sent_at, msg.error = "sent", pid, now_kst(), None
        if msg.is_auto and msg.inquiry_id:
            pass  # 자동문자는 접수 시 이미 로그됨
    else:
        msg.error = err
        msg.status = "failed" if msg.attempts >= MAX_ATTEMPTS else ("scheduled" if msg.scheduled_at else "queued")
        if msg.inquiry_id:
            inq = db.session.get(Inquiry, msg.inquiry_id)
            inq_svc.log(inq, None, "system", f"문자 발송 실패: {err}" + (" (재시도 예정)" if msg.status != "failed" else ""),
                        {"sms_id": msg.id})
    db.session.commit()
    return ok


def run_worker(limit: int = 200) -> dict:
    """crontab 1분 주기. queued 전부 + scheduled_at <= now 인 scheduled."""
    now = now_kst()
    ids = [m.id for m in SmsMessage.query.filter(
        or_(SmsMessage.status == "queued", (SmsMessage.status == "scheduled") & (SmsMessage.scheduled_at <= now)))
        .order_by(SmsMessage.id).limit(limit)]
    sent = failed = 0
    for mid in ids:
        # 동시 실행 대비: status가 아직 대기 상태인 행만 선점 (UPDATE ... WHERE status IN (...))
        claimed = db.session.query(SmsMessage).filter(SmsMessage.id == mid, SmsMessage.status.in_(["queued", "scheduled"])) \
            .update({"status": "sending", "attempts": SmsMessage.attempts + 1}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        msg = db.session.get(SmsMessage, mid)
        msg.status = "queued" if not msg.scheduled_at else "scheduled"
        msg.attempts -= 1  # deliver()가 다시 올림
        if deliver(msg):
            sent += 1
        elif msg.status == "failed":
            failed += 1
    return {"picked": len(ids), "sent": sent, "failed": failed}


def cancel(msg: SmsMessage, user: User) -> None:
    if msg.status not in ("queued", "scheduled"):
        raise SmsError("대기 중인 문자만 취소할 수 있습니다")
    msg.status = "canceled"
    if msg.inquiry_id:
        inq_svc.log(db.session.get(Inquiry, msg.inquiry_id), user, "system", "예약 문자 취소", {"sms_id": msg.id})
    db.session.commit()


def retry(msg: SmsMessage, user: User) -> bool:
    if msg.status != "failed":
        raise SmsError("실패한 문자만 재발송할 수 있습니다")
    msg.status, msg.attempts, msg.error = "queued", 0, None
    db.session.commit()
    return deliver(msg)

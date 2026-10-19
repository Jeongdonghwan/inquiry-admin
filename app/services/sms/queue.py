"""문자 큐 적재·즉시 발송·워커 (CLAUDE.md 6-2).

발송 선점은 deliver() 안의 원자적 UPDATE 한 곳에서만 한다 → 요청 경로와 cron 워커가 겹쳐도 중복 발송 없음.
"""
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
WAITING = ("queued", "scheduled")
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
    prefix = f"[예약 {scheduled_at:%m.%d %H:%M}] " if scheduled_at else ""
    inq_svc.log(inq, user, "sms", prefix + body, {"sms_id": msg.id, "scheduled": bool(scheduled_at)})
    db.session.commit()
    if not scheduled_at:
        deliver(msg)  # 지금 보내기: 요청 안에서 1회 시도, 실패하면 queued 유지 → 워커가 재시도
    return msg


def _claim(msg_id: int) -> bool:
    """대기 상태인 행만 원자적으로 sending 으로 선점."""
    n = (db.session.query(SmsMessage).filter(SmsMessage.id == msg_id, SmsMessage.status.in_(WAITING))
         .update({"status": "sending", "attempts": SmsMessage.attempts + 1}, synchronize_session=False))
    db.session.commit()
    return bool(n)


def deliver(msg: SmsMessage) -> bool:
    if not _claim(msg.id):
        db.session.refresh(msg)
        return msg.status == "sent"
    db.session.refresh(msg)
    ok, pid, err = False, None, None
    try:
        p = provider()
        msg.provider = p.name
        ok, pid, err = p.send(msg.to_phone, msg.from_phone, msg.body, msg.msg_type)
    except Exception as e:  # 발송사 설정 오류·네트워크 예외 → 실패로 기록, sending 고착 방지
        err = f"{type(e).__name__}: {e}"[:500]
    if ok:
        msg.status, msg.provider_msg_id, msg.sent_at, msg.error = "sent", pid, now_kst(), None
    else:
        msg.error = err
        msg.status = "failed" if msg.attempts >= MAX_ATTEMPTS else ("scheduled" if msg.scheduled_at else "queued")
        if msg.inquiry_id:
            inq = db.session.get(Inquiry, msg.inquiry_id)
            inq_svc.log(inq, None, "system", f"문자 발송 실패: {err}" + ("" if msg.status == "failed" else " (재시도 예정)"),
                        {"sms_id": msg.id})
    db.session.commit()
    return ok


def run_worker(limit: int = 200) -> dict:
    """crontab 1분 주기. queued 전부 + scheduled_at <= now 인 scheduled."""
    now = now_kst()
    msgs = SmsMessage.query.filter(
        or_(SmsMessage.status == "queued", (SmsMessage.status == "scheduled") & (SmsMessage.scheduled_at <= now))
    ).order_by(SmsMessage.id).limit(limit).all()
    sent = failed = 0
    for m in msgs:
        if deliver(m):
            sent += 1
        elif m.status == "failed":
            failed += 1
    return {"picked": len(msgs), "sent": sent, "failed": failed}


def cancel(msg: SmsMessage, user: User) -> None:
    if msg.status not in WAITING:
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

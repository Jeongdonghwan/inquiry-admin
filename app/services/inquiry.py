"""문의 변경 서비스 (CLAUDE.md 8). 모든 변경은 여기서 + inquiry_logs 기록을 한 트랜잭션에.

라우트는 모델을 직접 고치지 않는다. 권한은 진입 시 can_access 로 통일.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_

from .. import now_kst
from ..extensions import db
from ..models import CLOSE_REASONS, STATUS_LABELS, STATUSES, AccessLog, Inquiry, InquiryLog, Site, User
from ..permissions import can_access



class ServiceError(ValueError):
    pass


def _check(user: User, inq: Inquiry) -> None:
    if not can_access(user, inq):
        from flask import abort
        abort(404)


def log(inq: Inquiry, user: User | None, kind: str, body: str, meta: dict | None = None) -> InquiryLog:
    entry = InquiryLog(inquiry_id=inq.id, kind=kind, user_id=user.id if user else None, body=body, meta_json=meta,
                       created_at=now_kst())
    db.session.add(entry)
    return entry


def fmt_callback(dt: datetime | None) -> str:
    from .. import kcallback_str
    return kcallback_str(dt) if dt else ""


# ---- 상태 ----
def change_status(inq: Inquiry, user: User, status: str, close_reason: str | None = None) -> None:
    _check(user, inq)
    if status not in STATUSES:
        raise ServiceError("상태값이 올바르지 않습니다")
    if status == inq.status:
        return
    if status == "closed":
        if not close_reason or (close_reason not in CLOSE_REASONS and not close_reason.startswith("기타")):
            raise ServiceError("종결 사유를 선택하세요")
    now = now_kst()
    prev = inq.status
    inq.status = status
    inq.close_reason = close_reason[:100] if status == "closed" else None
    if prev == "new" and inq.first_contact_at is None:
        inq.first_contact_at = now
    if status == "contracted":
        inq.contracted_at = now
    if status == "closed":
        inq.closed_at = now
    body = f"{STATUS_LABELS[prev]} → {STATUS_LABELS[status]}"
    if status == "closed":
        body += f" (사유: {close_reason})"
    log(inq, user, "status", body, {"from": prev, "to": status})
    db.session.commit()


# ---- 배정 ----
def assign(inq: Inquiry, user: User, assignee_id: int | None) -> None:
    _check(user, inq)
    if user.role == "agent" and assignee_id not in (None, user.id):
        raise ServiceError("상담원은 본인에게만 배정할 수 있습니다")
    new = db.session.get(User, assignee_id) if assignee_id else None
    if assignee_id and (new is None or not new.is_active):
        raise ServiceError("담당자를 찾을 수 없습니다")
    if (inq.assignee_id or None) == (assignee_id or None):
        return
    prev = inq.assignee.display if inq.assignee else "미배정"
    inq.assignee_id = assignee_id
    log(inq, user, "assign", f"담당자 {prev} → {new.display if new else '미배정'}",
        {"from": None if prev == "미배정" else prev, "to": assignee_id})
    db.session.commit()


# ---- 콜백 ----
def set_callback(inq: Inquiry, user: User, at: datetime | None) -> None:
    _check(user, inq)
    if inq.callback_at == at:
        return
    inq.callback_at = at
    log(inq, user, "callback", f"콜백 예약 {fmt_callback(at)}" if at else "콜백 예약 해제", {"at": at.isoformat() if at else None})
    db.session.commit()


# ---- 상담 기록 ----
def add_record(inq: Inquiry, user: User, kind: str, body: str) -> None:
    _check(user, inq)
    body = (body or "").strip()
    if kind == "memo":
        if not body:
            raise ServiceError("메모 내용을 입력하세요")
        text = body
    elif kind == "call":
        text = f"통화 완료 · {body}" if body else "통화 완료"
    elif kind == "call_missed":
        text = "부재중 — 연결 안 됨" + (f" · {body}" if body else "")
    else:
        raise ServiceError("기록 종류가 올바르지 않습니다")
    if inq.status == "new" and kind in ("call", "call_missed"):
        # 첫 연락 시도 → 연락중으로 자동 전환 (응답속도 통계)
        inq.status = "contacting"
        inq.first_contact_at = inq.first_contact_at or now_kst()
        log(inq, user, "status", "신규 → 연락중", {"from": "new", "to": "contacting", "auto": True})
    log(inq, user, kind, text)
    db.session.commit()


# ---- 수동 등록 ----
def create_manual(user: User, site: Site, data: dict) -> Inquiry:
    from .intake import validate
    if user.site_ids() is not None and site.id not in user.site_ids():
        raise ServiceError("담당하지 않는 사이트입니다")
    data = dict(data, privacy_agreed="1")
    fields = validate(data)
    now = now_kst()
    prev = (Inquiry.query.filter(Inquiry.phone == fields["phone"], Inquiry.received_at >= now - timedelta(days=30))
            .order_by(Inquiry.received_at.desc()).first())
    inq = Inquiry(site=site, status="new", received_at=now, privacy_agreed=True, device="pc",
                  duplicate_of_id=prev.id if prev else None, assignee_id=user.id if user.role == "agent" else None, **fields)
    db.session.add(inq)
    db.session.flush()
    log(inq, user, "received", f"{user.display}이(가) 수동 등록 (전화 접수)")
    db.session.commit()
    return inq


# ---- 조회 범위·필터 ----
def scoped_query(user: User):
    q = Inquiry.query
    ids = user.site_ids()
    if ids is not None:
        q = q.filter(Inquiry.site_id.in_(ids or [-1]))
    if user.role == "agent":
        q = q.filter(or_(Inquiry.assignee_id.is_(None), Inquiry.assignee_id == user.id))
    return q


def apply_filters(q, user: User, args) -> tuple:
    """쿼리스트링 필터 적용. (query_without_status, query) 반환 — 탭 건수는 status 제외 쿼리로 센다."""
    today = now_kst().date()
    if args.get("site"):
        q = q.join(Site).filter(Site.code == args["site"])
    if args.get("cat"):
        q = q.filter(Inquiry.site.has(Site.category == args["cat"]))
    if args.get("q"):
        term = args["q"].strip()
        digits = "".join(ch for ch in term if ch.isdigit())
        conds = [Inquiry.customer_name.contains(term), Inquiry.message.contains(term), Inquiry.inquiry_type.contains(term)]
        if len(digits) >= 4:
            conds.append(Inquiry.phone.contains(digits))
        q = q.filter(or_(*conds))
    a = args.get("assignee")
    if a == "me":
        q = q.filter(Inquiry.assignee_id == user.id)
    elif a == "none":
        q = q.filter(Inquiry.assignee_id.is_(None))
    elif a and a.isdigit():
        q = q.filter(Inquiry.assignee_id == int(a))
    p = args.get("period")
    if p == "today":
        q = q.filter(Inquiry.received_at >= datetime.combine(today, datetime.min.time()))
    elif p in ("7", "30"):
        q = q.filter(Inquiry.received_at >= datetime.combine(today - timedelta(days=int(p)), datetime.min.time()))
    elif p == "custom" and args.get("from"):
        try:
            q = q.filter(Inquiry.received_at >= datetime.fromisoformat(args["from"]))
            if args.get("to"):
                q = q.filter(Inquiry.received_at < datetime.fromisoformat(args["to"]) + timedelta(days=1))
        except ValueError:
            pass  # 잘못된 날짜는 기간 필터 무시
    if args.get("cb") == "any":
        q = q.filter(Inquiry.callback_at.isnot(None))
    sheet = args.get("sheet")
    if sheet in ("done", "none"):
        from ..models import ConsultSheet
        sub = db.session.query(ConsultSheet.inquiry_id).filter(ConsultSheet.is_current.is_(True))
        q = q.filter(Inquiry.id.in_(sub) if sheet == "done" else Inquiry.id.notin_(sub))
    base = q
    if args.get("status") in STATUSES:
        q = q.filter(Inquiry.status == args["status"])
    return base, q


def badge_counts(user: User) -> dict:
    today = now_kst().date()
    q = scoped_query(user)
    return {
        "new": q.filter(Inquiry.status == "new").count(),
        "mine": q.filter(Inquiry.assignee_id == user.id, Inquiry.status.notin_(["closed", "contracted"])).count(),
    }


def record_view(user: User, inq: Inquiry, ip: str | None) -> None:
    """상세 열람 기록. 같은 사용자·같은 건은 10분 내 중복 기록 안 함."""
    since = now_kst() - timedelta(minutes=10)
    exists = AccessLog.query.filter(AccessLog.user_id == user.id, AccessLog.inquiry_id == inq.id,
                                    AccessLog.action == "view_detail", AccessLog.created_at >= since).first()
    if not exists:
        db.session.add(AccessLog(user_id=user.id, action="view_detail", inquiry_id=inq.id, ip=ip, created_at=now_kst()))
        db.session.commit()


def related_duplicates(user: User, inq: Inquiry) -> list[Inquiry]:
    """같은 연락처의 다른 문의 (앞뒤 모두). 사용자가 볼 수 있는 범위만."""
    if inq.is_masked:
        return []
    return (scoped_query(user).filter(Inquiry.phone == inq.phone, Inquiry.id != inq.id)
            .order_by(Inquiry.received_at.desc()).all())

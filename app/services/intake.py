"""문의 접수 처리 (CLAUDE.md 5-2).

인증·검증 → 정규화 → 기기 판정 → 중복 판정 → 저장 → 접수 로그 → 자동문자 큐 → 커밋.
"""
import re
from dataclasses import dataclass
from datetime import timedelta

from ..extensions import db
from ..models import Inquiry, InquiryLog, Site, SmsMessage, SmsTemplate

PHONE_RE = re.compile(r"^01[016789]\d{7,8}$")
KNOWN_FIELDS = {"name", "phone", "privacy_agreed", "inquiry_type", "region", "message", "utm_source", "utm_medium",
                "utm_campaign", "utm_term", "referrer", "landing_url", "website", "site_key", "csrf_token", "client_ua"}
DUP_WINDOW_DAYS = 30
AUTO_SMS_SKIP_MINUTES = 10


class IntakeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class IntakeResult:
    inquiry: Inquiry
    auto_sms_queued: bool


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes", "y")


def normalize_phone(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def detect_device(ua: str) -> str:
    ua = (ua or "").lower()
    if "ipad" in ua or "tablet" in ua or ("android" in ua and "mobile" not in ua):
        return "tablet"
    if "mobi" in ua or "iphone" in ua or "android" in ua:
        return "mobile"
    return "pc"


def validate(data: dict) -> dict:
    """필수·형식 검사. 통과하면 정규화된 dict 반환."""
    name = (data.get("name") or "").strip()
    if not 1 <= len(name) <= 50:
        raise IntakeError("name_invalid")
    phone = normalize_phone(data.get("phone") or "")
    if not PHONE_RE.match(phone):
        raise IntakeError("phone_invalid")
    if not _truthy(data.get("privacy_agreed")):
        raise IntakeError("privacy_required")
    message = (data.get("message") or "").strip() or None
    if message and len(message) > 3000:
        raise IntakeError("message_too_long")
    extra = {k: v for k, v in data.items() if k not in KNOWN_FIELDS and k not in Inquiry.__table__.columns}
    return {
        "customer_name": name, "phone": phone, "message": message,
        "inquiry_type": (data.get("inquiry_type") or "").strip()[:100] or None,
        "region": (data.get("region") or "").strip()[:100] or None,
        "utm_source": (data.get("utm_source") or "")[:100] or None,
        "utm_medium": (data.get("utm_medium") or "")[:100] or None,
        "utm_campaign": (data.get("utm_campaign") or "")[:150] or None,
        "utm_term": (data.get("utm_term") or "")[:200] or None,
        "referrer": (data.get("referrer") or "")[:500] or None,
        "landing_url": (data.get("landing_url") or "")[:500] or None,
        "extra_json": extra or None,
    }


def auto_reply_template(site: Site) -> SmsTemplate | None:
    if site.auto_reply_template_id:
        t = db.session.get(SmsTemplate, site.auto_reply_template_id)
        if t and t.is_active:
            return t
    return (SmsTemplate.query.filter_by(is_auto_reply=True, is_active=True)
            .filter((SmsTemplate.site_id == site.id) | (SmsTemplate.site_id.is_(None)))
            .order_by(SmsTemplate.site_id.desc().nullslast(), SmsTemplate.sort_order).first())


def intake(site: Site, data: dict, *, ip: str | None = None, user_agent: str | None = None,
           company_phone: str = "", default_sender: str = "") -> IntakeResult:
    from .. import now_kst
    fields = validate(data)
    now = now_kst()

    # 같은 연락처(추가 연락처 포함)가 이미 있으면 새 건을 만들지 않고 그 문의로 편입
    from .merge import find_existing, reinquire
    prev = find_existing(fields["phone"])
    last_at = (prev.last_received_at or prev.received_at) if prev else None
    recent_same_site = prev is not None and prev.site_id == site.id and last_at >= now - timedelta(minutes=AUTO_SMS_SKIP_MINUTES)

    if prev:
        inq = prev
        reinquire(inq, source=f"{site.name} 상담폼으로", message=fields["message"], inquiry_type=fields["inquiry_type"])
    else:
        inq = Inquiry(site=site, status="new", received_at=now, privacy_agreed=True, channel="web",
                      device=detect_device(user_agent), ip=ip, user_agent=(user_agent or "")[:500] or None, **fields)
        db.session.add(inq)
        db.session.flush()
        db.session.add(InquiryLog(inquiry_id=inq.id, kind="received", body=f"{site.name} 상담폼으로 접수", created_at=now))

    queued = False
    tpl = auto_reply_template(site) if site.auto_reply and not recent_same_site else None
    if tpl:
        from .template import msg_type, render, sms_bytes
        body = render(tpl.body, name=inq.customer_name, site_name=site.name, company_phone=company_phone)
        n = sms_bytes(body)
        db.session.add(SmsMessage(inquiry_id=inq.id, site_id=site.id, to_phone=inq.phone,
                                  from_phone=site.sender_number or default_sender, body=body,
                                  msg_type=msg_type(body), byte_len=n, status="queued", is_auto=True,
                                  created_at=now))
        db.session.add(InquiryLog(inquiry_id=inq.id, kind="sms", body=body, meta_json={"auto": True}, created_at=now))
        queued = True

    db.session.commit()
    return IntakeResult(inq, queued)

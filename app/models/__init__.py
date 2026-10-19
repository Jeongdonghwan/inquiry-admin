from .access_log import AccessLog
from .inquiry import Inquiry
from .log import InquiryLog
from .sheet import ConsultForm, ConsultSheet
from .site import Site
from .sms import SmsMessage
from .template import SmsTemplate
from .user import User, user_sites

# ---- 코드 상수 (3. 핵심 용어와 상태값) ----
STATUS_LABELS = {
    "new": "신규",
    "contacting": "연락중",
    "consulted": "상담완료",
    "contracted": "계약",
    "hold": "보류",
    "closed": "종결",
}
STATUSES = list(STATUS_LABELS)
CLOSE_REASONS = ["부재 지속", "비용 불일치", "타사 선택", "상담 불가 사건", "허위·스팸", "기타"]
CATEGORIES = {"legal": "법률", "labor": "인사·노무"}
ROLES = ("admin", "manager", "agent")
LOG_KINDS = ("received", "call", "call_missed", "memo", "sms", "status", "assign", "callback", "sheet", "system")

__all__ = [
    "AccessLog", "Inquiry", "InquiryLog", "ConsultForm", "ConsultSheet", "Site", "SmsMessage",
    "SmsTemplate", "User", "user_sites", "STATUS_LABELS", "STATUSES", "CLOSE_REASONS",
    "CATEGORIES", "ROLES", "LOG_KINDS",
]

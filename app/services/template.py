"""문자 템플릿 변수 치환·바이트 계산 (CLAUDE.md 6-3)."""
import re

from ..models import Inquiry

VARS = ("이름", "사이트", "담당자", "대표번호", "콜백일시")
LMS_MAX = 2000
SMS_MAX = 90


def sms_bytes(body: str) -> int:
    return len(body.encode("cp949", errors="replace"))


def msg_type(body: str) -> str:
    return "LMS" if sms_bytes(body) > SMS_MAX else "SMS"


def render(body: str, inq: Inquiry | None = None, *, company_phone: str = "", site_name: str | None = None,
           name: str | None = None) -> str:
    from .inquiry import fmt_callback
    mapping = {
        "이름": name or (inq.customer_name if inq else ""),
        "사이트": site_name or (inq.site.name if inq else ""),
        "담당자": inq.assignee.display if inq and inq.assignee else "",
        "대표번호": company_phone,
        "콜백일시": fmt_callback(inq.callback_at) if inq and inq.callback_at else "",
    }
    for k, v in mapping.items():
        body = body.replace("{" + k + "}", v)
    return body


def unresolved(body: str) -> list[str]:
    """치환되지 않고 남은 {변수} 목록."""
    return re.findall(r"\{([^{}]+)\}", body)

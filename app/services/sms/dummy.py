import logging
import uuid

from .base import SmsProvider

log = logging.getLogger("sms.dummy")


class DummyProvider(SmsProvider):
    """개발·테스트용. 외부 호출 없이 로그만 남기고 성공 처리."""
    name = "dummy"

    def __init__(self):
        self.sent: list[dict] = []  # 테스트에서 확인용

    def send(self, to, from_, body, msg_type, title=None):
        self.sent.append({"to": to, "from": from_, "body": body, "type": msg_type})
        log.info("[dummy sms] %s -> %s (%s) %s", from_, to, msg_type, body[:40])
        return True, f"dummy-{uuid.uuid4().hex[:10]}", None

"""알리고 문자 API 어댑터.

파라미터·테스트모드는 구현 시점 공식 문서(https://smartsms.aligo.in/admin/api/spec.html) 기준:
POST https://apis.aligo.in/send/  key, user_id, sender, receiver, msg, msg_type(SMS|LMS), title(LMS), testmode_yn(Y|N)
응답 JSON: result_code("1"=성공), message, msg_id
"""
import requests

from .base import SmsProvider

ENDPOINT = "https://apis.aligo.in/send/"


class AligoProvider(SmsProvider):
    name = "aligo"

    def __init__(self, api_key: str, user_id: str, testmode: bool = True):
        if not api_key or not user_id:
            raise ValueError("ALIGO_API_KEY / ALIGO_USER_ID 가 비어 있습니다")
        self.api_key, self.user_id, self.testmode = api_key, user_id, testmode

    def send(self, to, from_, body, msg_type, title=None):
        data = {"key": self.api_key, "user_id": self.user_id, "sender": from_, "receiver": to, "msg": body,
                "msg_type": msg_type, "testmode_yn": "Y" if self.testmode else "N"}
        if msg_type == "LMS":
            data["title"] = (title or body[:20]).strip()
        try:
            r = requests.post(ENDPOINT, data=data, timeout=5)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            return False, None, f"요청 실패: {e}"[:500]
        if str(j.get("result_code")) == "1":
            return True, str(j.get("msg_id") or ""), None
        return False, None, f"{j.get('result_code')}: {j.get('message')}"[:500]

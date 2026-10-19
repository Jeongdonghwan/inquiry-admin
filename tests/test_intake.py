import json

from app.extensions import db
from app.models import Inquiry, InquiryLog, Site, SmsMessage


def _site(code="hs"):
    return Site.query.filter_by(code=code).one()


def _secret_for(site):
    s = site.issue_secret()
    db.session.commit()
    return s


def test_server_key_201(client, app):
    site = _site()
    secret = _secret_for(site)
    r = client.post("/api/v1/inquiries", json={"name": "홍길동", "phone": "010-1234-5678", "privacy_agreed": True,
                                               "inquiry_type": "개인회생", "message": "상담 원합니다", "utm_term": "수원 개인회생"},
                    headers={"X-Site-Key": secret, "User-Agent": "Mozilla/5.0 (iPhone)"})
    assert r.status_code == 201 and r.json["ok"]
    inq = db.session.get(Inquiry, r.json["id"])
    assert inq.phone == "01012345678" and inq.site_id == site.id and inq.device == "mobile" and inq.status == "new"
    assert InquiryLog.query.filter_by(inquiry_id=inq.id, kind="received").count() == 1
    sms = SmsMessage.query.filter_by(inquiry_id=inq.id, is_auto=True).one()
    assert sms.status == "queued" and "홍길동" in sms.body and site.name in sms.body


def test_wrong_key_401(client):
    r = client.post("/api/v1/inquiries", json={"name": "a", "phone": "01011112222", "privacy_agreed": 1}, headers={"X-Site-Key": "nope"})
    assert r.status_code == 401 and not r.json["ok"]


def test_browser_origin_check(client):
    site = _site("ih")
    site.allowed_origins = "https://ok.example.com"
    db.session.commit()
    body = {"name": "브라우저", "phone": "01099998888", "privacy_agreed": "true", "site_key": site.public_key}
    bad = client.post("/api/v1/inquiries", data=body, headers={"Origin": "https://evil.example.com"})
    assert bad.status_code == 401
    good = client.post("/api/v1/inquiries", data=body, headers={"Origin": "https://ok.example.com"})
    assert good.status_code == 201
    assert good.headers["Access-Control-Allow-Origin"] == "https://ok.example.com"
    pre = client.open("/api/v1/inquiries", method="OPTIONS", headers={"Origin": "https://ok.example.com"})
    assert pre.status_code == 204 and pre.headers["Access-Control-Allow-Origin"] == "https://ok.example.com"


def test_validation_errors(client):
    secret = _secret_for(_site())
    h = {"X-Site-Key": secret}
    assert client.post("/api/v1/inquiries", json={"name": "a", "phone": "123", "privacy_agreed": 1}, headers=h).json["error"] == "phone_invalid"
    assert client.post("/api/v1/inquiries", json={"name": "a", "phone": "01011112222"}, headers=h).json["error"] == "privacy_required"
    assert client.post("/api/v1/inquiries", json={"name": "", "phone": "01011112222", "privacy_agreed": 1}, headers=h).json["error"] == "name_invalid"


def test_duplicate_marks_previous(client):
    secret = _secret_for(_site())
    h = {"X-Site-Key": secret}
    body = {"name": "중복", "phone": "01055556666", "privacy_agreed": 1}
    first = client.post("/api/v1/inquiries", json=body, headers=h).json["id"]
    second = client.post("/api/v1/inquiries", json=body, headers=h).json["id"]
    assert db.session.get(Inquiry, first).duplicate_of_id is None
    assert db.session.get(Inquiry, second).duplicate_of_id == first
    # 같은 사이트 10분 내 재접수 → 두 번째는 자동문자 생략
    assert SmsMessage.query.filter_by(inquiry_id=first).count() == 1
    assert SmsMessage.query.filter_by(inquiry_id=second).count() == 0


def test_honeypot_not_saved(client):
    secret = _secret_for(_site())
    before = Inquiry.query.count()
    r = client.post("/api/v1/inquiries", json={"name": "봇", "phone": "01077778888", "privacy_agreed": 1, "website": "http://spam"},
                    headers={"X-Site-Key": secret})
    assert r.status_code == 200 and r.json["ok"] and r.json["id"] is None
    assert Inquiry.query.count() == before


def test_client_ua_used_for_device(client):
    secret = _secret_for(_site())
    r = client.post("/api/v1/inquiries", json={"name": "a", "phone": "01011114444", "privacy_agreed": 1, "client_ua": "Mozilla/5.0 (iPhone) Mobile"},
                    headers={"X-Site-Key": secret, "User-Agent": "python-requests/2.34"})
    inq = db.session.get(Inquiry, r.json["id"])
    assert inq.device == "mobile" and inq.extra_json is None


def test_extra_fields_kept(client):
    secret = _secret_for(_site())
    r = client.post("/api/v1/inquiries", json={"name": "a", "phone": "01011113333", "privacy_agreed": 1, "age": 42, "when": "저녁"},
                    headers={"X-Site-Key": secret})
    assert db.session.get(Inquiry, r.json["id"]).extra_json == {"age": 42, "when": "저녁"}


def test_settings_sites_admin_only(client, login):
    login("yoon")
    assert client.get("/settings/sites").status_code == 403
    client.post("/logout")
    login("admin")
    assert client.get("/settings/sites").status_code == 200
    r = client.post("/settings/sites/new", data={"code": "rm", "name": "법률사무소 알엠", "category": "legal", "color": "#1c1c1c",
                                                 "allowed_origins": "https://rm.example.com/", "auto_reply": "on", "is_active": "on",
                                                 "retention_days": "365"}, follow_redirects=True)
    assert "비밀키".encode() in r.data
    site = Site.query.filter_by(code="rm").one()
    assert site.origins() == ["https://rm.example.com"]
    r = client.post(f"/settings/sites/{site.id}/test", follow_redirects=True)
    assert "테스트 문의 접수됨".encode() in r.data

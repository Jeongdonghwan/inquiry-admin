"""Phase 3~7 서비스·화면 테스트."""
from datetime import timedelta

import pytest

from app import now_kst
from app.extensions import db
from app.models import ConsultForm, ConsultSheet, Inquiry, InquiryLog, Site, SmsMessage, User
from app.services import inquiry as svc
from app.services import privacy, sheet as sheet_svc
from app.services.sms import queue as q
from app.services.template import msg_type, render, unresolved


def u(login_id):
    return User.query.filter_by(login_id=login_id).one()


def last(i):
    """가장 최근 기록 (seed 시각은 '오늘 HH:MM'이라 테스트 실행 시각보다 뒤일 수 있어 id 기준)."""
    return max(i.logs, key=lambda l: l.id)


def inq(name):
    return Inquiry.query.filter_by(customer_name=name).order_by(Inquiry.id).first()


# ---------- Phase 3 ----------
def test_status_change_logs_and_timestamps(app):
    i, yoon = inq("조민재"), u("yoon")
    svc.change_status(i, yoon, "contacting")
    assert i.status == "contacting" and i.first_contact_at is not None
    assert last(i).kind == "status" and last(i).body == "신규 → 연락중"
    svc.change_status(i, yoon, "contracted")
    assert i.contracted_at is not None
    with pytest.raises(svc.ServiceError):
        svc.change_status(i, yoon, "closed")  # 사유 없음
    svc.change_status(i, yoon, "closed", "비용 불일치")
    assert i.closed_at and "사유: 비용 불일치" in last(i).body


def test_assign_rules(app):
    i, yoon, oh, kang = inq("이수진"), u("yoon"), u("oh"), u("kang")  # 이수진 = nm (oh 담당 사이트)
    svc.assign(i, oh, oh.id)
    assert i.assignee_id == oh.id and "미배정 → 오세진 노무팀" in last(i).body
    with pytest.raises(svc.ServiceError):
        svc.assign(i, oh, kang.id)  # agent는 남에게 배정 불가
    svc.assign(i, yoon, None)
    assert i.assignee_id is None


def test_callback_and_records(app):
    i, kang = inq("조민재"), u("kang")
    at = now_kst().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)
    svc.set_callback(i, kang, at)
    assert i.callback_at == at and last(i).body.startswith("콜백 예약 ")
    svc.add_record(i, kang, "call_missed", "")
    assert i.status == "contacting"  # 신규 → 첫 연락 시도 시 자동 전환
    kinds = [l.kind for l in sorted(i.logs, key=lambda l: l.id)]
    assert kinds[-2:] == ["status", "call_missed"]
    with pytest.raises(svc.ServiceError):
        svc.add_record(i, kang, "memo", "   ")


def test_manual_create_marks_duplicate(app):
    yoon = u("yoon")
    hs = Site.query.filter_by(code="hs").one()
    new = svc.create_manual(yoon, hs, {"name": "박정훈", "phone": "010-4821-3307", "inquiry_type": "개인회생", "message": "전화 문의"})
    assert new.duplicate_of_id == inq("박정훈").id or new.duplicate_of_id is not None
    assert new.logs[0].kind == "received" and "수동 등록" in new.logs[0].body


def test_agent_scope_and_404(client, login):
    login("oh")
    r = client.get("/inquiries")
    assert "노무 상담센터".encode() in r.data and "회생파산 상담센터".encode() not in r.data
    hs_id = inq("박정훈").id
    assert client.get(f"/inquiries/{hs_id}/panel").status_code == 404
    assert client.post(f"/inquiries/{hs_id}/status", json={"status": "hold"}).status_code == 404
    # 남에게 배정된 담당 사이트 건도 404
    other = inq("서동현")  # in 사이트, oh 배정 → 접근 가능
    assert client.get(f"/inquiries/{other.id}/panel").status_code == 200
    svc.assign(other, u("yoon"), u("yoon").id)
    assert client.get(f"/inquiries/{other.id}/panel").status_code == 404


def test_action_returns_fragments_and_badge(client, login):
    login("yoon")
    i = inq("정다은")
    r = client.post(f"/inquiries/{i.id}/status", json={"status": "consulted"})
    j = r.get_json()
    assert j["ok"] and "상담완료" in j["panel_html"] and 'data-status="consulted"' in j["row_html"]
    b = client.get("/api/badge").get_json()
    assert set(b) == {"new", "mine"}


def test_view_detail_access_log_dedup(client, login):
    from app.models import AccessLog
    login("admin")
    i = inq("박정훈")
    client.get(f"/inquiries/{i.id}/panel")
    client.get(f"/inquiries/{i.id}/panel")
    assert AccessLog.query.filter_by(inquiry_id=i.id, action="view_detail").count() == 1


# ---------- Phase 4 ----------
def test_form_matching_and_show_if(app):
    rehab = inq("박정훈")
    f = sheet_svc.match_form(rehab)
    assert f and f.name == "개인회생·파산"
    assert sheet_svc.match_form(inq("정다은")).name.startswith("가사")
    fld = next(x for x in sheet_svc.fields_of(f.schema_json) if x["key"] == "lawsuit_detail")
    assert not sheet_svc.visible(fld, {"has_lawsuit": False}) and sheet_svc.visible(fld, {"has_lawsuit": True})


def test_schema_validation():
    good = {"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "text"}]}]}
    sheet_svc.validate_schema(good)
    with pytest.raises(sheet_svc.SchemaError, match="중복"):
        sheet_svc.validate_schema({"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "text"}, {"key": "x", "label": "Y", "type": "text"}]}]})
    with pytest.raises(sheet_svc.SchemaError, match="선택지"):
        sheet_svc.validate_schema({"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "select"}]}]})
    with pytest.raises(sheet_svc.SchemaError, match="show_if"):
        sheet_svc.validate_schema({"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "text", "show_if": {"key": "nope", "eq": 1}}]}]})


def test_save_answers_and_form_change_preserves(app):
    i, yoon = inq("정다은"), u("yoon")
    fam = ConsultForm.query.filter(ConsultForm.name.startswith("가사")).one()
    civil = ConsultForm.query.filter_by(name="민사").one()
    s = sheet_svc.save_answers(i, yoon, fam.id, {"kind": "협의이혼", "marriage_years": "7", "children": "1,000"})
    assert s.answers_json["marriage_years"] == 7 and s.answers_json["children"] == 1000 and s.required_done
    assert any(l.kind == "sheet" and "작성 시작" in l.body for l in i.logs)
    s2 = sheet_svc.save_answers(i, yoon, civil.id, {"case_kind": "대여금"})
    db.session.refresh(s)
    assert s.is_current is False and s2.is_current and not s2.required_done
    assert ConsultSheet.query.filter_by(inquiry_id=i.id).count() == 2
    txt = sheet_svc.summary_text(s2)
    assert "민사 상담지" in txt and "사건 종류: 대여금" in txt


def test_sheet_endpoints_permission(client, login):
    login("oh")
    i = inq("박정훈")  # hs → oh 접근 불가
    assert client.post(f"/inquiries/{i.id}/sheet", json={"form_id": 1, "answers": {}}).status_code == 404
    mine = inq("서동현")
    r = client.post(f"/inquiries/{mine.id}/sheet", json={"form_id": ConsultForm.query.filter_by(name="인사·노무").one().id,
                                                        "answers": {"side": "근로자", "issue": "임금체불", "unpaid_amount": "350"}})
    assert r.status_code == 200 and r.get_json()["ok"]


def test_form_builder_save_rejects_bad_schema(client, login):
    login("admin")
    r = client.post("/settings/forms/new", json={"name": "새 양식", "inquiry_type_keys": ["테스트"],
                                                "schema": {"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "select"}]}]}})
    assert r.status_code == 400 and "선택지" in r.get_json()["error"]
    r = client.post("/settings/forms/new", json={"name": "새 양식", "inquiry_type_keys": ["테스트"],
                                                "schema": {"sections": [{"title": "a", "fields": [{"key": "x", "label": "X", "type": "text"}]}]}})
    assert r.status_code == 200 and r.get_json()["version"] == 1


# ---------- Phase 5 ----------
def test_template_render_and_bytes(app):
    body = "[{사이트}] {이름}님, {콜백일시} {없는변수}"
    out = render(body, inq("정다은"), company_phone="031")
    assert out.startswith("[이혼·가사 상담] 정다은님,") and unresolved(out) == ["없는변수"]
    assert msg_type("가" * 45) == "SMS" and msg_type("가" * 46) == "LMS"


def test_sms_send_now_dummy(app):
    i, yoon = inq("정다은"), u("yoon")
    before = len(q._dummy.sent)
    m = q.enqueue(i, yoon, "안내 문자입니다.")
    assert m.status == "sent" and m.provider == "dummy" and len(q._dummy.sent) == before + 1
    assert last(i).kind == "sms" and last(i).body == "안내 문자입니다."
    with pytest.raises(q.SmsError):
        q.enqueue(i, yoon, "가" * 1001)  # 2,002 byte > LMS 최대


def test_sms_scheduled_worker_and_no_double_send(app):
    i, yoon = inq("정다은"), u("yoon")
    m = q.enqueue(i, yoon, "예약 문자", now_kst() + timedelta(minutes=5))
    assert m.status == "scheduled"
    assert q.run_worker()["sent"] == 0  # 아직 시간 전
    m.scheduled_at = now_kst() - timedelta(minutes=1)
    db.session.commit()
    before = len(q._dummy.sent)
    r1 = q.run_worker(); r2 = q.run_worker()
    assert r1["sent"] == 1 and r2["sent"] == 0 and len(q._dummy.sent) == before + 1
    assert db.session.get(SmsMessage, m.id).status == "sent"


def test_sms_failure_retries_then_failed(app, monkeypatch):
    i, yoon = inq("정다은"), u("yoon")
    monkeypatch.setattr(q._dummy, "send", lambda *a, **k: (False, None, "발송사 오류"))
    m = q.enqueue(i, yoon, "실패 테스트")
    assert m.status == "queued" and m.attempts == 1 and "문자 발송 실패" in last(i).body
    q.run_worker(); q.run_worker()
    assert db.session.get(SmsMessage, m.id).status == "failed"


def test_sms_endpoint_and_list(client, login):
    login("yoon")
    i = inq("정다은")
    r = client.post(f"/inquiries/{i.id}/sms", json={"body": "테스트 발송"})
    assert r.status_code == 200 and "테스트 발송" in r.get_json()["panel_html"]
    assert "테스트 발송".encode() in client.get("/sms/?status=sent").data


# ---------- Phase 6 ----------
def test_privacy_sweep_masks_expired(app):
    i = inq("유지호")  # closed
    i.closed_at = now_kst() - timedelta(days=400)
    db.session.commit()
    assert privacy.sweep() == 1
    db.session.refresh(i)
    assert i.is_masked and i.customer_name == "유*호" and i.phone == "010-****-1406" and i.message == privacy.DELETED
    assert all(l.body == privacy.DELETED for l in i.logs if l.kind in ("memo", "call", "call_missed"))
    assert privacy.sweep() == 0


def test_export_requires_admin_and_logs(client, login):
    from app.models import AccessLog
    login("yoon")
    assert client.get("/inquiries/export.xlsx").status_code == 403
    client.post("/logout"); login("admin")
    r = client.get("/inquiries/export.xlsx?site=hs")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    assert AccessLog.query.filter_by(action="export_excel").count() == 1



def test_users_admin_crud(client, login):
    login("admin")
    r = client.post("/settings/users/new", data={"login_id": "newbie", "name": "신입", "role": "agent", "is_active": "on",
                                                 "sites": [str(Site.query.filter_by(code="hs").one().id)]}, follow_redirects=True)
    assert "임시 비밀번호".encode() in r.data
    nu = User.query.filter_by(login_id="newbie").one()
    assert nu.role == "agent" and [s.code for s in nu.sites] == ["hs"]
    client.post("/logout")
    login("yoon")
    assert client.get("/settings/users").status_code == 403


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"


# ---------- Phase 7 ----------
def test_board_same_data_and_drawer(client, login):
    login("admin")
    r = client.get("/board")
    assert r.status_code == 200
    for name in ("박정훈", "정다은", "황보름"):
        assert name.encode() in r.data
    i = inq("정다은")
    r = client.get(f"/inquiries/{i.id}/panel?layout=drawer")
    assert "timeline".encode() in r.data and "정다은".encode() in r.data
    j = client.post(f"/inquiries/{i.id}/status?layout=drawer", json={"status": "hold"}).get_json()
    assert j["ok"] and 'data-status="hold"' in j["card_html"]


def test_user_delete_unassigns_and_blocks_self(client, login):
    login("admin")
    kang = User.query.filter_by(login_id="kang").one()
    n = Inquiry.query.filter_by(assignee_id=kang.id).count()
    assert n > 0
    r = client.post(f"/settings/users/{kang.id}/delete", follow_redirects=True)
    assert "삭제됨".encode() in r.data and User.query.filter_by(login_id="kang").first() is None
    assert Inquiry.query.filter_by(assignee_id=kang.id).count() == 0
    assert InquiryLog.query.filter_by(user_id=kang.id).count() == 0
    me = User.query.filter_by(login_id="admin").one()
    r = client.post(f"/settings/users/{me.id}/delete", follow_redirects=True)
    assert "본인 계정".encode() in r.data and User.query.filter_by(login_id="admin").first()

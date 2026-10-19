from app.extensions import db
from app.models import Inquiry, Site, User
from app.permissions import can_access


def test_seed_accounts_can_login(client, login):
    for uid in ("admin", "yoon", "kang", "oh"):
        r = login(uid)
        assert r.status_code == 200 and "통합 문의함".encode() in r.data
        client.post("/logout")


def test_wrong_password_rejected(login):
    r = login("admin", "nope")
    assert "올바르지 않습니다".encode() in r.data


def test_login_locks_after_5_failures(app, login):
    for _ in range(5):
        login("yoon", "nope")
    r = login("yoon")  # 올바른 비밀번호여도 잠김
    assert "잠겼습니다".encode() in r.data


def test_agent_does_not_see_staff_menu(client, login):
    assert "직원 · 권한".encode() in login("admin").data
    client.post("/logout")
    r = login("oh")
    assert "직원 · 권한".encode() not in r.data


def test_agent_sidebar_only_own_sites(login):
    r = login("oh")
    assert "바삭한형제 가맹".encode() in r.data
    assert "회생파산 상담센터".encode() not in r.data


def test_role_required_blocks_unauthenticated(client):
    r = client.get("/inquiries")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_can_access_rules(app):
    admin = User.query.filter_by(login_id="admin").one()
    yoon = User.query.filter_by(login_id="yoon").one()
    oh = User.query.filter_by(login_id="oh").one()
    hs = Site.query.filter_by(code="hs").one()
    cb = Site.query.filter_by(code="cb").one()
    hs_inq = Inquiry.query.filter_by(site_id=hs.id).first()
    cb_unassigned = Inquiry.query.filter_by(site_id=cb.id, assignee_id=None).first()
    cb_other = Inquiry(site_id=cb.id, assignee_id=yoon.id, customer_name="x", phone="01000000000",
                       received_at=hs_inq.received_at)
    db.session.add(cb_other)
    db.session.flush()

    assert can_access(admin, hs_inq)
    assert can_access(yoon, hs_inq)            # manager: 담당 사이트 전부
    assert not can_access(oh, hs_inq)          # agent: 담당 사이트 아님
    assert can_access(oh, cb_unassigned)       # agent: 미배정 건
    assert not can_access(oh, cb_other)        # agent: 남에게 배정된 건

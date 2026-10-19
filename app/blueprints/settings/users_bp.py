"""설정 > 직원·권한, 개인정보 조회 이력 (admin)."""
import re
import secrets

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import ROLES, AccessLog, Inquiry, Site, User
from ...permissions import role_required
from . import bp

ROLE_LABELS = {"admin": "관리자", "manager": "매니저", "agent": "상담원"}


@bp.get("/users")
@role_required("admin")
def users():
    rows = User.query.order_by(User.is_active_flag.desc(), User.role, User.name).all()
    return render_template("settings/users.html", rows=rows, roles=ROLE_LABELS, new_pw=request.args.get("pw"))


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<int:uid>", methods=["GET", "POST"])
@role_required("admin")
def user_form(uid=None):
    u = db.session.get(User, uid) if uid else User(role="agent", is_active_flag=True)
    if uid and u is None:
        abort(404)
    sites = Site.query.order_by(Site.id).all()
    if request.method == "POST":
        f = request.form
        login_id = (f.get("login_id") or "").strip().lower()
        errors = []
        if not re.fullmatch(r"[a-z0-9_.-]{3,50}", login_id):
            errors.append("아이디는 영문 소문자·숫자 3~50자")
        elif User.query.filter(User.login_id == login_id, User.id != u.id).first():
            errors.append("이미 사용 중인 아이디")
        u.login_id = login_id
        u.name = (f.get("name") or "").strip()[:50]
        u.title = (f.get("title") or "").strip()[:30] or None
        u.phone = re.sub(r"\D", "", f.get("phone") or "") or None
        u.role = f.get("role") if f.get("role") in ROLES else "agent"
        u.is_active_flag = f.get("is_active") == "on"
        u.sites = [s for s in sites if str(s.id) in f.getlist("sites")]
        if not u.name:
            errors.append("이름을 입력하세요")
        if u.id == current_user.id and (u.role != "admin" or not u.is_active_flag):
            errors.append("본인 계정의 관리자 권한·사용 여부는 바꿀 수 없습니다")
        pw = None
        if u.id is None:
            pw = f.get("password") or secrets.token_urlsafe(8)
            u.set_password(pw)
        if errors:
            for e in errors:
                flash(e)
        else:
            db.session.add(u)
            db.session.commit()
            flash(f"저장됨: {u.display}")
            return redirect(url_for("settings.users", pw=pw) if pw and not f.get("password") else url_for("settings.users"))
    return render_template("settings/user_form.html", u=u, sites=sites, roles=ROLE_LABELS)


@bp.post("/users/<int:uid>/reset-password")
@role_required("admin")
def user_reset_pw(uid):
    u = db.session.get(User, uid) or abort(404)
    pw = secrets.token_urlsafe(8)
    u.set_password(pw)
    u.failed_logins, u.locked_until = 0, None
    db.session.commit()
    flash(f"{u.display} 비밀번호 초기화됨")
    return redirect(url_for("settings.users", pw=pw))


@bp.post("/users/<int:uid>/toggle")
@role_required("admin")
def user_toggle(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.id == current_user.id:
        flash("본인 계정은 비활성화할 수 없습니다")
    else:
        u.is_active_flag = not u.is_active_flag
        db.session.commit()
    return redirect(url_for("settings.users"))


@bp.get("/access-logs")
@role_required("admin")
def access_logs():
    page = max(1, request.args.get("page", 1, type=int))
    q = AccessLog.query.order_by(AccessLog.created_at.desc())
    if request.args.get("action"):
        q = q.filter(AccessLog.action == request.args["action"])
    total = q.count()
    rows = q.offset((page - 1) * 100).limit(100).all()
    users = {u.id: u for u in User.query}
    return render_template("settings/access_logs.html", rows=rows, users=users, total=total, page=page, args=request.args,
                           labels={"view_detail": "상세 열람", "export_excel": "엑셀 다운로드", "reveal_phone": "번호 표시"})

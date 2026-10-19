from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ...extensions import db
from ...models import User

bp = Blueprint("auth", __name__, template_folder="../../templates")

LOCK_AFTER = 5
LOCK_MINUTES = 10


@bp.route("/login", methods=["GET", "POST"])
def login():
    from ... import now_kst
    if current_user.is_authenticated:
        return redirect(url_for("inquiries.list_view"))
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(login_id=login_id).first()
        now = now_kst()
        if user and user.locked_until and user.locked_until > now:
            flash(f"로그인 {LOCK_AFTER}회 실패로 잠겼습니다. {user.locked_until:%H:%M} 이후 다시 시도하세요.")
        elif user and user.is_active and user.check_password(password):
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = now
            db.session.commit()
            session.permanent = True
            login_user(user)
            return redirect(request.args.get("next") or url_for("inquiries.list_view"))
        else:
            if user:
                user.failed_logins += 1
                if user.failed_logins >= LOCK_AFTER:
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    user.failed_logins = 0
                db.session.commit()
            flash("아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

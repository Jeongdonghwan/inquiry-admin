from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, redirect, url_for

from .config import Config
from .extensions import csrf, db, limiter, login_manager, migrate

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"


def now_kst() -> datetime:
    """KST 기준 naive datetime (DB 저장용)."""
    return datetime.now(KST).replace(tzinfo=None)


def kcallback_str(dt: datetime) -> str:
    return f"{dt.month:02d}.{dt.day:02d} ({WEEKDAYS[dt.weekday()]}) {dt:%H:%M}"


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (모델 등록)
    from .blueprints.api import bp as api_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.board import bp as board_bp
    from .blueprints.export import bp as export_bp
    from .blueprints.inquiries import bp as inquiries_bp
    from .blueprints.settings import bp as settings_bp
    from .blueprints.sheet import bp as sheet_bp
    from .blueprints.sms import bp as sms_bp
    from .blueprints.stats import bp as stats_bp
    from .cli import register_cli

    for b in (auth_bp, inquiries_bp, sheet_bp, board_bp, export_bp, sms_bp, stats_bp, settings_bp, api_bp):
        app.register_blueprint(b)
    csrf.exempt(api_bp)  # 외부 사이트 접수 API는 키 인증
    register_cli(app)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config.get("ENV") == "production":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.route("/")
    def index():
        return redirect(url_for("inquiries.list_view"))

    # ---- Jinja 필터 (13. 코딩 규칙) ----
    @app.template_filter("kdate")
    def kdate(dt):
        return dt.strftime("%m.%d %H:%M") if dt else ""

    @app.template_filter("kcallback")
    def kcallback(dt):
        return kcallback_str(dt) if dt else "미지정"

    @app.template_filter("phone")
    def phone(num):
        if not num:
            return ""
        n = "".join(ch for ch in str(num) if ch.isdigit() or ch == "*")
        if len(n) == 11:
            return f"{n[:3]}-{n[3:7]}-{n[7:]}"
        if len(n) == 10:
            return f"{n[:3]}-{n[3:6]}-{n[6:]}"
        return num

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from sqlalchemy import func
        from .models import CATEGORIES, STATUS_LABELS, Inquiry, Site

        sites = []
        if current_user.is_authenticated:
            q = db.session.query(Site, func.count(Inquiry.id)).outerjoin(Inquiry).filter(Site.is_active)
            ids = current_user.site_ids()
            if ids is not None:
                q = q.filter(Site.id.in_(ids))
            sites = [{"code": s.code, "name": s.name, "color": s.color, "count": n}
                     for s, n in q.group_by(Site.id).order_by(Site.id)]
        return {"STATUS_LABELS": STATUS_LABELS, "CATEGORIES": CATEGORIES, "today": now_kst(), "sidebar_sites": sites}

    return app

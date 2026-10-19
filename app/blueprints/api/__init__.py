"""외부 사이트 → 어드민 접수 API (CLAUDE.md 5)."""
from flask import Blueprint, current_app, jsonify, request

from ...extensions import limiter
from ...models import Site
from ...services.intake import IntakeError, intake

bp = Blueprint("api", __name__, url_prefix="/api/v1")

CORS_HEADERS = {"Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Site-Key", "Vary": "Origin"}


def _payload() -> dict:
    if request.is_json:
        return dict(request.get_json(silent=True) or {})
    return request.form.to_dict()


def _authenticate(data: dict) -> tuple[Site | None, bool]:
    """(site, via_browser). 서버키 헤더 우선, 없으면 공개키 + Origin 검사."""
    secret = request.headers.get("X-Site-Key")
    if secret:
        for site in Site.query.filter_by(is_active=True):
            if site.check_secret(secret):
                return site, False
        return None, False
    pub = data.get("site_key")
    origin = request.headers.get("Origin", "")
    if pub:
        site = Site.query.filter_by(public_key=pub, is_active=True).first()
        if site and origin and origin.rstrip("/") in site.origins():
            return site, True
    return None, True


def _with_cors(resp, origin: str | None):
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        for k, v in CORS_HEADERS.items():
            resp.headers[k] = v
    return resp


@bp.route("/inquiries", methods=["OPTIONS"])
def inquiries_preflight():
    origin = request.headers.get("Origin", "").rstrip("/")
    allowed = origin and any(origin in s.origins() for s in Site.query.filter_by(is_active=True))
    return _with_cors(current_app.response_class(status=204), origin if allowed else None)


@bp.post("/inquiries")
@limiter.limit("5 per minute")
def create_inquiry():
    data = _payload()
    site, via_browser = _authenticate(data)
    origin = request.headers.get("Origin", "").rstrip("/") if via_browser else None
    if site is None:
        return _with_cors(jsonify(ok=False, error="unauthorized"), None), 401

    # 허니팟: 봇이 채운 값이 있으면 저장 없이 200 (티 안 냄)
    if (data.get("website") or "").strip():
        return _with_cors(jsonify(ok=True, id=None), origin), 200

    try:
        result = intake(site, data,
                        ip=request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
                        user_agent=(data.pop('client_ua', None) or request.user_agent.string),  # 서버→서버면 사이트가 전달한 브라우저 UA
                        company_phone=current_app.config["REPRESENTATIVE_PHONE"],
                        default_sender=current_app.config["SMS_DEFAULT_SENDER"])
    except IntakeError as e:
        return _with_cors(jsonify(ok=False, error=e.code), origin), 400
    return _with_cors(jsonify(ok=True, id=result.inquiry.id), origin), 201

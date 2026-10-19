from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from .models import Inquiry, User


def role_required(*roles):
    """로그인 + 역할 검사. 역할이 맞지 않으면 403."""
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if current_user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def can_access(user: User, inquiry: Inquiry) -> bool:
    """admin: 전체 / manager: 담당 사이트 전부 / agent: 담당 사이트 중 본인 배정 + 미배정."""
    if user.is_admin:
        return True
    if inquiry.site_id not in user.site_ids():
        return False
    if user.role == "manager":
        return True
    return inquiry.assignee_id in (None, user.id)


def get_inquiry_or_404(user: User, inquiry_id: int) -> Inquiry:
    from .extensions import db
    inq = db.session.get(Inquiry, inquiry_id)
    if inq is None or not can_access(user, inq):
        abort(404)  # 권한 없는 건은 존재 자체를 숨김
    return inq

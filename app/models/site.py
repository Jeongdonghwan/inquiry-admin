import secrets

from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class Site(db.Model):
    __tablename__ = "sites"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # legal | labor
    color = db.Column(db.String(7), nullable=False, default="#475569")
    domain = db.Column(db.String(255))
    allowed_origins = db.Column(db.Text)  # 줄바꿈 구분
    secret_key_hash = db.Column(db.String(255), nullable=False)
    public_key = db.Column(db.String(64), nullable=False, unique=True)
    sender_number = db.Column(db.String(20))
    auto_reply = db.Column(db.Boolean, nullable=False, default=True)
    auto_reply_template_id = db.Column(db.Integer)
    retention_days = db.Column(db.Integer, nullable=False, default=365)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    inquiries = db.relationship("Inquiry", back_populates="site")

    # ---- 키 관리: 비밀키는 발급 순간에만 평문 반환, DB에는 해시만 ----
    def issue_secret(self) -> str:
        secret = secrets.token_urlsafe(32)
        self.secret_key_hash = generate_password_hash(secret)
        return secret

    def check_secret(self, secret: str) -> bool:
        return bool(secret) and check_password_hash(self.secret_key_hash, secret)

    def issue_public(self) -> str:
        self.public_key = secrets.token_hex(16)
        return self.public_key

    def origins(self) -> list[str]:
        return [o.strip() for o in (self.allowed_origins or "").splitlines() if o.strip()]

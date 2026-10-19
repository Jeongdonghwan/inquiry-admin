from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager

user_sites = db.Table(
    "user_sites",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("site_id", db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(30))
    role = db.Column(db.String(20), nullable=False, default="agent")  # admin | manager | agent
    phone = db.Column(db.String(20))
    is_active_flag = db.Column("is_active", db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    sites = db.relationship("Site", secondary=user_sites, lazy="selectin")

    # Flask-Login의 is_active 프로퍼티와 컬럼명 충돌 방지
    @property
    def is_active(self):  # type: ignore[override]
        return self.is_active_flag

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def display(self) -> str:
        return f"{self.name} {self.title}" if self.title else self.name

    def site_ids(self) -> set[int] | None:
        """admin은 None(전체), 그 외는 담당 사이트 id 집합."""
        return None if self.is_admin else {s.id for s in self.sites}


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

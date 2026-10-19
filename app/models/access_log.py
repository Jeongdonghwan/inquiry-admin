from sqlalchemy import func

from ..extensions import db


class AccessLog(db.Model):
    """개인정보 조회·다운로드 이력."""
    __tablename__ = "access_logs"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(30), nullable=False)  # view_detail | export_excel | reveal_phone
    inquiry_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"))
    detail = db.Column(db.String(255))
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    __table_args__ = (db.Index("idx_user_created", "user_id", "created_at"),)

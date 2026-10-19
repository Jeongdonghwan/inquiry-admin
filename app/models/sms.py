from sqlalchemy import func

from ..extensions import db


class SmsMessage(db.Model):
    __tablename__ = "sms_messages"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    inquiry_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"),
                           db.ForeignKey("inquiries.id", ondelete="SET NULL"))
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # NULL = 자동발송
    to_phone = db.Column(db.String(20), nullable=False)
    from_phone = db.Column(db.String(20), nullable=False)
    body = db.Column(db.Text, nullable=False)
    msg_type = db.Column(db.String(5), nullable=False)  # SMS | LMS
    byte_len = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(12), nullable=False, default="queued")
    is_auto = db.Column(db.Boolean, nullable=False, default=False)
    scheduled_at = db.Column(db.DateTime)
    provider = db.Column(db.String(20))
    provider_msg_id = db.Column(db.String(100))
    error = db.Column(db.String(500))
    attempts = db.Column(db.Integer, nullable=False, default=0)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        db.Index("idx_status_sched", "status", "scheduled_at"),
        db.Index("idx_sms_inquiry", "inquiry_id"),
    )

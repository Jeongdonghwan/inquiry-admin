from sqlalchemy import func

from ..extensions import db


class InquiryLog(db.Model):
    __tablename__ = "inquiry_logs"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    inquiry_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"),
                           db.ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # NULL = 시스템/자동
    body = db.Column(db.Text)
    meta_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    inquiry = db.relationship("Inquiry", back_populates="logs")
    user = db.relationship("User")

    __table_args__ = (db.Index("idx_inquiry_created", "inquiry_id", "created_at"),)

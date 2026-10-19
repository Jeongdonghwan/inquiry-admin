from sqlalchemy import func

from ..extensions import db


class Inquiry(db.Model):
    __tablename__ = "inquiries"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="new")
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    customer_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)  # 숫자만
    region = db.Column(db.String(100))
    inquiry_type = db.Column(db.String(100))
    message = db.Column(db.Text)
    extra_json = db.Column(db.JSON)
    utm_source = db.Column(db.String(100))
    utm_medium = db.Column(db.String(100))
    utm_campaign = db.Column(db.String(150))
    utm_term = db.Column(db.String(200))
    referrer = db.Column(db.String(500))
    landing_url = db.Column(db.String(500))
    device = db.Column(db.String(10))  # mobile | pc | tablet
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    privacy_agreed = db.Column(db.Boolean, nullable=False, default=False)
    duplicate_of_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"))
    callback_at = db.Column(db.DateTime)
    close_reason = db.Column(db.String(100))
    received_at = db.Column(db.DateTime, nullable=False)
    first_contact_at = db.Column(db.DateTime)
    contracted_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    is_masked = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    site = db.relationship("Site", back_populates="inquiries")
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    logs = db.relationship("InquiryLog", back_populates="inquiry", cascade="all, delete-orphan",
                           order_by="InquiryLog.created_at")

    __table_args__ = (
        db.Index("idx_status_received", "status", "received_at"),
        db.Index("idx_site_received", "site_id", "received_at"),
        db.Index("idx_phone", "phone"),
        db.Index("idx_assignee", "assignee_id"),
        db.Index("idx_callback", "callback_at"),
    )

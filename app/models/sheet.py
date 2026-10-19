from sqlalchemy import func

from ..extensions import db


class ConsultForm(db.Model):
    """사건 유형별 상담지 양식 (7-7)."""
    __tablename__ = "consult_forms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(20))  # legal | labor | NULL(공통)
    inquiry_type_keys = db.Column(db.JSON, nullable=False)
    schema_json = db.Column(db.JSON, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ConsultSheet(db.Model):
    """문의 1건의 상담지 답변."""
    __tablename__ = "consult_sheets"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    inquiry_id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"),
                           db.ForeignKey("inquiries.id", ondelete="CASCADE"), nullable=False)
    form_id = db.Column(db.Integer, db.ForeignKey("consult_forms.id"), nullable=False)
    form_version = db.Column(db.Integer, nullable=False)
    answers_json = db.Column(db.JSON, nullable=False)
    is_current = db.Column(db.Boolean, nullable=False, default=True)
    required_done = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    form = db.relationship("ConsultForm")

    __table_args__ = (db.Index("idx_inquiry_current", "inquiry_id", "is_current"),)

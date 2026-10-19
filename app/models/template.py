from ..extensions import db


class SmsTemplate(db.Model):
    __tablename__ = "sms_templates"

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id"))  # NULL = 전체 공통
    category = db.Column(db.String(20))  # NULL = 전 업종
    name = db.Column(db.String(50), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_auto_reply = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

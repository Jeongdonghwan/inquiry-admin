"""접수 경로(channel), 추가 연락처(phone2), 최근 재문의 시각(last_received_at)

Revision ID: a1c2e3f4b5d6
Revises: 89176926e919
"""
import sqlalchemy as sa
from alembic import op

revision = "a1c2e3f4b5d6"
down_revision = "89176926e919"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("inquiries") as b:
        b.add_column(sa.Column("channel", sa.String(10), nullable=False, server_default="web"))
        b.add_column(sa.Column("phone2", sa.String(20), nullable=True))
        b.add_column(sa.Column("last_received_at", sa.DateTime(), nullable=True))
        b.create_index("idx_phone2", ["phone2"])


def downgrade():
    with op.batch_alter_table("inquiries") as b:
        b.drop_index("idx_phone2")
        b.drop_column("last_received_at")
        b.drop_column("phone2")
        b.drop_column("channel")

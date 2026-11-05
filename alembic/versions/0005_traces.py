"""질의 한 건의 판정 흐름 기록 (#83)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("house_manage_no", sa.Text, nullable=False),
        sa.Column("pblanc_no", sa.Text),  # 공고를 못 찾으면 null
        sa.Column("profile_hash", sa.Text, nullable=False),  # HMAC-SHA256 16진수 64자
        sa.Column("status", sa.Text, nullable=False),  # ok | error
        sa.Column("error", sa.Text),
        sa.Column("verdict", sa.Text),  # 전역 판정. 실패면 null
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("system_sha", sa.Text, nullable=False),
        sa.Column("seconds", sa.Float(53), nullable=False),
        sa.Column("steps", postgresql.JSONB, nullable=False),
        sa.Column("answer", postgresql.JSONB),  # B9 응답 전문. 실패면 null
    )
    op.create_index("traces_created_at_idx", "traces", ["created_at"])
    op.create_index("traces_notice_idx", "traces", ["house_manage_no", "pblanc_no"])
    op.create_index("traces_profile_hash_idx", "traces", ["profile_hash"])


def downgrade() -> None:
    op.drop_table("traces")  # 인덱스도 같이 지워진다

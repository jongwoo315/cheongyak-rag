"""하루 판정 한도 (#85): 한국 날짜별 판정 요청 수

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verdict_daily_count",
        sa.Column("day", sa.Date, primary_key=True),  # Asia/Seoul 기준 날짜
        sa.Column("count", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("verdict_daily_count")

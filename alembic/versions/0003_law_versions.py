"""「주택공급에 관한 규칙」 시행일별 버전(law_versions)과 공고별 유효 버전 view

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 고르는 규칙은 설계 §1이다: 시행일 ≤ 모집공고일 중 시행일이 가장 늦은 것,
# 같은 시행일이면 공포일이 늦은 것, 그래도 같으면 MST가 큰 것(text라 길이를 먼저 본다).
# 맞는 행이 없으면 버전 열이 NULL이다. 공포일이 NULL인 행은 가장 뒤로 보낸다
# (Postgres는 DESC에서 NULL을 맨 앞에 둔다)
VIEW_SQL = """
CREATE VIEW notice_law_versions AS
SELECT n.house_manage_no, n.pblanc_no, n.rcrit_pblanc_de,
       v.mst, v.effective_date, v.promulgation_date, v.promulgation_no
FROM notices n
LEFT JOIN LATERAL (
    SELECT lv.mst, lv.effective_date, lv.promulgation_date, lv.promulgation_no
    FROM law_versions lv
    WHERE lv.law_id = '008243' AND lv.effective_date <= n.rcrit_pblanc_de
    ORDER BY lv.effective_date DESC, lv.promulgation_date DESC NULLS LAST,
             length(lv.mst) DESC, lv.mst DESC
    LIMIT 1
) v ON true
"""


def upgrade() -> None:
    op.create_table(
        "law_versions",
        sa.Column("law_id", sa.Text, nullable=False),
        sa.Column("mst", sa.Text, nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("promulgation_date", sa.Date),
        sa.Column("promulgation_no", sa.Text),
        sa.Column("law_name", sa.Text),
        sa.Column("revision_kind", sa.Text),  # 제개정구분명
        sa.Column("status", sa.Text),  # 현행연혁코드
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("law_id", "mst", "effective_date"),
    )
    op.create_index(
        "ix_law_versions_law_id_effective_date", "law_versions", ["law_id", "effective_date"]
    )
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW notice_law_versions")
    op.drop_index("ix_law_versions_law_id_effective_date", table_name="law_versions")
    op.drop_table("law_versions")

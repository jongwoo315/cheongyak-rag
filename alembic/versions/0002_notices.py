"""청약홈 APT 공고(notices)와 주택형(notice_models) 테이블

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notices",
        sa.Column("house_manage_no", sa.Text, nullable=False),
        sa.Column("pblanc_no", sa.Text, nullable=False),
        sa.Column("house_nm", sa.Text, nullable=False),
        sa.Column("house_secd", sa.Text),
        sa.Column("house_dtl_secd", sa.Text),
        sa.Column("rent_secd", sa.Text),
        sa.Column("subscrpt_area_code", sa.Text),
        sa.Column("subscrpt_area_nm", sa.Text),
        sa.Column("hssply_adres", sa.Text),
        sa.Column("tot_suply_hshldco", sa.Integer),
        sa.Column("rcrit_pblanc_de", sa.Date),
        sa.Column("rcept_bgnde", sa.Date),
        sa.Column("rcept_endde", sa.Date),
        sa.Column("przwner_presnatn_de", sa.Date),
        sa.Column("mvn_prearnge_ym", sa.Text),
        sa.Column("speclt_rdn_earth_at", sa.Boolean),
        sa.Column("mdat_trget_area_secd", sa.Boolean),
        sa.Column("parcprc_uls_at", sa.Boolean),
        sa.Column("public_house_earth_at", sa.Boolean),
        sa.Column("pblanc_url", sa.Text),
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("house_manage_no", "pblanc_no"),
    )
    op.create_index("ix_notices_rcrit_pblanc_de", "notices", ["rcrit_pblanc_de"])
    op.create_index("ix_notices_subscrpt_area_nm", "notices", ["subscrpt_area_nm"])

    op.create_table(
        "notice_models",
        sa.Column("house_manage_no", sa.Text, nullable=False),
        sa.Column("pblanc_no", sa.Text, nullable=False),
        sa.Column("model_no", sa.Text, nullable=False),
        sa.Column("house_ty", sa.Text),
        sa.Column("suply_ar", sa.Numeric),
        sa.Column("suply_hshldco", sa.Integer),
        sa.Column("spsply_hshldco", sa.Integer),
        sa.Column("lttot_top_amount", sa.Integer),  # 만원
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("house_manage_no", "pblanc_no", "model_no"),
        sa.ForeignKeyConstraint(
            ["house_manage_no", "pblanc_no"],
            ["notices.house_manage_no", "notices.pblanc_no"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("notice_models")
    op.drop_index("ix_notices_subscrpt_area_nm", table_name="notices")
    op.drop_index("ix_notices_rcrit_pblanc_de", table_name="notices")
    op.drop_table("notices")

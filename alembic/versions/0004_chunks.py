"""조문·FAQ 청크와 임베딩·형태소 토큰 (#74)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = 1536  # text-embedding-3-small


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.Text, primary_key=True),  # `law:제2조` · `faq:47`
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("title", sa.Text),  # FAQ는 비어 있다
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.Text, nullable=False),
        sa.Column("law_mst", sa.Text),  # 조문 청크의 법령 버전. FAQ는 null
        sa.Column("embed_model", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("tokens", postgresql.TSVECTOR, nullable=False),
        sa.CheckConstraint("source IN ('law', 'faq')", name="chunks_source_check"),
    )
    # 조문과 FAQ를 따로 순위 매기므로 source별 부분 인덱스를 둔다. 인덱스 하나에 필터를 걸면
    # HNSW가 후보 ef_search개를 먼저 고른 뒤 필터를 걸어 k개보다 적게 돌아올 수 있다
    for source in ("law", "faq"):
        op.execute(
            f"CREATE INDEX chunks_embedding_{source}_hnsw ON chunks"
            f" USING hnsw (embedding vector_cosine_ops) WHERE source = '{source}'"
        )
    op.create_index("chunks_tokens_gin", "chunks", ["tokens"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("chunks_tokens_gin", table_name="chunks")
    op.execute("DROP INDEX chunks_embedding_faq_hnsw")
    op.execute("DROP INDEX chunks_embedding_law_hnsw")
    op.drop_table("chunks")

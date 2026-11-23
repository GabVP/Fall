"""Cria usuários e sessões.

Revision ID: 0002_access
Revises: 0001_baseline
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_access"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("login", sa.String(128, collation="C"), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("login", name="uq_users_login"),
        sa.CheckConstraint("char_length(login) > 0", name="ck_users_nonempty_login"),
    )
    op.create_index(
        "uq_users_active",
        "users",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_sessions_user"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_digest", name="uq_sessions_token_digest"),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_sessions_digest_size"),
        sa.CheckConstraint(
            "created_at <= last_seen_at AND last_seen_at < absolute_expires_at",
            name="ck_sessions_activity_window",
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("users")

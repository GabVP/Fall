"""Marco inicial sem entidades funcionais.

Revision ID: 0001_baseline
Revises:
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Registra apenas a versão de esquema administrada pelo Alembic."""


def downgrade() -> None:
    """Volta à base; não há tabelas de negócio a remover."""

"""remove a tabela usuarios: a interface e a API deixam de ter login

Revision ID: 0002_sem_login
Revises: 0001_inicial
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_sem_login"
down_revision = "0001_inicial"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("usuarios")


def downgrade():
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("senha_hash", sa.String(128), nullable=False),
        sa.Column("perfil", sa.String(16), nullable=False),
        sa.Column("criado_em", sa.DateTime, nullable=False),
    )

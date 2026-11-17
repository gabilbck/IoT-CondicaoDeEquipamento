"""esquema inicial: dispositivos, medicoes, comandos, comando_eventos, alertas, configuracoes, usuarios,
mensagens_invalidas, dispositivo_status

Revision ID: 0001_inicial
Revises:
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_inicial"
down_revision = None
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "dispositivos",
        sa.Column("device_id", sa.String(32), primary_key=True),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("online", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ultimo_contato", sa.DateTime),
        sa.Column("ultimo_estado", JSONB),
        sa.Column("fw", sa.String(32)),
    )
    op.create_table(
        "dispositivo_status",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(32), nullable=False, index=True),
        sa.Column("online", sa.Boolean, nullable=False),
        sa.Column("ts", sa.DateTime, nullable=False),
    )
    op.create_table(
        "medicoes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(32), nullable=False),
        sa.Column("grandeza", sa.String(16), nullable=False),
        sa.Column("valor", sa.Float),
        sa.Column("unidade", sa.String(8), nullable=False),
        sa.Column("valido", sa.Boolean, nullable=False),
        sa.Column("ts", sa.DateTime, nullable=False),
    )
    op.create_index("ix_medicoes_dev_grand_ts", "medicoes", ["device_id", "grandeza", "ts"])
    op.create_table(
        "comandos",
        sa.Column("command_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(32), nullable=False, index=True),
        sa.Column("origem", sa.String(48), nullable=False),
        sa.Column("usuario", sa.String(64)),
        sa.Column("acao", sa.String(16), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("codigo", sa.String(32)),
        sa.Column("expira_em_s", sa.Integer, nullable=False),
        sa.Column("enviado_em", sa.DateTime, nullable=False, index=True),
        sa.Column("recebido_em", sa.DateTime),
        sa.Column("executado_em", sa.DateTime),
        sa.Column("confirmado_em", sa.DateTime),
    )
    op.create_table(
        "comando_eventos",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("command_id", sa.String(36), nullable=False, index=True),
        sa.Column("fase", sa.String(16), nullable=False),
        sa.Column("resultado", sa.String(16)),
        sa.Column("codigo", sa.String(32)),
        sa.Column("detalhe", sa.Text),
        sa.Column("ts", sa.DateTime, nullable=False),
    )
    op.create_table(
        "alertas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tipo", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(32)),
        sa.Column("severidade", sa.String(16), nullable=False),
        sa.Column("mensagem", sa.Text, nullable=False),
        sa.Column("criado_em", sa.DateTime, nullable=False, index=True),
        sa.Column("resolvido_em", sa.DateTime),
        sa.Column("notificado", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "configuracoes",
        sa.Column("chave", sa.String(48), primary_key=True),
        sa.Column("valor", sa.Float, nullable=False),
        sa.Column("atualizado_em", sa.DateTime, nullable=False),
        sa.Column("atualizado_por", sa.String(64)),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("senha_hash", sa.String(128), nullable=False),
        sa.Column("perfil", sa.String(16), nullable=False),
        sa.Column("criado_em", sa.DateTime, nullable=False),
    )
    op.create_table(
        "mensagens_invalidas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topico", sa.String(128), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("erro", sa.Text, nullable=False),
        sa.Column("recebido_em", sa.DateTime, nullable=False, index=True),
    )


def downgrade():
    for t in ("mensagens_invalidas", "usuarios", "configuracoes", "alertas", "comando_eventos", "comandos",
              "medicoes", "dispositivo_status", "dispositivos"):
        op.drop_table(t)

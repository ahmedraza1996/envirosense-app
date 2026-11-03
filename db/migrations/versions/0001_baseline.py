"""Baseline schema: iam, audit, sem, ingest, core, wf

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade():
    op.get_bind().exec_driver_sql("DROP SCHEMA IF EXISTS wf, core, ingest, sem, audit, iam CASCADE")

"""Alignment check of uploads: route rules for placing tie points, choosing an alignment and confirming it before the assessment runs

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RULES = [("POST", "/api/uploads/[^/]+/alignment/(manual|choose|confirm)", "upload")]


def upgrade():
    c = op.get_bind()
    start = c.execute(sa.text("SELECT max(position) FROM iam.route_policy")).scalar()
    for i, (m, p, perm) in enumerate(RULES, start + 1):
        c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=i, m=m, p=p, x=perm))


def downgrade():
    op.get_bind().exec_driver_sql("DELETE FROM iam.route_policy WHERE path LIKE '/api/uploads/%%/alignment/%%'")

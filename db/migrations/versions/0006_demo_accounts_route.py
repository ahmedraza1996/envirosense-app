"""Route rule for the sign-in page's list of demo accounts (public; the route answers 404 when demo accounts are switched off)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

RULES = [("GET", "/api/auth/demo-accounts", "public")]


def upgrade():
    c = op.get_bind()
    start = c.execute(sa.text("SELECT max(position) FROM iam.route_policy")).scalar()
    for i, (m, p, perm) in enumerate(RULES, start + 1):
        c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=i, m=m, p=p, x=perm))


def downgrade():
    op.get_bind().exec_driver_sql("DELETE FROM iam.route_policy WHERE path = '/api/auth/demo-accounts'")

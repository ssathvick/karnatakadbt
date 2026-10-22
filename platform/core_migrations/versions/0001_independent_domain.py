"""Independent registry, programme, eligibility, audit and projection storage."""
revision='0001_independent_domain'
down_revision=None
def upgrade():
    from alembic import op
    from core_store import metadata
    metadata.create_all(op.get_bind())
def downgrade():
    raise RuntimeError('Restore the reviewed database backup rather than deleting domain data.')

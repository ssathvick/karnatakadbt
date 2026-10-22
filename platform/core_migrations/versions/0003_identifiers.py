"""Independent numeric-identifier namespaces and permanent issuance ledger."""
revision='0003_identifiers'
down_revision='0002_domain_indexes'
def upgrade():
    from alembic import op
    from identifier_store import metadata
    metadata.create_all(op.get_bind())
def downgrade():
    raise RuntimeError('Identifier history must not be dropped or reused by a downgrade.')

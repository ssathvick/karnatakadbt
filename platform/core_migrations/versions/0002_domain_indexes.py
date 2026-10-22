"""Indexes for queues, role-scoped registry access and historical collections."""
revision='0002_domain_indexes'
down_revision='0001_independent_domain'
def upgrade():
    from alembic import op
    from core_store import metadata
    for table in metadata.tables.values():
        for index in table.indexes:index.create(op.get_bind(),checkfirst=True)
def downgrade():
    from alembic import op
    for name in ['ix_registry_kind_subject','ix_registry_household','ix_applications_subject_status','ix_migration_collection','ix_outbox_status','ix_domain_events_at']:op.drop_index(name)

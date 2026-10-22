"""Fenced business-table projection for the remaining identity services.

Key material, scheduler locks and native security journals use their dedicated
recovery adapters. This adapter deliberately cannot authorize their transfer.
Callers must stop/drain writers and workers and retain a durable recovery journal
before using it. Table locks supplement that fence; they do not replace it.
"""
import hashlib
from contextlib import ExitStack

import psycopg2
from psycopg2 import sql

EXCLUDED = {'key_alias', 'key_policy_def', 'key_store', 'ca_cert_store', 'shedlock'}


def mirror_business_tables(source, destination, *, schema, quiescent, production_scope=None):
    if schema not in {'certify', 'esignet'} or not callable(quiescent) or quiescent() is not True:
        raise ValueError('Observed coordinated writer/worker fence required')
    if source['dbname'] == destination['dbname']:
        raise ValueError('Distinct migration databases required')
    if any(
            not c['dbname'].startswith(('kdbt_native_', 'kdbt_original_', 'kdbt_transfer_'))
            for c in (source, destination)):
        from native_remaining_three_projection_scope import ProductionProjectionScope
        if not isinstance(production_scope, ProductionProjectionScope):
            raise ValueError('Observed and pinned production projection scope required')
        production_scope.authorize(source, destination, schema)
        initial_observer = quiescent
        def quiescent():
            return initial_observer() is True and production_scope.require() is True
    with ExitStack() as stack:
        connections = {}
        for configuration in sorted((source, destination), key=lambda c: c['dbname']):
            connection = stack.enter_context(psycopg2.connect(**configuration, connect_timeout=5))
            connection.set_session(isolation_level='REPEATABLE READ')
            cursor = stack.enter_context(connection.cursor())
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='30s'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            connections[configuration['dbname']] = (connection, cursor)
        src, dst = connections[source['dbname']][1], connections[destination['dbname']][1]

        def tables(cursor):
            cursor.execute('''SELECT table_name FROM information_schema.tables
                WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name''', (schema,))
            return {r[0] for r in cursor.fetchall() if r[0] not in EXCLUDED and not r[0].startswith('native_')}

        selected = tables(src)
        if not selected or selected != tables(dst) or len(selected) > 64:
            raise ValueError('Exact bounded business table set required')
        for configuration in sorted((source, destination), key=lambda c: c['dbname']):
            cursor = connections[configuration['dbname']][1]
            cursor.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
                sql.SQL(',').join(sql.Identifier(schema, table) for table in sorted(selected))))
        if quiescent() is not True:
            raise ValueError('Writer/worker fence changed while acquiring locks')

        def columns(cursor, table):
            cursor.execute('''SELECT column_name,udt_schema,udt_name,is_generated,is_identity
                FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position''', (schema, table))
            return cursor.fetchall()

        signatures = {table: columns(src, table) for table in selected}
        if any(signatures[t] != columns(dst, t) or any(c[3] != 'NEVER' for c in signatures[t]) for t in selected):
            raise ValueError('Exact supported table columns required')
        # Reverse deletion and forward insertion respect nondeferrable FKs.
        dst.execute('''SELECT child.relname,parent.relname,parent_ns.nspname FROM pg_constraint fk
            JOIN pg_class child ON child.oid=fk.conrelid JOIN pg_namespace ns ON ns.oid=child.relnamespace
            JOIN pg_class parent ON parent.oid=fk.confrelid JOIN pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
            WHERE fk.contype='f' AND ns.nspname=%s''', (schema,))
        dependencies = {table: set() for table in selected}
        for child, parent, parent_schema in dst.fetchall():
            if child in selected:
                if parent_schema != schema or parent not in selected or parent == child:
                    raise ValueError('Cross-boundary or recursive foreign key requires dedicated recovery')
                dependencies[child].add(parent)
        order = []
        while len(order) < len(selected):
            ready = sorted(t for t in selected - set(order) if dependencies[t] <= set(order))
            if not ready:
                raise ValueError('Cyclic foreign key requires dedicated recovery')
            order.extend(ready)

        def rows(cursor, table):
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(sql.Identifier(schema, table)))
            values, size = [], 0
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    return values
                for (value,) in batch:
                    size += len(value.encode())
                    values.append(value)
                    if size > 128 * 1024 * 1024 or len(values) > 100000:
                        raise ValueError('Bounded business snapshot exceeded')

        incoming = {table: rows(src, table) for table in order}
        if quiescent() is not True:
            raise ValueError('Writer/worker fence changed before projection')
        for table in reversed(order):
            dst.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(schema, table)))
        for table in order:
            if incoming[table]:
                # Preserve PostgreSQL numeric precision and bytea/date values;
                # no JSON numbers are round-tripped through Python floats.
                payload = '[' + ','.join(incoming[table]) + ']'
                dst.execute(sql.SQL('INSERT INTO {} OVERRIDING SYSTEM VALUE SELECT * FROM json_populate_recordset(NULL::{},%s::json)').format(
                    sql.Identifier(schema, table), sql.Identifier(schema, table)), (payload,))
            if rows(dst, table) != incoming[table]:
                raise ValueError('Business projection differs from authoritative snapshot')

        sequences = 0
        for table in order:
            for column, *_ in signatures[table]:
                src.execute('SELECT pg_get_serial_sequence(%s,%s)', (schema + '.' + table, column))
                source_sequence = src.fetchone()[0]
                dst.execute('SELECT pg_get_serial_sequence(%s,%s)', (schema + '.' + table, column))
                target_sequence = dst.fetchone()[0]
                if bool(source_sequence) != bool(target_sequence):
                    raise ValueError('Owned sequence metadata differs')
                if source_sequence:
                    # Names returned by PostgreSQL are qualified identifiers,
                    # resolved to OIDs before reading their fixed catalog fields.
                    def sequence_state(cursor, name):
                        cursor.execute('SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=%s::regclass', (name,))
                        namespace, relation = cursor.fetchone()
                        cursor.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(namespace, relation)))
                        return cursor.fetchone()
                    before, current = sequence_state(src, source_sequence), sequence_state(dst, target_sequence)
                    dst.execute(sql.SQL('SELECT max({}) FROM {}').format(sql.Identifier(column), sql.Identifier(schema, table)))
                    maximum = dst.fetchone()[0]
                    high = max(before[0], current[0], maximum if maximum is not None else before[0])
                    called = before[1] or current[1] or maximum is not None
                    dst.execute('SELECT setval(%s::regclass,%s,%s)', (target_sequence, high, called))
                    sequences += 1
        if quiescent() is not True:
            raise ValueError('Writer/worker fence changed before commit')
        # Only the destination changes. A failure before this commit rolls its
        # table data back; PostgreSQL sequence advances are never rewound.
        connections[destination['dbname']][0].commit()
        return {'business_tables': len(order), 'rows': sum(map(len, incoming.values())),
                'owned_sequences_reconciled': sequences, 'native_security_journals_preserved': True,
                'crypto_and_scheduler_state_excluded': True,
                'table_sha256': {t: hashlib.sha256(('\n'.join(incoming[t])).encode()).hexdigest() for t in order}}

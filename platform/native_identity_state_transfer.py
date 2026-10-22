"""Atomic expiry-preserving projection between quiescent native identity stores."""
import hmac
import math
import re
import sqlite3
from contextlib import ExitStack
from pathlib import Path

TABLES={'identities','challenges','exchanges','wallet_proof_replay','legacy_exchange_history'}


def reconcile_wallet_replay(source_settings,destination_settings,*,quiescent,checkpoint):
    """Monotonically merge proof tombstones without renewing an expiry.

    All other business tables must match exactly. A crash between commits can
    only add replay protection; the same union is safe to resume. Neither a
    credential nor an authentication session is created by this operation.
    """
    if not callable(checkpoint) or quiescent() is not True:raise ValueError('Observed fences and durable checkpoint required')
    paths=[Path(s['database']).resolve(strict=True) for s in [source_settings,destination_settings]]
    root=Path('/opt/karnatakadbt/private/mosip-migration').resolve()
    if paths[0]==paths[1] or any(not p.is_relative_to(root) or p.stat().st_uid!=0 or p.stat().st_mode&0o077 for p in paths):raise ValueError('Protected distinct stores required')
    if not hmac.compare_digest(source_settings['data_key'],destination_settings['data_key']):raise ValueError('Matching identity keys required')
    with ExitStack() as stack:
        connections=[]
        for path in sorted(paths,key=str):
            c=sqlite3.connect(path,timeout=5);stack.callback(c.close);c.execute('BEGIN IMMEDIATE');connections.append(c)
        try:
            for c in connections:
                if c.execute('SELECT owner FROM control WHERE id=1').fetchone()!=('FENCED',):raise ValueError('Closed authority barriers required')
            schemas=[]
            for c in connections:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}-{'control'}
                if tables-TABLES or 'wallet_proof_replay' not in tables:raise ValueError('Known identity tables required')
                schemas.append({table:c.execute('PRAGMA table_info("'+table+'")').fetchall() for table in tables})
            if schemas[0]!=schemas[1]:raise ValueError('Matching identity schemas required')
            for table in schemas[0]:
                if table=='wallet_proof_replay':continue
                rows=[sorted(c.execute('SELECT * FROM "'+table+'"').fetchall()) for c in connections]
                if rows[0]!=rows[1]:raise ValueError('Non-replay identity differences require explicit recovery')
            union={}
            for c in connections:
                for proof,expiry in c.execute('SELECT proof_hash,expires FROM wallet_proof_replay'):
                    if not isinstance(proof,str) or not re.fullmatch('[a-f0-9]{64}',proof) or not isinstance(expiry,(int,float)) or not math.isfinite(expiry) or expiry<=0:raise ValueError('Valid replay tombstone required')
                    union[proof]=max(union.get(proof,0),expiry)
                    if len(union)>100000:raise ValueError('Replay merge exceeds bounded scope')
            checkpoint({'phase':'REPLAY_UNION_INTENT','rows':len(union),'absolute_expiry_preserved':True})
            for index,c in enumerate(connections):
                if quiescent() is not True:raise ValueError('Producer fences changed')
                c.executemany('INSERT INTO wallet_proof_replay(proof_hash,expires) VALUES(?,?) ON CONFLICT(proof_hash) DO UPDATE SET expires=MAX(wallet_proof_replay.expires,excluded.expires)',sorted(union.items()))
                if c.execute('SELECT proof_hash,expires FROM wallet_proof_replay ORDER BY proof_hash').fetchall()!=sorted(union.items()):raise ValueError('Replay union verification failed')
                c.commit();checkpoint({'phase':'REPLAY_UNION_COMMIT','store':index,'rows':len(union)})
            return {'passed':True,'rows':len(union),'absolute_expiry_preserved':True,'monotonic_replay_protection':True}
        except BaseException:
            for c in connections:c.rollback()
            raise


def mirror_identity_state(source_settings,destination_settings,*,quiescent):
    """Replace destination business state, preserving its closed owner barrier.

    Both service processes must be stopped/drained by the coordinator. SQLite
    IMMEDIATE transactions then lock both complete stores in lexical path order.
    Absolute timestamps, counters and tombstones are copied without renewal.
    """
    if not callable(quiescent) or quiescent() is not True:
        raise ValueError('Observed producer/worker quiescence required')
    paths=[Path(s['database']).resolve(strict=True) for s in [source_settings,destination_settings]]
    root=Path('/opt/karnatakadbt/private/mosip-migration').resolve()
    if paths[0]==paths[1] or any(not p.is_relative_to(root) or p.stat().st_uid!=0 or p.stat().st_mode&0o077 for p in paths):
        raise ValueError('Distinct protected identity stores required')
    if not hmac.compare_digest(source_settings['data_key'],destination_settings['data_key']):
        raise ValueError('Identity wrapping/HMAC keys differ; explicit re-encryption required')
    with ExitStack() as stack:
        connections={}
        for path in sorted(paths,key=str):
            c=sqlite3.connect(path,timeout=5);stack.callback(c.close);c.execute('BEGIN IMMEDIATE');connections[path]=c
        source,destination=[connections[p] for p in paths]
        try:
            for connection in [source,destination]:
                if connection.execute('SELECT owner FROM control WHERE id=1').fetchone()!=('FENCED',):
                    raise ValueError('Both durable identity ownership barriers must be closed')
            schemas=[]
            for connection in [source,destination]:
                tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'identities','challenges','exchanges','control','wallet_proof_replay'}<=tables or tables-{'control'}-TABLES:
                    raise ValueError('Unknown identity state table requires a migration adapter')
                schemas.append({table:connection.execute('PRAGMA table_info("'+table+'")').fetchall() for table in tables-{'control'}})
            if schemas[0]!=schemas[1]:raise ValueError('Identity state schemas differ')
            snapshots={};total_rows=total_bytes=0
            for table,columns in sorted(schemas[0].items()):
                order=','.join('"'+v[1]+'"' for v in sorted(columns,key=lambda v:v[5]) if v[5])
                if not order:raise ValueError('Explicit identity state primary key required')
                rows=source.execute('SELECT * FROM "'+table+'" ORDER BY '+order).fetchall()
                total_rows+=len(rows)
                total_bytes+=sum(len(v.encode()) if isinstance(v,str) else len(v) if isinstance(v,bytes) else 8 for row in rows for v in row)
                if total_rows>100000 or total_bytes>128*1024*1024:raise ValueError('Identity state transfer exceeds bound')
                snapshots[table]=(rows,order,len(columns))
            if quiescent() is not True:raise ValueError('Identity producer/worker fence changed')
            for table,(rows,order,width) in snapshots.items():
                destination.execute('DELETE FROM "'+table+'"')
                destination.executemany('INSERT INTO "'+table+'" VALUES('+','.join('?' for _ in range(width))+')',rows)
                if destination.execute('SELECT * FROM "'+table+'" ORDER BY '+order).fetchall()!=rows:
                    raise ValueError('Identity projection verification failed')
            if quiescent() is not True:raise ValueError('Identity producer/worker fence changed before commit')
            destination.commit();source.commit()
            return {'tables':len(snapshots),'rows':total_rows,'absolute_expiry_and_replay_state_preserved':True,
                    'destination_remains_fenced':True}
        except BaseException:
            destination.rollback();source.rollback();raise

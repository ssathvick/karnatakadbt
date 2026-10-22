"""Native household side effects for the pending change-approval pipeline.

These hooks do not approve a request or commit a transaction. The approval
coordinator must call them inside the transaction that updates the member,
history, documents and durable downstream jobs.
"""
from copy import deepcopy
from datetime import date

from sqlalchemy import select, update, cast, literal, Text
from sqlalchemy.dialects.postgresql import JSONB

from registry_domain_validation import day, number
from registry_record_store import records

ROSTER_FIELDS = frozenset({
    'link_internal_record_id', 'record_status', 'birth_date',
    'estimated_age', 'gender', 'residency_status',
})


def normalized_link(value):
    return str(value).strip() or None if value is not None else None


def roster_counts(members, today=None):
    today = today or date.today()
    counts = dict.fromkeys([
        'size_total', 'size_adults', 'size_children_u5', 'size_school_age',
        'size_elderly', 'number_of_female_members', 'number_of_male_members',
    ], 0)
    for member in members:
        if (member.get('record_status') or 'ACTIVE') != 'ACTIVE':
            continue
        counts['size_total'] += 1
        birth = day(member.get('birth_date'))
        age = (today.year - birth.year -
               ((today.month, today.day) < (birth.month, birth.day))) if birth else number(member.get('estimated_age'))
        if age is not None:
            field = ('size_children_u5' if age <= 4 else 'size_school_age' if age <= 17
                     else 'size_adults' if age <= 59 else 'size_elderly')
            counts[field] += 1
        if member.get('gender') in {'MALE', 'FEMALE'}:
            counts['number_of_' + member['gender'].lower() + '_members'] += 1
    return {**counts, 'elderly_member_present': counts['size_elderly'] > 0}


def before_individual_approval(individual, payloads, households, members, today=None):
    """Return household updates using the captured pre-approval semantics.

    Each payload is overlaid on the original member, as in the existing hook;
    this deliberately does not simulate the later register update here.
    """
    result = {}
    if individual is None:
        return result
    for payload in payloads or []:
        if payload.get('edit_action') == 'NO_CHANGE' or not ROSTER_FIELDS.intersection(payload):
            continue
        old = normalized_link(individual.get('link_internal_record_id'))
        changed = {**individual, **{key: value for key, value in payload.items()
                                   if key in ROSTER_FIELDS or key == 'internal_record_id'}}
        affected = {old}
        if 'link_internal_record_id' in payload:
            affected.add(normalized_link(payload['link_internal_record_id']))
        for household in sorted(affected - {None}):
            if household not in households:
                continue
            roster = {member['internal_record_id']: member for member in members
                      if member.get('link_internal_record_id') == household}
            key = individual['internal_record_id']
            if (normalized_link(changed.get('link_internal_record_id')) == household
                    and (changed.get('record_status') or 'ACTIVE') == 'ACTIVE'):
                roster[key] = changed
            else:
                roster.pop(key, None)
            result[household] = roster_counts(roster.values(), today)
    return result


def after_individual_approval(individual, payloads, households, approved_at):
    """Preserve the existing death annotation, including its legacy naming."""
    if individual is None or not individual.get('link_internal_record_id'):
        return {}
    household = individual['link_internal_record_id']
    if household not in households:
        return {}
    if any(p.get('record_status') == 'INACTIVE' and p.get('record_status_reason') == 'Death'
           for p in payloads or []):
        return {household: {'husband_dead': True, 'husband_dead_date': approved_at.date().isoformat()}}
    return {}


class ApprovalDomainHooks:
    """Apply household changes to native snapshots on the caller's connection.

    Register identifiers come from trusted deployment metadata. Deterministic
    household row locking serializes updates to the same household. The outer
    coordinator must obtain these locks before writing the member itself.
    """
    def __init__(self, individual_register, household_register):
        self.individual_register = individual_register
        self.household_register = household_register

    @staticmethod
    def require_candidate(connection):
        if not (connection.engine.url.database or '').startswith('kdbt_registry_candidate_'):
            raise ValueError('Isolated approval-domain candidate required')

    def member(self, connection, subject):
        self.require_candidate(connection)
        value = connection.execute(select(records.c.data).where(
            records.c.kind == 'current', records.c.register_id == self.individual_register,
            records.c.record_id == subject)).scalar_one_or_none()
        return deepcopy(value)

    def lock_households(self, connection, individual, payloads):
        self.require_candidate(connection)
        links = {normalized_link(individual.get('link_internal_record_id'))} if individual else set()
        links.update(normalized_link(p.get('link_internal_record_id')) for p in payloads or [])
        return {row.record_id: row.data for row in connection.execute(
            select(records.c.record_id, records.c.data).where(
                records.c.kind == 'current', records.c.register_id == self.household_register,
                records.c.record_id.in_(links - {None})).order_by(records.c.record_id).with_for_update())}

    def apply(self, connection, updates):
        self.require_candidate(connection)
        for household, values in updates.items():
            # Merge in PostgreSQL so untouched decimal values and JSON nulls are
            # preserved exactly in both the indexed JSON and original-text view.
            expression = records.c.data.op('||')(literal(values, type_=JSONB))
            connection.execute(update(records).where(
                records.c.kind == 'current', records.c.register_id == self.household_register,
                records.c.record_id == household).values(data=expression, source_json=cast(expression, Text)))

    def before(self, connection, subject, payloads, today=None):
        individual = self.member(connection, subject)
        households = self.lock_households(connection, individual, payloads)
        members = list(connection.execute(select(records.c.data).where(
            records.c.kind == 'current', records.c.register_id == self.individual_register,
            records.c.link_id.in_(households))).scalars()) if households else []
        updates = before_individual_approval(individual, payloads, households, members, today)
        self.apply(connection, updates)
        return updates

    def after(self, connection, subject, payloads, approved_at):
        individual = self.member(connection, subject)
        households = self.lock_households(connection, individual, payloads)
        updates = after_individual_approval(individual, payloads, households, approved_at)
        self.apply(connection, updates)
        return updates

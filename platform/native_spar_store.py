"""Independent financial-address mapping operations using parameterized SQL.

Transaction boundaries intentionally preserve the deployed mapping API: links
and unlinks commit per batch, updates commit per successful item. Authentication
and production ownership admission belong to the HTTP boundary.
"""
import copy
import re
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import text


class ProviderTypeEnum(str, Enum):
    BANK = 'BANK'
    EMAIL_WALLET = 'EMAIL_WALLET'
    MOBILE_WALLET = 'MOBILE_WALLET'


def now():
    return datetime.now(timezone.utc)


class NativeSparStore:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _mapping(connection, identifier):
        return connection.execute(text('SELECT * FROM public.id_fa_mappings WHERE id_value=:id'), {'id': identifier}).mappings().first()

    @staticmethod
    def _row(item, **values):
        return dict(reference_id=item['reference_id'], timestamp=now(), locale=item.get('locale', 'en'), **values)

    def _prepare(self, connection, items):
        result = copy.deepcopy(items)
        for item in result:
            fa = item.get('fa')
            if not fa:
                continue
            strategy = connection.execute(text('SELECT construct_strategy FROM public.strategy WHERE id=:id'), {'id': fa['strategy_id']}).scalar_one()
            # The existing protocol formats a str/Enum through Python's format
            # operator. Preserve stored addresses byte for byte during migration.
            fields = dict(fa, fa_type=ProviderTypeEnum(fa['fa_type']))
            item['fa'] = strategy.format(**fields)
            if not item.get('additional_info'):
                item['additional_info'] = [{}]
            item['additional_info'][0].setdefault('strategy_id', fa['strategy_id'])
        return result

    def execute(self, operation, request):
        if operation not in {'link', 'resolve', 'update', 'unlink'}:
            raise ValueError('Unknown mapping operation')
        payload = request['request_body']['request_payload']
        items = payload[operation + '_request']
        output = []
        header = dict(request_id=request['request_header']['request_id'], response_status='SUCCESS', response_error_code=None, response_error_message=None, response_timestamp=now())
        response = dict(response_header=header, response_body=dict(response_payload=dict(transaction_id=payload.get('transaction_id'), correlation_id=None, **{operation + '_response': output})))
        if not items:
            header.update(response_status='ERROR', response_error_code='rjct.request.validation', response_error_message='Request payload cannot be empty')
            return response
        with self.engine.connect() as connection:
            try:
                if operation in {'link', 'update'}:
                    items = self._prepare(connection, items)
                if operation == 'resolve':
                    self._resolve(connection, items, output)
                else:
                    pending = []
                    for item in items:
                        identifier, address = item.get('id'), item.get('fa')
                        base = {'fa': address} if operation == 'link' else {'id': identifier} if operation == 'update' else {}
                        reason = message = None
                        record = None
                        if not identifier:
                            reason, message = 'rjct.id.invalid', 'ID is null'
                        elif operation in {'link', 'update'} and not address:
                            reason, message = 'rjct.fa.invalid', 'FA is null'
                        else:
                            record = self._mapping(connection, identifier)
                            if operation == 'link' and record:
                                reason, message = 'rjct.reference_id.duplicate', 'ID and FA are already mapped'
                            elif operation == 'update' and not record:
                                reason, message = 'rjct.reference_id.duplicate', 'ID doesnt exist please link first'
                            elif operation == 'unlink' and (not record or (address and address != record['fa_value'])):
                                reason, message = 'rjct.id.invalid', 'ID doesnt exist please link first'
                        if not reason:
                            if operation == 'link':
                                pending.append(item)
                            elif operation == 'unlink':
                                connection.execute(text('DELETE FROM public.id_fa_mappings WHERE id_value=:id'), {'id': identifier})
                            else:
                                self._update(connection, item)
                                connection.commit()
                        output.append(self._row(item, **base, status='rjct' if reason else 'succ', status_reason_code=reason, status_reason_message=message, additional_info=None))
                    for item in pending:
                        self._insert(connection, item)
                    connection.commit()
            except Exception:
                connection.rollback()
                output.clear()
                header.update(response_status='ERROR', response_error_code='rjct.internal.error', response_error_message='Internal server error')
        return response

    @staticmethod
    def _insert(connection, item):
        import json
        connection.execute(text('''INSERT INTO public.id_fa_mappings
            (active,created_at,updated_at,id_value,fa_value,name,phone,additional_info)
            VALUES (true,:at,:at,:id,:fa,:name,:phone,CAST(:extra AS json))'''),
            dict(at=now().replace(tzinfo=None), id=item['id'], fa=item['fa'], name=item.get('name'), phone=item.get('phone_number'), extra=json.dumps(item.get('additional_info'))))

    @staticmethod
    def _update(connection, item):
        import json
        fields = {column: item[key] for key, column in [('fa', 'fa_value'), ('name', 'name'), ('phone_number', 'phone'), ('additional_info', 'additional_info')] if item.get(key)}
        assignments = ','.join(column + ('=CAST(:' + column + ' AS json)' if column == 'additional_info' else '=:' + column) for column in fields)
        if 'additional_info' in fields:
            fields['additional_info'] = json.dumps(fields['additional_info'])
        if assignments:
            connection.execute(text('UPDATE public.id_fa_mappings SET ' + assignments + ' WHERE id_value=:identifier'), dict(fields, identifier=item['id']))

    def _resolve(self, connection, items, output):
        valid = []
        for item in items:
            if not item.get('id') and not item.get('fa'):
                output.append(self._row(item, status='rjct', status_reason_code='rjct.reference_id.invalid', status_reason_message='ID is required'))
            else:
                valid.append(item)
        for item in valid:
            record = self._mapping(connection, item.get('id'))
            if not record:
                output.append(self._row(item, status='succ', status_reason_code='succ.fa_not_linked_to_id', status_reason_message="ID doesn't exist, please link first", fa=None, additional_info=None))
                # The wire enum uses periods; the older mapper's code uses the
                # underscore spelling internally. Return the declared wire value.
                output[-1]['status_reason_code'] = 'succ.fa.not_linked_to_id'
                continue
            address = None
            extra = item.get('additional_info')
            if item.get('scope', 'yes_no') == 'details':
                extra = record['additional_info']
                if record['fa_value'] and extra:
                    strategy_id = extra[0].get('strategy_id')
                    pattern = connection.execute(text('SELECT deconstruct_strategy FROM public.strategy WHERE id=:id'), {'id': strategy_id}).scalar_one_or_none()
                    match = re.match(pattern, record['fa_value']) if pattern else None
                    address = dict(match.groupdict() if match else {}, strategy_id=strategy_id) if pattern else {}
            output.append(self._row(item, id=item.get('id'), fa=address, status='succ', status_reason_code='succ.id.active', status_reason_message=None, additional_info=extra, account_provider_info=None))

    def reference_rows(self, kind, bank_id=None):
        table = {'banks': 'banks', 'branches': 'branches', 'wallet_service_providers': 'wallet_service_providers'}[kind]
        condition, order, parameters = 'active=true', 'id', {}
        if kind == 'branches' and bank_id is not None:
            condition, order, parameters = 'bank_id=:bank', 'branch_name', {'bank': bank_id}
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text('SELECT * FROM public.' + table + ' WHERE ' + condition + ' ORDER BY ' + order), parameters).mappings()]

"""Native partner and beneficiary mapping API boundaries.

Production assembly must supply signature/bearer authentication and writer
admission explicitly. Omitted integrations fail closed; this factory never
turns a test principal or an unverified token into production authority.
"""
import inspect
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from native_contract_models import ContractModels
from native_partner_signatures import PartnerKeyUnavailable
from native_spar_store import now


def create_native_spar_app(store, *, profile, signatures=None, authenticate=None, writer_admission=None):
    if profile not in {'partner', 'beneficiary'}:
        raise ValueError('Explicit account-mapping profile required')
    contract = json.loads(Path(__file__).with_name('native_spar_' + profile + '_contract.json').read_text())
    models = ContractModels(contract)
    app = FastAPI(title='KarnatakaDBT Account Mapping ' + profile.title(), version='1.0.0')

    @app.middleware('http')
    async def identify(request, call_next):
        response = await call_next(request)
        response.headers['X-KarnatakaDBT-Mapping-Backend'] = 'native'
        return response

    @app.get('/ping')
    def ping():
        return 'pong'

    def mapping_route(operation):
        request_model = models.type({'$ref': '#/components/schemas/' + operation.title() + 'Request'})
        response_model = models.type({'$ref': '#/components/schemas/' + operation.title() + 'Response'})

        async def handle(payload, request: Request):
            body = payload.model_dump(mode='json')
            if profile == 'partner':
                if signatures is None:
                    raise HTTPException(503, 'Partner signature integration is unavailable')
                try:
                    verified = await run_in_threadpool(signatures.verify, request.headers.get('signature', ''), await request.json())
                except PartnerKeyUnavailable:
                    raise HTTPException(503, 'Partner verification keys are unavailable') from None
                if not verified:
                    raise HTTPException(401, 'Invalid partner signature')
            else:
                principal = authenticate(request) if authenticate else None
                if inspect.isawaitable(principal):
                    principal = await principal
                if not isinstance(principal, dict) or not isinstance(principal.get('sub'), str) or not principal['sub']:
                    raise HTTPException(401, 'Beneficiary authentication required')
                rows = body['request_body']['request_payload'][operation + '_request']
                for row in rows:
                    # A beneficiary cannot supply another person's ID to resolve.
                    # Privileged staff delegation must be explicitly authorized
                    # by the trusted authentication integration, never the body.
                    if operation != 'resolve' or not row.get('id') or not principal.get('may_resolve_other_subjects', False):
                        row['id'] = principal['sub']
            def execute():
                if operation == 'resolve':
                    return store.execute(operation, body)
                if writer_admission is None:
                    raise HTTPException(503, 'Native mapping writer remains in standby')
                with writer_admission():
                    return store.execute(operation, body)
            return await run_in_threadpool(execute)

        handle.__name__ = operation + '_' + profile
        handle.__annotations__['payload'] = request_model
        app.add_api_route('/mapper/' + operation, handle, methods=['POST'], response_model=response_model)

    for operation in ['link', 'resolve', 'unlink', 'update']:
        mapping_route(operation)

    if profile == 'beneficiary':
        def reference_route(path, kind):
            operation = contract['paths'][path]['post']
            request_model = models.type(operation['requestBody']['content']['application/json']['schema'])
            response_model = models.type(operation['responses']['200']['content']['application/json']['schema'])

            def handle(payload):
                body = payload.model_dump(mode='json')
                rows = store.reference_rows(kind, body['request_body']['request_payload'].get('bank_id'))
                return {'response_header': {'request_id': body['request_header']['request_id'], 'response_status': 'SUCCESS', 'response_error_code': None, 'response_error_message': None, 'response_timestamp': now()}, 'response_body': {'response_payload': {kind: rows}}}

            handle.__name__ = kind + '_reference'
            handle.__annotations__['payload'] = request_model
            app.add_api_route(path, handle, methods=['POST'], response_model=response_model)
        for path, kind in [('/dfsp/fetch-banks', 'banks'), ('/dfsp/fetch-branches', 'branches'), ('/dfsp/fetch-wallet-service-providers', 'wallet_service_providers')]:
            reference_route(path, kind)
    return app

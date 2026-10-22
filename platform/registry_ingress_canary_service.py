"""Ephemeral, read-only registry endpoint for production ingress acceptance."""
import json,os
from pathlib import Path
from sqlalchemy import create_engine,text
from registry_metadata_api import create_app
from registry_metadata_store import RegistryMetadataStore
from registry_console_auth import RegistryConsoleAuthorizer

settings=json.loads(Path(os.environ['KDBT_INGRESS_CANARY_SETTINGS']).read_text())
contract=json.loads(Path(__file__).with_name('registry_metadata_contract.json').read_text())
contract['paths']={k:v for k,v in contract['paths'].items() if k=='/registry-language/get_all_languages'}
engine=create_engine(settings['url'],hide_parameters=True,pool_pre_ping=True)
app=create_app(RegistryMetadataStore(engine),RegistryConsoleAuthorizer(settings['iam_url'],allowed_origins=['https://localhost:8443']),contract)
@app.get('/health')
def health():
    with engine.connect() as c:
        if c.execute(text('SHOW transaction_read_only')).scalar_one()!='on':raise RuntimeError('Read-only database admission required')
    return {'ready':True}

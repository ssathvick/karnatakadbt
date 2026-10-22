"""Versioned local models, NOT government database dumps or production contracts."""
VERSION = '1.0.0'
PUBLIC_STANDARDS = [
 {'name':'MDDS generic person and location domains','url':'https://docs.apisetu.gov.in/document-central/mdds/','use':'Conceptual guidance only; local column names and project codes are simulated'},
 {'name':'DigiLocker generic certificate XML structure','url':'https://docs.apisetu.gov.in/document-central/dl-xml-format/XML%20Format.html','use':'Explicit field mappings in XML_MAPPINGS; no signature or production issuer API implemented'},
]
SOURCES = {
 'kutumba': ('Kutumba family register', 'Centre for e Governance', 'https://negd.gov.in/isl/Directory/statedata/403', 'Public domain description; simulated tables and API'),
 'ahara': ('AHARA ration register', 'Food Civil Supplies and Consumer Affairs', 'https://nfsa.gov.in/State/KA', 'Public service description; simulated tables and API'),
 'revenue': ('Nadakacheri certificate register', 'Revenue Department', 'https://bagalkot.nic.in/en/service/nadakacheri-ajsk/', 'Public service description; simulated tables and API'),
 'fruits': ('FRUITS farmer register', 'Agriculture and allied departments', 'https://amritmahotsav.negd.in/presentation/FRUITS-Rajeev%20Chawla,%20Additional%20Secretary,%20eGovernance,%20Karnataka.pdf', 'Published field domains; simulated tables and API'),
 'bhoomi': ('Bhoomi land register', 'Revenue Department', 'https://bengaluruurban.nic.in/en/bhoomi/', 'Public service description; simulated tables and API'),
 'ejanma': ('eJanMa life events', 'Birth and death registration authorities', 'https://informatics.nic.in/files/websites/january-2025/karnatakas-eJanma-revolutionizes-issuance-of-digitally-signed-birth-and-death-certificates.php', 'Public service description; simulated tables and API'),
 'education': ('Education and SSP register', 'Education and scholarship departments', 'https://www.nic.gov.in/state-content/karnataka/', 'Public service description; simulated tables and API'),
 'sevasindhu': ('Seva Sindhu applications', 'Service owning departments and platform team', 'https://www.nic.gov.in/state-content/karnataka/', 'Public service description; simulated tables and API'),
 'geography': ('Location master', 'LGD and state location custodians', 'https://lgdirectory.gov.in/', 'Published code domains; project codes are synthetic, official LGD mappings unset'),
 'identity': ('Identity verification simulator', 'Authorised identity provider for future onboarding', 'https://uidai.gov.in/en/ecosystem/authentication-devices-documents/requesting-agency.html', 'Local tokens only; no Aadhaar numbers, biometrics or authentication'),
 'documents': ('Document verification simulator', 'Document issuers via approved DigiLocker route', 'https://docs.apisetu.gov.in/document-central/dl-xml-format/XML%20Format.html', 'Published XML field mappings; local SQL and JSON API are simulated; no digital signatures'),
 'schemes': ('Scheme and sanction register', 'Sponsoring scheme department', 'https://negd.gov.in/isl/Directory/statedata/403', 'Demonstration rules and sanctions, not official scheme criteria'),
 'treasury': ('Treasury funding simulator', 'Finance and authorised treasury team', 'https://www.nic.gov.in/state-content/karnataka/', 'Local funding model, not a treasury contract'),
 'bank': ('State DBT and bank simulator', 'Authorised state DBT and bank route', 'https://www.nic.gov.in/state-content/karnataka/', 'Local accounts, instructions and settlement model, not a financial API'),
 'notifications': ('Notification and grievance simulator', 'Programme support team', 'https://negd.gov.in/isl/Directory/statedata/403', 'Local delivery and case model; no external messages'),
}
# Compact declarative SQL definitions. Foreign keys are within each source database;
# source references between databases are resolved through explicit crosswalks.
DDL = {
 'kutumba': '''CREATE TABLE families(family_id TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, household_name TEXT NOT NULL, district_id TEXT NOT NULL, address_line TEXT NOT NULL, monthly_income_inr INTEGER NOT NULL CHECK(monthly_income_inr>=0), status TEXT NOT NULL CHECK(status IN ('active','inactive')), source_updated_at TEXT NOT NULL);
 CREATE TABLE members(person_id TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES families(family_id), platform_member_ref TEXT UNIQUE NOT NULL, given_name TEXT NOT NULL, family_name TEXT NOT NULL, birth_date TEXT NOT NULL, gender TEXT NOT NULL, relationship TEXT NOT NULL, identity_token TEXT UNIQUE NOT NULL, source_updated_at TEXT NOT NULL);''',
 'ahara': '''CREATE TABLE ration_cards(card_id TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, family_id TEXT NOT NULL, category TEXT NOT NULL CHECK(category IN ('PHH','AAY','NPHH')), status TEXT NOT NULL CHECK(status IN ('active','inactive')), district_id TEXT NOT NULL, source_updated_at TEXT NOT NULL);
 CREATE TABLE card_members(card_id TEXT NOT NULL REFERENCES ration_cards(card_id), person_id TEXT NOT NULL, PRIMARY KEY(card_id,person_id));''',
 'revenue': '''CREATE TABLE certificates(certificate_id TEXT PRIMARY KEY, household_ref TEXT NOT NULL, person_id TEXT NOT NULL, certificate_type TEXT NOT NULL CHECK(certificate_type IN ('income','residence')), annual_income_inr INTEGER CHECK(annual_income_inr>=0), issued_on TEXT NOT NULL, valid_until TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','revoked','expired')), source_updated_at TEXT NOT NULL, UNIQUE(household_ref,certificate_type));''',
 'fruits': '''CREATE TABLE farmers(farmer_id TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, person_id TEXT NOT NULL, family_id TEXT NOT NULL, registration_status TEXT NOT NULL CHECK(registration_status IN ('active','inactive')), source_updated_at TEXT NOT NULL);
 CREATE TABLE crops(crop_id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL REFERENCES farmers(farmer_id), parcel_id TEXT NOT NULL, season TEXT NOT NULL, crop_name TEXT NOT NULL, area_hectares REAL NOT NULL CHECK(area_hectares>0));''',
 'bhoomi': '''CREATE TABLE parcels(parcel_id TEXT PRIMARY KEY, household_ref TEXT NOT NULL, district_id TEXT NOT NULL, village_code TEXT NOT NULL, survey_number TEXT NOT NULL, extent_hectares REAL NOT NULL CHECK(extent_hectares>0), owner_person_id TEXT NOT NULL, mutation_status TEXT NOT NULL CHECK(mutation_status IN ('clear','pending')), source_updated_at TEXT NOT NULL);''',
 'ejanma': '''CREATE TABLE life_events(event_id TEXT PRIMARY KEY, household_ref TEXT NOT NULL, person_id TEXT UNIQUE NOT NULL, birth_date TEXT NOT NULL, death_date TEXT, registration_status TEXT NOT NULL CHECK(registration_status IN ('registered','under_review')), source_updated_at TEXT NOT NULL);''',
 'education': '''CREATE TABLE students(student_id TEXT PRIMARY KEY, household_ref TEXT NOT NULL, person_id TEXT UNIQUE NOT NULL, institution_id TEXT NOT NULL, academic_year TEXT NOT NULL, course TEXT NOT NULL, enrolment_status TEXT NOT NULL CHECK(enrolment_status IN ('active','inactive')), scholarship_status TEXT NOT NULL CHECK(scholarship_status IN ('none','sanctioned','paid')), source_updated_at TEXT NOT NULL);''',
 'sevasindhu': '''CREATE TABLE service_applications(application_id TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, service_code TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('submitted','approved','returned')), source_updated_at TEXT NOT NULL);''',
 'geography': '''CREATE TABLE districts(district_id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, division TEXT NOT NULL, official_lgd_code TEXT, code_status TEXT NOT NULL CHECK(code_status='synthetic_project_code'));
 CREATE TABLE locations(location_id TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, district_id TEXT NOT NULL REFERENCES districts(district_id), village_code TEXT NOT NULL, latitude REAL CHECK(latitude BETWEEN -90 AND 90), longitude REAL CHECK(longitude BETWEEN -180 AND 180), coordinate_source TEXT NOT NULL, verified INTEGER NOT NULL CHECK(verified IN (0,1)), CHECK((latitude IS NULL)=(longitude IS NULL)));''',
 'identity': '''CREATE TABLE verifications(identity_token TEXT PRIMARY KEY, household_ref TEXT NOT NULL, person_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, birth_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('verified','mismatch','unavailable')), source_updated_at TEXT NOT NULL);''',
 'documents': '''CREATE TABLE documents(document_id TEXT PRIMARY KEY, household_ref TEXT NOT NULL, person_id TEXT NOT NULL, certificate_id TEXT NOT NULL, document_type TEXT NOT NULL, issuer_name TEXT NOT NULL, holder_name TEXT NOT NULL, issued_on TEXT NOT NULL, expiry_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('A','E','R','S')), signature_status TEXT NOT NULL CHECK(signature_status='unsigned_simulation'), source_updated_at TEXT NOT NULL);''',
 'schemes': '''CREATE TABLE schemes(scheme_id TEXT PRIMARY KEY, name TEXT NOT NULL, rule_version TEXT NOT NULL, audience TEXT NOT NULL CHECK(audience IN ('household','farmer','student')), monthly_income_ceiling_inr INTEGER NOT NULL CHECK(monthly_income_ceiling_inr>=0), benefit_minor INTEGER NOT NULL CHECK(benefit_minor>0), currency TEXT NOT NULL CHECK(currency='INR'), required_sources TEXT NOT NULL);
 CREATE TABLE sanctions(sanction_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, household_ref TEXT NOT NULL, scheme_id TEXT NOT NULL REFERENCES schemes(scheme_id), cycle TEXT NOT NULL, amount_minor INTEGER NOT NULL CHECK(amount_minor>0), status TEXT NOT NULL CHECK(status='sanctioned'), UNIQUE(household_ref,scheme_id,cycle));''',
 'treasury': '''CREATE TABLE budgets(scheme_id TEXT PRIMARY KEY, available_minor INTEGER NOT NULL CHECK(available_minor>=0), currency TEXT NOT NULL CHECK(currency='INR'));
 CREATE TABLE reservations(reservation_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, scheme_id TEXT NOT NULL REFERENCES budgets(scheme_id), amount_minor INTEGER NOT NULL CHECK(amount_minor>0), status TEXT NOT NULL CHECK(status IN ('reserved','spent','released')));''',
 'bank': '''CREATE TABLE accounts(account_token TEXT PRIMARY KEY, household_ref TEXT UNIQUE NOT NULL, holder_person_id TEXT NOT NULL, validation_status TEXT NOT NULL CHECK(validation_status IN ('valid','invalid')), routing_code TEXT NOT NULL CHECK(routing_code='SIMULATED'), source_updated_at TEXT NOT NULL);
 CREATE TABLE instructions(instruction_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, account_token TEXT NOT NULL REFERENCES accounts(account_token), sanction_id TEXT UNIQUE NOT NULL, amount_minor INTEGER NOT NULL CHECK(amount_minor>0), status TEXT NOT NULL CHECK(status IN ('accepted','settled','failed','reversed')));
 CREATE TABLE settlements(settlement_id TEXT PRIMARY KEY, instruction_id TEXT UNIQUE NOT NULL REFERENCES instructions(instruction_id), amount_minor INTEGER NOT NULL CHECK(amount_minor>=0), status TEXT NOT NULL CHECK(status IN ('settled','failed','reversed')), received_at TEXT NOT NULL);''',
 'notifications': '''CREATE TABLE deliveries(message_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, household_ref TEXT NOT NULL, template TEXT NOT NULL, status TEXT NOT NULL CHECK(status='simulated_delivered'), at TEXT NOT NULL);
 CREATE TABLE grievances(case_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, household_ref TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','resolved')), at TEXT NOT NULL);''',
}
ORCHESTRATOR_DDL = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crosswalk(household_ref TEXT PRIMARY KEY, family_id TEXT UNIQUE NOT NULL, snapshot TEXT NOT NULL, source_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, household_ref TEXT NOT NULL REFERENCES crosswalk(household_ref), scheme_id TEXT NOT NULL, scenario TEXT NOT NULL, cycle TEXT NOT NULL, state TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, snapshot TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, exception TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, request_json TEXT NOT NULL, response_json TEXT NOT NULL, source_table TEXT, fetched_at TEXT NOT NULL, actor TEXT NOT NULL, contract_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(run_id,source));
CREATE TABLE IF NOT EXISTS mirror_households(run_id TEXT PRIMARY KEY REFERENCES runs(id), household_ref TEXT NOT NULL, data TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eligibility(run_id TEXT PRIMARY KEY REFERENCES runs(id), rule_version TEXT NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)), checks TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS callback_inbox(event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_changes(id INTEGER PRIMARY KEY, source TEXT NOT NULL, household_ref TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id,id);
CREATE INDEX IF NOT EXISTS runs_household ON runs(household_ref,created_at);
'''
STAGES = ['Registration captured','Fetch departmental evidence','Review evidence','Synchronize simulation registry','Evaluate scheme rules','Approve and enrol','Validate payment destination','Reserve treasury funding','Submit payment instruction','Receive bank callback','Reconcile payment','Notify household']
SCENARIOS = {
 'normal':'Use actual synthetic source records', 'source_outage':'Kutumba temporarily unavailable',
 'no_match':'Family reference not found', 'identity_mismatch':'Identity details disagree',
 'certificate_expired':'Income certificate expired', 'deceased':'Head marked deceased',
 'invalid_account':'Payment destination invalid', 'insufficient_funds':'Insufficient treasury balance',
 'payment_failed':'Bank transfer failed', 'delayed_settlement':'Bank settlement delayed',
 'reconciliation_mismatch':'Settlement amount mismatch', 'reversal':'Settlement subsequently reversed',
}
XML_MAPPINGS = {'document_id':'Certificate/@number','document_type':'Certificate/@type','issued_on':'Certificate/@issueDate (ISO date stored locally; DD-MM-YYYY on XML output)','expiry_date':'Certificate/@expiryDate','status':'Certificate/@status','issuer_name':'Certificate/IssuedBy/Organization/@name','holder_name':'Certificate/IssuedTo/Person/@name'}

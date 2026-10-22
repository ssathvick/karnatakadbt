from pathlib import Path
source=Path(__file__).with_name('build_training_guide.py').read_text(encoding='utf-8')
exec(source[:source.index("flow('journey'")])
exec(source[source.index('doc=Document()'):source.index("pic(PROJECT/'platform/assets/sathvick-black.png'")])
doc.core_properties.title='KarnatakaDBT external data requirements'
doc.core_properties.subject='Department data requests and integration prerequisites'
styles['Normal'].font.size=Pt(10.5)
styles['Normal'].paragraph_format.space_after=Pt(5)
styles['Normal'].paragraph_format.line_spacing=1.02
styles['Title'].font.size=Pt(26)
styles['Heading 1'].font.size=Pt(20)
footer.runs[0].text='KarnatakaDBT  |  Data requirements  |  '
flow('data-request-flow',[('Departments','Authoritative records'),('Approved API','Minimum permitted fields'),('KarnatakaDBT','Evidence and review'),('Outcome','Eligibility and payment status')], 'Proposed data exchange. Production government connections are not yet enabled.')
pic(PROJECT/'platform/assets/sathvick-black.png',.65)
doc.add_paragraph('KarnatakaDBT external\ndata requirements',style='Title')
p('Department coordination brief  |  Built by Sathvick  |  16 October 2026')
p('Use this brief to request access to the minimum data needed for a KarnatakaDBT pilot. Start with household verification and one scheme. The fields below are proposed requirements, subject to the scheme rules and the data owner’s approval; they are not a confirmed API schema.')
pic('data-request-flow',6.3)
h('Core data to request',2)
table(['System and owner to approach','Minimum data requested','Use in KarnatakaDBT'],[
('Kutumba\nCentre for e Governance', 'Family and member references; names; relationships; date of birth or age; address and location codes; permitted verified attributes and source timestamps', 'Match households and members; prefill records; compare eligibility evidence'),
('AHARA\nFood Civil Supplies and Consumer Affairs', 'Ration card reference and category; active status; linked members; location; last update', 'Check food security category and household membership where scheme rules require it'),
('Nadakacheri AJSK\nRevenue Department', 'Certificate reference and type; income or category result where required; issue and validity dates; verification status', 'Validate income, residence or caste certificates only for applicable scheme conditions'),
('Scheme department\nProgramme owner', 'Scheme code; rule version; eligibility thresholds; sanctioned beneficiary reference; benefit amount; approval and existing benefit status', 'Configure the programme and prevent duplicate benefits within approved scope'),
],[1.65,3.35,2.1])
p('Prefer a permitted verification result over a full record when that is sufficient. Request Kutumba first and add direct departmental checks only for fields or freshness it cannot supply.',boldlead='Prefer a permitted verification result')
page('Additional data by scheme')
p('Connect these sources only when the selected scheme needs them. Confirm the responsible business owner and technical custodian during onboarding.')
table(['System and owner to approach','Minimum data requested','Use in KarnatakaDBT'],[
('FRUITS\nAgriculture and allied departments','Farmer reference; registration status; scheme relevant crop, season or land linkage; update date','Farmer eligibility and permitted benefit overlap checks'),
('Bhoomi\nRevenue Department','Land record reference; survey and village codes; extent; ownership or mutation status; effective date','Land based eligibility when explicitly required'),
('eJanMa\nBirth and death registration authorities','Birth or death event verification; registration reference; event date; matched person reference','Verify age or life event; route discrepancies for review'),
('SSP and education systems\nScholarship and education departments','Student reference; enrolment and institution; academic year; course; scholarship sanction and payment status','Student eligibility and scholarship overlap checks'),
('Seva Sindhu\nService owning department and platform team','Application reference; service code; stage; decision; correction request; timestamp','Link service applications and avoid repeated submission'),
('Official state DBT and authorised treasury or bank route\nCeG DBT team and Finance or Treasury','Beneficiary and scheme references; permitted financial address validation result; instruction reference; amount; settlement status; failure reason; reconciliation reference','Validate payment readiness and reconcile outcomes through the approved route'),
('LGD and state location masters\nPanchayati Raj and relevant state custodians','District, subdistrict, village and urban body codes; names; effective dates and change history','Maintain consistent geography and code crosswalks'),
],[1.65,3.35,2.1])
h('Identity and document verification',2)
p('DigiLocker or API Setu can provide an approved route to participating issuers’ documents. Aadhaar authentication requires the applicable authorised UIDAI ecosystem route. Do not request biometrics or assume unrestricted Aadhaar, bank or government database access.')
p('Latitude and longitude: collect from the beneficiary or authorised field staff with source and verification status. A household address or district code does not establish an exact GPS location.')
page('What to request from each server team')
p('Request an approved service interface rather than direct database credentials. The source owner must supply actual server addresses and network requirements; public websites are not production API endpoints.')
flow('onboarding-flow',[('Agree scope','Owner, scheme and permitted fields'),('Test access','Sandbox and sample responses'),('Validate','Matching, failures and corrections'),('Go live','Sign off and monitor')], 'Keep live connectors separate from the synthetic demonstration environment.')
pic('onboarding-flow',6.3)
table(['Request package','Details to obtain'],[
('Business approval','Sponsoring department; permitted purpose and fields; data sharing approval; retention and correction responsibilities'),
('Server and security','Separate test and production API base URLs; API owner; VPN or IP allowlist requirements; authentication method; certificates and credential rotation'),
('API contract','Request and response schema; identifier rules; code masters; timestamps; version; error codes; rate limits and approved refresh schedule'),
('Operations','Sandbox credentials delivered securely; synthetic test cases; timeout and retry policy; duplicate prevention keys; outage contact and service expectations'),
('Evidence and payment audit','Source and record reference; fetched and effective times; match result; evidence status; decision reference; payment reconciliation and failure handling'),
],[1.65,5.45])
p('Do not equate an unavailable source with ineligibility. Keep unavailable, no match, mismatch and verified results distinct, and provide an authorised correction or review route.')
h('Recommended first request',2)
p('Ask the sponsoring scheme department and CeG Kutumba team for a sandbox household verification interface, permitted member attributes and the current contract. Add one certificate verification source. Keep payments simulated until financial onboarding and reconciliation tests are approved.')
h('Official reference links',2)
for title,url in [
('Kutumba scope and CeG implementing agency','https://negd.gov.in/isl/Directory/statedata/403'),
('NIC Karnataka systems overview','https://www.nic.gov.in/state-content/karnataka/'),
('NIC FRUITS overview','https://www.nic.gov.in/project/fruits/'),
('Karnataka food security sources','https://nfsa.gov.in/State/KA'),
('Local Government Directory','https://lgdirectory.gov.in/'),
('DigiLocker integration route','https://apisetu.gov.in/digilocker')]:
 link(title,url)
 doc.paragraphs[-1].paragraph_format.space_after=Pt(1)
 for el in doc.paragraphs[-1]._p.iter(qn('w:rPr')):
  sz=OxmlElement('w:sz');sz.set(qn('w:val'),'18');el.append(sz)
for el in list(doc.element.iter(qn('w:pBdr')))+list(doc.styles.element.iter(qn('w:pBdr'))):el.getparent().remove(el)
for t in doc.tables:
 pr=t._tbl.tblPr;b=OxmlElement('w:tblBorders')
 for edge in ['top','left','bottom','right','insideH','insideV']:
  e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');b.append(e)
 pr.append(b)
out=ROOT/'KarnatakaDBT_External_Data_Requirements.docx';doc.save(out);print(out)

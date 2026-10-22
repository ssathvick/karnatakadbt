# Local deployment verification

Validated on **22 October 2026**. This report covers the fresh local deployment, not the live production migration or historical rollback evidence.

The application image, Next.js export, generic Java helpers and pinned community MinIO source have built successfully on Linux amd64 through Docker Engine in WSL 2. A separate Git clone with newly generated secrets and empty project volumes was installed using `python3 manage.py up --no-browser`. Windows Chromium was used for real browser tests. Windows configuration generation and ACL creation were exercised; a separate Docker Desktop installation on a clean Windows machine was not tested. Native macOS/Apple Silicon execution has not been tested on physical Mac hardware.

| Check | Result |
|---|---|
| Clean source checkout and container build | Passed |
| Fifteen application database schema files included; fresh database initialisation | Passed |
| Native HTTP processes | 28 health checks passed |
| Registry worker | RUNNING; native installation ownership admitted; 18 task handlers assembled |
| Bank and bridge worker loops; consent expiry loop | RUNNING |
| Staff and beneficiary browser sign-in | OIDC/PKCE callback and authenticated portal session passed |
| Household registration | Synthetic household submitted and saved |
| Independent review | Different staff subject approved the household |
| Registry synchronisation | Native registry projection completed |
| Programme lifecycle | Creation, beneficiary application, eligibility and enrolment passed |
| Access denial | Beneficiary denied privileged audit API access |
| Native consoles | IAM browser SSO plus authenticated IAM, Registry, Master Data, Partner, Consent and Staff sessions passed |
| Approval console | Browser SSO and policy-list page loaded through local routes |
| Complete stack stop/start | Programme records, portal session and all six native console sessions retained |
| Python source compilation | Passed |
| Secret scans | Gitleaks scanned publication history with no leaks; known deployment-secret comparison found no credential matches after reviewing a schema display-label false positive |

The visible sample household/programme used by acceptance tests is fictional. Private production records, accounts, signing keys, credentials and disk backups are excluded from the repository. Each clone creates fresh secrets.

See [TESTING.md](TESTING.md) and `tests/acceptance_local.py` to repeat the browser acceptance path. `docs/github-actions-example.yml` is an optional CI example, not an enabled workflow.

Never treat a successful health endpoint as full workflow or security acceptance. The checks above do not establish parity for every historical API/console operation, external credential/wallet/provider combination or cryptographic suite. Advanced providers and new programme integrations need their own configuration and acceptance. Real Aadhaar, treasury/bank and paid AI integrations are not part of this local profile.

This test establishes persistence across stop/start, not restoration from an independently captured backup, nationwide capacity, high availability or full production cutover/rollback. The local profile uses one machine and fresh local admission; it does not manufacture production migration/acceptance receipts.

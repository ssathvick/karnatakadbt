# Repeating local acceptance

Start the local application and run `python manage.py check`. This checks 28 HTTP processes and the registry worker's ownership/state heartbeat. The browser test below creates **fictional** household, programme, application and approval/enrolment records in this local installation. It never targets a remote hostname or transfers money.

Install the optional browser-test dependency using a separate virtual environment:

```bash
python -m venv .test-venv
# Windows: .test-venv\Scripts\activate
# Linux/macOS: . .test-venv/bin/activate
python -m pip install playwright
python -m playwright install chromium
python tests/acceptance_local.py
```

Use `py -3` or `python3` as needed when creating the environment. On Linux, Playwright may request browser system dependencies; follow its installation output. `KDBT_TEST_BROWSER_PATH` can point to an already installed compatible Chromium executable.

The script reads this machine's ignored `.local/credentials.json`; it does not contain passwords in source. It exercises actual browser OIDC sign-in, household submission, independent review and registry projection, programme creation, application, eligibility, enrolment, an access-denial check and native console sessions. It leaves synthetic records for inspection. Run it on a fresh evaluation installation.

Health checks and this acceptance path do not cover every API operation, external provider, cryptographic suite, concurrent workload, production migration or disaster-recovery scenario. See VERIFICATION.md for the recorded release results.


Implemented the login separation.

- /login/ accepts vendor phone number and password/PIN, then redirects to the dashboard.
- /admin/ retains Django’s built-in username/password login, staff checks and permissions.
- /accounts/login/ redirects to /login/.

The public form enforces vendor status server-side. Administrator credentials and submitted privilege flags cannot grant administrative access.

Modified forms.py (accounts/forms.py), views.py (accounts/views.py), account URLs (accounts/urls.py), project URLs (config/urls.py), login template (templates/accounts/login.html), authentication tests (accounts/tests/test_authentication.py) and README (README.md).

Verification: 76 tests passed, including Phase 1, registration and OTP coverage. Django checks, migration consistency and browser checks passed. No schema changes or migrations were created.

Outstanding issues: none. The temporary verification server is stopped.

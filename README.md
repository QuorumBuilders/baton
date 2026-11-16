# Baton

Baton is a health-tech platform built as a single Django monolith. It provides a
public landing page, verified vendor registration, session authentication and
Django administration. The frontend uses Django Templates, HTML and CSS;
registration, login and logout work without JavaScript. The vendor dashboard is
a placeholder for future functionality.

## Prerequisites

- Python 3.13 or later. The project selects Python 3.13 via `.python-version`.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency
  management and command execution.

The direct application dependencies are Django 5.2 LTS, `python-dotenv` for
environment configuration and `phonenumberslite` for phone validation. The lite
phone package supplies maintained numbering metadata without geocoding, carrier
or timezone data; validation of real Nigerian numbering ranges is more reliable
than checking length and formatting alone. `uv.lock` records the resolved
versions, including Django's required dependencies and Windows timezone data.

If uv was installed through pip and its executable is not on your PATH, use
`python -m uv` in place of `uv` in the commands below.

## Setup

Run commands from the repository root. Install the locked dependencies; uv
creates `.venv` automatically, so activation is unnecessary:

```sh
uv sync --locked
```

Copy `.env.example` to `.env`. In PowerShell:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux:

```sh
cp .env.example .env
```

Generate a secret key, then paste the result into `DJANGO_SECRET_KEY` in `.env`:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Keep `.env` private. It and the local SQLite database are ignored by Git.
`.env.example` contains no secret key, and Django refuses to start without one.

| Variable | Purpose | Default when unset |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Unique random Django secret key | Required; no fallback |
| `DJANGO_DEBUG` | Enable local debug pages and development static serving | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames, without schemes or ports | Empty list |

The example enables local debugging and allows `localhost`, `127.0.0.1` and
`[::1]`. `DJANGO_DEBUG` accepts true/false, 1/0, yes/no or on/off, regardless of
case. Existing process environment variables take precedence over `.env`.
Django settings load the repository-root `.env` automatically with `python-dotenv`,
regardless of the current working directory. The `--env-file .env` uv option is
optional. A `.env` file is unnecessary when the required configuration is
supplied through process environment variables.

SQLite stores development data in `db.sqlite3`. The interface language is
English and the timezone is `Africa/Lagos`, with timezone-aware datetimes.
Django's standard authentication, CSRF protection, security middleware and
password validators are enabled. Session and CSRF cookies require HTTPS when
debugging is disabled.

Apply the initial Django migrations:

```sh
uv run python manage.py migrate
```

Create an administrator account interactively:

```sh
uv run python manage.py createsuperuser
```

Start the development server:

```sh
uv run python manage.py runserver
```

- Landing page: <http://127.0.0.1:8000/>
- Django admin: <http://127.0.0.1:8000/admin/>

The admin uses Django's permission system and requires an active administrator
with staff privileges. Account type alone never grants access. The account list
supports username/phone searches, business names, account-type and activation
filters, and vendor activation/deactivation.

## Accounts and authentication

`AUTH_USER_MODEL` is `accounts.User`, which extends `AbstractUser` and retains
Django's standard fields, password hashing, groups and permissions. An explicit
`account_type` distinguishes `administrator` and `vendor` accounts.

| Account | Login identifier | Required account fields | Administrative privileges |
| --- | --- | --- | --- |
| Administrator | Username | Non-empty username | Controlled by Django's staff/superuser flags and permissions |
| Vendor | Normalized phone number | Phone number and business name | Staff and superuser flags must both be false |

Vendor usernames default to the empty string; no substitute usernames or separate
vendor profiles are created. A conditional unique constraint covers non-empty
usernames, allowing multiple blank vendor usernames. Another conditional unique
constraint covers vendor phone numbers. Business names can repeat. Phone and
business fields are nullable for administrators.

Database check constraints enforce account-specific required fields, account
types, canonical phone storage and vendor privilege restrictions, including when
bulk writes bypass model validation. Normal saves also validate the model.

Django's `auth.W004` check does not recognize conditional username uniqueness,
so that specific warning is silenced. The database constraint and authentication
backend enforce unique administrator lookups; tests exercise these boundaries.

`accounts.backends.AccountBackend` supports administrator username/password and
vendor phone/password-or-PIN authentication. It inherits Django's permission and
session behavior, rejects inactive accounts, and never authenticates vendors by
business name or optional username. The public login page accepts only vendor
phone numbers and passwords/PINs, and verifies the account's vendor status
server-side. Administrators authenticate through Django's built-in admin login
page with username/password; its staff-status and permission checks remain in
control of administrative access.

- Vendor login: <http://127.0.0.1:8000/login/>
- Administrator entry point: <http://127.0.0.1:8000/admin/>
- Vendor registration: <http://127.0.0.1:8000/accounts/register/>
- Vendor placeholder: <http://127.0.0.1:8000/accounts/dashboard/>
- Logout confirmation: <http://127.0.0.1:8000/accounts/logout/>

Logout occurs only through a CSRF-protected POST. Protected vendor pages require
an active vendor account; administrators use `/admin/`. Successful vendor logins
always redirect to the vendor dashboard, including when a different `next` URL
is submitted. Existing administrator sessions visiting `/login/` return to the
named Django admin entry point. `/accounts/login/` redirects to `/login/` for
existing bookmarks. Registration, verification, logout and dashboard URLs remain
under `/accounts/`. Sessions and authenticated state use Django's normal
middleware and cookies, with no API tokens or JWTs.

Create an administrator with the `createsuperuser` command above. It sets the
administrator account type and Django's staff/superuser flags, and does not
require a phone number or business name. Ordinary administrator accounts still
need appropriate Django permissions to use administrative functionality.

## Phone normalization

The vendor phone number is the primary identity and login identifier. Nigerian
mobile and current fixed-line numbers are supported. Local `08012345678`,
international `+2348012345678`, `2348012345678` and `002348012345678` all normalize
to `+2348012345678`. Spaces, parentheses and hyphens are accepted. Stored numbers
use E.164, and uniqueness is checked after normalization.

Invalid numbers, unsupported service numbers, foreign numbers and alphabetic
representations are rejected. The same normalization function is used by forms,
the user model, verification services and authentication.

## Vendor registration and development OTPs

1. With `DJANGO_DEBUG=True`, start the development server and open registration.
2. Enter a Nigerian phone number and a pharmacy/chemist business name.
3. Read the six-digit OTP in the **development server console**, then submit it
   on the verification page. It is never included in HTTP responses.
4. Create and confirm a password or six-digit PIN. The verified account is
   activated immediately and logged in; administrator approval is unnecessary.

Vendor passwords use the configured Django validators, including the eight-character
minimum. Six-digit ASCII PINs are accepted except repeated digits, `123456` and
`654321`. Both use Django's password hashing and are entered in the same login
password/PIN field. Administrator passwords retain Django's standard validators.

OTP rules live in `accounts/services.py`, separately from views:

- Codes are generated with `secrets` and only Django password hashes are stored.
- Codes expire after five minutes and allow five failed verification attempts.
- Resends have a 60-second cooldown and invalidate earlier outstanding codes,
  including verified registrations that have not yet been completed.
- Verification is bound to the exact normalized phone number and is single-use.
- The verified registration grant also expires and can create an account once.
- The record and phone are bound to the browser's registration session. A session
  flag alone cannot bypass the database verification check.
- Registration and credential errors avoid disclosing whether an account exists.

`PhoneVerification.consumed_at` records successful OTP verification;
`completed_at` records account creation and `invalidated_at` records replacement.
OTP records and hashes are not registered in Django admin. Verification and
credential pages are not cached, and submitted OTP/password values are not
redisplayed on validation errors.

| Setting | Default | Purpose |
| --- | --- | --- |
| `OTP_TTL_SECONDS` | `300` | Code and registration-grant lifetime |
| `OTP_MAX_ATTEMPTS` | `5` | Maximum failed code attempts |
| `OTP_RESEND_COOLDOWN_SECONDS` | `60` | Minimum interval between sends |
| `OTP_DELIVERY_BACKEND` | Console backend only when debug is enabled | Replaceable delivery class with `send(phone_number, code)` |

The timing/attempt settings can be set in `.env` and must be positive integers.
The console backend prints codes only when `DEBUG=True`, and refuses delivery
when debugging is disabled even if explicitly configured. With `DEBUG=False`,
the default delivery setting is empty and registration reports that verification
is unavailable. **Production SMS verification requires a future provider
integration.** No external SMS provider is integrated in this phase.

## Database transition from Phase 1

The existing Phase 1 development database used Django's default `auth.User`.
Switching to a custom user model changes the admin migration dependencies and
requires a consistent migration history. This checkout's database was confirmed
to contain no users, groups, sessions or admin activity, preserved in the ignored
`db.phase1-backup-e5334b34.sqlite3`, and initialized with `accounts.0001_initial`.
The project and existing Phase 1 code were extended in place.

Fresh installations apply all migrations normally with `manage.py migrate`.
Existing Phase 2 installations use that same command for future migrations.
A populated database still using `auth.User` needs a separate data-preserving
migration plan; do not delete or reset it.

## Tests and checks

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py findstatic core/css/site.css core/images/baton.svg
```

The complete suite covers Phase 1 behavior, environment loading, account creation,
database constraints, phone normalization/uniqueness, OTP expiration and reuse,
attempt and resend limits, registration binding, credential/session authentication,
CSRF protection, admin access and vendor privilege restrictions. Tests use a
separate Django test database and mocked OTP delivery, without external SMS.

## Static files

Project assets live in `static/`, and templates resolve them with Django's
`static` tag. `runserver` serves both project and admin assets at `/static/`
when `DJANGO_DEBUG=True`.

Collect project and admin assets when preparing a deployment:

```sh
uv run python manage.py collectstatic --noinput
```

Collected files go to the ignored `staticfiles/` directory. With debugging
disabled, configure the deployment's web server to serve that directory at
`/static/`. The development server is for local development; deployment setup
is outside Phase 1.

The landing page uses a small SVG copied from the supplied `SVG/coloured.svg`
and system fonts. Original assets in `SVG/` and `3x/` remain available.

## Project structure

```text
baton/
  .agents/skills/ui/SKILL.md  UI implementation guidance and completion checklist
  .env.example              Environment configuration template
  .gitignore
  .python-version
  AGENTS.md                 Persistent coding-agent instructions
  README.md
  pyproject.toml             Python compatibility and dependencies
  uv.lock                    Reproducible dependency resolution
  manage.py
  config/                    Django settings, URLs, WSGI and ASGI entry points
  accounts/                  Custom user, authentication, OTP services, forms and tests
    migrations/
  core/                      Landing-page view, URLs, app configuration and tests
    migrations/
  templates/
    base.html                Shared page layout
    core/landing.html
    accounts/                Registration, verification, credentials, login/logout and placeholder
  static/core/
    css/site.css
    images/baton.svg
  SVG/                       Supplied SVG logo originals
  3x/                        Supplied raster logo originals
```

Read `AGENTS.md` before changing the project and follow
`.agents/skills/ui/SKILL.md` for UI work. Facility management, patient records,
blood pressure monitoring, follow-ups, reminders, voice calls and external SMS
integrations are outside Phase 2.

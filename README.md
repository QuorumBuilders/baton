# Baton

Baton is a health-tech platform built as a single Django monolith. It provides a
public landing page, verified vendor registration, session authentication and
Django administration, plus vendor-facing patient registration, blood pressure
history, centralized follow-up coordination and simulated communication delivery.
The frontend uses Django Templates, HTML and CSS; all core workflows work without
JavaScript. **The prototype does not send real SMS messages or place real voice
calls.** No external provider credentials are required for local development.

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
| `SMS_DELIVERY_BACKEND` | Dotted Python class implementing the SMS adapter | Console adapter when debug is enabled; otherwise empty |
| `VOICE_DELIVERY_BACKEND` | Dotted Python class implementing the voice adapter | Mock adapter when debug is enabled; otherwise empty |

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

Apply the Django migrations:

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
- Vendor dashboard: <http://127.0.0.1:8000/accounts/dashboard/>
- Patient list: <http://127.0.0.1:8000/patients/>

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
- Vendor dashboard: <http://127.0.0.1:8000/accounts/dashboard/>
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

The vendor phone number is the primary identity and login identifier. New vendor
and patient registrations require a valid Nigerian mobile number. Existing
vendor accounts with a valid Nigerian fixed-line number remain able to log in.
Local `08012345678`, international `+2348012345678`, `2348012345678` and
`002348012345678` all normalize to `+2348012345678`. Spaces, parentheses and
hyphens are accepted. Stored numbers use E.164, uniqueness is checked after
normalization, and vendor-facing pages display Nigerian local format.

Invalid numbers, unsupported service numbers, foreign numbers and alphabetic
representations are rejected. The same normalization function is used by forms,
the user model, verification services and authentication.

## Vendor registration and development OTPs

1. With `DJANGO_DEBUG=True`, start the development server and open registration.
2. Enter a Nigerian mobile number and a pharmacy/chemist business name.
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
- The vendor registration grant expires with the original OTP deadline and can
  create an account once. A verified patient registration has a separate 30-minute
  window starting at successful OTP verification.
- The record and phone are bound to the browser's registration session. A session
  flag alone cannot bypass the database verification check.
- Registration and credential errors avoid disclosing whether an account exists.

Vendor and patient OTP records are separated by purpose, so one flow cannot use
the other flow's verification grant. `PhoneVerification.consumed_at` records
successful OTP verification;
`completed_at` records account creation and `invalidated_at` records replacement.
OTP records and hashes are not registered in Django admin. Verification and
credential pages are not cached, and submitted OTP/password values are not
redisplayed on validation errors.

| Setting | Default | Purpose |
| --- | --- | --- |
| `OTP_TTL_SECONDS` | `300` | OTP lifetime from issuance; also the vendor registration deadline |
| `PATIENT_REGISTRATION_TTL_SECONDS` | `1800` | Patient registration lifetime from successful OTP verification |
| `OTP_MAX_ATTEMPTS` | `5` | Maximum failed code attempts |
| `OTP_RESEND_COOLDOWN_SECONDS` | `60` | Minimum interval between sends |
| `SMS_DELIVERY_BACKEND` | `communications.adapters.ConsoleSMSAdapter` when debug is enabled | Shared SMS transport with `send(SMSMessage)` |

The timing/attempt settings can be set in `.env` and must be positive integers.
The SMS console adapter prints the recipient, complete message body (including
the generated OTP), purpose, UTC timestamp and verification reference to the
Django terminal. Every SMS submitted to this adapter is printed, including
non-OTP messages. Output is explicitly labelled simulated; it is never a claim
of delivery to a phone. Protect development terminal output and use synthetic
data for demonstrations.

The adapter requires `DEBUG=True` at construction and on every send. With
`DEBUG=False`, the default delivery setting is empty and registration reports
that verification is unavailable. Explicitly selecting a development adapter
cannot bypass the guard. A transport exception invalidates that OTP grant and
returns an unavailable error without exposing the provider payload or OTP through
an HTTP error page. **Production SMS verification requires a future provider
integration.** Baton continues to generate, hash, expire and verify its own OTPs.

For old local configuration, `OTP_DELIVERY_BACKEND` remains a fallback when
`SMS_DELIVERY_BACKEND` is unset. The old `accounts.delivery.ConsoleOTPBackend`
path is mapped to the new SMS console adapter. New configuration and provider
adapters should use `SMS_DELIVERY_BACKEND` and the message interface above.

## Patient management

Each patient has one global UUID-based record, matched by their normalized mobile
number. A record includes the required name, date of birth and preferred language,
optional sex and alternative contact number, and explicit SMS and voice consent
with audit timestamps. Patients do not receive application accounts.
New registrations select English or Nigerian Pidgin for voice reminders.
Historical language values are preserved; supported English/Pidgin aliases are
recognized, while an unsupported language produces an inspectable failed attempt
without silently choosing another language.

Vendors see only patients associated with their account. Registering a new patient
requires patient-phone OTP verification and automatically creates the first vendor
association. If the number already belongs to a Baton patient, no new record or OTP
is created. The vendor must confirm that the patient agreed to the association and
sharing of relevant Baton history; Baton records the confirming vendor and time.
All associated vendors can then see the patient's complete Baton BP and follow-up
history, while each historical entry retains its original vendor attribution.

The patient's OTP must be verified within five minutes of generation. After that
successful verification, the vendor has 30 minutes to submit the patient details;
time spent waiting for the code does not consume this registration window. The
server derives the deadline from the stored verification timestamp and enforces
it again when claiming the grant during patient creation. Resubmitting the form
does not extend the deadline. An expired, replaced or already-completed grant
cannot create another patient, and an unverified code never receives the longer
window. OTP single-use checks, attempt limits and resend cooldowns still apply.

The main routes are:

- `/patients/` for the associated-patient list and name/phone search.
- `/patients/register/` for new-patient discovery, OTP registration or association.
- `/patients/<patient-id>/` for patient information, BP history and active follow-up.
- `/patients/<patient-id>/measurements/new/` for the BP review-and-confirm workflow.
- `/patients/<patient-id>/follow-ups/` for complete follow-up history.

Every patient route checks the authenticated vendor association server-side.
Unrelated vendors receive no patient record through direct URL access.

## BP measurements and follow-ups

A BP measurement stores systolic and diastolic pressure, optional pulse, the
recording vendor and an automatic timestamp. The vendor reviews the entered values
and sees an explicit immutability warning before saving. Saved measurements have no
ordinary edit or delete operation and remain part of the permanent patient history.

Saving a measurement fulfils the patient's previous active follow-up, even when a
different associated vendor records it or the scheduled date has not arrived. Baton
then previews the next automatic date. The initial approved rule is 21 days after
the new measurement; administrators can deactivate it and create a new versioned
interval in Django admin. Existing follow-ups retain their original scheduled date
and rule/version. A vendor can accept the proposed date or choose a manual date,
and only one active follow-up is allowed per patient.
An explicit manual choice remains manual even when its date matches the automatic
proposal. Draft measurements and follow-ups are saved only after confirmation.

Changing an active follow-up date creates a recorded manual schedule revision and
recalculates its outstanding reminders. Measurement confirmation uses an operation
identifier, transactions and database constraints so retries do not create duplicate
measurements or active follow-ups.

## Reminder coordination

Follow-ups and reminders are separate records. For a 21-day interval, Baton creates
medication/general-health reminder schedules at days 7 and 14, followed by visit
reminders on the follow-up date and at 2 and 4 days overdue. Shorter intervals use
one between-visit reminder; intervals of 21 days or longer use two distributed
through the interval. These schedules do not prescribe medication, specify doses,
interpret BP values or alter treatment instructions.

Each schedule records its patient, follow-up, category, event, channel, revision,
processing state and delivery state. A new measurement cancels all outstanding
reminders for the fulfilled follow-up. Repeated processing is idempotent. A manual
follow-up becoming overdue creates one dashboard notification for the vendor who
scheduled it; after the final overdue reminder, all associated vendors can see that
the patient requires attention.

Routine patient reminders use **voice only**, independently of SMS consent. Voice
schedules represent business events and are created even when consent is absent;
current voice consent is required before invoking an adapter. Missing consent
produces a skipped attempt with a reason. OTP SMS verification retains its separate
registration semantics and does not depend on reminder consent.

`patients.services.send_patient_sms()` is the consent boundary for any non-OTP
patient SMS added to an authorized business workflow. It reads the current patient
record, targets that patient's primary phone, and raises `PermissionDenied` without
invoking the adapter when SMS consent is absent. It is not used for routine reminders.

## Voice content and mock delivery

`communications/content.py` holds a reusable catalog of recording references and
prototype scripts. Each category has English (`recordings/en/`) and Nigerian
Pidgin (`recordings/pcm/`) references:

| Reminder event | Voice category | Recording filename in each language directory |
| --- | --- | --- |
| Follow-up date | Scheduled visit | `scheduled-visit-v1.mp3` |
| Two days overdue | First overdue | `first-overdue-v1.mp3` |
| Four days overdue | Final overdue | `final-overdue-v1.mp3` |
| First between-visit reminder | Medication | `medication-v1.mp3` |
| Second between-visit reminder | General health | `general-health-v1.mp3` |

A shorter interval has only the first between-visit reminder. The existing timing
rules are unchanged. Medication scripts refer patients to instructions already
given by their healthcare professional; the catalog does not diagnose, interpret
BP or specify medication or dosage.

**The references are placeholders; actual recordings are not included.** Register
real, reviewed recordings by updating the corresponding catalog entry's reference
and script. The resolver selects content from the reminder event and current patient
language; scheduling contains no provider-specific content. Delivery uses prerecorded
assets, with no text-to-speech.

`communications.adapters.MockVoiceAdapter.invoke(VoiceRequest)` prints the recipient,
category, selected language, recording reference, timestamp and idempotency reference
to the terminal, explicitly marked **MOCK / NOT A REAL CALL**. It performs no playback,
streaming or phone call and returns `simulated`. Like the SMS console adapter, it
rejects use when `DEBUG=False`, including after it has already been instantiated.

## Manual reminder processing and communication records

Log in to `/admin/` with an administrator, open **Reminder schedules**, select at
least one row and run **Process all due reminder schedules now (development delivery
is simulated)**. The selection makes Django's action available; the action processes
**all currently due active schedules**, retaining the existing global trigger.
Runserver shows mock invocations, and the admin summary reports processed, simulated,
delivered, skipped and failed counts plus vendor notifications and attention flags.
The defaults always report zero real deliveries. No background worker is required.

Inspect **Communication attempts** in admin for the reminder, channel, intended
recipient, category, selected recording/language, processing timestamps, adapter,
delivery mode, outcome and reason. History is read-only. Vendors can see the reminder
and communication outcomes in the patient's shared follow-up history. Administrative
summaries contain counts, without patient details.

Reminder processing state is separate from communication outcome:

| Communication outcome | Meaning |
| --- | --- |
| Processing | A durable attempt has been reserved; its outcome is not yet known |
| Simulated | Development adapter logged an invocation; nothing was delivered |
| Skipped | A consent or follow-up state check prevented invocation |
| Failed | Content, adapter configuration or transport failed |
| Delivered | Reserved for an adapter that explicitly confirms actual delivery |

`patients.services.process_due_reminders(at=None)` is also callable from Django
code or a future scheduler. It uses existing reminder dates/events, reserves one
communication attempt per reminder under a transaction and a database uniqueness
constraint, and rechecks current consent, fulfilment and schedule revision before
invocation. SQLite IMMEDIATE transactions serialize competing writers. A second
manual run does not repeat simulated, delivered, failed or skipped attempts.
Failures preserve reminders and selected recording details; provider exception
payloads are omitted from stored reasons.

This prototype deliberately makes at most one invocation per reminder. If the
process stops after reservation, the attempt can remain `Processing`; inspect it
before deciding how to reconcile it. It is not automatically retried because
delivery might have occurred before interruption. There is no automatic retry UI,
queue, delivery receipt handler or claim of exactly-once external delivery.

## Future provider integration

The ordinary Python `communications/` package adds no Django app or dependency:

1. Implement `SMSAdapter.send(SMSMessage)` or `VoiceAdapter.invoke(VoiceRequest)`
   from `communications/adapters.py`.
2. Return a `DeliveryResult` from `communications/payloads.py`, with adapter/mode
   information and a provider reference. Report `delivered` only after confirmed
   actual delivery; never use it merely for accepting a request.
3. Configure the class through `SMS_DELIVERY_BACKEND` or `VOICE_DELIVERY_BACKEND`,
   and supply credentials required by that implementation through environment variables.

The provider transports Baton's SMS payload or invokes the selected recording.
It does not generate/verify OTPs or choose reminder dates, content or consent.
No external provider, credentials, USSD or vendor SMS command is integrated here.
An asynchronous provider would also need explicit pending/receipt handling before
it could report confirmed delivery; this prototype has no such integration.

## Administration

Django admin provides patient and vendor-association management, read-only BP and
follow-up history, versioned follow-up rule configuration, schedule-change history,
reminder schedules, communication attempts and vendor notifications. Vendor accounts never receive staff
privileges through these workflows.

## Database transition from Phase 1

The existing Phase 1 development database used Django's default `auth.User`.
Switching to a custom user model changes the admin migration dependencies and
requires a consistent migration history. This checkout's database was confirmed
to contain no users, groups, sessions or admin activity, preserved in the ignored
`db.phase1-backup-e5334b34.sqlite3`, and initialized with `accounts.0001_initial`.
The project and existing Phase 1 code were extended in place.

Fresh installations apply all migrations normally with `manage.py migrate`.
Existing Phase 2 installations use that same command for future migrations.
Phase 3 installations also run `uv run python manage.py migrate`. The Phase 4
migrations add communication outcomes/attempts and prepare pending events for voice
processing. Historical SMS rows remain in place; pending SMS rows are cancelled,
outstanding active events receive voice rows as needed, and previously processed,
cancelled or fulfilled events are not replayed. Follow-up dates, measurements and
historical language values are preserved.
A populated database still using `auth.User` needs a separate data-preserving
migration plan; do not delete or reset it.

## Tests and checks

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py findstatic core/css/site.css core/images/baton.svg
uv run python manage.py collectstatic --noinput
```

The complete suite covers the earlier landing, configuration and authentication
behavior as well as patient registration and discovery, OTP purpose isolation,
association consent, access control, immutable measurements, centralized follow-up
fulfilment, rule versioning, manual scheduling, reminder timing and recalculation,
overdue visibility, cancellation and idempotency. Communication coverage includes
complete SMS output, hashed/non-disclosed OTPs, production guards, all bilingual
recording references, consent, failed/skipped/simulated outcomes, concurrent manual
processing, changes between reservation and invocation, and the Phase 3 data transition.
Tests use the separate file-backed `test.sqlite3`, which Django creates and destroys,
so concurrency exercises the same SQLite locking as local development. The application
database is not used for tests. Delivery is mocked or captured; no external calls occur.

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
`/static/`. The development server is for local development; deployment setup is
outside the current prototype scope.

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
  communications/            Provider-neutral SMS/voice payloads, adapters and content catalog
  patients/                  Patients, associations, BP, follow-ups and reminders
    migrations/
    tests/
  core/                      Landing-page view, URLs, app configuration and tests
    migrations/
  templates/
    base.html                Shared page layout
    core/landing.html
    accounts/                Registration, verification, credentials, login/logout and dashboard
    patients/                Patient, measurement and follow-up pages
  static/core/
    css/site.css
    images/baton.svg
  SVG/                       Supplied SVG logo originals
  3x/                        Supplied raster logo originals
```

Read `AGENTS.md` before changing the project and follow
`.agents/skills/ui/SKILL.md` for UI work. Facility ownership, branches, staff
accounts, clinical diagnosis or recommendations, real patient messaging and
background scheduling remain outside the current scope.

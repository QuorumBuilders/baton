# Privacy review before real patient onboarding

Reviewed against the current implementation and official Nigerian sources on
19 November 2026. This document records open decisions, not certification or legal
advice. Use synthetic data for demonstrations while these matters remain unresolved.

## Verified facts and missing identity information

The project operator supplied the contact `teamtensorcs@gmail.com` and the general
location Akure, Ondo, Nigeria. These are configurable through the `BATON_*`
environment settings documented in the README. The email does not establish a
registered entity name, and the town does not establish a physical address or
hosting location. Verify the operator legal/operating name, full physical address,
controller contact and who handles the mailbox before live onboarding. Public pages
leave unknown details visibly marked.

## Current data map

- Accounts: vendor phone/business name, hashed credentials, status, timestamps;
  administrator username, standard Django optional personal fields and permissions.
- Patients: names, primary mobile, date of birth, language, optional sex/alternative
  number; patient/vendor associations and recording actors.
- History: BP/optional pulse, original vendor and time, follow-ups, date revisions,
  reminders, fulfilment and vendor attention notifications.
- Agreement: new-registration processing agreement actor/time, independent current
  SMS/voice choices and append-only change history, additional-vendor sharing
  confirmations. Pre-migration history is only a labelled snapshot of known choices.
- Verification: phone/purpose, hashed code, issuance/expiry, attempt count and
  verification/replacement/completion times.
- Communications: recipient, reminder/category/language/recording reference, times,
  adapter/mode, outcomes and safe reasons. All default delivery is simulated.
- Infrastructure: local SQLite, server-side sessions with unfinished registration
  and measurement drafts, necessary session/CSRF/message cookies, Django admin
  logs and development terminal output. There is no analytics integration.
- Contact enquiries use an external email service. The application does not send
  emails. Establish the mailbox access, storage, retention and sensitive-exchange
  procedure rather than treating the contact link as an automatic rights workflow.

## Lawful basis and vendor relationships

The new-registration confirmation records affirmative patient agreement to health
record-keeping, follow-up coordination and access by the first vendor. The intended
consent bases are NDPA sections 25(1)(a), 26 and 30(1)(a); oral agreement recorded by
the vendor is distinct from showing information or verifying a phone. Additional
vendor association retains its separate consent and lets that vendor see the complete
Baton BP/follow-up history. SMS and voice are separate optional choices, including
an explicit no for each; the SMS choice does not create a routine SMS workflow.

Confirm that this basis is appropriate, that agreement can be freely given, that
explanation is understandable, and that the stored actor/time is sufficient evidence
for the live service. GAID articles 16–20 govern lawful basis and consent. Existing
records without documented processing agreement must be reviewed; migration does
not manufacture consent. A fixed prototype notice is used without a legal-document
versioning framework; material changes need review and any necessary renewed consent.

Vendor account registration uses an intended contract basis under section 25(1)(b)(i).
Complete a legitimate-interest assessment for security/access processing under
section 25(1)(b)(v) and GAID article 26. Review whether the healthcare confidentiality
condition under section 30(1)(g) applies to any live processing; do not assume every
chemist is a qualifying professional or rely on that alternative without evidence.

Define whether the operator and each vendor are controllers, joint controllers or
processors for each activity. Agree responsibilities for lawful collection, access
to shared history, confidentiality, accuracy, requests, withdrawals and breaches.
Technical association is not proof of professional authorization. Phone OTP verifies
control of a number, not a vendor's licence or a patient's full identity.

## DPIA, registration and governance

NDPA section 28 requires a DPIA before processing likely to create high risk. GAID
article 28(3)(d) expressly includes sensitive or highly personal data among mandatory
DPIA circumstances and requires filing with the NDPC. Shared patient health histories
put Baton within the circumstances that must be planned for; commission a DPIA and
confirm filing and any consultation under section 28(2) before live use. Do not defer
this merely because patient volumes are initially small.

Assess controller/processor registration under NDPA sections 44 and 65, GAID articles
8–9 and Schedule 7, and the NDPC updated registration guidance. Classification
depends on nature, sector, sensitivity, scale and other criteria, not solely one
patient-count threshold. Health processing may matter independently of scale.
Confirm designation, registration/renewal, DPO duties (section 32), compliance audit
returns and applicable current regulatory guidance. No registration status is claimed.

The application accepts birth dates but has no guardian/age-capacity consent process.
Review children and persons lacking capacity under section 31 and applicable GAID
requirements before onboarding such patients. Do not interpret a vendor checkbox as
evidence of valid guardian authority.

## Rights, retention and operational procedures

Implement and assign a proportionate identity check and accountable handling for
access/copies, correction, deletion, restriction, portability, objection and withdrawal
under NDPA sections 34–38 and GAID rights guidance. Give statutory time-bound duties
legal review; public notices do not invent a support SLA. GAID article 21(2) also
addresses data from preliminary contracts that do not materialise: account/OTP
retention needs explicit legal assessment, not merely code expiry.

Communication withdrawal is implemented and blocks future selected-channel invocations
once recorded. Processing/sharing withdrawal and restrictions still need an operational
procedure and any necessary technical access control. Explain and record decisions;
preserving history is not a blanket reason to refuse erasure. The operator must not
continue consent-based processing after withdrawal without another applicable basis.

Set justified retention periods for each data category, expired verification and
sessions, logs, consent evidence, historical records and backups. Implement cleanup
and reviewed legal holds as needed. No automated patient cleanup or verified backup
procedure exists. Changing current SMS/voice booleans preserves earlier records;
saved BP measurements and follow-up revisions must not be silently overwritten.
Plan an auditable correction/restriction/deletion process without casual removal of
original attribution or medical history.

Ensure individuals can complain to the NDPC under section 46 without first exhausting
an internal process. Contacting the project does not waive statutory remedies.

## Hosting, providers and security

Verify hosting/provider names, processing locations, email handling, transfers and
agreements before publishing those details as facts. Akure describes the operator
location only. Review processor duties under section 29 and cross-border safeguards
under sections 41–43. No real SMS/voice provider is currently integrated.

Review HTTPS/deployment configuration, credentials and PIN risks, access privileges,
database/device/backup protection, audit and operational logging, vulnerability
handling, OTP abuse/rate limiting and incident response under sections 39–40.
Development SMS logs full phone/message/OTP content, and mock voice logs numbers
and recording details; these adapters reject production use but demo output still
requires protection. Do not use real patient data in demo logs or fixtures.
Add reviewed provider agreements, content/recordings, shared-phone safeguards and
delivery receipts before real communications. Keep OTP transactional and routine
SMS/voice consent independent. Do not label provider acceptance as actual delivery.

## Primary sources

- [Nigeria Data Protection Act 2023](https://ndpc.gov.ng/wp-content/uploads/2024/03/Nigeria_Data_Protection_Act_2023.pdf):
  sections 24–31 (principles, lawful basis, transparency, DPIA, processors and sensitive
  data), 32 (DPO), 34–43 (rights, security and transfers), 44/65 (registration) and
  46 (complaints).
- [NDPC General Application and Implementation Directive 2025](https://ndpc.gov.ng/wp-content/uploads/2025/07/NDP-ACT-GAID-2025-MARCH-20TH.pdf):
  articles 8–9, 15–28 and relevant rights guidance and schedules.
- [NDPC updated registration guidance](https://ndpc.gov.ng/wp-content/uploads/2025/07/Updated-Guidance-Notice-on-Registtration-2024.pdf),
  dated 19 December 2024 and incorporated in GAID Schedule 7.
- [NDPC official contact and complaint information](https://ndpc.gov.ng/contact/).

These references were fetched from the NDPC website and reviewed during implementation.
Check for subsequent legal/guidance changes before deployment. Implementing pages,
agreement evidence and withdrawal controls alone does not establish full compliance.

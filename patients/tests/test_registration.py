from datetime import date, timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import PhoneVerification
from accounts.services import VerificationError, get_verified_registration, issue_otp, verify_otp
from patients.models import CommunicationConsentRecord, Patient, VendorPatient
from patients.services import complete_patient_registration
from patients.views import REGISTRATION_KEY

from .helpers import make_patient, make_vendor


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    OTP_TTL_SECONDS=300,
    PATIENT_REGISTRATION_TTL_SECONDS=1800,
)
class PatientRegistrationTests(TestCase):
    code = "583029"

    def setUp(self):
        self.vendor = make_vendor()
        self.client.force_login(self.vendor)
        self.delivery = Mock()
        for mock in (
            patch("accounts.services.get_delivery_backend", return_value=self.delivery),
            patch("accounts.services.secrets.randbelow", return_value=int(self.code)),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def start(self, phone="08050675448"):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("patients:register"), {"phone_number": phone}
            )
        self.assertRedirects(response, reverse("patients:verify"))
        return PhoneVerification.objects.get(
            pk=self.client.session[REGISTRATION_KEY]["verification_id"]
        )

    def verify(self):
        response = self.client.post(reverse("patients:verify"), {"code": self.code})
        self.assertRedirects(response, reverse("patients:register_details"))

    def details(self, **overrides):
        data = {
            "processing_agreed": "on",
            "first_name": " Ada ",
            "last_name": " Okafor ",
            "date_of_birth": "1980-05-12",
            "sex": "Female",
            "preferred_language": "English",
            "sms_consent": "yes",
            "voice_consent": "no",
            "alternative_contact_number": "08031234567",
        }
        data.update(overrides)
        return self.client.post(reverse("patients:register_details"), data)

    def test_successful_registration_requires_otp_and_records_consent(self):
        verification = self.start()
        self.assertEqual(verification.purpose, "patient")
        self.verify()
        response = self.details()
        patient = Patient.objects.get()
        self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
        self.assertEqual(patient.phone_number, "+2348050675448")
        self.assertEqual(patient.local_phone, "08050675448")
        self.assertEqual(patient.alternative_contact_number, "+2348031234567")
        self.assertEqual((patient.first_name, patient.last_name), ("Ada", "Okafor"))
        self.assertTrue(patient.sms_consent)
        self.assertFalse(patient.voice_consent)
        self.assertIsNotNone(patient.sms_consent_recorded_at)
        self.assertIsNotNone(patient.voice_consent_recorded_at)
        self.assertIsNotNone(patient.processing_agreed_at)
        self.assertEqual(patient.processing_agreement_recorded_by, self.vendor)
        records = patient.communication_consent_history.all()
        self.assertEqual(records.count(), 2)
        self.assertEqual(set(records.values_list("channel", "agreed")), {("sms", True), ("voice", False)})
        self.assertTrue(all(record.recorded_by == self.vendor and record.source == "registration" for record in records))
        self.assertTrue(patient.vendors.filter(pk=self.vendor.pk).exists())
        verification.refresh_from_db()
        self.assertIsNotNone(verification.completed_at)

    def test_processing_agreement_is_required_without_claiming_the_verified_grant(self):
        verification = self.start()
        self.verify()
        for value in ("", False):
            response = self.details(processing_agreed=value)
            self.assertIn("processing_agreed", response.context["form"].errors)
            self.assertFalse(Patient.objects.exists())
            self.assertFalse(CommunicationConsentRecord.objects.exists())
            verification.refresh_from_db()
            self.assertIsNone(verification.completed_at)
        with self.assertRaises(ValidationError):
            self.create_with_grant(verification, processing_agreed=False)

    def test_all_independent_communication_choices_allow_registration(self):
        for index, (sms, voice) in enumerate(((False, False), (False, True), (True, False), (True, True))):
            with self.subTest(sms=sms, voice=voice):
                verification = self.start(phone=f"0805067544{index}")
                self.verify()
                response = self.details(sms_consent="yes" if sms else "no", voice_consent="yes" if voice else "no")
                patient = Patient.objects.get(phone_number=verification.phone_number)
                self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
                self.assertEqual((patient.sms_consent, patient.voice_consent), (sms, voice))
                self.assertEqual(set(patient.communication_consent_history.values_list("channel", "agreed")), {("sms", sms), ("voice", voice)})

    def test_notices_precede_collection_and_consent_is_not_preselected(self):
        response = self.client.get(reverse("patients:register"))
        body = response.content.decode().split('<footer class="site-footer">')[0]
        self.assertLess(body.index(reverse("core:patient_privacy")), body.index('<form method="post">', body.index('<h1')))
        self.start()
        self.verify()
        response = self.client.get(reverse("patients:register_details"))
        for field in ("processing_agreed", "sms_consent", "voice_consent"):
            self.assertNotIn("checked", str(response.context["form"][field]))
        body = response.content.decode().split('<footer class="site-footer">')[0]
        for route in ("patient_privacy", "privacy", "communication_info", "contact"):
            self.assertIn(reverse(f"core:{route}"), body)

    def test_association_notice_requires_agreement_and_preserves_choices(self):
        patient = make_patient()
        before = list(patient.communication_consent_history.values())
        self.client.post(reverse("patients:register"), {"phone_number": patient.local_phone})
        response = self.client.get(reverse("patients:associate"))
        self.assertNotIn("checked", str(response.context["form"]["patient_agreed"]))
        body = response.content.decode().split('<footer class="site-footer">')[0]
        self.assertIn(reverse("core:patient_privacy"), body)
        self.assertIn(reverse("core:communication_info"), body)
        self.assertNotIn(patient.first_name, body)
        response = self.client.post(reverse("patients:associate"), {})
        self.assertIn("patient_agreed", response.context["form"].errors)
        self.assertFalse(patient.vendors.exists())
        self.client.post(reverse("patients:associate"), {"patient_agreed": "on"})
        self.assertEqual(before, list(patient.communication_consent_history.values()))

    def delayed_verification(self):
        issued_at = timezone.now()
        with patch("accounts.services.timezone.now", return_value=issued_at):
            verification = self.start()
        verified_at = issued_at + timedelta(seconds=290)
        with patch("accounts.services.timezone.now", return_value=verified_at):
            self.verify()
        verification.refresh_from_db()
        return verification, issued_at, verified_at

    def test_patient_details_have_30_minutes_from_verification_even_after_otp_expiry(self):
        verification, issued_at, verified_at = self.delayed_verification()
        self.assertEqual(verification.expires_at, issued_at + timedelta(seconds=300))
        self.assertEqual(verification.consumed_at, verified_at)
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(seconds=1799)):
            response = self.details()
        patient = Patient.objects.get()
        self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
        self.assertEqual(VendorPatient.objects.count(), 1)
        self.assertEqual(PhoneVerification.objects.count(), 1)
        self.delivery.send.assert_called_once()
        verification.refresh_from_db()
        self.assertIsNotNone(verification.completed_at)
        self.assertEqual(verification.expires_at, issued_at + timedelta(seconds=300))

    def test_patient_registration_expires_exactly_30_minutes_after_verification(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=30)):
            response = self.details()
        self.assertRedirects(response, reverse("patients:verify"))
        self.assertFalse(Patient.objects.exists())
        self.assertFalse(VendorPatient.objects.exists())
        verification.refresh_from_db()
        self.assertIsNone(verification.completed_at)
        self.delivery.send.assert_called_once()

    def test_patient_otp_still_expires_after_five_minutes_and_cannot_gain_a_registration_window(self):
        issued_at = timezone.now()
        with patch("accounts.services.timezone.now", return_value=issued_at):
            verification = self.start()
        with patch("accounts.services.timezone.now", return_value=issued_at + timedelta(minutes=5)):
            with self.assertRaises(VerificationError):
                verify_otp(verification.pk, verification.phone_number, self.code, purpose="patient")
            with self.assertRaises(VerificationError):
                get_verified_registration(verification.pk, verification.phone_number, purpose="patient")
            response = self.details()
        self.assertRedirects(response, reverse("patients:verify"))
        self.assertFalse(Patient.objects.exists())
        verification.refresh_from_db()
        self.assertIsNone(verification.consumed_at)

    def test_form_validation_errors_do_not_restart_the_registration_window(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=20)):
            response = self.details(first_name="")
        self.assertIn("first_name", response.context["form"].errors)
        verification.refresh_from_db()
        self.assertEqual(verification.consumed_at, verified_at)
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=30)):
            response = self.details()
        self.assertRedirects(response, reverse("patients:verify"))
        self.assertFalse(Patient.objects.exists())

    def test_transactional_claim_rejects_grant_that_expires_after_the_initial_check(self):
        verification, _, verified_at = self.delayed_verification()
        # Simulate a successful read just before expiry, followed by an expired
        # grant when the creation transaction performs its conditional claim.
        with patch("patients.services.get_verified_registration", return_value=verification):
            with patch("patients.services.timezone.now", return_value=verified_at + timedelta(minutes=30)):
                with self.assertRaises(VerificationError):
                    self.create_with_grant(verification)
        self.assertFalse(Patient.objects.exists())
        self.assertFalse(VendorPatient.objects.exists())

    def create_with_grant(self, verification, **overrides):
        details = {
            "processing_agreed": True,
            "first_name": "Prototype", "last_name": "Patient",
            "date_of_birth": date(1990, 1, 1), "preferred_language": "English",
            "sms_consent": False, "voice_consent": False,
        }
        details.update(overrides)
        return complete_patient_registration(self.vendor, verification.pk, verification.phone_number, details)

    def test_new_patient_otp_invalidates_a_verified_grant_during_the_longer_window(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=10)):
            with self.captureOnCommitCallbacks(execute=True):
                replacement = issue_otp(verification.phone_number, purpose="patient")
            with self.assertRaises(VerificationError):
                self.create_with_grant(verification)
            with self.assertRaises(VerificationError):
                self.create_with_grant(replacement)
        self.assertFalse(Patient.objects.exists())
        self.assertEqual(self.delivery.send.call_count, 2)

    def test_verified_patient_code_cannot_be_verified_again_during_registration_window(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=10)):
            with self.assertRaises(VerificationError):
                verify_otp(verification.pk, verification.phone_number, self.code, purpose="patient")
            get_verified_registration(verification.pk, verification.phone_number, purpose="patient")

    def test_completed_patient_grant_cannot_create_another_patient(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=10)):
            self.create_with_grant(verification)
            with self.assertRaises(VerificationError):
                self.create_with_grant(verification)
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(VendorPatient.objects.count(), 1)

    def test_registration_window_does_not_allow_another_phone_or_otp_purpose(self):
        verification, _, verified_at = self.delayed_verification()
        with patch("accounts.services.timezone.now", return_value=verified_at + timedelta(minutes=10)):
            for phone, purpose in (("08050675449", "patient"), (verification.phone_number, "vendor")):
                with self.subTest(phone=phone, purpose=purpose):
                    with self.assertRaises(VerificationError):
                        get_verified_registration(verification.pk, phone, purpose=purpose)

    def test_patient_registration_session_remains_bound_to_the_verifying_vendor(self):
        self.delayed_verification()
        self.client.force_login(make_vendor("08012345679", "Second Pharmacy"))
        response = self.details()
        self.assertRedirects(response, reverse("patients:register"))
        self.assertFalse(Patient.objects.exists())

    def test_registration_details_cannot_skip_otp_verification(self):
        verification = self.start()
        session = self.client.session
        session[REGISTRATION_KEY]["verification_id"] = str(verification.pk)
        session.save()
        response = self.details()
        self.assertRedirects(response, reverse("patients:verify"))
        self.assertFalse(Patient.objects.exists())

    def test_required_fields_future_birth_date_and_phone_validation(self):
        response = self.client.post(
            reverse("patients:register"), {"phone_number": "02012345678"}
        )
        self.assertIn("phone_number", response.context["form"].errors)
        self.start()
        self.verify()
        response = self.details(
            first_name="",
            last_name="",
            date_of_birth=date.today().replace(year=date.today().year + 1).isoformat(),
            preferred_language="",
            sms_consent="",
            voice_consent="",
        )
        for field in (
            "first_name",
            "last_name",
            "date_of_birth",
            "preferred_language",
            "sms_consent",
            "voice_consent",
        ):
            self.assertIn(field, response.context["form"].errors)
        self.assertFalse(Patient.objects.exists())

    def test_global_phone_uniqueness_prevents_format_duplicates(self):
        make_patient(vendor=self.vendor)
        with self.assertRaises(ValidationError):
            make_patient(phone_number="+2348050675448")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Patient.objects.bulk_create(
                [
                    Patient(
                        first_name="Another",
                        last_name="Patient",
                        phone_number="+2348050675448",
                        date_of_birth=date(1990, 1, 1),
                        preferred_language="English",
                        sms_consent_recorded_at=patient_time(),
                        voice_consent_recorded_at=patient_time(),
                    )
                ]
            )

    def test_existing_patient_association_needs_consent_but_no_otp(self):
        patient = make_patient()
        response = self.client.post(
            reverse("patients:register"), {"phone_number": "08050675448"}
        )
        self.assertRedirects(response, reverse("patients:associate"))
        self.assertFalse(PhoneVerification.objects.exists())
        response = self.client.get(reverse("patients:associate"))
        self.assertContains(response, "patient record already exists")
        response = self.client.post(
            reverse("patients:associate"), {"patient_agreed": "on"}
        )
        self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
        association = VendorPatient.objects.get(patient=patient, vendor=self.vendor)
        self.assertIsNotNone(association.sharing_confirmed_at)
        self.assertEqual(association.confirmation_recorded_by, self.vendor)

    def test_declined_duplicate_and_already_associated_paths_do_not_duplicate_data(self):
        patient = make_patient()
        self.client.post(reverse("patients:register"), {"phone_number": patient.local_phone})
        response = self.client.post(reverse("patients:associate"), {"decision": "decline"})
        self.assertRedirects(response, reverse("patients:list"))
        self.assertFalse(VendorPatient.objects.exists())

        VendorPatient.objects.create(patient=patient, vendor=self.vendor)
        response = self.client.post(
            reverse("patients:register"), {"phone_number": patient.local_phone}
        )
        self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
        self.assertEqual(VendorPatient.objects.count(), 1)


def patient_time():
    from django.utils import timezone

    return timezone.now()

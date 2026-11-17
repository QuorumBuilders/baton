from datetime import date
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import PhoneVerification
from patients.models import Patient, VendorPatient
from patients.views import REGISTRATION_KEY

from .helpers import make_patient, make_vendor


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
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
        self.assertTrue(patient.vendors.filter(pk=self.vendor.pk).exists())
        verification.refresh_from_db()
        self.assertIsNotNone(verification.completed_at)

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

from datetime import timedelta
from importlib import import_module
from unittest.mock import Mock, patch

from django.apps import apps
from django.contrib import admin
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from communications.payloads import DeliveryOutcome, DeliveryResult

from accounts.models import User
from accounts.services import issue_otp
from patients.models import CommunicationConsentRecord, Patient, VendorPatient
from patients.services import (
    associate_existing_patient,
    process_due_reminders,
    send_patient_sms,
    withdraw_patient_communications,
)

from .helpers import make_patient, make_vendor
from .test_access_and_measurements import save_measurement


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ConsentHistoryTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.patient = make_patient(vendor=self.vendor, sms_consent=True, voice_consent=True)
        self.original = list(self.patient.communication_consent_history.values())

    def test_changes_append_history_and_preserve_original_choices_and_times(self):
        original_time = self.patient.voice_consent_recorded_at
        with patch("patients.models.timezone.now", return_value=original_time + timedelta(seconds=5)):
            self.patient.voice_consent = False
            self.patient.save(update_fields=["voice_consent"])
        self.patient.refresh_from_db()
        records = list(self.patient.communication_consent_history.values())
        self.assertEqual(records[:2], self.original)
        self.assertEqual(len(records), 3)
        self.assertEqual(self.patient.voice_consent_recorded_at, original_time + timedelta(seconds=5))
        self.assertTrue(self.patient.sms_consent)
        self.assertEqual(self.patient.sms_consent_recorded_at, self.original[0]["recorded_at"])
        self.assertEqual((records[-1]["channel"], records[-1]["agreed"]), ("voice", False))
        self.patient.voice_consent = True
        self.patient.save(update_fields=["voice_consent"])
        self.assertEqual(self.patient.communication_consent_history.count(), 4)

    def test_unchanged_and_partial_saves_do_not_invent_consent_changes(self):
        self.patient.save()
        self.patient.voice_consent = False
        self.patient.first_name = "Updated"
        self.patient.save(update_fields=["first_name"])
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.voice_consent)
        self.assertEqual(self.patient.first_name, "Updated")
        self.assertEqual(list(self.patient.communication_consent_history.values()), self.original)
        self.patient.voice_consent = False
        self.patient.save(update_fields=[])
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.voice_consent)
        self.assertEqual(self.patient.communication_consent_history.count(), 2)

    def test_consent_timestamps_and_processing_agreement_cannot_be_overwritten(self):
        self.patient.voice_consent_recorded_at = timezone.now() + timedelta(days=1)
        self.patient.save(update_fields=["voice_consent_recorded_at"])
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.voice_consent_recorded_at, self.original[1]["recorded_at"])
        self.patient.processing_agreed_at = timezone.now()
        self.patient.processing_agreement_recorded_by = self.vendor
        with self.assertRaises(ValidationError):
            self.patient.save()

    def test_audit_records_reject_edits_deletes_and_bulk_overwrites(self):
        record = self.patient.communication_consent_history.first()
        record.agreed = False
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()
        with self.assertRaises(ValidationError):
            CommunicationConsentRecord.objects.filter(pk=record.pk).update(agreed=False)
        with self.assertRaises(ValidationError):
            CommunicationConsentRecord.objects.filter(pk=record.pk).delete()
        with self.assertRaises(ValidationError), transaction.atomic():
            CommunicationConsentRecord.objects.bulk_update([record], ["agreed"])
        with self.assertRaises(ValidationError):
            Patient.objects.filter(pk=self.patient.pk).update(voice_consent=False)
        with self.assertRaises(ValidationError), transaction.atomic():
            Patient.objects.bulk_update([self.patient], ["sms_consent"])
        self.assertEqual(list(self.patient.communication_consent_history.values()), self.original)

    def test_duplicate_association_preserves_original_confirmation(self):
        vendor = make_vendor("08012345679", "Second Pharmacy")
        association, created = associate_existing_patient(vendor, self.patient, patient_agreed=True)
        self.assertTrue(created)
        original = (association.sharing_confirmed_at, association.confirmation_recorded_by_id)
        again, created = associate_existing_patient(vendor, self.patient, patient_agreed=True)
        self.assertFalse(created)
        self.assertEqual((again.sharing_confirmed_at, again.confirmation_recorded_by_id), original)
        association.sharing_confirmed_at = timezone.now() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            association.save()
        self.assertEqual(list(self.patient.communication_consent_history.values()), self.original)

    def test_admin_history_is_read_only_and_consent_changes_record_the_actor(self):
        administrator = User.objects.create_superuser(username="privacy-admin", password="safe-test-password")
        request = RequestFactory().post("/admin/")
        request.user = administrator
        for model in (CommunicationConsentRecord, VendorPatient):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        patient_admin = admin.site._registry[Patient]
        self.assertFalse(patient_admin.has_add_permission(request))
        self.patient.voice_consent = False
        patient_admin.save_model(request, self.patient, None, change=True)
        record = self.patient.communication_consent_history.last()
        self.assertEqual((record.source, record.recorded_by), ("admin", administrator))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CommunicationWithdrawalTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.patient = make_patient(vendor=self.vendor, sms_consent=True, voice_consent=True)
        self.client.force_login(self.vendor)
        self.url = reverse("patients:communication_consent", args=[self.patient.pk])

    def test_controls_are_unselected_and_linked_from_the_patient_record(self):
        response = self.client.get(self.url)
        self.assertNotIn("checked", str(response.context["form"]))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        body = response.content.decode().split('<footer class="site-footer">')[0]
        for route in ("patient_privacy", "communication_info", "contact"):
            self.assertIn(reverse(f"core:{route}"), body)
        response = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
        self.assertContains(response, f'href="{self.url}"')

    def test_sms_withdrawal_does_not_change_voice_or_remove_history(self):
        followup = save_measurement(self.patient, self.vendor).next_followup
        original = list(self.patient.communication_consent_history.values())
        response = self.client.post(self.url, {"withdraw_sms": "on"})
        self.assertRedirects(response, reverse("patients:detail", args=[self.patient.pk]))
        self.patient.refresh_from_db()
        self.assertFalse(self.patient.sms_consent)
        self.assertTrue(self.patient.voice_consent)
        records = list(self.patient.communication_consent_history.values())
        self.assertEqual(records[:2], original)
        self.assertEqual((records[-1]["channel"], records[-1]["source"], records[-1]["recorded_by_id"]), ("sms", "vendor", self.vendor.pk))
        self.assertEqual(self.patient.measurements.count(), 1)
        self.assertEqual(self.patient.followups.count(), 1)
        with patch("patients.services.get_sms_adapter") as sms_adapter:
            with self.assertRaises(PermissionDenied):
                send_patient_sms(patient_id=self.patient.pk, body="Prototype reminder", category="test", reference_id="withdrawn")
        sms_adapter.assert_not_called()
        # Voice remains permitted after withdrawing SMS.
        voice_adapter = Mock()
        voice_adapter.invoke.return_value = DeliveryResult(outcome=DeliveryOutcome.SIMULATED, adapter="test", delivery_mode="test")
        with patch("patients.services.get_voice_adapter", return_value=voice_adapter):
            result = process_due_reminders(at=followup.scheduled_date + timedelta(days=4))
        self.assertEqual(result["simulated"], 5)

    def test_voice_withdrawal_blocks_future_reminders_and_preserves_sms(self):
        followup = save_measurement(self.patient, self.vendor).next_followup
        self.client.post(self.url, {"withdraw_voice": "on"})
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.sms_consent)
        self.assertFalse(self.patient.voice_consent)
        with patch("patients.services.get_voice_adapter") as voice_adapter:
            result = process_due_reminders(at=followup.scheduled_date + timedelta(days=4))
        voice_adapter.assert_not_called()
        self.assertEqual(result["skipped"], 5)
        self.assertEqual(result["simulated"], 0)
        self.assertEqual(result["delivered"], 0)
        self.assertTrue(self.patient.vendors.filter(pk=self.vendor.pk).exists())

    def test_both_can_be_withdrawn_and_duplicate_requests_do_not_rewrite_history(self):
        self.client.post(self.url, {"withdraw_sms": "on", "withdraw_voice": "on"})
        self.patient.refresh_from_db()
        self.assertFalse(self.patient.sms_consent or self.patient.voice_consent)
        records = list(self.patient.communication_consent_history.values())
        self.assertEqual(len(records), 4)
        self.client.post(self.url, {"withdraw_sms": "on", "withdraw_voice": "on"})
        self.assertEqual(records, list(self.patient.communication_consent_history.values()))

    def test_empty_request_does_not_change_choices_or_history(self):
        response = self.client.post(self.url, {})
        self.assertTrue(response.context["form"].non_field_errors())
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.sms_consent and self.patient.voice_consent)
        self.assertEqual(self.patient.communication_consent_history.count(), 2)

    def test_associated_second_vendor_can_record_patient_withdrawal(self):
        vendor = make_vendor("08012345679", "Second Pharmacy")
        associate_existing_patient(vendor, self.patient, patient_agreed=True)
        self.client.force_login(vendor)
        response = self.client.post(self.url, {"withdraw_voice": "on"})
        self.assertRedirects(response, reverse("patients:detail", args=[self.patient.pk]))
        record = self.patient.communication_consent_history.last()
        self.assertEqual(record.recorded_by, vendor)

    def test_login_association_and_csrf_checks_protect_withdrawal(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        unrelated = make_vendor("08012345679", "Unrelated Pharmacy")
        self.client.force_login(unrelated)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.url).status_code, 404)
        with self.assertRaises(PermissionDenied):
            withdraw_patient_communications(unrelated, self.patient.pk, voice=True)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.vendor)
        self.assertEqual(csrf_client.post(self.url, {"withdraw_voice": "on"}).status_code, 403)
        csrf_client.get(self.url)
        token = csrf_client.cookies["csrftoken"].value
        response = csrf_client.post(self.url, {"withdraw_voice": "on", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertIn(CookieStorage.cookie_name, response.cookies)

    def test_admin_and_inactive_vendors_cannot_use_vendor_withdrawal(self):
        administrator = User.objects.create_superuser(username="privacy-admin", password="safe-test-password")
        self.client.force_login(administrator)
        self.assertEqual(self.client.post(self.url, {"withdraw_voice": "on"}).status_code, 403)
        self.vendor.is_active = False
        self.vendor.save()
        with self.assertRaises(PermissionDenied):
            withdraw_patient_communications(self.vendor, self.patient.pk, voice=True)

    def test_withdrawal_does_not_block_transactional_otp(self):
        withdraw_patient_communications(self.vendor, self.patient.pk, sms=True, voice=True)
        with patch("accounts.services.get_delivery_backend") as adapter:
            with self.captureOnCommitCallbacks(execute=True):
                verification = issue_otp(self.patient.phone_number, purpose="patient")
        adapter.return_value.send.assert_called_once()
        self.assertEqual(verification.purpose, "patient")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LegacyConsentMigrationTests(TestCase):
    def test_historical_model_snapshot_preserves_values_without_fabricating_agreement(self):
        # Historical migration models intentionally do not run current save hooks.
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        historical_apps = executor.loader.project_state([("patients", "0005_privacy_consent_history")]).apps
        HistoricalPatient = historical_apps.get_model("patients", "Patient")
        patient = HistoricalPatient.objects.create(
            first_name="Prototype", last_name="Patient", phone_number="+2348050675448",
            date_of_birth="1990-01-01", preferred_language="English",
            sms_consent=True, voice_consent=False,
            sms_consent_recorded_at=timezone.now() - timedelta(days=2),
            voice_consent_recorded_at=timezone.now() - timedelta(days=1),
        )
        migration = import_module("patients.migrations.0005_privacy_consent_history")
        migration.preserve_legacy_choices(historical_apps, connection.schema_editor())
        current = Patient.objects.get(pk=patient.pk)
        records = list(current.communication_consent_history.all())
        self.assertEqual(len(records), 2)
        self.assertEqual([(r.channel, r.agreed) for r in records], [("sms", True), ("voice", False)])
        self.assertEqual(records[0].recorded_at, patient.sms_consent_recorded_at)
        self.assertEqual(records[1].recorded_at, patient.voice_consent_recorded_at)
        self.assertTrue(all(r.source == "legacy" and r.recorded_by is None for r in records))
        self.assertIsNone(current.processing_agreed_at)
        self.assertIsNone(current.processing_agreement_recorded_by)
        migration.preserve_legacy_choices(historical_apps, connection.schema_editor())
        self.assertEqual(current.communication_consent_history.count(), 2)

    def test_snapshot_does_not_mislabel_already_audited_choices(self):
        patient = make_patient()
        original = list(patient.communication_consent_history.values())
        migration = import_module("patients.migrations.0005_privacy_consent_history")
        migration.preserve_legacy_choices(apps, connection.schema_editor())
        self.assertEqual(list(patient.communication_consent_history.values()), original)

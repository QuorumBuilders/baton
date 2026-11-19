from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from communications.adapters import DeliveryUnavailable, MockVoiceAdapter
from communications.content import (
    VoiceCategory,
    VoiceLanguage,
    resolve_voice_content,
)
from communications.payloads import DeliveryOutcome, DeliveryResult, VoiceRequest
from patients.models import CommunicationAttempt, Patient, ReminderSchedule
from patients.services import (
    _process_reserved_communication,
    _reserve_communication,
    process_due_reminders,
    reschedule_active_followup,
    send_patient_sms,
)

from .helpers import make_patient, make_vendor
from .test_access_and_measurements import save_measurement


class VoiceContentTests(SimpleTestCase):
    expected_references = {
        (VoiceCategory.SCHEDULED_VISIT, VoiceLanguage.ENGLISH): "recordings/en/scheduled-visit-v1.mp3",
        (VoiceCategory.SCHEDULED_VISIT, VoiceLanguage.NIGERIAN_PIDGIN): "recordings/pcm/scheduled-visit-v1.mp3",
        (VoiceCategory.FIRST_OVERDUE, VoiceLanguage.ENGLISH): "recordings/en/first-overdue-v1.mp3",
        (VoiceCategory.FIRST_OVERDUE, VoiceLanguage.NIGERIAN_PIDGIN): "recordings/pcm/first-overdue-v1.mp3",
        (VoiceCategory.FINAL_OVERDUE, VoiceLanguage.ENGLISH): "recordings/en/final-overdue-v1.mp3",
        (VoiceCategory.FINAL_OVERDUE, VoiceLanguage.NIGERIAN_PIDGIN): "recordings/pcm/final-overdue-v1.mp3",
        (VoiceCategory.MEDICATION, VoiceLanguage.ENGLISH): "recordings/en/medication-v1.mp3",
        (VoiceCategory.MEDICATION, VoiceLanguage.NIGERIAN_PIDGIN): "recordings/pcm/medication-v1.mp3",
        (VoiceCategory.GENERAL_HEALTH, VoiceLanguage.ENGLISH): "recordings/en/general-health-v1.mp3",
        (VoiceCategory.GENERAL_HEALTH, VoiceLanguage.NIGERIAN_PIDGIN): "recordings/pcm/general-health-v1.mp3",
    }

    def test_every_category_resolves_english_and_pidgin_recording_references(self):
        for (category, language), expected in self.expected_references.items():
            with self.subTest(category=category, language=language):
                preferred = "English" if language == VoiceLanguage.ENGLISH else "Nigerian Pidgin"
                content = resolve_voice_content(category, preferred)
                self.assertEqual(content.language, language)
                self.assertEqual(content.recording_reference, expected)
                self.assertTrue(content.approved_script)


class MockVoiceAdapterTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_mock_logs_complete_invocation_without_claiming_real_delivery(self):
        request = VoiceRequest(
            recipient="+2348050675448",
            category=VoiceCategory.MEDICATION,
            language=VoiceLanguage.NIGERIAN_PIDGIN,
            recording_reference="recordings/pcm/medication-v1.mp3",
            reference_id="voice-reference-1",
        )
        output = StringIO()
        with redirect_stdout(output):
            result = MockVoiceAdapter().invoke(request)
        rendered = output.getvalue()
        for expected in (
            request.recipient,
            request.category,
            request.language,
            request.recording_reference,
            request.reference_id,
            "timestamp=",
            "MOCK / NOT A REAL CALL",
        ):
            self.assertIn(expected, rendered)
        self.assertEqual(result.outcome, DeliveryOutcome.SIMULATED)

    @override_settings(DEBUG=False)
    def test_mock_voice_adapter_is_blocked_outside_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            MockVoiceAdapter()

    def test_existing_mock_adapter_checks_debug_again_before_invocation(self):
        with override_settings(DEBUG=True):
            adapter = MockVoiceAdapter()
        output = StringIO()
        with override_settings(DEBUG=False), redirect_stdout(output):
            with self.assertRaises(ImproperlyConfigured):
                adapter.invoke(VoiceRequest("+2348050675448", "medication", "english", "recording", "reference"))
        self.assertEqual(output.getvalue(), "")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ReminderCommunicationTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.patient = make_patient(
            vendor=self.vendor, voice_consent=True, sms_consent=True
        )
        self.followup = save_measurement(
            self.patient,
            self.vendor,
            manual_date=timezone.localdate() + timedelta(days=5),
        ).next_followup
        self.adapter = Mock()
        self.adapter.invoke.return_value = DeliveryResult(
            outcome=DeliveryOutcome.SIMULATED,
            adapter="tests.VoiceAdapter",
            delivery_mode="development_mock",
            provider_reference="provider-reference",
        )
        adapter_patch = patch(
            "patients.services.get_voice_adapter", return_value=self.adapter
        )
        adapter_patch.start()
        self.addCleanup(adapter_patch.stop)

    @property
    def final_processing_date(self):
        return self.followup.scheduled_date + timedelta(days=4)

    def test_due_reminders_create_inspectable_simulated_attempts(self):
        result = process_due_reminders(at=self.final_processing_date)
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["simulated"], 4)
        self.assertEqual(result["delivered"], 0)
        self.assertEqual(CommunicationAttempt.objects.count(), 4)
        attempt = CommunicationAttempt.objects.get(
            reminder__event=ReminderSchedule.Event.VISIT_DUE
        )
        self.assertEqual(attempt.recipient, self.patient.phone_number)
        self.assertEqual(attempt.category, VoiceCategory.SCHEDULED_VISIT)
        self.assertEqual(attempt.language, VoiceLanguage.ENGLISH)
        self.assertEqual(
            attempt.recording_reference, "recordings/en/scheduled-visit-v1.mp3"
        )
        self.assertEqual(attempt.outcome, CommunicationAttempt.Outcome.SIMULATED)
        self.assertEqual(
            attempt.reminder.delivery_status,
            ReminderSchedule.DeliveryStatus.SIMULATED,
        )

    def test_pidgin_preference_selects_pidgin_recording(self):
        self.patient.preferred_language = "Nigerian Pidgin"
        self.patient.save()
        process_due_reminders(at=self.followup.scheduled_date)
        attempt = CommunicationAttempt.objects.get(
            reminder__event=ReminderSchedule.Event.VISIT_DUE
        )
        self.assertEqual(attempt.language, VoiceLanguage.NIGERIAN_PIDGIN)
        self.assertIn("recordings/pcm/", attempt.recording_reference)

    def test_absent_voice_consent_is_skipped_and_never_invokes_adapter(self):
        self.patient.voice_consent = False
        self.patient.save()
        result = process_due_reminders(at=self.final_processing_date)
        self.assertEqual(result["skipped"], 4)
        self.assertEqual(result["simulated"], 0)
        self.adapter.invoke.assert_not_called()
        attempt = CommunicationAttempt.objects.first()
        self.assertEqual(attempt.outcome, CommunicationAttempt.Outcome.SKIPPED)
        self.assertIn("consent", attempt.reason)

    def test_adapter_failure_is_recorded_without_deleting_the_reminder(self):
        self.adapter.invoke.side_effect = RuntimeError("transport unavailable")
        result = process_due_reminders(at=self.followup.scheduled_date)
        self.assertGreater(result["failed"], 0)
        attempt = CommunicationAttempt.objects.get(
            reminder__event=ReminderSchedule.Event.VISIT_DUE
        )
        self.assertEqual(attempt.outcome, CommunicationAttempt.Outcome.FAILED)
        self.assertIn("RuntimeError", attempt.reason)
        self.assertNotIn("transport unavailable", attempt.reason)
        self.assertEqual(attempt.recording_reference, "recordings/en/scheduled-visit-v1.mp3")
        self.assertTrue(attempt.adapter)
        self.assertTrue(ReminderSchedule.objects.filter(pk=attempt.reminder_id).exists())

    def test_repeated_processing_does_not_duplicate_attempts(self):
        first = process_due_reminders(at=self.final_processing_date)
        second = process_due_reminders(at=self.final_processing_date)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(CommunicationAttempt.objects.count(), first["processed"])
        self.assertEqual(self.adapter.invoke.call_count, first["simulated"])

    def test_fulfilled_followup_does_not_produce_later_communications(self):
        old_followup = self.followup
        save_measurement(self.patient, self.vendor)
        process_due_reminders(at=self.final_processing_date)
        self.assertFalse(
            CommunicationAttempt.objects.filter(reminder__followup=old_followup).exists()
        )

    def test_manual_admin_processing_invokes_the_same_service(self):
        administrator = get_user_model().objects.create_superuser(
            "administrator", password="Pine!Stone7quiet"
        )
        self.client.force_login(administrator)
        selected = [self.followup.reminders.first().pk]
        with patch(
            "patients.admin.process_due_reminders",
            wraps=lambda: process_due_reminders(at=self.final_processing_date),
        ):
            response = self.client.post(
                reverse("admin:patients_reminderschedule_changelist"),
                {
                    "action": "process_due_reminder_schedules",
                    "_selected_action": selected,
                },
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "simulated")
        self.assertTrue(CommunicationAttempt.objects.exists())

    def test_vendor_history_identifies_simulated_communication(self):
        process_due_reminders(at=self.followup.scheduled_date)
        self.client.force_login(self.vendor)
        response = self.client.get(
            reverse("patients:followup_history", args=[self.patient.pk])
        )
        self.assertContains(response, "Reminder and communication history")
        self.assertContains(response, "Simulated")
        self.assertContains(response, "no phone call was made")

    def test_unknown_adapter_outcome_is_failed_and_never_recorded_as_delivery(self):
        self.adapter.invoke.return_value = DeliveryResult("unexpected", "tests.Adapter", "test")
        result = process_due_reminders(at=self.followup.scheduled_date)
        self.assertGreater(result["failed"], 0)
        self.assertEqual(result["delivered"], 0)
        self.assertFalse(CommunicationAttempt.objects.filter(outcome="delivered").exists())

    def test_legacy_unsupported_language_is_failed_without_using_another_language(self):
        Patient.objects.filter(pk=self.patient.pk).update(preferred_language="Yoruba")
        result = process_due_reminders(at=self.followup.scheduled_date)
        self.assertGreater(result["failed"], 0)
        self.adapter.invoke.assert_not_called()
        self.assertIn("No recording", CommunicationAttempt.objects.first().reason)

    @override_settings(VOICE_DELIVERY_BACKEND="")
    def test_missing_adapter_is_failed_and_selected_recording_remains_inspectable(self):
        self.adapter.invoke.side_effect = DeliveryUnavailable("unavailable")
        result = process_due_reminders(at=self.followup.scheduled_date)
        self.assertGreater(result["failed"], 0)
        self.assertTrue(CommunicationAttempt.objects.first().recording_reference)

    def test_failed_and_skipped_attempts_are_not_retried_by_the_manual_action(self):
        self.adapter.invoke.side_effect = RuntimeError("unavailable")
        first = process_due_reminders(at=self.followup.scheduled_date)
        self.patient.voice_consent = False
        self.patient.save()
        second = process_due_reminders(at=self.final_processing_date)
        third = process_due_reminders(at=self.final_processing_date)
        self.assertEqual(first["failed"], 2)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual(third["processed"], 0)
        self.assertEqual(CommunicationAttempt.objects.count(), 4)

    def reserve_visit(self):
        reminder = self.followup.reminders.get(event=ReminderSchedule.Event.VISIT_DUE)
        return _reserve_communication(reminder.pk, timezone.now())

    def test_consent_revoked_after_reservation_blocks_invocation(self):
        reminder, attempt = self.reserve_visit()
        self.patient.voice_consent = False
        self.patient.save()
        outcome = _process_reserved_communication(reminder, attempt, timezone.now())
        self.assertEqual(outcome, CommunicationAttempt.Outcome.SKIPPED)
        self.adapter.invoke.assert_not_called()

    def test_measurement_after_reservation_blocks_the_old_reminder(self):
        reminder, attempt = self.reserve_visit()
        save_measurement(self.patient, self.vendor)
        outcome = _process_reserved_communication(reminder, attempt, timezone.now())
        self.assertEqual(outcome, CommunicationAttempt.Outcome.SKIPPED)
        self.adapter.invoke.assert_not_called()

    def test_reschedule_after_reservation_blocks_the_old_revision(self):
        reminder, attempt = self.reserve_visit()
        reschedule_active_followup(
            followup_id=self.followup.pk, vendor=self.vendor,
            scheduled_date=self.followup.scheduled_date + timedelta(days=1),
        )
        outcome = _process_reserved_communication(reminder, attempt, timezone.now())
        self.assertEqual(outcome, CommunicationAttempt.Outcome.SKIPPED)
        self.adapter.invoke.assert_not_called()

    def test_vendor_cannot_use_admin_processing_or_inspect_admin_attempts(self):
        self.client.force_login(self.vendor)
        response = self.client.post(reverse("admin:patients_reminderschedule_changelist"), {
            "action": "process_due_reminder_schedules", "_selected_action": [self.followup.reminders.first().pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CommunicationAttempt.objects.exists())
        self.assertEqual(self.client.get(reverse("admin:patients_communicationattempt_changelist")).status_code, 302)

    def test_non_otp_patient_sms_requires_current_sms_consent(self):
        with patch("patients.services.get_sms_adapter") as sms_adapter:
            result = send_patient_sms(patient_id=self.patient.pk, body="Test message", category="test", reference_id="test-ref")
            self.assertIs(result, sms_adapter.return_value.send.return_value)
            self.assertEqual(sms_adapter.return_value.send.call_args.args[0].recipient, self.patient.phone_number)
            self.patient.sms_consent = False
            self.patient.save()
            with self.assertRaises(PermissionDenied):
                send_patient_sms(patient_id=self.patient.pk, body="Test message", category="test", reference_id="test-ref-2")
            self.assertEqual(sms_adapter.return_value.send.call_count, 1)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ConcurrentReminderProcessingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        vendor = make_vendor()
        patient = make_patient(vendor=vendor, voice_consent=True)
        self.followup = save_measurement(
            patient,
            vendor,
            manual_date=timezone.localdate() + timedelta(days=1),
        ).next_followup
        self.adapter = Mock()
        self.adapter.invoke.return_value = DeliveryResult(
            outcome=DeliveryOutcome.SIMULATED,
            adapter="tests.ConcurrentVoiceAdapter",
            delivery_mode="development_mock",
        )
        adapter_patch = patch(
            "patients.services.get_voice_adapter", return_value=self.adapter
        )
        adapter_patch.start()
        self.addCleanup(adapter_patch.stop)

    def process_in_separate_connection(self):
        close_old_connections()
        try:
            self.start_barrier.wait(timeout=10)
            return process_due_reminders(at=self.followup.scheduled_date)
        finally:
            close_old_connections()

    def test_concurrent_processing_creates_only_one_attempt(self):
        self.start_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.process_in_separate_connection(), range(2)))
        self.assertEqual(sum(result["processed"] for result in results), 1)
        self.assertEqual(CommunicationAttempt.objects.count(), 1)
        self.assertEqual(self.adapter.invoke.call_count, 1)

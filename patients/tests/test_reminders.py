from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from patients.models import (
    CommunicationAttempt,
    FollowUp,
    FollowUpRule,
    FollowUpScheduleChange,
    ReminderSchedule,
    VendorNotification,
    VendorPatient,
)
from communications.payloads import DeliveryOutcome, DeliveryResult
from patients.services import (
    create_reminder_schedules,
    process_due_reminders,
    reschedule_active_followup,
)

from .helpers import make_patient, make_vendor
from .test_access_and_measurements import save_measurement


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ReminderSchedulingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vendor = make_vendor()

    def patient(self, phone="08050675448", **kwargs):
        return make_patient(phone, vendor=self.vendor, **kwargs)

    def test_default_rule_is_active_and_uses_21_days(self):
        rule = FollowUpRule.objects.get(is_active=True)
        self.assertEqual(rule.interval_days, 21)
        patient = self.patient()
        followup = save_measurement(patient, self.vendor).next_followup
        measured_date = timezone.localdate(followup.source_measurement.measured_at)
        self.assertEqual(followup.scheduled_date, measured_date + timedelta(days=21))

    def test_21_day_interval_has_two_week_apart_health_reminders_and_visit_sequence(self):
        patient = self.patient()
        followup = save_measurement(patient, self.vendor).next_followup
        measured_date = timezone.localdate(followup.source_measurement.measured_at)
        health = list(
            followup.reminders.filter(
                category=ReminderSchedule.Category.MEDICATION_HEALTH
            ).order_by("scheduled_for")
        )
        self.assertEqual([timezone.localdate(item.scheduled_for) for item in health], [
            measured_date + timedelta(days=7),
            measured_date + timedelta(days=14),
        ])
        visits = list(
            followup.reminders.filter(category=ReminderSchedule.Category.VISIT)
            .order_by("scheduled_for")
            .values_list("event", "scheduled_for")
        )
        self.assertEqual([event for event, _ in visits], [
            ReminderSchedule.Event.VISIT_DUE,
            ReminderSchedule.Event.OVERDUE_FIRST,
            ReminderSchedule.Event.OVERDUE_FINAL,
        ])
        self.assertEqual([timezone.localdate(value) for _, value in visits], [
            followup.scheduled_date,
            followup.scheduled_date + timedelta(days=2),
            followup.scheduled_date + timedelta(days=4),
        ])

    def test_shorter_interval_has_one_health_reminder_and_longer_has_two(self):
        short_patient = self.patient()
        short_followup = save_measurement(
            short_patient,
            self.vendor,
            manual_date=timezone.localdate() + timedelta(days=10),
        ).next_followup
        self.assertEqual(
            short_followup.reminders.filter(
                category=ReminderSchedule.Category.MEDICATION_HEALTH
            ).count(),
            1,
        )

        long_patient = self.patient("08050675449")
        long_followup = save_measurement(
            long_patient,
            self.vendor,
            manual_date=timezone.localdate() + timedelta(days=30),
        ).next_followup
        self.assertEqual(
            long_followup.reminders.filter(
                category=ReminderSchedule.Category.MEDICATION_HEALTH
            ).count(),
            2,
        )

    def test_manual_reschedule_recalculates_reminders_and_preserves_revision_history(self):
        patient = self.patient()
        followup = save_measurement(patient, self.vendor).next_followup
        old_date = followup.scheduled_date
        new_date = timezone.localdate() + timedelta(days=10)
        reschedule_active_followup(
            followup_id=followup.pk,
            vendor=self.vendor,
            scheduled_date=new_date,
        )
        followup.refresh_from_db()
        self.assertEqual(followup.followup_type, FollowUp.Type.MANUAL)
        self.assertEqual(followup.scheduled_date, new_date)
        self.assertEqual(followup.schedule_revision, 2)
        self.assertEqual(
            followup.reminders.filter(
                schedule_revision=1,
                processing_status=ReminderSchedule.ProcessingStatus.CANCELLED,
            ).count(),
            5,
        )
        self.assertEqual(
            followup.reminders.filter(
                schedule_revision=2,
                processing_status=ReminderSchedule.ProcessingStatus.PENDING,
            ).count(),
            4,
        )
        change = FollowUpScheduleChange.objects.get()
        self.assertEqual((change.previous_scheduled_date, change.scheduled_date), (old_date, new_date))

    def test_schedule_creation_is_idempotent_and_does_not_modify_followup(self):
        patient = self.patient()
        followup = save_measurement(patient, self.vendor).next_followup
        original_date = followup.scheduled_date
        self.assertEqual(create_reminder_schedules(followup), [])
        self.assertEqual(followup.reminders.count(), 5)
        followup.refresh_from_db()
        self.assertEqual(followup.scheduled_date, original_date)

    def test_routine_reminders_are_voice_only_and_scheduled_independently_of_consent(self):
        patient = self.patient(sms_consent=True, voice_consent=True)
        followup = save_measurement(patient, self.vendor).next_followup
        self.assertEqual(followup.reminders.count(), 5)
        self.assertEqual(
            set(followup.reminders.values_list("channel", flat=True)),
            {ReminderSchedule.Channel.VOICE},
        )
        self.assertFalse(
            followup.reminders.exclude(
                delivery_status=ReminderSchedule.DeliveryStatus.NOT_ATTEMPTED
            ).exists()
        )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ReminderProcessingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.scheduler = make_vendor()
        cls.other_vendor = make_vendor("08012345679", "Second Pharmacy")

    def setUp(self):
        self.voice_adapter = patch("patients.services.get_voice_adapter").start()
        self.addCleanup(patch.stopall)
        self.voice_adapter.return_value.invoke.return_value = DeliveryResult(
            outcome=DeliveryOutcome.SIMULATED,
            adapter="tests.MockVoiceAdapter",
            delivery_mode="development_mock",
            provider_reference="mock-reference",
        )
        self.patient = make_patient(vendor=self.scheduler, voice_consent=True)
        VendorPatient.objects.create(patient=self.patient, vendor=self.other_vendor)
        self.followup = save_measurement(
            self.patient,
            self.scheduler,
            manual_date=timezone.localdate() + timedelta(days=5),
        ).next_followup

    def event(self, event):
        return self.followup.reminders.get(event=event)

    def test_visit_and_fixed_overdue_reminders_process_once_at_0_2_and_4_days(self):
        due = self.followup.scheduled_date
        first = process_due_reminders(at=due)
        self.event(ReminderSchedule.Event.VISIT_DUE).refresh_from_db()
        self.assertEqual(
            self.event(ReminderSchedule.Event.VISIT_DUE).processing_status,
            ReminderSchedule.ProcessingStatus.PROCESSED,
        )
        self.assertEqual(
            self.event(ReminderSchedule.Event.OVERDUE_FIRST).processing_status,
            ReminderSchedule.ProcessingStatus.PENDING,
        )
        self.assertGreaterEqual(first["processed"], 1)

        process_due_reminders(at=due + timedelta(days=2))
        self.assertEqual(
            self.event(ReminderSchedule.Event.OVERDUE_FIRST).processing_status,
            ReminderSchedule.ProcessingStatus.PROCESSED,
        )
        self.assertEqual(
            self.event(ReminderSchedule.Event.OVERDUE_FINAL).processing_status,
            ReminderSchedule.ProcessingStatus.PENDING,
        )

        process_due_reminders(at=due + timedelta(days=4))
        self.assertEqual(
            self.event(ReminderSchedule.Event.OVERDUE_FINAL).processing_status,
            ReminderSchedule.ProcessingStatus.PROCESSED,
        )
        self.followup.refresh_from_db()
        self.assertTrue(self.followup.attention_required)
        self.assertIsNotNone(self.followup.attention_flagged_at)
        self.assertEqual(
            process_due_reminders(at=due + timedelta(days=20))["processed"], 0
        )
        self.assertFalse(
            self.followup.reminders.filter(
                processing_status=ReminderSchedule.ProcessingStatus.PENDING
            ).exists()
        )

    def test_manual_overdue_notification_is_idempotent_and_dashboard_limits_it_to_scheduler(self):
        processing_date = self.followup.scheduled_date + timedelta(days=1)
        first = process_due_reminders(at=processing_date)
        second = process_due_reminders(at=processing_date)
        self.assertEqual(first["vendor_notifications"], 1)
        self.assertEqual(second["vendor_notifications"], 0)
        notification = VendorNotification.objects.get()
        self.assertEqual(notification.vendor, self.scheduler)
        self.assertEqual(notification.patient, self.patient)

        with patch("accounts.views.timezone.localdate", return_value=processing_date):
            self.client.force_login(self.scheduler)
            response = self.client.get(reverse("accounts:dashboard"))
            self.assertContains(response, "Manual follow-up overdue")
            self.client.force_login(self.other_vendor)
            response = self.client.get(reverse("accounts:dashboard"))
            self.assertNotContains(response, "Manual follow-up overdue")

        with patch("patients.views.timezone.localdate", return_value=processing_date):
            response = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
            self.assertContains(response, "Overdue")

    def test_final_attention_flag_is_visible_to_all_associated_vendors(self):
        process_due_reminders(at=self.followup.scheduled_date + timedelta(days=4))
        for vendor in (self.scheduler, self.other_vendor):
            self.client.force_login(vendor)
            response = self.client.get(reverse("accounts:dashboard"))
            self.assertContains(response, self.patient.first_name)
            response = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
            self.assertContains(response, "Vendor attention required")

    def test_new_measurement_cancels_all_outstanding_old_followup_reminders(self):
        old_followup = self.followup
        save_measurement(self.patient, self.other_vendor)
        old_followup.refresh_from_db()
        self.assertEqual(old_followup.status, FollowUp.Status.FULFILLED)
        self.assertFalse(
            old_followup.reminders.filter(
                processing_status=ReminderSchedule.ProcessingStatus.PENDING
            ).exists()
        )
        self.assertEqual(
            old_followup.reminders.filter(
                processing_status=ReminderSchedule.ProcessingStatus.CANCELLED
            ).count(),
            4,
        )

    def test_repeated_processing_never_duplicates_schedules_or_claims_real_delivery(self):
        count = ReminderSchedule.objects.count()
        at = self.followup.scheduled_date + timedelta(days=4)
        first = process_due_reminders(at=at)
        second = process_due_reminders(at=at)
        self.assertGreater(first["processed"], 0)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(ReminderSchedule.objects.count(), count)
        self.assertEqual(CommunicationAttempt.objects.count(), first["processed"])
        self.assertFalse(
            CommunicationAttempt.objects.exclude(
                outcome=CommunicationAttempt.Outcome.SIMULATED
            ).exists()
        )
        self.assertFalse(
            ReminderSchedule.objects.filter(
                delivery_status=ReminderSchedule.DeliveryStatus.DELIVERED
            ).exists()
        )

    def test_revoked_consent_skips_due_rows_but_still_flags_vendor_attention(self):
        self.patient.voice_consent = False
        self.patient.save()
        result = process_due_reminders(
            at=self.followup.scheduled_date + timedelta(days=4)
        )
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["skipped"], 4)
        self.assertEqual(result["simulated"], 0)
        self.assertFalse(self.voice_adapter.return_value.invoke.called)
        self.assertFalse(
            CommunicationAttempt.objects.exclude(
                outcome=CommunicationAttempt.Outcome.SKIPPED
            ).exists()
        )
        self.followup.refresh_from_db()
        self.assertTrue(self.followup.attention_required)

    def test_automatic_overdue_followup_does_not_notify_a_vendor(self):
        other_patient = make_patient("08050675449", vendor=self.scheduler)
        automatic = save_measurement(other_patient, self.scheduler).next_followup
        process_due_reminders(at=automatic.scheduled_date + timedelta(days=1))
        self.assertFalse(
            VendorNotification.objects.filter(followup=automatic).exists()
        )

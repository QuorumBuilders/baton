from importlib import import_module

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from patients.models import ReminderSchedule

from .helpers import make_patient, make_vendor
from .test_access_and_measurements import save_measurement


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PhaseThreeReminderTransitionTests(TestCase):
    def setUp(self):
        vendor = make_vendor()
        self.patient = make_patient(vendor=vendor)
        self.followup = save_measurement(self.patient, vendor).next_followup
        self.migration = import_module("patients.migrations.0004_prepare_voice_reminders")

    def test_pending_sms_is_replaced_by_voice_and_original_records_are_preserved(self):
        self.followup.reminders.update(channel="sms")
        original_ids = set(self.followup.reminders.values_list("pk", flat=True))
        # Run the data operation without entering schema_editor; no DDL is used.
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertEqual(self.followup.reminders.filter(channel="voice", processing_status="pending").count(), 5)
        self.assertEqual(self.followup.reminders.filter(pk__in=original_ids, channel="sms", processing_status="cancelled").count(), 5)
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertEqual(self.followup.reminders.count(), 10)

    def test_existing_voice_rows_are_not_duplicated_when_both_channels_exist(self):
        for reminder in list(self.followup.reminders.all()):
            ReminderSchedule.objects.create(
                followup=self.followup, patient=self.patient, event=reminder.event,
                category=reminder.category, scheduled_for=reminder.scheduled_for, channel="sms",
            )
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertEqual(self.followup.reminders.filter(channel="voice").count(), 5)
        self.assertFalse(self.followup.reminders.filter(channel="sms", processing_status="pending").exists())

    def test_followup_previously_without_consent_gains_voice_business_schedules(self):
        self.followup.reminders.all().delete()
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertEqual(self.followup.reminders.filter(channel="voice").count(), 5)

    def test_processed_events_are_not_replayed_and_fulfilled_followups_are_not_backfilled(self):
        self.followup.reminders.update(channel="sms", processing_status="processed")
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertFalse(self.followup.reminders.filter(channel="voice").exists())
        vendor = self.followup.scheduled_by
        save_measurement(self.patient, vendor)
        self.followup.reminders.all().delete()
        self.migration.prepare_voice_reminders(apps, connection.schema_editor())
        self.assertFalse(self.followup.reminders.exists())

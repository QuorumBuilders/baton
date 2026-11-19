"""Preserve Phase 3 history and prepare outstanding events for voice processing."""

from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


def prepare_voice_reminders(apps, schema_editor):
    FollowUp = apps.get_model("patients", "FollowUp")
    Reminder = apps.get_model("patients", "ReminderSchedule")
    database = schema_editor.connection.alias
    now = timezone.now()

    for followup in FollowUp.objects.using(database).filter(status="active").select_related("source_measurement"):
        rows = Reminder.objects.using(database).filter(
            followup=followup, schedule_revision=followup.schedule_revision,
        )
        measured_date = timezone.localdate(followup.source_measurement.measured_at)
        interval = (followup.scheduled_date - measured_date).days
        # Freeze the established Phase 3 timing for the one-time data transition.
        offsets = [] if interval <= 1 else (
            [max(1, interval // 2)] if interval < 21 else [interval // 3, 2 * interval // 3]
        )
        events = [
            (event, "medication_health", measured_date + timedelta(days=offset))
            for event, offset in zip(("health_first", "health_second"), offsets)
        ] + [
            (event, "visit", followup.scheduled_date + timedelta(days=offset))
            for event, offset in (("visit_due", 0), ("overdue_first", 2), ("overdue_final", 4))
        ]
        for event, category, day in events:
            if rows.filter(event=event, channel="voice").exists():
                continue
            # Never replay events processed or cancelled before the upgrade.
            if rows.filter(event=event).exclude(processing_status="pending").exists():
                continue
            if followup.attention_required:
                continue
            previous = rows.filter(event=event, channel="sms", processing_status="pending").first()
            Reminder.objects.using(database).create(
                followup=followup,
                patient_id=followup.patient_id,
                schedule_revision=followup.schedule_revision,
                category=category,
                event=event,
                channel="voice",
                scheduled_for=previous.scheduled_for if previous else timezone.make_aware(datetime.combine(day, time.min)),
            )

    # Retain old SMS records for audit, with no routine SMS transport invocation.
    Reminder.objects.using(database).filter(channel="sms", processing_status="pending").update(
        processing_status="cancelled", processed_at=now,
    )


class Migration(migrations.Migration):
    dependencies = [("patients", "0003_alter_patient_preferred_language_and_more")]
    operations = [migrations.RunPython(prepare_voice_reminders, migrations.RunPython.noop)]

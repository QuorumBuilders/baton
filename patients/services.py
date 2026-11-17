"""Patient registration and transactional patient-level monitoring coordination."""

from datetime import date, datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import PhoneVerification
from accounts.phone_numbers import normalize_mobile_number
from accounts.services import VerificationError, get_verified_registration

from .models import (
    BloodPressureMeasurement,
    FollowUp,
    FollowUpRule,
    FollowUpScheduleChange,
    Patient,
    ReminderSchedule,
    VendorNotification,
    VendorPatient,
)


class SchedulingUnavailable(ValidationError):
    pass


class ReviewChanged(ValidationError):
    pass


def require_vendor(vendor):
    if not vendor.is_active or vendor.account_type != "vendor" or vendor.is_staff or vendor.is_superuser:
        raise PermissionDenied


def complete_patient_registration(vendor, verification_id, phone_number, details):
    require_vendor(vendor)
    phone_number = normalize_mobile_number(phone_number)
    with transaction.atomic():
        verification = get_verified_registration(
            verification_id, phone_number, purpose="patient"
        )
        now = timezone.now()
        claimed = PhoneVerification.objects.filter(
            pk=verification.pk,
            purpose="patient",
            phone_number=phone_number,
            consumed_at__isnull=False,
            completed_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=now,
        ).update(completed_at=now)
        if claimed != 1:
            raise VerificationError("Patient phone verification is unavailable.")
        patient = Patient.objects.create(
            phone_number=phone_number,
            sms_consent_recorded_at=now,
            voice_consent_recorded_at=now,
            **details,
        )
        VendorPatient.objects.create(patient=patient, vendor=vendor)
    return patient


def associate_existing_patient(vendor, patient, *, patient_agreed):
    require_vendor(vendor)
    if patient_agreed is not True:
        raise ValidationError("Confirm the patient's agreement before sharing records.")
    with transaction.atomic():
        association, created = VendorPatient.objects.get_or_create(
            vendor=vendor,
            patient=patient,
            defaults={
                "sharing_confirmed_at": timezone.now(),
                "confirmation_recorded_by": vendor,
            },
        )
    return association, created


def automatic_proposal(*, measured_at=None):
    rule = FollowUpRule.objects.filter(is_active=True).first()
    proposed_date = None
    if rule:
        try:
            proposed_date = timezone.localdate(measured_at or timezone.now()) + timedelta(
                days=rule.interval_days
            )
        except OverflowError:
            raise SchedulingUnavailable(
                "The configured interval exceeds the supported calendar. "
                "Ask an administrator to configure a valid rule."
            ) from None
    return rule, proposed_date


def proposal_snapshot(rule, proposed_date):
    return {
        "rule_id": rule.pk if rule else None,
        "date": proposed_date.isoformat() if proposed_date else None,
    }


def _scheduled_for(day):
    return timezone.make_aware(
        datetime.combine(day, time.min), timezone.get_current_timezone()
    )


def medication_health_offsets(interval_days):
    """Return reminder-day offsets; 21 days is the short/long interval boundary."""
    if interval_days <= 1:
        return []
    if interval_days < 21:
        return [max(1, interval_days // 2)]
    return sorted(
        {
            offset
            for offset in (interval_days // 3, (interval_days * 2) // 3)
            if 0 < offset < interval_days
        }
    )


def create_reminder_schedules(followup):
    """Create provider-independent reminder rows for one follow-up revision."""
    patient = followup.patient
    channels = []
    if patient.sms_consent:
        channels.append(ReminderSchedule.Channel.SMS)
    if patient.voice_consent:
        channels.append(ReminderSchedule.Channel.VOICE)
    if not channels:
        return []

    measured_date = timezone.localdate(followup.source_measurement.measured_at)
    interval_days = (followup.scheduled_date - measured_date).days
    events = []
    health_events = (
        ReminderSchedule.Event.HEALTH_FIRST,
        ReminderSchedule.Event.HEALTH_SECOND,
    )
    for event, offset in zip(health_events, medication_health_offsets(interval_days)):
        events.append(
            (
                ReminderSchedule.Category.MEDICATION_HEALTH,
                event,
                measured_date + timedelta(days=offset),
            )
        )
    events.extend(
        (
            ReminderSchedule.Category.VISIT,
            event,
            followup.scheduled_date + timedelta(days=offset),
        )
        for event, offset in (
            (ReminderSchedule.Event.VISIT_DUE, 0),
            (ReminderSchedule.Event.OVERDUE_FIRST, 2),
            (ReminderSchedule.Event.OVERDUE_FINAL, 4),
        )
    )

    created = []
    for category, event, scheduled_date in events:
        for channel in channels:
            reminder, was_created = ReminderSchedule.objects.get_or_create(
                followup=followup,
                schedule_revision=followup.schedule_revision,
                event=event,
                channel=channel,
                defaults={
                    "patient": patient,
                    "category": category,
                    "scheduled_for": _scheduled_for(scheduled_date),
                },
            )
            if was_created:
                created.append(reminder)
    return created


def cancel_outstanding_reminders(followup, *, cancelled_at=None):
    return followup.reminders.filter(
        processing_status=ReminderSchedule.ProcessingStatus.PENDING
    ).update(
        processing_status=ReminderSchedule.ProcessingStatus.CANCELLED,
        processed_at=cancelled_at or timezone.now(),
    )


def record_measurement(
    *, patient_id, vendor, values, operation_id, expected_proposal, manual_date=None
):
    require_vendor(vendor)
    # IMMEDIATE transactions serialize SQLite writers before the first read;
    # select_for_update also protects this service on databases with row locks.
    with transaction.atomic():
        patient = Patient.objects.select_for_update().get(pk=patient_id)
        if not VendorPatient.objects.filter(patient=patient, vendor=vendor).exists():
            raise PermissionDenied
        previous = BloodPressureMeasurement.objects.filter(operation_id=operation_id).first()
        if previous:
            if previous.patient_id != patient.pk or previous.recording_vendor_id != vendor.pk:
                raise PermissionDenied
            return previous
        measured_at = timezone.now()
        rule, proposed_date = automatic_proposal(measured_at=measured_at)
        if expected_proposal != proposal_snapshot(rule, proposed_date):
            raise ReviewChanged(
                "The scheduling configuration or date has changed. "
                "Review the updated proposal before saving."
            )
        if manual_date is None and proposed_date is None:
            raise SchedulingUnavailable(
                "No approved automatic rule is configured. Specify a manual follow-up date."
            )
        if manual_date is not None and manual_date < timezone.localdate(measured_at):
            raise ValidationError("The next follow-up date cannot be in the past.")
        automatic = manual_date is None or manual_date == proposed_date
        measurement = BloodPressureMeasurement.objects.create(
            patient=patient,
            recording_vendor=vendor,
            measured_at=measured_at,
            operation_id=operation_id,
            **values,
        )
        active = (
            FollowUp.objects.select_for_update()
            .filter(patient=patient, status=FollowUp.Status.ACTIVE)
            .first()
        )
        if active:
            FollowUp.objects.filter(
                pk=active.pk, status=FollowUp.Status.ACTIVE
            ).update(
                status=FollowUp.Status.FULFILLED,
                actual_fulfilment_at=measured_at,
                fulfilled_by_measurement=measurement,
            )
            cancel_outstanding_reminders(active, cancelled_at=measured_at)
        followup = FollowUp.objects.create(
            patient=patient,
            scheduled_date=proposed_date if automatic else manual_date,
            followup_type=(
                FollowUp.Type.AUTOMATIC if automatic else FollowUp.Type.MANUAL
            ),
            scheduling_rule=rule if automatic else None,
            scheduled_by=vendor,
            source_measurement=measurement,
        )
        create_reminder_schedules(followup)
        return measurement


def reschedule_active_followup(*, followup_id, vendor, scheduled_date):
    require_vendor(vendor)
    if scheduled_date < timezone.localdate():
        raise ValidationError("The next follow-up date cannot be in the past.")
    with transaction.atomic():
        followup = FollowUp.objects.select_for_update().select_related(
            "patient", "source_measurement"
        ).get(pk=followup_id)
        if followup.status != FollowUp.Status.ACTIVE:
            raise ValidationError("Only the active follow-up can be rescheduled.")
        if not VendorPatient.objects.filter(
            patient=followup.patient, vendor=vendor
        ).exists():
            raise PermissionDenied
        previous_date = followup.scheduled_date
        cancel_outstanding_reminders(followup)
        followup.scheduled_date = scheduled_date
        followup.followup_type = FollowUp.Type.MANUAL
        followup.scheduling_rule = None
        followup.scheduled_by = vendor
        followup.schedule_revision += 1
        followup.attention_required = False
        followup.attention_flagged_at = None
        followup.save(
            update_fields=[
                "scheduled_date",
                "followup_type",
                "scheduling_rule",
                "scheduled_by",
                "schedule_revision",
                "attention_required",
                "attention_flagged_at",
            ]
        )
        FollowUpScheduleChange.objects.create(
            followup=followup,
            previous_scheduled_date=previous_date,
            scheduled_date=scheduled_date,
            changed_by=vendor,
        )
        create_reminder_schedules(followup)
        return followup


def _processing_time(value):
    if value is None:
        return timezone.now()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    if isinstance(value, date):
        return timezone.make_aware(
            datetime.combine(value, time.max), timezone.get_current_timezone()
        )
    raise TypeError("Process time must be a date or datetime.")


def process_due_reminders(*, at=None):
    """Mark due schedules processed without sending through an external provider."""
    processed_at = _processing_time(at)
    local_date = timezone.localdate(processed_at)
    processed = 0
    cancelled = 0
    notified = 0
    with transaction.atomic():
        overdue_manual = FollowUp.objects.select_for_update().filter(
            status=FollowUp.Status.ACTIVE,
            followup_type=FollowUp.Type.MANUAL,
            scheduled_date__lt=local_date,
        )
        for followup in overdue_manual:
            _, created = VendorNotification.objects.get_or_create(
                followup=followup,
                schedule_revision=followup.schedule_revision,
                defaults={
                    "patient": followup.patient,
                    "vendor": followup.scheduled_by,
                },
            )
            notified += int(created)

        reminders = list(
            ReminderSchedule.objects.select_for_update()
            .select_related("patient", "followup")
            .filter(
                processing_status=ReminderSchedule.ProcessingStatus.PENDING,
                scheduled_for__lte=processed_at,
                followup__status=FollowUp.Status.ACTIVE,
                schedule_revision=models.F("followup__schedule_revision"),
            )
            .order_by("scheduled_for", "id")
        )
        for reminder in reminders:
            has_consent = (
                reminder.channel == ReminderSchedule.Channel.SMS
                and reminder.patient.sms_consent
            ) or (
                reminder.channel == ReminderSchedule.Channel.VOICE
                and reminder.patient.voice_consent
            )
            if has_consent:
                reminder.processing_status = ReminderSchedule.ProcessingStatus.PROCESSED
                processed += 1
            else:
                reminder.processing_status = ReminderSchedule.ProcessingStatus.CANCELLED
                cancelled += 1
            reminder.processed_at = processed_at
            reminder.save(update_fields=["processing_status", "processed_at"])

        flagged = FollowUp.objects.filter(
            status=FollowUp.Status.ACTIVE,
            scheduled_date__lte=local_date - timedelta(days=4),
            attention_required=False,
        ).update(attention_required=True, attention_flagged_at=processed_at)
    return {
        "processed": processed,
        "cancelled": cancelled,
        "vendor_notifications": notified,
        "attention_flags": flagged,
    }


def due_reminder_schedules(*, at=None):
    """Return due, active schedules without changing or delivering them."""
    process_time = _processing_time(at)
    return ReminderSchedule.objects.filter(
        processing_status=ReminderSchedule.ProcessingStatus.PENDING,
        scheduled_for__lte=process_time,
        followup__status=FollowUp.Status.ACTIVE,
        schedule_revision=models.F("followup__schedule_revision"),
    ).select_related("followup__patient")

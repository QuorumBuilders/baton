import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.phone_numbers import local_phone_number, normalize_mobile_number


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=16, unique=True)
    date_of_birth = models.DateField()
    sex = models.CharField(max_length=30, blank=True)
    preferred_language = models.CharField(max_length=80)
    sms_consent = models.BooleanField(default=False)
    sms_consent_recorded_at = models.DateTimeField()
    voice_consent = models.BooleanField(default=False)
    voice_consent_recorded_at = models.DateTimeField()
    alternative_contact_number = models.CharField(max_length=16, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    vendors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="VendorPatient",
        through_fields=("patient", "vendor"),
        related_name="patients",
    )

    class Meta:
        ordering = ["last_name", "first_name", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(phone_number__regex=r"^\+234[1-9][0-9]{9}$"), name="patient_phone_canonical"),
            models.CheckConstraint(condition=Q(alternative_contact_number="") | Q(alternative_contact_number__regex=r"^\+234[1-9][0-9]{9}$"), name="patient_alt_phone_canonical"),
            models.CheckConstraint(condition=~Q(first_name__regex=r"^\s*$") & ~Q(last_name__regex=r"^\s*$") & ~Q(preferred_language__regex=r"^\s*$"), name="patient_required_text"),
        ]

    @property
    def local_phone(self):
        return local_phone_number(self.phone_number)

    @property
    def local_alternative_phone(self):
        return local_phone_number(self.alternative_contact_number)

    def clean_fields(self, exclude=None):
        for field in ("first_name", "last_name", "sex", "preferred_language"):
            setattr(self, field, (getattr(self, field) or "").strip())
        for field in ("phone_number", "alternative_contact_number"):
            value = getattr(self, field)
            if value:
                try:
                    setattr(self, field, normalize_mobile_number(value))
                except ValidationError as error:
                    raise ValidationError({field: error}) from error
        super().clean_fields(exclude=exclude)

    def clean(self):
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError({"date_of_birth": "Date of birth cannot be in the future."})

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self._state.adding:
            self.sms_consent_recorded_at = self.sms_consent_recorded_at or now
            self.voice_consent_recorded_at = self.voice_consent_recorded_at or now
        else:
            previous = type(self).objects.get(pk=self.pk)
            if previous.sms_consent != self.sms_consent:
                self.sms_consent_recorded_at = now
            if previous.voice_consent != self.voice_consent:
                self.voice_consent_recorded_at = now
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class VendorPatient(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="associations")
    vendor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="patient_associations", limit_choices_to={"account_type": "vendor"})
    created_at = models.DateTimeField(auto_now_add=True)
    sharing_confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="recorded_patient_confirmations", limit_choices_to={"account_type": "vendor"})

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "vendor"], name="unique_vendor_patient"),
            models.CheckConstraint(condition=Q(sharing_confirmed_at__isnull=True, confirmation_recorded_by__isnull=True) | Q(sharing_confirmed_at__isnull=False, confirmation_recorded_by__isnull=False), name="sharing_confirmation_audited"),
        ]

    def clean(self):
        if self.vendor_id and self.vendor.account_type != "vendor":
            raise ValidationError({"vendor": "Select a vendor account."})
        if self.confirmation_recorded_by_id and self.confirmation_recorded_by_id != self.vendor_id:
            raise ValidationError({"confirmation_recorded_by": "The new vendor must record the confirmation."})

    def __str__(self):
        return f"{self.patient} — {self.vendor}"


class FollowUpRule(models.Model):
    """A versioned administrator-configured interval for automatic follow-ups."""
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=40)
    interval_days = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="followup_rule_version_unique"),
            models.UniqueConstraint(fields=["is_active"], condition=Q(is_active=True), name="one_active_followup_rule"),
            models.CheckConstraint(condition=Q(interval_days__gte=1), name="followup_rule_positive_interval"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if any(getattr(previous, field) != getattr(self, field) for field in ("name", "version", "interval_days")):
                raise ValidationError("Create a new rule version instead of changing an existing rule.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.version})"


class MeasurementQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Saved measurements cannot be edited.")

    def delete(self):
        raise ValidationError("Saved measurements cannot be deleted.")


class BloodPressureMeasurement(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="measurements")
    recording_vendor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="measurements", limit_choices_to={"account_type": "vendor"})
    systolic = models.PositiveSmallIntegerField("Systolic pressure (mmHg)", validators=[MinValueValidator(1)])
    diastolic = models.PositiveSmallIntegerField("Diastolic pressure (mmHg)", validators=[MinValueValidator(1)])
    pulse = models.PositiveSmallIntegerField("Pulse rate (beats per minute)", null=True, blank=True, validators=[MinValueValidator(1)])
    measured_at = models.DateTimeField(default=timezone.now, editable=False)
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    objects = MeasurementQuerySet.as_manager()

    class Meta:
        ordering = ["-measured_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(systolic__gte=1, diastolic__gte=1), name="bp_positive_values"),
            models.CheckConstraint(condition=Q(pulse__isnull=True) | Q(pulse__gte=1), name="bp_positive_pulse"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Saved measurements cannot be edited.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Saved measurements cannot be deleted.")

    def __str__(self):
        return f"{self.systolic}/{self.diastolic} mmHg"


class FollowUp(models.Model):
    class Type(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTOMATIC = "automatic", "Automatic"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FULFILLED = "fulfilled", "Fulfilled"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="followups")
    scheduled_date = models.DateField()
    actual_fulfilment_at = models.DateTimeField(null=True, blank=True)
    followup_type = models.CharField(max_length=9, choices=Type.choices)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="scheduled_followups")
    source_measurement = models.OneToOneField(BloodPressureMeasurement, on_delete=models.PROTECT, related_name="next_followup")
    fulfilled_by_measurement = models.OneToOneField(BloodPressureMeasurement, on_delete=models.PROTECT, related_name="fulfilled_followup", null=True, blank=True)
    scheduling_rule = models.ForeignKey(FollowUpRule, on_delete=models.PROTECT, null=True, blank=True, related_name="followups")
    schedule_revision = models.PositiveIntegerField(default=1)
    attention_required = models.BooleanField(default=False)
    attention_flagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["patient"], condition=Q(status="active"), name="one_active_patient_followup"),
            models.CheckConstraint(condition=Q(status="active", actual_fulfilment_at__isnull=True, fulfilled_by_measurement__isnull=True) | Q(status="fulfilled", actual_fulfilment_at__isnull=False, fulfilled_by_measurement__isnull=False), name="followup_fulfilment_consistent"),
            models.CheckConstraint(condition=Q(followup_type="automatic", scheduling_rule__isnull=False) | Q(followup_type="manual", scheduling_rule__isnull=True), name="followup_rule_required_for_auto"),
            models.CheckConstraint(condition=Q(attention_required=False, attention_flagged_at__isnull=True) | Q(attention_required=True, attention_flagged_at__isnull=False), name="followup_attention_consistent"),
        ]

    def __str__(self):
        return f"{self.patient}: {self.scheduled_date} ({self.status})"


class FollowUpScheduleChange(models.Model):
    followup = models.ForeignKey(FollowUp, on_delete=models.PROTECT, related_name="schedule_changes")
    previous_scheduled_date = models.DateField()
    scheduled_date = models.DateField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="followup_schedule_changes",
        limit_choices_to={"account_type": "vendor"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.followup}: {self.previous_scheduled_date} to {self.scheduled_date}"


class ReminderSchedule(models.Model):
    class Category(models.TextChoices):
        VISIT = "visit", "Visit reminder"
        MEDICATION_HEALTH = "medication_health", "Medication and health reminder"

    class Event(models.TextChoices):
        HEALTH_FIRST = "health_first", "First medication and health reminder"
        HEALTH_SECOND = "health_second", "Second medication and health reminder"
        VISIT_DUE = "visit_due", "Follow-up date reminder"
        OVERDUE_FIRST = "overdue_first", "First overdue reminder"
        OVERDUE_FINAL = "overdue_final", "Final overdue reminder"

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        VOICE = "voice", "Voice call"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        CANCELLED = "cancelled", "Cancelled"

    class DeliveryStatus(models.TextChoices):
        NOT_ATTEMPTED = "not_attempted", "Not attempted"
        PENDING = "pending", "Pending provider delivery"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="reminder_schedules")
    followup = models.ForeignKey(FollowUp, on_delete=models.PROTECT, related_name="reminders")
    category = models.CharField(max_length=20, choices=Category.choices)
    event = models.CharField(max_length=20, choices=Event.choices)
    channel = models.CharField(max_length=5, choices=Channel.choices)
    schedule_revision = models.PositiveIntegerField(default=1)
    scheduled_for = models.DateTimeField(db_index=True)
    processing_status = models.CharField(
        max_length=9, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING
    )
    delivery_status = models.CharField(
        max_length=13, choices=DeliveryStatus.choices, default=DeliveryStatus.NOT_ATTEMPTED
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_for", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["followup", "schedule_revision", "event", "channel"],
                name="one_reminder_event_per_revision_channel",
            ),
        ]

    def clean(self):
        health_events = {self.Event.HEALTH_FIRST, self.Event.HEALTH_SECOND}
        expected_category = (
            self.Category.MEDICATION_HEALTH if self.event in health_events else self.Category.VISIT
        )
        if self.category and self.category != expected_category:
            raise ValidationError({"category": "The reminder category does not match its event."})
        if self.followup_id and self.patient_id != self.followup.patient_id:
            raise ValidationError({"patient": "The reminder patient must match the follow-up patient."})

    def __str__(self):
        return f"{self.get_event_display()} for {self.patient}"


class VendorNotification(models.Model):
    followup = models.ForeignKey(FollowUp, on_delete=models.PROTECT, related_name="vendor_notifications")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="vendor_notifications")
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="patient_notifications",
        limit_choices_to={"account_type": "vendor"},
    )
    schedule_revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["followup", "schedule_revision"],
                name="one_vendor_notification_per_followup_revision",
            ),
        ]

    def clean(self):
        if self.followup_id and self.patient_id != self.followup.patient_id:
            raise ValidationError({"patient": "The notification patient must match the follow-up patient."})
        if self.followup_id and self.vendor_id != self.followup.scheduled_by_id:
            raise ValidationError({"vendor": "Notify the vendor responsible for the manual follow-up."})

    def __str__(self):
        return f"Overdue manual follow-up for {self.patient}"

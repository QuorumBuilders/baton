from django.contrib import admin, messages

from .models import (
    BloodPressureMeasurement,
    CommunicationAttempt,
    FollowUp,
    FollowUpRule,
    FollowUpScheduleChange,
    Patient,
    ReminderSchedule,
    VendorNotification,
    VendorPatient,
)
from .services import process_due_reminders


class ReadOnlyHistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "first_name",
        "last_name",
        "local_phone",
        "preferred_language",
        "registered_at",
    )
    search_fields = ("id", "first_name", "last_name", "phone_number")
    list_filter = ("sms_consent", "voice_consent", "preferred_language")
    readonly_fields = ("id", "registered_at")


@admin.register(VendorPatient)
class VendorPatientAdmin(admin.ModelAdmin):
    list_display = ("patient", "vendor", "created_at", "sharing_confirmed_at")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__phone_number",
        "vendor__business_name",
        "vendor__phone_number",
    )
    list_filter = ("created_at", "sharing_confirmed_at")
    readonly_fields = ("created_at",)


@admin.register(BloodPressureMeasurement)
class BloodPressureMeasurementAdmin(ReadOnlyHistoryAdmin):
    list_display = (
        "patient",
        "systolic",
        "diastolic",
        "pulse",
        "measured_at",
        "recording_vendor",
    )
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__phone_number",
        "recording_vendor__business_name",
    )
    list_filter = ("measured_at",)


@admin.register(FollowUp)
class FollowUpAdmin(ReadOnlyHistoryAdmin):
    list_display = (
        "patient",
        "scheduled_date",
        "followup_type",
        "status",
        "scheduled_by",
        "attention_required",
    )
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__phone_number",
        "scheduled_by__business_name",
    )
    list_filter = ("followup_type", "status", "attention_required", "scheduled_date")


@admin.register(FollowUpRule)
class FollowUpRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "interval_days", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "version")
    readonly_fields = ("created_at",)


@admin.register(FollowUpScheduleChange)
class FollowUpScheduleChangeAdmin(ReadOnlyHistoryAdmin):
    list_display = (
        "followup",
        "previous_scheduled_date",
        "scheduled_date",
        "changed_by",
        "created_at",
    )
    search_fields = (
        "followup__patient__first_name",
        "followup__patient__last_name",
        "changed_by__business_name",
    )


@admin.action(
    description="Process all due reminder schedules now (development delivery is simulated)",
    permissions=["view"],
)
def process_due_reminder_schedules(modeladmin, request, queryset):
    result = process_due_reminders()
    modeladmin.message_user(
        request,
        (
            f"Processed {result['processed']} reminder(s): {result['simulated']} simulated, "
            f"{result['delivered']} delivered, {result['skipped']} skipped and "
            f"{result['failed']} failed. Created {result['vendor_notifications']} vendor "
            f"notification(s) and added {result['attention_flags']} attention flag(s)."
        ),
        level=messages.WARNING if result["failed"] else messages.SUCCESS,
    )


@admin.register(ReminderSchedule)
class ReminderScheduleAdmin(ReadOnlyHistoryAdmin):
    list_display = (
        "patient",
        "category",
        "event",
        "channel",
        "scheduled_for",
        "processing_status",
        "delivery_status",
    )
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__phone_number",
        "idempotency_key",
    )
    list_filter = (
        "category",
        "event",
        "channel",
        "processing_status",
        "delivery_status",
    )
    actions = (process_due_reminder_schedules,)


@admin.register(VendorNotification)
class VendorNotificationAdmin(ReadOnlyHistoryAdmin):
    list_display = ("vendor", "patient", "followup", "schedule_revision", "created_at")
    search_fields = (
        "vendor__business_name",
        "vendor__phone_number",
        "patient__first_name",
        "patient__last_name",
    )


@admin.register(CommunicationAttempt)
class CommunicationAttemptAdmin(ReadOnlyHistoryAdmin):
    list_display = (
        "reminder",
        "channel",
        "category",
        "outcome",
        "delivery_mode",
        "attempted_at",
    )
    list_filter = ("channel", "category", "outcome", "delivery_mode")
    search_fields = (
        "reminder__idempotency_key",
        "recipient",
        "provider_reference",
        "recording_reference",
    )

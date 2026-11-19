from django import forms
from django.utils import timezone

from accounts.forms import PhoneNumberField
from .models import Patient


class PatientLookupForm(forms.Form):
    phone_number = PhoneNumberField(mobile_only=True)


class PatientRegistrationForm(forms.Form):
    processing_agreed = forms.BooleanField(
        label="I confirm that the patient agrees to Baton collecting and using their details and health records for record-keeping and follow-up coordination, with access by my vendor account.",
        help_text="Explain the patient privacy notice before collecting details. They can withdraw agreement through an associated vendor or the project contact. If they decline, do not submit a record. This is separate from SMS and voice choices.",
    )
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    sex = forms.CharField(max_length=30, required=False)
    preferred_language = forms.ChoiceField(
        choices=Patient.PreferredLanguage.choices,
        help_text="Voice reminders are available in English and Nigerian Pidgin.",
    )
    sms_consent = forms.TypedChoiceField(
        label="Has the patient explicitly agreed to SMS communications?",
        choices=[("yes", "Yes"), ("no", "No")], coerce=lambda value: value == "yes",
        widget=forms.RadioSelect,
        help_text="Optional routine text communications; no routine SMS reminder workflow currently runs. OTP verification is separate. The patient can withdraw through an associated vendor or the project contact.",
    )
    voice_consent = forms.TypedChoiceField(
        label="Has the patient explicitly agreed to voice call reminders?",
        choices=[("yes", "Yes"), ("no", "No")], coerce=lambda value: value == "yes",
        widget=forms.RadioSelect,
        help_text="Optional visit, overdue, medication and general-health reminders. Calls are currently simulated. The patient can withdraw through an associated vendor or the project contact.",
    )
    alternative_contact_number = PhoneNumberField(mobile_only=True, required=False, label="Alternative contact number (optional)")

    def clean_date_of_birth(self):
        value = self.cleaned_data["date_of_birth"]
        if value > timezone.localdate():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return value

    def clean_alternative_contact_number(self):
        return self.cleaned_data["alternative_contact_number"] or ""


class AssociationConfirmationForm(forms.Form):
    patient_agreed = forms.BooleanField(
        label="I confirm that the patient has agreed to be added to my patient list and to share their relevant health history with me."
    )


class CommunicationWithdrawalForm(forms.Form):
    withdraw_sms = forms.BooleanField(required=False, label="The patient asks to stop routine SMS communications")
    withdraw_voice = forms.BooleanField(required=False, label="The patient asks to stop voice call reminders")

    def clean(self):
        data = super().clean()
        if not data.get("withdraw_sms") and not data.get("withdraw_voice"):
            raise forms.ValidationError("Select at least one channel the patient wants to stop.")
        return data


class MeasurementForm(forms.Form):
    # Positive whole numbers only; the upper bound is the storage type's limit,
    # not a clinical threshold or interpretation.
    systolic = forms.IntegerField(label="Systolic pressure (mmHg)", min_value=1, max_value=32767)
    diastolic = forms.IntegerField(label="Diastolic pressure (mmHg)", min_value=1, max_value=32767)
    pulse = forms.IntegerField(label="Pulse rate (beats per minute, optional)", required=False, min_value=1, max_value=32767)


class FollowUpSelectionForm(forms.Form):
    choice = forms.ChoiceField(label="Next follow-up", choices=[("automatic", "Accept proposed date"), ("manual", "Specify a date")], widget=forms.RadioSelect)
    scheduled_date = forms.DateField(label="Your follow-up date", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, automatic_date=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.automatic_date = automatic_date
        if automatic_date is None:
            self.fields["choice"].choices = [("manual", "Specify a date")]
            self.initial["choice"] = "manual"
        else:
            self.initial["choice"] = "automatic"

    def clean(self):
        data = super().clean()
        if data.get("choice") == "automatic" and self.automatic_date is None:
            self.add_error("choice", "Automatic scheduling is unavailable. Specify a date.")
        if data.get("choice") == "manual":
            value = data.get("scheduled_date")
            if value is None:
                self.add_error("scheduled_date", "Specify the next follow-up date.")
            elif value < timezone.localdate():
                self.add_error("scheduled_date", "The next follow-up date cannot be in the past.")
        return data


class FollowUpRescheduleForm(forms.Form):
    scheduled_date = forms.DateField(
        label="New follow-up date", widget=forms.DateInput(attrs={"type": "date"})
    )

    def clean_scheduled_date(self):
        value = self.cleaned_data["scheduled_date"]
        if value < timezone.localdate():
            raise forms.ValidationError("The next follow-up date cannot be in the past.")
        return value

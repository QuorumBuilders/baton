from datetime import date

from django.utils import timezone

from accounts.models import User
from patients.models import Patient, VendorPatient


def make_vendor(phone_number="08012345678", business_name="Community Pharmacy"):
    return User.objects.create_user(
        phone_number=phone_number,
        business_name=business_name,
        password="482953",
    )


def make_patient(
    phone_number="08050675448",
    *,
    vendor=None,
    sms_consent=True,
    voice_consent=False,
):
    now = timezone.now()
    patient = Patient.objects.create(
        first_name="Ada",
        last_name="Okafor",
        phone_number=phone_number,
        date_of_birth=date(1980, 5, 12),
        sex="Female",
        preferred_language="English",
        sms_consent=sms_consent,
        sms_consent_recorded_at=now,
        voice_consent=voice_consent,
        voice_consent_recorded_at=now,
        alternative_contact_number="",
    )
    if vendor:
        VendorPatient.objects.create(patient=patient, vendor=vendor)
    return patient

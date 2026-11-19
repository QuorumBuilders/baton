from dataclasses import dataclass
from enum import StrEnum

from .payloads import SMSMessage


class ContentUnavailable(ValueError):
    pass


class VoiceCategory(StrEnum):
    SCHEDULED_VISIT = "scheduled_visit"
    FIRST_OVERDUE = "first_overdue"
    FINAL_OVERDUE = "final_overdue"
    MEDICATION = "medication"
    GENERAL_HEALTH = "general_health"


class VoiceLanguage(StrEnum):
    ENGLISH = "english"
    NIGERIAN_PIDGIN = "nigerian_pidgin"


@dataclass(frozen=True)
class VoiceContent:
    category: VoiceCategory
    language: VoiceLanguage
    recording_reference: str
    approved_script: str


_VOICE_CONTENT = {
    (VoiceCategory.SCHEDULED_VISIT, VoiceLanguage.ENGLISH): VoiceContent(
        VoiceCategory.SCHEDULED_VISIT,
        VoiceLanguage.ENGLISH,
        "recordings/en/scheduled-visit-v1.mp3",
        "This is a reminder that your Baton follow-up visit is due. Please follow the instructions given by your healthcare professional.",
    ),
    (VoiceCategory.SCHEDULED_VISIT, VoiceLanguage.NIGERIAN_PIDGIN): VoiceContent(
        VoiceCategory.SCHEDULED_VISIT,
        VoiceLanguage.NIGERIAN_PIDGIN,
        "recordings/pcm/scheduled-visit-v1.mp3",
        "This na reminder say your Baton follow-up visit don reach. Abeg follow the instructions wey your healthcare professional give you.",
    ),
    (VoiceCategory.FIRST_OVERDUE, VoiceLanguage.ENGLISH): VoiceContent(
        VoiceCategory.FIRST_OVERDUE,
        VoiceLanguage.ENGLISH,
        "recordings/en/first-overdue-v1.mp3",
        "Your Baton follow-up visit is overdue. Please contact or visit your healthcare provider.",
    ),
    (VoiceCategory.FIRST_OVERDUE, VoiceLanguage.NIGERIAN_PIDGIN): VoiceContent(
        VoiceCategory.FIRST_OVERDUE,
        VoiceLanguage.NIGERIAN_PIDGIN,
        "recordings/pcm/first-overdue-v1.mp3",
        "Your Baton follow-up visit don pass. Abeg contact or visit your healthcare provider.",
    ),
    (VoiceCategory.FINAL_OVERDUE, VoiceLanguage.ENGLISH): VoiceContent(
        VoiceCategory.FINAL_OVERDUE,
        VoiceLanguage.ENGLISH,
        "recordings/en/final-overdue-v1.mp3",
        "This is the final automated reminder that your Baton follow-up visit is overdue. Please contact your healthcare provider.",
    ),
    (VoiceCategory.FINAL_OVERDUE, VoiceLanguage.NIGERIAN_PIDGIN): VoiceContent(
        VoiceCategory.FINAL_OVERDUE,
        VoiceLanguage.NIGERIAN_PIDGIN,
        "recordings/pcm/final-overdue-v1.mp3",
        "This na the final automatic reminder say your Baton follow-up visit don pass. Abeg contact your healthcare provider.",
    ),
    (VoiceCategory.MEDICATION, VoiceLanguage.ENGLISH): VoiceContent(
        VoiceCategory.MEDICATION,
        VoiceLanguage.ENGLISH,
        "recordings/en/medication-v1.mp3",
        "This is a reminder to take your medication according to the instructions given by your healthcare professional.",
    ),
    (VoiceCategory.MEDICATION, VoiceLanguage.NIGERIAN_PIDGIN): VoiceContent(
        VoiceCategory.MEDICATION,
        VoiceLanguage.NIGERIAN_PIDGIN,
        "recordings/pcm/medication-v1.mp3",
        "This na reminder to take your medicine the way your healthcare professional tell you.",
    ),
    (VoiceCategory.GENERAL_HEALTH, VoiceLanguage.ENGLISH): VoiceContent(
        VoiceCategory.GENERAL_HEALTH,
        VoiceLanguage.ENGLISH,
        "recordings/en/general-health-v1.mp3",
        "Remember to rest, stay hydrated and follow the health instructions given by your healthcare professional.",
    ),
    (VoiceCategory.GENERAL_HEALTH, VoiceLanguage.NIGERIAN_PIDGIN): VoiceContent(
        VoiceCategory.GENERAL_HEALTH,
        VoiceLanguage.NIGERIAN_PIDGIN,
        "recordings/pcm/general-health-v1.mp3",
        "Remember to rest, drink enough water and follow the health instructions wey your healthcare professional give you.",
    ),
}


def resolve_voice_language(value):
    normalized = (value or "").strip().casefold().replace("-", " ").replace("_", " ")
    if normalized in {"english", "en"}:
        return VoiceLanguage.ENGLISH
    if normalized in {"pidgin", "nigerian pidgin", "pcm"}:
        return VoiceLanguage.NIGERIAN_PIDGIN
    raise ContentUnavailable(f"No approved voice recording language is registered for {value!r}.")


def resolve_voice_content(category, preferred_language):
    try:
        category = VoiceCategory(category)
        language = resolve_voice_language(preferred_language)
        return _VOICE_CONTENT[(category, language)]
    except (KeyError, ValueError) as error:
        if isinstance(error, ContentUnavailable):
            raise
        raise ContentUnavailable("No approved voice recording is registered for this reminder.") from error


def otp_sms_message(*, recipient, code, purpose, reference_id):
    if purpose == "vendor":
        category = "vendor_otp"
        subject = "vendor registration"
    elif purpose == "patient":
        category = "patient_otp"
        subject = "patient registration"
    else:
        raise ValueError("Unsupported verification purpose.")
    return SMSMessage(
        recipient=recipient,
        body=(
            f"Your Baton {subject} verification code is {code}. "
            "Do not share this code with anyone."
        ),
        category=category,
        reference_id=str(reference_id),
    )

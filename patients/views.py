import uuid
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from accounts.delivery import DeliveryUnavailable
from accounts.forms import OTPVerificationForm
from accounts.phone_numbers import local_phone_number, normalize_mobile_number
from accounts.services import ResendCooldown, VerificationError, get_verified_registration, issue_otp, verify_otp

from .forms import (
    AssociationConfirmationForm,
    FollowUpRescheduleForm,
    FollowUpSelectionForm,
    MeasurementForm,
    PatientLookupForm,
    PatientRegistrationForm,
)
from .models import BloodPressureMeasurement, FollowUp, Patient
from .services import (
    ReviewChanged,
    SchedulingUnavailable,
    associate_existing_patient,
    automatic_proposal,
    complete_patient_registration,
    proposal_snapshot,
    record_measurement,
    require_vendor,
    reschedule_active_followup,
)

REGISTRATION_KEY = "patient_registration"
DRAFTS_KEY = "measurement_drafts"


def vendor_required(view):
    @never_cache
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_vendor(request.user)
        return view(request, *args, **kwargs)
    return wrapped


def associated_patient(request, patient_id):
    return get_object_or_404(Patient.objects.filter(vendors=request.user), pk=patient_id)


def pending_registration(request):
    pending = request.session.get(REGISTRATION_KEY)
    return pending if pending and pending.get("vendor_id") == request.user.pk else None


@vendor_required
@require_http_methods(["GET"])
def patient_list(request):
    query = request.GET.get("q", "").strip()[:150]
    patients = request.user.patients.prefetch_related(
        Prefetch(
            "followups",
            queryset=FollowUp.objects.filter(status=FollowUp.Status.ACTIVE),
            to_attr="active_followups",
        )
    )
    if query:
        match = Q(first_name__icontains=query) | Q(last_name__icontains=query)
        # Name searches also support the displayed full name.
        for word in query.split():
            if len(query.split()) > 1:
                match |= Q(first_name__icontains=word) & Q(last_name__icontains=query.split()[-1])
        try:
            phone = normalize_mobile_number(query)
        except ValidationError:
            phone = "".join(char for char in query if char.isascii() and char.isdigit())
            if phone.startswith("0"):
                phone = "+234" + phone[1:]
        if phone:
            match |= Q(phone_number__icontains=phone)
        patients = patients.filter(match)
    return render(request, "patients/list.html", {"patients": Paginator(patients, 20).get_page(request.GET.get("page")), "query": query})


@vendor_required
@require_http_methods(["GET", "POST"])
def register(request):
    form = PatientLookupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone_number"]
        previous = pending_registration(request) or {}
        pending = {"phone_number": phone, "vendor_id": request.user.pk}
        patient = Patient.objects.filter(phone_number=phone).first()
        if patient:
            request.session[REGISTRATION_KEY] = pending
            if patient.vendors.filter(pk=request.user.pk).exists():
                request.session.pop(REGISTRATION_KEY, None)
                messages.info(request, "This patient is already in your patient list.")
                return redirect("patients:detail", patient_id=patient.pk)
            return redirect("patients:associate")
        try:
            verification = issue_otp(phone, purpose="patient")
        except ResendCooldown:
            if previous.get("phone_number") == phone and previous.get("verification_id"):
                pending["verification_id"] = previous["verification_id"]
            else:
                form.add_error(None, "Please wait before requesting another code for this number.")
        except (DeliveryUnavailable, ImproperlyConfigured):
            form.add_error(None, "Phone verification is unavailable. Please try again later.")
        else:
            pending["verification_id"] = str(verification.pk)
        if not form.errors:
            request.session[REGISTRATION_KEY] = pending
            messages.info(request, "A verification code has been sent to the patient's phone.")
            return redirect("patients:verify")
    return render(request, "patients/register.html", {"form": form})


@vendor_required
@require_http_methods(["GET", "POST"])
def associate(request):
    pending = pending_registration(request)
    if not pending:
        return redirect("patients:register")
    patient = get_object_or_404(Patient, phone_number=pending["phone_number"])
    if patient.vendors.filter(pk=request.user.pk).exists():
        request.session.pop(REGISTRATION_KEY, None)
        messages.info(request, "This patient is already in your patient list.")
        return redirect("patients:detail", patient_id=patient.pk)
    if request.method == "POST" and request.POST.get("decision") == "decline":
        request.session.pop(REGISTRATION_KEY, None)
        messages.info(request, "The patient was not added. No records were changed.")
        return redirect("patients:list")
    form = AssociationConfirmationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        associate_existing_patient(request.user, patient, patient_agreed=form.cleaned_data["patient_agreed"])
        request.session.pop(REGISTRATION_KEY, None)
        messages.success(request, "The patient has been added to your patient list. Their relevant history is available.")
        return redirect("patients:detail", patient_id=patient.pk)
    # Discovery exposes existence and the supplied phone only, before agreement.
    return render(request, "patients/associate.html", {"form": form, "phone": local_phone_number(pending["phone_number"])})


@vendor_required
@sensitive_post_parameters("code")
@require_http_methods(["GET", "POST"])
def verify_phone(request):
    pending = pending_registration(request)
    if not pending or not pending.get("verification_id"):
        return redirect("patients:register")
    if Patient.objects.filter(phone_number=pending["phone_number"]).exists():
        return redirect("patients:associate")
    form = OTPVerificationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_otp(pending["verification_id"], pending["phone_number"], form.cleaned_data["code"], purpose="patient")
        except VerificationError:
            form.add_error("code", "The code could not be verified. Request a new code and try again.")
        else:
            return redirect("patients:register_details")
    return render(request, "patients/verify.html", {"form": form, "resend_cooldown": settings.OTP_RESEND_COOLDOWN_SECONDS})


@vendor_required
@require_POST
def resend_otp(request):
    pending = pending_registration(request)
    if not pending:
        return redirect("patients:register")
    if Patient.objects.filter(phone_number=pending["phone_number"]).exists():
        return redirect("patients:associate")
    try:
        verification = issue_otp(pending["phone_number"], purpose="patient")
    except ResendCooldown:
        messages.info(request, "Please wait before requesting another code.")
    except (DeliveryUnavailable, ImproperlyConfigured):
        messages.error(request, "Phone verification is unavailable. Please try again later.")
    else:
        pending["verification_id"] = str(verification.pk)
        request.session[REGISTRATION_KEY] = pending
        messages.info(request, "A new verification code has been sent to the patient's phone.")
    return redirect("patients:verify")


@vendor_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def register_details(request):
    pending = pending_registration(request)
    if not pending or not pending.get("verification_id"):
        return redirect("patients:register")
    if Patient.objects.filter(phone_number=pending["phone_number"]).exists():
        return redirect("patients:associate")
    try:
        get_verified_registration(pending["verification_id"], pending["phone_number"], purpose="patient")
    except VerificationError:
        messages.error(request, "Verify the patient's phone before completing registration.")
        return redirect("patients:verify")
    form = PatientRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            patient = complete_patient_registration(request.user, pending["verification_id"], pending["phone_number"], form.cleaned_data)
        except IntegrityError:
            if Patient.objects.filter(phone_number=pending["phone_number"]).exists():
                return redirect("patients:associate")
            raise
        except (VerificationError, ValidationError):
            form.add_error(None, "Registration could not be completed. Verify the phone and check the details again.")
        else:
            request.session.pop(REGISTRATION_KEY, None)
            messages.success(request, "The patient has been registered and added to your patient list.")
            return redirect("patients:detail", patient_id=patient.pk)
    return render(request, "patients/register_details.html", {"form": form, "phone": local_phone_number(pending["phone_number"])})


@vendor_required
@require_http_methods(["GET"])
def detail(request, patient_id):
    patient = associated_patient(request, patient_id)
    measurements = patient.measurements.select_related("recording_vendor")
    return render(request, "patients/detail.html", {
        "patient": patient, "latest": measurements.first(),
        "measurements": Paginator(measurements, 20).get_page(request.GET.get("page")),
        "active_followup": patient.followups.filter(status=FollowUp.Status.ACTIVE).first(),
        "followups": patient.followups.select_related("scheduled_by", "scheduling_rule", "fulfilled_by_measurement__recording_vendor")[:5],
        "today": timezone.localdate(),
    })


@vendor_required
@require_http_methods(["GET"])
def followup_history(request, patient_id):
    patient = associated_patient(request, patient_id)
    followups = patient.followups.select_related(
        "scheduled_by", "scheduling_rule", "fulfilled_by_measurement__recording_vendor"
    ).prefetch_related("schedule_changes__changed_by")
    return render(request, "patients/followups.html", {
        "patient": patient,
        "followups": Paginator(followups, 20).get_page(request.GET.get("page")),
        "today": timezone.localdate(),
    })


@vendor_required
@require_http_methods(["GET", "POST"])
def reschedule_followup(request, patient_id):
    patient = associated_patient(request, patient_id)
    followup = get_object_or_404(
        patient.followups.select_related("source_measurement"),
        status=FollowUp.Status.ACTIVE,
    )
    form = FollowUpRescheduleForm(
        request.POST if request.method == "POST" else None,
        initial={"scheduled_date": followup.scheduled_date},
    )
    if request.method == "POST" and form.is_valid():
        try:
            reschedule_active_followup(
                followup_id=followup.pk,
                vendor=request.user,
                scheduled_date=form.cleaned_data["scheduled_date"],
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            messages.success(
                request,
                "The active follow-up date and its reminder schedule have been updated.",
            )
            return redirect("patients:detail", patient_id=patient.pk)
    return render(
        request,
        "patients/reschedule_followup.html",
        {"patient": patient, "followup": followup, "form": form},
    )


@vendor_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def new_measurement(request, patient_id):
    patient = associated_patient(request, patient_id)
    form = MeasurementForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        operation_id = str(uuid.uuid4())
        drafts = request.session.get(DRAFTS_KEY, {})
        # Bound unfinished drafts to keep the normal database session lightweight.
        if len(drafts) >= 10:
            drafts.pop(next(iter(drafts)))
        drafts[operation_id] = {"patient_id": str(patient.pk), "vendor_id": request.user.pk, "values": form.cleaned_data}
        request.session[DRAFTS_KEY] = drafts
        return redirect("patients:confirm_measurement", patient_id=patient.pk, operation_id=operation_id)
    return render(request, "patients/measurement.html", {"form": form, "patient": patient, "recent": patient.measurements.select_related("recording_vendor")[:5]})


@vendor_required
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def confirm_measurement(request, patient_id, operation_id):
    patient = associated_patient(request, patient_id)
    if BloodPressureMeasurement.objects.filter(patient=patient, recording_vendor=request.user, operation_id=operation_id).exists():
        messages.info(request, "This measurement has already been saved.")
        return redirect("patients:detail", patient_id=patient.pk)
    drafts = request.session.get(DRAFTS_KEY, {})
    draft = drafts.get(str(operation_id))
    if not draft or draft["patient_id"] != str(patient.pk) or draft["vendor_id"] != request.user.pk:
        return redirect("patients:new_measurement", patient_id=patient.pk)
    try:
        rule, proposed_date = automatic_proposal()
    except SchedulingUnavailable as error:
        rule, proposed_date = None, None
        messages.error(request, error.messages[0])
    snapshot = proposal_snapshot(rule, proposed_date)
    form = FollowUpSelectionForm(request.POST if request.method == "POST" else None, automatic_date=proposed_date)
    status = 200
    if request.method == "POST" and draft.get("proposal") != snapshot:
        form = FollowUpSelectionForm(automatic_date=proposed_date)
        form.add_error(None, "The scheduling configuration or date has changed. Review the updated proposal before saving.")
    elif request.method == "POST" and form.is_valid():
        try:
            record_measurement(
                patient_id=patient.pk, vendor=request.user, values=draft["values"],
                operation_id=operation_id, expected_proposal=draft["proposal"],
                manual_date=form.cleaned_data["scheduled_date"] if form.cleaned_data["choice"] == "manual" else None,
            )
        except (ReviewChanged, SchedulingUnavailable, ValidationError) as error:
            form.add_error(None, error.messages[0])
        except OperationalError:
            form.add_error(None, "The database is busy. Please retry this confirmation; it will only save once.")
            status = 503
        else:
            drafts.pop(str(operation_id), None)
            request.session[DRAFTS_KEY] = drafts
            messages.success(request, "The measurement has been saved and the patient's follow-up updated.")
            return redirect("patients:detail", patient_id=patient.pk)
    draft["proposal"] = snapshot
    drafts[str(operation_id)] = draft
    request.session[DRAFTS_KEY] = drafts
    return render(request, "patients/confirm_measurement.html", {"patient": patient, "values": draft["values"], "form": form, "proposed_date": proposed_date}, status=status)

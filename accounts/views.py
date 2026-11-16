import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .delivery import DeliveryUnavailable
from .forms import OTPVerificationForm, VendorLoginForm, VendorPasswordForm, VendorRegistrationForm
from .models import User
from .services import (
    RegistrationError,
    ResendCooldown,
    VerificationError,
    complete_registration,
    get_verified_registration,
    issue_otp,
    verify_otp,
)

REGISTRATION_SESSION_KEY = "vendor_registration"
REGISTRATION_MESSAGE = "If this number can be registered, a verification code has been sent."


def account_home(user):
    return "accounts:dashboard" if user.account_type == User.AccountType.VENDOR else "admin:index"


@never_cache
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect(account_home(request.user))
    form = VendorRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        phone_number = form.cleaned_data["phone_number"]
        previous = request.session.get(REGISTRATION_SESSION_KEY, {})
        try:
            verification = issue_otp(phone_number)
            verification_id = str(verification.pk) if verification else str(uuid.uuid4())
        except ResendCooldown:
            verification_id = (
                previous.get("verification_id", str(uuid.uuid4()))
                if previous.get("phone_number") == phone_number else str(uuid.uuid4())
            )
        except (DeliveryUnavailable, ImproperlyConfigured):
            form.add_error(None, "Phone verification is unavailable. Please try again later.")
        if not form.errors:
            request.session[REGISTRATION_SESSION_KEY] = {
                "phone_number": phone_number,
                "business_name": form.cleaned_data["business_name"],
                "verification_id": verification_id,
                "verified": False,
            }
            messages.info(request, REGISTRATION_MESSAGE)
            return redirect("accounts:verify")
    return render(request, "accounts/register.html", {"form": form})


@never_cache
@sensitive_post_parameters("code")
@require_http_methods(["GET", "POST"])
def verify_phone(request):
    pending = request.session.get(REGISTRATION_SESSION_KEY)
    if not pending:
        return redirect("accounts:register")
    if pending.get("verified"):
        return redirect("accounts:create_password")
    form = OTPVerificationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_otp(pending["verification_id"], pending["phone_number"], form.cleaned_data["code"])
        except VerificationError:
            form.add_error("code", "The code could not be verified. Request a new code and try again.")
        else:
            pending["verified"] = True
            request.session[REGISTRATION_SESSION_KEY] = pending
            return redirect("accounts:create_password")
    return render(request, "accounts/verify.html", {
        "form": form, "resend_cooldown": settings.OTP_RESEND_COOLDOWN_SECONDS,
    })


@never_cache
@require_POST
def resend_otp(request):
    pending = request.session.get(REGISTRATION_SESSION_KEY)
    if not pending:
        return redirect("accounts:register")
    try:
        verification = issue_otp(pending["phone_number"])
    except ResendCooldown:
        pass
    except (DeliveryUnavailable, ImproperlyConfigured):
        messages.error(request, "Phone verification is unavailable. Please try again later.")
    else:
        pending["verification_id"] = str(verification.pk) if verification else str(uuid.uuid4())
        pending["verified"] = False
        request.session[REGISTRATION_SESSION_KEY] = pending
    messages.info(request, REGISTRATION_MESSAGE)
    return redirect("accounts:verify")


@never_cache
@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def create_password(request):
    pending = request.session.get(REGISTRATION_SESSION_KEY)
    if not pending:
        return redirect("accounts:register")
    if not pending.get("verified"):
        return redirect("accounts:verify")
    try:
        get_verified_registration(pending["verification_id"], pending["phone_number"])
    except VerificationError:
        request.session.pop(REGISTRATION_SESSION_KEY, None)
        messages.error(request, "Your verification is unavailable. Please start registration again.")
        return redirect("accounts:register")
    candidate = User(phone_number=pending["phone_number"], business_name=pending["business_name"])
    form = VendorPasswordForm(request.POST if request.method == "POST" else None, user=candidate)
    if request.method == "POST" and form.is_valid():
        try:
            user = complete_registration(
                pending["verification_id"], pending["phone_number"],
                pending["business_name"], form.cleaned_data["password1"],
            )
        except (VerificationError, RegistrationError, ValidationError):
            form.add_error(None, "Registration could not be completed. Start again or log in.")
        else:
            request.session.pop(REGISTRATION_SESSION_KEY, None)
            login(request, user, backend="accounts.backends.AccountBackend")
            messages.success(request, "Your vendor account is ready.")
            return redirect("accounts:dashboard")
    return render(request, "accounts/create_password.html", {"form": form})


class VendorLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = VendorLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        # Successful vendor logins go to the dashboard. Existing administrator
        # sessions return to Django admin through its named entry point.
        return reverse(account_home(self.request.user))


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def logout_account(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "You have been logged out.")
        return redirect("core:landing")
    return render(request, "accounts/logout.html")


@never_cache
@login_required
def vendor_dashboard(request):
    if (
        request.user.account_type != User.AccountType.VENDOR
        or not request.user.is_active
        or request.user.is_staff
        or request.user.is_superuser
    ):
        raise PermissionDenied
    return render(request, "accounts/dashboard.html")

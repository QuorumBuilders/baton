from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_safe


def landing(request):
    """Render Baton's public landing page."""
    return render(request, "core/landing.html")


@require_safe
def policy_page(request, template_name):
    """Public information; template names come only from explicit URL entries."""
    return render(request, template_name, {
        "operator_name": settings.BATON_OPERATOR_NAME,
        "operator_location": settings.BATON_OPERATOR_LOCATION,
        "operator_address": settings.BATON_OPERATOR_ADDRESS,
        "contact_email": settings.BATON_CONTACT_EMAIL,
        "session_cookie_name": settings.SESSION_COOKIE_NAME,
        "csrf_cookie_name": settings.CSRF_COOKIE_NAME,
        "session_cookie_days": settings.SESSION_COOKIE_AGE // 86400,
        "csrf_cookie_days": settings.CSRF_COOKIE_AGE // 86400,
    })

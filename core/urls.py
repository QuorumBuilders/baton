from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("policies/privacy/", views.policy_page, {"template_name": "core/policies/privacy.html"}, name="privacy"),
    path("policies/terms/", views.policy_page, {"template_name": "core/policies/terms.html"}, name="terms"),
    path("policies/patient-privacy/", views.policy_page, {"template_name": "core/policies/patient_privacy.html"}, name="patient_privacy"),
    path("policies/communications/", views.policy_page, {"template_name": "core/policies/communications.html"}, name="communication_info"),
    path("policies/cookies/", views.policy_page, {"template_name": "core/policies/cookies.html"}, name="cookies"),
    path("policies/retention/", views.policy_page, {"template_name": "core/policies/retention.html"}, name="retention"),
    path("policies/medical-disclaimer/", views.policy_page, {"template_name": "core/policies/medical.html"}, name="medical_disclaimer"),
    path("policies/contact/", views.policy_page, {"template_name": "core/policies/contact.html"}, name="contact"),
]

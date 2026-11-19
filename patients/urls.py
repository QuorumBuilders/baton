from django.urls import path

from . import views

app_name = "patients"
urlpatterns = [
    path("", views.patient_list, name="list"),
    path("register/", views.register, name="register"),
    path("register/associate/", views.associate, name="associate"),
    path("register/verify/", views.verify_phone, name="verify"),
    path("register/resend/", views.resend_otp, name="resend"),
    path("register/details/", views.register_details, name="register_details"),
    path("<uuid:patient_id>/", views.detail, name="detail"),
    path("<uuid:patient_id>/communication-consent/", views.communication_consent, name="communication_consent"),
    path("<uuid:patient_id>/follow-ups/", views.followup_history, name="followup_history"),
    path("<uuid:patient_id>/follow-ups/reschedule/", views.reschedule_followup, name="reschedule_followup"),
    path("<uuid:patient_id>/measurements/new/", views.new_measurement, name="new_measurement"),
    path("<uuid:patient_id>/measurements/confirm/<uuid:operation_id>/", views.confirm_measurement, name="confirm_measurement"),
]

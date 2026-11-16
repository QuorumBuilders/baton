from django.urls import include, path
from django.views.generic.base import RedirectView

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.VendorLoginView.as_view(), name="login"),
    path("accounts/", include([
        path("register/", views.register, name="register"),
        path("verify/", views.verify_phone, name="verify"),
        path("resend/", views.resend_otp, name="resend"),
        path("create-password/", views.create_password, name="create_password"),
        path("logout/", views.logout_account, name="logout"),
        path("dashboard/", views.vendor_dashboard, name="dashboard"),
        path(
            "login/",
            RedirectView.as_view(pattern_name="accounts:login", query_string=True),
            name="legacy_login",
        ),
    ])),
]

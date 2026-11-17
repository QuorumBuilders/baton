"""URL configuration for Baton."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("patients/", include("patients.urls")),
    path("", include("core.urls")),
]

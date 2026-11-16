from django.shortcuts import render


def landing(request):
    """Render Baton's public landing page."""
    return render(request, "core/landing.html")

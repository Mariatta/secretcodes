from django.shortcuts import render


def index(request):
    context = {}
    return render(request, "main.html", context)


def privacy(request):
    """Public privacy policy page."""
    return render(request, "privacy.html")


def terms(request):
    """Public terms-of-service page."""
    return render(request, "terms.html")

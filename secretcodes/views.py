from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from availability.services.mcp import get_server_descriptor


def index(request):
    context = {}
    return render(request, "main.html", context)


def privacy(request):
    """Public privacy policy page."""
    return render(request, "privacy.html")


def terms(request):
    """Public terms-of-service page."""
    return render(request, "terms.html")


def agents(request):
    """Developer-facing docs for the MCP server exposed at /mcp/."""
    return render(request, "agents.html")


def about(request):
    """About page: what this site is, plus the brand's origin story."""
    return render(request, "about.html")


def well_known_mcp(request):
    """Machine-readable MCP server descriptor.

    Agents and frameworks can GET this to discover the endpoint, protocol
    version, and the full tool catalog without making an MCP handshake.
    """
    endpoint = request.build_absolute_uri(reverse("mcp_endpoint"))
    documentation = request.build_absolute_uri(reverse("agents"))
    return JsonResponse(get_server_descriptor(endpoint, documentation))

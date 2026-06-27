from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image

from .forms import (
    QRCodePreviewForm,
    QRCodeStylePreviewForm,
    QRCodeWithSlugPreviewForm,
)
from .models import QRCode
from .permissions import is_qr_slug_user
from .qr_image import build_qr_png


@user_passes_test(is_qr_slug_user)
def qrcode_slug_generator(request):
    context = {"name": request.user.username}

    if request.method == "POST":
        qr_form = QRCodeWithSlugPreviewForm(request.POST, request.FILES)
        if qr_form.is_valid():
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                qr_obj = QRCode.objects.get(url=url)
                qr_obj.description = qr_form.cleaned_data.get("description")
            else:
                qr_obj = QRCode(
                    url=url, description=qr_form.cleaned_data.get("description")
                )
            qr_obj.slug = qr_form.cleaned_data.get("slug")
            for field in (
                "fill_color",
                "gradient_color",
                "back_color",
                "module_style",
                "color_mask_style",
            ):
                if qr_form.cleaned_data.get(field):
                    setattr(qr_obj, field, qr_form.cleaned_data[field])
            if qr_form.cleaned_data.get("logo"):
                qr_obj.attach_logo(qr_form.cleaned_data["logo"])
            qr_obj.save()

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
            context["result_url"] = settings.DOMAIN_NAME + "/qr/" + qr_obj.slug
    else:
        qr_form = QRCodeWithSlugPreviewForm()
    context["qr_preview_form"] = qr_form
    context["post_url"] = "qrcode_slug_generator"
    return render(request, "qrcode_manager/qr_code_customizer.html", context)


@user_passes_test(is_qr_slug_user)
@require_POST
def qrcode_style_preview(request):
    """Render a styled QR code PNG entirely in memory for the live
    preview pane. Nothing is persisted and S3 is never touched."""
    form = QRCodeStylePreviewForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    slug = form.cleaned_data.get("slug")
    if slug:
        data = settings.DOMAIN_NAME + "/qr/" + slug
    else:
        data = form.cleaned_data["url"]
    logo_upload = form.cleaned_data.get("logo")
    logo = Image.open(logo_upload) if logo_upload else None

    buffer = build_qr_png(
        data,
        fill_color=form.cleaned_data.get("fill_color"),
        back_color=form.cleaned_data.get("back_color"),
        gradient_color=form.cleaned_data.get("gradient_color"),
        module_style=form.cleaned_data.get("module_style"),
        color_mask_style=form.cleaned_data.get("color_mask_style"),
        logo=logo,
    )
    return HttpResponse(buffer.getvalue(), content_type="image/png")


def qr_code_generator(request):
    context = {}
    if request.method == "POST":
        qr_form = QRCodePreviewForm(request.POST)
        if qr_form.is_valid():
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                qr_obj = QRCode.objects.get(url=url)
            else:
                qr_obj = QRCode.objects.create(
                    url=url, description=qr_form.cleaned_data.get("description")
                )

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
            context["result_url"] = url
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form
    context["post_url"] = "qrcode_generator"

    return render(request, "qrcode_manager/qr_code_generator.html", context)


def url_reverse(request, slug):
    qr_obj = get_object_or_404(QRCode, slug=slug)
    # Use F() expression to avoid race conditions
    QRCode.objects.filter(pk=qr_obj.pk).update(
        visit_count=F("visit_count") + 1, last_visited=timezone.now()
    )
    return redirect(qr_obj.url)


def legacy_url_reverse(request, slug):
    """Redirect pre-migration URLs at /<slug>/ to the namespaced /qr/<slug>/.

    Uses get_object_or_404 so an unknown slug returns a clean 404 rather
    than chaining a 301 into a 404.
    """
    get_object_or_404(QRCode, slug=slug)
    return redirect(reverse("url_reverse", args=[slug]), permanent=True)

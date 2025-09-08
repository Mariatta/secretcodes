
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import render
from django.utils import timezone

from .forms import QRCodePreviewForm, QRCodeWithSlugPreviewForm
from .models import QRCode

@login_required
def qrcode_slug_generator(request):
    context = {"name": request.user.username}

    if request.method == "POST":
        qr_form = QRCodeWithSlugPreviewForm(request.POST)
        if qr_form.is_valid():
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                qr_obj = QRCode.objects.get(url=url)
                if not qr_obj.slug or qr_obj.slug != qr_form.cleaned_data.get("slug"):
                    qr_obj.slug = qr_form.cleaned_data.get("slug")
                    qr_obj.save()
            else:
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("description"),
                                               slug=qr_form.cleaned_data.get("slug"))

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
            context["result_url"] = settings.DOMAIN_NAME + "/" + qr_obj.slug
    else:
        qr_form = QRCodeWithSlugPreviewForm()
    context["qr_preview_form"] = qr_form
    context["post_url"] = "qrcode_slug_generator"
    return render(request, "qrcode_manager/qr_code_generator.html", context)

def qr_code_generator(request):
    context = {}
    if request.method == "POST":
        qr_form = QRCodePreviewForm(request.POST)
        if qr_form.is_valid():
            print(qr_form.cleaned_data)
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                qr_obj = QRCode.objects.get(url=url)
            else:
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("description"))

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
            context["result_url"] = url
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form
    context["post_url"] = "qrcode_generator"

    return render(request, "qrcode_manager/qr_code_generator.html", context)


def url_reverse(request, slug):
    qr_obj = QRCode.objects.filter(slug=slug).first()
    if qr_obj:
        qr_obj.visit_count += 1
        qr_obj.last_visited = timezone.now()
        qr_obj.save()
        return HttpResponseRedirect(qr_obj.url)
    else:
        raise Http404
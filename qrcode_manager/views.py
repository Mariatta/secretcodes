
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import render
from .forms import QRCodePreviewForm
from .models import QRCode
@login_required
def index(request):
    context = {"name": request.user.username}

    if request.method == "POST":
        qr_form = QRCodePreviewForm(request.POST)
        if qr_form.is_valid():
            print(qr_form.cleaned_data)
            # Process the form data and generate a QR code
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                qr_obj = QRCode.objects.get(url=url)
                qr_form = QRCodePreviewForm(initial={"url": url, "description": qr_obj.description})
            else:
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("description"))
            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form

    return render(request, "qrcode_manager/index.html", context)

def qr_code_generator(request):
    context = {}
    if request.method == "POST":
        qr_form = QRCodePreviewForm(request.POST)
        if qr_form.is_valid():
            print(qr_form.cleaned_data)
            url = qr_form.cleaned_data.get("url")
            if QRCode.objects.filter(url=url).exists():
                print("returning existing QR code")
                qr_obj = QRCode.objects.get(url=url)
                if not qr_obj.slug or qr_obj.slug != qr_form.cleaned_data.get("slug"):
                    qr_obj.slug = qr_form.cleaned_data.get("slug")
                    qr_obj.save()
            else:
                print("create new QR code")
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("description"), slug=qr_form.cleaned_data.get("slug"))

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form
    return render(request, "qrcode_manager/qr_code_generator.html", context)


def url_reverse(request, slug):

    qr_obj = QRCode.objects.filter(slug=slug).first()
    if qr_obj:
        return HttpResponseRedirect(qr_obj.url)
    else:
        raise Http404
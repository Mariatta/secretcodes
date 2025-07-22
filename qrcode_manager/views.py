
from django.contrib.auth.decorators import login_required
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
            else:
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("filename"))


            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
            # Here you would typically generate the QR code and save it or return it
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
            else:
                print("create new QR code")
                qr_obj = QRCode.objects.create(url=url, description=qr_form.cleaned_data.get("filename"))

            context["qr_image_presigned"] = qr_obj.get_qr_image_url()
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form
    return render(request, "qrcode_manager/qr_code_generator.html", context)
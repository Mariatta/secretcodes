from django.http import HttpResponse

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .forms import QRCodePreviewForm
from .models import generate_qr
@login_required
def index(request):
    context = {"name": request.user.username}


    if request.method == "POST":
        qr_form = QRCodePreviewForm(request.POST)
        if qr_form.is_valid():
            print(qr_form.cleaned_data)
            # Process the form data and generate a QR code
            url = qr_form.cleaned_data.get("url")
            filename = qr_form.cleaned_data.get("filename")
            generate_qr(url, filename)

            context["qr_image"] = filename
            # Here you would typically generate the QR code and save it or return it
    else:
        qr_form = QRCodePreviewForm()
    context["qr_preview_form"] = qr_form

    return render(request, "qrcode_manager/index.html", context)
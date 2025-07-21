from django.http import HttpResponse


def index(request):
    return HttpResponse("QR Code manager index page")
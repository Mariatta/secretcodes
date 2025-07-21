from django.http import HttpResponse


def index(request):
    return HttpResponse("Secret Codes Index page")
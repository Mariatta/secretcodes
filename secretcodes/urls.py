"""
URL configuration for secretcodes project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from django.conf import settings
from secretcodes import views
from qrcode_manager import views as qr_views

urlpatterns = [
    path("", views.index, name="index"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    # path("qrcode_manager/", include("qrcode_manager.urls")),
    path("qrcode_generator/", qr_views.qr_code_generator, name="qrcode_generator"),
    path(
        "qrcode_slug_generator/",
        qr_views.qrcode_slug_generator,
        name="qrcode_slug_generator",
    ),
    path("<str:slug>/", qr_views.url_reverse, name="url_reverse"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

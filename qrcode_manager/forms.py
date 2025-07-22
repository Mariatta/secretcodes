from django import forms
from qrcode_manager.models import QRCode

class QRCodePreviewForm(forms.Form):

    url = forms.URLField(label='URL')
    filename = forms.CharField(label='Filename')


import ssl
from django.core.mail.backends.smtp import EmailBackend


class InsecureEmailBackend(EmailBackend):
    """
    Désactive la vérification du certificat TLS.
    ⚠️ À utiliser uniquement en DEV/TEST.
    """
    def open(self):
        # TLS sans vérification (INSECURE)
        self.ssl_context = ssl._create_unverified_context()
        return super().open()

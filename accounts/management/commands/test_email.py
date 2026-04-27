from django.core.management.base import BaseCommand
from django.core.mail import send_mail, get_connection
from django.conf import settings


class Command(BaseCommand):
    help = "Test SMTP email sending — affiche la config et tente un envoi réel"

    def add_arguments(self, parser):
        parser.add_argument("to_email", type=str, help="Adresse email du destinataire")

    def handle(self, *args, **options):
        to = options["to_email"]

        self.stdout.write("─── Configuration email ───────────────────────────")
        self.stdout.write(f"  Backend  : {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  Host     : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  User     : {settings.EMAIL_HOST_USER}")
        self.stdout.write(f"  Password : {'(défini)' if settings.EMAIL_HOST_PASSWORD else '(vide !)'}")
        self.stdout.write(f"  TLS      : {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  SSL      : {settings.EMAIL_USE_SSL}")
        self.stdout.write(f"  From     : {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write("───────────────────────────────────────────────────")
        self.stdout.write(f"Envoi vers : {to}")

        try:
            connection = get_connection(
                backend=settings.EMAIL_BACKEND,
                host=settings.EMAIL_HOST,
                port=settings.EMAIL_PORT,
                username=settings.EMAIL_HOST_USER,
                password=settings.EMAIL_HOST_PASSWORD,
                use_tls=settings.EMAIL_USE_TLS,
                use_ssl=settings.EMAIL_USE_SSL,
                fail_silently=False,
            )
            connection.open()
            self.stdout.write(self.style.SUCCESS("  Connexion SMTP ouverte avec succès."))
            connection.close()

            send_mail(
                subject="[ACX] Test d'envoi email",
                message="Ceci est un test d'envoi depuis la plateforme ACX. Si vous recevez ce message, la configuration SMTP fonctionne correctement.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                fail_silently=False,
                connection=get_connection(
                    backend=settings.EMAIL_BACKEND,
                    host=settings.EMAIL_HOST,
                    port=settings.EMAIL_PORT,
                    username=settings.EMAIL_HOST_USER,
                    password=settings.EMAIL_HOST_PASSWORD,
                    use_tls=settings.EMAIL_USE_TLS,
                    use_ssl=settings.EMAIL_USE_SSL,
                    fail_silently=False,
                ),
            )
            self.stdout.write(self.style.SUCCESS(f"Email envoyé avec succès à {to} !"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Échec : {exc}"))
            self.stdout.write(self.style.ERROR("Vérifiez les credentials SMTP et l'accès réseau au serveur mail."))

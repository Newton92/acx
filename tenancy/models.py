#tenancy/models.py

from django.db import models
from django.utils.text import slugify

class Tenant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    # 1) Identité
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    legal_name = models.CharField(max_length=255, blank=True, null=True)  # raison sociale
    industry = models.CharField(max_length=120, blank=True, null=True)    # secteur

    # 2) Contact
    contact_name = models.CharField(max_length=120, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    # 3) Localisation / positionnement
    country = models.CharField(max_length=2, blank=True, null=True)  # ISO2: TD, FR...
    city = models.CharField(max_length=120, blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    postal_code = models.CharField(max_length=30, blank=True, null=True)

    # 4) Paramètres “monde”
    timezone = models.CharField(max_length=64, blank=True, null=True)  # ex: Africa/Ndjamena
    locale = models.CharField(max_length=10, blank=True, null=True)    # ex: fr, en
    currency = models.CharField(max_length=3, blank=True, null=True)   # ex: XAF

    # 5) SaaS
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    plan = models.CharField(max_length=50, blank=True, null=True)
    trial_ends_at = models.DateTimeField(blank=True, null=True)

    # 6) Conformité / Identifiants (optionnel)
    tax_id = models.CharField(max_length=80, blank=True, null=True)
    registration_id = models.CharField(max_length=80, blank=True, null=True)

    # 7) Branding
    logo = models.ImageField(upload_to="tenants/logos/", blank=True, null=True)

    # 8) Extensible
    metadata = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            i = 2
            while Tenant.objects.filter(slug=slug).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name





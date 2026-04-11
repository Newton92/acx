from django.contrib import admin

from .models import TreasuryAccount, TreasuryMovement, RemittanceBatch, RemittanceLine

admin.site.register(TreasuryAccount)
admin.site.register(TreasuryMovement)
admin.site.register(RemittanceBatch)
admin.site.register(RemittanceLine)

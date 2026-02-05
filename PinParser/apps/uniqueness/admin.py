from django.contrib import admin
from .models import UniquenessConfig


@admin.register(UniquenessConfig)
class UniquenessConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "model", "is_active", "max_workers")
    list_filter = ("is_active",)
from django.contrib import admin
from .models import PinterestAccount


@admin.register(PinterestAccount)
class PinterestAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "fail_count",
        "is_active",
        "last_used_at",
        "created_at",
    )

    list_filter = ("status", "is_active")
    search_fields = ("name",)
    readonly_fields = ("fail_count", "last_used_at", "created_at")
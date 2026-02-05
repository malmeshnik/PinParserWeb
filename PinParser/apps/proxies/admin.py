from django.contrib import admin
from .models import Proxy


@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "host",
        "port",
        "country",
        "status",
        "fail_count",
        "is_active",
        "created_at",
    )

    list_filter = ("status", "country", "is_active")
    search_fields = ("name", "host")
    readonly_fields = ("fail_count", "last_checked_at", "created_at")

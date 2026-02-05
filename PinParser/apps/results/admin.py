from django.contrib import admin
from django.utils.html import format_html

from .models import PinResult

# Register your models here.
from django.contrib import admin
from django.utils.html import format_html

from apps.results.models import PinResult


@admin.register(PinResult)
class PinResultAdmin(admin.ModelAdmin):
    list_display = (
        "short_title",
        "pin_link",
        "keyword",
        "pinner_username",
        "saves",
        "task",
        "created_at",
    )

    list_display_links = ("short_title",)

    list_filter = (
        "task",
        "keyword",
        "domain",
        "pinner_username",
    )

    search_fields = (
        "pin_url",
        "title",
        "utitle",
        "description",
        "udescription",
    )

    ordering = ("-created_at",)

    readonly_fields = (
        "task",
        "keyword",
        "pin_url",
        "pin_id",
        "title",
        "description",
        "utitle",
        "udescription",
        "slug_url",
        "image_url",
        "alt_text",
        "annotation",
        "domain",
        "saves",
        "pinner_username",
        "creation_date",
        "created_at",
    )

    fieldsets = (
        ("Звʼязок", {
            "fields": ("task", "keyword"),
        }),
        ("Pinterest", {
            "fields": (
                "pin_url",
                "pin_id",
                "pinner_username",
                "domain",
                "creation_date",
                "saves",
            )
        }),
        ("Контент (оригінал)", {
            "fields": ("title", "description", "alt_text", "annotation"),
        }),
        ("Контент (унікальний)", {
            "fields": ("utitle", "udescription", "slug_url"),
        }),
        ("Медіа", {
            "fields": ("image_url",),
        }),
        ("Система", {
            "fields": ("created_at",),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def pin_link(self, obj):
        return format_html(
            '<a href="{}" target="_blank">🔗 Pin</a>',
            obj.pin_url
        )
    pin_link.short_description = "Pin"

    def short_title(self, obj):
        text = obj.utitle or obj.title or ""
        return (text[:60] + "…") if len(text) > 60 else text
    short_title.short_description = "Title"

from django.contrib import admin
from django.utils.html import format_html

from .models import ParseTask, TaskStatus
from .tasks import run_parse_task
from apps.results.tasks import export_results_to_sheets
from apps.uniqueness.tasks import run_uniqueness, generate_slugs

@admin.register(ParseTask)
class ParseTaskAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status_badge",
        "threads",
        "progress",
        "use_uniqueness",
        "created_at",
    )
    list_display_links = ("name",)
    list_filter = ("status", "use_uniqueness")
    search_fields = ("name",)

    readonly_fields = (
        "status",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
        "processed_urls",
        "total_urls",
        "celery_task_id",
    )

    fieldsets = (
        ("Основне", {
            "fields": ("name", "keywords", "threads")
        }),
        ("Опції", {
            "fields": ("use_uniqueness",)
        }),
        ("Статус", {
            "fields": (
                "status",
                "error_message",
                "processed_urls",
                "total_urls",
                "celery_task_id",
            )
        }),
        ("Дати", {
            "fields": ("created_at", "started_at", "finished_at")
        }),
    )

    actions = [
        "start_task",
        "stop_task",
        "export_to_sheets",
        "run_uniqueness_action",
    ]

    def status_badge(self, obj):
        colors = {
            TaskStatus.PENDING: "#999",
            TaskStatus.RUNNING: "#0d6efd",
            TaskStatus.DONE: "#198754",
            TaskStatus.ERROR: "#dc3545",
            TaskStatus.STOPPED: "#ffc107",
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.status, "#000"),
            obj.get_status_display().upper(),
        )
    status_badge.short_description = "Статус"

    def progress(self, obj):
        if not obj.total_urls:
            return "—"
        return f"{obj.processed_urls} / {obj.total_urls}"
    progress.short_description = "Прогрес"

    @admin.action(description="▶️ Запустити парсинг")
    def start_task(self, request, queryset):
        for task in queryset:
            if task.status in [TaskStatus.RUNNING]:
                continue

            async_result = run_parse_task.delay(task.id)
            task.celery_task_id = async_result.id
            task.status = TaskStatus.PENDING
            task.save(update_fields=["celery_task_id", "status"])

    @admin.action(description="🛑 Зупинити")
    def stop_task(self, request, queryset):
        queryset.update(status=TaskStatus.STOPPED)

    @admin.action(description="📤 Експорт у Google Sheets")
    def export_to_sheets(self, request, queryset):
        for task in queryset:
            export_results_to_sheets.delay(task.id)

    @admin.action(description="✨ Запустити Uniqueness + Slug")
    def run_uniqueness_action(self, request, queryset):
        for task in queryset:
            run_uniqueness.delay(task.id)
            generate_slugs.delay(task.id)
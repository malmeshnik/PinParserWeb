import json

from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import ErrorLog, LogLevel

LEVEL_COLORS = {
    LogLevel.WARNING: "#b7791f",
    LogLevel.ERROR: "#dc3545",
    LogLevel.CRITICAL: "#7b1fa2",
}


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('created_at', 'level_badge', 'source', 'message_short', 'task_link', 'worker', 'is_resolved')
    list_display_links = ('created_at', 'message_short')
    list_filter = ('is_resolved', 'level', 'source', 'created_at')
    search_fields = ('message', 'traceback', 'logger_name', 'task__name')
    date_hierarchy = 'created_at'
    list_select_related = ('task',)
    list_per_page = 50
    actions = ['mark_resolved', 'mark_unresolved']

    fieldsets = (
        (None, {
            "fields": ("created_at", "level_badge", "source", "is_resolved", "message_full")
        }),
        (_("Где произошло"), {
            "fields": ("task_link", "account", "logger_name", "context_pretty", "similar_link")
        }),
        (_("Traceback"), {
            "fields": ("traceback_pretty",)
        }),
    )
    readonly_fields = (
        'created_at', 'level_badge', 'source', 'message_full', 'task_link', 'account',
        'logger_name', 'context_pretty', 'similar_link', 'traceback_pretty',
    )

    def has_add_permission(self, request):
        return False

    def lookup_allowed(self, lookup, value, request=None):
        # Посилання «Схожі помилки» і дашборд фільтрують за відпечатком
        if lookup == 'fingerprint':
            return True
        return super().lookup_allowed(lookup, value, request)

    @admin.display(description=_("Уровень"), ordering='level')
    def level_badge(self, obj):
        return format_html(
            '<b style="color:#fff;background:{};padding:2px 8px;border-radius:10px;font-size:11px">{}</b>',
            LEVEL_COLORS.get(obj.level, "#6c757d"), obj.level,
        )

    @admin.display(description=_("Сообщение"))
    def message_short(self, obj):
        first_line = (obj.message or "").splitlines()[0] if obj.message else ""
        return first_line[:140] + ("…" if len(first_line) > 140 else "")

    @admin.display(description=_("Сообщение"))
    def message_full(self, obj):
        return format_html('<pre style="white-space:pre-wrap;margin:0">{}</pre>', obj.message)

    @admin.display(description=_("Задание"), ordering='task')
    def task_link(self, obj):
        if not obj.task_id:
            return "-"
        url = reverse('admin:tasks_parsetask_change', args=[obj.task_id])
        return format_html('<a href="{}">#{} {}</a>', url, obj.task_id, obj.task.name if obj.task else "")

    @admin.display(description=_("Воркер"))
    def worker(self, obj):
        return (obj.context or {}).get("worker") or "-"

    @admin.display(description=_("Контекст"))
    def context_pretty(self, obj):
        if not obj.context:
            return "-"
        context = dict(obj.context)
        links = []
        if context.get("autopost_config_id"):
            url = reverse('admin:tasks_autopostconfig_change', args=[context["autopost_config_id"]])
            links.append(format_html('<a href="{}">⚙️ Автопостинг #{}</a>', url, context["autopost_config_id"]))
        if context.get("pin_id"):
            url = reverse('admin:results_pinresult_change', args=[context["pin_id"]])
            links.append(format_html('<a href="{}">📌 Пин #{}</a>', url, context["pin_id"]))
        pretty = json.dumps(context, ensure_ascii=False, indent=2, default=str)
        return format_html(
            '{}<pre style="white-space:pre-wrap;margin:6px 0 0">{}</pre>',
            mark_safe(" &nbsp; ".join(links)),
            pretty,
        )

    @admin.display(description=_("Схожие ошибки"))
    def similar_link(self, obj):
        if not obj.fingerprint:
            return "-"
        count = ErrorLog.objects.filter(fingerprint=obj.fingerprint).count()
        url = reverse('admin:logs_errorlog_changelist') + f'?fingerprint={obj.fingerprint}'
        return format_html('<a href="{}">{} {}</a>', url, count, _("шт. — показать все"))

    @admin.display(description=_("Traceback"))
    def traceback_pretty(self, obj):
        if not obj.traceback:
            return "-"
        return format_html(
            '<pre style="white-space:pre-wrap;max-height:600px;overflow:auto;background:var(--darkened-bg);'
            'padding:10px;border-radius:4px;font-size:12px">{}</pre>',
            obj.traceback,
        )

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.action(description=_("✅ Отметить решёнными"))
    def mark_resolved(self, request, queryset):
        updated = queryset.update(is_resolved=True)
        messages.success(request, _("Отмечено решёнными: %(count)s") % {'count': updated})

    @admin.action(description=_("↩️ Вернуть в нерешённые"))
    def mark_unresolved(self, request, queryset):
        updated = queryset.update(is_resolved=False)
        messages.success(request, _("Возвращено в нерешённые: %(count)s") % {'count': updated})

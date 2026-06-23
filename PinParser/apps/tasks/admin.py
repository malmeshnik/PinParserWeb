import zipfile
import os
from io import BytesIO

from django.core.cache import cache
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from django import forms
from celery.result import AsyncResult
from .models import ParseTask, TaskStatus, AutoPostConfig, AutoPostStatus, AutoPostQueue, PostQueueStatus
from .tasks import run_parse_task
from .errors import TaskAlreadyRunning
from apps.results.tasks import export_results_to_excel
from apps.uniqueness.tasks import run_uniqueness, generate_slugs
from config.celery import app
from apps.accounts.models import PinterestAccount, AccountStatus
from apps.proxies.models import Proxy, ProxyStatus

class ParseTaskForm(forms.ModelForm):
    keywords_text = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 5}),
        help_text=_("Введите ключевые слова, каждое с новой строки"),
        label=_("Ключевые слова (текст)"),
        required=False
    )

    class Meta:
        model = ParseTask
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.keywords:
            if isinstance(self.instance.keywords, list):
                self.fields['keywords_text'].initial = "\n".join(self.instance.keywords)
            else:
                self.fields['keywords_text'].initial = str(self.instance.keywords)

    def save(self, commit=True):
        keywords_text = self.cleaned_data.get('keywords_text')
        if keywords_text:
            self.instance.keywords = [k.strip() for k in keywords_text.split('\n') if k.strip()]
        return super().save(commit=commit)

@admin.register(ParseTask)
class ParseTaskAdmin(admin.ModelAdmin):
    form = ParseTaskForm
    change_form_template = "admin/tasks/parsetask/change_form.html"
    list_display = ('name', 'owner', 'status_badge', 'progress_display', 'short_error_message', 'view_results_link', 'download_excel', 'autopost_settings_link', 'created_at')
    list_filter = ('status', 'created_at', 'use_uniqueness')
    search_fields = ('name', 'keywords')
    exclude = ('keywords', 'celery_task_id')
    list_select_related = ('owner', 'uniqueness_config')
    list_per_page = 50
    show_full_result_count = False
    ordering = ('-created_at',)

    readonly_fields = (
        "error_message",
        "started_at",
        "finished_at",
        "processed_urls",
        "total_urls",
    )

    fieldsets = (
        (_("Основное"), {
            "fields": ("name", "keywords_text", "threads")
        }),
        (_("Опции"), {
            "fields": ("use_uniqueness", "uniqueness_config")
        }),
        (_("Статус"), {
            "fields": (
                "status",
                "error_message",
                "processed_urls",
                "total_urls",
            )
        }),
        (_("Даты"), {
            "fields": ("started_at", "finished_at")
        }),
    )

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
    status_badge.short_description = _("Статус")

    def short_error_message(self, obj):
        if not obj.error_message:
            return "-"
        if len(obj.error_message) > 50:
            return obj.error_message[:50] + "..."
        return obj.error_message
    short_error_message.short_description = _("Ошибка")


    actions = ['start_tasks', 'stop_task', 'export_to_excel', 'uniqueness_task', 'generate_slug_task', 'download_files']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related('owner', 'uniqueness_config')
        qs = qs.defer('keywords', 'error_message')

        if not request.user.is_superuser:
            qs = qs.filter(owner=request.user)

        return qs

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.owner:
            obj.owner = request.user
        super().save_model(request, obj, form, change)

    def download_excel(self, obj):
        if not obj.export_file:
            return "-"

        return format_html(
            '<a class="button" href="{}" download>⬇️ Excel</a>',
            obj.export_file.url
        )

    download_excel.short_description = _("Excel")

    def view_results_link(self, obj):
        url = reverse('admin:results_pinresult_changelist') + f'?task__id__exact={obj.id}'
        return format_html('<a class="button" href="{}">📊 {}</a>', url, _("Результаты"))
    view_results_link.short_description = _("Результаты")

    def autopost_settings_link(self, obj):
        url = f"/admin/tasks/parsetask/{obj.id}/autopost/"
        return format_html('<a class="button" href="{}">⚙️ {}</a>', url, _("Автопостинг"))
    autopost_settings_link.short_description = _("Автопостинг")

    def progress_display(self, obj):
        cache_key = f"task_progress_{obj.id}_{obj.processed_urls}_{obj.total_urls}"
        display = cache.get(cache_key)

        if display is None:
            display = f"{obj.processed_urls}/{obj.total_urls}"
            cache.set(cache_key, display, timeout=60)

        return display
    progress_display.short_description = _("Собрано/Найдено пинов")

    def start_tasks(self, request, queryset):
        PinterestAccount.objects.update(status=AccountStatus.ACTIVE)
        Proxy.objects.update(status=ProxyStatus.ACTIVE)

        for task in queryset:
            self.start_task(request, task)

        self.message_user(request, _("Задания запущены"))
    start_tasks.short_description = _("▶️ Запустить выбранные задания")

    def stop_task(self, request, queryset):
        stopped = 0
        for task in queryset:
            if task.status in (
                TaskStatus.RUNNING,
                TaskStatus.WAITING_UNIQUENESS,
                TaskStatus.UNIQUENESS,
            ):
                if task.status == TaskStatus.RUNNING:
                    cache.set(f"stop_task_{task.id}", True, timeout=3600)

                if task.celery_task_id:
                    app.control.revoke(
                        task.celery_task_id,
                        terminate=True,
                        signal="SIGTERM",
                    )

                task.status = TaskStatus.STOPPED
                task.celery_task_id = None
                task.save(update_fields=["status", "celery_task_id"])
                stopped += 1

        self.message_user(request, _("Остановлено задач: %(stopped)s") % {'stopped': stopped})
    stop_task.short_description = _("⛔ Остановить выполнение выбранных заданий")

    @admin.action(description=_("📤 Экспорт в Excel"))
    def export_to_excel(self, request, queryset):
        for task in queryset:
            export_results_to_excel.delay(task.id)

    @admin.action(description=_("Уникализировать"))
    def uniqueness_task(self, request, queryset):
        for task in queryset:
            run_uniqueness.delay(task.id)

    @admin.action(description=_("Сгенерировать slug"))
    def generate_slug_task(self, request, queryset):
        for task in queryset:
            generate_slugs.delay(task.id)

    @admin.action(description=_("⬇️ Скачать выбранные файлы"))
    def download_files(self, request, queryset):
        files = queryset.exclude(export_file="")

        if not files.exists():
            self.message_user(request, _("Нет файлов для скачивания"))
            return

        if files.count() == 1:
            task = files.first()
            response = HttpResponse(
                task.export_file.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(task.export_file.name)}"'
            return response

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as zip_file:
            for task in files:
                file_path = task.export_file.path
                if os.path.exists(file_path):
                    zip_file.write(
                        file_path,
                        arcname=os.path.basename(file_path)
                    )

        buffer.seek(0)

        response = HttpResponse(buffer, content_type="application/zip")
        response['Content-Disposition'] = 'attachment; filename="tasks_export.zip"'
        return response

    def response_add(self, request, obj, post_url_continue=None):
        if "_save_and_run" in request.POST:
            self.start_task(request, obj)
            return super().response_add(request, obj, post_url_continue)

        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_save_and_run" in request.POST:
            self.start_task(request, obj)
            return super().response_change(request, obj)

        return super().response_change(request, obj)

    def start_task(self, request, task):
        if task.status in (TaskStatus.RUNNING, TaskStatus.WAITING_UNIQUENESS, TaskStatus.UNIQUENESS):
            return

        result = run_parse_task.delay(task.id)

        task.celery_task_id = result.id
        task.status = TaskStatus.RUNNING
        task.save(update_fields=["celery_task_id", "status"])
        self.message_user(request, _("Задание %(id)s запущено 🚀") % {'id': task.id})


@admin.register(AutoPostConfig)
class AutoPostConfigAdmin(admin.ModelAdmin):
    change_form_template = "admin/tasks/autopostconfig/change_form.html"
    list_display = (
        'id',
        'task_link',
        'status_badge',
        'progress_display',
        'next_pin_display',
        'queue_link',
        'board_name',
        'webhook_token_short',
        'started_at',
        'finished_at',
    )
    list_filter = ('status', 'started_at', 'use_uniqueness')
    search_fields = ('task__name', 'board_name', 'webhook_token')
    readonly_fields = (
        'task',
        'posted_count',
        'total_count',
        'celery_task_id',
        'started_at',
        'finished_at',
        'created_at',
        'updated_at',
    )
    list_select_related = ('task', 'task__owner')
    ordering = ('-created_at',)

    fieldsets = (
        (_("Основная информация"), {
            "fields": ("task", "status", "started_at", "finished_at")
        }),
        (_("Прогресс"), {
            "fields": ("posted_count", "total_count")
        }),
        (_("Настройки Pinterest"), {
            "fields": ("webhook_token", "board_name")
        }),
        (_("Настройки интервалов"), {
            "fields": ("min_interval", "max_interval", "site_url")
        }),
        (_("Настройки уникализации"), {
            "fields": ("use_uniqueness", "groq_api_key", "groq_prompt")
        }),
        (_("Техническая информация"), {
            "fields": ("celery_task_id", "error_message", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def status_badge(self, obj):
        colors = {
            AutoPostStatus.IDLE: "#999",
            AutoPostStatus.RUNNING: "#0d6efd",
            AutoPostStatus.PAUSED: "#ffc107",
            AutoPostStatus.COMPLETED: "#198754",
            AutoPostStatus.ERROR: "#dc3545",
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.status, "#000"),
            obj.get_status_display().upper(),
        )
    status_badge.short_description = _("Статус")

    def task_link(self, obj):
        url = reverse('admin:tasks_parsetask_change', args=[obj.task.id])
        return format_html('<a href="{}">{}</a>', url, obj.task.name)
    task_link.short_description = _("Задание")

    def progress_display(self, obj):
        if obj.total_count == 0:
            return "0%"
        percentage = (obj.posted_count / obj.total_count) * 100
        color = "#198754" if percentage == 100 else "#0d6efd"
        percentage_str = f"{percentage:.1f}"
        return format_html(
            '<b style="color:{}">{}/{} ({}%)</b>',
            color,
            obj.posted_count,
            obj.total_count,
            percentage_str
        )
    progress_display.short_description = _("Прогресс")

    def _get_next_queue_item(self, obj):
        return (
            AutoPostQueue.objects.select_related('pin')
            .filter(config=obj, status=PostQueueStatus.PENDING)
            .order_by('scheduled_at', 'id')
            .first()
        )

    def next_pin_display(self, obj):
        next_item = self._get_next_queue_item(obj)

        if not next_item:
            return "-"

        next_time = timezone.localtime(next_item.scheduled_at).strftime("%d.%m.%Y %H:%M")
        return format_html(
            '<b>{}</b><br><small>{} #{}</small>',
            next_time,
            _("Пин"),
            next_item.pin_id,
        )
    next_pin_display.short_description = _("Следующий пин")

    def queue_link(self, obj):
        url = reverse('admin:tasks_autopostqueue_changelist') + f'?config__id__exact={obj.id}'
        return format_html('<a class="button" href="{}">📋 {}</a>', url, _("Очередь"))
    queue_link.short_description = _("Очередь")

    def webhook_token_short(self, obj):
        if not obj.webhook_token:
            return "-"
        token_str = str(obj.webhook_token)
        return f"{token_str[:8]}...{token_str[-4:]}"
    webhook_token_short.short_description = _("Webhook токен")

    def has_add_permission(self, request):
        return False

    def response_change(self, request, obj):
        from django.shortcuts import redirect
        from django.contrib import messages
        from .tasks import initialize_autopost_queue
        from .services.autopost_test_service import test_autopost_config

        if "_start_autopost" in request.POST:
            if obj.status == AutoPostStatus.RUNNING:
                messages.warning(request, _("Автопостинг уже запущен"))
            elif not obj.webhook_token or not obj.board_name:
                messages.error(request, _("Заполните webhook токен и название доски перед запуском"))
            else:
                initialize_autopost_queue.delay(obj.id)
                messages.success(request, _("Автопостинг запущен. Очередь создается..."))
            return redirect('admin:tasks_autopostconfig_change', obj.id)

        if "_stop_autopost" in request.POST:
            if obj.status == AutoPostStatus.RUNNING:
                obj.status = AutoPostStatus.PAUSED
                obj.save(update_fields=['status'])
                messages.success(request, _("Автопостинг остановлен"))
            else:
                messages.warning(request, _("Автопостинг не запущен"))
            return redirect('admin:tasks_autopostconfig_change', obj.id)

        if "_test_autopost" in request.POST:
            if not obj.webhook_token or not obj.board_name:
                messages.error(request, _("Заполните webhook токен и название доски перед тестом"))
            else:
                result = test_autopost_config(obj)
                if result['success']:
                    messages.success(
                        request,
                        _("Пин #%(pin_id)s успешно опубликован! Статус: %(status)s") % {
                            'pin_id': result['pin_id'],
                            'status': result['response_status']
                        }
                    )
                else:
                    messages.error(request, _("Ошибка публикации пина: %(error)s") % {'error': result['error']})
            return redirect('admin:tasks_autopostconfig_change', obj.id)

        if "_check_next_pin" in request.POST:
            next_item = self._get_next_queue_item(obj)

            if not next_item:
                messages.info(request, _("В очереди нет пинов в статусе ожидания"))
            else:
                next_time = timezone.localtime(next_item.scheduled_at).strftime("%d.%m.%Y %H:%M")
                status_text = ""
                if obj.status != AutoPostStatus.RUNNING:
                    status_text = _(" Сейчас автопостинг не запущен, поэтому пин будет опубликован после возобновления.")

                messages.success(
                    request,
                    _("Следующий пин #%(pin_id)s запланирован на %(time)s.%(status)s") % {
                        'pin_id': next_item.pin_id,
                        'time': next_time,
                        'status': status_text
                    }
                )
            return redirect('admin:tasks_autopostconfig_change', obj.id)

        return super().response_change(request, obj)

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = AutoPostConfig.objects.get(pk=obj.pk)
            super().save_model(request, obj, form, change)

            if old_obj.min_interval != obj.min_interval or old_obj.max_interval != obj.max_interval:
                from apps.tasks.models import AutoPostQueue, PostQueueStatus
                from django.utils import timezone
                import random
                from datetime import timedelta

                pending_items = AutoPostQueue.objects.filter(
                    config=obj,
                    status=PostQueueStatus.PENDING
                ).order_by('scheduled_at')

                if pending_items.exists():
                    current_time = timezone.now()
                    prev_time = current_time

                    for idx, item in enumerate(pending_items):
                        if idx == 0:
                            item.scheduled_at = max(item.scheduled_at, current_time)
                            prev_time = item.scheduled_at
                        else:
                            delay_minutes = random.randint(obj.min_interval, obj.max_interval)
                            item.scheduled_at = prev_time + timedelta(minutes=delay_minutes)
                            prev_time = item.scheduled_at

                        item.save(update_fields=['scheduled_at'])

                    messages.info(request, _("Пересчитано расписание для %(count)s пинов с новыми интервалами") % {'count': pending_items.count()})
        else:
            super().save_model(request, obj, form, change)


@admin.register(AutoPostQueue)
class AutoPostQueueAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'config',
        'pin',
        'status',
        'scheduled_at',
        'posted_at',
        'attempts',
    )
    list_filter = ('status', 'scheduled_at', 'config')
    search_fields = ('config__task__name', 'pin__title', 'pin__id')
    list_select_related = ('config', 'config__task', 'pin')
    readonly_fields = ('config', "pin", "scheduled_at", "posted_at", "attempts")
    ordering = ('scheduled_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('config', 'config__task', 'pin')

    def has_add_permission(self, request):
        return False
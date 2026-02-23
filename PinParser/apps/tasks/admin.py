import zipfile
import os
from io import BytesIO

from django.core.cache import cache
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponse
from django import forms
from celery.result import AsyncResult
from .models import ParseTask, TaskStatus
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
        help_text="Введіть ключові слова, кожне з нового рядка",
        label="Ключові слова (текст)",
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
    list_display = ('name', 'owner', 'status_badge', 'progress_display', 'error_message', 'view_results_link', 'download_excel', 'created_at')
    list_filter = ('status', 'created_at', 'use_uniqueness')
    search_fields = ('name', 'keywords')
    exclude = ('keywords', 'celery_task_id')

    readonly_fields = (
        "error_message",
        "started_at",
        "finished_at",
        "processed_urls",
        "total_urls",
    )

    fieldsets = (
        ("Основне", {
            "fields": ("name", "keywords_text", "threads")
        }),
        ("Опції", {
            "fields": ("use_uniqueness", "uniqueness_config")
        }),
        ("Статус", {
            "fields": (
                "status",
                "error_message",
                "processed_urls",
                "total_urls",
            )
        }),
        ("Дати", {
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
    status_badge.short_description = "Статус"


    actions = ['start_tasks', 'stop_task', 'export_to_excel', 'uniqueness_task', 'generate_slug_task', 'download_files']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)

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

    download_excel.short_description = "Excel"

    def view_results_link(self, obj):
        url = reverse('admin:results_pinresult_changelist') + f'?task__id__exact={obj.id}'
        return format_html('<a class="button" href="{}">📊 Результати</a>', url)
    view_results_link.short_description = "Результати"

    def progress_display(self, obj):
        parsed = obj.results.count()
        return f"{parsed}/{obj.total_urls}"
    progress_display.short_description = "Вдало оброблено/Знайдено пінів"

    def start_tasks(self, request, queryset):
        PinterestAccount.objects.update(status=AccountStatus.ACTIVE)
        Proxy.objects.update(status=ProxyStatus.ACTIVE)

        for task in queryset:

            self.start_task(request, task)

        self.message_user(request, "Завдання запущені")
    start_tasks.short_description = "▶️ Запустити вибрані завдання"

    def stop_task(self, request, queryset):

        stopped = 0

        for task in queryset:

            if not task.celery_task_id:
                continue

            if task.status == TaskStatus.RUNNING:
                cache.set(f"stop_task_{task.id}", True, timeout=3600)
                app.control.revoke(task.celery_task_id)

            elif task.status in (
                TaskStatus.UNIQUENESS,
            ):
                app.control.revoke(
                    task.celery_task_id,
                    terminate=True,
                    signal="SIGTERM",
                )

            else:
                continue

            task.status = TaskStatus.STOPPED
            task.save(update_fields=["status"])

            stopped += 1

        self.message_user(request, f"Зупинено задач: {stopped}")
    stop_task.short_description = "⛔ Зупинити виконання вибраних завдань"

    @admin.action(description="📤 Експорт у Excel")
    def export_to_excel(self, request, queryset):
        for task in queryset:
            export_results_to_excel.delay(task.id)

    @admin.action(description="Унікалізувати")
    def uniqueness_task(self, request, queryset):
        for task in queryset:
            run_uniqueness.delay(task.id)

    @admin.action(description="Згенерувати slug")
    def generate_slug_task(self, request, queryset):
        for task in queryset:
            generate_slugs.delay(task.id)

    @admin.action(description="⬇️ Завантажити вибрані файли")
    def download_files(self, request, queryset):
        files = queryset.exclude(export_file="")

        if not files.exists():
            self.message_user(request, "Немає файлів для завантаження")
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
            self.message_user(request, "Завдання збережено і запущено 🚀")
            return super().response_add(request, obj, post_url_continue)

        return super().response_add(request, obj, post_url_continue)
    
    def start_task(self, request, task):

        lock_key = f"parse_task_lock_{task.id}"

        if cache.get(lock_key):
            self.message_user(
                request,
                level="WARNING",
                message=f"Task {task.id} вже виконується"
            )
            return
            
        cache.set(lock_key, True, timeout=10800)

        result = run_parse_task.delay(task.id)

        task.celery_task_id = result.id
        task.status = TaskStatus.RUNNING
        task.save(update_fields=["celery_task_id", "status"])
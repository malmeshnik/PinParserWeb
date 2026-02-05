from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django import forms
from .models import ParseTask, TaskStatus
from .tasks import run_parse_task
from apps.results.tasks import export_results_to_sheets

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
    list_display = ('name', 'owner', 'status_badge', 'progress_display', 'error_message', 'view_results_link', 'created_at')
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
            "fields": ("use_uniqueness",)
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


    actions = ['start_task', 'stop_task', 'export_to_sheets']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.owner:
            obj.owner = request.user
        super().save_model(request, obj, form, change)

    def view_results_link(self, obj):
        url = reverse('admin:results_pinresult_changelist') + f'?task__id__exact={obj.id}'
        return format_html('<a class="button" href="{}">📊 Результати</a>', url)
    view_results_link.short_description = "Результати"

    def progress_display(self, obj):
        if obj.total_urls > 0:
            percentage = (obj.processed_urls / obj.total_urls) * 100
            return f"{obj.processed_urls}/{obj.total_urls} ({percentage:.1f}%)"
        return f"{obj.processed_urls}/0"
    progress_display.short_description = "Прогрес"

    def start_task(self, request, queryset):
        for task in queryset:
            if task.status != TaskStatus.RUNNING:
                run_parse_task.delay(task.id)
        self.message_user(request, "Завдання запущені")
    start_task.short_description = "▶️ Запустити вибрані завдання"

    def stop_task(self, request, queryset):
        queryset.update(status=TaskStatus.STOPPED)
        self.message_user(request, "Завдання зупинені")
    stop_task.short_description = "⏹️ Зупинити вибрані завдання"

    @admin.action(description="📤 Експорт у Google Sheets")
    def export_to_sheets(self, request, queryset):
        for task in queryset:
            export_results_to_sheets.delay(task.id)
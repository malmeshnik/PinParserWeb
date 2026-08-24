from django import forms
from django.contrib import admin
from django.contrib.admin.helpers import ActionForm
from django.utils.html import format_html

from .models import PinResult


class AnnotationFilterActionForm(ActionForm):
    words = forms.CharField(
        label='Слова для фільтра',
        help_text='Вкажіть слова через кому. Усі вони повинні міститися в annotation, незалежно від регістру та місця.',
        required=True,
    )


@admin.register(PinResult)
class PinResultAdmin(admin.ModelAdmin):
    action_form = AnnotationFilterActionForm
    actions = ['filter_by_annotation_words']
    list_display = ('image_preview', 'pin_url', 'task', 'keyword', 'title', 'annotation', 'utitle', 'slug_url', 'created_at')
    list_filter = ('task', 'keyword')
    search_fields = ('pin_url', 'title', 'description', 'keyword')
    readonly_fields = ('created_at',)

    @admin.display(description='Фото')
    def image_preview(self, obj):
        image_url = None

        if getattr(obj, 'local_image', None) and obj.local_image:
            image_url = obj.local_image.url
        elif getattr(obj, 'image_url', None):
            image_url = obj.image_url

        if not image_url:
            return '-'

        return format_html(
            '<img src="{}" alt="{}" style="max-width: 80px; max-height: 80px; object-fit: cover; border-radius: 4px;" />',
            image_url,
            obj.title or obj.pin_url or 'pin preview',
        )

    @admin.action(description='🧹 Видалити піни без слів в annotation')
    def filter_by_annotation_words(self, request, queryset):
        words_input = request.POST.get('words', '').strip()
        if not words_input:
            self.message_user(request, 'Вкажіть хоча б одне слово через кому.', level='error')
            return

        required_words = [word.strip().lower() for word in words_input.split(',') if word.strip()]
        if not required_words:
            self.message_user(request, 'Вкажіть корректні слова через кому.', level='error')
            return

        deleted = 0
        for pin in queryset:
            annotation_text = (pin.annotation or '').lower()
            if any(word not in annotation_text for word in required_words):
                pin.delete()
                deleted += 1

        self.message_user(
            request,
            f'Видалено {deleted} піна(ів), у яких відсутнє хоча б одне зі слів в annotation.',
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(task__owner=request.user)

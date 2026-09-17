from django.contrib import admin
from .models import UniquenessConfig

@admin.register(UniquenessConfig)
class UniquenessConfigAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = (
        'id',
        'name',
        'is_active',
        'uniqueness_method',
        'created_at'
    )
    list_editable = ('is_active',)
    list_filter = ('uniqueness_method', 'is_active')

    fieldsets = (
        ('Основні налаштування', {
            'fields': ('name', 'is_active', 'uniqueness_method')
        }),
        ('OpenAI налаштування', {
            'fields': ('openai_api_key', 'model'),
            'classes': ('collapse',),
            'description': 'Налаштування для OpenAI GPT методу унікалізації'
        }),
        ('Omniroute налаштування', {
            'fields': (
                'omniroute_api_key',
                'omniroute_base_url',
                'omniroute_model'
            ),
            'classes': ('collapse',),
            'description': 'Налаштування для Omniroute методу унікалізації'
        }),
        ('Параметри генерації', {
            'fields': (
                'temperature',
                'max_tokens_title',
                'max_tokens_description',
            )
        }),
        ('Промпт', {
            'fields': ('prompt_template',),
        }),
        ('Використовувані поля', {
            'fields': (
                'use_title',
                'use_description',
                'use_alt_text',
                'use_annotation',
                'use_domain',
                'use_image_url',
                'use_keyword',
            ),
            'classes': ('collapse',),
        }),
        ('Продуктивність', {
            'fields': ('max_requests_per_minute', 'max_workers'),
            'classes': ('collapse',),
        }),
    )

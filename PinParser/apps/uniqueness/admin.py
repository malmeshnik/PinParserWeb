from django.contrib import admin
from .models import UniquenessConfig

@admin.register(UniquenessConfig)
class UniquenessConfigAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'name', 'is_active', 'model_provider', 'get_model', 'created_at')
    list_editable = ('is_active',)
    list_filter = ('is_active', 'model_provider')
    search_fields = ('name',)

    def get_model(self, obj):
        """Відображає модель на основі провайдера"""
        return obj.model
    get_model.short_description = 'Модель'

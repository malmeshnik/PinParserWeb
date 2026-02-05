from django.contrib import admin
from .models import UniquenessConfig

@admin.register(UniquenessConfig)
class UniquenessConfigAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'is_active', 'model', 'created_at')
    list_editable = ('is_active',)

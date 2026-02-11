from django.contrib import admin
from .models import ErrorLog

@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('created_at', 'level', 'task', 'account', 'message_short')
    list_filter = ('level', 'created_at')
    search_fields = ('message', 'task__name')
    readonly_fields = ('created_at', 'level', 'task', 'account', 'message')

    def message_short(self, obj):
        return obj.message[:100]
    message_short.short_description = "Повідомлення"

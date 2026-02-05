from django.contrib import admin
from .models import PinterestAccount

@admin.register(PinterestAccount)
class PinterestAccountAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'name', 'proxy', 'status', 'fail_count', 'last_used_at', 'is_active')
    list_filter = ('status', 'is_active')
    search_fields = ('name',)

    actions = ['rotate_proxy_action']

    def rotate_proxy_action(self, request, queryset):
        count = 0
        for account in queryset:
            if account.rotate_proxy():
                count += 1
        self.message_user(request, f"Проксі змінено для {count} аккаунтів")
    rotate_proxy_action.short_description = "🔄 Ротувати проксі"

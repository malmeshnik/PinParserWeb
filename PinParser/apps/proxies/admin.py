from django.contrib import admin
from .models import Proxy, NineProxyConfig

@admin.register(NineProxyConfig)
class NineProxyConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'country', 'state', 'city', 'updated_at')

    def has_add_permission(self, request):
        # Only allow one config
        return not NineProxyConfig.objects.exists()

@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'name', 'host', 'port', 'country', 'status', 'last_checked_at', 'is_active')
    list_filter = ('status', 'is_active', 'country')
    search_fields = ('name', 'host', 'isp')

    actions = ['check_health_action']

    def check_health_action(self, request, queryset):
        for proxy in queryset:
            proxy.check_health()
        self.message_user(request, "Здоров'я проксі перевірено")
    check_health_action.short_description = "🧪 Перевірити здоров'я"

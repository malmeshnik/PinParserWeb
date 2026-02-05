from django.contrib import admin
from .models import PinResult

@admin.register(PinResult)
class PinResultAdmin(admin.ModelAdmin):
    list_display = ('pin_url', 'task', 'keyword', 'title', 'created_at')
    list_filter = ('task', 'keyword')
    search_fields = ('pin_url', 'title', 'description', 'keyword')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(task__owner=request.user)

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from .monitoring import collect


@staff_member_required
def monitoring_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    context = {
        **collect(),
        'title': 'Моніторинг',
        'has_permission': True,
        'site_header': 'PinParser',
    }
    return render(request, 'analytics/dashboard.html', context)

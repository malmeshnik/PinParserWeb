from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from apps.tasks.models import ParseTask, TaskStatus
from apps.logs.models import ErrorLog
from django.db.models import Count, Sum

@staff_member_required
def analytics_dashboard(request):
    total_tasks = ParseTask.objects.count()
    successful_tasks = ParseTask.objects.filter(status=TaskStatus.DONE).count()
    failed_tasks = ParseTask.objects.filter(status=TaskStatus.ERROR).count()
    total_pins = ParseTask.objects.aggregate(Sum('total_urls'))['total_urls__sum'] or 0

    recent_errors = ErrorLog.objects.all()[:20]

    context = {
        'total_tasks': total_tasks,
        'successful_tasks': successful_tasks,
        'failed_tasks': failed_tasks,
        'total_pins': total_pins,
        'recent_errors': recent_errors,
        'title': 'Аналітика'
    }
    return render(request, 'analytics/dashboard.html', context)

from django import forms
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .models import ParseTask, TaskStatus, AutoPostConfig, AutoPostStatus
from .serializers import ParseTaskSerializer, CreateTaskSerializer
from .tasks import run_parse_task, initialize_autopost_queue
from config.celery import app
from .services.autopost_test_service import test_autopost_config

@extend_schema(tags=['Tasks'])
class TaskViewSet(viewsets.ModelViewSet):
    queryset = ParseTask.objects.all()
    serializer_class = ParseTaskSerializer

    def get_queryset(self):
        if self.request.user.is_superuser:
            return ParseTask.objects.all()
        return ParseTask.objects.filter(owner=self.request.user)

    @extend_schema(
        request=CreateTaskSerializer,
        responses={201: ParseTaskSerializer},
        description="Створити нове завдання на парсинг та запустити його."
    )
    def create(self, request, *args, **kwargs):
        serializer = CreateTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(owner=request.user)
        # Start the task automatically
        run_parse_task.delay(task.id)
        return Response(ParseTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Завдання зупиняється")},
        description="Зупинити виконання завдання."
    )
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        task = self.get_object()
        task.status = TaskStatus.STOPPED
        task.save(update_fields=['status'])
        return Response({'status': 'task stopping'})

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Завдання перезапущено")},
        description="Перезапустити виконання завдання."
    )
    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        task = self.get_object()
        task.status = TaskStatus.PENDING
        task.save(update_fields=['status'])
        run_parse_task.delay(task.id)
        return Response({'status': 'task restarted'})


class AutoPostConfigForm(forms.ModelForm):
    class Meta:
        model = AutoPostConfig
        fields = [
            'webhook_token',
            'board_name',
            'min_interval',
            'max_interval',
            'site_url',
            'use_uniqueness',
            'groq_api_key',
            'groq_prompt',
        ]
        widgets = {
            'webhook_token': forms.TextInput(attrs={'class': 'vTextField', 'size': '40'}),
            'board_name': forms.TextInput(attrs={'class': 'vTextField'}),
            'min_interval': forms.NumberInput(attrs={'class': 'vIntegerField'}),
            'max_interval': forms.NumberInput(attrs={'class': 'vIntegerField'}),
            'site_url': forms.URLInput(attrs={'class': 'vURLField', 'size': '60'}),
            'groq_api_key': forms.TextInput(attrs={'class': 'vTextField', 'size': '60'}),
            'groq_prompt': forms.Textarea(attrs={'class': 'vLargeTextField', 'rows': 10, 'cols': 80}),
        }


@staff_member_required
def autopost_settings_view(request, task_id):
    """View для налаштування автопостингу"""
    task = get_object_or_404(ParseTask, id=task_id)

    # Перевірка прав доступу
    if not request.user.is_superuser and task.owner != request.user:
        messages.error(request, "У вас немає доступу до цього завдання")
        return redirect('admin:tasks_parsetask_changelist')

    config, created = AutoPostConfig.objects.get_or_create(task=task)

    if request.method == 'POST':
        action_type = request.POST.get('action')

        if action_type == 'save':
            form = AutoPostConfigForm(request.POST, instance=config)
            if form.is_valid():
                old_min = config.min_interval
                old_max = config.max_interval

                form.save()

                # Якщо змінились інтервали і є pending піни в черзі, перерахувати scheduled_at
                if (old_min != config.min_interval or old_max != config.max_interval):
                    from apps.tasks.models import AutoPostQueue, PostQueueStatus
                    from django.utils import timezone
                    import random
                    from datetime import timedelta

                    pending_items = AutoPostQueue.objects.filter(
                        config=config,
                        status=PostQueueStatus.PENDING
                    ).order_by('scheduled_at')

                    if pending_items.exists():
                        # Перерахувати інтервали починаючи з поточного часу
                        current_time = timezone.now()

                        for idx, item in enumerate(pending_items):
                            if idx == 0:
                                # Перший пін - зараз або його оригінальний час (якщо він пізніше)
                                item.scheduled_at = max(item.scheduled_at, current_time)
                            else:
                                # Наступні піни - з новими інтервалами
                                delay_minutes = random.randint(config.min_interval, config.max_interval)
                                prev_item = pending_items[idx - 1]
                                item.scheduled_at = prev_item.scheduled_at + timedelta(minutes=delay_minutes)

                            item.save(update_fields=['scheduled_at'])

                        messages.info(request, f"Перераховано розклад для {pending_items.count()} пінів з новими інтервалами")

                messages.success(request, "Налаштування збережено")
                return redirect('autopost_settings', task_id=task_id)

        elif action_type == 'start':
            if config.status == AutoPostStatus.RUNNING:
                messages.warning(request, "Автопостинг вже запущено")
            elif not config.webhook_token or not config.board_name:
                messages.error(request, "Заповніть webhook токен та назву дошки перед запуском")
            else:
                # Запускаємо ініціалізацію черги
                initialize_autopost_queue.delay(config.id)
                messages.success(request, "Автопостинг запущено. Черга створюється...")
            return redirect('autopost_settings', task_id=task_id)

        elif action_type == 'stop':
            if config.status == AutoPostStatus.RUNNING:
                config.status = AutoPostStatus.PAUSED
                config.save(update_fields=['status'])
                messages.success(request, "Автопостинг зупинено")
            else:
                messages.warning(request, "Автопостинг не запущено")
            return redirect('autopost_settings', task_id=task_id)

        elif action_type == 'test':
            if not config.webhook_token or not config.board_name:
                messages.error(request, "Заповніть webhook токен та назву дошки перед тестом")
            else:
                # Викликаємо синхронний тест
                result = test_autopost_config(config)

                if result['success']:
                    messages.success(
                        request,
                        f"Пін #{result['pin_id']} успішно опубліковано! "
                        f"Статус: {result['response_status']}"
                    )
                else:
                    messages.error(
                        request,
                        f"Помилка публікації піна: {result['error']}"
                    )
            return redirect('autopost_settings', task_id=task_id)

    else:
        form = AutoPostConfigForm(instance=config)

    context = {
        'task': task,
        'config': config,
        'form': form,
        'title': f'Налаштування автопостингу для завдання: {task.name}',
        'opts': ParseTask._meta,
        'has_view_permission': True,
        'site_header': 'PinParser Administration',
    }

    return render(request, 'admin/tasks/autopost_settings.html', context)

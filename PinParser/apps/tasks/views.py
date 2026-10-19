from django import forms
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from .models import ParseTask, AutoPostConfig, AutoPostUniquenessConfig, PostQueueStatus
from .serializers import (
    ParseTaskSerializer, CreateTaskSerializer,
    AutoPostConfigSerializer, AutoPostQueueSerializer,
    AutoPostUniquenessConfigSerializer, ChangeModelSerializer,
)
from .services.task_control import start_parse_task, stop_parse_task
from .services.autopost_service import reschedule_pending, start_autopost, stop_autopost, AutoPostError
from .services.autopost_test_service import test_autopost_config
from .services.autopost_uniqueness_service import AutoPostUniquenessService

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
        start_parse_task(task)
        return Response(ParseTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Завдання зупиняється")},
        description="Зупинити виконання завдання."
    )
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        task = self.get_object()
        if not stop_parse_task(task):
            return Response({'status': 'task is not running'}, status=status.HTTP_409_CONFLICT)
        return Response({'status': 'task stopping'})

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Завдання перезапущено")},
        description="Перезапустити виконання завдання."
    )
    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        task = self.get_object()
        if not start_parse_task(task):
            return Response({'status': 'task is already running'}, status=status.HTTP_409_CONFLICT)
        return Response({'status': 'task restarted'})


@extend_schema(tags=['Autopost'])
class AutoPostConfigViewSet(viewsets.ModelViewSet):
    """Налаштування автопостингу завдань. Одне налаштування на завдання."""
    queryset = AutoPostConfig.objects.all()
    serializer_class = AutoPostConfigSerializer

    def get_queryset(self):
        qs = AutoPostConfig.objects.select_related('task', 'uniqueness_config').order_by('-created_at')
        if not self.request.user.is_superuser:
            qs = qs.filter(task__owner=self.request.user)

        task_id = self.request.query_params.get('task_id')
        if task_id:
            qs = qs.filter(task_id=task_id)
        return qs

    @extend_schema(
        parameters=[OpenApiParameter(name='task_id', description='Фільтр за ID завдання', required=False, type=int)],
        description="Список налаштувань автопостингу ваших завдань."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_update(self, serializer):
        old = serializer.instance
        intervals_before = (old.min_interval, old.max_interval)
        config = serializer.save()
        # Як в адмінці: при зміні інтервалів перераховуємо розклад черги
        if intervals_before != (config.min_interval, config.max_interval):
            reschedule_pending(config)

    def _run(self, func, config, success_message):
        try:
            func(config)
        except AutoPostError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({'detail': success_message})

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Автопостинг запускається")},
                   description="Запустити автопостинг (або відновити після паузи).")
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._run(start_autopost, self.get_object(), "Автопостинг запущено. Черга створюється...")

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Автопостинг на паузі")},
                   description="Поставити автопостинг на паузу.")
    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        return self._run(stop_autopost, self.get_object(), "Автопостинг зупинено")

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Результат тестової публікації")},
                   description="Опублікувати один пін зараз (перший з черги або з результатів) для перевірки налаштувань.")
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        config = self.get_object()
        if not config.webhook_token or not config.board_name:
            return Response({'detail': "Заповніть webhook токен та назву дошки перед тестом"},
                            status=status.HTTP_400_BAD_REQUEST)
        result = test_autopost_config(config)
        return Response(result, status=status.HTTP_200_OK if result['success'] else status.HTTP_502_BAD_GATEWAY)

    @extend_schema(
        parameters=[
            OpenApiParameter(name='status', description='pending / posted / failed / skipped', required=False, type=str),
            OpenApiParameter(name='limit', description='Кількість записів (за замовчуванням 100, максимум 1000)', required=False, type=int),
        ],
        responses={200: AutoPostQueueSerializer(many=True)},
        description="Черга постів у порядку публікації."
    )
    @action(detail=True, methods=['get'])
    def queue(self, request, pk=None):
        items = self.get_object().queue_items.select_related('pin').order_by('scheduled_at', 'id')

        queue_status = request.query_params.get('status')
        if queue_status:
            if queue_status not in PostQueueStatus.values:
                allowed = ", ".join(PostQueueStatus.values)
                return Response({'detail': f"Невідомий статус. Можливі: {allowed}"},
                                status=status.HTTP_400_BAD_REQUEST)
            items = items.filter(status=queue_status)

        try:
            limit = min(max(int(request.query_params.get('limit', 100)), 1), 1000)
        except ValueError:
            limit = 100
        return Response(AutoPostQueueSerializer(items[:limit], many=True).data)


@extend_schema(tags=['Autopost uniqueness'])
class AutoPostUniquenessConfigViewSet(viewsets.ModelViewSet):
    """Конфіги уникалізації для автопостингу (Groq): ключ, модель, промпт. Тільки для адміністраторів."""
    permission_classes = [permissions.IsAdminUser]
    queryset = AutoPostUniquenessConfig.objects.all()
    serializer_class = AutoPostUniquenessConfigSerializer

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Результат тестового запиту")},
                   description="Тестовий запит до Groq з цим конфігом.")
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        service = AutoPostUniquenessService(self.get_object())
        result = service.uniquify(
            title="Cozy autumn living room ideas",
            description="Warm colors, soft blankets and candles for a cozy home.",
        )
        if result:
            return Response({'success': True, 'result': result})
        return Response({'success': False, 'error': service.last_error}, status=status.HTTP_502_BAD_GATEWAY)

    @extend_schema(request=ChangeModelSerializer,
                   responses={200: OpenApiResponse(description="Кількість оновлених конфігів")},
                   description="Змінити модель на всіх конфігах (або лише на переданих ids).")
    @action(detail=False, methods=['post'], url_path='change-model')
    def change_model(self, request):
        serializer = ChangeModelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        qs = AutoPostUniquenessConfig.objects.all()
        ids = serializer.validated_data.get('ids')
        if ids:
            qs = qs.filter(id__in=ids)

        model = serializer.validated_data['model'].strip()
        updated = qs.update(model=model, updated_at=timezone.now())
        return Response({'model': model, 'updated': updated})


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
            'uniqueness_config',
        ]
        widgets = {
            'webhook_token': forms.TextInput(attrs={'class': 'vTextField', 'size': '40'}),
            'board_name': forms.TextInput(attrs={'class': 'vTextField'}),
            'min_interval': forms.NumberInput(attrs={'class': 'vIntegerField'}),
            'max_interval': forms.NumberInput(attrs={'class': 'vIntegerField'}),
            'site_url': forms.URLInput(attrs={'class': 'vURLField', 'size': '60'}),
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

                if old_min != config.min_interval or old_max != config.max_interval:
                    count = reschedule_pending(config)
                    if count:
                        messages.info(request, f"Перераховано розклад для {count} пінів з новими інтервалами")

                messages.success(request, "Налаштування збережено")
                return redirect('autopost_settings', task_id=task_id)

        elif action_type == 'start':
            try:
                start_autopost(config)
                messages.success(request, "Автопостинг запущено. Черга створюється...")
            except AutoPostError as e:
                messages.warning(request, str(e))
            return redirect('autopost_settings', task_id=task_id)

        elif action_type == 'stop':
            try:
                stop_autopost(config)
                messages.success(request, "Автопостинг зупинено")
            except AutoPostError as e:
                messages.warning(request, str(e))
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

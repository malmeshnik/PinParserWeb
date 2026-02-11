from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .models import ParseTask, TaskStatus
from .serializers import ParseTaskSerializer, CreateTaskSerializer
from .tasks import run_parse_task

@extend_schema(tags=['Tasks'])
class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
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

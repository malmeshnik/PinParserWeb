from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import ParseTask, TaskStatus
from .serializers import ParseTaskSerializer, CreateTaskSerializer
from .tasks import run_parse_task

class TaskViewSet(viewsets.ModelViewSet):
    queryset = ParseTask.objects.all()
    serializer_class = ParseTaskSerializer

    def get_queryset(self):
        if self.request.user.is_superuser:
            return ParseTask.objects.all()
        return ParseTask.objects.filter(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = CreateTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(owner=request.user)
        # Start the task automatically
        run_parse_task.delay(task.id)
        return Response(ParseTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        task = self.get_object()
        task.status = TaskStatus.STOPPED
        task.save(update_fields=['status'])
        return Response({'status': 'task stopping'})

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        task = self.get_object()
        task.status = TaskStatus.PENDING
        task.save(update_fields=['status'])
        run_parse_task.delay(task.id)
        return Response({'status': 'task restarted'})

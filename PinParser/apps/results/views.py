from rest_framework import viewsets, permissions
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import PinResult
from .serializers import PinResultSerializer

@extend_schema(tags=['Results'])
class PinResultViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = PinResult.objects.all()
    serializer_class = PinResultSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(name='task_id', description='Фільтрація результатів за ID завдання', required=False, type=int),
        ],
        description="Отримати список результатів парсингу. Звичайні користувачі бачать лише свої результати."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(task__owner=self.request.user)

        task_id = self.request.query_params.get('task_id')
        if task_id:
            queryset = queryset.filter(task_id=task_id)
        return queryset

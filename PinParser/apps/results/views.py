from rest_framework import viewsets
from .models import PinResult
from .serializers import PinResultSerializer

class PinResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PinResult.objects.all()
    serializer_class = PinResultSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(task__owner=self.request.user)

        task_id = self.request.query_params.get('task_id')
        if task_id:
            queryset = queryset.filter(task_id=task_id)
        return queryset

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Proxy
from .serializers import ProxySerializer

class ProxyViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = Proxy.objects.all()
    serializer_class = ProxySerializer

    @action(detail=True, methods=['post'])
    def check_health(self, request, pk=None):
        proxy = self.get_object()
        is_active = proxy.check_health()
        return Response({'is_active': is_active, 'status': proxy.status})

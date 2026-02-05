from rest_framework import viewsets, permissions
from .models import UniquenessConfig
from .serializers import UniquenessConfigSerializer

class UniquenessConfigViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = UniquenessConfig.objects.all()
    serializer_class = UniquenessConfigSerializer

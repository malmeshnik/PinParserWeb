from rest_framework import viewsets, permissions
from drf_spectacular.utils import extend_schema
from .models import UniquenessConfig
from .serializers import UniquenessConfigSerializer

@extend_schema(tags=['Uniqueness'])
class UniquenessConfigViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = UniquenessConfig.objects.all()
    serializer_class = UniquenessConfigSerializer

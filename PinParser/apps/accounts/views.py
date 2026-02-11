from rest_framework import viewsets, permissions
from drf_spectacular.utils import extend_schema
from .models import PinterestAccount
from .serializers import PinterestAccountSerializer

@extend_schema(tags=['Accounts'])
class AccountViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = PinterestAccount.objects.all()
    serializer_class = PinterestAccountSerializer

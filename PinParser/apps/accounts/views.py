from rest_framework import viewsets, permissions
from .models import PinterestAccount
from .serializers import PinterestAccountSerializer

class AccountViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = PinterestAccount.objects.all()
    serializer_class = PinterestAccountSerializer

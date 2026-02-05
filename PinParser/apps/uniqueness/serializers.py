from rest_framework import serializers
from .models import UniquenessConfig

class UniquenessConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = UniquenessConfig
        fields = '__all__'

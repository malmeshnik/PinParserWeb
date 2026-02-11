from rest_framework import serializers
from .models import PinResult

class PinResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PinResult
        fields = '__all__'

from rest_framework import serializers
from .models import PinterestAccount

class PinterestAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PinterestAccount
        fields = '__all__'

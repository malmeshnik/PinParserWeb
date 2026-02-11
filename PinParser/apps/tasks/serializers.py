from rest_framework import serializers
from .models import ParseTask

class ParseTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParseTask
        fields = '__all__'
        read_only_fields = ('celery_task_id', 'status', 'total_urls', 'processed_urls', 'created_at', 'started_at', 'finished_at', 'error_message')

class CreateTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParseTask
        fields = ('name', 'keywords', 'threads', 'use_uniqueness', 'auto_sheet_name')

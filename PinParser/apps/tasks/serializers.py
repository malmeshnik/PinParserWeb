from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import ParseTask, AutoPostConfig, AutoPostQueue, AutoPostUniquenessConfig, PostQueueStatus

def normalize_keywords(value):
    """Список рядків; рядок розбивається по нових рядках і комах (інакше став би одним ключовим словом)."""
    if isinstance(value, str):
        value = value.replace(",", "\n").splitlines()
    if not isinstance(value, list):
        raise serializers.ValidationError("Очікується список рядків або рядок з ключовими словами")
    keywords = [str(k).strip() for k in value if str(k).strip()]
    if not keywords:
        raise serializers.ValidationError("Вкажіть хоча б одне ключове слово")
    return keywords


class ParseTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParseTask
        fields = '__all__'
        read_only_fields = ('owner', 'celery_task_id', 'status', 'total_urls', 'processed_urls', 'export_file', 'created_at', 'started_at', 'finished_at', 'error_message')

    def validate_keywords(self, value):
        return normalize_keywords(value)


class CreateTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParseTask
        fields = ('name', 'keywords', 'threads', 'use_uniqueness', 'uniqueness_config', 'annotation_filter_words', 'auto_sheet_name')

    def validate_keywords(self, value):
        return normalize_keywords(value)


class AutoPostConfigSerializer(serializers.ModelSerializer):
    next_post = serializers.SerializerMethodField(help_text="Наступний пін у черзі: {pin_id, scheduled_at}")

    class Meta:
        model = AutoPostConfig
        fields = (
            'id', 'task', 'webhook_token', 'board_name',
            'min_interval', 'max_interval', 'site_url',
            'use_uniqueness', 'uniqueness_config',
            'status', 'posted_count', 'total_count', 'error_message', 'next_post',
            'started_at', 'finished_at', 'created_at', 'updated_at',
        )
        read_only_fields = (
            'status', 'posted_count', 'total_count', 'error_message',
            'started_at', 'finished_at', 'created_at', 'updated_at',
        )

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_next_post(self, obj):
        item = obj.queue_items.filter(status=PostQueueStatus.PENDING).order_by('scheduled_at', 'id').first()
        if not item:
            return None
        return {'pin_id': item.pin_id, 'scheduled_at': item.scheduled_at}

    def validate_task(self, task):
        user = self.context['request'].user
        if not user.is_superuser and task.owner_id != user.id:
            raise serializers.ValidationError("Немає доступу до цього завдання")
        if self.instance and self.instance.task_id != task.id:
            raise serializers.ValidationError("Завдання не можна змінити")
        return task

    def validate(self, attrs):
        min_interval = attrs.get('min_interval', getattr(self.instance, 'min_interval', None))
        max_interval = attrs.get('max_interval', getattr(self.instance, 'max_interval', None))
        if min_interval is not None and max_interval is not None and min_interval > max_interval:
            raise serializers.ValidationError({'max_interval': "Максимальний інтервал має бути не меншим за мінімальний"})
        return attrs


class AutoPostQueueSerializer(serializers.ModelSerializer):
    pin_title = serializers.CharField(source='pin.title', read_only=True)

    class Meta:
        model = AutoPostQueue
        fields = ('id', 'pin', 'pin_title', 'status', 'scheduled_at', 'posted_at', 'attempts', 'error_message')


class AutoPostUniquenessConfigSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False)
    api_key_preview = serializers.SerializerMethodField(help_text="Ключ у маскованому вигляді")

    class Meta:
        model = AutoPostUniquenessConfig
        fields = ('id', 'name', 'is_active', 'api_key', 'api_key_preview', 'model', 'prompt', 'created_at', 'updated_at')
        read_only_fields = ('created_at', 'updated_at')

    def get_api_key_preview(self, obj) -> str:
        key = obj.api_key or ""
        return f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("***" if key else "")

    def validate(self, attrs):
        if not self.instance and not attrs.get('api_key'):
            raise serializers.ValidationError({'api_key': "Обов'язкове поле"})
        return attrs


class ChangeModelSerializer(serializers.Serializer):
    model = serializers.CharField(max_length=100)
    ids = serializers.ListField(
        child=serializers.IntegerField(), required=False,
        help_text="ID конфігів. Якщо не передано — модель зміниться на всіх конфігах",
    )

from django.db import migrations, models


# 0007 додавала колонки сирим SQL без оновлення стану міграцій (через це Django
# постійно пропонував нову міграцію) і пропускала omniroute_model.
# Тут реєструємо поля в стані та досоздаємо відсутні колонки.
COLUMNS = {
    'model_provider': "VARCHAR(50) NULL",
    'name': "VARCHAR(255) NULL",
    'uniqueness_method': "VARCHAR(20) NOT NULL DEFAULT 'gpt'",
    'omniroute_api_key': "VARCHAR(255) NOT NULL DEFAULT ''",
    'omniroute_base_url': "VARCHAR(255) NOT NULL DEFAULT 'http://localhost:20128/v1'",
    'omniroute_model': "VARCHAR(100) NOT NULL DEFAULT 'kr/deepseek-3.2'",
}


def add_missing_columns(apps, schema_editor):
    table_name = 'uniqueness_uniquenessconfig'
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

        for column, definition in COLUMNS.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")


class Migration(migrations.Migration):

    dependencies = [
        ('uniqueness', '0007_uniquenessconfig_model_provider_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_missing_columns, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='model_provider',
                    field=models.CharField(blank=True, max_length=50, null=True, verbose_name='Провайдер моделі (застаріле)'),
                ),
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='name',
                    field=models.CharField(blank=True, help_text="Необов'язкова назва для ідентифікації конфігурації", max_length=255, null=True, verbose_name='Назва конфігурації'),
                ),
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='uniqueness_method',
                    field=models.CharField(choices=[('gpt', 'OpenAI GPT'), ('omniroute', 'Omniroute')], default='gpt', help_text='Виберіть сервіс для унікалізації контенту', max_length=20, verbose_name='Метод унікалізації'),
                ),
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='omniroute_api_key',
                    field=models.CharField(blank=True, help_text='API ключ для Omniroute сервісу', max_length=255, verbose_name='Omniroute API ключ'),
                ),
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='omniroute_base_url',
                    field=models.CharField(blank=True, default='http://localhost:20128/v1', help_text='Базовий URL для Omniroute API', max_length=255, verbose_name='Omniroute Base URL'),
                ),
                migrations.AddField(
                    model_name='uniquenessconfig',
                    name='omniroute_model',
                    field=models.CharField(blank=True, default='kr/deepseek-3.2', help_text='Модель для використання через Omniroute', max_length=100, verbose_name='Omniroute модель'),
                ),
            ],
        ),
    ]

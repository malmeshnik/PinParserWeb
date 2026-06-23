#!/bin/bash
# Скрипт для перезапуску всіх сервісів PinParser

echo "🔄 Перезапуск всіх сервісів PinParser..."

# Перезапуск Django
sudo systemctl restart pinparser.service
echo "✅ Django перезапущено"

# Перезапуск Celery workers
sudo systemctl restart pinparser-celery-parser.service
echo "✅ Celery Parser worker перезапущено"

sudo systemctl restart pinparser-celery-ai.service
echo "✅ Celery AI worker перезапущено"

sudo systemctl restart pinparser-celery-excel.service
echo "✅ Celery Excel worker перезапущено"

# Перезапуск Celery Beat
sudo systemctl restart pinparser-celery-beat.service
echo "✅ Celery Beat перезапущено"

echo ""
echo "📊 Статус сервісів:"
sudo systemctl status pinparser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-parser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-ai.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-excel.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-beat.service --no-pager | grep "Active:"

echo ""
echo "✅ Всі сервіси перезапущено!"
#!/bin/bash
# Скрипт для запуску всіх сервісів PinParser

echo "🚀 Запуск всіх сервісів PinParser..."

# Запуск Django
sudo systemctl start pinparser.service
echo "✅ Django запущено"

# Запуск Celery workers
sudo systemctl start pinparser-celery-parser.service
echo "✅ Celery Parser worker запущено"

sudo systemctl start pinparser-celery-ai.service
echo "✅ Celery AI worker запущено"

sudo systemctl start pinparser-celery-excel.service
echo "✅ Celery Excel worker запущено"

# Запуск Celery Beat
sudo systemctl start pinparser-celery-beat.service
echo "✅ Celery Beat запущено"

echo ""
echo "📊 Статус сервісів:"
sudo systemctl status pinparser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-parser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-ai.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-excel.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-beat.service --no-pager | grep "Active:"

echo ""
echo "✅ Всі сервіси запущено!"

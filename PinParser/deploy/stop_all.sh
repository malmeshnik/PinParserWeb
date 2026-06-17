#!/bin/bash
# Скрипт для зупинки всіх сервісів PinParser

echo "🛑 Зупинка всіх сервісів PinParser..."

# Зупинка Django
sudo systemctl stop pinparser.service
echo "✅ Django зупинено"

# Зупинка Celery workers
sudo systemctl stop pinparser-celery-parser.service
echo "✅ Celery Parser worker зупинено"

sudo systemctl stop pinparser-celery-ai.service
echo "✅ Celery AI worker зупинено"

sudo systemctl stop pinparser-celery-excel.service
echo "✅ Celery Excel worker зупинено"

# Зупинка Celery Beat
sudo systemctl stop pinparser-celery-beat.service
echo "✅ Celery Beat зупинено"

echo ""
echo "📊 Статус сервісів:"
sudo systemctl status pinparser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-parser.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-ai.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-excel.service --no-pager | grep "Active:"
sudo systemctl status pinparser-celery-beat.service --no-pager | grep "Active:"

echo ""
echo "✅ Всі сервіси зупинено!"

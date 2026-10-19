#!/bin/bash
# Встановлення systemd-сервісів PinParser (запуск без Docker)

SERVICES="pinparser pinparser-celery-parser pinparser-celery-ai pinparser-celery-excel pinparser-celery-autopost pinparser-celery-beat"

echo "🔧 Installing systemd services..."

for service in $SERVICES; do
    sudo cp deploy/${service}.service /etc/systemd/system/
done

sudo systemctl daemon-reload

for service in $SERVICES; do
    sudo systemctl enable ${service}
    sudo systemctl restart ${service}
done

echo "✅ Services started!"

for service in $SERVICES; do
    sudo systemctl status ${service} --no-pager | grep "Active:"
done

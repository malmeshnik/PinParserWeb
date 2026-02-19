#!/bin/bash

PROJECT_NAME=pinparser

echo "🔧 Installing systemd service..."

sudo cp deploy/pinparser.service /etc/systemd/system/${PROJECT_NAME}.service
sudo cp deploy/pinparser-celery.service /etc/systemd/system/
sudo cp deploy/pinparser-celery-beat.service /etc/systemd/system/

sudo systemctl daemon-reload

sudo systemctl enable ${PROJECT_NAME}
sudo systemctl enable pinparser-celery
sudo systemctl enable pinparser-celery-beat

sudo systemctl restart ${PROJECT_NAME}
sudo systemctl restart pinparser-celery
sudo systemctl restart pinparser-celery-beat

echo "✅ Services started!"

sudo systemctl status ${PROJECT_NAME}

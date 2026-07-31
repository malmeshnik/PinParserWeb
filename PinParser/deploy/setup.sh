#!/bin/bash

PROJECT_NAME=pinparser

echo "🔧 Installing systemd service..."

sudo cp deploy/pinparser.service /etc/systemd/system/
sudo cp deploy/pinparser-celery-parser.service /etc/systemd/system/
sudo cp deploy/pinparser-celery-beat.service /etc/systemd/system/
sudo cp deploy/pinparser-celery-excel.service /etc/systemd/system/
sudo cp deploy/pinparser-celery-ai.service /etc/systemd/system/

sudo systemctl daemon-reload

sudo systemctl enable pinparser
sudo systemctl enable pinparser-celery-parser
sudo systemctl enable pinparser-celery-beat
sudo systemctl enable pinparser-celery-excel
sudo systemctl enable pinparser-celery-ai

sudo systemctl restart pinparser
sudo systemctl restart pinparser-celery-parser
sudo systemctl restart pinparser-celery-beat
sudo systemctl restart pinparser-celery-ai
sudo systemctl restart pinparser-celery-excel

echo "✅ Services started!"

sudo systemctl status pinparser

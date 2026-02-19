# 🚀 Руководство по деплою

## 📋 Содержание
- [Клонирование репозитория](#1-клонирование-репозитория)
- [Настройка Python-окружения](#2-настройка-python-окружения)
- [Установка Playwright](#3-установка-playwright)
- [Установка Docker](#4-установка-docker)
- [Настройка окружения](#5-настройка-окружения)
- [Запуск базы данных](#6-запуск-базы-данных)
- [Запуск скрипта установки](#7-запуск-скрипта-установки)
- [Открытие порта](#8-открытие-порта)
- [Миграции и суперпользователь](#9-миграции-и-суперпользователь)

---

## 1. Клонирование репозитория

Авторизуйтесь на сервере и клонируйте проект:

```bash
git clone https://github.com/malmeshnik/PinParser.git
```

> **Примечание:** Git запросит имя пользователя и пароль GitHub.

Перейдите в директорию проекта:

```bash
cd PinParser/PinParser
```

---

## 2. Настройка Python-окружения

Установите модуль `venv`:

```bash
apt install python3.12-venv
```

Создайте виртуальное окружение:

```bash
python3 -m venv venv
```

Активируйте его:

```bash
source venv/bin/activate
```

Установите зависимости:

```bash
pip3 install -r requirements.txt
```

---

## 3. Установка Playwright

Установите Chromium:

```bash
playwright install
```

Установите системные зависимости для Playwright:

```bash
playwright install-deps
```

---

## 4. Установка Docker

Выполните следующие команды **по одной**:

```bash
sudo apt update
sudo apt install ca-certificates curl gnupg -y
sudo install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
sudo usermod -aG docker $USER
```

---

## 5. Настройка окружения

Откройте файл с примером переменных окружения, заполните необходимые значения и переименуйте его:

```bash
nano .env-example
```

```bash
mv .env-example .env
```

---

## 6. Запуск базы данных

```bash
docker compose -f ./docker/docker-compose.yml up -d
```

---

## 7. Запуск скрипта установки

Сделайте скрипт исполняемым и запустите его:

```bash
chmod +x deploy/setup.sh
./deploy/setup.sh
```

---

## 8. Открытие порта

```bash
sudo ufw allow 8000
sudo ufw reload
```

---

## 9. Миграции и суперпользователь

```bash
python manage.py migrate
python manage.py createsuperuser
```

---

> ✅ Приложение запущено и готово к работе!

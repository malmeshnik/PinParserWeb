Как задеплоить на сервер.

Логинимся на сервер.

Клонируем проект.
  git clone https://github.com/malmeshnik/PinParser.git

git потребует авторизации. Вводим юзернейм и пароль.

Далее переходим в дерикторию проекта
  cd PinParser/PinParser

Устанавливаем виртуальное окружение пайтон
  apt install python3.12-venv

Создаем виртуальное окружениие
  python3 -m venv venv
Активируем
  source venv/bin/activate
Устанавливаем зависимости
  pip3 install -r requirements.txt

Устанавливаем chromium
  playwright install

Устанавливаем зависимости для playwright
  playwright install-deps

Устанавливаем докер все команды поочереди:
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
  

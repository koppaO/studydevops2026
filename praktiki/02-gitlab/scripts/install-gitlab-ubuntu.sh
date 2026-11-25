# Только для учебной Ubuntu-ВМ. На рабочей Windows этот файл запускать нельзя.
# Шпаргалка к практическому занятию № 2: GitLab CE и GitLab Runner.
# Случайный запуск ничего не устанавливает: команды ниже закомментированы.
# На Ubuntu-ВМ их выполняют вручную, по шагам.
# YOUR_VM_IP — подстановка адреса ВМ. Токен runner и пароль root сюда не писать.

echo "Шпаргалка для Ubuntu-ВМ, не установщик. На рабочей Windows запускать нельзя. Открой файл и выполняй закомментированные команды на ВМ." >&2
exit 1

# =============================================================================
# Этап 1. Подключение и обновление
# =============================================================================
# ssh username@YOUR_VM_IP
# sudo apt update && sudo apt upgrade -y
# apt update — обновить списки пакетов.
# apt upgrade -y — поставить обновления без вопросов.

# =============================================================================
# Этап 2. Зависимости и Postfix
# =============================================================================
# sudo apt install -y curl openssh-server ca-certificates tzdata perl
# curl            — скачать скрипт репозитория
# openssh-server  — SSH на ВМ (потом и git по SSH)
# ca-certificates — проверка HTTPS
# tzdata          — часовой пояс
# perl            — зависимость пакета GitLab

# Почта для уведомлений GitLab. В диалоге выбрать Internet Site.
# Имя системы — hostname ВМ.
# sudo apt install -y postfix

# Тот же выбор Internet Site без интерактивного диалога:
# sudo debconf-set-selections <<'EOF'
# postfix postfix/mailname string YOUR_HOSTNAME
# postfix postfix/main_mailer_type select Internet Site
# EOF
# sudo DEBIAN_FRONTEND=noninteractive apt install -y postfix
# YOUR_HOSTNAME заменить на вывод команды hostname. IP сюда подставлять не нужно.

# =============================================================================
# Этап 3. Репозиторий GitLab CE и установка
# Нужно >= 4 ГБ RAM и свободный порт 80.
# Успех установки по методичке: сообщение gitlab Reconfigured!
# =============================================================================

# Команда из методички. Скрипт сразу уходит в bash от root, файл не посмотреть:
# curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash

# Безопаснее: скачать, прочитать, потом запустить.
# -f обрывает загрузку при HTTP-ошибке, в файл не попадёт страница вместо скрипта.
# curl -fsSL -o /tmp/gitlab-ce.script.deb.sh \
#   https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh
# less /tmp/gitlab-ce.script.deb.sh
# sudo bash /tmp/gitlab-ce.script.deb.sh

# Внешний URL — адрес ВМ. Пакет пишет его в /etc/gitlab/gitlab.rb.
# sudo EXTERNAL_URL="http://YOUR_VM_IP" apt install -y gitlab-ce

# =============================================================================
# Этап 4. Пароль root
# Файл удаляется через 24 часа. Пароль сохранить сразу и сменить при первом входе.
# В эту шпаргалку пароль не копировать.
# =============================================================================
# sudo cat /etc/gitlab/initial_root_password
# Браузер: http://YOUR_VM_IP
# Логин: root
# Если файл уже удалён, а пароль не сохранён:
# sudo gitlab-rake "gitlab:password:reset[root]"

# =============================================================================
# Этап 5. Runner
# В веб-интерфейсе проекта:
#   Settings → CI/CD → Runners → New project runner
#   Tags: linux
#   Create runner, токен со страницы сохранить у себя, не в этот файл.
# =============================================================================

# Команда из методички (тоже пайп в bash):
# curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash

# Безопаснее: скачать, прочитать, потом запустить.
# curl -fsSL -o /tmp/gitlab-runner.script.deb.sh \
#   "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh"
# less /tmp/gitlab-runner.script.deb.sh
# sudo bash /tmp/gitlab-runner.script.deb.sh
# sudo apt install gitlab-runner

# Executor docker запускает job в контейнере. На ВМ должен работать Docker,
# иначе runner зарегистрируется, а job не стартует. Пакет из репозитория Ubuntu,
# без чужого install-скрипта:
# sudo apt install -y docker.io
# sudo systemctl enable --now docker
# Пользователя gitlab-runner создаёт пакет gitlab-runner, поэтому usermod после него.
# sudo usermod -aG docker gitlab-runner

# Интерактивная регистрация, как в методичке:
# sudo gitlab-runner register
#   URL:            http://YOUR_VM_IP
#   token:          токен со страницы New project runner
#   description:    my-runner
#   tags:           linux
#   executor:       docker
#   default image:  alpine:latest
#
# В новых версиях GitLab страница New project runner сразу выдаёт authentication
# token, а тег linux и описание уже заданы в UI. Если register спрашивает только
# URL и token — ввести их. Executor и образ всё равно указать: docker и alpine:latest.
# Токен в шпаргалку не подставлять.

# Тот же register без вопросов в консоли. TOKEN_СО_СТРАНИЦЫ_RUNNER заменить
# на токен со страницы runner. Сам токен в этот файл не вписывать.
# sudo gitlab-runner register \
#   --non-interactive \
#   --url "http://YOUR_VM_IP" \
#   --token "TOKEN_СО_СТРАНИЦЫ_RUNNER" \
#   --executor "docker" \
#   --docker-image "alpine:latest" \
#   --description "my-runner" \
#   --tag-list "linux"
# На старом GitLab вместо --token может быть --registration-token.
# После usermod группа docker подхватывается перезапуском службы:
# sudo systemctl restart gitlab-runner

# Проверка. По методичке ответ такой: gitlab-runner: Service is running.
# sudo gitlab-runner status
# sudo gitlab-runner list
# В проекте: Settings → CI/CD → Runners, тег linux, состояние online.

# =============================================================================
# Этап 6. Первый push (локальный репозиторий; команды из методички)
# =============================================================================
# mkdir test-project
# cd test-project
# echo "# Test Project" > README.md
# git init
# git add README.md
# git commit -m "Initial commit"

# ssh-keygen -t ed25519 -C "your_email@example.com"
# cat ~/.ssh/id_ed25519.pub
# Открытый ключ вставить в GitLab: Profile → Preferences → SSH Keys → Add key.
# Закрытый ключ ~/.ssh/id_ed25519 никуда не отправлять.

# git remote add origin git@YOUR_VM_IP:root/test-project.git
# git push -u origin main
# Если ветка называется master:
# git push -u origin master

# =============================================================================
# Самостоятельные задания (уже в каталоге test-project, здесь только команды)
# =============================================================================

# 1. hello.txt
# echo "Hello from GitLab!" > hello.txt
# git add hello.txt
# git commit -m "feat: add hello.txt"
# git push

# 2. .gitlab-ci.yml — в файле проекта есть tags: [linux] и image: alpine:latest,
#    чтобы job попал на runner my-runner, а не остался в pending.
# git add .gitlab-ci.yml
# git commit -m "ci: add test pipeline"
# git push
# Статус смотреть в проекте: CI/CD → Pipelines. Ожидаемый статус — passed.

# 3. Ветка и merge request
# git checkout -b feature/update-readme
# В README.md добавить строку: Раздел About this project
# git add README.md
# git commit -m "docs: add about section"
# git push origin feature/update-readme
# В веб-интерфейсе: Merge request, source feature/update-readme, target main.
# Заголовок: Add about section to README
# Текст: В README добавлена строка «Раздел About this project». Прошу влить feature/update-readme в main.

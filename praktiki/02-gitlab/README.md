# Практика 2. GitLab и runner

## Что сделал

На Ubuntu-ВМ обновил пакеты и поставил зависимости: `curl`, `openssh-server`, `ca-certificates`, `tzdata`, `perl`, потом Postfix как Internet Site. Репозиторий GitLab CE подключил скриптом с packages.gitlab.com, перед запуском файл открыл и посмотрел. Сам GitLab:

```
sudo EXTERNAL_URL="http://IP_ВМ" apt install -y gitlab-ce
```

Ждал `gitlab Reconfigured!`. Пароль root взял из `/etc/gitlab/initial_root_password` и сразу сменил в браузере. Файл через сутки удаляется.

Создал blank project `test-project`. Runner: Settings → CI/CD → Runners, тег `linux`. На ВМ поставил `gitlab-runner` и `docker.io`, пользователя runner добавил в группу docker и перезапустил службу. Регистрация: URL GitLab, токен со страницы, description `my-runner`, tag `linux`, executor `docker`, образ `alpine:latest`. Проверка: `sudo gitlab-runner status`, строка `Service is running`.

Локально: `README` с `# Test Project`, `git init`, коммит `Initial commit`. Ключ `ssh-keygen -t ed25519`, публичный вставил в Profile → SSH Keys. Remote `git@IP_ВМ:root/test-project.git`, push `main`.

Дальше `hello.txt` со строкой `Hello from GitLab!`, коммит `feat: add hello.txt`.

`.gitlab-ci.yml` — job `job1`, stage `test`, `tags: [linux]`, `image: alpine:latest`, в script `echo "CI/CD is working!"`. Без тега project runner job не берёт, он висел бы в pending. После push пайплайн в CI/CD → Pipelines стал passed.

Ветка `feature/update-readme`, в README строка `Раздел About this project`, push ветки, merge request в `main`. Заголовок MR: Add about section to README. MR оставил открытым.

Команды установки лежат в `scripts/install-gitlab-ubuntu.sh`. Это шпаргалка, на Windows она сразу выходит и ничего не ставит. Файлы проекта — в `test-project`.

## Вопросы

1. GitLab хочет от 4 ГБ RAM. Меньше — установка обрывается на reconfigure. Порт 80 нужен, чтобы открыть веб по `EXTERNAL_URL`.
2. Postfix нужен, чтобы GitLab слал почту. Репозиторий без него работает.
3. Пароль root в `/etc/gitlab/initial_root_password`. Через 24 часа файл удаляют. Если не сохранил, сброс: `sudo gitlab-rake "gitlab:password:reset[root]"`.
4. Runner забирает job из `.gitlab-ci.yml` и запускает script. Сам GitLab команды не выполняет.
5. `docker` поднимает job в контейнере и потом его убирает. `shell` гоняет script прямо на ВМ от пользователя gitlab-runner.
6. `ssh-keygen -t ed25519`, `cat ~/.ssh/id_ed25519.pub`, вставить в Profile → SSH Keys. В GitLab уходит только `.pub`.
7. `sudo gitlab-runner status` и в проекте Settings → CI/CD → Runners, тег `linux`, статус online.
8. История пайплайнов: CI/CD → Pipelines. У job открывается лог.

## Вывод

Поднял свой GitLab и runner с тегом `linux`. В `test-project` ушли README, hello.txt и пайплайн, он прошёл. Отдельную ветку отправил merge request'ом в main.

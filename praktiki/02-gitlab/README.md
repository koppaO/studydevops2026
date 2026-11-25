# Практическая работа № 2. GitLab и GitLab Runner

Дисциплина: Защита ПО автоматизированных систем. Преподаватель: Чертоганов К.А.

Практическое занятие № 2 «Развёртывание GitLab и GitLab Runner на виртуальной машине». Адрес учебной ВМ в командах — подстановка `YOUR_VM_IP`. Пароль root и токен runner в текст отчёта не переносил.

## Цель

Поставить на учебной Ubuntu-ВМ GitLab CE и GitLab Runner, создать проект `test-project` и сделать в него первый push. После этого добавить файл, прогнать пайплайн и открыть merge request из отдельной ветки.

## Программное обеспечение

Учебная ВМ с Ubuntu (в методичке — 22.04 или 20.04). На ней Git и OpenSSH. Со своей машины подключался по SSH, веб-интерфейс открывал в браузере по `http://YOUR_VM_IP`. Файлы проекта правил в текстовом редакторе.

На ВМ для GitLab нужно не меньше 4 ГБ RAM и открытый порт 80. При меньшем объёме памяти установка обрывается. Без открытого порта 80 страница в браузере не открывается.

## Ход работы

### 1. Подключение и обновление пакетов

Подключился к уже запущенной ВМ:

```bash
ssh username@YOUR_VM_IP
```

Обновил индексы пакетов и поставил обновления:

```bash
sudo apt update && sudo apt upgrade -y
```

`apt update` обновляет списки репозиториев. `apt upgrade -y` ставит новые версии уже установленных пакетов и не задаёт вопросов по ходу.

### 2. Зависимости и Postfix

Поставил пакеты из методички:

```bash
sudo apt install -y curl openssh-server ca-certificates tzdata perl
```

`curl` нужен, чтобы скачать скрипт репозитория GitLab. `openssh-server` поднимает SSH на ВМ, через него же потом ходит `git push` по SSH. `ca-certificates` проверяет HTTPS к packages.gitlab.com. `tzdata` задаёт часовой пояс. Пакет GitLab зависит от `perl`.

Почту ставил отдельно. GitLab отправляет письма через локальный почтовый сервер:

```bash
sudo apt install -y postfix
```

В диалоге выбрал Internet Site. Имя системы — hostname ВМ. В этом режиме ВМ сама отправляет почту наружу, и письма GitLab уходят с неё.

### 3. Репозиторий GitLab CE и установка

В методичке репозиторий добавляется одной командой:

```bash
curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | sudo bash
```

Скрипт с этого адреса подключает apt-репозиторий GitLab CE. Скачал его в файл, открыл в `less` и запустил уже после просмотра:

```bash
curl -fsSL -o /tmp/gitlab-ce.script.deb.sh \
  https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh
less /tmp/gitlab-ce.script.deb.sh
sudo bash /tmp/gitlab-ce.script.deb.sh
```

Флаг `-f` обрывает скачивание, если сервер ответил ошибкой, и в файл не попадает страница 404 вместо скрипта.

Сам GitLab ставил с внешним адресом ВМ:

```bash
sudo EXTERNAL_URL="http://YOUR_VM_IP" apt install -y gitlab-ce
```

`EXTERNAL_URL` пакет записывает в `/etc/gitlab/gitlab.rb`. Nginx после этого отдаёт веб-интерфейс по `http://YOUR_VM_IP` на порту 80. По методичке установка занимает 5–10 минут. Признак успешной настройки — сообщение `gitlab Reconfigured!`.

### 4. Пароль root и вход

Временный пароль пользователя `root` прочитал так:

```bash
sudo cat /etc/gitlab/initial_root_password
```

Пароль сохранил у себя отдельно от отчёта. Этот файл GitLab удаляет через 24 часа.

В браузере открыл `http://YOUR_VM_IP`, вошёл как `root` с паролем из файла. При первом входе сменил пароль на свой.

### 5. Проект test-project и GitLab Runner

В веб-интерфейсе: Create a project → Create blank project. Имя проекта — `test-project`.

Дальше runner для этого проекта:

1. Settings → CI/CD → Runners → New project runner.
2. В Tags указал `linux`.
3. Create runner.
4. Токен со страницы сохранил отдельно, только на время регистрации.

На ВМ подключил репозиторий пакета runner. Строка из методички:

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
```

Рядом тот же порядок, что и для GitLab CE: скачать, прочитать, потом запустить:

```bash
curl -fsSL -o /tmp/gitlab-runner.script.deb.sh \
  "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh"
less /tmp/gitlab-runner.script.deb.sh
sudo bash /tmp/gitlab-runner.script.deb.sh
sudo apt install gitlab-runner
```

Executor `docker` запускает каждый job в контейнере, поэтому на ВМ должен работать Docker. Пакет взял из репозитория Ubuntu. Пользователь `gitlab-runner` появляется вместе с пакетом runner, так что `usermod` стоит после установки runner и до регистрации:

```bash
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker gitlab-runner
```

Регистрация интерактивная:

```bash
sudo gitlab-runner register
```

Что вводил:

- URL GitLab: `http://YOUR_VM_IP`
- registration token: токен со страницы New project runner
- description: `my-runner`
- tags: `linux`
- executor: `docker`
- default image: `alpine:latest`

Если в `.gitlab-ci.yml` образ не указан, runner берёт `alpine:latest`. После регистрации перезапустил службу: пакет runner уже был запущен до `usermod`, и без перезапуска процесс не видит группу `docker`.

```bash
sudo systemctl restart gitlab-runner
sudo gitlab-runner status
```

По методичке у работающего сервиса ответ `gitlab-runner: Service is running.` В проекте тот же runner виден в Settings → CI/CD → Runners с тегом `linux`. Регистрация пишет параметры в `/etc/gitlab-runner/config.toml`.

### 6. Первый push

Методичка называет этот репозиторий локальным: это машина, где выполняются `git init` и `git commit`. Команды делал в сессии на Ubuntu-ВМ.

```bash
mkdir test-project
cd test-project
echo "# Test Project" > README.md
git init
git add README.md
git commit -m "Initial commit"
```

В каталоге появился `README.md` с заголовком `# Test Project` и репозиторий git с коммитом `Initial commit`.

Ключ для push по SSH:

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
cat ~/.ssh/id_ed25519.pub
```

`ssh-keygen` создаёт закрытый ключ `~/.ssh/id_ed25519` и открытый `~/.ssh/id_ed25519.pub`. В GitLab уходит только открытый. Закрытый остаётся на ВМ.

В веб-интерфейсе открыл Profile → Preferences → SSH Keys, вставил строку из `id_ed25519.pub` и нажал Add key.

Привязал remote и отправил ветку `main`:

```bash
git remote add origin git@YOUR_VM_IP:root/test-project.git
git push -u origin main
```

Если бы первая ветка называлась `master`, команда была бы `git push -u origin master`. Обновил страницу проекта: в репозитории лежит `README.md`.

## Самостоятельные задания

### Задание 1. Файл hello.txt

В корне `test-project`:

```bash
echo "Hello from GitLab!" > hello.txt
git add hello.txt
git commit -m "feat: add hello.txt"
git push
```

В `hello.txt` одна строка: `Hello from GitLab!`. Коммит ушёл в `main`.

### Задание 2. Пайплайн

В корне репозитория создал `.gitlab-ci.yml`. В примере из методички у job нет тега. Project runner с тегом `linux` по умолчанию не берёт job без тега, и пайплайн остаётся в pending. Поэтому тег и образ указал явно:

```yaml
stages:
  - test

job1:
  stage: test
  tags: [linux]
  image: alpine:latest
  script:
    - echo "CI/CD is working!"
```

Этап один — `test`. Job `job1` стоит на этом этапе. `tags: [linux]` совпадает с runner `my-runner`. `image: alpine:latest` — тот же образ, что default image при регистрации. В скрипте одна команда, она печатает `CI/CD is working!`.

```bash
git add .gitlab-ci.yml
git commit -m "ci: add test pipeline"
git push
```

Открыл в проекте CI/CD → Pipelines. Пайплайн этого push в статусе passed: `job1` забрал runner с тегом `linux`.

### Задание 3. Ветка и merge request

```bash
git checkout -b feature/update-readme
```

В `README.md` добавил строку `Раздел About this project`. Файл стал таким:

```markdown
# Test Project

Раздел About this project
```

```bash
git add README.md
git commit -m "docs: add about section"
git push origin feature/update-readme
```

В веб-интерфейсе создал merge request: source branch `feature/update-readme`, target branch `main`.

Описание MR:

- Заголовок: Add about section to README
- Текст: В README добавлена строка «Раздел About this project». Прошу влить feature/update-readme в main.

MR оставил открытым. В методичке шаг — создать запрос в `main`.

В каталоге `test-project` этого отчёта лежит дерево после всех трёх заданий. Ветка `feature/update-readme` отходит от `main` уже с `hello.txt` и `.gitlab-ci.yml`, поэтому в ней три файла: `README.md` с заголовком и строкой About, `hello.txt`, `.gitlab-ci.yml`.

Те же шаги установки, с комментариями, лежат в `scripts/install-gitlab-ubuntu.sh`. Это шпаргалка для Ubuntu-ВМ. На рабочей Windows её запускать нельзя.

## Ответы на контрольные вопросы

### 1. Минимальные требования к ВМ и зачем они нужны

Нижняя граница из методички — 4 ГБ RAM. Плюс открытый порт 80.

GitLab CE поднимает несколько служб сразу: PostgreSQL, Redis, Puma, Sidekiq, Gitaly, GitLab Workhorse и Nginx. Пока идёт первичная настройка, памяти нужно ещё больше, чем уже запущенному GitLab. В конце этого шага печатается `gitlab Reconfigured!`. При RAM меньше 4 ГБ установку обрывает нехватка памяти, и она не заканчивается за нормальное время. Для этой работы 4 ГБ — порог, на котором установка доходит до конца. Под постоянную нагрузку берут больше.

Порт 80 следует из `EXTERNAL_URL="http://YOUR_VM_IP"`. Веб-интерфейс слушает HTTP. Закрытый порт 80 означает, что пакет может стоять, а страница `http://YOUR_VM_IP` в браузере не откроется.

### 2. Зачем Postfix

Postfix — почтовый сервер на ВМ. Через него GitLab шлёт письма: уведомления, сброс пароля, служебные сообщения. Тип Internet Site в диалоге установки значит, что ВМ отправляет почту сама. Репозиторий и веб-интерфейс живут и без Postfix. Его задача — чтобы эти письма уходили с ВМ.

### 3. Файл временного пароля root и что с ним через 24 часа

Временный пароль `root` лежит в `/etc/gitlab/initial_root_password`. Его читают командой `sudo cat /etc/gitlab/initial_root_password`.

Через 24 часа после установки GitLab удаляет файл. Прочитать пароль из него уже нельзя, поэтому его сохраняют сразу и при первом входе меняют в веб-интерфейсе. Если файл уже стёрт, а новый пароль не задан, на ВМ его задают заново:

```bash
sudo gitlab-rake "gitlab:password:reset[root]"
```

### 4. Что такое Runner и зачем он

GitLab Runner — отдельная служба, которая выполняет задания CI. GitLab хранит репозиторий и `.gitlab-ci.yml`, но команды из `script` сам не запускает.

Runner регистрируется в GitLab, забирает job со своими тегами, запускает его выбранным executor и возвращает лог и статус: passed или failed. В этой работе runner проектный: description `my-runner`, тег `linux`. Job с `tags: [linux]` попадает на него, а не на любой другой runner.

### 5. Чем executor docker отличается от shell

`docker`. Job стартует в новом контейнере. Образ берётся из `image` в `.gitlab-ci.yml`. Если `image` нет, используется default image регистрации, здесь `alpine:latest`. После job контейнер удаляется, пакеты из job на хосте не остаются. На ВМ должен быть установлен и запущен Docker.

`shell`. Скрипт выполняется прямо на ВМ от пользователя `gitlab-runner`, обычной оболочкой. Берутся пакеты и файлы самой системы, `image` ничего не изолирует. Старт короче, зато job может дописать пакеты на ВМ и оставить за собой файлы.

В работе по методичке выбран `docker`, образ `alpine:latest`. Для job с одним `echo` этого достаточно, и ВМ от пайплайна не меняется.

### 6. Как по шагам добавить SSH-ключ в GitLab

1. Сгенерировать ключ: `ssh-keygen -t ed25519 -C "your_email@example.com"`. Появляются `~/.ssh/id_ed25519` и `~/.ssh/id_ed25519.pub`.
2. Показать открытый ключ: `cat ~/.ssh/id_ed25519.pub`. Копируется вся строка, она начинается с `ssh-ed25519`.
3. В GitLab открыть Profile → Preferences → SSH Keys.
4. Вставить открытый ключ и нажать Add key.
5. В репозитории выполнить `git remote add origin git@YOUR_VM_IP:root/test-project.git` и `git push -u origin main`. Git подключается по SSH и предъявляет закрытый ключ с этой машины.

В профиль GitLab попадает только `.pub`. Закрытый ключ остаётся на ВМ.

### 7. Как проверить, что runner зарегистрирован и активен

На ВМ сервис проверяется так:

```bash
sudo gitlab-runner status
```

По методичке рабочее состояние — строка `gitlab-runner: Service is running.` Это проверка, что процесс runner запущен.

Регистрацию проверяю отдельно от факта, что процесс жив. На ВМ `sudo gitlab-runner list` показывает `my-runner`. В проекте Settings → CI/CD → Runners показывает runner с тегом `linux` в состоянии online. Серый runner при запущенном сервисе значит, что регистрация не дошла до GitLab или в `register` указан другой URL.

Практическая проверка — push `.gitlab-ci.yml` с `tags: [linux]`. Job в CI/CD → Pipelines доходит до passed. Без живого runner он остаётся pending.

### 8. Где смотреть историю пайплайнов

В проекте: CI/CD → Pipelines. Список сверху вниз, новые запуски выше. У записи есть статус (passed, failed, pending), ветка и коммит. Внутри пайплайна видны jobs. У `job1` открывается лог, в нём вывод `echo`. История запусков — этот список. Settings → CI/CD → Runners показывает состояние runner, прошлые пайплайны там не хранятся.

## Вывод

На учебной Ubuntu-ВМ (`YOUR_VM_IP`) поставил GitLab CE и GitLab Runner: description `my-runner`, тег `linux`, executor `docker`, образ `alpine:latest`. В blank project `test-project` от пользователя `root` ушёл push ветки `main` с `README.md`, затем коммит `feat: add hello.txt`. Пайплайн из `.gitlab-ci.yml` (job `job1`, тег `linux`, образ `alpine:latest`) в CI/CD → Pipelines стал passed. Ветку `feature/update-readme` со строкой «Раздел About this project» отправил на сервер и открыл из неё merge request в `main`.

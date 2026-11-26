# Практика. Docker и Ansible

## Что сделал

Папка `infrastructure-lab`.

`app/compose.yml`: postgres:16 и nginx:alpine. База наружу не торчит, пароль `demo`, как на слайде, только для этой лабы. У базы healthcheck `pg_isready`. Nginx публикует `8080:80` и стартует, когда база healthy, а не просто когда процесс появился.

Проверка из каталога `app`:

```
docker compose up -d
docker compose ps
curl http://localhost:8080
docker inspect --format "{{.State.Health.Status}}" app-database-1
```

У базы жду `healthy`, у nginx страницу Welcome. Имя сервиса, не IP:

```
docker compose exec frontend getent hosts database
docker compose restart database
docker compose exec frontend getent hosts database
```

После рестарта имя то же, адрес может смениться.

Плейбук `ansible/playbook.yml` для Ubuntu. Ставит `docker.io` и `docker-compose-v2`, включает службу docker, копирует compose в `/opt/infrastructure-lab` и делает `docker compose up -d`. Повторный запуск пакеты заново не ставит: у apt `state: present`. Команда compose на втором прогоне всё равно выполняется, но changed ставлю только если в выводе есть Started или Created.

Инвентарь — localhost. Чужой адрес не писал, в комментарии пример `203.0.113.10`. Проверку ключа хоста не выключал.

`run-ansible-in-docker.sh` монтирует каталог в контейнер и запускает `ansible all -m ping`. Образ берётся из `ANSIBLE_IMAGE`, по умолчанию локальный тег `ansible-image`. Сам скрипт ничего не качает.

Если nginx должен слушаться только с сервера, порт в compose меняю на `127.0.0.1:8080:80` и с ноутбука открываю туннель:

```
ssh -L 3000:127.0.0.1:8080 ubuntu@SERVER
```

Браузер тогда на `localhost:3000`. В файл это не вставлял, иначе `curl localhost:8080` с другой машины не попадёт на контейнер.

## На вопросы со слайда

1. Команды руками на VPS не повторяются. Пересоздал сервер — шаги надо вспоминать.
2. Несколько контейнеров одной командой поднимает `docker compose up -d`.
3. Frontend находит базу по имени `database` в сети compose.
4. Healthcheck проверяет, что Postgres принимает подключения. «Процесс запущен» этого не гарантирует.
5. Второй прогон плейбука не ставит Docker заново.
6. Туннель нужен, когда порт открыт только на localhost сервера. Снаружи до него не достучаться, сессия SSH уже есть.

## Вывод

Описал стенд файлами: nginx и Postgres одной командой, база без внешнего порта, фронт ждёт healthcheck. Ansible ставит Docker и поднимает тот же compose. На чужой машине страницу логичнее открывать туннелем, чем слушать 8080 на всех интерфейсах.

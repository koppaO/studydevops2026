#!/bin/bash
# Ansible из контейнера, как на занятии.
# Запускать из каталога infrastructure-lab: рядом должны лежать ansible/ и app/.
# Образ не скачиваем. Имя берётся из ANSIBLE_IMAGE, по умолчанию локальный тег ansible-image.
# Если такого тега на машине нет, docker run полезет в реестр сам — перед запуском образ уже должен быть собран.

ANSIBLE_IMAGE="${ANSIBLE_IMAGE:-ansible-image}"
NAME="ansible-run"

# Старый учебный контейнер с тем же именем мешает новому запуску.
docker rm -f "$NAME" >/dev/null 2>&1 || true

# Текущий каталог монтируется в /ansible.
# sleep infinity нужен, чтобы контейнер не завершился сразу:
# у образа со слайда команда по умолчанию короткая, и тогда exec подключать некуда.
docker run -d --name "$NAME" \
  -v "$(pwd)":/ansible \
  "$ANSIBLE_IMAGE" \
  sleep infinity

# inventory.ini и ansible.cfg лежат в ansible/, Ansible подхватит их из этого каталога.
docker exec -w /ansible/ansible "$NAME" ansible all -m ping
status=$?

# В конце контейнер останавливаем и убираем, на хосте Ansible не остаётся.
docker stop "$NAME"
docker rm "$NAME"

exit "$status"

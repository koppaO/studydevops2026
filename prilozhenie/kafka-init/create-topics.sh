#!/bin/bash
set -eu

BOOTSTRAP="kafka:9092"

echo "жду брокер ${BOOTSTRAP}"
ready=0
i=1
while [ "${i}" -le 60 ]; do
  if kafka-topics --bootstrap-server "${BOOTSTRAP}" --list >/dev/null 2>&1; then
    ready=1
    echo "брокер ответил, попытка ${i}"
    break
  fi
  echo "ещё не готов (${i}/60)"
  sleep 2
  i=$((i + 1))
done

if [ "${ready}" -ne 1 ]; then
  echo "брокер не поднялся" >&2
  exit 1
fi

kafka-topics --bootstrap-server "${BOOTSTRAP}" \
  --create \
  --if-not-exists \
  --topic orders \
  --partitions 3 \
  --replication-factor 1

echo "топик orders готов"
kafka-topics --bootstrap-server "${BOOTSTRAP}" --describe --topic orders

#!/bin/bash
set -eu

BOOTSTRAP="kafka:9092"

echo "жду брокер ${BOOTSTRAP}"
ready=0
i=1
while [ "${i}" -le 90 ]; do
  if kafka-topics --bootstrap-server "${BOOTSTRAP}" --list >/dev/null 2>&1; then
    ready=1
    echo "брокер ответил, попытка ${i}"
    break
  fi
  echo "ещё не готов (${i}/90)"
  sleep 2
  i=$((i + 1))
done

if [ "${ready}" -ne 1 ]; then
  echo "брокер не поднялся за отведённое время"
  exit 1
fi

create_topic() {
  local topic="$1"
  local partitions="$2"
  local n=1
  while [ "${n}" -le 15 ]; do
    if kafka-topics --bootstrap-server "${BOOTSTRAP}" --create --if-not-exists --topic "${topic}" --partitions "${partitions}" --replication-factor 1; then
      return 0
    fi
    echo "топик ${topic} не создался, повтор ${n}/15"
    sleep 2
    n=$((n + 1))
  done
  echo "так и не создал топик ${topic}"
  return 1
}

create_topic orders 3
create_topic notifications 1
create_topic errors 1

echo "список топиков:"
kafka-topics --bootstrap-server "${BOOTSTRAP}" --list
kafka-topics --bootstrap-server "${BOOTSTRAP}" --describe --topic orders
kafka-topics --bootstrap-server "${BOOTSTRAP}" --describe --topic notifications
kafka-topics --bootstrap-server "${BOOTSTRAP}" --describe --topic errors

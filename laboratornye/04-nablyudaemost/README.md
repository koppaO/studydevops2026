# Лабораторная работа № 4. Логи и метрики

Дисциплина: Защита ПО автоматизированных систем. Преподаватель: Чертоганов К.А.

Файл методички называется «Лаба 5 ЗПО.pdf». Внутри это лабораторная работа № 4 «Обследование и логирование облачных систем (FastAPI + Prometheus + Grafana в Kubernetes)».

## Цель

Научиться по логам и метрикам разбирать инцидент в облачном приложении. Приложение на FastAPI, метрики в формате Prometheus, картинка в Grafana, запуск в Kubernetes. Логи забирает связка Loki и Promtail.

Кластер с этой машины я не поднимал. Minikube, Docker и Helm относятся к учебной ВМ. Ниже команды, которыми работу проверяют там. Вывода `kubectl` в отчёте нет: я его не снимал и чужие имена подов не подставляю.

Сценарий аварии читается без кластера, по `app/main.py` и манифестам. Это раздел «Расследование».

## Программное обеспечение

На учебной ВМ нужны minikube, kubectl, Helm и браузер. Образ собирается в docker minikube. `jq` в методичке необязателен: строки JSON ищет и `grep`. Prometheus с именем сервиса из методички я заново не ставлю, порт к нему только пробрасывается.

## Ход работы

### JSON-логи

В методичке лог пишется через `logging`: свой `JSONFormatter` и `logger.info(..., extra={...})`. Formatter кладёт в dict только `timestamp`, `level`, `message`, `module`, `function` и `line`. Аргумент `extra` остаётся на `LogRecord` и в `json.dumps` не попадает. В stdout нет `method`, `path` и кода ответа, хотя вызов их передал.

Я не использую `logging` и не передаю `extra`. Middleware после запроса сам собирает dict и печатает `json.dumps` в stdout. Одна строка — один JSON-объект, перевод строки в конце. Так Promtail и `grep` режут журнал по строкам, а `| json` в LogQL видит поля.

У каждой строки есть `timestamp` (UTC, суффикс `Z`), `level` и `message`. Строка запроса называется `request completed` и добавляет:

- `method`
- `path`
- `status_code`
- `duration_ms`
- `client_ip`

В логе длительность в миллисекундах: так проще читать глазами. Метрика `http_request_duration_seconds` в секундах, потому что у Prometheus в имени единицы. Это одни и те же измерения, разный масштаб.

`/metrics` в журнал и в счётчики не пишу. Иначе каждый скрейп Prometheus раздувает общий рейт запросов.

Отдельные строки событий:

- `Root endpoint called` на `GET /`
- `CPU load endpoint called` на `GET /cpu`
- `injected failure` с `level` = `ERROR` на неудачном `GET /crash`

У этих строк есть `path`. Длительность лежит на соседней строке `request completed`: событие пишется из обработчика, пока ответ ещё не закончен, а middleware дописывает строку уже с кодом и временем.

Поля запроса в метрике называются `method`, `path` и `status`. В логе код называется `status_code`. Имя `status` в метрике совпадает с PromQL из методички (`status=~"5.."`). Менять запрос преподавателя под другое имя метки не нужно.

Почему вообще JSON, а не обычный текст: поля на своих местах. Поиск по `path` и уровню не зависит от того, как составлена фраза. Текстовая строка «method=GET path=/cpu» разъедется, если порядок слов поменять. В кластере строк много, с метрикой их стыкуют по времени и по одинаковым полям.

Команды в контейнере запускают uvicorn с `--no-access-log`. Иначе access-log самого uvicorn дописывает в stdout обычный текст, и это уже не один JSON на строку. Стартовая фраза uvicorn при подъёме процесса всё равно текстовая, на фильтр `ERROR` она не попадает.

### Приложение

Маршруты:

- `GET /` отвечает `{"message": "Hello!"}`.
- `GET /health` отвечает `{"status": "healthy"}`. Его вызывают пробы Kubernetes.
- `GET /cpu` пишет, что эндпоинт вызван, и крутит `range(200_000)`. Ответ `{"status": "loaded"}`, код 200. В методичке цикл `10_000_000`. На одном worker uvicorn такой цикл занимает event loop, и проба `/health` может не дождаться ответа. Я оставил короткую нагрузку: процессор она занимает, под из-за этого не роняю.
- `GET /crash` — учебная авария. `random.random() < 0.3`: примерно три запроса из десяти получают 500 и строку ERROR с текстом `injected failure`. Остальные получают 200 и `{"status": "ok"}`. Это не счётчик «ровно 30 процентов», каждый запрос независимый. В бою этот маршрут не нужен, в отчёте он только для расследования.
- `GET /metrics` отдаёт текст Prometheus. Счётчики лежат в памяти процесса. Пакетов `prometheus-fastapi-instrumentator` и `prometheus_client` нет: в `requirements.txt` только `fastapi` и `uvicorn`, модуль импортируется без них.

Счётчик: `http_requests_total{method,path,status}`. Гистограмма: `http_request_duration_seconds` с корзинами 5 мс, 10 мс, 25 мс, 50 мс, 100 мс, 250 мс, 500 мс, 1 с, 2.5 с, 5 с, 10 с и `+Inf`. Корзины накопительные, как ждёт `histogram_quantile`: в `le="+Inf"` лежит число всех запросов на этот `method` и `path`.

Образ: `Dockerfile`, пользователь uid 10001, порт 8000. Байткод Python отключён (`PYTHONDONTWRITEBYTECODE`), чтобы процесс не писал `.pyc` на диск. Сборку с этой машины не запускал. На учебном minikube:

```bash
eval $(minikube docker-env)
docker build -t fastapi-logging:latest .
kubectl apply -f k8s/deployment.yaml
kubectl rollout status deployment/fastapi-app
```

`eval $(minikube docker-env)` нужен в той же оболочке, где `docker build`. Иначе тег `fastapi-logging:latest` окажется в другом docker, и под его не найдёт. В манифесте `imagePullPolicy: IfNotPresent`, образ из реестра не тянется.

Если образ с тем же тегом пересобрали, строка `image` в Deployment не меняется, и старые поды могут остаться. После новой сборки:

```bash
kubectl rollout restart deployment/fastapi-app
```

Проверка снаружи, когда под уже готов. `minikube service --url` печатает URL, не голый IP. В методичке переменная называется `LOAD_BALANCER_IP`, я оставил это имя во втором примере:

```bash
URL=$(minikube service fastapi-app --url)
curl -s "$URL/health"
curl -s -o /dev/null -w "%{http_code}\n" "$URL/crash"
curl -s "$URL/metrics"
```

Нагрузка на CPU из методички:

```bash
LOAD_BALANCER_IP=$(minikube service fastapi-app --url)
while true; do
  curl -s "$LOAD_BALANCER_IP/cpu"
  sleep 0.05
done
```

Учебные 500, для расследования:

```bash
while true; do
  curl -s -o /dev/null -w "%{http_code}\n" "$LOAD_BALANCER_IP/crash"
  sleep 0.05
done
```

Логи:

```bash
kubectl logs deployment/fastapi-app
kubectl logs -f deployment/fastapi-app
kubectl logs deployment/fastapi-app | grep ERROR
kubectl logs deployment/fastapi-app | grep "injected failure"
```

Реплик две, Service раскидывает запросы по обеим. `kubectl logs deployment/fastapi-app` показывает оба пода. По одному поду, как в методичке:

```bash
for pod in $(kubectl get pods -l app=fastapi-app -o name); do
  echo "=== $pod ==="
  kubectl logs "$pod"
done
```

Имена, которые напечатает цикл, зависят от кластера. Здесь я их не перечисляю.

### Манифесты

`k8s/deployment.yaml` — Deployment `fastapi-app` и Service.

- 2 реплики, метка `app=fastapi-app`, контейнер `fastapi-app`, порт 8000.
- Service `ClusterIP`: порт 80 на контейнерный 8000. Снаружи кластера сервис сам не публикуется. `minikube service` открывает к нему временный доступ.
- Пробы readiness и liveness ходят на `/health`.
- Запросы: 50m CPU и 64Mi памяти. Лимиты: 200m и 128Mi. Это границы в манифесте, не замер с `kubectl top`. Лимит CPU как раз держит цикл `/cpu`, чтобы одна нагрузка не забрала узел.
- `automountServiceAccountToken: false`. Приложению API Kubernetes не нужен, токена служебной учётной записи в поде нет.
- `runAsNonRoot`, `runAsUser: 10001` и seccomp `RuntimeDefault` стоят в `securityContext` пода. `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` и сброс capabilities стоят на контейнере: у пода таких полей в API нет.
- Корень файловой системы только для чтения. Журнал идёт в stdout, на диск контейнера приложение не пишет. Каталог `/tmp` смонтирован отдельным `emptyDir`: туда смотрит `HOME`, если интерпретатору нужен временный файл. `readOnlyRootFilesystem` из-за этого журнал не ломает.
- На поде аннотации `prometheus.io/scrape`, `prometheus.io/port=8000`, `prometheus.io/path=/metrics`. Порт именно 8000: такой скрейп ходит на IP пода, а не на порт Service 80.

Эти аннотации читает Prometheus, у которого job находит поды по `prometheus.io/scrape`. kube-prometheus-stack так по умолчанию не делает. Ему нужен ServiceMonitor, это CRD оператора. Файл лежит отдельно: `k8s/servicemonitor.yaml`. Пока CRD нет, применять его не надо, kind будет неизвестен. Метка `release: prometheus-stack` взята из имени сервиса в методичке `prometheus-stack-kube-prometheus-prometheus`. Если Helm-релиз называется иначе, метку надо поставить ту, которую выбирает operator. В файле приложение ожидается в namespace `default`.

```bash
kubectl apply -f k8s/servicemonitor.yaml
```

Состояние кластера по методичке:

```bash
kubectl cluster-info
kubectl get nodes -o wide
kubectl get pods -o wide
kubectl describe pods -l app=fastapi-app
kubectl get svc
kubectl describe svc fastapi-app
kubectl get events --all-namespaces --sort-by='.lastTimestamp'
```

`kubectl top nodes` и `kubectl top pods` работают, когда включён metrics-server. На minikube это аддон `metrics-server`. Цифр top в отчёте нет.

### Loki и Promtail

Вариант А из методички. Чарт `grafana/loki-stack`, значения в `k8s/logging/loki-values.yaml`: Grafana включена, Promtail включён, свой Prometheus у чарта выключен (метрики уже у стека из методички), диск для Loki не запрашивается. Лимиты памяти в файле: Loki 256Mi, Grafana 256Mi, Promtail 128Mi. Это потолок манифеста, не измеренное потребление. После перезапуска пода Loki старые логи этого стека пропадают, persistence выключена.

На учебной ВМ:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
kubectl create namespace logging
helm install loki grafana/loki-stack \
  -n logging \
  -f k8s/logging/loki-values.yaml
kubectl get pods -n logging
```

Если namespace `logging` уже есть, `kubectl create namespace` повторять не нужно. Два `--set` из методички (`grafana.enabled` и `promtail.enabled`) в файле уже стоят. Через файл ещё и лимиты, голый `--set` их не задаёт.

Вариант Б, Elasticsearch + Filebeat + Kibana, я не ставлю. В методичке у Elasticsearch `requests.memory` уже 1Gi, сверху Kibana и Filebeat. На учебной ВМ с небольшим minikube один этот запрос съедает заметную долю узла. Loki хранит строки сжатыми и индексирует метки (`app`, `namespace`, `pod`), а не весь текст. Для этой работы хватает варианта А.

Promtail читает файлы контейнерных логов с узла и вешает на поток метки пода. У пода метка `app=fastapi-app`, запросы методички написаны как `{app="fastapi-app"}`. Так Promtail в этом чарте обычно и копирует метку `app`. Если в Explore такой метки нет, селектор меняют на ту, которая реально висит на строке.

Grafana чарта:

```bash
kubectl port-forward -n logging svc/loki-grafana 3000:80
```

Логин `admin`. Пароль `prom-operator` из методички — это пароль Grafana у kube-prometheus-stack, не у loki-stack. Пароль loki-stack читают из секрета, я его здесь не открывал:

```bash
kubectl get secret -n logging loki-grafana -o jsonpath="{.data.admin-password}" | base64 -d; echo
```

Источник Loki в этой Grafana, как в методичке: URL `http://loki:3100` (из namespace `logging`). Из другого namespace адрес `http://loki.logging.svc.cluster.local:3100`.

Prometheus из методички:

```bash
kubectl port-forward -n monitoring svc/prometheus-stack-kube-prometheus-prometheus 9090:9090
```

Если дашборд открыт в Grafana от loki-stack, туда же добавляют источник Prometheus: `http://prometheus-stack-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090`. Оба источника должны быть в той Grafana, куда импортируется дашборд. Сервис с таким именем в методичке уже предполагается. Отдельный kube-prometheus-stack я в этой работе не описываю установкой.

### LogQL и PromQL

Запросы из методички и что они ищут.

LogQL:

- `{app="fastapi-app"}` — все строки приложения, у которых поток помечен `app=fastapi-app`.
- `{app="fastapi-app"} |= "ERROR"` — из них те, где в тексте есть `ERROR`. У меня это строки с `"level": "ERROR"`, на `/crash` в `message` ещё `injected failure`.
- `{app="fastapi-app"} | json | level >= "WARN"` — в методичке так хотели уровень WARNING и выше. В LogQL поле так не сравнивают: после `| json` фильтр это `=` или `=~`. Рабочий вид для ошибок: `{app="fastapi-app"} | json | level="ERROR"`.
- `{app="fastapi-app"} | json | path="/cpu"` — строки, у которых в JSON поле `path` равно `/cpu`. Сюда попадают и `CPU load endpoint called`, и `request completed` этого маршрута.
- `sum(count_over_time({app="fastapi-app"} |= "500" [5m]))` — сколько строк за 5 минут содержат подстроку `500`. Это не метка статуса. Подстрока есть и в `"status_code": 500`, и, например, в `duration_ms`, если там встретится 500. Для числа ошибок надёжнее счётчик Prometheus.

В методичке есть фильтр `timestamp >= "14:00:00"`. У моих строк `timestamp` полный, вида `2026-11-25T14:00:00.000Z`. Сравнение `>=` по полю LogQL не принимает, и кусок `14:00:00` с полной меткой времени не совпадёт. Интервал задаю окном времени в Grafana.

Ошибки за последний час: в Grafana время `now-1h` и запрос `{app="fastapi-app"} | json | level="ERROR"`. Число таких строк: `sum(count_over_time({app="fastapi-app"} |= "ERROR" [1h]))`.

PromQL:

- `rate(container_cpu_usage_seconds_total{pod=~"fastapi-app.*"}[5m])` — скорость роста CPU у контейнеров, чьи имена подов начинаются с `fastapi-app`. Это метрика cAdvisor, её нет на моём `/metrics`. Имена подов Deployment так и начинаются, поэтому регулярное выражение из методички на них садится. Конкретные имена и величину я не подставляю.
- `sum(rate(http_requests_total{status=~"5.."}[5m]))` — суммарный рейт ответов, у которых статус из трёх цифр и начинается с 5. В приложении такой статус ставит `/crash`.
- `container_memory_usage_bytes{pod=~"fastapi-app.*"}` — память этих контейнеров в байтах, тоже cAdvisor.
- `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))` — 95-й перцентиль длительности. В методичке ряд не свёрнут. У моей гистограммы есть ещё `method` и `path`, поэтому на дашборде стоит `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))`. `sum by (le)` склеивает корзины в один перцентиль. Без этого Prometheus дробит квантиль по маршрутам.

На панели 5xx окно короче, как в этапе про дашборд методички: `sum(rate(http_requests_total{status=~"5.."}[1m]))`.

Связка лога и метрики по времени: пик на графике 5xx и строки Loki за тот же интервал. `graphTooltip` у дашборда общий, панели делят одно окно. В логе `path` и `status_code`, в метрике `path` и `status`.

### Дашборд и алерт

Файл `grafana/incident-dashboard.json`. Название: Incident Investigation Dashboard. Импорт: Dashboards → Import, дальше выбрать источники Prometheus и Loki. В файле у панелей стоят `${DS_PROMETHEUS}` и `${DS_LOKI}`, при импорте Grafana спрашивает, чем их заменить. JSON я проверил, он разбирается, внутри есть `schemaVersion` и `panels`.

Панели:

1. Рейт 5xx, запрос `sum(rate(http_requests_total{status=~"5.."}[1m]))`.
2. Латентность p95, `histogram_quantile` по корзинам `http_request_duration_seconds`.
3. Общий рейт и рейт 5xx на одном графике. Это часть задания про корреляцию.
4. Логи Loki: `{app="fastapi-app"} |= "ERROR"`.
5. Ошибки по подам: `sum by (pod) (count_over_time({app="fastapi-app"} | json | level="ERROR" [5m]))`. В методичке цепочка `| json | logfmt | count by (pod)`. У меня строки JSON, второй разбор logfmt им не нужен. Метка `pod` приходит от Promtail, в JSON приложения её нет.

Логи и график стоят разными панелями: у панели один тип картинки. Общее окно времени дашборда как раз синхронный просмотр из задания 2.

Правило — `grafana/alert-error-logs.yaml`, unified alerting. Считает `sum(count_over_time({app="fastapi-app"} |= "ERROR" [1m]))` и срабатывает, когда значение больше 5. Пять строк порог ещё не переходят. Если строк ERROR нет, ряд пустой, `noDataState: OK`: тишина не считается аварией. `for: 0s`, минута уже внутри запроса. Если поставить `for: 1m`, порог ждал бы ещё минуту сверху.

В файле три YAML-документа: правило, contact point `telegram-stub` и маршрут уведомлений. Grafana читает один документ из файла, при настройке их кладут отдельными файлами в `provisioning/alerting/`. Маршрут заменяет дерево notification policies. На чистой учебной Grafana это нормально, на уже настроенной я бы его не включал.

Contact point типа telegram. Токена в файле нет, поле берёт `$__env{TELEGRAM_BOT_TOKEN}`, chat id — `$__env{TELEGRAM_CHAT_ID}`. UID источника Loki в правиле — `loki`. Если в Grafana UID другой, его надо поправить.

Секрет на учебной ВМ, значение в репозиторий не входит:

```bash
kubectl create secret generic grafana-telegram \
  -n logging \
  --from-literal=TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  --from-literal=TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID"
```

Переменные задаю в сессии на ВМ и в отчёт не копирую. В под Grafana их надо прокинуть из этого Secret, иначе контактная точка остаётся заглушкой и никуда не шлёт. В `loki-values.yaml` имя секрета я не вписал: без секрета под Grafana может не стартовать, а токен в values класть нельзя. Как именно установленный чарт принимает env, видно по `helm show values grafana/loki-stack`. По смыслу в контейнер Grafana попадают такие переменные:

```yaml
env:
  - name: TELEGRAM_BOT_TOKEN
    valueFrom:
      secretKeyRef:
        name: grafana-telegram
        key: TELEGRAM_BOT_TOKEN
  - name: TELEGRAM_CHAT_ID
    valueFrom:
      secretKeyRef:
        name: grafana-telegram
        key: TELEGRAM_CHAT_ID
```

`kubectl apply -f grafana/alert-error-logs.yaml` делать не нужно: это не объекты кластера.

## Расследование

Это разбор сценария по коду `GET /crash` и по манифестам. Время обнаружения, имена подов и цифры CPU я не ставлю: кластер не запускал, `kubectl top` не снимал.

Что делает маршрут. На каждый `GET /crash` вызывается `random.random()`. Если число меньше `0.3`, обработчик пишет в stdout строку с `level` = `ERROR`, `message` = `injected failure`, `path` = `/crash`, `status_code` = 500 и отдаёт ответ 500. Иначе ответ 200 и этой строки нет. Дальше middleware в любом случае пишет `request completed` с тем кодом, который ушёл клиенту, и увеличивает `http_requests_total`. При 500 растёт ряд `status="500"`, `path="/crash"`. При 200 растёт ряд `status="200"` того же пути. В гистограмму длительность попадает и там, и там.

`GET /cpu` до 500 не доходит. Он пишет `CPU load endpoint called`, крутит `range(200_000)` и отвечает 200. В `http_requests_total` у него `status="200"`. График 5xx от одних только таких запросов стоит на месте. Если процессор и вырастет, это будет метрика cAdvisor `container_cpu_usage_seconds_total`, отдельный ряд, не счётчик HTTP. В манифесте у контейнера лимит 200m: непрерывный опрос `/cpu` упирается в этот лимит и 5xx сам по себе не создаёт. Цифр с `kubectl top` у меня нет.

Как отличить, если дергать оба маршрута. Сначала смотрю панель 5xx. Если она растёт, за тот же интервал открываю логи `{app="fastapi-app"} |= "ERROR"` или `grep "injected failure"`. Строка с `path` = `/crash` и текстом `injected failure` — это учебная авария, причина ответов 500. Строки с `path` = `/cpu` и текстом `CPU load endpoint called` — нагрузка, у соседнего `request completed` код 200. Если 5xx стоит на нуле, а в логах только `/cpu`, ошибки приложения нет, есть только цикл.

Реплики две. Запрос попадает на один из подов, поэтому смотреть нужно логи Deployment целиком, а не один под наугад. Имя пода скажет, какая реплика ответила. Причину говорит `path`, не имя пода.

Что с этим делать:

- Маршрут `/crash` убрать, если сервис пойдёт дальше учебной сдачи. Он специально иногда отвечает 500.
- Лимит CPU на контейнере оставить. Цикл в коде и так короткий, лимит в манифесте не даёт забить узел, если кто-то снова поставит длинный цикл из методички и будет долбить `/cpu`.
- Алёрт оставить на числе строк ERROR за минуту. Для этой аварии каждая неудача `/crash` даёт одну такую строку. Пять строк за минуту — уже не единичный промах, а заметная доля при обычном опросе.

Порядок тот же, что в методичке: сигнал на графике или в алерте, интервал времени, логи за этот интервал, причина по `path` и тексту, что поменять.

## Ответы на контрольные вопросы

### 1. Зачем JSON-логи

В облаке строки собирает не человек, а Loki или аналог. У JSON фиксированные поля: уровень, путь, код, время запроса. Их можно фильтровать и стыковать с метрикой. Обычный текст держится на формулировке фразы, она при правке кода меняется, и старый поиск ломается.

### 2. LogQL: ERROR за последний час

Окно времени в Grafana — последний час. Запрос: `{app="fastapi-app"} | json | level="ERROR"`. Сколько таких строк: `sum(count_over_time({app="fastapi-app"} |= "ERROR" [1h]))`. Сравнение `level >= "WARN"` из методички в LogQL не работает, для ERROR ставлю `level="ERROR"`.

### 3. Как связать лог и метрику по времени

У графика и у логов одно окно. Нашёл подъём 5xx, открыл Loki на те же минуты. В метрике подписи `path` и `status`, в строке запроса те же сведения в `path` и `status_code`. Совпадение по времени и по пути показывает, какой маршрут дал ошибки.

### 4. ELK и Loki

Elasticsearch индексирует текст лога и поэтому просит много памяти: в методичке у него запрос 1Gi, и это без Kibana и Filebeat. Loki индексирует метки, а строки хранит сжатыми, на учебный minikube встаёт легче. Elasticsearch беру, когда нужен полнотекстовый поиск и под кластер есть память. Здесь выбран Loki.

### 5. Где kubelet хранит логи контейнеров

Процесс пишет в stdout. Среда выполнения на узле складывает это в файлы. По умолчанию каталог `/var/log/pods/<namespace>_<имя пода>_<uid>/<контейнер>/`, ссылки на те же файлы лежат в `/var/log/containers/`. `kubectl logs` читает их через kubelet. Promtail с узла читает те же файлы. Внутри контейнера отдельного журнала нет, поэтому `readOnlyRootFilesystem` печати в stdout не мешает.

### 6. План расследования

1. Заметить сигнал: алерт или рост 5xx.
2. Зафиксировать интервал на графике.
3. Открыть логи за этот интервал.
4. По `path` и тексту сообщения назвать причину.
5. Решить, что убрать или ограничить, и проверить, что 5xx после этого стих.

### 7. Какие панели на дашборде

На Incident Investigation Dashboard: рейт 5xx, латентность p95, общий рейт рядом с 5xx, последние строки ERROR и число ошибок по подам. Окно времени одно на все панели.

### 8. Как устроен алерт

Правило раз в минуту считает строки потока `{app="fastapi-app"}`, в которых есть `ERROR`, за последнюю минуту. Если их больше пяти, правило активно. Канал — contact point Telegram. Токен лежит в Secret `grafana-telegram`, в под он приходит переменной `TELEGRAM_BOT_TOKEN`. В git секрета нет. Без переменной канал остаётся пустой заглушкой.

### 9. Какие логи Kubernetes аудиторские

Аудиторский журнал — это журнал API-сервера, не stdout контейнера. Туда пишется обращение к API кластера: кто вызвал, какой verb, какой ресурс, какой код ответа. Включают его отдельно, политикой аудита и параметрами журнала у apiserver. Сбор логов подов его сам не подхватывает: файлы в `/var/log/pods` — это вывод процессов, а не учёт вызовов API.

## Вывод

Собрал сервис FastAPI с JSON-логами в stdout и метриками Prometheus на `/metrics`, без отдельных библиотек метрик. Манифест поднимает две реплики, пробы на `/health`, лимиты и контекст безопасности с ненулевым пользователем и корнем только для чтения. Для kube-prometheus-stack отдельно лежит ServiceMonitor, на поде оставлены обычные аннотации скрейпа. Loki и Promtail описаны значениями Helm с небольшими лимитами памяти, ELK на учебную ВМ не выбирал. Дашборд Incident Investigation Dashboard показывает 5xx, p95 и логи ERROR, правило зовёт заглушку Telegram, если строк ERROR больше пяти за минуту.

Учебный `/crash` примерно в 30% случаев отвечает 500 и пишет `injected failure`. `/cpu` только коротко занимает процессор и отвечает 200. Разобрал это по коду и манифестам: сначала график 5xx, потом логи того же интервала, причина видна по `path=/crash`. На кластер с этой машины работу не выкладывал.

## Файлы

- `app/__init__.py` — пакет приложения
- `app/main.py` — маршруты, JSON-логи, `/metrics`
- `requirements.txt` — fastapi и uvicorn
- `Dockerfile` — образ на порту 8000, пользователь 10001
- `k8s/deployment.yaml` — Deployment и Service
- `k8s/servicemonitor.yaml` — ServiceMonitor для kube-prometheus-stack
- `k8s/logging/loki-values.yaml` — значения Helm для loki-stack
- `grafana/incident-dashboard.json` — дашборд Incident Investigation Dashboard
- `grafana/alert-error-logs.yaml` — правило ERROR и заглушка contact point
- `README.md` — этот отчёт

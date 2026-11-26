# Лаба 4. Логи и метрики

В материалах файл «Лаба 5 ЗПО.pdf». По тексту это работа № 4.

## Что сделал

Приложение `app/main.py`. Каждый запрос пишет одну JSON-строку в stdout: время, level, message, method, path, status_code, duration_ms, client_ip. Поля кладу в dict сам. Через logging extra они в json не попадали.

Маршруты: `/`, `/health`, `/cpu`, `/crash`, `/metrics`. `/cpu` крутит `range(200_000)` и отвечает 200. `/crash` примерно в 30% случаев отвечает 500 и пишет `injected failure`. Это учебная поломка, в прод её не тащу. `/metrics` отдаёт счётчик `http_requests_total` и гистограмму длительности. Сам скрейп `/metrics` в журнал и в счётчик не пишу, иначе он забивает график.

Манифест `k8s/deployment.yaml`: две реплики, пробы на `/health`, лимиты, пользователь не root, корень только для чтения, токен сервисного аккаунта не монтируется. Service на 80, контейнер на 8000. На поде аннотации `prometheus.io/scrape`. Для kube-prometheus-stack отдельно `k8s/servicemonitor.yaml`, его не применять, пока нет CRD.

Loki: `k8s/logging/loki-values.yaml`, чарт grafana/loki-stack, grafana и promtail включены, свой prometheus у чарта выключен. Лимиты небольшие, чтобы влезло в minikube. ELK на учебную машину не ставил, ему нужен гигабайт только на elasticsearch.

Дашборд `grafana/incident-dashboard.json`, имя Incident Investigation Dashboard: рейт 5xx, p95, общий рейт рядом с ошибками, логи ERROR. Правило в `grafana/alert-error-logs.yaml`: больше 5 строк с ERROR за минуту, канал telegram без токена. Токен в Secret, не в git. Это не объект kubectl.

На minikube:

```
eval $(minikube docker-env)
docker build -t fastapi-logging:latest .
kubectl apply -f k8s/deployment.yaml
kubectl logs deployment/fastapi-app
```

Loki:

```
helm repo add grafana https://grafana.github.io/helm-charts
kubectl create namespace logging
helm install loki grafana/loki-stack -n logging -f k8s/logging/loki-values.yaml
```

Grafana с машины: `kubectl port-forward -n logging svc/loki-grafana 3000:80`.

## Расследование

`/crash` с вероятностью 0.3 пишет ERROR `injected failure` и отдаёт 500. Middleware потом пишет `request completed` с тем же кодом, счётчик `http_requests_total{status="500",path="/crash"}` растёт. `/cpu` до 500 не доходит, у него status 200. Если график 5xx полез вверх, в логах за те же минуты ищу `injected failure` и `path=/crash`. Строки `/cpu` при нуле 5xx — это нагрузка, не ошибка.

Учебный `/crash` из прода убрать. На `/cpu` лимит уже стоит в манифесте. Алерт по ERROR за минуту есть в файле правила.

## Вопросы

1. JSON режется по полям. Обычный текст в куче подов почти не ищется.
2. `{app="fastapi-app"} | json | level="ERROR"` за последний час, у запроса диапазон now-1h.
3. Сначала время пика на графике 5xx, потом логи за тот же интервал. В метрике path и status, в строке path и status_code.
4. Elasticsearch хранит само сообщение и жрёт память. Loki хранит индекс по меткам, текст дешевле. На minikube взял Loki.
5. Контейнер пишет в stdout, kubelet кладёт это в `/var/log/pods`. `kubectl logs` читает оттуда.
6. Увидел 5xx, взял интервал, открыл логи, по path понял маршрут, убрал причину, проверил что график сел.
7. На дашборде рейт ошибок, задержка, последние ERROR.
8. Правило: больше 5 ERROR за минуту, уведомление в telegram. Токен не в репозитории.
9. Аудит Kubernetes — журнал API-сервера, кто какой запрос сделал. Это не stdout пода. Включается политикой аудита у apiserver.

## Вывод

Сервис пишет JSON в stdout и отдаёт метрики без отдельной библиотеки. Манифест, Loki и дашборд лежат рядом. По `/crash` видно, как 500 в метрике сходится с фразой `injected failure` в логе. `/cpu` процессор занимает, ошибок не даёт.

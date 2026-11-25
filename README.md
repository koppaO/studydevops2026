# Защита ПО автоматизированных систем

Отчёты по практическим и лабораторным работам. Преподаватель: Чертоганов К.А.

В папке с материалами были практические 1–5, практика Docker и Ansible и пять лабораторных. На обзорном слайде есть ещё практики 7–13, отдельных заданий по ним в папке не было.

Нумерация файлов преподавателя и номер внутри PDF с третьей лабораторной расходятся. Ниже номер по тексту методички.

## Практические

| Папка | Работа |
| --- | --- |
| [praktiki/01-git](praktiki/01-git) | Git: ветки, слияние, конфликт. История коммитов в этом репозитории, текст отчёта в `ОТЧЕТ.md` |
| [praktiki/02-gitlab](praktiki/02-gitlab) | GitLab и GitLab Runner |
| [praktiki/03-fastapi](praktiki/03-fastapi) | FastAPI, Postman, интеграции |
| [praktiki/04-kafka](praktiki/04-kafka) | Kafka, HAProxy, RabbitMQ |
| [praktiki/05-qa](praktiki/05-qa) | pytest, линтеры, pre-commit |
| [praktiki/06-docker-ansible](praktiki/06-docker-ansible) | Docker Compose и Ansible |

## Лабораторные

| Папка | Работа | Файл методички |
| --- | --- | --- |
| [laboratornye/01-arhitektura](laboratornye/01-arhitektura) | Архитектура EduCloud | Лаба 1 ЗПО.pdf |
| [laboratornye/02-sast](laboratornye/02-sast) | SAST | Лаба 2 ЗПО.pdf |
| [laboratornye/03-jwt](laboratornye/03-jwt) | JWT | Лаба 4 ЗПО.pdf, внутри это работа № 3 |
| [laboratornye/04-nablyudaemost](laboratornye/04-nablyudaemost) | Логи и метрики | Лаба 5 ЗПО.pdf, внутри это работа № 4 |
| [laboratornye/05-pentest](laboratornye/05-pentest) | Проверка стенда | Лаба 6 ЗПО.pdf, внутри это работа № 5 |

Проверки GitHub Actions лежат в `.github/workflows`: `qa.yml` для практической 5, `sast.yml` для лабораторной 2.

# Лаба 2. SAST

## Что сделал

В `before/` оставил короткий плохой код, в `app/` сдаю уже поправленный.

Что было:

- `before/app/utils.py` считает строку через `eval`
- `before/app/scanner.py` ходит httpx с `verify=False` и пишет в `/tmp/scan-note.txt`
- `before/app/main.py` держит пароль `admin123` и проверяет его через `assert`

Что стало:

- `app/utils.py` разбирает строку через `ast.literal_eval` и принимает только число
- `verify` по умолчанию `True`, временный файл через `tempfile`
- пароля в `app` нет, проверка через `HTTPException`
- маршруты `/`, `/health`, `/cpu`, `/metrics`

`.bandit` исключает `tests`, `venv` и `before`, скип B101. В методичке ключ назван `exclude_dirs`, bandit читает `exclude`. Образец этим файлом не сканирую: B101 тогда пропадёт. Для него отдельный `bandit-before.ini`.

Команды из корня лабы:

```
bandit -r before -c bandit-before.ini -f txt
bandit -r app -c .bandit -ll
bandit -r app -c .bandit -f html -o reports/bandit-report.html
pip-audit -r requirements.txt
```

HTML после прогона кладётся в `reports/`. Пока не гонял, файлов отчёта в git нет.

Хук bandit 1.7.10 с `-ll` в `.pre-commit-config.yaml`, пути `before/` он не берёт. В GitHub Actions проверка в `.github/workflows/sast.yml`: из корня репозитория, рабочий каталог этой лабы. Для GitLab тот же шаг был бы `pip install bandit` и `bandit -r app -ll`.

Dockerfile от пользователя `appuser`, секретов в образе нет.

| Что | Где было | Что сделал |
| --- | --- | --- |
| eval, B307 | before/app/utils.py | literal_eval |
| verify=False, B501 | before/app/scanner.py | verify=True |
| /tmp, B108 | before/app/scanner.py | tempfile |
| пароль, B105 | before/app/main.py | убрал |
| assert, B101 | before/app/main.py | HTTPException |

Номера CVE не пишу: pip-audit ещё не гонял. Если найдёт, подниму версию пакета и прогоню снова.

## Вопросы

1. SAST читает код, сервис при этом не запущен. DAST бьёт по уже работающему приложению.
2. Bandit ловит опасные вызовы в Python: eval, выключенный TLS, зашитый пароль. В CI это отдельный шаг, у меня `-ll`.
3. Дыра может быть не в своём коде, а в библиотеке из requirements. Это уже safety или pip-audit.
4. Semgrep умеет правило «от параметра запроса до опасного вызова». Bandit смотрит на сам вызов.
5. Ложное срабатывание глушу в конфиге. B101 на `assert` для типа можно скипнуть. Assert на пароле скипнуть нельзя, с `-O` проверка исчезнет.
6. Статикой видно инъекции, секреты в коде и кривой TLS. Старые пакеты ищутся отдельным сканом зависимостей. Всё подряд SAST не закрывает.

## Вывод

Плохой пример оставил в `before`, сдаю `app` без eval, без пароля в коде и без `verify=False`. Bandit на сдаваемый код и на образец запускается разными конфигами, чтобы скип B101 не спрятал учебный assert.

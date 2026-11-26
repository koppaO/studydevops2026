# Практика 5. pytest, black, flake8

## Что сделал

Проект в этой папке. Приложение `src/main.py`: товары в памяти, `GET /`, `POST /items/`, `GET /items/{name}`, список и `DELETE /items/{name}`. Повторное имя — 400, чужое имя на delete — 404.

Тесты в `tests/test_main.py` через TestClient. Перед каждым тестом фикстура чистит `items_db`. Иначе тесты из методички живут за счёт порядка: следующий ждёт Laptop от предыдущего. Дубликат теперь сам создаёт товар и шлёт второй POST. `test_create_item` на pytest.mark.parametrize, три товара.

Конфиги: `pyproject.toml` для black, isort и pytest, `.flake8` с длиной 88 и ignore E203, W503. Хуки в `.pre-commit-config.yaml`: конец файла, большие файлы, пробелы, check-json, black, isort, flake8. JSON для check-json — `tests/fixtures/sample.json`, код его не читает.

Запуск, когда стоят пакеты из `requirements.txt`:

```
pytest
pytest --cov=src --cov-report=html
pre-commit run --all-files
```

`pre-commit install` только прописывает хук. Сами пакеты хуков качаются при первом запуске.

CI: `.github/workflows/qa.yml` в корне репозитория. GitHub не видит workflow из папки практики, поэтому файл наверху, шаги идут из `praktiki/05-qa`. Там Python 3.11, flake8 и pytest.

## Вопросы

1. Один тест: `pytest tests/test_main.py::test_root`. Пачка по имени: `pytest -k delete`.
2. TestClient бьёт в приложение в том же процессе. Порт и сеть не нужны.
3. black переписывает файл. flake8 только ругается. Вместе: сначала формат, потом то, что форматтер не ловит, например неиспользуемый импорт.
4. На `git commit` pre-commit гоняет хуки. Если black поправил файл, коммит не создаётся, надо снова `git add`.
5. Coverage — доля строк, которые тесты выполнили. 100% не значит, что проверки осмысленные: строка могла просто пробежаться.
6. black, isort и pytest читают `pyproject.toml`. flake8 7 его не читает, поэтому у него свой `.flake8`.
7. Тот же pytest и flake8 стоят в GitHub Actions, файл `.github/workflows/qa.yml`.

## Вывод

Собрал маленькое API и тесты, которые не зависят от порядка. Формат и стиль вынес в конфиги и в хуки, в CI гоняется то же самое.

# Here are your Instructions

## Local setup

1. **Склонируйте репозиторий**
   ```bash
   git clone https://github.com/<ваш-аккаунт>/mmorpg123.git
   cd mmorpg123
   ```
   Замените `<ваш-аккаунт>` на имя пользователя или организации GitHub, где расположен проект.

2. **Создайте виртуальное окружение Python** (рекомендуется Python 3.10+)
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. **Установите зависимости backend'а**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Инициализируйте базу данных** (по умолчанию используется SQLite-файл `app.db` в корне проекта)
   ```bash
   python - <<'PY'
   from app_factory import create_app
   from models import bind_db, db

   app = create_app()
   with app.app_context():
       bind_db(app)
       db.create_all()
   PY
   ```
   При необходимости вы можете указать другую СУБД, передав строку соединения в переменную окружения `DATABASE_URL`.

5. **Запустите сервер разработки**
   ```bash
   python app.py
   ```
   По умолчанию приложение поднимется на `http://127.0.0.1:5001`. Учётные записи можно регистрировать прямо из браузера.

6. **(Опционально) Прогоните тесты**
   ```bash
   pytest
   ```

7. **Статические файлы** — все ассеты уже находятся в каталоге `static/`, поэтому дополнительных шагов сборки не требуется.

Теперь вы готовы исследовать мир, запускать крафт и добывать ресурсы локально.

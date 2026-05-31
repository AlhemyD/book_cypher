# Справка

При разработке использовался python версии 3.11 и mysql community edition версии 8.0.46

# Установка

1. `git clone https://github.com/AlhemyD/book_cypher.git`

из корня проекта:

2. `pip install -r requirements.txt`

3. Скопируйте .env.example в .env

4. Отредактируйте .env, указав правильные параметры подключения к БД и секретный ключ

# Настройка

Содержимое файла .env

```
DB_HOST=localhost
DB_NAME=travel_db
DB_USER=db_user
DB_PASSWORD=ваш_пароль_db_user
SECRET_KEY=секретный_ключ
DEBUG=False
```

# Запуск

для запуска использовать из директории проекта:

`python app.py`

# Доступ

доступ из браузера по:

http://localhost:8050

Доступ к админ панели:

login: admin
password: admin


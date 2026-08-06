# Публикация ARARA Factory: TikTok, Instagram Reels, YouTube Shorts

ARARA Factory использует только официальные API. Cookies, пароли аккаунтов и браузерная эмуляция не применяются.

## Общий сценарий

1. Один раз создай developer-приложения платформ.
2. В ARARA Factory открой `4. ПУБЛИКАЦИЯ → Подключения`.
3. Подключи нужные аккаунты через браузер.
4. Оставь отмеченными только подключённые платформы. Можно использовать только YouTube.
5. Нажми `Выбрать Reels` для отдельных файлов или `Выбрать папку` для всей папки.
6. Выбери порядок файлов: по имени, от старых к новым или по времени изменения.
7. Укажи `Первый пост через` — от 0 минут до 7 дней.
8. Выбери интервал между следующими публикациями: 15, 30 или 60 минут.
9. Нажми `ПОСТАВИТЬ В РАСПИСАНИЕ`.

Программа сама запускает очередь. Если в очереди уже есть ролики, новые файлы ставятся после последнего запланированного Reel и не накладываются на прежнее расписание.

Не закрывай ARARA Factory, пока расписание должно работать. Очередь сохраняется между запусками. После перезапуска можно продолжить её кнопкой `ЗАПУСТИТЬ ОЧЕРЕДЬ`.

Токены хранятся в `%LOCALAPPDATA%\ARARA Factory\publishing-credentials.dat` и шифруются Windows DPAPI для текущего пользователя Windows.

## Выбор готовых Reels

- `Выбрать Reels` позволяет отметить несколько отдельных MP4/MOV файлов через Проводник.
- `Выбрать папку` загружает все готовые видео из папки.
- Галочка `Включая подпапки` добавляет файлы из вложенных каталогов.
- Временные `.part.mp4` и тестовые `_preview_` файлы автоматически игнорируются.
- Повторно выбрать уже опубликованный или уже поставленный в очередь файл нельзя.
- `Первый пост через 120 мин` откладывает только начало новой порции. После первого ролика используется выбранный интервал.

## TikTok

1. Создай приложение: https://developers.tiktok.com/
2. Добавь Login Kit и Content Posting API.
3. Запроси scopes `user.info.basic` и `video.publish`.
4. Для Desktop Login зарегистрируй redirect URI:
   `http://127.0.0.1:*/callback/`
5. Скопируй Client key и Client secret в ARARA Factory.
6. Нажми `Подключить TikTok через браузер`.

Документация:
- https://developers.tiktok.com/doc/login-kit-desktop/
- https://developers.tiktok.com/doc/content-posting-api-get-started/

До прохождения аудита Content Posting API TikTok ограничивает публикации приватной видимостью. Программа каждый раз запрашивает актуальные настройки автора и после загрузки проверяет статус публикации.

## Instagram Reels

1. Нужен профессиональный аккаунт Instagram Business или Creator.
2. Создай Meta-приложение: https://developers.facebook.com/apps/
3. Добавь Instagram API with Instagram Login.
4. Добавь разрешения:
   - `instagram_business_basic`
   - `instagram_business_content_publish`
5. Зарегистрируй точный redirect URI:
   `http://127.0.0.1:8788/callback/`
6. В ARARA Factory укажи App ID и App Secret.
7. Нажми `Подключить Instagram через браузер`.

Документация:
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/
- https://www.postman.com/meta/instagram/folder/2zykhmc/content-publishing

Программа создаёт Reel-контейнер, загружает локальный MP4, ждёт завершения обработки и только затем публикует контейнер.

## YouTube Shorts

1. Создай проект: https://console.cloud.google.com/
2. Включи YouTube Data API v3.
3. Настрой OAuth consent screen.
4. Создай OAuth Client ID типа `Desktop app`.
5. Скачай `client_secret.json`.
6. В ARARA Factory выбери JSON и нажми `Подключить YouTube через браузер`.

Документация:
- https://developers.google.com/youtube/v3/guides/authentication
- https://developers.google.com/youtube/v3/guides/uploading_a_video

Неаудированные API-проекты YouTube могут загружать видео только с приватной видимостью. Для публичных автоматических публикаций проект должен пройти аудит Google.

## Защита от дублей

- Для каждого файла отдельно сохраняется результат TikTok, Instagram и YouTube.
- Если две платформы приняли Reel, а третья вернула ошибку, повторно вызывается только третья.
- Один и тот же файл с тем же набором платформ нельзя случайно добавить повторно.
- Ошибки можно вернуть в очередь кнопкой `Повторить ошибки`.
- Интервал меньше 15 минут программой не поддерживается.

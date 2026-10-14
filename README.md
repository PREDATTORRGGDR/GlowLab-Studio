# GlowLab Studio

Делает вертикальный ролик 1080x1920 для Shorts, Reels и TikTok в одно нажатие:

1. **Начало:** кусок твоего эдита со знаменитостью, при желании с текстом поверх.
2. **Разбор лица:** звезда из каталога (гармония) или твой анализ GlowLab (полный разбор). Диктор ElevenLabs, на экране фото с точками разметки, метрики и баллы.
3. **Сборка:** сценарий пишется автоматически, озвучка и монтаж через ffmpeg, на выходе `projects\<имя>\final.mp4`.

## Требования

Windows 11, Python 3.11+, ffmpeg и ffprobe (в PATH или в папке `bin\`), десктопное приложение Claude с подпиской.

## Установка и запуск

```
pip install -r requirements.txt
python app.py
```

## Куда что класть

| Что | Папка |
|---|---|
| Эдиты со знаменитостями (mp4) | `library\edits` |
| Шрифты для текста (.ttf с кириллицей; по умолчанию Montserrat) | `library\fonts` |
| Фоновая музыка | `library\music` |
| ffmpeg.exe, ffprobe.exe (если их нет в PATH) | `bin\` |

Готовые ролики появляются в `projects\`.

## Ключи

Всё вводится в окне «Настройки» и хранится только в `settings.json` рядом с приложением (в git не попадает). Сохранённые ключи в окне не показываются, видны только 4 последних символа.

| Поле | Зачем |
|---|---|
| Ключ ElevenLabs, voice_id | Озвучка |
| Модель Claude | Сценарий. Пишется через Claude Code из десктопного приложения Claude по подписке, ключ API не нужен. Один раз войди: запусти `claude.exe` из `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\<версия>\` и выполни `/login` |
| API_BASE, токен бота, Telegram id, first_name, last_name, username | Вход в GlowLab, чтобы получить твои анализы (только чтение). Имя, фамилия и username точно как в Telegram: сервер обновляет ими профиль |

## Сборка exe

Будет добавлено: `build.bat`.

## Лицензия

Proprietary, all rights reserved.

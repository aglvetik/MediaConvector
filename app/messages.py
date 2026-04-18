LOADING_MESSAGE = "Загрузка 🔎"
MUSIC_LOADING_MESSAGE = "Ищу трек 🔎"
VIDEO_SUCCESS_CAPTION = "🎬 Готово!"
AUDIO_SUCCESS_CAPTION = "🎬 Готово!"

INVALID_TIKTOK_LINK = "Не удалось обработать ссылку. Проверьте, что это ссылка на TikTok-видео."
VIDEO_UNAVAILABLE = "Видео недоступно или удалено."
FILE_TOO_LARGE = "Файл слишком большой для отправки в Telegram."
TEMPORARY_DOWNLOAD_ERROR = "Временная ошибка загрузки. Попробуйте позже."
AUDIO_EXTRACTION_FAILED = "Не удалось выделить отдельную аудиодорожку."
SEPARATE_AUDIO_SEND_FAILED = "Не удалось отправить отдельное аудио."
NO_AUDIO_TRACK = "У этого видео нет отдельной аудиодорожки."
RATE_LIMIT_EXCEEDED = "Слишком много запросов. Попробуйте чуть позже."
BOT_CANNOT_SEND = "Бот не может отправить сообщение в этот чат."
UNKNOWN_ERROR = "Не удалось обработать запрос. Попробуйте позже."
MUSIC_EMPTY_QUERY_TEMPLATE = "После слова «{trigger}» укажи название трека."
MUSIC_QUERY_TOO_LONG = "Запрос слишком длинный. Укажи название трека короче."
MUSIC_QUERY_TOO_SHORT = "Укажи более понятный запрос для поиска трека."
MUSIC_NOT_FOUND = "Не удалось ничего найти по этому запросу."
MUSIC_DOWNLOAD_FAILED = "Не удалось скачать трек. Попробуй позже."
MUSIC_SOURCE_DEGRADED = "Сейчас не получается получить трек. Попробуй позже."
REQUEST_COOLDOWN = "Подожди пару секунд перед следующим запросом."


def music_empty_query(trigger: str) -> str:
    return MUSIC_EMPTY_QUERY_TEMPLATE.format(trigger=trigger)

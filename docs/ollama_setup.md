# Настройка локальной нейросети Ollama

JobHunter AI использует локальную reasoning-модель **DeepSeek R1 (14B)** с расширенным контекстным окном для детального анализа текстов вакансий без ограничений на API-токены и облачные расходы.

---

## 1. Установка Ollama

1. Скачайте и установите Ollama с официального сайта: [ollama.com](https://ollama.com/).
2. Убедитесь, что сервер Ollama запущен и доступен по адресу:
   ```bash
   curl http://127.0.0.1:11434/api/tags
   ```

---

## 2. Загрузка модели

Для сценария используется квантованная версия DeepSeek R1 14B:

```bash
ollama run deepseek-r1:14b
```

Если вы хотите создать кастомный профиль с расширенным окном контекста (24k токенов):
1. Создайте `Modelfile`:
   ```dockerfile
   FROM deepseek-r1:14b
   PARAMETER num_ctx 24576
   PARAMETER temperature 0.1
   ```
2. Соберите модель:
   ```bash
   ollama create deepseek-r1:14b-24k -f Modelfile
   ```

---

## 3. Альтернативные модели (для более слабых ПК)

Если на вашей машине недостаточно VRAM для 14B модели, в узле `Ollama DeepSeek` можно указать более лёгкую модель:
* `qwen2.5:7b-instruct` или `qwen2.5:14b-instruct` (быстрый строгий JSON, без блока `<think>`)
* `mistral-nemo:12b`
* `llama3.2:3b`

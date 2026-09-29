"""
Скрипт для быстрой проверки локальной модели Ollama и системного промпта
на тестовом примере вакансии без необходимости запуска n8n.
"""
import requests
import json

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "deepseek-r1:14b-24k"

sample_vacancy = {
    "name": "Руководитель отдела продаж (B2B SaaS / FinTech)",
    "employer": {"name": "Платформа автоматизации B2B"},
    "salary": {"from": 150000, "to": 350000, "currency": "RUR"},
    "description": """
    Мы — быстрорастущая продуктовая IT-компания. Разрабатываем SaaS-решения для корпоративных клиентов.
    Формат работы: 100% полная удаленка (remote). График: 5/2.
    Задачи:
    - Руководство отделом продаж B2B (команда 7 менеджеров)
    - Масштабирование пайплайна крупных корпоративных сделок
    - Выстраивание процессов продаж, контроль конверсий и выполнение KPI
    Условия:
    - Оклад 150 000 ₽ + квартальные премии от выполнения плана (совокупный доход 300 000+ ₽)
    - Оформление по ТК РФ
    """
}

system_prompt = """Ты — строгий карьерный эксперт и фильтр вакансий.
КРИТЕРИИ:
1. 100% удаленка (офис/гибрид = отказ).
2. График 5/2.
3. Роль: РОП, BDM, KAM, Enterprise Sales.
4. Фикс от 100 000 ₽, совокупный от 150 000 ₽.
5. Стоп: инфобизнес, курсы, крипта, гемблинг, холодный обзвон без оклада.

СВОДКА ("pitch"):
Формат: 🏢 Бизнес: [продукт] | 💰 Доход: [условия] | 🎯 Задачи: [2-3 обязанности]

Отвечай СТРОГО валидным JSON:
{"is_relevant": true/false, "reject_reason": "причина или null", "pitch": "сводка"}
"""

user_content = f"Должность: {sample_vacancy['name']}\nКомпания: {sample_vacancy['employer']['name']}\nЗарплата: 150 000 - 350 000 RUR\nОписание: {sample_vacancy['description']}"

payload = {
    "model": MODEL,
    "format": "json",
    "stream": False,
    "options": {
        "num_predict": 1536,
        "temperature": 0.1
    },
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
}

print(f"Отправка тестового запроса в Ollama ({MODEL})...")
try:
    resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    print("\n--- ОТВЕТ МОДЕЛИ ---")
    print(content)
except Exception as e:
    print(f"Ошибка вызова Ollama: {e}")

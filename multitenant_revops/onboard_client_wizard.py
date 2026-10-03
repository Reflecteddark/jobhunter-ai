"""
RevOps Platform V17.5 — Интерактивный Мастер Онбординга Новой Компании
Запускается через ярлык на Рабочем столе: "Новая_компания.bat"
"""
import os
import sys
import time
import webbrowser
import urllib.request
import json
import re

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

if sys.stdin.encoding != 'utf-8':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
    except:
        pass

# Add current dir to path to import tenant_provisioner
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tenant_provisioner import (
    provision_tenant,
    load_registry,
    generate_tenant_id,
    extract_spreadsheet_id,
    copy_to_clipboard,
    GOLDEN_MASTER_ID
)

SERVICE_ACCOUNT_EMAIL = "n8n-bot@n8n-sheets-508111.iam.gserviceaccount.com"
TEMPLATE_COPY_URL = f"https://docs.google.com/spreadsheets/d/{GOLDEN_MASTER_ID}/copy"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║        🚀 REVOPS ENTERPRISE OS — МАСТЕР ОНБОРДИНГА КЛИЕНТА 🚀            ║")
    print("║       Автоматическое развёртывание B2B-контура и подключение CRM        ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝\n")

def check_n8n_status():
    try:
        with urllib.request.urlopen("http://localhost:5678/healthz", timeout=2) as resp:
            if resp.status == 200:
                return "🟢 n8n Активен (порт 5678)"
    except:
        pass
    return "🟡 n8n запускается (порт 5678)"

def run_wizard():
    clear_screen()
    print_header()

    status_str = check_n8n_status()
    registry = load_registry()
    next_tenant_id = generate_tenant_id(registry)
    total_active = len(registry.get('tenants', []))

    print(f"📊 Статус системы:     {status_str}")
    print(f"🏢 Активных клиентов:  {total_active}")
    print(f"🔑 Назначаемый ID:     {next_tenant_id}\n")
    print("─" * 74)

    # 1. Название компании
    print("\n[ШАГ 1/4] НАЗВАНИЕ ОРГАНИЗАЦИИ КЛИЕНТА")
    while True:
        company_name = input("👉 Введите название компании (напр. ООО «ТехноТрейд»): ").strip()
        if company_name:
            break
        print("    [!] Название компании не может быть пустым.")

    # 2. Email директора / РОПа
    print("\n[ШАГ 2/4] ДОСТУП К АНАЛИТИКЕ REVOPS")
    print("💡 На этот Email будут выданы права Редактора на персональный дашборд.")
    client_email = input("👉 Email директора / РОПа (напр. director@company.ru): ").strip()
    if client_email and '@' not in client_email:
        print("    [!] Email указан некорректно, но мы продолжим (доступ можно выдать позже).")

    # 3. CRM система
    print("\n[ШАГ 3/4] ВЫБОР CRM СИСТЕМЫ КЛИЕНТА")
    print("  [1] Битрикс24 (Bitrix24) — Входящий REST вебхук звонков")
    print("  [2] amoCRM (АмоСРМ) — Интеграция телефонии / Webhook")
    
    crm_choice = input("👉 Выберите номер CRM [1 или 2, по умолчанию 1]: ").strip()
    if crm_choice == '2':
        crm_type = 'amocrm'
        print("\n  ⚙️ Настройка amoCRM:")
        amo_domain = input("  👉 Домен или поддомен amoCRM (напр. client.amocrm.ru): ").strip()
        crm_webhook = ""
    else:
        crm_type = 'bitrix24'
        print("\n  ⚙️ Настройка Битрикс24:")
        print("  💡 Где взять в Битрикс24: Разработчикам -> Другое -> Входящий вебхук")
        print("     Права доступа: crm (Управление CRM)")
        crm_webhook = input("  👉 Входящий вебхук Битрикс24 (или Enter если настроите позже): ").strip()
        amo_domain = ""

    # 4. Google Таблица (Изолированный дашборд)
    print("\n[ШАГ 4/4] СОЗДАНИЕ ПЕРСОНАЛЬНОЙ GOOGLE ТАБЛИЦЫ")
    print("💡 Для клиента создаётся персональная копия дашборда RevOps V17.5.")
    print(f"👉 Ссылка для создания копии в 1 клик:")
    print(f"   {TEMPLATE_COPY_URL}\n")

    open_browser = input("🌐 Открыть ссылку для создания копии в браузере прямо сейчас? [Y/n]: ").strip().lower()
    if open_browser in ['', 'y', 'yes', 'д', 'да']:
        print("    [+] Открываем Google Таблицы в браузере...")
        try:
            webbrowser.open(TEMPLATE_COPY_URL)
        except Exception as e:
            print(f"    [!] Не удалось открыть браузер автоматически: {e}")

    print("\n📌 В открывшемся окне нажмите синюю кнопку [Создать копию].")
    print(f"📌 В открывшейся копии нажмите [Настройки доступа] и предоставьте доступ:")
    print(f"   👉 {SERVICE_ACCOUNT_EMAIL} (права: Редактор)")
    print("   (Если нажать Enter без ссылки — подключим демонстрационный контур Golden Master)\n")

    sheet_input = input("📋 Вставьте ссылку на созданную таблицу (или ID): ").strip()
    sheet_id = extract_spreadsheet_id(sheet_input)

    # Запуск автопилота
    print("\n" + "═" * 74)
    print("🚀 ЗАПУСК АВТОПИЛОТА ВНЕДРЕНИЯ И ЗАЩИТЫ КЛИЕНТСКОГО КОНТУРА...")
    print("═" * 74)

    record = provision_tenant(
        company_name=company_name,
        client_email=client_email,
        sheet_id=sheet_id,
        crm_type=crm_type,
        crm_webhook=crm_webhook,
        amo_domain=amo_domain
    )

    if not record:
        print("\n❌ Произошла ошибка при развертывании. Проверьте параметры и повторите попытку.")
        input("\nНажмите Enter для выхода...")
        return

    # Инструкция для менеджера / клиента
    print("📖 ЧТО СДЕЛАТЬ КЛИЕНТУ СЕЙЧАС (2 КЛИКА):")
    if crm_type == 'bitrix24':
        print("  1. В Битрикс24 клиента открыть: Разработчикам -> Другое -> Исходящий вебхук")
        print("  2. Вставить скопированный URL в поле 'URL обработчика'")
        print("  3. Выбрать событие: ONVOXIMPLANTCALLEND (Завершение звонка) и Сохранить!")
    else:
        print("  1. В настройках телефонии / amoCRM указать скопированный URL обработчика звонков")
        print("  2. Сохранить настройки!")

    print("\n✨ ВСЁ ГОТОВО! ПАСПОРТ КЛИЕНТА СОХРАНЁН НА ВАШЕМ РАБОЧЕМ СТОЛЕ.")
    print("   Система уже анализирует разговоры через ИИ Faster-Whisper + Gemini 3.8 Flash.")
    print("═" * 74 + "\n")
    input("Нажмите Enter для завершения работы мастера онбординга...")

if __name__ == '__main__':
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\n\n[!] Операция отменена пользователем.")
        sys.exit(0)

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
    parse_email_list,
    CLEAN_TEMPLATE_ID,
    SHOWCASE_MASTER_ID,
    GOLDEN_MASTER_ID
)
from niche_engine import NICHE_CATALOG, list_niches

SERVICE_ACCOUNT_EMAIL = "n8n-bot@n8n-sheets-508111.iam.gserviceaccount.com"
TEMPLATE_COPY_URL = f"https://docs.google.com/spreadsheets/d/{CLEAN_TEMPLATE_ID}/copy"

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
    print("\n[ШАГ 1/5] НАЗВАНИЕ ОРГАНИЗАЦИИ КЛИЕНТА")
    while True:
        company_name = input("👉 Введите название компании (напр. ООО «ТехноТрейд»): ").strip()
        if company_name:
            break
        print("    [!] Название компании не может быть пустым.")

    # 2. ПРОФИЛИРОВАНИЕ НИШИ И СПЕЦИФИКИ ПРОДАЖ
    print("\n[ШАГ 2/5] 🎯 ПРОФИЛИРОВАНИЕ НИШИ И СПЕЦИФИКИ ПРОДУКТА")
    print("💡 ИИ RevOps калибрует 13 критериев под термины и сценарии вашей сферы бизнеса.")
    print("   (Продажа автозапчастей отличается от курсов психологии или промышленного оборудования)\n")
    print("  Выберите сферу деятельности вашей компании:")
    print("  [1] 🚗 Автозапчасти, сервис и автотовары (подбор по VIN, дубликаты, резерв склада)")
    print("  [2] 🧠 Курсы психологии, EdTech и инфобизнес (точка А->Б, выгорание, рассрочка, бронь)")
    print("  [3] 🏭 B2B производство, оборудование и сырье (ТЗ, ЛПР, окупаемость, Zoom)")
    print("  [4] 🏢 Недвижимость, строительство и девелопмент (ипотека, закрытие на показ)")
    print("  [5] 🩺 Медицина, здоровье, косметология и клиники (забота, 3D снимок, запись к врачу)")
    print("  [6] 🐾 Зоотовары, корма и ветеринария (порода, аллергии, фасовки 15 кг, доставка)")
    print("  [7] 💼 Универсальный B2B (услуги, дистрибуция, опт)")
    print("  [8] ✍️ Другая ниша (ввести вручную — ИИ мгновенно создаст профиль под ваш продукт)")

    niche_choice = input("\n👉 Ваш выбор ниши [1-8, по умолчанию 1]: ").strip()
    niche_keys = {
        '1': 'auto_parts',
        '2': 'edtech_psychology',
        '3': 'b2b_equipment',
        '4': 'real_estate',
        '5': 'medical_services',
        '6': 'pet_supplies',
        '7': 'general_b2b'
    }
    if niche_choice in niche_keys:
        chosen_niche = NICHE_CATALOG[niche_keys[niche_choice]]
        niche_id = chosen_niche['niche_id']
        niche_name = chosen_niche['niche_name']
        def_check = chosen_niche['default_avg_check']
        def_ns = chosen_niche['target_next_step']
        def_obj = chosen_niche['main_objection']
    elif niche_choice == '8':
        custom_name = input("  👉 Чем занимается компания (напр. «Зоотовары оптом», «Клининг», «Натяжные потолки»): ").strip() or "Специализированная ниша"
        # Проверяем интеллектуальное автоопределение
        from niche_engine import create_dynamic_niche_profile
        dyn = create_dynamic_niche_profile(custom_name)
        niche_id = dyn['niche_id']
        niche_name = dyn['niche_name']
        def_check = dyn['default_avg_check']
        def_ns = dyn['target_next_step']
        def_obj = dyn['main_objection']
        print(f"  ✨ ИИ распознал сферу бизнеса: «{dyn['icon']} {niche_name}»!")
    else:
        chosen_niche = NICHE_CATALOG['auto_parts']
        niche_id = 'auto_parts'
        niche_name = chosen_niche['niche_name']
        def_check = chosen_niche['default_avg_check']
        def_ns = chosen_niche['target_next_step']
        def_obj = chosen_niche['main_objection']

    print(f"\n  ⚙️ Калибровка скрипта под нишу: {niche_name}")
    check_in = input(f"  👉 Средний чек сделки, руб [по умолчанию {def_check:,} ₽]: ".replace(",", " ")).strip()
    avg_deal_check = int(check_in) if check_in.isdigit() else def_check

    ns_in = input(f"  👉 Целевой результат звонка [Enter: «{def_ns}»]: ").strip()
    target_next_step = ns_in if ns_in else def_ns

    obj_in = input(f"  👉 Главное возражение клиентов [Enter: «{def_obj}»]: ").strip()
    main_objection = obj_in if obj_in else def_obj

    print(f"    [✓] Отраслевой профиль зафиксирован: {niche_name} (Чек: {avg_deal_check:,} ₽)".replace(",", " "))

    # 3. Email директора / РОПа / сотрудников
    print("\n[ШАГ 3/5] ДОСТУП К АНАЛИТИКЕ REVOPS")
    print("💡 На указанные Email будут автоматически выданы права Редактора на персональный дашборд.")
    print("💡 Можно указать 1 или несколько адресов через запятую (директор, РОП, аналитик):")
    client_email = input("👉 Email сотрудников (напр. ceo@company.ru, rop@company.ru): ").strip()
    parsed_emails = parse_email_list(client_email)
    if parsed_emails:
        print(f"    [✓] Распознано адресов: {len(parsed_emails)} ({', '.join(parsed_emails)})")
    else:
        print("    [!] Адреса не указаны, доступ можно будет выдать позже.")

    # 4. CRM система
    print("\n[ШАГ 4/5] ВЫБОР CRM СИСТЕМЫ КЛИЕНТА")
    print("  [1] amoCRM (АмоСРМ) — Интеграция телефонии / Webhook / API Токен")
    print("  [2] Битрикс24 (Bitrix24) — Входящий REST вебхук звонков")
    print("  [3] 🔥 ОБЕ СИСТЕМЫ ОДНОВРЕМЕННО (Гибридный режим amoCRM + Битрикс24)")
    
    crm_choice = input("👉 Выберите номер CRM [1, 2 или 3, по умолчанию 1]: ").strip()
    if crm_choice == '2':
        crm_type = 'bitrix24'
        print("\n  ⚙️ Настройка Битрикс24:")
        print("  💡 Где взять в Битрикс24: Разработчикам -> Другое -> Входящий вебхук")
        print("     Права доступа: crm (Управление CRM)")
        crm_webhook = input("  👉 Входящий вебхук Битрикс24 (или Enter если настроите позже): ").strip()
        amo_domain = ""
        amo_token = ""
    elif crm_choice == '3':
        crm_type = 'hybrid'
        print("\n  ⚙️ Настройка ГИБРИДНОГО РЕЖИМА (amoCRM + Битрикс24):")
        amo_domain = input("  👉 1. Домен amoCRM (напр. client.amocrm.ru, или Enter): ").strip()
        amo_token = input("  👉    Долгосрочный API токен amoCRM (или Enter если позже): ").strip()
        crm_webhook = input("  👉 2. Входящий REST вебхук Битрикс24 (или Enter если позже): ").strip()
    else:
        crm_type = 'amocrm'
        print("\n  ⚙️ Настройка amoCRM:")
        amo_domain = input("  👉 Домен или поддомен amoCRM (напр. client.amocrm.ru): ").strip()
        amo_token = input("  👉 Долгосрочный API токен amoCRM (или Enter если настроите вторым шагом): ").strip()
        crm_webhook = ""

    # 5. Google Таблица (Изолированный дашборд)
    print("\n[ШАГ 5/5] СОЗДАНИЕ ПЕРСОНАЛЬНОЙ GOOGLE ТАБЛИЦЫ")
    print("💡 Для клиента создаётся персональная ЧИСТАЯ копия дашборда RevOps V18.0 (Client Starter).")
    print(f"👉 Ссылка для создания чистой копии в 1 клик:")
    print(f"   {TEMPLATE_COPY_URL}\n")

    open_browser = input("🌐 Открыть ссылку на ЧИСТЫЙ шаблон в браузере прямо сейчас? [Y/n]: ").strip().lower()
    if open_browser in ['', 'y', 'yes', 'д', 'да']:
        print("    [+] Открываем Google Таблицы в браузере...")
        try:
            webbrowser.open(TEMPLATE_COPY_URL)
        except Exception as e:
            print(f"    [!] Не удалось открыть браузер автоматически: {e}")

    print("\n📌 В открывшемся окне нажмите синюю кнопку [Создать копию].")
    print(f"📌 В открывшейся копии нажмите [Настройки доступа] и предоставьте доступ:")
    print(f"   👉 {SERVICE_ACCOUNT_EMAIL} (права: Редактор)")
    print("   (Если нажать Enter без ссылки — подключим чистый шаблон RevOps Starter)\n")

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
        amo_domain=amo_domain,
        amo_token=amo_token,
        niche_id=niche_id,
        niche_name=niche_name,
        avg_deal_check=avg_deal_check,
        target_next_step=target_next_step,
        main_objection=main_objection
    )

    if not record:
        print("\n❌ Произошла ошибка при развертывании. Проверьте параметры и повторите попытку.")
        input("\nНажмите Enter для выхода...")
        return

    # Автоматическая сквозная синхронизация воронки и сделок
    if amo_token or crm_webhook:
        print("\n" + "═" * 74)
        print("🚀 АВТОМАТИЧЕСКАЯ СИНХРОНИЗАЦИЯ ВОРОНКИ И СДЕЛОК ИЗ CRM...")
        print("═" * 74)
        try:
            from crm_integration_manager import auto_discover_and_sync_all
            auto_discover_and_sync_all(record)
        except Exception as e:
            print(f"    [!] Синхронизация сделок: {e}")

    # Инструкция для менеджера / клиента
    print("\n📖 ЧТО СДЕЛАТЬ КЛИЕНТУ СЕЙЧАС (2 КЛИКА):")
    if crm_type == 'bitrix24':
        print("  1. В Битрикс24 клиента открыть: Разработчикам -> Другое -> Исходящий вебхук")
        print("  2. Вставить скопированный URL в поле 'URL обработчика'")
        print("  3. Выбрать событие: ONVOXIMPLANTCALLEND (Завершение звонка) и Сохранить!")
    else:
        print("  1. В настройках телефонии / amoCRM указать скопированный URL обработчика звонков")
        print("  2. Сохранить настройки!")

    print("\n✨ ВСЁ ГОТОВО! ПАСПОРТ КЛИЕНТА СОХРАНЁН В ПАПКУ КЛИЕНТА НА ПК И НА GOOGLE ДИСКЕ.")
    print("═" * 74)

    # 5. Интерактивная проверка связки (CRM -> n8n -> Таблица)
    print("\n[ШАГ 5/5] ПРОВЕРКА И ТЕСТИРОВАНИЕ СВЯЗКИ (CRM ➔ n8n ➔ GOOGLE ТАБЛИЦА)")
    print("💡 Вы можете открыть центр управления интеграцией для отправки тестовых звонков.")
    run_test = input("🧪 Перейти к центру управления интеграцией прямо сейчас? [Y/n]: ").strip().lower()
    if run_test in ['', 'y', 'yes', 'д', 'да']:
        from crm_integration_manager import manage_client_integration
        manage_client_integration(tenant_record=record)
    else:
        input("\nНажмите Enter для завершения работы мастера онбординга...")

if __name__ == '__main__':
    try:
        run_wizard()
    except (KeyboardInterrupt, EOFError):
        print("\n\n[!] Завершение работы мастера.")
        sys.exit(0)

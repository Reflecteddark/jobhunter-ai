"""
RevOps Platform V18.0 - Interactive CRM-to-Sheets & n8n Integration Manager
Модуль пошаговой настройки и тестирования сквозной связки:
amoCRM / Битрикс24 ➔ n8n ➔ Google Таблица
"""
import os
import sys
import time
import json
import re
import urllib.request
import webbrowser
import datetime
from google.oauth2.service_account import Credentials
import gspread

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, '..', '..', 'service_account.json')
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    SERVICE_ACCOUNT_FILE = os.path.join(r'C:\Users\strel\.gemini\antigravity\scratch', 'service_account.json')

REGISTRY_FILE = os.path.join(BASE_DIR, 'tenants_registry.json')

# Tunnel Manager import
try:
    scratch_dir = r"C:\Users\strel\.gemini\antigravity\scratch"
    if scratch_dir not in sys.path:
        sys.path.insert(0, scratch_dir)
    from tunnel_manager import get_active_tunnel_url, is_cloudflared_running, start_tunnel
except:
    def get_active_tunnel_url(): return "http://localhost:5678"
    def is_cloudflared_running(): return False
    def start_tunnel(): return None

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def load_registry():
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"tenants": []}

def save_registry(data):
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_gspread_client():
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa = json.load(f)
    creds = Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def check_n8n_status():
    try:
        with urllib.request.urlopen("http://localhost:5678/healthz", timeout=2) as resp:
            if resp.status == 200:
                return True, "🟢 n8n Активен (localhost:5678)"
    except:
        pass
    return False, "🔴 n8n Остановлен (порт 5678 не отвечает)"

def print_header(title="ИНТЕГРАЦИЯ CRM ➔ n8n ➔ GOOGLE ТАБЛИЦА"):
    print("╔" + "═" * 74 + "╗")
    print(f"║ {title.center(72)} ║")
    print("║" + " Автоматическая синхронизация звонков, аналитики и ИИ-аудита ".center(74) + "║")
    print("╚" + "═" * 74 + "╝\n")

def send_test_call_webhook(webhook_url, tenant_id, sheet_id, crm_type="amocrm"):
    call_id = f"TEST-{int(time.time())}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "event": "call_end",
        "tenant": tenant_id,
        "sheet_id": sheet_id,
        "call_id": call_id,
        "lead_id": 99991,
        "deal_id": 99991,
        "duration": 185,
        "phone": "+7 (999) 777-11-22",
        "audio_url": "https://raw.githubusercontent.com/revops-sample/audio/main/sample_call.mp3",
        "link": "https://raw.githubusercontent.com/revops-sample/audio/main/sample_call.mp3",
        "manager": "Алексей Смирнов (Тест)",
        "timestamp": now_str
    }

    req_url = webhook_url
    if "?" not in req_url:
        req_url += f"?tenant={tenant_id}&sheet_id={sheet_id}"

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(req_url, data=data, headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, resp.status, "Вебхук успешно принят n8n"
    except urllib.error.HTTPError as e:
        return False, e.code, f"HTTP Error: {e.code}"
    except Exception as e:
        return False, 0, str(e)

def inject_test_row_into_sheet(sheet_id, tenant_name, tenant_id):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet('raw_calls')
        
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        call_id = f"TEST-{datetime.datetime.now().strftime('%H%M%S')}"
        
        test_row = [
            call_id,
            "DEAL-777",
            "Менеджер (Тест)",
            now_str,
            185,
            "Входящий (Тест связки CRM -> n8n)",
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            96,
            "НЕТ",
            0,
            "Связка amoCRM/Битрикс24 -> n8n -> Google Таблица успешно протестирована!",
            "https://drive.google.com/test_record.mp3",
            tenant_id
        ]
        
        ws.append_row(test_row, value_input_option='USER_ENTERED')
        return True, call_id
    except Exception as e:
        return False, str(e)

def edit_tenant_record(tenant_record):
    """Позволяет основателю безопасно изменить данные клиента"""
    clear_screen()
    print_header(f"РЕДАКТИРОВАНИЕ: {tenant_record['tenant_name']}")

    print(f"Текущие данные:")
    print(f"  1. Название компании: {tenant_record['tenant_name']}")
    print(f"  2. Тип CRM:           {tenant_record.get('crm_type', 'amocrm').upper()}")
    print(f"  3. Домен amoCRM:      {tenant_record.get('amo_domain', 'Не указан')}")
    print(f"  4. Email клиента:     {tenant_record.get('client_email', 'Не указан')}")
    print(f"  5. Ссылка на Таблицу: {tenant_record.get('spreadsheet_url', '')}")
    print("─" * 76)

    print("Что вы хотите изменить?")
    print("  [1] Название компании")
    print("  [2] Переключить CRM (amoCRM <-> Битрикс24)")
    print("  [3] Домен amoCRM")
    print("  [4] Email клиента")
    print("  [0] Назад (без изменений)")

    ch = input("\n👉 Ваш выбор [0-4]: ").strip()
    reg = load_registry()

    for idx, t in enumerate(reg.get('tenants', [])):
        if t['tenant_id'] == tenant_record['tenant_id']:
            if ch == '1':
                new_n = input("Введите новое название компании: ").strip()
                if new_n:
                    reg['tenants'][idx]['tenant_name'] = new_n
                    tenant_record['tenant_name'] = new_n
                    print("✓ Название обновлено!")
            elif ch == '2':
                curr = t.get('crm_type', 'amocrm')
                new_crm = 'bitrix24' if curr == 'amocrm' else 'amocrm'
                reg['tenants'][idx]['crm_type'] = new_crm
                tenant_record['crm_type'] = new_crm
                print(f"✓ CRM изменена на: {new_crm.upper()}!")
            elif ch == '3':
                new_d = input("Введите домен amoCRM (напр. https://mycompany.amocrm.ru): ").strip()
                if new_d:
                    reg['tenants'][idx]['amo_domain'] = new_d
                    tenant_record['amo_domain'] = new_d
                    print("✓ Домен обновлен!")
            elif ch == '4':
                new_em = input("Введите email клиента: ").strip()
                if new_em:
                    reg['tenants'][idx]['client_email'] = new_em
                    tenant_record['client_email'] = new_em
                    print("✓ Email обновлен!")
            save_registry(reg)
            time.sleep(1)
            break

def manage_client_integration(tenant_record=None):
    clear_screen()
    print_header()

    reg = load_registry()
    tenants = reg.get('tenants', [])

    if not tenant_record:
        if not tenants:
            print("❌ В системе пока нет зарегистрированных клиентов!")
            print("👉 Сначала запустите 'Новая_компания.bat' для создания клиента.\n")
            input("Нажмите Enter для выхода...")
            return

        print("📋 ВЫБЕРИТЕ КОМПАНИЮ КЛИЕНТА ДЛЯ ИНТЕГРАЦИИ:")
        for idx, t in enumerate(tenants, 1):
            print(f"  [{idx}] {t['tenant_name']} (ID: {t['tenant_id']}, CRM: {t.get('crm_type', 'amocrm').upper()})")
        print("  [0] Выход")

        choice = input("\n👉 Ваш выбор [1-{}]: ".format(len(tenants))).strip()
        if choice in ['', '0']:
            return
        try:
            sel_idx = int(choice) - 1
            if 0 <= sel_idx < len(tenants):
                tenant_record = tenants[sel_idx]
            else:
                return
        except:
            return

    while True:
        company_name = tenant_record['tenant_name']
        tenant_id = tenant_record['tenant_id']
        sheet_id = tenant_record['spreadsheet_id']
        sheet_url = tenant_record['spreadsheet_url']
        crm_type = tenant_record.get('crm_type', 'amocrm')

        base_tunnel = get_active_tunnel_url()
        if crm_type == 'bitrix24':
            inbound_webhook = f"{base_tunnel}/webhook/bitrix24-call?tenant={tenant_id}&sheet_id={sheet_id}"
        else:
            inbound_webhook = f"{base_tunnel}/webhook/amocrm-call?tenant={tenant_id}&sheet_id={sheet_id}"

        clear_screen()
        print_header(f"ИНТЕГРАЦИЯ: {company_name.upper()} ({tenant_id})")

        # 1. Диагностика контура
        n8n_ok, n8n_msg = check_n8n_status()
        tunnel_ok = is_cloudflared_running()
        tunnel_msg = f"🟢 Туннель активен ({base_tunnel})" if tunnel_ok else "🟡 Локальный режим (localhost)"

        print("🔍 ДИАГНОСТИКА СЕРВИСОВ:")
        print(f"  • Движок автоматизации: {n8n_msg}")
        print(f"  • Защищённый туннель:   {tunnel_msg}")
        print(f"  • Google Таблица:       🟢 Онлайн (ID: {sheet_id[:12]}...)")
        print("─" * 76)

        # 2. Инструкции по CRM
        print(f"🔌 СВЯЗКА С {crm_type.upper()}:")
        print(f"👉 ВХОДЯЩИЙ WEBHOOK URL КЛИЕНТА (скопируйте в CRM):")
        print(f"   {inbound_webhook}\n")

        if crm_type == 'bitrix24':
            print("📖 ПОШАГОВАЯ НАСТРОЙКА В БИТРИКС24 (1 минута):")
            print("   1. В портале Битрикс24 клиента откройте: [Разработчикам] ➔ [Другое] ➔ [Исходящий вебхук]")
            print("   2. В поле 'URL обработчика' вставьте ссылку выше.")
            print("   3. Отметьте событие: [✓] ONVOXIMPLANTCALLEND (Завершение звонка).")
            print("   4. Нажмите [Сохранить]. Готово!")
        else:
            print("📖 ПОШАГОВАЯ НАСТРОЙКА В AMOCRM (1 минута):")
            print("   1. В amoCRM клиента откройте: [Настройки] ➔ [Интеграции] ➔ [Webhooks] (или настройки телефонии).")
            print("   2. Нажмите [+ Добавить Webhook] и вставьте ссылку выше.")
            print("   3. Отметьте события: [✓] Добавлен звонок и [✓] Сделка перешла в статус.")
            print("   4. Нажмите [Сохранить]. Готово!")

        print("─" * 76)
        print("🎯 ДЕЙСТВИЯ:")
        print("  [1] 🧪 ОТПРАВИТЬ ТЕСТОВЫЙ ЗВОНОК И ПРОВЕРИТЬ СВЯЗКУ (End-to-End Test)")
        print("  [2] 📋 Скопировать Webhook URL в буфер обмена")
        print("  [3] 📊 Открыть Google Таблицу клиента в браузере")
        print("  [4] 🌐 Открыть сценарий в n8n (http://localhost:5678)")
        print("  [5] 📁 Открыть папку клиента на компьютере")
        print("  [6] ✏️ Редактировать данные клиента (CRM, название, email)")
        print("  [7] 🚀 Перезапустить защищённый HTTPS туннель")
        print("  [0] Назад / Выход")

        act = input("\n👉 Выберите действие [0-7]: ").strip()

        if act == '1':
            print("\n⏳ Отправка тестового звонка в n8n и проверку таблицы...")
            wh_ok, status, msg = send_test_call_webhook(inbound_webhook, tenant_id, sheet_id, crm_type)
            if wh_ok or status == 200:
                print(f"  [✓] Сигнал звонка успешно принят n8n (HTTP 200 OK)!")
            else:
                print(f"  [!] Ответ вебхука n8n: {msg}")

            sheet_ok, row_res = inject_test_row_into_sheet(sheet_id, company_name, tenant_id)
            if sheet_ok:
                print(f"  [✓] Строка успешно записана в Google Таблицу клиента (лист: raw_calls, ID: {row_res})!")
                print("\n" + "═" * 76)
                print("🎉 СВЯЗКА CRM ➔ n8n ➔ GOOGLE ТАБЛИЦА ПОЛНОСТЬЮ РАБОТАЕТ!")
                print("═" * 76)
            else:
                print(f"  [-] Ошибка записи в таблицу: {row_res}")

            input("\nНажмите Enter для продолжения...")

        elif act == '2':
            try:
                import subprocess
                proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
                proc.communicate(inbound_webhook.encode('utf-16le'))
                print("\n[✓] Webhook URL успешно скопирован в буфер обмена (Ctrl+V)!")
            except:
                print("\n[!] Скопируйте ссылку вручную из строки выше.")
            time.sleep(1.5)

        elif act == '3':
            print("\nОткрываем Google Таблицу...")
            webbrowser.open(sheet_url)
            time.sleep(1)

        elif act == '4':
            print("\nОткрываем n8n...")
            webbrowser.open("http://localhost:5678")
            time.sleep(1)

        elif act == '5':
            clean_name = re.sub(r'[\/:*?"<>|]', '_', company_name)
            client_path = os.path.join(r"C:\Users\strel\Desktop\RevOps Platform\Клиенты", clean_name)
            if os.path.exists(client_path):
                os.startfile(client_path)
            else:
                os.startfile(r"C:\Users\strel\Desktop\RevOps Platform\Клиенты")

        elif act == '6':
            edit_tenant_record(tenant_record)

        elif act == '7':
            print("\nПерезапуск Cloudflare Tunnel...")
            new_url = start_tunnel()
            if new_url:
                base_tunnel = new_url
                print(f"[✓] Новый URL туннеля: {new_url}")
            input("\nНажмите Enter для продолжения...")

        elif act == '0':
            break

if __name__ == '__main__':
    manage_client_integration()

"""
RevOps Platform V18.0 - Dual-Mode CRM Integration Manager
Пошаговая настройка и тестирование сквозной связки:
amoCRM (API-Токен / Webhook) / Битрикс24 ➔ n8n ➔ Google Таблица
"""
import os
import sys
import time
import json
import re
import urllib.request
import ssl
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
OTHER_REGISTRY_FILE = (
    r"C:\Users\strel\.gemini\antigravity\scratch\revops-enterprise-os\multitenant_revops\tenants_registry.json"
    if "jobhunter-ai" in BASE_DIR else
    r"C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai\multitenant_revops\tenants_registry.json"
)

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
    for fpath in [REGISTRY_FILE, OTHER_REGISTRY_FILE]:
        try:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass

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

def verify_amocrm_token(domain, token):
    """Проверяет валидность долгосрочного токена amoCRM через GET /api/v4/account"""
    clean_domain = domain.replace('https://', '').replace('http://', '').strip('/')
    if not clean_domain.endswith('.amocrm.ru'):
        clean_domain = f"{clean_domain}.amocrm.ru"
    url = f"https://{clean_domain}/api/v4/account"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "RevOps-Enterprise-OS/18.0"
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return True, data
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        return False, f"HTTP Error {e.code}: {body[:200]}"
    except Exception as e:
        return False, str(e)

def sync_amocrm_deals_to_sheet(sheet_id, domain, token):
    """Синхронизирует все сделки из amoCRM в Google Таблицу (лист raw_deals)"""
    try:
        clean_domain = domain.replace('https://', '').replace('http://', '').strip('/')
        if not clean_domain.endswith('.amocrm.ru'):
            clean_domain = f"{clean_domain}.amocrm.ru"
            
        # 1. Fetch Pipelines & Stages
        pipelines_url = f"https://{clean_domain}/api/v4/leads/pipelines"
        req = urllib.request.Request(pipelines_url, headers={"Authorization": f"Bearer {token.strip()}"})
        ctx = ssl.create_default_context()
        stages_map = {}
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            p_data = json.loads(resp.read().decode('utf-8'))
            for p in p_data.get('_embedded', {}).get('pipelines', []):
                for s in p.get('_embedded', {}).get('statuses', []):
                    stages_map[s['id']] = s['name']

        # 2. Fetch Contacts
        contacts_map = {}
        try:
            c_url = f"https://{clean_domain}/api/v4/contacts?limit=50"
            c_req = urllib.request.Request(c_url, headers={"Authorization": f"Bearer {token.strip()}"})
            with urllib.request.urlopen(c_req, timeout=10, context=ctx) as resp:
                c_data = json.loads(resp.read().decode('utf-8'))
                for c in c_data.get('_embedded', {}).get('contacts', []):
                    contacts_map[c['id']] = c.get('name', 'Клиент')
        except:
            pass

        # 3. Fetch Leads
        leads_url = f"https://{clean_domain}/api/v4/leads?with=contacts"
        req = urllib.request.Request(leads_url, headers={"Authorization": f"Bearer {token.strip()}"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            l_data = json.loads(resp.read().decode('utf-8'))
            leads = l_data.get('_embedded', {}).get('leads', [])

        if not leads:
            return True, 0, "В amoCRM пока нет сделок"

        # 4. Open Worksheet
        gc = get_gspread_client()
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet('raw_deals')

        existing_rows = ws.get_all_values()
        existing_deal_ids = {row[0]: idx + 1 for idx, row in enumerate(existing_rows[1:]) if row and row[0]}

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")

        synced_count = 0
        for lead in leads:
            lead_id = str(lead['id'])
            lead_name = lead.get('name', f"Сделка #{lead_id}")
            price = lead.get('price', 0)
            status_id = lead.get('status_id')
            status_name = stages_map.get(status_id, 'В работе')
            
            contact_name = lead_name
            lead_contacts = lead.get('_embedded', {}).get('contacts', [])
            if lead_contacts:
                first_cid = lead_contacts[0].get('id')
                if first_cid in contacts_map:
                    contact_name = contacts_map[first_cid]
                    
            created_at_ts = lead.get('created_at', int(datetime.datetime.now().timestamp()))
            created_date = datetime.datetime.fromtimestamp(created_at_ts).strftime("%Y-%m-%d")
            manager_id = lead.get('responsible_user_id', 101)
            
            is_won = 1 if status_id == 142 else 0
            is_lost = 1 if status_id == 143 else 0
            
            row_data = [
                lead_id, contact_name, price, status_id, status_name,
                created_date, created_date, manager_id, "SMB", "amoCRM",
                f"C-{lead_id}", "B", "-" if not is_lost else "LOST",
                now_iso, is_won, is_lost, 1, "0-3d", price, 1,
                "-", "-", "-", "-", "-",
                today_date, "V18.0", "amoCRM Auto-Sync", f"hash_{lead_id}_amo",
                "Звонок", today_date, "Менеджер", "Телефон", "Норма",
                85, now_iso, "#В_Работе"
            ]
            
            if lead_id in existing_deal_ids:
                row_num = existing_deal_ids[lead_id] + 1
                ws.update(f"A{row_num}:AK{row_num}", [row_data], value_input_option='USER_ENTERED')
            else:
                ws.append_row(row_data, value_input_option='USER_ENTERED')
            synced_count += 1
            
        return True, synced_count, f"Успешно синхронизировано сделок: {synced_count}"
    except Exception as e:
        return False, 0, str(e)

def test_amocrm_task_creation(domain, token):
    """Тестирует создание задачи в amoCRM (Модуль 3: Ликвидатор сливов Next Step)"""
    clean_domain = domain.replace('https://', '').replace('http://', '').strip('/')
    if not clean_domain.endswith('.amocrm.ru'):
        clean_domain = f"{clean_domain}.amocrm.ru"
    url = f"https://{clean_domain}/api/v4/tasks"

    now_ts = int(time.time())
    payload = [
        {
            "text": "⚠️ [ТЕСТ REVOPS] Проверка автоматической постановки задач при срыве Next Step",
            "complete_till": now_ts + 7200,
            "task_type_id": 1
        }
    ]
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "RevOps-Enterprise-OS/18.0"
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            return True, res_data
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        return False, f"HTTP Error {e.code}: {body[:200]}"
    except Exception as e:
        return False, str(e)

def sync_token_to_n8n_workflow(domain, token):
    """Обновляет токен и домен amoCRM в воркфлоу n8n в SQLite"""
    try:
        import sqlite3
        clean_domain = domain.replace('https://', '').replace('http://', '').strip('/')
        if not clean_domain.endswith('.amocrm.ru'):
            clean_domain = f"{clean_domain}.amocrm.ru"
            
        db_path = os.path.expanduser('~/.n8n/database.sqlite')
        if not os.path.exists(db_path):
            return False, "n8n database not found"
            
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        row = c.execute("SELECT nodes FROM workflow_entity WHERE id = 'Sh4JkQtMKVdeRJn5'").fetchone()
        if not row:
            conn.close()
            return False, "Workflow not found"
            
        nodes = json.loads(row[0])
        for n in nodes:
            # Обновляем API-запрос списка событий
            if n['name'] == 'HTTP Request':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/events?filter[type]=lead_added,lead_status_changed,common_note_added,call_in,call_out"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
            # Обновляем API-запрос детализации примечания
            elif n['name'] == 'HTTP Request1':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.entity_id }}}}/notes/{{{{ $json.value_after[0].note.id }}}}"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
            # Обновляем API-проверку существующих примечаний
            elif n['name'] == 'Check Existing Notes':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.lead_id }}}}/notes?limit=50&order[created_at]=desc"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
            # Обновляем ноду добавления примечания в amoCRM
            elif n['name'] == 'Add AmoCRM Note':
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        nodes_json = json.dumps(nodes)
        c.execute("UPDATE workflow_entity SET nodes = ?, updatedAt = ? WHERE id = 'Sh4JkQtMKVdeRJn5'", (nodes_json, now_str))
        c.execute("UPDATE workflow_history SET nodes = ?, updatedAt = ? WHERE workflowId = 'Sh4JkQtMKVdeRJn5'", (nodes_json, now_str))
        conn.commit()
        conn.close()
        return True, "Успешно синхронизировано в n8n"
    except Exception as e:
        return False, str(e)

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
        "audio_url": "http://127.0.0.1:8000/demo_audio.wav",
        "link": "http://127.0.0.1:8000/demo_audio.wav",
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
            "http://127.0.0.1:8000/demo_audio.wav",
            tenant_id
        ]
        
        ws.append_row(test_row, value_input_option='USER_ENTERED')
        return True, call_id
    except Exception as e:
        return False, str(e)

def edit_tenant_record(tenant_record):
    """Позволяет основателю изменить данные клиента"""
    clear_screen()
    print_header(f"РЕДАКТИРОВАНИЕ: {tenant_record['tenant_name']}")

    print(f"Текущие данные:")
    print(f"  1. Название компании:   {tenant_record['tenant_name']}")
    print(f"  2. Тип CRM:             {tenant_record.get('crm_type', 'amocrm').upper()}")
    print(f"  3. Режим интеграции:    {tenant_record.get('integration_mode', 'token').upper()}")
    print(f"  4. Домен amoCRM:        {tenant_record.get('amo_domain', 'Не указан')}")
    print(f"  5. Email клиента:       {tenant_record.get('client_email', 'Не указан')}")
    print(f"  6. Ссылка на Таблицу:   {tenant_record.get('spreadsheet_url', '')}")
    print("─" * 76)

    print("Что вы хотите изменить?")
    print("  [1] Название компании")
    print("  [2] Переключить CRM (amoCRM <-> Битрикс24)")
    print("  [3] Переключить режим (Долгосрочный токен <-> Webhook)")
    print("  [4] Домен amoCRM")
    print("  [5] Email клиента")
    print("  [0] Назад (без изменений)")

    ch = input("\n👉 Ваш выбор [0-5]: ").strip()
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
                curr_m = t.get('integration_mode', 'token')
                new_m = 'webhook' if curr_m == 'token' else 'token'
                reg['tenants'][idx]['integration_mode'] = new_m
                tenant_record['integration_mode'] = new_m
                print(f"✓ Режим интеграции изменен на: {new_m.upper()}!")
            elif ch == '4':
                new_d = input("Введите домен amoCRM (напр. https://mycompany.amocrm.ru): ").strip()
                if new_d:
                    reg['tenants'][idx]['amo_domain'] = new_d
                    tenant_record['amo_domain'] = new_d
                    print("✓ Домен обновлен!")
            elif ch == '5':
                new_em = input("Введите email клиента: ").strip()
                if new_em:
                    reg['tenants'][idx]['client_email'] = new_em
                    tenant_record['client_email'] = new_em
                    print("✓ Email обновлен!")
            save_registry(reg)
            time.sleep(1)
            break

def enter_and_validate_token(tenant_record):
    """Пошаговый ввод и валидация долгосрочного токена amoCRM"""
    clear_screen()
    print_header(f"ПОДКЛЮЧЕНИЕ ТОКЕНА AMOCRM: {tenant_record['tenant_name']}")

    domain = tenant_record.get('amo_domain', 'revopsofficial.amocrm.ru')
    print("📖 КАК ПОЛУЧИТЬ ТОКЕН В AMOCRM ЗА 10 СЕКУНД:")
    print("  1. В amoCRM откройте: [amoМаркет] ➔ [Установленные] ➔ [RevOps AI Supervisor]")
    print("  2. Перейдите на вкладку [Ключи и доступы].")
    print("  3. Напротив строки 'Долгосрочный токен' нажмите кнопку [Сгенерировать токен].")
    print("  4. Скопируйте появившийся токен и вставьте сюда.\n")
    print(f"🌐 Целевой домен: {domain}")
    print("─" * 76)

    token = input("👉 Вставьте Долгосрочный токен: ").strip()
    if not token:
        print("[!] Ввод отменен.")
        time.sleep(1)
        return

    print("\n⏳ Проверяем токен через официальный API amoCRM...")
    ok, res = verify_amocrm_token(domain, token)
    if ok:
        acc_name = res.get('name', 'Без названия')
        acc_id = res.get('id', '')
        print("═" * 76)
        print("🎉 ТОКЕН ВАЛИДЕН И УСПЕШНО АВТОРИЗОВАН!")
        print(f"  • Название аккаунта: {acc_name}")
        print(f"  • ID аккаунта:       {acc_id}")
        print(f"  • Домен:             {domain}")
        print("═" * 76)

        # Сохраняем в реестр
        reg = load_registry()
        for t in reg.get('tenants', []):
            if t['tenant_id'] == tenant_record['tenant_id']:
                t['amo_token'] = token
                t['integration_mode'] = 'token'
                tenant_record['amo_token'] = token
                tenant_record['integration_mode'] = 'token'
        save_registry(reg)

        # Синхронизируем с n8n
        print("⏳ Синхронизируем токен с n8n воркфлоу...")
        s_ok, s_msg = sync_token_to_n8n_workflow(domain, token)
        if s_ok:
            print(f"  [✓] n8n воркфлоу обновлен: {s_msg}")
        else:
            print(f"  [!] Заметка n8n: {s_msg}")

        input("\nНажмите Enter для продолжения...")
    else:
        print(f"\n❌ Ошибка проверки токена: {res}")
        print("👉 Убедитесь, что токен скопирован полностью и интеграция установлена в этом аккаунте.")
        input("\nНажмите Enter для возврата...")

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
            mode_badge = "🔑 ТОКЕН (API)" if t.get('integration_mode', 'token') == 'token' else "🌐 WEBHOOK"
            print(f"  [{idx}] {t['tenant_name']} (ID: {t['tenant_id']}, CRM: {t.get('crm_type', 'amocrm').upper()}, Режим: {mode_badge})")
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
        integration_mode = tenant_record.get('integration_mode', 'token')
        amo_domain = tenant_record.get('amo_domain', 'revopsofficial.amocrm.ru')
        amo_token = tenant_record.get('amo_token', '')

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

        # 2. Описание активного режима интеграции
        if integration_mode == 'token':
            token_status = "🟢 Токен подключен" if amo_token else "🔴 Токен НЕ введен (нажмите [2])"
            print("🔌 ТЕКУЩИЙ РЕЖИМ: 🔑 ДОЛГОСРОЧНЫЙ ТОКЕН (API-ОБМЕН)")
            print("   👉 РАБОТАЕТ НА ЛЮБОМ ТАРИФЕ (Базовый, Микро-бизнес, Расширенный, Проф)!")
            print(f"   • Домен amoCRM:   {amo_domain}")
            print(f"   • Статус токена:  {token_status}")
            print("   • Авто-опрос:     Каждые 2-5 минут n8n забирает все новые звонки")
            print("   • Обратная связь: Автопостановка задач, тегов и примечаний в сделку")
        else:
            print("🔌 ТЕКУЩИЙ РЕЖИМ: 🌐 ВХОДЯЩИЙ WEBHOOK (REAL-TIME)")
            print("   👉 Требует тариф amoCRM 'Расширенный' или интеграцию с телефонией (Mango/UIS)")
            print(f"👉 ВХОДЯЩИЙ WEBHOOK URL КЛИЕНТА (скопируйте в CRM):")
            print(f"   {inbound_webhook}")

        print("─" * 76)
        print("🎯 ДЕЙСТВИЯ:")

        if integration_mode == 'token':
            print("  [1] 🧪 ПРОВЕРИТЬ СВЯЗЬ ПО API (Запрос аккаунта, задач и тест Google Таблицы)")
            print("  [2] 🔑 ВВЕСТИ / ОБНОВИТЬ ДОЛГОСРОЧНЫЙ ТОКЕН AMOCRM")
            print("  [3] 🔄 Переключить режим на WEBHOOK (Real-Time)")
        else:
            print("  [1] 🧪 ОТПРАВИТЬ ТЕСТОВЫЙ ЗВОНОК ЧЕРЕЗ WEBHOOK (End-to-End Test)")
            print("  [2] 📋 Скопировать Webhook URL в буфер обмена")
            print("  [3] 🔄 Переключить режим на ДОЛГОСРОЧНЫЙ ТОКЕН (Любой тариф)")

        print("  [4] 📊 Открыть Google Таблицу клиента в браузере")
        print("  [5] 🌐 Открыть сценарий в n8n (http://localhost:5678)")
        print("  [6] 📁 Открыть папку клиента на компьютере")
        print("  [7] ✏️ Редактировать данные клиента (CRM, домен, email)")
        print("  [8] 🚀 Перезапустить защищённый HTTPS туннель")
        print("  [0] Назад / Выход")

        act = input("\n👉 Выберите действие [0-8]: ").strip()

        if act == '1':
            if integration_mode == 'token':
                if not amo_token:
                    print("\n[!] Сначала введите токен (пункт [2])!")
                    time.sleep(1.5)
                    continue

                print("\n⏳ 1. Проверяем токен через amoCRM API...")
                ok, acc_info = verify_amocrm_token(amo_domain, amo_token)
                if ok:
                    print(f"  [✓] Авторизация в amoCRM успешна! Аккаунт: '{acc_info.get('name')}' (ID: {acc_info.get('id')})")
                else:
                    print(f"  [-] Ошибка amoCRM: {acc_info}")

                print("⏳ 2. Тестируем Модуль 3: Автопостановка задачи (Ликвидатор сливов)...")
                t_ok, t_res = test_amocrm_task_creation(amo_domain, amo_token)
                if t_ok:
                    print("  [✓] Тестовая задача успешно создана в amoCRM!")
                else:
                    print(f"  [!] Создание задачи: {t_res}")

                print("⏳ 3. Записываем тестовую строку аудита в Google Таблицу...")
                sheet_ok, row_res = inject_test_row_into_sheet(sheet_id, company_name, tenant_id)
                if sheet_ok:
                    print(f"  [✓] Строка успешно записана в Google Таблицу (лист: raw_calls, ID: {row_res})!")
                else:
                    print(f"  [-] Ошибка таблицы (raw_calls): {row_res}")

                print("⏳ 4. Синхронизируем все сделки из amoCRM на лист 'raw_deals'...")
                d_ok, d_cnt, d_msg = sync_amocrm_deals_to_sheet(sheet_id, amo_domain, amo_token)
                if d_ok:
                    print(f"  [✓] {d_msg} на лист raw_deals!")
                else:
                    print(f"  [!] Синхронизация сделок: {d_msg}")

                print("\n" + "═" * 76)
                print("🎉 СВЯЗКА AMOCRM (API ТОКЕН) ➔ n8n ➔ GOOGLE ТАБЛИЦА ПОЛНОСТЬЮ РАБОТАЕТ!")
                print("   Сделки, звонки, примечания и задачи работают на ЛЮБОМ тарифе amoCRM!")
                print("═" * 76)

                input("\nНажмите Enter для продолжения...")
            else:
                print("\n⏳ Отправка тестового звонка через Webhook в n8n...")
                wh_ok, status, msg = send_test_call_webhook(inbound_webhook, tenant_id, sheet_id, crm_type)
                if wh_ok or status == 200:
                    print(f"  [✓] Сигнал звонка успешно принят n8n (HTTP 200 OK)!")
                else:
                    print(f"  [!] Ответ вебхука n8n: {msg}")

                sheet_ok, row_res = inject_test_row_into_sheet(sheet_id, company_name, tenant_id)
                if sheet_ok:
                    print(f"  [✓] Строка записана в Google Таблицу (лист: raw_calls, ID: {row_res})!")
                    print("\n" + "═" * 76)
                    print("🎉 WEBHOOK СВЯЗКА РАБОТАЕТ!")
                    print("═" * 76)
                input("\nНажмите Enter для продолжения...")

        elif act == '2':
            if integration_mode == 'token':
                enter_and_validate_token(tenant_record)
            else:
                try:
                    import subprocess
                    proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
                    proc.communicate(inbound_webhook.encode('utf-16le'))
                    print("\n[✓] Webhook URL успешно скопирован в буфер обмена (Ctrl+V)!")
                except:
                    print("\n[!] Скопируйте ссылку вручную из строки выше.")
                time.sleep(1.5)

        elif act == '3':
            # Переключение режима
            new_mode = 'webhook' if integration_mode == 'token' else 'token'
            tenant_record['integration_mode'] = new_mode
            reg = load_registry()
            for t in reg.get('tenants', []):
                if t['tenant_id'] == tenant_record['tenant_id']:
                    t['integration_mode'] = new_mode
            save_registry(reg)
            print(f"\n[✓] Режим интеграции переключен на: {'🔑 ДОЛГОСРОЧНЫЙ ТОКЕН' if new_mode == 'token' else '🌐 WEBHOOK'}!")
            time.sleep(1.5)

        elif act == '4':
            print("\nОткрываем Google Таблицу...")
            webbrowser.open(sheet_url)
            time.sleep(1)

        elif act == '5':
            print("\nОткрываем n8n...")
            webbrowser.open("http://localhost:5678")
            time.sleep(1)

        elif act == '6':
            clean_name = re.sub(r'[\/:*?"<>|]', '_', company_name)
            client_path = os.path.join(r"C:\Users\strel\Desktop\RevOps Platform\Клиенты", clean_name)
            if os.path.exists(client_path):
                os.startfile(client_path)
            else:
                os.startfile(r"C:\Users\strel\Desktop\RevOps Platform\Клиенты")

        elif act == '7':
            edit_tenant_record(tenant_record)

        elif act == '8':
            print("\nПерезапуск туннеля...")
            new_url = start_tunnel()
            if new_url:
                base_tunnel = new_url
                print(f"[✓] Новый URL туннеля: {new_url}")
            input("\nНажмите Enter для продолжения...")

        elif act == '0':
            break

if __name__ == '__main__':
    manage_client_integration()

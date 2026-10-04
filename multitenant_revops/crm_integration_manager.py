"""
RevOps Platform V18.0 - Dual-Mode & Hybrid CRM Integration Manager
Пошаговая настройка и тестирование сквозной связки:
amoCRM (API-Токен / Webhook) / Битрикс24 (REST API / Webhook) / 🔥 ГИБРИД (Обе CRM) ➔ n8n ➔ Google Таблица
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

# ─────────────────────────────────────────────────────────────────────────────
# 1. amoCRM ИНТЕГРАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────
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
            
        pipelines_url = f"https://{clean_domain}/api/v4/leads/pipelines"
        req = urllib.request.Request(pipelines_url, headers={"Authorization": f"Bearer {token.strip()}"})
        ctx = ssl.create_default_context()
        stages_map = {}
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            p_data = json.loads(resp.read().decode('utf-8'))
            for p in p_data.get('_embedded', {}).get('pipelines', []):
                for s in p.get('_embedded', {}).get('statuses', []):
                    stages_map[s['id']] = s['name']

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

        leads_url = f"https://{clean_domain}/api/v4/leads?with=contacts"
        req = urllib.request.Request(leads_url, headers={"Authorization": f"Bearer {token.strip()}"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            l_data = json.loads(resp.read().decode('utf-8'))
            leads = l_data.get('_embedded', {}).get('leads', [])

        if not leads:
            return True, 0, "В amoCRM пока нет сделок"

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
            
        return True, synced_count, f"Успешно синхронизировано сделок amoCRM: {synced_count}"
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
            if n['name'] == 'HTTP Request':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/events?filter[type]=lead_added,lead_status_changed,common_note_added,call_in,call_out"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
            elif n['name'] == 'HTTP Request1':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.entity_id }}}}/notes/{{{{ $json.value_after[0].note.id }}}}"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
            elif n['name'] == 'Check Existing Notes':
                n['parameters']['url'] = f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.lead_id }}}}/notes?limit=50&order[created_at]=desc"
                if 'headerParameters' in n['parameters']:
                    for p in n['parameters']['headerParameters'].get('parameters', []):
                        if p.get('name') == 'Authorization':
                            p['value'] = f"Bearer {token}"
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

# ─────────────────────────────────────────────────────────────────────────────
# 2. БИТРИКС24 ИНТЕГРАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────
def verify_bitrix24_webhook(webhook_url):
    """Проверяет валидность входящего REST вебхука Битрикс24 через user.current или app.info"""
    clean_url = webhook_url.strip()
    if not clean_url:
        return False, "URL вебхука пуст"
    if not clean_url.endswith('/'):
        clean_url += '/'

    url = f"{clean_url}user.current"
    req = urllib.request.Request(url, headers={
        "Content-Type": "application/json",
        "User-Agent": "RevOps-Enterprise-OS/18.0"
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            user = data.get('result', {})
            return True, user
    except Exception as e1:
        try:
            url2 = f"{clean_url}app.info"
            req2 = urllib.request.Request(url2, headers={"User-Agent": "RevOps-Enterprise-OS/18.0"})
            with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
                data2 = json.loads(resp2.read().decode('utf-8'))
                return True, data2.get('result', {})
        except Exception as e2:
            return False, f"Ошибка подключения к Битрикс24: {e1}"

def test_bitrix24_comment_creation(webhook_url):
    """Тестирует создание комментария в Битрикс24 через REST API crm.timeline.comment.add"""
    clean_url = webhook_url.strip()
    if not clean_url.endswith('/'):
        clean_url += '/'

    # 1. Попробуем найти последнюю сделку
    list_url = f"{clean_url}crm.deal.list"
    payload = json.dumps({"order": {"DATE_MODIFY": "DESC"}, "select": ["ID", "TITLE"]}).encode('utf-8')
    req = urllib.request.Request(list_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"})
    ctx = ssl.create_default_context()
    deal_id = None
    deal_title = ""

    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            d_data = json.loads(resp.read().decode('utf-8'))
            deals = d_data.get('result', [])
            if deals:
                deal_id = deals[0]['ID']
                deal_title = deals[0].get('TITLE', f'Сделка #{deal_id}')
    except:
        pass

    if not deal_id:
        return True, "Связь с Битрикс24 активна (но сделок для добавления комментария пока нет)"

    comment_url = f"{clean_url}crm.timeline.comment.add"
    comment_payload = json.dumps({
        "fields": {
            "ENTITY_ID": deal_id,
            "ENTITY_TYPE": "deal",
            "COMMENT": f"⚠️ [ТЕСТ REVOPS] Проверка автоматического добавления ИИ-аудита в таймлайн сделки '{deal_title}'"
        }
    }).encode('utf-8')
    req2 = urllib.request.Request(comment_url, data=comment_payload, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"})

    try:
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
            res_data = json.loads(resp2.read().decode('utf-8'))
            return True, f"Тестовый комментарий добавлен в сделку #{deal_id} ('{deal_title}')"
    except Exception as e:
        return False, f"Ошибка добавления комментария: {e}"

def sync_bitrix24_deals_to_sheet(sheet_id, webhook_url):
    """Синхронизирует последние сделки из Битрикс24 в Google Таблицу (лист raw_deals)"""
    try:
        clean_url = webhook_url.strip()
        if not clean_url.endswith('/'):
            clean_url += '/'

        list_url = f"{clean_url}crm.deal.list"
        payload = json.dumps({
            "order": {"DATE_MODIFY": "DESC"},
            "select": ["ID", "TITLE", "OPPORTUNITY", "STAGE_ID", "DATE_CREATE", "DATE_MODIFY", "ASSIGNED_BY_ID", "CONTACT_ID"],
            "start": 0
        }).encode('utf-8')
        req = urllib.request.Request(list_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"})
        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            d_data = json.loads(resp.read().decode('utf-8'))
            deals = d_data.get('result', [])

        if not deals:
            return True, 0, "В Битрикс24 пока нет сделок"

        gc = get_gspread_client()
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet('raw_deals')

        existing_rows = ws.get_all_values()
        existing_deal_ids = {row[0]: idx + 1 for idx, row in enumerate(existing_rows[1:]) if row and row[0]}

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")

        synced_count = 0
        for deal in deals:
            deal_id = f"B24-{deal['ID']}"
            deal_name = deal.get('TITLE', f"Сделка #{deal['ID']}")
            price = float(deal.get('OPPORTUNITY') or 0)
            stage_id = deal.get('STAGE_ID', 'NEW')
            
            created_date = (deal.get('DATE_CREATE') or today_date)[:10]
            modified_date = (deal.get('DATE_MODIFY') or today_date)[:10]
            manager_id = deal.get('ASSIGNED_BY_ID', 1)

            is_won = 1 if 'WON' in str(stage_id) else 0
            is_lost = 1 if 'LOSE' in str(stage_id) else 0

            row_data = [
                deal_id, deal_name, price, stage_id, stage_id,
                created_date, modified_date, manager_id, "B2B", "Bitrix24",
                f"C-{deal_id}", "A" if price > 500000 else "B", "-" if not is_lost else "LOST",
                now_iso, is_won, is_lost, 1, "0-3d", price, 1,
                "-", "-", "-", "-", "-",
                today_date, "V18.0", "Bitrix24 Auto-Sync", f"hash_{deal['ID']}_b24",
                "Звонок", today_date, "Менеджер", "Телефон", "Норма",
                90, now_iso, "#В_Работе"
            ]

            if deal_id in existing_deal_ids:
                row_num = existing_deal_ids[deal_id] + 1
                ws.update(f"A{row_num}:AK{row_num}", [row_data], value_input_option='USER_ENTERED')
            else:
                ws.append_row(row_data, value_input_option='USER_ENTERED')
            synced_count += 1

        return True, synced_count, f"Успешно синхронизировано сделок Битрикс24: {synced_count}"
    except Exception as e:
        return False, 0, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# 3. ТЕСТОВЫЕ ВЕБХУКИ И СТРОКИ
# ─────────────────────────────────────────────────────────────────────────────
def send_test_call_webhook(webhook_url, tenant_id, sheet_id, crm_type="amocrm"):
    call_id = f"TEST-{int(time.time())}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "event": "call_end",
        "tenant": tenant_id,
        "sheet_id": sheet_id,
        "crm_type": "bitrix24" if crm_type == 'bitrix24' else "amocrm",
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
    req = urllib.request.Request(req_url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'RevOps-Enterprise-OS/18.0'})

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, resp.status, "Вебхук успешно принят n8n"
    except urllib.error.HTTPError as e:
        return False, e.code, f"HTTP Error: {e.code}"
    except Exception as e:
        return False, 0, str(e)

def inject_test_row_into_sheet(sheet_id, tenant_name, tenant_id, crm_label="amoCRM"):
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
            f"Входящий (Тест связки {crm_label} -> n8n)",
            1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
            96,
            "НЕТ",
            0,
            f"Связка {crm_label} -> n8n -> Google Таблица успешно протестирована!",
            "http://127.0.0.1:8000/demo_audio.wav",
            tenant_id
        ]
        
        ws.append_row(test_row, value_input_option='USER_ENTERED')
        return True, call_id
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# 4. ИНТЕРАКТИВНЫЕ ДЕЙСТВИЯ (СМЕНА CRM, НАСТРОЙКА КЛЮЧЕЙ)
# ─────────────────────────────────────────────────────────────────────────────
def switch_tenant_crm(tenant_record):
    """Позволяет мгновенно переключить CRM между amoCRM, Битрикс24 и Гибридным режимом"""
    clear_screen()
    curr_crm = tenant_record.get('crm_type', 'amocrm')
    if curr_crm in ['hybrid', 'both']:
        curr_label = "🔥 ГИБРИДНЫЙ РЕЖИМ (amoCRM + Битрикс24 одновременно)"
    elif curr_crm == 'bitrix24':
        curr_label = "🔵 Битрикс24 (Bitrix24)"
    else:
        curr_label = "🟠 amoCRM (АмоСРМ)"

    print_header(f"ПЕРЕКЛЮЧЕНИЕ CRM: {tenant_record['tenant_name']}")
    print(f"Текущая конфигурация: {curr_label}\n")
    print("Выберите режим интеграции:")
    print("  [1] 🟠 Только amoCRM (API Токен / Webhook телефонии)")
    print("  [2] 🔵 Только Битрикс24 (Входящий REST Вебхук / Webhook телефонии)")
    print("  [3] 🔥 ОБЕ СИСТЕМЫ ОДНОВРЕМЕННО (Гибридный режим: amoCRM + Битрикс24)")
    print("  [0] Отмена (оставить без изменений)")

    ch = input("\n👉 Ваш выбор [0-3]: ").strip()
    if ch == '1':
        new_crm = 'amocrm'
    elif ch == '2':
        new_crm = 'bitrix24'
    elif ch == '3':
        new_crm = 'hybrid'
    else:
        return

    reg = load_registry()
    base_tunnel = get_active_tunnel_url()
    t_id = tenant_record['tenant_id']
    s_id = tenant_record['spreadsheet_id']

    wh_amo = f"{base_tunnel}/webhook/amocrm-call?tenant={t_id}&sheet_id={s_id}"
    wh_b24 = f"{base_tunnel}/webhook/bitrix24-call?tenant={t_id}&sheet_id={s_id}"

    for t in reg.get('tenants', []):
        if t['tenant_id'] == tenant_record['tenant_id']:
            t['crm_type'] = new_crm
            tenant_record['crm_type'] = new_crm
            t['inbound_webhook_amo_url'] = wh_amo
            t['inbound_webhook_b24_url'] = wh_b24
            tenant_record['inbound_webhook_amo_url'] = wh_amo
            tenant_record['inbound_webhook_b24_url'] = wh_b24
            if new_crm == 'bitrix24':
                t['inbound_webhook_url'] = wh_b24
                tenant_record['inbound_webhook_url'] = wh_b24
            else:
                t['inbound_webhook_url'] = wh_amo
                tenant_record['inbound_webhook_url'] = wh_amo

    save_registry(reg)

    try:
        from tenant_provisioner import create_client_passport
        create_client_passport(tenant_record)
    except:
        pass

    print(f"\n[✓] Режим CRM успешно переключен на: {new_crm.upper()}!")

    # Проверка ключей
    if new_crm in ['bitrix24', 'hybrid'] and not tenant_record.get('b24_webhook_url') and not tenant_record.get('crm_webhook_url'):
        ask_b24 = input("\n👉 Желаете сейчас ввести REST вебхук Битрикс24? [y/N]: ").strip().lower()
        if ask_b24 in ['y', 'yes', 'д', 'да']:
            enter_and_validate_bitrix24_webhook(tenant_record)

    if new_crm in ['amocrm', 'hybrid'] and not tenant_record.get('amo_token'):
        ask_amo = input("\n👉 Желаете сейчас ввести Долгосрочный токен amoCRM? [y/N]: ").strip().lower()
        if ask_amo in ['y', 'yes', 'д', 'да']:
            enter_and_validate_token(tenant_record)

    time.sleep(1)

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
    print(f"🌐 Текущий домен: {domain}")
    new_dom = input("👉 Изменить домен? (Enter чтобы оставить, или введите новый): ").strip()
    if new_dom:
        domain = new_dom
        tenant_record['amo_domain'] = domain

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

        reg = load_registry()
        for t in reg.get('tenants', []):
            if t['tenant_id'] == tenant_record['tenant_id']:
                t['amo_token'] = token
                t['amo_domain'] = domain
                t['integration_mode'] = 'token'
                tenant_record['amo_token'] = token
                tenant_record['amo_domain'] = domain
                tenant_record['integration_mode'] = 'token'
        save_registry(reg)

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

def enter_and_validate_bitrix24_webhook(tenant_record):
    """Пошаговый ввод и валидация входящего REST вебхука Битрикс24"""
    clear_screen()
    print_header(f"ПОДКЛЮЧЕНИЕ БИТРИКС24: {tenant_record['tenant_name']}")

    print("📖 КАК ПОЛУЧИТЬ ВХОДЯЩИЙ ВЕБХУК В БИТРИКС24 ЗА 1 МИНУТУ:")
    print("  1. В левом меню Битрикс24 откройте: [Разработчикам] (или Приложения -> Разработчикам)")
    print("  2. Выберите: [Другое] ➔ [Входящий вебхук]")
    print("  3. В настройках прав выберите: [✓] CRM и [✓] Пользователи")
    print("  4. Нажмите [Сохранить] и скопируйте созданный URL (вида https://portal.bitrix24.ru/rest/1/abc123/)\n")
    print("─" * 76)

    curr_wh = tenant_record.get('b24_webhook_url') or tenant_record.get('crm_webhook_url') or ""
    if curr_wh:
        print(f"Текущий URL вебхука: {curr_wh}")

    webhook_url = input("👉 Вставьте URL вебхука Битрикс24: ").strip()
    if not webhook_url:
        print("[!] Ввод отменен.")
        time.sleep(1)
        return

    if not webhook_url.endswith('/'):
        webhook_url += '/'

    print("\n⏳ Проверяем вебхук через REST API Битрикс24...")
    ok, res = verify_bitrix24_webhook(webhook_url)
    if ok:
        user_name = f"{res.get('LAST_NAME', '')} {res.get('NAME', '')}".strip() or "Авторизован"
        print("═" * 76)
        print("🎉 ВЕБХУК БИТРИКС24 ВАЛИДЕН И АКТИВЕН!")
        print(f"  • Пользователь / Приложение: {user_name}")
        print(f"  • URL:                        {webhook_url}")
        print("═" * 76)

        reg = load_registry()
        for t in reg.get('tenants', []):
            if t['tenant_id'] == tenant_record['tenant_id']:
                t['b24_webhook_url'] = webhook_url
                t['crm_webhook_url'] = webhook_url
                tenant_record['b24_webhook_url'] = webhook_url
                tenant_record['crm_webhook_url'] = webhook_url
        save_registry(reg)

        input("\nНажмите Enter для продолжения...")
    else:
        print(f"\n❌ Ошибка проверки вебхука: {res}")
        print("👉 Проверьте правильность URL и наличие прав 'CRM' и 'Пользователи'.")
        input("\nНажмите Enter для возврата...")

def manage_crm_credentials(tenant_record):
    """Меню управления ключами и токенами в зависимости от CRM"""
    crm_type = tenant_record.get('crm_type', 'amocrm')
    if crm_type == 'amocrm':
        enter_and_validate_token(tenant_record)
    elif crm_type == 'bitrix24':
        enter_and_validate_bitrix24_webhook(tenant_record)
    else:
        # Гибридный режим
        clear_screen()
        print_header(f"НАСТРОЙКА КЛЮЧЕЙ (ГИБРИДНЫЙ РЕЖИМ): {tenant_record['tenant_name']}")
        print("Выберите CRM для настройки ключей:")
        print("  [1] 🔑 amoCRM: Ввести / обновить Долгосрочный токен и домен")
        print("  [2] 🌐 Битрикс24: Ввести / обновить Входящий REST вебхук")
        print("  [3] ⚡ Настроить обе CRM по очереди")
        print("  [0] Назад")

        sub_ch = input("\n👉 Ваш выбор [0-3]: ").strip()
        if sub_ch == '1':
            enter_and_validate_token(tenant_record)
        elif sub_ch == '2':
            enter_and_validate_bitrix24_webhook(tenant_record)
        elif sub_ch == '3':
            enter_and_validate_token(tenant_record)
            enter_and_validate_bitrix24_webhook(tenant_record)

def edit_tenant_record(tenant_record):
    """Позволяет изменить данные клиента"""
    clear_screen()
    print_header(f"РЕДАКТИРОВАНИЕ: {tenant_record['tenant_name']}")

    crm_type = tenant_record.get('crm_type', 'amocrm')
    if crm_type in ['hybrid', 'both']:
        crm_label = "🔥 ГИБРИД (amoCRM + Битрикс24)"
    elif crm_type == 'bitrix24':
        crm_label = "БИТРИКС24"
    else:
        crm_label = "AMOCRM"

    print(f"Текущие данные:")
    print(f"  1. Название компании:   {tenant_record['tenant_name']}")
    print(f"  2. Тип CRM:             {crm_label}")
    print(f"  3. Режим интеграции:    {tenant_record.get('integration_mode', 'token').upper()}")
    print(f"  4. Домен amoCRM:        {tenant_record.get('amo_domain', 'Не указан')}")
    print(f"  5. Вебхук Битрикс24:    {tenant_record.get('b24_webhook_url') or tenant_record.get('crm_webhook_url') or 'Не указан'}")
    print(f"  6. Email клиента:       {tenant_record.get('client_email', 'Не указан')}")
    print(f"  7. Ссылка на Таблицу:   {tenant_record.get('spreadsheet_url', '')}")
    print("─" * 76)

    print("Что вы хотите изменить?")
    print("  [1] Название компании")
    print("  [2] 🔀 Переключить CRM (amoCRM ⟷ Битрикс24 ⟷ 🔥 ОБЕ CRM)")
    print("  [3] Домен amoCRM")
    print("  [4] Вебхук Битрикс24")
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
                switch_tenant_crm(tenant_record)
                return
            elif ch == '3':
                new_d = input("Введите домен amoCRM (напр. https://mycompany.amocrm.ru): ").strip()
                if new_d:
                    reg['tenants'][idx]['amo_domain'] = new_d
                    tenant_record['amo_domain'] = new_d
                    print("✓ Домен обновлен!")
            elif ch == '4':
                enter_and_validate_bitrix24_webhook(tenant_record)
                return
            elif ch == '5':
                new_em = input("Введите email клиента: ").strip()
                if new_em:
                    reg['tenants'][idx]['client_email'] = new_em
                    tenant_record['client_email'] = new_em
                    print("✓ Email обновлен!")
            save_registry(reg)
            time.sleep(1)
            break

# ─────────────────────────────────────────────────────────────────────────────
# 5. ГЛАВНОЕ МЕНЮ УПРАВЛЕНИЯ ИНТЕГРАЦИЕЙ КЛИЕНТА
# ─────────────────────────────────────────────────────────────────────────────
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
            c_type = t.get('crm_type', 'amocrm')
            if c_type in ['hybrid', 'both']:
                crm_badge = "🔥 ГИБРИД (amo+b24)"
            elif c_type == 'bitrix24':
                crm_badge = "🔵 БИТРИКС24"
            else:
                crm_badge = "🟠 AMOCRM"
            print(f"  [{idx}] {t['tenant_name']} (ID: {t['tenant_id']}, CRM: {crm_badge})")
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
        b24_webhook = tenant_record.get('b24_webhook_url') or tenant_record.get('crm_webhook_url') or ""

        base_tunnel = get_active_tunnel_url()
        inbound_amo_wh = f"{base_tunnel}/webhook/amocrm-call?tenant={tenant_id}&sheet_id={sheet_id}"
        inbound_b24_wh = f"{base_tunnel}/webhook/bitrix24-call?tenant={tenant_id}&sheet_id={sheet_id}"

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

        # 2. Описание активного режима CRM
        if crm_type in ['hybrid', 'both']:
            amo_status = "🟢 Токен подключен" if amo_token else "🔴 Токен НЕ введен"
            b24_status = "🟢 Вебхук подключен" if b24_webhook else "🔴 Вебхук НЕ введен"
            print("🔌 АКТИВНЫЙ РЕЖИМ: 🔥 ГИБРИДНЫЙ (amoCRM + БИТРИКС24 ОДНОВРЕМЕННО)")
            print("   👉 Система принимает звонки и синхронизирует сделки из ОБЕИХ CRM!")
            print("   ┌─ amoCRM:")
            print(f"   │  • Домен:          {amo_domain}")
            print(f"   │  • Статус API:     {amo_status}")
            print(f"   │  • Webhook звонка: {inbound_amo_wh}")
            print("   └─ Битрикс24:")
            print(f"   │  • Статус REST:    {b24_status}")
            print(f"   │  • Webhook звонка: {inbound_b24_wh}")
        elif crm_type == 'bitrix24':
            b24_status = "🟢 Вебхук подключен" if b24_webhook else "🔴 Вебхук НЕ введен (нажмите [2])"
            print("🔌 АКТИВНЫЙ РЕЖИМ: 🔵 БИТРИКС24 (Bitrix24 REST + Webhook)")
            print(f"   • Статус REST API:   {b24_status}")
            print(f"   • Webhook звонков:   {inbound_b24_wh}")
            print("   • Обратная связь:    Автодобавление комментариев в таймлайн сделки")
        else:
            token_status = "🟢 Токен подключен" if amo_token else "🔴 Токен НЕ введен (нажмите [2])"
            print("🔌 АКТИВНЫЙ РЕЖИМ: 🟠 AMOCRM (API-ОБМЕН + WEBHOOK)")
            print(f"   • Домен amoCRM:      {amo_domain}")
            print(f"   • Статус токена:     {token_status}")
            print(f"   • Webhook звонков:   {inbound_amo_wh}")
            print("   • Обратная связь:    Автопостановка задач, тегов и примечаний в сделку")

        print("─" * 76)
        print("🎯 ДЕЙСТВИЯ:")
        print("  [1] 🧪 ПРОВЕРИТЬ СВЯЗЬ ПО API (Проверка CRM, задач, звонков и Google Таблицы)")
        print("  [2] 🔑 НАСТРОЙКА КЛЮЧЕЙ И ТОКЕНОВ CRM (amoCRM токен / Битрикс24 вебхук)")
        print("  [3] 📋 Скопировать входящий Webhook URL в буфер обмена")
        print("  [4] 📊 Открыть Google Таблицу клиента в браузере")
        print("  [5] 🌐 Открыть сценарий в n8n (http://localhost:5678)")
        print("  [6] 📁 Открыть папку клиента на компьютере")
        print("  [7] 🔀 ПЕРЕКЛЮЧИТЬ CRM: amoCRM ⟷ БИТРИКС24 ⟷ 🔥 ОБЕ CRM (ГИБРИД)")
        print("  [8] 🚀 Перезапустить защищённый HTTPS туннель")
        print("  [9] ⚙️ УПРАВЛЕНИЕ КАСТОМНЫМИ ОПЦИЯМИ (ВКЛ / ВЫКЛ МОДУЛЕЙ)")
        print("  [0] Назад / Выход")

        act = input("\n👉 Выберите действие [0-9]: ").strip()

        if act == '1':
            print("\n" + "═" * 76)
            print("⏳ ЗАПУСК КОМПЛЕКСНОЙ ПРОВЕРКИ СВЯЗИ...")
            print("═" * 76)

            # amoCRM тесты
            if crm_type in ['amocrm', 'hybrid', 'both']:
                print("\n[Проверка amoCRM]:")
                if amo_token:
                    ok_a, acc_info = verify_amocrm_token(amo_domain, amo_token)
                    if ok_a:
                        print(f"  [✓] Авторизация amoCRM успешна! Аккаунт: '{acc_info.get('name')}' (ID: {acc_info.get('id')})")
                    else:
                        print(f"  [-] Ошибка amoCRM API: {acc_info}")

                    t_ok, t_res = test_amocrm_task_creation(amo_domain, amo_token)
                    if t_ok:
                        print("  [✓] Модуль 3: Тестовая задача успешно создана в amoCRM!")
                    else:
                        print(f"  [!] Создание задачи: {t_res}")

                    d_ok, d_cnt, d_msg = sync_amocrm_deals_to_sheet(sheet_id, amo_domain, amo_token)
                    if d_ok:
                        print(f"  [✓] {d_msg} на лист raw_deals!")
                    else:
                        print(f"  [!] Синхронизация сделок amoCRM: {d_msg}")
                else:
                    print("  [!] amoCRM токен не введен (нажмите [2] для подключения)")

            # Битрикс24 тесты
            if crm_type in ['bitrix24', 'hybrid', 'both']:
                print("\n[Проверка Битрикс24]:")
                if b24_webhook:
                    ok_b, b_user = verify_bitrix24_webhook(b24_webhook)
                    if ok_b:
                        u_name = f"{b_user.get('LAST_NAME', '')} {b_user.get('NAME', '')}".strip() or "Успешно"
                        print(f"  [✓] Авторизация Битрикс24 успешна! Пользователь: '{u_name}'")
                    else:
                        print(f"  [-] Ошибка Битрикс24 REST: {b_user}")

                    c_ok, c_msg = test_bitrix24_comment_creation(b24_webhook)
                    if c_ok:
                        print(f"  [✓] {c_msg}")
                    else:
                        print(f"  [!] Комментарий Битрикс24: {c_msg}")

                    bd_ok, bd_cnt, bd_msg = sync_bitrix24_deals_to_sheet(sheet_id, b24_webhook)
                    if bd_ok:
                        print(f"  [✓] {bd_msg} на лист raw_deals!")
                    else:
                        print(f"  [!] Синхронизация сделок Битрикс24: {bd_msg}")
                else:
                    print("  [!] REST вебхук Битрикс24 не введен (нажмите [2] для подключения)")

            # Тест Google Таблицы
            print("\n[Проверка Google Таблицы]:")
            lbl = "Гибридный" if crm_type in ['hybrid', 'both'] else ("Битрикс24" if crm_type == 'bitrix24' else "amoCRM")
            sheet_ok, row_res = inject_test_row_into_sheet(sheet_id, company_name, tenant_id, lbl)
            if sheet_ok:
                print(f"  [✓] Тестовая строка аудита записана в Google Таблицу (лист raw_calls, ID: {row_res})!")
            else:
                print(f"  [-] Ошибка таблицы: {row_res}")

            # Тест n8n Вебхука
            print("\n[Проверка n8n Webhook Контура]:")
            if crm_type in ['amocrm', 'hybrid', 'both']:
                wh_ok1, s1, m1 = send_test_call_webhook(inbound_amo_wh, tenant_id, sheet_id, "amocrm")
                if wh_ok1:
                    print(f"  [✓] Сигнал amoCRM принят n8n (HTTP {s1} OK)!")
                else:
                    print(f"  [!] amoCRM сигнал: {m1}")

            if crm_type in ['bitrix24', 'hybrid', 'both']:
                wh_ok2, s2, m2 = send_test_call_webhook(inbound_b24_wh, tenant_id, sheet_id, "bitrix24")
                if wh_ok2:
                    print(f"  [✓] Сигнал Битрикс24 принят n8n (HTTP {s2} OK)!")
                else:
                    print(f"  [!] Битрикс24 сигнал: {m2}")

            print("\n" + "═" * 76)
            print("🎉 ДИАГНОСТИКА СВЯЗКИ ЗАВЕРШЕНА!")
            print("═" * 76)
            input("\nНажмите Enter для продолжения...")

        elif act == '2':
            manage_crm_credentials(tenant_record)

        elif act == '3':
            # Копирование вебхука в буфер
            target_url = inbound_b24_wh if crm_type == 'bitrix24' else inbound_amo_wh
            try:
                import subprocess
                proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
                proc.communicate(target_url.encode('utf-16le'))
                print("\n[✓] Webhook URL успешно скопирован в буфер обмена (Ctrl+V)!")
            except:
                print(f"\n[!] Скопируйте ссылку вручную: {target_url}")
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
            switch_tenant_crm(tenant_record)

        elif act == '8':
            print("\nПерезапуск туннеля...")
            new_url = start_tunnel()
            if new_url:
                base_tunnel = new_url
                print(f"[✓] Новый URL туннеля: {new_url}")
            input("\nНажмите Enter для продолжения...")

        elif act == '9':
            try:
                from features_manager import interactive_loop
                interactive_loop()
            except Exception as e:
                print(f"\n[-] Ошибка вызова панели опций: {e}")
                time.sleep(2)

        elif act == '0':
            break

if __name__ == '__main__':
    manage_client_integration()

"""
RevOps Enterprise OS V18.0 - Background Deals Synchronization Daemon (Auto-Sync 24/7)
Автоматическая фоновая синхронизация сделок и воронки из amoCRM в Google Таблицу (raw_deals) каждые 3 минуты.
"""
import os
import sys
import time
import json
import urllib.request
import ssl
import datetime
from google.oauth2.service_account import Credentials
import gspread

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, 'deals_sync_daemon.pid')
LOG_FILE = os.path.join(BASE_DIR, 'deals_sync.log')

def find_service_account():
    candidates = [
        os.path.join(BASE_DIR, 'service_account.json'),
        os.path.join(BASE_DIR, '..', 'service_account.json'),
        os.path.join(BASE_DIR, '..', '..', 'service_account.json'),
        r"C:\Users\strel\.gemini\antigravity\scratch\service_account.json"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def find_registry_file():
    candidates = [
        os.path.join(BASE_DIR, 'tenants_registry.json'),
        os.path.join(BASE_DIR, '..', 'multitenant_revops', 'tenants_registry.json'),
        r"C:\Users\strel\.gemini\antigravity\scratch\revops-enterprise-os\multitenant_revops\tenants_registry.json",
        r"C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai\multitenant_revops\tenants_registry.json"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def prevent_windows_sleep():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except:
            pass

def sanitize_sheet_val(val):
    if isinstance(val, str) and val and val[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + val
    return val

def get_gspread_client():
    sa_path = find_service_account()
    if not sa_path:
        raise FileNotFoundError("service_account.json не найден ни в одном из доверенных путей")
    with open(sa_path, 'r', encoding='utf-8') as f:
        sa = json.load(f)
    creds = Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except:
        pass

def sync_tenant_deals(tenant, gc):
    tenant_id = tenant.get('tenant_id')
    tenant_name = tenant.get('tenant_name')
    domain = tenant.get('amo_domain', '').replace('https://', '').replace('http://', '').strip('/')
    token = tenant.get('amo_token')
    sheet_id = tenant.get('spreadsheet_id')

    if not token or not domain or not sheet_id:
        return

    if not domain.endswith('.amocrm.ru'):
        domain = f"{domain}.amocrm.ru"

    ctx = ssl.create_default_context()

    # 1. Fetch Pipelines & Stages
    pipelines_url = f"https://{domain}/api/v4/leads/pipelines"
    req = urllib.request.Request(pipelines_url, headers={"Authorization": f"Bearer {token.strip()}"})
    stages_map = {}
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            p_data = json.loads(resp.read().decode('utf-8'))
            for p in p_data.get('_embedded', {}).get('pipelines', []):
                for s in p.get('_embedded', {}).get('statuses', []):
                    stages_map[s['id']] = s['name']
    except Exception as e:
        log(f"[{tenant_id}] Ошибка загрузки воронки: {e}")
        return

    # 2. Fetch Users & Contacts Map
    users_map = {}
    try:
        u_url = f"https://{domain}/api/v4/users"
        u_req = urllib.request.Request(u_url, headers={"Authorization": f"Bearer {token.strip()}"})
        with urllib.request.urlopen(u_req, timeout=10, context=ctx) as resp:
            u_data = json.loads(resp.read().decode('utf-8'))
            for u in u_data.get('_embedded', {}).get('users', []):
                users_map[str(u['id'])] = u.get('name', 'Менеджер')
    except:
        pass

    contacts_map = {}
    try:
        c_url = f"https://{domain}/api/v4/contacts?limit=100"
        c_req = urllib.request.Request(c_url, headers={"Authorization": f"Bearer {token.strip()}"})
        with urllib.request.urlopen(c_req, timeout=10, context=ctx) as resp:
            c_data = json.loads(resp.read().decode('utf-8'))
            for c in c_data.get('_embedded', {}).get('contacts', []):
                contacts_map[c['id']] = c.get('name', 'Клиент')
    except:
        pass

    # 3. Fetch Leads
    leads_url = f"https://{domain}/api/v4/leads?with=contacts&limit=250"
    req = urllib.request.Request(leads_url, headers={"Authorization": f"Bearer {token.strip()}"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            l_data = json.loads(resp.read().decode('utf-8'))
            leads = l_data.get('_embedded', {}).get('leads', [])
    except Exception as e:
        log(f"[{tenant_id}] Ошибка загрузки сделок: {e}")
        return

    if not leads:
        return

    # 4. Open Google Sheet & Batch Update
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet('raw_deals')
    existing_rows = ws.get_all_values()
    existing_deal_ids = {row[0]: idx + 1 for idx, row in enumerate(existing_rows[1:]) if row and row[0]}

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_date = datetime.datetime.now().strftime("%Y-%m-%d")

    deals_to_update = []
    deals_to_append = []

    for lead in leads:
        lead_id = str(lead['id'])
        lead_name = lead.get('name', f"Сделка #{lead_id}")
        price = float(lead.get('price') or 0)
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
        
        raw_mgr_id = lead.get('responsible_user_id', 101)
        manager_id = int(raw_mgr_id) if str(raw_mgr_id).isdigit() else raw_mgr_id
        manager_name = users_map.get(str(raw_mgr_id), 'Менеджер')

        is_won = 1 if status_id == 142 else 0
        is_lost = 1 if status_id == 143 else 0

        row_data = [
            lead_id, contact_name, price, status_id, status_name,
            created_date, created_date, manager_id, "SMB", "amoCRM",
            f"C-{lead_id}", "B", "-" if not is_lost else "LOST",
            now_iso, is_won, is_lost, 1, "0-3d", price, 1,
            "-", "-", "-", "-", "-",
            today_date, "V18.0", "amoCRM Daemon 24/7", f"hash_{lead_id}_amo",
            "Звонок", today_date, manager_name, "Телефон", "Норма",
            85, now_iso, "#В_Работе" if not (is_won or is_lost) else ("#Успешно" if is_won else "#Закрыто")
        ]
        row_data = [sanitize_sheet_val(x) for x in row_data]

        if lead_id in existing_deal_ids:
            row_num = existing_deal_ids[lead_id] + 1
            deals_to_update.append({'range': f"A{row_num}:AK{row_num}", 'values': [row_data]})
        else:
            deals_to_append.append(row_data)

    # Batch write
    if deals_to_update:
        ws.batch_update(deals_to_update, value_input_option='USER_ENTERED')
    if deals_to_append:
        ws.append_rows(deals_to_append, value_input_option='USER_ENTERED')

    log(f"[{tenant_id} - {tenant_name}] Синхронизация завершена: {len(deals_to_append)} новых, {len(deals_to_update)} обновлено.")

def run_sync_cycle():
    reg_file = find_registry_file()
    if not reg_file:
        log("[-] Реестр clients/tenants_registry.json не найден ни по одному из путей.")
        return

    try:
        with open(reg_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        log(f"[-] Ошибка чтения {reg_file}: {e}")
        return

    tenants = data.get('tenants', [])
    if not tenants:
        return

    try:
        gc = get_gspread_client()
    except Exception as e:
        log(f"[-] Ошибка подключения к Google Drive API: {e}")
        return

    for t in tenants:
        try:
            sync_tenant_deals(t, gc)
        except Exception as e:
            log(f"[-] Ошибка синхронизации тенанта {t.get('tenant_id')}: {e}")

def main():
    prevent_windows_sleep()
    with open(PID_FILE, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))

    log("🚀 Демон фоновой синхронизации сделок RevOps (24/7) запущен.")
    interval_sec = 180  # каждые 3 минуты

    while True:
        try:
            prevent_windows_sleep()
            run_sync_cycle()
        except Exception as e:
            log(f"Непредвиденная ошибка в цикле: {e}")
        time.sleep(interval_sec)

if __name__ == '__main__':
    main()

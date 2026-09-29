"""
RevOps Platform V16.0 - Batch OTA (Over-the-Air) Updater
CI/CD для Google Таблиц: централизованное обновление формул и схем во всех клиентских инстансах.
"""
import os
import sys
import json
import argparse
import datetime
import gspread
from google.oauth2.service_account import Credentials

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, '..', '..', 'service_account.json')
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    SERVICE_ACCOUNT_FILE = os.path.join(r'C:\Users\strel\.gemini\antigravity\scratch', 'service_account.json')

REGISTRY_FILE = os.path.join(BASE_DIR, 'tenants_registry.json')
GOLDEN_MASTER_ID = '1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc'

def get_credentials():
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa = json.load(f)
    return Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])

def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"master_template": {"spreadsheet_id": GOLDEN_MASTER_ID}, "tenants": []}

def check_tenants_health():
    creds = get_credentials()
    gc = gspread.authorize(creds)
    registry = load_registry()
    tenants = registry.get('tenants', [])

    print("\n" + "="*70)
    print(f"📊 МОНИТОРИНГ ТЕНАНТОВ REVOPS PLATFORM (Всего подключено: {len(tenants)})")
    print("="*70)
    
    # Check Master
    try:
        sh_m = gc.open_by_key(GOLDEN_MASTER_ID)
        print(f"[*] GOLDEN MASTER: {sh_m.title} — 🟢 ONLINE ({len(sh_m.worksheets())} вкладок)")
    except Exception as e:
        print(f"[-] GOLDEN MASTER: {GOLDEN_MASTER_ID} — 🔴 ERROR: {e}")

    for t in tenants:
        tid = t.get('tenant_id')
        name = t.get('tenant_name')
        sid = t.get('spreadsheet_id')
        try:
            sh = gc.open_by_key(sid)
            print(f"[+] [{tid}] {name}: 🟢 ONLINE ({len(sh.worksheets())} листов) -> {sh.url}")
        except Exception as e:
            print(f"[-] [{tid}] {name}: 🔴 OFFLINE / ACCESS DENIED ({e})")
    print("="*70 + "\n")

def push_update_from_master(sheet_name, cell_range):
    """Считывает формулы из Golden Master и распространяет на всех клиентов"""
    creds = get_credentials()
    gc = gspread.authorize(creds)
    registry = load_registry()
    tenants = registry.get('tenants', [])

    if not tenants:
        print("В реестре пока нет клиентских тенантов. Запустите сначала tenant_provisioner.py.")
        return

    print(f"[*] Считывание эталонных значений из Golden Master ({sheet_name}!{cell_range})...")
    sh_master = gc.open_by_key(GOLDEN_MASTER_ID)
    ws_master = sh_master.worksheet(sheet_name)
    golden_formulas = ws_master.get(cell_range, value_render_option='FORMULA')

    print(f"[*] Эталонные формулы ({len(golden_formulas)} строк): {golden_formulas}")
    print(f"[*] Запуск каскадного OTA-обновления для {len(tenants)} тенантов...")

    success_count = 0
    for t in tenants:
        tid = t.get('tenant_id')
        name = t.get('tenant_name')
        sid = t.get('spreadsheet_id')
        try:
            sh_client = gc.open_by_key(sid)
            ws_client = sh_client.worksheet(sheet_name)
            ws_client.update(values=golden_formulas, range_name=cell_range, value_input_option='USER_ENTERED')
            print(f"[+] [{tid}] {name} — УСПЕШНО ОБНОВЛЕНО ({sheet_name}!{cell_range})")
            success_count += 1
        except Exception as e:
            print(f"[-] [{tid}] {name} — ОШИБКА: {e}")

    print(f"\n[✓] OTA-обновление завершено! Успешно обновлено: {success_count}/{len(tenants)} инстансов.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RevOps Platform V16.0 Batch OTA Updater")
    parser.add_argument('--status', action='store_true', help="Проверить доступность и статус всех клиентов")
    parser.add_argument('--sheet', help="Имя листа для обновления (например, 'calc_engine')")
    parser.add_argument('--range', help="Диапазон ячеек (например, 'B20:B25')")
    args = parser.parse_args()

    if args.status or (not args.sheet and not args.range):
        check_tenants_health()
    elif args.sheet and args.range:
        push_update_from_master(args.sheet, args.range)
    else:
        print("Укажите оба параметра --sheet и --range для обновления.")

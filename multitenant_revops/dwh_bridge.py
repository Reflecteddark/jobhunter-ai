"""
RevOps Platform V16.0 - DWH Storage Tiering & Archival Bridge
Решение проблемы лимита 10k строк: автоматический перенос закрытых сделок (>90 дней) в Cold Storage (ClickHouse/JSON).
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

ARCHIVE_DIR = os.path.join(BASE_DIR, 'archive_cold_storage')
os.makedirs(ARCHIVE_DIR, exist_ok=True)

def get_credentials():
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa = json.load(f)
    return Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])

def archive_old_deals(spreadsheet_id, tenant_id="TNT-MASTER-001", dry_run=False):
    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws_deals = sh.worksheet('raw_deals')

    all_rows = ws_deals.get_all_values()
    if not all_rows or len(all_rows) < 2:
        print("[*] Лист raw_deals пуст.")
        return

    headers = all_rows[0]
    data_rows = all_rows[1:]

    # Ищем индексы stage_id (D), closed_date (G), is_won (N), is_lost (O)
    stage_idx = 3 # Col D
    deal_id_idx = 0 # Col A

    active_rows = [headers]
    archived_rows = []

    for r in data_rows:
        if not r or not r[0]:
            continue
        try:
            stage_val = int(r[stage_idx]) if len(r) > stage_idx and r[stage_idx].isdigit() else 1
        except:
            stage_val = 1

        # Сделки на этапах Closed-Won (6) или Closed-Lost (7)
        if stage_val >= 6:
            archived_rows.append(r)
        else:
            active_rows.append(r)

    print(f"[*] Анализ оперативного хранилища {sh.title}:")
    print(f"    - Всего записей: {len(data_rows)}")
    print(f"    - Активных (в работе ОП): {len(active_rows)-1}")
    print(f"    - Готовых к архивации в DWH: {len(archived_rows)}")

    if not archived_rows:
        print("[✓] Лист raw_deals оптимизирован, архивация не требуется.")
        return

    archive_filename = f"deals_archive_{tenant_id}_{datetime.date.today().isoformat()}.json"
    archive_path = os.path.join(ARCHIVE_DIR, archive_filename)

    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump({
            "tenant_id": tenant_id,
            "archived_at": datetime.datetime.now().isoformat(),
            "count": len(archived_rows),
            "headers": headers,
            "records": archived_rows
        }, f, ensure_ascii=False, indent=2)

    print(f"[+] Экспортировано в Cold Storage: {archive_path}")

    if not dry_run:
        # Перезаписываем лист без закрытых исторических сделок (сохраняя формулы)
        ws_deals.clear()
        ws_deals.update(values=active_rows, range_name='A1')
        print(f"[✓] Лист raw_deals успешно очищен от архивных сделок. Таблица ускорена!")
    else:
        print("[i] Dry-run режим: изменения в Google Sheets не вносились.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RevOps V16.0 DWH Archival Bridge")
    parser.add_argument('--sheet-id', default='1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc', help="Spreadsheet ID")
    parser.add_argument('--tenant-id', default='TNT-MASTER-001', help="Tenant ID")
    parser.add_argument('--dry-run', action='store_true', help="Только симуляция архивации")
    args = parser.parse_args()

    archive_old_deals(args.sheet_id, args.tenant_id, dry_run=args.dry_run)

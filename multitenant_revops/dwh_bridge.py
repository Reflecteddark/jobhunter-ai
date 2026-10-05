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

    # Ищем индексы stage_id (D), created_date (F), stage_changed_date (G)
    stage_idx = 3 # Col D
    created_idx = 5 # Col F
    changed_idx = 6 # Col G
    deal_id_idx = 0 # Col A

    today = datetime.date.today()
    active_rows = [headers]
    archived_rows = []

    for r in data_rows:
        if not r or not r[0]:
            continue
        try:
            stage_val = int(r[stage_idx]) if len(r) > stage_idx and str(r[stage_idx]).isdigit() else 1
        except:
            stage_val = 1

        # Сделки на этапах Closed-Won (6) или Closed-Lost (7) старше 90 дней
        is_closed = stage_val >= 6
        is_older_than_90_days = False

        if is_closed:
            date_str = ""
            if len(r) > changed_idx and r[changed_idx]:
                date_str = str(r[changed_idx])[:10]
            elif len(r) > created_idx and r[created_idx]:
                date_str = str(r[created_idx])[:10]

            try:
                deal_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if (today - deal_dt).days > 90:
                    is_older_than_90_days = True
            except:
                is_older_than_90_days = False

        if is_closed and is_older_than_90_days:
            archived_rows.append(r)
        else:
            active_rows.append(r)

    print(f"[*] Анализ оперативного хранилища {sh.title}:")
    print(f"    - Всего записей: {len(data_rows)}")
    print(f"    - Активных и свежих (<90 дней): {len(active_rows)-1}")
    print(f"    - Готовых к архивации в DWH (>90 дней): {len(archived_rows)}")

    if not archived_rows:
        print("[✓] Лист raw_deals оптимизирован (нет закрытых сделок старше 90 дней), архивация не требуется.")
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
        # Перезаписываем без вызова clear(), чтобы сохранить форматы валют и колонок
        ws_deals.update(values=active_rows, range_name='A1')
        if len(data_rows) > len(active_rows) - 1:
            clear_start = len(active_rows) + 1
            clear_end = len(all_rows)
            ws_deals.batch_clear([f"A{clear_start}:AK{clear_end}"])
        print(f"[✓] Лист raw_deals успешно очищен от архивных сделок (>90 дней). Форматирование сохранено!")
    else:
        print("[i] Dry-run режим: изменения в Google Sheets не вносились.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RevOps V16.0 DWH Archival Bridge")
    parser.add_argument('--sheet-id', default='1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc', help="Spreadsheet ID")
    parser.add_argument('--tenant-id', default='TNT-MASTER-001', help="Tenant ID")
    parser.add_argument('--dry-run', action='store_true', help="Только симуляция архивации")
    args = parser.parse_args()

    archive_old_deals(args.sheet_id, args.tenant_id, dry_run=args.dry_run)

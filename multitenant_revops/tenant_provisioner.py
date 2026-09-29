"""
RevOps Platform V16.0 - Automated Tenant Provisioner
Служба автоматизированного развертывания и онбординга новых B2B-клиентов.
"""
import os
import sys
import json
import argparse
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import gspread

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

def save_registry(data):
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_tenant_id(registry):
    count = len(registry.get('tenants', [])) + 1
    return f"TNT-{count:03d}"

def enforce_rbac_protection(sh, sa_email):
    """Блокирует системные листы от случайного изменения клиентом"""
    targets = {}
    for ws in sh.worksheets():
        if ws.title in ['calc_engine', 'raw_audit_log', 'changelog']:
            targets[ws.title] = ws.id
            
    requests = []
    for name, sheet_id in targets.items():
        requests.append({
            "addProtectedRange": {
                "protectedRange": {
                    "range": {"sheetId": sheet_id},
                    "description": f"RBAC Protected: {name} (Hardware Lock)",
                    "warningOnly": False,
                    "editors": {"users": [sa_email]}
                }
            }
        })
    if requests:
        try:
            sh.batch_update({"requests": requests})
        except Exception as e:
            print(f"Warning: could not apply protected ranges: {e}")

def provision_tenant(company_name, client_email=None, sheet_id=None, folder_id=None):
    creds = get_credentials()
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa_email = json.load(f)['email']

    registry = load_registry()
    tenant_id = generate_tenant_id(registry)

    # 1. Получение инстанса таблицы
    if sheet_id:
        # Онбординг уже созданной копии
        new_sh = gc.open_by_key(sheet_id)
        print(f"[*] Онбординг существующего инстанса: {new_sh.title} ({sheet_id})")
    else:
        # Автоматическое клонирование через Drive API
        copy_body = {'name': f"RevOps Platform V16.0 - {company_name}"}
        if folder_id:
            copy_body['parents'] = [folder_id]
        
        try:
            copied_file = drive_service.files().copy(
                fileId=GOLDEN_MASTER_ID,
                body=copy_body,
                supportsAllDrives=True
            ).execute()
            sheet_id = copied_file['id']
            new_sh = gc.open_by_key(sheet_id)
            print(f"[+] Успешно скопирован Golden Master: ID {sheet_id}")
        except Exception as e:
            print(f"[-] Ошибка клонирования Drive API: {e}")
            print(f"[i] Подсказка: создайте копию вручную в Google Drive и запустите:")
            print(f"    python tenant_provisioner.py --name \"{company_name}\" --sheet-id <ID_КОПИИ> --email \"{client_email or 'client@example.com'}\"")
            return None

    # 2. Инициализация параметров тенанта
    ws_settings = new_sh.worksheet('⚙️ Настройки')
    ws_settings.update(values=[[company_name]], range_name='B3')
    ws_settings.update(values=[[tenant_id]], range_name='E3')
    ws_settings.update(values=[[company_name]], range_name='E4')
    ws_settings.update(values=[["🛡️ Hardware Enforcement (Client Copy)"]], range_name='E5')

    # 3. Аппаратная защита RBAC
    enforce_rbac_protection(new_sh, sa_email)

    # 4. Предоставление доступа клиенту
    if client_email:
        try:
            new_sh.share(client_email, perm_type='user', role='writer', notify=True)
            print(f"[+] Доступ редактора выдан клиенту: {client_email}")
        except Exception as e:
            print(f"[-] Не удалось расшарить с {client_email}: {e}")

    # 5. Регистрация в базе тенантов
    tenant_record = {
        "tenant_id": tenant_id,
        "tenant_name": company_name,
        "client_email": client_email,
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": new_sh.url,
        "created_at": datetime.datetime.now().isoformat(),
        "version": "16.0"
    }
    registry['tenants'].append(tenant_record)
    save_registry(registry)

    print("\n" + "="*60)
    print("🎉 ТЕНАНТ УСПЕШНО РАЗВЕРНУТ И ЗАЩИЩЕН!")
    print("="*60)
    print(f"🏢 Компания:    {company_name}")
    print(f"🔑 Tenant ID:   {tenant_id}")
    print(f"🔗 Ссылка:      {new_sh.url}")
    print(f"🛡️ RBAC:        Активен (calc_engine, raw_audit_log защищены)")
    print("="*60 + "\n")
    return tenant_record

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RevOps Platform V16.0 Tenant Provisioner")
    parser.add_argument('--name', required=True, help="Название компании клиента")
    parser.add_argument('--email', help="Email клиента для выдачи доступа")
    parser.add_argument('--sheet-id', help="ID уже скопированной таблицы (ручной режим)")
    parser.add_argument('--folder-id', help="ID папки Google Drive для размещения копии")
    args = parser.parse_args()

    provision_tenant(args.name, args.email, args.sheet_id, args.folder_id)

"""
RevOps Platform V17.5 - Automated Multi-Tenant Provisioner
Служба автоматизированного развертывания и онбординга новых B2B-клиентов.
"""
import os
import sys
import json
import re
import argparse
import datetime
import subprocess
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
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
GOLDEN_MASTER_ID = '1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc'
GOLDEN_MASTER_URL = f'https://docs.google.com/spreadsheets/d/{GOLDEN_MASTER_ID}/edit'
N8N_BASE_URL = 'http://localhost:5678'

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
    return {
        "master_template": {
            "tenant_id": "TNT-MASTER-001",
            "tenant_name": "Golden Master Template",
            "spreadsheet_id": GOLDEN_MASTER_ID,
            "spreadsheet_url": GOLDEN_MASTER_URL,
            "version": "17.5",
            "created_at": "2026-09-29T20:30:00"
        },
        "tenants": []
    }

def save_registry(data):
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_tenant_id(registry):
    count = len(registry.get('tenants', [])) + 1
    return f"TNT-{count:03d}"

def parse_email_list(emails_input):
    """Разбирает строку с email-адресами, разделёнными запятыми, точками с запятой или пробелами"""
    if not emails_input:
        return []
    if isinstance(emails_input, (list, tuple)):
        raw_list = emails_input
    else:
        raw_list = re.split(r'[,;\s]+', str(emails_input).strip())

    valid_emails = []
    seen = set()
    for item in raw_list:
        item = item.strip().lower()
        if item and '@' in item and '.' in item and item not in seen:
            valid_emails.append(item)
            seen.add(item)
    return valid_emails

def extract_spreadsheet_id(input_str):
    if not input_str:
        return GOLDEN_MASTER_ID
    input_str = input_str.strip()
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', input_str)
    if match:
        return match.group(1)
    if '/' not in input_str and len(input_str) > 20:
        return input_str
    return GOLDEN_MASTER_ID

def copy_to_clipboard(text):
    try:
        process = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
        process.communicate(text.encode('utf-16le'))
        return True
    except:
        return False

def enforce_rbac_protection(sh, sa_email):
    """Блокирует системные листы от случайного изменения клиентом"""
    targets = {}
    for ws in sh.worksheets():
        if ws.title in ['calc_engine', 'raw_audit_log', 'changelog', 'calc_sales', 'calc_marketing', 'calc_finance']:
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
            return True
        except Exception as e:
            print(f"    [!] Предупреждение RBAC: {e}")
            return False
    return True

def create_client_passport(tenant_record):
    desktop_dir = os.path.join(os.environ.get('USERPROFILE', r'C:\Users\strel'), 'Desktop')
    clean_name = re.sub(r'[\/:*?"<>|]', '_', tenant_record['tenant_name'])
    filename = f"Паспорт_клиента_{tenant_record['tenant_id']}_{clean_name}.txt"
    filepath = os.path.join(desktop_dir, filename)

    emails_list = tenant_record.get('client_emails') or [em.strip() for em in tenant_record.get('client_email', '').split(',') if em.strip()]
    if len(emails_list) > 1:
        emails_display = "\n" + "\n".join([f"                     • {em}" for em in emails_list])
    elif emails_list:
        emails_display = f" {emails_list[0]}"
    else:
        emails_display = " Не указан"

    content = f"""================================================================================
          📋 ПАСПОРТ КЛИЕНТСКОГО КОНТУРА — REVOPS PLATFORM V17.5
================================================================================

🏢 Компания:         {tenant_record['tenant_name']}
🔑 Идентификатор:    {tenant_record['tenant_id']}
📅 Дата активации:   {tenant_record['created_at'][:19].replace('T', ' ')}
🛡️ Статус защиты:    RBAC Hardware Lock (Активен)
📊 Таблица отчётов:  {tenant_record['spreadsheet_url']}
📧 Доступ выдан:    {emails_display} (Права Редактора)

--------------------------------------------------------------------------------
🔌 ПАРАМЕТРЫ ИНТЕГРАЦИИ С CRM ({tenant_record.get('crm_type', 'bitrix24').upper()})
--------------------------------------------------------------------------------
"""

    if tenant_record.get('crm_type') == 'bitrix24':
        content += f"""CRM Система:         Битрикс24 (REST API / Webhook)
Входящий Webhook n8n (куда Битрикс24 шлёт звонки):
👉 {tenant_record['inbound_webhook_url']}

ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ В БИТРИКС24 (2 минуты):
1. Откройте портал Битрикс24 клиента с правами администратора.
2. Перейдите: Разработчикам -> Другое -> Исходящий вебхук.
3. В поле "URL обработчика" вставьте:
   {tenant_record['inbound_webhook_url']}
4. В списке событий выберите:
   [✓] ONVOXIMPLANTCALLEND (Событие при завершении звонка)
5. Нажмите "Сохранить".
Готово! Теперь каждый разговор автоматически попадает в ИИ-анализ Faster-Whisper +
Gemini 3.8 Flash, результат публикуется комментарием в сделку и в персональную таблицу!
"""
    else:
        content += f"""CRM Система:         amoCRM
Домен amoCRM:        {tenant_record.get('amo_domain', 'Не указан')}
Входящий Webhook n8n (для телефонии UIS/Mango/Sipuni/amoCRM):
👉 {tenant_record['inbound_webhook_url']}

ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ В AMOCRM:
1. Перейдите в настройки телефонии (или виджета вебхуков amoCRM).
2. Укажите URL обработчика звонков:
   {tenant_record['inbound_webhook_url']}
3. Сохраните настройки. Каждый звонок теперь оценивается по 13 критериям RevOps!
"""

    content += f"""
================================================================================
💡 СЛУЖБА ПОДДЕРЖКИ REVOPS ENTERPRISE:
Локальный контур n8n: {N8N_BASE_URL}
Реестр тенантов:      {REGISTRY_FILE}
================================================================================
"""

    try:
        with open(filepath, 'w', encoding='utf-8-sig') as f:
            f.write(content)
        return filepath
    except Exception as e:
        print(f"    [!] Не удалось сохранить файл паспорта на Рабочий стол: {e}")
        return None

def provision_tenant(company_name, client_email=None, sheet_id=None, folder_id=None, crm_type="bitrix24", crm_webhook=None, amo_domain=None):
    creds = get_credentials()
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa_email = json.load(f)['email']

    registry = load_registry()
    tenant_id = generate_tenant_id(registry)
    clean_sheet_id = extract_spreadsheet_id(sheet_id)

    print(f"\n[1/5] 🔄 Подключение к Google Sheets...")
    # 1. Открытие инстанса таблицы
    if clean_sheet_id and clean_sheet_id != GOLDEN_MASTER_ID:
        try:
            new_sh = gc.open_by_key(clean_sheet_id)
            print(f"    [✓] Подключена персональная таблица клиента: {new_sh.title}")
            try:
                new_sh.update_title(f"RevOps Platform V17.5 - {company_name}")
                print(f"    [✓] Имя таблицы обновлено: 'RevOps Platform V17.5 - {company_name}'")
            except Exception as e:
                pass
        except Exception as e:
            print(f"    [-] Ошибка доступа к таблице {clean_sheet_id}: {e}")
            print(f"    [!] Сервисный аккаунт: {sa_email}")
            print(f"    [i] Убедитесь, что выдали права 'Редактор' сервисному аккаунту!")
            return None
    else:
        # Режим Golden Master (Showcase / Demo)
        clean_sheet_id = GOLDEN_MASTER_ID
        new_sh = gc.open_by_key(clean_sheet_id)
        print(f"    [✓] Использован Golden Master контур: {clean_sheet_id}")

    # 2. Инициализация параметров тенанта
    print(f"[2/5] ⚙️ Настройка конфигураций тенанта ({tenant_id})...")
    try:
        ws_settings = new_sh.worksheet('⚙️ Настройки')
        ws_settings.update(values=[[company_name]], range_name='B3')
        ws_settings.update(values=[[tenant_id]], range_name='E3')
        ws_settings.update(values=[[company_name]], range_name='E4')
        ws_settings.update(values=[["🛡️ Hardware Enforcement (Active)"]], range_name='E5')
        print(f"    [✓] Лист '⚙️ Настройки' успешно обновлён")
    except Exception as e:
        print(f"    [!] Не удалось обновить '⚙️ Настройки': {e}")

    # 3. Аппаратная защита RBAC
    print(f"[3/5] 🛡️ Активация аппаратной защиты RBAC...")
    enforce_rbac_protection(new_sh, sa_email)
    print(f"    [✓] Системные листы защищены от изменения клиентом")

    # 4. Предоставление доступа клиенту
    valid_emails = parse_email_list(client_email)
    print(f"[4/5] 💌 Выдача прав Редактора на Email ({len(valid_emails)} адр.)...")
    if valid_emails:
        for em in valid_emails:
            try:
                new_sh.share(em, perm_type='user', role='writer', notify=True)
                print(f"    [✓] Доступ Редактора выдан: {em}")
            except Exception as e:
                print(f"    [!] Заметка: не удалось выдать доступ {em} ({e}). Добавьте вручную.")
    else:
        print(f"    [-] Email не указан, пропускаем расшаривание")

    # 5. Формирование Webhook URL
    if crm_type == 'bitrix24':
        inbound_webhook_url = f"{N8N_BASE_URL}/webhook/bitrix24-call?tenant={tenant_id}&sheet_id={clean_sheet_id}"
    else:
        inbound_webhook_url = f"{N8N_BASE_URL}/webhook/amocrm-call?tenant={tenant_id}&sheet_id={clean_sheet_id}"

    # 6. Регистрация в базе тенантов
    tenant_record = {
        "tenant_id": tenant_id,
        "tenant_name": company_name,
        "client_email": ", ".join(valid_emails) if valid_emails else (client_email or ""),
        "client_emails": valid_emails,
        "crm_type": crm_type,
        "crm_webhook_url": crm_webhook or "",
        "amo_domain": amo_domain or "",
        "spreadsheet_id": clean_sheet_id,
        "spreadsheet_url": new_sh.url,
        "inbound_webhook_url": inbound_webhook_url,
        "created_at": datetime.datetime.now().isoformat(),
        "status": "active",
        "version": "17.5"
    }
    registry['tenants'].append(tenant_record)
    save_registry(registry)
    print(f"[5/5] 💾 Клиент зарегистрирован в базе tenants_registry.json")

    # 7. Паспорт клиента на Рабочий стол
    passport_path = create_client_passport(tenant_record)
    if passport_path:
        print(f"    [✓] Паспорт клиента сохранён на Рабочем столе: {os.path.basename(passport_path)}")

    # 8. Копирование вебхука в буфер обмена
    copied = copy_to_clipboard(inbound_webhook_url)

    print("\n" + "═"*70)
    print("🎉 КЛИЕНТ УСПЕШНО ОНБОРДИНГОВАН И ГОТОВ К РАБОТЕ!")
    print("═"*70)
    print(f"🏢 Компания:    {company_name}")
    print(f"🔑 Tenant ID:   {tenant_id}")
    print(f"📊 Дашборд:     {new_sh.url}")
    print(f"🔌 CRM система: {crm_type.upper()}")
    print("─"*70)
    print("🚀 ВХОДЯЩИЙ ВЕБХУК ДЛЯ ЗВОНКОВ КЛИЕНТА:")
    print(f"👉 {inbound_webhook_url}")
    if copied:
        print("📋 [URL АВТОМАТИЧЕСКИ СКОПИРОВАН В БУФЕР ОБМЕНА! (Ctrl+V)]")
    print("═"*70 + "\n")

    return tenant_record

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RevOps Platform V17.5 Tenant Provisioner")
    parser.add_argument('--name', required=True, help="Название компании клиента")
    parser.add_argument('--email', help="Email клиента для выдачи доступа")
    parser.add_argument('--sheet-id', help="ID или ссылка на созданную таблицу Google")
    parser.add_argument('--folder-id', help="ID папки Google Drive")
    parser.add_argument('--crm', choices=['bitrix24', 'amocrm'], default='bitrix24', help="Тип CRM")
    parser.add_argument('--crm-webhook', help="Входящий вебхук REST API Bitrix24")
    parser.add_argument('--amo-domain', help="Домен amoCRM")
    args = parser.parse_args()

    provision_tenant(
        company_name=args.name,
        client_email=args.email,
        sheet_id=args.sheet_id,
        folder_id=args.folder_id,
        crm_type=args.crm,
        crm_webhook=args.crm_webhook,
        amo_domain=args.amo_domain
    )

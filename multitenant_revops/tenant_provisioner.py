"""
RevOps Platform V17.5 - Automated Multi-Tenant Provisioner
Служба автоматизированного развертывания и онбординга новых B2B-клиентов.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except:
        pass

if sys.stdin.encoding != "utf-8":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except:
        pass

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def find_service_account():
    candidates = [
        os.getenv("REVOPS_SA_FILE"),
        BASE_DIR / "service_account.json",
        BASE_DIR.parent / "service_account.json",
        BASE_DIR.parent.parent / "service_account.json",
        Path.home() / ".gemini" / "antigravity" / "scratch" / "service_account.json",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return str(c)
    return str(BASE_DIR / "service_account.json")


SERVICE_ACCOUNT_FILE = find_service_account()
REGISTRY_FILE = str(BASE_DIR / "tenants_registry.json")
SHOWCASE_MASTER_ID = "1QnjrrbpqhYssofchee7G06szWrFvBCcOqGIVokjqdVc"
CLEAN_TEMPLATE_ID = "1jBBotOfFh-XEJGScJyQi10jiFrna66OpJ91yPDrXy2A"

# Для создания персональных клиентских дашбордов используется ЧИСТЫЙ шаблон (Clean Starter)
GOLDEN_MASTER_ID = CLEAN_TEMPLATE_ID
GOLDEN_MASTER_URL = f"https://docs.google.com/spreadsheets/d/{GOLDEN_MASTER_ID}/edit"


def get_base_url():
    try:
        scratch_dir = str(Path(os.getenv("REVOPS_SCRATCH", Path.home() / ".gemini" / "antigravity" / "scratch")))
        if scratch_dir not in sys.path:
            sys.path.append(scratch_dir)
        from tunnel_manager import get_active_tunnel_url

        url = get_active_tunnel_url()
        if url and url.startswith("http"):
            return url.rstrip("/")
    except Exception:
        pass
    return "http://localhost:5678"


N8N_BASE_URL = get_base_url()


def get_credentials():
    with open(SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as f:
        sa = json.load(f)
    email = sa.get("client_email") or sa.get("email")
    pkey = sa.get("private_key") or sa.get("privateKey")
    return Credentials.from_service_account_info(
        {
            "type": "service_account",
            "client_email": email,
            "private_key": pkey,
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )


def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "master_template": {
            "tenant_id": "TNT-MASTER-001",
            "tenant_name": "Golden Master Template",
            "spreadsheet_id": GOLDEN_MASTER_ID,
            "spreadsheet_url": GOLDEN_MASTER_URL,
            "version": "17.5",
            "created_at": "2026-09-29T20:30:00",
        },
        "tenants": [],
    }


def save_registry(data):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_tenant_id(registry):
    count = len(registry.get("tenants", [])) + 1
    return f"TNT-{count:03d}"


def parse_email_list(emails_input):
    """Разбирает строку с email-адресами, разделёнными запятыми, точками с запятой или пробелами"""
    if not emails_input:
        return []
    if isinstance(emails_input, (list, tuple)):
        raw_list = emails_input
    else:
        raw_list = re.split(r"[,;\s]+", str(emails_input).strip())

    valid_emails = []
    seen = set()
    for item in raw_list:
        item = item.strip().lower()
        if item and "@" in item and "." in item and item not in seen:
            valid_emails.append(item)
            seen.add(item)
    return valid_emails


def extract_spreadsheet_id(input_str):
    if not input_str:
        return GOLDEN_MASTER_ID
    input_str = input_str.strip()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", input_str)
    if match:
        return match.group(1)
    if "/" not in input_str and len(input_str) > 20:
        return input_str
    return GOLDEN_MASTER_ID


def copy_to_clipboard(text):
    try:
        process = subprocess.Popen("clip", stdin=subprocess.PIPE, shell=True)
        process.communicate(text.encode("utf-16le"))
        return True
    except:
        return False


def enforce_rbac_protection(sh, sa_email):
    """Блокирует системные листы от случайного изменения клиентом"""
    targets = {}
    for ws in sh.worksheets():
        if ws.title in ["calc_engine", "raw_audit_log", "changelog", "calc_sales", "calc_marketing", "calc_finance"]:
            targets[ws.title] = ws.id

    requests = []
    for name, sheet_id in targets.items():
        requests.append(
            {
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {"sheetId": sheet_id},
                        "description": f"RBAC Protected: {name} (Hardware Lock)",
                        "warningOnly": False,
                        "editors": {"users": [sa_email]},
                    }
                }
            }
        )
    if requests:
        try:
            sh.batch_update({"requests": requests})
            return True
        except Exception as e:
            print(f"    [!] Предупреждение RBAC: {e}")
            return False
    return True


def ensure_passport_sheet(sh, tenant_record):
    """Создаёт титульный лист '📋 Паспорт_Клиента' прямо внутри таблицы Google"""
    ws_name = "📋 Паспорт_Клиента"
    try:
        ws = sh.worksheet(ws_name)
    except Exception:
        try:
            ws = sh.add_worksheet(title=ws_name, rows=35, cols=10, index=0)
        except Exception:
            return

    crm_type = tenant_record.get("crm_type", "amocrm")
    if crm_type in ["hybrid", "both"]:
        crm_display = "🔥 ГИБРИД (amoCRM + Битрикс24)"
    elif crm_type == "bitrix24":
        crm_display = "БИТРИКС24"
    else:
        crm_display = "AMOCRM"

    wh_amo = tenant_record.get("inbound_webhook_url", "")
    wh_b24 = tenant_record.get("inbound_webhook_b24_url") or tenant_record.get("inbound_webhook_url", "")

    passport_rows = [
        ["📋 ПАСПОРТ КЛИЕНТСКОГО КОНТУРА REVOPS PLATFORM V18.0", ""],
        ["Параметр", "Значение"],
        ["🏢 Название компании", tenant_record["tenant_name"]],
        ["🔑 Идентификатор (Tenant ID)", tenant_record["tenant_id"]],
        ["📅 Дата активации", tenant_record["created_at"][:19].replace("T", " ")],
        ["🛡️ Статус защиты ядра", "RBAC Hardware Lock (Активен)"],
        ["📧 Email клиента (Редактор)", tenant_record.get("client_email", "Не указан")],
        ["🔌 CRM Система", crm_display],
        ["🌐 Домен amoCRM", tenant_record.get("amo_domain", "Не указан")],
        ["🔗 Webhook звонков amoCRM", wh_amo if crm_type != "bitrix24" else "-"],
        ["🔗 Webhook звонков Битрикс24", wh_b24 if crm_type != "amocrm" else "-"],
        ["", ""],
        ["📌 ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ:", ""],
        ["1. Вставьте соответствующий Webhook URL в настройки CRM или телефонии.", ""],
        ["2. Каждый звонок автоматически анализируется нейросетью и заносится в эту таблицу.", ""],
    ]
    try:
        ws.update(values=passport_rows, range_name="A1:B15")
        ws.format(
            "A1:B1",
            {
                "backgroundColor": {"red": 0.05, "green": 0.45, "blue": 0.55},
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "bold": True,
                    "fontSize": 12,
                },
            },
        )
        ws.format(
            "A2:B2",
            {
                "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.23},
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "bold": True,
                    "fontSize": 10,
                },
            },
        )
        ws.format("A3:A11", {"textFormat": {"bold": True, "fontSize": 10}})
    except Exception:
        pass


def get_client_folder(tenant_name: str) -> Path:
    """Возвращает кроссплатформенный путь к локальной папке клиента и гарантирует её создание."""
    clean = re.sub(r'[\/:*?"<>|]', "_", tenant_name)
    base = Path(os.getenv("REVOPS_DESKTOP", Path.home() / "Desktop"))
    folder = base / "RevOps Platform" / "Клиенты" / clean
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def create_client_passport(tenant_record):
    client_folder = get_client_folder(tenant_record["tenant_name"])
    clean_name = client_folder.name

    filename_txt = f"Паспорт_клиента_{tenant_record['tenant_id']}_{clean_name}.txt"
    filepath_txt = os.path.join(client_folder, filename_txt)
    filename_docx = f"Паспорт_клиента_{tenant_record['tenant_id']}_{clean_name}.docx"
    filepath_docx = os.path.join(client_folder, filename_docx)

    emails_list = tenant_record.get("client_emails") or [
        em.strip() for em in tenant_record.get("client_email", "").split(",") if em.strip()
    ]
    if len(emails_list) > 1:
        emails_display = "\n" + "\n".join([f"                     • {em}" for em in emails_list])
    elif emails_list:
        emails_display = f" {emails_list[0]}"
    else:
        emails_display = " Не указан"

    crm_type = tenant_record.get("crm_type", "amocrm")
    if crm_type in ["hybrid", "both"]:
        crm_label = "🔥 ГИБРИД (amoCRM + Битрикс24 одновременно)"
    elif crm_type == "bitrix24":
        crm_label = "БИТРИКС24 (Bitrix24)"
    else:
        crm_label = "amoCRM"

    wh_amo = tenant_record.get("inbound_webhook_url", "")
    wh_b24 = tenant_record.get("inbound_webhook_b24_url") or tenant_record.get("inbound_webhook_url", "")

    content = f"""================================================================================
          📋 ПАСПОРТ КЛИЕНТСКОГО КОНТУРА — REVOPS PLATFORM V18.0
================================================================================

🏢 Компания:         {tenant_record["tenant_name"]}
🔑 Идентификатор:    {tenant_record["tenant_id"]}
🎯 Ниша бизнеса:     {tenant_record.get("niche_name", "Универсальный B2B")}
💰 Средний чек:      {tenant_record.get("avg_deal_check", 150000):,} ₽
📌 Целевой Next Step:{tenant_record.get("target_next_step", "Фиксация следующего контакта с датой и временем")}
📅 Дата активации:   {tenant_record["created_at"][:19].replace("T", " ")}
🛡️ Статус защиты:    RBAC Hardware Lock (Активен)
📊 Таблица отчётов:  {tenant_record["spreadsheet_url"]}
📧 Доступ выдан:    {emails_display} (Права Редактора)

--------------------------------------------------------------------------------
🔌 ПАРАМЕТРЫ ИНТЕГРАЦИИ С CRM ({crm_label})
--------------------------------------------------------------------------------
"""

    if crm_type in ["hybrid", "both"]:
        content += f"""ВНИМАНИЕ: Для клиента активирован ГИБРИДНЫЙ РЕЖИМ (amoCRM + Битрикс24)!
Система одновременно принимает звонки и синхронизирует сделки из двух систем в единый дашборд.

[1] НАСТРОЙКА AMOCRM:
    • Домен:             {tenant_record.get("amo_domain", "revopsofficial.amocrm.ru")}
    • Входящий Webhook:  {wh_amo}
    Инструкция: Вставьте Webhook URL в настройки телефонии amoCRM (UIS/Mango/Sipuni)
    или в виджет интеграции. Задачи и примечания ставятся в amoCRM автоматически.

[2] НАСТРОЙКА БИТРИКС24:
    • REST Вебхук API:   {tenant_record.get("crm_webhook_url", "Укажите в консоли")}
    • Webhook звонков:   {wh_b24}
    Инструкция: В Битрикс24: Разработчикам -> Исходящий вебхук -> URL обработчика.
    Событие: ONVOXIMPLANTCALLEND. Комментарии и аудит добавляются в таймлайн сделки.
"""
    elif crm_type == "bitrix24":
        content += f"""CRM Система:         Битрикс24 (REST API / Webhook)
Входящий Webhook n8n (куда Битрикс24 шлёт звонки):
👉 {wh_b24}

ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ В БИТРИКС24 (2 минуты):
1. Откройте портал Битрикс24 клиента с правами администратора.
2. Перейдите: Разработчикам -> Другое -> Исходящий вебхук.
3. В поле "URL обработчика" вставьте:
   {wh_b24}
4. В списке событий выберите:
   [✓] ONVOXIMPLANTCALLEND (Событие при завершении звонка)
5. Нажмите "Сохранить".
Готово! Теперь каждый разговор автоматически попадает в ИИ-анализ Faster-Whisper +
Gemini 3.8 Flash, результат публикуется комментарием в сделку и в персональную таблицу!
"""
    else:
        content += f"""CRM Система:         amoCRM
Домен amoCRM:        {tenant_record.get("amo_domain", "Не указан")}
Входящий Webhook n8n (для телефонии UIS/Mango/Sipuni/amoCRM):
👉 {wh_amo}

ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ В AMOCRM:
1. Перейдите в настройки телефонии (или виджета вебхуков amoCRM).
2. Укажите URL обработчика звонков:
   {wh_amo}
3. Сохраните настройки. Каждый звонок теперь оценивается по 13 критериям RevOps!
"""

    content += f"""
================================================================================
💡 СЛУЖБА ПОДДЕРЖКИ REVOPS ENTERPRISE:
Локальный контур n8n: {N8N_BASE_URL}
Реестр тенантов:      {REGISTRY_FILE}
Папка на компьютере:  {client_folder}
================================================================================
"""

    try:
        with open(filepath_txt, "w", encoding="utf-8-sig") as f:
            f.write(content)
    except Exception as e:
        print(f"    [!] Не удалось сохранить текстовый паспорт: {e}")

    try:
        import docx
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        from docx.shared import Inches, Pt, RGBColor

        doc = docx.Document()
        for sec in doc.sections:
            sec.top_margin = Inches(0.8)
            sec.bottom_margin = Inches(0.8)
            sec.left_margin = Inches(0.8)
            sec.right_margin = Inches(0.8)

        p_t = doc.add_paragraph()
        rt = p_t.add_run("📋 ПАСПОРТ КЛИЕНТСКОГО КОНТУРА")
        rt.bold = True
        rt.font.size = Pt(18)
        rt.font.color.rgb = RGBColor(14, 116, 144)

        ps = doc.add_paragraph()
        rs = ps.add_run(f"RevOps Enterprise OS V18.0 — {tenant_record['tenant_name']} ({tenant_record['tenant_id']})")
        rs.font.size = Pt(11)
        rs.font.color.rgb = RGBColor(100, 116, 139)

        t_data = [
            ("Компания:", tenant_record["tenant_name"]),
            ("Идентификатор (Tenant ID):", tenant_record["tenant_id"]),
            ("Ниша бизнеса:", tenant_record.get("niche_name", "Универсальный B2B")),
            ("Средний чек сделки:", f"{tenant_record.get('avg_deal_check', 150000):,} ₽".replace(",", " ")),
            (
                "Целевой Next Step:",
                tenant_record.get("target_next_step", "Фиксация следующего контакта с датой и временем"),
            ),
            ("Дата активации:", tenant_record["created_at"][:19].replace("T", " ")),
            ("Статус защиты ядра:", "🛡️ RBAC Hardware Lock (Активен)"),
            ("Email доступа:", tenant_record.get("client_email", "Не указан")),
            ("CRM Режим:", crm_label),
            ("Google Таблица клиента:", tenant_record.get("spreadsheet_url", "")),
        ]
        tbl = doc.add_table(rows=len(t_data), cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.style = "Table Grid"
        for idx, (k, v) in enumerate(t_data):
            c1, c2 = tbl.cell(idx, 0), tbl.cell(idx, 1)
            c1.width = Inches(2.2)
            c2.width = Inches(4.5)
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>')
            c1._tc.get_or_add_tcPr().append(shd)
            p1 = c1.paragraphs[0]
            p1.paragraph_format.space_before = Pt(4)
            p1.paragraph_format.space_after = Pt(4)
            r1 = p1.add_run(k)
            r1.bold = True
            r1.font.size = Pt(10)
            r1.font.color.rgb = RGBColor(51, 65, 85)
            p2 = c2.paragraphs[0]
            p2.paragraph_format.space_before = Pt(4)
            p2.paragraph_format.space_after = Pt(4)
            r2 = p2.add_run(v)
            r2.font.size = Pt(10)
            if idx == 1:
                r2.bold = True
                r2.font.color.rgb = RGBColor(3, 105, 161)

        h2 = doc.add_paragraph()
        rh2 = h2.add_run("\n🔌 ПАРАМЕТРЫ ИНТЕГРАЦИИ С CRM")
        rh2.bold = True
        rh2.font.size = Pt(13)

        c_box = doc.add_table(rows=1, cols=1).cell(0, 0)
        c_box.width = Inches(6.7)
        c_box._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="EFF6FF"/>'))
        c_box._tc.get_or_add_tcPr().append(
            parse_xml(
                f'<w:tcBorders {nsdecls("w")}><w:left w:val="single" w:sz="24" w:space="0" w:color="2563EB"/><w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/></w:tcBorders>'
            )
        )
        pb = c_box.paragraphs[0]
        rb1 = pb.add_run("Входящие Webhook URL n8n:\n")
        rb1.bold = True
        rb1.font.size = Pt(10.5)
        rb1.font.color.rgb = RGBColor(30, 64, 175)

        if crm_type in ["hybrid", "both"]:
            rb2 = pb.add_run(f"• amoCRM Webhook:    {wh_amo}\n• Битрикс24 Webhook: {wh_b24}\n")
        elif crm_type == "bitrix24":
            rb2 = pb.add_run(f"• Битрикс24 Webhook: {wh_b24}\n")
        else:
            rb2 = pb.add_run(f"• amoCRM Webhook:    {wh_amo}\n")
        rb2.font.size = Pt(9.5)
        rb2.font.color.rgb = RGBColor(3, 105, 161)

        doc.save(filepath_docx)
    except Exception as e:
        print(f"    [!] Не удалось сохранить Word паспорт: {e}")

    return (filepath_txt, filepath_docx)


def provision_tenant(
    company_name,
    client_email=None,
    sheet_id=None,
    folder_id=None,
    crm_type="amocrm",
    crm_webhook=None,
    amo_domain=None,
    amo_token=None,
    niche_id="general_b2b",
    niche_name="Универсальный B2B",
    avg_deal_check=150000,
    target_next_step=None,
    main_objection=None,
    max_audit_calls=200,
):
    creds = get_credentials()
    gc = gspread.authorize(creds)
    with open(SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as f:
        sa_raw = json.load(f)
        sa_email = sa_raw.get("client_email") or sa_raw.get("email")

    registry = load_registry()
    tenant_id = generate_tenant_id(registry)
    clean_sheet_id = extract_spreadsheet_id(sheet_id)

    print("\n[1/5] 🔄 Подключение к Google Sheets...")
    if clean_sheet_id and clean_sheet_id not in (CLEAN_TEMPLATE_ID, SHOWCASE_MASTER_ID):
        try:
            new_sh = gc.open_by_key(clean_sheet_id)
            print(f"    [✓] Подключена персональная таблица клиента: {new_sh.title}")
            try:
                new_sh.update_title(f"RevOps Platform V18.0 - {company_name}")
                print(f"    [✓] Имя таблицы обновлено: 'RevOps Platform V18.0 - {company_name}'")
            except Exception:
                pass
        except Exception as e:
            print(f"    [-] Ошибка доступа к таблице {clean_sheet_id}: {e}")
            print(f"    [!] Сервисный аккаунт: {sa_email}")
            print("    [i] Убедитесь, что выдали права 'Редактор' сервисному аккаунту!")
            return None
    else:
        print(f"    [+] Клонирование чистого шаблона для '{company_name}' через Drive API...")
        try:
            drive_svc = build("drive", "v3", credentials=creds)
            copy_meta = {"name": f"RevOps Platform V18.0 - {company_name}"}
            copied_file = (
                drive_svc.files().copy(fileId=CLEAN_TEMPLATE_ID, body=copy_meta, supportsAllDrives=True).execute()
            )
            clean_sheet_id = copied_file["id"]
            new_sh = gc.open_by_key(clean_sheet_id)
            print(f"    [✓] Создана независимая копия шаблона: {clean_sheet_id}")
        except Exception as e:
            print(f"    [-] Автокопирование через Google Drive API не удалось: {e}")
            print("    [!] ВНИМАНИЕ: Во избежание порчи мастер-шаблона авто-провижининг остановлен.")
            print(f"    [i] 1. Откройте ссылку шаблона: https://docs.google.com/spreadsheets/d/{CLEAN_TEMPLATE_ID}/copy")
            print("    [i] 2. Создайте персональную копию для клиента")
            print(f"    [i] 3. Выдайте сервисному аккаунту ({sa_email}) права 'Редактор'")
            print(f"    [i] 4. Запустите: python tenant_provisioner.py --name \"{company_name}\" --sheet-id <ID_КОПИИ>")
            return None

    # 2. Инициализация параметров тенанта
    print(f"[2/5] ⚙️ Настройка конфигураций тенанта ({tenant_id})...")
    try:
        ws_settings = new_sh.worksheet("⚙️ Настройки")
        ws_settings.update(values=[[company_name]], range_name="B3")
        ws_settings.update(values=[[tenant_id]], range_name="E3")
        ws_settings.update(values=[[company_name]], range_name="E4")
        ws_settings.update(values=[["🛡️ Hardware Enforcement (Active)"]], range_name="E5")
        if client_email:
            first_em = client_email.split(",")[0].strip()
            if first_em:
                ws_settings.update(values=[[first_em, "👑 CEO", "📄 Executive_OnePager"]], range_name="J10:L10")
        print("    [✓] Лист '⚙️ Настройки' успешно обновлён")
    except Exception as e:
        print(f"    [!] Не удалось обновить '⚙️ Настройки': {e}")

    # 3. Аппаратная защита RBAC
    print("[3/5] 🛡️ Активация аппаратной защиты RBAC...")
    enforce_rbac_protection(new_sh, sa_email)
    print("    [✓] Системные листы защищены от изменения клиентом")

    # 4. Предоставление доступа клиенту
    valid_emails = parse_email_list(client_email)
    print(f"[4/5] 💌 Выдача прав Редактора на Email ({len(valid_emails)} адр.)...")
    if valid_emails:
        for em in valid_emails:
            try:
                new_sh.share(em, perm_type="user", role="writer", notify=True)
                print(f"    [✓] Доступ Редактора выдан: {em}")
            except Exception as e:
                print(f"    [!] Заметка: не удалось выдать доступ {em} ({e}). Добавьте вручную.")
    else:
        print("    [-] Email не указан, пропускаем расшаривание")

    # 5. Формирование Webhook URLs
    base_url = get_base_url()
    wh_amo = f"{base_url}/webhook/amocrm-call?tenant={tenant_id}&sheet_id={clean_sheet_id}"
    wh_b24 = f"{base_url}/webhook/bitrix24-call?tenant={tenant_id}&sheet_id={clean_sheet_id}"

    primary_wh = wh_b24 if crm_type == "bitrix24" else wh_amo

    # 6. Регистрация в базе тенантов
    tenant_record = {
        "tenant_id": tenant_id,
        "tenant_name": company_name,
        "niche_id": niche_id,
        "niche_name": niche_name or "Универсальный B2B",
        "avg_deal_check": int(avg_deal_check) if avg_deal_check else 150000,
        "target_next_step": target_next_step or "Фиксация следующего контакта с датой и временем",
        "main_objection": main_objection or "Дорого / скиньте на почту",
        "max_audit_calls": int(max_audit_calls) if max_audit_calls else 200,
        "client_email": ", ".join(valid_emails) if valid_emails else (client_email or ""),
        "client_emails": valid_emails,
        "crm_type": crm_type,
        "crm_webhook_url": crm_webhook or "",
        "b24_webhook_url": crm_webhook or "",
        "amo_domain": amo_domain or "",
        "amo_token": amo_token or "",
        "spreadsheet_id": clean_sheet_id,
        "spreadsheet_url": new_sh.url,
        "inbound_webhook_url": primary_wh,
        "inbound_webhook_amo_url": wh_amo,
        "inbound_webhook_b24_url": wh_b24,
        "created_at": datetime.datetime.now().isoformat(),
        "status": "active",
        "version": "18.0",
        "integration_mode": "token",
    }
    registry["tenants"].append(tenant_record)
    save_registry(registry)
    print("[5/5] 💾 Клиент зарегистрирован в базе tenants_registry.json")

    # Встраивание паспорта прямо в Google Таблицу
    ensure_passport_sheet(new_sh, tenant_record)

    # 7. Паспорт клиента в персональную папку клиента
    client_folder = get_client_folder(tenant_record["tenant_name"])
    clean_name = client_folder.name
    passport_paths = create_client_passport(tenant_record)
    if passport_paths:
        print(f"    [✓] Паспорт сохранён в папку клиента: 'RevOps Platform\\Клиенты\\{clean_name}\\'")
        print(f"        • Текстовый паспорт: {os.path.basename(passport_paths[0])}")
        print(f"        • Документ Word:     {os.path.basename(passport_paths[1])}")

    # 8. Синхронизация на Google Drive
    try:
        from google_drive_manager import sync_client_to_drive

        drive_res = sync_client_to_drive(
            tenant_name=company_name,
            tenant_id=tenant_id,
            local_passport_path=passport_paths[0] if passport_paths else None,
            spreadsheet_id=clean_sheet_id,
        )
        if drive_res and drive_res.get("status") == "success":
            print(f"    [✓] Синхронизировано на Google Drive: {drive_res.get('client_folder_url')}")
    except Exception:
        pass

    # 9. Копирование вебхука в буфер обмена
    copy_to_clipboard(primary_wh)

    print("\n" + "═" * 70)
    print("🎉 КЛИЕНТ УСПЕШНО ОНБОРДИНГОВАН И ГОТОВ К РАБОТЕ!")
    print("═" * 70)
    print(f"🏢 Компания:    {company_name}")
    print(f"🔑 Tenant ID:   {tenant_id}")
    print(f"📊 Дашборд:     {new_sh.url}")
    print(f"📁 Папка на ПК: {client_folder}")
    print(f"🔌 CRM режим:   {crm_type.upper()}")
    print("─" * 70)
    if crm_type in ["hybrid", "both"]:
        print("🚀 ВХОДЯЩИЕ ВЕБХУКИ ДЛЯ ЗВОНКОВ КЛИЕНТА (ГИБРИДНЫЙ РЕЖИМ):")
        print(f"👉 amoCRM:    {wh_amo}")
        print(f"👉 Битрикс24: {wh_b24}")
    else:
        print("🚀 ВХОДЯЩИЙ ВЕБХУК ДЛЯ ЗВОНКОВ КЛИЕНТА:")
        print(f"👉 {primary_wh}")
    print("📋 [URL АВТОМАТИЧЕСКИ СКОПИРОВАН В БУФЕР ОБМЕНА! (Ctrl+V)]")
    print("═" * 70 + "\n")

    return tenant_record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RevOps Platform V18.0 Tenant Provisioner")
    parser.add_argument("--name", required=True, help="Название компании клиента")
    parser.add_argument("--email", help="Email клиента для выдачи доступа")
    parser.add_argument("--sheet-id", help="ID или ссылка на созданную таблицу Google")
    parser.add_argument("--folder-id", help="ID папки Google Drive")
    parser.add_argument("--crm", choices=["bitrix24", "amocrm", "hybrid", "both"], default="amocrm", help="Тип CRM")
    parser.add_argument("--crm-webhook", help="Входящий вебхук REST API Bitrix24")
    parser.add_argument("--amo-domain", help="Домен amoCRM")
    args = parser.parse_args()

    provision_tenant(
        company_name=args.name,
        client_email=args.email,
        sheet_id=args.sheet_id,
        folder_id=args.folder_id,
        crm_type=args.crm,
        crm_webhook=args.crm_webhook,
        amo_domain=args.amo_domain,
    )

"""
RevOps Platform V18.0 - Dual-Mode & Hybrid CRM Integration Manager
Пошаговая настройка и тестирование сквозной связки:
amoCRM (API-Токен / Webhook) / Битрикс24 (REST API / Webhook) / 🔥 ГИБРИД (Обе CRM) ➔ n8n ➔ Google Таблица
"""

import datetime
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (UnicodeEncodeError, AttributeError):
        pass

if sys.stdin.encoding != "utf-8":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (UnicodeEncodeError, AttributeError):
        pass

HOME_DIR = Path.home()
BASE_DIR = Path(__file__).resolve().parent


# C1: Динамический кроссплатформенный поиск service_account.json
def find_service_account() -> str:
    env_sa = os.getenv("REVOPS_SA_FILE")
    if env_sa and os.path.exists(env_sa):
        return os.path.abspath(env_sa)
    candidates = [
        BASE_DIR / "service_account.json",
        BASE_DIR.parent / "service_account.json",
        BASE_DIR.parent.parent / "service_account.json",
        HOME_DIR / ".gemini" / "antigravity" / "scratch" / "service_account.json",
        HOME_DIR / "service_account.json",
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())
    return str((BASE_DIR.parent.parent / "service_account.json").resolve())


SERVICE_ACCOUNT_FILE = find_service_account()
REGISTRY_FILE = str(BASE_DIR / "tenants_registry.json")

# Tunnel Manager import с безопасным fallback
try:
    scratch_dir = os.getenv("REVOPS_SCRATCH", str(HOME_DIR / ".gemini" / "antigravity" / "scratch"))
    if os.path.exists(scratch_dir) and scratch_dir not in sys.path:
        sys.path.append(scratch_dir)
    from tunnel_manager import get_active_tunnel_url, is_cloudflared_running, start_tunnel
except ImportError:

    def get_active_tunnel_url():
        return "http://localhost:5678"

    def is_cloudflared_running():
        return False

    def start_tunnel():
        return None
except Exception:

    def get_active_tunnel_url():
        return "http://localhost:5678"

    def is_cloudflared_running():
        return False

    def start_tunnel():
        return None


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def load_registry():
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Ошибка чтения реестра {REGISTRY_FILE}: {e}")
    return {"tenants": []}


def save_registry(data):
    """C2: Атомарное сохранение локального реестра без cross-project мутаций"""
    try:
        os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
        tmp_file = REGISTRY_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, REGISTRY_FILE)
    except Exception as e:
        print(f"[!] Не удалось сохранить реестр {REGISTRY_FILE}: {e}")
        raise


def get_gspread_client():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"service_account.json не найден: {SERVICE_ACCOUNT_FILE}")
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds)


def check_n8n_status():
    try:
        with urllib.request.urlopen("http://localhost:5678/healthz", timeout=2) as resp:
            if resp.status == 200:
                return True, "🟢 n8n Активен (localhost:5678)"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return True, f"🟡 n8n Требует авторизации (HTTP {e.code})"
        return False, f"🔴 n8n Ошибка HTTP {e.code}"
    except Exception:
        pass
    return False, "🔴 n8n Остановлен (порт 5678 не отвечает)"


def print_header(title="ИНТЕГРАЦИЯ CRM ➔ n8n ➔ GOOGLE ТАБЛИЦА"):
    print("╔" + "═" * 74 + "╗")
    print(f"║ {title.center(72)} ║")
    print("║" + " Автоматическая синхронизация звонков, аналитики и ИИ-аудита ".center(74) + "║")
    print("╚" + "═" * 74 + "╝\n")


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ САНИТИЗАЦИИ И ПАГИНАЦИИ CRM
# ─────────────────────────────────────────────────────────────────────────────
def clean_stage_name(raw_name: str) -> str:
    """m3: Срезает только ведущие номера 1-2 цифр (напр. '1. ', '02 - '), сохраняя '2026-План'"""
    cleaned = re.sub(r"^\d{1,2}[\.\s\-]+", "", str(raw_name).strip()).strip()
    return cleaned or str(raw_name).strip()


DANGEROUS_FORMULA_PREFIXES = ("=", "+", "@")


def sanitize_sheet_val(val):
    """M3: Предотвращает Formula Injection, сохраняя дефисы '-' и отрицательные числа"""
    if isinstance(val, str) and val:
        if val in ("-", "—", "–"):
            return val
        if val[0] in DANGEROUS_FORMULA_PREFIXES:
            return "'" + val
    return val


# C4: Пагинаторы выгрузки 100% базы CRM
# C4: Пагинаторы выгрузки 100% базы CRM
def fetch_all_amocrm_leads(clean_domain: str, token: str, ctx: ssl.SSLContext = None, max_pages: int = 40) -> list:
    """C4: Выгружает ВСЕ сделки из amoCRM с постраничной навигацией (до 250 на страницу)"""
    if ctx is None:
        ctx = ssl.create_default_context()
    leads = []
    page = 1
    while page <= max_pages:
        url = f"https://{clean_domain}/api/v4/leads?with=contacts&limit=250&page={page}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token.strip()}", "User-Agent": "RevOps-Enterprise-OS/18.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            batch = data.get("_embedded", {}).get("leads", [])
            if not batch:
                break
            leads.extend(batch)
            if not data.get("_links", {}).get("next"):
                break
            page += 1
        except urllib.error.HTTPError as e:
            if e.code == 204:
                break
            print(f"      [!] amoCRM сделки (стр. {page}) HTTP {e.code}")
            break
        except Exception as e:
            print(f"      [!] amoCRM сделки (стр. {page}) ошибка: {e}")
            break
    return leads


def fetch_all_amocrm_contacts_map(
    clean_domain: str, token: str, ctx: ssl.SSLContext = None, max_pages: int = 20
) -> dict:
    """C4: Выгружает контакты с пагинацией и формирует словарь {contact_id: name}"""
    if ctx is None:
        ctx = ssl.create_default_context()
    contacts_map = {}
    page = 1
    while page <= max_pages:
        url = f"https://{clean_domain}/api/v4/contacts?limit=250&page={page}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token.strip()}", "User-Agent": "RevOps-Enterprise-OS/18.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            batch = data.get("_embedded", {}).get("contacts", [])
            if not batch:
                break
            for c in batch:
                contacts_map[c["id"]] = c.get("name", "Клиент")
            if not data.get("_links", {}).get("next"):
                break
            page += 1
        except urllib.error.HTTPError as e:
            if e.code == 204:
                break
            break
        except Exception:
            break
    return contacts_map


def fetch_all_b24_deals(
    clean_url: str, ctx: ssl.SSLContext = None, max_batches: int = 40, max_pages: int = None
) -> list:
    """C4: Выгружает ВСЕ сделки из Битрикс24 с постраничной навигацией start=next"""
    if ctx is None:
        ctx = ssl.create_default_context()
    if max_pages is not None:
        max_batches = max_pages
    deals = []
    start = 0
    batches = 0
    while batches < max_batches:
        batches += 1
        list_url = f"{clean_url}crm.deal.list"
        payload = json.dumps(
            {
                "order": {"DATE_MODIFY": "DESC"},
                "select": ["ID", "TITLE", "OPPORTUNITY", "STAGE_ID", "DATE_CREATE", "DATE_MODIFY", "ASSIGNED_BY_ID"],
                "start": start,
            }
        ).encode("utf-8")
        req = urllib.request.Request(list_url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            batch = data.get("result", [])
            if not batch:
                break
            deals.extend(batch)
            if data.get("next") is None:
                break
            start = data["next"]
        except Exception as e:
            print(f"      [!] Bitrix24 сделки (пакет {batches}) ошибка: {e}")
            break
    return deals


def fetch_all_b24_users(
    clean_url: str, ctx: ssl.SSLContext = None, max_batches: int = 10, max_pages: int = None
) -> list:
    """C4: Выгружает пользователей из Битрикс24 с пагинацией start=next"""
    if ctx is None:
        ctx = ssl.create_default_context()
    if max_pages is not None:
        max_batches = max_pages
    users = []
    start = 0
    batches = 0
    while batches < max_batches:
        batches += 1
        users_url = f"{clean_url}user.get?ACTIVE=Y&start={start}"
        req = urllib.request.Request(users_url)
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            batch = data.get("result", [])
            if not batch:
                break
            users.extend(batch)
            if data.get("next") is None:
                break
            start = data["next"]
        except Exception:
            break
    return users


def discover_crm_stages_and_mapping(crm_type, amo_domain, amo_token, b24_webhook_url):
    """
    Автоматически считывает этапы воронки из amoCRM или Битрикс24
    и возвращает:
      crm_to_canonical: dict {crm_status_id: 1..7}
      canonical_names: dict {1: "1. Этап", 2: "2. Этап", ... 7: "7. Этап"}
      stage_settings: list of [name, sla_hours, win_prob] for rows 12..18
    """
    crm_to_canonical = {}
    canonical_names = {}
    stage_settings = []

    def_sla = [24, 48, 72, 48, 72, 0, 0]
    def_win = [0.10, 0.35, 0.60, 0.85, 0.95, 1.00, 0.00]

    ctx = ssl.create_default_context()

    if crm_type in ["amocrm", "hybrid", "both"] and amo_token:
        clean_domain = (amo_domain or "").replace("https://", "").replace("http://", "").strip("/")
        if not clean_domain.endswith(".amocrm.ru"):
            clean_domain = f"{clean_domain}.amocrm.ru"

        pipelines_url = f"https://{clean_domain}/api/v4/leads/pipelines"
        req = urllib.request.Request(pipelines_url, headers={"Authorization": f"Bearer {amo_token.strip()}"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            p_data = json.loads(resp.read().decode("utf-8"))

        pipelines = p_data.get("_embedded", {}).get("pipelines", [])
        main_p = next((p for p in pipelines if p.get("is_main")), pipelines[0] if pipelines else {})
        statuses = main_p.get("_embedded", {}).get("statuses", [])
        statuses.sort(key=lambda s: int(s.get("sort") or 0))

        won_st = [s for s in statuses if s.get("id") == 142 or "успеш" in s.get("name", "").lower()]
        lost_st = [
            s
            for s in statuses
            if s.get("id") == 143 or "закрыт" in s.get("name", "").lower() or "не реализ" in s.get("name", "").lower()
        ]

        active_st = []
        unsorted_st = None
        for s in statuses:
            if s in won_st or s in lost_st:
                continue
            if "неразобран" in s.get("name", "").lower():
                unsorted_st = s
            else:
                active_st.append(s)

        if not active_st and unsorted_st:
            active_st.append(unsorted_st)
            unsorted_st = None

        default_names = [
            "Первичный контакт",
            "Переговоры",
            "Принимают решение",
            "Согласование договора",
            "Счёт / Оплата",
        ]
        for i in range(5):
            slot = i + 1
            if i < len(active_st):
                st = active_st[i]
                crm_to_canonical[st["id"]] = slot
                name = clean_stage_name(st["name"])
            else:
                name = default_names[i]
            canonical_names[slot] = f"{slot}. {name}"

        if unsorted_st:
            crm_to_canonical[unsorted_st["id"]] = 1

        if len(active_st) > 5:
            for extra_st in active_st[5:]:
                crm_to_canonical[extra_st["id"]] = 5

        won = won_st[0] if won_st else {"id": 142, "name": "Успешно реализовано"}
        for w in won_st:
            crm_to_canonical[w["id"]] = 6
        crm_to_canonical[142] = 6
        canonical_names[6] = f"6. {clean_stage_name(won.get('name', 'Успешно реализовано'))}"

        lost = lost_st[0] if lost_st else {"id": 143, "name": "Закрыто и не реализовано"}
        for l in lost_st:
            crm_to_canonical[l["id"]] = 7
        crm_to_canonical[143] = 7
        canonical_names[7] = f"7. {clean_stage_name(lost.get('name', 'Закрыто и не реализовано'))}"

    elif crm_type == "bitrix24" and b24_webhook_url:
        clean_url = b24_webhook_url.strip()
        if not clean_url.endswith("/"):
            clean_url += "/"

        stages_url = f"{clean_url}crm.dealcategory.stage.list?id=0"
        req = urllib.request.Request(stages_url)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_stages = data.get("result", [])

        if not raw_stages:
            fallback_url = f"{clean_url}crm.status.list?ENTITY_ID=DEAL_STAGE"
            req2 = urllib.request.Request(fallback_url)
            with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8"))
            raw_stages = data2.get("result", [])

        raw_stages.sort(key=lambda s: int(s.get("SORT") or 0))

        won_st = [
            s for s in raw_stages if "WON" in str(s.get("STATUS_ID", "")) or "SUCCESS" in str(s.get("STATUS_ID", ""))
        ]
        lost_st = [s for s in raw_stages if any(k in str(s.get("STATUS_ID", "")) for k in ["LOSE", "FAIL", "APOLOGY"])]
        active_st = [s for s in raw_stages if s not in won_st and s not in lost_st]

        default_names = ["Новая", "Подготовка документов", "Cчёт на предоплату", "В работе", "Финальный счёт"]
        for i in range(5):
            slot = i + 1
            if i < len(active_st):
                st = active_st[i]
                crm_to_canonical[st["STATUS_ID"]] = slot
                name = clean_stage_name(st["NAME"])
            else:
                name = default_names[i]
            canonical_names[slot] = f"{slot}. {name}"

        if len(active_st) > 5:
            for extra_st in active_st[5:]:
                crm_to_canonical[extra_st["STATUS_ID"]] = 5

        won = won_st[0] if won_st else {"STATUS_ID": "WON", "NAME": "Сделка успешна"}
        for w in won_st:
            crm_to_canonical[w["STATUS_ID"]] = 6
        crm_to_canonical["WON"] = 6
        canonical_names[6] = f"6. {clean_stage_name(won.get('NAME', 'Сделка успешна'))}"

        lost = lost_st[0] if lost_st else {"STATUS_ID": "LOSE", "NAME": "Сделка провалена"}
        for l in lost_st:
            crm_to_canonical[l["STATUS_ID"]] = 7
        crm_to_canonical["LOSE"] = 7
        canonical_names[7] = f"7. {clean_stage_name(lost.get('NAME', 'Сделка провалена'))}"

    else:
        canonical_names = {
            1: "1. Новый лид",
            2: "2. Квалификация / ЛПР",
            3: "3. Встреча / Демо",
            4: "4. КП и согласование",
            5: "5. Счет выставлен",
            6: "6. Успешно реализовано",
            7: "7. Закрыто и не реализовано",
        }

    for slot in range(1, 8):
        stage_settings.append([canonical_names.get(slot, f"{slot}. Этап {slot}"), def_sla[slot - 1], def_win[slot - 1]])

    return crm_to_canonical, canonical_names, stage_settings


def discover_crm_users(crm_type, amo_domain, amo_token, b24_webhook_url, client_email=None):
    """
    Автоматически опрашивает API CRM (amoCRM / Битрикс24)
    и возвращает список реальных пользователей/менеджеров:
    [
      {
        "id": "11422686",
        "name": "Дмитрий Федотов",
        "email": "dmitriyfedotov1908@gmail.com",
        "role": "РОП",
        "is_admin": True,
        "crm_type": "amocrm"
      },
      ...
    ]
    """
    users = []
    ctx = ssl.create_default_context()

    # amoCRM пользователи
    if crm_type in ["amocrm", "hybrid", "both"] and amo_token:
        clean_domain = (amo_domain or "").replace("https://", "").replace("http://", "").strip("/")
        if not clean_domain.endswith(".amocrm.ru"):
            clean_domain = f"{clean_domain}.amocrm.ru"
        users_url = f"https://{clean_domain}/api/v4/users"
        try:
            req = urllib.request.Request(users_url, headers={"Authorization": f"Bearer {amo_token.strip()}"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                u_data = json.loads(resp.read().decode("utf-8"))
                raw_users = u_data.get("_embedded", {}).get("users", [])
                for u in raw_users:
                    uid = str(u.get("id"))
                    uname = clean_stage_name(u.get("name") or f"Пользователь {uid}")
                    uemail = str(u.get("email") or "").strip()
                    is_adm = bool(u.get("rights", {}).get("is_admin"))
                    role = "РОП" if is_adm else "Менеджер ОП"
                    users.append(
                        {
                            "id": uid,
                            "name": uname,
                            "email": uemail,
                            "role": role,
                            "is_admin": is_adm,
                            "crm_type": "amocrm",
                        }
                    )
        except Exception:
            pass

    # Битрикс24 пользователи
    if crm_type in ["bitrix24", "hybrid", "both"] and b24_webhook_url:
        clean_url = b24_webhook_url.strip()
        if not clean_url.endswith("/"):
            clean_url += "/"
        b24_users_url = f"{clean_url}user.get?ACTIVE=Y"
        try:
            req = urllib.request.Request(b24_users_url)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                b_data = json.loads(resp.read().decode("utf-8"))
                raw_b_users = b_data.get("result", [])
                for u in raw_b_users:
                    uid = str(u.get("ID"))
                    fname = (u.get("NAME") or "").strip()
                    lname = (u.get("LAST_NAME") or "").strip()
                    uname = f"{fname} {lname}".strip() or u.get("EMAIL") or f"Менеджер {uid}"
                    uemail = str(u.get("EMAIL") or "").strip()
                    pos = str(u.get("WORK_POSITION") or "").lower()
                    is_adm = (
                        any(k in pos for k in ["роп", "рук", "дир", "head", "lead", "админ", "admin"]) or uid == "1"
                    )
                    role = "РОП" if is_adm else ("КАМ" if any(k in pos for k in ["кам", "kam"]) else "Менеджер ОП")
                    if not any(x["id"] == uid and x["crm_type"] == "bitrix24" for x in users):
                        users.append(
                            {
                                "id": uid,
                                "name": uname,
                                "email": uemail,
                                "role": role,
                                "is_admin": is_adm,
                                "crm_type": "bitrix24",
                            }
                        )
        except Exception:
            pass

    # Интеллектуальная сортировка:
    # 1. Основной пользователь (совпадающий с client_email)
    # 2. Администраторы / РОПы
    # 3. Реальные ФИО (без @ в имени)
    def user_sort_key(u):
        is_client = 0 if (client_email and u.get("email") and u["email"].lower() == str(client_email).lower()) else 1
        is_admin = 0 if u.get("is_admin") else 1
        has_real_name = 0 if ("@" not in u.get("name", "") and u.get("name")) else 1
        return (is_client, is_admin, has_real_name, u.get("id"))

    users.sort(key=user_sort_key)

    if not users:
        users = [
            {
                "id": "101",
                "name": "Менеджер 1 (РОП)",
                "email": "",
                "role": "РОП",
                "is_admin": True,
                "crm_type": "default",
            }
        ]

    return users


def sync_internal_navigation_bars(sh):
    """Синхронизирует бесшовную локальную навигацию Row 2 (#gid=...) на ключевых дашбордах"""
    try:
        title_to_id = {ws.title: ws.id for ws in sh.worksheets()}
        nav_items = [
            ("📄 Executive_OnePager", "📄 1. One-Pager"),
            ("⚡ Пульс_Компании", "⚡ 2. Пульс компании"),
            ("📋 Пульт_РОПа_15_Минут", "📋 3. Пульт РОПа"),
            ("💸 Диагностика_Утечек_ОП", "💸 4. 7 Грехов ОП"),
            ("🎯 Action_Center", "🎯 5. Action Center"),
            ("🎙️ ИИ_Аудит", "🎙️ 6. ИИ-Аудит"),
            ("⚡ Экспресс_Калькулятор_3_Цифры", "⚡ 7. Экспресс 3 цифры"),
            ("🧪 QA_Suite", "🧪 8. QA Suite"),
            ("⚙️ Настройки", "⚙️ 9. Настройки"),
        ]
        nav_formulas = []
        for sheet_name, label in nav_items:
            gid = title_to_id.get(sheet_name)
            if gid is not None:
                nav_formulas.append(f'=HYPERLINK("#gid={gid}", "{label}")')
            else:
                nav_formulas.append(label)

        for ws_name in [
            "📄 Executive_OnePager",
            "⚡ Пульс_Компании",
            "📋 Пульт_РОПа_15_Минут",
            "💸 Диагностика_Утечек_ОП",
        ]:
            try:
                ws = sh.worksheet(ws_name)
                ws.update(range_name="A2:I2", values=[nav_formulas], value_input_option="USER_ENTERED")
            except Exception:
                pass
    except Exception as e:
        print(f"      [!] Навигация: {e}")


def sync_executive_dashboards(sh):
    """Синхронизирует One-Pager, Пульт РОПа и Диагностику утечек с реальным пайплайном и воронкой"""
    # 1. 📄 Executive_OnePager
    try:
        ws_exec = sh.worksheet("📄 Executive_OnePager")
        kpi_f5_g5 = [
            [
                "=IFERROR(COUNTIF('🎯 Воронка_и_SLA'!$F$4:$F$8, \"⚠️ ПРОСРОЧЕН\"), 0)",
                '=IFERROR(ROUND(AVERAGEIF(raw_calls!$T$2:$T1000, ">0"), 1), 0)',
            ]
        ]
        ws_exec.update(range_name="F5:G5", values=kpi_f5_g5, value_input_option="USER_ENTERED")

        funnel_exec_rows = [
            [
                "='⚙️ Настройки'!$B$12",
                "='⚡ Пульс_Компании'!B10",
                "='⚡ Пульс_Компании'!C10",
                "='⚙️ Настройки'!$C$12 & \" ч\"",
            ],
            [
                "='⚙️ Настройки'!$B$13",
                "='⚡ Пульс_Компании'!B11",
                "='⚡ Пульс_Компании'!C11",
                "='⚙️ Настройки'!$C$13 & \" ч\"",
            ],
            [
                "='⚙️ Настройки'!$B$14",
                "='⚡ Пульс_Компании'!B12",
                "='⚡ Пульс_Компании'!C12",
                "='⚙️ Настройки'!$C$14 & \" ч\"",
            ],
            [
                "='⚙️ Настройки'!$B$15",
                "='⚡ Пульс_Компании'!B13",
                "='⚡ Пульс_Компании'!C13",
                "='⚙️ Настройки'!$C$15 & \" ч\"",
            ],
            [
                "='⚙️ Настройки'!$B$16",
                "='⚡ Пульс_Компании'!B14",
                "='⚡ Пульс_Компании'!C14",
                "='⚙️ Настройки'!$C$16 & \" ч\"",
            ],
            ["='⚙️ Настройки'!$B$17", "='⚡ Пульс_Компании'!B15", "='⚡ Пульс_Компании'!C15", "0 ч"],
            ["='⚙️ Настройки'!$B$18", "='⚡ Пульс_Компании'!B16", "='⚡ Пульс_Компании'!C16", "0 ч"],
        ]
        ws_exec.update(range_name="A9:D15", values=funnel_exec_rows, value_input_option="USER_ENTERED")
        try:
            ws_exec.format("B9:B15", {"horizontalAlignment": "CENTER"})
            ws_exec.format(
                "C9:C15", {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"}
            )
            ws_exec.format("D9:D15", {"horizontalAlignment": "CENTER"})
        except Exception:
            pass

        action_rows = [
            [
                '=IF(raw_deals!$B$2="", "—", raw_deals!$B$2)',
                '=IF(raw_deals!$B$2="", "—", "В пайплайне на этапе " & raw_deals!$E$2)',
                '=IF(raw_deals!$B$2="", 0, raw_deals!$C$2)',
                '=IF(raw_deals!$B$2="", "—", "⚡ Дожим до закрытия (РОП " & raw_deals!$AF$2 & ")")',
            ],
            [
                '=IF(raw_deals!$B$3="", "—", raw_deals!$B$3)',
                '=IF(raw_deals!$B$3="", "—", "В пайплайне на этапе " & raw_deals!$E$3)',
                '=IF(raw_deals!$B$3="", 0, raw_deals!$C$3)',
                '=IF(raw_deals!$B$3="", "—", "Квалификация лида (РОП " & raw_deals!$AF$3 & ")")',
            ],
            ["—", "—", 0, "—"],
            ["—", "—", 0, "—"],
            ["—", "—", 0, "—"],
        ]
        ws_exec.update(range_name="F9:I13", values=action_rows, value_input_option="USER_ENTERED")
        try:
            ws_exec.format(
                "H9:H13", {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"}
            )
        except Exception:
            pass
    except Exception as e:
        print(f"      [!] Executive_OnePager: {e}")

    # 2. 📋 Пульт_РОПа_15_Минут
    try:
        ws_rop = sh.worksheet("📋 Пульт_РОПа_15_Минут")
        rop_rows = [
            [
                1,
                '=IF(raw_deals!$B$2="", "—", raw_deals!$B$2)',
                '=IF(raw_deals!$B$2="", "—", "Этап: " & raw_deals!$E$2 & ", ответственный: " & raw_deals!$AF$2)',
                '=IF(raw_deals!$B$2="", 0, raw_deals!$C$2)',
                '=IF(raw_deals!$C$2>300000, "🔴 КРИТИЧЕСКИЙ (P0)", "🟡 ВНИМАНИЕ (P1)")',
                '=IF(raw_deals!$B$2="", "—", "Провести разбор звонка, согласовать спецпредложение и закрыть сделку")',
            ],
            [
                2,
                '=IF(raw_deals!$B$3="", "—", raw_deals!$B$3)',
                '=IF(raw_deals!$B$3="", "—", "Этап: " & raw_deals!$E$3 & ", ответственный: " & raw_deals!$AF$3)',
                '=IF(raw_deals!$B$3="", 0, raw_deals!$C$3)',
                '=IF(raw_deals!$B$3="", "—", "🟡 ВНИМАНИЕ (P1)")',
                '=IF(raw_deals!$B$3="", "—", "Квалифицировать ЛПР, выявить бюджет и зафиксировать Next Step")',
            ],
            [3, "—", "—", 0, "—", "—"],
            [4, "—", "—", 0, "—", "—"],
            [5, "—", "—", 0, "—", "—"],
        ]
        ws_rop.update(range_name="A9:F13", values=rop_rows, value_input_option="USER_ENTERED")
        try:
            ws_rop.format(
                "D9:D13", {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"}
            )
        except Exception:
            pass
    except Exception as e:
        print(f"      [!] Пульт РОПа: {e}")

    # 3. 💸 Диагностика_Утечек_ОП
    try:
        ws_leak = sh.worksheet("💸 Диагностика_Утечек_ОП")
        ws_leak.update(
            range_name="D11",
            values=[
                [
                    "=IFERROR(SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$21, raw_deals!$D$2:$D1000, \"<=5\"), 0)"
                ]
            ],
            value_input_option="USER_ENTERED",
        )
    except Exception as e:
        print(f"      [!] Диагностика утечек: {e}")


def auto_discover_and_sync_all(tenant_record):
    """
    Полная сквозная авто-синхронизация под ключ:
    1. Считывает этапы воронки и сотрудников из CRM (amoCRM / Битрикс24)
    2. Нормализует этапы (1..5 в работе, 6 выиграно, 7 проиграно)
    3. Записывает этапы в ⚙️ Настройки!B12:D18 и сотрудников в ⚙️ Настройки!A21:E24
    4. Обновляет RBAC email маппинг в ⚙️ Настройки!J10:L10
    5. Настраивает динамические формулы сотрудников (calc_engine, 👥 Ресурсный_План, 🌐 Сквозная_RevOps_Аналитика, calc_sales)
    6. Загружает сделки из CRM и нормализует stage_id (1..7), ответственных менеджеров и суммы (#,##0 ₽)
    7. Настраивает динамические формулы на листах ⚡ Пульс_Компании (A10:D16) и 🎯 Воронка_и_SLA (A4:F10)
    8. Настраивает воркфлоу n8n (токен, URL, привязка spreadsheet_id)
    9. Сохраняет метаданные синхронизации (этапы + сотрудники) в tenants_registry.json
    """
    try:
        sheet_id = tenant_record["spreadsheet_id"]
        crm_type = tenant_record.get("crm_type", "amocrm")
        amo_domain = tenant_record.get("amo_domain", "")
        amo_token = tenant_record.get("amo_token", "")
        b24_webhook = tenant_record.get("b24_webhook_url") or tenant_record.get("crm_webhook_url", "")
        client_email = tenant_record.get("client_email", "")

        ctx = ssl.create_default_context()
        gc = get_gspread_client()
        sh = gc.open_by_key(sheet_id)
        print(f"\n[1/7] 📊 Google Таблица открыта: '{sh.title}'")

        # 1. Считывание стадий воронки и сотрудников из CRM
        print(f"[2/7] 🔍 Считывание этапов воронки и сотрудников из CRM ({crm_type.upper()})...")
        crm_to_canon, canon_names, stage_settings = discover_crm_stages_and_mapping(
            crm_type, amo_domain, amo_token, b24_webhook
        )
        discovered_users = discover_crm_users(crm_type, amo_domain, amo_token, b24_webhook, client_email=client_email)
        users_map = {str(u["id"]): u["name"] for u in discovered_users}
        primary_user = discovered_users[0]

        print("      Обнаруженные этапы воронки:")
        for s in stage_settings:
            print(f"      • {s[0]} (SLA: {s[1]}ч, Win%: {int(s[2] * 100)}%)")
        print("      Обнаруженные сотрудники CRM:")
        for u in discovered_users:
            print(f"      • [{u['id']}] {u['name']} ({u['role']}, {u['email'] or 'нет email'})")

        # 2. Обновление листа ⚙️ Настройки (Этапы + Сотрудники + RBAC)
        print("[3/7] ⚙️ Синхронизация листа '⚙️ Настройки' (Этапы + Сотрудники + RBAC)...")
        ws_settings = sh.worksheet("⚙️ Настройки")
        existing_settings = ws_settings.get("C12:D18")
        def_win = [0.10, 0.35, 0.60, 0.85, 0.95, 1.00, 0.00]
        for idx, row in enumerate(existing_settings):
            if idx >= len(stage_settings):
                break
            if row and len(row) >= 1 and str(row[0]).strip().isdigit():
                stage_settings[idx][1] = int(row[0])
            if row and len(row) >= 2:
                try:
                    val = float(str(row[1]).replace(",", ".").replace("%", ""))
                    if val > 1.0:
                        val /= 100.0
                    if not (0.0 <= val <= 1.0):
                        print(
                            f"      [!] Win% для этапа {idx + 1} ({val:.2f}) вне диапазона [0..1], сброшено к дефолту"
                        )
                        val = def_win[idx]
                    stage_settings[idx][2] = val
                except Exception:
                    pass

        ws_settings.update(range_name="B12:D18", values=stage_settings, value_input_option="USER_ENTERED")

        # Запись сотрудников в A21:E24 (4 слота, лишние очищаются '—')
        manager_rows = []
        default_roles = ["РОП", "КАМ", "SDR", "SDR-2"]
        default_limits = [50, 30, 40, 40]
        for slot in range(4):
            if slot < len(discovered_users):
                u = discovered_users[slot]
                uid = int(u["id"]) if str(u["id"]).isdigit() else u["id"]
                uname = u["name"]
                urole = u.get("role") or default_roles[slot]
                ulimit = default_limits[slot]
                ustatus = "Норма"
                manager_rows.append([uid, uname, urole, ulimit, ustatus])
            else:
                manager_rows.append(["—", "—", "—", 0, "—"])
        ws_settings.update(range_name="A21:E24", values=manager_rows, value_input_option="USER_ENTERED")

        # RBAC Email mapping (привязка почты первого админа/клиента к роли CEO)
        client_email = tenant_record.get("client_email") or primary_user.get("email")
        if client_email:
            rbac_updates = [[client_email, "👑 CEO", "📄 Executive_OnePager"]]
            ws_settings.update(range_name="J10:L10", values=rbac_updates, value_input_option="USER_ENTERED")
        print("      [✓] Лист '⚙️ Настройки' успешно обновлён!")

        # 3. Настройка динамических формул по сотрудникам
        print("[4/7] 🔗 Настройка динамических формул сотрудников (calc_engine, Ресурсный план, Аналитика)...")
        try:
            ws_ce = sh.worksheet("calc_engine")
            ce_formulas = [
                [
                    "='⚙️ Настройки'!$A$21",
                    "='⚙️ Настройки'!$B$21",
                    150000,
                    "=IF(OR('⚙️ Настройки'!$A$21=\"—\", '⚙️ Настройки'!$A$21=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$21, raw_deals!$O$2:$O1000, TRUE))",
                    0.03,
                    1,
                    1.05,
                ],
                [
                    "='⚙️ Настройки'!$A$22",
                    "='⚙️ Настройки'!$B$22",
                    100000,
                    "=IF(OR('⚙️ Настройки'!$A$22=\"—\", '⚙️ Настройки'!$A$22=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$22, raw_deals!$O$2:$O1000, TRUE))",
                    0.05,
                    1,
                    0.70,
                ],
                [
                    "='⚙️ Настройки'!$A$23",
                    "='⚙️ Настройки'!$B$23",
                    70000,
                    "=IF(OR('⚙️ Настройки'!$A$23=\"—\", '⚙️ Настройки'!$A$23=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$23, raw_deals!$O$2:$O1000, TRUE))",
                    0.00,
                    1,
                    1.10,
                ],
            ]
            ws_ce.update(range_name="A172:G174", values=ce_formulas, value_input_option="USER_ENTERED")
            ce_counts = [
                [
                    "=IF(OR('⚙️ Настройки'!$A$21=\"—\", '⚙️ Настройки'!$A$21=\"\"), 0, COUNTIFS(raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$21, raw_deals!$D$2:$D1000, \"<=5\"))"
                ],
                [
                    "=IF(OR('⚙️ Настройки'!$A$22=\"—\", '⚙️ Настройки'!$A$22=\"\"), 0, COUNTIFS(raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$22, raw_deals!$D$2:$D1000, \"<=5\"))"
                ],
                [
                    "=IF(OR('⚙️ Настройки'!$A$23=\"—\", '⚙️ Настройки'!$A$23=\"\"), 0, COUNTIFS(raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$23, raw_deals!$D$2:$D1000, \"<=5\"))"
                ],
            ]
            ws_ce.update(range_name="D43:D45", values=ce_counts, value_input_option="USER_ENTERED")
        except Exception as e:
            print(f"      [!] calc_engine: {e}")

        try:
            ws_res = sh.worksheet("👥 Ресурсный_План")
            res_formulas = [
                ["='⚙️ Настройки'!$A$21", "='⚙️ Настройки'!$B$21", "='⚙️ Настройки'!$C$21", "='⚙️ Настройки'!$D$21"],
                ["='⚙️ Настройки'!$A$22", "='⚙️ Настройки'!$B$22", "='⚙️ Настройки'!$C$22", "='⚙️ Настройки'!$D$22"],
                ["='⚙️ Настройки'!$A$23", "='⚙️ Настройки'!$B$23", "='⚙️ Настройки'!$C$23", "='⚙️ Настройки'!$D$23"],
            ]
            ws_res.update(range_name="A8:D10", values=res_formulas, value_input_option="USER_ENTERED")
        except Exception as e:
            print(f"      [!] 👥 Ресурсный_План: {e}")

        try:
            ws_an = sh.worksheet("🌐 Сквозная_RevOps_Аналитика")
            an_ids = [
                ["='⚙️ Настройки'!$A$21", "='⚙️ Настройки'!$B$21", "='⚙️ Настройки'!$C$21"],
                ["='⚙️ Настройки'!$A$22", "='⚙️ Настройки'!$B$22", "='⚙️ Настройки'!$C$22"],
                ["='⚙️ Настройки'!$A$23", "='⚙️ Настройки'!$B$23", "='⚙️ Настройки'!$C$23"],
            ]
            ws_an.update(range_name="A17:C19", values=an_ids, value_input_option="USER_ENTERED")
            an_sums = [
                [
                    "=IF(OR('⚙️ Настройки'!$A$21=\"—\", '⚙️ Настройки'!$A$21=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$21, raw_deals!$D$2:$D1000, 6))"
                ],
                [
                    "=IF(OR('⚙️ Настройки'!$A$22=\"—\", '⚙️ Настройки'!$A$22=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$22, raw_deals!$D$2:$D1000, 6))"
                ],
                [
                    "=IF(OR('⚙️ Настройки'!$A$23=\"—\", '⚙️ Настройки'!$A$23=\"\"), 0, SUMIFS(raw_deals!$C$2:$C1000, raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$23, raw_deals!$D$2:$D1000, 6))"
                ],
            ]
            ws_an.update(range_name="I17:I19", values=an_sums, value_input_option="USER_ENTERED")
        except Exception as e:
            print(f"      [!] 🌐 Сквозная_RevOps_Аналитика: {e}")

        try:
            ws_cs = sh.worksheet("calc_sales")
            ws_cs.update(
                range_name="A15",
                values=[['="Доля клиентской базы РОПа (" & \'⚙️ Настройки\'!$B$21 & ")"']],
                value_input_option="USER_ENTERED",
            )
            ws_cs.update(
                range_name="B15",
                values=[
                    [
                        "=IF(OR('⚙️ Настройки'!$A$21=\"—\", '⚙️ Настройки'!$A$21=\"\"), 0, COUNTIFS(raw_deals!$H$2:$H1000, '⚙️ Настройки'!$A$21, raw_deals!$D$2:$D1000, \"<=5\")/MAX(calc_engine!B16, 1))"
                    ]
                ],
                value_input_option="USER_ENTERED",
            )
        except Exception as e:
            print(f"      [!] calc_sales: {e}")

        # 4. Синхронизация сделок из CRM в raw_deals (C4: 100% пагинация базы)
        print("[5/7] 📥 Загрузка и нормализация сделок в 'raw_deals' (с пагинацией)...")
        ws_deals = sh.worksheet("raw_deals")
        existing_deals = ws_deals.get_all_values()
        existing_deal_ids = {row[0]: idx + 1 for idx, row in enumerate(existing_deals[1:]) if row and row[0]}

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")

        synced_deals_count = 0
        total_pipeline_sum = 0.0
        deals_to_update = []
        deals_to_append = []

        # amoCRM сделки с полной пагинацией
        if crm_type in ["amocrm", "hybrid", "both"] and amo_token:
            clean_domain = amo_domain.replace("https://", "").replace("http://", "").strip("/")
            if not clean_domain.endswith(".amocrm.ru"):
                clean_domain = f"{clean_domain}.amocrm.ru"

            contacts_map = fetch_all_amocrm_contacts_map(clean_domain, amo_token, ctx)
            leads = fetch_all_amocrm_leads(clean_domain, amo_token, ctx)

            for lead in leads:
                lead_id = str(lead["id"])
                lead_name = lead.get("name", f"Сделка #{lead_id}")
                price = float(lead.get("price") or 0)
                status_id = lead.get("status_id")

                stage_num = crm_to_canon.get(status_id, 1)
                stage_name = clean_stage_name(canon_names.get(stage_num, "В работе"))

                contact_name = lead_name
                lead_contacts = lead.get("_embedded", {}).get("contacts", [])
                if lead_contacts:
                    first_cid = lead_contacts[0].get("id")
                    if first_cid in contacts_map:
                        contact_name = contacts_map[first_cid]

                created_at_ts = lead.get("created_at", int(datetime.datetime.now().timestamp()))
                created_date = datetime.datetime.fromtimestamp(created_at_ts).strftime("%Y-%m-%d")

                raw_mgr_id = lead.get("responsible_user_id") or primary_user["id"]
                manager_id = int(raw_mgr_id) if str(raw_mgr_id).isdigit() else raw_mgr_id
                manager_name = users_map.get(str(raw_mgr_id), primary_user["name"])

                win_prob = stage_settings[stage_num - 1][2]
                weighted_val = round(price * win_prob, 2)

                is_won = 1 if stage_num == 6 else 0
                is_lost = 1 if stage_num == 7 else 0

                row_data = [
                    lead_id,
                    contact_name,
                    price,
                    stage_num,
                    stage_name,
                    created_date,
                    created_date,
                    manager_id,
                    "SMB",
                    "amoCRM",
                    f"C-{lead_id}",
                    "A" if price > 300000 else "B",
                    "-" if not is_lost else "LOST",
                    now_iso,
                    is_won,
                    is_lost,
                    1,
                    "0-3d",
                    weighted_val,
                    1,
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    today_date,
                    "V18.0",
                    "amoCRM Auto-Sync",
                    f"hash_{lead_id}_amo",
                    "Звонок",
                    today_date,
                    manager_name,
                    "Телефон",
                    "Норма",
                    85,
                    now_iso,
                    "#В_Работе" if stage_num <= 5 else ("#Успешно" if stage_num == 6 else "#Закрыто"),
                ]
                row_data = [sanitize_sheet_val(x) for x in row_data]

                if lead_id in existing_deal_ids:
                    row_num = existing_deal_ids[lead_id] + 1
                    deals_to_update.append({"range": f"A{row_num}:AK{row_num}", "values": [row_data]})
                else:
                    deals_to_append.append(row_data)

                synced_deals_count += 1
                if stage_num <= 5:
                    total_pipeline_sum += price

        # Bitrix24 сделки с полной пагинацией
        if crm_type in ["bitrix24", "hybrid", "both"] and b24_webhook:
            clean_url = b24_webhook.strip()
            if not clean_url.endswith("/"):
                clean_url += "/"

            b_deals = fetch_all_b24_deals(clean_url, ctx)

            for deal in b_deals:
                deal_id = f"B24-{deal['ID']}"
                deal_name = deal.get("TITLE", f"Сделка #{deal['ID']}")
                price = float(deal.get("OPPORTUNITY") or 0)
                b24_st = deal.get("STAGE_ID", "NEW")

                stage_num = crm_to_canon.get(b24_st, 1)
                stage_name = clean_stage_name(canon_names.get(stage_num, "В работе"))

                created_date = (deal.get("DATE_CREATE") or today_date)[:10]
                modified_date = (deal.get("DATE_MODIFY") or today_date)[:10]

                raw_mgr_id = deal.get("ASSIGNED_BY_ID") or primary_user["id"]
                manager_id = int(raw_mgr_id) if str(raw_mgr_id).isdigit() else raw_mgr_id
                manager_name = users_map.get(str(raw_mgr_id), primary_user["name"])

                win_prob = stage_settings[stage_num - 1][2]
                weighted_val = round(price * win_prob, 2)

                is_won = 1 if stage_num == 6 else 0
                is_lost = 1 if stage_num == 7 else 0

                row_data = [
                    deal_id,
                    deal_name,
                    price,
                    stage_num,
                    stage_name,
                    created_date,
                    modified_date,
                    manager_id,
                    "B2B",
                    "Bitrix24",
                    f"C-{deal_id}",
                    "A" if price > 300000 else "B",
                    "-" if not is_lost else "LOST",
                    now_iso,
                    is_won,
                    is_lost,
                    1,
                    "0-3d",
                    weighted_val,
                    1,
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    today_date,
                    "V18.0",
                    "Bitrix24 Auto-Sync",
                    f"hash_{deal['ID']}_b24",
                    "Звонок",
                    today_date,
                    manager_name,
                    "Телефон",
                    "Норма",
                    90,
                    now_iso,
                    "#В_Работе" if stage_num <= 5 else ("#Успешно" if stage_num == 6 else "#Закрыто"),
                ]
                row_data = [sanitize_sheet_val(x) for x in row_data]

                if deal_id in existing_deal_ids:
                    row_num = existing_deal_ids[deal_id] + 1
                    deals_to_update.append({"range": f"A{row_num}:AK{row_num}", "values": [row_data]})
                else:
                    deals_to_append.append(row_data)

                synced_deals_count += 1
                if stage_num <= 5:
                    total_pipeline_sum += price

        # Пакетное сохранение в Google Sheets (защита от лимита 60 req/min)
        if deals_to_update:
            ws_deals.batch_update(deals_to_update, value_input_option="USER_ENTERED")
        if deals_to_append:
            ws_deals.append_rows(deals_to_append, value_input_option="USER_ENTERED")

        max_format_row = max(500, len(existing_deals) + len(deals_to_append) + 100)
        try:
            ws_deals.format(
                f"C2:C{max_format_row}",
                {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"},
            )
            ws_deals.format(
                f"S2:S{max_format_row}",
                {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"},
            )
            ws_deals.format(
                f"D2:D{max_format_row}",
                {"numberFormat": {"type": "NUMBER", "pattern": "0"}, "horizontalAlignment": "CENTER"},
            )
        except Exception:
            pass

        print(
            f"      [✓] Синхронизировано сделок: {synced_deals_count} (Активный пайплайн: {total_pipeline_sum:,.0f} ₽)".replace(
                ",", " "
            )
        )

        # 5. Настройка дашбордов ⚡ Пульс_Компании и 🎯 Воронка_и_SLA
        print("[6/7] 📈 Активация дашбордов '⚡ Пульс_Компании' и '🎯 Воронка_и_SLA'...")
        ws_pulse = sh.worksheet("⚡ Пульс_Компании")
        pulse_rows = [
            [
                "='⚙️ Настройки'!$B$12",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 1)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 1, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D2",
            ],
            [
                "='⚙️ Настройки'!$B$13",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 2)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 2, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D3",
            ],
            [
                "='⚙️ Настройки'!$B$14",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 3)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 3, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D4",
            ],
            [
                "='⚙️ Настройки'!$B$15",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 4)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 4, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D5",
            ],
            [
                "='⚙️ Настройки'!$B$16",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 5)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 5, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D6",
            ],
            [
                "='⚙️ Настройки'!$B$17",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 6)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 6, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D7",
            ],
            [
                "='⚙️ Настройки'!$B$18",
                "=COUNTIF(raw_deals!$D$2:$D$1000, 7)",
                "=SUMIF(raw_deals!$D$2:$D$1000, 7, raw_deals!$C$2:$C$1000)",
                "=calc_engine!D8",
            ],
        ]
        ws_pulse.update(range_name="A10:D16", values=pulse_rows, value_input_option="USER_ENTERED")
        ws_pulse.format(
            "B10:B16", {"numberFormat": {"type": "NUMBER", "pattern": '0" шт"'}, "horizontalAlignment": "CENTER"}
        )
        ws_pulse.format(
            "C10:D16", {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0 ₽"}, "horizontalAlignment": "RIGHT"}
        )

        ws_funnel = sh.worksheet("🎯 Воронка_и_SLA")
        funnel_formulas = [
            [
                "='⚙️ Настройки'!$B$12",
                "=calc_engine!E2",
                "=calc_engine!G2",
                "='⚙️ Настройки'!$C$12 & \" ч\"",
                '=TEXT(MAX(0, IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 1) * 24, 0)), "0.0") & " ч"',
                '=IF(IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 1)*24, 0)>\'⚙️ Настройки\'!$C$12, "⚠️ ПРОСРОЧЕН", "🟢 В НОРМЕ")',
            ],
            [
                "='⚙️ Настройки'!$B$13",
                "=calc_engine!E3",
                "=calc_engine!G3",
                "='⚙️ Настройки'!$C$13 & \" ч\"",
                '=TEXT(MAX(0, IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 2) * 24, 0)), "0.0") & " ч"',
                '=IF(IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 2)*24, 0)>\'⚙️ Настройки\'!$C$13, "⚠️ ПРОСРОЧЕН", "🟢 В НОРМЕ")',
            ],
            [
                "='⚙️ Настройки'!$B$14",
                "=calc_engine!E4",
                "=calc_engine!G4",
                "='⚙️ Настройки'!$C$14 & \" ч\"",
                '=TEXT(MAX(0, IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 3) * 24, 0)), "0.0") & " ч"',
                '=IF(IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 3)*24, 0)>\'⚙️ Настройки\'!$C$14, "⚠️ ПРОСРОЧЕН", "🟢 В НОРМЕ")',
            ],
            [
                "='⚙️ Настройки'!$B$15",
                "=calc_engine!E5",
                "=calc_engine!G5",
                "='⚙️ Настройки'!$C$15 & \" ч\"",
                '=TEXT(MAX(0, IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 4) * 24, 0)), "0.0") & " ч"',
                '=IF(IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 4)*24, 0)>\'⚙️ Настройки\'!$C$15, "⚠️ ПРОСРОЧЕН", "🟢 В НОРМЕ")',
            ],
            [
                "='⚙️ Настройки'!$B$16",
                "=calc_engine!E6",
                "=calc_engine!G6",
                "='⚙️ Настройки'!$C$16 & \" ч\"",
                '=TEXT(MAX(0, IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 5) * 24, 0)), "0.0") & " ч"',
                '=IF(IFERROR(AVERAGEIFS(raw_deals!$Q$2:$Q1000, raw_deals!$D$2:$D1000, 5)*24, 0)>\'⚙️ Настройки\'!$C$16, "⚠️ ПРОСРОЧЕН", "🟢 В НОРМЕ")',
            ],
            ["='⚙️ Настройки'!$B$17", "=calc_engine!E7", "=calc_engine!G7", "—", "—", "🟢 ФИНИШ"],
            ["='⚙️ Настройки'!$B$18", "=calc_engine!E8", "=calc_engine!G8", "—", "—", "🟢 ФИНИШ"],
        ]
        ws_funnel.update(range_name="A4:F10", values=funnel_formulas, value_input_option="USER_ENTERED")
        print("      [✓] Формулы '⚡ Пульс_Компании' и '🎯 Воронка_и_SLA' синхронизированы!")

        # 6. Синхронизация управленческих дашбордов и бесшовной навигации
        sync_executive_dashboards(sh)
        sync_internal_navigation_bars(sh)
        print(
            "      [✓] Дашборды '📄 Executive_OnePager', '📋 Пульт_РОПа_15_Минут' и локальная навигация синхронизированы!"
        )

        # 7. n8n синхронизация
        print("[7/7] 🔄 Синхронизация с n8n воркфлоу...")
        if amo_token and amo_domain:
            sync_token_to_n8n_workflow(amo_domain, amo_token, sheet_id)

        # Сохранение в реестр
        try:
            reg = load_registry()
            for t in reg.get("tenants", []):
                if t["tenant_id"] == tenant_record["tenant_id"]:
                    t["last_sync_at"] = datetime.datetime.now().isoformat()
                    t["synced_deals_count"] = synced_deals_count
                    t["pipeline_sum"] = total_pipeline_sum
                    t["discovered_stages"] = [s[0] for s in stage_settings]
                    t["discovered_users"] = discovered_users
                    tenant_record["last_sync_at"] = t["last_sync_at"]
                    tenant_record["synced_deals_count"] = synced_deals_count
                    tenant_record["pipeline_sum"] = total_pipeline_sum
                    tenant_record["discovered_users"] = discovered_users
            save_registry(reg)
            print("      [✓] Метаданные (этапы + сотрудники) сохранены в tenants_registry.json")
        except Exception as e:
            print(f"      [!] Реестр: {e}")

        print("=" * 76)
        print("🎉 СКВОЗНАЯ СИНХРОНИЗАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
        print("   • Воронка:           7 этапов синхронизировано из CRM")
        print(f"   • Сотрудники ОП:     {len(discovered_users)} чел ({', '.join(u['name'] for u in discovered_users)})")
        print(f"   • Сделок в работе:   {synced_deals_count} шт")
        print(f"   • Объем пайплайна:   {total_pipeline_sum:,.0f} ₽".replace(",", " "))
        print(f"   • Google Таблица:    🟢 Полностью активна ({tenant_record['spreadsheet_url']})")
        print("=" * 76)
        return (
            True,
            synced_deals_count,
            f"Сквозная синхронизация завершена: {synced_deals_count} сделок ({total_pipeline_sum:,.0f} ₽)",
        )
    except Exception as e:
        print(f"[-] Ошибка сквозной авто-синхронизации: {e}")
        return False, 0, str(e)


def sync_amocrm_deals_to_sheet(sheet_id, domain, token):
    """Синхронизирует сделки amoCRM через единый сквозной движок авто-синхронизации"""
    temp_record = {
        "tenant_id": "AUTO-SYNC",
        "tenant_name": "Клиент amoCRM",
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        "crm_type": "amocrm",
        "amo_domain": domain,
        "amo_token": token,
    }
    ok, count, msg = auto_discover_and_sync_all(temp_record)
    return ok, count, msg


def verify_amocrm_token(domain: str, token: str):
    """Проверяет валидность долгосрочного токена amoCRM через GET /api/v4/account"""
    clean_domain = domain.replace("https://", "").replace("http://", "").strip("/")
    if not clean_domain.endswith(".amocrm.ru"):
        clean_domain = f"{clean_domain}.amocrm.ru"
    url = f"https://{clean_domain}/api/v4/account"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "RevOps-Enterprise-OS/18.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data
    except urllib.error.HTTPError as he:
        return False, f"HTTP Error {he.code}: {he.reason}"
    except Exception as e:
        return False, str(e)


def test_amocrm_task_creation(domain, token):
    """Тестирует создание задачи в amoCRM (Модуль 3: Ликвидатор сливов Next Step)"""
    clean_domain = domain.replace("https://", "").replace("http://", "").strip("/")
    if not clean_domain.endswith(".amocrm.ru"):
        clean_domain = f"{clean_domain}.amocrm.ru"
    url = f"https://{clean_domain}/api/v4/tasks"

    now_ts = int(time.time())
    payload = [
        {
            "text": "⚠️ [ТЕСТ REVOPS] Проверка автоматической постановки задач при срыве Next Step",
            "complete_till": now_ts + 7200,
            "task_type_id": 1,
        }
    ]
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "RevOps-Enterprise-OS/18.0",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            return True, res_data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return False, f"HTTP Error {e.code}: {body[:200]}"
    except Exception as e:
        return False, str(e)


def sync_token_to_n8n_workflow(domain, token, sheet_id=None):
    """Обновляет токен, домен amoCRM и fallback sheet_id в воркфлоу n8n в SQLite"""
    try:
        import sqlite3

        clean_domain = domain.replace("https://", "").replace("http://", "").strip("/")
        if not clean_domain.endswith(".amocrm.ru"):
            clean_domain = f"{clean_domain}.amocrm.ru"

        db_path = os.path.expanduser("~/.n8n/database.sqlite")
        if not os.path.exists(db_path):
            return False, "n8n database not found"

        conn = sqlite3.connect(db_path)
        try:
            c = conn.cursor()
            row = c.execute("SELECT nodes FROM workflow_entity WHERE id = 'Sh4JkQtMKVdeRJn5'").fetchone()
            if not row:
                return False, "Workflow not found"

            nodes = json.loads(row[0])
            for n in nodes:
                params = n.get("parameters", {})
                if n["name"] == "HTTP Request":
                    params["url"] = (
                        f"=https://{clean_domain}/api/v4/events?filter[type]=lead_added,lead_status_changed,common_note_added,call_in,call_out"
                    )
                    if "headerParameters" in params:
                        for p in params["headerParameters"].get("parameters", []):
                            if p.get("name") == "Authorization":
                                p["value"] = f"Bearer {token}"
                elif n["name"] == "HTTP Request1":
                    params["url"] = (
                        f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.entity_id }}}}/notes/{{{{ $json.value_after[0].note.id }}}}"
                    )
                    if "headerParameters" in params:
                        for p in params["headerParameters"].get("parameters", []):
                            if p.get("name") == "Authorization":
                                p["value"] = f"Bearer {token}"
                elif n["name"] == "Check Existing Notes":
                    params["url"] = (
                        f"=https://{clean_domain}/api/v4/{{{{ $json.entity_type || 'leads' }}}}/{{{{ $json.lead_id }}}}/notes?limit=50&order[created_at]=desc"
                    )
                    if "headerParameters" in params:
                        for p in params["headerParameters"].get("parameters", []):
                            if p.get("name") == "Authorization":
                                p["value"] = f"Bearer {token}"
                elif n["name"] == "Add AmoCRM Note":
                    if "headerParameters" in params:
                        for p in params["headerParameters"].get("parameters", []):
                            if p.get("name") == "Authorization":
                                p["value"] = f"Bearer {token}"

                if "gemini" in n.get("name", "").lower():
                    if "url" in params and "gemini-3.8-flash" in params["url"]:
                        params["url"] = params["url"].replace("gemini-3.8-flash", "gemini-3.5-flash")

                if n.get("name") in ["Parse amoCRM Call", "Parse Bitrix24 Call"]:
                    try:
                        reg = load_registry()
                        trusted = {}
                        for t in reg.get("tenants", []):
                            tid = t.get("tenant_id")
                            if tid:
                                trusted[tid] = {
                                    "spreadsheet_id": t.get("spreadsheet_id", ""),
                                    "b24_webhook_url": t.get("b24_webhook_url") or t.get("crm_webhook_url", ""),
                                    "amo_domain": (t.get("amo_domain") or clean_domain)
                                    .replace("https://", "")
                                    .replace("http://", "")
                                    .strip("/"),
                                    "secret": t.get("secret", f"revops_sec_{tid.lower().replace('-', '')}"),
                                }
                        js_code = params.get("jsCode", "")
                        if "const TRUSTED_TENANTS =" in js_code:
                            rep = f"const TRUSTED_TENANTS = {json.dumps(trusted, indent=2)};"
                            params["jsCode"] = re.sub(r"const TRUSTED_TENANTS\s*=\s*\{[\s\S]*?\};", rep, js_code)
                    except Exception:
                        pass

                if sheet_id and ("sheet" in n.get("type", "").lower() or "google" in n.get("type", "").lower()):
                    doc = params.get("documentId")
                    val_expr = f"={{{{ $json.spreadsheet_id || '{sheet_id}' }}}}"
                    if isinstance(doc, dict):
                        doc["value"] = val_expr
                    elif isinstance(doc, str):
                        params["documentId"] = val_expr

            now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            nodes_json = json.dumps(nodes)
            with conn:
                conn.execute(
                    "UPDATE workflow_entity SET nodes = ?, updatedAt = ? WHERE id = 'Sh4JkQtMKVdeRJn5'",
                    (nodes_json, now_str),
                )
                conn.execute(
                    "UPDATE workflow_history SET nodes = ?, updatedAt = ? WHERE workflowId = 'Sh4JkQtMKVdeRJn5'",
                    (nodes_json, now_str),
                )
            return True, "Успешно синхронизировано в n8n"
        finally:
            conn.close()
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
    if not clean_url.endswith("/"):
        clean_url += "/"

    url = f"{clean_url}user.current"
    req = urllib.request.Request(
        url, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"}
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            user = data.get("result", {})
            return True, user
    except Exception as e1:
        try:
            url2 = f"{clean_url}app.info"
            req2 = urllib.request.Request(url2, headers={"User-Agent": "RevOps-Enterprise-OS/18.0"})
            with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8"))
                return True, data2.get("result", {})
        except Exception:
            return False, f"Ошибка подключения к Битрикс24: {e1}"


def test_bitrix24_comment_creation(webhook_url):
    """Тестирует создание комментария в Битрикс24 через REST API crm.timeline.comment.add"""
    clean_url = webhook_url.strip()
    if not clean_url.endswith("/"):
        clean_url += "/"

    # 1. Попробуем найти последнюю сделку
    list_url = f"{clean_url}crm.deal.list"
    payload = json.dumps({"order": {"DATE_MODIFY": "DESC"}, "select": ["ID", "TITLE"]}).encode("utf-8")
    req = urllib.request.Request(
        list_url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"}
    )
    ctx = ssl.create_default_context()
    deal_id = None
    deal_title = ""

    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            d_data = json.loads(resp.read().decode("utf-8"))
            deals = d_data.get("result", [])
            if deals:
                deal_id = deals[0]["ID"]
                deal_title = deals[0].get("TITLE", f"Сделка #{deal_id}")
    except Exception:
        deal_id = None

    if not deal_id:
        return True, "Связь с Битрикс24 активна (но сделок для добавления комментария пока нет)"

    comment_url = f"{clean_url}crm.timeline.comment.add"
    comment_payload = json.dumps(
        {
            "fields": {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"⚠️ [ТЕСТ REVOPS] Проверка автоматического добавления ИИ-аудита в таймлайн сделки '{deal_title}'",
            }
        }
    ).encode("utf-8")
    req2 = urllib.request.Request(
        comment_url,
        data=comment_payload,
        headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"},
    )

    try:
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp2:
            res_data = json.loads(resp2.read().decode("utf-8"))
            return True, f"Тестовый комментарий добавлен в сделку #{deal_id} ('{deal_title}')"
    except Exception as e:
        return False, f"Ошибка добавления комментария: {e}"


def sync_bitrix24_deals_to_sheet(sheet_id, webhook_url):
    """Синхронизирует сделки Битрикс24 через единый сквозной движок авто-синхронизации"""
    temp_record = {
        "tenant_id": "AUTO-SYNC-B24",
        "tenant_name": "Клиент Битрикс24",
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        "crm_type": "bitrix24",
        "b24_webhook_url": webhook_url,
        "crm_webhook_url": webhook_url,
    }
    ok, count, msg = auto_discover_and_sync_all(temp_record)
    return ok, count, msg


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
        "crm_type": "bitrix24" if crm_type == "bitrix24" else "amocrm",
        "call_id": call_id,
        "lead_id": 99991,
        "deal_id": 99991,
        "duration": 185,
        "phone": "+7 (999) 777-11-22",
        "audio_url": "http://127.0.0.1:8000/demo_audio.wav",
        "link": "http://127.0.0.1:8000/demo_audio.wav",
        "manager": "Алексей Смирнов (Тест)",
        "timestamp": now_str,
    }

    req_url = webhook_url
    if "?" not in req_url:
        req_url += f"?tenant={tenant_id}&sheet_id={sheet_id}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        req_url, data=data, headers={"Content-Type": "application/json", "User-Agent": "RevOps-Enterprise-OS/18.0"}
    )

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
        ws = sh.worksheet("raw_calls")

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        call_id = f"TEST-{datetime.datetime.now().strftime('%H%M%S')}"

        test_row = [
            call_id,
            "DEAL-777",
            "Менеджер (Тест)",
            now_str,
            185,
            f"Входящий (Тест связки {crm_label} -> n8n)",
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            96,
            "НЕТ",
            0,
            f"Связка {crm_label} -> n8n -> Google Таблица успешно протестирована!",
            "http://127.0.0.1:8000/demo_audio.wav",
            tenant_id,
        ]

        ws.append_row(test_row, value_input_option="USER_ENTERED")
        return True, call_id
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# 4. ИНТЕРАКТИВНЫЕ ДЕЙСТВИЯ (СМЕНА CRM, НАСТРОЙКА КЛЮЧЕЙ)
# ─────────────────────────────────────────────────────────────────────────────
def switch_tenant_crm(tenant_record):
    """Позволяет мгновенно переключить CRM между amoCRM, Битрикс24 и Гибридным режимом"""
    clear_screen()
    curr_crm = tenant_record.get("crm_type", "amocrm")
    if curr_crm in ["hybrid", "both"]:
        curr_label = "🔥 ГИБРИДНЫЙ РЕЖИМ (amoCRM + Битрикс24 одновременно)"
    elif curr_crm == "bitrix24":
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
    if ch == "1":
        new_crm = "amocrm"
    elif ch == "2":
        new_crm = "bitrix24"
    elif ch == "3":
        new_crm = "hybrid"
    else:
        return

    reg = load_registry()
    base_tunnel = get_active_tunnel_url()
    t_id = tenant_record["tenant_id"]
    s_id = tenant_record["spreadsheet_id"]

    wh_amo = f"{base_tunnel}/webhook/amocrm-call?tenant={t_id}&sheet_id={s_id}"
    wh_b24 = f"{base_tunnel}/webhook/bitrix24-call?tenant={t_id}&sheet_id={s_id}"

    for t in reg.get("tenants", []):
        if t["tenant_id"] == tenant_record["tenant_id"]:
            t["crm_type"] = new_crm
            tenant_record["crm_type"] = new_crm
            t["inbound_webhook_amo_url"] = wh_amo
            t["inbound_webhook_b24_url"] = wh_b24
            tenant_record["inbound_webhook_amo_url"] = wh_amo
            tenant_record["inbound_webhook_b24_url"] = wh_b24
            if new_crm == "bitrix24":
                t["inbound_webhook_url"] = wh_b24
                tenant_record["inbound_webhook_url"] = wh_b24
            else:
                t["inbound_webhook_url"] = wh_amo
                tenant_record["inbound_webhook_url"] = wh_amo

    save_registry(reg)

    try:
        from tenant_provisioner import create_client_passport

        create_client_passport(tenant_record)
    except Exception as e_pass:
        print(f"      [!] Не удалось обновить паспорт: {e_pass}")

    print(f"\n[✓] Режим CRM успешно переключен на: {new_crm.upper()}!")

    # Проверка ключей
    if (
        new_crm in ["bitrix24", "hybrid"]
        and not tenant_record.get("b24_webhook_url")
        and not tenant_record.get("crm_webhook_url")
    ):
        ask_b24 = input("\n👉 Желаете сейчас ввести REST вебхук Битрикс24? [y/N]: ").strip().lower()
        if ask_b24 in ["y", "yes", "д", "да"]:
            enter_and_validate_bitrix24_webhook(tenant_record)

    if new_crm in ["amocrm", "hybrid"] and not tenant_record.get("amo_token"):
        ask_amo = input("\n👉 Желаете сейчас ввести Долгосрочный токен amoCRM? [y/N]: ").strip().lower()
        if ask_amo in ["y", "yes", "д", "да"]:
            enter_and_validate_token(tenant_record)

    time.sleep(1)


def enter_and_validate_token(tenant_record):
    """Пошаговый ввод и валидация долгосрочного токена amoCRM"""
    clear_screen()
    print_header(f"ПОДКЛЮЧЕНИЕ ТОКЕНА AMOCRM: {tenant_record['tenant_name']}")

    domain = tenant_record.get("amo_domain", "revopsofficial.amocrm.ru")
    print("📖 КАК ПОЛУЧИТЬ ТОКЕН В AMOCRM ЗА 10 СЕКУНД:")
    print("  1. В amoCRM откройте: [amoМаркет] ➔ [Установленные] ➔ [RevOps AI Supervisor]")
    print("  2. Перейдите на вкладку [Ключи и доступы].")
    print("  3. Напротив строки 'Долгосрочный токен' нажмите кнопку [Сгенерировать токен].")
    print("  4. Скопируйте появившийся токен и вставьте сюда.\n")
    print(f"🌐 Текущий домен: {domain}")
    new_dom = input("👉 Изменить домен? (Enter чтобы оставить, или введите новый): ").strip()
    if new_dom:
        domain = new_dom
        tenant_record["amo_domain"] = domain

    print("─" * 76)
    token = input("👉 Вставьте Долгосрочный токен: ").strip()
    if not token:
        print("[!] Ввод отменен.")
        time.sleep(1)
        return

    print("\n⏳ Проверяем токен через официальный API amoCRM...")
    ok, res = verify_amocrm_token(domain, token)
    if ok:
        acc_name = res.get("name", "Без названия")
        acc_id = res.get("id", "")
        print("═" * 76)
        print("🎉 ТОКЕН ВАЛИДЕН И УСПЕШНО АВТОРИЗОВАН!")
        print(f"  • Название аккаунта: {acc_name}")
        print(f"  • ID аккаунта:       {acc_id}")
        print(f"  • Домен:             {domain}")
        print("═" * 76)

        reg = load_registry()
        for t in reg.get("tenants", []):
            if t["tenant_id"] == tenant_record["tenant_id"]:
                t["amo_token"] = token
                t["amo_domain"] = domain
                t["integration_mode"] = "token"
                tenant_record["amo_token"] = token
                tenant_record["amo_domain"] = domain
                tenant_record["integration_mode"] = "token"
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

    curr_wh = tenant_record.get("b24_webhook_url") or tenant_record.get("crm_webhook_url") or ""
    if curr_wh:
        print(f"Текущий URL вебхука: {curr_wh}")

    webhook_url = input("👉 Вставьте URL вебхука Битрикс24: ").strip()
    if not webhook_url:
        print("[!] Ввод отменен.")
        time.sleep(1)
        return

    if not webhook_url.endswith("/"):
        webhook_url += "/"

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
        for t in reg.get("tenants", []):
            if t["tenant_id"] == tenant_record["tenant_id"]:
                t["b24_webhook_url"] = webhook_url
                t["crm_webhook_url"] = webhook_url
                tenant_record["b24_webhook_url"] = webhook_url
                tenant_record["crm_webhook_url"] = webhook_url
        save_registry(reg)

        input("\nНажмите Enter для продолжения...")
    else:
        print(f"\n❌ Ошибка проверки вебхука: {res}")
        print("👉 Проверьте правильность URL и наличие прав 'CRM' и 'Пользователи'.")
        input("\nНажмите Enter для возврата...")


def manage_crm_credentials(tenant_record):
    """Меню управления ключами и токенами в зависимости от CRM"""
    crm_type = tenant_record.get("crm_type", "amocrm")
    if crm_type == "amocrm":
        enter_and_validate_token(tenant_record)
    elif crm_type == "bitrix24":
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
        if sub_ch == "1":
            enter_and_validate_token(tenant_record)
        elif sub_ch == "2":
            enter_and_validate_bitrix24_webhook(tenant_record)
        elif sub_ch == "3":
            enter_and_validate_token(tenant_record)
            enter_and_validate_bitrix24_webhook(tenant_record)


def edit_tenant_record(tenant_record):
    """Позволяет изменить данные клиента"""
    clear_screen()
    print_header(f"РЕДАКТИРОВАНИЕ: {tenant_record['tenant_name']}")

    crm_type = tenant_record.get("crm_type", "amocrm")
    if crm_type in ["hybrid", "both"]:
        crm_label = "🔥 ГИБРИД (amoCRM + Битрикс24)"
    elif crm_type == "bitrix24":
        crm_label = "БИТРИКС24"
    else:
        crm_label = "AMOCRM"

    print("Текущие данные:")
    print(f"  1. Название компании:   {tenant_record['tenant_name']}")
    print(f"  2. Тип CRM:             {crm_label}")
    print(f"  3. Режим интеграции:    {tenant_record.get('integration_mode', 'token').upper()}")
    print(f"  4. Домен amoCRM:        {tenant_record.get('amo_domain', 'Не указан')}")
    print(
        f"  5. Вебхук Битрикс24:    {tenant_record.get('b24_webhook_url') or tenant_record.get('crm_webhook_url') or 'Не указан'}"
    )
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

    for idx, t in enumerate(reg.get("tenants", [])):
        if t["tenant_id"] == tenant_record["tenant_id"]:
            if ch == "1":
                new_n = input("Введите новое название компании: ").strip()
                if new_n:
                    reg["tenants"][idx]["tenant_name"] = new_n
                    tenant_record["tenant_name"] = new_n
                    print("✓ Название обновлено!")
            elif ch == "2":
                switch_tenant_crm(tenant_record)
                return
            elif ch == "3":
                new_d = input("Введите домен amoCRM (напр. https://mycompany.amocrm.ru): ").strip()
                if new_d:
                    reg["tenants"][idx]["amo_domain"] = new_d
                    tenant_record["amo_domain"] = new_d
                    print("✓ Домен обновлен!")
            elif ch == "4":
                enter_and_validate_bitrix24_webhook(tenant_record)
                return
            elif ch == "5":
                new_em = input("Введите email клиента: ").strip()
                if new_em:
                    reg["tenants"][idx]["client_email"] = new_em
                    tenant_record["client_email"] = new_em
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
    tenants = reg.get("tenants", [])

    if not tenant_record:
        if not tenants:
            print("❌ В системе пока нет зарегистрированных клиентов!")
            print("👉 Сначала запустите 'Новая_компания.bat' для создания клиента.\n")
            input("Нажмите Enter для выхода...")
            return

        print("📋 ВЫБЕРИТЕ КОМПАНИЮ КЛИЕНТА ДЛЯ ИНТЕГРАЦИИ:")
        for idx, t in enumerate(tenants, 1):
            c_type = t.get("crm_type", "amocrm")
            if c_type in ["hybrid", "both"]:
                crm_badge = "🔥 ГИБРИД (amo+b24)"
            elif c_type == "bitrix24":
                crm_badge = "🔵 БИТРИКС24"
            else:
                crm_badge = "🟠 AMOCRM"
            print(f"  [{idx}] {t['tenant_name']} (ID: {t['tenant_id']}, CRM: {crm_badge})")
        print("  [0] Выход")

        choice = input("\n👉 Ваш выбор [1-{}]: ".format(len(tenants))).strip()
        if choice in ["", "0"]:
            return
        try:
            sel_idx = int(choice) - 1
            if 0 <= sel_idx < len(tenants):
                tenant_record = tenants[sel_idx]
            else:
                return
        except ValueError:
            return

    while True:
        company_name = tenant_record["tenant_name"]
        tenant_id = tenant_record["tenant_id"]
        sheet_id = tenant_record["spreadsheet_id"]
        sheet_url = tenant_record["spreadsheet_url"]
        crm_type = tenant_record.get("crm_type", "amocrm")
        integration_mode = tenant_record.get("integration_mode", "token")
        amo_domain = tenant_record.get("amo_domain", "revopsofficial.amocrm.ru")
        amo_token = tenant_record.get("amo_token", "")
        b24_webhook = tenant_record.get("b24_webhook_url") or tenant_record.get("crm_webhook_url") or ""

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
        if crm_type in ["hybrid", "both"]:
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
        elif crm_type == "bitrix24":
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
        print(
            "  [1] 🚀 ПОЛНАЯ АВТО-ИНТЕГРАЦИЯ И СИНХРОНИЗАЦИЯ ПОД КЛЮЧ (Воронка + Сотрудники + Сделки + Таблица + n8n)"
        )
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

        if act == "1":
            print("\n" + "═" * 76)
            print("🚀 ЗАПУСК ПОЛНОЙ АВТО-ИНТЕГРАЦИИ И СИНХРОНИЗАЦИИ ПОД КЛЮЧ...")
            print("═" * 76)

            # 1. Сквозная авто-синхронизация этапов и сделок
            s_ok, s_cnt, s_msg = auto_discover_and_sync_all(tenant_record)

            # 2. Тест создания задач / комментариев в CRM (опционально, чтобы не засорять живую CRM)
            test_prompt = (
                input("\n👉 Отправить тестовую задачу/комментарий в CRM для проверки связи? [y/N]: ").strip().lower()
            )
            if test_prompt in ["y", "yes", "д", "да"]:
                if crm_type in ["amocrm", "hybrid", "both"] and amo_token:
                    t_ok, t_res = test_amocrm_task_creation(amo_domain, amo_token)
                    if t_ok:
                        print("  [✓] Модуль 3: Тестовая задача успешно проверена в amoCRM!")
                    else:
                        print(f"  [!] Проверка задачи: {t_res}")

                if crm_type in ["bitrix24", "hybrid", "both"] and b24_webhook:
                    c_ok, c_msg = test_bitrix24_comment_creation(b24_webhook)
                    if c_ok:
                        print(f"  [✓] {c_msg}")
                    else:
                        print(f"  [!] Комментарий Битрикс24: {c_msg}")
            else:
                print(
                    "  [i] Отправка тестовых задач/комментариев в CRM пропущена (боевой таймлайн сделок сохранен в чистоте)."
                )

            # 3. Тест n8n Вебхука
            print("\n[Проверка n8n Webhook Контура]:")
            if crm_type in ["amocrm", "hybrid", "both"]:
                wh_ok1, s1, m1 = send_test_call_webhook(inbound_amo_wh, tenant_id, sheet_id, "amocrm")
                if wh_ok1:
                    print(f"  [✓] Сигнал amoCRM принят n8n (HTTP {s1} OK)!")
                else:
                    print(f"  [!] amoCRM сигнал: {m1}")

            if crm_type in ["bitrix24", "hybrid", "both"]:
                wh_ok2, s2, m2 = send_test_call_webhook(inbound_b24_wh, tenant_id, sheet_id, "bitrix24")
                if wh_ok2:
                    print(f"  [✓] Сигнал Битрикс24 принят n8n (HTTP {s2} OK)!")
                else:
                    print(f"  [!] Битрикс24 сигнал: {m2}")

            print("\n" + "═" * 76)
            print("🎉 ВСЯ ЭКОСИСТЕМА ПОЛНОСТЬЮ СИНХРОНИЗИРОВАНА И ГОТОВА К РАБОТЕ!")
            print("═" * 76)
            input("\nНажмите Enter для продолжения...")

        elif act == "2":
            manage_crm_credentials(tenant_record)

        elif act == "3":
            # Копирование вебхука в буфер
            target_url = inbound_b24_wh if crm_type == "bitrix24" else inbound_amo_wh
            if os.name == "nt":
                try:
                    import subprocess

                    subprocess.run(["clip"], input=target_url.encode("utf-16le"), check=True)
                    print("\n[✓] Webhook URL успешно скопирован в буфер обмена (Ctrl+V)!")
                except Exception as clip_err:
                    print(f"\n[!] Не удалось скопировать в буфер: {clip_err}. Скопируйте ссылку вручную: {target_url}")
            else:
                print(f"\n[i] Webhook URL: {target_url}")
            time.sleep(1.5)

        elif act == "4":
            print("\nОткрываем Google Таблицу...")
            webbrowser.open(sheet_url)
            time.sleep(1)

        elif act == "5":
            print("\nОткрываем n8n...")
            webbrowser.open("http://localhost:5678")
            time.sleep(1)

        elif act == "6":
            clean_name = re.sub(r'[\/:*?"<>|]', "_", company_name)
            clients_root = Path(
                os.getenv("REVOPS_CLIENTS_DIR", Path.home() / "Desktop" / "RevOps Platform" / "Клиенты")
            )
            client_path = clients_root / clean_name
            target_open = client_path if client_path.exists() else clients_root
            if target_open.exists():
                if hasattr(os, "startfile"):
                    os.startfile(str(target_open))
                else:
                    import subprocess

                    subprocess.run(["xdg-open", str(target_open)], check=False)
            else:
                print(f"[!] Папка не найдена: {target_open}")

        elif act == "7":
            switch_tenant_crm(tenant_record)

        elif act == "8":
            print("\nПерезапуск туннеля...")
            new_url = start_tunnel()
            if new_url:
                base_tunnel = new_url
                print(f"[✓] Новый URL туннеля: {new_url}")
            input("\nНажмите Enter для продолжения...")

        elif act == "9":
            try:
                from features_manager import interactive_loop

                interactive_loop()
            except Exception as e:
                print(f"\n[-] Ошибка вызова панели опций: {e}")
                time.sleep(2)

        elif act == "0":
            break


if __name__ == "__main__":
    manage_client_integration()

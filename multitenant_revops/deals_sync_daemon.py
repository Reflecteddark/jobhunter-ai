"""
RevOps Enterprise OS V18.0 - Background Deals Synchronization Daemon (Auto-Sync 24/7)
Автоматическая фоновая сквозная синхронизация сделок, воронки, сотрудников и Google Таблиц
из amoCRM и Битрикс24 каждые 3 минуты с полной пагинацией и отсутствием хардкодов.
"""
import os
import sys
import time
import json
import datetime
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / 'deals_sync_daemon.pid'
LOG_FILE = BASE_DIR / 'deals_sync.log'

# Импорт сквозного движка синхронизации
try:
    from crm_integration_manager import (
        auto_discover_and_sync_all,
        load_registry,
        find_registry_file,
        find_service_account,
        sanitize_sheet_val
    )
except ImportError:
    sys.path.insert(0, str(BASE_DIR))
    from crm_integration_manager import (
        auto_discover_and_sync_all,
        load_registry,
        find_registry_file,
        find_service_account,
        sanitize_sheet_val
    )

def prevent_windows_sleep():
    """Предотвращает переход Windows в спящий режим во время работы службы"""
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass

def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass

def sync_tenant_deals(tenant):
    """Синхронизирует конкретного клиента через единый сквозной движок"""
    tenant_id = tenant.get('tenant_id', 'UNKNOWN')
    tenant_name = tenant.get('tenant_name', 'Без названия')
    amo_token = tenant.get('amo_token')
    b24_webhook = tenant.get('b24_webhook_url') or tenant.get('crm_webhook_url')

    if not amo_token and not b24_webhook:
        return

    try:
        ok, count, msg = auto_discover_and_sync_all(tenant)
        if ok:
            log(f"[{tenant_id} - {tenant_name}] [✓] {msg}")
        else:
            log(f"[{tenant_id} - {tenant_name}] [!] {msg}")
    except Exception as e:
        log(f"[{tenant_id} - {tenant_name}] [-] Ошибка синхронизации: {e}")

def run_sync_cycle():
    """Один полный цикл синхронизации по всем клиентам в реестре"""
    reg_file = find_registry_file()
    if not reg_file or not os.path.exists(reg_file):
        log(f"[-] Реестр tenants_registry.json не найден (проверьте {reg_file})")
        return

    try:
        data = load_registry()
    except Exception as e:
        log(f"[-] Ошибка чтения реестра: {e}")
        return

    tenants = data.get('tenants', [])
    if not tenants:
        log("[i] В реестре нет клиентов для синхронизации.")
        return

    for t in tenants:
        try:
            sync_tenant_deals(t)
        except Exception as e:
            log(f"[-] Ошибка синхронизации клиента {t.get('tenant_id')}: {e}")

def main():
    prevent_windows_sleep()
    try:
        with open(PID_FILE, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log(f"[!] Не удалось записать PID-файл: {e}")

    log("🚀 Демон фоновой синхронизации сделок RevOps (24/7) запущен.")
    interval_sec = int(os.getenv("REVOPS_SYNC_INTERVAL", "180"))  # каждые 3 минуты по умолчанию

    while True:
        try:
            prevent_windows_sleep()
            run_sync_cycle()
        except Exception as e:
            log(f"[-] Непредвиденная ошибка в основном цикле: {e}")
        time.sleep(interval_sec)

if __name__ == '__main__':
    main()

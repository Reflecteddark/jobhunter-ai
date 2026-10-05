"""
RevOps Enterprise OS - Service Fleet Manager
Управление жизненным циклом фоновых служб (n8n + Faster-Whisper).
"""
import os
import sys
import time
import subprocess
import urllib.request
import json

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

WHISPER_PORT = 8000
N8N_PORT = 5678

WHISPER_DIR = r"C:\Users\strel\.gemini\antigravity\scratch\transcriber_service"
WHISPER_PYTHON = r"C:\Users\strel\.gemini\antigravity\scratch\game_vision_analytics\.venv\Scripts\python.exe"
N8N_HEADLESS = r"C:\Users\strel\.n8n\start_n8n_headless.ps1"

def prevent_windows_sleep():
    if os.name == 'nt':
        try:
            import ctypes
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except:
            pass

def is_port_open(port):
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except:
        return False

def check_whisper_health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{WHISPER_PORT}/health", timeout=2) as resp:
            return resp.status == 200
    except:
        return False

def check_n8n_health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{N8N_PORT}/healthz", timeout=2) as resp:
            return resp.status == 200
    except:
        return False

def start_services():
    prevent_windows_sleep()
    print("\n" + "═"*60)
    print("🚀 REVOPS ENTERPRISE OS — ЗАПУСК ФОНОВЫХ СЛУЖБ")
    print("═"*60 + "\n")

    # 1. Faster-Whisper
    if is_port_open(WHISPER_PORT) and check_whisper_health():
        print(f"  [✓] Faster-Whisper уже работает на порту {WHISPER_PORT}")
    else:
        print(f"  [+] Запуск Faster-Whisper (порт {WHISPER_PORT})...")
        if os.path.exists(WHISPER_PYTHON):
            subprocess.Popen(
                [WHISPER_PYTHON, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(WHISPER_PORT)],
                cwd=WHISPER_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            # Wait up to 10s for startup
            for _ in range(10):
                time.sleep(1)
                if check_whisper_health():
                    break
            if check_whisper_health():
                print(f"  [✓] Faster-Whisper успешно запущен и готов к работе!")
            else:
                print(f"  [!] Faster-Whisper запускается (инициализация модели)...")
        else:
            print(f"  [-] Ошибка: Python окружение Faster-Whisper не найдено по пути {WHISPER_PYTHON}")

    # 2. n8n
    if is_port_open(N8N_PORT) and check_n8n_health():
        print(f"  [✓] n8n Orchestrator уже работает на порту {N8N_PORT}")
    else:
        print(f"  [+] Запуск n8n Orchestrator (порт {N8N_PORT})...")
        if os.path.exists(N8N_HEADLESS):
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", N8N_HEADLESS], capture_output=True)
            for _ in range(20):
                time.sleep(1)
                if check_n8n_health():
                    break
            if check_n8n_health():
                print(f"  [✓] n8n Orchestrator успешно запущен!")
            else:
                print(f"  [!] n8n инициализируется в фоне...")
        else:
            print(f"  [-] Ошибка: файл запуска {N8N_HEADLESS} не найден")

    # 3. Secure Webhook Tunnel
    try:
        from tunnel_manager import start_tunnel, get_active_tunnel_url, is_cloudflared_running
        if is_cloudflared_running():
            print(f"  [✓] Защищённый HTTPS-туннель уже активен: {get_active_tunnel_url()}")
        else:
            print("  [+] Запуск защищённого HTTPS-туннеля (для amoCRM / Битрикс24)...")
            tunnel_url = start_tunnel()
            if tunnel_url:
                print(f"  [✓] Защищённый HTTPS-туннель успешно поднят: {tunnel_url}")
            else:
                print("  [i] Локальный режим (без внешнего туннеля)")
    except Exception as e:
        print(f"  [!] Заметка по туннелю: {e}")

    # 4. Background Deals Sync Daemon (Auto-Sync 24/7)
    daemon_script = os.path.join(os.path.dirname(__file__), 'deals_sync_daemon.py')
    pid_file = os.path.join(os.path.dirname(__file__), 'deals_sync_daemon.pid')
    daemon_running = False
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as pf:
                d_pid = int(pf.read().strip())
            chk = subprocess.run(["tasklist", "/FI", f"PID eq {d_pid}"], capture_output=True, text=True)
            if str(d_pid) in chk.stdout:
                daemon_running = True
        except:
            pass

    if daemon_running:
        print("  [✓] Демон авто-синхронизации сделок amoCRM (24/7) уже работает")
    else:
        print("  [+] Запуск демона авто-синхронизации сделок (amoCRM ➔ raw_deals каждые 3 мин)...")
        if os.path.exists(daemon_script):
            py_exe = sys.executable
            subprocess.Popen(
                [py_exe, daemon_script],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            print("  [✓] Демон синхронизации сделок успешно запущен!")

    print("\n" + "═"*60)
    print("✨ СТАТУС СИСТЕМЫ:")
    w_ok = "🟢 АКТИВЕН" if check_whisper_health() else "🟡 ЗАПУСКАЕТСЯ"
    n_ok = "🟢 АКТИВЕН" if check_n8n_health() else "🟡 ЗАПУСКАЕТСЯ"
    try:
        from tunnel_manager import get_active_tunnel_url
        cf_url = get_active_tunnel_url()
    except:
        cf_url = "http://localhost:5678"
    print(f"  • Faster-Whisper (Речь -> Текст): {w_ok} (http://127.0.0.1:{WHISPER_PORT})")
    print(f"  • n8n Orchestrator (Вебхуки):    {n_ok} (http://127.0.0.1:{N8N_PORT})")
    print(f"  • Авто-синхронизация сделок:     🟢 24/7 (каждые 3 мин в raw_deals)")
    print(f"  • Защищённый Webhook URL:        🌐 {cf_url}")
    print(f"  • Gemini 3.8 Flash AI Аудит:     🟢 ПОДКЛЮЧЕН")
    print("═"*60 + "\n")

def stop_services():
    print("\n" + "═"*60)
    print("🛑 REVOPS ENTERPRISE OS — ОСТАНОВКА СЛУЖБ")
    print("═"*60 + "\n")

    # Stop n8n (only the PID listening on port 5678)
    try:
        netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        pids = set()
        for line in netstat.splitlines():
            if f":{N8N_PORT} " in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            print(f"  [✓] Служба n8n Orchestrator (PID {pid}) остановлена")
        if not pids:
            print("  [i] n8n Orchestrator не был запущен")
    except Exception as e:
        print(f"  [!] Ошибка остановки n8n: {e}")

    # Stop tunnel
    try:
        from tunnel_manager import stop_tunnel
        stop_tunnel()
        print("  [✓] Защищённый HTTPS-туннель остановлен")
    except Exception as e:
        pass

    # Stop Deals Sync Daemon
    pid_file = os.path.join(os.path.dirname(__file__), 'deals_sync_daemon.pid')
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as pf:
                d_pid = int(pf.read().strip())
            subprocess.run(["taskkill", "/F", "/PID", str(d_pid)], capture_output=True)
            print(f"  [✓] Демон авто-синхронизации сделок (PID {d_pid}) остановлен")
        except:
            pass
        try: os.remove(pid_file)
        except: pass

    # Stop uvicorn/python listening on port 8000
    try:
        netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        pids = set()
        for line in netstat.splitlines():
            if f":{WHISPER_PORT} " in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            print(f"  [✓] Служба Faster-Whisper (PID {pid}) остановлена")
        if not pids:
            print("  [i] Faster-Whisper не был запущен")
    except Exception as e:
        print(f"  [!] Ошибка остановки Faster-Whisper: {e}")

    print("\n" + "═"*60)
    print("✨ Все локальные службы RevOps успешно остановлены.")
    print("═"*60 + "\n")

if __name__ == '__main__':
    action = sys.argv[1].lower() if len(sys.argv) > 1 else 'status'
    if action == 'start':
        start_services()
    elif action == 'stop':
        stop_services()
    else:
        print("Статус служб:")
        print("  Faster-Whisper:", check_whisper_health())
        print("  n8n:", check_n8n_health())

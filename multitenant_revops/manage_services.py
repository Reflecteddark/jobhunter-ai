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
N8N_VBS = r"C:\Users\strel\.n8n\run_n8n_silent.vbs"

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
        if os.path.exists(N8N_VBS):
            subprocess.run(["wscript.exe", N8N_VBS], shell=True)
            for _ in range(15):
                time.sleep(1)
                if check_n8n_health():
                    break
            if check_n8n_health():
                print(f"  [✓] n8n Orchestrator успешно запущен!")
            else:
                print(f"  [!] n8n инициализируется в фоне...")
        else:
            print(f"  [-] Ошибка: файл запуска {N8N_VBS} не найден")

    print("\n" + "═"*60)
    print("✨ СТАТУС СИСТЕМЫ:")
    w_ok = "🟢 АКТИВЕН" if check_whisper_health() else "🟡 ЗАПУСКАЕТСЯ"
    n_ok = "🟢 АКТИВЕН" if check_n8n_health() else "🟡 ЗАПУСКАЕТСЯ"
    print(f"  • Faster-Whisper (Речь -> Текст): {w_ok} (http://127.0.0.1:{WHISPER_PORT})")
    print(f"  • n8n Orchestrator (Вебхуки):    {n_ok} (http://127.0.0.1:{N8N_PORT})")
    print(f"  • Gemini 3.8 Flash (Cloudflare): 🟢 ПОДКЛЮЧЕН")
    print("═"*60 + "\n")

def stop_services():
    print("\n" + "═"*60)
    print("🛑 REVOPS ENTERPRISE OS — ОСТАНОВКА СЛУЖБ")
    print("═"*60 + "\n")

    # Stop node (n8n)
    try:
        subprocess.run(["taskkill", "/F", "/IM", "node.exe"], capture_output=True, text=True)
        print("  [✓] Служба n8n (node.exe) остановлена")
    except Exception as e:
        print(f"  [!] Ошибка остановки n8n: {e}")

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

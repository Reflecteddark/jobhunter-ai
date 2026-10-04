"""
RevOps Platform V18.0 - Bulletproof Secure Webhook Tunnel Manager
Управление защищённым внешним HTTPS туннелем с автоматическим перезапуском при любых сбоях сети (Auto-healing daemon).
"""
import os
import sys
import time
import subprocess
import re
import urllib.request
import json

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_DIR = os.path.join(BASE_DIR, "cloudflared")
CLOUDFLARED_EXE = os.path.join(CLOUDFLARED_DIR, "cloudflared.exe")
TUNNEL_CONFIG_FILE = os.path.join(BASE_DIR, "tunnel_config.json")
TUNNEL_URL_FILE = os.path.join(BASE_DIR, "active_tunnel_url.txt")
TUNNEL_LOG = os.path.join(BASE_DIR, "tunnel.log")
PID_FILE = os.path.join(BASE_DIR, "tunnel_daemon.pid")

def load_tunnel_config():
    if os.path.exists(TUNNEL_CONFIG_FILE):
        try:
            with open(TUNNEL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"mode": "auto", "custom_url": "", "tunnel_token": ""}

def save_tunnel_config(cfg):
    with open(TUNNEL_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_active_tunnel_url():
    cfg = load_tunnel_config()
    if cfg.get("custom_url"):
        return cfg["custom_url"].rstrip('/')
    
    if os.path.exists(TUNNEL_URL_FILE):
        try:
            with open(TUNNEL_URL_FILE, 'r', encoding='utf-8') as f:
                url = f.read().strip()
                if url.startswith("http"):
                    return url.rstrip('/')
        except:
            pass
    return "http://localhost:5678"

def is_cloudflared_running():
    # Проверяем, запущен ли процесс ssh.exe
    try:
        res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ssh.exe"], capture_output=True, text=True, errors='ignore')
        if "ssh.exe" in res.stdout:
            return True
    except:
        pass
    try:
        res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"], capture_output=True, text=True, errors='ignore')
        if "cloudflared.exe" in res.stdout:
            return True
    except:
        pass
    return False

def stop_tunnel():
    # Останавливаем фонового демона если записан PID
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as pf:
                pid = int(pf.read().strip())
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        except:
            pass
        try: os.remove(PID_FILE)
        except: pass

    try:
        subprocess.run(["taskkill", "/F", "/IM", "ssh.exe"], capture_output=True)
    except:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
    except:
        pass

    if os.path.exists(TUNNEL_URL_FILE):
        try: os.remove(TUNNEL_URL_FILE)
        except: pass
    return True

def run_daemon():
    """Фоновый авто-перезапускаемый процесс для удержания туннеля 24/7"""
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except:
            pass

    with open(PID_FILE, 'w') as pf:
        pf.write(str(os.getpid()))

    while True:
        log_out = open(TUNNEL_LOG, "w", encoding="utf-8")
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-R", "80:localhost:5678",
            "nokey@localhost.run"
        ]
        try:
            proc = subprocess.Popen(ssh_cmd, stdout=log_out, stderr=log_out)
        except Exception as e:
            time.sleep(3)
            continue

        # Ожидаем появления ссылки
        start_t = time.time()
        while time.time() - start_t < 25:
            time.sleep(1)
            if os.path.exists(TUNNEL_LOG):
                try:
                    with open(TUNNEL_LOG, 'r', encoding='utf-8', errors='ignore') as lf:
                        content = lf.read()
                        match = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', content)
                        if match:
                            with open(TUNNEL_URL_FILE, 'w', encoding='utf-8') as uf:
                                uf.write(match.group(0))
                            break
                except:
                    pass

        # Ждём завершения процесса (если оборвётся интернет)
        proc.wait()
        time.sleep(2)

def start_tunnel():
    cfg = load_tunnel_config()
    token = cfg.get("tunnel_token", "").strip()

    if is_cloudflared_running():
        url = get_active_tunnel_url()
        if url and not url.startswith("http://localhost"):
            return url

    stop_tunnel()
    time.sleep(1)

    flags = 0
    if os.name == 'nt':
        flags = 0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    # 1. Если настроен Cloudflare Named Tunnel с токеном
    if token and os.path.exists(CLOUDFLARED_EXE):
        print("[+] Запуск постоянного Cloudflare Tunnel (Named Tunnel via Token)...")
        proc = subprocess.Popen(
            [CLOUDFLARED_EXE, "tunnel", "--protocol", "http2", "run", "--token", token],
            creationflags=flags
        )
        url = cfg.get("custom_url") or "https://revops-tunnel.cloudflare"
        with open(TUNNEL_URL_FILE, 'w', encoding='utf-8') as f:
            f.write(url)
        return url

    # 2. Иначе запускаем отказоустойчивый SSH-демон
    print("[+] Запуск отказоустойчивого HTTPS-туннеля (localhost.run)...")
    this_script = os.path.abspath(__file__)
    py_exe = r"C:\Python314\python.exe" if os.path.exists(r"C:\Python314\python.exe") else sys.executable

    subprocess.Popen(
        [py_exe, this_script, "--daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags
    )

    # Ожидаем появления адреса
    tunnel_url = None
    start_t = time.time()
    while time.time() - start_t < 20:
        time.sleep(1)
        if os.path.exists(TUNNEL_URL_FILE):
            try:
                with open(TUNNEL_URL_FILE, 'r', encoding='utf-8') as uf:
                    u = uf.read().strip()
                    if u.startswith("https://"):
                        tunnel_url = u
                        break
            except:
                pass

    if tunnel_url:
        print(f"[✓] Внешний HTTPS адрес туннеля активен: {tunnel_url}")
        return tunnel_url
    else:
        print("[-] Не удалось получить адрес внешнего туннеля за 20 секунд.")
        return None

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--daemon':
        run_daemon()
    else:
        arg = sys.argv[1].lower() if len(sys.argv) > 1 else 'status'
        if arg == 'start':
            start_tunnel()
        elif arg == 'stop':
            stop_tunnel()
        elif arg == 'url':
            print(get_active_tunnel_url())
        else:
            print("Status: Running" if is_cloudflared_running() else "Status: Stopped")
            print("Active URL:", get_active_tunnel_url())

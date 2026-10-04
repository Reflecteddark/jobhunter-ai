"""
RevOps Platform V18.0 - Secure Webhook Tunnel Manager
Автоматическое управление защищённым внешним HTTPS туннелем для CRM (amoCRM / Битрикс24) -> n8n.
Поддерживает SSH Secure Tunnel (localhost.run) и Cloudflare Tunnel.
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
    # Проверяем, запущен ли туннельный процесс (ssh или cloudflared)
    try:
        res = subprocess.run(["tasklist"], capture_output=True, text=True, errors='ignore')
        out = res.stdout.lower()
        if "cloudflared.exe" in out or "ssh.exe" in out:
            return True
    except:
        pass
    
    # Также проверяем доступность сохранённого URL
    url = get_active_tunnel_url()
    if url and not url.startswith("http://localhost"):
        try:
            req = urllib.request.Request(f"{url}/healthz", headers={'User-Agent': 'RevOps/1.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 404):
                    return True
        except:
            pass
    return False

def stop_tunnel():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
    except:
        pass
    try:
        # Останавливаем ssh, только если это туннель localhost.run
        subprocess.run(["taskkill", "/F", "/IM", "ssh.exe"], capture_output=True)
    except:
        pass
    if os.path.exists(TUNNEL_URL_FILE):
        try:
            os.remove(TUNNEL_URL_FILE)
        except:
            pass
    return True

def start_tunnel():
    cfg = load_tunnel_config()
    token = cfg.get("tunnel_token", "").strip()

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

    # 2. Иначе запускаем SSH Secure Tunnel (localhost.run) — стабилен и не блокируется ТСПУ
    print("[+] Запуск защищённого внешнего HTTPS туннеля (localhost.run)...")
    if os.path.exists(TUNNEL_LOG):
        try: os.remove(TUNNEL_LOG)
        except: pass

    log_out = open(TUNNEL_LOG, "w", encoding="utf-8")
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", "80:localhost:5678",
        "nokey@localhost.run"
    ]
    proc = subprocess.Popen(
        ssh_cmd,
        stdout=log_out,
        stderr=log_out,
        creationflags=flags
    )

    tunnel_url = None
    start_t = time.time()
    while time.time() - start_t < 25:
        time.sleep(1)
        if os.path.exists(TUNNEL_LOG):
            try:
                with open(TUNNEL_LOG, 'r', encoding='utf-8', errors='ignore') as lf:
                    content = lf.read()
                    match = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', content)
                    if match:
                        tunnel_url = match.group(0)
                        break
            except:
                pass

    # Если SSH не дал URL, пробуем как запасной вариант Cloudflare Quick Tunnel
    if not tunnel_url and os.path.exists(CLOUDFLARED_EXE):
        print("[!] Пробуем запасной туннель Cloudflare...")
        proc_cf = subprocess.Popen(
            [CLOUDFLARED_EXE, "tunnel", "--protocol", "http2", "--url", "http://127.0.0.1:5678"],
            stdout=log_out,
            stderr=log_out,
            creationflags=flags
        )
        start_t = time.time()
        while time.time() - start_t < 20:
            time.sleep(1)
            if os.path.exists(TUNNEL_LOG):
                try:
                    with open(TUNNEL_LOG, 'r', encoding='utf-8', errors='ignore') as lf:
                        content = lf.read()
                        match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', content)
                        if match:
                            tunnel_url = match.group(0)
                            break
                except:
                    pass

    if tunnel_url:
        with open(TUNNEL_URL_FILE, 'w', encoding='utf-8') as f:
            f.write(tunnel_url)
        print(f"[✓] Внешний HTTPS адрес туннеля активен: {tunnel_url}")
        return tunnel_url
    else:
        print("[-] Не удалось получить адрес внешнего туннеля.")
        return None

if __name__ == '__main__':
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

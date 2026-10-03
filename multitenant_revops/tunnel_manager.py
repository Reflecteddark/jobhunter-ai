"""
RevOps Platform V17.5 - Cloudflare Tunnel Manager
Автоматическое управление защищённым туннелем Cloudflare (HTTP/2 over TCP 443).
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

def load_tunnel_config():
    if os.path.exists(TUNNEL_CONFIG_FILE):
        try:
            with open(TUNNEL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"mode": "quick", "custom_url": "", "tunnel_token": ""}

def save_tunnel_config(cfg):
    with open(TUNNEL_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_active_tunnel_url():
    # 1. Check custom permanent URL from config
    cfg = load_tunnel_config()
    if cfg.get("custom_url"):
        return cfg["custom_url"].rstrip('/')
    
    # 2. Check active dynamic tunnel file
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
    try:
        res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"], capture_output=True, text=True)
        return "cloudflared.exe" in res.stdout
    except:
        return False

def stop_tunnel():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
        if os.path.exists(TUNNEL_URL_FILE):
            os.remove(TUNNEL_URL_FILE)
        return True
    except:
        return False

def start_tunnel():
    cfg = load_tunnel_config()
    token = cfg.get("tunnel_token", "").strip()

    if is_cloudflared_running():
        stop_tunnel()
        time.sleep(1)

    if not os.path.exists(CLOUDFLARED_EXE):
        print(f"[-] cloudflared.exe не найден по пути: {CLOUDFLARED_EXE}")
        return None

    if token:
        # Named Production Tunnel via Token
        print("[+] Запуск постоянного Cloudflare Tunnel (Named Tunnel via Token)...")
        proc = subprocess.Popen(
            [CLOUDFLARED_EXE, "tunnel", "--protocol", "http2", "run", "--token", token],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        url = cfg.get("custom_url") or "https://revops-tunnel.cloudflare"
        with open(TUNNEL_URL_FILE, 'w', encoding='utf-8') as f:
            f.write(url)
        return url
    else:
        # Quick Tunnel mode
        print("[+] Запуск Cloudflare Quick Tunnel (HTTP/2)...")
        proc = subprocess.Popen(
            [CLOUDFLARED_EXE, "tunnel", "--protocol", "http2", "--url", "http://127.0.0.1:5678"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        tunnel_url = None
        start_t = time.time()
        while time.time() - start_t < 25:
            line = proc.stderr.readline()
            if not line:
                time.sleep(0.2)
                continue
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                tunnel_url = match.group(0)
                break

        if tunnel_url:
            with open(TUNNEL_URL_FILE, 'w', encoding='utf-8') as f:
                f.write(tunnel_url)
            print(f"[✓] Внешний HTTPS адрес туннеля активен: {tunnel_url}")
            return tunnel_url
        else:
            print("[-] Не удалось получить быстрый URL туннеля за 25 секунд")
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

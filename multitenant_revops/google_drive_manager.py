"""
RevOps Platform V18.0 - Google Drive Sync Manager
Автоматическая организация структуры на Google Диске:
Revops -> Клиенты -> {Название_Клиента} -> Ярлык Таблицы + Паспорт
"""
import os
import sys
import json
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def find_service_account():
    candidates = [
        os.getenv("REVOPS_SA_FILE"),
        BASE_DIR / 'service_account.json',
        BASE_DIR.parent / 'service_account.json',
        BASE_DIR.parent.parent / 'service_account.json',
        Path.home() / '.gemini' / 'antigravity' / 'scratch' / 'service_account.json'
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return str(c)
    return str(BASE_DIR / 'service_account.json')

SERVICE_ACCOUNT_FILE = find_service_account()

KNOWN_REVOPS_FOLDER_ID = '1WIxLFFnKsqRWxQ0cZ_hZBHu3be2REkI2'
KNOWN_CLIENTS_FOLDER_ID = '1b8OIfCZhWp6lpGi-W8eeNF6ye8W3lvac'

def get_drive_service():
    with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
        sa = json.load(f)
    creds = Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets'])
    return build('drive', 'v3', credentials=creds)

def find_or_create_client_folder(service, tenant_name, parent_clients_id=KNOWN_CLIENTS_FOLDER_ID):
    clean_name = re.sub(r'[\/:*?"<>|]', '_', tenant_name)
    q = f"name = '{clean_name}' and '{parent_clients_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = service.files().list(q=q, supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name, webViewLink)").execute()
    files = res.get('files', [])
    if files:
        return files[0]

    # Create client folder
    meta = {
        'name': clean_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_clients_id]
    }
    folder = service.files().create(body=meta, supportsAllDrives=True, fields="id, name, webViewLink").execute()
    return folder

def ensure_spreadsheet_shortcut(service, spreadsheet_id, folder_id, shortcut_name):
    q = f"name = '{shortcut_name}' and '{folder_id}' in parents and trashed = false"
    res = service.files().list(q=q, supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute()
    if res.get('files'):
        return res.get('files')[0]

    meta = {
        'name': shortcut_name,
        'mimeType': 'application/vnd.google-apps.shortcut',
        'parents': [folder_id],
        'shortcutDetails': {
            'targetId': spreadsheet_id
        }
    }
    shortcut = service.files().create(body=meta, supportsAllDrives=True, fields="id, name, webViewLink").execute()
    return shortcut

def sync_client_to_drive(tenant_name, tenant_id, local_passport_path=None, spreadsheet_id=None):
    try:
        service = get_drive_service()
        clean_name = re.sub(r'[\/:*?"<>|]', '_', tenant_name)
        
        # 1. Папка клиента на Google Диске
        client_folder = find_or_create_client_folder(service, clean_name, KNOWN_CLIENTS_FOLDER_ID)
        folder_id = client_folder['id']
        folder_url = client_folder.get('webViewLink') or f"https://drive.google.com/drive/folders/{folder_id}"

        # 2. Создание ярлыка таблицы клиента в его папке
        if spreadsheet_id:
            shortcut_name = f"📊 Таблица RevOps - {clean_name}"
            ensure_spreadsheet_shortcut(service, spreadsheet_id, folder_id, shortcut_name)

        return {
            "status": "success",
            "client_folder_id": folder_id,
            "client_folder_url": folder_url
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

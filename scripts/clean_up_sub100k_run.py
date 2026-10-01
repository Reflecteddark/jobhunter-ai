import json
import gspread
from google.oauth2.service_account import Credentials
import openpyxl

CURRENCY_RATES = {
    'RUB': 1, 'RUR': 1, 'USD': 92, 'EUR': 100, 'KZT': 0.19, 'BYN': 28, 'BYR': 28
}

SPREADSHEET_ID = "1rmM-J_XKOuGJAiaB2_McdfP0Wo_5w4NA6Xx3KXXuTq8"
EXCEL_OUTPUT_PATH = r"C:\Users\strel\Desktop\JobHunt_РОП.xlsx"

def clean_and_sync():
    with open('service_account.json', 'r', encoding='utf-8') as f:
        sa = json.load(f)

    creds = Credentials.from_service_account_info({
        'type': 'service_account',
        'client_email': sa['email'],
        'private_key': sa['privateKey'],
        'token_uri': 'https://oauth2.googleapis.com/token'
    }, scopes=['https://www.googleapis.com/auth/spreadsheets'])

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws_rop = sh.worksheet('JobHunt_РОП')
    ws_rej = sh.worksheet('JobHunt_Rejected')

    rop_rows = ws_rop.get_all_values()
    rej_rows = ws_rej.get_all_values()

    headers_rop = rop_rows[0]
    existing_rej_ids = set(r[0] for r in rej_rows[1:] if len(r) > 0 and r[0])

    kept_rop = [headers_rop]
    to_move = []

    for idx, r in enumerate(rop_rows[1:], start=2):
        vac_id = r[0] if len(r) > 0 else ''
        sal = r[4] if len(r) > 4 else ''
        url = r[5] if len(r) > 5 else ''
        my_st = r[8] if len(r) > 8 else ''
        
        # Don't touch active interactions where user/HR actively engaged
        # But if it's '⚪ Новая' or empty, check salary:
        is_hh = 'hh.ru' in url
        reject_reason = None

        if is_hh and my_st in ['⚪ Новая', '', 'Новая']:
            if sal.startswith('до '):
                reject_reason = f'Указан только потолок ({sal}, нет оклада от 100 000 ₽)'
            elif sal.startswith('от '):
                parts = sal.split()
                try:
                    num = int(parts[1])
                    curr = parts[-1].upper()
                    rate = CURRENCY_RATES.get(curr, 1)
                    if num * rate < 100000:
                        reject_reason = f'Зарплата {sal} (ниже 100 000 ₽)'
                except:
                    pass

        if reject_reason:
            rej_entry = [
                vac_id,
                r[1] if len(r) > 1 else '',
                r[2] if len(r) > 2 else '',
                r[3] if len(r) > 3 else '',
                sal,
                url,
                'REJECTED',
                reject_reason,
                r[8] if len(r) > 8 else '',
                r[9] if len(r) > 9 else '',
                r[10] if len(r) > 10 else ''
            ]
            to_move.append((vac_id, rej_entry))
        else:
            kept_rop.append(r)

    print(f"Total rows in JobHunt_РОП before: {len(rop_rows)}")
    print(f"Rows to move to Rejected: {len(to_move)}")
    print(f"Rows kept in JobHunt_РОП: {len(kept_rop)}")

    to_append_rej = []
    for vid, entry in to_move:
        if vid not in existing_rej_ids:
            to_append_rej.append(entry)
            existing_rej_ids.add(vid)

    if to_append_rej:
        print(f"Appending {len(to_append_rej)} rows to JobHunt_Rejected...")
        ws_rej.append_rows(to_append_rej, value_input_option='USER_ENTERED')

    print(f"Rewriting JobHunt_РОП with {len(kept_rop)} clean rows...")
    ws_rop.clear()
    ws_rop.update(range_name='A1', values=kept_rop)
    print("Google Sheets successfully updated!")

    # Now run sync_jobhunt_all to refresh local Excel
    from sync_jobhunt_all import export_to_excel
    export_to_excel(kept_rop[1:], headers_rop, EXCEL_OUTPUT_PATH)
    print(f"Desktop Excel {EXCEL_OUTPUT_PATH} successfully refreshed!")

if __name__ == '__main__':
    clean_and_sync()

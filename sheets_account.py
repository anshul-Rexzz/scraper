"""
Google Sheets access via a service account (gspread). Browser-automating
Google's own login is deliberately avoided - Google actively flags/blocks
automated sign-ins, unlike Amazon/Hector which have no such defenses.

Requires the target sheet to be shared (Editor access) with the service
account's client_email from the key file.
"""
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SERVICE_ACCOUNT_KEY_PATH = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_KEY", "data-reconciliation-510312-70a744333ac6.json"
)
SHEET_URL = os.environ.get(
    "RECONCILIATION_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1Qly9EUz4HPxuGuZXC-IqFt1Nspl62-v88-OZqqjF_MI/edit",
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_worksheet(sheet_name: str | None = None):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_KEY_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(SHEET_URL)
    return spreadsheet.worksheet(sheet_name) if sheet_name else spreadsheet.sheet1

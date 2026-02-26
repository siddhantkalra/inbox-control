from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = ENGINE_DIR / "credentials.json"

TOKEN_READONLY_PATH = ENGINE_DIR / "token.readonly.json"
TOKEN_MODIFY_PATH = ENGINE_DIR / "token.modify.json"

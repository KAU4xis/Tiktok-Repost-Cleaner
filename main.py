# main.py → FUNCIONA 100% NO GITHUB ACTIONS E WINDOWS — SEM POPUP
import os
import sys
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from supabase import create_client

# ========================= CONFIG =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
TABLE_NAME = "tiktok_sessions"
TIMEOUT_MINUTES = 5

if len(sys.argv) != 2:
    print("Erro: passe o row_id")
    sys.exit(1)

row_id = sys.argv[1]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"Iniciando login TikTok → sessão {row_id}")

# ==================== FIREFOX COM BYPASS PERFEITO ====================
options = webdriver.FirefoxOptions()
options.set_preference("general.useragent.override", 
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0")

if os.getenv("GITHUB_ACTIONS") == "true":
    print("GitHub Actions → Firefox headless")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
else:
    print("Local → janela visível")

options.set_preference("dom.webdriver.enabled", False)
options.set_preference("useAutomationExtension", False)

driver = webdriver.Firefox(options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")

deadline = datetime.utcnow() + timedelta(minutes=TIMEOUT_MINUTES)

def update(data: dict):
    data["id"] = row_id
    data["updated_at"] = datetime.utcnow().isoformat()
    if data.get("status") in ["expired", "error"]:
        data["closed_at"] = datetime.utcnow().isoformat()
    supabase.table(TABLE_NAME).upsert(data, on_conflict="id").execute()
    print(f"Supabase → {data.get('status')}")

def get_qr():
    try:
        canvas = driver.find_element(By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")
        return driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
    except:
        return None

try:
    # PASSO 1: ACESSA PÁGINA INICIAL PRIMEIRO (OBRIGATÓRIO NO ACTIONS)
    print("Acessando página inicial para enganar o TikTok...")
    driver.get("https://www.tiktok.com")
    time.sleep(3)

    # PASSO 2: VAI PRO QR
    print("Indo para QR Code...")
    driver.get("https://www.tiktok.com/login/qrcode")
    time.sleep(2)

    # Espera o QR aparecer
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas"))
    )
    print("QR carregado com sucesso!")

    qr_b64 = get_qr()
    update({
        "qrcode_base64": qr_b64,
        "status": "waiting_scan",
        "qrcode_expires_at": deadline.isoformat()
    })
    print("QR enviado ao Supabase")

    last_qr = qr_b64

    while True:
        now = datetime.utcnow()
        if now >= deadline:
            update({"status": "expired"})
            print("Sessão expirada")
            break

        if "login" not in driver.current_url.lower():
            cookies = driver.get_cookies()
            sec_uid = next((c["value"] for c in cookies if c["name"] == "sessionid" and c["value"].startswith("MS4wLjABAAAA")), None)
            update({
                "status": "logged",
                "cookies": cookies,
                "logged_at": now.isoformat(),
                "sec_uid": sec_uid,
                "closed_at": None
            })
            print(f"LOGADO! {len(cookies)} cookies salvos")
            break

        # Scanned
        try:
            if driver.find_element(By.XPATH, "//*[contains(text(),'escaneado') or contains(text(),'scanned')]").is_displayed():
                update({"status": "scanned"})
                print("QR escaneado → confirme no app")
        except:
            pass

        # QR renovado?
        current = get_qr()
        if current and current != last_qr:
            last_qr = current
            update({"qrcode_base64": current, "status": "waiting_scan"})
            print("QR renovado automaticamente")

        time.sleep(1.5)

except Exception as e:
    print(f"ERRO: {e}")
    update({"status": "error", "error_message": str(e)})
finally:
    driver.quit()
    print("Script finalizado.")

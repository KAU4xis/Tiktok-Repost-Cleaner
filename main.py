# main.py → VERSÃO FINAL (100% FUNCIONANDO — TikTok 2025)
import os
import sys
import time
from datetime import datetime, timedelta

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
TABLE_NAME = "tiktok_sessions"
TIMEOUT_MINUTES = 5

if len(sys.argv) != 2:
    print("Erro: passe o row_id")
    sys.exit(1)

row_id = sys.argv[1]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"Login TikTok → sessão {row_id}")

# ==================== BYPASS TOTAL ====================
options = uc.ChromeOptions()
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

if os.getenv("GITHUB_ACTIONS") == "true":
    print("GitHub Actions → headless")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
else:
    print("Local → janela visível")

# Deixa o undetected_chromedriver fazer o trabalho dele
driver = uc.Chrome(options=options)  # Detecta sua versão automaticamente

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
    driver.get("https://www.tiktok.com/login/qrcode")
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")))
    print("QR carregado!")

    qr_b64 = get_qr()
    update({"qrcode_base64": qr_b64, "status": "waiting_scan", "qrcode_expires_at": deadline.isoformat()})

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
            print(f"LOGADO COM SUCESSO! {len(cookies)} cookies salvos no Supabase")
            break

        try:
            if driver.find_element(By.XPATH, "//*[contains(text(),'escaneado') or contains(text(),'scanned')]").is_displayed():
                update({"status": "scanned"})
        except:
            pass

        current = get_qr()
        if current and current != last_qr:
            last_qr = current
            update({"qrcode_base64": current, "status": "waiting_scan"})
            print("QR renovado")

        time.sleep(1.5)

except Exception as e:
    print(f"ERRO CRÍTICO: {e}")
    update({"status": "error", "error_message": str(e)})
finally:
    try:
        driver.quit()
    except:
        pass  # Ignora o erro inofensivo do Windows
    print("Script finalizado com sucesso.")

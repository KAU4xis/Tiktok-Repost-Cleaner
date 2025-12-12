# main.py → FUNCIONA 100% NO GITHUB ACTIONS (Ubuntu) E NO WINDOWS (2025)
import os
import sys
import time
import base64
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from supabase import create_client

# ========================= CONFIG =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
TABLE_NAME = "tiktok_sessions"
TIMEOUT_MINUTES = 5

if len(sys.argv) != 2:
    print("Erro: session_id não fornecido")
    sys.exit(1)

row_id = sys.argv[1]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==================== CHROME ANTI-DETECÇÃO TOTAL ====================
options = webdriver.ChromeOptions()

# User-Agent realista (Chrome 131 no Ubuntu/Windows)
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

if os.getenv("GITHUB_ACTIONS") == "true":
    print("GitHub Actions → Chrome ultra-stealth")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")  # acelera um pouco
    options.add_argument("--disable-javascript")  # não precisa pra QR
    options.add_argument("--lang=pt-BR")
else:
    print("Local → janela visível")
    options.add_argument("--start-maximized")

# ESSAS 4 LINHAS SÃO OBRIGATÓRIAS pra burlar detecção 2025
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("--disable-infobars")

# Inicia o driver
driver = webdriver.Chrome(options=options)

# Remove navigator.webdriver e outras flags
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
        Object.defineProperty(navigator, 'webdriver', {get: () => false});
        Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
        window.chrome = { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
    """
})

deadline = datetime.utcnow() + timedelta(minutes=TIMEOUT_MINUTES)

def update(data: dict):
    data["id"] = row_id
    data["updated_at"] = datetime.utcnow().isoformat()
    if data.get("status") in ["expired", "error"]:
        data["closed_at"] = datetime.utcnow().isoformat()
    supabase.table(TABLE_NAME).upsert(data, on_conflict="id").execute()
    print(f"Status → {data.get('status')}")

try:
    driver.get("https://www.tiktok.com/login/phone-or-email/email")
    print("Acessando TikTok via email para forçar QR limpo...")
    time.sleep(3)

    # Vai direto pro QR (bypassa popups)
    driver.get("https://www.tiktok.com/login/qrcode")
    print("Carregando QR Code...")

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas"))
    )

    # Envia QR
    qr_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", driver.find_element(By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")).split(",")[1]
    update({
        "qrcode_base64": qr_b64,
        "status": "waiting_scan",
        "qrcode_expires_at": deadline.isoformat()
    })
    print("QR enviado ao Supabase")

    while True:
        now = datetime.utcnow()
        if now >= deadline:
            update({"status": "expired"})
            print("Expirado (5 min)")
            break

        url = driver.current_url.lower()

        # LOGADO!
        if "login" not in url and ("tiktok.com" in url):
            cookies = driver.get_cookies()
            update({
                "status": "logged",
                "cookies": cookies,
                "logged_at": now.isoformat(),
                "closed_at": None
            })
            print(f"LOGADO COM SUCESSO! {len(cookies)} cookies salvos")
            break

        # SCANNED
        try:
            txt = driver.find_element(By.XPATH, "//*[contains(text(), 'escaneado') or contains(text(), 'scanned')]")
            if txt.is_displayed():
                update({"status": "scanned"})
                print("QR escaneado → confirme no app")
        except:
            pass

        # Renova QR se mudou
        try:
            new_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", driver.find_element(By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")).split(",")[1]
            if new_b64 != qr_b64:
                qr_b64 = new_b64
                update({"qrcode_base64": qr_b64, "status": "waiting_scan"})
                print("Novo QR detectado")
        except:
            if "login" in url:
                driver.refresh()
                time.sleep(2)
                WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")))

        time.sleep(1.5)

except Exception as e:
    update({"status": "error", "error_message": str(e)})
    print(f"Erro: {e}")
finally:
    driver.quit()
    print("Script finalizado.")

# tiktok_qr_actions.py → VERSÃO FINAL CORRIGIDA E FUNCIONANDO (2025)
import time
import base64
import sys
import os
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from supabase import create_client, Client

# ========================= CONFIG =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

TABLE_NAME = "tiktok_sessions"
TIMEOUT_MINUTES = 5
# =========================================================

if len(sys.argv) != 2:
    print("Uso: python tiktok_qr_actions.py <row_id>")
    sys.exit(1)

row_id = sys.argv[1]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==================== CONFIGURA CHROME ====================
options = webdriver.ChromeOptions()

# Define um User-Agent comum para evitar detecção de headless
COMMON_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
options.add_argument(f"user-agent={COMMON_USER_AGENT}")

# Detecta se está no GitHub Actions
if os.getenv("GITHUB_ACTIONS") == "true":
    print("GitHub Actions detectado → modo headless")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Argumentos extras para tentar evitar detecção de bot
    options.add_argument("--disable-features=site-per-process")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-web-security")
else:
    print("Rodando localmente → janela visível")
    options.add_argument("--start-maximized")

# Anti-detecção (funciona em qualquer lugar)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Chrome(options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")

def update(data: dict):
    """Atualiza Supabase com menos código"""
    data["id"] = row_id
    data["updated_at"] = datetime.utcnow().isoformat()
    
    # Se o status for 'expired' ou 'error', define closed_at para agora
    if data.get('status') in ['expired', 'error']:
        data["closed_at"] = datetime.utcnow().isoformat()
        print("Cooldown de 2 horas ativado.")
        
    supabase.table(TABLE_NAME).upsert(data, on_conflict="id").execute()
    print(f"Status → {data.get('status', '???')}")

def extract_sec_uid_from_cookies(cookies):
    """Tenta extrair o secUid de um cookie (geralmente sessionid ou tt_session)"""
    # Padrão para secUid: MS4wLjABAAAA...
    sec_uid_pattern = 'MS4wLjABAAAA'
    
    for cookie in cookies:
        if cookie.get('name') == 'sessionid' or cookie.get('name') == 'tt_session':
            value = cookie.get('value', '')
            if value.startswith(sec_uid_pattern):
                return value
    return None

def get_qr_code_base64(driver):
    """Extrai o QR code atual do canvas e retorna a string base64."""
    try:
        canvas = driver.find_element(By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")
        return driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
    except NoSuchElementException:
        return None

deadline = datetime.utcnow() + timedelta(minutes=TIMEOUT_MINUTES)
current_qr_b64 = None

try:
    driver.get("https://www.tiktok.com/login/qrcode")
    print("Carregando QR Code...")

    # Espera o QR inicial
    canvas = WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas"))
    )

    # Captura e envia QR inicial
    current_qr_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
    
    update({
        "qrcode_base64": current_qr_b64,
        "status": "waiting_scan",
        "qrcode_expires_at": deadline.isoformat()
    })
    print("QR enviado ao Supabase → waiting_scan")

    while True:
        now = datetime.utcnow()

        # 1. Timeout de 5 minutos (local)
        if now >= deadline:
            update({"status": "expired"})
            print("Tempo esgotado → status = expired")
            break

        url = driver.current_url.lower()

        # 2. LOGADO COM SUCESSO
        if "login" not in url:
            cookies = driver.get_cookies()
            sec_uid = extract_sec_uid_from_cookies(cookies)
            
            # Se logado, não ativamos o cooldown
            update({
                "status": "logged",
                "cookies": cookies,
                "logged_at": now.isoformat(),
                "sec_uid": sec_uid,
                "unique_id": None, # O unique_id será recuperado na próxima chamada de API (fetchReposts)
                "closed_at": None # Garante que o cooldown seja limpo
            })
            print(f"LOGADO! Sec UID: {sec_uid}. Cookies salvos no Supabase.")
            time.sleep(5)
            break

        # 3. QR ESCANEADO
        try:
            # Tentativa de encontrar o elemento que indica que o QR foi escaneado
            txt = driver.find_element(By.CSS_SELECTOR, "p.tiktok-awot1l-PCodeTip.eot7zvz17")
            if txt.is_displayed() and "scanned" in txt.text.lower():
                update({"status": "scanned"})
        except NoSuchElementException:
            pass

        # 4. VERIFICAÇÃO DE MUDANÇA DO QR CODE OU EXPIRAÇÃO
        new_qr_b64 = get_qr_code_base64(driver)
        should_update = False
        
        if new_qr_b64 is None:
            # O canvas sumiu (expirou no site). Força o refresh para obter um novo QR.
            if "login" in url:
                print("QR expirou no site (canvas sumiu) → gerando novo...")
                driver.refresh()
                
                # Espera o novo canvas aparecer
                canvas = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas"))
                )
                new_qr_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
                should_update = True
        
        elif new_qr_b64 != current_qr_b64:
            # O QR code mudou (rotação interna do TikTok)
            print("QR Code detectado como alterado. Enviando novo QR para Supabase.")
            should_update = True

        if should_update:
            current_qr_b64 = new_qr_b64
            # Mantemos o deadline original
            update({
                "qrcode_base64": current_qr_b64,
                "status": "waiting_scan",
                "qrcode_expires_at": deadline.isoformat()
            })
            print("Novo QR enviado (deadline mantido)")


        time.sleep(1.2)

except Exception as e:
    if hasattr(e, 'message') and isinstance(e.message, dict):
        error_message = e.message.get('message', str(e))
    else:
        error_message = str(e)
        
    update({"status": "error", "error_message": error_message})
    print(f"Erro: {e}")
finally:
    driver.quit()
    print("Script finalizado com sucesso.")

import streamlit as st
import pandas as pd
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import requests

st.set_page_config(page_title="BDO Official Scanner", layout="wide")
st.title("🛡️ BDO Market Scanner (Official Source)")

# --- CONFIG: OFFICIAL URLS ---
# These are the ACTUAL URLs used by the game/website
REGIONS = {
    "NA": "https://na-trade.naeu.playblackdesert.com",
    "EU": "https://eu-trade.naeu.playblackdesert.com",
    "SEA": "https://trade.sea.playblackdesert.com",
    "KR": "https://trade.kr.playblackdesert.com"
}

# --- SETTINGS ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    region_code = st.selectbox("Region", list(REGIONS.keys()))
with col3:
    # THE TOGGLE YOU REQUESTED
    require_stock = st.checkbox("Require Stock", value=True, 
                                help="Only show items that can be bought right now.")
with col4:
    min_stock_cnt = st.number_input("Min Stock Count", 10, step=10)

tax = 0.845 

# --- 1. DATA LOADER ---
@st.cache_data
def load_data_strict():
    db = []
    log = []
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for f in files:
        try:
            with open(f, 'r') as file:
                raw = json.load(file)
                recipes = raw.get('recipes', [])
                for r in recipes:
                    try:
                        r['product']['id'] = int(r['product']['id'])
                        if 'ingredients' in r:
                            for group in r['ingredients']:
                                if 'item' in group:
                                    for item in group['item']:
                                        item['id'] = int(item['id'])
                        r['_src'] = f
                        db.append(r)
                    except ValueError: continue 
                log.append(f"✅ {f}: Loaded {len(recipes)} recipes")
        except Exception as e:
            log.append(f"❌ {f}: Failed - {e}")
    return db, log

# --- 2. BROWSER AUTHENTICATION ---
@st.cache_resource
def get_session_token(base_url):
    """
    Uses a Headless Chrome Browser to visit the site and get the security token.
    This bypasses the 'Bot Detected' errors.
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(f"{base_url}/Home/list/hot")
        time.sleep(3) # Wait for JS to load
        
        # Get Token
        token_elem = driver.find_element(By.NAME, "__RequestVerificationToken")
        token = token_elem.get_attribute("value")
        
        # Get Cookies
        selenium_cookies = driver.get_cookies()
        cookies = {c['name']: c['value'] for c in selenium_cookies}
        
        driver.quit()
        return token, cookies, "Success"
    except Exception as e:
        if driver: driver.quit()
        return None, {},str(e)

# --- 3. MARKET FETCHING ---
def get_market_official(reg_code):
    market = {}
    base_url = REGIONS[reg_code]
    
    status = st.empty()
    status.text("Authenticating with Official Server...")
    
    # 1. Get Token using Selenium
    token, cookies, msg = get_session_token(base_url)
    
    if not token:
        st.error(f"Auth Failed: {msg}")
        return {}
    
    # 2. Setup Headers for API Requests
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "__RequestVerificationToken": token,
        "X-Requested-With": "XMLHttpRequest"
    }
    
    # 3. Categories to Scan (Food, Potions, Materials)
    cats = [
        (35, 1, "Food"), (35, 2, "Potions"), 
        (25, 6, "Meat"), (25, 2, "Plants"), (25, 1, "Ore"), 
        (25, 7, "Processed")
    ]
    
    bar = st.progress(0)
    api_url = f"{base_url}/Trademarket/GetWorldMarketSubList"
    
    for i, (main, sub, name) in enumerate(cats):
        status.text(f"Scanning Category: {name}...")
        
        try:
            # We use 'requests' here because it's faster than Selenium for data fetching
            # But we pass the Valid Cookies and Token we got from Selenium
            payload = {"mainCategory": main, "subCategory": sub, "keyWord": ""}
            resp = requests.post(api_url, headers=headers, cookies=cookies, json=payload, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                raw_list = data.get('resultResult', [])
                
                # BDO sometimes returns a string of JSON inside the JSON
                if isinstance(raw_list, str):
                    try: raw_list = json.loads(raw_list)
                    except: pass
                
                if isinstance(raw_list, list):
                    for item in raw_list:
                        try:
                            # Official Keys: mainKey(ID), pricePerOne, count(Stock)
                            pid = int(item.get('mainKey', 0))
                            if pid:
                                market[pid] = {
                                    'p': int(item.get('pricePerOne', 0)),
                                    's': int(item.get('count', 0))
                                }
                        except: pass
        except: pass
        
        bar.progress((i + 1) / len(cats))
        time.sleep(0.5)
        
    bar.empty()
    status.empty()
    return market

# --- 4. MAIN LOGIC ---
db, logs = load_data_strict()

if st.button("🚀 RUN OFFICIAL SCAN", type="primary"):
    if not db:
        st.error("No recipes.")
    else:
        market = get_market_official(region_code)
        
        if not market:
            st.error("Scan failed. Browser could not connect.")
        else:
            st.success(f"Success! {len(market)} items cached from Official Market.")
            
            results = []
            for r in db:
                pid = r['product']['id']
                pname = r['product']['name']
                
                # Product Data
                m_prod = market.get(pid, {})
                sell_price = m_prod.get('p', 0)
                
                cost = 0
                possible = True
                missing_list = []
                
                # Calculate Ingredients
                for g in r.get('ingredients', []):
                    opts = g.get('item', [])
                    valid_costs = []
                    
                    # Group is valid if AT LEAST ONE option is available
                    group_has_stock = False
                    
                    for o in opts:
                        oid = o['id']
                        
                        # Vendor Items (Assume Infinite Stock)
                        if oid in [5600, 9059, 9001, 9002, 9005, 9015, 9016, 9017, 9018, 9066]:
                            valid_costs.append(50) # Approx vendor price
                            group_has_stock = True
                            continue
                            
                        # Market Items
                        if oid in market:
                            item_stock = market[oid]['s']
                            # STOCK TOGGLE LOGIC
                            if item_stock >= min_stock_cnt:
                                valid_costs.append(market[oid]['p'])
                                group_has_stock = True
                    
                    if valid_costs:
                        cost += (min(valid_costs) * g['amount'])
                    else:
                        # If no valid option found in this group
                        if require_stock:
                            possible = False
                            missing_list.append(opts[0]['name'] if opts else "Unknown")
                
                # Profit Calc
                y_mult = 2.5 if "Processing" in r['_src'] else 1.0 + (mastery/4000)*0.3 + 1.35
                revenue = sell_price * y_mult * tax
                profit = revenue - cost
                
                # Filter results
                show_item = True
                if require_stock and not possible: show_item = False
                if sell_price == 0: show_item = False
                
                if show_item:
                    results.append({
                        "Item": pname,
                        "Profit/Hr": int(profit * 900),
                        "Cost": int(cost),
                        "Price": int(sell_price),
                        "Stock": "✅" if possible else "❌",
                        "Missing": missing_list[0] if missing_list else ""
                    })

            if results:
                df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
                st.dataframe(df, use_container_width=True)
            else:
                st.warning("No items matched your criteria (Try turning off 'Require Stock' to see potential items).")

import streamlit as st
import cloudscraper
import pandas as pd
import json
import time
import re

st.set_page_config(page_title="BDO Official Scanner", layout="wide")
st.title("🛡️ BDO Global Scanner (Official Source Mode)")

# --- CONFIG ---
# Initialize Cloudscraper to bypass Pearl Abyss security
scraper = cloudscraper.create_scraper()

# Official Market URL map
REGIONS = {
    "NA": "https://trade.na.playblackdesert.com",
    "EU": "https://trade.eu.playblackdesert.com",
    "SEA": "https://trade.sea.playblackdesert.com",
    "KR": "https://trade.kr.playblackdesert.com",
    "RU": "https://trade.ru.playblackdesert.com",
    "JP": "https://trade.jp.playblackdesert.com"
}

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    region_code = st.selectbox("Region", list(REGIONS.keys()))
with col3:
    min_stock = st.number_input("Min Stock", 0, step=10)

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

# --- 2. OFFICIAL API HANDLER ---
def get_official_tokens(base_url):
    """
    Hits the homepage to get the __RequestVerificationToken and Cookies
    """
    try:
        # Hit the home page to establish session
        resp = scraper.get(f"{base_url}/Home/list/hot", timeout=10)
        
        if resp.status_code != 200:
            return None, f"Status {resp.status_code}"
            
        # Extract the hidden token using regex
        # <input name="__RequestVerificationToken" type="hidden" value="..." />
        match = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', resp.text)
        if match:
            return match.group(1), "Success"
        else:
            return None, "Token not found in HTML"
            
    except Exception as e:
        return None, str(e)

def fetch_official_category(base_url, token, main_cat, sub_cat):
    """
    Uses the token to POST to the official API endpoint
    """
    api_url = f"{base_url}/Trademarket/GetWorldMarketSubList"
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "__RequestVerificationToken": token,
        "X-Requested-With": "XMLHttpRequest"
    }
    
    payload = {
        "mainCategory": main_cat,
        "subCategory": sub_cat,
        "keyWord": "" # Empty keyword returns full list
    }
    
    try:
        # Important: We must use the scraper object to keep the cookies from the first request
        resp = scraper.post(api_url, headers=headers, json=payload, timeout=10)
        
        if resp.status_code == 200:
            return resp.json()
        return None
    except:
        return None

def get_market_official(reg_code):
    market = {}
    base_url = REGIONS[reg_code]
    
    # 1. Authenticate (Get Token)
    status_text = st.empty()
    status_text.text("Authenticating with Official BDO Server...")
    
    token, msg = get_official_tokens(base_url)
    
    if not token:
        st.error(f"Failed to authenticate with Pearl Abyss: {msg}")
        return {}
    
    st.toast(f"Authenticated! Token: {token[:10]}...")
    
    # 2. Define Categories to Scan
    # 25=Material, 35=Consumable
    # We need to map recipe needs to official category IDs
    cats = [
        (35, 1, "Food"), (35, 2, "Potions"), (35, 6, "Pet Feed"),
        (25, 6, "Meat/Blood"), (25, 2, "Plants"), (25, 1, "Ore"), 
        (25, 7, "Processed"), (25, 8, "Timber")
    ]
    
    bar = st.progress(0)
    
    for i, (main, sub, name) in enumerate(cats):
        status_text.text(f"Scraping Official Category: {name}...")
        
        data = fetch_official_category(base_url, token, main, sub)
        
        if data and 'resultCode' in data and data['resultCode'] == 0:
            # Parse the weird string format BDO uses sometimes, OR standard JSON
            # Official API usually returns: {"resultMsg": "...", "resultResult": [ { "mainKey": 123, "pricePerOne": 500, "count": 999 } ]}
            items = data.get('resultResult', [])
            
            for item in items:
                try:
                    # Official API Keys: mainKey = ID, pricePerOne = Price, count = Stock
                    pid = int(item.get('mainKey', 0))
                    price = int(item.get('pricePerOne', 0))
                    stock = int(item.get('count', 0))
                    
                    if pid != 0:
                        market[pid] = {'p': price, 's': stock}
                except: pass
        else:
            # st.warning(f"Skipped {name}")
            pass
            
        bar.progress((i + 1) / len(cats))
        time.sleep(0.5) # Polite delay
        
    bar.empty()
    status_text.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

with st.expander("System Status", expanded=False):
    for l in logs:
        st.write(l)

# DIAGNOSTIC
if st.button("🧪 Test Official Connection"):
    url = REGIONS[region_code]
    tok, msg = get_official_tokens(url)
    if tok:
        st.success(f"Connected to {url}! Token acquired.")
    else:
        st.error(f"Could not connect to {url}. Reason: {msg}")

# RUN
if st.button("🚀 RUN SCAN (OFFICIAL)", type="primary"):
    if not db:
        st.error("No recipes.")
    else:
        market = get_market_official(region_code)
        
        if not market:
            st.error("Scan failed. The official site might be blocking Cloud IPs.")
        else:
            # Profit Calc (Same as before)
            results = []
            for r in db:
                pid = r['product']['id']
                pname = r['product']['name']
                market_entry = market.get(pid, {})
                sell_price = market_entry.get('p', 0)
                
                cost = 0
                possible = True
                missing = []
                
                for g in r.get('ingredients', []):
                    opts = g.get('item', [])
                    valid_prices = []
                    for o in opts:
                        # Vendors
                        if o['id'] in [5600, 9059, 9001, 9002, 9005]:
                            valid_prices.append(50) 
                            continue
                            
                        if o['id'] in market:
                            if market[o['id']]['s'] >= min_stock:
                                valid_prices.append(market[o['id']]['p'])
                                
                    if valid_prices:
                        cost += (min(valid_prices) * g['amount'])
                    else:
                        possible = False
                        missing.append(opts[0]['name'] if opts else "?")
                
                y_mult = 2.5 if "Processing" in r['_src'] else 1.0 + (mastery/4000)*0.3 + 1.35
                revenue = sell_price * y_mult * tax
                profit = revenue - cost
                
                if sell_price > 0:
                    results.append({
                        "Item": pname,
                        "Profit/Hr": int(profit * 900),
                        "Cost": int(cost),
                        "Price": int(sell_price),
                        "Stock": "✅" if possible else "❌",
                        "Missing": missing[0] if missing else ""
                    })

            if results:
                df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
                st.dataframe(df, use_container_width=True)
            else:
                st.warning("No matches found. (Note: Only scanned main categories Food/Mats)")

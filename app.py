import streamlit as st
import cloudscraper
import pandas as pd
import json
import time
import re

st.set_page_config(page_title="BDO Market (Official)", layout="wide")
st.title("🛡️ BDO Market Scanner (Official Source)")

# --- CONFIG ---
scraper = cloudscraper.create_scraper()

# --- FIXED OFFICIAL URLS ---
# These are the actual endpoints BDOLytics scrapes
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
    # THE FEATURE YOU ASKED FOR
    require_stock = st.checkbox("Toggle: Require Stock?", value=True, 
                                help="If checked, recipes with missing ingredients are marked invalid.")
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

# --- 2. OFFICIAL API HANDLER ---
def get_official_tokens(base_url):
    """Hits the homepage to get the session token."""
    try:
        # We start a session to get cookies
        resp = scraper.get(f"{base_url}/Home/list/hot", timeout=10)
        
        if resp.status_code != 200:
            return None, f"Status {resp.status_code}"
            
        # Regex to find the hidden token input
        match = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', resp.text)
        if match:
            return match.group(1), "Success"
        else:
            return None, "Token not found (IP blocked?)"
    except Exception as e:
        return None, str(e)

def fetch_official_category(base_url, token, main_cat, sub_cat):
    """Uses token to fetch category data."""
    api_url = f"{base_url}/Trademarket/GetWorldMarketSubList"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "__RequestVerificationToken": token,
        "X-Requested-With": "XMLHttpRequest"
    }
    payload = {"mainCategory": main_cat, "subCategory": sub_cat, "keyWord": ""}
    
    try:
        resp = scraper.post(api_url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except: return None

def get_market_official(reg_code):
    market = {}
    base_url = REGIONS[reg_code]
    
    status_text = st.empty()
    status_text.text("Authenticating...")
    
    token, msg = get_official_tokens(base_url)
    if not token:
        st.error(f"Auth Failed: {msg}")
        return {}
    
    # Categories to scan (Material + Consumable)
    cats = [
        (35, 1, "Food"), (35, 2, "Potions"), (35, 6, "Pet Feed"),
        (25, 6, "Meat"), (25, 2, "Plants"), (25, 1, "Ore"), 
        (25, 7, "Processed"), (25, 8, "Timber")
    ]
    
    bar = st.progress(0)
    
    for i, (main, sub, name) in enumerate(cats):
        status_text.text(f"Scanning Official Market: {name}...")
        data = fetch_official_category(base_url, token, main, sub)
        
        if data and 'resultResult' in data:
            raw_list = data['resultResult']
            # Decode if it's a string
            if isinstance(raw_list, str):
                try: raw_list = json.loads(raw_list)
                except: pass
            
            if isinstance(raw_list, list):
                for item in raw_list:
                    try:
                        pid = int(item.get('mainKey', 0))
                        price = int(item.get('pricePerOne', 0))
                        stock = int(item.get('count', 0))
                        if pid != 0:
                            market[pid] = {'p': price, 's': stock}
                    except: pass
        
        bar.progress((i + 1) / len(cats))
        time.sleep(0.5) 
        
    bar.empty()
    status_text.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

with st.expander("System Logs", expanded=False):
    for l in logs: st.write(l)

# DIAGNOSTIC
if st.button("🧪 Test Official Connection (Corrected URL)"):
    url = REGIONS[region_code]
    tok, msg = get_official_tokens(url)
    if tok:
        st.success(f"Connected to {url}! Token: {tok[:10]}...")
    else:
        st.error(f"Connection Failed: {msg}")

# RUN
if st.button("🚀 RUN SCAN", type="primary"):
    if not db:
        st.error("No recipes.")
    else:
        market = get_market_official(region_code)
        
        if not market:
            st.error("Scan failed. Market empty.")
        else:
            st.success(f"Market Data: {len(market)} items cached.")
            
            results = []
            for r in db:
                pid = r['product']['id']
                pname = r['product']['name']
                market_entry = market.get(pid, {})
                sell_price = market_entry.get('p', 0)
                
                cost = 0
                possible = True
                missing = []
                
                # --- INGREDIENT CHECKER ---
                for g in r.get('ingredients', []):
                    opts = g.get('item', [])
                    valid_prices = []
                    
                    # 1. Check if ANY option in this group is purchasable
                    group_purchasable = False
                    
                    for o in opts:
                        # Vendors (Assume available)
                        if o['id'] in [5600, 9059, 9001, 9002, 9005, 9015, 9016, 9017, 9018, 9066, 6656]:
                            valid_prices.append(50)
                            group_purchasable = True
                            continue
                        
                        # Market Items
                        if o['id'] in market:
                            # Apply the TOGGLE logic here
                            if market[o['id']]['s'] >= min_stock_cnt:
                                valid_prices.append(market[o['id']]['p'])
                                group_purchasable = True
                    
                    if valid_prices:
                        cost += (min(valid_prices) * g['amount'])
                    else:
                        # If filtering is ON, and no valid items found, fail the recipe
                        if require_stock:
                            possible = False
                            missing.append(opts[0]['name'] if opts else "?")
                        else:
                            # If filtering OFF, we just assume 0 cost (or last known)
                            pass

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
                # Filter out stock failures if requested
                if require_stock:
                    results = [x for x in results if x['Stock'] == "✅"]
                
                df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
                st.dataframe(df, use_container_width=True)
            else:
                st.warning("No matches found.")

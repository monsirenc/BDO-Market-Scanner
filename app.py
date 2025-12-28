import streamlit as st
import requests
import pandas as pd
import json
import time
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="BDO Multi-Protocol Scanner", layout="wide")
st.title("🛡️ BDO Global Scanner (Multi-Protocol)")

# --- SETTINGS ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    region = st.selectbox("Region", ["na", "eu", "sea", "kr", "sa", "ru", "jp"])
with col3:
    min_stock = st.number_input("Min Stock", 0, step=10)
with col4:
    # NEW: Allow user to switch API methods if one is broken
    protocol = st.selectbox("API Protocol", ["v2 (Batch)", "v1 (Single)", "Hotlist (Test)"])

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

# --- 2. MULTI-PROTOCOL API ---
def get_market_data(ids, reg, proto):
    market = {}
    
    # Filter known trash to prevent 500 errors
    BLACKLIST = {5600, 9059, 9001, 9002, 9005, 9017, 9066, 9016, 9015, 9018, 6656, 6655}
    safe_ids = list(set([int(i) for i in ids if int(i) not in BLACKLIST]))
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    bar = st.progress(0)
    status = st.empty()
    
    # --- PROTOCOL: V2 (Batch) ---
    if "v2" in proto:
        batch_size = 20
        for i in range(0, len(safe_ids), batch_size):
            batch = safe_ids[i:i+batch_size]
            if not batch: continue
            
            url = f"https://api.arsha.io/v2/{reg}/price?id={','.join(map(str, batch))}&lang=en"
            try:
                r = requests.get(url, headers=headers, verify=False, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        for x in data:
                            pid = int(x.get('id', 0))
                            if pid: market[pid] = {'p': int(x.get('pricePerOne', 0)), 's': int(x.get('currentStock', 0))}
            except: pass
            
            bar.progress(min((i + batch_size) / len(safe_ids), 1.0))
            status.text(f"V2 Scanning... Found {len(market)} items")
            time.sleep(0.1)

    # --- PROTOCOL: V1 (Single Fetch - Slower but Reliable) ---
    elif "v1" in proto:
        for i, pid in enumerate(safe_ids):
            url = f"https://api.arsha.io/v1/{reg}/{pid}"
            try:
                r = requests.get(url, headers=headers, verify=False, timeout=2)
                if r.status_code == 200:
                    # V1 sometimes returns list, sometimes dict
                    data = r.json()
                    if isinstance(data, list) and data:
                        data = data[0] # Take first item if list
                    
                    if isinstance(data, dict) and 'pricePerOne' in data:
                         market[pid] = {
                             'p': int(data.get('pricePerOne', 0)), 
                             's': int(data.get('currentStock', 0))
                         }
            except: pass
            
            if i % 5 == 0:
                bar.progress(min(i / len(safe_ids), 1.0))
                status.text(f"V1 Scanning... Found {len(market)} items")
            time.sleep(0.05) # Be gentle

    bar.empty()
    status.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

with st.expander("📂 System Status", expanded=False):
    for l in logs:
        st.write(l)

# DIAGNOSTIC PANEL
st.divider()
st.subheader("🧪 Diagnostic Test")
col_t1, col_t2, col_t3 = st.columns(3)

with col_t1:
    if st.button("Test V2 (Batch)"):
        try:
            r = requests.get(f"https://api.arsha.io/v2/{region}/price?id=9213", headers={'User-Agent': 'Mozilla/5.0'}, verify=False, timeout=5)
            if r.status_code == 200:
                st.success(f"V2 Working! {r.json()[0]['pricePerOne']}")
            else:
                st.error(f"V2 Failed: {r.status_code}")
        except Exception as e: st.error(str(e))

with col_t2:
    if st.button("Test V1 (Single)"):
        try:
            r = requests.get(f"https://api.arsha.io/v1/{region}/9213", headers={'User-Agent': 'Mozilla/5.0'}, verify=False, timeout=5)
            if r.status_code == 200:
                # V1 structure might vary
                data = r.json()
                price = data[0]['pricePerOne'] if isinstance(data, list) else data.get('pricePerOne', 'Err')
                st.success(f"V1 Working! {price}")
            else:
                st.error(f"V1 Failed: {r.status_code}")
        except Exception as e: st.error(str(e))

with col_t3:
    if st.button("Test Category (Food)"):
        try:
            # Fetches 'Consumables -> Food' list
            url = f"https://api.arsha.io/v2/{region}/GetWorldMarketSubList?mainCategory=35&subCategory=1"
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, verify=False, timeout=5)
            if r.status_code == 200:
                data = r.json()
                st.success(f"Cat Working! Found {len(data)} items")
            else:
                st.error(f"Cat Failed: {r.status_code}")
        except Exception as e: st.error(str(e))

st.divider()

# RUN BUTTON
if st.button("🚀 RUN SCAN", type="primary"):
    if not db:
        st.error("No recipes.")
    else:
        # Collect IDs
        all_ids = set()
        for r in db:
            all_ids.add(r['product']['id'])
            for g in r.get('ingredients', []):
                for i in g.get('item', []):
                    all_ids.add(i['id'])
        
        # API FETCH
        st.info(f"Fetching data for {len(all_ids)} items using {protocol}...")
        market = get_market_data(list(all_ids), region, protocol)
        
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
                    # Check blacklist for vendors
                    if o['id'] in [5600, 9059, 9001, 9002, 9005]:
                        valid_prices.append(0)
                        continue

                    oid = o['id']
                    if oid in market:
                        if market[oid]['s'] >= min_stock:
                            valid_prices.append(market[oid]['p'])
                
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
                    "Missing": ", ".join(missing[:1])
                })

        if results:
            df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
            st.success(f"Success! {len(results)} items analyzed.")
            st.dataframe(df, use_container_width=True)
        else:
            st.error("No valid items found. Try switching the 'API Protocol' dropdown at the top.")

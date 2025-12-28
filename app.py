import streamlit as st
import requests
import pandas as pd
import json
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="BDO Final Fix", layout="wide")
st.title("🛡️ BDO Global Scanner (Safe Mode)")

# --- CONFIG ---
# KNOWN NON-MARKET ITEMS (Vendor items, trash, etc that crash the API)
BLACKLIST_IDS = {
    5600,  # Weeds
    9059,  # Mineral Water
    9001,  # Salt
    9002,  # Sugar
    9005,  # Leavening Agent
    9017,  # Cooking Wine
    9066,  # Vinegar (Craftable but sometimes glitchy on API?)
    9016,  # Deep Frying Oil
    9015,  # Olive Oil
    9018,  # Base Sauce
    6656,  # Purified Water (Keep just in case)
    6655,  # Bottle of Clean Water
}

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # V2 API usually works best with lowercase region
    region = st.selectbox("Region", ["na", "eu", "sea", "kr", "sa", "ru", "jp"])
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

# --- 2. SMART API FETCH ---
def get_market_smart(ids, reg):
    market = {}
    # Filter out Blacklisted items immediately
    safe_ids = list(set([int(i) for i in ids if int(i) not in BLACKLIST_IDS]))
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    bar = st.progress(0)
    status = st.empty()
    
    # Use small batches. If a batch fails, we fall back to single-fetch for that batch.
    batch_size = 20
    
    for i in range(0, len(safe_ids), batch_size):
        batch = safe_ids[i:i+batch_size]
        if not batch: continue
        
        url = f"https://api.arsha.io/v2/{reg}/price?id={','.join(map(str, batch))}&lang=en"
        
        try:
            resp = requests.get(url, headers=headers, timeout=5, verify=False)
            
            # CASE A: SUCCESS
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        pid = int(item.get('id', 0))
                        if pid != 0:
                            market[pid] = {
                                'p': int(item.get('pricePerOne', 0)),
                                's': int(item.get('currentStock', 0))
                            }
                else:
                    # Weird non-list response? Treat as failure
                    raise ValueError("API returned non-list")

            # CASE B: FAILURE (500/404) -> Fallback to Single Item Fetch
            else:
                # One of these items is bad. Try them one by one.
                for single_id in batch:
                    try:
                        s_url = f"https://api.arsha.io/v2/{reg}/price?id={single_id}&lang=en"
                        s_resp = requests.get(s_url, headers=headers, timeout=2, verify=False)
                        if s_resp.status_code == 200:
                            s_data = s_resp.json()
                            if isinstance(s_data, list) and s_data:
                                item = s_data[0]
                                market[int(item['id'])] = {
                                    'p': int(item['pricePerOne']),
                                    's': int(item['currentStock'])
                                }
                    except: pass # Skip truly broken items
                    time.sleep(0.05) # Tiny delay

        except Exception as e:
            print(f"Batch failed: {e}")
        
        # Update UI
        bar.progress(min((i + batch_size) / len(safe_ids), 1.0))
        status.caption(f"Scanning... Found prices for {len(market)} items")
        time.sleep(0.1)
        
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
col_test, col_run = st.columns([1, 2])

with col_test:
    if st.button("🧪 Connection Test", type="secondary"):
        st.write("Attempting to fetch **Beer (9213)**...")
        try:
            url = f"https://api.arsha.io/v2/{region}/price?id=9213&lang=en"
            r = requests.get(url, timeout=5, verify=False, headers={'User-Agent': 'Mozilla/5.0'})
            st.write(f"**Status:** {r.status_code}")
            if r.status_code == 200:
                st.success("✅ Success!")
                st.json(r.json())
            else:
                st.error("❌ Failed.")
                st.write(f"Raw Response: {r.text}")
        except Exception as e:
            st.error(f"❌ Connection Error: {e}")

with col_run:
    if st.button("🚀 START SAFE SCAN", type="primary"):
        if not db:
            st.error("No recipes.")
        else:
            # Gather IDs
            all_ids = set()
            for r in db:
                all_ids.add(r['product']['id'])
                for g in r.get('ingredients', []):
                    for i in g.get('item', []):
                        all_ids.add(i['id'])
            
            st.info(f"Scanning {len(all_ids)} items (Skipping {len(BLACKLIST_IDS)} known vendor items)...")
            market = get_market_smart(list(all_ids), region)
            
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
                    
                    # Check if this ingredient group uses a Vendor Item
                    is_vendor_group = False
                    for o in opts:
                        if o['id'] in BLACKLIST_IDS:
                            is_vendor_group = True
                            # Assume negligible cost for vendor items or add manual price if needed
                            # For now, we assume 0 or low cost, but mark it as 'possible'
                            valid_prices.append(0) 
                    
                    if not is_vendor_group:
                        for o in opts:
                            oid = o['id']
                            if oid in market:
                                if market[oid]['s'] >= min_stock:
                                    valid_prices.append(market[oid]['p'])
                    
                    if valid_prices:
                        # Use cheapest ingredient
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
                st.success(f"Generated data for {len(results)} items.")
                st.dataframe(df, use_container_width=True, column_config={
                    "Profit/Hr": st.column_config.NumberColumn(format="%d"),
                    "Cost": st.column_config.NumberColumn(format="%d"),
                    "Price": st.column_config.NumberColumn(format="%d"),
                })
            else:
                st.error("No items found. Run the 'Connection Test' on the left to diagnose.")

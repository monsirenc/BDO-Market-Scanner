import streamlit as st
import requests
import pandas as pd
import json
import time
import urllib3

# Suppress SSL warnings (common in cloud deployments)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="BDO Scanner Final", layout="wide")
st.title("🛡️ BDO Global Scanner (Connection Fixed)")

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Arsha API v2 generally prefers lowercase (na, eu, sea)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr", "sa", "men", "ru", "jp"])
with col3:
    min_stock = st.number_input("Min Stock", 0, step=10)

tax = 0.845 # VP assumed

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
                        # Force IDs to int to ensure matching works
                        r['product']['id'] = int(r['product']['id'])
                        if 'ingredients' in r:
                            for group in r['ingredients']:
                                if 'item' in group:
                                    for item in group['item']:
                                        item['id'] = int(item['id'])
                        r['_src'] = f
                        db.append(r)
                    except ValueError:
                        continue 
                log.append(f"✅ {f}: Loaded {len(recipes)} recipes")
        except Exception as e:
            log.append(f"❌ {f}: Failed - {e}")
    return db, log

# --- 2. MARKET API (Configured for Success) ---
def get_market(ids, reg):
    market = {}
    # Dedup IDs
    id_list = list(set([str(i) for i in ids]))
    
    # Headers are required to avoid being blocked (403/Empty Response)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Progress UI
    bar = st.progress(0)
    status = st.empty()
    
    # Debug Expander
    with st.expander("🔌 Connection Debugger", expanded=False):
        st.info("If you see 0 items, check the logs below.")
        log_area = st.empty()

    # Batching: Size 10 is safe. 
    batch_size = 10
    
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        if not batch: continue
        
        # USE LOWERCASE REGION for v2
        url = f"https://api.arsha.io/v2/{reg.lower()}/price?id={','.join(batch)}"
        
        try:
            # verify=False prevents SSL handshake errors on Streamlit Cloud
            resp = requests.get(url, headers=headers, timeout=5, verify=False)
            
            # Debug log first batch only
            if i == 0:
                log_area.code(f"URL: {url}\nStatus: {resp.status_code}\nResponse: {resp.text[:200]}...")

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for x in data:
                        # Safe extraction of data
                        pid = int(x.get('id', 0))
                        if pid != 0:
                            market[pid] = {
                                'p': int(x.get('pricePerOne', 0)),
                                's': int(x.get('currentStock', 0))
                            }
                else:
                    # Sometimes API returns a dict with 'result' key? 
                    # If so, handle it here. (Arsha v2 usually uses List)
                    pass
            elif resp.status_code == 429:
                time.sleep(1) # Backoff
            
        except Exception as e:
            pass # Skip failed batches
        
        # UI Updates
        current_progress = min((i + batch_size) / len(id_list), 1.0)
        bar.progress(current_progress)
        status.caption(f"Scanned {i}/{len(id_list)} items... Found {len(market)} prices.")
        time.sleep(0.1) # Be polite to API
        
    bar.empty()
    status.empty()
    return market

# --- 3. CALCULATOR LOGIC ---
db, logs = load_data_strict()

# System Status
with st.expander("📂 File Status", expanded=False):
    for l in logs:
        st.write(l)

if st.button("🚀 RUN SCAN", type="primary"):
    if not db:
        st.error("No recipes loaded.")
    else:
        # 1. Gather IDs
        all_ids = set()
        for r in db:
            all_ids.add(r['product']['id'])
            for g in r.get('ingredients', []):
                for i in g.get('item', []):
                    all_ids.add(i['id'])
        
        # 2. API Call
        with st.spinner(f"Fetching market data for {len(all_ids)} items..."):
            market = get_market(all_ids, region)
        
        # 3. Calculate
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
                    oid = o['id']
                    if oid in market:
                        if market[oid]['s'] >= min_stock:
                            valid_prices.append(market[oid]['p'])
                
                if valid_prices:
                    cost += (min(valid_prices) * g['amount'])
                else:
                    possible = False
                    missing.append(opts[0]['name'] if opts else "?")
            
            # Profit Logic
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
                    "Missing": ", ".join(missing[:2]),
                    "Type": r['_src'].split(".")[0].replace("recipes", "")
                })

        # 4. Display
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values("Profit/Hr", ascending=False)
            
            st.success(f"Done! Analyzing {len(results)} profitable recipes.")
            
            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "Profit/Hr": st.column_config.NumberColumn(format="%d silver"),
                    "Cost": st.column_config.NumberColumn(format="%d"),
                    "Price": st.column_config.NumberColumn(format="%d"),
                }
            )
        else:
            st.error("No items found.")
            st.warning("Check the 'Connection Debugger' section above. If Response is '[]', the API has no data for this region.")

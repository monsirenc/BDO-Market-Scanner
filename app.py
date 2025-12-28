import streamlit as st
import requests
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO Strict Fix", layout="wide")
st.title("🛡️ BDO Global Scanner (Batch Fix)")

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Ensure region matches API expected format
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
with col3:
    min_stock = st.number_input("Min Stock", 0, step=10)

tax = 0.845 # VP assumed

# --- 1. ROBUST DATA LOADER ---
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
                        # FORCE ID CONVERSION
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

# --- 2. MARKET API (ROBUST BATCHING) ---
def get_market(ids, reg):
    market = {}
    id_list = list(set([str(i) for i in ids]))
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Progress Bar
    bar = st.progress(0)
    status = st.empty()
    
    # --- FIX: Reduced batch size to 10 to prevent 500 Errors ---
    batch_size = 10
    
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        if not batch: continue
        
        url = f"https://api.arsha.io/v2/{reg}/price?id={','.join(batch)}"
        
        # --- FIX: Retry Logic ---
        success = False
        for attempt in range(3): # Try 3 times
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        for x in data:
                            pid = int(x.get('id', 0))
                            if pid != 0:
                                market[pid] = {
                                    'p': int(x.get('pricePerOne', 0)),
                                    's': int(x.get('currentStock', 0))
                                }
                    success = True
                    break # Success, exit retry loop
                elif resp.status_code == 429:
                    time.sleep(2) # Wait longer if rate limited
                else:
                    time.sleep(0.5) # Wait a bit before retry
            except Exception:
                time.sleep(0.5)
        
        if not success:
            print(f"Batch {i} failed after 3 attempts.")

        # Update progress
        current_progress = min((i + batch_size) / len(id_list), 1.0)
        bar.progress(current_progress)
        status.text(f"Fetching prices... {len(market)} items found")
        
        # --- FIX: Polite Delay ---
        time.sleep(0.2) 
        
    bar.empty()
    status.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

with st.expander("System Status", expanded=True):
    for l in logs:
        st.write(l)

if st.button("🚀 RUN SCAN", type="primary"):
    if not db:
        st.error("No recipes loaded.")
    else:
        # Collect IDs
        all_ids = set()
        for r in db:
            all_ids.add(r['product']['id'])
            for g in r.get('ingredients', []):
                for i in g.get('item', []):
                    all_ids.add(i['id'])
        
        market = get_market(all_ids, region)
        
        results = []
        
        for r in db:
            pid = r['product']['id']
            pname = r['product']['name']
            
            market_entry = market.get(pid, {})
            sell_price = market_entry.get('p', 0)
            
            cost = 0
            possible = True
            missing_mats = []
            
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
                    missing_mats.append(opts[0]['name'] if opts else "Unknown")
            
            y_mult = 2.5 if "Processing" in r['_src'] else 1.0 + (mastery/4000)*0.3 + 1.35
            
            revenue = sell_price * y_mult * tax
            profit = revenue - cost
            
            if sell_price > 0:
                results.append({
                    "Item": pname,
                    "Profit/Hr": int(profit * 900),
                    "Cost": int(cost),
                    "Price": int(sell_price),
                    "Stock": "✅" if possible else f"❌ Missing: {','.join(missing_mats[:1])}...",
                    "Source": r['_src'].replace("recipes", "").replace(".json", "")
                })

        if results:
            df = pd.DataFrame(results)
            df = df.sort_values("Profit/Hr", ascending=False)
            
            st.success(f"Generated data for {len(results)} items.")
            
            st.dataframe(
                df, 
                use_container_width=True,
                column_config={
                    "Profit/Hr": st.column_config.NumberColumn(format="%d"),
                    "Cost": st.column_config.NumberColumn(format="%d"),
                    "Price": st.column_config.NumberColumn(format="%d"),
                }
            )
        else:
            st.error("Still 0 items found. The API might be down or blocking requests.")
            st.write(f"Total IDs attempted: {len(all_ids)}")
            st.write(f"Total Market Prices Successfully Fetched: {len(market)}")

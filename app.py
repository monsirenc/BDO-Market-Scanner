import streamlit as st
import cloudscraper
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO Final Bypass", layout="wide")
st.title("🛡️ BDO Global Scanner (Cloudflare Bypass)")

# --- CONFIG ---
# Initializes the Cloudflare bypasser
scraper = cloudscraper.create_scraper() 

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Arsha V2 is sensitive. We will try both cases if one fails.
    region_input = st.selectbox("Region", ["NA", "EU", "SEA", "KR", "SA", "RU", "JP"])
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

# --- 2. ROBUST API FETCH ---
def get_market_bypass(ids, reg):
    market = {}
    # Filter trash IDs that act as "poison pills" for the API
    BLACKLIST = {5600, 9059, 9001, 9002, 9005, 9017, 9066, 9016, 9015, 9018, 6656, 6655}
    safe_ids = list(set([int(i) for i in ids if int(i) not in BLACKLIST]))
    
    bar = st.progress(0)
    status = st.empty()
    
    # Batch size 20 is safe for V2
    batch_size = 20
    
    for i in range(0, len(safe_ids), batch_size):
        batch = safe_ids[i:i+batch_size]
        if not batch: continue
        
        # Try lowercase region first (na), then uppercase (NA)
        for r_code in [reg.lower(), reg.upper()]:
            url = f"https://api.arsha.io/v2/{r_code}/price?id={','.join(map(str, batch))}&lang=en"
            try:
                # USE SCRAPER INSTEAD OF REQUESTS
                resp = scraper.get(url, timeout=10)
                
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
                        break # Success, stop trying region codes
            except Exception:
                pass
        
        # UI Updates
        bar.progress(min((i + batch_size) / len(safe_ids), 1.0))
        status.text(f"Bypassing... Found {len(market)} prices")
        time.sleep(0.1) # Respect rate limits
        
    bar.empty()
    status.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

with st.expander("System Status", expanded=False):
    for l in logs:
        st.write(l)

# --- DIAGNOSTIC BUTTON ---
if st.button("🧪 Force Test Connection (Cloudscraper)"):
    st.info("Attempting to bypass Cloudflare block...")
    try:
        # Try fetching just Beer (9213)
        url = f"https://api.arsha.io/v2/{region_input.lower()}/price?id=9213"
        r = scraper.get(url, timeout=10)
        
        if r.status_code == 200:
            st.success(f"✅ CONNECTION ESTABLISHED! Status: {r.status_code}")
            st.json(r.json())
        else:
            st.error(f"❌ Blocked. Status: {r.status_code}")
            st.code(r.text) # Show exactly what the server said
    except Exception as e:
        st.error(f"❌ Error: {e}")

# --- SCAN BUTTON ---
if st.button("🚀 RUN SCAN", type="primary"):
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
        
        market = get_market_bypass(list(all_ids), region_input)
        
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
                
                # Check blacklist
                if opts and opts[0]['id'] in [5600, 9059, 9001, 9002, 9005]:
                    valid_prices.append(0)
                else:
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
            st.success(f"Success! {len(results)} items analyzed.")
            st.dataframe(df, use_container_width=True)
        else:
            st.error("No items found. If 'Force Test' failed above, the Streamlit server IP is completely banned.")

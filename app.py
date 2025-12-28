import streamlit as st
import requests
import pandas as pd
import json
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="BDO Tank Mode", layout="wide")
st.title("🛡️ BDO Global Scanner (Tank Mode)")

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Arsha V2 usually wants lowercase 'na', 'eu', etc.
    region = st.selectbox("Region", ["na", "eu", "sea", "kr", "sa", "men", "ru", "jp"])
with col3:
    min_stock = st.number_input("Min Stock", 0, step=10)

tax = 0.845 

# --- 1. DATA LOADER (UNCHANGED) ---
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

# --- 2. SINGLE ITEM FETCH (THE FIX) ---
def fetch_single_item(session, pid, reg):
    """
    Fetches a single item. If it fails (500), it returns None 
    so it doesn't crash the whole app.
    """
    url = f"https://api.arsha.io/v2/{reg}/price?id={pid}&lang=en"
    try:
        # verify=False is crucial for Streamlit Cloud
        resp = session.get(url, timeout=5, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            # Arsha returns a LIST even for single items
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                return {
                    'id': int(item.get('id', 0)),
                    'p': int(item.get('pricePerOne', 0)),
                    's': int(item.get('currentStock', 0))
                }
    except:
        pass
    return None

# --- 3. MARKET MANAGER (THREADED) ---
def get_market_threaded(ids, reg):
    market = {}
    id_list = list(set([int(i) for i in ids]))
    
    # Session for connection pooling (faster)
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    # Progress UI
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Use 10 threads to fetch fast but safely
    total = len(id_list)
    completed = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        futures = {executor.submit(fetch_single_item, session, pid, reg): pid for pid in id_list}
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                market[result['id']] = {'p': result['p'], 's': result['s']}
            
            completed += 1
            if completed % 10 == 0:
                progress_bar.progress(min(completed / total, 1.0))
                status_text.text(f"Scanning... {len(market)} prices found (Checked {completed}/{total})")
                
    progress_bar.empty()
    status_text.empty()
    return market

# --- 4. MAIN APP LOGIC ---
db, logs = load_data_strict()

with st.expander("📂 System Status", expanded=False):
    for l in logs:
        st.write(l)

# --- ONE CLICK TEST BUTTON ---
st.write("---")
col_test, col_run = st.columns([1, 2])

with col_test:
    if st.button("🧪 Test Connection (Beer)", type="secondary"):
        with st.spinner("Testing connection to Arsha..."):
            # Beer ID = 9213
            test_res = get_market_threaded([9213], region)
            if 9213 in test_res:
                st.success(f"✅ SUCCESS! Beer Price: {test_res[9213]['p']:,} silver")
                st.json(test_res)
            else:
                st.error("❌ Connection Failed. API might be down or Region is wrong.")

with col_run:
    if st.button("🚀 RUN FULL SCAN", type="primary"):
        if not db:
            st.error("No recipes.")
        else:
            all_ids = set()
            for r in db:
                all_ids.add(r['product']['id'])
                for g in r.get('ingredients', []):
                    for i in g.get('item', []):
                        all_ids.add(i['id'])
            
            st.info(f"Targeting {len(all_ids)} unique items. Using 'Tank Mode' (Threaded Single Fetch)...")
            market = get_market_threaded(all_ids, region)
            
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
                        "Notes": f"Missing: {missing[0]}" if missing else ""
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
                st.error("No items found. Try the Test button to verify connectivity.")

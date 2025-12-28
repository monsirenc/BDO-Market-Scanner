import streamlit as st
import requests
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO Strict Fix", layout="wide")
st.title("🛡️ BDO Global Scanner (Fixed)")

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Ensure region matches API expected format (usually lowercase is fine for Arsha v2)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
with col3:
    # Set default to 0 so we see EVERYTHING, even out-of-stock items
    min_stock = st.number_input("Min Stock", 0, step=10)

tax = 0.845 # VP assumed

# --- 1. ROBUST DATA LOADER ---
@st.cache_data
def load_data_strict():
    db = []
    log = []
    # Ensure these filenames match exactly what is in your folder
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    
    for f in files:
        try:
            with open(f, 'r') as file:
                raw = json.load(file)
                # LifeBDO format: root -> "recipes" list
                recipes = raw.get('recipes', [])
                
                for r in recipes:
                    # FORCE ID CONVERSION HERE
                    try:
                        # Handle Product ID (Fixes "11527" string vs 4680 int issue)
                        r['product']['id'] = int(r['product']['id'])
                        
                        # Handle Ingredient IDs
                        if 'ingredients' in r:
                            for group in r['ingredients']:
                                if 'item' in group:
                                    for item in group['item']:
                                        item['id'] = int(item['id'])
                                        
                        r['_src'] = f
                        db.append(r)
                    except ValueError:
                        continue # Skip malformed entries
                        
                log.append(f"✅ {f}: Loaded {len(recipes)} recipes")
        except Exception as e:
            log.append(f"❌ {f}: Failed - {e}")
            
    return db, log

# --- 2. MARKET API (FIXED) ---
def get_market(ids, reg):
    market = {}
    # Dedup and ensure strings for URL
    id_list = list(set([str(i) for i in ids]))
    
    # CRITICAL FIX: Add User-Agent headers to prevent blocking
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Progress Bar
    bar = st.progress(0)
    status = st.empty()
    
    # Batch size reduced to 50 to prevent URL length errors
    batch_size = 50
    total_batches = len(id_list) // batch_size + 1
    
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        if not batch: continue
        
        # Updated to v2 endpoint which is more stable
        url = f"https://api.arsha.io/v2/{reg}/price?id={','.join(batch)}"
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                
                # Check if data is a list (Arsha v2 standard)
                if isinstance(data, list):
                    for x in data:
                        # Arsha v2 fields: 'pricePerOne', 'currentStock'
                        # We use .get() to be safe against missing keys
                        pid = int(x.get('id', 0))
                        if pid != 0:
                            market[pid] = {
                                'p': int(x.get('pricePerOne', 0)),
                                's': int(x.get('currentStock', 0))
                            }
            else:
                st.warning(f"Batch failed: {resp.status_code}")
                
        except Exception as e:
            print(f"Fetch error: {e}")
        
        # Update progress
        current_progress = min((i + batch_size) / len(id_list), 1.0)
        bar.progress(current_progress)
        status.text(f"Fetching prices... {len(market)} items found")
        
        # Slight delay to respect API rate limits
        time.sleep(0.1)
        
    bar.empty()
    status.empty()
    return market

# --- 3. MAIN LOGIC ---
db, logs = load_data_strict()

# Status Check
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
        
        # Get Prices
        market = get_market(all_ids, region)
        
        results = []
        
        for r in db:
            pid = r['product']['id']
            pname = r['product']['name']
            
            # Allow items even if price is missing (set to 0 for visibility)
            market_entry = market.get(pid, {})
            sell_price = market_entry.get('p', 0)
            
            # Calculate Cost
            cost = 0
            possible = True
            missing_mats = []
            
            for g in r.get('ingredients', []):
                # Find cheapest valid ingredient in group
                opts = g.get('item', [])
                valid_prices = []
                
                for o in opts:
                    oid = o['id']
                    if oid in market:
                        # Check min stock setting
                        if market[oid]['s'] >= min_stock:
                            valid_prices.append(market[oid]['p'])
                
                if valid_prices:
                    cost += (min(valid_prices) * g['amount'])
                else:
                    possible = False
                    # Collect names of missing mats for debugging
                    missing_mats.append(opts[0]['name'] if opts else "Unknown")
            
            # Calculate Yield
            # Processing is flat ~2.5. Cooking/Alch is Mastery
            y_mult = 2.5 if "Processing" in r['_src'] else 1.0 + (mastery/4000)*0.3 + 1.35
            
            revenue = sell_price * y_mult * tax
            profit = revenue - cost
            
            # Add to list if we have a sell price (even if profit is neg)
            if sell_price > 0:
                results.append({
                    "Item": pname,
                    "Profit/Hr": int(profit * 900), # Assuming 900 crafts/hr
                    "Cost": int(cost),
                    "Price": int(sell_price),
                    "Stock": "✅" if possible else f"❌ Missing: {','.join(missing_mats[:1])}...",
                    "Source": r['_src'].replace("recipes", "").replace(".json", "")
                })

        if results:
            df = pd.DataFrame(results)
            # Sorting
            df = df.sort_values("Profit/Hr", ascending=False)
            
            st.success(f"Generated data for {len(results)} items.")
            
            # Formating needed for clean display
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
            st.error("Still 0 items. Checking debug dump:")
            # Debug view
            st.write(f"Total IDs to fetch: {len(all_ids)}")
            st.write(f"Total Market Prices Found: {len(market)}")
            if len(market) > 0:
                st.write("Sample Market Data:", list(market.items())[:3])
            else:
                st.warning("The API returned 0 items. Check your internet connection or region code.")

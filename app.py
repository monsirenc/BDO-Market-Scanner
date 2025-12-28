import streamlit as st
import requests
import pandas as pd
import json
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="BDO Deep Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Deep Diagnostic Mode")

# --- DEBUG: SHOW LOADED STRUCTURE ---
st.write("### 🔍 1. File Structure Check")

@st.cache_data
def load_data_strict():
    """Loads data and strictly enforces structure."""
    all_recipes = []
    # Filenames must match GitHub exactly
    files = ["recipesProcessing.json", "recipesCooking.json", "recipesAlchemy.json"]
    
    status_msg = []
    
    for f_name in files:
        try:
            with open(f_name, 'r') as f:
                raw = json.load(f)
                # LifeBDO format check: does "recipes" key exist?
                if "recipes" in raw:
                    count = 0
                    for r in raw["recipes"]:
                        # Tag category
                        r["_cat"] = "Processing" if "Processing" in f_name else "Cooking/Alchemy"
                        all_recipes.append(r)
                        count += 1
                    status_msg.append(f"✅ **{f_name}**: Successfully loaded {count} recipes.")
                else:
                    status_msg.append(f"❌ **{f_name}**: Failed. JSON missing 'recipes' key.")
        except FileNotFoundError:
            status_msg.append(f"❌ **{f_name}**: File not found in repo.")
        except Exception as e:
            status_msg.append(f"❌ **{f_name}**: Error - {str(e)}")
            
    return all_recipes, status_msg

db, logs = load_data_strict()

# Print status to screen
for l in logs:
    st.markdown(l)

# Show the first recipe to prove data is real
if db:
    with st.expander("Click to see raw data of first recipe (Debugging)"):
        st.json(db[0])

# --- MARKET API ---
def fetch_market_strict(ids, region_code):
    price_map = {}
    # Deduplicate and clean IDs
    clean_ids = list(set([str(i) for i in ids if str(i).isdigit()]))
    
    st.write(f"### 📡 2. Querying API for {len(clean_ids)} items...")
    bar = st.progress(0)
    
    # Batch size 100
    for i in range(0, len(clean_ids), 100):
        batch = clean_ids[i : i+100]
        url = f"https://api.arsha.io/v1/{region_code}/price?id={','.join(batch)}"
        
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                for item in resp.json():
                    # STORE AS INTEGER TO MATCH JSON
                    try:
                        pid = int(item['id'])
                        price_map[pid] = {
                            'price': int(item['price']),
                            'stock': int(item['stock'])
                        }
                    except: pass
        except: pass
        
        bar.progress(min((i+100)/len(clean_ids), 1.0))
        
    bar.empty()
    return price_map

# --- MAIN SCANNER ---
if st.button("🚀 RUN DEEP SCAN", type="primary"):
    if not db:
        st.error("No data loaded. Cannot scan.")
    else:
        # 1. Gather IDs
        scan_ids = set()
        for r in db:
            scan_ids.add(r['product']['id']) # Product ID
            for group in r.get('ingredients', []):
                for item in group.get('item', []):
                    scan_ids.add(item['id']) # Ingredient IDs
        
        # 2. Get Prices
        market = fetch_market_strict(scan_ids, "na") # Defaulting to NA for test
        
        # 3. Calculate
        results = []
        
        for r in db:
            pid = int(r['product']['id'])
            
            # If product has no price, skip
            if pid not in market: continue
            
            sell_price = market[pid]['price']
            stock_count = market[pid]['stock']
            
            total_cost = 0
            is_valid = True
            
            # Loop ingredients
            for group in r.get('ingredients', []):
                # Find cheapest option in group (e.g. Any Timber)
                options = group.get('item', [])
                cheapest_price = 999999999
                found_opt = False
                
                for opt in options:
                    oid = int(opt['id'])
                    if oid in market:
                        # We accept 0 stock items now, but warn about them
                        p = market[oid]['price']
                        if p < cheapest_price:
                            cheapest_price = p
                            found_opt = True
                
                if found_opt:
                    total_cost += (cheapest_price * group['amount'])
                else:
                    # If absolutely no price found for any option, fail
                    is_valid = False
                    break
            
            if is_valid:
                # 2025 Yields
                mult = 2.5 if r['_cat'] == "Processing" else 1.25 # Lower conservative yield for cook/alch
                
                # Simple Profit Calc
                profit = (sell_price * mult * 0.845) - total_cost
                
                results.append({
                    "Item": r['product']['name'],
                    "Type": r['_cat'],
                    "Profit": profit,
                    "Cost": total_cost,
                    "Price": sell_price,
                    "Product Stock": stock_count
                })
                
        # 4. Show Table
        if results:
            st.success(f"Scan complete! Found {len(results)} items.")
            df = pd.DataFrame(results)
            # Sort by Profit
            df = df.sort_values(by="Profit", ascending=False)
            st.dataframe(df, use_container_width=True)
        else:
            st.error("Still 0 items. This implies the Market API returned NO matching IDs for your recipes.")
            st.write("Debug Sample (Market Data):", list(market.keys())[:10])

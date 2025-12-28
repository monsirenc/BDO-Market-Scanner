import streamlit as st
import requests
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO Strict Fix", layout="wide")
st.title("🛡️ BDO Global Scanner (Type-Safe Fix)")

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
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

# --- 2. MARKET API (Integer Forced) ---
def get_market(ids, reg):
    market = {}
    # Dedup and ensure strings for URL
    id_list = list(set([str(i) for i in ids]))
    
    # Progress Bar
    bar = st.progress(0)
    status = st.empty()
    
    # Batch size 100
    for i in range(0, len(id_list), 100):
        batch = id_list[i:i+100]
        url = f"https://api.arsha.io/v1/{reg}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                for x in resp.json():
                    # FORCE INTEGER KEY matches Loader
                    market[int(x['id'])] = {
                        'p': int(x['price']),
                        's': int(x['stock'])
                    }
        except: pass
        
        bar.progress(min((i+100)/len(id_list), 1.0))
        status.text(f"Fetching prices... {len(market)} items found")
        
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
            sell_price = market.get(pid, {}).get('p', 0)
            
            # Calculate Cost
            cost = 0
            possible = True
            
            for g in r.get('ingredients', []):
                # Find cheapest valid ingredient in group
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
                    # Don't break, just mark as impossible but keep checking other mats
            
            # Calculate Yield
            # Processing is flat ~2.5. Cooking/Alch is Mastery
            y_mult = 2.5 if "Processing" in r['_src'] else 1.0 + (mastery/4000)*0.3 + 1.35
            
            revenue = sell_price * y_mult * tax
            profit = revenue - cost
            
            # Add to list if we have a sell price (even if profit is neg)
            if sell_price > 0:
                results.append({
                    "Item": pname,
                    "Profit/Hr": profit * 900,
                    "Cost": cost,
                    "Stock": "✅" if possible else "❌ Low Mats",
                    "Source": r['_src'].replace("recipes", "").replace(".json", "")
                })

        if results:
            df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
            st.success(f"Generated data for {len(results)} items.")
            st.dataframe(df, use_container_width=True)
        else:
            st.error("Still 0 items. Checking debug dump:")
            st.write("First 5 Market Keys:", list(market.keys())[:5])
            st.write("First 5 Recipe IDs:", [r['product']['id'] for r in db[:5]])

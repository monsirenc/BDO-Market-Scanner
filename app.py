import streamlit as st
import requests
import pandas as pd
import json
import time

# 1. PAGE CONFIG MUST BE FIRST
st.set_page_config(page_title="BDO Profit Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Diagnostic Scanner")

# --- 2. SETTINGS (MOVED TO MAIN PAGE) ---
st.write("### 🛠️ Scanner Settings")
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
with col2:
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
with col3:
    # Set default to 0 to ensure we find ANY recipe
    min_stock = st.number_input("Min Stock Required", value=0, min_value=0, step=10)

tax_rate = 0.845 # Assuming Value Pack for simplicity

# --- 3. DATA LOADING ---
@st.cache_data
def load_database():
    recipes = []
    # Names must match GitHub exactly
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    
    log = []
    for f in files:
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                # Handle LifeBDO 'recipes' key
                content = data.get('recipes', [])
                for r in content:
                    r['type'] = "Processing" if "Processing" in f else "Cooking/Alchemy"
                    recipes.append(r)
                log.append(f"✅ Loaded {len(content)} recipes from {f}")
        except Exception as e:
            log.append(f"❌ Error loading {f}: {e}")
            
    return recipes, log

# --- 4. MARKET API ---
def get_prices(id_list, reg):
    price_map = {}
    ids = list(set([str(i) for i in id_list]))
    
    status = st.empty()
    bar = st.progress(0)
    
    # Batch size 100
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        url = f"https://api.arsha.io/v1/{reg}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                for item in resp.json():
                    # Force Integer Keys
                    price_map[int(item['id'])] = {
                        'price': int(item['price']),
                        'stock': int(item['stock'])
                    }
        except: pass
        bar.progress(min((i+100)/len(ids), 1.0))
        status.text(f"Fetching prices... ({len(price_map)} items found)")
        
    bar.empty()
    status.empty()
    return price_map

# --- 5. MAIN LOGIC ---
db, logs = load_database()

# Show File Status
with st.expander("📂 Database Status (Click to Expand)", expanded=True):
    for l in logs:
        st.write(l)

if st.button("🚀 START SCAN", type="primary"):
    if not db:
        st.error("No recipes loaded.")
    else:
        # Collect IDs
        all_ids = set()
        for r in db:
            all_ids.add(r['product']['id'])
            for group in r.get('ingredients', []):
                for item in group.get('item', []):
                    all_ids.add(item['id'])
        
        # Get Prices
        market = get_prices(all_ids, region)
        
        # Calculate
        profitable = []
        failures = [] # Track why things fail
        
        for r in db:
            pid = int(r['product']['id'])
            pname = r['product']['name']
            
            # Check Product Price
            if pid not in market:
                failures.append({"Item": pname, "Reason": "Product price missing on Market"})
                continue
                
            sell_price = market[pid]['price']
            total_cost = 0
            craftable = True
            missing_ing = ""
            
            # Check Ingredients
            for group in r.get('ingredients', []):
                # Find cheapest option in group
                options = group.get('item', [])
                cheapest = float('inf')
                found_in_group = False
                
                for opt in options:
                    oid = int(opt['id'])
                    if oid in market:
                        # Check Stock Threshold
                        if market[oid]['stock'] >= min_stock:
                            if market[oid]['price'] < cheapest:
                                cheapest = market[oid]['price']
                                found_in_group = True
                
                if found_in_group:
                    total_cost += (cheapest * group['amount'])
                else:
                    craftable = False
                    # Log the first item in the missing group
                    missing_name = options[0]['name'] if options else "Unknown"
                    missing_ing = f"Missing/Low Stock: {missing_name}"
                    break
            
            if craftable:
                mult = 2.5 if r['type'] == "Processing" else 1.0 + (mastery/4000)*0.3 + 1.35
                profit = ((sell_price * mult) * tax_rate) - total_cost
                
                if profit > 0:
                    profitable.append({
                        "Item": pname,
                        "Silver/Hr": profit * 900,
                        "Cost": total_cost,
                        "Type": r['type']
                    })
            else:
                failures.append({"Item": pname, "Reason": missing_ing})

        # --- RESULTS ---
        st.divider()
        if profitable:
            st.success(f"Found {len(profitable)} Profitable Recipes!")
            df = pd.DataFrame(profitable).sort_values("Silver/Hr", ascending=False)
            st.dataframe(df, use_container_width=True)
        else:
            st.error("⚠️ 0 Profitable items found.")
            
        # --- DIAGNOSTICS TABLE ---
        if len(failures) > 0:
            st.warning(f"⚠️ {len(failures)} Recipes Failed. Here is why (First 20):")
            fail_df = pd.DataFrame(failures[:20])
            st.table(fail_df)

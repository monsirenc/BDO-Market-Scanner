import streamlit as st
import requests
import pandas as pd
import json
import time
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="BDO Category Scanner", layout="wide")
st.title("🛡️ BDO Global Scanner (Category Mode)")

# --- CONFIG ---
# These are the BDO Market Category IDs we need to build our database
# Format: (MainCategory, SubCategory, Name)
# 25=Material, 35=Consumable
CATEGORIES_TO_SCAN = [
    (25, 1, "Ores & Gems"),
    (25, 2, "Plants & Grains"),
    (25, 6, "Meats & Bloods"),
    (25, 7, "Processed Materials"), # Dough, Flour, Planks, Ingots
    (25, 8, "Timber"),
    (35, 1, "Food & Meals"),       # Cooking products
    (35, 2, "Potions & Elixirs"),  # Alchemy products
    (35, 6, "Pet Feed")
]

# --- SETTINGS ---
col1, col2, col3 = st.columns(3)
with col1:
    mastery = st.number_input("Mastery", 2000, step=50)
with col2:
    # Lowercase usually best for this endpoint
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

# --- 2. CATEGORY API FETCH (The New Way) ---
def fetch_market_by_category(reg):
    market = {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Progress UI
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_cats = len(CATEGORIES_TO_SCAN)
    
    for idx, (main_cat, sub_cat, cat_name) in enumerate(CATEGORIES_TO_SCAN):
        status_text.text(f"Fetching Category: {cat_name}...")
        
        # Endpoint: GetWorldMarketSubList
        url = f"https://api.arsha.io/v2/{reg}/GetWorldMarketSubList?mainCategory={main_cat}&subCategory={sub_cat}&lang=en"
        
        try:
            # We use verify=False to ignore SSL errors on Streamlit Cloud
            resp = requests.get(url, headers=headers, timeout=10, verify=False)
            
            if resp.status_code == 200:
                data = resp.json()
                # Depending on API version, sometimes it's a list, sometimes a dict key
                # Arsha V2 List usually: [{"id": 123, "name": "Ore", "pricePerOne": 500, ...}, ...]
                
                # Check format
                items_list = []
                if isinstance(data, list):
                    items_list = data
                elif isinstance(data, dict) and 'detailList' in data:
                    items_list = data['detailList']
                
                # Process the batch
                count = 0
                for item in items_list:
                    # Safe extraction
                    try:
                        pid = int(item.get('id', 0))
                        price = int(item.get('pricePerOne', 0))
                        stock = int(item.get('count', 0)) # Note: key might be 'count' or 'currentStock'
                        
                        # Fallback for stock key
                        if stock == 0 and 'currentStock' in item:
                            stock = int(item['currentStock'])

                        if pid != 0:
                            market[pid] = {'p': price, 's': stock}
                            count += 1
                    except: pass
                
                # print(f"  -> Got {count} items from {cat_name}")
                
            else:
                st.warning(f"Failed to fetch {cat_name} (Code {resp.status_code})")
                
        except Exception as e:
            st.error(f"Error fetching {cat_name}: {e}")
            
        # Update Progress
        progress_bar.progress((idx + 1) / total_cats)
        time.sleep(0.5) # Polite delay
        
    progress_bar.empty()
    status_text.empty()
    return market

# --- 3. MAIN APP ---
db, logs = load_data_strict()

with st.expander("System Status", expanded=False):
    for l in logs:
        st.write(l)

# --- ONE BUTTON TO RULE THEM ALL ---
if st.button("🚀 RUN CATEGORY SCAN", type="primary"):
    if not db:
        st.error("No recipes.")
    else:
        # 1. Fetch Market Data (Bulk Mode)
        st.info("Fetching entire market categories. This avoids 'Bad ID' crashes.")
        market = fetch_market_by_category(region)
        
        if not market:
            st.error("Market data empty. The API Region might be down entirely.")
        else:
            st.success(f"Successfully cached {len(market)} market prices!")
            
            # 2. Calculate Profits
            results = []
            for r in db:
                pid = r['product']['id']
                pname = r['product']['name']
                
                # If product not in market (e.g. Imperial Delivery items), price is 0
                market_entry = market.get(pid, {})
                sell_price = market_entry.get('p', 0)
                
                cost = 0
                possible = True
                missing = []
                
                # Loop Ingredients
                for g in r.get('ingredients', []):
                    opts = g.get('item', [])
                    valid_prices = []
                    
                    # Vendor Item Logic (If item ID is known vendor trash, assume price 0 or skip)
                    # We assume vendor items are "Free" or handled externally for this simple calc
                    # But if it's a market item, we look it up.
                    
                    for o in opts:
                        oid = o['id']
                        # Check market DB
                        if oid in market:
                            if market[oid]['s'] >= min_stock:
                                valid_prices.append(market[oid]['p'])
                        # Fallback: If it's a vendor item (id < 1000 usually not strictly true but useful heuristc)
                        # or specifically known like mineral water (9059)
                        elif oid in [9059, 9001, 9002, 9005, 5600]:
                             valid_prices.append(50) # Assign dummy low cost for vendor mats
                    
                    if valid_prices:
                        cost += (min(valid_prices) * g['amount'])
                    else:
                        possible = False
                        missing.append(opts[0]['name'] if opts else "?")
                
                # Profit Calc
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
                        "Missing": ", ".join(missing[:2])
                    })

            # 3. Display
            if results:
                df = pd.DataFrame(results).sort_values("Profit/Hr", ascending=False)
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
                st.warning("No profitable recipes found (or prices missing for products).")

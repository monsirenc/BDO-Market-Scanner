import streamlit as st
import requests
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO Scanner Fix", layout="wide")
st.title("🛡️ BDO Global Scanner (Strict Mode)")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("Settings")
    mastery = st.number_input("Mastery", value=2000, step=50)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax_input = st.radio("Tax", ["Value Pack (15.5%)", "No VP (35%)"])
    tax_rate = 0.845 if "Value Pack" in tax_input else 0.65
    min_stock = st.slider("Min Component Stock", 0, 5000, 0)
    
    if st.button("🔄 Force Reload Data"):
        st.cache_data.clear()
        st.rerun()

# --- 1. DATA LOADER (LifeBDO Structure) ---
@st.cache_data
def load_database():
    """Loads JSON files and enforces Integer IDs."""
    data = []
    # Files must be in the same folder as app.py
    filenames = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    
    status_log = []
    
    for fname in filenames:
        try:
            with open(fname, 'r') as f:
                raw = json.load(f)
                # Access root 'recipes' list
                recipes = raw.get('recipes', [])
                
                for r in recipes:
                    # Determine category
                    cat = "Processing" if "Processing" in fname else "Cooking/Alchemy"
                    r['_category'] = cat 
                    data.append(r)
                    
            status_log.append(f"✅ Loaded {len(recipes)} from {fname}")
        except FileNotFoundError:
            status_log.append(f"❌ Missing file: {fname}")
        except Exception as e:
            status_log.append(f"❌ Error reading {fname}: {str(e)}")
            
    return data, status_log

# --- 2. MARKET API (Strict Integer Matching) ---
def fetch_prices(id_list, region_code):
    """Fetches prices and maps them by Integer ID."""
    price_map = {}
    
    # Clean and dedup IDs
    clean_ids = list(set([int(i) for i in id_list if str(i).isdigit()]))
    
    # Status bar for user feedback
    progress_text = st.empty()
    prog_bar = st.progress(0)
    
    batch_size = 100
    total_batches = (len(clean_ids) // batch_size) + 1
    
    for i in range(0, len(clean_ids), batch_size):
        batch = clean_ids[i : i + batch_size]
        id_str = ",".join(map(str, batch))
        
        url = f"https://api.arsha.io/v1/{region_code}/price?id={id_str}"
        
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                raw_data = resp.json()
                for item in raw_data:
                    # FORCE INTEGER KEY
                    item_id = int(item['id'])
                    price_map[item_id] = {
                        'price': int(item['price']),
                        'stock': int(item['stock'])
                    }
            time.sleep(0.05) # Tiny pause to be nice to API
        except:
            pass # Skip failed batches to keep moving
            
        # Update UI
        current_batch = (i // batch_size) + 1
        prog_bar.progress(min(current_batch / total_batches, 1.0))
        progress_text.text(f"Fetching market data... ({len(price_map)} items found)")
        
    prog_bar.empty()
    progress_text.empty()
    return price_map

# --- 3. MAIN LOGIC ---
db, logs = load_database()

# Show loading status in sidebar to verify files are read
with st.sidebar:
    with st.expander("File Status"):
        for log in logs:
            st.write(log)

if st.button("🚀 RUN SCAN"):
    if not db:
        st.error("No recipes loaded. Please check file names.")
    else:
        # Step A: Collect ALL IDs
        all_ids = set()
        for r in db:
            # Product ID
            all_ids.add(r['product']['id'])
            # Ingredient IDs (Nested Loop)
            if 'ingredients' in r:
                for group in r['ingredients']:
                    if 'item' in group:
                        for item in group['item']:
                            all_ids.add(item['id'])
                            
        st.info(f"Scanning {len(db)} recipes involving {len(all_ids)} unique items...")
        
        # Step B: Get Prices
        market = fetch_prices(all_ids, region)
        
        # Step C: Match & Calculate
        profitable_items = []
        debug_fail_count = 0
        debug_sample = None
        
        for r in db:
            pid = int(r['product']['id'])
            
            # Skip if product has no price data
            if pid not in market:
                debug_fail_count += 1
                continue
                
            sell_price = market[pid]['price']
            total_cost = 0
            is_craftable = True
            
            # Loop Ingredients
            for group in r.get('ingredients', []):
                cheapest_opt = float('inf')
                found_opt = False
                
                # Check "Any" groups (e.g., Any Grain)
                for item in group.get('item', []):
                    mid = int(item['id'])
                    if mid in market:
                        m_data = market[mid]
                        if m_data['stock'] >= min_stock:
                            if m_data['price'] < cheapest_opt:
                                cheapest_opt = m_data['price']
                                found_opt = True
                
                if found_opt:
                    total_cost += (cheapest_opt * group['amount'])
                else:
                    is_craftable = False
                    # Save one failure case for debugging
                    if debug_sample is None:
                        debug_sample = f"Failed on {r['product']['name']}: Missing ingredient group (e.g., ID {group['item'][0]['id']})"
                    break
            
            if is_craftable:
                # Calc Profit
                multiplier = 2.5 if r['_category'] == "Processing" else 1.0 + (mastery/4000)*0.3 + 1.35
                gross = sell_price * multiplier
                net = (gross * tax_rate) - total_cost
                
                profitable_items.append({
                    "Item": r['product']['name'],
                    "Category": r['_category'],
                    "Silver/Hr": net * 900, # Approx 1 sec per craft
                    "Profit/Craft": net,
                    "Cost": total_cost,
                    "Price": sell_price
                })

        # Step D: Display
        if profitable_items:
            df = pd.DataFrame(profitable_items)
            # Filter out negative profit
            df = df[df["Silver/Hr"] > 0]
            df = df.sort_values(by="Silver/Hr", ascending=False)
            
            st.success(f"Scan Done! Found {len(df)} profitable items.")
            st.dataframe(
                df.style.format({"Silver/Hr": "{:,.0f}", "Profit/Craft": "{:,.0f}", "Cost": "{:,.0f}", "Price": "{:,.0f}"}),
                use_container_width=True
            )
        else:
            st.error("No profitable items found.")
            st.write("### Diagnostics")
            st.write(f"- Total Recipes: {len(db)}")
            st.write(f"- Market Prices Found: {len(market)}")
            st.write(f"- Recipes skipped due to missing product price: {debug_fail_count}")
            if debug_sample:
                st.warning(f"- Sample Failure Reason: {debug_sample}")

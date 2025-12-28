import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Master Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Global Real-Time Scanner")

# --- SETTINGS ---
with st.sidebar:
    st.header("Settings")
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
    region = st.sidebar.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax = st.radio("Tax Rate", [0.845, 0.65], format_func=lambda x: "VP (15.5%)" if x == 0.845 else "No VP (35%)")
    min_stock = st.slider("Min Component Stock", 0, 1000, 1) # Set to 1 to find buyable items
    st.info("Scanner checks: recipesCooking.json, recipesAlchemy.json, recipesProcessing.json")

# --- CORE FUNCTIONS ---
@st.cache_data
def load_full_database():
    master_db = []
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for f_name in files:
        try:
            with open(f_name, 'r') as f:
                content = json.load(f)
                recipes_list = content.get('recipes', [])
                for r in recipes_list:
                    # Tag the source for category-specific yield math
                    r['source_type'] = "Processing" if "Processing" in f_name else "Other"
                master_db.extend(recipes_list)
        except: continue
    return master_db

def fetch_market_data(id_list, reg):
    full_market = {}
    ids = list(map(str, id_list))
    # Batch API calls to Arsha.io (100 IDs per request)
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        url = f"https://api.arsha.io/v1/{reg}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=10).json()
            for item in resp:
                full_market[item['id']] = (item['price'], item['stock'])
        except: continue
    return full_market

# --- MAIN EXECUTION ---
database = load_full_database()

if st.button("🚀 Run Global Profit Scan"):
    if not database:
        st.error("No recipe files found. Ensure filenames on GitHub match sidebar exactly.")
    else:
        # 1. Collect all IDs using the deeper LifeBDO structure
        all_ids = set()
        for r in database:
            all_ids.add(r['product']['id'])
            for ing in r.get('ingredients', []):
                for sub in ing.get('item', []):
                    all_ids.add(sub['id'])
        
        st.write(f"📡 Querying market for {len(all_ids)} items...")
        market_map = fetch_market_data(all_ids, region)
        results = []

        # 2. Match ingredients and check stock thresholds
        for r in database:
            p_id = r['product']['id']
            if p_id not in market_map: continue
            
            sell_price, _ = market_map[p_id]
            total_cost, in_stock = 0, True
            
            for ing in r.get('ingredients', []):
                possible_mats = ing.get('item', [])
                # Pick the cheapest material from the valid options
                valid_options = [market_map[m['id']][0] for m in possible_mats 
                                if m['id'] in market_map and market_map[m['id']][1] >= min_stock]
                
                if not valid_options:
                    in_stock = False
                    break
                total_cost += (min(valid_options) * ing['amount'])
            
            if in_stock:
                # Yield Formulas for Dec 2025 Meta
                # Processing (Heating/Chopping) avg 2.5x flat
                # Cooking/Alchemy uses Mastery-scaled proc rate
                mult = 2.5 if r['source_type'] == "Processing" else 1.0 + (mastery/4000)*0.3 + 1.35
                profit = ((sell_price * mult) * tax) - total_cost
                
                results.append({
                    "Item": r['product']['name'],
                    "Type": r['source_type'],
                    "Silver/Hr": profit * 900 # Avg 900 crafts per hour
                })

        # 3. Sort and Display Results
        if results:
            df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
            st.success(f"Global scan complete! Ranked {len(results)} items found in stock.")
            st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)
        else:
            st.warning("⚠️ 0 items found. Try lowering 'Min Component Stock' to 0 to debug.")

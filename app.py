import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Master Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Global Real-Time Scanner")

# --- SETTINGS ---
with st.sidebar:
    st.header("Parameters")
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax = st.radio("Tax Rate", [0.845, 0.65], format_func=lambda x: "VP (15.5%)" if x == 0.845 else "No VP (35%)")
    min_stock = st.slider("Min Component Stock", 0, 1000, 10)
    st.info("Scanner will check all three databases: Cooking, Alchemy, and Processing.")

# --- CORE FUNCTIONS ---
@st.cache_data
def load_full_database():
    combined = []
    # Ensure these match your GitHub file names exactly
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for file in files:
        try:
            with open(file, 'r') as f:
                data = json.load(f).get('recipes', [])
                for entry in data:
                    entry['source_file'] = file
                combined.extend(data)
        except: continue
    return combined

def get_market_batch(ids):
    id_list = list(map(str, ids))
    market_data = {}
    for i in range(0, len(id_list), 100):
        batch = id_list[i:i+100]
        url = f"https://api.arsha.io/v1/{region}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=15).json()
            for item in resp:
                market_data[item['id']] = (item['price'], item['stock'])
        except: continue
    return market_data

# --- EXECUTION LOGIC ---
db = load_full_database()

if st.button("🚀 Run Global Profit Scan"):
    if not db:
        st.error("No recipe files found. Check your GitHub file names.")
    else:
        # 1. Collect all product and ingredient IDs correctly
        all_item_ids = set()
        for r in db:
            all_item_ids.add(r['product']['id'])
            for ing in r.get('ingredients', []):
                for sub_item in ing.get('item', []):
                    all_item_ids.add(sub_item['id'])
        
        market = get_market_batch(all_item_ids)
        results = []

        # 2. Match ingredients to market data
        for r in db:
            prod_id = r['product']['id']
            if prod_id not in market: continue
            
            sell_price, _ = market[prod_id]
            total_cost, in_stock = 0, True
            
            for ing in r.get('ingredients', []):
                possible_items = ing.get('item', [])
                # Strategy: Choose the cheapest option currently in stock
                available_options = [market[i['id']][0] for i in possible_items 
                                    if i['id'] in market and market[i['id']][1] >= min_stock]
                
                if not available_options:
                    in_stock = False
                    break
                total_cost += (min(available_options) * ing['amount'])
            
            if in_stock:
                # Formula: Processing flat 2.5x; Others Mastery-based proc
                y_mult = 2.5 if "Processing" in r['source_file'] else 1.0 + (mastery/4000)*0.3 + 1.35
                profit = ((sell_price * y_mult) * tax) - total_cost
                
                results.append({
                    "Item": r['product']['name'],
                    "Category": r['source_file'].replace("recipes", "").replace(".json", ""),
                    "Silver/Hr": profit * 900
                })

        # 3. Safe Sorting Fix
        if results:
            df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
            st.success(f"Scan complete! Ranked {len(results)} items in stock.")
            st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)
        else:
            st.warning("⚠️ 0 items found. Try lowering the 'Min Component Stock' filter to 1.")

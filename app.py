import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Global Market Scanner", layout="wide")
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
    """Combines all available recipe files into one master list."""
    combined = []
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
    """Fetches real-time market data from arsha.io in batches of 100."""
    id_list = list(map(str, ids))
    market_data = {}
    # Arsha.io handles batch requests by joining IDs with commas
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
        st.error("No recipe files found. Ensure recipesCooking.json, recipesAlchemy.json, and recipesProcessing.json are in your repo.")
    else:
        # Collect all product and ingredient IDs across the entire database
        all_item_ids = set()
        for recipe in db:
            all_item_ids.add(recipe['product']['id'])
            for ing in recipe.get('ingredients', []):
                for sub_item in ing.get('item', []):
                    all_item_ids.add(sub_item['id'])
        
        st.write(f"📡 Querying market for {len(all_item_ids)} items...")
        market = get_market_batch(all_item_ids)
        results = []

        for recipe in db:
            prod_id = recipe['product']['id']
            if prod_id not in market: continue
            
            sell_price, _ = market[prod_id]
            total_cost, in_stock = 0, True
            
            # Check every ingredient for availability and cost
            for ing in recipe.get('ingredients', []):
                possible_items = ing.get('item', [])
                # Strategy: Choose the cheapest available material from the group
                available_options = [market[i['id']][0] for i in possible_items if i['id'] in market and market[i['id']][1] >= min_stock]
                
                if not available_options:
                    in_stock = False
                    break
                total_cost += (min(available_options) * ing['amount'])
            
            if in_stock:
                # Mastery Logic for 2025: Processing is flat 2.5x; Others scale
                if "Processing" in recipe['source_file']:
                    y_mult = 2.5
                else:
                    y_mult = 1.0 + (mastery/4000)*0.3 + 1.35
                
                # Formula: (Revenue * Tax) - Material Cost
                profit_per_craft = ((sell_price * y_mult) * tax) - total_cost
                # Baseline speed of 900 crafts per hour
                results.append({
                    "Item": recipe['product']['name'],
                    "Category": recipe['source_file'].replace("recipes", "").replace(".json", ""),
                    "Silver/Hr": profit_per_craft * 900
                })

        # --- FINAL DISPLAY & SORTING ---
        if results:
            df = pd.DataFrame(results)
            if "Silver/Hr" in df.columns:
                df = df.sort_values(by="Silver/Hr", ascending=False)
                st.success(f"Scan complete! Ranked {len(results)} items in stock.")
                st.dataframe(
                    df.style.format({"Silver/Hr": "{:,.0f}"}),
                    use_container_width=True
                )
        else:
            st.warning("⚠️ 0 items found in stock. Try lowering the 'Min Component Stock' filter.")

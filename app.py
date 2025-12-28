import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Global Profit Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Global Real-Time Scanner (LifeBDO Fix)")

# --- USER PARAMETERS ---
with st.sidebar:
    st.header("Settings")
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax = st.radio("Tax Rate", [0.845, 0.65], format_func=lambda x: "VP (15.5%)" if x == 0.845 else "No VP (35%)")
    min_stock = st.slider("Min Component Stock", 0, 1000, 1)
    st.info("Scanner checks: recipesCooking.json, recipesAlchemy.json, recipesProcessing.json")

# --- CORE DATA HANDLERS ---
@st.cache_data
def load_and_combine_dbs():
    combined = []
    # Ensure these match your GitHub filenames EXACTLY (case-sensitive)
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for f_name in files:
        try:
            with open(f_name, 'r') as f:
                data = json.load(f)
                # LifeBDO format wraps everything in a 'recipes' key
                recipes_list = data.get('recipes', [])
                for r in recipes_list:
                    # Determine type for mastery yield calculation
                    r['type'] = "Processing" if "Processing" in f_name else "Other"
                    combined.append(r)
        except Exception as e:
            st.error(f"Failed to load {f_name}: {e}")
    return combined

def fetch_live_market(id_list, reg):
    market_map = {}
    ids = [str(i) for i in id_list]
    # Fetch in batches of 100 to avoid API rate limits
    for i in range(0, len(ids), 100):
        batch = ",".join(ids[i:i+100])
        url = f"https://api.arsha.io/v1/{reg}/price?id={batch}"
        try:
            resp = requests.get(url, timeout=10).json()
            for item in resp:
                market_map[item['id']] = {"price": item['price'], "stock": item['stock']}
        except: continue
    return market_map

# --- EXECUTION ---
db = load_and_combine_dbs()

if st.button("🚀 Run Global Profit Scan"):
    if not db:
        st.error("Recipe database is empty. Check your JSON files on GitHub.")
    else:
        # 1. Traverse LifeBDO structure to collect every unique ID
        all_ids = set()
        for r in db:
            all_ids.add(r['product']['id'])
            for ing in r.get('ingredients', []):
                for sub_item in ing.get('item', []):
                    all_ids.add(sub_item['id'])
        
        market = fetch_live_market(all_ids, region)
        results = []

        # 2. Match market data to recipes
        for r in db:
            p_id = r['product']['id']
            if p_id not in market: continue
            
            p_name = r['product']['name']
            sell_price = market[p_id]['price']
            total_cost, in_stock = 0, True
            
            # Navigate nested ingredients -> item -> id
            for ing in r.get('ingredients', []):
                possible_choices = ing.get('item', [])
                # Find cheapest available option in the material group
                valid_options = [market[m['id']]['price'] for m in possible_choices 
                                if m['id'] in market and market[m['id']]['stock'] >= min_stock]
                
                if not valid_options:
                    in_stock = False
                    break
                total_cost += (min(valid_options) * ing['amount'])
            
            if in_stock:
                # 2025 Yield: Processing flat 2.5x; Others Mastery-based
                mult = 2.5 if r['type'] == "Processing" else 1.0 + (mastery/4000)*0.3 + 1.35
                profit = ((sell_price * mult) * tax) - total_cost
                
                results.append({
                    "Item": p_name,
                    "Type": r['type'],
                    "Silver/Hr": profit * 900 # Avg 900 crafts/hr
                })

        # 3. sorting and Display
        if results:
            df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
            st.success(f"Global Scan Complete! Found {len(results)} items in stock.")
            st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)
            
            # Debug: Show current market state for the top item
            st.divider()
            st.subheader("📡 Market Data Check (Top Item Components)")
            st.write(f"The scanner is using live data from arsha.io for {region.upper()}.")
        else:
            st.warning("⚠️ 0 items found. This means none of your recipes have all ingredients in stock at your 'Min Stock' level.")

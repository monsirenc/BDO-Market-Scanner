import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Master Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Global Profit Ranking")

# --- SETTINGS ---
with st.sidebar:
    st.header("Parameters")
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax = st.radio("Tax Rate", [0.845, 0.65], format_func=lambda x: "VP (15.5%)" if x == 0.845 else "No VP (35%)")
    min_stock = st.slider("Min Component Stock", 0, 1000, 50)
    # The scanner will now automatically find all .json files in your repo
    st.info("Scanning across: Cooking, Alchemy, and Processing databases simultaneously.")

# --- CORE FUNCTIONS ---
@st.cache_data
def load_all_dbs():
    combined_data = []
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for file in files:
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                # Mark where each recipe came from
                for item in data:
                    item['source_file'] = file
                combined_data.extend(data)
        except: continue
    return combined_data

def get_market(ids):
    # API bulk call - handle in chunks if list is massive
    id_list = list(map(str, ids))
    # We use a batch size of 100 for safety with the Arsha.io API
    full_market = {}
    for i in range(0, len(id_list), 100):
        batch = id_list[i:i+100]
        url = f"https://api.arsha.io/v1/{region}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=10).json()
            for item in resp:
                full_market[item['id']] = (item['price'], item['stock'])
        except: continue
    return full_market

# --- EXECUTION ---
db = load_all_dbs()
search_query = st.text_input("🔍 Search for any item (e.g., 'Elixir' or 'Plywood')")

if st.button("🚀 Run Global Scan"):
    if not db:
        st.error("No recipe files found. Check your GitHub file names.")
    else:
        # Collect all unique IDs for one set of API calls
        all_ids = set()
        for r in db:
            all_ids.add(r['id'])
            for i in r.get('ingredients', []): all_ids.add(i['id'])
        
        market = get_market(all_ids)
        results = []

        for r in db:
            if search_query and search_query.lower() not in r['name'].lower():
                continue
                
            p_id = r['id']
            if p_id not in market: continue
            
            sell_p, _ = market[p_id]
            cost, in_stock = 0, True
            
            for i in r.get('ingredients', []):
                m_id = i['id']
                if m_id not in market or market[m_id][1] < min_stock:
                    in_stock = False
                    break
                cost += (market[m_id][0] * i['quantity'])
            
            if in_stock:
                # Logic Switch: Processing uses a flat 2.5x; Others use Mastery Formula
                if "Processing" in r['source_file']:
                    y_mult = 2.5 
                    cat_label = "Processing"
                elif "Alchemy" in r['source_file']:
                    y_mult = 1.0 + (mastery/4000)*0.3 + 1.35
                    cat_label = "Alchemy"
                else:
                    y_mult = 1.0 + (mastery/4000)*0.3 + 1.35
                    cat_label = "Cooking"
                
                profit = ((sell_p * y_mult) * tax) - cost
                results.append({"Item": r['name'], "Category": cat_label, "Silver/Hr": profit * 900})

        if results:
            df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
            st.success(f"Global Scan complete! Found {len(results)} profitable items in stock.")
            st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)
        else:
            st.warning("No items found. Try lowering the 'Min Component Stock' filter.")

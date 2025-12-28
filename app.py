import streamlit as st
import requests
import pandas as pd
import json

st.set_page_config(page_title="BDO Master Scanner", layout="wide")
st.title("🛡️ BDO Buy-to-Sell: Full Database Scanner")

# --- SETTINGS ---
with st.sidebar:
    st.header("Parameters")
    mastery = st.number_input("Lifeskill Mastery", value=2000)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax = st.radio("Tax Rate", [0.845, 0.65], format_func=lambda x: "VP (15.5%)" if x == 0.845 else "No VP (35%)")
    min_stock = st.slider("Min Component Stock", 1, 1000, 50)
    # This dropdown lets you choose between the files you uploaded
    db_choice = st.selectbox("Select Database", ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"])

# --- DATA LOADING ---
@st.cache_data
def load_db(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except: return []

def get_market(ids):
    # API handles joined IDs for efficiency
    url = f"https://api.arsha.io/v1/{region}/price?id={','.join(map(str, ids))}"
    try:
        resp = requests.get(url).json()
        return {item['id']: (item['price'], item['stock']) for item in resp}
    except: return {}

# --- SCANNER EXECUTION ---
db = load_db(db_choice)

if st.button(f"🚀 Run Scan on {db_choice}"):
    if not db:
        st.error(f"File {db_choice} not found. Please ensure the file name matches exactly in GitHub.")
    else:
        # Collect all item IDs for one single API call to prevent rate limiting
        all_ids = set()
        for r in db:
            all_ids.add(r['id'])
            for i in r.get('ingredients', []): 
                all_ids.add(i['id'])
        
        market = get_market(list(all_ids))
        results = []

        for r in db:
            p_id = r['id']
            if p_id not in market: continue
            
            sell_p, _ = market[p_id]
            cost, in_stock = 0, True
            
            # Check every ingredient for availability and price
            for i in r.get('ingredients', []):
                m_id = i['id']
                if m_id not in market or market[m_id][1] < min_stock:
                    in_stock = False
                    break
                cost += (market[m_id][0] * i['quantity'])
            
            if in_stock:
                # Logic: Processing uses a flat 2.5x yield; Cooking/Alchemy use Mastery formula
                if "Processing" in db_choice:
                    y_mult = 2.5 
                else:
                    y_mult = 1.0 + (mastery/4000)*0.3 + 1.35
                
                profit_per_craft = ((sell_p * y_mult) * tax) - cost
                # Assuming a standard speed of 900 crafts per hour
                results.append({"Item": r['name'], "Silver/Hr": profit_per_craft * 900})

        if results:
            # Sort with most profitable at the top
            df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
            st.success(f"Scan complete! Found {len(results)} items in stock.")
            st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)
        else:
            st.warning("No items found with current stock levels. Try lowering 'Min Component Stock' in the sidebar.")

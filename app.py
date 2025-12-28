import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="BDO Profit Scanner", layout="wide")
st.title("⚖️ BDO Buy-to-Sell: Live Profit Ranking (2025)")

# Configuration Sidebar
st.sidebar.header("Settings")
mastery = st.sidebar.number_input("Lifeskill Mastery", value=2000, step=50)
region = st.sidebar.selectbox("Region", ["na", "eu", "sea", "kr"])
tax_rate = st.sidebar.radio("Value Pack?", [0.845, 0.65], format_func=lambda x: "Yes (15.5%)" if x == 0.845 else "No (35%)")

# EXTENDED RECIPE DATABASE
# Format: [ProductID, Category, {ComponentID: Quantity}]
RECIPES = {
    "Harmony Draught": [9691, "Alchemy", {9688: 1, 9689: 1, 9690: 1, 9635: 1}],
    "Berserk Draught": [9636, "Alchemy", {9452: 1, 9460: 1, 9454: 1, 9635: 1}],
    "Giant's Draught": [9638, "Alchemy", {9407: 1, 9403: 1, 9409: 1, 9635: 1}],
    "Frenzy Elixir": [9452, "Alchemy", {525: 1, 5421: 4, 9461: 3, 9414: 5}],
    "Spirit Elixir": [9460, "Alchemy", {528: 1, 5424: 4, 4601: 3, 9414: 5}],
    "Pure Iron Crystal": [4057, "Processing", {4052: 3, 4433: 1}],
    "Pure Copper Crystal": [4058, "Processing", {4053: 3, 4434: 1}],
    "Pure Tin Crystal": [4060, "Processing", {4055: 3, 4436: 1}],
    "Pure Zinc Crystal": [4062, "Processing", {4056: 3, 4437: 1}],
    "O'dyllita Meal": [9276, "Cooking", {9273: 1, 9274: 1, 9275: 1, 9403: 2}],
    "Kamasylvia Meal": [9213, "Cooking", {9209: 1, 9210: 1, 9211: 1, 9212: 1, 9414: 2}],
    "Balenos Meal": [9203, "Cooking", {9201: 1, 9202: 1, 9402: 2, 9401: 2, 9403: 1}],
    "Ship Repair Material": [5957, "Processing", {4052: 2, 4601: 2}]
}

def get_market_data(ids):
    id_list = ",".join(map(str, ids))
    url = f"https://api.arsha.io/v1/{region}/price?id={id_list}"
    try:
        data = requests.get(url).json()
        return {item['id']: (item['price'], item['stock']) for item in data}
    except: return {}

if st.button("🔍 Scan for In-Stock Profits"):
    all_ids = set()
    for d in RECIPES.values():
        all_ids.add(d[0])
        all_ids.update(d[2].keys())
    
    market = get_market_data(all_ids)
    results = []

    for name, data in RECIPES.items():
        p_id, cat, mats = data
        if p_id not in market: continue
        
        sell_p, _ = market[p_id]
        cost, in_stock = 0, True
        
        for m_id, qty in mats.items():
            if m_id not in market or market[m_id][1] < 200:
                in_stock = False
                break
            cost += (market[m_id][0] * qty)
        
        if in_stock:
            y_mult = 2.5 if cat == "Processing" else 1.0 + (mastery/4000)*0.3 + 1.35
            profit = ((sell_p * y_mult) * tax_rate) - cost
            results.append({"Item": name, "Category": cat, "Silver/Hr": profit * 900})

    df = pd.DataFrame(results).sort_values(by="Silver/Hr", ascending=False)
    st.dataframe(df.style.format({"Silver/Hr": "{:,.0f}"}), use_container_width=True)

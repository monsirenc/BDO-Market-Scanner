import streamlit as st
import json
import requests

st.title("🛑 BDO Sanity Check")

# 1. READ THE FILE
st.write("### Step 1: Reading File")
try:
    with open("recipesProcessing.json", "r") as f:
        data = json.load(f)
        # Grab the first recipe (Acacia Plank)
        sample = data['recipes'][0]
        sample_id = sample['product']['id']
        sample_name = sample['product']['name']
        
        st.success(f"✅ File Read Successfully!")
        st.write(f"**Target Item:** {sample_name}")
        st.write(f"**Raw ID from File:** `{sample_id}` (Type: {type(sample_id)})")
        
except Exception as e:
    st.error(f"❌ File Read Failed: {e}")
    st.stop()

# 2. CHECK THE API
st.write("### Step 2: Checking Market API")
url = f"https://api.arsha.io/v1/na/price?id={sample_id}"
st.write(f"**Requesting URL:** `{url}`")

try:
    response = requests.get(url, timeout=10)
    st.write(f"**API Status Code:** {response.status_code}")
    
    if response.status_code == 200:
        market_data = response.json()
        st.write("**Raw API Response:**")
        st.json(market_data)
        
        if market_data:
            price = market_data[0]['price']
            stock = market_data[0]['stock']
            st.success(f"✅ SUCCESS: API sees {sample_name} at {price:,} silver with {stock} stock.")
        else:
            st.error("❌ API returned an empty list. The item ID exists, but the market has no data for it.")
    else:
        st.error("❌ API Request failed.")
        
except Exception as e:
    st.error(f"❌ Connection Error: {e}")

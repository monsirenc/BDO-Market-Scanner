import streamlit as st
import requests
import pandas as pd
import json
import time

st.set_page_config(page_title="BDO LifeBDO Global Scanner", layout="wide")
st.title("🛡️ BDO Global Profit Scanner (LifeBDO Edition)")

# --- 1. SETTINGS SIDEBAR ---
with st.sidebar:
    st.header("Parameters")
    mastery = st.number_input("Lifeskill Mastery", value=2000, step=50)
    region = st.selectbox("Region", ["na", "eu", "sea", "kr"])
    tax_rate = st.radio("Tax (Value Pack)", [0.845, 0.65], format_func=lambda x: "Yes (15.5%)" if x == 0.845 else "No (35%)")
    min_stock = st.slider("Min Ingredient Stock", 0, 5000, 0) # Default 0 to see everything
    st.info("Scanner checks: recipesCooking.json, recipesAlchemy.json, recipesProcessing.json")

# --- 2. DATA LOADING (LifeBDO Structure) ---
@st.cache_data
def load_data():
    all_recipes = []
    # Exact filenames from your GitHub upload
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    
    for f_name in files:
        try:
            with open(f_name, 'r') as f:
                data = json.load(f)
                # LifeBDO format: Root object -> "recipes" key -> List of objects
                if 'recipes' in data:
                    for r in data['recipes']:
                        r['source_file'] = f_name
                        all_recipes.append(r)
        except FileNotFoundError:
            st.error(f"❌ File not found: {f_name}")
        except Exception as e:
            st.error(f"❌ Error loading {f_name}: {e}")
            
    return all_recipes

# --- 3. MARKET API (Batching) ---
def get_prices(id_list, region_code):
    market_map = {}
    # Convert all IDs to strings for API url
    ids = list(set([str(i) for i in id_list]))
    
    # Process in batches of 100 to respect Arsha.io limits
    batch_size = 100
    progress_bar = st.progress(0)
    
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        url = f"https://api.arsha.io/v1/{region_code}/price?id={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    # Map: ID (int) -> Price/Stock
                    market_map[int(item['id'])] = {
                        'price': item['price'],
                        'stock': item['stock']
                    }
            time.sleep(0.1) # Slight delay to be safe
        except Exception as e:
            print(f"API Error: {e}")
        
        progress_bar.progress(min((i + batch_size) / len(ids), 1.0))
        
    progress_bar.empty()
    return market_map

# --- 4. MAIN LOGIC ---
db = load_data()

if st.button("🚀 Run Scan"):
    if not db:
        st.error("No recipes loaded. Please check your JSON files.")
    else:
        # A. Extract ALL IDs (Product + Ingredients)
        all_ids = set()
        for r in db:
            # LifeBDO: Product ID is at r['product']['id']
            all_ids.add(r['product']['id'])
            
            # LifeBDO: Ingredients -> Array -> 'item' -> Array -> 'id'
            for ing_group in r.get('ingredients', []):
                for item_opt in ing_group.get('item', []):
                    all_ids.add(item_opt['id'])
        
        st.write(f"📡 Fetching live data for {len(all_ids)} unique items...")
        market_data = get_prices(all_ids, region)
        
        # B. Calculate Profits
        results = []
        
        for r in db:
            # 1. Check Product Market Data
            pid = r['product']['id']
            if pid not in market_data: continue
            
            sell_price = market_data[pid]['price']
            product_name = r['product']['name']
            
            # 2. Calculate Cost (Cheapest Ingredient Method)
            total_cost = 0
            is_craftable = True
            missing_items = []
            
            for ing_group in r.get('ingredients', []):
                # This group might allow "Wheat" OR "Barley". Find cheapest one in stock.
                options = ing_group.get('item', [])
                valid_options = []
                
                for opt in options:
                    oid = opt['id']
                    if oid in market_data:
                        price = market_data[oid]['price']
                        stock = market_data[oid]['stock']
                        if stock >= min_stock:
                            valid_options.append(price)
                
                if valid_options:
                    # Use the cheapest valid option
                    cheapest_price = min(valid_options)
                    total_cost += (cheapest_price * ing_group['amount'])
                else:
                    is_craftable = False
                    # For debugging, grab the first name if available
                    missing_items.append(options[0].get('name', 'Unknown'))
                    break
            
            if is_craftable:
                # 3. Apply Yield Multipliers
                # Processing (Chopping/Heating) -> Fixed ~2.5x yield
                # Cooking/Alchemy -> Mastery dependent
                if "Processing" in r['source_file']:
                    yield_mult = 2.5
                    craft_type = "Processing"
                else:
                    # Standard 2025 Mastery Formula approximation
                    yield_mult = 1.0 + (mastery / 4000) * 0.3 + 1.35 
                    craft_type = "Cooking/Alchemy"

                gross_revenue = sell_price * yield_mult
                net_revenue = gross_revenue * tax_rate
                profit = net_revenue - total_cost
                
                # Filter: Only show profitable items
                if profit > 0:
                    results.append({
                        "Item": product_name,
                        "Type": craft_type,
                        "Silver/Hr": profit * 900, # Assuming 900 crafts/hr (1 sec cooking)
                        "Unit Profit": profit,
                        "Cost": total_cost,
                        "Sell Price": sell_price
                    })

        # C. Display Results
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by="Silver/Hr", ascending=False)
            
            st.success(f"Scan Complete! Found {len(results)} profitable items.")
            
            # Formatting for cleaner look
            st.dataframe(
                df.style.format({
                    "Silver/Hr": "{:,.0f}", 
                    "Unit Profit": "{:,.0f}", 
                    "Cost": "{:,.0f}",
                    "Sell Price": "{:,.0f}"
                }), 
                use_container_width=True
            )
        else:
            st.warning("No profitable items found with current filters.")
            # Debugging Help
            with st.expander("Debug: Why 0 items?"):
                st.write(f"Total Recipes Scanned: {len(db)}")
                st.write(f"Total Market Prices Fetched: {len(market_data)}")
                st.write("Sample Market Data (First 5 IDs):")
                st.json(dict(list(market_data.items())[:5]))

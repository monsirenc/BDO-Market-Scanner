import streamlit as st
import pandas as pd
import json
import requests
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

st.set_page_config(page_title="BDOLytics Recursive Scanner", layout="wide")
st.title("🍳 BDOLytics Smart Scanner (Recursive Fix)")

# --- SETTINGS ---
with st.sidebar:
    region = st.selectbox("Region", ["NA", "EU", "SEA", "KR"], index=0)
    category = st.selectbox("Category", ["cooking", "alchemy", "processing"], index=0)
    st.divider()
    min_stock = st.number_input("Min. Ingredient Stock", value=100, step=100)
    
# --- 1. LOAD RECIPES (Recursive-Ready) ---
@st.cache_data
def load_recipe_databases():
    # We need two maps:
    # 1. Name -> ID (To link BDOLytics names to IDs)
    # 2. ID -> Ingredients (To look up sub-recipes like Iron Ingot -> Melted Shard -> Iron Ore)
    name_to_id = {}
    id_to_recipe = {}
    
    files = [
        "recipesCooking.json", 
        "recipesAlchemy.json", 
        "recipesProcessing.json"
    ]
    
    VENDOR_IDS = {5600, 9059, 9001, 9002, 9005, 9015, 9016, 9017, 9018, 9066, 6656, 6655, 9003, 9006}

    for fname in files:
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for r in data.get('recipes', []):
                    # Product Info
                    prod = r['product']
                    pid = int(prod['id'])
                    pname = prod['name']
                    
                    # Store Name Map
                    name_to_id[pname] = pid
                    
                    # Store Recipe Map (Keyed by Product ID)
                    if 'ingredients' in r:
                        ingredients = []
                        for group in r['ingredients']:
                            # Get list of valid IDs for this slot
                            valid_options = []
                            for item in group['item']:
                                i_id = int(item['id'])
                                # Vendor items are valid but we flag them as "Vendor" so we don't market check them
                                valid_options.append(i_id)
                            
                            if valid_options:
                                ingredients.append(valid_options)
                        
                        id_to_recipe[pid] = ingredients
        except: pass
        
    return name_to_id, id_to_recipe, VENDOR_IDS

# --- 2. SCRAPE BDOLYTICS ---
@st.cache_resource
def get_bdolytics_top_items(reg, cat):
    url = f"https://bdolytics.com/en/{reg}/{cat}/market"
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    
    data = []
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        driver.quit()
        
        rows = soup.find_all('tr')
        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) < 4: continue
            
            name_div = cols[0].find('div', class_='text-truncate')
            name = name_div.text.strip() if name_div else cols[0].text.strip()
            
            try:
                profit = int(cols[2].text.strip().replace(',', ''))
            except: profit = 0
            
            data.append({"Name": name, "Profit": profit})
            if len(data) >= 50: break
    except: return []
    return data

# --- 3. RECURSIVE STOCK CHECKER ---
def check_stock_recursive(target_id, market_data, recipe_db, vendor_ids, depth=0):
    """
    Returns True if the item is available.
    Logic:
    1. Is it a vendor item? -> True
    2. Is it on the market? -> True
    3. (Recursion) If missing, does it have a recipe? 
       -> If yes, check if THOSE ingredients are available.
    """
    # Safety brake for recursion
    if depth > 2: return False
    
    # 1. Vendor Check
    if target_id in vendor_ids:
        return True
        
    # 2. Market Check
    stock = market_data.get(target_id, 0)
    if stock >= st.session_state.get('min_stock_val', 100):
        return True
        
    # 3. Recursive Recipe Check (The Iron Ingot Fix)
    # If not on market, check if we can craft it from available base mats
    if target_id in recipe_db:
        ingredients = recipe_db[target_id]
        
        # Check if ALL ingredient slots can be filled
        for slot_options in ingredients:
            # We need at least ONE valid option for this slot
            slot_filled = False
            for opt_id in slot_options:
                if check_stock_recursive(opt_id, market_data, recipe_db, vendor_ids, depth + 1):
                    slot_filled = True
                    break
            
            if not slot_filled:
                return False # One slot is impossible to fill
        
        return True # All slots filled recursively
        
    return False

# --- 4. DATA FETCH & PROCESS ---
def process_market_data(items_list, name_map, recipe_db, vendor_ids, reg):
    # 1. Identify ALL IDs needed (Level 1 and Level 2)
    ids_to_fetch = set()
    
    # Function to collect IDs recursively (Depth 2)
    def collect_ids(pid, d):
        if d > 2: return
        if pid in recipe_db:
            for group in recipe_db[pid]:
                for iid in group:
                    if iid not in vendor_ids:
                        ids_to_fetch.add(iid)
                        collect_ids(iid, d + 1)

    for item in items_list:
        name = item['Name']
        if name in name_map:
            pid = name_map[name]
            collect_ids(pid, 0) # Start collection
            
    # 2. Batch Fetch from Arsha
    market_stock = {}
    id_list = list(ids_to_fetch)
    batch_size = 50
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    bar = st.progress(0)
    
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        url = f"https://api.arsha.io/v2/{reg.lower()}/price?id={','.join(map(str, batch))}"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                for x in r.json():
                    market_stock[int(x.get('id', 0))] = int(x.get('currentStock', 0))
        except: pass
        bar.progress(min((i+batch_size)/len(id_list), 1.0))
        time.sleep(0.1)
    bar.empty()
    
    # 3. Validate Items using Recursion
    final_results = []
    
    # Save min_stock to session for the recursive function to access easily
    st.session_state['min_stock_val'] = min_stock
    
    for item in items_list:
        name = item['Name']
        profit = item['Profit']
        status = "✅ Available"
        note = "Direct Purchase"
        
        if name not in name_map:
            continue
            
        pid = name_map[name]
        
        # Check ingredients for the main item
        if pid in recipe_db:
            ingredients = recipe_db[pid]
            for group in ingredients:
                slot_ok = False
                for opt_id in group:
                    # Perform the Recursive Check here
                    if check_stock_recursive(opt_id, market_stock, recipe_db, vendor_ids):
                        slot_ok = True
                        break
                
                if not slot_ok:
                    status = "❌ Out of Stock"
                    # Try to find name of missing item
                    # (This is hard without a huge ID->Name map, but logic holds)
                    break
        
        if status == "✅ Available":
            final_results.append({
                "Item": name,
                "Silver/Hour (BDOLytics)": profit,
                "Stock": status
            })
            
    return final_results

# --- MAIN APP ---
name_map, recipe_db, vendor_ids = load_recipe_databases()

if st.button("🚀 Scrape & Smart-Check"):
    if not name_map:
        st.error("JSON files missing.")
    else:
        with st.spinner("Step 1: Getting Top Items..."):
            top_items = get_bdolytics_top_items(region, category)
        
        if top_items:
            with st.spinner("Step 2: recursively checking stock (Iron Ore -> Melted Shard -> Ingot)..."):
                valid_items = process_market_data(top_items, name_map, recipe_db, vendor_ids, region)
            
            if valid_items:
                df = pd.DataFrame(valid_items)
                st.success(f"Found {len(valid_items)} items available via Purchase OR Crafting!")
                st.dataframe(
                    df, 
                    use_container_width=True,
                    column_config={
                        "Silver/Hour (BDOLytics)": st.column_config.NumberColumn(format="%d 💰")
                    }
                )
            else:
                st.warning("No items found. Everything is truly sold out.")

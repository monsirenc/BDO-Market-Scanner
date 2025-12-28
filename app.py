import streamlit as st
import pandas as pd
import json
import requests
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import shutil

st.set_page_config(page_title="BDOLytics Fast Scanner", layout="wide")
st.title("🍳 BDOLytics Smart Scanner (Fast Mode)")

# --- SETTINGS ---
with st.sidebar:
    region = st.selectbox("Region", ["NA", "EU", "SEA", "KR"], index=0)
    category = st.selectbox("Category", ["cooking", "alchemy", "processing"], index=0)
    st.divider()
    min_stock = st.number_input("Min. Ingredient Stock", value=100, step=100)
    
# --- 1. LOAD RECIPES ---
@st.cache_data
def load_recipe_databases():
    name_map = {}
    recipe_db = {}
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    VENDOR_IDS = {5600, 9059, 9001, 9002, 9005, 9015, 9016, 9017, 9018, 9066, 6656, 6655, 9003, 9006}

    for fname in files:
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for r in data.get('recipes', []):
                    prod = r['product']
                    pid = int(prod['id'])
                    pname = prod['name']
                    name_map[pname] = pid
                    
                    if 'ingredients' in r:
                        ingredients = []
                        for group in r['ingredients']:
                            valid_options = [int(item['id']) for item in group['item']]
                            if valid_options:
                                ingredients.append(valid_options)
                        recipe_db[pid] = ingredients
        except: pass
        
    return name_map, recipe_db, VENDOR_IDS

# --- 2. SCRAPE BDOLYTICS (OPTIMIZED) ---
@st.cache_resource
def get_bdolytics_top_items(reg, cat):
    url = f"https://bdolytics.com/en/{reg}/{cat}/market"
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # CRITICAL: Do not wait for ads/images to load
    options.page_load_strategy = 'eager'
    
    # Path Detection (Works on both Linux Cloud and Windows Local)
    chrome_bin = shutil.which("chromium") or shutil.which("chrome") or "/usr/bin/chromium"
    driver_bin = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    
    if chrome_bin: options.binary_location = chrome_bin

    data = []
    driver = None
    
    try:
        service = Service(driver_bin) if driver_bin else Service()
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get(url)
        
        # Increased timeout to 25s, but 'eager' mode should make this instant
        try:
            WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "tbody")))
        except:
            st.error("Still timed out. BDOLytics might be blocking the IP or loading very slowly.")
            return []
            
        # Small buffer for table population
        time.sleep(2) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
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
            
    except Exception as e:
        st.error(f"Browser Error: {e}")
        return []
    finally:
        if driver: driver.quit()
        
    return data

# --- 3. RECURSIVE STOCK CHECKER ---
def check_stock_recursive(target_id, market_data, recipe_db, vendor_ids, depth=0):
    if depth > 5: return False
    
    # 1. Vendor
    if target_id in vendor_ids: return True
    
    # 2. Market
    stock = market_data.get(target_id, 0)
    if stock >= st.session_state.get('min_stock_val', 100):
        return True
        
    # 3. Craftable?
    if target_id in recipe_db:
        ingredients = recipe_db[target_id]
        for slot_options in ingredients:
            slot_filled = False
            for opt_id in slot_options:
                if check_stock_recursive(opt_id, market_data, recipe_db, vendor_ids, depth + 1):
                    slot_filled = True
                    break
            if not slot_filled:
                return False
        return True
        
    return False

# --- 4. PROCESSING ---
def process_market_data(items_list, name_map, recipe_db, vendor_ids, reg):
    # Collect IDs
    ids_to_fetch = set()
    def collect_ids(pid, d):
        if d > 5: return
        if pid in recipe_db:
            for group in recipe_db[pid]:
                for iid in group:
                    if iid not in vendor_ids:
                        ids_to_fetch.add(iid)
                        collect_ids(iid, d + 1)

    for item in items_list:
        if item['Name'] in name_map:
            collect_ids(name_map[item['Name']], 0)
            
    # Fetch Market Data
    market_stock = {}
    id_list = list(ids_to_fetch)
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Progress UI
    bar = st.progress(0)
    status_text = st.empty()
    
    # Batch Fetch
    for i in range(0, len(id_list), 50):
        batch = id_list[i:i+50]
        url = f"https://api.arsha.io/v2/{reg.lower()}/price?id={','.join(map(str, batch))}"
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                for x in r.json():
                    market_stock[int(x.get('id', 0))] = int(x.get('currentStock', 0))
        except: pass
        
        bar.progress(min((i+50)/len(id_list), 1.0))
        time.sleep(0.1)
    
    bar.empty()
    status_text.empty()
    
    # Validate
    final_results = []
    st.session_state['min_stock_val'] = min_stock
    
    for item in items_list:
        name = item['Name']
        if name not in name_map: continue
        pid = name_map[name]
        
        can_craft = False
        if pid in recipe_db:
            # Check main recipe
            for group in recipe_db[pid]: 
                variation_ok = True
                for slot_opts in group:
                    slot_filled = False
                    for opt in slot_opts:
                        if check_stock_recursive(opt, market_stock, recipe_db, vendor_ids):
                            slot_filled = True
                            break
                    if not slot_filled:
                        variation_ok = False
                        break
                if variation_ok:
                    can_craft = True
                    break
        
        if can_craft:
            final_results.append({
                "Item": name,
                "Profit/Hour": item['Profit'],
                "Status": "✅ Craftable"
            })
            
    return final_results

# --- MAIN APP ---
name_map, recipe_db, vendor_ids = load_recipe_databases()

if st.button("🚀 Scrape & Smart-Check"):
    if not name_map:
        st.error("JSON files missing.")
    else:
        with st.spinner("Step 1: Scraping BDOLytics (Fast Mode)..."):
            top_items = get_bdolytics_top_items(region, category)
        
        if top_items:
            st.success(f"Scraped {len(top_items)} items. Checking recursive stock availability...")
            valid_items = process_market_data(top_items, name_map, recipe_db, vendor_ids, region)
            
            if valid_items:
                df = pd.DataFrame(valid_items)
                st.success(f"Found {len(valid_items)} profitable items available now!")
                st.dataframe(
                    df, 
                    use_container_width=True,
                    column_config={
                        "Profit/Hour": st.column_config.NumberColumn(format="%d 💰")
                    }
                )
            else:
                st.warning("No items found where all ingredients are available.")

import streamlit as st
import pandas as pd
import json
import time
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

st.set_page_config(page_title="BDOLytics Verbose Scanner", layout="wide")
st.title("🍳 BDOLytics Scraper (Debug Mode)")

# --- SIDEBAR ---
with st.sidebar:
    region = st.selectbox("Region", ["NA", "EU", "SEA", "KR"], index=0)
    category = st.selectbox("Category", ["cooking", "alchemy", "processing"], index=0)
    pages = st.slider("Pages to Scrape", 1, 10, 5)
    st.divider()
    min_stock = st.number_input("Min Stock", 100, step=100)

# --- 1. LOAD RECIPES ---
@st.cache_data
def load_recipe_db():
    name_map = {}
    recipe_db = {}
    vendor_ids = {5600, 9059, 9001, 9002, 9005, 9015, 9016, 9017, 9018, 9066, 6656, 6655, 9003, 9006}
    
    files = ["recipesCooking.json", "recipesAlchemy.json", "recipesProcessing.json"]
    for fname in files:
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for r in data.get('recipes', []):
                    pid = int(r['product']['id'])
                    name = r['product']['name']
                    name_map[name] = pid
                    
                    if 'ingredients' in r:
                        ingredients = []
                        for group in r['ingredients']:
                            valid_opts = [int(i['id']) for i in group['item']]
                            ingredients.append(valid_opts)
                        recipe_db[pid] = ingredients
        except: pass
    return name_map, recipe_db, vendor_ids

# --- 2. SCRAPE FUNCTION (VERBOSE) ---
def scrape_bdolytics_verbose(reg, cat, max_pages):
    url = f"https://bdolytics.com/en/{reg}/{cat}/market"
    
    # UI Elements for Feedback
    status = st.empty()
    prog_bar = st.progress(0)
    log_area = st.expander("Show Scraping Logs", expanded=True)
    
    data = []
    
    try:
        # 1. Launch Browser
        status.write("🔵 Launching Headless Chrome...")
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        # Anti-detection user agent
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        # 2. Load Page
        status.write(f"🔵 Loading {url}...")
        driver.get(url)
        
        # Wait for Table
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "tbody")))
            log_area.write("✅ Table loaded successfully.")
        except:
            log_area.error("❌ Timeout: Table not found. BDOLytics might be loading slowly.")
            driver.quit()
            return []

        # 3. Loop Pages
        for page in range(1, max_pages + 1):
            status.write(f"🔵 Scraping Page {page}/{max_pages}...")
            
            # Parse HTML
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('tr')[1:] # Skip header
            
            page_count = 0
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 4: continue
                
                # Name
                name_div = cols[0].find('div', class_='text-truncate')
                name = name_div.text.strip() if name_div else cols[0].text.strip()
                
                # Profit
                try:
                    profit = int(cols[2].text.strip().replace(',', ''))
                except: profit = 0
                
                data.append({"Name": name, "Profit": profit})
                page_count += 1
            
            log_area.write(f"  -> Page {page}: Found {page_count} items")
            prog_bar.progress(page / max_pages)
            
            # Pagination
            if page < max_pages:
                try:
                    # Look for the 'Next' button specifically by its icon class
                    next_btns = driver.find_elements(By.CSS_SELECTOR, "i.mdi-chevron-right")
                    if next_btns:
                        # The icon is inside the button, click the parent
                        parent_btn = next_btns[0].find_element(By.XPATH, "./..")
                        if "disabled" in parent_btn.get_attribute("class"):
                            log_area.warning("  -> Next button disabled. End of list.")
                            break
                        driver.execute_script("arguments[0].click();", parent_btn)
                        time.sleep(3) # Wait for load
                    else:
                        log_area.warning("  -> Next button not found.")
                        break
                except Exception as e:
                    log_area.error(f"  -> Pagination Error: {e}")
                    break
        
        driver.quit()
        status.write("✅ Scraping Complete!")
        return data

    except Exception as e:
        status.error(f"❌ CRITICAL ERROR: {e}")
        if 'driver' in locals(): driver.quit()
        return []

# --- 3. RECURSIVE STOCK CHECK ---
def check_stock_recursive(target_id, market_data, recipe_db, vendor_ids, depth=0):
    if depth > 5: return False # Prevent infinite loops
    
    # Case A: Vendor Item (Always Stocked)
    if target_id in vendor_ids: return True
    
    # Case B: Market Item (Check Stock)
    stock = market_data.get(target_id, 0)
    if stock >= st.session_state.min_stock_val: return True
    
    # Case C: Not in stock -> Can we craft it? (The "Iron Ingot" Fix)
    if target_id in recipe_db:
        ingredients = recipe_db[target_id]
        # Check if ANY recipe variation works
        for group in ingredients:
            # For a single recipe, ALL slots must be filled
            recipe_possible = True
            for options in group: # This is a list of potential items for one slot
                # We need ONE valid item from this list of options
                slot_filled = False
                # Handle single int or list of ints
                if isinstance(options, int): options = [options]
                
                for opt_id in options:
                    if check_stock_recursive(opt_id, market_data, recipe_db, vendor_ids, depth + 1):
                        slot_filled = True
                        break
                
                if not slot_filled:
                    recipe_possible = False
                    break
            
            if recipe_possible:
                return True # We found a valid recipe path!
                
    return False

# --- 4. MAIN APP ---
if 'min_stock_val' not in st.session_state:
    st.session_state.min_stock_val = min_stock

# Load DB
name_map, recipe_db, vendor_ids = load_recipe_db()

if st.button("🚀 Start Process", type="primary"):
    # A. Scrape
    items = scrape_bdolytics_verbose(region, category, pages)
    
    if not items:
        st.error("No items scraped. Check the logs above.")
    else:
        # B. Get IDs for Stock Check
        ids_to_check = set()
        
        # Helper to grab IDs recursively
        def collect_ids(pid, d=0):
            if d > 3: return
            if pid in recipe_db:
                for grp in recipe_db[pid]:
                    for opts in grp:
                        if isinstance(opts, int): opts = [opts]
                        for i in opts:
                            if i not in vendor_ids:
                                ids_to_check.add(i)
                                collect_ids(i, d+1)

        for item in items:
            if item['Name'] in name_map:
                collect_ids(name_map[item['Name']])
        
        st.info(f"Checking market stock for {len(ids_to_check)} unique ingredients...")
        
        # C. Market API (Arsha V2 Batch)
        market_stock = {}
        id_list = list(ids_to_check)
        
        # Progress bar for API
        bar = st.progress(0)
        
        # Arsha allows 50 items per call if using V2 safely
        for i in range(0, len(id_list), 50):
            batch = id_list[i:i+50]
            url = f"https://api.arsha.io/v2/{region.lower()}/price?id={','.join(map(str, batch))}"
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    for x in r.json():
                        market_stock[int(x['id'])] = int(x['currentStock'])
            except: pass
            bar.progress(min((i+50)/len(id_list), 1.0))
            time.sleep(0.1)
        bar.empty()
        
        # D. Validate
        valid_results = []
        st.session_state.min_stock_val = min_stock
        
        for item in items:
            name = item['Name']
            if name not in name_map: continue
            
            pid = name_map[name]
            
            # Check main recipe
            is_valid = False
            if pid in recipe_db:
                # Same logic: Can we craft the main item?
                # We reuse the recursive checker but treat the main item as a "Recipe" to check
                # Actually, check_stock_recursive checks if an item is OBTAINABLE.
                # But for the final product, we want to know if we can CRAFT it, not buy it.
                
                # Manual top-level check
                can_craft = False
                for group in recipe_db[pid]: # Each group is a variation of the recipe
                    # For a variation to be valid, ALL slots must be valid
                    variation_ok = True
                    for slot_opts in group:
                        if isinstance(slot_opts, int): slot_opts = [slot_opts]
                        
                        # Can we get ANY item for this slot?
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
                    valid_results.append(item)

        # E. Display
        if valid_results:
            df = pd.DataFrame(valid_results)
            st.success(f"Found {len(valid_results)} items you can craft RIGHT NOW!")
            st.dataframe(
                df,
                use_container_width=True,
                column_config={"Profit": st.column_config.NumberColumn(format="%d 💰")},
                height=800
            )
        else:
            st.warning("No profitable items found where ALL ingredients are available.")

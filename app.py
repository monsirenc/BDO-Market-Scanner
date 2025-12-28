import streamlit as st
import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

st.set_page_config(page_title="BDOLytics Automator", layout="wide")
st.title("🤖 BDOLytics 'Stock Check' Automator")

# --- SIDEBAR ---
with st.sidebar:
    region = st.selectbox("Region", ["NA", "EU", "SEA", "KR", "SA", "RU"], index=0)
    category = st.selectbox("Category", ["cooking", "alchemy", "processing"], index=0)
    limit = st.slider("Items to Scan", 10, 50, 20, help="Visiting pages takes time. Keep this low (10-20) for speed.")
    st.info("This script physically visits the BDOLytics recipe page for each item and looks for the 'Red Circle' warning icon.")

# --- SELENIUM SETUP ---
@st.cache_resource
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    return webdriver.Chrome(options=options)

# --- 1. SCRAPE LIST ---
def scrape_market_list(driver, reg, cat, limit):
    url = f"https://bdolytics.com/en/{reg}/{cat}/market"
    driver.get(url)
    
    # Wait for table
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "tbody")))
    except:
        return []

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    rows = soup.find_all('tr')[1:] # Skip header
    
    data = []
    for row in rows[:limit]:
        cols = row.find_all('td')
        if len(cols) < 4: continue
        
        # Name & Link
        a_tag = cols[0].find('a')
        if not a_tag: continue
        
        name = a_tag.text.strip()
        link = "https://bdolytics.com" + a_tag['href']
        
        # Profit
        try:
            profit = int(cols[2].text.strip().replace(',', ''))
        except: profit = 0
        
        data.append({"Name": name, "Profit": profit, "Link": link})
        
    return data

# --- 2. CHECK RECIPE PAGE ---
def check_recipe_stock(driver, url):
    driver.get(url)
    
    # Wait for ingredients to load
    try:
        # Wait for the ingredient list container
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "inv-slot-container")))
    except:
        return "❓ Timeout"

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    # Heuristic: Find the "Red Circle"
    # In BDOLytics, the red warning is usually a text-danger class or specific SVG fill
    # We look for "text-red" or similar indicators in the ingredient section
    
    # Find all ingredient rows (usually in the calculator box)
    # The warning icon usually has a class like 'text-red-500' or similar in Tailwind
    warnings = soup.find_all(lambda tag: tag.name in ['svg', 'i', 'span'] and 
                             tag.get('class') and 
                             any('text-red' in c or 'text-danger' in c for c in tag.get('class')))
    
    # Filter out warnings that might be unrelated (like "profit negative" text)
    # We only care if it's inside the ingredient list structure
    ingredient_warnings = 0
    for w in warnings:
        # Check if this warning is inside an ingredient row
        if w.find_parent(class_="inv-slot"):
            ingredient_warnings += 1
            
    if ingredient_warnings > 0:
        return "❌ Missing Ingredients"
    
    return "✅ In Stock"

# --- MAIN APP ---
if st.button("🚀 Start Deep Scan"):
    driver = get_driver()
    
    with st.spinner("Step 1: Getting Top Profit List..."):
        top_items = scrape_market_list(driver, region, category, limit)
        
    if not top_items:
        st.error("Failed to load list. BDOLytics might be slow.")
    else:
        st.success(f"Found {len(top_items)} items. Checking stock for each...")
        
        results = []
        bar = st.progress(0)
        status = st.empty()
        
        for i, item in enumerate(top_items):
            status.text(f"Checking: {item['Name']}...")
            
            stock_status = check_recipe_stock(driver, item['Link'])
            
            # Only add if In Stock (or if you want to see all, remove this if)
            if stock_status == "✅ In Stock":
                item['Status'] = stock_status
                results.append(item)
            
            bar.progress((i + 1) / len(top_items))
            # time.sleep(0.5) # Be polite to BDOLytics
            
        bar.empty()
        status.empty()
        
        if results:
            df = pd.DataFrame(results)
            st.dataframe(
                df[["Name", "Profit", "Status"]],
                use_container_width=True,
                column_config={
                    "Profit": st.column_config.NumberColumn(format="%d 💰")
                }
            )
        else:
            st.warning("No items found with full stock availability.")

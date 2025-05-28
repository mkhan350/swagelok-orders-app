import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Page setup
st.set_page_config(
    page_title="Swagelok Orders Manager", 
    page_icon="📦",
    layout="wide"
)

# Your API configurations
API_TOKEN = st.secrets["FULCRUM_API_TOKEN"]
BASE_URL = "https://api.fulcrumpro.us/api"

# Initialize session state
if 'orders_data' not in st.session_state:
    st.session_state.orders_data = None
if 'created_sos' not in st.session_state:
    st.session_state.created_sos = {}

# Authentication
def check_password():
    def password_entered():
        if st.session_state["password"] == "swagelok2025":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.write("*Please enter the company password to access the app*")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("Password incorrect")
        return False
    else:
        return True

# Main app
def main():
    st.title("🏭 Swagelok Orders Manager")
    
    if check_password():
        st.success("✅ Access granted!")
        
        # Sidebar for controls
        with st.sidebar:
            st.header("⚙️ Controls")
            
            # Order status selection
            order_status = st.selectbox(
                "Order Status:",
                [
                    "Order - New, Requires Supplier Action",
                    "Order - Modification, Requires Supplier Action",
                    "Ack - Sent", 
                    "Ack - Accepted",
                    "Order - History"
                ]
            )
            
            # Fetch orders button
            if st.button("🔄 Fetch Orders", type="primary"):
                with st.spinner("Fetching orders from Swagelok portal..."):
                    try:
                        headers, data = fetch_swagelok_orders(order_status)
                        if data:
                            st.session_state.orders_data = pd.DataFrame(data, columns=headers)
                            st.success(f"✅ Fetched {len(data)} orders successfully!")
                            st.rerun()
                        else:
                            st.error("❌ No orders found or connection failed")
                    except Exception as e:
                        st.error(f"❌ Error fetching orders: {str(e)}")
        
        # Main content area
        if st.session_state.orders_data is not None:
            st.header("📋 Open Orders")
            st.dataframe(st.session_state.orders_data, use_container_width=True)
        else:
            # Welcome screen
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Orders", "0")
            with col2:
                st.metric("SOs Created", len(st.session_state.created_sos))
            with col3:
                st.metric("API Status", "🟢 Online")
            
            st.info("👆 Use the sidebar to fetch orders and get started!")
            
            # Test API connection
            if st.button("Test API Connection"):
                with st.spinner("Testing API connection..."):
                    success = test_api_connection()
                    if success:
                        st.success("✅ API connection successful!")
                    else:
                        st.error("❌ API connection failed")

def test_api_connection():
    """Test connection to Fulcrum API"""
    try:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Test with a proper API call format
        payload = {
            "numbers": [{"query": "TEST", "mode": "equal"}],
            "latestRevision": True
        }
        
        response = requests.post(f"{BASE_URL}/items/list/v2", json=payload, headers=headers, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        return False

def fetch_swagelok_orders(selected_status):
    """Fetch orders from Swagelok portal using Selenium"""
    
    # Setup Chrome options for cloud deployment
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = None
    
    try:
        # Initialize WebDriver with system chromedriver
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)
        
        # Navigate to Swagelok login
        driver.get("https://supplierportal.swagelok.com//login.aspx")
        
        # Login
        username_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtUsername")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtPassword")))
        go_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_btnGo2")))

        username_field.send_keys("mstkhan")
        password_field.send_keys("Concept350!")
        go_button.click()

        # Handle terms page if it appears
        try:
            accept_terms_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_lnkAcceptTerms")))
            accept_terms_button.click()
        except:
            pass  # Terms page might not appear

        # Navigate to orders
        order_application_link = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_rptPortalApplications_ctl01_lnkPortalApplication")))
        order_application_link.click()
        driver.switch_to.window(driver.window_handles[-1])

        # Setup filters
        checkbox = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_chkOrdersRequiringAction")))
        checkbox.click()

        dropdown = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_cboRequestStatus")))
        for option in dropdown.find_elements(By.TAG_NAME, "option"):
            if option.text == selected_status:
                option.click()
                break

        search_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_btnSearch")))
        search_button.click()

        # Extract order data
        data = []
        row_index = 1
        max_iterations = 100  # Limit for cloud deployment
        
        while row_index <= max_iterations:
            try:
                order_details_id = f"ctl00_MainContentPlaceHolder_rptResults_ctl{row_index:02d}_trDetails"
                order_details_element = wait.until(EC.presence_of_element_located((By.ID, order_details_id)))
                
                order_details_text = order_details_element.text
                details = order_details_text.split()
                
                if selected_status in ["Order - New, Requires Supplier Action", "Order - History"]:
                    if len(details) >= 8:
                        order_number = details[0]
                        order_date = details[4]
                        part_number = details[5]
                        quantity = details[6]
                        delivery_date = details[7]
                        data.append([order_number, order_date, part_number, quantity, delivery_date])
                else:
                    if len(details) >= 10:
                        order_number = details[0]
                        order_date = details[7]
                        part_number = details[8]
                        quantity = details[9]
                        data.append([order_number, order_date, part_number, quantity])

                row_index += 1
                
            except:
                break  # No more rows found

        # Return headers and data
        if selected_status in ["Order - New, Requires Supplier Action", "Order - History"]:
            return ["Order Number", "Order Date", "Part Number", "Quantity", "Delivery Date"], data
        else:
            return ["Order Number", "Order Date", "Part Number", "Quantity"], data

    except Exception as e:
        st.error(f"Scraping error: {str(e)}")
        return [], []
        
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()

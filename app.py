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
from webdriver_manager.chrome import ChromeDriverManager

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
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'users_db' not in st.session_state:
    # Initialize with admin user
    st.session_state.users_db = {
        'mstkhan': {
            'first_name': 'Muhammad',
            'last_name': 'Khan',
            'username': 'mstkhan',
            'password': 'swagelok2025',
            'is_admin': True
        }
    }

# User Management Functions
def create_user_form():
    """Form to create new users (admin only)"""
    st.subheader("👤 Create New User")
    
    with st.form("create_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First Name")
            username = st.text_input("Username")
        with col2:
            last_name = st.text_input("Last Name")
            password = st.text_input("Password", type="password")
        
        submitted = st.form_submit_button("Create User")
        
        if submitted:
            if first_name and last_name and username and password:
                if username not in st.session_state.users_db:
                    st.session_state.users_db[username] = {
                        'first_name': first_name,
                        'last_name': last_name,
                        'username': username,
                        'password': password,
                        'is_admin': False
                    }
                    st.success(f"✅ User {first_name} {last_name} created successfully!")
                else:
                    st.error("❌ Username already exists!")
            else:
                st.error("❌ Please fill all fields!")

def change_password_form():
    """Form to change password"""
    st.subheader("🔒 Change Password")
    
    with st.form("change_password_form"):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        
        submitted = st.form_submit_button("Change Password")
        
        if submitted:
            current_user = st.session_state.users_db[st.session_state.current_user]
            if current_password == current_user['password']:
                if new_password == confirm_password and new_password:
                    st.session_state.users_db[st.session_state.current_user]['password'] = new_password
                    st.success("✅ Password changed successfully!")
                else:
                    st.error("❌ New passwords don't match or are empty!")
            else:
                st.error("❌ Current password is incorrect!")

# Authentication
def login_form():
    """Login form"""
    st.title("🏭 Swagelok Orders Manager")
    st.subheader("🔐 Login")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            if username in st.session_state.users_db:
                if st.session_state.users_db[username]['password'] == password:
                    st.session_state.current_user = username
                    st.experimental_rerun()
                else:
                    st.error("❌ Incorrect password!")
            else:
                st.error("❌ Username not found!")

def logout():
    """Logout function"""
    st.session_state.current_user = None
    st.session_state.orders_data = None
    st.experimental_rerun()

# Main app
def main():
    # Check if user is logged in
    if not st.session_state.current_user:
        login_form()
        return
    
    # Get current user info
    current_user = st.session_state.users_db[st.session_state.current_user]
    
    # Header with user info and buttons
    header_col1, header_col2, header_col3 = st.columns([3, 1, 1])
    
    with header_col1:
        st.title("🏭 Swagelok Orders Manager")
    
    with header_col2:
        if current_user['is_admin']:
            if st.button("👤 Create Users"):
                st.session_state.show_create_user = True
    
    with header_col3:
        if st.button("🚪 Logout"):
            logout()
    
    # Show user management forms if requested
    if current_user['is_admin'] and st.session_state.get('show_create_user', False):
        create_user_form()
        if st.button("← Back to Orders"):
            st.session_state.show_create_user = False
            st.experimental_rerun()
        return
    
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
                    else:
                        st.error("❌ No orders found or connection failed")
                except Exception as e:
                    st.error(f"❌ Error fetching orders: {str(e)}")
        
        # App info (moved from main page)
        st.header("📊 App Info")
        if st.session_state.orders_data is not None:
            st.metric("Total Orders", len(st.session_state.orders_data))
        else:
            st.metric("Total Orders", "0")
        st.metric("SOs Created", len(st.session_state.created_sos))
        st.metric("API Status", "🟢 Online")
        
        # Test API connection
        if st.button("Test API Connection"):
            with st.spinner("Testing API connection..."):
                success = test_api_connection()
                if success:
                    st.success("✅ API connection successful!")
                else:
                    st.error("❌ API connection failed")
        
        # Change password button
        st.header("🔧 Account")
        if st.button("🔒 Change Password"):
            st.session_state.show_change_password = True
    
    # Show change password form if requested
    if st.session_state.get('show_change_password', False):
        change_password_form()
        if st.button("← Back to Orders"):
            st.session_state.show_change_password = False
            st.experimental_rerun()
        return
    
    # Main content area
    if st.session_state.orders_data is not None:
        # Orders fetched - show orders table
        st.header("📋 Open Orders")
        st.write(f"**Found {len(st.session_state.orders_data)} orders:**")
        
        # Create enhanced table with action column
        df_display = st.session_state.orders_data.copy()
        df_display.insert(0, 'No.', range(1, len(df_display) + 1))
        
        # Display table
        st.dataframe(df_display, use_container_width=True)
        
        # Actions section with dropdowns
        st.subheader("🔧 Actions")
        for idx, row in st.session_state.orders_data.iterrows():
            col1, col2, col3, col4 = st.columns([1, 3, 2, 2])
            
            with col1:
                st.write(f"**{idx + 1}.**")
            
            with col2:
                st.write(f"**Order:** {row.iloc[0]} | **Part:** {row.iloc[2]}")
            
            with col3:
                st.write(f"**Qty:** {row.iloc[3]}")
            
            with col4:
                action = st.selectbox(
                    "Action",
                    ["Select Action", "Create SO"],
                    key=f"action_{idx}",
                    label_visibility="collapsed"
                )
                
                if action == "Create SO":
                    if st.button(f"Execute", key=f"execute_{idx}"):
                        st.info(f"Creating SO for Order {row.iloc[0]}...")
                        # SO creation functionality will be implemented here
    
    else:
        # Welcome screen
        st.markdown(f"# WELCOME **{current_user['first_name'].upper()}**")
        st.markdown("---")
        
        # Instructions
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.info("👆 Use the sidebar to fetch orders and get started!")
            st.markdown("""
            ### How to use:
            1. **Select Order Status** from the dropdown in the sidebar
            2. **Click 'Fetch Orders'** to retrieve orders from Swagelok portal
            3. **Review orders** in the main table
            4. **Use Action dropdowns** to create SOs for specific orders
            """)
        
        with col2:
            st.markdown("### Quick Stats")
            st.metric("Your Role", "Admin" if current_user['is_admin'] else "User")
            st.metric("Active Users", len(st.session_state.users_db))

def test_api_connection():
    """Test connection to Fulcrum API"""
    try:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        payload = {
            "numbers": [{"query": "TEST", "mode": "equal"}],
            "latestRevision": True
        }
        
        response = requests.post(f"{BASE_URL}/items/list/v2", json=payload, headers=headers, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        return False

def fetch_swagelok_orders(selected_status):
    """Fetch orders from Swagelok portal using Selenium"""
    
    # Setup Chrome options for cloud deployment with Chromium
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--remote-debugging-port=9222')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # For Streamlit Cloud with chromium packages
    options.binary_location = '/usr/bin/chromium'
    
    driver = None
    
    try:
        # Try to use system chromium-driver first, fallback to webdriver-manager
        try:
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(service=service, options=options)
        except:
            # Fallback to webdriver-manager
            service = Service(ChromeDriverManager().install())
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
        error_msg = f"Scraping error: {str(e)}"
        st.error(error_msg)
        
        # Debug info for deployment issues
        try:
            import os
            st.write("**Debug Info:**")
            st.write(f"Chromium exists: {os.path.exists('/usr/bin/chromium')}")
            st.write(f"ChromeDriver exists: {os.path.exists('/usr/bin/chromedriver')}")
        except:
            pass
            
        return [], []
        
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()

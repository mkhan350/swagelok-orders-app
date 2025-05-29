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
import json
import io
import sqlite3
import hashlib
import os

# Page setup
st.set_page_config(
    page_title="Swagelok Orders Manager", 
    page_icon="📦",
    layout="wide"
)

# Your API configurations
API_TOKEN = st.secrets["FULCRUM_API_TOKEN"]
BASE_URL = "https://api.fulcrumpro.us/api"

# ====== DATABASE MANAGEMENT FOR USER STORAGE ======
class UserDatabase:
    """Handles persistent user storage with SQLite"""
    
    def __init__(self, db_path="swagelok_users.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # Create admin user if not exists
        admin_exists = cursor.execute(
            "SELECT username FROM users WHERE username = ?", ("mstkhan",)
        ).fetchone()
        
        if not admin_exists:
            admin_password_hash = self.hash_password("swagelok2025")
            cursor.execute('''
                INSERT INTO users (username, first_name, last_name, password_hash, is_admin)
                VALUES (?, ?, ?, ?, ?)
            ''', ("mstkhan", "Muhammad", "Khan", admin_password_hash, True))
            
        conn.commit()
        conn.close()
    
    def hash_password(self, password):
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_password(self, password, password_hash):
        """Verify password against hash"""
        return self.hash_password(password) == password_hash
    
    def create_user(self, username, first_name, last_name, password, is_admin=False):
        """Create new user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if user exists
            if cursor.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone():
                conn.close()
                return False, "Username already exists"
            
            # Create user
            password_hash = self.hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, first_name, last_name, password_hash, is_admin)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, first_name, last_name, password_hash, is_admin))
            
            conn.commit()
            conn.close()
            return True, "User created successfully"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def authenticate_user(self, username, password):
        """Authenticate user login"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            user = cursor.execute('''
                SELECT username, first_name, last_name, password_hash, is_admin
                FROM users WHERE username = ?
            ''', (username,)).fetchone()
            
            if user and self.verify_password(password, user[3]):
                # Update last login
                cursor.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
                    (username,)
                )
                conn.commit()
                conn.close()
                
                return True, {
                    'username': user[0],
                    'first_name': user[1],
                    'last_name': user[2],
                    'is_admin': bool(user[4])
                }
            
            conn.close()
            return False, "Invalid username or password"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def change_password(self, username, old_password, new_password):
        """Change user password"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get current password hash
            user = cursor.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
            
            if not user or not self.verify_password(old_password, user[0]):
                conn.close()
                return False, "Current password is incorrect"
            
            # Update password
            new_password_hash = self.hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (new_password_hash, username)
            )
            
            conn.commit()
            conn.close()
            return True, "Password changed successfully"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def get_all_users(self):
        """Get all users (admin only)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            users = cursor.execute('''
                SELECT username, first_name, last_name, is_admin, created_at, last_login
                FROM users ORDER BY created_at DESC
            ''').fetchall()
            
            conn.close()
            return users
            
        except Exception as e:
            st.error(f"Database error: {str(e)}")
            return []

# Initialize database
@st.cache_resource
def get_user_db():
    return UserDatabase()

# Initialize session state
if 'orders_data' not in st.session_state:
    st.session_state.orders_data = None
if 'created_sos' not in st.session_state:
    st.session_state.created_sos = {}
if 'updated_delivery_dates' not in st.session_state:
    st.session_state.updated_delivery_dates = {}
if 'current_user' not in st.session_state:
    st.session_state.current_user = None

# ====== MIGRATED API CLIENT FROM DESKTOP APP ======
class OptimizedFulcrumAPI:
    """Migrated from desktop app - handles all Fulcrum API operations"""
    
    def __init__(self, token):
        self.api_token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.base_url = BASE_URL
        
    def _make_request(self, method, url, payload=None, max_retries=3):
        """Generic method with retry logic and better error handling"""
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = requests.get(url, headers=self.headers, timeout=30)
                elif method.upper() == "POST":
                    response = requests.post(url, json=payload, headers=self.headers, timeout=30)
                elif method.upper() == "DELETE":
                    response = requests.delete(url, headers=self.headers, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                if response.status_code in [200, 201, 204]:
                    return response.json() if response.content else {}
                elif response.status_code == 429:  # Rate limit
                    wait_time = 2 ** attempt
                    st.info(f"Rate limited. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    st.error(f"API Error {response.status_code}: {response.text}")
                    return None
                    
            except requests.exceptions.Timeout:
                st.error(f"Request timeout on attempt {attempt + 1}")
                if attempt == max_retries - 1:
                    return None
            except requests.exceptions.RequestException as e:
                st.error(f"Request error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(1)
        
        return None
    
    def check_item_exists(self, part_number):
        """Check if item exists and return its ID"""
        url = f"{self.base_url}/items/list/v2"
        payload = {
            "numbers": [{"query": part_number, "mode": "equal"}],
            "latestRevision": True
        }
        
        response_data = self._make_request("POST", url, payload)
        if response_data and isinstance(response_data, list) and len(response_data) > 0:
            item_id = response_data[0]["id"]
            st.success(f"Part '{part_number}' exists with ID: {item_id}")
            return item_id
        return None
    
    def create_item(self, part_number, description, price=None):
        """Create new item"""
        url = f"{self.base_url}/items"
        payload = {
            "number": part_number,
            "description": description or f"Swagelok Part {part_number}",
            "itemOrigin": "make",
            "unitTypeName": "Pieces",
            "unitOfMeasureName": "Pieces",
            "isSellable": True,
            "isTaxable": False,
            "minimumStockOnHand": 0,
            "minimumProductionQuantity": 0,
            "isLotTracked": True,
            "accountingCodeId": "63c80b38cd088c5cb605e40b",
            "categoryId": "65d508869733af68c352bdca"
        }
        
        response_data = self._make_request("POST", url, payload)
        if response_data and "id" in response_data:
            item_id = response_data["id"]
            st.success(f"Created item with ID: {item_id}")
            return item_id
        
        st.error("Failed to create item")
        return None
    
    def create_sales_order(self, order_data):
        """Create sales order"""
        url = f"{self.base_url}/sales-orders"
        
        response_data = self._make_request("POST", url, order_data)
        if response_data and "id" in response_data:
            return response_data["id"]
        return None
    
    def get_sales_order_details(self, sales_order_id):
        """Get sales order details"""
        url = f"{self.base_url}/sales-orders/{sales_order_id}"
        return self._make_request("GET", url)
    
    def add_part_line_item(self, sales_order_id, item_id, quantity, price):
        """Add part line item to sales order"""
        try:
            price_float = round(float(price), 2)
            if price_float <= 0.0:
                st.error(f"Invalid price ({price_float}) for part line item")
                return False

            url = f"{self.base_url}/sales-orders/{sales_order_id}/part-line-items"
            payload = {
                "itemId": item_id,
                "quantity": quantity,
                "price": price_float,
            }

            response_data = self._make_request("POST", url, payload)
            if response_data:
                st.success(f"Part line item added to sales order")
                return True
            else:
                st.error("Failed to add part line item")
                return False

        except (ValueError, TypeError) as e:
            st.error(f"Invalid price value: {price}. Error: {e}")
            return False

# Initialize API client
@st.cache_resource
def get_api_client():
    return OptimizedFulcrumAPI(API_TOKEN)

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
        
        is_admin = st.checkbox("Admin User")
        submitted = st.form_submit_button("Create User")
        
        if submitted:
            if first_name and last_name and username and password:
                user_db = get_user_db()
                success, message = user_db.create_user(username, first_name, last_name, password, is_admin)
                
                if success:
                    st.success(f"✅ {message}")
                else:
                    st.error(f"❌ {message}")
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
            if new_password != confirm_password:
                st.error("❌ New passwords don't match!")
            elif not new_password:
                st.error("❌ Password cannot be empty!")
            else:
                user_db = get_user_db()
                success, message = user_db.change_password(
                    st.session_state.current_user['username'], 
                    current_password, 
                    new_password
                )
                
                if success:
                    st.success(f"✅ {message}")
                else:
                    st.error(f"❌ {message}")

def view_users_form():
    """View all users (admin only)"""
    st.subheader("👥 All Users")
    
    user_db = get_user_db()
    users = user_db.get_all_users()
    
    if users:
        df = pd.DataFrame(users, columns=[
            'Username', 'First Name', 'Last Name', 'Admin', 'Created', 'Last Login'
        ])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No users found")

# Authentication
def login_form():
    """Login form with database authentication"""
    st.title("🏭 Swagelok Orders Manager")
    st.subheader("🔐 Login")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            user_db = get_user_db()
            success, result = user_db.authenticate_user(username, password)
            
            if success:
                st.session_state.current_user = result
                st.experimental_rerun()
            else:
                st.error(f"❌ {result}")

def logout():
    """Logout function"""
    st.session_state.current_user = None
    st.session_state.orders_data = None
    st.experimental_rerun()

# Business Logic Functions
def business_days_from(start_date, days):
    """Calculate business days from start date"""
    current_date = start_date
    while days > 0:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:
            days -= 1
    return current_date

def process_part_number(part_number, manual_price=None):
    """Process part number - simplified for web version"""
    api_client = get_api_client()
    
    # Check if item exists
    existing_item_id = api_client.check_item_exists(part_number)
    
    if existing_item_id:
        st.info(f"Item {part_number} already exists in system")
        return existing_item_id, manual_price or 100.0  # Default price
    else:
        # Create new item
        description = f"Swagelok Part {part_number}"
        item_id = api_client.create_item(part_number, description)
        return item_id, manual_price or 100.0  # Default price

def create_sales_order(order_row, delivery_date=None):
    """Create sales order from order data"""
    api_client = get_api_client()
    
    order_number = order_row[0]
    order_date = order_row[1]
    part_number = order_row[2]
    quantity = int(order_row[3])
    
    # Calculate due date
    if delivery_date:
        due_date_str = delivery_date
    else:
        due_date_str = order_row[4] if len(order_row) > 4 else business_days_from(datetime.strptime(order_date, "%m/%d/%Y"), 18).strftime("%m/%d/%Y")
    
    # Format due date
    if "-" in due_date_str:
        due_date_final = due_date_str
    else:
        due_date = datetime.strptime(due_date_str, "%m/%d/%Y")
        due_date_final = due_date.strftime("%Y-%m-%d")
    
    # Create sales order payload
    payload = {
        "customerId": "654241f9c77f04d8d76410c4",  # Swagelok customer ID
        "customerPoNumber": order_number,
        "orderedDate": datetime.strptime(order_date, "%m/%d/%Y").strftime("%Y-%m-%d"),
        "contact": {"firstName": "Kristian", "lastName": "Barnett"},
        "dueDate": due_date_final,
    }
    
    # Create sales order
    sales_order_id = api_client.create_sales_order(payload)
    if not sales_order_id:
        st.error("Failed to create sales order")
        return None
    
    # Get sales order details to get the SO number
    so_details = api_client.get_sales_order_details(sales_order_id)
    sales_order_number = so_details.get("number") if so_details else "Unknown"
    
    # Process part and add to order
    item_id, price = process_part_number(part_number)
    if item_id:
        api_client.add_part_line_item(sales_order_id, item_id, quantity, price)
        st.success(f"✅ Sales Order {sales_order_number} created successfully!")
        return sales_order_number
    else:
        st.error(f"Failed to process part {part_number}")
        return None

# Main app
def main():
    # Check if user is logged in
    if not st.session_state.current_user:
        login_form()
        return
    
    # Get current user info from session (already contains user data from database)
    current_user = st.session_state.current_user
    
    # Header with user info and buttons
    header_col1, header_col2, header_col3, header_col4 = st.columns([2, 1, 1, 1])
    
    with header_col1:
        st.title("🏭 Swagelok Orders Manager")
    
    with header_col2:
        if current_user['is_admin']:
            if st.button("👤 Create Users"):
                st.session_state.show_create_user = True
    
    with header_col3:
        if current_user['is_admin']:
            if st.button("👥 View Users"):
                st.session_state.show_view_users = True
    
    with header_col4:
        if st.button("🚪 Logout"):
            logout()
    
    # Show user management forms if requested
    if st.session_state.get('show_create_user', False):
        create_user_form()
        if st.button("← Back to Orders"):
            st.session_state.show_create_user = False
            st.experimental_rerun()
        return
    
    if st.session_state.get('show_view_users', False):
        view_users_form()
        if st.button("← Back to Orders"):
            st.session_state.show_view_users = False
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
        
        # App info
        st.header("📊 App Info")
        if st.session_state.orders_data is not None:
            st.metric("Total Orders", len(st.session_state.orders_data))
        else:
            st.metric("Total Orders", "0")
        st.metric("SOs Created", len(st.session_state.created_sos))
        
        # Get user count from database
        user_db = get_user_db()
        user_count = len(user_db.get_all_users())
        st.metric("Total Users", user_count)
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
        
        # Actions section with enhanced controls
        st.subheader("🔧 Actions")
        
        for idx, row in st.session_state.orders_data.iterrows():
            col1, col2, col3, col4, col5 = st.columns([0.5, 2.5, 1.5, 1.5, 1])
            
            with col1:
                st.write(f"**{idx + 1}.**")
            
            with col2:
                st.write(f"**Order:** {row.iloc[0]}")
                st.write(f"**Part:** {row.iloc[2]}")
            
            with col3:
                st.write(f"**Qty:** {row.iloc[3]}")
                # Add price input for manual override
                price_key = f"price_{idx}"
                if price_key not in st.session_state:
                    st.session_state[price_key] = 100.0
                st.session_state[price_key] = st.number_input(
                    "Price ($)", 
                    min_value=0.01, 
                    value=st.session_state[price_key],
                    key=f"price_input_{idx}",
                    step=0.01
                )
            
            with col4:
                # Delivery date picker
                if len(row) > 4:
                    default_date = datetime.strptime(row.iloc[4], "%m/%d/%Y").date()
                else:
                    default_date = business_days_from(datetime.now(), 18).date()
                
                delivery_date = st.date_input(
                    "Delivery Date",
                    value=default_date,
                    key=f"delivery_{idx}"
                )
            
            with col5:
                order_number = row.iloc[0]
                
                if order_number in st.session_state.created_sos:
                    st.success(f"✅ SO: {st.session_state.created_sos[order_number]}")
                else:
                    if st.button(f"Create SO", key=f"create_so_{idx}"):
                        with st.spinner(f"Creating SO for Order {order_number}..."):
                            # Convert row to list and add price
                            order_data = row.tolist()
                            manual_price = st.session_state[price_key]
                            
                            # Create sales order
                            so_number = create_sales_order(order_data, delivery_date.strftime("%Y-%m-%d"))
                            if so_number:
                                st.session_state.created_sos[order_number] = so_number
                                st.experimental_rerun()
    
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
            4. **Adjust prices and delivery dates** as needed
            5. **Click 'Create SO'** to create sales orders
            """)
        
        with col2:
            st.markdown("### Quick Stats")
            st.metric("Your Role", "Admin" if current_user['is_admin'] else "User")
            
            # Get user count from database
            user_db = get_user_db()
            user_count = len(user_db.get_all_users())
            st.metric("Active Users", user_count)

def test_api_connection():
    """Test connection to Fulcrum API"""
    try:
        api_client = get_api_client()
        # Try a simple API call
        headers = {
            "Authorization": f"Bearer {api_client.api_token}",
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
        return [], []
        
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()

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

# ====== DATABASE MANAGEMENT WITH GITHUB REPO BACKUP ======
class UserDatabase:
    """Handles persistent user storage with SQLite and GitHub repo backup"""
    
    def __init__(self, db_path="swagelok_users.db", repo_backup_path="users_backup.json"):
        self.db_path = db_path
        self.repo_backup_path = repo_backup_path
        self.init_database()
    
    def init_database(self):
        """Initialize database and load from repo backup if available"""
        # Try to load from repo backup file first
        if os.path.exists(self.repo_backup_path):
            self.load_from_repo_backup()
        
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
            # Update repo backup after creating admin
            self.create_repo_backup()
            
        conn.close()
    
    def load_from_repo_backup(self):
        """Load user data from repo backup file"""
        try:
            if not os.path.exists(self.repo_backup_path):
                return False
            
            with open(self.repo_backup_path, 'r') as f:
                backup_data = json.load(f)
            
            # Skip if backup is empty or invalid
            if not backup_data.get("users"):
                return False
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create table if not exists
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
            
            # Load users from backup
            for user in backup_data["users"]:
                cursor.execute('''
                    INSERT OR REPLACE INTO users 
                    (username, first_name, last_name, password_hash, is_admin, created_at, last_login)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user["username"],
                    user["first_name"], 
                    user["last_name"],
                    user["password_hash"],
                    user["is_admin"],
                    user.get("created_at"),
                    user.get("last_login")
                ))
            
            conn.commit()
            conn.close()
            
            st.success(f"✅ Loaded {len(backup_data['users'])} users from repo backup!")
            return True
            
        except Exception as e:
            st.error(f"Failed to load from repo backup: {str(e)}")
            return False
    
    def create_repo_backup(self):
        """Create backup file that can be committed to repo"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            users = cursor.execute('''
                SELECT username, first_name, last_name, password_hash, is_admin, created_at, last_login
                FROM users ORDER BY created_at DESC
            ''').fetchall()
            
            # Convert to dict format
            backup_data = {
                "backup_timestamp": datetime.now().isoformat(),
                "users": []
            }
            
            for user in users:
                backup_data["users"].append({
                    "username": user[0],
                    "first_name": user[1],
                    "last_name": user[2],
                    "password_hash": user[3],
                    "is_admin": bool(user[4]),
                    "created_at": user[5],
                    "last_login": user[6]
                })
            
            # Write backup file to repo location
            with open(self.repo_backup_path, 'w') as f:
                json.dump(backup_data, f, indent=2)
            
            conn.close()
            return backup_data
            
        except Exception as e:
            st.error(f"Backup creation failed: {str(e)}")
            return None
    
    def get_backup_download(self):
        """Get backup data for download"""
        backup_data = self.create_repo_backup()
        if backup_data:
            return json.dumps(backup_data, indent=2)
        return None
    
    def hash_password(self, password):
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_password(self, password, password_hash):
        """Verify password against hash"""
        return self.hash_password(password) == password_hash
    
    def create_user(self, username, first_name, last_name, password, is_admin=False):
        """Create new user and update repo backup"""
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
            
            # Update repo backup after user creation
            self.create_repo_backup()
            
            return True, "User created successfully"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def authenticate_user(self, username, password):
        """Authenticate user login and update backup"""
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
                
                # Update repo backup after login
                self.create_repo_backup()
                
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
        """Change user password and update backup"""
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
            
            # Update repo backup after password change
            self.create_repo_backup()
            
            return True, "Password changed successfully"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def get_all_users(self):
        """Get all users"""
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
    
    def get_backup_status(self):
        """Get status of repo backup file"""
        if os.path.exists(self.repo_backup_path):
            try:
                with open(self.repo_backup_path, 'r') as f:
                    backup_data = json.load(f)
                
                backup_time = backup_data.get("backup_timestamp", "Unknown")
                user_count = len(backup_data.get("users", []))
                
                return True, f"✅ {user_count} users, updated: {backup_time[:19]}"
            except:
                return False, "⚠️ Backup file corrupted"
        else:
            return False, "❌ No backup file found"

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
    """View all users and backup management (admin only)"""
    st.subheader("👥 All Users")
    
    user_db = get_user_db()
    
    # Backup status section
    st.markdown("### 📁 Repo Backup Status")
    backup_exists, backup_status = user_db.get_backup_status()
    
    if backup_exists:
        st.success(backup_status)
    else:
        st.warning(backup_status)
    
    # Backup management
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📄 Download Updated Backup"):
            backup_json = user_db.get_backup_download()
            if backup_json:
                st.download_button(
                    label="💾 Download users_backup.json",
                    data=backup_json,
                    file_name="users_backup.json",
                    mime="application/json"
                )
                st.info("📋 **Instructions:** Download this file and replace `users_backup.json` in your GitHub repo to make changes permanent.")
    
    with col2:
        st.info("🔄 Backup auto-updates on user changes")
    
    st.markdown("### 👤 User List")
    users = user_db.get_all_users()
    
    if users:
        df = pd.DataFrame(users, columns=[
            'Username', 'First Name', 'Last Name', 'Admin', 'Created', 'Last Login'
        ])
        st.dataframe(df, use_container_width=True)
        
        st.markdown("### 📋 How Repo Backup Works")
        st.markdown("""
        **Automatic Process:**
        - ✅ **Auto-loads** from `users_backup.json` in your repo on app start
        - ✅ **Auto-updates** backup file after every user change
        - ✅ **Survives rebuilds** when backup file is in your GitHub repo
        
        **To Make Changes Permanent:**
        1. **Download** updated backup using button above
        2. **Replace** `users_backup.json` in your GitHub repo  
        3. **Commit & push** to GitHub
        4. **Users persist** across all future app rebuilds!
        """)
    else:
        st.info("No users found")

# Authentication
def login_form():
    """Centered login form with logo and proper title"""
    
    # Create centered columns - make wider for the title
    col1, col2, col3 = st.columns([1.5, 2, 1.5])
    
    with col2:
        # Logo (upload this file to your GitHub repo)
        try:
            st.image("concept_insulon_logo.png", width=200)
        except:
            # Placeholder if logo file isn't found
            st.markdown("**[CONCEPT INSULON LOGO]**")
        
        # Single line title with smaller font size
        st.markdown("<h2 style='text-align: center; margin-top: 1rem; font-size: 1.5rem; white-space: nowrap;'>FV - Open Orders Management System</h2>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center; margin-bottom: 2rem;'>🔐 Login</h3>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            # Center the login button
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
            with col_btn2:
                submitted = st.form_submit_button("Login", use_container_width=True)
            
            if submitted:
                user_db = get_user_db()
                success, result = user_db.authenticate_user(username, password)
                
                if success:
                    # Clear all session state for fresh login
                    for key in list(st.session_state.keys()):
                        if key not in ['current_user']:
                            del st.session_state[key]
                    
                    st.session_state.current_user = result
                    st.session_state.orders_data = None
                    st.session_state.created_sos = {}
                    st.session_state.updated_delivery_dates = {}
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
    
    # Get current user info from session
    current_user = st.session_state.current_user
    
    # Header with just the title
    st.title("Swagelok Open Orders")
    
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
    
    if st.session_state.get('show_change_password', False):
        change_password_form()
        if st.button("← Back to Orders"):
            st.session_state.show_change_password = False
            st.experimental_rerun()
        return
    
    # Sidebar for controls only
    with st.sidebar:
        st.header("Controls")
        
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
        if st.button("Fetch Orders", type="primary"):
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
        
        # Test API connection
        if st.button("Test API Connection"):
            with st.spinner("Testing API connection..."):
                success = test_api_connection()
                if success:
                    st.success("✅ API connection successful!")
                else:
                    st.error("❌ API connection failed")
        
        # Backup status (for admins)
        if current_user['is_admin']:
            st.markdown("---")
            st.markdown("**📁 Backup Status**")
            user_db = get_user_db()
            backup_status = user_db.view_backup_status()
            if "✅" in backup_status:
                st.success("Backup Active")
            elif "⚠️" in backup_status:
                st.warning("Backup Issue")
            else:
                st.error("No Backup")
    
    # Main content area
    if st.session_state.orders_data is not None:
        # Orders fetched - show orders table with inline actions
        st.header("Open Orders")
        st.write(f"**Found {len(st.session_state.orders_data)} orders:**")
        
        # Create table with inline action buttons
        for idx, row in st.session_state.orders_data.iterrows():
            # Create columns for each row
            col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 1.5, 1.5, 2, 1, 1.5, 1.5])
            
            with col1:
                st.write(f"**{idx + 1}.**")
            
            with col2:
                st.write(f"**{row.iloc[0]}**")  # Order Number
                st.caption("Order #")
            
            with col3:
                st.write(f"{row.iloc[1]}")  # Order Date
                st.caption("Date")
            
            with col4:
                st.write(f"**{row.iloc[2]}**")  # Part Number
                st.caption("Part Number")
            
            with col5:
                st.write(f"{row.iloc[3]}")  # Quantity
                st.caption("Qty")
            
            with col6:
                if len(row) > 4:
                    # Delivery date picker for orders that have delivery date
                    default_date = datetime.strptime(row.iloc[4], "%m/%d/%Y").date()
                    delivery_date = st.date_input(
                        "Delivery",
                        value=default_date,
                        key=f"delivery_{idx}",
                        label_visibility="collapsed"
                    )
                    st.caption("Delivery Date")
                else:
                    # Default delivery date for orders without it
                    default_date = business_days_from(datetime.now(), 18).date()
                    delivery_date = st.date_input(
                        "Delivery",
                        value=default_date,
                        key=f"delivery_{idx}",
                        label_visibility="collapsed"
                    )
                    st.caption("Delivery Date")
            
            with col7:
                order_number = row.iloc[0]
                
                if order_number in st.session_state.created_sos:
                    st.success(f"SO: {st.session_state.created_sos[order_number]}")
                else:
                    # Action dropdown
                    action = st.selectbox(
                        "Action",
                        ["Select Action", "Create SO"],
                        key=f"action_{idx}",
                        label_visibility="collapsed"
                    )
                    
                    if action == "Create SO":
                        if st.button(f"Execute", key=f"execute_{idx}"):
                            with st.spinner(f"Creating SO for Order {order_number}..."):
                                # Get price - default to 100.0 for now
                                manual_price = 100.0
                                
                                # Convert row to list
                                order_data = row.tolist()
                                
                                # Create sales order
                                so_number = create_sales_order(order_data, delivery_date.strftime("%Y-%m-%d"))
                                if so_number:
                                    st.session_state.created_sos[order_number] = so_number
                                    st.experimental_rerun()
            
            # Add separator line
            st.markdown("---")
    
    else:
        # Welcome screen
        st.markdown(f"# WELCOME **{current_user['first_name'].upper()}**")
        st.markdown("---")
        
        # Instructions only
        st.info("👆 Use the sidebar to fetch orders and get started!")
        st.markdown("""
        ### How to use:
        1. **Select Order Status** from the dropdown in the sidebar
        2. **Click 'Fetch Orders'** to retrieve orders from Swagelok portal
        3. **Review orders** in the main table
        4. **Adjust delivery dates** as needed
        5. **Select 'Create SO'** from action dropdown and click Execute
        """)

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

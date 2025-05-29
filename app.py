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

# Custom CSS for action column styling
st.markdown("""
<style>
.action-column {
    background-color: #e3f2fd !important;
    border-radius: 8px !important;
    padding: 8px !important;
    border: 2px solid #2196f3 !important;
    margin: 2px 0 !important;
}

.action-column .stSelectbox > div > div {
    background-color: #2196f3 !important;
    color: white !important;
    border-radius: 4px !important;
}

.action-column .stSelectbox > div > div > div {
    color: white !important;
}

.action-column .stSelectbox {
    background-color: #2196f3 !important;
}

.action-column .stButton > button {
    background-color: #2196f3 !important;
    color: white !important;
    border: none !important;
    border-radius: 4px !important;
    font-weight: bold !important;
}

.action-column .stButton > button:hover {
    background-color: #1976d2 !important;
    color: white !important;
}

.success-action {
    background-color: #e8f5e8 !important;
    border: 2px solid #4caf50 !important;
    border-radius: 8px !important;
    padding: 8px !important;
    text-align: center !important;
    font-weight: bold !important;
    color: #2e7d32 !important;
}
</style>
""", unsafe_allow_html=True)

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
            
            return True
            
        except Exception as e:
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
                    time.sleep(wait_time)
                    continue
                else:
                    return None
                    
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    return None
            except requests.exceptions.RequestException as e:
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
            return item_id
        
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
                return False

            url = f"{self.base_url}/sales-orders/{sales_order_id}/part-line-items"
            payload = {
                "itemId": item_id,
                "quantity": quantity,
                "price": price_float,
            }

            response_data = self._make_request("POST", url, payload)
            if response_data:
                return True
            else:
                return False

        except (ValueError, TypeError) as e:
            return False

# Initialize API client
@st.cache_resource
def get_api_client():
    return OptimizedFulcrumAPI(API_TOKEN)

# Business Logic Functions
def business_days_from(start_date, days):
    """Calculate business days from start date (excluding weekends)"""
    current_date = start_date
    days_added = 0
    
    while days_added < days:
        current_date += timedelta(days=1)
        # Only count weekdays (Monday=0, Sunday=6)
        if current_date.weekday() < 5:
            days_added += 1
    
    return current_date

def parse_date_safely(date_str):
    """Safely parse date string in various formats"""
    if not date_str or date_str in ["TBD", "Delivered", ""]:
        return None
    
    # Try different date formats
    date_formats = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue
    
    return None

def format_delivery_date(date_input):
    """Format delivery date for API consumption"""
    if isinstance(date_input, str):
        parsed_date = parse_date_safely(date_input)
        if parsed_date:
            return parsed_date.strftime("%Y-%m-%d")
        else:
            # If can't parse, calculate 18 business days from today
            calculated_date = business_days_from(datetime.now(), 18)
            return calculated_date.strftime("%Y-%m-%d")
    elif hasattr(date_input, 'strftime'):  # datetime or date object
        return date_input.strftime("%Y-%m-%d")
    else:
        # Default fallback
        calculated_date = business_days_from(datetime.now(), 18)
        return calculated_date.strftime("%Y-%m-%d")

def process_part_number(part_number, manual_price=None):
    """Process part number - simplified for web version"""
    api_client = get_api_client()
    
    # Check if item exists
    existing_item_id = api_client.check_item_exists(part_number)
    
    if existing_item_id:
        return existing_item_id, manual_price or 100.0  # Default price
    else:
        # Create new item
        description = f"Swagelok Part {part_number}"
        item_id = api_client.create_item(part_number, description)
        return item_id, manual_price or 100.0  # Default price

def create_sales_order(order_row, delivery_date=None):
    """Create sales order from order data"""
    api_client = get_api_client()
    
    try:
        order_number = str(order_row[0]).strip()
        order_date = str(order_row[1]).strip()
        part_number = str(order_row[2]).strip()
        quantity = int(order_row[3])
        
        # Handle delivery date with improved logic
        if delivery_date:
            due_date_final = format_delivery_date(delivery_date)
        elif len(order_row) > 4:
            # Try to use delivery date from order data
            delivery_from_data = str(order_row[4]).strip() if len(order_row) > 4 else None
            if delivery_from_data and delivery_from_data not in ["", "TBD", "Delivered"]:
                due_date_final = format_delivery_date(delivery_from_data)
            else:
                # Calculate 18 business days from order date
                order_dt = parse_date_safely(order_date)
                if order_dt:
                    calculated_date = business_days_from(order_dt, 18)
                    due_date_final = calculated_date.strftime("%Y-%m-%d")
                else:
                    # Fallback to 18 business days from today
                    calculated_date = business_days_from(datetime.now(), 18)
                    due_date_final = calculated_date.strftime("%Y-%m-%d")
        else:
            # Calculate 18 business days from order date
            order_dt = parse_date_safely(order_date)
            if order_dt:
                calculated_date = business_days_from(order_dt, 18)
                due_date_final = calculated_date.strftime("%Y-%m-%d")
            else:
                # Fallback to 18 business days from today
                calculated_date = business_days_from(datetime.now(), 18)
                due_date_final = calculated_date.strftime("%Y-%m-%d")
        
        # Format order date for API
        order_dt = parse_date_safely(order_date)
        if order_dt:
            order_date_final = order_dt.strftime("%Y-%m-%d")
        else:
            order_date_final = datetime.now().strftime("%Y-%m-%d")
        
        # Create sales order payload
        payload = {
            "customerId": "654241f9c77f04d8d76410c4",  # Swagelok customer ID
            "customerPoNumber": order_number,
            "orderedDate": order_date_final,
            "contact": {"firstName": "Kristian", "lastName": "Barnett"},
            "dueDate": due_date_final,
        }
        
        # Create sales order
        sales_order_id = api_client.create_sales_order(payload)
        if not sales_order_id:
            return None
        
        # Get sales order details to get the SO number
        so_details = api_client.get_sales_order_details(sales_order_id)
        sales_order_number = so_details.get("number") if so_details else "Unknown"
        
        # Process part and add to order
        item_id, price = process_part_number(part_number)
        if item_id:
            success = api_client.add_part_line_item(sales_order_id, item_id, quantity, price)
            if success:
                return sales_order_number
            else:
                return None
        else:
            return None
            
    except Exception as e:
        st.error(f"Error creating sales order: {str(e)}")
        return None

def fetch_swagelok_orders(selected_status):
    """Fetch orders from Swagelok portal with improved parsing"""
    
    driver = None
    
    try:
        # Chrome options configuration
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox') 
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--single-process')
        
        try:
            options.binary_location = '/usr/bin/chromium'
        except:
            pass
        
        # Initialize driver
        try:
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e1:
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            except Exception as e2:
                return [], []
        
        # Set timeouts
        driver.set_page_load_timeout(20)
        wait = WebDriverWait(driver, 15)
        
        # Navigation and login
        driver.get("https://supplierportal.swagelok.com//login.aspx")
        
        username_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtUsername")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtPassword")))
        go_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_btnGo2")))

        username_field.send_keys("mstkhan")
        password_field.send_keys("Concept350!")
        go_button.click()

        # Handle terms page
        try:
            accept_terms_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_lnkAcceptTerms")))
            accept_terms_button.click()
        except:
            pass

        # Navigate to orders
        order_application_link = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_rptPortalApplications_ctl01_lnkPortalApplication")))
        order_application_link.click()
        driver.switch_to.window(driver.window_handles[-1])

        # Setup filters
        checkbox = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_chkOrdersRequiringAction")))
        if not checkbox.is_selected():
            checkbox.click()

        dropdown = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_cboRequestStatus")))
        for option in dropdown.find_elements(By.TAG_NAME, "option"):
            if option.text == selected_status:
                option.click()
                break

        search_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_btnSearch")))
        search_button.click()

        # Extract data with improved parsing
        data = []
        row_index = 1
        max_iterations = 50
        
        while row_index <= max_iterations:
            try:
                order_details_id = f"ctl00_MainContentPlaceHolder_rptResults_ctl{row_index:02d}_trDetails"
                
                try:
                    order_details_element = wait.until(EC.presence_of_element_located((By.ID, order_details_id)))
                except:
                    break
                
                order_details_text = order_details_element.text.strip()
                if not order_details_text:
                    row_index += 1
                    continue
                    
                details = order_details_text.split()
                
                # Improved parsing logic based on order status
                if selected_status == "Order - History":
                    # Expected format: OrderNumber Order - History Date PartNumber Qty SalesOrder [DeliveryDate] ...
                    if len(details) >= 8:
                        order_number = details[0]
                        
                        # Find the date (should be after "History")
                        date_index = -1
                        for i, detail in enumerate(details):
                            if detail == "History" and i + 1 < len(details):
                                date_index = i + 1
                                break
                        
                        if date_index > 0 and date_index < len(details):
                            order_date = details[date_index]
                            part_number = details[date_index + 1] if date_index + 1 < len(details) else ""
                            quantity = details[date_index + 2] if date_index + 2 < len(details) else "0"
                            sales_order = details[date_index + 3] if date_index + 3 < len(details) else ""
                            
                            # Look for delivery date (should contain "/")
                            delivery_date = "Delivered"
                            if date_index + 4 < len(details) and "/" in str(details[date_index + 4]):
                                delivery_date = details[date_index + 4]
                            
                            data.append([order_number, order_date, part_number, quantity, sales_order, delivery_date])
                
                elif selected_status == "Order - New, Requires Supplier Action":
                    # Expected format: OrderNumber Order - New, Requires Supplier Action Date PartNumber Qty DeliveryDate ...
                    if len(details) >= 11:
                        order_number = details[0]
                        
                        # Find the date (should be after "Action")
                        date_index = -1
                        for i, detail in enumerate(details):
                            if detail == "Action" and i + 1 < len(details):
                                date_index = i + 1
                                break
                        
                        if date_index > 0 and date_index < len(details):
                            order_date = details[date_index]
                            part_number = details[date_index + 1] if date_index + 1 < len(details) else ""
                            quantity = details[date_index + 2] if date_index + 2 < len(details) else "0"
                            delivery_date = details[date_index + 3] if date_index + 3 < len(details) else ""
                            
                            # Validate delivery date format
                            if not delivery_date or "/" not in delivery_date:
                                # Calculate default delivery date
                                order_dt = parse_date_safely(order_date)
                                if order_dt:
                                    delivery_dt = business_days_from(order_dt, 18)
                                    delivery_date = delivery_dt.strftime("%m/%d/%Y")
                                else:
                                    delivery_date = "TBD"
                            
                            data.append([order_number, order_date, part_number, quantity, delivery_date])
                
                elif selected_status == "Order - Modification, Requires Supplier Action":
                    # Expected format: OrderNumber Order - Modification, Requires Supplier Action Date PartNumber Qty SalesOrder ...
                    if len(details) >= 11:
                        order_number = details[0]
                        
                        # Find the date (should be after "Action")
                        date_index = -1
                        for i, detail in enumerate(details):
                            if detail == "Action" and i + 1 < len(details):
                                date_index = i + 1
                                break
                        
                        if date_index > 0 and date_index < len(details):
                            order_date = details[date_index]
                            part_number = details[date_index + 1] if date_index + 1 < len(details) else ""
                            quantity = details[date_index + 2] if date_index + 2 < len(details) else "0"
                            sales_order = details[date_index + 3] if date_index + 3 < len(details) else ""
                            
                            # Calculate delivery date (18 business days from order date)
                            order_dt = parse_date_safely(order_date)
                            if order_dt:
                                delivery_dt = business_days_from(order_dt, 18)
                                delivery_date = delivery_dt.strftime("%m/%d/%Y")
                            else:
                                delivery_date = "TBD"
                            
                            data.append([order_number, order_date, part_number, quantity, sales_order, delivery_date])
                
                else:
                    # Other statuses - generic parsing
                    if len(details) >= 10:
                        order_number = details[0]
                        
                        # Look for date pattern in the details
                        order_date = ""
                        part_number = ""
                        quantity = "0"
                        
                        for i, detail in enumerate(details):
                            if "/" in detail and len(detail.split("/")) == 3:
                                order_date = detail
                                if i + 1 < len(details):
                                    part_number = details[i + 1]
                                if i + 2 < len(details):
                                    quantity = details[i + 2]
                                break
                        
                        # Calculate delivery date
                        order_dt = parse_date_safely(order_date)
                        if order_dt:
                            delivery_dt = business_days_from(order_dt, 18)
                            delivery_date = delivery_dt.strftime("%m/%d/%Y")
                        else:
                            delivery_date = "TBD"
                        
                        if order_date and part_number:
                            data.append([order_number, order_date, part_number, quantity, delivery_date])

                row_index += 1
                
            except Exception as e:
                row_index += 1
                continue

        # Return appropriate headers based on data structure
        if data and len(data[0]) == 6:  # Has sales order column
            return ["Order Number", "Order Date", "Part Number", "Quantity", "Sales Order", "Delivery Date"], data
        elif data and len(data[0]) == 5:  # No sales order column
            return ["Order Number", "Order Date", "Part Number", "Quantity", "Delivery Date"], data
        else:
            return [], []

    except Exception as e:
        return [], []
        
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

# User Management Functions (keeping existing ones)
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
    
    # Simple backup status check
    try:
        if os.path.exists("users_backup.json"):
            st.success("✅ Backup file exists in repo")
        else:
            st.warning("❌ No backup file found")
    except:
        st.error("❌ Backup check failed")
    
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
                    st.rerun()
                else:
                    st.error(f"❌ {result}")

def logout():
    """Logout function"""
    st.session_state.current_user = None
    st.session_state.orders_data = None
    st.rerun()

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
            st.rerun()
        return
    
    if st.session_state.get('show_view_users', False):
        view_users_form()
        if st.button("← Back to Orders"):
            st.session_state.show_view_users = False
            st.rerun()
        return
    
    if st.session_state.get('show_change_password', False):
        change_password_form()
        if st.button("← Back to Orders"):
            st.session_state.show_change_password = False
            st.rerun()
        return
    
    # Sidebar for controls and account
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
        
        # Clear old data when order status changes
        if st.session_state.get('last_order_status') != order_status:
            st.session_state.orders_data = None
            st.session_state.created_sos = {}
            st.session_state.last_order_status = order_status
        
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
        
        # Separator
        st.markdown("---")
        
        # Account section at bottom
        st.header("Account")
        
        # Show current user info
        st.markdown(f"**Logged in as:** {current_user['first_name']} {current_user['last_name']}")
        st.markdown(f"**Role:** {'Administrator' if current_user['is_admin'] else 'User'}")
        
        # Account management buttons
        if current_user['is_admin']:
            if st.button("👤 Create Users", use_container_width=True):
                st.session_state.show_create_user = True
                st.rerun()
            
            if st.button("👥 View Users", use_container_width=True):
                st.session_state.show_view_users = True
                st.rerun()
        
        if st.button("🔒 Change Password", use_container_width=True):
            st.session_state.show_change_password = True
            st.rerun()
        
        if st.button("🚪 Logout", use_container_width=True):
            logout()
        
        # Backup status (for admins)
        if current_user['is_admin']:
            st.markdown("---")
            st.markdown("**📁 Backup Status**")
            
            # Simple backup status check
            try:
                if os.path.exists("users_backup.json"):
                    st.success("✅ Repo Backup Active")
                else:
                    st.warning("⚠️ No Backup File")
            except:
                st.error("❌ Backup Check Failed")
    
    # Main content area
    if st.session_state.orders_data is not None:
        # Orders fetched - show orders table with proper headers
        st.header("Open Orders")
        st.write(f"**Found {len(st.session_state.orders_data)} orders:**")
        st.info("💡 **Tip:** All delivery dates are editable - adjust them as needed before creating Sales Orders!")
        
        # Get column names from the DataFrame
        columns = st.session_state.orders_data.columns.tolist()
        
        # Create proper table headers based on the order status
        if len(columns) == 6:  # Has Sales Order column (Order History and Order Modification)
            header_cols = st.columns([0.5, 1.2, 1.2, 2, 1, 1.2, 1.2, 1.5])
            headers = ["No.", "Order #", "Date", "Part Number", "Qty", "Sales Order", "Delivery", "Action"]
        else:  # No Sales Order column (Order New and others)
            header_cols = st.columns([0.5, 1.2, 1.2, 2, 1, 1.5, 1.5])
            headers = ["No.", "Order #", "Date", "Part Number", "Qty", "Delivery", "Action"]
        
        # Display headers
        for i, header in enumerate(headers):
            with header_cols[i]:
                st.markdown(f"**{header}**")
        
        st.markdown("---")  # Separator line
        
        # Display data rows with improved delivery date handling
        for idx, row in st.session_state.orders_data.iterrows():
            if len(columns) == 6:  # Has Sales Order column
                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([0.5, 1.2, 1.2, 2, 1, 1.2, 1.2, 1.5])
                
                with col1:
                    st.write(f"{idx + 1}")
                with col2:
                    st.write(f"{row.iloc[0]}")  # Order Number
                with col3:
                    st.write(f"{row.iloc[1]}")  # Order Date
                with col4:
                    st.write(f"{row.iloc[2]}")  # Part Number
                with col5:
                    st.write(f"{row.iloc[3]}")  # Quantity
                with col6:
                    st.write(f"{row.iloc[4]}")  # Sales Order
                with col7:
                    delivery_value = str(row.iloc[5])  # Delivery Date
                    
                    # Make all delivery dates editable except "Delivered"
                    if delivery_value == "Delivered":
                        st.write("Delivered")
                        delivery_date = None  # Can't change delivered orders
                    else:
                        # Parse existing date or calculate default
                        parsed_date = parse_date_safely(delivery_value)
                        if parsed_date:
                            default_delivery = parsed_date.date()
                        else:
                            # Calculate default delivery date (18 business days from order date)
                            order_dt = parse_date_safely(str(row.iloc[1]))
                            if order_dt:
                                default_delivery = business_days_from(order_dt, 18).date()
                            else:
                                default_delivery = business_days_from(datetime.now(), 18).date()
                        
                        delivery_date = st.date_input(
                            "Delivery",
                            value=default_delivery,
                            key=f"delivery_{idx}",
                            label_visibility="collapsed"
                        )
                with col8:
                    order_number = str(row.iloc[0])
                    if order_number in st.session_state.created_sos:
                        st.markdown(f'<div class="success-action">✅ SO: {st.session_state.created_sos[order_number]}</div>', unsafe_allow_html=True)
                    else:
                        # Create container with blue background for action elements
                        action_container = st.container()
                        with action_container:
                            st.markdown('<div class="action-column">', unsafe_allow_html=True)
                            action = st.selectbox(
                                "Action",
                                ["Select Action", "Create SO"],
                                key=f"action_{idx}",
                                label_visibility="collapsed"
                            )
                            if action == "Create SO":
                                if st.button(f"Execute", key=f"execute_{idx}"):
                                    with st.spinner(f"Creating SO for Order {order_number}..."):
                                        order_data = row.tolist()
                                        # Use the editable delivery date if available, otherwise use original
                                        if delivery_date is not None:
                                            so_number = create_sales_order(order_data, delivery_date)
                                        else:
                                            so_number = create_sales_order(order_data, str(row.iloc[5]))
                                        
                                        if so_number:
                                            st.session_state.created_sos[order_number] = so_number
                                            st.success(f"✅ Created SO: {so_number}")
                                            st.rerun()
                                        else:
                                            st.error("❌ Failed to create Sales Order")
                            st.markdown('</div>', unsafe_allow_html=True)
            
            else:  # No Sales Order column (5 columns)
                col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 1.2, 1.2, 2, 1, 1.5, 1.5])
                
                with col1:
                    st.write(f"{idx + 1}")
                with col2:
                    st.write(f"{row.iloc[0]}")  # Order Number
                with col3:
                    st.write(f"{row.iloc[1]}")  # Order Date
                with col4:
                    st.write(f"{row.iloc[2]}")  # Part Number
                with col5:
                    st.write(f"{row.iloc[3]}")  # Quantity
                with col6:
                    # Delivery date - handle editable dates for new orders
                    delivery_value = str(row.iloc[4])  # Delivery Date
                    
                    if delivery_value in ["TBD", "Delivered", ""]:
                        # Calculate a default date for TBD orders
                        order_dt = parse_date_safely(str(row.iloc[1]))
                        if order_dt:
                            default_delivery = business_days_from(order_dt, 18).date()
                        else:
                            default_delivery = business_days_from(datetime.now(), 18).date()
                        
                        delivery_date = st.date_input(
                            "Delivery",
                            value=default_delivery,
                            key=f"delivery_{idx}",
                            label_visibility="collapsed"
                        )
                    else:
                        # Try to parse existing date and make it editable
                        parsed_date = parse_date_safely(delivery_value)
                        if parsed_date:
                            delivery_date = st.date_input(
                                "Delivery",
                                value=parsed_date.date(),
                                key=f"delivery_{idx}",
                                label_visibility="collapsed"
                            )
                        else:
                            # Fallback to calculated date
                            order_dt = parse_date_safely(str(row.iloc[1]))
                            if order_dt:
                                default_delivery = business_days_from(order_dt, 18).date()
                            else:
                                default_delivery = business_days_from(datetime.now(), 18).date()
                            
                            delivery_date = st.date_input(
                                "Delivery",
                                value=default_delivery,
                                key=f"delivery_{idx}",
                                label_visibility="collapsed"
                            )
                
                with col7:
                    order_number = str(row.iloc[0])
                    if order_number in st.session_state.created_sos:
                        st.markdown(f'<div class="success-action">✅ SO: {st.session_state.created_sos[order_number]}</div>', unsafe_allow_html=True)
                    else:
                        # Create container with blue background for action elements
                        action_container = st.container()
                        with action_container:
                            st.markdown('<div class="action-column">', unsafe_allow_html=True)
                            action = st.selectbox(
                                "Action",
                                ["Select Action", "Create SO"],
                                key=f"action_{idx}",
                                label_visibility="collapsed"
                            )
                            if action == "Create SO":
                                if st.button(f"Execute", key=f"execute_{idx}"):
                                    with st.spinner(f"Creating SO for Order {order_number}..."):
                                        order_data = row.tolist()
                                        so_number = create_sales_order(order_data, delivery_date)
                                        if so_number:
                                            st.session_state.created_sos[order_number] = so_number
                                            st.success(f"✅ Created SO: {so_number}")
                                            st.rerun()
                                        else:
                                            st.error("❌ Failed to create Sales Order")
                            st.markdown('</div>', unsafe_allow_html=True)
            
            # Add subtle separator between rows
            if idx < len(st.session_state.orders_data) - 1:
                st.markdown('<hr style="margin: 0.5rem 0; border: none; border-top: 1px solid #e0e0e0;">', unsafe_allow_html=True)
    
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
        4. **Adjust delivery dates** as needed (all dates are editable except "Delivered" orders)
        5. **Select 'Create SO'** from blue action dropdown and click Execute
        6. **Modified delivery dates** will be used when creating the Sales Order
        """)

if __name__ == "__main__":
    main()

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
import traceback
import math

# Import SS-FV Calculator
from ssfv_calculator import SmartNumberCalculator

# Page setup
st.set_page_config(
    page_title="Swagelok Orders Manager", 
    page_icon="📦",
    layout="wide"
)

# Custom CSS for better styling
st.markdown("""
<style>
.success-action {
    background-color: #e8f5e8 !important;
    border: 2px solid #4caf50 !important;
    border-radius: 8px !important;
    padding: 8px !important;
    text-align: center !important;
    font-weight: bold !important;
    color: #2e7d32 !important;
}
.modal-container {
    border: 3px solid #4CAF50;
    border-radius: 10px;
    padding: 20px;
    background-color: #f0f8f0;
    margin: 10px 0;
}
</style>
""", unsafe_allow_html=True)

# Your API configurations
try:
    API_TOKEN = st.secrets["FULCRUM_API_TOKEN"]
    BASE_URL = "https://api.fulcrumpro.us/api"
except KeyError:
    st.error("❌ FULCRUM_API_TOKEN not found in secrets. Please configure your API token.")
    st.stop()

# ====== ENHANCED SESSION STATE MANAGEMENT ======
def initialize_session_state():
    """Initialize all session state variables with safe defaults"""
    
    # Core application state
    if 'orders_data' not in st.session_state:
        st.session_state.orders_data = None
    
    if 'created_sos' not in st.session_state:
        st.session_state.created_sos = {}
    
    if 'updated_delivery_dates' not in st.session_state:
        st.session_state.updated_delivery_dates = {}
    
    if 'current_user' not in st.session_state:
        st.session_state.current_user = None
    
    if 'processing_order' not in st.session_state:
        st.session_state.processing_order = None
    
    # UI state
    if 'ui_state' not in st.session_state:
        st.session_state.ui_state = {
            'selected_action': 'Choose Action...',
            'show_success': False,
            'current_page': 'main',
            'active_row': None
        }
    
    # Calculator state
    if 'price_cache' not in st.session_state:
        st.session_state.price_cache = {}
    
    if 'ssfv_results' not in st.session_state:
        st.session_state.ssfv_results = {}
    
    # API state
    if 'api_operations' not in st.session_state:
        st.session_state.api_operations = {
            'in_progress': set(),
            'completed': [],
            'failed': []
        }
    
    # Modal state
    if 'show_modal' not in st.session_state:
        st.session_state.show_modal = False
    
    if 'modal_data' not in st.session_state:
        st.session_state.modal_data = None

def protect_session_state():
    """Enhanced session state protection with validation"""
    
    # Validate critical session state structure
    required_keys = ['created_sos', 'updated_delivery_dates', 'orders_data', 'current_user']
    
    for key in required_keys:
        if key not in st.session_state:
            initialize_session_state()
            break
    
    # Validate nested structures
    if not isinstance(st.session_state.created_sos, dict):
        st.session_state.created_sos = {}
    
    if not isinstance(st.session_state.updated_delivery_dates, dict):
        st.session_state.updated_delivery_dates = {}
    
    # Ensure UI state is properly structured
    if 'ui_state' not in st.session_state or not isinstance(st.session_state.ui_state, dict):
        st.session_state.ui_state = {
            'selected_action': 'Choose Action...',
            'show_success': False,
            'current_page': 'main',
            'active_row': None
        }

# Initialize session state at startup
initialize_session_state()

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
        
        # Always ensure admin user exists
        admin_password_hash = self.hash_password("swagelok2025")
        cursor.execute('''
            INSERT OR REPLACE INTO users (username, first_name, last_name, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', ("mstkhan", "Muhammad", "Khan", admin_password_hash, True))
        
        conn.commit()
        conn.close()
        
        # Update repo backup after ensuring admin exists
        self.create_repo_backup()
    
    def load_from_repo_backup(self):
        """Load user data from repo backup file"""
        try:
            with open(self.repo_backup_path, 'r') as f:
                backup_data = json.load(f)
            
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
            
            if cursor.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone():
                conn.close()
                return False, "Username already exists"
            
            password_hash = self.hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, first_name, last_name, password_hash, is_admin)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, first_name, last_name, password_hash, is_admin))
            
            conn.commit()
            conn.close()
            
            self.create_repo_backup()
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
                cursor.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
                    (username,)
                )
                conn.commit()
                conn.close()
                
                self.create_repo_backup()
                
                return True, {
                    'username': user[0],
                    'first_name': user[1],
                    'last_name': user[2],
                    'is_admin': bool(user[4])
                }
            else:
                conn.close()
                return False, "Invalid credentials"
            
        except Exception as e:
            return False, f"Database error: {str(e)}"
    
    def change_password(self, username, old_password, new_password):
        """Change user password"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            user = cursor.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
            
            if not user or not self.verify_password(old_password, user[0]):
                conn.close()
                return False, "Current password is incorrect"
            
            new_password_hash = self.hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (new_password_hash, username)
            )
            
            conn.commit()
            conn.close()
            
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

# Business Logic Functions
def business_days_from(start_date, days):
    """Calculate business days from start date (excluding weekends)"""
    current_date = start_date
    days_added = 0
    
    while days_added < days:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:  # Monday=0, Sunday=6
            days_added += 1
    
    return current_date

def parse_date_safely(date_str):
    """Safely parse date string in various formats"""
    if not date_str or date_str in ["TBD", "Delivered", ""]:
        return None
    
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
            calculated_date = business_days_from(datetime.now(), 18)
            return calculated_date.strftime("%Y-%m-%d")
    elif hasattr(date_input, 'strftime'):
        return date_input.strftime("%Y-%m-%d")
    else:
        calculated_date = business_days_from(datetime.now(), 18)
        return calculated_date.strftime("%Y-%m-%d")
    
# ====== ENHANCED API CLIENT WITH SS-FV INTEGRATION ======
class OptimizedFulcrumAPI:
    """Enhanced API client with BOM, operations, and SS-FV calculator integration"""
    
    def __init__(self, token):
        self.api_token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.base_url = BASE_URL
        self.item_cache = {}
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
    def _make_request(self, method, url, payload=None, max_retries=3):
        """Generic method with retry logic and better error handling"""
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = self.session.get(url, timeout=30)
                elif method.upper() == "POST":
                    response = self.session.post(url, json=payload, timeout=30)
                elif method.upper() == "DELETE":
                    response = self.session.delete(url, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                if response.status_code in [200, 201, 204]:
                    return response.json() if response.content else {}
                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                else:
                    st.error(f"API Error {response.status_code}: {response.text}")
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
        """Check if item exists and return its ID with caching"""
        if part_number in self.item_cache:
            return self.item_cache[part_number]
            
        url = f"{self.base_url}/items/list/v2"
        payload = {
            "numbers": [{"query": part_number, "mode": "equal"}],
            "latestRevision": True
        }
        
        response_data = self._make_request("POST", url, payload)
        if response_data and isinstance(response_data, list) and len(response_data) > 0:
            item_id = response_data[0]["id"]
            self.item_cache[part_number] = item_id
            return item_id
        
        self.item_cache[part_number] = None
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
            self.item_cache[part_number] = item_id
            return item_id
        
        return None

    def get_item_id(self, item_name):
        """Get item ID by name with caching"""
        if item_name in self.item_cache:
            return self.item_cache[item_name]
            
        url = f"{self.base_url}/items/list/v2"
        payload = {
            "numbers": [{"query": item_name, "mode": "equal"}],
            "latestRevision": True
        }
        
        response_data = self._make_request("POST", url, payload)
        if response_data and isinstance(response_data, list) and len(response_data) > 0:
            if "id" in response_data[0]:
                item_id = response_data[0]["id"]
                self.item_cache[item_name] = item_id
                return item_id
        
        self.item_cache[item_name] = None
        return None

    def list_input_items(self, item_id, bom_name=""):
        """List all input items (BOM items) for an item"""
        url = f"{self.base_url}/items/{item_id}/routing/input-items/list"
        payload = {"query": bom_name}
        
        response_data = self._make_request("POST", url, payload)
        if response_data and isinstance(response_data, list):
            return response_data
        return []

    def list_operations(self, item_id, bom_name=""):
        """List all operations for an item"""
        url = f"{self.base_url}/items/{item_id}/routing/operations/list"
        payload = {"query": bom_name}
        
        response_data = self._make_request("POST", url, payload)
        if response_data and isinstance(response_data, list):
            return response_data
        return []

    def delete_input_item(self, item_id, input_item_id):
        """Delete a single input item (BOM item)"""
        url = f"{self.base_url}/items/{item_id}/routing/input-items/{input_item_id}"
        response_data = self._make_request("DELETE", url)
        return response_data is not None

    def delete_operation(self, item_id, operation_id):
        """Delete a single operation"""
        url = f"{self.base_url}/items/{item_id}/routing/operations/{operation_id}"
        response_data = self._make_request("DELETE", url)
        return response_data is not None

    def clear_item_routing(self, item_id, first_bom_name=""):
        """Clear all routing (BOM and operations) for an item"""
        input_items = self.list_input_items(item_id, first_bom_name)
        deleted_inputs = 0
        for item in input_items:
            if "id" in item:
                if self.delete_input_item(item_id, item["id"]):
                    deleted_inputs += 1
        
        operations = self.list_operations(item_id, first_bom_name)
        deleted_operations = 0
        for op in operations:
            if "id" in op:
                if self.delete_operation(item_id, op["id"]):
                    deleted_operations += 1
        
        return True

    def add_bom_item(self, item_id, bom_item):
        """Add BOM item to item routing"""
        url = f"{self.base_url}/items/{item_id}/routing/input-items"
        payload = {
            "itemId": bom_item["id"],
            "valueTypeUnits": bom_item["value"],
            "valueType": "requires"
        }
        
        response_data = self._make_request("POST", url, payload)
        return response_data is not None

    def add_operation(self, item_id, operation):
        """Add operation to item routing"""
        url = f"{self.base_url}/items/{item_id}/routing/operations"
        payload = {
            "systemOperationId": operation["systemOperationId"],
            "order": operation["order"],
            "operation": {
                "laborTime": {
                    "time": int(operation["laborTime"]),
                    "option": "secondsPerUnit"
                }
            }
        }
        
        response_data = self._make_request("POST", url, payload)
        if response_data and "id" in response_data:
            return response_data["id"]
        return None

    def upload_attachment(self, sales_order_id, uploaded_file, order_number):
        """Upload file attachment to sales order"""
        try:
            attachment_url = f"{self.base_url}/attachments"
            headers = {"Authorization": f"Bearer {self.api_token}"}
            
            attachment_payload = {
                "Detail.Owner.Type": "salesOrder",
                "Detail.Owner.Id": sales_order_id,
                "Detail.Description": f"Order Attachment for {order_number}",
                "Detail.AttachmentType": "standard",
                "Detail.IsNoteAttachment": "false"
            }
            
            files = {"File": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            
            response = requests.post(
                attachment_url, 
                headers=headers, 
                data=attachment_payload, 
                files=files, 
                timeout=30
            )
            
            return response.status_code in [200, 201]
                
        except Exception as e:
            return False
    
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
            return response_data is not None

        except (ValueError, TypeError) as e:
            return False

# Initialize API client
@st.cache_resource
def get_api_client():
    return OptimizedFulcrumAPI(API_TOKEN)

# ====== SS-FV CALCULATOR INTEGRATION ======
@st.cache_resource
def get_ssfv_calculator():
    """Initialize and cache the SS-FV calculator"""
    return SmartNumberCalculator()

@st.cache_data(ttl=600)  # Cache for 10 minutes
def process_ssfv_part_number(part_number):
    """
    Process SS-FV part number using the calculator
    Returns: (success, result_dict, error_message)
    """
    try:
        calculator = get_ssfv_calculator()
        result = calculator.process_part_number(part_number)
        
        if "error" in result:
            return False, None, result["error"]
        
        return True, result, "SS-FV part processed successfully"
        
    except Exception as e:
        return False, None, f"Error processing SS-FV part: {str(e)}"

def convert_ssfv_to_fulcrum_format(ssfv_result):
    """
    Convert SS-FV calculator results to Fulcrum API format
    Returns: (bom_items, operations, description, price)
    """
    try:
        bom_items = []
        for bom_item in ssfv_result.get("bom_items", []):
            bom_items.append({
                "name": bom_item["part_number"],
                "value": bom_item["value"],
                "unit": bom_item["unit"]
            })
        
        operations = []
        for prod_item in ssfv_result.get("production_items", []):
            operations.append({
                "systemOperationId": prod_item["operation_number"],
                "order": len(operations) + 1,
                "laborTime": prod_item["time_minutes"] * 60
            })
        
        description = ssfv_result.get("description", f"SS-FV Part {ssfv_result.get('part_number', '')}")
        price = ssfv_result.get("unit_price", 0.0)
        
        return bom_items, operations, description, price
        
    except Exception as e:
        st.error(f"Error converting SS-FV results: {str(e)}")
        return [], [], "", 0.0

def process_part_number_with_ssfv(part_number, manual_price=None):
    """
    Enhanced part processing with SS-FV calculator integration
    Returns: (item_id, price, success, error_message, bom_items, operations)
    """
    api_client = get_api_client()
    
    try:
        existing_item_id = api_client.check_item_exists(part_number)
        
        if part_number.startswith("SS-FV"):
            success, ssfv_result, error_msg = process_ssfv_part_number(part_number)
            
            if not success:
                if manual_price is not None:
                    if existing_item_id:
                        item_id = existing_item_id
                    else:
                        item_id = api_client.create_item(part_number, f"Swagelok Part {part_number}")
                    
                    return item_id, manual_price, True, "SS-FV processing failed, using manual price", [], []
                else:
                    return None, None, False, f"SS-FV processing failed: {error_msg}. Please enter manual price.", [], []
            
            bom_items, operations, description, calculated_price = convert_ssfv_to_fulcrum_format(ssfv_result)
            
            final_price = manual_price if manual_price is not None else calculated_price
            
            if final_price is None or final_price <= 0:
                return None, None, False, "Valid price is required. Please enter manual price.", bom_items, operations
        
        else:
            if manual_price is None:
                return None, None, False, "This is not an SS-FV part. Manual price is required.", [], []
            
            final_price = manual_price
            description = f"Swagelok Part {part_number}"
            bom_items = []
            operations = []
        
        if existing_item_id:
            item_id = existing_item_id
            
            if bom_items or operations:
                first_bom_name = bom_items[0]["name"] if bom_items else ""
                api_client.clear_item_routing(existing_item_id, first_bom_name)
        else:
            item_id = api_client.create_item(part_number, description)
            if not item_id:
                return None, final_price, False, f"Failed to create item for {part_number}", bom_items, operations
        
        if bom_items:
            for bom_item in bom_items:
                bom_id = api_client.get_item_id(bom_item["name"])
                if bom_id:
                    bom_item["id"] = bom_id
                    api_client.add_bom_item(item_id, bom_item)
        
        if operations:
            for operation in operations:
                api_client.add_operation(item_id, operation)
        
        success_msg = "SS-FV part processing successful" if part_number.startswith("SS-FV") else "Part processing successful"
        return item_id, final_price, True, success_msg, bom_items, operations
        
    except Exception as e:
        return None, None, False, f"Error processing part {part_number}: {str(e)}", [], []

def create_sales_order_workflow(order_row, delivery_date=None, manual_price=None, skip_processing=False, uploaded_file=None):
    """
    Complete SO creation workflow with proper error handling
    """
    api_client = get_api_client()
    
    progress_placeholder = st.empty()
    
    try:
        order_number = str(order_row[0]).strip()
        order_date = str(order_row[1]).strip()
        part_number = str(order_row[2]).strip()
        quantity = int(order_row[3])
        
        with progress_placeholder.container():
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step 1: Check if item exists
            status_text.text("🔍 Checking if item exists...")
            progress_bar.progress(0.2)
            
            if skip_processing:
                if manual_price is None:
                    return None, "Manual price is required when skipping processing"
                
                existing_item_id = api_client.check_item_exists(part_number)
                if existing_item_id:
                    item_id = existing_item_id
                else:
                    item_id = api_client.create_item(part_number, f"Swagelok Part {part_number}")
                
                price = manual_price
            else:
                # Full SS-FV processing
                status_text.text("📊 Processing part details...")
                progress_bar.progress(0.3)
                
                item_id, price, success, error_msg, bom_items, operations = process_part_number_with_ssfv(part_number, manual_price)
                if not success:
                    return None, error_msg
                if price is None:
                    return None, "Price is required to create Sales Order"
            
            # Step 2: Create Sales Order
            status_text.text("📋 Creating sales order...")
            progress_bar.progress(0.5)
            
            if delivery_date:
                due_date_final = format_delivery_date(delivery_date)
            else:
                order_dt = parse_date_safely(order_date)
                if order_dt:
                    calculated_date = business_days_from(order_dt, 18)
                    due_date_final = calculated_date.strftime("%Y-%m-%d")
                else:
                    calculated_date = business_days_from(datetime.now(), 18)
                    due_date_final = calculated_date.strftime("%Y-%m-%d")
            
            order_dt = parse_date_safely(order_date)
            if order_dt:
                order_date_final = order_dt.strftime("%Y-%m-%d")
            else:
                order_date_final = datetime.now().strftime("%Y-%m-%d")
            
            payload = {
                "customerId": "654241f9c77f04d8d76410c4",
                "customerPoNumber": order_number,
                "orderedDate": order_date_final,
                "contact": {"firstName": "Kristian", "lastName": "Barnett"},
                "dueDate": due_date_final,
            }
            
            sales_order_id = api_client.create_sales_order(payload)
            
            if not sales_order_id:
                return None, "Failed to create Sales Order"
            
            # Get SO number
            so_details = api_client.get_sales_order_details(sales_order_id)
            sales_order_number = so_details.get("number") if so_details else "Unknown"
            
            # Step 3: Add line item
            status_text.text("➕ Adding line items...")
            progress_bar.progress(0.7)
            
            if item_id and price is not None:
                success = api_client.add_part_line_item(sales_order_id, item_id, quantity, price)
                
                if not success:
                    return None, "Failed to add line item to Sales Order"
            
            # Step 4: Handle attachment if provided
            if uploaded_file:
                status_text.text("📎 Uploading attachment...")
                progress_bar.progress(0.9)
                
                upload_success = api_client.upload_attachment(sales_order_id, uploaded_file, order_number)
                if not upload_success:
                    st.warning("⚠️ SO created but attachment upload failed")
            
            # Complete
            status_text.text("✅ Sales order created successfully!")
            progress_bar.progress(1.0)
            
            # Update session state
            if 'created_sos' not in st.session_state:
                st.session_state.created_sos = {}
            st.session_state.created_sos[order_number] = sales_order_number
            
            # Store success for display
            st.session_state.so_creation_success = {
                'so_number': sales_order_number,
                'order_number': order_number,
                'timestamp': datetime.now()
            }
            
            return sales_order_number, "Success"
                
    except Exception as e:
        return None, f"Error creating sales order: {str(e)}"
    finally:
        time.sleep(1)
        progress_placeholder.empty()
        
# ====== ENHANCED SO CREATION MODAL ======
@st.dialog("Create Sales Order", width="large")
def show_so_creation_modal():
    """Modern modal implementation for SO creation"""
    
    if not st.session_state.modal_data:
        st.error("No order data available")
        return
    
    order_data = st.session_state.modal_data
    order_number = str(order_data['row'][0])
    order_date = str(order_data['row'][1])
    part_number = str(order_data['row'][2])
    quantity = int(order_data['row'][3])
    delivery_date = order_data.get('delivery_date')
    
    st.markdown(f"### 📋 Order: **{order_number}**")
    st.markdown(f"### 🔧 Part: **{part_number}**")
    st.markdown(f"### 📊 Quantity: **{quantity}**")
    
    # Check if it's an SS-FV part
    is_ssfv_part = part_number.startswith("SS-FV")
    
    # Process SS-FV part once
    if is_ssfv_part and f"ssfv_{part_number}" not in st.session_state.ssfv_results:
        with st.spinner("Processing SS-FV part..."):
            success, ssfv_result, error_msg = process_ssfv_part_number(part_number)
            
            if success:
                price = ssfv_result.get("unit_price", 0.0)
                st.session_state.ssfv_results[f"ssfv_{part_number}"] = {
                    'success': True,
                    'price': price or 0.0,
                    'result': ssfv_result
                }
            else:
                st.session_state.ssfv_results[f"ssfv_{part_number}"] = {
                    'success': False,
                    'error': error_msg
                }
    
    # Price section
    st.markdown("#### 💰 Price Configuration")
    
    # Get calculated or default price
    default_price = 0.0
    if is_ssfv_part and f"ssfv_{part_number}" in st.session_state.ssfv_results:
        ssfv_data = st.session_state.ssfv_results[f"ssfv_{part_number}"]
        if ssfv_data.get('success'):
            default_price = ssfv_data.get('price', 0.0) or 0.0
            if default_price > 0:
                st.success(f"✅ SS-FV calculated price: ${default_price:.2f}")
            else:
                st.warning("⚠️ SS-FV calculation returned $0.00 - please enter price manually")
        else:
            st.error(f"❌ SS-FV failed: {ssfv_data.get('error', 'Unknown error')}")
            st.warning("⚠️ Please enter price manually")
    elif is_ssfv_part:
        st.info("🔄 Processing SS-FV part...")
    else:
        st.info("💰 Manual price required for non-SS-FV parts")
    
    # Price input
    final_price = st.number_input(
        "Enter/Edit Price ($)", 
        min_value=0.0, 
        value=float(default_price), 
        step=0.01,
        key="modal_price_input",
        help="Price is editable - modify as needed"
    )
    
    # Show BOM/Operations info if available
    if is_ssfv_part and f"ssfv_{part_number}" in st.session_state.ssfv_results:
        ssfv_data = st.session_state.ssfv_results[f"ssfv_{part_number}"]
        if ssfv_data.get('success'):
            result = ssfv_data['result']
            bom_count = len(result.get("bom_items", []))
            ops_count = len(result.get("production_items", []))
            if bom_count > 0 or ops_count > 0:
                st.info(f"📋 Will add {bom_count} BOM items and {ops_count} operations")
    
    # Attachment upload
    st.markdown("#### 📎 Attachment (Optional)")
    uploaded_file = st.file_uploader(
        "Choose a file", 
        type=['pdf', 'docx', 'jpg', 'png', 'xlsx'],
        key="modal_file_upload"
    )
    
    st.markdown("---")
    
    # Action buttons
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Create Sales Order", key="modal_create_so", disabled=(final_price <= 0), type="primary"):
            skip_processing = not is_ssfv_part or f"ssfv_{part_number}" not in st.session_state.ssfv_results or not st.session_state.ssfv_results[f"ssfv_{part_number}"].get('success')
            
            with st.spinner("Creating Sales Order..."):
                so_number, result_msg = create_sales_order_workflow(
                    order_data['row'], 
                    delivery_date, 
                    final_price, 
                    skip_processing=skip_processing,
                    uploaded_file=uploaded_file
                )
                
                if so_number:
                    st.success(f"🎉 Successfully Created SO: **{so_number}**")
                    st.balloons()
                    
                    # Clear modal data
                    st.session_state.modal_data = None
                    st.session_state.show_modal = False
                    
                    # Wait briefly then close
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"❌ Failed to create SO: {result_msg}")
    
    with col2:
        if st.button("❌ Cancel", key="modal_cancel", type="secondary"):
            st.session_state.modal_data = None
            st.session_state.show_modal = False
            st.rerun()

# ====== SWAGELOK ORDER FETCHING ======
def fetch_swagelok_orders(selected_status):
    """Fetch orders from Swagelok portal with improved parsing"""
    
    driver = None
    
    try:
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox') 
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--single-process')
        
        try:
            options.binary_location = '/usr/bin/chromium'
        except:
            pass
        
        try:
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e1:
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            except Exception as e2:
                return [], []
        
        driver.set_page_load_timeout(20)
        wait = WebDriverWait(driver, 15)
        
        driver.get("https://supplierportal.swagelok.com//login.aspx")
        
        username_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtUsername")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_txtPassword")))
        go_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_btnGo2")))

        username_field.send_keys("mstkhan")
        password_field.send_keys("Concept350!")
        go_button.click()

        try:
            accept_terms_button = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_lnkAcceptTerms")))
            accept_terms_button.click()
        except:
            pass

        order_application_link = wait.until(EC.presence_of_element_located((By.ID, "ctl00_MainContentPlaceHolder_rptPortalApplications_ctl01_lnkPortalApplication")))
        order_application_link.click()
        driver.switch_to.window(driver.window_handles[-1])

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
                
                if selected_status == "Order - History":
                    if len(details) >= 8:
                        order_number = details[0]
                        
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
                            
                            delivery_date = "Delivered"
                            if date_index + 4 < len(details) and "/" in str(details[date_index + 4]):
                                delivery_date = details[date_index + 4]
                            
                            data.append([order_number, order_date, part_number, quantity, sales_order, delivery_date])
                
                elif selected_status == "Order - New, Requires Supplier Action":
                    if len(details) >= 11:
                        order_number = details[0]
                        
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
                            
                            if not delivery_date or "/" not in delivery_date:
                                order_dt = parse_date_safely(order_date)
                                if order_dt:
                                    delivery_dt = business_days_from(order_dt, 18)
                                    delivery_date = delivery_dt.strftime("%m/%d/%Y")
                                else:
                                    delivery_date = "TBD"
                            
                            data.append([order_number, order_date, part_number, quantity, delivery_date])
                
                elif selected_status == "Order - Modification, Requires Supplier Action":
                    if len(details) >= 11:
                        order_number = details[0]
                        
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

# ====== USER MANAGEMENT FUNCTIONS ======
def create_user_form():
    """Form to create new users (admin only)"""
    st.subheader("👤 Create New User")
    
    if st.button("← Back to Home", key="back_from_create_user"):
        st.session_state.show_create_user = False
        st.rerun()
    
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
    
    if st.button("← Back to Home", key="back_from_change_password"):
        st.session_state.show_change_password = False
        st.rerun()
    
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
    
    if st.button("← Back to Home", key="back_from_view_users"):
        st.session_state.show_view_users = False
        st.rerun()
    
    user_db = get_user_db()
    
    st.markdown("### 📁 Repo Backup Status")
    
    try:
        if os.path.exists("users_backup.json"):
            st.success("✅ Backup file exists in repo")
        else:
            st.warning("❌ No backup file found")
    except:
        st.error("❌ Backup check failed")
    
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

# ====== AUTHENTICATION ======
def login_form():
    """Centered login form with logo and proper title"""
    
    col1, col2, col3 = st.columns([1.5, 2, 1.5])
    
    with col2:
        try:
            st.image("concept_insulon_logo.png", width=200)
        except:
            st.markdown("**[CONCEPT INSULON LOGO]**")
        
        st.markdown("<h2 style='text-align: center; margin-top: 1rem; font-size: 1.5rem; white-space: nowrap;'>FV - Open Orders Management System</h2>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center; margin-bottom: 2rem;'>🔐 Login</h3>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username", value="mstkhan")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
            with col_btn2:
                submitted = st.form_submit_button("Login", use_container_width=True)
            
            if submitted:
                user_db = get_user_db()
                success, result = user_db.authenticate_user(username, password)
                
                if success:
                    # Preserve critical data during login
                    keys_to_preserve = ['orders_data', 'created_sos', 'updated_delivery_dates']
                    preserved_data = {}
                    
                    for key in keys_to_preserve:
                        if key in st.session_state:
                            preserved_data[key] = st.session_state[key]
                    
                    keys_to_clear = ['show_create_user', 'show_change_password', 'show_view_users', 'processing_order', 'ssfv_results']
                    for key in keys_to_clear:
                        if key in st.session_state:
                            del st.session_state[key]
                    
                    st.session_state.current_user = result
                    for key, value in preserved_data.items():
                        st.session_state[key] = value
                    
                    st.rerun()
                else:
                    st.error(f"❌ {result}")
                    st.info("💡 **Default Admin Credentials:**\nUsername: `mstkhan`\nPassword: `swagelok2025`")

def logout():
    """Logout function"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ====== MAIN DISPLAY FUNCTIONS ======
def display_so_creation_success():
    """Display success state with proper cleanup"""
    
    if 'so_creation_success' in st.session_state:
        success_data = st.session_state.so_creation_success
        so_number = success_data['so_number']
        order_number = success_data.get('order_number', '')
        
        st.success(f"🎉 **Sales Order Created Successfully!**\n\nSO Number: **{so_number}**")
        st.toast(f'✅ SO {so_number} created!', icon='🎉')
        
        if st.button("Continue", key="clear_success"):
            del st.session_state.so_creation_success
            st.rerun()

def display_main_content():
    """Display the main content (orders table or welcome screen)"""
    
    protect_session_state()
    
    if st.session_state.orders_data is not None:
        col_header1, col_header2 = st.columns([1, 6])
        
        with col_header1:
            if st.button("← Back to Welcome", type="secondary"):
                st.session_state.orders_data = None
                st.session_state.created_sos = {}
                st.session_state.processing_order = None
                if hasattr(st.session_state, 'ssfv_results'):
                    del st.session_state.ssfv_results
                st.rerun()
        
        with col_header2:
            st.header("Open Orders")
        
        st.write(f"**Found {len(st.session_state.orders_data)} orders:**")
        st.info("💡 **Tip:** All delivery dates are editable - adjust them as needed before creating Sales Orders!")
        
        columns = st.session_state.orders_data.columns.tolist()
        
        if len(columns) == 6:  # Has Sales Order column
            header_cols = st.columns([0.5, 1.2, 1.2, 2, 1, 1.2, 1.2, 1.5])
            headers = ["No.", "Order #", "Date", "Part Number", "Qty", "Sales Order", "Delivery", "Action"]
        else:  # No Sales Order column
            header_cols = st.columns([0.5, 1.2, 1.2, 2, 1, 1.5, 1.5])
            headers = ["No.", "Order #", "Date", "Part Number", "Qty", "Delivery", "Action"]
        
        for i, header in enumerate(headers):
            with header_cols[i]:
                st.markdown(f"**{header}**")
        
        st.markdown("---")
        
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
                    part_num = str(row.iloc[2])
                    if part_num.startswith("SS-FV"):
                        st.write(f"🧮 {part_num}")
                    else:
                        st.write(f"{part_num}")
                with col5:
                    st.write(f"{row.iloc[3]}")  # Quantity
                with col6:
                    st.write(f"{row.iloc[4]}")  # Sales Order
                with col7:
                    delivery_value = str(row.iloc[5])  # Delivery Date
                    
                    if delivery_value == "Delivered":
                        st.write("Delivered")
                        delivery_date = None
                    else:
                        parsed_date = parse_date_safely(delivery_value)
                        if parsed_date:
                            default_delivery = parsed_date.date()
                        else:
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
                        so_number = st.session_state.created_sos[order_number]
                        st.markdown(f'<div class="success-action">✅ SO: {so_number}</div>', unsafe_allow_html=True)
                    else:
                        action = st.selectbox(
                            "Action",
                            ["Select Action", "Create SO"],
                            key=f"action_{idx}",
                            label_visibility="collapsed"
                        )
                        if action == "Create SO":
                            if st.button(f"Execute", key=f"execute_{idx}"):
                                st.session_state.modal_data = {
                                    'row': row.tolist(),
                                    'delivery_date': delivery_date,
                                    'order_number': order_number
                                }
                                st.session_state.show_modal = True
                                st.rerun()
            
            else:  # No Sales Order column (5 columns)
                col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 1.2, 1.2, 2, 1, 1.5, 1.5])
                
                with col1:
                    st.write(f"{idx + 1}")
                with col2:
                    st.write(f"{row.iloc[0]}")  # Order Number
                with col3:
                    st.write(f"{row.iloc[1]}")  # Order Date
                with col4:
                    part_num = str(row.iloc[2])
                    if part_num.startswith("SS-FV"):
                        st.write(f"🧮 {part_num}")
                    else:
                        st.write(f"{part_num}")
                with col5:
                    st.write(f"{row.iloc[3]}")  # Quantity
                with col6:
                    delivery_value = str(row.iloc[4])
                    
                    parsed_date = parse_date_safely(delivery_value)
                    if parsed_date:
                        default_delivery = parsed_date.date()
                    else:
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
                        so_number = st.session_state.created_sos[order_number]
                        st.markdown(f'<div class="success-action">✅ SO: {so_number}</div>', unsafe_allow_html=True)
                    else:
                        action = st.selectbox(
                            "Action",
                            ["Select Action", "Create SO"],
                            key=f"action_{idx}",
                            label_visibility="collapsed"
                        )
                        if action == "Create SO":
                            if st.button(f"Execute", key=f"execute_{idx}"):
                                st.session_state.modal_data = {
                                    'row': row.tolist(),
                                    'delivery_date': delivery_date,
                                    'order_number': order_number
                                }
                                st.session_state.show_modal = True
                                st.rerun()
            
            if idx < len(st.session_state.orders_data) - 1:
                st.markdown('<hr style="margin: 0.5rem 0; border: none; border-top: 1px solid #e0e0e0;">', unsafe_allow_html=True)
    
    else:
        # Welcome screen
        st.markdown(f"# WELCOME **{st.session_state.current_user['first_name'].upper()}**")
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            api_status = "✅ Connected" if API_TOKEN else "❌ Missing API Token"
            st.info(f"🔌 **API Status:** {api_status}")
        
        with col2:
            st.info(f"🧮 **SS-FV Calculator:** ✅ Ready")
        
        st.info("👆 Use the sidebar to fetch orders and get started!")
        st.markdown("""
        ### How to use:
        1. **Select Order Status** from the dropdown in the sidebar
        2. **Click 'Fetch Orders'** to retrieve orders from Swagelok portal
        3. **Review orders** in the main table (🧮 icon indicates SS-FV parts)
        4. **Adjust delivery dates** as needed (all dates are editable except "Delivered" orders)
        5. **Select 'Create SO'** from action dropdown and click Execute
        6. **SS-FV parts** will be automatically calculated (pricing, BOM, operations)
        7. **Non SS-FV parts** will require manual pricing input
        8. **Upload attachments** (optional) during SO creation
        9. **Click "← Back to Welcome"** to return to this screen when finished
        """)

# ====== MAIN APPLICATION ======
def main():
    """Main application entry point"""
    
    # Check if user is logged in
    if not st.session_state.current_user:
        login_form()
        return
    
    current_user = st.session_state.current_user
    
    st.title("Swagelok Open Orders")
    
    # Show user management forms if requested
    if st.session_state.get('show_create_user', False):
        create_user_form()
        return
    
    if st.session_state.get('show_view_users', False):
        view_users_form()
        return
    
    if st.session_state.get('show_change_password', False):
        change_password_form()
        return
    
    # Show SO creation modal if requested
    if st.session_state.get('show_modal', False) and st.session_state.get('modal_data'):
        show_so_creation_modal()
    
    # Sidebar for controls and account
    with st.sidebar:
        st.header("Controls")
        
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
        
        if st.session_state.get('last_order_status') != order_status:
            st.session_state.orders_data = None
            st.session_state.created_sos = {}
            st.session_state.last_order_status = order_status
        
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
        
        st.markdown("---")
        
        # Account section
        st.header("Account")
        
        st.markdown(f"**Logged in as:** {current_user['first_name']} {current_user['last_name']}")
        st.markdown(f"**Role:** {'Administrator' if current_user['is_admin'] else 'User'}")
        
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
    
    # Main content area
    display_so_creation_success()
    display_main_content()

if __name__ == "__main__":
    main()             

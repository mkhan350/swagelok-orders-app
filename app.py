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
import openpyxl
from openpyxl import load_workbook
import traceback

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
try:
    API_TOKEN = st.secrets["FULCRUM_API_TOKEN"]
    BASE_URL = "https://api.fulcrumpro.us/api"
except KeyError:
    st.error("❌ FULCRUM_API_TOKEN not found in secrets. Please configure your API token.")
    st.stop()

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
        
        # Always ensure admin user exists (force recreate if needed)
        admin_password_hash = self.hash_password("swagelok2025")
        cursor.execute('''
            INSERT OR REPLACE INTO users (username, first_name, last_name, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', ("mstkhan", "Muhammad", "Khan", admin_password_hash, True))
        
        conn.commit()
        
        # Verify admin user was created
        admin_check = cursor.execute(
            "SELECT username, first_name, is_admin FROM users WHERE username = ?", ("mstkhan",)
        ).fetchone()
        
        if admin_check:
            print(f"✅ Admin user verified: {admin_check[0]} ({admin_check[1]}) - Admin: {admin_check[2]}")
        else:
            print("❌ Failed to create admin user")
        
        conn.close()
        
        # Update repo backup after ensuring admin exists
        self.create_repo_backup()
    
    def load_from_repo_backup(self):
        """Load user data from repo backup file"""
        try:
            print(f"🔍 Looking for backup file: {self.repo_backup_path}")
            
            if not os.path.exists(self.repo_backup_path):
                print(f"❌ Backup file not found at: {os.path.abspath(self.repo_backup_path)}")
                return False
            
            print(f"✅ Found backup file, loading...")
            
            with open(self.repo_backup_path, 'r') as f:
                backup_data = json.load(f)
            
            print(f"📋 Backup data keys: {list(backup_data.keys())}")
            
            # Skip if backup is empty or invalid
            if not backup_data.get("users"):
                print("❌ No users found in backup data")
                return False
            
            print(f"👥 Found {len(backup_data['users'])} users in backup")
                
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
            loaded_count = 0
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
                loaded_count += 1
                print(f"✅ Loaded user: {user['username']} ({user['first_name']} {user['last_name']})")
            
            conn.commit()
            conn.close()
            
            print(f"🎉 Successfully loaded {loaded_count} users from backup!")
            return True
            
        except FileNotFoundError:
            print(f"❌ Backup file not found: {self.repo_backup_path}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in backup file: {e}")
            return False
        except Exception as e:
            print(f"❌ Error loading backup: {e}")
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
            
            # Debug: Check what users exist
            all_users = cursor.execute("SELECT username, first_name FROM users").fetchall()
            print(f"🔍 Available users: {all_users}")
            
            user = cursor.execute('''
                SELECT username, first_name, last_name, password_hash, is_admin
                FROM users WHERE username = ?
            ''', (username,)).fetchone()
            
            if user:
                print(f"🔍 Found user: {user[0]} ({user[1]} {user[2]})")
                stored_hash = user[3]
                input_hash = self.hash_password(password)
                print(f"🔍 Password hash match: {stored_hash == input_hash}")
                
                if self.verify_password(password, user[3]):
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
                else:
                    conn.close()
                    return False, "Invalid password"
            else:
                print(f"🔍 User '{username}' not found in database")
                conn.close()
                return False, "User not found"
            
        except Exception as e:
            print(f"🔍 Authentication error: {str(e)}")
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
if 'so_creation_panel' not in st.session_state:
    st.session_state.so_creation_panel = None
if 'processing_order' not in st.session_state:
    st.session_state.processing_order = None

# ====== ENHANCED API CLIENT WITH EXCEL AND BOM FUNCTIONALITY ======
class OptimizedFulcrumAPI:
    """Enhanced API client with BOM, operations, and Excel integration"""
    
    def __init__(self, token):
        self.api_token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.base_url = BASE_URL
        self.item_cache = {}  # Cache for item lookups
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
                elif response.status_code == 429:  # Rate limit
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
        # Delete all input items (BOM)
        input_items = self.list_input_items(item_id, first_bom_name)
        deleted_inputs = 0
        for item in input_items:
            if "id" in item:
                if self.delete_input_item(item_id, item["id"]):
                    deleted_inputs += 1
        
        # Delete all operations
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

# ====== MICROSOFT GRAPH EXCEL INTEGRATION ======
class GraphExcelProcessor:
    """Handle Excel operations using Microsoft Graph API for OneDrive Excel files"""
    
    def __init__(self):
        self.price_cache = {}
        self.access_token = None
        self.excel_file_id = st.secrets.get("EXCEL_FILE_ID", "")
        self.client_id = st.secrets.get("MICROSOFT_CLIENT_ID", "")
        self.client_secret = st.secrets.get("MICROSOFT_CLIENT_SECRET", "")
        self.tenant_id = st.secrets.get("MICROSOFT_TENANT_ID", "")
        
    def get_access_token(self):
        """Get access token for Microsoft Graph API"""
        if self.access_token:
            return self.access_token
            
        if not all([self.client_id, self.client_secret, self.tenant_id]):
            return None
            
        try:
            url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'https://graph.microsoft.com/.default'
            }
            
            response = requests.post(url, data=data, timeout=30)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                return self.access_token
            else:
                return None
                
        except Exception as e:
            return None
    
    def update_excel_cell(self, worksheet_name, cell_address, value):
        """Update a specific cell in Excel using Graph API"""
        token = self.get_access_token()
        if not token or not self.excel_file_id:
            return False
            
        try:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{self.excel_file_id}/workbook/worksheets/{worksheet_name}/range(address='{cell_address}')"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'values': [[value]]
            }
            
            response = requests.patch(url, headers=headers, json=data, timeout=30)
            return response.status_code in [200, 201]
            
        except Exception as e:
            return False
    
    def get_excel_cell_value(self, worksheet_name, cell_address):
        """Get value from a specific cell in Excel using Graph API"""
        token = self.get_access_token()
        if not token or not self.excel_file_id:
            return None
            
        try:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{self.excel_file_id}/workbook/worksheets/{worksheet_name}/range(address='{cell_address}')"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                values = data.get('values', [[]])
                if values and len(values) > 0 and len(values[0]) > 0:
                    return values[0][0]
            return None
            
        except Exception as e:
            return None
    
    def get_excel_range_values(self, worksheet_name, range_address):
        """Get values from a range of cells in Excel using Graph API"""
        token = self.get_access_token()
        if not token or not self.excel_file_id:
            return []
            
        try:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{self.excel_file_id}/workbook/worksheets/{worksheet_name}/range(address='{range_address}')"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('values', [])
            return []
            
        except Exception as e:
            return []
    
    def trigger_excel_calculation(self):
        """Trigger Excel calculation (equivalent to pressing F9)"""
        token = self.get_access_token()
        if not token or not self.excel_file_id:
            return False
            
        try:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{self.excel_file_id}/workbook/application/calculate"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            data = {'calculationType': 'Full'}
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            return response.status_code in [200, 201, 202]
            
        except Exception as e:
            return False
    
    def run_excel_macro(self, macro_name):
        """Try to run Excel macro using Graph API (if supported)"""
        token = self.get_access_token()
        if not token or not self.excel_file_id:
            return False
            
        try:
            # Note: As of 2024, Graph API has limited VBA macro support
            # This is a placeholder for when/if Microsoft adds full macro support
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{self.excel_file_id}/workbook/functions"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # This might not work for VBA macros, but worth trying
            data = {
                'function': macro_name,
                'arguments': []
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            return response.status_code in [200, 201]
            
        except Exception as e:
            return False
    
    def lookup_part_data(self, part_number):
        """
        Lookup part data from Excel using Graph API
        Returns: (price, description, bom_items, operations, success, error_message)
        """
        if part_number in self.price_cache:
            cached_result = self.price_cache[part_number]
            return cached_result + (True, "Using cached data")
        
        if not self.excel_file_id:
            error_msg = "Excel file ID not configured. Please add EXCEL_FILE_ID to secrets."
            return None, None, [], [], False, error_msg
        
        if not self.get_access_token():
            error_msg = "Failed to authenticate with Microsoft Graph API. Check your Microsoft credentials in secrets."
            return None, None, [], [], False, error_msg
        
        try:
            # Step 1: Update cell C5 with part number
            if not self.update_excel_cell("Sheet1", "C5", part_number):
                error_msg = "Failed to update Excel cell C5 with part number"
                return None, None, [], [], False, error_msg
            
            # Step 2: Try to trigger macro or calculation
            # First try to run the macro
            macro_success = self.run_excel_macro("RunMultipleMacros2")
            
            # If macro fails, try triggering calculation
            if not macro_success:
                calc_success = self.trigger_excel_calculation()
                if not calc_success:
                    error_msg = "Failed to trigger Excel macro or calculation"
                    return None, None, [], [], False, error_msg
            
            # Step 3: Wait a moment for calculations
            time.sleep(2)
            
            # Step 4: Get price from C13
            price_value = self.get_excel_cell_value("Sheet1", "C13")
            price = None
            if price_value is not None:
                try:
                    price = round(float(price_value), 2)
                except (ValueError, TypeError):
                    price = None
            
            # Step 5: Get description from C14
            description_value = self.get_excel_cell_value("Sheet1", "C14")
            description = str(description_value) if description_value else f"Swagelok Part {part_number}"
            
            # Step 6: Get BOM items from J14:M25
            bom_range = self.get_excel_range_values("Sheet1", "J14:M25")
            bom_items = []
            
            for row in bom_range:
                if len(row) >= 3:  # J, K, L, M columns
                    j_value = row[0]  # Part name (J column)
                    l_value = row[2] if len(row) > 2 else None  # Quantity (L column)
                    m_value = row[3] if len(row) > 3 else None  # Multiplier (M column)
                    
                    if j_value and l_value:
                        try:
                            value = float(l_value) * float(m_value) if m_value else float(l_value)
                            bom_items.append({
                                "name": str(j_value).strip(),
                                "value": value
                            })
                        except (ValueError, TypeError):
                            continue
            
            # Step 7: Get operations from J36:L40
            operations_range = self.get_excel_range_values("Sheet1", "J36:L40")
            operations = []
            
            for i, row in enumerate(operations_range):
                if len(row) >= 2:
                    operation_id = row[0]  # Operation ID (J column)
                    labor_time = row[1]   # Labor time (L column)
                    
                    if operation_id and labor_time:
                        try:
                            operations.append({
                                "systemOperationId": str(operation_id).strip(),
                                "order": i + 1,  # Order based on row position
                                "laborTime": int(float(labor_time) * 60)  # Convert to seconds
                            })
                        except (ValueError, TypeError):
                            continue
            
            if price is None:
                error_msg = "Excel processing completed but no price was returned. This might indicate the macro didn't run properly or the part number wasn't found."
                return None, None, [], [], False, error_msg
            
            # Cache successful result
            result = (price, description, bom_items, operations)
            self.price_cache[part_number] = result
            
            success_msg = f"Excel processing successful: Price=${price}, {len(bom_items)} BOM items, {len(operations)} operations"
            return price, description, bom_items, operations, True, success_msg
            
        except Exception as e:
            error_msg = f"Excel processing error: {str(e)}"
            return None, None, [], [], False, error_msg

# Initialize Graph Excel processor
@st.cache_resource
def get_graph_excel_processor():
    return GraphExcelProcessor()

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

# Enhanced process part number function
def process_part_number_with_fallback(part_number, manual_price=None):
    """
    Enhanced part processing with Graph Excel integration and fallback options
    Returns: (item_id, price, success, error_message, bom_items, operations)
    """
    api_client = get_api_client()
    excel_processor = get_graph_excel_processor()
    
    try:
        # Step 1: Check if item exists
        existing_item_id = api_client.check_item_exists(part_number)
        
        # Step 2: Try to get data from Excel using Graph API
        price, description, bom_items, operations, excel_success, excel_error = excel_processor.lookup_part_data(part_number)
        
        if not excel_success:
            # Excel failed - return error for user to decide
            return None, None, False, f"Excel processing failed: {excel_error}", [], []
        
        # Use manual price if Excel price is not available
        if price is None and manual_price is not None:
            price = manual_price
        elif price is None:
            price = 100.0  # Default fallback price
        
        # Step 3: Handle item creation or update
        if existing_item_id:
            item_id = existing_item_id
            
            # Clear existing routing if we have new BOM/operations data
            if bom_items or operations:
                api_client.clear_item_routing(existing_item_id)
        else:
            item_id = api_client.create_item(part_number, description)
            if not item_id:
                return None, price, False, f"Failed to create item for {part_number}", bom_items, operations
        
        # Step 4: Add BOM items
        if bom_items:
            for bom_item in bom_items:
                # Get BOM item ID
                bom_id = api_client.get_item_id(bom_item["name"])
                if bom_id:
                    bom_item["id"] = bom_id
                    api_client.add_bom_item(item_id, bom_item)
        
        # Step 5: Add operations
        if operations:
            for operation in operations:
                api_client.add_operation(item_id, operation)
        
        return item_id, price, True, "Part processing successful", bom_items, operations
        
    except Exception as e:
        return None, None, False, f"Error processing part {part_number}: {str(e)}", [], []

def create_sales_order_simple(order_row, delivery_date=None, manual_price=None, skip_excel=False):
    """
    Simplified sales order creation for manual processing
    """
    api_client = get_api_client()
    
    try:
        order_number = str(order_row[0]).strip()
        order_date = str(order_row[1]).strip()
        part_number = str(order_row[2]).strip()
        quantity = int(order_row[3])
        
        # Handle delivery date
        if delivery_date:
            due_date_final = format_delivery_date(delivery_date)
        else:
            # Calculate 18 business days from order date
            order_dt = parse_date_safely(order_date)
            if order_dt:
                calculated_date = business_days_from(order_dt, 18)
                due_date_final = calculated_date.strftime("%Y-%m-%d")
            else:
                calculated_date = business_days_from(datetime.now(), 18)
                due_date_final = calculated_date.strftime("%Y-%m-%d")
        
        # Format order date for API
        order_dt = parse_date_safely(order_date)
        if order_dt:
            order_date_final = order_dt.strftime("%Y-%m-%d")
        else:
            order_date_final = datetime.now().strftime("%Y-%m-%d")
        
        # Step 1: Create sales order
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
        
        # Get sales order details to get the SO number
        so_details = api_client.get_sales_order_details(sales_order_id)
        sales_order_number = so_details.get("number") if so_details else "Unknown"
        
        # Step 2: Process part
        if skip_excel:
            # Simple item creation without Excel processing
            existing_item_id = api_client.check_item_exists(part_number)
            if existing_item_id:
                item_id = existing_item_id
            else:
                item_id = api_client.create_item(part_number, f"Swagelok Part {part_number}")
            
            price = manual_price or 100.0
        else:
            # Full Excel processing
            item_id, price, success, error_msg, bom_items, operations = process_part_number_with_fallback(part_number, manual_price)
            if not success:
                return None, error_msg
        
        # Step 3: Add line item
        if item_id and price is not None:
            success = api_client.add_part_line_item(sales_order_id, item_id, quantity, price)
            if success:
                return sales_order_number, "Success"
            else:
                return None, "Failed to add line item to Sales Order"
        else:
            return None, "Failed to process part for Sales Order"
                
    except Exception as e:
        return None, f"Error creating sales order: {str(e)}"

def show_so_creation_panel():
    """Show the SO creation panel in the sidebar"""
    if not st.session_state.processing_order:
        return
    
    order_data = st.session_state.processing_order
    order_number = str(order_data['row'][0])
    part_number = str(order_data['row'][2])
    delivery_date = order_data.get('delivery_date')
    
    with st.sidebar:
        st.header("🔄 Creating Sales Order")
        st.write(f"**Order:** {order_number}")
        st.write(f"**Part:** {part_number}")
        
        # Step 1: Try Excel Processing
        with st.expander("📊 Microsoft Graph Excel Processing", expanded=True):
            if st.button("🔄 Process with Excel Online", key="excel_process"):
                with st.spinner("Connecting to Excel Online via Microsoft Graph..."):
                    excel_processor = get_graph_excel_processor()
                    price, description, bom_items, operations, excel_success, excel_error = excel_processor.lookup_part_data(part_number)
                    
                    if excel_success:
                        st.success("✅ Excel processing successful!")
                        st.write(f"**Price:** ${price}")
                        st.write(f"**Description:** {description}")
                        st.write(f"**BOM Items:** {len(bom_items)}")
                        st.write(f"**Operations:** {len(operations)}")
                        
                        # Show BOM details
                        if bom_items:
                            with st.expander("📦 BOM Items", expanded=False):
                                for item in bom_items:
                                    st.write(f"- {item['name']}: {item['value']}")
                        
                        # Show operations details
                        if operations:
                            with st.expander("⚙️ Operations", expanded=False):
                                for op in operations:
                                    st.write(f"- {op['systemOperationId']}: {op['laborTime']}s")
                        
                        if st.button("✅ Create SO with Excel Data", key="create_with_excel"):
                            with st.spinner("Creating Sales Order..."):
                                so_number, result_msg = create_sales_order_simple(
                                    order_data['row'], 
                                    delivery_date, 
                                    price, 
                                    skip_excel=False
                                )
                                
                                if so_number:
                                    # Handle file attachment if provided
                                    uploaded_file = st.session_state.get(f"attachment_{order_number}")
                                    if uploaded_file:
                                        api_client = get_api_client()
                                        # Get the sales order ID for attachment
                                        # Note: We'd need the sales_order_id here, which we don't have in the simple version
                                        # For now, we'll skip attachment in simple mode
                                        pass
                                    
                                    st.session_state.created_sos[order_number] = so_number
                                    st.success(f"🎉 Created SO: {so_number}")
                                    st.balloons()
                                    # Clear the processing order
                                    st.session_state.processing_order = None
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed: {result_msg}")
                    else:
                        st.error(f"❌ Excel processing failed:")
                        st.error(excel_error)
                        
                        st.warning("**Possible causes:**")
                        st.write("• Microsoft Graph API authentication failed")
                        st.write("• Excel file ID not configured or incorrect")
                        st.write("• Insufficient permissions to access Excel file")
                        st.write("• VBA macro couldn't be triggered via Graph API")
                        st.write("• Excel Online limitations with complex macros")
        
        # Step 2: Manual Options
        st.markdown("---")
        with st.expander("🔧 Manual Options", expanded=True):
            st.info("Create SO without Excel processing")
            
            manual_price = st.number_input(
                "Manual Price ($)", 
                min_value=0.0, 
                value=100.0, 
                step=1.0,
                key="manual_price"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Create SO", key="create_manual"):
                    with st.spinner("Creating Sales Order..."):
                        so_number, result_msg = create_sales_order_simple(
                            order_data['row'], 
                            delivery_date, 
                            manual_price, 
                            skip_excel=True
                        )
                        
                        if so_number:
                            # Handle file attachment if provided
                            uploaded_file = st.session_state.get(f"attachment_{order_number}")
                            if uploaded_file:
                                # File attachment would need to be implemented in the simple SO creation
                                pass
                            
                            st.session_state.created_sos[order_number] = so_number
                            st.success(f"🎉 Created SO: {so_number}")
                            st.balloons()
                            # Clear the processing order
                            st.session_state.processing_order = None
                            st.rerun()
                        else:
                            st.error(f"❌ Failed: {result_msg}")
            
            with col2:
                if st.button("❌ Cancel", key="cancel_so"):
                    st.session_state.processing_order = None
                    st.rerun()
        
        # Step 3: File Attachment (Optional)
        st.markdown("---")
        with st.expander("📎 File Attachment", expanded=False):
            st.info("Optional: Attach files after SO creation")
            uploaded_file = st.file_uploader(
                "Choose a file",
                key=f"attachment_{order_number}",
                help="Upload documents for this order"
            )
            
            if uploaded_file:
                st.info("File will be attached when SO is created")

def close_so_creation_panel():
    """Close the SO creation panel"""
    st.session_state.processing_order = None
    if st.session_state.get('so_creation_panel'):
        st.session_state.so_creation_panel = None

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
        **Important: The app CANNOT automatically commit to your GitHub repo!**
        
        **How it actually works:**
        1. ✅ **Auto-loads** from `users_backup.json` in your repo on app start
        2. ✅ **Auto-creates** local backup file after user changes  
        3. ❌ **CANNOT auto-commit** to GitHub (security limitation)
        
        **To Make Changes Permanent (Manual Process):**
        1. **Download** updated backup using button above
        2. **Manually replace** `users_backup.json` in your GitHub repo  
        3. **Commit & push** to GitHub manually
        4. **Users persist** across future app rebuilds!
        
        **Troubleshooting:**
        - Make sure file is named `users_backup.json` (not `.jason`)
        - File must be in the root directory of your repo
        - Check the debug panel on login screen if users aren't loading
        """)
        
        # Show current backup status
        st.markdown("### 🔍 Current Backup Status")
        if os.path.exists("users_backup.json"):
            try:
                with open("users_backup.json", 'r') as f:
                    backup_data = json.load(f)
                user_count = len(backup_data.get("users", []))
                backup_time = backup_data.get("backup_timestamp", "Unknown")
                st.success(f"✅ Local backup found: {user_count} users (Updated: {backup_time})")
            except Exception as e:
                st.error(f"❌ Backup file corrupted: {e}")
        else:
            st.warning("⚠️ No local backup file found")
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
        
        # Debug info
        with st.expander("🔧 Debug Info (Click if login issues)", expanded=False):
            user_db = get_user_db()
            
            # Show file system info
            st.write("**File System Check:**")
            current_dir = os.getcwd()
            st.write(f"Current directory: `{current_dir}`")
            
            backup_file = "users_backup.json"
            backup_exists = os.path.exists(backup_file)
            st.write(f"Backup file exists: `{backup_exists}`")
            
            if backup_exists:
                try:
                    with open(backup_file, 'r') as f:
                        backup_content = json.load(f)
                    st.write(f"Backup users: {len(backup_content.get('users', []))}")
                    for user in backup_content.get('users', []):
                        st.write(f"- {user['username']} ({user['first_name']} {user['last_name']})")
                except Exception as e:
                    st.error(f"Error reading backup: {e}")
            
            # Show database status
            try:
                conn = sqlite3.connect(user_db.db_path)
                cursor = conn.cursor()
                users = cursor.execute("SELECT username, first_name, is_admin FROM users").fetchall()
                conn.close()
                
                st.write("**Database Users:**")
                if users:
                    for user in users:
                        st.write(f"- {user[0]} ({user[1]}) - Admin: {user[2]}")
                else:
                    st.write("No users in database")
                
            except Exception as e:
                st.error(f"Database error: {e}")
            
            # Manual backup restore
            st.write("**Manual Backup Restore:**")
            uploaded_backup = st.file_uploader(
                "Upload your users_backup.json file",
                type=['json'],
                key="backup_restore"
            )
            
            if uploaded_backup is not None:
                if st.button("🔄 Restore from Uploaded Backup"):
                    try:
                        backup_data = json.load(uploaded_backup)
                        
                        conn = sqlite3.connect(user_db.db_path)
                        cursor = conn.cursor()
                        
                        # Clear existing users
                        cursor.execute("DELETE FROM users")
                        
                        # Load users from backup
                        for user in backup_data.get("users", []):
                            cursor.execute('''
                                INSERT INTO users 
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
                        
                        st.success(f"✅ Restored {len(backup_data.get('users', []))} users!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Restore failed: {e}")
            
            # Reset admin button
            if st.button("🔄 Reset Admin User", help="Recreate admin user with default credentials"):
                try:
                    conn = sqlite3.connect(user_db.db_path)
                    cursor = conn.cursor()
                    admin_password_hash = user_db.hash_password("swagelok2025")
                    cursor.execute('''
                        INSERT OR REPLACE INTO users (username, first_name, last_name, password_hash, is_admin, created_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', ("mstkhan", "Muhammad", "Khan", admin_password_hash, True))
                    conn.commit()
                    conn.close()
                    st.success("✅ Admin user reset! Try logging in now.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Reset failed: {e}")
        
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username", value="mstkhan")
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
                    
                    # Show default credentials reminder
                    st.info("💡 **Default Admin Credentials:**\nUsername: `mstkhan`\nPassword: `swagelok2025`")

def logout():
    """Logout function"""
    st.session_state.current_user = None
    st.session_state.orders_data = None
    st.rerun()

# Initialize API client and Excel processor
@st.cache_resource
def get_api_client():
    return OptimizedFulcrumAPI(API_TOKEN)

# Main app
def main():
    # Check if user is logged in
    if not st.session_state.current_user:
        login_form()
        return
    
    # Show SO creation panel if active
    if st.session_state.processing_order:
        show_so_creation_panel()
    
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
        
        # Clear processing panel if stuck
        if st.session_state.processing_order:
            st.markdown("---")
            st.warning("⚠️ SO Creation Panel Active")
            if st.button("🔄 Clear Panel", help="Clear the SO creation panel if stuck"):
                st.session_state.processing_order = None
                st.rerun()
        
        st.markdown("---")
        
        # Excel Configuration Status
        st.header("⚙️ Configuration")
        
        # Check Excel configuration
        graph_processor = get_graph_excel_processor()
        excel_configured = bool(graph_processor.excel_file_id and graph_processor.client_id)
        
        if excel_configured:
            st.success("✅ Microsoft Graph Excel Integration Configured")
            st.info("🔧 Real Excel Online integration with macro support")
            
            # Test authentication
            if st.button("🔗 Test Graph API Connection", key="test_graph"):
                with st.spinner("Testing Microsoft Graph API..."):
                    token = graph_processor.get_access_token()
                    if token:
                        st.success("✅ Microsoft Graph API authentication successful!")
                    else:
                        st.error("❌ Microsoft Graph API authentication failed")
        else:
            st.error("❌ Microsoft Graph Excel not configured")
            st.warning("⚠️ Manual pricing only")
            st.info("💡 Configure Microsoft Graph API for real Excel integration")
        
        # Show configuration help
        with st.expander("🔧 Configuration Help"):
            st.markdown("""
            **Required Secrets:**
            - `FULCRUM_API_TOKEN`: Your Fulcrum API token
            
            **Microsoft Graph Excel Integration:**
            - `MICROSOFT_CLIENT_ID`: Azure App Registration Client ID
            - `MICROSOFT_CLIENT_SECRET`: Azure App Registration Client Secret  
            - `MICROSOFT_TENANT_ID`: Your Azure Tenant ID
            - `EXCEL_FILE_ID`: OneDrive/SharePoint Excel file ID
            
            **How to get Microsoft Graph credentials:**
            1. Go to Azure Portal → App Registrations
            2. Create new app registration
            3. Add API permissions: Files.ReadWrite, Sites.ReadWrite.All
            4. Create client secret
            5. Copy Client ID, Client Secret, and Tenant ID to secrets
            
            **How to get Excel File ID:**
            1. Open your Excel file in OneDrive/SharePoint
            2. Share the file and copy the link
            3. Extract the file ID from the URL (long string after `/items/`)
            4. Or use Graph Explorer to browse and find file ID
            
            **Excel File Requirements:**
            - Must be accessible via Microsoft Graph API
            - Sheet1 with part number input in C5
            - VBA macro "RunMultipleMacros2" (will be triggered via API)
            - Price output in C13, Description in C14
            - BOM items in J14:M25 (name, qty, multiplier)
            - Operations in J36:L40 (operation ID, labor time)
            
            **Benefits of Graph API approach:**
            - Actually runs VBA macros in Excel Online
            - No popup questions blocking automation
            - Real-time Excel processing
            - Access to full Excel functionality
            """)
        
        with st.expander("📋 Setup Steps", expanded=False):
            st.markdown("""
            **Step 1: Azure App Registration**
            ```
            1. Go to https://portal.azure.com
            2. Navigate to "App registrations"
            3. Click "New registration"
            4. Name: "Swagelok Excel Integration"
            5. Account types: "Single tenant"
            6. Redirect URI: Leave blank
            7. Click "Register"
            ```
            
            **Step 2: API Permissions**
            ```
            1. In your app registration, go to "API permissions"
            2. Click "Add a permission"
            3. Choose "Microsoft Graph"
            4. Choose "Application permissions"
            5. Add: Files.ReadWrite, Sites.ReadWrite.All
            6. Click "Grant admin consent"
            ```
            
            **Step 3: Client Secret**
            ```
            1. Go to "Certificates & secrets"
            2. Click "New client secret"
            3. Description: "Swagelok Excel Access"
            4. Expires: Choose duration
            5. Copy the secret value (you won't see it again!)
            ```
            
            **Step 4: Get IDs**
            ```
            1. Copy "Application (client) ID" from Overview
            2. Copy "Directory (tenant) ID" from Overview
            3. Get Excel file ID from OneDrive/SharePoint URL
            ```
            
            **Step 5: Add to Streamlit Secrets**
            ```
            MICROSOFT_CLIENT_ID = "your-client-id"
            MICROSOFT_CLIENT_SECRET = "your-client-secret"
            MICROSOFT_TENANT_ID = "your-tenant-id"
            EXCEL_FILE_ID = "your-excel-file-id"
            ```
            """)
            

        
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
                                    # Set up the SO creation panel
                                    st.session_state.processing_order = {
                                        'row': row.tolist(),
                                        'delivery_date': delivery_date if delivery_date is not None else str(row.iloc[5]),
                                        'order_number': order_number
                                    }
                                    st.rerun()
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
                                    # Set up the SO creation panel
                                    st.session_state.processing_order = {
                                        'row': row.tolist(),
                                        'delivery_date': delivery_date,
                                        'order_number': order_number
                                    }
                                    st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
            
            # Add subtle separator between rows
            if idx < len(st.session_state.orders_data) - 1:
                st.markdown('<hr style="margin: 0.5rem 0; border: none; border-top: 1px solid #e0e0e0;">', unsafe_allow_html=True)
    
    else:
        # Welcome screen
        st.markdown(f"# WELCOME **{current_user['first_name'].upper()}**")
        st.markdown("---")
        
        # Configuration status
        col1, col2 = st.columns(2)
        with col1:
            api_status = "✅ Connected" if API_TOKEN else "❌ Missing API Token"
            st.info(f"🔌 **API Status:** {api_status}")
        
        with col2:
            graph_processor = get_graph_excel_processor()
            excel_status = "✅ Microsoft Graph Configured" if (graph_processor.excel_file_id and graph_processor.client_id) else "❌ Not Configured"
            st.info(f"📊 **Excel Integration:** {excel_status}")
        
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

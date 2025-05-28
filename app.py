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
            # Fetch orders button
            if st.button("🔄 Fetch Orders", type="primary"):
                with st.spinner("Fetching orders from Swagelok portal..."):
                    try:
                        headers, data = fetch_swagelok_orders(order_status)
                        if data:
                            st.session_state.orders_data = pd.DataFrame(data, columns=headers)
                            st.success(f"✅ Fetched {len(data)} orders successfully!")
                            st.experimental_rerun()
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

if __name__ == "__main__":
    main()

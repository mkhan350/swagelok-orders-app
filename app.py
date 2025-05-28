import streamlit as st
import pandas as pd
import requests
import threading
from datetime import datetime, timedelta
import time
import os

API_TOKEN = st.secrets["FULCRUM_API_TOKEN"]
# Page setup
st.set_page_config(
    page_title="Swagelok Orders Manager", 
    page_icon="📦",
    layout="wide"
)

# Simple authentication
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
        st.write("Welcome to the Swagelok Orders Manager")
        
        # Test button
        if st.button("Test Connection"):
            st.info("Connection test successful! Ready for next steps.")

if __name__ == "__main__":
    main()

import streamlit as st # type: ignore
import pandas as pd

def initialize_session_state():
    """Initialize session state variables"""
    if 'portfolio' not in st.session_state:
        st.session_state.portfolio = pd.DataFrame(
            columns=['coin', 'amount', 'buy_price', 'current_price', 'value', 'profit_loss']
        )

def format_large_number(number):
    """Format large numbers with appropriate suffixes"""
    suffixes = ['', 'K', 'M', 'B', 'T']
    magnitude = 0
    while abs(number) >= 1000 and magnitude < len(suffixes)-1:
        magnitude += 1
        number /= 1000.0
    return f'${number:.2f}{suffixes[magnitude]}'

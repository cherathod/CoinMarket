import streamlit as st # type: ignore
import pandas as pd
from pycoingecko import CoinGeckoAPI # type: ignore
import plotly.express as px # type: ignore

cg = CoinGeckoAPI()

def show_portfolio_tracker():
    st.subheader("Portfolio Tracker")
    
    # Initialize portfolio in session state if not exists
    if 'portfolio' not in st.session_state:
        st.session_state.portfolio = pd.DataFrame(
            columns=['coin', 'amount', 'buy_price', 'current_price', 'value', 'profit_loss']
        )
    
    # Add new position
    with st.expander("Add New Position"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            coin = st.selectbox(
                "Select Coin",
                options=[coin['id'] for coin in cg.get_coins_list()]
            )
        
        with col2:
            amount = st.number_input("Amount", min_value=0.0, value=0.0)
        
        with col3:
            buy_price = st.number_input("Buy Price (USD)", min_value=0.0, value=0.0)
        
        if st.button("Add Position"):
            try:
                current_price = cg.get_price(coin, vs_currencies='usd')[coin]['usd']
                value = amount * current_price
                profit_loss = (current_price - buy_price) * amount
                
                new_position = pd.DataFrame({
                    'coin': [coin],
                    'amount': [amount],
                    'buy_price': [buy_price],
                    'current_price': [current_price],
                    'value': [value],
                    'profit_loss': [profit_loss]
                })
                
                st.session_state.portfolio = pd.concat(
                    [st.session_state.portfolio, new_position],
                    ignore_index=True
                )
                st.success("Position added successfully!")
            
            except Exception as e:
                st.error(f"Error adding position: {str(e)}")
    
    # Display portfolio
    if not st.session_state.portfolio.empty:
        # Summary metrics
        total_value = st.session_state.portfolio['value'].sum()
        total_pl = st.session_state.portfolio['profit_loss'].sum()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Portfolio Value", f"${total_value:,.2f}")
        with col2:
            st.metric("Total Profit/Loss", f"${total_pl:,.2f}")
        
        # Portfolio composition pie chart
        fig = px.pie(
            st.session_state.portfolio,
            values='value',
            names='coin',
            title='Portfolio Composition'
        )
        st.plotly_chart(fig)
        
        # Detailed portfolio table
        st.dataframe(
            st.session_state.portfolio.style.format({
                'amount': '{:.4f}',
                'buy_price': '${:.2f}',
                'current_price': '${:.2f}',
                'value': '${:.2f}',
                'profit_loss': '${:.2f}'
            })
        )
    else:
        st.info("Your portfolio is empty. Add some positions to get started!")

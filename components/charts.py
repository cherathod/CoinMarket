import streamlit as st # type: ignore
import plotly.graph_objects as go # type: ignore
from pycoingecko import CoinGeckoAPI # type: ignore
from datetime import datetime, timedelta

cg = CoinGeckoAPI()

@st.cache_data(ttl=300)
def get_historical_data(coin_id, days):
    try:
        data = cg.get_coin_market_chart_by_id(
            id=coin_id,
            vs_currency='usd',
            days=days
        )
        return data
    except Exception as e:
        st.error(f"Error fetching historical data: {str(e)}")
        return None

def show_price_chart():
    st.subheader("Price Chart")
    
    # Chart controls
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_coin = st.selectbox(
            "Select Cryptocurrency",
            options=[coin['id'] for coin in cg.get_coins_list()[:100]],
            index=0
        )
    
    with col2:
        timeframe = st.selectbox(
            "Timeframe",
            options=['24h', '7d', '30d', '90d', '1y'],
            index=1
        )
    
    # Convert timeframe to days
    days_map = {'24h': 1, '7d': 7, '30d': 30, '90d': 90, '1y': 365}
    days = days_map[timeframe]
    
    # Fetch and display data
    with st.spinner("Loading chart data..."):
        data = get_historical_data(selected_coin, days)
        
        if data:
            prices = data['prices']
            
            # Create candlestick chart
            fig = go.Figure()
            
            # Add price line
            fig.add_trace(
                go.Scatter(
                    x=[datetime.fromtimestamp(price[0]/1000) for price in prices],
                    y=[price[1] for price in prices],
                    mode='lines',
                    name='Price',
                    line=dict(color='#FF4B4B')
                )
            )
            
            # Update layout
            fig.update_layout(
                title=f"{selected_coin.upper()} Price Chart",
                xaxis_title="Date",
                yaxis_title="Price (USD)",
                template="plotly_dark",
                height=600
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Unable to load chart data. Please try again later.")

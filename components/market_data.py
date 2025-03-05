import streamlit as st # type: ignore
import pandas as pd
from pycoingecko import CoinGeckoAPI # type: ignore
from datetime import datetime, timedelta
import time

cg = CoinGeckoAPI()

@st.cache_data(ttl=300)
def get_market_data():
    try:
        return cg.get_coins_markets(
            vs_currency='usd',
            order='market_cap_desc',
            per_page=100,
            sparkline=False
        )
    except Exception as e:
        st.error(f"Error fetching market data: {str(e)}")
        return []

def show_market_overview():
    st.subheader("Market Overview")
    
    with st.spinner("Loading market data..."):
        market_data = get_market_data()
        
        if market_data:
            df = pd.DataFrame(market_data)
            
            # Market stats
            col1, col2, col3 = st.columns(3)
            
            with col1:
                total_market_cap = df['market_cap'].sum()
                st.metric("Total Market Cap", f"${total_market_cap:,.0f}")
            
            with col2:
                total_volume = df['total_volume'].sum()
                st.metric("24h Volume", f"${total_volume:,.0f}")
            
            with col3:
                btc_dominance = (df.iloc[0]['market_cap'] / total_market_cap) * 100
                st.metric("BTC Dominance", f"{btc_dominance:.2f}%")
            
            # Top cryptocurrencies table
            st.dataframe(
                df[['name', 'current_price', 'price_change_percentage_24h', 'market_cap']]
                .head(10)
                .style.format({
                    'current_price': '${:.2f}',
                    'price_change_percentage_24h': '{:.2f}%',
                    'market_cap': '${:,.0f}'
                })
            )

def show_top_movers():
    st.subheader("Top Movers (24h)")
    
    market_data = get_market_data()
    if market_data:
        df = pd.DataFrame(market_data)
        
        # Top gainers
        st.write("Top Gainers")
        gainers = df.nlargest(5, 'price_change_percentage_24h')[
            ['name', 'price_change_percentage_24h']
        ]
        for _, row in gainers.iterrows():
            st.metric(
                row['name'],
                f"{row['price_change_percentage_24h']:.2f}%",
                delta=f"{row['price_change_percentage_24h']:.2f}%"
            )
        
        # Top losers
        st.write("Top Losers")
        losers = df.nsmallest(5, 'price_change_percentage_24h')[
            ['name', 'price_change_percentage_24h']
        ]
        for _, row in losers.iterrows():
            st.metric(
                row['name'],
                f"{row['price_change_percentage_24h']:.2f}%",
                delta=f"{row['price_change_percentage_24h']:.2f}%"
            )

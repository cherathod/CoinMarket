import streamlit as st # type: ignore
import requests
from datetime import datetime
import time

@st.cache_data(ttl=900)
def fetch_crypto_news():
    # Using CryptoCompare News API
    url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
    try:
        response = requests.get(url)
        return response.json()['Data']
    except Exception as e:
        st.error(f"Error fetching news: {str(e)}")
        return []

def show_news_feed():
    st.subheader("Crypto News Feed")
    
    with st.spinner("Loading news..."):
        news_items = fetch_crypto_news()
        
        if news_items:
            for news in news_items[:10]:  # Display top 10 news items
                with st.container():
                    col1, col2 = st.columns([1, 4])
                    
                    with col1:
                        st.image(news['imageurl'], use_column_width=True)
                    
                    with col2:
                        st.markdown(f"### [{news['title']}]({news['url']})")
                        st.write(news['body'][:200] + "...")
                        st.caption(f"Source: {news['source']} | "
                                 f"Published: {datetime.fromtimestamp(news['published_on']).strftime('%Y-%m-%d %H:%M')}")
                    
                st.divider()
        else:
            st.warning("Unable to fetch news at the moment. Please try again later.")


# Cryptocurrency Market Analysis Dashboard

A comprehensive Streamlit application for cryptocurrency market analysis, portfolio tracking, and news aggregation.

## Overview

This application provides a unified platform for cryptocurrency enthusiasts and investors to:
- Monitor real-time market data and trends
- Track personal cryptocurrency portfolios
- Stay updated with the latest crypto news

## Features

### Market Overview
- Real-time cryptocurrency market data via CoinGecko API
- Key market metrics (total market cap, 24h volume, BTC dominance)
- Top 10 cryptocurrencies by market cap
- Top gainers and losers in the last 24 hours
- Interactive price charts with customizable timeframes

### Portfolio Tracker
- Add and monitor cryptocurrency positions
- Calculate current value and profit/loss
- Portfolio composition visualization
- Total portfolio value and profit/loss metrics

### News Feed
- Latest cryptocurrency news from trusted sources
- Article summaries and source attribution
- Direct links to full articles

## Technical Architecture

### Core Technologies
- **Python**: Primary programming language
- **Streamlit**: Web application framework
- **Pandas**: Data manipulation and analysis
- **Plotly**: Interactive data visualization
- **PyCoingecko**: CoinGecko API wrapper
- **Requests**: HTTP requests for news API

### Project Structure
```
├── assets/              # Static assets (CSS, images)
├── components/          # Modular components
│   ├── charts.py        # Price chart functionality
│   ├── market_data.py   # Market data display
│   ├── news.py          # News feed component
│   └── portfolio.py     # Portfolio tracking
├── utils/               # Utility functions
│   └── helpers.py       # Helper functions
└── app.py               # Main application entry point
```

### Data Sources
- **CoinGecko API**: Market data, historical prices
- **CryptoCompare API**: News articles

## Getting Started

### Prerequisites
- Python 3.11 or higher
- Required packages listed in requirements.txt

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python -m streamlit run app.py
```

### Usage
Navigate between different sections using the sidebar navigation. The application provides:
- Real-time market metrics and visualizations
- Portfolio management tools
- Latest news from the cryptocurrency world

## License
This project is open source and available under the MIT License.

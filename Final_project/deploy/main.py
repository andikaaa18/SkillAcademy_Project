from datetime import date
from datetime import timedelta
import joblib
import numpy as np
import pandas as pd
import path
from plotly import graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import sys
import torch
import yfinance as yf

# atur direktori induk
dir = path.Path('__file__').abspath()
sys.path.append(str(dir.parent.parent))


def selected_date(bias=15):
    ndays = 26 + bias
    
    end = st.date_input("Select start date for forecasting")
    start = end - timedelta(days=ndays)
    
    return start, end

@st.cache_data
def load_data(stock_code:str, start, end):
    data = yf.download(stock_code, start, end)
    return data

def data_preprocessing(stock_data:pd.DataFrame):
    
    def missingvalue_handling(data:pd.DataFrame):
        df = data.copy()
        df = df.interpolate()
        return df
    
    def make_features(data:pd.DataFrame, lag:list[int]=None):
        df = data.copy()
        
        # rolling window features
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['breakout_MA20'] = (df['Close'] > df['MA20']).apply(lambda x: 1 if x else 0)
        
        # lag features
        if lag: # will be executed if the variable has a value
            for i in sorted(lag, reverse=True):
                df[f"Open(t-{i})"] = df['Open'].shift(i)
                df[f"High(t-{i})"] = df['High'].shift(i)
                df[f"Low(t-{i})"] = df['Low'].shift(i)
                df[f"Close(t-{i})"] = df['Close'].shift(i)
                df[f"MA20(t-{i})"] = df['MA20'].shift(i)
                df[f"breakout_MA20(t-{i})"] = df['breakout_MA20'].shift(i)
        
        return df.dropna()
    
    def remove_unimportant_columns(data:pd.DataFrame):
        columns = ["Volume", "Adj Close", "MA20", "breakout_MA20", 
                   "Open", "Close", "High", "Low"]
        return data.drop(columns=columns)
    
    def features_scaling(data):
        scaler = joblib.load("scaler.pkl")
        scaling_data = scaler.transform(data)
        return scaling_data

    def reshape_data(data):
        features_unique = ['Open', 'High', 'Low', 'Close', 'MA20', 'breakout_MA20']
        reshape_df = data.reshape((-1, data.shape[1]//len(features_unique), len(features_unique)))

        return torch.tensor(reshape_df, dtype=torch.float)
    
    # dummy_row berguna agar data pada baris terakhir tidak hilang selama proses preprocessing
    dummy_row = pd.DataFrame(data=np.zeros((1, len(stock_data.columns))), columns=stock_data.columns)   
    data_prep = missingvalue_handling(pd.concat([stock_data, dummy_row]))
    data_prep = make_features(data_prep, lag=list(range(1,4)))
    data_prep = remove_unimportant_columns(data_prep).iloc[[-1]]
    data_prep = features_scaling(data_prep)
    data_prep = reshape_data(data_prep)
    
    return data_prep

def forecasting(features):
    # memuat model
    path = "./untr_stock_price_predictor.pt"
    model = torch.jit.load(path)
    
    # forecasting
    result = {}
    with torch.inference_mode():
        predict = model(features)

        result['High'] = {'t': predict[:,0].item(), 
                          't+1': predict[:,2].item(), 
                          't+2': predict[:,4].item(), 
                          't+3': predict[:,6].item(), 
                          't+4': predict[:,8].item()}
        
        result['Low'] = {'t': predict[:,1].item(), 
                         't+1': predict[:,3].item(), 
                         't+2': predict[:,5].item(), 
                         't+3': predict[:,7].item(), 
                         't+4': predict[:,9].item()}
    
    result = pd.DataFrame(data=result)
    result["Mid"] = (result['High'] + result['Low'])/2
    return result
      
def t2date(t:date, n:int):
    def is_weekend(date:date):
        if date.weekday() in [5, 6]: # 5: Sabtu; 6: Minggu
            return True
        else:
            return False
    
    tn = t
    stored = []
    for i in range(n):
        a = 0
        
        while is_weekend(tn+timedelta(days=a)):         
            a += 1
        
        stored.append(tn+timedelta(days=a))
        tn = stored[-1] + timedelta(days=1)
    
    return stored

def plot(stock_data:pd.DataFrame, forecast_data:pd.DataFrame):
    fig = make_subplots(rows=1, cols=2, column_widths=[20,10],
                        column_titles=["Historical Price", "Forecasting Result"],
                        x_title = "Date", y_title= "Price (Rp)",)

    fig.add_trace(go.Candlestick(x=stock_data.index,
                                open=stock_data['Open'],
                                high=stock_data['High'],
                                low=stock_data['Low'],
                                close=stock_data['Close'], showlegend=False
                                ),
                row=1,
                col=1
                )

    fig.add_trace(go.Scatter(x=forecast_data.index, y=forecast_data['High'], name="High price"),
                row=1,
                col=2
                )
    fig.add_trace(go.Scatter(x=forecast_data.index, y=forecast_data['Mid'], name="Mid price", line={'dash':'5px'}),
                row=1,
                col=2
                )
    fig.add_trace(go.Scatter(x=forecast_data.index, y=forecast_data['Low'], name="Low price"),
                row=1,
                col=2
                )

    fig.update_layout(xaxis_rangeslider_visible=False, legend_title_text='Forecasting')
    st.plotly_chart(fig)
    # fig.show()
    

st.title("Stock Forecast App")

stocks = ("UNTR.JK",)
selected_stock = st.selectbox("Select stock code for prediction", stocks)

# select range of data
start, end = selected_date(bias=30)

# load data
data_load_state = st.text("Loading data...")
stock_data = load_data(selected_stock, start, end)
data_load_state.text("Loading data... Done!")

# display historical data
st.subheader(f"{selected_stock} historical stock data")
n_data = st.slider(label='Number of data displayed:', value=5, min_value=1, max_value=stock_data.shape[0])
st.write(stock_data.tail(n_data))

if st.button('Forecast'):
    st.subheader(f"Forecasting result")
    # plot and display forecasting result
    features = data_preprocessing(stock_data)
    forecast_data = forecasting(features).set_index([pd.DatetimeIndex(t2date(end, 5))])
    plot(stock_data, forecast_data)
    st.write(forecast_data)

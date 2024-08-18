import os
import streamlit as st
import pyedflib
import pandas as pd
import plotly.express as px
import tempfile
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Open Source CPAP Data Visualizer",
    page_icon="images/icon.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main {
        background-color: #f0f8ff !important;
    }
    .css-18ni7ap.e8zbici2 {
        background-color: #e0f7fa !important;
        color: #00695c !important;
    }
    .stButton > button {
        background-color: #00796b !important;
        color: white !important;
        border-radius: 8px !important;
        font-size: 16px !important;
        margin: 5px 0px !important;
    }
    .stSidebar .css-1d391kg {
        background-color: #00796b !important;
        color: white !important;
    }
    .stSidebar .css-qrbaxs a {
        color: white !important;
    }
    h1, h2 {
        color: #004d40 !important;
    }
    .stMarkdown p {
        font-size: 18px !important;
        color: #004d40 !important;
    }
    .css-1d391kg {
        background-color: white !important;
        padding: 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
    }
    .css-1d391kg .stTable, .css-1d391kg .stDataFrame {
        background-color: white !important;
        border: 1px solid #ddd !important;
        padding: 8px !important;
    }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.image("images/logo.png", use_column_width=True)

data_source = st.sidebar.selectbox(
    "Select Data Source",
    ["Upload EDF File", "Load from AirSense 11 Memory Card"]
)

temp_file_path = None

if data_source == "Upload EDF File":
    uploaded_file = st.sidebar.file_uploader("Upload CPAP Data File", type=["edf"])
    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(uploaded_file.getbuffer())
            temp_file_path = temp_file.name

elif data_source == "Load from AirSense 11 Memory Card":
    memory_card_directory = st.sidebar.text_input("Enter the path to the memory card directory")
    if memory_card_directory:
        edf_files = [f for f in os.listdir(memory_card_directory) if f.endswith('.edf')]
        if edf_files:
            selected_edf = st.sidebar.selectbox("Select EDF File", edf_files)
            temp_file_path = os.path.join(memory_card_directory, selected_edf)
        else:
            st.warning("No EDF files found in the specified directory.")

if temp_file_path:
    def load_metadata(file_path):
        edf = pyedflib.EdfReader(file_path)
        header = edf.getHeader()
        signals = edf.getSignalLabels()
        edf.close()
        return header, signals
    
    header, signals = load_metadata(temp_file_path)
    
    machine_type = header.get("device", "Unknown Device")
    if machine_type == "Unknown Device":
        st.sidebar.write("Detected Machine: Unknown Device (Defaulting to ResMed AirSense 11)")
    else:
        st.sidebar.write(f"Detected Machine: {machine_type}")
    
    def get_default_signals(machine_type, signals):
        defaults = {
            "ResMed AirSense 11": {"AHI": "AHI", "MaskPress.95": "MaskPress.95"},
            "ResMed AirCurve 10": {"AHI": "AHI", "MaskPress.95": "Pressure"},
        }
        if machine_type in defaults:
            ahi_signal = defaults[machine_type]["AHI"] if defaults[machine_type]["AHI"] in signals else None
            pressure_signal = defaults[machine_type]["MaskPress.95"] if defaults[machine_type]["MaskPress.95"] in signals else None
        else:
            ahi_signal = "AHI" if "AHI" in signals else None
            pressure_signal = "MaskPress.95" if "MaskPress.95" in signals else None
        return ahi_signal, pressure_signal

    default_ahi_signal, default_pressure_signal = get_default_signals(machine_type, signals)
    ahi_signal = st.sidebar.selectbox("Select AHI Signal", signals, index=signals.index(default_ahi_signal) if default_ahi_signal else 0)
    pressure_signal = st.sidebar.selectbox("Select Pressure Signal (MaskPress.95)", signals, index=signals.index(default_pressure_signal) if default_pressure_signal else 0)
    
    if ahi_signal and pressure_signal:
        def load_data(file_path, signal_name):
            edf = pyedflib.EdfReader(file_path)
            signal_index = edf.getSignalLabels().index(signal_name)
            signal = edf.readSignal(signal_index)
            sample_rate = edf.getSampleFrequency(signal_index)
            start_time_str = edf.getStartdatetime().strftime("%Y-%m-%d %H:%M:%S")
            num_samples = edf.getNSamples()[signal_index]
            time_axis = [datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=i/sample_rate) for i in range(num_samples)]
            edf.close()
            return pd.DataFrame({'Time': time_axis, signal_name: signal})
        
        df_ahi = load_data(temp_file_path, ahi_signal)
        df_pressure = load_data(temp_file_path, pressure_signal)
        
        df = pd.merge(df_ahi, df_pressure, on='Time')
        df.set_index('Time', inplace=True)
        
        daily_data = df.resample('D').mean()
        daily_data['Recommended Pressure'] = daily_data[pressure_signal].resample('W-SUN').transform('mean').round(1)
        
        fig_ahi = px.line(daily_data.tail(7), x=daily_data.tail(7).index, y=ahi_signal, title="Recorded AHI (Last 7 Days)")
        fig_ahi.update_xaxes(tickformat="%b %d", title_text="Day")
        fig_ahi.update_yaxes(title_text="Recorded AHI")
        fig_ahi.add_hline(y=5, line_dash="dash", annotation_text="AHI Threshold (5)", line_color="red")
        st.plotly_chart(fig_ahi, use_container_width=True)
        
        fig_pressure = px.line(daily_data.tail(7), x=daily_data.tail(7).index, y=pressure_signal, title="Recorded Pressure (Last 7 Days)")
        fig_pressure.update_xaxes(tickformat="%b %d", title_text="Day")
        fig_pressure.update_yaxes(title_text="Recorded Pressure (cmH2O)")
        st.plotly_chart(fig_pressure, use_container_width=True)
        
        weekly_recommended = daily_data['Recommended Pressure'].resample('W-SUN').mean()  # Get weekly averages
        weekly_recommended_table = pd.DataFrame({
            'Week Start': weekly_recommended.index.date,
            'Recommended Pressure': [f"{pressure:.1f}" for pressure in weekly_recommended.values]
        })
        recommended_pressure = st.dataframe(weekly_recommended_table, hide_index=True)
        st.download_button(label="Download Data as CSV", data=daily_data.to_csv(), file_name="cpap_analysis.csv")
    
    else:
        st.warning("Please select valid signals for AHI and MaskPress.95.")
else:
    st.write("Please upload a CPAP data file or select a file from your AirSense 11 memory card.")
# app.py
import streamlit as st
from utils.plate import create_plate_df, render_interactive_plate
from utils.parser import parse_qxmanager_csv
from utils.calculator import calculate_copies_per_sample
import pandas as pd

# ===========================
# PAGE CONFIG & TITLE
# ===========================
st.set_page_config(page_title="ddPCR Calculator Pro", layout="wide")
st.title("ddPCR Data Processor")
st.markdown("Upload your files → customize DNA input per well → get accurate copies/ng results")

# ===========================
# SESSION STATE INITIALIZATION
# ===========================
if "well_mass" not in st.session_state:
    st.session_state.well_mass = {}  # Format: {"A1": 140.0, "B7": 50.0}
if "plate_layout_df" not in st.session_state:
    st.session_state.plate_layout_df = None
if "study_info_df" not in st.session_state:
    st.session_state.study_info_df = None
if "qx_data" not in st.session_state:
    st.session_state.qx_data = None

# ===========================
# SIDEBAR: FILE UPLOADS
# ===========================
st.sidebar.header("1. Upload Files")

plate_layout_file = st.sidebar.file_uploader(
    "Plate Layout CSV (Well → Sample ID)",
    type="csv",
    key="plate"
)

study_info_file = st.sidebar.file_uploader(
    "Study Info CSV (Sample ID → Desired DNA mass in ng)",
    type="csv",
    key="study"
)

qx_file = st.sidebar.file_uploader(
    "QxManager / QuantaSoft Export CSV",
    type="csv",
    key="qx"
)

default_ng = st.sidebar.number_input("Global Default DNA Input (ng)", value=140.0, step=5.0)

# ===========================
# LOAD & CACHE DATA
# ===========================
@st.cache_data
def load_csv(file):
    if file is not None:
        return pd.read_csv(file)
    return None

plate_layout_df = load_csv(plate_layout_file)
study_info_df = load_csv(study_info_file)
qx_data_raw = load_csv(qx_file)

# Store in session state
st.session_state.plate_layout_df = plate_layout_df
st.session_state.study_info_df = study_info_df

# ===========================
# PARSE QXMANAGER DATA
# ===========================
if qx_data_raw is not None:
    with st.spinner("Parsing QuantaSoft data..."):
        st.session_state.qx_data = parse_qxmanager_csv(qx_data_raw)
    st.success("QxManager data loaded successfully!")
else:
    st.session_state.qx_data = None

# ===========================
# BUILD PLATE WITH DNA MASS
# ===========================
plate_df = create_plate_df(
    plate_layout_df=plate_layout_df,
    study_info_df=study_info_df,
    default_ng=default_ng,
    user_overrides=st.session_state.well_mass
)

# ===========================
# INTERACTIVE 96-WELL PLATE
# ===========================
st.subheader("Interactive 96-Well Plate – Click to Set DNA Mass (ng)")
updated_mass = render_interactive_plate(plate_df, st.session_state.well_mass)
st.session_state.well_mass = updated_mass  # Sync back

# ===========================
# FINAL CALCULATIONS & RESULTS
# ===========================
if st.button("Run Calculations", type="primary"):
    if st.session_state.qx_data is None:
        st.error("Please upload QxManager data first.")
    elif plate_df['Sample'].isna().all():
        st.error("Please upload a valid plate layout.")
    else:
        with st.spinner("Calculating copies/µL, copies/ng, and total copies..."):
            results_df = calculate_copies_per_sample(
                qx_data=st.session_state.qx_data,
                plate_df=plate_df
            )
        st.success("Calculations Complete!")
        st.dataframe(results_df, use_container_width=True)
        csv = results_df.to_csv(index=False).encode()
        st.download_button("Download Results CSV", csv, "ddpcr_results.csv", "text/csv")

# utils/plate.py
import pandas as pd
import streamlit as st
import numpy as np

def create_plate_df(plate_layout_df, study_info_df, default_ng, user_overrides):
    wells = [f"{row}{col}" for row in "ABCDEFGH" for col in range(1,13)]
    plate = pd.DataFrame({"Well": wells})
    
    # Start with empty sample
    plate["Sample"] = ""
    plate["DNA_ng"] = default_ng

    # Apply plate layout
    if plate_layout_df is not None and "Well" in plate_layout_df.columns:
        layout = plate_layout_df[["Well", "Sample"]].copy()
        layout["Well"] = layout["Well"].astype(str).str.upper()
        plate = plate.merge(layout, on="Well", how="left", suffixes=("", "_layout"))
        plate["Sample"] = plate["Sample_layout"].combine_first(plate["Sample"])
        plate.drop(columns=["Sample_layout"], inplace=True, errors='ignore')

    # Apply study info (Sample → DNA_ng)
    if study_info_df is not None and "Sample" in study_info_df.columns:
        study_dict = dict(zip(study_info_df["Sample"], study_info_df["DNA_ng"]))
        plate["DNA_ng"] = plate["Sample"].map(study_dict).fillna(plate["DNA_ng"])

    # Apply user manual overrides
    for well, ng in user_overrides.items():
        if well in plate["Well"].values:
            plate.loc[plate["Well"] == well.upper(), "DNA_ng"] = float(ng)

    return plate

def render_interactive_plate(plate_df, current_overrides):
    cols = st.columns(13)
    cols[0].markdown("**Well**")
    for c in range(1, 13):
        cols[c].markdown(f"**{c}**")

    new_overrides = current_overrides.copy()

    for row_letter in "ABCDEFGH":
        cols = st.columns(13)
        cols[0].write(f"**{row_letter}**")
        for col in range(1, 13):
            well = f"{row_letter}{col}"
            row = plate_df[plate_df["Well"] == well].iloc[0]
            sample = row["Sample"] if pd.notna(row["Sample"]) else "-"
            mass = row["DNA_ng"]

            # Color based on mass
            color = "lightblue" if mass == 140 else "lightcoral" if mass < 50 else "lightgreen"
            if well in current_overrides:
                color = "orange"

            with cols[col]:
                if st.button(f"{sample}\n{mass:.0f} ng", key=well, help=f"Click to change {well}"):
                    new_val = st.number_input(
                        f"DNA mass for {well}", value=float(mass), step=5.0, key=f"input_{well}"
                    )
                    new_overrides[well] = new_val
                    st.rerun()

    return new_overrides

# utils/parser.py
import pandas as pd

def parse_qxmanager_csv(df):
    # Standard QuantaSoft column names (adjust if needed)
    expected_cols = ["Well", "Target", "Copies/µL", "Positives", "AcceptedDroplets"]
    if not all(col in df.columns for col in ["Well", "Target"]):
        raise ValueError("Not a valid QuantaSoft export")

    df = df.copy()
    df["Well"] = df["Well"].astype(str).str.upper()
    df["Copies/µL"] = pd.to_numeric(df["Copies/µL"], errors="coerce")
    return df

# utils/calculator.py
import pandas as pd

def calculate_copies_per_sample(qx_data, plate_df):
    plate_dict = plate_df.set_index("Well")[["Sample", "DNA_ng"]].to_dict("index")
    
    results = []
    for _, row in qx_data.iterrows():
        well = row["Well"]
        if well not in plate_dict or plate_dict[well]["Sample"] == "":
            continue
        sample = plate_dict[well]["Sample"]
        dna_ng = plate_dict[well]["DNA_ng"]
        copies_per_ul = row["Copies/µL"] or 0
        copies_per_ng = copies_per_ul / dna_ng if dna_ng > 0 else 0
        total_copies = copies_per_ng * dna_ng  # per reaction

        results.append({
            "Well": well,
            "Sample": sample,
            "Target": row["Target"],
            "Copies/µL": copies_per_ul,
            "DNA_ng": dna_ng,
            "Copies/ng": copies_per_ng,
            "Total Copies": total_copies
        })

    return pd.DataFrame(results)




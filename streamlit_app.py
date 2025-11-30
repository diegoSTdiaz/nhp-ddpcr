# =============================================================================
# NHP / FST ddPCR Plate Planner & Analyzer
# Version: Clean + Sectioned for Easy Future Updates
# =============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ====================== SECTION 1: PAGE CONFIG & TITLE ======================
st.set_page_config(page_title="NHP ddPCR Analyzer", layout="wide")
st.title("ddPCR Automated Analysis with Graphs")
st.markdown("**Simple Upload**: only 3 required files")

# ====================== SECTION 2: FILE UPLOADERS ======================
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Plate Layout")
    plate_file = st.file_uploader(
        "Well1.csv or similar from Benchling/QuantaSoft",
        type=["csv"],
        key="plate"
    )

with col2:
    st.subheader("2. Sample Info (6 columns only)")
    sample_file = st.file_uploader(
        "Sample Number → Study ID, Treatment, Animal, Tissue, Day",
        type=["csv"],
        key="samples"
    )

# Optional results file
st.markdown("---")
results_file = st.file_uploader(
    "Finished run → QXManager results CSV (optional now)",
    type=["csv"],
    key="results"
)

# ====================== SECTION 3: ASSAY & LOADING SETTINGS ======================
st.markdown("---")
st.subheader("Assay & Loading Settings")

col_a, col_b, col_c = st.columns(3)

with col_a:
    fam_options = ["WPRE_5", "slot_1", "slot_2", "slot_3", "slot_4", "Other..."]
    fam_probe = st.selectbox("FAM target gene", options=fam_options, index=0)
    if fam_probe == "Other...":
        fam_probe = st.text_input("Custom FAM target")

with col_b:
    vic_options = ["Mf-B2M-VIC-PL", "Taqman_Rplp0_VIC_PL", "HPRT1-VIC", "GUSB-VIC", "Other..."]
    vic_probe = st.selectbox("VIC reference gene", options=vic_options, index=1)
    if vic_probe == "Other...":
        vic_probe = st.text_input("Custom VIC reference")

with col_c:
    show_loading = st.checkbox(
        "Show raw loading (copies/µL) instead of CN/DG",
        value=False
    )

# ====================== SECTION 4: LOAD PLATE LAYOUT (BULLETPROOF PARSER) ======================
if plate_file and sample_file:
    # --- Hard-coded expected plate template (96-well A1:H12) ---
    # This is the gold standard. Any uploaded CSV will be forced into this shape.
    expected_plate_cols = [str(i) for i in range(1, 13)]  # "1", "2", ..., "12"
    expected_rows = ["A", "B", "C", "D", "E", "F", "G", "H"]

    plate_raw = pd.read_csv(plate_file)

    # Auto-fix common issues
    if plate_raw.columns[0] == "Unnamed: 0" or plate_raw.iloc[:, 0].isin(expected_rows).all():
        plate_raw = plate_raw.set_index(plate_raw.columns[0])
    
    # Force into correct shape: 8 rows × 12 columns + proper index
    plate = pd.DataFrame(index=expected_rows, columns=expected_plate_cols)
    
    for idx, row in plate_raw.iterrows():
        if str(idx).strip() in expected_rows:
            for col in row.index:
                col_str = str(col).strip().replace(".0", "")
                if col_str in expected_plate_cols:
                    plate.loc[idx, col_str] = row[col]

    plate = plate.astype(str)
    plate_long = plate.stack().reset_index()
    plate_long.columns = ["Row", "Column", "Sample Number"]
    plate_long["Well"] = plate_long["Row"] + plate_long["Column"]
    plate_long = plate_long[["Well", "Sample Number"]]
    plate_long = plate_long[plate_long["Sample Number"].str.strip() != ""]
    plate_long = plate_long[plate_long["Sample Number"].notna()]

    # Normalize sample numbers (NTC stays string, others → int → str for consistency)
    def normalize_sample(x):
        x = str(x).strip().upper()
        if x in ["NTC", "NT", "NO TEMPLATE", "WATER"]:
            return "NTC"
        try:
            return str(int(float(x)))
        except:
            return x
    plate_long["Sample Number"] = plate_long["Sample Number"].apply(normalize_sample)

    st.success("Plate layout parsed perfectly (bulletproof mode enabled)")

# ====================== SECTION 5: LOAD SAMPLE METADATA (NOW INCLUDES MASS) ======================
    samples_raw = pd.read_csv(sample_file)

    # --- Expected columns (now including mass) ---
    expected_sample_cols = [
        "Sample Number", "Study ID", "Treatment",
        "Animal", "Tissue Type", "Takedown Day", "Desired mass in rxn (ng)"
    ]

    # Auto-map uploaded columns (still flexible)
    col_map = {}
    for expected in expected_sample_cols:
        for uploaded_col in samples_raw.columns:
            if expected.lower() in uploaded_col.lower() or uploaded_col.lower() in expected.lower():
                col_map[expected] = uploaded_col
                break
        else:
            if expected != "Desired mass in rxn (ng)":  # mass is optional for now
                st.error(f"Could not find required column: **{expected}**")
                st.stop()

    # Build clean samples dataframe
    samples = pd.DataFrame()
    for expected in expected_sample_cols:
        if expected in col_map:
            samples[expected] = samples_raw[col_map[expected]]
        else:
            samples[expected] = pd.NA  # only happens for mass if missing

    # Cleanup
    samples["Sample Number"] = samples["Sample Number"].astype(str).str.strip()
    samples["Study ID"] = samples["Study ID"].astype(str).str.strip()
    samples["Treatment"] = samples["Treatment"].str.strip()
    samples["Tissue Type"] = samples["Tissue Type"].str.strip()
    samples["Takedown Day"] = pd.to_numeric(samples["Takedown Day"], errors="coerce")
    samples["Desired mass in rxn (ng)"] = pd.to_numeric(samples["Desired mass in rxn (ng)"], errors="coerce")

    # Merge with plate
    full = plate_long.merge(samples, on="Sample Number", how="left")

    annotated_count = len(full.dropna(subset=["Study ID"]))
    st.success(f"Mapping complete! {annotated_count} wells fully annotated.")
    st.dataframe(full, use_container_width=True)

    st.download_button(
        label="Download Annotated Plate with Metadata",
        data=full.to_csv(index=False).encode(),
        file_name="annotated_plate_with_metadata.csv",
        mime="text/csv",
        key="download_annotated"
    )
# ====================== SECTION 6: PROCESS RESULTS (IF UPLOADED) ======================
    if results_file:
        results = pd.read_csv(results_file)

        # Auto-detect FAM and VIC concentration columns
        fam_col = vic_col = None
        for col in results.columns:
            if "FAM" in col.upper() and "CONC" in col.upper():
                fam_col = col
            if "VIC" in col.upper() and "CONC" in col.upper():
                vic_col = col

        if not (fam_col and vic_col and "Well" in results.columns):
            st.error("Could not find FAM/VIC concentration columns or Well column.")
            st.stop()

        # Pivot to one row per well
        fam = results[results["Target"] == 1][["Well", fam_col]].rename(columns={fam_col: "FAM"})
        vic = results[results["Target"] == 2][["Well", vic_col]].rename(columns={vic_col: "VIC"})
        conc = fam.merge(vic, on="Well", how="inner")

        final = full.merge(conc, on="Well", how="left")
        final["CN/DG"] = final["FAM"] / final["VIC"]

# ====================== SECTION 7: SIDEBAR – BAR COLOR PICKER ======================
        color_map = {
            "Treated": "lightpink",
            "Untreated": "lightblue",
            "Naïve": "lightgray",
            "Naive": "lightgray",
            "NTC": "whitesmoke"
        }
        st.sidebar.header("Bar colors")
        for tr in ["Treated", "Untreated", "Naïve", "NTC"]:
            color_map[tr] = st.sidebar.color_picker(tr, color_map.get(tr, "gray"), key=f"color_{tr}")

# ====================== SECTION 8: GENERATE PLOTS PER STUDY ======================
        for study in sorted(final["Study ID"].dropna().unique()):
            df = final[final["Study ID"] == study].copy()
            df = df.dropna(subset=["Treatment"])

            tissue = df["Tissue Type"].mode()[0]
            day = df["Takedown Day"].mode()[0]
            subtitle = f"{tissue} – Day {int(day)}"

            if not show_loading:
                # === Normalized CN/DG Plot ===
                fig1 = go.Figure()
                naive_mean = df[df["Treatment"].isin(["Naïve", "Naive"])]["CN/DG"].mean()

                for treatment in df["Treatment"].unique():
                    sub = df[df["Treatment"] == treatment]
                    mean_val = sub["CN/DG"].mean()
                    sem_val = sub["CN/DG"].sem() if len(sub) > 1 else 0

                    fig1.add_trace(go.Bar(
                        name=treatment,
                        x=[treatment],
                        y=[mean_val],
                        error_y=dict(type="data", array=[sem_val]),
                        marker_color=color_map.get(treatment, "gray"),
                        width=0.6
                    ))
                    fig1.add_trace(go.Scatter(
                        x=[treatment] * len(sub),
                        y=sub["CN/DG"],
                        mode="markers",
                        marker=dict(color="black", size=10),
                        showlegend=False
                    ))

                if not pd.isna(naive_mean):
                    fig1.add_hline(y=naive_mean, line_dash="dash", line_color="gray",
                                   annotation_text=" Naïve reference", annotation_position="top left")

                fig1.update_layout(
                    title=f"<b>{study}</b> – {subtitle}<br>{fam_probe} / {vic_probe} normalized CN/DG",
                    yaxis_title="Copies per diploid genome (CN/DG)",
                    template="simple_white",
                    height=700,
                    font=dict(size=18)
                )
                st.plotly_chart(fig1, use_container_width=True)
                st.download_button(
                    f"Download {study} – Normalized",
                    fig1.to_image(format="png", scale=2),
                    f"{study}_CN_DG.png",
                    "image/png",
                    key=f"norm_{study}"
                )

            else:
                # === Raw Loading Plots (FAM & VIC) ===
                # FAM loading
                fig_fam = go.Figure()
                for treatment in df["Treatment"].unique():
                    sub = df[df["Treatment"] == treatment]
                    fig_fam.add_trace(go.Bar(
                        name=treatment,
                        x=[treatment],
                        y=[sub["FAM"].mean()],
                        error_y=dict(type="data", array=[sub["FAM"].sem()]),
                        marker_color=color_map.get(treatment, "gray")
                    ))
                fig_fam.update_layout(
                    title=f"<b>{study}</b> – {subtitle}<br>{fam_probe} loading (copies/µL)",
                    yaxis_title="FAM copies/µL",
                    template="simple_white",
                    height=600
                )
                st.plotly_chart(fig_fam, use_container_width=True)

                # VIC loading
                fig_vic = go.Figure()
                for treatment in df["Treatment"].unique():
                    sub = df[df["Treatment"] == treatment]
                    fig_vic.add_trace(go.Bar(
                        name=treatment,
                        x=[treatment],
                        y=[sub["VIC"].mean()],
                        error_y=dict(type="data", array=[sub["VIC"].sem()]),
                        marker_color=color_map.get(treatment, "gray")
                    ))
                fig_vic.update_layout(
                    title=f"<b>{study}</b> – {subtitle}<br>{vic_probe} loading (copies/µL)",
                    yaxis_title="VIC copies/µL",
                    template="simple_white",
                    height=600
                )
                st.plotly_chart(fig_vic, use_container_width=True)

# ====================== SECTION 9: NO FILES UPLOADED MESSAGE ======================
else:
    st.info("Upload Plate Layout + Sample Info to begin. Add results CSV when run is done.")







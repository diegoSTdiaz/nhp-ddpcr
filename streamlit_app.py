Pythonimport streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="NHP ddPCR Analyzer", layout="wide")
st.title("NHP / FST ddPCR Plate Planner & Analyzer")
st.markdown("**New & improved**: only 2 required files + smart assay selector")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Plate Layout")
    plate_file = st.file_uploader("Well1.csv or similar from Benchling/QuantaSoft", type=["csv"], key="plate")

with col2:
    st.subheader("2. Sample Info (6 columns only)")
    sample_file = st.file_uploader("Sample Number → Study ID, Treatment, Animal, Tissue, Day", type=["csv"], key="samples")

# Optional results
st.markdown("---")
results_file = st.file_uploader("Finished run → QuantaSoft/QX200 results CSV (optional now)", type=["csv"], key="results")

# Assay selector
st.markdown("---")
st.subheader("Assay & Loading Settings")

col_a, col_b, col_c = st.columns(3)
with col_a:
    fam_options = ["WPRE_5", "hAAT", "CMV", "EF1α", "Other..."]
    fam_probe = st.selectbox("FAM target gene", options=fam_options, index=0)
    if fam_probe == "Other...":
        fam_probe = st.text_input("Custom FAM target", "MyTarget")

with col_b:
    vic_options = ["Mf-B2M-VIC-PL", "Taqman_Rplp0_VIC_PL", "HPRT1-VIC", "GUSB-VIC", "Other..."]
    vic_probe = st.selectbox("VIC reference gene", options=vic_options, index=1)
    if vic_probe == "Other...":
        vic_probe = st.text_input("Custom VIC reference", "MyReference")

with col_c:
    show_loading = st.checkbox("Show raw loading (copies/µL) instead of CN/DG", value=False)

if plate_file and sample_file:
    # ====================== Load plate layout ======================
    plate = pd.read_csv(plate_file)
    plate.columns = [""] + [f"{i}" for i in plate.columns[1:]]
    plate = plate.set_index(plate.columns[0])
    plate_long = plate.stack().reset_index()
    plate_long.columns = ["Row", "Column", "Sample Number"]
    plate_long["Well"] = plate_long["Row"] + plate_long["Column"].str.replace(".0", "")
    plate_long = plate_long[["Well", "Sample Number"]].dropna()

    # Handle both numeric sample numbers and text NTCs
    def to_sample(x):
        try:
            return int(x)
        except:
            return str(x)
    plate_long["Sample Number"] = plate_long["Sample Number"].apply(to_sample)

    # ====================== Load sample metadata ======================
    samples = pd.read_csv(sample_file)
    required = ["Sample Number", "Study ID", "Treatment", "Animal", "Tissue Type", "Takedown Day"]
    if not all(c in samples.columns for c in required):
        st.error(f"Sample Info missing columns. Needs: {', '.join(required)}")
        st.stop()

    samples["Sample Number"] = samples["Sample Number"].astype(str)
    full = plate_long.merge(samples, on="Sample Number", how="left")

    st.success(f"Plate mapped! {len(full.dropna(subset=['Study ID']))} wells annotated.")
    st.dataframe(full, use_container_width=True)
    st.download_button("Download annotated plate", full.to_csv(index=False), "annotated_plate.csv", "text/csv")

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
            st.error("Could not find FAM/VIC concentration columns.")
            st.stop()

        # Pivot results to one row per well
        fam = results[results["Target"] == 1][["Well", fam_col]].rename(columns={fam_col: "FAM"})
        vic = results[results["Target"] == 2][["Well", vic_col]].rename(columns={vic_col: "VIC"})
        conc = fam.merge(vic, on="Well", how="inner")

        final = full.merge(conc, on="Well", how="left")
        final["CN/DG"] = final["FAM"] / final["VIC"]

        # Color picker
        color_map = {"Treated": "lightpink", "Untreated": "lightblue", "Naïve": "lightgray", "Naive": "lightgray", "NTC": "whitesmoke"}
        st.sidebar.header("Bar colors")
        for tr in ["Treated", "Untreated", "Naïve", "NTC"]:
            color_map[tr] = st.sidebar.color_picker(tr, color_map.get(tr, "gray"), key=f"color_{tr}")

        for study in sorted(final["Study ID"].dropna().unique()):
            df = final[final["Study ID"] == study].copy()
            df = df.dropna(subset=["Treatment"])

            tissue = df["Tissue Type"].mode()[0]
            day = df["Takedown Day"].mode()[0]
            subtitle = f"{tissue} – Day {int(day)}"

            if not show_loading:
                # Normalized CN/DG plot
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
                st.download_button(f"Download {study} – Normalized", fig1.to_image(format="png", scale=2),
                                   f"{study}_CN_DG.png", "image/png", key=f"norm_{study}")

            else:
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
                fig_fam.update_layout(title=f"<b>{study}</b> – {subtitle}<br>{fam_probe} loading (copies/µL)",
                                      yaxis_title="FAM copies/µL", template="simple_white", height=600)
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
                fig_vic.update_layout(title=f"<b>{study}</b> – {subtitle}<br>{vic_probe} loading (copies/µL)",
                                      yaxis_title="VIC copies/µL", template="simple_white", height=600)
                st.plotly_chart(fig_vic, use_container_width=True)

else:
    st.info("Upload Plate Layout + Sample Info to begin. Add results CSV when run is done.")

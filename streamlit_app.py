import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="NHP ddPCR Analyzer", layout="wide")
st.title("🧬 NHP / FST ddPCR Plate Planner & Analyzer")
st.markdown("Upload your 3 Benchling/QuantaSoft files below – everything happens automatically.")

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("1. Plate Layout")
    plate_file = st.file_uploader("Plate layout with sample numbers in wells", type=["csv"], key="plate")

with col2:
    st.subheader("2. Sample Info")
    sample_file = st.file_uploader("Sample metadata with Sample Number → Treatment etc.", type=["csv"], key="samples")

with col3:
    st.subheader("3. Experiment Info")
    exp_file = st.file_uploader("Study → Tissue, Assay, Day", type=["csv"], key="exp")

# Optional – real results when the run is done
st.markdown("---")
results_file = st.file_uploader("Finished run? Upload QuantaSoft/QX200 results CSV (optional now, required for graphs)", type=["csv"], key="results")

if plate_file and sample_file and exp_file:
    # ====================== Load & clean plate layout ======================
    plate = pd.read_csv(plate_file)
    # Fix the standard Bio-Rad empty first cell
    plate.columns = [""] + [f"{i}" for i in plate.columns[1:]]
    plate = plate.set_index(plate.columns[0])
    plate_long = plate.stack().reset_index()
    plate_long.columns = ["Row", "Column", "Sample Number"]
    plate_long["Well"] = plate_long["Row"] + plate_long["Column"].str.replace(".0","")
    plate_long = plate_long[["Well", "Sample Number"]].dropna()
    plate_long["Sample Number"] = plate_long["Sample Number"].astype(int)

    # ====================== Load metadata ======================
    samples = pd.read_csv(sample_file)
    exp = pd.read_csv(exp_file)

    # Required columns check
    required = ["Sample Number", "Sample Name", "Study ID", "Treatment"]
    if not all(c in samples.columns for c in required):
        st.error("Sample file is missing one of these columns: " + ", ".join(required))
        st.stop()

    samples["Sample Number"] = samples["Sample Number"].astype(int)

    # ====================== Merge everything ======================
    full = plate_long.merge(samples, on="Sample Number", how="left")
    full = full.merge(exp, on="Study ID", how="left")

    st.success(f"Plate fully mapped! {len(full)} wells annotated.")
    st.dataframe(full, use_container_width=True)

    csv = full.to_csv(index=False).encode()
    st.download_button("📄 Download annotated plate CSV", csv, "ddPCR_full_plate.csv", "text/csv")

    # ====================== If real results are uploaded → make your exact graphs ======================
    if results_file:
        results = pd.read_csv(results_file)

        # Try to find FAM and VIC concentration columns automatically
        fam_col = None
        vic_col = None
        for col in results.columns:
            if "FAM" in col.upper() and ("CONC" in col.upper() or "COPIES" in col.upper()):
                fam_col = col
            if "VIC" in col.upper() and ("CONC" in col.upper() or "COPIES" in col.upper()):
                vic_col = col

        if fam_col and vic_col and "Well" in results.columns:
            results = results[["Well", fam_col, vic_col]].copy()
            results.columns = ["Well", "FAM", "VIC"]

            final = full.merge(results, on="Well", how="left")
            final["CN/DG"] = final["FAM"] / final["VIC"]

            # Colors
            color_map = {"Treated": "lightpink", "Untreated": "lightblue", "Naïve": "lightgray", "NTC": "whitesmoke", "Naive": "lightgray"}
            st.sidebar.header("🎨 Change bar colors live")
            for tr in ["Treated", "Untreated", "Naïve", "NTC"]:
                color_map[tr] = st.sidebar.color_picker(tr, color_map.get(tr, "gray"), key=tr)

            for study in final["Study ID"].dropna().unique():
                df = final[final["Study ID"] == study].copy()
                df["Group"] = df["Treatment"].fillna("Unknown")

                fig = go.Figure()
                for treatment in df["Group"].unique():
                    sub = df[df["Group"] == treatment]
                    mean_val = sub["CN/DG"].mean()
                    sem_val = sub["CN/DG"].sem() if len(sub) > 1 else 0

                    fig.add_trace(go.Bar(
                        name=treatment,
                        x=[treatment],
                        y=[mean_val],
                        error_y=dict(type="data", array=[sem_val]),
                        marker_color=color_map.get(treatment, "gray"),
                        width=0.6
                    ))
                    fig.add_trace(go.Scatter(
                        x=[treatment] * len(sub),
                        y=sub["CN/DG"],
                        mode="markers",
                        marker=dict(color="black", size=10),
                        showlegend=False
                    ))

                # Naïve diagonal label
                naive_rows = df[df["Treatment"] == "Naïve"]
                if not naive_rows.empty and mean_val > 0:
                    naive_name = naive_rows.iloc[0]["Animal"] + " Naïve reference"
                    fig.add_annotation(text=naive_name, x="Naïve", y=mean_val * 0.6,
                                       showarrow=False, textangle=-35, font=dict(size=12, color="gray"))

                fig.update_layout(
                    title=f"<b>{study}</b> – {df.iloc[0]['Tissue Type']} – Day {df.iloc[0]['Takedown Day']}<br>Normalized CN/DG",
                    yaxis_title="CN/DG",
                    template="simple_white",
                    font=dict(size=18),
                    height=700
                )
                st.plotly_chart(fig, use_container_width=True)
                png = fig.to_image(format="png", width=1200, height=800, scale=2)
                st.download_button(f"📸 Download {study} figure", png, f"{study}_CN_DG.png", "image/png", key=study)

else:
    st.info("Upload the three files above to get started. When your run is finished, drop the QuantaSoft results CSV for instant graphs.")


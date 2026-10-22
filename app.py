"""Dashboard · El incendio de Huanoquite: qué se quemó y a quién tocó.

Ejecutar:  streamlit run app.py
Lee solo archivos ya calculados por src/01..05 (no descarga nada).
"""

import json
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import rasterio
import streamlit as st
from rasterio.warp import Resampling, calculate_default_transform, reproject
from streamlit_folium import st_folium

RAIZ = Path(__file__).resolve().parent
PROC = RAIZ / "data" / "processed"
OUT = RAIZ / "outputs"

st.set_page_config(page_title="Incendio de Huanoquite", page_icon="🔥", layout="wide")

COLORES_SEV = {1: "#1a9850", 2: "#fee08b", 3: "#fdae61", 4: "#f46d43", 5: "#a50026"}
NOMBRES_SEV = {1: "No quemado", 2: "Baja", 3: "Moderada-baja", 4: "Moderada-alta", 5: "Alta"}


@st.cache_data
def cargar():
    d = {
        "info": json.load(open(PROC / "incendio_info.json")),
        "res": json.load(open(PROC / "resumen_dnbr.json")),
        "pob": json.load(open(PROC / "poblacion.json", encoding="utf-8")),
        "cob": pd.read_csv(PROC / "cobertura_quemada.csv"),
        "sev": pd.read_csv(PROC / "area_severidad.csv"),
        "sens": pd.read_csv(PROC / "sensibilidad.csv"),
    }
    return d


@st.cache_data
def severidad_rgba():
    """Reproyecta la severidad a EPSG:4326 y la pinta como imagen RGBA para el mapa."""
    with rasterio.open(PROC / "severidad.tif") as src:
        t, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        dst = np.zeros((h, w), dtype="uint8")
        reproject(src.read(1), dst, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=t, dst_crs="EPSG:4326", resampling=Resampling.nearest)
    rgba = np.zeros((h, w, 4), dtype="uint8")
    for k, hexa in COLORES_SEV.items():
        if k == 1:
            continue  # no pintamos lo no quemado
        r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
        rgba[dst == k] = [r, g, b, 210]
    oeste, norte = t.c, t.f
    este, sur = oeste + w * t.a, norte + h * t.e
    return rgba, [[sur, oeste], [norte, este]]


d = cargar()
info, res, pob, cob, sens = d["info"], d["res"], d["pob"], d["cob"], d["sens"]

# Encabezado ------------------------------------------------------------------------
st.title("🔥 El incendio de Huanoquite: qué se quemó y a quién tocó")
st.caption(
    "Paruro, Cusco · octubre de 2026 · Sentinel-2 L2A (Planetary Computer), focos VIIRS (NASA FIRMS), "
    "ESA WorldCover 2021, WorldPop 2020 · Proyecto de Ciencia de Datos con Python"
)

ha = res["ha_quemadas"]
pasto = cob.loc[cob["cobertura"] == "Pastizal", "pct_de_lo_quemado"].iat[0]
s15 = sens.query("umbral_dnbr == 0.27 and imagen_despues == 'Después = 15 oct'")["hectareas"].iat[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Área quemada", f"{ha:,.0f} ha", help=f"dNBR ≥ {res['umbral']} entre el 5 y el 17 de octubre")
c2.metric("Era pastizal", f"{pasto:.0f} %", help="Cruce con ESA WorldCover 2021")
c3.metric("Personas a ≤ 5 km", f"{pob['a_5km']:,}", help=f"WorldPop 2020 · {pob['a_1km']:,} a ≤ 1 km")
c4.metric("Creció en 2 días", f"×{ha / s15:.1f}", delta=f"{s15:,.0f} → {ha:,.0f} ha (15 → 17 oct)")

# Mapa --------------------------------------------------------------------------------
izq, der = st.columns([3, 2])
with izq:
    st.subheader("Mapa del incendio")
    capas = st.multiselect(
        "Capas", ["Severidad dNBR", "Focos VIIRS", "Radio de 5 km", "Contorno quemado"],
        default=["Severidad dNBR", "Focos VIIRS", "Radio de 5 km"],
    )
    lat, lon = (info["bbox"][1] + info["bbox"][3]) / 2, (info["bbox"][0] + info["bbox"][2]) / 2
    m = folium.Map(location=[lat, lon], zoom_start=14, tiles=None)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satélite",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Calles", show=False).add_to(m)

    if "Severidad dNBR" in capas:
        img, limites = severidad_rgba()
        folium.raster_layers.ImageOverlay(img, bounds=limites, name="Severidad dNBR").add_to(m)
    if "Radio de 5 km" in capas:
        folium.GeoJson(gpd.read_file(PROC / "buffer_5km.geojson"), name="Radio 5 km",
                       style_function=lambda _: {"color": "white", "weight": 2, "dashArray": "6", "fill": False}).add_to(m)
    if "Contorno quemado" in capas:
        folium.GeoJson(gpd.read_file(PROC / "quemado.geojson"), name="Quemado",
                       style_function=lambda _: {"color": "black", "weight": 1, "fillOpacity": 0}).add_to(m)
    if "Focos VIIRS" in capas:
        focos = gpd.read_file(PROC / "focos_peru.geojson")
        focos = focos[focos["incendio_id"] == info["incendio_id"]]
        for _, f in focos.iterrows():
            folium.CircleMarker(
                [f.latitude, f.longitude], radius=3, color="black", weight=1, fill=True,
                fill_color="cyan", fill_opacity=0.9,
                tooltip=f"{f.sensor} · {f.acq_date} {str(f.acq_time).zfill(4)} UTC · FRP {f.frp:.1f} MW",
            ).add_to(m)
    folium.LayerControl().add_to(m)
    st_folium(m, height=520, use_container_width=True, returned_objects=[])
    st.caption("Leyenda severidad: " + " · ".join(
        f"<span style='color:{COLORES_SEV[k]}'>■</span> {NOMBRES_SEV[k]}" for k in range(2, 6)), unsafe_allow_html=True)

with der:
    st.subheader("Tres hallazgos")
    bosque = cob.loc[cob["cobertura"] == "Bosque", "ha_quemadas"].iat[0]
    st.markdown(f"""
1. **Se quemaron {ha:,.0f} ha**, casi todo de severidad moderada. Equivale a ~{ha / 0.714:,.0f} canchas de fútbol.
2. **Ardió la puna, no el bosque:** el {pasto:.0f} % de lo quemado era **pastizal** — el forraje del ganado
   de las comunidades. Solo {bosque:.0f} ha eran bosque.
3. **{pob['a_5km']:,} personas viven a menos de 5 km** ({pob['a_1km']:,} a menos de 1 km), en
   {len(pob['distritos_en_5km'])} distritos: {", ".join(x['NOMBDIST'].title() for x in pob['distritos_en_5km'])}.
""")
    st.info(
        f"El incendio **se triplicó entre el 15 y el 17 de octubre** ({s15:,.0f} → {ha:,.0f} ha). "
        f"VIIRS detectó {info['focos']} focos entre el {info['primer_foco']} y el {info['ultimo_foco']}."
    )

# Pestañas -------------------------------------------------------------------------
t1, t2, t3, t4, t5 = st.tabs(["Antes y después", "¿Qué se quemó?", "¿A quién afecta?", "¿Cuánto se quemó? Depende", "Método y limitaciones"])

with t1:
    st.image(str(OUT / "01_antes_despues_dnbr.png"), use_container_width=True)
    st.markdown(
        "La mancha oscura a la derecha **ya existía el 5 de octubre**: es una quemadura anterior. "
        "El dNBR no la cuenta porque compara dos fechas — solo mide lo que cambió."
    )

with t2:
    cq = cob[cob["ha_quemadas"] > 0]
    fig = px.bar(cq, x="ha_quemadas", y="cobertura", orientation="h", text="ha_quemadas",
                 color="cobertura", color_discrete_map={"Pastizal": "#d9b44a", "Bosque": "#2d6a2d",
                                                        "Matorral": "#8a9a3b", "Cultivo": "#e07b39"},
                 labels={"ha_quemadas": "Hectáreas quemadas", "cobertura": ""})
    fig.update_layout(showlegend=False, height=300, yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(cob.rename(columns={
        "cobertura": "Cobertura", "ha_en_zona": "ha en la zona", "ha_quemadas": "ha quemadas",
        "pct_de_lo_quemado": "% de lo quemado", "pct_de_la_cobertura_que_ardio": "% de esa cobertura que ardió",
        "dnbr_medio_quemado": "dNBR medio"}), hide_index=True, use_container_width=True)

with t3:
    a, b = st.columns([3, 2])
    a.image(str(OUT / "05_poblacion_5km.png"), use_container_width=True)
    b.dataframe(pd.DataFrame(pob["distritos_en_5km"]).rename(
        columns={"NOMBDIST": "Distrito", "NOMBPROV": "Provincia", "poblacion_2020": "Población 2020"}),
        hide_index=True, use_container_width=True)
    b.markdown("Población **del distrito completo** (WorldPop). Las cifras a 1 y 5 km cuentan solo "
               "las celdas de 1 km cuyo centro cae dentro del radio.")

with t4:
    st.markdown("La computadora siempre da un número. **Cambiar la fecha de la imagen o el umbral cambia "
                "el resultado de 14 a 923 ha.** Por eso reportamos las decisiones:")
    st.image(str(OUT / "04_sensibilidad.png"), use_container_width=True)
    st.dataframe(sens, hide_index=True, use_container_width=True)

with t5:
    st.markdown(f"""
**Pregunta.** ¿Cuánto se quemó en el incendio de Huanoquite, qué tipo de cobertura era y cuánta gente vive cerca?

**Datos y fechas**
| Dato | Fuente | Fecha |
|---|---|---|
| Focos de calor | NASA FIRMS, VIIRS S-NPP + NOAA-20 (375 m) | 14–20 oct 2026 |
| Imagen antes | Sentinel-2 L2A, tile 18LZK | 5 oct 2026 · 0 % nubes en la zona |
| Imagen después | Sentinel-2 L2A, tile 18LZK | 17 oct 2026 · 0 % nubes en la zona |
| Cobertura | ESA WorldCover v200 (10 m) | 2021 |
| Población | WorldPop (1 km) | 2020 |
| Límites | INEI vía juaneladio/peru-geojson | — |

**Método**
1. Focos a ≤ 1 km y ≤ 48 h = un incendio (se descartan focos de confianza baja).
2. Zona de estudio = envolvente de los focos + 2 km.
3. NBR = (B8A − B12)/(B8A + B12) a 20 m; dNBR = NBR antes − NBR después.
4. Máscara SCL: nubes, sombras, cirros, agua y sin-dato en cualquiera de las dos fechas.
5. Quemado = dNBR ≥ {res['umbral']} (severidad moderada o más, Key & Benson 2006).
6. Cruce píxel a píxel con WorldCover (remuestreado a 20 m por moda) y suma de WorldPop en un radio de 5 km.

**Limitaciones**
- **Un foco de calor no es un incendio**, y la huella VIIRS (375 m) no es el área quemada.
- **El fuego seguía activo el 17 oct** (hay focos esa tarde): el área final puede ser mayor. La imagen del 20 oct
  está 100 % nublada, así que no se pudo cerrar la medición.
- **Humo** visible en la imagen del 17 oct en el sector oeste: puede bajar el dNBR y subestimar la severidad.
- Los umbrales de severidad son genéricos (EE. UU.); no están calibrados con campo para la puna peruana.
- WorldCover es de 2021 y WorldPop de 2020: la cobertura y la población actuales pueden diferir.
- Herramienta académica: no reemplaza los reportes del COEN, INDECI, SERFOR ni SERNANP.
""")

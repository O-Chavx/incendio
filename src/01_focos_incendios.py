"""Paso 1 · De focos de calor a incendios.

Lee los focos VIIRS (S-NPP y NOAA-20) de los últimos 7 días de NASA FIRMS,
se queda con los del Perú, les asigna distrito y los agrupa en incendios:
dos focos son del mismo incendio si están a <= 1 km y <= 48 h entre sí.

Salidas:
    data/processed/focos_peru.geojson     un foco por fila, con distrito e id de incendio
    data/processed/incendios_peru.csv     un incendio por fila, ordenado por tamaño
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.neighbors import BallTree

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
OUT = RAIZ / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

DIST_KM = 1.0
HORAS = 48
CRS_METRICO = "EPSG:32718"  # UTM 18S: distancias en metros para todo el sur del Perú

# 1 · Leer y unir los dos satélites -------------------------------------------
partes = []
for archivo, sat in [("firms_snpp_sa_7d.csv", "S-NPP"), ("firms_noaa20_sa_7d.csv", "NOAA-20")]:
    df = pd.read_csv(RAW / archivo)
    df["sensor"] = sat
    partes.append(df)
focos = pd.concat(partes, ignore_index=True)

# Fecha y hora en UTC (acq_time viene como HHMM)
hhmm = focos["acq_time"].astype(str).str.zfill(4)
focos["fecha_utc"] = pd.to_datetime(focos["acq_date"] + " " + hhmm, format="%Y-%m-%d %H%M", utc=True)

# Quitamos detecciones de baja confianza: suelen ser ruido
focos = focos[focos["confidence"] != "low"]

gfocos = gpd.GeoDataFrame(
    focos, geometry=gpd.points_from_xy(focos.longitude, focos.latitude), crs="EPSG:4326"
)

# 2 · Quedarse con el Perú y asignar distrito ----------------------------------
distritos = gpd.read_file(RAW / "peru_distrital_simple.geojson")[
    ["IDDIST", "NOMBDIST", "NOMBPROV", "NOMBDEP", "geometry"]
]
gfocos = gpd.sjoin(gfocos, distritos, predicate="within", how="inner").drop(columns="index_right")
print(f"Focos en el Perú (confianza nominal/alta): {len(gfocos):,}")

# 3 · Agrupar en incendios: grafo espacio-temporal ------------------------------
xy = gfocos.to_crs(CRS_METRICO).geometry
coords = np.column_stack([xy.x.values, xy.y.values])
t_horas = (gfocos["fecha_utc"].astype("int64") // 10**9 / 3600).values

arbol = BallTree(coords)
vecinos = arbol.query_radius(coords, r=DIST_KM * 1000)

filas, cols = [], []
for i, idx in enumerate(vecinos):
    cerca_en_tiempo = idx[np.abs(t_horas[idx] - t_horas[i]) <= HORAS]
    filas.extend([i] * len(cerca_en_tiempo))
    cols.extend(cerca_en_tiempo)
n = len(coords)
grafo = coo_matrix((np.ones(len(filas)), (filas, cols)), shape=(n, n))
_, etiqueta = connected_components(grafo, directed=False)
gfocos["incendio_id"] = etiqueta

# 4 · Resumen por incendio ------------------------------------------------------
ultimo = gfocos["fecha_utc"].max()

def resumir(g: pd.DataFrame) -> pd.Series:
    dep = g["NOMBDEP"].mode().iat[0]
    dist = g["NOMBDIST"].mode().iat[0]
    return pd.Series({
        "focos": len(g),
        "departamento": dep,
        "distrito": dist,
        "provincia": g["NOMBPROV"].mode().iat[0],
        "distritos_tocados": g["NOMBDIST"].nunique(),
        "inicio_utc": g["fecha_utc"].min(),
        "fin_utc": g["fecha_utc"].max(),
        "frp_total_mw": g["frp"].sum(),
        "lat": g["latitude"].mean(),
        "lon": g["longitude"].mean(),
        "lon_min": g["longitude"].min(), "lon_max": g["longitude"].max(),
        "lat_min": g["latitude"].min(), "lat_max": g["latitude"].max(),
        "activo_24h": (ultimo - g["fecha_utc"].max()) <= pd.Timedelta(hours=24),
    })

incendios = (
    gfocos.groupby("incendio_id").apply(resumir).sort_values("focos", ascending=False)
)
incendios.to_csv(OUT / "incendios_peru.csv")
gfocos.drop(columns=["fecha_utc"]).assign(fecha_utc=gfocos["fecha_utc"].astype(str)).to_file(
    OUT / "focos_peru.geojson", driver="GeoJSON"
)

print(f"Incendios (grupos de focos): {len(incendios):,}")
print("\nLos 15 más grandes en Apurímac y Cusco:")
sur = incendios[incendios["departamento"].isin(["APURIMAC", "CUSCO"])]
print(sur.head(15)[["focos", "departamento", "provincia", "distrito", "inicio_utc", "fin_utc", "frp_total_mw", "activo_24h"]].to_string())

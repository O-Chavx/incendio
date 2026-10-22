"""Paso 4 · ¿Qué se quemó y a quién afecta?

C · Cruce del área quemada (dNBR >= umbral) con ESA WorldCover 2021 (10 m):
    hectáreas quemadas por tipo de cobertura.
D · Personas que viven a <= 5 km del área quemada, con WorldPop 2020 (1 km).
    También el área quemada por distrito.

Salidas en data/processed/: cobertura_quemada.csv, cobertura.tif,
poblacion.json, quemado_por_distrito.csv, buffer_5km.geojson
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from rasterstats import zonal_stats

from config import UMBRAL_QUEMADO

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
PROC = RAIZ / "data" / "processed"
HA_PIXEL = 20 * 20 / 1e4

WORLDCOVER = {
    10: "Bosque", 20: "Matorral", 30: "Pastizal", 40: "Cultivo", 50: "Urbano",
    60: "Suelo desnudo", 70: "Nieve/hielo", 80: "Agua", 90: "Humedal", 95: "Manglar", 100: "Musgo/liquen",
}

# Grilla de referencia: la del dNBR
with rasterio.open(PROC / "dnbr.tif") as ref:
    dnbr = ref.read(1)
    perfil, crs, transform, shape = ref.profile, ref.crs, ref.transform, ref.shape
quemado = np.isfinite(dnbr) & (dnbr >= UMBRAL_QUEMADO)
valido = np.isfinite(dnbr)

# C · WorldCover ----------------------------------------------------------------
aoi = gpd.read_file(PROC / "aoi.geojson")
catalogo = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)
items = list(catalogo.search(collections=["esa-worldcover"], bbox=aoi.total_bounds.tolist()).items())
item = sorted(items, key=lambda i: i.datetime or i.properties.get("start_datetime"))[-1]  # 2021, v200
print(f"WorldCover: {item.id}")

cobertura = np.zeros(shape, dtype="uint8")
with rasterio.open(item.assets["map"].href) as src:
    b = aoi.total_bounds + np.array([-0.01, -0.01, 0.01, 0.01])
    ventana = from_bounds(*b, transform=src.transform)
    wc = src.read(1, window=ventana)
    # 10 m -> 20 m con "moda": cada píxel toma la clase más frecuente (no se promedian categorías)
    reproject(wc, cobertura, src_transform=src.window_transform(ventana), src_crs=src.crs,
              dst_transform=transform, dst_crs=crs, resampling=Resampling.mode)

p = perfil.copy(); p.update(dtype="uint8", nodata=0)
with rasterio.open(PROC / "cobertura.tif", "w", **p) as dst:
    dst.write(cobertura, 1)

filas = []
for codigo, nombre in WORLDCOVER.items():
    en_aoi = valido & (cobertura == codigo)
    if en_aoi.sum() == 0:
        continue
    q = (quemado & (cobertura == codigo)).sum()
    filas.append({
        "cobertura": nombre,
        "ha_en_zona": round(en_aoi.sum() * HA_PIXEL, 1),
        "ha_quemadas": round(q * HA_PIXEL, 1),
        "pct_de_lo_quemado": round(100 * q / quemado.sum(), 1),
        "pct_de_la_cobertura_que_ardio": round(100 * q / en_aoi.sum(), 1),
        "dnbr_medio_quemado": round(float(np.nanmean(np.where(quemado & (cobertura == codigo), dnbr, np.nan))), 3) if q else None,
    })
cob = pd.DataFrame(filas).sort_values("ha_quemadas", ascending=False)
cob.to_csv(PROC / "cobertura_quemada.csv", index=False)
print("\n¿Qué se quemó?\n" + cob.to_string(index=False))

# D · Población a <= 5 km --------------------------------------------------------
gq = gpd.read_file(PROC / "quemado.geojson")
utm = gq.to_crs(crs)
buffer_5km = gpd.GeoDataFrame(geometry=[utm.union_all().buffer(5000)], crs=crs)
buffer_5km.to_crs("EPSG:4326").to_file(PROC / "buffer_5km.geojson", driver="GeoJSON")
buffer_1km = gpd.GeoDataFrame(geometry=[utm.union_all().buffer(1000)], crs=crs)

wp = RAW / "per_ppp_2020_1km.tif"
pob = {}
for nombre, zona in [("a_5km", buffer_5km), ("a_1km", buffer_1km)]:
    z = zonal_stats(zona.to_crs("EPSG:4326"), str(wp), stats=["sum"], nodata=-99999, all_touched=False)
    pob[nombre] = round(z[0]["sum"] or 0)

# Contexto: población de los distritos tocados
distritos = gpd.read_file(RAW / "peru_distrital_simple.geojson")
tocados = distritos[distritos.intersects(buffer_5km.to_crs("EPSG:4326").geometry.iloc[0])].copy()
zs = zonal_stats(tocados, str(wp), stats=["sum"], nodata=-99999)
tocados["poblacion_2020"] = [round(z["sum"] or 0) for z in zs]

# Área quemada por distrito
dist_utm = tocados.to_crs(crs)
inter = gpd.overlay(utm, dist_utm[["NOMBDIST", "NOMBPROV", "NOMBDEP", "poblacion_2020", "geometry"]], how="intersection")
inter["ha"] = inter.area / 1e4
por_dist = (inter.groupby(["NOMBDEP", "NOMBPROV", "NOMBDIST", "poblacion_2020"])["ha"].sum()
            .round(1).reset_index().sort_values("ha", ascending=False))
por_dist.to_csv(PROC / "quemado_por_distrito.csv", index=False)

pob["distritos_en_5km"] = tocados[["NOMBDIST", "NOMBPROV", "poblacion_2020"]].to_dict("records")
json.dump(pob, open(PROC / "poblacion.json", "w"), indent=2, ensure_ascii=False)

print(f"\nPersonas a <= 1 km del área quemada: {pob['a_1km']:,}")
print(f"Personas a <= 5 km del área quemada: {pob['a_5km']:,}")
print("\nÁrea quemada por distrito:\n" + por_dist.to_string(index=False))
print("\nDistritos dentro del radio de 5 km:\n" + tocados[["NOMBDIST", "NOMBPROV", "poblacion_2020"]].to_string(index=False))

"""Paso 3 · NBR, dNBR y área quemada.

NBR  = (NIR - SWIR2) / (NIR + SWIR2)      con Sentinel-2 B8A (865 nm) y B12 (2190 nm), 20 m
dNBR = NBR_antes - NBR_despues           más alto = vegetación más dañada

Se enmascaran nubes, sombras, agua y sin-dato (capa SCL) en CUALQUIERA de las dos fechas.

Salidas en data/processed/:
    dnbr.tif, severidad.tif, rgb_antes.tif, rgb_despues.tif
    area_severidad.csv, sensibilidad.csv, quemado.geojson
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, shapes
from rasterio.windows import from_bounds

from config import CLASES_DNBR, IMG_ANTES, IMG_DESPUES, IMG_DESPUES_ALT, UMBRAL_QUEMADO

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
SCL_INVALIDO = [0, 1, 3, 6, 8, 9, 10, 11]  # + 6 (agua): el agua no "se quema" pero da dNBR ruidoso
RES = 20  # metros
HA_PIXEL = RES * RES / 1e4

catalogo = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)
aoi = gpd.read_file(PROC / "aoi.geojson")


def leer(item_id: str, banda: str, bounds, shape, resampling=Resampling.bilinear):
    """Lee una banda de un item recortada a la AOI y en la grilla común de 20 m."""
    item = catalogo.get_collection("sentinel-2-l2a").get_item(item_id)
    with rasterio.open(item.assets[banda].href) as src:
        ventana = from_bounds(*bounds, transform=src.transform)
        datos = src.read(1, window=ventana, out_shape=shape, resampling=resampling, boundless=True)
    return datos, item


def reflectancia(dn: np.ndarray, item) -> np.ndarray:
    """DN -> reflectancia. Desde la línea base 04.00 (2022) L2A trae un offset de -1000."""
    base = float(item.properties.get("s2:processing_baseline", "05.00"))
    offset = -1000 if base >= 4.0 else 0
    r = (dn.astype("float32") + offset) / 10000
    r[dn == 0] = np.nan
    return r


def nbr_y_mascara(item_id: str, bounds, shape):
    nir, item = leer(item_id, "B8A", bounds, shape)
    swir, _ = leer(item_id, "B12", bounds, shape)
    scl, _ = leer(item_id, "SCL", bounds, shape, resampling=Resampling.nearest)
    nir, swir = reflectancia(nir, item), reflectancia(swir, item)
    nbr = (nir - swir) / (nir + swir)
    return nbr, np.isin(scl, SCL_INVALIDO), item


def rgb(item_id: str, bounds, shape) -> np.ndarray:
    capas = []
    for b in ["B04", "B03", "B02"]:
        dn, item = leer(item_id, b, bounds, shape)
        capas.append(reflectancia(dn, item))
    return np.stack(capas)


# Grilla común: AOI en el CRS del tile (UTM 18S), redondeada a 20 m
item0 = catalogo.get_collection("sentinel-2-l2a").get_item(IMG_ANTES)
with rasterio.open(item0.assets["B12"].href) as src:
    crs = src.crs
aoi_utm = aoi.to_crs(crs)
x0, y0, x1, y1 = aoi_utm.total_bounds
x0, y0 = np.floor(x0 / RES) * RES, np.floor(y0 / RES) * RES
x1, y1 = np.ceil(x1 / RES) * RES, np.ceil(y1 / RES) * RES
bounds = (x0, y0, x1, y1)
shape = (int((y1 - y0) / RES), int((x1 - x0) / RES))
transform = rasterio.transform.from_origin(x0, y1, RES, RES)
dentro_aoi = ~geometry_mask(aoi_utm.geometry, out_shape=shape, transform=transform)


def guardar(nombre, arr, dtype="float32", nodata=np.nan, count=1):
    perfil = dict(driver="GTiff", height=shape[0], width=shape[1], count=count, dtype=dtype,
                  crs=crs, transform=transform, nodata=nodata, compress="deflate")
    with rasterio.open(PROC / nombre, "w", **perfil) as dst:
        dst.write(arr if count > 1 else arr[np.newaxis, ...])


def clasificar(dnbr: np.ndarray) -> np.ndarray:
    sev = np.zeros(dnbr.shape, dtype="uint8")  # 0 = sin dato
    for i, (lo, hi, _) in enumerate(CLASES_DNBR, start=1):
        sev[(dnbr >= lo) & (dnbr < hi)] = i
    return sev


def calcular(id_antes, id_despues):
    nbr_a, inv_a, _ = nbr_y_mascara(id_antes, bounds, shape)
    nbr_d, inv_d, _ = nbr_y_mascara(id_despues, bounds, shape)
    dnbr = nbr_a - nbr_d
    valido = dentro_aoi & ~inv_a & ~inv_d & np.isfinite(dnbr)
    dnbr[~valido] = np.nan
    return dnbr, valido


# 1 · Cálculo principal ---------------------------------------------------------
dnbr, valido = calcular(IMG_ANTES, IMG_DESPUES)
sev = clasificar(dnbr)
guardar("dnbr.tif", dnbr)
guardar("severidad.tif", sev, dtype="uint8", nodata=0)
guardar("rgb_antes.tif", rgb(IMG_ANTES, bounds, shape), count=3)
guardar("rgb_despues.tif", rgb(IMG_DESPUES, bounds, shape), count=3)

filas = []
for i, (lo, hi, nombre) in enumerate(CLASES_DNBR, start=1):
    filas.append({"clase": nombre, "dnbr_desde": lo, "dnbr_hasta": hi,
                  "hectareas": round((sev == i).sum() * HA_PIXEL, 1)})
area = pd.DataFrame(filas)
area.to_csv(PROC / "area_severidad.csv", index=False)

quemado = valido & (dnbr >= UMBRAL_QUEMADO)
ha_quemadas = quemado.sum() * HA_PIXEL
pct_valido = 100 * valido.sum() / dentro_aoi.sum()
print(area.to_string(index=False))
print(f"\nPíxeles válidos en la AOI: {pct_valido:.1f} %")
print(f"Área quemada (dNBR >= {UMBRAL_QUEMADO}): {ha_quemadas:,.0f} ha")

# Polígonos del área quemada (para mapas y cruces). Se descartan manchas < 0,5 ha (ruido)
geoms = [
    {"geometry": g, "properties": {}}
    for g, v in shapes(quemado.astype("uint8"), mask=quemado, transform=transform)
    if v == 1
]
gq = gpd.GeoDataFrame.from_features(geoms, crs=crs)
gq = gq[gq.area >= 5000]
gq.to_crs("EPSG:4326").to_file(PROC / "quemado.geojson", driver="GeoJSON")
print(f"Polígonos quemados (>= 0,5 ha): {len(gq)} · {gq.area.sum() / 1e4:,.0f} ha")

# 2 · Sensibilidad: ¿cuánto cambia el número con otras decisiones? -------------
sens = []
for etiqueta, desp in [("Después = 17 oct (principal)", IMG_DESPUES), ("Después = 15 oct", IMG_DESPUES_ALT)]:
    d, v = (dnbr, valido) if desp == IMG_DESPUES else calcular(IMG_ANTES, desp)
    for umbral in [0.10, 0.27, 0.44]:
        sens.append({"imagen_despues": etiqueta, "umbral_dnbr": umbral,
                     "hectareas": round((v & (d >= umbral)).sum() * HA_PIXEL, 0),
                     "validos_pct": round(100 * v.sum() / dentro_aoi.sum(), 1)})
sens = pd.DataFrame(sens)
sens.to_csv(PROC / "sensibilidad.csv", index=False)
print("\nSensibilidad:\n" + sens.to_string(index=False))

json.dump(
    {"ha_quemadas": round(float(ha_quemadas), 1), "umbral": UMBRAL_QUEMADO,
     "validos_pct": round(float(pct_valido), 1), "img_antes": IMG_ANTES, "img_despues": IMG_DESPUES},
    open(PROC / "resumen_dnbr.json", "w"), indent=2,
)

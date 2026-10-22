"""Paso 2 · Buscar imágenes Sentinel-2 antes y después del incendio.

Define la zona de estudio (AOI) a partir de los focos del incendio elegido,
busca escenas Sentinel-2 L2A en Microsoft Planetary Computer y, para cada una,
mide el % de nubes DENTRO de la zona usando la capa SCL (no el % de la escena
entera, que puede engañar).

Uso:
    python src/02_buscar_imagenes.py            # usa el incendio de config.py
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from config import AOI_BUFFER_M, BUSQUEDA_DESDE, BUSQUEDA_HASTA, INCENDIO_ID

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"

# Clases SCL de Sentinel-2 que tratamos como "no se ve el suelo"
SCL_INVALIDO = {0, 1, 3, 8, 9, 10, 11}  # sin dato, saturado, sombra de nube, nubes, cirros, nieve

# 1 · Zona de estudio --------------------------------------------------------
focos = gpd.read_file(PROC / "focos_peru.geojson")
focos_inc = focos[focos["incendio_id"] == INCENDIO_ID]
aoi_m = focos_inc.to_crs("EPSG:32718").union_all().convex_hull.buffer(AOI_BUFFER_M)
aoi = gpd.GeoSeries([aoi_m], crs="EPSG:32718").to_crs("EPSG:4326")
aoi.to_file(PROC / "aoi.geojson", driver="GeoJSON")
bbox = aoi.total_bounds.tolist()
print(f"Incendio {INCENDIO_ID}: {len(focos_inc)} focos · AOI bbox {np.round(bbox, 4)}")
print(f"Área de la AOI: {aoi_m.area / 1e4:,.0f} ha")

# 2 · Buscar escenas -----------------------------------------------------------
catalogo = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)
items = list(
    catalogo.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{BUSQUEDA_DESDE}/{BUSQUEDA_HASTA}",
    ).items()
)
print(f"Escenas encontradas: {len(items)}")

# 3 · % de nubes dentro de la AOI con la capa SCL -------------------------------
filas = []
for it in items:
    with rasterio.open(it.assets["SCL"].href) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox)
        ventana = from_bounds(*b, transform=src.transform)
        scl = src.read(1, window=ventana, boundless=True, fill_value=0)
    invalido = np.isin(scl, list(SCL_INVALIDO))
    filas.append({
        "id": it.id,
        "fecha": it.datetime.date().isoformat(),
        "tile": it.properties.get("s2:mgrs_tile"),
        "nubes_escena_pct": round(it.properties.get("eo:cloud_cover", np.nan), 1),
        "invalido_aoi_pct": round(100 * invalido.mean(), 1),
        "sin_dato_aoi_pct": round(100 * (scl == 0).mean(), 1),
    })

escenas = pd.DataFrame(filas).sort_values(["fecha", "invalido_aoi_pct"])
escenas.to_csv(PROC / "escenas_sentinel2.csv", index=False)
print(escenas.to_string(index=False))

inicio = pd.Timestamp(focos_inc["acq_date"].min())
fin = pd.Timestamp(focos_inc["acq_date"].max())
json.dump(
    {"incendio_id": INCENDIO_ID, "primer_foco": str(inicio.date()), "ultimo_foco": str(fin.date()),
     "focos": int(len(focos_inc)), "bbox": bbox},
    open(PROC / "incendio_info.json", "w"), indent=2,
)

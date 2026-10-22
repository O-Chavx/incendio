"""Decisiones de método en un solo lugar. Cambiar aquí cambia todo el análisis."""

# Incendio elegido (id de data/processed/incendios_peru.csv): Huanoquite, Paruro, Cusco
INCENDIO_ID = 42

# Zona de estudio: envolvente de los focos + este margen
AOI_BUFFER_M = 2000

# Ventana para buscar imágenes Sentinel-2
BUSQUEDA_DESDE = "2026-09-01"
BUSQUEDA_HASTA = "2026-10-21"

# Imágenes elegidas tras revisar data/processed/escenas_sentinel2.csv (tile 18LZK cubre toda la AOI)
IMG_ANTES = "S2C_MSIL2A_20261005T145731_R039_T18LZK_20261005T175220"    # 0 % nubes en la AOI
IMG_DESPUES = "S2A_MSIL2A_20261017T145731_R039_T18LZK_20261018T001002"  # 0 % nubes; fuego aún activo esa tarde
IMG_DESPUES_ALT = "S2C_MSIL2A_20261015T145731_R039_T18LZK_20261015T175103"  # 6 % nubes: prueba de sensibilidad

# Umbrales de severidad dNBR (Key & Benson 2006, USGS)
CLASES_DNBR = [
    (-1.0, 0.10, "No quemado"),
    (0.10, 0.27, "Baja"),
    (0.27, 0.44, "Moderada-baja"),
    (0.44, 0.66, "Moderada-alta"),
    (0.66, 2.0, "Alta"),
]
UMBRAL_QUEMADO = 0.27  # "quemado" = severidad moderada o más (mismo umbral que la clase del profesor)

# 🖼️ Better Images

Procesador de imágenes local con IA. Escala, quita fondos y convierte a SVG/ICO — todo en tu Mac, sin servicios pagos.

## Features

| Feature | Motor | Descripción |
|---|---|---|
| **AI Upscaling** ×2 / ×4 | Real-ESRGAN | Super-resolución con red neuronal |
| **Quitar Fondo** | rembg (U2-Net) | Eliminación de fondo con IA |
| **PNG → SVG** | vtracer | Conversión bitmap a vector |
| **PNG → ICO** | Pillow | Exportar favicon/icono multi-tamaño |

> 🔒 Todo corre 100% local. Los modelos AI se descargan una sola vez (~200MB total) y luego funciona completamente offline.

## Quick Start

### Con `uv` (recomendado)

```bash
cd better_images
uv sync
source .venv/bin/activate
python app.py
```

### Con `pip`

```bash
cd better_images
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Con el script automático

```bash
cd better_images
chmod +x run.sh
./run.sh
```

Luego abrí **http://localhost:5001** en tu navegador.

## Uso

1. **Arrastrá** o seleccioná una imagen (PNG, JPG, WEBP, BMP, TIFF)
2. **Elegí las opciones**:
   - Escalado: Sin escalar / ×2 / ×4
   - Quitar fondo: On/Off
   - Formato: PNG / SVG / ICO
3. Click en **Procesar Imagen**
4. **Descargá** el resultado

## Notas

- **Primera ejecución**: Los modelos AI se descargan automáticamente (~200MB). Después funciona offline.
- **Apple Silicon (M1/M2/M3/M4)**: Se detecta automáticamente el GPU Metal (MPS) para aceleración.
- **Imágenes grandes**: Se redimensionan automáticamente antes del upscaling si superan 1500px.
- **Tile processing**: Real-ESRGAN procesa en tiles de 256px para evitar problemas de memoria.

## Estructura

```
better_images/
├── app.py              # Flask server (API + static files)
├── processor.py        # Motor de procesamiento de imágenes
├── pyproject.toml      # Config para uv
├── requirements.txt    # Dependencias Python (pip)
├── run.sh              # Script de inicio automático
├── static/
│   ├── index.html      # UI web
│   ├── css/styles.css  # Dark theme con glassmorphism
│   └── js/app.js       # Frontend logic
├── models/             # Modelos AI (se descargan automáticamente)
├── uploads/            # Imágenes subidas (temporales)
└── outputs/            # Resultados procesados
```

## Requisitos

- Python 3.10+
- macOS / Linux / Windows
- ~2GB espacio en disco (para PyTorch + modelos)

# ⚡ Visor y Editor de Apuntes Manos Libres Asistido por IA (DeltaOS)

Sistema desacoplado de alto rendimiento para el **estudio técnico y preparación de oposiciones**, diseñado para visualización, intervención y compilación no destructiva de documentos PDF mediante comandos de voz emitidos por un modelo multimodal/LLM (Gemini Live) y ejecutados en cliente y servidor.

El flujo de trabajo es **"hands-free"**, asistido por seguimiento contextual del cursor del ratón y basado en una cuadrícula alfanumérica de referencia espacial discreta.

---

## 🏗️ 1. Arquitectura del Sistema

```
                   ┌───────────────────────────────────────────────┐
                   │               USUARIO (VOZ/RATÓN)             │
                   └───────┬───────────────────────────────▲───────┘
                           │                               │ Audio / Feedback
                           ▼                               │
              ┌────────────────────────┐      ┌────────────┴─────────────┐
              │ Orquestador LLM / Voz  │◄────►│ Contexto Espacial (HUD)  │
              │  (Gemini Live / API)   │      │ (página, celda, texto)   │
              └────────────┬───────────┘      └────────────▲─────────────┘
                           │ Function Calls                │
                           ▼                               │
     ┌─────────────────────────────────────────────────────┴──────────────────┐
     │                             BACKEND FASTAPI                            │
     │  - HTTP API: /api/pdf, /api/notes, /api/export, /api/tools, /api/context│
     │  - WebSocket: /ws/commands (bidireccional, baja latencia)              │
     │  - Sidecar JSON: documento.notes.json (persistencia no destructiva)    │
     │  - Compilador PyMuPDF: Ensanchado de MediaBox y dibujo vectorial nativo│
     └─────────────────────┬───────────────────────────────▲──────────────────┘
                           │ WS Events / Notes Sync        │
                           ▼                               │
     ┌─────────────────────────────────────────────────────┴──────────────────┐
     │                       FRONTEND INTERACTIVO (WEB)                       │
     │                                                                        │
     │   ┌────────────────────────────────────────────────────────────────┐   │
     │   │ Capa 3: SVG Overlay (100% ancho = PDF + Margen extendido)      │   │
     │   │         • Cuadrícula A1, B2... (pointer-events: none)          │   │
     │   │         • Resaltados vectoriales (mix-blend-mode: multiply)    │   │
     │   │         • Esquemas y árboles Dagre.js (Bézier + auto-layout)   │   │
     │   │         • Llaves verticales { con etiquetas de agrupación      │   │
     │   │         • Sellos ⚠️, 👁️, ⭐ en celdas o cabeceras             │   │
     │   │         • Repaso Activo (Active Recall con desenfoque suave)   │   │
     │   ├────────────────────────────────────────────────────────────────┤   │
     │   │ Capa 2: TextLayer nativo de PDF.js (selección y desambiguación)│   │
     │   ├────────────────────────────────────────────────────────────────┤   │
     │   │ Capa 1: Canvas de PDF.js (0 a ancho original del documento)    │   │
     │   └────────────────────────────────────────────────────────────────┘   │
     └────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 2. Puesta en Marcha Rápida

### Requisitos Previos
- Python 3.10+
- Entorno virtual con `fastapi`, `uvicorn`, `websockets`, `pymupdf` (ya disponible en `.venv`)

### Iniciar el Servidor
```bash
cd /home/jloslop/gemini-live-assistant/visor_apuntes
./run.sh
```
O directamente con Python:
```bash
/home/jloslop/gemini-live-assistant/.venv/bin/python main.py
```

Acceso web:
- **Visor interactivo:** [http://127.0.0.1:8766](http://127.0.0.1:8766)
- **Esquemas Function Calling:** [http://127.0.0.1:8766/api/tools](http://127.0.0.1:8766/api/tools)
- **Canal WebSocket:** `ws://127.0.0.1:8766/ws/commands`

### Ejecución de Pruebas Automatizadas
```bash
/home/jloslop/gemini-live-assistant/.venv/bin/python test_suite.py
```

---

## 🛠️ 3. Catálogo de Herramientas (Function Calling para Gemini Live)

Las herramientas se encuentran documentadas en formato estándar JSON-Schema en `function_calling_schemas.json` y se exponen en `/api/tools`:

| Herramienta | Parámetros Clave | Descripción |
|---|---|---|
| `activate_grid` | `show: bool` | Muestra u oculta la cuadrícula alfanumérica de referencia (A1, B2, J3...). |
| `highlight_passage` | `target_text: str`, `color?: str`, `page?: int` | Localiza y subraya texto con mezcla multiplicativa. Si hay varios párrafos idénticos, desambigua eligiendo el más próximo al cursor del ratón. |
| `create_schema` | `anchor_cell: str`, `root_title: str`, `nodes: []`, `edges: []`, `orientation?: str` | Genera un árbol jerárquico no solapado en el margen con Dagre.js (cajas dinámicas y curvas Bézier con flechas). |
| `add_schema_branch` | `schema_id: str`, `parent_node_id: str`, `new_node: {}` | Añade dinámicamente un nodo a un árbol existente recalculando el layout de forma fluida. |
| `add_margin_note` | `cell: str`, `text: str`, `note_type: str` | Inserta una tarjeta o post-it en el margen (`warning` ⚠️, `info` 📌, `tip` 💡, `exam` 👁️). |
| `add_bracket_group`| `start_cell: str`, `end_cell: str`, `label: str` | Proyecta una llave vertical `{` que agrupa un rango de líneas con etiqueta en su punta. |
| `add_stamp_symbol` | `cell: str`, `symbol: str`, `label?: str` | Estampa insignias rápidas en celdas (⚠️, 👁️, ⭐, 🎯, ⚖️). |
| `toggle_active_recall` | `enabled: bool` | Oculta visualmente definiciones y nodos secundarios con desenfoque para autoevaluación memorística (se revelan al pasar el ratón). |
| `undo_last_action` | *(sin argumentos)* | Deshace la última intervención del stack de notas. |

---

## 📐 4. Arquitectura de Coordenadas y Espacio Vectorial

- **Espacio Normalizado:** Todas las coordenadas se guardan en **puntos nativos de PDF** (72 pt = 1 pulgada).
- **Invarianza de Zoom:** El SVG utiliza `viewBox="0 0 anchoTotal alto"`. Al hacer zoom (75% a 250%), las notas, esquemas, flechas y llaves escalan con nitidez vectorial perfecta sin desalinearse ni una sola milésima de punto.
- **Auto-Snap al Margen:** Cuando un comando solicita crear un esquema o nota de margen indicando una celda dentro del texto del documento (ej. `E1` o `F4`), el sistema respeta la fila vertical pero proyecta automáticamente el origen hacia el comienzo del margen extendido (`ancho_original + 15 pt`).
- **Exportación Fiel (WYSIWYG):** El motor PyMuPDF lee exactamente los mismos puntos calculados por el visor, garantizando que el PDF compilado final (`sample_anotado.pdf`) sea idéntico a lo visualizado en pantalla.

---

## ⌨️ 5. Atajos de Teclado y Simulador Integrado

- **`G`**: Alternar cuadrícula alfanumérica.
- **`R`**: Alternar modo repaso activo (Active Recall).
- **`Ctrl + Z` / `Cmd + Z`**: Deshacer última acción.
- **`+` / `−`**: Acercar o alejar zoom.
- **Simulador HUD (Superior):** Incluye chips rápidos para probar todas las herramientas con un solo clic y un campo de entrada para enviar payloads JSON personalizados.

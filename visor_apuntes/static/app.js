/**
 * Visor y Editor de Apuntes Manos Libres - DeltaOS
 * 
 * Arquitectura de Capas Apiladas:
 * Capa 1: Canvas nativo de PDF.js (0 a ancho_original)
 * Capa 2: TextLayer nativo de PDF.js (detección geométrica y selección)
 * Capa 3: Capa Vectorial SVG Superior (PDF + Margen extendido, espacio de puntos nativo 1:1)
 *
 * Motor de Grafos: Dagre.js (cálculo de dimensiones, layout jerárquico y curvas Bézier)
 * Comunicación: WebSocket bidireccional y persistencia no destructiva en Sidecar JSON
 */

// Configuración del worker de PDF.js
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

// Constantes espaciales en Puntos PDF (72 pt/pulgada)
const MARGIN_LEFT_PT = 220;    // Ancho del margen lateral izquierdo (sellos, marcas, llaves)
const MARGIN_RIGHT_PT = 380;   // Ancho del margen lateral derecho (esquemas Dagre, notas de estudio)
let CELL_WIDTH = 55;          // Ancho de columna alfanumérica
let CELL_HEIGHT = 20;         // Alto base adaptado a la separación de líneas del texto

// Mapeo amigable de nombres de colores a valores HEX
const COLOR_MAP = {
  'amarillo': '#fef08a',
  'yellow': '#fef08a',
  'verde': '#bbf7d0',
  'green': '#bbf7d0',
  'azul': '#bae6fd',
  'blue': '#bae6fd',
  'rojo': '#ef4444',
  'red': '#ef4444',
  'rosa': '#fbcfe8',
  'pink': '#fbcfe8',
  'naranja': '#fed7aa',
  'orange': '#fed7aa',
  'morado': '#e9d5ff',
  'purple': '#e9d5ff',
  'turquesa': '#a5f3fc',
  'cyan': '#a5f3fc',
  'gris': '#94a3b8',
  'gray': '#94a3b8'
};

function resolveColor(col, defaultColor = '#fef08a') {
  if (!col) return defaultColor;
  const lower = String(col).trim().toLowerCase();
  return COLOR_MAP[lower] || col;
}

// Estado reactivo global
const state = {
  docId: 'sample.pdf',
  pdfDoc: null,
  scale: 1.25,
  showGrid: true,
  activeRecall: false,
  activeTool: 'highlighter',
  activeHighlightColor: '#fef08a',
  currentPage: 1,
  cursorContext: {
    page: 1,
    cell: 'A1',
    pos: [0, 0],         // Coordenadas en puntos PDF sin escalar
    posScreen: [0, 0],   // Coordenadas en píxeles del viewport
    nearestText: ''
  },
  notes: {
    document_id: 'sample.pdf',
    version: 1,
    pages: {}
  },
  historyStack: [],
  ws: null,
  pageViewports: {},  // Metadatos de dimensiones por página
  pageLineSpacing: {} // Separación exacta de líneas detectada por página
};

function getPageRowHeight(pageNum = 1) {
  return state.pageLineSpacing[pageNum] || CELL_HEIGHT;
}

// Canvas auxiliar para medición exacta de texto
const measureCanvas = document.createElement('canvas');
const measureCtx = measureCanvas.getContext('2d');

function measureText(text, font = '11px "Plus Jakarta Sans"') {
  measureCtx.font = font;
  return measureCtx.measureText(text || '').width;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sistema de Coordenadas y Conversión de Celdas (Adaptado a Líneas)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Convierte un nombre de celda alfanumérica (ej: "A1", "F4", "J2", "R16") a coordenadas (X, Y) en puntos.
 * Si isMarginTarget es true y la columna cae dentro del texto original del PDF,
 * auto-proyecta la X al comienzo del margen derecho manteniendo la fila Y.
 */
function cellToCoords(cellStr, pdfPtWidth = 595, isMarginTarget = false, pageNum = 1) {
  const rightMarginStart = MARGIN_LEFT_PT + pdfPtWidth;
  if (!cellStr || typeof cellStr !== 'string') {
    return { x: isMarginTarget ? rightMarginStart + 15 : 20, y: 20 };
  }
  const match = cellStr.toUpperCase().trim().match(/^([A-Z]+)(\d+)$/);
  if (!match) {
    return { x: isMarginTarget ? rightMarginStart + 15 : 20, y: 20 };
  }

  const letters = match[1];
  const row = Math.max(1, parseInt(match[2], 10)) - 1;
  const rowH = getPageRowHeight(pageNum);

  // Convertir columna alfanumérica (A=0, B=1 ... Z=25, AA=26)
  let col = 0;
  for (let i = 0; i < letters.length; i++) {
    col = col * 26 + (letters.charCodeAt(i) - 64);
  }
  col -= 1;

  let x = col * CELL_WIDTH;
  const y = Math.round(row * rowH);

  if (isMarginTarget && x < rightMarginStart && x >= MARGIN_LEFT_PT) {
    x = rightMarginStart + 15;
  }

  return { x, y };
}

/**
 * Convierte coordenadas (X, Y) en puntos PDF a su etiqueta alfanumérica correspondiente,
 * adaptada a la altura de línea de texto de la página.
 */
function coordsToCell(x, y, pageNum = 1) {
  const rowH = getPageRowHeight(pageNum);
  const col = Math.max(0, Math.floor(x / CELL_WIDTH));
  const row = Math.max(0, Math.floor(y / rowH)) + 1;

  let letters = '';
  let tempCol = col + 1;
  while (tempCol > 0) {
    const rem = (tempCol - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    tempCol = Math.floor((tempCol - 1) / 26);
  }

  return `${letters}${row}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Inicialización de la Aplicación y Carga del Documento
// ─────────────────────────────────────────────────────────────────────────────

async function initApp() {
  setupUIListeners();
  setupWebSocket();
  await refreshDocumentList();
  await loadDocument(state.docId);
}

let currentRenderToken = 0;
let pageObserver = null;

async function refreshDocumentList() {
  try {
    const resp = await fetch('/api/documents');
    if (resp.ok) {
      const data = await resp.json();
      const select = document.getElementById('doc-select');
      if (!select) return;
      select.innerHTML = '';
      (data.documents || []).forEach(doc => {
        const opt = document.createElement('option');
        opt.value = doc;
        opt.textContent = doc;
        if (doc === state.docId) opt.selected = true;
        select.appendChild(opt);
      });
      if (state.docId) {
        select.value = state.docId;
      }
    }
  } catch (e) {
    console.warn('Error al obtener lista de documentos:', e);
  }
}

async function loadDocument(docId) {
  const renderToken = ++currentRenderToken;
  state.docId = docId;
  const select = document.getElementById('doc-select');
  if (select && select.value !== docId) {
    select.value = docId;
  }

  const container = document.getElementById('pdf-container');
  container.innerHTML = '<div style="color: #64748b; padding: 40px; font-size: 14px; text-align: center;">Cargando documento PDF y notas...</div>';

  try {
    // 1. Cargar datos del sidecar JSON de notas
    try {
      const resp = await fetch(`/api/notes/${encodeURIComponent(docId)}`);
      if (resp.ok) {
        const loaded = await resp.json();
        if (loaded && typeof loaded === 'object') {
          state.notes = loaded;
        }
      }
    } catch (e) {
      console.warn('No se pudieron cargar notas sidecar iniciales:', e);
    }

    if (!state.notes || typeof state.notes !== 'object') {
      state.notes = { document_id: docId, version: 1, pages: {} };
    }
    if (!state.notes.pages || typeof state.notes.pages !== 'object') {
      state.notes.pages = {};
    }

    // 2. Cargar el PDF mediante PDF.js
    const loadingTask = pdfjsLib.getDocument(`/api/pdf/${encodeURIComponent(docId)}`);
    state.pdfDoc = await loadingTask.promise;
    if (renderToken !== currentRenderToken) return;

    container.innerHTML = '';
    const numPages = state.pdfDoc.numPages;

    // Configurar observador de visibilidad de páginas para sincronizar el HUD al hacer scroll
    if (pageObserver) pageObserver.disconnect();
    pageObserver = new IntersectionObserver((entries) => {
      let maxRatio = 0;
      let visiblePage = null;
      entries.forEach(entry => {
        if (entry.isIntersecting && entry.intersectionRatio > maxRatio) {
          maxRatio = entry.intersectionRatio;
          visiblePage = parseInt(entry.target.dataset.page, 10);
        }
      });
      if (visiblePage && visiblePage !== state.currentPage) {
        state.currentPage = visiblePage;
        state.cursorContext.page = visiblePage;
        updateHUD();
      }
    }, { threshold: [0.15, 0.5, 0.85] });

    // Badge flotante de progreso de renderizado progresivo para documentos multipágina
    let progressBadge = null;
    if (numPages > 1) {
      progressBadge = document.createElement('div');
      progressBadge.id = 'render-progress';
      progressBadge.style.cssText = 'position: fixed; bottom: 18px; right: 18px; background: rgba(17, 17, 17, 0.92); color: #94a3b8; padding: 6px 14px; border-radius: 20px; font-size: 11.5px; font-family: var(--mono); border: 1px solid var(--border-visible); z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.4); pointer-events: none; transition: opacity 0.3s;';
      progressBadge.textContent = `Páginas: 1 de ${numPages}...`;
      document.body.appendChild(progressBadge);
    }

    // 3. Renderizar solo la página actual
    await renderPage(state.currentPage);
    console.log(`PDF '${docId}' cargado correctamente en la página ${state.currentPage}.`);
  } catch (error) {
    if (renderToken !== currentRenderToken) return;
    console.error('Error cargando PDF:', error);
    container.innerHTML = `<div style="color: #ef4444; padding: 40px; font-size: 14px; text-align: center;">Error al cargar PDF: ${error.message}</div>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Renderizado por Página (Stacked Layer Architecture)
// ─────────────────────────────────────────────────────────────────────────────

async function renderPage(pageNum) {
  const container = document.getElementById('pdf-container');
  const page = await state.pdfDoc.getPage(pageNum);

  // Viewport unscaled (escala 1.0 = puntos nativos PDF)
  const unscaledViewport = page.getViewport({ scale: 1.0 });
  const pdfPtWidth = unscaledViewport.width;
  const pdfPtHeight = unscaledViewport.height;
  const totalPtWidth = MARGIN_LEFT_PT + pdfPtWidth + MARGIN_RIGHT_PT;

  state.pageViewports[pageNum] = {
    pdfPtWidth,
    pdfPtHeight,
    totalPtWidth
  };

  // Dimensiones renderizadas en píxeles de pantalla según el zoom
  const screenScale = state.scale;
  const screenWidth = totalPtWidth * screenScale;
  const screenHeight = pdfPtHeight * screenScale;
  const marginLeftScreenWidth = MARGIN_LEFT_PT * screenScale;
  const pdfScreenWidth = pdfPtWidth * screenScale;
  const rightMarginStartX = marginLeftScreenWidth + pdfScreenWidth;

  // Contenedor principal de la página
  const pageDiv = document.createElement('div');
  pageDiv.className = 'page-container';
  pageDiv.id = `page-container-${pageNum}`;
  pageDiv.dataset.page = pageNum;
  pageDiv.style.width = `${screenWidth}px`;
  pageDiv.style.height = `${screenHeight}px`;

  // Línea divisoria izquierda (Margen Izquierdo <-> PDF)
  const dividerLeft = document.createElement('div');
  dividerLeft.className = 'margin-divider margin-divider-left';
  dividerLeft.style.left = '0px';
  dividerLeft.style.width = `${marginLeftScreenWidth}px`;
  pageDiv.appendChild(dividerLeft);

  // Línea divisoria derecha (PDF <-> Margen Derecho)
  const dividerRight = document.createElement('div');
  dividerRight.className = 'margin-divider margin-divider-right';
  dividerRight.style.left = `${rightMarginStartX}px`;
  dividerRight.style.right = '0px';
  pageDiv.appendChild(dividerRight);

  // Capa 1: Canvas del PDF original (centrado entre márgenes)
  const canvas = document.createElement('canvas');
  canvas.className = 'pdf-canvas';
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(pdfScreenWidth * dpr);
  canvas.height = Math.round(screenHeight * dpr);
  canvas.style.left = `${marginLeftScreenWidth}px`;
  canvas.style.top = '0px';
  canvas.style.width = `${pdfScreenWidth}px`;
  canvas.style.height = `${screenHeight}px`;
  pageDiv.appendChild(canvas);

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const renderViewport = page.getViewport({ scale: screenScale });
  await page.render({ canvasContext: ctx, viewport: renderViewport }).promise;

  // Capa 2: TextLayer nativo de PDF.js para selección y desambiguación espacial (centrado sobre el Canvas)
  const textLayerDiv = document.createElement('div');
  textLayerDiv.className = 'textLayer';
  textLayerDiv.style.left = `${marginLeftScreenWidth}px`;
  textLayerDiv.style.top = '0px';
  textLayerDiv.style.width = `${pdfScreenWidth}px`;
  textLayerDiv.style.height = `${screenHeight}px`;
  textLayerDiv.style.setProperty('--scale-factor', screenScale);
  pageDiv.appendChild(textLayerDiv);

  const textContent = await page.getTextContent();
  const textLayerRender = pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayerDiv,
    viewport: renderViewport,
    textDivs: []
  });
  if (textLayerRender && textLayerRender.promise) {
    await textLayerRender.promise;
  }

  // Capa 3: Capa Vectorial SVG Superior (Cubre el 100% del contenedor: PDF + Margen)
  // El viewBox está fijado en puntos nativos (totalPtWidth x pdfPtHeight),
  // por lo que todas las coordenadas de anotaciones son inmunes al zoom.
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'overlay-svg');
  svg.setAttribute('viewBox', `0 0 ${totalPtWidth} ${pdfPtHeight}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.dataset.page = pageNum;
  svg.dataset.pdfPtWidth = pdfPtWidth;

  // Definición de filtros y marcadores de flecha para Dagre
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML = `
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#475569" />
    </marker>
    <filter id="card-shadow" x="-10%" y="-10%" width="130%" height="130%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.08" />
    </filter>
  `;
  svg.appendChild(defs);

  // Sub-capas SVG en orden de apilamiento
  const gridGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  gridGroup.setAttribute('class', `grid-layer ${state.showGrid ? '' : 'grid-hidden'}`);
  svg.appendChild(gridGroup);

  const highlightsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  highlightsGroup.setAttribute('class', 'highlights-layer');
  svg.appendChild(highlightsGroup);

  const bracketsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  bracketsGroup.setAttribute('class', 'brackets-layer');
  svg.appendChild(bracketsGroup);

  const stampsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  stampsGroup.setAttribute('class', 'stamps-layer');
  svg.appendChild(stampsGroup);

  const schemasGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  schemasGroup.setAttribute('class', 'schemas-layer');
  svg.appendChild(schemasGroup);

  const notesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  notesGroup.setAttribute('class', 'notes-layer');
  svg.appendChild(notesGroup);

  pageDiv.appendChild(svg);
  container.appendChild(pageDiv);
  if (pageObserver) pageObserver.observe(pageDiv);

  // Renderizar la cuadrícula alfanumérica adaptada exactamente a las líneas de esta página
  renderGrid(gridGroup, totalPtWidth, pdfPtHeight, pageDiv, pageNum);

  // Renderizar todas las anotaciones persistidas de la página
  renderPageAnnotations(pageNum, svg, pdfPtWidth);

  // Seguimiento contextual del cursor del ratón sobre la página
  setupMouseTracking(pageDiv, pageNum, textLayerDiv, pdfPtWidth);

  // Herramienta de subrayado manual interactivo con el ratón
  setupTextSelectionHighlighting(pageDiv, pageNum, pdfPtWidth);
}

// ─────────────────────────────────────────────────────────────────────────────
// Cuadrícula Alfanumérica Adaptada a la Separación de Líneas
// ─────────────────────────────────────────────────────────────────────────────

function calculateLineSeparation(pageContainer, pdfPtHeight) {
  const textLayer = pageContainer.querySelector('.textLayer');
  if (!textLayer) return 20;
  const spans = Array.from(textLayer.querySelectorAll('span'));
  if (spans.length < 2) return 20;

  const pageRect = pageContainer.getBoundingClientRect();
  const scaleY = pageRect.height > 0 ? (pageRect.height / pdfPtHeight) : state.scale;

  const yPositions = [];
  spans.forEach(s => {
    const cr = s.getBoundingClientRect();
    if (cr.width > 2 && cr.height > 2) {
      const ptY = (cr.top - pageRect.top) / scaleY;
      yPositions.push(Math.round(ptY));
    }
  });

  yPositions.sort((a, b) => a - b);
  const clusters = [];
  yPositions.forEach(y => {
    if (clusters.length === 0 || y - clusters[clusters.length - 1].avg > 5) {
      clusters.push({ sum: y, count: 1, avg: y });
    } else {
      const last = clusters[clusters.length - 1];
      last.sum += y;
      last.count += 1;
      last.avg = Math.round(last.sum / last.count);
    }
  });

  const lineYs = clusters.map(c => c.avg);
  const diffs = [];
  for (let i = 0; i < lineYs.length - 1; i++) {
    const d = lineYs[i+1] - lineYs[i];
    if (d >= 12 && d <= 32) diffs.push(d);
  }
  diffs.sort((a, b) => a - b);
  if (diffs.length > 0) {
    const median = diffs[Math.floor(diffs.length / 2)];
    if (median >= 14 && median <= 28) return Math.round(median);
  }
  return 20;
}

function renderGrid(group, width, height, pageContainer, pageNum) {
  group.innerHTML = '';
  const rowH = calculateLineSeparation(pageContainer, height);
  state.pageLineSpacing[pageNum] = rowH;

  const cols = Math.ceil(width / CELL_WIDTH);
  const rows = Math.ceil(height / rowH);

  // Líneas verticales
  for (let c = 0; c <= cols; c++) {
    const x = Math.min(width, c * CELL_WIDTH);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x);
    line.setAttribute('y1', 0);
    line.setAttribute('x2', x);
    line.setAttribute('y2', height);
    line.setAttribute('class', 'grid-line');
    group.appendChild(line);
  }

  // Líneas horizontales adaptadas a las líneas de texto
  for (let r = 0; r <= rows; r++) {
    const y = Math.min(height, r * rowH);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', 0);
    line.setAttribute('y1', y);
    line.setAttribute('x2', width);
    line.setAttribute('y2', y);
    line.setAttribute('class', 'grid-line grid-line-row');
    group.appendChild(line);

    // Gutter izquierdo: Indicador de línea/fila
    if (r < rows) {
      const numLeft = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      numLeft.setAttribute('x', 6);
      numLeft.setAttribute('y', y + rowH - 4);
      numLeft.setAttribute('class', 'grid-gutter-num');
      numLeft.textContent = `L${r + 1}`;
      group.appendChild(numLeft);

      // Gutter derecho: Indicador de línea/fila
      const numRight = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      numRight.setAttribute('x', width - 24);
      numRight.setAttribute('y', y + rowH - 4);
      numRight.setAttribute('class', 'grid-gutter-num');
      numRight.textContent = `L${r + 1}`;
      group.appendChild(numRight);
    }
  }

  // Celdas y etiquetas alfanuméricas
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const cellX = c * CELL_WIDTH;
      const cellY = r * rowH;
      const cellW = Math.min(CELL_WIDTH, width - cellX);
      const cellH = Math.min(rowH, height - cellY);
      if (cellW <= 0 || cellH <= 0) continue;

      const cellLabel = coordsToCell(cellX, cellY, pageNum);

      const box = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      box.setAttribute('x', cellX);
      box.setAttribute('y', cellY);
      box.setAttribute('width', cellW);
      box.setAttribute('height', cellH);
      box.setAttribute('class', 'grid-cell-box');
      box.dataset.cell = cellLabel;
      group.appendChild(box);

      // Etiqueta alfanumérica sutil
      if (c === 0 || c === 4 || c === Math.floor(cols / 2) || c === cols - 1 || (r + 1) % 5 === 0) {
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', cellX + 4);
        text.setAttribute('y', cellY + Math.min(13, rowH - 3));
        text.setAttribute('class', 'grid-label');
        text.textContent = cellLabel;
        group.appendChild(text);
      }
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Seguimiento Contextual del Ratón y Desambiguación
// ─────────────────────────────────────────────────────────────────────────────

let lastWsContextSend = 0;

function setupMouseTracking(pageDiv, pageNum, textLayerDiv, pdfPtWidth) {
  const viewportInfo = state.pageViewports[pageNum] || { totalPtWidth: 1195, pdfPtHeight: 842 };
  const totalPtWidth = viewportInfo.totalPtWidth || (MARGIN_LEFT_PT + pdfPtWidth + MARGIN_RIGHT_PT);
  const pdfPtHeight = viewportInfo.pdfPtHeight || 842;
  const marginLeftScreenWidth = MARGIN_LEFT_PT * state.scale;

  pageDiv.addEventListener('mousemove', (e) => {
    const rect = pageDiv.getBoundingClientRect();
    const screenX = e.clientX - rect.left;
    const screenY = e.clientY - rect.top;

    // Normalización exacta a puntos PDF acorde al viewBox nativo de la superficie
    const scaleX = rect.width > 0 ? (rect.width / totalPtWidth) : state.scale;
    const scaleY = rect.height > 0 ? (rect.height / pdfPtHeight) : state.scale;

    const ptX = Math.max(0, Math.min(totalPtWidth, Math.round(screenX / scaleX)));
    const ptY = Math.max(0, Math.min(pdfPtHeight, Math.round(screenY / scaleY)));

    const cell = coordsToCell(ptX, ptY);
    state.currentPage = pageNum;
    state.cursorContext = {
      page: pageNum,
      cell: cell,
      pos: [ptX, ptY],
      posScreen: [Math.round(screenX), Math.round(screenY)],
      nearestText: findNearestText(screenX, screenY, textLayerDiv, marginLeftScreenWidth)
    };

    updateHUD();

    // Notificar al backend vía WebSocket con throttling a 100ms
    const now = Date.now();
    if (now - lastWsContextSend > 100 && state.ws && state.ws.readyState === WebSocket.OPEN) {
      lastWsContextSend = now;
      state.ws.send(JSON.stringify({
        type: 'mouse_context',
        doc_id: state.currentDocId || 'sample.pdf',
        page: pageNum,
        nearest_cell: cell,
        mouse_pos: state.cursorContext.pos,
        nearest_text: state.cursorContext.nearestText,
        timestamp: now
      }));
    }
  });
}

function findNearestText(screenX, screenY, textLayerDiv, marginLeftScreenWidth = 0) {
  const spans = textLayerDiv.querySelectorAll('span');
  if (!spans.length) return '';

  let minDist = Infinity;
  let nearestStr = '';

  for (let i = 0; i < spans.length; i++) {
    const s = spans[i];
    const text = s.textContent.trim();
    if (!text || text.length < 3) continue;

    const sLeft = (parseFloat(s.style.left) || 0) + marginLeftScreenWidth;
    const sTop = parseFloat(s.style.top) || 0;
    const sWidth = parseFloat(s.style.width) || (text.length * 7);
    const sHeight = parseFloat(s.style.fontSize) || 12;

    const cx = sLeft + sWidth / 2;
    const cy = sTop + sHeight / 2;
    const dist = Math.hypot(screenX - cx, screenY - cy);

    if (dist < minDist) {
      minDist = dist;
      nearestStr = text;
    }
  }

  return nearestStr.length > 45 ? nearestStr.substring(0, 45) + '…' : nearestStr;
}

// ─────────────────────────────────────────────────────────────────────────────
// Herramientas de Subrayado y Borrado Interactivo con Ratón
// ─────────────────────────────────────────────────────────────────────────────

function deleteHighlight(hlId, pageNum) {
  const pageKey = String(pageNum);
  if (!state.notes || !state.notes.pages || !state.notes.pages[pageKey]) return;
  const pdata = state.notes.pages[pageKey];
  if (!Array.isArray(pdata.highlights)) return;

  const prevLen = pdata.highlights.length;
  pdata.highlights = pdata.highlights.filter(h => h.id !== hlId);
  if (pdata.highlights.length !== prevLen) {
    refreshCurrentPageSvg(pageNum);
    saveNotesToServer();
  }
}

function setupTextSelectionHighlighting(pageDiv, pageNum, pdfPtWidth) {
  pageDiv.addEventListener('mouseup', () => {
    if (state.activeTool !== 'highlighter') return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;

    const selectedText = selection.toString().trim();
    if (!selectedText) return;

    const range = selection.getRangeAt(0);
    const clientRects = range.getClientRects();
    if (!clientRects || clientRects.length === 0) return;

    const pageRect = pageDiv.getBoundingClientRect();
    const viewportInfo = state.pageViewports[pageNum] || { totalPtWidth: 1195, pdfPtHeight: 842 };
    const totalPtWidth = viewportInfo.totalPtWidth || (MARGIN_LEFT_PT + pdfPtWidth + MARGIN_RIGHT_PT);
    const pdfPtHeight = viewportInfo.pdfPtHeight || 842;

    const scaleX = pageRect.width > 0 ? (pageRect.width / totalPtWidth) : state.scale;
    const scaleY = pageRect.height > 0 ? (pageRect.height / pdfPtHeight) : state.scale;

    const rects = [];
    for (let i = 0; i < clientRects.length; i++) {
      const cr = clientRects[i];
      const x1 = Math.max(0, Math.min(totalPtWidth, (cr.left - pageRect.left) / scaleX));
      const y1 = Math.max(0, Math.min(pdfPtHeight, (cr.top - pageRect.top) / scaleY));
      const x2 = Math.max(0, Math.min(totalPtWidth, (cr.right - pageRect.left) / scaleX));
      const y2 = Math.max(0, Math.min(pdfPtHeight, (cr.bottom - pageRect.top) / scaleY));
      if (x2 - x1 > 2 && y2 - y1 > 2) {
        rects.push([Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)]);
      }
    }

    if (rects.length > 0) {
      const pageKey = String(pageNum);
      if (!state.notes.pages[pageKey]) {
        state.notes.pages[pageKey] = {
          highlights: [],
          annotations: [],
          brackets: [],
          stamps: [],
          schemas: []
        };
      }
      const pdata = state.notes.pages[pageKey];
      if (!Array.isArray(pdata.highlights)) pdata.highlights = [];

      pdata.highlights.push({
        id: `hl_${Date.now()}`,
        text: selectedText,
        color: state.activeHighlightColor || '#fef08a',
        rects: rects
      });

      refreshCurrentPageSvg(pageNum);
      saveNotesToServer();
      selection.removeAllRanges();
    }
  });
}

function updateHUD() {
  document.getElementById('hud-page').innerHTML = `Pág: <strong>${state.cursorContext.page}</strong>`;
  document.getElementById('hud-cell').innerHTML = `Celda: <strong class="badge-cell">${state.cursorContext.cell}</strong>`;
  document.getElementById('hud-coords').textContent = `(${state.cursorContext.pos[0]}, ${state.cursorContext.pos[1]}) pt`;
  document.getElementById('hud-text').innerHTML = `Texto: <em>${state.cursorContext.nearestText || 'ninguno'}</em>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Motor de Esquemas Jerárquicos con Dagre.js
// ─────────────────────────────────────────────────────────────────────────────

function renderSchemaTree(schemasGroup, schema, pdfPtWidth) {
  if (!schema) return;
  const rawNodes = schema.nodes || schema.layout_nodes || [];
  if (!rawNodes.length) return;

  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: schema.orientation || 'TB',
    nodesep: 25,
    ranksep: 35,
    marginx: 10,
    marginy: 10
  });
  g.setDefaultEdgeLabel(() => ({}));

  // 1. Añadir nodos al grafo midiendo dinámicamente sus dimensiones con measureText
  rawNodes.forEach((n, idx) => {
    const isRoot = idx === 0;
    const label = n.label || n.title || 'Nodo';
    const titleWidth = measureText(label, isRoot ? 'bold 12px "Plus Jakarta Sans"' : '600 11px "Plus Jakarta Sans"');
    const details = Array.isArray(n.details) ? n.details : [];
    let maxDetailWidth = 0;
    details.forEach(d => {
      const w = measureText(String(d), '9.5px "Plus Jakarta Sans"');
      if (w > maxDetailWidth) maxDetailWidth = w;
    });

    const boxWidth = Math.max(130, Math.max(titleWidth, maxDetailWidth) + 26);
    const boxHeight = 32 + (details.length * 16);

    g.setNode(n.id || `node_${idx}`, {
      id: n.id || `node_${idx}`,
      label: label,
      details: details,
      width: boxWidth,
      height: boxHeight,
      isRoot: isRoot
    });
  });

  // 2. Añadir aristas
  const rawEdges = schema.edges || schema.layout_edges || [];
  rawEdges.forEach(e => {
    if (e && e.from && e.to) {
      g.setEdge(e.from, e.to);
    }
  });

  // 3. Ejecutar layout libre de colisiones
  try {
    dagre.layout(g);
  } catch (layoutErr) {
    console.warn('Error calculando layout Dagre:', layoutErr);
    return;
  }

  // 4. Anclaje espacial (si cae en el texto, se auto-proyecta al margen extendido)
  const isLeft = schema.side === 'left';
  const defaultX = isLeft ? 15 : (MARGIN_LEFT_PT + pdfPtWidth + 15);
  let anchor;
  if (schema.anchor_y !== undefined) {
    anchor = { x: defaultX, y: schema.anchor_y };
  } else if (schema.anchor_cell) {
    anchor = cellToCoords(schema.anchor_cell, pdfPtWidth, true);
    if (isLeft) anchor.x = 15;
  } else {
    anchor = { x: defaultX, y: 60 };
  }
  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', `schema-tree ${schema.id || ''}`);
  group.setAttribute('transform', `translate(${anchor.x}, ${anchor.y})`);

  // Guardar datos calculados de nodos y aristas en puntos para PyMuPDF
  schema.layout_nodes = [];
  schema.layout_edges = [];

  // 5. Dibujar Aristas (Curvas Bézier con flechas)
  (g.edges() || []).forEach(e => {
    const edge = g.edge(e);
    const points = edge ? edge.points : null;
    if (!points || points.length < 2) return;

    schema.layout_edges.push({
      from: e.v,
      to: e.w,
      points: points.map(p => ({ x: Math.round(p.x + anchor.x), y: Math.round(p.y + anchor.y) }))
    });

    let d = `M ${points[0].x} ${points[0].y}`;
    if (points.length === 3) {
      d += ` Q ${points[1].x} ${points[1].y}, ${points[2].x} ${points[2].y}`;
    } else if (points.length >= 4) {
      d += ` C ${points[1].x} ${points[1].y}, ${points[2].x} ${points[2].y}, ${points[3].x} ${points[3].y}`;
    } else {
      for (let i = 1; i < points.length; i++) {
        d += ` L ${points[i].x} ${points[i].y}`;
      }
    }

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('class', 'schema-edge');
    path.setAttribute('marker-end', 'url(#arrow)');
    group.appendChild(path);
  });

  // 6. Dibujar Nodos (Tarjetas auto-adaptativas)
  (g.nodes() || []).forEach(nodeId => {
    const node = g.node(nodeId);
    if (!node) return;

    const x = node.x - node.width / 2;
    const y = node.y - node.height / 2;

    schema.layout_nodes.push({
      id: nodeId,
      label: node.label,
      details: node.details,
      isRoot: node.isRoot,
      x: Math.round(x + anchor.x),
      y: Math.round(y + anchor.y),
      width: Math.round(node.width),
      height: Math.round(node.height)
    });

    const nodeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    nodeG.setAttribute('class', `schema-node ${node.isRoot ? 'root-node' : ''}`);
    nodeG.setAttribute('transform', `translate(${x}, ${y})`);
    nodeG.dataset.nodeId = nodeId;

    // Caja de fondo
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('width', node.width);
    rect.setAttribute('height', node.height);
    rect.setAttribute('class', `node-card ${node.isRoot ? 'root-card' : ''}`);
    nodeG.appendChild(rect);

    // Título del nodo
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    title.setAttribute('x', 10);
    title.setAttribute('y', 19);
    title.setAttribute('class', `node-label ${node.isRoot ? 'root-label' : ''}`);
    title.textContent = node.label;
    nodeG.appendChild(title);

    // Viñetas o detalles
    if (node.details && node.details.length) {
      node.details.forEach((det, dIdx) => {
        const dText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        dText.setAttribute('x', 14);
        dText.setAttribute('y', 36 + (dIdx * 15));
        dText.setAttribute('class', 'node-detail-line');
        dText.textContent = `• ${det}`;
        nodeG.appendChild(dText);
      });
    }

    group.appendChild(nodeG);
  });

  schemasGroup.appendChild(group);
}

// ─────────────────────────────────────────────────────────────────────────────
// Renderizado de Anotaciones Específicas
// ─────────────────────────────────────────────────────────────────────────────

function renderPageAnnotations(pageNum, svg, pdfPtWidth) {
  if (!state.notes || !state.notes.pages) return;
  const pageKey = String(pageNum);
  const pdata = state.notes.pages[pageKey];
  if (!pdata) return;

  const highlightsGroup = svg.querySelector('.highlights-layer');
  const bracketsGroup = svg.querySelector('.brackets-layer');
  const stampsGroup = svg.querySelector('.stamps-layer');
  const schemasGroup = svg.querySelector('.schemas-layer');
  const notesGroup = svg.querySelector('.notes-layer');

  if (highlightsGroup) highlightsGroup.innerHTML = '';
  if (bracketsGroup) bracketsGroup.innerHTML = '';
  if (stampsGroup) stampsGroup.innerHTML = '';
  if (schemasGroup) schemasGroup.innerHTML = '';
  if (notesGroup) notesGroup.innerHTML = '';

  // 1. Resaltados, Subrayados, Recuadros y Tachados
  if (highlightsGroup && Array.isArray(pdata.highlights)) {
    pdata.highlights.forEach(hl => {
      if (Array.isArray(hl.rects)) {
        const style = hl.style || 'solid_highlight';
        const color = resolveColor(hl.color, '#fef08a');

        hl.rects.forEach(r => {
          if (!Array.isArray(r) || r.length < 4) return;
          const x1 = r[0], y1 = r[1], x2 = r[2], y2 = r[3];
          const w = Math.max(0, x2 - x1);
          const h = Math.max(0, y2 - y1);
          if (w <= 0 || h <= 0) return;

          let el;
          if (style === 'underline') {
            el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            el.setAttribute('x1', x1);
            el.setAttribute('y1', y2 + 1);
            el.setAttribute('x2', x2);
            el.setAttribute('y2', y2 + 1);
            el.setAttribute('stroke', color);
            el.setAttribute('class', 'highlight-underline');
          } else if (style === 'strikethrough') {
            const midY = (y1 + y2) / 2;
            el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            el.setAttribute('x1', x1);
            el.setAttribute('y1', midY);
            el.setAttribute('x2', x2);
            el.setAttribute('y2', midY);
            el.setAttribute('stroke', color);
            el.setAttribute('class', 'highlight-strikethrough');
          } else if (style === 'box' || style === 'rounded_box') {
            el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            el.setAttribute('x', x1 - 1);
            el.setAttribute('y', y1 - 1);
            el.setAttribute('width', w + 2);
            el.setAttribute('height', h + 2);
            el.setAttribute('stroke', color);
            el.setAttribute('class', 'highlight-box');
          } else {
            // solid_highlight tradicional
            el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            el.setAttribute('x', x1);
            el.setAttribute('y', y1);
            el.setAttribute('width', w);
            el.setAttribute('height', h);
            el.setAttribute('fill', color);
            el.setAttribute('class', 'highlight-rect');
          }

          el.dataset.hlId = hl.id;
          el.addEventListener('click', (e) => {
            e.stopPropagation();
            if (state.activeTool === 'eraser' || e.shiftKey || e.altKey) {
              deleteHighlight(hl.id, pageNum);
            }
          });
          highlightsGroup.appendChild(el);
        });
      }
    });
  }

  // 2. Llaves y Barras de agrupación vertical
  if (bracketsGroup && Array.isArray(pdata.brackets)) {
    pdata.brackets.forEach(br => {
      renderBracketGroup(bracketsGroup, br, pdfPtWidth);
    });
  }

  // 3. Sellos
  if (stampsGroup && Array.isArray(pdata.stamps)) {
    pdata.stamps.forEach(st => {
      renderStampSymbol(stampsGroup, st);
    });
  }

  // 4. Notas del margen con conectores a términos clave
  if (notesGroup && Array.isArray(pdata.annotations)) {
    pdata.annotations.forEach(note => {
      renderMarginNote(notesGroup, note, pdfPtWidth, pageNum);
    });
  }

  // 5. Esquemas Dagre
  if (schemasGroup && Array.isArray(pdata.schemas)) {
    pdata.schemas.forEach(schema => {
      if (schema) renderSchemaTree(schemasGroup, schema, pdfPtWidth);
    });
  }
}

function renderMarginNote(notesGroup, note, pdfPtWidth, pageNum = 1) {
  const coords = cellToCoords(note.cell, pdfPtWidth, true, pageNum);
  const nx = note.x !== undefined ? note.x : coords.x;
  const ny = note.y !== undefined ? note.y : coords.y;

  note.x = nx;
  note.y = ny;

  const w = note.width || 250;
  const h = note.height || 64;

  // Conector sutil discontinuo hacia el término destacado en el PDF
  if (note.connector_to && note.connector_to.x !== undefined) {
    const isRight = nx >= (MARGIN_LEFT_PT + pdfPtWidth);
    const startX = isRight ? nx : (nx + w);
    const startY = ny + 20;
    const targetX = note.connector_to.x;
    const targetY = note.connector_to.y;

    const midX = (startX + targetX) / 2;
    const d = `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${targetY}, ${targetX} ${targetY}`;

    const conn = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    conn.setAttribute('d', d);
    conn.setAttribute('stroke', note.highlight_color || '#ef4444');
    conn.setAttribute('stroke-width', '1.3');
    conn.setAttribute('class', 'note-connector-line');
    notesGroup.appendChild(conn);

    const anchorDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    anchorDot.setAttribute('cx', targetX);
    anchorDot.setAttribute('cy', targetY);
    anchorDot.setAttribute('r', '2.5');
    anchorDot.setAttribute('fill', note.highlight_color || '#ef4444');
    notesGroup.appendChild(anchorDot);
  }

  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', 'margin-note');
  group.setAttribute('transform', `translate(${nx}, ${ny})`);

  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rect.setAttribute('width', w);
  rect.setAttribute('height', h);
  rect.setAttribute('class', `note-box type-${note.type || 'warning'}`);
  group.appendChild(rect);

  const title = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  title.setAttribute('x', 10);
  title.setAttribute('y', 18);
  title.setAttribute('class', 'note-title');
  const prefix = note.type === 'warning' ? '⚠️ ATENCIÓN' : note.type === 'tip' ? '💡 CLAVE' : note.type === 'exam' ? '👁️ EXAMEN' : '📌 NOTA';
  title.textContent = prefix;
  group.appendChild(title);

  const body = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  body.setAttribute('x', 10);
  body.setAttribute('y', 36);
  body.setAttribute('class', 'note-body');

  const noteText = note.text || '';
  body.textContent = noteText.length > 80 ? noteText.substring(0, 80) + '…' : noteText;
  group.appendChild(body);

  if (noteText.length > 80) {
    const body2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    body2.setAttribute('x', 10);
    body2.setAttribute('y', 52);
    body2.setAttribute('class', 'note-body');
    body2.textContent = noteText.substring(80, 160);
    group.appendChild(body2);
  }

  notesGroup.appendChild(group);
}

function renderBracketGroup(bracketsGroup, br, pdfPtWidth) {
  const yStart = Number(br.y_start) || 100;
  const yEnd = Number(br.y_end) || 250;
  const yMid = (yStart + yEnd) / 2;
  const x = Number(br.x) || (MARGIN_LEFT_PT + pdfPtWidth - 12);
  const w = 10;
  const r = 8;

  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', 'bracket-group');

  if (br.bracket_type === 'bar') {
    // Barra lateral sólida de agrupación
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x + w);
    line.setAttribute('y1', yStart);
    line.setAttribute('x2', x + w);
    line.setAttribute('y2', yEnd);
    line.setAttribute('stroke', '#2563eb');
    line.setAttribute('stroke-width', '3');
    line.setAttribute('stroke-linecap', 'round');
    group.appendChild(line);
  } else {
    // Trazado de llave vertical {
    const d = `
      M ${x} ${yStart}
      Q ${x + w} ${yStart} ${x + w} ${yStart + r}
      L ${x + w} ${yMid - r}
      Q ${x + w} ${yMid} ${x + 2 * w} ${yMid}
      Q ${x + w} ${yMid} ${x + w} ${yMid + r}
      L ${x + w} ${yEnd - r}
      Q ${x + w} ${yEnd} ${x} ${yEnd}
    `.replace(/\s+/g, ' ').trim();

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('class', 'bracket-path');
    group.appendChild(path);
  }

  // Etiqueta en la punta
  const label = br.label || '';
  if (label) {
    const textWidth = measureText(label, '600 9.5px "Plus Jakarta Sans"');
    const badgeW = Math.max(60, textWidth + 18);
    const badgeH = 20;

    const badgeRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    badgeRect.setAttribute('x', x + 2 * w + 6);
    badgeRect.setAttribute('y', yMid - badgeH / 2);
    badgeRect.setAttribute('width', badgeW);
    badgeRect.setAttribute('height', badgeH);
    badgeRect.setAttribute('class', 'bracket-badge');
    group.appendChild(badgeRect);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', x + 2 * w + 14);
    text.setAttribute('y', yMid + 4);
    text.setAttribute('class', 'bracket-text');
    text.textContent = label;
    group.appendChild(text);
  }

  bracketsGroup.appendChild(group);
}

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', x + 2 * w + 14);
    text.setAttribute('y', yMid + 4);
    text.setAttribute('class', 'bracket-text');
    text.textContent = label;
    group.appendChild(text);
  }

  bracketsGroup.appendChild(group);
}

function renderStampSymbol(stampsGroup, st) {
  const x = Number(st.x) || 40;
  const y = Number(st.y) || 100;
  const symbol = st.symbol || '⚠️';

  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', 'stamp-group');
  group.setAttribute('transform', `translate(${x}, ${y})`);

  let badgeType = 'warning';
  if (symbol === '👁️') badgeType = 'exam';
  else if (symbol === '⭐') badgeType = 'star';
  else if (symbol === '🎯') badgeType = 'target';
  else if (symbol === '⚖️') badgeType = 'law';

  const badge = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  badge.setAttribute('width', 26);
  badge.setAttribute('height', 24);
  badge.setAttribute('class', `stamp-badge type-${badgeType}`);
  group.appendChild(badge);

  const symText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  symText.setAttribute('x', 5);
  symText.setAttribute('y', 17);
  symText.setAttribute('class', 'stamp-symbol');
  symText.textContent = symbol;
  group.appendChild(symText);

  stampsGroup.appendChild(group);
}

// ─────────────────────────────────────────────────────────────────────────────
// Localizador de Texto Preciso Multi-Span con Normalización Fonética y Puntuación
// ─────────────────────────────────────────────────────────────────────────────

function findTextRectsInPage(pageNum, query, options = {}) {
  const pageContainer = document.getElementById(`page-container-${pageNum}`);
  if (!pageContainer) return [];

  const textLayer = pageContainer.querySelector('.textLayer');
  if (!textLayer) return [];

  const spanElements = Array.from(textLayer.querySelectorAll('span'));
  if (spanElements.length === 0) return [];

  // Construir índice lineal de caracteres y mapeo inverso a nodos DOM
  let fullRaw = '';
  let mapRaw = [];

  spanElements.forEach((el, sIdx) => {
    const textNode = el.firstChild || el;
    const txt = el.textContent || '';
    for (let cIdx = 0; cIdx < txt.length; cIdx++) {
      mapRaw.push({ node: textNode, offset: cIdx });
      fullRaw += txt[cIdx];
    }
    // Separador sintético entre spans para permitir concordancias entre saltos de bloque
    mapRaw.push({ node: textNode, offset: txt.length });
    fullRaw += ' ';
  });

  // Normalización: elimina tildes, convierte puntuación en espacio y colapsa blancos
  let normStr = '';
  let normToRaw = [];
  let prevWasSpace = false;
  for (let rIdx = 0; rIdx < fullRaw.length; rIdx++) {
    const ch = fullRaw[rIdx];
    const nch = ch.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const isPunctOrSpace = /[.,\/#!$%\^&\*;:{}=\-_`~()\"'\''«»\s]/.test(nch);

    if (isPunctOrSpace) {
      if (!prevWasSpace) {
        normStr += ' ';
        normToRaw.push(rIdx);
        prevWasSpace = true;
      }
    } else {
      normStr += nch;
      normToRaw.push(rIdx);
      prevWasSpace = false;
    }
  }

  function findMatchIndices(searchStr, startAfter = 0) {
    if (!searchStr) return null;
    const normSearch = searchStr
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()\"'\''«»\s]+/g, ' ')
      .trim();

    if (!normSearch) return null;
    const idx = normStr.indexOf(normSearch, startAfter);
    if (idx === -1) return null;
    return {
      start: normToRaw[idx],
      end: normToRaw[idx + normSearch.length - 1],
      nextStart: idx + normSearch.length
    };
  }

  let startRaw = null;
  let endRaw = null;

  if (options.fromText && options.toText) {
    const mFrom = findMatchIndices(options.fromText);
    if (mFrom) {
      const mTo = findMatchIndices(options.toText, mFrom.nextStart) || findMatchIndices(options.toText);
      if (mTo) {
        startRaw = mFrom.start;
        endRaw = mTo.end;
      }
    }
  } else if (query) {
    const m = findMatchIndices(query);
    if (m) {
      startRaw = m.start;
      endRaw = m.end;
    }
  }

  if (startRaw === null || endRaw === null) {
    console.warn(`[findTextRectsInPage] Texto no localizado en pág ${pageNum}: "${query || options.fromText}"`);
    return [];
  }

  const startMap = mapRaw[startRaw];
  const endMap = mapRaw[endRaw];
  if (!startMap || !endMap) return [];

  const range = document.createRange();
  try {
    const maxStartOffset = startMap.node.length !== undefined ? Math.min(startMap.offset, startMap.node.length) : startMap.offset;
    const maxEndOffset = endMap.node.length !== undefined ? Math.min(endMap.offset + 1, endMap.node.length) : (endMap.offset + 1);
    range.setStart(startMap.node, maxStartOffset);
    range.setEnd(endMap.node, maxEndOffset);
  } catch (e) {
    console.warn('Error configurando DOM Range:', e);
    return [];
  }

  const clientRects = range.getClientRects();
  const pageRect = pageContainer.getBoundingClientRect();
  const viewportInfo = state.pageViewports[pageNum] || { totalPtWidth: 1195, pdfPtHeight: 842 };
  const totalPtWidth = viewportInfo.totalPtWidth || (MARGIN_LEFT_PT + 595 + MARGIN_RIGHT_PT);
  const pdfPtHeight = viewportInfo.pdfPtHeight || 842;

  const scaleX = pageRect.width > 0 ? (pageRect.width / totalPtWidth) : state.scale;
  const scaleY = pageRect.height > 0 ? (pageRect.height / pdfPtHeight) : state.scale;

  const rects = [];
  for (let i = 0; i < clientRects.length; i++) {
    const cr = clientRects[i];
    if (cr.width < 1 || cr.height < 1) continue;
    const x1 = Math.round((cr.left - pageRect.left) / scaleX);
    const y1 = Math.round((cr.top - pageRect.top) / scaleY);
    const x2 = Math.round((cr.right - pageRect.left) / scaleX);
    const y2 = Math.round((cr.bottom - pageRect.top) / scaleY);
    rects.push([x1, y1, x2, y2]);
  }

  return rects;
}

// ─────────────────────────────────────────────────────────────────────────────
// Ejecutor de Comandos y Herramientas (Function Calling & Pipeline de Voz)
// ─────────────────────────────────────────────────────────────────────────────

function executeVoiceCommand(command, args = {}) {
  // Soporte de payloads con 'action' directo o 'command'
  if (!command && args.action) {
    command = args.action;
  }
  if (typeof args !== 'object' || args === null) {
    args = {};
  }
  if (!command && args.command) {
    command = args.command;
    args = args.args || args;
  }
  if (!command) return;

  console.log(`🎙️ Ejecutando herramienta de voz: [${command}]`, args);

  // Registrar estado previo para deshacer
  state.historyStack.push(JSON.parse(JSON.stringify(state.notes)));

  const curPage = String(args.page || state.currentPage || 1);
  if (!state.notes.pages[curPage]) {
    state.notes.pages[curPage] = {
      highlights: [],
      annotations: [],
      schemas: [],
      brackets: [],
      stamps: []
    };
  }
  const pageNotes = state.notes.pages[curPage];
  if (!pageNotes.brackets) pageNotes.brackets = [];
  if (!pageNotes.stamps) pageNotes.stamps = [];
  if (!pageNotes.highlights) pageNotes.highlights = [];
  if (!pageNotes.annotations) pageNotes.annotations = [];
  if (!pageNotes.schemas) pageNotes.schemas = [];

  const viewportInfo = state.pageViewports[curPage] || { pdfPtWidth: 595 };
  const pdfPtWidth = viewportInfo.pdfPtWidth;

  switch (command) {
    case 'activate_grid': {
      state.showGrid = args.show !== undefined ? args.show : !state.showGrid;
      document.querySelectorAll('.grid-layer').forEach(el => {
        el.classList.toggle('grid-hidden', !state.showGrid);
      });
      document.getElementById('btn-toggle-grid').classList.toggle('active', state.showGrid);
      break;
    }

    case 'toggle_active_recall': {
      state.activeRecall = args.enabled !== undefined ? args.enabled : !state.activeRecall;
      document.body.classList.toggle('active-recall-enabled', state.activeRecall);
      document.getElementById('btn-toggle-recall').classList.toggle('active', state.activeRecall);
      break;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Opción 1: Comandos atómicos de marcado visual (Subrayar, Resaltar, Rango)
    // ─────────────────────────────────────────────────────────────────────────
    case 'highlight_passage':
    case 'mark_text': {
      const color = resolveColor(args.color, '#fef08a');
      const style = args.style || 'solid_highlight';
      let rects = [];

      if (args.from_text && args.to_text) {
        rects = findTextRectsInPage(curPage, null, { fromText: args.from_text, toText: args.to_text });
      } else {
        const target = args.target_text || args.text || '';
        rects = findTextRectsInPage(curPage, target);
      }

      if (rects.length === 0) {
        console.warn(`No se encontraron coincidencias para marcar: ${args.target_text || args.from_text}`);
        break;
      }

      pageNotes.highlights.push({
        id: `hl_${Date.now()}`,
        text: args.target_text || `${args.from_text} → ${args.to_text}`,
        color: color,
        style: style,
        rects: rects
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'frame_text':
    case 'box_text': {
      const color = resolveColor(args.color, '#2563eb');
      const target = args.target_text || args.text || '';
      const rects = findTextRectsInPage(curPage, target);
      if (rects.length === 0) break;

      pageNotes.highlights.push({
        id: `box_${Date.now()}`,
        text: target,
        color: color,
        style: 'box',
        rects: rects
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'strikethrough_text':
    case 'tacha_text': {
      const color = resolveColor(args.color, '#ef4444');
      const target = args.target_text || args.text || '';
      const rects = findTextRectsInPage(curPage, target);
      if (rects.length === 0) break;

      pageNotes.highlights.push({
        id: `strike_${Date.now()}`,
        text: target,
        color: color,
        style: 'strikethrough',
        rects: rects
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Pipeline Doble: Nota marginal con subrayado automático en rojo y conector
    // ─────────────────────────────────────────────────────────────────────────
    case 'margin_note_with_highlights': {
      const anchorText = args.anchor_text || '';
      const anchorRects = findTextRectsInPage(curPage, anchorText);
      const anchorY = anchorRects.length > 0 ? anchorRects[0][1] : (state.cursorContext.pos[1] || 150);

      const rules = args.highlight_rules || {};
      const hlColor = resolveColor(rules.color, '#ef4444');
      const hlStyle = rules.style || 'underline';

      let firstMatchPt = null;
      (rules.terms_to_match || []).forEach(term => {
        const tRects = findTextRectsInPage(curPage, term);
        if (tRects.length > 0) {
          if (!firstMatchPt) {
            firstMatchPt = {
              x: tRects[0][0],
              y: Math.round((tRects[0][1] + tRects[0][3]) / 2)
            };
          }
          pageNotes.highlights.push({
            id: `hl_sub_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
            text: term,
            color: hlColor,
            style: hlStyle,
            rects: tRects
          });
        }
      });

      const side = args.margin || 'right';
      const noteX = side === 'left' ? 15 : (MARGIN_LEFT_PT + pdfPtWidth + 15);
      const noteY = anchorY;

      pageNotes.annotations.push({
        id: `note_${Date.now()}`,
        type: 'exam',
        text: args.note_content || 'Nota marginal de estudio',
        highlight_terms: rules.terms_to_match || [],
        highlight_color: hlColor,
        x: noteX,
        y: noteY,
        width: 250,
        height: 65,
        connector_to: firstMatchPt
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Opción 2: Montar esquema jerárquico al margen (Dagre con auto-layout)
    // ─────────────────────────────────────────────────────────────────────────
    case 'create_margin_diagram': {
      const anchorText = args.anchor_text || '';
      const anchorRects = findTextRectsInPage(curPage, anchorText);
      const anchorY = anchorRects.length > 0 ? anchorRects[0][1] : (state.cursorContext.pos[1] || 100);

      const content = args.content || {};
      const rootLabel = content.root || args.root_title || 'Jerarquía';
      const rawNodes = content.nodes || [];

      const dagreNodes = [
        { id: 'root', label: rootLabel, isRoot: true }
      ];
      const dagreEdges = [];

      rawNodes.forEach((item, pIdx) => {
        const pId = `node_${pIdx}`;
        dagreNodes.push({
          id: pId,
          label: item.title || `Rama ${pIdx + 1}`,
          details: Array.isArray(item.children) ? item.children : []
        });
        dagreEdges.push({ from: 'root', to: pId });
      });

      const newSchema = {
        id: args.schema_id || `schema_${Date.now()}`,
        anchor_text: anchorText,
        anchor_y: anchorY,
        side: args.side || 'right',
        diagram_type: args.diagram_type || 'tree',
        orientation: 'TB',
        nodes: dagreNodes,
        edges: dagreEdges
      };

      pageNotes.schemas.push(newSchema);
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'create_schema': {
      const newSchema = {
        id: args.schema_id || `schema_${Date.now()}`,
        anchor_cell: args.anchor_cell || state.cursorContext.cell || 'E1',
        orientation: args.orientation || 'TB',
        nodes: args.nodes || [
          { id: 'root', label: args.root_title || 'Concepto Raíz', details: [] }
        ],
        edges: args.edges || []
      };

      pageNotes.schemas.push(newSchema);
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_schema_branch': {
      const { schema_id, parent_node_id, new_node } = args;
      const schema = pageNotes.schemas.find(s => s.id === schema_id) || pageNotes.schemas[pageNotes.schemas.length - 1];
      if (schema && new_node) {
        schema.nodes.push(new_node);
        schema.edges.push({ from: parent_node_id || 'root', to: new_node.id });
        refreshCurrentPageSvg(curPage);
        saveNotesToServer();
      }
      break;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Opción 3: Comandos de control, ajuste y corrección (Rollback, Mover, Borrar)
    // ─────────────────────────────────────────────────────────────────────────
    case 'move_schema': {
      const targetSide = args.side || 'left';
      if (pageNotes.schemas.length > 0) {
        const targetSchema = args.schema_id ? pageNotes.schemas.find(s => s.id === args.schema_id) : pageNotes.schemas[pageNotes.schemas.length - 1];
        if (targetSchema) {
          targetSchema.side = targetSide;
          refreshCurrentPageSvg(curPage);
          saveNotesToServer();
        }
      }
      break;
    }

    case 'undo':
    case 'undo_last_action': {
      if (state.historyStack.length > 0) {
        state.notes = state.historyStack.pop();
        for (let p = 1; p <= (state.pdfDoc?.numPages || 1); p++) {
          refreshCurrentPageSvg(String(p));
        }
        saveNotesToServer();
      }
      break;
    }

    case 'clear_page_annotations': {
      pageNotes.highlights = [];
      pageNotes.annotations = [];
      pageNotes.schemas = [];
      pageNotes.brackets = [];
      pageNotes.stamps = [];
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'remove_highlight': {
      const targetText = (args.target_text || '').toLowerCase().trim();
      if (!Array.isArray(pageNotes.highlights) || pageNotes.highlights.length === 0) break;

      if (targetText && targetText !== 'esto' && targetText !== 'aqui' && targetText !== 'aquí') {
        pageNotes.highlights = pageNotes.highlights.filter(h => !(h.text || '').toLowerCase().includes(targetText));
      } else {
        let bestIdx = -1;
        let minDist = Infinity;
        pageNotes.highlights.forEach((h, idx) => {
          (h.rects || []).forEach(r => {
            const cx = (r[0] + r[2]) / 2;
            const cy = (r[1] + r[3]) / 2;
            const d = Math.hypot(state.cursorContext.pos[0] - cx, state.cursorContext.pos[1] - cy);
            if (d < minDist) {
              minDist = d;
              bestIdx = idx;
            }
          });
        });
        if (bestIdx >= 0) {
          pageNotes.highlights.splice(bestIdx, 1);
        }
      }

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'clear_highlights': {
      pageNotes.highlights = [];
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_margin_note': {
      pageNotes.annotations.push({
        id: `note_${Date.now()}`,
        cell: args.cell || state.cursorContext.cell || 'R4',
        type: args.note_type || 'warning',
        text: args.text || 'Nota de estudio',
        width: 250,
        height: 62
      });
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_bracket_group': {
      let yStart = 100;
      let yEnd = 250;

      if (args.from_text && args.to_text) {
        const rFrom = findTextRectsInPage(curPage, args.from_text);
        const rTo = findTextRectsInPage(curPage, args.to_text);
        if (rFrom.length > 0 && rTo.length > 0) {
          yStart = rFrom[0][1];
          yEnd = rTo[rTo.length - 1][3];
        }
      } else {
        const startCoords = cellToCoords(args.start_cell || 'B5', pdfPtWidth, false, curPage);
        const endCoords = cellToCoords(args.end_cell || 'B10', pdfPtWidth, false, curPage);
        yStart = startCoords.y;
        yEnd = endCoords.y + getPageRowHeight(curPage);
      }

      const defaultX = MARGIN_LEFT_PT + pdfPtWidth - 12;
      pageNotes.brackets.push({
        id: `br_${Date.now()}`,
        y_start: yStart,
        y_end: yEnd,
        x: args.x !== undefined ? Number(args.x) : defaultX,
        label: args.label || '',
        bracket_type: args.bracket_type || 'bracket'
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_stamp_symbol': {
      const cellCoords = cellToCoords(args.cell || 'B2', pdfPtWidth, false, curPage);
      pageNotes.stamps.push({
        id: `stamp_${Date.now()}`,
        cell: args.cell || 'B2',
        x: cellCoords.x + 8,
        y: cellCoords.y + 8,
        symbol: args.symbol || '⚠️',
        label: args.label || ''
      });
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'open_document': {
      if (args.doc_id) {
        loadDocument(args.doc_id);
      }
      break;
    }

    case 'go_to_page': {
      const targetPage = parseInt(args.page, 10) || 1;
      if (targetPage >= 1 && targetPage <= state.pdfDoc.numPages) {
        state.currentPage = targetPage;
        state.cursorContext.page = targetPage;
        const container = document.getElementById('pdf-container');
        container.innerHTML = '';
        await renderPage(targetPage);
        updateHUD();
      }
      break;
    }

    default:
      console.warn(`Comando no reconocido: ${command}`);
  }
}

function refreshCurrentPageSvg(pageNum) {
  const pageContainer = document.getElementById(`page-container-${pageNum}`);
  if (!pageContainer) return;
  const svg = pageContainer.querySelector('.overlay-svg');
  if (svg) {
    const viewportInfo = state.pageViewports[pageNum] || { pdfPtWidth: 595 };
    renderPageAnnotations(pageNum, svg, viewportInfo.pdfPtWidth);
  }
}

async function saveNotesToServer() {
  try {
    await fetch(`/api/notes/${encodeURIComponent(state.docId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.notes)
    });
  } catch (e) {
    console.error('Error guardando notas en el servidor:', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// WebSocket & Comunicación Bidireccional
// ─────────────────────────────────────────────────────────────────────────────

function setupWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/commands`;

  const wsStatus = document.getElementById('ws-status');

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      wsStatus.classList.add('connected');
      console.log('🔗 WebSocket conectado con el backend.');
    };

    state.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'voice_command') {
          executeVoiceCommand(data.command || data.action, data.args || data);
        } else if (data.action) {
          executeVoiceCommand(data.action, data);
        } else if (data.type === 'notes_saved') {
          console.log('Persistencia sidecar confirmada por el servidor.');
        }
      } catch (err) {
        console.error('Error procesando mensaje WS:', err);
      }
    };

    state.ws.onclose = () => {
      wsStatus.classList.remove('connected');
      console.warn('⚠️ WebSocket desconectado. Reintentando en 3s...');
      setTimeout(setupWebSocket, 3000);
    };

    state.ws.onerror = (err) => {
      console.error('Error en WebSocket:', err);
      state.ws.close();
    };
  } catch (e) {
    console.error('No se pudo establecer WebSocket:', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Listeners de la Interfaz y Simulador
// ─────────────────────────────────────────────────────────────────────────────

function setupUIListeners() {
  // Selector de documento
  const docSelect = document.getElementById('doc-select');
  docSelect.addEventListener('change', async (e) => {
    await loadDocument(e.target.value);
  });

  // Subir nuevo PDF
  const btnUpload = document.getElementById('btn-upload-doc');
  const uploadInput = document.getElementById('doc-upload-input');
  btnUpload.addEventListener('click', () => uploadInput.click());

  uploadInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);

    try {
      btnUpload.textContent = '⏳';
      btnUpload.disabled = true;
      const resp = await fetch('/api/upload', { method: 'POST', body: formData });
      if (resp.ok) {
        const data = await resp.json();
        const uploadedDoc = data.filename || file.name;
        state.docId = uploadedDoc;
        await refreshDocumentList();
        await loadDocument(uploadedDoc);
      } else {
        const err = await resp.json().catch(() => ({}));
        alert(`Error al subir el archivo PDF: ${err.detail || resp.statusText}`);
      }
    } catch (err) {
      alert(`Error al subir: ${err.message}`);
    } finally {
      btnUpload.textContent = '+';
      btnUpload.disabled = false;
      uploadInput.value = '';
    }
  });

  // Toggle cuadrícula
  const btnGrid = document.getElementById('btn-toggle-grid');
  btnGrid.addEventListener('click', () => {
    executeVoiceCommand('activate_grid', { show: !state.showGrid });
  });

  // Toggle repaso activo
  const btnRecall = document.getElementById('btn-toggle-recall');
  btnRecall.addEventListener('click', () => {
    executeVoiceCommand('toggle_active_recall', { enabled: !state.activeRecall });
  });

  // Deshacer
  document.getElementById('btn-undo').addEventListener('click', () => {
    executeVoiceCommand('undo_last_action');
  });

  // Navegación
  document.getElementById('btn-prev').addEventListener('click', () => {
    if (state.currentPage > 1) {
      executeVoiceCommand('go_to_page', { page: state.currentPage - 1 });
    }
  });

  document.getElementById('btn-next').addEventListener('click', () => {
    if (state.currentPage < state.pdfDoc.numPages) {
      executeVoiceCommand('go_to_page', { page: state.currentPage + 1 });
    }
  });

  // Guardar notas
  document.getElementById('btn-save').addEventListener('click', () => {
    saveNotesToServer();
    alert('Notas guardadas en el archivo sidecar JSON.');
  });

  // Navegación de páginas
  document.getElementById('btn-prev').addEventListener('click', async () => {
    if (state.currentPage > 1) {
      state.currentPage--;
      await loadDocument(state.docId);
    }
  });

  document.getElementById('btn-next').addEventListener('click', async () => {
    if (state.pdfDoc && state.currentPage < state.pdfDoc.numPages) {
      state.currentPage++;
      await loadDocument(state.docId);
    }
  });

  // Exportar PDF
  document.getElementById('btn-export').addEventListener('click', async () => {
    const btn = document.getElementById('btn-export');
    btn.textContent = '⏳ Compilando...';
    btn.disabled = true;

    try {
      const resp = await fetch(`/api/export/${encodeURIComponent(state.docId)}`, { method: 'POST' });
      const data = await resp.json();
      if (resp.ok) {
        window.open(data.download_url, '_blank');
      } else {
        alert(`Error al exportar: ${data.detail}`);
      }
    } catch (e) {
      alert(`Error en la exportación: ${e.message}`);
    } finally {
      btn.textContent = '📤 Exportar PDF';
      btn.disabled = false;
    }
  });

  // Zoom
  document.getElementById('btn-zoom-in').addEventListener('click', async () => {
    state.scale = Math.min(2.5, state.scale + 0.15);
    document.getElementById('zoom-label').textContent = `${Math.round(state.scale * 100)}%`;
    await loadDocument(state.docId);
  });

  document.getElementById('btn-zoom-out').addEventListener('click', async () => {
    state.scale = Math.max(0.75, state.scale - 0.15);
    document.getElementById('zoom-label').textContent = `${Math.round(state.scale * 100)}%`;
    await loadDocument(state.docId);
  });

  // Panel colapsable del simulador
  const btnToggleSim = document.getElementById('btn-toggle-sim');
  const simPanel = document.getElementById('voice-simulator');
  btnToggleSim.addEventListener('click', () => {
    simPanel.classList.toggle('collapsed');
    btnToggleSim.textContent = simPanel.classList.contains('collapsed') ? '▼' : '▲';
  });

  // Chips de simulación rápida
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const cmdKey = chip.dataset.cmd;
      switch (cmdKey) {
        case 'highlight_un_mes':
          executeVoiceCommand('highlight_passage', {
            target_text: 'un mes si el acto fuera expreso',
            color: '#fef08a',
            style: 'solid_highlight'
          });
          break;

        case 'highlight_range_plazo':
          executeVoiceCommand('highlight_passage', {
            from_text: 'El plazo',
            to_text: 'tres meses',
            color: '#bbf7d0',
            style: 'solid_highlight'
          });
          break;

        case 'margin_note_double':
          executeVoiceCommand('margin_note_with_highlights', {
            anchor_text: 'plazo de interposición',
            margin: 'right',
            note_content: 'Recurso: 1 mes natural (improrrogable) tras notificación.',
            highlight_rules: {
              color: 'red',
              style: 'underline',
              terms_to_match: [
                'improrrogable',
                'un mes',
                'notificación expresa'
              ]
            }
          });
          break;

        case 'schema_jerarquia':
          executeVoiceCommand('create_margin_diagram', {
            anchor_text: 'órgano competente',
            side: 'right',
            diagram_type: 'tree',
            content: {
              root: 'Jerarquía',
              nodes: [
                {
                  title: 'Superior',
                  children: ['Ministro', 'Secretario']
                },
                {
                  title: 'Inferior',
                  children: ['Subdirector']
                }
              ]
            }
          });
          break;

        case 'bracket_text_anchor':
          executeVoiceCommand('add_bracket_group', {
            from_text: 'Iniciación',
            to_text: 'Finalización',
            label: 'Fases Art. 53-86',
            bracket_type: 'bracket'
          });
          break;

        case 'box_fases':
          executeVoiceCommand('frame_text', {
            target_text: 'FASES',
            color: '#2563eb'
          });
          break;

        case 'strike_oficio':
          executeVoiceCommand('strikethrough_text', {
            target_text: 'de oficio',
            color: '#ef4444'
          });
          break;

        case 'move_schema_left':
          executeVoiceCommand('move_schema', {
            side: 'left'
          });
          break;

        case 'schema_procedimiento':
          executeVoiceCommand('create_schema', {
            schema_id: 'schema_fases',
            anchor_cell: 'E1',
            orientation: 'TB',
            nodes: [
              { id: 'fases', label: 'Fases Proc. Admin.', details: ['Ley 39/2015', '4 fases clave'] },
              { id: 'iniciacion', label: '1. Iniciación', details: ['De oficio / A solicitud'] },
              { id: 'ordenacion', label: '2. Ordenación', details: ['Celeridad e impulso'] },
              { id: 'instruccion', label: '3. Instrucción', details: ['Alegaciones, prueba'] },
              { id: 'finalizacion', label: '4. Finalización', details: ['Resolución, desistimiento'] }
            ],
            edges: [
              { from: 'fases', to: 'iniciacion' },
              { from: 'fases', to: 'ordenacion' },
              { from: 'fases', to: 'instruccion' },
              { from: 'fases', to: 'finalizacion' }
            ]
          });
          break;

        case 'add_branch_recurso':
          executeVoiceCommand('add_schema_branch', {
            schema_id: 'schema_fases',
            parent_node_id: 'finalizacion',
            new_node: { id: 'recursos', label: 'Recursos', details: ['Alzada / Reposición'] }
          });
          break;

        case 'highlight_silencio':
          executeVoiceCommand('highlight_passage', {
            target_text: 'silencio administrativo',
            color: '#fef08a'
          });
          break;

        case 'remove_highlight':
          executeVoiceCommand('remove_highlight');
          break;

        case 'note_prescripcion':
          executeVoiceCommand('add_margin_note', {
            cell: 'F4',
            note_type: 'warning',
            text: 'Plazo general prescripción: 4 años (Art. 66 LGT)'
          });
          break;

        case 'bracket_fases':
          executeVoiceCommand('add_bracket_group', {
            start_cell: 'A6',
            end_cell: 'A10',
            label: 'Art. 53-86: Fases Procedimiento'
          });
          break;

        case 'stamp_examen':
          executeVoiceCommand('add_stamp_symbol', {
            cell: 'A2',
            symbol: '👁️',
            label: 'TEST'
          });
          break;

        case 'stamp_estrella':
          executeVoiceCommand('add_stamp_symbol', {
            cell: 'B4',
            symbol: '⭐',
            label: 'CLAVE'
          });
          break;

        case 'toggle_grid':
          executeVoiceCommand('activate_grid', { show: !state.showGrid });
          break;

        case 'toggle_recall':
          executeVoiceCommand('toggle_active_recall', { enabled: !state.activeRecall });
          break;

        case 'undo':
          executeVoiceCommand('undo_last_action');
          break;

        case 'clear_page':
          executeVoiceCommand('clear_page_annotations');
          break;
      }
    });
  });

  // Envío manual desde input del simulador (soporta tanto { command, args } como { action, ... })
  document.getElementById('btn-send-sim').addEventListener('click', () => {
    const input = document.getElementById('sim-input');
    try {
      const payload = JSON.parse(input.value.trim());
      executeVoiceCommand(payload.command || payload.action, payload.args || payload);
      input.value = '';
    } catch (e) {
      alert(`JSON no válido: ${e.message}`);
    }
  });

  // Barra de herramientas de subrayado y paleta
  const btnHighlighter = document.getElementById('btn-tool-highlighter');
  const btnEraser = document.getElementById('btn-tool-eraser');
  const swatches = document.querySelectorAll('.hl-swatch');

  function setHighlighterMode(tool) {
    state.activeTool = tool;
    if (tool === 'highlighter') {
      if (btnHighlighter) btnHighlighter.classList.add('active');
      if (btnEraser) btnEraser.classList.remove('active');
      document.body.classList.remove('hl-eraser-mode');
      document.body.classList.add('hl-pen-mode');
    } else if (tool === 'eraser') {
      if (btnHighlighter) btnHighlighter.classList.remove('active');
      if (btnEraser) btnEraser.classList.add('active');
      document.body.classList.add('hl-eraser-mode');
      document.body.classList.remove('hl-pen-mode');
    }
  }

  if (btnHighlighter) {
    btnHighlighter.addEventListener('click', () => {
      setHighlighterMode('highlighter');
    });
  }

  if (btnEraser) {
    btnEraser.addEventListener('click', () => {
      setHighlighterMode(state.activeTool === 'eraser' ? 'highlighter' : 'eraser');
    });
  }

  swatches.forEach(swatch => {
    swatch.addEventListener('click', () => {
      swatches.forEach(s => s.classList.remove('active'));
      swatch.classList.add('active');
      state.activeHighlightColor = swatch.dataset.color || '#fef08a';
      setHighlighterMode('highlighter');
    });
  });

  // Atajos de teclado
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'g' || e.key === 'G') {
      executeVoiceCommand('activate_grid', { show: !state.showGrid });
    } else if (e.key === 'r' || e.key === 'R') {
      executeVoiceCommand('toggle_active_recall', { enabled: !state.activeRecall });
    } else if (e.key === 'h' || e.key === 'H') {
      setHighlighterMode('highlighter');
    } else if (e.key === 'e' || e.key === 'E') {
      setHighlighterMode(state.activeTool === 'eraser' ? 'highlighter' : 'eraser');
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      executeVoiceCommand('undo_last_action');
    }
  });
}

// Iniciar aplicación al cargar el DOM
window.addEventListener('DOMContentLoaded', initApp);

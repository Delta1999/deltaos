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
const MARGIN_EXTENDED_PT = 380; // Ancho virtual del margen lateral derecho
const CELL_WIDTH = 65;          // Ancho de celda alfanumérica
const CELL_HEIGHT = 65;         // Alto de celda alfanumérica

// Estado reactivo global
const state = {
  docId: 'sample.pdf',
  pdfDoc: null,
  scale: 1.25,
  showGrid: true,
  activeRecall: false,
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
  pageViewports: {} // Metadatos de dimensiones por página
};

// Canvas auxiliar para medición exacta de texto
const measureCanvas = document.createElement('canvas');
const measureCtx = measureCanvas.getContext('2d');

function measureText(text, font = '11px "Plus Jakarta Sans"') {
  measureCtx.font = font;
  return measureCtx.measureText(text || '').width;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sistema de Coordenadas y Conversión de Celdas
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Convierte un nombre de celda alfanumérica (ej: "A1", "F4", "J2") a coordenadas (X, Y) en puntos.
 * Si isMarginTarget es true y la columna cae dentro del texto original del PDF,
 * auto-proyecta la X al comienzo del margen extendido manteniendo la fila Y.
 */
function cellToCoords(cellStr, pdfPtWidth = 595, isMarginTarget = false) {
  if (!cellStr || typeof cellStr !== 'string') {
    return { x: isMarginTarget ? pdfPtWidth + 15 : 20, y: 20 };
  }
  const match = cellStr.toUpperCase().trim().match(/^([A-Z]+)(\d+)$/);
  if (!match) {
    return { x: isMarginTarget ? pdfPtWidth + 15 : 20, y: 20 };
  }

  const letters = match[1];
  const row = Math.max(1, parseInt(match[2], 10)) - 1;

  // Convertir columna alfanumérica (A=0, B=1 ... Z=25, AA=26)
  let col = 0;
  for (let i = 0; i < letters.length; i++) {
    col = col * 26 + (letters.charCodeAt(i) - 64);
  }
  col -= 1;

  let x = col * CELL_WIDTH;
  const y = row * CELL_HEIGHT;

  if (isMarginTarget && x < pdfPtWidth) {
    x = pdfPtWidth + 15;
  }

  return { x, y };
}

/**
 * Convierte coordenadas (X, Y) en puntos PDF a su etiqueta alfanumérica correspondiente.
 */
function coordsToCell(x, y) {
  const col = Math.max(0, Math.floor(x / CELL_WIDTH));
  const row = Math.max(0, Math.floor(y / CELL_HEIGHT)) + 1;

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

async function refreshDocumentList() {
  try {
    const resp = await fetch('/api/documents');
    if (resp.ok) {
      const data = await resp.json();
      const select = document.getElementById('doc-select');
      select.innerHTML = '';
      (data.documents || []).forEach(doc => {
        const opt = document.createElement('option');
        opt.value = doc;
        opt.textContent = doc;
        if (doc === state.docId) opt.selected = true;
        select.appendChild(opt);
      });
    }
  } catch (e) {
    console.warn('Error al obtener lista de documentos:', e);
  }
}

async function loadDocument(docId) {
  state.docId = docId;
  const container = document.getElementById('pdf-container');
  container.innerHTML = '<div style="color: #64748b; padding: 40px; font-size: 14px;">Cargando documento PDF y notas...</div>';

  try {
    // 1. Cargar datos del sidecar JSON de notas
    try {
      const resp = await fetch(`/api/notes/${docId}`);
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
    const loadingTask = pdfjsLib.getDocument(`/api/pdf/${docId}`);
    state.pdfDoc = await loadingTask.promise;
    container.innerHTML = '';

    // 3. Renderizar cada página
    for (let pageNum = 1; pageNum <= state.pdfDoc.numPages; pageNum++) {
      await renderPage(pageNum);
    }

    console.log(`PDF '${docId}' cargado correctamente con ${state.pdfDoc.numPages} páginas.`);
  } catch (error) {
    console.error('Error cargando PDF:', error);
    container.innerHTML = `<div style="color: #ef4444; padding: 40px; font-size: 14px;">Error al cargar PDF: ${error.message}</div>`;
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
  const totalPtWidth = pdfPtWidth + MARGIN_EXTENDED_PT;

  state.pageViewports[pageNum] = {
    pdfPtWidth,
    pdfPtHeight,
    totalPtWidth
  };

  // Dimensiones renderizadas en píxeles de pantalla según el zoom
  const screenScale = state.scale;
  const screenWidth = totalPtWidth * screenScale;
  const screenHeight = pdfPtHeight * screenScale;
  const pdfScreenWidth = pdfPtWidth * screenScale;

  // Contenedor principal de la página
  const pageDiv = document.createElement('div');
  pageDiv.className = 'page-container';
  pageDiv.id = `page-container-${pageNum}`;
  pageDiv.dataset.page = pageNum;
  pageDiv.style.width = `${screenWidth}px`;
  pageDiv.style.height = `${screenHeight}px`;

  // Línea divisoria del margen extendido
  const divider = document.createElement('div');
  divider.className = 'margin-divider';
  divider.style.left = `${pdfScreenWidth}px`;
  pageDiv.appendChild(divider);

  // Capa 1: Canvas del PDF original (0 a pdfScreenWidth)
  const canvas = document.createElement('canvas');
  canvas.className = 'pdf-canvas';
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(pdfScreenWidth * dpr);
  canvas.height = Math.round(screenHeight * dpr);
  canvas.style.width = `${pdfScreenWidth}px`;
  canvas.style.height = `${screenHeight}px`;
  pageDiv.appendChild(canvas);

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const renderViewport = page.getViewport({ scale: screenScale });
  await page.render({ canvasContext: ctx, viewport: renderViewport }).promise;

  // Capa 2: TextLayer nativo de PDF.js para selección y desambiguación espacial
  const textLayerDiv = document.createElement('div');
  textLayerDiv.className = 'textLayer';
  textLayerDiv.style.width = `${pdfScreenWidth}px`;
  textLayerDiv.style.height = `${screenHeight}px`;
  pageDiv.appendChild(textLayerDiv);

  const textContent = await page.getTextContent();
  pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayerDiv,
    viewport: renderViewport,
    textDivs: []
  });

  // Capa 3: Capa Vectorial SVG Superior (Cubre el 100% del contenedor: PDF + Margen)
  // El viewBox está fijado en puntos nativos (totalPtWidth x pdfPtHeight),
  // por lo que todas las coordenadas de anotaciones son inmunes al zoom.
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'overlay-svg');
  svg.setAttribute('viewBox', `0 0 ${totalPtWidth} ${pdfPtHeight}`);
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

  // Renderizar la cuadrícula alfanumérica de esta página
  renderGrid(gridGroup, totalPtWidth, pdfPtHeight);

  // Renderizar todas las anotaciones persistidas de la página
  renderPageAnnotations(pageNum, svg, pdfPtWidth);

  // Seguimiento contextual del cursor del ratón sobre la página
  setupMouseTracking(pageDiv, pageNum, textLayerDiv, pdfPtWidth);
}

// ─────────────────────────────────────────────────────────────────────────────
// Cuadrícula Alfanumérica de Referencia
// ─────────────────────────────────────────────────────────────────────────────

function renderGrid(group, width, height) {
  group.innerHTML = '';
  const cols = Math.ceil(width / CELL_WIDTH);
  const rows = Math.ceil(height / CELL_HEIGHT);

  // Líneas verticales
  for (let c = 0; c <= cols; c++) {
    const x = c * CELL_WIDTH;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x);
    line.setAttribute('y1', 0);
    line.setAttribute('x2', x);
    line.setAttribute('y2', height);
    line.setAttribute('class', 'grid-line');
    group.appendChild(line);
  }

  // Líneas horizontales
  for (let r = 0; r <= rows; r++) {
    const y = r * CELL_HEIGHT;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', 0);
    line.setAttribute('y1', y);
    line.setAttribute('x2', width);
    line.setAttribute('y2', y);
    line.setAttribute('class', 'grid-line');
    group.appendChild(line);
  }

  // Etiquetas alfanuméricas
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const cellLabel = coordsToCell(c * CELL_WIDTH, r * CELL_HEIGHT);
      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', c * CELL_WIDTH + 5);
      text.setAttribute('y', r * CELL_HEIGHT + 13);
      text.setAttribute('class', 'grid-label');
      text.textContent = cellLabel;
      group.appendChild(text);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Seguimiento Contextual del Ratón y Desambiguación
// ─────────────────────────────────────────────────────────────────────────────

let lastWsContextSend = 0;

function setupMouseTracking(pageDiv, pageNum, textLayerDiv, pdfPtWidth) {
  pageDiv.addEventListener('mousemove', (e) => {
    const rect = pageDiv.getBoundingClientRect();
    const screenX = e.clientX - rect.left;
    const screenY = e.clientY - rect.top;

    // Convertir píxeles de pantalla a puntos PDF sin escalar
    const ptX = Math.round(screenX / state.scale);
    const ptY = Math.round(screenY / state.scale);

    const cell = coordsToCell(ptX, ptY);
    state.currentPage = pageNum;
    state.cursorContext = {
      page: pageNum,
      cell: cell,
      pos: [ptX, ptY],
      posScreen: [Math.round(screenX), Math.round(screenY)],
      nearestText: findNearestText(screenX, screenY, textLayerDiv)
    };

    updateHUD();

    // Notificar al backend vía WebSocket con throttling a 100ms
    const now = Date.now();
    if (now - lastWsContextSend > 100 && state.ws && state.ws.readyState === WebSocket.OPEN) {
      lastWsContextSend = now;
      state.ws.send(JSON.stringify({
        type: 'mouse_context',
        page: pageNum,
        nearest_cell: cell,
        mouse_pos: state.cursorContext.pos,
        nearest_text: state.cursorContext.nearestText,
        timestamp: now
      }));
    }
  });
}

function findNearestText(screenX, screenY, textLayerDiv) {
  const spans = textLayerDiv.querySelectorAll('span');
  if (!spans.length) return '';

  let minDist = Infinity;
  let nearestStr = '';

  for (let i = 0; i < spans.length; i++) {
    const s = spans[i];
    const text = s.textContent.trim();
    if (!text || text.length < 3) continue;

    const sLeft = parseFloat(s.style.left) || 0;
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
  const anchor = cellToCoords(schema.anchor_cell || 'E1', pdfPtWidth, true);
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

  // 1. Resaltados
  if (highlightsGroup && Array.isArray(pdata.highlights)) {
    pdata.highlights.forEach(hl => {
      if (Array.isArray(hl.rects)) {
        hl.rects.forEach(r => {
          if (!Array.isArray(r) || r.length < 4) return;
          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x', r[0]);
          rect.setAttribute('y', r[1]);
          rect.setAttribute('width', Math.max(0, r[2] - r[0]));
          rect.setAttribute('height', Math.max(0, r[3] - r[1]));
          rect.setAttribute('fill', hl.color || '#fef08a');
          rect.setAttribute('class', 'highlight-rect');
          highlightsGroup.appendChild(rect);
        });
      }
    });
  }

  // 2. Llaves de agrupación
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

  // 4. Notas del margen
  if (notesGroup && Array.isArray(pdata.annotations)) {
    pdata.annotations.forEach(note => {
      renderMarginNote(notesGroup, note, pdfPtWidth);
    });
  }

  // 5. Esquemas
  if (schemasGroup && Array.isArray(pdata.schemas)) {
    pdata.schemas.forEach(schema => {
      if (schema) renderSchemaTree(schemasGroup, schema, pdfPtWidth);
    });
  }
}

function renderMarginNote(notesGroup, note, pdfPtWidth) {
  const coords = cellToCoords(note.cell, pdfPtWidth, true);
  note.x = coords.x;
  note.y = coords.y;

  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', 'margin-note');
  group.setAttribute('transform', `translate(${coords.x}, ${coords.y})`);

  const w = note.width || 250;
  const h = note.height || 62;

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
  body.textContent = note.text;
  group.appendChild(body);

  notesGroup.appendChild(group);
}

function renderBracketGroup(bracketsGroup, br, pdfPtWidth) {
  const yStart = Number(br.y_start) || 100;
  const yEnd = Number(br.y_end) || 250;
  const yMid = (yStart + yEnd) / 2;
  const x = Number(br.x) || (pdfPtWidth - 12);
  const w = 10;
  const r = 8;

  const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', 'bracket-group');

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
// Ejecutor de Comandos y Herramientas (Function Calling)
// ─────────────────────────────────────────────────────────────────────────────

function executeVoiceCommand(command, args = {}) {
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
        schema.edges.push({ from: parent_node_id, to: new_node.id });
        refreshCurrentPageSvg(curPage);
        saveNotesToServer();
      }
      break;
    }

    case 'highlight_passage': {
      const targetText = (args.target_text || '').toLowerCase().trim();
      const color = args.color || '#fef08a';
      if (!targetText) break;

      const pageContainer = document.getElementById(`page-container-${curPage}`);
      if (!pageContainer) break;

      const textLayer = pageContainer.querySelector('.textLayer');
      const spans = textLayer ? textLayer.querySelectorAll('span') : [];
      let candidateMatches = [];

      spans.forEach(span => {
        const spanText = span.textContent.toLowerCase();
        if (spanText.includes(targetText)) {
          const sLeft = (parseFloat(span.style.left) || 0) / state.scale;
          const sTop = (parseFloat(span.style.top) || 0) / state.scale;
          const sWidth = ((parseFloat(span.style.width) || (span.textContent.length * 7))) / state.scale;
          const sHeight = ((parseFloat(span.style.fontSize) || 12)) / state.scale;

          const cx = sLeft + sWidth / 2;
          const cy = sTop + sHeight / 2;
          const dist = Math.hypot(state.cursorContext.pos[0] - cx, state.cursorContext.pos[1] - cy);

          candidateMatches.push({
            rect: [sLeft, sTop, sLeft + sWidth, sTop + sHeight],
            dist: dist
          });
        }
      });

      let matchedRects = [];
      if (candidateMatches.length > 0) {
        // Desambiguar eligiendo el pasaje más cercano al cursor del ratón
        candidateMatches.sort((a, b) => a.dist - b.dist);
        matchedRects.push(candidateMatches[0].rect);
      } else {
        // Fallback aproximado a la altura del cursor
        const mx = Math.min(state.cursorContext.pos[0] || 50, pdfPtWidth - 200);
        const my = state.cursorContext.pos[1] || 120;
        matchedRects.push([mx, my - 4, mx + 220, my + 14]);
      }

      pageNotes.highlights.push({
        id: `hl_${Date.now()}`,
        text: targetText,
        color: color,
        rects: matchedRects
      });

      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_margin_note': {
      pageNotes.annotations.push({
        id: `note_${Date.now()}`,
        cell: args.cell || state.cursorContext.cell || 'F4',
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
      const startCell = args.start_cell || 'A5';
      const endCell = args.end_cell || 'A10';
      const startCoords = cellToCoords(startCell, pdfPtWidth, false);
      const endCoords = cellToCoords(endCell, pdfPtWidth, false);

      pageNotes.brackets.push({
        id: `br_${Date.now()}`,
        start_cell: startCell,
        end_cell: endCell,
        y_start: startCoords.y,
        y_end: endCoords.y + CELL_HEIGHT,
        x: pdfPtWidth - 12,
        label: args.label || 'Grupo temático'
      });
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

    case 'add_stamp_symbol': {
      const cellCoords = cellToCoords(args.cell || 'A2', pdfPtWidth, false);
      pageNotes.stamps.push({
        id: `stamp_${Date.now()}`,
        cell: args.cell || 'A2',
        x: cellCoords.x + 6,
        y: cellCoords.y + 6,
        symbol: args.symbol || '⚠️',
        label: args.label || ''
      });
      refreshCurrentPageSvg(curPage);
      saveNotesToServer();
      break;
    }

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
    await fetch(`/api/notes/${state.docId}`, {
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
          executeVoiceCommand(data.command, data.args);
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
      const resp = await fetch('/api/upload', { method: 'POST', body: formData });
      if (resp.ok) {
        await refreshDocumentList();
        await loadDocument(file.name);
      } else {
        alert('Error al subir el archivo PDF.');
      }
    } catch (err) {
      alert(`Error al subir: ${err.message}`);
    } finally {
      btnUpload.textContent = '📁';
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

  // Guardar notas
  document.getElementById('btn-save').addEventListener('click', () => {
    saveNotesToServer();
    alert('Notas guardadas en el archivo sidecar JSON.');
  });

  // Exportar PDF
  document.getElementById('btn-export').addEventListener('click', async () => {
    const btn = document.getElementById('btn-export');
    btn.textContent = '⏳ Compilando...';
    btn.disabled = true;

    try {
      const resp = await fetch(`/api/export/${state.docId}`, { method: 'POST' });
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
      }
    });
  });

  // Envío manual desde input del simulador
  document.getElementById('btn-send-sim').addEventListener('click', () => {
    const input = document.getElementById('sim-input');
    try {
      const payload = JSON.parse(input.value.trim());
      executeVoiceCommand(payload.command, payload.args || {});
      input.value = '';
    } catch (e) {
      alert(`JSON no válido: ${e.message}`);
    }
  });

  // Atajos de teclado
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'g' || e.key === 'G') {
      executeVoiceCommand('activate_grid', { show: !state.showGrid });
    } else if (e.key === 'r' || e.key === 'R') {
      executeVoiceCommand('toggle_active_recall', { enabled: !state.activeRecall });
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      executeVoiceCommand('undo_last_action');
    }
  });
}

// Iniciar aplicación al cargar el DOM
window.addEventListener('DOMContentLoaded', initApp);

# Cambios hechos por Delta

Cada entrada es una petición de voz que Delta (Gemini Live) pasó a Claude Code con `mejorar_delta`.

## 2026-10-21 02:25 · vía Delta (Gemini Live → Claude Code)

**Petición:** pon el modo oscuro

**Claude:** El panel y el escritorio ya están en oscuro (BreezeDark y `prefer-dark`), así que lo que le falta a Delta es una herramienta para cambiar el tema por voz. La añado.Ahora la novedad, la chuleta y la prueba (aplico «activar», que no cambia nada porque ya está en oscuro).El panel y el escritorio ya estaban en modo oscuro (BreezeDark), así que le he dado a Delta la herramienta `modo_oscuro`, que pasa KDE y las aplicaciones a oscuro o a claro, o dice cuál está puesto; también está anotada en novedades y en la chuleta. La he probado y funciona, pero hace falta reiniciar Delta para que pueda usarla por voz, porque recargar el panel no basta.

```
acciones.py          | 16 +++++++++++++++-
 panel/index.html     |  2 +-
 panel/novedades.json |  7 ++++++-
 3 files changed, 22 insertions(+), 3 deletions(-)
```

Ver: `git diff refs/delta/20261021-022506/antes refs/delta/20261021-022506/despues` · Deshacer: `git diff refs/delta/20261021-022506/antes refs/delta/20261021-022506/despues | git apply -R`

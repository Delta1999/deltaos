"""Umbrales de alerta del sistema: una sola fuente para proactivo.py (Delta habla) y el panel (se pone rojo)."""
CALOR_PANEL = 85    # °C: el panel se pone rojo
CALOR = 88          # °C: Delta lo dice en voz alta, un escalón por encima
RAM_ALTA = 95       # % (8 GB: el 86 % es lo normal en esta máquina)
SWAP_ALTA = 70      # % — con la RAM llena pero sin swap tocada no pasa nada


def para_panel():
    return {"temp": CALOR_PANEL, "ram": RAM_ALTA, "swap": SWAP_ALTA}

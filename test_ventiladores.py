"""Comprobaciones del control ThinkPad sin escribir en el hardware."""
import deltaos


def test_parsea_niveles_validos_y_rechaza_otros():
    assert deltaos._nivel_ventilador("auto") == "auto"
    assert deltaos._nivel_ventilador("7") == "7"
    assert deltaos._nivel_ventilador("full-speed") == "full-speed"
    assert deltaos._nivel_ventilador("disengaged") == "disengaged"
    for nivel in ("8", "9", "enable", "0; reboot"):
        try:
            deltaos._nivel_ventilador(nivel)
        except ValueError:
            continue
        raise AssertionError(f"Nivel no admitido: {nivel}")


def test_parsea_temperature_hwmon():
    assert deltaos._temperatura_hwmon("42000\n") == 42
    assert deltaos._temperatura_hwmon("no disponible\n") is None


if __name__ == "__main__":
    test_parsea_niveles_validos_y_rechaza_otros()
    test_parsea_temperature_hwmon()
    print("✓ test_ventiladores: ok")

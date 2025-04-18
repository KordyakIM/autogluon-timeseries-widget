import os
import sysconfig

# Путь к справке, если она есть
WIDGET_HELP_PATH = os.path.join(
    sysconfig.get_path("data"),
    "share", "help", "orange3-autogluon-timeseries"
)
# Настройки категории
ICON = "icons/ItemTimeSeries.png"
PRIORITY = 0  # Чем выше число, тем ниже в списке
BACKGROUND = "#f0f0f0"  # Фоновый цвет категории

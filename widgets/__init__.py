import Orange.widgets
from .widget_autogluon import OWAutoGluonTimeSeries

print("=== ЗАГРУЗКА AutoGluon TimeSeries ВИДЖЕТА ===")

try:
    if hasattr(Orange.widgets, "category_from_package_globals"):
        category = Orange.widgets.category_from_package_globals(package=__name__)
        category.widgets.append(OWAutoGluonTimeSeries)
        print("=== Виджет зарегистрирован через category_from_package_globals ===")
    else:
        print("⚠ Ошибка: Способ регистрации не найден")
except Exception as e:
	print(f"⚠ Ошибка при регистрации виджета: {e}")

print("=== AutoGluon TimeSeries загружен, но НЕ зарегистрирован ===")

# AutoGluon TimeSeries Widget for Orange3

Прогнозирование временных рядов с помощью [AutoGluon TimeSeries](https://auto.gluon.ai/stable/) через интерфейс [Orange3](https://orange.biolab.si/).

## 🧠 Возможности

- Поддержка пользовательских столбцов и частоты
- Автоопределение частоты временного ряда
- Настройка метрики и длины прогноза
- Учет праздничных дней
- Очистка от отрицательных и некорректных значений
- Удобный лог и вывод модели

## 🧪 Зависимости

- Orange3 >= 3.38
- AutoGluon >= 1.2.0
- pandas == 2.2.3
- Python 3.9+
- numpy >= 1.25
- PyQt5 >= 5.15
- matplotlib >= 3.5

## 🚀 Установка

```bash
git clone https://github.com/KordyakIM/autogluon-timeseries-widget.git
cd autogluon-timeseries-widget
pip install .
```
or
```bash
pip install orange3-autogluon-timeseries
```

## 📦 Добавление виджета в Orange если устанавливаешь вручную

Скопируйте папку `widget` в директорию пользовательских виджетов Orange:
```bash
mkdir -p ~/orange3-widgets/autogluon_timeseries
cp -r widget/* ~/orange3-widgets/autogluon_timeseries/
```

## 📝 Лицензия

MIT License

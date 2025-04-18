import logging
import os
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets import gui, settings
from Orange.data import Table, Domain, ContinuousVariable, StringVariable, TimeVariable, Variable
import pandas as pd
import numpy as np
import tempfile
from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame
from datetime import datetime, timedelta
from pathlib import Path
import traceback
from Orange.widgets.utils.widgetpreview import WidgetPreview
from PyQt5.QtWidgets import QPlainTextEdit, QCheckBox, QComboBox, QLabel
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QFont
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OWAutoGluonTimeSeries(OWWidget):
    name = "AutoGluon TimeSeries"
    description = "Прогнозирование временных рядов с AutoGluon"
    icon = "icons/autogluon.png"
    priority = 100
    keywords = ["timeseries", "forecast", "autogluon"]

    # Настройки
    prediction_length = settings.Setting(10)
    time_limit = settings.Setting(60)
    selected_metric = settings.Setting("MAE")
    selected_preset = settings.Setting("best_quality")
    target_column = settings.Setting("sales")
    id_column = settings.Setting("item_id")
    timestamp_column = settings.Setting("timestamp")
    include_holidays = settings.Setting(False)
    use_current_date = settings.Setting(True)  # Настройка для использования текущей даты
    frequency = settings.Setting("D")  # Частота для прогноза (по умолчанию дни)
    auto_frequency = settings.Setting(True)  # Автоопределение частоты
    selected_model = settings.Setting("auto") # выбор моделей

    # Метрики
    METRICS = ["MAE", "MAPE", "MSE", "RMSE", "WQL"]
    
    # Частоты
    FREQUENCIES = [
        ("D", "День"),
        ("W", "Неделя"),
        ("M", "Месяц"),
        ("Q", "Квартал"),
        ("Y", "Год"),
        ("H", "Час"),
        ("T", "Минута"),
        ("B", "Рабочий день")
    ]

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        prediction = Output("Prediction", Table)
        leaderboard = Output("Leaderboard", Table)
        model_info = Output("Model Info", Table)
        log_messages = Output("Log", str)

    def __init__(self):
        super().__init__()
        self.data = None
        self.predictor = None
        self.log_messages = ""
        self.detected_frequency = "D"  # Определенная частота данных по умолчанию
        self.setup_ui()
        self.warning("")
        self.error("")
        self.log("Виджет инициализирован")
        
        # Данные для валидации длины прогноза
        self.max_allowed_prediction = 0
        self.data_length = 0

    def setup_ui(self):
        # Основные параметры
        box = gui.widgetBox(self.controlArea, "Параметры")
        self.prediction_spin = gui.spin(box, self, "prediction_length", 1, 365, 1, label="Длина прогноза:")
        self.prediction_spin.valueChanged.connect(self.on_prediction_length_changed)
        
        # Добавляем информационную метку о максимальной длине прогноза
        self.max_length_label = QLabel("Максимальная длина прогноза: N/A")
        box.layout().addWidget(self.max_length_label)
        
        gui.spin(box, self, "time_limit", 10, 86400, 10, label="Лимит времени (сек):")
        
        # Используем строки для метрик
        self.metric_combo = gui.comboBox(box, self, "selected_metric", 
                    items=self.METRICS,
                    label="Метрика:")
        
        gui.comboBox(box, self, "selected_preset",
                    items=["best_quality", "high_quality", "medium_quality", "fast_training"],
                    label="Пресет:")

        # Настройки столбцов
        col_box = gui.widgetBox(self.controlArea, "Столбцы")
        # Хранение всех колонок для выпадающего списка
        self.all_columns = []
        
        # Целевая переменная
        self.target_combo = gui.comboBox(col_box, self, "target_column", label="Целевая:", items=[])
        # ID ряда
        self.id_combo = gui.comboBox(col_box, self, "id_column", label="ID ряда:", items=[])
        # Временная метка
        self.timestamp_combo = gui.comboBox(col_box, self, "timestamp_column", label="Время:", items=[])
        
        # Настройки частоты
        freq_box = gui.widgetBox(self.controlArea, "Частота временного ряда")
        
        # Чекбокс для автоопределения частоты
        self.auto_freq_checkbox = QCheckBox("Автоматически определять частоту")
        self.auto_freq_checkbox.setChecked(self.auto_frequency)
        self.auto_freq_checkbox.stateChanged.connect(self.on_auto_frequency_changed)
        freq_box.layout().addWidget(self.auto_freq_checkbox)
        
        # Выпадающий список частот
        self.freq_combo = gui.comboBox(freq_box, self, "frequency", 
                      items=[f[0] for f in self.FREQUENCIES], 
                      label="Частота:")
        # Заменяем технические обозначения на понятные названия
        for i, (code, label) in enumerate(self.FREQUENCIES):
            self.freq_combo.setItemText(i, f"{label} ({code})")
        
        # Отключаем комбобокс, если автоопределение включено
        self.freq_combo.setDisabled(self.auto_frequency)
        
        # Метка для отображения определенной частоты
        self.detected_freq_label = QLabel("Определенная частота: N/A")
        freq_box.layout().addWidget(self.detected_freq_label)

        # Дополнительные настройки
        extra_box = gui.widgetBox(self.controlArea, "Дополнительно")
        self.holidays_checkbox = QCheckBox("Учитывать праздники")
        self.holidays_checkbox.setChecked(self.include_holidays)
        self.holidays_checkbox.stateChanged.connect(self.on_holidays_changed)
        extra_box.layout().addWidget(self.holidays_checkbox)
        
        # Настройка для принудительного использования текущей даты
        self.date_checkbox = QCheckBox("Использовать текущую дату (игнорировать даты в данных)")
        self.date_checkbox.setChecked(self.use_current_date)
        self.date_checkbox.stateChanged.connect(self.on_date_option_changed)
        extra_box.layout().addWidget(self.date_checkbox)
        
        # Добавляем выбор моделей
        self.model_selector = gui.comboBox(
            extra_box, self, "selected_model",
            items=["auto", "DirectTabular", "ETS", "DeepAR", "MLP", "TemporalFusionTransformer", "TiDE"],
            label="Модель:",
            sendSelectedValue=True  # ⬅️ вот это ключевое!
        )
        # Кнопка и логи
        self.run_button = gui.button(self.controlArea, self, "Запустить", callback=self.run_model)
        
        log_box = gui.widgetBox(self.controlArea, "Логи")
        self.log_widget = QPlainTextEdit(readOnly=True)
        self.log_widget.setMinimumHeight(200)
        log_box.layout().addWidget(self.log_widget)

    def on_holidays_changed(self, state):
        self.include_holidays = state > 0

    def on_date_option_changed(self, state):
        self.use_current_date = state > 0
        
    def on_auto_frequency_changed(self, state):
        self.auto_frequency = state > 0
        self.freq_combo.setDisabled(self.auto_frequency)
        if self.auto_frequency and self.data is not None:
            self.detected_freq_label.setText(f"Определенная частота: {self.detected_frequency}")
        
    def on_prediction_length_changed(self, value):
        """Проверяет валидность выбранной длины прогноза"""
        if self.data_length > 0:
            # Обновляем интерфейс и проверяем валидность
            self.check_prediction_length()

    def detect_frequency(self, data):
        """Определяет частоту временного ряда на основе данных"""
        try:
            # Сортируем даты
            dates = data[self.timestamp_column].sort_values()
            
            # Если меньше 2 точек, невозможно определить
            if len(dates) < 2:
                return "D"  # По умолчанию день
                
            # Вычисляем разницу между последовательными датами
            diffs = []
            for i in range(1, min(10, len(dates))):
                diff = dates.iloc[i] - dates.iloc[i-1]
                diffs.append(diff.total_seconds())
                
            # Используем медиану для определения типичного интервала
            if not diffs:
                return "D"
                
            median_diff = pd.Series(diffs).median()
            
            # Определяем частоту на основе интервала
            if median_diff <= 60:  # до 1 минуты
                freq = "T"
            elif median_diff <= 3600:  # до 1 часа
                freq = "H"
            elif median_diff <= 86400:  # до 1 дня
                freq = "D"
            elif median_diff <= 604800:  # до 1 недели
                freq = "W"
            elif median_diff <= 2678400:  # до ~1 месяца (31 день)
                freq = "M"
            elif median_diff <= 7948800:  # до ~3 месяцев (92 дня)
                freq = "Q"
            else:  # более 3 месяцев
                freq = "Y"
                
            self.log(f"Определена частота данных: {freq} (медианный интервал: {median_diff/3600:.1f} часов)")
            return freq
            
        except Exception as e:
            self.log(f"Ошибка при определении частоты: {str(e)}")
            return "D"  # По умолчанию день

    def check_prediction_length(self):
        """Проверяет длину прогноза и обновляет интерфейс"""
        if self.data_length == 0:
            return
            
        # Корректируем формулу расчета максимальной длины прогноза
        # Предыдущая формула: max(1, (self.data_length - 3) // 2)
        # Новая формула: более либеральная для данных средней длины
        
        if self.data_length <= 10:
            # Для очень коротких временных рядов очень строгое ограничение
            self.max_allowed_prediction = max(1, self.data_length // 3)
        elif self.data_length <= 30:
            # Для средних временных рядов - более либеральное ограничение
            # Для 21 строки: (21 - 1) // 2 = 10
            self.max_allowed_prediction = max(1, (self.data_length - 1) // 2)
        else:
            # Для длинных временных рядов - стандартное ограничение
            self.max_allowed_prediction = max(1, (self.data_length - 3) // 2)
            
        self.max_length_label.setText(f"Максимальная длина прогноза: {self.max_allowed_prediction}")
        
        # Проверка текущего значения
        if self.prediction_length > self.max_allowed_prediction:
            self.warning(f"Длина прогноза слишком велика для ваших данных. Максимум: {self.max_allowed_prediction}")
            # Визуальное предупреждение
            self.max_length_label.setStyleSheet("color: red; font-weight: bold")
            # Отключаем кнопку запуска, если прогноз слишком длинный
            self.run_button.setDisabled(True)
        else:
            self.warning("")
            self.max_length_label.setStyleSheet("")
            self.run_button.setDisabled(False)

    def log(self, message):
        """Надежное логирование"""
        log_entry = f"{datetime.now().strftime('%H:%M:%S')} - {message}"
        self.log_messages += log_entry + "\n"
        self.log_widget.appendPlainText(log_entry)
        self.log_widget.verticalScrollBar().setValue(
            self.log_widget.verticalScrollBar().maximum()
        )
        QCoreApplication.processEvents()

    @Inputs.data
    def set_data(self, dataset):
        self.error("")
        self.warning("")
        try:
            if dataset is None:
                self.data = None
                self.log("Данные очищены")
                self.data_length = 0
                self.max_length_label.setText("Максимальная длина прогноза: N/A")
                self.detected_freq_label.setText("Определенная частота: N/A")
                return
                
            self.log("Обработка входных данных...")
            self.data = self.prepare_data(dataset)

            # Обновление выпадающих списков колонок
            self.all_columns = list(self.data.columns)
            
            # Обновляем comboBox'ы
            self.target_combo.clear()
            self.id_combo.clear()
            self.timestamp_combo.clear()
            
            self.target_combo.addItems(self.all_columns)
            self.id_combo.addItems(self.all_columns)
            self.timestamp_combo.addItems(self.all_columns)
            
            # Установка выбранных значений
            if self.target_column in self.all_columns:
                self.target_combo.setCurrentText(self.target_column)
            else:
                self.target_column = self.all_columns[0]
            
            if self.id_column in self.all_columns:
                self.id_combo.setCurrentText(self.id_column)
            else:
                self.id_column = self.all_columns[0]
            
            if self.timestamp_column in self.all_columns:
                self.timestamp_combo.setCurrentText(self.timestamp_column)
            else:
                self.timestamp_column = self.all_columns[0]
            
            required = {self.timestamp_column, self.target_column, self.id_column}
            if not required.issubset(set(self.data.columns)):
                missing = required - set(self.data.columns)
                raise ValueError(f"Отсутствуют столбцы: {missing}")
                
            # Получаем длину данных
            self.data_length = len(self.data)
            self.log(f"Загружено {self.data_length} записей")
            
            # Определяем частоту данных
            if pd.api.types.is_datetime64_dtype(self.data[self.timestamp_column]):
                self.detected_frequency = self.detect_frequency(self.data)
                self.detected_freq_label.setText(f"Определенная частота: {self.detected_frequency}")
            
            # Обновляем максимальную длину прогноза
            self.check_prediction_length()
            
            # Если нужно заменить даты на текущую
            if self.use_current_date and self.timestamp_column in self.data.columns:
                self.log("Применяется замена дат на актуальные")
                
                # Получаем частоту
                freq = self.detected_frequency if self.auto_frequency else self.frequency
                
                try:
                    # Создаем даты от сегодня назад с нужной частотой
                    today = pd.Timestamp.now().normalize()
                    dates = pd.date_range(end=today, periods=len(self.data), freq=freq)
                    dates = dates.sort_values()  # Сортируем от ранних к поздним
                    
                    # Заменяем столбец времени
                    self.data[self.timestamp_column] = dates
                    self.log(f"Даты заменены: от {dates.min().strftime('%Y-%m-%d')} до {dates.max().strftime('%Y-%m-%d')}")
                except Exception as e:
                    self.log(f"Ошибка при создании дат с частотой {freq}: {str(e)}. Используем ежедневную частоту.")
                    # Резервный вариант - ежедневная частота
                    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=len(self.data), freq='D')
                    self.data[self.timestamp_column] = dates
            
        except Exception as e:
            self.log(f"ОШИБКА: {str(e)}\n{traceback.format_exc()}")
            self.error(f"Ошибка данных: {str(e)}")
            self.data = None
            self.data_length = 0
            self.max_length_label.setText("Максимальная длина прогноза: N/A")

    def prepare_data(self, table):
        """Подготовка данных"""
        domain = table.domain
        # Получаем атрибуты
        attr_cols = [var.name for var in domain.attributes]
        df = pd.DataFrame(table.X, columns=attr_cols)
        
        # Добавляем классы, если есть
        if domain.class_vars:
            class_cols = [var.name for var in domain.class_vars]
            class_data = table.Y
            if len(domain.class_vars) == 1:
                class_data = class_data.reshape(-1, 1)
            df_class = pd.DataFrame(class_data, columns=class_cols)
            df = pd.concat([df, df_class], axis=1)
        
        # Добавляем мета-атрибуты
        if domain.metas:
            meta_cols = [var.name for var in domain.metas]
            meta_data = table.metas
            df_meta = pd.DataFrame(meta_data, columns=meta_cols)
            df = pd.concat([df, df_meta], axis=1)
        
        # Преобразование типов
        try:
            df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column], errors="coerce")
        except:
            # Если прямое преобразование не работает, попробуем другой подход
            self.log(f"Попытка альтернативного преобразования столбца {self.timestamp_column}")
            if pd.api.types.is_numeric_dtype(df[self.timestamp_column]):
                df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column], unit='s')
            elif isinstance(df[self.timestamp_column].iloc[0], str):
                # Попробуем несколько форматов
                for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y', '%Y/%m/%d']:
                    try:
                        df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column], format=fmt)
                        break
                    except:
                        continue
        
        df[self.target_column] = pd.to_numeric(df[self.target_column], errors="coerce")
        df[self.id_column] = df[self.id_column].astype(str)
        
        return df.dropna(subset=[self.timestamp_column, self.target_column, self.id_column])

    def create_future_dates(self, periods):
        """Создает будущие даты с учетом нужной частоты"""
        today = pd.Timestamp.now().normalize()
        
        # Получаем частоту
        freq = self.detected_frequency if self.auto_frequency else self.frequency
        self.log(f"Создание будущих дат от {today} с частотой {freq}")
        
        try:
            # Создаем даты с нужной частотой
            if freq == 'B':  # Для рабочих дней нужна особая обработка
                # Создаем дневной диапазон и фильтруем выходные
                all_dates = pd.date_range(start=today + pd.Timedelta(days=1), periods=periods * 2, freq='D')
                # Фильтруем только рабочие дни (понедельник-пятница)
                business_dates = all_dates[all_dates.weekday < 5][:periods]
                dates = business_dates
            else:
                # Для остальных частот просто используем pandas
                # Начинаем с завтра (сегодня + 1 единица выбранной частоты)
                if freq == 'D':
                    start_date = today + pd.Timedelta(days=1)
                elif freq == 'W':
                    start_date = today + pd.Timedelta(weeks=1)
                elif freq == 'M':
                    start_date = today + pd.DateOffset(months=1)
                elif freq == 'Q':
                    start_date = today + pd.DateOffset(months=3)
                elif freq == 'Y':
                    start_date = today + pd.DateOffset(years=1)
                elif freq in ['H', 'T']:
                    # Для часов и минут начинаем с завтра
                    start_date = today + pd.Timedelta(days=1)
                else:
                    start_date = today + pd.Timedelta(days=1)
                    
                # Создаем диапазон дат с указанной частотой
                dates = pd.date_range(start=start_date, periods=periods, freq=freq)
        except Exception as e:
            self.log(f"Ошибка при создании дат с частотой {freq}: {str(e)}. Используем ежедневную.")
            dates = pd.date_range(start=today + pd.Timedelta(days=1), periods=periods, freq='D')
        
        self.log(f"Создан диапазон дат: с {dates[0].strftime('%Y-%m-%d')} по {dates[-1].strftime('%Y-%m-%d')}")
        return dates

    def run_model(self):
        if self.data is None:
            self.error("Нет данных")
            self.log("Ошибка: данные не загружены")
            return
            
        # Дополнительная проверка длины прогноза перед запуском
        if self.prediction_length > self.max_allowed_prediction and self.max_allowed_prediction > 0:
            self.error(f"Длина прогноза ({self.prediction_length}) превышает максимально допустимую ({self.max_allowed_prediction}) для ваших данных. Уменьшите длину прогноза.")
            self.log(f"ОШИБКА: Длина прогноза слишком велика. Максимум: {self.max_allowed_prediction}")
            return
            
        self.progressBarInit()
        try:
            self.log_widget.clear()
            self.log("=== НАЧАЛО ===")
            
            # Подготовка данных
            self.log("Преобразование в TimeSeriesDataFrame...")
            df_sorted = self.data.sort_values([self.id_column, self.timestamp_column])
            
            # Проверяем, что столбцы имеют правильные типы
            self.log(f"Типы данных: {df_sorted.dtypes.to_dict()}")
            
            # Определяем частоту для модели
            model_freq = self.detected_frequency if self.auto_frequency else self.frequency
            self.log(f"Используемая частота: {model_freq}")
            
            # Преобразуем в формат TimeSeriesDataFrame
            ts_data = TimeSeriesDataFrame.from_data_frame(
                df_sorted,
                id_column=self.id_column,
                timestamp_column=self.timestamp_column
            )
            
            # Пытаемся установить частоту после создания
            try:
                if model_freq != 'D':
                    self.log(f"Установка частоты временного ряда: {model_freq}")
                    ts_data = ts_data.asfreq(model_freq)
            except Exception as freq_err:
                self.log(f"Ошибка при установке частоты {model_freq}: {str(freq_err)}. Используем дневную частоту.")
            
            self.log(f"Создан временной ряд с {len(ts_data)} записями")
            
            # Обучение
            with tempfile.TemporaryDirectory() as temp_dir:
                model_path = Path(temp_dir)

                # 🛠️ Создаём папку для логов, иначе будет FileNotFoundError
                log_dir = model_path / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)

                self.log(f"Начало обучения модели, время: {self.time_limit} сек...")
                
                # Настройка конфигурации
                config = {}
                if self.include_holidays:
                    config['holiday_lookups'] = ["RU"]  # праздничные дни
                
                # Получение метрики (убеждаемся, что это строка)
                metric = self.selected_metric
                if isinstance(metric, int) and 0 <= metric < len(self.METRICS):
                    metric = self.METRICS[metric]
                self.log(f"Используемая метрика: {metric}")
                # проверка модели
                models = None
                if self.selected_model != "auto":
                    models = [self.selected_model]
                try:
                    # Создание предиктора
                    predictor = TimeSeriesPredictor(
                        path=model_path,
                        prediction_length=self.prediction_length,
                        target=self.target_column,
                        eval_metric=metric.lower()
                    )
                    
                    # Обучение
                    fit_args = {
                        "presets": self.selected_preset,
                        "time_limit": self.time_limit,
                        **config
                    }
                    
                    # Если выбрана конкретная модель — задаём через hyperparameters
                    if self.selected_model != "auto":
                        fit_args["hyperparameters"] = {self.selected_model: {}}
                        
                    # сбрасываем старый логгер, чтобы не пытался писать в удалённую папку
                    import logging

                    logger = logging.getLogger("autogluon")
                    for handler in logger.handlers[:]:
                        try:
                            handler.close()
                        except:
                            pass
                        logger.removeHandler(handler)
                    
                    predictor.fit(
                        ts_data,
                        **fit_args
                    )
                    
                except ValueError as ve:
                    if "must have >=" in str(ve):
                        # Обрабатываем ошибку длины данных
                        self.error(f"Недостаточно данных для выбранной длины прогноза. {str(ve)}")
                        self.log(f"ОШИБКА: {str(ve)}")
                        self.progressBarFinished()
                        return
                    else:
                        raise
                
                # Прогнозирование
                self.log("Выполнение прогноза...")
                predictions = predictor.predict(ts_data)
                
                # Преобразование результата
                try:
                    pred_df = predictions.reset_index()
                    self.log(f"Получен прогноз с {len(pred_df)} записями")
                    
                    # Убедимся, что все колонки имеют уникальные имена
                    cols = list(pred_df.columns)
                    for i, col in enumerate(cols):
                        count = cols[:i].count(col)
                        if count > 0:
                            new_name = f"{col}_{count}"
                            self.log(f"Переименование дублирующейся колонки: {col} -> {new_name}")
                            pred_df = pred_df.rename(columns={col: new_name})
                    
                    # Создаем новый DataFrame для прогноза с актуальными датами
                    self.log("Создание нового DataFrame для прогноза с актуальными датами")
                    forecast_df = pd.DataFrame()
                    
                    # Копируем идентификатор
                    if self.id_column in pred_df.columns:
                        forecast_df[self.id_column] = pred_df[self.id_column]
                    
                    # Используем текущую дату как основу для прогноза с нужной частотой
                    new_dates = self.create_future_dates(len(pred_df))
                    forecast_df['timestamp'] = [d.strftime('%Y-%m-%d') for d in new_dates]
                    
                    # Копируем прогнозные значения
                    for col in pred_df.columns:
                        if col not in [self.id_column, 'timestamp'] and pd.api.types.is_numeric_dtype(pred_df[col]):
                            #forecast_df[col] = pred_df[col].round(3)
                            forecast_df[col] = pred_df[col].round(0).astype(int)  # без e-формата, целые числа
                            
                    # 🧼 Очистка: убираем отрицательные значения и округляем
                    numeric_cols = forecast_df.select_dtypes(include=np.number).columns
                    forecast_df[numeric_cols] = forecast_df[numeric_cols].clip(lower=0).round(0)

                    # Логирование результатов
                    self.log(f"Структура итогового прогноза: {forecast_df.dtypes}")
                    self.log(f"Пример прогноза:\n{forecast_df.head(3).to_string()}")
                    
                    # Используем новый DataFrame вместо исходного
                    pred_df = forecast_df.copy()
                
                except Exception as e:
                    self.log(f"Ошибка при подготовке прогноза: {str(e)}\n{traceback.format_exc()}")
                
                # Отправка результатов
                self.log("Преобразование прогноза в таблицу Orange...")
                pred_table = self.df_to_table(pred_df)
                self.Outputs.prediction.send(pred_table)
                
                # Лидерборд
                try:
                    lb = predictor.leaderboard()
                    if lb is not None and not lb.empty:
                        self.log("Формирование лидерборда...")
                        # Округление числовых значений для улучшения читаемости
                        for col in lb.select_dtypes(include=['float']).columns:
                            lb[col] = lb[col].round(4)
                        
                        # Проверяем/исправляем имена колонок
                        lb.columns = [str(col).replace(' ', '_').replace('-', '_') for col in lb.columns]
                        
                        # Преобразуем все объектные колонки в строки
                        for col in lb.select_dtypes(include=['object']).columns:
                            lb[col] = lb[col].astype(str)
                            
                        self.log(f"Структура лидерборда: {lb.dtypes}")
                        
                        lb_table = self.df_to_table(lb)
                        self.Outputs.leaderboard.send(lb_table)
                except Exception as lb_err:
                    self.log(f"Ошибка лидерборда: {str(lb_err)}\n{traceback.format_exc()}")
                
                # Инфо о модели
                self.log("Формирование информации о модели...")
                
                # Получаем понятное название частоты
                freq_name = model_freq
                for code, label in self.FREQUENCIES:
                    if code == model_freq:
                        freq_name = f"{label} ({code})"
                        break
                
                # Получаем лучшую модель, если лидерборд доступен
                best_model_name = "Неизвестно"
                best_model_score = "Н/Д"
                
                try:
                    if 'lb' in locals() and lb is not None and not lb.empty:
                        best_model_name = lb.iloc[0]['model']
                        best_model_score = f"{lb.iloc[0]['score_val']:.4f}"
                        
                        # Логируем информацию о лучших моделях
                        self.log(f"Лучшая модель: {best_model_name}, Оценка: {best_model_score}")
                        
                        # Показываем топ-3 модели если их столько есть
                        if len(lb) > 1:
                            self.log("Топ модели:")
                            for i in range(min(3, len(lb))):
                                model = lb.iloc[i]['model']
                                score = lb.iloc[i]['score_val']
                                self.log(f"  {i+1}. {model}: {score:.4f}")
                except Exception as e:
                    self.log(f"Не удалось получить информацию о лучшей модели: {str(e)}")
                
                # Создаем расширенную информацию о модели
                model_info = pd.DataFrame({
                    'Parameter': ['Версия', 'Цель', 'Длина', 'Метрика', 'Пресет', 
                                'Время', 'Праздники', 'Даты', 'Частота', 'Лучшая модель', 'Оценка модели'],
                    'Value': ['1.2.0', self.target_column, str(self.prediction_length),
                              metric, self.selected_preset, 
                              f"{self.time_limit} сек", 
                              "Включены" if self.include_holidays else "Отключены",
                              "Текущие" if self.use_current_date else "Исходные",
                              freq_name,
                              best_model_name,
                              best_model_score]
                })
                self.Outputs.model_info.send(self.df_to_table(model_info))
                
                # Закрываем логгеры, чтобы не было WinError 32
                import logging
                logging.shutdown()
                
            self.log("=== УСПЕШНО ===")
            
        except Exception as e:
            self.log(f"ОШИБКА: {str(e)}\n{traceback.format_exc()}")
            self.error(str(e))
        finally:
            self.progressBarFinished()
            # Отправляем журнал
            self.Outputs.log_messages.send(self.log_messages)

    def df_to_table(self, df):
        """Безопасное преобразование DataFrame в таблицу Orange"""
        try:
            # Убедимся, что DataFrame не содержит индексов
            df = df.reset_index(drop=True).copy()
            
            # Раздельные списки для атрибутов, классов и мета-переменных
            attrs = []
            metas = []
            
            # Безопасное преобразование всех типов данных и создание соответствующих переменных
            X_cols = []  # Для непрерывных переменных (атрибутов)
            M_cols = []  # Для строковых переменных (мета)
            
            for col in df.columns:
                # Обрабатываем числовые данные - идут в X
                if pd.api.types.is_numeric_dtype(df[col]):
                    # Преобразуем в float, который Orange может обработать
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(float('nan')).astype(float)
                    attrs.append(ContinuousVariable(name=str(col)))
                    X_cols.append(col)
                else:
                    # Все нечисловые данные идут в мета
                    # Обрабатываем даты
                    if pd.api.types.is_datetime64_dtype(df[col]):
                        df[col] = df[col].dt.strftime('%Y-%m-%d')
                    
                    # Все остальное - в строки
                    df[col] = df[col].fillna('').astype(str)
                    metas.append(StringVariable(name=str(col)))
                    M_cols.append(col)
            
            self.log(f"Атрибуты: {[v.name for v in attrs]}")
            self.log(f"Мета: {[v.name for v in metas]}")
            
            # Создаем домен
            domain = Domain(attrs, metas=metas)
            
            # Создаем массивы для X и M
            if X_cols:
                X = df[X_cols].values
            else:
                X = np.zeros((len(df), 0))
                
            if M_cols:
                M = df[M_cols].values
            else:
                M = np.zeros((len(df), 0), dtype=object)
            
            # Создаем таблицу с помощью from_numpy
            return Table.from_numpy(domain, X, metas=M)
            
        except Exception as e:
            self.log(f"Ошибка преобразования DataFrame в Table: {str(e)}\n{traceback.format_exc()}")
            raise

if __name__ == "__main__":
    WidgetPreview(OWAutoGluonTimeSeries).run()
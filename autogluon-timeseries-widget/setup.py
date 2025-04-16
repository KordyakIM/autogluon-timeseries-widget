from setuptools import setup, find_packages

setup(
    name="orange3-autogluon-timeseries",
    version="1.0.0",
    description="AutoGluon Time Series forecasting widget for Orange3",
    author="Иван Кордяк",
    author_email="KordyakIM@gmail.com",
    url="https://github.com/KordyakIM/autogluon-timeseries-widget",
    license="MIT",
    packages=find_packages(),
    package_data={
        "orangecontrib.autogluon_timeseries.widgets": ["*.py", "*.png"],
    },
    entry_points={
        "orange.widgets": (
            "AutoGluonTimeSeries = orangecontrib.autogluon_timeseries.widgets"
        ),
        "orange.canvas.help": (
            "html-index = orangecontrib.autogluon_timeseries.widgets:help"
        )
    },
    install_requires=[
        "Orange3>=3.38.1",
        "autogluon.timeseries==1.2",
        "pandas==2.2.3",
        "numpy>=1.25"
    ],
    classifiers=[
        "Framework :: Orange3",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
    ]
)

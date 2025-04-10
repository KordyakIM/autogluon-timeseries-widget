from setuptools import setup, find_packages

setup(
    name='autogluon-timeseries-widget',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'pandas==1.5.3',
        'numpy==1.22.4',
        'orange3==3.38.0',
        'autogluon.timeseries==1.2.0',
        'PyQt5>=5.15'
    ],
    include_package_data=True,
    description='AutoGluon TimeSeries Widget for Orange3',
    author='Иван',
    license='MIT',
)

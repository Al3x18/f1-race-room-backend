# About

Backend server written with [Flask](https://flask.palletsprojects.com/en/stable/) in Python used to get telemetry data with [Fast-F1](https://github.com/theOehrly/Fast-F1) library and then send a PDF file generated with Matplotlib to custom application.

## Required Dependencies

To run the backend server, you need to install the following dependencies:

- **Flask**: A lightweight WSGI web application framework for Python.
- **Fast-F1**: A Python library to easily access Formula 1 telemetry data.
- **Matplotlib**: A comprehensive library for creating static, animated, and interactive visualizations in Python.

### List of Required Libraries

```bash
flask
fastf1
matplotlib
uwsgi
```

## Usage

To start the server, run the following command in the terminal:

```bash
uwsgi --ini uwsgi.ini
```

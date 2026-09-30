@echo off
rem Pronostico diario de TimesFM 3.0 en papel y puntuacion de los vencidos (investigacion personal no comercial).
rem Lo lanza el Programador de tareas de Windows tras el cierre diario de las 00:00 UTC; los reintentos no
rem recargan el modelo si el pronostico de ese cierre ya existe.
cd /d "%~dp0.."
set PYTHONPATH=%CD%
if not exist data\raw\tsfm mkdir data\raw\tsfm
echo ==== %DATE% %TIME% >> data\raw\tsfm\log.txt
"C:\TimesFM_Research\.venv\Scripts\python.exe" -m tools.tsfm_forecast --out data\raw\tsfm >> data\raw\tsfm\log.txt 2>&1
"C:\Python314\python.exe" -m tools.tsfm_ingest --dir data\raw\tsfm --insert >> data\raw\tsfm\log.txt 2>&1

"""
Віддалений сервер аналізу флоту.

Запускається ОКРЕМО від станцій (GCS).
Одна інстанція сервера обслуговує будь-яку кількість станцій.

Запуск:
    python -m server.main --port 8090
  або
    python scripts/start_analysis_server.py --port 8090 --vineyard-weights model.pt
"""

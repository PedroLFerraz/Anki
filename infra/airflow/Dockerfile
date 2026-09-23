# Airflow plus AnkiGen. The package is installed into the image rather than
# mounted, so the DAG imports it like any other library and the image is
# self-contained.
FROM apache/airflow:3.3.2

COPY --chown=airflow:root pyproject.toml /opt/ankigen/
COPY --chown=airflow:root src /opt/ankigen/src

USER airflow
RUN pip install --no-cache-dir /opt/ankigen

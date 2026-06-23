FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin shipvoice

COPY --chown=shipvoice:shipvoice . /app
RUN mkdir -p /app/results/runtime && chown -R shipvoice:shipvoice /app/results

EXPOSE 8022

USER shipvoice

CMD ["python", "run_app.py", "--host", "0.0.0.0", "--port", "8022", "--no-auto-port"]

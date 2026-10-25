FROM python:3.12.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY model.zip /tmp/model.zip
RUN echo "912e288c90a1ee1294a65bb6051780fed18497d4f736fc70153308c20c1df08b  /tmp/model.zip" | sha256sum -c -
RUN python -m zipfile -e /tmp/model.zip /tmp/unpacked && mv /tmp/unpacked/cashcast-risk-sr04-frozen-r3 /model
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
RUN python /model/predict.py --verify
COPY risk_http.py /app/risk_http.py
COPY smoke.py /app/smoke.py
USER 10002:10002
EXPOSE 8765
CMD ["python", "/app/risk_http.py"]

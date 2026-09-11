ARG CONTROL_BASE_IMAGE=python:3.12-slim
FROM ${CONTROL_BASE_IMAGE}
WORKDIR /opt/pr-pipeline
COPY deploy/cloud/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt && groupadd -g 2000 prpipeline && useradd -u 10001 -g prpipeline pipeline
COPY *.py ./
COPY static ./static
COPY web/dist ./web/dist
USER 10001:2000
EXPOSE 8792
ENTRYPOINT ["python", "cloud_entry.py", "--config", "/etc/pr-pipeline/config.toml"]
CMD ["control"]

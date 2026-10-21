FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

LABEL org.opencontainers.image.title="Agent Manager Security Worker" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Tencent/AI-Infra-Guard" \
      org.opencontainers.image.revision="e8931cc68001b66ad024fd87ef07394e9e96524a"

RUN useradd --create-home --uid 10001 worker
WORKDIR /app
COPY services/agent-security-worker/vendor/ai-infra-guard /opt/ai-infra-guard
COPY services/agent-security-worker/constraints.txt /opt/agent-security-worker-constraints.txt
COPY services/agent-security-worker/verify_vendor_tree.py /opt/verify_vendor_tree.py
COPY deploy/agent-security/upstreams.lock.json /opt/agent-security-upstreams.lock.json
RUN cd /opt/ai-infra-guard && \
    python /opt/verify_vendor_tree.py --lock /opt/agent-security-upstreams.lock.json --vendor-base /opt/ai-infra-guard --component agent-scan --component mcp-scan && \
    echo "6b4b9a4bd1f7107f47059bac748a94e98600c7d69411f74ce35823a1430aeace  agent-scan/agent_scan/core/agent_adapter/providers.yaml" | sha256sum -c - && \
    echo "5c57fd31f08515bac290c3f958df4289a2017d5a90b17cdf283b22dee2f79dca  agent-scan/agent_scan/core/agent_adapter/adapter.py" | sha256sum -c - && \
    echo "a2ad10f92a5ad0180fecd5f17ea5ef2d90335426e1a323b4035380fec359606e  agent-scan/requirements.txt" | sha256sum -c - && \
    echo "e0b60652f34807bf2cb5243d052404857c2ee146d857c04e5969a7dcb7073248  agent-scan/agent_scan/utils/logging.py" | sha256sum -c - && \
    echo "81124cfb04fa9377e23f5e26ffda1ab14849579c11182f693f7b63be7d09a9f8  mcp-scan/requirements.txt" | sha256sum -c - && \
    echo "780cea963b136d48738ac1bd960c2d674182e92ffe38f9778055c3915ede80a2  mcp-scan/mcp_scan/utils/mcp_tools.py" | sha256sum -c - && \
    echo "5d42a127192e32bd07b4333cca5e10c2f1493f0125b0f631988a7c519caa8e76  mcp-scan/mcp_scan/tools/mcp_tool/mcp_tool.py" | sha256sum -c - && \
    echo "e1a0d434e0fc10499c30b83f4451cb871c9d18f0a5f2eb0fbb607d5c639f22f3  mcp-scan/pyproject.toml" | sha256sum -c - && \
    echo "e77b34bf79aede74ad23d3fe9b54bfd24e428fdf70e1359d2e846966cc08f138  LICENSE" | sha256sum -c - && \
    echo "be0c75e8cfae06146b93e7de77f21e72c4a50a8b9ca0f5496d8c75e2ffccd577  NOTICE" | sha256sum -c -
RUN pip install --no-cache-dir -c /opt/agent-security-worker-constraints.txt \
        -r /opt/ai-infra-guard/agent-scan/requirements.txt \
        -r /opt/ai-infra-guard/mcp-scan/requirements.txt "cryptography==46.0.6" && \
    pip install --no-cache-dir --no-deps /opt/ai-infra-guard/agent-scan /opt/ai-infra-guard/mcp-scan
COPY services/agent-security-worker/worker.py /app/worker.py
COPY services/agent-security-worker/connection_probe.py /app/connection_probe.py
COPY agent_manager/security_redaction.py /app/security_redaction.py
COPY services/agent-security-worker/aig_adapter.py /app/aig_adapter.py
COPY services/agent-security-worker/mcp_adapter.py /app/mcp_adapter.py
COPY services/agent-security-worker/mcp_executor.py /app/mcp_executor.py
COPY services/agent-security-worker/aig_service_client.py /app/aig_service_client.py
COPY services/agent-security-worker/aig_scan_common.py /app/aig_scan_common.py
COPY services/agent-security-worker/llm_redteam_adapter.py /app/llm_redteam_adapter.py
COPY services/agent-security-worker/ai_infrastructure_adapter.py /app/ai_infrastructure_adapter.py
COPY services/agent-security-worker/dify_inventory_adapter.py /app/dify_inventory_adapter.py
COPY agent_manager/__init__.py agent_manager/security_redaction.py /app/agent_manager/
COPY agent_manager/core/__init__.py agent_manager/core/dify_console_client.py agent_manager/core/mcp_parameter_risk.py /app/agent_manager/core/
COPY agent_manager/core/dify_inventory /app/agent_manager/core/dify_inventory
COPY services/agent-security-worker/credential_envelope.py /app/credential_envelope.py
COPY services/agent-security-worker/generate_sbom.py /app/generate_sbom.py
RUN mkdir -p /app/licenses && \
    cp /opt/ai-infra-guard/LICENSE /opt/ai-infra-guard/NOTICE /app/licenses/ && \
    python /app/generate_sbom.py /app/licenses/sbom.spdx.json && \
    chown -R 10001:10001 /app

USER 10001:10001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "/app/worker.py", "--healthcheck"]
ENTRYPOINT ["python", "/app/worker.py"]

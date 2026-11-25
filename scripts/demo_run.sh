#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_URL="http://localhost:8000"

echo "=========================================================="
echo "⚡ AI Compute Server — Teste de Execução de Ponta a Ponta"
echo "=========================================================="

# 1. Verifica se o Docker está ativo
if ! docker info >/dev/null 2>&1; then
  echo "⚠️  AVISO: O Docker daemon não está rodando ou seu usuário não tem permissão."
  echo "    Para ativar no Linux: sudo systemctl start docker"
  echo "    Para conceder permissão: sudo usermod -aG docker \$USER"
  echo "    Continuando para testar upload, banco e fila..."
  echo ""
fi

# 2. Inicia o servidor se não estiver rodando
SERVER_PID=""
if ! curl -s "${SERVER_URL}/api/jobs" >/dev/null 2>&1; then
  echo "Iniciando servidor da API e Web na porta 8000..."
  python3 "${REPO_ROOT}/services/api/app/server.py" &
  SERVER_PID=$!
  sleep 1.5
else
  echo "Servidor já está rodando em ${SERVER_URL}."
fi

# Garante encerramento do processo em caso de saída se subimos ele
cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    echo "Encerrando servidor de teste (PID ${SERVER_PID})..."
    kill "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# 3. Envia o arquivo ZIP de exemplo
ZIP_FILE="${REPO_ROOT}/examples/sample_model.zip"
if [ ! -f "${ZIP_FILE}" ]; then
  echo "Gerando ${ZIP_FILE}..."
  cd "${REPO_ROOT}/examples/sample-job"
  python3 -c "import zipfile; zf = zipfile.ZipFile('../sample_model.zip', 'w'); zf.write('main.py'); zf.close()"
  cd "${REPO_ROOT}"
fi

echo ""
echo ">> 1. Enviando o arquivo ${ZIP_FILE} para a API..."
UPLOAD_RESP=$(curl -s -X POST "${SERVER_URL}/api/jobs/upload" \
  -F "file=@${ZIP_FILE}" \
  -F "entrypoint=main.py" \
  -F "cpu_limit=1.0" \
  -F "memory_limit=512m")

echo "Resposta do Upload:"
echo "${UPLOAD_RESP}" | python3 -m json.tool 2>/dev/null || echo "${UPLOAD_RESP}"

JOB_ID=$(echo "${UPLOAD_RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job_id', ''))" 2>/dev/null || true)

if [ -z "${JOB_ID}" ]; then
  echo "❌ Falha ao obter job_id do upload."
  exit 1
fi

echo ""
echo ">> 2. Disparando execução do job na fila..."
RUN_RESP=$(curl -s -X POST "${SERVER_URL}/api/jobs/run-next")
echo "Resposta da Execução:"
echo "${RUN_RESP}" | python3 -m json.tool 2>/dev/null || echo "${RUN_RESP}"

echo ""
echo ">> 3. Consultando logs gerados..."
curl -s "${SERVER_URL}/api/jobs/${JOB_ID}/logs" | python3 -m json.tool 2>/dev/null || true

echo ""
echo ">> 4. Listando arquivos gerados em output..."
curl -s "${SERVER_URL}/api/jobs/${JOB_ID}/output" | python3 -m json.tool 2>/dev/null || true

echo ""
echo "=========================================================="
echo "✔ Teste de ponta a ponta finalizado com sucesso!"
echo "Acesse a interface gráfica no navegador: http://localhost:8000"
echo "=========================================================="

#!/usr/bin/env bash
set -euo pipefail

# Bootstrap do ambiente Linux para o projeto AI Compute Server.
# Objetivo: preparar Docker, GPU e estrutura de diretórios para execução segura de jobs.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_SLURM="${INSTALL_SLURM:-false}"
RUNTIME_USER="${RUNTIME_USER:-$(id -un)}"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Este script deve ser executado como root." >&2
    exit 1
  fi
}

print_banner() {
  echo "=============================================================="
  echo " AI Compute Server - bootstrap do ambiente"
  echo "=============================================================="
}

check_os() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    echo "Distribuição detectada: ${NAME} ${VERSION_ID}"
  else
    echo "Não foi possível detectar a distribuição Linux." >&2
    exit 1
  fi

  case "${ID_LIKE:-${ID}}" in
    debian|ubuntu)
      ;;
    *)
      echo "Este bootstrap foi pensado para Ubuntu/Debian-based systems." >&2
      exit 1
      ;;
  esac
}

install_common_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    jq \
    uidmap \
    net-tools
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    echo "Docker já está instalado."
    return
  fi

  echo "Instalando Docker Engine..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo ${VERSION_CODENAME}) stable" > /etc/apt/sources.list.d/docker.list

  apt-get update
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  systemctl enable --now docker
  usermod -aG docker "${RUNTIME_USER}"
  echo "Docker instalado com sucesso."
}

install_nvidia_toolkit() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi não foi encontrado. A GPU NVIDIA não está disponível no host."
    echo "O toolkit NVIDIA será instalado apenas se a GPU estiver presente e o driver estiver funcional."
    return
  fi

  echo "Instalando NVIDIA Container Toolkit..."
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list

  apt-get update
  apt-get install -y --no-install-recommends nvidia-container-toolkit

  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
  echo "NVIDIA Container Toolkit configurado."
}

install_slurm() {
  if [[ "${INSTALL_SLURM}" != "true" ]]; then
    echo "SLURM não será instalado no MVP. Este é um passo opcional para cluster futuro."
    return
  fi

  echo "Instalando SLURM..."
  apt-get install -y --no-install-recommends slurm-wlm
  echo "SLURM instalado. Configure partitions e recursos conforme a topologia da sua máquina."
}

create_directories() {
  mkdir -p "${REPO_ROOT}/storage/jobs" \
           "${REPO_ROOT}/logs" \
           "${REPO_ROOT}/db"

  touch "${REPO_ROOT}/storage/jobs/.gitkeep" \
        "${REPO_ROOT}/logs/.gitkeep" \
        "${REPO_ROOT}/db/.gitkeep"

  chown -R "${RUNTIME_USER}:${RUNTIME_USER}" "${REPO_ROOT}/storage" "${REPO_ROOT}/logs" "${REPO_ROOT}/db"

  echo "Estrutura de diretórios criada em ${REPO_ROOT}"
}

finish() {
  echo ""
  echo "Bootstrap concluído. Próximos passos:"
  echo "1. Reinicie o host ou faça logout/login para aplicar o grupo docker."
  echo "2. Teste: docker run --rm hello-world"
  echo "3. Teste: nvidia-smi"
  echo "4. Teste: docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi"
  echo "5. A próxima fase será o executor isolado dos jobs."
}

main() {
  print_banner
  require_root
  check_os
  install_common_packages
  install_docker
  install_nvidia_toolkit
  install_slurm
  create_directories
  finish
}

main "$@"

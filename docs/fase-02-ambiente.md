# Fase 2 — Ambiente base

## Objetivo

Preparar o host Linux para executar trabalhos de IA em containers com isolamento, controle de recursos e compatibilidade com GPU NVIDIA.

## Componentes envolvidos

- Ubuntu Server ou Debian-based Linux;
- Docker Engine;
- NVIDIA Container Toolkit;
- estrutura de diretórios do projeto;
- usuários e permissões do sistema;
- configuração opcional do SLURM para ambientes de cluster futuro.

## Arquivos que serão criados/ajustados

- infra/system/bootstrap-host.sh
- infra/system/README.md
- .gitignore
- storage/jobs/.gitkeep
- logs/.gitkeep
- db/.gitkeep

## Tecnologias utilizadas

- Linux;
- Docker;
- NVIDIA Container Toolkit;
- systemd;
- bash scripting;
- SLURM (opcional, no futuro ou em cenários mais avançados).

## Como testar

### 1. Verificar o sistema

```bash
uname -a
lsb_release -a
```

### 2. Verificar Docker

```bash
docker --version
docker info
```

### 3. Verificar GPU no host

```bash
nvidia-smi
```

### 4. Verificar runtime NVIDIA dentro do container

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 5. Validar a estrutura do projeto

```bash
find . -maxdepth 3 -type d | sort
```

## Critérios para considerar a fase concluída

A fase está concluída quando:

- o host está rodando uma distribuição Linux suportada;
- Docker está instalado e funcional;
- a GPU NVIDIA está visível ao host;
- o NVIDIA Container Toolkit está configurado;
- a estrutura de diretórios do projeto foi criada;
- a política de isolamento por job foi documentada;
- o ambiente está pronto para a próxima fase de execução de containers.

## Observações importantes

### Docker

Docker é a base do isolamento para o MVP. Ele resolve o problema de executar código potencialmente inseguro em um ambiente controlado e separado do host.

### NVIDIA Container Toolkit

A GPU deve ser disponibilizada ao container de forma controlada, nunca diretamente ao código do usuário em modo irrestrito.

### SLURM

SLURM é útil para escalonamento e cluster, mas não é obrigatório para o MVP. Em um ambiente local, a fila própria e o controle do Docker podem ser suficientes e muito mais simples.

## Próxima etapa

A próxima etapa é a Fase 3: Executor isolado, onde o sistema começa a empacotar um job em um ambiente controlado com mount de input, workspace e output.

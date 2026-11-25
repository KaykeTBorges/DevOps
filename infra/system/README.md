# Sistema

Este diretório reúne os artefatos do host Linux para preparar a máquina principal para execução segura de workloads de IA.

## Objetivo

Garantir que o servidor local tenha:

- Ubuntu/Debian funcional;
- Docker instalado e configurado;
- NVIDIA Container Toolkit quando houver GPU;
- diretórios de armazenamento para jobs;
- permissões e organização adequadas;
- suporte futuro a SLURM em cenários mais avançados.

## Script de bootstrap

O arquivo principal é:

- infra/system/bootstrap-host.sh

Ele automatiza:

- verificação da distribuição Linux;
- instalação de pacotes básicos do sistema;
- instalação do Docker Engine;
- instalação do NVIDIA Container Toolkit quando a GPU está disponível;
- criação da estrutura de diretórios para jobs, logs e banco;
- opções para instalar SLURM apenas quando desejado.

## Uso

```bash
sudo bash infra/system/bootstrap-host.sh
```

Para instalar SLURM no fluxo do bootstrap:

```bash
sudo INSTALL_SLURM=true bash infra/system/bootstrap-host.sh
```

## Observações importantes

- O SLURM é opcional neste projeto e não deve ser considerado obrigatório no MVP.
- Para um cenário local simples, o Docker + fila própria é mais adequado e mais fácil de manter.
- A GPU deve ser acessada apenas pelo container através do toolkit NVIDIA, nunca pelo host de forma irrestrita.

## Próxima fase

A próxima etapa é a criação do executor isolado dos jobs em containers, com estrutura de input, workspace, output e logs.

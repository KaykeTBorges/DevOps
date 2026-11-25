# Roadmap do projeto

## Fase 1 — Arquitetura

Objetivo:

Definir requisitos, componentes, fluxo de jobs, modelo de segurança e decisões de MVP.

Componentes:

- documentação de arquitetura;
- decisões de tecnologias;
- definição de fluxo e limites do sistema.

Arquivos esperados:

- docs/architecture.md
- docs/security.md
- README.md

Tecnologias:

- documentação, diagramas, revisão de requisitos.

Teste:

- revisão crítica do fluxo geral;
- verificação dos requisitos de segurança;
- confirmação da escolha de Docker + fila local como MVP.

Critério de conclusão:

- arquitetura definida e alinhada com requisitos de segurança e crescimento futuro.

## Fase 2 — Ambiente base

Objetivo:

Preparar o host Linux para execução segura de jobs em containers.

Componentes:

- Ubuntu Server/Debian;
- Docker Engine;
- NVIDIA Container Toolkit;
- diretórios de jobs, banco e logs;
- permissões e organização do host.

Arquivos esperados:

- infra/system/bootstrap-host.sh
- infra/system/README.md
- docs/fase-02-ambiente.md

Tecnologias:

- Linux;
- Docker;
- NVIDIA Container Toolkit;
- bash scripting;
- systemd.

Teste:

- docker --version
- docker info
- nvidia-smi
- docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

Critério de conclusão:

- host preparado;
- Docker funcionando;
- GPU disponível ao host e ao runtime do container;
- estrutura de diretórios pronta para a próxima fase.

## Fase 3 — Executor isolado

Objetivo:

Implementar execução em container com diretórios e limites mínimos.

Componentes:

- executor em Python;
- job root com input, workspace, output e logs;
- container Docker com rede isolada;
- limites de CPU, memória e tempo;
- logs e metadata por job.

Arquivos esperados:

- services/job-manager/executor/job_executor.py
- services/job-manager/executor/test_job_executor.py
- docs/fase-03-executor.md

Tecnologias:

- Python;
- Docker;
- cgroups;
- Linux runtime.

Teste:

- execução de container de teste;
- criação do layout de diretórios;
- validação de timeout e saída;
- verificação de limites de rede e recursos.

Critério de conclusão:

- um job é executado em ambiente isolado;
- logs e output são gravados corretamente;
- o sistema organiza os diretórios por job;
- o executor falha com segurança quando os limites são excedidos.

## Fase 4 — Fila e scheduler

Objetivo:

Organizar jobs em fila e controlar ordem de execução.

Componentes:

- fila de jobs;
- status do job;
- scheduler simples;
- execução sequencial do próximo job;
- atualização de status e logs.

Arquivos esperados:

- services/job-manager/queue/queue_manager.py
- services/job-manager/queue/test_queue_manager.py
- services/job-manager/scheduler/scheduler.py
- docs/fase-04-fila.md

Tecnologias:

- Python;
- estruturas de dados em memória;
- subprocess;
- enumeração de estados.

Teste:

- verificar FIFO da fila;
- confirmar a execução do próximo job;
- confirmar status completed/failed/timeout;
- validar a interação com o executor isolado.

Critério de conclusão:

- a fila organiza os jobs corretamente;
- o scheduler executa o próximo item em ordem;
- o status do job é atualizado ao longo do fluxo;
- a execução continua segura e isolada.

## Fase 5 — Backend API

Objetivo:

Criar endpoints para receber, consultar e monitorar jobs.

Componentes:

- camada de serviço da API;
- registro de jobs;
- consulta de status e logs;
- listagem geral e remoção;
- integração com a fila e com o executor.

Arquivos esperados:

- services/api/app/job_api.py
- services/api/app/test_job_api.py
- docs/fase-05-api.md

Tecnologias:

- Python;
- classes de serviço;
- integração com o queue manager.

Teste:

- criar um job;
- listar jobs;
- consultar status;
- executar o próximo job;
- verificar logs e output.

Critério de conclusão:

- o sistema expõe a API de gestão do job de forma consistente;
- a API integra corretamente com a fila e o executor;
- a gestão de jobs fica separada da lógica de execução.

## Fase 6 — Upload e validação do ZIP

Objetivo:

Receber, validar e extrair o projeto com segurança.

Componentes:

- validação de extensão e tamanho;
- detecção de ZIP bomb;
- rejeição de path traversal;
- rejeição de symlinks;
- extração segura em diretório isolado do job.

Arquivos esperados:

- services/api/app/job_upload.py
- services/api/app/test_job_upload.py
- docs/fase-06-upload.md

Tecnologias:

- Python;
- zipfile;
- validação defensiva de arquivos.

Teste:

- ZIP válido;
- ZIP com path traversal;
- ZIP bomb indireto;
- entrada com symlink;
- limite máximo de arquivos e tamanho.

Critério de conclusão:

- apenas zips válidos e seguros são aceitos;
- arquivos perigosos são rejeitados antes da extração;
- os arquivos entram em um diretório exclusivo do job, sem risco de atingir o host.

## Fase 7 — Banco de dados

Objetivo:

Persistir estados, metadata e logs.

Componentes:

- SQLite inicial;
- tabela de jobs;
- status por job;
- timestamps, metadata e output path;
- atualização de estado e remoção.

Arquivos esperados:

- services/api/app/job_store.py
- services/api/app/test_job_store.py
- docs/fase-07-banco.md

Tecnologias:

- SQLite;
- Python;
- JSON para dados flexíveis.

Teste:

- criar job;
- listar jobs;
- atualizar status;
- remover registro;
- verificar armazenamento persistente em banco local.

Critério de conclusão:

- os jobs ficam persistidos em banco local;
- estados e timestamps são confiáveis;
- os dados básicos do fluxo do projeto ficam organizados e acessíveis.

## Fase 8 — Frontend

Objetivo:

Criar interface para upload e acompanhamento.

## Fase 9 — Persistência e limpeza

Objetivo:

Implementar retenção de 7 dias e remover arquivos automaticamente.

## Fase 10 — Segurança e hardening

Objetivo:

Validar isolamento real do job e a impossibilidade de acesso ao host.

## Fase 11 — Monitoramento

Objetivo:

Exibir CPU, RAM, GPU, tempo e logs.

## Fase 12 — Testes de robustez

Objetivo:

Validar comportamento em cenários de falha e abuso.

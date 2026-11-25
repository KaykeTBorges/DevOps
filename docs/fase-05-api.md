# Fase 5 — API

## Objetivo

Expor a camada de controle do sistema por meio de endpoints que permitam:

- criar jobs;
- listar jobs;
- consultar status;
- acessar logs;
- consultar output;
- remover jobs;
- acionar a execução do próximo item da fila.

## Componentes envolvidos

- backend API;
- camada de serviço da aplicação;
- integração com JobQueue;
- integração com JobScheduler;
- uso do executor isolado como peça central.

## Arquivos criados

- services/api/app/job_api.py
- services/api/app/test_job_api.py
- services/api/app/README.md

## Tecnologias utilizadas

- Python 3;
- classes de serviço;
- integração direta com o queue manager e o scheduler;
- estrutura simples e pronta para evolução para FastAPI ou Flask no futuro.

## Endpoints esperados

A API do MVP expõe as operações de forma simples e explícita:

- POST /api/jobs
- GET /api/jobs
- GET /api/jobs/{id}
- GET /api/jobs/{id}/status
- GET /api/jobs/{id}/logs
- GET /api/jobs/{id}/output
- DELETE /api/jobs/{id}

## Como testar

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 -m unittest services/api/app/test_job_api.py
```

## Critérios para considerar a fase concluída

A fase está concluída quando:

- um job pode ser criado via serviço da API;
- a lista de jobs funciona;
- o status pode ser consultado;
- o próximo job pode ser disparado;
- logs e output são lidos corretamente;
- jobs podem ser removidos da fila e do armazenamento.

## Observação de evolução

Embora o MVP utilize uma camada de serviço Python simples, a API pode evoluir futuramente para FastAPI ou Flask sem alterar o núcleo de negócio.

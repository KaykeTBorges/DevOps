# Fase 7 — Banco de dados

## Objetivo

Persistir os dados do sistema em um banco leve e suficiente para o MVP, armazenando todos os jobs, seus estados e metadata básica.

## Componentes envolvidos

- SQLite;
- tabela de jobs;
- timestamps e metadados;
- status do workflow;
- dados de saída e limpeza.

## Arquivos criados

- services/api/app/job_store.py
- services/api/app/test_job_store.py

## Tecnologias utilizadas

- SQLite;
- Python;
- JSON para metadata;
- timestamp em UTC.

## Estrutura inicial da tabela

A tabela `jobs` armazena:

- job_id;
- user_id;
- filename;
- status;
- created_at;
- started_at;
- finished_at;
- expiration_at;
- entrypoint;
- command;
- arguments;
- image;
- container_id;
- slurm_job_id;
- exit_code;
- error_message;
- output_path;
- cpu_limit;
- memory_limit;
- gpu_limit;
- timeout_seconds;
- metadata_json.

## Como testar

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 -m unittest services/api/app/test_job_store.py
```

## Critérios para considerar a fase concluída

A fase está concluída quando:

- o banco é criado automaticamente;
- um job pode ser persistido;
- status e timestamps são atualizados;
- a lista de jobs retorna corretamente;
- a remoção do registro funciona.

## Observação de evolução

SQLite é suficiente para o MVP e para uma máquina local com poucos usuários. Quando o sistema crescer em escala ou concorrência, a migração para PostgreSQL pode ser feita sem reescrever toda a lógica de domínio.

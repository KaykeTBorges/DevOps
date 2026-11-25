# Fase 3 — Executor isolado

## Objetivo

Implementar um executador simples capaz de preparar um job, criar seu ambiente isolado, executar um comando em um container e salvar logs e outputs em diretórios próprios.

## Componentes envolvidos

- executor em Python;
- diretórios por job;
- container Docker;
- limites de CPU, memória e rede;
- logs e metadata.

## Arquivos criados

- services/job-manager/executor/job_executor.py
- services/job-manager/executor/test_job_executor.py
- services/job-manager/executor/README.md

## Tecnologias utilizadas

- Python 3;
- Docker Engine;
- isolamento por container;
- cgroups para recursos;
- estruturas de diretórios por job.

## Estrutura do job

Cada job deve possuir:

```text
job_001/
├── input/
├── workspace/
├── output/
├── logs/
├── metadata/
└── state/
```

## Mecanismo do executor

O executor usa a seguinte lógica:

1. cria os diretórios do job;
2. monta somente input, workspace, output e logs;
3. roda o container em modo read-only para o sistema de arquivos principal;
4. usa usuário não-root;
5. aplica limites de CPU e memória;
6. usa rede `none` por padrão;
7. coleta logs e grava metadata do resultado.

## Como testar

### Teste direto do módulo

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 -m unittest services/job-manager/executor/test_job_executor.py
```

### Execução de smoke test com Docker

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 services/job-manager/executor/job_executor.py \
  --job-id job_001 \
  --job-root /tmp/ai_job_test \
  --image python:3.12-slim \
  --command python -c "print('hello from job')"
```

> O formato acima é aceito porque o parser captura o comando completo após `--command` e permite argumentos que iniciam com hífen, como `-c`.

## Critérios para considerar a fase concluída

A fase está concluída quando:

- o diretório do job é criado corretamente;
- o container roda com recursos limitados;
- o código do job não acessa o host diretamente;
- logs e metadata são salvos;
- a execução pode falhar de forma controlada com código de saída claro.

## Observação de segurança

A execução do container foi pensada para ser segura por padrão, mas ainda precisa ser reforçada em fases posteriores com:

- AppArmor/SELinux;
- seccomp;
- políticas mais rígidas de rede;
- validação de upload;
- isolamento de usuários e grupos;
- monitoramento do job.

# Fase 4 — Fila e scheduler

## Objetivo

Implementar uma fila simples de jobs e um scheduler que execute os trabalhos em ordem, respeitando estados e mantendo a execução em um fluxo controlado.

## Componentes envolvidos

- fila de jobs;
- status do job;
- scheduler;
- execução do executor isolado;
- registro de resultados, código de saída e erros.

## Arquivos criados

- services/job-manager/queue/queue_manager.py
- services/job-manager/queue/test_queue_manager.py
- services/job-manager/scheduler/scheduler.py

## Tecnologias utilizadas

- Python;
- estruturas de dados simples;
- subprocess para chamar o executor;
- enumeração de estados; 
- validação por testes automatizados.

## Estados do job

Os estados mínimos do MVP são:

- pending;
- queued;
- running;
- completed;
- failed;
- cancelled;
- timeout.

## Regras da fila

- o job entra na fila em ordem de criação;
- o scheduler pega o próximo job queued/pending;
- quando um job entra em execução, seu status vira running;
- ao fim da execução, o status vira completed ou failed;
- se houver timeout, marca timeout.

## Testes implementados

O conjunto de testes cobre:

- FIFO da fila;
- identificação correta do próximo job;
- execução do scheduler sobre um job real;
- resultado esperado do executor.

## Como testar

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 -m unittest services/job-manager/queue/test_queue_manager.py
```

## Critérios para considerar a fase concluída

A fase está concluída quando:

- a fila mantém a ordem de entrada;
- o scheduler executa o job seguinte;
- o status do job é atualizado corretamente;
- o executor isolado continua sendo o ator principal da execução;
- o sistema não executa diretamente no host.

## Observação importante

Esta fila é uma primeira camada de orchestration. Ela resolve o problema do MVP local e pode evoluir para um scheduler mais formal, como SLURM, no futuro, sem quebrar o restante da arquitetura.

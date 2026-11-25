# Fase 6 — Upload e validação do ZIP

## Objetivo

Implementar a camada segura de upload do projeto do usuário, validando o ZIP antes da extração e garantindo que o conteúdo entre em um diretório isolado do job.

## Componentes envolvidos

- upload do arquivo ZIP;
- validação de extensão e MIME;
- validação de tamanho e quantidade de arquivos;
- extração segura;
- bloqueio de path traversal, symlinks e arquivos perigosos.

## Arquivos criados

- services/api/app/job_upload.py
- services/api/app/test_job_upload.py

## Tecnologias utilizadas

- Python;
- zipfile;
- pathlib;
- validação defensiva de entrada;
- diretórios isolados por job.

## Regras do MVP

- somente `.zip` é aceito;
- tamanho máximo do arquivo restrito;
- ZIP bomb rejeitado;
- qualquer caminho com `..` é bloqueado;
- links simbólicos são proibidos;
- arquivos ocultos e perfis de diretório anômalos também são rejeitados;
- extração acontece em diretório do job e não no host.

## Como testar

```bash
cd /home/ktb/Desktop/workspace/Pessoal/projeto-devOps
python3 -m unittest services/api/app/test_job_upload.py
```

## Critérios para considerar a fase concluída

A fase está concluída quando:

- ZIP válido é aceito e extraído em diretório isolado;
- ZIP com path traversal é rejeitado;
- ZIP bomb ou grande quantidade de arquivos é rejeitada;
- symlink dentro do ZIP é bloqueado;
- a operação não coloca arquivos fora do job root.

## Observação de segurança

Esta fase reduz muito o risco de entrega de payloads maliciosos ao sistema. No entanto, o ambiente do job continua sendo o principal ponto de isolamento, e as próximas fases continuarão reforçando as regras de hardening.

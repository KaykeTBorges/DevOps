# AI Compute Server — Estado e Operação

## 1. Resumo do projeto

O AI Compute Server é uma plataforma local para receber projetos em ZIP, colocá-los em uma fila e executá-los em containers Docker isolados.

O fluxo principal é:

```text
Usuário autenticado
        |
        v
Upload ZIP + imagem aprovada + timeout
        |
        v
Validação e extração segura
        |
        v
SQLite + fila persistente
        |
        v
Scheduler exclusivo
        |
        v
Container Docker sem rede
        |
        v
Logs + output + retenção automática
```

## 2. Estado atual

### Implementado

- Autenticação por OTP restrita ao domínio `@academico.ufpb.br`.
- Rate limit de solicitação de OTP e limite de tentativas inválidas.
- Tokens de sessão armazenados como hash.
- Autorização por usuário para consultar, cancelar e remover jobs.
- Catálogo fechado de imagens Docker.
- Validação segura de ZIP contra path traversal, symlink, excesso de arquivos e ZIP bomb básica.
- Validação de entrypoint e limpeza de diretório em caso de falha no upload.
- Fila FIFO com reserva transacional no SQLite.
- Proteção contra execução duplicada do mesmo job.
- Timeout, cancelamento e remoção forçada do container.
- Container com rede desativada, usuário não-root, filesystem somente leitura e limites de CPU/RAM/processos.
- Outputs, logs e metadata separados por job.
- Retenção automática de sete dias em background.
- Endpoint público `/api/health`.
- Endpoint autenticado `/api/metrics`.
- Frontend com upload, autenticação, acompanhamento e resumo de métricas.
- Testes unitários, testes HTTP e smoke tests reais com Docker.

### Maturidade atual

O projeto está em estágio de **MVP funcional para ambiente local controlado**. A arquitetura está organizada e os principais fluxos estão integrados, mas ainda não deve ser tratado como uma plataforma de produção exposta diretamente à internet.

## 3. O que ainda falta

### Prioridade alta

1. **Envio real de OTP por e-mail**
   - Integrar SMTP ou provedor de e-mail.
   - Configurar TLS, remetente e tratamento de falhas.
   - Manter o modo de desenvolvimento somente para testes locais.

2. **Testes de abuso mais amplos**
   - Fork bomb.
   - Consumo excessivo de memória.
   - Escrita excessiva em disco.
   - Tentativas de acessar outros jobs.
   - Processos persistentes e encerramento da árvore de processos.

3. **Monitoramento histórico**
   - Persistir métricas ao longo do tempo.
   - Gráficos de CPU, RAM, GPU, disco e fila.
   - Tempo médio de espera e execução.
   - Alertas para jobs presos e containers órfãos.

4. **Operação independente da API**
   - Configurar `systemd timer` ou cron para limpeza mesmo quando a API estiver parada.
   - Criar serviço `systemd` para iniciar e reiniciar o servidor.
   - Registrar logs de operação em arquivo ou journald.

### Prioridade média

5. **Hardening avançado do host**
   - Perfil seccomp customizado.
   - AppArmor ou SELinux.
   - Quota de disco por job.
   - Limites adicionais de I/O e arquivos abertos.
   - Validação de compatibilidade com imagens CUDA/PyTorch.

6. **Imagens imutáveis**
   - Fixar imagens por digest `sha256`.
   - Evitar tags mutáveis como `latest`.
   - Processo de atualização e aprovação do catálogo.

7. **Banco e escalabilidade**
   - Migrações formais do SQLite.
   - Índices adicionais e configuração WAL.
   - Histórico de transições de status.
   - Migração futura para PostgreSQL se houver múltiplos workers ou hosts.

8. **Produção web**
   - HTTPS via Nginx ou Caddy.
   - Firewall e restrição de origem.
   - Headers de segurança.
   - Limites de requisição e conexão reversa.

## 4. Pré-requisitos

### Obrigatórios

- Linux recomendado: Ubuntu ou Debian.
- Python `3.12` ou superior.
- Docker Engine funcionando.
- Usuário com permissão para executar Docker.
- Aproximadamente 1 GB livre para o código e testes básicos.
- Uma imagem Docker aprovada e disponível localmente ou acessível pelo registry.

### Para GPU

- GPU NVIDIA compatível.
- Driver NVIDIA instalado.
- NVIDIA Container Toolkit.
- `nvidia-smi` funcionando no host.
- Imagem CUDA/PyTorch compatível com o driver.

### Verificação rápida

```bash
python3 --version
docker --version
docker info
```

Para GPU:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## 5. Configuração

As configurações administrativas ficam em [config/server_config.py](../config/server_config.py).

As principais variáveis de ambiente são:

| Variável | Padrão | Finalidade |
|---|---:|---|
| `HOST` | `0.0.0.0` | Interface HTTP |
| `PORT` | `8000` | Porta HTTP |
| `DEV_AUTH_MOCK` | `false` | Retorno de OTP apenas em desenvolvimento |
| `OTP_EXPIRATION_SECONDS` | `900` | Validade do OTP |
| `OTP_REQUEST_INTERVAL_SECONDS` | `60` | Intervalo mínimo entre solicitações |
| `OTP_MAX_ATTEMPTS` | `5` | Tentativas inválidas por OTP |
| `ADMIN_HARD_CAP_TIMEOUT` | `14400` | Timeout máximo em segundos |
| `SERVER_CPUS` | `4.0` | CPU administrada |
| `SERVER_MEMORY` | `16g` | Memória administrada |
| `SERVER_GPU_COUNT` | `0` | GPUs disponíveis |
| `SERVER_GPU_DEVICE` | vazio | GPU específica, quando aplicável |
| `ALLOWED_ORIGIN` | `http://localhost:8000` | Origem permitida pelo CORS |

Exemplo para uso local:

```bash
DEV_AUTH_MOCK=true PORT=8000 python3 services/api/app/server.py
```

O modo `DEV_AUTH_MOCK=true` deve ficar restrito a testes locais.

## 6. Como iniciar

Na raiz do projeto:

```bash
python3 services/api/app/server.py
```

Depois acesse:

```text
http://localhost:8000
```

O servidor inicia:

- API HTTP;
- frontend estático;
- worker automático da fila;
- worker automático de retenção;
- recuperação de jobs persistidos após reinício.

## 7. Como usar pelo frontend

1. Abra `http://localhost:8000`.
2. Solicite um OTP com e-mail institucional.
3. Confirme o código recebido.
4. Selecione uma imagem do catálogo.
5. Envie um arquivo `.zip`.
6. Informe o entrypoint, normalmente `main.py`.
7. Defina o timeout dentro dos limites exibidos.
8. Acompanhe status, logs, outputs e métricas.

O projeto enviado deve salvar resultados em:

```text
/job/output
```

As variáveis disponíveis no container são `OUTPUT_DIR`, `WORKSPACE_DIR`, `INPUT_DIR` e `JOB_ID`.

## 8. Como executar pela API

### Solicitar OTP

```bash
curl -X POST http://localhost:8000/api/auth/request-otp \
  -H 'Content-Type: application/json' \
  -d '{"email":"seu.nome@academico.ufpb.br"}'
```

Depois valide o OTP:

```bash
curl -X POST http://localhost:8000/api/auth/verify-otp \
  -H 'Content-Type: application/json' \
  -d '{"email":"seu.nome@academico.ufpb.br","otp":"123456"}'
```

Guarde o campo `token` retornado e use-o nas próximas requisições:

```bash
export AI_COMPUTE_TOKEN='token_recebido'
```

### Ver métricas

```bash
curl http://localhost:8000/api/metrics \
  -H "Authorization: Bearer $AI_COMPUTE_TOKEN"
```

### Ver saúde da aplicação

```bash
curl http://localhost:8000/api/health
```

### Enviar um job

```bash
curl -X POST http://localhost:8000/api/jobs/upload \
  -H "Authorization: Bearer $AI_COMPUTE_TOKEN" \
  -F 'file=@meu_projeto.zip' \
  -F 'entrypoint=main.py' \
  -F 'image_id=python312' \
  -F 'timeout_seconds=300'
```

### Listar jobs do usuário

```bash
curl http://localhost:8000/api/jobs \
  -H "Authorization: Bearer $AI_COMPUTE_TOKEN"
```

## 9. Como testar

Execute a bateria completa:

```bash
python3 services/job-manager/executor/test_job_executor.py && \
python3 services/job-manager/executor/test_docker_isolation.py && \
python3 services/job-manager/queue/test_queue_manager.py && \
python3 services/api/app/test_job_upload.py && \
python3 services/api/app/test_job_store.py && \
python3 services/api/app/test_job_api.py && \
python3 scripts/test_cleanup_jobs.py && \
python3 config/test_server_config.py && \
python3 services/api/app/test_server.py && \
python3 services/api/app/test_etapas_abc.py && \
python3 services/api/app/test_api_security.py
```

O teste Docker pode ser ignorado automaticamente quando Docker ou a imagem `python:3.12-slim` não estiverem disponíveis.

## 10. Estrutura principal

```text
config/                         Configuração administrativa
db/                             SQLite dos jobs
docs/                           Documentação
services/api/app/               API, autenticação e persistência
services/job-manager/executor/ Executor Docker
services/job-manager/queue/    Fila e estados
services/job-manager/scheduler/ Scheduler
services/frontend/web/         Interface web
scripts/                        Limpeza e rotinas auxiliares
storage/jobs/                   Dados temporários por job
```

## 11. Limitações atuais

- O envio de OTP ainda não está conectado a um SMTP real.
- O histórico de métricas ainda não é persistido; `/api/metrics` retorna o estado atual.
- A limpeza automática funciona enquanto o servidor está rodando; para alta disponibilidade, configure um timer externo.
- O smoke test Docker não substitui uma auditoria completa do kernel e do host.
- Não há suporte a múltiplas máquinas ou múltiplos nós ainda.
- Imagens do catálogo ainda devem ser fixadas por digest antes de um ambiente de produção.

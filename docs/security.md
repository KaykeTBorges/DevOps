# Segurança e hardening do MVP

## Premissa

Qualquer projeto enviado por usuário deve ser considerado potencialmente malicioso até que seja validado e executado em um ambiente isolado.

## Ameaças principais

- execução de comandos no host;
- leitura de arquivos do host;
- acesso a diretórios sensíveis como /, /home, /etc;
- uso ilimitado de CPU, memória e GPU;
- montagem de volumes do host dentro do job;
- uso da rede do host de forma irrestrita;
- acesso ao socket do Docker;
- criação de processos persistentes no host;
- tentativa de privilege escalation;
- acesso a outros jobs e arquivos de outros usuários;
- inanição da fila (*queue starvation*) por abuso de tempo de execução;
- injeção de imagens maliciosas ou poisoning de supply-chain via Dockerfile customizado;
- ataques de negação de serviço (DoS) via spam de requisições de e-mail OTP.

## Medidas de proteção

### 1. Autenticação Passwordless e Controle de Acesso
- **Restrição de Domínio:** Apenas e-mails com domínios institucionais permitidos (ex: `@instituicao.edu.br`) conseguem solicitar acesso; e-mails públicos/gratuitos são rejeitados no gateway da API;
- **Tokens Temporários e Descartáveis:** OTPs e Magic Links expiram em 10 a 15 minutos e são invalidados após o primeiro uso;
- **Rate-Limiting de E-mail:** Limite estrito de no máximo 1 solicitação de código a cada 60 segundos por IP e por e-mail para evitar abusos no servidor SMTP;
- **Rastreabilidade Inviolável:** Cada job fica associado irreversivelmente ao e-mail institucional autenticado no SQLite.

### 2. Controle de Imagens (Allowlist Estrita)
- **Bloqueio de Imagens Arbitrárias:** O usuário não tem permissão de digitar o nome de uma imagem ou enviar um `Dockerfile`;
- **Catálogo Fechado de Imagens:** O backend valida estritamente a imagem contra uma lista curada e aprovada pelo administrador;
- **Prevenção de Image Poisoning:** Garante que apenas ambientes auditados, sem ferramentas de ataque ou privilégios indevidos, sejam executados.

### 3. Alocação Exclusiva e Time-Boxing (Prevenção de Abuso e Starvation)
- **Recursos Fixados pelo Administrador:** Cotas de CPU, RAM e GPU são imutáveis pelo usuário;
- **Tempo Máximo Estrito:** O usuário estipula o timeout do job, respeitando um teto máximo inegociável (*hard cap*, ex: 4 horas);
- **Auto-Kill Forçado:** Se o processo exceder o timeout, o executor envia `SIGKILL` imediatamente para liberar a fila;
- **Cotas de Concorrência na Fila:** Para evitar que um único usuário monopolize a máquina, o sistema limita a quantidade de jobs simultaneamente enfileirados por usuário (ex: máx 2 jobs pendentes).

### 4. Isolamento por container

- rodar com usuário não-root;
- evitar `--privileged`;
- remover capacidades extras do container;
- operar com um filesystem mínimo;
- não montar o diretório raiz do host.

### 2. Montagens mínimas

O container deve receber apenas:

- /job/input
- /job/workspace
- /job/output
- /job/logs
- /job/metadata

Ele nunca deve receber:

- /
- /home
- /etc
- /root
- /var/run/docker.sock
- /proc do host
- dispositivos desnecessários

### 3. Limites de recursos

- CPU limitado via cgroups;
- memória limitada via `--memory`;
- tempo de execução limitado via timeout;
- quantidade de processos limitada;
- GPU limitada e gerenciada por scheduler;
- armazenamento limitado por diretório ou quota.

### 4. Rede

- usar `--network none` por padrão;
- permitir uso de rede somente se estritamente necessário;
- não expor serviços do host ao job;
- impedir o job de acessar qualquer rede que não seja controlada.

### 5. Upload do ZIP

- validar extensão .zip;
- validar tamanho máximo;
- rejeitar ZIP bomb;
- rejeitar path traversal;
- rejeitar symlinks e links externos;
- impedir extração em diretório compartilhado;
- extrair somente em workspace isolado do job.

### 6. Limpeza de ambiente

- remover o contêiner ao final;
- zerar ou remover logs temporários;
- não guardar dados além da política de retenção;
- restringir a área de remoção do job ao próprio diretório.

## Riscos que persistem mesmo com Docker

- vulnerabilidade de kernel;
- falha do runtime do container;
- falha no driver NVIDIA;
- má configuração de namespaces, seccomp ou AppArmor;
- contêiner executando com permissões indevidas.

Docker reduz o risco, mas não torna a execução infalível. A segurança precisa estar em camadas.

## Recomendação de hardening

Para o MVP, usar:

- usuário não-root;
- seccomp;
- limitação de capacidades;
- rede isolada;
- quotas de recursos;
- diretrizes de montagem rígidas;
- clean-up automático;
- auditoria dos logs.

## Critério de segurança

Uma fase só deve ser considerada concluída quando o sistema demonstrar que o job não consegue alterar o host, acessar recursos sensíveis ou interferir em outros jobs.

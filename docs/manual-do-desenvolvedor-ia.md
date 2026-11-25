# Manual do Desenvolvedor: Contrato de Entrada, Saída e Isolamento

Este documento define as regras e convenções que qualquer script de IA deve seguir para executar com sucesso na plataforma **AI Compute Server**.

---

## 1. A Regra de Ouro: Contrato de Entrada e Saída

Para que a plataforma saiba exatamente onde colocar seus arquivos e como devolver os resultados gerados, o servidor injeta **variáveis de ambiente** dentro do container.

### Variáveis Disponíveis no Container:

| Variável | Valor Padrão no Container | Para que serve |
| :--- | :--- | :--- |
| **`OUTPUT_DIR`** | `/job/output` | **Onde você DEVE salvar seus modelos, gráficos e resultados.** Tudo salvo aqui é preservado e disponibilizado para download. |
| **`WORKSPACE_DIR`** | `/job/workspace` | Diretório de trabalho onde o seu ZIP foi extraído e onde o script executa. |
| **`INPUT_DIR`** | `/job/input` | Diretório de arquivos de entrada (somente-leitura). |
| **`JOB_ID`** | ex: `job_20261117_...` | ID exclusivo do job atual. |

---

## 2. Como programar seu script (`main.py`)

A forma recomendada para capturar o diretório de saída é usando `os.environ.get("OUTPUT_DIR", "output")`.
Dessa forma, o seu código funciona **tanto no servidor dentro do container quanto localmente no seu computador pessoal** para testes antes do envio.

### Exemplo Modelo (Template Recomendado):

```python
import os
import json
import time

# 1. Captura o diretório de saída oficial da plataforma
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("=" * 50)
print(f"Iniciando Job {os.environ.get('JOB_ID', 'local')}")
print(f"Diretório de Saída: {OUTPUT_DIR}")
print("=" * 50)

# 2. Seu código de IA (leitura de dados, treino ou inferência)
# Arquivos que você enviou no ZIP estão no mesmo diretório:
# dados = pd.read_csv("meu_dataset.csv")

# 3. SALVANDO OS RESULTADOS EM OUTPUT_DIR:

# A) Salvando pesos de modelo (ex: PyTorch)
# torch.save(model.state_dict(), os.path.join(OUTPUT_DIR, "pesos_modelo.pt"))

# B) Salvando relatório de métricas em JSON
metricas = {
    "acuracia": 0.952,
    "loss": 0.081,
    "tempo_execucao_segundos": 120
}
with open(os.path.join(OUTPUT_DIR, "metricas.json"), "w", encoding="utf-8") as f:
    json.dump(metricas, f, indent=2)

# C) Salvando relatório em texto simples
with open(os.path.join(OUTPUT_DIR, "relatorio.txt"), "w", encoding="utf-8") as f:
    f.write("Treinamento concluído com sucesso.\n")

print("=" * 50)
print("Execução finalizada com sucesso! Arquivos salvos em OUTPUT_DIR.")
print("=" * 50)
```

---

## 3. Isolamento de Usuários

A plataforma permite que múltiplos usuários na mesma rede submetam tarefas para a mesma máquina potente.

### Como funciona:
1. **Identificação do Autor (`user_id`):**
   * No formulário de envio, cada pessoa digita seu nome ou equipe no campo **"Autor / Seu Nome"**.
   * O navegador guarda esse nome automaticamente no armazenamento local (`localStorage`), sem precisar redigitar em novos envios.
2. **Visualização Filtrada ("Meus Jobs"):**
   * Acima da tabela de histórico, o usuário pode clicar em:
     * **`Apenas Meus Jobs`**: filtra a tabela para exibir unicamente os jobs criados por ele.
     * **`Ver Todos`**: exibe a fila geral da máquina.
3. **Isolamento de Diretórios no Servidor:**
   * Cada job ganha um diretório estritamente isolado (`storage/jobs/<job_id>`).
   * Um container nunca tem acesso aos arquivos ou diretórios de outro job ou de outro usuário.

---

## 4. Como o Usuário Recebe os Resultados

Assim que o job finaliza (status `completed`):

1. **Logs de Terminal:** Clicando em **"Logs"**, o usuário vê todas as linhas impressas via `print()` durante o processo.
2. **Download de Arquivos:** Clicando em **"Output"**, a interface abre uma janela listando cada arquivo salvo em `OUTPUT_DIR`.
   * Basta clicar no nome do arquivo (ex: `pesos_modelo.pt` ou `metricas.json`) para baixá-lo diretamente pelo navegador.

---

## 5. Política de Retenção (Limpeza em 7 dias)

* Todos os arquivos de entrada, logs e resultados gerados permanecem disponíveis para download por **7 dias**.
* Após o período de retenção, o serviço de limpeza do servidor (`cleanup_jobs.py`) remove os arquivos temporários do disco automaticamente para evitar sobrecarga de armazenamento.

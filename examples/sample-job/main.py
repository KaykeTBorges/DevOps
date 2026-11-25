import json
import os
import sys
import time

print("=" * 50)
print("⚡ AI Compute Server - Exemplo de Workload")
print(f"Executando script: main.py")
print(f"Diretório de trabalho: {os.getcwd()}")
print(f"Python versão: {sys.version}")
print("=" * 50)

# Simulação de épocas de treino de modelo
print("Iniciando processamento...")
for epoch in range(1, 6):
    loss = 0.85 / epoch
    acc = 0.60 + (epoch * 0.07)
    print(f"[Epoch {epoch}/5] Loss: {loss:.4f} | Acurácia: {acc:.2%}")
    time.sleep(0.3)

# Identifica o diretório de output via variável injetada pelo servidor (ou 'output' local)
output_dir = os.environ.get("OUTPUT_DIR", "output")
os.makedirs(output_dir, exist_ok=True)

# 1. Salva arquivo de métricas em JSON
metrics = {
    "status": "success",
    "model_name": "DemoClassifier",
    "epochs_trained": 5,
    "final_loss": round(0.85 / 5, 4),
    "final_accuracy": round(0.60 + (5 * 0.07), 4),
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}

metrics_path = os.path.join(output_dir, "metrics.json")
with open(metrics_path, "w", encoding="utf-8") as f:
    json.dump(metrics, f, indent=2)

# 2. Salva arquivo de texto com resumo
summary_path = os.path.join(output_dir, "model_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write("=========================================\n")
    f.write(" Relatório Final do Treinamento de IA   \n")
    f.write("=========================================\n")
    f.write(f"Modelo: DemoClassifier\n")
    f.write(f"Acurácia: {metrics['final_accuracy'] * 100:.2f}%\n")
    f.write(f"Loss: {metrics['final_loss']}\n")
    f.write("Status: Treinamento concluído com sucesso.\n")

print("=" * 50)
print("Treinamento finalizado!")
print(f"Arquivos gerados em {output_dir}:")
print(f" - metrics.json")
print(f" - model_summary.txt")
print("=" * 50)

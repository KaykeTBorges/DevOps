#!/usr/bin/env python3
"""Executor isolado para jobs em containers.

O objetivo desta implementação é servir como base para o MVP da plataforma de
execução de modelos de IA em um ambiente local e seguro.

Principais regras do MVP:
- cada job possui diretório próprio;
- input, workspace, output e logs ficam isolados;
- o container é executado sem rede por padrão;
- CPU, memória e timeout são limitados;
- a execução não usa shell livre no host;
- o código do usuário roda dentro do container e não no host.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass
class JobSpec:
    job_id: str
    image: str
    command: list[str]
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    timeout_seconds: int = 300
    network_mode: str = "none"
    gpu_count: int = 0
    gpu_device: str | None = None
    working_dir: str = "/job/workspace"


def build_job_layout(job_root: str | Path) -> dict[str, Path]:
    root = Path(job_root).resolve()
    paths = {
        "input": root / "input",
        "workspace": root / "workspace",
        "output": root / "output",
        "logs": root / "logs",
        "metadata": root / "metadata",
    }

    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    return paths


def build_docker_command(spec: JobSpec, job_root: str | Path) -> list[str]:
    root = Path(job_root).resolve()
    paths = build_job_layout(root)

    cmd: list[str] = [
        "docker",
        "run",
        "--name",
        f"ai_job_{spec.job_id}",
        "--rm",
        "--network",
        spec.network_mode,
        "--cpus=" + str(spec.cpu_limit),
        "--memory=" + str(spec.memory_limit),
        "--pids-limit=256",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=512m",
        "--tmpfs",
        "/run:rw,noexec,nosuid,nodev,size=256m",
        "--user",
        "1000:1000",
        "-v",
        f"{paths['input']}:/job/input:ro",
        "-v",
        f"{paths['workspace']}:/job/workspace:rw",
        "-v",
        f"{paths['output']}:/job/output:rw",
        "-v",
        f"{paths['logs']}:/job/logs:rw",
        "-v",
        f"{paths['metadata']}:/job/metadata:rw",
        "-e",
        "OUTPUT_DIR=/job/output",
        "-e",
        "WORKSPACE_DIR=/job/workspace",
        "-e",
        "INPUT_DIR=/job/input",
        "-e",
        f"JOB_ID={spec.job_id}",
        "--workdir",
        spec.working_dir,
    ]

    if spec.gpu_count > 0:
        gpu_arg = spec.gpu_device if spec.gpu_device else "all"
        cmd.extend(["--gpus", gpu_arg])

    cmd.append(spec.image)
    cmd.extend(spec.command)
    return cmd


def write_metadata(job_root: str | Path, spec: JobSpec, exit_code: int | None = None) -> None:
    root = Path(job_root).resolve()
    metadata_path = root / "metadata" / "job_metadata.json"
    payload = {
        "job_id": spec.job_id,
        "image": spec.image,
        "command": spec.command,
        "cpu_limit": spec.cpu_limit,
        "memory_limit": spec.memory_limit,
        "timeout_seconds": spec.timeout_seconds,
        "network_mode": spec.network_mode,
        "gpu_count": spec.gpu_count,
        "gpu_device": spec.gpu_device,
        "working_dir": spec.working_dir,
        "exit_code": exit_code,
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def kill_job_container(job_id: str) -> bool:
    """Para e remove forçadamente o container do job em execução (docker kill / rm)."""
    container_name = f"ai_job_{job_id}"
    try:
        kill_result = subprocess.run(["docker", "kill", container_name], capture_output=True, text=True, timeout=10)
        remove_result = subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True, timeout=10)
        return kill_result.returncode == 0 or remove_result.returncode == 0
    except Exception:
        return False


def inspect_job_container(job_id: str) -> dict | None:
    """Verifica se o container do job ainda está rodando ou seu status no Docker."""
    container_name = f"ai_job_{job_id}"
    try:
        proc = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            if data and isinstance(data, list):
                return data[0].get("State", {})
        return None
    except Exception:
        return None


def run_job(spec: JobSpec, job_root: str | Path) -> int:
    root = Path(job_root).resolve()
    build_job_layout(root)
    docker_cmd = build_docker_command(spec, root)
    log_path = root / "logs" / "job.log"

    with log_path.open("w", encoding="utf-8") as log_file:
        completed = subprocess.run(
            docker_cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=spec.timeout_seconds,
            text=True,
        )

    write_metadata(root, spec, completed.returncode)
    return completed.returncode


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executor seguro de jobs em container para IA.")
    parser.add_argument("--job-id", required=True, help="Identificador do job")
    parser.add_argument("--job-root", required=True, help="Diretório raiz do job")
    parser.add_argument("--image", required=True, help="Imagem Docker da execução")
    parser.add_argument("--command", nargs=argparse.REMAINDER, required=True, help="Comando a ser executado no container")
    parser.add_argument("--cpu-limit", default="1.0", help="Limite de CPU por job")
    parser.add_argument("--memory-limit", default="512m", help="Limite de memória por job")
    parser.add_argument("--timeout-seconds", type=int, default=300, help="Tempo máximo de execução do job")
    parser.add_argument("--network-mode", default="none", help="Modo de rede do container")
    parser.add_argument("--gpu-count", type=int, default=0, help="Quantidade de GPUs alocadas ao job")
    parser.add_argument("--gpu-device", default=None, help="Dispositivo GPU específico (opcional)")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar o comando Docker sem executá-lo")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]

    dry_run = args.dry_run
    if "--dry-run" in command:
        dry_run = True
        command.remove("--dry-run")

    spec = JobSpec(
        job_id=args.job_id,
        image=args.image,
        command=command,
        cpu_limit=args.cpu_limit,
        memory_limit=args.memory_limit,
        timeout_seconds=args.timeout_seconds,
        network_mode=args.network_mode,
        gpu_count=args.gpu_count,
        gpu_device=args.gpu_device,
    )

    if dry_run:
        print(" ".join(build_docker_command(spec, args.job_root)))
        return 0

    try:
        return run_job(spec, args.job_root)
    except subprocess.TimeoutExpired:
        kill_job_container(spec.job_id)
        write_metadata(args.job_root, spec, 124)
        print(f"Job {spec.job_id} excedeu o timeout de {spec.timeout_seconds}s.", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())

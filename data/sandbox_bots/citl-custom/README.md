# CITL Bot Sandbox Bundle

Model name: `citl-custom`
Base model: `qwen2.5:14b-instruct`

## Local demo
```bash
./run_demo.sh
```

## Docker demo
```bash
docker build -t citl/citl-custom-demo:latest .
docker run --rm \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -e OLLAMA_MODEL=citl-custom \
  citl/citl-custom-demo:latest
```

## Kubernetes demo
1. Build/push the Docker image to your registry.
2. Update `k8s-job.yaml` image reference if needed.
3. Run:
```bash
kubectl apply -f k8s-job.yaml
kubectl logs -l job-name=citl-custom-demo --tail=100
```

## Slurm demo
```bash
sbatch slurm-job.sh
```

## Provenance checks
```bash
ollama list
ollama show citl-custom:latest
```

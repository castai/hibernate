#!/bin/sh
set -o errexit

cluster_name="kind"

if ! [ -x "$(command -v kind)" ]; then
  echo 'binary "kind" not found in PATH. Is it installed?' >&2
  exit 1
fi

if kind get clusters | grep -E "^${cluster_name}$" 2>/dev/null; then
  echo "Cluster with name '${cluster_name}' already exists, skipping creation. Make sure it matches the config required." >&2
else
cat <<EOF | kind create cluster --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
- role: worker
EOF
fi

kubectl taint node kind-worker2 scheduling.cast.ai/paused-cluster:NoSchedule
kubectl label node kind-worker2 "kubernetes.azure.com/mode=system"
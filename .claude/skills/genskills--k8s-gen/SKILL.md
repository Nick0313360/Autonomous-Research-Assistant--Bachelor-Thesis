---
name: genskills:k8s-gen
description: >
  Generate Kubernetes manifests - deployments, services, ingress, configmaps.
  Triggers on: "kubernetes", "k8s", "k8s manifest", "generate deployment",
  "helm chart", "kustomize".
user-invocable: true
argument-hint: "[type] - e.g., 'deployment' or 'full-stack' or 'helm'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(kubectl *), Bash(helm *), Bash(kustomize *), Bash(docker *)"
genskills-version: "1.2.0"
genskills-category: "devops"
genskills-depends: ["genskills:docker-gen"]
---

# K8s Gen

Generate production-ready Kubernetes manifests.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for K8s conventions, cluster info, namespaces
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `$0` = type: `deployment`, `service`, `ingress`, `full-stack`, `helm`, `kustomize`, `cronjob`
- `--namespace` = target namespace
- `--replicas` = replica count (default: 2)
- `--format` = "manifests" (default), "helm", "kustomize"

### Step 2: Detect Application
Analyze project to determine:
- Container image name and registry
- Port the application listens on
- Environment variables required
- Health check endpoints
- Resource requirements (CPU/memory)
- Persistent storage needs
- External service dependencies

### Step 3: Generate Manifests

**Directory structure:**
```
k8s/
├── base/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── hpa.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   └── patch-replicas.yaml
│   ├── staging/
│   │   └── kustomization.yaml
│   └── prod/
│       ├── kustomization.yaml
│       ├── patch-replicas.yaml
│       └── patch-resources.yaml
└── README.md
```

**Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <app-name>
  labels:
    app: <app-name>
spec:
  replicas: 2
  selector:
    matchLabels:
      app: <app-name>
  template:
    metadata:
      labels:
        app: <app-name>
    spec:
      containers:
        - name: <app-name>
          image: <registry>/<app-name>:latest
          ports:
            - containerPort: <port>
          envFrom:
            - configMapRef:
                name: <app-name>-config
            - secretRef:
                name: <app-name>-secrets
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /health
              port: <port>
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: <port>
            initialDelaySeconds: 5
            periodSeconds: 10
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
```

**Service:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: <app-name>
spec:
  selector:
    app: <app-name>
  ports:
    - port: 80
      targetPort: <port>
  type: ClusterIP
```

**Ingress:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <app-name>
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - <domain>
      secretName: <app-name>-tls
  rules:
    - host: <domain>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: <app-name>
                port:
                  number: 80
```

**HPA (Horizontal Pod Autoscaler):**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: <app-name>
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <app-name>
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Step 4: Helm Chart (if `--format helm`)
```
chart/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-prod.yaml
└── templates/
    ├── _helpers.tpl
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    ├── secret.yaml
    └── hpa.yaml
```

### Step 5: Best Practices
- Set resource requests AND limits
- Use liveness and readiness probes
- Run as non-root user
- Use ConfigMaps for config, Secrets for sensitive data
- Set pod disruption budgets for HA
- Use rolling update strategy
- Label everything consistently
- Use namespaces for environment isolation

### Step 6: Validate
```bash
kubectl apply --dry-run=client -f k8s/base/
# or
kubeval k8s/base/*.yaml
# or
kustomize build k8s/overlays/dev | kubectl apply --dry-run=client -f -
```

### Step 7: Report
```
## Kubernetes Manifests Generated

### Format: <manifests/helm/kustomize>
### Output: k8s/

### Resources
- Deployment: <app-name> (2 replicas)
- Service: ClusterIP on port 80
- Ingress: HTTPS with cert-manager
- HPA: 2-10 replicas, 70% CPU target
- ConfigMap + Secret

### Environments (via Kustomize overlays)
- dev: 1 replica, 100m CPU
- staging: 2 replicas, 250m CPU
- prod: 3 replicas, 500m CPU, PDB

### Deploy
$ kubectl apply -k k8s/overlays/dev    # Deploy to dev
$ kubectl apply -k k8s/overlays/prod   # Deploy to prod
$ helm install <app> ./chart -f chart/values-dev.yaml  # Helm

### Next Steps
- Update image registry in deployment
- Configure secrets (use sealed-secrets or external-secrets)
- Set up CI/CD with `/genskills:github-actions`
```

## Configuration
- `registry`: string - container registry (e.g., "ghcr.io/org")
- `namespace`: string - default namespace
- `format`: string - "manifests" | "helm" | "kustomize" (default: "kustomize")
- `ingressClass`: string - "nginx" | "traefik" | "alb" (default: "nginx")
- `certManager`: boolean - use cert-manager for TLS (default: true)

---
name: genskills:infra-gen
description: >
  Generate Infrastructure as Code templates - Terraform, Pulumi, CloudFormation.
  Triggers on: "infra", "terraform", "infrastructure", "pulumi", "cloudformation",
  "IaC", "provision cloud".
user-invocable: true
argument-hint: "[provider] [pattern] - e.g., 'aws serverless-api' or 'gcp static-site'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(terraform *), Bash(pulumi *), Bash(aws *), Bash(gcloud *), Bash(az *)"
genskills-version: "1.2.0"
genskills-category: "devops"
genskills-depends: []
---

# Infra Gen

Generate Infrastructure as Code for common deployment patterns.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for infrastructure conventions, cloud provider, IaC tool
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `$0` = cloud provider: `aws`, `gcp`, `azure`, `vercel`, `fly`, `railway`
- `$1` = pattern: `serverless-api`, `static-site`, `container-service`, `fullstack`, `database`, `cdn`, `queue`
- `--tool` = IaC tool: `terraform` (default), `pulumi`, `cloudformation`, `cdk`
- `--env` = environments: `dev`, `staging`, `prod` (can specify multiple)

### Step 2: Detect Project Needs
Analyze the project to determine infrastructure requirements:
- **Compute**: serverless (Lambda/Cloud Functions), containers (ECS/Cloud Run), VM
- **Database**: PostgreSQL, MySQL, MongoDB, DynamoDB, Firestore
- **Cache**: Redis/ElastiCache, Memcached
- **Storage**: S3/GCS/Blob for uploads, static assets
- **CDN**: CloudFront/Cloud CDN for static assets
- **Queue**: SQS/Pub-Sub for async processing
- **Auth**: Cognito/Firebase Auth/Auth0
- **DNS**: Route53/Cloud DNS

### Step 3: Generate IaC

**Directory structure:**
```
infra/
├── main.tf              # Provider config, backend
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── environments/
│   ├── dev.tfvars
│   ├── staging.tfvars
│   └── prod.tfvars
├── modules/
│   ├── networking/      # VPC, subnets, security groups
│   ├── compute/         # ECS, Lambda, EC2
│   ├── database/        # RDS, DynamoDB
│   └── storage/         # S3, CloudFront
└── README.md
```

**Pattern: Serverless API (AWS)**
```hcl
# API Gateway + Lambda + DynamoDB
# - REST or HTTP API Gateway
# - Lambda functions per route
# - DynamoDB table with on-demand billing
# - CloudWatch logging
# - IAM roles with least privilege
```

**Pattern: Container Service (AWS)**
```hcl
# ECS Fargate + ALB + RDS
# - VPC with public/private subnets
# - Application Load Balancer
# - ECS Fargate service with auto-scaling
# - RDS PostgreSQL in private subnet
# - Security groups with minimal access
# - Secrets Manager for credentials
```

**Pattern: Static Site (AWS)**
```hcl
# S3 + CloudFront + Route53
# - S3 bucket for static files
# - CloudFront distribution with HTTPS
# - Route53 DNS records
# - ACM certificate
# - Origin Access Identity
```

**Pattern: Fullstack (AWS)**
```hcl
# Combines container-service + static-site + database
# - Frontend: S3 + CloudFront
# - Backend: ECS Fargate + ALB
# - Database: RDS PostgreSQL
# - Cache: ElastiCache Redis
# - Shared VPC networking
```

### Step 4: Best Practices
Always include:
- **State management**: remote backend (S3+DynamoDB lock for Terraform)
- **Variables**: parameterize everything environment-specific
- **Outputs**: expose URLs, ARNs, connection strings
- **Tags**: consistent resource tagging for cost tracking
- **Security**: encryption at rest and in transit, least-privilege IAM
- **Environments**: separate tfvars per environment
- **Naming**: consistent resource naming convention

### Step 5: Generate Deployment Script
Create a deployment helper:
```bash
#!/bin/bash
# deploy.sh
ENV=${1:-dev}
terraform init
terraform workspace select $ENV || terraform workspace new $ENV
terraform plan -var-file="environments/$ENV.tfvars" -out=plan.out
terraform apply plan.out
```

### Step 6: Report
```
## Infrastructure Generated

### Provider: <cloud>
### Pattern: <pattern>
### Tool: Terraform

### Resources
- VPC with 2 public + 2 private subnets
- ECS Fargate cluster with auto-scaling (1-4 tasks)
- Application Load Balancer with HTTPS
- RDS PostgreSQL 16 (db.t3.micro)
- S3 bucket for assets
- CloudWatch log groups

### Environments
- dev.tfvars - minimal resources, single AZ
- staging.tfvars - production-like, reduced capacity
- prod.tfvars - full HA, multi-AZ

### Deploy
$ cd infra
$ terraform init
$ terraform plan -var-file="environments/dev.tfvars"
$ terraform apply -var-file="environments/dev.tfvars"

### Estimated Cost (dev)
~$XX/month (check with `infracost`)

### Next Steps
- Configure remote backend (S3 + DynamoDB)
- Set up CI/CD with `/genskills:github-actions`
- Add monitoring and alerting
```

## Configuration
- `provider`: string - default cloud provider (default: "aws")
- `tool`: string - "terraform" | "pulumi" | "cdk" (default: "terraform")
- `region`: string - default region (default: "us-east-1")
- `stateBackend`: string - remote state config
- `tagPrefix`: string - resource tag prefix for cost tracking

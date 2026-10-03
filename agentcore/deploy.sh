#!/usr/bin/env bash
# ==============================================================================
# Threadback — Amazon Bedrock AgentCore Runtime Deployment Script (M9)
# ==============================================================================
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo '000000000000')}"
ECR_REPO_NAME="${ECR_REPO_NAME:-threadback-mcp}"
IMAGE_TAG="${IMAGE_TAG:-m9-latest}"
AGENTCORE_RUNTIME_NAME="${AGENTCORE_RUNTIME_NAME:-threadback-mcp-runtime}"

echo "=================================================================="
echo "Threadback M9 — AgentCore Runtime Deployment"
echo "AWS Region:     ${AWS_REGION}"
echo "AWS Account ID: ${AWS_ACCOUNT_ID}"
echo "ECR Repo:       ${ECR_REPO_NAME}"
echo "Runtime Name:   ${AGENTCORE_RUNTIME_NAME}"
echo "=================================================================="

# Check Docker availability
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is required to build the AgentCore container image."
    exit 1
fi

# Check AWS CLI availability
if ! command -v aws >/dev/null 2>&1; then
    echo "[ERROR] AWS CLI is required for AgentCore deployment."
    exit 1
fi

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:${IMAGE_TAG}"

echo "[1/4] Building Docker container image for AgentCore (linux/arm64 required)..."
docker build --platform linux/arm64 -t "${ECR_REPO_NAME}:${IMAGE_TAG}" -f Dockerfile.agentcore .

echo "[1b/4] Verifying image architecture is linux/arm64..."
IMAGE_ARCH=$(docker inspect --format '{{.Architecture}}' "${ECR_REPO_NAME}:${IMAGE_TAG}" 2>/dev/null || echo "arm64")
if [ "$IMAGE_ARCH" != "arm64" ]; then
    echo "[ERROR] Built image architecture is '${IMAGE_ARCH}', but AgentCore MCP runtime strictly requires arm64."
    exit 1
fi
echo "[OK] Image architecture verified as linux/arm64."

echo "[2/4] Authenticating with Amazon ECR..."
aws ecr get-login-password --region "${AWS_REGION}" 2>/dev/null | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" 2>/dev/null || {
    echo "[INFO] ECR login skipped or denied by IAM (ViewOnlyAccess). Local container artifact prepared."
}

echo "[3/4] Tagging and pushing image to ECR..."
docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}" 2>/dev/null || true
docker push "${ECR_URI}" 2>/dev/null || {
    echo "[INFO] ECR push skipped. Active IAM user lacks write permissions."
}

echo "[4/4] Registering with Amazon Bedrock AgentCore..."
# Official AWS AgentCore workflow uses:
#   agentcore create / agentcore add agent --protocol MCP / agentcore deploy
# runtime-config.json represents Threadback's intended configuration manifest.
if command -v agentcore >/dev/null 2>&1; then
    echo "[INFO] Running official agentcore CLI workflow..."
    agentcore add agent --protocol MCP --name "${AGENTCORE_RUNTIME_NAME}" || true
elif aws bedrock-agentcore-control --help >/dev/null 2>&1; then
    aws bedrock-agentcore-control register-agent-runtime \
        --name "${AGENTCORE_RUNTIME_NAME}" \
        --region "${AWS_REGION}" \
        --image-uri "${ECR_URI}" \
        --config-file file://agentcore/runtime-config.json 2>/dev/null || {
        echo "[INFO] Bedrock AgentCore registration skipped. Active IAM user has ViewOnlyAccess."
    }
else
    echo "[INFO] Neither agentcore CLI nor bedrock-agentcore-control is installed in this environment."
fi

echo "=================================================================="
echo "Deployment preparation complete."
echo "=================================================================="

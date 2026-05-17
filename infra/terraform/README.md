# Audit Log Infrastructure

S3 Object Lock 기반 WORM(Write Once Read Many) 감사 로그 장기 보존 인프라.

## 언제 이걸 켜야 하는가

- 금융권: K-FSC §31 기준 5년 보존 의무 시
- 상장사: SOX §404 감사 대응 시 (7년 권장)
- PCI DSS: 카드 데이터 환경 감사 시 (12개월 즉시 접근 + 3년 보존)
- 내부 통제 성숙도가 올라가서 감사 로그를 "진짜 증거"로 써야 할 때

처음 3 스프린트는 `.audit/events.jsonl` 로컬 파일로 충분합니다.

## 전제 조건

- AWS 계정
- Terraform >= 1.6
- GitHub Actions OIDC provider가 AWS 계정에 등록되어 있어야 함

## 셋업

```bash
cd infra/terraform

# 1. OIDC provider 등록 (처음 한 번만)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. terraform.tfvars 작성
cat > terraform.tfvars <<EOF
project_name   = "my-project"
github_org     = "your-org"
github_repo    = "your-repo"
retention_days = 1825   # 5년 (K-FSC §31)
aws_region     = "ap-northeast-2"
EOF

# 3. Apply
terraform init
terraform plan
terraform apply

# 4. 출력값을 GitHub Secrets에 등록
# AWS_AUDIT_BUCKET     = <audit_bucket_name>
# AWS_AUDIT_ROLE_ARN   = <audit_writer_role_arn>
# AWS_REGION           = ap-northeast-2
```

## 보존 기간 가이드

| 규정 | 권장 days |
|------|-----------|
| K-FSC §31 | 1825 (5년) |
| SOX | 2555 (7년) |
| PCI DSS | 1095 (3년, 최소 365일 즉시 접근) |
| ISO 27001 | 조직 정책 (최소 3년 권장) |

**COMPLIANCE 모드**: `retention_days` 이내에는 root 계정도 삭제 불가.  
변경이 필요하면 `aws s3api extend-object-retention`으로 연장만 가능.

## 감사 로그 구조 (S3 경로)

```
s3://<bucket>/audit-logs/
  YYYY/
    MM/
      DD/
        events-YYYYMMDDHHMMSS.jsonl    ← 일별 스냅샷
  attestations/
    attest-sprint-N-YYYYMMDDHHMMSS.json
    attest-monthly-YYYY-MM-YYYYMMDDHHMMSS.json
    attest-project-final-YYYYMMDDHHMMSS.json
```

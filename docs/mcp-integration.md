# MCP Server Integration Guide

sprint-system은 외부 시스템 연동을 MCP(Model Context Protocol) 서버를 통해 처리합니다.  
모든 MCP 도구 호출은 `audit-mcp-hook.sh`를 통해 audit chain에 자동으로 기록됩니다.

## .mcp.json 설정

`.mcp.json.example`을 복사해 `.mcp.json`으로 만들고 gitignore에 추가합니다:

```bash
cp .mcp.json.example .mcp.json
echo ".mcp.json" >> .gitignore
```

---

## 지원 통합

### 1. Linear (태스크 보드)

sprint-system이 Linear를 태스크 보드로 사용할 때:
- `sprint.planned` → Linear 이슈 자동 생성
- `ac.confirmed` → Linear 이슈 Done으로 전환
- `sprint.completed` → Linear 스프린트 완료

**설정**:
```json
{
  "linear": {
    "command": "npx",
    "args": ["-y", "@linear/mcp-server"],
    "env": {
      "LINEAR_API_KEY": "${LINEAR_API_KEY}"
    }
  }
}
```

**사용**: sprint.md에서 `linear.create_issue`, `linear.update_issue` 도구 호출 가능.

### 2. Jira (엔터프라이즈 태스크 보드)

```json
{
  "jira": {
    "command": "npx",
    "args": ["-y", "@atlassian/mcp-jira"],
    "env": {
      "JIRA_URL": "${JIRA_URL}",
      "JIRA_EMAIL": "${JIRA_EMAIL}",
      "JIRA_API_TOKEN": "${JIRA_API_TOKEN}"
    }
  }
}
```

### 3. Sentry (에러 모니터링)

`sre-incident` 에이전트가 Sentry 에러를 자동으로 조회하고 incident 트리거:

```json
{
  "sentry": {
    "command": "npx",
    "args": ["-y", "@sentry/mcp-server"],
    "env": {
      "SENTRY_AUTH_TOKEN": "${SENTRY_AUTH_TOKEN}",
      "SENTRY_ORG": "${SENTRY_ORG}"
    }
  }
}
```

### 4. Datadog (메트릭 / APM)

`sre-incident`가 Datadog 대시보드를 조회하고 성능 SLO 체크:

```json
{
  "datadog": {
    "command": "npx",
    "args": ["-y", "@datadog/mcp-server"],
    "env": {
      "DD_API_KEY": "${DD_API_KEY}",
      "DD_APP_KEY": "${DD_APP_KEY}",
      "DD_SITE": "datadoghq.com"
    }
  }
}
```

### 5. GitHub (이미 내장 — gh CLI 사용)

GitHub 통합은 gh CLI를 통해 처리됩니다. MCP 서버 추가 없이 작동합니다.

---

## Audit Hook 설정 (모든 MCP 서버에 적용)

`.mcp.json`의 각 서버에 hook을 추가해 MCP 호출이 audit chain에 기록되게:

```json
{
  "mcpServers": {
    "linear": {
      "...": "...",
      "hooks": {
        "postToolCall": "bash .claude/bin/audit-mcp-hook.sh"
      }
    }
  }
}
```

이렇게 하면 `linear.create_issue` 같은 모든 외부 호출이 audit log에:
```json
{"event":"mcp.tool_called","tool":"create_issue","server":"linear","sanitized_input":{...}}
```
형태로 기록됩니다. 민감 필드(token, api_key, password)는 자동으로 `[REDACTED]`로 치환.

---

## 환경 변수 관리

로컬 개발:
```bash
# .env.local (gitignore에 추가)
LINEAR_API_KEY=lin_api_xxx
JIRA_API_TOKEN=xxx
SENTRY_AUTH_TOKEN=sntrys_xxx
DD_API_KEY=xxx
DD_APP_KEY=xxx
```

GitHub Actions:
```
Settings → Secrets and variables → Actions → New repository secret
```

필요한 시크릿: `LINEAR_API_KEY`, `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `SENTRY_AUTH_TOKEN`, `DD_API_KEY`, `DD_APP_KEY`

---

## 없어도 되는 것

MCP 없이도 sprint-system 전체가 작동합니다. MCP는 편의 기능입니다:
- **필수**: GitHub CLI (`gh`) — PR/Issue 자동화
- **선택**: Linear/Jira — 태스크를 마크다운 대신 외부 보드로
- **선택**: Sentry/Datadog — SRE 에이전트의 인시던트 탐지 자동화

처음 3 스프린트는 MCP 없이 운영하고, 패턴이 잡히면 연동하는 게 실용적입니다.

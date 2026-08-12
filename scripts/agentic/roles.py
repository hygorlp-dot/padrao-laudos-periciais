"""Select a role from an explicit task kind."""

ROLES = {
    "IMPLEMENT": "IMPLEMENTER",
    "RESEARCH": "RESEARCHER",
    "PR_REVIEW": "PR_REVIEWER",
    "SYSTEMIC_AUDIT": "SYSTEMIC_AUDITOR",
    "EXTERNAL_REVIEW": "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER",
}


def select_agent_role(task_kind: str) -> str:
    try:
        return ROLES[task_kind]
    except KeyError as exc:
        raise ValueError(f"unsupported agent task: {task_kind}") from exc

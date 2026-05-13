from typing import Literal, get_args

SecretKey = Literal[
    "GIT_USER_NAME",
    "GIT_USER_EMAIL",
    "AWS_ACCOUNT_ID",
    "GCP_PROJECT_ID",
    "GITHUB_TOKEN",
    "KUBE_CONTEXT",
    "EXA_API_KEY",
    "CONTEXT7_API_KEY",
]

DESCRIPTIONS: dict[str, str] = {
    "GIT_USER_NAME": "Full name for git commits",
    "GIT_USER_EMAIL": "Email for git commits",
    "AWS_ACCOUNT_ID": "12-digit AWS account number",
    "GCP_PROJECT_ID": "Default gcloud project id",
    "GITHUB_TOKEN": "PAT for gh auth",
    "KUBE_CONTEXT": "Default kubectl context name",
    "EXA_API_KEY": "API key for Exa search",
    "CONTEXT7_API_KEY": "API key for Context7 code search",
}


def all_keys() -> tuple[str, ...]:
    return get_args(SecretKey)

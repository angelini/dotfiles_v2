from typing import Literal, get_args

SecretKey = Literal[
    "GIT_USER_NAME",
    "GIT_USER_EMAIL",
    "GIT_SIGNING_KEY",
    "AWS_ACCOUNT_ID",
    "GCP_PROJECT_ID",
    "GITHUB_TOKEN",
    "KUBE_CONTEXT",
]

DESCRIPTIONS: dict[str, str] = {
    "GIT_USER_NAME": "Full name for git commits",
    "GIT_USER_EMAIL": "Email for git commits",
    "GIT_SIGNING_KEY": "GPG/SSH key id for commit signing",
    "AWS_ACCOUNT_ID": "12-digit AWS account number",
    "GCP_PROJECT_ID": "Default gcloud project id",
    "GITHUB_TOKEN": "PAT for gh auth",
    "KUBE_CONTEXT": "Default kubectl context name",
}


def all_keys() -> tuple[str, ...]:
    return get_args(SecretKey)

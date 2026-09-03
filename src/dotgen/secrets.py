from typing import Literal, get_args

SecretKey = Literal[
    "GIT_USER_NAME",
    "GIT_USER_EMAIL",
    "AWS_ACCOUNT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GITHUB_TOKEN",
    "NPM_TOKEN",
    "KUBE_CONTEXT",
    "EXA_API_KEY",
    "CONTEXT7_API_KEY",
    "ZED_HOST_BRIDGE_SSH_HOST",
]

DESCRIPTIONS: dict[str, str] = {
    "GIT_USER_NAME": "Full name for git commits",
    "GIT_USER_EMAIL": "Email for git commits",
    "AWS_ACCOUNT_ID": "12-digit AWS account number",
    "GOOGLE_CLOUD_PROJECT": "Google Cloud project id for Vertex AI",
    "GOOGLE_CLOUD_LOCATION": "Google Cloud location for Vertex AI",
    "GITHUB_TOKEN": "PAT for gh auth",
    "NPM_TOKEN": "GitHub Packages npm token",
    "KUBE_CONTEXT": "Default kubectl context name",
    "EXA_API_KEY": "API key for Exa search",
    "CONTEXT7_API_KEY": "API key for Context7 code search",
    "ZED_HOST_BRIDGE_SSH_HOST": "SSH config alias used by the Zed host bridge",
}


def all_keys() -> tuple[str, ...]:
    return get_args(SecretKey)

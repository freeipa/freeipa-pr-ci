"""GitHub GraphQL helpers module"""

import json
from typing import Dict, List, Text

from requests import Session

GITHUB_ENDPOINT = 'https://api.github.com/graphql'


def make_headers(token: Text) -> Dict[Text, Text]:
    """Make headers dict."""
    return {
        "Authorization": "token {}".format(token),
        "User-Agent": "FreeIPA CI"
    }


def create_session(headers: Dict[Text, Text]) -> Session:
    """Creates a session instance with given headers."""
    session = Session()
    session.headers.update(headers)
    return session


def perform_request(session: Session, query: Dict) -> Dict:
    """Performs a GraphQL API request."""
    response = session.post(url=GITHUB_ENDPOINT, json=query)
    if response.status_code != 200:
        raise EnvironmentError(response.text)

    return json.loads(response.text)


def get_data(response: Dict) -> Dict:
    """Extracts data from JSONed response."""
    return response["data"]


def get_repository(data: Dict) -> Dict:
    """Extracts repository from data."""
    return data["repository"]


def get_repository_url(repository: Dict) -> Text:
    """Extracts repository URL."""
    return repository["url"]


def get_pull_request(repository: Dict) -> Dict:
    """Extracts a pull request object from given repository."""
    return repository["pullRequest"]


def get_pull_requests(repository: Dict) -> List[Dict]:
    """Extract pull requests nodes from given repository."""
    return repository["pullRequests"]["nodes"]


def get_last_commit(pull_request: Dict) -> Dict:
    """Extracts last pull request from a given pull request."""
    return pull_request["commits"]["nodes"][0]["commit"]


def get_commit_sha(commit: Dict) -> Text:
    """Extracts sha from a given commit data."""
    return commit["oid"]


def get_status(statuses: Dict, status_name: Text) -> Dict:
    """Extracts the status info for a given status by name."""
    return statuses.get(status_name)


def get_statuses(commit: Dict) -> Dict:
    """Extracts statuses from a given commit."""
    commit_status = commit.get("status")
    if commit_status is None:
        return {}

    contexts = commit_status.get("contexts")
    if contexts is None:
        return {}

    return {c["context"]: c for c in contexts}


def get_labels(pull_request: Dict) -> List[Text]:
    """Extracts the labels names from a given pull request."""
    return [l["name"] for l in pull_request["labels"]["nodes"]]

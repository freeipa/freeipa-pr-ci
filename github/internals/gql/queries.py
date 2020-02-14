"""GitHub GraphQL queries module"""
from typing import Dict, Text

def make_pull_requests_query(owner: Text, repo: Text) -> Dict[Text, Text]:
    return {"query": """{
  repository(owner:"%s", name:"%s") {
    url
    pullRequests(last: 50, states: OPEN) {
      nodes {
        number
        baseRefName
        headRefOid
        mergeable
        author {
          login
        }
        labels(last: 5) {
          nodes {
            name
          }
        }
        commits(last: 250) {
          nodes {
            commit {
              oid
              status {
                contexts {
                  context
                  description
                  state
                  targetUrl
                }
              }
            }
          }
        }
      }
    }
  }
  rateLimit {
    limit
    cost
    remaining
    resetAt
  }
}""" % (owner, repo)}


def make_pull_request_query(
    owner: Text, repo: Text, pr_number: int
) -> Dict[Text, Text]:
    return {
        "query": """{
  repository(owner: "%s", name: "%s") {
    pullRequest(number: %s) {
      headRefOid
      commits(last: 250) {
        nodes {
          commit {
            oid
            status {
              state
              contexts {
                context
                description
                state
                targetUrl
              }
            }
          }
        }
      }
    }
  }
  rateLimit {
    limit
    cost
    remaining
    resetAt
  }
}""" % (owner, repo, pr_number)}

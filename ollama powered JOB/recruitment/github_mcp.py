"""
RecruitScreen / ARIA Core — GitHub MCP Client
────────────────────────────────────────────
Acts as the Model Context Protocol (MCP) bridge to GitHub:
fetches structured repository context for the LLM to verify candidate skill claims.

Strategy:
  1. Fetch top 30 repos (sorted by recent push)
  2. For repos whose name/description/language overlaps with target skills,
     fetch language breakdown + README excerpt
  3. Return a structured GitHubEvidence object — no raw API data leaks to LLM

Auth:
  - Uses a GitHub PAT (read-only: public_repo)
  - Token is recruiter-provided — NOT baked into code
  - Anonymous fallback for public repos (60 req/hr limit)

Rate Limits:
  - Checks X-RateLimit-Remaining header, logs warnings at < 10
  - Does NOT retry on 403 rate-limit; surfaces graceful error message
"""

import re
import json
import base64
import urllib.request
import urllib.error
from typing import Optional

from .models import GitHubRepo, GitHubEvidence


_GITHUB_API = "https://api.github.com"
_README_MAX_CHARS = 800
_REPO_FETCH_LIMIT = 30
_README_FETCH_LIMIT = 10   # Only fetch READMEs for the most relevant repos


class GitHubMCPClient:
    """
    Wraps GitHub REST API v3 to retrieve public repository evidence
    for candidate skill cross-validation.

    Usage:
        client = GitHubMCPClient(token="ghp_...")
        evidence = client.collect_evidence("octocat", ["Python", "FastAPI", "Docker"])
    """

    def __init__(self, token: str = ""):
        self.token = token.strip() if token else ""
        self._rate_remaining = 60

    # ── Internal helpers ──────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {
            "Accept":     "application/vnd.github+json",
            "User-Agent": "ARIA-RecruitScreen/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str) -> Optional[dict | list]:
        """HTTP GET with error handling. Returns parsed JSON or None."""
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                remaining = resp.headers.get("X-RateLimit-Remaining", "60")
                try:
                    self._rate_remaining = int(remaining)
                except ValueError:
                    pass
                if self._rate_remaining < 10:
                    print(f"[GitHubMCP] ⚠ Rate limit low: {self._rate_remaining} requests remaining")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                print(f"[GitHubMCP] Rate limited or forbidden ({e.code}): {url}")
                return None
            print(f"[GitHubMCP] HTTP error {e.code}: {url}")
            return None
        except Exception as ex:
            print(f"[GitHubMCP] Request error: {ex}")
            return None

    @staticmethod
    def _username_from_url(url: str) -> str:
        """Extract GitHub username from a profile URL."""
        url = url.strip().rstrip("/")
        m = re.search(r"github\.com/([^/?\s]+)", url)
        if m:
            return m.group(1)
        # Maybe the user pasted the username directly
        if "/" not in url and "." not in url:
            return url
        return ""

    @staticmethod
    def _skill_keywords(skill: str) -> list[str]:
        """Generate keyword variants for a skill name."""
        s = skill.lower().strip()
        variants = {s}
        # Common aliases
        aliases = {
            "python":       ["python", "py"],
            "javascript":   ["javascript", "js", "node"],
            "typescript":   ["typescript", "ts"],
            "react":        ["react", "reactjs", "react.js"],
            "vue":          ["vue", "vuejs", "vue.js"],
            "angular":      ["angular", "angularjs"],
            "fastapi":      ["fastapi", "fast-api"],
            "django":       ["django"],
            "flask":        ["flask"],
            "node":         ["node", "nodejs", "node.js", "express"],
            "kubernetes":   ["kubernetes", "k8s", "kubectl", "helm"],
            "docker":       ["docker", "dockerfile", "compose"],
            "terraform":    ["terraform", "tf"],
            "postgresql":   ["postgresql", "postgres", "psql"],
            "mongodb":      ["mongodb", "mongo"],
            "redis":        ["redis"],
            "graphql":      ["graphql", "gql"],
            "rust":         ["rust"],
            "go":           ["golang", "go"],
            "java":         ["java", "spring", "springboot"],
            "kotlin":       ["kotlin"],
            "swift":        ["swift"],
            "machine learning": ["ml", "machine-learning", "machinelearning"],
            "deep learning":    ["dl", "deep-learning", "deeplearning"],
        }
        for key, kws in aliases.items():
            if s in kws or s == key:
                variants.update(kws)
        return list(variants)

    @staticmethod
    def _score_repo_relevance(repo: dict, skill_keywords: list[str]) -> int:
        """
        Score how relevant a repo is for a given skill.
        Higher is more relevant.
        """
        score = 0
        name        = (repo.get("name") or "").lower()
        description = (repo.get("description") or "").lower()
        language    = (repo.get("language") or "").lower()
        topics      = [t.lower() for t in (repo.get("topics") or [])]

        for kw in skill_keywords:
            kw = kw.lower()
            if kw == language:
                score += 3
            if kw in name:
                score += 2
            if kw in description:
                score += 2
            if kw in topics:
                score += 2
            # Partial match in longer names (e.g. "fastapi" in "fastapi-backend")
            if len(kw) > 3 and kw in name.replace("-", "").replace("_", ""):
                score += 1

        return score

    # ── Public API ────────────────────────────────────────────────────

    def get_repos(self, username: str) -> list[dict]:
        """Fetch up to _REPO_FETCH_LIMIT public repos for a user."""
        url  = f"{_GITHUB_API}/users/{username}/repos"
        url += f"?per_page={_REPO_FETCH_LIMIT}&sort=pushed&type=owner"
        data = self._get(url)
        if not isinstance(data, list):
            return []
        return data

    def get_languages(self, username: str, repo_name: str) -> dict:
        """Fetch language breakdown for a repository."""
        url  = f"{_GITHUB_API}/repos/{username}/{repo_name}/languages"
        data = self._get(url)
        return data if isinstance(data, dict) else {}

    def get_readme(self, username: str, repo_name: str) -> str:
        """Fetch and decode README for a repository. Returns first _README_MAX_CHARS chars."""
        url  = f"{_GITHUB_API}/repos/{username}/{repo_name}/readme"
        data = self._get(url)
        if not data or not isinstance(data, dict):
            return ""
        try:
            content = data.get("content", "")
            # GitHub returns base64-encoded content with newlines
            decoded = base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
            return decoded[:_README_MAX_CHARS]
        except Exception:
            return ""

    def collect_evidence(
        self,
        github_url:     str,
        target_skills:  list[str],
    ) -> GitHubEvidence:
        """
        Main entry point: collect structured GitHub evidence for a candidate.

        Steps:
          1. Extract username from URL
          2. Fetch repo list
          3. For each repo: score relevance against target skills
          4. Fetch languages + README for top relevant repos (up to _README_FETCH_LIMIT)
          5. Return GitHubEvidence with GitHubRepo objects

        Args:
            github_url:    Candidate-provided GitHub profile URL
            target_skills: JD required skills to look for
        """
        username = self._username_from_url(github_url)
        if not username:
            return GitHubEvidence(
                github_url=github_url,
                fetch_error=f"Could not extract GitHub username from URL: '{github_url}'",
            )

        print(f"[GitHubMCP] Fetching evidence for @{username} ({len(target_skills)} skills)")

        raw_repos = self.get_repos(username)
        if not raw_repos:
            return GitHubEvidence(
                github_username=username,
                github_url=github_url,
                fetch_error=f"No public repositories found for @{username}. "
                            "Account may be private or username may be incorrect.",
                total_repos=0,
            )

        print(f"[GitHubMCP] @{username}: {len(raw_repos)} repos fetched")

        # Build keyword set for all target skills
        all_keywords: list[list[str]] = [self._skill_keywords(s) for s in target_skills]
        flat_keywords = [kw for kws in all_keywords for kw in kws]

        # Score each repo against all skills collectively
        scored = []
        for repo in raw_repos:
            score = self._score_repo_relevance(repo, flat_keywords)
            scored.append((score, repo))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Fetch detailed evidence for top relevant repos
        github_repos: list[GitHubRepo] = []
        readme_count = 0

        for score, repo in scored:
            repo_name   = repo.get("name", "")
            description = repo.get("description") or ""
            language    = repo.get("language") or ""
            topics      = repo.get("topics") or []
            pushed_at   = repo.get("pushed_at") or ""

            # Always include top-scored repos; skip completely irrelevant ones
            if score == 0 and len(github_repos) >= 5:
                continue

            languages = {}
            readme    = ""

            if score > 0 and readme_count < _README_FETCH_LIMIT:
                languages    = self.get_languages(username, repo_name)
                readme       = self.get_readme(username, repo_name)
                readme_count += 1

            github_repos.append(GitHubRepo(
                name           = repo_name,
                description    = description,
                language       = language,
                languages      = languages,
                readme_excerpt = readme,
                topics         = topics,
                pushed_at      = pushed_at,
            ))

        print(f"[GitHubMCP] @{username}: {len(github_repos)} repos processed, "
              f"{readme_count} READMEs fetched")

        return GitHubEvidence(
            github_username = username,
            github_url      = github_url,
            repos           = github_repos,
            fetch_error     = "",
            total_repos     = len(raw_repos),
        )

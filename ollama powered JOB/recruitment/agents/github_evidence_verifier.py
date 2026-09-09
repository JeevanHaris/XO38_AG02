"""
RecruitScreen / ARIA Core — GitHub Evidence Verifier Agent
──────────────────────────────────────────────────────────
Cross-validates resume skill claims against GitHub repository evidence.

Two-step pipeline:
  Step 1 (Python): Keyword-based repo matching — fast, deterministic, no LLM
  Step 2 (Llama 3.2): Contextual assessment of matched repos — understands README

CRITICAL: Absence from GitHub is NOT proof of absence of skill.
  SUPPORTED   — clear, direct GitHub evidence found
  PARTIAL     — weak/indirect evidence (language match only, generic repo name)
  UNVERIFIED  — no GitHub evidence found (NOT "candidate doesn't know X")

The LLM prompt explicitly enforces this distinction.
"""

import json
import re
from typing import Optional

from ..models import (
    Claim, GitHubEvidence, GitHubRepo,
    GitHubVerificationResult, GitHubEvidenceStatus,
)


SYSTEM_PROMPT = """You are a technical evidence analyst for a recruitment system.
Your job is to assess whether GitHub repository evidence supports a candidate's skill claim.

CRITICAL RULE: Absence of GitHub evidence does NOT mean the candidate lacks the skill.
GitHub is a supplementary evidence source only. Be careful and fair.

Output valid JSON only — no markdown, no explanation outside the JSON."""


GITHUB_VERIFICATION_PROMPT = """Assess whether the GitHub evidence supports the candidate's claimed skill.

Skill to assess: {skill}

GitHub Evidence:
---
{evidence_text}
---

Return EXACTLY this JSON:
{{
  "status": "SUPPORTED | PARTIAL | UNVERIFIED",
  "confidence": "HIGH | MEDIUM | LOW",
  "reasoning": "1-2 sentence factual assessment of what the evidence shows (or doesn't show)"
}}

Status rules:
- SUPPORTED: Evidence directly demonstrates the skill (repo uses the technology, README describes usage)
- PARTIAL: Evidence is indirect — e.g. repository language matches but name/README don't clarify usage
- UNVERIFIED: No GitHub evidence found for this skill

NEVER say the candidate doesn't know the skill. Only assess what the GitHub evidence shows.
Output ONLY valid JSON."""


class GitHubEvidenceVerifier:
    """
    Two-step GitHub evidence verifier:
    1. Python keyword matcher (deterministic, fast)
    2. Llama 3.2 contextual assessment (only for repos that pass step 1)
    """

    def __init__(self, gateway, router):
        self.gateway = gateway
        self.router  = router

    # ─── Public API ───────────────────────────────────────────────────

    def verify_all(
        self,
        claims:          list[Claim],
        github_evidence: GitHubEvidence,
    ) -> dict[str, GitHubVerificationResult]:
        """
        Verify all claims against GitHub evidence.

        Returns a dict keyed by jd_skill.
        Skills with no matching repos get UNVERIFIED (not an error).
        """
        if not github_evidence or github_evidence.fetch_error:
            # Graceful degradation — mark all as UNVERIFIED
            results = {}
            for claim in claims:
                skill = claim.jd_skill or claim.skill
                results[skill] = GitHubVerificationResult(
                    skill   = skill,
                    status  = GitHubEvidenceStatus.UNVERIFIED,
                    reasoning = github_evidence.fetch_error if github_evidence else "No GitHub evidence available.",
                )
            return results

        results = {}
        for claim in claims:
            skill = claim.jd_skill or claim.skill
            if not skill:
                continue
            result = self.verify(skill, github_evidence)
            results[skill] = result

        return results

    def verify(
        self,
        skill:           str,
        github_evidence: GitHubEvidence,
    ) -> GitHubVerificationResult:
        """
        Verify a single skill against GitHub evidence.
        Step 1: Python keyword matching → find candidate repos
        Step 2: Llama 3.2 contextual assessment (only if repos found)
        """
        # Step 1: Keyword matching
        matching_repos = self._keyword_match(skill, github_evidence.repos)

        if not matching_repos:
            return GitHubVerificationResult(
                skill     = skill,
                status    = GitHubEvidenceStatus.UNVERIFIED,
                confidence = "LOW",
                reasoning = (
                    f"No GitHub repositories with evidence of '{skill}' were identified. "
                    f"Note: absence from GitHub does not indicate absence of the skill."
                ),
            )

        # Step 2: LLM contextual assessment
        evidence_text = self._format_evidence(skill, matching_repos)
        return self._llm_assess(skill, matching_repos, evidence_text)

    # ─── Step 1: Python Keyword Matcher ──────────────────────────────

    def _keyword_match(
        self,
        skill: str,
        repos: list[GitHubRepo],
    ) -> list[GitHubRepo]:
        """
        Find repos where there is any evidence of the skill.
        Uses: language, repo name, description, topics, README.
        """
        keywords = self._skill_keywords(skill)
        matching = []

        for repo in repos:
            if self._repo_has_evidence(repo, keywords):
                matching.append(repo)

        return matching

    @staticmethod
    def _skill_keywords(skill: str) -> list[str]:
        """Normalize skill name to a list of keyword variants."""
        s = skill.lower().strip()
        base_variants = {s, s.replace(" ", "-"), s.replace(" ", "_"), s.replace(" ", "")}

        # Common tech aliases
        alias_map = {
            "python":           ["python", "py"],
            "javascript":       ["javascript", "js", "node", "nodejs"],
            "typescript":       ["typescript", "ts"],
            "react":            ["react", "reactjs", "react.js"],
            "vue":              ["vue", "vuejs"],
            "angular":          ["angular", "angularjs"],
            "fastapi":          ["fastapi", "fast-api", "fast_api"],
            "django":           ["django"],
            "flask":            ["flask"],
            "node":             ["node", "nodejs", "express"],
            "kubernetes":       ["kubernetes", "k8s", "kubectl", "helm"],
            "docker":           ["docker", "dockerfile", "compose", "container"],
            "terraform":        ["terraform", "tf"],
            "postgresql":       ["postgresql", "postgres", "psql", "pg"],
            "mysql":            ["mysql", "sql"],
            "mongodb":          ["mongodb", "mongo"],
            "redis":            ["redis"],
            "graphql":          ["graphql", "gql"],
            "rust":             ["rust"],
            "go":               ["golang", "go"],
            "java":             ["java", "spring", "springboot"],
            "kotlin":           ["kotlin"],
            "swift":            ["swift", "ios"],
            "machine learning": ["ml", "machine-learning", "machinelearning", "sklearn", "scikit"],
            "deep learning":    ["dl", "deep-learning", "deeplearning", "tensorflow", "pytorch", "torch"],
            "aws":              ["aws", "amazon", "lambda", "s3", "ec2"],
            "gcp":              ["gcp", "google-cloud"],
            "azure":            ["azure", "microsoft"],
            "ci/cd":            ["cicd", "ci-cd", "github-actions", "jenkins", "gitlab-ci"],
        }

        for key, kws in alias_map.items():
            if s in kws or s == key:
                base_variants.update(kws)

        return list(base_variants)

    @staticmethod
    def _repo_has_evidence(repo: GitHubRepo, keywords: list[str]) -> bool:
        """Check if a repository has any evidence of the target skill."""
        name_clean = repo.name.lower().replace("-", " ").replace("_", " ")
        desc_clean = (repo.description or "").lower()
        lang_clean = (repo.language or "").lower()
        readme_clean = (repo.readme_excerpt or "").lower()
        topics_clean = " ".join(t.lower() for t in (repo.topics or []))
        lang_keys_clean = " ".join(k.lower() for k in (repo.languages or {}).keys())

        combined = f"{name_clean} {desc_clean} {lang_clean} {readme_clean} {topics_clean} {lang_keys_clean}"

        for kw in keywords:
            kw = kw.lower()
            if kw in combined:
                return True

        return False

    # ─── Step 2: Llama 3.2 Contextual Assessment ─────────────────────

    def _llm_assess(
        self,
        skill:          str,
        matching_repos: list[GitHubRepo],
        evidence_text:  str,
    ) -> GitHubVerificationResult:
        """Send matched repo evidence to Llama 3.2 for contextual assessment."""
        decision = self.router.route(
            f"github evidence assessment for {skill}",
            task_type_hint="basic_evidence_check",
        )

        prompt = GITHUB_VERIFICATION_PROMPT.format(
            skill         = skill,
            evidence_text = evidence_text,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

        try:
            response = self.gateway.call(
                decision.model, messages, provider=decision.provider
            )
            raw  = (response.content or "").strip()
            data = self._parse_json(raw)

            # Parse status
            raw_status = data.get("status", "UNVERIFIED").upper().strip()
            try:
                status = GitHubEvidenceStatus(raw_status)
            except ValueError:
                status = GitHubEvidenceStatus.UNVERIFIED

            confidence = str(data.get("confidence", "MEDIUM")).upper()
            if confidence not in ("HIGH", "MEDIUM", "LOW"):
                confidence = "MEDIUM"

            reasoning = str(data.get("reasoning", "")).strip()

            repo_names = [r.name for r in matching_repos]
            print(f"[GitHubVerifier] {skill}: {status.value} ({confidence}) "
                  f"— {len(matching_repos)} repo(s): {repo_names}")

            return GitHubVerificationResult(
                skill          = skill,
                status         = status,
                confidence     = confidence,
                evidence_repos = repo_names,
                reasoning      = reasoning,
            )

        except Exception as e:
            print(f"[GitHubVerifier] LLM fallback for '{skill}': {e}")
            # Python fallback: check if any repo has README evidence (stronger than name-only)
            has_readme_evidence = any(
                r.readme_excerpt and any(
                    kw in r.readme_excerpt.lower()
                    for kw in self._skill_keywords(skill)
                )
                for r in matching_repos
            )
            status = GitHubEvidenceStatus.SUPPORTED if has_readme_evidence else GitHubEvidenceStatus.PARTIAL
            return GitHubVerificationResult(
                skill          = skill,
                status         = status,
                confidence     = "LOW",
                evidence_repos = [r.name for r in matching_repos],
                reasoning      = f"Found in {len(matching_repos)} repo(s) (fallback heuristic).",
            )

    # ─── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _format_evidence(skill: str, repos: list[GitHubRepo]) -> str:
        """Format matched repos into a readable block for the LLM."""
        lines = [f"Target skill: {skill}", f"Matching repositories ({len(repos)} found):\n"]
        for repo in repos[:5]:   # Cap at 5 repos to keep prompt short
            lines.append(f"Repository: {repo.name}")
            if repo.description:
                lines.append(f"  Description: {repo.description}")
            if repo.language:
                lines.append(f"  Primary language: {repo.language}")
            if repo.languages:
                lang_str = ", ".join(f"{k} ({v:,} bytes)" for k, v in list(repo.languages.items())[:4])
                lines.append(f"  Languages: {lang_str}")
            if repo.topics:
                lines.append(f"  Topics: {', '.join(repo.topics[:6])}")
            if repo.readme_excerpt:
                excerpt = repo.readme_excerpt[:400].replace("\n", " ")
                lines.append(f"  README (excerpt): {excerpt}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}

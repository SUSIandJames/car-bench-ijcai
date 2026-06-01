Rules
Official competition rules and policies. Please read carefully before submitting.

Table of Contents
Eligibility
Registration
Allowed Approaches
Prohibited Behaviors
Submission Mechanics
Code Release
Technical Reports
Data Use
1. Eligibility
The competition is open to individuals and teams worldwide.
There is no minimum or maximum team size, though we recommend 1–5 members.
Participants may be affiliated with academic institutions, industry organizations, or be independent researchers.
An individual may be a member of multiple teams. However, if two submissions from teams sharing a member are substantially overlapping, the worse-performing submission will be excluded from award eligibility.
2. Registration
Teams must register before their first submission to the official leaderboard.
Registration is preferably submitted through the official Google Form. If Google Forms is inaccessible from a participant’s location, teams may register by email using the fallback instructions on the registration page.
Registration requires: team name, institution or organization, country or region, contact person name, contact email, team member names, optional team member emails, and track selection (Open, Cerebras Fast-Reasoning with Codex Pro, or both).
Track 2 registration additionally requires one ChatGPT-account-linked email for Codex Pro access and a short, non-binding description of the intended submission or innovation idea. Teams that do not want to share a private account should create a dedicated team account before registering.
Track 2 participation is limited to 15 teams because sponsored Codex Pro access is limited.
Registration is open from May 25, 2026.
Teams may update their team members up to 7 days before the final evaluation deadline.
3. Allowed Approaches
We adopt a permissive stance. Any approach is permitted unless explicitly prohibited below. This includes but is not limited to:

Any LLM (proprietary or open-source, any size)
Prompting strategies (system prompts, few-shot, chain-of-thought, self-reflection)
Agentic scaffolding (planning-execution separation, retry logic, verification)
Multi-agent systems (subagents, orchestration, ensemble methods)
Fine-tuning on the provided training data (SFT, RLHF, DPO, etc.)
Retrieval-augmented generation (RAG) over environment data
External knowledge bases or pre-computed lookup tables (provided they do not encode test set answers)
Cerebras Fast-Reasoning with Codex Pro Track: Track 2 submissions must use the Codex Pro / Cerebras Spark setup described in the starter kit. Agents must expose the same dockerized A2A interface as Track 1. Multi-pass reasoning, private planning, self-verification, retries, and ensembles are allowed, but the agent must respect the official time budget and must not exploit evaluator internals. Participation is limited to 15 teams. The time budget will be announced soon.

4. Prohibited Behaviors
The following are strictly prohibited and will result in disqualification:

Hard-coding answers: Encoding specific test-set answers or lookup tables that map task descriptions to solutions.
Exploiting evaluation infrastructure: Reverse-engineering, probing, or exploiting vulnerabilities in the evaluation system. This includes self-evaluating against the task-level metrics (e.g., checking subscores and re-prompting the LLM to correct failures before the official evaluation scores the run). Agents must produce genuine responses, not iteratively repair them against the scoring criteria.
Probing the hidden test set: Any attempt to extract, infer, or reconstruct hidden test set tasks through the evaluation API or any other channel.
Overlapping submissions: Teams sharing a member may not submit substantially overlapping agents. If detected, the worse-performing submission will be excluded from award eligibility.
5. Submission Mechanics
Submissions are dockerized A2A-compatible agents built from the starter kit interface.
Participants submit a registered GHCR image reference plus scenario/config details. Digest-pinned images are preferred for reproducibility.
Submission configs should list required environment variable or secret names, but must never contain secret values.
Development validation: Participants may run public local, Docker, and GHCR scenario configs themselves before submitting.
Hidden test set: Two official evaluation rounds. 1st round (Jul 10): each team gets one submission and receives scores. Final (Jul 19): each team gets one submission. Final rankings are determined from the Jul 19 round.
Technical report: A 4-page technical report (IJCAI format, excluding references) is required for award eligibility. Deadline: July 26, 2026 (AoE).
More details soon. The exact submission form and required metadata fields will be published before the first official evaluation round.
6. Code Release
Participants are expected to release their code under a permissive open-source license (MIT, Apache 2.0, or equivalent) upon conclusion of the competition.
Code must be sufficient for independent reproduction of reported results.
7. Technical Reports
A 4-page technical report (IJCAI format, excluding references) is required for award eligibility.
Deadline: July 26, 2026 (AoE).
Reports should describe the approach, design decisions, ablation results, and lessons learned.
Reports will be published as non-archival proceedings on the competition website. ArXiv submission is encouraged but not required.
Submission portal link will be added here when available.
8. Data Use
The starter kit and public CAR-bench data are released under the MIT License.
Participants may use the training and dev data for other research, provided they cite the original paper.
The hidden test set will not be released during the competition. Post-competition release will be announced separately.
Results and rankings will be made publicly available on the competition website after the final evaluation.
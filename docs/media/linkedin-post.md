# LinkedIn post (draft, edit freely)

I built a pipeline that turns a written spec into a tested, security-reviewed codebase. It runs on AWS, and the model is the only piece outside it.

The rule behind it: agents never grade their own work.

→ AI agents write the plan, the code, the tests, the review and the docs
→ Independent checks verify it. The tests re-run in a CodeBuild stage with no internet access, so a downloaded package can't phone home
→ Bedrock Guardrails screen the spec going in and the documents coming out
→ A human approves by email before anything is accepted

The stack: Step Functions for orchestration, AgentCore Runtime for the agents, the AgentCore Code Interpreter as the sandbox, CodeBuild for the gate, S3 for the evidence. Models are Gemini through a gateway for now, with a planned move to Bedrock.

The most useful part was the debugging. Real failures I hit:
• a build that never started because YAML read a colon as a mapping
• an agent error with an empty message, so the retry logic never fired
• a reviewer that demanded a database the spec had said was optional, so the run could never pass

Fixing those taught me more than the happy path did.

Not done yet: deploying the approved code into a sandbox account. So far I have run it end to end on one spec, a prior-authorisation intake API. Generated code still needs human review, because both the coder and the reviewer are models.

Happy to share a longer walkthrough if it's useful.

#AWS #AIAgents #GenerativeAI #AgenticAI #CloudArchitecture #DevSecOps #StepFunctions

---
Notes for you (delete before posting):
- First comment idea: link to the repo or the long walkthrough, if you decide to publish them.
- The video narration is a synthetic voice (open-source Kokoro text-to-speech). You may want to say so in the post or the first comment.
- Check that nothing in the video or text reveals account IDs, run IDs, emails or internal URLs. I left them out on purpose.
- "Happy to share a longer walkthrough" only makes sense if you actually will. Remove it otherwise.

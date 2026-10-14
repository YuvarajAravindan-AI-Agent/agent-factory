# agent-factory-walkthrough: narration script


## 1. Agent Factory

- This is Agent Factory: a pipeline that turns a written specification into a tested, security-reviewed codebase, using mostly AWS services.
- Only the language model comes from outside AWS. Today that is Google's Gemini, reached through a gateway, with a planned switch to Amazon Bedrock after December sixteenth, twenty twenty-six.
- In this video you will learn what every piece does, why it is built that way, how to run it yourself, and which problems we hit while getting it working.

## 2. The core idea: never let agents grade their own work

- The idea fits in one sentence: let AI agents do the writing, but never let them grade their own work.
- So three kinds of actors share the job. Agents write the plan, the code, the tests, the review and the documentation.
- Deterministic checks verify the result. After an agent finishes, the runtime re-runs the tests itself, and a separate build job runs them again with no internet access.
- And a person makes the final call through an approval email. Approving does not deploy anything yet; deployment is a later phase.

## 3. The AWS building blocks

- Here are the building blocks. Step Functions is the conductor: it runs the pipeline, records every run, and puts a hard limit on every retry loop.
- Each agent runs on AgentCore Runtime in its own microVM, built with the Strands agent framework. Commands the agent runs go to the AgentCore Code Interpreter sandbox, which has no internet and no AWS credentials.
- CodeBuild is the independent test gate, and Bedrock Guardrails screens the spec going in and the documents coming out.
- S3 keeps the evidence for every run. A small Lambda function, an SNS email and a task token handle human approval.
- And the model is the one outside piece: a Secrets Manager token for a Gemini gateway today, switching to Bedrock later by editing a single file.

## 4. You write the spec: it is the only prompt

- You never chat with the agents. The spec is the only prompt. It is a markdown file with context, functional requirements, non-functional requirements and acceptance tests.
- There are four templates, one for each agent type: task, workflow, multi-agent and autonomous. Copy one and replace every placeholder with real requirements.
- The worked example is a prior-authorisation intake service for a health plan. It validates requests, applies coverage rules, and writes an audit log for every decision.
- Two rules. Use fake data only. And write your security requirements into the spec, because the reviewer checks the code against what the spec asks for.

## 5. The pipeline, end to end

- A run starts when you upload the spec to S3 and start a Step Functions execution with a run identifier.
- First the input guardrail scans the spec for prompt injection and sensitive identifiers. If it blocks, the run stops right here.
- Then three agents work in turn. The Architect plans, the Coder writes the code, and the Tester adds tests and runs them.
- Two CodeBuild stages then verify the tests independently of any agent.
- The Reviewer checks security and compliance. The Docs agent writes the README and runbook, and the output guardrail scans what was written.
- Finally the code is zipped for download, and a human approves or rejects by email.

## 6. Architect, Coder and Tester

- The Architect reads the spec and writes a plan and an architecture note, including trust boundaries and which regulation clauses apply. It writes no application code.
- The Coder implements that plan: application code, pinned requirements, starter tests, structured audit logging and input validation.
- The Tester makes sure every acceptance criterion has a test, adds edge cases, and runs pytest. It may fix a genuine app bug, but it must never delete or weaken a test.
- The Architect and Coder use the strong model. The Tester, Reviewer and Docs use the faster, cheaper one.

## 7. The fix loop

- If the tests are red, the pipeline does not just try again. The result comes from the runtime running pytest itself, not from what the agent says.
- A Fixer agent receives the failing output and looks for the root cause.
- It must make the smallest correct fix, and it may not delete or weaken tests. On the second attempt it switches to the strong model.
- Then the Tester runs again. After three failed rounds, the run stops with a TestsFailed error, so a loop can never run forever.

## 8. Two-stage CodeBuild gate

- The most important safety feature is a two-stage build. Stage one is allowed to use the internet, but only to download pre-built wheels, so no package setup script ever runs.
- Stage two runs in a private network with no internet gateway and no NAT, only an S3 endpoint. It installs from those wheels and runs the tests.
- Why split it? A downloaded package cannot phone home from the stage that runs the code, and the pass or fail comes from a build job, not from a model's claim.
- If a build fails, the Fixer gets one attempt using the build log, then the run goes back to the Tester. A second build failure ends the run.

## 9. The Reviewer and the one fix round

- The Reviewer reads the code without editing it. It checks the OWASP Top 10, threats at each trust boundary, secrets in code, personal health data in logs, audit trails, input validation and dependencies.
- It writes a review document and a machine-readable file that counts the critical and high findings.
- If any critical or high finding exists, the Fixer gets exactly one round. Then everything is re-tested and re-reviewed. If findings remain, the run stops.
- Early on this gate blocked runs for the wrong reasons. The reviewer now reads the spec, must quote the code it criticises, and lists limits the spec accepts, like an in-memory store, as accepted instead of blocking.

## 10. Docs, output guardrail, package and approval

- The Docs agent writes a README and a runbook that match the code. It is not allowed to change code.
- The output guardrail scans those documents for sensitive identifiers before anything is packaged.
- The package step zips the workspace and creates a download link valid for seven days.
- Then an email goes out with the link, plus approve and reject buttons. Each carries a task token. Opening a link only shows a confirmation page, so an email scanner can never approve by accident. The run waits seven days, then expires.

## 11. How one agent step really works

- Here is the trick that lets agents run for many minutes. Step Functions pauses at the step and calls a small Lambda function, passing a task token.
- The Lambda starts the agent runtime with a fresh session identifier and returns immediately.
- The runtime does the work in a background thread, so Lambda's fifteen minute limit never applies. Each role and attempt gets its own microVM.
- Inside, the agent's commands run in the Code Interpreter sandbox, with no internet and no AWS credentials.
- When done, the runtime uses the token to tell Step Functions it succeeded, or failed with the full error chain and traceback. Then the pipeline moves on.

## 12. Running it yourself

- To run it yourself, first copy a template and write your spec.
- If you changed any agent code, build the package and apply the Terraform. The package step needs the uv tool installed.
- Then start a run with the run script. It uploads your spec and prints a run identifier.
- Watch progress with the Step Functions execution history. The agent logs and the generated code are in the run's folder in S3. A full run took roughly half an hour in our latest test.

## 13. What we debugged to get it working

- Now the part worth learning from: what actually broke. First, a build never started because a command contained a colon followed by a space, which YAML reads as a mapping. Quoting it fixed that.
- Second, a failure had no message. The agent library wrapped a network error with empty text, so the keyword-based retry never matched. Retries now check the error type and chain, and failures report a full traceback.
- Third, the review gate never converged. The reviewer demanded a database although the spec allowed an in-memory store, and it reported issues that were already fixed. It is now spec-aware and must quote the code.
- Fourth, the Fixer was working blind. It only received the last fifteen hundred characters of the reviewer's chat reply. It now reads the full findings file.
- And two operational lessons: a single sign-on login expires, and a secret pasted into a chat must be deleted and replaced immediately.
- With those fixes, the final run passed review with no blocking findings, and the generated service's sixty-eight tests passed on a local machine too.

## 14. What is not done yet

- Be clear about what is not done. Deployment is Phase 2: approval currently just ends the run. Nothing is deployed into a sandbox account yet.
- The switch from Gemini to Bedrock is planned but untested, and probably needs extra permissions on the runtime role.
- Generated code varies from run to run. One run created its audit log with default file permissions, so every output still needs checking.
- Only one spec has been run end to end so far, and the fixes are on a branch that is not yet merged.
- Finally, both the coder and the reviewer are models. They make mistakes, so a human review of the result still matters.

## 15. How to study this project

- To study this, start with the pipeline state machine. It shows every step, retry and stop in one file.
- Then read the agent roles and the entry point to see the prompts, the retry logic, and how an agent reports back.
- After that, the Lambda functions, the two build specs, and the Terraform that creates the no-internet network.
- Finally read the example spec, then copy a template, run one spec yourself, and read every step's log in S3. That is the fastest way to learn it.
